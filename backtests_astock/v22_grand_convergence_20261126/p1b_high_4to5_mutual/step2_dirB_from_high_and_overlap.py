#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V22.0 Pillar 1B Direction B: High-Dragon V5.1 Genes -> 4to5 & 3to4, plus Sequential Overlap & Portfolio Audit.
Strict PIT causality (<= buy_date 09:25:00), zero yfinance (D12), SQLite ?mode=ro.
Covers:
  (B1) High-Dragon hard redlines (ex_reg5>=2, s_reg_10d/zdjk complete, JIANCHI_ONLY / TOX_STRICT_RE)
       transplanted onto 4to5 (G1_StrictJianchi_114, G1_FixPIT_120, G1_FixPIT_114, G1_Base_V20_114)
       and 3to4 (V4.1 95t & V4.2 85t entry & exit).
  (B2) High-Dragon `brk_r10` (both `brk_dt_r10` and `reb_zt_r10`) & `93% double-dev buffered limit sell`
       (`E_Abn93_Always`, `E_Abn93_ZTOnly` vs `E4`, `E_Abn95_Limit`, `E_Abn96_ZT5b`, `E_7Factor_Guard`)
       transplanted onto 4to5.
  (B3) Consecutive-day same-stock synergy & slot-priority conflict audit (4to5 <-> High-Dragon <-> 3to4)
       both standalone & inside full 6-strategy V20 / V21 portfolio (rd038_master_cache.pkl).
Supports `--trunc-date 2024-12-31 --out-json ...` for physical zero-leakage truncation verification.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import argparse
import gc
import json
import math
import pickle
import re
import sqlite3
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
assert "yfinance" not in sys.modules, "D12 VIOLATION"

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)
import _p1b_common as cm

# Read-only upstream library paths
for _p in (cm.RD048_W1A, cm.RD048_DIR, cm.RD038_DIR, cm.P3_DEEP, cm.F1_3TO4, cm.RD039_F23, f"{cm.SIM}/scripts"):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def sim_4to5_causal_exit_custom(
    c6: str,
    bd: str,
    buy_px: float,
    cb: dict,
    idx_map: dict,
    exit_rule: str,
    fee: float,
    reb_lt20_map: dict,
) -> tuple[Optional[str], float, int]:
    """
    Strictly causal daily executable exit simulator for 4to5:
      - `E_Abn93_Always`: 93% double-dev standing limit order (`idx_{t-1}` known at 09:25) from buy-day+1 + E1 YangImm1 fallback
      - `E_Abn93_ZTOnly`: High-Dragon V5.1 exact rule — 93% double-dev ONLY armed when buy-day sealed ZT or chained ZT
      - `E_Abn95_Always`: 95% double-dev standing limit order (`idx_{t-1}`)
      - `E_Abn96_ZT5b`: 3to4 XF30 rule — 96% double-dev when held >=5 boards (streak >= 5, since D4=4b, buy-day ZT = 5b) & `reb_zt_r10 < 0.20`
    """
    if cb is None or bd not in cb["dt_idx"]:
        return None, np.nan, 1500
    pos = cb["dt_idx"][bd]
    n = len(cb["dts"])
    if pos + 1 >= n:
        return None, np.nan, 1500

    a0 = float(cb["adjf"][pos])
    is_zt0 = bool(cb["is_zt"][pos])
    o0, c0, p0 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])

    def _sell_ret(k_idx: int, px: float) -> float:
        return (px * float(cb["adjf"][k_idx])) / (buy_px * a0) * (1.0 - fee) - 1.0

    def _defer_dt(k_idx: int) -> tuple[str, float, int]:
        kk = k_idx + 1
        while kk < n and bool(cb["is_yizi_dt"][kk]):
            kk += 1
        if kk >= n:
            kk = n - 1
            return cb["dts"][kk], _sell_ret(kk, float(cb["close"][kk])), 1500
        return cb["dts"][kk], _sell_ret(kk, float(cb["open"][kk])), 925

    def _check_dev_trigger(k_idx: int, dev_thr: float) -> Optional[tuple[str, float, int]]:
        dt_k = cb["dts"][k_idx]
        dt_prev = cb["dts"][k_idx - 1]
        idx_prev = idx_map.get(dt_prev)
        if not idx_prev or k_idx < 10:
            return None
        p_caps = []
        for lb in range(1, 11):
            j = k_idx - lb
            if j < 0:
                continue
            idx_base = idx_map.get(cb["dts"][j])
            if not idx_base or idx_base <= 0:
                continue
            idx_ret = idx_prev / idx_base - 1.0
            base_adj = float(cb["close"][j] * cb["adjf"][j])
            t_raw = base_adj * (1.0 + idx_ret + dev_thr) / float(cb["adjf"][k_idx])
            p_caps.append(math.ceil(t_raw * 100.0 - 1e-12) / 100.0)
        for lb in range(1, min(31, k_idx + 1)):
            j = k_idx - lb
            idx_base = idx_map.get(cb["dts"][j])
            if not idx_base or idx_base <= 0:
                continue
            idx_ret = idx_prev / idx_base - 1.0
            base_adj = float(cb["close"][j] * cb["adjf"][j])
            t_raw = base_adj * (1.0 + (dev_thr + 1.0) + idx_ret) / float(cb["adjf"][k_idx])
            p_caps.append(math.ceil(t_raw * 100.0 - 1e-12) / 100.0)
        if not p_caps:
            return None
        trig_px = min(p_caps)
        ok, hk, dt_p = float(cb["open"][k_idx]), float(cb["high"][k_idx]), float(cb["dt_px"][k_idx])
        if ok >= trig_px:
            if not bool(cb["is_yizi_dt"][k_idx]):
                return dt_k, _sell_ret(k_idx, ok), 925
        elif hk >= trig_px + 0.01 and trig_px > dt_p + 0.01:
            return dt_k, _sell_ret(k_idx, trig_px), 1030
        return None

    k_start = pos + 1
    chained_zt = False
    if not is_zt0:
        if bool(cb["is_yizi_dt"][k_start]):
            return _defer_dt(k_start)
        o5, p5, c5 = float(cb["open"][k_start]), float(cb["pre_c"][k_start]), float(cb["close"][k_start])
        d4_strong = (c0 >= o0) and (c0 >= p0) and (o5 >= p5 * 1.005)
        if not d4_strong:
            return cb["dts"][k_start], _sell_ret(k_start, o5), 925
        if not bool(cb["is_zt"][k_start]):
            if bool(cb["is_dt"][k_start]):
                return _defer_dt(k_start)
            return cb["dts"][k_start], _sell_ret(k_start, c5), 1500
        chained_zt = True
        k_start += 1

    imm_used = False
    k = k_start
    while k < n:
        dt_k = cb["dts"][k]
        if bool(cb["is_yizi_dt"][k]):
            k += 1
            continue

        arm_dev = None
        if exit_rule == "E_Abn93_Always":
            arm_dev = 0.93
        elif exit_rule == "E_Abn93_ZTOnly":
            if is_zt0 or chained_zt:
                arm_dev = 0.93
        elif exit_rule == "E_Abn95_Always":
            arm_dev = 0.95
        elif exit_rule == "E_Abn96_ZT5b":
            if (is_zt0 or chained_zt) and reb_lt20_map.get(dt_k, False):
                arm_dev = 0.96

        if arm_dev is not None:
            hit = _check_dev_trigger(k, arm_dev)
            if hit is not None:
                return hit

        if bool(cb["is_zt"][k]):
            k += 1
            continue

        allow_imm = (not imm_used) and (cb["close"][k] > cb["open"][k]) and (cb["close"][k] >= cb["pre_c"][k])
        if allow_imm:
            imm_used = True
            k += 1
            continue

        if bool(cb["is_dt"][k]):
            return _defer_dt(k)
        return dt_k, _sell_ret(k, float(cb["close"][k])), 1500

    k = n - 1
    return cb["dts"][k], _sell_ret(k, float(cb["close"][k])), 1500


