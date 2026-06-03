# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "rich>=13.0", "akshare>=1.12.0", "requests>=2.28.0"]
# ///
"""
风控监控脚本 — Claude模拟盘
读取 portfolio_state.json，执行全套风控检查。
不依赖 watchlist_config.json（从portfolio本身读取止损/目标价）。
Critical alert 时以 EXIT CODE 1 退出。

用法:
    uv run --script scripts/risk_monitor.py
    uv run --script scripts/risk_monitor.py --no-save
    uv run --script scripts/risk_monitor.py --no-fetch
"""

from __future__ import annotations

import json
import sys
import argparse
import time
from datetime import datetime, date
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal, Optional

import requests
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.text import Text

# ──────────────────────────────────────────────────────────────────────────────
# 路径配置
# ──────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio_state.json"
WATCHLIST_PATH = PROJECT_ROOT / "watchlist_config.json"
REPORTS_DIR = PROJECT_ROOT / "daily-reviews"

console = Console()

# ═══ 风控阈值 — A股/美股完全分离 (v9.1) ═══
# A股: strategy_astock.md v9.1 — 无现金底线/无板块上限/持仓≤8
# 美股: strategy.md — 无现金底线/S级可达50%
MAX_SINGLE_PCT = 50.0       # S级可达50% (两市通用上限)
MAX_SECTOR_PCT = 100.0      # legacy全局值(不再使用，被market-specific覆盖)
MIN_CASH_PCT = 0.0          # legacy全局值(不再使用，被market-specific覆盖)
MIN_CASH_PCT_CN = 0.0       # A股: v9.1无现金底线
MIN_CASH_PCT_US = -100.0    # 美股: 杠杆账户，现金可为负（保证金）
MAX_PORTFOLIO_DRAWDOWN = -10.0  # 组合回撤触发线 %
STOP_BUFFER_PCT = 5.0       # 接近止损线警戒区 %
try:
    from core.config import (ASTOCK_MAX_POSITIONS, ASTOCK_MAX_POSITIONS_FLEX,
                             US_MAX_POSITIONS)
except ImportError:
    ASTOCK_MAX_POSITIONS = 8       # v9.1
    ASTOCK_MAX_POSITIONS_FLEX = 8  # v9.1: 无弹性概念
    US_MAX_POSITIONS = 12

# Circuit Breaker 阈值（基于 peak NAV 回撤）
CB_WARN_DD = -5.0           # WARNING: 暂停新建仓
CB_CRITICAL_DD = -15.0      # CRITICAL: review stop-losses, trim highest-beta
CB_EMERGENCY_DD = -20.0     # EMERGENCY: evaluate thesis, reduce to core positions

# VIX 阈值
VIX_WARN = 25.0             # WARNING: 波动升高，检查止损距离 (raised from 20 — anti-aggression fix)
VIX_EMERGENCY = 35.0        # 现金≥70%, 只允许defensive

# Enhanced Stop 阈值（覆盖原 STOP_BUFFER_PCT）
STOP_ALERT_PCT = 3.0        # < 3% 距止损 → ALERT

# Concentration: 同 sector > N 只 → concentration risk
MAX_SECTOR_POSITIONS = 5

# ── Sector PCT — 两市均不做板块硬约束 ──
MAX_SECTOR_PCT_CN = 1.00    # A股: v9.1板块不做硬约束
MAX_SECTOR_PCT_US = 2.00    # 美股: 杠杆账户，板块可达200%

# ── Enhancement: Bear case 4-tier thresholds (US market) ──
# Tier definitions from watchlist_config.json portfolio_rules.bear_case_grade_us
BEAR_TIER_SAFE_LIMIT = -15.0        # bear_case_downside_pct > -15%   → Safe
BEAR_TIER_ELEVATED_LIMIT = -25.0    # -25% < bear ≤ -15%              → Elevated (max B- grade: ≤10%, v7.0废除C级)
BEAR_TIER_HIGH_LIMIT = -35.0        # -35% < bear ≤ -25%              → High (max B- grade: ≤10%, v7.0废除T级)
                                    # bear ≤ -35%                      → Extreme (exclude)

BEAR_TIER_HIGH_MAX_PCT = 10.0       # High tier: hard cap B- (10%) regardless of grade
# Elevated tier: uses position's SABCT grade limit (not flat cap)
SABCT_GRADE_LIMITS = {
    "S":  50.0, "A+": 35.0, "A":  25.0, "A-": 20.0,
    "B+": 15.0, "B":  12.0, "B-": 10.0, "C":  8.0, "INDEX": 100.0,
}

# ── Enhancement: S-grade holding period (v7.0: S级已废除，此检查仅保留为遗留兼容，CN端不会触发) ──
S_GRADE_MAX_TRADING_DAYS = 10       # S-grade positions held > 10 trading days → CRITICAL

# ── Enhancement: Catalyst proximity windows ──
CATALYST_HIGH_DAYS = 2              # ≤ 2 days → HIGH alert
CATALYST_INFO_DAYS = 7              # ≤ 7 days → INFO alert

# ── Enhancement: Broad sector correlation buckets ──
# Any broad bucket with > 3 positions → sector correlation risk
BROAD_SECTOR_BUCKETS: dict[str, list[str]] = {
    "tech/semiconductor": [
        "AI芯片", "半导体封装", "半导体材料", "先进封装",
        "AI芯片/半导体", "SaaS/AI Agent", "软件/SaaS",
        "AI搜索/云计算", "消费科技/硬件",
        "PCB/苹果链", "PCB/AI服务器",
    ],
    "energy": [
        "铀/核能", "HALEU/核燃料", "电力设备/燃气轮机",
        "数据中心电气配电", "数据中心配电",
        "电力设备", "储能/光伏逆变器",
    ],
    "commodity": [
        "铜矿/大宗商品", "黄金/贵金属", "铀/大宗商品",
    ],
}
MAX_BROAD_SECTOR_POSITIONS = 3

# OTC ticker mapping
YF_TICKER_MAP = {"SPUT": "SRUUF"}

# ──────────────────────────────────────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────────────────────────────────────
AlertLevel = Literal["critical", "high", "medium", "warning", "info"]


@dataclass
class Alert:
    level: AlertLevel
    ticker: str
    rule: str
    detail: str
    value: Optional[float] = None
    threshold: Optional[float] = None


@dataclass
class RiskReport:
    generated_at: str
    alerts: list[Alert] = field(default_factory=list)
    us_total_assets: float = 0.0
    cn_total_assets: float = 0.0
    us_cash: float = 0.0
    cn_cash: float = 0.0
    us_cash_pct: float = 0.0
    cn_cash_pct: float = 0.0
    us_drawdown_pct: float = 0.0
    cn_drawdown_pct: float = 0.0
    position_summaries: list[dict] = field(default_factory=list)
    sector_weights: dict[str, float] = field(default_factory=dict)
    vix_value: Optional[float] = None
    us_peak_nav: Optional[float] = None
    cn_peak_nav: Optional[float] = None
    us_cb_dd_pct: Optional[float] = None
    cn_cb_dd_pct: Optional[float] = None
    health_score: int = 100  # 0-100 portfolio health score

    @property
    def has_critical(self) -> bool:
        return any(a.level == "critical" for a in self.alerts)

    @property
    def criticals(self) -> list[Alert]:
        return [a for a in self.alerts if a.level == "critical"]

    @property
    def warnings(self) -> list[Alert]:
        return [a for a in self.alerts if a.level == "warning"]

    @property
    def highs(self) -> list[Alert]:
        return [a for a in self.alerts if a.level == "high"]

    @property
    def mediums(self) -> list[Alert]:
        return [a for a in self.alerts if a.level == "medium"]


