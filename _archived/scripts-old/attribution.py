#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich"]
# ///
"""
attribution.py — Brinson-Fachler归因分析

将组合收益分解为三个效应：
  Allocation Effect  = (w_pi - w_bi) × (r_bi - R_b)
  Selection Effect   = w_bi × (r_pi - r_bi)
  Interaction Effect = (w_pi - w_bi) × (r_pi - r_bi)

数据来源: portfolio_state.json
"""

import json
import argparse
import sys
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# ─── Paths ───────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
STATE_FILE = REPO_ROOT / "portfolio_state.json"

# ─── Data structures ─────────────────────────────────────────────────────────

@dataclass
class SectorAttribution:
    sector: str
    portfolio_weight: float       # w_pi
    benchmark_weight: float       # w_bi
    portfolio_return: float       # r_pi  (best estimate from position data)
    benchmark_sector_return: float # r_bi (benchmark sector proxy)
    allocation: float             # (w_pi - w_bi) × (r_bi - R_b)
    selection: float              # w_bi × (r_pi - r_bi)
    interaction: float            # (w_pi - w_bi) × (r_pi - r_bi)
    total: float                  # allocation + selection + interaction
    tickers: list = field(default_factory=list)
    note: str = ""

@dataclass
class MarketAttribution:
    market: str                   # "US" or "A-Share"
    period_start: str
    period_end: str
    total_return_pct: float
    benchmark_return_pct: float
    active_return_pct: float
    allocation_effect_pct: float
    selection_effect_pct: float
    interaction_effect_pct: float
    by_sector: list = field(default_factory=list)
    cash_drag_pct: float = 0.0
    residual_pct: float = 0.0
    confidence: str = "low"
    data_points: int = 0
    data_quality: str = "preliminary"
    notes: list = field(default_factory=list)

# ─── Load state ──────────────────────────────────────────────────────────────

def load_state() -> dict:
    if not STATE_FILE.exists():
        sys.exit(f"[ERROR] portfolio_state.json not found at {STATE_FILE}")
    with open(STATE_FILE) as f:
        return json.load(f)

# ─── Snapshot helpers ────────────────────────────────────────────────────────

def get_snapshots(state: dict) -> list[dict]:
    return state.get("performance", {}).get("daily_snapshots", [])

def compute_total_return(snapshots: list[dict], nav_key: str, initial: float) -> float:
    """Compute cumulative return from initial capital to latest NAV."""
    valid = [s for s in snapshots if s.get(nav_key) is not None]
    if not valid:
        return 0.0
    latest_nav = valid[-1][nav_key]
    return (latest_nav / initial - 1) * 100

def compute_benchmark_return(snapshots: list[dict], close_key: str, start_val: float) -> float:
    """Compute benchmark cumulative return from start value."""
    valid = [s for s in snapshots if s.get(close_key) is not None]
    if not valid:
        return 0.0
    latest = valid[-1][close_key]
    return (latest / start_val - 1) * 100

# ─── Position-level return estimates ─────────────────────────────────────────

def position_return_pct(pos: dict) -> float:
    """
    Estimate holding-period return from avg_cost → current_price.
    Uses unrealized_pnl_pct if available; otherwise computes directly.
    """
    if "unrealized_pnl_pct" in pos:
        return float(pos["unrealized_pnl_pct"])
    avg_cost = pos.get("avg_cost", 0)
    current = pos.get("current_price", avg_cost)
    if avg_cost == 0:
        return 0.0
    return (current / avg_cost - 1) * 100

# ─── US Brinson Attribution ──────────────────────────────────────────────────

