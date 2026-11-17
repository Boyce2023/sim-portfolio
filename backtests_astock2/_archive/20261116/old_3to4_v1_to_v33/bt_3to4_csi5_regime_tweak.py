#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""三进四 V3.3 大盘环境微调实测：在 V3.3 分数上叠加沪深300近5日分层加减分"""
import numpy as np
from verify_v33_calendar_upgrade import df, run_cfg

base = np.where(df["is_post_holiday_or_mon"], 2.0, 0.0) + np.where(df["mon"].isin([1, 5]), -4.0, 0.0)
c5 = df["csi_5d_prev"]
run_cfg("V0. 现役V3.3", base, (90, 98))
run_cfg("V1. +近5日沪深300涨超2.5%加3", base + np.where(c5 > 0.025, 3.0, 0.0), (90, 98))
run_cfg("V2. +近5日沪深300涨超2.5%加5", base + np.where(c5 > 0.025, 5.0, 0.0), (90, 98))
run_cfg("V3. +近5日横盘跌0.5至涨2.5%加2", base + np.where(c5.between(-0.005, 0.025), 2.0, 0.0), (90, 98))
run_cfg("V4. +近5日微跌0.5至3%扣3", base + np.where(c5.between(-0.03, -0.005), -3.0, 0.0), (90, 98))