# ──────────────────────────────────────────────────────────────────────────────
# 数据加载
# ──────────────────────────────────────────────────────────────────────────────
def load_portfolio() -> dict:
    if not PORTFOLIO_PATH.exists():
        console.print(f"[red]ERROR: portfolio_state.json not found at {PORTFOLIO_PATH}[/red]")
        sys.exit(2)
    with open(PORTFOLIO_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_watchlist() -> dict:
    """Load watchlist_config.json. Returns empty dict if not found."""
    if not WATCHLIST_PATH.exists():
        return {}
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        return json.load(f)


# ──────────────────────────────────────────────────────────────────────────────
# 实时价格获取
# ──────────────────────────────────────────────────────────────────────────────
def _cn_suffix(ticker: str) -> str:
    return ticker + ".SS" if ticker.startswith("6") else ticker + ".SZ"


def _us_yf(ticker: str) -> str:
    return YF_TICKER_MAP.get(ticker.upper(), ticker.upper())


def _fetch_price_cn_akshare(code: str) -> Optional[float]:
    """Fetch A-stock price via akshare (primary source). Returns None on failure."""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == code]
        if not row.empty:
            price = float(row["最新价"].iloc[0])
            if price > 0:
                return price
    except Exception:
        pass
    return None


# Module-level cache for akshare spot data (shared across all CN tickers in one run)
_akshare_spot_cache: Optional[object] = None


def _get_akshare_spot() -> Optional[object]:
    """Fetch the full akshare spot DataFrame once and cache it for this run."""
    global _akshare_spot_cache
    if _akshare_spot_cache is not None:
        return _akshare_spot_cache
    try:
        import akshare as ak
        _akshare_spot_cache = ak.stock_zh_a_spot_em()
        return _akshare_spot_cache
    except Exception:
        return None


def _fetch_price_cn_push2delay(code: str) -> Optional[float]:
    """Fetch A-stock price via Eastmoney push2delay API (fallback). Returns None on failure."""
    try:
        secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
        url = (
            f"https://push2delay.eastmoney.com/api/qt/stock/get"
            f"?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f170"
        )
        resp = requests.get(url, timeout=5).json()
        raw = resp.get("data", {}).get("f43")
        if raw is not None and raw > 0:
            return float(raw) / 100  # f43 is in 分
    except Exception:
        pass
    return None


def _fetch_price_cn_yfinance(code: str) -> Optional[float]:
    """Fetch A-stock price via yfinance (last resort). Returns None on failure."""
    yf_sym = _cn_suffix(code)
    for attempt in range(3):
        try:
            info = yf.Ticker(yf_sym).fast_info
            price = info.last_price
            if price and price > 0:
                return float(price)
            hist = yf.Ticker(yf_sym).history(period="1d", auto_adjust=True)
            if not hist.empty:
                p = float(hist["Close"].iloc[-1])
                if p > 0:
                    return p
        except Exception:
            pass
        if attempt < 2:
            time.sleep(1.5)
    return None


def _fetch_price_cn(code: str) -> tuple[Optional[float], str]:
    """
    Fetch A-stock price with source fallback chain:
      akshare (primary) → push2delay (backup) → yfinance (last resort)
    Returns (price_or_None, source_label).
    Uses cached akshare DataFrame when available.
    """
    # Try akshare via shared cache first
    df = _get_akshare_spot()
    if df is not None:
        try:
            row = df[df["代码"] == code]
            if not row.empty:
                price = float(row["最新价"].iloc[0])
                if price > 0:
                    return price, "akshare"
        except Exception:
            pass

    # Fallback: push2delay
    price = _fetch_price_cn_push2delay(code)
    if price is not None:
        return price, "push2delay"

    # Last resort: yfinance
    price = _fetch_price_cn_yfinance(code)
    if price is not None:
        return price, "yfinance(last-resort)"

    return None, "failed"


def _fetch_price_us(yf_ticker: str, retries: int = 3) -> Optional[float]:
    """Fetch US stock / ETF / index price via yfinance. Returns None on failure."""
    for attempt in range(retries):
        try:
            info = yf.Ticker(yf_ticker).fast_info
            price = info.last_price
            if price and price > 0:
                return float(price)
            # Fallback to history
            hist = yf.Ticker(yf_ticker).history(period="1d", auto_adjust=True)
            if not hist.empty:
                p = float(hist["Close"].iloc[-1])
                if p > 0:
                    return p
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(1.5)
    return None


# Keep _fetch_price as an alias for backward compatibility (used by US path)
def _fetch_price(yf_ticker: str, retries: int = 3) -> Optional[float]:
    return _fetch_price_us(yf_ticker, retries)


