"""
Fetch qfq (forward-adjusted) daily close series for the 49 tickers involved in the
n=60 a_share closed-trade sample, 2026-01-01 -> 2026-08-24.
Purpose: forward-return "卖对率" check (must match sell_review.py's methodology exactly,
which used adjust="qfq", to be directly comparable to the known C2 benchmark
机械型卖出20日卖对率36% / 判断型87%).

D12-compliant data source policy + WAF-avoidance (prior 2 sessions crashed Tencent's
WAF via concurrent kline requests -> HTTP 501):
  primary: akshare stock_zh_a_daily (sina), STRICTLY SERIAL, one ticker at a time
  socket.setdefaulttimeout(8) as a hard timeout backstop on all requests-layer calls
  on any exception: NO RETRY on sina, immediately fall back once to Tencent's
    web.ifzq.gtimg.cn/appstock/app/fqkline/get qfq endpoint (a different host/path
    than the kline_cache endpoint that WAF'd previously)
  0.4s sleep between tickers regardless of source, to stay well clear of rate limits
"""
import json
import socket
import time
import sys
import urllib.request
import akshare as ak

socket.setdefaulttimeout(8)

HERE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/gate13_roundtrip_10dlow"
AGG_PATH = f"{HERE}/agg_closed_trades_frozen.json"
OUT_PATH = f"{HERE}/qfq_close_series.json"
LOG_PATH = f"{HERE}/fetch_qfq_close.log"

def sina_symbol(t):
    return "sh" + t if t.startswith("6") else "sz" + t

def tencent_symbol(t):
    return "sh" + t if t.startswith("6") else "sz" + t

def fetch_sina_qfq(ticker):
    df = ak.stock_zh_a_daily(symbol=sina_symbol(ticker), start_date="20260101", end_date="20260824", adjust="qfq")
    df["date"] = df["date"].astype(str)
    return [[r["date"], float(r["close"])] for _, r in df.iterrows()]

def fetch_tencent_qfq(ticker):
    sym = tencent_symbol(ticker)
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,2026-01-01,2026-08-24,320,qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", errors="ignore")
    obj = json.loads(raw)
    d = obj["data"][sym]
    rows = d.get("qfqday") or d.get("day")
    # tencent row: [date, open, close, high, low, volume, ...]
    return [[r[0], float(r[2])] for r in rows]

def main():
    agg = json.load(open(AGG_PATH))
    tickers = sorted(set(x["ticker"] for x in agg))
    out = {}
    log_lines = []
    for i, tk in enumerate(tickers):
        source = None
        series = None
        try:
            series = fetch_sina_qfq(tk)
            source = "sina"
        except Exception as e1:
            log_lines.append(f"[{tk}] sina FAILED: {e1} -> trying tencent fallback (no sina retry)")
            try:
                series = fetch_tencent_qfq(tk)
                source = "tencent"
            except Exception as e2:
                log_lines.append(f"[{tk}] tencent FAILED too: {e2} -> UNRESOLVED")
        if series:
            out[tk] = {"source": source, "rows": series}
            log_lines.append(f"[{i+1}/{len(tickers)}] {tk}: {len(series)} rows via {source}")
        else:
            log_lines.append(f"[{i+1}/{len(tickers)}] {tk}: FAILED (no data from either source)")
        print(log_lines[-1])
        time.sleep(0.4)

    json.dump(out, open(OUT_PATH, "w"), ensure_ascii=False, indent=2)
    open(LOG_PATH, "w").write("\n".join(log_lines) + "\n")
    ok = len(out)
    print(f"\nDONE: {ok}/{len(tickers)} succeeded -> {OUT_PATH}")
    missing = set(tickers) - set(out.keys())
    if missing:
        print("MISSING (unresolved, needs manual re-run):", sorted(missing))
        sys.exit(1)

if __name__ == "__main__":
    main()
