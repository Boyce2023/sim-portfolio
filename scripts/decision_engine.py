# /// script
# requires-python = ">=3.9"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""
Claude模拟盘 — 交易决策引擎 v1.0
被远程agent调用，生成结构化交易建议。Agent最终决定是否执行。

用法:
  python decision_engine.py                            # 从当前目录读标准文件
  python decision_engine.py --portfolio /path/portfolio_state.json \
                             --prices    /path/latest_prices.json \
                             --watchlist /path/watchlist_config.json \
                             --output    /path/decisions.json
  python decision_engine.py --dry-run                  # 打印到stdout，不写文件
"""

import argparse
import json
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────
# 常量 / 策略参数
# ─────────────────────────────────────────────
MAX_SINGLE_PCT = 0.15          # 单只上限 15%
MAX_SECTOR_PCT = 0.30          # 单板块上限 30%
MIN_CASH_PCT   = 0.20          # 现金下限 20%
MAX_NEW_POS_PER_DAY = 3        # 同日新建仓上限
STALE_DAYS     = 14            # 无催化剂超过N天 → FLAG
TRAILING_DEFAULT_PCT = 0.08    # 默认trailing stop：从高点回撤 8%

# 信心等级 → 仓位上限映射（strategy.md §仓位管理）
CONFIDENCE_MAX_PCT = {
    "A": 0.15,   # 核心持仓：10-15%
    "B": 0.10,   # 重点持仓：5-10%
    "C": 0.05,   # 观察仓：2-5%
    "T": 0.05,   # 交易性：2-5%
}
CONFIDENCE_TARGET_PCT = {
    "A": 0.12,
    "B": 0.07,
    "C": 0.03,
    "T": 0.03,
}

# 市场日历（与 market_calendar.json 保持一致；脚本也会尝试从文件加载）
_BUILTIN_NYSE_CLOSED = {"2026-05-25", "2026-06-19", "2026-07-03"}
_BUILTIN_SSE_CLOSED  = {"2026-05-31", "2026-06-01", "2026-06-02",
                         "2026-06-19", "2026-06-20", "2026-06-21"}


# ─────────────────────────────────────────────
# 路径常量
# ─────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

# OTC ticker mapping
YF_TICKER_MAP = {"SPUT": "SRUUF"}


def _us_yf(ticker: str) -> str:
    return YF_TICKER_MAP.get(ticker.upper(), ticker.upper())


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def load_json(path: Path) -> Optional[Any]:
    """读取JSON文件，失败返回None并打印警告。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[WARN] 文件不存在: {path}", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON解析失败 {path}: {e}", file=sys.stderr)
        return None


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def today_str() -> str:
    return date.today().isoformat()


def days_since(date_str: str) -> int:
    """从date_str到今天的天数，解析失败返回0。"""
    try:
        d = date.fromisoformat(date_str[:10])
        return (date.today() - d).days
    except Exception:
        return 0


def days_until(date_str: str) -> int:
    """从今天到date_str的天数，解析失败返回999。"""
    try:
        d = date.fromisoformat(date_str[:10])
        return (d - date.today()).days
    except Exception:
        return 999


def is_weekend() -> bool:
    return date.today().weekday() >= 5


# ─────────────────────────────────────────────
# 市场状态判断
# ─────────────────────────────────────────────

def load_market_calendar(base_dir: Path) -> dict:
    cal_path = base_dir / "market_calendar.json"
    cal = load_json(cal_path) or {}
    return {
        "nyse_closed": set(cal.get("nyse_closed", [])) | _BUILTIN_NYSE_CLOSED,
        "sse_closed":  set(cal.get("sse_szse_closed", [])) | _BUILTIN_SSE_CLOSED,
    }


def get_market_status(calendar: dict) -> dict:
    today = today_str()
    weekend = is_weekend()
    us_open = not weekend and today not in calendar["nyse_closed"]
    cn_open = not weekend and today not in calendar["sse_closed"]
    # 粗略判断当前时段（BJT，UTC+8）
    now_bj = datetime.now(timezone(timedelta(hours=8)))
    us_session = us_open and (21 <= now_bj.hour or now_bj.hour < 5)
    cn_session = cn_open and (9 <= now_bj.hour < 15)
    return {
        "us_open": us_open,
        "cn_open": cn_open,
        "us_session_now": us_session,
        "cn_session_now": cn_session,
        "today": today,
    }


