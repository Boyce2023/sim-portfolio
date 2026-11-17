#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
test_true_walkforward.py
从 full_candidates_3main_5y.pkl 运行真实无遮蔽、严格 09:26 唯一挂单口径下的基准与滚动当季专供机制
"""
import pickle, json, sys, os
import pandas as pd, numpy as np

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CLEAN = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
LAB_DIR = f"{CLEAN}/scientific_seasonal_lab"
sys.path.insert(0, CLEAN)

# 1. 载入指数行情
with open(f"{SANDBOX}/index_klines_5y_cache.json", "r", encoding="utf-8") as f:
    sh300_daily = json.load(f)["sh000300"]
trading_days = sorted(sh300_daily.keys())
dt_to_idx = {d: i for i, d in enumerate(trading_days)}

# 2. 载入 5 年全量无遮蔽候选池
with open(f"{LAB_DIR}/full_candidates_3main_5y.pkl", "rb") as f:
    full_pool = pickle.load(f)

cands_hd = full_pool["high_dragon"]
cands_34 = full_pool["3to4"]
cands_12 = full_pool["1to2"]

df_all = pd.DataFrame(cands_hd + cands_34 + cands_12)
df_all.sort_values(["buy_date", "strategy", "score"], ascending=[True, True, False], inplace=True)
all_trade_dates = sorted([d for d in df_all["buy_date"].unique() if "2021-11-15" <= d <= "2026-11-16"])

print(f"全量候选池载入完成: 总记录 {len(df_all)} 条, 覆盖 {len(all_trade_dates)} 个交易日")

# 辅助绩效评估函数
def eval_perf(trades, label):
    if not trades:
        print(f"{label}: 0 笔交易")
        return
    df = pd.DataFrame(trades)
    rets = df["net_ret"].values
    n = len(rets)
    wr = np.mean(rets > 0) * 100
    nav = np.prod(1.0 + rets)
    mdd = 0.0; cur, pk = 1.0, 1.0
    for r in rets:
        cur *= (1.0 + r); pk = max(pk, cur); mdd = max(mdd, (pk - cur) / pk)
    # 1000万封顶实盘单利
    cap = 1000.0
    for r in rets:
        cap += min(cap, 1000.0) * float(r)
    cap_ret = (cap / 1000.0 - 1.0) * 100.0
    
    # 拆分窗口
    def sub_stat(s_d, e_d):
        sub = df[(df["buy_date"] >= s_d) & (df["buy_date"] <= e_d)]
        if sub.empty: return "0b/0.0%/1.0x"
        r = sub["net_ret"].values
        return f"{len(r):2d}b/{np.mean(r>0)*100:4.1f}%/NAV={np.prod(1+r):6.2f}x/均益={np.mean(r)*100:+.2f}%"

    print(f"\n[{label}] (全5年 N={n}, 胜率={wr:.1f}%, NAV={nav:.1f}x, 封顶单利=+{cap_ret:.1f}%, MDD={mdd*100:.1f}%):")
    print(f"  2021-2025(Train) : {sub_stat('2021-11-15', '2025-12-31')}")
    print(f"  2026全年          : {sub_stat('2026-01-01', '2026-11-16')}")
    print(f"  2026年7月以来     : {sub_stat('2026-07-01', '2026-11-16')}")
    print(f"  2026年10月以来    : {sub_stat('2026-10-01', '2026-11-16')}")

# ==============================================================================
# 基准 A: 静态五年基础版 · 严格 09:26 唯一挂单规则 (未触发即当天弃权空仓)
# ==============================================================================
def sim_strict_0926(df_candidates, get_daily_target_fn):
    """
    空仓日严格在 09:25:03 由 get_daily_target_fn 选定唯一目标
    若该目标 triggered == True 则成交持仓至 exit_date
    若 triggered == False 则 11:30 撤单当天保持空仓，绝不买入同日次选！
    """
    picked_trades = []
    free_date = ""
    free_hhmm = 0
    
    dates = sorted(df_candidates["buy_date"].unique())
    for d in dates:
        # 1. 检查今日是否有旧仓占用
        if free_date != "" and d < free_date:
            continue
        # 2. 检查今日是否为早盘接力
        allowed_hhmm = 0
        if free_date != "" and d == free_date:
            if free_hhmm > 925:
                # 盘中或尾盘卖出，今日不开新仓
                continue
            allowed_hhmm = 930
            
        day_cands = df_candidates[df_candidates["buy_date"] == d].copy()
        if day_cands.empty:
            continue
            
        # 若是同日早盘接力，只看 09:30 以后成交的标的
        if allowed_hhmm > 0:
            day_cands = day_cands[day_cands["buy_hhmm"] >= allowed_hhmm]
            if day_cands.empty:
                continue
                
        # 3. 由决策函数在 09:25:03 给出唯一目标
        target = get_daily_target_fn(d, day_cands, picked_trades)
        if target is None:
            continue
            
        # 4. 判断该目标是否触发真实撮合成交
        if target["triggered"]:
            picked_trades.append(target)
            free_date = str(target["exit_date"])
            free_hhmm = int(target["exit_hhmm"])
        else:
            # 严格实盘：该标的盘中未突破触发，挂单撤回，当天保持空仓！
            pass
            
    return picked_trades

# 1. 基准实现: 静态五年基础版 (高标88 > 三进四90 > 一进二304.8)
def base_rule(d, day_cands, closed_history):
    # 静态门槛
    c_h = day_cands[(day_cands["strategy"] == "高标首阴_V51") & (day_cands["score"] >= 88.0)]
    if not c_h.empty:
        return c_h.sort_values("score", ascending=False).iloc[0].to_dict()
    c_3 = day_cands[(day_cands["strategy"] == "三进四_V34") & (day_cands["score"] >= 90.0)]
    if not c_3.empty:
        return c_3.sort_values("score", ascending=False).iloc[0].to_dict()
    c_1 = day_cands[(day_cands["strategy"] == "一进二_V18") & (day_cands["score"] >= day_cands["base_threshold"])]
    if not c_1.empty:
        return c_1.sort_values("score", ascending=False).iloc[0].to_dict()
    return None

trades_base_strict = sim_strict_0926(df_all, base_rule)
eval_perf(trades_base_strict, "基准:静态五年基础版(严格09:26唯一挂单)")

# 同时对比既有台账
df_orig = pd.read_csv(f"{CLEAN}/ledger_base_combined_3main.csv")
eval_perf(df_orig.to_dict("records"), "既有总账:ledger_base_combined_3main.csv")
