# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "rich>=13.0"]
# ///
"""
绩效分析脚本 — Claude模拟盘
读取 portfolio_state.json 的 daily_snapshots，计算全套绩效指标并输出。

用法:
  python scripts/performance.py                # 从项目根目录运行
  python scripts/performance.py --state path/to/portfolio_state.json
  python scripts/performance.py --no-benchmark # 跳过基准对比(无网络时)
"""

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── 常量 ──────────────────────────────────────────────────────────────────────
RISK_FREE_RATE_ANNUAL = 0.03          # 无风险利率（年化）
MIN_DAYS_FOR_ADVANCED = 5             # 高级指标所需最少天数
CNY_USD_FALLBACK = 7.25               # 离线汇率回退值（CNY per USD）

GRADE_THRESHOLDS = {                  # R/R ratio → 交易评级
    "A": 2.0,   # R/R ≥ 2 → A
    "B": 1.0,   # R/R ≥ 1 → B
    "C": 0.0,   # R/R ≥ 0 → C（保本）
    # 其余 → D
}

console = Console()


# ── 数据加载 ──────────────────────────────────────────────────────────────────

def load_state(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── 基准数据获取 ───────────────────────────────────────────────────────────────

def fetch_benchmark(ticker: str, start: str, end: str) -> Optional[list[float]]:
    """返回基准的每日收益率序列（与 snapshots 长度对齐），失败返回 None。"""
    try:
        df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if df.empty:
            return None
        closes = df["Close"].dropna().tolist()
        # 日收益率：(t / t-1) - 1
        if len(closes) < 2:
            return None
        returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes))]
        return returns
    except Exception:
        return None


# ── 核心计算函数 ───────────────────────────────────────────────────────────────

def pct(v: float) -> str:
    """格式化百分比，带颜色。"""
    s = f"{v:+.2f}%"
    return s


def daily_returns(nav_series: list[float]) -> list[float]:
    """从净值序列计算每日收益率序列（长度 = len-1）。"""
    return [(nav_series[i] / nav_series[i - 1]) - 1 for i in range(1, len(nav_series))]


def cumulative_return(nav_series: list[float]) -> float:
    """累计收益率（从第一个值到最后一个值）。"""
    if len(nav_series) < 2 or nav_series[0] == 0:
        return 0.0
    return (nav_series[-1] / nav_series[0]) - 1


def max_drawdown(nav_series: list[float]) -> float:
    """最大回撤（负值）。"""
    peak = nav_series[0]
    mdd = 0.0
    for v in nav_series:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < mdd:
            mdd = dd
    return mdd


def sharpe_ratio(daily_ret: list[float], rf_annual: float = RISK_FREE_RATE_ANNUAL) -> float:
    """年化 Sharpe Ratio。"""
    if len(daily_ret) < 2:
        return float("nan")
    n = len(daily_ret)
    mean = sum(daily_ret) / n
    variance = sum((r - mean) ** 2 for r in daily_ret) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return float("nan")
    rf_daily = (1 + rf_annual) ** (1 / 252) - 1
    return (mean - rf_daily) / std * math.sqrt(252)


def win_rate(daily_ret: list[float]) -> tuple[float, int, int]:
    """(胜率, 盈利天数, 总天数)。"""
    wins = sum(1 for r in daily_ret if r > 0)
    total = len(daily_ret)
    rate = wins / total if total > 0 else 0.0
    return rate, wins, total


def excess_return(portfolio_ret: list[float], benchmark_ret: list[float]) -> float:
    """累计超额收益（基于日收益率序列）。"""
    # 对齐长度
    n = min(len(portfolio_ret), len(benchmark_ret))
    if n == 0:
        return 0.0
    port_cum = math.prod(1 + r for r in portfolio_ret[:n]) - 1
    bench_cum = math.prod(1 + r for r in benchmark_ret[:n]) - 1
    return port_cum - bench_cum


# ── 新增：Alpha分解 ────────────────────────────────────────────────────────────

def fetch_benchmark_total_return(ticker: str, start: str, end: str) -> Optional[float]:
    """返回基准区间累计收益率（%），失败返回 None。"""
    try:
        df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if df.empty or len(df) < 2:
            return None
        closes = df["Close"].dropna()
        if len(closes) < 2:
            return None
        # Handle MultiIndex columns from yfinance
        if hasattr(closes, 'columns'):
            closes = closes.iloc[:, 0]
        first = float(closes.iloc[0])
        last = float(closes.iloc[-1])
        if first == 0:
            return None
        return (last / first - 1) * 100
    except Exception:
        return None


def compute_current_drawdown(nav_series: list[float]) -> float:
    """当前回撤（从历史最高点到最新值，负值）。"""
    if not nav_series:
        return 0.0
    peak = max(nav_series)
    current = nav_series[-1]
    if peak == 0:
        return 0.0
    return (current - peak) / peak


def build_alpha_decomposition(
    snapshots: list[dict],
    a_navs: list[float],
    us_navs: list[float],
    fetch_bench: bool,
) -> Optional[Table]:
    """Alpha分解表：组合收益 vs 基准收益 vs Alpha。"""
    if len(snapshots) < 2:
        return None

    start_date = snapshots[0].get("date", "")[:10]
    end_date = snapshots[-1].get("date", "")[:10]
    try:
        end_dt = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        end_dt = end_date

    table = Table(
        title="🎯 Alpha分解",
        box=box.ROUNDED,
        header_style="bold cyan",
        min_width=70,
    )
    table.add_column("账户", style="bold", width=14)
    table.add_column("基准", width=18)
    table.add_column("组合收益", justify="right", width=14)
    table.add_column("基准收益", justify="right", width=14)
    table.add_column("Alpha", justify="right", width=14)

    rows = [
        ("A股", "沪深300 (000300.SS)", a_navs, "000300.SS"),
        ("美股", "SPY (标普500)", us_navs, "SPY"),
    ]

    added = False
    for label, bench_name, navs, bench_ticker in rows:
        if len(navs) < 2:
            continue
        port_ret = cumulative_return(navs) * 100

        if fetch_bench:
            bench_ret = fetch_benchmark_total_return(bench_ticker, start_date, end_dt)
        else:
            bench_ret = None

        if bench_ret is not None:
            alpha = port_ret - bench_ret
            table.add_row(
                label,
                bench_name,
                color_pct(port_ret),
                color_pct(bench_ret),
                color_pct(alpha),
            )
        else:
            table.add_row(
                label,
                bench_name,
                color_pct(port_ret),
                Text("获取失败" if fetch_bench else "已跳过", style="dim"),
                Text("N/A", style="dim"),
            )
        added = True

    if not added:
        return None
    return table


