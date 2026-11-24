#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD022 Part 1 - Step 2: 145+ High-Granularity PIT Factor Scan & Fine 6-8 Quantile Bucketing on Beta Days."""

import bisect
import datetime
import json
import os
import re
import sqlite3
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part1_beta_waves"

MKT_PQ = f"{OUT_DIR}/market_daily.parquet"
P20_PQ = f"{OUT_DIR}/panel_20cm.parquet"
KPL_JSONL = f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl"
LHB_PQ = f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117/clean_lhb_5y.parquet"
BAYES_PQ = f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117/bayes_seat_scores_d1_5y.parquet"
TOX_PQ = f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet"
NOTICES_DB = f"{SIM}/data/cninfo_notices_5y_pit.db"
IR_DB = f"{SIM}/data/cninfo_ir_qa_5y_pit.db"
ZT_DB = f"{SIM}/data/zt_micro_tape_5y_pit.db"
XQ_DB = f"{SIM}/data/xueqiu_guba_5y_pit.db"
CSRC_PIT = f"{SIM}/data/csrc_industry_pit_clean.csv"

IS_END = "2024-08-31"
OOS_START = "2024-09-01"

NON_THEME = {
    "其他", "公告", "ST板块", "科创板", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股", "新股与次新股", "北交所",
    "预盈预增", "回购", "增持", "高送转", "摘帽",
}
EVENT_BASKET_PLATES = {
    "并购重组", "股权转让", "资产注入", "国企改革", "央企改革",
    "地方国资改革", "业绩增长", "预盈预增", "摘帽", "回购",
    "增持", "次新股", "高送转", "参股新股",
}
BROAD_INDUSTRY_PLATES = {
    "通信", "汽车零部件", "医药", "医疗器械", "化工", "机械",
    "房地产", "建筑", "环保", "电力", "纺织", "传媒", "家电",
    "食品", "农业", "交通运输", "有色", "煤炭", "钢铁",
}
HARD_TECH_RE = re.compile(
    r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|CPO|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶|人形机器人|光刻|存储)"
)
CSRC_TECH_RE = re.compile(r"(?:计算机|软件|电子|通信|仪器|专用设备|通用设备|电气|医药|互联网)")

IS_GOOD_CODES = {
    "10430845", "10102873", "10046704", "10023415", "10026767", "10142874",
    "10122927", "10045035", "10025390", "10147201", "10318896",
}
IS_BAD_CODES = {
    "10063083", "10000147202", "10050414", "10115140", "10023543", "10046458",
    "10046604", "10485003", "10028577", "10547746", "10456237", "10027014",
    "10143030", "10477736", "10023559", "10026729",
}


