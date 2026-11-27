#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD048 Wave 2 Step 2B: Gem 2 (US-Map Strict PIT) Empty-Day Physical Ledger Integration into V20.0 & V21.0."""
import json, os, sys, time
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import _rd048_w2_lib as w2

W1B = f"{w2.RD048_DIR}/wave1b_gem2_gem4"
if W1B not in sys.path:
    sys.path.insert(0, W1B)
import step4_run_gem2_backtest as s4

def build_full_gem2_cands_pool(cands: pd.DataFrame, lookup: dict, pos_cache: dict, pool_name: str, exit_type: str, filter_fn, cal_end: str = "2026-11-16") -> pd.DataFrame:
    """Build ALL qualifying day-top1 Gem2 candidates (before Gem2 own-slot filtering) with exact MTM pairs."""
    ex_col, gret_col, ex_hhmm = s4.EXIT_MAP[exit_type]
    sub = s4.get_pool_slice(cands, pool_name, filter_fn)
    sub = sub[(sub["dt"] >= "2021-11-16") & (sub[ex_col] != "") & (sub[ex_col] <= cal_end) & sub[gret_col].notna()].copy()
    sub["rk"] = s4.compute_rank_score(sub, "corr_amt")
    sub = sub.sort_values(["dt", "rk", "c6"], ascending=[True, False, True]).groupby("dt", as_index=False).first()
    rows = []
    for r in sub.itertuples(index=False):
        ap, nr30 = s4.compute_trade_mtm_pairs(str(r.c6), str(r.dt), str(getattr(r, ex_col)), ex_hhmm, 0.0030, lookup, pos_cache)
        rows.append({
            "buy_date": str(r.dt), "exit_date": str(getattr(r, ex_col)), "buy_hhmm": 925, "exit_hhmm": int(ex_hhmm),
            "code": str(r.c6), "name": str(r.name), "score": float(r.rk), "net_ret": float(nr30), "mtm_pairs_json": json.dumps(ap),
        })
    return pd.DataFrame(rows)

def check_non_overlapping_theoretical_only(ep_df: pd.DataFrame, tr_base: pd.DataFrame, waits_base: list, cache: dict) -> pd.DataFrame:
    """Keep ONLY Gem2 trades whose [buy_date, exit_date] has ZERO collision with any future base trade or wait."""
    cal = cache["cal_5y"]
    idx = {d: i for i, d in enumerate(cal)}
    occ = set(waits_base)
    for r in tr_base.itertuples(index=False):
        bi, ei = idx.get(r.buy_date), idx.get(r.exit_date)
        if bi is not None and ei is not None:
            for ti in range(bi, ei + 1):
                occ.add(cal[ti])
    sel_rows, cur_ed = [], ""
    for idx_r, r in ep_df.sort_values("buy_date").iterrows():
        if cur_ed and r["buy_date"] <= cur_ed:
            continue
        bi, ei = idx.get(r["buy_date"]), idx.get(r["exit_date"])
        if bi is None or ei is None:
            continue
        if any(cal[ti] in occ for ti in range(bi, ei + 1)):
            continue
        sel_rows.append(idx_r)
        cur_ed = r["exit_date"]
    return ep_df.loc[sel_rows].copy().reset_index(drop=True)

