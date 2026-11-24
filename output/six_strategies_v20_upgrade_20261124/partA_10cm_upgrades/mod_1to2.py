#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""1to2 V19 -> V2.0_cand full-pool reconstruction, grids, drift checks & 2025-01-01 truncation."""
import os, sys, numpy as np, pandas as pd
from mod_common import SIM, OUT_DIR, all_windows_metrics, hlz_and_dsr150, calc_cscv_pbo, build_fb20_cln_dates_pit

UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
ABL_DIR = f"{SIM}/backtests_astock/ablation_1to2_psz35_tight37_20261123"
for p in (UPG_DIR, ABL_DIR):
    if p not in sys.path: sys.path.insert(0, p)
import upgrade_1to2_pit as u12
import run_ablation as ra12

LEDGER_COLS = ["code", "name", "buy_date", "buy_hhmm", "buy_price", "exit_date", "exit_hhmm",
               "exit_price", "net_ret", "score", "tag", "sealed_2b", "exit_at_open", "d2_o_pct"]

def run_1to2_variant(hf, inv, sim_cache, sc_delta, skip_mask=None):
    inv_m = dict(inv); sc_new = inv["sc_v"] + sc_delta; inv_m["sc_v"] = sc_new
    inv_m["m_t1"] = inv["common_ok"] & inv["open_in_win"] & (inv["sp_v"] >= 45.0) & (sc_new >= inv["thr_vec"])
    nb = (~hf["notice_bad"]).to_numpy(); pac = (hf["p_sz"].to_numpy() <= 35.0) & nb; pt = (hf["d1_seal_tightness"].to_numpy() >= 37.0)
    mm = ((inv_m["m_t1"] & inv_m["pass_l1"] & inv_m["pass_l2"] & inv_m["pass_l3"] & inv_m["pass_nd_true"] & pac) | (inv_m["m_t2_base"] & inv_m["pass_l2"])) & pt
    mmon = (inv_m["common_ok"] & inv_m["wk_mask"] & hf["d2_o_pct"].between(0.015, 0.090).to_numpy() & (inv_m["sp_v"] >= 38.0)
            & (sc_new >= inv_m["thr_vec"]) & inv_m["pass_l1"] & inv_m["pass_l2"] & inv_m["pass_l3"] & inv_m["pass_nd_true"] & pac & pt)
    tot18 = mm | (mmon & (~mm))
    fb295 = (inv_m["common_ok"] & inv_m["open_in_win"] & inv_m["pass_l1"] & inv_m["pass_l2"] & inv_m["pass_l3"] & inv_m["pass_nd_true"]
             & pac & pt & np.isin(inv_m["rk_t"], [2, 3]) & (inv_m["tbrk"] == 1) & (inv_m["xq2_arr"] < 4)
             & (inv_m["pos20_arr"] <= 0.40) & inv_m["cat_ok"] & (inv_m["lh_arr"] == 0) & (~inv_m["syz_arr"]) & ((sc_new - inv_m["sc_t3_pen"]) >= 295.0))
    tot19 = tot18 | fb295
    sv = np.where(mm, sc_new + 1000.0, np.where(mmon, sc_new, sc_new + 500.0))
    dt1, dt2, dt3 = inv_m["daily_t1"], inv_m["daily_t2"], inv_m["daily_t3"]
    dom_nd, melee = set(), set()
    for d in sorted(dt1.index):
        r1 = dt1.loc[d]; r2 = dt2.loc[d] if d in dt2.index else None; r3 = dt3.loc[d] if d in dt3.index else None
        m1, m2 = float(r1["p_theme_med"]), float(r2["p_theme_med"]) if r2 is not None else 0.0
        s1, s2 = int(r1["p_sz_max"]), int(r2["p_sz_max"]) if r2 is not None else 1
        if ((m1 - m2) >= 20.0) or ((s1 >= 6) and (s1 / max(1, s2) >= 2.0)):
            sd = hf[(hf["d2_dt"] == d) & tot18]
            if not (len(sd) > 0 and (sd["plate"] == r1["plate"]).any()): dom_nd.add(d)
        if r1 is not None and r2 is not None and r3 is not None:
            m3 = float(r3["p_theme_med"])
            if (m1 - m3) <= 15.0 and max(s1, s2, int(r3["p_sz_max"])) <= 5 and min(s1, s2, int(r3["p_sz_max"])) >= 2: melee.add(d)
    sub_t = hf[tot19].copy(); sub_t["_sv"] = sv[tot19]
    bad_dts = set()
    for d, grp in sub_t.groupby("d2_dt"):
        if (grp["rk_theme"] == 1).any():
            trk = grp.sort_values("_sv", ascending=False).iloc[0]["rk_theme"]
            if pd.notna(trk) and trk >= 4: bad_dts.add(d)
    fmask = tot19 & (~hf["d2_dt"].isin(bad_dts)).to_numpy()
    dom_blk = np.array([(d in dom_nd and rk == 3) for d, rk in zip(hf["d2_dt"], hf["rk_theme"])], dtype=bool)
    mel_blk = np.array([(d in melee) and (not ((mrk <= 2) or bool(nh) or bool(hm))) for d, mrk, nh, hm in zip(hf["d2_dt"], hf["buyable_mkt_open_rk"], hf["notice_hard"], hf["is_ma"])], dtype=bool)
    fmask = fmask & (~dom_blk) & (~mel_blk)
    if skip_mask is not None: fmask = fmask & (~skip_mask)
    trk = np.where(mm, "V18_main", np.where(mmon, "V18_mon", np.where(fb295, "V19_fb_dom295", "")))
    tr1s, eq_sigs, eq_d, _, _ = ra12.run_slot_and_eq_cached(hf, fmask, sv, trk, sim_cache)
    sc_map = {(r.d2_dt, str(r.c6).zfill(6)): round(float(s_v), 1) for r, s_v in zip(hf[fmask].itertuples(index=False), sc_new[fmask])}
    for t in tr1s: t["score"] = sc_map[(t["buy_date"], t["code"])]
    return fmask, tr1s, eq_sigs, eq_d

