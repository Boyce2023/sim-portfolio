# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""
Weekly Screen — Every Friday Full Portfolio Scan
=================================================
5-step scan:
  1. Regime Check:    SPY / VIX / SOX vs 50dma → BULL / NEUTRAL / BEAR
  2. Portfolio Review: US positions — ticker, shares, avg_cost, current_price,
                       pnl%, pod assignment, stop distance
  3. Pod Sizing:      Current pod % vs BULL targets
                      (A=35% B=25% C=20% D≤5% Cash≥10%)
  4. Rotation Signal: Momentum check — leading pods vs lagging pods
  5. Summary:         1-line regime + pod status + rotation + action

Usage:
  uv run --script scripts/weekly_screen.py
  python scripts/weekly_screen.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.config import POD_TARGETS, POD_NAMES

# ─── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PORTFOLIO_JSON = SCRIPT_DIR.parent / "portfolio_state.json"

# ─── Pod Assignment ───────────────────────────────────────────────────────────
# Hardcoded pod assignments per spec

POD_MAP: dict[str, str] = {
    # Pod I — Tech Supply Chain (V6.3: renamed from AI Supply Chain)
    "CLS":  "I",
    "AAON": "I",
    "DELL": "I",
    # Pod II — Energy / Infrastructure
    "VST":  "II",
    "GEV":  "II",
    "SPUT": "II",
    # Pod III — Compute Momentum
    "MU":   "III",
    "AMAT": "III",
    # Pod C — Best Ideas / Cross-Sector (V6.3 NEW)
    "DAL":  "C",
    "MOD":  "C",
    # Beta Reserve
    "AAPL": "Beta",
    # Pod IV — Short (ELIMINATED in V6.2)
    "MSTR": "IV",
    # EXIT CANDIDATES
    "CRM":  "EXIT",
    "INOD": "EXIT",
}

POD_LABELS: dict[str, str] = {
    "I":    POD_NAMES["I"],      # "Tech Supply Chain"
    "II":   POD_NAMES["II"],     # "Energy/Infrastructure"
    "III":  POD_NAMES["III"],    # "Momentum"
    "C":    POD_NAMES["C"],      # "Best Ideas (Cross-Sector)"
    "IV":   POD_NAMES["IV"],     # "Short Book (ELIMINATED in V6.2)"
    "Beta": "Beta Reserve",
    "EXIT":    "EXIT CANDIDATE",
    "UNKNOWN": "Unassigned",
}

# BULL regime pod targets derived from core.config.POD_TARGETS (fractions).
# Format: (lo, hi) as fractions — same as the old hardcoded BULL_TARGETS.
# Pod IV target = 0.0 (eliminated in V6.2); kept for display, won't trigger OVER.
BULL_TARGETS: dict[str, tuple[float, float]] = {
    pod: (frac, frac)
    for pod, frac in POD_TARGETS["BULL"].items()
    if pod != "CASH"
}
# Add IV with (0, 0) so it displays but never triggers OVER
BULL_TARGETS.setdefault("IV", (0.0, 0.0))
# Cash: (min, 1.0) — must hold at least this fraction
BULL_TARGETS["CASH"] = (POD_TARGETS["BULL"]["CASH"], 1.00)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def divider(char: str = "─", width: int = 68) -> str:
    return char * width


def pct_bar(pct: float, width: int = 20) -> str:
    """Simple ASCII bar for a percentage (0–1)."""
    filled = round(pct * width)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def fmt_pct(v: float, sign: bool = True) -> str:
    if sign:
        return f"{v:+.2f}%"
    return f"{v:.2f}%"


def fmt_usd(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}${v:,.2f}"


# ─── Step 1 — Regime Check ────────────────────────────────────────────────────

