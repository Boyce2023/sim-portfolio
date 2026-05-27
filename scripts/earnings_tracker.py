# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""
F21 Beat Cycle Tracker — F21框架自动化实现
追踪US持仓的Earnings Beat频率、质量分级、趋势持续性

Usage:
  uv run --script scripts/earnings_tracker.py
  uv run --script scripts/earnings_tracker.py --tickers AAPL VST CRM
  uv run --script scripts/earnings_tracker.py --quarters 6
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import yfinance as yf

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PORTFOLIO_PATH = REPO_ROOT / "portfolio_state.json"


# ─── Data types ───────────────────────────────────────────────────────────────
class QuarterResult(NamedTuple):
    period: str          # e.g. "2024-Q1"
    actual: float | None
    estimate: float | None
    surprise_pct: float | None  # (actual - estimate) / abs(estimate) * 100
    verdict: str         # "Beat" / "Miss" / "In-line" / "No Data"


class F21Status(NamedTuple):
    ticker: str
    name: str
    beat_count: int
    total_quarters: int
    beat_pct: float
    last_verdict: str        # "Beat" / "Miss" / "In-line" / "No Data"
    last_surprise_pct: float | None
    beat_quality: str        # "Expansionary" / "Maintenance" / "Consumptive" / "TBD" / "N/A"
    quality_note: str
    quarters: list[QuarterResult]
    consecutive_beats: int
    f21_signal: str          # "STRONG_BUY" / "BUY" / "HOLD" / "WATCH" / "SELL" / "NO_DATA"
    data_source: str         # "eps_with_estimates" / "eps_only" / "unavailable"


# ─── Portfolio loader ──────────────────────────────────────────────────────────
def load_us_tickers() -> list[tuple[str, str]]:
    """Read US long positions from portfolio_state.json. Returns list of (ticker, name)."""
    if not PORTFOLIO_PATH.exists():
        print(f"[ERROR] portfolio_state.json not found at {PORTFOLIO_PATH}", file=sys.stderr)
        return []

    with open(PORTFOLIO_PATH) as f:
        state = json.load(f)

    us = state.get("accounts", {}).get("us", {})
    positions = us.get("positions", [])
    result = []
    for pos in positions:
        ticker = pos.get("ticker", "").strip().upper()
        name = pos.get("name", ticker)
        if ticker:
            result.append((ticker, name))
    return result