# ── 新增：逐仓位归因 ──────────────────────────────────────────────────────────

def compute_position_attribution(state: dict) -> list[dict]:
    """
    按当前持仓计算贡献度：
    contribution = unrealized_pnl_pct × portfolio_pct
    返回按贡献排序的列表（最大正贡献在前）。
    """
    results = []

    for acct_key, acct_data in state.get("accounts", {}).items():
        currency = acct_data.get("currency", "USD")
        total_assets = acct_data.get("total_assets", 0) or 1

        for pos in acct_data.get("positions", []):
            ticker = pos.get("ticker", "?")
            name = pos.get("name", ticker)
            market_value = pos.get("market_value", 0) or 0
            unrealized_pnl = pos.get("unrealized_pnl", 0) or 0
            unrealized_pnl_pct = pos.get("unrealized_pnl_pct", 0) or 0
            portfolio_pct = pos.get("portfolio_pct") or (market_value / total_assets if total_assets else 0)

            # contribution = weight × return (%)
            contribution = portfolio_pct * unrealized_pnl_pct

            results.append({
                "ticker": ticker,
                "name": name,
                "account": "A股" if acct_key == "a_share" else "美股",
                "currency": currency,
                "portfolio_pct": portfolio_pct,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": unrealized_pnl_pct,
                "contribution": contribution,
            })

    results.sort(key=lambda x: x["contribution"], reverse=True)
    return results


def build_position_attribution_table(state: dict) -> Optional[Table]:
    """逐仓位归因表，按贡献排序。"""
    positions = compute_position_attribution(state)
    if not positions:
        return None

    table = Table(
        title=f"📐 逐仓位收益归因（共 {len(positions)} 个持仓）",
        box=box.ROUNDED,
        header_style="bold cyan",
        min_width=80,
    )
    table.add_column("排名", justify="center", width=6)
    table.add_column("代码", width=10)
    table.add_column("名称", width=14)
    table.add_column("账户", width=6)
    table.add_column("仓位占比", justify="right", width=10)
    table.add_column("持仓收益率", justify="right", width=12)
    table.add_column("未实现盈亏", justify="right", width=14)
    table.add_column("贡献度", justify="right", width=10)

    for i, pos in enumerate(positions, 1):
        sym = "¥" if pos["currency"] == "CNY" else "$"
        pnl = pos["unrealized_pnl"]
        pnl_display = Text(f"{sym}{pnl:+,.0f}", style="bold green" if pnl >= 0 else "bold red")

        rank_style = "bold green" if i <= 3 else ("bold red" if i > len(positions) - 3 else "")
        table.add_row(
            Text(str(i), style=rank_style),
            pos["ticker"],
            pos["name"],
            pos["account"],
            f"{pos['portfolio_pct']:.1%}",
            color_pct(pos["unrealized_pnl_pct"]),
            pnl_display,
            color_pct(pos["contribution"]),
        )

    return table


# ── 新增：交易级指标 ──────────────────────────────────────────────────────────

def compute_trade_metrics(trade_log: list[dict]) -> dict:
    """
    从 trade_log 计算：
    - 胜率（已平仓交易中有正realized_pnl的比例）
    - 平均盈利 vs 平均亏损（profit factor）
    - 平均持仓期（已平仓，按ticker配对买入/卖出）
    """
    # 筛选有 realized_pnl 的卖出/平仓记录
    closed_trades = [
        t for t in trade_log
        if t.get("action") in ("sell", "cover", "close")
        and t.get("realized_pnl") is not None
    ]

    wins = [t for t in closed_trades if (t.get("realized_pnl") or 0) > 0]
    losses = [t for t in closed_trades if (t.get("realized_pnl") or 0) < 0]
    breakeven = [t for t in closed_trades if (t.get("realized_pnl") or 0) == 0]

    total_closed = len(closed_trades)
    win_count = len(wins)
    loss_count = len(losses)

    win_rate_val = win_count / total_closed if total_closed > 0 else 0.0

    avg_win = sum(t.get("realized_pnl", 0) for t in wins) / win_count if wins else 0.0
    avg_loss = sum(abs(t.get("realized_pnl", 0)) for t in losses) / loss_count if losses else 0.0
    profit_factor = (avg_win * win_count) / (avg_loss * loss_count) if (avg_loss * loss_count) > 0 else float("nan")

    # 平均持仓期：配对买/卖（按ticker+account）
    holding_periods = []
    by_ticker: dict[str, list[dict]] = {}
    for t in trade_log:
        key = f"{t.get('account', '')}:{t.get('ticker', '')}"
        by_ticker.setdefault(key, []).append(t)

    for key, trades in by_ticker.items():
        buys = sorted([t for t in trades if t.get("action") == "buy"],
                      key=lambda x: x.get("timestamp", x.get("date", "")))
        sells = sorted([t for t in trades if t.get("action") in ("sell", "cover")],
                       key=lambda x: x.get("timestamp", x.get("date", "")))
        for sell in sells:
            sell_dt_str = sell.get("timestamp", sell.get("date", ""))[:10]
            # Find the most recent buy before this sell
            prior_buys = [b for b in buys if b.get("timestamp", b.get("date", ""))[:10] <= sell_dt_str]
            if not prior_buys:
                continue
            buy_dt_str = prior_buys[-1].get("timestamp", prior_buys[-1].get("date", ""))[:10]
            try:
                buy_dt = datetime.strptime(buy_dt_str, "%Y-%m-%d")
                sell_dt = datetime.strptime(sell_dt_str, "%Y-%m-%d")
                holding_periods.append((sell_dt - buy_dt).days)
            except ValueError:
                pass

    avg_holding_days = sum(holding_periods) / len(holding_periods) if holding_periods else None

    return {
        "total_closed": total_closed,
        "win_count": win_count,
        "loss_count": loss_count,
        "breakeven_count": len(breakeven),
        "win_rate": win_rate_val,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "avg_holding_days": avg_holding_days,
    }