def run_4to5_b1_b2(trunc_date: Optional[str], bench: pd.DataFrame, sh2: dict, sz2: dict, cal_dts: list[str], cal_idx: dict, nmap: dict) -> dict:
    """Evaluate Direction B1 & B2 on 4to5 across G1_StrictJianchi_114, G1_FixPIT_120, G1_FixPIT_114, G1_Base_V20_114."""
    import step1_gem1_4to5_polish as g1_mod
    from w2_4to5_v20_scorecard import score_single_4to5_row

    max_dt = trunc_date or "2026-11-25"
    df_e = pd.read_parquet(f"{cm.P3_DEEP}/w2_4to5_enriched_master.parquet")
    with open(f"{cm.SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json") as f:
        holders_raw = json.load(f)
    # Physically truncate holders at max_dt
    holders = {
        c6: [x for x in lst if isinstance(x, (list, tuple)) and str(x[0])[:10] <= max_dt]
        for c6, lst in holders_raw.items()
    }
    del holders_raw

    df_tox = pd.read_parquet(f"{cm.SIM}/data/pit_reg_tox_notices_5y_complete.parquet")
    df_tox["dt_p"] = df_tox["pub_datetime_cst"].astype(str).str[:10]
    if trunc_date:
        df_tox = df_tox[df_tox["dt_p"] <= trunc_date].copy()
    df_real_tox = df_tox[df_tox["title"].astype(str).str.contains(g1_mod.TOX_RE)].copy()

    sc_cols = [
        "dt", "c6", "open", "high", "low", "close", "open_pct", "ret_1d",
        "is_zt", "hit_zt", "is_yizi_zt", "is_dt", "is_yizi_dt", "is_st_pit", "is_20cm",
        "prev_streak", "streak", "turn_pct", "real_turn_pct_t1",
        "lock_top10_pct_pre", "free_mcap_yi_t1", "amount_yi_t1",
        "hr10d_space_t1", "hr30d_space_t1", "tox_reg_30d_pre", "abn_notice_30d_pre",
        "d1_open_board_cnt_t1", "d1_first_seal_hhmm_t1", "lhb_on_t1",
        "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1", "lhb_has_quant_t1",
        "kpl_in_t1", "kpl_zt3_t1",
    ]
    sc_ds = ds.dataset(f"{cm.WAVE1_BASE}/stock_day_core_features_pit.parquet", format="parquet")
    flt_sc = (ds.field("prev_streak") >= 4) | (ds.field("dt") >= "2026-11-08")
    if trunc_date:
        flt_sc = flt_sc & (ds.field("dt") <= trunc_date)
    df_sc = pd.concat([b.to_pandas() for b in sc_ds.scanner(columns=sc_cols, filter=flt_sc, batch_size=65536, use_threads=False).to_batches()], ignore_index=True)
    df_sc["dt"] = df_sc["dt"].astype(str).str[:10]
    df_sc["c6"] = df_sc["c6"].astype(str).str.zfill(6)

    codes_needed = set(df_e["code"].astype(str).str.zfill(6))
    if not trunc_date:
        codes_needed |= set(df_sc[(df_sc["dt"] >= "2026-11-10") & (df_sc["dt"] <= "2026-11-24") & (df_sc["prev_streak"] == 4) & (df_sc["is_st_pit"] == 0) & (df_sc["is_20cm"] == 0)]["c6"])

    hyd_cols = ["dt", "c6", "kpl_in_t1", "kpl_zt3_t1", "real_turn_pct_t1", "lock_top10_pct_pre", "d1_first_seal_hhmm_t1"]
    flt_c = ds.field("c6").isin(sorted(codes_needed))
    if trunc_date:
        flt_c = flt_c & (ds.field("dt") <= trunc_date)
    df_hyd = pd.concat([b.to_pandas() for b in sc_ds.scanner(columns=hyd_cols, filter=flt_c, batch_size=65536, use_threads=False).to_batches()], ignore_index=True).drop_duplicates(["dt", "c6"], keep="first")
    df_hyd["dt"] = df_hyd["dt"].astype(str).str[:10]
    df_hyd["c6"] = df_hyd["c6"].astype(str).str.zfill(6)

    df_mk = pd.read_parquet(f"{cm.WAVE1_BASE}/market_daily_all_new_factors_pit.parquet")
    df_mk["trade_date"] = df_mk["trade_date"].astype(str).str[:10]
    if trunc_date:
        df_e = df_e[df_e["buy_date"] <= trunc_date].copy().reset_index(drop=True)
        df_mk = df_mk[df_mk["trade_date"] <= trunc_date].copy()

    b6_codes = set(df_e[df_e["B6_auc_sweet_2_7_bought"] == 1]["code"].astype(str).str.zfill(6))
    if not trunc_date:
        b6_codes |= set(df_sc[(df_sc["dt"] >= "2026-11-10") & (df_sc["dt"] <= "2026-11-24") & (df_sc["prev_streak"] == 4) & (df_sc["is_st_pit"] == 0) & (df_sc["is_20cm"] == 0)]["c6"])
    rich_bars = g1_mod.load_daily_bars_rich(b6_codes, max_dt=max_dt)
    bar_lu = {
        (c6, cb["dts"][i]): (float(cb["open"][i]), float(cb["close"][i]), float(cb["adjf"][i]))
        for c6, cb in rich_bars.items()
        for i in range(len(cb["dts"]))
    }

    if not trunc_date:
        df_ext = g1_mod.build_extension_20261110_20261124(list(df_e.columns), df_sc, df_mk, holders, df_real_tox, rich_bars, cal_dts, max_dt="2026-11-24")
        if not df_ext.empty:
            df_e = pd.concat([df_e, df_ext], ignore_index=True)

    df_e["code6"] = df_e["code"].astype(str).str.zfill(6)
    df_e["buy_date"] = df_e["buy_date"].astype(str).str[:10]
    df_e = df_e.merge(df_hyd.rename(columns={"dt": "buy_date", "c6": "code6"}), on=["buy_date", "code6"], how="left")
    del df_hyd
    df_e["kpl_in_t1"] = df_e["kpl_in_t1"].fillna(0)
    df_e["prev_real_to"] = df_e["prev_real_to"].fillna(df_e["real_turn_pct_t1"]).fillna(20.0)
    df_e["lock_top10"] = np.where(df_e["lock_top10_pct_pre"].notna() & (df_e["lock_top10_pct_pre"] > 0), df_e["lock_top10_pct_pre"], df_e["lock_top10"])

    # Scores matching RD048 parity
    df_e["v20_score"] = [score_single_4to5_row(r.to_dict())["score"] for _, r in df_e.iterrows()]
    df_e["fixed_score"] = [g1_mod.score_fixed_4to5(r.to_dict(), holders, df_real_tox)[0] for _, r in df_e.iterrows()]
    df_e["buy_price_val"] = df_e["B6_auc_sweet_2_7_px"].fillna(0.0).astype(float)

    b6 = df_e[df_e["B6_auc_sweet_2_7_bought"] == 1].copy().reset_index(drop=True)
    b6["exit_date"] = b6["exdt_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"].astype(str).str[:10]
    b6["ret_E4_020"] = b6["ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"].astype(float)
    b6["ret_E4_030"] = cm.convert_fee(b6["ret_E4_020"].to_numpy(float), 0.0020, 0.0030)
    b6["ret_E4_050"] = cm.convert_fee(b6["ret_E4_020"].to_numpy(float), 0.0020, 0.0050)
    b6 = b6[b6["exit_date"] <= (trunc_date or "2026-11-25")].copy().reset_index(drop=True)

    # Also precompute daily reb_zt_r10 < 0.20 & brk_dt_r10 on b6 (for 2026-11-10..24 too)
    risk_ctx = g1_mod.build_daily_7factor_hold_map(set(b6["code6"]), df_mk, df_sc, rich_bars, max_dt=max_dt)
    reb_lt20_map = risk_ctx[3][1]

    # Attach High-Dragon PIT notice / ex_reg5 / brk_dt_r10 flags onto b6
    f54_vals, p1_ex_vals, full_ex_vals, sreg_un_vals, jc_pq_vals, ts_pq_vals, ts_un_vals, brk_dt_vals = [], [], [], [], [], [], [], []
    # Also compute daily brk_dt_r10 cleanly from df_sc for rows where master is NaN
    sc_dts_all = sorted(set(df_sc["dt"]))
    sc_dt_pos = {d: i for i, d in enumerate(sc_dts_all)}
    brk4_all = df_sc[(df_sc["prev_streak"] >= 4) & (df_sc["is_zt"] == 0) & (df_sc["is_st_pit"] == 0) & (df_sc["is_20cm"] == 0)]
    dt_brk_stats = brk4_all.groupby("dt")["is_dt"].agg(["sum", "count"]).to_dict("index")

    for r in b6.itertuples(index=False):
        c6 = r.code6
        bd = r.buy_date
        nf = cm.query_notice_flags(c6, bd, cal_dts, cal_idx, nmap)
        p1_ex_vals.append(nf["p1_ex_reg5"])
        full_ex_vals.append(nf["full_ex_reg5"])
        sreg_un_vals.append(nf["sreg_10d_union"])
        jc_pq_vals.append(nf["jianchi_only_pq"])
        ts_pq_vals.append(nf["tox_strict_pq"])
        ts_un_vals.append(nf["tox_strict_union"])
        f54_v = float(r.f54_ex_reg5) if pd.notna(getattr(r, "f54_ex_reg5", np.nan)) else float(nf["full_ex_reg5"])
        f54_vals.append(f54_v)

        bdt = getattr(r, "f47_env_brk_dt_r10", np.nan)
        if pd.isna(bdt):
            pi = sc_dt_pos.get(bd)
            if pi is not None and pi >= 10:
                w10 = sc_dts_all[pi - 10:pi]
                s_dt = sum(int(dt_brk_stats.get(d, {}).get("sum", 0)) for d in w10)
                s_tot = sum(int(dt_brk_stats.get(d, {}).get("count", 0)) for d in w10)
                bdt = s_dt / max(1, s_tot) if s_tot > 0 else 0.0
            else:
                bdt = 0.0
        brk_dt_vals.append(float(bdt))

    b6["f54_ex_reg5_c"] = f54_vals
    b6["p1_ex_reg5"] = p1_ex_vals
    b6["full_ex_reg5"] = full_ex_vals
    b6["sreg_10d_union"] = sreg_un_vals
    b6["jianchi_only_pq"] = jc_pq_vals
    b6["tox_strict_pq"] = ts_pq_vals
    b6["tox_strict_union"] = ts_un_vals
    b6["brk_dt_r10_c"] = brk_dt_vals
    b6["reb_zt_r10_c"] = b6["f47_reb_zt_r10"].fillna(0.0).astype(float)

    # Precompute causal exits on b6: E_Abn93_Always, E_Abn93_ZTOnly, E_Abn95_Limit, E_Abn96_ZT5b, E_7Factor_Guard
    ex_dict = {
        "E4": {"exit_date": b6["exit_date"].tolist(), "ret_030": b6["ret_E4_030"].to_numpy(float), "exit_hhmm": [1500] * len(b6)},
    }
    for er in ("E_YangImm1_EOD", "E_Abn95_Limit", "E_7Factor_Guard"):
        eds, r30s, ehs = [], [], []
        for r in b6.itertuples(index=False):
            cb = rich_bars.get(r.code6)
            idx_m = sh2 if r.code6.startswith("6") else sz2
            ed, r30, eh = g1_mod.sim_causal_daily_exit(r.code6, r.buy_date, float(r.buy_price_val), cb, idx_m, er, 0.0030, risk_ctx)
            if ed is None or (trunc_date and ed > trunc_date) or ((not trunc_date) and ed > "2026-11-25"):
                ed, r30, eh = r.exit_date, float(r.ret_E4_030), 1500
            eds.append(ed); r30s.append(float(r30)); ehs.append(int(eh))
        ex_dict[er] = {"exit_date": eds, "ret_030": np.array(r30s, dtype=float), "exit_hhmm": ehs}

    for er in ("E_Abn93_Always", "E_Abn93_ZTOnly", "E_Abn96_ZT5b"):
        eds, r30s, ehs = [], [], []
        for r in b6.itertuples(index=False):
            cb = rich_bars.get(r.code6)
            idx_m = sh2 if r.code6.startswith("6") else sz2
            ed, r30, eh = sim_4to5_causal_exit_custom(r.code6, r.buy_date, float(r.buy_price_val), cb, idx_m, er, 0.0030, reb_lt20_map)
            if ed is None or (trunc_date and ed > trunc_date) or ((not trunc_date) and ed > "2026-11-25"):
                ed, r30, eh = r.exit_date, float(r.ret_E4_030), 1500
            eds.append(ed); r30s.append(float(r30)); ehs.append(int(eh))
        ex_dict[er] = {"exit_date": eds, "ret_030": np.array(r30s, dtype=float), "exit_hhmm": ehs}

    del df_sc, rich_bars, risk_ctx, holders, df_real_tox, df_tox, df_e, df_mk
    pa.default_memory_pool().release_unused()
    gc.collect()

    # Helper masks
    sc_v20 = b6["v20_score"].to_numpy(float)
    sc_fix = b6["fixed_score"].to_numpy(float)
    m_v114 = sc_v20 >= 114.0
    m_f114 = sc_fix >= 114.0
    m_f120 = sc_fix >= 120.0
    m_strict114 = m_f114 & (~b6["tox_strict_pq"].to_numpy(bool))
    m_strict114_un = m_f114 & (~b6["tox_strict_union"].to_numpy(bool))
    m_jianchi_only = m_f114 & (~b6["jianchi_only_pq"].to_numpy(bool))

    # Parity check vs rd048 _cache_g1_strict_jianchi_raw.parquet & rd048_gem1_trades.parquet
    def _sel_ss(mask: np.ndarray, sc_arr: np.ndarray, ex_key: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        d = b6[mask].copy()
        if d.empty:
            return d, d
        ex_o = ex_dict[ex_key]
        d["score"] = sc_arr[mask]
        d["exit_date"] = np.array(ex_o["exit_date"])[mask]
        d["exit_hhmm"] = np.array(ex_o["exit_hhmm"])[mask]
        d["net_ret"] = ex_o["ret_030"][mask]
        d["net_ret_030"] = d["net_ret"]
        d["net_ret_020"] = cm.convert_fee(d["net_ret_030"].to_numpy(float), 0.0030, 0.0020)
        d["net_ret_050"] = cm.convert_fee(d["net_ret_030"].to_numpy(float), 0.0030, 0.0050)
        d["code"] = d["code6"]
        d = d[d["exit_date"] > d["buy_date"]].sort_values(["buy_date", "score", "open_pct", "code"], ascending=[True, False, False, True], kind="mergesort").reset_index(drop=True)
        d["mtm_pairs_json"] = cm.build_mtm_pairs_for_trades(d, cal_dts, bar_lu, ret_col="net_ret_030")
        idx_s, fd = [], ""
        for rr in d.itertuples():
            if not fd or rr.buy_date > fd:
                idx_s.append(rr.Index)
                fd = str(rr.exit_date)
        return d, d.loc[idx_s].copy().reset_index(drop=True)

    p_sj, s_sj = _sel_ss(m_strict114, sc_fix, "E4")
    sj_ref = pd.read_parquet(f"{cm.RD048_DIR}/_cache_g1_strict_jianchi_raw.parquet")
    if trunc_date:
        sj_ref = sj_ref[sj_ref["exit_date"] <= trunc_date].copy().reset_index(drop=True)
    p_sj_s = p_sj.sort_values(["buy_date", "code"]).reset_index(drop=True)
    sj_ref_s = sj_ref.sort_values(["buy_date", "code"]).reset_index(drop=True)
    parity_45_ok = (len(p_sj_s) == len(sj_ref_s)) and (list(zip(p_sj_s["buy_date"], p_sj_s["code"])) == list(zip(sj_ref_s["buy_date"], sj_ref_s["code"])))
    max_45_diff = float(np.max(np.abs(p_sj_s["net_ret_030"].to_numpy(float) - sj_ref_s["net_ret_030"].to_numpy(float)))) if parity_45_ok and len(p_sj_s) else 0.0
    assert parity_45_ok and max_45_diff < 1e-6, f"4to5 StrictJianchi parity fail: ok={parity_45_ok} diff={max_45_diff}"

    # Signals / Masks for B1 & B2
    b_f54 = b6["f54_ex_reg5_c"].to_numpy(float) >= 2.0
    b_p1ex = b6["p1_ex_reg5"].to_numpy(int) >= 2
    b_fulex = b6["full_ex_reg5"].to_numpy(int) >= 2
    b_sreg_un = b6["sreg_10d_union"].to_numpy(bool)
    b_brk20 = b6["brk_dt_r10_c"].to_numpy(float) >= 0.20
    b_brk45 = b6["brk_dt_r10_c"].to_numpy(float) < 0.45
    b_reb15 = b6["reb_zt_r10_c"].to_numpy(float) >= 0.15
    b_reb20 = b6["reb_zt_r10_c"].to_numpy(float) >= 0.20

    # Score swap for B2: replace 4to5 `reb_zt_r10>=0.20 (+6)` with High-Dragon `brk_dt_r10>=0.20 (+12/-8)` or `+6/-6`
    sc_fix_no_reb = sc_fix - np.where(b_reb20, 6.0, 0.0)
    sc_fix_hd_brk = sc_fix_no_reb + np.where(b_brk20, 12.0, -8.0)
    sc_fix_hd_brk6 = sc_fix_no_reb + np.where(b_brk20, 6.0, -6.0)
    sc_fix_hd_addbrk = sc_fix + np.where(b_brk20, 4.0, -4.0)

    specs = [
        # Baselines
        ("G1_StrictJianchi_114", m_strict114, sc_fix, "E4", "BASE"),
        ("G1_StrictJianchi_Union_114", m_strict114_un, sc_fix, "E4", "BASE"),
        ("G1_FixPIT_120", m_f120, sc_fix, "E4", "BASE"),
        ("G1_FixPIT_114", m_f114, sc_fix, "E4", "BASE"),
        ("G1_Base_V20_114", m_v114, sc_v20, "E4", "BASE"),
        ("G1_Fix114_JianchiOnly", m_jianchi_only, sc_fix, "E4", "B1"),
        # B1: High-Dragon reg/tox redlines on StrictJianchi_114, FixPIT_120, FixPIT_114
        ("B1_SJ114_Veto_f54ExReg2", m_strict114 & (~b_f54), sc_fix, "E4", "B1_SJ114"),
        ("B1_SJ114_Veto_P1ExReg2", m_strict114 & (~b_p1ex), sc_fix, "E4", "B1_SJ114"),
        ("B1_SJ114_Veto_FullExReg2", m_strict114 & (~b_fulex), sc_fix, "E4", "B1_SJ114"),
        ("B1_SJ114_Veto_SregUnion", m_strict114 & (~b_sreg_un), sc_fix, "E4", "B1_SJ114"),
        ("B1_SJ114_FullRedlines", m_strict114_un & (~b_p1ex) & (~b_sreg_un), sc_fix, "E4", "B1_SJ114"),
        ("B1_F120_Veto_f54ExReg2", m_f120 & (~b_f54), sc_fix, "E4", "B1_F120"),
        ("B1_F120_Veto_P1ExReg2", m_f120 & (~b_p1ex), sc_fix, "E4", "B1_F120"),
        ("B1_F120_Veto_StrictJC", m_f120 & (~b6["tox_strict_pq"].to_numpy(bool)), sc_fix, "E4", "B1_F120"),
        ("B1_F114_Veto_f54ExReg2", m_f114 & (~b_f54), sc_fix, "E4", "B1_F114"),
        ("B1_F114_Veto_P1ExReg2", m_f114 & (~b_p1ex), sc_fix, "E4", "B1_F114"),
        ("B1_F114_Veto_SregUnion", m_f114 & (~b_sreg_un), sc_fix, "E4", "B1_F114"),
        # B2a: High-Dragon brk_r10 (brk_dt_r10 & reb_zt_r10)
        ("B2_SJ114_BrkDt_ge20", m_strict114 & b_brk20, sc_fix, "E4", "B2_SJ114"),
        ("B2_SJ114_BrkDt_lt45", m_strict114 & b_brk45, sc_fix, "E4", "B2_SJ114"),
        ("B2_SJ114_SwapHdBrkScore", (sc_fix_hd_brk >= 114.0) & (~b6["tox_strict_pq"].to_numpy(bool)), sc_fix_hd_brk, "E4", "B2_SJ114"),
        ("B2_SJ114_SwapHdBrk6", (sc_fix_hd_brk6 >= 114.0) & (~b6["tox_strict_pq"].to_numpy(bool)), sc_fix_hd_brk6, "E4", "B2_SJ114"),
        ("B2_SJ114_AddHdBrk4", (sc_fix_hd_addbrk >= 114.0) & (~b6["tox_strict_pq"].to_numpy(bool)), sc_fix_hd_addbrk, "E4", "B2_SJ114"),
        ("B2_SJ114_RebZt_ge15", m_strict114 & b_reb15, sc_fix, "E4", "B2_SJ114"),
        ("B2_SJ114_RebZt_ge20", m_strict114 & b_reb20, sc_fix, "E4", "B2_SJ114"),
        ("B2_F114_SwapHdBrkScore", (sc_fix_hd_brk >= 114.0), sc_fix_hd_brk, "E4", "B2_F114"),
        # B2b: 93% double-dev buffered limit sell (Always & ZTOnly) vs E_Abn95_Limit vs E_Abn96_ZT5b vs E_7Factor_Guard
        ("B2_SJ114_E_YangImm1", m_strict114, sc_fix, "E_YangImm1_EOD", "B2_SJ114"),
        ("B2_SJ114_E_Abn93_Always", m_strict114, sc_fix, "E_Abn93_Always", "B2_SJ114"),
        ("B2_SJ114_E_Abn93_ZTOnly", m_strict114, sc_fix, "E_Abn93_ZTOnly", "B2_SJ114"),
        ("B2_SJ114_E_Abn95_Limit", m_strict114, sc_fix, "E_Abn95_Limit", "B2_SJ114"),
        ("B2_SJ114_E_Abn96_ZT5b", m_strict114, sc_fix, "E_Abn96_ZT5b", "B2_SJ114"),
        ("B2_SJ114_E_7Factor", m_strict114, sc_fix, "E_7Factor_Guard", "B2_SJ114"),
        ("B2_F120_E_YangImm1", m_f120, sc_fix, "E_YangImm1_EOD", "B2_F120"),
        ("B2_F120_E_Abn93_Always", m_f120, sc_fix, "E_Abn93_Always", "B2_F120"),
        ("B2_F120_E_Abn93_ZTOnly", m_f120, sc_fix, "E_Abn93_ZTOnly", "B2_F120"),
        ("B2_F120_E_Abn95_Limit", m_f120, sc_fix, "E_Abn95_Limit", "B2_F120"),
        ("B2_F120_E_7Factor", m_f120, sc_fix, "E_7Factor_Guard", "B2_F120"),
        ("B2_F114_E_Abn93_Always", m_f114, sc_fix, "E_Abn93_Always", "B2_F114"),
        ("B2_F114_E_Abn93_ZTOnly", m_f114, sc_fix, "E_Abn93_ZTOnly", "B2_F114"),
        ("B2_F114_E_Abn95_Limit", m_f114, sc_fix, "E_Abn95_Limit", "B2_F114"),
    ]

    wins_16 = cm.WINDOWS_1116 if not trunc_date else [("FULL_5Y", "2021-11-16", trunc_date), ("IS_2123", "2021-11-16", "2023-12-31"), ("OOS_2426", "2024-01-01", trunc_date)]
    wins_24 = cm.WINDOWS_1124 if not trunc_date else []

    out_variants = {}
    ledgers_out = {}
    ref_drs = {}

    for vname, mask, sc_arr, ex_key, grp in specs:
        p_df, s_df = _sel_ss(mask, sc_arr, ex_key)
        d15_16 = cm.evaluate_d15_windows(s_df, p_df, bench, wins_16, base_fee=0.0030, ret_col="net_ret_030")
        d15_24 = cm.evaluate_d15_windows(s_df, p_df, bench, wins_24, base_fee=0.0030, ret_col="net_ret_030") if wins_24 else {}
        rets30 = s_df["net_ret_030"].to_numpy(float) if not s_df.empty else np.array([], dtype=float)
        boot = cm.bootstrap_10k(rets30, n_boot=10000, seed=42)
        dr_v, mtm_diff = cm.daily_mtm_series(s_df, cal_dts, ret_col="net_ret_030")
        if vname in ("G1_StrictJianchi_114", "G1_FixPIT_120", "G1_FixPIT_114"):
            ref_drs[vname] = dr_v
        out_variants[vname] = {
            "group": grp, "exit_rule": ex_key, "raw_n": int(len(p_df)), "ss_n": int(len(s_df)),
            "mtm_diff": round(float(mtm_diff), 10),
            "d15_1116": d15_16, "d15_1124": d15_24,
            "boot_10k_30bps": boot,
        }
        ledgers_out[vname] = (p_df, s_df)

    # Compute paired t and promotion check vs respective base
    for vname, vd in out_variants.items():
        if vd["group"] == "BASE":
            continue
        rb_k = "G1_FixPIT_120" if "F120" in vname else ("G1_FixPIT_114" if "F114" in vname or "JianchiOnly" in vname else "G1_StrictJianchi_114")
        rb = out_variants[rb_k]
        dr_v, _ = cm.daily_mtm_series(ledgers_out[vname][1], cal_dts, ret_col="net_ret_030")
        vd["paired_vs_ref"] = cm.paired_daily_ttest(dr_v, ref_drs[rb_k])
        w_cur, w_ref = vd["d15_1116"], rb["d15_1116"]
        w_champ = out_variants["G1_StrictJianchi_114"]["d15_1116"]
        is_strict_lift = (w_cur["IS_2123"]["nav"] > w_ref["IS_2123"]["nav"] + 1e-4) and (w_cur["IS_2123"]["daily_sharpe"] >= w_ref["IS_2123"]["daily_sharpe"])
        oos_ok = (w_cur["OOS_2426"]["nav"] > w_ref["OOS_2426"]["nav"] + 1e-4) and (w_cur["OOS_2426"]["daily_sharpe"] >= w_ref["OOS_2426"]["daily_sharpe"])
        beats_champ = (w_cur["FULL_5Y"]["daily_sharpe"] >= w_champ["FULL_5Y"]["daily_sharpe"]) and (w_cur["FULL_5Y"]["daily_mdd_pct"] <= w_champ["FULL_5Y"]["daily_mdd_pct"])
        ex2_ok = w_cur["FULL_5Y"]["ex2_nav"] >= w_ref["FULL_5Y"]["ex2_nav"]
        mdd_ok = w_cur["FULL_5Y"]["daily_mdd_pct"] <= w_ref["FULL_5Y"]["daily_mdd_pct"] + 0.5
        vd["ref_base"] = rb_k
        vd["promotion_check"] = {
            "is_strict_lift": is_strict_lift, "oos_ok": oos_ok, "beats_champ_sj114": beats_champ, "ex2_ok": ex2_ok, "mdd_ok": mdd_ok,
            "passes_strict_gate": bool(is_strict_lift and oos_ok and beats_champ and ex2_ok and mdd_ok),
        }

    # Check exact exit trade diffs for B2 Abn93 / Abn95 vs E4 on SJ114 & F120
    b2_diffs = {}
    for base_k, cmp_keys in [
        ("G1_StrictJianchi_114", ["B2_SJ114_E_Abn93_Always", "B2_SJ114_E_Abn93_ZTOnly", "B2_SJ114_E_Abn95_Limit", "B2_SJ114_E_Abn96_ZT5b", "B2_SJ114_E_7Factor"]),
        ("G1_FixPIT_120", ["B2_F120_E_Abn93_Always", "B2_F120_E_Abn93_ZTOnly", "B2_F120_E_Abn95_Limit"]),
    ]:
        p_b = ledgers_out[base_k][0][["buy_date", "code", "name", "exit_date", "net_ret_030"]]
        for ck in cmp_keys:
            p_c = ledgers_out[ck][0][["buy_date", "code", "exit_date", "exit_hhmm", "net_ret_030"]]
            m = p_b.merge(p_c, on=["buy_date", "code"], suffixes=("_e4", "_new"))
            chg = m[(m["exit_date_e4"] != m["exit_date_new"]) | ((m["net_ret_030_e4"] - m["net_ret_030_new"]).abs() > 1e-5)]
            b2_diffs[ck] = [
                {
                    "buy_date": r.buy_date, "code": r.code, "name": r.name,
                    "e4_exit": r.exit_date_e4, "e4_pct": round(float(r.net_ret_030_e4) * 100, 2),
                    "new_exit": f"{r.exit_date_new}@{r.exit_hhmm}", "new_pct": round(float(r.net_ret_030_new) * 100, 2),
                    "delta_pp": round((float(r.net_ret_030_new) - float(r.net_ret_030_e4)) * 100, 2),
                }
                for r in chg.itertuples(index=False)
            ]

    return {
        "parity_4to5": {"strict_jianchi_ok": parity_45_ok, "max_ret_diff": round(max_45_diff, 10)},
        "variants": out_variants,
        "b2_trade_diffs": b2_diffs,
        "ledgers": ledgers_out,
        "b6_df": b6,
        "bar_lu": bar_lu,
    }


def run_3to4_b1(trunc_date: Optional[str], bench: pd.DataFrame, cal_dts: list[str], cal_idx: dict, nmap: dict) -> dict:
    """Evaluate Direction B1 High-Dragon regulatory/notice redlines on 3to4 V4.1 (95t) & V4.2 (85t)."""
    import _f23_common as fcm
    import run_front2_3to4 as f2
    import exit_factor_engine as efe

    with open(f"{cm.F1_3TO4}/pit_exit_cache_full.pkl", "rb") as f:
        _c34 = pickle.load(f)
    codes = {str(e["code"]).zfill(6) for e in _c34["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0}
    if trunc_date:
        codes = {str(e["code"]).zfill(6) for e in _c34["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0 and str(e["buy_date"]) <= trunc_date}
    del _c34

    ctx = fcm.load_filtered_5m_and_dmap(codes, load_5m=True, load_sub2=False)
    if trunc_date:
        # Physically truncate ctx + rebuild s34_ctx <= trunc_date
        import _truncation_proof_20241231 as tp34
        # Load & physically truncate directly using tp34 helper logic inline
        ctx["dmap"] = {k: v for k, v in ctx["dmap"].items() if k[1] <= trunc_date}
        ctx["bars_5m"] = {k: v for k, v in ctx["bars_5m"].items() if k[1] <= trunc_date}
        for c6, cs in ctx["code_series"].items():
            kn = sum(1 for d in cs["dts"] if d <= trunc_date)
            cs["dts"] = cs["dts"][:kn]
            cs["dt_to_pos"] = {d: i for i, d in enumerate(cs["dts"])}
            for ak in ("open", "high", "low", "close", "adj_close", "adjf", "pre_c", "zt_px", "dt_px", "is_zt", "is_dt", "is_yizi_zt", "is_yizi_dt"):
                cs[ak] = cs[ak][:kn]
        sys.path.insert(0, cm.WAVE1_BASE)
        sys.path.insert(0, f"{cm.SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a4_pairwise_interactions")
        sys.path.insert(0, f"{cm.SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5")
        import _w2a4_data_and_features as w2f
        import _common_rd036 as c36
        import run_m3_m4_3way_4way_trees as m34
        with open(f"{cm.F1_3TO4}/pit_exit_cache_full.pkl", "rb") as f:
            cache = pickle.load(f)
        untrig_c6 = {str(e["code"]).zfill(6) for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0 and e["buy_px"] is None and str(e["buy_date"]) <= trunc_date}
        trig_excl = {(str(e["code"]).zfill(6), str(e["buy_date"])) for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0 and e["buy_px"] is not None and str(e["buy_date"]) <= trunc_date}
        cache["bars_5m_map"] = {k: v for k, v in cache["bars_5m_map"].items() if k[1] <= trunc_date}
        for k, arr in ctx["bars_5m"].items():
            if k not in cache["bars_5m_map"] and (k[0] in untrig_c6) and (k not in trig_excl) and k not in {("002896", "2022-08-03"), ("603887", "2024-10-31")}:
                cache["bars_5m_map"][k] = arr
        for c6, cb in cache["code_bars_ext"].items():
            orig_len = len(cb["dts"])
            kn = sum(1 for d in cb["dts"] if str(d) <= trunc_date)
            for ak, av in list(cb.items()):
                if isinstance(av, (np.ndarray, list)) and len(av) == orig_len:
                    cb[ak] = av[:kn]
                elif isinstance(av, dict) and len(av) == orig_len:
                    cb[ak] = {k: v for k, v in av.items() if str(k) <= trunc_date}
        cache_all = dict(cache)
        patched = []
        for e in cache["buy_entries"]:
            if str(e["buy_date"]) > trunc_date:
                continue
            ec = dict(e)
            if ec["skel"] and ec["sc_v40"] >= 90.0 and ec["buy_px"] is None:
                ec["buy_px"] = 1.0
            patched.append(ec)
        cache_all["buy_entries"] = patched
        states = efe.precompute_trade_day_states(cache_all, min_score=90.0)
        dt_tables = fcm.build_lean_dt_tables(ctx["code_series"])
        cal_full_dts = [d for d in ctx["v20_ctx"]["bench"]["trade_date"].tolist() if d <= trunc_date]
        m_full = w2f.load_master_with_sim_cols(trunc_date)
        m_full = w2f.attach_pit_community_1d_burst(m_full, cal_full_dts, end_cutoff=trunc_date)
        m_full, _, _ = w2f.build_mechanism_interactions(m_full)
        m_full["mkt10_zt_est_t1"] = (m_full["L1_zt_cnt_t1"] - m_full["mkt20_zt_cnt_t1"]).astype(np.float32)
        sub12 = m_full[m_full["strategy"] == "1to2"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        sub12 = w2f.attach_strategy_sim_cols(sub12, "1to2")
        base_dyn_cols = w2f.select_base_single_factors_for_dyn(sub12)
        if "mkt10_zt_est_t1" not in base_dyn_cols:
            base_dyn_cols.append("mkt10_zt_est_t1")
        df34_m = m_full[m_full["strategy"] == "3to4"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        del m_full, sub12
        df34_m = w2f.attach_strategy_sim_cols(df34_m, "3to4")
        oh = pd.read_parquet(f"{cm.SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125/pool_3to4_oldhot.parquet")
        oh["buy_date"] = oh["buy_date"].astype(str).str[:10]
        oh["code"] = oh["code"].astype(str).str.zfill(6)
        oh = oh[oh["buy_date"] <= trunc_date].sort_values(["buy_date", "code"]).reset_index(drop=True)
        ex_oh = [c for c in ["buy_price", "prev_is_yizi", "buyable_open", "v20_pen"] if c in oh.columns and c not in df34_m.columns]
        if ex_oh:
            df34_m = df34_m.merge(oh[["buy_date", "code"] + ex_oh], on=["buy_date", "code"], how="left")
        df34_m["net_ret_020"] = pd.to_numeric(df34_m["net_ret"], errors="coerce").astype(np.float64)
        df34_m["net_ret_030"] = c36.convert_fee(df34_m["net_ret_020"], 0.0030)
        df34_m["net_ret"] = df34_m["net_ret_030"]
        is_yz = pd.to_numeric(df34_m["open_pct"], errors="coerce").fillna(0.0) >= 0.095
        if "prev_is_yizi" in df34_m.columns:
            is_yz = is_yz | df34_m["prev_is_yizi"].fillna(False).to_numpy(bool)
        df34_m["is_yizi"] = is_yz.astype(bool)
        df34_m["can_buy_hygiene"] = (~df34_m["is_yizi"]) & df34_m["sim_ok"].fillna(True).to_numpy(bool) & df34_m["net_ret"].notna()
        df34_m["c6"] = df34_m["code"].astype(str).str.zfill(6)
        df34_m["bd"] = df34_m["buy_date"].astype(str).str[:10]
        acols34 = sorted([c for c in df34_m.columns if c.startswith("s34_")])
        bp34 = list(dict.fromkeys(base_dyn_cols + acols34))
        r4 = m34.run_wf_3way_4way_and_trees(df34_m, bp34, min_leaf=20, min_days=8, order=4, run_trees=False)
        df34_m["m4_mine_bl15"] = r4["mine_bl"][15]
        master_map = {(r.bd, r.c6): {"s34_af_20": float(r.s34_af_20) if pd.notna(r.s34_af_20) else 0.0, "mkt10_zt_est_t1": float(r.mkt10_zt_est_t1) if pd.notna(r.mkt10_zt_est_t1) else 50.0, "m4_mine_bl15": bool(r.m4_mine_bl15)} for r in df34_m.itertuples(index=False)}
        cand_df = cache["cand_df"]
        entries = []
        for e in cache["buy_entries"]:
            if (not e["skel"]) or (e["sc_v40"] < 90.0):
                continue
            bd = str(e["buy_date"])
            if not ("2021-11-16" <= bd <= trunc_date):
                continue
            c6 = str(e["code"]).zfill(6)
            mm = master_map.get((bd, c6), {"s34_af_20": 0.0, "mkt10_zt_est_t1": 50.0, "m4_mine_bl15": False})
            entries.append({
                "entry": e, "bd": bd, "c6": c6, "name": str(e["name"]), "score": float(e["sc_v40"]),
                "prio_tie": float(cand_df["prio_3to4"].iloc[e["idx"]]),
                "priority_score": float(e["sc_v40"] * 10.0 + float(cand_df["prio_3to4"].iloc[e["idx"]]) * 0.1),
                "orig_buy_px": float(e["buy_px"]) if e["buy_px"] is not None else np.nan,
                "orig_buy_hhmm": int(e["buy_hhmm"]) if e["buy_hhmm"] is not None else 0,
                "state_map": states.get(e["idx"], {}), **mm,
            })
        entries.sort(key=lambda x: (x["bd"], -x["priority_score"], x["c6"]))
        s34_ctx = {"cache": cache, "cache_all": cache_all, "dt_tables": dt_tables, "entries": entries}
        f2.attach_causal_loo_s34_af20(ctx, s34_ctx)
        del df34_m, r4
    else:
        s34_ctx = f2.build_3to4_surgical_ctx(ctx)
        f2.attach_causal_loo_s34_af20(ctx, s34_ctx)

    # Build bar_lu for exact 3to4 MTM
    bar_lu = {
        (c6, str(d)[:10]): (float(r["open"]), float(r["close"]), float(r["adjf"]))
        for (c6, d), r in ctx["dmap"].items()
    }
    cdf = s34_ctx["cache"]["cand_df"]
    for it in s34_ctx["entries"]:
        nf = cm.query_notice_flags(it["c6"], it["bd"], cal_dts, cal_idx, nmap)
        row = cdf.iloc[it["entry"]["idx"]]
        it["has_ex_reg"] = bool(row["has_ex_reg"])
        it["p1_ex_reg5"] = nf["p1_ex_reg5"]
        it["full_ex_reg5"] = nf["full_ex_reg5"]
        it["sreg_10d_union"] = nf["sreg_10d_union"]
        it["jianchi_only"] = nf["jianchi_only_pq"] or nf["jianchi_only_union"]
        it["tox_strict"] = nf["tox_strict_pq"] or nf["tox_strict_union"]

    b_base = {"trig_mult": 1.065, "cancel_hhmm": 1030, "hi_open_mode": "direct_0925"}
    e_v41 = {"d5_mode": "base", "zt_sl_mode": "base"}
    e_v42 = {"d5_mode": "base", "zt_sl_mode": "prevc_tp1_m6_1000"}

    def _run_34(vid: str, base_ver: str, fn_flt=None, exit_override: str = "none") -> tuple[pd.DataFrame, pd.DataFrame]:
        ecfg = e_v41 if base_ver == "V41" else e_v42
        rows = []
        for it in s34_ctx["entries"]:
            if base_ver == "V42":
                ok_v42 = (not it["m4_mine_bl15"]) and ((it["score"] - (it["s34_af_20"] if it.get("causal_drop_af20", False) else 0.0)) >= 90.0)
                if not ok_v42:
                    continue
            if fn_flt is not None and not fn_flt(it):
                continue
            binfo = f2._sim_buy_3to4(it, ctx, s34_ctx, b_base)
            if binfo is None:
                continue
            rec = f2._sim_exit_3to4(it, ctx, s34_ctx, binfo, ecfg)
            if trunc_date and rec["exit_date"] > trunc_date:
                continue
            # Optional B1 holding-period 09:25 exit transplant (XF07_new or XF09_ex2)
            if exit_override != "none":
                st_map = it["state_map"]
                cb = s34_ctx["cache"]["code_bars_ext"][it["c6"]]
                pos = it["entry"]["pos"]
                for k in sorted(st_map.keys()):
                    dt_k = str(cb["dts"][k])
                    if dt_k <= it["bd"] or dt_k >= rec["exit_date"]:
                        continue
                    if bool(cb["is_yizi_dt"][k]):
                        continue
                    st = st_map[k]
                    trig = (bool(st.get("xf07_new")) if exit_override == "XF07_0925" else bool(st.get("xf09_2")))
                    if trig:
                        ok = float(cb["open"][k])
                        dtk = round(float(cb["pre_c"][k]) * 0.90, 2)
                        if ok > dtk + 0.005:
                            bp_f = float(rec["buy_price"])
                            nret20 = (ok * float(cb["adjf"][k])) / (bp_f * float(cb["adjf"][pos])) * 0.9980 - 1.0
                            rec["exit_date"] = dt_k
                            rec["exit_hhmm"] = 925
                            rec["exit_price"] = round(ok, 2)
                            rec["net_ret_020"] = float(nret20)
                            rec["exit_reason"] = exit_override
                            break
            r30 = float(cm.convert_fee(rec["net_ret_020"], 0.0020, 0.0030))
            rec["net_ret_030"] = r30
            rec["net_ret"] = r30
            rec["buy_price_val"] = float(rec["buy_price"])
            rows.append(rec)

        if not rows:
            return pd.DataFrame(), pd.DataFrame()
        df_p = pd.DataFrame(rows).sort_values(["buy_date", "buy_hhmm", "priority_score", "code"], ascending=[True, True, False, True], kind="mergesort").reset_index(drop=True)
        df_p["mtm_pairs_json"] = cm.build_mtm_pairs_for_trades(df_p, cal_dts, bar_lu, ret_col="net_ret_030")
        taken, fdt, fhh = [], "", 0
        for rr in df_p.itertuples():
            if (not fdt) or (rr.buy_date > fdt) or (rr.buy_date == fdt and int(rr.buy_hhmm) > fhh):
                taken.append(rr.Index)
                fdt, fhh = str(rr.exit_date), int(rr.exit_hhmm)
        df_s = df_p.loc[taken].copy().reset_index(drop=True)
        return df_p, df_s

    # Parity verification on V4.1 & V4.2
    p41, s41 = _run_34("V41_Base", "V41")
    p42, s42 = _run_34("V42_Base", "V42")
    if not trunc_date:
        ref41 = pd.read_csv(f"{cm.PARTC_V191}/ledger_3to4_v41_clean.csv", dtype={"code": str})
        ref41["code"] = ref41["code"].str.zfill(6)
        assert len(s41) == len(ref41) and float(np.max(np.abs(s41["net_ret_020"].to_numpy() - ref41["net_ret"].to_numpy()))) < 1e-6
        ref42 = pd.read_parquet(f"{cm.RD039_F23}/rd039_f23_best_trades.parquet")
        ref42 = ref42[ref42["strategy"] == "3to4"].reset_index(drop=True)
        assert len(s42) == len(ref42) and float(np.max(np.abs(s42["net_ret_030"].to_numpy() - ref42["net_ret_030"].to_numpy()))) < 1e-6

    specs34 = [
        ("3to4_V41_Base", "V41", None, "none"),
        ("3to4_V41_P1ExReg5_ge2", "V41", lambda it: it["p1_ex_reg5"] < 2, "none"),
        ("3to4_V41_FullExReg5_ge2", "V41", lambda it: it["full_ex_reg5"] < 2, "none"),
        ("3to4_V41_VetoT11_HasEx", "V41", lambda it: not it["has_ex_reg"], "none"),
        ("3to4_V41_VetoSregUnion", "V41", lambda it: not it["sreg_10d_union"], "none"),
        ("3to4_V41_VetoJianchiOnly", "V41", lambda it: not it["jianchi_only"], "none"),
        ("3to4_V41_VetoToxStrict", "V41", lambda it: not it["tox_strict"], "none"),
        ("3to4_V41_Exit_XF07_0925", "V41", None, "XF07_0925"),
        ("3to4_V41_Exit_XF09_0925", "V41", None, "XF09_0925"),
        ("3to4_V42_Base", "V42", None, "none"),
        ("3to4_V42_P1ExReg5_ge2", "V42", lambda it: it["p1_ex_reg5"] < 2, "none"),
        ("3to4_V42_FullExReg5_ge2", "V42", lambda it: it["full_ex_reg5"] < 2, "none"),
        ("3to4_V42_VetoT11_HasEx", "V42", lambda it: not it["has_ex_reg"], "none"),
        ("3to4_V42_VetoSregUnion", "V42", lambda it: not it["sreg_10d_union"], "none"),
        ("3to4_V42_VetoJianchiOnly", "V42", lambda it: not it["jianchi_only"], "none"),
        ("3to4_V42_VetoToxStrict", "V42", lambda it: not it["tox_strict"], "none"),
        ("3to4_V42_Exit_XF07_0925", "V42", None, "XF07_0925"),
        ("3to4_V42_Exit_XF09_0925", "V42", None, "XF09_0925"),
    ]
    wins = cm.WINDOWS_1116 if not trunc_date else [("FULL_5Y", "2021-11-16", trunc_date), ("IS_2123", "2021-11-16", "2023-12-31"), ("OOS_2426", "2024-01-01", trunc_date)]
    out34 = {}
    ref_drs = {}
    led34 = {}
    for vid, bv, fn, ex_ov in specs34:
        p_df, s_df = _run_34(vid, bv, fn, ex_ov)
        d15 = cm.evaluate_d15_windows(s_df, p_df, bench, wins, base_fee=0.0030, ret_col="net_ret_030")
        rets30 = s_df["net_ret_030"].to_numpy(float) if not s_df.empty else np.array([], dtype=float)
        dr_v, mtm_diff = cm.daily_mtm_series(s_df, cal_dts, ret_col="net_ret_030")
        if vid in ("3to4_V41_Base", "3to4_V42_Base"):
            ref_drs[vid] = dr_v
        out34[vid] = {
            "base_ver": bv, "raw_n": int(len(p_df)), "ss_n": int(len(s_df)),
            "mtm_diff": round(float(mtm_diff), 10), "d15": d15,
            "boot_10k_30bps": cm.bootstrap_10k(rets30, n_boot=10000, seed=42),
            "hefu_in_slot": bool(((s_df["buy_date"] == "2025-10-31") & (s_df["code"] == "603122")).any()) if not s_df.empty else False,
            "aiai_in_slot": bool(((s_df["buy_date"] == "2024-03-08") & (s_df["code"] == "603580")).any()) if not s_df.empty else False,
        }
        led34[vid] = (p_df, s_df)

    for vid, vd in out34.items():
        if vid.endswith("_Base"):
            continue
        rb_k = "3to4_V41_Base" if vd["base_ver"] == "V41" else "3to4_V42_Base"
        rb = out34[rb_k]
        dr_v, _ = cm.daily_mtm_series(led34[vid][1], cal_dts, ret_col="net_ret_030")
        vd["paired_vs_ref"] = cm.paired_daily_ttest(dr_v, ref_drs[rb_k])
        w_cur, w_ref = vd["d15"], rb["d15"]
        is_ok = w_cur["IS_2123"]["nav"] >= w_ref["IS_2123"]["nav"] and w_cur["IS_2123"]["daily_sharpe"] >= w_ref["IS_2123"]["daily_sharpe"]
        oos_ok = w_cur["OOS_2426"]["nav"] >= w_ref["OOS_2426"]["nav"] and w_cur["OOS_2426"]["daily_sharpe"] >= w_ref["OOS_2426"]["daily_sharpe"]
        strict_better = (w_cur["FULL_5Y"]["nav"] > w_ref["FULL_5Y"]["nav"]) or (w_cur["FULL_5Y"]["daily_sharpe"] > w_ref["FULL_5Y"]["daily_sharpe"] + 0.02)
        ex2_ok = w_cur["FULL_5Y"]["ex2_nav"] >= w_ref["FULL_5Y"]["ex2_nav"]
        vd["ref_base"] = rb_k
        vd["promotion_check"] = {
            "is_ok": is_ok, "oos_ok": oos_ok, "strict_better": strict_better, "ex2_ok": ex2_ok,
            "passes_strict_gate": bool(is_ok and oos_ok and strict_better and ex2_ok),
        }

    # Check exact diff vs V4.2 for interesting filters
    v42_diffs = {}
    s42_b = led34["3to4_V42_Base"][1][["buy_date", "code", "name", "net_ret_030"]]
    for ck in ("3to4_V42_P1ExReg5_ge2", "3to4_V42_FullExReg5_ge2", "3to4_V42_VetoT11_HasEx", "3to4_V42_VetoJianchiOnly", "3to4_V42_VetoToxStrict"):
        s_c = led34[ck][1][["buy_date", "code", "name", "net_ret_030"]]
        b_keys = set(zip(s42_b.buy_date, s42_b.code))
        c_keys = set(zip(s_c.buy_date, s_c.code))
        rem = s42_b[s42_b.apply(lambda r: (r.buy_date, r.code) not in c_keys, axis=1)]
        add = s_c[s_c.apply(lambda r: (r.buy_date, r.code) not in b_keys, axis=1)]
        v42_diffs[ck] = {
            "removed": [{"buy_date": r.buy_date, "code": r.code, "name": r.name, "pct": round(r.net_ret_030 * 100, 2)} for r in rem.itertuples(index=False)],
            "added": [{"buy_date": r.buy_date, "code": r.code, "name": r.name, "pct": round(r.net_ret_030 * 100, 2)} for r in add.itertuples(index=False)],
        }

    del ctx, s34_ctx
    gc.collect()
    return {"variants": out34, "v42_diffs": v42_diffs, "ledgers": led34}


def run_b3_overlap_and_portfolio(res45: dict, res34: dict, bench: pd.DataFrame) -> dict:
    """(B3) Consecutive-day same-stock overlap forensics + full V20/V21 6-strategy portfolio integration."""
    import _rd048_w2_lib as w2
    import _rd038_engine as eng

    cache = w2.load_rd038_cache()
    idx_5y = {d: i for i, d in enumerate(cache["cal_5y"])}

    # 1. Forensic same-stock sequence 4to5 <-> High-Dragon <-> 3to4
    b6 = res45["b6_df"]
    dh = cache["pools_ext"]["high"].copy()
    dh["buy_date"] = dh["buy_date"].astype(str).str[:10]
    dh["code"] = dh["code"].astype(str).str.zfill(6)
    dh_pass = dh[dh["orig_score"] >= 88.0].copy()

    g1_sj_raw = res45["ledgers"]["G1_StrictJianchi_114"][0]
    g1_fp_raw = res45["ledgers"]["G1_FixPIT_114"][0]
    sj_keys = set(zip(g1_sj_raw["buy_date"], g1_sj_raw["code"]))
    fp_keys = set(zip(g1_fp_raw["buy_date"], g1_fp_raw["code"]))

    m_45_hi = dh_pass[["buy_date", "exit_date", "code", "name", "orig_score", "net_ret_030"]].merge(
        b6[["buy_date", "exit_date", "code6", "fixed_score", "v20_score", "ret_E4_030", "is_zt_today"]],
        left_on="code", right_on="code6", suffixes=("_hi", "_45"),
    )
    m_45_hi["cal_gap_days"] = (pd.to_datetime(m_45_hi["buy_date_hi"]) - pd.to_datetime(m_45_hi["buy_date_45"])).dt.days
    seq_pairs = m_45_hi[(m_45_hi["cal_gap_days"] >= 1) & (m_45_hi["cal_gap_days"] <= 7)].sort_values(["buy_date_45", "code"]).copy()
    seq_records = []
    for r in seq_pairs.itertuples(index=False):
        in_sj = (r.buy_date_45, r.code) in sj_keys
        in_fp = (r.buy_date_45, r.code) in fp_keys
        ex45 = str(r.exit_date_45)
        collides_if_45_held = ex45 > str(r.buy_date_hi)
        seq_records.append({
            "code": r.code, "name": r.name,
            "d4_buy_45": r.buy_date_45, "d4_exit_45": ex45, "d4_zt_45": bool(r.is_zt_today),
            "fix_sc_45": int(r.fixed_score), "in_Fix114": in_fp, "in_StrictJianchi": in_sj,
            "ret_45_pct": round(float(r.ret_E4_030) * 100.0, 2),
            "hi_buy": r.buy_date_hi, "hi_exit": str(r.exit_date_hi), "hi_sc": int(r.orig_score),
            "ret_hi_pct": round(float(r.net_ret_030) * 100.0, 2),
            "cal_gap_days": int(r.cal_gap_days),
            "collides_if_45_held": collides_if_45_held,
        })
    seq_df = pd.DataFrame(seq_records)
    seq_stats = {}
    if not seq_df.empty:
        sub_fp = seq_df[seq_df["in_Fix114"]]
        sub_sj = seq_df[seq_df["in_StrictJianchi"]]
        sub_zt = sub_fp[sub_fp["d4_zt_45"]]
        sub_nozt = sub_fp[~sub_fp["d4_zt_45"]]
        seq_stats = {
            "total_1to7d_pairs_in_b6": int(len(seq_df)),
            "in_FixPIT_114_n": int(len(sub_fp)),
            "in_FixPIT_114_collides_with_High": int(sub_fp["collides_if_45_held"].sum()),
            "in_FixPIT_114_hi_wr_pct": round(float((sub_fp["ret_hi_pct"] > 0).mean() * 100.0), 2) if not sub_fp.empty else 0.0,
            "in_FixPIT_114_hi_mean_pct": round(float(sub_fp["ret_hi_pct"].mean()), 2) if not sub_fp.empty else 0.0,
            "in_StrictJianchi_n": int(len(sub_sj)),
            "in_StrictJianchi_collides_with_High": int(sub_sj["collides_if_45_held"].sum()),
            "in_StrictJianchi_hi_wr_pct": round(float((sub_sj["ret_hi_pct"] > 0).mean() * 100.0), 2) if not sub_sj.empty else 0.0,
            "in_StrictJianchi_hi_mean_pct": round(float(sub_sj["ret_hi_pct"].mean()), 2) if not sub_sj.empty else 0.0,
            "after_45_ZT_seal_hi_mean_pct": round(float(sub_zt["ret_hi_pct"].mean()), 2) if not sub_zt.empty else 0.0,
            "after_45_noZT_hi_mean_pct": round(float(sub_nozt["ret_hi_pct"].mean()), 2) if not sub_nozt.empty else 0.0,
        }

    # 2. Full V20.0 & V21.0 6-strategy portfolio test (..2026-11-16)
    base_res = {}
    for bname, bcfg in [("V20_0", w2.CFG_V20), ("V21_0", w2.CFG_V21)]:
        tr0, w0 = w2.run_tier_or_empty_sim(cache, bcfg, None, mode="tier", fee_mode="030")
        ev0 = w2.compute_dr_and_eval(bname, "BASE", tr0, cache, waits_n=len(w0))
        tr50, _ = w2.run_tier_or_empty_sim(cache, bcfg, None, mode="tier", fee_mode="050")
        ev50 = w2.compute_dr_and_eval(bname, "BASE", tr50, cache)
        base_res[bname] = {"cfg": bcfg, "tr": tr0, "ev": ev0, "ev50": ev50}

    # Test key 4to5 ledgers (Baseline StrictJianchi, F120, plus any B1/B2 top variants) at Pos1..Pos5
    cand_45_keys = [
        "G1_StrictJianchi_114", "G1_Fix114_JianchiOnly", "G1_FixPIT_120", "G1_FixPIT_114",
        "B1_SJ114_Veto_P1ExReg2", "B2_SJ114_E_Abn93_ZTOnly", "B2_SJ114_E_Abn95_Limit",
        "B2_SJ114_E_7Factor", "B2_F120_E_Abn93_ZTOnly", "B2_F114_E_Abn93_ZTOnly",
    ]
    positions = [
        ("Pos1_TopFirst", "tier", 0.0, 0),
        ("Pos2_After34High_Pre23", "tier", 2.5, 0),
        ("Pos2B_Between34AndHigh", "tier", 1.5, 0),  # 4to5 > High!
        ("Pos3_After23_Pre20cm12", "tier", 4.5, 0),
        ("Pos5_EmptyDayOnly", "empty_fill", 99.0, 0),
    ]
    port_rows = []
    for bname in ("V20_0", "V21_0"):
        b = base_res[bname]
        w_b5y = b["ev"]["windows"]["FULL_5Y"]
        w_bwf = b["ev"]["windows"]["WF_2326"]
        for gk in cand_45_keys:
            gdf = res45["ledgers"][gk][0]
            for pos_nm, smode, pr_v, ph_v in positions:
                cname = f"{bname}__{gk}__{pos_nm}"
                ep30 = w2.prepare_gem_pool_for_rd038(gdf, "4to5", f"4to5_{gk}", pr_v, ph_v, idx_5y, True, "030")
                tr30, w30 = w2.run_tier_or_empty_sim(cache, b["cfg"], ep30, mode=smode, fee_mode="030")
                ev30 = w2.compute_dr_and_eval(cname, "P1B", tr30, cache, ref_dr_wf=b["ev"]["dr_wf"], waits_n=len(w30))

                ep50 = w2.prepare_gem_pool_for_rd038(gdf, "4to5", f"4to5_{gk}", pr_v, ph_v, idx_5y, True, "050")
                tr50, _ = w2.run_tier_or_empty_sim(cache, b["cfg"], ep50, mode=smode, fee_mode="050")
                ev50 = w2.compute_dr_and_eval(cname, "P1B", tr50, cache)

                kb = {(r.buy_date, r.code, r.strategy): r for r in b["tr"].itertuples(index=False)}
                kn = {(r.buy_date, r.code, r.strategy): r for r in tr30.itertuples(index=False)}
                rem = [kb[k] for k in sorted(kb) if k not in kn and kb[k].buy_date >= eng.WF_START]
                add = [kn[k] for k in sorted(kn) if k not in kb and kn[k].buy_date >= eng.WF_START]
                worst_rem = min(rem, key=lambda r: float(r.net_ret)) if rem else None
                best_add = max(add, key=lambda r: float(r.net_ret)) if add else None

                w5, wf, y25, y26, h26 = (
                    ev30["windows"]["FULL_5Y"], ev30["windows"]["WF_2326"],
                    ev30["windows"]["Y2025_2026"], ev30["windows"]["Y2026"], ev30["windows"]["Y2026_H2"],
                )
                raw_mult_wf = wf["nav"] / max(1e-12, w_bwf["nav"])
                cf_both = raw_mult_wf
                if worst_rem and float(worst_rem.net_ret) < 0:
                    cf_both *= (1.0 + float(worst_rem.net_ret))
                if best_add and float(best_add.net_ret) > 0:
                    cf_both /= (1.0 + float(best_add.net_ret))

                n_hi_base = int((b["tr"]["strategy"] == "high").sum())
                n_hi_new = int((tr30["strategy"] == "high").sum())
                n_45_new = int((tr30["strategy"] == "4to5").sum())
                port_rows.append({
                    "combo": cname, "base": bname, "gem": gk, "pos": pos_nm,
                    "n_5y": w5["n"], "n_45": n_45_new, "n_hi": n_hi_new, "hi_delta": n_hi_new - n_hi_base,
                    "nav_5y": w5["nav"], "sh_5y": w5["daily_sharpe"], "mdd_5y": w5["daily_mdd_pct"],
                    "nav_wf": wf["nav"], "ex5_wf": wf["ex_top5_nav"], "sh_wf": wf["daily_sharpe"], "mdd_wf": wf["daily_mdd_pct"],
                    "nav_2526": y25["nav"], "nav_26": y26["nav"], "nav_26h2": h26["nav"],
                    "nav_wf_50bps": ev50["windows"]["WF_2326"]["nav"],
                    "paired_t_wf": ev30["vs_v20_wf"]["paired_t"], "paired_p_wf": ev30["vs_v20_wf"]["paired_p_2sided"],
                    "mult_wf": round(raw_mult_wf, 4), "mult_wf_ex_both": round(cf_both, 4),
                })

    base_port_summary = {}
    for bname in ("V20_0", "V21_0"):
        ev = base_res[bname]["ev"]
        ev50 = base_res[bname]["ev50"]
        base_port_summary[bname] = {
            "n_high": int((base_res[bname]["tr"]["strategy"] == "high").sum()),
            "windows_030": ev["windows"],
            "wf_nav_50bps": ev50["windows"]["WF_2326"]["nav"],
        }

    return {
        "seq_4to5_high_records": seq_records,
        "seq_4to5_high_stats": seq_stats,
        "base_portfolios": base_port_summary,
        "portfolio_grid": port_rows,
    }


def eval_dirB(trunc_date: Optional[str] = None, skip_portfolio: bool = False) -> dict:
    t0 = time.time()
    max_dt = trunc_date or "2026-11-25"
    bench, sh2, sz2, csi, all_dts = cm.load_bench_and_index(max_dt=max_dt)
    cal_dts = bench["trade_date"].tolist()
    cal_idx = {d: i for i, d in enumerate(cal_dts)}
    nmap = cm.load_pit_notice_maps(max_dt=max_dt)

    res45 = run_4to5_b1_b2(trunc_date, bench, sh2, sz2, cal_dts, cal_idx, nmap)
    res34 = run_3to4_b1(trunc_date, bench, cal_dts, cal_idx, nmap)
    res_b3 = {} if (trunc_date or skip_portfolio) else run_b3_overlap_and_portfolio(res45, res34, bench)

    ledgers45 = res45.pop("ledgers")
    res45.pop("b6_df", None)
    res45.pop("bar_lu", None)
    ledgers34 = res34.pop("ledgers")

    return {
        "dirB_4to5": res45,
        "dirB_3to4": res34,
        "dirB_b3_overlap_portfolio": res_b3,
        "ledgers_4to5": ledgers45,
        "ledgers_3to4": ledgers34,
        "elapsed_sec": round(time.time() - t0, 2),
        "rss_mb": cm.rss_mb(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trunc-date", default="")
    parser.add_argument("--out-json", default="")
    args = parser.parse_args()

    trunc = args.trunc_date.strip() or None
    out = eval_dirB(trunc_date=trunc)
    l45 = out.pop("ledgers_4to5")
    l34 = out.pop("ledgers_3to4")

    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(cm.sanitize_json(out), f, ensure_ascii=False)
        return

    with open(f"{cm.OUT_DIR}/dirB_results.json", "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(out), f, ensure_ascii=False, indent=2)
    with open(f"{cm.OUT_DIR}/_cache_dirB_ledgers.pkl", "wb") as f:
        pickle.dump({"ledgers_4to5": l45, "ledgers_3to4": l34}, f)

    print(f"[DirB DONE in {out['elapsed_sec']}s] RSS={out['rss_mb']} MB | 4to5 parity={out['dirB_4to5']['parity_4to5']}")
    print("\n=== 4to5 B1/B2 Variants (..2026-11-16, 30bps primary & 50bps stress) ===")
    r45 = []
    for vn, vd in out["dirB_4to5"]["variants"].items():
        w5 = vd["d15_1116"]["FULL_5Y"]
        wis = vd["d15_1116"]["IS_2123"]
        woos = vd["d15_1116"]["OOS_2426"]
        w26 = vd["d15_1116"]["Y2026"]
        wh2 = vd["d15_1116"]["Y2026_H2"]
        gate = vd.get("promotion_check", {}).get("passes_strict_gate", "-")
        r45.append({
            "vid": vn, "n": w5["ss_n"], "wr": w5["wr_pct"], "plr": w5["plr"],
            "nav5y": w5["nav"], "ex2": w5["ex2_nav"], "sh": w5["daily_sharpe"], "mdd": w5["daily_mdd_pct"],
            "nav50b": w5["nav_50bps"], "is_n": wis["ss_n"], "is_nav": wis["nav"], "is_sh": wis["daily_sharpe"],
            "oos_n": woos["ss_n"], "oos_nav": woos["nav"], "oos_sh": woos["daily_sharpe"],
            "y26": w26["nav"], "h2": wh2["nav"], "gate": gate,
        })
    print(pd.DataFrame(r45).to_string(index=False))

    print("\n=== 3to4 B1 Variants (..2026-11-16, 30bps primary & 50bps stress) ===")
    r34 = []
    for vn, vd in out["dirB_3to4"]["variants"].items():
        w5 = vd["d15"]["FULL_5Y"]
        wis = vd["d15"]["IS_2123"]
        woos = vd["d15"]["OOS_2426"]
        w26 = vd["d15"]["Y2026"]
        wh2 = vd["d15"]["Y2026_H2"]
        gate = vd.get("promotion_check", {}).get("passes_strict_gate", "-")
        r34.append({
            "vid": vn, "n": w5["ss_n"], "wr": w5["wr_pct"], "nav5y": w5["nav"], "ex2": w5["ex2_nav"],
            "sh": w5["daily_sharpe"], "mdd": w5["daily_mdd_pct"], "nav50b": w5["nav_50bps"],
            "is_nav": wis["nav"], "is_sh": wis["daily_sharpe"], "oos_nav": woos["nav"], "oos_sh": woos["daily_sharpe"],
            "y26": w26["nav"], "h2": wh2["nav"], "hf": vd["hefu_in_slot"], "aa": vd["aiai_in_slot"], "gate": gate,
        })
    print(pd.DataFrame(r34).to_string(index=False))

    if out["dirB_b3_overlap_portfolio"]:
        print("\n=== B3 Sequential 4to5 -> High Stats ===")
        print(json.dumps(out["dirB_b3_overlap_portfolio"]["seq_4to5_high_stats"], ensure_ascii=False, indent=2))
        pg = pd.DataFrame(out["dirB_b3_overlap_portfolio"]["portfolio_grid"]).sort_values(["base", "sh_wf"], ascending=[True, False])
        print("\n=== B3 Top 15 V20/V21 Portfolio Combinations ===")
        print(pg.head(20)[["combo", "n_5y", "n_45", "n_hi", "hi_delta", "nav_5y", "sh_5y", "nav_wf", "sh_wf", "mdd_wf", "nav_26h2", "mult_wf", "mult_wf_ex_both", "paired_p_wf"]].to_string(index=False))


if __name__ == "__main__":
    main()
