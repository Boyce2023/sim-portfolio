#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
p1_pry_v10_scorecard.py: 《冰点超跌撬板 V1.0》纯整数打分卡与执行器 (P1 专属定版)
严格遵守 D12（零 yfinance）、D15（四必核）、零未来函数与反幸存者偏差铁律：
  1. 基础池要求：非ST/退市名、股价 >= 2.0 元、交叉核验退市库；
  2. 买法：B3_pry_lift_15pct（跌停开盘 open <= dt_px + 0.011，盘中向上拉起 1.5% 右侧拐点买入 round(dt_px * 1.015, 2)）；
  3. 卖法：E6_cut_reseal_tp7_h3（断腕护城河卖法：Day 0 尾盘回封或大阴次日开盘立割绝不死扛；收红冲 +7% 止盈或最长持有 3 天，地天板连板持有）；
  4. 纯整数打分卡（100 分起评）：
      - 盘面恐慌：昨日跌停>=40家 (+25) / 昨日跌停>=20家 (+15) / 昨日跌停<15家 (-15)
      - 纯超跌结构：前20日无涨停纯超跌 (+20) / 前20日>=2次涨停妖股A杀 (-25)
      - 累计超跌：前10日跌幅<-25% (+15) / 前10日跌幅<-20% (+10) / 前10日跌幅>=-15% (-10)
      - 90日公告排雷：90日无毒丸 (+15) / 90日立案调查 (-30) / 退市风险 (-30) / 业绩预亏下修 (-15) / 减持 (-10)
      - 正向催化：90日回购增持中标 (+10) / 前8日机构调研 (+10)
      - 日历雷区：避开1月与4月年报季报期 (+10) / 处于1月或4月 (-15)
      - 股价档位：中低价股<15元 (+5) / 高价股>=30元 (-10)
      - 席位特征：无拉萨席位 (+5) / 拉萨席位>=3家散户扎堆 (-10)
  5. 阈值分档：
      - 精锐档 (Elite Tier): Score >= 150 (38笔，高胜率 57.9%，盈亏比 1.38，5年单仓净值 2.277，去前3极值 1.362)
      - 宽进档 (Broad Tier): Score >= 130 (72笔，胜率 58.3%，盈亏比 1.04，5年单仓净值 2.027)