def build_trade_metrics_panel(metrics: dict) -> str:
    """交易级指标的富文本摘要。"""
    if metrics["total_closed"] == 0:
        return "[dim]暂无已平仓记录（买入交易尚未对应卖出）[/dim]"

    lines = []
    wr = metrics["win_rate"]
    wr_style = "bold green" if wr >= 0.5 else "bold red"
    lines.append(
        f"已平仓: {metrics['total_closed']} 笔  |  "
        f"盈利: [{wr_style}]{metrics['win_count']}[/{wr_style}]  "
        f"亏损: [bold red]{metrics['loss_count']}[/bold red]  "
        f"平局: {metrics['breakeven_count']}"
    )

    lines.append(
        f"胜率: [{wr_style}]{wr:.1%}[/{wr_style}]  |  "
        f"平均盈利: [green]{metrics['avg_win']:+,.1f}[/green]  |  "
        f"平均亏损: [red]{metrics['avg_loss']:,.1f}[/red]"
    )

    pf = metrics["profit_factor"]
    if math.isnan(pf):
        pf_str = "N/A（无亏损记录）"
        pf_style = "dim"
    else:
        pf_str = f"{pf:.2f}"
        pf_style = "bold green" if pf >= 1.5 else ("yellow" if pf >= 1.0 else "bold red")
    lines.append(f"Profit Factor: [{pf_style}]{pf_str}[/{pf_style}]  (盈亏总额之比，>1.5=优秀)")

    if metrics["avg_holding_days"] is not None:
        lines.append(f"平均持仓期: {metrics['avg_holding_days']:.1f} 天")
    else:
        lines.append("平均持仓期: N/A（数据不足）")

    return "\n".join(lines)


# ── 新增：风险指标增强 ────────────────────────────────────────────────────────

def build_risk_metrics_table(
    snapshots: list[dict],
    a_navs: list[float],
    us_navs: list[float],
    combined_navs: list[float],
) -> Optional[Table]:
    """增强风险指标表：最大回撤、当前回撤、Sharpe。"""
    if len(snapshots) < MIN_DAYS_FOR_ADVANCED:
        return None

    table = Table(
        title="⚠️  风险指标增强",
        box=box.ROUNDED,
        header_style="bold cyan",
        min_width=70,
    )
    table.add_column("指标", style="bold", width=22)
    table.add_column("A股 (CNY)", justify="right", width=16)
    table.add_column("美股 (USD→CNY)", justify="right", width=16)
    table.add_column("合并", justify="right", width=16)

    # 最大回撤
    a_mdd = max_drawdown(a_navs) * 100 if a_navs else 0
    us_mdd = max_drawdown(us_navs) * 100 if us_navs else 0
    cb_mdd = max_drawdown(combined_navs) * 100 if combined_navs else 0
    table.add_row(
        "最大回撤 (MDD)",
        color_pct(a_mdd),
        color_pct(us_mdd),
        color_pct(cb_mdd),
    )

    # 当前回撤（从历史最高点）
    a_cdd = compute_current_drawdown(a_navs) * 100 if a_navs else 0
    us_cdd = compute_current_drawdown(us_navs) * 100 if us_navs else 0
    cb_cdd = compute_current_drawdown(combined_navs) * 100 if combined_navs else 0
    table.add_row(
        "当前回撤",
        color_pct(a_cdd),
        color_pct(us_cdd),
        color_pct(cb_cdd),
    )

    # Sharpe Ratio
    a_dr = daily_returns(a_navs) if len(a_navs) >= 2 else []
    us_dr = daily_returns(us_navs) if len(us_navs) >= 2 else []
    cb_dr = daily_returns(combined_navs) if len(combined_navs) >= 2 else []

    def fmt_sharpe(v) -> Text:
        if math.isnan(v):
            return Text("N/A", style="dim")
        style = "bold green" if v > 1 else ("yellow" if v > 0 else "bold red")
        return Text(f"{v:.2f}", style=style)

    note = "" if len(a_dr) >= 20 else f"  [dim](仅{len(a_dr)}天，仅供参考)[/dim]"
    table.add_row(
        f"Sharpe (年化){note}",
        fmt_sharpe(sharpe_ratio(a_dr)),
        fmt_sharpe(sharpe_ratio(us_dr)),
        fmt_sharpe(sharpe_ratio(cb_dr)),
    )

    return table


# ── 新增：账户对比表 ──────────────────────────────────────────────────────────