def compute_rolling_20cm_features(p20: pd.DataFrame) -> pd.DataFrame:
    """Compute all strict PIT price/volume/position features per stock on the full 20cm panel."""
    p20 = p20.sort_values(["c6", "dt"]).reset_index(drop=True)
    g = p20.groupby("c6", sort=False)

    # Pre-T0 averages & stds (shifted by 1 so strictly <= T-1)
    p20["ma5_pre"] = g["adj_close"].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    p20["ma10_pre"] = g["adj_close"].transform(lambda s: s.shift(1).rolling(10, min_periods=5).mean())
    p20["ma20_pre"] = g["adj_close"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    p20["ma60_pre"] = g["adj_close"].transform(lambda s: s.shift(1).rolling(60, min_periods=20).mean())
    p20["ma20_t0"] = g["adj_close"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    p20["ma20_pre5"] = g["ma20_pre"].shift(5)

    p20["high20_pre"] = g["adj_high"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).max())
    p20["low20_pre"] = g["adj_low"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).min())
    p20["high60_pre"] = g["adj_high"].transform(lambda s: s.shift(1).rolling(60, min_periods=15).max())
    p20["low60_pre"] = g["adj_low"].transform(lambda s: s.shift(1).rolling(60, min_periods=15).min())
    p20["high120_pre"] = g["adj_high"].transform(lambda s: s.shift(1).rolling(120, min_periods=30).max())
    p20["low120_pre"] = g["adj_low"].transform(lambda s: s.shift(1).rolling(120, min_periods=30).min())

    p20["high20_incl"] = g["adj_high"].transform(lambda s: s.rolling(20, min_periods=5).max())
    p20["low20_incl"] = g["adj_low"].transform(lambda s: s.rolling(20, min_periods=5).min())

    p20["amt_ma5_pre"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    p20["amt_ma20_pre"] = g["amount"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    p20["turn_ma5_pre"] = g["turn"].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    p20["turn_ma20_pre"] = g["turn"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    p20["prev_vol"] = g["volume"].shift(1)

    p20["std5_pre"] = g["ret"].transform(lambda s: s.shift(1).rolling(5, min_periods=4).std())
    p20["std20_pre"] = g["ret"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).std())
    p20["amihud_day"] = p20["ret"].abs() / np.maximum(p20["amount"] / 1e8, 0.01)
    p20["amihud_20d_pre"] = g["amihud_day"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())

    p20["prev_ret1"] = g["ret"].shift(1)
    p20["prev_ret3"] = p20["prev_adj_c"] / g["adj_close"].shift(4) - 1.0
    p20["prev_ret5"] = p20["prev_adj_c"] / g["adj_close"].shift(6) - 1.0
    p20["prev_ret10"] = p20["prev_adj_c"] / g["adj_close"].shift(11) - 1.0
    p20["prev_ret20"] = p20["prev_adj_c"] / g["adj_close"].shift(21) - 1.0
    p20["prev_ret60"] = p20["prev_adj_c"] / g["adj_close"].shift(61) - 1.0

    up_pos = (p20["ret"] > 0).astype(float)
    p20["up_days_5d_pre"] = up_pos.groupby(p20["c6"], sort=False).transform(lambda s: s.shift(1).rolling(5, min_periods=1).sum())
    # Consecutive up days ending T-1
    streak_up = up_pos.groupby([p20["c6"], (up_pos != g["ret"].shift(1).gt(0).astype(float)).cumsum()]).cumsum() * up_pos
    p20["consec_up_pre"] = streak_up.groupby(p20["c6"], sort=False).shift(1).fillna(0)

    big7_flag = ((p20["ret"] >= 0.07) & p20["is_clean_universe"]).astype(float)
    p20["big7_cnt_20d_pre"] = big7_flag.groupby(p20["c6"], sort=False).transform(lambda s: s.shift(1).rolling(20, min_periods=1).sum())
    p20["big7_cnt_60d_pre"] = big7_flag.groupby(p20["c6"], sort=False).transform(lambda s: s.shift(1).rolling(60, min_periods=1).sum())
    zt_flag = (p20["is_zt"] & p20["is_clean_universe"]).astype(float)
    p20["zt_cnt_20d_pre"] = zt_flag.groupby(p20["c6"], sort=False).transform(lambda s: s.shift(1).rolling(20, min_periods=1).sum())
    p20["zt_cnt_60d_pre"] = zt_flag.groupby(p20["c6"], sort=False).transform(lambda s: s.shift(1).rolling(60, min_periods=1).sum())

    # T0 intraday / microstructure
    p20["open_gap"] = p20["adj_open"] / p20["prev_adj_c"] - 1.0
    p20["intraday_ret"] = p20["adj_close"] / p20["adj_open"] - 1.0
    hl_rng = np.maximum(p20["high"] - p20["low"], 1e-4)
    p20["clv"] = (p20["close"] - p20["low"]) / hl_rng
    p20["upper_shadow_pct"] = (p20["high"] - np.maximum(p20["open"], p20["close"])) / p20["prev_c_adj"]
    p20["lower_shadow_pct"] = (np.minimum(p20["open"], p20["close"]) - p20["low"]) / p20["prev_c_adj"]
    p20["body_ratio"] = (p20["close"] - p20["open"]) / hl_rng
    p20["amplitude"] = (p20["high"] - p20["low"]) / p20["prev_c_adj"]
    p20["gap_vs_intraday_diff"] = p20["intraday_ret"] - p20["open_gap"]
    p20["is_true_yang"] = ((p20["close"] > p20["open"]) & (p20["ret"] >= 0.05)).astype(float)
    p20["close_near_high"] = p20["close"] / np.maximum(p20["high"], 1e-4)

    p20["turn_pct"] = p20["turn"] * 100.0
    p20["amt_yi"] = p20["amount"] / 1e8
    p20["log_amt"] = np.log1p(np.maximum(p20["amt_yi"], 0.0))
    p20["amt_ratio_5"] = p20["amount"] / np.maximum(p20["amt_ma5_pre"], 1e4)
    p20["amt_ratio_20"] = p20["amount"] / np.maximum(p20["amt_ma20_pre"], 1e4)
    p20["turn_ratio_5"] = p20["turn"] / np.maximum(p20["turn_ma5_pre"], 1e-5)
    p20["turn_ratio_20"] = p20["turn"] / np.maximum(p20["turn_ma20_pre"], 1e-5)
    p20["vol_exp_1d"] = p20["volume"] / np.maximum(p20["prev_vol"], 1.0)
    p20["vol_contraction_5_20"] = p20["std5_pre"] / np.maximum(p20["std20_pre"], 1e-5)

    p20["pos20_pre"] = (p20["prev_adj_c"] - p20["low20_pre"]) / np.maximum(p20["high20_pre"] - p20["low20_pre"], 1e-4)
    p20["pos20_incl"] = (p20["adj_close"] - p20["low20_incl"]) / np.maximum(p20["high20_incl"] - p20["low20_incl"], 1e-4)
    p20["pos60_pre"] = (p20["prev_adj_c"] - p20["low60_pre"]) / np.maximum(p20["high60_pre"] - p20["low60_pre"], 1e-4)
    p20["pos120_pre"] = (p20["prev_adj_c"] - p20["low120_pre"]) / np.maximum(p20["high120_pre"] - p20["low120_pre"], 1e-4)
    p20["dist_ma5_pre"] = p20["prev_adj_c"] / p20["ma5_pre"] - 1.0
    p20["dist_ma10_pre"] = p20["prev_adj_c"] / p20["ma10_pre"] - 1.0
    p20["dist_ma20_pre"] = p20["prev_adj_c"] / p20["ma20_pre"] - 1.0
    p20["dist_ma60_pre"] = p20["prev_adj_c"] / p20["ma60_pre"] - 1.0
    p20["dist_ma20_t0"] = p20["adj_close"] / p20["ma20_t0"] - 1.0
    p20["above_ma20_pre"] = (p20["prev_adj_c"] > p20["ma20_pre"]).astype(float)
    p20["above_ma60_pre"] = (p20["prev_adj_c"] > p20["ma60_pre"]).astype(float)
    p20["ma20_slope_5d"] = p20["ma20_pre"] / p20["ma20_pre5"] - 1.0
    p20["cross_above_ma20_t0"] = ((p20["prev_adj_c"] <= p20["ma20_pre"]) & (p20["adj_close"] > p20["ma20_t0"])).astype(float)
    p20["dd_20h_pre"] = p20["prev_adj_c"] / p20["high20_pre"] - 1.0
    p20["dd_60h_pre"] = p20["prev_adj_c"] / p20["high60_pre"] - 1.0
    p20["min_severe_headroom"] = np.minimum(p20["head_3d30"], np.minimum(p20["head_10d100"], p20["head_30d200"]))
    p20["is_first_bigup_20d"] = (p20["big7_cnt_20d_pre"] == 0).astype(float)
    p20["is_first_bigup_60d"] = (p20["big7_cnt_60d_pre"] == 0).astype(float)
    p20["is_old_dragon_rebound"] = ((p20["zt_cnt_60d_pre"] >= 2) & (p20["dd_60h_pre"] < -0.20)).astype(float)

    p20["log_mcap"] = np.log1p(np.maximum(p20["circ_mcap"], 0.0))
    p20["is_small_lt50"] = (p20["circ_mcap"] < 50.0).astype(float)
    p20["is_mid_50_150"] = ((p20["circ_mcap"] >= 50.0) & (p20["circ_mcap"] < 150.0)).astype(float)
    p20["is_big_army_ge150"] = (p20["circ_mcap"] >= 150.0).astype(float)
    p20["is_chinext"] = (~p20["is_star"]).astype(float)
    p20["is_301"] = p20["c6"].str.startswith("301").astype(float)
    p20["is_star_f"] = p20["is_star"].astype(float)
    p20["mcap_x_turn"] = p20["circ_mcap"] * p20["turn_pct"]
    p20["amt_over_mcap_pct"] = p20["amt_yi"] / np.maximum(p20["circ_mcap"], 0.1) * 100.0
    p20["list_age_capped"] = np.where(p20["first_dt"] >= "2020-08-01", p20["list_day_idx"], 1500.0)
    return p20


def build_auxiliary_enrichments(cand: pd.DataFrame, mkt: pd.DataFrame, p20: pd.DataFrame) -> pd.DataFrame:
    """Enrich beta-day candidates with strict PIT KPL, LHB, Notices, IR QA, Tox, Micro-Tape, and Community features."""
    beta_dts = sorted(cand["dt"].unique().tolist())
    beta_set = set(beta_dts)
    all_dts = mkt["dt"].tolist()
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}

    # 1. CSRC industry
    csrc_df = pd.read_csv(CSRC_PIT, dtype=str)
    csrc_map = dict(zip(csrc_df["sec_code"].str[:6], csrc_df["industry"].fillna("")))
    cand["csrc_hard_tech"] = [1.0 if CSRC_TECH_RE.search(csrc_map.get(c, "")) else 0.0 for c in cand["c6"]]

    # 2. KPL membership & live cross-board resonance
    # Build per-date stock return >= 5% & ZT sets from p20 + zt_micro_tape for beta_dts and T-1..T-5
    needed_dts = set()
    for d in beta_dts:
        i = dt_to_idx[d]
        for k in range(0, 6):
            if i - k >= 0:
                needed_dts.add(all_dts[i - k])

    # Load 10cm + 20cm ZT from zt_micro_tape for needed_dts
    conn_zt = sqlite3.connect(f"file:{ZT_DB}?mode=ro", uri=True)
    zt_df = pd.read_sql_query(
        "SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count, board_count FROM zt_micro_tape WHERE trade_date >= '2021-01-01'",
        conn_zt,
    )
    conn_zt.close()
    zt10_by_dt = defaultdict(set)
    zt20_tape = {}
    for r in zt_df.itertuples(index=False):
        c6 = str(r.sec_code)[:6]
        dt = r.trade_date
        if c6.startswith(("30", "688", "689")):
            # Parse HH:MM:SS -> minutes since 09:30
            st = str(r.first_seal_time or "")
            mins = 999.0
            if len(st) >= 5 and ":" in st:
                try:
                    hh, mm = int(st[:2]), int(st[3:5])
                    mins = (hh - 9) * 60 + (mm - 30) - (90 if hh >= 13 else 0)
                except Exception:
                    pass
            sa = float(r.seal_amount) / 1e8 if pd.notna(r.seal_amount) else 0.0
            obc = int(r.open_board_count) if pd.notna(r.open_board_count) else 0
            zt20_tape[(dt, c6)] = (mins, sa, obc)
        else:
            if dt in needed_dts:
                zt10_by_dt[dt].add(c6)

    # 20cm big-up >= 5% on beta days from p20
    big5_20_by_dt = defaultdict(set)
    p20_b = p20[p20["dt"].isin(beta_set) & p20["is_clean_universe"] & (p20["ret"] >= 0.05)]
    for dt, c6 in zip(p20_b["dt"], p20_b["c6"]):
        big5_20_by_dt[dt].add(c6)
    p20_zt = p20[p20["dt"].isin(beta_set) & p20["is_zt"]]
    zt20_by_dt = defaultdict(set)
    for dt, c6 in zip(p20_zt["dt"], p20_zt["c6"]):
        zt20_by_dt[dt].add(c6)

    # Parse KPL jsonl
    kpl_raw = {}
    with open(KPL_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            dt = obj.get("date", "")
            if dt in needed_dts:
                kpl_raw[dt] = obj.get("plates", [])

    # Pre-index T0 KPL and rolling T-5..T-1 KPL stock->plates
    kpl_t0_info = {}  # (dt, c6) -> dict
    kpl_max_plate_zt = {}  # dt -> max single plate 10cm+20cm ZT count
    kpl_yest_info = {}  # (dt, c6) -> dict
    kpl_hist5_plates = defaultdict(set)  # (dt, c6) -> set of plates seen T-5..T-1
    kpl_plate_members_hist5 = defaultdict(set)  # (dt, pname) -> set of member codes in T-5..T-1

    # Also compute live theme counts for T0 using T-5..T-1 plate members!
    for dt in sorted(kpl_raw.keys()):
        plates = kpl_raw[dt]
        z10 = zt10_by_dt.get(dt, set())
        z20 = zt20_by_dt.get(dt, set())
        max_zt_p = 0
        # Rank real plates
        rk = 0
        for pl in plates:
            pname = pl.get("plate", "")
            if not pname or pname in NON_THEME:
                continue
            rk += 1
            members = [str(s[0]).strip()[:6].zfill(6) for s in pl.get("stocks", [])]
            mset = set(members)
            n10 = len(mset & z10)
            n20 = len(mset & z20)
            max_zt_p = max(max_zt_p, n10 + n20)
            is_ht = 1.0 if HARD_TECH_RE.search(pname) else 0.0
            is_ev = 1.0 if pname in EVENT_BASKET_PLATES else 0.0
            is_bi = 1.0 if pname in BROAD_INDUSTRY_PLATES else 0.0
            if dt in beta_set:
                for c6 in mset:
                    cur = kpl_t0_info.get((dt, c6))
                    if cur is None:
                        kpl_t0_info[(dt, c6)] = {
                            "rk": rk, "sz": len(mset), "n10": n10, "n20": n20,
                            "ht": is_ht, "ev": is_ev, "bi": is_bi, "cnt": 1
                        }
                    else:
                        cur["cnt"] += 1
                        cur["ht"] = max(cur["ht"], is_ht)
        if dt in beta_set:
            kpl_max_plate_zt[dt] = max_zt_p

    # Build T-1 and T-5..T-1 KPL membership for each beta_dt (strictly legal for Route A!)
    for dt in beta_dts:
        i = dt_to_idx[dt]
        # Yesterday's KPL (T-1)
        if i - 1 >= 0:
            ydt = all_dts[i - 1]
            rk = 0
            for pl in kpl_raw.get(ydt, []):
                pname = pl.get("plate", "")
                if not pname or pname in NON_THEME:
                    continue
                rk += 1
                members = [str(s[0]).strip()[:6].zfill(6) for s in pl.get("stocks", [])]
                is_ht = 1.0 if HARD_TECH_RE.search(pname) else 0.0
                is_ev = 1.0 if pname in EVENT_BASKET_PLATES else 0.0
                is_bi = 1.0 if pname in BROAD_INDUSTRY_PLATES else 0.0
                for c6 in set(members):
                    cur = kpl_yest_info.get((dt, c6))
                    if cur is None:
                        kpl_yest_info[(dt, c6)] = {"rk": rk, "ht": is_ht, "ev": is_ev, "bi": is_bi, "cnt": 1}
                    else:
                        cur["cnt"] += 1
                        cur["ht"] = max(cur["ht"], is_ht)
        # T-5..T-1 plate members for live T0 cross-board resonance
        for k in range(1, 6):
            if i - k >= 0:
                hdt = all_dts[i - k]
                for pl in kpl_raw.get(hdt, []):
                    pname = pl.get("plate", "")
                    if not pname or pname in NON_THEME:
                        continue
                    for s in pl.get("stocks", []):
                        c6 = str(s[0]).strip()[:6].zfill(6)
                        kpl_hist5_plates[(dt, c6)].add(pname)
                        kpl_plate_members_hist5[(dt, pname)].add(c6)

    # Map KPL features onto cand
    n = len(cand)
    in_kpl_yest = np.zeros(n)
    kpl_yest_top3 = np.zeros(n)
    kpl_yest_top1 = np.zeros(n)
    kpl_yest_rk = np.full(n, 99.0)
    kpl_yest_cnt = np.zeros(n)
    kpl_ht_yest = np.zeros(n)
    kpl_ev_yest = np.zeros(n)
    kpl_bi_yest = np.zeros(n)
    kpl_live_20_cnt = np.zeros(n)
    kpl_live_10_zt_cnt = np.zeros(n)

    in_kpl_t0 = np.zeros(n)
    kpl_t0_top3 = np.zeros(n)
    kpl_t0_top1 = np.zeros(n)
    kpl_t0_rk = np.full(n, 99.0)
    kpl_t0_sz = np.zeros(n)
    kpl_t0_n10 = np.zeros(n)
    kpl_t0_n20 = np.zeros(n)
    kpl_t0_ht = np.zeros(n)
    kpl_t0_ev = np.zeros(n)
    kpl_t0_bi = np.zeros(n)
    kpl_t0_max_pzt = np.zeros(n)

    for idx, (dt, c6) in enumerate(zip(cand["dt"], cand["c6"])):
        yi = kpl_yest_info.get((dt, c6))
        if yi:
            in_kpl_yest[idx] = 1.0
            kpl_yest_rk[idx] = yi["rk"]
            kpl_yest_top3[idx] = 1.0 if yi["rk"] <= 3 else 0.0
            kpl_yest_top1[idx] = 1.0 if yi["rk"] == 1 else 0.0
            kpl_yest_cnt[idx] = yi["cnt"]
            kpl_ht_yest[idx] = yi["ht"]
            kpl_ev_yest[idx] = yi["ev"]
            kpl_bi_yest[idx] = yi["bi"]

        pls = kpl_hist5_plates.get((dt, c6))
        if pls:
            b20 = big5_20_by_dt.get(dt, set())
            z10 = zt10_by_dt.get(dt, set())
            best20 = best10 = 0
            for pname in pls:
                mems = kpl_plate_members_hist5[(dt, pname)]
                c20 = len((mems & b20) - {c6})
                c10 = len(mems & z10)
                if c20 > best20: best20 = c20
                if c10 > best10: best10 = c10
            kpl_live_20_cnt[idx] = best20
            kpl_live_10_zt_cnt[idx] = best10

        ti = kpl_t0_info.get((dt, c6))
        if ti:
            in_kpl_t0[idx] = 1.0
            kpl_t0_rk[idx] = ti["rk"]
            kpl_t0_top3[idx] = 1.0 if ti["rk"] <= 3 else 0.0
            kpl_t0_top1[idx] = 1.0 if ti["rk"] == 1 else 0.0
            kpl_t0_sz[idx] = ti["sz"]
            kpl_t0_n10[idx] = ti["n10"]
            kpl_t0_n20[idx] = ti["n20"]
            kpl_t0_ht[idx] = ti["ht"]
            kpl_t0_ev[idx] = ti["ev"]
            kpl_t0_bi[idx] = ti["bi"]
        kpl_t0_max_pzt[idx] = kpl_max_plate_zt.get(dt, 0)

    cand["in_kpl_yest"] = in_kpl_yest
    cand["kpl_yest_top3"] = kpl_yest_top3
    cand["kpl_yest_top1"] = kpl_yest_top1
    cand["kpl_yest_rk"] = kpl_yest_rk
    cand["kpl_yest_cnt"] = kpl_yest_cnt
    cand["kpl_ht_yest"] = kpl_ht_yest
    cand["kpl_ev_yest"] = kpl_ev_yest
    cand["kpl_bi_yest"] = kpl_bi_yest
    cand["kpl_live_20_cnt"] = kpl_live_20_cnt
    cand["kpl_live_10_zt_cnt"] = kpl_live_10_zt_cnt
    cand["kpl_live_20_to_10_ratio"] = kpl_live_20_cnt / (kpl_live_10_zt_cnt + 1.0)
    cand["kpl_live_climax_gt35"] = (kpl_live_10_zt_cnt > 35).astype(float)
    cand["in_kpl_t0"] = in_kpl_t0
    cand["kpl_t0_top3"] = kpl_t0_top3
    cand["kpl_t0_top1"] = kpl_t0_top1
    cand["kpl_t0_rk"] = kpl_t0_rk
    cand["kpl_t0_sz"] = kpl_t0_sz
    cand["kpl_t0_n10"] = kpl_t0_n10
    cand["kpl_t0_n20"] = kpl_t0_n20
    cand["kpl_t0_ht"] = kpl_t0_ht
    cand["kpl_t0_ev"] = kpl_t0_ev
    cand["kpl_t0_bi"] = kpl_t0_bi
    cand["kpl_t0_max_pzt_gt35"] = (kpl_t0_max_pzt > 35).astype(float)

    # 3. LHB & Bayes Seat Scores (Route A: strictly T-10..T-1; Route B: T0 post-close)
    print("  Loading LHB & Bayes seat scores...")
    lhb = pd.read_parquet(LHB_PQ)
    lhb20 = lhb[lhb["stock_code"].astype(str).str.startswith(("30", "688", "689"))].copy()
    lhb20["is_org"] = lhb20["dept_name"].str.contains("机构专用", na=False) | (lhb20["dept_code"] == "0")
    lhb20["is_lhasa"] = lhb20["dept_name"].str.contains("拉萨", na=False) & (~lhb20["dept_name"].str.contains("东亚", na=False))
    lhb20["is_north"] = lhb20["dept_name"].str.contains("深股通|沪股通", na=False)
    lhb20["is_good"] = lhb20["dept_code"].isin(IS_GOOD_CODES)
    lhb20["is_bad"] = lhb20["dept_code"].isin(IS_BAD_CODES)

    bayes = pd.read_parquet(BAYES_PQ)
    bayes20 = bayes[bayes["stock_code"].astype(str).str.startswith(("30", "688", "689"))].copy()
    b_map = {}
    for (dt, sc), grp in bayes20.groupby(["date", "stock_code"], sort=False):
        w = np.maximum(grp["NET"].to_numpy(dtype=float), 1.0)
        b_map[(dt, sc)] = (
            float(np.sum(w * grp["b_c"].to_numpy()) / np.sum(w)),
            float(np.sum(w * grp["b_t2"].to_numpy()) / np.sum(w)),
        )

    lhb_d1_map = {}
    lhb_3d_set = set()
    lhb_by_c6 = defaultdict(list)  # c6 -> list of (date, org_net, has_lhasa, bc, bt2)
    for (dt, sc, is3), grp in lhb20.groupby(["date", "stock_code", "is_three"], sort=False):
        if int(is3) == 1:
            lhb_3d_set.add((dt, sc))
            continue
        b = grp[grp["side"] == "B"]
        s = grp[grp["side"] == "S"]
        tot_b = float(b["BUY"].sum())
        tot_s = float(s["SELL"].sum())
        org_net = float(grp[grp["is_org"]]["NET"].sum())
        org_b_cnt = int((b["is_org"]).sum())
        org_b_amt = float(b[b["is_org"]]["BUY"].sum())
        lh_cnt = int(len(set(b[b["is_lhasa"]]["dept_code"])))
        lh_amt = float(b[b["is_lhasa"]]["BUY"].sum())
        north_net = float(grp[grp["is_north"]]["NET"].sum())
        has_good = int((b[b["NET"] > 0]["is_good"]).any())
        has_bad = int((b[b["NET"] > 0]["is_bad"]).any())
        bc, bt2 = b_map.get((dt, sc), (0.0, 0.0))
        lhb_d1_map[(dt, sc)] = (
            tot_b - tot_s, org_net, org_b_cnt, org_b_amt / tot_b if tot_b > 0 else 0.0,
            lh_cnt, lh_amt / tot_b if tot_b > 0 else 0.0, north_net, has_good, has_bad, bc, bt2
        )
        lhb_by_c6[sc].append((dt, org_net, int(lh_cnt > 0), bc, bt2))
    for sc in lhb_by_c6:
        lhb_by_c6[sc].sort(key=lambda x: x[0])

    # Assign LHB features (strictly T-10..T-1 for Route A; T0 for Route B)
    lhb_cnt_10d_pre = np.zeros(n)
    lhb_org_net_10d_pre = np.zeros(n)
    lhb_has_org_10d_pre = np.zeros(n)
    lhb_has_lhasa_10d_pre = np.zeros(n)
    lhb_bayes_10d_pre = np.zeros(n)

    lhb_on_t0 = np.zeros(n)
    lhb_on_t0_3d = np.zeros(n)
    lhb_t0_net_yi = np.zeros(n)
    lhb_t0_org_net_yi = np.zeros(n)
    lhb_t0_org_cnt = np.zeros(n)
    lhb_t0_org_share = np.zeros(n)
    lhb_t0_pure_org = np.zeros(n)
    lhb_t0_lhasa_cnt = np.zeros(n)
    lhb_t0_lhasa_share = np.zeros(n)
    lhb_t0_north_yi = np.zeros(n)
    lhb_t0_good = np.zeros(n)
    lhb_t0_bad = np.zeros(n)
    lhb_t0_bc = np.zeros(n)
    lhb_t0_bt2 = np.zeros(n)

    for idx, (dt, c6) in enumerate(zip(cand["dt"], cand["c6"])):
        # Pre-T0 10 calendar/trading days (< dt)
        arr = lhb_by_c6.get(c6)
        if arr:
            lo = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=14)).isoformat()
            dts_only = [x[0] for x in arr]
            i0 = bisect.bisect_left(dts_only, lo)
            i1 = bisect.bisect_left(dts_only, dt)  # strictly < dt!
            if i1 > i0:
                sl = arr[i0:i1]
                lhb_cnt_10d_pre[idx] = len(sl)
                lhb_org_net_10d_pre[idx] = sum(x[1] for x in sl) / 1e8
                lhb_has_org_10d_pre[idx] = 1.0 if any(x[1] > 0 for x in sl) else 0.0
                lhb_has_lhasa_10d_pre[idx] = 1.0 if any(x[2] > 0 for x in sl) else 0.0
                lhb_bayes_10d_pre[idx] = float(np.mean([x[4] for x in sl]))

        if (dt, c6) in lhb_3d_set:
            lhb_on_t0_3d[idx] = 1.0
        d1 = lhb_d1_map.get((dt, c6))
        if d1:
            lhb_on_t0[idx] = 1.0
            lhb_t0_net_yi[idx] = d1[0] / 1e8
            lhb_t0_org_net_yi[idx] = d1[1] / 1e8
            lhb_t0_org_cnt[idx] = d1[2]
            lhb_t0_org_share[idx] = d1[3]
            lhb_t0_pure_org[idx] = 1.0 if (d1[2] >= 2 and d1[1] > 1e7 and d1[4] == 0) else 0.0
            lhb_t0_lhasa_cnt[idx] = d1[4]
            lhb_t0_lhasa_share[idx] = d1[5]
            lhb_t0_north_yi[idx] = d1[6] / 1e8
            lhb_t0_good[idx] = d1[7]
            lhb_t0_bad[idx] = d1[8]
            lhb_t0_bc[idx] = d1[9]
            lhb_t0_bt2[idx] = d1[10]

    cand["lhb_cnt_10d_pre"] = lhb_cnt_10d_pre
    cand["lhb_org_net_10d_pre"] = lhb_org_net_10d_pre
    cand["lhb_has_org_10d_pre"] = lhb_has_org_10d_pre
    cand["lhb_has_lhasa_10d_pre"] = lhb_has_lhasa_10d_pre
    cand["lhb_bayes_10d_pre"] = lhb_bayes_10d_pre
    cand["lhb_on_t0"] = lhb_on_t0
    cand["lhb_on_t0_3d"] = lhb_on_t0_3d
    cand["lhb_t0_net_yi"] = lhb_t0_net_yi
    cand["lhb_t0_net_over_amt"] = np.where(lhb_on_t0 > 0, lhb_t0_net_yi / np.maximum(cand["amt_yi"], 0.1), 0.0)
    cand["lhb_t0_org_net_yi"] = lhb_t0_org_net_yi
    cand["lhb_t0_org_cnt"] = lhb_t0_org_cnt
    cand["lhb_t0_org_share"] = lhb_t0_org_share
    cand["lhb_t0_pure_org"] = lhb_t0_pure_org
    cand["lhb_t0_lhasa_cnt"] = lhb_t0_lhasa_cnt
    cand["lhb_t0_lhasa_share"] = lhb_t0_lhasa_share
    cand["lhb_t0_north_yi"] = lhb_t0_north_yi
    cand["lhb_t0_good"] = lhb_t0_good
    cand["lhb_t0_bad"] = lhb_t0_bad
    cand["lhb_t0_bc"] = lhb_t0_bc
    cand["lhb_t0_bt2"] = lhb_t0_bt2

    # 4. CNINFO Earnings Pre-Announcement, IR QA, Reg-Tox (exact timestamp cutoffs!)
    print("  Loading Notices, IR QA & Reg-Tox with exact CST timestamp cutoffs...")
    cand_c6_set = set(cand["c6"].unique())
    conn_n = sqlite3.connect(f"file:{NOTICES_DB}?mode=ro", uri=True)
    ep_ts = defaultdict(list)
    en_ts = defaultdict(list)
    for sc, pub_ts, atype in conn_n.execute(
        "SELECT sec_code, pub_datetime_cst, ann_type FROM notices WHERE (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%') AND ann_type LIKE '业绩预告:%'"
    ):
        c6 = str(sc)[:6]
        if c6 not in cand_c6_set or not pub_ts:
            continue
        if any(k in str(atype) for k in ("预增", "略增", "扭亏", "减亏")):
            ep_ts[c6].append(str(pub_ts))
        elif any(k in str(atype) for k in ("预减", "首亏", "增亏", "续亏")):
            en_ts[c6].append(str(pub_ts))
    conn_n.close()
    for dmap in (ep_ts, en_ts):
        for k in dmap:
            dmap[k].sort()

    conn_ir = sqlite3.connect(f"file:{IR_DB}?mode=ro", uri=True)
    ir_ts = defaultdict(list)
    for sc, pub_ts in conn_ir.execute(
        "SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%'"
    ):
        c6 = str(sc)[:6]
        if c6 in cand_c6_set and pub_ts:
            ir_ts[c6].append(str(pub_ts))
    conn_ir.close()
    for k in ir_ts:
        ir_ts[k].sort()

    tox = pd.read_parquet(TOX_PQ)
    tox20 = tox[tox["sec_code"].astype(str).str.startswith(("30", "688", "689"))].copy()
    tox_all_ts = defaultdict(list)
    tox_red_ts = defaultdict(list)
    tox_inq_ts = defaultdict(list)
    for sc, pub_ts, ttl in zip(tox20["sec_code"], tox20["pub_datetime_cst"], tox20["title"]):
        c6 = str(sc)[:6]
        if c6 not in cand_c6_set:
            continue
        pts = str(pub_ts)
        ts = str(ttl)
        tox_all_ts[c6].append(pts)
        if "减持" in ts:
            tox_red_ts[c6].append(pts)
        if any(k in ts for k in ("问询", "立案", "警示", "处罚")):
            tox_inq_ts[c6].append(pts)
    for dmap in (tox_all_ts, tox_red_ts, tox_inq_ts):
        for k in dmap:
            dmap[k].sort()

    def count_ts(ts_map, c6, lo_ts, hi_ts):
        arr = ts_map.get(c6)
        if not arr:
            return 0
        i0 = bisect.bisect_left(arr, lo_ts)
        i1 = bisect.bisect_right(arr, hi_ts)
        return max(0, i1 - i0)

    ep_30_A = np.zeros(n); ep_60_A = np.zeros(n); en_60_A = np.zeros(n)
    ir_7_A = np.zeros(n); ir_30_A = np.zeros(n); ir_90_A = np.zeros(n); ir_cnt90_A = np.zeros(n)
    tox_30_A = np.zeros(n); tox_90_A = np.zeros(n); tox_red90_A = np.zeros(n); tox_inq90_A = np.zeros(n)
    ep_post_B = np.zeros(n); ir_post_B = np.zeros(n); tox_post_B = np.zeros(n); tox_90_B = np.zeros(n); ep_60_B = np.zeros(n)

    for idx, (dt, t1_dt, c6) in enumerate(zip(cand["dt"], cand["t1_dt"], cand["c6"])):
        d_obj = datetime.date.fromisoformat(dt)
        cut_A = f"{dt} 14:55:00"
        cut_B = f"{t1_dt} 09:25:00" if t1_dt else f"{dt} 23:59:59"
        d7 = (d_obj - datetime.timedelta(days=7)).isoformat() + " 00:00:00"
        d30 = (d_obj - datetime.timedelta(days=30)).isoformat() + " 00:00:00"
        d60 = (d_obj - datetime.timedelta(days=60)).isoformat() + " 00:00:00"
        d90 = (d_obj - datetime.timedelta(days=90)).isoformat() + " 00:00:00"

        ep_30_A[idx] = float(count_ts(ep_ts, c6, d30, cut_A) > 0)
        ep_60_A[idx] = float(count_ts(ep_ts, c6, d60, cut_A) > 0)
        en_60_A[idx] = float(count_ts(en_ts, c6, d60, cut_A) > 0)
        ir_7_A[idx] = float(count_ts(ir_ts, c6, d7, cut_A) > 0)
        ir_30_A[idx] = float(count_ts(ir_ts, c6, d30, cut_A) > 0)
        c90 = count_ts(ir_ts, c6, d90, cut_A)
        ir_90_A[idx] = float(c90 > 0)
        ir_cnt90_A[idx] = float(c90)
        tox_30_A[idx] = float(count_ts(tox_all_ts, c6, d30, cut_A) > 0)
        tox_90_A[idx] = float(count_ts(tox_all_ts, c6, d90, cut_A) > 0)
        tox_red90_A[idx] = float(count_ts(tox_red_ts, c6, d90, cut_A) > 0)
        tox_inq90_A[idx] = float(count_ts(tox_inq_ts, c6, d90, cut_A) > 0)

        ep_post_B[idx] = float(count_ts(ep_ts, c6, cut_A, cut_B) > 0)
        ir_post_B[idx] = float(count_ts(ir_ts, c6, cut_A, cut_B) > 0)
        tox_post_B[idx] = float(count_ts(tox_all_ts, c6, cut_A, cut_B) > 0)
        tox_90_B[idx] = float(count_ts(tox_all_ts, c6, d90, cut_B) > 0)
        ep_60_B[idx] = float(count_ts(ep_ts, c6, d60, cut_B) > 0)

    cand["earn_pos_30d_A"] = ep_30_A; cand["earn_pos_60d_A"] = ep_60_A; cand["earn_neg_60d_A"] = en_60_A
    cand["ir_qa_7d_A"] = ir_7_A; cand["ir_qa_30d_A"] = ir_30_A; cand["ir_qa_90d_A"] = ir_90_A; cand["ir_qa_cnt90_A"] = ir_cnt90_A
    cand["reg_tox_30d_A"] = tox_30_A; cand["reg_tox_90d_A"] = tox_90_A
    cand["tox_reduce_90d_A"] = tox_red90_A; cand["tox_inquiry_90d_A"] = tox_inq90_A
    cand["earn_pos_t0_post_B"] = ep_post_B; cand["ir_qa_t0_post_B"] = ir_post_B
    cand["reg_tox_t0_post_B"] = tox_post_B; cand["reg_tox_90d_B"] = tox_90_B; cand["earn_pos_60d_B"] = ep_60_B

    # 5. Micro-tape ZT T0 quality (Route B legal)
    t0_seal_min = np.full(n, 999.0)
    t0_seal_amt = np.zeros(n)
    t0_open_cnt = np.zeros(n)
    for idx, (dt, c6) in enumerate(zip(cand["dt"], cand["c6"])):
        tp = zt20_tape.get((dt, c6))
        if tp:
            t0_seal_min[idx], t0_seal_amt[idx], t0_open_cnt[idx] = tp
    cand["t0_seal_min"] = t0_seal_min
    cand["t0_seal_amt_yi"] = t0_seal_amt
    cand["t0_open_cnt"] = t0_open_cnt
    cand["t0_is_zt"] = cand["is_zt"].astype(float)
    cand["t1_open_gap"] = cand["t1_open_ret"]
    cand["t1_open_minus_t0"] = cand["t1_open_ret"] - cand["ret"]

    # 6. Community Heat (STRICTLY evaluated on valid crawled pairs only, NaN outside crawled set!)
    print("  Loading Community Heat (strictly masked to crawled coverage)...")
    conn_xq = sqlite3.connect(f"file:{XQ_DB}?mode=ro", uri=True)
    gb_df = pd.read_sql_query(
        "SELECT sec_code, pub_time, read_cnt, comment_cnt, d1_date FROM guba_posts WHERE (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%') AND pub_time >= '2020-12-20'",
        conn_xq,
    )
    xq_df = pd.read_sql_query(
        "SELECT symbol, created_time_str, d1_date FROM xueqiu_posts WHERE (symbol LIKE '30%' OR symbol LIKE '688%' OR symbol LIKE '689%') AND created_time_str >= '2020-12-20'",
        conn_xq,
    )
    conn_xq.close()

    gb_df["pub_d"] = gb_df["pub_time"].str[:10]
    gb_stats = {}
    for (sc, d1), grp in gb_df.groupby(["sec_code", "d1_date"], sort=False):
        if d1 not in beta_set:
            continue
        d_obj = datetime.date.fromisoformat(d1)
        d3 = (d_obj - datetime.timedelta(days=3)).isoformat()
        d7 = (d_obj - datetime.timedelta(days=7)).isoformat()
        p3 = grp[(grp["pub_d"] >= d3) & (grp["pub_time"] < f"{d1} 15:00:00")]
        p7 = grp[(grp["pub_d"] >= d7) & (grp["pub_time"] < f"{d1} 15:00:00")]
        n3 = len(p3); n7 = len(p7)
        rd = int(p3["read_cnt"].sum()); cm = int(p3["comment_cnt"].sum())
        gb_stats[(d1, sc)] = (n3, cm / max(rd, 1), n3 / max(n7 / 2.33, 0.5))

    xq_df["pub_d"] = xq_df["created_time_str"].str[:10]
    xq_stats = {}
    for (sc, d1), grp in xq_df.groupby(["symbol", "d1_date"], sort=False):
        if d1 not in beta_set:
            continue
        d3 = (datetime.date.fromisoformat(d1) - datetime.timedelta(days=3)).isoformat()
        p3 = grp[(grp["pub_d"] >= d3) & (grp["created_time_str"] < f"{d1} 15:00:00")]
        xq_stats[(d1, sc)] = len(p3)

    gb_p3 = np.full(n, np.nan); gb_cm_rd = np.full(n, np.nan); gb_slope = np.full(n, np.nan); gb_dark = np.full(n, np.nan)
    xq_p3 = np.full(n, np.nan); xq_dark = np.full(n, np.nan)
    for idx, (dt, c6) in enumerate(zip(cand["dt"], cand["c6"])):
        g_v = gb_stats.get((dt, c6))
        if g_v is not None:
            gb_p3[idx], gb_cm_rd[idx], gb_slope[idx] = g_v
            gb_dark[idx] = float(g_v[0] < 4)
        x_v = xq_stats.get((dt, c6))
        if x_v is not None:
            xq_p3[idx] = float(x_v)
            xq_dark[idx] = float(x_v < 4)
    cand["gb_posts_3d_cov"] = gb_p3
    cand["gb_dark_lt4_cov"] = gb_dark
    cand["gb_cm_read_ratio_cov"] = gb_cm_rd
    cand["gb_slope_cov"] = gb_slope
    cand["xq_posts_3d_cov"] = xq_p3
    cand["xq_dark_lt4_cov"] = xq_dark

    # 7. Merge Market Macro columns & calendar
    mkt_renamed = mkt.rename(columns={"amt_ratio_20": "mkt_amt_ratio_20"})
    mkt_cols = [
        "dt", "ew_ret_all", "up_ratio_all", "ew_ret_20cm", "ew_ret_10cm", "tot_amt_trillion",
        "amt_ma20_trillion", "mkt_amt_ratio_20", "zt_all_cnt", "zt_20cm_cnt", "dt_all_cnt",
        "seal_rate_all", "yest_1b_promo_rate", "mkt_prev1d_ew", "mkt_prev3d_ew", "mkt_prev5d_ew",
        "mkt_prev20d_ew", "mkt_20cm_prev5d_ew", "mkt_is_above_ma20", "amt_20cm_trillion",
    ]
    cand = cand.merge(mkt_renamed[mkt_cols], on="dt", how="left")
    cand["mkt_20cm_minus_10cm"] = cand["ew_ret_20cm"] - cand["ew_ret_10cm"]
    cand["mkt_20cm_amt_share"] = cand["amt_20cm_trillion"] / np.maximum(cand["tot_amt_trillion"], 0.01)
    cand["mkt_is_climax_zt150"] = (cand["zt_all_cnt"] >= 150).astype(float)
    cand["mkt_is_golden_1t"] = (cand["amt_ma20_trillion"] >= 1.0).astype(float)
    cand["mkt_is_ice_rebound"] = (cand["mkt_prev5d_ew"] < -0.02).astype(float)
    dt_ts = pd.to_datetime(cand["dt"])
    cand["is_monday"] = (dt_ts.dt.dayofweek == 0).astype(float)
    cand["is_friday"] = (dt_ts.dt.dayofweek == 4).astype(float)
    cand["is_earnings_month"] = dt_ts.dt.month.isin([1, 4, 7, 8, 10]).astype(float)
    cand["mkt_is_above_ma20"] = cand["mkt_is_above_ma20"].astype(float)
    return cand


