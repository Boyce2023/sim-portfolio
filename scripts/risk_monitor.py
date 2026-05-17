# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "rich>=13.0"]
# ///
"""
风控监控脚本 — Claude模拟盘
读取 portfolio_state.json + watchlist_config.json，执行全套风控检查。
Critical alert（止损触发/组合回撤>10%）时以 EXIT CODE 1 退出。

用法:
    uv run scripts/risk_monitor.py             # 从项目根目录运行
    uv run scripts/risk_monitor.py --no-save   # 不保存markdown报告
"""

from __future__ import annotations

import json
import sys
import argparse
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal, Optional

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

# ──────────────────────────────────────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────────────────────────────────────
AlertLevel = Literal["critical", "warning", "info"]

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
    position_weights: list[dict] = field(default_factory=list)
    sector_weights: dict[str, float] = field(default_factory=dict)

    @property
    def has_critical(self) -> bool:
        return any(a.level == "critical" for a in self.alerts)

    @property
    def criticals(self) -> list[Alert]:
        return [a for a in self.alerts if a.level == "critical"]

    @property
    def warnings(self) -> list[Alert]:
        return [a for a in self.alerts if a.level == "warning"]


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
    if not WATCHLIST_PATH.exists():
        console.print(f"[red]ERROR: watchlist_config.json not found at {WATCHLIST_PATH}[/red]")
        sys.exit(2)
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        return json.load(f)


def build_watchlist_index(watchlist: dict) -> dict[str, dict]:
    """ticker → watchlist entry 的快速查找表"""
    index: dict[str, dict] = {}
    for item in watchlist.get("us_watchlist", []):
        index[item["ticker"]] = item
    for item in watchlist.get("cn_watchlist", []):
        index[item["ticker"]] = item
    return index


# ──────────────────────────────────────────────────────────────────────────────
# 实时价格获取
# ──────────────────────────────────────────────────────────────────────────────
def _yf_suffix(ticker: str) -> str:
    """A股代码加交易所后缀"""
    if ticker.startswith("6"):
        return ticker + ".SS"
    return ticker + ".SZ"


def fetch_current_prices(positions_us: list[dict], positions_cn: list[dict]) -> dict[str, float | None]:
    """返回 ticker → 当前价格（无价格时为 None）"""
    prices: dict[str, float | None] = {}

    us_tickers = [p["ticker"] for p in positions_us]
    for ticker in us_tickers:
        try:
            info = yf.Ticker(ticker).fast_info
            prices[ticker] = float(info.last_price) if info.last_price else None
        except Exception:
            prices[ticker] = None

    for pos in positions_cn:
        ticker = pos["ticker"]
        try:
            yf_ticker = _yf_suffix(ticker)
            info = yf.Ticker(yf_ticker).fast_info
            prices[ticker] = float(info.last_price) if info.last_price else None
        except Exception:
            prices[ticker] = None

    return prices


# ──────────────────────────────────────────────────────────────────────────────
# 风控规则引擎
# ──────────────────────────────────────────────────────────────────────────────
def _effective_price(pos: dict, live_prices: dict[str, float | None]) -> float:
    """优先使用实时价格，回退到 last_price 字段"""
    live = live_prices.get(pos["ticker"])
    if live is not None:
        return live
    return float(pos.get("last_price", pos.get("avg_cost", 0)))


def check_single_position_weight(
    pos: dict,
    total_assets: float,
    wl_index: dict,
    portfolio_rules: dict,
    alerts: list[Alert],
    live_prices: dict[str, float | None],
):
    """规则1: 单只仓位是否超过 max_weight_pct"""
    if total_assets <= 0:
        return
    ticker = pos["ticker"]
    price = _effective_price(pos, live_prices)
    quantity = pos.get("quantity", 0)
    market_value = price * quantity
    weight_pct = market_value / total_assets * 100

    # 从 watchlist 获取个股上限，fallback 到 portfolio_rules 全局上限
    wl_entry = wl_index.get(ticker, {})
    max_weight = wl_entry.get("max_weight_pct", portfolio_rules.get("max_single_position_pct", 15))
    global_max = portfolio_rules.get("max_single_position_pct", 15)
    effective_max = min(max_weight, global_max)

    if weight_pct > effective_max:
        alerts.append(Alert(
            level="warning",
            ticker=ticker,
            rule="单仓超限",
            detail=f"当前权重 {weight_pct:.1f}%，上限 {effective_max:.0f}%",
            value=weight_pct,
            threshold=effective_max,
        ))

    return {"ticker": ticker, "weight_pct": weight_pct, "market_value": market_value,
            "sector": wl_entry.get("sector", "未分类"), "max_weight": effective_max,
            "stop_pct": wl_entry.get("stop_pct"), "avg_cost": pos.get("avg_cost"),
            "current_price": price, "confidence": wl_entry.get("confidence", "?")}


