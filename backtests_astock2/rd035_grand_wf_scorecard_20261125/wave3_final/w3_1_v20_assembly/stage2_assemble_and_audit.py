#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 3-1 Stage 2:
  1. Exact V20.0 Baseline WF reproduction (Native 0.20%/0.30%, Unified 0.30%, Stress 0.50%).
  2. Single-Slot Leave-One-In Ablation for ALL 7 Wave 2 winning candidates
     (testing BOTH Hard-Occupy vs YieldToV20 on empty-slot patches).
  3. Tiered Assembly (Tier 1 Simple Physical -> Tier 2 Best Old Core -> Tier 3 Old + 1d Low-Corr -> Tier 4 Full Max with A5).
  4. Full multi-window metrics, 1000x perm, daily NAV diff vs V20, and 50bps slippage stress survival.

Outputs in `w3_1_v20_assembly/`:
  - `w3_1_assembly_audit.json`
  - `w3_1_tier_compare.csv`
  - `w3_1_recommended_trades.parquet`

Zero yfinance (D12). Zero cap10m. Single-thread, Peak RSS < 1.2 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import pickle
import resource
import sys
import time
import warnings
from typing import Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1 = f"{RD035}/wave1_base"
RD028 = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
TB1_DIR = f"{SIM}/output/rd025_cross_factor_fusion_20261125/trackB1_10cm_fusion"
OUT_DIR = f"{RD035}/wave3_final/w3_1_v20_assembly"
CACHE_DIR = f"{OUT_DIR}/_cache"

