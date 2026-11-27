#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_task2_20cm_thresholds.py — Task 2: V20 High-Strict 20cm >= 82 & 20cm 80-81 Demotion/Drop on V22.
Tests:
  - stack_c50_avg >= 80 (Base V22) vs >= 81 / 82 / 83 / 84 (re-running standalone 20cm pre-occlusion!)
  - Symmetric pre-WF >= 83/84 vs WF-only >= 83/84
  - V20 orig_score >= 82 clean (base_82_clean)
  - 20cm 80-81 demoted AFTER 4to5@Pos5 (Pos6, rank=950) & AFTER Tier3 (before 4to5, rank=200),
    testing BOTH Non-Occluding Split (20cm>=82 standalone + 80-81 top1) and Legacy >=80 Split, plus PassTop1.
Zero yfinance (D12).
"""
import json
import os
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

import _audit_utils as au


def _build_20cm_pool_variant(
    c_p2: dict,
    fee_mode: str,
    wf_thr: float,
    pre_wf_thr: float = 82.0,
    use_orig_5y: bool = False,
    demote_low_band: Optional[tuple[float, float]] = None,
    split_non_occluding: bool = True,
    use_pass_top1: bool = False,
) -> pd.DataFrame:
    """
    Build modified 20cm pool rows cleanly in _p5_engine schema (`keep_cols` + `bucket`, `s2c_prio`).
    If `demote_low_band=(lo, hi)` is set, `score >= hi` gets bucket `20cm_S82` (prio 6),
    and `lo <= score < hi` gets bucket `20cm_A80_81` (custom rank, e.g. Pos6 after 4to5).
    """
    df = c_p2["pools_ext"]["20cm"].copy()
    rc, mc, _ = au.v22.eng._fee_cols(fee_mode, "20cm")
    df["net_ret"] = df[rc]
    df["mtm_use"] = df[mc]
    sc20 = c_p2["sc20_aligned"]
    WF_START = au.v22.eng.WF_START
    WF_END = au.v22.eng.WF_END

    if use_orig_5y:
        sv = df["orig_score"].to_numpy(float)
        if use_pass_top1:
            m = df["can_buy_hygiene"].fillna(True).to_numpy(bool) & np.isfinite(sv) & (sv >= wf_thr)
            sl = df[m].copy()
            sl["_sc_adj"] = sv[m]
            sl = sl.sort_values(["buy_date", "_sc_adj", "code"], ascending=[True, False, True], kind="mergesort").groupby("buy_date", as_index=False).first()
        else:
            sl = au.v22.eng._sim_20cm_score_df(df, sv, wf_thr)
        sl["score"] = sl["_sc_adj"].astype(float)
    else:
        sv_full = np.where(
            df["buy_date"] < WF_START,
            np.where(df["orig_score"].to_numpy(float) >= pre_wf_thr, df["orig_score"].to_numpy(float), -999.0),
            sc20["stack_c50_avg"],
        )
        if demote_low_band is not None and split_non_occluding and (not use_pass_top1):
            lo, hi = demote_low_band
            # Keep exact RD038 pre-WF (< WF_START) so WF change is isolated cleanly
            _, sl_pre76 = au.v22.eng.m1.sim_standalone("20cm", df, np.zeros(len(df)), cm20_thr=76.0)
            sl_pre = sl_pre76[(sl_pre76["buy_date"] < WF_START) & (sl_pre76["orig_score"] >= pre_wf_thr)].copy()
            sl_pre["score"] = sl_pre["orig_score"].astype(float)
            # WF high band (>= hi) runs clean standalone occlusion without low band occluding it
            sv_hi_wf = np.where((df["buy_date"] >= WF_START) & (sc20["stack_c50_avg"] >= hi), sc20["stack_c50_avg"], -999.0)
            sl_hi_wf = au.v22.eng._sim_20cm_score_df(df, sv_hi_wf, hi)
            sl_hi_wf["score"] = sl_hi_wf["_sc_adj"].astype(float)
            # WF low band ([lo, hi)) takes daily top-1 on WF days without hi standalone trade
            m_lo = (df["buy_date"] >= WF_START).to_numpy(bool) & df["can_buy_hygiene"].fillna(True).to_numpy(bool) & np.isfinite(sv_full) & (sv_full >= lo) & (sv_full < hi)
            sl_lo = df[m_lo].copy()
            sl_lo["score"] = sv_full[m_lo].astype(float)
            sl_lo = sl_lo.sort_values(["buy_date", "score", "code"], ascending=[True, False, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            sl_lo = sl_lo[~sl_lo["buy_date"].isin(set(sl_hi_wf["buy_date"]))].copy()
            sl = pd.concat([sl_pre, sl_hi_wf, sl_lo], ignore_index=True)
        elif use_pass_top1:
            thr_eff = demote_low_band[0] if demote_low_band else wf_thr
            m = df["can_buy_hygiene"].fillna(True).to_numpy(bool) & np.isfinite(sv_full) & (sv_full >= thr_eff)
            sl = df[m].copy()
            sl["score"] = sv_full[m].astype(float)
            sl = sl.sort_values(["buy_date", "score", "code"], ascending=[True, False, True], kind="mergesort").groupby("buy_date", as_index=False).first()
        else:
            # Exact RD038 pre-WF logic (at 76 pre-occlusion, filtered >= pre_wf_thr) + WF _sim_20cm_score_df at wf_thr
            _, sl_pre76 = au.v22.eng.m1.sim_standalone("20cm", df, np.zeros(len(df)), cm20_thr=76.0)
            sl_pre = sl_pre76[(sl_pre76["buy_date"] < WF_START) & (sl_pre76["orig_score"] >= pre_wf_thr)].copy()
            sl_pre["score"] = sl_pre["orig_score"].astype(float)
            sv_wf = np.where(df["buy_date"] >= WF_START, sc20["stack_c50_avg"], -999.0)
            thr_eff = demote_low_band[0] if demote_low_band else wf_thr
            sl_wf = au.v22.eng._sim_20cm_score_df(df, sv_wf, thr_eff)
            sl_wf["score"] = sl_wf["_sc_adj"].astype(float)
            sl = pd.concat([sl_pre, sl_wf], ignore_index=True)

    sl = sl[sl["buy_date"].between("2021-11-16", WF_END)].copy()
    sl["strategy"] = "20cm"
    sl["tier"] = "20cm_S(>=82)"
    sl["is_untrig"] = False
    if "buy_price_val" not in sl.columns:
        sl["buy_price_val"] = pd.to_numeric(sl.get("buy_price", np.nan), errors="coerce")
    if "is_adj_px" not in sl.columns:
        sl["is_adj_px"] = False
    sl["buy_date"] = sl["buy_date"].astype(str).str[:10]
    sl["exit_date"] = sl["exit_date"].astype(str).str[:10]
    sl["buy_hhmm"] = pd.to_numeric(sl["buy_hhmm"], errors="coerce").fillna(925).astype(int)
    sl["exit_hhmm"] = pd.to_numeric(sl["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
    sl["code"] = sl["code"].astype(str).str.zfill(6)
    sl["score"] = pd.to_numeric(sl["score"], errors="coerce").astype(float)
    sl["net_ret"] = pd.to_numeric(sl["net_ret"], errors="coerce").astype(float)
    sl["s2c_prio"] = 6

    if demote_low_band is not None:
        _, hi = demote_low_band
        sl["bucket"] = np.where(sl["score"] >= hi, "20cm_S82p", "20cm_A80_81")
    else:
        sl["bucket"] = np.where(sl["score"] >= 86.0, "20cm_S86", "20cm_80_85")

    keep = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "mtm_use", "buy_price_val", "is_adj_px", "is_untrig", "bucket", "s2c_prio"]
    return sl[keep].reset_index(drop=True)


def _swap_20cm_in_mp(mp: pd.DataFrame, df20_new: pd.DataFrame) -> pd.DataFrame:
    mp_no20 = mp[mp["strategy"] != "20cm"].copy()
    return pd.concat([mp_no20, df20_new], ignore_index=True).reset_index(drop=True)


def _make_rank_with_demote(rk_80_81: int):
    def _fn(df: pd.DataFrame) -> np.ndarray:
        is_45 = (df["strategy"] == "4to5").to_numpy(bool)
        is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"]).to_numpy(bool)
        is_p0 = (df["buy_hhmm"].to_numpy(int) == 925) | is_s_cond
        s2c_p = df["s2c_prio"].to_numpy(int)
        base_rk = np.where(is_p0, s2c_p * 10, 1000 + s2c_p * 10)
        rk_45 = np.where(is_45, 2000, base_rk)
        return np.where(df["bucket"].to_numpy() == "20cm_A80_81", rk_80_81, rk_45)
    return _fn


def main():
    t0 = time.time()
    assets = au.load_all_assets()
    c_p2 = assets["c_p2"]
    cal_5y = assets["cal_5y"]

    # Check Base 20cm parity first
    s20_chk = _build_20cm_pool_variant(c_p2, "030", wf_thr=80.0, pre_wf_thr=82.0)
    mp_chk = _swap_20cm_in_mp(assets["mp030"], s20_chk)
    sim_chk = au.p5.run_priority_sim(mp_chk, au.base_engine_rank_fn(), cal_5y, allow_untrig=True)
    assert float(np.max(np.abs(sim_chk["dr_5y"] - assets["base_030"]["dr_5y"]))) < 1e-12

    from typing import Optional  # local safe
    specs = [
        ("T2_20cm_WF_ge81", 81.0, 82.0, False, None, True, 60, "20cm stack_c50_avg >= 81 (pre-WF >= 82)"),
        ("T2_20cm_WF_ge82_Drop8081", 82.0, 82.0, False, None, True, 60, "20cm stack_c50_avg >= 82 (drop 80-81 completely; pre-WF >= 82)"),
        ("T2_20cm_WF_ge83_Pre82", 83.0, 82.0, False, None, True, 60, "20cm stack_c50_avg >= 83 WF-only (pre-WF >= 82)"),
        ("T2_20cm_WF_ge83_Pre83", 83.0, 83.0, False, None, True, 60, "20cm stack_c50_avg >= 83 & pre-WF orig >= 83"),
        ("T2_20cm_WF_ge84_Pre82", 84.0, 82.0, False, None, True, 60, "20cm stack_c50_avg >= 84 WF-only (pre-WF >= 82)"),
        ("T2_20cm_WF_ge84_Pre84", 84.0, 84.0, False, None, True, 60, "20cm stack_c50_avg >= 84 & pre-WF orig >= 84"),
        ("T2_20cm_V20_Orig82Clean", 82.0, 82.0, True, None, True, 60, "V20 orig_score >= 82 clean across all 5Y (no 76-81 pre-occlusion)"),
        ("T2_20cm_8081_After4to5_Pos6_NoOcc", 80.0, 82.0, False, (80.0, 82.0), True, 2500, "20cm>=82@Pos2 + 20cm(80-81)@Pos6 after 4to5@Pos5 (non-occluding split)"),
        ("T2_20cm_8081_After4to5_Pos6_LegOcc", 80.0, 82.0, False, (80.0, 82.0), False, 2500, "20cm>=82@Pos2 + 20cm(80-81)@Pos6 after 4to5@Pos5 (legacy >=80 pre-occ)"),
        ("T2_20cm_8081_AfterTier3_Before4to5", 80.0, 82.0, False, (80.0, 82.0), True, 1500, "20cm>=82@Pos2 + 20cm(80-81) after Tier3 before 4to5 (non-occluding)"),
    ]

    results = {}
    rows = []
    for vid, wthr, pthr, use_orig, dem_band, split_noocc, rk_low, desc in specs:
        mp030_v = _swap_20cm_in_mp(assets["mp030"], _build_20cm_pool_variant(c_p2, "030", wthr, pthr, use_orig, dem_band, split_noocc, False))
        mp050_v = _swap_20cm_in_mp(assets["mp050"], _build_20cm_pool_variant(c_p2, "050", wthr, pthr, use_orig, dem_band, split_noocc, False))
        mppt_v = _swap_20cm_in_mp(assets["mp_pt030"], _build_20cm_pool_variant(c_p2, "030", wthr, pthr, use_orig, dem_band, split_noocc, True))

        rfn = _make_rank_with_demote(rk_low) if dem_band is not None else au.base_engine_rank_fn()
        s030 = au.p5.run_priority_sim(mp030_v, rfn, cal_5y, allow_untrig=True)
        s050 = au.p5.run_priority_sim(mp050_v, rfn, cal_5y, allow_untrig=True)
        spt = au.p5.run_priority_sim(mppt_v, rfn, cal_5y, allow_untrig=True)
        ev = au.evaluate_variant_complete(vid, "TASK2_20CM_THRESHOLDS", desc, s030, s050, spt, assets, n_perm=1000)
        results[vid] = ev
        rows.append(ev["row"])

    df_res = pd.DataFrame(rows)
    df_res.to_csv(f"{au.OUT_DIR}/task2_20cm_thresholds.csv", index=False, encoding="utf-8-sig")
    out_json = au.v22.sanitize_json({
        "task": "Task 2: V20 High-Strict 20cm>=82 & 80-81 Demotion/Drop",
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "pass_all_4_gates": [r["variant"] for r in rows if r["PASS_ALL_4_GATES"]],
        "rows": rows,
        "details": results,
    })
    with open(f"{au.OUT_DIR}/task2_20cm_thresholds.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)

    cols = ["variant", "n_trades", "5Y_nav", "5Y_mdd", "5Y_sh", "IS_nav", "OOS_nav", "WF_nav", "Y26_nav", "ex_both_5Y", "ex_both_WF", "ex_both_IS", "ex_both_OOS", "PASS_ALL_4_GATES"]
    print(df_res[cols].to_string(index=False))
    print("TASK 2 PASSERS:", [r["variant"] for r in rows if r["PASS_ALL_4_GATES"]])


if __name__ == "__main__":
    from typing import Optional
    main()