def fetch_regime() -> dict:
    """
    Fetch SPY, VIX, SOX prices and their 50-day MAs.
    Returns a dict with prices, 50dmas, and BULL/NEUTRAL/BEAR classification.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed", "regime": "UNKNOWN"}

    tickers_raw = {"SPY": "SPY", "VIX": "^VIX", "SOX": "^SOX"}
    result: dict = {}
    regime_votes: list[str] = []

    for label, ticker_sym in tickers_raw.items():
        try:
            t = yf.Ticker(ticker_sym)
            # Fetch ~1 year of data to compute 50dma reliably
            hist = t.history(period="1y", auto_adjust=True)
            if hist.empty:
                result[label] = {"error": "no data"}
                continue

            close_series = hist["Close"].dropna()
            current_price = float(close_series.iloc[-1])
            ma50 = float(close_series.tail(50).mean()) if len(close_series) >= 50 else None
            prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else current_price
            chg_pct = (current_price - prev_close) / prev_close * 100

            result[label] = {
                "price": current_price,
                "ma50": ma50,
                "chg_pct": chg_pct,
                "above_50dma": (current_price > ma50) if ma50 is not None else None,
            }

            if label == "VIX":
                # VIX: lower = bullish
                if current_price < 15:
                    regime_votes.append("BULL")
                elif current_price > 25:
                    regime_votes.append("BEAR")
                else:
                    regime_votes.append("NEUTRAL")
            else:
                # SPY / SOX: above 50dma = bullish
                if ma50 is not None:
                    if current_price > ma50 * 1.005:
                        regime_votes.append("BULL")
                    elif current_price < ma50 * 0.995:
                        regime_votes.append("BEAR")
                    else:
                        regime_votes.append("NEUTRAL")

        except Exception as e:
            result[label] = {"error": str(e)}

    # Majority vote: 2+ BULL → BULL, 2+ BEAR → BEAR, else NEUTRAL
    bull_count = regime_votes.count("BULL")
    bear_count = regime_votes.count("BEAR")
    if bull_count >= 2:
        regime = "BULL"
    elif bear_count >= 2:
        regime = "BEAR"
    else:
        regime = "NEUTRAL"

    result["regime"] = regime
    result["votes"] = regime_votes
    return result


# ─── Step 2 — Portfolio Review ────────────────────────────────────────────────

def load_us_positions() -> tuple[list[dict], list[dict], float, float]:
    """
    Load US long positions, short positions, cash, and total NAV
    from portfolio_state.json.
    Returns: (longs, shorts, cash_usd, total_assets_usd)
    """
    if not PORTFOLIO_JSON.exists():
        raise FileNotFoundError(f"portfolio_state.json not found at {PORTFOLIO_JSON}")

    with PORTFOLIO_JSON.open(encoding="utf-8") as f:
        state = json.load(f)

    us = state["accounts"]["us"]
    longs: list[dict] = us.get("positions", [])
    shorts: list[dict] = us.get("short_positions", [])
    cash: float = float(us.get("cash", 0))
    total_assets: float = float(us.get("total_assets", 0))

    return longs, shorts, cash, total_assets


def fetch_current_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch current prices for a list of tickers via yfinance."""
    if not tickers:
        return {}
    try:
        import yfinance as yf
        prices: dict[str, float] = {}
        for sym in tickers:
            try:
                t = yf.Ticker(sym)
                info = t.fast_info
                prices[sym] = float(info.last_price)
            except Exception:
                prices[sym] = 0.0
        return prices
    except ImportError:
        return {}


