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
pass_anti_climax = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
wk_mask = hist_fb["gap_days"] >= 3
f3_bonus = np.where(hist_fb["notice_hard"], 8.0, 0.0) + np.where(hist_fb["notice_bad"], -35.0, 0.0)
thr_vec_304 = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)

hist_fb["score_wk"] = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

m_t2_base = (
    common_ok
    & (hist_fb["p_sz"] == 1)
    & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"])
    & hist_fb["d2_o_pct"].between(0.035, 0.078)
    & (hist_fb["buyable_mkt_open_rk"] <= 3)
    & (hist_fb["d1_seal_tightness"] >= 15.0)
    & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
)

fn_champ = create_master_trade_engine(
    price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005,
    lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE
)
fn_champ_15 = create_master_trade_engine(
    price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005,
    lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE_DISCOUNT
)

print("=== PLATEAU CHECK: PENALIZING WEAK-OPEN OVERSOLD & NON-RK1 WEAK OPEN ===")
for pen_w in [0.0, 10.0, 12.0, 15.0, 18.0, 20.0]:
    for w_cut in [0.029, 0.031, 0.033]:
        for pen_rk2 in [0.0, 12.0, 18.0]:
            q_adj = (
                - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < w_cut), pen_w, 0.0)
                - np.where((hist_fb["buyable_plate_rk"] >= 2) & (hist_fb["d2_o_pct"] < 0.040), pen_rk2, 0.0)
            )
            sq_v = hist_fb["s_quant_dual"] + q_adj
            sc_v = hist_fb["score_wk"] + q_adj
            hist_fb["score_active"] = sc_v
            m_t1 = (
                common_ok
                & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078)))
                & (hist_fb["s_prior_wk"] >= 45.0) & (sq_v >= 150.0) & (sc_v >= thr_vec_304)
            )
            msk_m = (m_t1 & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy & pass_anti_climax) | (m_t2_base & pass_layer2)
            m_mon = (
                common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090)
                & (hist_fb["s_prior_wk"] >= 38.0) & (sq_v >= 145.0) & (sc_v >= thr_vec_304)
                & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy & pass_anti_climax
            )
            hist_fb["_s"] = np.where(msk_m, sc_v + 1000.0, sc_v)
            r = evaluate_strategy_master(hist_fb, "_s", msk_m | (m_mon & (~msk_m)), fn_champ, desc="g")
            if pen_w in [0.0, 12.0, 15.0, 18.0] and (pen_w > 0 or (w_cut == 0.031 and pen_rk2 == 0.0)):
                print(f"pen_w={pen_w:4.1f} cut={w_cut:.3f} pen_rk2={pen_rk2:4.1f} -> N={r['trades_5y']:3d} WR={r['wr_5y']:4.1f}% PF={r['payoff_5y']:4.2f} 1S={r['nav_1s']:6.2f}x MDD={r['mdd_1s']:4.1f}% 2S={r['nav_2s']:5.2f}x EQ={r['daily_eq']:5.2f}x")

# Detailed D15 printout for the cleanest structural tweak: pen_w=15.0, cut=0.031, pen_rk2=12.0 vs pen_w=15.0, cut=0.031, pen_rk2=0.0 vs NormFloor=3.0%
for lbl, pw, wc, prk2, onorm in [
    ("Clean_PenWeak15_Cut3.1%", 15.0, 0.031, 0.0, 0.022),
    ("Clean_PenWeak15_Cut3.1%_Rk2Pen12", 15.0, 0.031, 12.0, 0.022),
    ("Clean_NormFloor3.0%", 0.0, 0.031, 0.0, 0.030),
]:
    q_adj = (
        - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < wc), pw, 0.0)
        - np.where((hist_fb["buyable_plate_rk"] >= 2) & (hist_fb["d2_o_pct"] < 0.040), prk2, 0.0)
    )
    sq_v = hist_fb["s_quant_dual"] + q_adj
    sc_v = hist_fb["score_wk"] + q_adj
    hist_fb["score_active"] = sc_v
    m_t1 = (
        common_ok
        & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(onorm, 0.078)))
        & (hist_fb["s_prior_wk"] >= 45.0) & (sq_v >= 150.0) & (sc_v >= thr_vec_304)
    )
    msk_m = (m_t1 & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy & pass_anti_climax) | (m_t2_base & pass_layer2)
    m_mon = (
        common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090)
        & (hist_fb["s_prior_wk"] >= 38.0) & (sq_v >= 145.0) & (sc_v >= thr_vec_304)
        & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy & pass_anti_climax
    )
    hist_fb["_s"] = np.where(msk_m, sc_v + 1000.0, sc_v)
    mu = msk_m | (m_mon & (~msk_m))
    r20 = evaluate_strategy_master(hist_fb, "_s", mu, fn_champ, desc=lbl)
    r15 = evaluate_strategy_master(hist_fb, "_s", mu, fn_champ_15, desc=lbl+"_15")
    s0 = sum(1 for t in r20["trades_list"] if t.get("sealed_2b", 0) == 0)
    print(f"\n>>> {lbl}: 1S={r20['nav_1s']:.2f}x ({r15['nav_1s']:.2f}x @0.15%), MDD={r20['mdd_1s']:.1f}%, 2S={r20['nav_2s']:.2f}x (MDD {r20['mdd_2s']:.1f}%), EQ={r20['daily_eq']:.2f}x, N={r20['trades_5y']}")
    print(f"    WR/PF: 2026={r20['wr_2026']:.1f}%({r20['payoff_2026']:.2f}), 3Y={r20['wr_3y']:.1f}%({r20['payoff_3y']:.2f}), 5Y={r20['wr_5y']:.1f}%({r20['payoff_5y']:.2f}) | Blown={s0}/{r20['trades_5y']} ({s0/r20['trades_5y']*100:.1f}%)")
    print(f"    Annual: {json.dumps(r20['annual'], ensure_ascii=False)}")
