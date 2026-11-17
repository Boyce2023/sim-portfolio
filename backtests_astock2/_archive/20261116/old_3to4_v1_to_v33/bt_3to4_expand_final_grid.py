#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""三进四扩笔数第五步：候选组合的扣分平原与早晚两段拆分"""
import numpy as np
import bt_3to4_expand_soft_skeleton as B
from bt_3to4_expand_plateau import plateau
from bt_3to4_expand_combo import split

core, top1, obc, lock, to_ok, op_ok, pts = B.core, B.top1, B.obc, B.lock, B.to_ok, B.op_ok, B.pts
s = lambda m, pen: -pen + np.where(m, pen, 0)
print("=== 锁仓软扣分平原（头名软12）===")
for lp in (8, 10, 12, 15):
    plateau(f"L 头名软12+锁仓软{lp}", core & obc & to_ok & op_ok, pts + s(top1, 12) + s(lock, lp))
print("=== 换手软扣分平原（头名软12）===")
for tp in (6, 8, 10, 12):
    plateau(f"W 头名软12+换手软{tp}", core & obc & lock & op_ok, pts + s(top1, 12) + s(to_ok, tp))
print("=== 三项全软 ===")
for lp, tp in ((10, 10), (12, 10), (10, 12)):
    plateau(f"A 头名软12+锁仓软{lp}+换手软{tp}", core & obc & op_ok, pts + s(top1, 12) + s(lock, lp) + s(to_ok, tp))
print("=== 早晚拆分 ===")
split("头名软12+换手软10", core & obc & lock & op_ok, pts + s(top1, 12) + s(to_ok, 10))
split("头名软12+锁仓软10", core & obc & to_ok & op_ok, pts + s(top1, 12) + s(lock, 10))
split("头名软12+锁仓软10+换手软10", core & obc & op_ok, pts + s(top1, 12) + s(lock, 10) + s(to_ok, 10))
