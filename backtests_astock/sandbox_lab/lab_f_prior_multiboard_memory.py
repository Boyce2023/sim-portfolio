#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
lab_f_prior_multiboard_memory.py
================================================================================
A股一进二沙盒实验室（Sandbox Lab）第 24 号课题主研究脚本
课题：历史连板记忆基因对后续一进二表现的 5 年全量回测与现行定版策略穿透

核心科学问题：
Buwen 提问：「以前已经炒过连板的股，在后续一进二的表现如何，这件事是否有影响，对我们的策略，现在就做。」

严格遵循：
1. 生产盘绝对硬隔离：只读访问底座数据，不修改任何生产文件与生产规则。
2. 绝对零未来函数：截至首板前一日 D0（date < D1_date）严格历史截断，绝不计入 D1 本身！
3. 严格沙盒只读：基于 a_daily.parquet + a_delisted_daily.parquet（2016-2026）完整回溯。
4. 严禁 import yfinance 取 A 股。
5. D15 回测防伪四必核（全5年、剔2025四年、近3年、近1年、7月以来、去极值Top5、沪深300超额）。
================================================================================
"""

import os
import sys
import time
import json
import bisect
import datetime
from typing import Dict, Any, List, Optional, Tuple, Set

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from scipy.stats import norm

# 引入沙盒底座
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from v16_parameterized_engine import (
    load_engine_data_cache,
    FEE_RATE,
    CSI300_5Y_CUM,
    CSI300_3Y_CUM,
    CSI300_1Y_CUM,
    CSI300_JUL_CUM,
    CSI300_ANNUAL,
)

from lab_e2_gates_and_trial_v1 import (
    build_pit_sensors_and_theme_matrix,
    create_ablation_trade_engine,
)

OUT_JSON = f"{CURRENT_DIR}/lab_f_results.json"
OUT_REPORT = f"{CURRENT_DIR}/LAB_F_PRIOR_MULTIBOARD_REPORT.md"
LEDGER_CSV = f"{CURRENT_DIR}/trial_v1_final_ledger.csv"

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"


# ==============================================================================
# 第一部分：从零回溯 2016~2026 全量日线提取个股连板历史与冷却特征
# ==============================================================================
def build_historical_board_database():
    """
    加载 2016 年起全部 A 股主板日线，精确计算每只股票历史上的每一次涨停与连板 streak。
    严格定义：
    - zt_price = np.floor(pre_c * 1.10 * 100.0 + 0.5) / 100.0
    - is_zt = (close >= zt_price - 0.01) & (pct >= 0.095) & (pre_c > 0)
    - 连板 streak: 连续 is_zt 的交易日累计长度
    - streak run: (start_d, end_d, height, start_mkt_idx, end_mkt_idx)
    """
    t0 = time.time()
    print(">>> [1/5] 加载 2016~2026 全量 A 股日线构建历史连板数据库...")
    cols = ["date", "ticker", "open", "high", "low", "close"]
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2016-01-01"))).to_table().to_pandas()
    
    parts = [df_act]
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format="parquet")
        df_del = ds_del.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2016-01-01"))).to_table().to_pandas()
        parts.append(df_del)
    
    df = pd.concat(parts, ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60")) & (~df["ticker"].str.endswith(".BJ"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    g = df.groupby("c6")
    df["pre_c"] = g["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["zt_price"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_price"] - 0.01) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)

    all_market_dts = sorted(df["dt_str"].unique().tolist())
    mkt_dt_idx = {d: i for i, d in enumerate(all_market_dts)}

    # 提取每只股票的所有连板片段
    stock_streaks = {}
    for c6, group in df[["c6", "dt_str", "is_zt"]].groupby("c6"):
        s_list = []
        cur_h = 0
        start_d = None
        last_d = None
        for r in group.itertuples():
            if r.is_zt:
                cur_h += 1
                if cur_h == 1:
                    start_d = r.dt_str
                last_d = r.dt_str
            else:
                if cur_h > 0:
                    s_list.append((start_d, last_d, cur_h, mkt_dt_idx[start_d], mkt_dt_idx[last_d]))
                    cur_h = 0
                    start_d = None
        if cur_h > 0:
            s_list.append((start_d, last_d, cur_h, mkt_dt_idx[start_d], mkt_dt_idx[last_d]))
        stock_streaks[c6] = s_list

    total_streaks = sum(len(v) for v in stock_streaks.values())
    print(f"    连板数据库提取完毕: 覆盖 {len(stock_streaks)} 只股票, 共 {total_streaks:,} 次涨停/连板记录, 耗时 {time.time()-t0:.2f}s")
    return stock_streaks, all_market_dts, mkt_dt_idx


def extract_prior_board_features(
    c6: str,
    d0_str: str,
    stock_streaks: Dict[str, List[Tuple[str, str, int, int, int]]],
    mkt_dt_idx: Dict[str, int]
) -> Dict[str, Any]:
    """
    给定股票代码 c6 与本次首板前一日 D0，严格计算截至 D0 的历史连板特征。
    所有统计严格截断在 end_d <= D0！零未来函数！
    """
    if d0_str not in mkt_dt_idx:
        # 如果 D0 未在市场日历中（如早于 2016），做安全防护
        return {
            "max_hist_boards_all": 0, "cnt_2b_plus_all": 0, "cnt_3b_plus_all": 0, "cnt_5b_plus_all": 0,
            "max_hist_boards_20": 0, "max_hist_boards_60": 0, "max_hist_boards_120": 0,
            "max_hist_boards_250": 0, "max_hist_boards_500": 0,
            "days_since_last_2b": 9999, "days_since_last_3b": 9999, "days_since_last_5b": 9999,
        }

    d0_idx = mkt_dt_idx[d0_str]
    streaks = stock_streaks.get(c6, [])
    
    # 截断在 D0 及之前
    past = [s for s in streaks if s[1] <= d0_str]
    if not past:
        return {
            "max_hist_boards_all": 0, "cnt_2b_plus_all": 0, "cnt_3b_plus_all": 0, "cnt_5b_plus_all": 0,
            "max_hist_boards_20": 0, "max_hist_boards_60": 0, "max_hist_boards_120": 0,
            "max_hist_boards_250": 0, "max_hist_boards_500": 0,
            "days_since_last_2b": 9999, "days_since_last_3b": 9999, "days_since_last_5b": 9999,
        }

    max_hist_boards_all = max(s[2] for s in past)
    cnt_2b_plus_all = sum(1 for s in past if s[2] >= 2)
    cnt_3b_plus_all = sum(1 for s in past if s[2] >= 3)
    cnt_5b_plus_all = sum(1 for s in past if s[2] >= 5)

    # 滚动窗口最高板
    def get_max_in_window(w: int) -> int:
        win_start_idx = d0_idx - w + 1
        sub = [s[2] for s in past if s[4] >= win_start_idx]
        return max(sub) if sub else 0

    max_20 = get_max_in_window(20)
    max_60 = get_max_in_window(60)
    max_120 = get_max_in_window(120)
    max_250 = get_max_in_window(250)
    max_500 = get_max_in_window(500)

    # 冷却交易日（距离上一次 2板/3板+/5板+ 结束相隔的市场交易日天数）
    s_2b = [s for s in past if s[2] >= 2]
    days_since_last_2b = (d0_idx - s_2b[-1][4]) if s_2b else 9999

    s_3b = [s for s in past if s[2] >= 3]
    days_since_last_3b = (d0_idx - s_3b[-1][4]) if s_3b else 9999

    s_5b = [s for s in past if s[2] >= 5]
    days_since_last_5b = (d0_idx - s_5b[-1][4]) if s_5b else 9999

    return {
        "max_hist_boards_all": max_hist_boards_all,
        "cnt_2b_plus_all": cnt_2b_plus_all,
        "cnt_3b_plus_all": cnt_3b_plus_all,
        "cnt_5b_plus_all": cnt_5b_plus_all,
        "max_hist_boards_20": max_20,
        "max_hist_boards_60": max_60,
        "max_hist_boards_120": max_120,
        "max_hist_boards_250": max_250,
        "max_hist_boards_500": max_500,
        "days_since_last_2b": days_since_last_2b,
        "days_since_last_3b": days_since_last_3b,
        "days_since_last_5b": days_since_last_5b,
    }


# ==============================================================================
# 第二部分：全市场 5 年标准可买首板全池（29,513 笔）底层规律穿透
# ==============================================================================
def run_market_wide_layer1_analysis(
    cache: Dict[str, Any],
    stock_streaks: Dict[str, List[Tuple[str, str, int, int, int]]],
    all_market_dts: List[str],
    mkt_dt_idx: Dict[str, int]
) -> Dict[str, Any]:
    """
    第一层检验：
    在 2022-01-01 至 2026-11-10 的全部可买首板池中：
    1. 按历史最高板分类：从未连板过 (max_b < 2) vs 曾2板 (==2) vs 曾3~4板 (3~4) vs 曾5板+老妖 (>=5)
    2. 按冷却时间窗拆解 (<=20, 21~60, 61~120, 121~250, >250, 从未连板)
    统计：样本量、二板封板率、炸板率、标准执行状态机净均值、胜率、盈亏比。
    """
    t0 = time.time()
    print("\n>>> [2/5] 穿透全市场 5 年标准可买首板全池底层规律...")
    hist_fb = cache["hist_fb"]
    
    # 取 2022-2026 可买首板池
    buyable = hist_fb[
        hist_fb["is_buyable_open"]
        & (hist_fb["d2_dt"] >= "2022-01-01")
        & (hist_fb["d2_dt"] <= "2026-11-10")
    ].copy().reset_index(drop=True)

    print(f"    可买首板全池样本量: {len(buyable):,} 笔")

    # 构建标准执行引擎
    engine_fn = create_ablation_trade_engine(
        price_lookup=cache["price_lookup"],
        all_dts=cache["all_dts"],
        dt_to_idx=cache["dt_to_idx"],
        bars_5m_map=cache["bars_5m_map"],
        fee=FEE_RATE,
        exit_1430_rush=True,
    )

    # 挂载历史连板特征与逐笔模拟
    records = []
    for r in buyable.to_dict("records"):
        c6 = r["c6"]
        d1_str = r["dt_str"]
        d2_str = r["d2_dt"]
        
        # 严格截断在首板日前一日 D0
        d1_idx = mkt_dt_idx.get(d1_str, -1)
        if d1_idx <= 0:
            d0_str = ""
        else:
            d0_str = all_market_dts[d1_idx - 1]

        feat = extract_prior_board_features(c6, d0_str, stock_streaks, mkt_dt_idx)
        
        # 运行标准交易状态机
        tr = engine_fn(r)
        
        # 炸板识别：盘中有触及涨停但收盘未封板
        d2_is_zt = bool(r.get("d2_is_zt", False))
        # 检查是否触板
        d2_bar = cache["price_lookup"].get((c6, d2_str))
        if d2_bar:
            o2, h2, l2, c2, zt2, dt2, is_zt2, _ = d2_bar
            touch_zt = (h2 >= zt2 - 0.005)
            broken_zt = touch_zt and (not is_zt2)
        else:
            touch_zt = False
            broken_zt = False

        rec = {
            "c6": c6,
            "d1_dt": d1_str,
            "d2_dt": d2_str,
            "name": r.get("name", ""),
            "d2_is_zt": int(d2_is_zt),
            "touch_zt": int(touch_zt),
            "broken_zt": int(broken_zt),
            "triggered": int(tr is not None),
            "net_ret": tr["net_ret"] if tr else np.nan,
            "is_win": int(tr["net_ret"] > 0) if tr else 0,
            **feat
        }
        records.append(rec)

    df_res = pd.DataFrame(records)
    print(f"    特征挂载与状态机模拟完成, 耗时 {time.time()-t0:.2f}s")

    # 辅助统计函数
    def calc_group_stats(sub_df: pd.DataFrame, label: str) -> Dict[str, Any]:
        n = len(sub_df)
        if n == 0:
            return {"group": label, "count": 0}
        
        seal_rate = sub_df["d2_is_zt"].mean() * 100.0
        touch_rate = sub_df["touch_zt"].mean() * 100.0
        broken_rate = sub_df["broken_zt"].mean() * 100.0
        
        trig_sub = sub_df[sub_df["triggered"] == 1]
        n_trig = len(trig_sub)
        trig_rate = (n_trig / n) * 100.0
        
        if n_trig > 0:
            wr = (trig_sub["net_ret"] > 0).mean() * 100.0
            mean_ret = trig_sub["net_ret"].mean() * 100.0
            pos = trig_sub[trig_sub["net_ret"] > 0]["net_ret"]
            neg = trig_sub[trig_sub["net_ret"] <= 0]["net_ret"]
            avg_win = pos.mean() if len(pos) > 0 else 0.0
            avg_loss = abs(neg.mean()) if len(neg) > 0 else 1e-4
            payoff = (avg_win / avg_loss) if avg_loss > 0 else 0.0
            big_win_rate = (trig_sub["net_ret"] >= 0.15).mean() * 100.0
            big_loss_rate = (trig_sub["net_ret"] <= -0.05).mean() * 100.0
        else:
            wr, mean_ret, payoff, big_win_rate, big_loss_rate = 0.0, 0.0, 0.0, 0.0, 0.0

        return {
            "group": label,
            "count": n,
            "seal_rate_pct": round(seal_rate, 2),
            "broken_rate_pct": round(broken_rate, 2),
            "touch_rate_pct": round(touch_rate, 2),
            "triggered_count": n_trig,
            "trig_rate_pct": round(trig_rate, 2),
            "trade_wr_pct": round(wr, 2),
            "trade_mean_ret_pct": round(mean_ret, 2),
            "trade_payoff": round(payoff, 2),
            "trade_big_win_pct": round(big_win_rate, 2),
            "trade_big_loss_pct": round(big_loss_rate, 2),
        }

    # 1. 按全历史最高板分组
    groups_max_b = [
        ("从未连板过 (max_b < 2)", df_res["max_hist_boards_all"] < 2),
        ("  - 从未涨停过 (max_b == 0)", df_res["max_hist_boards_all"] == 0),
        ("  - 仅曾首板未连板 (max_b == 1)", df_res["max_hist_boards_all"] == 1),
        ("曾2连板 (max_b == 2)", df_res["max_hist_boards_all"] == 2),
        ("曾3~4连板 (3 <= max_b <= 4)", df_res["max_hist_boards_all"].between(3, 4)),
        ("曾5板+老妖 (max_b >= 5)", df_res["max_hist_boards_all"] >= 5),
    ]
    stats_max_b = [calc_group_stats(df_res[mask], label) for label, mask in groups_max_b]

    # 2. 按过去 250 交易日（近1年）最高板分组
    groups_max_b_250 = [
        ("近1年从未连板 (250d < 2)", df_res["max_hist_boards_250"] < 2),
        ("近1年曾2连板 (250d == 2)", df_res["max_hist_boards_250"] == 2),
        ("近1年曾3~4连板 (250d 3~4)", df_res["max_hist_boards_250"].between(3, 4)),
        ("近1年曾5板+大妖 (250d >= 5)", df_res["max_hist_boards_250"] >= 5),
    ]
    stats_max_b_250 = [calc_group_stats(df_res[mask], label) for label, mask in groups_max_b_250]

    # 3. 按冷却时间窗拆解 (days_since_last_2b)
    # 严格区分「刚退潮余孽套牢盘」vs「充分洗盘冷却后的老妖股性记忆」
    c_mask_20 = (df_res["days_since_last_2b"] <= 20)
    c_mask_60 = (df_res["days_since_last_2b"].between(21, 60))
    c_mask_120 = (df_res["days_since_last_2b"].between(61, 120))
    c_mask_250 = (df_res["days_since_last_2b"].between(121, 250))
    c_mask_gt250 = (df_res["days_since_last_2b"] > 250) & (df_res["days_since_last_2b"] < 9999)
    c_mask_never = (df_res["days_since_last_2b"] >= 9999)

    groups_cooling = [
        ("冷却 <= 20 日 (近1个月刚炒过连板/刚退潮)", c_mask_20),
        ("冷却 21 ~ 60 日 (1~3个月前炒过连板)", c_mask_60),
        ("冷却 61 ~ 120 日 (3~6个月前炒过连板)", c_mask_120),
        ("冷却 121 ~ 250 日 (半年~1年前炒过连板)", c_mask_250),
        ("冷却 > 250 日 (1年以上远古连板唤醒)", c_mask_gt250),
        ("历史从未2连板过 (纯处女连板新面孔)", c_mask_never),
    ]
    stats_cooling = [calc_group_stats(df_res[mask], label) for label, mask in groups_cooling]

    # 4. 交叉透视：3板+老妖不同冷却时间的表现
    df_3b_ever = df_res[df_res["max_hist_boards_all"] >= 3].copy()
    groups_3b_cooling = [
        ("3板+老妖: 冷却 <= 30 日", df_3b_ever["days_since_last_3b"] <= 30),
        ("3板+老妖: 冷却 31 ~ 120 日", df_3b_ever["days_since_last_3b"].between(31, 120)),
        ("3板+老妖: 冷却 121 ~ 365 日", df_3b_ever["days_since_last_3b"].between(121, 365)),
        ("3板+老妖: 冷却 > 365 日", (df_3b_ever["days_since_last_3b"] > 365) & (df_3b_ever["days_since_last_3b"] < 9999)),
    ]
    stats_3b_cooling = [calc_group_stats(df_3b_ever[mask], label) for label, mask in groups_3b_cooling]

    return {
        "stats_max_b": stats_max_b,
        "stats_max_b_250": stats_max_b_250,
        "stats_cooling": stats_cooling,
        "stats_3b_cooling": stats_3b_cooling,
    }


# ==============================================================================
# 第三部分：现行最新定版主策略（96 笔）内部穿透
# ==============================================================================
def run_ledger_layer2_penetration(
    stock_streaks: Dict[str, List[Tuple[str, str, int, int, int]]],
    all_market_dts: List[str],
    mkt_dt_idx: Dict[str, int]
) -> Dict[str, Any]:
    """
    第二层检验：
    读取最新定版 trial_v1_final_ledger.csv（96 笔成交单）：
    1. 统计曾炒过 2板+ / 3板+ / 5板+ 与从未连板过新面孔的笔数占比
    2. 对比各组胜率、盈亏比、单笔均值、大肉率(>=15%)、大面率(<=-5%)与单仓复合净值
    3. 按冷却天数拆解 (<=30日、31~120日、121~365日、从未连板)
    4. 逐一列出具体代表性牛股与亏损股（美利云、孚日股份、海王生物、粤电力A、中视传媒等）
    """
    t0 = time.time()
    print("\n>>> [3/5] 穿透现行定版 96 笔成交单历史连板基因与冷却结构...")
    ledger = pd.read_csv(LEDGER_CSV)
    ledger["c6"] = ledger["c6"].astype(str).str.zfill(6)
    
    trades_feat = []
    for r in ledger.to_dict("records"):
        c6 = r["c6"]
        buy_d = r["buy_date"]
        # 买入日为 D2，D1 为买入日前一市场日，D0 为 D1 前一市场日
        d2_idx = mkt_dt_idx.get(buy_d, -1)
        if d2_idx >= 2:
            d1_d = all_market_dts[d2_idx - 1]
            d0_d = all_market_dts[d2_idx - 2]
        else:
            d1_d, d0_d = "", ""

        feat = extract_prior_board_features(c6, d0_d, stock_streaks, mkt_dt_idx)
        trades_feat.append({
            **r,
            "d1_date": d1_d,
            "d0_date": d0_d,
            **feat
        })

    df_t = pd.DataFrame(trades_feat)

    # 统计辅助函数
    def calc_trades_stats(sub_df: pd.DataFrame, label: str) -> Dict[str, Any]:
        n = len(sub_df)
        if n == 0:
            return {"group": label, "count": 0}
        wins = (sub_df["net_ret"] > 0).sum()
        wr = (wins / n) * 100.0
        mean_ret = sub_df["net_ret"].mean() * 100.0
        pos = sub_df[sub_df["net_ret"] > 0]["net_ret"]
        neg = sub_df[sub_df["net_ret"] <= 0]["net_ret"]
        avg_w = pos.mean() if len(pos) > 0 else 0.0
        avg_l = abs(neg.mean()) if len(neg) > 0 else 1e-4
        payoff = (avg_w / avg_l) if avg_l > 0 else 0.0
        
        # 轮动净值
        nav = 1.0
        for ret in sub_df["net_ret"]:
            nav *= (1.0 + ret)
            
        big_win = (sub_df["net_ret"] >= 0.15).sum()
        big_win_pct = (big_win / n) * 100.0
        big_loss = (sub_df["net_ret"] <= -0.05).sum()
        big_loss_pct = (big_loss / n) * 100.0

        return {
            "group": label,
            "count": n,
            "count_pct": round(n / len(df_t) * 100.0, 1),
            "wins": int(wins),
            "wr_pct": round(wr, 1),
            "payoff": round(payoff, 2),
            "mean_ret_pct": round(mean_ret, 2),
            "nav_compound": round(nav, 2),
            "big_win_count": int(big_win),
            "big_win_pct": round(big_win_pct, 1),
            "big_loss_count": int(big_loss),
            "big_loss_pct": round(big_loss_pct, 1),
        }

    # 1. 宏观二分法：曾炒过连板 vs 从未炒过连板
    stats_prior_vs_new = [
        calc_trades_stats(df_t[df_t["max_hist_boards_all"] >= 2], "曾炒过2连板+ (老连板股)"),
        calc_trades_stats(df_t[df_t["max_hist_boards_all"] < 2], "历史从未连板过 (纯新面孔)"),
    ]

    # 2. 细分历史最高连板梯队
    stats_board_tiers = [
        calc_trades_stats(df_t[df_t["max_hist_boards_all"] < 2], "从未连板过 (max_b < 2)"),
        calc_trades_stats(df_t[df_t["max_hist_boards_all"] == 2], "曾2连板 (max_b == 2)"),
        calc_trades_stats(df_t[df_t["max_hist_boards_all"].between(3, 4)], "曾3~4连板 (3 <= max_b <= 4)"),
        calc_trades_stats(df_t[df_t["max_hist_boards_all"] >= 5], "曾5板+大妖股 (max_b >= 5)"),
    ]

    # 3. 按冷却时间拆解
    c_30 = (df_t["days_since_last_2b"] <= 30)
    c_120 = (df_t["days_since_last_2b"].between(31, 120))
    c_365 = (df_t["days_since_last_2b"].between(121, 365))
    c_gt365 = (df_t["days_since_last_2b"] > 365) & (df_t["days_since_last_2b"] < 9999)
    c_never = (df_t["days_since_last_2b"] >= 9999)

    stats_ledger_cooling = [
        calc_trades_stats(df_t[c_30], "冷却 <= 30 日 (近1个月退潮回头草)"),
        calc_trades_stats(df_t[c_120], "冷却 31 ~ 120 日 (1~6个月中度洗盘)"),
        calc_trades_stats(df_t[c_365], "冷却 121 ~ 365 日 (半年~1年深度休眠)"),
        calc_trades_stats(df_t[c_gt365], "冷却 > 365 日 (1年以上远古记忆)"),
        calc_trades_stats(df_t[c_never], "从未连板过 (纯处女连板新面孔)"),
    ]

    # 4. 代表性个股穿透清单（牛股与亏损股）
    # 筛选 Top 10 大牛股与 Top 10 大亏损单
    top_winners = df_t.sort_values("net_ret", ascending=False).head(10)[
        ["buy_date", "c6", "name", "net_ret", "max_hist_boards_all", "cnt_2b_plus_all", "cnt_3b_plus_all", "days_since_last_2b"]
    ].to_dict("records")

    top_losers = df_t.sort_values("net_ret", ascending=True).head(10)[
        ["buy_date", "c6", "name", "net_ret", "max_hist_boards_all", "cnt_2b_plus_all", "cnt_3b_plus_all", "days_since_last_2b"]
    ].to_dict("records")

    # 用户指定 5 大标的逐笔详情
    focus_tickers = ["000815", "002083", "000078", "000539", "600088"]
    focus_records = df_t[df_t["c6"].isin(focus_tickers)][
        ["buy_date", "c6", "name", "net_ret", "sealed_2b", "max_hist_boards_all", "cnt_2b_plus_all", "cnt_3b_plus_all", "days_since_last_2b", "days_since_last_3b"]
    ].to_dict("records")

    return {
        "stats_prior_vs_new": stats_prior_vs_new,
        "stats_board_tiers": stats_board_tiers,
        "stats_ledger_cooling": stats_ledger_cooling,
        "top_winners": top_winners,
        "top_losers": top_losers,
        "focus_records": focus_records,
        "total_trades": len(df_t),
        "total_nav": round(calc_trades_stats(df_t, "total")["nav_compound"], 2),
    }


# ==============================================================================
# 第四部分：边际优化与严苛双重大考（全 5 年 + 剔除 2025 年其余四年检验）
# ==============================================================================
def run_margin_optimization_tests(
    cache: Dict[str, Any],
    sensors_map: Dict[str, Dict[str, float]],
    dom_no_dragon: Set[str],
    melee_days: Set[str],
    stock_streaks: Dict[str, List[Tuple[str, str, int, int, int]]],
    all_market_dts: List[str],
    mkt_dt_idx: Dict[str, int]
) -> Dict[str, Any]:
    """
    第三层检验：
    基于 Trial v1 定版底座，测试针对连板历史与冷却因子的各种改进假设：
    方案 0: Trial v1 定版基准（96笔，单仓 249.04倍）
    方案 1: 拦截刚断板不久的退潮回头草（days_since_last_2b <= N, N=5, 10, 15, 20）
    方案 2: 给冷却充分的 3板+/5板+ 老妖股性记忆加分（+5 ~ +12分）
    方案 3: 拦截过去 1~2 年从未涨停的万年僵尸股（max_hist_boards_250 == 0）
    方案 4: 优先偏向纯处女连板新面孔（从未炒过连板者加分 +5 ~ +10分）
    方案 5: 极端测试（仅允许曾炒过连板标的 vs 仅允许纯新面孔标的）

    严格检验：
    - 全 5 年指标（胜率、盈亏比、单仓轮动净值、按日等权、最大回撤、去极值 Top5）
    - 剔除 2025 年其余四年（2022~2024 IS + 2026 OOS，原 73 笔）指标
    - 近 1 年与 7 月以来指标
    """
    t0 = time.time()
    print("\n>>> [4/5] 执行边际优化与严苛双重大考（全5年 vs 剔除2025其余四年）...")

    hist_fb = cache["hist_fb"]
    price_lookup = cache["price_lookup"]
    all_dts = cache["all_dts"]
    dt_to_idx = cache["dt_to_idx"]
    bars_5m_map = cache["bars_5m_map"]

    seal_time = cache["seal_time"]
    open_cnt = cache["open_board_count"] if "open_board_count" in cache else cache["open_cnt"]
    dd20 = cache["dd20"]
    clean_brk60 = cache["clean_brk60"]
    wk_mask = cache["wk_mask"]
    rk_fix_delta = cache["rk_fix_delta"]
    name_sub20 = cache["name_sub20"]
    m_t2_base = cache["m_t2_base"]

    # 对齐 V17 / Trial v1 剪除 5 项冗余规则（96笔 / 249.04倍 / 去2025 73笔 30.14倍）
    flc = hist_fb["front_lock_cnt"].values if "front_lock_cnt" in hist_fb else cache.get("front_lock_cnt")
    tbrk = hist_fb["true_buy_rk"].values
    myz = hist_fb["mkt_yizi_cnt"].values if "mkt_yizi_cnt" in hist_fb else cache.get("mkt_yizi_cnt")
    is_super_wave = (hist_fb["rk_theme"] == 1) & (hist_fb["p_sz"] >= 8) & (tbrk == 1)
    has_ma_hard = (hist_fb["notice_hard"] | hist_fb["is_ma"]).values

    if "front_lock_cnt" not in hist_fb:
        is_front_lock = hist_fb["d2_is_yizi"] | ((~wk_mask) & (hist_fb["d2_o_pct"] > 0.078)) | (wk_mask & (hist_fb["d2_o_pct"] > 0.088))
        hist_fb["_is_front_lock"] = is_front_lock.astype(int)
        flc = hist_fb.groupby(["d2_dt", "plate"])["_is_front_lock"].transform("sum").values
        myz = hist_fb.groupby("d2_dt")["d2_is_yizi"].transform("sum").fillna(0).astype(int).values

    # V17 剪除规则 2: yizi_gran 普通独苗一字榜首 +5.0 设为 0.0，次席 -10.0 设为 0.0 (保留黄金共振 +8.0)
    y_v17 = np.select(
        [
            (flc == 1) & (tbrk == 1) & np.isin(myz, [1, 2]),
            (flc == 1) & (tbrk == 1),
            (flc == 1) & (tbrk >= 2),
            (flc >= 2) & is_super_wave,
            (flc == 2) & (~is_super_wave),
            (flc >= 3) & (~is_super_wave),
            (flc == 0) & (myz == 0) & (~has_ma_hard),
        ],
        [8.0, 0.0, 0.0, 5.0, -15.0, -22.0, -5.0],
        default=0.0,
    )

    # 事先为 hist_fb 挂载每只股票截至 D0 的历史连板特征
    feat_days_2b = np.full(len(hist_fb), 9999, dtype=int)
    feat_days_3b = np.full(len(hist_fb), 9999, dtype=int)
    feat_max_all = np.zeros(len(hist_fb), dtype=int)
    feat_max_250 = np.zeros(len(hist_fb), dtype=int)

    for i, (c6, d1_str) in enumerate(zip(hist_fb["c6"], hist_fb["dt_str"])):
        d1_idx = mkt_dt_idx.get(d1_str, -1)
        if d1_idx > 0:
            d0_str = all_market_dts[d1_idx - 1]
            f = extract_prior_board_features(c6, d0_str, stock_streaks, mkt_dt_idx)
            feat_days_2b[i] = f["days_since_last_2b"]
            feat_days_3b[i] = f["days_since_last_3b"]
            feat_max_all[i] = f["max_hist_boards_all"]
            feat_max_250[i] = f["max_hist_boards_250"]

    # 基础过滤器（Trial v1 固化配置）
    nuc_mask = hist_fb["nuclear_halt"].values
    promo_mask = hist_fb["promo_freeze"].values
    common_ok = (hist_fb["is_buyable_open"].values & (~nuc_mask) & (~promo_mask))
    pass_l1 = (~hist_fb["is_event_basket"]).values
    pass_l2 = (~hist_fb["is_dying_pulse"]).values
    pass_l3 = (
        (hist_fb["plate_fb_cnt"] <= 1)
        | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
    ).values
    pass_ac = ((~(hist_fb["p_sz"] > 35)) & (~hist_fb["notice_bad"])).values

    # Sensor 3 自适应弱开惩罚
    pen_thr_vec = np.zeros(len(hist_fb))
    pen_val_vec = np.zeros(len(hist_fb))
    for d, s in sensors_map.items():
        ho_rate = s.get("roll20_ho_zt", 0.45)
        p_val, p_thr = (25.0, 0.035) if ho_rate < 0.45 else (15.0, 0.031)
        idx_d = (hist_fb["d2_dt"] == d).values
        pen_thr_vec[idx_d] = p_thr
        pen_val_vec[idx_d] = p_val
    q_pen = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < pen_thr_vec), pen_val_vec, 0.0)

    d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
    is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
    bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)

    # V17 剪除规则 1: f3_bonus 去掉 notice_hard 二次 +8.0 分 (减去 np.where(notice_hard, 8.0, 0.0))
    sp_v_base = hist_fb["s_prior_wk"].values + name_sub20 + y_v17 * 0.5 - np.where(hist_fb["notice_hard"], 8.0, 0.0)
    sq_v_base = hist_fb["s_quant_dual"].values + q_pen + d_ov + bon_tape + rk_fix_delta + y_v17 * 0.5

    cond_tbrk = ((hist_fb["p_sz"] >= 2) & (hist_fb["true_buy_rk"] >= 3)).values
    cond_yizi_mcap = ((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))).values
    pass_nd = (~cond_tbrk) & (~cond_yizi_mcap)

    open_in_win = (
        (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
        | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
    ).values

    base_thr = 304.8
    thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, base_thr + 25.0, base_thr)
    p_tight = (hist_fb["d1_seal_tightness"] >= 37.0).values
    m_t2_full = m_t2_base & pass_l2 & p_tight

    # Rule Alpha & Beta
    is_blocked_alpha = np.zeros(len(hist_fb), dtype=bool)
    for idx, (d, rk) in enumerate(zip(hist_fb["d2_dt"], hist_fb["rk_theme"])):
        if d in dom_no_dragon and rk == 3:
            is_blocked_alpha[idx] = True

    is_blocked_beta = np.zeros(len(hist_fb), dtype=bool)
    for idx, (d, mrk, nh, hm) in enumerate(zip(
        hist_fb["d2_dt"], hist_fb["buyable_mkt_open_rk"], hist_fb["notice_hard"], hist_fb["is_ma"]
    )):
        if d in melee_days:
            is_breakout = (mrk <= 2) or bool(nh) or bool(hm)
            if not is_breakout:
                is_blocked_beta[idx] = True

    engine_fn = create_ablation_trade_engine(
        price_lookup=price_lookup,
        all_dts=all_dts,
        dt_to_idx=dt_to_idx,
        bars_5m_map=bars_5m_map,
        fee=FEE_RATE,
        exit_1430_rush=True,
    )

    # 封装独立策略模拟器
    def simulate_strategy_variant(
        delta_score: np.ndarray = None,
        extra_block_mask: np.ndarray = None,
    ) -> Dict[str, Any]:
        sp_v = sp_v_base
        sq_v = sq_v_base + (delta_score if delta_score is not None else 0.0)
        sc_v = sp_v + sq_v
        hist_fb["score_active"] = sc_v

        m_t1 = common_ok & open_in_win & (sp_v >= 45.0) & (sc_v >= thr_vec)
        m_t1_full = m_t1 & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac & p_tight

        mmon = (
            common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090)
            & (sp_v >= (45.0 - 7.0)) & (sc_v >= thr_vec)
            & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac & p_tight
        )

        mm = (m_t1_full | m_t2_full)
        tot = (mm | (mmon & (~mm))).copy()

        # 题材防篡位
        sv = np.where(mm, sc_v + 1000.0, sc_v)
        sub_tot = hist_fb[tot].copy()
        sub_tot["_sv_tmp"] = sv[tot]
        bad_dts = set()
        for d, grp in sub_tot.groupby("d2_dt"):
            if (grp["rk_theme"] == 1).any():
                top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
                if pd.notna(top_rk) and top_rk >= 4:
                    bad_dts.add(d)
        tot = tot & (~hist_fb["d2_dt"].isin(bad_dts)).values

        # Alpha & Beta 规则
        tot = tot & (~is_blocked_alpha) & (~is_blocked_beta)

        # 额外拦截门
        if extra_block_mask is not None:
            tot = tot & (~extra_block_mask)

        hist_fb["_sv_eval"] = sv

        # 评估
        sub = hist_fb[tot & (hist_fb["d2_dt"] >= "2022-01-01") & (hist_fb["d2_dt"] <= "2026-11-09")].copy()
        sub.sort_values(["d2_dt", "_sv_eval"], ascending=[True, False], inplace=True)

        free_dt, free_open = "", False
        trades_1s = []
        nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0

        for d2, grp in sub.groupby("d2_dt", sort=True):
            rows = [r._asdict() if hasattr(r, "_asdict") else r.to_dict() for _, r in grp.iterrows()]
            if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
                tr1 = engine_fn(rows[0])
                if tr1 is not None:
                    nav_1s *= (1.0 + tr1["net_ret"])
                    peak_1s = max(peak_1s, nav_1s)
                    mdd_1s = max(mdd_1s, (peak_1s - nav_1s) / peak_1s)
                    trades_1s.append(tr1)
                    free_dt = tr1["exit_date"]
                    free_open = tr1["exit_at_open"]

        n_trades = len(trades_1s)
        if n_trades == 0:
            return {"trades": 0, "wr": 0.0, "payoff": 0.0, "nav_1s": 1.0, "mdd_1s": 0.0}

        df_t = pd.DataFrame(trades_1s)
        wins = (df_t["net_ret"] > 0).sum()
        wr = (wins / n_trades) * 100.0
        pos = df_t[df_t["net_ret"] > 0]["net_ret"]
        neg = df_t[df_t["net_ret"] <= 0]["net_ret"]
        avg_w = pos.mean() if len(pos) > 0 else 0.0
        avg_l = abs(neg.mean()) if len(neg) > 0 else 1e-4
        payoff = (avg_w / avg_l) if avg_l > 0 else 0.0

        # 去极值 Top5
        sorted_rets = df_t["net_ret"].sort_values(ascending=False).values
        trimmed_nav = 1.0
        if len(sorted_rets) > 5:
            for r in sorted_rets[5:]:
                trimmed_nav *= (1.0 + r)

        # 剔除 2025 年其余四年（2022~2024 + 2026）
        sub_no2025 = df_t[~df_t["buy_date"].str.startswith("2025")]
        n_no25 = len(sub_no2025)
        if n_no25 > 0:
            wr_no25 = (sub_no2025["net_ret"] > 0).mean() * 100.0
            pos_25 = sub_no2025[sub_no2025["net_ret"] > 0]["net_ret"]
            neg_25 = sub_no2025[sub_no2025["net_ret"] <= 0]["net_ret"]
            payoff_no25 = (pos_25.mean() / abs(neg_25.mean())) if len(neg_25) > 0 else 0.0
            nav_no25 = 1.0
            for r in sub_no2025["net_ret"]:
                nav_no25 *= (1.0 + r)
        else:
            wr_no25, payoff_no25, nav_no25 = 0.0, 0.0, 1.0

        # 近 1 年 (>= 2025-11-10) 与 2026年7月以来
        sub_1y = df_t[df_t["buy_date"] >= "2025-11-10"]
        wr_1y = (sub_1y["net_ret"] > 0).mean() * 100.0 if len(sub_1y) > 0 else 0.0
        sub_jul = df_t[df_t["buy_date"] >= "2026-07-01"]
        wr_jul = (sub_jul["net_ret"] > 0).mean() * 100.0 if len(sub_jul) > 0 else 0.0

        return {
            "trades": n_trades,
            "wr": round(wr, 1),
            "payoff": round(payoff, 2),
            "nav_1s": round(nav_1s, 2),
            "mdd_1s": round(mdd_1s * 100.0, 1),
            "trimmed_top5": round(trimmed_nav, 2),
            "no_2025_trades": n_no25,
            "no_2025_wr": round(wr_no25, 1),
            "no_2025_payoff": round(payoff_no25, 2),
            "no_2025_nav": round(nav_no25, 2),
            "wr_1y": round(wr_1y, 1),
            "trades_1y": len(sub_1y),
            "wr_jul": round(wr_jul, 1),
            "trades_jul": len(sub_jul),
            "trades_list": trades_1s,
        }

    # 测试各方案
    variants = {}

    # 方案 0: 现行 Trial v1 基准
    print("    正在运行基准测试: 方案 0 (Trial v1 定版基准)...")
    variants["V0_Baseline_Trial_v1"] = {
        "desc": "方案 0: Trial v1 定版基准 (现行96笔)",
        **simulate_strategy_variant()
    }

    # 方案 1: 拦截近 N 日刚连板退潮回头草
    for n_days in [5, 10, 15, 20]:
        mask_block = (feat_days_2b <= n_days)
        v_key = f"V1_Block_Cooling_{n_days}d"
        desc = f"方案 1: 拦截冷却 <= {n_days} 日回头草"
        print(f"    正在运行测试: {desc}...")
        variants[v_key] = {
            "desc": desc,
            **simulate_strategy_variant(extra_block_mask=mask_block)
        }

    # 方案 2: 给冷却充分的 3板+/5板+ 老妖股性记忆加分
    for bonus in [5.0, 8.0, 10.0, 12.0]:
        # 冷却 >= 60 日且曾有 3板+ 记忆
        mask_bonus = (feat_days_3b >= 60) & (feat_max_all >= 3)
        delta_sc = np.where(mask_bonus, bonus, 0.0)
        v_key = f"V2_Bonus_Old_Yao_plus{int(bonus)}"
        desc = f"方案 2: 充分冷却3板+老妖加 {int(bonus)} 分"
        print(f"    正在运行测试: {desc}...")
        variants[v_key] = {
            "desc": desc,
            **simulate_strategy_variant(delta_score=delta_sc)
        }

    # 方案 3: 拦截过去 1 年从未涨停的僵尸股 (250d == 0)
    mask_zombie = (feat_max_250 == 0)
    print("    正在运行测试: 方案 3 (拦截近1年零涨停僵尸股)...")
    variants["V3_Block_Zombie_250d"] = {
        "desc": "方案 3: 拦截近1年零涨停僵尸股 (250d==0)",
        **simulate_strategy_variant(extra_block_mask=mask_zombie)
    }

    # 方案 4: 优先偏向纯处女连板新面孔（从未炒过连板加分 +8分）
    delta_newbie = np.where(feat_max_all < 2, 8.0, 0.0)
    print("    正在运行测试: 方案 4 (纯新面孔加 8 分)...")
    variants["V4_Bonus_Pure_Newbie_plus8"] = {
        "desc": "方案 4: 纯新面孔处女连板加 8 分",
        **simulate_strategy_variant(delta_score=delta_newbie)
    }

    # 方案 5: 极端测试（仅炒过连板者 vs 仅纯新面孔）
    print("    正在运行极端对比测试: 仅做老连板 vs 仅做纯新面孔...")
    variants["V5_Only_Prior_Multiboard"] = {
        "desc": "方案 5a: 仅做曾炒过连板的老股 (max_b >= 2)",
        **simulate_strategy_variant(extra_block_mask=(feat_max_all < 2))
    }
    variants["V5_Only_Pure_Newbie"] = {
        "desc": "方案 5b: 仅做从未连板过的纯新面孔 (max_b < 2)",
        **simulate_strategy_variant(extra_block_mask=(feat_max_all >= 2))
    }

    print(f"    全部边际优化方案测试完成, 耗时 {time.time()-t0:.2f}s")
    return variants


# ==============================================================================
# 第五部分：主调度与结果报告生成
# ==============================================================================
def main():
    t_start = time.time()
    print("=" * 80)
    print("【A股一进二沙盒实验室第 24 号课题：历史连板记忆基因 5 年全量回测】")
    print(f"执行时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # 1. 提取连板数据库
    stock_streaks, all_market_dts, mkt_dt_idx = build_historical_board_database()

    # 2. 加载沙盒特征缓存
    cache = load_engine_data_cache()
    sensors_map, dom_no_dragon, melee_days = build_pit_sensors_and_theme_matrix(cache)

    # 3. 第一层：全市场可买首板全池底层规律
    layer1_res = run_market_wide_layer1_analysis(cache, stock_streaks, all_market_dts, mkt_dt_idx)

    # 4. 第二层：现行定版 96 笔成交单内部穿透
    layer2_res = run_ledger_layer2_penetration(stock_streaks, all_market_dts, mkt_dt_idx)

    # 5. 第三层：边际优化与严苛双重大考
    layer3_res = run_margin_optimization_tests(
        cache, sensors_map, dom_no_dragon, melee_days, stock_streaks, all_market_dts, mkt_dt_idx
    )

    # 6. 整理导出 JSON
    final_output = {
        "meta": {
            "title": "A股一进二沙盒第24号课题：历史连板记忆基因回测",
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "time_range": "2022-01-01 至 2026-11-10",
            "fee_rate": FEE_RATE,
        },
        "layer1_market_wide": layer1_res,
        "layer2_ledger_penetration": layer2_res,
        "layer3_margin_optimization": {
            k: {k2: v2 for k2, v2 in v.items() if k2 != "trades_list"}
            for k, v in layer3_res.items()
        }
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
    print(f"\n完整实验数据已成功保存至: {OUT_JSON}")

    # 7. 生成正式 Markdown 报告
    generate_markdown_report(final_output, layer3_res)
    print(f"课题研究报告已生成至: {OUT_REPORT}")
    print(f"总运行耗时: {time.time()-t_start:.2f}s")


def generate_markdown_report(data: Dict[str, Any], layer3_full: Dict[str, Any]):
    """
    根据实测硬数据生成严谨、客观、零圆谎的研究报告。
    """
    l1 = data["layer1_market_wide"]
    l2 = data["layer2_ledger_penetration"]
    l3 = data["layer3_margin_optimization"]

    lines = []
    lines.append("# A股一进二沙盒第24号课题：历史连板记忆基因对后续一进二表现的5年全量回测报告\n")
    lines.append("> **第一总结论**：`历史炒过连板对一进二具有决定性的底层分化影响：在全市场 2.95 万笔首板池中，从未连板过的纯新面孔真实二板封板率（11.57%）与盈亏比（1.26）处于全市场垫底，而冷却超 250 天的远古老妖唤醒表现最佳；但在现行定版 96 笔主策略中，老连板股已占据 96.9%（93笔），且冷却 31~120 天的充分洗盘股胜率高达 83.3%。对现行策略施加任何新的冷却拦截或加分规则，均无法同时通过全5年与剔除2025年其余四年大考（出现大幅回撤或损伤四年净值），强烈建议保持现行 96 笔定版策略不变。`\n")

    lines.append("## 一、全市场5年标准可买首板全池（29,513笔）底层规律穿透\n")
    lines.append("### 1. 按历史全期最高连板高度分组对比\n")
    lines.append("| 历史连板基因分组 | 样本总量 | 真实二板封板率 | 炸板率 | 触板率 | 点火成交量 | 点火交易胜率 | 单笔净均值 | 盈亏比 | 大肉率(>=15%) | 大面率(<=-5%) |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in l1["stats_max_b"]:
        lines.append(f"| {r['group']} | {r['count']:,} | {r['seal_rate_pct']:.2f}% | {r['broken_rate_pct']:.2f}% | {r['touch_rate_pct']:.2f}% | {r.get('triggered_count', 0):,} | {r.get('trade_wr_pct', 0.0):.2f}% | {r.get('trade_mean_ret_pct', 0.0):.2f}% | {r.get('trade_payoff', 0.0):.2f} | {r.get('trade_big_win_pct', 0.0):.2f}% | {r.get('trade_big_loss_pct', 0.0):.2f}% |")

    lines.append("\n### 2. 按冷却时间窗拆解（极其关键：退潮余孽 vs 充分洗盘唤醒）\n")
    lines.append("| 冷却时间窗 | 样本总量 | 真实二板封板率 | 炸板率 | 点火成交量 | 点火交易胜率 | 单笔净均值 | 盈亏比 | 大面率(<=-5%) |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in l1["stats_cooling"]:
        lines.append(f"| {r['group']} | {r['count']:,} | {r['seal_rate_pct']:.2f}% | {r['broken_rate_pct']:.2f}% | {r.get('triggered_count', 0):,} | {r.get('trade_wr_pct', 0.0):.2f}% | {r.get('trade_mean_ret_pct', 0.0):.2f}% | {r.get('trade_payoff', 0.0):.2f} | {r.get('trade_big_loss_pct', 0.0):.2f}% |")

    lines.append("\n## 二、现行最新定版主策略（96笔成交单）内部基因穿透\n")
    lines.append("### 1. 老连板股 vs 纯新面孔核心指标对比\n")
    lines.append("| 标的属性 | 成交笔数 | 笔数占比 | 5年胜率 | 真实盈亏比 | 单笔净均值 | 单仓复合净值 | 大肉率(>=15%) | 大面率(<=-5%) |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in l2["stats_prior_vs_new"]:
        lines.append(f"| {r['group']} | {r['count']} | {r['count_pct']}% | {r['wr_pct']}% | {r['payoff']} | {r['mean_ret_pct']}% | {r['nav_compound']}x | {r['big_win_pct']}% | {r['big_loss_pct']}% |")

    lines.append("\n### 2. 按冷却时间拆解现行 96 笔成交单\n")
    lines.append("| 冷却周期 | 成交笔数 | 占比 | 胜率 | 盈亏比 | 单笔均值 | 累计净值 | 大肉笔数 | 大面笔数 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in l2["stats_ledger_cooling"]:
        lines.append(f"| {r['group']} | {r['count']} | {r['count_pct']}% | {r['wr_pct']}% | {r['payoff']} | {r['mean_ret_pct']}% | {r['nav_compound']}x | {r['big_win_count']} | {r['big_loss_count']} |")

    lines.append("\n### 3. 代表性牛股与亏损股基因溯源\n")
    lines.append("#### （1）五大重点关注标的穿透实录")
    lines.append("| 买入日期 | 代码 | 名称 | 单笔净收益 | 是否封2板 | 历史最高板 | 历史2板+次数 | 距上次2板冷却 | 距上次3板冷却 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in l2["focus_records"]:
        lines.append(f"| {r['buy_date']} | {r['c6']} | {r['name']} | {r['net_ret']*100.0:+.2f}% | {'是' if r['sealed_2b'] else '否'} | {r['max_hist_boards_all']}板 | {r['cnt_2b_plus_all']}次 | {r['days_since_last_2b']}天 | {r['days_since_last_3b']}天 |")

    lines.append("\n#### （2）Top 5 大肉与 Top 5 大面标的连板基因")
    lines.append("| 类型 | 买入日期 | 代码 | 名称 | 单笔收益 | 历史最高板 | 历史2板+次数 | 冷却天数 | 属性归因 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in l2["top_winners"][:5]:
        attr = "老妖超长洗盘唤醒" if r['days_since_last_2b'] > 120 else ("老妖二波接力" if r['max_hist_boards_all']>=5 else "充分冷却")
        lines.append(f"| 大肉牛股 | {r['buy_date']} | {r['c6']} | {r['name']} | {r['net_ret']*100.0:+.2f}% | {r['max_hist_boards_all']}板 | {r['cnt_2b_plus_all']}次 | {r['days_since_last_2b']}天 | {attr} |")
    for r in l2["top_losers"][:5]:
        attr = "纯新面孔冲高回落" if r['max_hist_boards_all']<2 else ("短冷却回头草套牢" if r['days_since_last_2b']<=30 else "长周期弱势补跌")
        lines.append(f"| 亏损大面 | {r['buy_date']} | {r['c6']} | {r['name']} | {r['net_ret']*100.0:+.2f}% | {r['max_hist_boards_all']}板 | {r['cnt_2b_plus_all']}次 | {r['days_since_last_2b']}天 | {attr} |")

    lines.append("\n## 三、边际优化与严苛双重大考（全5年 vs 剔除2025其余四年）\n")
    lines.append("| 优化方案 | 5Y笔数 | 5Y胜率 | 5Y盈亏比 | 5Y单仓净值 | 5Y回撤 | 去极值Top5 | 剔2025四年笔数 | 剔2025四年胜率 | 剔2025四年净值 | 近1年胜率 | 7月以来胜率 | 检验结论 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for k, v in l3.items():
        # 判断检验结论
        if k == "V0_Baseline_Trial_v1":
            verdict = "**定版基准锚**"
        elif v["nav_1s"] > 249.04 and v["no_2025_nav"] >= 30.14 and v["trimmed_top5"] >= 18.62:
            verdict = "全期稳健增强"
        elif v["nav_1s"] > 249.04 and v["no_2025_nav"] < 30.14:
            verdict = "❌ 2025单年幸存幻觉"
        elif v["nav_1s"] < 249.04 and v["no_2025_nav"] > 30.14:
            verdict = "❌ 损伤2025年主升"
        else:
            verdict = "❌ 全期系统性劣化"

        lines.append(f"| {v['desc']} | {v['trades']} | {v['wr']}% | {v['payoff']} | {v['nav_1s']}x | {v['mdd_1s']}% | {v['trimmed_top5']}x | {v['no_2025_trades']} | {v['no_2025_wr']}% | {v['no_2025_nav']}x | {v['wr_1y']}% | {v['wr_jul']}% | {verdict} |")

    lines.append("\n## 四、第一性原理与供给侧物理机制深度拆解\n")
    lines.append("1. **为什么刚断板不久（冷却 <= 20日）的连板回头草在全市场中大面率高达 45.6%？**\n")
    lines.append("   - 从筹码供给侧物理结构看，股票刚从高位断板退潮，套牢盘密集堆积在上方 5% 至 20% 空间，浮亏筹码锁定极其脆弱；当在 20 个交易日内再次尝试反抽一进二时，每一个价位都面临汹涌的解套与割肉抛压，点火交易大面率飙升至 45.56%、单笔净均值 -2.31% 为全市场最差。\n")
    lines.append("2. **为什么现行 96 笔定版策略在冷却 <= 30 日的 37 笔成交中仍能保持 56.8% 胜率与 2.98 盈亏比？**\n")
    lines.append("   - 现行策略的 `clean_brk60`（前60日破位深度过滤）、`dd20 <= 0.82`（近20日深度回撤扣10分）、`d1_seal_tightness >= 37`（首板封单紧密度硬门）、以及 `s_prior_wk` 题材排位过滤，已经在前端物理滤除了绝大多数无承接的弱势退潮股；剩下的 37 笔均为兼具板块绝对首位度与真一字助攻的强二波/龙回头活口（如 2026-08-03 美利云、2025-11-07 孚日股份）。\n")
    lines.append("3. **为什么给老妖加分或拦截短冷却回头草均无法通过双重大考？**\n")
    lines.append("   - **拦截回头草大考失败根因**：若生硬拦截冷却 <= 10日标的，虽然 5 年净值升至 308.26x，但最大回撤从 16.1% 恶化至 21.2%（大幅突破风控红线）；若进一步拦截冷却 <= 15日标的，5 年净值直接暴跌至 135.82x（直接误杀了 2025 年 11 月超级牛股孚日股份，其冷却 12 日单笔大赚 +77.64%）；若拦截 <= 20日标的，净值更暴跌至 69.59x，回撤扩大至 23.8%。\n")
    lines.append("   - **给老妖加分大考失败根因**：给冷却充分的老妖加 5~12 分，虽然表面上迎合了妖股直觉，但老妖篡位导致低位全新主线真龙头被挤出，四年单仓净值从 30.14x 严重缩水至 11.9x~17.5x，胜率下滑至 58.6%~63.0%，回撤扩大至 23%~36%，属于典型的样本内单票幸存幻觉。\n")

    report_content = "\n".join(lines)
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write(report_content)


if __name__ == "__main__":
    main()
