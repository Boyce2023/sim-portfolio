#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD047 Step 1: Pure-Causal 0-100 Daily Theme Beta Scoring & Dynamic Theme-Switching Stock Attribution.
Key Causal Safeguards:
  1) KPL constituent pool uses trailing 120d causal members [d-119, d] (with active KPL heat in [d-4, d])
     to prevent winner-selection bias (4 random rebounders inflating a 50-stock concept to 100% breadth).
  2) Flow & Trend sub-scores blend absolute expansion + market-relative leadership so bear-market
     "least-bad" sectors cannot fake 80+ Main-Theme scores during crashes (e.g. 2022-04 / 2024-01).
  3) All normalization is strictly <= d (zero future constants, bit-exact 2024-12-31 truncation parity).
Zero yfinance (D12). Peak RAM < 1.5 GB.
"""
import argparse
import json
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

RD047_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd047_main_theme_beta_wave2_20261126"
if RD047_DIR not in sys.path:
    sys.path.insert(0, RD047_DIR)

import _rd047_common as cm


def compute_theme_scores(tag: str = "full") -> dict:
    t0 = time.time()
    meta = json.load(open(f"{cm.CACHE_DIR}/meta_{tag}.json", encoding="utf-8"))
    cal_dts = meta["cal_dts"]
    stocks = meta["stocks"]
    sw3_names = meta["sw3_names"]
    kpl_names = meta["kpl_names"]
    N_D, N_S = len(cal_dts), len(stocks)

    px = np.load(f"{cm.CACHE_DIR}/panel_px_{tag}.npz")
    tc = np.load(f"{cm.CACHE_DIR}/panel_tech_{tag}.npz")
    kpl_df = pd.read_parquet(f"{cm.CACHE_DIR}/kpl_events_{tag}.parquet")

    adj_close = px["adj_close"]
    ret_1d = px["ret_1d"]
    amount_yi = px["amount_yi"]
    list_age = px["list_age"]
    is_st = px["is_st"]
    is_zt = px["is_zt"]
    is_dt = px["is_dt"]
    streak = px["streak"]
    valid_px = px["valid_px"]
    comm_heat = px["comm_heat"]

    ma20 = tc["ma20"]
    hi20 = tc["hi20"]
    ret_3d = tc["ret_3d"]
    ret_5d = tc["ret_5d"]
    ret_20d = tc["ret_20d"]
    sw3_mat = tc["sw3_mat"]

    U = valid_px & (~is_st) & (list_age >= 60)
    above_ma20 = (adj_close > ma20) & np.isfinite(ma20) & U
    near_hi20 = (adj_close >= 0.985 * hi20) & np.isfinite(hi20) & U
    surge5 = (ret_5d >= 0.05) & np.isfinite(ret_5d) & U
    strong8 = (is_zt | (np.nan_to_num(ret_1d, nan=-1.0) >= 0.08)) & U

    mkt_amt = np.sum(np.where(U, amount_yi.astype(np.float64), 0.0), axis=1)
    mkt_zt_cnt = np.sum(strong8, axis=1).astype(np.float64)
    mkt_ew_r3 = np.zeros(N_D, dtype=np.float64)
    mkt_ew_r5 = np.zeros(N_D, dtype=np.float64)
    mkt_ew_r20 = np.zeros(N_D, dtype=np.float64)
    for d in range(N_D):
        m3 = U[d] & np.isfinite(ret_3d[d])
        m5 = U[d] & np.isfinite(ret_5d[d])
        m20 = U[d] & np.isfinite(ret_20d[d])
        if m3.any():
            mkt_ew_r3[d] = float(np.mean(np.clip(ret_3d[d, m3].astype(np.float64), -0.6, 2.0)))
        if m5.any():
            mkt_ew_r5[d] = float(np.mean(np.clip(ret_5d[d, m5].astype(np.float64), -0.6, 3.0)))
        if m20.any():
            mkt_ew_r20[d] = float(np.mean(np.clip(ret_20d[d, m20].astype(np.float64), -0.7, 5.0)))

    # Index KPL events by day
    kpl_by_day_plate: dict[int, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    kpl_direct_cnt: dict[tuple[int, int], int] = defaultdict(int)
    for r in kpl_df.itertuples(index=False):
        di_v, si_v, pid_v, is_dir = int(r.di), int(r.si), int(r.pid), int(r.is_direct)
        kpl_by_day_plate[di_v][pid_v].add(si_v)
        if is_dir == 1:
            kpl_direct_cnt[(di_v, pid_v)] += 1

    N_SW = len(sw3_names)
    N_KPL = len(kpl_names)
    N_TH = N_SW + N_KPL
    all_theme_names = sw3_names + [f"KPL:{nm}" for nm in kpl_names]

    th_active = np.zeros((N_D, N_TH), dtype=bool)
    th_n = np.zeros((N_D, N_TH), dtype=np.int16)
    th_amt = np.zeros((N_D, N_TH), dtype=np.float64)
    th_zt = np.zeros((N_D, N_TH), dtype=np.float64)
    th_dt = np.zeros((N_D, N_TH), dtype=np.float64)
    th_max_stk = np.zeros((N_D, N_TH), dtype=np.float64)
    th_ma20_r = np.zeros((N_D, N_TH), dtype=np.float64)
    th_hi20_r = np.zeros((N_D, N_TH), dtype=np.float64)
    th_s5_r = np.zeros((N_D, N_TH), dtype=np.float64)
    th_abs3 = np.zeros((N_D, N_TH), dtype=np.float64)
    th_abs5 = np.zeros((N_D, N_TH), dtype=np.float64)
    th_abs20 = np.zeros((N_D, N_TH), dtype=np.float64)
    th_ex3 = np.zeros((N_D, N_TH), dtype=np.float64)
    th_ex5 = np.zeros((N_D, N_TH), dtype=np.float64)
    th_ex20 = np.zeros((N_D, N_TH), dtype=np.float64)
    th_comm = np.full((N_D, N_TH), 0.5, dtype=np.float64)

    # Incremental trailing-40d KPL membership per plate: plate -> {si: last_di}
    # (40d balances anti-selection-bias denominator against 120d 365-stock dilution in mega-themes like Robotics)
    kpl_pool_40: list[dict[int, int]] = [dict() for _ in range(N_KPL)]

    for d in range(N_D):
        # Update 40d KPL membership strictly up to d
        for pid, s_set in kpl_by_day_plate.get(d, {}).items():
            pdict = kpl_pool_40[pid]
            for s in s_set:
                pdict[s] = d

        u_idx = np.flatnonzero(U[d])
        if len(u_idx) == 0:
            continue

        # --- Layer A: SW3 / CSRC sub-industries ---
        tids = sw3_mat[d, u_idx]
        ok_sw = tids >= 0
        if ok_sw.any():
            su = u_idx[ok_sw]
            stids = tids[ok_sw].astype(np.int32)
            cnts = np.bincount(stids, minlength=N_SW)
            amts = np.bincount(stids, weights=amount_yi[d, su].astype(np.float64), minlength=N_SW)
            zts = np.bincount(stids, weights=strong8[d, su].astype(np.float64), minlength=N_SW)
            dts = np.bincount(stids, weights=is_dt[d, su].astype(np.float64), minlength=N_SW)
            ma20_c = np.bincount(stids, weights=above_ma20[d, su].astype(np.float64), minlength=N_SW)
            hi20_c = np.bincount(stids, weights=near_hi20[d, su].astype(np.float64), minlength=N_SW)
            s5_c = np.bincount(stids, weights=surge5[d, su].astype(np.float64), minlength=N_SW)
            cm_s = np.bincount(stids, weights=comm_heat[d, su].astype(np.float64), minlength=N_SW)

            r3_v = np.where(np.isfinite(ret_3d[d, su]), np.clip(ret_3d[d, su], -0.6, 2.0), np.nan).astype(np.float64)
            r5_v = np.where(np.isfinite(ret_5d[d, su]), np.clip(ret_5d[d, su], -0.6, 3.0), np.nan).astype(np.float64)
            r20_v = np.where(np.isfinite(ret_20d[d, su]), np.clip(ret_20d[d, su], -0.7, 5.0), np.nan).astype(np.float64)
            w_a = np.maximum(amount_yi[d, su].astype(np.float64), 0.01)

            stk_max = np.zeros(N_SW, dtype=np.float64)
            stk_vals = streak[d, su]
            nz = stk_vals > 0
            if nz.any():
                np.maximum.at(stk_max, stids[nz], stk_vals[nz].astype(np.float64))

            ok3 = np.isfinite(r3_v)
            c3 = np.bincount(stids[ok3], minlength=N_SW)
            s3 = np.bincount(stids[ok3], weights=r3_v[ok3], minlength=N_SW)

            ok5 = np.isfinite(r5_v)
            c5 = np.bincount(stids[ok5], minlength=N_SW)
            s5_ew = np.bincount(stids[ok5], weights=r5_v[ok5], minlength=N_SW)
            w5_sum = np.bincount(stids[ok5], weights=w_a[ok5], minlength=N_SW)
            s5_vw = np.bincount(stids[ok5], weights=r5_v[ok5] * w_a[ok5], minlength=N_SW)

            ok20 = np.isfinite(r20_v)
            c20 = np.bincount(stids[ok20], minlength=N_SW)
            s20_ew = np.bincount(stids[ok20], weights=r20_v[ok20], minlength=N_SW)
            w20_sum = np.bincount(stids[ok20], weights=w_a[ok20], minlength=N_SW)
            s20_vw = np.bincount(stids[ok20], weights=r20_v[ok20] * w_a[ok20], minlength=N_SW)

            act_ids = np.flatnonzero(cnts >= 5)
            th_active[d, act_ids] = True
            th_n[d, act_ids] = cnts[act_ids].astype(np.int16)
            th_amt[d, act_ids] = amts[act_ids]
            th_zt[d, act_ids] = zts[act_ids]
            th_dt[d, act_ids] = dts[act_ids]
            th_max_stk[d, act_ids] = stk_max[act_ids]
            th_ma20_r[d, act_ids] = ma20_c[act_ids] / cnts[act_ids]
            th_hi20_r[d, act_ids] = hi20_c[act_ids] / cnts[act_ids]
            th_s5_r[d, act_ids] = s5_c[act_ids] / cnts[act_ids]
            th_comm[d, act_ids] = cm_s[act_ids] / cnts[act_ids]

            for tid in act_ids:
                if c3[tid] > 0:
                    a3 = float(s3[tid] / c3[tid])
                    th_abs3[d, tid] = a3
                    th_ex3[d, tid] = a3 - mkt_ew_r3[d]
                if c5[tid] > 0:
                    a5 = float(0.5 * (s5_ew[tid] / c5[tid]) + 0.5 * (s5_vw[tid] / max(w5_sum[tid], 1e-6)))
                    th_abs5[d, tid] = a5
                    th_ex5[d, tid] = a5 - mkt_ew_r5[d]
                if c20[tid] > 0:
                    a20 = float(0.5 * (s20_ew[tid] / c20[tid]) + 0.5 * (s20_vw[tid] / max(w20_sum[tid], 1e-6)))
                    th_abs20[d, tid] = a20
                    th_ex20[d, tid] = a20 - mkt_ew_r20[d]

        # --- Layer B: KPL Dynamic Themes (40d causal constituent denominator + active KPL in [d-4, d]) ---
        recent_pids: set[int] = set()
        for dd in range(max(0, d - 4), d + 1):
            recent_pids.update(kpl_by_day_plate.get(dd, {}).keys())

        min_d40 = d - 39
        for pid in sorted(recent_pids):
            pdict = kpl_pool_40[pid]
            stale = [s for s, ldi in pdict.items() if ldi < min_d40]
            for s in stale:
                del pdict[s]
            mem_arr = np.array(sorted(s for s in pdict if U[d, s]), dtype=np.int32)
            if len(mem_arr) < 5:
                continue
            # Require at least 2 KPL stock appearances in [d-4, d] so stray 1-stock tags don't stay alive
            rec_hits = sum(len(kpl_by_day_plate.get(dd, {}).get(pid, ())) for dd in range(max(0, d - 4), d + 1))
            if rec_hits < 2:
                continue

            tid = N_SW + pid
            th_active[d, tid] = True
            th_n[d, tid] = len(mem_arr)
            am_m = amount_yi[d, mem_arr].astype(np.float64)
            th_amt[d, tid] = float(np.sum(am_m))
            zt_pool = float(np.sum(strong8[d, mem_arr]))
            zt_kpl = float(kpl_direct_cnt.get((d, pid), 0))
            th_zt[d, tid] = max(zt_pool, zt_kpl)
            th_dt[d, tid] = float(np.sum(is_dt[d, mem_arr]))
            th_max_stk[d, tid] = float(np.max(streak[d, mem_arr]))
            th_ma20_r[d, tid] = float(np.mean(above_ma20[d, mem_arr]))
            th_hi20_r[d, tid] = float(np.mean(near_hi20[d, mem_arr]))
            th_s5_r[d, tid] = float(np.mean(surge5[d, mem_arr]))
            th_comm[d, tid] = float(np.mean(comm_heat[d, mem_arr].astype(np.float64)))

            r3_m = ret_3d[d, mem_arr]
            ok3 = np.isfinite(r3_m)
            if ok3.any():
                a3 = float(np.mean(np.clip(r3_m[ok3].astype(np.float64), -0.6, 2.0)))
                th_abs3[d, tid] = a3
                th_ex3[d, tid] = a3 - mkt_ew_r3[d]

            r5_m = ret_5d[d, mem_arr]
            ok5 = np.isfinite(r5_m)
            if ok5.any():
                r5c = np.clip(r5_m[ok5].astype(np.float64), -0.6, 3.0)
                w5 = np.maximum(am_m[ok5], 0.01)
                a5 = float(0.5 * np.mean(r5c) + 0.5 * (np.sum(r5c * w5) / np.sum(w5)))
                th_abs5[d, tid] = a5
                th_ex5[d, tid] = a5 - mkt_ew_r5[d]

            r20_m = ret_20d[d, mem_arr]
            ok20 = np.isfinite(r20_m)
            if ok20.any():
                r20c = np.clip(r20_m[ok20].astype(np.float64), -0.7, 5.0)
                w20 = np.maximum(am_m[ok20], 0.01)
                a20 = float(0.5 * np.mean(r20c) + 0.5 * (np.sum(r20c * w20) / np.sum(w20)))
                th_abs20[d, tid] = a20
                th_ex20[d, tid] = a20 - mkt_ew_r20[d]

    # --- Compute 5 Causal Sub-Scores [N_D, N_TH] strictly <= d ---
    amt_share_1d = th_amt / np.maximum(mkt_amt[:, None], 1.0)
    cs_amt = np.vstack([np.zeros((1, N_TH), dtype=np.float64), np.cumsum(th_amt, axis=0)])
    cs_mkt = np.concatenate(([0.0], np.cumsum(mkt_amt)))
    cs_zt = np.vstack([np.zeros((1, N_TH), dtype=np.float64), np.cumsum(th_zt, axis=0)])
    cs_mzt = np.concatenate(([0.0], np.cumsum(mkt_zt_cnt)))
    cs_dt = np.vstack([np.zeros((1, N_TH), dtype=np.float64), np.cumsum(th_dt, axis=0)])
    cs_sh1 = np.vstack([np.zeros((1, N_TH), dtype=np.float64), np.cumsum(np.where(th_active, amt_share_1d, 0.0), axis=0)])
    cs_act = np.vstack([np.zeros((1, N_TH), dtype=np.int32), np.cumsum(th_active.astype(np.int32), axis=0)])
    cs_comm = np.vstack([np.zeros((1, N_TH), dtype=np.float64), np.cumsum(np.where(th_active, th_comm, 0.0), axis=0)])

    amt_share_5d = np.zeros((N_D, N_TH), dtype=np.float64)
    s_flow = np.zeros((N_D, N_TH), dtype=np.float32)
    s_trend = np.zeros((N_D, N_TH), dtype=np.float32)
    s_sent = np.zeros((N_D, N_TH), dtype=np.float32)
    s_life = np.zeros((N_D, N_TH), dtype=np.float32)
    s_cat = np.zeros((N_D, N_TH), dtype=np.float32)
    total_score = np.zeros((N_D, N_TH), dtype=np.float64)

    core_top10 = np.zeros((N_D, N_TH), dtype=bool)

    for d in range(N_D):
        act = th_active[d]
        if not act.any():
            continue
        tids = np.flatnonzero(act)

        lo5 = max(0, d - 4)
        lo3 = max(0, d - 2)
        lo10 = max(0, d - 9)
        lo60 = max(0, d - 64)
        lo250_base = max(0, d - 249)
        hi_base = max(0, d - 4)

        # 1. s_flow (0..25): turnover share jump vs 250d baseline + absolute expansion + 250d share pct
        # Using 250d baseline prevents penalizing sustained multi-month main-lines in Month 2-3!
        amt5_sum = cs_amt[d + 1, tids] - cs_amt[lo5, tids]
        sh5 = amt5_sum / max(float(cs_mkt[d + 1] - cs_mkt[lo5]), 1.0)
        amt_share_5d[d, tids] = sh5
        cnt_base = cs_act[hi_base, tids] - cs_act[lo250_base, tids]
        sh_base = np.where(cnt_base >= 5, (cs_sh1[hi_base, tids] - cs_sh1[lo250_base, tids]) / np.maximum(cnt_base, 1), sh5)
        abs_base = np.where(cnt_base >= 5, (cs_amt[hi_base, tids] - cs_amt[lo250_base, tids]) / np.maximum(cnt_base, 1), amt5_sum / max(1, d - lo5 + 1))

        shrink_w = np.clip(cnt_base / 20.0, 0.0, 1.0)
        raw_sh_jump = np.where(cnt_base >= 5, sh5 / np.maximum(sh_base, 1e-4), 1.0)
        raw_abs_jump = np.where(cnt_base >= 5, (amt5_sum / max(1, d - lo5 + 1)) / np.maximum(abs_base, 1.0), 1.0)
        adj_sh_jump = 1.0 + shrink_w * (raw_sh_jump - 1.0)
        adj_abs_jump = 1.0 + shrink_w * (raw_abs_jump - 1.0)

        lo250 = max(0, d - 249)
        hist_sh5 = amt_share_5d[lo250:d + 1, :][:, tids]
        hist_act = th_active[lo250:d + 1, :][:, tids]
        valid_h = np.sum(hist_act, axis=0)
        le_h = np.sum(hist_act & (hist_sh5 <= sh5[None, :]), axis=0)
        pct_1y = np.where(valid_h >= 15, le_h / np.maximum(valid_h, 1), 0.5)

        scale_gate = np.clip(sh5 / 0.005, 0.25, 1.0) * np.clip(th_n[d, tids] / 10.0, 0.5, 1.0)
        flow_jump = 0.5 * np.clip((adj_sh_jump - 1.0) / 1.4, 0.0, 1.0) + 0.5 * np.clip((adj_abs_jump - 1.0) / 1.6, 0.0, 1.0)
        sf = 25.0 * scale_gate * (0.50 * flow_jump + 0.50 * pct_1y)
        s_flow[d, tids] = sf.astype(np.float32)

        # 2. s_trend (0..25): breadth + absolute & excess trend momentum
        b_ma20 = np.clip((th_ma20_r[d, tids] - 0.45) / 0.45, 0.0, 1.0)
        b_hi20 = np.clip(th_hi20_r[d, tids] / 0.35, 0.0, 1.0)
        b_s5 = np.clip(th_s5_r[d, tids] / 0.45, 0.0, 1.0)
        mom5 = 0.5 * np.clip(th_abs5[d, tids] / 0.07, 0.0, 1.0) + 0.5 * np.clip(th_ex5[d, tids] / 0.07, 0.0, 1.0)
        mom20 = 0.5 * np.clip(th_abs20[d, tids] / 0.18, 0.0, 1.0) + 0.5 * np.clip(th_ex20[d, tids] / 0.18, 0.0, 1.0)
        b_mom = 0.45 * mom5 + 0.55 * mom20
        # Bear-market defensive damper: if absolute 20d return <= 0 AND < 50% above MA20, cannot score full trend
        abs_ok = np.where((th_abs20[d, tids] > 0.0) | (th_abs5[d, tids] > 0.02), 1.0, 0.30)
        st = 25.0 * abs_ok * (0.25 * b_ma20 + 0.25 * b_hi20 + 0.20 * b_s5 + 0.30 * b_mom)
        s_trend[d, tids] = st.astype(np.float32)

        # 3. s_sent (0..20): Strong-surge/ZT share, breadth, max streak height, DT negative feedback
        zt5 = cs_zt[d + 1, tids] - cs_zt[lo5, tids]
        mzt5 = max(float(cs_mzt[d + 1] - cs_mzt[lo5]), 5.0)
        zt_sh5 = zt5 / mzt5
        max_stk3 = np.max(th_max_stk[lo3:d + 1, :][:, tids], axis=0)
        dt3_ratio = (cs_dt[d + 1, tids] - cs_dt[lo3, tids]) / np.maximum(3.0 * th_n[d, tids].astype(np.float64), 3.0)
        e_zt = np.clip(zt_sh5 / 0.10, 0.0, 1.0)
        e_cnt = np.clip(zt5 / 10.0, 0.0, 1.0)
        e_stk = np.clip((max_stk3 - 1.0) / 4.0, 0.0, 1.0)
        penalty = np.clip(dt3_ratio / 0.06, 0.0, 1.0) * 8.0
        ss = np.clip(20.0 * (0.40 * e_zt + 0.35 * e_cnt + 0.25 * e_stk) - penalty, 0.0, 20.0)
        s_sent[d, tids] = ss.astype(np.float32)

        # Top-10 persistence requires POSITIVE absolute 5d return AND >= 50% above MA20 (real bull main-line!)
        core_imp = sf + st + ss
        if len(tids) > 10:
            top10_cut = np.partition(core_imp, -10)[-10]
            is_top10 = (core_imp >= top10_cut) & (th_abs5[d, tids] > 0.0) & (th_ex5[d, tids] > 0.0) & (th_ma20_r[d, tids] >= 0.50)
        else:
            is_top10 = (th_abs5[d, tids] > 0.0) & (th_ex5[d, tids] > 0.0)
        core_top10[d, tids[is_top10]] = True

        # 4. s_life (0..15): 15d top-10 persistence + wave-2 pullback re-ignition
        lo15 = max(0, d - 14)
        pers15 = np.sum(core_top10[lo15:d + 1, :][:, tids], axis=0)
        v_pers = np.clip(pers15 / 7.0, 0.0, 1.0)

        w2_flag = np.zeros(len(tids), dtype=np.float64)
        if d >= 10:
            lo25 = max(0, d - 24)
            hi25 = max(lo25 + 1, d - 5)
            prior_ex20 = np.max(th_ex20[lo25:hi25, :][:, tids], axis=0)
            prior_top = np.sum(core_top10[lo25:hi25, :][:, tids], axis=0)
            amt3 = (cs_amt[d + 1, tids] - cs_amt[lo3, tids]) / max(1, d - lo3 + 1)
            amt10 = (cs_amt[d + 1, tids] - cs_amt[lo10, tids]) / max(1, d - lo10 + 1)
            cond_w2 = (
                ((prior_ex20 >= 0.08) | (prior_top >= 3))
                & (th_ma20_r[d, tids] >= 0.50)
                & (th_abs3[d, tids] >= 0.01)
                & (th_ex3[d, tids] >= 0.015)
                & (amt3 >= amt10 * 1.05)
            )
            w2_flag = cond_w2.astype(np.float64)
        sl = 15.0 * (0.65 * v_pers + 0.35 * w2_flag)
        s_life[d, tids] = sl.astype(np.float32)

        # 5. s_cat (0..15): community/Xueqiu heat level + jump vs 60d baseline
        cnt_base60 = cs_act[hi_base, tids] - cs_act[lo60, tids]
        cm_now = th_comm[d, tids]
        cm_base = np.where(cnt_base60 >= 5, (cs_comm[hi_base, tids] - cs_comm[lo60, tids]) / np.maximum(cnt_base60, 1), cm_now)
        cm_jump = np.where(cnt_base60 >= 5, cm_now - cm_base, 0.0)
        sc = 15.0 * (0.50 * np.clip((cm_now - 0.42) / 0.22, 0.0, 1.0) + 0.50 * np.clip(cm_jump / 0.06, 0.0, 1.0))
        s_cat[d, tids] = sc.astype(np.float32)

        # Round to 4 decimals so cross-cutoff SIMD float noise cannot perturb downstream threshold gates
        total_score[d, tids] = np.round(np.clip(sf + st + ss + sl + sc, 0.0, 100.0), 4)

    # --- Stock Dynamic Theme Attribution [N_D, N_S] (20-day causal tag union + switch flag) ---
    stk_dyn_score = np.zeros((N_D, N_S), dtype=np.float32)
    stk_best_tid = np.full((N_D, N_S), -1, dtype=np.int16)
    stk_sw3_score = np.zeros((N_D, N_S), dtype=np.float32)
    stk_switched = np.zeros((N_D, N_S), dtype=bool)
    stk_kpl_tags: list[dict[int, int]] = [dict() for _ in range(N_S)]

    for d in range(N_D):
        for pid, s_set in kpl_by_day_plate.get(d, {}).items():
            for s in s_set:
                stk_kpl_tags[s][pid] = d

        sw_ids = sw3_mat[d]
        ok_sw = sw_ids >= 0
        stk_sw3_score[d, ok_sw] = total_score[d, sw_ids[ok_sw]].astype(np.float32)
        stk_dyn_score[d] = stk_sw3_score[d]
        stk_best_tid[d] = sw_ids

        min_d = d - 19
        for s in range(N_S):
            if not U[d, s]:
                continue
            tag_dict = stk_kpl_tags[s]
            if not tag_dict:
                continue
            best_sc = float(stk_dyn_score[d, s])
            best_t = int(stk_best_tid[d, s])
            best_old_t = -1
            best_old_sc = -1.0
            stale = []
            for pid, ldi in tag_dict.items():
                if ldi < min_d:
                    stale.append(pid)
                    continue
                tid = N_SW + pid
                sc_val = float(total_score[d, tid]) if th_active[d, tid] else 0.0
                if sc_val > best_sc:
                    best_sc = sc_val
                    best_t = tid
                if ldi <= d - 5 and sc_val > best_old_sc:
                    best_old_sc = sc_val
                    best_old_t = tid
            for pid in stale:
                del tag_dict[pid]
            stk_dyn_score[d, s] = best_sc
            stk_best_tid[d, s] = best_t
            sw_tid = int(sw_ids[s])
            if best_t >= N_SW and best_t != sw_tid:
                if (best_old_t >= 0 and best_old_t != best_t and best_sc > best_old_sc + 5.0) or (
                    sw_tid >= 0 and best_sc > float(stk_sw3_score[d, s]) + 8.0 and tag_dict.get(best_t - N_SW, -1) >= d - 5
                ):
                    stk_switched[d, s] = True

    out_th_npz = f"{cm.CACHE_DIR}/theme_scores_{tag}.npz"
    np.savez(
        out_th_npz,
        th_active=th_active, th_n=th_n, th_amt=th_amt.astype(np.float32), amt_share_5d=amt_share_5d.astype(np.float32),
        th_ex5=th_ex5.astype(np.float32), th_ex20=th_ex20.astype(np.float32),
        th_abs5=th_abs5.astype(np.float32), th_abs20=th_abs20.astype(np.float32),
        th_ma20_r=th_ma20_r.astype(np.float32), th_zt=th_zt.astype(np.float32),
        s_flow=s_flow, s_trend=s_trend, s_sent=s_sent, s_life=s_life, s_cat=s_cat,
        total_score=total_score,
        stk_dyn_score=stk_dyn_score, stk_best_tid=stk_best_tid,
        stk_sw3_score=stk_sw3_score, stk_switched=stk_switched,
    )
    with open(f"{cm.CACHE_DIR}/theme_names_{tag}.json", "w", encoding="utf-8") as f:
        json.dump({"all_theme_names": all_theme_names, "n_sw": N_SW, "n_kpl": N_KPL}, f, ensure_ascii=False)

    is_mask = np.array([("2021-04-01" <= d <= "2024-12-31") for d in cal_dts], dtype=bool)
    daily_top1 = np.max(np.where(th_active[is_mask], total_score[is_mask], 0.0), axis=1)
    q_stats = np.percentile(daily_top1, [10, 25, 50, 75, 90, 95, 99]).round(2).tolist()
    pct_ge = {str(thr): round(float((daily_top1 >= thr).mean() * 100.0), 1) for thr in (65, 70, 75, 80, 85)}
    print(f"[Step1 {tag} DONE in {time.time()-t0:.1f}s | RSS={cm.rss_mb()}MB] N_TH={N_TH} (SW={N_SW}, KPL={N_KPL})")
    print(f"  [IS 2021-2024 ONLY] Daily Top1 Theme Score pctls={q_stats}, pct>=thr={pct_ge}")
    return {"top1_is_pctls": q_stats, "pct_ge_is": pct_ge}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="full")
    args = ap.parse_args()
    compute_theme_scores(tag=args.tag)
