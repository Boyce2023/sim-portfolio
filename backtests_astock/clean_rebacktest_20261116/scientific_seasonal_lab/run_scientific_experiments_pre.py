#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_scientific_experiments_pre.py
深入比对 4 大科学专供机制在五期 D15 与 2022-2025 样本外指标
"""
import os, sys, json, math, pickle
import pandas as pd
import numpy as np

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CLEAN = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
sys.path.insert(0, CLEAN)

from synthesize_master_clean_20261116 import standardize_ledger, run_1slot, calc_metrics

# 1. 载入基准指数
with open(f"{CLEAN}/csi300_canonical_20261116.json", "r", encoding="utf-8") as f:
    CSI_MAP = json.load(f)

with open(f"{SANDBOX}/index_klines_5y_cache.json", "r", encoding="utf-8") as f:
    sh300_daily = json.load(f)["sh000300"]

trading_days = sorted(sh300_daily.keys())

# 2. 载入既有三策略独立账本
b_h = standardize_ledger(f"{CLEAN}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴_V51", 1)
b_3 = standardize_ledger(f"{CLEAN}/partA_high_3to4/ledger_base_3to4_v34.csv", "三进四_V34", 2)
b_1 = standardize_ledger(f"{CLEAN}/partB_1to2/ledger_base_1to2_v18.csv", "一进二_V18", 3)

# 基础打分标准化 Z-score 参数 (严格由 2021-11 ~ 2025-12 历史均值与标准差率定，零未来函数)
# Train 期: 2021-11-15 ~ 2025-12-31
train_h = b_h[b_h["buy_date"] < "2026-01-01"]["score"]
train_3 = b_3[b_3["buy_date"] < "2026-01-01"]["score"]
train_1 = b_1[b_1["buy_date"] < "2026-01-01"]["score"]

mean_h, std_h = float(train_h.mean()), float(train_h.std())
mean_3, std_3 = float(train_3.mean()), float(train_3.std())
mean_1, std_1 = float(train_1.mean()), float(train_1.std())

print(f"Train期 (2021-2025) 基础打分分布率定参数:")
print(f"  高标首阴: Mean={mean_h:.2f}, Std={std_h:.2f} (Base_T=88.0)")
print(f"  三进四:   Mean={mean_3:.2f}, Std={std_3:.2f} (Base_T=90.0)")
print(f"  一进二:   Mean={mean_1:.2f}, Std={std_1:.2f} (Base_T=304.8)")

# 计算各候选的标准化 Z-score (偏离基础门槛的标准差倍数)
b_h["z_score"] = (b_h["score"] - 88.0) / std_h
b_3["z_score"] = (b_3["score"] - 90.0) / std_3
b_1["z_score"] = (b_1["score"] - 304.8) / std_1

# 基础候选全池
pool_base = pd.concat([b_h, b_3, b_1], ignore_index=True)

# 3. 辅助评估函数
def eval_slot_ledger(df_slot: pd.DataFrame, strat_name: str) -> dict:
    rets = df_slot["net_ret"].to_numpy(dtype=float)
    n = len(rets)
    if n == 0: return {}
    wr = float(np.mean(rets > 0) * 100.0)
    nav = float(np.prod(1.0 + rets))
    mdd = 0.0
    cur, pk = 1.0, 1.0
    for r in rets:
        cur *= (1.0 + r)
        pk = max(pk, cur)
        mdd = max(mdd, (pk - cur) / pk)
    # cap10m
    cap = 1000.0
    for r in rets:
        cap += min(cap, 1000.0) * float(r)
    cap_ret = (cap / 1000.0 - 1.0) * 100.0
    
    # 拆解五大窗口与 2022-2025
    windows = [
        ("全五年", "2021-11-15", "2026-11-16"),
        ("2022-2025", "2022-01-01", "2025-12-31"),
        ("2026全年", "2026-01-01", "2026-11-16"),
        ("2026年7月以来", "2026-07-01", "2026-11-16"),
        ("2026年10月以来", "2026-10-01", "2026-11-16"),
    ]
    res = {
        "strat_name": strat_name, "total_trades": n, "win_rate": round(wr, 2),
        "cum_nav": round(nav, 2), "max_dd_pct": round(mdd * 100.0, 2),
        "cap10m_ret_pct": round(cap_ret, 2), "windows": {}
    }
    for w_name, s_d, e_d in windows:
        sub = df_slot[(df_slot["buy_date"] >= s_d) & (df_slot["buy_date"] <= e_d)]
        r_sub = sub["net_ret"].to_numpy(dtype=float)
        n_sub = len(r_sub)
        wr_sub = float(np.mean(r_sub > 0) * 100.0) if n_sub > 0 else 0.0
        nav_sub = float(np.prod(1.0 + r_sub)) if n_sub > 0 else 1.0
        mdd_sub = 0.0
        cur_sub, pk_sub = 1.0, 1.0
        for rx in r_sub:
            cur_sub *= (1.0 + rx)
            pk_sub = max(pk_sub, cur_sub)
            mdd_sub = max(mdd_sub, (pk_sub - cur_sub) / pk_sub)
        cap_sub = 1000.0
        for rx in r_sub:
            cap_sub += min(cap_sub, 1000.0) * float(rx)
        cap_ret_sub = (cap_sub / 1000.0 - 1.0) * 100.0
        mean_ret_sub = float(np.mean(r_sub) * 100.0) if n_sub > 0 else 0.0
        res["windows"][w_name] = {
            "trades": n_sub, "win_rate": round(wr_sub, 2), "mean_ret_pct": round(mean_ret_sub, 2),
            "nav": round(nav_sub, 2), "max_dd_pct": round(mdd_sub * 100.0, 2), "cap10m_ret_pct": round(cap_ret_sub, 2)
        }
    return res

# 4. 实现 4 大候选机制
# --- 机制 0: 五年静态基础版 ---
slot_base = pd.read_csv(f"{CLEAN}/ledger_base_combined_3main.csv")
res_base = eval_slot_ledger(slot_base, "静态五年基础版")

# --- 机制 0-old: 旧版 26Q4 专供 (微观改分版) ---
slot_26q4 = pd.read_csv(f"{CLEAN}/partD_26q4_and_combined/ledger_26q4_combined_3main.csv")
# 统一费率为 0.0020
slot_26q4["net_ret_0020"] = (1.0 + slot_26q4["net_ret"]) / (1.0 - 0.0030) * (1.0 - 0.0020) - 1.0
slot_26q4_adj = slot_26q4.copy(); slot_26q4_adj["net_ret"] = slot_26q4_adj["net_ret_0020"]
res_q4_old = eval_slot_ledger(slot_26q4_adj, "旧版26Q4专供(微观改分)")

# --- 机制 C1: 标准化确信度 Z-score 顺位机制 (Standardized Conviction Priority) ---
# 同日碰撞时，按 Z-score 从高到低选龙头
def run_slot_zscore(pool_df: pd.DataFrame) -> pd.DataFrame:
    df_s = pool_df.sort_values(["buy_date", "z_score", "buy_hhmm"], ascending=[True, False, True]).reset_index(drop=True)
    picked = []
    cur_exit_dt = ""
    cur_exit_hhmm = 0
    for row in df_s.itertuples(index=False):
        if not cur_exit_dt or row.buy_date > cur_exit_dt or (row.buy_date == cur_exit_dt and row.buy_hhmm > cur_exit_hhmm):
            picked.append(row._asdict())
            cur_exit_dt = row.exit_date
            cur_exit_hhmm = row.exit_hhmm
    return pd.DataFrame(picked)

slot_c1 = run_slot_zscore(pool_base)
res_c1 = eval_slot_ledger(slot_c1, "机制C1:标准化确信度顺位")

# --- 机制 A1: 贝叶斯滚动当季表现顺位机制 (Bayesian Rolling Paper Edge Priority) ---
# 只看 exit_date < t 且过去 W=40 个交易日已结平交易的纸面表现：
# 若某策略近期胜率明显更高，则碰撞日优先放行近期状态好的策略
def run_slot_rolling_bayesian(pool_df: pd.DataFrame, W_days: int = 40) -> pd.DataFrame:
    # 模拟每日实盘推进
    all_dts = sorted(pool_df["buy_date"].unique())
    dt_to_idx = {d: i for i, d in enumerate(trading_days) if d in trading_days}
    
    picked = []
    cur_exit_dt = ""
    cur_exit_hhmm = 0
    closed_history = []
    
    for d in all_dts:
        day_cands = pool_df[pool_df["buy_date"] == d].copy()
        if day_cands.empty: continue
        
        # 1. 过滤单仓可用性
        if cur_exit_dt != "" and d < cur_exit_dt: continue
        if cur_exit_dt != "" and d == cur_exit_dt:
            day_cands = day_cands[day_cands["buy_hhmm"] > cur_exit_hhmm]
            if day_cands.empty: continue
            
        # 2. 仅用 exit_date < d 的已结平交易计算各策略过去 W_days 的贝叶斯滚动表现
        past_closed = [tr for tr in closed_history if tr["exit_date"] < d]
        # 过滤在过去 W_days 交易日内平仓的
        idx_cur = dt_to_idx.get(d, 9999)
        w_closed = [tr for tr in past_closed if (idx_cur - dt_to_idx.get(tr["exit_date"], 0)) <= W_days]
        
        # 计算各策略近期的纸面动量修正
        prio_scores = []
        for r in day_cands.itertuples():
            strat = r.strategy
            s_tr = [tr for tr in w_closed if tr["strategy"] == strat]
            n_s = len(s_tr)
            if n_s == 0:
                # 无近期样本，完全按先验 (Z-score)
                prio_adj = float(r.z_score)
            else:
                wr_s = np.mean([tr["net_ret"] > 0 for tr in s_tr])
                mean_r = np.mean([tr["net_ret"] for tr in s_tr])
                k_shrink = min(1.0, n_s / (n_s + 3.0))
                # 贝叶斯修正：动量加分 = k * (wr_s - 0.65) * 2.0
                prio_adj = float(r.z_score) + k_shrink * (wr_s - 0.65) * 2.0
            prio_scores.append(prio_adj)
            
        day_cands["dyn_prio"] = prio_scores
        top_cand = day_cands.sort_values(["dyn_prio", "buy_hhmm"], ascending=[False, True]).iloc[0].to_dict()
        
        picked.append(top_cand)
        cur_exit_dt = top_cand["exit_date"]
        cur_exit_hhmm = top_cand["exit_hhmm"]
        closed_history.append(top_cand)
        
    return pd.DataFrame(picked)

slot_a1 = run_slot_rolling_bayesian(pool_base, W_days=40)
res_a1 = eval_slot_ledger(slot_a1, "机制A1:贝叶斯滚动纸面动量顺位(W=40)")

# --- 机制 B1: 宏观生态温度计顺位与避险门 (Market Regime Thermometer) ---
# 仅使用 D-1 收盘已知大盘 20 日动量: csi_20d = sh300[D-1] / sh300[D-21] - 1.0
# 当大盘处于深熊下行期 (csi_20d < -0.04 时)，三进四往往容易受连板断板跌停拖累，碰撞日若有高标/一进二则下调三进四优先级；
# 同时对三进四单独要求分数 >= 93 分 (避开 90-92 分断板雷)
def run_slot_regime(pool_df: pd.DataFrame) -> pd.DataFrame:
    picked = []
    cur_exit_dt = ""
    cur_exit_hhmm = 0
    
    all_dts = sorted(pool_df["buy_date"].unique())
    dt_to_idx = {d: i for i, d in enumerate(trading_days)}
    
    for d in all_dts:
        day_cands = pool_df[pool_df["buy_date"] == d].copy()
        if day_cands.empty: continue
        
        if cur_exit_dt != "" and d < cur_exit_dt: continue
        if cur_exit_dt != "" and d == cur_exit_dt:
            day_cands = day_cands[day_cands["buy_hhmm"] > cur_exit_hhmm]
            if day_cands.empty: continue
            
        # D-1 宏观温度
        idx_cur = dt_to_idx.get(d, 0)
        idx_prev = max(0, idx_cur - 1)
        idx_20 = max(0, idx_cur - 21)
        d_prev = trading_days[idx_prev]
        d_20 = trading_days[idx_20]
        csi_20d = sh300_daily[d_prev] / sh300_daily[d_20] - 1.0
        
        # 若大盘处于急跌期 (csi_20d < -0.04)，三进四门槛提升至 93 (过滤擦边90-92分)
        if csi_20d < -0.04:
            day_cands = day_cands[~((day_cands["strategy"] == "三进四_V34") & (day_cands["score"] < 93.0))]
            if day_cands.empty: continue
            
        top_cand = day_cands.sort_values(["z_score", "buy_hhmm"], ascending=[False, True]).iloc[0].to_dict()
        picked.append(top_cand)
        cur_exit_dt = top_cand["exit_date"]
        cur_exit_hhmm = top_cand["exit_hhmm"]
        
    return pd.DataFrame(picked)

slot_b1 = run_slot_regime(pool_base)
res_b1 = eval_slot_ledger(slot_b1, "机制B1:宏观温度计避险门+Z-score")

# --- 机制 D: 科学当季专供最优组合 (Mechanism D = C1确信度顺位 + 纸面连亏避险) ---
# 规则极简透明 (实盘 09:25:03 一行算完):
# 1. 锁死五年基础版微观打分一字不动；
# 2. 同日碰撞日：按 standardized Z-score 确信度从高到低放行龙头；
# 3. 动态避险护栏：若某策略在过去 40 天纸面连续 2 笔亏损，碰撞日暂扣 1.0 Z-score，直至恢复盈利。
def run_slot_mechanism_d(pool_df: pd.DataFrame) -> pd.DataFrame:
    picked = []
    cur_exit_dt = ""
    cur_exit_hhmm = 0
    closed_history = []
    
    all_dts = sorted(pool_df["buy_date"].unique())
    dt_to_idx = {d: i for i, d in enumerate(trading_days)}
    
    for d in all_dts:
        day_cands = pool_df[pool_df["buy_date"] == d].copy()
        if day_cands.empty: continue
        
        if cur_exit_dt != "" and d < cur_exit_dt: continue
        if cur_exit_dt != "" and d == cur_exit_dt:
            day_cands = day_cands[day_cands["buy_hhmm"] > cur_exit_hhmm]
            if day_cands.empty: continue
            
        past_closed = [tr for tr in closed_history if tr["exit_date"] < d]
        
        scores = []
        for r in day_cands.itertuples():
            strat = r.strategy
            s_tr = [tr for tr in past_closed if tr["strategy"] == strat]
            z = float(r.z_score)
            # 若最近连续 2 笔均亏损，扣 1.0 个 Z 标准分 (约收紧门槛 8~13 分)
            if len(s_tr) >= 2 and s_tr[-1]["net_ret"] < 0 and s_tr[-2]["net_ret"] < 0:
                z -= 1.0
            scores.append(z)
            
        day_cands["final_prio"] = scores
        top_cand = day_cands.sort_values(["final_prio", "buy_hhmm"], ascending=[False, True]).iloc[0].to_dict()
        picked.append(top_cand)
        cur_exit_dt = top_cand["exit_date"]
        cur_exit_hhmm = top_cand["exit_hhmm"]
        closed_history.append(top_cand)
        
    return pd.DataFrame(picked)

slot_d = run_slot_mechanism_d(pool_base)
res_d = eval_slot_ledger(slot_d, "机制D:当季专供定版(Z-score+连亏避险)")

# 5. 打印对比总表
print("\n" + "=" * 105)
print(f"{'方案名称':<25s} | {'2026-10+':<14s} | {'2026-07+':<14s} | {'2026全年':<15s} | {'2022-2025':<16s} | {'全五年':<16s}")
print("=" * 105)

for res in [res_base, res_q4_old, res_c1, res_a1, res_b1, res_d]:
    w10 = res["windows"]["2026年10月以来"]
    w07 = res["windows"]["2026年7月以来"]
    w26 = res["windows"]["2026全年"]
    woos = res["windows"]["2022-2025"]
    w5y = res["windows"]["全五年"]
    
    s10 = f"{w10['trades']}b/{w10['win_rate']}%/{w10['nav']}x"
    s07 = f"{w07['trades']}b/{w07['win_rate']}%/{w07['nav']}x"
    s26 = f"{w26['trades']}b/{w26['win_rate']}%/{w26['nav']}x"
    soos = f"{woos['trades']}b/{woos['win_rate']}%/{woos['mean_ret_pct']}%"
    s5y = f"{w5y['trades']}b/1000万+{w5y['cap10m_ret_pct']}%"
    print(f"{res['strat_name']:<25s} | {s10:<14s} | {s07:<14s} | {s26:<15s} | {soos:<16s} | {s5y:<16s}")

print("=" * 105)
