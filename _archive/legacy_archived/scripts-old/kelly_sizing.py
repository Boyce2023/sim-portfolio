# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Kelly Criterion Position Sizing Calculator
==========================================
Reads trade_log from portfolio_state.json and computes Kelly metrics.

Usage:
    uv run --script scripts/kelly_sizing.py
    uv run --script scripts/kelly_sizing.py --verbose

WARNING: This calculator requires closed (realized) trades to be meaningful.
With < 30 closed trades, output is marked "insufficient" and for reference only.
"""

import json
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path


# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PORTFOLIO_STATE = SCRIPT_DIR.parent / "portfolio_state.json"

# ── Constants ──────────────────────────────────────────────────────────────────
MINIMUM_RECOMMENDED_TRADES = 30
MAX_KELLY_CAP = 0.25          # Never recommend >25% per Kelly, regardless of formula
HALF_KELLY_FACTOR = 0.5


def load_portfolio() -> dict:
    """Load portfolio_state.json — the single source of truth."""
    if not PORTFOLIO_STATE.exists():
        print(f"ERROR: portfolio_state.json not found at {PORTFOLIO_STATE}", file=sys.stderr)
        sys.exit(1)
    with open(PORTFOLIO_STATE, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_realized_trades(trade_log: list[dict]) -> list[dict]:
    """
    Return only sell/cover trades that have a realized_pnl field.
    Buy trades do not produce realized P&L — they are excluded.
    """
    realized = []
    for t in trade_log:
        if t.get("action") in ("sell", "cover") and "realized_pnl" in t:
            realized.append(t)
    return realized


def compute_kelly(realized_trades: list[dict], verbose: bool = False) -> dict:
    """
    Compute Kelly Criterion metrics from realized trades.

    Full Kelly: f* = (b*p - q) / b
        b = payoff ratio = avg_win / avg_loss   (both positive magnitudes)
        p = win rate
        q = 1 - p

    Half Kelly: f* / 2  (recommended for real use)

    Returns a metrics dict with data_quality flags.
    """
    wins   = [t for t in realized_trades if t["realized_pnl"] > 0]
    losses = [t for t in realized_trades if t["realized_pnl"] < 0]
    break_evens = [t for t in realized_trades if t["realized_pnl"] == 0]

    total_closed = len(realized_trades)
    n_wins   = len(wins)
    n_losses = len(losses)
    n_be     = len(break_evens)

    # Currency flags
    win_currencies  = list({t.get("currency", "UNKNOWN") for t in wins})
    loss_currencies = list({t.get("currency", "UNKNOWN") for t in losses})
    mixed_currencies = len(set(win_currencies + loss_currencies)) > 1

    # Raw averages (absolute magnitudes)
    avg_win  = sum(t["realized_pnl"] for t in wins)  / n_wins  if n_wins  > 0 else 0.0
    avg_loss = abs(sum(t["realized_pnl"] for t in losses) / n_losses) if n_losses > 0 else 0.0

    if verbose:
        print("\n── Realized Trades Detail ──────────────────────────────")
        for t in realized_trades:
            pnl = t["realized_pnl"]
            sign = "WIN " if pnl > 0 else ("LOSS" if pnl < 0 else "BE  ")
            curr = t.get("currency", "?")
            print(f"  [{sign}] {t['id']:12s} {t['ticker']:8s}  PnL={pnl:+,.2f} {curr}  reason={t.get('reason','')[:60]}")
        print(f"\n  Wins: {n_wins}  Losses: {n_losses}  Break-even: {n_be}  Total closed: {total_closed}")
        if mixed_currencies:
            print(f"  ⚠  Mixed currencies: wins={win_currencies}, losses={loss_currencies}")

    # Kelly calculation (only if we have both wins and losses)
    full_kelly_pct = None
    half_kelly_pct = None
    payoff_ratio   = None
    win_rate       = None
    kelly_note     = []

    if total_closed == 0:
        kelly_note.append("No closed trades — Kelly undefined")
    elif n_wins == 0:
        kelly_note.append("No winning trades — Kelly = 0% (bet nothing)")
        full_kelly_pct = 0.0
        half_kelly_pct = 0.0
    elif n_losses == 0:
        kelly_note.append("No losing trades — Kelly formula undefined (b/0); bet maximum allowed by risk rules")
        win_rate = 1.0
    else:
        win_rate     = n_wins / total_closed
        q            = 1.0 - win_rate
        payoff_ratio = avg_win / avg_loss  # b

        raw_kelly = (payoff_ratio * win_rate - q) / payoff_ratio
        full_kelly_pct = max(0.0, raw_kelly) * 100   # floor at 0%
        half_kelly_pct = full_kelly_pct * HALF_KELLY_FACTOR

        if mixed_currencies:
            kelly_note.append(
                f"MIXED CURRENCIES: {n_wins} {win_currencies} win(s) + {n_losses} {loss_currencies} loss(es) "
                "— not directly comparable, treat with extreme caution"
            )
        if full_kelly_pct > MAX_KELLY_CAP * 100:
            kelly_note.append(
                f"Full Kelly {full_kelly_pct:.1f}% exceeds hard cap {MAX_KELLY_CAP*100:.0f}% "
                "(small-sample artifact — do NOT use)"
            )

    data_quality = "insufficient" if total_closed < MINIMUM_RECOMMENDED_TRADES else "adequate"

    return {
        "total_closed_trades": total_closed,
        "n_wins":   n_wins,
        "n_losses": n_losses,
        "n_break_even": n_be,
        "win_rate":      round(win_rate,   4) if win_rate   is not None else None,
        "avg_win":       round(avg_win,    2),
        "avg_loss":      round(avg_loss,   2),
        "payoff_ratio":  round(payoff_ratio, 4) if payoff_ratio is not None else None,
        "full_kelly_pct": round(full_kelly_pct, 2) if full_kelly_pct is not None else None,
        "half_kelly_pct": round(half_kelly_pct, 2) if half_kelly_pct is not None else None,
        "win_currencies":  win_currencies,
        "loss_currencies": loss_currencies,
        "mixed_currencies": mixed_currencies,
        "data_quality": data_quality,
        "notes": kelly_note,
    }


def build_current_vs_kelly(positions_list: list[dict], kelly_half_pct: float | None) -> list[dict]:
    """
    Compare each open position's current portfolio % against Kelly recommendation.
    With insufficient data, recommended_pct is null for all.
    """
    result = []
    for pos in positions_list:
        ticker = pos.get("ticker", "UNKNOWN")
        current_pct = round((pos.get("portfolio_pct", 0) or 0) * 100, 1)

        if kelly_half_pct is None:
            entry = {
                "ticker": ticker,
                "name": pos.get("name", ""),
                "current_pct": current_pct,
                "kelly_recommended_pct": None,
                "deviation": None,
                "note": "Insufficient per-ticker data",
            }
        else:
            # With adequate data we'd use per-ticker win/loss stats.
            # With only aggregate Kelly, we flag deviation from half-Kelly as a reference.
            deviation = round(current_pct - kelly_half_pct, 1)
            entry = {
                "ticker": ticker,
                "name": pos.get("name", ""),
                "current_pct": current_pct,
                "kelly_recommended_pct": round(kelly_half_pct, 2),
                "deviation": deviation,
                "note": (
                    "Over-weight vs aggregate Half Kelly" if deviation > 2
                    else "Under-weight vs aggregate Half Kelly" if deviation < -2
                    else "Within ±2% of aggregate Half Kelly"
                ),
            }
        result.append(entry)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Kelly Criterion position sizing calculator for sim-portfolio"
    )
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print detailed trade-by-trade breakdown")
    args = parser.parse_args()

    # ── Load data ──────────────────────────────────────────────────────────────
    portfolio = load_portfolio()
    trade_log = portfolio.get("trade_log", [])
    accounts  = portfolio.get("accounts", {})

    total_trades  = len(trade_log)
    buy_trades    = [t for t in trade_log if t.get("action") in ("buy", "short")]
    realized      = extract_realized_trades(trade_log)

    # Collect all open positions across accounts
    all_positions = []
    for acct_data in accounts.values():
        all_positions.extend(acct_data.get("positions", []))

    # ── Unrealized P&L summary ─────────────────────────────────────────────────
    us_unrealized  = accounts.get("us",      {}).get("unrealized_pnl", 0)
    cn_unrealized  = accounts.get("a_share", {}).get("unrealized_pnl", 0)
    us_realized    = accounts.get("us",      {}).get("realized_pnl", 0)
    cn_realized    = accounts.get("a_share", {}).get("realized_pnl", 0)

    # ── Kelly calculation ──────────────────────────────────────────────────────
    kelly = compute_kelly(realized, verbose=args.verbose)

    # ── Current-vs-Kelly table ─────────────────────────────────────────────────
    current_vs_kelly = build_current_vs_kelly(all_positions, kelly["half_kelly_pct"])

    # ── Recommendation text ────────────────────────────────────────────────────
    if kelly["data_quality"] == "insufficient":
        recommendation = (
            f"数据量不足({kelly['total_closed_trades']}笔已实现交易，建议≥{MINIMUM_RECOMMENDED_TRADES}笔)，"
            "Kelly计算仅供参考。目前继续使用固定百分比+bear case规则。"
            "建议积累≥30笔已实现交易后启用Kelly sizing。"
        )
    else:
        recommendation = (
            f"基于{kelly['total_closed_trades']}笔已实现交易，Half Kelly = {kelly['half_kelly_pct']:.1f}%。"
            "实际使用Half Kelly作为单只仓位上限参考，结合bear case规则和流动性约束。"
        )

    # ── Assemble output ────────────────────────────────────────────────────────
    output = {
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_file": str(PORTFOLIO_STATE),
        "data_quality": kelly["data_quality"],
        "confidence_note": "LOW CONFIDENCE — insufficient data" if kelly["data_quality"] == "insufficient"
                           else "MEDIUM — cross-verify before acting",

        "sample_size": {
            "total_trades_in_log": total_trades,
            "buy_trades": len(buy_trades),
            "closed_trades": kelly["total_closed_trades"],
            "wins": kelly["n_wins"],
            "losses": kelly["n_losses"],
            "break_even": kelly["n_break_even"],
            "minimum_recommended": MINIMUM_RECOMMENDED_TRADES,
        },

        "pnl_summary": {
            "us_realized_usd":    us_realized,
            "us_unrealized_usd":  us_unrealized,
            "cn_realized_cny":    cn_realized,
            "cn_unrealized_cny":  cn_unrealized,
        },

        "realized_metrics": {
            "win_rate":       kelly["win_rate"],
            "avg_win":        kelly["avg_win"],
            "avg_loss":       kelly["avg_loss"],
            "payoff_ratio":   kelly["payoff_ratio"],
            "full_kelly_pct": kelly["full_kelly_pct"],
            "half_kelly_pct": kelly["half_kelly_pct"],
            "mixed_currencies": kelly["mixed_currencies"],
            "win_currencies":   kelly["win_currencies"],
            "loss_currencies":  kelly["loss_currencies"],
            "formula": "f* = (b*p - q) / b  |  b=payoff_ratio, p=win_rate, q=1-p",
            "notes": kelly["notes"],
        },

        "current_vs_kelly": current_vs_kelly,
        "recommendation": recommendation,

        "kelly_interpretation": {
            "full_kelly": "Theoretically optimal bet fraction — too aggressive for real use",
            "half_kelly": "Standard practitioner adjustment — reduces variance, slower to ruin",
            "with_small_sample": (
                "Small-sample Kelly massively overfits. "
                "A single outlier trade can push Kelly to 40-80%. "
                "Ignore numerical output; focus on win/loss count only."
            ),
        },
    }

    # ── Print results ──────────────────────────────────────────────────────────
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if args.verbose:
        # Human-readable summary
        print("\n" + "="*60)
        print("KELLY CRITERION SUMMARY")
        print("="*60)
        print(f"  Data quality   : {kelly['data_quality'].upper()}")
        print(f"  Closed trades  : {kelly['total_closed_trades']} / {MINIMUM_RECOMMENDED_TRADES} recommended")
        print(f"  Win rate       : {(kelly['win_rate']*100):.1f}%" if kelly['win_rate'] else "  Win rate       : N/A")
        print(f"  Payoff ratio   : {kelly['payoff_ratio']:.2f}x" if kelly['payoff_ratio'] else "  Payoff ratio   : N/A")
        print(f"  Full Kelly     : {kelly['full_kelly_pct']:.1f}%" if kelly['full_kelly_pct'] is not None else "  Full Kelly     : N/A")
        print(f"  Half Kelly     : {kelly['half_kelly_pct']:.1f}%" if kelly['half_kelly_pct'] is not None else "  Half Kelly     : N/A")
        print()
        print(f"  Recommendation : {recommendation}")
        print()
        if kelly["notes"]:
            print("  Warnings:")
            for note in kelly["notes"]:
                print(f"    ⚠  {note}")
        print("="*60)


if __name__ == "__main__":
    main()
