#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD048 Wave 2 Step 2A: Gem 1 (5 Priority Positions) & Gem 3 Stress Test Integration into V20.0 & V21.0."""
import json, os, sys, time
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import _rd048_w2_lib as w2

def forensic_diff(tag: str, tr_new: pd.DataFrame, tr_base: pd.DataFrame, ev_new: dict, ev_base: dict) -> dict:
    """Compare trades_new vs trades_base, audit crowded-out base trades, and remove max lucky crowding/addition."""
    kb = {(r.buy_date, r.code, r.strategy): r for r in tr_base.itertuples(index=False)}
    kn = {(r.buy_date, r.code, r.strategy): r for r in tr_new.itertuples(index=False)}
    removed = [kb[k] for k in sorted(kb) if k not in kn]
    added = [kn[k] for k in sorted(kn) if k not in kb]

    # Lucky crowding counterfactual (remove single worst avoided base loss; both 5Y and WF 2023-2026)
    def _calc_cf(win_name: str, start_dt: str) -> dict:
        rem_w = [r for r in removed if r.buy_date >= start_dt]
        add_w = [r for r in added if r.buy_date >= start_dt]
        n_new, n_base = ev_new["windows"][win_name]["nav"], ev_base["windows"][win_name]["nav"]
        sh_new, sh_base = ev_new["windows"][win_name]["daily_sharpe"], ev_base["windows"][win_name]["daily_sharpe"]
        mdd_new, mdd_base = ev_new["windows"][win_name]["daily_mdd_pct"], ev_base["windows"][win_name]["daily_mdd_pct"]
        raw_mult = n_new / max(1e-12, n_base)
        worst_rem = min(rem_w, key=lambda r: float(r.net_ret)) if rem_w else None
        best_add = max(add_w, key=lambda r: float(r.net_ret)) if add_w else None
        cf_ex_worst_crowd = raw_mult * (1.0 + float(worst_rem.net_ret)) if (worst_rem and float(worst_rem.net_ret) < 0) else raw_mult
        cf_ex_best_add = raw_mult / (1.0 + float(best_add.net_ret)) if (best_add and float(best_add.net_ret) > 0) else raw_mult
        cf_ex_both = cf_ex_worst_crowd / (1.0 + float(best_add.net_ret)) if (best_add and float(best_add.net_ret) > 0) else cf_ex_worst_crowd
        return {
            "nav_base": n_base, "nav_new": n_new, "raw_mult": round(raw_mult, 4),
            "d_sharpe": round(sh_new - sh_base, 3), "d_mdd_pp": round(mdd_new - mdd_base, 2),
            "n_added": len(add_w), "n_removed": len(rem_w),
            "worst_crowded_loss": {"buy_date": worst_rem.buy_date, "code": worst_rem.code, "name": worst_rem.name, "strat": worst_rem.strategy, "ret_pct": round(float(worst_rem.net_ret) * 100.0, 2)} if worst_rem else None,
            "best_added_win": {"buy_date": best_add.buy_date, "code": best_add.code, "name": best_add.name, "strat": best_add.strategy, "ret_pct": round(float(best_add.net_ret) * 100.0, 2)} if best_add else None,
            "mult_ex_worst_crowd": round(cf_ex_worst_crowd, 4),
            "mult_ex_best_add": round(cf_ex_best_add, 4),
            "mult_ex_both": round(cf_ex_both, 4),
        }

    crowd_rows = []
    for r in removed:
        crowd_rows.append({"combo": tag, "diff_type": "REMOVED_BASE", "window": "WF" if r.buy_date >= w2.eng.WF_START else "IS",
                           "buy_date": r.buy_date, "exit_date": r.exit_date, "strategy": r.strategy, "code": r.code, "name": r.name, "net_ret_030_pct": round(float(r.net_ret) * 100.0, 2)})
    for r in added:
        crowd_rows.append({"combo": tag, "diff_type": "ADDED_NEW", "window": "WF" if r.buy_date >= w2.eng.WF_START else "IS",
                           "buy_date": r.buy_date, "exit_date": r.exit_date, "strategy": r.strategy, "code": r.code, "name": r.name, "net_ret_030_pct": round(float(r.net_ret) * 100.0, 2)})
    return {"cf_5y": _calc_cf("FULL_5Y", "2021-11-16"), "cf_wf": _calc_cf("WF_2326", w2.eng.WF_START), "crowd_rows": crowd_rows}