# ─────────────────────────────────────────────
# 持仓分析工具
# ─────────────────────────────────────────────

def get_price(prices: dict, ticker: str, market: str) -> Optional[float]:
    """从latest_prices结构中取价格。"""
    if market == "us":
        return (prices.get("us") or {}).get(ticker, {}).get("price")
    else:
        # A股：先试原始ticker，再试带后缀
        cn = prices.get("cn") or {}
        if ticker in cn:
            return cn[ticker].get("price")
        for suffix in (".SS", ".SZ"):
            key = ticker + suffix
            if key in cn:
                return cn[key].get("price")
        return None


def calc_total_assets(account: dict, prices: dict, market: str) -> float:
    """计算账户总资产（现金 + 持仓市值）。"""
    total = float(account.get("cash", 0))
    for pos in account.get("positions", []):
        ticker = pos["ticker"]
        shares = pos.get("shares", 0)
        price  = get_price(prices, ticker, market)
        if price and shares:
            total += price * shares
        else:
            # Fallback: use current_price or avg_cost from position
            fallback = pos.get("current_price") or pos.get("avg_cost", 0)
            if fallback and shares:
                total += float(fallback) * shares
    return total


def get_sector_exposure(account: dict, prices: dict, market: str, total_assets: float) -> Dict[str, float]:
    """按sector汇总持仓占比。"""
    sector_val: dict[str, float] = {}
    for pos in account.get("positions", []):
        sector = pos.get("sector", "Unknown")
        shares = pos.get("shares", 0)
        price  = get_price(prices, pos["ticker"], market)
        # avg_cost is per-share; cost_basis is total — use avg_cost as fallback
        fallback = pos.get("current_price") or pos.get("avg_cost", 0)
        val    = (price or float(fallback)) * shares
        sector_val[sector] = sector_val.get(sector, 0) + val
    if total_assets <= 0:
        return {}
    return {s: round(v / total_assets * 100, 2) for s, v in sector_val.items()}


def count_new_positions_today(account: dict) -> int:
    """统计今日已新建仓数量（trade_log中今日buy记录）。"""
    today = today_str()
    count = 0
    for trade in account.get("trade_log", []):
        if (trade.get("date", "")[:10] == today
                and trade.get("action", "").upper() in ("BUY", "OPEN")):
            count += 1
    return count


# ─────────────────────────────────────────────
# ABCD下跌分类
# ─────────────────────────────────────────────

def classify_drawdown(pos: dict, prices: dict, market: str) -> str:
    """
    ABCD下跌分类（从strategy.md §ABCD）：
    A: 大盘拖累  B: 行业轮动  C: 叙事切换  D: 基本面变化
    需要position记录 'drawdown_class' 字段，否则返回 'UNKNOWN'。
    """
    return pos.get("drawdown_class", "UNKNOWN")


# ─────────────────────────────────────────────
# 卖出规则引擎
# ─────────────────────────────────────────────

