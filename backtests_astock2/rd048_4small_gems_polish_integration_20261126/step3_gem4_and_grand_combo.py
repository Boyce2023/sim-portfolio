#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD048 Wave 2 Step 3: Gem 4 Mode A/B Integration, Orthogonal Grand Combo & Master Audit JSON/CSVs."""
import json, os, sys, time
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import _rd048_w2_lib as w2
import step3_helpers as h3

def _fmt_row(name, grp, ev, b_ev, extra=None):
    w5, wf, y26, h26 = ev["windows"]["FULL_5Y"], ev["windows"]["WF_2326"], ev["windows"]["Y2026"], ev["windows"]["Y2026_H2"]
    b5, bwf = b_ev["windows"]["FULL_5Y"]["nav"], b_ev["windows"]["WF_2326"]["nav"]
    row = {
        "combo": name, "group": grp,
        "n_5y": w5["n"], "nav_5y": w5["nav"], "mult_5y": round(w5["nav"] / b5, 4), "sh_5y": w5["daily_sharpe"], "mdd_5y": w5["daily_mdd_pct"], "cal_5y": w5["daily_calmar"],
        "n_wf": wf["n"], "nav_wf": wf["nav"], "mult_wf": round(wf["nav"] / bwf, 4), "sh_wf": wf["daily_sharpe"], "mdd_wf": wf["daily_mdd_pct"], "cal_wf": wf["daily_calmar"],
        "nav_2026": y26["nav"], "nav_26h2": h26["nav"], "paired_t_wf": ev["vs_v20_wf"]["paired_t"], "paired_p_wf": ev["vs_v20_wf"]["paired_p_2sided"],
    }
    if extra:
        row.update(extra)
    return row

def run_gem4_mode_a(cache, bases, g4_pq, idx_5y, forensics):
    """Gem 4 Mode A: empty-day switch between stocks and IF/510300 with real bank-futures transfer lag."""
    variants = [
        ("P_IF_3x_V3EOD_ge65_H3_SL2", [(0, 0), (1, 1), (2, 2)]),
        ("P_IF_5x_V3EOD_ge65_H3_SL2", [(0, 0), (1, 1), (2, 2)]),
        ("P_IF_3x_V3EOD_ge65_H3_NoSL", [(1, 1)]),
        ("P_IF_5x_V3EOD_ge65_H3_NoSL", [(1, 1)]),
        ("A_IF_3x_V3Live60_H5_NoSL_10bps", [(1, 1)]),
        ("A_IF_5x_V3Live60_H5_NoSL_10bps", [(1, 1)]),
        ("A_ETF510300_1x_V3Live60_H5", [(0, 0)]),
    ]
    rows = []
    for vname, lags in variants:
        sub = g4_pq[g4_pq["variant"] == vname].copy()
        ep = w2.prepare_gem_pool_for_rd038(sub, "gem4_fut", vname, 99.0, 0, idx_5y, False, "030")
        for bname, b in bases.items():
            for l_s2f, l_f2s in lags:
                cname = f"{bname}__ModeA_{vname}__Lag{l_s2f}_{l_f2s}"
                tr_n, w_n = w2.run_tier_or_empty_sim(cache, b["cfg"], ep, mode="empty_fill", fee_mode="030", stock_to_fut_lag=l_s2f, fut_to_stock_lag=l_f2s)
                ev_n = w2.compute_dr_and_eval(cname, "GEM4_MODEA", tr_n, cache, ref_dr_wf=b["ev"]["dr_wf"], waits_n=len(w_n))
                assert ev_n["mtm_diff_5y"] / max(1.0, ev_n["windows"]["FULL_5Y"]["nav"]) < 1e-10
                assert ev_n["mtm_diff_wf"] / max(1.0, ev_n["windows"]["WF_2326"]["nav"]) < 1e-10
                kb = {(r.buy_date, r.code, r.strategy): r for r in b["tr"].itertuples(index=False)}
                kn = {(r.buy_date, r.code, r.strategy): r for r in tr_n.itertuples(index=False)}
                rem = [kb[k] for k in sorted(kb) if k not in kn]
                add = [kn[k] for k in sorted(kn) if k not in kb]
                for r in rem:
                    forensics.append({"combo": cname, "diff_type": "CROWDED_BASE_BY_GEM4", "window": "WF" if r.buy_date >= w2.eng.WF_START else "IS",
                                      "buy_date": r.buy_date, "exit_date": r.exit_date, "strategy": r.strategy, "code": r.code, "name": r.name, "net_ret_pct": round(float(r.net_ret)*100, 2)})
                for r in add:
                    forensics.append({"combo": cname, "diff_type": "ADDED_GEM4", "window": "WF" if r.buy_date >= w2.eng.WF_START else "IS",
                                      "buy_date": r.buy_date, "exit_date": r.exit_date, "strategy": r.strategy, "code": r.code, "name": r.name, "net_ret_pct": round(float(r.net_ret)*100, 2)})
                rows.append(_fmt_row(cname, "GEM4_MODEA", ev_n, b["ev"], {
                    "base": bname, "gem": vname, "mode": f"ModeA_Lag{l_s2f}_{l_f2s}",
                    "extra_trades_5y": int((tr_n["strategy"] == "gem4_fut").sum()), "crowded_base_5y": len(rem),
                }))
    return rows

