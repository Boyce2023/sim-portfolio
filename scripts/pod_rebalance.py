# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13.0"]
# ///
"""
Pod Rebalance Audit — Claude模拟盘美股Pod配置审计

读取 portfolio_state.json 的 US 部分，把每个持仓映射到 Pod，
计算当前 vs 目标配置，输出 over/under 表 + 具体建议操作。

用法:
    uv run --script scripts/pod_rebalance.py
    uv run --script scripts/pod_rebalance.py --regime BEAR
    uv run --script scripts/pod_rebalance.py --regime BULL
"""

from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.config import POD_TARGETS, POD_NAMES

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

console = Console()

# ──────────────────────────────────────────────────────────────────────────────
# 目标权重（derived from core.config.POD_TARGETS — fractions → percentages)
# ──────────────────────────────────────────────────────────────────────────────
# POD_TARGETS uses fractions (e.g. 0.25); TARGETS here uses percentages (25.0)
# to preserve the existing display and delta logic in this script.
TARGETS: dict[str, dict[str, float]] = {
    regime: {
        pod: round(frac * 100, 1)
        for pod, frac in pods.items()
    }
    for regime, pods in POD_TARGETS.items()
}
# Add display-only keys that the script expects (not in config)
for _regime in list(TARGETS.keys()):
    TARGETS[_regime].setdefault("Beta", 0.0)
    TARGETS[_regime].setdefault("EXIT", 0.0)
    TARGETS[_regime].setdefault("Unassigned", 0.0)
    # Rename config key "CASH" → "Cash" used throughout this script
    if "CASH" in TARGETS[_regime]:
        TARGETS[_regime]["Cash"] = TARGETS[_regime].pop("CASH")

# ──────────────────────────────────────────────────────────────────────────────
# Pod 映射
# ──────────────────────────────────────────────────────────────────────────────
POD_MAP: dict[str, str] = {
    # Pod I: Tech Supply Chain (V6.3: renamed from "AI Supply Chain")
    "CLS": "I",
    "AAON": "I",
    "DELL": "I",
    "ANET": "I",
    "TSM": "I",
    "INOD": "I",
    # Pod II: Energy / Infrastructure
    "VST": "II",
    "GEV": "II",
    "SPUT": "II",
    "LEU": "II",
    "CCJ": "II",
    # Pod III: Compute Momentum
    "MU": "III",
    "AMAT": "III",
    "MRVL": "III",
    "AVGO": "III",
    "AMD": "III",
    "ARM": "III",
    "CRDO": "III",
    # Pod C: Best Ideas / Cross-Sector (V6.3 NEW)
    "DAL": "C",
    "MOD": "C",
    # Beta Reserve
    "AAPL": "Beta",
    # EXIT CANDIDATES
    "CRM": "EXIT",
    "MSTR": "EXIT",
}

# Pod IV = 所有 short_positions（动态）


# ──────────────────────────────────────────────────────────────────────────────
# 数据类
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Position:
    ticker: str
    name: str
    market_value: float
    pod: str
    side: str   # "long" or "short"
    pct_of_total: float = 0.0


@dataclass
class PodSummary:
    pod: str
    positions: list[Position] = field(default_factory=list)
    total_value: float = 0.0
    current_pct: float = 0.0
    target_pct: float = 0.0

    @property
    def delta_pct(self) -> float:
        return self.current_pct - self.target_pct

    @property
    def status(self) -> str:
        delta = self.delta_pct
        if abs(delta) < 2.0:
            return "ON TARGET"
        return "OVER" if delta > 0 else "UNDER"


# ──────────────────────────────────────────────────────────────────────────────
# 核心逻辑
# ──────────────────────────────────────────────────────────────────────────────
def load_portfolio(path: Path) -> dict:
    if not path.exists():
        console.print(f"[red]ERROR: {path} not found[/red]")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def assign_pod(ticker: str, side: str) -> str:
    if side == "short":
        return "IV"
    return POD_MAP.get(ticker.upper(), "Unassigned")


