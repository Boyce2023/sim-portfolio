#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""sub2_test_anatomy.py - 检验已拉取 5m 真实数据的点火时点 (上午 vs 下午) 与异动双红线 (10日100% vs 30日200%)"""

import pickle, pandas as pd, numpy as np

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
cache_path = f"{OUT_DIR}/sub2_5m_bars_cache.pkl"
part1_path = f"{OUT_DIR}/part1_cache.pkl"

(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(part1_path, "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/dfr_deep_native.pkl")
cache = pickle.load(open(cache_path, "rb"))

print(f"Loaded cache with {len(cache)} entries.")

# 1. 检验 10日100% vs 30日200% 异动线
def get_double_yidong_px(bars, cp, idx_map, disc=0.07):
    cd = bars["dts"][cp]
    ir = idx_map.get(cd)
    if not ir: return 99999.0, 99999.0
    
    # 10日100%
    pl_10_min = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k
        bi = idx_map.get(bars["dts"][p])
        bc = bars["close"][p]
        if bi and bc > 0:
            pl = bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0))
            if pl < pl_10_min: pl_10_min = pl
            
    # 30日200%
    pl_30_min = 99999.0
    for k in range(1, min(31, cp + 1)):
        p = cp - k
        bi = idx_map.get(bars["dts"][p])
        bc = bars["close"][p]
        if bi and bc > 0:
            pl = bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0))
            if pl < pl_30_min: pl_30_min = pl
            
    return pl_10_min, pl_30_min

tighter_30 = 0
total_checked = 0
for r in dfr.itertuples():
    c6 = str(r.code).zfill(6)
    bars = code_bars[c6]
    if r.buy_date not in bars["p"]: continue
    d2p = bars["p"][r.buy_date]
    imap = SH_MAP if r.ex == "SH" else SZ_MAP
    p10, p30 = get_double_yidong_px(bars, d2p, imap, disc=0.07)
    if p30 < p10:
        tighter_30 += 1
    total_checked += 1

print(f"Total checked: {total_checked}, 30-day 200% is tighter in {tighter_30} ({tighter_30/total_checked*100:.1f}%) cases!")

# 2. 检验已拉取 5m K 线的买入日点火时点 (上午 vs 下午)
morn_cnt = 0
aft_cnt = 0
no_hit_cnt = 0
for key, df_k in cache.items():
    if df_k is None or df_k.empty: continue
    c6, d1, buy_date = key
    df_d2 = df_k[df_k["date"] == buy_date]
    if df_d2.empty: continue
    
    b_op = df_d2.iloc[0]["open"]
    ipx = b_op * 1.015
    
    df_morn = df_d2[df_d2["hhmm"] <= "11:30"]
    df_aft = df_d2[df_d2["hhmm"] > "11:30"]
    
    morn_hit = (df_morn["high"].max() >= ipx) if not df_morn.empty else False
    aft_hit = (df_aft["high"].max() >= ipx) if not df_aft.empty else False
    
    if morn_hit:
        morn_cnt += 1
    elif aft_hit:
        aft_cnt += 1
        print(f"Afternoon only hit! {c6} {buy_date}: b_op={b_op}, ipx={round(ipx, 2)}, morn_high={df_morn['high'].max()}, aft_high={df_aft['high'].max()}")
    else:
        no_hit_cnt += 1

print(f"5m Ignition stats: Morning hit={morn_cnt}, Afternoon ONLY hit={aft_cnt}, Never hit={no_hit_cnt}")
