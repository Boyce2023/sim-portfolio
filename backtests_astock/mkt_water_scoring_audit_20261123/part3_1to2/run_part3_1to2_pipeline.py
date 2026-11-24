#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part 3 (1to2 V19): Un-truncated Clean Candidate Pool & T-1 Market Water Scoring Audit.
100% local read-only inputs. Zero yfinance. Zero network calls. Zero lookahead.
"""
import itertools
import json
import math
import os
import sys
import time
import warnings
import numpy as np
import pandas as pd
import scipy.stats as stats

warnings.filterwarnings("ignore", category=FutureWarning)
assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part3_1to2"
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117")
sys.path.insert(0, f"{SIM}/scripts")
import upgrade_1to2_pit as u12
import astock_mkt_water_chart as mwc

FEE_RATE = 0.0020
CANON_5Y_START = "2021-11-15"
DATA_END_DT = "2026-11-16"
IS_END = "2023-12-31"
OOS_START = "2024-01-01"
OOS_END = "2026-11-12"


def load_daily_adj_map():
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    da = pd.read_parquet(
        f"{SIM}/data/cn_hk_price_db/a_daily.parquet",
        columns=cols,
        filters=[("date", ">=", pd.Timestamp("2021-09-01")), ("date", "<=", pd.Timestamp("2026-11-20"))],
    )
    dd = pd.read_parquet(
        f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet",
        columns=cols,
        filters=[("date", ">=", pd.Timestamp("2021-09-01")), ("date", "<=", pd.Timestamp("2026-11-20"))],
    )
    delisted_c6 = set(dd["ticker"].astype(str).str[:6].unique())
    df_d = pd.concat([da, dd], ignore_index=True)
    df_d["c6"] = df_d["ticker"].astype(str).str[:6]
    df_d = df_d[df_d["c6"].str.startswith(("00", "60")) & (~df_d["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df_d["dt_s"] = df_d["date"].dt.strftime("%Y-%m-%d")
    df_d.sort_values(["c6", "dt_s"], inplace=True)
    df_d.drop_duplicates(["c6", "dt_s"], keep="first", inplace=True)
    df_d["adjf"] = np.where(df_d["close"] > 0, df_d["adj_close"] / df_d["close"], 1.0)
    g = df_d.groupby("c6")
    df_d["prev_c_adj"] = g["close"].shift(1) * g["adjf"].shift(1) / df_d["adjf"]
    df_d["dt_px"] = np.floor(df_d["prev_c_adj"] * 0.90 * 100.0 + 0.5) / 100.0
    df_d["zt_px"] = np.floor(df_d["prev_c_adj"] * 1.10 * 100.0 + 0.5) / 100.0
    df_d["is_dt_exact"] = (df_d["close"] <= df_d["dt_px"] + 0.005) & (df_d["prev_c_adj"] > 0)
    df_d["is_yizi_dt"] = df_d["is_dt_exact"] & (df_d["open"] <= df_d["dt_px"] + 0.005) & (df_d["high"] <= df_d["dt_px"] + 0.005)
    by_c = {c6: grp.reset_index(drop=True) for c6, grp in df_d.groupby("c6")}
    dmap = {(r.c6, r.dt_s): r for r in df_d.itertuples(index=False)}
    return by_c, dmap, delisted_c6


def build_water_t1_df() -> pd.DataFrame:
    """Exact copy of astock_mkt_water_chart.compute_daily_water() shifted T-1 BEFORE >= 2021-11-15 slice."""
    cols_p = ["ticker", "date", "open", "high", "low", "close", "amount"]
    df = pd.concat([
        pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", columns=cols_p),
        pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=cols_p),
    ], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[df["date"] >= "2021-09-01"].copy()
    df["code6"] = df["ticker"].astype(str).str.extract(r"(\d{6})")[0]
    df = df[df["code6"].str.startswith(("00", "60"), na=False)].copy()
    df = df.sort_values(["code6", "date"]).reset_index(drop=True)

    df["pre_c"] = df.groupby("code6")["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["zt_px"] = (df["pre_c"] * 1.10).round(2)
    df["dt_px"] = (df["pre_c"] * 0.90).round(2)
    df["is_zt"] = (df["close"] >= df["zt_px"] - 0.005) & (df["pre_c"] > 0) & (df["pct"] >= 0.095)
    df["is_dt"] = (df["close"] <= df["dt_px"] + 0.005) & (df["pre_c"] > 0) & (df["pct"] <= -0.095)
    df["is_zb"] = (df["high"] >= df["zt_px"] - 0.005) & (~df["is_zt"]) & (df["pre_c"] > 0)
    df["prev_zt"] = df.groupby("code6")["is_zt"].shift(1).astype("boolean").fillna(False).astype(bool)

    z = df["is_zt"].astype(int).values
    codes = df["code6"].values
    streak = np.zeros(len(df), dtype=np.int16)
    for i in range(len(df)):
        if z[i] == 1:
            streak[i] = (streak[i - 1] + 1) if (i > 0 and codes[i] == codes[i - 1]) else 1
    df["streak"] = streak

    g = df.groupby("date")
    mkt = pd.DataFrame({
        "zt_cnt": g["is_zt"].sum(),
        "dt_cnt": g["is_dt"].sum(),
        "zb_cnt": g["is_zb"].sum(),
        "max_board": g["streak"].max(),
    })
    gp = df[df["prev_zt"]].groupby("date")
    mkt["zt_prem"] = gp["pct"].mean() * 100.0
    mkt["zb_rate"] = mkt["zb_cnt"] / (mkt["zt_cnt"] + mkt["zb_cnt"]).clip(lower=1) * 100.0
    mkt["prem_3d"] = mkt["zt_prem"].rolling(3).mean()
    mkt["dt_3d"] = mkt["dt_cnt"].rolling(3).sum()
    mkt["max_b_drop5"] = mkt["max_board"].rolling(5).max() - mkt["max_board"]
    mkt = mkt.sort_index()

    zb = mkt["zb_rate"].values
    d3 = mkt["dt_3d"].fillna(0.0).values
    p3 = mkt["prem_3d"].fillna(1.5).values
    mbd = mkt["max_b_drop5"].fillna(0.0).values
    mkt["s_zb"] = np.where(
        (zb >= 25) & (zb <= 40),
        70 + 30 * (1 - np.abs(zb - 32.5) / 7.5),
        np.where(zb > 40, np.clip(70 * (1 - (zb - 40) / 20.0), 0, 70), np.clip(70 * (1 - (25 - zb) / 15.0), 0, 70)),
    )
    mkt["s_mb"] = np.clip(25.0 + mbd * 25.0, 0, 100)
    mkt["s_dt"] = np.clip(d3 / 60.0 * 100.0, 0, 100)
    mkt["s_p3"] = np.where(
        p3 <= 1.0,
        np.clip(70 + np.maximum(0, 1.0 - p3) / 2.0 * 30.0, 70, 100),
        np.where(p3 <= 3.0, 70 - (p3 - 1.0) / 2.0 * 40.0, np.clip(30 * (1 - (p3 - 3.0) / 2.0), 0, 30)),
    )
    mkt["v2_idx"] = 0.25 * (mkt["s_zb"] + mkt["s_dt"] + mkt["s_p3"] + mkt["s_mb"])
    cols = ["zb_rate", "max_b_drop5", "dt_3d", "prem_3d", "v2_idx", "s_zb", "s_mb", "s_dt", "s_p3"]
    w_t1 = mkt[cols].shift(1).copy()
    w_t1.columns = [f"{c}_t1" for c in cols]
    w_t1 = w_t1[w_t1.index >= "2021-11-15"].copy()
    # Cross-check parity vs astock_mkt_water_chart.compute_daily_water()
    ref_mkt = mwc.compute_daily_water()
    diff_v2 = float((w_t1.loc["2021-11-16":, "v2_idx_t1"] - ref_mkt.loc["2021-11-16":, "v2_idx_t1"]).abs().max())
    assert diff_v2 < 1e-10, f"Water parity check failed: {diff_v2}"
    return w_t1


def build_clean_candidate_pool():
    t0 = time.time()
    print("[1/4] Building PIT signals, T-1 market water, and Red-Team clean pool...")
    ctx = u12.build_signals_and_data_pit(DATA_END_DT)
    by_c, dmap, delisted_c6 = load_daily_adj_map()
    w_t1 = build_water_t1_df()

    hf = ctx["hist_fb"].copy()
    m5y = (hf["d2_dt"] >= CANON_5Y_START) & (hf["d2_dt"] <= DATA_END_DT)

    common_ok = hf["is_buyable_open"] & (~hf["nuclear_halt"]) & (~hf["promo_freeze"])
    pass_l1 = ~hf["is_event_basket"]
    pass_l2 = ~hf["is_dying_pulse"]
    pass_l3 = (hf["plate_fb_cnt"] <= 1) | (
        (hf["plate_peers_open_avg"] >= -0.010)
        & ((hf["plate_d2_open_avg"] >= -0.005) | (hf["plate_high_open_cnt"] >= 2))
    )
    pass_ac = ~(hf["p_sz"] > 35) & (~hf["notice_bad"])
    wk_mask = hf["gap_days"] >= 3
    open_in_win = (wk_mask & hf["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hf["d2_o_pct"].between(0.022, 0.078))
    p_tight = hf["d1_seal_tightness"] >= 37.0
    pass_nd_true = (~((hf["p_sz"] >= 2) & (hf["true_buy_rk"] >= 3))) & (
        ~((hf["plate_d2_yizi_cnt"] >= 1) & (hf["d1_seal_tightness"] < 15.0))
    )

    csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hf["csrc_ind"]]
    is_hard_tech = hf["plate"].astype(str).str.contains(
        r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)",
        regex=True,
    ).values
    has_ma_hard = (hf["notice_hard"] | hf["is_ma"]).values
    is_pure_outsider = np.array(
        [ht and (cs in u12.CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)],
        dtype=bool,
    )
    name_sub20 = np.where(is_pure_outsider, -20.0, 0.0)
    flc, tbrk, myz = hf["front_lock_cnt"].values, hf["true_buy_rk"].values, hf["mkt_yizi_cnt"].values
    is_super_wave = (hf["rk_theme"] == 1) & (hf["p_sz"] >= 8) & (tbrk == 1)
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
    sp_v = hf["s_prior_wk"].values + name_sub20 + y_v17 * 0.5

    valid_plate = hf[(hf["plate"] != "其他") & (~hf["is_event_basket"])].copy()
    pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median"))
    pg_m = pg[pg["p_sz_max"] >= 2].copy()
    pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
    daily_t1 = pg_m[pg_m["rk_theme"] == 1].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t2 = pg_m[pg_m["rk_theme"] == 2].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t3 = pg_m[pg_m["rk_theme"] == 3].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    t1_med_map = daily_t1["p_theme_med"].to_dict()
    t3_med_map = daily_t3["p_theme_med"].to_dict()
    _t1m = hf["d2_dt"].map(t1_med_map).fillna(0.0).values
    _t3m = hf["d2_dt"].map(t3_med_map).fillna(0.0).values
    v18_dom_t3 = (_t1m >= 65.0) & (_t1m - _t3m >= 35.0) & (_t3m < 42.0)
    sc_t3_pen = np.where(v18_dom_t3 & (hf["rk_theme"].values >= 3), -15.0, 0.0)

    dom_cond_days = {}
    melee_days = set()
    for d in sorted(daily_t1.index):
        t1_row = daily_t1.loc[d]
        t2_row = daily_t2.loc[d] if d in daily_t2.index else None
        t3_row = daily_t3.loc[d] if d in daily_t3.index else None
        t1_med = float(t1_row["p_theme_med"])
        t2_med = float(t2_row["p_theme_med"]) if t2_row is not None else 0.0
        t1_sz = int(t1_row["p_sz_max"])
        t2_sz = int(t2_row["p_sz_max"]) if t2_row is not None else 1
        if ((t1_med - t2_med) >= 20.0) or ((t1_sz >= 6) and (t1_sz / max(1, t2_sz) >= 2.0)):
            dom_cond_days[d] = str(t1_row["plate"])
        if t1_row is not None and t2_row is not None and t3_row is not None:
            t3_med = float(t3_row["p_theme_med"])
            sz_max = max(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            sz_min = min(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            if (t1_med - t3_med) <= 15.0 and sz_max <= 5 and sz_min >= 2:
                melee_days.add(d)

    hf["thr_vec"] = np.where(hf["mkt_seal_rate"] > 0.75, 329.8, 304.8)
    hf["sc_t3_pen"] = sc_t3_pen
    hf["elig_t1"] = common_ok & open_in_win & (sp_v >= 45.0) & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac & p_tight
    hf["elig_mon"] = common_ok & wk_mask & hf["d2_o_pct"].between(0.015, 0.090) & (sp_v >= 38.0) & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac & p_tight
    hf["elig_t2"] = (
        common_ok & (hf["p_sz"] == 1)
        & (hf["is_pioneer_word"] | hf["notice_hard"] | hf["is_ma"] | hf["has_new_term"] | hf["own_new_term"])
        & hf["d2_o_pct"].between(0.035, 0.078) & (hf["buyable_mkt_open_rk"] <= 3)
        & (hf["d1_seal_tightness"] >= 15.0) & ((hf["f_dd20_d0"] <= 0.88) | (hf["clean_brk60"] == 1))
        & pass_l2 & p_tight
    )
    rk_t = hf["rk_theme"].fillna(99).values
    pos20_arr = hf["f_pos20_d0"].fillna(0.5).values
    cat_ok = (hf["notice_hard"] | hf["is_ma"] | hf["is_pioneer_word"] | hf["has_new_term"] | hf["own_new_term"]).values
    hf["elig_dom295"] = (
        common_ok & open_in_win & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac & p_tight
        & np.isin(rk_t, [2, 3]) & (tbrk == 1) & (hf["xq_pre_d2"].values < 4) & (pos20_arr <= 0.40)
        & cat_ok & (hf["lhb_lh_cnt_d1"].values == 0) & (hf["surf_yz_d1"].values != 1)
    )
    hf["mel_blk"] = [
        (d in melee_days) and (not ((mrk <= 2) or bool(nh) or bool(hm)))
        for d, mrk, nh, hm in zip(hf["d2_dt"], hf["buyable_mkt_open_rk"], hf["notice_hard"], hf["is_ma"])
    ]
    hf["t1_dom_plate"] = hf["d2_dt"].map(dom_cond_days).fillna("")
    hf["base_pass_v19"] = ctx["mask_v19"]
    hf["sv_base"] = hf["_sv_v19"]

    pool_mask = m5y & (~hf["mel_blk"]) & (((hf["elig_t1"] | hf["elig_mon"] | hf["elig_dom295"]) & (hf["score_active"] >= 250.0)) | hf["elig_t2"])
    sub = hf[pool_mask].copy().reset_index(drop=True)

    sim = u12.make_trade_sim(ctx, use_m1_d3_exempt=True)
    bars_5m = ctx["bars_5m_map"]
    all_dts = ctx["all_dts"]
    dt_to_idx = ctx["dt_to_idx"]

    pretrig_records = []
    clean_records = []
    n_5m_buy_cov, n_5m_hold_cov, n_deferred, n_exdiv, n_delisted = 0, 0, 0, 0, 0
    delisted_trades = []
    for idx_r, row in enumerate(sub.itertuples(index=False)):
        rdict = row._asdict()
        w_row = w_t1.loc[row.d2_dt]
        common_meta = {
            "buy_date": str(row.d2_dt),
            "code": str(row.c6).zfill(6),
            "name": str(row.name),
            "base_score": round(float(row.score_active), 2),
            "zb_rate_t1": round(float(w_row["zb_rate_t1"]), 4),
            "max_b_drop5_t1": float(w_row["max_b_drop5_t1"]),
            "dt_3d_t1": float(w_row["dt_3d_t1"]),
            "prem_3d_t1": round(float(w_row["prem_3d_t1"]), 4),
            "v2_idx_t1": round(float(w_row["v2_idx_t1"]), 4),
            "s_zb_t1": round(float(w_row["s_zb_t1"]), 4),
            "s_mb_t1": round(float(w_row["s_mb_t1"]), 4),
            "s_dt_t1": round(float(w_row["s_dt_t1"]), 4),
            "s_p3_t1": round(float(w_row["s_p3_t1"]), 4),
            "elig_t1": bool(row.elig_t1),
            "elig_mon": bool(row.elig_mon),
            "elig_t2": bool(row.elig_t2),
            "elig_dom295": bool(row.elig_dom295),
            "thr_vec": float(row.thr_vec),
            "sc_t3_pen": float(row.sc_t3_pen),
            "rk_theme": float(row.rk_theme) if pd.notna(row.rk_theme) else 99.0,
            "plate": str(row.plate),
            "t1_dom_plate": str(row.t1_dom_plate),
            "base_pass_v19": bool(row.base_pass_v19),
            "sv_base": float(row.sv_base),
        }

        tr = sim(rdict)
        if tr is None:
            pretrig_records.append({
                **common_meta,
                "sim_ok": False,
                "buy_hhmm": 0, "exit_date": "", "exit_hhmm": 0,
                "buy_price": np.nan, "exit_price": np.nan, "net_ret": np.nan,
                "tag": "no_trigger", "sealed_2b": 0, "exit_at_open": False,
                "d2_o_pct": float(row.d2_o_pct),
                "has_5m_buy": False, "has_5m_full": False, "is_delisted": bool(str(row.c6).zfill(6) in delisted_c6),
            })
            continue

        c6 = tr["code"]
        b_dt = tr["buy_date"]
        e_dt = tr["exit_date"]
        e_hhmm = int(tr["exit_hhmm"])
        b_px = float(tr["buy_price"])
        e_px = float(tr["exit_price"])
        e_open = bool(tr["exit_at_open"])
        tag = str(tr["tag"])

        eb = dmap[(c6, e_dt)]
        if e_hhmm >= 1455 and bool(eb.is_dt_exact):
            gc = by_c[c6]
            pe = gc.index[gc["dt_s"] == e_dt][0]
            k = pe + 1
            while k < len(gc) - 1 and bool(gc.loc[k, "is_yizi_dt"]):
                k += 1
            nb = gc.loc[k]
            e_dt = str(nb.dt_s)
            e_hhmm = 925
            e_px = round(float(nb.open), 2)
            e_open = True
            tag = "eod_dt_defer_open"
            n_deferred += 1

        bb = dmap[(c6, b_dt)]
        eb2 = dmap[(c6, e_dt)]
        adj_ratio = float(eb2.adjf) / float(bb.adjf)
        if abs(adj_ratio - 1.0) > 1e-4:
            n_exdiv += 1
        net_ret = round((e_px / b_px) * adj_ratio * (1.0 - FEE_RATE) - 1.0, 4)

        assert e_dt > b_dt, f"T+0 violation: {c6} {b_dt}->{e_dt}"
        assert not (bool(bb.open >= bb.zt_px - 0.005) and bool(bb.low >= bb.zt_px - 0.005)), f"Yizi ZT buy: {c6} {b_dt}"
        assert float(row.close) <= 60.0, f"Price >60 violation: {c6} {row.close}"
        if e_hhmm >= 1455:
            assert not bool(eb2.is_dt_exact), f"15:00 limit-down sell violation: {c6} {e_dt}"

        has_5m_b = (c6, b_dt) in bars_5m
        bi, ei = dt_to_idx[b_dt], dt_to_idx[e_dt]
        has_5m_all = all((c6, all_dts[idx]) in bars_5m for idx in range(bi, ei + 1))
        if has_5m_b:
            n_5m_buy_cov += 1
        if has_5m_all:
            n_5m_hold_cov += 1
        if c6 in delisted_c6:
            n_delisted += 1
            delisted_trades.append((b_dt, c6, tr["name"], float(row.score_active), net_ret, has_5m_all))

        trade_rec = {
            **common_meta,
            "sim_ok": True,
            "buy_hhmm": int(tr["buy_hhmm"]),
            "exit_date": e_dt,
            "exit_hhmm": e_hhmm,
            "buy_price": round(b_px, 2),
            "exit_price": round(e_px, 2),
            "net_ret": float(net_ret),
            "tag": tag,
            "sealed_2b": int(tr["sealed_2b"]),
            "exit_at_open": bool(e_open),
            "d2_o_pct": float(tr["d2_o_pct"]),
            "has_5m_buy": bool(has_5m_b),
            "has_5m_full": bool(has_5m_all),
            "is_delisted": bool(c6 in delisted_c6),
        }
        pretrig_records.append(trade_rec)
        clean_records.append(trade_rec)

    pretrig_df = pd.DataFrame(pretrig_records).sort_values(["buy_date", "base_score"], ascending=[True, False]).reset_index(drop=True)
    pool_df = pd.DataFrame(clean_records).sort_values(["buy_date", "base_score"], ascending=[True, False]).reset_index(drop=True)
    pool_df = pool_df[pool_df["base_score"] >= 250.0].reset_index(drop=True)

    # Mark pre-trigger rank-1 status under baseline V19 for downstream 5-strat combination
    v19_sub = pretrig_df[pretrig_df["base_pass_v19"]].sort_values(["buy_date", "sv_base", "code"], ascending=[True, False, True])
    v19_top1_keys = {(g.iloc[0]["buy_date"], g.iloc[0]["code"]) for _, g in v19_sub.groupby("buy_date", sort=False)}
    pool_df["is_v19_day_top1"] = [(r.buy_date, r.code) in v19_top1_keys for r in pool_df.itertuples(index=False)]

    # Save exact required CSV (clean buyable candidates >= 250) + pretrig cache for exact 09:25 ranking
    cols_out = [
        "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
        "base_score", "buy_price", "exit_price", "net_ret",
        "zb_rate_t1", "max_b_drop5_t1", "dt_3d_t1", "prem_3d_t1", "v2_idx_t1",
        "s_zb_t1", "s_mb_t1", "s_dt_t1", "s_p3_t1",
        "tag", "sealed_2b", "exit_at_open", "d2_o_pct",
        "elig_t1", "elig_mon", "elig_t2", "elig_dom295", "thr_vec", "sc_t3_pen",
        "rk_theme", "plate", "t1_dom_plate", "base_pass_v19", "is_v19_day_top1",
        "has_5m_buy", "has_5m_full", "is_delisted",
    ]
    pool_df[cols_out].to_csv(f"{OUT_DIR}/pool_1to2_full_clean.csv", index=False, encoding="utf-8-sig")
    pretrig_df.to_parquet(f"{OUT_DIR}/_cache_pretrig_pool.parquet", index=False)

    cov_info = {
        "total_pretrig_rows": int(len(pretrig_df)),
        "total_buyable_pool_rows": int(len(pool_df)),
        "unique_buy_dates": int(pool_df["buy_date"].nunique()),
        "base_pass_buyable_rows": int(pool_df["base_pass_v19"].sum()),
        "near_line_rows_lt3048": int((pool_df["base_score"] < 304.8).sum()),
        "has_5m_buy_cnt": int(n_5m_buy_cov),
        "has_5m_buy_pct": round(n_5m_buy_cov / len(pool_df) * 100.0, 2),
        "has_5m_full_cnt": int(n_5m_hold_cov),
        "has_5m_full_pct": round(n_5m_hold_cov / len(pool_df) * 100.0, 2),
        "deferred_1500_dt_cnt": int(n_deferred),
        "exdiv_adjusted_cnt": int(n_exdiv),
        "delisted_pool_cnt": int(n_delisted),
        "delisted_trades": delisted_trades,
        "build_sec": round(time.time() - t0, 1),
    }
    print(f"    Pool saved: {len(pool_df)} buyable rows (pretrig={len(pretrig_df)}), 5m_buy={cov_info['has_5m_buy_pct']}%, 5m_full={cov_info['has_5m_full_pct']}%, defer={n_deferred}, exdiv={n_exdiv}, delisted={n_delisted}")
    return pretrig_df, pool_df, cov_info


def filter_and_sim_pretrig(pretrig_df: pd.DataFrame, delta_arr: np.ndarray, force_base: bool = False):
    """Exact V19 pre-trigger ranking & dynamic day blocks (zero intraday fallback peek)."""
    if force_base:
        sub = pretrig_df[pretrig_df["base_pass_v19"]].copy()
        sub["_sv"] = sub["sv_base"]
        sub["_score_adj"] = sub["base_score"]
    else:
        sc_adj = pretrig_df["base_score"].to_numpy() + delta_arr
        m_t1 = pretrig_df["elig_t1"].to_numpy() & (sc_adj >= pretrig_df["thr_vec"].to_numpy())
        m_t2 = pretrig_df["elig_t2"].to_numpy()
        m_mon = pretrig_df["elig_mon"].to_numpy() & (sc_adj >= pretrig_df["thr_vec"].to_numpy())
        m_dom = pretrig_df["elig_dom295"].to_numpy() & ((sc_adj - pretrig_df["sc_t3_pen"].to_numpy()) >= 295.0)
        tot_v18 = m_t1 | m_t2 | m_mon
        tot_v19 = tot_v18 | m_dom
        if not tot_v19.any():
            return [], []

        sv = np.where(m_t1 | m_t2, sc_adj + 1000.0, np.where(m_mon, sc_adj, sc_adj + 500.0))
        sub = pretrig_df[tot_v19].copy()
        sub["_sv"] = sv[tot_v19]
        sub["_score_adj"] = sc_adj[tot_v19]
        sub["_is_v18"] = tot_v18[tot_v19]

        bad_dts = set()
        dom_no_dragon = set()
        for d, grp in sub.groupby("buy_date", sort=False):
            if (grp["rk_theme"] == 1).any():
                top_rk = grp.sort_values("_sv", ascending=False).iloc[0]["rk_theme"]
                if top_rk >= 4:
                    bad_dts.add(d)
            t1_p = grp["t1_dom_plate"].iloc[0]
            if t1_p:
                v18_g = grp[grp["_is_v18"]]
                if not (len(v18_g) > 0 and (v18_g["plate"] == t1_p).any()):
                    dom_no_dragon.add(d)

        keep = (~sub["buy_date"].isin(bad_dts)) & (~(sub["buy_date"].isin(dom_no_dragon) & (sub["rk_theme"] == 3)))
        sub = sub[keep].copy()

    if sub.empty:
        return [], []
    sub.sort_values(["buy_date", "_sv", "code"], ascending=[True, False, True], inplace=True)

    trades_1s = []
    eq_daily = []
    free_dt, free_open = "", False
    for d2, grp in sub.groupby("buy_date", sort=True):
        ok_grp = grp[grp["sim_ok"]]
        if len(ok_grp) > 0:
            eq_daily.append((d2, float(np.mean(ok_grp["net_ret"].to_numpy(dtype=float)))))
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            # Pick pre-trigger top-1 candidate at 09:25 (NO fallback if h2 < trig_p!)
            top = grp.iloc[0]
            if bool(top["sim_ok"]):
                trades_1s.append({
                    "buy_date": d2,
                    "exit_date": str(top["exit_date"]),
                    "exit_at_open": bool(top["exit_at_open"]),
                    "code": str(top["code"]).zfill(6),
                    "name": str(top["name"]),
                    "base_score": float(top["base_score"]),
                    "adj_score": float(top["_score_adj"]),
                    "net_ret": float(top["net_ret"]),
                })
                free_dt = str(top["exit_date"])
                free_open = bool(top["exit_at_open"])
    return trades_1s, eq_daily


def calc_d15_metrics(trades_1s, eq_daily, start_dt, end_dt, sh300, bench_ov=None):
    all_dts = sorted(sh300.keys())
    if bench_ov is not None:
        bench_pct = float(bench_ov)
    else:
        prevs = [d for d in all_dts if d < start_dt]
        posts = [d for d in all_dts if d <= end_dt]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_dts[0]]
        p1 = sh300[posts[-1]]
        bench_pct = float((p1 / p0 - 1.0) * 100.0)

    st = [t for t in trades_1s if start_dt <= t["buy_date"] <= end_dt]
    se = [r for d, r in eq_daily if start_dt <= d <= end_dt]
    n = len(st)
    eq_nav = float(np.prod(1.0 + np.array(se, dtype=float))) if se else 1.0
    if n == 0:
        return {
            "trades": 0, "wr": 0.0, "plr": 0.0, "nav_1s": 1.0, "mdd_pct": 0.0,
            "cap10m": 1.0, "trim3_nav": 1.0, "trim5_nav": 1.0,
            "eq_days": len(se), "eq_nav": round(eq_nav, 2),
            "csi300_pct": round(bench_pct, 2),
            "excess_1s_pp": round(-bench_pct, 2),
            "excess_eq_pp": round((eq_nav - 1.0) * 100.0 - bench_pct, 2),
            "sharpe_tr": 0.0, "calmar_log": 0.0,
        }
    rets = np.array([t["net_ret"] for t in st], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    wr = float(len(wins) / n * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0) else (99.0 if len(wins) > 0 else 0.0)
    nav, pk, mdd = 1.0, 1.0, 0.0
    cap = 100.0
    for r in rets:
        nav *= (1.0 + float(r))
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)
        cap += min(cap, 1000.0) * float(r)
    sr = np.sort(rets)
    trim3 = float(np.prod(1.0 + sr[:-3])) if n > 3 else 1.0
    trim5 = float(np.prod(1.0 + sr[:-5])) if n > 5 else 1.0
    sharpe_tr = float(rets.mean() / rets.std(ddof=1) * math.sqrt(n)) if (n > 1 and rets.std(ddof=1) > 1e-12) else 0.0
    calmar_log = float(math.log(max(nav, 1e-9)) / max(mdd, 0.05))
    return {
        "trades": n,
        "wr": round(wr, 2),
        "plr": round(plr, 2),
        "nav_1s": round(nav, 2),
        "mdd_pct": round(mdd * 100.0, 2),
        "cap10m": round(cap / 100.0, 2),
        "trim3_nav": round(trim3, 2),
        "trim5_nav": round(trim5, 2),
        "eq_days": len(se),
        "eq_nav": round(eq_nav, 2),
        "csi300_pct": round(bench_pct, 2),
        "excess_1s_pp": round((nav - 1.0) * 100.0 - bench_pct, 2),
        "excess_eq_pp": round((eq_nav - 1.0) * 100.0 - bench_pct, 2),
        "sharpe_tr": round(sharpe_tr, 3),
        "calmar_log": round(calmar_log, 3),
    }


def compute_delta(df_in: pd.DataFrame, factor: str, mode: str, step: int) -> np.ndarray:
    n = len(df_in)
    if step == 0:
        return np.zeros(n, dtype=float)
    if factor == "F1_zb":
        v = df_in["zb_rate_t1"].to_numpy()
        sweet = (v >= 25.0) & (v <= 40.0)
        danger = (v < 25.0) | (v > 40.0)
        sf = df_in["s_zb_t1"].to_numpy()
    elif factor == "F2_mbd":
        v = df_in["max_b_drop5_t1"].to_numpy()
        sweet = v >= 2.0
        danger = v <= 0.0
        sf = df_in["s_mb_t1"].to_numpy()
    elif factor == "F3_dt3":
        v = df_in["dt_3d_t1"].to_numpy()
        sweet = v >= 40.0
        danger = v <= 12.0
        sf = df_in["s_dt_t1"].to_numpy()
    elif factor == "F4_p3":
        v = df_in["prem_3d_t1"].to_numpy()
        sweet = v <= 1.0
        danger = v > 3.0
        sf = df_in["s_p3_t1"].to_numpy()
    elif factor == "F_comp":
        v = df_in["v2_idx_t1"].to_numpy()
        sweet = v >= 65.0
        danger = v < 45.0
        sf = v
    else:
        raise ValueError(factor)

    m = float(step)
    if mode == "tier_pos":
        return np.where(sweet, m, 0.0)
    if mode == "tier_neg":
        return np.where(danger, -m, 0.0)
    if mode == "tier_bi":
        return np.where(sweet, m, np.where(danger, -m, 0.0))
    if mode == "lin_pos":
        return m * np.maximum(0.0, (sf - 50.0) / 50.0)
    if mode == "lin_neg":
        return -m * np.maximum(0.0, (50.0 - sf) / 50.0)
    if mode == "lin_bi":
        return m * (sf - 50.0) / 50.0
    raise ValueError(mode)


def calc_cscv_pbo(daily_mat: np.ndarray, s_blocks: int = 10) -> dict:
    t_len, k_len = daily_mat.shape
    if k_len <= 1:
        return {"pbo_pct": 0.0, "combos": 0, "mean_omega": 0.5}
    gs = t_len // s_blocks
    gidx = [list(range(i * gs, (i + 1) * gs if i < s_blocks - 1 else t_len)) for i in range(s_blocks)]
    omegas = []
    for te in itertools.combinations(range(s_blocks), s_blocks // 2):
        trg = [x for x in range(s_blocks) if x not in te]
        tri = [i for x in trg for i in gidx[x]]
        tei = [i for x in te for i in gidx[x]]
        rt, re_ = daily_mat[tri], daily_mat[tei]
        st = np.where(rt.std(0, ddof=1) > 1e-12, rt.mean(0) / rt.std(0, ddof=1), 0.0)
        se = np.where(re_.std(0, ddof=1) > 1e-12, re_.mean(0) / re_.std(0, ddof=1), 0.0)
        best_j = int(np.argmax(st))
        better = float(np.sum(se > se[best_j]))
        ties = float(np.sum(np.isclose(se, se[best_j], atol=1e-12))) - 1.0
        omega = (better + 0.5 * max(0.0, ties)) / k_len
        omegas.append(omega)
    pbo = float(np.mean(np.array(omegas) > 0.50) * 100.0)
    return {"pbo_pct": round(pbo, 2), "combos": len(omegas), "mean_omega": round(float(np.mean(omegas)), 4)}


def main():
    t_all = time.time()
    pretrig_df, pool_df, cov_info = build_clean_candidate_pool()

    sh300 = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))["sh000300"]
    csi_canon = json.load(open(f"{SIM}/backtests_astock/clean_rebacktest_20261116/csi300_canonical_20261116.json", encoding="utf-8"))
    ref_1to2 = pd.read_csv(f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117/ledger_upg_1to2.csv")
    ref_1to2["code"] = ref_1to2["code"].astype(str).str.zfill(6)

    tr_base, eq_base = filter_and_sim_pretrig(pretrig_df, np.zeros(len(pretrig_df)), force_base=False)
    tr_base_f, eq_base_f = filter_and_sim_pretrig(pretrig_df, np.zeros(len(pretrig_df)), force_base=True)
    nav_base = round(float(np.prod([1.0 + t["net_ret"] for t in tr_base])), 2)
    nav_ref = round(float(np.prod(1.0 + ref_1to2["net_ret"])), 2)
    assert len(tr_base) == 97 and len(tr_base_f) == 97, f"Baseline trade count mismatch: {len(tr_base)}/{len(tr_base_f)} vs 97"
    assert abs(nav_base - nav_ref) < 1e-4, f"Baseline NAV mismatch: {nav_base} vs {nav_ref}"
    for tb, (_, rr) in zip(tr_base, ref_1to2.iterrows()):
        assert tb["buy_date"] == rr["buy_date"] and tb["code"] == rr["code"] and abs(tb["net_ret"] - rr["net_ret"]) < 1e-6
    print(f"[Baseline Parity PASSED] n={len(tr_base)}, 5Y_NAV={nav_base}x == ref {nav_ref}x")

    WINS = [
        ("5Y", CANON_5Y_START, DATA_END_DT, csi_canon["全五年(2021-11-16起)"][0]),
        ("IS", CANON_5Y_START, IS_END, None),
        ("OOS", OOS_START, OOS_END, csi_canon["近三年(2024-01-01起)"][0]),
        ("3Y", "2023-11-16", DATA_END_DT, csi_canon["近三年(2023-11-16起)"][0]),
        ("2026", "2026-01-01", OOS_END, csi_canon["2026全年"][0]),
    ]
    base_metrics = {wn: calc_d15_metrics(tr_base, eq_base, sd, ed, sh300, ov) for wn, sd, ed, ov in WINS}

    t_days = sorted([d for d in sh300.keys() if CANON_5Y_START <= d <= DATA_END_DT])
    day_idx = {d: i for i, d in enumerate(t_days)}

    def trades_to_daily_vec(trades):
        arr = np.zeros(len(t_days), dtype=float)
        for t in trades:
            i = day_idx.get(t["exit_date"])
            if i is not None:
                arr[i] += float(t["net_ret"])
        return arr

    print("[2/4] Running 5-factor x 6-mode x 7-step grid (strict IS <= 2023-12-31 selection)...")
    FACTORS = ["F1_zb", "F2_mbd", "F3_dt3", "F4_p3", "F_comp"]
    MODES = ["tier_pos", "tier_neg", "tier_bi", "lin_pos", "lin_neg", "lin_bi"]
    STEPS = [0, 5, 10, 15, 20, 25, 30]

    all_daily_cols = [trades_to_daily_vec(tr_base)]
    grid_records = []
    factor_summaries = {}

    for fac in FACTORS:
        fac_daily_cols = [trades_to_daily_vec(tr_base)]
        fac_configs = [{
            "factor": fac, "mode": "baseline", "step": 0,
            "IS": base_metrics["IS"], "OOS": base_metrics["OOS"],
            "5Y": base_metrics["5Y"], "3Y": base_metrics["3Y"], "2026": base_metrics["2026"],
        }]
        for mode in MODES:
            for step in STEPS:
                if step == 0:
                    continue
                delta = compute_delta(pretrig_df, fac, mode, step)
                tr, eq = filter_and_sim_pretrig(pretrig_df, delta, force_base=False)
                m_dict = {wn: calc_d15_metrics(tr, eq, sd, ed, sh300, ov) for wn, sd, ed, ov in WINS}
                cfg = {"factor": fac, "mode": mode, "step": step, **m_dict}
                fac_configs.append(cfg)
                grid_records.append(cfg)
                dv = trades_to_daily_vec(tr)
                fac_daily_cols.append(dv)
                all_daily_cols.append(dv)

        def is_obj(c):
            return (c["IS"]["calmar_log"], c["IS"]["nav_1s"], -c["step"])

        def pick_best(cands):
            elig = [c for c in cands if c["IS"]["trades"] >= 30]
            return max(elig if elig else cands, key=is_obj)

        best_calmar = pick_best(fac_configs)
        best_is_nav = max(fac_configs, key=lambda c: (c["IS"]["nav_1s"], c["IS"]["calmar_log"], -c["step"]))
        best_pos = pick_best([c for c in fac_configs if c["mode"] in ("baseline", "tier_pos", "lin_pos")])
        best_neg = pick_best([c for c in fac_configs if c["mode"] in ("baseline", "tier_neg", "lin_neg")])
        best_bi = pick_best([c for c in fac_configs if c["mode"] in ("baseline", "tier_bi", "lin_bi")])
        best_is_eq = max(fac_configs, key=lambda c: (c["IS"]["eq_nav"], -c["step"]))

        def get_neighbor(target_cfg, offset):
            ns = target_cfg["step"] + offset
            if ns < 0 or ns > 30:
                return None
            if ns == 0:
                return fac_configs[0]
            for c in fac_configs:
                if c["mode"] == target_cfg["mode"] and c["step"] == ns:
                    return c
            return None

        nb_left = get_neighbor(best_calmar, -5)
        nb_right = get_neighbor(best_calmar, +5)
        nb_neg_left = get_neighbor(best_neg, -5)
        nb_neg_right = get_neighbor(best_neg, +5)
        pbo_fac = calc_cscv_pbo(np.column_stack(fac_daily_cols), s_blocks=10)
        # PBO within neg_only subset (baseline + tier_neg + lin_neg)
        neg_idx = [0] + [i + 1 for i, c in enumerate(fac_configs[1:]) if c["mode"] in ("tier_neg", "lin_neg")]
        pbo_neg = calc_cscv_pbo(np.column_stack([fac_daily_cols[i] for i in neg_idx]), s_blocks=10)

        # Also check trade diffs between best_calmar / best_neg and baseline
        def diff_trades(cfg):
            d_arr = compute_delta(pretrig_df, fac, cfg["mode"], cfg["step"]) if cfg["step"] > 0 else np.zeros(len(pretrig_df))
            tr_c, _ = filter_and_sim_pretrig(pretrig_df, d_arr, force_base=False)
            kb = {(t["buy_date"], t["code"]): t for t in tr_base}
            kw = {(t["buy_date"], t["code"]): t for t in tr_c}
            return [kw[k] for k in sorted(set(kw) - set(kb))], [kb[k] for k in sorted(set(kb) - set(kw))]

        added_trades, dropped_trades = diff_trades(best_calmar)
        added_neg, dropped_neg = diff_trades(best_neg)

        factor_summaries[fac] = {
            "is_best_calmar": best_calmar,
            "is_best_nav": best_is_nav,
            "is_best_eq": best_is_eq,
            "is_best_pos_only": best_pos,
            "is_best_neg_only": best_neg,
            "is_best_bidir": best_bi,
            "neighbor_minus5": nb_left,
            "neighbor_plus5": nb_right,
            "neg_neighbor_minus5": nb_neg_left,
            "neg_neighbor_plus5": nb_neg_right,
            "cscv_pbo": pbo_fac,
            "cscv_pbo_neg_only": pbo_neg,
            "added_vs_base": added_trades,
            "dropped_vs_base": dropped_trades,
            "neg_added_vs_base": added_neg,
            "neg_dropped_vs_base": dropped_neg,
        }

    # Global PBO for neg_only across all 5 factors
    neg_global_cols = [all_daily_cols[0]]
    col_ptr = 1
    for fac in FACTORS:
        for mode in MODES:
            for step in STEPS:
                if step == 0:
                    continue
                if mode in ("tier_neg", "lin_neg"):
                    neg_global_cols.append(all_daily_cols[col_ptr])
                col_ptr += 1
    global_pbo = calc_cscv_pbo(np.column_stack(all_daily_cols), s_blocks=10)
    global_pbo_neg = calc_cscv_pbo(np.column_stack(neg_global_cols), s_blocks=10)
    assert pool_df[["zb_rate_t1", "max_b_drop5_t1", "dt_3d_t1", "prem_3d_t1", "v2_idx_t1"]].isna().sum().sum() == 0, "NaNs found in water T-1"
    all_cands_flat = [factor_summaries[f]["is_best_calmar"] for f in FACTORS]
    global_is_best = max(all_cands_flat, key=lambda c: (c["IS"]["calmar_log"], c["IS"]["nav_1s"]))

    corr_stats = {}
    for col, fname in [
        ("zb_rate_t1", "F1_zb"), ("max_b_drop5_t1", "F2_mbd"),
        ("dt_3d_t1", "F3_dt3"), ("prem_3d_t1", "F4_p3"), ("v2_idx_t1", "F_comp"),
        ("s_zb_t1", "s_zb"), ("s_mb_t1", "s_mb"), ("s_dt_t1", "s_dt"), ("s_p3_t1", "s_p3"),
    ]:
        is_p = pool_df[pool_df["buy_date"] <= IS_END]
        oos_p = pool_df[pool_df["buy_date"] >= OOS_START]
        r_all, p_all = stats.spearmanr(pool_df[col], pool_df["net_ret"])
        r_is, p_is = stats.spearmanr(is_p[col], is_p["net_ret"])
        r_oos, p_oos = stats.spearmanr(oos_p[col], oos_p["net_ret"])
        b_df = pool_df[pool_df["base_pass_v19"]]
        r_b, p_b = stats.spearmanr(b_df[col], b_df["net_ret"])
        corr_stats[fname] = {
            "pool_all_r": round(float(r_all), 4), "pool_all_p": round(float(p_all), 4),
            "pool_is_r": round(float(r_is), 4), "pool_is_p": round(float(p_is), 4),
            "pool_oos_r": round(float(r_oos), 4), "pool_oos_p": round(float(p_oos), 4),
            "v19_pass_r": round(float(r_b), 4), "v19_pass_p": round(float(p_b), 4),
        }

    zone_breakdown = {}
    for label, cond_fn in [
        ("pool_all", lambda d: np.ones(len(d), dtype=bool)),
        ("near_lt3048", lambda d: d["base_score"] < 304.8),
        ("v19_pass", lambda d: d["base_pass_v19"]),
    ]:
        sub_z = pool_df[cond_fn(pool_df)]
        zb_res = {}
        for zlbl, zc in [
            ("sweet_ge65", sub_z["v2_idx_t1"] >= 65.0),
            ("neut_45_65", (sub_z["v2_idx_t1"] >= 45.0) & (sub_z["v2_idx_t1"] < 65.0)),
            ("danger_lt45", sub_z["v2_idx_t1"] < 45.0),
        ]:
            sz = sub_z[zc]
            zb_res[zlbl] = {
                "n": int(len(sz)),
                "wr": round(float((sz["net_ret"] > 0).mean() * 100.0), 2) if len(sz) else 0.0,
                "mean_pct": round(float(sz["net_ret"].mean() * 100.0), 2) if len(sz) else 0.0,
            }
        zone_breakdown[label] = zb_res

    out_summary = {
        "pool_coverage": cov_info,
        "baseline_v19": base_metrics,
        "global_cscv_pbo_181configs": global_pbo,
        "global_cscv_pbo_neg_61configs": global_pbo_neg,
        "global_is_best": global_is_best,
        "factor_spearman_vs_net_ret": corr_stats,
        "v2_zone_empirical_breakdown": zone_breakdown,
        "factors": factor_summaries,
        "full_grid_180_runs": grid_records,
        "elapsed_sec": round(time.time() - t_all, 1),
    }

    out_json = f"{OUT_DIR}/results_part3_1to2.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out_summary, f, ensure_ascii=False, indent=2)

    print("\n=== SUMMARY: Baseline vs 5 Factors IS-Best (Calmar-log) ===")
    print(f"Baseline | IS: {base_metrics['IS']['trades']}b NAV={base_metrics['IS']['nav_1s']}x MDD={base_metrics['IS']['mdd_pct']}% EQ={base_metrics['IS']['eq_nav']}x"
          f" | OOS: {base_metrics['OOS']['trades']}b NAV={base_metrics['OOS']['nav_1s']}x MDD={base_metrics['OOS']['mdd_pct']}% EQ={base_metrics['OOS']['eq_nav']}x"
          f" | 2026: {base_metrics['2026']['trades']}b NAV={base_metrics['2026']['nav_1s']}x"
          f" | 5Y: {base_metrics['5Y']['trades']}b NAV={base_metrics['5Y']['nav_1s']}x T3={base_metrics['5Y']['trim3_nav']}x T5={base_metrics['5Y']['trim5_nav']}x")
    for f in FACTORS:
        b = factor_summaries[f]["is_best_calmar"]
        pbo = factor_summaries[f]["cscv_pbo"]["pbo_pct"]
        nl = factor_summaries[f]["neighbor_minus5"]
        nr = factor_summaries[f]["neighbor_plus5"]
        nl_str = f"{nl['OOS']['nav_1s']}x/{nl['5Y']['nav_1s']}x" if nl else "N/A"
        nr_str = f"{nr['OOS']['nav_1s']}x/{nr['5Y']['nav_1s']}x" if nr else "N/A"
        print(f"{f:<7} ({b['mode']} {b['step']:>2}) | IS: {b['IS']['trades']}b {b['IS']['nav_1s']}x MDD={b['IS']['mdd_pct']}% EQ={b['IS']['eq_nav']}x"
              f" | OOS: {b['OOS']['trades']}b {b['OOS']['nav_1s']}x MDD={b['OOS']['mdd_pct']}% EQ={b['OOS']['eq_nav']}x"
              f" | 2026: {b['2026']['trades']}b {b['2026']['nav_1s']}x | 5Y: {b['5Y']['nav_1s']}x T5={b['5Y']['trim5_nav']}x | PBO={pbo}% | -5:{nl_str} +5:{nr_str}")
    print(f"Global CSCV PBO (all configs): {global_pbo}")
    print(f"Spearman vs net_ret: {corr_stats}")
    print(f"V2 zone breakdown: {zone_breakdown}")
    print(f"Done in {out_summary['elapsed_sec']}s -> {out_json}")


if __name__ == "__main__":
    main()
