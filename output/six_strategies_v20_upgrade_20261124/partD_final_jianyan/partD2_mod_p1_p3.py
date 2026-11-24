#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Part D2 Pillars 1, 2 & 3: All-A 5F/6F Alpha & Dual-Eco Matched Control, AC Capacity (pure compounding only), Regimes & Block Bootstrap."""
import math, os, sys
import numpy as np, pandas as pd, scipy.stats as stats
import pyarrow.dataset as ds

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
VAL5_DIR = f"{SIM}/output/five_strategies_institutional_validation_20261124"
PARTB_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partB_20cm_full_jianyan"
for p in (VAL5_DIR, PARTB_DIR):
    if p not in sys.path: sys.path.insert(0, p)

import run_part1_alpha_micro_regime as p1
import run_partB_20cm_7pillars as pb

SEED = 20261124

def build_all_a_factors(df_all: pd.DataFrame, cal_dates: list[str], all_dts: list[str], zt_tape: pd.DataFrame, csi_s: pd.Series):
    sub = df_all[df_all["dt"].isin(set(cal_dates))].copy()
    valid = (~sub["is_st_flag"]) & (sub["volume"] > 0) & (sub["vol_m1"] > 0) & sub["mcap_m1"].notna() & (sub["mcap_m1"] > 0) & sub["ret"].notna() & (sub["ret"].abs() <= 0.22)
    sv = sub[valid].copy(); sv["w_ret"] = sv["mcap_m1"] * sv["ret"]; g_dt = sv.groupby("dt")
    mkt_vw = (g_dt["w_ret"].sum() / g_dt["mcap_m1"].sum()).reindex(cal_dates).fillna(0.0)
    sv["mcap_pct"] = g_dt["mcap_m1"].rank(pct=True)
    smb = (sv[sv["mcap_pct"] <= 0.30].groupby("dt")["ret"].mean() - sv[sv["mcap_pct"] >= 0.70].groupby("dt")["ret"].mean()).reindex(cal_dates).fillna(0.0)
    sv_v = sv[sv["vol20_m1"].notna() & (sv["vol20_m1"] > 0)].copy(); sv_v["vp"] = sv_v.groupby("dt")["vol20_m1"].rank(pct=True)
    vol_f = (sv_v[sv_v["vp"] >= 0.70].groupby("dt")["ret"].mean() - sv_v[sv_v["vp"] <= 0.30].groupby("dt")["ret"].mean()).reindex(cal_dates).fillna(0.0)
    sv_l = sv[sv["turn20_m1"].notna() & (sv["turn20_m1"] > 0)].copy(); sv_l["lp"] = sv_l.groupby("dt")["turn20_m1"].rank(pct=True)
    liq_f = (sv_l[sv_l["lp"] >= 0.70].groupby("dt")["ret"].mean() - sv_l[sv_l["lp"] <= 0.30].groupby("dt")["ret"].mean()).reindex(cal_dates).fillna(0.0)

    prev_map = {d: all_dts[all_dts.index(d) - 1] for d in cal_dates}; rev_prev = {v: k for k, v in prev_map.items()}
    zt_lb = zt_tape[zt_tape["sec_code"].str.startswith(("00", "60")) & (~zt_tape["sec_name"].str.contains("ST|退", na=False)) & (zt_tape["board_count"] >= 2)][["trade_date", "sec_code"]].drop_duplicates()
    zt_lb["dt"] = zt_lb["trade_date"].map(rev_prev); zt_lb = zt_lb.dropna(subset=["dt"])
    lb_m = zt_lb.merge(sub[["c6", "dt", "ret", "open", "close", "is_yizi_zt", "volume"]].rename(columns={"c6": "sec_code"}), on=["sec_code", "dt"], how="inner")
    lb_m = lb_m[lb_m["ret"].notna() & (lb_m["ret"].abs() <= 0.22)]
    lb_c2c = lb_m.groupby("dt")["ret"].mean().reindex(cal_dates).fillna(mkt_vw) - mkt_vw
    lb_ny = lb_m[(~lb_m["is_yizi_zt"]) & (lb_m["volume"] > 0) & (lb_m["open"] > 0)].copy(); lb_ny["o2c"] = lb_ny["close"] / lb_ny["open"] - 1.0
    lb_o2c = lb_ny.groupby("dt")["o2c"].mean().reindex(cal_dates).fillna(0.0) - mkt_vw

    fb20 = sub[sub["is20"] & (~sub["is_st_flag"]) & (sub["board_cnt_m1"] == 1) & sub["ret"].notna() & (sub["ret"].abs() <= 0.22)].copy()
    fb20_c2c = fb20.groupby("dt")["ret"].mean().reindex(cal_dates).fillna(mkt_vw) - mkt_vw
    fb20_ny = fb20[(~fb20["is_yizi_zt_m1"]) & (fb20["volume"] > 0) & (fb20["open"] > 0) & (~fb20["open_is_zt"])].copy(); fb20_ny["o2c"] = fb20_ny["close"] / fb20_ny["open"] - 1.0
    fb20_o2c = fb20_ny.groupby("dt")["o2c"].mean().reindex(cal_dates).fillna(mkt_vw) - mkt_vw

    fac_5f = pd.DataFrame({"MKT": mkt_vw, "SMB": smb, "VOL": vol_f, "LIQ": liq_f, "LIANBAN_BETA": lb_c2c}, index=cal_dates)
    extra = pd.DataFrame({"CSI300": csi_s.reindex(cal_dates), "LIANBAN_O2C_EXCESS": lb_o2c, "FB20_C2C_EXCESS": fb20_c2c, "FB20_O2C_EXCESS": fb20_o2c}, index=cal_dates)
    return fac_5f, extra

