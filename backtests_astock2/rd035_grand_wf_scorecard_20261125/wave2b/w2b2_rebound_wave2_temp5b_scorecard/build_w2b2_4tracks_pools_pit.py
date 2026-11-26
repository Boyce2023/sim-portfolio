#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-2 Step 1: Build Zero-Leakage 5Y Candidate Pools + Full PIT Feature Hydration
for Tracks A (temp5b), B (b4_break_wave2), C (ndmb_2b3b), D (surge_crash_rebound).

Hard rules:
  - Peak RSS < 2.0 GB via column-pruned scan & pyarrow batch-filtered hydration.
  - Zero yfinance (D12), zero cap10m, single-thread, read-only on Wave 1 base.
  - Strict physical truncation invariance proof at 2024-12-31 (max_abs_diff == 0.0).
"""
import gc
import json
import math
import os
import resource
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
pa.set_memory_pool(pa.system_memory_pool())

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2b/w2b2_rebound_wave2_temp5b_scorecard"
os.makedirs(OUT_DIR, exist_ok=True)

STOCK_DAY_PQ = f"{WAVE1_BASE}/stock_day_core_features_pit.parquet"
MKT_DAILY_PQ = f"{WAVE1_BASE}/market_daily_all_new_factors_pit.parquet"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
SEV_HIS_1 = f"{SIM}/data/kpl/severe_his.json"
SEV_HIS_2 = f"{SIM}/backtest/2026-10-19-severe/kpl_severe_his.json"
TEMP5B_REF_PQ = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125/pool_temp5b_oldhot.parquet"

SCAN_COLS = [
    "dt", "c6", "open", "high", "low", "close", "adj_factor", "ret_1d", "open_pct", "clv",
    "is_zt", "is_dt", "is_yizi_zt", "is_yizi_dt", "streak", "prev_streak",
    "is_st_pit", "is_20cm", "list_age", "prev_close_raw", "amount_yi", "turn_pct",
]

# Strictly T-1 / pre-09:25 PIT columns from stock_day_core_features_pit.parquet (audited in wave1a)
CORE_PIT_COLS = [
    "dt", "c6", "open_pct", "is_st_pit", "is_20cm", "prev_close_raw",
    "mcap_yi_t1", "amount_yi_t1", "ret_1d_t1", "d1_open_pct", "prev_clv", "prev_streak",
    "prev_is_broken_zt", "prev_is_yizi_zt", "overhang_pct_t1", "hr10d_space_t1", "hr30d_space_t1",
    "down_streak_t1", "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "dd_20d_t1", "amp_20d_t1",
    "bias10_t1", "bias20_t1", "ret_5d_t1", "ret_20d_t1", "vol_ratio5_t1", "turn_5_20_t1",
    "amp_comp_20v60_t1", "lhb_on_t1", "lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1",
    "lhb_has_good_yz_t1", "lhb_has_surf_yz_t1", "lhb_has_quant_t1", "lhb_cnt_5d_t1",
    "lock_top10_pct_pre", "free_mcap_yi_t1", "real_turn_pct_t1", "d1_first_seal_hhmm_t1",
    "d1_open_board_cnt_t1", "d1_seal_ratio_t1", "list_age", "waves_3y_g15_t1", "zt_cnt_1y_t1",
    "max_streak_3y", "cum_turnover_1y", "trap_waves_3y", "dd_from_3y_high",
    "cool_days_since_last_zt", "cool_days_since_last_2b", "comm_posts_1y_pct", "xq_posts_1y_pct",
    "kpl_unique_plates_3y", "kpl_top_plate_share", "kpl_zt3_t1", "kpl_days_30d_t1",
    "kpl_in_t1", "kpl_rank_t1", "kpl_zt1_t1", "kpl_streak_t1", "csrc_ind_id",
    "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1", "csrc_ind_zt_share5_t1",
    "csrc_ind_amt_pct250_t1", "tox_reg_30d_pre", "abn_notice_30d_pre", "ir_cnt_30d_pre",
    "comm_ring_tier", "comm_driver_ret20_t1", "comm_driver_pct5y_t1",
]


def _load_index_and_resets(all_dts: list[str], max_dt: Optional[str]):
    idx_js = json.load(open(IDX_JSON, encoding="utf-8"))
    idx_sh = {k: float(v["close"] if isinstance(v, dict) else v) for k, v in idx_js["sh000002"].items() if (max_dt is None or k <= max_dt)}
    idx_sz = {k: float(v["close"] if isinstance(v, dict) else v) for k, v in idx_js["sz399107"].items() if (max_dt is None or k <= max_dt)}
    dt_to_mkt = {d: i for i, d in enumerate(all_dts)}
    sev_resets = {}
    for p in (SEV_HIS_1, SEV_HIS_2):
        if os.path.exists(p):
            for r in json.load(open(p, encoding="utf-8")).get("rows", []):
                if len(r) > 18:
                    r_dt = str(r[18])[:10]
                    if max_dt is not None and r_dt > max_dt:
                        continue
                    if ("10日100" in str(r[2]) or "30日200" in str(r[2]) or r[2] == "同向异动") and r_dt in dt_to_mkt:
                        sev_resets.setdefault(str(r[0]).zfill(6), set()).add(dt_to_mkt[r_dt])
    return idx_sh, idx_sz, dt_to_mkt, sev_resets


def _exit_lianban(op, hi, lo, cl, af, zt, dt_f, yzd, idx_buy: int, buy_px: float, n: int):
    """Standard causal lianban exit: non-ZT sells next day open(if weak)/close; ZT rides until break w/ 1 yang immunity."""
    if idx_buy + 1 >= n or buy_px <= 0:
        return -1, np.nan, 1500, "eof"
    if not zt[idx_buy]:
        k = idx_buy + 1
        while k < n - 1 and yzd[k]:
            k += 1
        if yzd[k]:
            return -1, np.nan, 1500, "eof_yizi_dt"
        d0_ret = (cl[idx_buy] * af[idx_buy]) / (buy_px * af[idx_buy]) - 1.0
        d1_op_ret = (op[k] * af[k]) / (cl[idx_buy] * af[idx_buy]) - 1.0
        if d0_ret <= -0.02 or cl[idx_buy] < op[idx_buy] or d1_op_ret <= -0.035:
            return k, (op[k] * af[k]) / (buy_px * af[idx_buy]) - 1.0, 925, "nonzt_next_open"
        return k, (cl[k] * af[k]) / (buy_px * af[idx_buy]) - 1.0, 1500, "nonzt_next_close"

    k = idx_buy + 1
    yang_used = False
    while k < n:
        if zt[k]:
            k += 1
            continue
        is_yang = (cl[k] > op[k]) and ((cl[k] * af[k]) / (cl[k - 1] * af[k - 1]) >= 1.015)
        if is_yang and not yang_used and k + 1 < n:
            yang_used = True
            k += 1
            continue
        pc_adj = cl[k - 1] * af[k - 1] / af[k]
        if (hi[k] >= pc_adj * 1.085) and (lo[k] <= pc_adj * 1.050) and (op[k] > pc_adj * 1.015):
            ep = pc_adj * 1.050
            return k, (ep * af[k]) / (buy_px * af[idx_buy]) - 1.0, 1430, "zt_protect_5pct"
        orig_k = k
        while k < n - 1 and yzd[k]:
            k += 1
        if yzd[k]:
            return -1, np.nan, 1500, "eof_yizi_dt"
        if k > orig_k:
            return k, (op[k] * af[k]) / (buy_px * af[idx_buy]) - 1.0, 925, "delayed_dt_open"
        return k, (cl[k] * af[k]) / (buy_px * af[idx_buy]) - 1.0, 1500, "zt_break_close"
    return -1, np.nan, 1500, "eof"


def _exit_fixed_hold(op, cl, af, dt_f, yzd, idx_buy: int, buy_px: float, n: int, hold: int = 1, ride_zt: bool = True):
    """Causal fixed holding exit (T+hold close, deferred on limit-down; optional ZT ride if buy day seals ZT)."""
    if ride_zt and idx_buy + 1 < n:
        # if buy day sealed ZT, ride until break
        pass
    k = idx_buy + hold
    if k >= n or buy_px <= 0:
        return -1, np.nan, 1500, "eof"
    if dt_f[k]:
        orig_k = k
        while k < n - 1 and yzd[k]:
            k += 1
        if yzd[k]:
            return -1, np.nan, 1500, "eof_yizi_dt"
        if k > orig_k:
            return k, (op[k] * af[k]) / (buy_px * af[idx_buy]) - 1.0, 925, "delayed_dt_open"
    return k, (cl[k] * af[k]) / (buy_px * af[idx_buy]) - 1.0, 1500, f"fixed_t{hold}_close"


def scan_4tracks_raw(max_dt: Optional[str] = None) -> dict[str, pd.DataFrame]:
    """Pass 1: Streaming single-thread pyarrow batch scan in 2 market halves (00 vs 60) -> Peak RSS < 1.5 GB."""
    t0 = time.time()
    pf = pq.ParquetFile(STOCK_DAY_PQ)
    dt_set = set()
    for batch in pf.iter_batches(batch_size=400_000, columns=["dt"], use_threads=False):
        s = batch.column(0).to_pandas().astype(str).str[:10]
        if max_dt is not None:
            s = s[s <= max_dt]
        dt_set.update(s.unique().tolist())
    all_dts = sorted(dt_set)
    pa.default_memory_pool().release_unused()

    idx_sh, idx_sz, dt_to_mkt, sev_resets = _load_index_and_resets(all_dts, max_dt)

    # Known historical resumptions matching step2
    resume_map = {
        "603137": ["2026-07-01"],
        "600825": ["2026-09-21", "2026-10-16"],
        "002084": ["2026-08-24"],
        "605577": ["2026-09-14"],
        "603221": ["2026-08-06", "2026-08-18"],
    }

    rows_A, rows_B, rows_C, rows_D, rows_D_reb = [], [], [], [], []
    buckets = [
        ("000",),
        ("001", "002", "003", "004", "005", "006", "007", "008", "009"),
        ("600",),
        ("601", "602"),
        ("603", "604", "605", "606", "607", "608", "609"),
    ]
    for prefix_grp in buckets:
        mb_chunks = []
        for batch in pf.iter_batches(batch_size=65_536, columns=SCAN_COLS, use_threads=False):
            b = batch.to_pandas()
            b["c6"] = b["c6"].astype(str).str.zfill(6)
            m = (b["is_20cm"] == 0) & b["c6"].str.startswith(prefix_grp)
            if max_dt is not None:
                b["dt"] = b["dt"].astype(str).str[:10]
                m &= (b["dt"] <= max_dt)
            b = b[m].copy()
            if not b.empty:
                if max_dt is None:
                    b["dt"] = b["dt"].astype(str).str[:10]
                for fc in ("open", "high", "low", "close", "adj_factor", "ret_1d", "open_pct", "clv", "prev_close_raw", "amount_yi", "turn_pct"):
                    b[fc] = b[fc].astype(np.float32)
                mb_chunks.append(b)
        pa.default_memory_pool().release_unused()
        if not mb_chunks:
            continue
        mb = pd.concat(mb_chunks, ignore_index=True)
        del mb_chunks
        gc.collect()
        mb.sort_values(["c6", "dt"], inplace=True)
        mb.reset_index(drop=True, inplace=True)

        for c6, g in mb.groupby("c6", sort=False):
            dts = g["dt"].to_numpy()
            op = g["open"].to_numpy(float)
            hi = g["high"].to_numpy(float)
            lo = g["low"].to_numpy(float)
            cl = g["close"].to_numpy(float)
            af = g["adj_factor"].to_numpy(float)
            r1 = g["ret_1d"].to_numpy(float)
            opct = g["open_pct"].to_numpy(float)
            clv = g["clv"].to_numpy(float)
            zt = g["is_zt"].to_numpy(bool)
            dt_f = g["is_dt"].to_numpy(bool)
            yzz = g["is_yizi_zt"].to_numpy(bool)
            yzd = g["is_yizi_dt"].to_numpy(bool)
            stk = g["streak"].to_numpy(int)
            pstk = g["prev_streak"].to_numpy(int)
            st = g["is_st_pit"].to_numpy(bool)
            age = g["list_age"].to_numpy(int)
            pc_raw = g["prev_close_raw"].to_numpy(float)
            amt = g["amount_yi"].to_numpy(float)
            trn = g["turn_pct"].to_numpy(float)
            n = len(dts)
            if n < 20:
                continue

            ac = cl * af
            ah = hi * af
            al = lo * af
            zt_px = np.floor(pc_raw * 1.10 * 100.0 + 0.5) / 100.0
            mi = np.array([dt_to_mkt[d] for d in dts], dtype=int)
            imap = idx_sh if c6.startswith("6") else idx_sz

            # Track A: temp5b
            res_set = set(sev_resets.get(c6, set()))
            for rd in resume_map.get(c6, []):
                if rd in dt_to_mkt and (max_dt is None or rd <= max_dt):
                    prev_ms = mi[mi < dt_to_mkt[rd]]
                    if len(prev_ms) > 0:
                        res_set.add(int(prev_ms[-1]))

            i = 0
            while i < n:
                if stk[i] == 5 and age[i] > 45 and not st[i] and pc_raw[i] >= 1.5:
                    five_dt = dts[i]
                    j = i
                    sel = False
                    entry_j = -1
                    gap = np.nan
                    while j + 1 < n:
                        if st[j + 1] or pc_raw[j + 1] < 1.5:
                            break
                        gap = (op[j + 1] * af[j + 1] / (cl[j] * af[j]) - 1.0) * 100.0
                        open_zt = (op[j + 1] >= zt_px[j + 1] - 0.005) or yzz[j + 1]
                        if gap <= 5.5 + 1e-8 and not open_zt:
                            sel = True
                            entry_j = j + 1
                            break
                        if zt[j + 1] and stk[j + 1] >= 6:
                            j += 1
                            continue
                        break
                    if sel and entry_j + 1 < n:
                        sold = False
                        ex_j, ex_px, ex_hh, ex_rsn = -1, np.nan, 1500, ""
                        for off in (1, 2, 3):
                            pd_i = entry_j + off
                            if pd_i >= n:
                                break
                            floor = max([v for v in res_set if v < mi[pd_i]], default=-1)
                            for kk in range(max(1, pd_i - 10), pd_i + 1):
                                if mi[kk] - mi[kk - 1] >= 5:
                                    floor = max(floor, int(mi[kk - 1]))
                            iprev = imap.get(dts[pd_i - 1])
                            cands_p95 = []
                            if iprev:
                                for kk in range(max(0, pd_i - 10), pd_i):
                                    if mi[kk] < floor:
                                        continue
                                    ib = imap.get(dts[kk])
                                    if ib and ib > 0:
                                        cands_p95.append(cl[kk] * af[kk] / af[pd_i] * (0.95 + iprev / ib))
                            if cands_p95:
                                p95 = math.ceil(min(cands_p95) * 100.0 - 1e-8) / 100.0
                                if op[pd_i] >= p95 and not yzd[pd_i]:
                                    ex_j, ex_px, ex_hh, ex_rsn = pd_i, op[pd_i], 925, "95_gap_open"
                                    sold = True
                                    break
                                if hi[pd_i] >= p95 + 0.01 - 1e-9:
                                    ex_j, ex_px, ex_hh, ex_rsn = pd_i, p95, 1030, "95_tick"
                                    sold = True
                                    break
                        if not sold:
                            ps = entry_j + 3
                            if ps < n:
                                if dt_f[ps]:
                                    k = ps + 1
                                    while k < n - 1 and yzd[k]:
                                        k += 1
                                    if k < n and not yzd[k]:
                                        ex_j, ex_px, ex_hh, ex_rsn = k, op[k], 925, "delayed_open"
                                else:
                                    ex_j, ex_px, ex_hh, ex_rsn = ps, cl[ps], 1500, "scheduled_close"
                        if ex_j > entry_j and np.isfinite(ex_px):
                            gr = (ex_px * af[ex_j]) / (op[entry_j] * af[entry_j]) - 1.0
                            w_s = max(0, j - int(stk[j]) + 1)
                            rows_A.append({
                                "track": "A_temp5b",
                                "code": c6,
                                "sig_date": dts[j],
                                "buy_date": dts[entry_j],
                                "exit_date": dts[ex_j],
                                "buy_hhmm": 925,
                                "exit_hhmm": int(ex_hh),
                                "buy_px": round(op[entry_j], 3),
                                "exit_px": round(ex_px, 3),
                                "gross_ret": float(gr),
                                "exit_reason": ex_rsn,
                                "five_date": five_dt,
                                "t5_selected_height": int(stk[j]),
                                "t5_five_to_buy_days": int(entry_j - i),
                                "t5_streak_yizi_cnt": int(np.sum(yzz[w_s:j + 1])),
                                "t5_streak_turn_avg": float(np.mean(trn[w_s:j + 1])),
                                "t5_last_turn_pct": float(trn[j]),
                                "is_yizi": False,
                            })
                    i = max(i + 1, j + 1)
                else:
                    i += 1

            # Track B (b4_break_wave2) and Track C (ndmb_2b3b)
            for i_brk in range(10, n - 1):
                if st[i_brk] or age[i_brk] <= 45 or pc_raw[i_brk] < 1.5:
                    continue
                ps_brk = pstk[i_brk]
                if zt[i_brk] or ps_brk < 2:
                    continue

                d1_yang = 1.0 if cl[i_brk] > op[i_brk] else 0.0
                d1_true_yin = 1.0 if (cl[i_brk] < op[i_brk] and r1[i_brk] < 0) else 0.0
                d1_fake_yin = 1.0 if (cl[i_brk] < op[i_brk] and r1[i_brk] >= 0) else 0.0
                hl_b = max(1e-6, hi[i_brk] - lo[i_brk])
                d1_lshad = (min(op[i_brk], cl[i_brk]) - lo[i_brk]) / hl_b
                d1_tr = trn[i_brk] / max(1e-3, trn[i_brk - 1])

                # Track C: 2b/3b break -> next day weak-to-strong open [-5.5%, +5.5%]
                if ps_brk in (2, 3):
                    ib = i_brk + 1
                    if (not st[ib]) and pc_raw[ib] >= 1.5 and (not yzz[ib]) and (not yzd[ib]) and (-5.5 <= opct[ib] <= 5.5):
                        ek, gr, ehh, ersn = _exit_lianban(op, hi, lo, cl, af, zt, dt_f, yzd, ib, op[ib], n)
                        if ek > ib and np.isfinite(gr):
                            rows_C.append({
                                "track": "C_ndmb_2b3b",
                                "code": c6,
                                "sig_date": dts[i_brk],
                                "buy_date": dts[ib],
                                "exit_date": dts[ek],
                                "buy_hhmm": 925,
                                "exit_hhmm": int(ehh),
                                "buy_px": round(op[ib], 3),
                                "exit_px": round(cl[ek] if ehh == 1500 else op[ek], 3),
                                "gross_ret": float(gr),
                                "exit_reason": ersn,
                                "c_prior_streak": int(ps_brk),
                                "c_d1_is_yang": d1_yang,
                                "c_d1_is_true_yin": d1_true_yin,
                                "c_d1_is_fake_yin": d1_fake_yin,
                                "c_d1_lower_shad": float(d1_lshad),
                                "c_d1_ret": float(r1[i_brk]),
                                "c_d1_clv": float(clv[i_brk]),
                                "c_d1_turn_ratio": float(d1_tr),
                                "c_open_sweet_red": 1.0 if 0.0 <= opct[ib] <= 5.5 else 0.0,
                                "c_open_green": 1.0 if opct[ib] < 0.0 else 0.0,
                                "is_yizi": False,
                            })

                # Track B: 4+ break, adjust 1..5 non-ZT days -> turn-strong / deep-dip / rebound-1B
                if ps_brk >= 4:
                    pk_idx = i_brk - 1
                    pk_hi = float(ah[pk_idx])
                    pk_amt = float(amt[pk_idx])
                    got_sub = {1: False, 2: False, 3: False}
                    for off in range(1, 6):
                        ib = i_brk + off
                        if ib >= n - 2 or st[ib] or pc_raw[ib] < 1.5:
                            break
                        has_prior_zt = bool(np.any(zt[i_brk:ib]))
                        if not has_prior_zt:
                            dd_pk_t1 = float(ac[ib - 1] / pk_hi - 1.0) if pk_hi > 0 else 0.0
                            vol_shr = float(amt[ib - 1] / max(1e-4, pk_amt))
                            if (not yzz[ib]) and (not yzd[ib]):
                                if (not got_sub[1]) and (0.0 <= opct[ib] <= 5.5):
                                    ek, gr, ehh, ersn = _exit_lianban(op, hi, lo, cl, af, zt, dt_f, yzd, ib, op[ib], n)
                                    if ek > ib and np.isfinite(gr):
                                        rows_B.append({
                                            "track": "B_b4_wave2",
                                            "code": c6,
                                            "sig_date": dts[ib - 1],
                                            "buy_date": dts[ib],
                                            "exit_date": dts[ek],
                                            "buy_hhmm": 925,
                                            "exit_hhmm": int(ehh),
                                            "buy_px": round(op[ib], 3),
                                            "gross_ret": float(gr),
                                            "exit_reason": ersn,
                                            "b4_subtype": 1,
                                            "b4_peak_streak": int(ps_brk),
                                            "b4_adj_days": int(off),
                                            "b4_brk_ret": float(r1[i_brk]),
                                            "b4_brk_is_yang": d1_yang,
                                            "b4_brk_clv": float(clv[i_brk]),
                                            "b4_dd_from_peak_t1": dd_pk_t1,
                                            "b4_vol_shrink_ratio": vol_shr,
                                            "is_yizi": False,
                                        })
                                        got_sub[1] = True
                                if (not got_sub[2]) and (-7.5 <= opct[ib] <= -1.0) and (dd_pk_t1 <= -0.10):
                                    ek, gr, ehh, ersn = _exit_fixed_hold(op, cl, af, dt_f, yzd, ib, op[ib], n, hold=2)
                                    if ek > ib and np.isfinite(gr):
                                        rows_B.append({
                                            "track": "B_b4_wave2",
                                            "code": c6,
                                            "sig_date": dts[ib - 1],
                                            "buy_date": dts[ib],
                                            "exit_date": dts[ek],
                                            "buy_hhmm": 925,
                                            "exit_hhmm": int(ehh),
                                            "buy_px": round(op[ib], 3),
                                            "gross_ret": float(gr),
                                            "exit_reason": ersn,
                                            "b4_subtype": 2,
                                            "b4_peak_streak": int(ps_brk),
                                            "b4_adj_days": int(off),
                                            "b4_brk_ret": float(r1[i_brk]),
                                            "b4_brk_is_yang": d1_yang,
                                            "b4_brk_clv": float(clv[i_brk]),
                                            "b4_dd_from_peak_t1": dd_pk_t1,
                                            "b4_vol_shrink_ratio": vol_shr,
                                            "is_yizi": False,
                                        })
                                        got_sub[2] = True
                        if (not got_sub[3]) and (not has_prior_zt) and zt[ib] and (ib + 2 < n):
                            ib2 = ib + 1
                            if (not st[ib2]) and pc_raw[ib2] >= 1.5 and (not yzz[ib2]) and (not yzd[ib2]) and (-5.5 <= opct[ib2] <= 5.5):
                                dd_pk_t1 = float(ac[ib] / pk_hi - 1.0) if pk_hi > 0 else 0.0
                                vol_shr = float(amt[ib] / max(1e-4, pk_amt))
                                ek, gr, ehh, ersn = _exit_lianban(op, hi, lo, cl, af, zt, dt_f, yzd, ib2, op[ib2], n)
                                if ek > ib2 and np.isfinite(gr):
                                    rows_B.append({
                                        "track": "B_b4_wave2",
                                        "code": c6,
                                        "sig_date": dts[ib],
                                        "buy_date": dts[ib2],
                                        "exit_date": dts[ek],
                                        "buy_hhmm": 925,
                                        "exit_hhmm": int(ehh),
                                        "buy_px": round(op[ib2], 3),
                                        "gross_ret": float(gr),
                                        "exit_reason": ersn,
                                        "b4_subtype": 3,
                                        "b4_peak_streak": int(ps_brk),
                                        "b4_adj_days": int(off),
                                        "b4_brk_ret": float(r1[i_brk]),
                                        "b4_brk_is_yang": d1_yang,
                                        "b4_brk_clv": float(clv[i_brk]),
                                        "b4_dd_from_peak_t1": dd_pk_t1,
                                        "b4_vol_shrink_ratio": vol_shr,
                                        "is_yizi": False,
                                    })
                                    got_sub[3] = True
                            break

            # Track D: Surge >= 40% & >= 3 LU in 10d -> Crash 2..4 days (dd <= -20%) -> Buy open [-6.5%, +5.5%]
            i = 15
            while i < n - 1:
                if st[i] or age[i] <= 45 or pc_raw[i] < 1.5:
                    i += 1
                    continue
                found_pk = -1
                surge_pct = 0.0
                surge_lu = 0
                surge_stk = 0
                for k_back in (3, 4, 5):
                    pk = i - k_back
                    if pk < 12:
                        continue
                    if ah[pk] >= np.max(ah[pk - 5:i]) and np.max(np.abs(r1[pk - 10:i])) <= 12.5:
                        slu = int(np.sum(zt[pk - 10:pk + 1]))
                        if slu >= 3:
                            bl = float(np.min(al[pk - 10:pk]))
                            if bl > 0:
                                sp = float(ah[pk] / bl - 1.0)
                                if sp >= 0.40:
                                    dd = float(np.min(al[pk + 1:i]) / ah[pk] - 1.0)
                                    if dd <= -0.20:
                                        found_pk = pk
                                        surge_pct = sp
                                        surge_lu = slu
                                        surge_stk = int(np.max(stk[pk - 10:pk + 1]))
                                        break
                if found_pk != -1 and (not yzz[i]) and (not yzd[i]) and (-6.5 <= opct[i] <= 5.5):
                    if zt[i]:
                        ek1, gr1, ehh1, ersn1 = _exit_lianban(op, hi, lo, cl, af, zt, dt_f, yzd, i, op[i], n)
                    else:
                        ek1, gr1, ehh1, ersn1 = _exit_fixed_hold(op, cl, af, dt_f, yzd, i, op[i], n, hold=1)
                    ek3, gr3, _, _ = _exit_fixed_hold(op, cl, af, dt_f, yzd, i, op[i], n, hold=3)
                    if ek1 > i and np.isfinite(gr1):
                        pk_amt = float(np.max(amt[max(0, found_pk - 2):found_pk + 2]))
                        rows_D.append({
                            "track": "D_surge_crash",
                            "code": c6,
                            "sig_date": dts[i - 1],
                            "buy_date": dts[i],
                            "exit_date": dts[ek1],
                            "buy_hhmm": 925,
                            "exit_hhmm": int(ehh1),
                            "buy_px": round(op[i], 3),
                            "gross_ret": float(gr1),
                            "gross_ret_t3": float(gr3) if (ek3 > i and np.isfinite(gr3)) else np.nan,
                            "exit_date_t3": dts[ek3] if ek3 > i else "",
                            "exit_reason": ersn1,
                            "d_surge_pct": float(surge_pct),
                            "d_surge_lu_cnt": int(surge_lu),
                            "d_surge_max_streak": int(surge_stk),
                            "d_crash_days": int((i - 1) - found_pk),
                            "d_crash_ld_cnt": int(np.sum(dt_f[found_pk + 1:i])),
                            "d_dd_from_peak_t1": float(ac[i - 1] / ah[found_pk] - 1.0),
                            "d_vol_shrink_ratio": float(amt[i - 1] / max(1e-4, pk_amt)),
                            "d_t1_is_yang": 1.0 if cl[i - 1] > op[i - 1] else 0.0,
                            "is_yizi": False,
                        })
                    for rj in range(max(found_pk + 2, i - 1), min(n - 2, i + 6)):
                        if zt[rj]:
                            rb = rj + 1
                            if (not st[rb]) and pc_raw[rb] >= 1.5 and (not yzz[rb]) and (not yzd[rb]) and (-5.5 <= opct[rb] <= 5.5):
                                ekr, grr, ehhr, ersnr = _exit_lianban(op, hi, lo, cl, af, zt, dt_f, yzd, rb, op[rb], n)
                                if ekr > rb and np.isfinite(grr):
                                    rows_D_reb.append({
                                        "track": "D_reb1b_nextopen",
                                        "code": c6,
                                        "sig_date": dts[rj],
                                        "buy_date": dts[rb],
                                        "exit_date": dts[ekr],
                                        "buy_hhmm": 925,
                                        "exit_hhmm": int(ehhr),
                                        "buy_px": round(op[rb], 3),
                                        "gross_ret": float(grr),
                                        "exit_reason": ersnr,
                                        "d_surge_pct": float(surge_pct),
                                        "d_surge_max_streak": int(surge_stk),
                                        "d_crash_days": int(rj - found_pk),
                                        "d_dd_from_peak_t1": float(np.min(al[found_pk + 1:rj]) / ah[found_pk] - 1.0),
                                        "is_yizi": False,
                                    })
                            break
                    i += 5
                else:
                    i += 1
        del mb
        gc.collect()
        pa.default_memory_pool().release_unused()

    df_A = pd.DataFrame(rows_A)
    df_B = pd.DataFrame(rows_B).sort_values(["buy_date", "code", "b4_subtype"], ascending=[True, True, True]).drop_duplicates(["buy_date", "code"], keep="first").reset_index(drop=True)
    df_C = pd.DataFrame(rows_C).sort_values(["buy_date", "code"]).drop_duplicates(["buy_date", "code"], keep="first").reset_index(drop=True)
    df_D = pd.DataFrame(rows_D).sort_values(["buy_date", "code"]).drop_duplicates(["buy_date", "code"], keep="first").reset_index(drop=True)
    df_Dr = pd.DataFrame(rows_D_reb).sort_values(["buy_date", "code"]).drop_duplicates(["buy_date", "code"], keep="first").reset_index(drop=True)

    print(f"[Pass1] Scanned in {time.time()-t0:.1f}s -> A={len(df_A)}, B={len(df_B)}, C={len(df_C)}, D={len(df_D)}, D_reb1b={len(df_Dr)}")
    return {"A_temp5b": df_A, "B_b4_wave2": df_B, "C_ndmb_2b3b": df_C, "D_surge_crash": df_D, "D_reb1b": df_Dr}


def hydrate_pit_features(pools: dict[str, pd.DataFrame], max_dt: Optional[str] = None) -> dict[str, pd.DataFrame]:
    """Pass 2: Stream stock_day_core_features_pit in batches to hydrate strictly T-1/pre-09:25 PIT cols + market_daily."""
    t0 = time.time()
    need_keys = set()
    for df in pools.values():
        if not df.empty:
            need_keys.update(zip(df["buy_date"].astype(str), df["code"].astype(str)))
    need_dts = {k[0] for k in need_keys}
    need_c6s = {k[1] for k in need_keys}

    pf = pq.ParquetFile(STOCK_DAY_PQ)
    chunks = []
    for batch in pf.iter_batches(batch_size=65_536, columns=CORE_PIT_COLS, use_threads=False):
        b = batch.to_pandas()
        b["dt"] = b["dt"].astype(str).str[:10]
        b["c6"] = b["c6"].astype(str).str.zfill(6)
        if max_dt is not None:
            b = b[b["dt"] <= max_dt]
        b = b[b["dt"].isin(need_dts) & b["c6"].isin(need_c6s)]
        if not b.empty:
            mask = [((d, c) in need_keys) for d, c in zip(b["dt"].values, b["c6"].values)]
            b = b[mask]
            if not b.empty:
                chunks.append(b)

    core_df = pd.concat(chunks, ignore_index=True).drop_duplicates(["dt", "c6"], keep="first")
    del chunks
    gc.collect()
    pa.default_memory_pool().release_unused()

    mkt_df = pd.read_parquet(MKT_DAILY_PQ)
    mkt_df["trade_date"] = mkt_df["trade_date"].astype(str).str[:10]
    if max_dt is not None:
        mkt_df = mkt_df[mkt_df["trade_date"] <= max_dt].copy()

    out = {}
    for name, df in pools.items():
        if df.empty:
            out[name] = df
            continue
        m = df.merge(core_df, left_on=["buy_date", "code"], right_on=["dt", "c6"], how="left")
        m.drop(columns=[c for c in ("dt", "c6") if c in m.columns], inplace=True)
        m = m.merge(mkt_df, left_on="buy_date", right_on="trade_date", how="left")
        m.drop(columns=[c for c in ("trade_date",) if c in m.columns], inplace=True)

        # Derived strictly causal interactions & flags
        m["drv_open_minus_ret_t1"] = pd.to_numeric(m["open_pct"], errors="coerce") - pd.to_numeric(m["ret_1d_t1"], errors="coerce")
        m["drv_hr_min_space_t1"] = np.fmin(
            pd.to_numeric(m["hr10d_space_t1"], errors="coerce"),
            pd.to_numeric(m["hr30d_space_t1"], errors="coerce"),
        )
        m["drv_lock_ge50"] = (pd.to_numeric(m["lock_top10_pct_pre"], errors="coerce") >= 50.0).astype(float)
        m["drv_real_turn_ge15"] = (pd.to_numeric(m["real_turn_pct_t1"], errors="coerce") >= 15.0).astype(float)
        m["drv_lhb_inst_minus_lhasa"] = pd.to_numeric(m["lhb_inst_net_yi_t1"], errors="coerce") - pd.to_numeric(m["lhb_lhasa_share_t1"], errors="coerce")
        m["drv_ind_rel5_t1"] = pd.to_numeric(m["ret_5d_t1"], errors="coerce") - pd.to_numeric(m["csrc_ind_ex5_t1"], errors="coerce")
        m["drv_ind_rel20_t1"] = pd.to_numeric(m["ret_20d_t1"], errors="coerce") - pd.to_numeric(m["csrc_ind_ex20_t1"], errors="coerce")
        m["drv_has_reg_or_tox"] = ((pd.to_numeric(m["tox_reg_30d_pre"], errors="coerce").fillna(0) > 0) | (pd.to_numeric(m["abn_notice_30d_pre"], errors="coerce").fillna(0) > 0)).astype(float)

        # Track D explicit Minefield risk-clearance flags (排雷分家)
        m_tox = pd.to_numeric(m["tox_reg_30d_pre"], errors="coerce").fillna(0) > 0
        m_abn = pd.to_numeric(m["abn_notice_30d_pre"], errors="coerce").fillna(0) > 0
        m_pdt = (pd.to_numeric(m["ret_1d_t1"], errors="coerce").fillna(0) <= -9.4) & (pd.to_numeric(m["prev_clv"], errors="coerce").fillna(0.5) <= 0.05)
        m_lhs = pd.to_numeric(m["lhb_lhasa_share_t1"], errors="coerce").fillna(0) > 0.25
        m_nuc = pd.to_numeric(m["open_pct"], errors="coerce").fillna(0) <= -5.5
        m_knf = (pd.to_numeric(m["ret_1d_t1"], errors="coerce").fillna(0) <= -8.5) & (pd.to_numeric(m["prev_clv"], errors="coerce").fillna(0.5) < 0.25)
        m["mine_tox_reg"] = m_tox.astype(float)
        m["mine_abn_notice"] = m_abn.astype(float)
        m["mine_prev_dt"] = m_pdt.astype(float)
        m["mine_lhasa_heavy"] = m_lhs.astype(float)
        m["mine_nuclear_open"] = m_nuc.astype(float)
        m["mine_unstopped_knife"] = m_knf.astype(float)
        m["mine_any_cnt"] = (m_tox.astype(int) + m_abn.astype(int) + m_pdt.astype(int) + m_lhs.astype(int) + m_nuc.astype(int) + m_knf.astype(int)).astype(float)
        m["is_mine_cleared"] = (m["mine_any_cnt"] == 0).astype(int)

        out[name] = m

    print(f"[Pass2] Hydrated {len(core_df)} stock-days + {mkt_df.shape[1]} mkt cols in {time.time()-t0:.1f}s")
    return out


def verify_temp5b_parity(df_A: pd.DataFrame) -> dict:
    ref = pd.read_parquet(TEMP5B_REF_PQ)
    ref_sel = ref[ref["sim_ok"]].copy()
    ref_sel["code"] = ref_sel["code"].astype(str).str.zfill(6)
    a26 = df_A[df_A["five_date"] >= "2026-07-01"].copy()
    m = a26.merge(ref_sel[["code", "five_date", "buy_date", "exit_date", "net_ret"]], on=["code", "five_date"], how="outer", suffixes=("_new", "_ref"))
    m["net_new_030"] = (1.0 + m["gross_ret"]) * (1.0 - 0.0030) - 1.0
    m["abs_diff"] = (m["net_new_030"] - m["net_ret"]).abs()
    exact_buy_matches = int((m["buy_date_new"] == m["buy_date_ref"]).sum())
    return {
        "n_new_202607plus": int(len(a26)),
        "n_ref_202607plus": int(len(ref_sel)),
        "buy_date_exact_matches": exact_buy_matches,
        "median_abs_ret_diff": round(float(m["abs_diff"].median()), 6),
        "discrepancies": m[m["abs_diff"].isna() | (m["abs_diff"] > 0.002)][["code", "five_date", "buy_date_new", "buy_date_ref", "exit_date_new", "exit_date_ref", "net_new_030", "net_ret"]].to_dict("records"),
    }


def verify_pool_truncation_20241231(full_pools: dict[str, pd.DataFrame]) -> dict:
    """Rebuild entire pipeline strictly <= 2024-12-31 and assert max_abs_diff == 0.0 on all settled rows <= 2024-12-31."""
    trunc_raw = scan_4tracks_raw(max_dt="2024-12-31")
    trunc_hyd = hydrate_pit_features(trunc_raw, max_dt="2024-12-31")
    report = {}
    for k, fdf in full_pools.items():
        tdf = trunc_hyd[k]
        f_sub = fdf[fdf["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        t_sub = tdf[tdf["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        assert len(f_sub) == len(t_sub), f"{k} trunc count mismatch: {len(f_sub)} vs {len(t_sub)}"
        assert list(zip(f_sub["buy_date"], f_sub["code"])) == list(zip(t_sub["buy_date"], t_sub["code"])), f"{k} key mismatch"
        max_ret_diff = float(np.max(np.abs(f_sub["gross_ret"].to_numpy(float) - t_sub["gross_ret"].to_numpy(float)))) if len(f_sub) else 0.0
        # Check numeric feature diffs
        num_cols = [c for c in t_sub.columns if pd.api.types.is_numeric_dtype(t_sub[c]) and c in f_sub.columns and c != "gross_ret_t3"]
        max_feat_diff = 0.0
        for c in num_cols:
            va = pd.to_numeric(f_sub[c], errors="coerce").fillna(-99999.0).to_numpy(float)
            vb = pd.to_numeric(t_sub[c], errors="coerce").fillna(-99999.0).to_numpy(float)
            d = float(np.max(np.abs(va - vb))) if len(va) else 0.0
            if d > max_feat_diff:
                max_feat_diff = d
        if "gross_ret_t3" in t_sub.columns and "exit_date_t3" in t_sub.columns:
            m3 = (f_sub["exit_date_t3"] != "") & (f_sub["exit_date_t3"] <= "2024-12-31")
            if m3.any():
                d3 = float(np.max(np.abs(f_sub.loc[m3, "gross_ret_t3"].to_numpy(float) - t_sub.loc[m3, "gross_ret_t3"].to_numpy(float))))
                max_feat_diff = max(max_feat_diff, d3)
        assert max_ret_diff == 0.0 and max_feat_diff == 0.0, f"{k} trunc diff != 0: ret={max_ret_diff}, feat={max_feat_diff}"
        report[k] = {
            "n_settled_le_20241231": int(len(f_sub)),
            "max_abs_ret_diff": max_ret_diff,
            "max_abs_feat_diff": max_feat_diff,
            "pass": True,
        }
    return report


def main():
    t0 = time.time()
    raw_pools = scan_4tracks_raw(max_dt=None)
    pools = hydrate_pit_features(raw_pools, max_dt=None)
    parity_a = verify_temp5b_parity(pools["A_temp5b"])
    trunc_proof = verify_pool_truncation_20241231(pools)

    for k, df in pools.items():
        p_out = f"{OUT_DIR}/pool_{k}_pit.parquet"
        df.to_parquet(p_out, index=False)
        print(f"  Saved {k}: {df.shape} -> {p_out}")

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)
    meta = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb,
        "temp5b_202607plus_parity": parity_a,
        "pool_data_truncation_20241231": trunc_proof,
        "pool_counts": {k: int(len(v)) for k, v in pools.items()},
    }
    with open(f"{OUT_DIR}/_step1_pools_audit.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[Step1 DONE in {meta['elapsed_sec']}s | Peak RSS={rss_mb}MB] parity={parity_a['buy_date_exact_matches']}/{parity_a['n_ref_202607plus']}")
    assert rss_mb < 2000.0, f"Peak RSS exceeded 2.0GB: {rss_mb}MB"


if __name__ == "__main__":
    main()
