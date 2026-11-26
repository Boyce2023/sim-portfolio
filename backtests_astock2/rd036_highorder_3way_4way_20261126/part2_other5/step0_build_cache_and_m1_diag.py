#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD036-B Step 0: Build cache, verify 100% V20 baseline parity & exact daily MTM,
and run Module 1 Deep Diagnostic:
  - Cold Day (`mkt10 < 50`, plus `<40/<45/<55`) vs Active Day (`>= 50`) stratified performance
    across all 5 strategies (`1to2`, `2to3`, `3to4`, `high`, `pry`) on candidate pool + V20 slot trades
  - Native atomic factor red/yellow-light audit specifically comparing Cold vs Active & Recent(25-26) vs Early(21-24)

Zero yfinance (D12). Peak RSS < 2 GB.
"""
import json
import os
import sys
import time
import numpy as np
import pandas as pd

DIR = os.path.dirname(os.path.abspath(__file__))
if DIR not in sys.path:
    sys.path.insert(0, DIR)

import _common_rd036 as cm
import _wf_core as wfc


def strat_regime_stats(df_sub: pd.DataFrame, ret_col: str = "net_ret_030") -> dict:
    if df_sub.empty:
        return {"n": 0, "wr_pct": 0.0, "mean_pct": 0.0, "plr": 0.0, "nav": 1.0}
    r = df_sub[ret_col].to_numpy(float)
    w, l = r[r > 0], r[r <= 0]
    wr = float((r > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    return {
        "n": int(len(r)),
        "days": int(df_sub["buy_date"].nunique()),
        "wr_pct": round(wr, 2),
        "mean_pct": round(float(r.mean() * 100.0), 2),
        "plr": round(plr, 2),
        "nav": round(float(np.prod(1.0 + r)), 4),
    }


def main():
    t0 = time.time()
    bundle = cm.build_or_load_cache(force_rebuild=True)
    print(f"[Cache built in {time.time()-t0:.1f}s] RSS={cm.rss_mb()} MB")
    print("Parity 0.20%:", json.dumps(bundle["parity_020"], ensure_ascii=False))
    bc = bundle["base_comb_030"]
    print(f"V20 Combined WF (0.30%): n={bc['n']}, nav={bc['nav_wf']}, sh={bc['sharpe']}, mdd={bc['mdd_pct']}%, 2526={bc['nav_2526']}, y26={bc['nav_y26']}, 26h2={bc['nav_26h2']}")

    # 1. Baseline 0.30% / 0.50% / 0.80% / >=2亿 for all 5 strategies
    base_rows = []
    m1_diag = {"baseline_wf_030": {}, "cold_vs_active_stratified": {}, "native_atom_cold_vs_active": {}}

    for st in cm.OTHER5:
        df = bundle["pools"][st]
        ps_wf, sl_wf = cm.sim_strategy(st, df, df["orig_score"].to_numpy(float), wf_only=True)
        row_b, _ = cm.evaluate_variant_complete(bundle, st, "M0_Baseline", "V20_Baseline_030", ps_wf, sl_wf, perm_n=1000)
        base_rows.append(row_b)
        m1_diag["baseline_wf_030"][st] = row_b
        print(f"  Base {st:4s} WF: n={row_b['n_trades']:3d}, wr={row_b['wr_pct']:5.1f}%, nav={row_b['nav_wf']:7.3f}x, sh={row_b['exact_mtm_sharpe']:5.3f}, mdd={row_b['mdd_pct']:5.1f}%, 2526={row_b['nav_2526']:6.2f}x, y26={row_b['nav_2026']:5.2f}x, 26h2={row_b['nav_26h2']:5.2f}x, 80bps={row_b['nav_80bps']:6.2f}x, liq2y={row_b['n_liq2yi']}/{row_b['nav_liq2yi']:6.2f}x")

        # 2. Cold vs Active stratified diagnostics (Candidate Pool + Passed Pool + V20 Slot Trades)
        df_buy = df[df["can_buy_hygiene"]].copy()
        df_wf_buy = df_buy[df_buy["buy_date"].between(cm.WF_START, cm.WF_END)].copy()
        sl_wf_enriched = sl_wf.copy()
        if "mkt10_zt_est_t1" not in sl_wf_enriched.columns:
            sl_wf_enriched["mkt10_zt_est_t1"] = sl_wf_enriched["L1_zt_cnt_t1"] - sl_wf_enriched["mkt20_zt_cnt_t1"]

        reg_out = {}
        for cut in (40, 45, 50, 55):
            # All buyable WF candidates
            c_cold = df_wf_buy[df_wf_buy["mkt10_zt_est_t1"] < cut]
            c_act = df_wf_buy[df_wf_buy["mkt10_zt_est_t1"] >= cut]
            # V20 passing candidates
            p_cold = ps_wf[ps_wf["mkt10_zt_est_t1"] < cut]
            p_act = ps_wf[ps_wf["mkt10_zt_est_t1"] >= cut]
            # V20 slot trades (WF)
            s_cold = sl_wf_enriched[sl_wf_enriched["mkt10_zt_est_t1"] < cut]
            s_act = sl_wf_enriched[sl_wf_enriched["mkt10_zt_est_t1"] >= cut]
            # V20 slot trades (Full 5Y for larger N on high/pry)
            _, sl_5y = cm.sim_strategy(st, df, df["orig_score"].to_numpy(float), wf_only=False)
            s5_cold = sl_5y[sl_5y["mkt10_zt_est_t1"] < cut]
            s5_act = sl_5y[sl_5y["mkt10_zt_est_t1"] >= cut]
            # Recent 25-26 slot trades
            s25_cold = s_cold[s_cold["buy_date"] >= "2025-01-01"]
            s25_act = s_act[s_act["buy_date"] >= "2025-01-01"]
            reg_out[f"cut_{cut}"] = {
                "wf_cands_cold": strat_regime_stats(c_cold),
                "wf_cands_active": strat_regime_stats(c_act),
                "wf_pass_cold": strat_regime_stats(p_cold),
                "wf_pass_active": strat_regime_stats(p_act),
                "wf_slot_cold": strat_regime_stats(s_cold),
                "wf_slot_active": strat_regime_stats(s_act),
                "full5y_slot_cold": strat_regime_stats(s5_cold),
                "full5y_slot_active": strat_regime_stats(s5_act),
                "y2526_slot_cold": strat_regime_stats(s25_cold),
                "y2526_slot_active": strat_regime_stats(s25_act),
            }
        m1_diag["cold_vs_active_stratified"][st] = reg_out

        # 3. Native Atomic Factor Red/Yellow Light Audit: Cold (<50) vs Active (>=50) & Recent vs Early
        acols = bundle["atom_info"][st]["cols"]
        amat = bundle["atom_info"][st]["contrib_mat"]
        buy_m = df["can_buy_hygiene"].to_numpy(bool)
        is_wf = df["buy_date"].between(cm.WF_START, cm.WF_END).to_numpy(bool)
        is_cold50 = (df["mkt10_zt_est_t1"].to_numpy(float) < 50.0)
        is_rec = (df["buy_date"].to_numpy(str) >= "2025-01-01")
        rets = df["net_ret_030"].to_numpy(float)
        wins = (rets > 0.0).astype(float)
        uniq_dts = sorted(df["buy_date"].unique().tolist())
        dt_map = {d: i for i, d in enumerate(uniq_dts)}
        day_ids = np.array([dt_map[d] for d in df["buy_date"]], dtype=np.int32)

        af_reports = []
        for j, cname in enumerate(acols):
            val = amat[:, j]
            def _sub_stat(m_sub):
                m_u = buy_m & m_sub
                if m_u.sum() < 8 or np.std(val[m_u]) < 1e-12:
                    return {"n": int(m_u.sum()), "t": None, "pos_n": 0, "pos_wr": None, "pos_mean": None, "zero_mean": None}
                rv, wv, dv, xv = rets[m_u], wins[m_u], day_ids[m_u], val[m_u]
                mu0, wr0 = float(rv.mean()), float(wv.mean())
                sdr = max(1e-5, float(rv.std(ddof=1)))
                u = 0.6 * (rv - mu0) / sdr + 0.4 * (wv - wr0) / 0.25
                tc = wfc._cluster_t_stat(u, xv, dv)
                # Active trigger (>0 for bonus, !=0 for general)
                pm = xv > 0 if np.max(xv) > 0 else (xv < 0)
                zm = ~pm
                return {
                    "n": int(m_u.sum()),
                    "t": round(float(tc), 3),
                    "pos_n": int(pm.sum()),
                    "pos_wr": round(float(wv[pm].mean() * 100.0), 1) if pm.any() else None,
                    "pos_mean": round(float(rv[pm].mean() * 100.0), 2) if pm.any() else None,
                    "zero_mean": round(float(rv[zm].mean() * 100.0), 2) if zm.any() else None,
                }

            st_all = _sub_stat(np.ones(len(df), dtype=bool))
            st_cold = _sub_stat(is_cold50)
            st_act = _sub_stat(~is_cold50)
            st_rec = _sub_stat(is_rec)
            st_rec_cold = _sub_stat(is_rec & is_cold50)
            af_reports.append({
                "atom": cname,
                "mean_pts": round(float(val[buy_m].mean()), 2),
                "min_pts": round(float(val[buy_m].min()), 1),
                "max_pts": round(float(val[buy_m].max()), 1),
                "all_5y": st_all,
                "cold50_5y": st_cold,
                "active50_5y": st_act,
                "recent_2526": st_rec,
                "recent_cold50": st_rec_cold,
            })
        # Sort by cold50 t ascending (worst cold-day saboteurs first!)
        af_reports.sort(key=lambda x: (x["cold50_5y"]["t"] if x["cold50_5y"]["t"] is not None else 999.0))
        m1_diag["native_atom_cold_vs_active"][st] = af_reports

    out_json = f"{cm.CACHE_DIR}/m1_diag.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(m1_diag), f, ensure_ascii=False, indent=2)

    print("\n=== Cold (<50) vs Active (>=50) WF Slot Summary ===")
    for st in cm.OTHER5:
        r50 = m1_diag["cold_vs_active_stratified"][st]["cut_50"]
        sc, sa = r50["wf_slot_cold"], r50["wf_slot_active"]
        pc, pa_ = r50["wf_pass_cold"], r50["wf_pass_active"]
        print(f"  {st:4s} | Slot Cold(<50): n={sc['n']:2d} wr={sc['wr_pct']:5.1f}% mean={sc['mean_pct']:+5.2f}% nav={sc['nav']:6.2f}x | Slot Act(>=50): n={sa['n']:2d} wr={sa['wr_pct']:5.1f}% mean={sa['mean_pct']:+5.2f}% nav={sa['nav']:6.2f}x")
        print(f"       | Pass Cold(<50): n={pc['n']:3d} wr={pc['wr_pct']:5.1f}% mean={pc['mean_pct']:+5.2f}% | Pass Act(>=50): n={pa_['n']:3d} wr={pa_['wr_pct']:5.1f}% mean={pa_['mean_pct']:+5.2f}%")
        bad_atoms = [a for a in m1_diag["native_atom_cold_vs_active"][st] if a["cold50_5y"]["t"] is not None and a["cold50_5y"]["t"] < -0.5]
        print(f"       | Cold-weak atoms (t_cold<-0.5): {[(a['atom'], a['cold50_5y']['t'], a['active50_5y']['t'], a['recent_2526']['t']) for a in bad_atoms[:5]]}")
    print(f"[Step 0 DONE in {time.time()-t0:.1f}s] Peak RSS={cm.rss_mb()} MB")


if __name__ == "__main__":
    main()