def build_positions(us: dict, total_assets: float) -> list[Position]:
    positions: list[Position] = []

    for p in us.get("positions", []):
        ticker = p.get("ticker", "UNKNOWN")
        name = p.get("name", ticker)
        mv = p.get("market_value", 0.0)
        pod = assign_pod(ticker, "long")
        pos = Position(
            ticker=ticker,
            name=name,
            market_value=mv,
            pod=pod,
            side="long",
            pct_of_total=mv / total_assets * 100 if total_assets else 0,
        )
        positions.append(pos)

    for p in us.get("short_positions", []):
        ticker = p.get("ticker", "UNKNOWN")
        name = p.get("name", ticker)
        # short market value: use shares * current_price
        shares = p.get("shares", 0)
        price = p.get("current_price", p.get("entry_price", 0))
        mv = shares * price
        pos = Position(
            ticker=ticker,
            name=name,
            market_value=mv,
            pod="IV",
            side="short",
            pct_of_total=mv / total_assets * 100 if total_assets else 0,
        )
        positions.append(pos)

    return positions


def compute_pods(positions: list[Position], cash: float, total_assets: float,
                 targets: dict[str, float]) -> dict[str, PodSummary]:
    pod_keys = list(targets.keys())
    summaries: dict[str, PodSummary] = {
        k: PodSummary(pod=k, target_pct=targets.get(k, 0.0))
        for k in pod_keys
    }
    # Make sure Unassigned exists
    if "Unassigned" not in summaries:
        summaries["Unassigned"] = PodSummary(pod="Unassigned", target_pct=0.0)

    for pos in positions:
        pod = pos.pod
        if pod not in summaries:
            summaries[pod] = PodSummary(pod=pod, target_pct=0.0)
        summaries[pod].positions.append(pos)
        summaries[pod].total_value += pos.market_value

    # Cash pod
    if "Cash" not in summaries:
        summaries["Cash"] = PodSummary(pod="Cash", target_pct=targets.get("Cash", 0.0))
    summaries["Cash"].total_value = cash

    # Compute current_pct for all pods
    for s in summaries.values():
        s.current_pct = s.total_value / total_assets * 100 if total_assets else 0

    return summaries


def fmt_pct(v: float) -> str:
    return f"{v:.1f}%"


