#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import numpy as np, pandas as pd
from verify_v33_calendar_upgrade import df, p_v32, skel_v32, pts_v32, run_cfg

# Test clean individual & combined non-inflating rules!
run_cfg("H1. 仅周一/节后首日加分 (+3分)", np.where(df["is_post_holiday_or_mon"], 3.0, 0.0), (90, 98, 102))
run_cfg("H2. 仅周五/节前末日加分 (+3分)", np.where(df["is_pre_holiday_or_fri"], 3.0, 0.0), (90, 98, 102))
run_cfg("H3. 仅5月退潮月扣分 (-6分)", np.where(df["mon"] == 5, -6.0, 0.0), (90, 98, 102))
run_cfg("H4. 仅1月预告雷月扣分 (-6分)", np.where(df["mon"] == 1, -6.0, 0.0), (90, 98, 102))
run_cfg("H5. 周一/节后(+3) + 5月(-6) + 1月(-6)",
        np.where(df["is_post_holiday_or_mon"], 3.0, 0.0) + np.where(df["mon"].isin([1, 5]), -6.0, 0.0), (90, 98, 102))
run_cfg("H6. 周一/节后(+3) + 周五(+2) + 5月(-6) + 1月15至31日年报预告雷(-8)",
        np.where(df["is_post_holiday_or_mon"], 3.0, np.where(df["is_pre_holiday_or_fri"], 2.0, 0.0))
        + np.where(df["mon"] == 5, -6.0, 0.0)
        + np.where(df["md"].between("01-15", "01-31") | df["md"].between("10-20", "10-30"), -8.0, 0.0),
        (90, 98, 102))
run_cfg("H7. 周一/节后(+3) + 周五(+2) + 财报末期(1月底/8月底/10月底, 不误杀4月主线! -8) + 5月(-6)",
        np.where(df["is_post_holiday_or_mon"], 3.0, np.where(df["is_pre_holiday_or_fri"], 2.0, 0.0))
        + np.where(df["mon"] == 5, -6.0, 0.0)
        + np.where(df["md"].between("01-15", "01-31") | df["md"].between("08-22", "08-31") | df["md"].between("10-20", "10-30"), -8.0, 0.0),
        (90, 98, 102))
