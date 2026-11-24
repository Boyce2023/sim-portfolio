#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Full-pool audits & drift checks for 2to3 V2.1, 3to4 V4.1, high V5.1, pry V2.1."""
import pickle, sqlite3, sys, numpy as np, pandas as pd
from mod_common import SIM, all_windows_metrics, hlz_and_dsr150

def _sim_2to3(df, sh300, all_dts):
    sub = df[df["sc_adj"] >= 90.0].sort_values(["buy_date", "sc_adj", "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True])
    taken, fdt, fhh = [], "", 0
    for r in sub.itertuples(index=False):
        if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
            taken.append({"buy_date": r.buy_date, "exit_date": r.exit_date, "code": r.code, "name": r.name, "net_ret": float(r.net_ret)})
            fdt, fhh = r.exit_date, int(r.exit_hhmm)
    eq_d = [(d, float(g["net_ret"].mean())) for d, g in sub.groupby("buy_date", sort=True)]
    tv, dsr = hlz_and_dsr150(taken, sh300, all_dts)
    return {"windows": all_windows_metrics(taken, eq_d, sh300, all_dts), "hlz_t": tv, "dsr_m150": dsr, "raw_pass": int(len(sub))}

def audit_2to3(sh300, all_dts, a76_dts, high_dts, t12_dts, mkt20_zt_cln):
    p23 = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry/pool_2to3_full_clean.csv", dtype={"code": str})
    p23["code"] = p23["code"].str.zfill(6)
    c23 = pickle.load(open(f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_2to3_pit_20261116.pkl", "rb"))
    ga = c23["gated_all"].copy(); ga["code"] = ga["code"].astype(str).str.zfill(6)
    m = p23.merge(ga[["buy_date", "code", "xq_cnt_tot", "d2_seal_amt_ratio"]].drop_duplicates(["buy_date", "code"]), on=["buy_date", "code"], how="left")
    prev_td = {all_dts[i]: all_dts[i - 1] for i in range(1, len(all_dts))}
    m["sr_10_25_green"] = m["d2_seal_amt_ratio"].between(0.10, 0.25) & (m["open_pct"] < 0.0)
    m["mkt20_zt_sig"] = m["sig_date"].astype(str).map(mkt20_zt_cln).fillna(0).astype(int)
    m["sc_adj"] = m["base_score"].to_numpy()
    base_res = _sim_2to3(m, sh300, all_dts)

    sr_grid = []
    for w in (0, 4, 6, 8, 10, 12):
        m["sc_adj"] = m["base_score"] - np.where(m["sr_10_25_green"], float(w), 0.0)
        sr_grid.append({"weight": -w, **_sim_2to3(m, sh300, all_dts)})

    zt_grid = []
    for w in (0, 4, 6, 8):
        m["sc_adj"] = m["base_score"] - np.where(m["mkt20_zt_sig"] >= 16, float(w), 0.0)
        zt_grid.append({"weight": -w, **_sim_2to3(m, sh300, all_dts)})

    # Xueqiu P3_1 drift (0 / -10 / -18)
    orig_xq_pen = np.where(m["xq_cnt_tot"] == 0, 0.0, np.where(m["xq_cnt_tot"] >= 4, -18.0, -10.0))
    m["yr"] = m["buy_date"].str[:4]
    yr_xq = {y: {"n": int(len(g)), "ge4_pct": round(float((g["xq_cnt_tot"] >= 4).mean() * 100), 1), "mean_xq": round(float(g["xq_cnt_tot"].mean()), 2)} for y, g in m.groupby("yr")}
    # Rolling PIT q90/q95/mean_scaled on daily xq_cnt_tot
    dxq = m.groupby("buy_date")["xq_cnt_tot"].agg(q90=lambda s: np.quantile(s, 0.90), q95=lambda s: np.quantile(s, 0.95), mn="mean").sort_index()
    rq = dxq.shift(1).rolling(60, min_periods=20).mean().ffill().bfill()
    q95_thr = np.maximum(2.0, m["buy_date"].map(rq["q95"].to_dict()).fillna(4.0).to_numpy())
    base_mn = max(0.05, float(dxq["mn"].iloc[:60].mean()))
    sc_fac = np.maximum(1.0, m["buy_date"].map(rq["mn"].to_dict()).fillna(base_mn).to_numpy() / base_mn)
    xq_v = m["xq_cnt_tot"].to_numpy()
    xq_variants = []
    for lbl, np_pen in [("orig(0/-10/-18)", orig_xq_pen), ("mild(0/-5/-10)", np.where(xq_v == 0, 0.0, np.where(xq_v >= 4, -10.0, -5.0))),
                        ("mild(0/-4/-8)", np.where(xq_v == 0, 0.0, np.where(xq_v >= 4, -8.0, -4.0))),
                        ("zero_xq(0/0/0)", np.zeros(len(m))),
                        ("roll60_q95_ge2", np.where(xq_v == 0, 0.0, np.where(xq_v >= q95_thr, -18.0, -10.0))),
                        ("roll60_mean_scaled", np.where(xq_v == 0, 0.0, np.where(xq_v >= 4.0 * sc_fac, -18.0, np.where(xq_v >= 1.0 * sc_fac, -10.0, 0.0))))]:
        m["sc_adj"] = m["base_score"] - orig_xq_pen + np_pen
        xq_variants.append({"variant": lbl, **_sim_2to3(m, sh300, all_dts)})

    inter_tests = {}
    for ilbl, sset in [("1to2_prev", t12_dts), ("high_prev", high_dts)]:
        hit = m["buy_date"].astype(str).map(lambda d: prev_td.get(d, "") in sset).to_numpy()
        inter_tests[ilbl] = []
        for w in (4, 6, 8, 10):
            m["sc_adj"] = m["base_score"] - np.where(hit, float(w), 0.0)
            inter_tests[ilbl].append({"weight": -w, **_sim_2to3(m, sh300, all_dts)})

    return {"baseline": base_res, "sr_10_25_green_grid": sr_grid, "mkt20_zt_ge16_grid": zt_grid,
            "xueqiu_yearly_rates": yr_xq, "xueqiu_variants": xq_variants, "interaction_tests": inter_tests, "verdict": "KEEP_V21_UNCHANGED"}

def _sim_3to4(df, sh300, all_dts):
    sub = df[df["sc_adj"] >= 90.0].copy()
    sub["prio"] = sub["sc_adj"] * 10.0 + sub["prio_tie"] * 0.1
    sub = sub.sort_values(["buy_date", "buy_hhmm", "prio", "code"], ascending=[True, True, False, True])
    taken, fdt, fhh = [], "", 0
    for r in sub.itertuples(index=False):
        if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
            taken.append({"buy_date": r.buy_date, "exit_date": r.exit_date, "code": r.code, "name": r.name, "net_ret": float(r.net_ret)})
            fdt, fhh = r.exit_date, int(r.exit_hhmm)
    eq_d = [(d, float(g["net_ret"].mean())) for d, g in sub.groupby("buy_date", sort=True)]
    tv, dsr = hlz_and_dsr150(taken, sh300, all_dts)
    return {"windows": all_windows_metrics(taken, eq_d, sh300, all_dts), "hlz_t": tv, "dsr_m150": dsr, "raw_pass": int(len(sub))}

def audit_3to4(sh300, all_dts, a76_dts, mkt20_dt_cln):
    p34 = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high/pool_3to4_full_clean.csv", dtype={"code": str})
    p34["code"] = p34["code"].str.zfill(6)
    c34 = pickle.load(open(f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4/pit_exit_cache_full.pkl", "rb"))
    cd = c34["cand_df"].copy(); cd["code"] = cd["code"].astype(str).str.zfill(6)
    m = p34.merge(cd[["buy_date", "code", "xq_cnt_2d"]].drop_duplicates(["buy_date", "code"]), on=["buy_date", "code"], how="left")
    m["sc_adj"] = m["base_score"].to_numpy()
    base_res = _sim_3to4(m, sh300, all_dts)

    a76_grid = []
    hit_a76 = m["buy_date"].astype(str).isin(a76_dts).to_numpy()
    for w in (0, 3, 5, 7, 10):
        m["sc_adj"] = m["base_score"] - np.where(hit_a76, float(w), 0.0)
        a76_grid.append({"weight": -w, **_sim_3to4(m, sh300, all_dts)})

    m["yr"] = m["buy_date"].str[:4]
    yr_xq = {y: {"n": int(len(g)), "ge4_pct": round(float((g["xq_cnt_2d"] >= 4).mean() * 100), 1), "mean_xq": round(float(g["xq_cnt_2d"].mean()), 2)} for y, g in m.groupby("yr")}
    orig_u02 = np.where(m["xq_cnt_2d"] >= 4, -15.0, 0.0)
    dx34 = m.groupby("buy_date")["xq_cnt_2d"].agg(q95=lambda s: np.quantile(s, 0.95), mn="mean").sort_index()
    rq34 = dx34.shift(1).rolling(30, min_periods=10).mean().ffill().bfill()
    q95_34 = np.maximum(4.0, m["buy_date"].map(rq34["q95"].to_dict()).fillna(4.0).to_numpy())
    bmn34 = max(0.20, float(dx34["mn"].iloc[:30].mean()))
    sf34 = np.maximum(1.0, m["buy_date"].map(rq34["mn"].to_dict()).fillna(bmn34).to_numpy() / bmn34)
    xv34 = m["xq_cnt_2d"].to_numpy()
    xq_variants = []
    for lbl, pen in [("orig(-15)", orig_u02), ("mild(-10)", np.where(xv34 >= 4, -10.0, 0.0)),
                     ("mild(-5)", np.where(xv34 >= 4, -5.0, 0.0)), ("zero(0)", np.zeros(len(m))),
                     ("roll30_q95_ge4", np.where(xv34 >= q95_34, -15.0, 0.0)),
                     ("roll30_mean_scaled", np.where(xv34 >= 4.0 * sf34, -15.0, 0.0))]:
        m["sc_adj"] = m["base_score"] - orig_u02 + pen
        xq_variants.append({"variant": lbl, **_sim_3to4(m, sh300, all_dts)})

    # 8th holding risk switch via exit_factor_engine
    sys.path.insert(0, f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4")
    import exit_factor_engine as efe34, step4_audit_trunc_and_report as s434
    states34 = efe34.precompute_trade_day_states(c34, min_score=90.0)
    bdt_m = {e["idx"]: e["buy_date"] for e in c34["buy_entries"]}
    for idx, kmap in states34.items():
        b_hit = mkt20_dt_cln.get(bdt_m[idx], 0) >= 3
        for _, st in kmap.items():
            st["bdt_20dt3"] = b_hit
            st["prev_20dt3"] = mkt20_dt_cln.get(st.get("d_prev", ""), 0) >= 3
    rb = efe34.evaluate_rule(c34, states34, lambda st, ctx: {"tight_1345_thr": 0.070 if s434.risk7_score(st) >= 1 else 0.050}, "base", 90.0)["raw_df"]
    r8 = efe34.evaluate_rule(c34, states34, lambda st, ctx: {"tight_1345_thr": 0.070 if (s434.risk7_score(st) >= 1 or st.get("bdt_20dt3", False)) else 0.050}, "r8", 90.0)["raw_df"]
    diff_cnt = int((np.abs(rb["net_ret"].to_numpy() - r8["net_ret"].to_numpy()) > 1e-6).sum())
    return {"baseline": base_res, "a76_same_grid": a76_grid, "xueqiu_yearly_rates": yr_xq,
            "xueqiu_variants": xq_variants, "risk8_buy20dt3_changed_trades": diff_cnt, "verdict": "KEEP_V41_UNCHANGED"}

def audit_high_and_pry(sh300, all_dts, a76_dts):
    phd = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high/pool_high_full_clean.csv", dtype={"code": str})
    phd["code"] = phd["code"].str.zfill(6)
    hit_a76 = phd["buy_date"].astype(str).isin(a76_dts).to_numpy()
    high_grids = {}
    for use_cb in (False, True):
        res_cb = []
        for w in (0, 3, 5, 6, 8):
            phd["sc_adj"] = phd["base_score"] + np.where(hit_a76, float(w), 0.0)
            sub = phd[phd["sc_adj"] >= 88.0].sort_values(["buy_date", "sc_adj", "code"], ascending=[True, False, True])
            taken, fd, peo, cl, sk = [], "", False, 0, False
            for r in sub.itertuples(index=False):
                if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not bool(r.b_open_h))):
                    if use_cb and sk:
                        fd, peo = str(r.exit_date), bool(r.eo)
                        if float(r.net_ret) > 0: sk, cl = False, 0
                        continue
                    taken.append({"buy_date": r.buy_date, "exit_date": r.exit_date, "code": r.code, "name": r.name, "net_ret": float(r.net_ret)})
                    fd, peo = str(r.exit_date), bool(r.eo)
                    if float(r.net_ret) < -0.02:
                        cl += 1
                        if cl >= 2: sk = True
                    elif float(r.net_ret) > 0: cl = 0
            eq_d = [(d, float(g["net_ret"].mean())) for d, g in sub.groupby("buy_date", sort=True)]
            res_cb.append({"bonus": w, "windows": all_windows_metrics(taken, eq_d, sh300, all_dts), "raw_pass": int(len(sub))})
        high_grids[f"use_cb_{use_cb}"] = res_cb

    ppr = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry/pool_pry_full_clean.csv", dtype={"code": str})
    ppr["code"] = ppr["code"].str.zfill(6)
    sub_pr = ppr[ppr["base_score"] >= 165.0].sort_values(["buy_date", "base_score", "bias10", "code"], ascending=[True, False, True, True])
    tk_pr, fdt = [], ""
    for r in sub_pr.itertuples(index=False):
        if (not fdt) or (r.buy_date > fdt):
            tk_pr.append({"buy_date": r.buy_date, "exit_date": r.exit_date, "code": r.code, "name": r.name, "net_ret": float(r.net_ret)})
            fdt = r.exit_date
    eq_pr = [(d, float(g["net_ret"].mean())) for d, g in sub_pr.groupby("buy_date", sort=True)]
    pry_res = {"baseline": {"windows": all_windows_metrics(tk_pr, eq_pr, sh300, all_dts), "raw_pass": int(len(sub_pr))},
               "total_candidate_rows": int(len(ppr)), "verdict": "KEEP_V21_UNCHANGED"}
    return {"high_v51": {**high_grids, "verdict": "KEEP_V51_UNCHANGED"}, "pry_v21": pry_res}