def check_sector_weight(
    sector_weights: dict[str, float],
    sector_limit: float,
    alerts: list[Alert],
):
    """规则2: 板块是否超过 30%（或 sector_limits 配置值）"""
    for sector, weight in sector_weights.items():
        if weight > sector_limit:
            alerts.append(Alert(
                level="warning",
                ticker="PORTFOLIO",
                rule="板块超限",
                detail=f"板块「{sector}」权重 {weight:.1f}%，上限 {sector_limit:.0f}%",
                value=weight,
                threshold=sector_limit,
            ))


def check_cash_level(
    cash: float,
    total_assets: float,
    min_cash_pct: float,
    account_label: str,
    alerts: list[Alert],
) -> float:
    """规则3: 现金是否低于 20%"""
    if total_assets <= 0:
        return 0.0
    cash_pct = cash / total_assets * 100
    if cash_pct < min_cash_pct:
        alerts.append(Alert(
            level="warning",
            ticker=account_label,
            rule="现金不足",
            detail=f"现金比例 {cash_pct:.1f}%，最低要求 {min_cash_pct:.0f}%",
            value=cash_pct,
            threshold=min_cash_pct,
        ))
    return cash_pct


def check_portfolio_drawdown(
    initial_capital: float,
    total_assets: float,
    max_drawdown_pct: float,
    account_label: str,
    alerts: list[Alert],
) -> float:
    """规则4: 组合级最大回撤是否超过 10%"""
    if initial_capital <= 0:
        return 0.0
    drawdown_pct = (total_assets - initial_capital) / initial_capital * 100
    if drawdown_pct < max_drawdown_pct:  # max_drawdown_pct 是负数如 -10
        alerts.append(Alert(
            level="critical",
            ticker=account_label,
            rule="组合回撤超限",
            detail=f"账户回撤 {drawdown_pct:.1f}%，触发阈值 {max_drawdown_pct:.0f}%",
            value=drawdown_pct,
            threshold=max_drawdown_pct,
        ))
    return drawdown_pct


def check_stop_loss_proximity(
    pos: dict,
    wl_index: dict,
    alerts: list[Alert],
    live_prices: dict[str, float | None],
    buffer_pct: float = 5.0,
):
    """规则5: 任何持仓是否接近止损（距止损线 < buffer_pct）"""
    ticker = pos["ticker"]
    wl_entry = wl_index.get(ticker)
    if not wl_entry:
        return

    stop_pct = wl_entry.get("stop_pct")  # 负数，如 -12
    trailing_stop_pct = wl_entry.get("trailing_stop_pct")  # 负数，如 -15
    avg_cost = pos.get("avg_cost")
    if avg_cost is None or avg_cost <= 0:
        return

    current_price = _effective_price(pos, live_prices)
    if current_price <= 0:
        return

    pnl_pct = (current_price - avg_cost) / avg_cost * 100

    # 硬止损检查
    if stop_pct is not None:
        distance_to_stop = pnl_pct - stop_pct  # 距止损还有多少空间
        if distance_to_stop < 0:
            # 已经突破止损线
            alerts.append(Alert(
                level="critical",
                ticker=ticker,
                rule="止损触发",
                detail=f"当前亏损 {pnl_pct:.1f}%，已突破止损线 {stop_pct:.0f}%，立即执行止损！",
                value=pnl_pct,
                threshold=stop_pct,
            ))
        elif distance_to_stop < buffer_pct:
            alerts.append(Alert(
                level="warning",
                ticker=ticker,
                rule="接近止损",
                detail=f"当前亏损 {pnl_pct:.1f}%，距止损线 {stop_pct:.0f}% 仅剩 {distance_to_stop:.1f}%",
                value=pnl_pct,
                threshold=stop_pct,
            ))

    # 移动止损检查（基于 highest_price 字段，若无则跳过）
    highest_price = pos.get("highest_price")
    if highest_price and trailing_stop_pct is not None and highest_price > 0:
        drawdown_from_high = (current_price - highest_price) / highest_price * 100
        distance_to_trailing = drawdown_from_high - trailing_stop_pct
        if distance_to_trailing < 0:
            alerts.append(Alert(
                level="critical",
                ticker=ticker,
                rule="移动止损触发",
                detail=f"从最高价回撤 {drawdown_from_high:.1f}%，已突破移动止损 {trailing_stop_pct:.0f}%",
                value=drawdown_from_high,
                threshold=trailing_stop_pct,
            ))
        elif distance_to_trailing < buffer_pct:
            alerts.append(Alert(
                level="warning",
                ticker=ticker,
                rule="接近移动止损",
                detail=f"从最高价回撤 {drawdown_from_high:.1f}%，距移动止损 {trailing_stop_pct:.0f}% 仅剩 {distance_to_trailing:.1f}%",
                value=drawdown_from_high,
                threshold=trailing_stop_pct,
            ))


