#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Additional drift, tail-switch, and 6x6 diagnostics for 1to2, 2to3, 3to4, high, pry."""
import bisect, pickle, sqlite3
from datetime import datetime, timedelta
import numpy as np, pandas as pd
from mod_common import SIM, all_windows_metrics

def audit_extra_diagnostics(sh300, all_dts, hf_1to2, inv_1to2, sim_cache_1to2, run_1to2_fn,
                            a76_dts, fb20_dts, mkt20_dt_cln, mkt20_zt_cln) -> dict:
    # 1. 1to2 buy-date close 20cm_dt >= 3 tail switch & mcap yearly median & xq>=4 detail
    _, base_1s, _, _ = run_1to2_fn(hf_1to2, inv_1to2, sim_cache_1to2, np.zeros(len(hf_1to2)))
    dt3_hits = [{"buy_date": t["buy_date"], "code": t["code"], "name": t["name"],
                 "mkt20_dt": int(mkt20_dt_cln.get(t["buy_date"], 0)), "net_ret_pct": round(t["net_ret"] * 100, 2)}
                for t in base_1s if mkt20_dt_cln.get(t["buy_date"], 0) >= 3]
    hf_1to2_cp = hf_1to2[hf_1to2["gate_ok"]].copy()
    hf_1to2_cp["yr"] = hf_1to2_cp["d2_dt"].str[:4]
    mcap_1to2_yr = {y: {"n": int(len(g)), "med_mcap": round(float(g["mcap"].median()), 1),
                        "gt90_pct": round(float((g["mcap"] > 90).mean() * 100), 1)}
                    for y, g in hf_1to2_cp.groupby("yr")}

    # 2. 1to2 a76 threshold sensitivity inside equal_sum(-12,-12)
    s20 = pd.read_csv(f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack/final_v11_all_scored_signals.csv", dtype={"c6": str})
    m_cln = hf_1to2["d2_dt"].isin(fb20_dts).to_numpy()
    eq_sens = []
    for th in (72, 74, 76, 78, 80):
        dts_th = set(s20[s20["score"] >= th]["buy_date"].astype(str))
        _, tr_s, _, eq_s = run_1to2_fn(hf_1to2, inv_1to2, sim_cache_1to2,
                                       np.where(hf_1to2["d2_dt"].isin(dts_th).to_numpy(), -12.0, 0.0) + np.where(m_cln, -12.0, 0.0))
        eq_sens.append({"a76_thr": th, "signal_days": len(dts_th), "windows": all_windows_metrics(tr_s, eq_s, sh300, all_dts)})

    # 3. 2to3 hit-subset stats + 2025-2026 Xueqiu rescued trades
    p23 = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry/pool_2to3_full_clean.csv", dtype={"code": str})
    p23["code"] = p23["code"].str.zfill(6)
    c23 = pickle.load(open(f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_2to3_pit_20261116.pkl", "rb"))
    ga = c23["gated_all"].copy(); ga["code"] = ga["code"].astype(str).str.zfill(6)
    m23 = p23.merge(ga[["buy_date", "code", "xq_cnt_tot", "d2_seal_amt_ratio"]].drop_duplicates(["buy_date", "code"]), on=["buy_date", "code"], how="left")
    m23["mkt20_zt_sig"] = m23["sig_date"].astype(str).map(mkt20_zt_cln).fillna(0).astype(int)
    m23["sr_10_25_green"] = m23["d2_seal_amt_ratio"].between(0.10, 0.25) & (m23["open_pct"] < 0.0)
    orig_xq = np.where(m23["xq_cnt_tot"] == 0, 0.0, np.where(m23["xq_cnt_tot"] >= 4, -18.0, -10.0))
    resc23 = m23[(m23["buy_date"] >= "2025-01-01") & (m23["base_score"] < 90.0) & ((m23["base_score"] - orig_xq) >= 90.0)]
    zt16_pass = m23[(m23["base_score"] >= 90.0) & (m23["mkt20_zt_sig"] >= 16)]
    sr_pass = m23[(m23["base_score"] >= 90.0) & m23["sr_10_25_green"]]

    # 4. 3to4 2025-2026 Xueqiu rescued trades
    p34 = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high/pool_3to4_full_clean.csv", dtype={"code": str})
    p34["code"] = p34["code"].str.zfill(6)
    c34 = pickle.load(open(f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4/pit_exit_cache_full.pkl", "rb"))
    cd34 = c34["cand_df"].copy(); cd34["code"] = cd34["code"].astype(str).str.zfill(6)
    m34 = p34.merge(cd34[["buy_date", "code", "xq_cnt_2d"]].drop_duplicates(["buy_date", "code"]), on=["buy_date", "code"], how="left")
    resc34 = m34[(m34["buy_date"] >= "2025-01-01") & (m34["xq_cnt_2d"] >= 4) & (m34["base_score"] < 90.0) & ((m34["base_score"] + 15.0) >= 90.0)]

    # 5. high V5.1 & pry V2.1 Xueqiu 2d & mcap yearly drift
    phd = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high/pool_high_full_clean.csv", dtype={"code": str})
    ppr = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry/pool_pry_full_clean.csv", dtype={"code": str})
    phd["code"] = phd["code"].str.zfill(6); ppr["code"] = ppr["code"].str.zfill(6)
    all_c6 = sorted(set(phd["code"]) | set(ppr["code"]))
    qm = ",".join("?" * len(all_c6))
    xq_m = {}
    con_x = sqlite3.connect(f"file:{SIM}/data/xueqiu_guba_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con_x.execute(f"SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE substr(symbol,1,6) IN ({qm})", all_c6):
        xq_m.setdefault(str(sym)[:6].zfill(6), []).append((str(cts)[:19], str(pid).replace("xq_", "")))
    con_x.close()
    con_c = sqlite3.connect(f"file:{SIM}/data/astock_community_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con_c.execute(f"SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND substr(symbol,1,6) IN ({qm})", all_c6):
        xq_m.setdefault(str(sym)[:6].zfill(6), []).append((str(cts)[:19], str(pid).replace("xq_", "")))
    con_c.close()
    xq_ts = {}
    for c6, arr in xq_m.items():
        seen = {}
        for ts, pid in arr:
            if pid not in seen: seen[pid] = ts
        xq_ts[c6] = sorted(seen.values())
    def _cnt_xq(c6, bdt):
        arr = xq_ts.get(c6, [])
        d0 = (datetime.strptime(bdt, "%Y-%m-%d") - timedelta(days=2)).strftime("%Y-%m-%d 00:00:00")
        return max(0, bisect.bisect_left(arr, f"{bdt} 09:00:00") - bisect.bisect_left(arr, d0)) if arr else 0
    phd["xq_2d"] = [_cnt_xq(r.code, r.buy_date) for r in phd.itertuples(index=False)]
    ppr["xq_2d"] = [_cnt_xq(r.code, r.buy_date) for r in ppr.itertuples(index=False)]

    return {
        "1to2_mcap_yearly": mcap_1to2_yr,
        "1to2_buy20dt3_hits": dt3_hits,
        "1to2_equal_sum_a76_thr_sensitivity": eq_sens,
        "2to3_subset_checks": {
            "mkt20_zt_ge16_pass": {"n": int(len(zt16_pass)), "wr_pct": round(float((zt16_pass["net_ret"] > 0).mean() * 100), 2),
                                   "mean_pct": round(float(zt16_pass["net_ret"].mean() * 100), 2)},
            "sr_10_25_green_pass": {"n": int(len(sr_pass)), "wr_pct": round(float((sr_pass["net_ret"] > 0).mean() * 100), 2),
                                    "mean_pct": round(float(sr_pass["net_ret"].mean() * 100), 2)},
            "xq_2526_rescued": {"n": int(len(resc23)), "wr_pct": round(float((resc23["net_ret"] > 0).mean() * 100), 2),
                                "mean_pct": round(float(resc23["net_ret"].mean() * 100), 2)},
        },
        "3to4_xq_2526_rescued": {"n": int(len(resc34)), "wr_pct": round(float((resc34["net_ret"] > 0).mean() * 100), 2),
                                 "mean_pct": round(float(resc34["net_ret"].mean() * 100), 2)},
        "high_v51_xq_audit": {"total_rows": int(len(phd)), "xq_ge4_total": int((phd["xq_2d"] >= 4).sum()),
                              "xq_ge4_pass88": int(((phd["base_score"] >= 88) & (phd["xq_2d"] >= 4)).sum())},
        "pry_v21_xq_audit": {"total_rows": int(len(ppr)), "xq_ge4_total": int((ppr["xq_2d"] >= 4).sum()),
                             "xq_ge4_pass165": int(((ppr["base_score"] >= 165) & (ppr["xq_2d"] >= 4)).sum())},
    }
