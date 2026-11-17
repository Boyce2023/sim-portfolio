#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
test_walkforward_variants.py
在全量候选池与严格 09:26 唯一挂单实盘口径下，系统性回测 M1/M2/M3
"""
import pickle, json, sys, os
import pandas as pd, numpy as np

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CLEAN = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
LAB_DIR = f"{CLEAN}/scientific_seasonal_lab"

with open(f"{SANDBOX}/index_klines_5y_cache.json", "r", encoding="utf-8") as f:
    sh300_daily = json.load(f)["sh000300"]
trading_days = sorted(sh300_daily.keys())
dt_to_idx = {d: i for i, d in enumerate(trading_days)}

with open(f"{LAB_DIR}/full_candidates_3main_5y.pkl", "rb") as f:
    full_pool = pickle.load(f)

cands_hd = full_pool["high_dragon"]
cands_34 = full_pool["3to4"]
cands_12 = full_pool["1to2"]

df_all = pd.DataFrame(cands_hd + cands_34 + cands_12)

# Rate train parameters (2021-2025)
train_all = df_all[df_all["buy_date"] < "2026-01-01"]
std_h = float(train_all[train_all["strategy"] == "高标首阴_V51"]["score"].std())
std_3 = float(train_all[train_all["strategy"] == "三进四_V34"]["score"].std())
std_1 = float(train_all[train_all["strategy"] == "一进二_V18"]["score"].std())

print(f"Train期标准差: HD={std_h:.2f}, 3to4={std_3:.2f}, 1to2={std_1:.2f}")

def sim_engine(df_candidates, get_daily_target_fn):
    picked_trades = []
    free_date = ""
    free_hhmm = 0
    dates = sorted(df_candidates["buy_date"].unique())
    for d in dates:
        if free_date != "" and d < free_date: continue
        allowed_hhmm = 0
        if free_date != "" and d == free_date:
            if free_hhmm > 925: continue
            allowed_hhmm = 930
            
        day_cands = df_candidates[df_candidates["buy_date"] == d].copy()
        if day_cands.empty: continue
        if allowed_hhmm > 0:
            day_cands = day_cands[day_cands["buy_hhmm"] >= allowed_hhmm]
            if day_cands.empty: continue
            
        target = get_daily_target_fn(d, day_cands, picked_trades)
        if target is None: continue
        
        if target["triggered"]:
            picked_trades.append(target)
            free_date = str(target["exit_date"])
            free_hhmm = int(target["exit_hhmm"])
            
    return picked_trades

def get_perf_stats(trades):
    if not trades: return {}
    df = pd.DataFrame(trades)
    rets = df["net_ret"].values
    n = len(rets)
    wr = float(np.mean(rets > 0) * 100)
    nav = float(np.prod(1.0 + rets))
    mdd = 0.0; cur, pk = 1.0, 1.0
    for r in rets:
        cur *= (1.0 + r); pk = max(pk, cur); mdd = max(mdd, (pk - cur) / pk)
    cap = 1000.0
    for r in rets: cap += min(cap, 1000.0) * float(r)
    cap_ret = float((cap / 1000.0 - 1.0) * 100.0)
    
    def win_stat(s_d, e_d):
        sub = df[(df["buy_date"] >= s_d) & (df["buy_date"] <= e_d)]
        if sub.empty: return {"n": 0, "wr": 0.0, "nav": 1.0, "mean": 0.0}
        r = sub["net_ret"].values
        return {"n": len(r), "wr": round(float(np.mean(r > 0) * 100), 1), "nav": round(float(np.prod(1 + r)), 2), "mean": round(float(np.mean(r) * 100), 2)}

    return {
        "n": n, "wr": round(wr, 1), "nav": round(nav, 1), "cap_ret": round(cap_ret, 1), "mdd": round(mdd * 100, 1),
        "train": win_stat("2021-11-15", "2025-12-31"),
        "y2026": win_stat("2026-01-01", "2026-11-16"),
        "m07": win_stat("2026-07-01", "2026-11-16"),
        "m10": win_stat("2026-10-01", "2026-11-16")
    }

# --- 1. 基准 ---
def fn_base(d, day_cands, history):
    ch = day_cands[(day_cands["strategy"] == "高标首阴_V51") & (day_cands["score"] >= 88.0)]
    if not ch.empty: return ch.sort_values("score", ascending=False).iloc[0].to_dict()
    c3 = day_cands[(day_cands["strategy"] == "三进四_V34") & (day_cands["score"] >= 90.0)]
    if not c3.empty: return c3.sort_values("score", ascending=False).iloc[0].to_dict()
    c1 = day_cands[(day_cands["strategy"] == "一进二_V18") & (day_cands["score"] >= day_cands["base_threshold"])]
    if not c1.empty: return c1.sort_values("score", ascending=False).iloc[0].to_dict()
    return None

p_base = get_perf_stats(sim_engine(df_all, fn_base))

# --- 2. 机制 M1: 滚动纸面动量温度计 (W=40) ---
# 仅看 exit_date < d 过去 W 天已完成交易的纸面表现
def make_fn_m1(W_days=40, penalty_loss2=True, relax_hot=False):
    def fn(d, day_cands, history):
        cur_idx = dt_to_idx.get(d, 9999)
        past_closed = [t for t in history if t["exit_date"] < d and (cur_idx - dt_to_idx.get(t["exit_date"], 0)) <= W_days]
        
        # 计算各策略动态阈值
        th_h, th_3, th_1 = 88.0, 90.0, 0.0 # 1to2 offset
        
        for strat in ["高标首阴_V51", "三进四_V34", "一进二_V18"]:
            s_tr = [t for t in past_closed if t["strategy"] == strat]
            if len(s_tr) >= 2 and penalty_loss2:
                # 检查最近 2 笔是否全亏
                if s_tr[-1]["net_ret"] < 0 and s_tr[-2]["net_ret"] < 0:
                    if strat == "高标首阴_V51": th_h += 3.0
                    elif strat == "三进四_V34": th_3 += 3.0
                    elif strat == "一进二_V18": th_1 += 8.0
            if len(s_tr) >= 2 and relax_hot:
                wr_s = np.mean([t["net_ret"] > 0 for t in s_tr])
                if wr_s >= 0.75 and np.mean([t["net_ret"] for t in s_tr]) > 0.06:
                    if strat == "高标首阴_V51": th_h -= 2.0
                    elif strat == "三进四_V34": th_3 -= 2.0
                    elif strat == "一进二_V18": th_1 -= 4.0
                    
        # 过滤各策略
        c_h = day_cands[(day_cands["strategy"] == "高标首阴_V51") & (day_cands["score"] >= th_h)]
        c_3 = day_cands[(day_cands["strategy"] == "三进四_V34") & (day_cands["score"] >= th_3)]
        c_1 = day_cands[(day_cands["strategy"] == "一进二_V18") & (day_cands["score"] >= day_cands["base_threshold"] + th_1)]
        
        pool_pass = pd.concat([c_h, c_3, c_1], ignore_index=True) if (not c_h.empty or not c_3.empty or not c_1.empty) else pd.DataFrame()
        if pool_pass.empty: return None
        
        # 顺位按标准化得分择优
        z_scores = []
        for r in pool_pass.itertuples():
            if r.strategy == "高标首阴_V51": z = (r.score - 88.0) / std_h + 0.50
            elif r.strategy == "三进四_V34": z = (r.score - 90.0) / std_3 + 0.25
            else: z = (r.score - float(r.base_threshold)) / std_1
            z_scores.append(z)
        pool_pass["z_comp"] = z_scores
        return pool_pass.sort_values(["z_comp", "buy_hhmm"], ascending=[False, True]).iloc[0].to_dict()
    return fn

p_m1_w40 = get_perf_stats(sim_engine(df_all, make_fn_m1(40, True, False)))
p_m1_w20 = get_perf_stats(sim_engine(df_all, make_fn_m1(20, True, False)))
p_m1_w60 = get_perf_stats(sim_engine(df_all, make_fn_m1(60, True, False)))

# --- 3. 机制 M2: D-1 宏观生态温度计 ---
def make_fn_m2(tight_bear=3.0):
    def fn(d, day_cands, history):
        cur_idx = dt_to_idx.get(d, 0)
        idx_prev = max(0, cur_idx - 1)
        idx_20 = max(0, cur_idx - 21)
        d_prev = trading_days[idx_prev]
        d_20 = trading_days[idx_20]
        csi_20d = sh300_daily[d_prev] / sh300_daily[d_20] - 1.0
        
        th_h, th_3, th_1 = 88.0, 90.0, 0.0
        # 当大盘处于下跌抱团期 (csi_20d < -0.02) 时，三进四加速容易断板，收紧三进四门槛
        if csi_20d < -0.02:
            th_3 += tight_bear
            
        c_h = day_cands[(day_cands["strategy"] == "高标首阴_V51") & (day_cands["score"] >= th_h)]
        c_3 = day_cands[(day_cands["strategy"] == "三进四_V34") & (day_cands["score"] >= th_3)]
        c_1 = day_cands[(day_cands["strategy"] == "一进二_V18") & (day_cands["score"] >= day_cands["base_threshold"] + th_1)]
        
        pool_pass = pd.concat([c_h, c_3, c_1], ignore_index=True) if (not c_h.empty or not c_3.empty or not c_1.empty) else pd.DataFrame()
        if pool_pass.empty: return None
        
        z_scores = []
        for r in pool_pass.itertuples():
            if r.strategy == "高标首阴_V51": z = (r.score - 88.0) / std_h + 0.50
            elif r.strategy == "三进四_V34": z = (r.score - 90.0) / std_3 + 0.25
            else: z = (r.score - float(r.base_threshold)) / std_1
            z_scores.append(z)
        pool_pass["z_comp"] = z_scores
        return pool_pass.sort_values(["z_comp", "buy_hhmm"], ascending=[False, True]).iloc[0].to_dict()
    return fn

p_m2_t3 = get_perf_stats(sim_engine(df_all, make_fn_m2(3.0)))
p_m2_t5 = get_perf_stats(sim_engine(df_all, make_fn_m2(5.0)))

# --- 4. 机制 M3: M1 + M2 综合贝叶斯收缩专供卡 ---
def make_fn_m3(W_days=40, tight_bear=3.0):
    def fn(d, day_cands, history):
        cur_idx = dt_to_idx.get(d, 0)
        idx_prev = max(0, cur_idx - 1)
        idx_20 = max(0, cur_idx - 21)
        csi_20d = sh300_daily[trading_days[idx_prev]] / sh300_daily[trading_days[idx_20]] - 1.0
        
        past_closed = [t for t in history if t["exit_date"] < d and (cur_idx - dt_to_idx.get(t["exit_date"], 0)) <= W_days]
        
        th_h, th_3, th_1 = 88.0, 90.0, 0.0
        # 1. 宏观温度避险
        if csi_20d < -0.02:
            th_3 += tight_bear
            
        # 2. 纸面连亏避险
        s_tr_3 = [t for t in past_closed if t["strategy"] == "三进四_V34"]
        if len(s_tr_3) >= 2 and s_tr_3[-1]["net_ret"] < 0 and s_tr_3[-2]["net_ret"] < 0:
            th_3 += 2.0
            
        s_tr_1 = [t for t in past_closed if t["strategy"] == "一进二_V18"]
        if len(s_tr_1) >= 2 and s_tr_1[-1]["net_ret"] < 0 and s_tr_1[-2]["net_ret"] < 0:
            th_1 += 6.0
            
        c_h = day_cands[(day_cands["strategy"] == "高标首阴_V51") & (day_cands["score"] >= th_h)]
        c_3 = day_cands[(day_cands["strategy"] == "三进四_V34") & (day_cands["score"] >= th_3)]
        c_1 = day_cands[(day_cands["strategy"] == "一进二_V18") & (day_cands["score"] >= day_cands["base_threshold"] + th_1)]
        
        pool_pass = pd.concat([c_h, c_3, c_1], ignore_index=True) if (not c_h.empty or not c_3.empty or not c_1.empty) else pd.DataFrame()
        if pool_pass.empty: return None
        
        z_scores = []
        for r in pool_pass.itertuples():
            if r.strategy == "高标首阴_V51": z = (r.score - 88.0) / std_h + 0.50
            elif r.strategy == "三进四_V34": z = (r.score - 90.0) / std_3 + 0.25
            else: z = (r.score - float(r.base_threshold)) / std_1
            z_scores.append(z)
        pool_pass["z_comp"] = z_scores
        return pool_pass.sort_values(["z_comp", "buy_hhmm"], ascending=[False, True]).iloc[0].to_dict()
    return fn

p_m3 = get_perf_stats(sim_engine(df_all, make_fn_m3(40, 3.0)))

# 汇总打印对比
print("\n" + "=" * 115)
print(f"{'方案名称':<32s} | {'2026-10+':<15s} | {'2026-07+':<15s} | {'2026全年':<17s} | {'2021-2025(Train)':<18s} | {'全五年5Y':<18s}")
print("=" * 115)

cases = [
    ("基准:静态五年基础版(严格09:26)", p_base),
    ("M1:滚动纸面动量温度计(W=40)", p_m1_w40),
    ("M1:滚动纸面动量温度计(W=20)", p_m1_w20),
    ("M1:滚动纸面动量温度计(W=60)", p_m1_w60),
    ("M2:宏观温度计避险(大盘<-2%收紧3)", p_m2_t3),
    ("M2:宏观温度计避险(大盘<-2%收紧5)", p_m2_t5),
    ("M3:综合贝叶斯收缩专供卡(M1+M2)", p_m3)
]

for label, p in cases:
    s10 = f"{p['m10']['n']}b/{p['m10']['wr']}%/{p['m10']['nav']}x"
    s07 = f"{p['m07']['n']}b/{p['m07']['wr']}%/{p['m07']['nav']}x"
    s26 = f"{p['y2026']['n']}b/{p['y2026']['wr']}%/{p['y2026']['nav']}x"
    strain = f"{p['train']['n']}b/{p['train']['wr']}%/均益{p['train']['mean']:+.2f}%"
    s5y = f"{p['n']}b/1000万+{p['cap_ret']}%"
    print(f"{label:<32s} | {s10:<15s} | {s07:<15s} | {s26:<17s} | {strain:<18s} | {s5y:<18s}")

print("=" * 115)
