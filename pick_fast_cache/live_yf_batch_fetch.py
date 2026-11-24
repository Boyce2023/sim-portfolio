#!/usr/bin/env python3
"""
Reusable Concurrent Yahoo Finance Batch Quote/Fundamental Fetcher for pick seat.
Replaces serial yf.Ticker().info loops with ThreadPoolExecutor(max_workers=12).
Supports --tickers A,B,C and --benchmark (compares serial vs parallel wall time).
"""
import argparse, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import yfinance as yf


def fetch_one(ticker: str) -> dict:
    try:
        inf = yf.Ticker(ticker).info
        mc = (inf.get("marketCap") or 0) / 1e9
        px = inf.get("currentPrice") or inf.get("regularMarketPrice") or np.nan
        rev = inf.get("totalRevenue") or np.nan
        pe = inf.get("trailingPE") or np.nan
        ps = inf.get("priceToSalesTrailing12Months") or (mc * 1e9 / rev if rev and rev > 0 else np.nan)
        gm = (inf.get("grossMargins") or np.nan) * 100
        opm = (inf.get("operatingMargins") or np.nan) * 100
        rg = (inf.get("revenueGrowth") or np.nan) * 100
        return {
            "ticker": ticker,
            "mcap_b": round(mc, 2),
            "px": round(px, 2) if pd.notna(px) else np.nan,
            "pe": round(pe, 2) if pd.notna(pe) else np.nan,
            "ps": round(ps, 2) if pd.notna(ps) else np.nan,
            "gm_pct": round(gm, 1) if pd.notna(gm) else np.nan,
            "opm_pct": round(opm, 1) if pd.notna(opm) else np.nan,
            "rev_yoy_pct": round(rg, 1) if pd.notna(rg) else np.nan,
            "ok": pd.notna(px),
        }
    except Exception:
        return {"ticker": ticker, "mcap_b": np.nan, "px": np.nan, "pe": np.nan, "ps": np.nan, "gm_pct": np.nan, "opm_pct": np.nan, "rev_yoy_pct": np.nan, "ok": False}


def fetch_batch(tickers: list[str], max_workers: int = 12) -> pd.DataFrame:
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

    if args.benchmark:
        t0 = time.time()
        _ = [fetch_one(t) for t in tkrs]
        t_ser = time.time() - t0
        t1 = time.time()
        df = fetch_batch(tkrs, max_workers=args.workers)
        t_par = time.time() - t1
        print(f"BENCHMARK ({len(tkrs)} tickers): serial={t_ser:.2f}s -> parallel({args.workers}w)={t_par:.2f}s | speedup={t_ser/max(t_par,0.01):.2f}x | ok={int(df['ok'].sum())}/{len(df)}")
    else:
        t0 = time.time()
        df = fetch_batch(tkrs, max_workers=args.workers)
        print(f"FETCHED {int(df['ok'].sum())}/{len(df)} tickers in {time.time()-t0:.2f}s")
    if args.out:
        df.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
