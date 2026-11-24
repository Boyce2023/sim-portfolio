#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
part2_data_builder.py
PIT 5-year (2021-11-15 ~ 2026-11-23) data & 50+ factor builder for:
  High-Heat Theme (rk_c <= 2 or sz >= 5) + Large-Cap (mcap >= 150亿, contrast >= 250亿).
100% read-only local data; NO yfinance; NO baostock; NO network calls.
"""

import bisect
import datetime
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
assert "baostock" not in sys.modules, "Redline violation: baostock forbidden"

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{PROJECT_ROOT}/sim-portfolio"
DATA_DIR = f"{SIM_DIR}/data"

A_DAILY_PATH = f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{DATA_DIR}/cn_hk_price_db/a_delisted_daily.parquet"
KPL_MERGED_PATH = f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl"
CSRC_PIT_PATH = f"{DATA_DIR}/csrc_industry_pit_clean.csv"
ST_PATH = f"{DATA_DIR}/st_universe.json"
NOTICES_DB = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
REG_TOX_PQ = f"{DATA_DIR}/pit_reg_tox_notices_5y_complete.parquet"
IR_QA_DB = f"{DATA_DIR}/cninfo_ir_qa_5y_pit.db"
XUEQIU_DB = f"{DATA_DIR}/xueqiu_guba_5y_pit.db"
COMM_DB = f"{DATA_DIR}/astock_community_5y_pit.db"
LHB_PATH = f"{SIM_DIR}/backtests_astock2/rd016_famous_youzi_seats_20261117/clean_lhb_5y.parquet"
IDX_5Y_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
SH000852_ATTR_PATH = f"{SIM_DIR}/backtest/2026-08-24/attr_index_sh000852.json"

BT_START = "2021-11-15"
BT_END = "2026-11-23"
FEE_RATE = 0.0020

NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股",
}
MA_PAT = re.compile(r"(重组|收购|股权转让|实控人变更|控制权变更|资产注入|借壳|控股|整合|中标|重大合同)")
TECH_PAT_TIMELESS = re.compile(
    r"(芯片|半导体|光刻|集成电路|软件|信创|云计算|大数据|人工智能|AI|机器人|智能制造|自动化|"
    r"通信|5G|光通信|卫星|航天|军工|锂电|光伏|储能|风电|氢能|新材料|消费电子|智能驾驶|无人驾驶|算力|CPO|PCB|减速器|低空|量子)"
)
EARN_PAT = re.compile(r"(业绩|预增|扭亏|季报|年报|半年报|分红)")
CSRC_HARD_TECH_PREFIX = ("C39", "I65", "C35", "C38", "C37", "C40", "I64")
CSRC_TRAD_CONSUMER_CYCLE = (
    "A01", "A02", "A03", "A04", "A05", "B06", "B07", "B08", "B09", "B11",
    "C13", "C14", "C15", "C17", "C18", "C19", "C20", "C21", "C22", "C25", "C26",
    "C30", "C31", "C32", "C33", "D44", "D45", "D46", "E47", "E48", "E50",
    "F51", "F52", "G53", "G54", "G55", "G56", "H61", "H62", "J66", "J67", "J68", "J69", "K70", "L72"
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


def roll_mean(x: np.ndarray, w: int) -> np.ndarray:
    bad = ~np.isfinite(x)
    x0 = np.where(bad, 0.0, x)
    cs = np.cumsum(np.insert(x0, 0, 0.0))
    bc = np.cumsum(np.insert(bad.astype(np.int32), 0, 0))
    out = np.full(len(x), np.nan, dtype=np.float64)
    if len(x) >= w:
        valid = (bc[w:] - bc[:-w]) == 0
        out[w - 1:] = np.where(valid, (cs[w:] - cs[:-w]) / w, np.nan)
    return out


def roll_max(x: np.ndarray, w: int) -> np.ndarray:
    return pd.Series(x).rolling(w, min_periods=max(5, w // 2)).max().to_numpy()


def roll_min(x: np.ndarray, w: int) -> np.ndarray:
    return pd.Series(x).rolling(w, min_periods=max(5, w // 2)).min().to_numpy()


def build_daily_and_kpl():
    """Load 2018~2026-11-23 A-share daily panel (00/60/30/68) and compute PIT KPL themes + synthetic CSI1000."""
    t0 = time.time()
    with open(ST_PATH, "r", encoding="utf-8") as f:
        st_codes = set(json.load(f)["codes"])

    csrc_df = pd.read_csv(CSRC_PIT_PATH)
    csrc_df["c6"] = csrc_df["code"].astype(str).str[-6:].str.zfill(6)
    csrc_name_map = dict(zip(csrc_df["c6"], csrc_df["code_name"].fillna("")))

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn", "oshare"]
    f_expr = (ds.field("date") >= pd.Timestamp("2018-01-01")) & (ds.field("date") <= pd.Timestamp(BT_END))
    d1 = ds.dataset(A_DAILY_PATH, format="parquet").scanner(columns=cols, filter=f_expr).to_table().to_pandas()
    d2 = ds.dataset(A_DELISTED_PATH, format="parquet").scanner(columns=cols, filter=f_expr).to_table().to_pandas()
    df = pd.concat([d1, d2], ignore_index=True)

    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[
        df["ticker"].astype(str).str.endswith((".SH", ".SZ"))
        & df["c6"].str.startswith(("00", "60", "30", "68"))
    ].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    all_mkt_dts = sorted(df["dt_str"].unique())
    dt_to_mkt_idx = {d: i for i, d in enumerate(all_mkt_dts)}
    df["mkt_idx"] = df["dt_str"].map(dt_to_mkt_idx).astype(np.int32)

    df["adjf"] = np.where(df["close"] > 0, df["adj_close"] / df["close"], 1.0)
    df["a_open"] = df["open"] * df["adjf"]
    df["a_high"] = df["high"] * df["adjf"]
    df["a_low"] = df["low"] * df["adjf"]
    df["a_close"] = df["adj_close"]

    g = df.groupby("c6", sort=False)
    df["trade_num"] = g.cumcount()
    df["pre_a_close"] = g["a_close"].shift(1)
    df["pre_c"] = df["pre_a_close"] / df["adjf"]
    df["pct"] = df["a_close"] / df["pre_a_close"] - 1.0
    df["o_pct"] = df["open"] / df["pre_c"] - 1.0
    df["h_pct"] = df["high"] / df["pre_c"] - 1.0
    df["mcap"] = np.where(
        df["oshare"].notna() & (df["oshare"] > 0),
        df["close"] * df["oshare"] / 1e8,
        np.where(df["turn"] > 0, df["close"] * (df["volume"] / df["turn"]) / 1e8, np.nan),
    )
    df["to_pct"] = df["turn"] * 100.0

    is_20 = df["c6"].str.startswith(("30", "68"))
    lim_mult = np.where(is_20, 1.20, 1.10)
    dt_mult = np.where(is_20, 0.80, 0.90)
    df["zt_px"] = np.floor(df["pre_c"] * lim_mult * 100.0 + 0.5 + 1e-9) / 100.0
    df["dt_px"] = np.floor(df["pre_c"] * dt_mult * 100.0 + 0.5 + 1e-9) / 100.0

    df["is_zt"] = np.where(
        is_20,
        (df["close"] >= df["zt_px"] - 0.011) & (df["pct"] >= 0.195),
        (df["close"] >= df["zt_px"] - 0.011) & (df["pct"] >= 0.095),
    ) & (df["pre_c"] > 0)
    df["is_dt"] = np.where(
        is_20,
        (df["close"] <= df["dt_px"] + 0.011) & (df["pct"] <= -0.195),
        (df["close"] <= df["dt_px"] + 0.011) & (df["pct"] <= -0.095),
    ) & (df["pre_c"] > 0)
    df["touch_zt"] = ((df["high"] >= df["zt_px"] - 0.011) | (df["h_pct"] >= np.where(is_20, 0.198, 0.098))) & (df["pre_c"] > 0)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_px"] - 0.011) & (df["low"] >= df["zt_px"] - 0.011)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_px"] + 0.011) & (df["high"] <= df["dt_px"] + 0.011)

    s_zt = df["is_zt"].astype(int)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != g["is_zt"].shift().fillna(False)).cumsum()]).cumsum() * s_zt
    df["is_2b_plus"] = df["streak"] >= 2

    df["name"] = df["c6"].map(csrc_name_map).fillna("")
    df["is_st"] = df["c6"].isin(st_codes) | df["name"].str.contains("ST|退", na=False)

    non_st = df[(~df["is_st"]) & (df["trade_num"] >= 10) & (df["volume"] > 0)].copy()
    mkt_agg = non_st.groupby("dt_str").agg(
        mkt_zt_cnt=("is_zt", "sum"),
        mkt_dt_cnt=("is_dt", "sum"),
        mkt_amt_yi=("amount", lambda s: s.sum() / 1e8),
    )
    mkt_agg["mkt_amt_ma20"] = mkt_agg["mkt_amt_yi"].rolling(20, min_periods=5).mean()
    mkt_agg["mkt_amt_ratio"] = mkt_agg["mkt_amt_yi"] / mkt_agg["mkt_amt_ma20"]
    mkt_stats_map = mkt_agg.to_dict(orient="index")

    sub_syn = non_st[non_st["dt_str"] >= "2021-08-01"][["dt_str", "c6", "pct", "mcap"]].copy()
    sub_syn["mcap_prev"] = sub_syn.groupby("c6")["mcap"].shift(1)
    sub_syn["rk_mcap"] = sub_syn.groupby("dt_str")["mcap_prev"].rank(ascending=False, method="first")
    syn_ret = sub_syn[sub_syn["rk_mcap"].between(801, 1800)].groupby("dt_str")["pct"].mean().sort_index()
    syn_1000_lvl = (1.0 + syn_ret.fillna(0.0)).cumprod() * 1000.0
    if os.path.exists(SH000852_ATTR_PATH):
        att = json.load(open(SH000852_ATTR_PATH))
        att_s = pd.Series({r[0]: float(r[2]) for r in att}).sort_index().pct_change().dropna()
        both = pd.concat([syn_ret, att_s], axis=1).dropna()
        syn_corr = float(both.iloc[:, 0].corr(both.iloc[:, 1])) if len(both) >= 10 else np.nan
    else:
        syn_corr = np.nan
    syn_1000_map = syn_1000_lvl.to_dict()

    kpl_days = []
    with open(KPL_MERGED_PATH, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                obj = json.loads(ln)
                if obj.get("date", "") <= BT_END:
                    kpl_days.append(obj)
    kpl_days.sort(key=lambda x: x["date"])
    kpl_dt_set = {d["date"] for d in kpl_days}
    sub_kpl = df[df["dt_str"].isin(kpl_dt_set)][
        ["dt_str", "c6", "is_zt", "touch_zt", "is_yizi", "pct", "mcap", "is_2b_plus", "streak"]
    ]
    day_stock_map = {
        (r.dt_str, r.c6): (r.is_zt, r.touch_zt, r.is_yizi, r.pct, r.mcap, r.is_2b_plus, int(r.streak))
        for r in sub_kpl.itertuples(index=False)
    }

    elo = defaultdict(lambda: 100.0)
    plate_recent_zts = defaultdict(list)
    plate_last_idx = {}
    prev_plate_stocks = {}
    term_seen_days = Counter()
    term_first_dt, term_last_idx = {}, {}
    plate_stock_last_dt = defaultdict(dict)

    hot_rows = []
    for day_idx, d_entry in enumerate(kpl_days):
        dt = d_entry["date"]
        cutoff_15d = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=15)).isoformat()
        cutoff_365d = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=365)).isoformat()

        for pname, c6_list in prev_plate_stocks.items():
            touches, seals, rets = 0, 0, []
            for c6 in c6_list:
                st = day_stock_map.get((dt, c6))
                if st is not None:
                    rets.append(st[3])
                    touches += int(st[1])
                    seals += int(st[0])
            if touches >= 2 and (seals / touches) < 0.50:
                elo[pname] -= 12.0 * ((touches - seals) / touches)
            elif rets and np.mean(rets) < -0.025:
                elo[pname] -= 10.0
            elif seals >= 2 and (seals / max(touches, 1)) >= 0.70:
                elo[pname] += min(10.0, 5.0 + seals * 1.2)
            elif rets and np.mean(rets) > 0.025:
                elo[pname] += 6.0

        for p_k in list(elo.keys()):
            if day_idx - plate_last_idx.get(p_k, day_idx) > 3:
                elo[p_k] = 100.0 + (elo[p_k] - 100.0) * 0.85

        new_prev_p = {}
        plate_meta = {}
        day_terms_to_commit = {}
        for p in d_entry.get("plates", []):
            pname = p.get("plate", "").strip()
            if not pname or pname in NON_THEME:
                continue
            stocks = p.get("stocks", [])
            sz = len(stocks)
            if sz == 0:
                continue
            c6_list = []
            n_ma = n_tech_t = n_earn = n_big = n_yizi = n_new = 0
            spark_b = 0.0
            max_board = 0
            for s in stocks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6_list.append(c6)
                plate_stock_last_dt[pname][c6] = dt
                if "," in pname:
                    for sub_p in pname.split(","):
                        sub_p = sub_p.strip()
                        if sub_p and sub_p not in NON_THEME:
                            plate_stock_last_dt[sub_p][c6] = dt
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                r_lg = str(s[3]).strip() if len(s) > 3 else ""
                txt = f"{pname} {r_sh} {r_lg}"
                if MA_PAT.search(txt):
                    n_ma += 1
                if TECH_PAT_TIMELESS.search(txt):
                    n_tech_t += 1
                if EARN_PAT.search(txt):
                    n_earn += 1
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
                    if st[4] >= 150.0:
                        n_big += 1
                    if st[2]:
                        n_yizi += 1
                    if st[6] > max_board:
                        max_board = st[6]

            new_prev_p[pname] = c6_list
            plate_last_idx[pname] = day_idx
            r5_zts = sum(cnt for idx_p, cnt in plate_recent_zts[pname] if day_idx - idx_p <= 5)
            plate_recent_zts[pname].append((day_idx, sz))
            sc_base = (
                elo[pname] + min(sz, 15) * 1.8 + min(r5_zts, 30) * 0.35
                + (8.0 if n_ma > 0 else 0.0) + (5.0 if n_new > 0 else 0.0)
                + spark_b + min(n_yizi * 4.0, 8.0) - (n_earn / sz) * 12.0 - (n_big / sz) * 10.0
            )
            is_ht = bool(TECH_PAT_TIMELESS.search(pname) or n_tech_t >= max(1, sz // 2))
            sc_clean = sc_base + (6.0 if is_ht else 0.0)
            plate_meta[pname] = (sc_clean, elo[pname], sz, max_board, is_ht)

        ranked_c = sorted(plate_meta.keys(), key=lambda k: plate_meta[k][0], reverse=True)
        rk_map_c = {k: i + 1 for i, k in enumerate(ranked_c)}

        if BT_START <= dt <= BT_END:
            best_for_stock = {}
            for pname, (sc_c, p_elo, sz, max_b, is_ht) in plate_meta.items():
                rk_c = rk_map_c[pname]
                if not (rk_c <= 2 or sz >= 5):
                    continue
                cand_c6 = set()
                for p_cand in ([pname] + ([x.strip() for x in pname.split(",")] if "," in pname else [])):
                    for c6, last_d in plate_stock_last_dt.get(p_cand, {}).items():
                        if last_d >= cutoff_365d:
                            cand_c6.add(c6)
                for c6 in cand_c6:
                    cur = best_for_stock.get(c6)
                    if cur is None or sc_c > cur[3]:
                        best_for_stock[c6] = (pname, rk_c, sz, sc_c, p_elo, max_b, is_ht)
            for c6, (pname, rk_c, sz, sc_c, p_elo, max_b, is_ht) in best_for_stock.items():
                hot_rows.append((dt, c6, pname, rk_c, sz, sc_c, p_elo, max_b, int(is_ht)))

        for t, dt_v in day_terms_to_commit.items():
            term_seen_days[t] += 1
            if t not in term_first_dt:
                term_first_dt[t] = dt_v
            term_last_idx[t] = day_idx
        prev_plate_stocks = new_prev_p

    hp_df = pd.DataFrame(
        hot_rows,
        columns=["dt_str", "c6", "plate", "rk_c", "p_sz", "sc_clean", "p_elo", "plate_max_board", "plate_hard_tech"],
    )
    print(f"[Builder 1/3] Daily + KPL built in {time.time()-t0:.1f}s: df={len(df):,}, hot_pairs={len(hp_df):,}, syn1000_corr={syn_corr:.4f}")
    return df, hp_df, all_mkt_dts, dt_to_mkt_idx, mkt_stats_map, syn_1000_map, syn_corr, csrc_df


def compute_stock_technicals_and_returns(df: pd.DataFrame, hp_df: pd.DataFrame, all_mkt_dts: list, dt_to_mkt_idx: dict, csi300_map: dict):
    """Merge candidate pool (mcap >= 150亿, non-ST, trade_num >= 60, tradable T+1) and compute exact forward returns & technicals."""
    t0 = time.time()
    n = len(df)
    c6_arr = df["c6"].to_numpy()
    splits = np.flatnonzero(c6_arr[1:] != c6_arr[:-1]) + 1
    bounds = np.concatenate(([0], splits, [n]))

    ret_pre5_exT = np.full(n, np.nan)
    ret_pre5_incT = np.full(n, np.nan)
    ret_pre10_exT = np.full(n, np.nan)
    ret_pre20_exT = np.full(n, np.nan)
    ret_pre60_exT = np.full(n, np.nan)
    pos20 = np.full(n, np.nan)
    pos60 = np.full(n, np.nan)
    pos120 = np.full(n, np.nan)
    dd20 = np.full(n, np.nan)
    dd60 = np.full(n, np.nan)
    dd20_pre = np.full(n, np.nan)
    break60 = np.zeros(n, dtype=np.int8)
    ma_bull = np.zeros(n, dtype=np.int8)
    vol_ratio_5d = np.full(n, np.nan)
    clv = np.full(n, np.nan)

    d1_dt = np.full(n, "", dtype=object)
    d1_open_pct = np.full(n, np.nan)
    d1_buyable = np.zeros(n, dtype=bool)
    ret_1d_o2o = np.full(n, np.nan)
    ret_1d = np.full(n, np.nan)
    ret_3d = np.full(n, np.nan)
    ret_5d = np.full(n, np.nan)
    ret_10d = np.full(n, np.nan)
    ret_20d = np.full(n, np.nan)
    ex_1d = np.full(n, np.nan)
    ex_3d = np.full(n, np.nan)
    ex_5d = np.full(n, np.nan)
    ex_10d = np.full(n, np.nan)
    ex_20d = np.full(n, np.nan)

    a_close = df["a_close"].to_numpy()
    a_open = df["a_open"].to_numpy()
    a_high = df["a_high"].to_numpy()
    a_low = df["a_low"].to_numpy()
    close_u = df["close"].to_numpy()
    open_u = df["open"].to_numpy()
    high_u = df["high"].to_numpy()
    low_u = df["low"].to_numpy()
    amt = df["amount"].to_numpy()
    vol = df["volume"].to_numpy()
    mkt_idx = df["mkt_idx"].to_numpy()
    dt_arr = df["dt_str"].to_numpy()
    zt_px = df["zt_px"].to_numpy()
    o_pct = df["o_pct"].to_numpy()
    is_yz_dt = df["is_yizi_dt"].to_numpy()
    mcap = df["mcap"].to_numpy()
    trade_num = df["trade_num"].to_numpy()
    is_st = df["is_st"].to_numpy()

    cand_keys = set(zip(hp_df["dt_str"], hp_df["c6"]))
    n_mkt = len(all_mkt_dts)

    for s_i in range(len(bounds) - 1):
        a, b = bounds[s_i], bounds[s_i + 1]
        m = b - a
        if m < 25:
            continue

        ac = a_close[a:b]
        ao = a_open[a:b]
        ah = a_high[a:b]
        al = a_low[a:b]
        cu = close_u[a:b]
        hu = high_u[a:b]
        lu = low_u[a:b]
        am = amt[a:b]

        ac_s1 = np.empty(m); ac_s1[0] = np.nan; ac_s1[1:] = ac[:-1]
        ac_s5 = np.empty(m); ac_s5[:5] = np.nan; ac_s5[5:] = ac[:-5]
        ac_s6 = np.empty(m); ac_s6[:6] = np.nan; ac_s6[6:] = ac[:-6]
        ac_s11 = np.empty(m); ac_s11[:11] = np.nan; ac_s11[11:] = ac[:-11]
        ac_s21 = np.empty(m); ac_s21[:21] = np.nan; ac_s21[21:] = ac[:-21]
        ac_s61 = np.empty(m); ac_s61[:61] = np.nan; ac_s61[61:] = ac[:-61]

        ret_pre5_exT[a:b] = ac_s1 / ac_s6 - 1.0
        ret_pre5_incT[a:b] = ac / ac_s5 - 1.0
        ret_pre10_exT[a:b] = ac_s1 / ac_s11 - 1.0
        ret_pre20_exT[a:b] = ac_s1 / ac_s21 - 1.0
        ret_pre60_exT[a:b] = ac_s1 / ac_s61 - 1.0

        max20 = roll_max(ah, 20)
        min20 = roll_min(al, 20)
        max60 = roll_max(ah, 60)
        min60 = roll_min(al, 60)
        max120 = roll_max(ah, 120)
        min120 = roll_min(al, 120)

        max20_p = np.empty(m); max20_p[0] = np.nan; max20_p[1:] = max20[:-1]
        max60_p = np.empty(m); max60_p[0] = np.nan; max60_p[1:] = max60[:-1]

        pos20[a:b] = np.where(max20 > min20, (ac - min20) / np.maximum(max20 - min20, 1e-12), np.nan)
        pos60[a:b] = np.where(max60 > min60, (ac - min60) / np.maximum(max60 - min60, 1e-12), np.nan)
        pos120[a:b] = np.where(max120 > min120, (ac - min120) / np.maximum(max120 - min120, 1e-12), np.nan)
        dd20[a:b] = ac / max20 - 1.0
        dd60[a:b] = ac / max60 - 1.0
        dd20_pre[a:b] = ac_s1 / max20_p - 1.0
        break60[a:b] = np.where(np.isfinite(max60_p) & (ac >= max60_p * 0.9999), 1, 0)

        ma20 = roll_mean(ac, 20)
        ma60 = roll_mean(ac, 60)
        ma_bull[a:b] = np.where(np.isfinite(ma60) & (ac > ma20) & (ma20 > ma60), 1, 0)

        am_ma5 = roll_mean(am, 5)
        am_ma5_p = np.empty(m); am_ma5_p[0] = np.nan; am_ma5_p[1:] = am_ma5[:-1]
        vol_ratio_5d[a:b] = am / np.maximum(am_ma5_p, 1.0)
        span = np.maximum(hu - lu, 1e-12)
        clv[a:b] = np.where(hu > lu, (cu - lu) / span, 0.5)

        mi = mkt_idx[a:b]
        dts = dt_arr[a:b]
        c_code = c6_arr[a]
        for i in range(m):
            if mcap[a + i] < 150.0 or is_st[a + i] or trade_num[a + i] < 60 or vol[a + i] <= 0 or am[i] <= 0:
                continue
            dt_t = dts[i]
            if (dt_t, c_code) not in cand_keys or i + 1 >= m:
                continue
            t_mi = int(mi[i])
            if int(mi[i + 1]) != t_mi + 1:
                continue
            g_buy = a + i + 1
            if vol[g_buy] <= 0 or open_u[g_buy] <= 0:
                continue
            if open_u[g_buy] >= zt_px[g_buy] - 0.011 or is_yz_dt[g_buy]:
                continue

            d1_buyable[a + i] = True
            d1_dt[a + i] = dts[i + 1]
            d1_open_pct[a + i] = o_pct[g_buy]
            entry_px = ao[i + 1]
            csi_base = csi300_map.get(dt_t, np.nan)

            def get_exit_ret(offset_mkt: int, use_open: bool = False):
                target_mi = t_mi + offset_mkt
                if target_mi >= n_mkt:
                    return np.nan, np.nan
                pos = int(np.searchsorted(mi, target_mi, side="left"))
                if pos >= m:
                    k_last = m - 1
                    while k_last > i + 1 and (vol[a + k_last] <= 0 or is_yz_dt[a + k_last]):
                        k_last -= 1
                    if k_last <= i + 1:
                        return np.nan, np.nan
                    epx = ac[k_last]
                    ex_dt = dts[k_last]
                else:
                    k = pos
                    while k < m and (vol[a + k] <= 0 or is_yz_dt[a + k]):
                        k += 1
                    if k >= m:
                        return np.nan, np.nan
                    epx = ao[k] if use_open else ac[k]
                    ex_dt = dts[k]
                net_r = (epx / entry_px) * (1.0 - FEE_RATE) - 1.0
                csi_ex = csi300_map.get(ex_dt, np.nan)
                ex_r = (net_r - (csi_ex / csi_base - 1.0)) if (np.isfinite(csi_base) and np.isfinite(csi_ex)) else np.nan
                return net_r, ex_r

            r1o, _ = get_exit_ret(2, use_open=True)
            r1, e1 = get_exit_ret(2, use_open=False)
            r3, e3 = get_exit_ret(3, use_open=False)
            r5, e5 = get_exit_ret(5, use_open=False)
            r10, e10 = get_exit_ret(10, use_open=False)
            r20, e20 = get_exit_ret(20, use_open=False)

            ret_1d_o2o[a + i] = r1o
            ret_1d[a + i], ex_1d[a + i] = r1, e1
            ret_3d[a + i], ex_3d[a + i] = r3, e3
            ret_5d[a + i], ex_5d[a + i] = r5, e5
            ret_10d[a + i], ex_10d[a + i] = r10, e10
            ret_20d[a + i], ex_20d[a + i] = r20, e20

    df["ret_pre5_exT"] = ret_pre5_exT
    df["ret_pre5_incT"] = ret_pre5_incT
    df["ret_pre10_exT"] = ret_pre10_exT
    df["ret_pre20_exT"] = ret_pre20_exT
    df["ret_pre60_exT"] = ret_pre60_exT
    df["pos20"] = pos20
    df["pos60"] = pos60
    df["pos120"] = pos120
    df["dd20"] = dd20
    df["dd60"] = dd60
    df["dd20_pre"] = dd20_pre
    df["break60"] = break60
    df["ma_bull"] = ma_bull
    df["vol_ratio_5d"] = vol_ratio_5d
    df["clv"] = clv
    df["d1_dt"] = d1_dt
    df["d1_open_pct"] = d1_open_pct
    df["d1_buyable"] = d1_buyable
    df["ret_1d_o2o"] = ret_1d_o2o
    df["ret_1d"] = ret_1d
    df["ret_3d"] = ret_3d
    df["ret_5d"] = ret_5d
    df["ret_10d"] = ret_10d
    df["ret_20d"] = ret_20d
    df["ex_1d"] = ex_1d
    df["ex_3d"] = ex_3d
    df["ex_5d"] = ex_5d
    df["ex_10d"] = ex_10d
    df["ex_20d"] = ex_20d

    cand = df[df["d1_buyable"]].merge(hp_df, on=["dt_str", "c6"], how="inner")
    cand["amt_yi"] = cand["amount"] / 1e8
    cand["amt_rk_in_plate"] = cand.groupby(["dt_str", "plate"])["amt_yi"].rank(ascending=False, method="min")
    cand["mcap_rk_in_plate"] = cand.groupby(["dt_str", "plate"])["mcap"].rank(ascending=False, method="min")
    print(f"[Builder 2/3] Candidate pool with returns built in {time.time()-t0:.1f}s: rows={len(cand):,}, days={cand['dt_str'].nunique()}, stocks={cand['c6'].nunique()}")
    return cand


def enrich_pit_external_factors(cand: pd.DataFrame, all_mkt_dts: list, dt_to_mkt_idx: dict,
                                mkt_stats_map: dict, syn_1000_map: dict, csi300_map: dict,
                                idx_5y: dict, csrc_df: pd.DataFrame) -> pd.DataFrame:
    """Attach strictly PIT (< T+1 09:25:00 & d1_date <= T) Notices, Reg/Tox 5Y, IR QA, LHB seats, Xueqiu, CSRC, Macro."""
    t0 = time.time()
    c6_set = set(cand["c6"].unique())

    ind_spans = defaultdict(list)
    for r in csrc_df.itertuples(index=False):
        ind_spans[r.c6].append((str(r.start_date), str(r.end_date), str(r.industry)))

    def get_csrc_ind(c6, dt):
        sp = ind_spans.get(c6)
        if not sp:
            return ""
        for sd, ed, ind in sp:
            if sd <= dt <= ed:
                return ind
        return sp[-1][2]

    cand["csrc_ind"] = [get_csrc_ind(c6, dt) for c6, dt in zip(cand["c6"], cand["dt_str"])]
    cand["csrc_code3"] = cand["csrc_ind"].str[:3]
    cand["is_hard_tech_ind"] = cand["csrc_code3"].isin(CSRC_HARD_TECH_PREFIX).astype(int)
    cand["is_trad_cycle_ind"] = cand["csrc_code3"].isin(CSRC_TRAD_CONSUMER_CYCLE).astype(int)
    cand["sector_style"] = np.where(
        (cand["plate_hard_tech"] == 1) | (cand["is_hard_tech_ind"] == 1),
        "硬科技",
        np.where(cand["is_trad_cycle_ind"] == 1, "传统消费周期", "其他中游制造"),
    )

    # Notices (< T+1 09:25:00) with separated subtypes
    PAT_EARN_POS = re.compile(r"预增|略增|续盈|扭亏")
    PAT_EARN_KB_POS = re.compile(r"业绩快报.*(?:增长|增加|上升|扭亏)|(?:净利润|归母净利润).*(?:增长|增加|上升)")
    PAT_EARN_NEG_GUARD = re.compile(r"预亏|首亏|增亏|续亏|略减|预减|下降|下滑|减少|亏损")
    PAT_CONTRACT = re.compile(r"重大合同|日常经营.*合同|中标|定点|签订.*合同|采购协议")
    PAT_BUYBACK = re.compile(r"回购|增持")
    PAT_REDUCE = re.compile(r"减持")
    PAT_LOSS = re.compile(r"预亏|首亏|增亏|续亏|业绩预告:略减|业绩预告:预减")
    PAT_REG = re.compile(r"立案|处罚|监管函|监管工作函|警示函|关注函|问询函|退市风险|实施退市|违约|冻结")
    PAT_REPORT = re.compile(r"(?:一季度|半年度|三季度|年度)报告(?:全文|正文)?$|业绩快报")

    notices_by_c6 = defaultdict(list)
    con_n = sqlite3.connect(f"file:{NOTICES_DB}?mode=ro", uri=True)
    for sc, pdt, title, atype in con_n.execute(
        "SELECT sec_code, pub_datetime_cst, title, ann_type FROM notices WHERE pub_datetime_cst >= '2021-08-01' AND pub_datetime_cst <= ?",
        (f"{BT_END} 09:25:00",),
    ):
        c6 = str(sc)[:6].zfill(6)
        if c6 not in c6_set or not pdt:
            continue
        t = str(title or "")
        a = str(atype or "")
        ta = f"{a} {t}"
        is_red = bool(PAT_REDUCE.search(ta)) and ("不减持" not in t)
        is_loss = bool(PAT_LOSS.search(ta))
        is_reg = bool(PAT_REG.search(ta))
        is_earn_pos = (
            (a in ("业绩预告:预增", "业绩预告:略增", "业绩预告:续盈", "业绩预告:扭亏"))
            or (bool(PAT_EARN_POS.search(t)) and not is_loss and not is_reg)
            or (bool(PAT_EARN_KB_POS.search(t)) and not PAT_EARN_NEG_GUARD.search(t))
        )
        is_contract = (a == "重大合同") or (bool(PAT_CONTRACT.search(t)) and "解除" not in t)
        is_buyback = bool(PAT_BUYBACK.search(ta)) and ("减持" not in t) and ("不增持" not in t)
        is_report = (a in ("一季度报告全文", "半年度报告全文", "三季度报告全文", "年度报告全文", "一季度报告正文", "业绩快报")) or bool(PAT_REPORT.search(t))
        if is_earn_pos or is_contract or is_buyback or is_red or is_loss or is_reg or is_report:
            notices_by_c6[c6].append((str(pdt), is_earn_pos, is_contract, is_buyback, is_red, is_loss, is_reg, is_report))
    con_n.close()

    # Merge full-5y pit_reg_tox_notices_5y_complete.parquet for complete 2021-2026 regulatory/toxic coverage
    regtox_by_c6 = defaultdict(list)
    if os.path.exists(REG_TOX_PQ):
        tx = pd.read_parquet(REG_TOX_PQ, columns=["sec_code", "pub_datetime_cst"])
        tx["c6"] = tx["sec_code"].astype(str).str[:6].str.zfill(6)
        tx = tx[tx["c6"].isin(c6_set)]
        for r in tx.itertuples(index=False):
            if r.pub_datetime_cst:
                regtox_by_c6[r.c6].append(str(r.pub_datetime_cst)[:19])
        for c6 in regtox_by_c6:
            regtox_by_c6[c6].sort()

    for c6 in notices_by_c6:
        notices_by_c6[c6].sort(key=lambda x: x[0])

    ir_by_c6 = defaultdict(list)
    con_ir = sqlite3.connect(f"file:{IR_QA_DB}?mode=ro", uri=True)
    for sc, pdt in con_ir.execute(
        "SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE pub_datetime_cst >= '2021-08-01' AND pub_datetime_cst <= ?",
        (f"{BT_END} 09:25:00",),
    ):
        c6 = str(sc)[:6].zfill(6)
        if c6 in c6_set and pdt:
            ir_by_c6[c6].append(str(pdt))
    con_ir.close()
    for c6 in ir_by_c6:
        ir_by_c6[c6].sort()

    # Xueqiu strict PIT: created_time_str < d1_dt 09:25:00 AND d1_date <= dt_str (zero future-crawl leakage!)
    xq_by_c6 = defaultdict(list)
    xq_union_by_c6 = defaultdict(list)
    seen_pids = defaultdict(set)
    con_xq = sqlite3.connect(f"file:{XUEQIU_DB}?mode=ro", uri=True)
    for sym, pid, ts, d1d in con_xq.execute(
        "SELECT symbol, post_id, created_time_str, d1_date FROM xueqiu_posts WHERE created_time_str >= '2021-10-01' AND created_time_str <= ?",
        (f"{BT_END} 09:25:00",),
    ):
        c6 = str(sym)[:6].zfill(6)
        if c6 in c6_set and ts:
            ts_s = str(ts)[:19]
            d1d_s = str(d1d or "")[:10]
            pid_s = str(pid).lstrip("xq_")
            xq_by_c6[c6].append((ts_s, d1d_s))
            if pid_s not in seen_pids[c6]:
                seen_pids[c6].add(pid_s)
                xq_union_by_c6[c6].append((ts_s, d1d_s))
    con_xq.close()
    if os.path.exists(COMM_DB):
        con_cm = sqlite3.connect(f"file:{COMM_DB}?mode=ro", uri=True)
        for sym, pid, ts in con_cm.execute(
            "SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND pub_datetime_cst >= '2021-10-01' AND pub_datetime_cst <= ?",
            (f"{BT_END} 09:25:00",),
        ):
            c6 = str(sym)[-6:].zfill(6)
            if c6 in c6_set and ts:
                ts_s = str(ts)[:19]
                pid_s = str(pid).lstrip("xq_")
                if pid_s not in seen_pids[c6]:
                    seen_pids[c6].add(pid_s)
                    xq_union_by_c6[c6].append((ts_s, ts_s[:10]))
        con_cm.close()
    for c6 in xq_by_c6:
        xq_by_c6[c6].sort(key=lambda x: x[0])
    for c6 in xq_union_by_c6:
        xq_union_by_c6[c6].sort(key=lambda x: x[0])

    # LHB deduplicated daily stats
    lhb = pd.read_parquet(LHB_PATH, columns=["date", "stock_code", "is_three", "dept_code", "dept_name", "BUY", "SELL", "NET"])
    lhb = lhb[(lhb["date"] >= "2021-10-01") & (lhb["date"] <= BT_END)].copy()
    lhb["c6"] = lhb["stock_code"].astype(str).str[:6].str.zfill(6)
    lhb = lhb[lhb["c6"].isin(c6_set)].copy()
    min_t = lhb.groupby(["date", "c6"])["is_three"].transform("min")
    lhb = lhb[lhb["is_three"] == min_t].copy()
    lhb = lhb.drop_duplicates(["date", "c6", "dept_code", "dept_name", "BUY", "SELL", "NET"]).copy()
    dn = lhb["dept_name"].astype(str)
    youzi_re = re.compile(r"(?:章建平|国泰君安.*江苏路|中信.*东阳|中信.*西安朱雀|华泰.*总部|国盛.*慈溪|中国银河.*大连金马路|联储.*宁波|六一中路|呼家楼|中信建投.*北京朝外|陈小群|东亚前海.*苏州留园)")
    lhb["inst_net"] = np.where(dn == "机构专用", lhb["NET"].fillna(0.0), 0.0)
    lhb["north_net"] = np.where(dn.str.contains("股通专用", na=False), lhb["NET"].fillna(0.0), 0.0)
    lhb["is_lhasa"] = dn.str.contains("拉萨", na=False).astype(int)
    lhb["youzi_net"] = np.where(dn.str.contains(youzi_re, na=False), lhb["NET"].fillna(0.0), 0.0)
    lhb_agg = lhb.groupby(["date", "c6"], as_index=False).agg(
        inst_net=("inst_net", "sum"),
        north_net=("north_net", "sum"),
        lhasa_cnt=("is_lhasa", "sum"),
        youzi_net=("youzi_net", "sum"),
    )
    lhb_day_map = {
        (r.date, r.c6): (float(r.inst_net) / 1e4, float(r.north_net) / 1e4, int(r.lhasa_cnt), float(r.youzi_net) / 1e4)
        for r in lhb_agg.itertuples(index=False)
    }

    n_rows = len(cand)
    n_earn = np.zeros(n_rows, dtype=np.int8)
    n_contract = np.zeros(n_rows, dtype=np.int8)
    n_buyback = np.zeros(n_rows, dtype=np.int8)
    n_cb = np.zeros(n_rows, dtype=np.int8)
    n_reduce = np.zeros(n_rows, dtype=np.int8)
    n_loss = np.zeros(n_rows, dtype=np.int8)
    n_reg = np.zeros(n_rows, dtype=np.int8)
    n_regtox_5y = np.zeros(n_rows, dtype=np.int8)
    n_report = np.zeros(n_rows, dtype=np.int8)
    ir_30 = np.zeros(n_rows, dtype=np.int16)
    ir_90 = np.zeros(n_rows, dtype=np.int16)
    xq_2 = np.zeros(n_rows, dtype=np.int16)
    xq_7 = np.zeros(n_rows, dtype=np.int16)
    xq_u7 = np.zeros(n_rows, dtype=np.int16)
    lhb_inst_5d = np.full(n_rows, np.nan)
    lhb_inst_1d = np.full(n_rows, np.nan)
    lhb_north_5d = np.full(n_rows, np.nan)
    lhb_lhasa_5d = np.zeros(n_rows, dtype=np.int8)
    lhb_youzi_5d = np.full(n_rows, np.nan)

    c6_col = cand["c6"].to_numpy()
    dt_col = cand["dt_str"].to_numpy()
    d1_col = cand["d1_dt"].to_numpy()

    uniq_dts = cand[["dt_str", "d1_dt"]].drop_duplicates()
    cut_cache = {}
    for r in uniq_dts.itertuples(index=False):
        dt_s = r.dt_str
        d1_s = r.d1_dt
        dt_d = datetime.date.fromisoformat(dt_s)
        t_idx = dt_to_mkt_idx[dt_s]
        prev_5_dts = [all_mkt_dts[max(0, t_idx - k)] for k in range(5) if t_idx - k >= 0]
        cut_cache[(dt_s, d1_s)] = (
            (dt_d - datetime.timedelta(days=90)).isoformat() + " 00:00:00",
            (dt_d - datetime.timedelta(days=30)).isoformat() + " 00:00:00",
            (dt_d - datetime.timedelta(days=6)).isoformat() + " 00:00:00",
            (dt_d - datetime.timedelta(days=1)).isoformat() + " 00:00:00",
            f"{d1_s} 09:25:00",
            prev_5_dts,
        )

    for i in range(n_rows):
        c6 = c6_col[i]
        dt_s = dt_col[i]
        d1_s = d1_col[i]
        lo90, lo30, lo7, lo2, hi_cut, p5_dts = cut_cache[(dt_s, d1_s)]

        nl = notices_by_c6.get(c6)
        if nl:
            idx_lo = bisect.bisect_left(nl, (lo90, False, False, False, False, False, False, False))
            idx_hi = bisect.bisect_left(nl, (hi_cut, False, False, False, False, False, False, False))
            for k in range(idx_lo, idx_hi):
                pdt, f_ep, f_ct, f_bb, f_rd, f_ls, f_rg, f_rp = nl[k]
                if f_ep: n_earn[i] = 1
                if f_ct: n_contract[i] = 1; n_cb[i] = 1
                if f_bb: n_buyback[i] = 1; n_cb[i] = 1
                if f_rd: n_reduce[i] = 1
                if f_ls: n_loss[i] = 1
                if f_rg: n_reg[i] = 1
                if f_rp and pdt >= lo30: n_report[i] = 1

        rtl = regtox_by_c6.get(c6)
        if rtl:
            idx_r = bisect.bisect_left(rtl, lo90)
            if idx_r < len(rtl) and rtl[idx_r] < hi_cut:
                n_regtox_5y[i] = 1

        irl = ir_by_c6.get(c6)
        if irl:
            hi_i = bisect.bisect_left(irl, hi_cut)
            ir_90[i] = hi_i - bisect.bisect_left(irl, lo90)
            ir_30[i] = hi_i - bisect.bisect_left(irl, lo30)

        xql = xq_by_c6.get(c6)
        if xql:
            lo_x = bisect.bisect_left(xql, (lo7, ""))
            hi_x = bisect.bisect_left(xql, (hi_cut, ""))
            c7 = c2 = 0
            for k in range(lo_x, hi_x):
                ts_k, d1d_k = xql[k]
                if d1d_k <= dt_s:
                    c7 += 1
                    if ts_k >= lo2:
                        c2 += 1
            xq_7[i] = c7
            xq_2[i] = c2

        xqul = xq_union_by_c6.get(c6)
        if xqul:
            lo_xu = bisect.bisect_left(xqul, (lo7, ""))
            hi_xu = bisect.bisect_left(xqul, (hi_cut, ""))
            xq_u7[i] = sum(1 for k in range(lo_xu, hi_xu) if xqul[k][1] <= dt_s)

        hit_5d = False
        inst_s = north_s = yz_s = 0.0
        lh_cnt = 0
        for d_p in p5_dts:
            rec = lhb_day_map.get((d_p, c6))
            if rec is not None:
                hit_5d = True
                inst_s += rec[0]
                north_s += rec[1]
                lh_cnt += rec[2]
                yz_s += rec[3]
        if hit_5d:
            lhb_inst_5d[i] = inst_s
            lhb_north_5d[i] = north_s
            lhb_lhasa_5d[i] = 1 if lh_cnt > 0 else 0
            lhb_youzi_5d[i] = yz_s
        rec1 = lhb_day_map.get((dt_s, c6))
        if rec1 is not None:
            lhb_inst_1d[i] = rec1[0]

    cand["notice_earn_pos_90d"] = n_earn
    cand["notice_contract_90d"] = n_contract
    cand["notice_buyback_90d"] = n_buyback
    cand["notice_contract_buyback_90d"] = n_cb
    cand["notice_reduce_90d"] = n_reduce
    cand["notice_loss_90d"] = n_loss
    cand["notice_reg_90d"] = n_reg
    cand["notice_regtox_5y_90d"] = n_regtox_5y
    cand["notice_report_30d"] = n_report
    cand["ir_cnt_30d"] = ir_30
    cand["ir_cnt_90d"] = ir_90
    cand["xq_posts_2d"] = xq_2
    cand["xq_posts_7d"] = xq_7
    cand["xq_union_7d"] = xq_u7
    cand["lhb_inst_net_5d_wan"] = lhb_inst_5d
    cand["lhb_inst_net_1d_wan"] = lhb_inst_1d
    cand["lhb_north_net_5d_wan"] = lhb_north_5d
    cand["lhb_lhasa_5d"] = lhb_lhasa_5d
    cand["lhb_youzi_net_5d_wan"] = lhb_youzi_5d

    sz399107_map = idx_5y.get("sz399107", {})
    csi_dts = sorted(csi300_map.keys())
    csi_idx_map = {d: i for i, d in enumerate(csi_dts)}
    macro_by_dt = {}
    for dt_s in cand["dt_str"].unique():
        ci = csi_idx_map.get(dt_s)
        c_ret5 = c_ret20 = zz_rel5 = sz_rel5 = np.nan
        if ci is not None and ci >= 20:
            c_now = csi300_map[csi_dts[ci]]
            c_5 = csi300_map[csi_dts[ci - 5]]
            c_20 = csi300_map[csi_dts[ci - 20]]
            c_ret5 = c_now / c_5 - 1.0
            c_ret20 = c_now / c_20 - 1.0
            d_5 = csi_dts[ci - 5]
            if dt_s in syn_1000_map and d_5 in syn_1000_map:
                zz_rel5 = (syn_1000_map[dt_s] / syn_1000_map[d_5] - 1.0) - c_ret5
            if dt_s in sz399107_map and d_5 in sz399107_map:
                sz_rel5 = (sz399107_map[dt_s] / sz399107_map[d_5] - 1.0) - c_ret5
        ms = mkt_stats_map.get(dt_s, {})
        macro_by_dt[dt_s] = (
            c_ret5, c_ret20, zz_rel5, sz_rel5,
            ms.get("mkt_zt_cnt", np.nan),
            ms.get("mkt_amt_ratio", np.nan),
        )

    m_arr = np.array([macro_by_dt[d] for d in cand["dt_str"]], dtype=float)
    cand["csi300_ret5"] = m_arr[:, 0]
    cand["csi300_ret20"] = m_arr[:, 1]
    cand["zz1000_vs_csi300_5d"] = m_arr[:, 2]
    cand["sz399107_vs_csi300_5d"] = m_arr[:, 3]
    cand["mkt_zt_cnt"] = m_arr[:, 4]
    cand["mkt_amt_ratio"] = m_arr[:, 5]

    print(f"[Builder 3/3] External PIT features attached in {time.time()-t0:.1f}s")
    return cand
