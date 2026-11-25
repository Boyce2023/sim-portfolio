#!/usr/bin/env python3
"""
Reusable Concurrent Yahoo Finance Batch Quote/Fundamental Fetcher for pick seat.
Upgraded 2026-11-25 (ALL-HANDS Phase 2):
- Strict D12 guard: rejects A-share tickers (.SS/.SZ/.BJ or 6-digit codes).
- Strict U9 guard: fetches exact close & px_date via history(period='5d')['Close'].dropna()
  instead of relying blindly on .info currentPrice (prevents NaN placeholder & stale quote bugs).
- Flags .info fundamental ratios as screening-only (must cross-check quarterly statements before entry).
"""
import argparse, re, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import yfinance as yf

_ASHARE_RE = re.compile(r"^(\d{6}(\.(SS|SZ|BJ))?|(sh|sz)\d{6})$", re.IGNORECASE)


def fetch_one(ticker: str) -> dict:
    t = str(ticker).strip()
    if _ASHARE_RE.match(t):
        raise ValueError(f"D12 VIOLATION: yfinance strictly forbidden for A-share ticker {t!r}")
    try:
        tk = yf.Ticker(t)
        hist = tk.history(period="5d", auto_adjust=False)["Close"].dropna()
        px_hist = float(hist.iloc[-1]) if not hist.empty else np.nan
        px_date = str(hist.index[-1])[:10] if not hist.empty else ""
        inf = tk.info or {}
        mc = (inf.get("marketCap") or 0) / 1e9
        px = px_hist if pd.notna(px_hist) else (inf.get("currentPrice") or inf.get("regularMarketPrice") or np.nan)
        rev = inf.get("totalRevenue") or np.nan
        pe = inf.get("trailingPE") or np.nan
        ps = inf.get("priceToSalesTrailing12Months") or (mc * 1e9 / rev if rev and rev > 0 else np.nan)
        gm = (inf.get("grossMargins") or np.nan) * 100
        opm = (inf.get("operatingMargins") or np.nan) * 100
        rg = (inf.get("revenueGrowth") or np.nan) * 100
        return {
            "ticker": t,
            "px_date": px_date,
            "mcap_b": round(mc, 2),
            "px": round(px, 2) if pd.notna(px) else np.nan,
            "pe_info": round(pe, 2) if pd.notna(pe) else np.nan,
            "ps_info": round(ps, 2) if pd.notna(ps) else np.nan,
            "gm_pct": round(gm, 1) if pd.notna(gm) else np.nan,
            "opm_pct": round(opm, 1) if pd.notna(opm) else np.nan,
            "rev_yoy_pct": round(rg, 1) if pd.notna(rg) else np.nan,
            "ok": pd.notna(px),
        }
    except Exception:
        return {"ticker": t, "px_date": "", "mcap_b": np.nan, "px": np.nan, "pe_info": np.nan, "ps_info": np.nan, "gm_pct": np.nan, "opm_pct": np.nan, "rev_yoy_pct": np.nan, "ok": False}


def fetch_batch(tickers: list[str], max_workers: int = 12) -> pd.DataFrame:
    for t in tickers:
        if _ASHARE_RE.match(str(t).strip()):
            raise ValueError(f"D12 VIOLATION: yfinance strictly forbidden for A-share ticker {t!r}")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        rows = list(ex.map(fetch_one, tickers))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="TXN,MPWR,EME,LRCX,KLAC,PWR,CBOE,CPAY,HPE,AMZN,CVNA,DASH")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--benchmark", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    tkrs = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    t0 = time.time()
    df = fetch_batch(tkrs, max_workers=args.workers)
    print(f"FETCHED {int(df['ok'].sum())}/{len(df)} tickers in {time.time()-t0:.2f}s")
    print(df.to_string(index=False))
    if args.out:
        df.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