def build_account_comparison_table(
    snapshots: list[dict],
    a_navs: list[float],
    us_navs: list[float],
    state: dict,
    trade_metrics_a: dict,
    trade_metrics_us: dict,
    a_bench_ret: Optional[float],
    us_bench_ret: Optional[float],
) -> Table:
    """A股 vs 美股并排对比表。"""
    table = Table(
        title="🆚 账户并排对比",
        box=box.ROUNDED,
        header_style="bold cyan",
        min_width=55,
    )
    table.add_column("指标", style="bold", width=22)
    table.add_column("A股", justify="right", width=14)
    table.add_column("美股", justify="right", width=14)

    # 收益率
    a_ret = cumulative_return(a_navs) * 100 if len(a_navs) >= 2 else None
    us_ret = cumulative_return(us_navs) * 100 if len(us_navs) >= 2 else None
    table.add_row(
        "累计收益率",
        color_pct(a_ret) if a_ret is not None else Text("N/A"),
        color_pct(us_ret) if us_ret is not None else Text("N/A"),
    )

    # Alpha
    if a_ret is not None and a_bench_ret is not None:
        a_alpha = a_ret - a_bench_ret
        a_alpha_text = color_pct(a_alpha)
    else:
        a_alpha_text = Text("N/A", style="dim")
    if us_ret is not None and us_bench_ret is not None:
        us_alpha = us_ret - us_bench_ret
        us_alpha_text = color_pct(us_alpha)
    else:
        us_alpha_text = Text("N/A", style="dim")
    table.add_row("Alpha (vs 基准)", a_alpha_text, us_alpha_text)

    # 持仓数量
    a_positions = len(state.get("accounts", {}).get("a_share", {}).get("positions", []))
    us_positions = len(state.get("accounts", {}).get("us", {}).get("positions", []))
    table.add_row("持仓数量", Text(str(a_positions)), Text(str(us_positions)))

    # 交易胜率（已平仓）
    a_wr = trade_metrics_a.get("win_rate")
    us_wr = trade_metrics_us.get("win_rate")
    a_wr_text = Text(f"{a_wr:.1%}  ({trade_metrics_a['win_count']}/{trade_metrics_a['total_closed']})",
                     style="bold green" if (a_wr or 0) >= 0.5 else "bold red") if trade_metrics_a["total_closed"] > 0 else Text("N/A", style="dim")
    us_wr_text = Text(f"{us_wr:.1%}  ({trade_metrics_us['win_count']}/{trade_metrics_us['total_closed']})",
                      style="bold green" if (us_wr or 0) >= 0.5 else "bold red") if trade_metrics_us["total_closed"] > 0 else Text("N/A", style="dim")
    table.add_row("交易胜率（已平仓）", a_wr_text, us_wr_text)

    # 最大回撤
    a_mdd = max_drawdown(a_navs) * 100 if a_navs else 0
    us_mdd = max_drawdown(us_navs) * 100 if us_navs else 0
    table.add_row("最大回撤 (MDD)", color_pct(a_mdd), color_pct(us_mdd))

    # Profit Factor
    a_pf = trade_metrics_a.get("profit_factor", float("nan"))
    us_pf = trade_metrics_us.get("profit_factor", float("nan"))

    def fmt_pf(v) -> Text:
        if math.isnan(v):
            return Text("N/A", style="dim")
        style = "bold green" if v >= 1.5 else ("yellow" if v >= 1.0 else "bold red")
        return Text(f"{v:.2f}", style=style)

    table.add_row("Profit Factor", fmt_pf(a_pf), fmt_pf(us_pf))

    return table


def sector_attribution(snapshots: list[dict]) -> dict[str, dict]:
    """
    按板块计算周/月贡献。
    snapshots 中若有 positions_breakdown 字段（含 sector/market_value），则使用。
    否则退化为按账户（a_share / us）聚合。
    """
    monthly: dict[str, dict[str, float]] = {}

    for snap in snapshots:
        dt = snap.get("date", "")[:7]  # YYYY-MM
        month = monthly.setdefault(dt, {})

        # 尝试细粒度板块
        if "positions_breakdown" in snap:
            for pos in snap["positions_breakdown"]:
                sector = pos.get("sector", "未分类")
                pnl = pos.get("daily_pnl", 0)
                month[sector] = month.get(sector, 0) + pnl
        else:
            # 回退：按账户聚合
            month["A股"] = month.get("A股", 0) + snap.get("a_share_daily_pnl", 0)
            month["美股"] = month.get("美股", 0) + snap.get("us_daily_pnl", 0)

    return monthly


# ── 交易分析 ───────────────────────────────────────────────────────────────────

def grade_trade(rr_ratio: Optional[float]) -> str:
    """根据 R/R ratio 给交易评级。"""
    if rr_ratio is None:
        return "N/A"
    if rr_ratio >= GRADE_THRESHOLDS["A"]:
        return "A"
    if rr_ratio >= GRADE_THRESHOLDS["B"]:
        return "B"
    if rr_ratio >= GRADE_THRESHOLDS["C"]:
        return "C"
    return "D"


def compute_rr(trade: dict) -> Optional[float]:
    """
    计算单笔交易的 R/R ratio。
    支持两种模式：
      1. trade 含 stop_loss_price + target_price + entry_price（计划 R/R）
      2. 否则用实际 realized_pnl / risk_amount（若存在）
    """
    entry = trade.get("avg_entry_price") or trade.get("entry_price")
    target = trade.get("target_price")
    stop = trade.get("stop_loss_price")

    if entry and target and stop and entry != stop:
        reward = abs(target - entry)
        risk = abs(entry - stop)
        return reward / risk if risk > 0 else None

    # 回退：实际盈亏 / 风险额
    pnl = trade.get("realized_pnl", 0) or 0
    risk_amount = trade.get("risk_amount")
    if risk_amount and risk_amount > 0:
        return pnl / risk_amount

    return None


def trade_analysis(trade_log: list[dict]) -> dict:
    """
    分析 trade_log：
    - 每笔交易盈亏
    - A/B/C/D 评级
    - 最赚钱 / 最亏钱
    """
    results = []

    for trade in trade_log:
        ticker = trade.get("ticker", "?")
        action = trade.get("action", "")
        market = trade.get("market", "us")
        realized_pnl = trade.get("realized_pnl", 0) or 0
        currency = "CNY" if market == "a_share" else "USD"
        rr = compute_rr(trade)
        grade = grade_trade(rr)

        results.append({
            "ticker": ticker,
            "action": action,
            "date": trade.get("date", trade.get("timestamp", ""))[:10],
            "realized_pnl": realized_pnl,
            "currency": currency,
            "rr_ratio": rr,
            "grade": grade,
            "market": market,
        })

    if not results:
        return {"trades": [], "best": None, "worst": None, "grade_dist": {}}

    # 按盈亏排序（CNY/USD 混合，粗略统一到 USD 比较）
    def normalize_pnl(t):
        pnl = t["realized_pnl"]
        return pnl / CNY_USD_FALLBACK if t["currency"] == "CNY" else pnl

    sorted_results = sorted(results, key=normalize_pnl, reverse=True)
    best = sorted_results[0] if sorted_results else None
    worst = sorted_results[-1] if sorted_results else None

    # 评级分布
    grade_dist: dict[str, int] = {}
    for t in results:
        g = t["grade"]
        grade_dist[g] = grade_dist.get(g, 0) + 1

    return {
        "trades": results,
        "best": best,
        "worst": worst,
        "grade_dist": grade_dist,
    }


# ── 快照解析 ───────────────────────────────────────────────────────────────────

