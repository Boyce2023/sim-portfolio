#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""三进四扩笔数第四步：头名改软的扣分平原 + 组合，并拆早期与近期两段"""
import numpy as np, pandas as pd
import bt_3to4_expand_soft_skeleton as B
from bt_3to4_expand_plateau import plateau, stats
from core_3to4_5m_engine import _slice_metrics_chrono

d, p = B.d, B.p_v32
core, top1, obc, lock, to_ok, op_ok, pts = B.core, B.top1, B.obc, B.lock, B.to_ok, B.op_ok, B.pts
def split(tag, mask, sc, th=90):
    sel = np.where(mask & (sc >= th))[0]
    t = pd.DataFrame([dict(p[i], priority_score=float(sc[i]) * 10 + float(d.prio_3to4.iloc[i]) * 0.1) for i in sel if p[i] is not None])
    e = _slice_metrics_chrono(t[t.buy_date < "2024-01-01"], "2022-01-04", "2023-12-29")
    l = _slice_metrics_chrono(t[t.buy_date >= "2024-01-01"], "2024-01-02", "2026-11-10")
    print(f"   {tag:30s} 22至23: {e['single_n']}笔 {e['single_nav']:5.2f}x MDD{e['single_mdd_pct']:4.1f}% | 24至26: {l['single_n']}笔 {l['single_nav']:6.2f}x MDD{l['single_mdd_pct']:4.1f}%")

print("=== 头名改软扣分平原 ===")
for pen in (8, 10, 12, 15, 20):
    plateau(f"T 非头名扣{pen}", core & obc & lock & to_ok & op_ok, pts - pen + np.where(top1, pen, 0))
print("=== 组合 ===")
s_top = lambda pen: -pen + np.where(top1, pen, 0)
s_lock = lambda pen: -pen + np.where(lock, pen, 0)
s_to = lambda pen: -pen + np.where(to_ok, pen, 0)
plateau("C1 头名软10+锁仓软8", core & obc & to_ok & op_ok, pts + s_top(10) + s_lock(8))
plateau("C2 头名软10+换手软8", core & obc & lock & op_ok, pts + s_top(10) + s_to(8))
plateau("C3 头名软10+锁仓软8+换手软8", core & obc & op_ok, pts + s_top(10) + s_lock(8) + s_to(8))
plateau("C4 头名软12+锁仓软10", core & obc & to_ok & op_ok, pts + s_top(12) + s_lock(10))
print("=== 早期与近期拆分（90分档）===")
split("V3.3现役", B.skel33, pts)
split("非头名扣10", core & obc & lock & to_ok & op_ok, pts + s_top(10))
split("C1 头名软10+锁仓软8", core & obc & to_ok & op_ok, pts + s_top(10) + s_lock(8))
sel = np.where((core & obc & lock & to_ok & op_ok) & (pts + s_top(10) >= 90) & (~B.skel33))[0]
for i in sel:
    r = d.iloc[i]; x = p[i]
    print("   非头名放行:", r.buy_date, str(r.code).zfill(6), r["name"], int(pts[i] - 10), f"{x['net_ret']*100:+.1f}%" if x else "无成交")
