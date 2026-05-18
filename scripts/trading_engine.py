# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "yfinance>=0.2.40",
#   "rich>=13.0",
# ]
# ///
"""
Claude模拟盘交易引擎 — 每日全自动执行脚本
用法: uv run --script trading_engine.py [--date YYYY-MM-DD] [--dry-run]

功能:
  1. 读取 portfolio_state.json
  2. 用 yfinance 获取所有持仓最新价格
  3. 检查止损/目标价触发
  4. 更新持仓市值和P&L
  5. 生成每日报告 daily-reviews/YYYY-MM-DD.md
  6. 原子性更新 portfolio_state.json
  7. stdout 打印摘要供远程agent读取
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf
from rich.console import Console
from rich.table import Table

# ─── Constants ────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / "portfolio_state.json"
DAILY_DIR = REPO_ROOT / "daily-reviews"

BENCHMARKS = {
    "cn": "000300.SS",   # 沪深300 (Yahoo Finance uses .SS for Shanghai)
    "us": "SPY",
}

# OTC / special tickers that need remapping for yfinance
YF_TICKER_MAP: dict[str, str] = {
    "SPUT": "SRUUF",    # Sprott Uranium Trust trades OTC as SRUUF
}

# A股: 6开头→.SS, 0/3开头→.SZ
def cn_ticker_to_yf(ticker: str) -> str:
    if ticker.startswith("6"):
        return ticker + ".SS"
    return ticker + ".SZ"


def us_ticker_to_yf(ticker: str) -> str:
    """Apply OTC remapping for US tickers."""
    return YF_TICKER_MAP.get(ticker.upper(), ticker.upper())


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class Alert:
    account: str
    ticker: str
    name: str
    alert_type: str          # "STOP_LOSS" | "TARGET_HIT" | "TRAILING_STOP" | "PRICE_ERROR"
    price: float | None
    threshold: float | None
    message: str
    severity: str = "INFO"   # "CRITICAL" | "WARNING" | "INFO"


@dataclass
class PriceData:
    ticker: str
    price: float | None
    prev_close: float | None
    change_pct: float | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.price is not None and self.error is None


# ─── Module 1: Price Fetching ─────────────────────────────────────────────────

def _fetch_yf_price(yf_ticker: str, retries: int = 3, delay: float = 1.5) -> PriceData:
    """Fetch a single ticker from yfinance with retry. Returns PriceData with error on failure."""
    import time
    last_error = ""
    for attempt in range(retries):
        try:
            t = yf.Ticker(yf_ticker)
            info = t.fast_info
            last_price = info.last_price
            prev_close = info.previous_close

            if last_price is None or last_price <= 0:
                # Fallback: try history
                hist = t.history(period="2d", auto_adjust=True)
                if not hist.empty:
                    last_price = float(hist["Close"].iloc[-1])
                    if len(hist) >= 2:
                        prev_close = float(hist["Close"].iloc[-2])
                    else:
                        prev_close = last_price

            if last_price is None or last_price <= 0:
                last_error = "no valid price returned"
                if attempt < retries - 1:
                    time.sleep(delay)
                continue

            price = round(float(last_price), 4)
            prev = round(float(prev_close), 4) if (prev_close and prev_close > 0) else price
            chg = round((price / prev - 1) * 100, 2) if prev > 0 else None
            return PriceData(yf_ticker, price, prev, chg)

        except Exception as e:
            last_error = str(e)
            if attempt < retries - 1:
                time.sleep(delay)

    return PriceData(yf_ticker, None, None, None, error=last_error)


def fetch_all_prices(state: dict) -> dict[str, PriceData]:
    """
    Fetch prices for all positions + benchmarks.
    Returns dict keyed by yfinance ticker symbol.
    """
    to_fetch: set[str] = set()

    # A股持仓
    for pos in state["accounts"]["a_share"]["positions"]:
        if pos.get("instrument_type") == "call_option":
            continue
        raw = pos["ticker"]
        to_fetch.add(cn_ticker_to_yf(raw))

    # 美股持仓 — apply OTC remapping
    for pos in state["accounts"]["us"]["positions"]:
        if pos.get("instrument_type") == "call_option":
            continue
        raw = pos["ticker"]
        to_fetch.add(us_ticker_to_yf(raw))

    # 基准
    for bm in BENCHMARKS.values():
        to_fetch.add(bm)

    prices: dict[str, PriceData] = {}
    for ticker in sorted(to_fetch):
        prices[ticker] = _fetch_yf_price(ticker)

    return prices


# ─── Module 2: Trigger Checks ─────────────────────────────────────────────────

def check_triggers(state: dict, prices: dict[str, PriceData]) -> list[Alert]:
    """Check stop-loss, target, and trailing-stop triggers for all positions."""
    alerts: list[Alert] = []

    def _check_account(account_key: str, is_cn: bool) -> None:
        for pos in state["accounts"][account_key]["positions"]:
            if pos.get("instrument_type") == "call_option":
                continue

            raw_ticker = pos["ticker"]
            # Apply OTC remapping for US tickers
            if is_cn:
                yf_ticker = cn_ticker_to_yf(raw_ticker)
            else:
                yf_ticker = us_ticker_to_yf(raw_ticker)
            name = pos.get("name", raw_ticker)
            pd_obj = prices.get(yf_ticker)

            if pd_obj is None or not pd_obj.ok:
                err = pd_obj.error if pd_obj else "not fetched"
                alerts.append(Alert(
                    account=account_key,
                    ticker=raw_ticker,
                    name=name,
                    alert_type="PRICE_ERROR",
                    price=None,
                    threshold=None,
                    message=f"价格获取失败: {err}",
                    severity="WARNING",
                ))
                continue

            current = pd_obj.price
            # Support both field naming conventions
            stop = pos.get("stop_loss") or pos.get("stop")
            target = pos.get("target_1") or pos.get("target")
            trailing_stop = pos.get("trailing_stop")
            direction = pos.get("direction", "long")

            if direction == "long":
                # 止损检查
                if stop is not None and current <= stop:
                    alerts.append(Alert(
                        account=account_key,
                        ticker=raw_ticker,
                        name=name,
                        alert_type="STOP_LOSS",
                        price=current,
                        threshold=stop,
                        message=f"【止损触发】当前 {current:.2f} ≤ 止损 {stop:.2f}，请立即执行止损",
                        severity="CRITICAL",
                    ))

                # 目标价检查
                if target is not None and current >= target:
                    alerts.append(Alert(
                        account=account_key,
                        ticker=raw_ticker,
                        name=name,
                        alert_type="TARGET_HIT",
                        price=current,
                        threshold=target,
                        message=f"【目标达成】当前 {current:.2f} ≥ 目标 {target:.2f}，考虑分批出场",
                        severity="WARNING",
                    ))

                # Trailing stop检查
                if trailing_stop is not None and current <= trailing_stop:
                    alerts.append(Alert(
                        account=account_key,
                        ticker=raw_ticker,
                        name=name,
                        alert_type="TRAILING_STOP",
                        price=current,
                        threshold=trailing_stop,
                        message=f"【追踪止损】当前 {current:.2f} ≤ trailing stop {trailing_stop:.2f}",
                        severity="CRITICAL",
                    ))

            elif direction == "short":
                # 空头止损（价格上涨触发）
                if stop is not None and current >= stop:
                    alerts.append(Alert(
                        account=account_key,
                        ticker=raw_ticker,
                        name=name,
                        alert_type="STOP_LOSS",
                        price=current,
                        threshold=stop,
                        message=f"【空头止损】当前 {current:.2f} ≥ 止损 {stop:.2f}，请立即平仓",
                        severity="CRITICAL",
                    ))

                # 空头目标（价格下跌触发）
                if target is not None and current <= target:
                    alerts.append(Alert(
                        account=account_key,
                        ticker=raw_ticker,
                        name=name,
                        alert_type="TARGET_HIT",
                        price=current,
                        threshold=target,
                        message=f"【空头目标】当前 {current:.2f} ≤ 目标 {target:.2f}，考虑回补",
                        severity="WARNING",
                    ))

    _check_account("a_share", is_cn=True)
    _check_account("us", is_cn=False)
    return alerts


# ─── Module 3: Update Positions ───────────────────────────────────────────────

def update_positions(state: dict, prices: dict[str, PriceData]) -> dict:
    """
    Update current_price, market_value, unrealized_pnl for all positions.
    Also recalculates account-level totals.
    Returns mutated state (in-place for dict).
    """

    def _update_account(account_key: str, is_cn: bool) -> None:
        account = state["accounts"][account_key]
        total_unrealized = 0.0

        for pos in account["positions"]:
            if pos.get("instrument_type") == "call_option":
                # 期权跳过价格更新，保留账面值
                continue

            raw_ticker = pos["ticker"]
            if is_cn:
                yf_ticker = cn_ticker_to_yf(raw_ticker)
            else:
                yf_ticker = us_ticker_to_yf(raw_ticker)
            pd_obj = prices.get(yf_ticker)

            if pd_obj and pd_obj.ok:
                current = pd_obj.price
                avg_cost = pos.get("avg_cost", 0)
                shares = pos.get("shares", 0)
                direction = pos.get("direction", "long")

                pos["current_price"] = current
                pos["prev_close"] = pd_obj.prev_close
                pos["change_pct"] = pd_obj.change_pct

                market_value = current * shares
                pos["market_value"] = round(market_value, 2)

                if direction == "long":
                    unrealized = (current - avg_cost) * shares
                else:
                    unrealized = (avg_cost - current) * shares

                pos["unrealized_pnl"] = round(unrealized, 2)
                pos["unrealized_pnl_pct"] = round(unrealized / (avg_cost * shares) * 100, 2) if avg_cost * shares != 0 else 0
                total_unrealized += unrealized
            else:
                # 保留上次价格，但标记获取失败
                pos["price_error"] = True
                mv = pos.get("market_value", 0)
                total_unrealized += pos.get("unrealized_pnl", 0)

        account["unrealized_pnl"] = round(total_unrealized, 2)

        # 更新账户总资产 = 现金 + 持仓市值
        total_mv = sum(
            p.get("market_value", 0)
            for p in account["positions"]
            if p.get("instrument_type") != "call_option"
        )
        # 期权的账面价值也加入（按买入成本）
        options_value = sum(
            p.get("market_value", 0)
            for p in account["positions"]
            if p.get("instrument_type") == "call_option"
        )
        account["total_assets"] = round(account["cash"] + total_mv + options_value, 2)

    _update_account("a_share", is_cn=True)
    _update_account("us", is_cn=False)
    return state


# ─── Module 4: Performance Calculation ────────────────────────────────────────

@dataclass
class PerformanceStats:
    date: str
    # A股
    a_share_nav: float
    a_share_return_pct: float
    a_share_daily_pnl: float
    a_share_realized: float
    a_share_unrealized: float
    # 美股
    us_nav: float
    us_return_pct: float
    us_daily_pnl: float
    us_realized: float
    us_unrealized: float
    # 基准
    sse_close: float | None
    spy_close: float | None
    sse_return_pct: float | None
    spy_return_pct: float | None
    # 超额
    a_share_alpha: float | None
    us_alpha: float | None


def calculate_performance(state: dict, prices: dict[str, PriceData], today: str) -> PerformanceStats:
    """Calculate daily and cumulative performance vs benchmarks."""
    a_acc = state["accounts"]["a_share"]
    us_acc = state["accounts"]["us"]
    perf = state["performance"]

    a_nav = a_acc["total_assets"]
    us_nav = us_acc["total_assets"]

    a_initial = a_acc["initial_capital"]
    us_initial = us_acc["initial_capital"]

    a_return_pct = round((a_nav / a_initial - 1) * 100, 2) if a_initial else 0
    us_return_pct = round((us_nav / us_initial - 1) * 100, 2) if us_initial else 0

    # 日度P&L: 与昨日snapshot对比
    # Support multiple field naming conventions across snapshot versions
    snapshots = perf.get("daily_snapshots", [])
    # Find most recent snapshot that is not today (to avoid double-counting)
    prev_snapshot = None
    for snap in reversed(snapshots):
        if snap.get("date", "") != today:
            prev_snapshot = snap
            break

    def _snap_a_nav(snap: dict) -> float:
        return float(
            snap.get("a_share_nav")
            or snap.get("a_share_total_assets")
            or snap.get("a_share_total")
            or snap.get("a_total_assets")
            or 0
        )

    def _snap_us_nav(snap: dict) -> float:
        return float(
            snap.get("us_nav")
            or snap.get("us_total_assets")
            or snap.get("us_total")
            or 0
        )

    a_daily_pnl = round(a_nav - _snap_a_nav(prev_snapshot), 2) if prev_snapshot else 0.0
    us_daily_pnl = round(us_nav - _snap_us_nav(prev_snapshot), 2) if prev_snapshot else 0.0

    # 基准价格
    sse_pd = prices.get(BENCHMARKS["cn"])
    spy_pd = prices.get(BENCHMARKS["us"])
    sse_close = sse_pd.price if sse_pd and sse_pd.ok else None
    spy_close = spy_pd.price if spy_pd and spy_pd.ok else None

    # 基准累计收益率（从初始baseline）
    sse_start = perf.get("benchmark", {}).get("sse_composite_start")
    spy_start = perf.get("benchmark", {}).get("spy_start")

    sse_return_pct = round((sse_close / sse_start - 1) * 100, 2) if (sse_close and sse_start) else None
    spy_return_pct = round((spy_close / spy_start - 1) * 100, 2) if (spy_close and spy_start) else None

    # 初始化基准起点（第一次运行）
    if sse_start is None and sse_close:
        perf["benchmark"]["sse_composite_start"] = sse_close
        sse_return_pct = 0.0
    if spy_start is None and spy_close:
        perf["benchmark"]["spy_start"] = spy_close
        spy_return_pct = 0.0

    a_alpha = round(a_return_pct - sse_return_pct, 2) if sse_return_pct is not None else None
    us_alpha = round(us_return_pct - spy_return_pct, 2) if spy_return_pct is not None else None

    return PerformanceStats(
        date=today,
        a_share_nav=a_nav,
        a_share_return_pct=a_return_pct,
        a_share_daily_pnl=a_daily_pnl,
        a_share_realized=a_acc.get("realized_pnl", 0),
        a_share_unrealized=a_acc.get("unrealized_pnl", 0),
        us_nav=us_nav,
        us_return_pct=us_return_pct,
        us_daily_pnl=us_daily_pnl,
        us_realized=us_acc.get("realized_pnl", 0),
        us_unrealized=us_acc.get("unrealized_pnl", 0),
        sse_close=sse_close,
        spy_close=spy_close,
        sse_return_pct=sse_return_pct,
        spy_return_pct=spy_return_pct,
        a_share_alpha=a_alpha,
        us_alpha=us_alpha,
    )


# ─── Module 5: Report Generation ──────────────────────────────────────────────

def _fmt_pct(v: float | None, suffix: str = "%") -> str:
    if v is None:
        return "N/A"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}{suffix}"


def _fmt_num(v: float | None, currency: str = "") -> str:
    if v is None:
        return "N/A"
    sign = "+" if v > 0 else ""
    if currency:
        return f"{sign}{currency}{v:,.2f}"
    return f"{sign}{v:,.2f}"


def generate_daily_report(
    state: dict,
    alerts: list[Alert],
    stats: PerformanceStats,
    prices: dict[str, PriceData],
    date: str,
) -> str:
    """Generate full markdown daily report."""
    lines: list[str] = []
    a = lines.append

    a(f"# 模拟盘每日报告 — {date}")
    a("")
    a(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} BJT")
    a("")

    # ── 1. 执行摘要 ──
    a("## 执行摘要")
    a("")
    a("| 维度 | A股账户 | 美股账户 |")
    a("|------|---------|---------|")
    a(f"| 账户净值 | ¥{stats.a_share_nav:,.2f} | ${stats.us_nav:,.2f} |")
    a(f"| 累计收益 | {_fmt_pct(stats.a_share_return_pct)} | {_fmt_pct(stats.us_return_pct)} |")
    a(f"| 今日P&L | {_fmt_num(stats.a_share_daily_pnl, '¥')} | {_fmt_num(stats.us_daily_pnl, '$')} |")
    a(f"| 基准收益 | {_fmt_pct(stats.sse_return_pct)} (沪深300) | {_fmt_pct(stats.spy_return_pct)} (SPY) |")
    a(f"| Alpha | {_fmt_pct(stats.a_share_alpha)} | {_fmt_pct(stats.us_alpha)} |")
    a(f"| 已实现P&L | ¥{stats.a_share_realized:,.2f} | ${stats.us_realized:,.2f} |")
    a(f"| 未实现P&L | ¥{stats.a_share_unrealized:,.2f} | ${stats.us_unrealized:,.2f} |")
    a("")

    # ── 2. 触发警报 ──
    critical_alerts = [al for al in alerts if al.severity == "CRITICAL"]
    warning_alerts = [al for al in alerts if al.severity == "WARNING"]
    info_alerts = [al for al in alerts if al.severity == "INFO"]

    a("## 触发警报")
    a("")
    if not alerts:
        a("> ✅ 无触发警报")
    else:
        if critical_alerts:
            a("### 🔴 CRITICAL — 需立即处理")
            for al in critical_alerts:
                a(f"- **[{al.account.upper()}] {al.ticker} {al.name}**: {al.message}")
            a("")
        if warning_alerts:
            a("### 🟡 WARNING — 关注")
            for al in warning_alerts:
                a(f"- **[{al.account.upper()}] {al.ticker} {al.name}**: {al.message}")
            a("")
        if info_alerts:
            a("### 🔵 INFO")
            for al in info_alerts:
                a(f"- [{al.account.upper()}] {al.ticker}: {al.message}")
            a("")
    a("")

    # ── 3. A股持仓 ──
    a("## A股持仓")
    a("")
    a_positions = state["accounts"]["a_share"]["positions"]
    if not a_positions:
        a("> 暂无持仓")
    else:
        a("| 股票 | 名称 | 股数 | 均价 | 现价 | 今日% | 市值 | 浮盈亏 | 浮盈% | 止损 | 目标 |")
        a("|------|------|------|------|------|-------|------|--------|-------|------|------|")
        for pos in a_positions:
            if pos.get("instrument_type") == "call_option":
                continue
            ticker = pos["ticker"]
            yf_tk = cn_ticker_to_yf(ticker)
            pd_obj = prices.get(yf_tk)
            chg = pd_obj.change_pct if (pd_obj and pd_obj.ok) else None
            stop = pos.get("stop_loss") or pos.get("stop") or 0
            target = pos.get("target_1") or pos.get("target") or 0
            a(
                f"| {ticker} | {pos.get('name', '-')} "
                f"| {pos.get('shares', 0):,} "
                f"| ¥{pos.get('avg_cost', 0):.2f} "
                f"| ¥{pos.get('current_price', 0):.2f} "
                f"| {_fmt_pct(chg)} "
                f"| ¥{pos.get('market_value', 0):,.0f} "
                f"| ¥{pos.get('unrealized_pnl', 0):+,.0f} "
                f"| {_fmt_pct(pos.get('unrealized_pnl_pct'))} "
                f"| ¥{stop:.2f} "
                f"| ¥{target:.2f} |"
            )
    a("")
    a_cash = state["accounts"]["a_share"]["cash"]
    a_total = state["accounts"]["a_share"]["total_assets"]
    a_cash_pct = round(a_cash / a_total * 100, 1) if a_total else 0
    a(f"**A股现金**: ¥{a_cash:,.2f} ({a_cash_pct}%)")
    a("")

    # ── 4. 美股持仓 ──
    a("## 美股持仓")
    a("")
    us_positions = state["accounts"]["us"]["positions"]
    if not us_positions:
        a("> 暂无持仓")
    else:
        a("| 代码 | 名称 | 股数/合约 | 均价 | 现价 | 今日% | 市值 | 浮盈亏 | 浮盈% | 止损 | 目标 |")
        a("|------|------|----------|------|------|-------|------|--------|-------|------|------|")
        for pos in us_positions:
            ticker = pos["ticker"]
            is_option = pos.get("instrument_type") == "call_option"
            if is_option:
                a(
                    f"| {ticker} | {pos.get('name', '-')} (期权) "
                    f"| {pos.get('contracts', 0)} 合约 "
                    f"| ${pos.get('avg_cost', 0):.2f} "
                    f"| (跳过) | — "
                    f"| ${pos.get('market_value', 0):,.0f} "
                    f"| — | — | ${pos.get('stop', 0):.2f} | ${pos.get('target', 0):.2f} |"
                )
            else:
                yf_tk = us_ticker_to_yf(ticker)
                pd_obj = prices.get(yf_tk)
                chg = pd_obj.change_pct if (pd_obj and pd_obj.ok) else None
                stop = pos.get("stop_loss") or pos.get("stop") or 0
                target = pos.get("target_1") or pos.get("target") or 0
                a(
                    f"| {ticker} | {pos.get('name', '-')} "
                    f"| {pos.get('shares', 0):,} "
                    f"| ${pos.get('avg_cost', 0):.2f} "
                    f"| ${pos.get('current_price', 0):.2f} "
                    f"| {_fmt_pct(chg)} "
                    f"| ${pos.get('market_value', 0):,.0f} "
                    f"| ${pos.get('unrealized_pnl', 0):+,.0f} "
                    f"| {_fmt_pct(pos.get('unrealized_pnl_pct'))} "
                    f"| ${stop:.2f} "
                    f"| ${target:.2f} |"
                )
    a("")
    us_cash = state["accounts"]["us"]["cash"]
    us_total = state["accounts"]["us"]["total_assets"]
    us_cash_pct = round(us_cash / us_total * 100, 1) if us_total else 0
    a(f"**美股现金**: ${us_cash:,.2f} ({us_cash_pct}%)")
    a("")

    # ── 5. 基准价格 ──
    a("## 基准行情")
    a("")
    a("| 基准 | 今日收盘 | 今日涨跌 | 累计涨跌 |")
    a("|------|---------|---------|---------|")
    sse_pd = prices.get(BENCHMARKS["cn"])
    spy_pd = prices.get(BENCHMARKS["us"])
    if sse_pd and sse_pd.ok:
        a(f"| 沪深300 | {sse_pd.price:.2f} | {_fmt_pct(sse_pd.change_pct)} | {_fmt_pct(stats.sse_return_pct)} |")
    else:
        a(f"| 沪深300 | 获取失败 | — | — |")
    if spy_pd and spy_pd.ok:
        a(f"| SPY | ${spy_pd.price:.2f} | {_fmt_pct(spy_pd.change_pct)} | {_fmt_pct(stats.spy_return_pct)} |")
    else:
        a(f"| SPY | 获取失败 | — | — |")
    a("")

    # ── 6. 今日交易记录 ──
    a("## 今日交易记录")
    a("")
    today_trades = [t for t in state.get("trade_log", []) if t.get("date") == date]
    if not today_trades:
        a("> 今日无交易")
    else:
        a("| 时间 | 账户 | 代码 | 操作 | 股数 | 价格 | 金额 | 原因 |")
        a("|------|------|------|------|------|------|------|------|")
        for tr in today_trades:
            a(
                f"| {tr.get('time', '-')} "
                f"| {tr.get('account', '-')} "
                f"| {tr.get('ticker', '-')} "
                f"| {tr.get('action', '-')} "
                f"| {tr.get('shares', '-')} "
                f"| {tr.get('price', 0):.2f} "
                f"| {tr.get('amount', 0):,.0f} "
                f"| {tr.get('reason', '-')} |"
            )
    a("")

    # ── 7. 价格获取状态 ──
    errors = {t: pd for t, pd in prices.items() if not pd.ok}
    if errors:
        a("## 价格获取异常")
        a("")
        for tk, pd in errors.items():
            a(f"- `{tk}`: {pd.error}")
        a("")

    # ── 8. 待处理事项 ──
    pending = state.get("pending_orders", [])
    if pending:
        a("## 待处理订单")
        a("")
        for order in pending:
            a(
                f"- **{order.get('ticker')}** {order.get('action')} "
                f"{order.get('shares', '')} 股 @ {order.get('limit_price', 'MKT')} "
                f"| 原因: {order.get('reason', '-')}"
            )
        a("")

    a("---")
    a(f"*由 trading_engine.py 自动生成 | {datetime.now().isoformat()}*")

    return "\n".join(lines)


# ─── Module 6: Atomic State Save ─────────────────────────────────────────────

def save_state(state: dict, path: Path) -> None:
    """Write JSON atomically: write to tmp → fsync → rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".portfolio_tmp_", suffix=".json")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)  # atomic on POSIX
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ─── Module 7: Main ────────────────────────────────────────────────────────────