def run_us_attribution(state: dict, snapshots: list[dict], verbose: bool) -> MarketAttribution:
    us = state["accounts"]["us"]
    perf_bench = state["performance"]["benchmark"]
    positions = us["positions"]
    initial_capital = us["initial_capital"]   # $150,000
    total_assets = us["total_assets"]
    cash = us["cash"]

    # ── Benchmark: SPY ────────────────────────────────────────────────────────
    spy_start = perf_bench.get("spy_start", 738.65)
    spy_snapshots = [s for s in snapshots if s.get("spy_close") is not None]
    spy_latest = spy_snapshots[-1]["spy_close"] if spy_snapshots else spy_start
    benchmark_return = (spy_latest / spy_start - 1) * 100

    # ── Portfolio total return ─────────────────────────────────────────────────
    portfolio_return = (total_assets / initial_capital - 1) * 100

    active_return = portfolio_return - benchmark_return

    # ── Sector grouping ────────────────────────────────────────────────────────
    sector_map: dict[str, list[dict]] = {}
    for pos in positions:
        s = pos.get("sector", "Other")
        sector_map.setdefault(s, []).append(pos)

    # Total invested value (excluding cash)
    total_invested = sum(
        p.get("market_value", p.get("shares", 0) * p.get("current_price", 0))
        for p in positions
    )

    # ── Benchmark sector weights (SPY proxy) ──────────────────────────────────
    # SPY approximate sector weights (as of mid-2026, sourced from SSGA sector SPDR sheets)
    # These are approximations. Confidence: low (no live pull).
    SPY_SECTOR_WEIGHTS = {
        "AI芯片/半导体":      0.045,   # Semiconductors ~4.5% of SPY
        "消费科技/硬件":      0.065,   # AAPL ~6.5% of SPY
        "AI搜索/云计算":      0.040,   # GOOGL ~4.0% of SPY
        "软件/SaaS":          0.025,   # ADBE et al.; Software ~12% total; ADBE alone ~0.5%
        "铀/核能":            0.001,   # Near zero in SPY
        "电力设备/燃气轮机":  0.003,   # GEV / industrials sub-sector
        "数据中心电气配电":   0.001,   # FPS is micro-cap IPO
    }
    # Benchmark sector returns = SPY total return (flat proxy — no live sector data)
    # We treat each sector's benchmark return = SPY return as a conservative simplification.
    # A more rigorous analysis would use SPDR XLK, XLE, XLU returns.
    SPY_SECTOR_RETURNS = {k: benchmark_return for k in SPY_SECTOR_WEIGHTS}

    R_b = benchmark_return  # overall benchmark return

    sectors_out = []
    total_alloc = 0.0
    total_sel = 0.0
    total_inter = 0.0

    for sector, pos_list in sorted(sector_map.items()):
        # Portfolio weight for this sector
        sector_mv = sum(
            p.get("market_value", p.get("shares", 0) * p.get("current_price", 0))
            for p in pos_list
        )
        w_pi = sector_mv / total_assets  # weight including cash in denominator

        # Sector portfolio return (market-value weighted average)
        if sector_mv > 0:
            r_pi = sum(
                p.get("market_value", 0) * position_return_pct(p)
                for p in pos_list
            ) / sector_mv
        else:
            r_pi = 0.0

        # Benchmark weight and return
        w_bi = SPY_SECTOR_WEIGHTS.get(sector, 0.002)
        r_bi = SPY_SECTOR_RETURNS.get(sector, R_b)

        # Brinson-Fachler formulas
        allocation  = (w_pi - w_bi) * (r_bi - R_b)
        selection   = w_bi * (r_pi - r_bi)
        interaction = (w_pi - w_bi) * (r_pi - r_bi)
        total       = allocation + selection + interaction

        total_alloc += allocation
        total_sel   += selection
        total_inter += interaction

        tickers = [p["ticker"] for p in pos_list]
        sectors_out.append(SectorAttribution(
            sector=sector,
            portfolio_weight=round(w_pi * 100, 2),
            benchmark_weight=round(w_bi * 100, 2),
            portfolio_return=round(r_pi, 3),
            benchmark_sector_return=round(r_bi, 3),
            allocation=round(allocation * 100, 4),
            selection=round(selection * 100, 4),
            interaction=round(interaction * 100, 4),
            total=round(total * 100, 4),
            tickers=tickers,
        ))

    # ── Cash drag ─────────────────────────────────────────────────────────────
    cash_weight = cash / total_assets
    # Cash earns 0%; benchmark earns R_b → cash drag = cash_weight × (0 - R_b)
    cash_drag = cash_weight * (0 - R_b)  # negative if market went up

    # ── Residual (rounding / benchmark proxy error) ────────────────────────────
    explained = (total_alloc + total_sel + total_inter) * 100 + cash_drag * 100
    residual  = active_return - explained

    data_points = len([s for s in snapshots if s.get("spy_close") is not None])
    period_start = snapshots[0]["date"] if snapshots else "N/A"
    period_end   = snapshots[-1]["date"] if snapshots else "N/A"

    return MarketAttribution(
        market="US (USD)",
        period_start=period_start,
        period_end=period_end,
        total_return_pct=round(portfolio_return, 3),
        benchmark_return_pct=round(benchmark_return, 3),
        active_return_pct=round(active_return, 3),
        allocation_effect_pct=round(total_alloc * 100, 4),
        selection_effect_pct=round(total_sel * 100, 4),
        interaction_effect_pct=round(total_inter * 100, 4),
        cash_drag_pct=round(cash_drag * 100, 4),
        residual_pct=round(residual, 4),
        by_sector=[asdict(s) for s in sectors_out],
        confidence="low",
        data_points=data_points,
        data_quality="preliminary",
        notes=[
            "仅4天数据，所有归因结论置信度=LOW",
            "Benchmark sector weights: SPY近似权重 (SSGA SPDR参考，非实时拉取)",
            "Sector benchmark return = SPY total return (无sector ETF实时数据，保守简化)",
            "持仓收益率 = avg_cost→current_price HPR (不含股息)",
            "HSAI已止损(05-20)：不含在当前归因中",
            "FPS建仓于05-21，当日数据: 持有期极短",
            "Cash drag已单独列出，使用 cash/total_assets × (0 - R_b) 计算",
        ],
    )