# ──────────────────────────────────────────────────────────────────────────────
# 主执行逻辑
# ──────────────────────────────────────────────────────────────────────────────
def run_risk_check(fetch_live: bool = True) -> RiskReport:
    portfolio = load_portfolio()
    watchlist = load_watchlist()
    wl_index = build_watchlist_index(watchlist)
    portfolio_rules = watchlist.get("portfolio_rules", {})
    sector_config = watchlist.get("sector_limits", {})

    us_account = portfolio["accounts"]["us"]
    cn_account = portfolio["accounts"]["a_share"]
    positions_us: list[dict] = us_account.get("positions", [])
    positions_cn: list[dict] = cn_account.get("positions", [])

    # 获取实时价格
    live_prices: dict[str, float | None] = {}
    if fetch_live and (positions_us or positions_cn):
        with console.status("[dim]正在获取实时价格...[/dim]"):
            live_prices = fetch_current_prices(positions_us, positions_cn)

    report = RiskReport(generated_at=datetime.now().isoformat())

    # ── 账户资产计算 ────────────────────────────────────────────────────────
    # 用实时价格重算总资产（如果有持仓+实时价格）
    def calc_total_assets(account: dict, positions: list[dict], is_cn: bool) -> float:
        cash = float(account.get("cash", 0))
        position_value = sum(
            _effective_price(p, live_prices) * p.get("quantity", 0)
            for p in positions
        )
        return cash + position_value

    us_total = calc_total_assets(us_account, positions_us, is_cn=False)
    cn_total = calc_total_assets(cn_account, positions_cn, is_cn=True)
    us_cash = float(us_account.get("cash", 0))
    cn_cash = float(cn_account.get("cash", 0))
    us_initial = float(us_account.get("initial_capital", us_total))
    cn_initial = float(cn_account.get("initial_capital", cn_total))

    report.us_total_assets = us_total
    report.cn_total_assets = cn_total
    report.us_cash = us_cash
    report.cn_cash = cn_cash

    alerts = report.alerts

    # ── 规则3: 现金比例 ──────────────────────────────────────────────────────
    min_cash_pct = portfolio_rules.get("min_cash_pct", 20)
    report.us_cash_pct = check_cash_level(us_cash, us_total, min_cash_pct, "US账户", alerts)
    report.cn_cash_pct = check_cash_level(cn_cash, cn_total, min_cash_pct, "A股账户", alerts)

    # ── 规则4: 组合回撤 ──────────────────────────────────────────────────────
    max_drawdown_pct = portfolio_rules.get("max_portfolio_drawdown_pct", -10)
    report.us_drawdown_pct = check_portfolio_drawdown(us_initial, us_total, max_drawdown_pct, "US账户", alerts)
    report.cn_drawdown_pct = check_portfolio_drawdown(cn_initial, cn_total, max_drawdown_pct, "A股账户", alerts)

    # ── 规则1+5: 单仓 + 止损 ─────────────────────────────────────────────────
    stop_buffer = portfolio_rules.get("stop_loss_alert_buffer_pct", 5)
    sector_weights: dict[str, float] = {}
    position_summaries: list[dict] = []

    all_positions = [(p, us_total, False) for p in positions_us] + \
                    [(p, cn_total, True) for p in positions_cn]

    for pos, total_assets, is_cn in all_positions:
        summary = check_single_position_weight(pos, total_assets, wl_index, portfolio_rules, alerts, live_prices)
        if summary:
            position_summaries.append({**summary, "is_cn": is_cn, "total_assets": total_assets})
            # 累计板块权重（按各自账户的资产计算，仅用于参考）
            sector = summary["sector"]
            sector_weights[sector] = sector_weights.get(sector, 0) + summary["weight_pct"]

        check_stop_loss_proximity(pos, wl_index, alerts, live_prices, buffer_pct=stop_buffer)

    report.position_weights = position_summaries
    report.sector_weights = sector_weights

    # ── 规则2: 板块超限 ──────────────────────────────────────────────────────
    max_sector_pct = portfolio_rules.get("max_sector_pct", 30)
    check_sector_weight(sector_weights, max_sector_pct, alerts)

    # ── 持仓数量检查 ─────────────────────────────────────────────────────────
    total_positions = len(positions_us) + len(positions_cn)
    max_positions = portfolio_rules.get("max_positions", 12)
    if total_positions > max_positions:
        alerts.append(Alert(
            level="warning",
            ticker="PORTFOLIO",
            rule="持仓数量超限",
            detail=f"当前持仓 {total_positions} 只，上限 {max_positions} 只",
            value=float(total_positions),
            threshold=float(max_positions),
        ))

    # ── C级标的合计仓位 ──────────────────────────────────────────────────────
    c_grade_total = sum(
        s["weight_pct"] for s in position_summaries
        if wl_index.get(s["ticker"], {}).get("confidence") == "C"
    )
    c_grade_max = portfolio_rules.get("c_grade_total_max_pct", 15)
    if c_grade_total > c_grade_max:
        alerts.append(Alert(
            level="warning",
            ticker="PORTFOLIO",
            rule="C级仓位超限",
            detail=f"C级标的合计 {c_grade_total:.1f}%，上限 {c_grade_max:.0f}%",
            value=c_grade_total,
            threshold=float(c_grade_max),
        ))

    return report