def parse_snapshots(snapshots: list[dict]) -> tuple[list[float], list[float], list[float]]:
    """
    从 snapshots 提取三条净值序列：A股、美股（CNY折算）、合并。
    返回 (a_nav_series, us_nav_series_cny, combined_nav_series)

    Supports multiple field naming conventions written by trading_engine.py:
    - a_share_nav  (trading_engine.py v2)
    - a_share_total_assets, a_total_assets  (older)
    """
    if not snapshots:
        return [], [], []

    a_navs, us_navs, combined_navs = [], [], []

    for snap in snapshots:
        # A-share NAV: try multiple field names
        a_total = (
            snap.get("a_share_nav")
            or snap.get("a_share_total_assets")
            or snap.get("a_total_assets")
            or 0
        )
        # US NAV: try multiple field names
        us_total = (
            snap.get("us_nav")
            or snap.get("us_total_assets")
            or 0
        )
        exchange_rate = snap.get("cny_usd_rate", CNY_USD_FALLBACK) or CNY_USD_FALLBACK
        us_in_cny = float(us_total) * exchange_rate

        a_navs.append(float(a_total))
        us_navs.append(float(us_in_cny))
        combined_navs.append(float(a_total) + us_in_cny)

    return a_navs, us_navs, combined_navs


# ── Rich 输出 ──────────────────────────────────────────────────────────────────

def color_pct(v: float) -> Text:
    s = f"{v:+.2f}%"
    if v > 0:
        return Text(s, style="bold green")
    elif v < 0:
        return Text(s, style="bold red")
    return Text(s, style="white")


def color_val(v: float, fmt: str = ".2f") -> Text:
    s = format(v, fmt)
    if v > 0:
        return Text(f"+{s}", style="bold green")
    elif v < 0:
        return Text(s, style="bold red")
    return Text(s, style="white")


def build_overview_table(
    snapshots: list[dict],
    a_navs: list[float],
    us_navs: list[float],
    combined_navs: list[float],
    state: dict,
) -> Table:
    """核心绩效总览表。"""
    table = Table(
        title="📊 绩效总览",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        min_width=60,
    )
    table.add_column("指标", style="bold", width=24)
    table.add_column("A股 (CNY)", justify="right", width=16)
    table.add_column("美股 (USD→CNY)", justify="right", width=16)
    table.add_column("合并", justify="right", width=16)

    # 初始资金
    a_init = state["accounts"]["a_share"]["initial_capital"]
    us_init = state["accounts"]["us"]["initial_capital"]
    ex = CNY_USD_FALLBACK
    us_init_cny = us_init * ex

    def safe_stat(navs, fn, *args):
        try:
            return fn(navs, *args) if len(navs) >= 2 else None
        except Exception:
            return None

    # 累计收益率
    a_cum = safe_stat(a_navs, cumulative_return)
    us_cum = safe_stat(us_navs, cumulative_return)
    cb_cum = safe_stat(combined_navs, cumulative_return)

    table.add_row(
        "累计收益率",
        color_pct(a_cum * 100) if a_cum is not None else Text("N/A"),
        color_pct(us_cum * 100) if us_cum is not None else Text("N/A"),
        color_pct(cb_cum * 100) if cb_cum is not None else Text("N/A"),
    )

    # 绝对盈亏
    a_pnl = (a_navs[-1] - a_navs[0]) if a_navs else 0
    us_pnl = (us_navs[-1] - us_navs[0]) if us_navs else 0
    cb_pnl = (combined_navs[-1] - combined_navs[0]) if combined_navs else 0

    table.add_row(
        "绝对盈亏",
        color_val(a_pnl, ",.0f"),
        color_val(us_pnl, ",.0f"),
        color_val(cb_pnl, ",.0f"),
    )

    n_days = len(snapshots)
    if n_days < MIN_DAYS_FOR_ADVANCED:
        table.add_row(
            Text("高级指标", style="dim"),
            Text(f"数据不足（{n_days}/{MIN_DAYS_FOR_ADVANCED}天）", style="dim"),
            Text("—", style="dim"),
            Text("—", style="dim"),
        )
        return table

    # 以下需要 daily_returns
    a_dr = daily_returns(a_navs) if len(a_navs) >= 2 else []
    us_dr = daily_returns(us_navs) if len(us_navs) >= 2 else []
    cb_dr = daily_returns(combined_navs) if len(combined_navs) >= 2 else []

    # 最大回撤
    a_mdd = max_drawdown(a_navs) if a_navs else 0
    us_mdd = max_drawdown(us_navs) if us_navs else 0
    cb_mdd = max_drawdown(combined_navs) if combined_navs else 0
    table.add_row(
        "最大回撤",
        color_pct(a_mdd * 100),
        color_pct(us_mdd * 100),
        color_pct(cb_mdd * 100),
    )

    # Sharpe Ratio
    a_sr = sharpe_ratio(a_dr)
    us_sr = sharpe_ratio(us_dr)
    cb_sr = sharpe_ratio(cb_dr)

    def fmt_sharpe(v):
        if math.isnan(v):
            return Text("N/A", style="dim")
        style = "bold green" if v > 1 else ("yellow" if v > 0 else "bold red")
        return Text(f"{v:.2f}", style=style)

    table.add_row("Sharpe (年化)", fmt_sharpe(a_sr), fmt_sharpe(us_sr), fmt_sharpe(cb_sr))

    # 胜率
    a_wr, a_wins, a_tot = win_rate(a_dr)
    us_wr, us_wins, us_tot = win_rate(us_dr)
    cb_wr, cb_wins, cb_tot = win_rate(cb_dr)
    table.add_row(
        "胜率（盈利天数）",
        Text(f"{a_wr:.1%}  ({a_wins}/{a_tot}天)"),
        Text(f"{us_wr:.1%}  ({us_wins}/{us_tot}天)"),
        Text(f"{cb_wr:.1%}  ({cb_wins}/{cb_tot}天)"),
    )

    # 最大单日收益 / 亏损
    def minmax_day(dr, navs, snaps):
        if not dr:
            return "—", "—"
        idx_max = max(range(len(dr)), key=lambda i: dr[i])
        idx_min = min(range(len(dr)), key=lambda i: dr[i])
        d_max = snaps[idx_max + 1].get("date", "")[:10] if idx_max + 1 < len(snaps) else ""
        d_min = snaps[idx_min + 1].get("date", "")[:10] if idx_min + 1 < len(snaps) else ""
        best_s = f"{dr[idx_max]:+.2%}  {d_max}"
        worst_s = f"{dr[idx_min]:+.2%}  {d_min}"
        return best_s, worst_s

    a_best, a_worst = minmax_day(a_dr, a_navs, snapshots)
    us_best, us_worst = minmax_day(us_dr, us_navs, snapshots)
    cb_best, cb_worst = minmax_day(cb_dr, combined_navs, snapshots)

    table.add_row(
        "最大单日收益",
        Text(a_best, style="green"),
        Text(us_best, style="green"),
        Text(cb_best, style="green"),
    )
    table.add_row(
        "最大单日亏损",
        Text(a_worst, style="red"),
        Text(us_worst, style="red"),
        Text(cb_worst, style="red"),
    )

    return table