# ─── A-Share Brinson Attribution ─────────────────────────────────────────────

def run_astock_attribution(state: dict, snapshots: list[dict], verbose: bool) -> MarketAttribution:
    cn = state["accounts"]["a_share"]
    perf_bench = state["performance"]["benchmark"]
    positions = cn["positions"]
    initial_capital = cn["initial_capital"]  # ¥1,000,000
    total_assets = cn["total_assets"]
    cash = cn["cash"]

    # ── Benchmark: 上证综指 ────────────────────────────────────────────────────
    sse_start = perf_bench.get("sse_composite_start", 4833.524)
    sse_snapshots = [s for s in snapshots if s.get("sse_close") is not None]
    sse_latest = sse_snapshots[-1]["sse_close"] if sse_snapshots else sse_start
    benchmark_return = (sse_latest / sse_start - 1) * 100

    # ── Portfolio total return ─────────────────────────────────────────────────
    portfolio_return = (total_assets / initial_capital - 1) * 100
    active_return = portfolio_return - benchmark_return

    # ── Sector grouping ────────────────────────────────────────────────────────
    sector_map: dict[str, list[dict]] = {}
    for pos in positions:
        s = pos.get("sector", "Other")
        sector_map.setdefault(s, []).append(pos)

    total_invested = sum(
        p.get("market_value", p.get("shares", 0) * p.get("current_price", 0))
        for p in positions
    )

    # ── Benchmark sector weights (上证综指 proxy) ─────────────────────────────
    # 上证综指行业权重近似值 (Wind行业分类，非精确，用于教学性归因)
    # Confidence: low — 无实时Wind/彭博数据
    SSE_SECTOR_WEIGHTS = {
        "电力设备":       0.040,   # 申万电力设备 ~4% of SSE
        "半导体封装":     0.012,   # 申万半导体 ~3-4%, 封装细分更小
        "PCB/苹果链":     0.008,   # 消费电子 ~2% of SSE
        "机器人/精密齿轮": 0.006,  # 机械设备 ~5%, 精密齿轮细分极小
    }
    SSE_SECTOR_RETURNS = {k: benchmark_return for k in SSE_SECTOR_WEIGHTS}

    R_b = benchmark_return

    sectors_out = []
    total_alloc = 0.0
    total_sel = 0.0
    total_inter = 0.0

    for sector, pos_list in sorted(sector_map.items()):
        sector_mv = sum(
            p.get("market_value", p.get("shares", 0) * p.get("current_price", 0))
            for p in pos_list
        )
        w_pi = sector_mv / total_assets

        if sector_mv > 0:
            r_pi = sum(
                p.get("market_value", 0) * position_return_pct(p)
                for p in pos_list
            ) / sector_mv
        else:
            r_pi = 0.0

        w_bi = SSE_SECTOR_WEIGHTS.get(sector, 0.003)
        r_bi = SSE_SECTOR_RETURNS.get(sector, R_b)

        allocation  = (w_pi - w_bi) * (r_bi - R_b)
        selection   = w_bi * (r_pi - r_bi)
        interaction = (w_pi - w_bi) * (r_pi - r_bi)
        total       = allocation + selection + interaction

        total_alloc += allocation
        total_sel   += selection
        total_inter += interaction

        tickers = [p["ticker"] for p in pos_list]
        note = ""
        if sector == "PCB/苹果链":
            note = "鹏鼎(002938)于05-20建仓，持有期极短"
        elif sector == "机器人/精密齿轮":
            note = "双环传动(002472)于05-20建仓，持有期极短"

        sectors_out.append(SectorAttribution(
            sector=sector,
            portfolio_weight=round(w_pi * 100, 2),
            benchmark_weight=round(w_bi * 100, 2),
            portfolio_return=round(r_pi, 3),
            benchmark_sector_return=round(r_bi, 3),
            allocation=round(allocation * 100, 4),
            selection=round(selection * 100, 4),
            interaction=round(interaction * 100, 4),
            total=round(total * 100, 4),
            tickers=tickers,
            note=note,
        ))

    # ── Cash drag ─────────────────────────────────────────────────────────────
    cash_weight = cash / total_assets
    cash_drag = cash_weight * (0 - R_b)

    # ── Residual ───────────────────────────────────────────────────────────────
    # A股有已实现PnL (蓝思止损+¥6870), 会造成额外residual
    explained = (total_alloc + total_sel + total_inter) * 100 + cash_drag * 100
    residual  = active_return - explained

    data_points = len(sse_snapshots)
    period_start = snapshots[0]["date"] if snapshots else "N/A"
    period_end   = snapshots[-1]["date"] if snapshots else "N/A"

    return MarketAttribution(
        market="A-Share (CNY)",
        period_start=period_start,
        period_end=period_end,
        total_return_pct=round(portfolio_return, 3),
        benchmark_return_pct=round(benchmark_return, 3),
        active_return_pct=round(active_return, 3),
        allocation_effect_pct=round(total_alloc * 100, 4),
        selection_effect_pct=round(total_sel * 100, 4),
        interaction_effect_pct=round(total_inter * 100, 4),
        cash_drag_pct=round(cash_drag * 100, 4),
        residual_pct=round(residual, 4),
        by_sector=[asdict(s) for s in sectors_out],
        confidence="low",
        data_points=data_points,
        data_quality="preliminary",
        notes=[
            f"仅{data_points}个有效SSE收盘价数据点，归因置信度=LOW",
            "SSE 05-20日收盘价=null(数据缺失)，该日A股alpha无法计算",
            "Benchmark sector weights: 申万行业近似权重 (非实时Wind数据)",
            "Sector benchmark return = SSE总指数收益 (无申万行业ETF实时数据，保守简化)",
            "蓝思(300433)已止损(05-20)+¥6870已实现PnL，不含在当前持仓归因中，计入residual",
            "鹏鼎(002938) + 双环传动(002472)于05-20建仓，持有期仅1天",
            "大量现金(63.4%)在策略中为主动选择，cash drag已单独列出",
        ],
    )

