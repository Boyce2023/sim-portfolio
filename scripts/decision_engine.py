# /// script
# requires-python = ">=3.9"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""
Claude模拟盘 — 交易决策引擎 v3.0 (strategy v9.1 + V6.2)
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

try:
    from core.config import (
        ASTOCK_POSITION_LIMITS, US_POSITION_LIMITS,
        ASTOCK_SECTOR_LIMIT, ASTOCK_MAX_POSITIONS, ASTOCK_MAX_POSITIONS_FLEX,
        US_MAX_POSITIONS, LEVERAGED_ETF_NO_STOP,
    )
except ImportError:
    LEVERAGED_ETF_NO_STOP = frozenset()
    pass  # fallback below

# ─────────────────────────────────────────────
# 常量 / 策略参数
# ─────────────────────────────────────────────
# ── A股常量（strategy_astock.md v9.1）──────────────────────
MAX_SECTOR_PCT_CN  = ASTOCK_SECTOR_LIMIT if 'ASTOCK_SECTOR_LIMIT' in dir() else 1.00   # v9.1: 板块不做硬约束
MIN_CASH_PCT_CN    = 0.00      # v9.1: 无现金底线（用止损管风险）
MAX_TOTAL_POSITIONS_CN = ASTOCK_MAX_POSITIONS if 'ASTOCK_MAX_POSITIONS' in dir() else 8  # v9.1: ≤8只

# ── 美股常量（strategy.md 价值投资）──────────────────────────
MAX_SECTOR_PCT_US  = 2.00      # 美股杠杆账户，板块可达200%
MIN_CASH_PCT_US    = -1.00     # 美股杠杆账户，现金可为负（-100%）
MAX_TOTAL_POSITIONS_US = US_MAX_POSITIONS if 'US_MAX_POSITIONS' in dir() else 16

MAX_SINGLE_PCT = 0.50          # 单只上限50%（S级，两市通用）
MAX_NEW_POS_PER_DAY = 2        # 同日新建仓上限
# V7.0: Value investing holds for months/years. 14 days was way too short.
# US: 90 days (value positions need time). CN: 14 days (shorter-term system).
STALE_DAYS_US  = 90            # US: 无催化剂超过90天 → FLAG
STALE_DAYS_CN  = 14            # CN: 无催化剂超过14天 → FLAG (A股系统不变)
STALE_DAYS     = 14            # legacy fallback
TRAILING_DEFAULT_PCT = 0.08    # 默认trailing stop：从高点回撤 8%

# A股 SABCT v9.1 评级→仓位上限 (7级)
CONFIDENCE_MAX_PCT_CN = {
    "S":  0.50, "A+": 0.35, "A":  0.25, "A-": 0.20,
    "B+": 0.15, "B":  0.12, "B-": 0.10, "INDEX": 1.00,
}
CONFIDENCE_TARGET_PCT_CN = {
    "S":  0.35, "A+": 0.25, "A":  0.18, "A-": 0.14,
    "B+": 0.10, "B":  0.08, "B-": 0.07, "INDEX": 0.50,
}

# 美股 SABCT v3.0 评级→仓位上限 (strategy.md §3)
CONFIDENCE_MAX_PCT_US = {
    "S":  0.50, "A+": 0.35, "A":  0.25, "A-": 0.20,
    "B+": 0.15, "B":  0.12, "B-": 0.10, "C":  0.08, "INDEX": 1.00,
}
CONFIDENCE_TARGET_PCT_US = {
    "S":  0.35, "A+": 0.25, "A":  0.18, "A-": 0.14,
    "B+": 0.10, "B":  0.08, "B-": 0.06, "C":  0.05, "INDEX": 0.50,
}

if 'ASTOCK_POSITION_LIMITS' in dir():
    CONFIDENCE_MAX_PCT_CN.update(ASTOCK_POSITION_LIMITS)
if 'US_POSITION_LIMITS' in dir():
    CONFIDENCE_MAX_PCT_US.update(US_POSITION_LIMITS)

