#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
test_relaxation_breakdown.py
================================================================================
深度解剖五大松绑候选池在黄金期内的真实胜率、赔率与边际贡献
================================================================================
"""

import os, sys, json, pickle, numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113"
FEE = 0.0020

part1_path = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/part1_cache.pkl"
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, plate_zt, stock_pls, lhb, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(part1_path, "rb"))

with open(f"{OUT_DIR}/v6_gold_regime_daily.json", "r") as fp:
    regime_dict = json.load(fp)

# 加载候选并合并 119 经典池
df_raw = pd.read_pickle(f"{OUT_DIR}/v6_gold_all_cands_raw.pkl")
dfr119 = pd.read_pickle(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/v5_enriched_119.pkl")

print(f"df_raw: {len(df_raw)} | dfr119: {len(dfr119)}")

# 重新计算与 V5.1 100% 对齐的基准打分与黄金期打分
def calc_unified_scores(r, is_gold):
    # 基础风控硬一票否决
    if r["s_reg"] or r["tox"]: return -999
    
    if not is_gold:
        # 平时严苛审美
        if r["ex_reg5"] >= 2 or r["d1_to"] > 38.0 or r["lh1"] >= 3 or r["op2"] > 0.045 or r["op2"] < -0.065:
            return -999
        sc = 60
        sc += 12 if r["brk_r10"] >= 0.20 else -8
        # n_zt
        n_zt = r.get("n_zt", 60)
        if n_zt < 70: sc += 10
        elif n_zt >= 95: sc -= 10
        if r["csi5"] >= -0.005: sc += 8
        elif r["csi5"] < -0.025: sc -= 10
        if r["d1_op"] < 0.0: sc += 8
        if r["op2"] < 0.0: sc += 8
        elif 0.0 <= r["op2"] <= 0.025: sc += 6
        if r["obc"] == 0 and r["d0_tight"] >= 35.0: sc += 6
        if r["pelo"] < 135.0 and (not r["dom"]): sc += 6
        if r["lh1"] == 0: sc += 6
        elif r["lh1"] == 2: sc -= 10
        if r["in1"] >= 1: sc -= 6
        if r["low_price_le20"]: sc += 5
        elif r["high_price_gt35"]: sc -= 10
        if r["turn_boards_ge4"]: sc += 5
        elif r["turn_boards_cnt"] <= 2: sc -= 5
        if r["d1_deep_dip_le6"]: sc += 5
        if r["lock"] >= 45.0: sc += 4
        elif r["lock"] < 25.0: sc -= 4
        if r["qu1"] >= 1 and r["lh1"] <= 1: sc += 4
        # KPL/LHB bonus if available
        if r.get("kpl_hist_1y_has_ge5", False): sc += 6
        elif r.get("kpl_hist_3y_has_ge5", False): sc += 3
        if r.get("lhb_d0_top_locked", False): sc += 5
        if r.get("lhb_d1_lhasa_heavy", False): sc -= 10
        return sc
    else:
        # 黄金期专属打分卡 (废除熊市审美)
        if r["d1_to"] > 42.0 or r["lh1"] >= 4 or r["op2"] > 0.078 or r["op2"] < -0.065:
            return -999
        sc = 65
        sc += 12 if r["brk_r10"] >= 0.20 else -5
        # 黄金期大主线龙头重奖！
        if r["dom"]: sc += 10
        else: sc += 4
        # 抢筹高开加分
        if 0.045 < r["op2"] <= 0.078: sc += 14 # 弱转强抢筹高开顶格加分！
        elif 0.0 <= r["op2"] <= 0.045: sc += 8
        elif -0.035 <= r["op2"] < 0.0: sc += 5
        # 换手放宽
        if r["d1_to"] <= 32.0: sc += 6
        elif 32.0 < r["d1_to"] <= 40.0: sc += 5
        # 盘口与筹码
        if r["obc"] == 0 and r["d0_tight"] >= 30.0: sc += 6
        if r["lh1"] == 0: sc += 6
        elif r["lh1"] <= 2: sc += 2
        if r["low_price_le20"]: sc += 5
        if r["turn_boards_ge4"]: sc += 6
        if r["qu1"] >= 1: sc += 4
        if r.get("kpl_hist_1y_has_ge5", False): sc += 6
        elif r.get("kpl_hist_3y_has_ge5", False): sc += 3
        if r.get("lhb_d0_top_locked", False): sc += 5
        return sc

# 运行单笔交易仿真
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

def run_trade(r, is_gold):
    c6 = str(r["code"]).zfill(6)
    bars = code_bars.get(c6)
    if not bars: return None
    d2_dt = r["buy_date"]
    if d2_dt not in bars["p"]: return None
    d2p = bars["p"][d2_dt]
    b_op = float(bars["open"][d2p])
    zt_px = float(bars["zt_px"][d2p])
    imap = SH_MAP if r["ex"] == "SH" else SZ_MAP
    
    # Buy execution:
    # morn_cond: if op2 >= 0, buy at auction; if op2 < 0, require high >= open * 1.015
    if r["op2"] >= 0.0:
        if b_op >= zt_px - 0.011: return None
        buy_px, is_auc = b_op, True
    else:
        ipx = round(b_op * 1.015, 2)
        if ipx >= zt_px - 0.011 or float(bars["high"][d2p]) < ipx: return None
        buy_px, is_auc = ipx, False
        
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
        
        # S_gold_upgrade
        can_hold_gold = is_gold and (d2_c >= b_op and d2_ret >= 0.0)
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

    ret = (epx * bars["adjf"][ep]) / (buy_px * bars["adjf"][d2p]) * (1.0 - FEE) - 1.0
    return {
        "buy_date": d2_dt, "exit_date": bars["dts"][ep], "code": c6, "name": r["name"],
        "is_gold": is_gold, "shape": r.get("shape", "TRUE_YANG"),
        "cand_type": r.get("cand_type", "BASE_TRUE_YANG"),
        "buy_px": buy_px, "exit_px": epx, "net_ret": float(ret),
        "hold_days": max(1, ep - d2p), "b_open_h": is_auc, "eo": eo
    }

# 组合回测
def run_portfolio_sim(cands_list, th_reg=88, th_gold=88, use_cb=True):
    valid = []
    for r in cands_list:
        is_gold = bool(regime_dict.get(r["buy_date"], False))
        sc = calc_unified_scores(r, is_gold)
        th = th_gold if is_gold else th_reg
        if sc < th: continue
        res = run_trade(r, is_gold)
        if res is not None:
            res["sc"] = sc
            valid.append(res)
            
    if not valid: return pd.DataFrame()
    tdf = pd.DataFrame(valid).sort_values(["buy_date", "sc"], ascending=[True, False])
    
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

def calc_metrics_table(led):
    if led.empty: return {}
    def s_slice(s, e):
        w = led[(led["buy_date"] >= s) & (led["buy_date"] <= e)]
        if w.empty: return {"n": 0, "wr": 0.0, "nav": 1.0, "mdd": 0.0, "pl": 0.0}
        r = w["net_ret"].values
        nav = float(np.prod(1.0 + r))
        pk, cur, mdd = 1.0, 1.0, 0.0
        for x in r: cur *= (1.0 + x); pk = max(pk, cur); mdd = max(mdd, (pk - cur) / pk)
        wr = float(np.mean(r > 0) * 100)
        pos, neg = r[r > 0], np.abs(r[r <= 0])
        plr = float(np.mean(pos) / np.mean(neg)) if (len(pos) > 0 and len(neg) > 0) else 99.0
        gold_cnt = sum(1 for x in w["is_gold"] if x)
        return {"n": len(w), "gold_n": gold_cnt, "reg_n": len(w) - gold_cnt, "wr": wr, "nav": nav, "mdd": mdd * 100, "pl": plr}
    return {
        "5Y": s_slice("2022-01-04", "2026-11-12"),
        "3Y": s_slice("2024-01-02", "2026-11-12"),
        "IS": s_slice("2022-01-04", "2023-12-29"),
        "25_26": s_slice("2025-01-02", "2026-11-12")
    }

# 组合不同松绑维度进行实测
# 1. 纯 119 基础池 (平时模式 vs 黄金期双态模式)
c_119 = dfr119.to_dict(orient="records")
led_119_reg = run_portfolio_sim(c_119, th_reg=88, th_gold=88, use_cb=True)
m_119_reg = calc_metrics_table(led_119_reg)

print("\n[Baseline 119 Records]")
print(f"  5Y: N={m_119_reg['5Y']['n']} (G:{m_119_reg['5Y']['gold_n']}/N:{m_119_reg['5Y']['reg_n']}), WR={m_119_reg['5Y']['wr']:.1f}%, NAV={m_119_reg['5Y']['nav']:.2f}x, MDD={m_119_reg['5Y']['mdd']:.1f}%")
print(f"  3Y: N={m_119_reg['3Y']['n']}, WR={m_119_reg['3Y']['wr']:.1f}%, NAV={m_119_reg['3Y']['nav']:.2f}x, MDD={m_119_reg['3Y']['mdd']:.1f}%")

# 2. 纯 119 池中，允许黄金期开盘放宽至 +7.8% 且启用黄金期卖点升级
# 检查 119 中 op2 > 0.045 的标的
for r in c_119:
    is_gold = bool(regime_dict.get(r["buy_date"], False))
    if is_gold and 0.045 < r["op2"] <= 0.078:
        pass # now permitted

# 3. 逐个松绑池测试 (单测)
c_raw = df_raw.to_dict(orient="records")
# 找出 raw 中不在 119 的纯增量候选
s119 = set((r["buy_date"], str(r["code"]).zfill(6)) for r in c_119)

increments = {
    "松绑①_水下真阳与抗跌阴线": [r for r in c_raw if (r["buy_date"], str(r["code"]).zfill(6)) not in s119 and r["shape"] in ("KANGDIE_YIN", "FAKE_YIN_ZHEN_YANG")],
    "松绑③_D2企稳反包": [r for r in c_raw if (r["buy_date"], str(r["code"]).zfill(6)) not in s119 and r["shape"] == "D2_WASH_STABILIZE"],
    "松绑④_二波新高首阴": [r for r in c_raw if r.get("cand_type") == "WAVE2_NEW_HIGH_BREAK"],
}

print("\n--- 增量松绑池单笔质量解剖 (仅限 G(T)==True 黄金期内) ---")
for name, c_list in increments.items():
    gold_cands = [r for r in c_list if regime_dict.get(r["buy_date"], False)]
    sim_rets = []
    for r in gold_cands:
        sc = calc_unified_scores(r, True)
        if sc >= 86:
            res = run_trade(r, True)
            if res is not None: sim_rets.append(res["net_ret"])
    if sim_rets:
        wr = (np.array(sim_rets) > 0).mean() * 100
        mean_r = np.mean(sim_rets) * 100
        print(f"  {name:25s}: 候选={len(gold_cands):2d}, 过线86分={len(sim_rets):2d}, 胜率={wr:5.1f}%, 平均收益={mean_r:+5.2f}%")
    else:
        print(f"  {name:25s}: 候选={len(gold_cands):2d}, 过线86分= 0")

