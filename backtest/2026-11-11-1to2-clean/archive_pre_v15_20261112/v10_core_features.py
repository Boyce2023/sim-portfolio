#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
v10_core_features.py — Zero-Lookahead 5Y PIT Feature & Elo Engine (2021-2026)
100% absorbs fast_1to2_today.py's 6 core gems + Dual-Layer Sub-Theme Elo + Delisted DB + PIT Notices (<= D2 09:25:00).
"""
import os
import re
import json
import time
import sqlite3
import datetime
from collections import defaultdict, Counter

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT_DIR = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT_DIR}/sim-portfolio"
A_DAILY_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_5Y_PATH = f"{SIM_DIR}/data/kpl_plates_5y_2021_2026_complete.jsonl"
PIT_NOTICES_DB = f"{SIM_DIR}/data/cninfo_notices_5y_pit.db"

NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股"
}
MA_PAT = re.compile(r"(重组|收购|股权转让|实控人变更|控制权变更|资产注入|借壳|控股|整合|中标|重大合同)")
# Original fast_1to2_today.py TECH_PAT (tested alongside hindsight-free dynamic Elo/new-term version)
TECH_PAT_ORIG = re.compile(
    r"(AI|算力|机器人|芯片|半导体|光刻|低空|商业航天|卫星|太空|固态电池|量子|脑机|大模型|具身智能|"
    r"华为|鸿蒙|无人驾驶|智驾|游戏|影之刃|黑神话|CPO|光模块|液冷|HBM|数据要素|深海|核聚变)"
)
# Timeless broad growth/tech sector pattern (known before 2021: 科技/半导体/软件/新能源/军工/通信/智能制造)
TECH_PAT_TIMELESS = re.compile(
    r"(芯片|半导体|光刻|集成电路|软件|信创|云计算|大数据|人工智能|AI|机器人|智能制造|自动化|"
    r"通信|5G|光通信|卫星|航天|军工|锂电|光伏|储能|风电|氢能|新材料|消费电子|智能驾驶|无人驾驶)"
)
EARN_PAT = re.compile(r"(业绩|预增|扭亏|季报|年报|半年报|分红)")

HARD_NOTICE_PAT = re.compile(
    r"(重组|收购|股权转让|控制权|实控人变更|资产注入|借壳|重大合同|中标|战略合作|框架协议|投资设立)"
)
HARD_NOTICE_ORIG_PAT = re.compile(
    r"(重组|收购|股权转让|控制权|实控人变更|资产注入|借壳|重大合同|中标|战略合作|框架协议|投资设立|"
    r"算力|机器人|芯片|卫星|人工智能|固态电池|低空)"
)
MA_NOTICE_PAT = re.compile(r"(重组|收购|股权转让|控制权变更|实控人变更|资产注入|借壳|重大合同|中标)")
EARN_NOTICE_PAT = re.compile(r"(业绩预增|业绩快报|扭亏为盈|半年度业绩|年度业绩|季度业绩)")
BAD_NOTICE_PAT = re.compile(
    r"(减持|问询函|监管函|警示函|立案|风险提示|业绩预亏|亏损|计提资产减值|退市风险|终止上市|违规|质押|冻结)"
)


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


def load_full_5y_prices():
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn", "oshare"]
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2020-08-01"))).to_table().to_pandas()

    parts = [df_act]
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format="parquet")
        df_del = ds_del.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2020-08-01"))).to_table().to_pandas()
        parts.append(df_del)

    df = pd.concat(parts, ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    # Main board 10% limit stocks only (exclude 30/68/BJ)
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
    df["is_1to2_day"] = df["prev_zt"] & (~df["prev2_zt"])
    df["is_first_board"] = df["is_zt"] & (~df["prev_zt"])
    print(f"[Prices] Loaded {len(df):,} mainboard rows (incl. delisted) in {time.time()-t0:.2f}s")
    return df


def build_5y_elo_and_candidates(df: pd.DataFrame):
    t0 = time.time()
    g = df.groupby("c6")
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

    df["d2_dt"] = g["dt_str"].shift(-1)
    df["d2_open"] = g["open"].shift(-1)
    df["d2_high"] = g["high"].shift(-1)
    df["d2_low"] = g["low"].shift(-1)
    df["d2_close"] = g["close"].shift(-1)
    df["d2_o_pct"] = df["d2_open"] / df["close"] - 1.0
    df["d2_zt_p"] = np.floor(df["close"] * 1.10 * 100.0 + 0.5) / 100.0
    df["d2_is_zt"] = g["is_zt"].shift(-1).fillna(False)
    df["d2_is_yizi"] = g["is_yizi"].shift(-1).fillna(False)

    # Daily market sentiment (100% known at D1 15:00)
    all_dts = sorted(df["dt_str"].unique())
    dg = df.groupby("dt_str")
    zt_cnt_map = dg["is_zt"].sum().to_dict()
    dt_cnt_map = dg["is_dt"].sum().to_dict()
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

    # Fast lookup for Elo update
    kpl_days = [json.loads(ln) for ln in open(KPL_5Y_PATH, encoding="utf-8") if ln.strip()]
    kpl_days.sort(key=lambda x: x["date"])
    kpl_dt_set = {d["date"] for d in kpl_days}
    sub_df_kpl = df[df["dt_str"].isin(kpl_dt_set)][["dt_str", "c6", "is_zt", "touch_zt", "is_yizi", "pct", "mcap"]]
    day_stock_map = {
        (r.dt_str, r.c6): (r.is_zt, r.touch_zt, r.is_yizi, r.pct, r.mcap)
        for r in sub_df_kpl.itertuples(index=False)
    }

    elo = defaultdict(lambda: 100.0)
    sub_elo = defaultdict(lambda: 100.0)
    plate_recent_zts = defaultdict(list)
    plate_last_idx, sub_last_idx = {}, {}
    prev_plate_stocks, prev_sub_stocks = {}, {}
    term_seen_days = Counter()
    term_first_dt, term_last_idx = {}, {}
    stock_theme_5y = {}

    for day_idx, d_entry in enumerate(kpl_days):
        dt = d_entry["date"]
        cutoff_15d = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=15)).isoformat()
        plates = d_entry.get("plates", [])

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
            for s in stocks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6_list.append(c6)
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
            plate_meta[pname] = (sc_orig, sc_clean, elo[pname], sz, n_yizi, n_new > 0, spark_b, n_tech_o, n_tech_t, stocks)

        ranked_p = sorted(plate_scores.keys(), key=lambda k: plate_scores[k], reverse=True)
        rk_map = {k: i + 1 for i, k in enumerate(ranked_p)}
        top2_sc = plate_scores[ranked_p[1]] if len(ranked_p) >= 2 else 100.0
        ranked_c = sorted(plate_meta.keys(), key=lambda k: plate_meta[k][1], reverse=True)
        rk_map_c = {k: i + 1 for i, k in enumerate(ranked_c)}
        top2_sc_c = plate_meta[ranked_c[1]][1] if len(ranked_c) >= 2 else 100.0

        for pname, m in plate_meta.items():
            sc_o, sc_c, p_elo, sz, n_yz, has_new, spk, nto, ntt, stocks = m
            rk_o, rk_c = rk_map[pname], rk_map_c[pname]
            gap_o = (sc_o - top2_sc) if rk_o == 1 else 0.0
            gap_c = (sc_c - top2_sc_c) if rk_c == 1 else 0.0
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
                        "rk_o": rk_o, "t_score_o": sc_o, "gap_o": gap_o,
                        "rk_c": rk_c, "t_score_c": sc_c, "gap_c": gap_c,
                        "p_elo": p_elo, "s_elo": s_elo, "p_sz": sz, "n_yizi": n_yz,
                        "has_new": has_new, "own_new": own_new, "spark": spk,
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

    print(f"[Elo] Built 5Y Dual-Layer Elo & New-Terms across {len(kpl_days)} days ({len(stock_theme_5y):,} hits) in {time.time()-t0:.2f}s")
    return df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map