MAX_A_PLUS_POSITIONS_CN = 4    # A+/A/A-合计上限 4 个（SABCT v2.0，A股专属）
MAX_A_PLUS_POSITIONS_US = None  # 美股无此限制

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
    tdm = cal.get("trading_days_by_market", {})
    return {
        "nyse_closed": set(tdm.get("us_closed_dates", cal.get("nyse_closed", []))) | _BUILTIN_NYSE_CLOSED,
        "sse_closed":  set(tdm.get("cn_closed_dates", cal.get("sse_szse_closed", []))) | _BUILTIN_SSE_CLOSED,
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


def count_new_positions_today(account: dict, trade_log: Optional[List] = None) -> int:
    """统计今日已新建仓数量（从root trade_log读取，按account_key过滤）。
    trade_log: 从portfolio root读取的trade_log（account级别无此字段）。
    """
    today = today_str()
    count = 0
    # trade_log在portfolio root级别，不在account级别；account.get()永远返回[]
    source = trade_log or []
    # 确定账户key（用于过滤仅本账户的交易）
    account_currency = account.get("currency", "")
    account_key = "a_share" if account_currency == "CNY" else "us"
    for trade in source:
        if (trade.get("timestamp", trade.get("date", ""))[:10] == today
                and trade.get("action", "").lower() in ("buy", "open")
                and trade.get("account", "") == account_key):
            count += 1
    return count


# ─────────────────────────────────────────────
# Decision Chain 构建
# ─────────────────────────────────────────────

def build_decision_chain(
    trigger_type: str,
    trigger_description: str,
    ticker: str,
    action: str,
    pre_cash_pct: float,
    position_pct: float,
    total_assets: float,
    cash: float,
    bear_case_pct: Optional[float] = None,
    thesis_confirmed: Optional[bool] = None,
    catalyst: Optional[str] = None,
    catalyst_date: Optional[str] = None,
    confidence: Optional[str] = None,
    extra_notes: str = "",
    market: str = "us",
) -> dict:
    """
    构建结构化决策链，供 audit trail 使用。
    trigger_type: 'catalyst' | 'stop_loss' | 'target_reached' | 'trailing_stop' |
                  'overweight_trim' | 'stale_review' | 'thesis_invalidated' |
                  'momentum' | 'research' | 'manual'
    """
    # 估算交易后现金占比（粗算，execute_trade 执行后会用实际值覆盖）
    # 这里只做 pre-execution 预检，不需要精确
    # 按信心等级动态判断是否超仓（v9.1 SABCT）
    _confidence_limits = {"S": 0.50, "A+": 0.35, "A": 0.25, "A-": 0.20, "B+": 0.15, "B": 0.12, "B-": 0.10}
    _effective_limit = _confidence_limits.get(confidence or "B", 0.12)
    single_position_limit_ok = position_pct <= _effective_limit * 100
    _min_cash = MIN_CASH_PCT_CN if market == "cn" else MIN_CASH_PCT_US
    cash_minimum_ok = pre_cash_pct >= _min_cash * 100
    # bear_case_ok：extreme(>35%)才硬拒，其余分级处理（P1）
    bear_case_ok = (bear_case_pct is None) or (abs(bear_case_pct) <= 35)

    # Kelly sizing stub（尚无 kelly_sizing.py 时提供占位建议）
    _conf_map    = CONFIDENCE_MAX_PCT_CN    if market == "cn" else CONFIDENCE_MAX_PCT_US
    _target_map  = CONFIDENCE_TARGET_PCT_CN if market == "cn" else CONFIDENCE_TARGET_PCT_US
    kelly_suggestion: Optional[dict] = None
    if confidence in _target_map:
        kelly_suggestion = {
            "confidence_grade": confidence,
            "target_pct": round(_target_map[confidence] * 100, 1),
            "max_pct": round(_conf_map[confidence] * 100, 1),
            "method": "confidence_table",  # 升级为 kelly_sizing.py 后改为 'kelly_formula'
        }

    return {
        "trigger": {
            "type": trigger_type,
            "description": trigger_description,
            "source": "decision_engine",
            "catalyst": catalyst or "",
            "catalyst_date": catalyst_date or "",
        },
        "thesis_validation": {
            "confirmed": thesis_confirmed,
            "bear_case_downside_pct": bear_case_pct,
            "bear_case_ok": bear_case_ok,
        },
        "risk_check": {
            "pre_trade_cash_pct": round(pre_cash_pct, 2),
            "post_trade_cash_pct": None,   # 由 execute_trade 执行后填充
            "position_size_pct": round(position_pct, 2),
            "single_position_limit_ok": single_position_limit_ok,
            "cash_minimum_ok": cash_minimum_ok,
            "bear_case_pass": bear_case_ok,
        },
        "kelly_sizing": kelly_suggestion,
        "final_decision": {
            "approved": True,
            "approver": "decision_engine",
            "notes": extra_notes,
        },
    }


# ─────────────────────────────────────────────
# ABCD下跌分类
# ─────────────────────────────────────────────

def classify_drawdown(
    pos: dict,
    prices: dict,
    market: str,
    market_change_pct: float = 0.0,
    sector_change_pct: float = 0.0,
) -> str:
    """
    增强ABCD分类（P2，v2.0）：
    A: 市场跌>1.5%且个股跟跌（大盘系统性）
    B: 板块跌>2%但大盘平/涨（板块轮动噪音）
    C: 个股独跌且无新闻（叙事切换，需人工确认是否升D）
    D: 手动标记thesis证伪（不自动升级，必须人工确认）

    优先使用手动标记的 drawdown_class 字段；
    无手动标记时，用市场/板块变动参数自动分类。
    如无法获取价格或参数，降级返回 UNKNOWN。
    """
    # 手动标记优先（人工分类后不覆盖）
    manual = pos.get("drawdown_class")
    if manual and manual not in ("UNKNOWN", ""):
        return manual

    price = get_price(prices, pos["ticker"], market)
    avg_cost = pos.get("avg_cost", 0)

    if not price or not avg_cost:
        return "UNKNOWN"

    pnl_pct = (price / float(avg_cost) - 1) * 100
    if pnl_pct >= 0:
        return "NONE"  # 未在下跌中，无需分类

    # 止损触发：价格低于stop_price → 视同D类（立即清仓规则）
    stop_price = pos.get("stop_price") or pos.get("stop_loss") or pos.get("stop")
    if stop_price and price <= float(stop_price):
        return "D"

    # 自动分类（基于市场/板块参数）
    if market_change_pct < -1.5:
        return "A"
    if sector_change_pct < -2.0:
        return "B"
    # 默认C类（个股独跌，需人工判断是否升D）
    return "C"


# ─────────────────────────────────────────────
# Bear Case 分级（P1）
# ─────────────────────────────────────────────

# confidence等级顺序（数字越大越保守；A+最激进==0）
# v9.1: 废除S/C/T，新增A+/A-/B+/B-
_CONFIDENCE_ORDER = {"A+": 0, "A": 1, "A-": 2, "B+": 3, "B": 4, "B-": 5}

# A级组（A+/A/A-）合计上限3个
_A_GRADE_SET = {"A+", "A", "A-"}


def get_bear_case_grade(bear_case_pct: float) -> str:
    """
    四档bear case分级（F9 v2，strategy.md §2.5）：
    ≤15%  → safe     （T1绿灯：A+/A级可正常建仓）
    ≤25%  → elevated （T2黄灯：A级建仓需止损点；B级减半）
    ≤40%  → high     （T3橙灯：仅A级事件驱动可建，B级不建）
    >40%  → extreme  （T4红灯：排除做多）
    """
    abs_pct = abs(bear_case_pct) if bear_case_pct else 0
    if abs_pct <= 15:
        return "safe"
    if abs_pct <= 25:
        return "elevated"
    if abs_pct <= 40:
        return "high"
    return "extreme"


def max_confidence_for_bear_case(grade: str) -> Optional[str]:
    """bear case等级限制最高可用信心等级。返回None表示排除。"""
    # v9.1: safe→A+可用, elevated→最高A-, high→最高B-（事件驱动）, extreme→排除
    return {"safe": "A+", "elevated": "A-", "high": "B-", "extreme": None}[grade]


def cap_confidence_by_bear_case(confidence: str, bear_grade: str) -> Optional[str]:
    """
    按bear case等级对confidence降级（v7.0）。
    如果bear_grade==extreme，返回None（排除）。
    数字越小越激进（A+=0最激进，B-=5最保守）。
    原始confidence比允许上限更激进时，降级至bear_grade允许的上限。
    """
    max_conf = max_confidence_for_bear_case(bear_grade)
    if max_conf is None:
        return None  # extreme，排除
    orig_order = _CONFIDENCE_ORDER.get(confidence, 4)
    max_order  = _CONFIDENCE_ORDER.get(max_conf, 4)
    if orig_order >= max_order:
        return confidence  # 原始等级已经足够保守（或等于上限），不降级
    return max_conf  # 降级至bear_grade允许的上限（更保守）


# ─────────────────────────────────────────────
# 卖出规则引擎
# ─────────────────────────────────────────────

def evaluate_sell_signals(account: dict, prices: dict, market: str, total_assets: float) -> list[dict]:
    """
    卖出规则 V7.0 — 美股价值投资重构版：

    美股(market="us"): Thesis-based exit. 价格下跌≠卖出理由。
      1. thesis被证伪(D类)              → SELL_ALL (critical) — 唯一自动卖出触发
      2. 止损价触及                     → THESIS_REVIEW (high) — 强制review，不自动卖
      3. 目标价达到                     → CATALYST_CHAIN_CHECK (medium) — 检查催化剂链
      4. 杠杆ETF: 永不机械止损          → 仅thesis变化时退出
      5. 90天无催化剂                   → FLAG_REVIEW (low)
      6. 单只超仓                       → TRIM_TO_TARGET (medium)

    A股(market="cn"): 保持原有短线纪律，规则不变。
      1. price <= stop_price            → SELL_ALL (critical)
      2. price >= target_price          → SELL_50 (high)
      3. trailing stop                  → SELL_ALL_REMAINING (high)
      4. 14天无催化剂                   → FLAG_REVIEW (medium)
      5. 超仓                           → TRIM (medium)
      6. D类                            → SELL_ALL (critical)
    """
    signals = []
    account_cash = float(account.get("cash", 0))
    account_cash_pct = account_cash / total_assets * 100 if total_assets > 0 else 100.0

    # V7.0: Market-specific stale threshold
    _stale_days = STALE_DAYS_US if market == "us" else STALE_DAYS_CN

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
                "decision_chain": build_decision_chain(
                    trigger_type="manual",
                    trigger_description="价格不可用，需人工确认",
                    ticker=ticker,
                    action="MANUAL_CHECK",
                    pre_cash_pct=account_cash_pct,
                    position_pct=0.0,
                    total_assets=total_assets,
                    cash=account_cash,
                    extra_notes="yfinance返回None，跳过自动决策",
                    market=market,
                ),
            })
            continue

        avg_cost     = float(pos.get("avg_cost", 0))
        cost_basis   = avg_cost
        stop_price   = pos.get("stop_price") or pos.get("stop_loss") or pos.get("stop")
        target_price = pos.get("target_price") or pos.get("target_1") or pos.get("target")
        high_close   = pos.get("high_close", price)
        trailing_pct = pos.get("trailing_stop_pct", TRAILING_DEFAULT_PCT)
        entry_date   = pos.get("entry_date", today_str())
        catalyst_date = pos.get("next_catalyst_date")
        held_days    = days_since(entry_date)
        pct_of_total = (price * shares / total_assets * 100) if total_assets > 0 else 0
        drawdown_class = classify_drawdown(pos, prices, market)
        is_leveraged_etf = ticker.upper() in LEVERAGED_ETF_NO_STOP

        # ═══════════════════════════════════════════════════════════════
        # US VALUE INVESTING RULES (market="us")
        # ═══════════════════════════════════════════════════════════════
        if market == "us":
            # US Rule 1: D类thesis被证伪 → SELL_ALL (唯一自动卖出)
            if drawdown_class == "D":
                signals.append({
                    "ticker": ticker,
                    "reason": "thesis_invalidated_D_type",
                    "action": "SELL_ALL",
                    "priority": "critical",
                    "detail": "D类下跌：thesis被证伪，清仓",
                    "shares": shares,
                    "current_pct": round(pct_of_total, 2),
                    "decision_chain": build_decision_chain(
                        trigger_type="thesis_invalidated",
                        trigger_description="ABCD下跌分类=D，thesis被证伪",
                        ticker=ticker, action="SELL_ALL",
                        pre_cash_pct=account_cash_pct,
                        position_pct=round(pct_of_total, 2),
                        total_assets=total_assets, cash=account_cash,
                        extra_notes="D类下跌，thesis被证伪，清仓",
                        market=market,
                    ),
                })
                continue

            # US Rule 2: 杠杆ETF — 永不机械止损
            if is_leveraged_etf:
                if avg_cost > 0:
                    pnl_pct = (price - avg_cost) / avg_cost * 100
                    if pnl_pct < -30:
                        signals.append({
                            "ticker": ticker,
                            "reason": "leveraged_etf_deep_loss",
                            "action": "THESIS_REVIEW",
                            "priority": "medium",
                            "detail": (f"杠杆ETF {ticker} 浮亏 {pnl_pct:.1f}%。"
                                       f"V7.0: 不自动卖出。问题：thesis(行业周期)变了吗？"),
                            "current_pct": round(pct_of_total, 2),
                            "decision_chain": build_decision_chain(
                                trigger_type="manual",
                                trigger_description=f"杠杆ETF浮亏{pnl_pct:.1f}%，需thesis review",
                                ticker=ticker, action="THESIS_REVIEW",
                                pre_cash_pct=account_cash_pct,
                                position_pct=round(pct_of_total, 2),
                                total_assets=total_assets, cash=account_cash,
                                extra_notes="V7.0: 杠杆ETF不机械止损，thesis驱动退出",
                                market=market,
                            ),
                        })
                # Skip all other rules for leveraged ETFs
                continue

            # US Rule 3: 止损价触及 → THESIS_REVIEW (不自动卖！)
            if stop_price and price <= stop_price:
                signals.append({
                    "ticker": ticker,
                    "reason": "stop_advisory_hit",
                    "action": "THESIS_REVIEW",
                    "priority": "high",
                    "detail": (f"价格 ${price:.2f} <= 参考止损 ${stop_price:.2f}。"
                               f"V7.0: 不自动卖出。必须回答：thesis变了吗？以当前价你会新买吗？"),
                    "shares": shares,
                    "current_pct": round(pct_of_total, 2),
                    "decision_chain": build_decision_chain(
                        trigger_type="stop_loss",
                        trigger_description=f"价格 {price:.2f} 触及参考止损 {stop_price:.2f}",
                        ticker=ticker, action="THESIS_REVIEW",
                        pre_cash_pct=account_cash_pct,
                        position_pct=round(pct_of_total, 2),
                        total_assets=total_assets, cash=account_cash,
                        extra_notes="V7.0: 价值投资止损=thesis review，不自动执行",
                        market=market,
                    ),
                })
                # Don't skip other rules — stop hit is a review, not an action

            # US Rule 4: 目标价达到 → 检查催化剂链 (不自动卖)
            if target_price and price >= target_price:
                if price > target_price * 1.3:
                    signals.append({
                        "ticker": ticker,
                        "reason": "target_stale",
                        "action": "FLAG_TARGET_STALE",
                        "priority": "low",
                        "detail": (f"Price ${price:.2f} is {(price/target_price-1)*100:.0f}% above target "
                                   f"${target_price:.2f}. Update target or confirm catalyst chain."),
                        "current_pct": round(pct_of_total, 2),
                        "decision_chain": build_decision_chain(
                            trigger_type="target_reached",
                            trigger_description=f"价格远超目标价，需更新",
                            ticker=ticker, action="FLAG_TARGET_STALE",
                            pre_cash_pct=account_cash_pct,
                            position_pct=round(pct_of_total, 2),
                            total_assets=total_assets, cash=account_cash,
                            extra_notes="目标价过期，请更新",
                            market=market,
                        ),
                    })
                else:
                    signals.append({
                        "ticker": ticker,
                        "reason": "target_reached",
                        "action": "CATALYST_CHAIN_CHECK",
                        "priority": "medium",
                        "detail": (f"价格 ${price:.2f} >= 目标 ${target_price:.2f} "
                                   f"(+{(price/cost_basis - 1)*100:.1f}%)。"
                                   f"V7.0: 检查催化剂链——下一个催化剂<3月→持有，无后续→减仓"),
                        "current_pct": round(pct_of_total, 2),
                        "decision_chain": build_decision_chain(
                            trigger_type="target_reached",
                            trigger_description=f"价格达到目标价，检查催化剂链",
                            ticker=ticker, action="CATALYST_CHAIN_CHECK",
                            pre_cash_pct=account_cash_pct,
                            position_pct=round(pct_of_total, 2),
                            total_assets=total_assets, cash=account_cash,
                            extra_notes="V7.0: 不因涨多了卖。催化剂链完整→持有",
                            market=market,
                        ),
                    })

            # US Rule 5: 超仓trim (保留，这是风控不是恐慌)
            _conf_map_sell = CONFIDENCE_MAX_PCT_US
            pos_confidence = pos.get("confidence_grade") or pos.get("confidence") or pos.get("type", "B")
            _type_to_conf = {"core_position": "A", "catalyst_position": "B", "scout_position": "B-"}
            if pos_confidence not in _conf_map_sell:
                pos_confidence = _type_to_conf.get(pos_confidence, "B")
            _rebalance_limits  = {"S": 0.50, "A+": 0.35, "A": 0.25, "A-": 0.20, "B+": 0.15, "B": 0.12, "B-": 0.10}
            _rebalance_targets = {"S": 0.40, "A+": 0.28, "A": 0.20, "A-": 0.16, "B+": 0.12, "B": 0.10, "B-": 0.08}
            pos_limit_pct  = _rebalance_limits.get(pos_confidence, 0.15) * 100
            pos_target_pct = _rebalance_targets.get(pos_confidence, 0.12) * 100

            if pct_of_total > pos_limit_pct:
                target_val   = total_assets * (pos_target_pct / 100)
                trim_shares  = max(0, shares - int(target_val / price))
                if trim_shares > 0:
                    action_label = f"TRIM_TO_{int(pos_target_pct)}PCT"
                    signals.append({
                        "ticker": ticker,
                        "reason": "overweight",
                        "action": action_label,
                        "priority": "medium",
                        "detail": (f"持仓占比 {pct_of_total:.1f}% > {pos_confidence}级上限"
                                   f"{pos_limit_pct:.0f}%，减仓至{pos_target_pct:.0f}%"),
                        "shares": trim_shares,
                        "current_pct": round(pct_of_total, 2),
                        "decision_chain": build_decision_chain(
                            trigger_type="overweight_trim",
                            trigger_description=f"持仓占比 {pct_of_total:.1f}% 超过上限",
                            ticker=ticker, action=action_label,
                            pre_cash_pct=account_cash_pct,
                            position_pct=round(pct_of_total, 2),
                            total_assets=total_assets, cash=account_cash,
                            confidence=pos_confidence,
                            extra_notes=f"需减仓 {trim_shares} 股",
                            market=market,
                        ),
                    })

            # US Rule 6: 90天无催化剂 → flag (不急)
            if held_days > _stale_days:
                has_upcoming = catalyst_date and days_until(catalyst_date) <= 60
                if not has_upcoming:
                    signals.append({
                        "ticker": ticker,
                        "reason": "stale_no_catalyst",
                        "action": "FLAG_REVIEW",
                        "priority": "low",
                        "detail": (f"持仓 {held_days} 天，60天内无催化剂。"
                                   "价值投资可以长持，但需确认thesis仍然完整"),
                        "held_days": held_days,
                        "next_catalyst": catalyst_date,
                        "decision_chain": build_decision_chain(
                            trigger_type="stale_review",
                            trigger_description=f"持仓 {held_days} 天无近期催化剂",
                            ticker=ticker, action="FLAG_REVIEW",
                            pre_cash_pct=account_cash_pct,
                            position_pct=round(pct_of_total, 2),
                            total_assets=total_assets, cash=account_cash,
                            catalyst_date=catalyst_date,
                            extra_notes="V7.0: 价值投资允许长持，但需定期thesis review",
                            market=market,
                        ),
                    })

        # ═══════════════════════════════════════════════════════════════
        # A股 RULES (market="cn") — 保持原有短线纪律，不变
        # ═══════════════════════════════════════════════════════════════
        else:
            # CN Rule 1: 止损触发（最高优先）— A股保持机械止损
            if stop_price and price <= stop_price:
                signals.append({
                    "ticker": ticker,
                    "reason": "stop_loss",
                    "action": "SELL_ALL",
                    "priority": "critical",
                    "detail": f"价格 {price:.2f} <= 止损 {stop_price:.2f}",
                    "shares": shares,
                    "current_pct": round(pct_of_total, 2),
                    "decision_chain": build_decision_chain(
                        trigger_type="stop_loss",
                        trigger_description=f"价格 {price:.2f} 触及止损位 {stop_price:.2f}",
                        ticker=ticker, action="SELL_ALL",
                        pre_cash_pct=account_cash_pct,
                        position_pct=round(pct_of_total, 2),
                        total_assets=total_assets, cash=account_cash,
                        extra_notes="A股止损触发，无条件执行",
                        market=market,
                    ),
                })
                continue

            # CN Rule 6: D类下跌
            if drawdown_class == "D":
                signals.append({
                    "ticker": ticker,
                    "reason": "thesis_invalidated_D_type",
                    "action": "SELL_ALL",
                    "priority": "critical",
                    "detail": "D类下跌：thesis被证伪，无条件止损",
                    "shares": shares,
                    "current_pct": round(pct_of_total, 2),
                    "decision_chain": build_decision_chain(
                        trigger_type="thesis_invalidated",
                        trigger_description="ABCD下跌分类=D，thesis被证伪",
                        ticker=ticker, action="SELL_ALL",
                        pre_cash_pct=account_cash_pct,
                        position_pct=round(pct_of_total, 2),
                        total_assets=total_assets, cash=account_cash,
                        extra_notes="D类下跌，无条件清仓",
                        market=market,
                    ),
                })
                continue

            # CN Rule 3: Trailing stop触发 (A股保留)
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
                        "decision_chain": build_decision_chain(
                            trigger_type="trailing_stop",
                            trigger_description=f"价格 {price:.2f} 跌破 trailing trigger",
                            ticker=ticker, action="SELL_ALL_REMAINING",
                            pre_cash_pct=account_cash_pct,
                            position_pct=round(pct_of_total, 2),
                            total_assets=total_assets, cash=account_cash,
                            extra_notes=f"高点 {high_close:.2f}，回撤 {trailing_pct:.0%}",
                            market=market,
                        ),
                    })
                    continue

            # CN Rule 2: 达到目标价 → SELL_50 (A股保留两段式)
            if target_price and price >= target_price:
                if price > target_price * 1.3:
                    signals.append({
                        "ticker": ticker,
                        "reason": "target_stale",
                        "action": "FLAG_TARGET_STALE",
                        "priority": "medium",
                        "detail": f"Price {price:.2f} is {(price/target_price-1)*100:.0f}% above target",
                        "current_pct": round(pct_of_total, 2),
                        "decision_chain": build_decision_chain(
                            trigger_type="target_reached",
                            trigger_description="目标价过期",
                            ticker=ticker, action="FLAG_TARGET_STALE",
                            pre_cash_pct=account_cash_pct,
                            position_pct=round(pct_of_total, 2),
                            total_assets=total_assets, cash=account_cash,
                            extra_notes="目标价过期，不触发卖出",
                            market=market,
                        ),
                    })
                else:
                    sell_shares = max(1, shares // 2)
                    signals.append({
                        "ticker": ticker,
                        "reason": "target_reached",
                        "action": "SELL_50",
                        "priority": "high",
                        "detail": (f"价格 {price:.2f} >= 目标 {target_price:.2f} "
                                   f"(+{(price/cost_basis - 1)*100:.1f}%)"),
                        "shares": sell_shares,
                        "current_pct": round(pct_of_total, 2),
                        "note": "卖出后激活trailing_stop_active=True",
                        "decision_chain": build_decision_chain(
                            trigger_type="target_reached",
                            trigger_description=f"价格达到目标价",
                            ticker=ticker, action="SELL_50",
                            pre_cash_pct=account_cash_pct,
                            position_pct=round(pct_of_total, 2),
                            total_assets=total_assets, cash=account_cash,
                            extra_notes=f"盈利 +{(price/cost_basis - 1)*100:.1f}%",
                            market=market,
                        ),
                    })

            # CN Rule 5: 超仓trim
            _conf_map_sell = CONFIDENCE_MAX_PCT_CN
            pos_confidence = pos.get("confidence_grade") or pos.get("confidence") or pos.get("type", "B")
            _type_to_conf = {"core_position": "A", "catalyst_position": "B", "scout_position": "B-"}
            if pos_confidence not in _conf_map_sell:
                pos_confidence = _type_to_conf.get(pos_confidence, "B")
            _rebalance_limits  = {"S": 0.50, "A+": 0.35, "A": 0.25, "A-": 0.20, "B+": 0.15, "B": 0.12, "B-": 0.10}
            _rebalance_targets = {"S": 0.40, "A+": 0.28, "A": 0.20, "A-": 0.16, "B+": 0.12, "B": 0.10, "B-": 0.08}
            pos_limit_pct  = _rebalance_limits.get(pos_confidence, 0.15) * 100
            pos_target_pct = _rebalance_targets.get(pos_confidence, 0.12) * 100

            if pct_of_total > pos_limit_pct:
                target_val   = total_assets * (pos_target_pct / 100)
                trim_shares  = max(0, shares - int(target_val / price))
                if trim_shares > 0:
                    action_label = f"TRIM_TO_{int(pos_target_pct)}PCT"
                    signals.append({
                        "ticker": ticker,
                        "reason": "overweight",
                        "action": action_label,
                        "priority": "medium",
                        "detail": (f"持仓占比 {pct_of_total:.1f}% > {pos_confidence}级上限"
                                   f"{pos_limit_pct:.0f}%"),
                        "shares": trim_shares,
                        "current_pct": round(pct_of_total, 2),
                        "decision_chain": build_decision_chain(
                            trigger_type="overweight_trim",
                            trigger_description=f"持仓占比超过上限",
                            ticker=ticker, action=action_label,
                            pre_cash_pct=account_cash_pct,
                            position_pct=round(pct_of_total, 2),
                            total_assets=total_assets, cash=account_cash,
                            confidence=pos_confidence,
                            extra_notes=f"需减仓 {trim_shares} 股",
                            market=market,
                        ),
                    })

            # CN Rule 4: 14天无催化剂
            if held_days > _stale_days:
                has_upcoming = catalyst_date and days_until(catalyst_date) <= 30
                if not has_upcoming:
                    signals.append({
                        "ticker": ticker,
                        "reason": "stale_no_catalyst",
                        "action": "FLAG_REVIEW",
                        "priority": "medium",
                        "detail": (f"持仓 {held_days} 天，30天内无催化剂，"
                                   "请评估是否符合退出规则"),
                        "held_days": held_days,
                        "next_catalyst": catalyst_date,
                        "decision_chain": build_decision_chain(
                            trigger_type="stale_review",
                            trigger_description=f"持仓 {held_days} 天无近期催化剂",
                            ticker=ticker, action="FLAG_REVIEW",
                            pre_cash_pct=account_cash_pct,
                            position_pct=round(pct_of_total, 2),
                            total_assets=total_assets, cash=account_cash,
                            catalyst_date=catalyst_date,
                            extra_notes="需人工评估是否退出",
                            market=market,
                        ),
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
    trade_log: Optional[List] = None,
) -> list[dict]:
    """
    买入规则（v9.1）：
    1. 只买watchlist里的标的，且必须有SABCT评级和明确thesis
    2. 单只不超等级上限（S≤50%/A+≤35%/A≤25%/A-≤20%/B+≤15%/B≤12%/B-≤10%）
    3. 板块不做硬约束（用conviction和止损管风险）
    4. 现金无底线（用止损管风险不用现金管）
    5. 同日新建仓不超2只；持仓总数≤8
    6. A+/A/A-合计≤4个
    [加仓规则]
    7. 已有持仓+thesis confirmed → 可加仓至上限（不在亏损状态，除非非D类下跌）
    """
    candidates = []
    if not watchlist:
        return candidates

    cash             = float(account.get("cash", 0))
    cash_pct         = cash / total_assets * 100 if total_assets > 0 else 100
    sector_exposure  = get_sector_exposure(account, prices, market, total_assets)
    new_today        = count_new_positions_today(account, trade_log=trade_log)
    existing_tickers = {pos["ticker"] for pos in account.get("positions", [])}

    # 已有critical卖出信号的ticker不建议新买
    sell_critical_tickers = {
        s["ticker"] for s in sell_signals if s.get("priority") == "critical"
    }

    # A股：现金≥20%才允许新建仓；美股：无底线
    _min_cash_pct = MIN_CASH_PCT_CN if market == "cn" else MIN_CASH_PCT_US
    if _min_cash_pct > 0 and total_assets > 0:
        cash_ok = (cash / total_assets) >= _min_cash_pct
    else:
        cash_ok = True

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

        confidence   = item.get("confidence", "B")          # A+/A/A-/B+/B/B- (v9.1)
        sector       = item.get("sector", "Unknown")
        # 处理嵌套dict或plain string的next_catalyst
        next_cat = item.get("next_catalyst", "")
        if isinstance(next_cat, dict):
            catalyst_str = next_cat.get("event", "")
            catalyst_date = next_cat.get("date", "") or item.get("next_catalyst_date", "")
        else:
            catalyst_str = str(next_cat)
            catalyst_date = item.get("next_catalyst_date", "")
        # in_portfolio的标的默认thesis已确认
        thesis_confirmed = item.get("thesis_confirmed",
                                    item.get("status") == "in_portfolio")
        bear_case_pct    = item.get("bear_case_downside_pct", 999)

        # P1: Bear case分级处理（替换二元20%排除规则）
        bear_grade = get_bear_case_grade(bear_case_pct)
        effective_confidence = cap_confidence_by_bear_case(confidence, bear_grade)
        if effective_confidence is None:
            # extreme (>35%)：排除做多
            continue
        # 记录是否因bear case降级
        bear_case_downgraded = (effective_confidence != confidence)
        if bear_case_downgraded:
            confidence = effective_confidence  # 降级后的confidence用于后续计算

        # v9.1 A级组上限检查：A+/A/A-合计≤4个（A股），美股无此限制
        _max_a = MAX_A_PLUS_POSITIONS_CN if market == "cn" else MAX_A_PLUS_POSITIONS_US
        if _max_a is not None and confidence in _A_GRADE_SET:
            existing_a_grade_count = sum(
                1 for pos in account.get("positions", [])
                if (pos.get("confidence_grade") or pos.get("confidence", "")) in _A_GRADE_SET
            )
            if existing_a_grade_count >= _max_a:
                continue  # A级组已满，不可新建

        # v9.1 总持仓数上限：≤8只
        current_position_count = len(account.get("positions", []))

        # 计算催化剂距今天数
        cat_days = days_until(catalyst_date) if catalyst_date else 999

        # 过期催化剂过滤：催化剂日期已过 → 跳过（不再是有效买入信号）
        if catalyst_date and cat_days < 0:
            continue  # expired catalyst, no longer a valid buy signal

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
            _conf_map  = CONFIDENCE_MAX_PCT_CN if market == "cn" else CONFIDENCE_MAX_PCT_US
            max_pct    = _conf_map.get(confidence, 0.05) * 100

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
            if cash <= 0:
                continue

            # 加仓额度：min(room, 可用现金的50%)
            add_budget = min(add_room_pct / 100 * total_assets, cash * 0.5)
            suggested_shares = int(add_budget / price) if price else 0
            if suggested_shares <= 0:
                continue

            _orig_conf_add = item.get("confidence", "B")
            _dg_note_add   = (
                f"bear case {bear_case_pct}% → {bear_grade}，confidence从{_orig_conf_add}降至{confidence}"
                if bear_case_downgraded else ""
            )
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
                "bear_case_grade": bear_grade,
                "confidence_downgraded": bear_case_downgraded,
                "original_confidence": _orig_conf_add if bear_case_downgraded else None,
                "current_price": price,
                "note": _dg_note_add or "",
                "decision_chain": build_decision_chain(
                    trigger_type="research",
                    trigger_description=f"加仓: thesis_confirmed={thesis_confirmed}, 距催化剂 {cat_days}d",
                    ticker=ticker,
                    action="ADD",
                    pre_cash_pct=cash_pct,
                    position_pct=round(cur_pct, 2),
                    total_assets=total_assets,
                    cash=cash,
                    bear_case_pct=bear_case_pct,
                    thesis_confirmed=thesis_confirmed,
                    catalyst=catalyst_str,
                    catalyst_date=catalyst_date,
                    confidence=confidence,
                    extra_notes=(
                        f"加仓空间 {add_room_pct:.1f}%，建议 {suggested_shares} 股"
                        + (f"；{_dg_note_add}" if _dg_note_add else "")
                    ),
                    market=market,
                ),
            })
            continue

        # ── 新建仓逻辑 ─────────────────────────────────────────────
        # 当日新建仓上限：≤2只/天
        if new_today >= MAX_NEW_POS_PER_DAY:
            continue

        _max_pos = MAX_TOTAL_POSITIONS_CN if market == "cn" else MAX_TOTAL_POSITIONS_US
        if current_position_count >= _max_pos:
            continue

        # 无现金可用
        if cash <= 0:
            continue

        # 计算建议仓位（按confidence分级单只上限，P0）
        _conf_map_buy    = CONFIDENCE_MAX_PCT_CN    if market == "cn" else CONFIDENCE_MAX_PCT_US
        _target_map_buy  = CONFIDENCE_TARGET_PCT_CN if market == "cn" else CONFIDENCE_TARGET_PCT_US
        target_pct   = _target_map_buy.get(confidence, 0.05)
        _conf_max    = _conf_map_buy.get(confidence, 0.08)
        buy_budget   = min(
            target_pct * total_assets,    # 目标仓位
            cash * 0.8,                   # 不超现金80%
            _conf_max * total_assets,     # 分级单只上限
        )
        if buy_budget <= 0:
            continue

        suggested_shares = int(buy_budget / price) if price else 0
        if not price_ok:
            suggested_shares = 0  # 无价格时不给出具体数量

        _orig_confidence = item.get("confidence", "B")
        _downgrade_note  = (
            f"bear case {bear_case_pct}% → {bear_grade}，confidence从{_orig_confidence}降至{confidence}"
            if bear_case_downgraded else ""
        )
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
            "bear_case_grade": bear_grade,
            "confidence_downgraded": bear_case_downgraded,
            "original_confidence": _orig_confidence if bear_case_downgraded else None,
            "current_price": price,
            "note": _downgrade_note or ("" if price_ok else "无实时价格，shares仅供参考"),
            "decision_chain": build_decision_chain(
                trigger_type="catalyst",
                trigger_description=(
                    f"催化剂 {catalyst_str or '待确认'} | 距今 {cat_days}d"
                ),
                ticker=ticker,
                action="BUY",
                pre_cash_pct=cash_pct,
                position_pct=0.0,  # 新建仓，当前占比为0
                total_assets=total_assets,
                cash=cash,
                bear_case_pct=bear_case_pct,
                thesis_confirmed=thesis_confirmed,
                catalyst=catalyst_str,
                catalyst_date=catalyst_date,
                confidence=confidence,
                extra_notes=(
                    f"目标仓位 {round(target_pct * 100, 1)}%，建议 {suggested_shares} 股"
                    + (f"；{_downgrade_note}" if _downgrade_note else "")
                ),
                market=market,
            ),
        })
        new_today += 1  # 本轮内计数，防止超过当日限额

    # 按催化剂紧迫性排序（越近越优先）
    candidates.sort(key=lambda x: (days_until(x.get("catalyst_date", "")), x.get("confidence", "C")))
    return candidates


