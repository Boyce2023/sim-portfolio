# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""
模拟盘交易执行器

用法:
  uv run scripts/execute_trade.py buy   --account us --ticker NVDA --shares 10 --reason "AI infra base position"
  uv run scripts/execute_trade.py sell  --account us --ticker NVDA --shares 5  --reason "target reached"
  uv run scripts/execute_trade.py sell  --account cn --ticker 002929 --all     --reason "stop loss"
  uv run scripts/execute_trade.py short --account us --ticker MSTR --shares 20 --reason "BTC overexposure thesis"
  uv run scripts/execute_trade.py cover --account us --ticker MSTR --shares 20 --reason "target reached"

  # Options
  uv run scripts/execute_trade.py option --account us --ticker MU --strategy put_credit_spread \\
    --contracts 5 --short-strike 900 --long-strike 870 --expiry 2026-06-27 --premium 4000 --reason "IV 99%"
  uv run scripts/execute_trade.py option --account us --ticker VST --strategy covered_call \\
    --contracts 8 --short-strike 175 --expiry 2026-07-18 --premium 3200 --reason "income"
  uv run scripts/execute_trade.py close_option --account us --id OPT-001 --close-premium -2000 --reason "50% profit"
  uv run scripts/execute_trade.py close_option --account us --id OPT-001 --expire --reason "expired OTM"

  # Futures
  uv run scripts/execute_trade.py future --account us --product MES --direction long --contracts 4 --reason "beta bridge"
  uv run scripts/execute_trade.py close_future --account us --id FUT-001 --reason "positions built"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from core.config import ATR_STOP, SHORT_STOP_LOSS_PCT, ASTOCK_HARD_STOP_PCT, ASTOCK_TWO_STAGE_EXIT

AUDIT_TRAIL_DIR = Path(__file__).parent.parent / "audit-trail"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PORTFOLIO_PATH = Path(__file__).parent.parent / "portfolio_state.json"
CN_LOT_SIZE = 100  # A股最小交易单位
MAX_SINGLE_POSITION_PCT = 0.35  # 单一持仓上限 35% (A+级最高, v7.0)
MAX_SHORT_POSITION_PCT = 0.10   # 单一空头上限 10%
MAX_GROSS_EXPOSURE = 3000000    # 美股总敞口上限 $3M (2x on $1.5M capital)
# SHORT_STOP_LOSS_PCT imported from core.config
CN_ACCOUNT_KEY = "a_share"
US_ACCOUNT_KEY = "us"

# A股交易频率约束 — 从 core/config 读取，保持单一来源
try:
    from core.config import (ASTOCK_MAX_POSITIONS, ASTOCK_MAX_POSITIONS_FLEX,
                             TRADING_BUDGET)
    CN_MAX_POSITIONS = ASTOCK_MAX_POSITIONS           # 软目标 5只 (WARN)
    CN_MAX_POSITIONS_FLEX = ASTOCK_MAX_POSITIONS_FLEX # 硬上限 7只 (BLOCK)
    CN_MAX_DAILY_NEW_POSITIONS = TRADING_BUDGET["daily_new_positions"]
    CN_MAX_WEEKLY_TRADES = TRADING_BUDGET["weekly_total_trades"]
except ImportError:
    CN_MAX_POSITIONS = 5
    CN_MAX_POSITIONS_FLEX = 7
    CN_MAX_DAILY_NEW_POSITIONS = 2
    CN_MAX_WEEKLY_TRADES = 8

# v7.0 SABCT评级仓位上限 (strategy.md §2.2)
SABCT_LIMITS: dict[str, float] = {
    "A+": 0.35,
    "A":  0.25,
    "A-": 0.20,
    "B+": 0.15,
    "B":  0.12,
    "B-": 0.10,
}
VALID_CN_GRADES = set(SABCT_LIMITS.keys())  # 无C级/S级/T级

TZ_BEIJING = timezone(timedelta(hours=8))

# OTC / special tickers that need yfinance remapping
YF_TICKER_MAP: dict[str, str] = {
    "SPUT": "SRUUF",    # Sprott Uranium Trust trades OTC as SRUUF
}

# Futures product specifications
FUTURES_SPECS: dict[str, dict] = {
    "ES":  {"multiplier": 50,   "margin": 15000, "name": "E-mini S&P 500",       "yf": "ES=F"},
    "MES": {"multiplier": 5,    "margin": 1800,  "name": "Micro E-mini S&P 500", "yf": "ES=F"},
    "NQ":  {"multiplier": 20,   "margin": 20000, "name": "E-mini Nasdaq 100",    "yf": "NQ=F"},
    "MNQ": {"multiplier": 2,    "margin": 2200,  "name": "Micro E-mini Nasdaq",  "yf": "NQ=F"},
    "YM":  {"multiplier": 5,    "margin": 9000,  "name": "E-mini Dow",           "yf": "YM=F"},
    "MYM": {"multiplier": 0.5,  "margin": 1100,  "name": "Micro E-mini Dow",     "yf": "YM=F"},
    "VX":  {"multiplier": 1000, "margin": 10000, "name": "VIX Futures",          "yf": "VX=F"},
}

