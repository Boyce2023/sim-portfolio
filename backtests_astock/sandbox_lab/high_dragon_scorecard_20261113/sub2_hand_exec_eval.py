#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""sub2_hand_exec_eval.py - 全面评测可手操买卖点定式矩阵 (5m真实走势验证)"""

import pickle, re, os, numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
FEE = 0.0020

# 1. 载入基础设施与数据
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_DIR}/part1_cache.pkl", "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/dfr_deep_native.pkl")
cache_5m = pickle.load(open(f"{OUT_DIR}/sub2_5m_bars_cache.pkl", "rb"))

# 龙虎榜与1c映射 (与 verify_v2_vs_expanded_factors.py 100% 对齐)
df_1c = pd.read_parquet(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/verified_1c_rebound_cands.parquet")
df_1c["c6"] = df_1c["code"].astype(str).str.zfill(6)
c1_map = {(str(r.buy_date)[:10], r.c6): r for r in df_1c.itertuples()}

Q_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")
lb = pd.read_parquet(f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
lb["dt"], lb["c6"] = lb["TRADE_DATE"].astype(str).str[:10], lb["SECURITY_CODE"].astype(str).str[:6]
g_seat = lb[lb["dt"] >= "2021-10-01"].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["BUY"].min()
lhb_clean = {}
for (d, c), gl in g_seat.groupby(["dt", "c6"]):
    tb = float(gl["BUY"].sum()); ns = gl["OPERATEDEPT_NAME"].astype(str); lm = ns.str.contains("拉萨", na=False)
    lhb_clean[(d, c)] = (int(lm.sum()), float(gl.loc[lm, "BUY"].sum()) / tb if tb > 0 else 0.0, int(ns.str.contains(Q_RE, na=False).sum()), int(ns.str.contains("机构专用", na=False).sum()))

csi5_l, lh1_l, qu1_l, in1_l, obc_l, pelo_l, fmv_l = [], [], [], [], [], [], []
for r in dfr.itertuples():
    i1 = dt_to_idx[r.d1]
    csi5_l.append(CSI_MAP[r.d1] / CSI_MAP[all_dts[max(0, i1-5)]] - 1.0)
    a1 = lhb_clean.get((r.d1, r.code), (0,0.0,0,0))
    lh1_l.append(a1[0]); qu1_l.append(a1[2]); in1_l.append(a1[3])
    m = c1_map.get((r.buy_date, r.code))
    obc_l.append(int(getattr(m, "open_board_count", 0)) if m else 0)
    pelo_l.append(float(getattr(m, "p_elo", 120.0)) if m else 120.0)
    fmv_l.append(float(getattr(m, "float_mv", 50e8)) / 1e8 if m and pd.notna(getattr(m, "float_mv", np.nan)) else 50.0)

dfr["csi5"], dfr["lh1"], dfr["qu1"], dfr["in1"], dfr["obc"], dfr["pelo"], dfr["fmv_yi"] = csi5_l, lh1_l, qu1_l, in1_l, obc_l, pelo_l, fmv_l

# 2. 打分公式
def score_v2(r):
    if r["s_reg"] or r["tox"] or r["ex_reg5"] >= 2 or r["d1_to"] > 38.0 or r["lh1"] >= 3 or r["op2"] > 0.045 or r["op2"] < -0.065:
        return -999
    sc = 60
    if r["brk_r10"] >= 0.20: sc += 12
    else: sc -= 8
    if r["n_zt"] < 70: sc += 10
    elif r["n_zt"] >= 95: sc -= 10
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
    return sc

def score_v3_14f(r):
    sc = score_v2(r)
    if sc < 0: return -999
    if r["low_price_le20"]: sc += 5
    elif r["high_price_gt35"]: sc -= 10
    if r["turn_boards_ge4"]: sc += 5
    elif r["turn_boards_cnt"] <= 2: sc -= 5
    if r["d1_deep_dip_le6"]: sc += 5
    if r["lock"] >= 45.0: sc += 4
    elif r["lock"] < 25.0: sc -= 4
    if r["qu1"] >= 1 and r["lh1"] <= 1: sc += 4
    return sc

dfr["sc2"] = [score_v2(row) for _, row in dfr.iterrows()]
dfr["sc3"] = [score_v3_14f(row) for _, row in dfr.iterrows()]

# 3. 5m 辅助函数
def get_df_k(c6, buy_date):
    for k, v in cache_5m.items():
        if k[0] == c6 and k[2] == buy_date:
            return v
    return None

def get_1030_info(df_k, dt, pre_c):
    if df_k is None or df_k.empty:
        return None, None
    sub = df_k[(df_k["date"] == dt) & (df_k["hhmm"] <= "10:30")]
    if sub.empty:
        return None, None
    p_1030 = float(sub.iloc[-1]["close"])
    vol_sum = float(sub["volume"].sum())
    vwap_1030 = float(sub["amount"].sum()) / (vol_sum * 100) if vol_sum > 0 else p_1030
    return p_1030, vwap_1030

# 双红线严重异动极限价格计算 (10日100% 与 30日200%)
def get_double_dev_px(bars, cp, idx_map, disc=0.07):
    cd = bars["dts"][cp]
    ir = idx_map.get(cd)
    if not ir: return 99999.0
    pl_min = 99999.0
    # 10日100%
    for k in range(1, min(11, cp + 1)):
        p = cp - k; bi = idx_map.get(bars["dts"][p]); bc = bars["close"][p]
        if bi and bc > 0:
            pl = bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0))
            if pl < pl_min: pl_min = pl
    # 30日200%
    for k in range(1, min(31, cp + 1)):
        p = cp - k; bi = idx_map.get(bars["dts"][p]); bc = bars["close"][p]
        if bi and bc > 0:
            pl = bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0))
            if pl < pl_min: pl_min = pl
    return pl_min

