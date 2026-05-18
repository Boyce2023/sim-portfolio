# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "rich>=13.0"]
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
REPORTS_DIR = PROJECT_ROOT / "daily-reviews"

console = Console()

# 风控阈值
MAX_SINGLE_PCT = 15.0       # 单只仓位上限 %
MAX_SECTOR_PCT = 30.0       # 板块集中度上限 %
MIN_CASH_PCT = 20.0         # 现金下限 %
MAX_PORTFOLIO_DRAWDOWN = -10.0  # 组合回撤触发线 %
STOP_BUFFER_PCT = 5.0       # 接近止损线警戒区 %
MAX_POSITIONS = 15          # 最大持仓数量

# OTC ticker mapping
YF_TICKER_MAP = {"SPUT": "SRUUF"}

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
    position_summaries: list[dict] = field(default_factory=list)
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


# ──────────────────────────────────────────────────────────────────────────────
# 实时价格获取
# ──────────────────────────────────────────────────────────────────────────────
def _cn_suffix(ticker: str) -> str:
    return ticker + ".SS" if ticker.startswith("6") else ticker + ".SZ"


def _us_yf(ticker: str) -> str:
    return YF_TICKER_MAP.get(ticker.upper(), ticker.upper())


def _fetch_price(yf_ticker: str, retries: int = 3) -> Optional[float]:
    """Fetch price with retry. Returns None on failure."""
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


def fetch_current_prices(
    positions_us: list[dict],
    positions_cn: list[dict],
) -> dict[str, Optional[float]]:
    """Returns {original_ticker: price_or_None}."""
    prices: dict[str, Optional[float]] = {}

    for pos in positions_us:
        if pos.get("instrument_type") == "call_option":
            continue
        ticker = pos["ticker"]
        prices[ticker] = _fetch_price(_us_yf(ticker))

    for pos in positions_cn:
        ticker = pos["ticker"]
        prices[ticker] = _fetch_price(_cn_suffix(ticker))

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
    invested = sum(
        _effective_price(p, live) * p.get("shares", 0)
        for p in positions
        if p.get("instrument_type") != "call_option"
    )
    return cash + invested


# ─── Rule checkers ────────────────────────────────────────────────────────────