for p in (WAVE1, RD028, PARTC_V20, TB1_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import step4_mod_rules_and_sim as m1
import tier_priority_engine as tpe
import trackB1_pools_and_sim as tb1

WF_START = "2023-01-03"
WF_END = "2026-11-16"
WINDOWS = [
    ("FULL_WF", WF_START, WF_END),
    ("Y2023", WF_START, "2023-12-31"),
    ("Y2024", "2024-01-01", "2024-12-31"),
    ("Y2025", "2025-01-01", "2025-12-31"),
    ("Y2026", "2026-01-01", WF_END),
    ("Y2025_2026", "2025-01-01", WF_END),
    ("Y2026H2", "2026-07-01", WF_END),
]


def peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


def _sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def _scale_mtm_pairs_to_fee(pairs: list, old_ret: float, new_ret: float) -> list:
    if not pairs:
        return []
    out = [list(x) for x in pairs]
    denom = 1.0 + float(old_ret)
    numer = 1.0 + float(new_ret)
    if denom > 1e-12:
        out[-1][1] = float(out[-1][1]) * (numer / denom)
    return out


def _convert_stock_ret(ret_at_base, base_fee: float, target_fee: float):
    return (1.0 + ret_at_base) / (1.0 - base_fee) * (1.0 - target_fee) - 1.0


def _sim_20cm_score(df_20: pd.DataFrame, score_vec: np.ndarray, thr: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    m = score_vec >= float(thr)
    sub = df_20[m].copy()
    if sub.empty:
        return sub, sub
    sub["_sc_adj"] = score_vec[m]
    srt = sub.sort_values(["buy_date", "_sc_adj", "code"], ascending=[True, False, True], kind="mergesort")
    t_idx, fd = [], ""
    for r in srt.itertuples():
        if (not fd) or (r.buy_date > fd):
            t_idx.append(r.Index)
            fd = str(r.exit_date)
    return sub, srt.loc[t_idx].copy()


def _sim_3to4_filtered(df_34: pd.DataFrame, blk_map: dict[tuple[str, str], bool]) -> tuple[pd.DataFrame, pd.DataFrame]:
    m_keep = np.array([not blk_map.get((str(r.buy_date)[:10], str(r.code).zfill(6)), False) for r in df_34[["buy_date", "code"]].itertuples(index=False)], dtype=bool)
    sub = df_34[m_keep & (df_34["v20_score"].to_numpy(float) >= 90.0)].copy()
    if sub.empty:
        return sub, sub
    sub["_sc_adj"] = sub["v20_score"].astype(float)
    sub["_prio"] = sub["_sc_adj"] * 10.0 + sub["prio_tie"].astype(float) * 0.1
    srt = sub.sort_values(["buy_date", "buy_hhmm", "_prio", "code"], ascending=[True, True, False, True], kind="mergesort")
    t_idx, fdt, fhh = [], "", 0
    for r in srt.itertuples():
        if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
            t_idx.append(r.Index)
            fdt, fhh = str(r.exit_date), int(r.exit_hhmm)
    return sub, srt.loc[t_idx].copy()


def _sim_pry_pruned(df_pry: pd.DataFrame, pry_map: dict[tuple[str, str], tuple[float, bool]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    sc_vec = np.empty(len(df_pry), dtype=float)
    for idx, r in enumerate(df_pry[["buy_date", "code", "v20_score"]].itertuples(index=False)):
        k = (str(r.buy_date)[:10], str(r.code).zfill(6))
        pr_sc, in_wf = pry_map.get(k, (np.nan, False))
        if in_wf and np.isfinite(pr_sc):
            sc_vec[idx] = pr_sc
        else:
            sc_vec[idx] = float(r.v20_score)
    m = sc_vec >= 165.0
    sub = df_pry[m].copy()
    if sub.empty:
        return sub, sub
    sub["_sc_adj"] = sc_vec[m]
    srt = sub.sort_values(["buy_date", "_sc_adj", "bias10", "code"], ascending=[True, False, True, True], kind="mergesort")
    t_idx, fdt = [], ""
    for r in srt.itertuples():
        if (not fdt) or (r.buy_date > fdt):
            t_idx.append(r.Index)
            fdt = str(r.exit_date)
    return sub, srt.loc[t_idx].copy()


def simulate_v20_core(
    data: dict,
    cfg_20cm: str = "base_76",
    cfg_3to4: str = "base",
    cfg_pry: str = "base",
    fee_mode: str = "unified_030",  # 'native', 'unified_030', 'stress_050'
) -> tuple[pd.DataFrame, list[dict]]:
    """
    Run V20.0 6-strategy single-slot core (`2021-11-16..2026-11-16`), then slice WF (`2023-01-03..2026-11-16`)
    and convert `net_ret` + `mtm_pairs` cleanly to `fee_mode`.
    """
    pools = data["v20_pools"]
    untrig = data["v20_untrig"]
    w2a3_sc = data["w2a3_scores"]
    w2a4_dm = data["w2a4_deltas"]
    blk_34 = data["blk_3to4_m4_bl15"]
    pry_map = data["pry_m1_tm05"]

    parts = []
    for st in m1.STRAT_ORDER:
        df = pools[st]
        if st == "3to4":
            if cfg_3to4 == "m4_bl15":
                _, slot_df = _sim_3to4_filtered(df, blk_34)
            else:
                _, slot_df = m1.sim_standalone(st, df, np.zeros(len(df)), high_cb_mode="v51_exact")
        elif st == "pry":
            if cfg_pry == "m1_tm05":
                _, slot_df = _sim_pry_pruned(df, pry_map)
            else:
                _, slot_df = m1.sim_standalone(st, df, np.zeros(len(df)), high_cb_mode="v51_exact")
        elif st == "20cm":
            # Build score vector over pool_20cm
            if cfg_20cm == "base_76":
                _, slot_df = m1.sim_standalone("20cm", df, np.zeros(len(df)), cm20_thr=76.0)
            elif cfg_20cm == "base_82":
                _, slot_df = m1.sim_standalone("20cm", df, np.zeros(len(df)), cm20_thr=82.0)
            elif cfg_20cm == "w2a3_cold50_s80":
                c50_map = {(r.buy_date, r.code): float(r.v20_cold50) for r in w2a3_sc.itertuples(index=False)}
                sc_v = np.array([c50_map.get((r.buy_date, r.code), float(r.v20_score)) for r in df.itertuples(index=False)], dtype=float)
                _, slot_df = _sim_20cm_score(df, sc_v, 80.0)
                slot_df["tier"] = "20cm_S(>=82)"
            elif cfg_20cm in ("w2a3_cleanb_s80", "w2a3_cleanb_s84"):
                thr_c = 80.0 if cfg_20cm.endswith("s80") else 84.0
                cb_map = {(r.buy_date, r.code): (float(r.clean_b_cold50_d15_score), bool(r.clean_b_wf_in)) for r in w2a3_sc.itertuples(index=False)}
                sc_v = np.empty(len(df), dtype=float)
                for idx_r, r in enumerate(df.itertuples(index=False)):
                    cb_s, cb_in = cb_map.get((r.buy_date, r.code), (np.nan, False))
                    if r.buy_date >= WF_START:
                        sc_v[idx_r] = cb_s if (cb_in and np.isfinite(cb_s)) else -999.0
                    else:
                        sc_v[idx_r] = float(r.v20_score) if float(r.v20_score) >= 82.0 else -999.0
                _, slot_df = _sim_20cm_score(df, sc_v, thr_c if True else 82.0)
                # Ensure pre-WF trades adhere to V20.0 >= 82
                if thr_c < 82.0:
                    slot_df = slot_df[(slot_df["buy_date"] >= WF_START) | (slot_df["v20_score"] >= 82.0)].copy()
                slot_df["tier"] = "20cm_S(>=82)"
            elif cfg_20cm in ("w2a4_d10_76", "w2a4_d10_82", "w2a4_d15_76", "w2a4_d15_82"):
                md_key = "mech_d10" if "d10" in cfg_20cm else "mech_d15"
                preslot = 76.0 if cfg_20cm.endswith("_76") else 82.0
                dm = w2a4_dm[md_key]
                d_vec = np.array([dm.get((r.buy_date, r.code), 0.0) for r in df.itertuples(index=False)], dtype=float)
                _, slot_df = m1.sim_standalone("20cm", df, d_vec, cm20_thr=preslot)
            elif cfg_20cm in ("w2a34_cold50_d10_80", "w2a34_cold50_d15_80"):
                md_key = "cold50_mech_d10" if "d10" in cfg_20cm else "cold50_mech_d15"
                c50_map = {(r.buy_date, r.code): float(r.v20_cold50) for r in w2a3_sc.itertuples(index=False)}
                dm = w2a4_dm[md_key]
                sc_v = np.array([
                    (c50_map.get((r.buy_date, r.code), float(r.v20_score)) + dm.get((r.buy_date, r.code), 0.0))
                    if r.buy_date >= WF_START else (float(r.v20_score) if float(r.v20_score) >= 82.0 else -999.0)
                    for r in df.itertuples(index=False)
                ], dtype=float)
                _, slot_df = _sim_20cm_score(df, sc_v, 80.0)
                slot_df = slot_df[(slot_df["buy_date"] >= WF_START) | (slot_df["v20_score"] >= 82.0)].copy()
                slot_df["tier"] = "20cm_S(>=82)"
            else:
                raise ValueError(cfg_20cm)
        else:
            _, slot_df = m1.sim_standalone(st, df, np.zeros(len(df)), high_cb_mode="v51_exact")

        chosen = slot_df[slot_df["buy_date"].between("2021-11-16", WF_END)].copy()
        if chosen.empty:
            continue
        if st == "1to2":
            sc_s = chosen["_sc_adj"] if "_sc_adj" in chosen.columns else chosen["v20_score"]
            chosen["score"] = [round(float(x), 1) for x in sc_s]
        else:
            chosen["score"] = chosen["_sc_adj"] if "_sc_adj" in chosen.columns else chosen["v20_score"]
        if "tier" not in chosen.columns or (st != "20cm" or cfg_20cm in ("base_76", "base_82", "w2a4_d10_76", "w2a4_d10_82", "w2a4_d15_76", "w2a4_d15_82")):
            chosen["tier"] = [tpe.assign_physical_tier(st, sc) for sc in chosen["score"]]
        chosen["is_untrig"] = False
        cols = [
            "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
            "strategy", "tier", "score", "net_ret", "net_ret_020", "net_ret_030",
            "buy_price_val", "is_adj_px", "is_untrig", "mtm_pairs",
        ]
        parts.append(chosen[cols])

    pool6 = pd.concat(parts, ignore_index=True)
    mtm_map = {(r.strategy, r.buy_date, r.code): r.mtm_pairs for r in pool6.itertuples(index=False)}
    ret_map = {(r.strategy, r.buy_date, r.code): (float(r.net_ret_020), float(r.net_ret_030)) for r in pool6.itertuples(index=False)}

    # Untriggered S-tier conditional orders
    ut = untrig[untrig["buy_date"].between("2021-11-16", WF_END)].copy()
    if cfg_3to4 == "m4_bl15" and not ut.empty:
        m_ut = np.array([not (r.strategy == "3to4" and blk_34.get((r.buy_date, r.code), False)) for r in ut.itertuples(index=False)], dtype=bool)
        ut = ut[m_ut].copy()
    # Keep only strategies that didn't trigger on that date (same logic as m1.run_combined_v20)
    trig_by_st = {st: set(pool6.loc[pool6["strategy"] == st, "buy_date"]) for st in m1.STRAT_ORDER}
    ut = ut[~ut.apply(lambda r: r["buy_date"] in trig_by_st.get(r["strategy"], set()), axis=1)].copy()
    ut_cols = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig"]
    ut_final = ut[ut_cols].copy() if not ut.empty else pd.DataFrame()

    tr_df, waits = tpe.run_single_slot(
        pool6.drop(columns=["mtm_pairs", "net_ret_020", "net_ret_030"]),
        lambda d: d["tier"].map(m1.S2C_MAP).fillna(999).to_numpy(),
        untrig_df=ut_final,
        timing_mode="s_tier_reserve_only",
    )
    tr_wf = tr_df[tr_df["buy_date"].between(WF_START, WF_END)].copy().reset_index(drop=True)
    waits_wf = [w for w in waits if WF_START <= w["buy_date"] <= WF_END]

    # Adjust net_ret and mtm_pairs for fee_mode
    new_rets, new_pairs = [], []
    for r in tr_wf.itertuples(index=False):
        r020, r030 = ret_map[(r.strategy, r.buy_date, r.code)]
        mp_raw = mtm_map[(r.strategy, r.buy_date, r.code)]
        if fee_mode == "native":
            nr = r020
            mp = mp_raw
        elif fee_mode == "unified_030":
            nr = r030
            mp = _scale_mtm_pairs_to_fee(mp_raw, r020, r030)
        elif fee_mode == "stress_050":
            nr = _convert_stock_ret(r030, 0.0030, 0.0050)
            mp = _scale_mtm_pairs_to_fee(mp_raw, r020, nr)
        else:
            raise ValueError(fee_mode)
        new_rets.append(nr)
        new_pairs.append(mp)

    tr_wf["net_ret"] = new_rets
    tr_wf["mtm_pairs"] = new_pairs
    tr_wf["source"] = "v20"
    return tr_wf, waits_wf


def build_empty_slot_track_candidates(
    data: dict,
    track_name: str,
    stock_fee_rt: float = 0.0030,
    etf_fee_rt: float = 0.0005,
) -> dict:
    """
    Build normalized candidate dict for an empty-slot track:
      - '512100_v3eod': ETF 512100, nt_v3_score_eod_t1 >= 60, max_hold=10, extend=False
      - '512100_v3live': ETF 512100, nt_v3_score_live_t1 >= 60, max_hold=20, extend=True
      - 'e3_top5' / 'e3_abs70' / 'e3_top10': ModE_E3_US4pct_MingmenOnly_H1
      - 'c1_top10' / 'c1_top20' / 'c1_all': ModC_C1_EarnPre_NoRun_H1
      - 'a5_abs85' / 'a5_abs80': A5_12_23_v11_PURE
    """
    if track_name.startswith("512100"):
        e512 = data["e512_daily"]
        sig_col = "nt_v3_score_eod_t1" if track_name == "512100_v3eod" else "nt_v3_score_live_t1"
        max_h = 10 if track_name == "512100_v3eod" else 20
        ext = False if track_name == "512100_v3eod" else True
        sub = e512[e512["date"].between(WF_START, WF_END)].sort_values("date").reset_index(drop=True)
        sig_map = {str(r.date): bool(pd.notna(getattr(r, sig_col)) and getattr(r, sig_col) >= 60.0) for r in sub.itertuples(index=False)}
        px_map = {str(r.date): (float(r.open), float(r.close)) for r in sub.itertuples(index=False)}
        return {
            "kind": "etf_signal",
            "name": track_name,
            "code": "512100",
            "sig_map": sig_map,
            "px_map": px_map,
            "max_hold_td": max_h,
            "extend_on_retrig": ext,
            "fee_rt": etf_fee_rt,
        }

    if track_name.startswith("e3_"):
        df = data["e3_scored"].copy()
        thr = {"e3_top5": "wf_thr_top5", "e3_top10": "wf_thr_top10", "e3_abs70": 70.0}[track_name]
    elif track_name.startswith("c1_"):
        df = data["c1_scored"].copy()
        thr = {"c1_all": None, "c1_top20": "wf_thr_top20", "c1_top10": "wf_thr_top10"}[track_name]
    elif track_name.startswith("a5_"):
        df = data["a5_scored"].copy()
        thr = {"a5_abs85": 85.0, "a5_abs80": 80.0}[track_name]
    else:
        raise ValueError(track_name)

    m = df["can_buy_hygiene"].fillna(True).to_numpy(bool) & df["wf_in_window"].fillna(False).to_numpy(bool) & df["wf_score"].notna().to_numpy(bool)
    if thr is not None:
        if isinstance(thr, str):
            tv = pd.to_numeric(df[thr], errors="coerce").to_numpy(float)
            m &= np.isfinite(tv) & (df["wf_score"].to_numpy(float) >= tv)
        else:
            m &= df["wf_score"].to_numpy(float) >= float(thr)
    p = df[m].copy()
    p = p[p["buy_date"].between(WF_START, WF_END) & (p["exit_date"] > p["buy_date"]) & (p["exit_date"] <= WF_END)].copy()
    p["net_ret"] = (1.0 + p["gross_ret"].astype(float)) * (1.0 - stock_fee_rt) - 1.0
    p_top1 = p.sort_values(["buy_date", "wf_score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    by_dt = {str(r.buy_date): r for r in p_top1.itertuples(index=False)}
    return {
        "kind": "stock_pool",
        "name": track_name,
        "by_dt": by_dt,
        "pass_df": p,
        "fee_rt": stock_fee_rt,
    }


def _build_stock_mtm_pairs(
    code: str,
    buy_dt: str,
    exit_dt: str,
    bpx: float,
    epx: float,
    net_ret: float,
    cal_dts: list[str],
    dt_idx: dict[str, int],
    bar_map: dict,
    fee_rt: float,
    orig_mtm_json: Optional[str] = None,
    use_orig_exit: bool = False,
) -> list:
    if use_orig_exit and orig_mtm_json:
        pairs = json.loads(orig_mtm_json)
        if pairs:
            # Adjust last multiplier from 0.30% native in w2b4 to target fee_rt
            if abs(fee_rt - 0.0030) > 1e-9:
                r030 = (1.0 + net_ret) / (1.0 - fee_rt) * 0.9970 - 1.0
                return _scale_mtm_pairs_to_fee(pairs, r030, net_ret)
            return pairs
    bi = dt_idx.get(buy_dt)
    ei = dt_idx.get(exit_dt)
    if bi is None or ei is None or ei <= bi or bpx <= 0:
        return [[buy_dt, 1.0 + net_ret]] if bi is not None else []
    fee_b = fee_rt * 0.5
    segs = []
    prev_v = bpx
    ok = True
    for k in range(bi, ei):
        bk = bar_map.get((code, cal_dts[k]))
        if bk is None or bk[1] <= 0:
            ok = False
            break
        ck = float(bk[1])
        mult = (ck / prev_v) * ((1.0 - fee_b) if k == bi else 1.0)
        segs.append([cal_dts[k], mult])
        prev_v = ck
    if ok and segs:
        target_end = bpx * (1.0 + net_ret)
        # Ensure exact product == 1 + net_ret
        prod_prev = 1.0
        for _, mv in segs:
            prod_prev *= mv
        segs.append([cal_dts[ei], (1.0 + net_ret) / prod_prev])
        return segs
    span = ei - bi + 1
    g = (1.0 + net_ret) ** (1.0 / span)
    return [[cal_dts[k], g] for k in range(bi, ei + 1)]


def simulate_combined_with_empty_slots(
    core_tr: pd.DataFrame,
    core_waits: list[dict],
    empty_tracks: list[dict],
    cal_dts: list[str],
    bar_map: dict,
    patch_mode: str = "yield_to_v20",  # 'yield_to_v20' or 'hard_occupy'
) -> dict:
    """
    Strictly causal chronological simulation combining V20 Core + ordered Empty-Slot tracks.
    In `yield_to_v20`: any open empty-slot position yields at d 09:25 open (09:24) whenever V20 Core
    fires a signal or S-tier wait on day d >= buy_date+1 (provided sellable at open).
    In `hard_occupy`: empty-slot position holds to natural exit, skipping conflicting V20 signals.
    """
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    T = len(cal_dts)

    # Identify core V20 occupied dates and S-tier wait dates
    v20_occ = np.zeros(T, dtype=bool)
    for r in core_tr.itertuples(index=False):
        bi, ei = dt_idx.get(r.buy_date), dt_idx.get(r.exit_date)
        if bi is not None and ei is not None:
            v20_occ[bi : ei + 1] = True
    st_wait_dts = {w["buy_date"] for w in core_waits if w["wait_tier"] in ("3to4_S(>=102)", "high_S(>=96)")}
    core_empty_set = {cal_dts[i] for i in range(T) if (not v20_occ[i]) and (cal_dts[i] not in st_wait_dts)}
    v20_by_buy = {d: g for d, g in core_tr.groupby("buy_date")}

    if not empty_tracks:
        return {
            "comb_df": core_tr.copy(),
            "patch_df": pd.DataFrame(),
            "n_v20_kept": int(len(core_tr)),
            "n_patch_added": 0,
            "n_v20_skipped": 0,
            "n_v20_locked_skip": 0,
            "skipped_v20_prod": 1.0,
            "n_patch_yielded": 0,
        }

    in_patch = False
    p_trk = None
    p_row = None
    p_code = ""
    p_buy_i = -1
    p_bpx = 0.0
    p_rem = 0
    p_fee = 0.0
    p_orig_exit_dt = ""
    p_orig_exit_hh = 1500
    p_orig_gross = 0.0
    p_orig_net = 0.0
    p_orig_mtm_json = None
    p_orig_reason = ""

    in_v20_until = -1
    in_v20_eh = 0

    comb_rows = []
    patch_rows = []
    skipped_v20 = []
    n_locked_skip = 0
    n_yielded = 0

    for i, d in enumerate(cal_dts):
        v20_today = v20_by_buy.get(d)
        is_st_wait = d in st_wait_dts
        v20_free_morning = in_v20_until < i

        # 1. Morning yield check if holding an empty-slot trade from an earlier day (i > p_buy_i)
        want_yield = False
        if patch_mode == "yield_to_v20":
            want_yield = (v20_today is not None) or is_st_wait
        elif patch_mode == "yield_925_only":
            want_yield = (v20_today is not None) and bool((v20_today["buy_hhmm"] == 925).any())
        if in_patch and want_yield and v20_free_morning:
            if p_trk["kind"] == "etf_signal":
                px = p_trk["px_map"].get(d)
                can_sell = (px is not None) and np.isfinite(px[0]) and (px[0] > 0)
                epx = float(px[0]) if can_sell else 0.0
            else:
                bm = bar_map.get((p_code, d))
                can_sell = (bm is not None) and (bm[0] > 0) and (bm[2] == 0) and (bm[5] > 0)
                epx = float(bm[0]) if can_sell else 0.0

            if can_sell:
                gr = epx / p_bpx - 1.0
                nr = (1.0 + gr) * (1.0 - p_fee) - 1.0
                if p_trk["kind"] == "etf_signal":
                    segs = []
                    prev_v = p_bpx
                    ok = True
                    for k in range(p_buy_i, i):
                        pk = p_trk["px_map"].get(cal_dts[k])
                        if pk is None or pk[1] <= 0:
                            ok = False
                            break
                        ck = float(pk[1])
                        segs.append([cal_dts[k], (ck / prev_v) * ((1.0 - 0.5 * p_fee) if k == p_buy_i else 1.0)])
                        prev_v = ck
                    if ok and segs:
                        prod_p = 1.0
                        for _, mv in segs:
                            prod_p *= mv
                        segs.append([d, (1.0 + nr) / prod_p])
                    else:
                        span = i - p_buy_i + 1
                        g = (1.0 + nr) ** (1.0 / span)
                        segs = [[cal_dts[k], g] for k in range(p_buy_i, i + 1)]
                else:
                    segs = _build_stock_mtm_pairs(p_code, cal_dts[p_buy_i], d, p_bpx, epx, nr, cal_dts, dt_idx, bar_map, p_fee)

                tr = {
                    "buy_date": cal_dts[p_buy_i], "buy_hhmm": 925, "exit_date": d, "exit_hhmm": 924,
                    "code": p_code, "name": "", "strategy": f"patch_{p_trk['name']}", "tier": "patch",
                    "score": float(getattr(p_row, "wf_score", 100.0)) if p_row is not None else 100.0,
                    "net_ret": nr, "source": "patch", "mtm_pairs": segs, "exit_reason": "yield_to_v20_open",
                }
                patch_rows.append(tr)
                comb_rows.append(tr)
                in_patch = False
                n_yielded += 1
            else:
                n_locked_skip += 1

        # 2. V20 Core entry/wait check
        if v20_today is not None:
            for r in v20_today.itertuples(index=False):
                can_v20 = (not in_patch) and ((in_v20_until < i) or (in_v20_until == i and int(r.buy_hhmm) > in_v20_eh))
                if can_v20:
                    comb_rows.append({
                        "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm),
                        "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
                        "code": r.code, "name": r.name, "strategy": r.strategy, "tier": r.tier,
                        "score": float(r.score), "net_ret": float(r.net_ret),
                        "source": "v20", "mtm_pairs": r.mtm_pairs, "exit_reason": "v20",
                    })
                    in_v20_until = dt_idx.get(r.exit_date, i)
                    in_v20_eh = int(r.exit_hhmm)
                    break
                elif in_patch:
                    skipped_v20.append({"buy_date": r.buy_date, "code": r.code, "strategy": r.strategy, "net_ret": float(r.net_ret)})
                    break

        if in_v20_until < i and is_st_wait and not in_patch:
            in_v20_until = max(in_v20_until, i)
            in_v20_eh = 1500

        # 3. Natural exit of held empty-slot trade if still in_patch
        if in_patch:
            if p_trk["kind"] == "etf_signal":
                if p_trk["extend_on_retrig"] and p_trk["sig_map"].get(d, False):
                    p_rem = p_trk["max_hold_td"] - 1
                else:
                    p_rem -= 1
                if p_rem <= 0 or i == T - 1:
                    px = p_trk["px_map"].get(d)
                    if px is not None and np.isfinite(px[1]) and px[1] > 0:
                        epx = float(px[1])
                        gr = epx / p_bpx - 1.0
                        nr = (1.0 + gr) * (1.0 - p_fee) - 1.0
                        segs = []
                        prev_v = p_bpx
                        ok = True
                        for k in range(p_buy_i, i):
                            pk = p_trk["px_map"].get(cal_dts[k])
                            if pk is None or pk[1] <= 0:
                                ok = False
                                break
                            ck = float(pk[1])
                            segs.append([cal_dts[k], (ck / prev_v) * ((1.0 - 0.5 * p_fee) if k == p_buy_i else 1.0)])
                            prev_v = ck
                        if ok and segs:
                            prod_p = 1.0
                            for _, mv in segs:
                                prod_p *= mv
                            segs.append([d, (1.0 + nr) / prod_p])
                        else:
                            span = i - p_buy_i + 1
                            g = (1.0 + nr) ** (1.0 / span)
                            segs = [[cal_dts[k], g] for k in range(p_buy_i, i + 1)]
                        tr = {
                            "buy_date": cal_dts[p_buy_i], "buy_hhmm": 925, "exit_date": d, "exit_hhmm": 1500,
                            "code": p_code, "name": "", "strategy": f"patch_{p_trk['name']}", "tier": "patch",
                            "score": 100.0, "net_ret": nr, "source": "patch", "mtm_pairs": segs, "exit_reason": "etf_hold_expire",
                        }
                        patch_rows.append(tr)
                        comb_rows.append(tr)
                        in_patch = False
                        continue
            else:
                if d >= p_orig_exit_dt or i == T - 1:
                    if d == p_orig_exit_dt and i < T - 1:
                        nr = p_orig_net
                        ehh = p_orig_exit_hh
                        bm = bar_map.get((p_code, d))
                        epx = float(bm[1]) if bm else p_bpx * (1.0 + p_orig_gross)
                        segs = _build_stock_mtm_pairs(
                            p_code, cal_dts[p_buy_i], d, p_bpx, epx, nr, cal_dts, dt_idx, bar_map, p_fee,
                            orig_mtm_json=p_orig_mtm_json, use_orig_exit=True,
                        )
                    else:
                        bm = bar_map.get((p_code, d))
                        epx = float(bm[1]) if (bm and bm[1] > 0) else p_bpx
                        gr = epx / p_bpx - 1.0
                        nr = (1.0 + gr) * (1.0 - p_fee) - 1.0
                        ehh = 1500
                        segs = _build_stock_mtm_pairs(p_code, cal_dts[p_buy_i], d, p_bpx, epx, nr, cal_dts, dt_idx, bar_map, p_fee)
                    tr = {
                        "buy_date": cal_dts[p_buy_i], "buy_hhmm": 925, "exit_date": d, "exit_hhmm": ehh,
                        "code": p_code, "name": "", "strategy": f"patch_{p_trk['name']}", "tier": "patch",
                        "score": float(getattr(p_row, "wf_score", 100.0)), "net_ret": nr,
                        "source": "patch", "mtm_pairs": segs, "exit_reason": p_orig_reason or "natural_exit",
                    }
                    patch_rows.append(tr)
                    comb_rows.append(tr)
                    in_patch = False
                    continue

        # 4. Empty-slot entry check (only when V20 Core is empty today AND not holding any trade)
        if (not in_patch) and (d in core_empty_set) and (i < T - 1):
            for trk in empty_tracks:
                if trk["kind"] == "etf_signal":
                    if trk["sig_map"].get(d, False):
                        px = trk["px_map"].get(d)
                        if px is not None and np.isfinite(px[0]) and px[0] > 0:
                            in_patch = True
                            p_trk, p_row, p_code, p_buy_i = trk, None, trk["code"], i
                            p_bpx, p_rem, p_fee = float(px[0]), trk["max_hold_td"] - 1, trk["fee_rt"]
                            break
                else:
                    row_c = trk["by_dt"].get(d)
                    if row_c is not None:
                        c_code = str(row_c.code).zfill(6)
                        bm = bar_map.get((c_code, d))
                        if bm is not None and bm[0] > 0:
                            in_patch = True
                            p_trk, p_row, p_code, p_buy_i = trk, row_c, c_code, i
                            p_bpx = float(bm[0])
                            p_fee = trk["fee_rt"]
                            p_orig_exit_dt = str(row_c.exit_date)
                            p_orig_exit_hh = int(getattr(row_c, "exit_hhmm", 1500))
                            p_orig_gross = float(row_c.gross_ret)
                            p_orig_net = float(row_c.net_ret)
                            p_orig_mtm_json = getattr(row_c, "mtm_json", None)
                            p_orig_reason = str(getattr(row_c, "exit_reason", "natural_exit"))
                            break

    comb_df = pd.DataFrame(comb_rows) if comb_rows else pd.DataFrame(columns=["buy_date", "exit_date", "code", "strategy", "net_ret", "source", "mtm_pairs"])
    patch_df = pd.DataFrame(patch_rows) if patch_rows else pd.DataFrame()
    return {
        "comb_df": comb_df,
        "patch_df": patch_df,
        "n_v20_kept": int((comb_df["source"] == "v20").sum()) if not comb_df.empty else 0,
        "n_patch_added": int(len(patch_df)),
        "n_v20_skipped": int(len(skipped_v20)),
        "n_v20_locked_skip": int(n_locked_skip),
        "skipped_v20_prod": float(np.prod(1.0 + np.array([x["net_ret"] for x in skipped_v20]))) if skipped_v20 else 1.0,
        "n_patch_yielded": int(n_yielded),
    }


def _daily_mtm_from_df(tr_df: pd.DataFrame, cal_dts: list[str]) -> tuple[np.ndarray, float]:
    T = len(cal_dts)
    if tr_df.empty:
        return np.zeros(T, dtype=float), 0.0
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    day_mult = np.ones(T, dtype=float)
    for r in tr_df.itertuples(index=False):
        mp = getattr(r, "mtm_pairs", None)
        if mp:
            for d_str, mult in mp:
                ti = dt_idx.get(str(d_str))
                if ti is not None:
                    day_mult[ti] *= float(mult)
        else:
            bi = dt_idx.get(str(r.buy_date))
            ei = dt_idx.get(str(r.exit_date))
            if bi is None:
                continue
            if ei is None or ei <= bi:
                day_mult[bi] *= (1.0 + float(r.net_ret))
            else:
                span = ei - bi + 1
                day_mult[bi : ei + 1] *= (1.0 + float(r.net_ret)) ** (1.0 / span)
    dr = day_mult - 1.0
    tr_nav = float(np.prod(1.0 + tr_df["net_ret"].to_numpy(float)))
    return dr, abs(float(np.prod(day_mult)) - tr_nav)


def evaluate_portfolio_full(
    name: str,
    group: str,
    sim_res: dict,
    cal_dts: list[str],
    csi_arr: np.ndarray,
    ew_arr: np.ndarray,
    cand_pool_df: pd.DataFrame,
    v20_ref_dr_030: Optional[np.ndarray] = None,
    perm_n: int = 1000,
) -> tuple[dict, np.ndarray]:
    comb_df = sim_res["comb_df"]
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    dr, mtm_diff = _daily_mtm_from_df(comb_df, cal_dts)

    win_dict = {
        wn: wfm._calc_one_window(comb_df, None, dr, cal_dts, dt_idx, csi_arr, ew_arr, s, e)
        for wn, s, e in WINDOWS
    }
    perm = wfm.perm_test_trading_days(comb_df, cand_pool_df, WF_START, WF_END, n_perm=perm_n, seed=20261125) if perm_n > 0 else {}

    diff_diag = {}
    if v20_ref_dr_030 is not None:
        dd = dr - v20_ref_dr_030
        act_diff = np.abs(dd) > 1e-12
        corr_v20 = float(np.corrcoef(dr, v20_ref_dr_030)[0, 1]) if (np.std(dr) > 1e-12 and np.std(v20_ref_dr_030) > 1e-12) else 1.0
        diff_diag = {
            "corr_vs_v20_daily": round(corr_v20, 4),
            "n_diff_days": int(act_diff.sum()),
            "daily_diff_mean_bps": round(float(dd.mean() * 10000.0), 3),
            "daily_diff_max_abs_pct": round(float(np.max(np.abs(dd)) * 100.0), 2),
            "days_beat_v20_pct": round(float((dd[act_diff] > 0).mean() * 100.0), 2) if act_diff.any() else 50.0,
        }

    return {
        "name": name,
        "group": group,
        "mtm_diff": round(mtm_diff, 8),
        "n_v20_kept": sim_res["n_v20_kept"],
        "n_patch_added": sim_res["n_patch_added"],
        "n_v20_skipped": sim_res["n_v20_skipped"],
        "n_v20_locked_skip": sim_res.get("n_v20_locked_skip", 0),
        "skipped_v20_prod": round(sim_res["skipped_v20_prod"], 4),
        "n_patch_yielded": sim_res.get("n_patch_yielded", 0),
        "windows": win_dict,
        "perm_1000": perm,
        "vs_v20_daily": diff_diag,
    }, dr


def main():
    t0 = time.time()
    print("[Stage 2] Loading cached pools...")
    v20_ctx = wf.load_v20_reference_context(WAVE1)
    cal5 = v20_ctx["calendar_5y"]
    cal_wf = cal5[cal5["trade_date"].between(WF_START, WF_END)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_wf["trade_date"].tolist()
    csi_arr = cal_wf["csi300_daily_ret"].to_numpy(float)
    ew_arr = cal_wf["alla_ew_daily_ret"].to_numpy(float)

    with open(f"{CACHE_DIR}/v20_core_pools.pkl", "rb") as f:
        c_v20 = pickle.load(f)
    with open(f"{CACHE_DIR}/w2a3_w2a4_20cm_scores.pkl", "rb") as f:
        c_20 = pickle.load(f)
    with open(f"{CACHE_DIR}/w2a2_3to4_pry.pkl", "rb") as f:
        c_34p = pickle.load(f)
    with open(f"{CACHE_DIR}/empty_slot_bar_map.pkl", "rb") as f:
        bar_map = pickle.load(f)

    data = {
        "v20_pools": c_v20["pools"],
        "v20_untrig": c_v20["untrig"],
        "w2a3_scores": c_20["w2a3_scores"],
        "w2a4_deltas": c_20["w2a4_deltas"],
        "blk_3to4_m4_bl15": c_34p["blk_3to4_m4_bl15"],
        "pry_m1_tm05": c_34p["pry_m1_tm05"],
        "e512_daily": pd.read_parquet(f"{CACHE_DIR}/w2b5_512100_daily.parquet"),
        "c1_scored": pd.read_parquet(f"{CACHE_DIR}/w2b6_c1_scored.parquet"),
        "e3_scored": pd.read_parquet(f"{CACHE_DIR}/w2b6_e3_scored.parquet"),
        "a5_scored": pd.read_parquet(f"{CACHE_DIR}/w2b4_a5_scored.parquet"),
    }

    # Build unified 0.30% candidate pool for permutation tests
    master_p = pd.read_parquet(f"{WAVE1}/pools_6strat_master_newfactors_pit.parquet", columns=["strategy", "buy_date", "code", "net_ret", "sim_ok"])
    master_p["buy_date"] = master_p["buy_date"].astype(str).str[:10]
    master_p["code"] = master_p["code"].astype(str).str.zfill(6)
    master_p = master_p[master_p["buy_date"].between(WF_START, WF_END) & (master_p["sim_ok"] == 1) & master_p["net_ret"].notna()].copy()
    master_p["net_ret"] = np.where(master_p["strategy"] == "20cm", master_p["net_ret"], _convert_stock_ret(master_p["net_ret"], 0.0020, 0.0030))
    master_p["can_buy_hygiene"] = True
    base_cand_pool = master_p[["buy_date", "code", "net_ret", "can_buy_hygiene"]].copy()

    # =========================================================================
    # 1. Exact V20.0 Baseline Reproduction (Native vs Unified 0.30% vs Stress 0.50%)
    # =========================================================================
    tr_nat, w_nat = simulate_v20_core(data, "base_76", "base", "base", fee_mode="native")
    ev_nat, dr_nat = evaluate_portfolio_full(
        "V20_Base_Native_020_030", "0_BASELINE",
        {"comb_df": tr_nat, "n_v20_kept": len(tr_nat), "n_patch_added": 0, "n_v20_skipped": 0, "skipped_v20_prod": 1.0},
        cal_dts, csi_arr, ew_arr, base_cand_pool, perm_n=1000,
    )
    fw_nat = ev_nat["windows"]["FULL_WF"]
    assert fw_nat["n"] == 207 and abs(fw_nat["nav"] - 611729.5546) < 0.05 and fw_nat["daily_mdd_pct"] == 47.32
    assert abs(fw_nat["daily_sharpe"] - 4.672) < 0.002
    print(f"[1. V20 Native Parity PASS] n={fw_nat['n']} WF={fw_nat['nav']:.2f}x 25-26={ev_nat['windows']['Y2025_2026']['nav']:.2f}x Y26={ev_nat['windows']['Y2026']['nav']:.2f}x MDD={fw_nat['daily_mdd_pct']}% Sh={fw_nat['daily_sharpe']}")

    tr_030, w_030 = simulate_v20_core(data, "base_76", "base", "base", fee_mode="unified_030")
    ev_030, dr_030 = evaluate_portfolio_full(
        "V20_Base_Unified_030", "0_BASELINE",
        {"comb_df": tr_030, "n_v20_kept": len(tr_030), "n_patch_added": 0, "n_v20_skipped": 0, "skipped_v20_prod": 1.0},
        cal_dts, csi_arr, ew_arr, base_cand_pool, perm_n=1000,
    )
    tr_050, _ = simulate_v20_core(data, "base_76", "base", "base", fee_mode="stress_050")
    ev_050, _ = evaluate_portfolio_full(
        "V20_Base_Stress_050", "0_BASELINE",
        {"comb_df": tr_050, "n_v20_kept": len(tr_050), "n_patch_added": 0, "n_v20_skipped": 0, "skipped_v20_prod": 1.0},
        cal_dts, csi_arr, ew_arr, base_cand_pool, perm_n=0,
    )
    print(f"    V20 Unified 0.30%: WF={ev_030['windows']['FULL_WF']['nav']:.2f}x | Stress 0.50%: WF={ev_050['windows']['FULL_WF']['nav']:.2f}x")

    all_records = []

    def run_and_record(name: str, group: str, c20: str, c34: str, cpry: str, empty_specs: list[tuple[str, float]], patch_mode: str = "yield_to_v20", save_df_out: bool = False):
        # Unified 0.30% stock / 0.05% ETF
        c_tr, c_w = simulate_v20_core(data, c20, c34, cpry, fee_mode="unified_030")
        tracks_030 = [build_empty_slot_track_candidates(data, tname, stock_fee_rt=0.0030, etf_fee_rt=0.0005) for tname, _ in empty_specs]
        sim_030 = simulate_combined_with_empty_slots(c_tr, c_w, tracks_030, cal_dts, bar_map, patch_mode=patch_mode)
        # Augment perm cand pool with active empty-slot pass dfs
        pool_perm = [base_cand_pool]
        for trk in tracks_030:
            if trk["kind"] == "stock_pool" and not trk["pass_df"].empty:
                pool_perm.append(trk["pass_df"][["buy_date", "code", "net_ret"]].assign(can_buy_hygiene=True))
        cp_df = pd.concat(pool_perm, ignore_index=True)

        ev30, dr30 = evaluate_portfolio_full(name, group, sim_030, cal_dts, csi_arr, ew_arr, cp_df, v20_ref_dr_030=dr_030, perm_n=1000)

        # Stress 0.50% stock / 0.05% ETF AND 0.50% stock / 0.25% ETF
        c_tr50, c_w50 = simulate_v20_core(data, c20, c34, cpry, fee_mode="stress_050")
        tracks_050 = [build_empty_slot_track_candidates(data, tname, stock_fee_rt=0.0050, etf_fee_rt=0.0005) for tname, _ in empty_specs]
        sim_050 = simulate_combined_with_empty_slots(c_tr50, c_w50, tracks_050, cal_dts, bar_map, patch_mode=patch_mode)
        ev50, _ = evaluate_portfolio_full(f"{name}_050", group, sim_050, cal_dts, csi_arr, ew_arr, cp_df, perm_n=0)

        tracks_050_etf25 = [build_empty_slot_track_candidates(data, tname, stock_fee_rt=0.0050, etf_fee_rt=0.0025) for tname, _ in empty_specs]
        sim_050_etf25 = simulate_combined_with_empty_slots(c_tr50, c_w50, tracks_050_etf25, cal_dts, bar_map, patch_mode=patch_mode)
        ev50_etf25, _ = evaluate_portfolio_full(f"{name}_050e25", group, sim_050_etf25, cal_dts, csi_arr, ew_arr, cp_df, perm_n=0)

        rec = {
            **ev30,
            "config": {"20cm": c20, "3to4": c34, "pry": cpry, "empty": [x[0] for x in empty_specs], "patch_mode": patch_mode},
            "stress_050": {
                "stock_050_etf_005": ev50["windows"],
                "stock_050_etf_025": ev50_etf25["windows"],
                "survival_ratio_050_vs_030": round(ev50["windows"]["FULL_WF"]["nav"] / max(1e-9, ev30["windows"]["FULL_WF"]["nav"]), 4),
            },
        }
        all_records.append(rec)
        fw3 = ev30["windows"]["FULL_WF"]
        y25 = ev30["windows"]["Y2025_2026"]
        y26 = ev30["windows"]["Y2026"]
        h2 = ev30["windows"]["Y2026H2"]
        fw5 = ev50["windows"]["FULL_WF"]
        print(
            f"  [{group:12s}] {name:38s} | n={fw3['n']:3d}(+{sim_030['n_patch_added']:2d},sk={sim_030['n_v20_skipped']:2d},yld={sim_030.get('n_patch_yielded',0):2d}) "
            f"WF={fw3['nav']:10.2f}x 2526={y25['nav']:7.2f}x 26={y26['nav']:5.2f}x H2={h2['nav']:4.2f}x "
            f"MDD={fw3['daily_mdd_pct']:5.2f}% Sh={fw3['daily_sharpe']:5.3f} Cal={fw3['daily_calmar']:6.2f} | 50bps={fw5['nav']:10.2f}x"
        )
        return sim_030["comb_df"] if save_df_out else None

    # Record V20 Baseline 0.30% + 0.50% as row 0
    all_records.append({
        **ev_030,
        "config": {"20cm": "base_76", "3to4": "base", "pry": "base", "empty": [], "patch_mode": "none"},
        "vs_v20_daily": {"corr_vs_v20_daily": 1.0, "n_diff_days": 0, "daily_diff_mean_bps": 0.0, "daily_diff_max_abs_pct": 0.0, "days_beat_v20_pct": 50.0},
        "stress_050": {
            "stock_050_etf_005": ev_050["windows"],
            "stock_050_etf_025": ev_050["windows"],
            "survival_ratio_050_vs_030": round(ev_050["windows"]["FULL_WF"]["nav"] / max(1e-9, ev_030["windows"]["FULL_WF"]["nav"]), 4),
        },
    })

    # =========================================================================
    # 2. Leave-One-In Ablation (7 Winning Candidates Individually)
    # =========================================================================
    print("\n=== [2] LEAVE-ONE-IN ABLATION (Unified 0.30% & 0.50% Stress) ===")
    # Base S82 clean reference (without 76..81 shadow)
    run_and_record("LOI_0_Base_S82_Clean", "LOI_REF", "base_82", "base", "base", [])
    # Candidate 1 (W2A3 Trio)
    run_and_record("LOI_1a_20cm_W2A3_Cold50_S80", "LOI_1_W2A3", "w2a3_cold50_s80", "base", "base", [])
    run_and_record("LOI_1b_20cm_W2A3_CleanB_S84", "LOI_1_W2A3", "w2a3_cleanb_s84", "base", "base", [])
    run_and_record("LOI_1c_20cm_W2A3_CleanB_S80", "LOI_1_W2A3", "w2a3_cleanb_s80", "base", "base", [])
    # Candidate 2 (W2A4 130 Mech Interactions)
    run_and_record("LOI_2a_20cm_W2A4_d10_preslot76", "LOI_2_W2A4", "w2a4_d10_76", "base", "base", [])
    run_and_record("LOI_2b_20cm_W2A4_d10_S82", "LOI_2_W2A4", "w2a4_d10_82", "base", "base", [])
    run_and_record("LOI_2c_20cm_W2A4_d15_preslot76", "LOI_2_W2A4", "w2a4_d15_76", "base", "base", [])
    run_and_record("LOI_2d_20cm_W2A4_d15_S82", "LOI_2_W2A4", "w2a4_d15_82", "base", "base", [])
    run_and_record("LOI_2e_20cm_Cold50_Plus_W2A4_d10_S80", "LOI_2_DIAG", "w2a34_cold50_d10_80", "base", "base", [])
    run_and_record("LOI_2f_20cm_Cold50_Plus_W2A4_d15_S80", "LOI_2_DIAG", "w2a34_cold50_d15_80", "base", "base", [])
    # Candidate 3 (W2A2 3to4 + pry)
    run_and_record("LOI_3a_3to4_M4_MineBL15", "LOI_3_W2A2", "base_76", "m4_bl15", "base", [])
    run_and_record("LOI_3b_pry_M1_DropNeg_tm05", "LOI_3_W2A2", "base_76", "base", "m1_tm05", [])
    run_and_record("LOI_3ab_3to4_M4_Plus_pry_tm05", "LOI_3_W2A2", "base_76", "m4_bl15", "m1_tm05", [])
    # Candidate 4 (W2B5 512100 ETF: Hard Occupy vs YieldToV20 vs Strict925)
    run_and_record("LOI_4a_512100_V3EOD_HardOccupy", "LOI_4_W2B5", "base_76", "base", "base", [("512100_v3eod", 0.0005)], "hard_occupy")
    run_and_record("LOI_4b_512100_V3EOD_YieldToV20", "LOI_4_W2B5", "base_76", "base", "base", [("512100_v3eod", 0.0005)], "yield_to_v20")
    run_and_record("LOI_4b_512100_V3EOD_Strict925", "LOI_4_W2B5", "base_76", "base", "base", [("512100_v3eod", 0.0005)], "yield_925_only")
    run_and_record("LOI_4c_512100_V3Live_YieldToV20", "LOI_4_W2B5", "base_76", "base", "base", [("512100_v3live", 0.0005)], "yield_to_v20")
    # Candidate 5a (W2B6 ModE_E3: Hard Occupy vs YieldToV20 vs Strict925)
    run_and_record("LOI_5a_ModE_E3_top5_HardOccupy", "LOI_5_W2B6", "base_76", "base", "base", [("e3_top5", 0.0030)], "hard_occupy")
    run_and_record("LOI_5b_ModE_E3_top5_YieldToV20", "LOI_5_W2B6", "base_76", "base", "base", [("e3_top5", 0.0030)], "yield_to_v20")
    run_and_record("LOI_5b_ModE_E3_top5_Strict925", "LOI_5_W2B6", "base_76", "base", "base", [("e3_top5", 0.0030)], "yield_925_only")
    run_and_record("LOI_5c_ModE_E3_abs70_HardOccupy", "LOI_5_W2B6", "base_76", "base", "base", [("e3_abs70", 0.0030)], "hard_occupy")
    run_and_record("LOI_5d_ModE_E3_abs70_YieldToV20", "LOI_5_W2B6", "base_76", "base", "base", [("e3_abs70", 0.0030)], "yield_to_v20")
    # Candidate 5b (W2B6 C1_EarnPre: Hard Occupy vs YieldToV20 vs Strict925)
    run_and_record("LOI_5e_C1_EarnPre_top10_HardOccupy", "LOI_5_W2B6", "base_76", "base", "base", [("c1_top10", 0.0030)], "hard_occupy")
    run_and_record("LOI_5f_C1_EarnPre_top10_YieldToV20", "LOI_5_W2B6", "base_76", "base", "base", [("c1_top10", 0.0030)], "yield_to_v20")
    run_and_record("LOI_5f_C1_EarnPre_top10_Strict925", "LOI_5_W2B6", "base_76", "base", "base", [("c1_top10", 0.0030)], "yield_925_only")
    run_and_record("LOI_5g_C1_EarnPre_all_HardOccupy", "LOI_5_W2B6", "base_76", "base", "base", [("c1_all", 0.0030)], "hard_occupy")
    run_and_record("LOI_5h_C1_EarnPre_all_YieldToV20", "LOI_5_W2B6", "base_76", "base", "base", [("c1_all", 0.0030)], "yield_to_v20")
    # Candidate 6 (W2B4 A5 20cm 1->2: Hard Occupy vs YieldToV20 vs Strict925)
    run_and_record("LOI_6a_A5_abs85_HardOccupy", "LOI_6_W2B4", "base_76", "base", "base", [("a5_abs85", 0.0030)], "hard_occupy")
    run_and_record("LOI_6b_A5_abs85_YieldToV20", "LOI_6_W2B4", "base_76", "base", "base", [("a5_abs85", 0.0030)], "yield_to_v20")
    run_and_record("LOI_6b_A5_abs85_Strict925", "LOI_6_W2B4", "base_76", "base", "base", [("a5_abs85", 0.0030)], "yield_925_only")
    run_and_record("LOI_6c_A5_abs80_HardOccupy", "LOI_6_W2B4", "base_76", "base", "base", [("a5_abs80", 0.0030)], "hard_occupy")
    run_and_record("LOI_6d_A5_abs80_YieldToV20", "LOI_6_W2B4", "base_76", "base", "base", [("a5_abs80", 0.0030)], "yield_to_v20")

    # =========================================================================
    # 3. Tiered Portfolio Assembly (Tier 1 -> Tier 2 -> Tier 3 -> Tier 4)
    # =========================================================================
    print("\n=== [3] TIERED PORTFOLIO ASSEMBLY ===")
    # Tier 1: Pure physical zero black-box (Cold50 S80 + pry drop lock50 + 512100 ETF YieldToV20 / Strict925)
    run_and_record("Tier1_SimplePhysical", "TIER_1", "w2a3_cold50_s80", "base", "m1_tm05", [("512100_v3eod", 0.0005)], "yield_to_v20")
    run_and_record("Tier1_SimplePhysical_Strict925", "TIER_1", "w2a3_cold50_s80", "base", "m1_tm05", [("512100_v3eod", 0.0005)], "yield_925_only")

    # Tier 2: Best Old Core (test across all top 20cm candidates + 3to4 M4_BL15 + pry M1_tm05)
    t2_cands = [
        ("Tier2_OldCore_W2A3_Cold50_S80", "w2a3_cold50_s80"),
        ("Tier2_OldCore_W2A3_CleanB_S80", "w2a3_cleanb_s80"),
        ("Tier2_OldCore_W2A3_CleanB_S84", "w2a3_cleanb_s84"),
        ("Tier2_OldCore_W2A4_d10_76", "w2a4_d10_76"),
        ("Tier2_OldCore_W2A4_d15_82", "w2a4_d15_82"),
        ("Tier2_OldCore_Cold50_W2A4_d10_S80", "w2a34_cold50_d10_80"),
    ]
    for t2_name, c20_id in t2_cands:
        run_and_record(t2_name, "TIER_2", c20_id, "m4_bl15", "m1_tm05", [])

    # Pick Tier 2 winner dynamically by composite WF NAV & Sharpe & 25-26 & Ex5
    t2_recs = [r for r in all_records if r["group"] == "TIER_2"]
    best_t2 = max(t2_recs, key=lambda r: (r["windows"]["FULL_WF"]["daily_sharpe"], r["windows"]["FULL_WF"]["nav"]))
    best_t2_c20 = best_t2["config"]["20cm"]
    print(f"  >> Selected Tier 2 best 20cm engine: {best_t2['name']} ({best_t2_c20})")

    # Also test Tier 3 on BOTH best Tier 2 AND W2A3_CleanB_S80 / W2A34_Cold50_d10_80
    t3_bases = [best_t2_c20]
    for cand_20 in ("w2a34_cold50_d10_80", "w2a3_cleanb_s80", "w2a3_cold50_s80"):
        if cand_20 not in t3_bases:
            t3_bases.append(cand_20)

    # Tier 3: Old Core + 1-day low-corr empty-slot patches (512100 + ModE_E3 + C1_EarnPre)
    for b20 in t3_bases[:3]:
        tag = b20.replace("w2a3_", "").replace("w2a4_", "").replace("w2a34_", "c50w4_")
        run_and_record(f"Tier3_{tag}_Yield_E3top5_C1top10", "TIER_3", b20, "m4_bl15", "m1_tm05", [("512100_v3eod", 0.0005), ("e3_top5", 0.0030), ("c1_top10", 0.0030)], "yield_to_v20")
        run_and_record(f"Tier3_{tag}_Strict925_E3top5_C1top10", "TIER_3", b20, "m4_bl15", "m1_tm05", [("512100_v3eod", 0.0005), ("e3_top5", 0.0030), ("c1_top10", 0.0030)], "yield_925_only")
        run_and_record(f"Tier3_{tag}_Yield_E3abs70_C1top10", "TIER_3", b20, "m4_bl15", "m1_tm05", [("512100_v3eod", 0.0005), ("e3_abs70", 0.0030), ("c1_top10", 0.0030)], "yield_to_v20")
        run_and_record(f"Tier3_{tag}_HardOcc_E3top5_C1top10", "TIER_3", b20, "m4_bl15", "m1_tm05", [("512100_v3eod", 0.0005), ("e3_top5", 0.0030), ("c1_top10", 0.0030)], "hard_occupy")
    run_and_record(f"Tier3_{best_t2_c20}_Yield_E3top5_Only", "TIER_3", best_t2_c20, "m4_bl15", "m1_tm05", [("512100_v3eod", 0.0005), ("e3_top5", 0.0030)], "yield_to_v20")
    run_and_record(f"Tier3_{best_t2_c20}_Yield_E3top5_C1all", "TIER_3", best_t2_c20, "m4_bl15", "m1_tm05", [("512100_v3eod", 0.0005), ("e3_top5", 0.0030), ("c1_all", 0.0030)], "yield_to_v20")

    t3_recs = [r for r in all_records if r["group"] == "TIER_3"]
    best_t3 = max(t3_recs, key=lambda r: (r["windows"]["FULL_WF"]["nav"] * (1.0 + 0.2 * r["windows"]["Y2025_2026"]["daily_sharpe"])))
    best_t3_c20 = best_t3["config"]["20cm"]
    best_t3_empty = [(x, 0.0005 if x.startswith("512100") else 0.0030) for x in best_t3["config"]["empty"]]
    print(f"  >> Selected Tier 3 best: {best_t3['name']}")

    # Tier 4: Full Max (Tier 3 + A5_12_23_v11_PURE@abs_85 and @abs_80, YieldToV20, Strict925, HardOccupy)
    for a5_id in ("a5_abs85", "a5_abs80"):
        for pm in ("yield_to_v20", "yield_925_only", "hard_occupy"):
            run_and_record(
                f"Tier4_{a5_id}_{pm}", "TIER_4",
                best_t3_c20, "m4_bl15", "m1_tm05",
                best_t3_empty + [(a5_id, 0.0030)], pm,
            )

    # Identify Overall Recommended Winner across Tiers 1-4 (favoring high WF + 25-26 + 2026H2 + Sharpe + 0.50% survival, no 26H2 drag)
    tier_recs = [r for r in all_records if r["group"].startswith("TIER_")]
    best_overall = max(
        tier_recs,
        key=lambda r: (
            r["windows"]["FULL_WF"]["daily_sharpe"]
            + 0.3 * math.log10(max(1.0, r["windows"]["FULL_WF"]["nav"]))
            + 0.4 * math.log10(max(1.0, r["windows"]["Y2025_2026"]["nav"]))
            + 0.5 * (r["windows"]["Y2026H2"]["nav"] - 1.0)
            - 0.02 * r["windows"]["FULL_WF"]["daily_mdd_pct"]
        ),
    )
    print(f"\n>> RECOMMENDED OVERALL TIER: {best_overall['name']} ({best_overall['group']})")

    # Export recommended trades parquet
    rec_cfg = best_overall["config"]
    rec_empty = [(x, 0.0005 if x.startswith("512100") else 0.0030) for x in rec_cfg["empty"]]
    rec_df = run_and_record("RECOMMENDED_FINAL", "RECOMMENDED", rec_cfg["20cm"], rec_cfg["3to4"], rec_cfg["pry"], rec_empty, rec_cfg["patch_mode"], save_df_out=True)
    if rec_df is not None:
        save_cols = [c for c in rec_df.columns if c != "mtm_pairs"]
        rec_df[save_cols].to_parquet(f"{OUT_DIR}/w3_1_recommended_trades.parquet", index=False)

    # Build flat comparison CSV covering ALL requested metrics
    csv_rows = []
    for r in all_records:
        if r["group"] == "RECOMMENDED":
            continue
        ws = r["windows"]
        fw = ws["FULL_WF"]
        y23 = ws["Y2023"]
        y24 = ws["Y2024"]
        y25 = ws["Y2025"]
        y26 = ws["Y2026"]
        y2526 = ws["Y2025_2026"]
        h2 = ws["Y2026H2"]
        s50 = r["stress_050"]["stock_050_etf_005"]
        s50_fw = s50["FULL_WF"]
        s50_e25_fw = r["stress_050"]["stock_050_etf_025"]["FULL_WF"]
        pm = r.get("perm_1000", {})
        vd = r.get("vs_v20_daily", {})
        csv_rows.append({
            "name": r["name"],
            "group": r["group"],
            "patch_mode": r["config"]["patch_mode"],
            "n_wf": fw["n"],
            "n_v20_kept": r["n_v20_kept"],
            "n_patch_added": r["n_patch_added"],
            "n_v20_skipped": r["n_v20_skipped"],
            "n_v20_locked_skip": r["n_v20_locked_skip"],
            "n_patch_yielded": r["n_patch_yielded"],
            "wr_wf_pct": fw["wr_pct"],
            "plr_wf": fw["plr"],
            "nav_wf": fw["nav"],
            "ex5_wf": fw["ex_top5_nav"],
            "mdd_wf_pct": fw["daily_mdd_pct"],
            "sharpe_wf": fw["daily_sharpe"],
            "calmar_wf": fw["daily_calmar"],
            "excess_csi300_wf_pp": fw["excess_csi300_pp"],
            "nav_2023": y23["nav"],
            "nav_2024": y24["nav"],
            "nav_2025": y25["nav"],
            "nav_2026": y26["nav"],
            "wr_2026_pct": y26["wr_pct"],
            "nav_2526": y2526["nav"],
            "ex5_2526": y2526["ex_top5_nav"],
            "sharpe_2526": y2526["daily_sharpe"],
            "nav_26h2": h2["nav"],
            "wr_26h2_pct": h2["wr_pct"],
            "mdd_26h2_pct": h2["daily_mdd_pct"],
            "perm_sd_p": pm.get("same_day_p_nav"),
            "perm_any_p": pm.get("any_cand_day_p_nav"),
            "corr_vs_v20_daily": vd.get("corr_vs_v20_daily"),
            "daily_diff_mean_bps": vd.get("daily_diff_mean_bps"),
            "daily_diff_max_abs_pct": vd.get("daily_diff_max_abs_pct"),
            "stress050_nav_wf": s50_fw["nav"],
            "stress050_ex5_wf": s50_fw["ex_top5_nav"],
            "stress050_mdd_wf_pct": s50_fw["daily_mdd_pct"],
            "stress050_sharpe_wf": s50_fw["daily_sharpe"],
            "stress050_calmar_wf": s50_fw["daily_calmar"],
            "stress050_nav_2526": s50["Y2025_2026"]["nav"],
            "stress050_nav_2026": s50["Y2026"]["nav"],
            "stress050_nav_26h2": s50["Y2026H2"]["nav"],
            "stress050_etf025_nav_wf": s50_e25_fw["nav"],
            "survival_ratio_050_vs_030": r["stress_050"]["survival_ratio_050_vs_030"],
            "mtm_diff": r["mtm_diff"],
        })

    df_cmp = pd.DataFrame(csv_rows)
    df_cmp.to_csv(f"{OUT_DIR}/w3_1_tier_compare.csv", index=False, encoding="utf-8-sig")

    audit_out = _sanitize({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": peak_rss_mb(),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "wf_window": f"{WF_START} ~ {WF_END}",
        "v20_baseline_native": ev_nat,
        "v20_baseline_unified_030": ev_030,
        "v20_baseline_stress_050": ev_050,
        "tier2_best_name": best_t2["name"],
        "tier3_best_name": best_t3["name"],
        "recommended_overall_name": best_overall["name"],
        "recommended_overall_summary": best_overall,
        "all_variants": all_records[:-1],
    })
    with open(f"{OUT_DIR}/w3_1_assembly_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit_out, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"\n[STAGE 2 COMPLETE in {time.time()-t0:.2f}s | Peak RSS={peak_rss_mb()} MB]")
    print(f"Saved: {OUT_DIR}/w3_1_tier_compare.csv ({len(df_cmp)} rows)")
    print(f"Saved: {OUT_DIR}/w3_1_assembly_audit.json")
    print(f"Saved: {OUT_DIR}/w3_1_recommended_trades.parquet")


if __name__ == "__main__":
    main()