# 4. 手操买点检验函数
# buy_mode:
#   'B1_band': 纯竞价直买，要求 op2 在 [low_b, high_b]
#   'B2_morn': 09:25 >=0% 竞价直买；<0% 挂条件单 (open*1.015)，仅限 09:30-11:30 上午触发，下午撤单
#   'B2_allday': 09:25 >=0% 竞价直买；<0% 挂条件单全天有效
def check_buy_exec(r, bars, df_k, buy_mode="B2_morn", low_b=-0.02, high_b=0.04):
    c6 = str(r.code).zfill(6)
    d2p = bars["p"][r.buy_date]
    b_op = float(bars["open"][d2p])
    zt_px = float(bars["zt_px"][d2p])
    
    # 涨跌停保护：如果开盘一字涨停无法买入
    if bars["is_yizi"][d2p]:
        return False, 0.0, "一字涨停无法买入"
        
    if buy_mode.startswith("B1"):
        # 纯竞价直买
        if low_b <= r.op2 <= high_b:
            return True, b_op, "竞价直买"
        else:
            return False, 0.0, "开盘不在黄金区间"
            
    elif buy_mode in ("B2_morn", "B2_allday"):
        if r.op2 >= 0.0:
            if r.op2 <= high_b:
                return True, b_op, "红开竞价直买"
            else:
                return False, 0.0, "高开超幅放弃"
        else:
            # 绿开挂条件单
            ipx = b_op * 1.015
            if ipx >= zt_px - 0.011:
                return False, 0.0, "点火价触及涨停放弃"
            if df_k is None or df_k.empty:
                # 回退日线 high 检验
                if float(bars["high"][d2p]) >= ipx:
                    return True, ipx, "日线触发点火"
                return False, 0.0, "未触发点火"
                
            df_d2 = df_k[df_k["date"] == r.buy_date]
            if df_d2.empty:
                if float(bars["high"][d2p]) >= ipx:
                    return True, ipx, "日线触发点火"
                return False, 0.0, "未触发点火"
                
            if buy_mode == "B2_morn":
                # 严格限制上午 09:30-11:30
                df_morn = df_d2[df_d2["hhmm"] <= "11:30"]
                if not df_morn.empty and df_morn["high"].max() >= ipx:
                    # 确定成交价格：如果是 09:35 第一根 bar open 就跳空过线，以 09:35 open 成交，否则以 ipx 限价成交
                    exec_px = ipx
                    if df_morn.iloc[0]["open"] >= ipx:
                        exec_px = df_morn.iloc[0]["open"]
                    return True, exec_px, "上午条件单触发"
                else:
                    return False, 0.0, "上午未触发中午撤单"
            else:
                if df_d2["high"].max() >= ipx:
                    exec_px = ipx
                    if df_d2.iloc[0]["open"] >= ipx:
                        exec_px = df_d2.iloc[0]["open"]
                    return True, exec_px, "全天条件单触发"
                else:
                    return False, 0.0, "全天未触发"
    return False, 0.0, "未知买点模式"