def fmt_delta(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def fmt_usd(v: float) -> str:
    return f"${v:,.0f}"


def color_status(status: str) -> str:
    mapping = {"OVER": "red", "UNDER": "yellow", "ON TARGET": "green"}
    color = mapping.get(status, "white")
    return f"[{color}]{status}[/{color}]"


def color_delta(delta: float) -> str:
    if abs(delta) < 2.0:
        return f"[green]{fmt_delta(delta)}[/green]"
    elif delta > 0:
        return f"[red]{fmt_delta(delta)}[/red]"
    else:
        return f"[yellow]{fmt_delta(delta)}[/yellow]"


# ──────────────────────────────────────────────────────────────────────────────
# 建议生成
# ──────────────────────────────────────────────────────────────────────────────
def generate_recommendations(
    summaries: dict[str, PodSummary],
    total_assets: float,
    regime: str,
) -> list[str]:
    recs: list[str] = []
    idx = 1

    # 1. EXIT candidates first — always recommend exiting
    exit_pod = summaries.get("EXIT")
    if exit_pod and exit_pod.positions:
        for pos in exit_pod.positions:
            recs.append(
                f"{idx}. Exit {pos.ticker} ({pos.name}) → free "
                f"{fmt_usd(pos.market_value)} ({fmt_pct(pos.pct_of_total)})"
            )
            idx += 1

    # 2. OVER pods — trim largest position first
    over_pods = sorted(
        [s for s in summaries.values() if s.status == "OVER" and s.pod not in ("Cash", "EXIT", "Unassigned")],
        key=lambda s: s.delta_pct,
        reverse=True,
    )
    for pod_sum in over_pods:
        trim_usd = abs(pod_sum.delta_pct) / 100 * total_assets
        top_pos = sorted(pod_sum.positions, key=lambda p: p.market_value, reverse=True)
        if top_pos:
            top = top_pos[0]
            recs.append(
                f"{idx}. Trim Pod {pod_sum.pod} — reduce {top.ticker} by "
                f"~{fmt_usd(trim_usd)} to bring Pod {pod_sum.pod} from "
                f"{fmt_pct(pod_sum.current_pct)} → {fmt_pct(pod_sum.target_pct)}"
            )
            idx += 1

    # 3. UNDER pods — deploy freed capital
    under_pods = sorted(
        [s for s in summaries.values() if s.status == "UNDER" and s.pod not in ("Cash", "EXIT", "Unassigned")],
        key=lambda s: s.delta_pct,
    )
    for pod_sum in under_pods:
        deploy_usd = abs(pod_sum.delta_pct) / 100 * total_assets
        existing = [p.ticker for p in pod_sum.positions]
        if existing:
            recs.append(
                f"{idx}. Add to Pod {pod_sum.pod} — deploy ~{fmt_usd(deploy_usd)} "
                f"(target gap {fmt_pct(abs(pod_sum.delta_pct))}); "
                f"current positions: {', '.join(existing)}"
            )
        else:
            recs.append(
                f"{idx}. Build Pod {pod_sum.pod} from scratch — "
                f"deploy ~{fmt_usd(deploy_usd)} ({fmt_pct(pod_sum.target_pct)} target, "
                f"currently 0%); select from POD_MAP candidates"
            )
        idx += 1

    # 4. Cash check
    cash_sum = summaries.get("Cash")
    if cash_sum:
        cash_target = summaries["Cash"].target_pct
        if regime == "BULL" and cash_sum.current_pct < cash_target:
            recs.append(
                f"{idx}. [bold red]CASH WARNING[/bold red] — current cash "
                f"{fmt_pct(cash_sum.current_pct)} < min required {fmt_pct(cash_target)}; "
                "do NOT deploy further until EXIT positions are closed"
            )
            idx += 1

    # 5. Unassigned positions
    unassigned = summaries.get("Unassigned")
    if unassigned and unassigned.positions:
        tickers = [p.ticker for p in unassigned.positions]
        recs.append(
            f"{idx}. Unassigned positions need Pod classification: {', '.join(tickers)} — "
            "add to POD_MAP or consider exiting"
        )

    return recs


# ──────────────────────────────────────────────────────────────────────────────
# 输出
# ──────────────────────────────────────────────────────────────────────────────
def print_report(
    summaries: dict[str, PodSummary],
    positions: list[Position],
    total_assets: float,
    cash: float,
    regime: str,
    recs: list[str],
) -> None:
    console.print()
    console.print(Panel.fit(
        f"[bold white]POD REBALANCE AUDIT[/bold white]   "
        f"Regime: [bold cyan]{regime}[/bold cyan]   "
        f"Total Assets: [bold green]{fmt_usd(total_assets)}[/bold green]",
        box=box.DOUBLE_EDGE,
    ))
    console.print()

    # ── Pod summary table ──
    pod_order = ["I", "II", "III", "C", "IV", "Beta", "Cash", "EXIT", "Unassigned"]
    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold magenta",
                  min_width=100)
    table.add_column("Pod", style="bold", min_width=16, no_wrap=True)
    table.add_column("Target %", justify="right", min_width=9, no_wrap=True)
    table.add_column("Current %", justify="right", min_width=10, no_wrap=True)
    table.add_column("Delta", justify="right", min_width=8, no_wrap=True)
    table.add_column("Value (USD)", justify="right", min_width=13, no_wrap=True)
    table.add_column("Status", justify="center", min_width=11, no_wrap=True)
    table.add_column("Positions", min_width=36)

    for pod_key in pod_order:
        s = summaries.get(pod_key)
        if s is None:
            continue
        if s.total_value == 0 and s.target_pct == 0 and pod_key == "Unassigned":
            continue

        tickers_str = ", ".join(
            f"{p.ticker}({'S' if p.side == 'short' else fmt_pct(p.pct_of_total)})"
            for p in sorted(s.positions, key=lambda p: p.market_value, reverse=True)
        ) if s.positions else ("—" if pod_key != "Cash" else "")

        # Label adjustments
        pod_label = {
            "I": "I   Tech Supply",
            "II": "II  Energy Infra",
            "III": "III Momentum",
            "C": "C   Best Ideas",
            "IV": "IV  Shorts",
            "Beta": "Beta  Reserve",
            "Cash": "Cash",
            "EXIT": "EXIT Candidates",
            "Unassigned": "Unassigned",
        }.get(pod_key, pod_key)

        table.add_row(
            pod_label,
            fmt_pct(s.target_pct),
            fmt_pct(s.current_pct),
            color_delta(s.delta_pct),
            fmt_usd(s.total_value),
            color_status(s.status),
            tickers_str,
        )

    console.print(table)

    # ── EXIT detail block ──
    exit_pod = summaries.get("EXIT")
    if exit_pod and exit_pod.positions:
        console.print()
        exit_items = []
        exit_total = 0.0
        for pos in exit_pod.positions:
            exit_items.append(f"{pos.ticker} ({fmt_usd(pos.market_value)}, {fmt_pct(pos.pct_of_total)})")
            exit_total += pos.market_value
        exit_pct = exit_total / total_assets * 100 if total_assets else 0
        console.print(
            f"[bold yellow]EXIT CANDIDATES:[/bold yellow] {', '.join(exit_items)}"
        )
        console.print(
            f"  → Freeing [bold green]{fmt_usd(exit_total)} ({fmt_pct(exit_pct)})[/bold green] "
            "for redeployment"
        )

    # ── Unassigned warning ──
    unassigned = summaries.get("Unassigned")
    if unassigned and unassigned.positions:
        console.print()
        console.print(
            f"[bold red]UNASSIGNED POSITIONS:[/bold red] "
            + ", ".join(f"{p.ticker} ({fmt_usd(p.market_value)})" for p in unassigned.positions)
        )
        console.print("  → Add to POD_MAP or classify before next rebalance")

    # ── Recommendations ──
    console.print()
    console.print("[bold white]RECOMMENDATIONS:[/bold white]")
    if recs:
        for r in recs:
            console.print(f"  {r}")
    else:
        console.print("  [green]Portfolio is on target — no action required.[/green]")

    console.print()


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Pod Rebalance Audit")
    parser.add_argument(
        "--regime",
        choices=list(TARGETS.keys()),
        default=None,
        help="Market regime override (default: auto-detect from portfolio_state.json note)",
    )
    parser.add_argument(
        "--portfolio",
        type=Path,
        default=PORTFOLIO_PATH,
        help="Path to portfolio_state.json",
    )
    args = parser.parse_args()

    # ── Load data ──
    data = load_portfolio(args.portfolio)
    us = data.get("accounts", {}).get("us", {})

    if not us:
        console.print("[red]ERROR: No 'us' account found in portfolio_state.json[/red]")
        sys.exit(1)

    total_assets: float = us.get("total_assets", 0.0)
    cash: float = us.get("cash", 0.0)

    if total_assets == 0:
        console.print("[red]ERROR: total_assets is 0 — check portfolio_state.json[/red]")
        sys.exit(1)

    # ── Detect regime ──
    if args.regime:
        regime = args.regime
    else:
        # Try to infer from meta note or regime field
        note = data.get("_meta", {}).get("note", "").upper()
        regime_field = data.get("accounts", {}).get("us", {}).get("regime", "").upper()
        combined = f"{note} {regime_field}"
        if "CORRECTION" in combined:
            regime = "CORRECTION"
        elif "BEAR" in combined:
            regime = "BEAR"
        elif "NEUTRAL" in combined:
            regime = "NEUTRAL"
        elif "BULL" in combined:
            regime = "BULL"
        else:
            regime = "BULL"
            console.print("[yellow]WARN: Regime not detected in meta.note — defaulting to BULL. Use --regime to override.[/yellow]")

    targets = TARGETS[regime]

    # ── Build positions ──
    positions = build_positions(us, total_assets)

    # ── Compute pod summaries ──
    summaries = compute_pods(positions, cash, total_assets, targets)

    # ── Generate recommendations ──
    recs = generate_recommendations(summaries, total_assets, regime)

    # ── Print report ──
    print_report(summaries, positions, total_assets, cash, regime, recs)

    # ── Summary stats ──
    console.print(
        f"[dim]Data as of last portfolio update. "
        f"total_assets={fmt_usd(total_assets)}  cash={fmt_usd(cash)}  "
        f"cash%={fmt_pct(cash/total_assets*100)}[/dim]"
    )
    console.print()


if __name__ == "__main__":
    main()