# ─── Build output dict ────────────────────────────────────────────────────────

def build_output(state: dict) -> dict:
    snapshots = get_snapshots(state)
    period_start = snapshots[0]["date"] if snapshots else "N/A"
    period_end   = snapshots[-1]["date"] if snapshots else "N/A"

    us_attr = run_us_attribution(state, snapshots, verbose=False)
    cn_attr = run_astock_attribution(state, snapshots, verbose=False)

    return {
        "meta": {
            "model": "Brinson-Fachler (1985)",
            "period": f"{period_start} to {period_end}",
            "data_points_us": us_attr.data_points,
            "data_points_astock": cn_attr.data_points,
            "data_quality": "preliminary",
            "confidence": "low",
            "warning": (
                "4天数据不足以支持统计显著性结论。"
                "归因结果仅供方向性参考，不可用于策略决策。"
                "建议积累≥20个交易日数据后重新评估。"
            ),
            "benchmark_proxy_warning": (
                "Sector weights为近似值(SPY/申万)，非实时拉取。"
                "Selection effect因sector benchmark return = 总指数return而可能失真。"
            ),
            "formula": {
                "allocation":  "Allocation_i  = (w_pi - w_bi) × (r_bi - R_b)",
                "selection":   "Selection_i   = w_bi × (r_pi - r_bi)",
                "interaction": "Interaction_i = (w_pi - w_bi) × (r_pi - r_bi)",
            },
        },
        "us_attribution": {
            "market": us_attr.market,
            "period": f"{us_attr.period_start} to {us_attr.period_end}",
            "data_points": us_attr.data_points,
            "data_quality": us_attr.data_quality,
            "confidence": us_attr.confidence,
            "returns": {
                "portfolio_return_pct": us_attr.total_return_pct,
                "benchmark_return_pct": us_attr.benchmark_return_pct,
                "active_return_pct": us_attr.active_return_pct,
            },
            "attribution_effects_pct": {
                "allocation_effect":  us_attr.allocation_effect_pct,
                "selection_effect":   us_attr.selection_effect_pct,
                "interaction_effect": us_attr.interaction_effect_pct,
                "cash_drag":          us_attr.cash_drag_pct,
                "residual":           us_attr.residual_pct,
                "sum_check": round(
                    us_attr.allocation_effect_pct
                    + us_attr.selection_effect_pct
                    + us_attr.interaction_effect_pct
                    + us_attr.cash_drag_pct
                    + us_attr.residual_pct, 4
                ),
            },
            "by_sector": us_attr.by_sector,
            "notes": us_attr.notes,
        },
        "a_share_attribution": {
            "market": cn_attr.market,
            "period": f"{cn_attr.period_start} to {cn_attr.period_end}",
            "data_points": cn_attr.data_points,
            "data_quality": cn_attr.data_quality,
            "confidence": cn_attr.confidence,
            "returns": {
                "portfolio_return_pct": cn_attr.total_return_pct,
                "benchmark_return_pct": cn_attr.benchmark_return_pct,
                "active_return_pct": cn_attr.active_return_pct,
            },
            "attribution_effects_pct": {
                "allocation_effect":  cn_attr.allocation_effect_pct,
                "selection_effect":   cn_attr.selection_effect_pct,
                "interaction_effect": cn_attr.interaction_effect_pct,
                "cash_drag":          cn_attr.cash_drag_pct,
                "residual":           cn_attr.residual_pct,
                "sum_check": round(
                    cn_attr.allocation_effect_pct
                    + cn_attr.selection_effect_pct
                    + cn_attr.interaction_effect_pct
                    + cn_attr.cash_drag_pct
                    + cn_attr.residual_pct, 4
                ),
            },
            "by_sector": cn_attr.by_sector,
            "notes": cn_attr.notes,
        },
    }

