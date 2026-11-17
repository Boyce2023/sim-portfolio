#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import numpy as np
from verify_v33_calendar_upgrade import df, skel_v32, run_cfg

# Check first-principles Friday split: Bull/flat Friday (csi_5d_prev >= 0) vs Bear Friday (csi_5d_prev < 0)
sub = df[skel_v32 & df["ret"].notna()]
f_bull = sub[sub["is_pre_holiday_or_fri"] & (sub["csi_5d_prev"] >= 0)]
f_bear = sub[sub["is_pre_holiday_or_fri"] & (sub["csi_5d_prev"] < 0)]
print(f"Friday csi_5d>=0 (n={len(f_bull)}): WR={(f_bull['ret']>0).mean()*100:.1f}% mean={f_bull['ret'].mean()*100:+.2f}%")
print(f"Friday csi_5d< 0 (n={len(f_bear)}): WR={(f_bear['ret']>0).mean()*100:.1f}% mean={f_bear['ret'].mean()*100:+.2f}%")

for pen in [-3.0, -4.0, -5.0]:
    run_cfg(f"F_mon2_friBull2_pen{int(pen)}: 周一/节后(+2) + 周五/节前且沪深300近5日红盘(+2) + 1月5月({int(pen)})",
            np.where(df["is_post_holiday_or_mon"], 2.0, np.where(df["is_pre_holiday_or_fri"] & (df["csi_5d_prev"] >= 0.0), 2.0, 0.0))
            + np.where(df["mon"].isin([1, 5]), pen, 0.0), (90, 98, 102))
