#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import sys, json
import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock")
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean")
from master_5y_zero_lookahead_walkforward import (
    load_all_data, create_master_trade_engine, evaluate_strategy_master, FEE_RATE, FEE_RATE_DISCOUNT
)
from forensic_audit_v14 import run_audit

hist_fb, price_lookup, all_dts, dt_to_idx = load_all_data()

is_granularity = (
    hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
)
s_elo_impact = np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))
bonus_spear = np.where(is_granularity, 15.0, 0.0) + s_elo_impact

common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
pass_layer1_orig = (~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))
pass_layer2 = (~hist_fb["is_dying_pulse"])
pass_layer3 = (
    (hist_fb["plate_fb_cnt"] <= 1)
    | (
        (hist_fb["plate_peers_open_avg"] >= -0.010)
        & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2))
    )
)
pass_no_decoy = (
    (~((hist_fb["p_sz"] >= 2) & (hist_fb["buyable_plate_rk"] >= 3)))
    & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))))
)
m_t2_base = (
    common_ok
    & (hist_fb["p_sz"] == 1)
    & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"])
    & hist_fb["d2_o_pct"].between(0.035, 0.078)
    & (hist_fb["buyable_mkt_open_rk"] <= 3)
    & (hist_fb["d1_seal_tightness"] >= 15.0)
    & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
)

thr_vec_304 = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)
hist_fb["score_0"] = hist_fb["score_dual"] + bonus_spear
hist_fb["s_prior_0"] = hist_fb["s_prior_dual"] + bonus_spear

wk_mask = hist_fb["gap_days"] >= 3
f3_bonus = np.where(hist_fb["notice_hard"], 8.0, 0.0) + np.where(hist_fb["notice_bad"], -35.0, 0.0)
pass_anti_climax = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])

hist_fb["score_wk"] = hist_fb["score_0"] + np.where(wk_mask, 10.0, 0.0) + f3_bonus
hist_fb["s_prior_wk"] = hist_fb["s_prior_0"] + np.where(wk_mask, 10.0, 0.0) + f3_bonus
hist_fb["score_active"] = hist_fb["score_wk"]

m_t1_wk = (
    common_ok
    & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078)))
    & (hist_fb["s_prior_wk"] >= 45.0)
    & (hist_fb["s_quant_dual"] >= 150.0)
    & (hist_fb["score_wk"] >= thr_vec_304)
)
msk_champ = (m_t1_wk & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy & pass_anti_climax) | (m_t2_base & pass_layer2)

fn_champ = create_master_trade_engine(
    price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005,
    lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE
)
fn_champ_15 = create_master_trade_engine(
    price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005,
    lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE_DISCOUNT
)

res_base = evaluate_strategy_master(hist_fb, "score_active", msk_champ, fn_champ, desc="Base_Champ")
base_dates = {t["buy_date"]: t for t in res_base["trades_list"]}

print("=== 1. PLATEAU GRID AROUND MONDAY SUB-GATE RELAXATION (score_wk >= 304.8 strictly kept!) ===")
for sp_min in [35.0, 38.0, 40.0, 42.0]:
    for sq_min in [140.0, 145.0, 150.0]:
        for o_lo in [0.010, 0.015, 0.018]:
            for o_hi in [0.088, 0.090]:
                m_b = (
                    common_ok & wk_mask & hist_fb["d2_o_pct"].between(o_lo, o_hi)
                    & (hist_fb["s_prior_wk"] >= sp_min) & (hist_fb["s_quant_dual"] >= sq_min)
                    & (hist_fb["score_wk"] >= thr_vec_304)
                    & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy & pass_anti_climax
                )
                hist_fb["_tmp_sort"] = np.where(msk_champ, hist_fb["score_active"] + 1000.0, hist_fb["score_active"])
                r = evaluate_strategy_master(hist_fb, "_tmp_sort", msk_champ | (m_b & (~msk_champ)), fn_champ, desc="grid")
                print(f"sp>={sp_min:4.1f} sq>={sq_min:5.1f} o=[{o_lo:.3f},{o_hi:.3f}] -> trades={r['trades_5y']:3d}, wr={r['wr_5y']:4.1f}%, nav_1s={r['nav_1s']:6.2f}x, mdd={r['mdd_1s']:4.1f}%, nav_2s={r['nav_2s']:5.2f}x, eq={r['daily_eq']:5.2f}x")

