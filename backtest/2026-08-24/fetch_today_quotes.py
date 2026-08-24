"""
Fetch today's (2026-08-24) intraday snapshot bar via Tencent qt.gtimg.cn batch quote API.
A-share data source per D12: NOT yfinance. Uses Tencent web quote endpoint.
Output: /private/tmp/.../scratchpad/today_quotes.json  {ticker: [date,open,close(proxy=current),high,low,volume]}
NOTE: as of fetch time, SH/SZ markets are in midday recess (11:xx-13:00), so "close" here
is the last-traded price of the morning session, not the official EOD close. Disclosed in report.
"""
import json
import urllib.request

AGG_PATH = "/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad/agg_closed_trades.json"
OUT_PATH = "/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad/today_quotes.json"

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
        prev_close = float(f[4])
        open_ = float(f[5])
        ts = f[30]  # e.g. 20260824115241
        today_high = float(f[33])
        today_low = float(f[34])
        date = ts[:4] + "-" + ts[4:6] + "-" + ts[6:8]
        out[ticker] = [date, open_, current, today_high, today_low, None]
    json.dump(out, open(OUT_PATH, "w"), ensure_ascii=False, indent=2)
    print(f"fetched {len(out)}/{len(tickers)} tickers, saved to {OUT_PATH}")
    missing = set(tickers) - set(out.keys())
    if missing:
        print("MISSING:", missing)

if __name__ == "__main__":
    main()