# ─────────────────────────────────────────────
# 持有状态汇总
# ─────────────────────────────────────────────

def build_hold_notes(account: dict, prices: dict, market: str, total_assets: float,
                     sell_tickers: set,
                     pending_signals: Optional[List] = None,
                     trump_tickers: Optional[set] = None,
                     ous_data: Optional[dict] = None) -> list[dict]:
    """对当前持仓中未触发卖出信号的标的生成持有状态摘要。"""
    notes = []
    _pending_signals = pending_signals or []
    _trump_tickers = trump_tickers or set()
    _ous_data = ous_data or {}

    # Build a lookup: ticker → list of signal summaries that mention it
    _ticker_signal_map: Dict[str, List[str]] = {}
    for sig in _pending_signals:
        for affected_ticker in sig.get("affected_tickers", []):
            _ticker_signal_map.setdefault(affected_ticker, []).append(
                f"[{sig.get('type', 'signal')}] {sig.get('summary', '')}"
            )

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

        note: Dict[str, Any] = {
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
        }

        # Nexus signal flag: add signal_flag if ticker appears in pending signals
        if ticker in _ticker_signal_map:
            note["signal_flag"] = _ticker_signal_map[ticker]

        # Trump portfolio overlap flag
        if ticker in _trump_tickers:
            note["trump_overlap"] = True

        # OUS enrichment: F21 signal and PEG value
        if ticker in _ous_data:
            ous_entry = _ous_data[ticker]
            ous_signal: Dict[str, Any] = {}
            if "f21_signal" in ous_entry:
                ous_signal["f21_signal"] = ous_entry["f21_signal"]
            if "peg" in ous_entry:
                ous_signal["peg"] = ous_entry["peg"]
            elif "peg_ratio" in ous_entry:
                ous_signal["peg"] = ous_entry["peg_ratio"]
            if ous_signal:
                note["ous_signal"] = ous_signal

        notes.append(note)
    return notes