def fetch_current_prices(
    positions_us: list[dict],
    positions_cn: list[dict],
) -> dict[str, Optional[float]]:
    """
    Returns {original_ticker: price_or_None}.
    A-stock: akshare (primary) → push2delay (backup) → yfinance (last resort).
    US stocks / VIX: yfinance (unchanged).
    Fetches all tickers using a thread pool; akshare bulk data is pre-fetched once.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Pre-warm akshare cache once before parallel fetch (avoids N concurrent akshare calls)
    if positions_cn:
        _get_akshare_spot()

    # Build task list: (orig_ticker, is_cn)
    tasks_us: list[tuple[str, str]] = []
    tasks_cn: list[str] = []

    for pos in positions_us:
        if pos.get("instrument_type") == "call_option":
            continue
        ticker = pos["ticker"]
        tasks_us.append((ticker, _us_yf(ticker)))

    for pos in positions_cn:
        tasks_cn.append(pos["ticker"])

    prices: dict[str, Optional[float]] = {}
    source_log: list[str] = []

    def _do_us(item: tuple[str, str]) -> tuple[str, Optional[float], str]:
        orig, yf_sym = item
        price = _fetch_price_us(yf_sym)
        return orig, price, "yfinance"

    def _do_cn(code: str) -> tuple[str, Optional[float], str]:
        price, src = _fetch_price_cn(code)
        return code, price, src

    all_futures = []
    with ThreadPoolExecutor(max_workers=min(len(tasks_us) + len(tasks_cn) + 1, 8)) as pool:
        for t in tasks_us:
            all_futures.append(pool.submit(_do_us, t))
        for code in tasks_cn:
            all_futures.append(pool.submit(_do_cn, code))

        for fut in as_completed(all_futures):
            orig, price, src = fut.result()
            prices[orig] = price
            source_log.append(f"{orig}:{src}")

    if source_log:
        console.print(f"[dim]价格来源: {', '.join(source_log)}[/dim]")

    return prices


# ──────────────────────────────────────────────────────────────────────────────
# 风控规则引擎
# ──────────────────────────────────────────────────────────────────────────────
def _effective_price(pos: dict, live: dict[str, Optional[float]]) -> float:
    """Live price → current_price field → avg_cost."""
    ticker = pos["ticker"]
    p = live.get(ticker)
    if p and p > 0:
        return p
    p2 = pos.get("current_price")
    if p2 and p2 > 0:
        return float(p2)
    return float(pos.get("avg_cost", 0))


def _calc_total_assets(account: dict, positions: list[dict], live: dict) -> float:
    cash = float(account.get("cash", 0))
    long_value = 0.0
    short_pnl = 0.0
    for p in positions:
        if p.get("instrument_type") == "call_option":
            continue
        shares = p.get("shares", 0)
        price = _effective_price(p, live)
        if shares >= 0:
            long_value += price * shares
        else:
            entry_price = float(p.get("avg_cost", price))
            short_pnl += (entry_price - price) * abs(shares)
    return cash + long_value + short_pnl


# ─── Rule checkers ────────────────────────────────────────────────────────────

def _check_cash(cash: float, total: float, label: str, alerts: list[Alert], market: str = "cn") -> float:
    if total <= 0:
        return 0.0
    pct = cash / total * 100
    min_cash = MIN_CASH_PCT_CN if market == "cn" else MIN_CASH_PCT_US
    if min_cash > 0 and pct < min_cash:
        alerts.append(Alert(
            level="warning", ticker=label, rule="现金不足",
            detail=f"现金比例 {pct:.1f}%，最低 {min_cash:.0f}%",
            value=pct, threshold=min_cash,
        ))
    return round(pct, 2)


def _check_drawdown(initial: float, total: float, label: str, alerts: list[Alert]) -> float:
    if initial <= 0:
        return 0.0
    dd = (total / initial - 1) * 100
    if dd < MAX_PORTFOLIO_DRAWDOWN:
        alerts.append(Alert(
            level="critical", ticker=label, rule="组合回撤超限",
            detail=f"回撤 {dd:.1f}%，触发线 {MAX_PORTFOLIO_DRAWDOWN:.0f}%",
            value=dd, threshold=MAX_PORTFOLIO_DRAWDOWN,
        ))
    return round(dd, 2)


def _check_position(
    pos: dict,
    total: float,
    live: dict,
    is_cn: bool,
    alerts: list[Alert],
) -> dict:
    """Check single position weight and stop-loss proximity. Returns summary dict."""
    ticker = pos["ticker"]
    shares = pos.get("shares", 0)
    price = _effective_price(pos, live)
    market_value = price * shares
    weight_pct = (market_value / total * 100) if total > 0 else 0.0

    # Weight check — INDEX级别(ETF)不受单只上限约束
    conviction = pos.get("conviction_level", "")
    if conviction != "INDEX" and weight_pct > MAX_SINGLE_PCT:
        alerts.append(Alert(
            level="warning", ticker=ticker, rule="单仓超限",
            detail=f"持仓占比 {weight_pct:.1f}%，上限 {MAX_SINGLE_PCT:.0f}%",
            value=weight_pct, threshold=MAX_SINGLE_PCT,
        ))

    # Stop-loss checks using portfolio data directly
    avg_cost = float(pos.get("avg_cost", 0))
    stop_loss = pos.get("stop_loss") or pos.get("stop")
    target = pos.get("target_1") or pos.get("target")

    is_short = shares < 0

    if avg_cost > 0 and price > 0:
        pnl_pct = ((price - avg_cost) / avg_cost * 100) if not is_short else ((avg_cost - price) / avg_cost * 100)

        if stop_loss and stop_loss > 0:
            if is_short:
                stop_triggered = price >= stop_loss
                dist_to_stop_pct = (stop_loss - price) / price * 100 if not stop_triggered else 0
                stop_detail_op = "≥"
                cover_cmd = (
                    f"uv run --script scripts/execute_trade.py cover "
                    f"{'--account cn' if is_cn else '--account us'} --ticker {ticker} --all "
                    f'--reason "空头止损触发: 现价{price:.2f}{stop_detail_op}止损{stop_loss:.2f}"'
                )
            else:
                stop_triggered = price <= stop_loss
                dist_to_stop_pct = (price - stop_loss) / price * 100 if not stop_triggered else 0
                stop_detail_op = "≤"
                cover_cmd = (
                    f"uv run --script scripts/execute_trade.py sell "
                    f"{'--account cn' if is_cn else '--account us'} --ticker {ticker} --all "
                    f'--reason "止损触发: 现价{price:.2f}{stop_detail_op}止损{stop_loss:.2f}"'
                )

            if stop_triggered:
                alerts.append(Alert(
                    level="critical", ticker=ticker, rule="止损触发",
                    detail=(
                        f"现价 {price:.2f} {stop_detail_op} 止损 {stop_loss:.2f}，"
                        f"P&L {pnl_pct:+.1f}%。立即执行：{cover_cmd}"
                    ),
                    value=price, threshold=stop_loss,
                ))
            else:
                if dist_to_stop_pct < STOP_ALERT_PCT:
                    alerts.append(Alert(
                        level="critical", ticker=ticker, rule="止损临界 — ALERT",
                        detail=(
                            f"现价 {price:.2f}，止损 {stop_loss:.2f}，"
                            f"距止损仅 {dist_to_stop_pct:.1f}% (<{STOP_ALERT_PCT:.0f}%)。"
                            " 准备止损执行命令，密切监控。"
                        ),
                        value=dist_to_stop_pct, threshold=STOP_ALERT_PCT,
                    ))
                elif dist_to_stop_pct < STOP_BUFFER_PCT:
                    alerts.append(Alert(
                        level="warning", ticker=ticker, rule="接近止损",
                        detail=(
                            f"现价 {price:.2f}，止损 {stop_loss:.2f}，"
                            f"距止损 {dist_to_stop_pct:.1f}%"
                        ),
                        value=dist_to_stop_pct, threshold=STOP_BUFFER_PCT,
                    ))
                elif dist_to_stop_pct > 20.0:
                    alerts.append(Alert(
                        level="info", ticker=ticker, rule="止损过宽",
                        detail=(
                            f"{ticker} 止损过宽 ({dist_to_stop_pct:.1f}%)，"
                            f"考虑上移止损以锁定收益"
                        ),
                        value=dist_to_stop_pct, threshold=20.0,
                    ))

        if target and target > 0:
            target_hit = price <= target if is_short else price >= target
            if target_hit:
                alerts.append(Alert(
                    level="info", ticker=ticker, rule="目标价到达",
                    detail=f"现价 {price:.2f} {'≤' if is_short else '≥'} 目标 {target:.2f}，重新评估thesis: 催化剂链是否完整? 是否上调目标?",
                    value=price, threshold=target,
                ))

    currency = "¥" if is_cn else "$"
    if avg_cost > 0:
        summary_pnl = round(((avg_cost - price) / avg_cost * 100) if is_short else ((price - avg_cost) / avg_cost * 100), 2)
    else:
        summary_pnl = None
    abs_market_value = abs(round(market_value, 2))
    return {
        "ticker": ticker,
        "name": pos.get("name", ticker),
        "sector": pos.get("sector", "未分类"),
        "is_cn": is_cn,
        "shares": shares,
        "avg_cost": avg_cost,
        "current_price": price,
        "market_value": round(market_value, 2),
        "abs_market_value": abs_market_value,
        "weight_pct": round(weight_pct, 2),
        "pnl_pct": summary_pnl,
        "stop_loss": stop_loss,
        "target": target,
        "currency": currency,
    }


def _check_sectors(sector_weights: dict[str, float], alerts: list[Alert]) -> None:
    """Kept for compatibility — actual enforcement now in _check_sectors_by_market."""
    pass  # superseded by _check_sectors_by_market


def _check_sectors_by_market(
    summaries: list[dict], us_total: float, cn_total: float, alerts: list[Alert]
) -> None:
    """
    Enhancement #4: Market-specific sector concentration limits.
    A股 ≤ 35% (v7.0: 40%→35%), 美股 ≤ 35%.
    """
    cn_sector_weights: dict[str, float] = {}
    us_sector_weights: dict[str, float] = {}

    for s in summaries:
        sec = s.get("sector") or "未分类"
        if s.get("is_cn"):
            total = cn_total if cn_total > 0 else 1
            cn_sector_weights[sec] = cn_sector_weights.get(sec, 0) + (
                s["market_value"] / total * 100
            )
        else:
            total = us_total if us_total > 0 else 1
            us_sector_weights[sec] = us_sector_weights.get(sec, 0) + (
                s["market_value"] / total * 100
            )

    limit_cn = MAX_SECTOR_PCT_CN * 100  # 35.0 (v7.0)
    limit_us = MAX_SECTOR_PCT_US * 100  # 35.0

    for sec, w in cn_sector_weights.items():
        if w > limit_cn:
            alerts.append(Alert(
                level="warning", ticker="A股PORTFOLIO", rule="A股板块超限",
                detail=f"A股板块「{sec}」占比 {w:.1f}%，上限 {limit_cn:.0f}%",
                value=w, threshold=limit_cn,
            ))

    for sec, w in us_sector_weights.items():
        if w > limit_us:
            alerts.append(Alert(
                level="warning", ticker="US PORTFOLIO", rule="美股板块超限",
                detail=f"美股板块「{sec}」占比 {w:.1f}%，上限 {limit_us:.0f}%",
                value=w, threshold=limit_us,
            ))


# ──────────────────────────────────────────────────────────────────────────────
# Circuit Breaker — peak NAV drawdown
# ──────────────────────────────────────────────────────────────────────────────
def _get_peak_nav(portfolio: dict, market: str) -> Optional[float]:
    """
    从 daily_snapshots 提取历史最高 NAV。
    market: "us" | "cn"
    """
    snapshots = portfolio.get("daily_snapshots", [])
    nav_key = "us_nav" if market == "us" else "cn_nav"
    peaks = [s[nav_key] for s in snapshots if isinstance(s.get(nav_key), (int, float)) and s[nav_key] > 0]
    return max(peaks) if peaks else None


def _check_circuit_breaker(
    portfolio: dict,
    us_current_nav: float,
    cn_current_nav: float,
    alerts: list[Alert],
) -> None:
    """
    Portfolio-level Circuit Breaker: compares current NAV vs peak NAV from snapshots.
    Fires WARNING / CRITICAL / EMERGENCY based on CB_* thresholds.
    """
    for market, current_nav, label in (
        ("us", us_current_nav, "US账户"),
        ("cn", cn_current_nav, "A股账户"),
    ):
        if current_nav <= 0:
            continue
        peak_nav = _get_peak_nav(portfolio, market)
        if peak_nav is None or peak_nav <= 0:
            # Fallback: use initial_capital as peak
            acct_key = "us" if market == "us" else "a_share"
            peak_nav = float(portfolio["accounts"][acct_key].get("initial_capital", 0))
        if peak_nav <= 0:
            continue

        dd_pct = (current_nav / peak_nav - 1) * 100

        if dd_pct <= CB_EMERGENCY_DD:
            alerts.append(Alert(
                level="critical",
                ticker=f"CB-{label}",
                rule="Circuit Breaker — EMERGENCY",
                detail=(
                    f"[EMERGENCY] {label} 从峰值回撤 {dd_pct:.1f}% "
                    f"(峰值 {peak_nav:,.0f} → 现值 {current_nav:,.0f})。"
                    " 逐一评估各持仓thesis，考虑减仓至核心持仓。"
                ),
                value=dd_pct,
                threshold=CB_EMERGENCY_DD,
            ))
        elif dd_pct <= CB_CRITICAL_DD:
            alerts.append(Alert(
                level="critical",
                ticker=f"CB-{label}",
                rule="Circuit Breaker — CRITICAL",
                detail=(
                    f"[CRITICAL] {label} 从峰值回撤 {dd_pct:.1f}% "
                    f"(峰值 {peak_nav:,.0f} → 现值 {current_nav:,.0f})。"
                    " 检查所有止损位，考虑减持高Beta仓位。"
                ),
                value=dd_pct,
                threshold=CB_CRITICAL_DD,
            ))
        elif dd_pct <= CB_WARN_DD:
            alerts.append(Alert(
                level="warning",
                ticker=f"CB-{label}",
                rule="Circuit Breaker — WARNING",
                detail=(
                    f"[WARNING] {label} 从峰值回撤 {dd_pct:.1f}% "
                    f"(峰值 {peak_nav:,.0f} → 现值 {current_nav:,.0f})。"
                    " 暂停新建仓，等待回撤修复。"
                ),
                value=dd_pct,
                threshold=CB_WARN_DD,
            ))


# ──────────────────────────────────────────────────────────────────────────────
# VIX-based Exposure Scaling
# ──────────────────────────────────────────────────────────────────────────────
def _fetch_vix() -> Optional[float]:
    """Fetch current VIX level via yfinance. Returns None on failure."""
    try:
        vix = yf.Ticker("^VIX")
        info = vix.fast_info
        price = info.last_price
        if price and price > 0:
            return float(price)
        hist = vix.history(period="1d", auto_adjust=True)
        if not hist.empty:
            p = float(hist["Close"].iloc[-1])
            if p > 0:
                return p
    except Exception:
        pass
    return None


def _check_vix_exposure(vix: Optional[float], alerts: list[Alert]) -> None:
    """
    VIX-based exposure scaling alerts.
    VIX unavailable → annotate but do not fire alert.
    """
    if vix is None:
        alerts.append(Alert(
            level="info",
            ticker="VIX",
            rule="VIX数据不可用",
            detail="无法获取 VIX 实时报价（网络/市场关闭）。建议手动检查市场波动率。",
        ))
        return

    if vix > VIX_EMERGENCY:
        alerts.append(Alert(
            level="critical",
            ticker=f"VIX={vix:.1f}",
            rule="VIX — EMERGENCY (>35)",
            detail=(
                f"VIX {vix:.1f} > {VIX_EMERGENCY:.0f}。"
                " 极端恐慌模式：建议现金≥70%，只保留defensive仓位。"
                " 禁止新建非防御性头寸。"
            ),
            value=vix,
            threshold=VIX_EMERGENCY,
        ))
    elif vix > VIX_WARN:
        alerts.append(Alert(
            level="warning",
            ticker=f"VIX={vix:.1f}",
            rule="VIX — ELEVATED (25-35)",
            detail=(
                f"VIX {vix:.1f} > {VIX_WARN:.0f}。"
                " 波动升高，检查止损距离是否充足。"
            ),
            value=vix,
            threshold=VIX_WARN,
        ))
    # VIX < 25: no alert, normal operation


# ──────────────────────────────────────────────────────────────────────────────
# Concentration Alert — same-sector position count
# ──────────────────────────────────────────────────────────────────────────────
def _check_concentration(summaries: list[dict], alerts: list[Alert]) -> None:
    """
    Fires concentration risk alert when the same sector has > MAX_SECTOR_POSITIONS positions.
    High correlation proxy: if many stocks share the same sector, idiosyncratic
    risk may be lower but drawdown correlation in a sector selloff is high.
    """
    sector_tickers: dict[str, list[str]] = {}
    for s in summaries:
        sec = s.get("sector") or "未分类"
        sector_tickers.setdefault(sec, []).append(s["ticker"])

    for sector, tickers in sector_tickers.items():
        if len(tickers) > MAX_SECTOR_POSITIONS:
            alerts.append(Alert(
                level="info",
                ticker="PORTFOLIO",
                rule="相关性提示 — 同板块持仓",
                detail=(
                    f"板块「{sector}」持有 {len(tickers)} 只"
                    f" (>{MAX_SECTOR_POSITIONS})：{', '.join(tickers)}。"
                    " 相关性提示: 确认各持仓thesis独立。"
                ),
                value=float(len(tickers)),
                threshold=float(MAX_SECTOR_POSITIONS),
            ))


# ──────────────────────────────────────────────────────────────────────────────
# Enhancement #1: 4-tier bear case integration
# ──────────────────────────────────────────────────────────────────────────────
def _bear_tier(bear_pct: Optional[float]) -> str:
    """
    Classify a US bear case downside % into tier name.
    bear_pct is expected as a negative float, e.g. -18.0 means -18%.
    """
    if bear_pct is None:
        return "Unknown"
    if bear_pct > BEAR_TIER_SAFE_LIMIT:           # > -15  → Safe
        return "Safe"
    if bear_pct > BEAR_TIER_ELEVATED_LIMIT:       # -25 < x ≤ -15 → Elevated
        return "Elevated"
    if bear_pct > BEAR_TIER_HIGH_LIMIT:           # -35 < x ≤ -25 → High
        return "High"
    return "Extreme"                               # ≤ -35


def _check_bear_case_tiers(summaries: list[dict], positions_raw: list[dict], alerts: list[Alert]) -> None:
    """
    Enhancement #1: For US positions, check bear case tier vs position size.
    SABCT v3.0: "bear case管仓位不管入选" — Elevated tier uses grade-based limit.
      Safe     (>-15%)     → no cap from bear case
      Elevated (-15%~-25%) → cap at position's SABCT grade limit
      High     (-25%~-35%) → hard cap B- (10%), confirm stop
      Extreme  (≤-35%)     → exclude (CRITICAL)
    """
    raw_by_ticker: dict[str, dict] = {p["ticker"]: p for p in positions_raw}

    for s in summaries:
        if s.get("is_cn"):
            continue
        ticker = s["ticker"]
        raw = raw_by_ticker.get(ticker, {})
        grade = raw.get("conviction_level", "B")
        if grade == "INDEX":
            continue
        bear_pct = raw.get("bear_case_downside")
        if bear_pct is None:
            bear_pct = raw.get("bear_case_downside_pct")
        if bear_pct is not None and abs(bear_pct) < 1:
            bear_pct = bear_pct * 100

        tier = _bear_tier(bear_pct)
        weight = s["weight_pct"]

        if tier == "Extreme":
            alerts.append(Alert(
                level="critical", ticker=ticker, rule="Bear Case — Extreme Tier",
                detail=(
                    f"US持仓 {ticker} bear case {bear_pct:.0f}% ≤ -35%（Extreme tier）。"
                    " 应排除出投资universe，硬规则。建议立即清仓。"
                ),
                value=bear_pct, threshold=BEAR_TIER_HIGH_LIMIT,
            ))
        elif tier == "High" and weight > BEAR_TIER_HIGH_MAX_PCT:
            alerts.append(Alert(
                level="warning", ticker=ticker, rule="Bear Case — High Tier 仓位超限",
                detail=(
                    f"US持仓 {ticker} bear case {bear_pct:.0f}% (High tier, {grade}级)，"
                    f" 当前仓位 {weight:.1f}% 超过 High tier 硬上限 {BEAR_TIER_HIGH_MAX_PCT:.0f}%。"
                    " 需确认明确止损并减仓。"
                ),
                value=weight, threshold=BEAR_TIER_HIGH_MAX_PCT,
            ))
        elif tier == "Elevated":
            grade_limit = SABCT_GRADE_LIMITS.get(grade, 12.0)
            if weight > grade_limit:
                alerts.append(Alert(
                    level="warning", ticker=ticker, rule="Bear Case — Elevated + 超SABCT上限",
                    detail=(
                        f"US持仓 {ticker} bear case {bear_pct:.0f}% (Elevated tier)，"
                        f" {grade}级上限 {grade_limit:.0f}%，当前 {weight:.1f}%。"
                    ),
                    value=weight, threshold=grade_limit,
                ))


# ──────────────────────────────────────────────────────────────────────────────
# Enhancement #2: S-grade holding period check
# ──────────────────────────────────────────────────────────────────────────────
def _trading_days_held(entry_date_str: Optional[str]) -> Optional[int]:
    """
    Approximate trading days held since entry_date (ignore holidays for simplicity;
    counts Mon-Fri only).
    """
    if not entry_date_str:
        return None
    try:
        # Handle ISO format with time component
        entry_dt = datetime.fromisoformat(entry_date_str.replace("Z", "+00:00")).date()
    except Exception:
        try:
            entry_dt = date.fromisoformat(entry_date_str[:10])
        except Exception:
            return None
    today = date.today()
    if today < entry_dt:
        return 0
    delta = today - entry_dt
    # Count weekdays only (Mon-Fri)
    trading_days = sum(
        1 for i in range(delta.days + 1)
        if (entry_dt + __import__("datetime").timedelta(days=i)).weekday() < 5
    )
    return trading_days


def _check_s_grade_holding(positions_raw: list[dict], is_cn: bool, alerts: list[Alert]) -> None:
    """
    Enhancement #2: S-grade positions held > S_GRADE_MAX_TRADING_DAYS → CRITICAL.
    'S-grade' is identified by confidence_grade == 'S' or grade == 'S' in position data.
    """
    for pos in positions_raw:
        grade = pos.get("confidence_grade") or pos.get("grade") or pos.get("confidence", "")
        if str(grade).upper() != "S":
            continue
        entry_date = pos.get("entry_date") or pos.get("entry_date_str")
        days = _trading_days_held(entry_date)
        if days is not None and days > S_GRADE_MAX_TRADING_DAYS:
            ticker = pos["ticker"]
            alerts.append(Alert(
                level="critical", ticker=ticker, rule="S-grade 持仓时间超限",
                detail=(
                    f"S-grade持仓 {ticker} 已持有 {days} 个交易日，"
                    f" 超过最大持仓期限 {S_GRADE_MAX_TRADING_DAYS} 个交易日（约2周）。"
                    " 请重新评估是否继续持有。"
                ),
                value=float(days), threshold=float(S_GRADE_MAX_TRADING_DAYS),
            ))


# ──────────────────────────────────────────────────────────────────────────────
# Enhancement #3: Catalyst proximity alerts
# ──────────────────────────────────────────────────────────────────────────────
def _parse_catalyst_date(date_str: Optional[str]) -> Optional[date]:
    """Parse catalyst date string to date. Returns None if not parseable."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str[:10], fmt).date()
        except Exception:
            pass
    return None


