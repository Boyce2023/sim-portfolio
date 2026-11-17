#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
实测把通过双期同向 + 5/5 LOYO 检验的星期与制度日历因子纳入三进四打分卡（V3.2 -> V3.3），
检验全五年、去2025四年、2025-2026样本外、近三年、7月以来及逐年收益、胜率、盈亏比与最大回撤，并做参数平原检验。
"""
import os, sys
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from bt_3to4_calendar_factors_oos import df, p_v32, skel_v32
from core_3to4_5m_engine import csi300_ret, _slice_metrics_chrono
from bt_3to4_scorecard_verify import sim_dd_ctrl

pts_v32 = (
    78.0
    + np.where(df["px_d3"] <= 20.0, 8.0, np.where(df["px_d3"] > 32.0, -5.0, 0.0))
    + np.where(df["mkt_max_board_prev"] <= 4, 8.0, 0.0)
    + np.where(df["p_elo"] >= 115.0, 3.0, 0.0)
    + np.where(df["mkt_zt_prev"] >= 95, -10.0, np.where(df["mkt_zt_prev"].between(35, 85), 5.0, 0.0))
    + np.where(df["has_ex_reg"], -12.0, 0.0)
    + np.where(df["surf_yz_buy"], -12.0, 0.0)
    + np.where(df["lhb_lh_cnt"] == 0, 4.0, np.where(df["lhb_lh_cnt"] >= 3, -5.0, 0.0))
    + np.where((df["plate_fb_ho_cnt"] >= 2) & (df["plate_fb_yz_cnt"] == 0), 4.0, 0.0)
    + np.where(df["plate_fb_yz_cnt"] >= 1, -7.0, 0.0)
    + np.where(df["plate_peers_open_avg"] < -0.015, -10.0, 0.0)
    + np.where(df["prev_3b_dt_cnt"] == 0, 3.0, np.where(df["prev_3b_dt_cnt"] >= 2, -4.0, 0.0))
    + np.where((df["csi_1d_prev"] <= -0.020) | (df["csi_5d_prev"] <= -0.030), -8.0, 0.0)
    + np.where(df["prev_to"].between(9.5, 28.0), 3.0, 0.0)
)
sc_v32 = np.where(skel_v32, pts_v32, -999.0)

def run_cfg(name, add_pts, th_list=(90, 98, 102)):
    sc = np.where(skel_v32, pts_v32 + add_pts, -999.0)
    print(f"\n=== {name} ===")
    for th in th_list:
        recs = [dict(p_v32[i], score=int(sc[i]), priority_score=float(sc[i])*10+float(df["prio_3to4"].iloc[i])*0.1)
                for i in np.where(sc >= th)[0] if p_v32[i] is not None]
        tdf = pd.DataFrame(recs)
        s5 = _slice_metrics_chrono(tdf, "2022-01-04", "2026-11-10")
        ex4 = _slice_metrics_chrono(tdf[~tdf["buy_date"].str.startswith("2025")], "2022-01-04", "2026-11-10")
        r3 = _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2024-01-02"], "2024-01-02", "2026-11-10")
        j26 = _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2026-07-01"], "2026-07-01", "2026-11-10")
        hnav, hmdd = sim_dd_ctrl(tdf, "half_cb")
        yrs = [round(_slice_metrics_chrono(tdf[tdf["buy_date"].str.startswith(y)], f"{y}-01-01", f"{y}-12-31" if y!="2026" else "2026-11-10")["single_nav"], 2)
               for y in ["2022", "2023", "2024", "2025", "2026"]]
        print(f"  >={th:3d} | 5Y:{s5['single_n']:2d}b WR={s5['wr']:4.1f}% PO={s5['payoff']:4.2f} NAV={s5['single_nav']:6.2f}x Eq={s5['eq_nav']:6.2f}x MDD={s5['single_mdd_pct']:4.1f}% HalfCB={hnav:6.2f}x({hmdd*100:4.1f}%) | Ex25:{ex4['single_nav']:5.2f}x | 24-26:{r3['single_n']:2d}b WR={r3['wr']:4.1f}% PO={r3['payoff']:4.2f} NAV={r3['single_nav']:5.2f}x MDD={r3['single_mdd_pct']:4.1f}% | Jul26:{j26['single_nav']:4.2f}x | Yrs={yrs}")

run_cfg("0. 基准 V3.2 (无星期与日历因子)", 0.0)

# Test clean institutional combinations:
c_mon_fri = np.where(df["is_post_holiday_or_mon"], 4.0, np.where(df["is_pre_holiday_or_fri"], 3.0, 0.0))
c_earn = np.where(df["is_earn_landmine"], -8.0, 0.0)
c_jan_may = np.where(df["mon"] == 5, -6.0, np.where(df["mon"] == 1, -4.0, 0.0))

run_cfg("A. 仅加跨周末双端 (周一/节后+4, 周五/节前+3)", c_mon_fri)
run_cfg("B. 仅加财报暴雷末期窗排雷 (财报末期-8)", c_earn)
run_cfg("C. 跨周末双端(+4/+3) + 财报暴雷末期排雷(-8)", c_mon_fri + c_earn)
run_cfg("D. 跨周末双端(+4/+3) + 财报暴雷末期(-8) + 5月退潮(-6)/1月(-4)", c_mon_fri + c_earn + c_jan_may)
run_cfg("E. 参数平原微调1: 周一/节后+3, 周五/节前+3, 财报末期-8, 5月-6",
        np.where(df["is_post_holiday_or_mon"] | df["is_pre_holiday_or_fri"], 3.0, 0.0) + c_earn + np.where(df["mon"] == 5, -6.0, 0.0))
run_cfg("F. 参数平原微调2: 周一/节后+4, 周五/节前+4, 财报末期-10, 5月-8",
        np.where(df["is_post_holiday_or_mon"] | df["is_pre_holiday_or_fri"], 4.0, 0.0) + np.where(df["is_earn_landmine"], -10.0, 0.0) + np.where(df["mon"] == 5, -8.0, 0.0))
