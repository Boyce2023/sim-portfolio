#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V22.0 Wave 2 Step 1:
  - Strict DtDefer vs NoDefer E4 audit (standalone 4to5 & integrated into V21)
  - Full Ablation Ladder (B0, B1, M1, M2, M3, M4, M5_A, M5_B, M5_B_NoXQ) on V21 & V20
  - 30bps main + 50bps / 80bps slippage stress + 1000x trading-day & paired permutation tests
  - LOO Attribution & Dual-Scissors Counterfactual (mult_wf_ex_both > 1.0)
Zero yfinance (D12). Read-only on V20/V21/RD038/RD049.
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

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly"
CACHE_DIR = f"{OUT_DIR}/_cache"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import _v22_engine as v22


def flatten_row(nm: str, base_lbl: str, rung: str, pos_lbl: str, fee: str, ev: dict, scis_vs_base: dict | None = None, scis_marg: dict | None = None) -> dict:
    w = ev["windows"]
    row = {
        "model": nm, "base": base_lbl, "rung": rung, "pos_mode": pos_lbl, "fee": fee,
        "mtm_rel_5y": ev["mtm_rel_5y"], "mtm_rel_wf": ev["mtm_rel_wf"],
    }
    for wn in ("FULL_5Y", "IS_2123", "OOS_2426", "WF_2326", "Y2025_2026", "Y2026", "Y2026_H2"):
        mw = w[wn]
        row[f"{wn}_n"] = mw["n"]
        row[f"{wn}_wr"] = mw["wr_pct"]
        row[f"{wn}_plr"] = mw["plr"]
        row[f"{wn}_mean"] = mw["mean_pct"]
        row[f"{wn}_nav"] = mw["nav"]
        row[f"{wn}_ex3"] = mw["ex_top3_nav"]
        row[f"{wn}_ex5"] = mw["ex_top5_nav"]
        row[f"{wn}_sh"] = mw["daily_sharpe"]
        row[f"{wn}_cal"] = mw["daily_calmar"]
        row[f"{wn}_mdd"] = mw["daily_mdd_pct"]
        row[f"{wn}_dd2"] = mw["second_mdd_pct"]
        row[f"{wn}_ex_csi"] = mw["excess_csi300_pp"]
    pwf = ev.get("perm_wf", {})
    pvs = ev.get("paired_vs_ref_wf", {})
    row["perm_sd_p"] = pwf.get("same_day_p_nav", np.nan)
    row["perm_any_p"] = pwf.get("any_cand_day_p_nav", np.nan)
    row["paired_t_wf"] = pvs.get("paired_t", np.nan)
    row["paired_p_wf"] = pvs.get("paired_p_2sided", np.nan)
    row["paired_perm_p1_wf"] = pvs.get("paired_perm_p_1sided", np.nan)
    row["paired_perm_p2_wf"] = pvs.get("paired_perm_p_2sided", np.nan)
    if scis_vs_base:
        cw = scis_vs_base["cf_wf"]
        row["vs_base_mult_wf"] = cw["raw_mult"]
        row["vs_base_ex_both_wf"] = cw["mult_ex_both"]
        row["vs_base_ex_both_mod_wf"] = cw["mult_ex_both_and_mod"]
    if scis_marg:
        cw = scis_marg["cf_wf"]
        row["marg_mult_wf"] = cw["raw_mult"]
        row["marg_ex_both_wf"] = cw["mult_ex_both"]
        row["marg_ex_both_mod_wf"] = cw["mult_ex_both_and_mod"]
    return row