def build_1to2_ctx_and_cache(end_dt: str):
    ctx = u12.build_signals_and_data_pit(end_dt)
    by_c, dmap = ra12.load_daily_truth_and_adj()
    ra12.enrich_local_5m_map(ctx, dmap)
    hf = ctx["hist_fb"]; inv = ra12.prepare_invariants(hf); sim_fn = ra12.make_clean_sim(ctx, by_c, dmap)
    m5y = ((hf["d2_dt"] >= u12.CANON_5Y_START) & (hf["d2_dt"] <= end_dt)).to_numpy()
    sim_cache = {}
    for r in hf[m5y & hf["is_buyable_open"].to_numpy() & hf["gate_ok"].to_numpy()].itertuples(index=False):
        tr = sim_fn(r._asdict())
        if tr is not None: sim_cache[(r.d2_dt, r.c6)] = tr
    return hf, inv, sim_cache, by_c, dmap

def run_1to2_full_audit(sh300: dict, all_dts: list) -> dict:
    hf, inv, sim_cache, _, dmap = build_1to2_ctx_and_cache(u12.DATA_END_DT)
    ref_v19 = pd.read_csv(ra12.REF_CLEAN_CSV, dtype={"code": str}); ref_v19["code"] = ref_v19["code"].str.zfill(6)
    base_mask, base_1s, base_eq_sigs, base_eq = run_1to2_variant(hf, inv, sim_cache, np.zeros(len(hf)))
    assert len(base_1s) == len(ref_v19) == 97
    max_par = max(abs(float(a["net_ret"]) - float(b.net_ret)) for a, b in zip(base_1s, ref_v19.itertuples(index=False)))
    assert max_par == 0.0, f"1to2 parity fail: {max_par}"

    s20 = pd.read_csv(f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack/final_v11_all_scored_signals.csv", dtype={"c6": str})
    p1cln = pd.read_parquet(f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit/p1_clean_candidates.parquet", columns=["f1_dt", "f1_o_pct", "mkt20_zt_cnt"])
    fb20_parq = set(p1cln[(p1cln["f1_o_pct"] <= -0.03) & (p1cln["mkt20_zt_cnt"] < 16) & (p1cln["f1_dt"] <= u12.DATA_END_DT)].groupby("f1_dt").size().loc[lambda s: s >= 2].index.astype(str))
    fb20_pit_cnt = build_fb20_cln_dates_pit(u12.DATA_END_DT)
    fb20_pit = {d for d, c in fb20_pit_cnt.items() if c >= 2}
    assert fb20_parq == fb20_pit, f"fb20_cln mismatch: {fb20_parq ^ fb20_pit}"
    m_cln = hf["d2_dt"].isin(fb20_pit).to_numpy()
    m_a76 = hf["d2_dt"].isin(set(s20[s20["score"] >= 76]["buy_date"].astype(str))).to_numpy()

    def _rec(lbl, delta, skip_m=None, strict_5m=False):
        _, tr, _, eqd = run_1to2_variant(hf, inv, sim_cache, delta, skip_m)
        cln = ra12.verify_v191_cleanliness(tr, dmap)
        if strict_5m:
            assert cln["trades_5m_full_pct"] == 100.0, (lbl, cln["missing_5m_trades"])
        tv, dsr = hlz_and_dsr150(tr, sh300, all_dts)
        return {"label": lbl, "windows": all_windows_metrics(tr, eqd, sh300, all_dts),
                "hlz_t": tv, "dsr_m150": dsr, "cleanliness": cln}, tr

    fb_grid, fb_trs = [], []
    for w in (0, 10, 15, 20, 25, 30, 35):
        r, tr = _rec(f"fb20cln(-{w})", np.where(m_cln, -float(w), 0.0), strict_5m=True); fb_grid.append(r); fb_trs.append(tr)
    fb_grid.append(_rec("fb20cln(SKIP)", np.zeros(len(hf)), skip_m=m_cln)[0])

    a76_grid, a76_trs = [], []
    for w in (0, 10, 15, 20, 25, 30):
        r, tr = _rec(f"a76(-{w})", np.where(m_a76, -float(w), 0.0)); a76_grid.append(r); a76_trs.append(tr)
    a76_grid.append(_rec("a76(SKIP)", np.zeros(len(hf)), skip_m=m_a76)[0])

    eq_grid, eq_trs = [], []
    for w in (0, 8, 10, 12, 15, 18):
        r, tr = _rec(f"equal_sum(-{w},-{w})", np.where(m_a76, -float(w), 0.0) + np.where(m_cln, -float(w), 0.0))
        eq_grid.append(r); eq_trs.append(tr)

    # Mcap drift test (plate_d2_yizi_cnt >= 1 & mcap > thr)
    old_pen = np.where((hf["plate_d2_yizi_cnt"] >= 1) & (hf["mcap"] > 90.0), -25.0, 0.0)
    zts = hf[hf["gate_ok"]][["d2_dt", "c6", "mcap"]].drop_duplicates(["d2_dt", "c6"])
    dm_q = zts.groupby("d2_dt")["mcap"].agg(p70=lambda s: np.quantile(s, 0.70), p75=lambda s: np.quantile(s, 0.75), p80=lambda s: np.quantile(s, 0.80)).sort_index()
    roll_q = dm_q.shift(1).rolling(60, min_periods=20).median().ffill().bfill()
    mcap_tests = []
    for mlbl, cond in [("mcap>90_base", hf["mcap"] > 90.0), ("mcap>120", hf["mcap"] > 120.0), ("mcap>150", hf["mcap"] > 150.0),
                       ("mcap_cancel", np.zeros(len(hf), bool)), ("roll60_p70", hf["mcap"].to_numpy() > hf["d2_dt"].map(roll_q["p70"].to_dict()).fillna(90.0).to_numpy()),
                       ("roll60_p75", hf["mcap"].to_numpy() > hf["d2_dt"].map(roll_q["p75"].to_dict()).fillna(90.0).to_numpy()),
                       ("roll60_p80", hf["mcap"].to_numpy() > hf["d2_dt"].map(roll_q["p80"].to_dict()).fillna(90.0).to_numpy())]:
        new_pen = np.where((hf["plate_d2_yizi_cnt"].to_numpy() >= 1) & np.asarray(cond, bool), -25.0, 0.0)
        mcap_tests.append(_rec(mlbl, -old_pen + new_pen)[0])

    # Xueqiu fb_dom295 drift & 20cm_dt>=3 check
    fb_no_xq = (inv["common_ok"] & inv["open_in_win"] & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"]
                & (hf["p_sz"].to_numpy() <= 35.0) & (~hf["notice_bad"]).to_numpy() & (hf["d1_seal_tightness"].to_numpy() >= 37.0)
                & np.isin(inv["rk_t"], [2, 3]) & (inv["tbrk"] == 1) & (inv["pos20_arr"] <= 0.40) & inv["cat_ok"] & (inv["lh_arr"] == 0) & (~inv["syz_arr"]) & ((inv["sc_v"] - inv["sc_t3_pen"]) >= 295.0))
    xq_vals = hf.loc[fb_no_xq & (hf["d2_dt"] >= u12.CANON_5Y_START), "xq_pre_d2"].to_numpy()

    # Select V2.0_cand: fb20cln(-25)
    cand_tr = fb_trs[4]  # w=25
    df_cand = pd.DataFrame([{k: t[k] for k in LEDGER_COLS} for t in cand_tr])
    cand_csv = f"{OUT_DIR}/ledger_1to2_v20_cand.csv"
    df_cand.to_csv(cand_csv, index=False, encoding="utf-8-sig")

    # 2025-01-01 physical truncation proof on V2.0_cand
    hf_t, inv_t, sc_t, _, _ = build_1to2_ctx_and_cache("2024-12-31")
    fb20_tr = {d for d, c in build_fb20_cln_dates_pit("2024-12-31").items() if c >= 2}
    _, tr_t, _, _ = run_1to2_variant(hf_t, inv_t, sc_t, np.where(hf_t["d2_dt"].isin(fb20_tr).to_numpy(), -25.0, 0.0))
    f24 = sorted([t for t in cand_tr if t["exit_date"] <= "2024-12-31"], key=lambda x: (x["buy_date"], x["code"]))
    t24 = sorted([t for t in tr_t if t["exit_date"] <= "2024-12-31"], key=lambda x: (x["buy_date"], x["code"]))
    assert len(f24) == len(t24)
    trunc_diff = max(abs(float(a["net_ret"]) - float(b["net_ret"])) for a, b in zip(f24, t24))
    assert trunc_diff == 0.0, f"Truncation mismatch: {trunc_diff}"

    pass_rows = [{"buy_date": r.d2_dt, "net_ret": sim_cache[(r.d2_dt, r.c6)]["net_ret"]}
                 for r in hf[base_mask & (hf["d2_dt"] >= u12.CANON_5Y_START) & (hf["d2_dt"] <= u12.DATA_END_DT)].itertuples(index=False)
                 if (r.d2_dt, r.c6) in sim_cache]
    return pd.DataFrame(pass_rows), {
        "baseline_parity_max_diff": max_par, "fb20cln_grid": fb_grid, "a76_grid": a76_grid, "equal_sum_grid": eq_grid,
        "pbo_s8_s10": {"fb20cln_1d": [calc_cscv_pbo(fb_trs[:-1], all_dts, 8), calc_cscv_pbo(fb_trs[:-1], all_dts, 10)],
                       "a76_1d": [calc_cscv_pbo(a76_trs, all_dts, 8), calc_cscv_pbo(a76_trs, all_dts, 10)],
                       "equal_sum_1d": [calc_cscv_pbo(eq_trs, all_dts, 8), calc_cscv_pbo(eq_trs, all_dts, 10)]},
        "mcap_drift_tests": mcap_tests,
        "xueqiu_fb_dom295_audit": {"rows_ignoring_xq": int(len(xq_vals)), "rows_xq_lt4": int((xq_vals < 4).sum()), "rows_xq_ge4": int((xq_vals >= 4).sum())},
        "truncation_20250101": {"trades_2021_2024": len(t24), "max_abs_diff": trunc_diff},
        "primary_cand_rule": "fb20_cln>=2 (-25 score penalty)", "primary_cand_csv": cand_csv,
    }, (hf, inv, sim_cache)