def scan_factors(df: pd.DataFrame, factors: list[tuple[str, str, str]], target_col: str, buy_mask_col: str, pool_name: str):
    """Scan all factors on IS vs OOS and return summary rows + 6-8 fine buckets for continuous factors."""
    sub = df[df[buy_mask_col] & df[target_col].notna()].copy()
    is_m = sub["dt"] <= IS_END
    oos_m = sub["dt"] >= OOS_START
    base_is = float(sub.loc[is_m, target_col].mean())
    base_oos = float(sub.loc[oos_m, target_col].mean())

    scan_rows = []
    bucket_rows = []

    for fname, family, legal_route in factors:
        if fname not in sub.columns:
            continue
        s = pd.to_numeric(sub[fname], errors="coerce")
        valid = s.notna()
        if valid.sum() < 60:
            continue

        s_is = s[is_m & valid]; y_is = sub.loc[is_m & valid, target_col]
        s_oos = s[oos_m & valid]; y_oos = sub.loc[oos_m & valid, target_col]
        if len(s_is) < 30 or len(s_oos) < 30:
            continue

        # Spearman-like rank IC
        ic_is = float(s_is.corr(y_is, method="spearman")) if s_is.nunique() > 1 else 0.0
        ic_oos = float(s_oos.corr(y_oos, method="spearman")) if s_oos.nunique() > 1 else 0.0

        uniq = s[valid].nunique()
        if uniq <= 2:
            # Binary factor: 1 vs 0
            m1_is = s_is > 0.5; m0_is = ~m1_is
            m1_oos = s_oos > 0.5; m0_oos = ~m1_oos
            if m1_is.sum() < 10 or m0_is.sum() < 10 or m1_oos.sum() < 10 or m0_oos.sum() < 10:
                continue
            hi_is, lo_is = float(y_is[m1_is].mean()), float(y_is[m0_is].mean())
            hi_oos, lo_oos = float(y_oos[m1_oos].mean()), float(y_oos[m0_oos].mean())
            wr_hi_is, wr_hi_oos = float((y_is[m1_is] > 0).mean()), float((y_oos[m1_oos] > 0).mean())
            wr_lo_is, wr_lo_oos = float((y_is[m0_is] > 0).mean()), float((y_oos[m0_oos] > 0).mean())
            n_hi_is, n_hi_oos = int(m1_is.sum()), int(m1_oos.sum())
            spread_is = hi_is - lo_is
            spread_oos = hi_oos - lo_oos
        else:
            # Top 30% vs Bottom 30% (or >0 vs ==0 for sparse positive signals)
            if (s[valid] == 0).mean() > 0.65:
                m1_is = s_is > 0; m0_is = s_is == 0
                m1_oos = s_oos > 0; m0_oos = s_oos == 0
                if m1_is.sum() < 10 or m1_oos.sum() < 10:
                    continue
            else:
                q70 = float(s_is.quantile(0.70))
                q30 = float(s_is.quantile(0.30))
                if q70 <= q30:
                    med = float(s_is.median())
                    m1_is = s_is > med; m0_is = s_is <= med
                    m1_oos = s_oos > med; m0_oos = s_oos <= med
                else:
                    m1_is = s_is >= q70; m0_is = s_is <= q30
                    m1_oos = s_oos >= q70; m0_oos = s_oos <= q30
                if m1_is.sum() < 15 or m0_is.sum() < 15 or m1_oos.sum() < 15 or m0_oos.sum() < 15:
                    continue
            hi_is, lo_is = float(y_is[m1_is].mean()), float(y_is[m0_is].mean())
            hi_oos, lo_oos = float(y_oos[m1_oos].mean()), float(y_oos[m0_oos].mean())
            wr_hi_is, wr_hi_oos = float((y_is[m1_is] > 0).mean()), float((y_oos[m1_oos] > 0).mean())
            wr_lo_is, wr_lo_oos = float((y_is[m0_is] > 0).mean()), float((y_oos[m0_oos] > 0).mean())
            n_hi_is, n_hi_oos = int(m1_is.sum()), int(m1_oos.sum())
            spread_is = hi_is - lo_is
            spread_oos = hi_oos - lo_oos

        same_dir = (spread_is > 0 and spread_oos > 0) or (spread_is < 0 and spread_oos < 0)

        # Day-level equal-weight spread & within-day cross-sectional IC (eliminates single frenzy-day weight bias)
        dt_is = sub.loc[is_m & valid, "dt"]
        dt_oos = sub.loc[oos_m & valid, "dt"]
        dew_hi_is = float(y_is[m1_is].groupby(dt_is[m1_is]).mean().mean())
        dew_lo_is = float(y_is[m0_is].groupby(dt_is[m0_is]).mean().mean())
        dew_hi_oos = float(y_oos[m1_oos].groupby(dt_oos[m1_oos]).mean().mean())
        dew_lo_oos = float(y_oos[m0_oos].groupby(dt_oos[m0_oos]).mean().mean())
        dew_sp_is = dew_hi_is - dew_lo_is
        dew_sp_oos = dew_hi_oos - dew_lo_oos
        dew_same = (dew_sp_is > 0 and dew_sp_oos > 0) or (dew_sp_is < 0 and dew_sp_oos < 0)

        # Within-day rank IC (if cross-sectional variation exists within days)
        def daily_mean_ic(s_vec, y_vec, dt_vec):
            ics = []
            tmp = pd.DataFrame({"dt": dt_vec.values, "x": s_vec.values, "y": y_vec.values})
            for _, g in tmp.groupby("dt", sort=False):
                if len(g) >= 8 and g["x"].nunique() > 1:
                    c = g["x"].corr(g["y"], method="spearman")
                    if pd.notna(c):
                        ics.append(float(c))
            return float(np.mean(ics)) if len(ics) >= 5 else np.nan

        cs_ic_is = daily_mean_ic(s_is, y_is, dt_is)
        cs_ic_oos = daily_mean_ic(s_oos, y_oos, dt_oos)

        scan_rows.append({
            "pool": pool_name,
            "route_target": target_col,
            "factor": fname,
            "family": family,
            "legal_route": legal_route,
            "is_n_all": int(len(s_is)),
            "oos_n_all": int(len(s_oos)),
            "is_n_hi": n_hi_is,
            "oos_n_hi": n_hi_oos,
            "is_hi_mean_pct": round(hi_is * 100, 3),
            "is_lo_mean_pct": round(lo_is * 100, 3),
            "is_spread_pp": round(spread_is * 100, 3),
            "is_hi_wr_pct": round(wr_hi_is * 100, 1),
            "is_lo_wr_pct": round(wr_lo_is * 100, 1),
            "oos_hi_mean_pct": round(hi_oos * 100, 3),
            "oos_lo_mean_pct": round(lo_oos * 100, 3),
            "oos_spread_pp": round(spread_oos * 100, 3),
            "oos_hi_wr_pct": round(wr_hi_oos * 100, 1),
            "oos_lo_wr_pct": round(wr_lo_oos * 100, 1),
            "ic_is": round(ic_is, 4) if not np.isnan(ic_is) else 0.0,
            "ic_oos": round(ic_oos, 4) if not np.isnan(ic_oos) else 0.0,
            "dual_same_dir": bool(same_dir),
            "min_abs_spread_pp": round(min(abs(spread_is), abs(spread_oos)) * 100, 3) if same_dir else 0.0,
            "dew_is_hi_pct": round(dew_hi_is * 100, 3),
            "dew_is_lo_pct": round(dew_lo_is * 100, 3),
            "dew_is_spread_pp": round(dew_sp_is * 100, 3),
            "dew_oos_hi_pct": round(dew_hi_oos * 100, 3),
            "dew_oos_lo_pct": round(dew_lo_oos * 100, 3),
            "dew_oos_spread_pp": round(dew_sp_oos * 100, 3),
            "dew_dual_same_dir": bool(dew_same),
            "dew_min_abs_pp": round(min(abs(dew_sp_is), abs(dew_sp_oos)) * 100, 3) if dew_same else 0.0,
            "cs_ic_is": round(cs_ic_is, 4) if pd.notna(cs_ic_is) else None,
            "cs_ic_oos": round(cs_ic_oos, 4) if pd.notna(cs_ic_oos) else None,
        })

        # 7-bin quantile bucketing for continuous factors (thresholds derived strictly from IS!)
        if uniq >= 10 and (s[valid] == 0).mean() < 0.50:
            try:
                qs = np.unique(np.nanquantile(s_is, np.linspace(0, 1, 8)))
                if len(qs) >= 5:
                    qs[0] = -1e18; qs[-1] = 1e18
                    b_is = pd.cut(s_is, bins=qs, include_lowest=True)
                    b_oos = pd.cut(s_oos, bins=qs, include_lowest=True)
                    for bi, cat in enumerate(b_is.cat.categories, 1):
                        mi = b_is == cat; mo = b_oos == cat
                        dew_i = float(y_is[mi].groupby(dt_is[mi]).mean().mean() * 100) if mi.sum() else None
                        dew_o = float(y_oos[mo].groupby(dt_oos[mo]).mean().mean() * 100) if mo.sum() else None
                        bucket_rows.append({
                            "pool": pool_name, "route_target": target_col, "factor": fname,
                            "bin_idx": bi, "bin_range": str(cat),
                            "is_n": int(mi.sum()), "is_mean_pct": round(float(y_is[mi].mean() * 100), 3) if mi.sum() else None,
                            "is_day_ew_pct": round(dew_i, 3) if dew_i is not None else None,
                            "is_wr_pct": round(float((y_is[mi] > 0).mean() * 100), 1) if mi.sum() else None,
                            "oos_n": int(mo.sum()), "oos_mean_pct": round(float(y_oos[mo].mean() * 100), 3) if mo.sum() else None,
                            "oos_day_ew_pct": round(dew_o, 3) if dew_o is not None else None,
                            "oos_wr_pct": round(float((y_oos[mo] > 0).mean() * 100), 1) if mo.sum() else None,
                        })
            except Exception:
                pass

    return pd.DataFrame(scan_rows), pd.DataFrame(bucket_rows)