def build_benchmark_table(
    snapshots: list[dict],
    a_navs: list[float],
    us_navs: list[float],
    combined_navs: list[float],
    fetch_bench: bool,
) -> Optional[Table]:
    """基准对比表。"""
    if len(snapshots) < 2:
        return None

    start_date = snapshots[0].get("date", "")[:10]
    end_date = snapshots[-1].get("date", "")[:10]
    # yfinance end 需要 +1 天
    try:
        end_dt = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        end_dt = end_date

    table = Table(
        title="📈 vs 基准",
        box=box.ROUNDED,
        header_style="bold cyan",
        min_width=60,
    )
    table.add_column("维度", style="bold", width=24)
    table.add_column("组合", justify="right", width=16)
    table.add_column("基准", justify="right", width=16)
    table.add_column("超额", justify="right", width=16)

    cb_dr = daily_returns(combined_navs) if len(combined_navs) >= 2 else []
    a_dr = daily_returns(a_navs) if len(a_navs) >= 2 else []
    us_dr = daily_returns(us_navs) if len(us_navs) >= 2 else []

    benchmarks = [
        ("沪深300 (CSI300)", "000300.SS", a_dr, "A股"),
        ("SPY (标普500)", "SPY", us_dr, "美股"),
    ]

    added = False
    for bench_name, bench_ticker, port_dr, label in benchmarks:
        if not fetch_bench or not port_dr:
            continue

        bench_dr = fetch_benchmark(bench_ticker, start_date, end_dt)
        if bench_dr is None:
            table.add_row(bench_name, "—", Text("获取失败", style="dim red"), "—")
            continue

        port_cum = cumulative_return([1] + [math.prod(1 + r for r in port_dr[:i + 1]) for i in range(len(port_dr))])
        bench_cum = cumulative_return([1] + [math.prod(1 + r for r in bench_dr[:i + 1]) for i in range(len(bench_dr))])
        excess = port_cum - bench_cum

        table.add_row(
            f"{label} vs {bench_name}",
            color_pct(port_cum * 100),
            color_pct(bench_cum * 100),
            color_pct(excess * 100),
        )
        added = True

    if not added:
        return None
    return table


