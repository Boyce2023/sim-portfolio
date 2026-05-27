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
from core.config import ATR_STOP

AUDIT_TRAIL_DIR = Path(__file__).parent.parent / "audit-trail"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PORTFOLIO_PATH = Path(__file__).parent.parent / "portfolio_state.json"
CN_LOT_SIZE = 100  # A股最小交易单位
MAX_SINGLE_POSITION_PCT = 0.35  # 单一持仓上限 35% (A+级最高, v7.0)
MAX_SHORT_POSITION_PCT = 0.10   # 单一空头上限 10%
MAX_GROSS_EXPOSURE = 300000     # 美股总敞口上限 $300K (2x leverage)
SHORT_STOP_LOSS_PCT = 0.15      # 空头止损: 反向+15%
CN_ACCOUNT_KEY = "a_share"
US_ACCOUNT_KEY = "us"

# v7.0 A股交易频率约束
CN_MAX_POSITIONS = 5            # A股最多持仓数 (v7.0 §3.2)
CN_MAX_DAILY_NEW_POSITIONS = 2  # 每日新建仓上限 (v7.0 §3.2)
CN_MAX_WEEKLY_TRADES = 8        # 每周总交易上限（含加仓减仓）(v7.0 §3.2)

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
                return {
                    "name": item.get("name", ""),
                    "sector": item.get("sector", ""),
                    "type": item.get("type", ""),
                    "stop_loss": item.get("stop_loss"),
                    "target_1": item.get("target_1"),
                    "target_2": item.get("target_2"),
                    "bear_case": item.get("bear_case", ""),
                    "thesis": item.get("thesis", ""),
                    "conviction_level": grade,
                }
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

        # 2. 持仓数 ≤ 5（新建仓时检查）
        if is_new_position:
            current_cn_longs = len([
                p for p in account.get("positions", [])
                if p.get("instrument_type") != "call_option"
            ])
            if current_cn_longs >= CN_MAX_POSITIONS:
                sys.exit(
                    f"[BLOCKED] A股持仓已达 {current_cn_longs}/{CN_MAX_POSITIONS} 只上限 (v7.0 §3.2)。"
                    f"先清掉最弱仓位再建新仓。交易取消。"
                )

        # 3. 每日新建仓 ≤ 2（仅新建仓计入）
        if is_new_position and trade_log is not None:
            daily_new = _count_daily_new_cn_positions(trade_log, today)
            if daily_new >= CN_MAX_DAILY_NEW_POSITIONS:
                sys.exit(
                    f"[BLOCKED] 今日A股新建仓已达 {daily_new}/{CN_MAX_DAILY_NEW_POSITIONS} 笔上限 (v7.0 §3.2)。"
                    f"第3只等次日。交易取消。"
                )

        # 4. 每周交易总量 ≤ 8笔
        if trade_log is not None:
            weekly_count = _count_weekly_cn_trades(trade_log, today)
            if weekly_count >= CN_MAX_WEEKLY_TRADES:
                sys.exit(
                    f"[BLOCKED] 本周A股交易已达 {weekly_count}/{CN_MAX_WEEKLY_TRADES} 笔上限 (v7.0 §3.2)。"
                    f"暂停到下周。交易取消。"
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

    # ── 现金充足检查 ─────────────────────────────────────────────────────────
    if cost > cash:
        sym = "¥" if currency == "CNY" else "$"
        sys.exit(
            f"[ERROR] 现金不足。需要 {sym}{cost:,.2f}，可用 {sym}{cash:,.2f}。交易取消。"
        )

    # ── 现金≥20%检查（买入后）─────────────────────────────────────────────────
    total_assets = account.get("total_assets", 0)
    if total_assets > 0:
        remaining_cash = cash - cost
        cash_pct_after = remaining_cash / total_assets
        if cash_pct_after < 0.20:
            sym = "¥" if currency == "CNY" else "$"
            print(
                f"[WARN] 买入后现金将降至 {cash_pct_after:.1%}（低于20%下限）。"
                f"剩余: {sym}{remaining_cash:,.2f}"
            )
            # Warning only, not hard stop — agent decides

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
            # 美股：沿用通用上限 MAX_SINGLE_POSITION_PCT
            if pct > MAX_SINGLE_POSITION_PCT:
                sys.exit(
                    f"[ERROR] 买入后 {ticker} 持仓占比将达 {pct:.1%}，超过上限 {MAX_SINGLE_POSITION_PCT:.0%}。"
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

def execute_buy(state: dict, account_key: str, ticker: str, shares: int, price: float, reason: str):
    account = state["accounts"][account_key]
    currency = account["currency"]
    cost = round(shares * price, 4)

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
                    new_pos["stop_loss"] = round(price * 0.85, 2)
                    new_pos["stop_loss_note"] = f"fallback: fixed -15% (insufficient ATR data, need {_PERIOD} days)"
                    print(f"  [ATR] 数据不足，使用固定-15%止损: ${new_pos['stop_loss']:,.2f}")
            except Exception as _atr_err:
                new_pos["stop_loss"] = round(price * 0.85, 2)
                new_pos["stop_loss_note"] = f"fallback: fixed -15% (ATR fetch failed: {_atr_err})"
                print(f"  [ATR] 获取失败，使用固定-15%止损: ${new_pos['stop_loss']:,.2f}")

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

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    account_key = get_account_key(args.account)
    ticker = args.ticker.upper() if not args.ticker.isdigit() else args.ticker

    # 期权跳过 — only match option-like patterns (e.g. AAPL250620C00200000), not tickers containing "PUT"/"CALL"
    if len(ticker) > 10 and ("CALL" in ticker or "PUT" in ticker):
        print(f"[SKIP] {ticker} 识别为期权，跳过自动执行。")
        sys.exit(0)

    print(f"[INFO] 获取 {ticker} 实时价格...")
    price = fetch_price(ticker, account_key)
    print(f"[INFO] 成交价: {price}")

    # 加载状态（在价格获取成功后再加载，减少锁定时间）
    try:
        state = load_portfolio()
    except Exception as e:
        sys.exit(f"[ERROR] 无法读取 portfolio_state.json: {e}")

    account = state["accounts"][account_key]

    # 捕获交易前快照（用于 audit trail）
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

    # Sync to nexus-package dashboard
    try:
        sync_script = Path(__file__).parent / "sync_nexus.py"
        if sync_script.exists():
            result = subprocess.run(
                ["/Users/huaichuaibeimeng/.local/bin/uv", "run", "--script", str(sync_script)],
                cwd=Path(__file__).parent.parent, capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                print(f"⚠️ [sync] sync_nexus.py failed (exit {result.returncode}):")
                print(f"  stderr: {result.stderr[:300]}")
            else:
                print("[sync] ✓ nexus sync completed")
    except subprocess.TimeoutExpired:
        print("⚠️ [sync] sync_nexus.py timed out after 60s")
    except Exception as e:
        print(f"⚠️ [sync] sync_nexus.py error: {e}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print("[CRITICAL] 未预期错误，交易未执行:")
        traceback.print_exc()
        sys.exit(2)
