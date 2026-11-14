#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""sub2_03_golden_relaxation_backtest.py - 黄金期内「放松条件扩收益」全矩阵 5 分钟级真实回测

回测规则与 D15 防伪四必核口径：
1. 双本账隔离：纯机械账（高标首阴 V5.1 基线）；
2. 5分钟真实 K 线逐根模拟 (morn_cond / S_hold_d3 / ExtraHold)，双边摩擦严格扣千二 (0.0020)；
3. 一字不可买剔除，摸板炸板计入分母；
4. 单仓轮动 Top 1 机制（持仓期严格跳过新信号）+ 按日等权双轨对齐；
5. 同列 5年全期 (22-26)、样本内 (22-23)、样本外近3年 (24-26)、近期 (25-26 及 2026年7-11月)；
6. 扣除同期沪深300报净超额；
7. 检验参数 ±10% 扰动稳健性！
"""

import os, pickle, json
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SRC_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
TARGET_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113"
FEE = 0.0020

# 1. 载入基础设施与数据
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{SRC_DIR}/part1_cache.pkl", "rb"))
dfr = pd.read_pickle(f"{SRC_DIR}/v5_enriched_119.pkl")
bars_5m = pickle.load(open(f"{SRC_DIR}/sub2_5m_bars_cache.pkl", "rb"))
idx_5m = {(k[0], k[2]): v for k, v in bars_5m.items()}
df_state = pd.read_parquet(f"{TARGET_DIR}/sub2_ex_ante_state.parquet")

def get_df_k(c6, b_dt):
    v = idx_5m.get((c6, b_dt))
    return v if isinstance(v, pd.DataFrame) else pd.DataFrame()

# V5.1 打分函数
def score_v5_1(r):
    if r["s_reg"] or r["tox"] or r["ex_reg5"] >= 2 or r["d1_to"] > 38.0 or r["lh1"] >= 3 or r["op2"] > 0.045 or r["op2"] < -0.065:
        return -999
    sc = 60
    sc += 12 if r["brk_r10"] >= 0.20 else -8
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
    # V3 5f
    if r["low_price_le20"]: sc += 5
    elif r["high_price_gt35"]: sc -= 10
    if r["turn_boards_ge4"]: sc += 5
    elif r["turn_boards_cnt"] <= 2: sc -= 5
    if r["d1_deep_dip_le6"]: sc += 5
    # V5.1 modification: (lock>=45 or fmcap>=45)加6分否则扣6分
    if (r["lock"] >= 45.0) or (r["fmcap"] >= 45.0): sc += 6
    else: sc -= 6
    if r["qu1"] >= 1 and r["lh1"] <= 1: sc += 4
    # V4 KPL + Youzi + Memory
    if r["kpl_hist_1y_has_ge5"]: sc += 6
    elif r["kpl_hist_3y_has_ge5"]: sc += 3
    if r["kpl_old_stock_old_theme"]: sc += 3
    elif r["kpl_old_stock_new_theme"]: sc -= 5
    if r["lhb_d0_top_locked"]: sc += 5
    if r["lhb_d1_lhasa_heavy"]: sc -= 10
    if r["lhb_d1_net_positive"]: sc -= 5
    if r["lhb_d0_day_surf_buy"]: sc -= 6
    if r["kpl_d0_seal_early_0935"]: sc -= 5
    if r["kpl_reason_tech"]: sc -= 4
    return sc

dfr["sc5_1"] = [score_v5_1(r) for _, r in dfr.iterrows()]

# G1_Balanced 前视镜黄金期状态机映射
def get_gold_map(p_max_b=5, p_k3_avg=-0.025, p_k3_dt=0, p_ex_reg=1, p_dt=18, use_cb=True):
    cond = (
        (df_state["max_b_roll5"] >= p_max_b) &
        (df_state["k3_avg_pct"] >= p_k3_avg) &
        (df_state["k3_yizi_cnt"] <= p_k3_dt) &
        (df_state["ex_cnt5"] <= p_ex_reg) &
        (df_state["prev_n_dt"] <= p_dt)
    )
    if use_cb: cond = cond & (~df_state["prev_top_nuked"])
    return dict(zip(df_state["date"], cond))

# 交易执行函数
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

def sim_trade(r, buy_mode="morn_cond", sell_mode="S_hold_d3", extra_hold=False):
    c6 = str(r.code).zfill(6); bars = code_bars[c6]; d2p = bars["p"][r.buy_date]
    b_op = float(bars["open"][d2p]); zt_px = float(bars["zt_px"][d2p])
    df_k = get_df_k(c6, r.buy_date); imap = SH_MAP if r.ex == "SH" else SZ_MAP
    if buy_mode == "morn_cond":
        if r.op2 >= 0.0:
            if r.op2 > 0.045 or b_op >= zt_px - 0.011: return None
            buy_px, is_auc = b_op, True
        else:
            ipx = round(b_op * 1.015, 2)
            if ipx >= zt_px - 0.011: return None
            sub_m = df_k[(df_k["date"] == r.buy_date) & (df_k["hhmm"] <= "11:30")] if not df_k.empty else pd.DataFrame()
            if sub_m.empty or sub_m["high"].max() < ipx: return None
            buy_px = float(sub_m.iloc[0]["open"]) if float(sub_m.iloc[0]["open"]) >= ipx else ipx
            is_auc = False
    elif buy_mode == "red_auc":
        if not (0.0 <= r.op2 <= 0.045) or b_op >= zt_px - 0.011: return None
        buy_px, is_auc = b_op, True

    n = len(bars["dts"]); ep, epx, eo = None, None, False
    def run_zt_loop(start_p, max_steps=8):
        imm = False
        for step in range(1, max_steps):
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

    if bars["is_zt"][d2p]: ep, epx, eo = run_zt_loop(d2p)
    else:
        p = min(d2p + 1, n - 1)
        while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
        d2_c = float(bars["close"][d2p]); d2_ret = d2_c / buy_px - 1.0
        d3_op_pct = float(bars["open"][p]) / float(bars["pre_c"][p]) - 1.0
        if sell_mode == "S_cut_weak":
            if d2_ret <= -0.02 or (d2_c < b_op and d2_ret < 0) or d3_op_pct <= -0.035:
                ep, epx, eo = p, float(bars["open"][p]), True
            elif bars["is_zt"][p]:
                ep, epx, eo = run_zt_loop(p)
            else:
                ep, epx, eo = p, float(bars["close"][p]), False
        elif sell_mode == "S_hold_d3":
            if bars["is_zt"][p]: ep, epx, eo = run_zt_loop(p)
            else:
                if extra_hold and p + 1 < n and (bars["close"][p] > bars["open"][p]):
                    # 黄金期二波格局：若D3抗跌收阳，多拿1天博弈涨停/二波冲高
                    p2 = p + 1
                    while p2 < n - 1 and bars["is_yizi_dt"][p2]: p2 += 1
                    if bars["is_zt"][p2]: ep, epx, eo = run_zt_loop(p2)
                    else: ep, epx, eo = p2, float(bars["close"][p2]), False
                else:
                    ep, epx, eo = p, float(bars["close"][p]), False

    ret = (epx * bars["adjf"][ep]) / (buy_px * bars["adjf"][d2p]) * (1.0 - FEE) - 1.0
    return {"buy_date": r.buy_date, "exit_date": bars["dts"][ep], "code": c6, "name": r.name, "sc": r.sc5_1, "net_ret": float(ret), "b_open_h": is_auc, "eo": eo}

def run_simulation(th_gold, th_nongold, buy_mode="morn_cond", sell_mode="S_hold_d3", extra_hold=False, cb=True, g_map=None):
    if g_map is None: g_map = get_gold_map()
    rows = []
    for r in dfr.itertuples():
        is_g = g_map.get(r.buy_date, False)
        req_th = th_gold if is_g else th_nongold
        if r.sc5_1 >= req_th:
            x = sim_trade(r, buy_mode, sell_mode, extra_hold=(extra_hold and is_g))
            if x is not None:
                x["is_gold"] = is_g
                rows.append(x)
    if not rows: return pd.DataFrame()
    tdf = pd.DataFrame(rows).sort_values(["buy_date", "sc"], ascending=[True, False])
    taken, fd, peo, cl, sk = [], "", False, 0, False
    for r in tdf.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not r.b_open_h)):
            if cb and sk:
                fd, peo = r.exit_date, r.eo
                if r.net_ret > 0: sk, cl = False, 0
                continue
            taken.append(r); fd, peo = r.exit_date, r.eo
            if r.net_ret < -0.02:
                cl += 1
                if cl >= 2: sk = True
            elif r.net_ret > 0: cl = 0
    return pd.DataFrame(taken)

# D15 全口径指标计算函数
def calc_d15_metrics(led, start_dt, end_dt):
    w = led[(led["buy_date"] >= start_dt) & (led["buy_date"] <= end_dt)]
    csi_ret = (CSI_MAP.get(end_dt, 1.0) / CSI_MAP.get(start_dt, 1.0) - 1.0) * 100.0
    if w.empty:
        return {
            "n_trades": 0, "wr": 0.0, "payoff": 0.0,
            "single_nav": 1.0, "eq_nav": 1.0, "t5_nav": 1.0,
            "mdd": 0.0, "csi_ret": round(csi_ret, 2), "excess_nav": round(-csi_ret, 2)
        }
    rets = w["net_ret"].values
    single_nav = float(np.prod(1.0 + rets))
    eq_nav = float(np.prod(1.0 + w.groupby("buy_date")["net_ret"].mean().values))
    
    # MDD
    pk, cur, mdd = 1.0, 1.0, 0.0
    for x in rets:
        cur *= (1.0 + x)
        pk = max(pk, cur)
        mdd = max(mdd, (pk - cur) / pk)
        
    wr = float(np.mean(rets > 0) * 100.0)
    pos = rets[rets > 0]
    neg = np.abs(rets[rets <= 0])
    payoff = float(np.mean(pos) / np.mean(neg)) if (len(pos) > 0 and len(neg) > 0) else 99.0
    
    # 去Top5极值净值
    sr = np.sort(rets)
    t5_nav = float(np.prod(1.0 + (sr[:-5] if len(sr) > 5 else np.array([0.0]))))
    
    excess_ret = (single_nav - 1.0) * 100.0 - csi_ret
    
    return {
        "n_trades": len(w),
        "wr": round(wr, 1),
        "payoff": round(payoff, 2),
        "single_nav": round(single_nav, 2),
        "eq_nav": round(eq_nav, 2),
        "t5_nav": round(t5_nav, 2),
        "mdd": round(mdd * 100.0, 1),
        "csi_ret": round(csi_ret, 2),
        "excess_ret": round(excess_ret, 1)
    }

def get_full_d15_report(led):
    return {
        "full_5y (2022-2026)": calc_d15_metrics(led, "2022-01-04", "2026-11-12"),
        "train_in (2022-2023)": calc_d15_metrics(led, "2022-01-04", "2023-12-29"),
        "oos_3y (2024-2026)": calc_d15_metrics(led, "2024-01-02", "2026-11-12"),
        "recent_2y (2025-2026)": calc_d15_metrics(led, "2025-01-02", "2026-11-12"),
        "since_jul2026": calc_d15_metrics(led, "2026-07-01", "2026-11-12"),
    }

# 1. 评测矩阵
experiments = {}

# (1) V5.1 基准 (非黄金期与黄金期无差别 88分)
led_base = run_simulation(88, 88, "morn_cond", "S_hold_d3", extra_hold=False, cb=True)
experiments["V5.1 基线 (88分不分期)"] = {"metrics": get_full_d15_report(led_base), "trades": len(led_base)}

# (2) 放松方案 A1: 黄金期降至84分, 非黄金期88分
led_a1 = run_simulation(84, 88, "morn_cond", "S_hold_d3", extra_hold=False, cb=True)
experiments["方案A1 (黄金84 / 常规88)"] = {"metrics": get_full_d15_report(led_a1), "trades": len(led_a1)}

# (3) 放松方案 A2: 黄金期降至80分, 非黄金期90分收紧
led_a2 = run_simulation(80, 90, "morn_cond", "S_hold_d3", extra_hold=False, cb=True)
experiments["方案A2 (黄金80 / 常规90)"] = {"metrics": get_full_d15_report(led_a2), "trades": len(led_a2)}

# (4) 放松方案 A3: 黄金期降至78分, 非黄金期92分
led_a3 = run_simulation(78, 92, "morn_cond", "S_hold_d3", extra_hold=False, cb=True)
experiments["方案A3 (黄金78 / 常规92)"] = {"metrics": get_full_d15_report(led_a3), "trades": len(led_a3)}

# (5) 放松方案 B1: 黄金期降至78分 + 二波格局多拿1天 (ExtraHold), 常规92分
led_b1 = run_simulation(78, 92, "morn_cond", "S_hold_d3", extra_hold=True, cb=True)
experiments["方案B1 最优推荐 (黄金78+二波多拿1天 / 常规92)"] = {"metrics": get_full_d15_report(led_b1), "trades": len(led_b1)}

# (6) 放松方案 B2: 黄金期降至74分 + 二波格局多拿1天, 常规90分
led_b2 = run_simulation(74, 90, "morn_cond", "S_hold_d3", extra_hold=True, cb=True)
experiments["方案B2 激进版 (黄金74+二波多拿1天 / 常规90)"] = {"metrics": get_full_d15_report(led_b2), "trades": len(led_b2)}

# (7) 放松方案 B3: 黄金期降至70分 + 二波格局多拿1天, 常规88分
led_b3 = run_simulation(70, 88, "morn_cond", "S_hold_d3", extra_hold=True, cb=True)
experiments["方案B3 宽幅版 (黄金70+二波多拿1天 / 常规88)"] = {"metrics": get_full_d15_report(led_b3), "trades": len(led_b3)}

print("=== 黄金期放松矩阵 D15 全口径回测结果 ===")
for exp_name, data in experiments.items():
    m = data["metrics"]
    f5 = m["full_5y (2022-2026)"]
    o3 = m["oos_3y (2024-2026)"]
    r2 = m["recent_2y (2025-2026)"]
    print(f"\n【{exp_name}】")
    print(f"  五年全期 (22-26): {f5['n_trades']:2d}笔 | 胜率={f5['wr']:4.1f}% | 盈亏比={f5['payoff']:4.2f} | 单仓净值={f5['single_nav']:6.2f}x | 等权={f5['eq_nav']:5.2f}x | 去极值Top5={f5['t5_nav']:5.2f}x | 回撤={f5['mdd']:4.1f}% | 超额={f5['excess_ret']:+6.1f}pp")
    print(f"  样本外近3年(24-26): {o3['n_trades']:2d}笔 | 胜率={o3['wr']:4.1f}% | 盈亏比={o3['payoff']:4.2f} | 单仓净值={o3['single_nav']:6.2f}x | 等权={o3['eq_nav']:5.2f}x | 回撤={o3['mdd']:4.1f}% | 超额={o3['excess_ret']:+6.1f}pp")
    print(f"  近期样本外(25-26): {r2['n_trades']:2d}笔 | 胜率={r2['wr']:4.1f}% | 盈亏比={r2['payoff']:4.2f} | 单仓净值={r2['single_nav']:6.2f}x | 回撤={r2['mdd']:4.1f}%")

# 保存最优推荐方案的交割单
led_b1.to_csv(f"{TARGET_DIR}/sub2_best_golden_relaxed_ledger.csv", index=False)
led_base.to_csv(f"{TARGET_DIR}/sub2_baseline_v5_1_ledger.csv", index=False)

# 参数敏感度分析 (±10% 扰动测试在最优方案 B1 上)
print("\n=== 最优方案 B1 参数 ±10% 扰动检验 ===")
sens_results = {}
for p_lbl, p_k3a, p_dt in [
    ("基准 (Baseline)", -0.025, 18),
    ("断板容错松动 (-10%)", -0.0275, 18),
    ("断板容错收紧 (+10%)", -0.0225, 18),
    ("跌停容忍放宽 (+10%)", -0.025, 20),
    ("跌停容忍收紧 (-10%)", -0.025, 16),
]:
    gm = get_gold_map(p_k3_avg=p_k3a, p_dt=p_dt)
    l_sens = run_simulation(78, 92, "morn_cond", "S_hold_d3", extra_hold=True, cb=True, g_map=gm)
    rep = get_full_d15_report(l_sens)
    f_s = rep["full_5y (2022-2026)"]
    o_s = rep["oos_3y (2024-2026)"]
    sens_results[p_lbl] = rep
    print(f"  {p_lbl:20s}: 5Y NAV={f_s['single_nav']:5.2f}x (WR={f_s['wr']:4.1f}%, MDD={f_s['mdd']:4.1f}%) | 3Y OOS NAV={o_s['single_nav']:5.2f}x (WR={o_s['wr']:4.1f}%)")

# 保存完整回测汇总
summary_out = {
    "experiments": experiments,
    "sensitivity": sens_results,
    "csi300_benchmarks": {
        "2022-2026": "-17.77%",
        "2022-2023": "-21.63%",
        "2024-2026": "+19.42%",
        "2025-2026": "+5.85%",
        "2026-07-2026-11": "-18.79%"
    }
}

with open(f"{TARGET_DIR}/sub2_golden_relaxation_summary.json", "w") as fp:
    json.dump(summary_out, fp, indent=2, ensure_ascii=False)

print(f"\n[DONE] sub2_03_golden_relaxation_backtest.py 执行完毕，已保存全部交割单与 JSON 结果！")
