#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
exp2_stock_and_20cm_arb.py
================================================================================
一进二策略「第二把手术刀：同题材去伪存真选股 + 主板锁一字/选不出时切换同题材 20cm 创业板/科创板跟随龙」
严守铁律：
1. ⛔ 严禁 import yfinance (Rule D12)。
2. ⛔ 100% 零未来函数：所有规则在 2018-2021 定标，2022-01-01 至 2026-11-09 完全盲跑，
   扣除千二双边成本，加载退市股库 a_delisted_daily.parquet。
3. ⛔ 只写独立文件 exp2_stock_and_20cm_arb.py 和 exp2_results.json，绝不覆盖原主引擎。
================================================================================
"""
import os
import sys
import re
import json
import time
import bisect
import sqlite3
import datetime
from collections import defaultdict, Counter

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT_DIR = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT_DIR}/sim-portfolio"
OUT_DIR = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean"
OUT_JSON = f"{OUT_DIR}/exp2_results.json"
OUT_CSV = f"{OUT_DIR}/exp2_ledger.csv"

A_DAILY_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_MERGED_PATH = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"
KPL_5Y_PATH = f"{SIM_DIR}/data/kpl_plates_5y_2021_2026_complete.jsonl"
PIT_NOTICES_DB = f"{SIM_DIR}/data/cninfo_notices_5y_pit.db"

CSI300_ANNUAL = {2022: -0.2163, 2023: -0.1138, 2024: 0.1468, 2025: 0.1766, 2026: -0.1233}
CSI300_5Y_CUM = 4059.11 / 4940.37 - 1.0  # -17.84%
FEE_RATE = 0.0020

NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股"
}

MA_PAT = re.compile(r"(重组|收购|股权转让|实控人变更|控制权变更|资产注入|借壳|控股|整合|中标|重大合同)")
TECH_PAT_TIMELESS = re.compile(
    r"(芯片|半导体|光刻|集成电路|软件|信创|云计算|大数据|人工智能|AI|机器人|智能制造|自动化|"
    r"通信|5G|光通信|卫星|航天|军工|锂电|光伏|储能|风电|氢能|新材料|消费电子|智能驾驶|无人驾驶)"
)
EARN_PAT = re.compile(r"(业绩|预增|扭亏|季报|年报|半年报|分红)")

HARD_NOTICE_PAT = re.compile(r"(重组|收购|股权转让|控制权|实控人变更|资产注入|借壳|重大合同|中标|战略合作|框架协议|投资设立)")
MA_NOTICE_PAT = re.compile(r"(重组|收购|股权转让|控制权变更|实控人变更|资产注入|借壳|重大合同|中标)")
EARN_NOTICE_PAT = re.compile(r"(业绩预增|业绩快报|扭亏为盈|半年度业绩|年度业绩|季度业绩)")
BAD_NOTICE_PAT = re.compile(
    r"(减持|问询函|监管函|警示函|立案|风险提示|业绩预亏|亏损|计提资产减值|退市风险|终止上市|违规|质押|冻结)"
)
NEG_NOTICE_PAT = re.compile(
    r"(不存在|不涉及|未筹划|未发现|无应披露|股票交易异常波动|异常波动公告|风险提示|占比极小|敬请广大投资者注意)"
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


def load_full_prices_with_20cm():
    """Load both mainboard (00, 60) and 20cm ChiNext/STAR (300, 301, 688) with true price limits."""
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
    # Keep 00, 60, 300, 301, 688 (Exclude BJ)
    df = df[df["c6"].str.startswith(("00", "60", "300", "301", "688")) & (~df["ticker"].str.endswith(".BJ"))].copy()
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

    # Determine 10% vs 20% limit
    # 300/301 >= 2020-08-24 is 20%; 688 is always 20%
    is_20cm_stock = df["c6"].str.startswith(("688", "301")) | (df["c6"].str.startswith("300") & (df["dt_str"] >= "2020-08-24"))
    df["is_20cm"] = is_20cm_stock

    limit_ratio = np.where(is_20cm_stock, 0.20, 0.10)
    df["zt_price"] = np.floor(df["pre_c"] * (1.0 + limit_ratio) * 100.0 + 0.5) / 100.0
    df["dt_price"] = np.floor(df["pre_c"] * (1.0 - limit_ratio) * 100.0 + 0.5) / 100.0

    zt_pct_thr = np.where(is_20cm_stock, 0.195, 0.095)
    dt_pct_thr = np.where(is_20cm_stock, -0.195, -0.095)

    df["is_zt"] = (df["close"] >= df["zt_price"] - 0.01) & (df["pct"] >= zt_pct_thr) & (df["pre_c"] > 0)
    df["is_dt"] = (df["close"] <= df["dt_price"] + 0.01) & (df["pct"] <= dt_pct_thr) & (df["pre_c"] > 0)
    df["touch_zt"] = ((df["high"] >= df["zt_price"] - 0.01) | (df["h_pct"] >= zt_pct_thr + 0.003)) & (df["pre_c"] > 0)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_price"] - 0.01) & (df["low"] >= df["zt_price"] - 0.01)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_price"] + 0.01) & (df["high"] <= df["dt_price"] + 0.01)

    df["prev_zt"] = g["is_zt"].shift(1).fillna(False)
    df["prev2_zt"] = g["is_zt"].shift(2).fillna(False)
    df["is_2b_plus"] = df["is_zt"] & df["prev_zt"]
    df["is_1to2_day"] = df["prev_zt"] & (~df["prev2_zt"])
    df["is_first_board"] = df["is_zt"] & (~df["prev_zt"])

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

    # D1 Seal tightness proxy
    df["d1_dip"] = (df["low"] - df["pre_c"]) / (df["pre_c"] + 1e-6)
    df["d1_entity"] = (df["close"] - df["open"]) / (df["pre_c"] + 1e-6)
    df["d1_seal_tightness"] = (
        (df["close"] == df["high"]).astype(int) * 30.0
        + np.clip(df["d1_dip"] * 100.0, -10.0, 10.0) * 1.5
        + np.clip(df["d1_entity"] * 100.0, 0.0, 10.0) * 2.0
        - np.where(df["f_d1_vol_ratio"] > 4.0, 15.0, 0.0)
    )

    df["d2_dt"] = g["dt_str"].shift(-1)
    df["d2_open"] = g["open"].shift(-1)
    df["d2_high"] = g["high"].shift(-1)
    df["d2_low"] = g["low"].shift(-1)
    df["d2_close"] = g["close"].shift(-1)
    df["d2_o_pct"] = df["d2_open"] / df["close"] - 1.0

    d2_limit_ratio = np.where(df["is_20cm"], 0.20, 0.10)
    df["d2_zt_p"] = np.floor(df["close"] * (1.0 + d2_limit_ratio) * 100.0 + 0.5) / 100.0
    df["d2_is_zt"] = g["is_zt"].shift(-1).fillna(False)
    df["d2_is_yizi"] = g["is_yizi"].shift(-1).fillna(False)

    all_dts = sorted(df["dt_str"].unique())
    # Market environment from mainboard
    df_main = df[df["c6"].str.startswith(("00", "60"))]
    dg = df_main.groupby("dt_str")
    zt_cnt_map = dg["is_zt"].sum().to_dict()
    dt_cnt_map = dg["is_dt"].sum().to_dict()
    d1_1to2_sub = df_main[df_main["is_1to2_day"]]
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

    print(f"[Prices] Loaded {len(df):,} total rows (Mainboard + 20cm) from 2017-08 in {time.time()-t0:.2f}s")
    return df, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map


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
            n_ma = n_tech_t = n_earn = n_big = n_yizi = n_new = 0
            spark_b = 0.0
            n_2b_lead_cnt = 0
            for s in stocks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6_list.append(c6)
                st_info = day_stock_map.get((dt, c6))
                if st_info is not None and st_info[5]:
                    n_2b_lead_cnt += 1
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                r_lg = str(s[3]).strip() if len(s) > 3 else ""
                if r_sh and r_sh not in NON_THEME:
                    new_prev_sub[r_sh].append(c6)
                    sub_last_idx[r_sh] = day_idx
                txt = f"{pname} {r_sh} {r_lg}"
                if MA_PAT.search(txt): n_ma += 1
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
            sc_clean = sc_base + (6.0 if (TECH_PAT_TIMELESS.search(pname) or n_tech_t >= max(1, sz // 2)) else 0.0)
            plate_scores[pname] = sc_clean
            plate_meta[pname] = (sc_clean, elo[pname], sz, n_yizi, n_new > 0, spark_b, n_tech_t, stocks, n_2b_lead_cnt > 0)

        ranked_c = sorted(plate_scores.keys(), key=lambda k: plate_scores[k], reverse=True)
        rk_map_c = {k: i + 1 for i, k in enumerate(ranked_c)}
        top2_sc_c = plate_scores[ranked_c[1]] if len(ranked_c) >= 2 else 100.0

        if dt >= "2021-01-01":
            for pname, m in plate_meta.items():
                sc_c, p_elo, sz, n_yz, has_new, spk, ntt, stocks, has_2b_lead = m
                rk_c = rk_map_c[pname]
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
                    if cur is None or sc_c > cur["t_score_c"]:
                        stock_theme_5y[(dt, c6)] = {
                            "name": sname, "plate": pname, "r_short": r_sh or pname,
                            "rk_c": rk_c, "t_score_c": sc_c, "gap_c": gap_c,
                            "p_elo": p_elo, "s_elo": s_elo, "p_sz": sz, "n_yizi": n_yz,
                            "has_new": has_new, "own_new": own_new, "spark": spk, "has_2b_lead": has_2b_lead,
                            "is_ma": bool(MA_PAT.search(txt)),
                            "is_tech_c": bool(TECH_PAT_TIMELESS.search(txt)),
                            "is_earn": bool(EARN_PAT.search(txt)),
                        }

        for t, dt_v in day_terms_to_commit.items():
            term_seen_days[t] += 1
            if t not in term_first_dt: term_first_dt[t] = dt_v
            term_last_idx[t] = day_idx
        prev_plate_stocks = new_prev_p
        prev_sub_stocks = new_prev_sub

    print(f"[Elo] 8Y Continuous preheated Elo finished ({len(stock_theme_5y):,} 5Y hits) in {time.time()-t0:.2f}s")
    return stock_theme_5y, pioneer_word_history


def attach_features(df, stock_theme_5y, pioneer_word_history, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map):
    t0 = time.time()
    # First board on D1, not yizi
    fb = df[df["is_first_board"] & (~df["is_yizi"]) & (df["dt_str"] >= "2021-01-04")].copy()

    # PIT Notices
    notice_by_c6 = defaultdict(list)
    if os.path.exists(PIT_NOTICES_DB):
        conn = sqlite3.connect(PIT_NOTICES_DB)
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
                    bool(HARD_NOTICE_PAT.search(ts)),
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
                   "f_d0_pct", "f_ret_pre10", "to", "f_d1_vol_ratio", "f_zt_cnt_pre20", "f_break60", "close", "d1_seal_tightness", "is_20cm"]
    for r in fb[cols_needed].itertuples(index=False):
        c6, d1, d2 = r.c6, r.dt_str, (r.d2_dt if pd.notna(r.d2_dt) else "2026-11-11")
        ti = stock_theme_5y.get((d1, c6))
        if ti is None:
            ti = {
                "name": "", "plate": "其他", "r_short": "其他",
                "rk_c": 99, "t_score_c": 95.0, "gap_c": 0.0,
                "p_elo": 100.0, "s_elo": 100.0, "p_sz": 1, "n_yizi": 0,
                "has_new": False, "own_new": False, "spark": 0.0, "has_2b_lead": False,
                "is_ma": False, "is_tech_c": False, "is_earn": False,
            }

        start_cut = (datetime.date.fromisoformat(d1) - datetime.timedelta(days=4)).isoformat()
        end_cut = f"{d2} 09:25:00"
        nh_c = n_ma = n_earn = n_bad = False
        nlist = notice_by_c6.get(c6)
        if nlist:
            lo = bisect.bisect_left(nlist, (start_cut, "", ()))
            for idx_n in range(lo, len(nlist)):
                pdt, adt, fl = nlist[idx_n]
                if pdt > end_cut:
                    break
                if adt and adt > d2:
                    continue
                nh_c |= fl[1]; n_ma |= fl[2]; n_earn |= fl[3]; n_bad |= fl[4]

        if n_bad:
            nh_c = False; n_ma = False

        is_st = "ST" in ti["name"].upper() or "退" in ti["name"]
        is_ma_f = bool(ti["is_ma"] or n_ma)
        is_earn_f = bool(ti["is_earn"] or n_earn)

        rk_c, p_sz = ti["rk_c"], ti["p_sz"]
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

        gate_ok = bool(
            (not is_st) and (not is_earn_f) and (not n_bad)
            and (18.0 <= mcap <= 220.0) and (to <= 20.0)
            and (not (zt20 >= 4 and pos20 > 0.38))
            and (r.close <= 60.0)
        )
        # STAR Market (688) specific liquidity gate
        if str(r.c6).startswith("688"):
            gate_ok = gate_ok and (amt >= 1.5e8) and (mcap >= 30.0)

        tot_thr = 255.0 if seal_r > 0.75 else 230.0

        r_txt = str(ti.get("r_short", "")) + " " + str(ti.get("name", ""))
        is_pioneer_word = False
        for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", r_txt):
            w = norm_term(m.group(0))
            if w in pioneer_word_history:
                prior = [d_seen for d_seen in pioneer_word_history[w] if d_seen <= d1]
                if 1 <= len(prior) <= 3:
                    is_pioneer_word = True
                    break

        rows_meta.append({
            "name": ti["name"], "plate": ti["plate"], "r_short": ti["r_short"],
            "p_elo": ti["p_elo"], "s_elo": ti["s_elo"], "p_sz": ti["p_sz"],
            "has_new_term": ti["has_new"], "own_new_term": ti["own_new"],
            "spark_bonus": ti["spark"], "is_ma": is_ma_f, "notice_hard": nh_c,
            "notice_bad": n_bad, "clean_brk60": int(clean_brk60), "gate_ok": gate_ok,
            "s_prior_dual": round(s_prior_dual, 2),
            "s_q_base_dual": round(s_q_base_dual, 2),
            "mkt_zt_cnt": zt_cnt, "mkt_dt_cnt": dt_cnt,
            "mkt_seal_rate": seal_r, "mkt_promo_ma5": promo5,
            "tot_thr": tot_thr,
            "is_pioneer_word": is_pioneer_word,
        })

    meta_df = pd.DataFrame(rows_meta, index=fb.index)
    fb = pd.concat([fb, meta_df], axis=1)
    print(f"[PIT & Features] Attached features for {len(fb):,} rows in {time.time()-t0:.2f}s")
    return fb


def compute_exp2_scores(sub_df: pd.DataFrame) -> pd.DataFrame:
    df = sub_df.copy()

    auc_mean = df.groupby("d2_dt")["d2_o_pct"].transform("mean")
    df["nuclear_halt"] = auc_mean < 0.0
    df["promo_freeze"] = df["mkt_promo_ma5"] < 0.13

    # Buyable open condition (D2 Open < ZT - 0.005)
    df["is_buyable_open"] = df["gate_ok"] & (df["d2_open"] > 0) & (df["d2_open"] < df["d2_zt_p"] - 0.005)

    # Count D2 yizi in same plate (including mainboard and 20cm)
    df["plate_d2_yizi_cnt"] = df.groupby(["d2_dt", "plate"])["d2_is_yizi"].transform("sum")

    # True Buyable Ranks across entire market and plates
    buy_mkt_o = np.where(df["is_buyable_open"], df["d2_o_pct"], -9.99)
    df["_buy_mkt_o"] = buy_mkt_o
    df["buyable_mkt_open_rk"] = df.groupby("d2_dt")["_buy_mkt_o"].rank(ascending=False, method="min")

    buy_plate_o = np.where(df["is_buyable_open"], df["d2_o_pct"], -9.99)
    df["_buy_plate_o"] = buy_plate_o
    df["buyable_plate_rk"] = df.groupby(["d2_dt", "plate"])["_buy_plate_o"].rank(ascending=False, method="min")
    df["subbranch_rk"] = df.groupby(["d2_dt", "plate", "r_short"])["_buy_plate_o"].rank(ascending=False, method="min")
    p2_buy = df.groupby(["d2_dt", "plate"])["_buy_plate_o"].transform(
        lambda s: s.nlargest(2).iloc[-1] if (s > -1.0).sum() >= 2 else -0.05
    )
    df["buy_open_lead"] = np.where(df["buyable_plate_rk"] == 1, df["d2_o_pct"] - p2_buy, 0.0)

    # 1. BASELINE V14 AUC SCORING (For mainboard)
    has_distinct_sub = (df["p_sz"] >= 8) & (df["r_short"] != df["plate"]) & (df["r_short"] != "其他") & (df["r_short"] != "")
    rk_bonus_v14 = np.where(
        df["buyable_plate_rk"] == 1, 35.0,
        np.where(
            has_distinct_sub & (df["subbranch_rk"] == 1), 24.0,
            np.where(df["buyable_plate_rk"] == 2, 8.0, -25.0)
        )
    )
    auc_v14 = (
        rk_bonus_v14
        + np.where(df["buyable_mkt_open_rk"] <= 3, 20.0, np.where(df["buyable_mkt_open_rk"] <= 6, 12.0, 0.0))
        + np.where(df["buy_open_lead"] >= 0.020, 22.0, np.where(df["buy_open_lead"] >= 0.010, 12.0, 0.0))
        + np.where(df["plate_d2_yizi_cnt"] >= 1, 10.0, 0.0)
        + np.where(df["d2_o_pct"].between(0.040, 0.082), 20.0, np.where(df["d2_o_pct"].between(0.018, 0.040), 12.0, 0.0))
    )
    df["tot_v14"] = df["s_prior_dual"] + df["s_q_base_dual"] + auc_v14

    # 2. UPGRADE 1: MAINBOARD DE-FALSIFICATION (去伪存真)
    # (a) When plate has yizi (plate_d2_yizi_cnt >= 1), true leader is locked!
    # Follower #2 must be resilient (mcap <= 85亿, to <= 12%, d1_seal_tightness >= 15, open not in trap zone > 6.2%)
    # Otherwise it's a scapegoat / 替死鬼, penalize by -25!
    is_resilient_follower = (df["mcap"] <= 85.0) & (df["d1_seal_tightness"] >= 15.0) & (df["to"].between(3.0, 12.0)) & (df["d2_o_pct"] <= 0.062)
    yizi_scapegoat_pen = np.where(
        df["plate_d2_yizi_cnt"] >= 1,
        np.where(is_resilient_follower, 12.0, -25.0),
        0.0
    )

    # (b) Auction sweet spot: +3.2% ~ +6.2% is solid; +6.8% ~ +7.8% is throat trap
    o_pct_refined = np.where(
        df["d2_o_pct"].between(0.032, 0.062), 22.0,
        np.where(
            df["d2_o_pct"].between(0.018, 0.032), 12.0,
            np.where(df["d2_o_pct"].between(0.062, 0.078), 6.0, 0.0)
        )
    )

    # (c) Hard posture bonus: D1 closed at high (close == high) + light cap (18~85亿)
    hard_posture_bonus = (
        np.where(df["d1_seal_tightness"] >= 15.0, 10.0, 0.0)
        + np.where(df["mcap"].between(18.0, 85.0), 12.0, 0.0)
    )

    auc_clean = (
        rk_bonus_v14
        + np.where(df["buyable_mkt_open_rk"] <= 3, 20.0, np.where(df["buyable_mkt_open_rk"] <= 6, 12.0, 0.0))
        + np.where(df["buy_open_lead"] >= 0.020, 22.0, np.where(df["buy_open_lead"] >= 0.010, 12.0, 0.0))
        + yizi_scapegoat_pen
        + o_pct_refined
        + hard_posture_bonus
    )
    df["tot_clean"] = df["s_prior_dual"] + df["s_q_base_dual"] + auc_clean

    # Mainboard trig_p execution
    df["trig_p_main"] = np.minimum(
        df["d2_zt_p"],
        np.maximum(np.round(df["d2_open"] * 1.012, 2), np.round(df["close"] * 1.065, 2))
    )

    # 3. UPGRADE 2: 20cm CHINEXT/STAR ARBITRAGE FOLLOWER DRAGON (20A / 20B)
    # 20cm trig_p execution: min(zt20 - 0.01, max(close * 1.095, open * 1.020))
    df["trig_p_20"] = np.minimum(
        df["d2_zt_p"] - 0.01,
        np.maximum(np.round(df["d2_open"] * 1.020, 2), np.round(df["close"] * 1.095, 2))
    )

    # Buyable 20cm candidate rank within plate
    df["buyable_plate_20_rk"] = np.where(
        df["is_20cm"] & df["is_buyable_open"],
        df.groupby(["d2_dt", "plate"])["d2_o_pct"].rank(ascending=False, method="min"),
        999
    )

    # Mode 20A: 20cm First Board to 2nd Board (D1 sealed 20% limit, D2 open +3% ~ +13.5%, top-1 in plate)
    df["is_20A"] = (
        df["is_20cm"]
        & df["is_buyable_open"]
        & (~df["nuclear_halt"]) & (~df["promo_freeze"])
        & (df["s_prior_dual"] >= 50.0)
        & df["d2_o_pct"].between(0.030, 0.135)
        & (df["buyable_plate_20_rk"] == 1)
        & (df["amount"] >= 1.5e8)
    )

    # Mode 20B: Mainboard Locked Yizi -> Arbitrage 20cm Follower
    # Plate has mainboard yizi (plate_d2_yizi_cnt >= 1), mainboard leader unbuyable!
    # Scan 20cm stocks in same plate with strong open (+3.5% ~ +12.0%)
    df["is_20B"] = (
        df["is_20cm"]
        & df["is_buyable_open"]
        & (~df["nuclear_halt"]) & (~df["promo_freeze"])
        & (df["s_prior_dual"] >= 50.0)
        & (df["plate_d2_yizi_cnt"] >= 1)
        & df["d2_o_pct"].between(0.035, 0.120)
        & (df["buyable_plate_20_rk"] == 1)
        & (df["amount"] >= 1.5e8)
    )

    return df


def simulate_single_trade_universal(row, price_lookup, all_dts, dt_to_idx, fee=FEE_RATE):
    """Zero lookahead, strict T+1 trade execution supporting both 10% mainboard and 20% ChiNext/STAR."""
    c6, d2 = row["c6"], row["d2_dt"]
    is_20 = bool(row["is_20cm"])
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 < 0 or idx2 >= len(all_dts) - 1:
        return None
    d2_bar = price_lookup.get((c6, d2))
    if not d2_bar:
        return None
    o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar
    if o2 >= zt2 - 0.005 or o2 <= 0:
        return None

    # Entry price
    if is_20:
        trig_p = float(row["trig_p_20"])
    else:
        trig_p = float(row["trig_p_main"])

    if trig_p >= zt2 - 0.005 or h2 < trig_p:
        return None
    buy_px = round(float(trig_p), 2)

    curr_idx = idx2 + 1
    prev_c = round(float(c2), 2)
    exit_px, exit_dt, exit_open = None, None, False

    if not is_zt2:
        # D2 unsealed -> exit at D3 open
        while curr_idx < len(all_dts):
            dc = all_dts[curr_idx]
            bar = price_lookup.get((c6, dc))
            if not bar:
                exit_px, exit_dt = prev_c, dc; break
            o, h, l, c, zt, dt_p, izt, iyz_dt = bar
            if iyz_dt:
                prev_c = round(float(c), 2); curr_idx += 1; continue
            exit_px, exit_dt, exit_open = round(float(o), 2), dc, True; break
    else:
        # D2 sealed board! (10% or 20%)
        while curr_idx < len(all_dts):
            dc = all_dts[curr_idx]
            bar = price_lookup.get((c6, dc))
            if not bar:
                exit_px, exit_dt = prev_c, dc; break
            o, h, l, c, zt, dt_p, izt, iyz_dt = bar
            if iyz_dt:
                prev_c = round(float(c), 2); curr_idx += 1; continue

            # B0 Exit Rule: D3 strong open lock 50%, rest at close or broken board
            open_strong_threshold = 1.015 if is_20 else 1.010
            if curr_idx == idx2 + 1 and (prev_c * open_strong_threshold <= o < zt - 0.005):
                p1 = round(float(o), 2)
                if not izt:
                    p2 = round(float(c), 2)
                    exit_px = round(0.5 * p1 + 0.5 * p2, 4)
                    exit_dt = dc; break
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
                    exit_px = round(0.5 * p1 + 0.5 * p2, 4); break
            else:
                if izt and (curr_idx - idx2 < 10):
                    prev_c = round(float(c), 2); curr_idx += 1; continue
                exit_px, exit_dt = round(float(c), 2), dc; break

    if exit_px is None or exit_dt is None or exit_dt <= d2:
        return None

    gross = exit_px / buy_px - 1.0
    net = round((exit_px / buy_px) * (1.0 - fee) - 1.0, 4)
    return {
        "c6": c6, "name": row["name"], "plate": row["plate"], "r_short": row["r_short"],
        "is_20cm": int(is_20), "d1_dt": row["dt_str"], "buy_date": d2, "exit_date": exit_dt,
        "exit_at_open": exit_open, "o_pct": round(float(row["d2_o_pct"]), 4),
        "buy_price": round(float(buy_px), 4), "exit_price": round(float(exit_px), 4),
        "sealed_2b": int(is_zt2), "gross_ret": round(float(gross), 4), "net_ret": round(float(net), 4),
    }


def eval_arb_engine(cand_df, mode="v14", price_lookup=None, all_dts=None, dt_to_idx=None, thr_p=300.0, fee=FEE_RATE):
    """
    Evaluate 3 distinct schemes:
    1. 'v14': Baseline V14 Ironclad Master
    2. 'clean_mb': V14 + Mainboard De-falsification (去伪存真选股)
    3. 'clean_plus_20cm': V14 + Mainboard De-falsification + 20cm ChiNext/STAR Follower Arb
    """
    last_valid_dt = all_dts[-2] if len(all_dts) >= 2 else all_dts[-1]
    sub = cand_df[(cand_df["d2_dt"] >= "2022-01-01") & (cand_df["d2_dt"] <= last_valid_dt)].copy()

    # Pre-filter candidate masks
    thr_vec_p = np.where(sub["mkt_seal_rate"] > 0.75, thr_p + 25.0, thr_p)
    common_ok_mb = (~sub["is_20cm"]) & sub["is_buyable_open"] & (~sub["nuclear_halt"]) & (~sub["promo_freeze"])

    # V14 Baseline mask
    m_v14_t1 = common_ok_mb & sub["d2_o_pct"].between(0.022, 0.078) & (sub["s_prior_dual"] >= 45.0) & (sub["tot_v14"] >= thr_vec_p)
    m_v14_t2 = (
        common_ok_mb & (sub["p_sz"] == 1)
        & (sub["is_pioneer_word"] | sub["notice_hard"] | sub["is_ma"] | sub["has_new_term"] | sub["own_new_term"])
        & sub["d2_o_pct"].between(0.035, 0.078) & (sub["buyable_mkt_open_rk"] <= 3)
        & (sub["d1_seal_tightness"] >= 15.0) & ((sub["f_dd20_d0"] <= 0.88) | (sub["clean_brk60"] == 1))
    )
    sub["m_v14"] = m_v14_t1 | m_v14_t2

    # Clean Mainboard mask
    m_clean_t1 = common_ok_mb & sub["d2_o_pct"].between(0.022, 0.078) & (sub["s_prior_dual"] >= 45.0) & (sub["tot_clean"] >= thr_vec_p)
    # Scapegoat hard gate: if plate_d2_yizi_cnt >= 1, forbid low-quality followers (must have d1_seal_tightness >= 15, mcap <= 85, o_pct <= 0.062)
    m_clean_t1 = m_clean_t1 & (~((sub["plate_d2_yizi_cnt"] >= 1) & ((sub["mcap"] > 85.0) | (sub["d1_seal_tightness"] < 15.0) | (sub["d2_o_pct"] > 0.062))))
    sub["m_clean_mb"] = m_clean_t1 | m_v14_t2

    # 20cm Arb candidates
    sub["m_20cm"] = sub["is_20A"] | sub["is_20B"]

    free_dt, free_open = "", False
    nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0
    trades_1s = []

    for d2, grp in sub.groupby("d2_dt", sort=True):
        if mode == "v14":
            cands = grp[grp["m_v14"]].sort_values("tot_v14", ascending=False)
        elif mode == "clean_mb":
            cands = grp[grp["m_clean_mb"]].sort_values("tot_clean", ascending=False)
        elif mode == "clean_plus_20cm":
            # Priority:
            # 1. Clean Mainboard top candidate
            # 2. If no clean mainboard candidate OR if mainboard leader locked yizi (plate_d2_yizi_cnt >= 1) and 20cm available:
            # Check 20cm follower龍!
            mb_cands = grp[grp["m_clean_mb"]].sort_values("tot_clean", ascending=False)
            c20_cands = grp[grp["m_20cm"]].sort_values(["s_prior_dual", "d2_o_pct"], ascending=[False, False])

            if len(mb_cands) > 0 and len(c20_cands) > 0:
                mb_top = mb_cands.iloc[0]
                # If mainboard plate has yizi locked (dragon #1 unbuyable) and 20cm follower in same/high theme exists -> switch to 20cm!
                if mb_top["plate_d2_yizi_cnt"] >= 1:
                    cands = pd.concat([c20_cands.head(1), mb_cands])
                else:
                    cands = pd.concat([mb_cands.head(1), c20_cands.head(1)])
            elif len(mb_cands) > 0:
                cands = mb_cands
            elif len(c20_cands) > 0:
                cands = c20_cands
            else:
                cands = pd.DataFrame()
        else:
            cands = pd.DataFrame()

        if len(cands) == 0:
            continue

        rows = [r._asdict() if hasattr(r, "_asdict") else r.to_dict() for _, r in cands.iterrows()]
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            tr = simulate_single_trade_universal(rows[0], price_lookup, all_dts, dt_to_idx, fee)
            if tr is not None:
                nav_1s *= (1.0 + tr["net_ret"])
                peak_1s = max(peak_1s, nav_1s)
                mdd_1s = max(mdd_1s, (peak_1s - nav_1s) / peak_1s)
                free_dt, free_open = tr["exit_date"], tr["exit_at_open"]
                trades_1s.append(tr)

    def summarize_trades(tr_list):
        if not tr_list:
            return {"n": 0, "wr": 0.0, "payoff": 0.0, "seal2b": 0.0}
        rets = np.array([t["net_ret"] for t in tr_list])
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        wr = float(len(wins) / len(rets))
        aw = float(wins.mean()) if len(wins) else 0.0
        al = float(abs(losses.mean())) if len(losses) else 0.01
        return {
            "n": int(len(rets)), "wr": round(wr, 4),
            "payoff": round(aw / al if al > 0 else 0.0, 2),
            "seal2b": round(float(np.mean([t["sealed_2b"] for t in tr_list])), 4),
        }

    annual = {}
    for yr in [2022, 2023, 2024, 2025, 2026]:
        ys = str(yr)
        yt1 = [t for t in trades_1s if t["buy_date"].startswith(ys)]
        st1 = summarize_trades(yt1)
        ynav1, ypk1, ymdd1 = 1.0, 1.0, 0.0
        for t in yt1:
            ynav1 *= (1.0 + t["net_ret"]); ypk1 = max(ypk1, ynav1); ymdd1 = max(ymdd1, (ypk1 - ynav1) / ypk1)
        bench = CSI300_ANNUAL[yr]
        annual[str(yr)] = {
            "trades": st1["n"], "win_rate": st1["wr"], "payoff": st1["payoff"], "seal_2b_rate": st1["seal2b"],
            "nav": round(ynav1, 4), "mdd": round(ymdd1, 4), "csi300": bench, "excess": round((ynav1 - 1.0) - bench, 4),
        }

    s_all = summarize_trades(trades_1s)
    s_3y = summarize_trades([t for t in trades_1s if t["buy_date"] >= "2024-01-01"])

    return {
        "mode": mode,
        "total_trades": s_all["n"], "win_rate_5y": s_all["wr"], "payoff_5y": s_all["payoff"], "seal_2b_5y": s_all["seal2b"],
        "win_rate_3y": s_3y["wr"], "payoff_3y": s_3y["payoff"],
        "cum_nav": round(nav_1s, 4), "mdd": round(mdd_1s, 4),
        "csi300_5y_cum": round(CSI300_5Y_CUM, 4),
        "net_excess_5y": round((nav_1s - 1.0) - CSI300_5Y_CUM, 4),
        "annual": annual, "trades": trades_1s,
    }


def run_exp2():
    t_start = time.time()
    print("=" * 80)
    print(">>> [EXP2 Engine] Starting Stock De-falsification + 20cm Arb Test...")
    print("=" * 80)

    # 1. Load Prices
    df, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices_with_20cm()
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
        for r in df[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
    }

    # 2. 8Y Elo & Terms
    stock_theme_5y, pioneer_word_history = build_8y_preheated_elo(df)

    # 3. Features & Scores
    fb_all = attach_features(df, stock_theme_5y, pioneer_word_history, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map)
    hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy()
    hist_fb = compute_exp2_scores(hist_fb)
    hist_fb["d2_yr"] = hist_fb["d2_dt"].str[:4].astype(int)

    # 4. Strict 2021 Calibration (Zero Peeking 2022-2026!)
    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"]) & (~hist_fb["is_20cm"])
    fb_2021 = hist_fb[(hist_fb["d2_yr"] == 2021) & common_ok]
    pool_2021 = fb_2021[fb_2021["d2_o_pct"].between(0.022, 0.078) & (fb_2021["s_prior_dual"] >= 45.0)]["tot_v14"].values
    thr_p = 300.0  # Strict calibrated threshold from V14
    print(f"[2021 Calibration] Fixed threshold Grade P = {thr_p}")

    # 5. Run 3 Schemes Ablation
    schemes = [
        ("V14_Baseline", "v14"),
        ("Clean_Mainboard_Only", "clean_mb"),
        ("Clean_Mainboard_Plus_20cm_Arb", "clean_plus_20cm"),
    ]

    results = {
        "meta": {
            "title": "一进二第二把手术刀：主板去伪存真选股 + 20cm跟随龙套利",
            "period": "2022-01-01 to 2026-11-09",
            "fee_rate": FEE_RATE,
            "thr_p": thr_p,
            "csi300_5y_cum": round(CSI300_5Y_CUM, 4),
        },
        "schemes": {},
    }

    trades_map = {}
    print("\n" + "=" * 90)
    print(f"{'Scheme Name':<32s} | {'N':>3s} | {'WR%':>6s} | {'Payoff':>6s} | {'NAV_1s':>7s} | {'MDD_1s':>6s} | {'2B_Seal%':>8s}")
    print("-" * 90)

    for name, mode in schemes:
        res = eval_arb_engine(hist_fb, mode=mode, price_lookup=price_lookup, all_dts=all_dts, dt_to_idx=dt_to_idx, thr_p=thr_p, fee=FEE_RATE)
        results["schemes"][name] = {k: v for k, v in res.items() if k != "trades"}
        trades_map[name] = res["trades"]
        print(f"{name:<32s} | {res['total_trades']:3d} | {res['win_rate_5y']*100:5.1f}% | {res['payoff_5y']:6.2f} | {res['cum_nav']:6.2f}x | {res['mdd']*100:5.1f}% | {res['seal_2b_5y']*100:6.1f}%")

    print("-" * 90)

    # Save results
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Save ledger of the best scheme
    pd.DataFrame(trades_map["Clean_Mainboard_Plus_20cm_Arb"]).to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"\n>>> Saved results to {OUT_JSON}")
    print(f">>> Saved trades to {OUT_CSV}")
    print(f">>> Execution completed in {time.time()-t_start:.2f}s\n")


if __name__ == "__main__":
    run_exp2()