# ─── Rich display ─────────────────────────────────────────────────────────────

def display_rich(output: dict) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box
        from rich.panel import Panel
        from rich.text import Text
    except ImportError:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    console = Console()
    meta = output["meta"]

    # Header
    console.print()
    console.print(Panel(
        f"[bold cyan]Brinson-Fachler 归因分析[/bold cyan]\n"
        f"期间: {meta['period']}\n"
        f"[yellow]⚠  数据质量: PRELIMINARY — {meta['warning'][:60]}…[/yellow]",
        title="Portfolio Attribution",
        border_style="cyan",
    ))

    for mkt_key, label in [("us_attribution", "美股 (USD vs SPY)"), ("a_share_attribution", "A股 (CNY vs 上证综指)")]:
        attr = output[mkt_key]
        ret = attr["returns"]
        eff = attr["attribution_effects_pct"]
        console.print()

        # Summary panel
        active_color = "green" if ret["active_return_pct"] >= 0 else "red"
        console.print(Panel(
            f"组合收益: [bold]{ret['portfolio_return_pct']:+.2f}%[/bold]  |  "
            f"基准收益: {ret['benchmark_return_pct']:+.2f}%  |  "
            f"超额收益: [{active_color}][bold]{ret['active_return_pct']:+.2f}%[/bold][/{active_color}]\n"
            f"数据点: {attr['data_points']}  |  置信度: [yellow]{attr['confidence'].upper()}[/yellow]",
            title=f"[bold]{label}[/bold]",
            border_style="blue",
        ))

        # Effect decomposition
        eff_table = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta")
        eff_table.add_column("效应", style="cyan")
        eff_table.add_column("贡献 (pp)", justify="right")
        eff_table.add_column("解读", style="dim")

        def fmt(v: float) -> str:
            color = "green" if v > 0 else ("red" if v < 0 else "white")
            return f"[{color}]{v:+.4f}[/{color}]"

        eff_table.add_row("Allocation Effect",  fmt(eff["allocation_effect"]),  "行业/板块权重偏离基准的贡献")
        eff_table.add_row("Selection Effect",   fmt(eff["selection_effect"]),   "板块内选股超额收益贡献")
        eff_table.add_row("Interaction Effect", fmt(eff["interaction_effect"]), "配置与选股交叉项")
        eff_table.add_row("Cash Drag",          fmt(eff["cash_drag"]),          "现金持有拖累 (持仓不满仓)")
        eff_table.add_row("Residual",           fmt(eff["residual"]),           "已实现PnL/benchmark近似误差")
        eff_table.add_row("─" * 20, "─" * 12, "")
        eff_table.add_row("[bold]Active Return[/bold]",
                          f"[bold]{ret['active_return_pct']:+.4f}[/bold]", "")
        console.print(eff_table)

        # Sector table
        sector_table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        sector_table.add_column("板块", style="cyan", min_width=18)
        sector_table.add_column("Tickers", style="dim", min_width=10)
        sector_table.add_column("组合权重%", justify="right")
        sector_table.add_column("基准权重%", justify="right")
        sector_table.add_column("持仓收益%", justify="right")
        sector_table.add_column("Alloc", justify="right")
        sector_table.add_column("Select", justify="right")
        sector_table.add_column("Inter", justify="right")
        sector_table.add_column("总计", justify="right", style="bold")

        for s in attr["by_sector"]:
            rp = s["portfolio_return"]
            rp_color = "green" if rp > 0 else ("red" if rp < 0 else "white")
            total_v = s["total"]
            tot_color = "green" if total_v > 0 else ("red" if total_v < 0 else "white")
            sector_table.add_row(
                s["sector"],
                ",".join(s["tickers"]),
                f"{s['portfolio_weight']:.1f}",
                f"{s['benchmark_weight']:.1f}",
                f"[{rp_color}]{rp:+.2f}[/{rp_color}]",
                fmt(s["allocation"]),
                fmt(s["selection"]),
                fmt(s["interaction"]),
                f"[{tot_color}]{total_v:+.4f}[/{tot_color}]",
            )

        console.print(sector_table)

        # Notes
        if attr.get("notes"):
            console.print("[dim]Notes:[/dim]")
            for n in attr["notes"]:
                console.print(f"  [dim]• {n}[/dim]")

    console.print()
    console.print(
        "[yellow]⚠  Sector benchmark return = 总指数收益 (简化假设)。"
        "Selection effect因此主要反映持仓绝对收益而非真实选股超额。[/yellow]"
    )
    console.print()

# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Brinson-Fachler归因分析 — 从portfolio_state.json计算",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run --script scripts/attribution.py
  uv run --script scripts/attribution.py --verbose
  uv run --script scripts/attribution.py --output attribution.json
        """,
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="显示详细归因表格 (default: summary only)",
    )
    parser.add_argument(
        "--output", "-o", metavar="FILE",
        help="将结果写入JSON文件",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="强制输出原始JSON (不用rich格式)",
    )
    args = parser.parse_args()

    state = load_state()
    output = build_output(state)

    if args.output:
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"[OK] Attribution saved to {out_path}")

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        display_rich(output)

    if args.verbose:
        # Extra: print raw JSON after rich display
        print("\n=== RAW JSON ===")
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