def build_position_rows(
    longs: list[dict],
    shorts: list[dict],
    live_prices: dict[str, float],
    total_assets: float,
) -> list[dict]:
    """
    Combine long and short positions into a unified list of rows
    with computed fields: pnl%, pod, stop_distance.
    """
    rows: list[dict] = []

    for pos in longs:
        ticker = pos.get("ticker", "???")
        shares = float(pos.get("shares", 0))
        avg_cost = float(pos.get("avg_cost", 0))

        # Prefer live price, fallback to stored current_price
        if ticker in live_prices and live_prices[ticker] > 0:
            current_price = live_prices[ticker]
        else:
            current_price = float(pos.get("current_price", avg_cost))

        market_value = shares * current_price
        cost_basis = shares * avg_cost
        pnl_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0.0
        port_pct = market_value / total_assets * 100 if total_assets > 0 else 0.0

        stop_loss = pos.get("stop_loss")
        if stop_loss is not None and current_price > 0:
            stop_dist_pct = (float(stop_loss) - current_price) / current_price * 100
        else:
            stop_dist_pct = None

        pod = POD_MAP.get(ticker, "UNKNOWN")

        rows.append({
            "ticker": ticker,
            "type": "LONG",
            "shares": shares,
            "avg_cost": avg_cost,
            "current_price": current_price,
            "market_value": market_value,
            "port_pct": port_pct,
            "pnl_pct": pnl_pct,
            "pod": pod,
            "stop_loss": stop_loss,
            "stop_dist_pct": stop_dist_pct,
            "name": pos.get("name", ticker),
        })

    for pos in shorts:
        ticker = pos.get("ticker", "???")
        shares = float(pos.get("shares", 0))
        entry_price = float(pos.get("entry_price", 0))

        if ticker in live_prices and live_prices[ticker] > 0:
            current_price = live_prices[ticker]
        else:
            current_price = float(pos.get("current_price", entry_price))

        # Short P&L: profit when price falls
        pnl_pct = (entry_price - current_price) / entry_price * 100 if entry_price > 0 else 0.0
        market_value = shares * current_price  # gross exposure

        stop_loss = pos.get("stop_loss")
        if stop_loss is not None and current_price > 0:
            # For shorts, stop is above current price
            stop_dist_pct = (float(stop_loss) - current_price) / current_price * 100
        else:
            stop_dist_pct = None

        pod = POD_MAP.get(ticker, "IV")  # shorts default to Pod IV

        rows.append({
            "ticker": ticker,
            "type": "SHORT",
            "shares": shares,
            "avg_cost": entry_price,
            "current_price": current_price,
            "market_value": market_value,
            "port_pct": market_value / total_assets * 100 if total_assets > 0 else 0.0,
            "pnl_pct": pnl_pct,
            "pod": pod,
            "stop_loss": stop_loss,
            "stop_dist_pct": stop_dist_pct,
            "name": pos.get("name", ticker),
        })

    return rows


# ─── Step 3 — Pod Sizing ──────────────────────────────────────────────────────

def compute_pod_sizing(
    rows: list[dict],
    cash: float,
    total_assets: float,
    regime: str,
) -> dict[str, dict]:
    """
    Compute current % allocation per pod and compare to BULL targets.
    """
    pod_value: dict[str, float] = {"I": 0, "II": 0, "III": 0, "C": 0, "IV": 0, "Beta": 0, "EXIT": 0, "UNKNOWN": 0}

    for row in rows:
        if row["type"] == "LONG":
            pod_value[row["pod"]] = pod_value.get(row["pod"], 0) + row["market_value"]
        elif row["type"] == "SHORT":
            # Count short exposure in Pod IV (target=0 in V6.2, kept for display)
            pod_value["IV"] = pod_value.get("IV", 0) + row["market_value"]

    cash_pct = cash / total_assets if total_assets > 0 else 0

    sizing: dict[str, dict] = {}
    for pod_key in ["I", "II", "III", "C", "IV", "Beta", "EXIT", "UNKNOWN"]:
        val = pod_value.get(pod_key, 0)
        pct = val / total_assets if total_assets > 0 else 0
        target = BULL_TARGETS.get(pod_key)
        if target:
            lo, hi = target
            if pod_key == "IV":
                # Pod IV eliminated (target=0); only flag if somehow over
                status = "OK" if pct <= hi else "OVER"
            elif pod_key in ("I", "II", "III"):
                if pct < lo * 0.80:
                    status = "UNDER"
                elif pct > hi * 1.20:
                    status = "OVER"
                else:
                    status = "OK"
            else:
                status = "-"
        else:
            status = "FLAG"

        sizing[pod_key] = {
            "value": val,
            "pct": pct,
            "status": status,
            "target": target,
        }

    # Cash
    cash_lo, cash_hi = BULL_TARGETS["CASH"]
    sizing["CASH"] = {
        "value": cash,
        "pct": cash_pct,
        "status": "OK" if cash_pct >= cash_lo else "LOW",
        "target": BULL_TARGETS["CASH"],
    }

    return sizing


# ─── Step 4 — Rotation Signal ─────────────────────────────────────────────────