# 5. 手操卖点仿真函数
# sell_mode_A (针对 D2 未封涨停):
#   'A0_baseline': 旧规则拿到 D3 收盘 (smart_bounce +1.5%)
#   'A1_auction_or_tp': 若 D2 浮亏或 D3 绿开 -> D3 09:25 竞价一键走；若 D2 浮盈且 D3 红开 -> 盘前挂 +3% 限价止盈，10:30 未到市价全卖
#   'A2_1030_vwap': D3 09:25 < -2% 竞价走；其余 10:30 闹钟看一眼：破均线/翻绿市价走，站稳均线拿至尾盘 (若封板转Case B)
#   'A3_pure_auction': D3 09:25 集合竞价一键全卖 (零盯盘)
#
# sell_mode_B (针对 D2 封涨停连板):
#   'B_yidong_1030': 每天盘前挂双红线止盈单 (93%/95%)；未触及异动且断板时，10:30 破均线市价卖，站稳均线尾盘卖
#   'B_yidong_close': 每天盘前挂双红线止盈单；断板日按收盘价卖 (旧版)
def sim_hand_exit(bars, d2p, buy_px, idx_map, df_k, sell_mode_A="A1_auction_or_tp", sell_mode_B="B_yidong_1030", disc=0.07, yang_immune=False):
    d2_zt = bool(bars["is_zt"][d2p])
    d2_close = float(bars["close"][d2p])
    d2_c_ret = d2_close / buy_px - 1.0
    n = len(bars["dts"])
    
    ep, epx, eo = None, None, False
    
    if d2_zt:
        # ===== 情形 B: 买入日 D2 成功封板 (利润奔跑，卡异动线) =====
        imm = False
        for step in range(1, 8):
            p = d2p + step
            if p >= n: break
            
            # 双红线极限价格
            pl_dev = get_double_dev_px(bars, p, idx_map, disc=disc)
            
            # 1. 开盘越过异动线 -> 09:25 竞价一键止盈
            if bars["open"][p] >= pl_dev:
                ep, epx, eo = p, bars["open"][p], True
                break
            # 2. 盘中触及异动线 -> 限价单自动成交
            elif bars["high"][p] >= pl_dev:
                ep, epx, eo = p, pl_dev, False
                break
                
            # 3. 检查断板
            if not bars["is_zt"][p]:
                # 免死检验
                if yang_immune and (not imm) and (bars["close"][p] > bars["open"][p]):
                    imm = True
                    continue
                # 一字跌停顺延
                while p < n - 1 and bars["is_yizi_dt"][p]:
                    p += 1
                    
                if sell_mode_B == "B_yidong_1030":
                    # 10:30 看一眼
                    p_1030, vwap_1030 = get_1030_info(df_k, bars["dts"][p], bars["pre_c"][p])
                    if p_1030 is not None and vwap_1030 is not None:
                        if p_1030 < vwap_1030 or p_1030 < bars["pre_c"][p]:
                            # 跌破均线或翻绿，10:30 市价卖出
                            ep, epx, eo = p, p_1030, False
                            break
                        else:
                            # 均线上方拿至收盘
                            ep, epx, eo = p, bars["close"][p], False
                            break
                    else:
                        ep, epx, eo = p, bars["close"][p], False
                        break
                else:
                    ep, epx, eo = p, bars["close"][p], False
                    break
    else:
        # ===== 情形 A: 买入日 D2 未封涨停 (亏钱重灾区，手操减亏) =====
        p = min(d2p + 1, n - 1)
        d3_dt = bars["dts"][p]
        d3_open = float(bars["open"][p])
        d3_high = float(bars["high"][p])
        d3_close = float(bars["close"][p])
        d3_pre_c = float(bars["pre_c"][p])
        d3_op_pct = d3_open / d3_pre_c - 1.0
        
        # 处理可能的一字跌停
        while p < n - 1 and bars["is_yizi_dt"][p]:
            p += 1
            d3_open = float(bars["open"][p])
            d3_close = float(bars["close"][p])
            
        if sell_mode_A == "A0_baseline":
            # 旧版 smart_bounce
            if d2_c_ret <= -0.04 and (not bars["is_yizi_dt"][p]):
                bt = d3_pre_c * 1.015
                if d3_open >= bt: ep, epx, eo = p, d3_open, True
                elif d3_high >= bt: ep, epx, eo = p, bt, False
            if ep is None:
                ep, epx, eo = p, d3_close, False
                
        elif sell_mode_A == "A1_auction_or_tp":
            # 若 D2 浮亏 或 D3 绿开 -> 09:25 竞价一键走
            if d2_c_ret < 0.0 or d3_op_pct < 0.0:
                ep, epx, eo = p, d3_open, True
            else:
                # D2 浮盈且 D3 红开 -> 盘前挂 +3% 限价止盈单
                tp_px = d3_pre_c * 1.03
                p_1030, vwap_1030 = get_1030_info(df_k, d3_dt, d3_pre_c)
                if df_k is not None and not df_k.empty:
                    sub_m = df_k[(df_k["date"] == d3_dt) & (df_k["hhmm"] <= "10:30")]
                    if not sub_m.empty and sub_m["high"].max() >= tp_px:
                        ep, epx, eo = p, tp_px, False
                if ep is None:
                    # 10:30 未触及，看一眼市价卖出
                    ep, epx, eo = p, (p_1030 if p_1030 is not None else d3_close), False
                    
        elif sell_mode_A == "A2_1030_vwap":
            if d3_op_pct < -0.02:
                # 大幅低开核按钮，09:25 竞价走
                ep, epx, eo = p, d3_open, True
            else:
                # 10:30 闹钟看一眼
                p_1030, vwap_1030 = get_1030_info(df_k, d3_dt, d3_pre_c)
                if p_1030 is not None and vwap_1030 is not None:
                    if p_1030 < vwap_1030 or p_1030 < d3_pre_c:
                        ep, epx, eo = p, p_1030, False
                    else:
                        # 强势站稳均线拿至收盘；若收盘涨停则锁仓转情形 B
                        if bars["is_zt"][p]:
                            # 转连板锁仓
                            d2_zt = True
                            d2p = p
                            # 继续下一轮循环
                            return sim_hand_exit(bars, p, buy_px, idx_map, df_k, sell_mode_A, sell_mode_B, disc, yang_immune)
                        else:
                            ep, epx, eo = p, d3_close, False
                else:
                    ep, epx, eo = p, d3_close, False
                    
        elif sell_mode_A == "A3_pure_auction":
            # 极简纯竞价：次日 09:25 一键市价卖出
            ep, epx, eo = p, d3_open, True

    if ep is None:
        ep = min(d2p + 5, n - 1)
        epx, eo = bars["close"][ep], False
        
    ret = (epx * bars["adjf"][ep]) / (buy_px * bars["adjf"][d2p]) * (1.0 - FEE) - 1.0
    return bars["dts"][ep], float(ret), max(1, ep - d2p), eo

