#!/usr/bin/env python3
"""
Full A-share universe backtest: does breakout magnitude above the prior 20-trading-day
high predict forward returns, and is there an empirical cutoff where chasing turns
negative-expectancy?

Signal definition: for stock S on trading day i (i's own bar sequence, i>=20 bars
available before it), let prior20_high = max(high[i-20:i]) (20 PRIOR trading days,
excludes day i itself). If close[i] > prior20_high, day i is a "breakout day" with
  magnitude_pct = (close[i] / prior20_high - 1) * 100

Every (ticker, day) pair with i>=20 inside the window is recorded (not just breakout
days) so we can build:
  - 4 breakout buckets: (0,3] / (3,8] / (8,15] / (15,+inf)  [pct above prior 20d high]
  - Control A "baseline": ALL days in window regardless of position vs prior high
  - Control B "near_miss": days at -8%..0% vs prior high (approaching resistance,
    not yet broken out) -- the most relevant comparison group for "does breaking
    out actually help vs. just being strong-but-not-broken-out"

Forward returns fwd5/fwd20/fwd40 = close[i+N]/close[i]-1, using the SAME ticker's
own trading-day sequence (N trading days later within its own bar list). Left as
NULL (censored) when i+N is beyond the ticker's available bars (i.e. that many real
future trading days have not happened yet as of today 2026-08-24) -- NOT imputed,
NOT dropped from the raw file, just excluded from that horizon's aggregate stats.
This is why n shrinks as horizon lengthens (real censoring, not survivorship).

Data source: akshare ak.stock_zh_a_daily (Sina, unadjusted adjust="") -- D12-compliant
(no yfinance for A-share). Universe from astock_data_layer.get_full_market()
(Eastmoney bulk quote list, 5,861-5,901 tickers incl. BJ exchange). BJ-exchange
codes (prefix 4/8/9) are EXCLUDED because Sina's stock_zh_a_daily does not cover
them -- this is a data-source limitation, not a methodology choice; reported
explicitly in the output as an exclusion, not silently dropped.

Window: signal days must fall in [2026-06-24, 2026-08-24]. Price history fetched
2026-04-01 -> 2026-08-21 (last complete session before "today" 2026-08-24, a Monday;
08-22/23 were weekend) to give >20 trading days of lookback buffer before window
start and to capture whatever forward days have actually occurred by now.

Outputs (this directory):
  universe_codes.json          - full SH/SZ ticker list used
  fetch_log.json                - per-ticker fetch success/fail log
  daylevel_records.csv          - full tidy population, one row per (ticker,day) in window
  bucket_stats.json             - aggregated stats per bucket x horizon (+ control groups)
  bucket_stats.csv              - same, flat table
"""
import json
import sys
import time
import random
import csv
import statistics as st
from concurrent.futures import ThreadPoolExecutor, as_completed

import akshare as ak

OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
FETCH_START = "20260401"
FETCH_END = "20260821"          # last complete session before "today" 2026-08-24
WINDOW_START = "2026-06-24"
WINDOW_END = "2026-08-24"
LOOKBACK_N = 20
HORIZONS = (5, 20, 40)
MAX_WORKERS = 16
FETCH_TIMEOUT_S = 8
MAX_ABS_RET = 3.0  # exclude |fwd return| > 300% as likely unadjusted corp-action artifact (raw split/rights issue)


def get_universe():
    """Reads universe_codes.json produced by step1_fetch_universe.py (run as a SEPARATE
    process -- importing astock_data_layer in the same process as the heavy threaded
    akshare fetch below crashes native mini_racer state, confirmed by testing)."""
    codes = json.load(open(f"{OUTDIR}/universe_codes.json"))
    sh_sz = [c["code"] for c in codes if c["code"][0] in ("6", "0", "3")]
    bj_excluded = [c["code"] for c in codes if c["code"][0] in ("4", "8", "9")]
    print(f"[universe] total={len(codes)} SH/SZ(usable)={len(sh_sz)} BJ_excluded(no sina coverage)={len(bj_excluded)}",
          file=sys.stderr)
    return sh_sz, len(codes), len(bj_excluded)


def prefix(code):
    return "sh" + code if code.startswith("6") else "sz" + code