def _check_catalyst_proximity(watchlist: dict, portfolio: dict, alerts: list[Alert]) -> None:
    """
    Enhancement #3: For each held position with a catalyst in the watchlist,
    emit INFO (≤7 days) or HIGH (≤2 days) alerts.
    Uses portfolio_state catalyst_calendar_30d and per-position next_catalyst_date.
    """
    today = date.today()
    held_tickers: set[str] = set()

    # Collect held tickers from portfolio
    for acct_key in ("us", "a_share"):
        for pos in portfolio.get("accounts", {}).get(acct_key, {}).get("positions", []):
            held_tickers.add(pos["ticker"].upper())

    # Also map SPUT → SRUUF
    if "SPUT" in held_tickers:
        held_tickers.add("SRUUF")

    # Check catalyst_calendar_30d in portfolio_state
    for entry in portfolio.get("catalyst_calendar_30d", []):
        ticker = (entry.get("ticker") or "").upper()
        event = entry.get("event", "")
        cat_date = _parse_catalyst_date(entry.get("date"))
        if cat_date is None:
            continue
        if cat_date < today:
            continue  # past event
        # Match held tickers (split multi-ticker entries like "LEU/SPUT")
        tickers_in_entry = {t.strip().upper() for t in ticker.split("/")}
        if not tickers_in_entry.intersection(held_tickers):
            continue
        delta = (cat_date - today).days
        if delta <= CATALYST_HIGH_DAYS:
            alerts.append(Alert(
                level="high", ticker=ticker, rule="催化剂临近 — HIGH",
                detail=f"催化剂「{event}」距今仅 {delta} 天 ({cat_date})。高度关注，准备预案。",
                value=float(delta), threshold=float(CATALYST_HIGH_DAYS),
            ))
        elif delta <= CATALYST_INFO_DAYS:
            alerts.append(Alert(
                level="info", ticker=ticker, rule="催化剂临近 — INFO",
                detail=f"催化剂「{event}」距今 {delta} 天 ({cat_date})。提前准备预案。",
                value=float(delta), threshold=float(CATALYST_INFO_DAYS),
            ))

    # Also check per-position next_catalyst_date from both accounts
    seen_events: set[str] = set()  # avoid duplicate alerts
    for acct_key in ("us", "a_share"):
        for pos in portfolio.get("accounts", {}).get(acct_key, {}).get("positions", []):
            ticker = pos["ticker"].upper()
            next_cat = pos.get("next_catalyst")
            if isinstance(next_cat, dict):
                cat_date_str = next_cat.get("date") or pos.get("next_catalyst_date")
                event = next_cat.get("event", cat_date_str or "")
            else:
                cat_date_str = pos.get("next_catalyst_date")
                event = next_cat or cat_date_str or ""
            cat_date = _parse_catalyst_date(cat_date_str)
            if cat_date is None or cat_date < today:
                continue
            dedup_key = f"{ticker}:{cat_date}"
            if dedup_key in seen_events:
                continue
            seen_events.add(dedup_key)
            delta = (cat_date - today).days
            if delta <= CATALYST_HIGH_DAYS:
                alerts.append(Alert(
                    level="high", ticker=ticker, rule="催化剂临近 — HIGH",
                    detail=f"持仓 {ticker} 催化剂「{event}」距今仅 {delta} 天 ({cat_date})。高度关注，准备预案。",
                    value=float(delta), threshold=float(CATALYST_HIGH_DAYS),
                ))
            elif delta <= CATALYST_INFO_DAYS:
                alerts.append(Alert(
                    level="info", ticker=ticker, rule="催化剂临近 — INFO",
                    detail=f"持仓 {ticker} 催化剂「{event}」距今 {delta} 天 ({cat_date})。提前准备预案。",
                    value=float(delta), threshold=float(CATALYST_INFO_DAYS),
                ))