# ─────────────────────────────────────────────
# 类别均衡度（OUS三分类：mainline/offnarr_tech/non_tech）
# ─────────────────────────────────────────────

def calc_category_balance(account: dict, prices: dict, market: str, total_assets: float,
                          ticker_category_map: Dict[str, str]) -> dict:
    """Calculate portfolio's distribution across OUS categories."""
    cat_weights: Dict[str, float] = {"mainline": 0.0, "offnarr_tech": 0.0, "non_tech": 0.0, "uncategorized": 0.0}
    cat_counts: Dict[str, int] = {"mainline": 0, "offnarr_tech": 0, "non_tech": 0, "uncategorized": 0}

    for pos in account.get("positions", []):
        ticker = pos["ticker"]
        if ticker in ("QQQ", "SPY", "TQQQ", "SQQQ"):
            continue  # skip ETFs
        shares = pos.get("shares", 0)
        price = get_price(prices, ticker, market) or float(pos.get("avg_cost", 0))
        val = float(price) * shares
        cat = ticker_category_map.get(ticker, "uncategorized")
        if cat not in cat_weights:
            cat = "uncategorized"
        cat_weights[cat] += val
        cat_counts[cat] += 1

    total_stock_val = sum(cat_weights.values())
    cat_pcts = {}
    for cat, val in cat_weights.items():
        cat_pcts[cat] = round(val / total_stock_val * 100, 1) if total_stock_val > 0 else 0.0

    # Anti-echo-chamber check: non_tech weight should be >= 10% for balanced portfolio
    anti_echo_ok = cat_pcts.get("non_tech", 0) >= 10.0

    recommendation = None
    if not anti_echo_ok:
        recommendation = f"科技外类别占比{cat_pcts.get('non_tech', 0):.1f}%(<10%), 建议增加非科技标的(反茧房)"

    return {
        "weights_pct": cat_pcts,
        "counts": cat_counts,
        "anti_echo_chamber_ok": anti_echo_ok,
        "recommendation": recommendation,
    }


