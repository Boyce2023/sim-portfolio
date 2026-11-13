#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""sub2_test_refined_exit.py - 检验精细手操卖点 A_refined 与 B_refined"""

import pickle, re, os, numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
FEE = 0.0020

(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_DIR}/part1_cache.pkl", "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/dfr_deep_native.pkl")
cache_5m = pickle.load(open(f"{OUT_DIR}/sub2_5m_bars_cache.pkl", "rb"))

# 载入打分
from sub2_hand_exec_eval import score_v2, score_v3_14f, get_double_dev_px, get_1030_info, get_df_k, calc_metrics
dfr["sc2"] = [score_v2(row) for _, row in dfr.iterrows()]
dfr["sc3"] = [score_v3_14f(row) for _, row in dfr.iterrows()]

def sim_refined_exit(bars, d2p, buy_px, idx_map, df_k, disc=0.07, yang_immune=False, a_rule="refined"):
    d2_zt = bool(bars["is_zt"][d2p])
    d2_close = float(bars["close"][d2p])
    d2_c_ret = d2_close / buy_px - 1.0
    n = len(bars["dts"])
    
    ep, epx, eo = None, None, False
    
    if d2_zt:
        # ===== 情形 B: 买入日 D2 成功封板 (利润奔跑，卡双红线异动) =====
        imm = False
        for step in range(1, 8):
            p = d2p + step
            if p >= n: break
            
            # 双红线极限价格 (10日100% 与 30日200%)
            pl_dev = get_double_dev_px(bars, p, idx_map, disc=disc)
            
            # 1. 竞价越线
            if bars["open"][p] >= pl_dev:
                ep, epx, eo = p, bars["open"][p], True
                break
            # 2. 盘中触线
            elif bars["high"][p] >= pl_dev:
                ep, epx, eo = p, pl_dev, False
                break
                
            # 3. 断板检查
            if not bars["is_zt"][p]:
                if yang_immune and (not imm) and (bars["close"][p] > bars["open"][p]):
                    imm = True
                    continue
                while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
                
                # 断板日 10:30 看一眼
                p_1030, vwap_1030 = get_1030_info(df_k, bars["dts"][p], bars["pre_c"][p])
                if p_1030 is not None and vwap_1030 is not None:
                    if p_1030 < vwap_1030 or p_1030 < bars["pre_c"][p]:
                        ep, epx, eo = p, p_1030, False
                        break
                    else:
                        ep, epx, eo = p, bars["close"][p], False
                        break
                else:
                    ep, epx, eo = p, bars["close"][p], False
                    break
    else:
        # ===== 情形 A: 买入日 D2 未封涨停 =====
        p = min(d2p + 1, n - 1)
        d3_dt = bars["dts"][p]
        d3_open = float(bars["open"][p])
        d3_high = float(bars["high"][p])
        d3_close = float(bars["close"][p])
        d3_pre_c = float(bars["pre_c"][p])
        d3_op_pct = d3_open / d3_pre_c - 1.0
        
        while p < n - 1 and bars["is_yizi_dt"][p]:
            p += 1
            d3_open = float(bars["open"][p])
            d3_close = float(bars["close"][p])
            
        if a_rule == "refined_1":
            # 规则 R1:
            # 1. 如果 D2 浮亏 (收盘 < 买入价): D3 09:25 竞价一键割出，绝不拖延！
            # 2. 如果 D2 浮盈 (收盘 >= 买入价):
            #    - 若 D3 绿开 (< 0%): 09:25 竞价市价卖出落袋为安 (保住浮盈)
            #    - 若 D3 红开 (>= 0%): 拿至 14:55 收盘；若收盘封板转连板锁仓，未封板卖出
            if d2_c_ret < 0.0:
                ep, epx, eo = p, d3_open, True
            else:
                if d3_op_pct < 0.0:
                    ep, epx, eo = p, d3_open, True
                else:
                    if bars["is_zt"][p]:
                        # 转连板锁仓
                        return sim_refined_exit(bars, p, buy_px, idx_map, df_k, disc, yang_immune, a_rule)
                    else:
                        ep, epx, eo = p, d3_close, False
                        
        elif a_rule == "refined_2":
            # 规则 R2:
            # 1. 如果 D2 浮亏: D3 09:25 竞价走
            # 2. 如果 D2 浮盈:
            #    - 设 10:30 闹钟：若 10:30 跌破均线或翻绿，市价卖出；若站稳均线拿至尾盘 (封板锁仓，未封卖出)
            if d2_c_ret < 0.0:
                ep, epx, eo = p, d3_open, True
            else:
                p_1030, vwap_1030 = get_1030_info(df_k, d3_dt, d3_pre_c)
                if p_1030 is not None and vwap_1030 is not None:
                    if p_1030 < vwap_1030 or p_1030 < d3_pre_c:
                        ep, epx, eo = p, p_1030, False
                    else:
                        if bars["is_zt"][p]:
                            return sim_refined_exit(bars, p, buy_px, idx_map, df_k, disc, yang_immune, a_rule)
                        else:
                            ep, epx, eo = p, d3_close, False
                else:
                    ep, epx, eo = p, d3_close, False

        elif a_rule == "refined_3":
            # 规则 R3: D3 盘中冲高保本止盈法
            # 1. 若 D2 浮亏且 D3 绿开: 09:25 竞价直接割
            # 2. 其余情况盘前挂保本价 (+1.0%) 限价单；10:30 未成交市价走
            if d2_c_ret < 0.0 and d3_op_pct < 0.0:
                ep, epx, eo = p, d3_open, True
            else:
                tp_px = buy_px * 1.010
                p_1030, _ = get_1030_info(df_k, d3_dt, d3_pre_c)
                if df_k is not None and not df_k.empty:
                    sub_m = df_k[(df_k["date"] == d3_dt) & (df_k["hhmm"] <= "10:30")]
                    if not sub_m.empty and sub_m["high"].max() >= tp_px:
                        ep, epx, eo = p, tp_px, False
                if ep is None:
                    ep, epx, eo = p, (p_1030 if p_1030 is not None else d3_close), False

    if ep is None:
        ep = min(d2p + 5, n - 1)
        epx, eo = bars["close"][ep], False
        
    ret = (epx * bars["adjf"][ep]) / (buy_px * bars["adjf"][d2p]) * (1.0 - FEE) - 1.0
    return bars["dts"][ep], float(ret), max(1, ep - d2p), eo