# ──────────────────────────────────────────────────────────────────────────────
# Rich 终端输出
# ──────────────────────────────────────────────────────────────────────────────
def _level_style(level: AlertLevel) -> str:
    return {"critical": "bold red", "warning": "yellow", "info": "cyan"}.get(level, "white")


def _level_icon(level: AlertLevel) -> str:
    return {"critical": "[bold red]CRITICAL[/bold red]",
            "warning": "[yellow]WARNING [/yellow]",
            "info":    "[cyan]INFO    [/cyan]"}.get(level, level)


def print_report(report: RiskReport):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_color = "red" if report.has_critical else ("yellow" if report.warnings else "green")
    status_text = "CRITICAL" if report.has_critical else ("WARNING" if report.warnings else "CLEAR")

    console.print()
    console.print(Panel(
        f"[bold]Claude 模拟盘 — 风控监控报告[/bold]\n"
        f"生成时间: {now_str}  |  状态: [{status_color}]{status_text}[/{status_color}]  |  "
        f"告警: [red]{len(report.criticals)}条CRITICAL[/red] / [yellow]{len(report.warnings)}条WARNING[/yellow]",
        border_style=status_color,
        box=box.DOUBLE_EDGE,
    ))

    # ── 账户概览 ─────────────────────────────────────────────────────────────
    overview = Table(title="账户概览", box=box.SIMPLE_HEAD, show_lines=False)
    overview.add_column("账户", style="bold")
    overview.add_column("总资产", justify="right")
    overview.add_column("现金", justify="right")
    overview.add_column("现金比例", justify="right")
    overview.add_column("回撤", justify="right")

    def _cash_style(pct: float) -> str:
        return "red bold" if pct < 20 else ("yellow" if pct < 25 else "green")

    def _drawdown_style(pct: float) -> str:
        return "red bold" if pct < -10 else ("yellow" if pct < -5 else "green")

    us_cash_pct_str = Text(f"{report.us_cash_pct:.1f}%", style=_cash_style(report.us_cash_pct))
    cn_cash_pct_str = Text(f"{report.cn_cash_pct:.1f}%", style=_cash_style(report.cn_cash_pct))
    us_dd_str = Text(f"{report.us_drawdown_pct:+.2f}%", style=_drawdown_style(report.us_drawdown_pct))
    cn_dd_str = Text(f"{report.cn_drawdown_pct:+.2f}%", style=_drawdown_style(report.cn_drawdown_pct))

    overview.add_row("US", f"${report.us_total_assets:,.0f}", f"${report.us_cash:,.0f}", us_cash_pct_str, us_dd_str)
    overview.add_row("A股", f"¥{report.cn_total_assets:,.0f}", f"¥{report.cn_cash:,.0f}", cn_cash_pct_str, cn_dd_str)
    console.print(overview)

    # ── 持仓权重表 ────────────────────────────────────────────────────────────
    if report.position_weights:
        pos_table = Table(title="持仓权重", box=box.SIMPLE_HEAD, show_lines=False)
        pos_table.add_column("Ticker", style="bold")
        pos_table.add_column("市场")
        pos_table.add_column("板块")
        pos_table.add_column("评级", justify="center")
        pos_table.add_column("权重%", justify="right")
        pos_table.add_column("上限%", justify="right")
        pos_table.add_column("均价", justify="right")
        pos_table.add_column("现价", justify="right")
        pos_table.add_column("P&L%", justify="right")
        pos_table.add_column("止损", justify="right")

        for s in sorted(report.position_weights, key=lambda x: -x["weight_pct"]):
            avg = s.get("avg_cost") or 0
            cur = s.get("current_price") or 0
            pnl_pct = (cur - avg) / avg * 100 if avg > 0 else 0
            stop = s.get("stop_pct")

            weight_style = "red bold" if s["weight_pct"] > s["max_weight"] else (
                "yellow" if s["weight_pct"] > s["max_weight"] * 0.9 else "default")
            pnl_style = "green" if pnl_pct >= 0 else "red"
            conf = s.get("confidence", "?")
            conf_style = {"A": "green bold", "B": "yellow", "C": "red"}.get(conf, "white")
            mkt = "A股" if s.get("is_cn") else "US"
            price_fmt = f"¥{cur:.2f}" if s.get("is_cn") else f"${cur:.2f}"
            avg_fmt = f"¥{avg:.2f}" if s.get("is_cn") else f"${avg:.2f}"

            pos_table.add_row(
                s["ticker"],
                mkt,
                s.get("sector", "")[:12],
                Text(conf, style=conf_style),
                Text(f"{s['weight_pct']:.1f}%", style=weight_style),
                f"{s['max_weight']:.0f}%",
                avg_fmt if avg > 0 else "—",
                price_fmt if cur > 0 else "—",
                Text(f"{pnl_pct:+.1f}%", style=pnl_style) if avg > 0 else Text("—"),
                f"{stop:.0f}%" if stop else "—",
            )
        console.print(pos_table)
    else:
        console.print("[dim]当前无持仓[/dim]\n")

    # ── 板块分布 ─────────────────────────────────────────────────────────────
    if report.sector_weights:
        sec_table = Table(title="板块分布", box=box.SIMPLE_HEAD, show_lines=False)
        sec_table.add_column("板块")
        sec_table.add_column("合计权重%", justify="right")
        sec_table.add_column("状态", justify="center")
        for sec, w in sorted(report.sector_weights.items(), key=lambda x: -x[1]):
            status = "[red]超限[/red]" if w > 30 else ("[yellow]偏高[/yellow]" if w > 25 else "[green]正常[/green]")
            sec_table.add_row(sec, f"{w:.1f}%", status)
        console.print(sec_table)

    # ── 告警列表 ─────────────────────────────────────────────────────────────
    console.print()
    if not report.alerts:
        console.print(Panel("[bold green]所有风控检查通过，无告警[/bold green]", border_style="green"))
    else:
        alert_table = Table(title="风控告警", box=box.SIMPLE_HEAD, show_lines=True)
        alert_table.add_column("级别", justify="center", min_width=10)
        alert_table.add_column("标的")
        alert_table.add_column("规则")
        alert_table.add_column("详情")

        for a in sorted(report.alerts, key=lambda x: {"critical": 0, "warning": 1, "info": 2}[x.level]):
            alert_table.add_row(
                _level_icon(a.level),
                a.ticker,
                a.rule,
                a.detail,
            )
        console.print(alert_table)

    console.print()