def main():
    t0 = time.time()
    cache = w2.load_rd038_cache()
    idx_5y = {d: i for i, d in enumerate(cache["cal_5y"])}

    # Verify Exact Baselines V20.0 & V21.0
    base_res = {}
    for bname, bcfg in [("V20_0", w2.CFG_V20), ("V21_0", w2.CFG_V21)]:
        tr0, w0 = w2.run_tier_or_empty_sim(cache, bcfg, None, mode="tier", fee_mode="030")
        ev0 = w2.compute_dr_and_eval(bname, "BASE", tr0, cache, waits_n=len(w0))
        tr50, _ = w2.run_tier_or_empty_sim(cache, bcfg, None, mode="tier", fee_mode="050")
        ev50 = w2.compute_dr_and_eval(bname, "BASE", tr50, cache)
        tr80, _ = w2.run_tier_or_empty_sim(cache, bcfg, None, mode="tier", fee_mode="080")
        ev80 = w2.compute_dr_and_eval(bname, "BASE", tr80, cache)
        base_res[bname] = {"cfg": bcfg, "tr": tr0, "ev": ev0, "ev50": ev50, "ev80": ev80}
        assert ev0["mtm_diff_5y"] < 1e-6 and ev0["mtm_diff_wf"] < 1e-6
    assert base_res["V20_0"]["ev"]["windows"]["FULL_5Y"]["n"] == 278
    assert base_res["V21_0"]["ev"]["windows"]["FULL_5Y"]["n"] == 277

    # Load Gem1 & Gem3 raw pools (is_single_slot == False)
    g1_pq = pd.read_parquet(f"{w2.RD048_DIR}/wave1a_gem1_gem3/rd048_gem1_trades.parquet")
    g1_strict = pd.read_parquet(f"{w2.RD048_DIR}/_cache_g1_strict_jianchi_raw.parquet")
    g3_pq = pd.read_parquet(f"{w2.RD048_DIR}/wave1a_gem1_gem3/rd048_gem3_trades.parquet")

    g1_variants = {
        "G1_FixPIT_114": g1_pq[(g1_pq["variant"] == "G1_FixPIT_114") & (~g1_pq["is_single_slot"])].copy(),
        "G1_FixPIT_120": g1_pq[(g1_pq["variant"] == "G1_FixPIT_120") & (~g1_pq["is_single_slot"])].copy(),
        "G1_Base_V20_120": g1_pq[(g1_pq["variant"] == "G1_Base_V20_120") & (~g1_pq["is_single_slot"])].copy(),
        "G1_Base_V20_114": g1_pq[(g1_pq["variant"] == "G1_Base_V20_114") & (~g1_pq["is_single_slot"])].copy(),
        "G1_StrictJianchi_114": g1_strict.copy(),
    }
    positions = [
        ("Pos1_TopFirst", "tier", 0.0, 0),
        ("Pos2_After34High_Pre23", "tier", 2.5, 0),
        ("Pos3_After23_Pre20cm12", "tier", 4.5, 0),
        ("Pos4_After20cm_PreWait", "tier", 6.5, 0),
        ("Pos5_EmptyDayOnly", "empty_fill", 99.0, 0),
    ]

    summary_rows, forensics_all, detail_map = [], [], {}
    for bname in ("V20_0", "V21_0"):
        b = base_res[bname]
        for gname, gdf in g1_variants.items():
            for pos_nm, sim_mode, pr_v, ph_v in positions:
                cname = f"{bname}__{gname}__{pos_nm}"
                # Run 030 / 050 / 080
                res_fee = {}
                for fm in ("030", "050", "080"):
                    ep = w2.prepare_gem_pool_for_rd038(gdf, "4to5", f"4to5_{gname}", pr_v, ph_v, idx_5y, True, fm)
                    tr_n, w_n = w2.run_tier_or_empty_sim(cache, b["cfg"], ep, mode=sim_mode, fee_mode=fm)
                    ev_n = w2.compute_dr_and_eval(cname, "GEM1_PERM", tr_n, cache, ref_dr_wf=b["ev"]["dr_wf"] if fm == "030" else None, waits_n=len(w_n))
                    assert ev_n["mtm_diff_5y"] / max(1.0, ev_n["windows"]["FULL_5Y"]["nav"]) < 1e-10 and ev_n["mtm_diff_wf"] / max(1.0, ev_n["windows"]["WF_2326"]["nav"]) < 1e-10, f"MTM diff error on {cname}"
                    res_fee[fm] = (tr_n, ev_n)

                fa = forensic_diff(cname, res_fee["030"][0], b["tr"], res_fee["030"][1], b["ev"])
                forensics_all.extend(fa["crowd_rows"])
                e30, e50, e80 = res_fee["030"][1], res_fee["050"][1], res_fee["080"][1]
                w5, wf, y26, h26 = e30["windows"]["FULL_5Y"], e30["windows"]["WF_2326"], e30["windows"]["Y2026"], e30["windows"]["Y2026_H2"]
                row = {
                    "combo": cname, "base": bname, "gem": gname, "position": pos_nm,
                    "n_5y": w5["n"], "nav_5y": w5["nav"], "ex5_5y": w5["ex_top5_nav"], "sh_5y": w5["daily_sharpe"], "mdd_5y": w5["daily_mdd_pct"], "cal_5y": w5["daily_calmar"],
                    "n_wf": wf["n"], "nav_wf": wf["nav"], "ex5_wf": wf["ex_top5_nav"], "sh_wf": wf["daily_sharpe"], "mdd_wf": wf["daily_mdd_pct"], "cal_wf": wf["daily_calmar"],
                    "nav_2026": y26["nav"], "nav_26h2": h26["nav"],
                    "nav_wf_50bps": e50["windows"]["WF_2326"]["nav"], "nav_wf_80bps": e80["windows"]["WF_2326"]["nav"],
                    "paired_t_wf": e30["vs_v20_wf"]["paired_t"], "paired_p_wf": e30["vs_v20_wf"]["paired_p_2sided"],
                    "mult_5y": fa["cf_5y"]["raw_mult"], "mult_5y_ex_worst_crowd": fa["cf_5y"]["mult_ex_worst_crowd"],
                    "mult_wf": fa["cf_wf"]["raw_mult"], "mult_wf_ex_worst_crowd": fa["cf_wf"]["mult_ex_worst_crowd"],
                    "mult_wf_ex_best_add": fa["cf_wf"]["mult_ex_best_add"], "mult_wf_ex_both": fa["cf_wf"]["mult_ex_both"],
                    "worst_crowd_wf": json.dumps(fa["cf_wf"]["worst_crowded_loss"], ensure_ascii=False),
                    "best_add_wf": json.dumps(fa["cf_wf"]["best_added_win"], ensure_ascii=False),
                }
                summary_rows.append(row)
                detail_map[cname] = {"row": row, "cf_5y": fa["cf_5y"], "cf_wf": fa["cf_wf"]}

    # Gem 3 Stress Test into V20_0 & V21_0 (main pool Pos4 vs empty_fill Pos5)
    g3_stress = []
    for g3v in ("G3_Base_All", "G3_SZ00", "G3_SZ00_Lock50", "G3_SoleHighest_Lock50"):
        g3_sub = g3_pq[(g3_pq["variant"] == g3v) & (~g3_pq["is_single_slot"])].copy()
        for bname in ("V20_0", "V21_0"):
            b = base_res[bname]
            for pos_nm, sim_mode, pr_v in [("Pos4_After20cm", "tier", 6.5), ("Pos5_EmptyDayOnly", "empty_fill", 99.0)]:
                ep3 = w2.prepare_gem_pool_for_rd038(g3_sub, "5board", g3v, pr_v, 0, idx_5y, True, "030")
                tr3, w3 = w2.run_tier_or_empty_sim(cache, b["cfg"], ep3, mode=sim_mode, fee_mode="030")
                ev3 = w2.compute_dr_and_eval(f"{bname}__{g3v}__{pos_nm}", "GEM3_STRESS", tr3, cache, ref_dr_wf=b["ev"]["dr_wf"], waits_n=len(w3))
                w5, wf, y26, h26 = ev3["windows"]["FULL_5Y"], ev3["windows"]["WF_2326"], ev3["windows"]["Y2026"], ev3["windows"]["Y2026_H2"]
                g3_stress.append({
                    "combo": f"{bname}__{g3v}__{pos_nm}", "base": bname, "gem": g3v, "position": pos_nm,
                    "n_5y": w5["n"], "nav_5y": w5["nav"], "mult_5y": round(w5["nav"] / b["ev"]["windows"]["FULL_5Y"]["nav"], 4), "sh_5y": w5["daily_sharpe"], "mdd_5y": w5["daily_mdd_pct"],
                    "n_wf": wf["n"], "nav_wf": wf["nav"], "mult_wf": round(wf["nav"] / b["ev"]["windows"]["WF_2326"]["nav"], 4), "sh_wf": wf["daily_sharpe"], "mdd_wf": wf["daily_mdd_pct"],
                    "nav_2026": y26["nav"], "nav_26h2": h26["nav"], "g3_trades_taken_5y": int((tr3["strategy"] == "5board").sum()),
                })

    pd.DataFrame(summary_rows).to_csv(f"{w2.RD048_DIR}/_step2a_gem1_summary.csv", index=False)
    pd.DataFrame(forensics_all).to_csv(f"{w2.RD048_DIR}/_step2a_gem1_forensics.csv", index=False)
    with open(f"{w2.RD048_DIR}/_step2a_results.json", "w", encoding="utf-8") as f:
        json.dump({"gem1_details": detail_map, "gem3_stress": g3_stress, "elapsed_sec": round(time.time() - t0, 2), "rss_mb": w2.rss_mb()}, f, ensure_ascii=False, indent=2)
    print(f"Step 2A DONE in {time.time()-t0:.1f}s | RSS={w2.rss_mb()} MB | Gem1 rows={len(summary_rows)} | Gem3 stress={len(g3_stress)}")

if __name__ == "__main__":
    main()
