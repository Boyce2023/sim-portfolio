#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""100%全量95因子普查 + 修复微盘股指数NaN后的真实择时归因与2022-2024收益提升实证"""
import pickle, numpy as np, pandas as pd
from collections import defaultdict

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
GFM_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"

(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_DIR}/part1_cache.pkl", "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/dfr_all75_factors.pkl")
df_1c = pd.read_parquet(f"{GFM_DIR}/verified_1c_rebound_cands.parquet")
df_1c["c6"] = df_1c["code"].astype(str).str.zfill(6)

# 1. 修复微盘股等权指数 (dropna!)
micro_lvl = 1.0
micro_hist = []
micro_map = {}
for i, d in enumerate(all_dts):
    grp = by_dt[d]
    sml = grp[grp["mcap"].notna() & grp["pct"].notna()].nsmallest(400, "mcap")
    mr = float(sml["pct"].mean()) if len(sml) else 0.0
    micro_lvl *= (1.0 + mr)
    micro_hist.append(micro_lvl)
    ma10 = float(np.mean(micro_hist[max(0, i-9):i+1]))
    ma20 = float(np.mean(micro_hist[max(0, i-19):i+1]))
    micro_map[d] = {
        "mc_r5": micro_lvl / micro_hist[max(0, i-5)] - 1.0,
        "mc_r10": micro_lvl / micro_hist[max(0, i-10)] - 1.0,
        "mc_r20": micro_lvl / micro_hist[max(0, i-20)] - 1.0,
        "mc_gt_ma10": micro_lvl >= ma10,
        "mc_gt_ma20": micro_lvl >= ma20,
    }
for k in ["mc_r5", "mc_r10", "mc_r20", "mc_gt_ma10", "mc_gt_ma20"]:
    dfr[k] = [micro_map[d][k] for d in dfr["d1"]]

# 2. 把 df_1c 全部 94 列剩余未挂载列一次性全部挂进 dfr 做 100% 穷尽回测！
c1_map = {(str(r.buy_date)[:10], r.c6): r for r in df_1c.itertuples()}
skip_c = {"code","c6","name","sig_date","buy_date","d1_date","exit_date","ed_nop93","net_ret","ret_nop93","hold_bars","exit_at_open"}
added_cnt = 0
for col in df_1c.columns:
    if col in skip_c or col in dfr.columns: continue
    dfr[col] = [getattr(c1_map.get((r.buy_date, r.code)), col, np.nan) for r in dfr.itertuples()]
    added_cnt += 1

print(f"Total exhausted factor columns on canonical Pool A+B dataset: {len(dfr.columns)} columns (newly merged {added_cnt} from 94-col matrix)")

# 3. 穷尽扫描全部数值与布尔因子在 2022-2024 与 2025-2026 两期【双期同向显著】的真因子！
is_m = dfr["buy_date"] < "2025-01-01"
oos_m = dfr["buy_date"] >= "2025-01-01"
consistent_factors = []
tested_total = 0
for c in dfr.columns:
    if c in ("ret_e2","auc_e2","auc_sm","hyb_sm","d0","d1","buy_date","code","name","ex","pool","reason","plate","r_short","csrc_ind","first_seal_time"):
        continue
    if not (pd.api.types.is_numeric_dtype(dfr[c]) or pd.api.types.is_bool_dtype(dfr[c])):
        continue
    s1 = dfr.loc[is_m, [c, "ret_e2"]].dropna()
    s2 = dfr.loc[oos_m, [c, "ret_e2"]].dropna()
    if len(s1) < 20 or len(s2) < 15 or s1[c].nunique() < 2: continue
    tested_total += 1
    if pd.api.types.is_bool_dtype(dfr[c]) or s1[c].nunique() == 2:
        v_hi = s1[c].max()
        hi1, lo1 = s1[s1[c]==v_hi]["ret_e2"].mean()*100, s1[s1[c]!=v_hi]["ret_e2"].mean()*100
        hi2, lo2 = s2[s2[c]==v_hi]["ret_e2"].mean()*100, s2[s2[c]!=v_hi]["ret_e2"].mean()*100
    else:
        med = s1[c].median()
        if (s1[c]>med).sum() < 5 or (s1[c]<=med).sum() < 5: continue
        hi1, lo1 = s1[s1[c]>med]["ret_e2"].mean()*100, s1[s1[c]<=med]["ret_e2"].mean()*100
        hi2, lo2 = s2[s2[c]>med]["ret_e2"].mean()*100, s2[s2[c]<=med]["ret_e2"].mean()*100
    d1_diff, d2_diff = hi1 - lo1, hi2 - lo2
    if d1_diff * d2_diff > 0 and (abs(d1_diff) >= 1.5 and abs(d2_diff) >= 1.0):
        consistent_factors.append((c, d1_diff, d2_diff, (abs(d1_diff)+abs(d2_diff))/2.0, hi1, lo1, hi2, lo2))