def run_pillar1_v20(comb_df: pd.DataFrame, daily_s: np.ndarray, fac_5f: pd.DataFrame, extra: pd.DataFrame,
                    cal_dates: list[str], pool10_dt: dict, q10: dict, by_c10: dict, pool20_dt: dict, q20: dict, by_c20: dict) -> dict:
    daily_ser = pd.Series(daily_s, index=cal_dates, dtype=float)
    act_flag = np.abs(daily_s) > 1e-12
    reg = p1.run_pillar1_regressions("combined_v20", comb_df, daily_ser, act_flag, fac_5f, extra, cal_dates)
    f6_c2c = fac_5f.copy(); f6_c2c["FB20_BETA"] = extra["FB20_C2C_EXCESS"]
    f6_o2c = fac_5f.copy(); f6_o2c["LIANBAN_BETA"] = extra["LIANBAN_O2C_EXCESS"]; f6_o2c["FB20_BETA"] = extra["FB20_O2C_EXCESS"]
    reg["full_5y_6f_joint_c2c_hac"] = p1.fit_hac_ols(daily_ser, f6_c2c, maxlags=5)
    reg["full_5y_6f_joint_o2c_hac"] = p1.fit_hac_ols(daily_ser, f6_o2c, maxlags=5)

    # Dual-eco matched control (191 10cm trades + 87 20cm trades)
    smap = {"3to4": "3to4_V41", "high": "high_V51", "pry": "pry_V21", "2to3": "2to3_V21", "1to2": "1to2_V19"}
    rng = np.random.default_rng(SEED)
    sr_all, pm_all, p_lists = [], [], []
    sr_10, pm_10, sr_20, pm_20 = [], [], [], []
    tiers = {"1": 0, "2": 0, "3": 0, "4": 0, "unmatched": 0}
    for r in comb_df.itertuples(index=False):
        c6, b_dt, e_dt, b_hh, e_hh = r.code, r.buy_date, r.exit_date, int(r.buy_hhmm), int(r.exit_hhmm)
        if r.strategy == "20cm":
            mq, tq = q20.get((c6, b_dt), (None, None)); cands = [x for x in pool20_dt.get(b_dt, []) if x[0] != c6]
            tier, sel = None, []
            if mq is not None:
                t1, t2 = [x[0] for x in cands if x[1] == mq and x[2] == tq], [x[0] for x in cands if x[1] == mq]
                if t1: sel, tier = t1, "1"
                elif t2: sel, tier = t2, "2"
            if not sel and cands: sel, tier = [x[0] for x in cands], "3"
            prets = [p for pc in sel if (p := pb.peer_hold_ret_20cm(pc, b_dt, e_dt, e_hh, by_c20, 0.0030)) is not None]
        else:
            pk = smap[r.strategy]; mq, tq = q10.get((c6, b_dt), (None, None)); cands = [x for x in pool10_dt[pk].get(b_dt, []) if x[0] != c6]
            tier, sel = None, []
            if mq is not None:
                t1, t2 = [x[0] for x in cands if x[1] == mq and x[2] == tq], [x[0] for x in cands if x[1] == mq]
                if t1: sel, tier = t1, "1"
                elif t2: sel, tier = t2, "2"
            if not sel and cands: sel, tier = [x[0] for x in cands], "3"
            if not sel:
                fbs = {"high_V51": ["high_V51_fb","high_V51_fb2","3to4_V41"], "pry_V21": ["pry_V21_fb"], "3to4_V41": ["2to3_V21","1to2_V19"], "2to3_V21": ["1to2_V19","3to4_V41"], "1to2_V19": ["2to3_V21"]}[pk]
                for fk in fbs:
                    fc = [x[0] for x in pool10_dt[fk].get(b_dt, []) if x[0] != c6]
                    if fc: sel, tier = fc, "4"; break
            prets = [p for pc in sel if (p := p1.peer_hold_return(pc, b_dt, e_dt, b_hh, e_hh, by_c10, "matched_timing")) is not None]
        if not prets: tiers["unmatched"] += 1; continue
        tiers[tier] += 1; pm_v = float(np.mean(prets))
        sr_all.append(float(r.net_ret)); pm_all.append(pm_v); p_lists.append(np.array(prets, float))
        (sr_20 if r.strategy == "20cm" else sr_10).append(float(r.net_ret))
        (pm_20 if r.strategy == "20cm" else pm_10).append(pm_v)

    def _sum_mc(sr_l, pm_l):
        sa, pa = np.array(sr_l, float), np.array(pm_l, float); df = sa - pa
        ts, pv = stats.ttest_rel(sa, pa) if len(sa) > 1 else (0.0, 1.0)
        try: _, wp = stats.wilcoxon(df) if len(sa) >= 5 else (0.0, 1.0)
        except Exception: wp = 1.0
        return {"n": int(len(sa)), "strat_mean_pct": pb.sf(sa.mean()*100, 3), "matched_mean_pct": pb.sf(pa.mean()*100, 3),
                "excess_pct": pb.sf(df.mean()*100, 3), "paired_t": pb.sf(ts, 3), "paired_p": pb.sf(pv, 6), "wilcoxon_p": pb.sf(wp, 6)}
    mc_ex = [float(np.mean(np.array(sr_all) - np.array([a[rng.integers(0, len(a))] for a in p_lists])) * 100.0) for _ in range(1000)]
    return {"regressions": reg, "matched_control": {**_sum_mc(sr_all, pm_all), "tier_counts": tiers,
            "mc_1draw_1000_excess_med_pct": pb.sf(np.median(mc_ex), 3), "sub_10cm": _sum_mc(sr_10, pm_10), "sub_20cm": _sum_mc(sr_20, pm_20)}}

