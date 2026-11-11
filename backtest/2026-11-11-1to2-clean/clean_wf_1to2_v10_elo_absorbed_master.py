#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v10_elo_absorbed_master.py
================================================================================
100% Zero-Lookahead Absorption of fast_1to2_today.py's 6 Core Gems + Dual-Layer Sub-Theme Elo
+ Intraday trig_p Confirmation + Expanding Walk-Forward Hybrid Master (2021-2026 Full 5Y + Delisted + PIT Notices)
================================================================================
"""
import json
import os
import time
import urllib.request
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from v10_core_features import load_full_5y_prices, build_5y_elo_and_candidates
from v10_pit_and_sim import attach_pit_notices_and_scores, CSI300_ANNUAL, CSI300_5Y_CUM, FEE_RATE
from v10_backtest_eval import compute_d2_auction_scores, simulate_single_trade

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
OUT_JSON = f"{OUT_DIR}/clean_wf_1to2_v10_elo_absorbed_master_results.json"
OUT_CSV = f"{OUT_DIR}/clean_wf_1to2_v10_elo_absorbed_master_ledger.csv"


def summarize_trades(tr_list):
    if not tr_list:
        return {"n": 0, "wr": 0.0, "payoff": 0.0, "seal2b": 0.0}
    rets = np.array([t["net_ret"] for t in tr_list])
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = float(len(wins) / len(rets))
    aw = float(wins.mean()) if len(wins) else 0.0
    al = float(abs(losses.mean())) if len(losses) else 0.01
    return {
        "n": int(len(rets)), "wr": round(wr, 4),
        "payoff": round(aw / al if al > 0 else 0.0, 2),
        "seal2b": round(float(np.mean([t["sealed_2b"] for t in tr_list])), 4),
    }


def eval_scheme_d15(cand_df, score_col, mask_series, price_lookup, all_dts, dt_to_idx, entry_mode="trig", exit_mode="E4", fee=FEE_RATE):
    sub = cand_df[mask_series & (cand_df["d2_dt"] >= "2022-01-01") & (cand_df["d2_dt"] <= "2026-11-10")].copy()
    sub.sort_values(["d2_dt", score_col], ascending=[True, False], inplace=True)

    # 1. Strict Pre-Committed Top-1 1-Slot (zero peeking if #1 misses trig_p!)
    free_dt, free_open = "", False
    nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0
    trades_1s = []
    # 2. Strict Pre-Committed Top-2 2-Slot
    slot_dt = ["", ""]
    slot_open = [False, False]
    slot_cap = [0.5, 0.5]
    peak_2s, mdd_2s = 1.0, 0.0
    trades_2s = []
    # 3. Same-Day All-Triggered Equal-Weight (D15 Check 1)
    eq_daily_rets = []

    for d2, grp in sub.groupby("d2_dt", sort=True):
        rows = [r._asdict() if hasattr(r, "_asdict") else r.to_dict() for _, r in grp.iterrows()]
        # 1-Slot: strictly commit to Top-1 at 09:25 ONLY
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            tr1 = simulate_single_trade(rows[0], price_lookup, all_dts, dt_to_idx, entry_mode, exit_mode, fee)
            if tr1 is not None:
                nav_1s *= (1.0 + tr1["net_ret"])
                peak_1s = max(peak_1s, nav_1s)
                mdd_1s = max(mdd_1s, (peak_1s - nav_1s) / peak_1s)
                free_dt, free_open = tr1["exit_date"], tr1["exit_at_open"]
                trades_1s.append(tr1)

        # 2-Slot: commit at most Top-2 at 09:25
        for r_cand in rows[:2]:
            s_chosen = -1
            for si in range(2):
                if slot_dt[si] == "" or d2 > slot_dt[si] or (d2 == slot_dt[si] and slot_open[si]):
                    s_chosen = si; break
            if s_chosen != -1:
                tr2 = simulate_single_trade(r_cand, price_lookup, all_dts, dt_to_idx, entry_mode, exit_mode, fee)
                if tr2 is not None:
                    slot_cap[s_chosen] *= (1.0 + tr2["net_ret"])
                    slot_dt[s_chosen], slot_open[s_chosen] = tr2["exit_date"], tr2["exit_at_open"]
                    trades_2s.append(tr2)
                    c_nav2 = slot_cap[0] + slot_cap[1]
                    peak_2s = max(peak_2s, c_nav2)
                    mdd_2s = max(mdd_2s, (peak_2s - c_nav2) / peak_2s)

        # Daily Equal-Weight across all triggered candidates on d2
        day_r = []
        for r_all in rows:
            tra = simulate_single_trade(r_all, price_lookup, all_dts, dt_to_idx, entry_mode, exit_mode, fee)
            if tra is not None:
                day_r.append(tra["net_ret"])
        if day_r:
            eq_daily_rets.append((d2, float(np.mean(day_r))))

    nav_eq, pk_eq, mdd_eq = 1.0, 1.0, 0.0
    for _, mr in eq_daily_rets:
        nav_eq *= (1.0 + mr); pk_eq = max(pk_eq, nav_eq); mdd_eq = max(mdd_eq, (pk_eq - nav_eq) / pk_eq)

    annual = {}
    for yr in [2022, 2023, 2024, 2025, 2026]:
        ys = str(yr)
        yt1 = [t for t in trades_1s if t["buy_date"].startswith(ys)]
        yt2 = [t for t in trades_2s if t["buy_date"].startswith(ys)]
        yeq = [r for d, r in eq_daily_rets if d.startswith(ys)]
        st1 = summarize_trades(yt1)
        ynav1, ypk1, ymdd1 = 1.0, 1.0, 0.0
        for t in yt1:
            ynav1 *= (1.0 + t["net_ret"]); ypk1 = max(ypk1, ynav1); ymdd1 = max(ymdd1, (ypk1 - ynav1) / ypk1)
        ynav2 = float(np.prod([1.0 + 0.5 * t["net_ret"] for t in yt2])) if yt2 else 1.0
        ynaveq = float(np.prod([1.0 + r for r in yeq])) if yeq else 1.0
        bench = CSI300_ANNUAL[yr]
        annual[str(yr)] = {
            "trades_1slot": st1["n"], "win_rate": st1["wr"], "payoff": st1["payoff"], "seal_2b_rate": st1["seal2b"],
            "nav_1slot": round(ynav1, 4), "nav_2slot": round(ynav2, 4), "nav_daily_eq": round(ynaveq, 4),
            "mdd_1slot": round(ymdd1, 4), "csi300": bench, "excess_1slot": round((ynav1 - 1.0) - bench, 4),
        }

    s_all = summarize_trades(trades_1s)
    s_3y = summarize_trades([t for t in trades_1s if t["buy_date"] >= "2024-01-01"])
    s_1y = summarize_trades([t for t in trades_1s if t["buy_date"] >= "2026-01-01"])
    nav_2s_tot = slot_cap[0] + slot_cap[1]
    return {
        "total_trades_1slot": s_all["n"], "win_rate_5y": s_all["wr"], "payoff_5y": s_all["payoff"], "seal_2b_5y": s_all["seal2b"],
        "win_rate_3y": s_3y["wr"], "payoff_3y": s_3y["payoff"],
        "win_rate_2026": s_1y["wr"], "payoff_2026": s_1y["payoff"],
        "cum_nav_1slot": round(nav_1s, 4), "mdd_1slot": round(mdd_1s, 4),
        "cum_nav_2slot": round(nav_2s_tot, 4), "mdd_2slot": round(mdd_2s, 4),
        "cum_nav_daily_eq": round(nav_eq, 4), "mdd_daily_eq": round(mdd_eq, 4),
        "csi300_5y_cum": round(CSI300_5Y_CUM, 4),
        "net_excess_5y_1slot": round((nav_1s - 1.0) - CSI300_5Y_CUM, 4),
        "annual": annual, "trades": trades_1s,
    }


def run_master():
    t0 = time.time()
    df = load_full_5y_prices()
    df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = build_5y_elo_and_candidates(df)
    fb_all = attach_pit_notices_and_scores(df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map)

    # Split historical D2 (<= 2026-11-10) vs Today Live (D1 == 2026-11-10 -> D2 == 2026-11-11)
    hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy()
    hist_fb = compute_d2_auction_scores(hist_fb)

    all_dts = sorted(df["dt_str"].unique())
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
        for r in df[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
    }

    # Precompute E4 & B1 trig_p targets for Expanding Walk-Forward ML (strictly using training years < test_yr)
    y_b1 = np.full(len(hist_fb), np.nan)
    for i, (_, r) in enumerate(hist_fb.iterrows()):
        if r["is_buyable_open"] and (0.018 <= r["d2_o_pct"] <= 0.085):
            tr = simulate_single_trade(r, price_lookup, all_dts, dt_to_idx, entry_mode="trig", exit_mode="B1", fee=FEE_RATE)
            if tr is not None:
                y_b1[i] = np.clip(tr["net_ret"], -0.15, 0.35)
    hist_fb["y_b1_trig"] = y_b1
    hist_fb["d2_yr"] = hist_fb["d2_dt"].str[:4].astype(int)

    # 1. Calibrate S1B threshold strictly on 2021 pre-sample ONLY (matching S1A's 2021 pass count, zero 2022-2026 peeking!)
    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    fb_2021 = hist_fb[(hist_fb["d2_yr"] == 2021) & common_ok]
    n_s1a_2021 = int((fb_2021["d2_o_pct"].between(0.030, 0.082) & (fb_2021["s_prior_orig"] >= 35.0) & (fb_2021["s_quant_orig"] >= 140.0) & (fb_2021["tot_orig"] >= fb_2021["tot_thr"])).sum())
    pool_2021_dual = fb_2021[fb_2021["d2_o_pct"].between(0.022, 0.082) & (fb_2021["s_prior_dual"] >= 45.0) & (fb_2021["s_quant_dual"] >= 150.0)]["tot_dual"].values
    # Match top selectivity (~top 40% stricter than raw S1A pass pool on 2021 alone)
    target_2021_k = max(15, int(n_s1a_2021 * 0.65))
    s1b_base_thr = float(np.sort(pool_2021_dual)[-target_2021_k]) if len(pool_2021_dual) > target_2021_k else 280.0
    s1b_base_thr = round(s1b_base_thr, 1)
    print(f"[2021 Pre-Sample Calibration] S1A_2021_cands={n_s1a_2021}, S1B_calibrated_base_thr={s1b_base_thr} (climax +25)")

    # 2. Expanding Walk-Forward Ridge Refinement (S2_V10_Hybrid_WF: 100% < test_yr training & threshold!)
    ml_feats = [
        "s_prior_dual", "s_q_base_dual", "p_elo", "s_elo", "p_sz", "has_new_term", "own_new_term",
        "spark_bonus", "is_ma", "notice_hard", "clean_brk60", "mkt_seal_rate", "d2_o_pct",
        "buyable_plate_rk", "subbranch_rk", "mkt_open_rk", "buy_open_lead", "plate_d2_yizi_cnt"
    ]
    for c in ml_feats:
        hist_fb[c] = hist_fb[c].fillna(0.0)

    hist_fb["ml_adj"] = 0.0
    hist_fb["wf_dyn_thr"] = 285.0
    wf_models_2026 = None
    wf_thr_2026 = s1b_base_thr

    for test_yr in [2022, 2023, 2024, 2025, 2026]:
        tr_domain = (hist_fb["d2_yr"] < test_yr) & common_ok & hist_fb["d2_o_pct"].between(0.022, 0.082) & (hist_fb["s_prior_dual"] >= 45.0) & (hist_fb["s_quant_dual"] >= 145.0)
        tr_fit = tr_domain & hist_fb["y_b1_trig"].notna()
        te_mask = (hist_fb["d2_yr"] == test_yr)
        tr_df, te_df = hist_fb[tr_fit], hist_fb[te_mask]
        if len(tr_df) >= 30 and len(te_df) > 0:
            sc = StandardScaler()
            X_tr = sc.fit_transform(tr_df[ml_feats].values)
            y_tr = tr_df["y_b1_trig"].values
            ridge = Ridge(alpha=50.0).fit(X_tr, y_tr)
            # Zero-mean standardized ML adjustment (+/- ~18 pts max) on top of M2_DualElo backbone
            p_tr_all = ridge.predict(sc.transform(hist_fb.loc[tr_domain, ml_feats].values))
            p_mean, p_std = float(np.mean(p_tr_all)), float(np.std(p_tr_all) + 1e-6)
            z_tr = np.clip((p_tr_all - p_mean) / p_std, -2.0, 2.0) * 10.0
            tr_hyb_scores = hist_fb.loc[tr_domain, "tot_dual"].values + z_tr
            n_yrs = float(test_yr - 2021)
            target_cands = max(18, int(42 * n_yrs))
            wf_base_thr = float(np.sort(tr_hyb_scores)[-target_cands]) if len(tr_hyb_scores) > target_cands else s1b_base_thr

            p_te = ridge.predict(sc.transform(te_df[ml_feats].values))
            z_te = np.clip((p_te - p_mean) / p_std, -2.0, 2.0) * 10.0
            hist_fb.loc[te_mask, "ml_adj"] = z_te
            hist_fb.loc[te_mask, "wf_dyn_thr"] = np.where(te_df["mkt_seal_rate"] > 0.75, wf_base_thr + 25.0, wf_base_thr)
            if test_yr == 2026:
                wf_models_2026 = (sc, ridge, p_mean, p_std)
                wf_thr_2026 = wf_base_thr

    hist_fb["tot_v10_hybrid"] = hist_fb["tot_dual"] + hist_fb["ml_adj"]
    s1b_thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, s1b_base_thr + 25.0, s1b_base_thr)

    m_s1a = common_ok & hist_fb["d2_o_pct"].between(0.030, 0.082) & (hist_fb["s_prior_orig"] >= 35.0) & (hist_fb["s_quant_orig"] >= 140.0) & (hist_fb["tot_orig"] >= hist_fb["tot_thr"])
    m_s1b = common_ok & hist_fb["d2_o_pct"].between(0.022, 0.082) & (hist_fb["s_prior_dual"] >= 45.0) & (hist_fb["s_quant_dual"] >= 150.0) & (hist_fb["tot_dual"] >= s1b_thr_vec)
    m_v10 = common_ok & hist_fb["d2_o_pct"].between(0.022, 0.082) & (hist_fb["s_prior_dual"] >= 45.0) & (hist_fb["s_quant_dual"] >= 150.0) & (hist_fb["tot_v10_hybrid"] >= hist_fb["wf_dyn_thr"])

    results = {
        "meta": {
            "fee_rate": FEE_RATE, "s1b_2021_calibrated_thr": s1b_base_thr, "wf_2026_thr": round(wf_thr_2026, 1),
            "csi300_annual": CSI300_ANNUAL, "csi300_5y_cum": round(CSI300_5Y_CUM, 4),
        },
        "schemes": {},
    }
    configs = [
        ("S1A_M2_Clean_Open_E4", "tot_orig", m_s1a, "open", "E4"),
        ("S1A_M2_Clean_Trig_E4", "tot_orig", m_s1a, "trig", "E4"),
        ("S1A_M2_Clean_Trig_B1", "tot_orig", m_s1a, "trig", "B1"),
        ("S1A_M2_Clean_Trig_P2", "tot_orig", m_s1a, "trig", "P2"),
        ("S1B_M2_DualElo_Trig_E4", "tot_dual", m_s1b, "trig", "E4"),
        ("S1B_M2_DualElo_Trig_E7", "tot_dual", m_s1b, "trig", "E7"),
        ("S1B_M2_DualElo_Trig_B1", "tot_dual", m_s1b, "trig", "B1"),
        ("S1B_M2_DualElo_Trig_P2", "tot_dual", m_s1b, "trig", "P2"),
        ("S2_V10_Hybrid_WF_Trig_E4", "tot_v10_hybrid", m_v10, "trig", "E4"),
        ("S2_V10_Hybrid_WF_Trig_E7", "tot_v10_hybrid", m_v10, "trig", "E7"),
        ("S2_V10_Hybrid_WF_Trig_B1", "tot_v10_hybrid", m_v10, "trig", "B1"),
        ("S2_V10_Hybrid_WF_Trig_P2", "tot_v10_hybrid", m_v10, "trig", "P2"),
    ]
    print("\n=== 5Y Walk-Forward Clean Results (2022-2026, Delisted Incl, PIT Notices <= D2 09:25) ===")
    for name, scol, msk, em, xm in configs:
        res = eval_scheme_d15(hist_fb, scol, msk, price_lookup, all_dts, dt_to_idx, em, xm, FEE_RATE)
        results["schemes"][name] = {k: v for k, v in res.items() if k != "trades"}
        if name in ("S1B_M2_DualElo_Trig_E4", "S1B_M2_DualElo_Trig_B1", "S2_V10_Hybrid_WF_Trig_E4", "S2_V10_Hybrid_WF_Trig_B1"):
            results[f"ledger_{name}"] = res["trades"]
        print(
            f"{name:<26s} | N={res['total_trades_1slot']:3d} | WR={res['win_rate_5y']*100:5.1f}% | Payoff={res['payoff_5y']:4.2f} "
            f"| 2B={res['seal_2b_5y']*100:5.1f}% | 1S={res['cum_nav_1slot']:6.2f}x (MDD={res['mdd_1slot']*100:4.1f}%) "
            f"| 2S={res['cum_nav_2slot']:6.2f}x | EQ={res['cum_nav_daily_eq']:6.2f}x | Excess={res['net_excess_5y_1slot']*100:+6.1f}%"
        )

    # ±10% Perturbation Stress Test on S1B_DualElo & S2_V10_Hybrid (E4 & B1)
    perturb = {}
    for mult, tag in [(0.90, "Loose_-10%"), (0.95, "Loose_-5%"), (1.00, "Base_0%"), (1.05, "Tight_+5%"), (1.10, "Tight_+10%")]:
        p_thr = np.where(hist_fb["mkt_seal_rate"] > 0.75, s1b_base_thr * mult + 25.0, s1b_base_thr * mult)
        mp_s1b = common_ok & hist_fb["d2_o_pct"].between(0.022 * mult, min(0.090, 0.082 / mult)) & (hist_fb["s_prior_dual"] >= 45.0 * mult) & (hist_fb["s_quant_dual"] >= 150.0 * mult) & (hist_fb["tot_dual"] >= p_thr)
        rp_e4 = eval_scheme_d15(hist_fb, "tot_dual", mp_s1b, price_lookup, all_dts, dt_to_idx, "trig", "E4", FEE_RATE)
        rp_b1 = eval_scheme_d15(hist_fb, "tot_dual", mp_s1b, price_lookup, all_dts, dt_to_idx, "trig", "B1", FEE_RATE)
        perturb[tag] = {
            "E4": {"n": rp_e4["total_trades_1slot"], "wr": rp_e4["win_rate_5y"], "payoff": rp_e4["payoff_5y"], "nav_1s": rp_e4["cum_nav_1slot"], "mdd_1s": rp_e4["mdd_1slot"], "nav_2s": rp_e4["cum_nav_2slot"], "nav_eq": rp_e4["cum_nav_daily_eq"]},
            "B1": {"n": rp_b1["total_trades_1slot"], "wr": rp_b1["win_rate_5y"], "payoff": rp_b1["payoff_5y"], "nav_1s": rp_b1["cum_nav_1slot"], "mdd_1s": rp_b1["mdd_1slot"], "nav_2s": rp_b1["cum_nav_2slot"], "nav_eq": rp_b1["cum_nav_daily_eq"]},
        }
    results["perturbation_s1b"] = perturb
    print("Perturbation S1B:", json.dumps(perturb, ensure_ascii=False))

    # Today 2026-11-11 Live Forensic & Selection Verification
    live_fb = fb_all[fb_all["dt_str"] == "2026-11-10"].copy()
    live_fb["d2_dt"] = "2026-11-11"
    q_codes = [("sh" + c if c.startswith("6") else "sz" + c) for c in live_fb["c6"].tolist()]
    live_q = {}
    try:
        txt = urllib.request.urlopen("http://qt.gtimg.cn/q=" + ",".join(q_codes), timeout=5).read().decode("gbk", errors="ignore")
        for ln in txt.strip().splitlines():
            if '="' not in ln: continue
            k, v = ln.split('="', 1); p = v.strip('";').split("~")
            if len(p) > 35:
                live_q[k[-6:]] = (float(p[5] or 0), float(p[33] or 0), float(p[34] or 0), float(p[3] or 0))
    except Exception as e:
        print("Live fetch warn:", e)

    live_fb["d2_open"] = [live_q.get(c, (0, 0, 0, 0))[0] for c in live_fb["c6"]]
    live_fb["d2_high"] = [live_q.get(c, (0, 0, 0, 0))[1] for c in live_fb["c6"]]
    live_fb["d2_low"] = [live_q.get(c, (0, 0, 0, 0))[2] for c in live_fb["c6"]]
    live_fb["d2_close"] = [live_q.get(c, (0, 0, 0, 0))[3] for c in live_fb["c6"]]
    live_fb["d2_o_pct"] = np.where(live_fb["d2_open"] > 0, live_fb["d2_open"] / live_fb["close"] - 1.0, -0.99)
    live_fb["d2_zt_p"] = np.floor(live_fb["close"] * 1.10 * 100.0 + 0.5) / 100.0
    live_fb["d2_is_yizi"] = (live_fb["d2_open"] >= live_fb["d2_zt_p"] - 0.01) & (live_fb["d2_low"] >= live_fb["d2_zt_p"] - 0.01)
    live_fb = compute_d2_auction_scores(live_fb)

    if wf_models_2026 is not None and len(live_fb) > 0:
        sc, ridge, p_mean, p_std = wf_models_2026
        for c in ml_feats: live_fb[c] = live_fb[c].fillna(0.0)
        p_lv = ridge.predict(sc.transform(live_fb[ml_feats].values))
        live_fb["ml_adj"] = np.clip((p_lv - p_mean) / p_std, -2.0, 2.0) * 10.0
        live_fb["tot_v10_hybrid"] = live_fb["tot_dual"] + live_fb["ml_adj"]
    else:
        live_fb["tot_v10_hybrid"] = live_fb["tot_dual"]

    lv_s1b_thr = np.where(live_fb["mkt_seal_rate"] > 0.75, s1b_base_thr + 25.0, s1b_base_thr)
    lv_v10_thr = np.where(live_fb["mkt_seal_rate"] > 0.75, wf_thr_2026 + 25.0, wf_thr_2026)
    lv_com = live_fb["is_buyable_open"] & (~live_fb["nuclear_halt"]) & (~live_fb["promo_freeze"]) & live_fb["d2_o_pct"].between(0.022, 0.082) & (live_fb["s_prior_dual"] >= 45.0) & (live_fb["s_quant_dual"] >= 150.0)
    live_fb["ok_s1b"] = lv_com & (live_fb["tot_dual"] >= lv_s1b_thr)
    live_fb["ok_v10"] = lv_com & (live_fb["tot_v10_hybrid"] >= lv_v10_thr)
    live_fb["hit_trig"] = (live_fb["d2_high"] >= live_fb["trig_p"]) & (live_fb["d2_open"] < live_fb["d2_zt_p"] - 0.005)
    live_fb["intraday_ret_from_trig"] = np.where(live_fb["hit_trig"], live_fb["d2_close"] / live_fb["trig_p"] - 1.0, 0.0)

    live_top = live_fb.sort_values(["ok_v10", "tot_v10_hybrid"], ascending=[False, False]).head(12)
    live_records = []
    print(f"\n=== 2026-11-11 Live V10 Candidates (Climax Thr: S1B={float(lv_s1b_thr[0]):.1f}, V10={float(lv_v10_thr[0]):.1f}) ===")
    for _, r in live_top.iterrows():
        rec = {
            "c6": r["c6"], "name": r["name"], "plate": r["plate"], "r_short": r["r_short"],
            "ok_s1b": bool(r["ok_s1b"]), "ok_v10": bool(r["ok_v10"]),
            "tot_orig": round(float(r["tot_orig"]), 1), "tot_dual": round(float(r["tot_dual"]), 1), "tot_v10": round(float(r["tot_v10_hybrid"]), 1),
            "o_pct": round(float(r["d2_o_pct"]), 4), "open_p": round(float(r["d2_open"]), 2),
            "trig_p": round(float(r["trig_p"]), 2), "high_p": round(float(r["d2_high"]), 2), "cur_p": round(float(r["d2_close"]), 2),
            "hit_trig": bool(r["hit_trig"]), "intraday_pnl": round(float(r["intraday_ret_from_trig"]), 4),
        }
        live_records.append(rec)
        print(
            f"V10_OK={int(rec['ok_v10'])} S1B_OK={int(rec['ok_s1b'])} | {rec['c6']} {rec['name']:<6s} | {rec['plate']}({rec['r_short']}) "
            f"| V10={rec['tot_v10']:5.1f} Dual={rec['tot_dual']:5.1f} Orig={rec['tot_orig']:5.1f} "
            f"| op={rec['o_pct']*100:+5.2f}% trig={rec['trig_p']:6.2f} cur={rec['cur_p']:6.2f}(hi={rec['high_p']:6.2f}) | hit={int(rec['hit_trig'])} pnl={rec['intraday_pnl']*100:+5.2f}%"
        )
    results["live_20261111"] = live_records

    all_ledger = []
    for k in ("S1B_M2_DualElo_Trig_E4", "S1B_M2_DualElo_Trig_B1", "S2_V10_Hybrid_WF_Trig_E4", "S2_V10_Hybrid_WF_Trig_B1"):
        for t in results.pop(f"ledger_{k}", []):
            tc = dict(t); tc["scheme"] = k; all_ledger.append(tc)
    pd.DataFrame(all_ledger).to_csv(OUT_CSV, index=False, encoding="utf-8")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[DONE] Total runtime={time.time()-t0:.2f}s | Saved {OUT_JSON} & {OUT_CSV}")


if __name__ == "__main__":
    run_master()