# ─────────────────────────────────────────────
# 组合健康度
# ─────────────────────────────────────────────

def calc_portfolio_health(account: dict, prices: dict, market: str, total_assets: float) -> dict:
    cash = float(account.get("cash", 0))
    cash_pct = round(cash / total_assets * 100, 2) if total_assets > 0 else 100.0

    positions = account.get("positions", [])
    pos_values = []
    pos_values_ex_index = []
    unrealized_vals = []
    for pos in positions:
        shares    = pos.get("shares", 0)
        avg_cost  = float(pos.get("avg_cost", 0))
        price     = get_price(prices, pos["ticker"], market)
        cur_price = price or pos.get("current_price") or avg_cost
        val       = float(cur_price) * shares
        pos_values.append(val)
        if pos.get("conviction_level") != "INDEX":
            pos_values_ex_index.append(val)
        if price and avg_cost and shares:
            unrealized_vals.append((price - avg_cost) * shares)

    check_vals = pos_values_ex_index or pos_values
    max_single_pct = round(max(check_vals) / total_assets * 100, 2) if (check_vals and total_assets > 0) else 0.0
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
        "cash_rule_ok": cash_pct >= (MIN_CASH_PCT_CN if market == "cn" else MIN_CASH_PCT_US) * 100,
        "single_rule_ok": max_single_pct <= MAX_SINGLE_PCT * 100,
        "sector_rule_ok": max_sector_pct <= (MAX_SECTOR_PCT_CN if market == "cn" else MAX_SECTOR_PCT_US) * 100,
    }