# 6. 单策略回测撮合与绩效统计
def simulate_portfolio(df_cands, score_col, score_th, buy_mode, sell_A, sell_B, disc=0.07, yang_imm=False, low_b=-0.02, high_b=0.04, use_cb=False):
    # 筛选
    sub = df_cands[df_cands[score_col] >= score_th].copy()
    trades = []
    
    for r in sub.itertuples():
        c6 = str(r.code).zfill(6)
        bars = code_bars[c6]
        df_k = get_df_k(c6, r.buy_date)
        imap = SH_MAP if r.ex == "SH" else SZ_MAP
        
        can_buy, buy_px, buy_reason = check_buy_exec(r, bars, df_k, buy_mode, low_b, high_b)
        if not can_buy:
            continue
            
        d2p = bars["p"][r.buy_date]
        ed, net_ret, hold_days, eo = sim_hand_exit(bars, d2p, buy_px, imap, df_k, sell_A, sell_B, disc, yang_imm)
        
        trades.append({
            "buy_date": r.buy_date,
            "exit_date": ed,
            "code": r.code,
            "name": r.name,
            "sc": getattr(r, score_col),
            "net_ret": net_ret,
            "b_open_h": (r.op2 >= 0.0),
            "eo": eo,
            "buy_px": buy_px,
            "hold_days": hold_days
        })
        
    if not trades:
        return pd.DataFrame()
        
    tdf = pd.DataFrame(trades).sort_values(["buy_date", "sc"], ascending=[True, False])
    
    # 真实单仓轮动排他
    taken = []
    fd = ""
    peo = False
    consec_loss = 0
    skip_next = False
    
    for r in tdf.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not r.b_open_h)):
            if use_cb and skip_next:
                fd = r.exit_date; peo = r.eo
                if r.net_ret > 0:
                    skip_next = False; consec_loss = 0
                continue
            taken.append(r)
            fd = r.exit_date; peo = r.eo
            if r.net_ret < -0.02:
                consec_loss += 1
                if consec_loss >= 2: skip_next = True
            elif r.net_ret > 0:
                consec_loss = 0
                
    return pd.DataFrame(taken)

