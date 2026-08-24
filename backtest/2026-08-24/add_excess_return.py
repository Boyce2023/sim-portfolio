#!/usr/bin/env python3
"""
第二步: 给已算好的个股前瞻收益加"超额收益"(相对上证指数sh000001同期), 目的是
剥离"整个动量/主题池同期集体回撤"这个regime因素, 单独检验裁决(reject/watch/probe)
本身是否有信息含量, 而不是被时间分布不均(reject组更集中在7月, watch/probe组8月占比更高)
的timing confound污染。
方法: 对每条已算出 anchor_trading_date + fwd_date_Xd 的记录, 在指数序列里查同一对日期
的收盘价算指数同期收益, excess = 个股收益 - 指数同期收益。
"""
import json
import akshare as ak
from collections import Counter

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
RESULT_PATH = f"{OUT_DIR}/reject_watch_probe_result.json"

d = json.load(open(RESULT_PATH))

idx_df = ak.stock_zh_a_hist_tx(symbol="sh000001", start_date="20260601", end_date="20260824", adjust="qfq")
idx_df["date"] = idx_df["date"].astype(str)
idx_close = dict(zip(idx_df["date"], idx_df["close"].astype(float)))
idx_dates_sorted = sorted(idx_close.keys())


def nearest_close(date_str):
    if date_str in idx_close:
        return idx_close[date_str]
    # 找最近的前一个交易日
    for dd in reversed(idx_dates_sorted):
        if dd <= date_str:
            return idx_close[dd]
    return None


HORIZONS = [5, 20, 40]
for r in d["all_records"]:
    if r.get("status") != "ok":
        continue
    base_idx_close = nearest_close(r["anchor_trading_date"])
    for h in HORIZONS:
        fwd_date = r.get(f"fwd_date_{h}d")
        stock_ret = r.get(f"ret_{h}d")
        if fwd_date is None or stock_ret is None or base_idx_close is None:
            r[f"excess_ret_{h}d"] = None
            continue
        fwd_idx_close = nearest_close(fwd_date)
        if fwd_idx_close is None:
            r[f"excess_ret_{h}d"] = None
            continue
        idx_ret = (fwd_idx_close / base_idx_close - 1.0) * 100.0
        r[f"excess_ret_{h}d"] = round(stock_ret - idx_ret, 2)


def pct(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    k = (len(vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(vals) - 1)
    if f == c:
        return vals[f]
    return vals[f] + (vals[c] - vals[f]) * (k - f)


def stats(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0}
    mean = sum(vals) / n
    s = sorted(vals)
    median = s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2
    win_rate = sum(1 for v in vals if v > 0) / n * 100
    return {
        "n": n,
        "mean_pct": round(mean, 2),
        "median_pct": round(median, 2),
        "win_rate_pct": round(win_rate, 1),
        "p5_pct": round(pct(vals, 0.05), 2),
        "p95_pct": round(pct(vals, 0.95), 2),
        "min_pct": round(min(vals), 2),
        "max_pct": round(max(vals), 2),
    }


groups = ["reject", "watch", "probe"]
excess_summary = {}
for g in groups:
    excess_summary[g] = {}
    for h in HORIZONS:
        vals = [
            r[f"excess_ret_{h}d"]
            for r in d["all_records"]
            if r.get("status") == "ok" and r["group"] == g and r.get(f"excess_ret_{h}d") is not None
        ]
        excess_summary[g][f"{h}d"] = stats(vals)

d["group_summary_excess_vs_index"] = excess_summary

# timing distribution per group (for confound disclosure)
timing = {}
for g in groups:
    months = [r["date"][:7] for r in d["all_records"] if r.get("status") == "ok" and r["group"] == g]
    timing[g] = dict(Counter(months))
d["meta"]["timing_distribution_by_month"] = timing

with open(RESULT_PATH, "w") as f:
    json.dump(d, f, ensure_ascii=False, indent=1)

print("超额收益(相对上证指数)分组统计:")
print(json.dumps(excess_summary, ensure_ascii=False, indent=1))
print("\n各组按月份的裁决数量分布(timing confound检查):")
print(json.dumps(timing, ensure_ascii=False, indent=1))
