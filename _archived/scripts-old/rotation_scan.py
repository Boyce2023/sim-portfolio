# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""
AI Sub-Sector Rotation Scanner
Weekly relative strength + volume surge detection vs SMH benchmark.
"""

import sys
from datetime import datetime, timedelta, timezone

import yfinance as yf

# ── Configuration ────────────────────────────────────────────────────────────

SUBSECTORS = {
    "GPU_Accel":  ["NVDA", "AMD"],
    "Memory_HBM": ["MU"],
    "Networking": ["AVGO", "MRVL", "ANET", "CRDO"],
    "Servers":    ["DELL", "SMCI"],
    "Power":      ["VST", "GEV", "CEG"],
    "Cooling":    ["VRT", "AAON"],
    "Equipment":  ["ASML", "AMAT", "LRCX"],
    "IP_Design":  ["ARM", "SNPS", "CDNS"],
    "Storage":    ["STX"],
}
BENCHMARK = "SMH"

LOOKBACK_DAYS   = 90    # calendar days of history to fetch
RS_WINDOW_WEEKS = 4     # relative strength window
VOL_FAST        = 10    # fast volume window (days)
VOL_SLOW        = 60    # slow volume window (days)

# Scoring thresholds
RS_GREEN_PCT  = 8.0     # RS > 8% → green signal
RS_RED_PCT    = -4.0    # RS < -4% → red signal
VOL_GREEN_X   = 1.30    # vol ratio > 1.30× → elevated
VOL_RED_X     = 0.85    # vol ratio < 0.85× → depressed


# ── Data Fetch ────────────────────────────────────────────────────────────────

def fetch_close(tickers: list[str], start: str, end: str) -> dict[str, list]:
    """Return {ticker: [close prices]} using daily adj close."""
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty:
        return {}

    close = raw["Close"] if "Close" in raw.columns else raw
    # Single ticker returns a Series
    if hasattr(close, "squeeze"):
        close = close.squeeze()

    result: dict[str, list] = {}
    if len(tickers) == 1:
        ticker = tickers[0]
        series = close
        vals = series.dropna().tolist()
        if vals:
            result[ticker] = vals
    else:
        for t in tickers:
            if t in close.columns:
                vals = close[t].dropna().tolist()
                if vals:
                    result[t] = vals
    return result


# ── Computation ───────────────────────────────────────────────────────────────

def _last_return(prices: list[float], n_days: int) -> float | None:
    """Return pct return over last n_days from the price list."""
    if len(prices) < n_days + 1:
        return None
    start_px = prices[-(n_days + 1)]
    end_px   = prices[-1]
    if start_px == 0:
        return None
    return (end_px / start_px - 1) * 100.0


def _vol_ratio(volumes: list[float], fast: int, slow: int) -> float | None:
    """Return fast/slow volume ratio."""
    if len(volumes) < slow:
        return None
    fast_avg = sum(volumes[-fast:]) / fast
    slow_avg = sum(volumes[-slow:]) / slow
    if slow_avg == 0:
        return None
    return fast_avg / slow_avg


def compute_sector_metrics(
    sector_name: str,
    tickers: list[str],
    all_close: dict[str, list],
    all_vol: dict[str, list],
    bmk_return_4w: float,
    rs_days: int,
) -> dict:
    """
    Aggregate tickers → equal-weight sector return & volume ratio.
    Returns dict with rs_pct, vol_ratio, score, signal.
    """
    returns: list[float] = []
    vol_ratios: list[float] = []

    for t in tickers:
        prices = all_close.get(t, [])
        ret = _last_return(prices, rs_days)
        if ret is not None:
            returns.append(ret)

        vols = all_vol.get(t, [])
        vr = _vol_ratio(vols, VOL_FAST, VOL_SLOW)
        if vr is not None:
            vol_ratios.append(vr)

    if not returns:
        return {"sector": sector_name, "rs_pct": None, "vol_ratio": None,
                "signal": "N/A", "score": -999}

    avg_return  = sum(returns) / len(returns)
    avg_vol_r   = (sum(vol_ratios) / len(vol_ratios)) if vol_ratios else None
    rs_vs_bench = avg_return - bmk_return_4w

    # Scoring
    score  = 0
    signal = "YELLOW"

    if rs_vs_bench >= RS_GREEN_PCT:
        score += 2
    elif rs_vs_bench <= RS_RED_PCT:
        score -= 2

    if avg_vol_r is not None:
        if avg_vol_r >= VOL_GREEN_X:
            score += 1
        elif avg_vol_r <= VOL_RED_X:
            score -= 1

    if score >= 2:
        signal = "GREEN"
    elif score <= -2:
        signal = "RED"

    return {
        "sector":    sector_name,
        "tickers":   tickers,
        "return_4w": avg_return,
        "rs_pct":    rs_vs_bench,
        "vol_ratio": avg_vol_r,
        "score":     score,
        "signal":    signal,
    }


# ── Output ────────────────────────────────────────────────────────────────────

SIGNAL_LABEL = {
    "GREEN":  "🟢 GREEN ",
    "YELLOW": "🟡 YELLOW",
    "RED":    "🔴 RED   ",
    "N/A":    "⬜ N/A   ",
}

def fmt_pct(v: float | None) -> str:
    if v is None:
        return "  N/A  "
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:6.2f}%"

def fmt_ratio(v: float | None) -> str:
    if v is None:
        return "  N/A  "
    return f"{v:.2f}x  "

def print_table(rows: list[dict], bmk_return: float, bmk_vol: float | None) -> None:
    divider = "─" * 72

    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║          AI SUB-SECTOR ROTATION SCAN — Weekly Signal Matrix         ║")
    now_utc = datetime.now(tz=timezone.utc)
    print(f"║  Generated: {now_utc.strftime('%Y-%m-%d %H:%M UTC')}     Benchmark: {BENCHMARK}                    ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print()
    print(f"  {BENCHMARK} (benchmark) │ 4-week return: {fmt_pct(bmk_return):>8}  "
          f"│ Vol ratio ({VOL_FAST}d/{VOL_SLOW}d): {fmt_ratio(bmk_vol):>7}")
    print()
    print(divider)
    print(f"  {'Sector':<13}  {'Signal':<9}  {'4w Return':>10}  "
          f"{'RS vs SMH':>10}  {'Vol Ratio':>10}  {'Score':>5}  Tickers")
    print(divider)

    for r in rows:
        label = SIGNAL_LABEL.get(r["signal"], r["signal"])
        ret   = fmt_pct(r.get("return_4w"))
        rs    = fmt_pct(r.get("rs_pct"))
        vr    = fmt_ratio(r.get("vol_ratio"))
        score = r.get("score", 0)
        tks   = ", ".join(r.get("tickers", []))
        print(f"  {r['sector']:<13}  {label}  {ret:>10}  {rs:>10}  {vr:>10}  {score:>5}  {tks}")

    print(divider)
    print()


def print_conclusion(rows: list[dict]) -> None:
    greens = [r["sector"] for r in rows if r["signal"] == "GREEN"]
    reds   = [r["sector"] for r in rows if r["signal"] == "RED"]

    if not greens and not reds:
        print("ROTATION SIGNAL: NO ROTATION DETECTED")
    else:
        parts: list[str] = []
        if greens:
            parts.append(f"{', '.join(greens)} scoring GREEN")
        if reds:
            parts.append(f"{', '.join(reds)} scoring RED")
        print("ROTATION SIGNAL: " + "; ".join(parts))
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    end_dt   = datetime.today()
    start_dt = end_dt - timedelta(days=LOOKBACK_DAYS)
    start    = start_dt.strftime("%Y-%m-%d")
    end      = end_dt.strftime("%Y-%m-%d")

    rs_days = RS_WINDOW_WEEKS * 5  # trading days ≈ 5d/week

    # Collect all unique tickers
    all_tickers = [BENCHMARK]
    for tks in SUBSECTORS.values():
        all_tickers.extend(tks)
    all_tickers = list(dict.fromkeys(all_tickers))  # deduplicate, preserve order

    print(f"Fetching {len(all_tickers)} tickers ({LOOKBACK_DAYS}d history)…", flush=True)

    # Fetch close prices
    raw_close = yf.download(
        all_tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    if raw_close.empty:
        print("ERROR: No data returned from yfinance.", file=sys.stderr)
        sys.exit(1)

    close_df = raw_close["Close"] if "Close" in raw_close.columns else raw_close

    # Fetch volume (separate download)
    raw_vol = yf.download(
        all_tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    vol_df = raw_vol["Volume"] if "Volume" in raw_vol.columns else None

    # Build per-ticker price lists
    def get_prices(ticker: str) -> list[float]:
        if ticker in close_df.columns:
            return close_df[ticker].dropna().tolist()
        # single-ticker squeeze case (shouldn't happen here but guard)
        return []

    def get_volumes(ticker: str) -> list[float]:
        if vol_df is None:
            return []
        if ticker in vol_df.columns:
            return vol_df[ticker].dropna().tolist()
        return []

    # Benchmark metrics
    bmk_prices  = get_prices(BENCHMARK)
    bmk_volumes = get_volumes(BENCHMARK)
    bmk_return  = _last_return(bmk_prices, rs_days)
    bmk_vol_r   = _vol_ratio(bmk_volumes, VOL_FAST, VOL_SLOW)

    if bmk_return is None:
        print(f"ERROR: Not enough {BENCHMARK} data to compute 4-week return.", file=sys.stderr)
        sys.exit(1)

    # Build price/volume dicts
    all_close = {t: get_prices(t)  for t in all_tickers}
    all_vol   = {t: get_volumes(t) for t in all_tickers}

    # Score each sector
    results: list[dict] = []
    for sector_name, tickers in SUBSECTORS.items():
        m = compute_sector_metrics(
            sector_name, tickers,
            all_close, all_vol,
            bmk_return, rs_days,
        )
        results.append(m)

    # Sort: GREEN first, then by score desc, then RS desc
    results.sort(key=lambda r: (
        -r.get("score", -999),
        -(r.get("rs_pct") or -999),
    ))

    # Output
    print_table(results, bmk_return, bmk_vol_r)
    print_conclusion(results)


if __name__ == "__main__":
    main()
