#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""三进四拆细后入选的子条件，放进三项改扣分模型实测（门槛平原 + 权重平原 + 早晚拆分）"""
import numpy as np, pandas as pd
import bt_3to4_expand_soft_skeleton as B
from bt_3to4_expand_plateau import plateau
from bt_3to4_expand_combo import split

d = B.d
core, top1, obc, lock, to_ok, op_ok, pts = B.core, B.top1, B.obc, B.lock, B.to_ok, B.op_ok, B.pts
s = lambda m, pen: -pen + np.where(m, pen, 0)
mask_A = core & obc & op_ok
sc_A = pts + s(top1, 12) + s(lock, 10) + s(to_ok, 10)
fst = pd.to_numeric(d.first_seal_time.astype(str).str.replace(":", "").str[:4], errors="coerce").fillna(9999)

f_seal = np.where(fst <= 935, -3, np.where(fst.between(936, 1030), 3, 0))
f_promo = np.where(d.mkt_promo_1to2_5d < 0.13, -6, np.where(d.mkt_promo_1to2_5d >= 0.25, -3, 0))
f_dom = np.where(d.is_dominant_day.astype(bool) & (d.rk_theme == 1), -5, 0)
f_cold = np.where(d.roll20_ho_zt < 0.40, 3, 0)

plateau("A0 三项改扣分（上轮方案）", mask_A, sc_A)
plateau("A1 +首封时间（秒封扣3，10点半前换手封加3）", mask_A, sc_A + f_seal)
plateau("A2 +一进二晋级率两头扣分", mask_A, sc_A + f_promo)
plateau("A3 +断层主线日主线票扣5", mask_A, sc_A + f_dom)
plateau("A4 +近20日高开封板率低加3", mask_A, sc_A + f_cold)
for k in (0.5, 1.0, 1.5):
    plateau(f"A5 四项全加（权重x{k}）", mask_A, sc_A + k * (f_seal + f_promo + f_dom + f_cold))
plateau("A6 首封+晋级率", mask_A, sc_A + f_seal + f_promo)
plateau("A7 首封+晋级率+断层主线", mask_A, sc_A + f_seal + f_promo + f_dom)
print("=== 早晚拆分 ===")
split("A0", mask_A, sc_A)
split("A5 x1", mask_A, sc_A + f_seal + f_promo + f_dom + f_cold)
split("A6", mask_A, sc_A + f_seal + f_promo)
split("A7", mask_A, sc_A + f_seal + f_promo + f_dom)
