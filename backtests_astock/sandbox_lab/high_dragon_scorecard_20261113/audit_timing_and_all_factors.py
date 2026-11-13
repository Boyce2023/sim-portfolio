#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""全量因子普查（75+因子）与 2022-2024 择时机制深度拆解（零未来函数）"""
import json, pickle, glob
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
GFM_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"

(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_DIR}/part1_cache.pkl", "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/dfr_pit.pkl")
df_1c = pd.read_parquet(f"{GFM_DIR}/verified_1c_rebound_cands.parquet")
df_1c["c6"] = df_1c["code"].astype(str).str.zfill(6)

# 构建每日全市场微观择时指标（全部在 D1 收盘已知，零未来！）
# 含：微盘股等权指数20日涨跌(micro_r20)、5日涨跌(micro_r5)、昨日涨停次日平均溢价(zt_prem_5d)、全场涨停数(n_zt)、跌停数(n_dt)、最高连板高度(max_b)、3板+家数(n_b3p)、连板晋级率(promo_rate_5d)
mkt_timing = {}
micro_lvl = 1.0
micro_hist = []
prem_hist = []
promo_hist = []
prev_zt_codes = set()
prev_ge2_codes = set()

for i, d in enumerate(all_dts):
    grp = by_dt[d]
    # 微盘股（市值最小的400只主板非一字跌停票当日均涨跌）
    sml = grp.nsmallest(400, "mcap")
    m_ret = float(sml["pct"].mean()) if len(sml) else 0.0
    micro_lvl *= (1.0 + m_ret)
    micro_hist.append(micro_lvl)
    mr5 = micro_lvl / micro_hist[max(0, i - 5)] - 1.0
    mr20 = micro_lvl / micro_hist[max(0, i - 20)] - 1.0
    ma20 = np.mean(micro_hist[max(0, i - 19):i + 1])
    above_ma20 = micro_lvl >= ma20

    # 昨日涨停今日开盘溢价 & 收盘溢价
    if prev_zt_codes:
        sub_p = grp[grp["c6"].isin(prev_zt_codes)]
        op_prem = float(sub_p["o_pct"].mean()) if len(sub_p) else 0.0
        cl_prem = float(sub_p["pct"].mean()) if len(sub_p) else 0.0
        pr_cnt = int(sub_p["is_zt"].sum())
        pr_rate = pr_cnt / max(1, len(sub_p))
    else:
        op_prem, cl_prem, pr_rate = 0.0, 0.0, 0.0
    prem_hist.append(cl_prem)
    promo_hist.append(pr_rate)

    zt_g = grp[grp["is_zt"]]
    prev_zt_codes = set(zt_g["c6"])
    mkt_timing[d] = {
        "micro_r5": mr5,
        "micro_r20": mr20,
        "micro_above_ma20": above_ma20,
        "zt_cl_prem_d1": cl_prem,
        "zt_cl_prem_ma5": float(np.mean(prem_hist[-5:])),
        "promo_rate_ma5": float(np.mean(promo_hist[-5:])),
        "n_zt": int(len(zt_g)),
        "n_dt": int(grp["is_dt"].sum()),
        "zt_dt_ratio": float(len(zt_g)) / max(1.0, float(grp["is_dt"].sum())),
        "max_b_d1": int(zt_g["streak"].max()) if len(zt_g) else 0,
        "n_b3p_d1": int((zt_g["streak"] >= 3).sum()),
        "tot_amt_yi": float(grp["amount"].sum() / 1e8),
    }

# 合并 df_1c 里的全部微观盘口因子（封板时间、开板次数、封单金额、社区发帖、机构调研、板块ELO等）
c1_map = {}
for r in df_1c.itertuples():
    c1_map[(str(r.buy_date)[:10], r.c6)] = r

# 给 dfr 挂载所有择时因子与微观因子，并计算滚动前3笔首阴胜率（反馈环择时）
dfr = dfr.sort_values("buy_date").reset_index(drop=True)
closed_trades = []
roll3_wr, roll3_mean = [], []
for r in dfr.itertuples():
    ed, ret, _, _ = r.auc_e2
    past = [x[1] for x in closed_trades if x[0] < r.buy_date]
    closed_trades.append((ed, ret))
    if len(past) >= 3:
        roll3_wr.append(float(np.mean([v > 0 for v in past[-3:]])))
        roll3_mean.append(float(np.mean(past[-3:])))
    else:
        roll3_wr.append(0.5)
        roll3_mean.append(0.0)
dfr["roll3_wr"] = roll3_wr
dfr["roll3_mean"] = roll3_mean

for k in ["micro_r5", "micro_r20", "micro_above_ma20", "zt_cl_prem_d1", "zt_cl_prem_ma5", "promo_rate_ma5", "n_zt", "n_dt", "zt_dt_ratio", "max_b_d1", "n_b3p_d1", "tot_amt_yi"]:
    dfr[k] = [mkt_timing[d][k] for d in dfr["d1"]]

extra_cols = ["first_seal_time", "open_board_count", "seal_amount", "is_hard_open_1030", "has_ir_8d", "comm_posts_24h", "p_elo", "s_prior", "mkt_fb_open_avg", "mkt_seal_rate_prev", "zt_cnt_pre20", "prev_3to4_nuke_rate_20d"]
for col in extra_cols:
    vals = []
    for r in dfr.itertuples():
        m = c1_map.get((r.buy_date, r.code))
        vals.append(getattr(m, col) if m is not None and hasattr(m, col) else np.nan)
    dfr[col] = vals