# ──────────────────────────────────────────────────────────────────────────────
# Enhancement #5: Portfolio health score
# ──────────────────────────────────────────────────────────────────────────────
def _compute_health_score(alerts: list[Alert]) -> int:
    """
    Simple 0-100 health score:
      Start at 100
      -20 per CRITICAL
      -10 per HIGH
      -5  per MEDIUM
    Floor at 0.
    """
    score = 100
    for a in alerts:
        if a.level == "critical":
            score -= 20
        elif a.level == "high":
            score -= 10
        elif a.level == "medium":
            score -= 5
    return max(0, score)


# ──────────────────────────────────────────────────────────────────────────────
# Enhancement #6: Broad sector correlation risk
# ──────────────────────────────────────────────────────────────────────────────
def _check_broad_sector_correlation(summaries: list[dict], alerts: list[Alert]) -> None:
    """
    Enhancement #6: If > MAX_BROAD_SECTOR_POSITIONS positions share the same
    broad sector bucket (tech/semiconductor, energy, commodity), flag correlation risk.
    """
    bucket_tickers: dict[str, list[str]] = {b: [] for b in BROAD_SECTOR_BUCKETS}

    for s in summaries:
        sector = s.get("sector") or ""
        ticker = s["ticker"]
        for bucket_name, sector_list in BROAD_SECTOR_BUCKETS.items():
            if any(kw.lower() in sector.lower() for kw in sector_list):
                bucket_tickers[bucket_name].append(ticker)
                break  # assign to first matching bucket only

    for bucket_name, tickers in bucket_tickers.items():
        if len(tickers) > MAX_BROAD_SECTOR_POSITIONS:
            alerts.append(Alert(
                level="warning", ticker="PORTFOLIO", rule="板块相关性风险",
                detail=(
                    f"广义板块「{bucket_name}」持有 {len(tickers)} 只"
                    f" (>{MAX_BROAD_SECTOR_POSITIONS})：{', '.join(tickers)}。"
                    " 板块系统性事件将同步冲击所有持仓。"
                ),
                value=float(len(tickers)), threshold=float(MAX_BROAD_SECTOR_POSITIONS),
            ))