def main():
    t0 = time.time()
    print("[Step 2] Loading market_daily & panel_20cm...")
    mkt = pd.read_parquet(MKT_PQ)
    p20 = pd.read_parquet(P20_PQ)

    p20 = compute_rolling_20cm_features(p20)

    # Beta days: ew_ret_all >= +2.0% & up_ratio_all >= 80%
    beta_dts = set(mkt[(mkt["dt"] >= "2021-01-04") & (mkt["ew_ret_all"] >= 0.02) & (mkt["up_ratio_all"] >= 0.80)]["dt"])
    cand = p20[p20["dt"].isin(beta_dts) & p20["is_clean_universe"] & (p20["ret"] >= 0.05)].copy().reset_index(drop=True)
    print(f"  Beta-day 20cm >= +5% pool: {len(cand):,} rows across {cand['dt'].nunique()} days")

    cand = build_auxiliary_enrichments(cand, mkt, p20)
    cand.to_parquet(f"{OUT_DIR}/beta_day_candidates_enriched.parquet", index=False)
    print(f"  Saved beta_day_candidates_enriched.parquet ({len(cand):,} rows, {cand.shape[1]} cols) in {time.time()-t0:.1f}s")

    # Define 145+ factor registry: (col_name, family, legal_route)
    FACTORS = [
        # F1: Price & Intraday Microstructure (26)
        ("ret", "F1_Micro", "A_and_B"), ("open_gap", "F1_Micro", "A_and_B"), ("intraday_ret", "F1_Micro", "A_and_B"),
        ("clv", "F1_Micro", "A_and_B"), ("upper_shadow_pct", "F1_Micro", "A_and_B"), ("lower_shadow_pct", "F1_Micro", "A_and_B"),
        ("body_ratio", "F1_Micro", "A_and_B"), ("amplitude", "F1_Micro", "A_and_B"), ("gap_vs_intraday_diff", "F1_Micro", "A_and_B"),
        ("is_true_yang", "F1_Micro", "A_and_B"), ("close_near_high", "F1_Micro", "A_and_B"), ("turn_pct", "F1_Micro", "A_and_B"),
        ("amt_yi", "F1_Micro", "A_and_B"), ("log_amt", "F1_Micro", "A_and_B"), ("amt_ratio_5", "F1_Micro", "A_and_B"),
        ("amt_ratio_20", "F1_Micro", "A_and_B"), ("turn_ratio_5", "F1_Micro", "A_and_B"), ("turn_ratio_20", "F1_Micro", "A_and_B"),
        ("vol_exp_1d", "F1_Micro", "A_and_B"), ("amihud_day", "F1_Micro", "A_and_B"), ("amihud_20d_pre", "F1_Micro", "A_and_B"),
        ("vol_contraction_5_20", "F1_Micro", "A_and_B"), ("up_days_5d_pre", "F1_Micro", "A_and_B"), ("consec_up_pre", "F1_Micro", "A_and_B"),
        ("is_first_bigup_20d", "F1_Micro", "A_and_B"), ("is_first_bigup_60d", "F1_Micro", "A_and_B"),
        # F2: Trend, Box Pos, Headroom & Old Dragon (28)
        ("prev_ret1", "F2_TrendPos", "A_and_B"), ("prev_ret3", "F2_TrendPos", "A_and_B"), ("prev_ret5", "F2_TrendPos", "A_and_B"),
        ("prev_ret10", "F2_TrendPos", "A_and_B"), ("prev_ret20", "F2_TrendPos", "A_and_B"), ("prev_ret60", "F2_TrendPos", "A_and_B"),
        ("pos20_pre", "F2_TrendPos", "A_and_B"), ("pos20_incl", "F2_TrendPos", "A_and_B"), ("pos60_pre", "F2_TrendPos", "A_and_B"),
        ("pos120_pre", "F2_TrendPos", "A_and_B"), ("dist_ma5_pre", "F2_TrendPos", "A_and_B"), ("dist_ma10_pre", "F2_TrendPos", "A_and_B"),
        ("dist_ma20_pre", "F2_TrendPos", "A_and_B"), ("dist_ma60_pre", "F2_TrendPos", "A_and_B"), ("dist_ma20_t0", "F2_TrendPos", "A_and_B"),
        ("above_ma20_pre", "F2_TrendPos", "A_and_B"), ("above_ma60_pre", "F2_TrendPos", "A_and_B"), ("ma20_slope_5d", "F2_TrendPos", "A_and_B"),
        ("cross_above_ma20_t0", "F2_TrendPos", "A_and_B"), ("dd_20h_pre", "F2_TrendPos", "A_and_B"), ("dd_60h_pre", "F2_TrendPos", "A_and_B"),
        ("head_3d30", "F2_TrendPos", "A_and_B"), ("head_10d100", "F2_TrendPos", "A_and_B"), ("head_30d200", "F2_TrendPos", "A_and_B"),
        ("min_severe_headroom", "F2_TrendPos", "A_and_B"), ("big7_cnt_20d_pre", "F2_TrendPos", "A_and_B"),
        ("zt_cnt_60d_pre", "F2_TrendPos", "A_and_B"), ("is_old_dragon_rebound", "F2_TrendPos", "A_and_B"),
        # F3: Size & Board (11)
        ("circ_mcap", "F3_SizeBoard", "A_and_B"), ("log_mcap", "F3_SizeBoard", "A_and_B"),
        ("is_small_lt50", "F3_SizeBoard", "A_and_B"), ("is_mid_50_150", "F3_SizeBoard", "A_and_B"), ("is_big_army_ge150", "F3_SizeBoard", "A_and_B"),
        ("is_star_f", "F3_SizeBoard", "A_and_B"), ("is_chinext", "F3_SizeBoard", "A_and_B"), ("is_301", "F3_SizeBoard", "A_and_B"),
        ("close", "F3_SizeBoard", "A_and_B"), ("mcap_x_turn", "F3_SizeBoard", "A_and_B"), ("amt_over_mcap_pct", "F3_SizeBoard", "A_and_B"),
        ("list_age_capped", "F3_SizeBoard", "A_and_B"),
        # F4: KPL Theme & Cross-Board (22)
        ("csrc_hard_tech", "F4_KPL", "A_and_B"),
        ("in_kpl_yest", "F4_KPL", "A_and_B"), ("kpl_yest_top3", "F4_KPL", "A_and_B"), ("kpl_yest_top1", "F4_KPL", "A_and_B"),
        ("kpl_yest_rk", "F4_KPL", "A_and_B"), ("kpl_yest_cnt", "F4_KPL", "A_and_B"), ("kpl_ht_yest", "F4_KPL", "A_and_B"),
        ("kpl_ev_yest", "F4_KPL", "A_and_B"), ("kpl_bi_yest", "F4_KPL", "A_and_B"),
        ("kpl_live_20_cnt", "F4_KPL", "A_and_B"), ("kpl_live_10_zt_cnt", "F4_KPL", "A_and_B"),
        ("kpl_live_20_to_10_ratio", "F4_KPL", "A_and_B"), ("kpl_live_climax_gt35", "F4_KPL", "A_and_B"),
        ("in_kpl_t0", "F4_KPL", "B_only"), ("kpl_t0_top3", "F4_KPL", "B_only"), ("kpl_t0_top1", "F4_KPL", "B_only"),
        ("kpl_t0_rk", "F4_KPL", "B_only"), ("kpl_t0_sz", "F4_KPL", "B_only"), ("kpl_t0_n10", "F4_KPL", "B_only"),
        ("kpl_t0_n20", "F4_KPL", "B_only"), ("kpl_t0_ht", "F4_KPL", "B_only"), ("kpl_t0_ev", "F4_KPL", "B_only"),
        ("kpl_t0_max_pzt_gt35", "F4_KPL", "B_only"),
        # F5: LHB & Bayes Seats (20)
        ("lhb_cnt_10d_pre", "F5_LHB", "A_and_B"), ("lhb_org_net_10d_pre", "F5_LHB", "A_and_B"),
        ("lhb_has_org_10d_pre", "F5_LHB", "A_and_B"), ("lhb_has_lhasa_10d_pre", "F5_LHB", "A_and_B"), ("lhb_bayes_10d_pre", "F5_LHB", "A_and_B"),
        ("lhb_on_t0", "F5_LHB", "B_only"), ("lhb_on_t0_3d", "F5_LHB", "B_only"), ("lhb_t0_net_yi", "F5_LHB", "B_only"),
        ("lhb_t0_net_over_amt", "F5_LHB", "B_only"), ("lhb_t0_org_net_yi", "F5_LHB", "B_only"), ("lhb_t0_org_cnt", "F5_LHB", "B_only"),
        ("lhb_t0_org_share", "F5_LHB", "B_only"), ("lhb_t0_pure_org", "F5_LHB", "B_only"), ("lhb_t0_lhasa_cnt", "F5_LHB", "B_only"),
        ("lhb_t0_lhasa_share", "F5_LHB", "B_only"), ("lhb_t0_north_yi", "F5_LHB", "B_only"), ("lhb_t0_good", "F5_LHB", "B_only"),
        ("lhb_t0_bad", "F5_LHB", "B_only"), ("lhb_t0_bc", "F5_LHB", "B_only"), ("lhb_t0_bt2", "F5_LHB", "B_only"),
        # F6: Notices, IR QA & Reg-Tox (16)
        ("earn_pos_30d_A", "F6_NoticesTox", "A_and_B"), ("earn_pos_60d_A", "F6_NoticesTox", "A_and_B"), ("earn_neg_60d_A", "F6_NoticesTox", "A_and_B"),
        ("ir_qa_7d_A", "F6_NoticesTox", "A_and_B"), ("ir_qa_30d_A", "F6_NoticesTox", "A_and_B"), ("ir_qa_90d_A", "F6_NoticesTox", "A_and_B"),
        ("ir_qa_cnt90_A", "F6_NoticesTox", "A_and_B"), ("reg_tox_30d_A", "F6_NoticesTox", "A_and_B"), ("reg_tox_90d_A", "F6_NoticesTox", "A_and_B"),
        ("tox_reduce_90d_A", "F6_NoticesTox", "A_and_B"), ("tox_inquiry_90d_A", "F6_NoticesTox", "A_and_B"),
        ("earn_pos_t0_post_B", "F6_NoticesTox", "B_only"), ("ir_qa_t0_post_B", "F6_NoticesTox", "B_only"),
        ("reg_tox_t0_post_B", "F6_NoticesTox", "B_only"), ("reg_tox_90d_B", "F6_NoticesTox", "B_only"), ("earn_pos_60d_B", "F6_NoticesTox", "B_only"),
        # F7: Market Macro & Sentiment (20)
        ("ew_ret_all", "F7_Macro", "A_and_B"), ("up_ratio_all", "F7_Macro", "A_and_B"), ("ew_ret_20cm", "F7_Macro", "A_and_B"),
        ("mkt_20cm_minus_10cm", "F7_Macro", "A_and_B"), ("tot_amt_trillion", "F7_Macro", "A_and_B"), ("amt_ma20_trillion", "F7_Macro", "A_and_B"),
        ("mkt_amt_ratio_20", "F7_Macro", "A_and_B"), ("zt_all_cnt", "F7_Macro", "A_and_B"), ("zt_20cm_cnt", "F7_Macro", "A_and_B"),
        ("dt_all_cnt", "F7_Macro", "A_and_B"), ("seal_rate_all", "F7_Macro", "A_and_B"), ("yest_1b_promo_rate", "F7_Macro", "A_and_B"),
        ("mkt_prev1d_ew", "F7_Macro", "A_and_B"), ("mkt_prev3d_ew", "F7_Macro", "A_and_B"), ("mkt_prev5d_ew", "F7_Macro", "A_and_B"),
        ("mkt_prev20d_ew", "F7_Macro", "A_and_B"), ("mkt_20cm_prev5d_ew", "F7_Macro", "A_and_B"), ("mkt_is_above_ma20", "F7_Macro", "A_and_B"),
        ("mkt_20cm_amt_share", "F7_Macro", "A_and_B"), ("mkt_is_climax_zt150", "F7_Macro", "A_and_B"),
        ("mkt_is_golden_1t", "F7_Macro", "A_and_B"), ("mkt_is_ice_rebound", "F7_Macro", "A_and_B"),
        ("is_monday", "F7_Macro", "A_and_B"), ("is_friday", "F7_Macro", "A_and_B"), ("is_earnings_month", "F7_Macro", "A_and_B"),
        # F8: Route B T+1 Open & T0 ZT Tape (6)
        ("t1_open_gap", "F8_RouteB_Micro", "B_only"), ("t1_open_minus_t0", "F8_RouteB_Micro", "B_only"),
        ("t0_is_zt", "F8_RouteB_Micro", "B_only"), ("t0_seal_min", "F8_RouteB_Micro", "B_only"),
        ("t0_seal_amt_yi", "F8_RouteB_Micro", "B_only"), ("t0_open_cnt", "F8_RouteB_Micro", "B_only"),
        # F9: Community (6, covered subset only)
        ("gb_posts_3d_cov", "F9_Community", "Covered_ZT_only"), ("gb_dark_lt4_cov", "F9_Community", "Covered_ZT_only"),
        ("gb_cm_read_ratio_cov", "F9_Community", "Covered_ZT_only"), ("gb_slope_cov", "F9_Community", "Covered_ZT_only"),
        ("xq_posts_3d_cov", "F9_Community", "Covered_ZT_only"), ("xq_dark_lt4_cov", "F9_Community", "Covered_ZT_only"),
    ]
    print(f"  Registered {len(FACTORS)} factors!")

    # Pools to scan:
    # 1) [5%, 15%) Route A (T0 close -> T+2)
    # 2) [7%, 15%) Route A (T0 close -> T+2)
    # 3) [5%, 15%) Route B (T+1 open -> T+2)
    # 4) [7%, 19.5%) Route B (T+1 open -> T+2)
    p_5_15 = cand[(cand["ret"] >= 0.05) & (cand["ret"] < 0.15)].copy()
    p_7_15 = cand[(cand["ret"] >= 0.07) & (cand["ret"] < 0.15)].copy()
    p_5_zt = cand.copy()

    factors_A = [f for f in FACTORS if f[2] == "A_and_B"]
    factors_B = [f for f in FACTORS if f[2] != "Covered_ZT_only"]

    s1, b1 = scan_factors(p_5_15, factors_A, "retA_t2", "buyable_A", "Band_5_15_RouteA")
    s2, b2 = scan_factors(p_7_15, factors_A, "retA_t2", "buyable_A", "Band_7_15_RouteA")
    s3, b3 = scan_factors(p_5_15, factors_B, "retB_t2", "buyable_B", "Band_5_15_RouteB")
    s4, b4 = scan_factors(p_5_zt, FACTORS, "retB_t2", "buyable_B", "Band_5_20ZT_RouteB")

    scan_all = pd.concat([s1, s2, s3, s4], ignore_index=True)
    buckets_all = pd.concat([b1, b2, b3, b4], ignore_index=True)
    scan_all.to_csv(f"{OUT_DIR}/factor_scan_part1.csv", index=False)
    buckets_all.to_csv(f"{OUT_DIR}/factor_buckets_part1.csv", index=False)

    print(f"[Step 2 Done] Saved factor_scan_part1.csv ({len(scan_all)} rows, {scan_all['factor'].nunique()} unique factors) & factor_buckets_part1.csv ({len(buckets_all)} rows) in {time.time()-t0:.1f}s")
    # Print top dual-period factors for Band_5_15_RouteA & Band_7_15_RouteA & Band_5_15_RouteB
    for pnm in ["Band_5_15_RouteA", "Band_7_15_RouteA", "Band_5_15_RouteB"]:
        sub_s = scan_all[(scan_all["pool"] == pnm) & scan_all["dew_dual_same_dir"]].sort_values("dew_min_abs_pp", ascending=False).head(18)
        print(f"\n=== TOP 18 DAY-EQUAL-WEIGHT DUAL-PERIOD FACTORS: {pnm} ===")
        print(sub_s[["factor","family","dew_is_hi_pct","dew_is_lo_pct","dew_is_spread_pp","dew_oos_hi_pct","dew_oos_lo_pct","dew_oos_spread_pp","cs_ic_is","cs_ic_oos"]].to_string(index=False))


if __name__ == "__main__":
    main()
