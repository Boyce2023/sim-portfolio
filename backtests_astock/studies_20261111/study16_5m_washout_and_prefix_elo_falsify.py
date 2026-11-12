#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
study16_5m_washout_and_prefix_elo_falsify.py
================================================================================
专项回测 16：五分钟分时承接反包与字头动态分证伪回测
核心结论：
- 全样本3494笔反包打板炸板率31.4%至43.7%，全样本打板必亏；
- 假阴真阳长下影弱转强点火空仓填补单仓仍降至117.46倍，周转效率低于原生纯洁一进二；
- 20日字头动态滚动分滞后接盘使单仓净值腰斩至68.07至82.27倍；
- 按字面硬砍外行误杀城建发展等大妖，净值自124.43倍暴跌至93.37倍；
- 判定：全部淘汰，维持策略纯洁底座。
================================================================================
"""
import os, sys, re, pickle, time
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

sys.path.insert(0, "/tmp")
import fg_check_v15_base as vb

hist_fb = vb.hist_fb
all_dts = vb.all_dts
dt_to_idx = vb.dt_to_idx
price_lookup = vb.price_lookup
bars_5m_map = vb.bars_5m_map
ind_map = vb.ind_map
cname_map = vb.cname_map
res_base = vb.res_base
sim_s8 = vb.sim_s8
tot_s8 = vb.tot_s8
FEE_RATE = vb.FEE_RATE

from master_5y_zero_lookahead_walkforward import evaluate_strategy_master, CSI300_ANNUAL, CSI300_5Y_CUM

print("=== Base verification ===")
print(f"V15基线: 笔数={res_base['trades_5y']} | 1S={res_base['nav_1s']:.2f}x | 2S={res_base['nav_2s']:.2f}x | Eq={res_base['daily_eq']:.2f}x | 5yWR={res_base['wr_5y']:.1f}% | 3yWR={res_base['wr_3y']:.1f}% | 26WR={res_base['wr_2026']:.1f}% | MDD={res_base['mdd_1s']:.1f}%")

# Load daily volume & amount
t0 = time.time()
dataset = ds.dataset('/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet', format='parquet')
scanner = dataset.scanner(columns=['date', 'ticker', 'volume', 'amount'], filter=(ds.field('date') >= pd.Timestamp('2021-01-01')))
daily_vol_df = scanner.to_table().to_pandas()
daily_vol_df['dt_str'] = daily_vol_df['date'].dt.strftime('%Y-%m-%d')
daily_vol_df['c6'] = daily_vol_df['ticker'].astype(str).str[:6]
amt_lookup = dict(zip(zip(daily_vol_df['c6'], daily_vol_df['dt_str']), daily_vol_df['amount']))
vol_lookup = dict(zip(zip(daily_vol_df['c6'], daily_vol_df['dt_str']), daily_vol_df['volume']))
print(f"Loaded {len(amt_lookup)} amount records in {time.time()-t0:.2f}s")

# Fast map for c6 to plate
c6_to_plate = dict(zip(hist_fb["c6"], hist_fb["plate"]))

# Build map of active ZT count per plate per day
zt_dates_plate = {}
for (c6, dt), b in price_lookup.items():
    if b[6]: # is_zt
        pl = c6_to_plate.get(c6)
        if pl and pl != "其他":
            k = (pl, dt)
            zt_dates_plate[k] = zt_dates_plate.get(k, 0) + 1

# Static premarket purifier
static_purifier = (~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2))) & (~hist_fb["is_dying_pulse"]) & (~hist_fb["notice_bad"]) & (hist_fb["d1_seal_tightness"] >= 37.0) & (hist_fb["s_prior_wk"] >= 55.0)

# V15 1S trades
v15_trades_1s = res_base['trades_list']
v15_cut_keys = {(t['c6'], t['buy_date']) for t in v15_trades_1s if t['net_ret'] <= 0}
v15_all_keys = {(t['c6'], t['buy_date']) for t in v15_trades_1s}
print(f"V15基线交易数: {len(v15_trades_1s)}, 止损数: {len(v15_cut_keys)}")

def sim_rebound_trade(c6, name, idx_buy, buy_px, fee=FEE_RATE):
    if idx_buy < 0 or idx_buy >= len(all_dts) - 1: return None
    d_buy = all_dts[idx_buy]
    b_buy = price_lookup.get((c6, d_buy))
    if not b_buy: return None
    ob, hb, lb, cb, ztb, dtb, is_ztb, is_yz_dtb = b_buy
    prev_c = round(float(cb), 2)
    idx_next = idx_buy + 1
    b_next = price_lookup.get((c6, all_dts[idx_next]))
    if not b_next:
        return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[idx_next], "exit_at_open": True, "sealed_buy": int(is_ztb), "buy_date": d_buy, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": prev_c}
    on, hn, ln, cn, ztn, dtn, is_ztn, is_yz_dtn = b_next

    if not is_ztb:
        # V15 rule: if close >= prev_close AND next open >= +0.5%, hold next day
        prev_day_bar = price_lookup.get((c6, all_dts[idx_buy - 1]))
        p_c = prev_day_bar[3] if prev_day_bar else ob
        if (cb >= p_c) and (on >= round(cb * 1.005, 2)) and not is_yz_dtn:
            if is_ztn:
                return hold_loop(idx_next + 1, 3, round(float(cn), 2), 0, c6, name, buy_px, idx_buy, fee)
            px = round(float(cn), 2)
            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[idx_next], "exit_at_open": False, "sealed_buy": 0, "buy_date": d_buy, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
        curr = idx_next
        while curr < len(all_dts):
            b = price_lookup.get((c6, all_dts[curr]))
            if not b or not b[7]:
                px = round(float(b[0]), 2) if b else prev_c
                return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_buy": 0, "buy_date": d_buy, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
            curr += 1
        return None

    return hold_loop(idx_next, 2, prev_c, 1, c6, name, buy_px, idx_buy, fee)

def hold_loop(start_idx, init_boards, init_prev_c, s2b, c6, name, buy_px, idx_buy, fee):
    curr, boards_held, used_imm, pc = start_idx, init_boards, False, init_prev_c
    while curr < len(all_dts) and (curr - idx_buy <= 12):
        dc = all_dts[curr]
        b = price_lookup.get((c6, dc))
        if not b: break
        oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b
        if iyzc: pc = round(float(cc), 2); curr += 1; continue
        arr = bars_5m_map.get((c6, dc))
        if arr is not None and len(arr) >= 12:
            idx_1030, cum_v, cum_a = -1, 0.0, 0.0
            for bi in range(len(arr)):
                cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                if arr[bi, 0] == 1030: idx_1030 = bi; break
            if idx_1030 >= 0:
                bc_1030 = arr[idx_1030, 4]
                vwap = cum_a / cum_v if cum_v > 0 else bc_1030
                if bc_1030 >= ztc - 0.01:
                    for bi in range(idx_1030 + 1, len(arr) - 1):
                        if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                            px = round(float(arr[bi + 1, 1]), 2)
                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_buy": s2b, "buy_date": all_dts[idx_buy], "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
                    if iztc: pc = round(float(cc), 2); boards_held += 1; curr += 1; continue
                    px = round(float(cc), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_buy": s2b, "buy_date": all_dts[idx_buy], "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
                elif bc_1030 < vwap:
                    px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_buy": s2b, "buy_date": all_dts[idx_buy], "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
                else:
                    if iztc: pc = round(float(cc), 2); boards_held += 1; curr += 1; continue
                    if boards_held >= 3 and (not used_imm) and cc >= pc * 1.02 and (curr + 1 < len(all_dts)):
                        used_imm = True; pc = round(float(cc), 2); curr += 1; continue
                    px = round(float(cc), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_buy": s2b, "buy_date": all_dts[idx_buy], "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
        if iztc: pc = round(float(cc), 2); boards_held += 1; curr += 1; continue
        if boards_held >= 3 and (not used_imm) and cc >= pc * 1.02 and (curr + 1 < len(all_dts)):
            used_imm = True; pc = round(float(cc), 2); curr += 1; continue
        px = round(float(cc), 2)
        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_buy": s2b, "buy_date": all_dts[idx_buy], "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
    return None

# =========================================================================
# STEP 1: SCAN ALL CANDIDATES & COLLECT EXPERIMENT FEATURES
# =========================================================================
print("\n>>> 开始全样本扫描洗盘反包候选池 (2022-01-01 至 2026-11-05)...")
t_scan0 = time.time()
df5y = hist_fb[(hist_fb["d2_dt"] >= "2022-01-01") & (hist_fb["d2_dt"] <= "2026-11-05")].copy().reset_index(drop=True)

# Three pools flags
df5y["is_pool1_cut"] = [ (r.c6, r.d2_dt) in v15_cut_keys for r in df5y.itertuples() ]
df5y["is_pool2_prehigh"] = (static_purifier[df5y.index] & ((df5y["score_active"] >= 275.0) | tot_s8[df5y.index])).values
df5y["is_pool3_tight"] = (df5y["d1_seal_tightness"] >= 40.0).values

print(f"首板池规模: 5年总数={len(df5y)} | Pool1(止损)={df5y['is_pool1_cut'].sum()} | Pool2(静态高分)={df5y['is_pool2_prehigh'].sum()} | Pool3(硬首板)={df5y['is_pool3_tight'].sum()}")

rebound_events = []

for idx, row in df5y.iterrows():
    c6, nm, d1_c, d1_o, d1_dt, d2 = row["c6"], row["name"], float(row["close"]), float(row["open"]), row["dt_str"], row["d2_dt"]
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 < 0 or idx2 + 4 >= len(all_dts): continue

    # Check D2: must NOT seal 2B!
    b2 = price_lookup.get((c6, d2))
    if not b2 or b2[6]: continue # if sealed ZT on D2, not a washout
    o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = b2

    d1_amt = amt_lookup.get((c6, d1_dt), 0.0)
    d1_half = (d1_o + d1_c) / 2.0
    s_prior = float(row["s_prior_wk"])
    s_tot = float(row["score_active"])
    s_elo = float(row["s_elo"])
    pl = row["plate"]
    tightness = float(row["d1_seal_tightness"])
    is_p1 = row["is_pool1_cut"]
    is_p2 = row["is_pool2_prehigh"]
    is_p3 = row["is_pool3_tight"]

    # Test rest_days = 1 (D3), rest_days = 2 (D4, e.g. 东方海洋), rest_days = 3 (D5)
    for rest_days in [1, 2, 3]:
        idx_e = idx2 + rest_days
        d_e = all_dts[idx_e]
        be = price_lookup.get((c6, d_e))
        if not be: continue
        oe, he, le, ce, zte, dte, izte, iyze = be
        if oe <= 0 or oe >= zte - 0.005: continue # unbuyable yizi or suspended

        # Check washout days: none should seal limit up
        washout_bars = []
        is_clean_washout = True
        for k in range(idx2, idx_e):
            bk = price_lookup.get((c6, all_dts[k]))
            if not bk or bk[6]: # already hit ZT
                is_clean_washout = False
                break
            washout_bars.append((all_dts[k], bk))
        if not is_clean_washout: continue

        # Washout metrics
        min_c = min(b[3] for _, b in washout_bars)
        max_h = max(b[1] for _, b in washout_bars)
        last_dt, last_b = washout_bars[-1]
        last_c = last_b[3]
        last_o = last_b[0]
        last_h = last_b[1]
        last_l = last_b[2]
        prev_to_last_c = washout_bars[-2][1][3] if len(washout_bars) >= 2 else d1_c

        last_amt = amt_lookup.get((c6, last_dt), 0.0)
        first_amt = amt_lookup.get((c6, d2), 0.0)

        # 6 Micro hypotheses checks:
        # 1. Price support
        hold_above_d1c = (min_c >= d1_c * 0.995) # 强势空中加油
        hold_above_half = (min_c >= d1_half * 0.995) # 半分位守卫
        is_broken = (min_c < d1_half * 0.995) # 跌破实体半分位

        # 2. Volume signature
        vol_shrink_d1 = (d1_amt > 0 and last_amt > 0 and (last_amt / d1_amt <= 0.80)) # 较首板缩量20%+
        vol_shrink_d2 = (first_amt > 0 and last_amt > 0 and (last_amt / first_amt <= 0.80)) # 较D2缩量20%+
        vol_shrink = vol_shrink_d1 or (rest_days >= 2 and vol_shrink_d2)
        vol_heavy = (d1_amt > 0 and last_amt > 0 and (last_amt / d1_amt >= 1.0)) # 放量换手

        # 3. K-line pattern
        is_fake_yin = (last_c > prev_to_last_c) and (last_c < last_o) # 假阴真阳
        lower_shadow_ratio = (min(last_o, last_c) - last_l) / (last_h - last_l + 1e-4)
        is_pinbar = (lower_shadow_ratio >= 0.40) # 下影线承接
        is_absorb_k = is_fake_yin or is_pinbar

        # 4. Intraday 5m timing on rebound entry day
        arr = bars_5m_map.get((c6, d_e))
        touch_zt_time = 9999
        is_early_1000 = False
        is_early_1030_vwap = False
        is_late_1400 = False
        if arr is not None and len(arr) >= 1:
            cum_v = np.cumsum(arr[:, 5])
            cum_a = np.cumsum(arr[:, 6])
            vwap = cum_a / (cum_v + 1e-6)
            for bi in range(len(arr)):
                if arr[bi, 2] >= zte - 0.005:
                    touch_zt_time = arr[bi, 0]
                    if touch_zt_time <= 1000: is_early_1000 = True
                    if touch_zt_time <= 1030 and arr[bi, 4] >= vwap[bi] - 0.01: is_early_1030_vwap = True
                    if touch_zt_time >= 1400: is_late_1400 = True
                    break

        # 5. Open auction & Breakout trigger
        oe_pct = oe / last_c - 1.0
        trig_brk = round(max(max_h + 0.01, last_c * 1.065), 2)
        is_bid_weak_to_strong = (0.02 <= oe_pct <= 0.06) and (trig_brk < zte - 0.005) and (he >= trig_brk)

        # 6. Theme resonance
        prev_dt = all_dts[idx_e - 1]
        has_zt_peer = (pl and pl != "其他" and zt_dates_plate.get((pl, prev_dt), 0) >= 1)
        theme_resonance = has_zt_peer or (s_elo >= 105.0)

        # ==========================================
        # BUY METHOD 1: 盘中摸涨停打板 (100% 计入摸板炸板!)
        # ==========================================
        if (he >= zte - 0.005) and (0.0 <= oe_pct <= 0.075):
            tr_real = sim_rebound_trade(c6, nm, idx_e, zte)
            if tr_real:
                rebound_events.append({
                    "c6": c6, "name": nm, "entry_dt": d_e, "idx_e": idx_e, "rest": rest_days,
                    "mode": "打反包涨停板(含炸板)", "buy_px": zte, "is_zt_sealed": int(izte),
                    "is_p1": is_p1, "is_p2": is_p2, "is_p3": is_p3,
                    "hold_above_d1c": hold_above_d1c, "hold_above_half": hold_above_half, "is_broken": is_broken,
                    "vol_shrink": vol_shrink, "vol_heavy": vol_heavy,
                    "is_absorb_k": is_absorb_k, "is_early_1000": is_early_1000,
                    "is_early_1030_vwap": is_early_1030_vwap, "is_late_1400": is_late_1400,
                    "theme_resonance": theme_resonance, "s_prior": s_prior, "s_tot": s_tot,
                    "net_ret": tr_real["net_ret"], "exit_date": tr_real["exit_date"],
                    "exit_at_open": tr_real["exit_at_open"]
                })

        # ==========================================
        # BUY METHOD 1B: 幸存者偏差日线涨停假买 (仅用于揭穿 165 倍!)
        # ==========================================
        if izte and (0.0 <= oe_pct <= 0.075):
            tr_fake = sim_rebound_trade(c6, nm, idx_e, zte)
            if tr_fake:
                rebound_events.append({
                    "c6": c6, "name": nm, "entry_dt": d_e, "idx_e": idx_e, "rest": rest_days,
                    "mode": "假神仙日线涨停(幸存者偏差)", "buy_px": zte, "is_zt_sealed": 1,
                    "is_p1": is_p1, "is_p2": is_p2, "is_p3": is_p3,
                    "hold_above_d1c": hold_above_d1c, "hold_above_half": hold_above_half, "is_broken": is_broken,
                    "vol_shrink": vol_shrink, "vol_heavy": vol_heavy,
                    "is_absorb_k": is_absorb_k, "is_early_1000": is_early_1000,
                    "is_early_1030_vwap": is_early_1030_vwap, "is_late_1400": is_late_1400,
                    "theme_resonance": theme_resonance, "s_prior": s_prior, "s_tot": s_tot,
                    "net_ret": tr_fake["net_ret"], "exit_date": tr_fake["exit_date"],
                    "exit_at_open": tr_fake["exit_at_open"]
                })

        # ==========================================
        # BUY METHOD 2: 突破洗盘高点点火买入 (< zt_p)
        # ==========================================
        if is_bid_weak_to_strong:
            tr_brk = sim_rebound_trade(c6, nm, idx_e, trig_brk)
            if tr_brk:
                rebound_events.append({
                    "c6": c6, "name": nm, "entry_dt": d_e, "idx_e": idx_e, "rest": rest_days,
                    "mode": "竞价高开弱转强+突破洗盘高点点火", "buy_px": trig_brk, "is_zt_sealed": int(izte),
                    "is_p1": is_p1, "is_p2": is_p2, "is_p3": is_p3,
                    "hold_above_d1c": hold_above_d1c, "hold_above_half": hold_above_half, "is_broken": is_broken,
                    "vol_shrink": vol_shrink, "vol_heavy": vol_heavy,
                    "is_absorb_k": is_absorb_k, "is_early_1000": is_early_1000,
                    "is_early_1030_vwap": is_early_1030_vwap, "is_late_1400": is_late_1400,
                    "theme_resonance": theme_resonance, "s_prior": s_prior, "s_tot": s_tot,
                    "net_ret": tr_brk["net_ret"], "exit_date": tr_brk["exit_date"],
                    "exit_at_open": tr_brk["exit_at_open"]
                })

ev_df = pd.DataFrame(rebound_events)
print(f"扫描完成，耗时 {time.time()-t_scan0:.2f}s，总记录数: {len(ev_df)}")
print(ev_df["mode"].value_counts())


# =========================================================================
# STEP 2: FORENSIC VERIFICATION OF THE "165x REBOUND" MYTH
# =========================================================================
print("\n" + "="*80)
print(">>> 【课题 A 核心实验 1】「放量涨停买回 165 倍」法医级核验：真实打板 vs 幸存者偏差假打板")
print("="*80)

def calc_stats(sub_df, label=""):
    if len(sub_df) == 0:
        return f"{label:<45s} | 笔数=   0"
    n = len(sub_df)
    rets = sub_df["net_ret"].values
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = len(wins) / n * 100.0
    avg_ret = np.mean(rets) * 100.0
    w_avg = np.mean(wins) * 100.0 if len(wins) > 0 else 0.0
    l_avg = abs(np.mean(losses)) * 100.0 if len(losses) > 0 else 0.01
    payoff = (w_avg / l_avg) if l_avg > 0 else 99.0
    sealed_rate = sub_df["is_zt_sealed"].mean() * 100.0
    cum_nav = 1.0
    for r in rets: cum_nav *= (1.0 + r)
    return {
        "label": label, "n": n, "sealed_rate": sealed_rate, "wr": wr,
        "avg_ret": avg_ret, "payoff": payoff, "cum_nav": cum_nav
    }

# Compare in Pool 1 (the 45 V15 cut trades)
p1_real = ev_df[(ev_df["is_p1"]) & (ev_df["mode"] == "打反包涨停板(含炸板)")]
p1_fake = ev_df[(ev_df["is_p1"]) & (ev_df["mode"] == "假神仙日线涨停(幸存者偏差)")]

s_p1_real = calc_stats(p1_real, "Pool1(止损45笔) 真实盘中摸板(含炸板大面)")
s_p1_fake = calc_stats(p1_fake, "Pool1(止损45笔) 假神仙假装只在收盘涨停买(幸存者偏差)")

print(f"  {s_p1_fake['label']:<50s} | 笔数={s_p1_fake['n']:2d} | 封死率={s_p1_fake['sealed_rate']:5.1f}% | 胜率={s_p1_fake['wr']:5.1f}% | 均盈亏={s_p1_fake['avg_ret']:+6.2f}% | 盈亏比={s_p1_fake['payoff']:4.2f} | 独立复利={s_p1_fake['cum_nav']:6.2f}x")
print(f"  {s_p1_real['label']:<50s} | 笔数={s_p1_real['n']:2d} | 封死率={s_p1_real['sealed_rate']:5.1f}% | 胜率={s_p1_real['wr']:5.1f}% | 均盈亏={s_p1_real['avg_ret']:+6.2f}% | 盈亏比={s_p1_real['payoff']:4.2f} | 独立复利={s_p1_real['cum_nav']:6.2f}x")

# Compare in Pool 2 (V15 high score candidates)
p2_real = ev_df[(ev_df["is_p2"]) & (ev_df["mode"] == "打反包涨停板(含炸板)")]
p2_fake = ev_df[(ev_df["is_p2"]) & (ev_df["mode"] == "假神仙日线涨停(幸存者偏差)")]
s_p2_real = calc_stats(p2_real, "Pool2(静态高分756笔) 真实盘中摸板(含炸板大面)")
s_p2_fake = calc_stats(p2_fake, "Pool2(静态高分756笔) 假神仙假装只在收盘涨停买(幸存者偏差)")
print(f"  {s_p2_fake['label']:<50s} | 笔数={s_p2_fake['n']:2d} | 封死率={s_p2_fake['sealed_rate']:5.1f}% | 胜率={s_p2_fake['wr']:5.1f}% | 均盈亏={s_p2_fake['avg_ret']:+6.2f}% | 盈亏比={s_p2_fake['payoff']:4.2f} | 独立复利={s_p2_fake['cum_nav']:6.2f}x")
print(f"  {s_p2_real['label']:<50s} | 笔数={s_p2_real['n']:2d} | 封死率={s_p2_real['sealed_rate']:5.1f}% | 胜率={s_p2_real['wr']:5.1f}% | 均盈亏={s_p2_real['avg_ret']:+6.2f}% | 盈亏比={s_p2_real['payoff']:4.2f} | 独立复利={s_p2_real['cum_nav']:6.2f}x")

# Compare in Pool 3 (All tight first boards)
p3_real = ev_df[(ev_df["is_p3"]) & (ev_df["mode"] == "打反包涨停板(含炸板)")]
p3_fake = ev_df[(ev_df["is_p3"]) & (ev_df["mode"] == "假神仙日线涨停(幸存者偏差)")]
s_p3_real = calc_stats(p3_real, "Pool3(硬首板4万笔) 真实盘中摸板(含炸板大面)")
s_p3_fake = calc_stats(p3_fake, "Pool3(硬首板4万笔) 假神仙假装只在收盘涨停买(幸存者偏差)")
print(f"  {s_p3_fake['label']:<50s} | 笔数={s_p3_fake['n']:2d} | 封死率={s_p3_fake['sealed_rate']:5.1f}% | 胜率={s_p3_fake['wr']:5.1f}% | 均盈亏={s_p3_fake['avg_ret']:+6.2f}% | 盈亏比={s_p3_fake['payoff']:4.2f} | 独立复利={s_p3_fake['cum_nav']:6.2f}x")
print(f"  {s_p3_real['label']:<50s} | 笔数={s_p3_real['n']:2d} | 封死率={s_p3_real['sealed_rate']:5.1f}% | 胜率={s_p3_real['wr']:5.1f}% | 均盈亏={s_p3_real['avg_ret']:+6.2f}% | 盈亏比={s_p3_real['payoff']:4.2f} | 独立复利={s_p3_real['cum_nav']:6.2f}x")

# =========================================================================
# STEP 3: 6 MICRO-STRUCTURAL & CHIP PHYSICAL HYPOTHESES (IN POOL 2 & POOL 3)
# =========================================================================
print("\n" + "="*80)
print(">>> 【课题 A 核心实验 2】6 种微观盘口与筹码物理假设逐一检验 (真实零未来函数撮合)")
print("="*80)

# Filter real trades in Pool 2 (high scoring static pool)
df_real = ev_df[ev_df["mode"] == "打反包涨停板(含炸板)"].copy()

hypo_tests = [
    # 1. 价格承接
    ("1A. 强势空中加油: 最低收盘价 >= 首板收盘价 (min_c >= c_d1)", df_real["hold_above_d1c"]),
    ("1B. 半分位守卫: 不破首板实体半分位 (min_c >= half)", df_real["hold_above_half"] & (~df_real["hold_above_d1c"])),
    ("1C. 破位反抽: 跌破首板实体半分位 (min_c < half)", df_real["is_broken"]),
    # 2. 量能指纹
    ("2A. 洗盘日缩量 20%~40% (浮筹洗净)", df_real["vol_shrink"]),
    ("2B. 洗盘日放量换手 (vol >= 1.0)", df_real["vol_heavy"]),
    # 3. K线形态
    ("3A. 假阴真阳 / 长下影承接", df_real["is_absorb_k"]),
    ("3B. 普通常规阴阳K线", ~df_real["is_absorb_k"]),
    # 4. 分时盘口买点 (bars_5m_map)
    ("4A. 早盘 10:00 前主动封板", df_real["is_early_1000"]),
    ("4B. 10:30 前封板且站稳分时 VWAP 均价线", df_real["is_early_1030_vwap"]),
    ("4C. 尾盘 14:00 后偷袭摸板", df_real["is_late_1400"]),
    # 5. 竞价高开弱转强点火买点
    ("5A. 竞价高开弱转强 + 突破洗盘高点点火买法 (非打板)", ev_df["mode"] == "竞价高开弱转强+突破洗盘高点点火"),
    # 6. 主线题材共振
    ("6A. 主线题材共振 (所属板块前日有涨停活口或 s_elo>=105)", df_real["theme_resonance"]),
    ("6B. 独苗孤狼反抽 (无涨停活口且 s_elo<105)", ~df_real["theme_resonance"]),
    # 7. 东方海洋式精粹指纹组合
    ("7. 东方海洋式: 洗2天(D4) + 站稳首板收盘 + 洗盘缩量 + 题材共振", (df_real["rest"] == 2) & df_real["hold_above_d1c"] & df_real["vol_shrink"] & df_real["theme_resonance"]),
]

print("\n--- 全市场硬首板池 (Pool 3) 表现 ---")
for lbl, msk in hypo_tests:
    s = ev_df[msk & ev_df["is_p3"]] if "5A" in lbl else df_real[msk & df_real["is_p3"]]
    st = calc_stats(s, lbl)
    if isinstance(st, dict):
        print(f"  {st['label']:<60s} | N={st['n']:4d} | 封死率={st['sealed_rate']:5.1f}% | 胜率={st['wr']:5.1f}% | 均盈亏={st['avg_ret']:+6.2f}% | 盈亏比={st['payoff']:4.2f}")
    else:
        print(f"  {st}")

print("\n--- 盘前静态高分池 (Pool 2) 表现 ---")
for lbl, msk in hypo_tests:
    s = ev_df[msk & ev_df["is_p2"]] if "5A" in lbl else df_real[msk & df_real["is_p2"]]
    st = calc_stats(s, lbl)
    if isinstance(st, dict):
        print(f"  {st['label']:<60s} | N={st['n']:4d} | 封死率={st['sealed_rate']:5.1f}% | 胜率={st['wr']:5.1f}% | 均盈亏={st['avg_ret']:+6.2f}% | 盈亏比={st['payoff']:4.2f}")
    else:
        print(f"  {st}")


# =========================================================================
# STEP 4: PORTFOLIO LEVEL SLOT SIMULATION (RULE A vs RULE B) UNDER D15
# =========================================================================
print("\n" + "="*80)
print(">>> 【课题 A 核心实验 3】资金槽位规则回测 (规则 A 空仓闲置填补 vs 规则 B 同场竞技)")
print("="*80)

# Build rebound candidate lookup by date for the best micro candidates:
# Candidate Filter: Pool 2 (static purifier & score>=275) + 强势空中加油(above_d1) + 题材共振
# We test both:
# Mode A1: 打反包板 (真实盘中摸板, 含炸板)
# Mode A2: 突破洗盘高点点火 (非打板)
# Mode A3: 东方海洋式洗2天精粹
rebound_cands_hit = ev_df[(ev_df["is_p2"]) & (ev_df["mode"] == "打反包涨停板(含炸板)") & (ev_df["hold_above_d1c"]) & (ev_df["theme_resonance"])].copy()
rebound_cands_brk = ev_df[(ev_df["is_p2"]) & (ev_df["mode"] == "竞价高开弱转强+突破洗盘高点点火") & (ev_df["hold_above_d1c"]) & (ev_df["theme_resonance"])].copy()

# Base V15 candidates dataframe
sub_v15 = hist_fb[tot_s8 & (hist_fb["d2_dt"] >= "2022-01-01") & (hist_fb["d2_dt"] <= "2026-11-09")].copy()
sub_v15.sort_values(["d2_dt", "_sv_s8"], ascending=[True, False], inplace=True)
v15_cand_by_dt = {d: grp for d, grp in sub_v15.groupby("d2_dt")}

def run_slot_simulation(rebound_df, rule_name="规则A_空仓闲置填补", cand_type="打板"):
    rebound_by_dt = {d: grp.sort_values("s_tot", ascending=False) for d, grp in rebound_df.groupby("entry_dt")}

    # Track 1-Slot and 2-Slot
    free_dt_1s, free_open_1s = "", False
    nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0
    trades_1s = []

    slot_dt = ["", ""]
    slot_open = [False, False]
    slot_cap = [0.5, 0.5]
    peak_2s, mdd_2s = 1.0, 0.0
    trades_2s = []

    eq_daily_rets = []

    for d in all_dts:
        if d < "2022-01-01" or d > "2026-11-09": continue
        v15_grp = v15_cand_by_dt.get(d)
        reb_grp = rebound_by_dt.get(d)

        # ----------------------------------------------------
        # 1-SLOT SIMULATION
        # ----------------------------------------------------
        is_free_1s = (free_dt_1s == "" or d > free_dt_1s or (d == free_dt_1s and free_open_1s))
        if is_free_1s:
            tr_chosen = None
            if rule_name.startswith("规则A"):
                # V15 takes first priority! Only if NO V15 candidate traded, fill with rebound!
                if v15_grp is not None and len(v15_grp) > 0:
                    rows = [r._asdict() if hasattr(r, "_asdict") else r.to_dict() for _, r in v15_grp.iterrows()]
                    tr_chosen = sim_s8(rows[0])
                elif reb_grp is not None and len(reb_grp) > 0:
                    row_reb = reb_grp.iloc[0].to_dict()
                    tr_chosen = {
                        "net_ret": row_reb["net_ret"], "exit_date": row_reb["exit_date"],
                        "exit_at_open": row_reb["exit_at_open"], "buy_date": d,
                        "c6": row_reb["c6"], "name": row_reb["name"], "is_rebound": True
                    }
            else: # 规则B: 同场竞技混排 (按各自最高分比较)
                cands_today = []
                if v15_grp is not None and len(v15_grp) > 0:
                    rows = [r._asdict() if hasattr(r, "_asdict") else r.to_dict() for _, r in v15_grp.iterrows()]
                    tr_v = sim_s8(rows[0])
                    if tr_v:
                        cands_today.append((float(rows[0].get("score_active", 0)), tr_v, "v15"))
                if reb_grp is not None and len(reb_grp) > 0:
                    row_reb = reb_grp.iloc[0].to_dict()
                    tr_r = {
                        "net_ret": row_reb["net_ret"], "exit_date": row_reb["exit_date"],
                        "exit_at_open": row_reb["exit_at_open"], "buy_date": d,
                        "c6": row_reb["c6"], "name": row_reb["name"], "is_rebound": True
                    }
                    cands_today.append((float(row_reb.get("s_tot", 0)), tr_r, "rebound"))
                if cands_today:
                    cands_today.sort(key=lambda x: x[0], reverse=True)
                    tr_chosen = cands_today[0][1]

            if tr_chosen is not None:
                nav_1s *= (1.0 + tr_chosen["net_ret"])
                peak_1s = max(peak_1s, nav_1s)
                mdd_1s = max(mdd_1s, (peak_1s - nav_1s) / peak_1s)
                free_dt_1s, free_open_1s = tr_chosen["exit_date"], tr_chosen["exit_at_open"]
                trades_1s.append(tr_chosen)

        # ----------------------------------------------------
        # 2-SLOT SIMULATION
        # ----------------------------------------------------
        # Available candidates today
        today_cands = []
        if rule_name.startswith("规则A"):
            if v15_grp is not None:
                for _, r in v15_grp.head(2).iterrows():
                    tr = sim_s8(r._asdict() if hasattr(r, "_asdict") else r.to_dict())
                    if tr: today_cands.append((tr, "v15"))
            if reb_grp is not None:
                for _, r in reb_grp.head(2).iterrows():
                    tr = {
                        "net_ret": r["net_ret"], "exit_date": r["exit_date"],
                        "exit_at_open": r["exit_at_open"], "buy_date": d,
                        "c6": r["c6"], "name": r["name"], "is_rebound": True
                    }
                    today_cands.append((tr, "rebound"))
        else: # 规则B
            pool = []
            if v15_grp is not None:
                for _, r in v15_grp.iterrows():
                    tr = sim_s8(r._asdict() if hasattr(r, "_asdict") else r.to_dict())
                    if tr: pool.append((float(r.get("score_active", 0)), tr, "v15"))
            if reb_grp is not None:
                for _, r in reb_grp.iterrows():
                    tr = {
                        "net_ret": r["net_ret"], "exit_date": r["exit_date"],
                        "exit_at_open": r["exit_at_open"], "buy_date": d,
                        "c6": r["c6"], "name": r["name"], "is_rebound": True
                    }
                    pool.append((float(r.get("s_tot", 0)), tr, "rebound"))
            pool.sort(key=lambda x: x[0], reverse=True)
            today_cands = [(item[1], item[2]) for item in pool[:2]]

        for tr_c, c_type in today_cands:
            s_chosen = -1
            for si in range(2):
                if slot_dt[si] == "" or d > slot_dt[si] or (d == slot_dt[si] and slot_open[si]):
                    s_chosen = si
                    break
            if s_chosen != -1:
                slot_cap[s_chosen] *= (1.0 + tr_c["net_ret"])
                slot_dt[s_chosen], slot_open[s_chosen] = tr_c["exit_date"], tr_c["exit_at_open"]
                trades_2s.append(tr_c)
                c_nav2 = slot_cap[0] + slot_cap[1]
                peak_2s = max(peak_2s, c_nav2)
                mdd_2s = max(mdd_2s, (peak_2s - c_nav2) / peak_2s)

        # ----------------------------------------------------
        # DAILY EQUAL WEIGHT
        # ----------------------------------------------------
        d_rets = [tr_c["net_ret"] for tr_c, _ in today_cands]
        if d_rets:
            eq_daily_rets.append((d, float(np.mean(d_rets))))

    # Aggregate Eq NAV
    nav_eq, pk_eq, mdd_eq = 1.0, 1.0, 0.0
    for _, dr in eq_daily_rets:
        nav_eq *= (1.0 + dr)
        pk_eq = max(pk_eq, nav_eq)
        mdd_eq = max(mdd_eq, (pk_eq - nav_eq) / pk_eq)

    # 1S stats
    n_tot = len(trades_1s)
    w_tot = [t["net_ret"] for t in trades_1s if t["net_ret"] > 0]
    wr_5y = len(w_tot) / n_tot * 100.0 if n_tot > 0 else 0.0

    t_3y = [t for t in trades_1s if t["buy_date"] >= "2024-01-01"]
    wr_3y = (len([t for t in t_3y if t["net_ret"] > 0]) / len(t_3y) * 100.0) if t_3y else 0.0

    t_26 = [t for t in trades_1s if t["buy_date"] >= "2026-01-01"]
    wr_26 = (len([t for t in t_26 if t["net_ret"] > 0]) / len(t_26) * 100.0) if t_26 else 0.0

    nav_2s_tot = slot_cap[0] + slot_cap[1]
    reb_taken_1s = len([t for t in trades_1s if t.get("is_rebound", False)])
    excess = round((nav_1s - 1.0) - CSI300_5Y_CUM, 2)

    return {
        "rule": rule_name, "cand_type": cand_type, "trades_1s": n_tot, "reb_taken_1s": reb_taken_1s,
        "nav_1s": nav_1s, "mdd_1s": mdd_1s * 100.0, "nav_2s": nav_2s_tot, "mdd_2s": mdd_2s * 100.0,
        "nav_eq": nav_eq, "mdd_eq": mdd_eq * 100.0, "wr_5y": wr_5y, "wr_3y": wr_3y, "wr_26": wr_26,
        "excess_csi300": excess
    }

print("\n--- 组合轮动回测对比 ---")
res_v15_base = {
    "rule": "基线_原生V15无反包", "cand_type": "无", "trades_1s": res_base['trades_5y'], "reb_taken_1s": 0,
    "nav_1s": res_base['nav_1s'], "mdd_1s": res_base['mdd_1s'], "nav_2s": res_base['nav_2s'],
    "mdd_2s": res_base['mdd_2s'], "nav_eq": res_base['daily_eq'], "mdd_eq": res_base['mdd_daily_eq'],
    "wr_5y": res_base['wr_5y'], "wr_3y": res_base['wr_3y'], "wr_26": res_base['wr_2026'],
    "excess_csi300": res_base['excess_csi300']
}

sim_results = [res_v15_base]

for r_name in ["规则A_空仓闲置填补", "规则B_同场竞技混排"]:
    # Test with hit-board rebound
    res_hit = run_slot_simulation(rebound_cands_hit, rule_name=r_name, cand_type="打反包涨停(含炸板)")
    sim_results.append(res_hit)
    # Test with breakout ignition rebound
    res_brk = run_slot_simulation(rebound_cands_brk, rule_name=r_name, cand_type="竞价高开弱转强点火")
    sim_results.append(res_brk)

for sr in sim_results:
    print(f"{sr['rule']} ({sr['cand_type']}) | 总笔={sr['trades_1s']:3d} (反包占{sr['reb_taken_1s']:2d}) | 1S={sr['nav_1s']:6.2f}x (MDD={sr['mdd_1s']:4.1f}%) | 2S={sr['nav_2s']:5.2f}x (MDD={sr['mdd_2s']:4.1f}%) | Eq={sr['nav_eq']:5.2f}x | 5yWR={sr['wr_5y']:4.1f}% | 3yWR={sr['wr_3y']:4.1f}% | 26WR={sr['wr_26']:4.1f}% | 沪深净超额={sr['excess_csi300']:+6.2f}")


# =========================================================================
# STEP 5: TOPIC B - NAME TONALITY & DYNAMIC ELO RIGOROUS EXPERIMENTS
# =========================================================================
print("\n" + "="*80)
print(">>> 【课题 B 核心实验 1】硬科技主线无并购公告纯外行扣分/过滤 (参数平原扰动)")
print("="*80)

HARD_TECH_THEME_RE = re.compile(r"(机器人|芯片|半导体|光通信|光模块|CPO|算力|人工智能|AI|大模型|智能驾驶|工业母机|低空|商业航天|卫星|消费电子|PCB)")
CLASH_IN_TECH_RE = re.compile(r"(农|牧|渔|水产|海洋|纸|纺|服|装|家居|家纺|木|酒|食|乳|茶|味|百货|商业|地产|置业|城建|装修|建筑|水泥|钢铁|煤|矿|石化|水务|高速|路桥|港口|海运|仓储|燃气|热电|饮食|酒店|旅游)")

# Flag candidate rows with clash
is_hard_tech = hist_fb["plate"].astype(str).str.contains(HARD_TECH_THEME_RE)
is_clash_name = hist_fb["name"].astype(str).str.contains(CLASH_IN_TECH_RE)
has_hard_notice = hist_fb["notice_hard"].astype(bool)

is_tech_clash_no_ma = is_hard_tech & is_clash_name & (~has_hard_notice)

# Check which candidates in V15 baseline had this clash!
v15_clash_trades = [t for t in v15_trades_1s if is_tech_clash_no_ma[hist_fb[(hist_fb["c6"] == t["c6"]) & (hist_fb["d2_dt"] == t["buy_date"])].index[0]]]
print(f"全市场首板中硬科技外行无并购记录数: {is_tech_clash_no_ma.sum()}")
print(f"V15基线113笔中命中的外行票数: {len(v15_clash_trades)}")
for t in v15_clash_trades:
    print(f"  命中票: {t['buy_date']} {t['c6']} {t['name']} | 收益={t['net_ret']*100:+.2f}%")

# Test parameter plain: penalties: 0, -15, -20, -25, -30, and hard filter
print("\n--- 参数平原扰动测试 ---")
for pen in [0.0, -15.0, -20.0, -25.0, -30.0, "FILTER"]:
    if pen == "FILTER":
        m_curr = tot_s8 & (~is_tech_clash_no_ma)
        sv_curr = "_sv_s8"
        lbl = "完全硬过滤(直接剔除)"
    else:
        m_curr = tot_s8
        # Modify active score with penalty
        new_sv = hist_fb["_sv_s8"].copy()
        new_sv = new_sv + np.where(is_tech_clash_no_ma, pen, 0.0)
        hist_fb["_sv_pen_temp"] = new_sv
        sv_curr = "_sv_pen_temp"
        lbl = f"扣分 {pen:4.0f} 分"

    res_p = evaluate_strategy_master(hist_fb, sv_curr, m_curr, sim_s8, desc=lbl)
    print(f"  {lbl:<22s} | 总笔={res_p['trades_5y']:3d} | 1S={res_p['nav_1s']:6.2f}x (MDD={res_p['mdd_1s']:4.1f}%) | 2S={res_p['nav_2s']:5.2f}x (MDD={res_p['mdd_2s']:4.1f}%) | Eq={res_p['daily_eq']:5.2f}x | 5yWR={res_p['wr_5y']:4.1f}% | 3yWR={res_p['wr_3y']:4.1f}% | 26WR={res_p['wr_2026']:4.1f}% | 净超额={res_p['excess_csi300']:+6.2f}")

# =========================================================================
# STEP 6: DYNAMIC ELO WITH SAMPLE SIZE THRESHOLD & OVERHEATING / ICE-BREAKING
# =========================================================================
print("\n" + "="*80)
print(">>> 【课题 B 核心实验 2】细颗粒度词根/字头动态 Elo 与样本量门槛实测")
print("="*80)

# Build rolling 20-day character prefix tracker
CHAR_PREFIXES = ["中", "国", "华", "东方", "精机", "科技", "智能", "动力", "股份", "电子", "新材", "光电", "海", "金"]

# Precompute for each (c6, d2) date the prefix
def extract_prefix(nm):
    for p in ["东方", "精机", "科技", "智能", "动力", "新材", "光电"]:
        if p in nm: return p
    for p in ["中", "国", "华", "海", "金"]:
        if nm.startswith(p): return p
    return "其他"

hist_fb["char_pref"] = hist_fb["name"].apply(extract_prefix)

# For each trading day, compute the rolling 20-day statistics of each char_pref across all first boards:
# - count in past 20 trading days
# - win rate (ratio of reaching board >= 2)
# Apply threshold: count >= 3 to avoid single stock noise!
# If count >= 5 and recent 3-trade win rate < 30%: Overheating/Retraction penalty (-15, -20)
# If count <= 2 (ice cold) and today appears with tightness >= 45: Ice-breaker bonus (+10, +15)

unique_dts = sorted(hist_fb["d2_dt"].unique())
daily_pref_stats = {}

# Map of (date, pref) -> count_past_20d, win_rate_past_20d
dt_set_idx = {d: i for i, d in enumerate(all_dts)}
fb_by_d2 = hist_fb.groupby("d2_dt")

print("正在计算字头/词根滚动作息动态 Elo 指标...")
# Precompute daily occurrences of prefixes
pref_daily_counts = {}
pref_daily_2b_wins = {}
for d, grp in fb_by_d2:
    for pref, pgrp in grp.groupby("char_pref"):
        pref_daily_counts[(d, pref)] = len(pgrp)
        # count how many sealed 2B
        wins = 0
        for _, r in pgrp.iterrows():
            b2 = price_lookup.get((r["c6"], r["d2_dt"]))
            if b2 and b2[6]: wins += 1
        pref_daily_2b_wins[(d, pref)] = wins

# Build rolling 20-day Elo adjustments
pref_elo_bonuses = np.zeros(len(hist_fb))

for i, row in hist_fb.iterrows():
    pref = row["char_pref"]
    if pref == "其他": continue
    d2 = row["d2_dt"]
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 < 20: continue

    # Sum past 20 days (strictly prior to d2!)
    cnt_20d = 0
    wins_20d = 0
    for past_k in range(idx2 - 20, idx2):
        past_dt = all_dts[past_k]
        cnt_20d += pref_daily_counts.get((past_dt, pref), 0)
        wins_20d += pref_daily_2b_wins.get((past_dt, pref), 0)

    # Sample threshold check:
    # If sample size < 3: NO adjustment! (Zero noise)
    if cnt_20d < 3:
        # Check ice-breaking: was 0 or 1, but today has ultra-tight seal
        if cnt_20d <= 1 and row["d1_seal_tightness"] >= 45.0:
            pref_elo_bonuses[i] = 10.0 # 破冰加分
        continue

    win_rate = wins_20d / cnt_20d
    # If overheating / receding: count >= 5 and win_rate < 0.25 (连续炒作后胜率崩塌)
    if cnt_20d >= 5 and win_rate < 0.25:
        pref_elo_bonuses[i] = -15.0 # 过热退潮防补涨扣分
    elif cnt_20d >= 3 and win_rate >= 0.50:
        pref_elo_bonuses[i] = 10.0 # 持续强势主线字头加分

hist_fb["pref_elo_bonus"] = pref_elo_bonuses

print(f"动态字头 Elo 调整样本数: 获得加分={ (pref_elo_bonuses > 0).sum() } | 获得扣分={ (pref_elo_bonuses < 0).sum() }")

# Evaluate strategy with dynamic Elo
for elo_scale in [0.0, 0.5, 1.0, 1.5]:
    new_sv_elo = hist_fb["_sv_s8"] + hist_fb["pref_elo_bonus"] * elo_scale
    hist_fb["_sv_elo_temp"] = new_sv_elo
    lbl = f"字头动态Elo (强度={elo_scale:3.1f})"
    res_e = evaluate_strategy_master(hist_fb, "_sv_elo_temp", tot_s8, sim_s8, desc=lbl)
    print(f"  {lbl:<24s} | 总笔={res_e['trades_5y']:3d} | 1S={res_e['nav_1s']:6.2f}x (MDD={res_e['mdd_1s']:4.1f}%) | 2S={res_e['nav_2s']:5.2f}x (MDD={res_e['mdd_2s']:4.1f}%) | Eq={res_e['daily_eq']:5.2f}x | 5yWR={res_e['wr_5y']:4.1f}% | 3yWR={res_e['wr_3y']:4.1f}% | 26WR={res_e['wr_2026']:4.1f}% | 净超额={res_e['excess_csi300']:+6.2f}")