def main():
    t0 = time.time()
    print("[Step 1.1] Loading master caches...", flush=True)
    with open(f"{v22.RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache_base = pickle.load(f)
    reg = pd.read_parquet(f"{v22.RD049}/_cache/rd049_daily_regime_pit.parquet")
    reg_idx = v22.cm49.build_2d_states(reg, y_cut=42.0, x_sh=20.0, x_dp=42.0).set_index("trade_date")
    dirA_raw = pd.read_parquet(f"{v22.P1A}/dirA_pass_Risk7D2_Tight80_raw.parquet")
    with open(f"{CACHE_DIR}/v22_dirb_ledgers_full.pkl", "rb") as f:
        dirb_pkg = pickle.load(f)
    dirb = dirb_pkg["ledgers"]

    # Pre-build modified caches for V20 & V21
    mods = {}
    for use_p2 in (False, True):
        for use_da in (False, True):
            mods[(use_p2, use_da)] = v22.apply_v22_modifications(
                cache_base, reg_idx, use_p2=use_p2, use_dirA=use_da, dirA_raw_df=dirA_raw if use_da else None
            )

    # 1. Standalone 4to5 E4 vs DtDefer Table (030 / 050 / 080)
    print("[Step 1.2] Running standalone 4to5 E4 vs DtDefer audit...", flush=True)
    standalone_4to5 = {}
    for k, dpair in dirb.items():
        slot_df = dpair["slot"]
        standalone_4to5[k] = {}
        for fm in ("030", "050", "080"):
            fv = float(fm) / 10000.0
            sdf = slot_df.copy()
            sdf["net_ret"] = ((1.0 + sdf["net_ret_020"].to_numpy(float)) / (1.0 - 0.0020) * (1.0 - fv) - 1.0) if "net_ret_020" in sdf.columns else sdf[f"net_ret_{fm}"]
            cal_5y = cache_base["cal_5y"]
            idx_5y = {d: i for i, d in enumerate(cal_5y)}
            day_mult = np.ones(len(cal_5y), dtype=float)
            for r in sdf.itertuples(index=False):
                segs = v22.w2.mtm_json_to_segs(r.mtm_pairs_json, idx_5y, True, float(r.net_ret_030), float(r.net_ret))
                for ti, m in segs:
                    day_mult[ti] *= m
            dr_5y = day_mult - 1.0
            wf_off = idx_5y[v22.eng.WF_START]
            sim_s = {"trades_df": sdf, "dr_5y": dr_5y, "dr_wf": dr_5y[wf_off:], "mtm_diff_5y": 0.0, "mtm_diff_wf": 0.0, "waits": [], "swaps": []}
            ev_s = v22.evaluate_d15_full(f"4to5_{k}_{fm}", "STANDALONE_4TO5", sim_s, cache_base, perm_n=0)
            standalone_4to5[k][fm] = ev_s

    # 2. Define full ablation model specifications
    specs = []
    # Baselines & M1/M2/M4 on both V21 and V20
    for b_lbl, b_cfg in [("V20", v22.CFG_V20), ("V21", v22.CFG_V21)]:
        b_tag = "B0_V20" if b_lbl == "V20" else "B1_V21"
        specs.append((b_tag, b_lbl, "Base", False, False, None, "none", True))
        specs.append((f"{b_lbl}_M1_P2", b_lbl, "M1_P2", True, False, None, "none", True))
        specs.append((f"{b_lbl}_M2_DirA", b_lbl, "M2_DirA", False, True, None, "none", True))
        specs.append((f"{b_lbl}_M4_P2_DirA", b_lbl, "M4_P2_DirA", True, True, None, "none", True))

    # M3 (V21 + 4to5): all 6 variants (Fix120/SJ114/SJ114_XQLt6 x E4/7f) x (NoDefer & DtDefer) x (Pos1/Pos2/Pos5)
    for g4 in ("Fix120_E4", "Fix120_E4_DtDefer", "Fix120_7f", "Fix120_7f_DtDefer",
               "SJ114_E4", "SJ114_E4_DtDefer", "SJ114_7f", "SJ114_7f_DtDefer",
               "SJ114_XQLt6_E4", "SJ114_XQLt6_E4_DtDefer", "SJ114_XQLt6_7f", "SJ114_XQLt6_7f_DtDefer"):
        for pm in ("Pos1", "Pos2", "Pos5"):
            is_key = g4.endswith("7f_DtDefer")
            specs.append((f"V21_M3_{g4}_{pm}", "V21", f"M3_{g4}", False, False, g4, pm, is_key))
            if is_key:
                specs.append((f"V20_M3_{g4}_{pm}", "V20", f"M3_{g4}", False, False, g4, pm, True))

    # M5_A / M5_B / M5_B_NoXQ (+ NoDefer & E4_DtDefer controls) on V21 and V20
    m5_g4s = [
        ("M5_A", "Fix120_7f_DtDefer", True),
        ("M5_A_NoDefer", "Fix120_7f", False),
        ("M5_B", "SJ114_XQLt6_7f_DtDefer", True),
        ("M5_B_NoDefer", "SJ114_XQLt6_7f", False),
        ("M5_B_E4_DtDefer", "SJ114_XQLt6_E4_DtDefer", False),
        ("M5_B_NoXQ", "SJ114_7f_DtDefer", True),
        ("M5_B_NoXQ_NoDefer", "SJ114_7f", False),
    ]
    for m_lbl, g4, run_v20 in m5_g4s:
        for pm in ("Pos1", "Pos2", "Pos5"):
            specs.append((f"V21_{m_lbl}_{pm}", "V21", m_lbl, True, True, g4, pm, True))
            if run_v20:
                specs.append((f"V20_{m_lbl}_{pm}", "V20", m_lbl, True, True, g4, pm, True))

    print(f"[Step 1.3] Running {len(specs)} configurations at 030bps (and stress 050/080bps on key rungs)...", flush=True)
    sim_030 = {}
    eval_all = {}
    table_rows = []

    # Run B0 and B1 first so reference arrays are ready
    for nm, b_lbl, rung, use_p2, use_da, g4, pm, run_stress in specs:
        b_cfg = v22.CFG_V20 if b_lbl == "V20" else v22.CFG_V21
        c_use = mods[(use_p2, use_da)]
        raw45 = dirb[g4]["raw"] if g4 else None
        s30 = v22.run_v22_sim(c_use, b_cfg, raw_4to5_df=raw45, pos_mode=pm, fee_mode="030", tier_lbl=f"4to5_{g4}" if g4 else "4to5")
        assert s30["mtm_diff_5y"] / max(1.0, float(np.prod(1.0 + s30["dr_5y"]))) < 1e-10, f"MTM 5Y mismatch on {nm}"
        assert s30["mtm_diff_wf"] / max(1.0, float(np.prod(1.0 + s30["dr_wf"]))) < 1e-10, f"MTM WF mismatch on {nm}"
        sim_030[nm] = s30

        ref_nm = "B0_V20" if b_lbl == "V20" else "B1_V21"
        ref_wf = sim_030[ref_nm]["dr_wf"] if nm != ref_nm else None
        ref_5y = sim_030[ref_nm]["dr_5y"] if nm != ref_nm else None
        p_n = 1000 if (nm in ("B0_V20", "B1_V21") or ("V21_M" in nm and "NoDefer" not in nm and ("M1" in nm or "M2" in nm or "M4" in nm or "M5_" in nm))) else 0
        ev30 = v22.evaluate_d15_full(nm, rung, s30, cache_base, ref_dr_wf=ref_wf, ref_dr_5y=ref_5y, perm_n=p_n)
        eval_all[(nm, "030")] = ev30

        if run_stress:
            for fm in ("050", "080"):
                sf = v22.run_v22_sim(c_use, b_cfg, raw_4to5_df=raw45, pos_mode=pm, fee_mode=fm, tier_lbl=f"4to5_{g4}" if g4 else "4to5")
                ref_s_wf = eval_all[(ref_nm, fm)]["_dr_wf"] if (ref_nm, fm) in eval_all else None
                evf = v22.evaluate_d15_full(nm, rung, sf, cache_base, ref_dr_wf=ref_s_wf, perm_n=0)
                evf["_dr_wf"] = sf["dr_wf"]
                eval_all[(nm, fm)] = evf
                if nm in ("B0_V20", "B1_V21"):
                    ev_b = eval_all[(nm, fm)]
                    ev_b["_dr_wf"] = sf["dr_wf"]

    # 3. Dual-Scissors & LOO Attribution
    print("[Step 1.4] Running Dual-Scissors & LOO Attribution...", flush=True)
    scissors_vs_base = {}
    scissors_marginal = {}
    diff_details = {}

    marg_parent_map = {}
    for b_lbl in ("V21", "V20"):
        ref_b = "B1_V21" if b_lbl == "V21" else "B0_V20"
        marg_parent_map[f"{b_lbl}_M1_P2"] = ref_b
        marg_parent_map[f"{b_lbl}_M2_DirA"] = ref_b
        marg_parent_map[f"{b_lbl}_M4_P2_DirA"] = f"{b_lbl}_M1_P2"
        for pm in ("Pos1", "Pos2", "Pos5"):
            marg_parent_map[f"{b_lbl}_M5_A_{pm}"] = f"{b_lbl}_M4_P2_DirA"
            marg_parent_map[f"{b_lbl}_M5_B_{pm}"] = f"{b_lbl}_M4_P2_DirA"
            marg_parent_map[f"{b_lbl}_M5_B_NoXQ_{pm}"] = f"{b_lbl}_M4_P2_DirA"
            if b_lbl == "V21":
                marg_parent_map[f"V21_M5_B_E4_DtDefer_{pm}"] = "V21_M4_P2_DirA"

    # Also test marginal XQLt6 (M5_B vs M5_B_NoXQ) and 7f on 4to5 (M5_B vs M5_B_E4_DtDefer) and P2 / DirA LOO
    extra_pairs = []
    for pm in ("Pos1", "Pos2", "Pos5"):
        extra_pairs.extend([
            (f"LOO_XQLt6_on_M5B_{pm}", f"V21_M5_B_{pm}", f"V21_M5_B_NoXQ_{pm}"),
            (f"LOO_7f_on_M5B_{pm}", f"V21_M5_B_{pm}", f"V21_M5_B_E4_DtDefer_{pm}"),
            (f"LOO_4to5_SJ114XQLt6_on_M4_{pm}", f"V21_M5_B_{pm}", "V21_M4_P2_DirA"),
            (f"LOO_4to5_Fix120_on_M4_{pm}", f"V21_M5_A_{pm}", "V21_M4_P2_DirA"),
            (f"LOO_P2_on_M5B_{pm}", f"V21_M5_B_{pm}", f"V21_M3_SJ114_XQLt6_7f_DtDefer_{pm}"),
            (f"LOO_DirA_on_M4", "V21_M4_P2_DirA", "V21_M1_P2"),
            (f"LOO_P2_on_M4", "V21_M4_P2_DirA", "V21_M2_DirA"),
        ])

    for nm, b_lbl, rung, use_p2, use_da, g4, pm, run_stress in specs:
        ref_b = "B0_V20" if b_lbl == "V20" else "B1_V21"
        if nm != ref_b:
            sc_b = v22.run_dual_scissors_and_diff(f"{nm}_vs_{ref_b}", sim_030[nm]["trades_df"], sim_030[ref_b]["trades_df"], eval_all[(nm, "030")], eval_all[(ref_b, "030")])
            scissors_vs_base[nm] = {"cf_5y": sc_b["cf_5y"], "cf_wf": sc_b["cf_wf"]}
            if ("V21_M5_" in nm or nm in ("V21_M1_P2", "V21_M2_DirA", "V21_M4_P2_DirA")) and "NoDefer" not in nm:
                diff_details[nm] = sc_b["diff_rows"]
        mp = marg_parent_map.get(nm)
        if mp:
            sc_m = v22.run_dual_scissors_and_diff(f"{nm}_vs_{mp}", sim_030[nm]["trades_df"], sim_030[mp]["trades_df"], eval_all[(nm, "030")], eval_all[(mp, "030")])
            paired_m = v22.paired_perm_test(sim_030[nm]["dr_wf"], sim_030[mp]["dr_wf"], n_perm=1000)
            scissors_marginal[nm] = {"parent": mp, "cf_5y": sc_m["cf_5y"], "cf_wf": sc_m["cf_wf"], "paired_wf": paired_m}

        for fm in ("030", "050", "080"):
            if (nm, fm) not in eval_all:
                continue
            table_rows.append(
                flatten_row(
                    nm, b_lbl, rung, pm, fm, eval_all[(nm, fm)],
                    scissors_vs_base.get(nm) if fm == "030" else None,
                    scissors_marginal.get(nm) if fm == "030" else None,
                )
            )

    loo_audit = {}
    for tag, nm_new, nm_old in extra_pairs:
        sc = v22.run_dual_scissors_and_diff(tag, sim_030[nm_new]["trades_df"], sim_030[nm_old]["trades_df"], eval_all[(nm_new, "030")], eval_all[(nm_old, "030")])
        p_wf = v22.paired_perm_test(sim_030[nm_new]["dr_wf"], sim_030[nm_old]["dr_wf"], n_perm=1000)
        loo_audit[tag] = {"new": nm_new, "without_block": nm_old, "cf_5y": sc["cf_5y"], "cf_wf": sc["cf_wf"], "paired_wf": p_wf, "diff_rows": sc["diff_rows"]}

    # Clean non-serializable helper keys before dumping
    eval_clean = {
        f"{nm}__{fm}": {k: v for k, v in ev.items() if k != "_dr_wf"}
        for (nm, fm), ev in eval_all.items()
    }
    df_tbl = pd.DataFrame(table_rows)
    df_tbl.to_csv(f"{OUT_DIR}/v22_ablation_table.csv", index=False, encoding="utf-8-sig")

    pkg = {
        "standalone_4to5": standalone_4to5,
        "evals": eval_clean,
        "sim_030": sim_030,
        "scissors_vs_base": scissors_vs_base,
        "scissors_marginal": scissors_marginal,
        "loo_audit": loo_audit,
        "diff_details": diff_details,
    }
    with open(f"{CACHE_DIR}/step1_ablation_results.pkl", "wb") as f:
        pickle.dump(pkg, f, protocol=pickle.HIGHEST_PROTOCOL)

    print(f"\n[Step 1 DONE in {time.time()-t0:.1f}s | RSS={v22.rss_mb()} MB] Rows={len(df_tbl)}")
    # Print concise V21 30bps summary for immediate inspection
    sub = df_tbl[(df_tbl["fee"] == "030") & (df_tbl["base"] == "V21") & (~df_tbl["model"].str.contains("NoDefer"))]
    cols = ["model", "FULL_5Y_n", "FULL_5Y_nav", "FULL_5Y_mdd", "FULL_5Y_dd2", "FULL_5Y_sh", "WF_2326_nav", "WF_2326_mdd", "WF_2326_sh", "Y2025_2026_nav", "Y2026_nav", "Y2026_H2_nav", "vs_base_ex_both_wf", "marg_ex_both_wf", "paired_p_wf"]
    print(sub[cols].to_string(index=False))


if __name__ == "__main__":
    main()
