#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""三进四 V3.4 过拟合体检：门槛放松扫描、权重随机扰动、剔除大牛股、逐年对比"""
import numpy as np, pandas as pd
import bt_3to4_expand_soft_skeleton as B
from core_3to4_5m_engine import _slice_metrics_chrono

d, p = B.d, B.p_v32
fst = pd.to_numeric(d.first_seal_time.astype(str).str.replace(":", "").str[:4], errors="coerce").fillna(9999)
mask = B.core & B.obc & B.op_ok
lock = B.lock; to_ok = B.to_ok; top1 = B.top1
C = [  # (权重, 条件)
    (8, d.px_d3 <= 20), (-5, d.px_d3 > 32), (8, d.mkt_max_board_prev <= 4), (3, d.p_elo >= 115),
    (-10, d.mkt_zt_prev >= 95), (5, d.mkt_zt_prev.between(35, 85)), (-12, d.has_ex_reg.astype(bool)), (-12, d.surf_yz_buy.astype(bool)),
    (4, d.lhb_lh_cnt == 0), (-5, d.lhb_lh_cnt >= 3), (4, (d.plate_fb_ho_cnt >= 2) & (d.plate_fb_yz_cnt == 0)), (-7, d.plate_fb_yz_cnt >= 1),
    (-10, d.plate_peers_open_avg < -0.015), (3, d.prev_3b_dt_cnt == 0), (-4, d.prev_3b_dt_cnt >= 2),
    (-8, (d.csi_1d_prev <= -0.02) | (d.csi_5d_prev <= -0.03)), (3, d.prev_to.between(9.5, 28)),
    (2, d.is_post_holiday_or_mon.astype(bool)), (-4, d.buy_month.isin([1, 5])),
    (-12, ~top1), (-10, ~lock), (-10, ~to_ok), (3, fst.between(936, 1030)),
]
W = np.array([w for w, _ in C], float); X = np.column_stack([np.asarray(m, float) for _, m in C])
def score(w): return np.where(mask, 78 + X @ w, -999.0)
sc0 = score(W)
assert int((sc0 != d.score_v33).sum()) == 0

def ev(sc, th=90, drop_top=0):
    idx = np.where(sc >= th)[0]
    t = pd.DataFrame([dict(p[i], priority_score=float(sc[i]) * 10 + float(d.prio_3to4.iloc[i]) * 0.1) for i in idx if p[i] is not None])
    s = _slice_metrics_chrono(t, "2022-01-04", "2026-11-10")
    yrs = [_slice_metrics_chrono(t[t.buy_date.str.startswith(y)], f"{y}-01-01", f"{y}-12-31" if y != "2026" else "2026-11-10")["single_nav"] for y in ["2022", "2023", "2024", "2025", "2026"]]
    return s, yrs

print("=== 一、门槛放松扫描（笔数变多会怎样）===")
for th in (78, 80, 82, 84, 86, 88, 90, 92, 94):
    s, y = ev(sc0, th)
    print(f"门槛{th:3d} | {s['single_n']:3d}笔 WR={s['wr']:4.1f}% PO={s['payoff']:4.2f} 单仓={s['single_nav']:7.2f}x MDD={s['single_mdd_pct']:4.1f}% 去前五={s['trimmed5_nav']:5.2f}x | 逐年{[round(v,2) for v in y]}")

print("=== 二、全部23项权重各自随机打七折到一点三倍，跑300次 ===")
rng = np.random.default_rng(7); navs, allpos, beat = [], 0, 0
for _ in range(300):
    s, y = ev(score(W * rng.uniform(0.7, 1.3, len(W))))
    navs.append(s["single_nav"]); allpos += int(min(y) > 1.0); beat += int(s["single_nav"] > 187.6)
navs = np.array(navs)
print(f"中位数{np.median(navs):.1f}x 最差10%分位{np.percentile(navs,10):.1f}x 最差{navs.min():.1f}x | 跑赢V3.3的187.6倍占{beat/3:.0f}% | 五年全正占{allpos/3:.0f}%")

print("=== 三、剔除收益最大的若干笔（看是不是靠几只妖股撑着）===")
s, _ = ev(sc0)
idx = np.where(sc0 >= 90)[0]
t = pd.DataFrame([dict(p[i], priority_score=float(sc0[i]) * 10) for i in idx if p[i] is not None])
from core_3to4_5m_engine import _sim_single_slot_chrono
taken, nav, mdd, _ = _sim_single_slot_chrono(t)
r = np.sort(np.array([x.net_ret for x in taken]))[::-1]
for k in (0, 3, 5, 10):
    print(f"剔除最赚{k:2d}笔 | 剩余{len(r)-k}笔 净值={np.prod(1 + r[k:]):7.2f}x 笔均={r[k:].mean()*100:+.2f}%")
print("最赚的5笔:", [f"{v*100:+.1f}%" for v in r[:5]])