# ──────────────────────────────────────────────────────────────────────────────
# 主执行逻辑
# ──────────────────────────────────────────────────────────────────────────────
def run_risk_check(fetch_live: bool = True) -> RiskReport:
    portfolio = load_portfolio()
    watchlist = load_watchlist()
    us_account = portfolio["accounts"]["us"]
    cn_account = portfolio["accounts"]["a_share"]
    positions_us: list[dict] = [
        p for p in us_account.get("positions", [])
        if p.get("instrument_type") != "call_option"
    ]
    positions_cn: list[dict] = cn_account.get("positions", [])

    # Fetch live prices
    live: dict[str, Optional[float]] = {}
    if fetch_live and (positions_us or positions_cn):
        with console.status("[dim]获取实时价格...[/dim]"):
            live = fetch_current_prices(positions_us, positions_cn)

    report = RiskReport(generated_at=datetime.now().isoformat())
    alerts = report.alerts

    # Totals
    us_total = _calc_total_assets(us_account, positions_us, live)
    cn_total = _calc_total_assets(cn_account, positions_cn, live)
    us_cash = float(us_account.get("cash", 0))
    cn_cash = float(cn_account.get("cash", 0))
    us_initial = float(us_account.get("initial_capital", us_total or 1))
    cn_initial = float(cn_account.get("initial_capital", cn_total or 1))

    report.us_total_assets = us_total
    report.cn_total_assets = cn_total
    report.us_cash = us_cash
    report.cn_cash = cn_cash

    # Cash rules
    report.us_cash_pct = _check_cash(us_cash, us_total, "US账户", alerts, market="us")
    report.cn_cash_pct = _check_cash(cn_cash, cn_total, "A股账户", alerts, market="cn")

    # Drawdown rules
    report.us_drawdown_pct = _check_drawdown(us_initial, us_total, "US账户", alerts)
    report.cn_drawdown_pct = _check_drawdown(cn_initial, cn_total, "A股账户", alerts)

    # Per-position checks
    sector_weights: dict[str, float] = {}
    summaries: list[dict] = []

    for pos in positions_us:
        s = _check_position(pos, us_total, live, is_cn=False, alerts=alerts)
        summaries.append(s)
        sec = s["sector"]
        sector_weights[sec] = sector_weights.get(sec, 0) + s["weight_pct"]

    for pos in positions_cn:
        s = _check_position(pos, cn_total, live, is_cn=True, alerts=alerts)
        summaries.append(s)
        sec = s["sector"]
        sector_weights[sec] = sector_weights.get(sec, 0) + s["weight_pct"]

    report.position_summaries = summaries
    report.sector_weights = sector_weights

    # Sector limits — market-aware (Enhancement #4)
    _check_sectors_by_market(summaries, us_total, cn_total, alerts)

    # Position count — per-market (v9.1: A股≤8只, 无弹性概念)
    cn_pos = len(positions_cn)
    us_pos = len(positions_us)
    if cn_pos > ASTOCK_MAX_POSITIONS:
        alerts.append(Alert(
            level="high", ticker="PORTFOLIO", rule="A股持仓超限",
            detail=f"A股持仓 {cn_pos} 只，上限 {ASTOCK_MAX_POSITIONS} 只 (v9.1)",
            value=float(cn_pos), threshold=float(ASTOCK_MAX_POSITIONS),
        ))
    if us_pos > US_MAX_POSITIONS:
        alerts.append(Alert(
            level="warning", ticker="PORTFOLIO", rule="US持仓超限",
            detail=f"US持仓 {us_pos} 只，上限 {US_MAX_POSITIONS} 只",
            value=float(us_pos), threshold=float(US_MAX_POSITIONS),
        ))

    # ── Circuit Breaker / VIX / 集中度 ──────────────────────────────────────
    _check_circuit_breaker(portfolio, us_total, cn_total, alerts)

    # Store peak NAVs for display
    report.us_peak_nav = _get_peak_nav(portfolio, "us")
    report.cn_peak_nav = _get_peak_nav(portfolio, "cn")
    if report.us_peak_nav and report.us_peak_nav > 0:
        report.us_cb_dd_pct = round((us_total / report.us_peak_nav - 1) * 100, 2)
    if report.cn_peak_nav and report.cn_peak_nav > 0:
        report.cn_cb_dd_pct = round((cn_total / report.cn_peak_nav - 1) * 100, 2)

    with console.status("[dim]获取 VIX...[/dim]"):
        vix_value = _fetch_vix()
    report.vix_value = vix_value
    _check_vix_exposure(vix_value, alerts)

    _check_concentration(report.position_summaries, alerts)

    # ── Enhancement #1: Bear case 4-tier integration ──────────────────────────
    _check_bear_case_tiers(summaries, positions_us, alerts)

    # ── Enhancement #2: S-grade holding period ───────────────────────────────
    _check_s_grade_holding(positions_us, is_cn=False, alerts=alerts)
    _check_s_grade_holding(positions_cn, is_cn=True, alerts=alerts)

    # ── Enhancement #3: Catalyst proximity ──────────────────────────────────
    _check_catalyst_proximity(watchlist, portfolio, alerts)

    # ── Enhancement #6: Broad sector correlation ─────────────────────────────
    _check_broad_sector_correlation(report.position_summaries, alerts)

    # ── Enhancement #5: Portfolio health score (computed last) ───────────────
    report.health_score = _compute_health_score(alerts)
    # ─────────────────────────────────────────────────────────────────────────

    return report


# ──────────────────────────────────────────────────────────────────────────────
# Rich 终端输出
# ──────────────────────────────────────────────────────────────────────────────
def _level_icon(level: AlertLevel) -> str:
    return {
        "critical": "[bold red]CRITICAL[/bold red]",
        "high":     "[red]HIGH    [/red]",
        "medium":   "[magenta]MEDIUM  [/magenta]",
        "warning":  "[yellow]WARNING [/yellow]",
        "info":     "[cyan]INFO    [/cyan]",
    }.get(level, level)


