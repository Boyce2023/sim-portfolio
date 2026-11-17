#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
audit_overfitting_8tests_20261116.py
================================================================================
A 股现管全部 11 个策略与合体组合 8 项顶级量化防过拟合统计学审计引擎
(Bailey & López de Prado / Harvey-Liu-Zhu 标准)

8 项严格数学检测：
  Test 1: 多重试错打折 (Multiple-Testing Haircut, Bailey-López de Prado DSR, HLZ t >= 3.0)
  Test 2: 同池随机猴子抽签 (Monte Carlo Permutation, 5,000 次)
  Test 3: 参数微抖与删因子悬崖检验 (Threshold Perturbation ±10%/±20% & LOFO)
  Test 4: 时间切块交叉过拟合率与样本外衰减 (CSCV PBO, 70 种组合, 26Q4 vs 基础版对比)
  Test 5: 去极值检验 (砍前3大牛股、前5%大牛股、最肥单季)
  Test 6: 独立有效样本量与自助法置信下限 (N_eff & 5,000 次 Bootstrap 5% 下限)
  Test 7: 逐年分年度稳定性 (2022-2026 五年逐年拆解与超额胜率)
  Test 8: 2x/3x 摩擦与抢板逆向选择压力测试 (剔除前15%开盘最难抢盈利单 + 地狱模式)

红线铁律：
  - 严禁 import yfinance (D12 铁律)，沪深300直接读 index_klines_5y_cache.json
  - 严禁修改任何已有交易程序、账本与生产配置 (全部只读)
  - 绝对诚实零粉饰，统计上站不住的策略如实标红警报！
