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
hist_fb = hist_fb.reset_index(drop=True)

dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
clean_brk60 = hist_fb["clean_brk60"].values == 1
is_granularity = (
    hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
)
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

q_pen15 = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < 0.031), 15.0, 0.0)
d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)

hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
hist_fb["sq_91"] = hist_fb["s_quant_dual"] + q_pen15 + d_ov
hist_fb["sc_91"] = hist_fb["s_prior_wk"] + hist_fb["sq_91"]
hist_fb["score_active"] = hist_fb["sc_91"]

m_t2 = (
    common_ok & (hist_fb["p_sz"] == 1)
    & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"])
    & hist_fb["d2_o_pct"].between(0.035, 0.078)
    & (hist_fb["buyable_mkt_open_rk"] <= 3)
    & (hist_fb["d1_seal_tightness"] >= 15.0)
    & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
)
mt1_91 = (
    common_ok
    & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078)))
    & (hist_fb["s_prior_wk"] >= 45.0) & (hist_fb["sq_91"] >= 150.0) & (hist_fb["sc_91"] >= thr_vec)
)
mm_91 = (mt1_91 & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac) | (m_t2 & pass_l2)
mmon_91 = (
    common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090)
    & (hist_fb["s_prior_wk"] >= 38.0) & (hist_fb["sq_91"] >= 145.0) & (hist_fb["sc_91"] >= thr_vec)
    & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac
)
hist_fb["msk_91"] = mm_91 | (mmon_91 & (~mm_91))
hist_fb["m_t2_clean"] = m_t2 & pass_l2
hist_fb["pass_filters"] = pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac
hist_fb["common_ok"] = common_ok

fn20 = create_master_trade_engine(
    price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005,
    lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE
)
fn15 = create_master_trade_engine(
    price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005,
    lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE_DISCOUNT
)

# Compute pure concept score of each plate (strip individual stock notice_hard / is_ma)
# Notice: s_prior_dual has +18 if nh_c, +18 if is_ma_f, +8 if own_new. Median across plate stocks measures plate's true concept score!
valid_plate_df = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
pg = valid_plate_df.groupby(["d2_dt", "plate"], as_index=False).agg(
    p_fb_cnt=("c6", "count"),
    p_sz_max=("p_sz", "max"),
    p_prior_med=("s_prior_dual", "median"),
    p_open_avg=("d2_o_pct", "mean"),
    p_yizi_cnt=("d2_is_yizi", "sum"),
    p_hi_cnt=("_is_high_open", "sum"),
    p_top_sc=("sc_91", "max"),
    p_2nd_sc=("sc_91", lambda s: s.nlargest(2).iloc[-1] if len(s) >= 2 else -999.0),
)
pg["p_auc_power"] = pg["p_open_avg"] * 600.0 + pg["p_yizi_cnt"] * 18.0 + np.minimum(pg["p_hi_cnt"], 6) * 6.0
pg["p_total_power"] = pg["p_prior_med"] + pg["p_auc_power"]

pg_multi = pg[pg["p_sz_max"] >= 2].copy()
pg_multi["rk_auc"] = pg_multi.groupby("d2_dt")["p_auc_power"].rank(ascending=False, method="min")
pg_multi["rk_prior"] = pg_multi.groupby("d2_dt")["p_prior_med"].rank(ascending=False, method="min")
pg_multi["rk_comb"] = pg_multi.groupby("d2_dt")["p_total_power"].rank(ascending=False, method="min")

p2_prior = pg_multi.groupby("d2_dt")["p_prior_med"].transform(lambda s: s.nlargest(2).iloc[-1] if len(s) >= 2 else 0.0)
p2_comb = pg_multi.groupby("d2_dt")["p_total_power"].transform(lambda s: s.nlargest(2).iloc[-1] if len(s) >= 2 else 0.0)
p2_auc = pg_multi.groupby("d2_dt")["p_auc_power"].transform(lambda s: s.nlargest(2).iloc[-1] if len(s) >= 2 else 0.0)

pg_multi["lead_prior"] = pg_multi["p_prior_med"] - p2_prior
pg_multi["lead_comb"] = pg_multi["p_total_power"] - p2_comb
pg_multi["lead_auc"] = pg_multi["p_auc_power"] - p2_auc
pg_multi["stock_gap_1_2"] = np.where(pg_multi["p_2nd_sc"] > -500, pg_multi["p_top_sc"] - pg_multi["p_2nd_sc"], 99.0)

hist_m = hist_fb.merge(
    pg_multi[["d2_dt", "plate", "p_prior_med", "p_auc_power", "p_total_power", "rk_auc", "rk_prior", "rk_comb", "lead_prior", "lead_comb", "lead_auc", "stock_gap_1_2"]],
    on=["d2_dt", "plate"], how="left"
)

oos = hist_m[(hist_m["d2_dt"] >= "2022-01-01") & (hist_m["d2_dt"] <= "2026-11-09") & hist_m["common_ok"] & hist_m["d2_o_pct"].between(0.015, 0.090)].copy()
recs = oos.to_dict("records")
rets = [tr["net_ret"] if (tr := fn20(r)) is not None else np.nan for r in recs]
oos["_ret"] = rets
oos = oos[oos["_ret"].notna()].copy()
print("Total triggered OOS buyable candidates:", len(oos))

