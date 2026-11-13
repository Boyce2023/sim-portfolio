#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""sub2_deep_pathology.py - 深度解剖高标首阴 40.7%/27.8% 回撤病灶与亏损根源"""

import pickle, pandas as pd, numpy as np

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
CACHE_PATH = f"{OUT_DIR}/sub2_5m_bars_cache.pkl"
PART1_PATH = f"{OUT_DIR}/part1_cache.pkl"

(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(PART1_PATH, "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/dfr_deep_native.pkl")
cache = pickle.load(open(CACHE_PATH, "rb"))

# 载入现行 V2 80分交割单
v2_led = pd.read_csv(f"{OUT_DIR}/v2_pure_yin_80_ledger.csv")
v2_cb_led = pd.read_csv(f"{OUT_DIR}/v2_pure_yin_80_cb_ledger.csv")

print("=== 1. V2 80分交割单亏损单病灶解剖 ===")
bad_v2 = v2_led[v2_led["net_ret"] <= -0.05].copy()
print(f"V2 总共 52 笔，亏损超过 -5% 的大面单共 {len(bad_v2)} 笔:")

def analyze_trade(r, bars, df_k, imap):
    c6 = str(r.code).zfill(6)
    d2p = bars["p"][r.buy_date]
    d3p = min(d2p + 1, len(bars["dts"]) - 1)
    d2_zt = bool(bars["is_zt"][d2p])
    
    # D2 走势
    df_d2 = df_k[df_k["date"] == r.buy_date] if df_k is not None else pd.DataFrame()
    d2_open = bars["open"][d2p]
    d2_close = bars["close"][d2p]
    d2_high = bars["high"][d2p]
    d2_low = bars["low"][d2p]
    
    # D3 走势
    d3_dt = bars["dts"][d3p]
    df_d3 = df_k[df_k["date"] == d3_dt] if df_k is not None else pd.DataFrame()
    d3_open = bars["open"][d3p]
    d3_close = bars["close"][d3p]
    d3_high = bars["high"][d3p]
    d3_low = bars["low"][d3p]
    d3_pre_c = bars["pre_c"][d3p]
    
    d3_op_pct = (d3_open / d3_pre_c - 1.0) * 100
    d3_c_pct = (d3_close / d3_pre_c - 1.0) * 100
    d3_hi_pct = (d3_high / d3_pre_c - 1.0) * 100
    
    # 10:30 价格与 VWAP
    p_1030, vwap_1030 = np.nan, np.nan
    if not df_d3.empty:
        sub_1030 = df_d3[df_d3["hhmm"] <= "10:30"]
        if not sub_1030.empty:
            p_1030 = sub_1030.iloc[-1]["close"]
            vol_sum = sub_1030["volume"].sum()
            vwap_1030 = sub_1030["amount"].sum() / (vol_sum * 100) if vol_sum > 0 else p_1030
            
    return {
        "d2_zt": d2_zt,
        "d2_c_ret": (d2_close / d2_open - 1.0) * 100,
        "d3_op_pct": d3_op_pct,
        "d3_c_pct": d3_c_pct,
        "d3_hi_pct": d3_hi_pct,
        "p_1030": p_1030,
        "vwap_1030": vwap_1030,
        "p_1030_pct": (p_1030 / d3_pre_c - 1.0) * 100 if pd.notna(p_1030) else np.nan,
    }

for r in bad_v2.itertuples():
    c6 = str(r.code).zfill(6)
    bars = code_bars[c6]
    df_k = cache.get((c6, str(r.buy_date), str(r.buy_date))) # check key
    if df_k is None:
        # find matching key in cache
        for k, v in cache.items():
            if k[0] == c6 and k[2] == r.buy_date:
                df_k = v; break
    info = analyze_trade(r, bars, df_k, SH_MAP if c6.startswith("6") else SZ_MAP)
    print(f"  {r.buy_date} {c6} {r.name:4s}: 净盈亏={r.net_ret*100:+5.1f}% | D2封板={info['d2_zt']} D2涨跌={info['d2_c_ret']:+5.1f}% | D3开盘={info['d3_op_pct']:+5.1f}% 10:30={info['p_1030_pct']:+5.1f}% D3收盘={info['d3_c_pct']:+5.1f}%")

print("\n=== 2. 全池 119 笔中 D2 未封板 vs 封板的次日 (D3) 真实走势与亏损对比 ===")
d2_not_zt_cnt = 0
d2_not_zt_d3_down = 0
d2_not_zt_d3_drop_further = 0
for r in dfr.itertuples():
    c6 = str(r.code).zfill(6)
    bars = code_bars[c6]
    d2p = bars["p"][r.buy_date]
    d3p = min(d2p + 1, len(bars["dts"]) - 1)
    if not bars["is_zt"][d2p]:
        d2_not_zt_cnt += 1
        d3_op = bars["open"][d3p] / bars["pre_c"][d3p] - 1.0
        d3_cl = bars["close"][d3p] / bars["pre_c"][d3p] - 1.0
        if d3_cl < 0:
            d2_not_zt_d3_down += 1
        if d3_cl < d3_op:
            d2_not_zt_d3_drop_further += 1

print(f"全池 119 笔中 D2 未封涨停的有 {d2_not_zt_cnt} 笔 (占 {d2_not_zt_cnt/len(dfr)*100:.1f}%)")
print(f"  其中 D3 收盘收绿的有 {d2_not_zt_d3_down} 笔 (占 {d2_not_zt_d3_down/d2_not_zt_cnt*100:.1f}%)")
print(f"  其中 D3 开盘后继续全天阴跌 (收盘 < 开盘) 的有 {d2_not_zt_d3_drop_further} 笔 (占 {d2_not_zt_d3_drop_further/d2_not_zt_cnt*100:.1f}%)")
print(f"  --> 这就是为什么死拿到 D3 收盘会吃大面！如果 D3 09:25 开盘直接卖，能规避全天持续阴跌！")

print("\n=== 3. 检验 119 笔点火时间：上午 09:30-11:30 vs 下午 13:00-15:00 ===")
m_only, a_only, both, neither = 0, 0, 0, 0
for r in dfr.itertuples():
    c6 = str(r.code).zfill(6)
    df_k = None
    for k, v in cache.items():
        if k[0] == c6 and k[2] == r.buy_date:
            df_k = v; break
    if df_k is None or df_k.empty: continue
    df_d2 = df_k[df_k["date"] == r.buy_date]
    if df_d2.empty: continue
    b_op = df_d2.iloc[0]["open"]
    ipx = b_op * 1.015
    m_hit = (df_d2[df_d2["hhmm"] <= "11:30"]["high"].max() >= ipx)
    a_hit = (df_d2[df_d2["hhmm"] > "11:30"]["high"].max() >= ipx)
    if m_hit and (not a_hit): m_only += 1
    elif a_hit and (not m_hit): a_only += 1
    elif m_hit and a_hit: both += 1
    else: neither += 1

print(f"119 笔点火时点统计: 上午点火={m_only + both} (其中仅上午={m_only}, 全天均触及={both}) | 仅下午偷袭点火={a_only} | 全天从未点火={neither}")

print("\n=== 4. 检验断板日『真阳免死一次 (yang_immune)』到底是赚还是亏？ ===")
# 对比 yang_immune=True vs yang_immune=False
def sim_exit_test(bars, d2_p, buy_px, idx_map, yang_immune=False, use_30d=True):
    d2_zt = bool(bars["is_zt"][d2_p])
    n = len(bars["dts"])
    ep, epx, eo = None, None, False
    if d2_zt:
        imm = False
        for step in range(1, 8):
            p = d2_p + step
            if p >= n: break
            # 异动线
            cd = bars["dts"][p]; ir = idx_map.get(cd)
            pl_min = 99999.0
            if ir:
                for k in range(1, min(11, p + 1)):
                    p_k = p - k; bi = idx_map.get(bars["dts"][p_k]); bc = bars["close"][p_k]
                    if bi and bc > 0:
                        pl = bc * (1.0 + 0.93 + (ir / bi - 1.0))
                        if pl < pl_min: pl_min = pl
                if use_30d:
                    for k in range(1, min(31, p + 1)):
                        p_k = p - k; bi = idx_map.get(bars["dts"][p_k]); bc = bars["close"][p_k]
                        if bi and bc > 0:
                            pl = bc * (1.0 + 1.93 + (ir / bi - 1.0))
                            if pl < pl_min: pl_min = pl
            if bars["open"][p] >= pl_min: ep, epx, eo = p, bars["open"][p], True; break
            elif bars["high"][p] >= pl_min: ep, epx, eo = p, pl_min, False; break
            
            if not bars["is_zt"][p]:
                if yang_immune and (not imm) and (bars["close"][p] > bars["open"][p]):
                    imm = True; continue
                while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
                ep, epx, eo = p, bars["close"][p], False; break
    else:
        # D2 未涨停
        p = min(d2_p + 1, n - 1)
        # 次日集合竞价开盘直接卖
        ep, epx, eo = p, bars["open"][p], True
    if ep is None:
        ep = min(d2_p + 5, n - 1); epx, eo = bars["close"][ep], False
    ret = (epx * bars["adjf"][ep]) / (buy_px * bars["adjf"][d2_p]) * (1.0 - 0.0020) - 1.0
    return bars["dts"][ep], float(ret), max(1, ep - d2_p), eo

# 统计在 D2 涨停的 27 笔样本中，yang_immune 开启 vs 关闭的收益差异
zt_rets_with_imm = []
zt_rets_without_imm = []
for r in dfr.itertuples():
    c6 = str(r.code).zfill(6)
    bars = code_bars[c6]
    d2p = bars["p"][r.buy_date]
    if not bars["is_zt"][d2p]: continue
    imap = SH_MAP if c6.startswith("6") else SZ_MAP
    b_op = float(bars["open"][d2p])
    buy_px = b_op if r.op2 >= 0.0 else b_op * 1.015
    ed1, rt1, _, _ = sim_exit_test(bars, d2p, buy_px, imap, yang_immune=True, use_30d=True)
    ed2, rt2, _, _ = sim_exit_test(bars, d2p, buy_px, imap, yang_immune=False, use_30d=True)
    zt_rets_with_imm.append(rt1)
    zt_rets_without_imm.append(rt2)

print(f"D2 涨停连板标的 (共 {len(zt_rets_with_imm)} 笔):")
print(f"  开启真阳免死 (yang_immune=True): 均值={np.mean(zt_rets_with_imm)*100:+.2f}%, 胜率={np.mean(np.array(zt_rets_with_imm)>0)*100:.1f}%, 累计收益={np.prod(1+np.array(zt_rets_with_imm)):.2f}x")
print(f"  关闭真阳免死 (首次断板即走):     均值={np.mean(zt_rets_without_imm)*100:+.2f}%, 胜率={np.mean(np.array(zt_rets_without_imm)>0)*100:.1f}%, 累计收益={np.prod(1+np.array(zt_rets_without_imm)):.2f}x")
