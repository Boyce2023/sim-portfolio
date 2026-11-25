#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Scoring thresholds, monotonicity, Spearman IC & core factor LOO stability audit
under 3-tier velocity slippage for 1to2 V20, 3to4 V4.1 & high V5.1 (ZERO yfinance, ZERO cap10m).
"""
import math
import pickle
import sys
import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

from vel_slip_common import (
    SIM,
    CANON_WINDOWS,
    apply_vel_slip_df,
    build_daily_mtm_series,
    calc_d15_window,
    sf,
)

PARTA_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
MW1_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high"
MW3_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part3_1to2"
F1_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4"
HD_DIR = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"


def calc_spearman_windows(df: pd.DataFrame, score_col: str, ret_col: str) -> dict:
    out = {}
    splits = [
        ("FULL", np.ones(len(df), dtype=bool)),
        ("IS", (df["buy_date"] <= "2024-06-30").to_numpy()),
        ("OOS", (df["buy_date"] >= "2024-07-04").to_numpy()),
        ("Y2026", (df["buy_date"] >= "2026-01-01").to_numpy()),
    ]
    for lbl, m in splits:
        sub = df[m].dropna(subset=[score_col, ret_col])
        if len(sub) < 5 or sub[score_col].nunique() < 2:
            out[lbl] = {"n": int(len(sub)), "ic": None, "p": None}
        else:
            r, p = stats.spearmanr(sub[score_col], sub[ret_col])
            out[lbl] = {"n": int(len(sub)), "ic": sf(r, 4), "p": sf(p, 5)}
    return out


def calc_q5_monotonicity(scores: np.ndarray, rets: np.ndarray, n_bins: int = 5) -> dict:
    s = pd.Series(scores, dtype=float)
    r = np.asarray(rets, dtype=float)
    if len(s) < n_bins:
        return {"insufficient": True, "n": int(len(s))}
    cats = pd.qcut(s.rank(method="first"), q=n_bins, labels=False)
    bins = []
    for b in sorted(cats.unique()):
        m = (cats == b).to_numpy()
        rb = r[m]
        sb = scores[m]
        w, l = rb[rb > 0], rb[rb < 0]
        plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l)) else (99.0 if len(w) else 0.0)
        bins.append({
            "bin": int(b) + 1, "n": int(m.sum()),
            "score_min": sf(sb.min(), 1), "score_max": sf(sb.max(), 1),
            "wr_pct": sf((rb > 0).mean() * 100.0, 2),
            "mean_ret_pct": sf(rb.mean() * 100.0, 3),
            "plr": sf(plr, 2),
        })
    bidx = np.array([x["bin"] for x in bins], float)
    bmns = np.array([x["mean_ret_pct"] for x in bins], float)
    bwrs = np.array([x["wr_pct"] for x in bins], float)
    rho_m, p_m = stats.spearmanr(bidx, bmns)
    rho_w, p_w = stats.spearmanr(bidx, bwrs)
    r_bot, r_top = r[(cats == 0).to_numpy()], r[(cats == n_bins - 1).to_numpy()]
    t_sp, p_sp = stats.ttest_ind(r_top, r_bot, equal_var=False) if (len(r_top) > 1 and len(r_bot) > 1) else (0.0, 1.0)
    return {
        "bins": bins,
        "rho_mean_ret": sf(rho_m, 4), "p_mean_ret": sf(p_m, 4),
        "rho_win_rate": sf(rho_w, 4), "p_win_rate": sf(p_w, 4),
        "top_minus_bot_pp": sf((r_top.mean() - r_bot.mean()) * 100.0, 3),
        "welch_t": sf(t_sp, 3), "welch_p": sf(p_sp, 5),
    }


def tier_breakdown_pool(df: pd.DataFrame, score_col: str, ret_col: str, bins_spec: list[tuple[str, float, float]]) -> dict:
    out = {}
    for lbl, lo, hi in bins_spec:
        sub = df[(df[score_col] >= lo) & (df[score_col] < hi)]
        w_out = {}
        for wl, wm in [("FULL", np.ones(len(sub), bool)), ("IS", (sub["buy_date"] <= "2024-06-30").to_numpy()), ("OOS", (sub["buy_date"] >= "2024-07-04").to_numpy())]:
            r = sub.loc[wm, ret_col].to_numpy(float)
            if len(r) == 0:
                w_out[wl] = {"n": 0}
                continue
            w, l = r[r > 0], r[r < 0]
            plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l)) else (99.0 if len(w) else 0.0)
            w_out[wl] = {
                "n": int(len(r)), "wr_pct": sf((r > 0).mean() * 100.0, 2),
                "mean_pct": sf(r.mean() * 100.0, 3), "plr": sf(plr, 2),
                "eq_nav": sf(float(np.prod(1.0 + sub.loc[wm].groupby("buy_date")[ret_col].mean().to_numpy(float))), 4),
            }
        out[lbl] = w_out
    return out


def sim_3to4_slot_df(pool_df: pd.DataFrame, scores: np.ndarray, thr: float) -> pd.DataFrame:
    mask = scores >= thr
    sub = pool_df[mask].copy()
    if sub.empty:
        return sub
    sub["_sc"] = scores[mask]
    sub["_prio"] = sub["_sc"] * 10.0 + sub["prio_tie"] * 0.1
    sub = sub.sort_values(["buy_date", "buy_hhmm", "_prio", "c6"], ascending=[True, True, False, True])
    taken, fdt, fhh = [], "", 0
    for r in sub.itertuples(index=False):
        if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
            taken.append(r._asdict())
            fdt, fhh = str(r.exit_date), int(r.exit_hhmm)
    return pd.DataFrame(taken)


def sim_high_slot_df(pool_df: pd.DataFrame, scores: np.ndarray, thr: float, ret_col: str, use_cb: bool = True) -> pd.DataFrame:
    mask = scores >= thr
    sub = pool_df[mask].copy()
    if sub.empty:
        return sub
    sub["_sc"] = scores[mask]
    sub = sub.sort_values(["buy_date", "_sc", "c6"], ascending=[True, False, True])
    taken, fd, peo, cl, sk = [], "", False, 0, False
    for r in sub.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not bool(r.b_open_h))):
            rv = float(getattr(r, ret_col))
            if use_cb and sk:
                fd, peo = str(r.exit_date), bool(r.eo)
                if rv > 0.0:
                    sk, cl = False, 0
                continue
            taken.append(r._asdict())
            fd, peo = str(r.exit_date), bool(r.eo)
            if rv < -0.02:
                cl += 1
                if cl >= 2:
                    sk = True
            elif rv > 0.0:
                cl = 0
    return pd.DataFrame(taken)


def audit_3to4_scoring(dmap, m5_bar, sh300, all_sh_dts, cal_dts, dt_to_idx) -> dict:
    if UPG_DIR not in sys.path:
        sys.path.insert(0, UPG_DIR)
    import upgrade_3to4_pit as u34

    p34 = pd.read_csv(f"{MW1_DIR}/pool_3to4_full_clean.csv", dtype={"code": str})
    p34 = apply_vel_slip_df(p34, dmap, m5_bar, mode="base", missing_5m_policy="error")
    p34_strict = apply_vel_slip_df(p34, dmap, m5_bar, mode="strict_surge", missing_5m_policy="error")
    p34["net_ret_strict"] = p34_strict["net_ret_vel"]

    c34 = pickle.load(open(f"{F1_DIR}/pit_exit_cache_full.pkl", "rb"))
    cd = c34["cand_df"].copy()
    cd["c6"] = cd["code"].astype(str).str.zfill(6)
    cd_map = {(str(r.buy_date), r.c6): i for i, r in enumerate(cd.itertuples(index=False))}
    idxs = [cd_map[(r.buy_date, r.c6)] for r in p34.itertuples(index=False)]
    comp = c34["comp_v40"][idxs]
    sc_base = c34["sc_v40"][idxs]
    assert np.max(np.abs(sc_base - p34["base_score"].to_numpy(float))) < 1e-6

    bins_spec = [("Fail(<90)", -999.0, 90.0), ("A_tier(90-101)", 90.0, 102.0), ("S_tier(>=102)", 102.0, 999.0)]
    thr_ladder = {}
    for th in (84, 86, 88, 90, 92, 94, 96, 98, 100, 102, 104):
        sl = sim_3to4_slot_df(p34, sc_base, float(th))
        raw_pass = p34[sc_base >= th]
        if sl.empty:
            continue
        dr_b, _ = build_daily_mtm_series(sl, cal_dts, dt_to_idx, dmap, ret_col="net_ret")
        dr_v, _ = build_daily_mtm_series(sl, cal_dts, dt_to_idx, dmap, ret_col="net_ret_vel", buy_px_col="eff_buy_price")
        thr_ladder[str(th)] = {
            "before": {wn: calc_d15_window(sl, dr_b, cal_dts, dt_to_idx, sh300, all_sh_dts, sd, ed, "net_ret", raw_pass, "net_ret") for wn, sd, ed in CANON_WINDOWS},
            "after_vel": {wn: calc_d15_window(sl, dr_v, cal_dts, dt_to_idx, sh300, all_sh_dts, sd, ed, "net_ret_vel", raw_pass, "net_ret_vel") for wn, sd, ed in CANON_WINDOWS},
        }

    base_slot = sim_3to4_slot_df(p34, sc_base, 90.0)
    b_nav_full = float(np.prod(1.0 + base_slot["net_ret"].to_numpy(float)))
    v_nav_full = float(np.prod(1.0 + base_slot["net_ret_vel"].to_numpy(float)))
    b_nav_is = float(np.prod(1.0 + base_slot[base_slot["buy_date"] <= "2024-06-30"]["net_ret"].to_numpy(float)))
    v_nav_is = float(np.prod(1.0 + base_slot[base_slot["buy_date"] <= "2024-06-30"]["net_ret_vel"].to_numpy(float)))
    b_nav_oos = float(np.prod(1.0 + base_slot[base_slot["buy_date"] >= "2024-07-04"]["net_ret"].to_numpy(float)))
    v_nav_oos = float(np.prod(1.0 + base_slot[base_slot["buy_date"] >= "2024-07-04"]["net_ret_vel"].to_numpy(float)))

    loo_factors = []
    flips = []
    for j, fn in enumerate(u34.V40_FACTOR_NAMES):
        sc_d = sc_base - comp[:, j]
        sl_j = sim_3to4_slot_df(p34, sc_d, 90.0)
        def _ns(df_s, rc):
            if df_s.empty:
                return 1.0, 1.0, 1.0, 0
            nf = float(np.prod(1.0 + df_s[rc].to_numpy(float)))
            ni = float(np.prod(1.0 + df_s[df_s["buy_date"] <= "2024-06-30"][rc].to_numpy(float)))
            no = float(np.prod(1.0 + df_s[df_s["buy_date"] >= "2024-07-04"][rc].to_numpy(float)))
            return nf, ni, no, int(len(df_s))
        bf, bi, bo, nj = _ns(sl_j, "net_ret")
        vf, vi, vo, _ = _ns(sl_j, "net_ret_vel")
        # Positive sign means keeping factor j helps NAV (base > drop)
        d_full_b, d_full_v = b_nav_full - bf, v_nav_full - vf
        d_is_b, d_is_v = b_nav_is - bi, v_nav_is - vi
        d_oos_b, d_oos_v = b_nav_oos - bo, v_nav_oos - vo
        # Marginal spearman IC of factor j on full pool
        r_b, _ = stats.spearmanr(comp[:, j], p34["net_ret"]) if np.std(comp[:, j]) > 0 else (0.0, 1.0)
        r_v, _ = stats.spearmanr(comp[:, j], p34["net_ret_vel"]) if np.std(comp[:, j]) > 0 else (0.0, 1.0)
        ic_flip = (r_b * r_v < -1e-6)
        loo_flip = ((d_full_b > 1e-6 and d_full_v < -1e-6) or (d_full_b < -1e-6 and d_full_v > 1e-6))
        if ic_flip or loo_flip:
            flips.append(fn)
        loo_factors.append({
            "factor": fn,
            "drop_n": nj,
            "before_delta_nav_full": sf(d_full_b, 2), "vel_delta_nav_full": sf(d_full_v, 2),
            "before_delta_nav_is": sf(d_is_b, 3), "vel_delta_nav_is": sf(d_is_v, 3),
            "before_delta_nav_oos": sf(d_oos_b, 2), "vel_delta_nav_oos": sf(d_oos_v, 2),
            "before_pool_ic": sf(r_b, 4), "vel_pool_ic": sf(r_v, 4),
            "ic_sign_flip": bool(ic_flip), "loo_full_sign_flip": bool(loo_flip),
        })

    return {
        "pool_size": int(len(p34)),
        "pool_5m_cov_intraday": f"{int((p34['buy_hhmm']>925).sum())}/{int((p34['buy_hhmm']>925).sum())} (100%)",
        "vel_tier_counts_pool": p34["vel_tier"].value_counts().to_dict(),
        "tier_breakdown": {
            "before": tier_breakdown_pool(p34, "base_score", "net_ret", bins_spec),
            "after_vel": tier_breakdown_pool(p34, "base_score", "net_ret_vel", bins_spec),
        },
        "spearman_ic_pool": {
            "before": calc_spearman_windows(p34, "base_score", "net_ret"),
            "after_vel": calc_spearman_windows(p34, "base_score", "net_ret_vel"),
            "after_strict": calc_spearman_windows(p34, "base_score", "net_ret_strict"),
        },
        "spearman_ic_pass90": {
            "before": calc_spearman_windows(p34[sc_base >= 90], "base_score", "net_ret"),
            "after_vel": calc_spearman_windows(p34[sc_base >= 90], "base_score", "net_ret_vel"),
        },
        "q5_monotonicity_pool": {
            "before": calc_q5_monotonicity(sc_base, p34["net_ret"].to_numpy(float)),
            "after_vel": calc_q5_monotonicity(sc_base, p34["net_ret_vel"].to_numpy(float)),
        },
        "threshold_ladder": thr_ladder,
        "loo_22_factors": loo_factors,
        "any_factor_flip": flips,
    }


def _extract_high_factors(dfr_row) -> dict:
    r = dfr_row
    return {
        "H01_brk_r10": 12 if r["brk_r10"] >= 0.20 else -8,
        "H02_n_zt": 10 if r["n_zt"] < 70 else (-10 if r["n_zt"] >= 95 else 0),
        "H03_csi5": 8 if r["csi5"] >= -0.005 else (-10 if r["csi5"] < -0.025 else 0),
        "H04_d1_op": 8 if r["d1_op"] < 0.0 else 0,
        "H05_op2": 8 if r["op2"] < 0.0 else (6 if 0.0 <= r["op2"] <= 0.025 else 0),
        "H06_obc_tight": 6 if (r["obc"] == 0 and r["d0_tight"] >= 35.0) else 0,
        "H07_pelo_dom": 6 if (r["pelo"] < 135.0 and (not r["dom"])) else 0,
        "H08_lh1": 6 if r["lh1"] == 0 else (-10 if r["lh1"] == 2 else 0),
        "H09_in1": -6 if r["in1"] >= 1 else 0,
        "H10_price_tier": 5 if r["low_price_le20"] else (-10 if r["high_price_gt35"] else 0),
        "H11_turn_boards": 5 if r["turn_boards_ge4"] else (-5 if r["turn_boards_cnt"] <= 2 else 0),
        "H12_d1_deep_dip": 5 if r["d1_deep_dip_le6"] else 0,
        "H13_lock_fmcap": 6 if (r["lock"] >= 45.0 or r["fmcap"] >= 45.0) else -6,
        "H14_qu1_lh1": 4 if (r["qu1"] >= 1 and r["lh1"] <= 1) else 0,
        "H15_hist_ge5": 6 if r["kpl_hist_1y_has_ge5"] else (3 if r["kpl_hist_3y_has_ge5"] else 0),
        "H16_old_stock_theme": 3 if r["kpl_old_stock_old_theme"] else (-5 if r["kpl_old_stock_new_theme"] else 0),
        "H17_lhb_d0_locked": 5 if r["lhb_d0_top_locked"] else 0,
        "H18_lhb_d1_lhasa_heavy": -10 if r["lhb_d1_lhasa_heavy"] else 0,
        "H19_lhb_d1_net_pos": -5 if r["lhb_d1_net_positive"] else 0,
        "H20_lhb_d0_daysurf": -6 if r["lhb_d0_day_surf_buy"] else 0,
        "H21_kpl_seal0935": -5 if r["kpl_d0_seal_early_0935"] else 0,
        "H22_kpl_tech": -4 if r["kpl_reason_tech"] else 0,
    }


def audit_high_scoring(dmap, m5_bar, sub2_bar, sh300, all_sh_dts, cal_dts, dt_to_idx) -> dict:
    ph = pd.read_csv(f"{MW1_DIR}/pool_high_full_clean.csv", dtype={"code": str})
    ph = apply_vel_slip_df(ph, dmap, m5_bar, sub2_bar=sub2_bar, mode="base", allow_sub2_fallback=True, missing_5m_policy="error")
    ph_strict = apply_vel_slip_df(ph, dmap, m5_bar, sub2_bar=sub2_bar, mode="strict_surge", allow_sub2_fallback=True, missing_5m_policy="error")
    ph["net_ret_strict"] = ph_strict["net_ret_vel"]

    dfr = pd.read_pickle(f"{HD_DIR}/v5_enriched_119.pkl")
    dfr["c6"] = dfr["code"].astype(str).str.zfill(6)
    m = ph.merge(dfr, on=["buy_date", "c6"], suffixes=("", "_dfr"))
    assert len(m) == len(ph) == 62
    f_rows = [_extract_high_factors(row) for _, row in m.iterrows()]
    f_df = pd.DataFrame(f_rows)
    sc_base = ph["base_score"].to_numpy(float)
    assert np.max(np.abs(60.0 + f_df.sum(axis=1).to_numpy(float) - sc_base)) < 1e-6

    bins_spec = [("Fail(<88)", -999.0, 88.0), ("A_tier(88-95)", 88.0, 96.0), ("S_tier(>=96)", 96.0, 999.0)]
    thr_ladder = {}
    for th in (80, 84, 86, 88, 90, 92, 94, 96, 98):
        sl_b = sim_high_slot_df(ph, sc_base, float(th), "net_ret", use_cb=True)
        sl_v = sim_high_slot_df(ph, sc_base, float(th), "net_ret_vel", use_cb=True)
        raw_pass = ph[sc_base >= th]
        if sl_b.empty:
            continue
        dr_b, _ = build_daily_mtm_series(sl_b, cal_dts, dt_to_idx, dmap, ret_col="net_ret")
        dr_v, _ = build_daily_mtm_series(sl_v, cal_dts, dt_to_idx, dmap, ret_col="net_ret_vel")
        thr_ladder[str(th)] = {
            "before": {wn: calc_d15_window(sl_b, dr_b, cal_dts, dt_to_idx, sh300, all_sh_dts, sd, ed, "net_ret", raw_pass, "net_ret") for wn, sd, ed in CANON_WINDOWS},
            "after_vel": {wn: calc_d15_window(sl_v, dr_v, cal_dts, dt_to_idx, sh300, all_sh_dts, sd, ed, "net_ret_vel", raw_pass, "net_ret_vel") for wn, sd, ed in CANON_WINDOWS},
        }

    base_sl_b = sim_high_slot_df(ph, sc_base, 88.0, "net_ret", use_cb=True)
    base_sl_v = sim_high_slot_df(ph, sc_base, 88.0, "net_ret_vel", use_cb=True)
    b_nav_full = float(np.prod(1.0 + base_sl_b["net_ret"].to_numpy(float)))
    v_nav_full = float(np.prod(1.0 + base_sl_v["net_ret_vel"].to_numpy(float)))
    b_nav_is = float(np.prod(1.0 + base_sl_b[base_sl_b["buy_date"] <= "2024-06-30"]["net_ret"].to_numpy(float)))
    v_nav_is = float(np.prod(1.0 + base_sl_v[base_sl_v["buy_date"] <= "2024-06-30"]["net_ret_vel"].to_numpy(float)))
    b_nav_oos = float(np.prod(1.0 + base_sl_b[base_sl_b["buy_date"] >= "2024-07-04"]["net_ret"].to_numpy(float)))
    v_nav_oos = float(np.prod(1.0 + base_sl_v[base_sl_v["buy_date"] >= "2024-07-04"]["net_ret_vel"].to_numpy(float)))

    loo_factors, flips = [], []
    for col in f_df.columns:
        fv = f_df[col].to_numpy(float)
        sc_d = sc_base - fv
        sl_jb = sim_high_slot_df(ph, sc_d, 88.0, "net_ret", use_cb=True)
        sl_jv = sim_high_slot_df(ph, sc_d, 88.0, "net_ret_vel", use_cb=True)
        def _ns(df_s, rc):
            if df_s.empty:
                return 1.0, 1.0, 1.0, 0
            return (
                float(np.prod(1.0 + df_s[rc].to_numpy(float))),
                float(np.prod(1.0 + df_s[df_s["buy_date"] <= "2024-06-30"][rc].to_numpy(float))),
                float(np.prod(1.0 + df_s[df_s["buy_date"] >= "2024-07-04"][rc].to_numpy(float))),
                int(len(df_s)),
            )
        bf, bi, bo, njb = _ns(sl_jb, "net_ret")
        vf, vi, vo, njv = _ns(sl_jv, "net_ret_vel")
        d_full_b, d_full_v = b_nav_full - bf, v_nav_full - vf
        r_b, _ = stats.spearmanr(fv, ph["net_ret"]) if np.std(fv) > 0 else (0.0, 1.0)
        r_v, _ = stats.spearmanr(fv, ph["net_ret_vel"]) if np.std(fv) > 0 else (0.0, 1.0)
        ic_flip = (r_b * r_v < -1e-6)
        loo_flip = ((d_full_b > 1e-6 and d_full_v < -1e-6) or (d_full_b < -1e-6 and d_full_v > 1e-6))
        if ic_flip or loo_flip:
            flips.append(col)
        loo_factors.append({
            "factor": col, "drop_n_b": njb, "drop_n_v": njv,
            "before_delta_nav_full": sf(d_full_b, 3), "vel_delta_nav_full": sf(d_full_v, 3),
            "before_delta_nav_is": sf(b_nav_is - bi, 3), "vel_delta_nav_is": sf(v_nav_is - vi, 3),
            "before_delta_nav_oos": sf(b_nav_oos - bo, 3), "vel_delta_nav_oos": sf(v_nav_oos - vo, 3),
            "before_pool_ic": sf(r_b, 4), "vel_pool_ic": sf(r_v, 4),
            "ic_sign_flip": bool(ic_flip), "loo_full_sign_flip": bool(loo_flip),
        })

    return {
        "pool_size": int(len(ph)),
        "pool_5m_sources": ph["src_5m"].value_counts().to_dict(),
        "vel_tier_counts_pool": ph["vel_tier"].value_counts().to_dict(),
        "cb_diff_before_vs_vel_pass88": int(len(base_sl_b) != len(base_sl_v)),
        "tier_breakdown": {
            "before": tier_breakdown_pool(ph, "base_score", "net_ret", bins_spec),
            "after_vel": tier_breakdown_pool(ph, "base_score", "net_ret_vel", bins_spec),
        },
        "spearman_ic_pool": {
            "before": calc_spearman_windows(ph, "base_score", "net_ret"),
            "after_vel": calc_spearman_windows(ph, "base_score", "net_ret_vel"),
            "after_strict": calc_spearman_windows(ph, "base_score", "net_ret_strict"),
        },
        "spearman_ic_pass88": {
            "before": calc_spearman_windows(ph[sc_base >= 88], "base_score", "net_ret"),
            "after_vel": calc_spearman_windows(ph[sc_base >= 88], "base_score", "net_ret_vel"),
        },
        "q5_monotonicity_pool": {
            "before": calc_q5_monotonicity(sc_base, ph["net_ret"].to_numpy(float)),
            "after_vel": calc_q5_monotonicity(sc_base, ph["net_ret_vel"].to_numpy(float)),
        },
        "threshold_ladder_cb": thr_ladder,
        "loo_22_factors": loo_factors,
        "any_factor_flip": flips,
    }


def _extract_1to2_factor_groups(hf_sub: pd.DataFrame, m_fb20: np.ndarray) -> pd.DataFrame:
    """Decompose 1to2 V20 score_active - 25*fb20 into orthogonal factor modules summing exactly to v20_score."""
    df = hf_sub.copy()
    mcap = df["mcap"].fillna(50.0).to_numpy(float)
    amt = df["amount"].fillna(2e8).to_numpy(float)
    dd20 = df["f_dd20_d0"].fillna(0.90).to_numpy(float)
    dd60 = df["f_dd60_d0"].fillna(0.85).to_numpy(float)
    pos20 = df["f_pos20_d0"].fillna(0.50).to_numpy(float)
    d0p = df["f_d0_pct"].fillna(0.0).to_numpy(float)
    ret10 = df["f_ret_pre10"].fillna(0.0).to_numpy(float)
    to = df["to"].fillna(8.0).to_numpy(float)
    vr = df["f_d1_vol_ratio"].fillna(1.5).to_numpy(float)
    zt20 = df["f_zt_cnt_pre20"].fillna(0).to_numpy(int)
    cb60 = df["clean_brk60"].fillna(0).to_numpy(int) == 1
    sr = df["mkt_seal_rate"].fillna(0.55).to_numpy(float)
    dc = df["mkt_dt_cnt"].fillna(5).to_numpy(float)
    zc = df["mkt_zt_cnt"].fillna(50).to_numpy(float)

    sc_mcap = np.where((mcap >= 60) & (mcap <= 155), 28.0, np.where((mcap >= 40) & (mcap < 60), 10.0, np.where(mcap < 35, -20.0, 0.0)))
    sc_amt = np.where((amt >= 2.2e8) & (amt <= 15e8), 18.0, np.where(amt < 1.8e8, -25.0, -10.0))
    sc_dd20 = np.where(dd20 <= 0.82, 42.0, np.where(dd20 <= 0.86, 32.0, np.where(dd20 <= 0.90, 18.0, np.where(dd20 > 0.95, -40.0, 0.0))))
    sc_dd60 = np.where(dd60 <= 0.76, 18.0, np.where(dd60 <= 0.82, 10.0, np.where(dd60 > 0.92, -15.0, 0.0)))
    sc_nshape = np.where((zt20 >= 1) & (dd20 <= 0.86), 22.0, np.where((zt20 >= 1) & (dd20 > 0.92), -20.0, 0.0))
    sc_pos20 = np.where(pos20 <= 0.30, 25.0, np.where(pos20 <= 0.45, 12.0, np.where(pos20 > 0.75, -35.0, 0.0)))
    sc_d0 = np.where(d0p <= -0.010, 25.0, np.where(d0p <= 0.005, 15.0, np.where(d0p > 0.030, -35.0, 0.0)))
    sc_ret10 = np.where(ret10 <= 0.05, 15.0, np.where(ret10 > 0.18, -35.0, 0.0))
    sc_to = np.where(to <= 9.0, 15.0, np.where(to <= 15.0, 8.0, np.where(to > 18.0, -25.0, 0.0)))
    sc_vol = np.where(vr <= 1.75, 15.0, np.where(vr > 2.3, -15.0, 0.0))
    sc_mseal = np.where(sr < 0.64, 18.0, np.where(sr >= 0.72, -25.0, 0.0))
    sc_mdt = np.where(dc <= 6, 12.0, np.where(dc >= 15, -15.0, 0.0))
    sc_mzt = np.where(zc >= 45, 12.0, np.where(zc < 35, -18.0, 0.0))
    # clean_brk60 replaces dd20+dd60+nshape+pos20 with flat +24
    sc_base_shape = np.where(cb60, 24.0, sc_dd20 + sc_dd60 + sc_nshape + sc_pos20)

    has_sub = (df["p_sz"] >= 8) & (df["r_short"] != df["plate"]) & (df["r_short"] != "其他") & (df["r_short"] != "")
    auc_rk = np.where(df["true_buy_rk"] == 1, 35.0, np.where(has_sub & (df["subbranch_rk"] == 1), 24.0, np.where(df["true_buy_rk"] == 2, 8.0, -25.0)))
    auc_mrk = np.where(df["buyable_mkt_open_rk"] <= 3, 20.0, np.where(df["buyable_mkt_open_rk"] <= 6, 12.0, 0.0))
    auc_lead = np.where(df["buy_open_lead"] >= 0.020, 22.0, np.where(df["buy_open_lead"] >= 0.010, 12.0, 0.0))
    auc_yizi = np.where(df["plate_d2_yizi_cnt"] >= 1, 10.0, 0.0)
    auc_op = np.where(df["d2_o_pct"].between(0.040, 0.082), 20.0, np.where(df["d2_o_pct"].between(0.018, 0.040), 12.0, 0.0))

    is_gran = df["is_pioneer_word"] | df["has_new_term"] | df["own_new_term"] | (df["sub_cluster_cnt"] >= 2)
    b_spear = np.where(is_gran, 15.0, 0.0) + np.where(df["s_elo"] >= 105.0, 10.0, np.where(df["s_elo"] <= 95.0, -10.0, 0.0))
    b_wk = np.where(df["gap_days"] >= 3, 10.0, 0.0)
    b_bad = np.where(df["notice_bad"], -35.0, 0.0)

    p_sz_b = np.where(df["p_sz"] >= 4, 18.0, np.where(df["p_sz"] >= 2, 10.0, -15.0))
    cat_nh = np.where(df["notice_hard"], 18.0, 0.0)
    cat_ma = np.where(df["is_ma"], 18.0, 0.0)
    cat_new = np.where(df["has_new_term"], 12.0, 0.0) + np.where(df["own_new_term"], 8.0, 0.0) + np.where(df["spark_bonus"] > 0, 10.0, 0.0)
    selo_b = np.clip((df["s_elo"].to_numpy(float) - 100.0) * 0.35, -10.0, 18.0)
    prior_rest = df["s_prior_dual"].to_numpy(float) - (p_sz_b + cat_nh + cat_ma + cat_new + selo_b)

    # Residual captures y_v17 + name_sub20 + q_pen + d_ov + bon_tape + v18_pen (climax/seal/cap/t3)
    sum_explicit = (
        sc_mcap + sc_amt + sc_base_shape + sc_d0 + sc_ret10 + sc_to + sc_vol + sc_mseal + sc_mdt + sc_mzt
        + auc_rk + auc_mrk + auc_lead + auc_yizi + auc_op
        + b_spear + b_wk + b_bad + p_sz_b + cat_nh + cat_ma + cat_new + selo_b + prior_rest
    )
    tail_v17_v18 = df["score_active"].to_numpy(float) - sum_explicit
    fb20_pen = np.where(m_fb20, -25.0, 0.0)

    out = pd.DataFrame({
        "F01_mcap": sc_mcap, "F02_amt": sc_amt, "F03_dd_shape": sc_base_shape,
        "F04_d0_ret10": sc_d0 + sc_ret10, "F05_to_vol": sc_to + sc_vol,
        "F06_mkt_env": sc_mseal + sc_mdt + sc_mzt,
        "F07_auc_plate_rk": auc_rk, "F08_auc_mkt_rk": auc_mrk,
        "F09_auc_open_lead": auc_lead, "F10_auc_yizi_op": auc_yizi + auc_op,
        "F11_spear_elo_gran": b_spear + selo_b, "F12_wk_gap": b_wk,
        "F13_p_sz": p_sz_b, "F14_catalysts": cat_nh + cat_ma + cat_new,
        "F15_prior_rk_theme": prior_rest,
        "F16_v17_v18_guards": tail_v17_v18 + b_bad,
        "F17_v20_fb20cln": fb20_pen,
    }, index=df.index)
    assert np.max(np.abs(out.sum(axis=1).to_numpy(float) - (df["score_active"].to_numpy(float) + fb20_pen))) < 1e-5
    return out


def sim_1to2_from_pretrig(pt: pd.DataFrame, delta: np.ndarray, ret_col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    sc_adj = pt["base_score"].to_numpy(float) + delta
    m_t1 = pt["elig_t1"].to_numpy(bool) & (sc_adj >= pt["thr_vec"].to_numpy(float))
    m_t2 = pt["elig_t2"].to_numpy(bool)
    m_mon = pt["elig_mon"].to_numpy(bool) & (sc_adj >= pt["thr_vec"].to_numpy(float))
    m_dom = pt["elig_dom295"].to_numpy(bool) & ((sc_adj - pt["sc_t3_pen"].to_numpy(float)) >= 295.0)
    tot_v18 = m_t1 | m_t2 | m_mon
    tot_v19 = tot_v18 | m_dom
    if not tot_v19.any():
        return pd.DataFrame(), pd.DataFrame()
    sv = np.where(m_t1 | m_t2, sc_adj + 1000.0, np.where(m_mon, sc_adj, sc_adj + 500.0))
    sub_all = pt[tot_v19].copy()
    sub_all["_sv"] = sv[tot_v19]
    sub_all["_is_v18"] = tot_v18[tot_v19]
    sub_all["_sc_eff"] = sc_adj[tot_v19]
    bad_dts, dom_nd = set(), set()
    for d, grp in sub_all.groupby("buy_date", sort=False):
        if (grp["rk_theme"] == 1).any():
            top_rk = grp.sort_values("_sv", ascending=False).iloc[0]["rk_theme"]
            if pd.notna(top_rk) and top_rk >= 4:
                bad_dts.add(d)
        t1_p = grp["t1_dom_plate"].iloc[0]
        if t1_p:
            v18_g = grp[grp["_is_v18"]]
            if not (len(v18_g) > 0 and (v18_g["plate"] == t1_p).any()):
                dom_nd.add(d)
    keep_sub = (~sub_all["buy_date"].isin(bad_dts)) & (~(sub_all["buy_date"].isin(dom_nd) & (sub_all["rk_theme"] == 3)))
    sub = sub_all[keep_sub].copy()
    if sub.empty:
        return pd.DataFrame(), pd.DataFrame()
    sub.sort_values(["buy_date", "_sv", "c6"], ascending=[True, False, True], inplace=True)
    picked, fdt, fopen = [], "", False
    for d2, grp in sub.groupby("buy_date", sort=True):
        if fdt == "" or d2 > fdt or (d2 == fdt and fopen):
            top = grp.iloc[0]
            if bool(top["sim_ok"]):
                picked.append(top.to_dict())
                fdt = str(top["exit_date"])
                fopen = bool(top["exit_at_open"])
    return sub[sub["sim_ok"]].copy(), pd.DataFrame(picked)


def audit_1to2_scoring(dmap, m5_bar, sh300, all_sh_dts, cal_dts, dt_to_idx) -> dict:
    for p in (PARTA_DIR, UPG_DIR):
        if p not in sys.path:
            sys.path.insert(0, p)
    import mod_common as mc
    import upgrade_1to2_pit as u12

    fb20_dts = {d for d, c in mc.build_fb20_cln_dates_pit("2026-11-16").items() if c >= 2}

    p12 = pd.read_csv(f"{MW3_DIR}/pool_1to2_full_clean.csv", dtype={"code": str})
    p12_z = apply_vel_slip_df(p12, dmap, m5_bar, mode="base", missing_5m_policy="zero")
    p12_dp = apply_vel_slip_df(p12, dmap, m5_bar, mode="base", missing_5m_policy="daily_proxy")
    p12_st = apply_vel_slip_df(p12, dmap, m5_bar, mode="strict_surge", missing_5m_policy="zero")
    p12_z["net_ret_vel_dproxy"] = p12_dp["net_ret_vel"]
    p12_z["net_ret_strict"] = p12_st["net_ret_vel"]
    p12_z["has_exact_5m"] = p12_z["src_5m"].isin(["auction_0925", "parquet_5m"])
    p12_z["v20_score"] = p12_z["base_score"].to_numpy(float) - np.where(p12_z["buy_date"].isin(fb20_dts), 25.0, 0.0)
    p12_dp["v20_score"] = p12_z["v20_score"]

    cov_pool = p12_z[p12_z["has_exact_5m"]].copy()
    bins_v20 = [
        ("Fail(<295)", -999.0, 295.0),
        ("FB(295-304.7)", 295.0, 304.8),
        ("A_tier(304.8-339.9)", 304.8, 340.0),
        ("S_tier(>=340)", 340.0, 999.0),
    ]

    # Pretrig simulation (V20 threshold shift & fb20_cln penalty grid)
    pt = pd.read_parquet(f"{MW3_DIR}/_cache_pretrig_pool.parquet")
    pt["c6"] = pt["code"].astype(str).str.zfill(6)
    pt["buy_date"] = pt["buy_date"].astype(str).str[:10]
    pt["exit_date"] = pt["exit_date"].astype(str).str[:10]
    pt = pt[pt["buy_date"] >= "2021-11-16"].copy().reset_index(drop=True)
    ok_m = pt["sim_ok"].to_numpy(bool)
    pt_ok = apply_vel_slip_df(pt[ok_m].copy(), dmap, m5_bar, mode="base", missing_5m_policy="zero")
    pt["net_ret_vel"] = pt["net_ret"].to_numpy(float)
    pt.loc[ok_m, "net_ret_vel"] = pt_ok["net_ret_vel"].to_numpy(float)
    pt["eff_buy_price"] = np.nan
    pt.loc[ok_m, "eff_buy_price"] = pt_ok["eff_buy_price"].to_numpy(float)
    pt["has_exact_5m"] = False
    pt.loc[ok_m, "has_exact_5m"] = pt_ok["src_5m"].isin(["auction_0925", "parquet_5m"]).to_numpy(bool)

    m_fb = pt["buy_date"].isin(fb20_dts).to_numpy(bool)
    thr_shift = {}
    for sh_v in (-6.0, -3.0, 0.0, 3.0, 6.0):
        delta = np.where(m_fb, -25.0, 0.0) - sh_v
        rw, sl = sim_1to2_from_pretrig(pt, delta, "net_ret")
        miss_5m_slot = int((~sl["has_exact_5m"]).sum()) if not sl.empty else 0
        dr_b, _ = build_daily_mtm_series(sl, cal_dts, dt_to_idx, dmap, ret_col="net_ret")
        dr_v, _ = build_daily_mtm_series(sl, cal_dts, dt_to_idx, dmap, ret_col="net_ret_vel", buy_px_col="eff_buy_price")
        thr_shift[f"shift_{sh_v:+.0f}"] = {
            "miss_5m_in_slot": miss_5m_slot,
            "before": {wn: calc_d15_window(sl, dr_b, cal_dts, dt_to_idx, sh300, all_sh_dts, sd, ed, "net_ret", rw, "net_ret") for wn, sd, ed in CANON_WINDOWS},
            "after_vel": {wn: calc_d15_window(sl, dr_v, cal_dts, dt_to_idx, sh300, all_sh_dts, sd, ed, "net_ret_vel", rw, "net_ret_vel") for wn, sd, ed in CANON_WINDOWS},
        }

    fb_grid = {}
    for w in (0, 15, 20, 25, 30, 35):
        delta = np.where(m_fb, -float(w), 0.0)
        rw, sl = sim_1to2_from_pretrig(pt, delta, "net_ret")
        dr_b, _ = build_daily_mtm_series(sl, cal_dts, dt_to_idx, dmap, ret_col="net_ret")
        dr_v, _ = build_daily_mtm_series(sl, cal_dts, dt_to_idx, dmap, ret_col="net_ret_vel", buy_px_col="eff_buy_price")
        fb_grid[f"fb20_neg{w}"] = {
            "miss_5m_in_slot": int((~sl["has_exact_5m"]).sum()),
            "before": {wn: calc_d15_window(sl, dr_b, cal_dts, dt_to_idx, sh300, all_sh_dts, sd, ed, "net_ret", rw, "net_ret") for wn, sd, ed in CANON_WINDOWS},
            "after_vel": {wn: calc_d15_window(sl, dr_v, cal_dts, dt_to_idx, sh300, all_sh_dts, sd, ed, "net_ret_vel", rw, "net_ret_vel") for wn, sd, ed in CANON_WINDOWS},
        }

    # Core Factor LOO on 1to2 V20 via u12.build_signals_and_data_pit
    ctx = u12.build_signals_and_data_pit("2026-11-16")
    hf = ctx["hist_fb"].copy()
    hf["c6"] = hf["c6"].astype(str).str.zfill(6)
    hf["buy_date"] = hf["d2_dt"].astype(str).str[:10]
    hf_map = {(r.buy_date, r.c6): i for i, r in enumerate(hf.itertuples(index=False))}
    pt_hf_idx = [hf_map[(r.buy_date, r.c6)] for r in pt.itertuples(index=False)]
    hf_sub = hf.iloc[pt_hf_idx].copy().reset_index(drop=True)
    f_12 = _extract_1to2_factor_groups(hf_sub, m_fb)

    _, base_sl12 = sim_1to2_from_pretrig(pt, np.where(m_fb, -25.0, 0.0), "net_ret")
    b12_full = float(np.prod(1.0 + base_sl12["net_ret"].to_numpy(float)))
    v12_full = float(np.prod(1.0 + base_sl12["net_ret_vel"].to_numpy(float)))
    b12_is = float(np.prod(1.0 + base_sl12[base_sl12["buy_date"] <= "2024-06-30"]["net_ret"].to_numpy(float)))
    v12_is = float(np.prod(1.0 + base_sl12[base_sl12["buy_date"] <= "2024-06-30"]["net_ret_vel"].to_numpy(float)))
    b12_oos = float(np.prod(1.0 + base_sl12[base_sl12["buy_date"] >= "2024-07-04"]["net_ret"].to_numpy(float)))
    v12_oos = float(np.prod(1.0 + base_sl12[base_sl12["buy_date"] >= "2024-07-04"]["net_ret_vel"].to_numpy(float)))

    # Map factor matrix onto covered pool (N=219) for marginal pool IC
    cov_keys = list(zip(cov_pool["buy_date"], cov_pool["c6"]))
    pt_key_map = {(r.buy_date, r.c6): idx for idx, r in enumerate(pt.itertuples(index=False))}
    cov_pt_idxs = [pt_key_map[k] for k in cov_keys]

    loo_12, flips_12 = [], []
    for col in f_12.columns:
        fv = f_12[col].to_numpy(float)
        # Drop factor col from V20 score (note F17_v20_fb20cln drops the -25 fb20 penalty)
        delta_drop = np.where(m_fb, -25.0, 0.0) - fv
        _, sl_j = sim_1to2_from_pretrig(pt, delta_drop, "net_ret")
        def _ns(df_s, rc):
            if df_s.empty:
                return 1.0, 1.0, 1.0, 0, 0
            return (
                float(np.prod(1.0 + df_s[rc].to_numpy(float))),
                float(np.prod(1.0 + df_s[df_s["buy_date"] <= "2024-06-30"][rc].to_numpy(float))),
                float(np.prod(1.0 + df_s[df_s["buy_date"] >= "2024-07-04"][rc].to_numpy(float))),
                int(len(df_s)),
                int((~df_s["has_exact_5m"]).sum()),
            )
        bf, bi, bo, nj, nm5 = _ns(sl_j, "net_ret")
        vf, vi, vo, _, _ = _ns(sl_j, "net_ret_vel")
        d_full_b, d_full_v = b12_full - bf, v12_full - vf
        fv_cov = fv[cov_pt_idxs]
        r_b, _ = stats.spearmanr(fv_cov, cov_pool["net_ret"]) if np.std(fv_cov) > 0 else (0.0, 1.0)
        r_v, _ = stats.spearmanr(fv_cov, cov_pool["net_ret_vel"]) if np.std(fv_cov) > 0 else (0.0, 1.0)
        ic_flip = (r_b * r_v < -1e-6)
        loo_flip = ((d_full_b > 1e-6 and d_full_v < -1e-6) or (d_full_b < -1e-6 and d_full_v > 1e-6))
        if ic_flip or loo_flip:
            flips_12.append(col)
        loo_12.append({
            "factor": col, "drop_n": nj, "miss_5m_in_drop_slot": nm5,
            "before_delta_nav_full": sf(d_full_b, 2), "vel_delta_nav_full": sf(d_full_v, 2),
            "before_delta_nav_is": sf(b12_is - bi, 3), "vel_delta_nav_is": sf(v12_is - vi, 3),
            "before_delta_nav_oos": sf(b12_oos - bo, 2), "vel_delta_nav_oos": sf(v12_oos - vo, 2),
            "before_cov_pool_ic": sf(r_b, 4), "vel_cov_pool_ic": sf(r_v, 4),
            "ic_sign_flip": bool(ic_flip), "loo_full_sign_flip": bool(loo_flip),
        })

    thr_ladder_pool_12 = {}
    for th in (285.0, 295.0, 304.8, 315.0, 325.0, 340.0):
        thr_ladder_pool_12[str(th)] = {
            "exact_5m_cov": {
                "before": tier_breakdown_pool(cov_pool, "v20_score", "net_ret", [(f"ge_{th}", th, 999.0), (f"lt_{th}", -999.0, th)]),
                "after_vel": tier_breakdown_pool(cov_pool, "v20_score", "net_ret_vel", [(f"ge_{th}", th, 999.0), (f"lt_{th}", -999.0, th)]),
            },
            "full_447_daily_proxy": {
                "before": tier_breakdown_pool(p12_dp, "v20_score", "net_ret", [(f"ge_{th}", th, 999.0), (f"lt_{th}", -999.0, th)]),
                "after_vel": tier_breakdown_pool(p12_dp, "v20_score", "net_ret_vel", [(f"ge_{th}", th, 999.0), (f"lt_{th}", -999.0, th)]),
            },
        }

    return {
        "pool_total_size": int(len(p12_z)),
        "pool_exact_5m_covered_size": int(len(cov_pool)),
        "pool_exact_5m_ge3048_cov": f"{int(p12_z[p12_z['base_score']>=304.8]['has_exact_5m'].sum())}/{int((p12_z['base_score']>=304.8).sum())}",
        "vel_tier_counts_cov_pool": cov_pool["vel_tier"].value_counts().to_dict(),
        "threshold_ladder_pool_v20": thr_ladder_pool_12,
        "exact_5m_covered_pool": {
            "tier_breakdown_v20": {
                "before": tier_breakdown_pool(cov_pool, "v20_score", "net_ret", bins_v20),
                "after_vel": tier_breakdown_pool(cov_pool, "v20_score", "net_ret_vel", bins_v20),
            },
            "spearman_ic_v20": {
                "before": calc_spearman_windows(cov_pool, "v20_score", "net_ret"),
                "after_vel": calc_spearman_windows(cov_pool, "v20_score", "net_ret_vel"),
                "after_strict": calc_spearman_windows(cov_pool, "v20_score", "net_ret_strict"),
            },
            "spearman_ic_base": {
                "before": calc_spearman_windows(cov_pool, "base_score", "net_ret"),
                "after_vel": calc_spearman_windows(cov_pool, "base_score", "net_ret_vel"),
            },
            "q5_monotonicity_v20": {
                "before": calc_q5_monotonicity(cov_pool["v20_score"].to_numpy(float), cov_pool["net_ret"].to_numpy(float)),
                "after_vel": calc_q5_monotonicity(cov_pool["v20_score"].to_numpy(float), cov_pool["net_ret_vel"].to_numpy(float)),
            },
        },
        "full_pool_447_with_missing_imputation": {
            "spearman_ic_v20_zero_for_missing": {
                "before": calc_spearman_windows(p12_z, "v20_score", "net_ret"),
                "after_vel": calc_spearman_windows(p12_z, "v20_score", "net_ret_vel"),
            },
            "spearman_ic_v20_daily_proxy_for_missing": {
                "before": calc_spearman_windows(p12_dp, "v20_score", "net_ret"),
                "after_vel": calc_spearman_windows(p12_dp, "v20_score", "net_ret_vel"),
            },
            "tier_breakdown_v20_daily_proxy": {
                "before": tier_breakdown_pool(p12_dp, "v20_score", "net_ret", bins_v20),
                "after_vel": tier_breakdown_pool(p12_dp, "v20_score", "net_ret_vel", bins_v20),
            },
        },
        "v20_threshold_shift_grid": thr_shift,
        "v20_fb20cln_penalty_grid": fb_grid,
        "loo_17_factor_groups": loo_12,
        "any_factor_flip": flips_12,
    }