dfr["ret_e2"] = [x[1] for x in dfr["auc_e2"]]
is_m = dfr["buy_date"] < "2025-01-01"
oos_m = dfr["buy_date"] >= "2025-01-01"

print(f"=== 1. 为什么 2022-2024 收益偏低？先看逐年候选数与大肉分布 ===")
for yr in ["2022", "2023", "2024", "2025", "2026"]:
    s = dfr[dfr["buy_date"].str.startswith(yr)]
    w_s = s[s["ret_e2"] > 0]
    l_s = s[s["ret_e2"] <= 0]
    print(f"  {yr}: 总触发={len(s):2d}笔 | 胜率={(s['ret_e2']>0).mean()*100:5.1f}% | 均值={s['ret_e2'].mean()*100:+5.2f}% | 赚>10%大肉={int((s['ret_e2']>=0.10).sum()):2d}笔 | 亏<-8%大面={int((s['ret_e2']<=-0.08).sum()):2d}笔 | 全做复利={(1+s['ret_e2']).prod():.2f}x")

print(f"\n=== 2. 择时因子大比拼（重点看能否把 2022-2024 提上去且 2025-2026 依然强！）===")
timing_tests = [
    ("T0_不择时全做 (换手<=38% -6%~+5%)", (dfr["d1_to"]<=38)&(dfr["op2"]>=-0.06)&(dfr["op2"]<=0.05)),
    ("T1_微盘股站上20日均线 (micro_above_ma20)", dfr["micro_above_ma20"]),
    ("T2_微盘股20日涨幅 > 0%", dfr["micro_r20"] > 0.0),
    ("T3_微盘股5日涨幅 > -2% (非微盘股崩盘周)", dfr["micro_r5"] > -0.02),
    ("T4_涨跌停家数比 >= 3.0 (非恐慌冰点)", dfr["zt_dt_ratio"] >= 3.0),
    ("T5_涨跌停家数比 >= 5.0 (多头情绪区)", dfr["zt_dt_ratio"] >= 5.0),
    ("T6_昨日涨停5日均收盘溢价 > +1.0%", dfr["zt_cl_prem_ma5"] > 0.01),
    ("T7_昨日涨停5日均收盘溢价 > +2.0%", dfr["zt_cl_prem_ma5"] > 0.02),
    ("T8_近5日连板晋级率 >= 20%", dfr["promo_rate_ma5"] >= 0.20),
    ("T9_全场涨停 >= 45家 且 跌停 <= 15家", (dfr["n_zt"] >= 45) & (dfr["n_dt"] <= 15)),
    ("T10_D0最高板 >= 6板 (高空间周期)", dfr["st0"] >= 6),
    ("T11_D0最高板 == 4~5板 (压制期低空间)", dfr["st0"].isin([4, 5])),
    ("T12_前3笔首阴至少赢1笔 (roll3_wr > 0)", dfr["roll3_wr"] > 0.0),
    ("T13_前3笔首阴至少赢2笔 (roll3_wr >= 0.66)", dfr["roll3_wr"] >= 0.66),
    ("T14_近10日高标断板跌停率 <= 30%", dfr["brk_r10"] <= 0.30),
    ("T15_本所零发函 且 跌停<=15家 且 微盘5日>-2%", (dfr["ex_reg5"] == 0) & (dfr["n_dt"] <= 15) & (dfr["micro_r5"] > -0.02)),
]
base_ok = (dfr["d1_to"] <= 38.0) & (dfr["op2"] >= -0.06) & (dfr["op2"] <= 0.05) & (~dfr["s_reg"]) & (~dfr["tox"])
for tname, tmask in timing_tests:
    si = dfr[base_ok & is_m & tmask]
    so = dfr[base_ok & oos_m & tmask]
    sf = dfr[base_ok & tmask]
    # Single slot NAV
    def s_nav(sub):
        taken, fd, nav, pk, mdd = [], "", 1.0, 1.0, 0.0
        for r in sub.sort_values("buy_date").itertuples():
            ed, rt, _, _ = r.auc_e2
            if fd == "" or r.buy_date > fd:
                taken.append(rt); fd = ed; nav *= (1.0 + rt); pk = max(pk, nav); mdd = max(mdd, (pk - nav)/pk)
        return len(taken), (np.mean([x>0 for x in taken])*100 if taken else 0), nav, mdd*100
    ni, wri, navi, mddi = s_nav(si)
    no, wro, navo, mddo = s_nav(so)
    nf, wrf, navf, mddf = s_nav(sf)
    print(f"  {tname:42s} | 22-24: {ni:2d}笔 WR={wri:4.1f}% NAV={navi:5.2f}x MDD={mddi:4.1f}% | 25-26: {no:2d}笔 WR={wro:4.1f}% NAV={navo:5.2f}x | 5Y: {nf:2d}笔 NAV={navf:6.2f}x MDD={mddf:4.1f}%")

# 保存供下一步检查数值相关性排序
dfr.to_pickle(f"{OUT_DIR}/dfr_all75_factors.pkl")
