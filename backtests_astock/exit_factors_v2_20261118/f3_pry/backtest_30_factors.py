#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
backtest_30_factors.py
Run marginal exit-factor evaluation across all 27 cross-strategy holding-period factors (XF01..XF27)
plus synthesis models (XF28..XF30) on P165, P150, P140, and P000 in both IS and OOS.
Strictly uses _cache_feats_830.pkl (zero lookahead) and produces factor_30_marginal_table.csv.
"""
import os, sys, json, pickle, time
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
S3_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s3_pry_exit"
F3_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry"
for d in (S3_DIR, F3_DIR):
    if d not in sys.path:
        sys.path.insert(0, d)

import run_exit_scan as base

COST = 0.0020


def sim_dynamic(d, p0, buy_px, r, ft, spec):
    """
    Generalized strictly-PIT holding-period simulator.
    spec keys:
      base_mode: 'DecD_4d' or 'X10_v1'
      max_h: int (default 4)
      preopen_cut_fn(off, st, ft, r) -> bool (exit at T+off 09:25 open)
      tp_sched_fn(off, st, ft, r, base_tp) -> float or None
      eod_cut_fn(off, k, st, ft, d, p0, buy_px, end_p) -> bool (exit at T+off 14:55 close)
      zt_judge_fn(off, st, ft, r) -> 'relay' | 'next_open' | 'eod_sell'
      disable_default_eod_cut_fn(off, st, ft, r) -> bool
      t1_ratio: float or None (default 0.985 for DecD_4d)
      t2_ratio: float or None (default 0.985 for DecD_4d)
    """
    L = len(d["dts"])
    if p0 + 1 >= L or buy_px <= 0:
        return np.nan, "", 0, 1455, "invalid"
    o, h, c, dt_px, is_zt, is_yz_dt, adjf = (
        d["open"], d["high"], d["close"], d["dt_px"], d["is_zt"], d["is_yizi_dt"], d["adjf"]
    )
    base_mode = spec.get("base_mode", "DecD_4d")
    max_h = spec.get("max_h", 4)
    zt_judge_fn = spec.get("zt_judge_fn")

    # D0 limit-up
    if is_zt[p0]:
        if zt_judge_fn is not None:
            act = zt_judge_fn(0, ft["steps"].get(0, {}), ft, r)
            if act == "next_open":
                ps = base.first_sellable_day(d, p0 + 1)
                s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
                rv, ed, hd = base.ret_from_px(d, p0, ps, s_px, buy_px)
                return rv, ed, hd, 925, "D0烂板次日开盘出"
        rv, ed, hd = base.hold_zt_relay(d, p0, p0, buy_px)
        return rv, ed, hd, 1455, "D0涨停连板"

    # D0 limit-down reseal -> T+1 09:25 cut
    if c[p0] <= dt_px[p0] + 0.005:
        ps = base.first_sellable_day(d, p0 + 1)
        s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
        rv, ed, hd = base.ret_from_px(d, p0, ps, s_px, buy_px)
        return rv, ed, hd, 925, "D0回封跌停T+1开盘砍"

    dyn_tp = float(np.clip(0.45 * abs(r.prev_ret10), 0.06, 0.16))
    if base_mode == "X10_v1":
        base_sched = [dyn_tp, dyn_tp, dyn_tp, dyn_tp]
        zt_relay_default = False
        t1_r_def, t2_r_def = None, None
    else:
        base_sched = [None, dyn_tp, 0.05, 0.02]
        zt_relay_default = True
        t1_r_def = spec.get("t1_ratio", 0.985)
        t2_r_def = spec.get("t2_ratio", 0.985)

    end_p = min(L - 1, p0 + max_h)
    preopen_cut_fn = spec.get("preopen_cut_fn")
    tp_sched_fn = spec.get("tp_sched_fn")
    eod_cut_fn = spec.get("eod_cut_fn")
    dis_eod_fn = spec.get("disable_default_eod_cut_fn")

    for off, k in enumerate(range(p0 + 1, end_p + 1), start=1):
        if is_yz_dt[k]:
            continue
        st = ft["steps"].get(off, {})

        # 1. 09:25 pre-open / auction exit trigger
        if preopen_cut_fn is not None and preopen_cut_fn(off, st, ft, r):
            if o[k] > dt_px[k] + 0.005:
                rv, ed, hd = base.ret_from_px(d, p0, k, o[k], buy_px)
                return rv, ed, hd, 925, f"T+{off}早盘因子砍仓"
            ps = base.first_sellable_day(d, k)
            s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
            rv, ed, hd = base.ret_from_px(d, p0, ps, s_px, buy_px)
            return rv, ed, hd, 925, f"T+{off}早盘因子顺延砍仓"

        # 2. Pre-market limit TP order
        btp = base_sched[min(off - 1, len(base_sched) - 1)]
        tp_r = tp_sched_fn(off, st, ft, r, btp) if tp_sched_fn is not None else btp
        if tp_r is not None:
            tp_px = round(buy_px * (1.0 + tp_r) * (adjf[p0] / adjf[k]), 2)
            if o[k] >= tp_px:
                rv, ed, hd = base.ret_from_px(d, p0, k, o[k], buy_px)
                return rv, ed, hd, 925, f"T+{off}高开越线止盈"
            if h[k] >= tp_px:
                rv, ed, hd = base.ret_from_px(d, p0, k, tp_px, buy_px)
                return rv, ed, hd, 1455, f"T+{off}盘中触及限价止盈"

        # 3. Unfilled ZT handling
        if is_zt[k]:
            if zt_judge_fn is not None:
                act = zt_judge_fn(off, st, ft, r)
                if act == "next_open" and k + 1 < L:
                    ps = base.first_sellable_day(d, k + 1)
                    s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
                    rv, ed, hd = base.ret_from_px(d, p0, ps, s_px, buy_px)
                    return rv, ed, hd, 925, f"T+{off}烂板次日开盘兑现"
                elif act == "relay":
                    rv, ed, hd = base.hold_zt_relay(d, p0, k, buy_px)
                    return rv, ed, hd, 1455, f"T+{off}紧封连板"
            elif zt_relay_default:
                rv, ed, hd = base.hold_zt_relay(d, p0, k, buy_px)
                return rv, ed, hd, 1455, f"T+{off}涨停转连板"

        # 4. 14:55 EOD cut rules (only if k < end_p)
        if k < end_p:
            cut_eod = False
            if eod_cut_fn is not None and eod_cut_fn(off, k, st, ft, d, p0, buy_px, end_p):
                cut_eod = True
            allow_def = True if dis_eod_fn is None else (not dis_eod_fn(off, st, ft, r))
            if (not cut_eod) and allow_def:
                ck = c[k] * adjf[k] / adjf[p0]
                cp = c[k - 1] * adjf[k - 1] / adjf[p0]
                thr = t1_r_def if off == 1 else t2_r_def
                if thr is not None and ck < cp * thr:
                    cut_eod = True
            if cut_eod:
                if c[k] > dt_px[k] + 0.005:
                    rv, ed, hd = base.ret_from_px(d, p0, k, c[k], buy_px)
                    return rv, ed, hd, 1455, f"T+{off}尾盘清仓"
                ps = base.first_sellable_day(d, k + 1)
                s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
                rv, ed, hd = base.ret_from_px(d, p0, ps, s_px, buy_px)
                return rv, ed, hd, 925, f"T+{off}跌停顺延清仓"

    ps = base.first_sellable_day(d, end_p)
    if zt_relay_default and is_zt[ps]:
        rv, ed, hd = base.hold_zt_relay(d, p0, ps, buy_px)
        return rv, ed, hd, 1455, f"T+{max_h}涨停接力"
    rv, ed, hd = base.ret_from_px(d, p0, ps, c[ps], buy_px)
    return rv, ed, hd, 1455, f"T+{max_h}到期清仓"


def run_spec(sub, cb, feats, spec):
    n = len(sub)
    rets = np.full(n, np.nan, dtype=float)
    edts = np.full(n, "", dtype=object)
    hlds = np.zeros(n, dtype=int)
    ehms = np.zeros(n, dtype=int)
    rsns = np.full(n, "", dtype=object)
    for i, r in enumerate(sub.itertuples(index=False)):
        rv, ed, hd, eh, rsn = sim_dynamic(cb[r.c6], int(r.p0), float(r.buy_px), r, feats[i], spec)
        rets[i], edts[i], hlds[i], ehms[i], rsns[i] = rv, ed, hd, eh, rsn
    return rets, edts, hlds, ehms, rsns


def quick_metrics(sub, rets, edts, hlds, ref_rets=None):
    out = {}
    changed = int(np.sum(np.abs(rets - ref_rets) > 1e-6)) if ref_rets is not None else 0
    out["changed_all"] = changed
    for th in [165, 150, 140, 0]:
        ev = base.eval_variant(sub, rets, edts, hlds, th)
        m = sub["score"].values >= th
        ch_p = int(np.sum(np.abs(rets[m] - ref_rets[m]) > 1e-6)) if ref_rets is not None else 0
        out[f"P{th:03d}"] = {
            "ch": ch_p,
            "ALL_ss_nav": ev["ALL"]["ss"]["nav"],
            "ALL_ss_wr": ev["ALL"]["ss"]["wr"],
            "ALL_ss_mdd": ev["ALL"]["ss"]["mdd"],
            "ALL_ss_h": ev["ALL"]["ss"]["avg_hold"],
            "IS_ss_nav": ev["IS"]["ss"]["nav"],
            "OOS_ss_nav": ev["OOS"]["ss"]["nav"],
            "IS_deq_nav": ev["IS"]["deq"]["nav"],
            "OOS_deq_nav": ev["OOS"]["deq"]["nav"],
            "ALL_deq_nav": ev["ALL"]["deq"]["nav"],
        }
    return out