def run_gem4_mode_b(cache, bases, g4_pq):
    """Gem 4 Mode B: independent margin sleeve (10%/15%/20%) + Cash control + crash co-movement audit."""
    cal_5y = cache["cal_5y"]
    vars_b = ["P_IF_3x_V3EOD_ge65_H3_SL2", "P_IF_5x_V3EOD_ge65_H3_SL2", "P_IF_3x_V3EOD_ge65_H3_NoSL", "A_IF_3x_V3Live60_H5_NoSL_10bps", "A_ETF510300_1x_V3Live60_H5", "CASH_0PCT"]
    dr_map, df_map = {}, {}
    for vn in vars_b:
        if vn == "CASH_0PCT":
            dr_map[vn] = np.zeros(len(cal_5y), dtype=float)
        else:
            sub = g4_pq[g4_pq["variant"] == vn].copy()
            dr_v, sub_c = h3.build_gem4_daily_returns(sub, cal_5y, "2026-11-16")
            dr_map[vn], df_map[vn] = dr_v, sub_c
    rows, comov_audit = [], {}
    wf_off = {d: i for i, d in enumerate(cal_5y)}[w2.eng.WF_START]
    for bname, b in bases.items():
        dr_stk = b["ev"]["dr_5y"]
        # Precompute CASH_0PCT reference for exact same-weight pure-alpha comparison
        cash_ref = {w: h3.calc_mode_b_accounting(dr_stk, dr_map["CASH_0PCT"], w, cal_5y) for w in (0.10, 0.15, 0.20)}
        cash_navs = {}
        for w in (0.10, 0.15, 0.20):
            for anm, drc in cash_ref[w].items():
                ev_cr = h3.eval_daily_series("cr", "CR", drc, b["ev"]["dr_wf"], cache, b["tr"])
                cash_navs[(w, anm)] = (ev_cr["windows"]["FULL_5Y"]["nav"], ev_cr["windows"]["WF_2326"]["nav"], drc[wf_off:])
        for vn in vars_b:
            for w in (0.10, 0.15, 0.20):
                if vn not in ("P_IF_3x_V3EOD_ge65_H3_SL2", "P_IF_5x_V3EOD_ge65_H3_SL2", "CASH_0PCT") and w != 0.15:
                    continue
                acc_dict = h3.calc_mode_b_accounting(dr_stk, dr_map[vn], w, cal_5y)
                for acc_nm, dr_c in acc_dict.items():
                    cname = f"{bname}__ModeB_w{int(w*100)}_{vn}__{acc_nm}"
                    c5, cwf, dr_cwf = cash_navs[(w, acc_nm)]
                    ev_c = h3.eval_daily_series(cname, "GEM4_MODEB", dr_c, b["ev"]["dr_wf"], cache, b["tr"], ref_cash_wf=dr_cwf)
                    rows.append(_fmt_row(cname, "GEM4_MODEB", ev_c, b["ev"], {
                        "base": bname, "gem": vn, "mode": f"ModeB_w{int(w*100)}_{acc_nm}",
                        "mult_vs_cash_5y": round(ev_c["windows"]["FULL_5Y"]["nav"] / c5, 4),
                        "mult_vs_cash_wf": round(ev_c["windows"]["WF_2326"]["nav"] / cwf, 4),
                        "t_vs_cash_wf": ev_c.get("t_vs_cash_wf", 0.0),
                    }))
            if vn in ("P_IF_3x_V3EOD_ge65_H3_SL2", "P_IF_5x_V3EOD_ge65_H3_SL2"):
                comov_audit[f"{bname}__{vn}__w15"] = h3.audit_crash_window_comovement(b["tr"], dr_stk, df_map[vn], cal_5y, 0.15)
    return rows, comov_audit, dr_map

