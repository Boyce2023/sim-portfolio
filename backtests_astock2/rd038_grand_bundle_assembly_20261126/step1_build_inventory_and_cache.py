#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD038 Step 1: Clean Candidate Inventory + Unified Parity-Verified Cache Builder.

Reconstructs & parity-verifies all clean causal candidates (exit_date < t) across:
  - 20cm (RD036 Stack_c50_Avg_CB15_MN15_R3W12_S80, Blend_c50_Half_CB15_MN15_S80, NoRound, Cold50_S80, CleanB_c50_S80)
  - Other 5 strategies (RD035 W2A1/W2A2 + RD036 Part2 causal candidates vs static LOO controls)
  - W2A5 Weak-Red 09:25 Swap b0/tp1 causal lookup
  - W2A6 Priority & 1to2_S>=340 Wait Reservation untriggered pool

Outputs in `rd038_grand_bundle_assembly_20261126/`:
  - `rd038_candidate_inventory.csv`
  - `_cache/rd038_master_cache.pkl`

Zero yfinance (D12). Zero cap10m. Threads <= 2. Peak RSS < 2.2 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import math
import pickle
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
pa.set_memory_pool(pa.system_memory_pool())
assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
RD036 = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126"
WAVE1 = f"{RD035}/wave1_base"
W2A1 = f"{RD035}/wave2a/w2a1_old_1to2_2to3"
W2A2 = f"{RD035}/wave2a/w2a2_old_3to4_high_pry"
W2A5 = f"{RD035}/wave2a/w2a5_exit_tree_swaps"
PART1_20CM = f"{RD036}/part1_20cm"
PART2_O5 = f"{RD036}/part2_other5"
RD028 = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"

OUT_DIR = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

for p in (PART2_O5, PART1_20CM, WAVE1, RD028, PARTC_V20):
    if p not in sys.path:
        sys.path.insert(0, p)