def print_report(report: RiskReport) -> None:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_color = "red" if report.has_critical else ("yellow" if report.warnings else "green")
    status_text = "CRITICAL" if report.has_critical else ("WARNING" if report.warnings else "CLEAR")

    console.print()
    console.print(Panel(
        f"[bold]Claude 模拟盘 — 风控报告[/bold]\n"
        f"生成时间: {now_str}  |  状态: [{status_color}]{status_text}[/{status_color}]  |  "
        f"告警: [red]{len(report.criticals)}条CRITICAL[/red] / "
        f"[yellow]{len(report.warnings)}条WARNING[/yellow]",
        border_style=status_color,
        box=box.DOUBLE_EDGE,
    ))

    # 账户概览
    overview = Table(title="账户概览", box=box.SIMPLE_HEAD)
    overview.add_column("账户", style="bold")
    overview.add_column("总资产", justify="right")
    overview.add_column("现金", justify="right")
    overview.add_column("现金%", justify="right")
    overview.add_column("累计回撤", justify="right")

    def _cash_style(pct: float) -> str:
        return "green"  # v9.1: 无现金底线，不标红

    def _dd_style(pct: float) -> str:
        return "red bold" if pct < MAX_PORTFOLIO_DRAWDOWN else ("yellow" if pct < -5 else "green")

    overview.add_row(
        "US", f"${report.us_total_assets:,.0f}", f"${report.us_cash:,.0f}",
        Text(f"{report.us_cash_pct:.1f}%", style=_cash_style(report.us_cash_pct)),
        Text(f"{report.us_drawdown_pct:+.2f}%", style=_dd_style(report.us_drawdown_pct)),
    )
    overview.add_row(
        "A股", f"¥{report.cn_total_assets:,.0f}", f"¥{report.cn_cash:,.0f}",
        Text(f"{report.cn_cash_pct:.1f}%", style=_cash_style(report.cn_cash_pct)),
        Text(f"{report.cn_drawdown_pct:+.2f}%", style=_dd_style(report.cn_drawdown_pct)),
    )
    console.print(overview)

    # ── Circuit Breaker 面板 ───────────────────────────────────────────────
    def _cb_dd_style(dd: Optional[float]) -> str:
        if dd is None:
            return "dim"
        if dd <= CB_EMERGENCY_DD:
            return "bold red"
        if dd <= CB_CRITICAL_DD:
            return "red"
        if dd <= CB_WARN_DD:
            return "yellow"
        return "green"

    def _cb_status(dd: Optional[float]) -> str:
        if dd is None:
            return "N/A"
        if dd <= CB_EMERGENCY_DD:
            return "EMERGENCY"
        if dd <= CB_CRITICAL_DD:
            return "CRITICAL"
        if dd <= CB_WARN_DD:
            return "WARNING"
        return "CLEAR"

    vix_str = f"{report.vix_value:.1f}" if report.vix_value is not None else "N/A"
    vix_style = "dim" if report.vix_value is None else (
        "bold red" if report.vix_value > VIX_EMERGENCY else
        "yellow" if report.vix_value > VIX_WARN else "green"
    )

    cb_table = Table(title="Circuit Breaker & VIX", box=box.SIMPLE_HEAD)
    cb_table.add_column("账户/指标", style="bold")
    cb_table.add_column("峰值NAV", justify="right")
    cb_table.add_column("当前NAV", justify="right")
    cb_table.add_column("峰值回撤", justify="right")
    cb_table.add_column("CB状态", justify="center")

    us_dd = report.us_cb_dd_pct
    cn_dd = report.cn_cb_dd_pct
    us_peak_str = f"${report.us_peak_nav:,.0f}" if report.us_peak_nav else "—"
    cn_peak_str = f"¥{report.cn_peak_nav:,.0f}" if report.cn_peak_nav else "—"

    cb_table.add_row(
        "US",
        us_peak_str,
        f"${report.us_total_assets:,.0f}",
        Text(f"{us_dd:+.2f}%" if us_dd is not None else "—", style=_cb_dd_style(us_dd)),
        Text(_cb_status(us_dd), style=_cb_dd_style(us_dd)),
    )
    cb_table.add_row(
        "A股",
        cn_peak_str,
        f"¥{report.cn_total_assets:,.0f}",
        Text(f"{cn_dd:+.2f}%" if cn_dd is not None else "—", style=_cb_dd_style(cn_dd)),
        Text(_cb_status(cn_dd), style=_cb_dd_style(cn_dd)),
    )
    cb_table.add_row(
        "VIX",
        "—",
        Text(vix_str, style=vix_style),
        "—",
        Text(
            "EMERGENCY" if report.vix_value and report.vix_value > VIX_EMERGENCY else
            "ELEVATED" if report.vix_value and report.vix_value > VIX_WARN else
            "NORMAL" if report.vix_value else "N/A",
            style=vix_style,
        ),
    )
    console.print(cb_table)
    # ─────────────────────────────────────────────────────────────────────────

    # 持仓权重表
    if report.position_summaries:
        pos_table = Table(title="持仓明细", box=box.SIMPLE_HEAD)
        pos_table.add_column("代码", style="bold")
        pos_table.add_column("名称")
        pos_table.add_column("市场")
        pos_table.add_column("板块")
        pos_table.add_column("股数", justify="right")
        pos_table.add_column("均价", justify="right")
        pos_table.add_column("现价", justify="right")
        pos_table.add_column("P&L%", justify="right")
        pos_table.add_column("市值", justify="right")
        pos_table.add_column("仓位%", justify="right")
        pos_table.add_column("止损", justify="right")

        for s in sorted(report.position_summaries, key=lambda x: -x["weight_pct"]):
            avg = s.get("avg_cost") or 0
            cur = s.get("current_price") or 0
            pnl_pct = s.get("pnl_pct")
            stop = s.get("stop_loss")
            is_cn = s.get("is_cn", False)
            mkt = "A股" if is_cn else "US"
            sym = "¥" if is_cn else "$"

            # 仓位上限按评级查，不用全局硬编码
            weight_style = "red bold" if s["weight_pct"] > 50.0 else "default"
            pnl_style = "green" if (pnl_pct or 0) >= 0 else "red"

            pos_table.add_row(
                s["ticker"],
                (s.get("name") or "")[:12],
                mkt,
                (s.get("sector") or "")[:10],
                f"{s.get('shares', 0):,}",
                f"{sym}{avg:.2f}" if avg > 0 else "—",
                f"{sym}{cur:.2f}" if cur > 0 else "—",
                Text(f"{pnl_pct:+.1f}%" if pnl_pct is not None else "—", style=pnl_style),
                f"{sym}{s.get('market_value', 0):,.0f}",
                Text(f"{s['weight_pct']:.1f}%", style=weight_style),
                f"{sym}{stop:.2f}" if stop else "—",
            )
        console.print(pos_table)

    # 板块分布
    if report.sector_weights:
        sec_table = Table(title="板块分布", box=box.SIMPLE_HEAD)
        sec_table.add_column("板块")
        sec_table.add_column("合计%", justify="right")
        sec_table.add_column("状态", justify="center")
        for sec, w in sorted(report.sector_weights.items(), key=lambda x: -x[1]):
            sec_table.add_row(sec, f"{w:.1f}%", "[green]正常[/green]")
        console.print(sec_table)

    # 告警列表
    _LEVEL_ORDER = {"critical": 0, "high": 1, "medium": 2, "warning": 3, "info": 4}
    console.print()
    if not report.alerts:
        console.print(Panel("[bold green]所有风控检查通过，无告警[/bold green]", border_style="green"))
    else:
        alert_table = Table(title="风控告警", box=box.SIMPLE_HEAD, show_lines=True)
        alert_table.add_column("级别", justify="center", min_width=10)
        alert_table.add_column("标的")
        alert_table.add_column("规则")
        alert_table.add_column("详情")
        for a in sorted(report.alerts, key=lambda x: _LEVEL_ORDER.get(x.level, 5)):
            alert_table.add_row(_level_icon(a.level), a.ticker, a.rule, a.detail)
        console.print(alert_table)

    # ── Enhancement #5: Portfolio health score ────────────────────────────────
    health = report.health_score
    health_style = "bold green" if health >= 80 else ("yellow" if health >= 60 else "bold red")
    console.print(Panel(
        f"[{health_style}]Portfolio Health: {health}/100[/{health_style}]  "
        f"  ({len(report.criticals)} CRITICAL × −20  |  "
        f"{len(report.highs)} HIGH × −10  |  "
        f"{len(report.mediums)} MEDIUM × −5)",
        title="[bold]健康评分[/bold]",
        border_style=health_style.replace("bold ", ""),
    ))
    # ─────────────────────────────────────────────────────────────────────────

    console.print()