# ─────────────────────────────────────────────
# 主决策函数
# ─────────────────────────────────────────────

def run_decision_engine(
    portfolio_path: Path,
    prices_path: Path,
    watchlist_path: Path,
    base_dir: Path,
    market: str = "all",
) -> dict:
    # 1. 加载输入
    portfolio = load_json(portfolio_path) or {}
    prices    = load_json(prices_path)   or {}
    watchlist_cfg = load_json(watchlist_path) or {}

    accounts  = portfolio.get("accounts", {})
    us_acct   = accounts.get("us", {})
    cn_acct   = accounts.get("a_share", {})
    trade_log = portfolio.get("trade_log", [])  # root-level trade_log

    watchlist_us = watchlist_cfg.get("us_watchlist", [])
    watchlist_cn = watchlist_cfg.get("cn_watchlist", [])

    # 1a. 加载Regime（来自nexus truth store）— 美股regime
    REGIME_PATH = Path.home() / ".claude/nexus/truth/macro/regime.json"
    regime = "unknown"
    if REGIME_PATH.exists():
        try:
            regime_data = json.loads(REGIME_PATH.read_text())
            cr = regime_data.get("current_regime", {})
            regime = cr.get("regime", regime_data.get("regime", "unknown"))
        except Exception:
            pass

    # 1a2. 加载A股Regime（来自astock_regime.py写入）
    ASTOCK_REGIME_PATH = Path.home() / ".claude/nexus/truth/macro/astock_regime.json"
    astock_regime = "unknown"
    if ASTOCK_REGIME_PATH.exists():
        try:
            astock_regime_data = json.loads(ASTOCK_REGIME_PATH.read_text())
            astock_regime = astock_regime_data.get("current_regime", {}).get("regime", "unknown")
        except Exception:
            pass
    if astock_regime == "unknown":
        print(f"[WARN] A股Regime未加载（{ASTOCK_REGIME_PATH}），使用fallback=unknown", file=sys.stderr)

    # 1b. 加载Nexus pending signals
    SIGNALS_DIR = Path.home() / ".claude/nexus/signals/pending"
    _EXIT_KEYWORDS = {"止盈", "龙头崩", "exit", "退出", "止损", "sell", "清仓", "减仓"}
    pending_signals = []
    nexus_exit_signals: list[dict] = []   # 退出类信号（纳入sell_signals）
    nexus_signals_consumed = 0
    if SIGNALS_DIR.exists():
        for sig_file in sorted(SIGNALS_DIR.glob("sig-*.json")):
            try:
                sig = json.loads(sig_file.read_text())
                priority = sig.get("priority", "low")
                # 只处理 critical / high 信号
                if priority not in ("critical", "high"):
                    continue
                nexus_signals_consumed += 1
                sig_summary = sig.get("summary", "")
                sig_type = sig.get("type", "")
                affected_tickers = sig.get("affected_tickers", [])

                # 判断是否为退出信号
                is_exit = any(
                    kw in sig_summary.lower() or kw in sig_type.lower()
                    for kw in _EXIT_KEYWORDS
                )

                sig_entry = {
                    "id": sig.get("id"),
                    "type": sig_type,
                    "priority": priority,
                    "summary": sig_summary[:100],
                    "affected_tickers": affected_tickers,
                    "source": str(sig_file.name),
                }
                pending_signals.append(sig_entry)

                # 退出信号 → 为每个受影响ticker生成 sell_signal
                if is_exit and affected_tickers:
                    for ticker in affected_tickers:
                        nexus_exit_signals.append({
                            "ticker": ticker,
                            "reason": "nexus_exit_signal",
                            "action": "SELL_ALL" if priority == "critical" else "FLAG_REVIEW",
                            "priority": priority,
                            "detail": f"[Nexus] {sig_type}: {sig_summary[:80]}",
                            "nexus_signal_id": sig.get("id"),
                            "nexus_signal_source": str(sig_file.name),
                        })
            except Exception:
                pass
    else:
        print(f"[WARN] Nexus signals目录不存在: {SIGNALS_DIR}", file=sys.stderr)

    # 1c. 加载OUS扫描结果（PEG/F21数据富化）
    OUS_PATH = REPO_ROOT / "ous_scan_results.json"
    ous_data: Dict[str, Any] = {}
    if OUS_PATH.exists():
        try:
            ous_raw = json.loads(OUS_PATH.read_text())
            for item in ous_raw.get("results", []):
                if item.get("ticker"):
                    ous_data[item["ticker"]] = item
        except Exception:
            pass

    # 1c2. Build ticker→category map from OUS universe
    OUS_UNIVERSE_PATH = REPO_ROOT / "ous_universe.json"
    ticker_category_map: Dict[str, str] = {}
    if OUS_UNIVERSE_PATH.exists():
        try:
            ous_uni = json.loads(OUS_UNIVERSE_PATH.read_text())
            for stock in ous_uni.get("stocks", []):
                ticker_category_map[stock["ticker"]] = stock.get("category", "unknown")
        except Exception:
            pass

    # 1d. 加载Trump portfolio overlay
    TRUMP_PATH = Path.home() / ".claude/nexus/truth/macro/trump_portfolio.json"
    trump_tickers: set = set()
    if TRUMP_PATH.exists():
        try:
            trump_data = json.loads(TRUMP_PATH.read_text())
            for h in trump_data.get("holdings", []):
                if h.get("in_trump_portfolio"):
                    trump_tickers.add(h.get("ticker", ""))
        except Exception:
            pass

    # 2. 市场状态
    calendar = load_market_calendar(base_dir)
    market_status = get_market_status(calendar)

    run_us = market in ("us", "all")
    run_cn = market in ("cn", "all")

    # 3. 总资产计算（用于百分比计算）
    total_us = calc_total_assets(us_acct, prices, "us") if run_us else 0.0
    total_cn = calc_total_assets(cn_acct, prices, "cn") if run_cn else 0.0

    # 4. 卖出信号
    sell_us = evaluate_sell_signals(us_acct, prices, "us", total_us) if run_us else []
    sell_cn = evaluate_sell_signals(cn_acct, prices, "cn", total_cn) if run_cn else []

    # 4a. A股Regime感知：BEAR模式时向A股卖出信号注入regime警告
    if run_cn and astock_regime == "bear":
        # 在A股持仓review类信号上添加regime标注（不新增sell，仅附注）
        for sig in sell_cn:
            if sig.get("priority") in ("medium", "low"):
                sig.setdefault("astock_regime_note", f"当前A股Regime={astock_regime}，建议从严执行止损")

    # 4b. 注入Nexus退出信号（A股+美股，按affected_tickers归类）
    # 退出信号按市场路由：ticker在cn_acct中→归cn，在us_acct→归us
    cn_tickers = {pos["ticker"] for pos in cn_acct.get("positions", [])}
    us_tickers = {pos["ticker"] for pos in us_acct.get("positions", [])}
    for exit_sig in nexus_exit_signals:
        t = exit_sig["ticker"]
        if run_cn and t in cn_tickers:
            sell_cn.append(exit_sig)
        elif run_us and t in us_tickers:
            sell_us.append(exit_sig)
        # ticker不在持仓中时跳过（观察池标的不生成sell signal）

    all_sell = sell_us + sell_cn

    # 5. 买入候选
    sell_tickers_us = {s["ticker"] for s in sell_us}
    sell_tickers_cn = {s["ticker"] for s in sell_cn}

    buy_us = evaluate_buy_candidates(us_acct, prices, "us", total_us, watchlist_us, sell_us, trade_log=trade_log) if run_us else []
    buy_cn = evaluate_buy_candidates(cn_acct, prices, "cn", total_cn, watchlist_cn, sell_cn, trade_log=trade_log) if run_cn else []
    all_buy = buy_us + buy_cn

    # 6. 持有摘要
    hold_us = build_hold_notes(us_acct, prices, "us", total_us, sell_tickers_us,
                                pending_signals=pending_signals, trump_tickers=trump_tickers,
                                ous_data=ous_data) if run_us else []
    hold_cn = build_hold_notes(cn_acct, prices, "cn", total_cn, sell_tickers_cn,
                                pending_signals=pending_signals, trump_tickers=trump_tickers,
                                ous_data=ous_data) if run_cn else []
    all_hold = hold_us + hold_cn

    # 7. 组合健康度
    health_us = calc_portfolio_health(us_acct, prices, "us", total_us) if run_us else {}
    health_cn = calc_portfolio_health(cn_acct, prices, "cn", total_cn) if run_cn else {}

    # 7a. Category balance (US only)
    category_balance_us = {}
    if run_us and ticker_category_map:
        category_balance_us = calc_category_balance(us_acct, prices, "us", total_us, ticker_category_map)

    # 8. 组装输出
    if market == "cn":
        portfolio_health: Dict[str, Any] = {
            "cn": health_cn,
            "cn_cash_pct": health_cn.get("cash_pct"),
            "cn_max_single_pct": health_cn.get("max_single_pct"),
            "cn_max_sector_pct": health_cn.get("max_sector_pct"),
            "cn_total_unrealized_pnl_pct": health_cn.get("total_unrealized_pnl_pct"),
        }
    elif market == "us":
        portfolio_health = {
            "us": health_us,
            "cash_pct": health_us.get("cash_pct"),
            "max_single_pct": health_us.get("max_single_pct"),
            "max_sector_pct": health_us.get("max_sector_pct"),
            "total_unrealized_pnl_pct": health_us.get("total_unrealized_pnl_pct"),
        }
    else:  # "all"
        portfolio_health = {
            "us": health_us,
            "cn": health_cn,
            # 顶层快捷字段（US，与输出规范保持兼容）
            "cash_pct": health_us.get("cash_pct"),
            "max_single_pct": health_us.get("max_single_pct"),
            "max_sector_pct": health_us.get("max_sector_pct"),
            "total_unrealized_pnl_pct": health_us.get("total_unrealized_pnl_pct"),
            # 顶层CN快捷字段（D3-L1修复，防止agent遗漏A股风控）
            "cn_cash_pct": health_cn.get("cash_pct"),
            "cn_max_single_pct": health_cn.get("max_single_pct"),
            "cn_max_sector_pct": health_cn.get("max_sector_pct"),
            "cn_total_unrealized_pnl_pct": health_cn.get("total_unrealized_pnl_pct"),
        }

    output: Dict[str, Any] = {
        "date": today_str(),
        "generated_at": datetime.now().isoformat(),
        "engine_version": "3.1",  # strategy v9.1 + astock_regime + nexus exit signals
        "market": market,
        "regime": regime,
        "astock_regime": astock_regime,
        "market_status": market_status,
        "sell_signals": all_sell,
        "buy_candidates": all_buy,
        "hold_notes": all_hold,
        "portfolio_health": portfolio_health,
        "category_balance": category_balance_us if run_us else {},
        "pending_signals": pending_signals,
        "nexus_signals_consumed": nexus_signals_consumed,
        "warnings": _collect_warnings(health_us, health_cn, all_sell, astock_regime=astock_regime, market=market),
        "meta": {
            "portfolio_path": str(portfolio_path),
            "prices_path": str(prices_path),
            "watchlist_path": str(watchlist_path),
            "sell_count": len(all_sell),
            "buy_count": len(all_buy),
            "hold_count": len(all_hold),
            "pending_signal_count": len(pending_signals),
            "nexus_signals_consumed": nexus_signals_consumed,
            "nexus_exit_signals_injected": len(nexus_exit_signals),
            "regime_source": str(REGIME_PATH) if REGIME_PATH.exists() else "not_found",
            "astock_regime_source": str(ASTOCK_REGIME_PATH) if ASTOCK_REGIME_PATH.exists() else "not_found",
        },
    }
    return output