import _common_rd036 as cm
import run_m1_m2_cold_and_pairwise as m12
import run_m3_m4_3way_4way_trees as m34
import rd036_lib as lib20
import step4_mod_rules_and_sim as m1
import tier_priority_engine as tpe


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def build_candidate_inventory() -> pd.DataFrame:
    """
    Audit and inventory ALL recent RD035 + RD036 candidates, strictly distinguishing:
      - STRICT_CAUSAL_WF (exit_date < t)
      - PURE_PHYSICAL_STATIC (zero ML fitting, pure physical regime rule)
      - STATIC_POSTHOC_LOO (full-sample LOO illusion -> barred from causal bundles)
      - EXCLUDED_TOXIC_LEAKY (GBDT_D3, 512100, ModE_E3, ModC_C1, W2B4_A5, RD037)
    """
    rows = []

    def add(cid, source, target, name, caus, stand_n, stand_nav, stand_sh, comb_r_rep, inc_robust, inc_off, reason):
        rows.append({
            "candidate_id": cid,
            "source_rd": source,
            "target_layer": target,
            "raw_variant_name": name,
            "causality_class": caus,
            "standalone_n_wf": stand_n,
            "standalone_nav_wf": stand_nav,
            "standalone_sharpe_wf": stand_sh,
            "reported_comb_ratio": comb_r_rep,
            "in_allin_robust": inc_robust,
            "in_allin_offensive": inc_off,
            "audit_reason": reason,
        })

    # --- 20cm ---
    g20 = pd.read_csv(f"{PART1_20CM}/rd036_20cm_grid.csv").set_index("variant")
    for cid, vname, caus, r_flag, o_flag, rsn in [
        ("20cm_Stack_c50_S80", "Stack_c50_Avg_CB15_MN15_R3W12_S80", "STRICT_CAUSAL_WF", True, False,
         "RD036 Tier2 steady winner: min MDD (26.08%), max WR (61.24%), NoRound=111.88x, 0 crowding"),
        ("20cm_Blend_c50_S80", "Blend_c50_Half_CB15_MN15_S80", "STRICT_CAUSAL_WF", False, True,
         "RD036 Tier2 offensive winner: max NAV (146.36x), Sharpe 2.413, 16/16 S80 plateau"),
        ("20cm_Cold50_S80", "COLD50_S80", "PURE_PHYSICAL_STATIC", False, False,
         "Pure physical F06 cold-day disable control (zero scorecard fitting)"),
        ("20cm_CleanB_c50_S80", "CLEANB_cold50_d15_S80", "STRICT_CAUSAL_WF", False, False,
         "RD035 W2A3 Tier2 baseline reference"),
        ("20cm_GBDT_D3_S80", "GBDT_D3_cold50_d8_S80", "EXCLUDED_TOXIC_LEAKY", False, False,
         "KILLED in RD036: d8 single-point spike + crowds out 合富中国 in V20 combined"),
    ]:
        r = g20.loc[vname]
        add(cid, "RD036_Part1", "20cm", vname, caus, int(r["n_wf"]), round(float(r["nav_wf"]), 4),
            round(float(r["sharpe_wf"]), 3), round(float(r.get("comb_wf_nav_ratio", np.nan)), 4) if pd.notna(r.get("comb_wf_nav_ratio")) else None,
            r_flag, o_flag, rsn)
    add("20cm_Stack_NoRound_S80", "RD036_Part3", "20cm", "Stack_c50_Avg_CB15_MN15_R3W12_NoRound_S80",
        "STRICT_CAUSAL_WF", 128, 111.8822, 2.370, None, False, False, "Zero-rounding sensitivity control for Stack")
    add("20cm_Blend_NoRound_S80", "RD036_Part3", "20cm", "Blend_c50_Half_CB15_MN15_NoRound_S80",
        "STRICT_CAUSAL_WF", 129, 104.1349, 2.365, None, False, False, "Zero-rounding sensitivity control for Blend")

    # --- Other 5 strategies (RD036 Part2 + RD035 W2A1/W2A2) ---
    go5 = pd.read_csv(f"{PART2_O5}/rd036_other5_grid.csv")
    def _get_o5(st, vid):
        return go5[(go5["strategy"] == st) & (go5["variant_id"] == vid)].iloc[0]

    # 3to4
    r34_4w = _get_o5("3to4", "M4_4WayMineBL15_SafePool")
    add("3to4_M4_4WayMineBL15", "RD036_Part2", "3to4", "M4_4WayMineBL15_SafePool", "STRICT_CAUSAL_WF",
        int(r34_4w["n_trades"]), round(float(r34_4w["nav_wf"]), 4), round(float(r34_4w["exact_mtm_sharpe"]), 3),
        round(float(r34_4w["comb_nav_ratio"]), 4), True, True,
        "Causal exit_date<t 4-way minefield blacklist top 15%; beats base on NAV, Sharpe, and comb")
    r34_pr = _get_o5("3to4", "M2_Pair_cold_only_cut45_d15")
    add("3to4_M2_PairCold45_d15", "RD036_Part2", "3to4", "M2_Pair_cold_only_cut45_d15", "STRICT_CAUSAL_WF",
        int(r34_pr["n_trades"]), round(float(r34_pr["nav_wf"]), 4), round(float(r34_pr["exact_mtm_sharpe"]), 3),
        round(float(r34_pr["comb_nav_ratio"]), 4), False, False,
        "Causal cold<45 pairwise delta15 sensitivity control for 3to4")
    w2a2_tbl = pd.read_csv(f"{W2A2}/w2a2_variants_table.csv")
    r34_w2 = w2a2_tbl[(w2a2_tbl["strategy"] == "3to4") & (w2a2_tbl["variant_id"] == "M4_MineBL15_OrigScore")].iloc[0]
    add("3to4_W2A2_MineBL15", "RD035_W2A2", "3to4", "M4_MineBL15_OrigScore", "STRICT_CAUSAL_WF",
        int(r34_w2["n_trades"]), round(float(r34_w2["nav_wf"]), 4), round(float(r34_w2["sharpe"]), 3),
        round(float(r34_w2["v20_comb_delta_ratio_vs_leg030"]), 4), False, False,
        "RD035 W2A2 causal 1-way minefield blacklist top 15% control")
    r34_st = _get_o5("3to4", "M1_AllLOO_s34_af_20")
    add("3to4_StaticLOO_af20", "RD036_Part2", "3to4", "M1_AllLOO_s34_af_20", "STATIC_POSTHOC_LOO",
        int(r34_st["n_trades"]), round(float(r34_st["nav_wf"]), 4), round(float(r34_st["exact_mtm_sharpe"]), 3),
        round(float(r34_st["comb_nav_ratio"]), 4), False, False,
        "STATIC full-sample LOO drop s34_af_20 (post-hoc illusion -> barred from causal bundles)")

    # 2to3
    r23_pr = _get_o5("2to3", "M2_Pair_cold_only_cut45_d15")
    add("2to3_M2_PairCold45_d15", "RD036_Part2", "2to3", "M2_Pair_cold_only_cut45_d15", "STRICT_CAUSAL_WF",
        int(r23_pr["n_trades"]), round(float(r23_pr["nav_wf"]), 4), round(float(r23_pr["exact_mtm_sharpe"]), 3),
        round(float(r23_pr["comb_nav_ratio"]), 4), True, True,
        "Only causal 2to3 variant beating base on BOTH standalone (51.64x/Sh2.46) and comb (1.08x)")
    r23_st = _get_o5("2to3", "M1_ColdLOO_s23_af_17_cut50")
    add("2to3_StaticColdLOO_af17", "RD036_Part2", "2to3", "M1_ColdLOO_s23_af_17_cut50", "STATIC_POSTHOC_LOO",
        int(r23_st["n_trades"]), round(float(r23_st["nav_wf"]), 4), round(float(r23_st["exact_mtm_sharpe"]), 3),
        round(float(r23_st["comb_nav_ratio"]), 4), False, False,
        "STATIC full-sample LOO drop s23_af_17 -> barred from causal bundles")
    w2a1_tbl = pd.read_csv(f"{W2A1}/w2a1_variants_table.csv")
    r23_w1 = w2a1_tbl[(w2a1_tbl["strat"] == "2to3") & (w2a1_tbl["variant"] == "LOO_drop_s23_af_05")].iloc[0]
    add("2to3_W2A1_StaticLOO_af05", "RD035_W2A1", "2to3", "LOO_drop_s23_af_05", "STATIC_POSTHOC_LOO",
        int(r23_w1["n_trades"]), round(float(r23_w1["nav_wf"]), 4), round(float(r23_w1["sharpe_wf"]), 3),
        round(float(r23_w1["comb_nav_ratio"]), 4), False, False,
        "STATIC full-sample LOO drop s23_af_05 (failed IS consistency) -> barred")

    # high
    rh_ca = _get_o5("high", "M1_CausalColdBonusDrop_cut40_t0")
    add("high_M1_CausalColdDrop40_t0", "RD036_Part2", "high", "M1_CausalColdBonusDrop_cut40_t0", "STRICT_CAUSAL_WF",
        int(rh_ca["n_trades"]), round(float(rh_ca["nav_wf"]), 4), round(float(rh_ca["exact_mtm_sharpe"]), 3),
        round(float(rh_ca["comb_nav_ratio"]), 4), True, True,
        "Causal exit_date<t cold-day (<40) negative bonus atom drop; trims 1 cold loss (30t, 10.12x)")

    # pry
    rp_sk = _get_o5("pry", "M1_SkipCold_cut50")
    add("pry_M1_SkipCold50", "RD036_Part2", "pry", "M1_SkipCold_cut50", "PURE_PHYSICAL_STATIC",
        int(rp_sk["n_trades"]), round(float(rp_sk["nav_wf"]), 4), round(float(rp_sk["exact_mtm_sharpe"]), 3),
        round(float(rp_sk["comb_nav_ratio"]), 4), True, False,
        "Pure physical skip cold<50 (n=6, WR=100%, 1.568x); tiny sample warning")
    rp_pr = _get_o5("pry", "M2_Pair_cold_only_cut45_d15")
    add("pry_M2_PairCold45_d15", "RD036_Part2", "pry", "M2_Pair_cold_only_cut45_d15", "STRICT_CAUSAL_WF",
        int(rp_pr["n_trades"]), round(float(rp_pr["nav_wf"]), 4), round(float(rp_pr["exact_mtm_sharpe"]), 3),
        round(float(rp_pr["comb_nav_ratio"]), 4), False, True,
        "Causal cold<45 pairwise delta15 (n=10, 1.579x); tiny sample warning")
    rp_w2 = w2a2_tbl[(w2a2_tbl["strategy"] == "pry") & (w2a2_tbl["variant_id"] == "M1_WF_DropNeg_tm05")].iloc[0]
    add("pry_W2A2_DropNeg_tm05", "RD035_W2A2", "pry", "M1_WF_DropNeg_tm05", "STRICT_CAUSAL_WF",
        int(rp_w2["n_trades"]), round(float(rp_w2["nav_wf"]), 4), round(float(rp_w2["sharpe"]), 3),
        round(float(rp_w2["v20_comb_delta_ratio_vs_leg030"]), 4), False, False,
        "RD035 W2A2 causal prune tm05 (n=6, 1.517x) control")

    # 1to2 -> 0 clean causal upgrades
    r12_w1 = w2a1_tbl[(w2a1_tbl["strat"] == "1to2") & (w2a1_tbl["variant"] == "New330_XTR37_ModeB_d15_t15_k8")].iloc[0]
    add("1to2_W2A1_ModeB_d15", "RD035_W2A1", "1to2", "New330_XTR37_ModeB_d15_t15_k8", "STRICT_CAUSAL_WF",
        int(r12_w1["n_trades"]), round(float(r12_w1["nav_wf"]), 4), round(float(r12_w1["sharpe_wf"]), 3),
        round(float(r12_w1["comb_nav_ratio"]), 4), False, False,
        "REJECTED/ZERO GAIN: adds 1 trade but 0.00% V20 combined impact -> 1to2 keeps 0 upgrades")
    r12_t4 = _get_o5("1to2", "M4_TreeD4_Single_d8")
    add("1to2_RD036_TreeD4_d8", "RD036_Part2", "1to2", "M4_TreeD4_Single_d8", "EXCLUDED_TOXIC_LEAKY",
        int(r12_t4["n_trades"]), round(float(r12_t4["nav_wf"]), 4), round(float(r12_t4["exact_mtm_sharpe"]), 3),
        round(float(r12_t4["comb_nav_ratio"]), 4), False, False,
        "REJECTED: depth-4 tree (overfit risk) + 0.00% V20 combined impact -> 1to2 = 0 clean items")

    # --- W2A5 Exit Swaps & W2A6 Priority/Waits ---
    add("w2a5_WeakRed_S_HighTier", "RD035_W2A5", "exit_swap", "M2_v20_slot|1to2+2to3|b0_red_close|gap_0.5_2.5|S_HighTier|0925_simul",
        "STRICT_CAUSAL_WF", 207, 534297.0317, 4.624, 1.0000, True, True,
        "Causal T+1 09:25 weak-red open (+0.5..+2.5%) swap only into S_HighTier; tested dynamically in All-In")
    add("w2a6_1to2S_Wait_Reserve", "RD035_W2A6", "priority_wait", "M1_WAIT_Plus1to2S",
        "STRICT_CAUSAL_WF", 206, 814328.7, 4.808, 1.3312, True, True,
        "1to2_S>=340 enters S-tier 09:35..11:30 wait phase=0 (tested both with & without untriggered wait)")
    add("w2a6_1to2S_TrigOnly_gt_20cm", "RD035_W2A6_EXT", "priority_wait", "M1_1to2S_TrigOnly_phase0",
        "STRICT_CAUSAL_WF", 207, None, None, None, False, False,
        "Triggered 1to2_S>=340 gets phase=0 > 20cm WITHOUT untriggered wait blocking 3to4_A")

    # --- Explicitly Excluded Toxic/Leaky Items ---
    for cid, src, tgt, rsn in [
        ("512100_ETF_V3", "RD035_W2B5", "empty_slot", "EXCLUDED: intraday nt_v3_score peek + tiny sample (n=11) + 25-26 stall"),
        ("ModE_E3_US4pct", "RD035_W2B6", "empty_slot", "EXCLUDED: post-hoc US-to-A mapping tree leakage"),
        ("ModC_C1_EarnPre", "RD035_W2B6", "empty_slot", "EXCLUDED: ex-top5 negative (0.82x) + isolated top10 island"),
        ("W2B4_A5_20cm_1to2", "RD035_W2B4", "empty_slot", "EXCLUDED: 2026H2 collapse (0.69x)"),
        ("RD037_1to2_Peers", "RD037", "1to2", "EXCLUDED per prompt / falsified peer-leader variant"),
    ]:
        add(cid, src, tgt, cid, "EXCLUDED_TOXIC_LEAKY", None, None, None, None, False, False, rsn)

    inv_df = pd.DataFrame(rows)
    inv_df.to_csv(f"{OUT_DIR}/rd038_candidate_inventory.csv", index=False, encoding="utf-8-sig")
    print(f"[Inventory] Saved {len(inv_df)} candidate rows to {OUT_DIR}/rd038_candidate_inventory.csv")
    return inv_df


