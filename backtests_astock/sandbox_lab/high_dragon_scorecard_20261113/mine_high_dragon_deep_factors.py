#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""深挖高标专属微观因子（身位断层差/换手成龙板数/股价/异动剩余空间/K线收盘分位/周历效应/缩量承接）双期同向检验"""
import pickle, re, numpy as np, pandas as pd
from collections import defaultdict

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_DIR}/part1_cache.pkl", "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/dfr_all75_factors.pkl")

def get_dev_px(bars, cp, idx_map, disc=0.00):
    cd = bars["dts"][cp]; ir = idx_map.get(cd)
    if not ir: return 99999.0
    bp_min = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k; bi = idx_map.get(bars["dts"][p]); bc = bars["close"][p]
        if bi and bc > 0:
            pl = bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0))
            if pl < bp_min: bp_min = pl
    return bp_min

# 构造 18 个【高标专属原生因子】（之前通用1进2表里没有的！）
new_feats = defaultdict(list)
for r in dfr.itertuples():
    g0 = by_dt[r.d0]
    zt0 = g0[g0["is_zt"]]
    streaks = sorted(zt0["streak"].unique(), reverse=True)
    second_b = int(streaks[1]) if len(streaks) > 1 else 0
    # 1. 身位断层领先优势 (第一高领先第二高几板！如8板领先4板=断层4板)
    new_feats["lead_gap"].append(int(r.st0 - second_b))
    # 2. 买日星期几 (周一=0 .. 周五=4)
    wd = pd.Timestamp(r.buy_date).weekday()
    new_feats["is_mon_tue"].append(wd in (0, 1))
    new_feats["is_thu_fri"].append(wd in (3, 4))
    new_feats["is_wed"].append(wd == 2)

    bars = code_bars[r.code]
    d1p = bars["p"][r.d1]; d0p = d1p - 1; d2p = d1p + 1
    # 3. 绝对股价高低 (游资偏爱低价股 <20元 vs 高价股 >35元)
    px_d1 = float(bars["close"][d1p])
    new_feats["low_price_le20"].append(px_d1 <= 20.0)
    new_feats["high_price_gt35"].append(px_d1 > 35.0)
    # 4. 连板期间真实换手板数量 (非一字板个数: 换手成龙 vs 一字虚高)
    turn_b_cnt = sum(1 for k in range(max(0, d0p - r.st0 + 1), d0p + 1) if bars["is_zt"][k] and (not bars["is_yizi"][k]))
    new_feats["turn_boards_cnt"].append(turn_b_cnt)
    new_feats["turn_boards_ge4"].append(turn_b_cnt >= 4)
    # 5. D1 首阴K线收盘处在全天振幅的分位 (close - low) / (high - low): 尾盘抢筹光头真阳 vs 冲高回落
    rng = max(float(bars["high"][d1p] - bars["low"][d1p]), 0.01)
    c_pos = float(bars["close"][d1p] - bars["low"][d1p]) / rng
    new_feats["d1_close_pos_in_rng"].append(c_pos)
    new_feats["d1_strong_close_ge70"].append(c_pos >= 0.70)
    # 6. D1 是否曾摸涨停炸板 vs 全天未摸板水下换手洗盘
    d1_touch_zt = float(bars["high"][d1p]) >= float(bars["zt_px"][d1p]) - 0.011
    new_feats["d1_no_touch_zt"].append(not d1_touch_zt)
    # 7. D1 是否触及过跌停深水撬起 (大长腿承接)
    d1_deep_dip = (float(bars["low"][d1p]) / float(bars["pre_c"][d1p]) - 1.0) <= -0.06
    new_feats["d1_deep_dip_le6"].append(d1_deep_dip)
    # 8. 10日100%严重异动剩余安全空间 (headroom_100)
    imap = SH_MAP if r.ex == "SH" else SZ_MAP
    p100 = get_dev_px(bars, d2p, imap, 0.00)
    hr100 = p100 / float(bars["open"][d2p]) - 1.0
    new_feats["headroom_100"].append(hr100)
    new_feats["headroom_ge18"].append(hr100 >= 0.18)
    new_feats["headroom_lt08"].append(hr100 < 0.08)
    # 9. D1 量比 (相对于 D0 成交量/换手是温和放量还是缩量还是天量2.5倍爆量)
    g1_row = by_dt[r.d1].set_index("c6").loc[r.code]
    vr = float(g1_row["d1_vol_r"])
    new_feats["d1_vol_r_mild"].append(0.75 <= vr <= 1.85)
    new_feats["d1_vol_r_blowout"].append(vr > 2.20)
    # 10. 深市主板(00) vs 沪市主板(60)
    new_feats["is_sz_00"].append(r.ex == "SZ")

for k, v in new_feats.items():
    dfr[k] = v

is_m = dfr["buy_date"] < "2025-01-01"
oos_m = dfr["buy_date"] >= "2025-01-01"

print("=== 高标专属原生因子 2022-2024 vs 2025-2026 双期同向检验 ===")
for k in new_feats.keys():
    s1 = dfr.loc[is_m, [k, "ret_e2"]].dropna()
    s2 = dfr.loc[oos_m, [k, "ret_e2"]].dropna()
    if pd.api.types.is_bool_dtype(dfr[k]):
        h1, l1 = s1[s1[k]]["ret_e2"].mean()*100, s1[~s1[k]]["ret_e2"].mean()*100
        h2, l2 = s2[s2[k]]["ret_e2"].mean()*100, s2[~s2[k]]["ret_e2"].mean()*100
        n1, n2 = int(s1[k].sum()), int(s2[k].sum())
    else:
        med = s1[k].median()
        h1, l1 = s1[s1[k]>med]["ret_e2"].mean()*100, s1[s1[k]<=med]["ret_e2"].mean()*100
        h2, l2 = s2[s2[k]>med]["ret_e2"].mean()*100, s2[s2[k]<=med]["ret_e2"].mean()*100
        n1, n2 = int((s1[k]>med).sum()), int((s2[k]>med).sum())
    d1_v, d2_v = h1 - l1, h2 - l2
    tag = "★双期同向" if d1_v * d2_v > 0 else "  反向噪音"
    print(f"  {tag} | {k:22s} | 22-24(n={n1:2d}): 差={d1_v:+6.2f}% ({h1:+5.2f}%/{l1:+5.2f}%) | 25-26(n={n2:2d}): 差={d2_v:+6.2f}% ({h2:+5.2f}%/{l2:+5.2f}%)")

dfr.to_pickle(f"{OUT_DIR}/dfr_deep_native.pkl")