def calc_metrics(led, s_dt="2022-01-04", e_dt="2026-11-12"):
    if led.empty:
        return {"n": 0, "wr": 0.0, "plr": 0.0, "nav": 1.0, "t5": 1.0, "mdd": 0.0, "eq_nav": 1.0}
    w = led[(led["buy_date"] >= s_dt) & (led["buy_date"] <= e_dt)]
    if w.empty:
        return {"n": 0, "wr": 0.0, "plr": 0.0, "nav": 1.0, "t5": 1.0, "mdd": 0.0, "eq_nav": 1.0}
    rets = w["net_ret"].values
    n = len(rets)
    wr = float(np.mean(rets > 0) * 100)
    pos, neg = rets[rets > 0], np.abs(rets[rets <= 0])
    plr = float(np.mean(pos) / np.mean(neg)) if (len(pos) > 0 and len(neg) > 0) else 99.0
    
    # 单仓复利净值与 MDD
    cur, pk, mdd = 1.0, 1.0, 0.0
    for x in rets:
        cur *= (1.0 + x)
        pk = max(pk, cur)
        mdd = max(mdd, (pk - cur) / pk)
    nav = cur
    
    # 去 Top5 净值
    sr = np.sort(rets)
    t5 = float(np.prod(1.0 + (sr[:-5] if len(sr) > 5 else np.array([0.0]))))
    
    # 按日等权净值 (按 buy_date 分组等权)
    g = w.groupby("buy_date")["net_ret"].mean()
    eq_nav = float(np.prod(1.0 + g.values))
    
    return {
        "n": n,
        "wr": wr,
        "plr": plr,
        "nav": nav,
        "t5": t5,
        "mdd": mdd * 100,
        "eq_nav": eq_nav
    }
