"""
Refresh today's (2026-08-24) intraday snapshot via Tencent qt.gtimg.cn batch quote API
(single lightweight batched request, not the kline endpoint that WAF'd previously).
D12-compliant: not yfinance.
"""
import json
import socket
import urllib.request

socket.setdefaulttimeout(8)

HERE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/gate13_roundtrip_10dlow"
AGG_PATH = f"{HERE}/agg_closed_trades_frozen.json"
OUT_PATH = f"{HERE}/today_quotes.json"

def prefix(t):
    return "sh" + t if t.startswith("6") else "sz" + t

def main():
    agg = json.load(open(AGG_PATH))
    tickers = sorted(set(x["ticker"] for x in agg))
    codes = [prefix(t) for t in tickers]
    url = "http://qt.gtimg.cn/q=" + ",".join(codes)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=8).read().decode("gbk", errors="ignore")

    out = {}
    for line in raw.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        left, right = line.split("=", 1)
        code = left.replace("v_", "").strip()
        ticker = code[2:]
        val = right.strip().strip('"')
        f = val.split("~")
        if len(f) < 35:
            continue
        current = float(f[3])
        open_ = float(f[5])
        ts = f[30]
        today_high = float(f[33])
        today_low = float(f[34])
        date = ts[:4] + "-" + ts[4:6] + "-" + ts[6:8]
        out[ticker] = [date, open_, current, today_high, today_low, None]
    json.dump(out, open(OUT_PATH, "w"), ensure_ascii=False, indent=2)
    print(f"fetched {len(out)}/{len(tickers)} tickers -> {OUT_PATH}")
    missing = set(tickers) - set(out.keys())
    if missing:
        print("MISSING:", missing)

if __name__ == "__main__":
    main()