def evaluate_sell_signals(account: dict, prices: dict, market: str, total_assets: float) -> list[dict]:
    """
    卖出规则：
    1. price <= stop_price           → SELL_ALL  (critical)
    2. price >= target_price         → SELL_50   (high)
    3. trailing stop触发             → SELL_ALL_REMAINING (high)
    4. 持仓 > 14天且无催化剂         → FLAG_REVIEW (medium)
    5. 单只占比 > 15%                → TRIM_TO_12PCT (medium)
    6. D类下跌（thesis证伪）         → SELL_ALL  (critical)
    """
    signals = []

    for pos in account.get("positions", []):
        ticker  = pos["ticker"]
        shares  = pos.get("shares", 0)
        if shares <= 0:
            continue

        price = get_price(prices, ticker, market)
        if price is None:
            signals.append({
                "ticker": ticker,
                "reason": "price_unavailable",
                "action": "MANUAL_CHECK",
                "priority": "medium",
                "detail": "无法获取最新价格，请手动确认",
            })
            continue

        # avg_cost is the per-share cost; cost_basis is total cost
        avg_cost     = float(pos.get("avg_cost", 0))
        cost_basis   = avg_cost  # use per-share avg_cost for P&L calcs
        # Support both stop_price and stop_loss field names
        stop_price   = pos.get("stop_price") or pos.get("stop_loss") or pos.get("stop")
        # Support target_price, target_1, target field names
        target_price = pos.get("target_price") or pos.get("target_1") or pos.get("target")
        high_close   = pos.get("high_close", price)     # 最高收盘价（用于trailing）
        trailing_pct = pos.get("trailing_stop_pct", TRAILING_DEFAULT_PCT)
        entry_date   = pos.get("entry_date", today_str())
        catalyst_date = pos.get("next_catalyst_date")
        held_days    = days_since(entry_date)
        pct_of_total = (price * shares / total_assets * 100) if total_assets > 0 else 0
        drawdown_class = classify_drawdown(pos, prices, market)

        # 规则1: 止损触发（最高优先）
        if stop_price and price <= stop_price:
            signals.append({
                "ticker": ticker,
                "reason": "stop_loss",
                "action": "SELL_ALL",
                "priority": "critical",
                "detail": f"价格 {price:.2f} <= 止损 {stop_price:.2f}",
                "shares": shares,
                "current_pct": round(pct_of_total, 2),
            })
            continue  # 已有critical，跳过其他规则

        # 规则6: D类下跌 — thesis被证伪
        if drawdown_class == "D":
            signals.append({
                "ticker": ticker,
                "reason": "thesis_invalidated_D_type",
                "action": "SELL_ALL",
                "priority": "critical",
                "detail": "D类下跌：thesis被证伪，无条件止损",
                "shares": shares,
                "current_pct": round(pct_of_total, 2),
            })
            continue

        # 规则3: Trailing stop触发
        trailing_trigger = high_close * (1 - trailing_pct)
        if pos.get("trailing_stop_active", False) and price <= trailing_trigger:
            remaining = pos.get("remaining_shares", shares)
            if remaining > 0:
                signals.append({
                    "ticker": ticker,
                    "reason": "trailing_stop",
                    "action": "SELL_ALL_REMAINING",
                    "priority": "high",
                    "detail": (f"价格 {price:.2f} <= trailing trigger {trailing_trigger:.2f} "
                               f"(高点 {high_close:.2f} × {1 - trailing_pct:.0%})"),
                    "shares": remaining,
                    "current_pct": round(pct_of_total, 2),
                })
                continue

        # 规则2: 达到目标价 → 卖出50%
        if target_price and price >= target_price:
            sell_shares = max(1, shares // 2)
            signals.append({
                "ticker": ticker,
                "reason": "target_reached",
                "action": "SELL_50",
                "priority": "high",
                "detail": (f"价格 {price:.2f} >= 目标 {target_price:.2f} "
                           f"(+{(price/cost_basis - 1)*100:.1f}%)，建议卖出50%并激活trailing stop"),
                "shares": sell_shares,
                "current_pct": round(pct_of_total, 2),
                "note": "卖出后在remaining上激活trailing_stop_active=True",
            })

        # 规则5: 单只超仓 → 减仓至12%
        if pct_of_total > 15.0:
            target_val   = total_assets * 0.12
            trim_shares  = max(0, shares - int(target_val / price))
            if trim_shares > 0:
                signals.append({
                    "ticker": ticker,
                    "reason": "overweight",
                    "action": "TRIM_TO_12PCT",
                    "priority": "medium",
                    "detail": f"持仓占比 {pct_of_total:.1f}% > 15%，减仓至12%",
                    "shares": trim_shares,
                    "current_pct": round(pct_of_total, 2),
                })

        # 规则4: 持仓 >14天且无催化剂
        if held_days > STALE_DAYS:
            has_upcoming = catalyst_date and days_until(catalyst_date) <= 30
            if not has_upcoming:
                signals.append({
                    "ticker": ticker,
                    "reason": "stale_no_catalyst",
                    "action": "FLAG_REVIEW",
                    "priority": "medium",
                    "detail": (f"持仓 {held_days} 天，30天内无催化剂，"
                               "请评估是否符合'2周无催化剂→退出'规则"),
                    "held_days": held_days,
                    "next_catalyst": catalyst_date,
                })

    # 按优先级排序：critical > high > medium > low
    _priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    signals.sort(key=lambda x: _priority_order.get(x.get("priority", "low"), 3))
    return signals


# ─────────────────────────────────────────────
# 买入规则引擎
# ─────────────────────────────────────────────

def evaluate_buy_candidates(
    account: dict,
    prices: dict,
    market: str,
    total_assets: float,
    watchlist: list[dict],
    sell_signals: list[dict],
) -> list[dict]:
    """
    买入规则：
    1. 只买watchlist里的标的
    2. 单只不超总资产15%
    3. 同板块不超30%
    4. 总现金不低于20%
    5. 同日新建仓不超3只
    [加仓规则]
    6. 已有持仓+thesis confirmed → 可加仓至上限（不在亏损状态，除非非D类下跌）
    """
    candidates = []
    if not watchlist:
        return candidates

    cash             = float(account.get("cash", 0))
    cash_pct         = cash / total_assets * 100 if total_assets > 0 else 100
    sector_exposure  = get_sector_exposure(account, prices, market, total_assets)
    new_today        = count_new_positions_today(account)
    existing_tickers = {pos["ticker"] for pos in account.get("positions", [])}

    # 已有critical卖出信号的ticker不建议新买
    sell_critical_tickers = {
        s["ticker"] for s in sell_signals if s.get("priority") == "critical"
    }

    # 现金不足20% → 不开新仓
    cash_ok = cash_pct >= MIN_CASH_PCT * 100

    for item in watchlist:
        ticker     = item.get("ticker", "")
        market_id  = item.get("market", market)  # watchlist可指定市场
        if market_id != market:
            continue

        if ticker in sell_critical_tickers:
            continue

        price = get_price(prices, ticker, market)
        # 允许无价格的标的进入候选，但标注
        price_ok = price is not None

        confidence   = item.get("confidence", "C")          # A/B/C/T
        sector       = item.get("sector", "Unknown")
        catalyst_str = item.get("next_catalyst", "")
        catalyst_date = item.get("next_catalyst_date", "")
        thesis_confirmed = item.get("thesis_confirmed", False)
        bear_case_pct    = item.get("bear_case_downside_pct", 999)

        # 硬规则：bear case downside > 20% 不建仓
        if bear_case_pct > 20:
            continue

        # 计算催化剂距今天数
        cat_days = days_until(catalyst_date) if catalyst_date else 999

        is_existing = ticker in existing_tickers

        # ── 加仓逻辑 ──────────────────────────────────────────────
        if is_existing:
            existing_pos = next(
                (p for p in account.get("positions", []) if p["ticker"] == ticker), {}
            )
            avg_cost   = float(existing_pos.get("avg_cost", price or 0))
            shares     = existing_pos.get("shares", 0)
            cur_price  = price or existing_pos.get("current_price") or avg_cost
            cur_val    = float(cur_price) * shares
            cur_pct    = cur_val / total_assets * 100 if total_assets > 0 else 0
            max_pct    = CONFIDENCE_MAX_PCT.get(confidence, 0.05) * 100

            # 不在亏损状态加仓（D类下跌外）
            drawdown_class = existing_pos.get("drawdown_class", "UNKNOWN")
            in_loss = price and price < avg_cost
            if in_loss and drawdown_class == "D":
                continue  # D类亏损不加仓
            if in_loss and not thesis_confirmed:
                continue  # 亏损且thesis未确认，不加仓

            if cur_pct >= max_pct:
                continue  # 已达上限

            add_room_pct = max_pct - cur_pct
            if not cash_ok or cash <= 0:
                continue

            # 加仓额度：min(room, 可用现金的50%)
            add_budget = min(add_room_pct / 100 * total_assets, cash * 0.5)
            suggested_shares = int(add_budget / price) if price else 0
            if suggested_shares <= 0:
                continue

            candidates.append({
                "ticker": ticker,
                "market": market,
                "action": "ADD",
                "reason": f"加仓: thesis_confirmed={thesis_confirmed}, 距催化剂 {cat_days}d",
                "catalyst": catalyst_str,
                "catalyst_date": catalyst_date,
                "suggested_shares": suggested_shares,
                "suggested_pct": round(add_room_pct, 2),
                "current_pct": round(cur_pct, 2),
                "confidence": confidence,
                "bear_case_downside_pct": bear_case_pct,
                "current_price": price,
            })
            continue

        # ── 新建仓逻辑 ─────────────────────────────────────────────
        # 当日新建仓上限
        if new_today >= MAX_NEW_POS_PER_DAY:
            continue

        # 现金不足
        if not cash_ok:
            continue

        # 板块超配
        sector_pct = sector_exposure.get(sector, 0)
        if sector_pct >= MAX_SECTOR_PCT * 100:
            continue

        # 计算建议仓位
        target_pct   = CONFIDENCE_TARGET_PCT.get(confidence, 0.03)
        buy_budget   = min(
            target_pct * total_assets,                   # 目标仓位
            cash * 0.8,                                  # 不超现金80%
            (MAX_SINGLE_PCT - 0) * total_assets,         # 单只上限
        )
        # 留足现金底线：买入后剩余现金 >= 20%
        max_spend = cash - MIN_CASH_PCT * total_assets
        buy_budget = min(buy_budget, max_spend)
        if buy_budget <= 0:
            continue

        suggested_shares = int(buy_budget / price) if price else 0
        if not price_ok:
            suggested_shares = 0  # 无价格时不给出具体数量

        candidates.append({
            "ticker": ticker,
            "market": market,
            "action": "BUY",
            "reason": (f"催化剂 {catalyst_str or '待确认'} | "
                       f"距今 {cat_days}d | confidence={confidence}"),
            "catalyst": catalyst_str,
            "catalyst_date": catalyst_date,
            "suggested_shares": suggested_shares,
            "suggested_pct": round(target_pct * 100, 1),
            "confidence": confidence,
            "bear_case_downside_pct": bear_case_pct,
            "current_price": price,
            "note": "" if price_ok else "无实时价格，shares仅供参考",
        })
        new_today += 1  # 本轮内计数，防止超过当日限额

    # 按催化剂紧迫性排序（越近越优先）
    candidates.sort(key=lambda x: (days_until(x.get("catalyst_date", "")), x.get("confidence", "C")))
    return candidates


# ─────────────────────────────────────────────
# 持有状态汇总
# ─────────────────────────────────────────────

def build_hold_notes(account: dict, prices: dict, market: str, total_assets: float,
                     sell_tickers: set[str]) -> list[dict]:
    """对当前持仓中未触发卖出信号的标的生成持有状态摘要。"""
    notes = []
    for pos in account.get("positions", []):
        ticker = pos["ticker"]
        if ticker in sell_tickers:
            continue  # 已有卖出信号，不重复出现在hold_notes

        shares      = pos.get("shares", 0)
        # avg_cost is per-share; cost_basis is total cost — use avg_cost for P&L
        avg_cost    = float(pos.get("avg_cost", 0))
        price       = get_price(prices, ticker, market)
        held_days   = days_since(pos.get("entry_date", today_str()))
        cat_date    = pos.get("next_catalyst_date", "") or pos.get("next_catalyst", "")[:10] if pos.get("next_catalyst") and pos.get("next_catalyst", "").startswith("2") else ""
        cat_str     = pos.get("next_catalyst", "")
        trailing_active = pos.get("trailing_stop_active", False)

        pnl_pct = ((price / avg_cost - 1) * 100) if (price and avg_cost) else None

        status = "ok"
        if held_days > STALE_DAYS and not cat_date:
            status = "review_needed"
        elif pnl_pct is not None and pnl_pct < -10:
            status = "monitor_loss"

        notes.append({
            "ticker": ticker,
            "market": market,
            "status": status,
            "shares": shares,
            "avg_cost": avg_cost,
            "current_price": price,
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "days_held": held_days,
            "trailing_stop_active": trailing_active,
            "next_catalyst": cat_str or cat_date or "未设定",
            "next_catalyst_date": cat_date,
        })
    return notes


# ─────────────────────────────────────────────
# 组合健康度
# ─────────────────────────────────────────────

def calc_portfolio_health(account: dict, prices: dict, market: str, total_assets: float) -> dict:
    cash = float(account.get("cash", 0))
    cash_pct = round(cash / total_assets * 100, 2) if total_assets > 0 else 100.0

    positions = account.get("positions", [])
    pos_values = []
    unrealized_vals = []
    for pos in positions:
        shares    = pos.get("shares", 0)
        avg_cost  = float(pos.get("avg_cost", 0))
        price     = get_price(prices, pos["ticker"], market)
        cur_price = price or pos.get("current_price") or avg_cost
        val       = float(cur_price) * shares
        pos_values.append(val)
        if price and avg_cost and shares:
            unrealized_vals.append((price - avg_cost) * shares)

    max_single_pct = round(max(pos_values) / total_assets * 100, 2) if (pos_values and total_assets > 0) else 0.0
    sector_exp     = get_sector_exposure(account, prices, market, total_assets)
    max_sector_pct = round(max(sector_exp.values()), 2) if sector_exp else 0.0
    total_unrealized = sum(unrealized_vals)
    initial_capital  = account.get("initial_capital", total_assets)
    unrealized_pct   = round(total_unrealized / initial_capital * 100, 2) if initial_capital > 0 else 0.0

    return {
        "cash": round(cash, 2),
        "cash_pct": cash_pct,
        "total_assets": round(total_assets, 2),
        "max_single_pct": max_single_pct,
        "max_sector_pct": max_sector_pct,
        "total_unrealized_pnl": round(total_unrealized, 2),
        "total_unrealized_pnl_pct": unrealized_pct,
        "position_count": len(positions),
        "sector_breakdown": sector_exp,
        "cash_rule_ok": cash_pct >= MIN_CASH_PCT * 100,
        "single_rule_ok": max_single_pct <= MAX_SINGLE_PCT * 100,
        "sector_rule_ok": max_sector_pct <= MAX_SECTOR_PCT * 100,
    }


# ─────────────────────────────────────────────
# 主决策函数
# ─────────────────────────────────────────────

def run_decision_engine(
    portfolio_path: Path,
    prices_path: Path,
    watchlist_path: Path,
    base_dir: Path,
) -> dict:
    # 1. 加载输入
    portfolio = load_json(portfolio_path) or {}
    prices    = load_json(prices_path)   or {}
    watchlist_cfg = load_json(watchlist_path) or {}

    accounts  = portfolio.get("accounts", {})
    us_acct   = accounts.get("us", {})
    cn_acct   = accounts.get("a_share", {})

    watchlist_us = [w for w in watchlist_cfg.get("watchlist", [])
                    if w.get("market", "us") == "us"]
    watchlist_cn = [w for w in watchlist_cfg.get("watchlist", [])
                    if w.get("market", "cn") == "cn"]

    # 2. 市场状态
    calendar = load_market_calendar(base_dir)
    market_status = get_market_status(calendar)

    # 3. 总资产计算（用于百分比计算）
    total_us = calc_total_assets(us_acct, prices, "us")
    total_cn = calc_total_assets(cn_acct, prices, "cn")

    # 4. 卖出信号
    sell_us = evaluate_sell_signals(us_acct, prices, "us", total_us)
    sell_cn = evaluate_sell_signals(cn_acct, prices, "cn", total_cn)
    all_sell = sell_us + sell_cn

    # 5. 买入候选
    sell_tickers_us = {s["ticker"] for s in sell_us}
    sell_tickers_cn = {s["ticker"] for s in sell_cn}

    buy_us = evaluate_buy_candidates(us_acct, prices, "us", total_us, watchlist_us, sell_us)
    buy_cn = evaluate_buy_candidates(cn_acct, prices, "cn", total_cn, watchlist_cn, sell_cn)
    all_buy = buy_us + buy_cn

    # 6. 持有摘要
    hold_us = build_hold_notes(us_acct, prices, "us", total_us, sell_tickers_us)
    hold_cn = build_hold_notes(cn_acct, prices, "cn", total_cn, sell_tickers_cn)
    all_hold = hold_us + hold_cn

    # 7. 组合健康度
    health_us = calc_portfolio_health(us_acct, prices, "us", total_us)
    health_cn = calc_portfolio_health(cn_acct, prices, "cn", total_cn)

    # 8. 组装输出
    output: Dict[str, Any] = {
        "date": today_str(),
        "generated_at": datetime.now().isoformat(),
        "engine_version": "1.0",
        "market_status": market_status,
        "sell_signals": all_sell,
        "buy_candidates": all_buy,
        "hold_notes": all_hold,
        "portfolio_health": {
            "us": health_us,
            "cn": health_cn,
            # 顶层快捷字段（与输出规范保持兼容）
            "cash_pct": health_us["cash_pct"],
            "max_single_pct": health_us["max_single_pct"],
            "max_sector_pct": health_us["max_sector_pct"],
            "total_unrealized_pnl_pct": health_us["total_unrealized_pnl_pct"],
        },
        "warnings": _collect_warnings(health_us, health_cn, all_sell),
        "meta": {
            "portfolio_path": str(portfolio_path),
            "prices_path": str(prices_path),
            "watchlist_path": str(watchlist_path),
            "sell_count": len(all_sell),
            "buy_count": len(all_buy),
            "hold_count": len(all_hold),
        },
    }
    return output


def _collect_warnings(health_us: dict, health_cn: dict, sell_signals: list[dict]) -> list[str]:
    """收集需要agent注意的系统级警告。"""
    warnings = []
    if not health_us["cash_rule_ok"]:
        warnings.append(f"[US] 现金占比 {health_us['cash_pct']:.1f}% < 20% 下限，禁止新建仓")
    if not health_cn["cash_rule_ok"]:
        warnings.append(f"[CN] 现金占比 {health_cn['cash_pct']:.1f}% < 20% 下限，禁止新建仓")
    if not health_us["single_rule_ok"]:
        warnings.append(f"[US] 单只最大持仓 {health_us['max_single_pct']:.1f}% > 15%，需减仓")
    if not health_cn["single_rule_ok"]:
        warnings.append(f"[CN] 单只最大持仓 {health_cn['max_single_pct']:.1f}% > 15%，需减仓")
    if not health_us["sector_rule_ok"]:
        warnings.append(f"[US] 板块集中度 {health_us['max_sector_pct']:.1f}% > 30%，留意板块风险")
    if not health_cn["sector_rule_ok"]:
        warnings.append(f"[CN] 板块集中度 {health_cn['max_sector_pct']:.1f}% > 30%，留意板块风险")
    critical_sells = [s for s in sell_signals if s.get("priority") == "critical"]
    if critical_sells:
        tickers = ", ".join(s["ticker"] for s in critical_sells)
        warnings.append(f"CRITICAL卖出信号: {tickers}，请优先处理")
    return warnings


# ─────────────────────────────────────────────
# CLI入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Claude模拟盘交易决策引擎 — 生成结构化买卖建议",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--portfolio", "-p",
        default=str(REPO_ROOT / "portfolio_state.json"),
        help="portfolio_state.json 路径",
    )
    parser.add_argument(
        "--prices", "-r",
        default=str(REPO_ROOT / "latest_prices.json"),
        help="latest_prices.json 路径",
    )
    parser.add_argument(
        "--watchlist", "-w",
        default=str(REPO_ROOT / "watchlist_config.json"),
        help="watchlist_config.json 路径 (可选，不存在时跳过买入候选评估)",
    )
    parser.add_argument(
        "--output", "-o",
        default=str(REPO_ROOT / "decisions.json"),
        help="输出文件路径",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="只打印到stdout，不写文件",
    )
    parser.add_argument(
        "--base-dir", "-b",
        default=None,
        help="市场日历等辅助文件的根目录 (默认: repo根目录)",
    )
    args = parser.parse_args()

    portfolio_path = Path(args.portfolio).resolve()
    prices_path    = Path(args.prices).resolve()
    watchlist_path = Path(args.watchlist).resolve()
    output_path    = Path(args.output).resolve()
    base_dir       = Path(args.base_dir).resolve() if args.base_dir else REPO_ROOT

    print(f"[决策引擎] {today_str()}", file=sys.stderr)
    print(f"  portfolio : {portfolio_path}", file=sys.stderr)
    print(f"  prices    : {prices_path}", file=sys.stderr)
    print(f"  watchlist : {watchlist_path}", file=sys.stderr)

    result = run_decision_engine(portfolio_path, prices_path, watchlist_path, base_dir)

    output_str = json.dumps(result, indent=2, ensure_ascii=False)

    if args.dry_run:
        print(output_str)
    else:
        save_json(output_path, result)
        print(f"[决策引擎] 输出已写入: {output_path}", file=sys.stderr)

    # 摘要打印
    ms = result["market_status"]
    print(
        f"[决策引擎] 完成 | "
        f"US {'开' if ms['us_open'] else '休'} | CN {'开' if ms['cn_open'] else '休'} | "
        f"卖出信号={result['meta']['sell_count']} | "
        f"买入候选={result['meta']['buy_count']} | "
        f"持仓监控={result['meta']['hold_count']}",
        file=sys.stderr,
    )
    for w in result.get("warnings", []):
        print(f"  ⚠ {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
