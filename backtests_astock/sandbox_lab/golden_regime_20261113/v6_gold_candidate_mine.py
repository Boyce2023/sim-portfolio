#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
v6_gold_candidate_mine.py
================================================================================
高标首阴反包 V6 黄金期候选池深度挖掘与全量特征装配引擎
全量 2022-01-04 至 2026-11-12 (1176 个交易日，含退市股，零未来函数)
从底层 1.3GB 日线底座全量提取，彻底打破 119 窄池限制！
逐项落地五大物理松绑候选池：
  1. 假阴真阳与抗跌洗盘阴线 (形态松绑)
  2. +4.5% 至 +7.8% 抢筹高开 (开盘窗口松绑)
  3. D2/D3洗盘企稳与二波新高首阴 (形态演进松绑)
  4. 3板最高换手龙与并列双龙 (高度与竞价松绑)
  5. 黄金期专属打分卡与持仓卖点升级
================================================================================
"""

import os, sys, json, pickle, re, time
from collections import defaultdict
import numpy as np
import pandas as pd
import baostock as bs

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113"
FEE = 0.0020

print("[1/5] Loading part1_cache.pkl and regime daily dictionary...")
t0 = time.time()
part1_path = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/part1_cache.pkl"
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, plate_zt, stock_pls, lhb, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(part1_path, "rb"))

with open(f"{OUT_DIR}/v6_gold_regime_daily.json", "r") as fp:
    regime_dict = json.load(fp)

eval_dts = [d for d in all_dts if "2022-01-04" <= d <= "2026-11-12"]
print(f"Loaded in {time.time()-t0:.2f}s, total eval days: {len(eval_dts)}")

# 龙虎榜去重清洗
print("[2/5] Indexing LHB and KPL features...")
Q_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")
lb = pd.read_parquet(f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
lb["dt"], lb["c6"] = lb["TRADE_DATE"].astype(str).str[:10], lb["SECURITY_CODE"].astype(str).str[:6]
g_seat = lb[lb["dt"] >= "2021-10-01"].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["BUY"].min()
lhb_clean = {}
for (d, c), gl in g_seat.groupby(["dt", "c6"]):
    tb = float(gl["BUY"].sum()); ns = gl["OPERATEDEPT_NAME"].astype(str); lm = ns.str.contains("拉萨", na=False)
    lhb_clean[(d, c)] = (int(lm.sum()), float(gl.loc[lm, "BUY"].sum()) / tb if tb > 0 else 0.0, int(ns.str.contains(Q_RE, na=False).sum()), int(ns.str.contains("机构专用", na=False).sum()))

# KPL 涨停微观盘口
db_path = f"{ROOT}/sim-portfolio/data/zt_micro_tape_5y_pit.db"
import sqlite3
con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
cur = con.cursor()
cur.execute("SELECT trade_date, sec_code, first_seal_time, open_board_count, plate_name, reason_desc FROM zt_micro_tape")
tape_map = {}
for td, sc, fst, obc, pn, rd in cur.fetchall():
    tape_map[(str(td)[:10], str(sc).zfill(6))] = (fst or "99:99:99", int(obc or 0), pn or "", rd or "")
con.close()

# 1C verified rebound cache
df_1c = pd.read_parquet(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/verified_1c_rebound_cands.parquet")
df_1c["c6"] = df_1c["code"].astype(str).str.zfill(6)
c1_map = {(str(r.buy_date)[:10], r.c6): r for r in df_1c.itertuples()}

# 5m bars cache
bars_5m_cache = pickle.load(open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl", "rb"))
idx_5m = {(k[0], k[2]): v for k, v in bars_5m_cache.items()}

# Baostock lazy loader for missing 5m bars
bs_logged_in = False
def get_5m_bars(c6, buy_date):
    if (c6, buy_date) in idx_5m:
        v = idx_5m[(c6, buy_date)]
        if isinstance(v, pd.DataFrame) and not v.empty: return v
    global bs_logged_in
    if not bs_logged_in:
        bs.login()
        bs_logged_in = True
    prefix = "sh" if c6.startswith("6") else "sz"
    rs = bs.query_history_k_data_plus(f"{prefix}.{c6}", "date,time,open,high,low,close,volume,amount", start_date=buy_date, end_date=buy_date, frequency="5")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if rows:
        df_k = pd.DataFrame(rows, columns=["date", "time", "open", "high", "low", "close", "volume", "amount"])
        for col in ["open", "high", "low", "close", "volume", "amount"]: df_k[col] = df_k[col].astype(float)
        df_k["hhmm"] = df_k["time"].str[8:12]
        idx_5m[(c6, buy_date)] = df_k
        return df_k
    return pd.DataFrame()

get_lock = lambda c6, d: float(max([r for r in holders.get(c6, []) if r[0] < d], key=lambda x: x[1])[2]) if any(r[0] < d for r in holders.get(c6, [])) else 38.0

print("[3/5] Mining candidates across all 1176 days from full market daily panel...")

raw_candidates = []

for d1 in eval_dts:
    idx = dt_to_idx[d1]
    if idx < 2: continue
    d0 = all_dts[idx - 1]
    g0, g1 = by_dt[d0], by_dt[d1]
    zt0 = g0[g0["is_zt"]]
    if zt0.empty: continue
    mb = int(zt0["streak"].max())
    
    is_gold_today = bool(regime_dict.get(d1, False))
    
    # 确定 D0 的最高标梯队
    top0 = zt0[zt0["streak"] == mb]
    top_cnt = len(top0)
    
    # 候选目标收集 [(c6, pool_tag, streak_d0, candidate_type)]
    targets = []
    
    # 1. 常规高度 >= 4 (Pool A / Pool B)
    if mb >= 4:
        if top_cnt == 1:
            r0 = top0.iloc[0]
            targets.append((r0["c6"], "PoolA_Solo", mb, "PRIMARY_DRAGON"))
        elif top_cnt == 2:
            for r0 in top0.itertuples():
                targets.append((r0.c6, "PoolA_Dual", mb, "DUAL_DRAGON"))
        elif all(top0["yz_streak"] >= 3):
            # 一字顶死下的换手第一高
            tz = zt0[(zt0["streak"] < mb) & (zt0["streak"] >= 4) & (zt0["yz_streak"] < 3)]
            if not tz.empty:
                sm = int(tz["streak"].max())
                stp = tz[tz["streak"] == sm]
                for r0 in stp.itertuples():
                    targets.append((r0.c6, "PoolB_Turnover", sm, "POOLB_DRAGON"))
                    
    # 2. 松绑 ④: 黄金期 3 板最高换手龙首阴
    elif mb == 3 and is_gold_today:
        if top_cnt == 1:
            r0 = top0.iloc[0]
            if not bool(r0["is_yizi"]):
                targets.append((r0["c6"], "PoolD_3Board", 3, "B3_GOLD_DRAGON"))
                
    g1i = g1.set_index("c6")
    
    for c6, pool_tag, st0, cand_type in targets:
        if c6 not in g1i.index: continue
        r1 = g1i.loc[c6]
        if bool(r1["is_zt"]): continue # 必须断板
        
        bars = code_bars.get(c6)
        if not bars: continue
        d1p = bars["p"].get(d1)
        if d1p is None: continue
        d2p = d1p + 1
        if d2p >= len(bars["dts"]) or bars["is_yizi"][d2p]: continue
        
        b_op = float(bars["open"][d2p])
        zt_px2 = float(bars["zt_px"][d2p])
        dt_px2 = float(bars["dt_px"][d2p])
        if b_op <= dt_px2 + 0.011 or b_op >= zt_px2 - 0.011 or b_op <= 0: continue
        
        d2_dt = bars["dts"][d2p]
        op2 = float(bars["o_pct"][d2p])
        
        # 判断 D1 K线形态
        c1, o1, p1 = float(r1["close"]), float(r1["open"]), float(r1["pre_c"])
        d1_pct = c1 / p1 - 1.0
        rng1 = max(float(r1["high"] - r1["low"]), 0.01)
        l_sh1 = (c1 - float(r1["low"])) / rng1
        is_true_yang = (c1 > o1)
        is_fake_yin = (not is_true_yang) and (c1 >= p1)
        is_kangdie_yin = (c1 < p1) and (d1_pct >= -0.050) and (l_sh1 >= 0.35 or float(r1["to"]) <= 30.0) and (not bool(r1["is_dt"]))
        
        # 分类形态标签
        if is_true_yang:
            shape_tag = "TRUE_YANG"
        elif is_fake_yin:
            shape_tag = "FAKE_YIN_ZHEN_YANG"
        elif is_kangdie_yin:
            shape_tag = "KANGDIE_YIN"
        else:
            shape_tag = "DEAD_YIN"
            
        # 若不是黄金期，非真阳一律跳过！
        is_gold_buy_day = bool(regime_dict.get(d2_dt, False))
        if (not is_gold_buy_day) and shape_tag != "TRUE_YANG":
            continue
        if is_gold_buy_day and shape_tag == "DEAD_YIN":
            continue
            
        # 开盘区间过滤
        # 平时：[-6.5%, +4.5%]；黄金期：[-6.5%, +7.8%]
        if not is_gold_buy_day:
            if not (-0.065 <= op2 <= 0.045): continue
        else:
            if not (-0.065 <= op2 <= 0.078): continue
            
        ex = "SH" if c6.startswith("60") else "SZ"
        d1_ts = pd.Timestamp(d1)
        w5_dt = all_dts[max(0, idx - 5)]
        lh0 = lhb_clean.get((d0, c6), (0, 0.0, 0, 0))
        lh1 = lhb_clean.get((d1, c6), (0, 0.0, 0, 0))
        tape_d0 = tape_map.get((d0, c6), ("99:99:99", 0, "", ""))
        dom, mbg = t_lookup.get((d1, c6), (False, 999))
        c1_item = c1_map.get((d2_dt, c6))
        pelo = float(getattr(c1_item, "p_elo", 120.0)) if c1_item else 120.0
        obc = int(getattr(c1_item, "open_board_count", tape_d0[1])) if c1_item else tape_d0[1]
        lk = get_lock(c6, d1)
        env1 = env_stats[d1]
        
        # 换手板数量与原生特征
        d0p = d1p - 1
        turn_b_cnt = sum(1 for k in range(max(0, d0p - st0 + 1), d0p + 1) if bars["is_zt"][k] and (not bars["is_yizi"][k]))
        d1_touch_zt = float(bars["high"][d1p]) >= float(bars["zt_px"][d1p]) - 0.011
        d1_deep_dip = (float(bars["low"][d1p]) / float(bars["pre_c"][d1p]) - 1.0) <= -0.06
        
        raw_candidates.append({
            "buy_date": d2_dt, "d1": d1, "d0": d0, "code": c6, "name": str(r1["name"]), "ex": ex,
            "pool": pool_tag, "cand_type": cand_type, "st0": st0, "shape": shape_tag,
            "is_gold": is_gold_buy_day, "op2": op2, "b_op": b_op, "zt_px2": zt_px2, "dt_px2": dt_px2,
            "d1_pct": d1_pct, "d1_op": float(r1["o_pct"]), "d1_to": float(r1["to"]),
            "d0_tight": float(r1["d0_tight"]), "csi5": CSI_MAP[d1] / CSI_MAP[all_dts[max(0, idx - 5)]] - 1.0,
            "lh0": lh0[0], "lh1": lh1[0], "lh_sh1": lh1[1], "qu1": lh1[2], "in1": lh1[3],
            "s_reg": any(0 <= (d1_ts - pd.Timestamp(x)).days <= 10 for x in stock_reg.get(c6, [])),
            "tox": any(0 <= (d1_ts - pd.Timestamp(x)).days <= 10 for x in tox_dates.get(c6, [])),
            "ex_reg5": sum(1 for x in ex_reg[ex] if w5_dt <= x <= d1),
            "b3_dt": env1["b3_dt"], "brk_r10": env1["brk_r10"],
            "dom": dom, "pelo": pelo, "obc": obc, "lock": lk, "fmcap": float(r1["mcap"]) * (1.0 - lk / 100.0),
            "low_price_le20": c1 <= 20.0, "high_price_gt35": c1 > 35.0,
            "turn_boards_ge4": turn_b_cnt >= 4, "turn_boards_cnt": turn_b_cnt,
            "d1_deep_dip_le6": d1_deep_dip, "fst": tape_d0[0], "reason_desc": tape_d0[3]
        })

# 3. 添加松绑 ③: D2/D3 洗盘企稳反包 (D2洗盘 -> D3买)
print("[3.5/5] Mining Relax ③ D2/D3 wash & second wave break candidates...")
for d1 in eval_dts:
    idx = dt_to_idx[d1]
    if idx < 2: continue
    d0 = all_dts[idx - 1]
    g0, g1 = by_dt[d0], by_dt[d1]
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
        if d1p is None: continue
        d0p = d1p - 1
        d2p = d1p + 1
        d3p = d1p + 2
        if d3p >= len(bars["dts"]): continue
        
        # 仅在 D3 为黄金期时触发松绑 ③
        d3_dt = bars["dts"][d3p]
        if not regime_dict.get(d3_dt, False): continue
        
        # D1 破板且未跌停
        is_dt1 = bars["close"][d1p] <= bars["dt_px"][d1p] + 0.011
        if bars["is_zt"][d1p] or is_dt1: continue
        d1_pct = float(bars["close"][d1p] / bars["pre_c"][d1p] - 1.0)
        if d1_pct < -0.06: continue
        
        # D2 洗盘企稳
        is_dt2 = bars["close"][d2p] <= bars["dt_px"][d2p] + 0.011
        if bars["is_zt"][d2p] or is_dt2: continue
        d2_pct = float(bars["close"][d2p] / bars["pre_c"][d2p] - 1.0)
        if d2_pct < -0.05: continue
        if bars["close"][d2p] < bars["close"][d0p] * 0.90: continue
        
        b_op3 = float(bars["open"][d3p])
        zt_px3 = float(bars["zt_px"][d3p])
        dt_px3 = float(bars["dt_px"][d3p])
        op3 = float(bars["o_pct"][d3p])
        if b_op3 <= dt_px3 + 0.011 or b_op3 >= zt_px3 - 0.011 or not (-0.065 <= op3 <= 0.078): continue
        
        ex = "SH" if c6.startswith("60") else "SZ"
        d2_dt = bars["dts"][d2p]
        d2_ts = pd.Timestamp(d2_dt)
        w5_dt = all_dts[max(0, dt_to_idx[d2_dt] - 5)]
        lh0 = lhb_clean.get((d0, c6), (0, 0.0, 0, 0))
        lh2 = lhb_clean.get((d2_dt, c6), (0, 0.0, 0, 0))
        tape_d0 = tape_map.get((d0, c6), ("99:99:99", 0, "", ""))
        dom, mbg = t_lookup.get((d2_dt, c6), (False, 999))
        lk = get_lock(c6, d2_dt)
        env2 = env_stats[d2_dt]
        c2 = float(bars["close"][d2p])
        
        raw_candidates.append({
            "buy_date": d3_dt, "d1": d2_dt, "d0": d0, "code": c6, "name": str(r0.name if hasattr(r0, "name") else ""), "ex": ex,
            "pool": "PoolA_D2D3_Wash", "cand_type": "D2D3_WASH_REBOUND", "st0": mb, "shape": "D2_WASH_STABILIZE",
            "is_gold": True, "op2": op3, "b_op": b_op3, "zt_px2": zt_px3, "dt_px2": dt_px3,
            "d1_pct": d2_pct, "d1_op": float(bars["o_pct"][d2p]), "d1_to": float(bars["to"][d2p] if "to" in bars else 20.0),
            "d0_tight": 35.0, "csi5": CSI_MAP[d2_dt] / CSI_MAP[all_dts[max(0, dt_to_idx[d2_dt] - 5)]] - 1.0,
            "lh0": lh0[0], "lh1": lh2[0], "lh_sh1": lh2[1], "qu1": lh2[2], "in1": lh2[3],
            "s_reg": any(0 <= (d2_ts - pd.Timestamp(x)).days <= 10 for x in stock_reg.get(c6, [])),
            "tox": any(0 <= (d2_ts - pd.Timestamp(x)).days <= 10 for x in tox_dates.get(c6, [])),
            "ex_reg5": sum(1 for x in ex_reg[ex] if w5_dt <= x <= d2_dt),
            "b3_dt": env2["b3_dt"], "brk_r10": env2["brk_r10"],
            "dom": dom, "pelo": 120.0, "obc": 0, "lock": lk, "fmcap": 50.0,
            "low_price_le20": c2 <= 20.0, "high_price_gt35": c2 > 35.0,
            "turn_boards_ge4": True, "turn_boards_cnt": 4,
            "d1_deep_dip_le6": False, "fst": tape_d0[0], "reason_desc": tape_d0[3]
        })

df_all = pd.DataFrame(raw_candidates).drop_duplicates(["buy_date", "code"]).reset_index(drop=True)
print(f"Total raw candidates mined: {len(df_all)}")
print(f"   Golden Regime cands: {len(df_all[df_all['is_gold']])} | Normal cands: {len(df_all[~df_all['is_gold']])}")
print(df_all["shape"].value_counts())

# 4. 双打分卡构建：平时 V5.1 打分卡 vs 黄金期专属打分卡
print("[4/5] Computing Regular & Golden Scorecards...")

def calc_scores(r):
    # 平时打分卡 score_regular
    # 严格门槛：个股监管/减持立案/监管函>=2/换手>38%/拉萨>=3/高开>4.5%/低开<-6.5%
    if r["s_reg"] or r["tox"] or r["ex_reg5"] >= 2 or r["d1_to"] > 38.0 or r["lh1"] >= 3 or r["op2"] > 0.045 or r["op2"] < -0.065:
        sc_reg = -999
    else:
        sc = 60
        sc += 12 if r["brk_r10"] >= 0.20 else -8
        # 平时审美
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
        sc_reg = sc

    # 黄金期专属打分卡 score_gold
    # 黄金期专属规则：
    # 1. 废除熊市审美：主线总龙头 dom 不扣分反加 +8 分；换手放宽至 42%；开盘放宽至 +7.8%！
    if r["s_reg"] or r["tox"] or r["d1_to"] > 42.0 or r["lh1"] >= 4 or r["op2"] > 0.078 or r["op2"] < -0.065:
        sc_gold = -999
    else:
        sg = 65 # 基础分略高（黄金期高风偏）
        sg += 12 if r["brk_r10"] >= 0.20 else -5
        if r["dom"]: sg += 10 # 黄金期超级大主线龙头重奖！
        else: sg += 4
        # 抢筹高开加分
        if 0.045 < r["op2"] <= 0.078: sg += 12 # 弱转强抢筹高开给顶格加分！
        elif 0.0 <= r["op2"] <= 0.045: sg += 8
        elif -0.035 <= r["op2"] < 0.0: sg += 5
        # 换手良性
        if r["d1_to"] <= 32.0: sg += 6
        elif 32.0 < r["d1_to"] <= 40.0: sg += 5 # 黄金期二波换手龙
        # 形态加分
        if r["shape"] == "TRUE_YANG": sg += 6
        elif r["shape"] == "FAKE_YIN_ZHEN_YANG": sg += 5
        elif r["shape"] in ("KANGDIE_YIN", "D2_WASH_STABILIZE"): sg += 4
        # 盘口与筹码
        if r["obc"] == 0 and r["d0_tight"] >= 30.0: sg += 6
        if r["lh1"] == 0: sg += 6
        elif r["lh1"] <= 2: sg += 2
        if r["low_price_le20"]: sg += 5
        if r["turn_boards_ge4"]: sg += 6
        if r["qu1"] >= 1: sg += 4
        sc_gold = sg

    return sc_reg, sc_gold

sc_pairs = [calc_scores(row) for _, row in df_all.iterrows()]
df_all["sc_reg"] = [p[0] for p in sc_pairs]
df_all["sc_gold"] = [p[1] for p in sc_pairs]

# 5. 交易模拟引擎 (严格 D15 规范 + 真实 5m 点火确认 + 双红线 93% 止盈 + 免死金牌)
print("[5/5] Simulating trades and exit paths...")

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

def run_trade_sim(r, buy_mode, sell_mode):
    c6 = str(r["code"]).zfill(6)
    bars = code_bars[c6]
    d2_dt = r["buy_date"]
    d2p = bars["p"][d2_dt]
    b_op = float(bars["open"][d2p])
    zt_px = float(bars["zt_px"][d2p])
    imap = SH_MAP if r["ex"] == "SH" else SZ_MAP
    
    # Buy Execution
    if buy_mode == "red_auc":
        # 纯红开竞价直买
        if r["op2"] < 0.0 or b_op >= zt_px - 0.011: return None
        buy_px, is_auc = b_op, True
    elif buy_mode == "morn_cond":
        # 智能早盘：红开竞价直买，绿开向上突破开盘+1.5%点火买
        if r["op2"] >= 0.0:
            if b_op >= zt_px - 0.011: return None
            buy_px, is_auc = b_op, True
        else:
            ipx = round(b_op * 1.015, 2)
            if ipx >= zt_px - 0.011: return None
            df_k = get_5m_bars(c6, d2_dt)
            if df_k.empty: return None
            sub_m = df_k[(df_k["date"] == d2_dt) & (df_k["hhmm"] <= "11:30")]
            if sub_m.empty or sub_m["high"].max() < ipx: return None
            buy_px = float(sub_m.iloc[0]["open"]) if float(sub_m.iloc[0]["open"]) >= ipx else ipx
            is_auc = False
            
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
                # 连板中首次真阳免死金牌
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
            # 黄金期升级卖点：
            # 若在黄金期内且买入日收真阳(c > op 且 pct >= 0)，给予免死多格局1天博二波！
            # 否则执行严格 S_cut_weak 止损：买入日亏超2%或收绿阴线且浮亏或次日核按钮<-3.5% -> 次日09:25竞价走
            can_hold_gold = r["is_gold"] and (d2_c >= b_op and d2_ret >= 0.0)
            if can_hold_gold:
                # 黄金期真阳多拿一天至 D3 收盘（若 D3 涨停则继续锁仓）
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
        "sc_reg": r["sc_reg"], "sc_gold": r["sc_gold"],
        "buy_px": buy_px, "exit_px": epx, "net_ret": float(ret),
        "hold_days": max(1, ep - d2p), "b_open_h": is_auc, "eo": eo
    }

# 预先跑出所有候选在 morn_cond + S_gold_upgrade 下的单笔表现并落盘
print("Simulating all candidate trades under morn_cond + S_gold_upgrade...")
sim_results = []
for _, row in df_all.iterrows():
    res = run_trade_sim(row, "morn_cond", "S_gold_upgrade")
    if res is not None:
        sim_results.append(res)

df_sim = pd.DataFrame(sim_results)
print(f"Total simulated valid trades: {len(df_sim)}")
df_sim.to_pickle(f"{OUT_DIR}/v6_gold_all_cands_sim.pkl")
df_all.to_pickle(f"{OUT_DIR}/v6_gold_all_cands_raw.pkl")
print("Saved v6_gold_all_cands_sim.pkl successfully.")
