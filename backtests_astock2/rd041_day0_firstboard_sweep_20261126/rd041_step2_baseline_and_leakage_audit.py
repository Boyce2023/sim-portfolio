#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD041 Step 2: Raw Baseline Distribution, Broken-Board Denominator Proof,
Track A (Pre-Open/Intraday News & Day-0 Theme) & Track B (09:25 Weak-to-Strong & Micro-Tape Trap) Diagnostic.

Zero yfinance (D12). Peak RSS < 1.5 GB.
"""
import os
for _env_k in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_env_k] = "1"

import json
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd041_day0_firstboard_sweep_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"
PQ_PATH = f"{CACHE_DIR}/rd041_fb_master_pit.parquet"


def eval_pool_stats(sub: pd.DataFrame, exit_col: str = "E1_T1Open_gross_ret", fee_rt: float = 0.0030, p_fill_zt: float = 1.0) -> dict:
    """Compute pool stats with optional adverse selection reweighting (p_fill_zt on is_zt==1 vs 1.0 on broken)."""
    s = sub[sub[exit_col].notna()].copy()
    if s.empty:
        return {"n": 0}
    gr = s[exit_col].to_numpy(float)
    nr = (1.0 + gr) * (1.0 - fee_rt) - 1.0
    zt = s["is_zt"].to_numpy(int)
    w = np.where(zt == 1, p_fill_zt, 1.0)
    w_sum = float(w.sum())
    if w_sum <= 0:
        return {"n": 0}
    mean_pct = float(np.sum(w * nr) / w_sum * 100.0)
    wr_pct = float(np.sum(w * (nr > 0)) / w_sum * 100.0)
    brk_pct = float(np.sum(w * (zt == 0)) / w_sum * 100.0)

    # Simple equal-weight daily portfolio compounding (reweighted by fill prob)
    s["_nr"] = nr
    s["_w"] = w
    s["_wnr"] = w * nr
    by_d = s.groupby("buy_date", as_index=False).agg(wnr=("_wnr", "sum"), w=("_w", "sum"))
    by_d = by_d[by_d["w"] > 0].sort_values("buy_date")
    d_ret = (by_d["wnr"] / by_d["w"]).to_numpy(float)
    ew_nav = float(np.prod(1.0 + np.clip(d_ret, -0.95, 5.0))) if len(d_ret) else 1.0

    # Also 2025-2026 subset
    s25 = s[s["buy_date"] >= "2025-01-01"]
    if not s25.empty:
        w25 = s25["_w"].to_numpy(float)
        nr25 = s25["_nr"].to_numpy(float)
        mean25 = float(np.sum(w25 * nr25) / np.sum(w25) * 100.0)
        wr25 = float(np.sum(w25 * (nr25 > 0)) / np.sum(w25) * 100.0)
    else:
        mean25, wr25 = 0.0, 0.0

    return {
        "n": int(len(s)),
        "n_days": int(len(by_d)),
        "brk_pct": round(brk_pct, 2),
        "wr_pct": round(wr_pct, 2),
        "mean_pct": round(mean_pct, 3),
        "ew_daily_nav": round(ew_nav, 4),
        "n_2526": int(len(s25)),
        "wr_2526_pct": round(wr25, 2),
        "mean_2526_pct": round(mean25, 3),
    }


def main():
    t0 = time.time()
    df = pd.read_parquet(PQ_PATH)
    print(f"[Step2] Loaded {len(df)} FB touches | RSS={round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e6,1)} MB")

    exits = ["E1_T1Open_gross_ret", "E2_T1Close_gross_ret", "E3_T2Close_gross_ret", "E4_StreakHold_gross_ret"]
    ex_names = ["T1_Open", "T1_Close", "T2_Close", "StreakHold"]

    # 1. Full Raw Baseline (10cm vs 20cm vs Combined) across Exits, Friction & Adverse Selection
    base_summary = {}
    print("\n=== 1. FULL RAW POOL BASELINE (100% Broken Denominator Included) ===")
    for grp_lbl, mask_g in [("10cm", df["is_20cm"] == 0), ("20cm", df["is_20cm"] == 1), ("All_10_20", np.ones(len(df), dtype=bool))]:
        sub = df[mask_g]
        base_summary[grp_lbl] = {}
        print(f"\n--- {grp_lbl} (N={len(sub)}, broken={(sub['is_zt']==0).mean()*100:.2f}%) ---")
        for ex_col, ex_nm in zip(exits, ex_names):
            r_30 = eval_pool_stats(sub, ex_col, fee_rt=0.0030, p_fill_zt=1.0)
            r_80 = eval_pool_stats(sub, ex_col, fee_rt=0.0080, p_fill_zt=1.0)
            r_adv70 = eval_pool_stats(sub, ex_col, fee_rt=0.0030, p_fill_zt=0.70)
            r_adv50 = eval_pool_stats(sub, ex_col, fee_rt=0.0030, p_fill_zt=0.50)
            r_adv50_80 = eval_pool_stats(sub, ex_col, fee_rt=0.0080, p_fill_zt=0.50)
            base_summary[grp_lbl][ex_nm] = {
                "fee30_fill100": r_30, "fee80_fill100": r_80,
                "fee30_adv70": r_adv70, "fee30_adv50": r_adv50, "fee80_adv50": r_adv50_80,
            }
            print(f"  {ex_nm:10s} | 30bp/100%: WR={r_30['wr_pct']:4.1f}% mean={r_30['mean_pct']:+5.2f}% ewNAV={r_30['ew_daily_nav']:6.3f} (25-26:{r_30['mean_2526_pct']:+5.2f}%)"
                  f" | 80bp={r_80['mean_pct']:+5.2f}% | Adv70={r_adv70['mean_pct']:+5.2f}% | Adv50={r_adv50['mean_pct']:+5.2f}% | Adv50+80bp={r_adv50_80['mean_pct']:+5.2f}%")

    # 2. Track A Raw Sub-pools (Strict flash_news window <= 2026-11-11 where flash_news is complete)
    print("\n=== 2. TRACK A: PRE-OPEN & INTRADAY NEWS / DAY-0 THEME CATALYSTS ===")
    df_fn = df[(df["buy_date"] >= "2021-01-19") & (df["buy_date"] <= "2026-11-11")].copy()
    track_a_defs = [
        ("A1a_FN_PreAny_10cm", (df_fn["is_20cm"] == 0) & (df_fn["fn_pre_any"] == 1)),
        ("A1b_FN_PrePos_10cm", (df_fn["is_20cm"] == 0) & (df_fn["fn_pre_pos"] == 1)),
        ("A1c_FN_PreHard_10cm", (df_fn["is_20cm"] == 0) & (df_fn["fn_pre_hard"] == 1)),
        ("A1d_FN_PreCold_10cm", (df_fn["is_20cm"] == 0) & (df_fn["fn_pre_cold"] == 1)),
        ("A1e_AnyPreCat_All", df_fn["any_pre_cat"] == 1),
        ("A1f_FN_PrePos_20cm", (df_fn["is_20cm"] == 1) & (df_fn["fn_pre_pos"] == 1)),
        ("A2a_ThemePreNews_All", df_fn["theme_news_pre_cnt"] >= 1),
        ("A2b_ThemeColdDay0_All", (df_fn["theme_news_pre_cnt"] >= 1) & (df_fn["kpl_theme_cold_t1"] == 1)),
        ("A2c_ThemeDay0_TopGap2", (df_fn["is_day0_theme_ignite"] == 1) & ((df_fn["kpl_0925_rank_gap"] <= 2) | (df_fn["ind_0925_rank_gap"] <= 2))),
        ("A2d_Ind0925_Ignite3_Top1", (df_fn["ind_0925_gap3_cnt"] >= 3) & (df_fn["ind_0925_rank_gap"] == 1) & (df_fn["csrc_ind_ex5_t1"].fillna(0) < 1.0)),
        ("A3_IntraEarly_0930_1000", df_fn["fn_intra_early"] == 1),
        ("A4_IntraAll_0930_1455", df_fn["fn_intra_all"] == 1),
    ]
    track_a_res = {}
    for nm, mk in track_a_defs:
        sub = df_fn[mk]
        track_a_res[nm] = {}
        print(f"\n  [{nm}] N={len(sub)}, brk={(sub['is_zt']==0).mean()*100 if len(sub) else 0:.1f}%")
        for ex_col, ex_nm in zip(exits, ex_names):
            r30 = eval_pool_stats(sub, ex_col, 0.0030, 1.0)
            ra50 = eval_pool_stats(sub, ex_col, 0.0030, 0.50)
            track_a_res[nm][ex_nm] = {"fee30_fill100": r30, "fee30_adv50": ra50}
            print(f"    {ex_nm:10s}: 30bp={r30['mean_pct']:+5.2f}% (WR={r30['wr_pct']:4.1f}%, ewNAV={r30['ew_daily_nav']:6.3f}, 25-26={r30['mean_2526_pct']:+5.2f}%) | Adv50={ra50['mean_pct']:+5.2f}%")

    # 3. Track B Raw Sub-pools (100% Broken Denominator) + Micro-Tape Survivorship Trap Audit
    print("\n=== 3. TRACK B: CAUSAL 09:25 SUB-POOLS (100% BROKEN DENOM) ===")
    track_b_defs = [
        ("B1a_10cm_Gap0_3", (df["is_20cm"] == 0) & df["open_pct"].between(0.0, 3.0)),
        ("B1b_10cm_Gap3_6", (df["is_20cm"] == 0) & df["open_pct"].between(3.0, 6.0)),
        ("B1c_10cm_GapGe6", (df["is_20cm"] == 0) & (df["open_pct"] >= 6.0)),
        ("B1d_10cm_GreenOpen", (df["is_20cm"] == 0) & (df["open_pct"] < 0.0)),
        ("B2a_10cm_W2S_PrevBrk", (df["is_20cm"] == 0) & (df["is_weak_to_strong_brk"] == 1)),
        ("B2b_10cm_W2S_PrevNeg", (df["is_20cm"] == 0) & (df["is_weak_to_strong_neg"] == 1)),
        ("B3_10cm_LowPos_Small", (df["is_20cm"] == 0) & (df["mcap_yi_t1"] <= 40.0) & (df["pos_250d_t1"] <= 0.35) & (df["open_pct"] >= 1.0)),
        ("B4_10cm_IceRebound", (df["is_20cm"] == 0) & (df["L1_sent_phase_t1"] <= 2) & (df["open_pct"] >= 2.0)),
        ("B5_20cm_GapGe3", (df["is_20cm"] == 1) & (df["open_pct"] >= 3.0)),
        ("B6_20cm_LowPos_Small", (df["is_20cm"] == 1) & (df["mcap_yi_t1"] <= 50.0) & (df["pos_250d_t1"] <= 0.35)),
    ]
    track_b_res = {}
    for nm, mk in track_b_defs:
        sub = df[mk]
        track_b_res[nm] = {}
        print(f"\n  [{nm}] N={len(sub)}, brk={(sub['is_zt']==0).mean()*100 if len(sub) else 0:.1f}%")
        for ex_col, ex_nm in zip(exits, ex_names):
            r30 = eval_pool_stats(sub, ex_col, 0.0030, 1.0)
            ra50 = eval_pool_stats(sub, ex_col, 0.0030, 0.50)
            track_b_res[nm][ex_nm] = {"fee30_fill100": r30, "fee30_adv50": ra50}
            print(f"    {ex_nm:10s}: 30bp={r30['mean_pct']:+5.2f}% (WR={r30['wr_pct']:4.1f}%, ewNAV={r30['ew_daily_nav']:6.3f}, 25-26={r30['mean_2526_pct']:+5.2f}%) | Adv50={ra50['mean_pct']:+5.2f}%")

    # 4. Micro-Tape Seal-Time Trap Audit (Exposing is_zt==1 Only Illusion vs Parametric Imputation + Adverse Selection)
    print("\n=== 4. MICRO-TAPE EARLY-SEAL TRAP AUDIT (FAKE BIASED vs IMPUTED BROKEN + ADVERSE SELECTION) ===")
    trap_audit = {}
    for cm20, cm_lbl in [(0, "10cm"), (1, "20cm")]:
        sub_c = df[df["is_20cm"] == cm20]
        brk_pool = sub_c[sub_c["is_zt"] == 0]
        brk_t1o = float(brk_pool["E1_T1Open_gross_ret"].mean())
        brk_t1c = float(brk_pool["E2_T1Close_gross_ret"].mean())
        brk_stk = float(brk_pool["E4_StreakHold_gross_ret"].mean())
        trap_audit[cm_lbl] = {"broken_pool_n": int(len(brk_pool)), "broken_gross_mean": {"T1O": round(brk_t1o*100,2), "T1C": round(brk_t1c*100,2), "Stk": round(brk_stk*100,2)}}

        for w_lbl, w_mask in [
            ("Seal<=0945", (sub_c["is_zt"] == 1) & (sub_c["audit_only_seal_hhmm"] > 0) & (sub_c["audit_only_seal_hhmm"] <= 945)),
            ("Seal<=1000", (sub_c["is_zt"] == 1) & (sub_c["audit_only_seal_hhmm"] > 0) & (sub_c["audit_only_seal_hhmm"] <= 1000)),
            ("Seal<=1000_ZeroOpen", (sub_c["is_zt"] == 1) & (sub_c["audit_only_seal_hhmm"] > 0) & (sub_c["audit_only_seal_hhmm"] <= 1000) & (sub_c["audit_only_open_cnt"] == 0)),
        ]:
            s_z = sub_c[w_mask]
            fake_r = eval_pool_stats(s_z, "E1_T1Open_gross_ret", 0.0030, 1.0)
            fake_stk = eval_pool_stats(s_z, "E4_StreakHold_gross_ret", 0.0030, 1.0)
            seal_t1o = float(s_z["E1_T1Open_gross_ret"].mean())
            seal_stk = float(s_z["E4_StreakHold_gross_ret"].mean())

            # Parametric imputation across broken rates (20%, 32.5%, 40%) x fill probs (100%, 70%, 50%) x fee (30bps, 80bps)
            matrix = {}
            for brk_rate in (0.20, 0.325, 0.40):
                for p_fill in (1.00, 0.70, 0.50):
                    eff_w_seal = (1.0 - brk_rate) * p_fill
                    eff_w_brk = brk_rate * 1.0
                    p_seal_real = eff_w_seal / (eff_w_seal + eff_w_brk)
                    p_brk_real = 1.0 - p_seal_real
                    for ex_nm, s_m, b_m in [("T1O", seal_t1o, brk_t1o), ("Stk", seal_stk, brk_stk)]:
                        gr_imp = p_seal_real * s_m + p_brk_real * b_m
                        net30 = (1.0 + gr_imp) * (1.0 - 0.0030) - 1.0
                        net80 = (1.0 + gr_imp) * (1.0 - 0.0080) - 1.0
                        matrix[f"{ex_nm}_brk{int(brk_rate*100)}_fill{int(p_fill*100)}"] = {
                            "real_brk_share_pct": round(p_brk_real * 100.0, 1),
                            "net30_pct": round(net30 * 100.0, 2),
                            "net80_pct": round(net80 * 100.0, 2),
                        }
            trap_audit[cm_lbl][w_lbl] = {"fake_sealed_only_T1O": fake_r, "fake_sealed_only_Stk": fake_stk, "imputed_stress": matrix}
            print(f"  {cm_lbl} {w_lbl:20s} | FAKE(0% brk): N={len(s_z):5d} T1O={fake_r['mean_pct']:+5.2f}% Stk={fake_stk['mean_pct']:+5.2f}%"
                  f" | Brk32.5%+Fill70%(30bp): T1O={matrix['T1O_brk32_fill70']['net30_pct']:+5.2f}% Stk={matrix['Stk_brk32_fill70']['net30_pct']:+5.2f}%"
                  f" | Brk32.5%+Fill50%(30bp): T1O={matrix['T1O_brk32_fill50']['net30_pct']:+5.2f}% Stk={matrix['Stk_brk32_fill50']['net30_pct']:+5.2f}%")

    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "base_summary": base_summary,
        "track_a_raw": track_a_res,
        "track_b_raw": track_b_res,
        "micro_tape_trap_audit": trap_audit,
    }
    with open(f"{CACHE_DIR}/rd041_step2_diag.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[Step2 DONE] Saved rd041_step2_diag.json in {out['elapsed_sec']}s")


if __name__ == "__main__":
    main()