def _collect_warnings(
    health_us: dict,
    health_cn: dict,
    sell_signals: list[dict],
    astock_regime: str = "unknown",
    market: str = "all",
) -> list[str]:
    """收集需要agent注意的系统级警告。单市场模式只警告该市场。"""
    warnings = []
    if market in ("us", "all") and health_us and not health_us.get("single_rule_ok", True):
        warnings.append(f"[US] 单只最大持仓 {health_us['max_single_pct']:.1f}% > 50%（S级上限），需减仓")
    if market in ("cn", "all") and health_cn and not health_cn.get("single_rule_ok", True):
        warnings.append(f"[CN] 单只最大持仓 {health_cn['max_single_pct']:.1f}% > 50%（S级上限），需减仓")
    # A股Regime警告
    if market in ("cn", "all") and astock_regime == "bear":
        warnings.append("[CN] A股Regime=BEAR：市场处于熊市regime，建议收缩仓位、严格止损")
    elif market in ("cn", "all") and astock_regime == "sideways":
        warnings.append("[CN] A股Regime=NEUTRAL：市场中性，新建仓需催化剂驱动")
    critical_sells = [s for s in sell_signals if s.get("priority") == "critical"]
    if critical_sells:
        tickers = ", ".join(s["ticker"] for s in critical_sells)
        warnings.append(f"CRITICAL卖出信号: {tickers}，请优先处理")
    # Nexus退出信号警告
    nexus_crits = [s for s in sell_signals
                   if s.get("reason") == "nexus_exit_signal" and s.get("priority") == "critical"]
    if nexus_crits:
        tickers = ", ".join(s["ticker"] for s in nexus_crits)
        warnings.append(f"[Nexus] CRITICAL退出信号: {tickers}，来自退出信号检测器")
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
    parser.add_argument(
        "--market", "-m",
        choices=["cn", "us", "all"],
        default="all",
        help="只评估指定市场 (default: all)",
    )
    args = parser.parse_args()

    portfolio_path = Path(args.portfolio).resolve()
    prices_path    = Path(args.prices).resolve()
    watchlist_path = Path(args.watchlist).resolve()
    base_dir       = Path(args.base_dir).resolve() if args.base_dir else REPO_ROOT

    # Determine output path based on market flag (unless --output was explicitly provided)
    _default_output = str(REPO_ROOT / "decisions.json")
    if args.output != _default_output:
        output_path = Path(args.output).resolve()
    elif args.market == "cn":
        output_path = REPO_ROOT / "decisions_cn.json"
    elif args.market == "us":
        output_path = REPO_ROOT / "decisions_us.json"
    else:
        output_path = REPO_ROOT / "decisions.json"

    print(f"[决策引擎] {today_str()} | market={args.market}", file=sys.stderr)
    print(f"  portfolio : {portfolio_path}", file=sys.stderr)
    print(f"  prices    : {prices_path}", file=sys.stderr)
    print(f"  watchlist : {watchlist_path}", file=sys.stderr)

    result = run_decision_engine(portfolio_path, prices_path, watchlist_path, base_dir, market=args.market)

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
        f"Regime US={result['regime']} | A股={result['astock_regime']} | "
        f"卖出信号={result['meta']['sell_count']} | "
        f"买入候选={result['meta']['buy_count']} | "
        f"持仓监控={result['meta']['hold_count']} | "
        f"Nexus信号={result['nexus_signals_consumed']}(退出注入={result['meta']['nexus_exit_signals_injected']})",
        file=sys.stderr,
    )
    for w in result.get("warnings", []):
        print(f"  [W] {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
