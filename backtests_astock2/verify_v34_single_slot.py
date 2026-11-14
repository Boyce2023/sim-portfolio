#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""核验 V3.4 单仓轮动：同日多只过线时，引擎按先触发先买；对比「只挂总分最高1只、不触发就空仓」的严格口径"""
import numpy as np, pandas as pd
import bt_3to4_expand_soft_skeleton as B
from bt_3to4_split_integrate import mask_A, sc_A, fst
from core_3to4_5m_engine import _slice_metrics_chrono

d, p = B.d, B.p_v32
sc = np.where(mask_A, sc_A + np.where(fst.between(936, 1030), 3, 0), -999.0)
assert int((sc != d.score_v33).sum()) == 0, "与落盘分数不一致"
c = d[sc >= 90].assign(sc=sc[sc >= 90])
per_day = c.groupby("buy_date").size()
print(f"过90分候选 {len(c)} 只，分布在 {len(per_day)} 天，其中同日2只及以上 {int((per_day >= 2).sum())} 天")

def show(tag, idx):
    t = pd.DataFrame([dict(p[i], priority_score=float(sc[i]) * 10 + float(d.prio_3to4.iloc[i]) * 0.1) for i in idx if p[i] is not None])
    s = _slice_metrics_chrono(t, "2022-01-04", "2026-11-10")
    j = _slice_metrics_chrono(t[t.buy_date >= "2026-07-01"], "2026-07-01", "2026-11-10")
    r3 = _slice_metrics_chrono(t[t.buy_date >= "2024-01-02"], "2024-01-02", "2026-11-10")
    print(f"{tag:34s} | {s['single_n']}笔 WR={s['wr']:.1f}% PO={s['payoff']:.2f} NAV={s['single_nav']:.2f}x MDD={s['single_mdd_pct']:.1f}% 等权={s['eq_nav']:.1f}x | 近三年{r3['single_nav']:.2f}x | 7月起{j['single_n']}笔{j['single_nav']:.2f}x")

all_idx = list(np.where(sc >= 90)[0])
show("口径一 引擎现状：先触发先买", all_idx)
top_idx = []
for bd, g in c.groupby("buy_date"):
    g = g.assign(pr=g.sc * 10 + g.prio_3to4 * 0.1).sort_values("pr", ascending=False)
    top_idx.append(d.index.get_loc(g.index[0]))
show("口径二 严格：只挂当日最高分1只", top_idx)
top1_idx = [i for i in all_idx if bool(d.is_top1_3b_open.iloc[i])]
show("口径三 只做竞价头名（旧骨架思路）", top1_idx)
multi = per_day[per_day >= 2].index
for bd in multi[-8:]:
    g = c[c.buy_date == bd]
    print("  同日多只:", bd, [(str(r.code).zfill(6), r["name"], int(r.sc), ("头名" if r.is_top1_3b_open else "非头名"), (f"{p[d.index.get_loc(i)]['net_ret']*100:+.1f}%" if p[d.index.get_loc(i)] else "未触发")) for i, r in g.iterrows()])
