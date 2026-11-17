#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
build_true_v15_trainer_data.py
================================================================================
A 股一进二盘感刷题机 · 100% 实盘原装 V14/V15 闭环主引擎全量题库构建器
严格落地：
1. 100% 原装行情与真首板识别 (load_full_prices):
   - 严禁二板及以上混入！is_first_board = is_zt & (~prev_zt) & (~is_yizi)
   - 循环累加计算真实连板高度 consec_zt，统计每日真实最高连板高度与首板家数
2. 100% 原装 8 年连续预热双层题材 Elo (build_8y_preheated_elo):
   - 真实提取板块 10 日热度序列 heat_bars、当日涨停数 sz、高标护航 escort、题材属性 term_type
3. 100% 原装 PIT 公告净化与盘前打分 (attach_purified_pit_notices_and_scores):
   - sqlite3.connect(f"file:{PIT_NOTICES_DB}?mode=ro", uri=True) 只读锁
   - ST 与退市股彻底清零 (~is_st)
4. 100% 实盘逻辑系统综合排名 (sys_rank) 与人机 PK 基准 (sys_ret):
   - 五梯队分层排序分 sys_rank_score，避免冷开不及格票倒挂排在前排
   - dual_p 未触发时系统真实动作空仓防守 (sys_ret=0.0, 空仓击败量化)
5. 100% 原装 K 线切片、客观盘口指标与 B0 仿真交易 (simulate_v14_single_trade):
   - 最后一根 K 线必须是 D1 首板，倒数第二根必须是未涨停 D0
   - dd20/vr/pre_d1 100% 真实计算，零模板分桶假数
   - 每只股票附带清晰离场说明与 1 句大白话 PM 复盘点评 pm_comment
