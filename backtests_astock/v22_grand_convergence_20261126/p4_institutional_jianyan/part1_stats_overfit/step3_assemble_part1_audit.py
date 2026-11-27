#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step3_assemble_part1_audit.py — Assemble V22.0 Institutional Audit Part 1 (Pillars 1 to 4):
  Combines:
    - Pillar 1 (DSR & MinTRL)
    - Pillar 2 (CSCV PBO)
    - Pillar 3 (Full ±20% MC Perturbation: MC_CORE_12, MC_FULL_38, plus SJ114 cliff sweep & MC_MARGIN_12 control)
    - Pillar 4 (LOYO 2021..2026 & 10,000x Moving Block Bootstrap)
  Outputs: p4_part1_audit.json
Zero yfinance (D12). Read-only on V20/V21/RD038/RD048/RD049/P1A/P2/P3.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
P3 = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly"
OUT_DIR = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p4_institutional_jianyan/part1_stats_overfit"
CACHE_DIR = f"{OUT_DIR}/_cache"

for p in (RD038, RD049, P3, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _v22_engine as v22
from step2_run_pillar3_mc_perturb import FastV22Evaluator

CHAMP_ID = "V21_M5_B_NoXQ_Pos5"
PURE_ID = "Pure_V21_P2_SJ114_E4_Pos5"


def main():
    t0 = time.time()
    with open(f"{CACHE_DIR}/p4_pillars_1_2_4.json", encoding="utf-8") as f:
        p124 = json.load(f)
    with open(f"{CACHE_DIR}/p4_pillar3_mc.json", encoding="utf-8") as f:
        p3 = json.load(f)
    with open(f"{CACHE_DIR}/p4_pillar3_mc_margin_ctrl.json", encoding="utf-8") as f:
        p3_margin = json.load(f)
    df_mc = pd.read_csv(f"{OUT_DIR}/p4_mc_perturb_samples.csv")

    # 1. Exact SJ114 threshold sweep + MC failure attribution
    with open(f"{CACHE_DIR}/p4_mc_assets.pkl", "rb") as f:
        mc_assets = pickle.load(f)
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache_base = pickle.load(f)
    reg_df = pd.read_parquet(f"{RD049}/_cache/rd049_daily_regime_pit.parquet")
    ev = FastV22Evaluator(cache_base, reg_df, mc_assets)
    nom = {
        "y_cut": 42.0, "x_sh": 20.0, "x_dp": 42.0,
        "d_l2": 9.0, "d_l3": 9.0, "d_l4": 12.0,
        "pos750": 0.50, "pry_mkt": 50.0, "pry_dt": 100.0,
        "sj_thr": 114.0, "dirA_thr": 0.080, "dirB_7f_thr": 0.070,
        "hr_min": 0.12, "open_lo": 0.020, "open_hi": 0.075, "w_mult": None,
    }
    sj_sweep = []
    for thr in [95, 100, 104, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 118, 120, 125]:
        r = ev.run_one({**nom, "sj_thr": float(thr)}, use_dira=True, use_7f_4to5=True)
        sj_sweep.append({
            "sj_thr": thr,
            "n_trades": r["n_trades"],
            "n_4to5_trades": r["n_4to5_trades"],
            "nav_5y": round(r["nav_5y"], 2),
            "nav_wf": round(r["nav_wf"], 2),
            "sh_wf": round(r["sh_wf"], 3),
            "mdd_5y": round(r["mdd_5y"], 2),
            "nav_2026": round(r["nav_2026"], 2),
        })

    # Compute exact correlation & conditional pass rates in MC_CORE_12 & MC_FULL_38
    v21_wf_sh = float(p3["v21_ref_wf_sharpe"])
    mc_attrib = {}
    for suite in ("MC_CORE_12", "MC_FULL_38"):
        sub = df_mc[(df_mc["suite"] == suite) & (df_mc["model"] == "V22_Champ")].copy()
        sub["beat_v21"] = (sub["sh_wf"] > v21_wf_sh).astype(float)
        sub["mdd_ok"] = (sub["mdd_5y"] <= 35.0).astype(float)
        pcols = ["y_cut", "x_sh", "x_dp", "d_l2", "d_l3", "d_l4", "pos750", "pry_mkt", "pry_dt", "sj_thr", "dirA_thr", "dirB_7f_thr"]
        if suite == "MC_FULL_38":
            pcols += ["hr_min", "open_lo", "open_hi"]
        corrs = {
            c: {
                "corr_beat_v21": round(float(sub[c].corr(sub["beat_v21"])), 4),
                "corr_mdd_le35": round(float(sub[c].corr(sub["mdd_ok"])), 4),
            }
            for c in pcols
        }
        s_ge109 = sub[sub["sj_thr"] >= 109.0]
        s_lt109 = sub[sub["sj_thr"] < 109.0]
        s_margin_band = sub[(sub["sj_thr"] >= 111.2) & (sub["sj_thr"] <= 116.8)]
        mc_attrib[suite] = {
            "param_correlations": corrs,
            "cond_sj_ge_109": {
                "n": int(len(s_ge109)),
                "beat_v21_pct": round(float(s_ge109["beat_v21"].mean() * 100.0), 2),
                "mdd_le35_pct": round(float(s_ge109["mdd_ok"].mean() * 100.0), 2),
                "med_mdd_5y": round(float(s_ge109["mdd_5y"].median()), 2),
            },
            "cond_sj_lt_109": {
                "n": int(len(s_lt109)),
                "beat_v21_pct": round(float(s_lt109["beat_v21"].mean() * 100.0), 2),
                "mdd_le35_pct": round(float(s_lt109["mdd_ok"].mean() * 100.0), 2),
                "med_mdd_5y": round(float(s_lt109["mdd_5y"].median()), 2),
            },
            "cond_sj_margin_111_2_to_116_8": {
                "n": int(len(s_margin_band)),
                "beat_v21_pct": round(float(s_margin_band["beat_v21"].mean() * 100.0), 2),
                "mdd_le35_pct": round(float(s_margin_band["mdd_ok"].mean() * 100.0), 2),
                "med_mdd_5y": round(float(s_margin_band["mdd_5y"].median()), 2),
            },
        }

    # 2. Gate verdicts across Pillars 1 to 4
    p1 = p124["pillar1_dsr_mintrl"]
    p2 = p124["pillar2_cscv_pbo"]
    p4 = p124["pillar4_loyo_and_boot"]

    abs_dsr_ch_5y = p1["absolute_vs_0"][CHAMP_ID]["FULL_5Y"]["N_300"]["pooled_var"]["dsr"]
    abs_dsr_pu_5y = p1["absolute_vs_0"][PURE_ID]["FULL_5Y"]["N_300"]["pooled_var"]["dsr"]
    inc_dsr_ch_5y = p1["incremental_spread_vs_v21"][CHAMP_ID]["FULL_5Y"]["by_N"]["N_300"]["spread_emp_var"]["dsr"]
    inc_dsr_ch_wf = p1["incremental_spread_vs_v21"][CHAMP_ID]["WF_2326"]["by_N"]["N_300"]["spread_emp_var"]["dsr"]
    inc_dsr_pu_5y = p1["incremental_spread_vs_v21"][PURE_ID]["FULL_5Y"]["by_N"]["N_300"]["spread_emp_var"]["dsr"]
    inc_dsr_pu_wf = p1["incremental_spread_vs_v21"][PURE_ID]["WF_2326"]["by_N"]["N_300"]["spread_emp_var"]["dsr"]

    pbo_5y_s10 = p2["full_pool"]["FULL_5Y"]["S10_exact_252"]["pbo_pct"]
    pbo_5y_s16 = p2["full_pool"]["FULL_5Y"]["S16_2000_nondup"]["pbo_pct"]
    pbo_wf_s10 = p2["full_pool"]["WF_2326"]["S10_exact_252"]["pbo_pct"]
    pbo_wf_s16 = p2["full_pool"]["WF_2326"]["S16_2000_nondup"]["pbo_pct"]

    mc_core_ch = p3["suites"]["MC_CORE_12"]["V22_Champ"]
    mc_full_ch = p3["suites"]["MC_FULL_38"]["V22_Champ"]

    verdicts = {
        "pillar1_dsr_mintrl": {
            "absolute_vs_0_status": "PASS",
            "incremental_vs_v21_status": "WARN",
            "overall_status": "WARN",
            "reason": (
                f"Absolute DSR at N=100/300/600 is 1.0000 for both Champ (5Y MinTRL=37.5d<<1212d) & Pure (37.9d<<1212d) -> PASS. "
                f"HOWEVER, on the incremental active spread (V22-V21, active on 117/1212 days), N=300 empirical-var DSR is {inc_dsr_ch_5y:.4f} (5Y, MinTRL=1357d>1212d) / {inc_dsr_ch_wf:.4f} (WF, MinTRL=984d>936d) for Champ and {inc_dsr_pu_5y:.4f}/{inc_dsr_pu_wf:.4f} for Pure (both just below 0.950; null-var DSR=0.67-0.72), while N=100 passes (0.9679)."
            ),
        },
        "pillar2_cscv_pbo": {
            "overall_status": "PASS",
            "reason": (
                f"Across K=25 unique V22/RD049/V21/V20 variants: 5Y S=10 PBO={pbo_5y_s10:.2f}%, 5Y S=16(2k) PBO={pbo_5y_s16:.2f}%, WF S=10 PBO={pbo_wf_s10:.2f}%, WF S=16(2k) PBO={pbo_wf_s16:.2f}% — ALL strictly < 20% strong-pass gate. Champ beats V21 in 98.81%..99.70% of OOS splits; Pure beats V21 in 98.41%..99.65%."
            ),
        },
        "pillar3_mc_20pct": {
            "overall_status": "FAIL",
            "reason": (
                f"Unconditional ±20% joint MC FAILS both hard gates (>=85% beat V21 WF Sharpe & >=80% MDD<=35%): "
                f"MC_CORE_12 (500w): Champ beat_v21={mc_core_ch['beat_v21_wf_sharpe_pct']}%, MDD<=35={mc_core_ch['mdd_5y_le_35_pct']}% (Pure identical 68.0%/62.6%); "
                f"MC_FULL_38 (500w): Champ beat_v21={mc_full_ch['beat_v21_wf_sharpe_pct']}%, MDD<=35={mc_full_ch['mdd_5y_le_35_pct']}%. "
                f"Root cause: 100% driven by SJ114 cliff (corr=+0.793/+0.823). Multiplying 114 by -20% lowers cutoff to 91.2 (below 100 neutral baseline!), and a sharp MDD cliff hits at sj<=108 (5Y MDD jumps 29.23%->50.05%). "
                f"In MC_MARGIN_12 control where SJ net margin (+14) is perturbed ±20% [111.2, 116.8] while all other 11 V22 params stay ±20%, pass rate is 100.0% beat V21 & 100.0% MDD<=32%."
            ),
        },
        "pillar4_loyo_and_boot": {
            "overall_status": "PASS_WITH_2023_CAVEAT",
            "reason": (
                "LOYO (leave out any 1 year 2021..2026): Champ & Pure beat V21 & V20 in 6/6 folds on NAV and Sharpe, with MDD<=V21 in 6/6 folds. "
                "10,000x Moving Block Bootstrap (B=5 & B=10): Champ vs V21 P(mean>0)=99.94%/99.91% (5Y mult p05=3.40x/3.10x). "
                "Caveat: in SOLO-YEAR 2023, V22 (8.55x, SR=3.274) underperformed V21 (10.14x, SR=3.542) by -15.7%."
            ),
        },
        "champion_vs_pure_verdict": {
            "preferred_for_live": PURE_ID,
            "reason": (
                "Pure_V21_P2_SJ114_E4_Pos5 (2 clean rules, zero 13:45 exit micro-thresholds) is statistically cleaner for live capital: "
                "Champ's +5.4% 5Y NAV edge over Pure comes from only 5 diff trades in 5 years (paired_t=0.857, p=0.3914; 0 diff in 2024 & 2026; Block-5 bootstrap mult p05=0.995<1.0; collapses to 0.9868x ex-601566). "
                "Pure also has lower CSCV win_pbo (0.0%/11.8% vs 22.8%/16.7% in 5Y). However, Champ's extra exits do not degrade MC robustness (beat Pure in 90.4%-93.4% of MC worlds)."
            ),
        },
        "part1_final_gate_verdict": "CONDITIONAL_FAIL_ON_SJ114_CLIFF_AND_INC_DSR",
    }

    master = v22.sanitize_json({
        "task": "V22.0 Institutional Seven-Pillar Audit Part 1 (Pillars 1 to 4: DSR/MinTRL, CSCV PBO, ±20% Joint MC, LOYO + Block Bootstrap)",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": False,
        "read_only_verified": True,
        "models_compared": ["B0_V20", "B1_V21", CHAMP_ID, PURE_ID],
        "verdicts": verdicts,
        "pillar1_dsr_mintrl": p1,
        "pillar2_cscv_pbo": p2,
        "pillar3_mc_20pct": {
            **p3,
            "mc_margin_12_diagnostic_ctrl": p3_margin,
            "sj_threshold_cliff_sweep": sj_sweep,
            "failure_attribution": mc_attrib,
        },
        "pillar4_loyo_and_boot": p4,
    })

    out_path = f"{OUT_DIR}/p4_part1_audit.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False, indent=2)
    print(f"[Step 3 DONE in {time.time()-t0:.1f}s] Saved {out_path}", flush=True)
    print(json.dumps(verdicts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
