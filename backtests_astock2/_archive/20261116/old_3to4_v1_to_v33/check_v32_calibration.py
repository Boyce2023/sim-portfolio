#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import numpy as np, pandas as pd
from bt_3to4_v32_final_build import df, sim_pool, _slice_metrics_chrono
from bt_3to4_scorecard_verify import sim_dd_ctrl

p = sim_pool("touch65_1130", "cut_weak", "pm1345", True, False)
skel = (df["is_10cm_non_st"] & (~df["prev_is_yizi"]) & df["buyable_open"] & (~df["has_tox_notice"]) & (~df["has_stock_reg"])
        & (df["open_board_count"] >= 1) & ((df["lock_top10"] >= 45.0) | (df["real_free_mcap"] >= 45.0))
        & df["prev_to"].between(8.5, 31.0) & df["open_pct"].between(0.030, 0.092) & df["is_top1_3b_open"].astype(bool))
pts0 = (78.0 + np.where(df["px_d3"] <= 20.0, 8.0, np.where(df["px_d3"] > 32.0, -5.0, 0.0))
        + np.where(df["mkt_max_board_prev"] <= 4, 8.0, 0.0)
        + np.where(df["mkt_zt_prev"] >= 95, -10.0, np.where(df["mkt_zt_prev"].between(35, 85), 5.0, 0.0))
        + np.where(df["has_ex_reg"], -12.0, 0.0) + np.where(df["surf_yz_buy"], -12.0, 0.0)
        + np.where(df["lhb_lh_cnt"] == 0, 4.0, np.where(df["lhb_lh_cnt"] >= 3, -5.0, 0.0))
        + np.where((df["plate_fb_ho_cnt"] >= 2) & (df["plate_fb_yz_cnt"] == 0), 4.0, 0.0)
        + np.where(df["plate_fb_yz_cnt"] >= 1, -7.0, 0.0) + np.where(df["plate_peers_open_avg"] < -0.015, -10.0, 0.0)
        + np.where(df["prev_3b_dt_cnt"] == 0, 3.0, np.where(df["prev_3b_dt_cnt"] >= 2, -4.0, 0.0))
        + np.where((df["csi_1d_prev"] <= -0.020) | (df["csi_5d_prev"] <= -0.030), -8.0, 0.0) + np.where(df["prev_to"].between(9.5, 28.0), 3.0, 0.0))

for w_elo in [0.0, 3.0, 4.0, 5.0]:
    sc = np.where(skel, pts0 + np.where(df["p_elo"] >= 115.0, w_elo, 0.0), -999.0)
    print(f"=== w_elo = {w_elo} ===")
    for th in [90, 96, 98, 100, 102]:
        recs = [dict(p[i], priority_score=float(sc[i])*10+float(df["prio_3to4"].iloc[i])*0.1) for i in np.where(sc >= th)[0] if p[i] is not None]
        tdf = pd.DataFrame(recs)
        s5 = _slice_metrics_chrono(tdf, "2022-01-04", "2026-11-10")
        r3 = _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2024-01-02"], "2024-01-02", "2026-11-10")
        hnav, hmdd = sim_dd_ctrl(tdf, "half_cb")
        yrs = [round(_slice_metrics_chrono(tdf[tdf["buy_date"].str.startswith(y)], f"{y}-01-01", f"{y}-12-31" if y!="2026" else "2026-11-10")["single_nav"], 2) for y in ["2022","2023","2024","2025","2026"]]
        print(f"  th={th:3d} | 5Y:{s5['single_n']:2d}b WR={s5['wr']:4.1f}% PO={s5['payoff']:4.2f} NAV={s5['single_nav']:6.2f}x(MDD={s5['single_mdd_pct']:4.1f}%) HalfCB={hnav:5.2f}x(MDD={hmdd*100:4.1f}%) | 24-26:{r3['single_n']:2d}b WR={r3['wr']:4.1f}% PO={r3['payoff']:4.2f} NAV={r3['single_nav']:5.2f}x(MDD={r3['single_mdd_pct']:4.1f}%) | Yrs={yrs}")
