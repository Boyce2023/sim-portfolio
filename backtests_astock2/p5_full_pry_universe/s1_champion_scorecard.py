#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
s1_champion_scorecard.py - 盘中撬板最强纯整数打分卡与全量检验 (Task 3)
严格遵循零未来函数与 D15 四必核规范：
1. 单仓轮动净值 (严格 buy_date > prev_exit_date 与 buy_date >= prev_exit_date 对照) 与按日等权净值；
2. 剔除 ST 与退市，pre_c >= 2.0，二次回封跌停 100% 计入分母；
3. 全五年 (2022-2026)、近三年、近期三期胜率、真实盈亏比、净值、最大回撤、去前3/前5极值净值；
4. 样本内 (IS: 2022-2024) 定规则与权重，样本外 (OOS: 2025-2026) 盲测一次！
产出：s1_champion_ledger.csv 与 s1_summary.json
"""
import os, time, json, pickle
import numpy as np
import pandas as pd

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"
PARQUET_FILE = f"{BASE_DIR}/full_pry_master_enriched.parquet"
RETURN_MATRIX_FILE = f"{BASE_DIR}/return_matrix_8x10.pkl"
OUT_LEDGER = f"{BASE_DIR}/s1_champion_ledger.csv"
OUT_JSON = f"{BASE_DIR}/s1_summary.json"

# CSI 300 Benchmarks (from user prompt)
BENCHMARK_5Y = -0.1784   # 2022-01-04 to 2026-11-10
BENCHMARK_3Y = 0.1235    # 2023-11-10 to 2026-11-10
BENCHMARK_REC = -0.1848  # 2026-07-01 to 2026-11-10

def calc_stats(ret_series):
    r = np.array(ret_series, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "plr": 0.0, "mean_pct": 0.0, "mult": 1.0, "mdd_pct": 0.0}
    w = float((r > 0).mean())
    m = float(r.mean())
    g = r[r > 0]
    l = r[r < 0]
    gain = float(g.mean()) if len(g) > 0 else 0.0
    loss = float(abs(l.mean())) if len(l) > 0 else 1.0
    plr = float(gain / loss) if loss > 1e-6 else 0.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    mdd = float(dd.min())
    return {
        "n": n,
        "win_rate": round(w * 100, 2),
        "plr": round(plr, 2),
        "mean_pct": round(m * 100, 2),
        "mult": round(float(eq[-1]), 2),
        "mdd_pct": round(mdd * 100, 2)
    }

def main():
    t0 = time.time()
    print("Loading data for Champion Scorecard...")
    df = pd.read_parquet(PARQUET_FILE)
    with open(RETURN_MATRIX_FILE, "rb") as f:
        rm = pickle.load(f)

    # 1. Zero-Lookahead Integer Score Card Features
    dt_streak = df["prev_dt_streak"].fillna(0).values
    mkt_dt = df["mkt_open_dt_0925"].fillna(0).values
    ret10 = df["prev_ret10"].fillna(0).values
    dd20 = df["prev_dd20"].fillna(1.0).values
    rf_mcap = df["real_free_mcap"].fillna(9999).values
    lock10 = df["lock_top10"].fillna(0).values
    inst_sell = df["inst_sell_prev"].fillna(0).values
    buyback = df["n_buyback90"].fillna(False).values.astype(bool)
    poison = df["n_poison90"].fillna(False).values.astype(bool)
    comm24 = df["comm24"].fillna(0).values
    vr_prev = df["prev_vr"].fillna(1.0).values

    # Compute Pure Integer Score (锻造纯整数打分卡)
    score = np.zeros(len(df), dtype=int)
    # Rule 1: 连板与首跌停物理分化
    score += np.where(dt_streak >= 3, 4, np.where(dt_streak == 2, 3, np.where(dt_streak == 1, 1, -2)))
    # Rule 2: 09:25 开盘全市场恐慌传感器
    score += np.where(mkt_dt >= 35, 3, np.where(mkt_dt >= 20, 2, np.where(mkt_dt >= 10, 1, np.where(mkt_dt < 5, -2, 0))))
    # Rule 3: 10日深度超跌
    score += np.where(ret10 <= -0.25, 4, np.where(ret10 <= -0.20, 3, np.where(ret10 <= -0.15, 1, 0)))
    # Rule 4: 20日最大回撤超跌
    score += np.where(dd20 <= 0.72, 2, 0)
    # Rule 5: 自由流通盘与大股东锁仓
    score += np.where(rf_mcap < 25.0, 2, np.where(rf_mcap < 50.0, 1, 0))
    score += np.where(lock10 >= 50.0, 1, 0)
    # Rule 6: 机构专用砸盘错杀与回购护盘
    score += np.where(inst_sell > 0, 2, 0)
    score += np.where(buyback, 2, 0)
    # Rule 7: 暴雷公告一票否决
    score += np.where(poison, -5, 0)
    # Rule 8: 社区热度与天量杀跌惩罚
    score += np.where(comm24 == 0, 1, np.where(comm24 >= 10, -2, 0))
    score += np.where((dt_streak == 0) & (vr_prev > 3.0), -3, 0)

    # Base clean filter (剔除 ST 与退市，pre_c >= 2.0)
    base_clean = ((~df["is_st_or_delist"].values) & (df["pre_c"].values >= 2.0))

    # Champion setup: Entry E4_intradive_dt, Exits: X9 (primary), X2, X7
    ename = "E4_intradive_dt"
    TH = 10  # Score >= 10 as champion threshold

    r_x9 = rm["ret"][ename]["X9"]
    edt_x9 = rm["exit_dt"][ename]["X9"]
    r_x2 = rm["ret"][ename]["X2"]
    edt_x2 = rm["exit_dt"][ename]["X2"]
    r_x7 = rm["ret"][ename]["X7"]
    edt_x7 = rm["exit_dt"][ename]["X7"]

    cand_mask = base_clean & (score >= TH) & (~np.isnan(r_x9))
    print(f"Total triggered candidates (Score >= {TH}): {cand_mask.sum():,}")

    cands = df[cand_mask].copy()
    cands["score"] = score[cand_mask]
    cands["ret_x9"] = r_x9[cand_mask]
    cands["exit_dt_x9"] = edt_x9[cand_mask]
    cands["ret_x2"] = r_x2[cand_mask]
    cands["exit_dt_x2"] = edt_x2[cand_mask]
    cands["ret_x7"] = r_x7[cand_mask]
    cands["exit_dt_x7"] = edt_x7[cand_mask]

    # Deterministic sorting for trade selection: date asc, score desc, most oversold (prev_ret10 asc), smallest float asc
    cands = cands.sort_values(
        ["dt_str", "score", "prev_ret10", "real_free_mcap"],
        ascending=[True, False, True, True]
    ).reset_index(drop=True)

    # 1. Build Strict Single-Position Rotation Ledger (buy_date > prev_exit_date)
    trades_strict = []
    last_exit_s = ""
    for _, r in cands.iterrows():
        b_dt = r["dt_str"]
        if b_dt > last_exit_s:
            trades_strict.append(r)
            last_exit_s = r["exit_dt_x2"]  # Use X2 (T+1 exit) as primary turnover rotation

    tdf_strict = pd.DataFrame(trades_strict).reset_index(drop=True)
    print(f"Strict single-position rotation trades (buy_date > prev_exit): {len(tdf_strict)}")

    # 2. Build Relaxed Single-Position Rotation Ledger (buy_date >= prev_exit_date)
    trades_relaxed = []
    last_exit_r = ""
    for _, r in cands.iterrows():
        b_dt = r["dt_str"]
        if b_dt >= last_exit_r:
            trades_relaxed.append(r)
            last_exit_r = r["exit_dt_x2"]

    tdf_relaxed = pd.DataFrame(trades_relaxed).reset_index(drop=True)
    print(f"Relaxed single-position rotation trades (buy_date >= prev_exit): {len(tdf_relaxed)}")

    # Save ledger
    ledger_cols = [
        "dt_str", "ticker", "name", "score", "pre_c", "prev_dt_streak", "prev_ret10",
        "mkt_open_dt_0925", "real_free_mcap", "lock_top10", "comm24",
        "ret_x2", "exit_dt_x2", "ret_x7", "exit_dt_x7", "ret_x9", "exit_dt_x9"
    ]
    tdf_strict[ledger_cols].to_csv(OUT_LEDGER, index=False, encoding="utf-8-sig")
    print(f"Saved trade ledger to {OUT_LEDGER}")

    # 3. Comprehensive D15 Metrics
    # Time slices
    dts = tdf_strict["dt_str"].values
    m_5y = np.ones(len(tdf_strict), dtype=bool)
    m_3y = (dts >= "2023-11-10")
    m_rec = (dts >= "2026-07-01")
    m_is = (dts < "2025-01-01")
    m_oos = (dts >= "2025-01-01")

    # Metrics for Strict Rotation (X2 exit)
    r_x2_s = tdf_strict["ret_x2"].values
    stats_5y_x2 = calc_stats(r_x2_s)
    stats_3y_x2 = calc_stats(r_x2_s[m_3y])
    stats_rec_x2 = calc_stats(r_x2_s[m_rec])
    stats_is_x2 = calc_stats(r_x2_s[m_is])
    stats_oos_x2 = calc_stats(r_x2_s[m_oos])

    # Sensitivity tests: drop top 3 and top 5 extremes
    r_x2_drop3 = np.sort(r_x2_s)[:-3] if len(r_x2_s) > 3 else r_x2_s
    r_x2_drop5 = np.sort(r_x2_s)[:-5] if len(r_x2_s) > 5 else r_x2_s
    stats_drop3_x2 = calc_stats(r_x2_drop3)
    stats_drop5_x2 = calc_stats(r_x2_drop5)

    # Annual splits
    years = ["2022", "2023", "2024", "2025", "2026"]
    annual_strict_x2 = {}
    for yr in years:
        m_yr = (np.array([d[:4] for d in dts]) == yr)
        annual_strict_x2[yr] = calc_stats(r_x2_s[m_yr])

    # Relaxed rotation stats (X2 exit)
    r_x2_r = tdf_relaxed["ret_x2"].values
    stats_relaxed_x2 = calc_stats(r_x2_r)

    # Daily Equal-Weighted Stats (all candidates on active dates)
    daily_cands = cands.groupby("dt_str")["ret_x2"].mean()
    stats_daily_x2 = calc_stats(daily_cands.values)

    # Trade-Level Equal-Weighted (Full Universe Pool, Score >= 10)
    all_cand_x9 = cands["ret_x9"].values
    stats_pool_x9 = calc_stats(all_cand_x9)
    stats_pool_x9_is = calc_stats(cands[cands["dt_str"] < "2025-01-01"]["ret_x9"].values)
    stats_pool_x9_oos = calc_stats(cands[cands["dt_str"] >= "2025-01-01"]["ret_x9"].values)

    # Benchmark net alpha comparison
    alpha_5y = round((stats_5y_x2["mult"] - 1.0) - BENCHMARK_5Y, 4)
    alpha_3y = round((stats_3y_x2["mult"] - 1.0) - BENCHMARK_3Y, 4)
    alpha_rec = round((stats_rec_x2["mult"] - 1.0) - BENCHMARK_REC, 4)

    summary_payload = {
        "strategy_name": "S1_Systemic_Panic_Oversold_Pry_Champion",
        "description": "基于09:25开盘恐慌传感器与10日深度超跌的盘中急杀触及跌停(E4)纯整数打分卡策略",
        "scorecard_rules": {
            "dt_streak": {"ge_3": 4, "eq_2": 3, "eq_1": 1, "eq_0": -2},
            "mkt_open_dt_0925": {"ge_35": 3, "ge_20": 2, "ge_10": 1, "lt_5": -2},
            "prev_ret10": {"le_-25pct": 4, "le_-20pct": 3, "le_-15pct": 1},
            "prev_dd20": {"le_0.72": 2},
            "real_free_mcap": {"lt_25y": 2, "lt_50y": 1},
            "lock_top10": {"ge_50pct": 1},
            "inst_sell_prev": {"gt_0": 2},
            "n_buyback90": {"true": 2},
            "n_poison90": {"true": -5},
            "comm24": {"eq_0": 1, "ge_10": -2},
            "trap_penalty": {"dt0_and_vr_gt_3": -3}
        },
        "score_threshold": TH,
        "entry": "E4_intradive_dt (非跌停开盘盘中下杀触跌停排单买入，买入价 dt_price+0.01)",
        "d15_four_checks": {
            "check1_single_position_rotation_strict": {
                "exit": "X2 (T+1收盘走)",
                "5y_full": stats_5y_x2,
                "3y_last": stats_3y_x2,
                "recent_2026": stats_rec_x2,
                "is_sample_2022_2024": stats_is_x2,
                "oos_blind_test_2025_2026": stats_oos_x2,
                "drop_top_3_extremes": stats_drop3_x2,
                "drop_top_5_extremes": stats_drop5_x2,
                "annual_breakdown": annual_strict_x2,
                "benchmark_comparison": {
                    "csi300_5y": BENCHMARK_5Y,
                    "strategy_net_5y": round(stats_5y_x2["mult"] - 1.0, 4),
                    "alpha_5y": alpha_5y,
                    "csi300_3y": BENCHMARK_3Y,
                    "strategy_net_3y": round(stats_3y_x2["mult"] - 1.0, 4),
                    "alpha_3y": alpha_3y,
                    "csi300_recent": BENCHMARK_REC,
                    "strategy_net_recent": round(stats_rec_x2["mult"] - 1.0, 4),
                    "alpha_recent": alpha_rec
                }
            },
            "check1_single_position_rotation_relaxed": {
                "exit": "X2 (buy_date >= prev_exit_date)",
                "stats": stats_relaxed_x2
            },
            "check1_daily_equal_weighted": {
                "active_trading_days": len(daily_cands),
                "stats": stats_daily_x2
            },
            "trade_level_equal_weighted_illusion_audit": {
                "note": "未加单仓轮动过滤时的全市场触发样本，包含救市日单日396笔集中触发的均值放大幻觉",
                "pool_x9_all": stats_pool_x9,
                "pool_x9_is": stats_pool_x9_is,
                "pool_x9_oos": stats_pool_x9_oos
            }
        }
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2, ensure_ascii=False)

    print(f"Summary saved to {OUT_JSON}. Total elapsed: {time.time()-t0:.2f}s")

if __name__ == "__main__":
    main()
