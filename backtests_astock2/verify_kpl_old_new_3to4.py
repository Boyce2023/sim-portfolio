#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import os, sys, json, numpy as np, pandas as pd
from collections import defaultdict

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path: sys.path.insert(0, CUR_DIR)
ROOT = "/Users/huaichuaibeimeng/claude-projects"

from core_3to4_5m_engine import evaluate_5m_d15
from bt_3to4_scorecard_verify import load_all_5m, build_scores

df, _ = load_all_5m()
skel, sc_v31, _ = build_scores(df)

# Parse nested kpl_plates_2018_2026_merged.jsonl properly
hist_pl = defaultdict(list)
with open(f"{ROOT}/sim-portfolio/data/kpl_plates_2018_2026_merged.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip(): continue
        o = json.loads(line)
        dt = str(o.get("date", ""))[:10]
        if dt < "2020-12-01": continue
        for p_obj in o.get("plates", []):
            pl = str(p_obj.get("plate", ""))
            if not pl or pl in ("其他", "ST板块", "新股与次新股"): continue
            for st in p_obj.get("stocks", []):
                if st: hist_pl[str(st[0])[:6]].append((dt, pl))

old_old, old_new = [False]*len(df), [False]*len(df)
for i, r in enumerate(df.itertuples(index=False)):
    c6, sd, cur_p = str(r.code).zfill(6), str(r.sig_date), str(r.plate)
    arr_p = [p for d, p in hist_pl.get(c6, []) if d < sd and 5 <= (pd.Timestamp(sd) - pd.Timestamp(d)).days <= 365]
    if len(arr_p) >= 1 and cur_p and cur_p != "其他":
        if cur_p in arr_p: old_old[i] = True
        else: old_new[i] = True

df["kpl_old_old"] = old_old; df["kpl_old_new"] = old_new
sub = df[skel & df["net_ret_5m"].notna()].copy()
sub_r = sub[sub["buy_date"] >= "2024-01-01"]
for nm, col in [("7b.开盘啦老熟票炒纯正老题材", "kpl_old_old"), ("7c.开盘啦老熟票蹭陌生新概念", "kpl_old_new")]:
    a1, a0 = sub.loc[sub[col], "net_ret_5m"], sub.loc[~sub[col], "net_ret_5m"]
    r1, r0 = sub_r.loc[sub_r[col], "net_ret_5m"], sub_r.loc[~sub_r[col], "net_ret_5m"]
    print(f"{nm:28s} | 5Y(n={len(a1):3d}): WR={(a1>0).mean()*100:4.1f}%(Δ{((a1>0).mean()-(a0>0).mean())*100:+5.1f}%) Mean={a1.mean()*100:+5.2f}%(Δ{(a1.mean()-a0.mean())*100:+5.2f}%) || 24-26(n={len(r1):3d}): WR={(r1>0).mean()*100:4.1f}%(Δ{((r1>0).mean()-(r0>0).mean())*100:+5.1f}%) Mean={r1.mean()*100:+5.2f}%(Δ{(r1.mean()-r0.mean())*100:+5.2f}%)")