def compute_rotation_signal(rows: list[dict], regime: str) -> dict:
    """
    Inline rotation scan logic (no external import).
    Logic:
    - Compute 4-week momentum proxy from stored pnl% (best available without
      historical trade data: uses current unrealized pnl% as a proxy for
      recent relative performance).
    - Flag pods where all positions are negative as ROTATION OUT candidates.
    - Flag pods where majority of positions are positive as ROTATION IN candidates.
    - Also flag EXIT CANDIDATES for immediate review.
    """
    pod_pnls: dict[str, list[float]] = {}
    exit_candidates: list[str] = []

    for row in rows:
        if row["pod"] == "EXIT":
            exit_candidates.append(row["ticker"])
            continue
        pod = row["pod"]
        pod_pnls.setdefault(pod, []).append(row["pnl_pct"])

    pod_signals: dict[str, str] = {}
    for pod, pnls in pod_pnls.items():
        if not pnls:
            continue
        avg = sum(pnls) / len(pnls)
        n_pos = sum(1 for p in pnls if p > 0)
        n_neg = sum(1 for p in pnls if p <= 0)
        if avg < -3.0 or (n_neg == len(pnls) and len(pnls) > 0):
            pod_signals[pod] = "ROTATE_OUT"
        elif avg > 3.0 and n_pos >= n_neg:
            pod_signals[pod] = "STRONG"
        elif avg > 0:
            pod_signals[pod] = "HOLDING"
        else:
            pod_signals[pod] = "WEAK"

    # Determine overall rotation signal
    rotate_out_pods = [p for p, s in pod_signals.items() if s == "ROTATE_OUT"]
    strong_pods = [p for p, s in pod_signals.items() if s == "STRONG"]

    if rotate_out_pods and strong_pods:
        signal_text = f"ROTATE: out of {','.join(rotate_out_pods)} → into {','.join(strong_pods)}"
        has_signal = True
    elif rotate_out_pods:
        signal_text = f"WEAK PODS: {','.join(rotate_out_pods)} — no clear destination"
        has_signal = True
    elif exit_candidates:
        signal_text = f"NO ROTATION — EXIT candidates need review: {','.join(exit_candidates)}"
        has_signal = True
    else:
        signal_text = "NO ROTATION SIGNAL — all pods holding"
        has_signal = False

    return {
        "signal_text": signal_text,
        "has_signal": has_signal,
        "pod_signals": pod_signals,
        "exit_candidates": exit_candidates,
        "rotate_out_pods": rotate_out_pods,
        "strong_pods": strong_pods,
    }


# ─── Report Printer ───────────────────────────────────────────────────────────