def run_pillar2_v20(comb_df: pd.DataFrame, by_c_all: dict, cal_dates: list[str], bars_5m: dict, zt_tape: pd.DataFrame) -> dict:
    dt_to_idx = {d: i for i, d in enumerate(cal_dates)}; n_days = len(cal_dates)
    day_base, items = [[] for _ in range(n_days)], []
    for r in comb_df.itertuples(index=False):
        bar = by_c_all[r.code]; p0, pe = bar["dt_to_pos"][r.buy_date], bar["dt_to_pos"][r.exit_date]
        b_adj, e_adj = float(r.buy_px_adj), float(r.exit_px_adj); gfs, idxs = [], []
        for k in range(p0, pe + 1):
            idxs.append(dt_to_idx[bar["dt"][k]])
            gfs.append(bar["adj_close"][k] / b_adj if k == p0 else (bar["adj_close"][k] / bar["adj_close"][k-1] if k < pe else e_adj / bar["adj_close"][k-1]))
        pg = float(np.prod(gfs)); sc = math.sqrt((1.0 + float(r.net_ret)) / pg) if pg > 0 else 1.0
        gfs[0] *= sc; gfs[-1] *= sc; pos_l = []
        for d_i, m in zip(idxs, gfs): pos_l.append((d_i, len(day_base[d_i]))); day_base[d_i].append(m)
        sb = 0.04 if (np.isnan(bar["vol20_m1"][p0]) or bar["vol20_m1"][p0] <= 0) else float(bar["vol20_m1"][p0])
        se = 0.04 if (np.isnan(bar["vol20_m1"][pe]) or bar["vol20_m1"][pe] <= 0) else float(bar["vol20_m1"][pe])
        items.append({"d0": pos_l[0][0], "pos0": pos_l[0][1], "dk": pos_l[-1][0], "posk": pos_l[-1][1],
                      "sig_b": sb, "sig_e": se, "v_b": float(bar["amount"][p0]), "v_e": float(bar["amount"][pe]), "net_ret": float(r.net_ret)})

    q_grid = [1e6, 3e6, 5e6, 1e7, 2e7, 5e7, 1e8]; base_0 = p1.eval_ac_metrics(items, day_base, n_days, False, 0.0, 0.50); ac = {}
    for Y in (0.50, 0.70):
        gd = {f"{int(Q//1e4)}w": {k: pb.sf(v, 4 if "nav" in k else (2 if "pct" in k or "bps" in k else 3))
              for k, v in p1.eval_ac_metrics(items, day_base, n_days, False, Q, Y).items()} for Q in q_grid}
        ac[f"Y_{Y:.2f}"] = {"grid": gd, "breakeven_cap_wan": p1.bisect_capacity(lambda q: p1.eval_ac_metrics(items, day_base, n_days, False, q, Y)["nav_5y"], 1.0),
                            "half_cagr_cap_wan": p1.bisect_capacity(lambda q: p1.eval_ac_metrics(items, day_base, n_days, False, q, Y)["cagr_pct"], 0.5 * base_0["cagr_pct"]),
                            "half_simple_profit_cap_wan": p1.bisect_capacity(lambda q: p1.eval_ac_metrics(items, day_base, n_days, False, q, Y)["nav_5y"] - 1.0, 0.5 * (base_0["nav_5y"] - 1.0))}
    dyn_comp = {}
    for q0 in (1e6, 5e6):
        nc = 1.0
        for it in items:
            qt = q0 * nc
            ib = min(0.95, 0.50 * it["sig_b"] * math.sqrt(qt / it["v_b"])) if it["v_b"] > 0 else 0.95
            ie = min(0.95, 0.50 * it["sig_e"] * math.sqrt(qt / it["v_e"])) if it["v_e"] > 0 else 0.95
            nc *= (1.0 + it["net_ret"]) * (1.0 - ib) * (1.0 - ie)
        dyn_comp[f"q0_{int(q0//1e4)}w_uncapped"] = round(nc, 4)

    rng = np.random.default_rng(SEED); rets = comb_df["net_ret"].to_numpy(float); n_tr = len(rets); fill = {}
    for pf in (0.50, 0.70):
        ms = rng.random((2000, n_tr)) < pf; paths = np.concatenate([np.ones((2000, 1)), np.cumprod(np.where(ms, 1.0 + rets[None, :], 1.0), 1)], 1)
        tn = paths[:, -1]; cagrs = ((tn ** (252.0 / n_days)) - 1.0) * 100.0; mdds = (1.0 - paths / np.maximum.accumulate(paths, 1)).max(1) * 100.0
        fill[f"fill_{int(pf*100)}pct"] = {"nav_5y_median": pb.sf(np.median(tn), 4), "nav_5y_p05": pb.sf(np.quantile(tn, 0.05), 4),
                                          "cagr_median_pct": pb.sf(np.median(cagrs), 2), "mdd_median_pct": pb.sf(np.median(mdds), 2), "mdd_p95_pct": pb.sf(np.quantile(mdds, 0.95), 2)}

    smap = {(zr.sec_code, zr.trade_date): -float(zr.seal_amount or 0.0) for zr in zt_tape.itertuples(index=False)}
    idx_r = np.argsort(-rets, kind="mergesort"); skeys = []; scov = 0
    for r in comb_df.itertuples(index=False):
        bar = by_c_all[r.code]; p0 = bar["dt_to_pos"][r.buy_date]; dm1 = bar["dt"][p0-1] if p0 > 0 else r.buy_date
        sv = smap.get((r.code, r.buy_date)) or smap.get((r.code, dm1))
        if sv is not None: scov += 1; skeys.append((0, sv))
        else: skeys.append((1, -float(r.net_ret)))
    idx_s = sorted(range(n_tr), key=lambda i: skeys[i]); adv = {"by_net_ret": {}, "by_seal_amount_queue_proxy": {"seal_cov": f"{scov}/{n_tr}"}}
    for pct in (10, 20):
        kd = max(1, int(round(n_tr * pct / 100.0)))
        for lbl, idxs_d in [("by_net_ret", idx_r[:kd]), ("by_seal_amount_queue_proxy", idx_s[:kd])]:
            km = np.ones(n_tr, bool); km[idxs_d] = False; sr = rets[km]
            adv[lbl][f"drop_top_{pct}pct"] = {"n_rem": int(len(sr)), "wr_pct": pb.sf((sr>0).mean()*100, 2), "avg_ret_pct": pb.sf(sr.mean()*100, 3), "nav_5y": pb.sf(np.prod(1+sr), 4)}

    cov_10 = sum((r.code, r.buy_date) in bars_5m for r in comb_df[comb_df["strategy"] != "20cm"].itertuples(index=False))
    cov_20 = sum((r.code, r.buy_date) in bars_5m for r in comb_df[comb_df["strategy"] == "20cm"].itertuples(index=False))
    delay = {"delay_1m": "MISSING_LOCAL_DATA (本地无任何A股1分钟K线数据，仅存5分钟K线)",
             "five_m_buy_coverage_total": f"{cov_10+cov_20}/{n_tr} ({(cov_10+cov_20)/n_tr*100:.1f}%)",
             "five_m_buy_coverage_10cm": f"{cov_10}/191 ({cov_10/191*100:.1f}%)",
             "five_m_buy_coverage_20cm": f"{cov_20}/87 ({cov_20/87*100:.1f}%; 20cm本地5m线仅覆盖至2023-08-22)"}
    for slbl, sb_bars in (("plus_5m", 1), ("plus_15m", 3)):
        rcz, rcs, rbc, nmc = [], [], [], 0
        for r in comb_df.itertuples(index=False):
            arr = bars_5m.get((r.code, r.buy_date))
            if arr is None or len(arr) == 0: continue
            rbc.append(float(r.net_ret)); bd = by_c_all[r.code]; p0 = bd["dt_to_pos"][r.buy_date]; ztp = float(bd["zt_px"][p0])
            ti = (sb_bars - 1) if int(r.buy_hhmm) <= 925 else min(len(arr)-1, int(np.where(arr[:,0]>=int(r.buy_hhmm))[0][0] if len(np.where(arr[:,0]>=int(r.buy_hhmm))[0]) else 0) + sb_bars)
            db = arr[ti]
            if (not np.isnan(ztp)) and (db[4] >= ztp - 0.011): nmc += 1; rcz.append(0.0)
            else:
                nr = (float(r.exit_px_adj) / (float(db[4]) * bd["adjf"][p0])) * (1.0 - float(r.fee_rt)) - 1.0
                rcz.append(nr); rcs.append(nr)
        def _sd(l): a = np.array(l, float); return {"n": int(len(a)), "wr_pct": pb.sf((a>0).mean()*100, 2), "avg_ret_pct": pb.sf(a.mean()*100, 3), "nav": pb.sf(np.prod(1+a), 4)} if len(a) else {"n": 0}
        delay[slbl] = {"covered_base_stats": _sd(rbc), "missed_zt_close_count": nmc, "covered_missed_as_zero": _sd(rcz), "covered_missed_skipped": _sd(rcs)}

    vb, ve = np.array([it["v_b"] for it in items])/1e4, np.array([it["v_e"] for it in items])/1e4
    vg = {"v_buy_wan_p10": pb.sf(np.quantile(vb, 0.10), 1), "v_buy_wan_median": pb.sf(np.median(vb), 1),
          "v_exit_wan_p10": pb.sf(np.quantile(ve, 0.10), 1), "v_exit_wan_median": pb.sf(np.median(ve), 1),
          "cap_10pct_adv_p10_wan": pb.sf(min(np.quantile(vb, 0.10), np.quantile(ve, 0.10)) * 0.10, 1),
          "cap_5pct_adv_p10_wan": pb.sf(min(np.quantile(vb, 0.10), np.quantile(ve, 0.10)) * 0.05, 1)}
    return {"baseline_unconstrained": {"nav_5y": pb.sf(base_0["nav_5y"], 4), "cagr_pct": pb.sf(base_0["cagr_pct"], 2), "sharpe": pb.sf(base_0["sharpe"], 3)},
            "liquidity_participation_guardrails": vg, "almgren_chriss": ac, "dynamic_compounding_Y050_uncapped": dyn_comp,
            "random_fill_2000mc": fill, "adverse_selection": adv, "entry_delay": delay}