# ──────────────────────────────────────────────────────────────────────────────
# Markdown 报告
# ──────────────────────────────────────────────────────────────────────────────
def save_markdown_report(report: RiskReport) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = REPORTS_DIR / f"risk-{date_str}.md"

    _LEVEL_ORDER_MD = {"critical": 0, "high": 1, "medium": 2, "warning": 3, "info": 4}
    status = "CRITICAL" if report.has_critical else ("WARNING" if report.warnings else "CLEAR")
    health = report.health_score
    lines = [
        f"# 风控报告 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**状态**: {status}  **告警**: {len(report.criticals)} CRITICAL / {len(report.highs)} HIGH / {len(report.mediums)} MEDIUM / {len(report.warnings)} WARNING",
        f"**Portfolio Health**: {health}/100",
        "",
        "## 账户概览",
        "",
        "| 账户 | 总资产 | 现金 | 现金% | 回撤 |",
        "|------|--------|------|-------|------|",
        f"| US | ${report.us_total_assets:,.0f} | ${report.us_cash:,.0f} | {report.us_cash_pct:.1f}% | {report.us_drawdown_pct:+.2f}% |",
        f"| A股 | ¥{report.cn_total_assets:,.0f} | ¥{report.cn_cash:,.0f} | {report.cn_cash_pct:.1f}% | {report.cn_drawdown_pct:+.2f}% |",
        "",
    ]

    # Circuit Breaker & VIX section
    vix_str = f"{report.vix_value:.1f}" if report.vix_value is not None else "N/A"
    us_dd_str = f"{report.us_cb_dd_pct:+.2f}%" if report.us_cb_dd_pct is not None else "—"
    cn_dd_str = f"{report.cn_cb_dd_pct:+.2f}%" if report.cn_cb_dd_pct is not None else "—"
    us_peak_str = f"${report.us_peak_nav:,.0f}" if report.us_peak_nav else "—"
    cn_peak_str = f"¥{report.cn_peak_nav:,.0f}" if report.cn_peak_nav else "—"
    lines += [
        "## Circuit Breaker & VIX",
        "",
        "| 账户/指标 | 峰值NAV | 当前NAV | 峰值回撤 | CB状态 |",
        "|---------|--------|--------|--------|------|",
        f"| US | {us_peak_str} | ${report.us_total_assets:,.0f} | {us_dd_str} | "
        f"{'EMERGENCY' if report.us_cb_dd_pct and report.us_cb_dd_pct <= CB_EMERGENCY_DD else 'CRITICAL' if report.us_cb_dd_pct and report.us_cb_dd_pct <= CB_CRITICAL_DD else 'WARNING' if report.us_cb_dd_pct and report.us_cb_dd_pct <= CB_WARN_DD else 'CLEAR'} |",
        f"| A股 | {cn_peak_str} | ¥{report.cn_total_assets:,.0f} | {cn_dd_str} | "
        f"{'EMERGENCY' if report.cn_cb_dd_pct and report.cn_cb_dd_pct <= CB_EMERGENCY_DD else 'CRITICAL' if report.cn_cb_dd_pct and report.cn_cb_dd_pct <= CB_CRITICAL_DD else 'WARNING' if report.cn_cb_dd_pct and report.cn_cb_dd_pct <= CB_WARN_DD else 'CLEAR'} |",
        f"| VIX | — | {vix_str} | — | "
        f"{'EMERGENCY' if report.vix_value and report.vix_value > VIX_EMERGENCY else 'ELEVATED' if report.vix_value and report.vix_value > VIX_WARN else 'NORMAL' if report.vix_value else 'N/A'} |",
        "",
    ]

    if report.position_summaries:
        lines += [
            "## 持仓明细",
            "",
            "| 代码 | 名称 | 市场 | 板块 | 股数 | 均价 | 现价 | P&L% | 仓位% | 止损 |",
            "|------|------|------|------|------|------|------|------|-------|------|",
        ]
        for s in sorted(report.position_summaries, key=lambda x: -x["weight_pct"]):
            avg = s.get("avg_cost") or 0
            cur = s.get("current_price") or 0
            pnl = s.get("pnl_pct")
            stop = s.get("stop_loss")
            is_cn = s.get("is_cn", False)
            mkt = "A股" if is_cn else "US"
            sym = "¥" if is_cn else "$"
            pnl_str = f"{pnl:+.1f}%" if pnl is not None else "—"
            stop_str = f"{sym}{stop:.2f}" if stop else "—"
            lines.append(
                f"| {s['ticker']} | {(s.get('name') or '')[:12]} | {mkt} | {s.get('sector', '')} "
                f"| {s.get('shares', 0):,} | {sym}{avg:.2f} | {sym}{cur:.2f} "
                f"| {pnl_str} | {s['weight_pct']:.1f}% | {stop_str} |"
            )
        lines.append("")

    if report.alerts:
        lines += [
            "## 风控告警",
            "",
            "| 级别 | 标的 | 规则 | 详情 |",
            "|------|------|------|------|",
        ]
        for a in sorted(report.alerts, key=lambda x: _LEVEL_ORDER_MD.get(x.level, 5)):
            lines.append(f"| {a.level.upper()} | {a.ticker} | {a.rule} | {a.detail} |")
        lines.append("")
    else:
        lines += ["## 风控告警", "", "所有检查通过，无告警。", ""]

    lines += [
        "## Portfolio Health",
        "",
        f"**Portfolio Health: {health}/100**  "
        f"({len(report.criticals)} CRITICAL × −20 | "
        f"{len(report.highs)} HIGH × −10 | "
        f"{len(report.mediums)} MEDIUM × −5)",
        "",
    ]

    filename.write_text("\n".join(lines), encoding="utf-8")
    return filename


# ──────────────────────────────────────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────────────────────────────────────
def print_compact(report: RiskReport) -> None:
    """Plain-text compact output (~500 tokens vs ~2500 for rich tables)."""
    status = "CRITICAL" if report.has_critical else ("WARNING" if report.warnings else "CLEAR")
    print(f"[风控] {status} | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  US: ${report.us_total_assets:,.0f} | 现金{report.us_cash_pct:.0f}% | 回撤{report.us_drawdown_pct:+.1f}%")
    print(f"  A股: ¥{report.cn_total_assets:,.0f} | 现金{report.cn_cash_pct:.0f}% | 回撤{report.cn_drawdown_pct:+.1f}%")

    if report.criticals:
        print(f"  CRITICAL ({len(report.criticals)}):")
        for a in report.criticals:
            print(f"    {a.ticker}: {a.detail}")
    if report.warnings:
        print(f"  WARNING ({len(report.warnings)}):")
        for a in report.warnings:
            print(f"    {a.ticker}: {a.detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude模拟盘风控监控")
    parser.add_argument("--no-save", action="store_true", help="不保存markdown报告")
    parser.add_argument("--no-fetch", action="store_true", help="不获取实时价格（使用portfolio中的当前价格）")
    parser.add_argument("--compact", action="store_true", help="纯文本精简输出（节省context tokens）")
    args = parser.parse_args()

    try:
        report = run_risk_check(fetch_live=not args.no_fetch)
    except Exception as e:
        console.print(f"[bold red]风控检查失败: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    if args.compact:
        print_compact(report)
    else:
        print_report(report)

    if not args.no_save:
        try:
            saved = save_markdown_report(report)
            if not args.compact:
                console.print(f"[dim]报告已保存: {saved}[/dim]")
        except Exception as e:
            if not args.compact:
                console.print(f"[yellow]报告保存失败: {e}[/yellow]")

    if report.has_critical:
        if not args.compact:
            console.print(Panel(
                f"[bold red]{len(report.criticals)} 条 CRITICAL 告警 — 需立即处理！[/bold red]\n" +
                "\n".join(f"  • [{a.ticker}] {a.rule}: {a.detail}" for a in report.criticals),
                title="[bold red]CRITICAL ALERTS[/bold red]",
                border_style="red",
                box=box.DOUBLE_EDGE,
            ))
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