# ──────────────────────────────────────────────────────────────────────────────
# Markdown 报告
# ──────────────────────────────────────────────────────────────────────────────
def save_markdown_report(report: RiskReport) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = REPORTS_DIR / f"risk-{date_str}.md"

    lines = [
        f"# 风控监控报告 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**状态**: {'CRITICAL' if report.has_critical else ('WARNING' if report.warnings else 'CLEAR')}  ",
        f"**告警**: {len(report.criticals)} CRITICAL / {len(report.warnings)} WARNING",
        "",
        "## 账户概览",
        "",
        "| 账户 | 总资产 | 现金 | 现金比例 | 回撤 |",
        "|------|--------|------|----------|------|",
        f"| US | ${report.us_total_assets:,.0f} | ${report.us_cash:,.0f} | {report.us_cash_pct:.1f}% | {report.us_drawdown_pct:+.2f}% |",
        f"| A股 | ¥{report.cn_total_assets:,.0f} | ¥{report.cn_cash:,.0f} | {report.cn_cash_pct:.1f}% | {report.cn_drawdown_pct:+.2f}% |",
        "",
    ]

    if report.position_weights:
        lines += [
            "## 持仓权重",
            "",
            "| Ticker | 市场 | 板块 | 评级 | 权重% | 上限% | 均价 | 现价 | P&L% | 止损 |",
            "|--------|------|------|------|-------|-------|------|------|------|------|",
        ]
        for s in sorted(report.position_weights, key=lambda x: -x["weight_pct"]):
            avg = s.get("avg_cost") or 0
            cur = s.get("current_price") or 0
            pnl_pct = (cur - avg) / avg * 100 if avg > 0 else float("nan")
            stop = s.get("stop_pct")
            is_cn = s.get("is_cn", False)
            mkt = "A股" if is_cn else "US"
            price_fmt = f"¥{cur:.2f}" if is_cn else f"${cur:.2f}"
            avg_fmt = f"¥{avg:.2f}" if is_cn else f"${avg:.2f}"
            pnl_str = f"{pnl_pct:+.1f}%" if avg > 0 else "—"
            lines.append(
                f"| {s['ticker']} | {mkt} | {s.get('sector', '')} | {s.get('confidence', '?')} "
                f"| {s['weight_pct']:.1f}% | {s['max_weight']:.0f}% "
                f"| {avg_fmt if avg > 0 else '—'} | {price_fmt if cur > 0 else '—'} "
                f"| {pnl_str} | {f'{stop:.0f}%' if stop else '—'} |"
            )
        lines.append("")

    if report.sector_weights:
        lines += [
            "## 板块分布",
            "",
            "| 板块 | 合计权重% | 状态 |",
            "|------|-----------|------|",
        ]
        for sec, w in sorted(report.sector_weights.items(), key=lambda x: -x[1]):
            status = "超限" if w > 30 else ("偏高" if w > 25 else "正常")
            lines.append(f"| {sec} | {w:.1f}% | {status} |")
        lines.append("")

    if report.alerts:
        lines += [
            "## 风控告警",
            "",
            "| 级别 | 标的 | 规则 | 详情 |",
            "|------|------|------|------|",
        ]
        for a in sorted(report.alerts, key=lambda x: {"critical": 0, "warning": 1, "info": 2}[x.level]):
            lines.append(f"| {a.level.upper()} | {a.ticker} | {a.rule} | {a.detail} |")
        lines.append("")
    else:
        lines += ["## 风控告警", "", "所有检查通过，无告警。", ""]

    filename.write_text("\n".join(lines), encoding="utf-8")
    return filename


# ──────────────────────────────────────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Claude模拟盘风控监控")
    parser.add_argument("--no-save", action="store_true", help="不保存markdown报告")
    parser.add_argument("--no-fetch", action="store_true", help="不获取实时价格（使用组合文件中的last_price）")
    args = parser.parse_args()

    try:
        report = run_risk_check(fetch_live=not args.no_fetch)
    except Exception as e:
        console.print(f"[bold red]风控检查失败: {e}[/bold red]")
        raise

    print_report(report)

    if not args.no_save:
        try:
            saved_path = save_markdown_report(report)
            console.print(f"[dim]报告已保存: {saved_path}[/dim]")
        except Exception as e:
            console.print(f"[yellow]报告保存失败: {e}[/yellow]")

    if report.has_critical:
        console.print(
            Panel(
                f"[bold red]共 {len(report.criticals)} 条 CRITICAL 告警 — 需立即处理！[/bold red]\n" +
                "\n".join(f"  • [{a.ticker}] {a.rule}: {a.detail}" for a in report.criticals),
                title="[bold red]CRITICAL ALERTS[/bold red]",
                border_style="red",
                box=box.DOUBLE_EDGE,
            )
        )
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