consistent_factors.sort(key=lambda x: x[3], reverse=True)
print(f"\n=== 穷尽回测 {tested_total} 个候选因子后，2022-2024 与 2025-2026【两期100%同向且均超1%】的真有效因子（共 {len(consistent_factors)} 个）===")
for c, d1_v, d2_v, avg_v, h1, l1, h2, l2 in consistent_factors:
    direction = "越高越好(+)" if d1_v > 0 else "越低越好(-)"
    print(f"  {c:26s} | {direction} | 22-24多空差={d1_v:+6.2f}% ({h1:+5.2f}%/{l1:+5.2f}%) | 25-26多空差={d2_v:+6.2f}% ({h2:+5.2f}%/{l2:+5.2f}%)")

# 4. 测试微盘股择时 + 抱团分歧择时在 2022-2024 与 2025-2026 的单仓表现！
base_ok = (dfr["d1_to"] <= 38.0) & (dfr["op2"] >= -0.06) & (dfr["op2"] <= 0.05) & (~dfr["s_reg"]) & (~dfr["tox"]) & (dfr["ex_reg5"] < 2)
def sim_ss(sub, col_ex="auc_e2"):
    taken, fd, nav, pk, mdd = [], "", 1.0, 1.0, 0.0
    for r in sub.sort_values("buy_date").itertuples():
        val = getattr(r, col_ex)
        if val is None: continue
        ed, rt, _, _ = val
        if fd == "" or r.buy_date > fd:
            taken.append(rt); fd = ed; nav *= (1.0 + rt); pk = max(pk, nav); mdd = max(mdd, (pk - nav)/pk)
    return len(taken), (np.mean([x>0 for x in taken])*100 if taken else 0), nav, mdd*100

print("\n=== 修复微盘股指数后的各大【纯择时】单仓对比 (2022-2024 vs 2025-2026) ===")
t_regimes = [
    ("R0_基础池不择时", pd.Series(True, index=dfr.index)),
    ("R1_微盘股站上MA20 (mc_gt_ma20)", dfr["mc_gt_ma20"]),
    ("R2_微盘股不在MA20上方 (~mc_gt_ma20)", ~dfr["mc_gt_ma20"]),
    ("R3_微盘股10日跌幅不超-5% (排除微盘流动性踩踏)", dfr["mc_r10"] > -0.05),
    ("R4_沪深300近20日>-3% (大盘非单边阴跌)", dfr["csi_r20"] > -0.03),
    ("R5_非百股涨停高潮分流 (n_zt < 75)", dfr["n_zt"] < 75),
    ("R6_抱团黄金择时: csi_r20>-4% & mc_r10>-5% & n_zt<80", (dfr["csi_r20"] > -0.04) & (dfr["mc_r10"] > -0.05) & (dfr["n_zt"] < 80)),
    ("R7_抱团精粹择时: R6 + 非主线高潮(~dom) + 3板+<=5家", (dfr["csi_r20"] > -0.04) & (dfr["mc_r10"] > -0.05) & (dfr["n_zt"] < 80) & (~dfr["dom"]) & (dfr["n_b3p_d1"] <= 5)),
]
for rname, rmask in t_regimes:
    ni, wri, navi, mddi = sim_ss(dfr[base_ok & is_m & rmask])
    no, wro, navo, mddo = sim_ss(dfr[base_ok & oos_m & rmask])
    nf, wrf, navf, mddf = sim_ss(dfr[base_ok & rmask])
    print(f"  {rname:52s} | 22-24: {ni:2d}笔 WR={wri:4.1f}% NAV={navi:5.2f}x MDD={mddi:4.1f}% | 25-26: {no:2d}笔 WR={wro:4.1f}% NAV={navo:5.2f}x | 5Y: {nf:2d}笔 NAV={navf:6.2f}x MDD={mddf:4.1f}%")