def _fetch_raw(code):
    df = ak.stock_zh_a_daily(symbol=prefix(code), start_date=FETCH_START, end_date=FETCH_END, adjust="")
    if df is None or len(df) == 0:
        raise ValueError("empty")
    rows = df[["date", "open", "high", "low", "close", "volume"]].values.tolist()
    # normalize date to str
    out = []
    for r in rows:
        d = str(r[0])[:10]
        out.append((d, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    out.sort(key=lambda x: x[0])
    return out


def fetch_one(code, executor_inner):
    """fetch with an 8s hard timeout + 1 retry, run via a nested single-call future."""
    for attempt in range(2):
        fut = executor_inner.submit(_fetch_raw, code)
        try:
            bars = fut.result(timeout=FETCH_TIMEOUT_S)
            return code, bars, None
        except Exception as e:
            last_err = str(e)[:100]
            time.sleep(0.15)
    return code, None, last_err


def extract_records(code, bars):
    """bars: list of (date, open, high, low, close). returns list of day-level record dicts."""
    n = len(bars)
    recs = []
    dates = [b[0] for b in bars]
    highs = [b[2] for b in bars]
    closes = [b[4] for b in bars]
    for i in range(LOOKBACK_N, n):
        d = dates[i]
        if d < WINDOW_START or d > WINDOW_END:
            continue
        prior20_high = max(highs[i - LOOKBACK_N:i])
        if prior20_high <= 0:
            continue
        mag = (closes[i] / prior20_high - 1.0) * 100.0
        row = {"ticker": code, "date": d, "mag_pct": round(mag, 4)}
        for hz in HORIZONS:
            j = i + hz
            if j < n:
                fwd = closes[j] / closes[i] - 1.0
                if abs(fwd) > MAX_ABS_RET:
                    row[f"fwd{hz}"] = None  # likely unadjusted split/rights artifact
                    row[f"fwd{hz}_excluded_outlier"] = True
                else:
                    row[f"fwd{hz}"] = round(fwd, 6)
            else:
                row[f"fwd{hz}"] = None  # censored: that many real future trading days haven't happened yet
        recs.append(row)
    return recs


def main():
    t_start = time.time()
    sh_sz, universe_total, bj_excluded_n = get_universe()

    print(f"[fetch] starting {len(sh_sz)} tickers, {MAX_WORKERS} workers, timeout={FETCH_TIMEOUT_S}s/attempt, "
          f"window {FETCH_START}->{FETCH_END}", file=sys.stderr)

    # warm-up single-threaded call first (avoids a lazy-init race in akshare's first call)
    warm_code, warm_bars, warm_err = fetch_one(sh_sz[0], ThreadPoolExecutor(max_workers=1))
    print(f"[fetch] warmup {warm_code}: {'ok ' + str(len(warm_bars)) + ' bars' if warm_bars else warm_err}", file=sys.stderr)

    all_records = []
    fetch_log = {"ok": 0, "fail": 0, "fail_reasons": {}}
    fail_list = []

    # inner executor used per-call for hard timeout enforcement; outer pool drives concurrency across tickers
    inner_ex = ThreadPoolExecutor(max_workers=MAX_WORKERS * 2)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as outer_ex:
        futs = {outer_ex.submit(fetch_one, c, inner_ex): c for c in sh_sz}
        done_ct = 0
        for f in as_completed(futs):
            code, bars, err = f.result()
            done_ct += 1
            if bars is None or len(bars) < LOOKBACK_N + 1:
                fetch_log["fail"] += 1
                fail_list.append({"code": code, "err": err or "insufficient_bars"})
                fetch_log["fail_reasons"][err[:40] if err else "insufficient_bars"] = \
                    fetch_log["fail_reasons"].get(err[:40] if err else "insufficient_bars", 0) + 1
            else:
                fetch_log["ok"] += 1
                all_records.extend(extract_records(code, bars))
            if done_ct % 500 == 0:
                elapsed = time.time() - t_start
                print(f"[fetch] {done_ct}/{len(sh_sz)} done, elapsed={elapsed:.0f}s, ok={fetch_log['ok']} fail={fetch_log['fail']}",
                      file=sys.stderr)
    inner_ex.shutdown(wait=False)

    fetch_elapsed = time.time() - t_start
    print(f"[fetch] complete: ok={fetch_log['ok']} fail={fetch_log['fail']} elapsed={fetch_elapsed:.0f}s", file=sys.stderr)
    json.dump({"summary": fetch_log, "failures_sample": fail_list[:60], "n_failures_total": len(fail_list)},
              open(f"{OUTDIR}/fetch_log.json", "w"), ensure_ascii=False, indent=2)

    print(f"[records] total day-level rows in window: {len(all_records)}", file=sys.stderr)

    # write tidy CSV
    fieldnames = ["ticker", "date", "mag_pct", "fwd5", "fwd20", "fwd40"]
    with open(f"{OUTDIR}/daylevel_records.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in all_records:
            w.writerow(r)

    # ---------------- aggregation ----------------
    def bucket_of(mag):
        if mag <= 0:
            return None  # not a breakout day
        if mag <= 3:
            return "b1_0_3pct"
        if mag <= 8:
            return "b2_3_8pct"
        if mag <= 15:
            return "b3_8_15pct"
        return "b4_gt15pct"

    groups = {
        "b1_0_3pct": [], "b2_3_8pct": [], "b3_8_15pct": [], "b4_gt15pct": [],
        "ctrl_baseline_all_days": [], "ctrl_near_miss_-8_0pct": [],
    }
    outlier_excluded = {5: 0, 20: 0, 40: 0}

    for r in all_records:
        groups["ctrl_baseline_all_days"].append(r)
        mag = r["mag_pct"]
        if -8.0 <= mag <= 0.0:
            groups["ctrl_near_miss_-8_0pct"].append(r)
        b = bucket_of(mag)
        if b:
            groups[b].append(r)
        for hz in HORIZONS:
            if r.get(f"fwd{hz}_excluded_outlier"):
                outlier_excluded[hz] += 1

    def stats_for(rows, hz):
        vals = [r[f"fwd{hz}"] for r in rows if r.get(f"fwd{hz}") is not None]
        n = len(vals)
        if n == 0:
            return {"n": 0}
        vals_sorted = sorted(vals)
        def pct(p):
            idx = min(len(vals_sorted) - 1, max(0, int(round(p * (len(vals_sorted) - 1)))))
            return vals_sorted[idx]
        return {
            "n": n,
            "mean_pct": round(st.mean(vals) * 100, 3),
            "median_pct": round(st.median(vals) * 100, 3),
            "win_rate_pct": round(sum(1 for v in vals if v > 0) / n * 100, 2),
            "p5_pct": round(pct(0.05) * 100, 3),
            "p95_pct": round(pct(0.95) * 100, 3),
            "stdev_pct": round(st.pstdev(vals) * 100, 3) if n > 1 else None,
        }

    result = {}
    for gname, rows in groups.items():
        result[gname] = {"n_signal_days": len(rows)}
        for hz in HORIZONS:
            result[gname][f"fwd{hz}"] = stats_for(rows, hz)

    meta = {
        "run_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "universe_total_incl_BJ": universe_total,
        "BJ_excluded_no_sina_coverage": bj_excluded_n,
        "SH_SZ_target_tickers": len(sh_sz),
        "fetch_ok": fetch_log["ok"],
        "fetch_fail": fetch_log["fail"],
        "total_daylevel_rows_in_window": len(all_records),
        "outlier_excluded_by_horizon": outlier_excluded,
        "window_start": WINDOW_START,
        "window_end_requested": WINDOW_END,
        "price_data_through": FETCH_END,
        "fetch_elapsed_sec": round(fetch_elapsed, 1),
        "signal_definition": "close[i] > max(high[i-20:i]) (20 prior trading days, unadjusted prices)",
        "note": "fwdN is None/censored when i+N trading day hasn't occurred yet as of 2026-08-24 for that ticker's own bar sequence -- n shrinks with horizon by construction, not by filtering",
    }
    json.dump({"meta": meta, "buckets": result}, open(f"{OUTDIR}/bucket_stats.json", "w"),
               ensure_ascii=False, indent=2)

    # flat CSV
    with open(f"{OUTDIR}/bucket_stats.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bucket", "n_signal_days", "horizon", "n", "mean_pct", "median_pct", "win_rate_pct", "p5_pct", "p95_pct", "stdev_pct"])
        for gname, rows in groups.items():
            for hz in HORIZONS:
                s = result[gname][f"fwd{hz}"]
                w.writerow([gname, len(rows), hz, s.get("n", 0), s.get("mean_pct"), s.get("median_pct"),
                            s.get("win_rate_pct"), s.get("p5_pct"), s.get("p95_pct"), s.get("stdev_pct")])

    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[done] total elapsed={time.time()-t_start:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