def _build_b0_tp1_state_lookup(pools_all: dict, cal_5y: list[str]) -> dict:
    """
    Build exact causal b0/tp1 09:25 weak-red state lookup keyed by (code, buy_date)
    for all 1to2 / 2to3 / 3to4 trades across 2021-11-16..2026-11-16.
    """
    if W2A5 not in sys.path:
        sys.path.insert(0, W2A5)
    import w2a5_data_loader as dl
    ctx_w5 = dl.load_w2a5_context("2026-11-16", load_5m=False)
    ss_map = ctx_w5["stock_series"]

    b0_lu = {}
    for st in ("1to2", "2to3", "3to4"):
        df = pools_all[st]
        for r in df.itertuples(index=False):
            c6 = str(r.code).zfill(6)
            bd = str(r.buy_date)[:10]
            k = (st, c6, bd)
            if k in b0_lu:
                continue
            ss = ss_map.get(c6)
            if ss is None or bd not in ss["d2i"]:
                continue
            b0 = ss["d2i"][bd]
            if b0 + 1 >= len(ss["dts"]):
                continue
            k1 = b0 + 1
            pc0 = float(ss["prev_c"][b0])
            c0 = float(ss["close"][b0])
            o0 = float(ss["open"][b0])
            zt0 = bool(ss["is_zt"][b0])
            tp1_dt = str(ss["dts"][k1])
            o1 = float(ss["open"][k1])
            pc1 = float(ss["prev_c"][k1])
            op1_pct = (o1 / pc1 - 1.0) * 100.0 if pc1 > 0 else np.nan
            sellable_0925 = (not bool(ss["is_yizi_dt"][k1])) and (o1 > float(ss["dt_px"][k1]) + 0.005)
            adjf0 = float(ss["adjf"][b0])
            bp_val = float(r.buy_price) if pd.notna(getattr(r, "buy_price", np.nan)) else o0
            buy_adj = bp_val * adjf0
            gross_0925 = (o1 * float(ss["adjf"][k1]) / buy_adj - 1.0) if buy_adj > 0 else 0.0
            b0_lu[k] = {
                "b0_unsealed": (not zt0),
                "b0_red_close": (not zt0) and (pc0 > 0) and (c0 > pc0),
                "tp1_dt": tp1_dt,
                "op1_pct": float(op1_pct),
                "sellable_0925": sellable_0925,
                "gross_0925": float(gross_0925),
                "buy_adj": float(buy_adj),
                "o1_adj": float(o1 * float(ss["adjf"][k1])),
            }
    del ctx_w5
    gc.collect()
    pa.default_memory_pool().release_unused()
    return b0_lu


