#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import numpy as np
from verify_v33_calendar_upgrade import df, run_cfg

cands = [
    ("0. 基准 V3.2", np.zeros(len(df))),
    ("M0. 仅 1月与5月弱势月(-6)", np.where(df["mon"].isin([1, 5]), -6.0, 0.0)),
    ("M1. 周一/节后首日(+2) + 1月与5月弱势月(-6)",
     np.where(df["is_post_holiday_or_mon"], 2.0, 0.0) + np.where(df["mon"].isin([1, 5]), -6.0, 0.0)),
    ("M2. 周一/节后首日(+2) + 周五/节前末日(+1) + 1月与5月弱势月(-6)",
     np.where(df["is_post_holiday_or_mon"], 2.0, np.where(df["is_pre_holiday_or_fri"], 1.0, 0.0)) + np.where(df["mon"].isin([1, 5]), -6.0, 0.0)),
    ("M3. 周一/节后首日(+2) + 周五且全场涨停>=40温热孵妖(+2) + 1月与5月弱势月(-6)",
     np.where(df["is_post_holiday_or_mon"], 2.0, np.where(df["is_pre_holiday_or_fri"] & (df["mkt_zt_prev"] >= 40), 2.0, 0.0))
     + np.where(df["mon"].isin([1, 5]), -6.0, 0.0)),
    ("M4. 周一/节后首日(+2) + 1月与5月弱势月(-5)",
     np.where(df["is_post_holiday_or_mon"], 2.0, 0.0) + np.where(df["mon"].isin([1, 5]), -5.0, 0.0)),
    ("M5. 周一/节后首日(+2) + 1月与5月弱势月(-7)",
     np.where(df["is_post_holiday_or_mon"], 2.0, 0.0) + np.where(df["mon"].isin([1, 5]), -7.0, 0.0)),
    ("M6. 周一/节后首日(+3) + 1月与5月弱势月(-6)",
     np.where(df["is_post_holiday_or_mon"], 3.0, 0.0) + np.where(df["mon"].isin([1, 5]), -6.0, 0.0)),
]
for nm, pts in cands:
    run_cfg(nm, pts, (90, 98, 102))