def _update_daily_snapshot(state: dict, stats: PerformanceStats) -> None:
    """Append or update today's snapshot in performance.daily_snapshots."""
    snapshots = state["performance"]["daily_snapshots"]
    today = stats.date

    # Remove existing entry for today (idempotent re-runs)
    state["performance"]["daily_snapshots"] = [s for s in snapshots if s.get("date") != today]

    snapshot = {
        "date": today,
        "a_share_nav": stats.a_share_nav,
        "a_share_return_pct": stats.a_share_return_pct,
        "us_nav": stats.us_nav,
        "us_return_pct": stats.us_return_pct,
        "sse_close": stats.sse_close,
        "spy_close": stats.spy_close,
        "sse_return_pct": stats.sse_return_pct,
        "spy_return_pct": stats.spy_return_pct,
        "a_share_alpha": stats.a_share_alpha,
        "us_alpha": stats.us_alpha,
        "a_share_daily_pnl": stats.a_share_daily_pnl,
        "us_daily_pnl": stats.us_daily_pnl,
    }
    state["performance"]["daily_snapshots"].append(snapshot)

    # Update top-level performance fields
    state["performance"]["total_return_cny"] = round(
        stats.a_share_nav - state["accounts"]["a_share"]["initial_capital"], 2
    )
    state["performance"]["total_return_usd"] = round(
        stats.us_nav - state["accounts"]["us"]["initial_capital"], 2
    )
    state["performance"]["total_return_pct_cny"] = stats.a_share_return_pct
    state["performance"]["total_return_pct_usd"] = stats.us_return_pct