def print_report(
    regime_data: dict,
    rows: list[dict],
    sizing: dict,
    rotation: dict,
    cash: float,
    total_assets: float,
) -> None:
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M BJT")
    regime = regime_data.get("regime", "UNKNOWN")

    REGIME_ICON = {"BULL": "BULL", "NEUTRAL": "NEUTRAL", "BEAR": "BEAR", "UNKNOWN": "?"}

    print()
    print("=" * 68)
    print(f"  WEEKLY SCREEN — {now}")
    print(f"  US Portfolio  |  Total Assets: ${total_assets:,.2f}")
    print("=" * 68)

    # ── Step 1: Regime ──────────────────────────────────────────────────────
    print()
    print(f"  [1/5] REGIME CHECK")
    print(f"  {divider()}")

    for label in ["SPY", "VIX", "SOX"]:
        d = regime_data.get(label, {})
        if "error" in d:
            print(f"  {label:<5}  ERROR: {d['error']}")
            continue
        price = d.get("price", 0)
        ma50  = d.get("ma50")
        chg   = d.get("chg_pct", 0)
        above = d.get("above_50dma")

        ma50_str  = f"50dma={ma50:,.2f}" if ma50 else "50dma=N/A"
        above_str = ("above" if above else "BELOW") if above is not None else "N/A"
        print(f"  {label:<5}  {price:>8,.2f}   {ma50_str}   [{above_str}]   1d: {chg:+.2f}%")

    print()
    votes = regime_data.get("votes", [])
    votes_str = " | ".join(f"{v}" for v in ["SPY", "VIX", "SOX"] if regime_data.get(v))
    regime_label = REGIME_ICON.get(regime, regime)
    print(f"  Regime votes: {votes}")
    print(f"  >>> REGIME: {regime_label} <<<")

    # ── Step 2: Portfolio Review ─────────────────────────────────────────────
    print()
    print(f"  [2/5] PORTFOLIO REVIEW")
    print(f"  {divider()}")

    # Header
    print(f"  {'Ticker':<6} {'Type':<5} {'Shares':>6} {'Avg$':>7} {'Last$':>7}  "
          f"{'P&L%':>7}  {'Pod':<5} {'Stop%':>7}  Status")
    print(f"  {divider('-', 66)}")

    exit_tickers: list[str] = []
    for row in rows:
        ticker = row["ticker"]
        rtype  = row["type"]
        shares = int(row["shares"])
        avg    = row["avg_cost"]
        price  = row["current_price"]
        pnl    = row["pnl_pct"]
        pod    = row["pod"]
        stop_d = row["stop_dist_pct"]

        pnl_str  = fmt_pct(pnl)
        stop_str = fmt_pct(stop_d, sign=False) + " away" if stop_d is not None else "  N/A"
        pod_str  = pod if pod not in ("EXIT", "UNKNOWN") else pod

        # Warning flags
        flags: list[str] = []
        if pod == "EXIT":
            flags.append("FLAG:NO-POD")
            exit_tickers.append(ticker)
        if stop_d is not None and abs(stop_d) < 5.0:
            flags.append("NEAR-STOP")
        if pnl < -10.0:
            flags.append("DRAWDOWN")

        flag_str = " ".join(flags)

        print(f"  {ticker:<6} {rtype:<5} {shares:>6,} {avg:>7.2f} {price:>7.2f}  "
              f"{pnl_str:>7}  {pod_str:<5} {stop_str:>12}  {flag_str}")

    print(f"  {divider('-', 66)}")
    print(f"  Cash: ${cash:,.2f}   NAV: ${total_assets:,.2f}")

    # ── Step 3: Pod Sizing ───────────────────────────────────────────────────
    bull = POD_TARGETS["BULL"]
    target_summary = (
        f"I={bull['I']*100:.0f}% II={bull['II']*100:.0f}% "
        f"III={bull['III']*100:.0f}% C={bull.get('C', 0)*100:.0f}% "
        f"Cash≥{bull['CASH']*100:.0f}%"
    )
    print()
    print(f"  [3/5] POD SIZING  ({regime} targets: {target_summary})")
    print(f"  {divider()}")

    print(f"  {'Pod':<8} {'Name':<22} {'$Value':>10} {'Current%':>9} {'Target%':>9} {'Status':>8}")
    print(f"  {divider('-', 66)}")

    for pod_key in ["I", "II", "III", "C", "IV", "CASH"]:
        info = sizing.get(pod_key, {})
        val  = info.get("value", 0)
        pct  = info.get("pct", 0) * 100
        tgt  = info.get("target")
        stat = info.get("status", "-")

        label = POD_LABELS.get(pod_key, pod_key)
        if tgt:
            lo, hi = tgt
            if lo == hi:
                tgt_str = f"{lo*100:.0f}%"
            elif pod_key == "IV":
                tgt_str = f"≤{hi*100:.0f}%"
            elif pod_key == "CASH":
                tgt_str = f"≥{lo*100:.0f}%"
            else:
                tgt_str = f"{lo*100:.0f}%"
        else:
            tgt_str = " N/A"

        stat_icon = {"OK": "OK", "OVER": "OVER!", "UNDER": "UNDER!", "LOW": "LOW!", "-": "  -"}.get(stat, stat)
        print(f"  {pod_key:<8} {label:<22} ${val:>9,.0f} {pct:>8.1f}% {tgt_str:>9} {stat_icon:>8}")

    # EXIT/UNKNOWN
    for pod_key in ["EXIT", "UNKNOWN"]:
        info = sizing.get(pod_key, {})
        if info.get("value", 0) > 0:
            val = info["value"]
            pct = info.get("pct", 0) * 100
            label = POD_LABELS.get(pod_key, pod_key)
            print(f"  {pod_key:<8} {label:<22} ${val:>9,.0f} {pct:>8.1f}% {'  ---':>9} {'FLAG!':>8}")

    # ── Step 4: Rotation Signal ──────────────────────────────────────────────
    print()
    print(f"  [4/5] ROTATION SIGNAL")
    print(f"  {divider()}")

    pod_sigs = rotation.get("pod_signals", {})
    for pod, sig in pod_sigs.items():
        label = POD_LABELS.get(pod, pod)
        icon  = {"STRONG": "STRONG", "HOLDING": "Holding", "WEAK": "Weak", "ROTATE_OUT": "ROTATE OUT!"}.get(sig, sig)
        print(f"  Pod {pod} ({label:<22}):  {icon}")

    exit_cands = rotation.get("exit_candidates", [])
    if exit_cands:
        print()
        print(f"  EXIT CANDIDATES (no pod assigned — review immediately):")
        for tk in exit_cands:
            matching = [r for r in rows if r["ticker"] == tk]
            if matching:
                r = matching[0]
                print(f"    {tk}  pnl={fmt_pct(r['pnl_pct'])}  value=${r['market_value']:,.0f}")

    print()
    print(f"  Rotation verdict: {rotation['signal_text']}")

    # ── Step 5: Summary ──────────────────────────────────────────────────────
    print()
    print(f"  [5/5] SUMMARY")
    print(f"  {divider()}")

    # Build 1-line summary
    pod_issues = [
        f"Pod{k} {v['status']}"
        for k, v in sizing.items()
        if v.get("status") not in ("OK", "-", None) and k not in ("EXIT", "UNKNOWN")
    ]
    pod_status_str = ", ".join(pod_issues) if pod_issues else "all pods OK"

    rotation_short = rotation["signal_text"].split("—")[0].strip() if "—" in rotation["signal_text"] else rotation["signal_text"]

    # Action recommendation
    actions: list[str] = []
    if regime == "BULL":
        under_pods = [k for k, v in sizing.items() if v.get("status") == "UNDER"]
        over_pods  = [k for k, v in sizing.items() if v.get("status") == "OVER"]
        if under_pods:
            actions.append(f"Add to Pod {'/'.join(under_pods)}")
        if over_pods:
            actions.append(f"Trim Pod {'/'.join(over_pods)}")
    elif regime == "BEAR":
        actions.append("Reduce equity exposure, raise cash")
    else:
        actions.append("Hold current allocation, monitor regime")

    if exit_cands:
        actions.append(f"Assign pod or EXIT: {', '.join(exit_cands)}")

    near_stop = [r["ticker"] for r in rows if r.get("stop_dist_pct") is not None and abs(r["stop_dist_pct"]) < 5.0]
    if near_stop:
        actions.append(f"Near stop — review: {', '.join(near_stop)}")

    action_str = " | ".join(actions) if actions else "No immediate action"

    summary_line = (
        f"Regime={regime}  |  Pods: {pod_status_str}  |  "
        f"Rotation: {rotation_short}  |  Action: {action_str}"
    )
    print(f"  {summary_line}")
    print()
    print("=" * 68)
    print()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("[weekly_screen] Loading portfolio data...", file=sys.stderr)

    # Load positions
    try:
        longs, shorts, cash, total_assets = load_us_positions()
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Collect all tickers for live price fetch
    all_tickers = [p.get("ticker", "") for p in longs] + [p.get("ticker", "") for p in shorts]
    all_tickers = [t for t in all_tickers if t]

    print("[weekly_screen] Fetching live prices for portfolio tickers...", file=sys.stderr)
    live_prices = fetch_current_prices(all_tickers)

    print("[weekly_screen] Fetching regime indicators (SPY / VIX / SOX)...", file=sys.stderr)
    regime_data = fetch_regime()
    regime = regime_data.get("regime", "NEUTRAL")

    # Build rows
    rows = build_position_rows(longs, shorts, live_prices, total_assets)

    # Pod sizing
    sizing = compute_pod_sizing(rows, cash, total_assets, regime)

    # Rotation signal
    rotation = compute_rotation_signal(rows, regime)

    # Print full report
    print_report(regime_data, rows, sizing, rotation, cash, total_assets)


if __name__ == "__main__":
    main()
