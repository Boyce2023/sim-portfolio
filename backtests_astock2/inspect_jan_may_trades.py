#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import numpy as np, pandas as pd
from verify_v33_calendar_upgrade import df, p_v32, skel_v32, pts_v32, sc_v32, run_cfg

print("--- Jan & May trades with sc_v32 >= 86 ---")
for i in np.where((sc_v32 >= 86) & df["mon"].isin([1, 5]))[0]:
    r = df.iloc[i]
    rec = p_v32[i]
    if rec:
        print(f"{r['buy_date']} dow={r['dow']} {str(r['code']).zfill(6)} {r['name']:6s} | sc_v32={int(sc_v32[i]):3d} | ret={rec['net_ret']*100:+6.2f}% | zt_prev={r['mkt_zt_prev']} maxb={r['mkt_max_board_prev']}")

print("\n--- Test refined institutional variants (-3 / -4 / 01-15..01-31 + May) ---")
for nm, pts in [
    ("R1. 周一/节后(+2) + 1月与5月弱势月(-4)",
     np.where(df["is_post_holiday_or_mon"], 2.0, 0.0) + np.where(df["mon"].isin([1, 5]), -4.0, 0.0)),
    ("R2. 周一/节后(+2) + 周五温热(+2) + 1月与5月弱势月(-4)",
     np.where(df["is_post_holiday_or_mon"], 2.0, np.where(df["is_pre_holiday_or_fri"] & (df["mkt_zt_prev"] >= 40), 2.0, 0.0))
     + np.where(df["mon"].isin([1, 5]), -4.0, 0.0)),
    ("R3. 周一/节后(+2) + 1月下半月年报预告雷(01-15~01-31,-6) + 5月退潮月(-5)",
     np.where(df["is_post_holiday_or_mon"], 2.0, 0.0)
     + np.where(df["md"].between("01-15", "01-31"), -6.0, np.where(df["mon"] == 5, -5.0, 0.0))),
    ("R4. 周一/节后(+2) + 周五温热(+2) + 1月下半月预告雷(-6) + 5月退潮月(-5)",
     np.where(df["is_post_holiday_or_mon"], 2.0, np.where(df["is_pre_holiday_or_fri"] & (df["mkt_zt_prev"] >= 40), 2.0, 0.0))
     + np.where(df["md"].between("01-15", "01-31"), -6.0, np.where(df["mon"] == 5, -5.0, 0.0))),
]:
    run_cfg(nm, pts, (90, 98, 102))