def _check_cash(cash: float, total: float, label: str, alerts: list[Alert]) -> float:
    if total <= 0:
        return 0.0
    pct = cash / total * 100
    if pct < MIN_CASH_PCT:
        alerts.append(Alert(
            level="warning", ticker=label, rule="现金不足",
            detail=f"现金比例 {pct:.1f}%，最低 {MIN_CASH_PCT:.0f}%",
            value=pct, threshold=MIN_CASH_PCT,
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

    # Weight check
    if weight_pct > MAX_SINGLE_PCT:
        alerts.append(Alert(
            level="warning", ticker=ticker, rule="单仓超限",
            detail=f"持仓占比 {weight_pct:.1f}%，上限 {MAX_SINGLE_PCT:.0f}%",
            value=weight_pct, threshold=MAX_SINGLE_PCT,
        ))

    # Stop-loss checks using portfolio data directly
    avg_cost = float(pos.get("avg_cost", 0))
    stop_loss = pos.get("stop_loss") or pos.get("stop")
    target = pos.get("target_1") or pos.get("target")

    if avg_cost > 0 and price > 0:
        pnl_pct = (price - avg_cost) / avg_cost * 100

        if stop_loss and stop_loss > 0:
            # Check if stop already triggered
            if price <= stop_loss:
                alerts.append(Alert(
                    level="critical", ticker=ticker, rule="止损触发",
                    detail=f"现价 {price:.2f} ≤ 止损 {stop_loss:.2f}，立即执行止损！",
                    value=price, threshold=stop_loss,
                ))
            else:
                # Check proximity: how close to stop (as % from current)
                dist_to_stop_pct = (price - stop_loss) / price * 100
                if dist_to_stop_pct < STOP_BUFFER_PCT:
                    alerts.append(Alert(
                        level="warning", ticker=ticker, rule="接近止损",
                        detail=f"现价 {price:.2f}，止损 {stop_loss:.2f}，距止损 {dist_to_stop_pct:.1f}%",
                        value=price, threshold=stop_loss,
                    ))

        if target and target > 0 and price >= target:
            alerts.append(Alert(
                level="info", ticker=ticker, rule="目标价到达",
                detail=f"现价 {price:.2f} ≥ 目标 {target:.2f}，考虑分批出场",
                value=price, threshold=target,
            ))

    currency = "¥" if is_cn else "$"
    return {
        "ticker": ticker,
        "name": pos.get("name", ticker),
        "sector": pos.get("sector", "未分类"),
        "is_cn": is_cn,
        "shares": shares,
        "avg_cost": avg_cost,
        "current_price": price,
        "market_value": round(market_value, 2),
        "weight_pct": round(weight_pct, 2),
        "pnl_pct": round((price - avg_cost) / avg_cost * 100, 2) if avg_cost > 0 else None,
        "stop_loss": stop_loss,
        "target": target,
        "currency": currency,
    }


def _check_sectors(sector_weights: dict[str, float], alerts: list[Alert]) -> None:
    for sector, w in sector_weights.items():
        if w > MAX_SECTOR_PCT:
            alerts.append(Alert(
                level="warning", ticker="PORTFOLIO", rule="板块超限",
                detail=f"板块「{sector}」占比 {w:.1f}%，上限 {MAX_SECTOR_PCT:.0f}%",
                value=w, threshold=MAX_SECTOR_PCT,
            ))


# ──────────────────────────────────────────────────────────────────────────────
# 主执行逻辑
# ──────────────────────────────────────────────────────────────────────────────
def run_risk_check(fetch_live: bool = True) -> RiskReport:
    portfolio = load_portfolio()
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
    report.us_cash_pct = _check_cash(us_cash, us_total, "US账户", alerts)
    report.cn_cash_pct = _check_cash(cn_cash, cn_total, "A股账户", alerts)

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

    # Sector limits
    _check_sectors(sector_weights, alerts)

    # Total position count
    total_pos = len(positions_us) + len(positions_cn)
    if total_pos > MAX_POSITIONS:
        alerts.append(Alert(
            level="warning", ticker="PORTFOLIO", rule="持仓数量超限",
            detail=f"持仓 {total_pos} 只，上限 {MAX_POSITIONS} 只",
            value=float(total_pos), threshold=float(MAX_POSITIONS),
        ))

    return report


# ──────────────────────────────────────────────────────────────────────────────
# Rich 终端输出
# ──────────────────────────────────────────────────────────────────────────────
def _level_icon(level: AlertLevel) -> str:
    return {
        "critical": "[bold red]CRITICAL[/bold red]",
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
        return "red bold" if pct < MIN_CASH_PCT else ("yellow" if pct < MIN_CASH_PCT + 5 else "green")

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

            weight_style = "red bold" if s["weight_pct"] > MAX_SINGLE_PCT else "default"
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
            status = "[red]超限[/red]" if w > MAX_SECTOR_PCT else (
                "[yellow]偏高[/yellow]" if w > MAX_SECTOR_PCT * 0.85 else "[green]正常[/green]")
            sec_table.add_row(sec, f"{w:.1f}%", status)
        console.print(sec_table)

    # 告警列表
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
            alert_table.add_row(_level_icon(a.level), a.ticker, a.rule, a.detail)
        console.print(alert_table)

    console.print()


# ──────────────────────────────────────────────────────────────────────────────
# Markdown 报告
# ──────────────────────────────────────────────────────────────────────────────
def save_markdown_report(report: RiskReport) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = REPORTS_DIR / f"risk-{date_str}.md"

    status = "CRITICAL" if report.has_critical else ("WARNING" if report.warnings else "CLEAR")
    lines = [
        f"# 风控报告 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**状态**: {status}  **告警**: {len(report.criticals)} CRITICAL / {len(report.warnings)} WARNING",
        "",
        "## 账户概览",
        "",
        "| 账户 | 总资产 | 现金 | 现金% | 回撤 |",
        "|------|--------|------|-------|------|",
        f"| US | ${report.us_total_assets:,.0f} | ${report.us_cash:,.0f} | {report.us_cash_pct:.1f}% | {report.us_drawdown_pct:+.2f}% |",
        f"| A股 | ¥{report.cn_total_assets:,.0f} | ¥{report.cn_cash:,.0f} | {report.cn_cash_pct:.1f}% | {report.cn_drawdown_pct:+.2f}% |",
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
def main() -> None:
    parser = argparse.ArgumentParser(description="Claude模拟盘风控监控")
    parser.add_argument("--no-save", action="store_true", help="不保存markdown报告")
    parser.add_argument("--no-fetch", action="store_true", help="不获取实时价格（使用portfolio中的当前价格）")
    args = parser.parse_args()

    try:
        report = run_risk_check(fetch_live=not args.no_fetch)
    except Exception as e:
        console.print(f"[bold red]风控检查失败: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    print_report(report)

    if not args.no_save:
        try:
            saved = save_markdown_report(report)
            console.print(f"[dim]报告已保存: {saved}[/dim]")
        except Exception as e:
            console.print(f"[yellow]报告保存失败: {e}[/yellow]")

    if report.has_critical:
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
