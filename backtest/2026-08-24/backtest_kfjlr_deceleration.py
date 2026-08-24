#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证假设: 扣非增速"连续2期减速"(仍为正但斜率向下)是有效的降级信号
对照组: 连续两期扣非同比增速加速(仍为正)
数据源: akshare (yjbb_em批量净利润增速做预筛 + stock_financial_abstract_ths单股扣非增速精确取数
        + stock_zh_a_daily新浪源做前复权价格)
窗口: 2026-06-24 ~ 2026-08-24
铁律: 全部反例主动报告,n<30只作方向性提示不作结论
"""

import akshare as ak
import pandas as pd
import numpy as np
import time
import json
import traceback
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

WORKDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
WINDOW_START = "2026-06-24"
WINDOW_END = "2026-08-24"
TODAY = "2026-08-24"

PERIODS = ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]  # t-3..t


def pct_to_float(x):
    """'198.64%' -> 198.64 ; NaN/空/'--' -> np.nan"""
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
    """拉单只股票 stock_financial_abstract_ths, 提取PERIODS对应的 扣非净利润同比增长率"""
    try:
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        df = df[["报告期", "扣非净利润同比增长率"]].copy()
        df["报告期"] = df["报告期"].astype(str)
        out = {}
        for p in PERIODS:
            row = df[df["报告期"] == p]
            if len(row) == 1:
                out[p] = pct_to_float(row["扣非净利润同比增长率"].values[0])
            else:
                out[p] = np.nan
        return code, out, None
    except Exception as e:
        return code, None, str(e)


def fetch_price(code_6):
    """code_6: 6位代码(无sh/sz前缀); 返回按日期升序的价格df(前复权)"""
    prefix = "sh" if code_6[0] in ("6", "9") else ("bj" if code_6[0] == "8" or code_6[0] == "4" else "sz")
    sym = prefix + code_6
    try:
        df = ak.stock_zh_a_daily(symbol=sym, start_date="20260601", end_date="20260824", adjust="qfq")
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return code_6, df, None
    except Exception as e:
        return code_6, None, str(e)


def forward_return(price_df, signal_date_str, n_days):
    """signal_date_str: 'YYYY-MM-DD' 公告日. 从公告日当天收盘价(若非交易日取下一交易日)起算,
    向后n_days个交易日的收盘价, 算涨跌幅(%)。数据不足返回 np.nan。"""
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
    return dict(
        n=n,
        mean=round(float(np.mean(arr)), 2),
        median=round(float(np.median(arr)), 2),
        win_rate=round(float((arr > 0).mean()) * 100, 1),
        p5=round(float(np.percentile(arr, 5)), 2),
        p95=round(float(np.percentile(arr, 95)), 2),
    )


def main():
    t_start = time.time()
    log = []

    def LOG(msg):
        print(msg)
        log.append(msg)

    # ---------- Step 1: 读取预筛候选(已由前置探索生成,若不存在则现场重建) ----------
    import os
    proxy_path = os.path.join(WORKDIR, "merged_proxy_periods.csv")
    if not os.path.exists(proxy_path):
        raise RuntimeError("merged_proxy_periods.csv 不存在,需先跑批量yjbb_em预筛步骤")

    m = pd.read_csv(proxy_path, dtype={"code": str})
    decel_proxy = pd.read_csv(os.path.join(WORKDIR, "proxy_decel_candidates.csv"), dtype={"code": str})
    accel_proxy = pd.read_csv(os.path.join(WORKDIR, "proxy_accel_candidates.csv"), dtype={"code": str})
    candidates = pd.concat([decel_proxy, accel_proxy], ignore_index=True).drop_duplicates(subset=["code"])
    LOG(f"[预筛] 净利润增速代理法候选: decel={len(decel_proxy)} accel={len(accel_proxy)} 合计去重={len(candidates)}")

    codes = candidates["code"].tolist()

    # ---------- Step 2: 串行拉真实扣非净利润同比增长率(THS) ----------
    # 实测: 多线程/多进程(含fork/spawn)在本机环境下都会触发native crash
    # (mini_racer PartitionAlloc reinit assertion / macOS objc fork-safety abort)。
    # 单进程单线程顺序调用实测20只股票0 crash、0.46s/只,故改为纯串行,牺牲并发换稳定。
    kfjlr = {}
    errors = {}
    for i, c in enumerate(codes):
        code, out, err = fetch_ths_kfjlr(c)
        if err:
            errors[code] = err
        else:
            kfjlr[code] = out
        if (i + 1) % 40 == 0:
            LOG(f"  ...THS进度 {i+1}/{len(codes)} (耗时{time.time()-t_start:.0f}s)")
    LOG(f"[THS扣非] 成功={len(kfjlr)} 失败={len(errors)}")
    if errors:
        LOG(f"[THS扣非] 失败样例: {list(errors.items())[:5]}")

    # ---------- Step 3: 用真实扣非数据重新分类(不采信代理法结果) ----------
    rows = []
    for code in codes:
        if code not in kfjlr:
            continue
        d = kfjlr[code]
        g_ann25 = d.get("2025-12-31")
        g_q1 = d.get("2026-03-31")
        g_h1 = d.get("2026-06-30")
        g_q3_25 = d.get("2025-09-30")
        if any(pd.isna(x) for x in [g_ann25, g_q1, g_h1]):
            continue
        name = candidates.loc[candidates["code"] == code, "name"].values[0]
        is_decel = (g_ann25 > 0) and (g_q1 > 0) and (g_h1 > 0) and (g_ann25 > g_q1) and (g_q1 > g_h1)
        is_accel = (g_ann25 > 0) and (g_q1 > 0) and (g_h1 > 0) and (g_ann25 < g_q1) and (g_q1 < g_h1)
        if not (is_decel or is_accel):
            continue
        rows.append(dict(
            code=code, name=name,
            g_q3_25=g_q3_25, g_ann25=g_ann25, g_q1_26=g_q1, g_h1_26=g_h1,
            group="decel" if is_decel else "accel",
            high_growth=(max(g_ann25, g_q1) >= 50.0),
        ))
    sig_df = pd.DataFrame(rows)
    LOG(f"[真实扣非分类] decel={len(sig_df[sig_df.group=='decel'])} "
        f"accel={len(sig_df[sig_df.group=='accel'])} (代理法命中后经真实扣非二次验证)")

    # 厦门钨业 专项核对
    xmwy = sig_df[sig_df.code == "600549"]
    if len(xmwy) == 0:
        raw = kfjlr.get("600549")
        LOG(f"[厦门钨业600549专项核对] 未通过严格'连续两期下降'分类。原始扣非增速序列: {raw}")
    else:
        LOG(f"[厦门钨业600549专项核对] 通过分类, 详情: {xmwy.to_dict('records')}")

    # ---------- Step 4: 拿H1'26公告日期(用EM yjbb batch数据) ----------
    yjbb_h1 = pd.read_csv(os.path.join(WORKDIR, "yjbb_20260630.csv"), dtype={"股票代码": str})
    yjbb_h1["股票代码"] = yjbb_h1["股票代码"].str.zfill(6)
    ann_date_map = dict(zip(yjbb_h1["股票代码"], yjbb_h1["最新公告日期"]))
    sig_df["ann_date"] = sig_df["code"].map(ann_date_map)
    before_dropna = len(sig_df)
    sig_df = sig_df.dropna(subset=["ann_date"])
    LOG(f"[公告日期匹配] {before_dropna} -> {len(sig_df)} (丢失{before_dropna-len(sig_df)}个无H1公告日期)")

    in_window = sig_df[(sig_df.ann_date >= WINDOW_START) & (sig_df.ann_date <= WINDOW_END)]
    LOG(f"[窗口过滤] 公告日期落在{WINDOW_START}~{WINDOW_END}内: {len(in_window)}/{len(sig_df)}")
    sig_df = in_window

    # ---------- Step 5: 串行拉价格(同样规避并发导致的native crash) ----------
    price_cache = {}
    price_err = {}
    for c in sig_df["code"].tolist():
        code, df, err = fetch_price(c)
        if err:
            price_err[code] = err
        else:
            price_cache[code] = df
    LOG(f"[价格数据] 成功={len(price_cache)} 失败={len(price_err)}")
    if price_err:
        LOG(f"[价格数据] 失败样例: {list(price_err.items())[:5]}")

    # ---------- Step 6: 算前瞻收益 ----------
    for h in [5, 20, 40]:
        col = f"ret_{h}d"
        vals = []
        for _, r in sig_df.iterrows():
            pdf = price_cache.get(r["code"])
            v = forward_return(pdf, r["ann_date"], h)
            vals.append(v)
        sig_df[col] = vals

    sig_df.to_csv(os.path.join(WORKDIR, "signal_results_full.csv"), index=False)

    # ---------- Step 7: 汇总统计 ----------
    result = {}
    for grp in ["decel", "accel"]:
        sub = sig_df[sig_df.group == grp]
        for h in [5, 20, 40]:
            result[f"{grp}_{h}d"] = summarize(sub[f"ret_{h}d"].tolist())
        result[f"{grp}_n_total"] = len(sub)

    # 关键子集: 高增速(>=50%)但在减速
    hg_decel = sig_df[(sig_df.group == "decel") & (sig_df.high_growth)]
    lg_decel = sig_df[(sig_df.group == "decel") & (~sig_df.high_growth)]
    for h in [5, 20, 40]:
        result[f"hg_decel_{h}d"] = summarize(hg_decel[f"ret_{h}d"].tolist())
        result[f"lg_decel_{h}d"] = summarize(lg_decel[f"ret_{h}d"].tolist())
    result["hg_decel_n_total"] = len(hg_decel)
    result["lg_decel_n_total"] = len(lg_decel)

    LOG("\n========== 汇总结果 ==========")
    LOG(json.dumps(result, ensure_ascii=False, indent=2))

    LOG(f"\n[样本股票明细] decel组:\n{sig_df[sig_df.group=='decel'][['code','name','g_ann25','g_q1_26','g_h1_26','ret_5d','ret_20d','ret_40d']].to_string()}")
    LOG(f"\n[样本股票明细] accel组:\n{sig_df[sig_df.group=='accel'][['code','name','g_ann25','g_q1_26','g_h1_26','ret_5d','ret_20d','ret_40d']].to_string()}")

    with open(os.path.join(WORKDIR, "backtest_log.txt"), "w") as f:
        f.write("\n".join(log))

    LOG(f"\n[耗时] {time.time()-t_start:.1f}s")
    return result, sig_df


if __name__ == "__main__":
    main()
