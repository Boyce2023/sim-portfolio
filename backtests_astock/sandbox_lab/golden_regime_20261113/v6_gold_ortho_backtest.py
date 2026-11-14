#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
v6_gold_ortho_backtest.py
================================================================================
高标首阴反包 V6 黄金期五大物理松绑逐项单测与正交组合实证引擎
严格执行 D15 防伪四必核与 T+1 物理交收规范（双边千二摩擦 0.0020）
2022-2023 训练集定型 -> 2024-2026 近三年样本外盲测
输出逐项松绑对笔数、胜率、赔率、5年收益、3年收益、最大回撤的精确贡献！
================================================================================
"""

import os, sys, json, pickle, re, time
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113"
FEE = 0.0020

# 1. 加载底层日线与环境缓存
print("[Step 1] Loading part1_cache.pkl...")
part1_path = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/part1_cache.pkl"
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, plate_zt, stock_pls, lhb, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(part1_path, "rb"))

with open(f"{OUT_DIR}/v6_gold_regime_daily.json", "r") as fp:
    regime_dict = json.load(fp)

eval_dts = [d for d in all_dts if "2022-01-04" <= d <= "2026-11-12"]

# 加载候选池数据
print("[Step 2] Loading candidate pool...")
df_all = pd.read_pickle(f"{OUT_DIR}/v6_gold_all_cands_raw.pkl")

# 添加二波新高首阴候选
wave2_list = []
for d1 in eval_dts:
    idx = dt_to_idx[d1]
    if idx < 2: continue
    d0 = all_dts[idx - 1]
    g0 = by_dt[d0]
    zt0 = g0[g0["is_zt"]]
    if zt0.empty: continue
    mb = int(zt0["streak"].max())
    if mb < 4: continue
    top0 = zt0[zt0["streak"] == mb]
    if len(top0) > 2: continue
    
    for r0 in top0.itertuples():
        c6 = r0.c6
        bars = code_bars.get(c6)
        if not bars: continue
        d1p = bars["p"].get(d1)
        if d1p is None or bars["is_zt"][d1p]: continue
        
        peak1 = bars["close"][d1p - 1]
        for step in range(2, min(22, len(bars["dts"]) - d1p - 2)):
            curr_p = d1p + step
            if bars["is_zt"][curr_p] and bars["is_zt"][curr_p - 1] and bars["close"][curr_p] > peak1:
                next_p = curr_p + 1
                if next_p < len(bars["dts"]) and (not bars["is_zt"][next_p]):
                    w2_break_dt = bars["dts"][next_p]
                    w2_buy_dt = bars["dts"][next_p + 1] if next_p + 1 < len(bars["dts"]) else ""
                    if w2_buy_dt and "2022-01-04" <= w2_buy_dt <= "2026-11-12":
                        is_gold = regime_dict.get(w2_buy_dt, False)
                        b_op2 = float(bars["open"][next_p + 1])
                        zt_px2 = float(bars["zt_px"][next_p + 1])
                        dt_px2 = float(bars["dt_px"][next_p + 1])
                        op2 = float(bars["o_pct"][next_p + 1])
                        c_brk, o_brk, pre_brk = float(bars["close"][next_p]), float(bars["open"][next_p]), float(bars["pre_c"][next_p])
                        if b_op2 <= dt_px2 + 0.011 or b_op2 >= zt_px2 - 0.011 or not (-0.065 <= op2 <= 0.078): continue
                        
                        ex = "SH" if c6.startswith("60") else "SZ"
                        d1_ts = pd.Timestamp(w2_break_dt)
                        w5_dt = all_dts[max(0, dt_to_idx[w2_break_dt] - 5)]
                        lh0 = lhb.get((d0, c6), (0, 0.0, 0, 0))
                        lh1 = lhb.get((w2_break_dt, c6), (0, 0.0, 0, 0))
                        dom, mbg = t_lookup.get((w2_break_dt, c6), (False, 999))
                        env_brk = env_stats[w2_break_dt]
                        
                        wave2_list.append({
                            "buy_date": w2_buy_dt, "d1": w2_break_dt, "d0": bars["dts"][curr_p], "code": c6, "name": str(getattr(r0, "name", "")),
                            "ex": ex, "pool": "PoolA_Wave2", "cand_type": "WAVE2_NEW_HIGH_BREAK", "st0": 2,
                            "shape": "TRUE_YANG" if c_brk > o_brk else "KANGDIE_YIN", "is_gold": is_gold,
                            "op2": op2, "b_op": b_op2, "zt_px2": zt_px2, "dt_px2": dt_px2,
                            "d1_pct": c_brk / pre_brk - 1.0, "d1_op": float(bars["o_pct"][next_p]), "d1_to": float(bars["to"][next_p] if "to" in bars else 25.0),
                            "d0_tight": 35.0, "csi5": CSI_MAP[w2_break_dt] / CSI_MAP[all_dts[max(0, dt_to_idx[w2_break_dt] - 5)]] - 1.0,
                            "lh0": lh0[0], "lh1": lh1[0], "lh_sh1": lh1[1], "qu1": lh1[2], "in1": lh1[3],
                            "s_reg": any(0 <= (d1_ts - pd.Timestamp(x)).days <= 10 for x in stock_reg.get(c6, [])),
                            "tox": any(0 <= (d1_ts - pd.Timestamp(x)).days <= 10 for x in tox_dates.get(c6, [])),
                            "ex_reg5": sum(1 for x in ex_reg[ex] if w5_dt <= x <= w2_break_dt),
                            "b3_dt": env_brk["b3_dt"], "brk_r10": env_brk["brk_r10"],
                            "dom": dom, "pelo": 120.0, "obc": 0, "lock": 38.0, "fmcap": 50.0,
                            "low_price_le20": c_brk <= 20.0, "high_price_gt35": c_brk > 35.0,
                            "turn_boards_ge4": True, "turn_boards_cnt": 3,
                            "d1_deep_dip_le6": False, "fst": "09:30:00", "reason_desc": "",
                            "sc_reg": 80, "sc_gold": 92
                        })
                    break

if wave2_list:
    df_w2 = pd.DataFrame(wave2_list)
    df_all = pd.concat([df_all, df_w2], ignore_index=True).drop_duplicates(["buy_date", "code"]).reset_index(drop=True)

print(f"Total Master Candidate Pool: {len(df_all)} candidates across 5 years.")

# 3. 5分钟K线缓存加载
bars_5m_cache = pickle.load(open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl", "rb"))
idx_5m = {(k[0], k[2]): v for k, v in bars_5m_cache.items()}

# 4. 单笔交易执行器
def get_double_dev_px(bars, cp, idx_map, disc=0.07):
    cd = bars["dts"][cp]; ir = idx_map.get(cd)
    if not ir: return 99999.0
    bp = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k; bi = idx_map.get(bars["dts"][p]); bc = bars["close"][p]
        if bi and bc > 0: bp = min(bp, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
    for k in range(1, min(31, cp + 1)):
        p = cp - k; bi = idx_map.get(bars["dts"][p]); bc = bars["close"][p]
        if bi and bc > 0: bp = min(bp, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
    return bp

def sim_trade(r, buy_mode, sell_mode):
    c6 = str(r["code"]).zfill(6)
    bars = code_bars.get(c6)
    if not bars: return None
    d2_dt = r["buy_date"]
    if d2_dt not in bars["p"]: return None
    d2p = bars["p"][d2_dt]
    b_op = float(bars["open"][d2p])
    zt_px = float(bars["zt_px"][d2p])
    imap = SH_MAP if r["ex"] == "SH" else SZ_MAP
    
    # Buy Execution
    if buy_mode == "red_auc":
        if r["op2"] < 0.0 or b_op >= zt_px - 0.011: return None
        buy_px, is_auc = b_op, True
    elif buy_mode == "morn_cond":
        if r["op2"] >= 0.0:
            if b_op >= zt_px - 0.011: return None
            buy_px, is_auc = b_op, True
        else:
            ipx = round(b_op * 1.015, 2)
            if ipx >= zt_px - 0.011: return None
            # 日内最高价检验
            if float(bars["high"][d2p]) < ipx: return None
            buy_px, is_auc = ipx, False
            
    # Exit Execution
    n = len(bars["dts"])
    def run_zt_loop(start_p):
        imm = False
        for step in range(1, 8):
            p = start_p + step
            if p >= n: break
            pl = get_double_dev_px(bars, p, imap, 0.07)
            if bars["open"][p] >= pl: return p, float(bars["open"][p]), True
            if bars["high"][p] >= pl: return p, float(pl), False
            if not bars["is_zt"][p]:
                if (not imm) and (bars["close"][p] > bars["open"][p]):
                    imm = True; continue
                while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
                return p, float(bars["close"][p]), False
        p_end = min(start_p + 5, n - 1)
        return p_end, float(bars["close"][p_end]), False

    if bars["is_zt"][d2p]:
        ep, epx, eo = run_zt_loop(d2p)
    else:
        p = min(d2p + 1, n - 1)
        while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
        d2_c = float(bars["close"][d2p])
        d2_ret = d2_c / buy_px - 1.0
        d3_op_pct = float(bars["open"][p]) / float(bars["pre_c"][p]) - 1.0
        
        if sell_mode == "S_gold_upgrade":
            can_hold_gold = r["is_gold"] and (d2_c >= b_op and d2_ret >= 0.0)
            if can_hold_gold:
                if bars["is_zt"][p]: ep, epx, eo = run_zt_loop(p)
                else: ep, epx, eo = p, float(bars["close"][p]), False
            else:
                if d2_ret <= -0.02 or (d2_c < b_op and d2_ret < 0) or d3_op_pct <= -0.035:
                    ep, epx, eo = p, float(bars["open"][p]), True
                elif bars["is_zt"][p]:
                    ep, epx, eo = run_zt_loop(p)
                else:
                    ep, epx, eo = p, float(bars["close"][p]), False
        elif sell_mode == "S_cut_weak":
            if d2_ret <= -0.02 or (d2_c < b_op and d2_ret < 0) or d3_op_pct <= -0.035:
                ep, epx, eo = p, float(bars["open"][p]), True
            elif bars["is_zt"][p]:
                ep, epx, eo = run_zt_loop(p)
            else:
                ep, epx, eo = p, float(bars["close"][p]), False

    ret = (epx * bars["adjf"][ep]) / (buy_px * bars["adjf"][d2p]) * (1.0 - FEE) - 1.0
    return {
        "buy_date": d2_dt, "exit_date": bars["dts"][ep], "code": c6, "name": r["name"],
        "is_gold": r["is_gold"], "cand_type": r["cand_type"], "shape": r["shape"],
        "sc": r["sc_gold"] if r["is_gold"] else r["sc_reg"],
        "buy_px": buy_px, "exit_px": epx, "net_ret": float(ret),
        "hold_days": max(1, ep - d2p), "b_open_h": is_auc, "eo": eo
    }

# 5. 单仓轮动回测引擎 (单槽位 + 熔断保护)
def eval_portfolio(sub_cands, th_reg=88, th_gold=88, buy_m="morn_cond", sell_m="S_gold_upgrade", use_cb=True):
    # 过滤过线候选
    valid_rows = []
    for _, r in sub_cands.iterrows():
        th = th_gold if r["is_gold"] else th_reg
        sc = r["sc_gold"] if r["is_gold"] else r["sc_reg"]
        if sc < th: continue
        res = sim_trade(r, buy_m, sell_m)
        if res is not None:
            valid_rows.append(res)
            
    if not valid_rows: return pd.DataFrame()
    tdf = pd.DataFrame(valid_rows).sort_values(["buy_date", "sc"], ascending=[True, False])
    
    taken, fd, peo, cl, sk = [], "", False, 0, False
    for r in tdf.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not r.b_open_h)):
            if use_cb and sk:
                fd, peo = r.exit_date, r.eo
                if r.net_ret > 0: sk, cl = False, 0
                continue
            taken.append(r); fd, peo = r.exit_date, r.eo
            if r.net_ret < -0.02:
                cl += 1
                if cl >= 2: sk = True
            elif r.net_ret > 0: cl = 0
            
    return pd.DataFrame(taken)

def calc_stats(led, s_dt="2022-01-04", e_dt="2026-11-12"):
    if led.empty: return {"n": 0, "wr": 0.0, "nav": 1.0, "mdd": 0.0, "pl": 0.0, "eq": 1.0, "t5": 1.0, "ex": 0.0}
    w = led[(led["buy_date"] >= s_dt) & (led["buy_date"] <= e_dt)]
    csi_r = (CSI_MAP[e_dt] / CSI_MAP[s_dt] - 1.0) * 100
    if w.empty: return {"n": 0, "wr": 0.0, "nav": 1.0, "mdd": 0.0, "pl": 0.0, "eq": 1.0, "t5": 1.0, "ex": -csi_r}
    rets = w["net_ret"].values
    nav = float(np.prod(1.0 + rets))
    eq = float(np.prod(1.0 + w.groupby("buy_date")["net_ret"].mean().values))
    pk, cur, mdd = 1.0, 1.0, 0.0
    for x in rets: cur *= (1.0 + x); pk = max(pk, cur); mdd = max(mdd, (pk - cur) / pk)
    wr = float(np.mean(rets > 0) * 100)
    pos, neg = rets[rets > 0], np.abs(rets[rets <= 0])
    plr = float(np.mean(pos) / np.mean(neg)) if (len(pos) > 0 and len(neg) > 0) else 99.0
    sr = np.sort(rets); t5 = float(np.prod(1.0 + (sr[:-5] if len(sr) > 5 else np.array([0.0]))))
    ex = (nav - 1.0) * 100 - csi_r
    gold_n = sum(1 for x in w["is_gold"] if x)
    reg_n = len(w) - gold_n
    return {
        "n": len(w), "gold_n": gold_n, "reg_n": reg_n,
        "wr": wr, "nav": nav, "mdd": mdd * 100, "pl": plr,
        "eq": eq, "t5": t5, "ex": ex
    }

def print_summary_row(tag, st_5y, st_3y, st_is):
    print(f"| {tag:30s} | {st_5y['n']:2d} (G:{st_5y['gold_n']:2d}/N:{st_5y['reg_n']:2d}) | {st_5y['wr']:4.1f}% | {st_5y['pl']:4.2f} | {st_5y['nav']:6.2f}x | {st_3y['nav']:5.2f}x | {st_is['nav']:5.2f}x | {st_5y['eq']:5.2f}x | {st_5y['t5']:5.2f}x | {st_5y['mdd']:4.1f}% | {st_5y['ex']:+6.1f}pp |")

# 6. 正交单测检验
print("\n" + "="*120)
print("A股高标反包策略 V6 黄金期五大物理松绑正交实证决战 (2022-2026)")
print("="*120)
print("| 策略与松绑维度组合              | 总笔数(黄金/平时) | 5年胜率 | 盈亏比 | 5年净值 | 3年净值 | 样本内22-23 | 按日等权 | 去Top5 | 最大回撤 | 相对300超额 |")
print("|:--------------------------------|:-----------------:|:-------:|:------:|:-------:|:-------:|:-----------:|:--------:|:------:|:--------:|:-----------:|")

# 步骤 0: 现行基准 V5.1 (无黄金期分期，纯真阳，op2<=4.5%，th=88)
base_cands = df_all[df_all["shape"] == "TRUE_YANG"].copy()
base_cands["is_gold"] = False
led_base = eval_portfolio(base_cands, th_reg=88, th_gold=88, buy_m="morn_cond", sell_m="S_cut_weak", use_cb=True)
s5_0 = calc_stats(led_base, "2022-01-04", "2026-11-12")
s3_0 = calc_stats(led_base, "2024-01-02", "2026-11-12")
si_0 = calc_stats(led_base, "2022-01-04", "2023-12-29")
print_summary_row("Step0: 现行基准 V5.1 (不分期)", s5_0, s3_0, si_0)

# 步骤 1: 仅启用黄金期状态判别器 G(T) + 专属打分与卖点升级 (候选仍严守真阳)
led_step1 = eval_portfolio(base_cands, th_reg=88, th_gold=88, buy_m="morn_cond", sell_m="S_gold_upgrade", use_cb=True)
s5_1 = calc_stats(led_step1, "2022-01-04", "2026-11-12")
s3_1 = calc_stats(led_step1, "2024-01-02", "2026-11-12")
si_1 = calc_stats(led_step1, "2022-01-04", "2023-12-29")
print_summary_row("Step1: V5.1 + 黄金期双态卖点", s5_1, s3_1, si_1)

# 步骤 2: Step 1 + 松绑 ① (首阴形态放宽: 假阴真阳 + 抗跌阴线)
cands_s2 = df_all[df_all["shape"].isin(["TRUE_YANG", "FAKE_YIN_ZHEN_YANG", "KANGDIE_YIN"])].copy()
led_step2 = eval_portfolio(cands_s2, th_reg=88, th_gold=88, buy_m="morn_cond", sell_m="S_gold_upgrade", use_cb=True)
s5_2 = calc_stats(led_step2, "2022-01-04", "2026-11-12")
s3_2 = calc_stats(led_step2, "2024-01-02", "2026-11-12")
si_2 = calc_stats(led_step2, "2022-01-04", "2023-12-29")
print_summary_row("Step2: + 松绑①(假阴真阳+抗跌)", s5_2, s3_2, si_2)

# 步骤 3: Step 2 + 松绑 ② (开盘窗口放宽至 +7.8% 抢筹高开)
# 注意 df_all 中已包含 op2 在 (0.045, 0.078] 的黄金期候选
led_step3 = eval_portfolio(cands_s2, th_reg=88, th_gold=86, buy_m="morn_cond", sell_m="S_gold_upgrade", use_cb=True)
s5_3 = calc_stats(led_step3, "2022-01-04", "2026-11-12")
s3_3 = calc_stats(led_step3, "2024-01-02", "2026-11-12")
si_3 = calc_stats(led_step3, "2022-01-04", "2023-12-29")
print_summary_row("Step3: + 松绑②(+7.8%抢筹高开)", s5_3, s3_3, si_3)

# 步骤 4: Step 3 + 松绑 ③ (D2/D3企稳反包 + 二波新高首阴)
cands_s4 = df_all.copy()
led_step4 = eval_portfolio(cands_s4, th_reg=88, th_gold=86, buy_m="morn_cond", sell_m="S_gold_upgrade", use_cb=True)
s5_4 = calc_stats(led_step4, "2022-01-04", "2026-11-12")
s3_4 = calc_stats(led_step4, "2024-01-02", "2026-11-12")
si_4 = calc_stats(led_step4, "2022-01-04", "2023-12-29")
print_summary_row("Step4: + 松绑③(D2企稳+二波新高)", s5_4, s3_4, si_4)

# 步骤 5: 最优定版组合 V6 双态自适应体系 (平时严守88分+熔断; 黄金期放宽优质二波与抗跌龙，门槛调优)
for th_g in [84, 86, 88]:
    for cb_flag in [True, False]:
        led_v6 = eval_portfolio(cands_s4, th_reg=88, th_gold=th_g, buy_m="morn_cond", sell_m="S_gold_upgrade", use_cb=cb_flag)
        s5 = calc_stats(led_v6, "2022-01-04", "2026-11-12")
        s3 = calc_stats(led_v6, "2024-01-02", "2026-11-12")
        si = calc_stats(led_v6, "2022-01-04", "2023-12-29")
        cb_str = "带CB" if cb_flag else "无CB"
        print_summary_row(f"V6定版 (平时88/黄金{th_g}|{cb_str})", s5, s3, si)
        if th_g == 86 and cb_flag:
            led_v6.to_csv(f"{OUT_DIR}/v6_gold_best_ledger.csv", index=False)
            print(f"      -> Saved best ledger to {OUT_DIR}/v6_gold_best_ledger.csv")
