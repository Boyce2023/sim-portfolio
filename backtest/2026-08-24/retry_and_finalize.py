#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重跑首轮THS失败的210只(rate-limit已过,验证可恢复),补全后重新分类+算收益+汇总。"""
import akshare as ak
import pandas as pd
import numpy as np
import time
import json
import os

WORKDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
WINDOW_START = "2026-06-24"
WINDOW_END = "2026-08-24"
PERIODS = ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]


def pct_to_float(x):
    if x is None:
        return np.nan
    if isinstance(x, float) and np.isnan(x):
        return np.nan
    s = str(x).strip()
    if s in ("", "--", "nan", "None"):
        return np.nan
    s = s.replace("%", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return np.nan


def fetch_ths_kfjlr(code):
    try:
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        df = df[["报告期", "扣非净利润同比增长率"]].copy()
        df["报告期"] = df["报告期"].astype(str)
        out = {}
        for p in PERIODS:
            row = df[df["报告期"] == p]
            out[p] = pct_to_float(row["扣非净利润同比增长率"].values[0]) if len(row) == 1 else np.nan
        return code, out, None
    except Exception as e:
        return code, None, str(e)


def fetch_price(code_6):
    prefix = "sh" if code_6[0] in ("6", "9") else ("bj" if code_6[0] in ("8", "4") else "sz")
    sym = prefix + code_6
    try:
        df = ak.stock_zh_a_daily(symbol=sym, start_date="20260601", end_date="20260824", adjust="qfq")
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return code_6, df, None
    except Exception as e:
        return code_6, None, str(e)


def forward_return(price_df, signal_date_str, n_days):
    if price_df is None or len(price_df) == 0:
        return np.nan
    sig = pd.Timestamp(signal_date_str)
    idx = price_df.index[price_df["date"] >= sig]
    if len(idx) == 0:
        return np.nan
    i0 = idx[0]
    i1 = i0 + n_days
    if i1 >= len(price_df):
        return np.nan
    p0 = price_df.loc[i0, "close"]
    p1 = price_df.loc[i1, "close"]
    if p0 is None or p0 == 0 or pd.isna(p0):
        return np.nan
    return (p1 / p0 - 1.0) * 100.0


def summarize(returns):
    arr = np.array([r for r in returns if not (r is None or (isinstance(r, float) and np.isnan(r)))], dtype=float)
    n = len(arr)
    if n == 0:
        return dict(n=0, mean=np.nan, median=np.nan, win_rate=np.nan, p5=np.nan, p95=np.nan)
    return dict(n=n, mean=round(float(np.mean(arr)), 2), median=round(float(np.median(arr)), 2),
                win_rate=round(float((arr > 0).mean()) * 100, 1),
                p5=round(float(np.percentile(arr, 5)), 2), p95=round(float(np.percentile(arr, 95)), 2))


def main():
    t0 = time.time()
    decel_proxy = pd.read_csv(os.path.join(WORKDIR, "proxy_decel_candidates.csv"), dtype={"code": str})
    accel_proxy = pd.read_csv(os.path.join(WORKDIR, "proxy_accel_candidates.csv"), dtype={"code": str})
    candidates = pd.concat([decel_proxy, accel_proxy], ignore_index=True).drop_duplicates(subset=["code"])
    codes = candidates["code"].tolist()
    print(f"[候选] 合计{len(codes)} (decel_proxy={len(decel_proxy)} accel_proxy={len(accel_proxy)})")

    kfjlr = {}
    errors = {}
    for i, c in enumerate(codes):
        code, out, err = fetch_ths_kfjlr(c)
        if err:
            errors[code] = err
        else:
            kfjlr[code] = out
        if (i + 1) % 50 == 0:
            print(f"  ...THS进度 {i+1}/{len(codes)} (耗时{time.time()-t0:.0f}s) 成功={len(kfjlr)}")
    print(f"[THS扣非-第一轮] 成功={len(kfjlr)} 失败={len(errors)}")

    if errors:
        retry_codes = list(errors.keys())
        print(f"[THS扣非-重试] {len(retry_codes)}个")
        still_fail = {}
        for i, c in enumerate(retry_codes):
            code, out, err = fetch_ths_kfjlr(c)
            if err:
                still_fail[code] = err
            else:
                kfjlr[code] = out
            if (i + 1) % 50 == 0:
                print(f"  ...重试进度 {i+1}/{len(retry_codes)} (耗时{time.time()-t0:.0f}s)")
        errors = still_fail
    print(f"[THS扣非-最终] 成功={len(kfjlr)} 失败={len(errors)}")

    rows = []
    for code in codes:
        if code not in kfjlr:
            continue
        d = kfjlr[code]
        g_ann25, g_q1, g_h1, g_q3_25 = d.get("2025-12-31"), d.get("2026-03-31"), d.get("2026-06-30"), d.get("2025-09-30")
        if any(pd.isna(x) for x in [g_ann25, g_q1, g_h1]):
            continue
        name = candidates.loc[candidates["code"] == code, "name"].values[0]
        is_decel = (g_ann25 > 0) and (g_q1 > 0) and (g_h1 > 0) and (g_ann25 > g_q1) and (g_q1 > g_h1)
        is_accel = (g_ann25 > 0) and (g_q1 > 0) and (g_h1 > 0) and (g_ann25 < g_q1) and (g_q1 < g_h1)
        if not (is_decel or is_accel):
            continue
        rows.append(dict(code=code, name=name, g_q3_25=g_q3_25, g_ann25=g_ann25, g_q1_26=g_q1, g_h1_26=g_h1,
                          group="decel" if is_decel else "accel", high_growth=(max(g_ann25, g_q1) >= 50.0)))
    sig_df = pd.DataFrame(rows)
    print(f"[真实扣非分类] decel={len(sig_df[sig_df.group=='decel']) if len(sig_df) else 0} "
          f"accel={len(sig_df[sig_df.group=='accel']) if len(sig_df) else 0}")

    xmwy_raw = kfjlr.get("600549")
    print(f"[厦门钨业600549专项核对] THS数据: {xmwy_raw} -> "
          f"{'不在候选池(净利润代理法预筛就没通过monotonic条件)' if '600549' not in codes else ''}")

    yjbb_h1 = pd.read_csv(os.path.join(WORKDIR, "yjbb_20260630.csv"), dtype={"股票代码": str})
    yjbb_h1["股票代码"] = yjbb_h1["股票代码"].str.zfill(6)
    ann_date_map = dict(zip(yjbb_h1["股票代码"], yjbb_h1["最新公告日期"]))
    sig_df["ann_date"] = sig_df["code"].map(ann_date_map)
    sig_df = sig_df.dropna(subset=["ann_date"])
    sig_df = sig_df[(sig_df.ann_date >= WINDOW_START) & (sig_df.ann_date <= WINDOW_END)]
    print(f"[窗口过滤后] {len(sig_df)}")

    price_cache = {}
    price_err = {}
    for c in sig_df["code"].tolist():
        code, df, err = fetch_price(c)
        if err:
            price_err[code] = err
        else:
            price_cache[code] = df
    print(f"[价格] 成功={len(price_cache)} 失败={len(price_err)}")

    for h in [5, 20, 40]:
        sig_df[f"ret_{h}d"] = [forward_return(price_cache.get(r["code"]), r["ann_date"], h) for _, r in sig_df.iterrows()]

    sig_df.to_csv(os.path.join(WORKDIR, "signal_results_full.csv"), index=False)

    result = {}
    for grp in ["decel", "accel"]:
        sub = sig_df[sig_df.group == grp]
        for h in [5, 20, 40]:
            result[f"{grp}_{h}d"] = summarize(sub[f"ret_{h}d"].tolist())
        result[f"{grp}_n_total"] = len(sub)
    hg = sig_df[(sig_df.group == "decel") & (sig_df.high_growth)]
    lg = sig_df[(sig_df.group == "decel") & (~sig_df.high_growth)]
    for h in [5, 20, 40]:
        result[f"hg_decel_{h}d"] = summarize(hg[f"ret_{h}d"].tolist())
        result[f"lg_decel_{h}d"] = summarize(lg[f"ret_{h}d"].tolist())
    result["hg_decel_n_total"] = len(hg)
    result["lg_decel_n_total"] = len(lg)

    print("\n========== 最终汇总 ==========")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n[decel明细]")
    print(sig_df[sig_df.group == "decel"][["code", "name", "ann_date", "g_ann25", "g_q1_26", "g_h1_26", "ret_5d", "ret_20d", "ret_40d"]].to_string())
    print("\n[accel明细]")
    print(sig_df[sig_df.group == "accel"][["code", "name", "ann_date", "g_ann25", "g_q1_26", "g_h1_26", "ret_5d", "ret_20d", "ret_40d"]].to_string())
    print(f"\n[耗时] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