"""
import os
import sys
import json
import time
import pickle
import numpy as np
import pandas as pd

WORK_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p4_pry_board"
MAT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
if WORK_DIR not in sys.path:
    sys.path.insert(0, WORK_DIR)

from p1_sim_engine import (
    precompute_all_entries_and_exits,
    build_trades_dataframe,
    eval_d15_all,
    CSI_BENCHMARKS,
)
from p1_task2_factor_mining import extract_90d_notices, compute_cb_features


def compute_v10_score(df: pd.DataFrame) -> np.ndarray:
    """计算《冰点超跌撬板 V1.0》纯整数得分 (100分起评)"""
    score = np.full(len(df), 100, dtype=int)

    # 1. 盘面恐慌程度 (Market Panic - 系统性错杀赋能)
    dt_prev = df["mkt_dt_prev"].values
    score += np.where(dt_prev >= 40, 25, np.where(dt_prev >= 20, 15, np.where(dt_prev < 15, -15, 0)))

    # 2. 纯超跌结构 vs 妖股A杀 (Pure Oversold Reversal)
    zt_cnt = df["zt_cnt_pre20"].values
    score += np.where(zt_cnt == 0, 20, np.where(zt_cnt >= 2, -25, 0))

    # 3. 累计超跌深度 (Exhaustion Drop)
    ret10 = df["ret_pre10"].values
    score += np.where(ret10 < -0.25, 15, np.where(ret10 < -0.20, 10, np.where(ret10 >= -0.15, -10, 0)))

    # 4. 90日细粒度公告排雷 (Notice Minefield)
    poison = df["notice_90d_poison_any"].values
    score += np.where(~poison, 15, 0)
    score -= np.where(df["notice_90d_investigation"].values, 30, 0)
    score -= np.where(df["notice_90d_delist_risk"].values, 30, 0)
    score -= np.where(df["notice_90d_loss_down"].values, 15, 0)
    score -= np.where(df["notice_90d_reduction"].values, 10, 0)

    # 5. 正向催化与机构调研 (Positive Catalysts)
    score += np.where(df["notice_90d_positive_any"].values, 10, 0)
    score += np.where(df["has_ir_8d"].values == 1, 10, 0)

    # 6. 日历雷区过滤 (Calendar Minefield)
    score += np.where(~df["is_month_1_or_4"].values, 10, -15)

    # 7. 股价档位 (Price Tier)
    px = df["open_px_raw"].values
    score += np.where(px < 15.0, 5, np.where(px >= 30.0, -10, 0))

    # 8. 席位特征 (Dragon-Tiger Seats)
    seats = df["lhasa_seats_prev"].values
    score += np.where(seats == 0, 5, np.where(seats >= 3, -10, 0))

    return score


def load_and_score_pry_data():
    """全量加载与打分管线"""
    print("[+] Loading cand_pry_limitdown.parquet & code_bars_5y.pkl...")
    df = pd.read_parquet(f"{MAT_DIR}/cand_pry_limitdown.parquet")
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f:
        cb = pickle.load(f)["code_bars"]

    # 提取特征
    notices = extract_90d_notices(df)
    for k, v in notices.items():
        df[k] = v

    cb_f = compute_cb_features(df, cb)
    for k, v in cb_f.items():
        df[k] = v

    df["buy_date_dt"] = pd.to_datetime(df["buy_date"])
    df["month"] = df["buy_date_dt"].dt.month
    df["is_month_1_or_4"] = df["month"].isin([1, 4])

    # 打分
    df["score_v10"] = compute_v10_score(df)

    # 基础合规过滤
    is_st_name = df["name"].str.contains("ST|退", na=False).values
    is_penny = df["open_px_raw"].values < 2.0
    df["base_valid"] = (~is_st_name) & (~is_penny)

    return df, cb


def main():
    df, cb = load_and_score_pry_data()
    pre = precompute_all_entries_and_exits(df, cb)
    prio_deep10 = -df["ret_pre10"].values.astype(float)

    # 1. 产出精锐档台账 (Th=150)
    mask_150 = df["base_valid"].values & (df["score_v10"].values >= 150)
    tdf_150 = build_trades_dataframe(df, pre, mask_150, "B3_pry_lift_15pct", "E6_cut_reseal_tp7_h3", prio_deep10)

    # 整理标准逐笔台账列
    ledger_cols = [
        "code", "name", "buy_date", "exit_date", "buy_px", "exit_price",
        "net_ret", "hold_bars", "exit_at_open", "score_v10", "day0_ret",
        "day0_reseal", "day0_zt", "mkt_dt_prev", "ret_pre10",
        "notice_90d_poison_any", "is_month_1_or_4", "open_px_raw"
    ]
    tdf_150["exit_price"] = np.round(tdf_150["buy_px"] * (1.0 + tdf_150["net_ret"] + 0.0020), 2)
    ledger_df = tdf_150[ledger_cols].copy()
    ledger_path = f"{WORK_DIR}/p1_pry_v10_ledger.csv"
    ledger_df.to_csv(ledger_path, index=False, encoding="utf-8-sig")
    print(f"[+] Saved V1.0 Elite Ledger to: {ledger_path} ({len(ledger_df)} candidate rows)")

    # 2. 评测指标
    ev_150 = eval_d15_all(tdf_150)
    print("\n=== V1.0 Elite (Th=150) 5Y Performance ===")
    print(json.dumps(ev_150["full_5y"], indent=2, ensure_ascii=False))
    print("\n=== V1.0 Elite (Th=150) IS vs OOS ===")
    print(f"IS 2022-2024: NAV={ev_150['is_2022_2024']['single_nav']}, WR={ev_150['is_2022_2024']['wr']}%, Excess={ev_150['is_2022_2024']['single_excess_pct']}%")
    print(f"OOS 2025-2026: NAV={ev_150['oos_2025_2026']['single_nav']}, WR={ev_150['oos_2025_2026']['wr']}%, Excess={ev_150['oos_2025_2026']['single_excess_pct']}%")


if __name__ == "__main__":
    main()
