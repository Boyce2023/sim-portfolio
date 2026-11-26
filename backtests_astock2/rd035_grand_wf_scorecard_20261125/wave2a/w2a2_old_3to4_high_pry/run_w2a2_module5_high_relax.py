#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-2 Module 5: High-Dragon First-Yin Relaxation & Edge-Tier Expansion (Strict WF, 0.30% Fee).
  Part 5A: Inside `pool_high_master_pit.parquet` (62 rows: 46 pass vs 16 edge_cand, 42 V5.1 trades)
  Part 5B: Market-wide relaxation from `stock_day_core_features_pit.parquet` + `a_daily` + `market_daily`:
    - R1: PoolA + PoolA_melee + PoolB, true_yang | fake_yin, D1 turnover <= 45%
    - R2: R1 + PoolC (secondary 4-board+ leaders)
    - R3: Broad 4-board+ (A+A_melee+B+C), any non-DT D1 K-line, D1 turnover <= 50%
    - R4: R2 + PoolD (ice-point 3-board max)
  Runs Mode A 0..100 causal WF scorecard (exit_date < t), Minefield/Dragon split,
  V20.0 strict no-peek empty-slot patch, and 2024-12-31 physical truncation proof.

Zero yfinance (D12). Memory < 2.5 GB. Threads <= 2.
"""
import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import gc
import json
import pickle
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
A2_ASSETS = f"{SIM}/backtests_astock2/assets"
SANDBOX_CACHE = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"

for p in (CUR_DIR, WAVE1_BASE, A2_ASSETS):
    if p not in sys.path:
        sys.path.insert(0, p)

import _w2a2_common as cm
import wf_scorecard_engine as wf
import _wf_core as wfc
import _wf_sim_and_metrics as wfm
from v191_dt_defer_helper import load_dt_defer_tables, defer_eod_limit_down, calc_adj_net_ret


def run_part_5a_existing_pool(v20_ctx: dict) -> tuple[list[dict], dict]:
    """Audit and test relaxations inside existing 62-row `pool_high_master_pit.parquet`."""
    pm, _ = cm.load_master_pool_with_exec("high")
    wf_start = "2023-01-03"
    wf_cands = pm[pm["buy_date"] >= wf_start].copy()

    rows = []
    # Characterize 16 edge candidates vs 46 passing vs 4 skipped passing
    pass_df_0, slot_df_0 = cm.sim_strategy_custom("high", pm, "orig_score", 88.0, wf_only=False, high_cb_mode="v51_exact")
    slot_keys = set(zip(slot_df_0["buy_date"], slot_df_0["code"]))
    edge_df = pm[pm["orig_score"] < 88.0].copy()
    skipped_pass = pass_df_0[~pass_df_0.apply(lambda r: (r["buy_date"], r["code"]) in slot_keys, axis=1)].copy()

    # Empty-slot check on the 16 edge candidates alone (Mode 2 standalone + Mode 1 patch)
    edge_wf = edge_df[edge_df["buy_date"] >= wf_start].copy()
    edge_ep = wf.simulate_v20_empty_slot_patch(
        edge_wf, v20_ctx=v20_ctx, wf_start_dt=wf_start, end_dt="2026-11-16", score_col="orig_score"
    ) if not edge_wf.empty else None

    diag_5a = {
        "total_pool_rows": int(len(pm)),
        "pass_ge88_rows": int(len(pass_df_0)),
        "v51_slot_trades_5y": int(len(slot_df_0)),
        "skipped_pass_rows": skipped_pass[["buy_date", "code", "name", "orig_score", "net_ret"]].to_dict("records"),
        "edge_cand_count_5y": int(len(edge_df)),
        "edge_cand_mean_ret_030_pct": round(float(edge_df["net_ret"].mean() * 100.0), 2),
        "edge_cand_wr_pct": round(float((edge_df["net_ret"] > 0).mean() * 100.0), 2),
        "edge_cand_wf_count": int(len(edge_wf)),
        "edge_cand_wf_mean_ret_030_pct": round(float(edge_wf["net_ret"].mean() * 100.0), 2) if len(edge_wf) else 0.0,
        "edge_cand_empty_patch": {
            "mode1_delta_ratio": edge_ep["mode1_strict_combined_no_peek"]["delta_nav_ratio_full_wf"] if edge_ep else 1.0,
            "mode1_n_added": edge_ep["mode1_strict_combined_no_peek"]["n_patch_added"] if edge_ep else 0,
            "mode2_empty_n": edge_ep["mode2_empty_slot_standalone"]["n_standalone_empty_trades"] if edge_ep else 0,
            "mode2_empty_nav": edge_ep["mode2_empty_slot_standalone"]["windows"]["FULL_WF"]["nav"] if edge_ep else 1.0,
        },
    }

    configs = [
        ("M5A_Orig88_NoCB", 88.0, "none"),
        ("M5A_Relax84_CB", 84.0, "v51_exact"),
        ("M5A_Relax84_NoCB", 84.0, "none"),
        ("M5A_Relax80_CB", 80.0, "v51_exact"),
        ("M5A_Relax80_NoCB", 80.0, "none"),
        ("M5A_Relax75_CB", 75.0, "v51_exact"),
        ("M5A_All62_Orig_NoCB", 60.0, "none"),
    ]
    for vid, thr, cb_m in configs:
        p_a, s_a = cm.sim_strategy_custom("high", pm, "orig_score", thr, wf_only=False, high_cb_mode=cb_m)
        p_w = p_a[p_a["buy_date"] >= wf_start].reset_index(drop=True)
        s_w = s_a[s_a["buy_date"] >= wf_start].reset_index(drop=True)
        r_row, _ = cm.summarize_eval_row(
            "high", "M5A_ExistingEdge", vid, p_w, s_w, wf_cands, v20_ctx, wf_start, perm_n=1000, score_col="orig_score",
        )
        rows.append(r_row)

    return rows, diag_5a


def get_double_dev_px(dts: np.ndarray, closes: np.ndarray, cp: int, idx_map: dict, disc: float = 0.07) -> float:
    cd = str(dts[cp])
    ir = idx_map.get(cd)
    if not ir:
        return 99999.0
    bp = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k
        bi = idx_map.get(str(dts[p]))
        bc = float(closes[p])
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
    for k in range(1, min(31, cp + 1)):
        p = cp - k
        bi = idx_map.get(str(dts[p]))
        bc = float(closes[p])
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
    return bp


def load_filtered_dt_tables(codes_needed: set[str], start_date: str = "2021-09-01") -> dict:
    """Low-RAM (<1.5GB) loader for limit-down deferral & adjf strictly filtered to `codes_needed`."""
    import pyarrow.dataset as ds
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp(start_date)
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["c6"] = da["ticker"].astype(str).str[:6]
    da = da[da["c6"].isin(codes_needed) & (~da["ticker"].astype(str).str.endswith(".BJ"))].copy()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd["c6"] = dd["ticker"].astype(str).str[:6]
    dd = dd[dd["c6"].isin(codes_needed) & (~dd["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df_d = pd.concat([da, dd], ignore_index=True)
    del da, dd
    gc.collect()

    df_d["dt_s"] = df_d["date"].dt.strftime("%Y-%m-%d")
    df_d.sort_values(["c6", "dt_s"], inplace=True)
    df_d.drop_duplicates(["c6", "dt_s"], keep="first", inplace=True)
    df_d["adjf"] = np.where(df_d["close"] > 0, df_d["adj_close"] / df_d["close"], 1.0)
    g = df_d.groupby("c6")
    df_d["prev_c_adj"] = g["close"].shift(1) * g["adjf"].shift(1) / df_d["adjf"]
    df_d["dt_px"] = np.floor(df_d["prev_c_adj"] * 0.90 * 100.0 + 0.5) / 100.0
    df_d["is_dt_exact"] = (df_d["close"] <= df_d["dt_px"] + 0.005) & (df_d["prev_c_adj"] > 0)
    df_d["is_yizi_dt"] = df_d["is_dt_exact"] & (df_d["open"] <= df_d["dt_px"] + 0.005) & (df_d["high"] <= df_d["dt_px"] + 0.005)
    by_c = {c6: grp.reset_index(drop=True) for c6, grp in df_d.groupby("c6")}
    dmap = {(r.c6, r.dt_s): r for r in df_d.itertuples(index=False)}
    return {"dmap": dmap, "by_c": by_c}


def build_relaxed_high_pool(end_cutoff: str = "2026-11-16") -> pd.DataFrame:
    """
    Build strictly PIT relaxed high-dragon candidate pool directly from `stock_day_core_features_pit.parquet`
    + `market_daily_all_new_factors_pit.parquet` + low-RAM filtered `a_daily` tables.
    100% truncation-invariant (no future data used).
    """
    t0 = time.time()
    with open(SANDBOX_CACHE, "r", encoding="utf-8") as f:
        idx_k = json.load(f)
    sh_map = {k: float(v) for k, v in idx_k["sh000002"].items() if k <= end_cutoff}
    sz_map = {k: float(v) for k, v in idx_k["sz399107"].items() if k <= end_cutoff}

    # Step 1: Load minimal columns of stock_day_core to compute daily ZT streaks & D0 landscape
    base_cols = [
        "dt", "c6", "open", "high", "low", "close", "ret_1d", "open_pct",
        "clv", "is_yizi_dt", "is_st_pit", "is_20cm", "prev_close_raw", "turn_pct", "tox_reg_30d_pre",
    ]
    sd = pd.read_parquet(
        f"{WAVE1_BASE}/stock_day_core_features_pit.parquet",
        columns=base_cols,
        filters=[("dt", ">=", "2021-09-01"), ("dt", "<=", end_cutoff)],
    )
    sd["dt_s"] = sd["dt"].astype(str)
    sd["c6_s"] = sd["c6"].astype(str)
    sd = sd[(sd["c6_s"].str.startswith(("00", "60"))) & (~sd["is_20cm"].astype(bool)) & (~sd["is_st_pit"].astype(bool))].copy()
    sd.sort_values(["c6_s", "dt_s"], inplace=True)
    sd.reset_index(drop=True, inplace=True)

    # Recompute 0.011 ZT tolerance matching high-dragon convention (e.g. 000815 2022-03-01 close=14.17 vs zt=14.18)
    zt_px_011 = np.floor(sd["prev_close_raw"].fillna(0).to_numpy(float) * 1.10 * 100.0 + 0.5) / 100.0
    is_zt_h = (
        (sd["prev_close_raw"].fillna(0).to_numpy(float) > 0)
        & (sd["close"].to_numpy(float) >= zt_px_011 - 0.011)
        & (sd["ret_1d"].fillna(0).to_numpy(float) >= 9.5)
    )
    is_yz_h = is_zt_h & (sd["open"].to_numpy(float) >= zt_px_011 - 0.011) & (sd["low"].to_numpy(float) >= zt_px_011 - 0.011)

    c6_arr = sd["c6_s"].to_numpy()
    n_sd = len(sd)
    stk = np.zeros(n_sd, dtype=np.int16)
    yz_stk = np.zeros(n_sd, dtype=np.int16)
    yz_in_stk = np.zeros(n_sd, dtype=np.int16)
    prev_stk = np.zeros(n_sd, dtype=np.int16)
    prev_yz_ratio = np.zeros(n_sd, dtype=np.float32)

    cur_s, cur_y, cur_ysum, pc = 0, 0, 0, ""
    for i in range(n_sd):
        if c6_arr[i] != pc:
            cur_s, cur_y, cur_ysum, pc = 0, 0, 0, c6_arr[i]
        prev_stk[i] = cur_s
        prev_yz_ratio[i] = (cur_ysum / cur_s) if cur_s > 0 else 0.0
        if is_zt_h[i]:
            cur_s += 1
            cur_y = (cur_y + 1) if is_yz_h[i] else 0
            cur_ysum = cur_ysum + (1 if is_yz_h[i] else 0)
        else:
            cur_s, cur_y, cur_ysum = 0, 0, 0
        stk[i] = cur_s
        yz_stk[i] = cur_y
        yz_in_stk[i] = cur_ysum

    sd["is_zt_h"] = is_zt_h
    sd["is_yz_h"] = is_yz_h
    sd["stk_h"] = stk
    sd["yz_stk_h"] = yz_stk
    sd["prev_stk_h"] = prev_stk
    sd["prev_yz_ratio_h"] = prev_yz_ratio

    # Build daily D0 landscape
    zt_only = sd[sd["is_zt_h"] & (sd["stk_h"] >= 1)][["dt_s", "c6_s", "stk_h", "yz_stk_h"]]
    mkt_d0 = {}
    for dts, grp in zt_only.groupby("dt_s", sort=False):
        s_max = int(grp["stk_h"].max())
        top_sub = grp[grp["stk_h"] == s_max]
        top_cnt = int(len(top_sub))
        top1_all_yizi3 = bool((top_sub["yz_stk_h"] >= 3).all())
        uni_s = sorted(grp["stk_h"].unique(), reverse=True)
        sec_b = int(uni_s[1]) if len(uni_s) > 1 else 0
        non_yz = grp[grp["yz_stk_h"] < 3]
        if len(non_yz) > 0:
            ny_s = sorted(non_yz["stk_h"].unique(), reverse=True)
            ny_max = int(ny_s[0])
            ny_sec = int(ny_s[1]) if len(ny_s) > 1 else 0
            ny_codes = set(non_yz[non_yz["stk_h"].isin([ny_max, ny_sec])]["c6_s"])
        else:
            ny_max, ny_sec, ny_codes = 0, 0, set()
        mkt_d0[dts] = (s_max, top_cnt, top1_all_yizi3, sec_b, ny_max, ny_sec, ny_codes)

    # Identify D1 broken events (prev_stk_h >= 3, ~is_zt_h, dt >= 2021-11-01)
    d1_mask = (sd["prev_stk_h"] >= 3) & (~sd["is_zt_h"]) & (~sd["is_yizi_dt"].astype(bool)) & (sd["dt_s"] >= "2021-11-01")
    d1_idx = np.flatnonzero(d1_mask.to_numpy())

    cal_dts = sorted(sd["dt_s"].unique().tolist())
    cal_pos = {d: i for i, d in enumerate(cal_dts)}

    pre_cands = []
    for i1 in d1_idx:
        if i1 == 0 or i1 + 1 >= n_sd:
            continue
        c6 = c6_arr[i1]
        if c6_arr[i1 - 1] != c6 or c6_arr[i1 + 1] != c6:
            continue
        d0_dt = sd["dt_s"].iat[i1 - 1]
        d1_dt = sd["dt_s"].iat[i1]
        d2_dt = sd["dt_s"].iat[i1 + 1]
        if cal_pos[d1_dt] - cal_pos[d0_dt] > 3 or cal_pos[d2_dt] - cal_pos[d1_dt] > 3:
            continue
        if d2_dt > end_cutoff:
            continue

        meta0 = mkt_d0.get(d0_dt)
        if meta0 is None:
            continue
        s_max, top_cnt, top1_yz3, sec_b, ny_max, ny_sec, ny_codes = meta0
        pst = int(sd["prev_stk_h"].iat[i1])
        pyr = float(sd["prev_yz_ratio_h"].iat[i1])

        pool_tier = None
        if pst >= 4 and pst == s_max:
            pool_tier = "PoolA_Top12" if top_cnt <= 2 else "PoolA_Melee"
        elif top1_yz3 and pst >= 4 and (c6 in ny_codes or pst in (ny_max, ny_sec)):
            pool_tier = "PoolB_MABackup"
        elif (not top1_yz3) and pst >= 4 and pst < s_max and pst >= max(4, sec_b):
            pool_tier = "PoolC_Sub4p"
        elif s_max == 3 and pst == 3:
            pool_tier = "PoolD_Ice3"
        if pool_tier is None:
            continue

        d1_op = float(sd["open"].iat[i1])
        d1_hi = float(sd["high"].iat[i1])
        d1_lo = float(sd["low"].iat[i1])
        d1_cl = float(sd["close"].iat[i1])
        d1_pc = float(sd["prev_close_raw"].iat[i1])
        d1_to = float(sd["turn_pct"].iat[i1])
        d1_ret = float(sd["ret_1d"].iat[i1]) / 100.0
        d1_op_pct = float(sd["open_pct"].iat[i1]) / 100.0
        d1_clv = float(sd["clv"].iat[i1])
        d1_is_ty = bool(d1_cl > d1_op)
        d1_is_fy = bool((d1_cl <= d1_op) and (d1_cl > d1_pc))
        d1_uwick = (d1_hi - max(d1_op, d1_cl)) / d1_pc if d1_pc > 0 else 0.0
        d1_body = (d1_cl - d1_op) / d1_pc if d1_pc > 0 else 0.0
        d1_amp = (d1_hi - d1_lo) / d1_pc if d1_pc > 0 else 0.0
        d1_tox = int(sd["tox_reg_30d_pre"].iat[i1 + 1])

        if d1_to > 55.0 or d1_ret <= -0.095:
            continue

        d2_op = float(sd["open"].iat[i1 + 1])
        d2_pc = float(sd["prev_close_raw"].iat[i1 + 1])
        d2_op_pct = float(sd["open_pct"].iat[i1 + 1]) / 100.0
        if d2_pc <= 0 or not (-0.065 <= d2_op_pct <= 0.045):
            continue

        pre_cands.append((
            d2_dt, d1_dt, d0_dt, c6, pool_tier, pst, s_max, top_cnt, pyr,
            d1_is_ty, d1_is_fy, d1_to, d1_ret, d1_op_pct, d1_clv,
            d1_uwick, d1_body, d1_amp, d1_tox, d2_op, d2_op_pct,
        ))

    del sd, zt_only
    gc.collect()

    needed_c6 = {x[3] for x in pre_cands}
    dt_tables = load_filtered_dt_tables(needed_c6, start_date="2021-09-01")
    by_c = dt_tables["by_c"]

    cand_records = []
    for (
        d2_dt, d1_dt, d0_dt, c6, pool_tier, pst, s_max, top_cnt, pyr,
        d1_is_ty, d1_is_fy, d1_to, d1_ret, d1_op_pct, d1_clv,
        d1_uwick, d1_body, d1_amp, d1_tox, d2_op, d2_op_pct,
    ) in pre_cands:
        gc_bar = by_c.get(c6)
        if gc_bar is None:
            continue
        m_pos = gc_bar.index[gc_bar["dt_s"] == d2_dt]
        if len(m_pos) == 0:
            continue
        d2p = int(m_pos[0])
        if d2p + 1 >= len(gc_bar):
            continue

        g_dts = gc_bar["dt_s"].to_numpy()
        g_op = gc_bar["open"].to_numpy(float)
        g_hi = gc_bar["high"].to_numpy(float)
        g_lo = gc_bar["low"].to_numpy(float)
        g_cl = gc_bar["close"].to_numpy(float)
        g_adjf = gc_bar["adjf"].to_numpy(float)
        g_pc = gc_bar["prev_c_adj"].to_numpy(float)
        g_yz_dt = gc_bar["is_yizi_dt"].to_numpy(bool)

        zt_d2 = float(np.floor(g_pc[d2p] * 1.10 * 100.0 + 0.5) / 100.0)
        dt_d2 = float(np.floor(g_pc[d2p] * 0.90 * 100.0 + 0.5) / 100.0)
        if g_op[d2p] >= zt_d2 - 0.011 or g_op[d2p] <= dt_d2 + 0.011:
            continue

        # Simulate V5.1 `S_hold_d3` and `S_cut_weak` on 09:25 auction buy (0.30% fee + strict limit-down deferral)
        imap = sh_map if c6.startswith("60") else sz_map
        n_bar = len(g_dts)
        is_zt_arr = (g_pc > 0) & (g_cl >= (np.floor(g_pc * 1.10 * 100.0 + 0.5) / 100.0) - 0.011) & ((g_cl / np.maximum(1e-9, g_pc) - 1.0) >= 0.095)

        def run_zt_loop(start_p):
            imm = False
            for step in range(1, 8):
                p = start_p + step
                if p >= n_bar:
                    break
                pl = get_double_dev_px(g_dts, g_cl, p, imap, 0.07)
                if g_op[p] >= pl:
                    return p, 925, float(g_op[p])
                if g_hi[p] >= pl:
                    return p, 1030, float(pl)
                if not is_zt_arr[p]:
                    if (not imm) and (g_cl[p] > g_op[p]):
                        imm = True
                        continue
                    while p < n_bar - 1 and g_yz_dt[p]:
                        p += 1
                    return p, 1500, float(g_cl[p])
            p_end = min(start_p + 5, n_bar - 1)
            return p_end, 1500, float(g_cl[p_end])

        # S_hold_d3
        if is_zt_arr[d2p]:
            ep_h, eh_h, epx_h = run_zt_loop(d2p)
        else:
            p = min(d2p + 1, n_bar - 1)
            while p < n_bar - 1 and g_yz_dt[p]:
                p += 1
            if is_zt_arr[p]:
                ep_h, eh_h, epx_h = run_zt_loop(p)
            else:
                ep_h, eh_h, epx_h = p, 1500, float(g_cl[p])

        e_dt_h = str(g_dts[ep_h])
        nr_h = calc_adj_net_ret(c6, d2_dt, d2_op, e_dt_h, epx_h, dt_tables, 0.0030)
        if nr_h is None:
            continue
        ned_h, neh_h, nep_h, nret_h, _ = defer_eod_limit_down(c6, d2_dt, d2_op, e_dt_h, eh_h, epx_h, nr_h, dt_tables, 0.0030)

        # S_cut_weak
        if is_zt_arr[d2p]:
            ned_cw, neh_cw, nret_cw = ned_h, neh_h, nret_h
        else:
            p = min(d2p + 1, n_bar - 1)
            while p < n_bar - 1 and g_yz_dt[p]:
                p += 1
            d2_ret_i = g_cl[d2p] / d2_op - 1.0
            d3_op_p = g_op[p] / g_pc[p] - 1.0 if g_pc[p] > 0 else 0.0
            if d2_ret_i <= -0.02 or (g_cl[d2p] < d2_op and d2_ret_i < 0) or d3_op_p <= -0.035:
                ep_c, eh_c, epx_c = p, 925, float(g_op[p])
            elif is_zt_arr[p]:
                ep_c, eh_c, epx_c = run_zt_loop(p)
            else:
                ep_c, eh_c, epx_c = p, 1500, float(g_cl[p])
            e_dt_c = str(g_dts[ep_c])
            nr_c = calc_adj_net_ret(c6, d2_dt, d2_op, e_dt_c, epx_c, dt_tables, 0.0030)
            if nr_c is None:
                nr_c = nret_h
                ned_cw, neh_cw, nret_cw = ned_h, neh_h, nret_h
            else:
                ned_cw, neh_cw, _, nret_cw, _ = defer_eod_limit_down(c6, d2_dt, d2_op, e_dt_c, eh_c, epx_c, nr_c, dt_tables, 0.0030)

        cand_records.append({
            "buy_date": d2_dt,
            "d1_date": d1_dt,
            "d0_date": d0_dt,
            "buy_hhmm": 925,
            "exit_date": ned_h,
            "exit_hhmm": int(neh_h),
            "code": c6,
            "pool_tier": pool_tier,
            "prev_streak_d0": pst,
            "mkt_max_d0": s_max,
            "top_cnt_d0": top_cnt,
            "prev_yizi_ratio": pyr,
            "d1_is_true_yang": int(d1_is_ty),
            "d1_is_fake_yin": int(d1_is_fy),
            "d1_turn_pct": d1_to,
            "d1_ret": d1_ret,
            "d1_open_pct": d1_op_pct,
            "d1_clv": d1_clv,
            "d1_upper_shadow": d1_uwick,
            "d1_real_body": d1_body,
            "d1_amp": d1_amp,
            "d1_tox_30d": d1_tox,
            "open_pct": d2_op_pct,
            "buy_price": round(d2_op, 2),
            "net_ret": float(nret_h),
            "net_ret_hold_d3": float(nret_h),
            "exit_date_cutweak": ned_cw,
            "exit_hhmm_cutweak": int(neh_cw),
            "net_ret_cutweak": float(nret_cw),
            "is_yizi": False,
            "can_buy_hygiene": True,
        })

    cand_df = pd.DataFrame(cand_records).sort_values(["buy_date", "code"]).reset_index(drop=True)
    del dt_tables, by_c, pre_cands
    gc.collect()

    # Step 2: Attach ALL T-1/pre-09:25 PIT features from stock_day_core ONLY for the ~500 candidate codes!
    cand_c6 = sorted(cand_df["code"].unique().tolist())
    cand_dt = sorted(cand_df["buy_date"].unique().tolist())
    sd_t1_cols = [
        "c6", "dt", "prev_close_raw", "mcap_yi_t1", "amount_yi_t1", "ret_1d_t1", "d1_open_pct",
        "prev_clv", "prev_streak", "prev_is_broken_zt", "prev_is_yizi_zt", "overhang_pct_t1",
        "hr10d_space_t1", "hr30d_space_t1", "down_streak_t1", "pos_20d_t1", "pos_60d_t1",
        "pos_250d_t1", "dd_20d_t1", "amp_20d_t1", "bias10_t1", "bias20_t1", "ret_5d_t1",
        "ret_20d_t1", "vol_ratio5_t1", "turn_5_20_t1", "amp_comp_20v60_t1",
        "lhb_on_t1", "lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1",
        "lhb_has_good_yz_t1", "lhb_has_surf_yz_t1", "lhb_has_quant_t1", "lhb_cnt_5d_t1",
        "lock_top10_pct_pre", "free_mcap_yi_t1", "real_turn_pct_t1",
        "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "d1_seal_ratio_t1",
        "list_age", "waves_3y_g15_t1", "zt_cnt_1y_t1", "max_streak_3y", "cum_turnover_1y",
        "trap_waves_3y", "dd_from_3y_high", "cool_days_since_last_zt", "cool_days_since_last_2b",
        "comm_posts_1y_pct", "xq_posts_1y_pct", "kpl_unique_plates_3y", "kpl_top_plate_share",
        "kpl_zt3_t1", "kpl_days_30d_t1", "kpl_in_t1", "kpl_rank_t1", "kpl_zt1_t1", "kpl_streak_t1",
        "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1", "csrc_ind_zt_share5_t1",
        "csrc_ind_amt_pct250_t1", "tox_reg_30d_pre", "abn_notice_30d_pre", "ir_cnt_30d_pre",
    ]
    sd_sub = pd.read_parquet(
        f"{WAVE1_BASE}/stock_day_core_features_pit.parquet",
        columns=sd_t1_cols,
        filters=[("dt", "<=", end_cutoff), ("c6", "in", cand_c6)],
    )
    sd_sub["code"] = sd_sub["c6"].astype(str)
    sd_sub["buy_date"] = sd_sub["dt"].astype(str)
    sd_sub = sd_sub[sd_sub["code"].isin(cand_c6) & sd_sub["buy_date"].isin(cand_dt)].drop_duplicates(["buy_date", "code"])
    rename_sd = {c: f"sd_{c}" for c in sd_t1_cols if c not in ("c6", "dt")}
    sd_sub = sd_sub.rename(columns=rename_sd).drop(columns=["c6", "dt"])
    cand_df = cand_df.merge(sd_sub, on=["buy_date", "code"], how="left")
    del sd_sub
    gc.collect()

    # Step 3: Attach Market Daily New Factors (119 cols strictly <= end_cutoff)
    mkt = pd.read_parquet(f"{WAVE1_BASE}/market_daily_all_new_factors_pit.parquet")
    mkt = mkt[mkt["trade_date"] <= end_cutoff].copy()
    cand_df = cand_df.merge(mkt, left_on="buy_date", right_on="trade_date", how="left").drop(columns=["trade_date"])

    # Step 4: Add causal cross-strategy binary flags (all strictly T-1 / 09:25 PIT)
    cand_df["x_d1_op_neg"] = (cand_df["d1_open_pct"] < 0.0).astype(float)
    cand_df["x_op2_neg"] = (cand_df["open_pct"] < 0.0).astype(float)
    cand_df["x_px_le20"] = (cand_df["sd_prev_close_raw"] <= 20.0).astype(float)
    cand_df["x_lock_or_fmcap45"] = ((cand_df["sd_lock_top10_pct_pre"] >= 45.0) | (cand_df["sd_free_mcap_yi_t1"] >= 45.0)).astype(float)
    cand_df["x_lh1_zero"] = ((cand_df["sd_lhb_on_t1"] == 1) & (cand_df["sd_lhb_lhasa_share_t1"] == 0.0)).astype(float)
    cand_df["x_d1_to_le35"] = (cand_df["d1_turn_pct"] <= 35.0).astype(float)
    cand_df["x_pool_is_top"] = cand_df["pool_tier"].isin(["PoolA_Top12", "PoolB_MABackup"]).astype(float)
    cand_df["x_pool_is_sub4p"] = (cand_df["pool_tier"] == "PoolC_Sub4p").astype(float)

    print(f"[M5B] Built relaxed high-dragon pool ({len(cand_df)} rows, {cand_df['pool_tier'].value_counts().to_dict()}) in {time.time()-t0:.1f}s")
    return cand_df


def run_part_5b_market_relaxation(v20_ctx: dict) -> tuple[list[dict], dict, pd.DataFrame]:
    cand_all = build_relaxed_high_pool(end_cutoff="2026-11-16")

    # Feature list: strictly T-1 / 09:25 PIT columns only!
    exclude = {
        "buy_date", "d1_date", "d0_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "pool_tier",
        "buy_price", "net_ret", "net_ret_hold_d3", "exit_date_cutweak", "exit_hhmm_cutweak", "net_ret_cutweak",
        "is_yizi", "can_buy_hygiene",
    }
    feat_cols = [c for c in cand_all.columns if c not in exclude and pd.api.types.is_numeric_dtype(cand_all[c])]

    # Isolated dimension anatomy across all 603+ market-wide candidates (0.30% friction)
    def _slice_stat(sub, col="net_ret"):
        if sub.empty:
            return {"n": 0, "wr_pct": 0.0, "mean_pct": 0.0, "plr": 0.0, "wf_n": 0, "wf_mean_pct": 0.0, "wf_wr_pct": 0.0}
        r = sub[col].to_numpy(float)
        w, l = r[r > 0], r[r <= 0]
        plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else 0.0
        sw = sub[sub["buy_date"] >= "2023-01-03"]
        rw = sw[col].to_numpy(float)
        return {
            "n": int(len(r)), "wr_pct": round(float((r > 0).mean() * 100.0), 2),
            "mean_pct": round(float(r.mean() * 100.0), 2), "plr": round(plr, 2),
            "wf_n": int(len(rw)), "wf_wr_pct": round(float((rw > 0).mean() * 100.0), 2) if len(rw) else 0.0,
            "wf_mean_pct": round(float(rw.mean() * 100.0), 2) if len(rw) else 0.0,
        }

    anatomy_5b = {
        "by_pool_tier_hold_d3": {k: _slice_stat(cand_all[cand_all["pool_tier"] == k], "net_ret") for k in ["PoolA_Top12", "PoolA_Melee", "PoolB_MABackup", "PoolC_Sub4p", "PoolD_Ice3"]},
        "by_pool_tier_cutweak": {k: _slice_stat(cand_all[cand_all["pool_tier"] == k], "net_ret_cutweak") for k in ["PoolA_Top12", "PoolA_Melee", "PoolB_MABackup", "PoolC_Sub4p", "PoolD_Ice3"]},
        "by_d1_kline_4p": {
            "true_yang": _slice_stat(cand_all[(cand_all["pool_tier"] != "PoolD_Ice3") & (cand_all["d1_is_true_yang"] == 1)]),
            "fake_yin": _slice_stat(cand_all[(cand_all["pool_tier"] != "PoolD_Ice3") & (cand_all["d1_is_fake_yin"] == 1)]),
            "normal_yin": _slice_stat(cand_all[(cand_all["pool_tier"] != "PoolD_Ice3") & (cand_all["d1_is_true_yang"] == 0) & (cand_all["d1_is_fake_yin"] == 0)]),
        },
        "by_d1_turn_4p": {
            "to_le_35": _slice_stat(cand_all[(cand_all["pool_tier"] != "PoolD_Ice3") & (cand_all["d1_turn_pct"] <= 35.0)]),
            "to_35_to_45": _slice_stat(cand_all[(cand_all["pool_tier"] != "PoolD_Ice3") & (cand_all["d1_turn_pct"] > 35.0) & (cand_all["d1_turn_pct"] <= 45.0)]),
            "to_45_to_55": _slice_stat(cand_all[(cand_all["pool_tier"] != "PoolD_Ice3") & (cand_all["d1_turn_pct"] > 45.0)]),
        },
        "by_open_auc_4p_tyfy": {
            "red_auc_0_45": _slice_stat(cand_all[(cand_all["pool_tier"] != "PoolD_Ice3") & ((cand_all["d1_is_true_yang"] == 1) | (cand_all["d1_is_fake_yin"] == 1)) & (cand_all["open_pct"] >= 0.0)]),
            "green_auc_neg": _slice_stat(cand_all[(cand_all["pool_tier"] != "PoolD_Ice3") & ((cand_all["d1_is_true_yang"] == 1) | (cand_all["d1_is_fake_yin"] == 1)) & (cand_all["open_pct"] < 0.0)]),
        },
    }

    # Define progressive relaxation pools
    pools_m5 = {
        "M5B_R1_TopPlusMelee_To45_TYFY": cand_all[
            cand_all["pool_tier"].isin(["PoolA_Top12", "PoolA_Melee", "PoolB_MABackup"])
            & ((cand_all["d1_is_true_yang"] == 1) | (cand_all["d1_is_fake_yin"] == 1))
            & (cand_all["d1_turn_pct"] <= 45.0)
            & (cand_all["prev_yizi_ratio"] <= 0.50)
        ].copy().reset_index(drop=True),
        "M5B_R2_AddSub4p_To45_TYFY": cand_all[
            cand_all["pool_tier"].isin(["PoolA_Top12", "PoolA_Melee", "PoolB_MABackup", "PoolC_Sub4p"])
            & ((cand_all["d1_is_true_yang"] == 1) | (cand_all["d1_is_fake_yin"] == 1))
            & (cand_all["d1_turn_pct"] <= 45.0)
            & (cand_all["prev_yizi_ratio"] <= 0.50)
        ].copy().reset_index(drop=True),
        "M5B_R2_RedAuc_To45_TYFY": cand_all[
            cand_all["pool_tier"].isin(["PoolA_Top12", "PoolA_Melee", "PoolB_MABackup", "PoolC_Sub4p"])
            & ((cand_all["d1_is_true_yang"] == 1) | (cand_all["d1_is_fake_yin"] == 1))
            & (cand_all["d1_turn_pct"] <= 45.0)
            & (cand_all["prev_yizi_ratio"] <= 0.50)
            & (cand_all["open_pct"] >= 0.0)
        ].copy().reset_index(drop=True),
        "M5B_R3_Broad4p_AnyK_To50": cand_all[
            cand_all["pool_tier"].isin(["PoolA_Top12", "PoolA_Melee", "PoolB_MABackup", "PoolC_Sub4p"])
            & (cand_all["d1_turn_pct"] <= 50.0)
            & (cand_all["prev_yizi_ratio"] <= 0.55)
        ].copy().reset_index(drop=True),
        "M5B_R4_AddIce3B_To45_TYFY": cand_all[
            ((cand_all["d1_is_true_yang"] == 1) | (cand_all["d1_is_fake_yin"] == 1))
            & (cand_all["d1_turn_pct"] <= 45.0)
            & (cand_all["prev_yizi_ratio"] <= 0.50)
        ].copy().reset_index(drop=True),
    }

    rows = []
    diag_5b = {"pool_counts": {k: int(len(v)) for k, v in pools_m5.items()}, "anatomy_5b": anatomy_5b, "mode_a_results": {}, "truncation_20241231": {}}
    best_r_slot = pd.DataFrame()
    best_r_nav = -1.0

    for pname, pdf in pools_m5.items():
        # Run Mode A 0..100 causal WF scorecard (exit_date < t)
        res_a = wf.run_wf_scorecard_new_strategy(
            pdf, feat_cols, v20_ctx=v20_ctx, wf_start_date="2023-01-03",
            end_date="2026-11-16", min_warmup_trades=45, min_warmup_trades_rare=35,
            min_warmup_months=12, recalc_freq="daily", top_k=12, min_k=5,
            max_corr=0.65, min_t_stat=1.0, shrink_tau=15.0,
            thresholds=("all_cands", "top30", "top20", "top10", "top5", 65, 70, 75, 80),
            eval_v20_patch=True, perm_n=1000,
        )
        wfs = res_a["meta"]["wf_actual_start"] or "2023-01-03"
        wf_cands = res_a["scored_df"][res_a["scored_df"]["wf_in_window"]].copy()

        diag_5b["mode_a_results"][pname] = {
            "wf_actual_start": wfs,
            "n_wf_cands": int(len(wf_cands)),
            "latest_factors": res_a["meta"]["latest_scorecard"]["factors"] if res_a["meta"].get("latest_scorecard") else [],
        }

        for th_key, tr_obj in res_a["threshold_results"].items():
            pass_df = tr_obj["pass_df"]
            slot_df = tr_obj["slot_df"]
            ep = tr_obj["v20_empty_patch"]
            r_row, _ = cm.summarize_eval_row(
                "high_relax", f"M5B_{pname}", f"{pname}_ModeA_{th_key}",
                pass_df, slot_df, wf_cands, v20_ctx, wfs, perm_n=1000,
                s_tier_cutoff=70.0, score_col="wf_score", empty_patch_res=ep,
            )
            if ep is not None:
                m2 = ep["mode2_empty_slot_standalone"]["windows"]["FULL_WF"]
                m1c = ep["mode1_strict_combined_no_peek"]
                r_row["note"] = f"empty_n={m2['n']} empty_nav={m2['nav']}x comb_ratio={m1c['delta_nav_ratio_full_wf']} comb_add={m1c['n_patch_added']} skip_v20={m1c['n_v20_skipped_by_collision']}"
            rows.append(r_row)

            if th_key in ("top30", "top20", "top10", "abs_70") and r_row["n_trades"] >= 15 and r_row["nav_wf"] > best_r_nav:
                best_r_nav = r_row["nav_wf"]
                best_r_slot = slot_df.copy()

        # Also test S_cut_weak exit on R2/R3
        if pname in ("M5B_R2_AddSub4p_To45_TYFY", "M5B_R3_Broad4p_AnyK_To50"):
            pdf_cw = pdf.copy()
            pdf_cw["exit_date"] = pdf_cw["exit_date_cutweak"]
            pdf_cw["exit_hhmm"] = pdf_cw["exit_hhmm_cutweak"]
            pdf_cw["net_ret"] = pdf_cw["net_ret_cutweak"]
            res_cw = wf.run_wf_scorecard_new_strategy(
                pdf_cw, feat_cols, v20_ctx=v20_ctx, wf_start_date="2023-01-03",
                end_date="2026-11-16", min_warmup_trades=45, min_warmup_trades_rare=35,
                min_warmup_months=12, recalc_freq="daily", top_k=12, min_k=5,
                thresholds=("all_cands", "top20", "top10", 70), eval_v20_patch=True, perm_n=1000,
            )
            wfs_cw = res_cw["meta"]["wf_actual_start"] or "2023-01-03"
            wfc_cw = res_cw["scored_df"][res_cw["scored_df"]["wf_in_window"]].copy()
            for th_key, tr_obj in res_cw["threshold_results"].items():
                ep = tr_obj["v20_empty_patch"]
                r_cw, _ = cm.summarize_eval_row(
                    "high_relax", f"M5B_{pname}_CutWeak", f"{pname}_CutWeak_ModeA_{th_key}",
                    tr_obj["pass_df"], tr_obj["slot_df"], wfc_cw, v20_ctx, wfs_cw, perm_n=1000,
                    s_tier_cutoff=70.0, score_col="wf_score", empty_patch_res=ep,
                )
                if ep is not None:
                    m2 = ep["mode2_empty_slot_standalone"]["windows"]["FULL_WF"]
                    m1c = ep["mode1_strict_combined_no_peek"]
                    r_cw["note"] = f"empty_n={m2['n']} empty_nav={m2['nav']}x comb_ratio={m1c['delta_nav_ratio_full_wf']} comb_add={m1c['n_patch_added']} skip_v20={m1c['n_v20_skipped_by_collision']}"
                rows.append(r_cw)

    # Physical Truncation Proof at 2024-12-31 for relaxed high pool builder + Mode A scorecard
    cand_trunc = build_relaxed_high_pool(end_cutoff="2024-12-31")
    r2_full = pools_m5["M5B_R2_AddSub4p_To45_TYFY"]
    r2_trunc = cand_trunc[
        cand_trunc["pool_tier"].isin(["PoolA_Top12", "PoolA_Melee", "PoolB_MABackup", "PoolC_Sub4p"])
        & ((cand_trunc["d1_is_true_yang"] == 1) | (cand_trunc["d1_is_fake_yin"] == 1))
        & (cand_trunc["d1_turn_pct"] <= 45.0)
        & (cand_trunc["prev_yizi_ratio"] <= 0.50)
    ].copy().reset_index(drop=True)

    r2_f_le = r2_full[r2_full["buy_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    r2_t_le = r2_trunc.sort_values(["buy_date", "code"]).reset_index(drop=True)
    assert len(r2_f_le) == len(r2_t_le), f"M5B trunc row mismatch: {len(r2_f_le)} vs {len(r2_t_le)}"
    feat_max_diff = 0.0
    for c in feat_cols:
        a = r2_f_le[c].to_numpy(float)
        b = r2_t_le[c].to_numpy(float)
        fin = np.isfinite(a) & np.isfinite(b)
        d = float(np.max(np.abs(a[fin] - b[fin]))) if fin.any() else 0.0
        feat_max_diff = max(feat_max_diff, d)
    assert feat_max_diff == 0.0, f"M5B feature truncation diff: {feat_max_diff}"

    trunc_wf = wf.verify_truncation_zero_leakage(
        r2_full, feat_cols, mode="A", cutoff="2024-12-31", score_threshold="top20",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=45,
        min_warmup_trades_rare=35, min_warmup_months=12, recalc_freq="daily",
    )
    diag_5b["truncation_20241231"] = {"pool_feature_max_abs_diff": feat_max_diff, **trunc_wf}
    return rows, diag_5b, best_r_slot


def main():
    t0 = time.time()
    v20_ctx = wf.load_v20_reference_context()
    rows_5a, diag_5a = run_part_5a_existing_pool(v20_ctx)
    rows_5b, diag_5b, best_r_slot = run_part_5b_market_relaxation(v20_ctx)

    all_rows = rows_5a + rows_5b
    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)

    out_pkl = f"{CUR_DIR}/_w2a2_m5_results.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump({
            "rows": all_rows,
            "diag_5a": diag_5a,
            "diag_5b": diag_5b,
            "best_r_slot": best_r_slot,
        }, f)
    print(f"[DONE M5 in {time.time()-t0:.1f}s | RSS={rss_mb}MB] rows={len(all_rows)} -> {out_pkl}")


if __name__ == "__main__":
    main()
