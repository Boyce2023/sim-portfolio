#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_dirA_addendum_audit.py — Direction A 深度复核与稳健性终裁（V21池对照 + 阈值平滑度 + 龙虎榜子原子消融 + 滑点/顺延检查）。
"""
import json
import os
import pickle
import sys
import time
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)
import _p1a_common as cm
import run_dirA_4to5_to_3to4 as dirA


def eval_subset_metrics(name: str, cache, states, genes, daily_ctx, bench_df, cal_dts, mode_cfg, v21_bl_keys, min_score=90.0):
    res = dirA.evaluate_dirA_variant(
        name, "ADDENDUM", cache, states, genes, daily_ctx, bench_df, cal_dts,
        mode_cfg, max_dt="2026-11-16", v21_bl_keys=v21_bl_keys, min_score=min_score,
    )
    w = res["windows"]
    return {
        "name": name,
        "ss_n": w["FULL_5Y"]["ss_n"],
        "IS_nav": w["IS_21_23"]["nav"],
        "IS_eq": w["IS_21_23"]["eq_nav"],
        "OOS_nav": w["OOS_24_26"]["nav"],
        "OOS_eq": w["OOS_24_26"]["eq_nav"],
        "OOS_exHefu": w["OOS_24_26"]["ex_hefu_nav"],
        "Y2526_nav": w["Y2025_2026"]["nav"],
        "Y26_nav": w["Y2026"]["nav"],
        "FULL_nav": w["FULL_5Y"]["nav"],
        "FULL_eq": w["FULL_5Y"]["eq_nav"],
        "FULL_ex2": w["FULL_5Y"]["ex2_nav"],
        "FULL_50bps": w["FULL_5Y"]["nav_50bps"],
        "boot_p05": res["bootstrap_10k"]["mean_p05_pct"],
        "V21_IS": res["v21_pool"].get("IS_nav", 1.0),
        "V21_OOS": res["v21_pool"].get("OOS_nav", 1.0),
        "V21_Y2526": res["v21_pool"].get("Y2526_nav", 1.0),
        "V21_FULL": res["v21_pool"].get("FULL_nav", 1.0),
        "raw_df": res["raw_df"],
        "slot_df": res["slot_df"],
    }


def main():
    t0 = time.time()
    with open(f"{dirA.F1_DIR}/pit_exit_cache_full.pkl", "rb") as f:
        cache = pickle.load(f)
    states = dirA.efe.precompute_trade_day_states(cache, min_score=78.0)
    target_codes = {e["code"] for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 78.0 and e["buy_px"] is not None}
    daily_ctx = dirA.load_daily_context_pit(target_codes, max_dt="2026-11-16")
    bench_df, _, _, _, _ = cm.load_bench_and_indices(max_dt="2026-11-16")
    cal_dts = bench_df["trade_date"].tolist()
    genes = dirA.compute_d2_4to5_genes(cache, daily_ctx, max_dt="2026-11-16")

    # Also hydrate raw LHB sub-atoms on D1 for ablation
    lhb_map = cache["lhb_map"]
    code_bars = cache["code_bars_ext"]
    kpl_plate_zt = cache["kpl_plate_zt_stocks"]
    stock_theme = cache["stock_theme_5y"]
    for e in cache["buy_entries"]:
        if e["idx"] not in genes:
            continue
        c6, pos = e["code"], e["pos"]
        sd = str(code_bars[c6]["dts"][pos])
        lhb4 = lhb_map.get((sd, c6))
        plate = stock_theme.get((sd, c6), {}).get("plate", e["plate"])
        b3_set = daily_ctx["b3_codes_by_dt"].get(sd, set())
        p3_cnt = sum(1 for x in kpl_plate_zt.get((sd, plate), []) if x != c6 and x in b3_set)
        genes[e["idx"]]["d4_quant_sell"] = bool(lhb4 and lhb4["qu_net_sell"] > 0)
        genes[e["idx"]]["d4_inst_sell_10m"] = bool(lhb4 and lhb4["inst_net_sell"] > 1e7)
        genes[e["idx"]]["d4_inst_sell_20m"] = bool(lhb4 and lhb4["inst_net_sell"] > 2e7)
        genes[e["idx"]]["d4_lh_cnt_ge3"] = bool(lhb4 and lhb4["lh_cnt"] >= 3)
        genes[e["idx"]]["plate_3b_cnt"] = int(p3_cnt)

    rc_path = f"{cm.SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126/_cache/rd038_master_cache.pkl"
    with open(rc_path, "rb") as f:
        rc = pickle.load(f)
    p34 = rc["pools_ext"]["3to4"]
    m4_mask = rc["other5_variants"]["3to4"]["m4_4way_bl15"]["mask"]
    blk = p34[(p34["orig_pass"] == 1) & (~m4_mask)]
    v21_bl_keys = set(zip(blk["buy_date"].astype(str).str[:10], blk["code"].astype(str).str.zfill(6)))
    del rc

    base90 = eval_subset_metrics("V41_Base", cache, states, genes, daily_ctx, bench_df, cal_dts, None, v21_bl_keys, 90.0)
    base78 = eval_subset_metrics("V41_Base_78", cache, states, genes, daily_ctx, bench_df, cal_dts, None, v21_bl_keys, 78.0)
    b90_raw = base90["raw_df"].set_index("idx")

    tests = []
    # 1. D2OpenNeg_Cut0925 smoothness sweep
    for thr in [-0.03, -0.02, -0.01, -0.005, 0.0, 0.005, 0.01, 0.02]:
        lbl = f"D2Open_lt_{thr*100:+.1f}pct_Cut0925"
        tests.append((lbl, "1_D2OPEN_SMOOTH", {"cond_fn": (lambda t: (lambda g, st: g["d2_open_pct"] < t))(thr), "action": "cut_0925"}))

    # 2. CoreLt threshold smoothness (Tight80 + TightStep + Tight80Strip)
    for thr in [95, 100, 102, 105, 108, 110, 112]:
        tests.append((f"Core_lt_{thr}_TightStep", "2_CORELT_SMOOTH", {"cond_fn": (lambda t: (lambda g, st: g["core_score"] < t))(thr), "action": "tight_step"}))
        tests.append((f"Core_lt_{thr}_Tight80", "2_CORELT_SMOOTH", {"cond_fn": (lambda t: (lambda g, st: g["core_score"] < t))(thr), "action": "tight_80"}))
        tests.append((f"Core_lt_{thr}_Tight80Strip", "2_CORELT_SMOOTH", {"cond_fn": (lambda t: (lambda g, st: g["core_score"] < t))(thr), "action": "tight80_strip"}))

    # 3. D4LhbBad sub-atom ablation
    lhb_atoms = [
        ("D4Lhb_QuantSell", lambda g, st: g["d4_quant_sell"]),
        ("D4Lhb_Inst10M", lambda g, st: g["d4_inst_sell_10m"]),
        ("D4Lhb_Inst20M", lambda g, st: g["d4_inst_sell_20m"]),
        ("D4Lhb_LhasaGe3", lambda g, st: g["d4_lh_cnt_ge3"]),
        ("D4Lhb_QuantOrLhasa", lambda g, st: g["d4_quant_sell"] or g["d4_lh_cnt_ge3"]),
        ("D4Lhb_Full3_Bad", lambda g, st: g["d4_lhb_bad"]),
    ]
    for nm, fn in lhb_atoms:
        tests.append((f"{nm}_TightStep", "3_LHB_ABLATION", {"cond_fn": fn, "action": "tight_step"}))
        tests.append((f"{nm}_Tight80", "3_LHB_ABLATION", {"cond_fn": fn, "action": "tight_80"}))

    # 4. Plate3BCrowd check
    tests.append(("Plate3B_ge1_TightStep", "4_PLATE3B", {"cond_fn": lambda g, st: g["plate_3b_cnt"] >= 1, "action": "tight_step"}))
    tests.append(("Plate3B_ge2_TightStep", "4_PLATE3B", {"cond_fn": lambda g, st: g["plate_3b_cnt"] >= 2, "action": "tight_step"}))
    tests.append(("Plate3B_ge1_Tight80", "4_PLATE3B", {"cond_fn": lambda g, st: g["plate_3b_cnt"] >= 1, "action": "tight_80"}))

    # 5. Also check RedAnyReal / RedNoRiskHint / D4BlownPM with V21 baseline reference
    tests.append(("RedAnyReal_TightStep", "5_REF", {"cond_fn": lambda g, st: g["red_any_real"], "action": "tight_step"}))
    tests.append(("RedNoRiskHint_TightStep", "5_REF", {"cond_fn": lambda g, st: g["red_no_riskhint"], "action": "tight_step"}))
    tests.append(("D4BlownPM_TightStep", "5_REF", {"cond_fn": lambda g, st: g["d4_blown_pm"], "action": "tight_step"}))

    rows = []
    diffs_map = {}
    for tname, grp, cfg in tests:
        r90 = eval_subset_metrics(tname, cache, states, genes, daily_ctx, bench_df, cal_dts, cfg, v21_bl_keys, 90.0)
        r78 = eval_subset_metrics(f"{tname}_78", cache, states, genes, daily_ctx, bench_df, cal_dts, cfg, v21_bl_keys, 78.0)
        c_raw = r90["raw_df"].set_index("idx")
        chg_m = (c_raw["net_ret"] - b90_raw["net_ret"]).abs() > 1e-6
        n_chg = int(chg_m.sum())
        n_win = int(((c_raw["net_ret"] - b90_raw["net_ret"]) > 1e-6).sum())
        b90_ss = set(zip(base90["slot_df"]["buy_date"], base90["slot_df"]["code"]))
        c90_ss = set(zip(r90["slot_df"]["buy_date"], r90["slot_df"]["code"]))
        slot_ripple = len(b90_ss ^ c90_ss) > 0

        beat_90_3w = (r90["IS_nav"] > base90["IS_nav"] + 1e-4) and (r90["OOS_nav"] > base90["OOS_nav"] + 1e-4) and (r90["Y2526_nav"] > base90["Y2526_nav"] + 1e-4)
        beat_v21_3w = (r90["V21_IS"] > base90["V21_IS"] + 1e-4) and (r90["V21_OOS"] > base90["V21_OOS"] + 1e-4) and (r90["V21_Y2526"] > base90["V21_Y2526"] + 1e-4)
        beat_78_3w = (r78["IS_nav"] > base78["IS_nav"] + 1e-4) and (r78["OOS_nav"] > base78["OOS_nav"] + 1e-4) and (r78["Y2526_nav"] > base78["Y2526_nav"] + 1e-4)

        rows.append({
            "group": grp, "name": tname, "n_chg": n_chg, "n_win": n_win, "slot_ripple": slot_ripple,
            "IS_nav": r90["IS_nav"], "OOS_nav": r90["OOS_nav"], "Y2526_nav": r90["Y2526_nav"], "FULL_nav": r90["FULL_nav"],
            "FULL_ex2": r90["FULL_ex2"], "FULL_50bps": r90["FULL_50bps"],
            "V21_IS": r90["V21_IS"], "V21_OOS": r90["V21_OOS"], "V21_Y2526": r90["V21_Y2526"], "V21_FULL": r90["V21_FULL"],
            "N78_IS": r78["IS_nav"], "N78_OOS": r78["OOS_nav"], "N78_Y2526": r78["Y2526_nav"], "N78_FULL": r78["FULL_nav"],
            "beat_90_3w": beat_90_3w, "beat_v21_3w": beat_v21_3w, "beat_78_3w": beat_78_3w,
        })
        if tname in ("D4Lhb_QuantSell_Tight80", "D4Lhb_Inst10M_Tight80", "D4Lhb_LhasaGe3_Tight80", "Plate3B_ge1_TightStep", "D2Open_lt_+0.0pct_Cut0925", "D2Open_lt_-0.5pct_Cut0925", "D2Open_lt_+0.5pct_Cut0925"):
            dlist = []
            for idx_i, row in c_raw.iterrows():
                br = b90_raw.loc[idx_i]
                if abs(float(row["net_ret"]) - float(br["net_ret"])) > 1e-6:
                    dlist.append({"buy_date": row["buy_date"], "code": row["code"], "name": row["name"], "d_pp": round((float(row["net_ret"]) - float(br["net_ret"])) * 100.0, 2), "rpts_d2": int(dirA._risk7_pts(states[idx_i].get(row["buy_date"] if False else ( cache["buy_entries"][0]["pos"] if False else -1), {}))) if False else 0})
            diffs_map[tname] = dlist

    df_res = pd.DataFrame(rows)
    base_ref = {
        "base90": {k: v for k, v in base90.items() if k not in ("raw_df", "slot_df")},
        "base78": {k: v for k, v in base78.items() if k not in ("raw_df", "slot_df")},
    }
    out = {"elapsed_sec": round(time.time() - t0, 2), "base_ref": base_ref, "rows": rows, "diffs_map": diffs_map}
    with open(f"{cm.OUT_DIR}/dirA_addendum_audit.json", "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(out), f, ensure_ascii=False, indent=2)
    df_res.to_csv(f"{cm.OUT_DIR}/dirA_addendum_summary.csv", index=False, encoding="utf-8-sig")
    print(f"[DirA Addendum DONE in {out['elapsed_sec']}s]")
    print("BASE90:", base_ref["base90"])
    print("BASE78:", base_ref["base78"])
    print(df_res.to_string(index=False))


if __name__ == "__main__":
    main()
