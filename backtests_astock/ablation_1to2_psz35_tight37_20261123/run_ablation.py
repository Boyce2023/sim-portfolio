#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_ablation.py
================================================================================
一进二 V19 单题材涨停上限（p_sz <= 35）与首板封板紧密度（d1_seal_tightness >= 37）
五年物理清洁消融回测（2021-11-15 ~ 2026-11-16）。

硬红线：
  1. 100% 本地只读，严禁 import yfinance (D12)、严禁 baostock 或任何外部联网。
  2. 严禁修改任何现役生产脚本或 strategy_astock.md。
  3. 严格复用 upgrade_1to2_pit.py 的全量 PIT 特征与 5m 撮合引擎，并叠加 V19.1 清洁校准
     （0 T+0 / 0 重叠 / 0 一字买 / 0 15:00 跌停卖 / 除权 adjf 复权修正），确保基准 V19
     与 ledger_1to2_v19_clean.csv 100% 零误差对齐。
  4. 检索合并本地所有已有 5m 数据源（不覆盖主源已有键值并核对日内收盘价一致），对仍缺 5m
     的样本显式报告 5m 覆盖率，分别给出全样本（引擎默认 / 保守日线）与纯 5m 覆盖子集指标。
================================================================================
"""

import json
import math
import os
import pickle
import sqlite3
import sys
import time
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
assert "baostock" not in sys.modules, "Redline violation: baostock forbidden"

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{PROJECT_ROOT}/sim-portfolio"
UPG_DIR = f"{SIM_DIR}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
OUT_DIR = f"{SIM_DIR}/backtests_astock/ablation_1to2_psz35_tight37_20261123"
REF_CLEAN_CSV = f"{SIM_DIR}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_1to2_v19_clean.csv"
os.makedirs(OUT_DIR, exist_ok=True)

if UPG_DIR not in sys.path:
    sys.path.insert(0, UPG_DIR)
import upgrade_1to2_pit as u

CANON_5Y_START = u.CANON_5Y_START
DATA_END_DT = u.DATA_END_DT
FEE_RATE = u.FEE_RATE  # 0.0020 (V19 / V19.1 canonical)


def load_daily_truth_and_adj():
    """加载主板活跃+退市全量日线，用于 V19.1 物理清洁校准与保守日线回退核对。"""
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    da = pd.read_parquet(
        f"{SIM_DIR}/data/cn_hk_price_db/a_daily.parquet",
        columns=cols,
        filters=[("date", ">=", pd.Timestamp("2021-09-01")), ("date", "<=", pd.Timestamp("2026-11-20"))],
    )
    dd = pd.read_parquet(
        f"{SIM_DIR}/data/cn_hk_price_db/a_delisted_daily.parquet",
        columns=cols,
        filters=[("date", ">=", pd.Timestamp("2021-09-01")), ("date", "<=", pd.Timestamp("2026-11-20"))],
    )
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
    df_d["is_yizi_dt"] = (
        df_d["is_dt_exact"] & (df_d["open"] <= df_d["dt_px"] + 0.005) & (df_d["high"] <= df_d["dt_px"] + 0.005)
    )
    by_c = {c6: grp.reset_index(drop=True) for c6, grp in df_d.groupby("c6")}
    dmap = {(r.c6, r.dt_s): r for r in df_d.itertuples(index=False)}
    return by_c, dmap


def enrich_local_5m_map(ctx: dict, dmap: dict) -> dict:
    """
    检索并合并本地所有已有 5m 数据源至 bars_5m_map（不覆盖主源已有键），
    并校验日内最后一条 5m 收盘与 a_daily 裸收盘一致（<0.5%）。
    """
    bars = ctx["bars_5m_map"]
    stats_add = {}

    def _try_add(key, arr, src_name):
        if key in bars or arr is None or len(arr) < 12:
            return False
        db = dmap.get(key)
        if db is None or db.close <= 0:
            return False
        if abs(float(arr[-1, 4]) - float(db.close)) / float(db.close) > 0.005:
            return False
        bars[key] = arr
        stats_add[src_name] = stats_add.get(src_name, 0) + 1
        return True

    # 1. 本地辅助 parquet 5m 源
    parquet_srcs = [
        ("gt60_5m_patch", f"{SIM_DIR}/backtests_astock/ablation_1to2_price60_20261119/gt60_5m_patch.parquet"),
        ("cand_3to4_5m", f"{SIM_DIR}/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet"),
        ("cand_4to5_5m", f"{SIM_DIR}/backtests_astock2/_archive/20261116/old_phase1_phase2_supersede/p2_4to5/cand_4to5_5m_bars.parquet"),
        ("v15_bak_5m", f"{SIM_DIR}/data/_archive/20261116_dup_pit_dbs/cand_5m_bars_v15_complete.parquet.bak"),
    ]
    for sname, path in parquet_srcs:
        if not os.path.exists(path):
            continue
        dfp = pd.read_parquet(path)
        dfp = dfp[dfp["date"].astype(str) <= DATA_END_DT].copy()
        dfp["c6"] = dfp["c6"].astype(str).str.zfill(6)
        if "hhmm_int" not in dfp.columns:
            dfp["hhmm_int"] = dfp["hhmm"].astype(int)
        dfp.sort_values(["c6", "date", "hhmm_int"], inplace=True)
        for (c6, dt), grp in dfp.groupby(["c6", "date"], sort=False):
            _try_add((c6, str(dt)[:10]), grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float), sname)

    # 2. 本地 SQLite firstboard 5m 源
    db_specs = [
        ("fb_5m_kline_db", f"{SIM_DIR}/backtests_astock2/data_5y/firstboard_5m_5y_pit.db", "firstboard_5m_kline"),
        ("fb_5m_bars_dup_db", f"{SIM_DIR}/data/_archive/20261116_dup_pit_dbs/firstboard_5m_5y_pit.db", "firstboard_5m_bars"),
    ]
    for sname, dbp, tbl in db_specs:
        if not os.path.exists(dbp):
            continue
        conn = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
        q = f"SELECT sec_code, trade_date, bar_time, open, high, low, close, volume, amount FROM {tbl} WHERE trade_date <= ?"
        df_db = pd.read_sql_query(q, conn, params=(DATA_END_DT,))
        conn.close()
        if df_db.empty:
            continue
        df_db["c6"] = df_db["sec_code"].astype(str).str.zfill(6)
        df_db["dt"] = df_db["trade_date"].astype(str).str[:10]
        # 跳过已存在的键以加速
        df_db = df_db[~df_db.set_index(["c6", "dt"]).index.isin(bars.keys())].copy()
        if df_db.empty:
            continue
        df_db["hhmm_int"] = df_db["bar_time"].astype(str).str[11:16].str.replace(":", "").astype(int)
        df_db.sort_values(["c6", "dt", "hhmm_int"], inplace=True)
        for (c6, dt), grp in df_db.groupby(["c6", "dt"], sort=False):
            _try_add((c6, dt), grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float), sname)

    # 3. 本地 PKL 5m 缓存源
    pkl_specs = [
        ("p2_5m_pkl", f"{SIM_DIR}/backtests_astock2/_archive/20261116/old_phase1_phase2_supersede/p4_pry_board/p2_5m_bars_cache.pkl", "k01"),
        ("sub2_5m_pkl", f"{SIM_DIR}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl", "k02"),
        ("s2_supp_pkl", f"{SIM_DIR}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_5m_supplement_bs.pkl", "supp"),
    ]
    for sname, pkl_p, mode in pkl_specs:
        if not os.path.exists(pkl_p):
            continue
        d_obj = pickle.load(open(pkl_p, "rb"))
        if mode == "supp":
            d_obj = d_obj.get("supp_5m", {})
        for k, val in d_obj.items():
            c6 = str(k[0]).zfill(6)
            dt = str(k[2] if mode == "k02" else k[1])[:10]
            if dt > DATA_END_DT or (c6, dt) in bars:
                continue
            if isinstance(val, np.ndarray) and len(val) >= 12:
                _try_add((c6, dt), val.astype(float), sname)
            elif isinstance(val, pd.DataFrame) and not val.empty:
                sub = val[val["date"].astype(str).str[:10] == dt] if "date" in val.columns else val
                if len(sub) >= 12:
                    hh = sub["hhmm"].astype(str).str.replace(":", "").astype(int).to_numpy()
                    arr = np.column_stack([
                        hh, sub["open"].to_numpy(), sub["high"].to_numpy(),
                        sub["low"].to_numpy(), sub["close"].to_numpy(),
                        sub["volume"].to_numpy(), sub["amount"].to_numpy(),
                    ]).astype(float)
                    _try_add((c6, dt), arr, sname)

    return stats_add


def make_clean_sim(ctx: dict, by_c: dict, dmap: dict):
    """构建带 V19.1 物理清洁校准（15:00跌停顺延 + 除权adjf复权修正）与保守日线对比的模拟器。"""
    base_sim = u.make_trade_sim(ctx, use_m1_d3_exempt=True)
    bars = ctx["bars_5m_map"]
    all_dts = ctx["all_dts"]
    dt_to_idx = ctx["dt_to_idx"]

    def sim_clean(row: dict):
        tr = base_sim(row)
        if tr is None:
            return None
        c6 = str(tr["code"]).zfill(6)
        b_dt = str(tr["buy_date"])
        e_dt = str(tr["exit_date"])
        e_hhmm = int(tr["exit_hhmm"])
        b_px = float(tr["buy_price"])
        e_px = float(tr["exit_price"])
        e_open = bool(tr["exit_at_open"])
        tag = str(tr["tag"])

        eb = dmap.get((c6, e_dt))
        if eb is not None and e_hhmm >= 1455 and bool(eb.is_dt_exact):
            gc = by_c[c6]
            hits = gc.index[gc["dt_s"] == e_dt]
            if len(hits) > 0:
                pe = hits[0]
                k = pe + 1
                while k < len(gc) - 1 and bool(gc.loc[k, "is_yizi_dt"]):
                    k += 1
                if k < len(gc):
                    nb = gc.loc[k]
                    e_dt = str(nb.dt_s)
                    e_hhmm = 925
                    e_px = round(float(nb.open), 2)
                    e_open = True
                    tag = "eod_dt_defer_open"

        bb = dmap.get((c6, b_dt))
        eb2 = dmap.get((c6, e_dt))
        adj_ratio = (float(eb2.adjf) / float(bb.adjf)) if (bb is not None and eb2 is not None and bb.adjf > 0) else 1.0
        net_ret = round((e_px / b_px) * adj_ratio * (1.0 - FEE_RATE) - 1.0, 4)

        # 5m 覆盖检查 + 保守日线回退收益率计算
        has_5m_buy = (c6, b_dt) in bars
        bi = dt_to_idx.get(b_dt, -1)
        ei = dt_to_idx.get(e_dt, -1)
        if bi >= 0 and ei >= bi:
            hold_dts = [all_dts[idx] for idx in range(bi, ei + 1)]
            cov_days = sum(1 for d in hold_dts if (c6, d) in bars)
            tot_days = len(hold_dts)
            has_5m_full = (cov_days == tot_days)
        else:
            cov_days, tot_days, has_5m_full = int(has_5m_buy), 1, has_5m_buy

        # 保守日线口径：若非涨停日线尾盘退出（e_hhmm == 1500 且无当期 5m 线跳过 10:30 检查），按 min(open, close) 退出
        cons_px = e_px
        cons_ret = net_ret
        if (not has_5m_full) and e_hhmm == 1500 and (c6, e_dt) not in bars and eb2 is not None:
            cons_px = round(min(float(eb2.open), float(eb2.close)), 2)
            cons_ret = round((cons_px / b_px) * adj_ratio * (1.0 - FEE_RATE) - 1.0, 4)

        tr_out = dict(tr)
        tr_out.update({
            "code": c6,
            "exit_date": e_dt,
            "exit_hhmm": e_hhmm,
            "exit_price": round(e_px, 2),
            "exit_at_open": e_open,
            "tag": tag,
            "net_ret": float(net_ret),
            "cons_exit_price": cons_px,
            "cons_net_ret": float(cons_ret),
            "has_5m_buy": bool(has_5m_buy),
            "has_5m_full": bool(has_5m_full),
            "cov_5m_days": int(cov_days),
            "tot_hold_days": int(tot_days),
        })
        return tr_out

    return sim_clean


def prepare_invariants(hf: pd.DataFrame):
    """预计算与 p_sz / tight 无关的 V19 特征组件，供消融网格秒级复算。"""
    wk_mask = (hf["gap_days"] >= 3).to_numpy()
    common_ok = (hf["is_buyable_open"] & (~hf["nuclear_halt"]) & (~hf["promo_freeze"])).to_numpy()
    pass_l1 = (~hf["is_event_basket"]).to_numpy()
    pass_l2 = (~hf["is_dying_pulse"]).to_numpy()
    pass_l3 = (
        (hf["plate_fb_cnt"] <= 1)
        | (
            (hf["plate_peers_open_avg"] >= -0.010)
            & ((hf["plate_d2_open_avg"] >= -0.005) | (hf["plate_high_open_cnt"] >= 2))
        )
    ).to_numpy()
    open_in_win = (
        (wk_mask & hf["d2_o_pct"].between(0.020, 0.088).to_numpy())
        | ((~wk_mask) & hf["d2_o_pct"].between(0.022, 0.078).to_numpy())
    )
    pass_nd_true = (
        (~((hf["p_sz"] >= 2) & (hf["true_buy_rk"] >= 3)))
        & (~((hf["plate_d2_yizi_cnt"] >= 1) & (hf["d1_seal_tightness"] < 15.0)))
    ).to_numpy()

    csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hf["csrc_ind"]]
    is_hard_tech = hf["plate"].astype(str).str.contains(
        r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)",
        regex=True,
    ).to_numpy()
    has_ma_hard = (hf["notice_hard"] | hf["is_ma"]).to_numpy()
    is_pure_outsider = np.array(
        [ht and (cs in u.CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)],
        dtype=bool,
    )
    name_sub20 = np.where(is_pure_outsider, -20.0, 0.0)
    flc = hf["front_lock_cnt"].to_numpy()
    tbrk = hf["true_buy_rk"].to_numpy()
    myz = hf["mkt_yizi_cnt"].to_numpy()
    is_super_wave = ((hf["rk_theme"] == 1) & (hf["p_sz"] >= 8) & (tbrk == 1)).to_numpy()
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
    sp_v = hf["s_prior_wk"].to_numpy() + name_sub20 + y_v17 * 0.5
    sc_v = hf["score_active"].to_numpy()
    thr_vec = np.where(hf["mkt_seal_rate"].to_numpy() > 0.75, 329.8, 304.8)

    valid_plate = hf[(hf["plate"] != "其他") & (~hf["is_event_basket"])].copy()
    pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(
        p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median")
    )
    pg_m = pg[pg["p_sz_max"] >= 2].copy()
    pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
    daily_t1 = pg_m[pg_m["rk_theme"] == 1].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t2 = pg_m[pg_m["rk_theme"] == 2].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t3 = pg_m[pg_m["rk_theme"] == 3].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    _t1m = hf["d2_dt"].map(daily_t1["p_theme_med"].to_dict()).fillna(0.0).to_numpy()
    _t3m = hf["d2_dt"].map(daily_t3["p_theme_med"].to_dict()).fillna(0.0).to_numpy()
    v18_dom_t3 = (_t1m >= 65.0) & (_t1m - _t3m >= 35.0) & (_t3m < 42.0)
    sc_t3_pen = np.where(v18_dom_t3 & (hf["rk_theme"].to_numpy() >= 3), -15.0, 0.0)

    rk_t = hf["rk_theme"].fillna(99).to_numpy()
    pos20_arr = hf["f_pos20_d0"].fillna(0.5).to_numpy()
    cat_ok = (hf["notice_hard"] | hf["is_ma"] | hf["is_pioneer_word"] | hf["has_new_term"] | hf["own_new_term"]).to_numpy()
    xq2_arr = hf["xq_pre_d2"].to_numpy()
    lh_arr = hf["lhb_lh_cnt_d1"].to_numpy()
    syz_arr = (hf["surf_yz_d1"] == 1).to_numpy()

    m_t1 = common_ok & open_in_win & (sp_v >= 45.0) & (sc_v >= thr_vec)
    m_t2_base = (
        common_ok
        & (hf["p_sz"] == 1).to_numpy()
        & cat_ok
        & hf["d2_o_pct"].between(0.035, 0.078).to_numpy()
        & (hf["buyable_mkt_open_rk"] <= 3).to_numpy()
        & (hf["d1_seal_tightness"] >= 15.0).to_numpy()
        & ((hf["f_dd20_d0"] <= 0.88) | (hf["clean_brk60"] == 1)).to_numpy()
    )

    return {
        "wk_mask": wk_mask, "common_ok": common_ok,
        "pass_l1": pass_l1, "pass_l2": pass_l2, "pass_l3": pass_l3,
        "open_in_win": open_in_win, "pass_nd_true": pass_nd_true,
        "sp_v": sp_v, "sc_v": sc_v, "thr_vec": thr_vec, "sc_t3_pen": sc_t3_pen,
        "m_t1": m_t1, "m_t2_base": m_t2_base, "rk_t": rk_t, "tbrk": tbrk,
        "pos20_arr": pos20_arr, "cat_ok": cat_ok, "xq2_arr": xq2_arr,
        "lh_arr": lh_arr, "syz_arr": syz_arr,
        "daily_t1": daily_t1, "daily_t2": daily_t2, "daily_t3": daily_t3,
    }


def build_variant_mask(hf: pd.DataFrame, inv: dict, max_psz, min_tight):
    """按给定的 max_psz 与 min_tight 生成 V19 完整信号掩码与排序分（含动态日过滤）。"""
    n = len(hf)
    not_bad = (~hf["notice_bad"]).to_numpy()
    pass_ac = not_bad if max_psz is None else ((hf["p_sz"].to_numpy() <= float(max_psz)) & not_bad)
    p_tight = np.ones(n, dtype=bool) if min_tight is None else (hf["d1_seal_tightness"].to_numpy() >= float(min_tight))

    mm = ((inv["m_t1"] & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & pass_ac) | (inv["m_t2_base"] & inv["pass_l2"])) & p_tight
    mmon = (
        inv["common_ok"] & inv["wk_mask"] & hf["d2_o_pct"].between(0.015, 0.090).to_numpy()
        & (inv["sp_v"] >= 38.0) & (inv["sc_v"] >= inv["thr_vec"])
        & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & pass_ac & p_tight
    )
    tot_v18 = mm | (mmon & (~mm))
    fb_dom295 = (
        inv["common_ok"] & inv["open_in_win"]
        & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & pass_ac & p_tight
        & np.isin(inv["rk_t"], [2, 3]) & (inv["tbrk"] == 1)
        & (inv["xq2_arr"] < 4) & (inv["pos20_arr"] <= 0.40) & inv["cat_ok"] & (inv["lh_arr"] == 0) & (~inv["syz_arr"])
        & ((inv["sc_v"] - inv["sc_t3_pen"]) >= 295.0)
    )
    tot_v19 = tot_v18 | fb_dom295
    sv_v19 = np.where(mm, inv["sc_v"] + 1000.0, np.where(mmon, inv["sc_v"], inv["sc_v"] + 500.0))

    daily_t1, daily_t2, daily_t3 = inv["daily_t1"], inv["daily_t2"], inv["daily_t3"]
    dom_no_dragon, melee_days = set(), set()
    for d in sorted(daily_t1.index):
        t1_row = daily_t1.loc[d]
        t2_row = daily_t2.loc[d] if d in daily_t2.index else None
        t3_row = daily_t3.loc[d] if d in daily_t3.index else None
        t1_med = float(t1_row["p_theme_med"])
        t2_med = float(t2_row["p_theme_med"]) if t2_row is not None else 0.0
        t1_sz = int(t1_row["p_sz_max"])
        t2_sz = int(t2_row["p_sz_max"]) if t2_row is not None else 1
        if ((t1_med - t2_med) >= 20.0) or ((t1_sz >= 6) and (t1_sz / max(1, t2_sz) >= 2.0)):
            sub_d = hf[(hf["d2_dt"] == d) & tot_v18]
            if not (len(sub_d) > 0 and (sub_d["plate"] == t1_row["plate"]).any()):
                dom_no_dragon.add(d)
        if t1_row is not None and t2_row is not None and t3_row is not None:
            t3_med = float(t3_row["p_theme_med"])
            sz_max = max(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            sz_min = min(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            if (t1_med - t3_med) <= 15.0 and sz_max <= 5 and sz_min >= 2:
                melee_days.add(d)

    sub_t = hf[tot_v19].copy()
    sub_t["_sv_tmp"] = sv_v19[tot_v19]
    bad_dts = set()
    for d, grp in sub_t.groupby("d2_dt"):
        if (grp["rk_theme"] == 1).any():
            top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
            if pd.notna(top_rk) and top_rk >= 4:
                bad_dts.add(d)

    res_mask = tot_v19 & (~hf["d2_dt"].isin(bad_dts)).to_numpy()
    dom_blk = np.array([(d in dom_no_dragon and rk == 3) for d, rk in zip(hf["d2_dt"], hf["rk_theme"])], dtype=bool)
    mel_blk = np.array(
        [
            (d in melee_days) and (not ((mrk <= 2) or bool(nh) or bool(hm)))
            for d, mrk, nh, hm in zip(hf["d2_dt"], hf["buyable_mkt_open_rk"], hf["notice_hard"], hf["is_ma"])
        ],
        dtype=bool,
    )
    final_mask = res_mask & (~dom_blk) & (~mel_blk)

    track = np.where(mm, "V18_main", np.where(mmon, "V18_mon", np.where(fb_dom295, "V19_fb_dom295", "")))
    return final_mask, sv_v19, tot_v19, track, bad_dts, dom_no_dragon, melee_days


def run_slot_and_eq_cached(hf: pd.DataFrame, mask: np.ndarray, sv: np.ndarray, track: np.ndarray, sim_cache: dict):
    """按单仓轮动与按日等权双口径运行，并返回完整交易及 5m 覆盖统计（严格不回退同日第2名）。"""
    m5y = (hf["d2_dt"] >= CANON_5Y_START) & (hf["d2_dt"] <= DATA_END_DT)
    use_m = mask & m5y.to_numpy()
    sub = hf[use_m].copy()
    sub["sv_ablation"] = sv[use_m]
    sub["track_ablation"] = track[use_m]
    sub.sort_values(["d2_dt", "sv_ablation", "c6"], ascending=[True, False, True], inplace=True)

    free_dt, free_open = "", False
    tr_1s = []
    eq_sigs = []
    eq_daily_rets = []
    eq_daily_rets_cons = []
    eq_daily_rets_5m = []

    for d2, grp in sub.groupby("d2_dt", sort=True):
        rows = list(grp.itertuples(index=False))
        # 单仓轮动：09:25 只选排序第一名，不因盘中未触达顺延当日第2名
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            r0 = rows[0]
            tr0 = sim_cache.get((r0.d2_dt, r0.c6))
            if tr0 is not None:
                tr_e = dict(tr0)
                tr_e.update({
                    "plate": str(r0.plate), "p_sz": int(r0.p_sz),
                    "d1_seal_tightness": round(float(r0.d1_seal_tightness), 2),
                    "rk_theme": float(r0.rk_theme) if pd.notna(r0.rk_theme) else 99.0,
                    "true_buy_rk": int(r0.true_buy_rk),
                    "sv_v19": round(float(r0.sv_ablation), 2), "track": str(r0.track_ablation),
                    "trig_p": round(float(r0.trig_p), 2),
                })
                tr_1s.append(tr_e)
                free_dt, free_open = tr0["exit_date"], tr0["exit_at_open"]

        d_r, d_rc, d_r5 = [], [], []
        for rs in rows:
            trs = sim_cache.get((rs.d2_dt, rs.c6))
            if trs is not None:
                tr_e = dict(trs)
                tr_e.update({
                    "plate": str(rs.plate), "p_sz": int(rs.p_sz),
                    "d1_seal_tightness": round(float(rs.d1_seal_tightness), 2),
                    "rk_theme": float(rs.rk_theme) if pd.notna(rs.rk_theme) else 99.0,
                    "true_buy_rk": int(rs.true_buy_rk),
                    "sv_v19": round(float(rs.sv_ablation), 2), "track": str(rs.track_ablation),
                    "trig_p": round(float(rs.trig_p), 2),
                })
                eq_sigs.append(tr_e)
                d_r.append(trs["net_ret"])
                d_rc.append(trs["cons_net_ret"])
                if trs["has_5m_full"]:
                    d_r5.append(trs["net_ret"])
        if d_r:
            eq_daily_rets.append((d2, float(np.mean(d_r))))
            eq_daily_rets_cons.append((d2, float(np.mean(d_rc))))
        if d_r5:
            eq_daily_rets_5m.append((d2, float(np.mean(d_r5))))

    return tr_1s, eq_sigs, eq_daily_rets, eq_daily_rets_cons, eq_daily_rets_5m


def calc_window_metrics(trades_1s, eq_daily, start_dt, end_dt, sh300, bench_ov=None, ret_key="net_ret"):
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

    eq_nav, eq_pk, eq_mdd = 1.0, 1.0, 0.0
    for r in se:
        eq_nav *= (1.0 + float(r))
        eq_pk = max(eq_pk, eq_nav)
        eq_mdd = max(eq_mdd, (eq_pk - eq_nav) / eq_pk)

    n = len(st)
    if n == 0:
        return {
            "trades": 0, "win_rate_pct": 0.0, "plr": 0.0, "mean_ret_pct": 0.0, "med_ret_pct": 0.0,
            "nav_1s": 1.0, "cap10m_mult": 1.0, "trim3_nav": 1.0, "mdd_1s_pct": 0.0,
            "eq_days": len(se), "eq_nav": round(eq_nav, 2), "mdd_eq_pct": round(eq_mdd * 100.0, 2),
            "csi300_pct": round(bench_pct, 2), "excess_1s_pp": round(-bench_pct, 2),
            "excess_eq_pp": round((eq_nav - 1.0) * 100.0 - bench_pct, 2),
        }

    rets = np.array([float(t[ret_key]) for t in st], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    wr = float(len(wins) / n * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0) else (99.9 if len(wins) > 0 else 0.0)

    nav, pk, mdd, cap = 1.0, 1.0, 0.0, 100.0
    for r in rets:
        nav *= (1.0 + float(r))
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)
        cap += min(cap, 1000.0) * float(r)
    trim3 = float(np.prod(1.0 + np.sort(rets)[:-3])) if n > 3 else 1.0

    return {
        "trades": int(n),
        "win_rate_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_ret_pct": round(float(rets.mean() * 100.0), 2),
        "med_ret_pct": round(float(np.median(rets) * 100.0), 2),
        "nav_1s": round(nav, 2),
        "cap10m_mult": round(cap / 100.0, 2),
        "trim3_nav": round(trim3, 2),
        "mdd_1s_pct": round(mdd * 100.0, 2),
        "eq_days": len(se),
        "eq_nav": round(eq_nav, 2),
        "mdd_eq_pct": round(eq_mdd * 100.0, 2),
        "csi300_pct": round(bench_pct, 2),
        "excess_1s_pp": round((nav - 1.0) * 100.0 - bench_pct, 2),
        "excess_eq_pp": round((eq_nav - 1.0) * 100.0 - bench_pct, 2),
    }


def verify_v191_cleanliness(trades_1s: list, dmap: dict, allow_overlap: bool = False) -> dict:
    """V19.1 物理清洁校验：0 T+0 / 0 重叠 / 0 一字买 / 0 15:00跌停卖 / 0 除权未校正 + 5m覆盖统计。"""
    t0_viol = sum(1 for t in trades_1s if t["exit_date"] <= t["buy_date"])
    overlap_viol = 0
    for i in range(len(trades_1s) - 1):
        c_t, n_t = trades_1s[i], trades_1s[i + 1]
        if n_t["buy_date"] < c_t["exit_date"] or (n_t["buy_date"] == c_t["exit_date"] and not c_t["exit_at_open"]):
            overlap_viol += 1

    yizi_buy_viol = 0
    dt_1500_viol = 0
    ex_div_err = 0
    for t in trades_1s:
        c6 = t["code"]
        bb = dmap.get((c6, t["buy_date"]))
        eb = dmap.get((c6, t["exit_date"]))
        if bb is not None and bb.zt_px > 0 and bb.open >= bb.zt_px - 0.015 and bb.low >= bb.zt_px - 0.015:
            yizi_buy_viol += 1
        if eb is not None and int(t["exit_hhmm"]) >= 1455 and bool(eb.is_dt_exact):
            dt_1500_viol += 1
        if bb is not None and eb is not None and bb.adjf > 0:
            exp_ret = (float(t["exit_price"]) / float(t["buy_price"])) * (float(eb.adjf) / float(bb.adjf)) * (1.0 - FEE_RATE) - 1.0
            if abs(exp_ret - float(t["net_ret"])) > 0.005:
                ex_div_err += 1

    ov_ok = True if allow_overlap else (overlap_viol == 0)
    assert t0_viol == 0 and ov_ok and yizi_buy_viol == 0 and dt_1500_viol == 0 and ex_div_err == 0, (
        f"Cleanliness assert failed: t0={t0_viol}, ov={overlap_viol}, yizi={yizi_buy_viol}, dt={dt_1500_viol}, div={ex_div_err}"
    )

    n = len(trades_1s)
    buy_5m_cnt = sum(1 for t in trades_1s if t["has_5m_buy"])
    full_5m_cnt = sum(1 for t in trades_1s if t["has_5m_full"])
    tot_days = sum(t["tot_hold_days"] for t in trades_1s)
    cov_days = sum(t["cov_5m_days"] for t in trades_1s)
    miss_list = [f"{t['buy_date']}:{t['code']}:{t['name']}" for t in trades_1s if not t["has_5m_full"]]

    return {
        "t0_violations": t0_viol,
        "overlap_violations": overlap_viol,
        "yizi_buy_violations": yizi_buy_viol,
        "dt_1500_violations": dt_1500_viol,
        "ex_div_unadjusted_err": ex_div_err,
        "trades_total": n,
        "trades_5m_buy_cov": buy_5m_cnt,
        "trades_5m_buy_pct": round(buy_5m_cnt / n * 100.0, 2) if n else 100.0,
        "trades_5m_full_cov": full_5m_cnt,
        "trades_5m_full_pct": round(full_5m_cnt / n * 100.0, 2) if n else 100.0,
        "hold_days_total": int(tot_days),
        "hold_days_5m_cov": int(cov_days),
        "hold_days_5m_pct": round(cov_days / tot_days * 100.0, 2) if tot_days else 100.0,
        "missing_5m_trades": miss_list,
    }


def summarize_rets(rets_list):
    n = len(rets_list)
    if n == 0:
        return {"n": 0, "win_rate_pct": 0.0, "mean_ret_pct": 0.0, "med_ret_pct": 0.0, "plr": 0.0}
    a = np.array(rets_list, dtype=float)
    w, l = a[a > 0], a[a < 0]
    plr = float(w.mean() / abs(l.mean())) if (len(w) > 0 and len(l) > 0) else (99.9 if len(w) > 0 else 0.0)
    return {
        "n": int(n),
        "win_rate_pct": round(float((a > 0).mean() * 100.0), 2),
        "mean_ret_pct": round(float(a.mean() * 100.0), 2),
        "med_ret_pct": round(float(np.median(a) * 100.0), 2),
        "plr": round(plr, 2),
    }


def main():
    t0 = time.time()
    print("=" * 80)
    print("一进二 V19 单题材涨停上限(p_sz<=35) & 首板紧密度(tight>=37) 五年清洁消融")
    print("=" * 80)

    with open(u.IDX_JSON_PATH, encoding="utf-8") as f:
        sh300 = json.load(f)["sh000300"]
    with open(u.CSI300_BENCH_FILE, encoding="utf-8") as f:
        csi_canon = json.load(f)

    windows = [
        ("5Y", CANON_5Y_START, DATA_END_DT, csi_canon["全五年(2021-11-16起)"][0]),
        ("IS", CANON_5Y_START, "2023-12-31", None),
        ("OOS", "2024-01-01", DATA_END_DT, csi_canon["近三年(2024-01-01起)"][0]),
        ("3Y", "2023-11-16", DATA_END_DT, csi_canon["近三年(2023-11-16起)"][0]),
        ("2026", "2026-01-01", DATA_END_DT, csi_canon["2026全年"][0]),
    ]

    ctx = u.build_signals_and_data_pit(DATA_END_DT)
    by_c, dmap = load_daily_truth_and_adj()
    added_5m_stats = enrich_local_5m_map(ctx, dmap)
    print(f"[5m Enrich] base=52888, extra_added={added_5m_stats}")

    hf = ctx["hist_fb"]
    inv = prepare_invariants(hf)
    sim_fn = make_clean_sim(ctx, by_c, dmap)

    # 预计算全池满足至少部分门槛的样本仿真缓存（确保全矩阵一致性与秒级响应）
    m5y = ((hf["d2_dt"] >= CANON_5Y_START) & (hf["d2_dt"] <= DATA_END_DT)).to_numpy()
    broad_pool_mask = m5y & hf["is_buyable_open"].to_numpy() & (hf["gate_ok"].to_numpy())
    print(f"[Sim Cache] Pre-simulating broad 5Y gate_ok & buyable_open pool ({broad_pool_mask.sum()} rows)...")
    sim_cache = {}
    for r in hf[broad_pool_mask].itertuples(index=False):
        tr = sim_fn(r._asdict())
        if tr is not None:
            sim_cache[(r.d2_dt, r.c6)] = tr
    print(f"[Sim Cache] Triggered trades cached: {len(sim_cache)}")

    # 1. 基准复现硬核验 (vs ledger_1to2_v19_clean.csv)
    base_mask, base_sv, _, base_track, _, _, _ = build_variant_mask(hf, inv, 35, 37.0)
    base_1s, base_eq_sigs, base_eq_d, base_eq_dc, base_eq_d5 = run_slot_and_eq_cached(hf, base_mask, base_sv, base_track, sim_cache)
    ref_clean = pd.read_csv(REF_CLEAN_CSV, dtype={"code": str})
    ref_clean["code"] = ref_clean["code"].str.zfill(6)
    assert len(base_1s) == len(ref_clean) == 97, f"Baseline trade count mismatch: {len(base_1s)} vs {len(ref_clean)}"
    max_ret_diff = max(abs(float(a["net_ret"]) - float(b.net_ret)) for a, b in zip(base_1s, ref_clean.itertuples(index=False)))
    for a, b in zip(base_1s, ref_clean.itertuples(index=False)):
        assert a["buy_date"] == b.buy_date and a["code"] == b.code and a["exit_date"] == b.exit_date, (a, b)
    assert max_ret_diff == 0.0, f"Baseline net_ret mismatch: max_diff={max_ret_diff}"
    base_clean_check = verify_v191_cleanliness(base_1s, dmap)
    assert base_clean_check["trades_5m_full_pct"] == 100.0
    print(f"[Baseline Parity PASSED] n={len(base_1s)}, max_ret_diff={max_ret_diff}, 5m_1S=100.0%")

    # 2. 运行全部消融矩阵 (Panel A: p_sz, Panel B: tightness, Panel C: Joint)
    variants = [
        # Panel A: p_sz (fix tight >= 37)
        ("A_psz_le25", "A", 25, 37.0),
        ("A_psz_le35_base", "A", 35, 37.0),
        ("A_psz_le50", "A", 50, 37.0),
        ("A_psz_le80", "A", 80, 37.0),
        ("A_psz_inf", "A", None, 37.0),
        # Panel B: tightness (fix p_sz <= 35)
        ("B_tight_ge40", "B", 35, 40.0),
        ("B_tight_ge37_base", "B", 35, 37.0),
        ("B_tight_ge30", "B", 35, 30.0),
        ("B_tight_ge20", "B", 35, 20.0),
        ("B_tight_none", "B", 35, None),
        # Panel C: Joint
        ("C_psz_inf_t37", "C", None, 37.0),
        ("C_both_inf", "C", None, None),
    ]

    variant_results = {}
    variant_trades = {}
    base_1s_map = {(t["buy_date"], t["code"]): t for t in base_1s}
    base_eq_map = {(t["buy_date"], t["code"]): t for t in base_eq_sigs}

    for vname, panel, mp, mt in variants:
        msk, sv, tot_v19, trk, bad_dts, dom_nd, mel_d = build_variant_mask(hf, inv, mp, mt)
        tr1s, eq_sigs, eq_d, eq_dc, eq_d5 = run_slot_and_eq_cached(hf, msk, sv, trk, sim_cache)
        c1s = verify_v191_cleanliness(tr1s, dmap, allow_overlap=False)
        ceq = verify_v191_cleanliness(eq_sigs, dmap, allow_overlap=True)

        # 纯 5m 覆盖子集（1S 中剥离缺 5m 样本后按单仓重排，绝不混同）
        tr1s_5m_sub = [t for t in tr1s if t["has_5m_full"]]
        tr1s_5m_free = []
        fdt, fopen = "", False
        for t in sorted(tr1s_5m_sub, key=lambda x: x["buy_date"]):
            if fdt == "" or t["buy_date"] > fdt or (t["buy_date"] == fdt and fopen):
                tr1s_5m_free.append(t)
                fdt, fopen = t["exit_date"], t["exit_at_open"]

        wins_full = {wn: calc_window_metrics(tr1s, eq_d, sd, ed, sh300, ov, ret_key="net_ret") for wn, sd, ed, ov in windows}
        wins_cons = {wn: calc_window_metrics(tr1s, eq_dc, sd, ed, sh300, ov, ret_key="cons_net_ret") for wn, sd, ed, ov in windows}
        wins_pure5m = {wn: calc_window_metrics(tr1s_5m_free, eq_d5, sd, ed, sh300, ov, ret_key="net_ret") for wn, sd, ed, ov in windows}

        cur_1s_map = {(t["buy_date"], t["code"]): t for t in tr1s}
        added_1s = sorted(set(cur_1s_map) - set(base_1s_map))
        dropped_1s = sorted(set(base_1s_map) - set(cur_1s_map))
        cur_eq_map = {(t["buy_date"], t["code"]): t for t in eq_sigs}
        added_eq = sorted(set(cur_eq_map) - set(base_eq_map))
        dropped_eq = sorted(set(base_eq_map) - set(cur_eq_map))

        variant_trades[vname] = {"tr1s": tr1s, "eq_sigs": eq_sigs, "msk": msk, "tot_v19": tot_v19, "sv": sv, "trk": trk, "bad_dts": bad_dts, "dom_nd": dom_nd, "mel_d": mel_d}
        variant_results[vname] = {
            "panel": panel, "max_p_sz": mp, "min_tight": mt,
            "passed_signals_5y": int((msk & m5y).sum()),
            "eq_triggered_signals_5y": len(eq_sigs),
            "clean_and_5m_1s": c1s,
            "clean_and_5m_eq": ceq,
            "windows_full_engine": wins_full,
            "windows_conservative_daily": wins_cons,
            "windows_pure_5m_subset": wins_pure5m,
            "diff_1s_vs_base": {
                "added": [{"buy_date": k[0], "code": k[1], "name": cur_1s_map[k]["name"], "net_ret_pct": round(cur_1s_map[k]["net_ret"]*100, 2), "cons_ret_pct": round(cur_1s_map[k]["cons_net_ret"]*100, 2), "p_sz": cur_1s_map[k]["p_sz"], "tight": cur_1s_map[k]["d1_seal_tightness"], "has_5m_full": cur_1s_map[k]["has_5m_full"]} for k in added_1s],
                "dropped": [{"buy_date": k[0], "code": k[1], "name": base_1s_map[k]["name"], "net_ret_pct": round(base_1s_map[k]["net_ret"]*100, 2), "p_sz": base_1s_map[k]["p_sz"], "tight": base_1s_map[k]["d1_seal_tightness"]} for k in dropped_1s],
            },
            "diff_eq_vs_base": {
                "added": [{"buy_date": k[0], "code": k[1], "name": cur_eq_map[k]["name"], "net_ret_pct": round(cur_eq_map[k]["net_ret"]*100, 2)} for k in added_eq],
                "dropped": [{"buy_date": k[0], "code": k[1], "name": base_eq_map[k]["name"], "net_ret_pct": round(base_eq_map[k]["net_ret"]*100, 2)} for k in dropped_eq],
            },
        }

    # 3. 详细输出新增明细 CSV: added_trades_psz_gt35.csv & added_trades_tight_lt37.csv
    def export_added_csv(mode_name, out_csv_path):
        if mode_name == "psz_gt35":
            vkey = "A_psz_inf"
            cond_fn = lambda r: r.p_sz > 35
        else:
            vkey = "B_tight_none"
            cond_fn = lambda r: r.d1_seal_tightness < 37.0

        vt = variant_trades[vkey]
        tr1s_keys = {(t["buy_date"], t["code"]) for t in vt["tr1s"]}
        eq_keys = {(t["buy_date"], t["code"]) for t in vt["eq_sigs"]}

        # 包含所有过 V19 核心门 (tot_v19) 的目标样本，显式标注是否被日拦截/是否未触发/是否进 1S
        not_bad = (~hf["notice_bad"]).to_numpy()
        pass_ac_u = not_bad if mode_name == "psz_gt35" else ((hf["p_sz"].to_numpy() <= 35) & not_bad)
        p_tight_u = (hf["d1_seal_tightness"].to_numpy() >= 37.0) if mode_name == "psz_gt35" else np.ones(len(hf), dtype=bool)
        mm_u = ((inv["m_t1"] & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & pass_ac_u) | (inv["m_t2_base"] & inv["pass_l2"])) & p_tight_u
        mmon_u = inv["common_ok"] & inv["wk_mask"] & hf["d2_o_pct"].between(0.015, 0.090).to_numpy() & (inv["sp_v"] >= 38.0) & (inv["sc_v"] >= inv["thr_vec"]) & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & pass_ac_u & p_tight_u
        fb_u = inv["common_ok"] & inv["open_in_win"] & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & pass_ac_u & p_tight_u & np.isin(inv["rk_t"], [2, 3]) & (inv["tbrk"] == 1) & (inv["xq2_arr"] < 4) & (inv["pos20_arr"] <= 0.40) & inv["cat_ok"] & (inv["lh_arr"] == 0) & (~inv["syz_arr"]) & ((inv["sc_v"] - inv["sc_t3_pen"]) >= 295.0)
        tot_u = mm_u | mmon_u | fb_u

        rows_out = []
        sub_df = hf[m5y & tot_u].sort_values(["d2_dt", "score_active"], ascending=[True, False])
        for r in sub_df.itertuples(index=False):
            if not cond_fn(r):
                continue
            k = (r.d2_dt, str(r.c6).zfill(6))
            tr = sim_cache.get(k)
            in_final = bool(vt["msk"][hf.index[(hf["d2_dt"] == r.d2_dt) & (hf["c6"] == r.c6)][0]])
            blk_reasons = []
            if not in_final:
                if r.d2_dt in vt["bad_dts"]:
                    blk_reasons.append("usurpation_bad_day")
                if r.d2_dt in vt["dom_nd"] and r.rk_theme == 3:
                    blk_reasons.append("dom_no_dragon_rk3")
                if r.d2_dt in vt["mel_d"] and not ((r.buyable_mkt_open_rk <= 2) or r.notice_hard or r.is_ma):
                    blk_reasons.append("melee_day_block")

            # 检查同一天或重叠期原有 1S 交易
            overlapping_base = [
                f"{bt['buy_date']}->{bt['exit_date']} {bt['code']} {bt['name']}({bt['net_ret']*100:+.2f}%)"
                for bt in base_1s
                if not (bt["exit_date"] < r.d2_dt or bt["buy_date"] > (tr["exit_date"] if tr else r.d2_dt))
                and not (bt["exit_date"] == r.d2_dt and bt["exit_at_open"])
            ]
            rows_out.append({
                "buy_date": r.d2_dt,
                "code": str(r.c6).zfill(6),
                "name": str(r.name),
                "plate": str(r.plate),
                "p_sz": int(r.p_sz),
                "d1_seal_tightness": round(float(r.d1_seal_tightness), 2),
                "score_active": round(float(r.score_active), 2),
                "rk_theme": float(r.rk_theme) if pd.notna(r.rk_theme) else 99.0,
                "true_buy_rk": int(r.true_buy_rk),
                "d2_o_pct": round(float(r.d2_o_pct) * 100.0, 2),
                "trig_p": round(float(r.trig_p), 2),
                "in_final_v19_mask": in_final,
                "block_reason": "|".join(blk_reasons) if blk_reasons else "NONE",
                "triggered_buy": tr is not None,
                "in_eq_pool": k in eq_keys,
                "in_1s_slot": k in tr1s_keys,
                "displaced_base_1s_count": len(variant_results[vkey]["diff_1s_vs_base"]["dropped"]),
                "overlapping_or_sameday_base_1s": " ; ".join(overlapping_base) if overlapping_base else "NONE",
                "buy_price": tr["buy_price"] if tr else np.nan,
                "exit_date": tr["exit_date"] if tr else "",
                "exit_hhmm": tr["exit_hhmm"] if tr else 0,
                "exit_price": tr["exit_price"] if tr else np.nan,
                "net_ret_pct": round(tr["net_ret"] * 100.0, 2) if tr else np.nan,
                "cons_exit_price": tr["cons_exit_price"] if tr else np.nan,
                "cons_net_ret_pct": round(tr["cons_net_ret"] * 100.0, 2) if tr else np.nan,
                "tag": tr["tag"] if tr else "no_trig_before_1130",
                "has_5m_buy": tr["has_5m_buy"] if tr else ((str(r.c6).zfill(6), r.d2_dt) in ctx["bars_5m_map"]),
                "has_5m_full": tr["has_5m_full"] if tr else False,
                "is_924_1008_rescue": bool("2024-09-24" <= r.d2_dt <= "2024-10-08"),
            })
        df_csv = pd.DataFrame(rows_out)
        df_csv.to_csv(out_csv_path, index=False, encoding="utf-8-sig")
        return rows_out

    added_psz_rows = export_added_csv("psz_gt35", f"{OUT_DIR}/added_trades_psz_gt35.csv")
    added_tight_rows = export_added_csv("tight_lt37", f"{OUT_DIR}/added_trades_tight_lt37.csv")

    # 4. 全池对比统计（严格区分 924/1008 救市日 vs 常规主线高潮日，覆盖 4 个漏斗层级）
    not_bad = (~hf["notice_bad"]).to_numpy()
    p_t37 = (hf["d1_seal_tightness"] >= 37.0).to_numpy()
    lvl_masks = {
        "L1_full_v19_ex_psz": (
            m5y & ((inv["m_t1"] & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & not_bad)
                   | (inv["m_t2_base"] & inv["pass_l2"])
                   | (inv["common_ok"] & inv["wk_mask"] & hf["d2_o_pct"].between(0.015, 0.090).to_numpy() & (inv["sp_v"] >= 38.0) & (inv["sc_v"] >= inv["thr_vec"]) & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & not_bad)
                   | (inv["common_ok"] & inv["open_in_win"] & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & not_bad & np.isin(inv["rk_t"], [2, 3]) & (inv["tbrk"] == 1) & (inv["xq2_arr"] < 4) & (inv["pos20_arr"] <= 0.40) & inv["cat_ok"] & (inv["lh_arr"] == 0) & (~inv["syz_arr"]) & ((inv["sc_v"] - inv["sc_t3_pen"]) >= 295.0)))
            & p_t37
        ),
        "L2_hard_gates_nd_no_score": m5y & inv["common_ok"] & inv["open_in_win"] & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & not_bad & p_t37,
        "L3_hard_gates_all_rk_no_score": m5y & inv["common_ok"] & inv["open_in_win"] & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & not_bad & p_t37,
        "L4_buyable_gate_open_broad": m5y & hf["gate_ok"].to_numpy() & hf["is_buyable_open"].to_numpy() & not_bad & p_t37,
    }

    def eval_pool_slice(sub_mask):
        sub = hf[sub_mask]
        rets, cons_rets, rets_5m = [], [], []
        for r in sub.itertuples(index=False):
            tr = sim_cache.get((r.d2_dt, r.c6))
            if tr is not None:
                rets.append(tr["net_ret"])
                cons_rets.append(tr["cons_net_ret"])
                if tr["has_5m_full"]:
                    rets_5m.append(tr["net_ret"])
        return {
            "candidates": int(len(sub)),
            "triggered": summarize_rets(rets),
            "triggered_conservative_daily": summarize_rets(cons_rets),
            "triggered_pure_5m_only": summarize_rets(rets_5m),
        }

    psz_pool_stats = {}
    is_rescue_924 = hf["d2_dt"].between("2024-09-24", "2024-10-08").to_numpy()
    is_rescue_924_ext = hf["d2_dt"].between("2024-09-24", "2024-10-09").to_numpy()
    psz_arr = hf["p_sz"].to_numpy()
    for lvl_name, lm in lvl_masks.items():
        psz_pool_stats[lvl_name] = {
            "psz_le_25": eval_pool_slice(lm & (psz_arr <= 25)),
            "psz_26_to_35": eval_pool_slice(lm & (psz_arr > 25) & (psz_arr <= 35)),
            "psz_le_35_all": eval_pool_slice(lm & (psz_arr <= 35)),
            "psz_gt_35_all": eval_pool_slice(lm & (psz_arr > 35)),
            "psz_gt_35_rescue_0924_1008": eval_pool_slice(lm & (psz_arr > 35) & is_rescue_924),
            "psz_gt_35_rescue_0924_1009": eval_pool_slice(lm & (psz_arr > 35) & is_rescue_924_ext),
            "psz_gt_35_normal_climax": eval_pool_slice(lm & (psz_arr > 35) & (~is_rescue_924_ext)),
            "psz_gt_35_is_21_23": eval_pool_slice(lm & (psz_arr > 35) & (hf["d2_dt"] <= "2023-12-31").to_numpy()),
            "psz_gt_35_oos_24_26_normal": eval_pool_slice(lm & (psz_arr > 35) & (hf["d2_dt"] >= "2024-01-01").to_numpy() & (~is_rescue_924_ext)),
        }

    # tightness 分层对比统计（固定 p_sz <= 35）
    tight_arr = hf["d1_seal_tightness"].to_numpy()
    lm_t = m5y & inv["common_ok"] & inv["open_in_win"] & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & not_bad & (psz_arr <= 35)
    tight_pool_stats = {
        "L2_hard_gates_nd_no_score": {
            "tight_ge_40": eval_pool_slice(lm_t & (tight_arr >= 40.0)),
            "tight_37_to_40": eval_pool_slice(lm_t & (tight_arr >= 37.0) & (tight_arr < 40.0)),
            "tight_ge_37": eval_pool_slice(lm_t & (tight_arr >= 37.0)),
            "tight_30_to_37": eval_pool_slice(lm_t & (tight_arr >= 30.0) & (tight_arr < 37.0)),
            "tight_20_to_30": eval_pool_slice(lm_t & (tight_arr >= 20.0) & (tight_arr < 30.0)),
            "tight_lt_20": eval_pool_slice(lm_t & (tight_arr < 20.0)),
            "tight_lt_37_all": eval_pool_slice(lm_t & (tight_arr < 37.0)),
        },
        "L1_full_v19_added_lt37": summarize_rets([r["net_ret_pct"] / 100.0 for r in added_tight_rows if r["triggered_buy"]]),
        "L1_full_v19_added_lt37_in_final": summarize_rets([r["net_ret_pct"] / 100.0 for r in added_tight_rows if r["triggered_buy"] and r["in_final_v19_mask"]]),
        "L1_full_v19_added_lt37_cons": summarize_rets([r["cons_net_ret_pct"] / 100.0 for r in added_tight_rows if r["triggered_buy"]]),
    }

    # 汇总 JSON
    summary = {
        "study": "一进二 V19 p_sz<=35 & d1_seal_tightness>=37 五年物理清洁消融回测",
        "data_as_of_date": DATA_END_DT,
        "canon_5y_window": f"{CANON_5Y_START} ~ {DATA_END_DT}",
        "fee_rate": FEE_RATE,
        "baseline_parity": {
            "ref_csv": REF_CLEAN_CSV,
            "trades": len(base_1s),
            "max_ret_diff": max_ret_diff,
            "cleanliness": base_clean_check,
        },
        "local_5m_enrichment": added_5m_stats,
        "ablation_variants": variant_results,
        "added_candidates_psz_gt35": added_psz_rows,
        "added_candidates_tight_lt37": added_tight_rows,
        "full_pool_psz_comparison": psz_pool_stats,
        "full_pool_tightness_comparison": tight_pool_stats,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    with open(f"{OUT_DIR}/summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n=== 消融总表 (V19.1 物理清洁口径 · 全五年 / IS / OOS / 近3年 / 2026) ===")
    for vname, _, _, _ in variants:
        vr = variant_results[vname]
        w5 = vr["windows_full_engine"]["5Y"]
        wi = vr["windows_full_engine"]["IS"]
        wo = vr["windows_full_engine"]["OOS"]
        w3 = vr["windows_full_engine"]["3Y"]
        w26 = vr["windows_full_engine"]["2026"]
        c1 = vr["clean_and_5m_1s"]
        print(
            f"  {vname:<18} | pass={vr['passed_signals_5y']:>3} | 5m_1S={c1['trades_5m_full_pct']:>5.1f}%({c1['trades_5m_full_cov']}/{c1['trades_total']}) | "
            f"5Y:{w5['trades']:>2}b WR={w5['win_rate_pct']:>5.2f}% PLR={w5['plr']:>4.2f} 1S={w5['nav_1s']:>6.2f}x EQ={w5['eq_nav']:>5.2f}x MDD={w5['mdd_1s_pct']:>5.2f}% Ex1S={w5['excess_1s_pp']:>+8.1f}pp | "
            f"IS:{wi['nav_1s']:>5.2f}x(EQ={wi['eq_nav']:>4.2f}x) | OOS:{wo['nav_1s']:>5.2f}x(EQ={wo['eq_nav']:>5.2f}x) | "
            f"3Y:{w3['nav_1s']:>5.2f}x | 26:{w26['nav_1s']:>4.2f}x"
        )
    print(f"\n[Done] Outputs written to {OUT_DIR} in {summary['elapsed_sec']}s")


if __name__ == "__main__":
    main()