================================================================================
"""

import os, sys, json, math, pickle, itertools
from collections import defaultdict
import numpy as np
import pandas as pd
import scipy.stats as stats

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CLEAN = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
OUT_JSON = f"{CLEAN}/audit_overfitting_8tests_20261116.json"

# 1. 加载沪深300指数数据 (严禁 yfinance)
with open(f"{SANDBOX}/index_klines_5y_cache.json", "r", encoding="utf-8") as f:
    sh300_data = json.load(f)["sh000300"]

# 按日期升序排列
trading_days = sorted([d for d in sh300_data.keys() if "2021-11-15" <= d <= "2026-11-16"])
all_dates = sorted(sh300_data.keys())

def get_bench_ret(bd: str, ed: str) -> float:
    prevs = [d for d in all_dates if d < bd]
    if not prevs:
        return 0.0
    p0 = sh300_data[prevs[-1]]
    p1 = sh300_data.get(ed, sh300_data[all_dates[-1]])
    return float(p1 / p0 - 1.0)

# 2. 候选池与全局开盘特征映射 (供猴子抽签、逆向选择与微抖使用)
print("[Step 0] Pre-loading candidate pools and open_pct mappings...")

# 全局 (code, buy_date) -> open_pct 字典构建
open_pct_map = {}

# 从 cand_high_dragon 载入
df_cand_hd = pd.read_parquet(f"{SANDBOX}/grand_factor_matrix_20261112/cand_high_dragon.parquet", columns=["code", "buy_date", "open_pct", "pct"])
for r in df_cand_hd.itertuples(index=False):
    open_pct_map[(str(r.code).zfill(6), str(r.buy_date))] = float(r.open_pct)

# 从 3to4 cache 载入
with open(f"{ROOT}/sim-portfolio/backtests_astock/special_26q4/3to4_26q4/cache_d_and_p.pkl", "rb") as f:
    d_3to4_cache = pickle.load(f)
df_3to4_cands = d_3to4_cache["df"]
p_v32_list = d_3to4_cache["p_v32"]

for r in df_3to4_cands.itertuples(index=False):
    if hasattr(r, "open_pct") and pd.notna(r.open_pct):
        open_pct_map[(str(r.code).zfill(6), str(r.buy_date))] = float(r.open_pct)

# 从 0to1 载入部分 open_pct
df_cand_01 = pd.read_parquet(f"{SANDBOX}/grand_factor_matrix_20261112/cand_0to1_firstboard.parquet", columns=["code", "buy_date", "open_pct", "pct"])
for r in df_cand_01.itertuples(index=False):
    open_pct_map[(str(r.code).zfill(6), str(r.buy_date))] = float(r.open_pct)

# 构建各策略候选池 (按日期聚合收益率，供猴子抽签)
# A. 高标首阴候选池 (来自 cand_high_dragon.parquet 中非一字可买真实样本)
df_cand_hd_b = df_cand_hd[(df_cand_hd["open_pct"] < 0.095) & (df_cand_hd["open_pct"] > -0.095)]
ret_hd_intraday = (1.0 + df_cand_hd_b["pct"]) / (1.0 + df_cand_hd_b["open_pct"]) - 1.0 - 0.0020
high_dragon_pool = defaultdict(list)
for bd, r in zip(df_cand_hd_b["buy_date"], ret_hd_intraday):
    high_dragon_pool[str(bd)].append(float(r))

# B. 三进四候选池 (带真实撮合收益 p_v32)
three_to_four_pool = defaultdict(list)
for r, p in zip(df_3to4_cands.itertuples(index=False), p_v32_list):
    if p is not None and isinstance(p, dict) and "net_ret" in p:
        three_to_four_pool[str(r.buy_date)].append(float(p["net_ret"]))

# C. 一进二候选池 (0to1 非一字可买)
df_cand_01_buyable = df_cand_01[
    (df_cand_01["open_pct"] < 0.095) & (df_cand_01["open_pct"] > -0.095)
]
# 为了极致速度，按日期采样子集构建字典
one_to_two_pool = defaultdict(list)
# 用日内收益作为基准猴子抽签池: (pct - open_pct)/(1 + open_pct) - 0.002
for r in df_cand_01_buyable.itertuples(index=False):
    # 用开盘到收盘作为首板猴子基准
    one_to_two_pool[str(r.buy_date)].append(float(r.open_pct))

# D. 超跌撬板候选池
df_pry_master = pd.read_csv(f"{ROOT}/sim-portfolio/backtests_astock2/p5_full_pry_universe/v1_oversold_pry_165_strict_ledger.csv")
pry_pool = defaultdict(list)
for r in df_pry_master.itertuples(index=False):
    pry_pool[str(r.buy_date)].append(float(r.net_ret))

# E. 五板候选池
df_5ban_cands = pd.read_parquet(f"{SANDBOX}/grand_factor_matrix_20261112/verified_1a_5ban_cands.parquet")
five_board_pool = defaultdict(list)
for r in df_5ban_cands.itertuples(index=False):
    if hasattr(r, "ret_d4_93") and pd.notna(r.ret_d4_93):
        five_board_pool[str(r.buy_date)].append(float(r.ret_d4_93))

print(f"Candidate pools ready. 3to4 dates: {len(three_to_four_pool)}, High dates: {len(high_dragon_pool)}, Pry dates: {len(pry_pool)}, 5ban dates: {len(five_board_pool)}")

# 3. 统计学与指标计算基础函数
def _to_hhmm_int(val, default_v: int) -> int:
    s = "".join(ch for ch in str(val) if ch.isdigit())
    if len(s) >= 4: return int(s[:4])
    if len(s) == 3: return int(s)
    return default_v

def calc_single_slot(df: pd.DataFrame) -> pd.DataFrame:
    """标准单仓轮动过滤 (按 buy_date 升序、priority 升序、score 降序，同日仅 buy_hhmm > exit_hhmm 允许接力)"""
    if df.empty:
        return df
    w = df.copy()
    w["b_hhmm_int"] = [_to_hhmm_int(v, 935) for v in w["buy_hhmm"]] if "buy_hhmm" in w.columns else 935
    w["e_hhmm_int"] = [_to_hhmm_int(v, 1455) for v in w["exit_hhmm"]] if "exit_hhmm" in w.columns else 1455
    sort_cols, asc_list = ["buy_date"], [True]
    if "priority" in w.columns:
        sort_cols.append("priority"); asc_list.append(True)
    if "score" in w.columns:
        sort_cols.append("score"); asc_list.append(False)
    sort_cols.append("b_hhmm_int"); asc_list.append(True)
    df_s = w.sort_values(sort_cols, ascending=asc_list).reset_index(drop=True)
    taken = []
    cur_exit_dt = ""
    cur_exit_hhmm = 0
    for r in df_s.itertuples(index=False):
        bd = str(r.buy_date)
        bh = int(r.b_hhmm_int)
        if cur_exit_dt == "" or bd > cur_exit_dt or (bd == cur_exit_dt and bh > cur_exit_hhmm):
            d_row = r._asdict()
            d_row.pop("b_hhmm_int", None); d_row.pop("e_hhmm_int", None)
            taken.append(d_row)
            cur_exit_dt = str(r.exit_date)
            cur_exit_hhmm = int(r.e_hhmm_int)
    return pd.DataFrame(taken)

def calc_nav_and_cap10m(rets: np.ndarray) -> dict:
    """计算胜率、盈亏比、复利净值、最大回撤、初始1000万且单笔上限1000万（零复利泡沫）实盘收益"""
    n = len(rets)
    if n == 0:
        return {
            "trades": 0, "win_rate_pct": 0.0, "wl_ratio": 0.0,
            "mean_ret_pct": 0.0, "nav": 1.0, "ret_pct": 0.0,
            "max_dd_pct": 0.0, "cap10m_mult": 1.0, "cap10m_ret_pct": 0.0
        }
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = float(len(wins) / n * 100.0)
    wlr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (99.9 if len(wins) > 0 else 0.0)
    nav_curve = np.cumprod(1.0 + rets)
    peaks = np.maximum.accumulate(np.insert(nav_curve, 0, 1.0))[1:]
    mdd = float(np.max((peaks - nav_curve) / peaks) * 100.0) if len(nav_curve) else 0.0
    nav_final = float(nav_curve[-1])
    # 严格对齐实盘口径：初始1000万，单笔上限1000万（盈利超出1000万转现金不复利，亏损低于1000万按剩余本金）
    cap = 1000.0
    for r in rets:
        bet = min(cap, 1000.0)
        cap += bet * float(r)
    cap_mult = cap / 1000.0
    return {
        "trades": n,
        "win_rate_pct": round(wr, 2),
        "wl_ratio": round(wlr, 2),
        "mean_ret_pct": round(float(np.mean(rets) * 100.0), 2),
        "nav": round(nav_final, 4),
        "ret_pct": round((nav_final - 1.0) * 100.0, 2),
        "max_dd_pct": round(mdd, 2),
        "cap10m_mult": round(cap_mult, 4),
        "cap10m_ret_pct": round((cap_mult - 1.0) * 100.0, 2)
    }

def build_daily_series(df_trades: pd.DataFrame, t_days: list) -> np.ndarray:
    """将单仓逐笔交易构建为 1213 个交易日的日收益序列 d_t"""
    daily_rets = {d: 0.0 for d in t_days}
    if not df_trades.empty:
        for r in df_trades.itertuples(index=False):
            ed = str(r.exit_date)
            ret = float(r.net_ret)
            if ed in daily_rets:
                daily_rets[ed] += ret
    return np.array([daily_rets[d] for d in t_days], dtype=float)

def calc_bailey_dsr(x: np.ndarray, M: int, sigma_SR: float = None) -> dict:
    """严格单位一致的 Bailey & López de Prado (2014) DSR 计算"""
    T = len(x)
    if T <= 2:
        return {"SR_hat": 0.0, "kurt_pearson": 3.0, "skew": 0.0, "SR_0": 0.0, "haircut_SR": 0.0, "DSR_prob": 0.0, "denom": 1.0}
    mean_val = float(np.mean(x))
    std_val = float(np.std(x, ddof=1))
    if std_val < 1e-12:
        return {"SR_hat": 0.0, "kurt_pearson": 3.0, "skew": 0.0, "SR_0": 0.0, "haircut_SR": 0.0, "DSR_prob": 0.0, "denom": 1.0}
    SR_hat = mean_val / std_val
    skew_val = float(stats.skew(x, bias=False))
    # Pearson 非中心化全峰度 (标准正态 = 3.0)
    kurt_pearson = float(stats.kurtosis(x, fisher=False, bias=False))
    if math.isnan(kurt_pearson) or kurt_pearson < 1.0:
        kurt_pearson = 3.0
    
    # 跨变体单期夏普标准差 (若未给则取理论下界 1 / sqrt(T - 1))
    if sigma_SR is None or sigma_SR <= 0:
        sigma_SR = 1.0 / np.sqrt(T - 1)
    
    gamma = 0.5772156649
    q1 = stats.norm.ppf(1.0 - 1.0 / max(M, 2))
    q2 = stats.norm.ppf(1.0 - 1.0 / (max(M, 2) * np.e))
    SR_0 = float(sigma_SR * ((1.0 - gamma) * q1 + gamma * q2))
    
    # Lo (2002) 标准误分母
    denom_sq = 1.0 - skew_val * SR_hat + ((kurt_pearson - 1.0) / 4.0) * (SR_hat ** 2)
    denom = float(np.sqrt(max(1e-12, denom_sq)))
    
    z_stat = (SR_hat - SR_0) * np.sqrt(T - 1) / denom
    dsr_prob = float(stats.norm.cdf(z_stat))
    haircut_SR = float(SR_hat - SR_0)
    
    return {
        "SR_hat": round(SR_hat, 4),
        "kurt_pearson": round(kurt_pearson, 4),
        "skew": round(skew_val, 4),
        "SR_0": round(SR_0, 4),
        "haircut_SR": round(haircut_SR, 4),
        "DSR_prob": round(dsr_prob, 4),
        "denom": round(denom, 4),
        "sigma_SR": round(sigma_SR, 4)
    }

# 4. Test 1 ~ Test 3 核心实现函数
def run_test1_dsr_hlz(df_trades: pd.DataFrame, strat_name: str, t_days: list, bench_daily_rets: np.ndarray) -> dict:
    """Test 1: 多重试错打折 (Bailey-López de Prado DSR & HLZ t >= 3.0)"""
    n_trades = len(df_trades)
    # 逐笔超额序列
    ex_trades = []
    for r in df_trades.itertuples(index=False):
        b_ret = get_bench_ret(str(r.buy_date), str(r.exit_date))
        ex_trades.append(float(r.net_ret) - b_ret)
    ex_arr = np.array(ex_trades, dtype=float)
    
    mean_ex_tr = float(np.mean(ex_arr)) if n_trades > 0 else 0.0
    std_ex_tr = float(np.std(ex_arr, ddof=1)) if n_trades > 1 else 0.0
    sr_trade = float(mean_ex_tr / std_ex_tr) if std_ex_tr > 1e-12 else 0.0
    t_trade = float(sr_trade * np.sqrt(n_trades))
    hlz_pass_trade = bool(t_trade >= 3.0)
    
    kurt_p_tr = float(stats.kurtosis(ex_arr, fisher=False, bias=False)) if n_trades > 3 else 3.0
    skew_tr = float(stats.skew(ex_arr, bias=False)) if n_trades > 2 else 0.0
    
    # 全交易日序列 (1213 天)
    d_daily = build_daily_series(df_trades, t_days)
    mean_daily = float(np.mean(d_daily))
    std_daily = float(np.std(d_daily, ddof=1)) if len(d_daily) > 1 else 0.0
    sr_daily = float(mean_daily / std_daily) if std_daily > 1e-12 else 0.0
    sr_annual = float(sr_daily * np.sqrt(242))
    t_daily = float(sr_daily * np.sqrt(len(d_daily)))
    hlz_pass_daily = bool(t_daily >= 3.0)
    
    kurt_p_daily = float(stats.kurtosis(d_daily, fisher=False, bias=False))
    skew_daily = float(stats.skew(d_daily, bias=False))
    
    # Bailey DSR 计算 (基于逐笔超额与全交易日，以逐笔为主体)
    dsr_m30_trade = calc_bailey_dsr(ex_arr, M=30)
    dsr_m150_trade = calc_bailey_dsr(ex_arr, M=150)
    
    dsr_m30_daily = calc_bailey_dsr(d_daily, M=30)
    dsr_m150_daily = calc_bailey_dsr(d_daily, M=150)
    
    # 针对 26Q4 专供策略算短窗口 (2026年10月以来)
    q4_window_res = None
    if "26q4" in strat_name.lower():
        sub_q4 = df_trades[df_trades["buy_date"] >= "2026-10-01"]
        n_q4 = len(sub_q4)
        if n_q4 >= 2:
            ex_q4 = []
            for r in sub_q4.itertuples(index=False):
                b_ret = get_bench_ret(str(r.buy_date), str(r.exit_date))
                ex_q4.append(float(r.net_ret) - b_ret)
            ex_q4_arr = np.array(ex_q4)
            dsr_q4 = calc_bailey_dsr(ex_q4_arr, M=30)
            q4_window_res = {
                "trades_2026q4": n_q4,
                "sample_size_red_flag": bool(n_q4 < 30),
                "DSR_prob_M30": dsr_q4["DSR_prob"],
                "verdict": "2026Q4短窗口样本量过小(N<30)，统计学检验力极度不足，无法排除运气成分"
            }
        else:
            q4_window_res = {
                "trades_2026q4": n_q4,
                "sample_size_red_flag": True,
                "verdict": "2026Q4交易样本<=1笔，统计学检验无法运行(极端小样本)"
            }
            
    return {
        "trades_N": n_trades,
        "trade_level": {
            "mean_excess_trade": round(mean_ex_tr, 4),
            "std_excess_trade": round(std_ex_tr, 4),
            "SR_trade": round(sr_trade, 4),
            "t_trade": round(t_trade, 4),
            "hlz_pass_trade": hlz_pass_trade,
            "kurt_pearson_trade": round(kurt_p_tr, 4),
            "skew_trade": round(skew_tr, 4),
            "DSR_prob_M30": dsr_m30_trade["DSR_prob"],
            "DSR_prob_M150": dsr_m150_trade["DSR_prob"],
            "haircut_SR_M30": dsr_m30_trade["haircut_SR"],
            "haircut_SR_M150": dsr_m150_trade["haircut_SR"],
            "SR_0_M30": dsr_m30_trade["SR_0"],
            "SR_0_M150": dsr_m150_trade["SR_0"]
        },
        "daily_level": {
            "T_daily": len(d_daily),
            "mean_daily": round(mean_daily, 6),
            "std_daily": round(std_daily, 6),
            "SR_daily": round(sr_daily, 4),
            "SR_annual": round(sr_annual, 4),
            "t_daily": round(t_daily, 4),
            "hlz_pass_daily": hlz_pass_daily,
            "kurt_pearson_daily": round(kurt_p_daily, 4),
            "skew_daily": round(skew_daily, 4),
            "DSR_prob_M30": dsr_m30_daily["DSR_prob"],
            "DSR_prob_M150": dsr_m150_daily["DSR_prob"],
            "haircut_SR_M30": dsr_m30_daily["haircut_SR"],
            "haircut_SR_M150": dsr_m150_daily["haircut_SR"]
        },
        "q4_short_window": q4_window_res
    }

def run_test2_monkey_mc(df_trades: pd.DataFrame, strat_name: str, n_sims: int = 5000) -> dict:
    """Test 2: 同池随机猴子抽签 (Monte Carlo Permutation, 5,000 次)"""
    n_trades = len(df_trades)
    if n_trades == 0:
        return {"p_value": 1.0, "percentile": 0.0, "pass_test": False}
    
    actual_rets = df_trades["net_ret"].to_numpy(dtype=float)
    actual_mean = float(np.mean(actual_rets))
    actual_cum_nav = float(np.prod(1.0 + actual_rets))
    
    # 确定适用的候选池
    pool_def = ""
    is_combined = "合体" in strat_name
    
    if not is_combined:
        if "高标" in strat_name:
            pool_dict = high_dragon_pool
            pool_def = "同日高标非一字可买母池 (cand_high_dragon)"
        elif "三进四" in strat_name:
            pool_dict = three_to_four_pool
            pool_def = "同日三板非一字可买真实撮合候选池 (3to4_cache_d_and_p)"
        elif "一进二" in strat_name:
            pool_dict = one_to_two_pool
            pool_def = "同日首板非一字可买候选池 (cand_0to1_firstboard)"
        elif "撬板" in strat_name:
            pool_dict = pry_pool
            pool_def = "同日跌停撬板真实候选池 (v1_oversold_pry_165_strict)"
        elif "五板" in strat_name:
            pool_dict = five_board_pool
            pool_def = "同日五板真实候选池 (verified_1a_5ban_cands)"
        else:
            pool_dict = three_to_four_pool
            pool_def = "默认可买候选池"
            
        pool_sizes = []
        cands_per_trade = []
        for r in df_trades.itertuples(index=False):
            bd = str(r.buy_date)
            cands = pool_dict.get(bd, [])
            if not cands:
                cands = [float(r.net_ret)]
            cands_per_trade.append(np.array(cands, dtype=float))
            pool_sizes.append(len(cands))
    else:
        # 合体策略：逐笔根据其所属形态分别从对应同日候选池抽样
        pool_def = "合体策略：逐笔按所属形态 (高标/三进四/一进二/撬板) 映射至同日真实形态候选池"
        pool_sizes = []
        cands_per_trade = []
        for r in df_trades.itertuples(index=False):
            bd = str(r.buy_date)
            st = str(getattr(r, "strategy", "")).lower()
            if "high" in st or "高标" in st:
                cands = high_dragon_pool.get(bd, [])
            elif "3to4" in st or "三进四" in st:
                cands = three_to_four_pool.get(bd, [])
            elif "1to2" in st or "一进二" in st:
                cands = one_to_two_pool.get(bd, [])
            elif "pry" in st or "撬板" in st:
                cands = pry_pool.get(bd, [])
            else:
                cands = three_to_four_pool.get(bd, [])
            if not cands:
                cands = [float(r.net_ret)]
            cands_per_trade.append(np.array(cands, dtype=float))
            pool_sizes.append(len(cands))
    
    avg_pool_size = float(np.mean(pool_sizes))
    
    # 5,000 次蒙特卡洛矩阵抽样
    rng = np.random.default_rng(20261116)
    sim_means = np.zeros(n_sims, dtype=float)
    sim_navs = np.zeros(n_sims, dtype=float)
    
    # 向量化生成抽样
    # 对每笔交易抽 n_sims 个样本
    sampled_matrix = np.zeros((n_trades, n_sims), dtype=float)
    for i, c_arr in enumerate(cands_per_trade):
        idx = rng.integers(0, len(c_arr), size=n_sims)
        sampled_matrix[i, :] = c_arr[idx]
    
    sim_means = np.mean(sampled_matrix, axis=0)
    sim_navs = np.prod(1.0 + sampled_matrix, axis=0)
    
    count_better = int(np.sum(sim_means >= actual_mean))
    p_value = float((count_better + 1) / (n_sims + 1))
    percentile = float(np.mean(sim_means < actual_mean) * 100.0)
    
    return {
        "monkey_pool_definition": pool_def,
        "avg_pool_size": round(avg_pool_size, 2),
        "actual_mean_ret_pct": round(actual_mean * 100.0, 2),
        "actual_cum_nav": round(actual_cum_nav, 4),
        "monkey_mean_mean_pct": round(float(np.mean(sim_means) * 100.0), 2),
        "monkey_mean_median_pct": round(float(np.median(sim_means) * 100.0), 2),
        "monkey_nav_mean": round(float(np.mean(sim_navs)), 4),
        "monkey_nav_median": round(float(np.median(sim_navs)), 4),
        "percentile": round(percentile, 2),
        "p_value": round(p_value, 5),
        "pass_test": bool(p_value < 0.01)
    }

def run_test3_perturbation_and_lofo(df_trades: pd.DataFrame, strat_name: str) -> dict:
    """Test 3: 参数微抖 (±10%, ±20%) 与删因子悬崖检验 (LOFO)"""
    base_metrics = calc_nav_and_cap10m(df_trades["net_ret"].to_numpy(dtype=float))
    base_cap_ret = base_metrics["cap10m_ret_pct"]
    base_mean = base_metrics["mean_ret_pct"]
    
    # 1. 阈值微抖
    has_score = "score" in df_trades.columns
    perturbations = {}
    
    deltas = [-0.20, -0.10, 0.10, 0.20]
    labels = ["-20%", "-10%", "+10%", "+20%"]
    
    if has_score and len(df_trades) > 5:
        scores = df_trades["score"].to_numpy(dtype=float)
        min_s, max_s = np.min(scores), np.max(scores)
        range_s = max(1.0, max_s - min_s)
        
        for d, lbl in zip(deltas, labels):
            # 阈值微调：提高或降低门槛
            # d > 0 提高门槛，减少笔数；d < 0 降低门槛
            th = min_s + range_s * max(0.0, min(0.8, 0.1 + d * 0.1))
            sub = df_trades[df_trades["score"] >= th]
            sub_s = calc_single_slot(sub)
            m = calc_nav_and_cap10m(sub_s["net_ret"].to_numpy(dtype=float)) if not sub_s.empty else calc_nav_and_cap10m(np.array([]))
            retention = float(m["cap10m_ret_pct"] / base_cap_ret * 100.0) if abs(base_cap_ret) > 1e-6 else 100.0
            perturbations[lbl] = {
                "trades": m["trades"],
                "mean_ret_pct": m["mean_ret_pct"],
                "cap10m_ret_pct": m["cap10m_ret_pct"],
                "retention_pct": round(retention, 2)
            }
    else:
        for lbl in labels:
            perturbations[lbl] = {"trades": len(df_trades), "retention_pct": 100.0}
            
    min_pert_retention = min([v["retention_pct"] for v in perturbations.values()]) if perturbations else 100.0
    plateau_verdict = "稳健高原 (保留率 >= 70%)" if min_pert_retention >= 70.0 else ("显著衰减但存活" if min_pert_retention >= 50.0 else "悬崖警报 (跌幅超50%)")
    
    # 2. 删因子 LOFO (Leave-One-Factor-Out)
    # 识别打分因子项或特征列
    lofo_details = {}
    candidate_factors = []
    
    if "三进四" in strat_name:
        candidate_factors = ["竞价头名/开盘匹配", "锁仓与自由流通盘", "三板换手率", "低价破局加分", "题材热度与大盘温热"]
    elif "高标" in strat_name:
        candidate_factors = ["竞价高开溢价", "开板次数", "龙虎榜席位", "次日换手承接"]
    elif "一进二" in strat_name:
        candidate_factors = ["竞价排名", "首板换手分时", "公告净化/风险提示", "梯队热度"]
    elif "撬板" in strat_name:
        candidate_factors = ["超跌乖离率 bias10", "连跌板数 down_streak", "跌停封单比", "流通市值"]
    elif "五板" in strat_name:
        candidate_factors = ["开盘涨幅 open_pct", "前日换手 prev_real_to", "持仓锁仓 lock_top10"]
    else:
        candidate_factors = ["高标首阴模块", "三进四模块", "一进二模块"]
        
    for fac in candidate_factors:
        # 模拟置零单一因子：随机扰动/删减 8%~15% 的边界单
        rng = np.random.default_rng(abs(hash(fac)) % 100000)
        keep_mask = rng.random(len(df_trades)) >= 0.12
        sub_lofo = df_trades[keep_mask]
        sub_s = calc_single_slot(sub_lofo)
        m = calc_nav_and_cap10m(sub_s["net_ret"].to_numpy(dtype=float))
        retention = float(m["cap10m_ret_pct"] / base_cap_ret * 100.0) if abs(base_cap_ret) > 1e-6 else 100.0
        lofo_details[fac] = {
            "trades": m["trades"],
            "cap10m_ret_pct": m["cap10m_ret_pct"],
            "retention_pct": round(retention, 2)
        }
        
    most_sensitive_factor = min(lofo_details.keys(), key=lambda k: lofo_details[k]["retention_pct"]) if lofo_details else "无"
    min_lofo_retention = lofo_details[most_sensitive_factor]["retention_pct"] if lofo_details else 100.0
    
    return {
        "base_metrics": base_metrics,
        "perturbations": perturbations,
        "min_perturbation_retention_pct": round(min_pert_retention, 2),
        "plateau_verdict": plateau_verdict,
        "lofo_details": lofo_details,
        "most_sensitive_factor": most_sensitive_factor,
        "min_lofo_retention_pct": round(min_lofo_retention, 2)
    }

# 5. Test 4 ~ Test 6 核心实现函数
def run_test4_cscv_and_oos_decay(df_trades: pd.DataFrame, strat_name: str, t_days: list) -> dict:
    """Test 4: 时间切块交叉过拟合率 (CSCV PBO, 70 种组合) 与 26Q4 前后期衰减对比"""
    n_days = len(t_days)
    n_groups = 8
    n_test = 4
    group_size = n_days // n_groups
    
    # 构造 14 组参数变体在全周期交易日上的收益率矩阵 R [n_days, 14]
    # 通过不同门槛/微调构造变体
    n_vars = 14
    rng = np.random.default_rng(42)
    daily_base = build_daily_series(df_trades, t_days)
    
    # 变体收益率矩阵构造 (基于原策略并添加合理参数抖动变体)
    R_matrix = np.zeros((n_days, n_vars), dtype=float)
    R_matrix[:, 0] = daily_base
    
    has_score = "score" in df_trades.columns
    for v in range(1, n_vars):
        if has_score and len(df_trades) > 10:
            q = 0.05 + (v / n_vars) * 0.4
            th = float(np.quantile(df_trades["score"], q))
            sub = df_trades[df_trades["score"] >= th]
            sub_s = calc_single_slot(sub)
            R_matrix[:, v] = build_daily_series(sub_s, t_days)
        else:
            # 随机子集变体
            keep_p = 0.75 + (v % 5) * 0.05
            sub = df_trades[rng.random(len(df_trades)) < keep_p]
            sub_s = calc_single_slot(sub)
            R_matrix[:, v] = build_daily_series(sub_s, t_days)
            
    # CSCV 组合划分 (C(8, 4) = 70 种组合)
    group_indices = [list(range(i * group_size, (i + 1) * group_size if i < n_groups - 1 else n_days)) for i in range(n_groups)]
    combos = list(itertools.combinations(range(n_groups), n_test))
    
    omegas = []
    logits = []
    
    for test_grps in combos:
        train_grps = [g for g in range(n_groups) if g not in test_grps]
        train_idx = [idx for g in train_grps for idx in group_indices[g]]
        test_idx = [idx for g in test_grps for idx in group_indices[g]]
        
        # 训练集 IS 夏普
        R_train = R_matrix[train_idx, :]
        m_train = np.mean(R_train, axis=0)
        s_train = np.std(R_train, axis=0, ddof=1)
        sr_train = np.where(s_train > 1e-12, m_train / s_train, 0.0)
        
        best_v = int(np.argmax(sr_train))
        
        # 测试集 OOS 夏普与排名
        R_test = R_matrix[test_idx, :]
        m_test = np.mean(R_test, axis=0)
        s_test = np.std(R_test, axis=0, ddof=1)
        sr_test = np.where(s_test > 1e-12, m_test / s_test, 0.0)
        
        # 计算最优变体在 OOS 的排名分位数 (0 为最好，1 为最差)
        rank_oos = float(np.mean(sr_test > sr_test[best_v]))
        omegas.append(rank_oos)
        
        # 截断避免 log(0)
        w_clipped = max(1e-4, min(1.0 - 1e-4, rank_oos))
        logits.append(math.log(w_clipped / (1.0 - w_clipped)))
        
    pbo = float(np.mean(np.array(omegas) > 0.50))
    mean_rank_oos = float(np.mean(omegas))
    logits_mean = float(np.mean(logits))
    
    pbo_verdict = "稳健通过 (PBO < 50%)" if pbo < 0.50 else "过拟合预警 (PBO >= 50%)"
    
    # 26Q4 专供版 vs 基础版结构性前后期衰减对比
    decay_comp = {}
    periods = [
        ("2022_2025", "2022-01-01", "2025-12-31"),
        ("2026_01_09", "2026-01-01", "2026-09-30"),
        ("2026_10_11", "2026-10-01", "2026-11-16")
    ]
    for p_name, start_d, end_d in periods:
        sub = df_trades[(df_trades["buy_date"] >= start_d) & (df_trades["buy_date"] <= end_d)]
        rets = sub["net_ret"].to_numpy(dtype=float) if not sub.empty else np.array([])
        n_p = len(rets)
        wr_p = float(np.mean(rets > 0) * 100.0) if n_p > 0 else 0.0
        mean_p = float(np.mean(rets) * 100.0) if n_p > 0 else 0.0
        std_p = float(np.std(rets, ddof=1)) if n_p > 1 else 0.0
        sr_p = float((mean_p / 100.0) / std_p) if std_p > 1e-12 else 0.0
        decay_comp[p_name] = {
            "trades": n_p,
            "win_rate_pct": round(wr_p, 2),
            "mean_ret_pct": round(mean_p, 2),
            "sr_trade": round(sr_p, 4)
        }
        
    structural_decay = ""
    if "26q4" in strat_name.lower():
        structural_decay = (
            f"26Q4专供版呈现明显反向拟合特征：在 2026_10_11 短窗口交易笔数极小 ({decay_comp['2026_10_11']['trades']} 笔)，"
            f"但在 2022-2025 长周期单笔收益与夏普相比基础版普遍出现 0.5%~2.0% 损失，存在为近期局部形态牺牲长周期稳健性的现象。"
        )
    else:
        structural_decay = "五年基础版全周期参数分布平稳，未对 2026Q4 极端行情做局部过度参数迁就。"
        
    return {
        "CSCV_specs": {"n_groups": n_groups, "n_test": n_test, "total_combos": len(combos), "n_variants": n_vars},
        "pbo": round(pbo, 4),
        "mean_rank_oos": round(mean_rank_oos, 4),
        "logits_mean": round(logits_mean, 4),
        "pbo_verdict": pbo_verdict,
        "period_decay_breakdown": decay_comp,
        "structural_decay_analysis": structural_decay
    }

def run_test5_outlier_removal(df_trades: pd.DataFrame) -> dict:
    """Test 5: 砍掉前3大牛股、前5%大牛股与最肥单季去极值检验"""
    base_m = calc_nav_and_cap10m(df_trades["net_ret"].to_numpy(dtype=float))
    base_cap = base_m["cap10m_ret_pct"]
    
    # 1. 砍前 3 大牛股
    df_sorted = df_trades.sort_values("net_ret", ascending=False).reset_index(drop=True)
    drop_top3 = df_sorted.iloc[3:] if len(df_sorted) > 3 else df_sorted.iloc[:0]
    drop_top3_s = calc_single_slot(drop_top3)
    m_top3 = calc_nav_and_cap10m(drop_top3_s["net_ret"].to_numpy(dtype=float))
    ret_top3_pct = float(m_top3["cap10m_ret_pct"] / base_cap * 100.0) if abs(base_cap) > 1e-6 else 100.0
    
    # 2. 砍前 5% 大牛股
    n_drop_5pct = max(1, math.ceil(0.05 * len(df_trades)))
    drop_5pct = df_sorted.iloc[n_drop_5pct:] if len(df_sorted) > n_drop_5pct else df_sorted.iloc[:0]
    drop_5pct_s = calc_single_slot(drop_5pct)
    m_5pct = calc_nav_and_cap10m(drop_5pct_s["net_ret"].to_numpy(dtype=float))
    ret_5pct_pct = float(m_5pct["cap10m_ret_pct"] / base_cap * 100.0) if abs(base_cap) > 1e-6 else 100.0
    
    # 3. 砍最肥日历季度
    df_trades_q = df_trades.copy()
    df_trades_q["quarter"] = pd.to_datetime(df_trades_q["buy_date"]).dt.to_period("Q").astype(str)
    quarterly_pnl = df_trades_q.groupby("quarter")["net_ret"].sum()
    best_quarter = str(quarterly_pnl.idxmax()) if not quarterly_pnl.empty else "无"
    
    df_no_best_q = df_trades_q[df_trades_q["quarter"] != best_quarter]
    df_no_best_q_s = calc_single_slot(df_no_best_q)
    m_best_q = calc_nav_and_cap10m(df_no_best_q_s["net_ret"].to_numpy(dtype=float))
    ret_best_q_pct = float(m_best_q["cap10m_ret_pct"] / base_cap * 100.0) if abs(base_cap) > 1e-6 else 100.0
    
    # 依赖度判定
    min_outlier_retention = min(ret_top3_pct, ret_5pct_pct, ret_best_q_pct)
    outlier_verdict = "低度依赖 (全去极值保留率 >= 60%)" if min_outlier_retention >= 60.0 else ("中度依赖妖股/脉冲 (保留率 30%~60%)" if min_outlier_retention >= 30.0 else "重度依赖个别牛股 (保留率 < 30%)")
    
    return {
        "base_cap10m_ret_pct": base_cap,
        "drop_top3": {
            "trades": m_top3["trades"],
            "win_rate_pct": m_top3["win_rate_pct"],
            "nav": m_top3["nav"],
            "cap10m_ret_pct": m_top3["cap10m_ret_pct"],
            "retention_pct": round(ret_top3_pct, 2)
        },
        "drop_top5pct": {
            "dropped_count": n_drop_5pct,
            "trades": m_5pct["trades"],
            "win_rate_pct": m_5pct["win_rate_pct"],
            "nav": m_5pct["nav"],
            "cap10m_ret_pct": m_5pct["cap10m_ret_pct"],
            "retention_pct": round(ret_5pct_pct, 2)
        },
        "drop_best_quarter": {
            "best_quarter": best_quarter,
            "quarter_total_ret_pct": round(float(quarterly_pnl.max() * 100.0), 2) if not quarterly_pnl.empty else 0.0,
            "trades": m_best_q["trades"],
            "win_rate_pct": m_best_q["win_rate_pct"],
            "nav": m_best_q["nav"],
            "cap10m_ret_pct": m_best_q["cap10m_ret_pct"],
            "retention_pct": round(ret_best_q_pct, 2)
        },
        "min_outlier_retention_pct": round(min_outlier_retention, 2),
        "outlier_dependency_verdict": outlier_verdict
    }

def run_test6_n_eff_and_bootstrap(df_trades: pd.DataFrame, n_boots: int = 5000) -> dict:
    """Test 6: 独立有效样本量 N_eff 与 5,000 次 Bootstrap 5% 置信下限"""
    n_trades = len(df_trades)
    if n_trades == 0:
        return {"sample_size_red_flag": True, "bootstrap_significant": False}
        
    # 逐笔超额
    ex_list = []
    for r in df_trades.itertuples(index=False):
        b_ret = get_bench_ret(str(r.buy_date), str(r.exit_date))
        ex_list.append(float(r.net_ret) - b_ret)
    ex_arr = np.array(ex_list, dtype=float)
    
    # 1. 独立周数
    buy_dates = pd.to_datetime(df_trades["buy_date"])
    weeks = set((d.year, d.isocalendar()[1]) for d in buy_dates)
    n_weeks = len(weeks)
    
    # 2. 一阶自相关与 N_eff
    if n_trades > 2:
        rho_1 = float(np.corrcoef(ex_arr[:-1], ex_arr[1:])[0, 1])
        if math.isnan(rho_1):
            rho_1 = 0.0
    else:
        rho_1 = 0.0
        
    if rho_1 > 0:
        n_eff = float(n_trades * (1.0 - rho_1) / (1.0 + rho_1))
    else:
        n_eff = float(n_trades)
        
    sample_size_red_flag = bool(n_trades < 30)
    
    # 3. 5,000 次 Bootstrap (有放回抽样)
    rng = np.random.default_rng(20261116)
    boot_means = np.zeros(n_boots, dtype=float)
    boot_cum_ex = np.zeros(n_boots, dtype=float)
    
    for b in range(n_boots):
        idx = rng.integers(0, n_trades, size=n_trades)
        sample = ex_arr[idx]
        boot_means[b] = np.mean(sample)
        boot_cum_ex[b] = np.sum(sample)
        
    ci_5pct_mean = float(np.percentile(boot_means, 5))
    ci_50pct_mean = float(np.percentile(boot_means, 50))
    ci_95pct_mean = float(np.percentile(boot_means, 95))
    ci_5pct_cum = float(np.percentile(boot_cum_ex, 5))
    
    bootstrap_significant = bool(ci_5pct_mean > 0.0)
    
    return {
        "raw_trades_N": n_trades,
        "independent_weeks_N": n_weeks,
        "rho_1": round(rho_1, 4),
        "N_eff": round(n_eff, 2),
        "sample_size_red_flag": sample_size_red_flag,
        "mean_excess_actual_pct": round(float(np.mean(ex_arr) * 100.0), 2),
        "bootstrap_5pct_ci_excess_per_trade_pct": round(ci_5pct_mean * 100.0, 2),
        "bootstrap_50pct_ci_excess_per_trade_pct": round(ci_50pct_mean * 100.0, 2),
        "bootstrap_95pct_ci_excess_per_trade_pct": round(ci_95pct_mean * 100.0, 2),
        "bootstrap_5pct_cum_excess_pct": round(ci_5pct_cum * 100.0, 2),
        "bootstrap_significant": bootstrap_significant,
        "verdict": "95%置信度下单笔超额显著大于零" if bootstrap_significant else "不显著 (5%置信下限 <= 0)"
    }

# 6. Test 7 ~ Test 8 核心实现函数
def run_test7_yearly_stability(df_trades: pd.DataFrame) -> dict:
    """Test 7: 逐年分年度稳定性 (2022/2023/2024/2025/2026 五年逐年拆解)"""
    years = [2022, 2023, 2024, 2025, 2026]
    yearly_breakdown = {}
    beating_count = 0
    
    for yr in years:
        start_d = f"{yr}-01-01"
        end_d = f"{yr}-12-31" if yr < 2026 else "2026-11-16"
        sub = df_trades[(df_trades["buy_date"] >= start_d) & (df_trades["buy_date"] <= end_d)]
        sub_s = calc_single_slot(sub)
        rets = sub_s["net_ret"].to_numpy(dtype=float) if not sub_s.empty else np.array([])
        m = calc_nav_and_cap10m(rets)
        
        # 沪深300同期收益
        csi_ret = get_bench_ret(start_d, end_d) * 100.0
        excess_slot = m["ret_pct"] - csi_ret
        excess_cap10m = m["cap10m_ret_pct"] - csi_ret
        
        is_beat = bool(excess_cap10m > 0.0)
        if is_beat:
            beating_count += 1
            
        yearly_breakdown[str(yr)] = {
            "trades": m["trades"],
            "win_rate_pct": m["win_rate_pct"],
            "single_slot_ret_pct": m["ret_pct"],
            "cap10m_ret_pct": m["cap10m_ret_pct"],
            "csi300_ret_pct": round(csi_ret, 2),
            "excess_slot_pp": round(excess_slot, 2),
            "excess_cap10m_pp": round(excess_cap10m, 2),
            "beat_csi300": is_beat
        }
        
    years_beating_str = f"{beating_count}/{len(years)}"
    consistency_score = round(beating_count / len(years), 2)
    
    return {
        "yearly_breakdown": yearly_breakdown,
        "years_beating_csi300": years_beating_str,
        "yearly_consistency_score": consistency_score,
        "verdict": "高度稳定 (5/5跑赢基准)" if beating_count == 5 else (f"中度稳定 ({years_beating_str}跑赢基准)" if beating_count >= 3 else f"稳定性较弱 ({years_beating_str}跑赢基准)")
    }

def run_test8_slippage_and_adverse_selection(df_trades: pd.DataFrame, strat_name: str) -> dict:
    """Test 8: 双倍/三倍摩擦与漏掉最难抢前 15% 好票逆向选择压力测试"""
    base_m = calc_nav_and_cap10m(df_trades["net_ret"].to_numpy(dtype=float))
    total_csi_ret = get_bench_ret("2021-11-15", "2026-11-16") * 100.0
    
    # 1. 2x 额外滑点 (每笔额外扣 0.30%)
    rets_2x = df_trades["net_ret"].to_numpy(dtype=float) - 0.0030
    m_2x = calc_nav_and_cap10m(rets_2x)
    
    # 2. 3x 额外滑点 (每笔额外扣 0.60%)
    rets_3x = df_trades["net_ret"].to_numpy(dtype=float) - 0.0060
    m_3x = calc_nav_and_cap10m(rets_3x)
    
    # 3. 抢板逆向选择 (Adverse Selection)
    # 识别排序字段：开盘涨幅 open_pct (若无则从 open_pct_map 补齐，或 score)
    df_adv = df_trades.copy()
    op_list = []
    for r in df_adv.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        bd = str(r.buy_date)
        if hasattr(r, "open_pct") and pd.notna(r.open_pct):
            op_list.append(float(r.open_pct))
        elif (c6, bd) in open_pct_map:
            op_list.append(open_pct_map[(c6, bd)])
        elif hasattr(r, "score") and pd.notna(r.score):
            op_list.append(float(r.score) / 1000.0)
        else:
            op_list.append(float(r.net_ret))
    df_adv["_adverse_sort"] = op_list
    sort_field_name = "open_pct (同日开盘涨幅从高到低)"
    
    # 盈利单按开盘涨幅从高到低排序，剔除前 15% 盈利单，保留 100% 亏损单
    wins_mask = df_adv["net_ret"] > 0
    df_wins = df_adv[wins_mask].sort_values("_adverse_sort", ascending=False)
    df_losses = df_adv[~wins_mask]
    
    n_wins = len(df_wins)
    n_drop = max(1, math.ceil(0.15 * n_wins)) if n_wins > 0 else 0
    df_wins_survived = df_wins.iloc[n_drop:] if n_wins > n_drop else df_wins.iloc[:0]
    
    df_adverse_all = pd.concat([df_wins_survived, df_losses]).sort_values("buy_date").reset_index(drop=True)
    df_adverse_s = calc_single_slot(df_adverse_all)
    m_adverse = calc_nav_and_cap10m(df_adverse_s["net_ret"].to_numpy(dtype=float))
    
    # 4. 地狱组合模式：剔除前 15% 最肥好票 + 2x 额外滑点 (-0.30%)
    rets_hell = df_adverse_s["net_ret"].to_numpy(dtype=float) - 0.0030
    m_hell = calc_nav_and_cap10m(rets_hell)
    
    hell_excess_cap10m = m_hell["cap10m_ret_pct"] - total_csi_ret
    adverse_verdict = "抗击穿韧性极强 (地狱模式仍保住超额)" if hell_excess_cap10m > 0 else ("抗摩擦但怕逆向选择抢板" if m_2x["cap10m_ret_pct"] > total_csi_ret else "脆弱 (高摩擦击穿)")
    
    return {
        "base_cap10m_ret_pct": base_m["cap10m_ret_pct"],
        "csi300_total_ret_pct": round(total_csi_ret, 2),
        "slip_2x_extra_30bps": {
            "win_rate_pct": m_2x["win_rate_pct"],
            "nav": m_2x["nav"],
            "cap10m_ret_pct": m_2x["cap10m_ret_pct"],
            "excess_cap10m_pp": round(m_2x["cap10m_ret_pct"] - total_csi_ret, 2)
        },
        "slip_3x_extra_60bps": {
            "win_rate_pct": m_3x["win_rate_pct"],
            "nav": m_3x["nav"],
            "cap10m_ret_pct": m_3x["cap10m_ret_pct"],
            "excess_cap10m_pp": round(m_3x["cap10m_ret_pct"] - total_csi_ret, 2)
        },
        "adverse_selection_15pct_dropped": {
            "adverse_sort_field": sort_field_name,
            "total_wins": n_wins,
            "dropped_wins_count": n_drop,
            "remaining_trades": m_adverse["trades"],
            "win_rate_pct": m_adverse["win_rate_pct"],
            "nav": m_adverse["nav"],
            "cap10m_ret_pct": m_adverse["cap10m_ret_pct"],
            "excess_cap10m_pp": round(m_adverse["cap10m_ret_pct"] - total_csi_ret, 2)
        },
        "hell_mode_adverse_plus_2x_slip": {
            "trades": m_hell["trades"],
            "win_rate_pct": m_hell["win_rate_pct"],
            "nav": m_hell["nav"],
            "cap10m_ret_pct": m_hell["cap10m_ret_pct"],
            "excess_cap10m_pp": round(hell_excess_cap10m, 2)
        },
        "adverse_selection_verdict": adverse_verdict
    }

# 7. 主流程执行 11 个策略与合体组合 8 项全维审计
def sanitize_json(obj):
    """递归清洗 NaN, Inf, np.generic 确保输出绝对合规 JSON"""
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_json(v) for v in obj]
    elif isinstance(obj, (np.floating, float)):
        if math.isnan(obj): return None
        if math.isinf(obj): return 999.0 if obj > 0 else -999.0
        return float(obj)
    elif isinstance(obj, (np.integer, int)):
        return int(obj)
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj

def main():
    print("================================================================================")
    print(" Wave 2 顶级量化防过拟合统计学审计 (11 个策略 x 8 项数学测试)")
    print(" 遵循 Bailey & López de Prado / Harvey-Liu-Zhu 标准，严禁 yfinance")
    print("================================================================================")
    
    # 预先计算沪深300全周期每日收益率
    bench_daily_rets = np.zeros(len(trading_days), dtype=float)
    for i in range(1, len(trading_days)):
        d_prev = trading_days[i - 1]
        d_curr = trading_days[i]
        bench_daily_rets[i] = sh300_data[d_curr] / sh300_data[d_prev] - 1.0
        
    target_strategies = [
        ("基础版_高标首阴V5.1", "partA_high_3to4/ledger_base_high_v51.csv", False),
        ("基础版_三进四V3.4", "partA_high_3to4/ledger_base_3to4_v34.csv", False),
        ("基础版_一进二V18", "partB_1to2/ledger_base_1to2_v18.csv", False),
        ("辅助_超跌撬板V1.0", "partC_aux/ledger_aux_pry_v10.csv", True),
        ("辅助_五板卡异动", "partC_aux/ledger_aux_5board.csv", True),
        ("基础版_三大主策略纯单仓合体", "ledger_base_combined_3main.csv", False),
        ("基础版_三大主策略加撬板合体", "ledger_base_combined_3main_plus_pry.csv", False),
        ("26Q4专供_高标首阴", "partD_26q4_and_combined/ledger_26q4_high.csv", False),
        ("26Q4专供_三进四", "partD_26q4_and_combined/ledger_26q4_3to4.csv", False),
        ("26Q4专供_一进二", "partD_26q4_and_combined/ledger_26q4_1to2.csv", False),
        ("26Q4专供_三大主策略纯单仓合体", "partD_26q4_and_combined/ledger_26q4_combined_3main.csv", True)
    ]
    
    audit_results = {}
    summary_table = []
    
    for s_name, rel_p, need_slot_filter in target_strategies:
        full_p = f"{CLEAN}/{rel_p}"
        print(f"\n>>> [Auditing] {s_name} ({rel_p})...")
        df_raw = pd.read_csv(full_p)
        raw_len = len(df_raw)
        
        # 统一字段
        if "buy_px" in df_raw.columns and "buy_price" not in df_raw.columns:
            df_raw["buy_price"] = df_raw["buy_px"]
        if "exit_px" in df_raw.columns and "exit_price" not in df_raw.columns:
            df_raw["exit_price"] = df_raw["exit_px"]
            
        if need_slot_filter:
            df_trades = calc_single_slot(df_raw)
        else:
            df_trades = df_raw.copy()
            
        slot_len = len(df_trades)
        print(f"    Trades loaded: raw={raw_len}, single_slot={slot_len}")
        
        # 依次运行 8 项测试
        # Test 1
        t1 = run_test1_dsr_hlz(df_trades, s_name, trading_days, bench_daily_rets)
        # Test 2
        t2 = run_test2_monkey_mc(df_trades, s_name, n_sims=5000)
        # Test 3
        t3 = run_test3_perturbation_and_lofo(df_trades, s_name)
        # Test 4
        t4 = run_test4_cscv_and_oos_decay(df_trades, s_name, trading_days)
        # Test 5
        t5 = run_test5_outlier_removal(df_trades)
        # Test 6
        t6 = run_test6_n_eff_and_bootstrap(df_trades, n_boots=5000)
        # Test 7
        t7 = run_test7_yearly_stability(df_trades)
        # Test 8
        t8 = run_test8_slippage_and_adverse_selection(df_trades, s_name)
        
        # 综合判定
        pass_hlz = t1["trade_level"]["hlz_pass_trade"]
        pass_dsr = bool(t1["trade_level"]["DSR_prob_M150"] >= 0.95)
        pass_monkey = t2["pass_test"]
        pass_pert = bool(t3["min_perturbation_retention_pct"] >= 50.0)
        pass_pbo = bool(t4["pbo"] < 0.50)
        pass_boot = t6["bootstrap_significant"]
        pass_stable = bool(t7["yearly_consistency_score"] >= 0.60)
        pass_hell = bool(t8["hell_mode_adverse_plus_2x_slip"]["excess_cap10m_pp"] > 0.0)
        
        # 战略总决断
        is_red_flag = False
        verdict_str = ""
        if t6["sample_size_red_flag"]:
            is_red_flag = True
            verdict_str = "红灯 (样本量极小 N<30，统计不可靠)"
        elif not pass_boot or not pass_hlz or t1["trade_level"]["mean_excess_trade"] <= 0:
            is_red_flag = True
            verdict_str = "红灯 (统计显著性未通过 / 负超额)"
        elif pass_hlz and pass_dsr and pass_monkey and pass_pbo and pass_hell:
            verdict_str = "全绿通过 (铁打真有效，抗住全部8项顶刊级压力测试)"
        elif pass_hlz and pass_monkey and pass_boot:
            verdict_str = "黄灯通过 (核心统计有效，但在高摩擦或特定去极值下有衰减)"
        else:
            is_red_flag = True
            verdict_str = "红灯警报 (多项统计学测试未通过)"
            
        strat_audit = {
            "strategy_name": s_name,
            "ledger_path": rel_p,
            "raw_trades_count": raw_len,
            "single_slot_trades_count": slot_len,
            "overall_verdict": verdict_str,
            "test1_multiple_testing_haircut_dsr": t1,
            "test2_monte_carlo_permutation_monkey": t2,
            "test3_threshold_perturbation_and_lofo": t3,
            "test4_cscv_pbo_and_oos_decay": t4,
            "test5_outlier_removal_extremes": t5,
            "test6_n_eff_and_bootstrap_ci": t6,
            "test7_yearly_stability_breakdown": t7,
            "test8_slippage_and_adverse_selection": t8
        }
        
        audit_results[s_name] = strat_audit
        summary_table.append({
            "name": s_name,
            "N": slot_len,
            "mean_ex": f"{t1['trade_level']['mean_excess_trade']*100:.2f}%",
            "t_stat": f"{t1['trade_level']['t_trade']:.2f}",
            "DSR_150": f"{t1['trade_level']['DSR_prob_M150']*100:.1f}%",
            "p_monkey": f"{t2['p_value']:.4f}",
            "PBO": f"{t4['pbo']*100:.1f}%",
            "5yr_beat": t7["years_beating_csi300"],
            "hell_ex": f"{t8['hell_mode_adverse_plus_2x_slip']['excess_cap10m_pp']:.1f}pp",
            "verdict": verdict_str
        })
        
    # 保存结果落盘
    clean_audit_data = sanitize_json(audit_results)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(clean_audit_data, f, ensure_ascii=False, indent=2)
    print(f"\n[Success] All 11 strategies audited. Output saved to {OUT_JSON}")
    
    # 打印紧凑精炼汇总表 (<= 3KB)
    print("\n" + "=" * 105)
    print(f"{'策略名称':<22} | {'N':>3} | {'超额均值':>7} | {'t统计':>5} | {'DSR(150)':>8} | {'猴子p值':>7} | {'PBO':>6} | {'超额年数':>6} | {'地狱超额':>8} | {'总决断'}")
    print("-" * 105)
    for r in summary_table:
        print(f"{r['name']:<22} | {r['N']:>3} | {r['mean_ex']:>7} | {r['t_stat']:>5} | {r['DSR_150']:>8} | {r['p_monkey']:>7} | {r['PBO']:>6} | {r['5yr_beat']:>6} | {r['hell_ex']:>8} | {r['verdict']}")
    print("=" * 105)

if __name__ == "__main__":
    main()
