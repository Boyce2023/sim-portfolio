# -*- coding: utf-8 -*-
"""
v16_data_loader.py: 题库底层数据与行情载入
严格只读 SQLite (mode=ro, uri=True)，严禁 import yfinance。
"""
import os, sys, re, json, time, sqlite3
from collections import defaultdict
import numpy as np, pandas as pd

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{PROJECT_ROOT}/sim-portfolio"
BACKTEST_CLEAN = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean"
if BACKTEST_CLEAN not in sys.path:
    sys.path.insert(0, BACKTEST_CLEAN)

from clean_wf_1to2_v14_ironclad_master import load_full_prices, FEE_RATE
from exp1_fake_theme_purifier import (
    build_8y_purified_theme_metadata, attach_features_and_purifiers,
    compute_purifier_auction_scores, EVENT_BASKET_PLATES, BROAD_INDUSTRY_PLATES
)
from v16_scoring import compute_v16_features_and_scores

PARQUET_5M_PATH = f"{SIM_DIR}/data/cand_5m_bars_v15_complete.parquet"
CSRC_PATH = f"{SIM_DIR}/data/csrc_industry_l2.csv"
TAPE_DB_PATH = f"{SIM_DIR}/data/zt_micro_tape_5y_pit.db"
IR_DB_PATH = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db"
KPL_5Y_PATH = f"{SIM_DIR}/data/kpl_plates_5y_2021_2026_complete.jsonl"
SH_PKL_PATH = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock2/assets/astock2_sh_daily.pkl"
PKL_CACHE_FB = "/tmp/astock_hist_fb_preprocessed.pkl"

def load_all_market_base():
    df, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt, r.volume)
        for r in df[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt", "volume"]].itertuples(index=False)
    }
    df["c6"] = df["ticker"].astype(str).str[:6]
    is_new = (df["c6"].values != np.roll(df["c6"].values, 1))
    is_new[0] = True
    is_zt_arr = df["is_zt"].values
    consec_arr = np.zeros(len(df), dtype=np.int32)
    cur_consec = 0
    for i in range(len(df)):
        if is_new[i] or not is_zt_arr[i]: cur_consec = int(is_zt_arr[i])
        else: cur_consec += 1
        consec_arr[i] = cur_consec
    df["consec_zt"] = consec_arr

    fb_valid = df[df["is_first_board"] & (~df["is_yizi"])]
    fb_cnt_map = fb_valid.groupby("dt_str")["c6"].count().to_dict()
    d1_fb_open_map = fb_valid.groupby("dt_str")["d2_o_pct"].mean().to_dict()
    dg = df.groupby("dt_str")
    max_height_map = dg["consec_zt"].max().to_dict()
    stock_rows_by_c6 = defaultdict(list)
    for r in df[["c6", "dt_str", "open", "high", "low", "close", "volume", "is_zt"]].itertuples(index=False):
        stock_rows_by_c6[r.c6].append(r)
    return df, all_dts, dt_to_idx, price_lookup, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map, max_height_map, fb_cnt_map, d1_fb_open_map, stock_rows_by_c6

def load_5m_bars_map():
    df_5m = pd.read_parquet(PARQUET_5M_PATH)
    df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    return {(c6, dt): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy() for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False)}

def load_kpl_metadata():
    r_long_map = {}
    plate_daily_sz = defaultdict(dict)
    kpl_dates = []
    if os.path.exists(KPL_5Y_PATH):
        with open(KPL_5Y_PATH, "r", encoding="utf-8") as f:
            for ln in f:
                if not ln.strip(): continue
                d = json.loads(ln)
                dt = d["date"]
                kpl_dates.append(dt)
                for p in d.get("plates", []):
                    pname = p.get("plate", "")
                    stocks = p.get("stocks", [])
                    plate_daily_sz[dt][pname] = len(stocks)
                    for s in stocks:
                        c6 = str(s[0]).strip()[:6].zfill(6)
                        rl = str(s[3]).strip() if len(s) > 3 else ""
                        r_long_map[(dt, c6)] = rl
    return r_long_map, plate_daily_sz, kpl_dates

def load_sh_index_series():
    df_sh = pd.read_pickle(SH_PKL_PATH)
    df_sh["date_str"] = df_sh["date"].dt.strftime("%Y-%m-%d")
    df_sh = df_sh.sort_values("date").reset_index(drop=True)
    sh_date_to_idx = {r.date_str: i for i, r in enumerate(df_sh.itertuples())}
    sh_rows = [[round(float(r.open), 2), round(float(r.high), 2), round(float(r.low), 2), round(float(r.close), 2), round(float(r.volume / 1e8), 2)] for r in df_sh.itertuples()]
    return df_sh, sh_date_to_idx, sh_rows

def load_v16_candidates_full(df_daily, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map):
    if os.path.exists(PKL_CACHE_FB):
        hist_fb = pd.read_pickle(PKL_CACHE_FB)
    else:
        stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata(df_daily)
        fb_all = attach_features_and_purifiers(df_daily, stock_theme_5y, pioneer_word_history, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map)
        hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy()
        hist_fb = compute_purifier_auction_scores(hist_fb)

    hist_fb["gap_days"] = (pd.to_datetime(hist_fb["d2_dt"]) - pd.to_datetime(hist_fb["dt_str"])).dt.days
    hist_fb["c6"] = hist_fb["ticker"].astype(str).str[:6]

    ind_df = pd.read_csv(CSRC_PATH)
    ind_df["c6"] = ind_df["code"].astype(str).str[-6:]
    ind_map = dict(zip(ind_df["c6"], ind_df["industry"].fillna("")))
    hist_fb["csrc_ind"] = hist_fb["c6"].map(ind_map).fillna("")

    conn_tape = sqlite3.connect(f"file:{TAPE_DB_PATH}?mode=ro", uri=True)
    tape_df = pd.read_sql_query("SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape", conn_tape)
    conn_tape.close()
    hist_fb = hist_fb.merge(tape_df.drop_duplicates(["trade_date", "sec_code"]), left_on=["dt_str", "c6"], right_on=["trade_date", "sec_code"], how="left")

    conn_ir = sqlite3.connect(f"file:{IR_DB_PATH}?mode=ro", uri=True)
    ir_df = pd.read_sql_query("SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE pub_datetime_cst IS NOT NULL", conn_ir)
    conn_ir.close()
    ir_grp = ir_df.groupby("sec_code")["pub_datetime_cst"].apply(lambda s: np.sort(s.unique())).to_dict()
    ir_7d_pit = np.zeros(len(hist_fb), dtype=bool)
    for idx, (c6, d2) in enumerate(zip(hist_fb["c6"], hist_fb["d2_dt"])):
        arr = ir_grp.get(c6)
        if arr is not None:
            pos = np.searchsorted(arr, f"{d2} 09:25:00", side="left")
            if pos > 0 and 0 <= (pd.Timestamp(d2) - pd.Timestamp(arr[pos - 1][:10])).days <= 8:
                ir_7d_pit[idx] = True
    hist_fb["has_ir_pit"] = ir_7d_pit

    valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
    pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median"))
    pg_m = pg[pg["p_sz_max"] >= 2].copy()
    pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
    hist_fb = hist_fb.merge(pg_m[["d2_dt", "plate", "rk_theme", "p_theme_med"]], on=["d2_dt", "plate"], how="left")

    hist_fb["is_st"] = hist_fb["name"].str.contains("ST|退", case=False, regex=True)
    hist_fb = compute_v16_features_and_scores(hist_fb)
    return hist_fb
