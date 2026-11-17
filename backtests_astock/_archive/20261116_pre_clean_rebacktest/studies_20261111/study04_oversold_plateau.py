import sys, json, numpy as np
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock")
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean")
from master_5y_zero_lookahead_walkforward import load_all_data, create_master_trade_engine, evaluate_strategy_master, FEE_RATE, FEE_RATE_DISCOUNT

hist_fb, price_lookup, all_dts, dt_to_idx = load_all_data()
dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
dd60 = hist_fb["f_dd60_d0"].fillna(0.85).values
pos20 = hist_fb["f_pos20_d0"].fillna(0.50).values
d0_pct = hist_fb["f_d0_pct"].fillna(0.0).values
clean_brk60 = hist_fb["clean_brk60"].values == 1

sc_dd20 = np.where(dd20 <= 0.82, 42.0, np.where(dd20 <= 0.86, 32.0, np.where(dd20 <= 0.90, 18.0, np.where(dd20 > 0.95, -40.0, 0.0))))
sc_dd60 = np.where(dd60 <= 0.76, 18.0, np.where(dd60 <= 0.82, 10.0, np.where(dd60 > 0.92, -15.0, 0.0)))
sc_pos20 = np.where(pos20 <= 0.30, 25.0, np.where(pos20 <= 0.45, 12.0, np.where(pos20 > 0.75, -35.0, 0.0)))
sc_d0 = np.where(d0_pct <= -0.010, 25.0, np.where(d0_pct <= 0.005, 15.0, np.where(d0_pct > 0.030, -35.0, 0.0)))
ov4_orig = np.where(clean_brk60, 0.0, sc_dd20 + sc_dd60 + sc_pos20) + sc_d0

is_granularity = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))
common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
pass_l1 = (~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))
pass_l2 = (~hist_fb["is_dying_pulse"])
pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
pass_nd = (~((hist_fb["p_sz"] >= 2) & (hist_fb["buyable_plate_rk"] >= 3))) & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))))
pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
wk_mask = hist_fb["gap_days"] >= 3
f3_bonus = np.where(hist_fb["notice_hard"], 8.0, 0.0) + np.where(hist_fb["notice_bad"], -35.0, 0.0)
thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)
hist_fb["score_wk"] = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
m_t2 = common_ok & (hist_fb["p_sz"] == 1) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]) & hist_fb["d2_o_pct"].between(0.035, 0.078) & (hist_fb["buyable_mkt_open_rk"] <= 3) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))

fn20 = create_master_trade_engine(price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005, lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE)
fn15 = create_master_trade_engine(price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005, lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE_DISCOUNT)
q_pen15 = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < 0.031), 15.0, 0.0)

print("--- Grid 1: Cut dd20<=0.82 from 42 down by delta ---")
for cut_dd in [0.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0]:
    d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -cut_dd, 0.0)
    sq_v = hist_fb["s_quant_dual"] + q_pen15 + d_ov
    sc_v = hist_fb["score_wk"] + q_pen15 + d_ov
    hist_fb["score_active"] = sc_v
    mt1 = common_ok & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))) & (hist_fb["s_prior_wk"] >= 45.0) & (sq_v >= 150.0) & (sc_v >= thr_vec)
    mm = (mt1 & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac) | (m_t2 & pass_l2)
    mmon = common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090) & (hist_fb["s_prior_wk"] >= 38.0) & (sq_v >= 145.0) & (sc_v >= thr_vec) & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac
    hist_fb["_sv"] = np.where(mm, sc_v + 1000.0, sc_v)
    r = evaluate_strategy_master(hist_fb, "_sv", mm | (mmon & (~mm)), fn20, desc="g")
    print(f"cut_dd={cut_dd:4.1f} (dd20_top={42-cut_dd:4.1f}) -> N={r['trades_5y']:3d} WR={r['wr_5y']:4.1f}% PF={r['payoff_5y']:4.2f} 1S={r['nav_1s']:6.2f}x MDD={r['mdd_1s']:4.1f}% 2S={r['nav_2s']:5.2f}x EQ={r['daily_eq']:5.2f}x")

print("--- Grid 2: Cap ov4_orig (max 110) ---")
for cap in [110.0, 102.0, 98.0, 95.0, 92.0, 90.0]:
    d_ov = np.minimum(0.0, cap - ov4_orig)
    sq_v = hist_fb["s_quant_dual"] + q_pen15 + d_ov
    sc_v = hist_fb["score_wk"] + q_pen15 + d_ov
    hist_fb["score_active"] = sc_v
    mt1 = common_ok & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))) & (hist_fb["s_prior_wk"] >= 45.0) & (sq_v >= 150.0) & (sc_v >= thr_vec)
    mm = (mt1 & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac) | (m_t2 & pass_l2)
    mmon = common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090) & (hist_fb["s_prior_wk"] >= 38.0) & (sq_v >= 145.0) & (sc_v >= thr_vec) & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac
    hist_fb["_sv"] = np.where(mm, sc_v + 1000.0, sc_v)
    r = evaluate_strategy_master(hist_fb, "_sv", mm | (mmon & (~mm)), fn20, desc="g")
    print(f"cap={cap:5.1f} -> N={r['trades_5y']:3d} WR={r['wr_5y']:4.1f}% PF={r['payoff_5y']:4.2f} 1S={r['nav_1s']:6.2f}x MDD={r['mdd_1s']:4.1f}% 2S={r['nav_2s']:5.2f}x EQ={r['daily_eq']:5.2f}x")

d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
sq_v = hist_fb["s_quant_dual"] + q_pen15 + d_ov
sc_v = hist_fb["score_wk"] + q_pen15 + d_ov
hist_fb["score_active"] = sc_v
mt1 = common_ok & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))) & (hist_fb["s_prior_wk"] >= 45.0) & (sq_v >= 150.0) & (sc_v >= thr_vec)
mm = (mt1 & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac) | (m_t2 & pass_l2)
mmon = common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090) & (hist_fb["s_prior_wk"] >= 38.0) & (sq_v >= 145.0) & (sc_v >= thr_vec) & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac
hist_fb["_sv"] = np.where(mm, sc_v + 1000.0, sc_v)
r20 = evaluate_strategy_master(hist_fb, "_sv", mm | (mmon & (~mm)), fn20, desc="dd32")
r15 = evaluate_strategy_master(hist_fb, "_sv", mm | (mmon & (~mm)), fn15, desc="dd32_15")
s0 = sum(1 for t in r20["trades_list"] if t.get("sealed_2b", 0) == 0)
print("DETAIL dd32:", round(r20["nav_1s"],2), round(r15["nav_1s"],2), round(r20["mdd_1s"],1), round(r20["nav_2s"],2), round(r20["mdd_2s"],1), round(r20["daily_eq"],2), r20["trades_5y"], s0)
print("WR/PF:", r20["wr_2026"], r20["payoff_2026"], r20["wr_3y"], r20["payoff_3y"], r20["wr_5y"], r20["payoff_5y"])
print("ANNUAL:", json.dumps(r20["annual"], ensure_ascii=False))
