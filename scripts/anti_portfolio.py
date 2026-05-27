# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""
Anti-Portfolio Analysis — "我没有的赢家是谁？"

Finds top performers NOT in your known universe (portfolio + watchlist names).
Breaks information cocoon by forcing visibility into unfamiliar winners.

Usage:
    uv run --script scripts/anti_portfolio.py
    uv run --script scripts/anti_portfolio.py --period 1m --top 50
    uv run --script scripts/anti_portfolio.py --portfolio /path/to/portfolio_state.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio_state.json"
OUTPUT_DIR   = PROJECT_ROOT / "research-notes" / "system-v6" / "discovery"
OUTPUT_PATH  = OUTPUT_DIR / "anti_portfolio_latest.json"

# ── Known Names (V6 Phase 1 already-scanned universe) ─────────────────────────
# These are names you already know — portfolio + regular watchlist names.
# Anything NOT in this set is potentially a blind spot.

KNOWN_NAMES: set[str] = {
    # AI Semis / Compute
    "NVDA", "AMD", "MU", "AVGO", "MRVL", "ARM", "CRDO", "ANET",
    "DELL", "TSM", "INTC", "ASML", "LRCX", "AMAT", "SMCI",
    "SNPS", "CDNS", "KLAC", "ON", "MCHP",
    # Energy / Power
    "GEV", "VST", "CEG", "NRG", "VRT", "EME", "ETN",
    "APH", "NEE", "AES",
    # Networking / Storage
    "STX", "WDC", "SNDK",
    # Comms / Data
    "GOOGL", "META", "MSFT", "AAPL", "AMZN",
    # Semis broader
    "QCOM", "TXN", "NXPI", "ADI",
    # Uranium / Nuclear
    "SPUT", "LEU", "CCJ", "UEC", "DNN",
    # Other portfolio neighbors
    "AAON", "CLS", "INOD", "CRM", "MSTR",
}

# ── 200-Ticker Universe (11 GICS sectors, ~18 per sector) ─────────────────────

UNIVERSE: dict[str, list[str]] = {
    "Technology": [
        "AAPL", "MSFT", "NVDA", "AMD", "MU", "AVGO", "CRM", "ADBE", "ORCL",
        "NOW", "PANW", "CRWD", "SNPS", "CDNS", "MRVL", "KLAC", "LRCX", "AMAT",
        "MCHP", "ON",
    ],
    "Healthcare": [
        "UNH", "JNJ", "LLY", "ABBV", "TMO", "ABT", "DHR", "BMY", "AMGN",
        "GILD", "VRTX", "REGN", "ISRG", "SYK", "MDT", "ZTS", "CI", "HUM",
        "DXCM", "VEEV",
    ],
    "Financials": [
        "JPM", "BAC", "GS", "MS", "BLK", "SCHW", "AXP", "PGR", "TRV",
        "ALL", "AFL", "MET", "ICE", "CME", "SPGI", "MCO", "FIS", "AJG",
    ],
    "Industrials": [
        "GE", "HON", "CAT", "DE", "RTX", "LMT", "NOC", "BA", "EMR", "ETN",
        "ROK", "PCAR", "WM", "RSG", "URI", "FAST", "VRSK", "TRMB",
    ],
    "Consumer Discretionary": [
        "AMZN", "TSLA", "HD", "LOW", "NKE", "SBUX", "TJX", "ROST",
        "YUM", "DPZ", "BKNG", "MAR", "HLT", "F", "GM",
    ],
    "Consumer Staples": [
        "PG", "KO", "PEP", "COST", "WMT", "CL", "MDLZ", "PM",
        "MO", "EL", "CLX", "KMB",
    ],
    "Energy": [
        "XOM", "CVX", "COP", "EOG", "SLB", "HAL", "OXY", "PSX",
        "VLO", "MPC", "FANG", "DVN",
    ],
    "Utilities": [
        "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "WEC",
        "ES", "ATO", "NRG", "CEG",
    ],
    "Materials": [
        "LIN", "APD", "SHW", "ECL", "NEM", "FCX", "NUE", "STLD", "VMC", "MLM",
    ],
    "Real Estate": [
        "PLD", "AMT", "EQIX", "DLR", "PSA", "O", "WELL", "SPG", "VICI", "ARE",
    ],
    "Communication Services": [
        "GOOGL", "META", "DIS", "NFLX", "CMCSA", "T", "VZ",
        "TMUS", "CHTR", "EA",
    ],
}

# Reverse map: ticker → sector
TICKER_SECTOR: dict[str, str] = {
    t: sector
    for sector, tickers in UNIVERSE.items()
    for t in tickers
}

