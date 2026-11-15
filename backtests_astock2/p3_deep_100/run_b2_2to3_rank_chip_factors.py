#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_b2_2to3_rank_chip_factors.py — B2 二进三策略专项因子回测
将《一进二 V18》全部板块内排位、伴生一字阶梯、竞价断层、高潮传感器与筹码双通道共 32+ 因子（70+ 精细切片）
在 10cm 主板非 ST 非一字二板可买池（prev_streak==2 & ~prev_is_yizi & buyable_open）上逐个挨个回测。
同时评估：
  - 模式A：一进二式点火 max(open*1.012, pre_c*1.065) (11:30前触发) + 封三板后转13:45护利 (dyn65_12_1130 + pm1345_5m + reb2)
  - 模式B：竞价 09:25 open + 封三板后转13:45护利 (open_reb2)
  - 以及在【同题材二板竞价第1名 (2b_plate_buy_rk == 1)】骨架上的边际增减。
铁律：零 yfinance (D12)、SQLite mode=ro、不改 portfolio_state.json、统一调用 common_eval_harness.eval_factor_slice。
"""
import os
import sys
import json
import time
import pickle
import sqlite3
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
AST2_DIR = f"{SIM_DIR}/backtests_astock2"
P2_DIR = f"{AST2_DIR}/p2_2to3"
P3_DIR = f"{AST2_DIR}/p3_deep_100"
MAT_DIR = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
FEE = 0.0020

if P3_DIR not in sys.path:
    sys.path.insert(0, P3_DIR)
if AST2_DIR not in sys.path:
    sys.path.insert(0, AST2_DIR)

from common_eval_harness import eval_factor_slice, CSI_BENCH
from core_3to4_5m_engine import sim_buy_5m, sim_exit_5m

OUT_SCRIPT_CSV = f"{P3_DIR}/b2_2to3_rank_yizi_chip_factors.csv"
OUT_SUMMARY_JSON = f"{P3_DIR}/b2_summary.json"


def load_all_local_5m(needed_codes: set) -> dict:
    """加载全部本地 5 分钟 K 线缓存（Parquet + 只读 SQLite）。"""
    bars = {}
    for pq in [
        f"{SIM_DIR}/data/cand_5m_bars_v15_complete.parquet",
        f"{AST2_DIR}/data_5y/cand_3to4_5m_bars.parquet",
        f"{AST2_DIR}/p2_4to5/cand_4to5_5m_bars.parquet",
    ]:
        if os.path.exists(pq):
            d5 = pd.read_parquet(
                pq, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"]
            )
            d5["c6"] = d5["c6"].astype(str).str.zfill(6)
            d5 = d5[d5["c6"].isin(needed_codes)].sort_values(["c6", "date", "hhmm_int"])
            for (c, dt_s), g in d5.groupby(["c6", "date"], sort=False):
                if (c, dt_s) not in bars:
                    bars[(c, dt_s)] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)

    db_p = f"{SIM_DIR}/data/firstboard_5m_5y_pit.db"
    if os.path.exists(db_p):
        con = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
        q_codes = sorted(needed_codes)
        for i in range(0, len(q_codes), 400):
            sub_c = q_codes[i:i + 400]
            qm = ",".join(["?"] * len(sub_c))
            sql = (
                "SELECT sec_code, substr(bar_time,1,10) as dt, "
                "CAST(substr(bar_time,12,2)||substr(bar_time,15,2) AS INT) as hhmm_int, "
                "open, high, low, close, volume, amount "
                f"FROM firstboard_5m_bars WHERE sec_code IN ({qm})"
            )
            dfb = pd.read_sql_query(sql, con, params=sub_c)
            if not dfb.empty:
                dfb["c6"] = dfb["sec_code"].astype(str).str.zfill(6)
                dfb.sort_values(["c6", "dt", "hhmm_int"], inplace=True)
                for (c, dt_s), g in dfb.groupby(["c6", "dt"], sort=False):
                    if (c, dt_s) not in bars:
                        bars[(c, dt_s)] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        con.close()
    return bars


def sim_mode_a_dyn65_12(df: pd.DataFrame, cb_map: dict, bars_5m: dict) -> list:
    """模式A: 一进二式点火 max(open*1.012, pre_c*1.065) (11:30前触发) + 封三板后转13:45护利 (pm1345_5m + reb2)。"""
    out = [None] * len(df)
    for idx, r in enumerate(df.itertuples(index=False)):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = cb_map.get(c6)
        if cb is None:
            continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1:
            continue
        if (c6, bd) in bars_5m:
            bpx, bhh = sim_buy_5m(c6, bd, cb, pos, bars_5m, "dyn65_12_1130")
        else:
            op, pc, hi, zt = float(cb["open"][pos]), float(cb["pre_c"][pos]), float(cb["high"][pos]), float(cb["zt_px"][pos])
            trig = max(pc * 1.065, op * 1.012)
            if op >= zt - 0.005 or trig >= zt - 0.005 or hi < trig:
                continue
            bpx, bhh = max(op, trig), 1000
        if bpx is None:
            continue
        ex_dt, spx, adjs, hb, shh = sim_exit_5m(
            c6, cb, pos, bars_5m, exit_mode="pm1345_5m", day5_unsealed_mode="reb2", use_yang_imm=False
        )
        net_r = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
        out[idx] = {
            "code": c6, "name": r.name, "buy_date": bd, "buy_hhmm": bhh,
            "exit_date": ex_dt, "exit_hhmm": shh, "hold_bars": hb, "net_ret": float(net_r),
        }
    return out


def build_cross_board_features(df_en: pd.DataFrame) -> pd.DataFrame:
    """
    基于全市场 10cm 主板非 ST 原始表（cand_2to3, cand_0to1_firstboard, cand_3to4, cand_high_dragon）
    精确构造无未来函数的同题材二板排位、一字锁筹阶梯、高标大哥压制、首板次日表现等特征。
    """
    df = df_en.copy()

    def _is_10cm_nonst(d: pd.DataFrame) -> pd.Series:
        c = d["code"].astype(str).str.zfill(6)
        return c.str.startswith(("00", "60")) & (~d["name"].astype(str).str.upper().str.contains("ST"))

    # 1. 全量 10cm 2板池（含一字不可买与跌停），用于精确计算同题材一字二板数与全场二进三一字数
    d23_raw = pd.read_parquet(
        f"{MAT_DIR}/cand_2to3.parquet",
        columns=["code", "name", "sig_date", "buy_date", "gap_days", "prev_is_yizi", "open_pct", "buyable_open", "is_yizi_open", "plate", "r_short", "p_sz"],
    )
    d23_10 = d23_raw[_is_10cm_nonst(d23_raw)].copy()
    d23_10["c6"] = d23_10["code"].astype(str).str.zfill(6)

    # 全场二进三一字数 (buy_date)
    mkt_2b_yizi_map = d23_10[d23_10["is_yizi_open"]].groupby("buy_date").size().to_dict()
    df["mkt_2to3_yizi_cnt"] = df["buy_date"].map(mkt_2b_yizi_map).fillna(0).astype(int)

    # 同题材二板一字数 (buy_date, plate; plate=="其他"不归为同一题材)
    d23_named = d23_10[d23_10["plate"].notna() & (d23_10["plate"] != "") & (d23_10["plate"] != "其他")]
    p_2b_yz_map = d23_named[d23_named["is_yizi_open"]].groupby(["buy_date", "plate"]).size().to_dict()
    p_2b_tot_map = d23_named.groupby(["buy_date", "plate"]).size().to_dict()

    # V18 前排锁筹口径 (is_yizi_open 或 Tue-Fri > 7.8% / Mon > 8.8%)
    wk23 = d23_named["gap_days"] >= 3
    fl_mask = d23_named["is_yizi_open"] | ((~wk23) & (d23_named["open_pct"] > 0.078)) | (wk23 & (d23_named["open_pct"] > 0.088))
    p_2b_fl_map = d23_named[fl_mask].groupby(["buy_date", "plate"]).size().to_dict()

    df["plate_2b_yizi_cnt"] = [
        p_2b_yz_map.get((b, p), 0) if (p and p != "其他") else 0
        for b, p in zip(df["buy_date"], df["plate"])
    ]
    df["plate_2b_tot_cnt"] = [
        p_2b_tot_map.get((b, p), 1) if (p and p != "其他") else 1
        for b, p in zip(df["buy_date"], df["plate"])
    ]
    df["front_lock_2b"] = [
        p_2b_fl_map.get((b, p), 0) if (p and p != "其他") else 0
        for b, p in zip(df["buy_date"], df["plate"])
    ]

    # 2. 同题材可买二板排位与全场可买二板排位 (基于 df_en = 全量 10cm buyable_open 2板 6542 只)
    df["mkt_2b_open_rk"] = df.groupby("buy_date")["open_pct"].rank(ascending=False, method="min").astype(int)
    df["day_2b_buyable_cnt"] = df.groupby("buy_date")["code"].transform("count").astype(int)

    named_mask = df["plate"].notna() & (df["plate"] != "") & (df["plate"] != "其他")
    df["plate_2b_cnt"] = 1
    df["2b_plate_buy_rk"] = 1
    df["open_lead_plate_rk2_clean"] = 0.0

    # 仅在有名题材内分组排位（"其他" 互不为同题材）
    grp_named = df[named_mask].groupby(["buy_date", "plate"])
    df.loc[named_mask, "plate_2b_cnt"] = grp_named["code"].transform("count").astype(int)
    df.loc[named_mask, "2b_plate_buy_rk"] = grp_named["open_pct"].rank(ascending=False, method="min").astype(int)

    # 精确计算第1名领先第2名幅度 (仅 plate_2b_cnt >= 2 且 rk == 1)
    p_sorted = {}
    for (bd, pl), g in df[named_mask].groupby(["buy_date", "plate"], sort=False):
        ops = sorted(g["open_pct"].tolist(), reverse=True)
        p_sorted[(bd, pl)] = ops

    lead_list = []
    for r in df.itertuples(index=False):
        if r.plate != "其他" and r._asdict().get("plate_2b_cnt", 1) >= 2:
            ops = p_sorted.get((r.buy_date, r.plate), [])
            if len(ops) >= 2 and abs(r.open_pct - ops[0]) < 1e-9:
                lead_list.append(float(ops[0] - ops[1]))
            else:
                lead_list.append(0.0)
        else:
            lead_list.append(0.0)
    # Use direct column iteration to avoid namedtuple field renaming issues on '2b_plate_buy_rk'
    lead_vals = []
    for bd, pl, op_v, pcnt, rk in zip(df["buy_date"], df["plate"], df["open_pct"], df["plate_2b_cnt"], df["2b_plate_buy_rk"]):
        if pl != "其他" and pcnt >= 2 and rk == 1:
            ops = p_sorted.get((bd, pl), [])
            lead_vals.append(float(ops[0] - ops[1]) if len(ops) >= 2 else 0.0)
        else:
            lead_vals.append(0.0)
    df["open_lead_plate_rk2_clean"] = lead_vals

    # 3. 细分分支龙头 (p_sz >= 8 下 r_short 子分支排第1)
    sub_mask = (
        named_mask
        & (df["p_sz"] >= 8)
        & df["r_short"].notna()
        & (df["r_short"] != "")
        & (df["r_short"] != "其他")
        & (df["r_short"] != df["plate"])
    )
    df["has_distinct_sub"] = sub_mask
    df["subbranch_rk"] = 99
    if sub_mask.any():
        df.loc[sub_mask, "subbranch_rk"] = (
            df[sub_mask].groupby(["buy_date", "plate", "r_short"])["open_pct"]
            .rank(ascending=False, method="min")
            .astype(int)
        )

    # 4. Day2 (sig_date) 同题材是否有 >=3板 高标大哥压制 (cand_high_dragon + cand_3to4)
    dhd = pd.read_parquet(f"{MAT_DIR}/cand_high_dragon.parquet", columns=["code", "name", "sig_date", "prev_streak", "plate"])
    d34 = pd.read_parquet(f"{MAT_DIR}/cand_3to4.parquet", columns=["code", "name", "sig_date", "prev_streak", "plate"])
    d_ge3 = pd.concat([dhd, d34], ignore_index=True)
    d_ge3 = d_ge3[_is_10cm_nonst(d_ge3) & (d_ge3["prev_streak"] >= 3)]
    d_ge3_named = d_ge3[d_ge3["plate"].notna() & (d_ge3["plate"] != "") & (d_ge3["plate"] != "其他")]
    big_bro_pairs = set(zip(d_ge3_named["sig_date"], d_ge3_named["plate"]))
    df["has_plate_3b_plus_big_bro"] = [
        ((s, p) in big_bro_pairs) if (p and p != "其他") else False
        for s, p in zip(df["sig_date"], df["plate"])
    ]
    df["is_plate_highest_dragon"] = ~df["has_plate_3b_plus_big_bro"]

    # 5. Day2 (sig_date) 同题材首板在 Day3 (buy_date) 一字与高开数量 (cand_0to1_firstboard)
    d01 = pd.read_parquet(
        f"{MAT_DIR}/cand_0to1_firstboard.parquet",
        columns=["code", "name", "sig_date", "buy_date", "plate", "open_pct", "is_yizi_open", "is_zt_today"],
    )
    d01_10 = d01[_is_10cm_nonst(d01) & (d01["plate"].notna()) & (d01["plate"] != "") & (d01["plate"] != "其他")].copy()
    # 注意: cand_0to1_firstboard 中 sig_date 是 0->1 前一天, buy_date 是首板日 (is_zt_today==True 为真首板)!
    # 所以在 2to3 的 sig_date (=Day2) 封死首板的股票，其 cand_0to1_firstboard.buy_date == 2to3.sig_date!
    # 若要看这些首板次日 (2to3.buy_date = Day3) 的开盘表现，需把 Day2 真首板集合映射到 Day3 open (cand_1to2 或 code_bars)。
    # 此外 2to3.parquet 已有基于 code_bars 算好的 plate_fb_cnt 与 plate_fb_ho_cnt (>=2%高开)；此处补充 Day2 真首板数校验。
    d01_zt = d01_10[d01_10["is_zt_today"] == True]
    fb_cnt_sig_map = d01_zt.groupby(["buy_date", "plate"]).size().to_dict()
    df["plate_fb_cnt_clean"] = [
        fb_cnt_sig_map.get((s, p), 0) if (p and p != "其他") else 0
        for s, p in zip(df["sig_date"], df["plate"])
    ]

    # 6. 派生盘口比例
    df["seal_amt_ratio"] = np.where(df["prev_amt"] > 0, df["seal_amount"] / df["prev_amt"], 0.0)
    return df


def define_factor_specs(df: pd.DataFrame) -> list:
    """定义全部 32+ 《一进二 V18》排位/一字/情绪/筹码因子切片。"""
    sr = df["seal_amt_ratio"]
    specs = [
        # 1. 同题材内可买二板竞价排位
        ("01_同题材唯一二板独苗(plate_2b_cnt==1)", df["plate_2b_cnt"] == 1),
        ("01b_有名题材唯一二板独苗(去其他)", (df["plate"] != "其他") & (df["plate_2b_cnt"] == 1)),
        ("01c_纯独苗(含一字总计plate_2b_tot==1)", df["plate_2b_tot_cnt"] == 1),
        ("02_同题材多二板中竞价第1(cnt>=2&rk==1)", (df["plate_2b_cnt"] >= 2) & (df["2b_plate_buy_rk"] == 1)),
        ("03_同题材二板第1名总集(rk==1)", df["2b_plate_buy_rk"] == 1),
        ("04_同题材二板第2名(rk==2)", df["2b_plate_buy_rk"] == 2),
        ("05_同题材二板第3名及以后(rk>=3)", df["2b_plate_buy_rk"] >= 3),

        # 2. 细分分支龙头
        ("06_大题材细分分支龙头(p_sz>=8&sub_rk==1)", df["has_distinct_sub"] & (df["subbranch_rk"] == 1)),
        ("06b_细分分支第1且非大题材第1(补救通道)", df["has_distinct_sub"] & (df["subbranch_rk"] == 1) & (df["2b_plate_buy_rk"] >= 2)),

        # 3. 板块最高连板空间龙 vs 高标大哥压制
        ("07_板块最高身位真龙(无>=3板压制)", df["is_plate_highest_dragon"]),
        ("07b_有名题材最高身位真龙(去其他)", (df["plate"] != "其他") & df["is_plate_highest_dragon"]),
        ("08_同题材已有>=3板高标压制(补涨小弟)", df["has_plate_3b_plus_big_bro"]),

        # 4. 全场可买二板竞价总排名 & F26
        ("09_全场可买二板竞价第1(mkt_rk==1)", df["mkt_2b_open_rk"] == 1),
        ("10_全场可买二板竞价前2(mkt_rk<=2)", df["mkt_2b_open_rk"] <= 2),
        ("11_全场可买二板竞价前3(mkt_rk<=3)", df["mkt_2b_open_rk"] <= 3),
        ("12_全场可买二板竞价前5(mkt_rk<=5)", df["mkt_2b_open_rk"] <= 5),
        ("13_全场可买二板竞价后排(mkt_rk>10)", df["mkt_2b_open_rk"] > 10),
        ("14_F26唯一二板活口x全场前2", (df["plate_2b_cnt"] == 1) & (df["mkt_2b_open_rk"] <= 2)),
        ("14b_F26有名题材独苗x全场前2", (df["plate"] != "其他") & (df["plate_2b_cnt"] == 1) & (df["mkt_2b_open_rk"] <= 2)),

        # 5. 竞价断层领先优势
        ("15_竞价断层领先第2名>=1.0%", df["open_lead_plate_rk2_clean"] >= 0.010),
        ("16_竞价断层领先第2名>=2.0%", df["open_lead_plate_rk2_clean"] >= 0.020),
        ("17_竞价断层领先第2名>=2.5%", df["open_lead_plate_rk2_clean"] >= 0.025),

        # 6. 同题材二板前排一字锁筹阶梯 & 90亿规则
        ("18_同题材1只二板一字+本股换手第1(黄金共振)", (df["plate_2b_yizi_cnt"] == 1) & (df["2b_plate_buy_rk"] == 1)),
        ("18b_front_lock==1+本股换手第1(含>7.8%前排)", (df["front_lock_2b"] == 1) & (df["2b_plate_buy_rk"] == 1)),
        ("19_同题材>=2只二板顶一字(通道堵死)", df["plate_2b_yizi_cnt"] >= 2),
        ("19b_front_lock>=2(前排顶死>=2只)", df["front_lock_2b"] >= 2),
        ("20_全场二进三一字数==0", df["mkt_2to3_yizi_cnt"] == 0),
        ("21_全场二进三一字数1~2只", df["mkt_2to3_yizi_cnt"].isin([1, 2])),
        ("22_全场二进三一字数>=3只", df["mkt_2to3_yizi_cnt"] >= 3),
        ("23_V18_90亿伴生二板一字(plate_2b_yz>=1&mcap>90)", (df["plate_2b_yizi_cnt"] >= 1) & (df["mcap"] > 90.0)),
        ("23b_V18_90亿伴生全板一字(plate_yz>=1&mcap>90)", (df["plate_yizi_cnt"] >= 1) & (df["mcap"] > 90.0)),
        ("23c_同题材首板次日高开>=2只(plate_fb_ho>=2)", df["plate_fb_ho_cnt"] >= 2),

        # 7. Day3 竞价开盘窗口精细分箱
        ("24_竞价深水低开(open<-2%)", df["open_pct"] < -0.02),
        ("25_竞价浅水低开(-2%~0%)", (df["open_pct"] >= -0.02) & (df["open_pct"] < 0.0)),
        ("26_竞价微幅高开(0%~2.2%)", (df["open_pct"] >= 0.0) & (df["open_pct"] < 0.022)),
        ("27_竞价温和高开(2.2%~4.0%)", (df["open_pct"] >= 0.022) & (df["open_pct"] < 0.040)),
        ("28_竞价强势高开(4.0%~7.8%)", (df["open_pct"] >= 0.040) & (df["open_pct"] <= 0.078)),
        ("29_竞价超强抢筹(open>7.8%)", df["open_pct"] > 0.078),
        ("30_周一节后窗口(gap>=3&open_1.5~9.0%)", (df["gap_days"] >= 3) & df["open_pct"].between(0.015, 0.090)),
        ("31_周一断层直买(gap>=3&lead>=2.5%)", (df["gap_days"] >= 3) & (df["open_lead_plate_rk2_clean"] >= 0.025)),

        # 8. 宏观情绪与高潮熔断传感器
        ("32_昨涨停家数>=100(百股高潮)", df["mkt_zt_prev"] >= 100),
        ("33_昨涨停家数95~99(准高潮)", df["mkt_zt_prev"].between(95, 99)),
        ("34_昨涨停家数45~94(健康活跃)", df["mkt_zt_prev"].between(45, 94)),
        ("35_昨涨停家数35~85(舒适区)", df["mkt_zt_prev"].between(35, 85)),
        ("36_昨涨停家数<35(冰点缩量)", df["mkt_zt_prev"] < 35),
        ("37_昨封板率>=80%(极度一致高潮)", df["mkt_seal_rate_prev"] >= 0.80),
        ("38_昨封板率>75%(高潮警戒)", df["mkt_seal_rate_prev"] > 0.75),
        ("39_昨封板率<64%(分歧偏弱)", df["mkt_seal_rate_prev"] < 0.64),
        ("40_F13高潮淘汰赛(seal>=75%&day2b>=12)", (df["mkt_seal_rate_prev"] >= 0.75) & (df["day_2b_cnt"] >= 12)),
        ("41_昨跌停家数<=6(安全无恐慌)", df["mkt_dt_prev"] <= 6),
        ("42_昨跌停家数>=15(亏钱效应扩散)", df["mkt_dt_prev"] >= 15),
        ("43_首板核按钮熔断(mkt_fb_open_avg<0)", df["mkt_fb_open_avg"] < 0.0),
        ("44_晋级率冰点(mkt_promo_1to2_5d<0.13)", df["mkt_promo_1to2_5d"] < 0.13),

        # 9. 一进二 V18 筹码双通道全因子
        ("45_总市值<35亿(微盘)", df["mcap"] < 35.0),
        ("46_F05_15~40亿唯一二板", df["mcap"].between(15.0, 40.0) & (df["plate_2b_cnt"] == 1)),
        ("46b_F05_15~40亿有名题材唯一二板", df["mcap"].between(15.0, 40.0) & (df["plate"] != "其他") & (df["plate_2b_cnt"] == 1)),
        ("47_总市值40~60亿(小盘甜点)", (df["mcap"] >= 40.0) & (df["mcap"] < 60.0)),
        ("48_总市值60~155亿(中盘)", (df["mcap"] >= 60.0) & (df["mcap"] <= 155.0)),
        ("49_总市值>155亿(大盘股)", df["mcap"] > 155.0),
        ("50_昨成交额<1.8亿(流动性不足)", df["prev_amt"] < 1.8e8),
        ("51_昨成交额2.2~15亿(黄金容量)", df["prev_amt"].between(2.2e8, 15.0e8)),
        ("52_昨成交额>15亿(大成交放量)", df["prev_amt"] > 15.0e8),
        ("53_dd20<=0.82(20日回撤超18%)", df["dd20"] <= 0.82),
        ("54_dd20<=0.86(20日回撤超14%)", df["dd20"] <= 0.86),
        ("55_dd20<=0.90(20日回撤超10%)", df["dd20"] <= 0.90),
        ("56_dd20>0.95(20日高位贴顶)", df["dd20"] > 0.95),
        ("57_dd60<=0.76(60日深坑超24%)", df["dd60"] <= 0.76),
        ("58_dd60<=0.82(60日超跌超18%)", df["dd60"] <= 0.82),
        ("59_dd60>0.92(60日高位区)", df["dd60"] > 0.92),
        ("60_N型龙回头(zt20>=1&dd20<=0.86)", (df["zt_cnt_pre20"] >= 1) & (df["dd20"] <= 0.86)),
        ("60b_真N型前妖回头(zt20>=3&dd20<=0.86)", (df["zt_cnt_pre20"] >= 3) & (df["dd20"] <= 0.86)),
        ("61_高位连板(zt20>=1&dd20>0.92)", (df["zt_cnt_pre20"] >= 1) & (df["dd20"] > 0.92)),
        ("62_F17老庄反抽(zt_cnt_pre20>=4)", df["zt_cnt_pre20"] >= 4),
        ("63_pos20<=0.30(20日箱体低位)", df["pos20"] <= 0.30),
        ("64_pos20<=0.45(20日箱体中下)", df["pos20"] <= 0.45),
        ("65_pos20>0.75(20日箱体顶)", df["pos20"] > 0.75),
        ("66_clean_brk60(60日干净突破第2通道)", df["clean_brk60"] == True),
        ("67_无突破高位(~clean_brk60&dd20>0.92)", (~df["clean_brk60"]) & (df["dd20"] > 0.92)),

        # 10. 二板微观盘口质量
        ("68_封板紧密度>=37", df["seal_tightness"] >= 37.0),
        ("69_封板紧密度>=45", df["seal_tightness"] >= 45.0),
        ("70_早盘换手回封(is_hard_open_1030)", df["is_hard_open_1030"] == True),
        ("70b_早盘高紧度换手回封(hard1030&tight>=38)", (df["is_hard_open_1030"] == True) & (df["seal_tightness"] >= 38.0)),
        ("71_F33封成比>=0.08(seal_amt/prev_amt)", sr >= 0.08),
        ("72_温和换手放量比(to_ratio_0.7~1.5)", df["to_ratio_d2_d1"].between(0.7, 1.5)),
        ("73_爆量分歧换手比(to_ratio>2.2)", df["to_ratio_d2_d1"] > 2.2),
    ]
    return specs


def main():
    t0 = time.time()
    print("[B2] Loading cand_2to3_enriched.parquet + rd_trajectories_5m.pkl + code_bars_5y.pkl ...")
    df_en = pd.read_parquet(f"{P2_DIR}/cand_2to3_enriched.parquet")
    with open(f"{P2_DIR}/rd_trajectories_5m.pkl", "rb") as f:
        traj_pkl = pickle.load(f)
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f:
        cb_map = pickle.load(f)["code_bars"]

    needed_codes = set(df_en["code"].astype(str).str.zfill(6))
    bars_5m = load_all_local_5m(needed_codes)
    print(f"[B2] Loaded {len(bars_5m):,} 5m (code, date) pairs in {time.time()-t0:.1f}s")

    # 1. 构造 Mode A (dyn65_12_1130 + pm1345_5m + reb2) 与挂载 Mode B (open_reb2)
    t1 = time.time()
    traj_a = sim_mode_a_dyn65_12(df_en, cb_map, bars_5m)
    traj_b = traj_pkl["open_reb2"]
    print(f"[B2] Mode A simulation complete in {time.time()-t1:.1f}s")

    df_en["ret_mode_a"] = [x["net_ret"] if x else np.nan for x in traj_a]
    df_en["exit_mode_a"] = [x["exit_date"] if x else "" for x in traj_a]
    df_en["ret_mode_b"] = [x["net_ret"] if x else np.nan for x in traj_b]
    df_en["exit_mode_b"] = [x["exit_date"] if x else "" for x in traj_b]

    # 2. 构造跨板/同题材排位/一字阶梯/筹码比例特征 (在全量 6542 可买二板 + cand_2to3 + cand_high_dragon 上算完再过滤到可交易池)
    df_feat = build_cross_board_features(df_en)

    # 3. 过滤到 10cm 主板非 ST 非一字二板可买池
    base_mask = (df_feat["prev_streak"] == 2) & (~df_feat["prev_is_yizi"]) & (df_feat["buyable_open"])
    pool = df_feat[base_mask].copy().reset_index(drop=True)
    print(f"[B2] Base pool (prev_streak==2 & ~prev_is_yizi & buyable_open): {len(pool)} rows")

    pool_a = pool[pool["ret_mode_a"].notna()].copy()
    pool_b = pool[pool["ret_mode_b"].notna()].copy()
    skel_mask = pool["2b_plate_buy_rk"] == 1
    skel_a = pool[skel_mask & pool["ret_mode_a"].notna()].copy()
    skel_b = pool[skel_mask & pool["ret_mode_b"].notna()].copy()

    base_a_mean = float(pool_a["ret_mode_a"].mean())
    base_b_mean = float(pool_b["ret_mode_b"].mean())
    skel_a_mean = float(skel_a["ret_mode_a"].mean())
    skel_b_mean = float(skel_b["ret_mode_b"].mean())

    base_evals = {
        "ModeA_Full": eval_factor_slice(pool_a, ret_col="ret_mode_a", exit_col="exit_mode_a", rank_col="open_pct", base_mean=base_a_mean),
        "ModeB_Full": eval_factor_slice(pool_b, ret_col="ret_mode_b", exit_col="exit_mode_b", rank_col="open_pct", base_mean=base_b_mean),
        "ModeA_Skel_Rk1": eval_factor_slice(skel_a, ret_col="ret_mode_a", exit_col="exit_mode_a", rank_col="open_pct", base_mean=skel_a_mean),
        "ModeB_Skel_Rk1": eval_factor_slice(skel_b, ret_col="ret_mode_b", exit_col="exit_mode_b", rank_col="open_pct", base_mean=skel_b_mean),
    }

    # 4. 逐个挨个评测全部因子
    specs = define_factor_specs(pool)
    rows_out = []
    for fname, cond in specs:
        cond_s = pd.Series(cond, index=pool.index).fillna(False).astype(bool)

        ev_a = eval_factor_slice(pool[cond_s & pool["ret_mode_a"].notna()], "ret_mode_a", "exit_mode_a", "open_pct", base_a_mean)
        ev_b = eval_factor_slice(pool[cond_s & pool["ret_mode_b"].notna()], "ret_mode_b", "exit_mode_b", "open_pct", base_b_mean)
        ev_sa = eval_factor_slice(pool[skel_mask & cond_s & pool["ret_mode_a"].notna()], "ret_mode_a", "exit_mode_a", "open_pct", skel_a_mean)
        ev_sb = eval_factor_slice(pool[skel_mask & cond_s & pool["ret_mode_b"].notna()], "ret_mode_b", "exit_mode_b", "open_pct", skel_b_mean)

        rec = {
            "factor": fname,
            "pool_hit_n": int(cond_s.sum()),
            "pool_hit_pct": round(float(cond_s.mean() * 100), 2),
        }
        for prefix, ev in [("A_full", ev_a), ("B_full", ev_b), ("A_rk1", ev_sa), ("B_rk1", ev_sb)]:
            for k, v in ev.items():
                rec[f"{prefix}_{k}"] = v
        rows_out.append(rec)

    res_df = pd.DataFrame(rows_out)
    res_df.to_csv(OUT_SCRIPT_CSV, index=False, encoding="utf-8-sig")

    # 5. 生成精炼总结 JSON
    def _top_records(col_delta: str, col_dual: str, col_n: str, ascending: bool = False, min_n: int = 20, top_k: int = 12):
        sub = res_df[res_df[col_n] >= min_n].sort_values(col_delta, ascending=ascending).head(top_k)
        out_l = []
        for r in sub.itertuples(index=False):
            d = r._asdict() if hasattr(r, "_asdict") else {}
            # Build clean dict directly from res_df row
        for _, row in sub.iterrows():
            pfx = col_delta.split("_")[0] + "_" + col_delta.split("_")[1]
            out_l.append({
                "factor": row["factor"],
                "n_raw": int(row[f"{pfx}_n_raw"]),
                "wr_raw": float(row[f"{pfx}_wr_raw"]),
                "payoff_raw": float(row[f"{pfx}_payoff_raw"]),
                "avg_ret": float(row[f"{pfx}_avg_ret"]),
                "delta_vs_base": float(row[f"{pfx}_delta_vs_base"]),
                "early_22_23_avg": float(row[f"{pfx}_early_22_23_avg"]),
                "recent_24_26_avg": float(row[f"{pfx}_recent_24_26_avg"]),
                "dual_same_sign": bool(row[f"{pfx}_dual_same_sign"]),
                "ss_n": int(row[f"{pfx}_ss_n"]),
                "ss_nav": float(row[f"{pfx}_ss_nav"]),
                "ss_mdd": float(row[f"{pfx}_ss_mdd"]),
                "eq_nav": float(row[f"{pfx}_eq_nav"]),
            })
        return out_l

    summary = {
        "meta": {
            "pool_total_n": int(len(pool)),
            "csi300_bench_pct": {k: round(v * 100, 2) for k, v in CSI_BENCH.items()},
            "mode_a_desc": "dyn65_12_1130 max(open*1.012, pre_c*1.065) + pm1345_5m + reb2",
            "mode_b_desc": "open (09:25) + pm1345_5m + reb2",
            "skeleton_desc": "2b_plate_buy_rk == 1 (板内可买二板竞价第1名, 含独苗/多板榜首; 其他不互组)",
            "total_slices_tested": int(len(res_df)),
        },
        "baselines": base_evals,
        "top_positive_A_full": _top_records("A_full_delta_vs_base", "A_full_dual_same_sign", "A_full_n_raw", ascending=False),
        "top_negative_A_full": _top_records("A_full_delta_vs_base", "A_full_dual_same_sign", "A_full_n_raw", ascending=True),
        "top_positive_B_full": _top_records("B_full_delta_vs_base", "B_full_dual_same_sign", "B_full_n_raw", ascending=False),
        "top_negative_B_full": _top_records("B_full_delta_vs_base", "B_full_dual_same_sign", "B_full_n_raw", ascending=True),
        "top_positive_A_rk1_skel": _top_records("A_rk1_delta_vs_base", "A_rk1_dual_same_sign", "A_rk1_n_raw", ascending=False),
        "top_positive_B_rk1_skel": _top_records("B_rk1_delta_vs_base", "B_rk1_dual_same_sign", "B_rk1_n_raw", ascending=False),
        "dual_consistent_positive_A_full": [
            r["factor"] for _, r in res_df[(res_df["A_full_dual_same_sign"]) & (res_df["A_full_delta_vs_base"] > 0)].sort_values("A_full_delta_vs_base", ascending=False).iterrows()
        ],
        "dual_consistent_positive_B_full": [
            r["factor"] for _, r in res_df[(res_df["B_full_dual_same_sign"]) & (res_df["B_full_delta_vs_base"] > 0)].sort_values("B_full_delta_vs_base", ascending=False).iterrows()
        ],
        "dual_consistent_negative_A_full": [
            r["factor"] for _, r in res_df[(res_df["A_full_dual_same_sign"]) & (res_df["A_full_delta_vs_base"] < 0)].sort_values("A_full_delta_vs_base", ascending=True).iterrows()
        ],
        "dual_consistent_negative_B_full": [
            r["factor"] for _, r in res_df[(res_df["B_full_dual_same_sign"]) & (res_df["B_full_delta_vs_base"] < 0)].sort_values("B_full_delta_vs_base", ascending=True).iterrows()
        ],
    }

    with open(OUT_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n=== [Baselines] ===")
    for k, v in base_evals.items():
        print(f"  {k:15s}: n={v['n_raw']:4d} WR={v['wr_raw']:5.2f}% PO={v['payoff_raw']:4.2f} avg={v['avg_ret']:+5.2f}% (22-23:{v['early_22_23_avg']:+5.2f}% 24-26:{v['recent_24_26_avg']:+5.2f}%) ss_n={v['ss_n']} ss_nav={v['ss_nav']}x eq_nav={v['eq_nav']}x")

    print("\n=== [Top 12 Positive Factors - Mode A (dyn65_12)] ===")
    for x in summary["top_positive_A_full"]:
        print(f"  {x['factor']:44s} | n={x['n_raw']:4d} WR={x['wr_raw']:5.1f}% avg={x['avg_ret']:+5.2f}% d={x['delta_vs_base']:+5.2f}% dual={str(x['dual_same_sign']):5s} ({x['early_22_23_avg']:+5.2f}%/{x['recent_24_26_avg']:+5.2f}%) ss={x['ss_nav']:.2f}x")

    print("\n=== [Top 12 Positive Factors - Mode B (09:25 Open)] ===")
    for x in summary["top_positive_B_full"]:
        print(f"  {x['factor']:44s} | n={x['n_raw']:4d} WR={x['wr_raw']:5.1f}% avg={x['avg_ret']:+5.2f}% d={x['delta_vs_base']:+5.2f}% dual={str(x['dual_same_sign']):5s} ({x['early_22_23_avg']:+5.2f}%/{x['recent_24_26_avg']:+5.2f}%) ss={x['ss_nav']:.2f}x")

    print("\n=== [Top 10 Negative/Veto Factors - Mode B (09:25 Open)] ===")
    for x in summary["top_negative_B_full"][:10]:
        print(f"  {x['factor']:44s} | n={x['n_raw']:4d} WR={x['wr_raw']:5.1f}% avg={x['avg_ret']:+5.2f}% d={x['delta_vs_base']:+5.2f}% dual={str(x['dual_same_sign']):5s} ({x['early_22_23_avg']:+5.2f}%/{x['recent_24_26_avg']:+5.2f}%) ss={x['ss_nav']:.2f}x")

    print(f"\n[+] Saved CSV: {OUT_SCRIPT_CSV}")
    print(f"[+] Saved JSON: {OUT_SUMMARY_JSON}")
    print(f"[DONE] Elapsed {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