def _print_summary(stats: PerformanceStats, alerts: list[Alert], console: Console) -> None:
    """Print a concise summary table to stdout for remote agent consumption."""
    console.print(f"\n[bold cyan]===== 模拟盘每日引擎 {stats.date} =====[/bold cyan]")

    # Performance table
    perf_table = Table(title="账户表现", show_header=True, header_style="bold")
    perf_table.add_column("账户")
    perf_table.add_column("净值", justify="right")
    perf_table.add_column("累计", justify="right")
    perf_table.add_column("今日P&L", justify="right")
    perf_table.add_column("vs基准", justify="right")

    def _color_pct(v: float | None) -> str:
        if v is None:
            return "N/A"
        sign = "+" if v > 0 else ""
        color = "green" if v > 0 else "red" if v < 0 else "white"
        return f"[{color}]{sign}{v:.2f}%[/{color}]"

    perf_table.add_row(
        "A股 (CNY)",
        f"¥{stats.a_share_nav:,.0f}",
        _color_pct(stats.a_share_return_pct),
        f"[{'green' if stats.a_share_daily_pnl >= 0 else 'red'}]¥{stats.a_share_daily_pnl:+,.0f}[/]",
        _color_pct(stats.a_share_alpha),
    )
    perf_table.add_row(
        "美股 (USD)",
        f"${stats.us_nav:,.0f}",
        _color_pct(stats.us_return_pct),
        f"[{'green' if stats.us_daily_pnl >= 0 else 'red'}]${stats.us_daily_pnl:+,.0f}[/]",
        _color_pct(stats.us_alpha),
    )
    console.print(perf_table)

    # Alerts
    if alerts:
        console.print(f"\n[bold yellow]警报 ({len(alerts)}条):[/bold yellow]")
        for al in alerts:
            color = "red" if al.severity == "CRITICAL" else "yellow"
            console.print(f"  [{color}][{al.severity}][/{color}] {al.account.upper()} {al.ticker}: {al.message}")
    else:
        console.print("\n[green]✅ 无触发警报[/green]")

    console.print("")


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude模拟盘每日交易引擎")
    parser.add_argument("--date", default=None, help="运行日期 YYYY-MM-DD (默认今日)")
    parser.add_argument("--dry-run", action="store_true", help="不写入文件，仅打印")
    parser.add_argument("--state-file", default=str(STATE_FILE), help="portfolio_state.json路径")
    parser.add_argument("--output-dir", default=str(DAILY_DIR), help="每日报告输出目录")
    args = parser.parse_args()

    console = Console()
    today = args.date or datetime.now().strftime("%Y-%m-%d")
    state_path = Path(args.state_file)
    output_dir = Path(args.output_dir)

    # ─── Step 0: 加载状态 ───
    console.print(f"[dim]读取状态文件: {state_path}[/dim]")
    if not state_path.exists():
        console.print(f"[red]ERROR: portfolio_state.json 不存在: {state_path}[/red]")
        return 1

    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except json.JSONDecodeError as e:
        console.print(f"[red]ERROR: JSON解析失败: {e}[/red]")
        return 1

    # ─── Step 1: 获取价格 ───
    console.print("[dim]获取最新价格...[/dim]")
    try:
        prices = fetch_all_prices(state)
    except Exception as e:
        console.print(f"[red]ERROR: 价格获取失败: {e}[/red]")
        traceback.print_exc()
        return 1

    ok_count = sum(1 for pd in prices.values() if pd.ok)
    err_count = len(prices) - ok_count
    console.print(f"[dim]价格获取完成: {ok_count}成功 / {err_count}失败[/dim]")

    # ─── Step 2: 检查触发 ───
    alerts = check_triggers(state, prices)

    # ─── Step 3: 更新持仓 ───
    state = update_positions(state, prices)

    # ─── Step 4: 计算表现 ───
    stats = calculate_performance(state, prices, today)

    # ─── Step 5: 打印摘要 ───
    _print_summary(stats, alerts, console)

    # ─── Step 6: 生成报告 ───
    report_md = generate_daily_report(state, alerts, stats, prices, today)

    # ─── Step 7: 更新state并写入 ───
    _update_daily_snapshot(state, stats)
    state["_meta"]["last_updated"] = datetime.now(timezone.utc).astimezone().isoformat()
    state["_meta"]["update_trigger"] = "daily_engine"
    state["_meta"]["last_engine_run"] = today

    if args.dry_run:
        console.print("[yellow]--dry-run: 不写入任何文件[/yellow]")
        console.print("\n--- 报告预览 (前50行) ---")
        preview_lines = report_md.split("\n")[:50]
        console.print("\n".join(preview_lines))
    else:
        # 写入报告
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / f"{today}.md"
        report_path.write_text(report_md, encoding="utf-8")
        console.print(f"[green]报告已写入: {report_path}[/green]")

        # 原子性保存state
        save_state(state, state_path)
        console.print(f"[green]状态已更新: {state_path}[/green]")

    # ─── Step 8: 结构化摘要输出（给远程agent解析）───
    # 最后输出JSON摘要，方便agent读取关键数据
    summary = {
        "date": today,
        "run_time": datetime.now().isoformat(),
        "a_share": {
            "nav": stats.a_share_nav,
            "return_pct": stats.a_share_return_pct,
            "daily_pnl": stats.a_share_daily_pnl,
            "alpha": stats.a_share_alpha,
        },
        "us": {
            "nav": stats.us_nav,
            "return_pct": stats.us_return_pct,
            "daily_pnl": stats.us_daily_pnl,
            "alpha": stats.us_alpha,
        },
        "alerts_count": len(alerts),
        "critical_alerts": [
            {"ticker": al.ticker, "type": al.alert_type, "message": al.message}
            for al in alerts if al.severity == "CRITICAL"
        ],
        "price_errors": [t for t, pd in prices.items() if not pd.ok],
        "dry_run": args.dry_run,
    }
    print("\n__ENGINE_SUMMARY_JSON__")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