def main():
    t0 = time.time()
    cache = w2.load_rd038_cache()
    idx_5y = {d: i for i, d in enumerate(cache["cal_5y"])}
    cands = pd.read_parquet(f"{W1B}/_gem2_pit_candidates_cache.parquet")
    lookup, pos_cache = s4.load_price_lookup_for_codes(set(cands["c6"].unique().tolist()), "2026-11-25")

    specs = [
        ("PIT1A_NoZT_GapMod15_VR12_MA5", "PIT_Track1A_CausalCorr", "MA5",
         lambda d: (d["prev_streak"] == 0) & (d["open_pct"] >= 1.0) & (d["open_pct"] <= 5.0) & (d["vol_ratio5_t1"] >= 1.2)),
        ("PIT1B_NoZT_GapLow_VR12_T1C", "PIT_Track1B_IR_Plus_Corr", "T1C",
         lambda d: (d["prev_streak"] == 0) & (d["open_pct"] >= -3.0) & (d["open_pct"] <= 1.0) & (d["vol_ratio5_t1"] >= 1.2)),
        ("PIT1A_NoZT_GapMod15_VR12_T2C", "PIT_Track1A_CausalCorr", "T2C",
         lambda d: (d["prev_streak"] == 0) & (d["open_pct"] >= 1.0) & (d["open_pct"] <= 5.0) & (d["vol_ratio5_t1"] >= 1.2)),
    ]

    bases = {}
    for bname, bcfg in [("V20_0", w2.CFG_V20), ("V21_0", w2.CFG_V21)]:
        tr0, w0 = w2.run_tier_or_empty_sim(cache, bcfg, None, mode="tier", fee_mode="030")
        ev0 = w2.compute_dr_and_eval(bname, "BASE", tr0, cache, waits_n=len(w0))
        bases[bname] = {"cfg": bcfg, "tr": tr0, "waits": w0, "ev": ev0}

    results, crowd_rows = [], []
    for gname, pool_nm, ex_t, flt_fn in specs:
        raw_df = build_full_gem2_cands_pool(cands, lookup, pos_cache, pool_nm, ex_t, flt_fn, "2026-11-16")
        ep_df = w2.prepare_gem_pool_for_rd038(raw_df, "usmap", gname, 99.0, 0, idx_5y, False, "030")
        for bname in ("V20_0", "V21_0"):
            b = bases[bname]
            # 1) Real single-account physical ledger (enters on empty day, holds till exit, crowds future base trades!)
            tr_real, w_real = w2.run_tier_or_empty_sim(cache, b["cfg"], ep_df, mode="empty_fill", fee_mode="030")
            ev_real = w2.compute_dr_and_eval(f"{bname}__{gname}__RealLedger", "GEM2_REAL", tr_real, cache, ref_dr_wf=b["ev"]["dr_wf"], waits_n=len(w_real))
            assert ev_real["mtm_diff_5y"] / max(1.0, ev_real["windows"]["FULL_5Y"]["nav"]) < 1e-10 and ev_real["mtm_diff_wf"] / max(1.0, ev_real["windows"]["WF_2326"]["nav"]) < 1e-10

            kb = {(r.buy_date, r.code, r.strategy): r for r in b["tr"].itertuples(index=False)}
            kn = {(r.buy_date, r.code, r.strategy): r for r in tr_real.itertuples(index=False)}
            rem = [kb[k] for k in sorted(kb) if k not in kn]
            add_g2 = [r for r in tr_real.itertuples(index=False) if r.strategy == "usmap"]
            for r in rem:
                crowd_rows.append({"combo": f"{bname}__{gname}__RealLedger", "diff_type": "CROWDED_BASE_BY_GEM2", "buy_date": r.buy_date, "exit_date": r.exit_date, "strategy": r.strategy, "code": r.code, "name": r.name, "net_ret_030_pct": round(float(r.net_ret) * 100.0, 2)})

            # 2) Theoretical Zero-Collision Upper Bound
            ep_nocoll = check_non_overlapping_theoretical_only(ep_df, b["tr"], b["waits"], cache)
            tr_theo, w_theo = w2.run_tier_or_empty_sim(cache, b["cfg"], ep_nocoll, mode="empty_fill", fee_mode="030")
            ev_theo = w2.compute_dr_and_eval(f"{bname}__{gname}__TheoZeroColl", "GEM2_THEO", tr_theo, cache, ref_dr_wf=b["ev"]["dr_wf"], waits_n=len(w_theo))

            for lbl, evx, n_g2, n_cr, rem_list in [
                ("RealPhysicalLedger", ev_real, len(add_g2), len(rem), rem),
                ("TheoZeroCollision", ev_theo, int((tr_theo["strategy"] == "usmap").sum()), 0, []),
            ]:
                w5, wf, y26, h26 = evx["windows"]["FULL_5Y"], evx["windows"]["WF_2326"], evx["windows"]["Y2026"], evx["windows"]["Y2026_H2"]
                b5, bwf = b["ev"]["windows"]["FULL_5Y"]["nav"], b["ev"]["windows"]["WF_2326"]["nav"]
                results.append({
                    "combo": f"{bname}__{gname}__{lbl}", "base": bname, "gem": gname, "mode": lbl,
                    "gem2_trades_taken_5y": n_g2, "base_trades_crowded_5y": n_cr,
                    "crowded_base_mean_ret_pct": round(float(np.mean([r.net_ret for r in rem_list]) * 100.0), 2) if rem_list else 0.0,
                    "n_5y": w5["n"], "nav_5y": w5["nav"], "mult_5y": round(w5["nav"] / b5, 4), "sh_5y": w5["daily_sharpe"], "mdd_5y": w5["daily_mdd_pct"],
                    "n_wf": wf["n"], "nav_wf": wf["nav"], "mult_wf": round(wf["nav"] / bwf, 4), "sh_wf": wf["daily_sharpe"], "mdd_wf": wf["daily_mdd_pct"],
                    "nav_2026": y26["nav"], "nav_26h2": h26["nav"], "paired_t_wf": evx["vs_v20_wf"]["paired_t"],
                })

    pd.DataFrame(results).to_csv(f"{w2.RD048_DIR}/_step2b_gem2_summary.csv", index=False)
    pd.DataFrame(crowd_rows).to_csv(f"{w2.RD048_DIR}/_step2b_gem2_forensics.csv", index=False)
    print(f"Step 2B DONE in {time.time()-t0:.1f}s | RSS={w2.rss_mb()} MB | rows={len(results)}")

if __name__ == "__main__":
    main()
