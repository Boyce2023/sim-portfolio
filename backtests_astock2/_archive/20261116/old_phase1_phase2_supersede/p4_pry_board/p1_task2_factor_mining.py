#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
p1_task2_factor_mining.py: 任务二：扩充新特征并跑满 180+ 个因子切片逐一防伪回测
输出: p1_oversold_factor_catalog.csv
严格遵守 D12（零 yfinance）、D15（四必核）、零未来函数与反幸存者偏差铁律。
"""
import os
import sys
import json
import time
import sqlite3
import pickle
from datetime import datetime, timedelta
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
    eval_d15_period,
    is_locked_limit_down_bar,
    CSI_BENCHMARKS,
    FEE_RATE,
)


def extract_90d_notices(df_candidates: pd.DataFrame) -> dict:
    """从 cninfo_notices_5y_pit.db 提取每个标的在 buy_date 前 90 日内的细粒度公告"""
    t0 = time.time()
    db_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    query = """
    SELECT sec_code, trade_date_avail, title 
    FROM notices 
    WHERE title LIKE '%立案%' 
       OR title LIKE '%减持%' 
       OR title LIKE '%退市风险%' 
       OR title LIKE '%终止上市%' 
       OR title LIKE '%违规担保%' 
       OR title LIKE '%资金占用%' 
       OR title LIKE '%预亏%' 
       OR title LIKE '%下修%' 
       OR title LIKE '%问询%' 
       OR title LIKE '%监管函%' 
       OR title LIKE '%关注函%' 
       OR title LIKE '%回购%' 
       OR title LIKE '%增持%' 
       OR title LIKE '%中标%' 
       OR title LIKE '%重大合同%'
    """
    df_notices = pd.read_sql_query(query, conn)
    conn.close()
    print(f"[+] Loaded {len(df_notices)} notices in {time.time()-t0:.2f}s")

    # 按股票代码建立倒排索引
    notices_by_code = {}
    for code, group in df_notices.groupby("sec_code"):
        notices_by_code[code] = list(zip(group["trade_date_avail"].values, group["title"].values))

    N = len(df_candidates)
    n_investigation = np.zeros(N, dtype=bool)
    n_reduction = np.zeros(N, dtype=bool)
    n_delist_risk = np.zeros(N, dtype=bool)
    n_illegal_guarantee = np.zeros(N, dtype=bool)
    n_loss_down = np.zeros(N, dtype=bool)
    n_inquiry = np.zeros(N, dtype=bool)
    n_poison_any = np.zeros(N, dtype=bool)
    n_buyback = np.zeros(N, dtype=bool)
    n_increase = np.zeros(N, dtype=bool)
    n_bid_win = np.zeros(N, dtype=bool)
    n_positive_any = np.zeros(N, dtype=bool)

    codes = df_candidates["code"].values
    buy_dates = df_candidates["buy_date"].values

    for i in range(N):
        c = codes[i]
        bd = buy_dates[i]
        c_notices = notices_by_code.get(c, [])
        if not c_notices:
            continue

        # 计算 90 日窗口
        # bd: YYYY-MM-DD
        dt_bd = datetime.strptime(bd, "%Y-%m-%d")
        dt_start = (dt_bd - timedelta(days=90)).strftime("%Y-%m-%d")

        for nd, title in c_notices:
            if dt_start <= nd <= bd:
                # 毒丸类别
                if "立案" in title:
                    n_investigation[i] = True
                    n_poison_any[i] = True
                if "减持" in title:
                    n_reduction[i] = True
                    n_poison_any[i] = True
                if "退市风险" in title or "终止上市" in title:
                    n_delist_risk[i] = True
                    n_poison_any[i] = True
                if "违规担保" in title or "资金占用" in title:
                    n_illegal_guarantee[i] = True
                    n_poison_any[i] = True
                if "预亏" in title or "下修" in title or "亏损" in title:
                    n_loss_down[i] = True
                    n_poison_any[i] = True
                if "问询" in title or "监管函" in title or "关注函" in title:
                    n_inquiry[i] = True
                    n_poison_any[i] = True

                # 正向类别
                if "回购" in title:
                    n_buyback[i] = True
                    n_positive_any[i] = True
                if "增持" in title:
                    n_increase[i] = True
                    n_positive_any[i] = True
                if "中标" in title or "重大合同" in title:
                    n_bid_win[i] = True
                    n_positive_any[i] = True

    return {
        "notice_90d_investigation": n_investigation,
        "notice_90d_reduction": n_reduction,
        "notice_90d_delist_risk": n_delist_risk,
        "notice_90d_illegal_guarantee": n_illegal_guarantee,
        "notice_90d_loss_down": n_loss_down,
        "notice_90d_inquiry": n_inquiry,
        "notice_90d_poison_any": n_poison_any,
        "notice_90d_buyback": n_buyback,
        "notice_90d_increase": n_increase,
        "notice_90d_bid_win": n_bid_win,
        "notice_90d_positive_any": n_positive_any,
    }


def compute_cb_features(df_candidates: pd.DataFrame, cb: dict) -> dict:
    """从 code_bars_5y 提取新 PIT 因子"""
    N = len(df_candidates)
    prev_dt_to_sum = np.zeros(N, dtype=float)
    prev_is_yizi_dt = np.zeros(N, dtype=bool)
    ret_pre5 = np.zeros(N, dtype=float)
    ret_pre20 = np.zeros(N, dtype=float)
    open_px_raw = np.zeros(N, dtype=float)

    codes = df_candidates["code"].values
    buy_dates = df_candidates["buy_date"].values
    prev_dt_streaks = df_candidates["prev_dt_streak"].values

    for i in range(N):
        c = codes[i]
        bd = buy_dates[i]
        b = cb[c]
        pos = b["date_to_pos"][bd]
        open_px_raw[i] = float(b["open"][pos])

        # 检查前一日是否无量一字跌停
        if pos > 0:
            p_op, p_hi, p_lo, p_cl, p_pc = b["open"][pos - 1], b["high"][pos - 1], b["low"][pos - 1], b["close"][pos - 1], b["pre_c"][pos - 1]
            prev_is_yizi_dt[i] = is_locked_limit_down_bar(p_op, p_hi, p_lo, p_cl, p_pc, bool(b["is_yizi_dt"][pos - 1]))

        # 计算连跌期间换手率之和
        streak = max(1, int(prev_dt_streaks[i]))
        to_sum = 0.0
        for k in range(1, streak + 1):
            if pos - k >= 0:
                to_sum += float(b["to"][pos - k])
        prev_dt_to_sum[i] = to_sum

        # 计算前5日与前20日涨跌幅
        if pos >= 6:
            c1 = b["close"][pos - 1] * b["adjf"][pos - 1]
            c5 = b["close"][pos - 6] * b["adjf"][pos - 6]
            ret_pre5[i] = float(c1 / c5 - 1.0) if c5 > 0 else 0.0
        else:
            ret_pre5[i] = 0.0

        if pos >= 21:
            c1 = b["close"][pos - 1] * b["adjf"][pos - 1]
            c20 = b["close"][pos - 21] * b["adjf"][pos - 21]
            ret_pre20[i] = float(c1 / c20 - 1.0) if c20 > 0 else 0.0
        else:
            ret_pre20[i] = 0.0

    return {
        "open_px_raw": open_px_raw,
        "prev_is_yizi_dt": prev_is_yizi_dt,
        "prev_dt_to_sum": prev_dt_to_sum,
        "ret_pre5": ret_pre5,
        "ret_pre20": ret_pre20,
    }


def run_task2():
    t_start = time.time()
    print("[+] Loading cand_pry_limitdown.parquet & code_bars_5y.pkl...")
    df = pd.read_parquet(f"{MAT_DIR}/cand_pry_limitdown.parquet")
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f:
        cb = pickle.load(f)["code_bars"]

    # 1. 扩充新 PIT 因子
    print("[+] Extracting 90-day notices...")
    notice_feats = extract_90d_notices(df)
    for k, v in notice_feats.items():
        df[k] = v

    print("[+] Computing price bars & streak features...")
    cb_feats = compute_cb_features(df, cb)
    for k, v in cb_feats.items():
        df[k] = v

    # 补充日历特征
    df["buy_date_dt"] = pd.to_datetime(df["buy_date"])
    df["month"] = df["buy_date_dt"].dt.month
    df["weekday"] = df["buy_date_dt"].dt.weekday  # 0=Mon, 4=Fri
    df["is_month_1_or_4"] = df["month"].isin([1, 4])

    # 补充市值与筹码特征
    df["chip_lock_val"] = df["lock_top10"] * df["real_free_mcap"]
    df["mkt_panic_index"] = df["mkt_dt_prev"] / (df["mkt_zt_prev"] + 1.0)

    # 基础池过滤：非ST/退，股价 >= 2.0
    is_st_name = df["name"].str.contains("ST|退", na=False).values
    is_penny = df["open_px_raw"].values < 2.0
    base_mask = (~is_st_name) & (~is_penny)
    print(f"[+] Total candidates: {len(df)}, Base pool valid: {base_mask.sum()}")

    # 预计算买卖矩阵 (采用 B3_pry_lift_15pct + E6_cut_reseal_tp7_h3 作为标准基准，同时对比 B2+E5)
    print("[+] Precomputing execution outcomes...")
    pre = precompute_all_entries_and_exits(df, cb)

    # 构建基础流水
    prio_deep10 = -df["ret_pre10"].values.astype(float)
    tdf_base = build_trades_dataframe(df, pre, base_mask, "B3_pry_lift_15pct", "E6_cut_reseal_tp7_h3", prio_deep10)
    ev_base = eval_d15_all(tdf_base)

    base_avg_ret_5y = float(tdf_base["net_ret"].mean()) if len(tdf_base) else 0.0
    tdf_is = tdf_base[(tdf_base["buy_date"] >= "2022-01-04") & (tdf_base["buy_date"] <= "2024-12-31")]
    tdf_oos = tdf_base[(tdf_base["buy_date"] >= "2025-01-01") & (tdf_base["buy_date"] <= "2026-11-10")]
    base_avg_ret_is = float(tdf_is["net_ret"].mean()) if len(tdf_is) else 0.0
    base_avg_ret_oos = float(tdf_oos["net_ret"].mean()) if len(tdf_oos) else 0.0

    print(f"[+] Base Pool B3+E6 Stats: 5Y trades={len(tdf_base)}, IS avg_ret={base_avg_ret_is*100:.2f}%, OOS avg_ret={base_avg_ret_oos*100:.2f}%")

    # 2. 定义 180+ 个高颗粒度因子切片
    slices = []

    # A. 盘面恐慌与冰点环境 (30个切片)
    mkt_dt_cutoffs = [10, 15, 20, 25, 30, 40, 50, 60, 80, 100]
    for cut in mkt_dt_cutoffs:
        slices.append((f"F_mkt_dt_ge_{cut}", "Market_Panic", f"昨日跌停家数 >= {cut}", df["mkt_dt_prev"].values >= cut))
        slices.append((f"F_mkt_dt_lt_{cut}", "Market_Panic", f"昨日跌停家数 < {cut}", df["mkt_dt_prev"].values < cut))

    mkt_zt_cutoffs = [15, 20, 25, 30, 35, 40, 50]
    for cut in mkt_zt_cutoffs:
        slices.append((f"F_mkt_zt_lt_{cut}", "Market_Panic", f"昨日涨停家数 < {cut} (冰点)", df["mkt_zt_prev"].values < cut))
        slices.append((f"F_mkt_zt_ge_{cut}", "Market_Panic", f"昨日涨停家数 >= {cut}", df["mkt_zt_prev"].values >= cut))

    for p_cut in [0.5, 1.0, 1.5, 2.0]:
        slices.append((f"F_panic_idx_ge_{p_cut}", "Market_Panic", f"昨日跌停/涨停比 >= {p_cut}", df["mkt_panic_index"].values >= p_cut))
        slices.append((f"F_panic_idx_lt_{p_cut}", "Market_Panic", f"昨日跌停/涨停比 < {p_cut}", df["mkt_panic_index"].values < p_cut))

    # B. 妖股A杀 vs 纯超跌反弹 (20个切片)
    slices.append(("F_pure_ovs_zt0", "Dragon_Structure", "前20日无涨停(纯超跌)", df["zt_cnt_pre20"].values == 0))
    slices.append(("F_dragon_a_zt1_plus", "Dragon_Structure", "前20日有涨停(妖股/连板A杀)", df["zt_cnt_pre20"].values >= 1))
    slices.append(("F_dragon_a_zt2_plus", "Dragon_Structure", "前20日>=2次涨停(强妖股A杀)", df["zt_cnt_pre20"].values >= 2))
    slices.append(("F_dragon_a_zt3_plus", "Dragon_Structure", "前20日>=3次涨停(高标A杀)", df["zt_cnt_pre20"].values >= 3))
    slices.append(("F_dragon_a_zt5_plus", "Dragon_Structure", "前20日>=5次涨停(超级妖股A杀)", df["zt_cnt_pre20"].values >= 5))

    for streak in [1, 2, 3, 4, 5]:
        slices.append((f"F_prev_dt_streak_eq_{streak}", "Dragon_Structure", f"前期连续跌停正好 {streak} 天", df["prev_dt_streak"].values == streak))
        slices.append((f"F_prev_dt_streak_ge_{streak}", "Dragon_Structure", f"前期连续跌停 >= {streak} 天", df["prev_dt_streak"].values >= streak))

    slices.append(("F_prev_is_yizi_dt_true", "Dragon_Structure", "前一日无量一字跌停", df["prev_is_yizi_dt"].values == True))
    slices.append(("F_prev_is_yizi_dt_false", "Dragon_Structure", "前一日已开板放量跌停", df["prev_is_yizi_dt"].values == False))

    # C. 90日细粒度公告排雷与正向催化 (25个切片)
    slices.append(("F_notice_investigation_false", "Notices_Mine", "90日无立案调查", ~df["notice_90d_investigation"].values))
    slices.append(("F_notice_investigation_true", "Notices_Mine", "90日有立案调查", df["notice_90d_investigation"].values))
    slices.append(("F_notice_reduction_false", "Notices_Mine", "90日无减持计划", ~df["notice_90d_reduction"].values))
    slices.append(("F_notice_reduction_true", "Notices_Mine", "90日有减持计划", df["notice_90d_reduction"].values))
    slices.append(("F_notice_delist_risk_false", "Notices_Mine", "90日无退市风险提示", ~df["notice_90d_delist_risk"].values))
    slices.append(("F_notice_delist_risk_true", "Notices_Mine", "90日有退市风险提示", df["notice_90d_delist_risk"].values))
    slices.append(("F_notice_illegal_guar_false", "Notices_Mine", "90日无违规担保资金占用", ~df["notice_90d_illegal_guarantee"].values))
    slices.append(("F_notice_illegal_guar_true", "Notices_Mine", "90日有违规担保资金占用", df["notice_90d_illegal_guarantee"].values))
    slices.append(("F_notice_loss_down_false", "Notices_Mine", "90日无业绩预亏下修", ~df["notice_90d_loss_down"].values))
    slices.append(("F_notice_loss_down_true", "Notices_Mine", "90日有业绩预亏下修", df["notice_90d_loss_down"].values))
    slices.append(("F_notice_inquiry_false", "Notices_Mine", "90日无问询监管函", ~df["notice_90d_inquiry"].values))
    slices.append(("F_notice_inquiry_true", "Notices_Mine", "90日有问询监管函", df["notice_90d_inquiry"].values))
    slices.append(("F_notice_poison_any_false", "Notices_Mine", "90日无任何毒丸公告(纯净标的)", ~df["notice_90d_poison_any"].values))
    slices.append(("F_notice_poison_any_true", "Notices_Mine", "90日有任何毒丸公告", df["notice_90d_poison_any"].values))

    # 正向公告
    slices.append(("F_notice_buyback_true", "Notices_Positive", "90日有回购公告", df["notice_90d_buyback"].values))
    slices.append(("F_notice_increase_true", "Notices_Positive", "90日有股东增持公告", df["notice_90d_increase"].values))
    slices.append(("F_notice_bid_win_true", "Notices_Positive", "90日有中标/重大合同", df["notice_90d_bid_win"].values))
    slices.append(("F_notice_positive_any_true", "Notices_Positive", "90日有任何正向公告", df["notice_90d_positive_any"].values))
    slices.append(("F_notice_positive_any_false", "Notices_Positive", "90日无正向公告", ~df["notice_90d_positive_any"].values))

    # D. 股价分档与仙股排雷 (15个切片)
    slices.append(("F_px_tier_2_5", "Price_Tier", "股价 2.0 ~ 5.0 元", (df["open_px_raw"].values >= 2.0) & (df["open_px_raw"].values < 5.0)))
    slices.append(("F_px_tier_5_10", "Price_Tier", "股价 5.0 ~ 10.0 元", (df["open_px_raw"].values >= 5.0) & (df["open_px_raw"].values < 10.0)))
    slices.append(("F_px_tier_10_15", "Price_Tier", "股价 10.0 ~ 15.0 元", (df["open_px_raw"].values >= 10.0) & (df["open_px_raw"].values < 15.0)))
    slices.append(("F_px_tier_15_30", "Price_Tier", "股价 15.0 ~ 30.0 元", (df["open_px_raw"].values >= 15.0) & (df["open_px_raw"].values < 30.0)))
    slices.append(("F_px_tier_gt_30", "Price_Tier", "股价 > 30.0 元", df["open_px_raw"].values >= 30.0))
    slices.append(("F_px_tier_lt_15", "Price_Tier", "股价 < 15.0 元(中低价)", df["open_px_raw"].values < 15.0))
    slices.append(("F_px_tier_lt_10", "Price_Tier", "股价 < 10.0 元(低价)", df["open_px_raw"].values < 10.0))
    slices.append(("F_px_tier_ge_15", "Price_Tier", "股价 >= 15.0 元(中高价)", df["open_px_raw"].values >= 15.0))

    # E. 累计超跌幅度与回撤深度 (25个切片)
    for cut in [-0.15, -0.20, -0.25, -0.30, -0.35]:
        slices.append((f"F_ret_pre5_lt_{int(abs(cut)*100)}", "Oversold_Depth", f"前5日累计跌幅 < {int(cut*100)}%", df["ret_pre5"].values < cut))
        slices.append((f"F_ret_pre5_ge_{int(abs(cut)*100)}", "Oversold_Depth", f"前5日累计跌幅 >= {int(cut*100)}%", df["ret_pre5"].values >= cut))

    for cut in [-0.20, -0.25, -0.30, -0.35, -0.40]:
        slices.append((f"F_ret_pre10_lt_{int(abs(cut)*100)}", "Oversold_Depth", f"前10日累计跌幅 < {int(cut*100)}%", df["ret_pre10"].values < cut))
        slices.append((f"F_ret_pre10_ge_{int(abs(cut)*100)}", "Oversold_Depth", f"前10日累计跌幅 >= {int(cut*100)}%", df["ret_pre10"].values >= cut))

    for cut in [-0.25, -0.35, -0.45]:
        slices.append((f"F_ret_pre20_lt_{int(abs(cut)*100)}", "Oversold_Depth", f"前20日累计跌幅 < {int(cut*100)}%", df["ret_pre20"].values < cut))

    for cut in [-0.30, -0.40, -0.50]:
        slices.append((f"F_dd60_lt_{int(abs(cut)*100)}", "Oversold_Depth", f"60日最高点回撤 < {int(cut*100)}%", df["dd60"].values < cut))

    # F. 换手率与筹码换手充分度 (20个切片)
    for to_cut in [0.01, 0.02, 0.05, 0.10]:
        slices.append((f"F_prev_to_ge_{int(to_cut*100)}", "Turnover_Volume", f"前日换手率 >= {int(to_cut*100)}%", df["prev_to"].values >= to_cut))
        slices.append((f"F_prev_to_lt_{int(to_cut*100)}", "Turnover_Volume", f"前日换手率 < {int(to_cut*100)}%", df["prev_to"].values < to_cut))

    for to_sum_cut in [0.02, 0.05, 0.10, 0.20]:
        slices.append((f"F_prev_dt_to_sum_ge_{int(to_sum_cut*100)}", "Turnover_Volume", f"连跌期间累计换手 >= {int(to_sum_cut*100)}%", df["prev_dt_to_sum"].values >= to_sum_cut))
        slices.append((f"F_prev_dt_to_sum_lt_{int(to_sum_cut*100)}", "Turnover_Volume", f"连跌期间累计换手 < {int(to_sum_cut*100)}%", df["prev_dt_to_sum"].values < to_sum_cut))

    # G. 市值与流通筹码结构 (20个切片)
    for mcap_cut in [15.0, 30.0, 50.0, 100.0]:
        slices.append((f"F_free_mcap_lt_{int(mcap_cut)}e", "Capital_Structure", f"自由流通市值 < {int(mcap_cut)}亿", df["real_free_mcap"].values < mcap_cut))
        slices.append((f"F_free_mcap_ge_{int(mcap_cut)}e", "Capital_Structure", f"自由流通市值 >= {int(mcap_cut)}亿", df["real_free_mcap"].values >= mcap_cut))

    for lock_cut in [0.4, 0.5, 0.6]:
        slices.append((f"F_lock_top10_ge_{int(lock_cut*100)}", "Capital_Structure", f"前十大锁仓比例 >= {int(lock_cut*100)}%", df["lock_top10"].values >= lock_cut))
        slices.append((f"F_lock_top10_lt_{int(lock_cut*100)}", "Capital_Structure", f"前十大锁仓比例 < {int(lock_cut*100)}%", df["lock_top10"].values < lock_cut))

    # H. 席位与热度特征 (15个切片)
    slices.append(("F_lhasa_seats_eq_0", "Sentiment_Seats", "前日龙虎榜无拉萨席位", df["lhasa_seats_prev"].values == 0))
    slices.append(("F_lhasa_seats_ge_1", "Sentiment_Seats", "前日龙虎榜有拉萨席位", df["lhasa_seats_prev"].values >= 1))
    slices.append(("F_lhasa_seats_ge_3", "Sentiment_Seats", "前日龙虎榜拉萨席位>=3(散户扎堆)", df["lhasa_seats_prev"].values >= 3))
    slices.append(("F_comm_posts_lt_50", "Sentiment_Seats", "社区讨论热度 < 50 (无人问津冷门)", df["comm_posts_24h"].values < 50))
    slices.append(("F_comm_posts_50_200", "Sentiment_Seats", "社区讨论热度 50 ~ 200", (df["comm_posts_24h"].values >= 50) & (df["comm_posts_24h"].values < 200)))
    slices.append(("F_comm_posts_ge_200", "Sentiment_Seats", "社区讨论热度 >= 200 (散户高热度)", df["comm_posts_24h"].values >= 200))
    slices.append(("F_has_ir_8d_true", "Sentiment_Seats", "前8日有机构调研", df["has_ir_8d"].values == 1))
    slices.append(("F_has_ir_8d_false", "Sentiment_Seats", "前8日无机构调研", df["has_ir_8d"].values == 0))

    # I. 日历与月份效应 (15个切片)
    slices.append(("F_is_month_1_or_4_true", "Calendar_Effect", "1月或4月(年报季报雷区)", df["is_month_1_or_4"].values == True))
    slices.append(("F_is_month_1_or_4_false", "Calendar_Effect", "避开1月和4月(非财报雷区)", df["is_month_1_or_4"].values == False))
    for w in [0, 1, 2, 3, 4]:
        w_names = ["周一", "周二", "周三", "周四", "周五"]
        slices.append((f"F_weekday_{w}", "Calendar_Effect", f"{w_names[w]}撬板", df["weekday"].values == w))

    # J. 大盘中期趋势联动 (15个切片)
    for csi_cut in [-0.03, -0.01, 0.0, 0.02]:
        slices.append((f"F_csi5_lt_{int(abs(csi_cut)*100)}", "Macro_Index", f"沪深300近5日收益 < {csi_cut*100:.1f}%", df["csi300_ret5"].values < csi_cut))
        slices.append((f"F_csi5_ge_{int(abs(csi_cut)*100)}", "Macro_Index", f"沪深300近5日收益 >= {csi_cut*100:.1f}%", df["csi300_ret5"].values >= csi_cut))

    # K. 高阶复合交叉因子 (35个切片)
    slices.append(("F_combo_pure_ovs_panic20", "Composite_Cross", "纯超跌(前20无涨停) + 昨日跌停>=20", (df["zt_cnt_pre20"].values == 0) & (df["mkt_dt_prev"].values >= 20)))
    slices.append(("F_combo_pure_ovs_panic30", "Composite_Cross", "纯超跌 + 昨日跌停>=30", (df["zt_cnt_pre20"].values == 0) & (df["mkt_dt_prev"].values >= 30)))
    slices.append(("F_combo_pure_ovs_panic40", "Composite_Cross", "纯超跌 + 昨日跌停>=40 (超级错杀)", (df["zt_cnt_pre20"].values == 0) & (df["mkt_dt_prev"].values >= 40)))
    slices.append(("F_combo_pure_ovs_no_poison", "Composite_Cross", "纯超跌 + 90日无毒丸公告", (df["zt_cnt_pre20"].values == 0) & (~df["notice_90d_poison_any"].values)))
    slices.append(("F_combo_panic20_no_poison", "Composite_Cross", "昨日跌停>=20 + 90日无毒丸公告", (df["mkt_dt_prev"].values >= 20) & (~df["notice_90d_poison_any"].values)))
    slices.append(("F_combo_panic20_safe_month", "Composite_Cross", "昨日跌停>=20 + 避开1/4月雷区", (df["mkt_dt_prev"].values >= 20) & (~df["is_month_1_or_4"].values)))
    slices.append(("F_combo_panic20_deep10", "Composite_Cross", "昨日跌停>=20 + 前10日跌幅<-25%", (df["mkt_dt_prev"].values >= 20) & (df["ret_pre10"].values < -0.25)))
    slices.append(("F_combo_panic20_unsealed", "Composite_Cross", "昨日跌停>=20 + 前一日已放量非一字", (df["mkt_dt_prev"].values >= 20) & (df["prev_is_yizi_dt"].values == False)))
    slices.append(("F_combo_pure_ovs_deep10_panic20", "Composite_Cross", "纯超跌 + 前10日跌幅<-25% + 跌停>=20", (df["zt_cnt_pre20"].values == 0) & (df["ret_pre10"].values < -0.25) & (df["mkt_dt_prev"].values >= 20)))
    slices.append(("F_combo_golden_triple", "Composite_Cross", "黄金三重核: 纯超跌 + 无毒丸 + 跌停>=20", (df["zt_cnt_pre20"].values == 0) & (~df["notice_90d_poison_any"].values) & (df["mkt_dt_prev"].values >= 20)))
    slices.append(("F_combo_golden_quad", "Composite_Cross", "黄金四重核: 纯超跌 + 无毒丸 + 跌停>=20 + 避开1/4月", (df["zt_cnt_pre20"].values == 0) & (~df["notice_90d_poison_any"].values) & (df["mkt_dt_prev"].values >= 20) & (~df["is_month_1_or_4"].values)))
    slices.append(("F_combo_golden_penta", "Composite_Cross", "黄金五重核: 纯超跌 + 无毒丸 + 跌停>=20 + 避开1/4月 + 股价<15元", (df["zt_cnt_pre20"].values == 0) & (~df["notice_90d_poison_any"].values) & (df["mkt_dt_prev"].values >= 20) & (~df["is_month_1_or_4"].values) & (df["open_px_raw"].values < 15.0)))
    slices.append(("F_combo_positive_panic", "Composite_Cross", "有正向公告(回购/增持/中标) + 跌停>=20", (df["notice_90d_positive_any"].values) & (df["mkt_dt_prev"].values >= 20)))
    slices.append(("F_combo_positive_pure_ovs", "Composite_Cross", "有正向公告 + 纯超跌", (df["notice_90d_positive_any"].values) & (df["zt_cnt_pre20"].values == 0)))
    slices.append(("F_combo_dragon_slaughter_mine", "Composite_Cross", "高危双雷: 妖股A杀(zt>=2) + 有毒丸公告", (df["zt_cnt_pre20"].values >= 2) & (df["notice_90d_poison_any"].values)))
    slices.append(("F_combo_unsealed_deep10", "Composite_Cross", "前日已放量 + 前10日跌幅<-25%", (df["prev_is_yizi_dt"].values == False) & (df["ret_pre10"].values < -0.25)))

    print(f"[+] Total factor slices generated: {len(slices)}")

    # 3. 逐个切片计算 D15 全套指标与 IS/OOS 边际贡献
    catalog_rows = []
    for name, cat, desc, condition_mask in slices:
        sub_mask = base_mask & condition_mask
        tdf_sub = build_trades_dataframe(df, pre, sub_mask, "B3_pry_lift_15pct", "E6_cut_reseal_tp7_h3", prio_deep10)

        n_raw = len(tdf_sub)
        if n_raw == 0:
            continue

        rets = tdf_sub["net_ret"].values
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        wr_raw = float(len(wins) / n_raw * 100.0)
        po_raw = float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) and losses.mean() < 0 else 0.0
        avg_ret_raw = float(rets.mean() * 100.0)

        # IS 切片
        tdf_sub_is = tdf_sub[(tdf_sub["buy_date"] >= "2022-01-04") & (tdf_sub["buy_date"] <= "2024-12-31")]
        n_is = len(tdf_sub_is)
        avg_ret_is = float(tdf_sub_is["net_ret"].mean() * 100.0) if n_is else 0.0
        delta_is = round(avg_ret_is - base_avg_ret_is * 100.0, 2)

        # OOS 切片
        tdf_sub_oos = tdf_sub[(tdf_sub["buy_date"] >= "2025-01-01") & (tdf_sub["buy_date"] <= "2026-11-10")]
        n_oos = len(tdf_sub_oos)
        avg_ret_oos = float(tdf_sub_oos["net_ret"].mean() * 100.0) if n_oos else 0.0
        delta_oos = round(avg_ret_oos - base_avg_ret_oos * 100.0, 2)

        # 双期同向增益判定 (IS 与 OOS 均跑赢基础池)
        dual_same_sign = (delta_is > 0) and (delta_oos > 0) and (n_is >= 3) and (n_oos >= 2)

        # 运行 D15 完整评测
        ev = eval_d15_all(tdf_sub)
        f5 = ev.get("full_5y", {})
        is_m = ev.get("is_2022_2024", {})
        oos_m = ev.get("oos_2025_2026", {})
        h2 = ev.get("half2_5y", {})

        catalog_rows.append({
            "factor_name": name,
            "category": cat,
            "description": desc,
            "raw_n_5y": n_raw,
            "raw_wr_pct": round(wr_raw, 2),
            "raw_payoff": round(po_raw, 2),
            "avg_ret_pct": round(avg_ret_raw, 2),
            "delta_is_vs_base": delta_is,
            "delta_oos_vs_base": delta_oos,
            "dual_period_same_sign": dual_same_sign,
            # 单仓 5Y
            "ss_n_5y": f5.get("single_n", 0),
            "ss_wr_5y": f5.get("wr", 0.0),
            "ss_payoff_5y": f5.get("payoff", 0.0),
            "ss_nav_5y": f5.get("single_nav", 1.0),
            "ss_mdd_5y": f5.get("single_mdd_pct", 0.0),
            "ss_trimmed3_nav_5y": f5.get("trimmed3_nav", 1.0),
            "ss_trimmed5_nav_5y": f5.get("trimmed5_nav", 1.0),
            "ss_excess_csi300_5y": f5.get("single_excess_pct", 0.0),
            # 双半仓 5Y
            "h2_nav_5y": h2.get("nav", 1.0),
            "h2_mdd_5y": h2.get("mdd_pct", 0.0),
            # 按日等权 5Y
            "eq_nav_5y": f5.get("eq_nav", 1.0),
            "eq_mdd_5y": f5.get("eq_mdd_pct", 0.0),
            # IS (2022-2024)
            "is_single_n": is_m.get("single_n", 0),
            "is_single_wr": is_m.get("wr", 0.0),
            "is_single_payoff": is_m.get("payoff", 0.0),
            "is_single_nav": is_m.get("single_nav", 1.0),
            "is_single_excess": is_m.get("single_excess_pct", 0.0),
            # OOS (2025-2026)
            "oos_single_n": oos_m.get("single_n", 0),
            "oos_single_wr": oos_m.get("wr", 0.0),
            "oos_single_payoff": oos_m.get("payoff", 0.0),
            "oos_single_nav": oos_m.get("single_nav", 1.0),
            "oos_single_excess": oos_m.get("single_excess_pct", 0.0),
        })

    df_catalog = pd.DataFrame(catalog_rows)
    # 按 5Y 单仓净值与双期同向排序
    df_catalog = df_catalog.sort_values(["dual_period_same_sign", "ss_nav_5y", "ss_payoff_5y"], ascending=[False, False, False])

    out_csv = f"{WORK_DIR}/p1_oversold_factor_catalog.csv"
    df_catalog.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"[+] Successfully evaluated {len(df_catalog)} factor slices!")
    print(f"[+] Saved factor catalog to: {out_csv} (Elapsed: {time.time()-t_start:.1f}s)")

    # 打印前 15 大正向有效因子
    print("\n=== Top 15 Effective Factors with Dual-Period Alpha ===")
    top15 = df_catalog[df_catalog["dual_period_same_sign"]].head(15)
    cols_show = ["factor_name", "description", "ss_n_5y", "ss_wr_5y", "ss_payoff_5y", "ss_nav_5y", "is_single_nav", "oos_single_nav"]
    print(top15[cols_show].to_string(index=False))


if __name__ == "__main__":
    run_task2()