VALID_OPTION_STRATEGIES = {
    "long_call", "long_put", "short_call", "short_put",
    "covered_call", "cash_secured_put",
    "bull_call_spread", "bear_put_spread",
    "put_credit_spread", "call_credit_spread",
    "straddle", "strangle", "iron_condor",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(TZ_BEIJING).isoformat(timespec="seconds")


def load_portfolio() -> dict:
    with open(PORTFOLIO_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_portfolio_atomic(state: dict) -> None:
    """写 tmp 文件再 rename，保证原子性。"""
    dir_ = PORTFOLIO_PATH.parent
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp", prefix="portfolio_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, PORTFOLIO_PATH)
        except Exception:
            # 清理 tmp
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        raise RuntimeError(f"JSON写入失败，回滚: {e}") from e


def get_account_key(account_arg: str) -> str:
    mapping = {
        "us": US_ACCOUNT_KEY,
        "cn": CN_ACCOUNT_KEY,
        "a_share": CN_ACCOUNT_KEY,
    }
    key = mapping.get(account_arg.lower())
    if key is None:
        sys.exit(f"[ERROR] 未知账户 '{account_arg}'，支持: us / cn")
    return key


def is_cn_ticker(ticker: str) -> bool:
    return ticker.isdigit() and len(ticker) == 6


def yf_cn_ticker(ticker: str) -> str:
    if ticker.startswith("6"):
        return ticker + ".SS"
    return ticker + ".SZ"  # 0开头 / 3开头 → 深交所


def fetch_price(ticker: str, account_key: str) -> float:
    """获取实时价格（含重试）；失败则 sys.exit。"""
    import time
    if account_key == CN_ACCOUNT_KEY:
        yf_sym = yf_cn_ticker(ticker)
    else:
        # Apply OTC remapping (e.g. SPUT → SRUUF)
        yf_sym = YF_TICKER_MAP.get(ticker.upper(), ticker.upper())

    retries = 3
    last_error = ""
    for attempt in range(retries):
        try:
            t = yf.Ticker(yf_sym)
            info = t.fast_info
            price = info.last_price
            if price is None or price <= 0:
                # 尝试 history fallback
                hist = t.history(period="1d", auto_adjust=True)
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            if price and price > 0:
                return round(float(price), 4)
            last_error = "no valid price"
        except Exception as e:
            last_error = str(e)
        if attempt < retries - 1:
            time.sleep(1.5)

    sys.exit(f"[ERROR] 无法获取 {ticker} ({yf_sym}) 的有效价格（{last_error}），交易取消。")


def find_position(positions: list, ticker: str) -> tuple[int, dict | None]:
    """返回 (index, position_dict)，未找到返回 (-1, None)。"""
    for i, pos in enumerate(positions):
        if pos.get("ticker") == ticker:
            return i, pos
    return -1, None


def _resolve_name(state: dict, ticker: str, account_key: str) -> str:
    """三层fallback取标的名称: 持仓 → watchlist → yfinance。永远不返回空。"""
    for pos in state["accounts"].get(account_key, {}).get("positions", []):
        if pos.get("ticker") == ticker and pos.get("name"):
            return pos["name"]
    for pos in state["accounts"].get(account_key, {}).get("short_positions", []):
        if pos.get("ticker") == ticker and pos.get("name"):
            return pos["name"]

    watchlist_path = PORTFOLIO_PATH.parent / "watchlist_config.json"
    try:
        with open(watchlist_path, encoding="utf-8") as f:
            wl = json.load(f)
        list_key = "cn_watchlist" if account_key == CN_ACCOUNT_KEY else "us_watchlist"
        for item in wl.get(list_key, []):
            if item.get("ticker") == ticker and item.get("name"):
                return item["name"]
    except Exception:
        pass

    try:
        yf_sym = yf_cn_ticker(ticker) if account_key == CN_ACCOUNT_KEY else YF_TICKER_MAP.get(ticker.upper(), ticker.upper())
        info = yf.Ticker(yf_sym).info
        for key in ("shortName", "longName"):
            if info.get(key):
                return info[key]
    except Exception:
        pass

    return ticker


# ---------------------------------------------------------------------------
# v7.0 Trade-frequency helpers (A股 only)
# ---------------------------------------------------------------------------

def _get_week_start(date_str: str) -> str:
    """返回给定日期所在自然周的周一日期字符串 (YYYY-MM-DD)。"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    monday = d - timedelta(days=d.weekday())
    return monday.strftime("%Y-%m-%d")


def _count_daily_new_cn_positions(trade_log: list, today: str) -> int:
    """计算今日A股新建仓笔数 (action=buy 且 该ticker在今日之前无持仓记录)。"""
    # 今日已出现过的买入ticker
    today_buys: set[str] = set()
    # 今日之前曾买过的ticker（视为旧仓加仓，不计入新建仓）
    existing_tickers: set[str] = set()
    for entry in trade_log:
        if entry.get("account") != CN_ACCOUNT_KEY:
            continue
        entry_date = entry.get("date", "")[:10]
        if entry.get("action") == "buy":
            if entry_date < today:
                existing_tickers.add(entry.get("ticker", ""))
            elif entry_date == today:
                today_buys.add(entry.get("ticker", ""))
    # 新建仓 = 今日首次买入 且 此前从未买过的ticker
    new_today = today_buys - existing_tickers
    return len(new_today)


def _count_weekly_cn_trades(trade_log: list, today: str) -> int:
    """计算本周A股交易总笔数（每笔trade_log条目计1笔，含买/卖/加仓/减仓）。"""
    week_start = _get_week_start(today)
    count = 0
    for entry in trade_log:
        if entry.get("account") != CN_ACCOUNT_KEY:
            continue
        entry_date = entry.get("date", "")[:10]
        if entry_date >= week_start and entry_date <= today:
            count += 1
    return count


def _check_round_trip_penalty(trade_log: list, account: dict, ticker: str) -> None:
    """
    Round Trip惩罚检查 (v7.0 §4.4):
    若本周对同一标的已执行过一次反向操作（买→卖 或 卖→买），
    则第2次反向操作触发惩罚——发出警告，并在round_trip_penalties字段记录。
    （惩罚生效：下周禁止新建仓，由 pre_session_check 或 compliance_check 执行。）
    """
    today = datetime.now(TZ_BEIJING).strftime("%Y-%m-%d")
    week_start = _get_week_start(today)

    # 本周该ticker的A股交易序列（按时间排序）
    week_trades = [
        e for e in trade_log
        if e.get("account") == CN_ACCOUNT_KEY
        and e.get("ticker") == ticker
        and e.get("date", "")[:10] >= week_start
    ]

    if len(week_trades) < 1:
        return

    # 统计反向操作次数（buy后有sell，或sell后有buy）
    actions = [e.get("action") for e in week_trades]
    reversals = 0
    for i in range(1, len(actions)):
        prev, curr = actions[i - 1], actions[i]
        if (prev == "buy" and curr == "sell") or (prev == "sell" and curr == "buy"):
            reversals += 1

    if reversals >= 1:
        # 已发生过一次反向——再次反向即为第2次，触发惩罚
        penalties = account.get("round_trip_penalties", [])
        existing = [p for p in penalties if p.get("ticker") == ticker and p.get("week_start") == week_start]
        penalty_count = len(existing) + 1

        if penalty_count >= 2:
            # 记录惩罚并阻断（下周禁止新建仓）
            if "round_trip_penalties" not in account:
                account["round_trip_penalties"] = []
            account["round_trip_penalties"].append({
                "ticker": ticker,
                "week_start": week_start,
                "penalty_level": 2,
                "consequence": "next_week_no_new_positions",
                "recorded_at": now_iso(),
            })
            sys.exit(
                f"[BLOCKED] Round Trip惩罚 (v7.0 §4.4): {ticker} 本周第2次反向操作。\n"
                f"后果: 下周禁止新建仓。本笔交易取消。"
            )
        else:
            # 第1次反向——警告但不阻断
            if "round_trip_penalties" not in account:
                account["round_trip_penalties"] = []
            account["round_trip_penalties"].append({
                "ticker": ticker,
                "week_start": week_start,
                "penalty_level": 1,
                "consequence": "warning",
                "recorded_at": now_iso(),
            })
            print(
                f"[WARN] Round Trip警告 (v7.0 §4.4): {ticker} 本周第1次反向操作。\n"
                f"如再次反向，下周将禁止新建仓。已记录到round_trip_penalties。"
            )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _enrich_position_from_watchlist(ticker: str, account_key: str) -> dict:
    """从watchlist_config.json读取标的信息，填充新建仓位的字段"""
    watchlist_path = PORTFOLIO_PATH.parent / "watchlist_config.json"
    try:
        with open(watchlist_path, encoding="utf-8") as f:
            wl = json.load(f)
        list_key = "cn_watchlist" if account_key == CN_ACCOUNT_KEY else "us_watchlist"
        for item in wl.get(list_key, []):
            if item.get("ticker") == ticker:
                # 支持 conviction_level (v7.0) 和旧版 confidence 字段
                grade = item.get("conviction_level") or item.get("confidence", "")
                catalyst = item.get("next_catalyst", "")
                if isinstance(catalyst, dict):
                    catalyst = catalyst.get("event", "")
                result = {
                    "name": item.get("name", ""),
                    "sector": item.get("sector", ""),
                    "type": item.get("type", ""),
                    "stop_loss": item.get("stop_loss"),
                    "target_1": item.get("target_1"),
                    "target_2": item.get("target_2"),
                    "bear_case": item.get("bear_case", ""),
                    "bear_case_downside": item.get("bear_case_downside_pct", 0) / 100 if item.get("bear_case_downside_pct") else None,
                    "thesis": item.get("thesis", ""),
                    "thesis_short": item.get("thesis", "")[:80] if item.get("thesis") else "",
                    "conviction_level": grade,
                    "next_catalyst": catalyst,
                }
                return {k: v for k, v in result.items() if v is not None and v != ""}
    except Exception:
        pass
    return {}


def validate_buy(account: dict, account_key: str, ticker: str, shares: int, price: float,
                 bear_case_downside: float | None = None,
                 trade_log: list | None = None):
    """
    Validate a buy order. Raises sys.exit on failure.

    v7.0 A股新增检查:
    - SABCT评级必须为 A+/A/A-/B+/B/B-（无C/S/T级）
    - 仓位上限按SABCT分级（35%/25%/20%/15%/12%/10%）
    - 持仓数 ≤ 5只
    - 每日新建仓 ≤ 2笔
    - 每周交易总量 ≤ 8笔
    - Bear case F9 v2: T4>40%硬阻断, T3 25-40%/T2 15-25% 警告

    bear_case_downside: 负数, 如 -0.15 表示 -15%
    trade_log: 完整交易记录（用于频率检查），传入 state["trade_log"]
    """
    currency = account["currency"]
    cost = shares * price
    cash = account["cash"]
    today = datetime.now(TZ_BEIJING).strftime("%Y-%m-%d")

    # ── A股专属检查 ──────────────────────────────────────────────────────────
    if account_key == CN_ACCOUNT_KEY:
        _, existing_pos = find_position(account["positions"], ticker)
        is_new_position = existing_pos is None

        # 1. SABCT评级必须存在且合法（无C级/无waiver）
        enrichment = _enrich_position_from_watchlist(ticker, account_key)
        grade = enrichment.get("conviction_level", "")
        # 也从现有持仓读取 conviction_level（加仓场景）
        if not grade and existing_pos:
            grade = existing_pos.get("conviction_level", "")
        if not grade or grade not in VALID_CN_GRADES:
            invalid_note = f"（当前值: '{grade}'）" if grade else "（未设置）"
            sys.exit(
                f"[BLOCKED] {ticker} 必须先设置SABCT评级 {invalid_note}。\n"
                f"v7.0有效等级: {', '.join(sorted(VALID_CN_GRADES))}。\n"
                f"无C级/S级/T级/waiver机制。无thesis不建仓（strategy.md R3）。交易取消。"
            )

        # 2. 持仓数检查（新建仓时）— 5只软提醒，7只硬拒绝
        if is_new_position:
            current_cn_longs = len([
                p for p in account.get("positions", [])
                if p.get("instrument_type") != "call_option"
            ])
            if current_cn_longs >= CN_MAX_POSITIONS_FLEX:
                sys.exit(
                    f"[BLOCKED] A股持仓已达 {current_cn_longs}/{CN_MAX_POSITIONS_FLEX} 只弹性上限。"
                    f"必须先清仓再建新仓。交易取消。"
                )
            elif current_cn_longs >= CN_MAX_POSITIONS:
                print(
                    f"[WARN] A股持仓 {current_cn_longs}/{CN_MAX_POSITIONS} 只，超过目标但在弹性"
                    f"{CN_MAX_POSITIONS_FLEX}只内。注意控制持仓数。"
                )

        # 3. 每日新建仓 ≤ 2（仅新建仓计入）
        if is_new_position and trade_log is not None:
            daily_new = _count_daily_new_cn_positions(trade_log, today)
            if daily_new >= CN_MAX_DAILY_NEW_POSITIONS:
                sys.exit(
                    f"[BLOCKED] 今日A股新建仓已达 {daily_new}/{CN_MAX_DAILY_NEW_POSITIONS} 笔上限 (v7.0 §3.2)。"
                    f"第3只等次日。交易取消。"
                )

        # 4. 每周交易总量 — 软提醒，不硬BLOCK（灵活执行）
        if trade_log is not None:
            weekly_count = _count_weekly_cn_trades(trade_log, today)
            if weekly_count >= CN_MAX_WEEKLY_TRADES:
                print(
                    f"[WARN] 本周A股交易已达 {weekly_count}/{CN_MAX_WEEKLY_TRADES} 笔，"
                    f"超过目标上限。继续执行但请注意交易频率。"
                )

        # 5. A股整数倍检查
        if shares % CN_LOT_SIZE != 0:
            sys.exit(
                f"[ERROR] A股交易必须为 {CN_LOT_SIZE} 股整数倍，收到 {shares} 股。交易取消。"
            )

    # ── 美股专属检查 ──────────────────────────────────────────────────────────
    if account_key == US_ACCOUNT_KEY:
        _, existing_pos = find_position(account["positions"], ticker)
        is_new_position = existing_pos is None

        # L16: 持仓数上限 9
        if is_new_position:
            current_us_longs = len([
                p for p in account.get("positions", [])
                if p.get("instrument_type") != "call_option"
            ])
            if current_us_longs >= 9:
                sys.exit(
                    f"BLOCKED: US portfolio at 9-position limit (L16). "
                    f"Current positions: {current_us_longs}. "
                    f"Close the weakest position before opening a new one."
                )

        # L16: 最小仓位 $7,500（仅美股新建仓）
        if is_new_position:
            if cost < 7500:
                sys.exit(
                    f"BLOCKED: Minimum position $7,500 (L16). "
                    f"Order value ${cost:,.2f} is below the $7,500 floor. "
                    f"Increase share count or do not open this position."
                )
        else:
            existing_value = existing_pos.get("shares", 0) * price
            total_value = existing_value + cost
            if total_value < 7500:
                sys.exit(
                    f"BLOCKED: Minimum position $7,500 (L16). "
                    f"After adding, total position value ${total_value:,.2f} is still below $7,500 floor."
                )

    # ── Bear Case 4-Tier F9 v2（v7.0）——两个市场通用 ────────────────────────
    # T4 >40% = 硬阻断; T3 25-40% = 橙灯警告; T2 15-25% = 黄灯警告
    if bear_case_downside is not None:
        if bear_case_downside < -0.40:
            sys.exit(
                f"[ERROR] {ticker} Bear case downside = {bear_case_downside:.1%}（>40%，T4红灯）。"
                f"F9 v2硬性排除，不建仓。交易取消。"
            )
        elif bear_case_downside < -0.25:
            print(
                f"[WARN] {ticker} Bear case downside = {bear_case_downside:.1%}（T3橙灯，25-40%）。"
                f"A股：仅A级可建，减半size；美股：不建仓（观察池）。"
            )
        elif bear_case_downside < -0.15:
            print(
                f"[INFO] {ticker} Bear case downside = {bear_case_downside:.1%}（T2黄灯，15-25%）。"
                f"A股：建仓但需止损点；美股：半仓起步等earnings确认。"
            )

    # ── 现金/杠杆检查 ───────────────────────────────────────────────────────
    total_assets = account.get("total_assets", 0)
    leverage_cap = account.get("leverage_cap", 1.0)
    sym = "¥" if currency == "CNY" else "$"

    if leverage_cap > 1.0 and total_assets > 0:
        positions = account.get("positions", [])
        if isinstance(positions, list):
            current_long = sum(p.get("market_value", 0) for p in positions)
        else:
            current_long = sum(p.get("market_value", 0) for p in positions.values())
        gross_after = current_long + cost
        leverage_after = gross_after / total_assets if total_assets > 0 else 999
        if leverage_after > leverage_cap:
            sys.exit(
                f"[ERROR] 杠杆超限。买入后总多头 {sym}{gross_after:,.0f}，"
                f"杠杆 {leverage_after:.2f}x > 上限 {leverage_cap:.1f}x。交易取消。"
            )
        remaining_cash = cash - cost
        if remaining_cash < 0:
            print(
                f"[MARGIN] 使用保证金 {sym}{abs(remaining_cash):,.2f}。"
                f"买入后杠杆 {leverage_after:.2f}x（上限 {leverage_cap:.1f}x）"
            )
        elif total_assets > 0:
            cash_pct_after = remaining_cash / total_assets
            if cash_pct_after < 0.20:
                print(
                    f"[WARN] 买入后现金将降至 {cash_pct_after:.1%}。"
                    f"剩余: {sym}{remaining_cash:,.2f}"
                )
    else:
        if cost > cash:
            sys.exit(
                f"[ERROR] 现金不足。需要 {sym}{cost:,.2f}，可用 {sym}{cash:,.2f}。交易取消。"
            )

    # ── 仓位上限检查 ──────────────────────────────────────────────────────────
    if total_assets > 0:
        _, existing = find_position(account["positions"], ticker)
        existing_value = 0.0
        if existing:
            existing_value = existing.get("shares", 0) * price
        new_value = existing_value + cost
        pct = new_value / total_assets

        if account_key == CN_ACCOUNT_KEY:
            # v7.0 SABCT分级上限
            enrichment = _enrich_position_from_watchlist(ticker, account_key)
            grade = enrichment.get("conviction_level", "")
            if not grade and existing:
                grade = existing.get("conviction_level", "")
            limit = SABCT_LIMITS.get(grade, 0.12)  # 未知等级默认B级(12%)
            if pct > limit:
                sys.exit(
                    f"[ERROR] 买入后 {ticker} 持仓占比将达 {pct:.1%}，超过{grade}级上限 {limit:.0%} (v7.0 §2.2)。\n"
                    f"（现有价值: ¥{existing_value:,.2f}，本次买入: ¥{cost:,.2f}，总资产: ¥{total_assets:,.2f}）\n交易取消。"
                )
        else:
            # 美股：ETF/指数不受单只上限限制；个股上限50%（S级）
            etf_tickers = {"QQQ", "SPY", "TQQQ", "SQQQ", "SSO", "UPRO", "SMH", "SOXX", "IWM", "DIA", "VOO", "VTI"}
            if ticker not in etf_tickers and pct > 0.50:
                sys.exit(
                    f"[ERROR] 买入后 {ticker} 持仓占比将达 {pct:.1%}，超过上限 50%。"
                    f"（现有价值: ${existing_value:,.2f}，本次买入: ${cost:,.2f}，总资产: ${total_assets:,.2f}）\n交易取消。"
                )


def validate_sell(account: dict, account_key: str, ticker: str, shares: int, sell_all: bool,
                  reason: str = "", price: float = 0.0) -> int:
    """
    验证卖出，返回实际卖出股数。

    v7.0新增:
    - 止损执行必须一次性全部清仓（reason含'stop'/'止损'时强制sell_all）
    - 两段式出场提示（第一段卖50%，第二段全出）
    """
    _, pos = find_position(account["positions"], ticker)
    if pos is None:
        sys.exit(f"[ERROR] 账户中没有 {ticker} 的持仓，无法卖出。交易取消。")
    if pos.get("instrument_type") == "call_option":
        sys.exit(f"[ERROR] {ticker} 是期权，跳过（不支持自动执行期权交易）。")

    # A股T+1硬拦截：当日买入的股票当日不能卖出
    if account_key == CN_ACCOUNT_KEY:
        entry_date_str = pos.get("entry_date", "")
        if entry_date_str:
            from datetime import datetime, date
            try:
                if "T" in entry_date_str:
                    entry_dt = datetime.fromisoformat(entry_date_str).date()
                else:
                    entry_dt = date.fromisoformat(entry_date_str[:10])
                if entry_dt == date.today():
                    sys.exit(
                        f"[BLOCKED] A股T+1规则：{ticker} 于今日 {entry_dt} 买入，当日不可卖出。\n"
                        f"最早可卖出日期：明天。交易取消。\n"
                        f"如用户明确授权T+0，使用 --force-t0 绕过。"
                    )
            except (ValueError, TypeError):
                pass

    # Sell Gate: 催化剂T-14天内减仓提醒
    # 若持仓有 catalyst_date 字段且在未来14天内，打印WARNING（不阻断）
    if account_key == CN_ACCOUNT_KEY:
        _catalyst_raw = pos.get("next_catalyst", "") or pos.get("catalyst_date", "")
        if _catalyst_raw:
            import re as _re_sg
            from datetime import date as _date_sg
            # 从 next_catalyst 字符串中提取日期（格式 YYYY-MM-DD 或 YYYY/MM/DD）
            _dt_match = _re_sg.search(r'(\d{4})[/-](\d{2})[/-](\d{2})', str(_catalyst_raw))
            if _dt_match:
                try:
                    _cat_date = _date_sg(
                        int(_dt_match.group(1)),
                        int(_dt_match.group(2)),
                        int(_dt_match.group(3))
                    )
                    _today_sg = _date_sg.today()
                    _days_to_cat = (_cat_date - _today_sg).days
                    if 0 <= _days_to_cat <= 14:
                        print(
                            f"\n[WARNING] Sell Gate 催化剂窗口: {ticker} 催化剂距今 "
                            f"T-{_days_to_cat}天 ({_cat_date})。\n"
                            f"  催化剂: {_catalyst_raw}\n"
                            f"  → 催化剂前减仓可能踏空核心上涨。确认要减仓？\n"
                            f"  → 若是止损/资金需求/另有A级机会，继续；否则建议持仓至催化剂后。"
                        )
                except (ValueError, TypeError):
                    pass

    held = pos.get("shares", 0)

    # v7.0 §3.1 止损铁律: 止损操作必须一次性全部清仓
    reason_lower = reason.lower()
    is_stop_loss = any(kw in reason_lower for kw in ("stop", "止损", "stop_loss", "stoploss"))
    if is_stop_loss and not sell_all and shares < held:
        sys.exit(
            f"[BLOCKED] 止损执行必须一次性全部清仓 (v7.0 §3.1 止损铁律)。\n"
            f"当前持有 {held} 股，本次仅卖 {shares} 股不符合规则。\n"
            f"请使用 --all 参数执行止损全部清仓。交易取消。"
        )

    if sell_all:
        actual = held
    else:
        if shares > held:
            sys.exit(
                f"[ERROR] 持仓不足。持有 {held} 股，尝试卖出 {shares} 股。交易取消。"
            )
        actual = shares

    # v7.0 §4.2 两段式出场提示（非止损场景）
    if account_key == CN_ACCOUNT_KEY and not is_stop_loss and not sell_all:
        half_held = held // 2
        target_1 = pos.get("target_1")
        if target_1 and price > 0 and price >= target_1:
            # 到达目标价1，应卖50%
            if actual > half_held * 1.1:  # 超过55%则提示
                print(
                    f"[INFO] 两段式出场 (v7.0 §4.2): {ticker} 已达目标价1 ¥{target_1}。\n"
                    f"第一段建议卖出 {half_held} 股（50%），剩余设trailing stop。\n"
                    f"本次卖出 {actual} 股，确认继续请忽略此提示。"
                )
        elif actual == held:
            # 非止损全清且未触及止损，提示两段式
            avg_cost = pos.get("avg_cost", 0)
            if avg_cost > 0 and price > 0:
                pnl_pct = (price - avg_cost) / avg_cost
                if pnl_pct > 0.05:  # 盈利>5%全清时提示
                    print(
                        f"[INFO] 两段式出场提示 (v7.0 §4.2): {ticker} 持仓盈利 {pnl_pct:.1%}，"
                        f"全仓卖出前确认是否已执行第一段（50%）出场逻辑。"
                    )

    return actual


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

def _astock_pre_buy_gate(ticker: str, shares: int, price: float, reason: str):
    """A股建仓前强制拦截 — 不过检查不让买。"""
    import re
    code = ticker.replace(".SZ", "").replace(".SH", "").replace(".BJ", "")
    blocks = []
    warnings = []

    # ── Gate 0a: reason必须包含具体催化剂日期 ──
    has_date = bool(re.search(r'\d{1,2}[/\-月]\d{0,2}|\d{4}[/\-]\d{2}|ASCO|WWDC|COMPUTEX|财报|业绩预告|Q[1-4]', reason))
    if not has_date:
        blocks.append(
            f"[BLOCKED] reason中没有具体催化剂日期。\n"
            f"  reason: \"{reason}\"\n"
            f"  → 买入理由必须包含催化剂日期(如'6/15旺季启动'/'ASCO 5/29')。\n"
            f"  → 说不出催化剂日期 = γ级 = 不建仓。"
        )

    # ── Gate 0b: reason必须包含Track B信号确认 ──
    has_tb = bool(re.search(r'TB[=:].?[ABS]|Track.?B.?[≥>=].?B|涨停|龙虎榜|板块资金|主力净买|北向', reason))
    if not has_tb:
        blocks.append(
            f"[BLOCKED] reason中没有Track B市场信号确认。\n"
            f"  → 市场没动的票不建仓。reason必须注明Track B信号\n"
            f"    (如'TB=A-,龙虎榜机构净买2.3亿'/'同板块3只涨停')。\n"
            f"  → Track B = C/D = 市场不care你的thesis = 放观察池。"
        )

    # ── Gate 1: D6筹码+技术体检 ──
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from uass_scan import chip_health_check
        d6 = chip_health_check(code, current_price=price)
        flags = d6.get("flags", [])
        if "DATA_ERROR" not in flags and "HEALTHY" not in flags:
            # 计算D6扣分
            penalty = 0
            core_flags = [f for f in flags if f not in ("VOL_SHRINK", "VOL_PRICE_DIV", "RSI_EXTREME", "HIGH_SHADOW")]
            flag_scores = {
                "EXTREME_RUN": -35, "HEAVY_RUN": -20, "VOLUME_CLIMAX": -15,
                "STAGNANT_VOL": -15, "MA_OVEREXTEND": -15, "MACD_TOP_DIV": -10,
                "PROFIT_TRAPPED": -10, "MA_BEARISH": -10,
            }
            aux_scores = {"VOL_SHRINK": -5, "VOL_PRICE_DIV": -5, "RSI_EXTREME": -5, "HIGH_SHADOW": -5}
            for f in flags:
                if f in flag_scores:
                    penalty += flag_scores[f]
                elif f in aux_scores and core_flags:
                    penalty += aux_scores[f]

            g30 = d6.get("30d_gain")
            rsi = d6.get("rsi14")
            ma_dev = d6.get("ma20_dev")
            info = f"flags={','.join(flags)} | 30d涨幅={g30}% | RSI={rsi} | MA偏离={ma_dev}%"

            if penalty <= -35:
                blocks.append(f"[BLOCKED] D6筹码体检不通过(扣分{penalty}): {info}\n"
                              f"  → 技术面严重恶化，禁止建仓。等D6恢复HEALTHY后再买。")
            elif penalty <= -20:
                warnings.append(f"[WARNING] D6筹码体检预警(扣分{penalty}): {info}\n"
                                f"  → 技术面有风险，仓位上限降至8%。")
        elif "HEALTHY" in flags:
            print(f"  [D6] ✓ 筹码体检通过 (HEALTHY)")
    except Exception as e:
        warnings.append(f"[WARNING] D6体检跳过(导入失败): {e}")

    # ── Gate 2: 30日涨幅极端 ──
    try:
        from uass_scan import _fetch_hist
        import numpy as np
        hist = _fetch_hist(code, days=35)
        if hist is not None and len(hist) >= 20:
            closes = np.array(hist["Close"].values, dtype=float)
            gain_20d = (closes[-1] - closes[-15]) / closes[-15] * 100
            if gain_20d > 40:
                blocks.append(f"[BLOCKED] 20日涨幅{gain_20d:.1f}% > 40% — 追高买入，等回调再考虑。")
    except Exception:
        pass

    # ── Gate 3: A股持仓数量硬上限 ──
    # 读取 portfolio_state.json，检查当前持仓数（新建仓时才触发）
    _gate3_triggered = False
    try:
        _pf3 = load_portfolio()
        _acct3 = _pf3["accounts"].get(CN_ACCOUNT_KEY, {})
        _existing3 = [
            p for p in _acct3.get("positions", [])
            if p.get("instrument_type") != "call_option"
        ]
        _is_new3 = all(p.get("ticker") != ticker for p in _existing3)
        if _is_new3:
            _cn_count = len(_existing3)
            # 读取 config 上限，回退值 8
            _max_pos = CN_MAX_POSITIONS_FLEX  # 硬顶，与 config 保持一致
            if _cn_count >= _max_pos:
                blocks.append(
                    f"[BLOCKED] Gate 3 持仓数量硬上限: 当前A股持仓 {_cn_count}/{_max_pos} 只，"
                    f"已达上限。\n"
                    f"  → 必须先清仓至少1只再建新仓。交易取消。"
                )
                _gate3_triggered = True
            elif _cn_count >= CN_MAX_POSITIONS:
                warnings.append(
                    f"[WARNING] Gate 3 持仓接近上限: 当前 {_cn_count}/{_max_pos} 只，"
                    f"建仓后将达到上限，谨慎新增。"
                )
        else:
            print(f"  [Gate 3] ✓ 加仓已有持仓 {ticker}，跳过持仓数检查")
    except Exception as _g3e:
        warnings.append(f"[WARNING] Gate 3 持仓数检查失败（跳过）: {_g3e}")

    # ── Gate 4: 单只权重上限（按 conviction 等级）──
    # 评级从 reason 中解析，或从 watchlist 读取，或默认 B 级（15%上限）
    if not _gate3_triggered:
        try:
            import re as _re4
            _pf4 = load_portfolio()
            _acct4 = _pf4["accounts"].get(CN_ACCOUNT_KEY, {})
            _total4 = _acct4.get("total_assets", 0)
            if _total4 > 0:
                # 解析评级：reason > watchlist > 现有持仓 > 默认B
                _grade4 = ""
                # 从 reason 中匹配（如"评级A+"/"conviction=A+"/"A+级"）
                _m4 = _re4.search(
                    r'(?:评级|conviction[=:]\s*|等级)([SABsab][+-]?)',
                    reason
                )
                if _m4:
                    _grade4 = _m4.group(1).upper()
                # 从 watchlist 读取
                if not _grade4 or _grade4 not in SABCT_LIMITS:
                    _en4 = _enrich_position_from_watchlist(ticker, CN_ACCOUNT_KEY)
                    _grade4 = _en4.get("conviction_level", "")
                # 从现有持仓读取（加仓场景）
                if not _grade4 or _grade4 not in SABCT_LIMITS:
                    for _p4 in _acct4.get("positions", []):
                        if _p4.get("ticker") == ticker:
                            _grade4 = _p4.get("conviction_level", "")
                            break
                # 默认 B 级 12%（比 reason 里没写评级更保守）
                if not _grade4 or _grade4 not in SABCT_LIMITS:
                    _grade4 = "B"
                    print(
                        f"  [Gate 4] reason 中未检测到评级，默认按B级上限 "
                        f"{SABCT_LIMITS['B']:.0%} 检查。"
                    )

                _limit4 = SABCT_LIMITS[_grade4]
                # 计算买入后权重
                _cost4 = shares * price
                _existing_val4 = 0.0
                for _p4 in _acct4.get("positions", []):
                    if _p4.get("ticker") == ticker:
                        _existing_val4 = _p4.get("shares", 0) * price
                        break
                _new_val4 = _existing_val4 + _cost4
                _pct4 = _new_val4 / _total4
                if _pct4 > _limit4:
                    blocks.append(
                        f"[BLOCKED] Gate 4 单只权重超限: 买入后 {ticker} 将占 {_pct4:.1%}，"
                        f"超过 {_grade4} 级上限 {_limit4:.0%}。\n"
                        f"  现有市值: ¥{_existing_val4:,.0f}，"
                        f"本次买入: ¥{_cost4:,.0f}，"
                        f"总资产: ¥{_total4:,.0f}\n"
                        f"  → 减少买入股数，使买后权重 ≤ {_limit4:.0%}。交易取消。"
                    )
                else:
                    print(
                        f"  [Gate 4] ✓ {ticker} 买后权重 {_pct4:.1%} ≤ {_grade4}级上限 {_limit4:.0%}"
                    )
        except Exception as _g4e:
            warnings.append(f"[WARNING] Gate 4 权重检查失败（跳过）: {_g4e}")

    # ── Gate 5: Portfolio Heat 检查（系统性风险）──
    # 持仓中亏损 > ATR止损距离的标的比例 > 50% 时，不允许新建仓
    try:
        _pf5 = load_portfolio()
        _acct5 = _pf5["accounts"].get(CN_ACCOUNT_KEY, {})
        _positions5 = [
            p for p in _acct5.get("positions", [])
            if p.get("instrument_type") != "call_option"
        ]
        _is_new5 = all(p.get("ticker") != ticker for p in _positions5)
        if _is_new5 and len(_positions5) >= 3:
            # 判断每个持仓是否"处于止损警戒区"：
            # 当前价 < avg_cost AND (avg_cost - current_price) > (avg_cost - stop_loss)
            # 即：亏损幅度已超过设定的止损距离，属于"应止损但未止损"状态
            _heat_count = 0
            _heat_total = 0
            for _p5 in _positions5:
                _cp5 = _p5.get("current_price") or _p5.get("avg_cost", 0)
                _avg5 = _p5.get("avg_cost", 0)
                _sl5 = _p5.get("stop_loss", 0)
                if _avg5 <= 0 or _cp5 <= 0:
                    continue
                _heat_total += 1
                # 亏损超过止损距离：价格已跌破止损线
                if _sl5 > 0 and _cp5 < _sl5:
                    _heat_count += 1
            if _heat_total > 0:
                _heat_ratio = _heat_count / _heat_total
                if _heat_ratio > 0.50:
                    blocks.append(
                        f"[BLOCKED] Gate 5 Portfolio Heat 系统性风险: "
                        f"{_heat_count}/{_heat_total} 只持仓已跌破止损线 "
                        f"({_heat_ratio:.0%} > 50% 阈值)。\n"
                        f"  → 系统性风险过高，禁止新建仓。先处理已触发止损的持仓。\n"
                        f"  → 已跌破止损: " +
                        ", ".join(
                            p.get("ticker", "")
                            for p in _positions5
                            if (p.get("current_price") or p.get("avg_cost", 0)) < p.get("stop_loss", float("inf"))
                            and p.get("stop_loss", 0) > 0
                        )
                    )
                elif _heat_ratio > 0.30:
                    warnings.append(
                        f"[WARNING] Gate 5 Portfolio Heat 预警: "
                        f"{_heat_count}/{_heat_total} 只持仓跌破止损线 "
                        f"({_heat_ratio:.0%})。距离50%阻断阈值还有 "
                        f"{int(0.50 * _heat_total) - _heat_count} 只缓冲。谨慎建仓。"
                    )
                else:
                    print(
                        f"  [Gate 5] ✓ Portfolio Heat 正常: "
                        f"{_heat_count}/{_heat_total} 只触及止损 ({_heat_ratio:.0%} ≤ 50%)"
                    )
        elif not _is_new5:
            print(f"  [Gate 5] ✓ 加仓已有持仓，跳过Portfolio Heat检查")
        else:
            print(f"  [Gate 5] ✓ 持仓数 < 3，跳过Portfolio Heat检查")
    except Exception as _g5e:
        warnings.append(f"[WARNING] Gate 5 Portfolio Heat检查失败（跳过）: {_g5e}")

    # ── Gate 6: 同板块集中度警告 ──
    # 买入后同sector持仓权重 > 40% 给 WARNING（不block）
    try:
        _pf6 = load_portfolio()
        _acct6 = _pf6["accounts"].get(CN_ACCOUNT_KEY, {})
        _total6 = _acct6.get("total_assets", 0)
        if _total6 > 0:
            # 获取目标标的 sector（watchlist > 现有持仓）
            _en6 = _enrich_position_from_watchlist(ticker, CN_ACCOUNT_KEY)
            _target_sector6 = _en6.get("sector", "")
            if not _target_sector6:
                for _p6 in _acct6.get("positions", []):
                    if _p6.get("ticker") == ticker:
                        _target_sector6 = _p6.get("sector", "")
                        break

            if _target_sector6:
                # 计算买入后该 sector 总权重
                _sector_val6 = 0.0
                for _p6 in _acct6.get("positions", []):
                    _p6_sector = _p6.get("sector", "")
                    # 宽松匹配：sector字段包含目标sector关键词，或目标sector包含p6的sector
                    _same_sector = (
                        _target_sector6 == _p6_sector or
                        _target_sector6 in _p6_sector or
                        _p6_sector in _target_sector6
                    )
                    if _same_sector:
                        _p6_price = _p6.get("current_price") or _p6.get("avg_cost", 0)
                        if _p6.get("ticker") == ticker:
                            # 买入后该标的的预估市值（原有 + 本次）
                            _sector_val6 += _p6.get("shares", 0) * _p6_price + shares * price
                        else:
                            _sector_val6 += _p6.get("shares", 0) * _p6_price
                # 如果是新建仓（该sector目前没有该ticker）
                _has_ticker6 = any(p.get("ticker") == ticker for p in _acct6.get("positions", []))
                if not _has_ticker6:
                    _sector_val6 += shares * price

                _sector_pct6 = _sector_val6 / _total6
                if _sector_pct6 > 0.40:
                    warnings.append(
                        f"[WARNING] Gate 6 板块集中度: 买入后 '{_target_sector6}' 板块持仓将达 "
                        f"{_sector_pct6:.1%}（> 40% 警戒线）。\n"
                        f"  → 同板块风险集中，建议控制单板块总权重。此警告不阻断交易。"
                    )
                else:
                    print(
                        f"  [Gate 6] ✓ 板块集中度正常: '{_target_sector6}' "
                        f"买后权重 {_sector_pct6:.1%} ≤ 40%"
                    )
            else:
                print(f"  [Gate 6] ✓ 未获取到 {ticker} sector信息，跳过板块集中度检查")
    except Exception as _g6e:
        warnings.append(f"[WARNING] Gate 6 板块集中度检查失败（跳过）: {_g6e}")

    # ── 输出 ──
    if blocks:
        msg = "\n".join(blocks)
        sys.exit(f"{'='*60}\n⛔ A股建仓前置拦截 — {ticker}\n{'='*60}\n{msg}\n\n"
                 f"此拦截不可绕过。修复条件后重试。")
    for w in warnings:
        print(w)


def execute_buy(state: dict, account_key: str, ticker: str, shares: int, price: float, reason: str):
    account = state["accounts"][account_key]
    currency = account["currency"]
    cost = round(shares * price, 4)

    # A股建仓前强制拦截
    if account_key == CN_ACCOUNT_KEY:
        _astock_pre_buy_gate(ticker, shares, price, reason)

    idx, existing = find_position(account["positions"], ticker)
    if existing is None:
        # 新建持仓
        new_pos = {
            "ticker": ticker,
            "shares": shares,
            "avg_cost": price,
            "instrument_type": "stock",
            "entry_date": now_iso(),
            "last_updated": now_iso(),
        }
        # 从watchlist填充额外字段（name/sector/type/stop_loss/target_1/target_2/bear_case/thesis/conviction_level）
        enrichment = _enrich_position_from_watchlist(ticker, account_key)
        if enrichment:
            new_pos.update(enrichment)
            grade = enrichment.get("conviction_level", "")
            print(f"  [+] 新建持仓: {ticker} (从watchlist补全: name={enrichment.get('name', '')}, "
                  f"sector={enrichment.get('sector', '')}, 评级={grade})")
        else:
            print(f"  [+] 新建持仓: {ticker} (watchlist中未找到，请手动补全name/sector/stop_loss等字段)")

        # A-stock: 统一-12%硬止损 (3轮回测: -12%最优, 不误杀回撤反弹)
        if account_key == CN_ACCOUNT_KEY:
            if not new_pos.get("stop_loss"):
                new_pos["stop_loss"] = round(price * (1 + ASTOCK_HARD_STOP_PCT), 2)
                new_pos["stop_loss_note"] = f"硬止损{ASTOCK_HARD_STOP_PCT:.0%} (3轮回测迭代)"
                print(f"  [止损] ¥{new_pos['stop_loss']:,.2f} (入场¥{price:.2f} × {ASTOCK_HARD_STOP_PCT:.0%})")

        # V6.2: US buy — override stop_loss with ATR(14)-based calculation
        # Entry − K×ATR(14), with a floor of −20%
        if account_key == US_ACCOUNT_KEY:
            _K = ATR_STOP["K"]          # 2.5
            _PERIOD = ATR_STOP["period"]  # 14
            _FLOOR = ATR_STOP["floor_pct"]  # -0.20
            yf_sym = YF_TICKER_MAP.get(ticker.upper(), ticker.upper())
            try:
                hist = yf.Ticker(yf_sym).history(period="30d")
                if len(hist) >= _PERIOD:
                    _high = hist["High"]
                    _low = hist["Low"]
                    _close = hist["Close"]
                    _tr = pd.concat([
                        _high - _low,
                        (_high - _close.shift()).abs(),
                        (_low - _close.shift()).abs()
                    ], axis=1).max(axis=1)
                    atr_14 = float(_tr.rolling(_PERIOD).mean().iloc[-1])
                    atr_stop = price - _K * atr_14
                    floor_stop = price * (1 + _FLOOR)
                    new_pos["stop_loss"] = round(max(atr_stop, floor_stop), 2)
                    new_pos["stop_loss_note"] = (
                        f"ATR({_PERIOD})={atr_14:.2f}, stop=entry-{_K}×ATR, floor={_FLOOR:.0%}"
                    )
                    print(f"  [ATR] 止损: ${new_pos['stop_loss']:,.2f} "
                          f"(entry ${price:.2f} - {_K}×ATR {atr_14:.2f}; "
                          f"floor ${floor_stop:.2f})")
                else:
                    _fb = ATR_STOP.get("fallback_pct", -0.15)
                    new_pos["stop_loss"] = round(price * (1 + _fb), 2)
                    new_pos["stop_loss_note"] = f"fallback: fixed {_fb:.0%} (insufficient ATR data, need {_PERIOD} days)"
                    print(f"  [ATR] 数据不足，使用固定{_fb:.0%}止损: ${new_pos['stop_loss']:,.2f}")
            except Exception as _atr_err:
                _fb = ATR_STOP.get("fallback_pct", -0.15)
                new_pos["stop_loss"] = round(price * (1 + _fb), 2)
                new_pos["stop_loss_note"] = f"fallback: fixed {_fb:.0%} (ATR fetch failed: {_atr_err})"
                print(f"  [ATR] 获取失败，使用固定{_fb:.0%}止损: ${new_pos['stop_loss']:,.2f}")

        # Bug 1 Fix: append new_pos to positions list
        account["positions"].append(new_pos)
    else:
        # 加权平均更新 avg_cost
        old_shares = existing["shares"]
        old_cost = existing["avg_cost"]
        new_shares = old_shares + shares
        new_avg = round((old_shares * old_cost + shares * price) / new_shares, 6)
        account["positions"][idx]["shares"] = new_shares
        account["positions"][idx]["avg_cost"] = new_avg
        account["positions"][idx]["last_updated"] = now_iso()
        print(f"  [+] 加仓: {ticker}，新持仓 {new_shares} 股，新均成本 {new_avg:.4f}")

    account["cash"] = round(account["cash"] - cost, 4)
    account["trade_count"] = account.get("trade_count", 0) + 1
    _update_total_assets(account, price, ticker)

    trade_entry = {
        "id": f"TRD-{len(state['trade_log']) + 1:04d}",
        "timestamp": now_iso(),
        "date": datetime.now(TZ_BEIJING).strftime("%Y-%m-%d"),
        "action": "buy",
        "account": account_key,
        "ticker": ticker,
        "name": _resolve_name(state, ticker, account_key),
        "shares": shares,
        "price": price,
        "value": cost,
        "currency": currency,
        "reason": reason,
    }
    state["trade_log"].append(trade_entry)
    state["_meta"]["last_updated"] = now_iso()
    state["_meta"]["update_trigger"] = "execute_trade"

    sym = "¥" if currency == "CNY" else "$"
    print(f"\n{'='*50}")
    print(f"  交易确认 — 买入")
    print(f"  账户:   {account_key}")
    print(f"  标的:   {ticker}")
    print(f"  股数:   {shares:,}")
    print(f"  成交价: {sym}{price:,.4f}")
    print(f"  成交额: {sym}{cost:,.2f}")
    print(f"  剩余现金: {sym}{account['cash']:,.2f}")
    print(f"  交易ID: {trade_entry['id']}")
    print(f"  备注:   {reason}")
    print(f"{'='*50}\n")


def execute_sell(state: dict, account_key: str, ticker: str, actual_shares: int, price: float, reason: str):
    account = state["accounts"][account_key]
    currency = account["currency"]
    proceeds = round(actual_shares * price, 4)

    idx, pos = find_position(account["positions"], ticker)
    avg_cost = pos["avg_cost"]
    realized_pnl = round((price - avg_cost) * actual_shares, 4)

    remaining = pos["shares"] - actual_shares
    if remaining <= 0:
        # 清空持仓
        account["positions"].pop(idx)
        print(f"  [-] 清空持仓: {ticker}")
    else:
        account["positions"][idx]["shares"] = remaining
        # Bug 5 Fix: recalculate cost_basis after partial sell
        account["positions"][idx]["cost_basis"] = round(remaining * account["positions"][idx]["avg_cost"], 2)
        account["positions"][idx]["last_updated"] = now_iso()
        print(f"  [-] 减仓: {ticker}，剩余 {remaining} 股")

    account["cash"] = round(account["cash"] + proceeds, 4)
    account["realized_pnl"] = round(account.get("realized_pnl", 0) + realized_pnl, 4)
    account["trade_count"] = account.get("trade_count", 0) + 1
    _update_total_assets(account, price, ticker)

    trade_entry = {
        "id": f"TRD-{len(state['trade_log']) + 1:04d}",
        "timestamp": now_iso(),
        "date": datetime.now(TZ_BEIJING).strftime("%Y-%m-%d"),
        "action": "sell",
        "account": account_key,
        "ticker": ticker,
        "name": _resolve_name(state, ticker, account_key),
        "shares": actual_shares,
        "price": price,
        "value": proceeds,
        "currency": currency,
        "realized_pnl": realized_pnl,
        "reason": reason,
    }
    state["trade_log"].append(trade_entry)
    state["_meta"]["last_updated"] = now_iso()
    state["_meta"]["update_trigger"] = "execute_trade"

    sym = "¥" if currency == "CNY" else "$"
    pnl_sign = "+" if realized_pnl >= 0 else ""
    print(f"\n{'='*50}")
    print(f"  交易确认 — 卖出")
    print(f"  账户:     {account_key}")
    print(f"  标的:     {ticker}")
    print(f"  股数:     {actual_shares:,}")
    print(f"  成交价:   {sym}{price:,.4f}")
    print(f"  成交额:   {sym}{proceeds:,.2f}")
    print(f"  均成本:   {sym}{avg_cost:,.4f}")
    print(f"  已实现PnL: {sym}{pnl_sign}{realized_pnl:,.2f}")
    print(f"  剩余现金: {sym}{account['cash']:,.2f}")
    print(f"  交易ID:   {trade_entry['id']}")
    print(f"  备注:     {reason}")
    print(f"{'='*50}\n")


def execute_short(state: dict, account_key: str, ticker: str, shares: int, price: float, reason: str):
    account = state["accounts"][account_key]
    currency = account["currency"]
    proceeds = round(shares * price, 4)

    if account_key == CN_ACCOUNT_KEY:
        sys.exit("[ERROR] A股不支持做空。交易取消。")

    gross = _calc_gross_exposure(account, price, ticker)
    new_short_value = shares * price
    if gross + new_short_value > MAX_GROSS_EXPOSURE:
        sys.exit(
            f"[ERROR] 做空后总敞口将达 ${gross + new_short_value:,.0f}，"
            f"超过 ${MAX_GROSS_EXPOSURE:,.0f} 上限。交易取消。"
        )

    total_assets = account["total_assets"]
    if total_assets > 0:
        if "short_positions" not in account:
            account["short_positions"] = []
        _, existing = find_position(account["short_positions"], ticker)
        existing_value = existing["shares"] * price if existing else 0
        if (existing_value + new_short_value) / total_assets > MAX_SHORT_POSITION_PCT:
            sys.exit(
                f"[ERROR] {ticker} 空头将占 {(existing_value + new_short_value) / total_assets:.1%}，"
                f"超过 10% 上限。交易取消。"
            )

    if "short_positions" not in account:
        account["short_positions"] = []

    idx, existing = find_position(account["short_positions"], ticker)
    if existing is None:
        new_pos = {
            "ticker": ticker,
            "shares": shares,
            "entry_price": price,
            "instrument_type": "short",
            "entry_date": now_iso(),
            "stop_loss": round(price * (1 + SHORT_STOP_LOSS_PCT), 2),
            "last_updated": now_iso(),
        }
        account["short_positions"].append(new_pos)
        print(f"  [S] 新建空头: {ticker}")
    else:
        old_shares = existing["shares"]
        old_price = existing["entry_price"]
        new_shares = old_shares + shares
        new_avg = round((old_shares * old_price + shares * price) / new_shares, 6)
        account["short_positions"][idx]["shares"] = new_shares
        account["short_positions"][idx]["entry_price"] = new_avg
        account["short_positions"][idx]["stop_loss"] = round(new_avg * (1 + SHORT_STOP_LOSS_PCT), 2)
        account["short_positions"][idx]["last_updated"] = now_iso()
        print(f"  [S] 加空: {ticker}，新持仓 {new_shares} 股，新均价 {new_avg:.4f}")

    # Bug 3 Fix: deduct short margin (proceeds) from cash
    account["cash"] = round(account["cash"] - proceeds, 2)
    account["trade_count"] = account.get("trade_count", 0) + 1
    _update_total_assets(account, price, ticker)

    trade_entry = {
        "id": f"TRD-{len(state['trade_log']) + 1:04d}",
        "timestamp": now_iso(),
        "date": datetime.now(TZ_BEIJING).strftime("%Y-%m-%d"),
        "action": "short",
        "account": account_key,
        "ticker": ticker,
        "name": _resolve_name(state, ticker, account_key),
        "shares": shares,
        "price": price,
        "value": proceeds,
        "currency": currency,
        "reason": reason,
    }
    state["trade_log"].append(trade_entry)
    state["_meta"]["last_updated"] = now_iso()
    state["_meta"]["update_trigger"] = "execute_trade"

    print(f"\n{'='*50}")
    print(f"  交易确认 — 做空")
    print(f"  标的:     {ticker}")
    print(f"  股数:     {shares:,}")
    print(f"  开仓价:   ${price:,.4f}")
    print(f"  敞口:     ${proceeds:,.2f}")
    print(f"  止损:     ${round(price * (1 + SHORT_STOP_LOSS_PCT), 2):,.2f} (+{SHORT_STOP_LOSS_PCT:.0%})")
    print(f"  交易ID:   {trade_entry['id']}")
    print(f"  备注:     {reason}")
    print(f"{'='*50}\n")


def execute_cover(state: dict, account_key: str, ticker: str, shares: int, price: float, reason: str, cover_all: bool = False):
    account = state["accounts"][account_key]
    currency = account["currency"]

    if "short_positions" not in account:
        sys.exit(f"[ERROR] 账户中没有空头持仓。交易取消。")

    idx, pos = find_position(account["short_positions"], ticker)
    if pos is None:
        sys.exit(f"[ERROR] 账户中没有 {ticker} 的空头持仓。交易取消。")

    held = pos["shares"]
    actual_shares = held if cover_all else shares
    if actual_shares > held:
        sys.exit(f"[ERROR] 空头持仓不足。持有 {held} 股空头，尝试平 {actual_shares} 股。交易取消。")

    entry_price = pos["entry_price"]
    entry_avg_cost = pos.get("entry_price", price)  # entry_price IS avg_cost for shorts
    realized_pnl = round((entry_avg_cost - price) * actual_shares, 4)

    remaining = held - actual_shares
    if remaining <= 0:
        account["short_positions"].pop(idx)
        # Ghost entry cleanup: remove any stale entry in positions[] for this ticker
        # that is NOT a legitimate long position (shares <= 0, or instrument_type="short").
        # This handles old-style ghosts (negative shares from legacy code) and
        # zero-share residuals left by partial operations.
        pos_idx, pos_ghost = find_position(account.get("positions", []), ticker)
        if pos_ghost is not None:
            ghost_shares = pos_ghost.get("shares", 0)
            ghost_type = pos_ghost.get("instrument_type", "stock")
            if ghost_shares <= 0 or ghost_type == "short":
                account["positions"].pop(pos_idx)
                print(f"  [C] 清理positions数组中的ghost entry: {ticker} "
                      f"(shares={ghost_shares}, type={ghost_type})")
        print(f"  [C] 平空完毕: {ticker}")
    else:
        account["short_positions"][idx]["shares"] = remaining
        account["short_positions"][idx]["last_updated"] = now_iso()
        print(f"  [C] 部分平空: {ticker}，剩余空头 {remaining} 股")

    # Bug 4 Fix: add back margin + realized_pnl to cash on cover
    account["cash"] = round(account["cash"] + actual_shares * entry_avg_cost + realized_pnl, 2)
    account["realized_pnl"] = round(account.get("realized_pnl", 0) + realized_pnl, 4)
    account["trade_count"] = account.get("trade_count", 0) + 1
    _update_total_assets(account, price, ticker)

    trade_entry = {
        "id": f"TRD-{len(state['trade_log']) + 1:04d}",
        "timestamp": now_iso(),
        "date": datetime.now(TZ_BEIJING).strftime("%Y-%m-%d"),
        "action": "cover",
        "account": account_key,
        "ticker": ticker,
        "name": _resolve_name(state, ticker, account_key),
        "shares": actual_shares,
        "price": price,
        "value": round(actual_shares * price, 4),
        "currency": currency,
        "realized_pnl": realized_pnl,
        "reason": reason,
    }
    state["trade_log"].append(trade_entry)
    state["_meta"]["last_updated"] = now_iso()
    state["_meta"]["update_trigger"] = "execute_trade"

    pnl_sign = "+" if realized_pnl >= 0 else ""
    print(f"\n{'='*50}")
    print(f"  交易确认 — 平空")
    print(f"  标的:     {ticker}")
    print(f"  股数:     {actual_shares:,}")
    print(f"  平仓价:   ${price:,.4f}")
    print(f"  开仓均价: ${entry_price:,.4f}")
    print(f"  已实现PnL: ${pnl_sign}{realized_pnl:,.2f}")
    print(f"  交易ID:   {trade_entry['id']}")
    print(f"  备注:     {reason}")
    print(f"{'='*50}\n")


# ---------------------------------------------------------------------------
# Options & Futures Execute
# ---------------------------------------------------------------------------

def _next_option_id(account: dict) -> str:
    existing = account.get("options_positions", [])
    max_num = 0
    for opt in existing:
        oid = opt.get("id", "")
        if oid.startswith("OPT-"):
            try:
                max_num = max(max_num, int(oid.split("-")[1]))
            except (ValueError, IndexError):
                pass
    return f"OPT-{max_num + 1:03d}"


def _next_future_id(account: dict) -> str:
    existing = account.get("futures_positions", [])
    max_num = 0
    for fut in existing:
        fid = fut.get("id", "")
        if fid.startswith("FUT-"):
            try:
                max_num = max(max_num, int(fid.split("-")[1]))
            except (ValueError, IndexError):
                pass
    return f"FUT-{max_num + 1:03d}"


def _build_option_legs(args) -> list[dict]:
    strategy = args.strategy
    legs = []
    short_strike = getattr(args, "short_strike", None)
    long_strike = getattr(args, "long_strike", None)
    expiry = args.expiry

    if strategy in ("covered_call", "short_call"):
        legs.append({"type": "sell_call", "strike": short_strike, "expiry": expiry})
    elif strategy == "short_put":
        legs.append({"type": "sell_put", "strike": short_strike, "expiry": expiry})
    elif strategy in ("cash_secured_put",):
        legs.append({"type": "sell_put", "strike": short_strike, "expiry": expiry})
    elif strategy == "long_call":
        legs.append({"type": "buy_call", "strike": long_strike, "expiry": expiry})
    elif strategy == "long_put":
        legs.append({"type": "buy_put", "strike": long_strike, "expiry": expiry})
    elif strategy == "bull_call_spread":
        legs.append({"type": "buy_call", "strike": long_strike, "expiry": expiry})
        legs.append({"type": "sell_call", "strike": short_strike, "expiry": expiry})
    elif strategy == "bear_put_spread":
        legs.append({"type": "buy_put", "strike": long_strike, "expiry": expiry})
        legs.append({"type": "sell_put", "strike": short_strike, "expiry": expiry})
    elif strategy == "put_credit_spread":
        legs.append({"type": "sell_put", "strike": short_strike, "expiry": expiry})
        legs.append({"type": "buy_put", "strike": long_strike, "expiry": expiry})
    elif strategy == "call_credit_spread":
        legs.append({"type": "sell_call", "strike": short_strike, "expiry": expiry})
        legs.append({"type": "buy_call", "strike": long_strike, "expiry": expiry})
    elif strategy == "iron_condor":
        legs.append({"type": "sell_put", "strike": short_strike, "expiry": expiry})
        legs.append({"type": "buy_put", "strike": long_strike, "expiry": expiry})
        ic_short_call = getattr(args, "ic_short_call", None)
        ic_long_call = getattr(args, "ic_long_call", None)
        if ic_short_call and ic_long_call:
            legs.append({"type": "sell_call", "strike": ic_short_call, "expiry": expiry})
            legs.append({"type": "buy_call", "strike": ic_long_call, "expiry": expiry})
    return legs


def _calc_spread_risk_reward(args) -> tuple[float, float]:
    """Estimate max risk and max reward for spread strategies."""
    premium = args.premium
    contracts = args.contracts
    short_strike = getattr(args, "short_strike", None) or 0
    long_strike = getattr(args, "long_strike", None) or 0
    width = abs(short_strike - long_strike) * contracts * 100

    if premium > 0:
        max_reward = premium
        max_risk = width - premium if width > 0 else premium
    else:
        max_reward = width + premium if width > 0 else abs(premium) * 2
        max_risk = abs(premium)
    return max_risk, max_reward


def execute_option(state: dict, account_key: str, args):
    account = state["accounts"][account_key]
    currency = account["currency"]
    ticker = args.ticker.upper()
    strategy = args.strategy
    contracts = args.contracts
    premium = args.premium  # positive = credit received, negative = debit paid

    if account_key == CN_ACCOUNT_KEY:
        sys.exit("[ERROR] A股不支持期权交易。交易取消。")
    if strategy not in VALID_OPTION_STRATEGIES:
        sys.exit(f"[ERROR] 未知期权策略 '{strategy}'。支持: {', '.join(sorted(VALID_OPTION_STRATEGIES))}")

    if strategy == "covered_call":
        _, pos = find_position(account["positions"], ticker)
        if pos is None:
            sys.exit(f"[ERROR] Covered call需要持有{ticker}正股。当前无持仓。交易取消。")
        if pos["shares"] < contracts * 100:
            sys.exit(f"[ERROR] Covered call需要{contracts * 100}股，当前持有{pos['shares']}股。交易取消。")

    if premium < 0 and abs(premium) > account["cash"]:
        sys.exit(f"[ERROR] 现金不足。需要${abs(premium):,.2f}权利金，可用${account['cash']:,.2f}。交易取消。")

    legs = _build_option_legs(args)
    max_risk, max_reward = _calc_spread_risk_reward(args)
    option_id = _next_option_id(account)

    account["cash"] = round(account["cash"] + premium, 2)

    position = {
        "id": option_id,
        "ticker": ticker,
        "name": _resolve_name(state, ticker, account_key),
        "strategy": strategy,
        "legs": legs,
        "contracts": contracts,
        "premium_cash_flow": premium,
        "current_value": -premium,
        "max_risk": round(max_risk, 2),
        "max_reward": round(max_reward, 2),
        "status": "open",
        "entry_date": now_iso(),
        "expiry": args.expiry,
        "reason": args.reason,
    }

    if "options_positions" not in account:
        account["options_positions"] = []
    account["options_positions"].append(position)

    account["trade_count"] = account.get("trade_count", 0) + 1
    _update_total_assets(account, 0, "")

    trade_entry = {
        "id": f"TRD-{len(state['trade_log']) + 1:04d}",
        "timestamp": now_iso(),
        "date": datetime.now(TZ_BEIJING).strftime("%Y-%m-%d"),
        "action": "option",
        "account": account_key,
        "ticker": ticker,
        "name": _resolve_name(state, ticker, account_key),
        "option_id": option_id,
        "strategy": strategy,
        "contracts": contracts,
        "premium": premium,
        "currency": currency,
        "reason": args.reason,
    }
    state["trade_log"].append(trade_entry)
    state["_meta"]["last_updated"] = now_iso()
    state["_meta"]["update_trigger"] = "execute_trade"

    prem_label = f"收入 ${premium:,.2f}" if premium > 0 else f"支出 ${abs(premium):,.2f}"
    print(f"\n{'='*50}")
    print(f"  交易确认 — 开仓期权")
    print(f"  ID:       {option_id}")
    print(f"  标的:     {ticker}")
    print(f"  策略:     {strategy}")
    print(f"  合约数:   {contracts}")
    for leg in legs:
        print(f"  Leg:      {leg['type']} @ ${leg['strike']:,.2f} exp {leg['expiry']}")
    print(f"  权利金:   {prem_label}")
    print(f"  最大风险: ${max_risk:,.2f}")
    print(f"  最大收益: ${max_reward:,.2f}")
    print(f"  到期日:   {args.expiry}")
    print(f"  剩余现金: ${account['cash']:,.2f}")
    print(f"  交易ID:   {trade_entry['id']}")
    print(f"  备注:     {args.reason}")
    print(f"{'='*50}\n")


def execute_close_option(state: dict, account_key: str, args):
    account = state["accounts"][account_key]
    currency = account["currency"]
    option_id = args.id

    options = account.get("options_positions", [])
    idx = None
    opt = None
    for i, o in enumerate(options):
        if o["id"] == option_id and o.get("status") == "open":
            idx = i
            opt = o
            break
    if idx is None or opt is None:
        sys.exit(f"[ERROR] 期权 {option_id} 未找到或已关闭。交易取消。")

    expire = getattr(args, "expire", False)
    close_premium = 0 if expire else args.close_premium

    realized_pnl = round(opt["premium_cash_flow"] + close_premium, 2)

    account["cash"] = round(account["cash"] + close_premium, 2)
    account["realized_pnl"] = round(account.get("realized_pnl", 0) + realized_pnl, 2)

    opt["status"] = "closed"
    opt["close_date"] = now_iso()
    opt["close_premium"] = close_premium
    opt["realized_pnl"] = realized_pnl
    opt["current_value"] = 0

    account["trade_count"] = account.get("trade_count", 0) + 1
    _update_total_assets(account, 0, "")

    trade_entry = {
        "id": f"TRD-{len(state['trade_log']) + 1:04d}",
        "timestamp": now_iso(),
        "date": datetime.now(TZ_BEIJING).strftime("%Y-%m-%d"),
        "action": "close_option",
        "account": account_key,
        "ticker": opt["ticker"],
        "name": opt.get("name", opt["ticker"]),
        "option_id": option_id,
        "strategy": opt["strategy"],
        "close_premium": close_premium,
        "realized_pnl": realized_pnl,
        "currency": currency,
        "reason": args.reason,
    }
    state["trade_log"].append(trade_entry)
    state["_meta"]["last_updated"] = now_iso()
    state["_meta"]["update_trigger"] = "execute_trade"

    pnl_sign = "+" if realized_pnl >= 0 else ""
    close_label = "到期归零" if expire else f"${close_premium:,.2f}"
    print(f"\n{'='*50}")
    print(f"  交易确认 — 关闭期权")
    print(f"  ID:       {option_id}")
    print(f"  标的:     {opt['ticker']} ({opt['strategy']})")
    print(f"  关闭方式: {close_label}")
    print(f"  入场权利金: ${opt['premium_cash_flow']:,.2f}")
    print(f"  已实现PnL:  ${pnl_sign}{realized_pnl:,.2f}")
    print(f"  交易ID:   {trade_entry['id']}")
    print(f"  备注:     {args.reason}")
    print(f"{'='*50}\n")


def _fetch_futures_price(product: str) -> float:
    spec = FUTURES_SPECS.get(product)
    if not spec:
        sys.exit(f"[ERROR] 未知期货产品: {product}")
    yf_sym = spec["yf"]
    import time
    for attempt in range(3):
        try:
            t = yf.Ticker(yf_sym)
            price = t.fast_info.last_price
            if price and price > 0:
                return round(float(price), 2)
            hist = t.history(period="1d")
            if not hist.empty:
                return round(float(hist["Close"].iloc[-1]), 2)
        except Exception:
            pass
        if attempt < 2:
            time.sleep(1.5)
    sys.exit(f"[ERROR] 无法获取 {product} ({yf_sym}) 价格。交易取消。")


def execute_future(state: dict, account_key: str, args):
    account = state["accounts"][account_key]
    currency = account["currency"]
    product = args.product.upper()
    direction = args.direction.lower()
    contracts = args.contracts

    if account_key == CN_ACCOUNT_KEY:
        sys.exit("[ERROR] A股账户不支持期货交易。交易取消。")
    if product not in FUTURES_SPECS:
        sys.exit(f"[ERROR] 未知期货产品 '{product}'。支持: {', '.join(sorted(FUTURES_SPECS))}")
    if direction not in ("long", "short"):
        sys.exit("[ERROR] direction必须为 long 或 short。")

    spec = FUTURES_SPECS[product]
    entry_price = getattr(args, "entry_price", None)
    if entry_price is None:
        print(f"[INFO] 获取 {product} ({spec['yf']}) 实时价格...")
        entry_price = _fetch_futures_price(product)
        print(f"[INFO] 成交价: {entry_price}")

    margin_per = spec["margin"]
    total_margin = margin_per * contracts
    multiplier = spec["multiplier"]
    notional = round(entry_price * contracts * multiplier, 2)

    if total_margin > account["cash"]:
        sys.exit(f"[ERROR] 保证金不足。需要${total_margin:,.0f}，可用${account['cash']:,.2f}。交易取消。")

    account["cash"] = round(account["cash"] - total_margin, 2)
    future_id = _next_future_id(account)

    position = {
        "id": future_id,
        "product": product,
        "name": spec["name"],
        "direction": direction,
        "contracts": contracts,
        "entry_price": entry_price,
        "current_price": entry_price,
        "multiplier": multiplier,
        "notional": notional,
        "margin_required": total_margin,
        "unrealized_pnl": 0,
        "status": "open",
        "entry_date": now_iso(),
        "reason": args.reason,
    }

    if "futures_positions" not in account:
        account["futures_positions"] = []
    account["futures_positions"].append(position)

    account["trade_count"] = account.get("trade_count", 0) + 1
    _update_total_assets(account, 0, "")

    trade_entry = {
        "id": f"TRD-{len(state['trade_log']) + 1:04d}",
        "timestamp": now_iso(),
        "date": datetime.now(TZ_BEIJING).strftime("%Y-%m-%d"),
        "action": "future",
        "account": account_key,
        "ticker": product,
        "name": spec["name"],
        "future_id": future_id,
        "direction": direction,
        "contracts": contracts,
        "price": entry_price,
        "notional": notional,
        "currency": currency,
        "reason": args.reason,
    }
    state["trade_log"].append(trade_entry)
    state["_meta"]["last_updated"] = now_iso()
    state["_meta"]["update_trigger"] = "execute_trade"

    dir_label = "做多" if direction == "long" else "做空"
    print(f"\n{'='*50}")
    print(f"  交易确认 — 开仓期货")
    print(f"  ID:       {future_id}")
    print(f"  产品:     {product} ({spec['name']})")
    print(f"  方向:     {dir_label}")
    print(f"  合约数:   {contracts}")
    print(f"  成交价:   {entry_price:,.2f}")
    print(f"  乘数:     ${multiplier}/点")
    print(f"  名义价值: ${notional:,.2f}")
    print(f"  保证金:   ${total_margin:,.2f}")
    print(f"  剩余现金: ${account['cash']:,.2f}")
    print(f"  交易ID:   {trade_entry['id']}")
    print(f"  备注:     {args.reason}")
    print(f"{'='*50}\n")


def execute_close_future(state: dict, account_key: str, args):
    account = state["accounts"][account_key]
    currency = account["currency"]
    future_id = args.id

    futures = account.get("futures_positions", [])
    idx = None
    fut = None
    for i, f in enumerate(futures):
        if f["id"] == future_id and f.get("status") == "open":
            idx = i
            fut = f
            break
    if idx is None or fut is None:
        sys.exit(f"[ERROR] 期货 {future_id} 未找到或已关闭。交易取消。")

    exit_price = getattr(args, "exit_price", None)
    if exit_price is None:
        print(f"[INFO] 获取 {fut['product']} 实时价格...")
        exit_price = _fetch_futures_price(fut["product"])
        print(f"[INFO] 平仓价: {exit_price}")

    direction_sign = 1 if fut["direction"] == "long" else -1
    realized_pnl = round(
        (exit_price - fut["entry_price"]) * fut["contracts"] * fut["multiplier"] * direction_sign, 2
    )

    account["cash"] = round(account["cash"] + fut["margin_required"] + realized_pnl, 2)
    account["realized_pnl"] = round(account.get("realized_pnl", 0) + realized_pnl, 2)

    fut["status"] = "closed"
    fut["close_date"] = now_iso()
    fut["exit_price"] = exit_price
    fut["realized_pnl"] = realized_pnl
    fut["unrealized_pnl"] = 0

    account["trade_count"] = account.get("trade_count", 0) + 1
    _update_total_assets(account, 0, "")

    trade_entry = {
        "id": f"TRD-{len(state['trade_log']) + 1:04d}",
        "timestamp": now_iso(),
        "date": datetime.now(TZ_BEIJING).strftime("%Y-%m-%d"),
        "action": "close_future",
        "account": account_key,
        "ticker": fut["product"],
        "name": fut.get("name", fut["product"]),
        "future_id": future_id,
        "direction": fut["direction"],
        "contracts": fut["contracts"],
        "entry_price": fut["entry_price"],
        "exit_price": exit_price,
        "realized_pnl": realized_pnl,
        "currency": currency,
        "reason": args.reason,
    }
    state["trade_log"].append(trade_entry)
    state["_meta"]["last_updated"] = now_iso()
    state["_meta"]["update_trigger"] = "execute_trade"

    pnl_sign = "+" if realized_pnl >= 0 else ""
    print(f"\n{'='*50}")
    print(f"  交易确认 — 平仓期货")
    print(f"  ID:       {future_id}")
    print(f"  产品:     {fut['product']} ({fut.get('name', '')})")
    print(f"  方向:     {fut['direction']}")
    print(f"  合约数:   {fut['contracts']}")
    print(f"  入场价:   {fut['entry_price']:,.2f}")
    print(f"  平仓价:   {exit_price:,.2f}")
    print(f"  已实现PnL: ${pnl_sign}{realized_pnl:,.2f}")
    print(f"  退回保证金: ${fut['margin_required']:,.2f}")
    print(f"  剩余现金: ${account['cash']:,.2f}")
    print(f"  交易ID:   {trade_entry['id']}")
    print(f"  备注:     {args.reason}")
    print(f"{'='*50}\n")


def _calc_gross_exposure(account: dict, last_price: float = 0, last_ticker: str = "") -> float:
    long_value = 0.0
    for pos in account.get("positions", []):
        if pos.get("instrument_type") == "call_option":
            continue
        p = last_price if pos["ticker"] == last_ticker else pos.get("avg_cost", 0)
        long_value += pos["shares"] * p
    short_value = 0.0
    for pos in account.get("short_positions", []):
        p = last_price if pos["ticker"] == last_ticker else pos.get("entry_price", 0)
        short_value += pos["shares"] * p
    return long_value + short_value


def _update_total_assets(account: dict, last_price: float, last_ticker: str):
    from nav_calc import calc_nav, apply_nav

    for pos in account.get("positions", []):
        if pos["ticker"] == last_ticker:
            pos["current_price"] = round(last_price, 4)
            pos["unrealized_pnl"] = round((last_price - pos.get("avg_cost", 0)) * pos["shares"], 2)
    for sp in account.get("short_positions", []):
        if sp["ticker"] == last_ticker:
            sp["current_price"] = round(last_price, 4)

    nav = calc_nav(account)
    apply_nav(account, nav)


# ---------------------------------------------------------------------------
# Audit Trail
# ---------------------------------------------------------------------------

def _snapshot_account(account: dict, ticker: str, price: float) -> dict:
    """捕获账户快照，用于audit trail的 pre/post state对比。"""
    total_assets = account.get("total_assets", 0)
    cash = account.get("cash", 0)
    cash_pct = round(cash / total_assets * 100, 2) if total_assets > 0 else 100.0

    # 当前标的持仓占比
    position_value = 0.0
    for pos in account.get("positions", []):
        if pos.get("ticker") == ticker:
            position_value = pos.get("shares", 0) * price
            break
    position_pct = round(position_value / total_assets * 100, 2) if total_assets > 0 else 0.0

    return {
        "cash": round(cash, 4),
        "cash_pct": cash_pct,
        "total_assets": round(total_assets, 4),
        "position_count": len(account.get("positions", [])),
        "nav": round(total_assets, 2),
        "position_pct": position_pct,
    }


def generate_audit_trail(
    trade_entry: dict,
    pre_snapshot: dict,
    post_snapshot: dict,
    decision_chain: dict | None = None,
) -> None:
    """
    生成交易审计记录，写入 audit-trail/{date}-{ticker}-{action}.json。
    写入失败不阻塞主流程（由调用方用 try-except 包裹）。
    decision_chain: 由 decision_engine 调用时传入，manual 交易时为 None。
    """
    ticker  = trade_entry.get("ticker", "UNKNOWN")
    action  = trade_entry.get("action", "unknown")
    ts      = trade_entry.get("timestamp", now_iso())
    date_str = ts[:10]

    # 构建 decision_chain（manual 交易默认值）
    if decision_chain is None:
        decision_chain = {
            "trigger": {
                "type": "manual",
                "description": trade_entry.get("reason", ""),
                "source": "execute_trade",
            },
            "risk_check": {
                "pre_trade_cash_pct": pre_snapshot["cash_pct"],
                "post_trade_cash_pct": post_snapshot["cash_pct"],
                "position_size_pct": post_snapshot.get("position_pct", 0),
                "single_position_limit_ok": post_snapshot.get("position_pct", 0) <= MAX_SINGLE_POSITION_PCT * 100,
                "cash_minimum_ok": post_snapshot["cash_pct"] >= 20,
            },
            "final_decision": {
                "approved": True,
                "approver": "auto",
                "notes": trade_entry.get("reason", ""),
            },
        }
    else:
        # decision_engine 提供的 chain：补充实际交易后的 risk 数值
        decision_chain.setdefault("risk_check", {})
        decision_chain["risk_check"]["post_trade_cash_pct"] = post_snapshot["cash_pct"]
        decision_chain["risk_check"]["position_size_pct"] = post_snapshot.get("position_pct", 0)
        decision_chain["risk_check"]["single_position_limit_ok"] = (
            post_snapshot.get("position_pct", 0) <= MAX_SINGLE_POSITION_PCT * 100
        )
        decision_chain["risk_check"]["cash_minimum_ok"] = post_snapshot["cash_pct"] >= 20

    audit = {
        "trade_id": trade_entry.get("id"),
        "timestamp": ts,
        "ticker": ticker,
        "action": action,
        "account": trade_entry.get("account"),
        "shares": trade_entry.get("shares"),
        "price": trade_entry.get("price"),
        "value": trade_entry.get("value"),
        "currency": trade_entry.get("currency"),
        "realized_pnl": trade_entry.get("realized_pnl"),
        "reason": trade_entry.get("reason", ""),
        "decision_chain": decision_chain,
        "pre_trade_state": {
            "account_cash_pct": pre_snapshot["cash_pct"],
            "account_total_positions": pre_snapshot["position_count"],
            "account_nav": pre_snapshot["nav"],
        },
        "post_trade_state": {
            "account_cash_pct": post_snapshot["cash_pct"],
            "account_total_positions": post_snapshot["position_count"],
            "account_nav": post_snapshot["nav"],
            "realized_pnl": trade_entry.get("realized_pnl"),
        },
    }

    AUDIT_TRAIL_DIR.mkdir(exist_ok=True)
    # 同一天同一标的可能有多笔，加 trade_id 后缀避免覆盖
    trade_id_suffix = (trade_entry.get("id") or "").replace("TRD-", "")
    filename = f"{date_str}-{ticker}-{action}-{trade_id_suffix}.json"
    out_path = AUDIT_TRAIL_DIR / filename

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"[AUDIT] 记录已写入: {out_path.name}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="模拟盘交易执行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # --- buy ---
    buy_p = sub.add_parser("buy", help="买入")
    buy_p.add_argument("--account", required=True, help="账户: us / cn")
    buy_p.add_argument("--ticker", required=True, help="股票代码，A股用6位数字")
    buy_p.add_argument("--shares", required=True, type=int, help="买入股数")
    buy_p.add_argument("--reason", required=True, help="交易理由")
    buy_p.add_argument("--bear-case-downside", type=float, default=None,
                       help="Bear case downside (负数, 如 -0.15 表示-15%)")

    # --- sell ---
    sell_p = sub.add_parser("sell", help="卖出")
    sell_p.add_argument("--account", required=True, help="账户: us / cn")
    sell_p.add_argument("--ticker", required=True, help="股票代码")
    shares_grp = sell_p.add_mutually_exclusive_group(required=True)
    shares_grp.add_argument("--shares", type=int, help="卖出股数")
    shares_grp.add_argument("--all", dest="sell_all", action="store_true", help="卖出全部")
    sell_p.add_argument("--reason", required=True, help="交易理由")

    # --- short ---
    short_p = sub.add_parser("short", help="做空(仅美股)")
    short_p.add_argument("--account", required=True, help="账户: us")
    short_p.add_argument("--ticker", required=True, help="股票代码")
    short_p.add_argument("--shares", required=True, type=int, help="做空股数")
    short_p.add_argument("--reason", required=True, help="做空理由(含thesis)")

    # --- cover ---
    cover_p = sub.add_parser("cover", help="平空")
    cover_p.add_argument("--account", required=True, help="账户: us")
    cover_p.add_argument("--ticker", required=True, help="股票代码")
    cover_shares_grp = cover_p.add_mutually_exclusive_group(required=True)
    cover_shares_grp.add_argument("--shares", type=int, help="平仓股数")
    cover_shares_grp.add_argument("--all", dest="cover_all", action="store_true", help="全部平仓")
    cover_p.add_argument("--reason", required=True, help="平仓理由")

    # --- option ---
    opt_p = sub.add_parser("option", help="开仓期权(仅美股)")
    opt_p.add_argument("--account", required=True, help="账户: us")
    opt_p.add_argument("--ticker", required=True, help="标的代码")
    opt_p.add_argument("--strategy", required=True, help="策略类型: covered_call/put_credit_spread/bull_call_spread/...")
    opt_p.add_argument("--contracts", required=True, type=int, help="合约数")
    opt_p.add_argument("--short-strike", type=float, default=None, help="卖出腿行权价")
    opt_p.add_argument("--long-strike", type=float, default=None, help="买入腿行权价")
    opt_p.add_argument("--expiry", required=True, help="到期日 YYYY-MM-DD")
    opt_p.add_argument("--premium", required=True, type=float, help="净权利金(正=收入credit/负=支出debit)")
    opt_p.add_argument("--reason", required=True, help="交易理由")

    # --- close_option ---
    copt_p = sub.add_parser("close_option", help="关闭期权")
    copt_p.add_argument("--account", required=True, help="账户: us")
    copt_p.add_argument("--id", required=True, help="期权ID (OPT-001)")
    close_grp = copt_p.add_mutually_exclusive_group(required=True)
    close_grp.add_argument("--close-premium", type=float, help="关闭时收到/支付的权利金(正=收/负=付)")
    close_grp.add_argument("--expire", action="store_true", help="到期归零(premium=0)")
    copt_p.add_argument("--reason", required=True, help="关闭理由")

    # --- future ---
    fut_p = sub.add_parser("future", help="开仓期货(仅美股)")
    fut_p.add_argument("--account", required=True, help="账户: us")
    fut_p.add_argument("--product", required=True, help="产品: MES/ES/MNQ/NQ/VX/...")
    fut_p.add_argument("--direction", required=True, help="方向: long/short")
    fut_p.add_argument("--contracts", required=True, type=int, help="合约数")
    fut_p.add_argument("--entry-price", type=float, default=None, help="入场价(不填则自动获取)")
    fut_p.add_argument("--reason", required=True, help="交易理由")

    # --- close_future ---
    cfut_p = sub.add_parser("close_future", help="平仓期货")
    cfut_p.add_argument("--account", required=True, help="账户: us")
    cfut_p.add_argument("--id", required=True, help="期货ID (FUT-001)")
    cfut_p.add_argument("--exit-price", type=float, default=None, help="平仓价(不填则自动获取)")
    cfut_p.add_argument("--reason", required=True, help="平仓理由")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    account_key = get_account_key(args.account)

    # Options/futures don't need ticker normalization or price fetch
    if args.action in ("option", "close_option", "future", "close_future"):
        try:
            state = load_portfolio()
        except Exception as e:
            sys.exit(f"[ERROR] 无法读取 portfolio_state.json: {e}")
        account = state["accounts"][account_key]
        ticker = getattr(args, "ticker", getattr(args, "product", getattr(args, "id", "OPT/FUT"))).upper()
        price = 0
        pre_snapshot = _snapshot_account(account, ticker, price)
        trade_log_len_before = len(state["trade_log"])
    else:
        ticker = args.ticker.upper() if not args.ticker.isdigit() else args.ticker

        if len(ticker) > 10 and ("CALL" in ticker or "PUT" in ticker):
            print(f"[SKIP] {ticker} 识别为期权，跳过自动执行。")
            sys.exit(0)

        print(f"[INFO] 获取 {ticker} 实时价格...")
        price = fetch_price(ticker, account_key)
        print(f"[INFO] 成交价: {price}")

        try:
            state = load_portfolio()
        except Exception as e:
            sys.exit(f"[ERROR] 无法读取 portfolio_state.json: {e}")

        account = state["accounts"][account_key]
        pre_snapshot = _snapshot_account(account, ticker, price)
        trade_log_len_before = len(state["trade_log"])

    if args.action == "buy":
        bear_case = getattr(args, "bear_case_downside", None)
        validate_buy(account, account_key, ticker, args.shares, price, bear_case,
                     trade_log=state.get("trade_log", []))
        # A股 Round Trip 检查（新买入时检查本周是否已有反向操作）
        if account_key == CN_ACCOUNT_KEY:
            _check_round_trip_penalty(state.get("trade_log", []), account, ticker)
        execute_buy(state, account_key, ticker, args.shares, price, args.reason)

    elif args.action == "sell":
        sell_all = getattr(args, "sell_all", False)
        sell_shares = getattr(args, "shares", None) or 0
        actual_shares = validate_sell(account, account_key, ticker, sell_shares, sell_all,
                                      reason=args.reason, price=price)
        # A股 Round Trip 检查（卖出时检查本周是否已有反向操作）
        if account_key == CN_ACCOUNT_KEY:
            _check_round_trip_penalty(state.get("trade_log", []), account, ticker)
        execute_sell(state, account_key, ticker, actual_shares, price, args.reason)

    elif args.action == "short":
        execute_short(state, account_key, ticker, args.shares, price, args.reason)

    elif args.action == "cover":
        cover_all = getattr(args, "cover_all", False)
        cover_shares = getattr(args, "shares", None) or 0
        execute_cover(state, account_key, ticker, cover_shares, price, args.reason, cover_all)

    elif args.action == "option":
        execute_option(state, account_key, args)

    elif args.action == "close_option":
        execute_close_option(state, account_key, args)

    elif args.action == "future":
        execute_future(state, account_key, args)

    elif args.action == "close_future":
        execute_close_future(state, account_key, args)

    try:
        save_portfolio_atomic(state)
        print(f"[OK] portfolio_state.json 已更新。")
    except RuntimeError as e:
        print(f"[CRITICAL] {e}")
        sys.exit(1)

    # Post-trade compliance check — pass --market flag based on the account used
    try:
        compliance_script = Path(__file__).parent / "compliance_check.py"
        if compliance_script.exists():
            market_flag = "astock" if account_key == CN_ACCOUNT_KEY else "us"
            result = subprocess.run(
                ["/Users/huaichuaibeimeng/.local/bin/uv", "run", "--script",
                 str(compliance_script), "--post-trade",
                 "--market", market_flag,
                 "--account", account_key],
                check=False, timeout=30, capture_output=False
            )
            if result.returncode == 2:
                print("[COMPLIANCE] CRITICAL violation active — review pending_actions.json before next trade")
            elif result.returncode == 1:
                print("[COMPLIANCE] Violation(s) detected — review pending_actions.json")
    except Exception as _comp_err:
        print(f"[WARN] compliance_check failed (non-blocking): {_comp_err}")

    # 生成 audit trail（写入失败不阻塞）
    try:
        if len(state["trade_log"]) > trade_log_len_before:
            trade_entry = state["trade_log"][-1]
            post_snapshot = _snapshot_account(
                state["accounts"][account_key], ticker, price
            )
            generate_audit_trail(trade_entry, pre_snapshot, post_snapshot)
    except Exception as _audit_err:
        print(f"[WARN] Audit trail 写入失败（不影响交易）: {_audit_err}")

    # Refresh session_view files so next Read picks up the trade
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from session_view import build_view, build_all_view
        state_fresh = json.loads(Path(PORTFOLIO_PATH).read_text(encoding="utf-8"))
        repo = Path(__file__).parent.parent
        # Only rebuild the session_view for the market that was traded
        mkt = "cn" if account_key == "a_share" else "us"
        v = build_view(state_fresh, mkt)
        (repo / f"session_view_{mkt}.json").write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
        # Always rebuild the combined view
        av = build_all_view(state_fresh)
        (repo / "session_view_all.json").write_text(json.dumps(av, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[sync] ✓ session_view files refreshed")
    except Exception as e:
        print(f"⚠️ [sync] session_view refresh: {e}")

    # Auto-push to nexus-package (Railway website)
    try:
        sync_script = Path(__file__).parent / "sync_nexus.py"
        if sync_script.exists():
            result = subprocess.run(
                ["uv", "run", "--script", str(sync_script)],
                capture_output=True, text=True, timeout=60
            )
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    print(line)
            if result.returncode != 0 and result.stderr:
                print(f"⚠️ [nexus-sync] stderr: {result.stderr[:200]}")
    except Exception as e:
        print(f"⚠️ [nexus-sync] push failed (non-blocking): {e}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print("[CRITICAL] 未预期错误，交易未执行:")
        traceback.print_exc()
        sys.exit(2)