ALL_UNIVERSE_TICKERS: list[str] = [t for tickers in UNIVERSE.values() for t in tickers]
# deduplicate preserving order
ALL_UNIVERSE_TICKERS = list(dict.fromkeys(ALL_UNIVERSE_TICKERS))


# ── Period helpers ─────────────────────────────────────────────────────────────

PERIOD_DAYS: dict[str, int] = {
    "1w":  7,
    "1m":  30,
    "3m":  90,
    "ytd": 0,   # special: calc from Jan 1
}


def period_start(period: str) -> str:
    today = datetime.today()
    if period == "ytd":
        return f"{today.year}-01-01"
    days = PERIOD_DAYS[period]
    return (today - timedelta(days=days)).strftime("%Y-%m-%d")


def period_label(period: str) -> str:
    labels = {"1w": "1-Week", "1m": "1-Month", "3m": "3-Month", "ytd": "YTD"}
    return labels.get(period, period)


# ── Data fetch ─────────────────────────────────────────────────────────────────

def load_portfolio_tickers(path: Path) -> set[str]:
    """Read US long + short tickers from portfolio_state.json."""
    if not path.exists():
        print(f"WARN: portfolio_state.json not found at {path}", file=sys.stderr)
        return set()
    with open(path) as f:
        data = json.load(f)
    us = data.get("accounts", {}).get("us", {})
    tickers: set[str] = set()
    for p in us.get("positions", []):
        t = p.get("ticker", "").upper()
        if t:
            tickers.add(t)
    for p in us.get("short_positions", []):
        t = p.get("ticker", "").upper()
        if t:
            tickers.add(t)
    return tickers


def fetch_returns(tickers: list[str], start: str, end: str) -> dict[str, float | None]:
    """Fetch close prices and compute period return for each ticker."""
    if not tickers:
        return {}

    print(f"  Fetching {len(tickers)} tickers ({start} → {end})…", flush=True)

    try:
        raw = yf.download(
            tickers,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        print(f"ERROR: yfinance download failed: {e}", file=sys.stderr)
        return {}

    if raw.empty:
        return {}

    # Handle single-ticker squeeze
    if len(tickers) == 1:
        close = raw["Close"] if "Close" in raw.columns else raw
        series = close.squeeze()
        vals = series.dropna().tolist()
        if len(vals) >= 2:
            ret = (vals[-1] / vals[0] - 1) * 100.0
        else:
            ret = None
        return {tickers[0]: ret}

    close = raw["Close"] if "Close" in raw.columns else raw
    results: dict[str, float | None] = {}
    for t in tickers:
        if t not in close.columns:
            results[t] = None
            continue
        vals = close[t].dropna().tolist()
        if len(vals) >= 2:
            results[t] = (vals[-1] / vals[0] - 1) * 100.0
        else:
            results[t] = None
    return results


def fetch_fundamentals(ticker: str) -> dict:
    """Fetch market cap, trailing PE, and industry from yfinance."""
    try:
        info = yf.Ticker(ticker).info
        mktcap = info.get("marketCap")
        pe     = info.get("trailingPE")
        name   = info.get("shortName") or info.get("longName") or ticker
        industry = info.get("industry") or ""
        return {"name": name, "mktcap": mktcap, "pe": pe, "industry": industry}
    except Exception:
        return {"name": ticker, "mktcap": None, "pe": None, "industry": ""}


# ── Formatting helpers ─────────────────────────────────────────────────────────

def fmt_return(v: float | None) -> str:
    if v is None:
        return "  N/A  "
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def fmt_mktcap(v: int | None) -> str:
    if v is None:
        return "N/A"
    if v >= 1_000_000_000_000:
        return f"${v / 1_000_000_000_000:.1f}T"
    if v >= 1_000_000_000:
        return f"${v / 1_000_000_000:.0f}B"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.0f}M"
    return f"${v:,.0f}"


def fmt_pe(v: float | None) -> str:
    if v is None or v <= 0 or v > 999:
        return "N/A"
    return f"{v:.0f}x"