def build_monthly_table(snapshots: list[dict]) -> Optional[Table]:
    """月度归因表。"""
    if len(snapshots) < 5:
        return None

    monthly = sector_attribution(snapshots)
    if not monthly:
        return None

    table = Table(
        title="📅 月度归因（按板块 PnL）",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("月份", style="bold", width=10)

    # 收集所有板块
    all_sectors: set[str] = set()
    for m_data in monthly.values():
        all_sectors.update(m_data.keys())
    sectors = sorted(all_sectors)
    for s in sectors:
        table.add_column(s, justify="right", width=14)
    table.add_column("合计", justify="right", width=14)

    for month in sorted(monthly.keys()):
        m_data = monthly[month]
        total = sum(m_data.values())
        row = [month]
        for s in sectors:
            v = m_data.get(s, 0)
            row.append(color_val(v, ",.0f"))
        row.append(color_val(total, ",.0f"))
        table.add_row(*row)

    return table


def build_trade_table(analysis: dict) -> Table:
    """交易分析表。"""
    trades = analysis.get("trades", [])
    table = Table(
        title=f"🔄 交易记录分析（共 {len(trades)} 笔）",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("日期", width=12)
    table.add_column("代码", width=10)
    table.add_column("方向", width=6)
    table.add_column("市场", width=6)
    table.add_column("盈亏", justify="right", width=14)
    table.add_column("R/R", justify="right", width=8)
    table.add_column("评级", justify="center", width=6)

    grade_style = {"A": "bold green", "B": "green", "C": "yellow", "D": "bold red", "N/A": "dim"}

    for t in trades:
        pnl = t["realized_pnl"]
        currency_sym = "¥" if t["currency"] == "CNY" else "$"
        pnl_text = color_val(pnl)
        pnl_text.plain  # force
        pnl_str = f"{currency_sym}{abs(pnl):,.0f}"
        if pnl >= 0:
            pnl_display = Text(f"+{pnl_str}", style="bold green")
        else:
            pnl_display = Text(f"-{pnl_str}", style="bold red")

        rr_str = f"{t['rr_ratio']:.2f}" if t["rr_ratio"] is not None else "—"
        grade = t["grade"]

        table.add_row(
            t["date"],
            t["ticker"],
            t["action"],
            t["market"],
            pnl_display,
            rr_str,
            Text(grade, style=grade_style.get(grade, "")),
        )

    return table


def build_grade_dist_panel(analysis: dict) -> str:
    """评级分布文本。"""
    dist = analysis.get("grade_dist", {})
    if not dist:
        return ""
    parts = []
    for g in ["A", "B", "C", "D", "N/A"]:
        cnt = dist.get(g, 0)
        if cnt:
            parts.append(f"[bold]{g}[/bold]: {cnt}笔")
    best = analysis.get("best")
    worst = analysis.get("worst")
    lines = ["评级分布: " + "  ".join(parts)]
    if best:
        sym = "¥" if best["currency"] == "CNY" else "$"
        lines.append(f"[green]最赚: {best['ticker']} {sym}{best['realized_pnl']:+,.0f} ({best['date']})[/green]")
    if worst:
        sym = "¥" if worst["currency"] == "CNY" else "$"
        lines.append(f"[red]最亏: {worst['ticker']} {sym}{worst['realized_pnl']:+,.0f} ({worst['date']})[/red]")
    return "\n".join(lines)


# ── Markdown 导出 ──────────────────────────────────────────────────────────────

def export_markdown(
    snapshots: list[dict],
    a_navs: list[float],
    us_navs: list[float],
    combined_navs: list[float],
    trade_result: dict,
    state: dict,
    output_path: Path,
) -> None:
    lines = [
        "# 模拟盘绩效报告",
        f"\n> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"> 数据天数: {len(snapshots)} 天  ",
        f"> 模拟盘周期: {state['_meta'].get('start_date', '?')} → {state['_meta'].get('end_date', '?')}\n",
    ]

    def pct_str(v):
        return f"{v:+.2f}%" if v is not None else "N/A"

    def add_section(title, rows):
        lines.append(f"\n## {title}\n")
        lines.append("| 指标 | A股 (CNY) | 美股 (USD→CNY) | 合并 |")
        lines.append("|------|-----------|----------------|------|")
        for row in rows:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")

    # 累计收益率
    a_cum = cumulative_return(a_navs) * 100 if len(a_navs) >= 2 else None
    us_cum = cumulative_return(us_navs) * 100 if len(us_navs) >= 2 else None
    cb_cum = cumulative_return(combined_navs) * 100 if len(combined_navs) >= 2 else None
    a_pnl = (a_navs[-1] - a_navs[0]) if a_navs else 0
    us_pnl = (us_navs[-1] - us_navs[0]) if us_navs else 0
    cb_pnl = (combined_navs[-1] - combined_navs[0]) if combined_navs else 0

    basic_rows = [
        ["累计收益率", pct_str(a_cum), pct_str(us_cum), pct_str(cb_cum)],
        ["绝对盈亏", f"{a_pnl:+,.0f}", f"{us_pnl:+,.0f}", f"{cb_pnl:+,.0f}"],
    ]

    if len(snapshots) >= MIN_DAYS_FOR_ADVANCED:
        a_dr = daily_returns(a_navs)
        us_dr = daily_returns(us_navs)
        cb_dr = daily_returns(combined_navs)

        a_mdd = max_drawdown(a_navs) * 100
        us_mdd = max_drawdown(us_navs) * 100
        cb_mdd = max_drawdown(combined_navs) * 100

        a_sr = sharpe_ratio(a_dr)
        us_sr = sharpe_ratio(us_dr)
        cb_sr = sharpe_ratio(cb_dr)

        a_wr, a_w, a_t = win_rate(a_dr)
        us_wr, us_w, us_t = win_rate(us_dr)
        cb_wr, cb_w, cb_t = win_rate(cb_dr)

        basic_rows += [
            ["最大回撤", pct_str(a_mdd), pct_str(us_mdd), pct_str(cb_mdd)],
            ["Sharpe (年化)", f"{a_sr:.2f}" if not math.isnan(a_sr) else "N/A",
             f"{us_sr:.2f}" if not math.isnan(us_sr) else "N/A",
             f"{cb_sr:.2f}" if not math.isnan(cb_sr) else "N/A"],
            ["胜率", f"{a_wr:.1%} ({a_w}/{a_t})", f"{us_wr:.1%} ({us_w}/{us_t})",
             f"{cb_wr:.1%} ({cb_w}/{cb_t})"],
        ]

    add_section("绩效总览", basic_rows)

    # 月度归因
    monthly = sector_attribution(snapshots)
    if monthly:
        all_sectors = sorted({s for m in monthly.values() for s in m})
        lines.append("\n## 月度归因\n")
        header = "| 月份 | " + " | ".join(all_sectors) + " | 合计 |"
        sep = "|------|" + "--------|" * len(all_sectors) + "--------|"
        lines.append(header)
        lines.append(sep)
        for month in sorted(monthly.keys()):
            m_data = monthly[month]
            total = sum(m_data.values())
            row = f"| {month} | "
            row += " | ".join(f"{m_data.get(s, 0):+,.0f}" for s in all_sectors)
            row += f" | {total:+,.0f} |"
            lines.append(row)

    # 交易分析
    trades = trade_result.get("trades", [])
    if trades:
        lines.append("\n## 交易记录\n")
        lines.append("| 日期 | 代码 | 方向 | 盈亏 | R/R | 评级 |")
        lines.append("|------|------|------|------|-----|------|")
        for t in trades:
            sym = "¥" if t["currency"] == "CNY" else "$"
            pnl_s = f"{sym}{t['realized_pnl']:+,.0f}"
            rr_s = f"{t['rr_ratio']:.2f}" if t["rr_ratio"] is not None else "—"
            lines.append(f"| {t['date']} | {t['ticker']} | {t['action']} | {pnl_s} | {rr_s} | {t['grade']} |")

        best = trade_result.get("best")
        worst = trade_result.get("worst")
        dist = trade_result.get("grade_dist", {})
        if best or worst or dist:
            lines.append("\n### 交易摘要\n")
            dist_str = "  ".join(f"{g}: {c}笔" for g, c in dist.items() if c)
            lines.append(f"- 评级分布: {dist_str}")
            if best:
                sym = "¥" if best["currency"] == "CNY" else "$"
                lines.append(f"- 最赚: **{best['ticker']}** {sym}{best['realized_pnl']:+,.0f} ({best['date']})")
            if worst:
                sym = "¥" if worst["currency"] == "CNY" else "$"
                lines.append(f"- 最亏: **{worst['ticker']}** {sym}{worst['realized_pnl']:+,.0f} ({worst['date']})")

    output_path.write_text("\n".join(lines), encoding="utf-8")


# ── 主函数 ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Claude模拟盘绩效分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=None,
        help="portfolio_state.json 路径（默认自动搜索）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="报告输出路径（默认: performance_report.md，与 state 同目录）",
    )
    parser.add_argument(
        "--no-benchmark",
        action="store_true",
        help="跳过基准对比（无网络或测试时使用）",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="不保存 Markdown 报告",
    )
    args = parser.parse_args()

    # 定位 portfolio_state.json
    if args.state:
        state_path = args.state.resolve()
    else:
        # 向上搜索至多3层
        candidates = [
            Path.cwd() / "portfolio_state.json",
            Path.cwd().parent / "portfolio_state.json",
            Path(__file__).parent.parent / "portfolio_state.json",
        ]
        state_path = next((p for p in candidates if p.exists()), None)
        if state_path is None:
            console.print("[bold red]错误:[/bold red] 找不到 portfolio_state.json，请用 --state 指定路径。")
            sys.exit(1)

    output_path = args.output or (state_path.parent / "performance_report.md")

    console.print(Panel(f"[bold cyan]Claude 模拟盘绩效分析[/bold cyan]\n读取: {state_path}", expand=False))

    # 加载数据
    state = load_state(state_path)
    snapshots: list[dict] = state.get("performance", {}).get("daily_snapshots", [])
    trade_log: list[dict] = state.get("trade_log", [])

    meta = state.get("_meta", {})
    console.print(
        f"周期: [cyan]{meta.get('start_date', '?')}[/cyan] → [cyan]{meta.get('end_date', '?')}[/cyan]  "
        f"快照: [bold]{len(snapshots)}[/bold] 天  "
        f"交易: [bold]{len(trade_log)}[/bold] 笔"
    )

    # 数据检查
    if not snapshots:
        console.print(
            Panel(
                "[yellow]数据不足：daily_snapshots 为空。\n"
                "模拟盘尚未开始或尚未记录快照。[/yellow]",
                title="⚠️  无数据",
                border_style="yellow",
            )
        )
        # 仍然做交易分析（如果有）
        if trade_log:
            trade_result = trade_analysis(trade_log)
            console.print()
            console.print(build_trade_table(trade_result))
            dist_text = build_grade_dist_panel(trade_result)
            if dist_text:
                console.print(Panel(dist_text, title="交易摘要", border_style="cyan"))
        sys.exit(0)

    if len(snapshots) < MIN_DAYS_FOR_ADVANCED:
        console.print(
            f"[yellow]数据不足：仅有 {len(snapshots)} 天快照（高级指标需 ≥ {MIN_DAYS_FOR_ADVANCED} 天）。"
            f"将跳过 Sharpe / 最大回撤 / 胜率等指标。[/yellow]"
        )

    # 解析净值序列
    a_navs, us_navs, combined_navs = parse_snapshots(snapshots)

    # ── 绩效总览表 ──
    overview_table = build_overview_table(snapshots, a_navs, us_navs, combined_navs, state)
    console.print()
    console.print(overview_table)

    # ── 基准数据（获取一次，多处复用）──
    a_bench_ret: Optional[float] = None   # A股 vs 沪深300 累计收益率(%)
    us_bench_ret: Optional[float] = None  # 美股 vs SPY 累计收益率(%)
    if not args.no_benchmark and len(snapshots) >= 2:
        start_date = snapshots[0].get("date", "")[:10]
        end_date = snapshots[-1].get("date", "")[:10]
        try:
            end_dt = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            end_dt = end_date

        with console.status("[cyan]获取基准数据（沪深300 / SPY）...[/cyan]"):
            a_bench_ret = fetch_benchmark_total_return("000300.SS", start_date, end_dt)
            us_bench_ret = fetch_benchmark_total_return("SPY", start_date, end_dt)

        bench_table = build_benchmark_table(
            snapshots, a_navs, us_navs, combined_navs,
            fetch_bench=True,
        )
        console.print()
        if bench_table:
            console.print(bench_table)
        else:
            console.print("[dim]基准数据获取失败或数据不足，已跳过。[/dim]")

    # ── Alpha分解 ──
    alpha_table = build_alpha_decomposition(
        snapshots, a_navs, us_navs,
        fetch_bench=not args.no_benchmark,
    )
    if alpha_table:
        console.print()
        console.print(alpha_table)

    # ── 逐仓位归因 ──
    attribution_table = build_position_attribution_table(state)
    if attribution_table:
        console.print()
        console.print(attribution_table)

    # ── 风险指标增强 ──
    risk_table = build_risk_metrics_table(snapshots, a_navs, us_navs, combined_navs)
    if risk_table:
        console.print()
        console.print(risk_table)

    # ── 月度归因 ──
    if len(snapshots) >= MIN_DAYS_FOR_ADVANCED:
        monthly_table = build_monthly_table(snapshots)
        if monthly_table:
            console.print()
            console.print(monthly_table)

    # ── 交易分析 ──
    trade_result = trade_analysis(trade_log)
    console.print()
    console.print(build_trade_table(trade_result))
    dist_text = build_grade_dist_panel(trade_result)
    if dist_text:
        console.print(Panel(dist_text, title="交易摘要", border_style="cyan"))

    # ── 交易级指标（全局 + 按账户）──
    trade_log_a = [t for t in trade_log if t.get("account") in ("a_share", "cn")]
    trade_log_us = [t for t in trade_log if t.get("account") == "us"]
    metrics_all = compute_trade_metrics(trade_log)
    metrics_a = compute_trade_metrics(trade_log_a)
    metrics_us = compute_trade_metrics(trade_log_us)

    console.print()
    console.print(Panel(
        build_trade_metrics_panel(metrics_all),
        title="📊 交易级指标（全部）",
        border_style="cyan",
    ))
    if trade_log_a and trade_log_us:
        # Show per-account breakdown too
        a_panel = build_trade_metrics_panel(metrics_a)
        us_panel = build_trade_metrics_panel(metrics_us)
        console.print(Panel(a_panel, title="A股交易指标", border_style="yellow"))
        console.print(Panel(us_panel, title="美股交易指标", border_style="blue"))

    # ── 账户并排对比 ──
    # Use already-fetched bench returns (or None if --no-benchmark)
    comparison_table = build_account_comparison_table(
        snapshots, a_navs, us_navs, state,
        metrics_a, metrics_us,
        a_bench_ret, us_bench_ret,
    )
    console.print()
    console.print(comparison_table)

    # ── 导出 Markdown ──
    if not args.no_export:
        export_markdown(snapshots, a_navs, us_navs, combined_navs, trade_result, state, output_path)
        console.print(f"\n[dim]报告已保存: {output_path}[/dim]")

    console.print()


if __name__ == "__main__":
    main()