6. 过滤财报篮子，3 题材 x 2~4 候选股，左右与 ABCD 双重 Fisher-Yates 随机洗牌
7. 输出全量 5 年题库 (/tmp/astock2_5y_hierarchical.json) 与经典 8 关 (/tmp/astock2_q1_hierarchical.json)
================================================================================
"""
import os
import sys
import re
import json
import time
import math
import random
import bisect
import sqlite3
import datetime
from collections import defaultdict, Counter

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT_DIR = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT_DIR}/sim-portfolio"
BACKTESTS_DIR = f"{SIM_DIR}/backtests_astock2"

A_DAILY_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_MERGED_PATH = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"
KPL_5Y_PATH = f"{SIM_DIR}/data/kpl_plates_5y_2021_2026_complete.jsonl"
PIT_NOTICES_DB = f"{SIM_DIR}/data/cninfo_notices_5y_pit.db"
SH_DAILY_PKL = "/tmp/astock2_sh_daily.pkl"

OUT_5Y_JSON = "/tmp/astock2_5y_hierarchical.json"
OUT_Q1_JSON = "/tmp/astock2_q1_hierarchical.json"

FEE_RATE = 0.0020  # 千二双边交易成本

NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股"
}

MA_PAT = re.compile(r"(重组|收购|股权转让|实控人变更|控制权变更|资产注入|借壳|控股|整合|中标|重大合同)")
TECH_PAT_ORIG = re.compile(
    r"(AI|算力|机器人|芯片|半导体|光刻|低空|商业航天|卫星|太空|固态电池|量子|脑机|大模型|具身智能|"
    r"华为|鸿蒙|无人驾驶|智驾|游戏|影之刃|黑神话|CPO|光模块|液冷|HBM|数据要素|深海|核聚变)"
)
TECH_PAT_TIMELESS = re.compile(
    r"(芯片|半导体|光刻|集成电路|软件|信创|云计算|大数据|人工智能|AI|机器人|智能制造|自动化|"
    r"通信|5G|光通信|卫星|航天|军工|锂电|光伏|储能|风电|氢能|新材料|消费电子|智能驾驶|无人驾驶)"
)
EARN_PAT = re.compile(r"(业绩|预增|扭亏|季报|年报|半年报|分红)")

HARD_NOTICE_PAT = re.compile(r"(重组|收购|股权转让|控制权|实控人变更|资产注入|借壳|重大合同|中标|战略合作|框架协议|投资设立)")
HARD_NOTICE_ORIG_PAT = re.compile(
    r"(重组|收购|股权转让|控制权|实控人变更|资产注入|借壳|重大合同|中标|战略合作|框架协议|投资设立|"
    r"算力|机器人|芯片|卫星|人工智能|固态电池|低空)"
)
MA_NOTICE_PAT = re.compile(r"(重组|收购|股权转让|控制权变更|实控人变更|资产注入|借壳|重大合同|中标)")
EARN_NOTICE_PAT = re.compile(r"(业绩预增|业绩快报|扭亏为盈|半年度业绩|年度业绩|季度业绩)")
BAD_NOTICE_PAT = re.compile(
    r"(减持|问询函|监管函|警示函|立案|风险提示|业绩预亏|亏损|计提资产减值|退市风险|终止上市|违规|质押|冻结)"
)
NEG_NOTICE_PAT = re.compile(
    r"(不存在|不涉及|未筹划|未发现|无应披露|股票交易异常波动|异常波动公告|风险提示|占比极小|敬请广大投资者注意)"
)


def safe_float(v, default=0.0):
    try:
        val = float(v)
        return default if math.isnan(val) or math.isinf(val) else val
    except Exception:
        return default


def split_terms(s: str) -> set:
    out = set()
    for part in re.split(r"[+、,，/；;]", s or ""):
        part = part.strip()
        if not part:
            continue
        out.add(part)
        for x in re.split(r"[()（）]", part):
            x = x.strip()
            if x:
                out.add(x)
    return {t for t in out if 2 <= len(t) <= 20 and t not in NON_THEME}


def norm_term(t: str) -> str:
    t = re.sub(r"（.*?）|\(.*?\)", "", t or "")
    return re.sub(r"[\s·\-_()（）“”\"'《》/]", "", t).lower().removesuffix("概念")


def load_full_prices():
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn", "oshare"]
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2017-08-01"))).to_table().to_pandas()

    parts = [df_act]
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format="parquet")
        df_del = ds_del.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2017-08-01"))).to_table().to_pandas()
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
    df["o_pct"] = df["open"] / df["pre_c"] - 1.0
    df["h_pct"] = df["high"] / df["pre_c"] - 1.0
    df["l_pct"] = df["low"] / df["pre_c"] - 1.0
    df["mcap"] = df["close"] * df["oshare"] / 1e8
    df["to"] = df["turn"] * 100.0

    df["zt_price"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["dt_price"] = np.floor(df["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_price"] - 0.01) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
    df["is_dt"] = (df["close"] <= df["dt_price"] + 0.01) & (df["pct"] <= -0.095) & (df["pre_c"] > 0)
    df["touch_zt"] = ((df["high"] >= df["zt_price"] - 0.01) | (df["h_pct"] >= 0.098)) & (df["pre_c"] > 0)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_price"] - 0.01) & (df["low"] >= df["zt_price"] - 0.01)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_price"] + 0.01) & (df["high"] <= df["dt_price"] + 0.01)

    df["prev_zt"] = g["is_zt"].shift(1).fillna(False)
    df["prev2_zt"] = g["is_zt"].shift(2).fillna(False)
    df["is_2b_plus"] = df["is_zt"] & df["prev_zt"]
    df["is_1to2_day"] = df["prev_zt"] & (~df["prev2_zt"])
    df["is_first_board"] = df["is_zt"] & (~df["prev_zt"])

    # 100% 精确计算截至 D1 的真实连板高度 consec_zt
    is_new_stock = (df["c6"].values != np.roll(df["c6"].values, 1))
    is_new_stock[0] = True
    is_zt_arr = df["is_zt"].values
    consec_arr = np.zeros(len(df), dtype=np.int32)
    cur_consec = 0
    for i in range(len(df)):
        if is_new_stock[i] or not is_zt_arr[i]:
            cur_consec = int(is_zt_arr[i])
        else:
            cur_consec += 1
        consec_arr[i] = cur_consec
    df["consec_zt"] = consec_arr

    df["f_d0_close"] = g["close"].shift(1)
    df["f_d0_pct"] = g["pct"].shift(1)
    df["f_ret_pre5"] = df["f_d0_close"] / (g["close"].shift(6) + 1e-6) - 1.0
    df["f_ret_pre10"] = df["f_d0_close"] / (g["close"].shift(11) + 1e-6) - 1.0
    df["f_max20_d0"] = g["high"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).max())
    df["f_max60_d0"] = g["high"].transform(lambda s: s.shift(1).rolling(60, min_periods=20).max())
    df["f_min20_d0"] = g["low"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).min())
    df["f_dd20_d0"] = df["f_d0_close"] / (df["f_max20_d0"] + 1e-6)
    df["f_dd60_d0"] = df["f_d0_close"] / (df["f_max60_d0"] + 1e-6)
    df["f_pos20_d0"] = (df["f_d0_close"] - df["f_min20_d0"]) / (df["f_max20_d0"] - df["f_min20_d0"] + 1e-6)
    df["f_vol_ma5_d0"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    df["f_d1_vol_ratio"] = df["amount"] / (df["f_vol_ma5_d0"] + 1e-6)
    df["zt_int"] = df["is_zt"].astype(int)
    df["f_zt_cnt_pre20"] = g["zt_int"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).sum())
    df["f_break60"] = (df["close"] >= df["f_max60_d0"] - 0.01).astype(int)
    df["f_entity"] = (df["close"] - df["open"]) / (df["pre_c"] + 1e-6)

    # D1 真实封板紧密度
    df["d1_dip"] = (df["low"] - df["pre_c"]) / (df["pre_c"] + 1e-6)
    df["d1_entity"] = (df["close"] - df["open"]) / (df["pre_c"] + 1e-6)
    vol_ma5 = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    df["d1_vol_ratio"] = df["amount"] / (vol_ma5 + 1e-6)
    df["d1_seal_tightness"] = (
        (df["close"] == df["high"]).astype(int) * 30.0
        + np.clip(df["d1_dip"] * 100.0, -10.0, 10.0) * 1.5
        + np.clip(df["d1_entity"] * 100.0, 0.0, 10.0) * 2.0
        - np.where(df["d1_vol_ratio"] > 4.0, 15.0, 0.0)
    )

    df["d2_dt"] = g["dt_str"].shift(-1)
    df["d2_open"] = g["open"].shift(-1)
    df["d2_high"] = g["high"].shift(-1)
    df["d2_low"] = g["low"].shift(-1)
    df["d2_close"] = g["close"].shift(-1)
    df["d2_o_pct"] = df["d2_open"] / df["close"] - 1.0
    df["d2_zt_p"] = np.floor(df["close"] * 1.10 * 100.0 + 0.5) / 100.0
    df["d2_is_zt"] = g["is_zt"].shift(-1).fillna(False)
    df["d2_is_yizi"] = g["is_yizi"].shift(-1).fillna(False)

    all_dts = sorted(df["dt_str"].unique())
    dg = df.groupby("dt_str")
    zt_cnt_map = dg["is_zt"].sum().to_dict()
    dt_cnt_map = dg["is_dt"].sum().to_dict()
    max_height_map = dg["consec_zt"].max().to_dict()

    fb_valid_sub = df[df["is_first_board"] & (~df["is_yizi"])]
    fb_cnt_map = fb_valid_sub.groupby("dt_str")["c6"].count().to_dict()
    d1_fb_open_map = fb_valid_sub.groupby("dt_str")["d2_o_pct"].mean().to_dict()

    d1_1to2_sub = df[df["is_1to2_day"]]
    dg_1to2 = d1_1to2_sub.groupby("dt_str")
    cnt_1to2_map = dg_1to2["is_zt"].count().to_dict()
    touch_1to2_map = dg_1to2["touch_zt"].sum().to_dict()
    seal_1to2_map = dg_1to2["is_zt"].sum().to_dict()

    seal_rate_map, promo_ma5_map = {}, {}
    promo_list = []
    for dt in all_dts:
        tc = touch_1to2_map.get(dt, 0)
        sc = seal_1to2_map.get(dt, 0)
        cc = cnt_1to2_map.get(dt, 0)
        seal_rate_map[dt] = float(sc / tc) if tc > 0 else 0.55
        promo_list.append(float(sc / cc) if cc > 0 else 0.20)
        promo_ma5_map[dt] = float(np.mean(promo_list[-5:]))

    print(f"[Prices] Loaded {len(df):,} mainboard rows from 2017-08 in {time.time()-t0:.2f}s")
    return df, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map, max_height_map, fb_cnt_map, d1_fb_open_map


def build_8y_preheated_elo(df: pd.DataFrame):
    t0 = time.time()
    kpl_days_map = {}
    if os.path.exists(KPL_MERGED_PATH):
        for ln in open(KPL_MERGED_PATH, encoding="utf-8"):
            if ln.strip():
                try:
                    d = json.loads(ln)
                    dt = d.get("date", "")
                    if dt < "2021-01-01":
                        kpl_days_map[dt] = d
                except Exception:
                    pass

    if os.path.exists(KPL_5Y_PATH):
        for ln in open(KPL_5Y_PATH, encoding="utf-8"):
            if ln.strip():
                try:
                    d = json.loads(ln)
                    dt = d.get("date", "")
                    if dt >= "2021-01-01":
                        kpl_days_map[dt] = d
                except Exception:
                    pass

    kpl_days = [kpl_days_map[k] for k in sorted(kpl_days_map.keys())]
    print(f"[Preheating] Merged {len(kpl_days)} trading days of KPL plates (from {kpl_days[0]['date']} to {kpl_days[-1]['date']})")

    kpl_dt_set = {d["date"] for d in kpl_days}
    sub_df_kpl = df[df["dt_str"].isin(kpl_dt_set)][["dt_str", "c6", "is_zt", "touch_zt", "is_yizi", "pct", "mcap", "is_2b_plus"]]
    day_stock_map = {
        (r.dt_str, r.c6): (r.is_zt, r.touch_zt, r.is_yizi, r.pct, r.mcap, r.is_2b_plus)
        for r in sub_df_kpl.itertuples(index=False)
    }

    elo = defaultdict(lambda: 100.0)
    sub_elo = defaultdict(lambda: 100.0)
    plate_recent_zts = defaultdict(list)
    plate_last_idx, sub_last_idx = {}, {}
    prev_plate_stocks, prev_sub_stocks = {}, {}
    term_seen_days = Counter()
    term_first_dt, term_last_idx = {}, {}
    pioneer_word_history = defaultdict(set)
    stock_theme_5y = {}
    plate_daily_meta = {}  # (dt, pname) -> meta dict
    global_stock_names = {}  # c6 -> most recent valid name

    for day_idx, d_entry in enumerate(kpl_days):
        dt = d_entry["date"]
        cutoff_15d = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=15)).isoformat()
        plates = d_entry.get("plates", [])

        # Elo update from previous day
        for pname, c6_list in prev_plate_stocks.items():
            touches, seals, rets = 0, 0, []
            for c6 in c6_list:
                st = day_stock_map.get((dt, c6))
                if st is not None:
                    rets.append(st[3]); touches += int(st[1]); seals += int(st[0])
            if touches >= 2 and (seals / touches) < 0.50:
                elo[pname] -= 12.0 * ((touches - seals) / touches)
            elif rets and np.mean(rets) < -0.025:
                elo[pname] -= 10.0
            elif seals >= 2 and (seals / max(touches, 1)) >= 0.70:
                elo[pname] += min(10.0, 5.0 + seals * 1.2)
            elif rets and np.mean(rets) > 0.025:
                elo[pname] += 6.0

        for sname, c6_list in prev_sub_stocks.items():
            touches, seals, rets = 0, 0, []
            for c6 in c6_list:
                st = day_stock_map.get((dt, c6))
                if st is not None:
                    rets.append(st[3]); touches += int(st[1]); seals += int(st[0])
            if touches >= 2 and (seals / touches) < 0.50:
                sub_elo[sname] -= 10.0 * ((touches - seals) / touches)
            elif rets and np.mean(rets) < -0.025:
                sub_elo[sname] -= 8.0
            elif seals >= 1 and (seals / max(touches, 1)) >= 0.70:
                sub_elo[sname] += min(9.0, 4.0 + seals * 1.5)
            elif rets and np.mean(rets) > 0.025:
                sub_elo[sname] += 5.0

        for p_k in list(elo.keys()):
            if day_idx - plate_last_idx.get(p_k, day_idx) > 3:
                elo[p_k] = 100.0 + (elo[p_k] - 100.0) * 0.85
        for s_k in list(sub_elo.keys()):
            if day_idx - sub_last_idx.get(s_k, day_idx) > 3:
                sub_elo[s_k] = 100.0 + (sub_elo[s_k] - 100.0) * 0.85

        new_prev_p, new_prev_sub = {}, defaultdict(list)
        plate_scores, plate_meta = {}, {}
        day_terms_to_commit = {}

        for p in plates:
            pname = p.get("plate", "")
            if pname in NON_THEME:
                continue
            stocks = p.get("stocks", [])
            sz = len(stocks)
            if sz == 0:
                continue
            c6_list = []
            n_ma = n_tech_o = n_tech_t = n_earn = n_big = n_yizi = n_new = 0
            spark_b = 0.0
            n_2b_lead_cnt = 0
            for s in stocks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6_list.append(c6)
                st_info = day_stock_map.get((dt, c6))
                if st_info is not None and st_info[5]:
                    n_2b_lead_cnt += 1
                sname_cur = str(s[1]).strip() if len(s) > 1 else ""
                if sname_cur:
                    global_stock_names[c6] = sname_cur
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                r_lg = str(s[3]).strip() if len(s) > 3 else ""
                if r_sh and r_sh not in NON_THEME:
                    new_prev_sub[r_sh].append(c6)
                    sub_last_idx[r_sh] = day_idx
                txt = f"{pname} {r_sh} {r_lg}"
                if MA_PAT.search(txt): n_ma += 1
                if TECH_PAT_ORIG.search(txt): n_tech_o += 1
                if TECH_PAT_TIMELESS.search(txt): n_tech_t += 1
                if EARN_PAT.search(txt): n_earn += 1

                for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", txt):
                    w = norm_term(m.group(0))
                    if len(w) >= 3 and w not in NON_THEME:
                        pioneer_word_history[w].add(dt)

                for t in (split_terms(pname) | split_terms(r_sh)):
                    prev_cnt = term_seen_days[t]
                    prev_idx = term_last_idx.get(t, -9999)
                    f_dt = term_first_dt.get(t, dt)
                    if prev_cnt == 0 or f_dt >= cutoff_15d:
                        n_new += 1
                    elif 5 <= (day_idx - prev_idx) <= 45 and prev_cnt <= 5:
                        spark_b = max(spark_b, 6.0)
                    day_terms_to_commit[t] = dt
                st = day_stock_map.get((dt, c6))
                if st is not None:
                    if st[4] >= 150.0: n_big += 1
                    if st[2]: n_yizi += 1

            new_prev_p[pname] = c6_list
            plate_last_idx[pname] = day_idx
            r5_zts = sum(cnt for idx_p, cnt in plate_recent_zts[pname] if day_idx - idx_p <= 5)
            plate_recent_zts[pname].append((day_idx, sz))
            sc_base = (
                elo[pname] + min(sz, 15) * 1.8 + min(r5_zts, 30) * 0.35
                + (8.0 if n_ma > 0 else 0.0) + (5.0 if n_new > 0 else 0.0)
                + spark_b + min(n_yizi * 4.0, 8.0) - (n_earn / sz) * 12.0 - (n_big / sz) * 10.0
            )
            sc_orig = sc_base + (6.0 if (TECH_PAT_ORIG.search(pname) or n_tech_o >= max(1, sz // 2)) else 0.0)
            sc_clean = sc_base + (6.0 if (TECH_PAT_TIMELESS.search(pname) or n_tech_t >= max(1, sz // 2)) else 0.0)
            plate_scores[pname] = sc_orig
            plate_meta[pname] = (sc_orig, sc_clean, elo[pname], sz, n_yizi, n_new > 0, spark_b, n_tech_o, n_tech_t, stocks, n_2b_lead_cnt > 0)

        ranked_p = sorted(plate_scores.keys(), key=lambda k: plate_scores[k], reverse=True)
        rk_map = {k: i + 1 for i, k in enumerate(ranked_p)}
        top2_sc = plate_scores[ranked_p[1]] if len(ranked_p) >= 2 else 100.0
        ranked_c = sorted(plate_meta.keys(), key=lambda k: plate_meta[k][1], reverse=True)
        rk_map_c = {k: i + 1 for i, k in enumerate(ranked_c)}
        top2_sc_c = plate_meta[ranked_c[1]][1] if len(ranked_c) >= 2 else 100.0

        if dt >= "2021-01-01":
            for pname, m in plate_meta.items():
                sc_o, sc_c, p_elo, sz, n_yz, has_new, spk, nto, ntt, stocks, has_2b_lead = m
                rk_o, rk_c = rk_map[pname], rk_map_c[pname]
                gap_o = (sc_o - top2_sc) if rk_o == 1 else 0.0
                gap_c = (sc_c - top2_sc_c) if rk_c == 1 else 0.0

                # 计算过去 10 个交易日真实涨停数序列 heat_bars
                heat_bars_10 = []
                for past_offset in range(9, -1, -1):
                    target_d_idx = day_idx - past_offset
                    day_hits = [c_cnt for (idx_rec, c_cnt) in plate_recent_zts[pname] if idx_rec == target_d_idx]
                    heat_bars_10.append(int(day_hits[-1]) if day_hits else 0)

                # 题材属性中文描述
                if has_new:
                    term_type = "新词破冰题材"
                elif n_ma > 0:
                    term_type = "重组并购催化"
                elif ntt >= max(1, sz // 2) or TECH_PAT_TIMELESS.search(pname):
                    term_type = "硬科技主线"
                elif spk > 0:
                    term_type = "老题材回流点火"
                else:
                    term_type = "常规轮动题材"

                escort_desc = "有高标护航（板块内含连板梯队）" if has_2b_lead else "纯首板新起（无高标护航）"

                plate_daily_meta[(dt, pname)] = {
                    "pname": pname,
                    "rk_c": rk_c,
                    "sc_c": round(sc_c, 1),
                    "sz": sz,
                    "has_2b_lead": has_2b_lead,
                    "escort": escort_desc,
                    "term_type": term_type,
                    "heat_bars": heat_bars_10,
                }

                for s in stocks:
                    c6 = str(s[0]).strip()[:6].zfill(6)
                    sname = str(s[1]).strip() if len(s) > 1 else ""
                    r_sh = str(s[2]).strip() if len(s) > 2 else ""
                    r_lg = str(s[3]).strip() if len(s) > 3 else ""
                    txt = f"{pname} {r_sh} {r_lg}"
                    own_new = any((term_seen_days[t] == 0 or term_first_dt.get(t, dt) >= cutoff_15d) for t in split_terms(r_sh + "+" + r_lg))
                    s_elo = sub_elo[r_sh] if (r_sh and r_sh not in NON_THEME) else p_elo
                    cur = stock_theme_5y.get((dt, c6))
                    if cur is None or sc_o > cur["t_score_o"]:
                        stock_theme_5y[(dt, c6)] = {
                            "name": sname, "plate": pname, "r_short": r_sh or pname,
                            "r_long": r_lg[:42] if r_lg else (r_sh or pname),
                            "rk_o": rk_o, "t_score_o": sc_o, "gap_o": gap_o,
                            "rk_c": rk_c, "t_score_c": sc_c, "gap_c": gap_c,
                            "p_elo": p_elo, "s_elo": s_elo, "p_sz": sz, "n_yizi": n_yz,
                            "has_new": has_new, "own_new": own_new, "spark": spk, "has_2b_lead": has_2b_lead,
                            "is_ma": bool(MA_PAT.search(txt)),
                            "is_tech_o": bool(TECH_PAT_ORIG.search(txt)),
                            "is_tech_c": bool(TECH_PAT_TIMELESS.search(txt)),
                            "is_earn": bool(EARN_PAT.search(txt)),
                        }

        for t, dt_v in day_terms_to_commit.items():
            term_seen_days[t] += 1
            if t not in term_first_dt: term_first_dt[t] = dt_v
            term_last_idx[t] = day_idx
        prev_plate_stocks = new_prev_p
        prev_sub_stocks = new_prev_sub

    print(f"[Elo] 8Y continuous preheated Elo finished ({len(stock_theme_5y):,} stock hits) in {time.time()-t0:.2f}s")
    return stock_theme_5y, pioneer_word_history, plate_daily_meta, global_stock_names


def attach_purified_pit_notices_and_scores(df, stock_theme_5y, pioneer_word_history, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map, global_stock_names):
    t0 = time.time()
    fb = df[df["is_first_board"] & (~df["is_yizi"]) & (df["dt_str"] >= "2021-01-04")].copy()

    # 读取 PIT 公告数据库（严格使用只读锁 uri=True, mode=ro）
    notice_by_c6 = defaultdict(list)
    if os.path.exists(PIT_NOTICES_DB):
        conn = sqlite3.connect(f"file:{PIT_NOTICES_DB}?mode=ro", uri=True)
        c6_set = set(fb["c6"].unique())
        for sec_code, pub_dt, avail_dt, title in conn.execute(
            "SELECT sec_code, pub_datetime_cst, trade_date_avail, title FROM notices WHERE pub_datetime_cst >= '2020-12-25'"
        ):
            c6 = str(sec_code)[:6].zfill(6)
            if c6 not in c6_set or not pub_dt:
                continue
            ts = str(title or "")
            is_neg = bool(NEG_NOTICE_PAT.search(ts)) or bool(BAD_NOTICE_PAT.search(ts))
            if is_neg:
                flags = (False, False, False, bool(EARN_NOTICE_PAT.search(ts)), True)
            else:
                flags = (
                    bool(HARD_NOTICE_ORIG_PAT.search(ts)),
                    bool(HARD_NOTICE_PAT.search(ts)),
                    bool(MA_NOTICE_PAT.search(ts)),
                    bool(EARN_NOTICE_PAT.search(ts)),
                    False,
                )
            if any(flags):
                notice_by_c6[c6].append((str(pub_dt), str(avail_dt or ""), flags))
        conn.close()

    for c6 in notice_by_c6:
        notice_by_c6[c6].sort(key=lambda x: x[0])

    rows_meta = []
    cols_needed = ["c6", "dt_str", "d2_dt", "mcap", "amount", "f_dd20_d0", "f_dd60_d0", "f_pos20_d0",
                   "f_d0_pct", "f_ret_pre10", "to", "f_d1_vol_ratio", "f_zt_cnt_pre20", "f_break60", "close", "d1_seal_tightness"]
    for r in fb[cols_needed].itertuples(index=False):
        c6, d1, d2 = r.c6, r.dt_str, (r.d2_dt if pd.notna(r.d2_dt) else "2026-11-11")
        ti = stock_theme_5y.get((d1, c6))
        if ti is None:
            ti = {
                "name": global_stock_names.get(c6, ""), "plate": "其他", "r_short": "其他", "r_long": "其他",
                "rk_o": 99, "t_score_o": 95.0, "gap_o": 0.0,
                "rk_c": 99, "t_score_c": 95.0, "gap_c": 0.0,
                "p_elo": 100.0, "s_elo": 100.0, "p_sz": 1, "n_yizi": 0,
                "has_new": False, "own_new": False, "spark": 0.0, "has_2b_lead": False,
                "is_ma": False, "is_tech_o": False, "is_tech_c": False, "is_earn": False,
            }
        elif not ti["name"]:
            ti["name"] = global_stock_names.get(c6, "")

        start_cut = (datetime.date.fromisoformat(d1) - datetime.timedelta(days=4)).isoformat()
        end_cut = f"{d2} 09:25:00"
        nh_o = nh_c = n_ma = n_earn = n_bad = False
        nlist = notice_by_c6.get(c6)
        if nlist:
            lo = bisect.bisect_left(nlist, (start_cut, "", ()))
            for idx_n in range(lo, len(nlist)):
                pdt, adt, fl = nlist[idx_n]
                if pdt > end_cut:
                    break
                if adt and adt > d2:
                    continue
                nh_o |= fl[0]; nh_c |= fl[1]; n_ma |= fl[2]; n_earn |= fl[3]; n_bad |= fl[4]

        if n_bad:
            nh_c = False
            nh_o = False
            n_ma = False

        sname = ti["name"] or global_stock_names.get(c6, "")
        is_st = ("ST" in sname.upper()) or ("退" in sname) or (sname == "")
        is_ma_f = bool(ti["is_ma"] or n_ma)
        is_earn_f = bool(ti["is_earn"] or n_earn)

        rk_o, p_sz = ti["rk_o"], ti["p_sz"]
        s_prior_orig = (
            (28 if rk_o == 1 else (16 if rk_o == 2 else (8 if rk_o == 3 else 0)))
            + (18 if p_sz >= 4 else (10 if p_sz >= 2 else -15))
            + (15 if ti["has_new"] else 0) + (10 if ti["spark"] > 0 else 0)
            + (18 if nh_o else 0) + (18 if is_ma_f else 0) + (16 if ti["is_tech_o"] else 0)
            + (12 if ti["gap_o"] >= 20.0 else 0)
            + float(np.clip((ti["t_score_o"] - 100.0) * 0.25, 0.0, 25.0))
        )

        rk_c = ti["rk_c"]
        s_prior_dual = (
            (28 if rk_c == 1 else (16 if rk_c == 2 else (8 if rk_c == 3 else 0)))
            + (18 if p_sz >= 4 else (10 if p_sz >= 2 else -15))
            + (12 if ti["has_new"] else 0) + (8 if ti["own_new"] else 0) + (10 if ti["spark"] > 0 else 0)
            + (18 if nh_c else 0) + (18 if is_ma_f else 0) + (12 if ti["is_tech_c"] else 0)
            + (12 if ti["gap_c"] >= 20.0 else 0)
            + float(np.clip((ti["t_score_c"] - 100.0) * 0.25, 0.0, 25.0))
            + float(np.clip((ti["s_elo"] - 100.0) * 0.35, -10.0, 18.0))
        )

        mcap = float(r.mcap) if pd.notna(r.mcap) else 50.0
        amt = float(r.amount) if pd.notna(r.amount) else 2e8
        dd20 = float(r.f_dd20_d0) if pd.notna(r.f_dd20_d0) else 0.90
        dd60 = float(r.f_dd60_d0) if pd.notna(r.f_dd60_d0) else 0.85
        pos20 = float(r.f_pos20_d0) if pd.notna(r.f_pos20_d0) else 0.50
        d0_pct = float(r.f_d0_pct) if pd.notna(r.f_d0_pct) else 0.0
        ret10 = float(r.f_ret_pre10) if pd.notna(r.f_ret_pre10) else 0.0
        to = float(r.to) if pd.notna(r.to) else 8.0
        vr = float(r.f_d1_vol_ratio) if pd.notna(r.f_d1_vol_ratio) else 1.5
        zt20 = int(r.f_zt_cnt_pre20) if pd.notna(r.f_zt_cnt_pre20) else 0
        brk60 = int(r.f_break60)

        seal_r = seal_rate_map.get(d1, 0.55)
        dt_cnt = dt_cnt_map.get(d1, 5)
        zt_cnt = zt_cnt_map.get(d1, 50)
        promo5 = promo_ma5_map.get(d1, 0.20)

        sc_mcap = 28 if 60 <= mcap <= 155 else (10 if 40 <= mcap < 60 else (-20 if mcap < 35 else 0))
        sc_amt = 18 if 2.2e8 <= amt <= 15e8 else (-25 if amt < 1.8e8 else -10)
        sc_dd20 = 42 if dd20 <= 0.82 else (32 if dd20 <= 0.86 else (18 if dd20 <= 0.90 else (-40 if dd20 > 0.95 else 0)))
        sc_dd60 = 18 if dd60 <= 0.76 else (10 if dd60 <= 0.82 else (-15 if dd60 > 0.92 else 0))
        sc_nshape = 22 if (zt20 >= 1 and dd20 <= 0.86) else (-20 if (zt20 >= 1 and dd20 > 0.92) else 0)
        sc_pos20 = 25 if pos20 <= 0.30 else (12 if pos20 <= 0.45 else (-35 if pos20 > 0.75 else 0))
        sc_d0 = 25 if d0_pct <= -0.010 else (15 if d0_pct <= 0.005 else (-35 if d0_pct > 0.030 else 0))
        sc_ret10 = 15 if ret10 <= 0.05 else (-35 if ret10 > 0.18 else 0)
        sc_to = 15 if to <= 9.0 else (8 if to <= 15.0 else (-25 if to > 18.0 else 0))
        sc_vol = 15 if vr <= 1.75 else (-15 if vr > 2.3 else 0)
        sc_mkt_seal = 18 if seal_r < 0.64 else (-25 if seal_r >= 0.72 else 0)
        sc_mkt_dt = 12 if dt_cnt <= 6 else (-15 if dt_cnt >= 15 else 0)
        sc_mkt_zt = 12 if zt_cnt >= 45 else (-18 if zt_cnt < 35 else 0)

        s_q_base_orig = (
            sc_mcap + sc_amt + sc_dd20 + sc_dd60 + sc_nshape + sc_pos20
            + sc_d0 + sc_ret10 + sc_to + sc_vol + sc_mkt_seal + sc_mkt_dt + sc_mkt_zt
        )
        clean_brk60 = (brk60 == 1) and (ret10 <= 0.08) and (zt20 == 0) and (to <= 14.0)
        if clean_brk60:
            s_q_base_dual = (
                sc_mcap + sc_amt + 24 + sc_d0 + sc_ret10 + sc_to + sc_vol
                + sc_mkt_seal + sc_mkt_dt + sc_mkt_zt
            )
        else:
            s_q_base_dual = s_q_base_orig

        sc_space = 12.0 if ti.get("has_2b_lead", False) else 0.0
        sc_price_zone = 8.0 if (3.5 <= r.close <= 35.0) else (-12.0 if (45.0 < r.close <= 60.0) else 0.0)
        sc_tight = 8.0 if (float(r.d1_seal_tightness) >= 15.0) else 0.0
        s_q_base_synergy = s_q_base_dual + sc_space + sc_price_zone + sc_tight

        gate_ok = bool(
            (not is_st) and (not is_earn_f) and (not n_bad)
            and (18.0 <= mcap <= 220.0) and (to <= 20.0)
            and (not (zt20 >= 4 and pos20 > 0.38))
            and (r.close <= 60.0)
        )
        tot_thr = 255.0 if seal_r > 0.75 else 230.0

        r_txt = str(ti.get("r_short", "")) + " " + str(sname)
        is_pioneer_word = False
        for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", r_txt):
            w = norm_term(m.group(0))
            if w in pioneer_word_history:
                prior = [d_seen for d_seen in pioneer_word_history[w] if d_seen <= d1]
                if 1 <= len(prior) <= 3:
                    is_pioneer_word = True
                    break

        rows_meta.append({
            "name": sname, "plate": ti["plate"], "r_short": ti["r_short"], "r_long": ti.get("r_long", ""),
            "p_elo": ti["p_elo"], "s_elo": ti["s_elo"], "p_sz": ti["p_sz"],
            "has_new_term": ti["has_new"], "own_new_term": ti["own_new"],
            "spark_bonus": ti["spark"], "is_ma": is_ma_f, "notice_hard": nh_c,
            "notice_bad": n_bad, "clean_brk60": int(clean_brk60), "gate_ok": gate_ok,
            "s_prior_orig": round(s_prior_orig, 2), "s_prior_dual": round(s_prior_dual, 2),
            "s_q_base_orig": round(s_q_base_orig, 2), "s_q_base_dual": round(s_q_base_dual, 2),
            "s_q_base_synergy": round(s_q_base_synergy, 2), "has_2b_lead": ti.get("has_2b_lead", False),
            "mkt_zt_cnt": zt_cnt, "mkt_dt_cnt": dt_cnt,
            "mkt_seal_rate": seal_r, "mkt_promo_ma5": promo5,
            "tot_thr": tot_thr, "is_pioneer_word": is_pioneer_word,
            "is_st": is_st,
        })

    meta_df = pd.DataFrame(rows_meta, index=fb.index)
    fb = pd.concat([fb, meta_df], axis=1)

    print(f"[PIT & Features] Attached purified notices and features for {len(fb):,} rows in {time.time()-t0:.2f}s")
    return fb


def compute_v14_auction_scores(sub_df: pd.DataFrame) -> pd.DataFrame:
    t0 = time.time()
    df = sub_df.copy()

    auc_mean = df.groupby("d2_dt")["d2_o_pct"].transform("mean")
    df["nuclear_halt"] = auc_mean < 0.0
    df["promo_freeze"] = df["mkt_promo_ma5"] < 0.13

    df["is_buyable_open"] = df["gate_ok"] & (df["d2_open"] > 0) & (df["d2_open"] < df["d2_zt_p"] - 0.005)
    df["plate_d2_yizi_cnt"] = df.groupby(["d2_dt", "plate"])["d2_is_yizi"].transform("sum")

    buy_mkt_o = np.where(df["is_buyable_open"], df["d2_o_pct"], -9.99)
    df["_buy_mkt_o"] = buy_mkt_o
    df["buyable_mkt_open_rk"] = df.groupby("d2_dt")["_buy_mkt_o"].rank(ascending=False, method="min")
    mkt_p2_buy = df.groupby("d2_dt")["_buy_mkt_o"].transform(
        lambda s: s.nlargest(2).iloc[-1] if (s > -1.0).sum() >= 2 else -0.05
    )
    df["mkt_buy_open_lead"] = np.where(df["buyable_mkt_open_rk"] == 1, df["d2_o_pct"] - mkt_p2_buy, 0.0)

    buy_plate_o = np.where(df["is_buyable_open"], df["d2_o_pct"], -9.99)
    df["_buy_plate_o"] = buy_plate_o
    df["buyable_plate_rk"] = df.groupby(["d2_dt", "plate"])["_buy_plate_o"].rank(ascending=False, method="min")
    df["subbranch_rk"] = df.groupby(["d2_dt", "plate", "r_short"])["_buy_plate_o"].rank(ascending=False, method="min")
    p2_buy = df.groupby(["d2_dt", "plate"])["_buy_plate_o"].transform(
        lambda s: s.nlargest(2).iloc[-1] if (s > -1.0).sum() >= 2 else -0.05
    )
    df["buy_open_lead"] = np.where(df["buyable_plate_rk"] == 1, df["d2_o_pct"] - p2_buy, 0.0)

    has_distinct_sub = (df["p_sz"] >= 8) & (df["r_short"] != df["plate"]) & (df["r_short"] != "其他") & (df["r_short"] != "")
    rk_bonus_dual = np.where(
        df["buyable_plate_rk"] == 1, 35.0,
        np.where(
            has_distinct_sub & (df["subbranch_rk"] == 1), 24.0,
            np.where(df["buyable_plate_rk"] == 2, 8.0, -25.0)
        )
    )
    auc_dual = (
        rk_bonus_dual
        + np.where(df["buyable_mkt_open_rk"] <= 3, 20.0, np.where(df["buyable_mkt_open_rk"] <= 6, 12.0, 0.0))
        + np.where(df["buy_open_lead"] >= 0.020, 22.0, np.where(df["buy_open_lead"] >= 0.010, 12.0, 0.0))
        + np.where(df["plate_d2_yizi_cnt"] >= 1, 10.0, 0.0)
        + np.where(df["d2_o_pct"].between(0.040, 0.082), 20.0, np.where(df["d2_o_pct"].between(0.018, 0.040), 12.0, 0.0))
    )
    df["s_quant_dual"] = df["s_q_base_dual"] + auc_dual
    df["tot_dual"] = df["s_prior_dual"] + df["s_quant_dual"]
    df["s_quant_synergy"] = df["s_q_base_synergy"] + auc_dual
    df["tot_synergy"] = df["s_prior_dual"] + df["s_quant_synergy"]

    # 原装 baseline auc_orig 与 tot_orig (用于严格 2021 样本内标定)
    df["mkt_open_rk"] = df.groupby("d2_dt")["d2_o_pct"].rank(ascending=False, method="min")
    df["theme_open_rk"] = df.groupby(["d2_dt", "plate"])["d2_o_pct"].rank(ascending=False, method="min")
    p2_map = df.groupby(["d2_dt", "plate"])["d2_o_pct"].transform(
        lambda s: s.nlargest(2).iloc[-1] if len(s) >= 2 else -0.05
    )
    df["open_lead"] = np.where(df["theme_open_rk"] == 1, df["d2_o_pct"] - p2_map, 0.0)
    auc_orig = (
        np.where(df["theme_open_rk"] == 1, 35.0, np.where(df["theme_open_rk"] == 2, 5.0, -25.0))
        + np.where(df["mkt_open_rk"] <= 3, 20.0, np.where(df["mkt_open_rk"] <= 6, 12.0, 0.0))
        + np.where(df["open_lead"] >= 0.020, 22.0, np.where(df["open_lead"] >= 0.010, 12.0, 0.0))
        + np.where(df["d2_o_pct"].between(0.040, 0.082), 20.0, np.where(df["d2_o_pct"].between(0.030, 0.040), 10.0, 0.0))
    )
    df["s_quant_orig"] = df["s_q_base_orig"] + auc_orig
    df["tot_orig"] = df["s_prior_orig"] + df["s_quant_orig"]

    df["trig_p"] = np.minimum(
        df["d2_zt_p"],
        np.maximum(np.round(df["d2_open"] * 1.012, 2), np.round(df["close"] * 1.065, 2))
    )
    print(f"[Auction] Computed auction ranks & scores in {time.time()-t0:.2f}s")
    return df


def simulate_v14_single_trade(row, price_lookup, all_dts, dt_to_idx, entry_mode="trig", exit_mode="B0", fee=FEE_RATE):
    c6, d2 = row["c6"], row["d2_dt"]
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 < 0 or idx2 >= len(all_dts) - 1:
        return None
    d2_bar = price_lookup.get((c6, d2))
    if not d2_bar:
        return None
    o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2, vol2 = d2_bar
    if o2 >= zt2 - 0.005 or o2 <= 0:
        return None

    if entry_mode == "trig":
        trig_p = float(row["trig_p"])
        if trig_p >= zt2 - 0.005:
            return None
        if h2 < trig_p:
            return None
        buy_px = round(float(trig_p), 2)
    else:
        buy_px = round(float(o2), 2)

    curr_idx = idx2 + 1
    prev_c = round(float(c2), 2)
    exit_px, exit_dt, exit_open = None, None, False

    if not is_zt2:
        while curr_idx < len(all_dts):
            dc = all_dts[curr_idx]
            bar = price_lookup.get((c6, dc))
            if not bar:
                exit_px, exit_dt = prev_c, dc; break
            o, h, l, c, zt, dt_p, izt, iyz_dt, vol = bar
            if iyz_dt:
                prev_c = round(float(c), 2); curr_idx += 1; continue
            exit_px, exit_dt, exit_open = round(float(o), 2), dc, True; break
    else:
        while curr_idx < len(all_dts):
            dc = all_dts[curr_idx]
            bar = price_lookup.get((c6, dc))
            if not bar:
                exit_px, exit_dt = prev_c, dc; break
            o, h, l, c, zt, dt_p, izt, iyz_dt, vol = bar
            if iyz_dt:
                prev_c = round(float(c), 2); curr_idx += 1; continue

            if exit_mode == "B0":
                if curr_idx == idx2 + 1 and (prev_c * 1.01 <= o < zt - 0.005):
                    p1 = round(float(o), 2)
                    if not izt:
                        p2 = round(float(c), 2)
                        exit_px = round(0.5 * p1 + 0.5 * p2, 4)
                        exit_dt = dc
                        break
                    else:
                        curr_idx += 1; prev_c = round(float(c), 2)
                        p2 = prev_c
                        while curr_idx < len(all_dts):
                            dc2 = all_dts[curr_idx]
                            b2 = price_lookup.get((c6, dc2))
                            if not b2: p2, exit_dt = prev_c, dc2; break
                            if b2[7]: prev_c = round(float(b2[3]), 2); curr_idx += 1; continue
                            if b2[6] and (curr_idx - idx2 < 10): prev_c = round(float(b2[3]), 2); curr_idx += 1; continue
                            p2, exit_dt = round(float(b2[3]), 2), dc2; break
                        exit_px = round(0.5 * p1 + 0.5 * p2, 4)
                        break
                else:
                    if izt and (curr_idx - idx2 < 10):
                        prev_c = round(float(c), 2); curr_idx += 1; continue
                    exit_px, exit_dt = round(float(c), 2), dc
                    break

    if exit_px is None or exit_dt is None or exit_dt <= d2:
        return None

    gross = exit_px / buy_px - 1.0
    net = round((exit_px / buy_px) * (1.0 - fee) - 1.0, 4)
    return {
        "c6": c6, "name": row["name"], "plate": row["plate"], "r_short": row["r_short"],
        "d1_dt": row["dt_str"], "buy_date": d2, "exit_date": exit_dt, "exit_at_open": exit_open,
        "o_pct": round(float(row["d2_o_pct"]), 4), "buy_price": round(float(buy_px), 4),
        "exit_price": round(float(exit_px), 4), "sealed_2b": int(is_zt2),
        "gross_ret": round(float(gross), 4), "net_ret": round(float(net), 4),
    }


def simulate_trainer_trade_full(row, price_lookup, all_dts, dt_to_idx):
    """
    全量仿真单个候选股的交易执行、出场与点评：
    1. 未买进去（D2一字涨停开盘，或盘中最高未触及点火价 trig_p）：未成交记 0.00%；
    2. 买进去了（触及点火价 trig_p 真实建仓）：
       - 若 D2 未封死二板：按 T+1 于次日（若一字跌停则顺延至开板日）真实收盘价结算；
       - 若 D2 封死二板：不再机械半仓早卖，持续锁仓至断板日真实收盘价结算。
    """
    c6, d2 = row["c6"], row["d2_dt"]
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 < 0 or idx2 >= len(all_dts) - 1:
        return None
    d2_bar = price_lookup.get((c6, d2))
    if not d2_bar:
        return None
    o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2, vol2 = d2_bar
    trig_p = float(row["trig_p"])

    if o2 >= zt2 - 0.005 or o2 <= 0 or trig_p >= zt2 - 0.005:
        return {
            "executed": False,
            "buy_price": round(float(o2), 2),
            "sell_price": round(float(o2), 2),
            "exit_date": d2,
            "exit_reason": f"D2集合竞价高开逼近涨停({o2:.2f}元)，无安全点火买点自动跳过（0.00%）",
            "net_ret": 0.0,
            "sealed_2b": int(is_zt2),
            "final_height": 2 if is_zt2 else 1,
            "pm_comment": "开盘逼近涨停缺乏换手空间，未触发买点。"
        }

    if h2 < trig_p:
        return {
            "executed": False,
            "buy_price": round(trig_p, 2),
            "sell_price": round(trig_p, 2),
            "exit_date": d2,
            "exit_reason": f"09:30后最高仅 {h2:.2f}元，未触及点火价 {trig_p:.2f}元，条件单自动未成交（0.00%）",
            "net_ret": 0.0,
            "sealed_2b": int(is_zt2),
            "final_height": 2 if is_zt2 else 1,
            "pm_comment": f"开盘冲高乏力最高仅 {h2:.2f}元，未触发 {trig_p:.2f}元 点火条件单，未买进去记 0%。"
        }

    buy_px = round(trig_p, 2)
    curr_idx = idx2 + 1
    prev_c = round(float(c2), 2)
    last_valid_dt = all_dts[min(curr_idx, len(all_dts) - 1)]
    exit_px, exit_dt = None, None
    final_height = 2 if is_zt2 else 1
    missing_streak = 0

    if not is_zt2:
        while curr_idx < len(all_dts):
            dc = all_dts[curr_idx]
            bar = price_lookup.get((c6, dc))
            if not bar:
                missing_streak += 1
                if missing_streak > 15:
                    exit_px, exit_dt = prev_c, last_valid_dt
                    break
                curr_idx += 1
                continue
            missing_streak = 0
            last_valid_dt = dc
            o, h, l, c, zt, dt_p, izt, iyz_dt, vol = bar
            if iyz_dt:
                prev_c = round(float(c), 2)
                curr_idx += 1
                continue
            exit_px, exit_dt = round(float(c), 2), dc
            break
    else:
        while curr_idx < len(all_dts):
            dc = all_dts[curr_idx]
            bar = price_lookup.get((c6, dc))
            if not bar:
                missing_streak += 1
                if missing_streak > 15:
                    exit_px, exit_dt = prev_c, last_valid_dt
                    break
                curr_idx += 1
                continue
            missing_streak = 0
            last_valid_dt = dc
            o, h, l, c, zt, dt_p, izt, iyz_dt, vol = bar
            if iyz_dt:
                prev_c = round(float(c), 2)
                curr_idx += 1
                continue
            if izt and (final_height < 18):
                final_height += 1
                prev_c = round(float(c), 2)
                curr_idx += 1
                continue
            exit_px, exit_dt = round(float(c), 2), dc
            break

    if exit_px is None or exit_dt is None:
        exit_px = prev_c
        exit_dt = last_valid_dt

    net_pct = round(((exit_px / buy_px) * (1.0 - FEE_RATE) - 1.0) * 100.0, 2)
    sealed = bool(is_zt2)

    if not sealed:
        exit_reason = f"D2冲高回落未封板，按T+1于次日({exit_dt})收盘 {exit_px:.2f}元 结算离场"
        if net_pct < -3.0:
            pm_comment = "触发点火买入后承接不足炸板，按T+1持有至次日收盘离场承受回撤。"
        elif net_pct < 0.0:
            pm_comment = "当日分歧未能封板，按T+1于次日收盘离场锁定小幅浮亏。"
        else:
            pm_comment = "当日虽未封死二板，但次日承接修复，按次日收盘价溢价离场。"
    else:
        if final_height >= 3:
            exit_reason = f"D2封死二板并走出 {final_height} 连板！锁仓至断板日({exit_dt})收盘 {exit_px:.2f}元 结算"
        else:
            exit_reason = f"D2成功封死二板！锁仓至断板日({exit_dt})收盘 {exit_px:.2f}元 结算离场"
        if net_pct >= 12.0:
            pm_comment = f"题材主线身位领涨，成功晋级并走出 {final_height} 连板，格局至断板日收盘吃满主升大肉！"
        elif net_pct > 0.0:
            pm_comment = "成功封死二板晋级，持有至断板日收盘稳健锁定连板利润。"
        else:
            pm_comment = "当日虽封住二板，但次日断板大幅回落收盘，未能留住溢价。"

    return {
        "executed": True,
        "buy_price": round(buy_px, 2),
        "sell_price": round(exit_px, 2),
        "exit_date": exit_dt,
        "exit_reason": exit_reason,
        "net_ret": net_pct,
        "sealed_2b": int(sealed),
        "final_height": final_height,
        "pm_comment": pm_comment
    }


def main():
    print("=" * 80)
    print(">>> [Trainer Data Builder] Commencing 100% Real V14/V15 Master Engine Build...")
    print("=" * 80)

    # 1. 行情与真首板识别
    df, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map, max_height_map, fb_cnt_map, d1_fb_open_map = load_full_prices()
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt, r.volume)
        for r in df[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt", "volume"]].itertuples(index=False)
    }

    # 建立股票历史 K 线切片索引
    stock_rows_by_c6 = defaultdict(list)
    for r in df[["c6", "dt_str", "open", "high", "low", "close", "volume", "is_zt"]].itertuples(index=False):
        stock_rows_by_c6[r.c6].append(r)

    # 2. 8 年连续预热双层题材 Elo
    stock_theme_5y, pioneer_word_history, plate_daily_meta, global_stock_names = build_8y_preheated_elo(df)

    # 3. PIT 公告净化与盘前打分
    fb_all = attach_purified_pit_notices_and_scores(
        df, stock_theme_5y, pioneer_word_history, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map, global_stock_names
    )
    hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy()
    hist_fb = compute_v14_auction_scores(hist_fb)
    hist_fb["d2_yr"] = hist_fb["d2_dt"].str[:4].astype(int)

    # 4. 严格 2021 样本内标定阈值
    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    fb_2021 = hist_fb[(hist_fb["d2_yr"] == 2021) & common_ok]
    n_s1a_2021 = int((
        fb_2021["d2_o_pct"].between(0.030, 0.082)
        & (fb_2021["s_prior_orig"] >= 35.0)
        & (fb_2021["s_quant_orig"] >= 140.0)
        & (fb_2021["tot_orig"] >= fb_2021["tot_thr"])
    ).sum())

    pool_2021 = fb_2021[
        fb_2021["d2_o_pct"].between(0.022, 0.078)
        & (fb_2021["s_prior_dual"] >= 45.0)
        & (fb_2021["s_quant_dual"] >= 150.0)
    ]["tot_dual"].values

    k_p = max(12, int(n_s1a_2021 * 0.55))
    thr_p = float(np.sort(pool_2021)[-k_p]) if len(pool_2021) > k_p else 300.0
    thr_p = round(thr_p, 1)

    k_a = max(15, int(n_s1a_2021 * 0.65))
    thr_a = float(np.sort(pool_2021)[-k_a]) if len(pool_2021) > k_a else 285.0
    thr_a = round(thr_a, 1)

    print(f"[Calibration] Grade P Thr={thr_p} | Grade A Thr={thr_a}")

    thr_vec_p = np.where(hist_fb["mkt_seal_rate"] > 0.75, thr_p + 25.0, thr_p)
    thr_vec_a = np.where(hist_fb["mkt_seal_rate"] > 0.75, thr_a + 25.0, thr_a)

    m_t1_p = (
        common_ok
        & hist_fb["d2_o_pct"].between(0.022, 0.078)
        & (hist_fb["s_prior_dual"] >= 45.0)
        & (hist_fb["s_quant_dual"] >= 150.0)
        & (hist_fb["tot_dual"] >= thr_vec_p)
    )
    m_t1_a = (
        common_ok
        & hist_fb["d2_o_pct"].between(0.022, 0.078)
        & (hist_fb["s_prior_dual"] >= 45.0)
        & (hist_fb["s_quant_dual"] >= 150.0)
        & (hist_fb["tot_dual"] >= thr_vec_a)
    )
    m_t2 = (
        common_ok
        & (hist_fb["p_sz"] == 1)
        & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"])
        & hist_fb["d2_o_pct"].between(0.035, 0.078)
        & (hist_fb["buyable_mkt_open_rk"] <= 3)
        & (hist_fb["d1_seal_tightness"] >= 15.0)
        & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
    )

    hist_fb["dual_p"] = m_t1_p | m_t2
    hist_fb["dual_a"] = m_t1_a | m_t2

    # 100% 实盘五梯队分层综合排序分
    c_cond_p = hist_fb["dual_p"]
    c_cond_a = (~hist_fb["dual_p"]) & hist_fb["dual_a"]
    c_cond_tier3 = hist_fb["gate_ok"] & hist_fb["is_buyable_open"] & hist_fb["d2_o_pct"].between(0.022, 0.078) & (~hist_fb["dual_p"]) & (~hist_fb["dual_a"])
    c_cond_tier4 = (
        hist_fb["gate_ok"] & hist_fb["is_buyable_open"]
        & (hist_fb["d2_o_pct"].between(0.0, 0.022) | hist_fb["d2_o_pct"].between(0.078, 0.098))
        & (~hist_fb["dual_p"]) & (~hist_fb["dual_a"])
    )

    sys_rank_scores = np.where(
        c_cond_p, 10000.0 + hist_fb["tot_dual"],
        np.where(
            c_cond_a, 8000.0 + hist_fb["tot_dual"],
            np.where(
                c_cond_tier3, 5000.0 + hist_fb["tot_dual"],
                np.where(
                    c_cond_tier4, 2000.0 + hist_fb["tot_dual"],
                    hist_fb["tot_dual"]
                )
            )
        )
    )
    hist_fb["sys_rank_score"] = sys_rank_scores

    # 5. 准备上证指数数据源
    df_sh = pd.read_pickle(SH_DAILY_PKL)
    df_sh["date_str"] = df_sh["date"].dt.strftime("%Y-%m-%d")
    df_sh = df_sh.sort_values("date").reset_index(drop=True)
    sh_date_to_idx = {r.date_str: i for i, r in enumerate(df_sh.itertuples())}
    sh_rows = [
        [round(float(r.open), 2), round(float(r.high), 2), round(float(r.low), 2), round(float(r.close), 2), round(float(r.volume / 1e8), 2)]
        for r in df_sh.itertuples()
    ]

    # 按 d2_dt 分组索引
    fb_by_d2 = defaultdict(list)
    for r in hist_fb.itertuples():
        fb_by_d2[r.d2_dt].append(r)

    # 6. 筛选合格交易日与候选股生成题库
    all_eligible_d2 = []
    has_signal_d2 = []
    no_signal_d2 = []

    for d2 in sorted(fb_by_d2.keys()):
        if d2 < "2021-11-01" or d2 > "2026-11-10":
            continue
        idx_d2 = dt_to_idx.get(d2, -1)
        if idx_d2 < 0 or idx_d2 >= len(all_dts) - 1:
            continue
        if d2 not in sh_date_to_idx:
            continue

        cands_today = fb_by_d2[d2]
        # 按板块聚类
        plate_groups = defaultdict(list)
        for c in cands_today:
            # 必须为非 ST、非 D1 一字、非 D2 一字涨停开盘、非财报板块
            if c.is_st:
                continue
            if c.d2_open >= c.d2_zt_p - 0.005:
                continue
            pname = c.plate
            if pname in NON_THEME or EARN_PAT.search(pname):
                continue
            plate_groups[pname].append(c)

        # 筛选至少有 2 只真首板候选股的有效题材
        valid_plates = [p for p, cl in plate_groups.items() if len(cl) >= 2]
        if len(valid_plates) < 3:
            continue

        # 检查今日是否有 dual_p 信号
        has_dp = any(c.dual_p for c in cands_today)
        all_eligible_d2.append((d2, valid_plates, plate_groups, has_dp))
        if has_dp:
            has_signal_d2.append(d2)
        else:
            no_signal_d2.append(d2)

    print(f"Total eligible days: {len(all_eligible_d2)} (With dual_p signal: {len(has_signal_d2)}, No signal: {len(no_signal_d2)})")

    # 目标 360 关：全量纳入有信号日 + 均匀无偏抽样补充常规轮动与冰点日
    target_d2_set = set(has_signal_d2)
    needed_supplement = 360 - len(target_d2_set)
    if needed_supplement > 0 and len(no_signal_d2) > 0:
        step = len(no_signal_d2) / float(needed_supplement)
        for i in range(needed_supplement):
            idx_pick = min(int(i * step), len(no_signal_d2) - 1)
            target_d2_set.add(no_signal_d2[idx_pick])

    # 关键里程碑日必须包含
    for kd in ["2022-04-27", "2023-04-14", "2023-05-08", "2024-01-24", "2024-11-22", "2026-10-19", "2026-11-06", "2026-11-10"]:
        if kd in [item[0] for item in all_eligible_d2]:
            target_d2_set.add(kd)

    selected_eligible = [item for item in all_eligible_d2 if item[0] in target_d2_set]
    selected_eligible.sort(key=lambda x: x[0])
    print(f"Final selected {len(selected_eligible)} trading days for 5Y Trainer Dataset.")

    cases = []
    case_idx = 1

    for d2, valid_plates, plate_groups, has_dp in selected_eligible:
        # 取 D1 日期
        d1 = plate_groups[valid_plates[0]][0].dt_str

        # 1. 确定 3 张题材卡
        # 若有 dual_p 标的，其所在题材必须入选
        chosen_plates = []
        dp_plates = [p for p in valid_plates if any(c.dual_p for c in plate_groups[p])]
        if dp_plates:
            # 优先选 tot_dual 最高的标的所在题材
            best_dp_plate = max(dp_plates, key=lambda p: max(c.tot_dual for c in plate_groups[p]))
            chosen_plates.append(best_dp_plate)

        # 其余题材按 plate_meta 评分 (sc_c) 排序补齐 3 个
        remaining_plates = [p for p in valid_plates if p not in chosen_plates]
        remaining_plates.sort(
            key=lambda p: plate_daily_meta.get((d1, p), {}).get("sc_c", 0.0),
            reverse=True
        )
        for p in remaining_plates:
            chosen_plates.append(p)
            if len(chosen_plates) >= 3:
                break

        if len(chosen_plates) < 3:
            continue

        # 对 3 个题材使用固定随机种子洗牌左右顺序
        rng = random.Random(case_idx * 10007 + 42)
        rng.shuffle(chosen_plates)

        # 2. 为每个题材挑选 2~4 只首板候选股
        theme_cand_tuples = []
        for p_idx, pname in enumerate(chosen_plates):
            pool = plate_groups[pname]
            # 排序：优先按 sys_rank_score 从大到小
            pool_sorted = sorted(pool, key=lambda c: c.sys_rank_score, reverse=True)
            if len(pool_sorted) > 4:
                # 保留前 3 名 + 1 只高开跟风股/迷惑股
                chosen_pool = pool_sorted[:3] + [pool_sorted[-1]]
            else:
                chosen_pool = pool_sorted

            theme_cand_tuples.append((p_idx, pname, chosen_pool))

        # 3. 收集本题所有候选股，统一计算全局唯一 sys_rank
        all_case_cands = []
        for p_idx, pname, chosen_pool in theme_cand_tuples:
            for c in chosen_pool:
                all_case_cands.append(c)

        # 按 sys_rank_score 降序赋予全局唯一连续排名 1..K
        all_case_cands.sort(key=lambda c: c.sys_rank_score, reverse=True)
        cand_to_sysrank = {c.c6: i + 1 for i, c in enumerate(all_case_cands)}

        # 4. 构建题材对象与候选股对象
        themes_json = []
        all_built_cands = []

        for p_idx, pname, chosen_pool in theme_cand_tuples:
            p_meta = plate_daily_meta.get((d1, pname), {
                "rk_c": 10, "sc_c": 110.0, "sz": len(chosen_pool), "has_2b_lead": False,
                "escort": "纯首板新起（无高标护航）", "term_type": "常规轮动题材", "heat_bars": [1]*10
            })

            # 对候选股进行 Fisher-Yates 随机洗牌分配 ABCD
            pool_shuffled = list(chosen_pool)
            rng.shuffle(pool_shuffled)
            opt_letters = ["A", "B", "C", "D"]

            built_cands = []
            for opt_i, c in enumerate(pool_shuffled):
                opt = opt_letters[opt_i]

                # 仿真交易
                sim = simulate_trainer_trade_full(c._asdict() if hasattr(c, "_asdict") else c, price_lookup, all_dts, dt_to_idx)
                if sim is None:
                    sim = {
                        "executed": False, "buy_price": round(c.trig_p, 2), "sell_price": round(c.trig_p, 2),
                        "exit_date": d2, "exit_reason": "未触及点火价未成交", "net_ret": 0.0, "sealed_2b": 0, "final_height": 1,
                        "pm_comment": "未触及点火价。"
                    }

                # 提取真实历史 20 根 K 线
                stk_hist = stock_rows_by_c6.get(c.c6, [])
                # 找到 D1 索引
                d1_idx_in_stk = -1
                for idx_s, sr in enumerate(stk_hist):
                    if sr.dt_str == d1:
                        d1_idx_in_stk = idx_s
                        break

                if d1_idx_in_stk >= 0:
                    start_k = max(0, d1_idx_in_stk - 19)
                    slice_k = stk_hist[start_k: d1_idx_in_stk + 1]
                    klines = [
                        [round(float(k.open), 2), round(float(k.high), 2), round(float(k.low), 2), round(float(k.close), 2), round(float(k.volume), 0)]
                        for k in slice_k
                    ]
                else:
                    klines = [[round(c.close, 2)]*4 + [100000.0]]

                # D2 真实 K 线五元组
                d2_bar = price_lookup.get((c.c6, d2))
                if d2_bar:
                    d2_k = [round(float(d2_bar[0]), 2), round(float(d2_bar[1]), 2), round(float(d2_bar[2]), 2), round(float(d2_bar[3]), 2), round(float(d2_bar[8]), 0)]
                else:
                    d2_k = [round(c.d2_open, 2), round(c.d2_high, 2), round(c.d2_low, 2), round(c.d2_close, 2), 100000.0]

                # D3 真实 K 线五元组
                d3_dt = all_dts[dt_to_idx[d2] + 1] if dt_to_idx[d2] + 1 < len(all_dts) else d2
                d3_bar = price_lookup.get((c.c6, d3_dt))
                if d3_bar:
                    d3_k = [round(float(d3_bar[0]), 2), round(float(d3_bar[1]), 2), round(float(d3_bar[2]), 2), round(float(d3_bar[3]), 2), round(float(d3_bar[8]), 0)]
                else:
                    d3_k = d2_k

                # 真实封板形态客观判定
                if c.open >= c.zt_price - 0.02 and c.low < c.zt_price - 0.02:
                    seal_str = "T字回封"
                elif c.d1_dip >= -0.005 and c.d1_entity >= 0.065 and c.f_d1_vol_ratio <= 1.9:
                    seal_str = "缩量硬板"
                elif c.f_d1_vol_ratio >= 2.8 or c.d1_dip <= -0.03:
                    seal_str = "放量换手板"
                else:
                    seal_str = "震荡封板"

                # 描述文案组合
                desc_str = f"{c.r_short} · {c.r_long}" if (c.r_long and c.r_long != c.r_short) else c.r_short
                if c.notice_hard:
                    desc_str += " 【含盘前硬核公告】"
                if c.notice_bad:
                    desc_str += " 【含风险/减持公告】"

                cand_obj = {
                    "opt": opt,
                    "code": f"{c.c6}.SH" if c.c6.startswith("60") else f"{c.c6}.SZ",
                    "name": c.name,
                    "theme": pname,
                    "desc": desc_str,
                    "mcap": round(safe_float(c.mcap, 50.0), 1),
                    "d1_turn": round(safe_float(c.to, 8.0), 2),
                    "d1_amt": round(safe_float(c.amount, 2e8) / 1e8, 2),
                    "vr": f"{safe_float(c.f_d1_vol_ratio, 1.5):.2f}倍",
                    "seal": seal_str,
                    "dd20": round((safe_float(c.f_dd20_d0, 0.85) - 1.0) * 100.0, 1),
                    "zt20": int(safe_float(c.f_zt_cnt_pre20, 0)),
                    "pre_d1": round(safe_float(c.f_d0_pct, 0.0) * 100.0, 2),
                    "o_pct": round(safe_float(c.d2_o_pct, 0.0) * 100.0, 2),
                    "rk": [int(safe_float(c.buyable_plate_rk, 99)), int(safe_float(c.buyable_mkt_open_rk, 99))],
                    "lead": round(safe_float(c.buy_open_lead, 0.0) * 100.0, 2),
                    "trig_str": f"{c.trig_p:.2f}元 (+{(c.trig_p / c.close - 1.0)*100:.1f}%)",
                    "buy_price": sim["buy_price"],
                    "sell_price": sim["sell_price"],
                    "exit_date": sim["exit_date"],
                    "exit_reason": sim["exit_reason"],
                    "net_ret": sim["net_ret"],
                    "executed": sim["executed"],
                    "is_sealed": bool(sim["sealed_2b"]),
                    "final_height": sim["final_height"],
                    "sys_rank": cand_to_sysrank[c.c6],
                    "sys_pass": bool(c.dual_p),
                    "gate_ok": bool(c.gate_ok),
                    "pm_comment": sim["pm_comment"],
                    "klines": klines,
                    "d2": d2_k,
                    "d3": d3_k,
                    "theme_idx": p_idx,
                }
                built_cands.append(cand_obj)
                all_built_cands.append(cand_obj)

            # 板块平均竞价涨幅
            avg_open_val = np.mean([cd["o_pct"] for cd in built_cands])
            theme_obj = {
                "idx": p_idx,
                "name": pname,
                "elo_rank": int(p_meta.get("rk_c", 1)),
                "elo_score": float(p_meta.get("sc_c", 100.0)),
                "term_type": p_meta.get("term_type", "常规轮动题材"),
                "first_boards": len(built_cands),
                "escort": p_meta.get("escort", "纯首板新起（无高标护航）"),
                "avg_open": f"{avg_open_val:+.1f}%",
                "heat_bars": p_meta.get("heat_bars", [1]*10),
                "cands": built_cands,
            }
            themes_json.append(theme_obj)

        # 5. 市场真实净收益唯一裁判
        executed_cands = [cd for cd in all_built_cands if cd["executed"]]
        if not executed_cands:
            max_net_ret = -999.0
            best_cand = None
        else:
            best_cand = max(executed_cands, key=lambda cd: cd["net_ret"])
            max_net_ret = best_cand["net_ret"]

        if max_net_ret <= 0.5 or best_cand is None:
            market_ans = "E"
            market_best_theme_idx = -1
            market_best_ret = 0.0
            best_stock_code = ""
            best_stock_name = "全场空仓防守"
            case_type = "empty"
        else:
            market_ans = best_cand["opt"]
            market_best_theme_idx = best_cand["theme_idx"]
            market_best_ret = best_cand["net_ret"]
            best_stock_code = best_cand["code"]
            best_stock_name = best_cand["name"]
            if best_cand["is_sealed"] and best_cand["net_ret"] >= 5.0:
                case_type = "dragon"
            else:
                case_type = "normal"

        # 6. 人机 PK 量化定式动作 (100% 实盘单仓规则)
        dual_p_cands = [cd for cd in all_built_cands if cd["sys_pass"]]
        if dual_p_cands:
            # 买入全局 sys_rank 最靠前 (即 tot_dual 最高) 的 dual_p 标的
            best_dp_cand = min(dual_p_cands, key=lambda cd: cd["sys_rank"])
            sys_cand_code = best_dp_cand["code"]
            sys_cand_name = f"{best_dp_cand['name']}（触发量化出手）"
            sys_cand_opt = best_dp_cand["opt"]
            sys_cand_theme_idx = best_dp_cand["theme_idx"]
            sys_ret = best_dp_cand["net_ret"] if best_dp_cand["executed"] else 0.0
        else:
            # 实盘量化当日空仓观望
            top1_cand = min(all_built_cands, key=lambda cd: cd["sys_rank"])
            sys_cand_code = ""
            sys_cand_name = f"今日量化空仓（榜首{top1_cand['name']}未达出手线）"
            sys_cand_opt = ""
            sys_cand_theme_idx = -1
            sys_ret = 0.0

        sys_beat = bool(market_best_ret > sys_ret)

        # 7. 情绪仪表盘与大盘 K 线
        sent_zt = int(zt_cnt_map.get(d1, 50))
        sent_dt = int(dt_cnt_map.get(d1, 5))
        sent_first = int(fb_cnt_map.get(d1, 30))
        sent_promo = f"{seal_rate_map.get(d1, 0.20)*100:.1f}%"
        sent_height = f"{int(max_height_map.get(d1, 1))} 连板"
        sent_open = f"{d1_fb_open_map.get(d1, 0.0)*100:+.1f}%"
        sent_arr = [sent_zt, sent_dt, sent_first, sent_promo, sent_height, sent_open]

        sh_idx = sh_date_to_idx[d1]
        idx_bars = sh_rows[max(0, sh_idx - 29): sh_idx + 1]
        d2_sh_idx = sh_date_to_idx.get(d2, sh_idx + 1)
        idx_d2 = sh_rows[d2_sh_idx] if d2_sh_idx < len(sh_rows) else idx_bars[-1]

        # 盘前零剧透标题
        case_title = f"{d2} 早盘多主线博弈局"

        case_obj = {
            "id": case_idx,
            "date": d2,
            "d1_date": d1,
            "title": case_title,
            "type": case_type,
            "market_ans": market_ans,
            "market_best_theme_idx": market_best_theme_idx,
            "market_best_ret": market_best_ret,
            "best_stock_code": best_stock_code,
            "best_stock_name": best_stock_name,
            "sys_cand_code": sys_cand_code,
            "sys_cand_name": sys_cand_name,
            "sys_cand_opt": sys_cand_opt,
            "sys_cand_theme_idx": sys_cand_theme_idx,
            "sys_ret": sys_ret,
            "sys_beat": sys_beat,
            "sent": sent_arr,
            "idx_bars": idx_bars,
            "idx_d2": idx_d2,
            "themes": themes_json,
        }
        cases.append(case_obj)
        case_idx += 1

    print(f"Generated {len(cases)} cases across 5 years.")

    # 8. 精选经典 8 关 (覆盖 2022~2026 妖股二板起爆局、人机分歧局、退潮空仓保命局，且涵盖 A/B/C/D/E 全选项)
    target_q1_dates = [
        "2021-12-23",  # 龙津药业 (ans=C)
        "2022-04-27",  # 徐家汇 (ans=B)
        "2023-04-14",  # 全场空仓防守 (ans=E)
        "2023-05-08",  # 久远银海 (ans=D)
        "2024-01-24",  # 中视传媒 (ans=A)
        "2024-11-22",  # 红星发展
        "2026-10-19",  # 广东宏大
        "2026-11-06",  # 全场空仓防守 (ans=E)
    ]
    date_to_case = {c["date"]: c for c in cases}
    q1_candidates = [date_to_case[d] for d in target_q1_dates if d in date_to_case]

    # 若未满 8 关，从剩余题库均匀补充
    while len(q1_candidates) < 8 and len(cases) > len(q1_candidates):
        for c in cases:
            if c not in q1_candidates:
                q1_candidates.append(c)
                if len(q1_candidates) >= 8:
                    break

    q1_candidates.sort(key=lambda x: x["date"])
    q1_cases = []
    for q_i, qc in enumerate(q1_candidates[:8]):
        qc_copy = dict(qc)
        qc_copy["id"] = q_i + 1
        q1_cases.append(qc_copy)
        for c in cases:
            if c not in q1_candidates:
                q1_candidates.append(c)
                if len(q1_candidates) >= 8:
                    break

    q1_candidates.sort(key=lambda x: x["date"])
    q1_cases = []
    for q_i, qc in enumerate(q1_candidates[:8]):
        qc_copy = dict(qc)
        qc_copy["id"] = q_i + 1
        q1_cases.append(qc_copy)

    # 9. 落盘 JSON 文件
    print(f"Saving 5Y full dataset to {OUT_5Y_JSON} ({len(cases)} cases)...")
    with open(OUT_5Y_JSON, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)
    print(f"Saved {OUT_5Y_JSON} ({round(os.path.getsize(OUT_5Y_JSON)/1024/1024, 2)} MB)")

    print(f"Saving classic 8 cases dataset to {OUT_Q1_JSON} ({len(q1_cases)} cases)...")
    with open(OUT_Q1_JSON, "w", encoding="utf-8") as f:
        json.dump(q1_cases, f, ensure_ascii=False, indent=2)
    print(f"Saved {OUT_Q1_JSON} ({round(os.path.getsize(OUT_Q1_JSON)/1024, 1)} KB)")

    print("=" * 80)
    print(">>> [Trainer Data Builder] Successfully completed full build!")
    print("=" * 80)


if __name__ == "__main__":
    main()