# ── Main logic ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Anti-Portfolio Analysis — find winners outside your known universe")
    parser.add_argument(
        "--portfolio",
        type=Path,
        default=PORTFOLIO_PATH,
        help="Path to portfolio_state.json",
    )
    parser.add_argument(
        "--period",
        choices=["1w", "1m", "3m", "ytd"],
        default="1m",
        help="Ranking period (default: 1m)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="Top N performers to analyse (default: 50)",
    )
    args = parser.parse_args()

    now_utc = datetime.now(tz=timezone.utc)
    today   = datetime.today().strftime("%Y-%m-%d")

    # ── 1. Build "known world" ──
    portfolio_tickers = load_portfolio_tickers(args.portfolio)
    known_world: set[str] = KNOWN_NAMES | {t.upper() for t in portfolio_tickers}

    # ── 2. Fetch universe returns ──
    start = period_start(args.period)
    end   = datetime.today().strftime("%Y-%m-%d")

    print(f"\nFetching universe returns for period={args.period} ({start} → {end})…", flush=True)
    universe_returns = fetch_returns(ALL_UNIVERSE_TICKERS, start, end)

    # ── 3. Rank by return, take top N ──
    ranked = sorted(
        [(t, r) for t, r in universe_returns.items() if r is not None],
        key=lambda x: x[1],
        reverse=True,
    )
    top_n     = args.top
    top_list  = ranked[:top_n]

    # ── 4. Anti-Portfolio: top performers NOT in known world ──
    anti_portfolio = [
        (rank + 1, ticker, ret)
        for rank, (ticker, ret) in enumerate(top_list)
        if ticker.upper() not in known_world
    ]

    anti_gap_pct = len(anti_portfolio) / top_n * 100 if top_n > 0 else 0
    cocoon_alert = anti_gap_pct > 50

    # ── 5. Sector blind spots (≥3 anti-portfolio names in same sector) ──
    sector_counts: dict[str, list[str]] = {}
    for _, ticker, _ in anti_portfolio:
        sector = TICKER_SECTOR.get(ticker, "Unknown")
        sector_counts.setdefault(sector, []).append(ticker)

    blind_spots = {s: tks for s, tks in sector_counts.items() if len(tks) >= 3}

    # ── 6. Sector coverage of known_world on top performers ──
    known_sectors: set[str] = set()
    for rank_idx, (ticker, _) in enumerate(top_list):
        if ticker.upper() in known_world:
            s = TICKER_SECTOR.get(ticker, "Unknown")
            if s != "Unknown":
                known_sectors.add(s)

    total_sectors = len(UNIVERSE)
    covered_sectors = len(known_sectors)

    # ── 7. Fetch fundamentals for top 5 investigate candidates ──
    print("\nFetching fundamentals for top investigate candidates…", flush=True)
    investigate_candidates = anti_portfolio[:5]
    fundamentals: dict[str, dict] = {}
    for _, ticker, _ in investigate_candidates:
        fundamentals[ticker] = fetch_fundamentals(ticker)

    # ── 8. Print report ──
    divider     = "─" * 80
    thin_div    = "─" * 80

    print()
    print("╔" + "═" * 78 + "╗")
    print(f"║{'ANTI-PORTFOLIO ANALYSIS — ' + today:^78}║")
    print(f"║{'Generated: ' + now_utc.strftime('%Y-%m-%d %H:%M UTC'):^78}║")
    print("╚" + "═" * 78 + "╝")

    print()
    print(
        f"  Period: {period_label(args.period):10s} | "
        f"Universe: {len(ALL_UNIVERSE_TICKERS)} stocks | "
        f"Portfolio+Known: {len(known_world)} names"
    )
    print()

    # Top performers — show only anti-portfolio names
    print(f"[TOP {top_n} PERFORMERS — {period_label(args.period)}]")
    print(f"  (showing only ANTI-PORTFOLIO names — NOT in your known universe)")
    print()
    print(f"  {'Rank':<6}  {'Ticker':<8}  {'Sector':<26}  {'Return':>8}")
    print("  " + thin_div[:70])

    if not anti_portfolio:
        print("  ✅  All top performers are already in your known universe!")
    else:
        for rank, ticker, ret in anti_portfolio:
            sector = TICKER_SECTOR.get(ticker, "Unknown")
            print(f"  #{rank:<5}  {ticker:<8}  {sector:<26}  {fmt_return(ret):>8}")

    print()

    # Anti-Portfolio metrics
    print("[ANTI-PORTFOLIO METRICS]")
    print(f"  Gap: {len(anti_portfolio)}/{top_n} = {anti_gap_pct:.0f}% of top performers NOT in known world")
    if cocoon_alert:
        print(f"  ⚠️  COCOON ALERT: >{top_n // 2} of top {top_n} performers are outside your known universe")
    else:
        print(f"  ✅  Awareness OK — majority of top performers are in your known universe")
    print()

    # Sector blind spots
    print("[SECTOR BLIND SPOTS]")
    if not blind_spots:
        print("  ✅  No sector with 3+ unknown top performers detected")
    else:
        for sector, tickers in sorted(blind_spots.items(), key=lambda x: -len(x[1])):
            print(f"  🔴  {sector}: {len(tickers)} top performers you haven't looked at  ({', '.join(tickers)})")
    print()

    # Investigate candidates
    print("[INVESTIGATE CANDIDATES — Top 5]")
    if not investigate_candidates:
        print("  ✅  No investigate candidates — known universe covers all top performers")
    else:
        for idx, (rank, ticker, ret) in enumerate(investigate_candidates, 1):
            fund = fundamentals.get(ticker, {})
            name     = fund.get("name", ticker)
            mktcap   = fmt_mktcap(fund.get("mktcap"))
            pe       = fmt_pe(fund.get("pe"))
            sector   = TICKER_SECTOR.get(ticker, "Unknown")
            industry = fund.get("industry", "")
            blind_flag = "sector blind spot" if sector in blind_spots else "not in any scanner"
            print(f"  {idx}. {ticker} — {name}")
            print(f"     MktCap: {mktcap}  PE: {pe}  |  {sector} / {industry}")
            print(f"     Return: {fmt_return(ret)} ({period_label(args.period)})  |  Why investigate: #{rank} overall, {blind_flag}")
    print()

    # Cocoon metrics summary
    print("[COCOON METRICS]")
    alert_status = f"ALERT (>{70}% threshold)" if anti_gap_pct > 70 else ("WARNING (>50%)" if anti_gap_pct > 50 else "OK")
    print(f"  Anti-Portfolio Gap:  {anti_gap_pct:.0f}%  (target <50%, ALERT if >70%)  → {alert_status}")
    print(f"  Sector Coverage:     {covered_sectors}/{total_sectors}  (target ≥6/11)")
    print(f"  Discovery Candidates: {len(anti_portfolio)} names worth investigating")
    print()

    # Also show what IS in known world for context
    known_in_top = [(rank + 1, t, r) for rank, (t, r) in enumerate(top_list) if t.upper() in known_world]
    if known_in_top:
        print("[KNOWN WORLD IN TOP PERFORMERS — for context]")
        print(f"  {'Rank':<6}  {'Ticker':<8}  {'Sector':<26}  {'Return':>8}")
        print("  " + thin_div[:70])
        for rank, ticker, ret in known_in_top[:15]:
            sector = TICKER_SECTOR.get(ticker, "Unknown")
            print(f"  #{rank:<5}  {ticker:<8}  {sector:<26}  {fmt_return(ret):>8}")
        if len(known_in_top) > 15:
            print(f"  … and {len(known_in_top) - 15} more")
        print()

    # ── 9. Write JSON output ──
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_data = {
        "_meta": {
            "generated_at": now_utc.isoformat(),
            "period": args.period,
            "period_label": period_label(args.period),
            "universe_size": len(ALL_UNIVERSE_TICKERS),
            "known_world_size": len(known_world),
            "top_n": top_n,
            "date": today,
        },
        "metrics": {
            "anti_portfolio_count": len(anti_portfolio),
            "anti_portfolio_gap_pct": round(anti_gap_pct, 1),
            "cocoon_alert": cocoon_alert,
            "sector_coverage": covered_sectors,
            "total_sectors": total_sectors,
            "discovery_candidates": len(anti_portfolio),
        },
        "anti_portfolio": [
            {
                "rank": rank,
                "ticker": ticker,
                "sector": TICKER_SECTOR.get(ticker, "Unknown"),
                "return_pct": round(ret, 2),
                "in_blind_spot_sector": TICKER_SECTOR.get(ticker, "") in blind_spots,
            }
            for rank, ticker, ret in anti_portfolio
        ],
        "sector_blind_spots": {
            sector: {
                "count": len(tickers),
                "tickers": tickers,
            }
            for sector, tickers in blind_spots.items()
        },
        "investigate_candidates": [
            {
                "rank": rank,
                "ticker": ticker,
                "return_pct": round(ret, 2),
                "sector": TICKER_SECTOR.get(ticker, "Unknown"),
                "name": fundamentals.get(ticker, {}).get("name", ticker),
                "market_cap": fundamentals.get(ticker, {}).get("mktcap"),
                "trailing_pe": fundamentals.get(ticker, {}).get("pe"),
                "industry": fundamentals.get(ticker, {}).get("industry", ""),
                "reason": f"#{rank} overall, {period_label(args.period)} return {fmt_return(ret)}",
            }
            for rank, ticker, ret in investigate_candidates
        ],
        "top_performers_full": [
            {
                "rank": rank + 1,
                "ticker": ticker,
                "return_pct": round(ret, 2),
                "sector": TICKER_SECTOR.get(ticker, "Unknown"),
                "in_known_world": ticker.upper() in known_world,
            }
            for rank, (ticker, ret) in enumerate(top_list)
        ],
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"  JSON saved → {OUTPUT_PATH}")
    print()


if __name__ == "__main__":
    main()
