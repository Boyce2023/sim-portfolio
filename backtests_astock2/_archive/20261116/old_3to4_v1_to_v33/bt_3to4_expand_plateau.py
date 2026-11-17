#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""三进四扩笔数第三步：只看门槛平原（88/90/92三档几何平均）与按日等权，防刀尖过拟合"""
import numpy as np, pandas as pd
import bt_3to4_expand_soft_skeleton as B
from core_3to4_5m_engine import _slice_metrics_chrono

d, p = B.d, B.p_v32
def stats(mask, sc, th):
    sel = np.where(mask & (sc >= th))[0]
    t = pd.DataFrame([dict(p[i], priority_score=float(sc[i]) * 10 + float(d.prio_3to4.iloc[i]) * 0.1) for i in sel if p[i] is not None])
    s = _slice_metrics_chrono(t, "2022-01-04", "2026-11-10")
    j7 = _slice_metrics_chrono(t[t.buy_date >= "2026-07-01"], "2026-07-01", "2026-11-10")
    yrs = [_slice_metrics_chrono(t[t.buy_date.str.startswith(y)], f"{y}-01-01", f"{y}-12-31" if y != "2026" else "2026-11-10")["single_nav"] for y in ["2022", "2023", "2024", "2025", "2026"]]
    return s, j7, min(yrs)

def plateau(tag, mask, sc):
    out = [stats(mask, sc, th) for th in (88, 90, 92)]
    g = float(np.exp(np.mean([np.log(o[0]["single_nav"]) for o in out])))
    ge = float(np.exp(np.mean([np.log(o[0]["eq_nav"]) for o in out])))
    s, j7, mn = out[1]
    print(f"{tag:34s} | 三档平原单仓{g:6.1f}x 等权{ge:6.1f}x | 90分: {s['single_n']:3d}笔 WR={s['wr']:4.1f}% PO={s['payoff']:4.2f} NAV={s['single_nav']:6.1f}x MDD={s['single_mdd_pct']:4.1f}% 最差年{mn:4.2f}x 7月起{j7['single_n']}笔{j7['single_nav']:4.2f}x")

core, top1, obc, lock, to_ok, op_ok, pts, newf = B.core, B.top1, B.obc, B.lock, B.to_ok, B.op_ok, B.pts, B.newf
sk = B.skel33
plateau("P0 现役V3.3", sk, pts)
plateau("P1 V3.3+新四因子", sk, pts + newf)
f_basket = np.where(d.is_event_basket.astype(bool), -6, 0)
f_brk = np.where(d.prev_break_dt_rate_10d >= 0.20, -3, 0)
f_seal = np.where(d.roll20_ho_zt < 0.45, 3, 0)
plateau("P2 V3.3+仅事件大筐扣6", sk, pts + f_basket)
plateau("P3 V3.3+仅断板跌停率扣3", sk, pts + f_brk)
plateau("P4 V3.3+仅低封板率加3", sk, pts + f_seal)
for pen in (3, 5, 8):
    plateau(f"P5 换手改软(越界扣{pen})", core & top1 & obc & lock & op_ok, pts - pen + np.where(to_ok, pen, 0))
for pen in (4, 6, 8):
    plateau(f"P6 锁仓改软(双低扣{pen})", core & top1 & obc & to_ok & op_ok, pts - pen + np.where(lock, pen, 0))
for pen in (6, 10):
    plateau(f"P7 头名改软(非头名扣{pen})", core & obc & lock & to_ok & op_ok, pts - pen + np.where(top1, pen, 0))
wide_op = d.open_pct.between(0.02, 0.095)
plateau("P8 高开放宽2至9.5(2至3扣6)", core & top1 & obc & lock & to_ok & wide_op, pts + np.where(d.open_pct < 0.03, -6, 0))