# 运行评测
print("=== 评测 精细手操卖点 R1, R2, R3 ===")
for m_label, sc_col, sc_th in [("V2_9因子80分", "sc2", 80), ("V3_14因子88分", "sc3", 88)]:
    for b_label, b_mode, low_b, high_b in [
        ("B1_[0,+4.5%]", "B1_band", 0.00, 0.045),
        ("B1_[-1,+4%]", "B1_band", -0.01, 0.040),
        ("B2_上午条件单", "B2_morn", -0.065, 0.045)
    ]:
        for r_name in ["refined_1", "refined_2", "refined_3"]:
            for cb in [False, True]:
                sub = dfr[dfr[sc_col] >= sc_th].copy()
                trades = []
                for r in sub.itertuples():
                    c6 = str(r.code).zfill(6)
                    bars = code_bars[c6]
                    df_k = get_df_k(c6, r.buy_date)
                    imap = SH_MAP if r.ex == "SH" else SZ_MAP
                    
                    from sub2_hand_exec_eval import check_buy_exec
                    can_buy, buy_px, _ = check_buy_exec(r, bars, df_k, b_mode, low_b, high_b)
                    if not can_buy: continue
                    d2p = bars["p"][r.buy_date]
                    ed, net_ret, hold_days, eo = sim_refined_exit(bars, d2p, buy_px, imap, df_k, 0.07, False, r_name)
                    trades.append({
                        "buy_date": r.buy_date, "exit_date": ed, "code": r.code, "name": r.name,
                        "sc": getattr(r, sc_col), "net_ret": net_ret, "b_open_h": (r.op2 >= 0.0),
                        "eo": eo, "hold_days": hold_days
                    })
                if not trades: continue
                tdf = pd.DataFrame(trades).sort_values(["buy_date", "sc"], ascending=[True, False])
                taken = []
                fd = ""; peo = False; consec_loss = 0; skip_next = False
                for t in tdf.itertuples(index=False):
                    if fd == "" or t.buy_date > fd or (t.buy_date == fd and peo and (not t.b_open_h)):
                        if cb and skip_next:
                            fd = t.exit_date; peo = t.eo
                            if t.net_ret > 0: skip_next = False; consec_loss = 0
                            continue
                        taken.append(t)
                        fd = t.exit_date; peo = t.eo
                        if t.net_ret < -0.02:
                            consec_loss += 1
                            if consec_loss >= 2: skip_next = True
                        elif t.net_ret > 0:
                            consec_loss = 0
                led = pd.DataFrame(taken)
                m_5y = calc_metrics(led, "2022-01-04", "2026-11-12")
                m_22_24 = calc_metrics(led, "2022-01-04", "2024-12-31")
                m_25_26 = calc_metrics(led, "2025-01-02", "2026-11-12")
                m_3y = calc_metrics(led, "2024-01-02", "2026-11-12")
                print(f"[{m_label} | {b_label} | {r_name} | cb={cb}]")
                print(f"  5Y: {m_5y['n']}b WR={m_5y['wr']:4.1f}% PLR={m_5y['plr']:4.2f} 单仓={m_5y['nav']:5.2f}x 去Top5={m_5y['t5']:4.2f}x 等权={m_5y['eq_nav']:4.2f}x | 原始MDD={m_5y['mdd']:4.1f}%")
                print(f"  22-24: {m_22_24['n']}b 单仓={m_22_24['nav']:4.2f}x MDD={m_22_24['mdd']:4.1f}% || 25-26: {m_25_26['n']}b 单仓={m_25_26['nav']:4.2f}x MDD={m_25_26['mdd']:4.1f}%")
