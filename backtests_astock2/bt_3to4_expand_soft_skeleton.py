#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""三进四扩笔数第二步：硬骨架改软打分 + 新稳定因子加减分，单仓轮动实测净值"""
import numpy as np, pandas as pd
from verify_v33_calendar_upgrade import df, p_v32
from core_3to4_5m_engine import _slice_metrics_chrono

d = df
fst = pd.to_numeric(d["first_seal_time"].astype(str).str.replace(":", "").str[:4], errors="coerce").fillna(9999)
core = (d.is_10cm_non_st & (~d.prev_is_yizi) & d.buyable_open & (~d.has_tox_notice) & (~d.has_stock_reg))
top1 = d.is_top1_3b_open.astype(bool)
obc = d.open_board_count >= 1
lock = (d.lock_top10 >= 45) | (d.real_free_mcap >= 45)
to_ok = d.prev_to.between(8.5, 31)
op_ok = d.open_pct.between(0.03, 0.092)
skel33 = core & top1 & obc & lock & to_ok & op_ok

pts = (78.0 + np.where(d.px_d3 <= 20, 8, np.where(d.px_d3 > 32, -5, 0)) + np.where(d.mkt_max_board_prev <= 4, 8, 0)
       + np.where(d.p_elo >= 115, 3, 0) + np.where(d.mkt_zt_prev >= 95, -10, np.where(d.mkt_zt_prev.between(35, 85), 5, 0))
       + np.where(d.has_ex_reg, -12, 0) + np.where(d.surf_yz_buy, -12, 0)
       + np.where(d.lhb_lh_cnt == 0, 4, np.where(d.lhb_lh_cnt >= 3, -5, 0))
       + np.where((d.plate_fb_ho_cnt >= 2) & (d.plate_fb_yz_cnt == 0), 4, 0) + np.where(d.plate_fb_yz_cnt >= 1, -7, 0)
       + np.where(d.plate_peers_open_avg < -0.015, -10, 0)
       + np.where(d.prev_3b_dt_cnt == 0, 3, np.where(d.prev_3b_dt_cnt >= 2, -4, 0))
       + np.where((d.csi_1d_prev <= -0.02) | (d.csi_5d_prev <= -0.03), -8, 0) + np.where(d.prev_to.between(9.5, 28), 3, 0)
       + np.where(d.is_post_holiday_or_mon, 2, 0) + np.where(d.buy_month.isin([1, 5]), -4, 0)).astype(float)
# V3.3 parity check retired (parquet score_v33 now stores V3.4)
newf = (np.where(d.is_event_basket.astype(bool), -6, 0) + np.where(d.prev_break_dt_rate_10d >= 0.20, -3, 0)
        + np.where(d.roll20_ho_zt < 0.45, 3, 0) + np.where(d.notice_ma.astype(bool), -4, 0)).astype(float)

def ev(tag, mask, sc, th):
    sel = np.where(mask & (sc >= th))[0]
    recs = [dict(p_v32[i], priority_score=float(sc[i]) * 10 + float(d.prio_3to4.iloc[i]) * 0.1) for i in sel if p_v32[i] is not None]
    t = pd.DataFrame(recs)
    s5 = _slice_metrics_chrono(t, "2022-01-04", "2026-11-10")
    r3 = _slice_metrics_chrono(t[t.buy_date >= "2024-01-02"], "2024-01-02", "2026-11-10")
    j7 = _slice_metrics_chrono(t[t.buy_date >= "2026-07-01"], "2026-07-01", "2026-11-10")
    yrs = [round(_slice_metrics_chrono(t[t.buy_date.str.startswith(y)], f"{y}-01-01", f"{y}-12-31" if y != "2026" else "2026-11-10")["single_nav"], 2) for y in ["2022", "2023", "2024", "2025", "2026"]]
    print(f"{tag:40s} th{th:3d} | {s5['single_n']:3d}笔 WR={s5['wr']:4.1f}% PO={s5['payoff']:4.2f} NAV={s5['single_nav']:7.2f}x MDD={s5['single_mdd_pct']:4.1f}% | 近三年{r3['single_nav']:6.2f}x | 7月起{j7['single_n']}笔{j7['single_nav']:4.2f}x | {yrs}")

for th in (90, 88, 86):
    ev("E0 现役V3.3", skel33, pts, th)
for th in (92, 90, 88, 86):
    ev("E1 V3.3+新四因子", skel33, pts + newf, th)
soft_top1 = pts + newf - 8 + np.where(top1, 8, 0)
for th in (92, 90, 88):
    ev("E2 头名改软(非头名扣8)", core & obc & lock & to_ok & op_ok, soft_top1, th)
soft_obc = pts + newf - 5 + np.where(obc, 5, 0)
for th in (92, 90, 88):
    ev("E3 开板改软(死封扣5)", core & top1 & lock & to_ok & op_ok, soft_obc, th)
soft_lock = pts + newf - 6 + np.where(lock, 6, 0)
for th in (92, 90, 88):
    ev("E4 锁仓改软(双低扣6)", core & top1 & obc & to_ok & op_ok, soft_lock, th)
soft_to = pts + newf - 5 + np.where(to_ok, 5, 0)
for th in (92, 90, 88):
    ev("E5 换手改软(越界扣5)", core & top1 & obc & lock & op_ok, soft_to, th)