def show_stat(title, mask_s, pick_top1_per_day=True):
    sub = oos[mask_s].copy()
    if pick_top1_per_day and len(sub) > 0:
        sub.sort_values(["d2_dt", "sc_91"], ascending=[True, False], inplace=True)
        sub = sub.groupby("d2_dt", as_index=False).first()
    s = sub["_ret"]
    if len(s) == 0:
        print(f"  {title:58s}: N=   0")
        return
    wr = (s > 0).mean() * 100
    pf = (s[s > 0].mean() / abs(s[s <= 0].mean())) if ((s > 0).any() and (s <= 0).any()) else 0.0
    print(f"  {title:58s}: N={len(s):4d} | WR={wr:4.1f}% | PF={pf:4.2f} | Avg={s.mean()*100:+5.2f}%")

print("\n=== QUESTION 1: PLATE AUCTION #1 + CONCEPT SCORE FAR AHEAD OF #2 -> PICK BEST STOCK IN PLATE ===")
b_in_p = (oos["buyable_plate_rk"] == 1) & oos["d2_o_pct"].between(0.025, 0.085) & oos["pass_filters"]
show_stat("Q1_0: 90.98x Baseline Passed Pool (daily top-1)", oos["msk_91"])
show_stat("Q1_1: Plate Auc #1 (rk_auc==1), any concept score", b_in_p & (oos["rk_auc"] == 1))
show_stat("Q1_2: Plate Auc #1 & Concept #1 (rk_prior==1)", b_in_p & (oos["rk_auc"] == 1) & (oos["rk_prior"] == 1))
show_stat("Q1_3: Plate Auc #1 & Concept lead_prior >= 12", b_in_p & (oos["rk_auc"] == 1) & (oos["lead_prior"] >= 12))
show_stat("Q1_4: Plate Auc #1 & Concept lead_prior >= 20", b_in_p & (oos["rk_auc"] == 1) & (oos["lead_prior"] >= 20))
show_stat("Q1_5: Plate Auc #1 & Concept lead_prior >= 20 & sc>=290", b_in_p & (oos["rk_auc"] == 1) & (oos["lead_prior"] >= 20) & (oos["sc_91"] >= 290))
show_stat("Q1_6: Plate Combined #1 & lead_comb >= 25 & sc>=290", b_in_p & (oos["rk_comb"] == 1) & (oos["lead_comb"] >= 25) & (oos["sc_91"] >= 290))
show_stat("Q1_7: Plate Combined #1 & lead_comb >= 35 & sc>=290", b_in_p & (oos["rk_comb"] == 1) & (oos["lead_comb"] >= 35) & (oos["sc_91"] >= 290))
show_stat("Q1_8: Inside 90.98x pool: rk_auc==1 & lead_prior>=15", oos["msk_91"] & (oos["rk_auc"] == 1) & (oos["lead_prior"] >= 15))
show_stat("Q1_9: Inside 90.98x pool: rk_comb==1 & lead_comb>=20", oos["msk_91"] & (oos["rk_comb"] == 1) & (oos["lead_comb"] >= 20))

print("\n=== QUESTION 2: MEDIOCRE PLATE WITH ONLY ONE HIGH-SCORE STOCK (LONE STAR) ===")
show_stat("Q2_1: Mediocre plate (s_prior_wk<45) + high quant>=180", oos["d2_o_pct"].between(0.025, 0.085) & (oos["s_prior_wk"] < 45) & (oos["sq_91"] >= 180))
show_stat("Q2_2: Mediocre plate (s_prior_wk<45) + super quant>=195", oos["d2_o_pct"].between(0.025, 0.085) & (oos["s_prior_wk"] < 45) & (oos["sq_91"] >= 195))
show_stat("Q2_3: Multi-stock mediocre plate (p_prior_med<35) + 1 star sc>=290", (oos["p_sz"] >= 2) & (oos["p_prior_med"] < 35) & (oos["buyable_plate_rk"] == 1) & (oos["stock_gap_1_2"] >= 35) & (oos["sc_91"] >= 290))
show_stat("Q2_4: Multi-stock mediocre plate (rk_prior>=4) + 1 star sc>=300", (oos["p_sz"] >= 2) & (oos["rk_prior"] >= 4) & (oos["buyable_plate_rk"] == 1) & (oos["stock_gap_1_2"] >= 35) & (oos["sc_91"] >= 300))
show_stat("Q2_5: Solo plate (p_sz==1) NO hard notice/MA/pioneer + quant>=180", (oos["p_sz"] == 1) & (~(oos["notice_hard"] | oos["is_ma"] | oos["is_pioneer_word"])) & (oos["sq_91"] >= 180) & oos["d2_o_pct"].between(0.030, 0.080))
show_stat("Q2_6: Solo plate (p_sz==1) WITH hard M&A/notice/pioneer (Track 2)", oos["m_t2_clean"])
show_stat("Q2_7: Inside 90.98x pool: mediocre plate (rk_prior>=4, p_sz>=2)", oos["msk_91"] & (oos["p_sz"] >= 2) & (oos["rk_prior"] >= 4))
show_stat("Q2_8: Inside 90.98x pool: top-2 concept plate (rk_prior<=2, p_sz>=2)", oos["msk_91"] & (oos["p_sz"] >= 2) & (oos["rk_prior"] <= 2))
