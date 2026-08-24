#!/usr/bin/env python3
"""Step 2: fetch daily kline (bfq/unadjusted, tencent/sina via ak CLI) for every
ticker appearing in episodes_window.json. Append today's live quote as a partial
bar (2026-08-24) using ak price. Cache to klines.json.
"""
import json, subprocess, sys, time

AK = "/Users/huaichuaibeimeng/.claude/skills/akshare-china/scripts/ak"
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"

def kline(ticker, n=150):
    try:
        out = subprocess.run([AK, "kline", ticker, str(n), "--json"],
                              capture_output=True, text=True, timeout=30)
        rows = json.loads(out.stdout)
        bars = []
        for r in rows:
            try:
                bars.append({
                    "d": str(r.get("day"))[:10],
                    "o": float(r.get("open")),
                    "h": float(r.get("high")),
                    "l": float(r.get("low")),
                    "c": float(r.get("close")),
                })
            except Exception:
                continue
        bars.sort(key=lambda x: x["d"])
        return bars
    except Exception as e:
        print(f"  kline FAIL {ticker}: {e}", file=sys.stderr)
        return []

def live_quote(ticker):
    try:
        out = subprocess.run([AK, "price", ticker, "--json"],
                              capture_output=True, text=True, timeout=15)
        d = json.loads(out.stdout)
        return {"d": "2026-08-24", "o": float(d["open"]), "h": float(d["high"]),
                "l": float(d["low"]), "c": float(d["price"])}
    except Exception as e:
        print(f"  price FAIL {ticker}: {e}", file=sys.stderr)
        return None

def main():
    with open(f"{BASE}/episodes_window.json") as f:
        eps = json.load(f)
    tickers = sorted(set(e["ticker"] for e in eps))
    print(f"fetching {len(tickers)} tickers...")
    out = {}
    for i, t in enumerate(tickers):
        bars = kline(t, 150)
        today = live_quote(t)
        if today and (not bars or bars[-1]["d"] != today["d"]):
            bars.append(today)
        out[t] = bars
        print(f"  [{i+1}/{len(tickers)}] {t}: {len(bars)} bars, "
              f"{bars[0]['d'] if bars else '?'} -> {bars[-1]['d'] if bars else '?'}")
    with open(f"{BASE}/klines.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    n_empty = sum(1 for t in tickers if not out[t])
    print(f"done. empty/failed: {n_empty}")
    if n_empty:
        print("FAILED TICKERS:", [t for t in tickers if not out[t]])

if __name__ == "__main__":
    main()