# Inspect plateau center: sp>=38.0, sq>=145.0, o=[0.015, 0.090] vs sp>=38.0, sq>=150.0, o=[0.015, 0.090]
for label, sp_c, sq_c, o_l, o_h in [
    ("Center_A_sp38_sq145_o15_90", 38.0, 145.0, 0.015, 0.090),
    ("Center_B_sp38_sq150_o15_90", 38.0, 150.0, 0.015, 0.090),
]:
    m_b = (
        common_ok & wk_mask & hist_fb["d2_o_pct"].between(o_l, o_h)
        & (hist_fb["s_prior_wk"] >= sp_c) & (hist_fb["s_quant_dual"] >= sq_c)
        & (hist_fb["score_wk"] >= thr_vec_304)
        & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy & pass_anti_climax
    )
    hist_fb["_tmp_sort"] = np.where(msk_champ, hist_fb["score_active"] + 1000.0, hist_fb["score_active"])
    msk_u = msk_champ | (m_b & (~msk_champ))
    r20 = evaluate_strategy_master(hist_fb, "_tmp_sort", msk_u, fn_champ, desc=label)
    r15 = evaluate_strategy_master(hist_fb, "_tmp_sort", msk_u, fn_champ_15, desc=label+"_15")
    print(f"\n=== {label} ===")
    print(f"0.20% fee: nav_1s={r20['nav_1s']:.2f}x, mdd_1s={r20['mdd_1s']:.1f}%, nav_2s={r20['nav_2s']:.2f}x (mdd {r20['mdd_2s']:.1f}%), eq={r20['daily_eq']:.2f}x, trades={r20['trades_5y']}")
    print(f"0.15% fee: nav_1s={r15['nav_1s']:.2f}x, nav_2s={r15['nav_2s']:.2f}x")
    print(f"3-period WR/Payoff: 2026={r20['wr_2026']:.1f}%({r20['payoff_2026']:.2f}), 3Y={r20['wr_3y']:.1f}%({r20['payoff_3y']:.2f}), 5Y={r20['wr_5y']:.1f}%({r20['payoff_5y']:.2f})")
    sealed_0 = sum(1 for t in r20["trades_list"] if t.get("sealed_2b", 0) == 0)
    print(f"Blown/unsealed count in denominator: {sealed_0}/{r20['trades_5y']} ({sealed_0/r20['trades_5y']*100:.1f}%)")
    print("Annual:", json.dumps(r20["annual"], ensure_ascii=False))
    new_dts = {t["buy_date"]: t for t in r20["trades_list"]}
    print("Added/Changed trades vs Base_Champ:")
    for d in sorted(set(base_dates.keys()) | set(new_dts.keys())):
        tb, tn = base_dates.get(d), new_dts.get(d)
        if tb != tn:
            sb = f"{tb['c6']} {tb['name']} {tb['net_ret']:+.2%}" if tb else "EMPTY"
            sn = f"{tn['c6']} {tn['name']} {tn['net_ret']:+.2%}" if tn else "EMPTY"
            print(f"  {d}: Base=[{sb}] -> New=[{sn}]")
    # Run forensic audit 8/8
    df_l = pd.DataFrame(r20["trades_list"])
    d1_map = dict(zip(hist_fb["d2_dt"] + "_" + hist_fb["c6"], hist_fb["dt_str"]))
    nh_map = dict(zip(hist_fb["d2_dt"] + "_" + hist_fb["c6"], hist_fb["notice_hard"]))
    df_l["key"] = df_l["buy_date"] + "_" + df_l["c6"]
    df_l["d1_dt"] = df_l["key"].map(d1_map)
    df_l["notice_hard"] = df_l["key"].map(nh_map).fillna(0).astype(int)
    csv_p = f"/tmp/ledger_{label}.csv"
    df_l.to_csv(csv_p, index=False)
    ok = run_audit(csv_p)
    print(f"Forensic Audit 8/8: {ok}")