def main():
    t0 = time.time()
    inv_df = build_candidate_inventory()

    print("[1/5] Loading RD036 other5 bundle (full 5Y pools + exact MTM + bars) ...")
    bundle = cm.build_or_load_cache(force_rebuild=False)
    v20_ctx = bundle["v20_ctx"]
    cal_5y = bundle["cal_5y"]
    cal_wf = bundle["cal_wf"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    T_5y = len(cal_5y)

    # Extend MTM segments on all 6 pools across full 5Y (at 0.20%, 0.30%, 0.50%, 0.80%)
    # IMPORTANT: In pools_6strat/rd036 cache, other5 native is 0.20% while 20cm native is ALREADY 0.30%!
    pools_ext = {}
    for st in cm.ALL6:
        df = bundle["pools"][st].copy()
        if st == "20cm":
            df["net_ret_native"] = df["net_ret_020"]  # native 20cm in cache is 0.30%
            df["mtm_5y_native"] = df["mtm_5y_020"]
            df["net_ret_030"] = df["net_ret_native"]
            df["net_ret_050"] = (1.0 + df["net_ret_030"]) / 0.9970 * 0.9950 - 1.0
            df["net_ret_080"] = (1.0 + df["net_ret_030"]) / 0.9970 * 0.9920 - 1.0
            df["net_ret_020"] = (1.0 + df["net_ret_030"]) / 0.9970 * 0.9980 - 1.0
            df["mtm_5y_030"] = df["mtm_5y_native"]
            df["mtm_5y_050"] = [cm.scale_mtm_segs(s, r30, r50) for s, r30, r50 in zip(df["mtm_5y_native"], df["net_ret_030"], df["net_ret_050"])]
            df["mtm_5y_080"] = [cm.scale_mtm_segs(s, r30, r80) for s, r30, r80 in zip(df["mtm_5y_native"], df["net_ret_030"], df["net_ret_080"])]
            df["mtm_5y_020"] = [cm.scale_mtm_segs(s, r30, r20) for s, r30, r20 in zip(df["mtm_5y_native"], df["net_ret_030"], df["net_ret_020"])]
        else:
            df["net_ret_native"] = df["net_ret_020"]  # native other5 is 0.20%
            df["mtm_5y_native"] = df["mtm_5y_020"]
            df["mtm_5y_030"] = [cm.scale_mtm_segs(s, r20, r30) for s, r20, r30 in zip(df["mtm_5y_020"], df["net_ret_020"], df["net_ret_030"])]
            df["mtm_5y_050"] = [cm.scale_mtm_segs(s, r20, r50) for s, r20, r50 in zip(df["mtm_5y_020"], df["net_ret_020"], df["net_ret_050"])]
            df["mtm_5y_080"] = [cm.scale_mtm_segs(s, r20, r80) for s, r20, r80 in zip(df["mtm_5y_020"], df["net_ret_020"], df["net_ret_080"])]
        pools_ext[st] = df

    # Verify exact V20.0 native 5Y & WF baseline parity on pools_ext!
    print("[2/5] Verifying V20.0 baseline 5Y & WF parity (69.13M x / 611.7k x) ...")
    parts_v20 = []
    trig_dts_v20 = {}
    for st in cm.ALL6:
        df = pools_ext[st].copy()
        df["net_ret"] = df["net_ret_native"]
        if st == "20cm":
            _, sl = m1.sim_standalone("20cm", df, np.zeros(len(df)), cm20_thr=76.0)
        else:
            _, sl = cm.sim_strategy(st, df, df["orig_score"].to_numpy(float), wf_only=False)
        sl = sl[sl["buy_date"].between("2021-11-16", "2026-11-16")].copy()
        sl["strategy"] = st
        sl["score"] = [round(float(x), 1) for x in sl["orig_score"]] if st == "1to2" else sl["orig_score"].astype(float)
        sl["tier"] = [tpe.assign_physical_tier(st, sc) for sc in sl["score"]]
        trig_dts_v20[st] = set(sl["buy_date"])
        parts_v20.append(sl)
    pool6_v20 = pd.concat(parts_v20, ignore_index=True)
    pool6_v20["buy_price_val"] = np.nan
    pool6_v20["is_adj_px"] = False
    pool6_v20["is_untrig"] = False

    # Full 5Y untriggered pool from wave1_base/v20_waits_41 + rd034/untrig
    ut_full_raw = pd.read_parquet(f"{SIM}/backtests_astock2/rd034_ashare_3layer_cycles_6strat_20261125/rd034_untrig_with_3layer_cycles.parquet")
    ut_full_raw["buy_date"] = ut_full_raw["buy_date"].astype(str).str[:10]
    ut_full_raw["code"] = ut_full_raw["code"].astype(str).str.zfill(6)
    ut_full_raw["v20_score"] = ut_full_raw["score"].astype(float)
    ut_full_raw = ut_full_raw[ut_full_raw["buy_date"].between("2021-11-16", "2026-11-16")].copy().reset_index(drop=True)

    def _build_ut(trig_map):
        ut_parts = []
        for st_u in ("3to4", "high", "1to2"):
            sub_u = ut_full_raw[(ut_full_raw["strategy"] == st_u) & (~ut_full_raw["buy_date"].isin(trig_map.get(st_u, set())))].copy()
            thr_u = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[st_u]
            sub_u = sub_u[sub_u["score"] >= thr_u].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
            if not sub_u.empty:
                sub_u["tier"] = [tpe.assign_physical_tier(st_u, sc) for sc in sub_u["score"]]
                ut_parts.append(sub_u)
        if not ut_parts:
            return pd.DataFrame()
        utf = pd.concat(ut_parts, ignore_index=True)
        utf["is_untrig"] = True
        utf["net_ret"] = 0.0
        utf["buy_price_val"] = np.nan
        utf["is_adj_px"] = False
        return utf[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig"]]

    ut_v20 = _build_ut(trig_dts_v20)
    tr_v20_check, _ = tpe.run_single_slot(pool6_v20, lambda d: d["tier"].map(m1.S2C_MAP).fillna(999).to_numpy(), untrig_df=ut_v20, timing_mode="s_tier_reserve_only")
    nav_5y_chk = float(np.prod(1.0 + tr_v20_check["net_ret"].to_numpy(float)))
    tr_v20_wf = tr_v20_check[tr_v20_check["buy_date"] >= "2023-01-03"]
    nav_wf_chk = float(np.prod(1.0 + tr_v20_wf["net_ret"].to_numpy(float)))
    assert len(tr_v20_check) == 278 and abs(nav_5y_chk - 69134091.5067) < 2.0, f"5Y parity fail: {len(tr_v20_check)}/{nav_5y_chk}"
    assert len(tr_v20_wf) == 207 and abs(nav_wf_chk - 611729.5546) < 0.05, f"WF parity fail: {len(tr_v20_wf)}/{nav_wf_chk}"
    print(f"  [V20 Parity OK] 5Y: n={len(tr_v20_check)} nav={nav_5y_chk:,.2f}x | WF: n={len(tr_v20_wf)} nav={nav_wf_chk:,.2f}x")

    # [3/5] Reconstruct ALL 20cm candidates (RD036 Stack, Blend, NoRound, Cold50, CleanB)
    print("[3/5] Reconstructing RD036 20cm candidates (Stack, Blend, NoRound, Cold50, CleanB) ...")
    p20, meta20 = lib20.load_20cm_enriched_data()
    p20["wf_in_window"] = p20["buy_date"] >= "2023-01-03"
    feat_cb = meta20["feat_clean_b"]
    feat_ix = meta20["ix_cols"]
    feat_union = meta20["feat_union_cb_mech"]
    atomic_cols = meta20["atomic_cols"]

    dm_cb, _ = lib20.run_mode_b_multi_grid(p20, feat_cb, ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=15, top_k=10)
    dm_mn, _ = lib20.run_mode_b_multi_grid(p20, feat_ix, ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=0, top_k=10)
    ho_res = lib20.run_causal_highorder_and_tree_wf(
        p20, atomic_cols=atomic_cols, extra_static_cols=feat_union,
        wf_start_date="2023-01-03", min_warmup_trades=80, deltas=(8, 12, 15), enable_4way=False,
    )
    c50 = p20["v20_cold50"].to_numpy(float)
    d_cb15 = dm_cb[("v20_cold50", 15)]
    d_mn15 = dm_mn[("v20_cold50", 15)]
    d_3w12 = ho_res["rule_deltas"][("Rule3Way", 12)]

    scores_20cm = {
        "cold50": c50,
        "cleanb_c50_d15": c50 + d_cb15,
        "blend_c50_half": c50 + np.round(0.5 * d_cb15 + 0.5 * d_mn15),
        "blend_c50_noround": c50 + 0.5 * d_cb15 + 0.5 * d_mn15,
        "stack_c50_avg": c50 + np.round((d_cb15 + d_mn15 + d_3w12) / 3.0),
        "stack_c50_noround": c50 + (d_cb15 + d_mn15 + d_3w12) / 3.0,
    }
    # Map 20cm candidate scores cleanly onto pools_ext["20cm"]
    p20_key_idx = {(str(r.buy_date)[:10], str(r.code).zfill(6)): idx for idx, r in enumerate(p20.itertuples(index=False))}
    df20_pool = pools_ext["20cm"]
    sc20_aligned = {}
    for kname, svec in scores_20cm.items():
        arr = np.empty(len(df20_pool), dtype=float)
        for j, r in enumerate(df20_pool.itertuples(index=False)):
            idx_p = p20_key_idx.get((str(r.buy_date)[:10], str(r.code).zfill(6)))
            if idx_p is None:
                arr[j] = float(r.orig_score)
            elif str(r.buy_date)[:10] < "2023-01-03" and kname != "cold50":
                # During WF warmup (<2023-01-03), run clean V20.0 >=82 rule
                arr[j] = float(r.orig_score) if float(r.orig_score) >= 82.0 else -999.0
            else:
                arr[j] = float(svec[idx_p])
        sc20_aligned[kname] = arr

    # Assert exact parity vs RD036 standalone Blend (135t / 146.3644x) and Stack (129t / 125.9588x)
    for kname, exp_n, exp_nav in [("blend_c50_half", 135, 146.3644), ("stack_c50_avg", 129, 125.9588), ("cold50", 120, 50.9555)]:
        _, sl_chk = cm.sim_strategy("20cm", df20_pool, sc20_aligned[kname], thr=80.0, wf_only=True)
        nav_chk = float(np.prod(1.0 + sl_chk["net_ret_030"].to_numpy(float)))
        assert len(sl_chk) == exp_n and abs(nav_chk - exp_nav) < 0.05, f"20cm {kname} parity fail: {len(sl_chk)}/{nav_chk}"
    print("  [20cm Parity OK] Blend=135t/146.36x, Stack=129t/125.96x, Cold50=120t/50.96x")
    del p20, dm_cb, dm_mn, ho_res
    gc.collect()

    # [4/5] Reconstruct all causal & static controls for Other 5 strategies
    print("[4/5] Reconstructing Other 5 strategy causal candidates + static LOO controls ...")
    other5_variants = {}

    # 3to4
    df34 = pools_ext["3to4"]
    orig34 = df34["orig_score"].to_numpy(float)
    bp34 = list(dict.fromkeys(bundle["base_dyn_cols"] + bundle["atom_info"]["3to4"]["cols"]))
    r4_34 = m34.run_wf_3way_4way_and_trees(df34, bp34, min_leaf=20, min_days=8, order=4, run_trees=False)
    dp34, _ = m12.run_causal_pairwise_multi(df34, bundle["ix_cols"], bp34, cold_cut=45.0, regime_mode="cold_only", max_deltas=(15,), min_cell=20)
    # Also W2A2 M4_MineBL15
    with open(f"{RD035}/wave3_final/w3_1_v20_assembly/_cache/w2a2_3to4_pry.pkl", "rb") as f:
        w2a2_c = pickle.load(f)
    blk34_w2a2 = np.array([w2a2_c["blk_3to4_m4_bl15"].get((str(r.buy_date)[:10], str(r.code).zfill(6)), False) for r in df34.itertuples(index=False)], dtype=bool)
    # Static LOO s34_af_20 (post-hoc reference ONLY)
    j34_20 = bundle["atom_info"]["3to4"]["cols"].index("s34_af_20")
    sc34_st = np.where(df34["buy_date"] >= "2023-01-03", orig34 - bundle["atom_info"]["3to4"]["contrib_mat"][:, j34_20], orig34)
    other5_variants["3to4"] = {
        "m4_4way_bl15": {"score": orig34, "mask": np.where(df34["buy_date"] >= "2023-01-03", ~r4_34["mine_bl"][15], True)},
        "m2_pair_cold45_d15": {"score": orig34 + np.where(df34["buy_date"] >= "2023-01-03", dp34[15], 0.0), "mask": None},
        "w2a2_mine_bl15": {"score": orig34, "mask": np.where(df34["buy_date"] >= "2023-01-03", ~blk34_w2a2, True)},
        "static_loo_af20": {"score": sc34_st, "mask": None},
    }

    # 2to3
    df23 = pools_ext["2to3"]
    orig23 = df23["orig_score"].to_numpy(float)
    bp23 = list(dict.fromkeys(bundle["base_dyn_cols"] + bundle["atom_info"]["2to3"]["cols"]))
    dp23, _ = m12.run_causal_pairwise_multi(df23, bundle["ix_cols"], bp23, cold_cut=45.0, regime_mode="cold_only", max_deltas=(15,), min_cell=cm.MIN_LEAF_MAP["2to3"])
    j23_17 = bundle["atom_info"]["2to3"]["cols"].index("s23_af_17")
    sc23_st = np.where((df23["buy_date"] >= "2023-01-03") & (df23["mkt10_zt_est_t1"] < 50.0), orig23 - bundle["atom_info"]["2to3"]["contrib_mat"][:, j23_17], orig23)
    other5_variants["2to3"] = {
        "m2_pair_cold45_d15": {"score": orig23 + np.where(df23["buy_date"] >= "2023-01-03", dp23[15], 0.0), "mask": None},
        "static_cold_loo_af17": {"score": sc23_st, "mask": None},
    }

    # high
    dfhi = pools_ext["high"]
    orighi = dfhi["orig_score"].to_numpy(float)
    sc_hi_ca = m12.run_causal_cold_atom_disable(dfhi, bundle["atom_info"]["high"]["cols"], bundle["atom_info"]["high"]["contrib_mat"], cold_cut=40.0, t_cut=0.0, bonus_only=True)
    other5_variants["high"] = {
        "m1_causal_cold_drop40_t0": {"score": np.where(dfhi["buy_date"] >= "2023-01-03", sc_hi_ca, orighi), "mask": None},
    }

    # pry
    dfpr = pools_ext["pry"]
    origpr = dfpr["orig_score"].to_numpy(float)
    bp_pr = list(dict.fromkeys(bundle["base_dyn_cols"] + bundle["atom_info"]["pry"]["cols"]))
    dp_pr, _ = m12.run_causal_pairwise_multi(dfpr, bundle["ix_cols"], bp_pr, cold_cut=45.0, regime_mode="cold_only", max_deltas=(15,), min_cell=cm.MIN_LEAF_MAP["pry"], decluster_days=True)
    pry_w2_map = w2a2_c["pry_m1_tm05"]
    sc_pr_w2 = np.array([
        pry_w2_map.get((str(r.buy_date)[:10], str(r.code).zfill(6)), (float(r.orig_score), False))[0]
        if (str(r.buy_date)[:10] >= "2023-01-03" and pry_w2_map.get((str(r.buy_date)[:10], str(r.code).zfill(6)), (np.nan, False))[1] and np.isfinite(pry_w2_map.get((str(r.buy_date)[:10], str(r.code).zfill(6)), (np.nan, False))[0]))
        else float(r.orig_score)
        for r in dfpr.itertuples(index=False)
    ], dtype=float)
    other5_variants["pry"] = {
        "m1_skip_cold50": {"score": origpr, "mask": np.where(dfpr["buy_date"] >= "2023-01-03", dfpr["mkt10_zt_est_t1"].to_numpy(float) >= 50.0, True)},
        "m2_pair_cold45_d15": {"score": origpr + np.where(dfpr["buy_date"] >= "2023-01-03", dp_pr[15], 0.0), "mask": None},
        "w2a2_drop_neg_tm05": {"score": sc_pr_w2, "mask": None},
    }

    # Verify standalone WF parities for all other5 causal candidates
    for st, vdict in other5_variants.items():
        for vn, cfg in vdict.items():
            _, sl_v = cm.sim_strategy(st, pools_ext[st], cfg["score"], mask=cfg["mask"], wf_only=True)
            nav_v = float(np.prod(1.0 + sl_v["net_ret_030"].to_numpy(float)))
            print(f"  Other5 parity [{st}::{vn}]: n={len(sl_v)} WF_nav={nav_v:.4f}x")

    # [5/5] Build b0/tp1 state lookup for W2A5 weak-red 09:25 swaps + save master cache
    print("[5/5] Building W2A5 b0/tp1 state lookup & saving rd038_master_cache.pkl ...")
    b0_lu = _build_b0_tp1_state_lookup(pools_ext, cal_5y)

    # Also build bar_lu for exact MTM recomputation when a swap happens (only for 1to2/2to3/3to4 codes)
    # Actually we can compute exact MTM ratio directly from precomputed mtm_5y_030? No, exiting at tp1_dt 09:25 changes tp1_dt multiplier!
    # So save daily close/adjf for 1to2/2to3/3to4 codes on [buy_date .. tp1_dt]
    swap_codes = {str(r.code).zfill(6) for st in ("1to2", "2to3", "3to4") for r in pools_ext[st].itertuples(index=False)}
    # We already have bar_lu in w2a5 or can load light close/adjf map for swap_codes
    import pyarrow.dataset as ds
    tks_sw = sorted({f"{c}.SH" for c in swap_codes} | {f"{c}.SZ" for c in swap_codes})
    flt_sw = (ds.field("date") >= pd.Timestamp("2021-11-01")) & (ds.field("date") <= pd.Timestamp("2026-11-25")) & ds.field("ticker").isin(tks_sw)
    swap_close_lu = {}
    for ppath in (f"{SIM}/data/cn_hk_price_db/a_daily.parquet", f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"):
        for b in ds.dataset(ppath).scanner(columns=["date", "ticker", "close", "adj_close"], filter=flt_sw).to_batches():
            dfb = b.to_pandas()
            if dfb.empty:
                continue
            dfb["c6"] = dfb["ticker"].astype(str).str[:6]
            dfb["dt"] = pd.to_datetime(dfb["date"]).dt.strftime("%Y-%m-%d")
            for r in dfb.itertuples(index=False):
                k = (r.c6, r.dt)
                if k not in swap_close_lu and r.close > 0 and r.adj_close > 0:
                    swap_close_lu[k] = float(r.adj_close)

    # Load daily benchmark (CSI300 & All-A EW) across full 5Y
    bench_5y = v20_ctx["calendar_5y"].sort_values("trade_date").reset_index(drop=True)
    assert bench_5y["trade_date"].tolist() == cal_5y

    # Also build unified 0.30% master candidate pool for 1000x permutation tests (both 5Y & WF)
    master_cand = pd.read_parquet(f"{WAVE1}/pools_6strat_master_newfactors_pit.parquet", columns=["strategy", "buy_date", "code", "net_ret", "sim_ok"])
    master_cand["buy_date"] = master_cand["buy_date"].astype(str).str[:10]
    master_cand["code"] = master_cand["code"].astype(str).str.zfill(6)
    master_cand = master_cand[master_cand["buy_date"].between("2021-11-16", "2026-11-16") & (master_cand["sim_ok"] == 1) & master_cand["net_ret"].notna()].copy()
    master_cand["net_ret"] = np.where(
        master_cand["strategy"] == "20cm",
        master_cand["net_ret"].astype(float),
        cm.convert_fee(master_cand["net_ret"].astype(float), 0.0030),
    )
    master_cand["can_buy_hygiene"] = True

    master_cache = {
        "cal_5y": cal_5y,
        "cal_wf": cal_wf,
        "bench_5y": bench_5y,
        "pools_ext": pools_ext,
        "ut_full_raw": ut_full_raw,
        "sc20_aligned": sc20_aligned,
        "other5_variants": other5_variants,
        "b0_lu": b0_lu,
        "swap_close_lu": swap_close_lu,
        "master_cand_perm": master_cand[["buy_date", "code", "net_ret", "can_buy_hygiene"]].copy(),
    }
    out_pkl = f"{CACHE_DIR}/rd038_master_cache.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump(master_cache, f)
    print(f"[STEP 1 DONE in {time.time()-t0:.1f}s | RSS={rss_mb()} MB] Saved {out_pkl}")


if __name__ == "__main__":
    main()