def main():
    t0 = time.time()
    cache = w2.load_rd038_cache()
    cal_5y = cache["cal_5y"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    bases = {}
    for bname, bcfg in [("V20_0", w2.CFG_V20), ("V21_0", w2.CFG_V21)]:
        tr0, w0 = w2.run_tier_or_empty_sim(cache, bcfg, None, mode="tier", fee_mode="030")
        ev0 = w2.compute_dr_and_eval(bname, "BASE", tr0, cache, waits_n=len(w0))
        bases[bname] = {"cfg": bcfg, "tr": tr0, "ev": ev0}

    g4_pq = pd.read_parquet(f"{w2.RD048_DIR}/wave1b_gem2_gem4/rd048_gem4_trades.parquet")
    g1_pq = pd.read_parquet(f"{w2.RD048_DIR}/wave1a_gem1_gem3/rd048_gem1_trades.parquet")
    g1_strict = pd.read_parquet(f"{w2.RD048_DIR}/_cache_g1_strict_jianchi_raw.parquet")

    forensics = []
    rows_a = run_gem4_mode_a(cache, bases, g4_pq, idx_5y, forensics)
    rows_b, comov, dr_g4 = run_gem4_mode_b(cache, bases, g4_pq)

    # Orthogonal Grand Combos + G1_StrictJianchi_120 check + Post-1116 sensitivity
    g1_sets = {
        "G1_FixPIT_120": g1_pq[(g1_pq["variant"] == "G1_FixPIT_120") & (~g1_pq["is_single_slot"])].copy(),
        "G1_StrictJianchi_114": g1_strict.copy(),
        "G1_StrictJianchi_120": g1_strict[g1_strict["score"] >= 120.0].copy(),
    }
    combo_rows, combo_slip = [], []
    for bname, b in bases.items():
        for g1n, g1df in g1_sets.items():
            # Stock combo at Pos2 (prio=2.5) and Pos5 (empty_fill); note G1_FixPIT_120 is invariant across Pos1..5
            tr_g1, w_g1 = w2.run_tier_or_empty_sim(cache, b["cfg"], w2.prepare_gem_pool_for_rd038(g1df, "4to5", g1n, 2.5, 0, idx_5y, True, "030"), mode="tier", fee_mode="030")
            ev_g1 = w2.compute_dr_and_eval(f"{bname}__{g1n}", "GRAND_COMBO", tr_g1, cache, ref_dr_wf=b["ev"]["dr_wf"], waits_n=len(w_g1))
            combo_rows.append(_fmt_row(f"{bname}__{g1n}__Pos2", "GRAND_COMBO", ev_g1, b["ev"], {"base": bname, "gem": g1n, "mode": "StockUpgrade_030bps"}))
            for fm in ("050", "080"):
                tr_s, w_s = w2.run_tier_or_empty_sim(cache, b["cfg"], w2.prepare_gem_pool_for_rd038(g1df, "4to5", g1n, 2.5, 0, idx_5y, True, fm), mode="tier", fee_mode=fm)
                ev_s = w2.compute_dr_and_eval(f"{bname}__{g1n}__{fm}", "SLIP", tr_s, cache, ref_dr_wf=b["ev"]["dr_wf"], waits_n=len(w_s))
                combo_slip.append(_fmt_row(f"{bname}__{g1n}__{fm}bps", "SLIP", ev_s, b["ev"], {"base": bname, "gem": g1n, "mode": f"StockUpgrade_{fm}bps"}))
            # Orthogonal Combo: Stock (V+G1) + Mode B 10/15/20% IF 3x & 5x + 20bps IF stress + Mode A (Lag1_1)
            for ifn in ("P_IF_3x_V3EOD_ge65_H3_SL2", "P_IF_5x_V3EOD_ge65_H3_SL2"):
                ws = (0.10, 0.15, 0.20) if g1n == "G1_FixPIT_120" else (0.15,)
                for w_f in ws:
                    acc = h3.calc_mode_b_accounting(ev_g1["dr_5y"], dr_g4[ifn], w_f, cal_5y)
                    for anm in ("FixedWeight_DailyRebal", "Quarterly_Rebal"):
                        cname = f"{bname}__{g1n}__ModeB_w{int(w_f*100)}_{ifn}__{anm}"
                        ev_c = h3.eval_daily_series(cname, "GRAND_COMBO", acc[anm], b["ev"]["dr_wf"], cache, tr_g1)
                        combo_rows.append(_fmt_row(cname, "GRAND_COMBO", ev_c, b["ev"], {"base": bname, "gem": f"{g1n}+{ifn}", "mode": f"Ortho_w{int(w_f*100)}_{anm}"}))
                # 20bps IF stress (with 050bps stock stress) for w=15% FixedWeight
                if g1n == "G1_FixPIT_120":
                    lev = 3.0 if "3x" in ifn else 5.0
                    sub20 = g4_pq[g4_pq["variant"] == ifn].copy()
                    sub20["net_ret"] = sub20["net_ret"] - lev * 0.0010
                    dr_20, _ = h3.build_gem4_daily_returns(sub20, cal_5y, "2026-11-16", allow_fee_scale=True)
                    tr_s50, _ = w2.run_tier_or_empty_sim(cache, b["cfg"], w2.prepare_gem_pool_for_rd038(g1df, "4to5", g1n, 2.5, 0, idx_5y, True, "050"), mode="tier", fee_mode="050")
                    ev_s50 = w2.compute_dr_and_eval(f"{bname}_{g1n}_50", "SLIP", tr_s50, cache)
                    dr_20c = h3.calc_mode_b_accounting(ev_s50["dr_5y"], dr_20, 0.15, cal_5y)["FixedWeight_DailyRebal"]
                    ev_20c = h3.eval_daily_series(f"{bname}__{g1n}__ModeB_w15_{ifn}__Stk50_IF20", "SLIP", dr_20c, b["ev"]["dr_wf"], cache, tr_s50)
                    combo_slip.append(_fmt_row(f"{bname}__{g1n}__ModeB_w15_{ifn}__Stk50_IF20", "SLIP", ev_20c, b["ev"], {"base": bname, "gem": f"{g1n}+{ifn}", "mode": "Ortho_w15_Stk50_IF20"}))
                    ep_if = w2.prepare_gem_pool_for_rd038(g4_pq[g4_pq["variant"] == ifn].copy(), "gem4_fut", ifn, 99.0, 0, idx_5y, False, "030")
                    for l1, l2 in [(1, 1), (2, 2)]:
                        tr_ma, _ = h3.overlay_mode_a_on_stock_ledger(cache, tr_g1, ep_if, l1, l2)
                        ev_ma = w2.compute_dr_and_eval(f"{bname}__{g1n}__ModeA_{ifn}_Lag{l1}_{l2}", "GRAND_COMBO", tr_ma, cache, ref_dr_wf=b["ev"]["dr_wf"])
                        combo_rows.append(_fmt_row(f"{bname}__{g1n}__ModeA_{ifn}_Lag{l1}_{l2}", "GRAND_COMBO", ev_ma, b["ev"], {"base": bname, "gem": f"{g1n}+{ifn}", "mode": f"Ortho_ModeA_Lag{l1}_{l2}"}))

    # Redlines (bootstrap consecutive-loss streaks on sequential single-slot trades)
    g1_sj114_ss = h3.dedupe_single_slot(g1_strict)
    g1_sj120_ss = h3.dedupe_single_slot(g1_strict[g1_strict["score"] >= 120.0])
    redlines = {
        "G1_FixPIT_120": h3.bootstrap_streak_redline(g1_pq[(g1_pq["variant"] == "G1_FixPIT_120") & (g1_pq["is_single_slot"])]["net_ret"].to_numpy(float)),
        "G1_StrictJianchi_114": h3.bootstrap_streak_redline(g1_sj114_ss["net_ret"].to_numpy(float)),
        "G1_StrictJianchi_120": h3.bootstrap_streak_redline(g1_sj120_ss["net_ret"].to_numpy(float)),
        "P_IF_3x_V3EOD_ge65_H3_SL2": h3.bootstrap_streak_redline(g4_pq[g4_pq["variant"] == "P_IF_3x_V3EOD_ge65_H3_SL2"]["net_ret"].to_numpy(float)),
        "P_IF_5x_V3EOD_ge65_H3_SL2": h3.bootstrap_streak_redline(g4_pq[g4_pq["variant"] == "P_IF_5x_V3EOD_ge65_H3_SL2"]["net_ret"].to_numpy(float)),
    }
    # Merge all summary CSVs and JSON
    s2a = pd.read_csv(f"{w2.RD048_DIR}/_step2a_gem1_summary.csv"); s2a["group"] = "GEM1_PERM"
    s2b = pd.read_csv(f"{w2.RD048_DIR}/_step2b_gem2_summary.csv"); s2b["group"] = "GEM2_USMAP"
    with open(f"{w2.RD048_DIR}/_step2a_results.json") as f:
        s2a_j = json.load(f)
    s2a_g3 = pd.DataFrame(s2a_j["gem3_stress"]); s2a_g3["group"] = "GEM3_STRESS"
    all_df = pd.concat([s2a, s2b, s2a_g3, pd.DataFrame(rows_a), pd.DataFrame(rows_b), pd.DataFrame(combo_rows), pd.DataFrame(combo_slip)], ignore_index=True)
    all_df.to_csv(f"{w2.RD048_DIR}/rd048_integration_summary.csv", index=False)

    f2a = pd.read_csv(f"{w2.RD048_DIR}/_step2a_gem1_forensics.csv")
    f2b = pd.read_csv(f"{w2.RD048_DIR}/_step2b_gem2_forensics.csv")
    pd.concat([f2a, f2b, pd.DataFrame(forensics)], ignore_index=True).to_csv(f"{w2.RD048_DIR}/rd048_crowding_forensics.csv", index=False)

    with open(f"{w2.RD048_DIR}/_step1_redteam_audit.json") as f:
        s1_j = json.load(f)
    master = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "baselines_rd038_exact": {b: {"windows": bases[b]["ev"]["windows"], "mtm_diff_5y": bases[b]["ev"]["mtm_diff_5y"]} for b in bases},
        "step1_redteam_wave1_audit": s1_j,
        "gem4_mode_a": rows_a, "gem4_mode_b": rows_b, "gem4_crash_comovement": comov,
        "orthogonal_grand_combos": combo_rows, "combo_slippage": combo_slip, "stop_redlines": redlines,
        "post_1116_if_trade18": g4_pq[(g4_pq["variant"].isin(["P_IF_3x_V3EOD_ge65_H3_SL2", "P_IF_5x_V3EOD_ge65_H3_SL2"])) & (g4_pq["buy_date"] > "2026-11-16")][["variant", "buy_date", "exit_date", "net_ret"]].to_dict("records"),
        "elapsed_sec": round(time.time() - t0, 2), "rss_mb": w2.rss_mb(),
    }
    with open(f"{w2.RD048_DIR}/rd048_master_audit.json", "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False, indent=2)
    print(f"Step 3 DONE in {time.time()-t0:.1f}s | RSS={w2.rss_mb()} MB | total_rows={len(all_df)}")

if __name__ == "__main__":
    main()
