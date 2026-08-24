#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复用已缓存的 full_a_disclosed 财务信号(kfjlr_flip_signals_full_a_disclosed.csv),
只重跑价格/前向收益部分(用切源后的sina fetch_price), 避免重打THS财务接口浪费时间。
说明: mini_racer(sina源解密用的JS VM)非线程安全, 用ThreadPoolExecutor并发跑
ak.stock_zh_a_daily会直接crash整个进程(实测复现: FATAL partition_address_space.cc
Check failed: !IsConfigurablePoolInitialized), 改用ProcessPoolExecutor(进程隔离,
每个进程各自的V8 isolate不冲突), 且必须放在 __main__ guard 里(macOS默认spawn)。"""
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

import backtest_kfjlr_flip as B

OUTDIR = B.OUTDIR
MODE = "full_a_disclosed"


def process_one(row):
    code = row["code"]
    pdf = B.fetch_price(code)
    fr = B.forward_returns(pdf, row["signal_date"])
    rec = dict(row)
    if fr is None:
        rec["price_ok"] = False
        return rec
    rec["price_ok"] = True
    rec.update(fr)
    return rec


def group_stats(df, horizon):
    col = f"ret_{horizon}d"
    if col not in df.columns:
        return {"n": 0, "mean": None, "median": None, "winrate": None, "p5": None, "p95": None}
    s = df[col].dropna()
    n = len(s)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "winrate": None, "p5": None, "p95": None}
    return {
        "n": int(n), "mean": float(s.mean()), "median": float(s.median()),
        "winrate": float((s > 0).mean()), "p5": float(np.percentile(s, 5)),
        "p95": float(np.percentile(s, 95)),
    }


def fmtpct(x):
    return "N/A" if x is None else f"{x*100:+.2f}%"


def main():
    sig_df = pd.read_csv(f"{OUTDIR}/kfjlr_flip_signals_{MODE}.csv", dtype={"code": str})
    sig_df["code"] = sig_df["code"].str.zfill(6)
    print(f"loaded {len(sig_df)} signals", flush=True)

    t0 = time.time()
    rows = sig_df.to_dict("records")
    results = []
    with ProcessPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(process_one, r): r["code"] for r in rows}
        for i, fut in enumerate(as_completed(futs)):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({"code": futs[fut], "price_ok": False, "err": str(e)})
            if (i + 1) % 100 == 0:
                print(f"  {i+1}/{len(rows)}  elapsed={time.time()-t0:.1f}s", flush=True)

    ret_df = pd.DataFrame(results)
    ret_df.to_csv(f"{OUTDIR}/kfjlr_flip_returns_{MODE}.csv", index=False, encoding="utf-8-sig")
    print(f"done. price_ok={ret_df['price_ok'].sum()}/{len(ret_df)} elapsed={time.time()-t0:.1f}s", flush=True)

    summary = {}
    for h in (5, 20, 40):
        summary[f"{h}d"] = {
            "treatment": group_stats(ret_df[ret_df["group"] == "treatment_turn_negative"], h),
            "control": group_stats(ret_df[ret_df["group"] == "control_stay_positive"], h),
        }
    with open(f"{OUTDIR}/kfjlr_flip_summary_{MODE}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    for h in (5, 20, 40):
        t = summary[f"{h}d"]["treatment"]
        c = summary[f"{h}d"]["control"]
        print(f"\n--- {h}日 --- treat n={t['n']} mean={fmtpct(t['mean'])} median={fmtpct(t['median'])} "
              f"win={fmtpct(t['winrate'])} p5~p95=[{fmtpct(t['p5'])},{fmtpct(t['p95'])}]")
        print(f"           ctrl  n={c['n']} mean={fmtpct(c['mean'])} median={fmtpct(c['median'])} "
              f"win={fmtpct(c['winrate'])} p5~p95=[{fmtpct(c['p5'])},{fmtpct(c['p95'])}]")
        if t["n"] > 0 and c["n"] > 0:
            print(f"  diff mean={fmtpct(t['mean']-c['mean'])}  diff median={fmtpct(t['median']-c['median'])}")
            overlap = not (t["p95"] < c["p5"] or c["p95"] < t["p5"])
            print(f"  p5-p95重叠: {overlap}")

    print("\n反例(treatment组20日仍正收益, 按大小排序前15):")
    if "ret_20d" in ret_df.columns:
        t20 = ret_df[(ret_df["group"] == "treatment_turn_negative") & ret_df["ret_20d"].notna()]
        ctr = t20[t20["ret_20d"] > 0].sort_values("ret_20d", ascending=False)
        if len(ctr) > 0:
            print(ctr[["code", "curr_growth", "signal_date", "ret_20d"]].head(15).to_string(index=False))
        else:
            print("  (0个反例)")
    else:
        print("  (无ret_20d列)")

    print("\n反例(treatment组5日仍正收益, 按大小排序前15):")
    if "ret_5d" in ret_df.columns:
        t5 = ret_df[(ret_df["group"] == "treatment_turn_negative") & ret_df["ret_5d"].notna()]
        ctr5 = t5[t5["ret_5d"] > 0].sort_values("ret_5d", ascending=False)
        if len(ctr5) > 0:
            print(ctr5[["code", "curr_growth", "signal_date", "ret_5d"]].head(15).to_string(index=False))
        else:
            print("  (0个反例)")
    else:
        print("  (无ret_5d列)")


if __name__ == "__main__":
    main()
