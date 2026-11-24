#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_part2_factors.py
================================================================================
热点题材大票中军 53 维正交因子检验与 IS/OOS 盲测筛选（Part 2）。
- 100% 本地只读，严禁 import yfinance / baostock / 联网 API。
- 主池 mcap >= 150亿（并对比 >= 250亿），IS (2021-11-15~2023-12-31) vs OOS (2024-01-01~2026-11-23)。
- 覆盖 1日 / 3日 / 5日(主) / 10日(主) / 20日 持有周期，扣 0.20% 费用，剔除停牌与一字不可买。
- 同时计算逐笔均值/胜率/Spread、按日等权去重后的 Daily Spread 与 Newey-West HAC t-stat、
  剔除 2024-09-24~10-08 救市日稳定性、Fama-MacBeth 正交检验、以及复合正交验证。
================================================================================
"""

import json
import math
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
assert "yfinance" not in sys.modules, "D12 violation"
assert "baostock" not in sys.modules, "Redline violation"

PART2_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/hot_theme_largecap_audit_20261123/part2_factors"
if PART2_DIR not in sys.path:
    sys.path.insert(0, PART2_DIR)

import part2_data_builder as pdb

RESCUE_DTS = {
    "2024-09-24", "2024-09-25", "2024-09-26", "2024-09-27", "2024-09-30", "2024-10-08",
}


def newey_west_tstat(x: np.ndarray, max_lag: int) -> tuple[float, float, int]:
    """Compute mean, Newey-West HAC t-stat, and valid sample size."""
    v = x[np.isfinite(x)]
    n = len(v)
    if n < 10:
        return (float(np.mean(v)) if n > 0 else np.nan), np.nan, n
    mu = float(np.mean(v))
    d = v - mu
    gamma0 = float(np.dot(d, d) / n)
    lrv = gamma0
    L = min(max_lag, n - 1)
    for lag in range(1, L + 1):
        w = 1.0 - lag / (L + 1.0)
        cov = float(np.dot(d[lag:], d[:-lag]) / n)
        lrv += 2.0 * w * cov
    if lrv <= 1e-18:
        return mu, np.nan, n
    se = math.sqrt(lrv / n)
    return mu, mu / se, n


def pooled_tstat(x_top: np.ndarray, x_bot: np.ndarray) -> float:
    t = x_top[np.isfinite(x_top)]
    b = x_bot[np.isfinite(x_bot)]
    if len(t) < 10 or len(b) < 10:
        return np.nan
    se = math.sqrt(np.var(t, ddof=1) / len(t) + np.var(b, ddof=1) / len(b))
    if se <= 1e-12:
        return np.nan
    return float((np.mean(t) - np.mean(b)) / se)


def build_factor_specs(df: pd.DataFrame) -> list[dict]:
    """Assign 53 orthogonal/categorical factor columns and return factor specifications."""
    # Cat 1: Pre-signal returns & position (14 factors)
    df["f_ret_pre5_exT"] = pd.cut(df["ret_pre5_exT"], [-9, -0.05, 0.0, 0.10, 99], labels=["B1_跌超5%", "B2_跌0~5%", "B3_涨0~10%", "B4_涨超10%"]).astype(str)
    df["f_ret_pre5_incT"] = pd.cut(df["ret_pre5_incT"], [-9, -0.05, 0.0, 0.10, 99], labels=["B1_跌超5%", "B2_跌0~5%", "B3_涨0~10%", "B4_涨超10%"]).astype(str)
    df["f_ret_pre10_exT"] = pd.cut(df["ret_pre10_exT"], [-9, -0.08, 0.0, 0.15, 99], labels=["B1_跌超8%", "B2_跌0~8%", "B3_涨0~15%", "B4_涨超15%"]).astype(str)
    df["f_ret_pre20_exT"] = pd.cut(df["ret_pre20_exT"], [-9, -0.10, 0.0, 0.20, 99], labels=["B1_跌超10%", "B2_跌0~10%", "B3_涨0~20%", "B4_涨超20%"]).astype(str)
    df["f_ret_pre60_exT"] = pd.cut(df["ret_pre60_exT"], [-9, -0.15, 0.0, 0.30, 99], labels=["B1_跌超15%", "B2_跌0~15%", "B3_涨0~30%", "B4_涨超30%"]).astype(str)

    df["f_pos20"] = pd.cut(df["pos20"], [-1, 0.25, 0.50, 0.80, 2], labels=["B1_低位<0.25", "B2_中低0.25~0.5", "B3_中高0.5~0.8", "B4_高位>=0.8"]).astype(str)
    df["f_pos60"] = pd.cut(df["pos60"], [-1, 0.25, 0.50, 0.80, 2], labels=["B1_低位<0.25", "B2_中低0.25~0.5", "B3_中高0.5~0.8", "B4_高位>=0.8"]).astype(str)
    df["f_pos120"] = pd.cut(df["pos120"], [-1, 0.25, 0.50, 0.80, 2], labels=["B1_低位<0.25", "B2_中低0.25~0.5", "B3_中高0.5~0.8", "B4_高位>=0.8"]).astype(str)
    df["f_dd20"] = pd.cut(df["dd20"], [-9, -0.15, -0.05, 1], labels=["B1_深回撤<-15%", "B2_中回撤-15~-5%", "B3_近高点>-5%"]).astype(str)
    df["f_dd60"] = pd.cut(df["dd60"], [-9, -0.20, -0.10, 1], labels=["B1_深回撤<-20%", "B2_中回撤-20~-10%", "B3_近高点>-10%"]).astype(str)
    df["f_break60"] = np.where(df["break60"] == 1, "B2_突破60日新高", "B1_未突破")
    df["f_ma_bull"] = np.where(df["ma_bull"] == 1, "B2_多头排列(C>MA20>MA60)", "B1_非多头排列")

    df["f_rebound10"] = np.where(
        (df["ret_pre10_exT"] < -0.05) & (df["pct"] >= 0.03), "B3_先跌10d>5%大弹>=3%",
        np.where((df["ret_pre10_exT"] >= 0.10) & (df["pct"] >= 0.03), "B1_高位连涨追",
                 np.where((df["ret_pre10_exT"] < -0.05) & (df["pct"] < 0.03), "B2_先跌未弹", "B0_其余"))
    )
    df["f_rebound20"] = np.where(
        (df["ret_pre20_exT"] < -0.10) & (df["pct"] >= 0.03), "B3_先跌20d>10%大弹>=3%",
        np.where((df["ret_pre20_exT"] > 0.20) & (df["pct"] >= 0.03), "B1_前20d大涨>20%再追>=3%",
                 np.where((df["ret_pre20_exT"] < -0.10) & (df["pct"] < 0.03), "B2_先跌20d>10%低迷<3%", "B0_其余"))
    )

    # Cat 2: Day-T price/volume & T+1 open auction (11 factors)
    df["f_d0_pct"] = np.where(
        df["is_zt"], "B4_涨停",
        np.where(df["pct"] >= 0.06, "B3_6~9.5%大涨",
                 np.where(df["pct"] >= 0.03, "B2_3~6%中阳", "B1_<3%"))
    )
    df["f_d0_pct_5bkt"] = np.where(
        df["is_zt"], "B5_真涨停",
        np.where(df["pct"] >= 0.05, "B4_>=5%未涨停",
                 np.where(df["pct"] >= 0.02, "B3_2~5%温和",
                          np.where(df["pct"] >= 0.0, "B2_0~2%潜伏", "B1_<0%阴跌")))
    )
    df["f_vol_ratio_5d"] = pd.cut(df["vol_ratio_5d"], [-1, 1.0, 1.8, 3.0, 999], labels=["B1_<1.0缩量", "B2_1.0~1.8温和", "B3_1.8~3.0放量", "B4_>=3.0巨量"]).astype(str)
    df["f_turn_pct"] = pd.cut(df["to_pct"], [-1, 2.0, 5.0, 10.0, 999], labels=["B1_<2%", "B2_2~5%", "B3_5~10%", "B4_>=10%"]).astype(str)
    df["f_turn_extreme"] = np.where(df["to_pct"] >= 10.0, "B2_高换手>=10%", "B1_常态<10%")
    df["f_amt_yi"] = pd.cut(df["amt_yi"], [-1, 5.0, 15.0, 30.0, 99999], labels=["B1_<5亿", "B2_5~15亿", "B3_15~30亿", "B4_>=30亿"]).astype(str)
    df["f_amt_rk_plate"] = np.where(df["amt_rk_in_plate"] == 1, "B3_成交额第1中军",
                                    np.where(df["amt_rk_in_plate"] <= 3, "B2_前3前排", "B1_>=4后排"))
    df["f_mcap_bkt"] = pd.cut(df["mcap"], [0, 250.0, 500.0, 999999], labels=["B1_150~250亿", "B2_250~500亿", "B3_>=500亿"]).astype(str)
    df["f_clv"] = pd.cut(df["clv"], [-1, 0.3, 0.7, 2.0], labels=["B1_<0.3上影回落", "B2_0.3~0.7均衡", "B3_>=0.7光头强收"]).astype(str)
    df["f_d1_open_pct"] = pd.cut(df["d1_open_pct"], [-1, 0.0, 0.02, 0.05, 1.0], labels=["B1_低开(<0%)", "B2_平开(0~2%)", "B3_中高开(2~5%)", "B4_极高开(>5%)"]).astype(str)
    df["f_d1_open_after_surge"] = np.where(
        df["pct"] < 0.03, "B0_非启动日",
        np.where(df["d1_open_pct"] > 0.05, "B4_启动后极高开>5%",
                 np.where(df["d1_open_pct"] >= 0.02, "B3_启动后中高开2~5%",
                          np.where(df["d1_open_pct"] >= 0.0, "B2_启动后平开0~2%", "B1_启动后低开<0%")))
    )

    # Cat 3: Notices (< T+1 09:25) (8 factors)
    df["f_notice_earn_pos_90d"] = np.where(df["notice_earn_pos_90d"] == 1, "B2_近90天业绩正增/预增/扭亏", "B1_无")
    df["f_notice_contract_buyback_90d"] = np.where(df["notice_contract_buyback_90d"] == 1, "B2_近90天合同/中标/回购/增持", "B1_无")
    df["f_notice_contract_90d"] = np.where(df["notice_contract_90d"] == 1, "B2_近90天重大合同/中标/定点", "B1_无")
    df["f_notice_buyback_90d"] = np.where(df["notice_buyback_90d"] == 1, "B2_近90天回购/增持", "B1_无")
    df["f_notice_regtox_5y_90d"] = np.where(df["notice_regtox_5y_90d"] == 1, "B2_近90天监管毒丸(5Y完备)", "B1_无")
    df["f_notice_reduce_90d"] = np.where(df["notice_reduce_90d"] == 1, "B2_近90天减持公告", "B1_无")
    df["f_notice_loss_90d"] = np.where(df["notice_loss_90d"] == 1, "B2_近90天业绩预亏/减", "B1_无")
    df["f_notice_report_30d"] = np.where(df["notice_report_30d"] == 1, "B2_近30天刚发财报季报", "B1_无")

    # Cat 4: Institutional & LHB Seats (8 factors)
    df["f_ir_30d"] = np.where(df["ir_cnt_30d"] >= 3, "B3_>=3次", np.where(df["ir_cnt_30d"] >= 1, "B2_1~2次", "B1_0次"))
    df["f_ir_90d"] = np.where(df["ir_cnt_90d"] >= 3, "B3_>=3次", np.where(df["ir_cnt_90d"] >= 1, "B2_1~2次", "B1_0次"))
    df["f_lhb_inst_5d"] = np.where(
        df["lhb_inst_net_5d_wan"].isna(), "B2_未上榜",
        np.where(df["lhb_inst_net_5d_wan"] > 5000.0, "B4_机构净买>5000万",
                 np.where(df["lhb_inst_net_5d_wan"] > 0.0, "B3_机构净买0~5000万", "B1_机构净卖或0"))
    )
    df["f_lhb_inst_buy_vs_sell"] = df["f_lhb_inst_5d"]
    df["f_lhb_inst_1d"] = np.where(
        df["lhb_inst_net_1d_wan"].isna(), "B2_当日未上榜",
        np.where(df["lhb_inst_net_1d_wan"] > 0.0, "B3_当日机构净买>0", "B1_当日机构净卖或0")
    )
    df["f_lhb_north_5d"] = np.where(
        df["lhb_north_net_5d_wan"].isna(), "B2_未上榜",
        np.where(df["lhb_north_net_5d_wan"] > 0.0, "B3_北向净买>0", "B1_北向净卖或0")
    )
    df["f_lhb_lhasa_5d"] = np.where(df["lhb_lhasa_5d"] == 1, "B2_近5日拉萨席位出现", "B1_无拉萨")
    df["f_lhb_youzi_5d"] = np.where(df["lhb_youzi_net_5d_wan"] > 0.0, "B2_知名游资净买>0", "B1_无/净卖")

    # Cat 5: Community heat & Plate structure (9 factors)
    df["f_xq_posts_2d"] = np.where(df["xq_posts_2d"] >= 3, "B3_>=3帖", np.where(df["xq_posts_2d"] >= 1, "B2_1~2帖", "B1_0帖"))
    df["f_xq_posts_7d"] = np.where(df["xq_posts_7d"] >= 5, "B3_>=5帖", np.where(df["xq_posts_7d"] >= 1, "B2_1~4帖", "B1_0帖"))
    df["f_xq_union_7d"] = np.where(df["xq_union_7d"] >= 5, "B3_>=5帖", np.where(df["xq_union_7d"] >= 1, "B2_1~4帖", "B1_0帖"))
    df["_xq_yr_pct"] = df.groupby(df["dt_str"].str[:4])["xq_union_7d"].rank(pct=True)
    df["f_xq_yr_rank"] = np.where(df["xq_union_7d"] == 0, "B1_0帖", np.where(df["_xq_yr_pct"] >= 0.85, "B3_年内高热前15%", "B2_年内中温"))

    df["f_p_sz"] = pd.cut(df["p_sz"], [0, 9, 20, 35, 999], labels=["B1_<10", "B2_10~20", "B3_21~35", "B4_>35"]).astype(str)
    df["f_plate_max_board"] = np.where(df["plate_max_board"] >= 3, "B2_板块有>=3板连板龙头", "B1_板块最高<=2板")
    df["f_sector_style"] = np.where(df["sector_style"] == "硬科技", "B3_硬科技", np.where(df["sector_style"] == "传统消费周期", "B1_传统消费周期", "B2_其他中游制造"))
    df["f_rk_c"] = np.where(df["rk_c"] == 1, "B3_主线第1(rk_c=1)", np.where(df["rk_c"] == 2, "B2_主线第2(rk_c=2)", "B1_后排主线(rk_c>=3&sz>=5)"))
    df["f_p_elo"] = pd.cut(df["p_elo"], [-999, 100.0, 115.0, 9999], labels=["B1_<100", "B2_100~115", "B3_>=115"]).astype(str)

    # Cat 6: Market & Style Regime (6 factors)
    df["f_csi300_ret5"] = pd.cut(df["csi300_ret5"], [-9, -0.02, 0.02, 9], labels=["B1_<-2%弱势", "B2_-2~2%震荡", "B3_>2%强势"]).astype(str)
    df["f_csi300_ret20"] = pd.cut(df["csi300_ret20"], [-9, -0.05, 0.05, 9], labels=["B1_<-5%熊段", "B2_-5~5%震荡", "B3_>5%牛段"]).astype(str)
    df["f_zz1000_vs_csi300_5d"] = pd.cut(df["zz1000_vs_csi300_5d"], [-9, -0.02, 0.02, 9], labels=["B1_<-2%大票占优", "B2_-2~2%均衡", "B3_>2%小票占优"]).astype(str)
    df["f_sz399107_vs_csi300_5d"] = pd.cut(df["sz399107_vs_csi300_5d"], [-9, -0.02, 0.02, 9], labels=["B1_<-2%大票占优", "B2_-2~2%均衡", "B3_>2%小票占优"]).astype(str)
    df["f_mkt_zt_cnt"] = pd.cut(df["mkt_zt_cnt"], [-1, 39, 89, 9999], labels=["B1_<40冰点", "B2_40~89温和", "B3_>=90高潮"]).astype(str)
    df["f_mkt_amt_ratio"] = pd.cut(df["mkt_amt_ratio"], [-1, 0.85, 1.15, 99], labels=["B1_<0.85缩量", "B2_0.85~1.15常态", "B3_>=1.15放量"]).astype(str)

    specs = [
        # Cat 1 (14)
        ("C1_01_ret_pre5_exT", "1_前期涨跌与位置", "f_ret_pre5_exT", "B4_涨超10%", "B1_跌超5%", "启动前5日涨跌[T-6,T-1]"),
        ("C1_02_ret_pre5_incT", "1_前期涨跌与位置", "f_ret_pre5_incT", "B4_涨超10%", "B1_跌超5%", "含T近5日涨跌[T-5,T]"),
        ("C1_03_ret_pre10_exT", "1_前期涨跌与位置", "f_ret_pre10_exT", "B4_涨超15%", "B1_跌超8%", "启动前10日涨跌[T-11,T-1]"),
        ("C1_04_ret_pre20_exT", "1_前期涨跌与位置", "f_ret_pre20_exT", "B4_涨超20%", "B1_跌超10%", "启动前20日涨跌[T-21,T-1]"),
        ("C1_05_ret_pre60_exT", "1_前期涨跌与位置", "f_ret_pre60_exT", "B4_涨超30%", "B1_跌超15%", "启动前60日涨跌[T-61,T-1]"),
        ("C1_06_pos20", "1_前期涨跌与位置", "f_pos20", "B4_高位>=0.8", "B1_低位<0.25", "20日箱体位置"),
        ("C1_07_pos60", "1_前期涨跌与位置", "f_pos60", "B4_高位>=0.8", "B1_低位<0.25", "60日箱体位置"),
        ("C1_08_pos120", "1_前期涨跌与位置", "f_pos120", "B4_高位>=0.8", "B1_低位<0.25", "120日箱体位置"),
        ("C1_09_dd20", "1_前期涨跌与位置", "f_dd20", "B3_近高点>-5%", "B1_深回撤<-15%", "距20日高点回撤"),
        ("C1_10_dd60", "1_前期涨跌与位置", "f_dd60", "B3_近高点>-10%", "B1_深回撤<-20%", "距60日高点回撤"),
        ("C1_11_break60", "1_前期涨跌与位置", "f_break60", "B2_突破60日新高", "B1_未突破", "60日新高突破"),
        ("C1_12_ma_bull", "1_前期涨跌与位置", "f_ma_bull", "B2_多头排列(C>MA20>MA60)", "B1_非多头排列", "均线多头排列"),
        ("C1_13_rebound10", "1_前期涨跌与位置", "f_rebound10", "B3_先跌10d>5%大弹>=3%", "B1_高位连涨追", "前10日跌5%+启动反弹 vs 高位追"),
        ("C1_14_rebound20", "1_前期涨跌与位置", "f_rebound20", "B3_先跌20d>10%大弹>=3%", "B1_前20d大涨>20%再追>=3%", "拓普式前20日跌10%+大弹>=3% vs 高位连涨追"),
        # Cat 2 (11)
        ("C2_01_d0_pct", "2_启动当日量价与盘口", "f_d0_pct", "B4_涨停", "B1_<3%", "当日涨跌幅4分桶"),
        ("C2_02_d0_pct_5bkt", "2_启动当日量价与盘口", "f_d0_pct_5bkt", "B5_真涨停", "B2_0~2%潜伏", "真涨停追击 vs 潜伏对比"),
        ("C2_03_vol_ratio_5d", "2_启动当日量价与盘口", "f_vol_ratio_5d", "B4_>=3.0巨量", "B1_<1.0缩量", "当日量比(相对5日均额)"),
        ("C2_04_turn_pct", "2_启动当日量价与盘口", "f_turn_pct", "B4_>=10%", "B1_<2%", "当日换手率分桶"),
        ("C2_05_turn_extreme", "2_启动当日量价与盘口", "f_turn_extreme", "B2_高换手>=10%", "B1_常态<10%", "极端换手>=10% vs 常态"),
        ("C2_06_amt_yi", "2_启动当日量价与盘口", "f_amt_yi", "B4_>=30亿", "B1_<5亿", "当日成交额分桶"),
        ("C2_07_amt_rk_plate", "2_启动当日量价与盘口", "f_amt_rk_plate", "B3_成交额第1中军", "B1_>=4后排", "板块内成交额第1中军 vs 后排"),
        ("C2_08_mcap_bkt", "2_启动当日量价与盘口", "f_mcap_bkt", "B3_>=500亿", "B1_150~250亿", "市值规模分层"),
        ("C2_09_clv", "2_启动当日量价与盘口", "f_clv", "B3_>=0.7光头强收", "B1_<0.3上影回落", "收盘光头强度CLV"),
        ("C2_10_d1_open_pct", "2_启动当日量价与盘口", "f_d1_open_pct", "B4_极高开(>5%)", "B2_平开(0~2%)", "全池次日T+1竞价开盘分桶"),
        ("C2_11_d1_open_after_surge", "2_启动当日量价与盘口", "f_d1_open_after_surge", "B4_启动后极高开>5%", "B1_启动后低开<0%", "启动(d0>=3%)后次日高开>5% vs 低开"),
        # Cat 3 (8)
        ("C3_01_notice_earn_pos_90d", "3_基本面公告催化", "f_notice_earn_pos_90d", "B2_近90天业绩正增/预增/扭亏", "B1_无", "近90天业绩预增/扭亏/正增"),
        ("C3_02_notice_contract_buyback_90d", "3_基本面公告催化", "f_notice_contract_buyback_90d", "B2_近90天合同/中标/回购/增持", "B1_无", "近90天合同中标/回购增持(2025+全库)"),
        ("C3_03_notice_contract_90d", "3_基本面公告催化", "f_notice_contract_90d", "B2_近90天重大合同/中标/定点", "B1_无", "近90天重大合同/中标/定点(2025+全库)"),
        ("C3_04_notice_buyback_90d", "3_基本面公告催化", "f_notice_buyback_90d", "B2_近90天回购/增持", "B1_无", "近90天回购/增持(2025+全库)"),
        ("C3_05_notice_regtox_5y_90d", "3_基本面公告催化", "f_notice_regtox_5y_90d", "B2_近90天监管毒丸(5Y完备)", "B1_无", "近90天监管/立案/风险毒丸(5Y全库)"),
        ("C3_06_notice_reduce_90d", "3_基本面公告催化", "f_notice_reduce_90d", "B2_近90天减持公告", "B1_无", "近90天减持公告(2025+全库)"),
        ("C3_07_notice_loss_90d", "3_基本面公告催化", "f_notice_loss_90d", "B2_近90天业绩预亏/减", "B1_无", "近90天业绩预亏/减"),
        ("C3_08_notice_report_30d", "3_基本面公告催化", "f_notice_report_30d", "B2_近30天刚发财报季报", "B1_无", "近30天刚发定期财报季报(2025+全库)"),
        # Cat 4 (8)
        ("C4_01_ir_30d", "4_机构与席位背书", "f_ir_30d", "B3_>=3次", "B1_0次", "近30天机构调研次数"),
        ("C4_02_ir_90d", "4_机构与席位背书", "f_ir_90d", "B3_>=3次", "B1_0次", "近90天机构调研次数"),
        ("C4_03_lhb_inst_5d_vs_none", "4_机构与席位背书", "f_lhb_inst_5d", "B4_机构净买>5000万", "B2_未上榜", "近5日机构专用净买>5000万 vs 未上榜"),
        ("C4_04_lhb_inst_buy_vs_sell", "4_机构与席位背书", "f_lhb_inst_buy_vs_sell", "B4_机构净买>5000万", "B1_机构净卖或0", "近5日机构专用净买>5000万 vs 净卖"),
        ("C4_05_lhb_inst_1d", "4_机构与席位背书", "f_lhb_inst_1d", "B3_当日机构净买>0", "B1_当日机构净卖或0", "当日机构专用净买 vs 净卖"),
        ("C4_06_lhb_north_5d", "4_机构与席位背书", "f_lhb_north_5d", "B3_北向净买>0", "B1_北向净卖或0", "近5日北向席位净买 vs 净卖"),
        ("C4_07_lhb_lhasa_5d", "4_机构与席位背书", "f_lhb_lhasa_5d", "B2_近5日拉萨席位出现", "B1_无拉萨", "近5日拉萨席位出现"),
        ("C4_08_lhb_youzi_5d", "4_机构与席位背书", "f_lhb_youzi_5d", "B2_知名游资净买>0", "B1_无/净卖", "近5日知名游资席位净买"),
        # Cat 5 (9)
        ("C5_01_xq_posts_2d", "5_社区情绪与拥挤度", "f_xq_posts_2d", "B3_>=3帖", "B1_0帖", "雪球近2日发帖数(严格PIT)"),
        ("C5_02_xq_posts_7d", "5_社区情绪与拥挤度", "f_xq_posts_7d", "B3_>=5帖", "B1_0帖", "雪球近7日发帖数(严格PIT)"),
        ("C5_03_xq_union_7d", "5_社区情绪与拥挤度", "f_xq_union_7d", "B3_>=5帖", "B1_0帖", "雪球双库合并近7日发帖数"),
        ("C5_04_xq_yr_rank", "5_社区情绪与拥挤度", "f_xq_yr_rank", "B3_年内高热前15%", "B1_0帖", "雪球年内分位高热 vs 0帖"),
        ("C5_05_p_sz", "5_社区情绪与拥挤度", "f_p_sz", "B4_>35", "B1_<10", "板块当日涨停/上榜数p_sz"),
        ("C5_06_plate_max_board", "5_社区情绪与拥挤度", "f_plate_max_board", "B2_板块有>=3板连板龙头", "B1_板块最高<=2板", "板块是否有小票连板龙头"),
        ("C5_07_sector_style", "5_社区情绪与拥挤度", "f_sector_style", "B3_硬科技", "B1_传统消费周期", "硬科技 vs 传统消费周期"),
        ("C5_08_rk_c", "5_社区情绪与拥挤度", "f_rk_c", "B3_主线第1(rk_c=1)", "B1_后排主线(rk_c>=3&sz>=5)", "主线第1 vs 后排"),
        ("C5_09_p_elo", "5_社区情绪与拥挤度", "f_p_elo", "B3_>=115", "B1_<100", "板块滚动Elo分桶"),
        # Cat 6 (6)
        ("C6_01_csi300_ret5", "6_市场大盘与风格环境", "f_csi300_ret5", "B3_>2%强势", "B1_<-2%弱势", "沪深300近5日涨跌"),
        ("C6_02_csi300_ret20", "6_市场大盘与风格环境", "f_csi300_ret20", "B3_>5%牛段", "B1_<-5%熊段", "沪深300近20日涨跌"),
        ("C6_03_zz1000_vs_csi300_5d", "6_市场大盘与风格环境", "f_zz1000_vs_csi300_5d", "B3_>2%小票占优", "B1_<-2%大票占优", "中证1000(PIT合成)相对沪深300近5日"),
        ("C6_04_sz399107_vs_csi300_5d", "6_市场大盘与风格环境", "f_sz399107_vs_csi300_5d", "B3_>2%小票占优", "B1_<-2%大票占优", "深证综指相对沪深300近5日"),
        ("C6_05_mkt_zt_cnt", "6_市场大盘与风格环境", "f_mkt_zt_cnt", "B3_>=90高潮", "B1_<40冰点", "全市场涨停家数"),
        ("C6_06_mkt_amt_ratio", "6_市场大盘与风格环境", "f_mkt_amt_ratio", "B3_>=1.15放量", "B1_<0.85缩量", "全市场成交额/20日均额"),
    ]
    return specs


def eval_factor_horizon(sub: pd.DataFrame, col: str, top_b: str, bot_b: str, ret_col: str, nw_lag: int) -> tuple[dict, list[dict]]:
    """Evaluate a single factor on one horizon across IS, OOS, Full, and Daily-Collapsed spreads."""
    v_all = sub[sub[ret_col].notna() & (~sub[col].isin(["nan", "None"]))].copy()
    bucket_rows = []
    b_stats = {}

    for bkt, grp in v_all.groupby(col, observed=True):
        g_is = grp[grp["dt_str"] <= "2023-12-31"][ret_col].to_numpy()
        g_oos = grp[grp["dt_str"] >= "2024-01-01"][ret_col].to_numpy()
        g_full = grp[ret_col].to_numpy()
        d_is = grp[grp["dt_str"] <= "2023-12-31"].groupby("dt_str")[ret_col].mean()
        d_oos = grp[grp["dt_str"] >= "2024-01-01"].groupby("dt_str")[ret_col].mean()
        d_full = grp.groupby("dt_str")[ret_col].mean()

        row = {
            "bucket": str(bkt),
            "n_is": len(g_is),
            "is_mean": float(np.mean(g_is)) if len(g_is) else np.nan,
            "is_wr": float(np.mean(g_is > 0)) if len(g_is) else np.nan,
            "n_oos": len(g_oos),
            "oos_mean": float(np.mean(g_oos)) if len(g_oos) else np.nan,
            "oos_wr": float(np.mean(g_oos > 0)) if len(g_oos) else np.nan,
            "n_full": len(g_full),
            "full_mean": float(np.mean(g_full)) if len(g_full) else np.nan,
            "full_wr": float(np.mean(g_full > 0)) if len(g_full) else np.nan,
            "d_is_days": len(d_is),
            "d_is_mean": float(d_is.mean()) if len(d_is) else np.nan,
            "d_oos_days": len(d_oos),
            "d_oos_mean": float(d_oos.mean()) if len(d_oos) else np.nan,
            "d_full_days": len(d_full),
            "d_full_mean": float(d_full.mean()) if len(d_full) else np.nan,
            "d_full_wr": float((d_full > 0).mean()) if len(d_full) else np.nan,
        }
        b_stats[str(bkt)] = row
        bucket_rows.append(row)

    t_df = v_all[v_all[col] == top_b]
    b_df = v_all[v_all[col] == bot_b]

    t_is = t_df[t_df["dt_str"] <= "2023-12-31"][ret_col].to_numpy()
    b_is = b_df[b_df["dt_str"] <= "2023-12-31"][ret_col].to_numpy()
    t_oos = t_df[t_df["dt_str"] >= "2024-01-01"][ret_col].to_numpy()
    b_oos = b_df[b_df["dt_str"] >= "2024-01-01"][ret_col].to_numpy()
    t_full = t_df[ret_col].to_numpy()
    b_full = b_df[ret_col].to_numpy()

    is_spread = (float(np.mean(t_is)) - float(np.mean(b_is))) if (len(t_is) >= 5 and len(b_is) >= 5) else np.nan
    oos_spread = (float(np.mean(t_oos)) - float(np.mean(b_oos))) if (len(t_oos) >= 5 and len(b_oos) >= 5) else np.nan
    full_spread = (float(np.mean(t_full)) - float(np.mean(b_full))) if (len(t_full) >= 10 and len(b_full) >= 10) else np.nan
    pool_t = pooled_tstat(t_full, b_full)

    dt_top = t_df.groupby("dt_str")[ret_col].mean()
    dt_bot = b_df.groupby("dt_str")[ret_col].mean()
    paired = pd.concat([dt_top, dt_bot], axis=1, keys=["top", "bot"]).dropna()
    if len(paired) >= 10:
        paired["sp"] = paired["top"] - paired["bot"]
        p_is = paired[paired.index <= "2023-12-31"]["sp"].to_numpy()
        p_oos = paired[paired.index >= "2024-01-01"]["sp"].to_numpy()
        p_full = paired["sp"].to_numpy()
        d_is_sp = float(np.mean(p_is)) if len(p_is) >= 5 else np.nan
        d_oos_sp = float(np.mean(p_oos)) if len(p_oos) >= 5 else np.nan
        d_full_sp, d_nw_t, _ = newey_west_tstat(p_full, nw_lag)
        d_sp_wr = float(np.mean(p_full > 0))
    else:
        p_is_top = dt_top[dt_top.index <= "2023-12-31"].to_numpy()
        p_is_bot = dt_bot[dt_bot.index <= "2023-12-31"].to_numpy()
        p_oos_top = dt_top[dt_top.index >= "2024-01-01"].to_numpy()
        p_oos_bot = dt_bot[dt_bot.index >= "2024-01-01"].to_numpy()
        d_is_sp = (float(np.mean(p_is_top)) - float(np.mean(p_is_bot))) if (len(p_is_top) >= 5 and len(p_is_bot) >= 5) else np.nan
        d_oos_sp = (float(np.mean(p_oos_top)) - float(np.mean(p_oos_bot))) if (len(p_oos_top) >= 5 and len(p_oos_bot) >= 5) else np.nan
        d_full_sp = (float(dt_top.mean()) - float(dt_bot.mean())) if (len(dt_top) >= 5 and len(dt_bot) >= 5) else np.nan
        if len(dt_top) >= 5 and len(dt_bot) >= 5:
            _, t_t, _ = newey_west_tstat(dt_top.to_numpy(), nw_lag)
            _, b_t, _ = newey_west_tstat(dt_bot.to_numpy(), nw_lag)
            se2 = (dt_top.mean() / t_t) ** 2 + (dt_bot.mean() / b_t) ** 2 if (t_t and b_t and np.isfinite(t_t) and np.isfinite(b_t)) else np.nan
            d_nw_t = float(d_full_sp / math.sqrt(se2)) if (se2 and np.isfinite(se2) and se2 > 0) else np.nan
        else:
            d_nw_t = np.nan
        d_sp_wr = np.nan

    same_dir_pool = bool(np.isfinite(is_spread) and np.isfinite(oos_spread) and (is_spread * oos_spread > 0))
    same_dir_daily = bool(np.isfinite(d_is_sp) and np.isfinite(d_oos_sp) and (d_is_sp * d_oos_sp > 0))

    summary = {
        "top_bucket": top_b,
        "bot_bucket": bot_b,
        "top_stats": b_stats.get(top_b, {}),
        "bot_stats": b_stats.get(bot_b, {}),
        "is_spread": is_spread,
        "oos_spread": oos_spread,
        "full_spread": full_spread,
        "pooled_t": pool_t,
        "daily_paired_days": int(len(paired)) if len(paired) >= 10 else 0,
        "daily_is_spread": d_is_sp,
        "daily_oos_spread": d_oos_sp,
        "daily_full_spread": d_full_sp,
        "daily_nw_t": d_nw_t,
        "daily_sp_wr": d_sp_wr,
        "oos_same_dir_pool": same_dir_pool,
        "oos_same_dir_daily": same_dir_daily,
    }
    return summary, bucket_rows


def run_fama_macbeth_orthogonal(df: pd.DataFrame, ret_col: str = "ret_5d", nw_lag: int = 4) -> list[dict]:
    """Run daily Fama-MacBeth cross-sectional OLS on standardized orthogonal continuous/dummy factors."""
    feats = [
        ("ret_pre5_exT", "前5日涨跌[T-6,T-1]"),
        ("ret_pre20_exT", "前20日涨跌[T-21,T-1]"),
        ("rebound20_flag", "拓普式先跌20d>10%再大弹>=3%"),
        ("pos60", "60日箱体位置"),
        ("dd20", "距20日高点回撤"),
        ("pct", "当日涨跌幅d0_pct"),
        ("is_zt_flag", "当日真涨停"),
        ("log_vol_ratio", "对数量比ln(VR5)"),
        ("to_pct", "当日换手率%"),
        ("log_mcap", "对数市值ln(mcap)"),
        ("clv", "收盘光头强度CLV"),
        ("d1_open_pct", "次日开盘幅度d1_open"),
        ("notice_earn_pos_90d", "近90天业绩正增"),
        ("notice_regtox_5y_90d", "近90天监管毒丸(5Y)"),
        ("ir_ge3_30d", "近30天调研>=3次"),
        ("lhb_inst_buy_flag", "近5日机构净买>0"),
        ("lhb_lhasa_5d", "近5日拉萨出现"),
        ("xq_log_7d", "对数雪球7日发帖(PIT)"),
        ("p_sz", "板块涨停数p_sz"),
        ("plate_max_board", "板块最高连板"),
        ("is_hard_tech_style", "硬科技板块/行业"),
    ]
    w = df[df[ret_col].notna()].copy()
    w["rebound20_flag"] = ((w["ret_pre20_exT"] < -0.10) & (w["pct"] >= 0.03)).astype(float)
    w["is_zt_flag"] = w["is_zt"].astype(float)
    w["log_vol_ratio"] = np.log1p(np.clip(w["vol_ratio_5d"], 0, 50))
    w["log_mcap"] = np.log(np.clip(w["mcap"], 1.0, 1e6))
    w["ir_ge3_30d"] = (w["ir_cnt_30d"] >= 3).astype(float)
    w["xq_log_7d"] = np.log1p(w["xq_posts_7d"])
    w["lhb_inst_buy_flag"] = (w["lhb_inst_net_5d_wan"].fillna(0) > 0).astype(float)
    w["is_hard_tech_style"] = (w["sector_style"] == "硬科技").astype(float)

    fcols = [f[0] for f in feats]
    w = w.dropna(subset=fcols + [ret_col]).copy()
    for fc in fcols:
        if w[fc].nunique() > 5:
            lo, hi = w[fc].quantile(0.01), w[fc].quantile(0.99)
            w[fc] = np.clip(w[fc], lo, hi)

    betas_is, betas_oos, betas_full = [], [], []
    for dt_s, grp in w.groupby("dt_str"):
        if len(grp) < 30:
            continue
        X = grp[fcols].to_numpy(dtype=float)
        std = X.std(axis=0)
        keep = std > 1e-8
        if keep.sum() < 5:
            continue
        Xz = np.zeros_like(X)
        Xz[:, keep] = (X[:, keep] - X[:, keep].mean(axis=0)) / std[keep]
        X_des = np.column_stack([np.ones(len(grp)), Xz])
        y = grp[ret_col].to_numpy(dtype=float)
        XtX = X_des.T @ X_des + np.eye(X_des.shape[1]) * 1e-3
        b = np.linalg.solve(XtX, X_des.T @ y)[1:]
        b[~keep] = np.nan
        betas_full.append(b)
        if dt_s <= "2023-12-31":
            betas_is.append(b)
        else:
            betas_oos.append(b)

    B_full = np.array(betas_full)
    B_is = np.array(betas_is)
    B_oos = np.array(betas_oos)
    out = []
    for j, (fc, fdesc) in enumerate(feats):
        mu_f, t_f, n_f = newey_west_tstat(B_full[:, j], nw_lag)
        mu_is, t_is, _ = newey_west_tstat(B_is[:, j], nw_lag) if len(B_is) else (np.nan, np.nan, 0)
        mu_oos, t_oos, _ = newey_west_tstat(B_oos[:, j], nw_lag) if len(B_oos) else (np.nan, np.nan, 0)
        out.append({
            "feature": fc,
            "desc": fdesc,
            "n_days": n_f,
            "beta_is_bps": round(mu_is * 10000, 2) if np.isfinite(mu_is) else None,
            "t_is": round(t_is, 2) if np.isfinite(t_is) else None,
            "beta_oos_bps": round(mu_oos * 10000, 2) if np.isfinite(mu_oos) else None,
            "t_oos": round(t_oos, 2) if np.isfinite(t_oos) else None,
            "beta_full_bps": round(mu_f * 10000, 2) if np.isfinite(mu_f) else None,
            "nw_t_full": round(t_f, 2) if np.isfinite(t_f) else None,
            "is_oos_same_sign": bool(np.isfinite(mu_is) and np.isfinite(mu_oos) and (mu_is * mu_oos > 0)),
        })
    out.sort(key=lambda r: abs(r["nw_t_full"] or 0.0), reverse=True)
    return out


def eval_composite_orthogonal_filter(cand: pd.DataFrame) -> dict:
    """Verify practical orthogonal composite rules in IS vs OOS vs >=250亿 vs No-Rescue."""
    rules = {
        "0_Baseline_All": pd.Series(True, index=cand.index),
        "1_Toxic_Purge_Only(no_xq & no_lhasa & no_zt & clv<0.7 & to<10%)": (
            (cand["xq_posts_7d"] == 0) & (cand["lhb_lhasa_5d"] == 0) & (~cand["is_zt"])
            & (cand["clv"] < 0.7) & (cand["to_pct"] < 10.0)
        ),
        "2_Rebound20_Clean(pre20<-10% & d0>=3% & xq==0 & d1_open<2% & no_lhasa)": (
            (cand["ret_pre20_exT"] < -0.10) & (cand["pct"] >= 0.03)
            & (cand["xq_posts_7d"] == 0) & (cand["d1_open_pct"] < 0.02) & (cand["lhb_lhasa_5d"] == 0)
        ),
        "3_Inst_Endorsed_Clean(ir30>=3 or inst5d>5000w, xq==0 & no_lhasa & ~is_zt & d1_open<2%)": (
            ((cand["ir_cnt_30d"] >= 3) | (cand["lhb_inst_net_5d_wan"].fillna(-1) > 5000.0))
            & (cand["xq_posts_7d"] == 0) & (cand["lhb_lhasa_5d"] == 0)
            & (~cand["is_zt"]) & (cand["d1_open_pct"] < 0.02)
        ),
        "4_Macro_Liquidity_Plus_Rebound(mkt_amt>=1.15 & pre20<-10% & d0>=3% & xq==0 & d1_open<2%)": (
            (cand["mkt_amt_ratio"] >= 1.15) & (cand["ret_pre20_exT"] < -0.10) & (cand["pct"] >= 0.03)
            & (cand["xq_posts_7d"] == 0) & (cand["d1_open_pct"] < 0.02)
        ),
    }
    res = {}
    for name, mask in rules.items():
        r_out = {}
        for p_lbl, pm in [
            ("IS_150", mask & (cand["dt_str"] <= "2023-12-31")),
            ("OOS_150", mask & (cand["dt_str"] >= "2024-01-01")),
            ("OOS_NoRes", mask & (cand["dt_str"] >= "2024-01-01") & (~cand["dt_str"].isin(RESCUE_DTS))),
            ("Full_250", mask & (cand["mcap"] >= 250.0)),
        ]:
            sub = cand[pm]
            d5 = sub.dropna(subset=["ret_5d"]).groupby("dt_str")["ret_5d"].mean()
            d10 = sub.dropna(subset=["ret_10d"]).groupby("dt_str")["ret_10d"].mean()
            m5, t5, _ = newey_west_tstat(d5.to_numpy(), 4)
            m10, t10, _ = newey_west_tstat(d10.to_numpy(), 9)
            r_out[p_lbl] = {
                "n": int(len(sub)),
                "days": int(len(d5)),
                "pool_5d_pct": round(float(sub["ret_5d"].mean()) * 100, 3) if sub["ret_5d"].notna().any() else None,
                "daily_5d_pct": round(m5 * 100, 3) if np.isfinite(m5) else None,
                "daily_5d_wr": round(float((d5 > 0).mean()) * 100, 2) if len(d5) else None,
                "nw_t5": round(t5, 2) if np.isfinite(t5) else None,
                "pool_10d_pct": round(float(sub["ret_10d"].mean()) * 100, 3) if sub["ret_10d"].notna().any() else None,
                "daily_10d_pct": round(m10 * 100, 3) if np.isfinite(m10) else None,
                "nw_t10": round(t10, 2) if np.isfinite(t10) else None,
            }
        res[name] = r_out
    return res


def main():
    t0 = time.time()
    idx_5y = json.load(open(pdb.IDX_5Y_PATH, encoding="utf-8"))
    csi300_map = idx_5y["sh000300"]

    df, hp_df, all_mkt_dts, dt_to_mkt_idx, mkt_stats_map, syn_1000_map, syn_corr, csrc_df = pdb.build_daily_and_kpl()
    cand = pdb.compute_stock_technicals_and_returns(df, hp_df, all_mkt_dts, dt_to_mkt_idx, csi300_map)
    cand = pdb.enrich_pit_external_factors(cand, all_mkt_dts, dt_to_mkt_idx, mkt_stats_map, syn_1000_map, csi300_map, idx_5y, csrc_df)

    specs = build_factor_specs(cand)
    out_dir = PART2_DIR
    os.makedirs(out_dir, exist_ok=True)
    cand.to_parquet(f"{out_dir}/cand_pool_5y_pit.parquet", index=False)

    horizons = [("1d", "ret_1d", 1), ("3d", "ret_3d", 2), ("5d", "ret_5d", 4), ("10d", "ret_10d", 9), ("20d", "ret_20d", 19)]
    ledger_rows = []
    factor_summaries = []

    sub_150 = cand
    sub_250 = cand[cand["mcap"] >= 250.0].copy()
    sub_150_norescue = cand[~cand["dt_str"].isin(RESCUE_DTS)].copy()

    print(f"[Eval] Running {len(specs)} factors across 5 horizons + >=250亿 + no-rescue + CSI300 excess...")
    for fid, cat, col, top_b, bot_b, desc in specs:
        f_entry = {"factor_id": fid, "category": cat, "col": col, "desc": desc, "top_bucket": top_b, "bot_bucket": bot_b, "horizons": {}}
        for h_name, r_col, nw_lag in horizons:
            s_150, b_rows = eval_factor_horizon(sub_150, col, top_b, bot_b, r_col, nw_lag)
            f_entry["horizons"][h_name] = s_150
            for br in b_rows:
                ledger_rows.append({
                    "pool": "mcap>=150",
                    "horizon": h_name,
                    "factor_id": fid,
                    "category": cat,
                    "desc": desc,
                    "bucket": br["bucket"],
                    "is_top": int(br["bucket"] == top_b),
                    "is_bot": int(br["bucket"] == bot_b),
                    "n_is": br["n_is"],
                    "is_mean_pct": round(br["is_mean"] * 100, 3) if np.isfinite(br["is_mean"]) else None,
                    "is_wr_pct": round(br["is_wr"] * 100, 2) if np.isfinite(br["is_wr"]) else None,
                    "n_oos": br["n_oos"],
                    "oos_mean_pct": round(br["oos_mean"] * 100, 3) if np.isfinite(br["oos_mean"]) else None,
                    "oos_wr_pct": round(br["oos_wr"] * 100, 2) if np.isfinite(br["oos_wr"]) else None,
                    "n_full": br["n_full"],
                    "full_mean_pct": round(br["full_mean"] * 100, 3) if np.isfinite(br["full_mean"]) else None,
                    "full_wr_pct": round(br["full_wr"] * 100, 2) if np.isfinite(br["full_wr"]) else None,
                    "d_is_mean_pct": round(br["d_is_mean"] * 100, 3) if np.isfinite(br["d_is_mean"]) else None,
                    "d_oos_mean_pct": round(br["d_oos_mean"] * 100, 3) if np.isfinite(br["d_oos_mean"]) else None,
                    "d_full_mean_pct": round(br["d_full_mean"] * 100, 3) if np.isfinite(br["d_full_mean"]) else None,
                    "d_full_wr_pct": round(br["d_full_wr"] * 100, 2) if np.isfinite(br["d_full_wr"]) else None,
                    "is_spread_pct": round(s_150["is_spread"] * 100, 3) if np.isfinite(s_150["is_spread"]) else None,
                    "oos_spread_pct": round(s_150["oos_spread"] * 100, 3) if np.isfinite(s_150["oos_spread"]) else None,
                    "full_spread_pct": round(s_150["full_spread"] * 100, 3) if np.isfinite(s_150["full_spread"]) else None,
                    "pooled_t": round(s_150["pooled_t"], 2) if np.isfinite(s_150["pooled_t"]) else None,
                    "daily_is_spread_pct": round(s_150["daily_is_spread"] * 100, 3) if np.isfinite(s_150["daily_is_spread"]) else None,
                    "daily_oos_spread_pct": round(s_150["daily_oos_spread"] * 100, 3) if np.isfinite(s_150["daily_oos_spread"]) else None,
                    "daily_full_spread_pct": round(s_150["daily_full_spread"] * 100, 3) if np.isfinite(s_150["daily_full_spread"]) else None,
                    "daily_nw_t": round(s_150["daily_nw_t"], 2) if np.isfinite(s_150["daily_nw_t"]) else None,
                    "oos_same_dir_pool": s_150["oos_same_dir_pool"],
                    "oos_same_dir_daily": s_150["oos_same_dir_daily"],
                })

        f_entry["mcap250_5d"] = eval_factor_horizon(sub_250, col, top_b, bot_b, "ret_5d", 4)[0]
        f_entry["mcap250_10d"] = eval_factor_horizon(sub_250, col, top_b, bot_b, "ret_10d", 9)[0]
        f_entry["norescue_5d"] = eval_factor_horizon(sub_150_norescue, col, top_b, bot_b, "ret_5d", 4)[0]
        f_entry["norescue_10d"] = eval_factor_horizon(sub_150_norescue, col, top_b, bot_b, "ret_10d", 9)[0]
        f_entry["ex300_5d"] = eval_factor_horizon(sub_150, col, top_b, bot_b, "ex_5d", 4)[0]
        f_entry["ex300_10d"] = eval_factor_horizon(sub_150, col, top_b, bot_b, "ex_10d", 9)[0]
        factor_summaries.append(f_entry)

    df_ledger = pd.DataFrame(ledger_rows)
    df_ledger.to_csv(f"{out_dir}/factors_ledger.csv", index=False)

    fm_5d = run_fama_macbeth_orthogonal(sub_150, "ret_5d", 4)
    fm_10d = run_fama_macbeth_orthogonal(sub_150, "ret_10d", 9)
    fm_250_5d = run_fama_macbeth_orthogonal(sub_250, "ret_5d", 4)
    composite_ortho = eval_composite_orthogonal_filter(sub_150)

    corr_cols = [
        "ret_pre5_exT", "ret_pre20_exT", "pos60", "dd20", "pct",
        "vol_ratio_5d", "to_pct", "amt_yi", "mcap", "clv", "d1_open_pct",
        "notice_earn_pos_90d", "notice_regtox_5y_90d", "ir_cnt_30d", "xq_posts_7d",
        "p_sz", "plate_max_board", "csi300_ret5", "mkt_zt_cnt"
    ]
    corr_mat = sub_150[corr_cols].corr().round(3).to_dict()

    pool_stats = {}
    for p_name, p_df in [("mcap>=150", sub_150), ("mcap>=250", sub_250), ("mcap>=150_norescue", sub_150_norescue)]:
        ps = {"n_rows": int(len(p_df)), "n_days": int(p_df["dt_str"].nunique()), "n_stocks": int(p_df["c6"].nunique())}
        for h_n, rc, nw in horizons:
            sub_h = p_df[p_df[rc].notna()]
            d_ser = sub_h.groupby("dt_str")[rc].mean()
            mu_d, t_d, _ = newey_west_tstat(d_ser.to_numpy(), nw)
            ps[h_n] = {
                "n": int(len(sub_h)),
                "pool_mean_pct": round(float(sub_h[rc].mean()) * 100, 3),
                "pool_wr_pct": round(float((sub_h[rc] > 0).mean()) * 100, 2),
                "daily_mean_pct": round(mu_d * 100, 3) if np.isfinite(mu_d) else None,
                "daily_wr_pct": round(float((d_ser > 0).mean()) * 100, 2) if len(d_ser) else None,
                "daily_nw_t": round(t_d, 2) if np.isfinite(t_d) else None,
            }
        pool_stats[p_name] = ps

    def clean_json(obj):
        if isinstance(obj, dict):
            return {k: clean_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [clean_json(v) for v in obj]
        if isinstance(obj, (np.floating, float)):
            return None if (not np.isfinite(obj)) else round(float(obj), 6)
        if isinstance(obj, (np.integer, int)):
            return int(obj)
        if isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        return obj

    summary = clean_json({
        "meta": {
            "bt_start": pdb.BT_START,
            "bt_end": pdb.BT_END,
            "is_window": "2021-11-15 ~ 2023-12-31",
            "oos_window": "2024-01-01 ~ 2026-11-23",
            "fee_roundtrip": pdb.FEE_RATE,
            "syn_csi1000_corr_2026": syn_corr,
            "n_factors": len(specs),
            "elapsed_sec": round(time.time() - t0, 1),
        },
        "pool_baseline": pool_stats,
        "fama_macbeth_5d_mcap150": fm_5d,
        "fama_macbeth_10d_mcap150": fm_10d,
        "fama_macbeth_5d_mcap250": fm_250_5d,
        "composite_orthogonal_tests": composite_ortho,
        "corr_matrix": corr_mat,
        "factors": factor_summaries,
    })
    with open(f"{out_dir}/summary_part2.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] Saved {out_dir}/factors_ledger.csv ({len(df_ledger)} rows) & summary_part2.json in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