# ─── yfinance helpers ──────────────────────────────────────────────────────────
def _safe_float(val) -> float | None:
    """Convert various yfinance return types to float or None."""
    if val is None:
        return None
    try:
        f = float(val)
        # yfinance sometimes returns NaN
        import math
        if math.isnan(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def fetch_earnings_history(ticker: str, n_quarters: int) -> list[QuarterResult]:
    """
    Try multiple yfinance APIs to get earnings history with estimates.
    Gracefully degrades to actual-only if estimates unavailable.
    Returns list of QuarterResult, newest first.
    """
    t = yf.Ticker(ticker)
    quarters: list[QuarterResult] = []

    # ── Attempt 1: earnings_history (has actual + estimate) ───────────────────
    try:
        eh = t.get_earnings_history()
        if eh is not None and not eh.empty:
            # Columns vary: may be [epsActual, epsEstimate, epsDifference, surprisePercent]
            # or [EPS Estimate, Reported EPS, Surprise(%)]
            col_map = {c.lower().replace(" ", "").replace("_", ""): c for c in eh.columns}
            actual_col = col_map.get("epsactual") or col_map.get("reportedeps")
            estimate_col = col_map.get("epsestimate") or col_map.get("epsestimate")
            surprise_col = col_map.get("surprisepercent") or col_map.get("surprise(%)")

            rows = eh  # already oldest → newest; we collect in order then slice newest N
            for idx, row in rows.iterrows():
                period = str(idx)[:10] if idx else "Unknown"
                actual = _safe_float(row.get(actual_col) if actual_col else None)
                estimate = _safe_float(row.get(estimate_col) if estimate_col else None)
                surprise = _safe_float(row.get(surprise_col) if surprise_col else None)

                if actual is None and estimate is None:
                    continue

                # yfinance surprisePercent is a decimal (0.533 = 53.3%), convert to pct
                if surprise is not None:
                    surprise = surprise * 100

                # Compute surprise if not provided
                if surprise is None and actual is not None and estimate is not None and estimate != 0:
                    surprise = (actual - estimate) / abs(estimate) * 100

                verdict = _classify_verdict(actual, estimate)
                quarters.append(QuarterResult(period, actual, estimate, surprise, verdict))

            if quarters:
                quarters = quarters[-n_quarters:]  # keep most recent N
                return quarters
    except Exception as e:
        pass  # fall through to next attempt

    # ── Attempt 2: quarterly_earnings (actual only, no estimates) ─────────────
    try:
        qe = t.quarterly_earnings
        if qe is not None and not qe.empty:
            for idx, row in qe.iterrows():
                period = str(idx)[:10] if idx else "Unknown"
                actual = _safe_float(row.get("Earnings") or row.get("EPS"))
                quarters.append(QuarterResult(period, actual, None, None, "No Data" if actual is None else "Actual Only"))

            if quarters:
                quarters = list(reversed(quarters))[-n_quarters:]
                return quarters
    except Exception:
        pass

    # ── Attempt 3: income_stmt quarterly ─────────────────────────────────────
    try:
        inc = t.quarterly_income_stmt
        if inc is not None and not inc.empty:
            eps_rows = [r for r in inc.index if "diluted" in r.lower() or "eps" in r.lower()]
            if eps_rows:
                for col in inc.columns[:n_quarters]:
                    val = _safe_float(inc.loc[eps_rows[0], col])
                    period = str(col)[:10]
                    quarters.append(QuarterResult(period, val, None, None, "Actual Only" if val else "No Data"))
                return list(reversed(quarters))
    except Exception:
        pass

    return []


def _classify_verdict(actual: float | None, estimate: float | None) -> str:
    """Classify a quarter as Beat / Miss / In-line / No Data."""
    if actual is None or estimate is None:
        return "No Data"
    if estimate == 0:
        return "Beat" if actual > 0 else "Miss" if actual < 0 else "In-line"
    diff_pct = (actual - estimate) / abs(estimate) * 100
    if diff_pct > 2.0:
        return "Beat"
    elif diff_pct < -2.0:
        return "Miss"
    else:
        return "In-line"


def _assess_beat_quality(ticker: str, ticker_obj: yf.Ticker) -> tuple[str, str]:
    """
    Try to infer beat quality from available data:
    - Expansionary: Beat + next-quarter guidance raised
    - Maintenance: Beat + guidance flat
    - Consumptive: Beat + guidance lowered (sell signal)

    Returns (quality_label, note).
    """
    try:
        # Check if analyst forward EPS estimates have been revised upward recently
        # yfinance earnings_trend has 5-quarter forward estimates
        trend = ticker_obj.earnings_trend
        if trend is not None and not trend.empty:
            # earnings_trend index: 0q, +1q, 0y, +1y, +2y etc.
            fwd_rows = [r for r in trend.index if "+1q" in str(r).lower() or "0q" in str(r).lower()]
            if fwd_rows:
                row = trend.loc[fwd_rows[0]]
                current_est = _safe_float(row.get("earningsEstimate.avg") or row.get("Earnings Estimate"))
                revision = _safe_float(row.get("earningsEstimate.growth") or row.get("EPS Trend.7daysAgo"))
                if revision is not None:
                    if revision > 0.02:
                        return "Expansionary", f"fwd guidance revised +{revision*100:.1f}% → beat quality STRONG"
                    elif revision < -0.02:
                        return "Consumptive", f"fwd guidance revised {revision*100:.1f}% → watch for trend break"
                    else:
                        return "Maintenance", "guidance revision flat (<2%) → trend intact but not accelerating"
    except Exception:
        pass

    try:
        # Fallback: check analyst recommendation trend for recent upgrades
        upgrades = ticker_obj.upgrades_downgrades
        if upgrades is not None and not upgrades.empty:
            recent = upgrades.head(5)
            upgrade_count = sum(1 for _, r in recent.iterrows()
                                if str(r.get("Action", "")).lower() in ("up", "upgrade", "initiated"))
            downgrade_count = sum(1 for _, r in recent.iterrows()
                                  if str(r.get("Action", "")).lower() in ("down", "downgrade"))
            if upgrade_count > downgrade_count:
                return "TBD", f"recent analyst activity: {upgrade_count} upgrades vs {downgrade_count} downgrades — lean Expansionary, confirm next qtr"
            elif downgrade_count > upgrade_count:
                return "TBD", f"recent analyst activity: {downgrade_count} downgrades — lean Consumptive, check guidance"
    except Exception:
        pass

    return "TBD", "需手动确认 — 无法从yfinance获取guidance revision数据"


def _f21_signal(status: F21Status) -> str:
    """
    F21 framework signal based on beat frequency + quality.

    STRONG_BUY: ≥5/6 beats + Expansionary quality
    BUY:        ≥4/6 beats + not Consumptive
    HOLD:       3/6 beats or last quarter beat but trend unclear
    WATCH:      Last Miss or Consumptive quality
    SELL:       Consecutive misses or Consumptive + downward revision
    NO_DATA:    Insufficient data
    """
    if status.total_quarters < 2:
        return "NO_DATA"
    if status.data_source == "unavailable":
        return "NO_DATA"

    beat_pct = status.beat_pct
    last = status.last_verdict
    quality = status.beat_quality
    consec = status.consecutive_beats

    if last == "No Data" or last == "Actual Only":
        return "NO_DATA"

    if quality == "Consumptive":
        return "WATCH" if last == "Beat" else "SELL"

    if beat_pct >= 0.83 and consec >= 3 and quality == "Expansionary":
        return "STRONG_BUY"
    elif beat_pct >= 0.67 and last == "Beat":
        return "BUY"
    elif beat_pct >= 0.5 and last == "Beat":
        return "HOLD"
    elif last == "Miss":
        return "WATCH"
    elif beat_pct < 0.5:
        return "WATCH"
    else:
        return "HOLD"


# ─── Core analysis ─────────────────────────────────────────────────────────────
def analyze_ticker(ticker: str, name: str, n_quarters: int) -> F21Status:
    """Full F21 analysis for one ticker."""
    t = yf.Ticker(ticker)

    quarters = fetch_earnings_history(ticker, n_quarters)

    data_source: str
    if not quarters:
        data_source = "unavailable"
    elif any(q.estimate is not None for q in quarters):
        data_source = "eps_with_estimates"
    else:
        data_source = "eps_only"

    # Filter to actual beat/miss verdicts for frequency calc
    scored = [q for q in quarters if q.verdict in ("Beat", "Miss", "In-line")]
    beat_count = sum(1 for q in scored if q.verdict == "Beat")
    total = len(scored)
    beat_pct = beat_count / total if total > 0 else 0.0

    last_verdict = quarters[-1].verdict if quarters else "No Data"
    last_surprise = quarters[-1].surprise_pct if quarters else None

    # Consecutive beats from most recent
    consecutive = 0
    for q in reversed(quarters):
        if q.verdict == "Beat":
            consecutive += 1
        else:
            break

    # Beat quality — only assess if last quarter was a Beat and we have estimates
    if last_verdict == "Beat" and data_source == "eps_with_estimates":
        quality, quality_note = _assess_beat_quality(ticker, t)
    elif last_verdict == "Miss":
        quality, quality_note = "N/A", "Last quarter was a Miss — no quality assessment"
    elif data_source == "eps_only":
        quality, quality_note = "TBD", "需手动确认 — yfinance无estimate数据，只有actual EPS趋势"
    elif last_verdict == "In-line":
        quality, quality_note = "Maintenance", "In-line result; guidance direction unknown"
    elif data_source == "unavailable":
        quality, quality_note = "N/A", "无earnings数据"
    else:
        quality, quality_note = "TBD", "需手动确认"

    status = F21Status(
        ticker=ticker,
        name=name,
        beat_count=beat_count,
        total_quarters=total,
        beat_pct=beat_pct,
        last_verdict=last_verdict,
        last_surprise_pct=last_surprise,
        beat_quality=quality,
        quality_note=quality_note,
        quarters=quarters,
        consecutive_beats=consecutive,
        f21_signal="",  # filled below
        data_source=data_source,
    )

    signal = _f21_signal(status)
    # Rebuild with signal (NamedTuple is immutable, use _replace)
    status = status._replace(f21_signal=signal)
    return status


# ─── Output formatter ──────────────────────────────────────────────────────────
SIGNAL_ICONS = {
    "STRONG_BUY": "★★",
    "BUY":        "★ ",
    "HOLD":       "◇ ",
    "WATCH":      "⚠ ",
    "SELL":       "✗ ",
    "NO_DATA":    "? ",
}

VERDICT_COLOR = {
    "Beat":        "Beat ✓",
    "Miss":        "Miss ✗",
    "In-line":     "In-line ~",
    "No Data":     "No Data",
    "Actual Only": "Actual Only",
}


def format_output(results: list[F21Status], verbose: bool = False) -> str:
    lines = []
    lines.append("")
    lines.append("=" * 72)
    lines.append("  F21 BEAT CYCLE TRACKER — US Portfolio")
    lines.append(f"  Run date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("=" * 72)
    lines.append("")

    # Summary table
    lines.append(f"  {'Ticker':<8} {'Name':<22} {'Beat Rate':<14} {'Last Qtr':<12} {'Consec':<8} {'Quality':<16} {'Signal'}")
    lines.append(f"  {'-'*7} {'-'*21} {'-'*13} {'-'*11} {'-'*7} {'-'*15} {'-'*12}")

    for r in results:
        icon = SIGNAL_ICONS.get(r.f21_signal, "? ")
        if r.total_quarters > 0:
            beat_str = f"{r.beat_count}/{r.total_quarters} ({r.beat_pct*100:.0f}%)"
        else:
            beat_str = "N/A"

        last = r.last_verdict
        if r.last_surprise_pct is not None:
            surprise_tag = f"+{r.last_surprise_pct:.1f}%" if r.last_surprise_pct >= 0 else f"{r.last_surprise_pct:.1f}%"
            last_str = f"{last} ({surprise_tag})"
        else:
            last_str = last

        consec_str = f"{r.consecutive_beats}Q" if r.consecutive_beats > 0 else "-"
        quality_str = r.beat_quality[:14]
        signal_str = f"{icon}{r.f21_signal}"

        lines.append(f"  {r.ticker:<8} {r.name[:22]:<22} {beat_str:<14} {last_str:<22} {consec_str:<8} {quality_str:<16} {signal_str}")

    lines.append("")
    lines.append("─" * 72)

    # Detail section
    for r in results:
        lines.append("")
        lines.append(f"  [{r.ticker}] {r.name}")
        lines.append(f"  Data source  : {r.data_source}")
        lines.append(f"  Beat rate    : {r.beat_count}/{r.total_quarters} quarters ({r.beat_pct*100:.0f}%)")
        lines.append(f"  Consecutive  : {r.consecutive_beats} beats in a row")
        lines.append(f"  Last quarter : {r.last_verdict}" +
                     (f" (surprise: {r.last_surprise_pct:+.1f}%)" if r.last_surprise_pct is not None else ""))
        lines.append(f"  Beat quality : {r.beat_quality}")
        lines.append(f"  Quality note : {r.quality_note}")
        lines.append(f"  F21 Signal   : {r.f21_signal}")

        if r.quarters and verbose:
            lines.append(f"  Earnings history (newest first):")
            for q in reversed(r.quarters):
                actual_str = f"{q.actual:+.3f}" if q.actual is not None else "N/A "
                est_str = f"{q.estimate:+.3f}" if q.estimate is not None else "N/A  "
                surp_str = f"{q.surprise_pct:+.1f}%" if q.surprise_pct is not None else "   N/A"
                lines.append(f"    {q.period}  actual={actual_str}  est={est_str}  surp={surp_str}  → {q.verdict}")

        lines.append("")

    # Legend
    lines.append("─" * 72)
    lines.append("  F21 Signal legend:")
    lines.append("    STRONG_BUY  — ≥5/6 beats + Expansionary guidance + 3+ consecutive")
    lines.append("    BUY         — ≥4/6 beats + last quarter Beat")
    lines.append("    HOLD        — ≥3/6 beats + last Beat; trend intact")
    lines.append("    WATCH       — Last quarter Miss OR Consumptive quality signal")
    lines.append("    SELL        — Consumptive quality + downward revision")
    lines.append("    NO_DATA     — Insufficient earnings data from yfinance")
    lines.append("")
    lines.append("  Beat Quality:")
    lines.append("    Expansionary — Beat + fwd guidance raised (strongest signal)")
    lines.append("    Maintenance  — Beat + guidance flat; trend intact")
    lines.append("    Consumptive  — Beat + guidance lowered (trend break warning)")
    lines.append("    TBD          — 需手动确认 guidance direction")
    lines.append("=" * 72)
    lines.append("")

    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="F21 Beat Cycle Tracker for US portfolio")
    parser.add_argument("--tickers", nargs="+", metavar="TICKER",
                        help="Override tickers (default: read from portfolio_state.json)")
    parser.add_argument("--quarters", type=int, default=6, metavar="N",
                        help="Number of quarters to analyze (default: 6)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show quarter-by-quarter detail")
    args = parser.parse_args()

    n_quarters = max(2, min(12, args.quarters))  # clamp 2-12

    if args.tickers:
        holdings = [(t.upper(), t.upper()) for t in args.tickers]
    else:
        holdings = load_us_tickers()
        if not holdings:
            print("[ERROR] No US tickers found. Check portfolio_state.json or use --tickers", file=sys.stderr)
            sys.exit(1)

    print(f"\nLoading F21 earnings data for {len(holdings)} tickers ({n_quarters}Q lookback)...")
    print("Note: yfinance estimate coverage varies by ticker — degrading gracefully if unavailable.\n")

    results: list[F21Status] = []
    for i, (ticker, name) in enumerate(holdings, 1):
        print(f"  [{i}/{len(holdings)}] {ticker} ({name})...", end=" ", flush=True)
        try:
            status = analyze_ticker(ticker, name, n_quarters)
            results.append(status)
            source_tag = {"eps_with_estimates": "✓ estimates", "eps_only": "~ actual only", "unavailable": "✗ no data"}.get(status.data_source, "?")
            print(f"{status.beat_count}/{status.total_quarters} beats | {source_tag}")
        except Exception as e:
            print(f"ERROR — {e}")
            # Add placeholder
            results.append(F21Status(
                ticker=ticker, name=name, beat_count=0, total_quarters=0,
                beat_pct=0.0, last_verdict="No Data", last_surprise_pct=None,
                beat_quality="N/A", quality_note=f"Fetch error: {e}",
                quarters=[], consecutive_beats=0,
                f21_signal="NO_DATA", data_source="unavailable"
            ))

    output = format_output(results, verbose=args.verbose)
    print(output)

    # Quick summary line for easy reading (matching requested format)
    print("=== Quick Reference ===")
    for r in results:
        beat_str = f"{r.beat_count}/{r.total_quarters} beats ({r.beat_pct*100:.0f}%)" if r.total_quarters > 0 else "N/A"
        last_str = r.last_verdict
        if r.last_surprise_pct is not None:
            last_str += f" (+{r.last_surprise_pct:.1f}%)" if r.last_surprise_pct >= 0 else f" ({r.last_surprise_pct:.1f}%)"
        quality_str = r.beat_quality if r.beat_quality not in ("TBD", "N/A") else "TBD (check guidance)"
        print(f"{r.ticker:<6}: {beat_str:<18} | Last: {last_str:<22} | Quality: {quality_str}")
    print("")


if __name__ == "__main__":
    main()
