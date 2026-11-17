#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
expA2_cross_learn_2to3.py
================================================================================
二进三 V1.0 跨策略双向互学实证引擎（从一进二 V18 & 三进四 V3.4 借入 8 大因子）
严格遵守：
  1. 沙盒隔离：只输出到 factor_mutual_learning_and_ablation_20261117/result_A2_cross_learn_2to3.json
  2. 严禁 import yfinance (D12)；所有 SQLite 使用 file:...?mode=ro 只读连接
  3. 正向 / 反向 / 非线性（两头/中段）全向检验，禁止预设同向有效
  4. 严格 IS (2021-2023) 定方向与分值 -> OOS (2024-2026) 纯盲测，D15 五期净超额 + 100万起1000万封顶/EQ/Trim3/MDD + HLZ t / CSCV PBO
  5. 三行代码校验：单位除数 + 时间锚点 < buy_date 09:25:00 + 极值与基线 assert
================================================================================
"""

import os
import sys
import re
import json
import time
import sqlite3
import datetime
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{PROJECT_ROOT}/sim-portfolio"
BACKTEST_ASTOCK_DIR = f"{SIM_DIR}/backtests_astock"
CLEAN_23_DIR = f"{BACKTEST_ASTOCK_DIR}/clean_2to3_v10_20261117"
SANDBOX_OUT_DIR = f"{BACKTEST_ASTOCK_DIR}/factor_mutual_learning_and_ablation_20261117"
os.makedirs(SANDBOX_OUT_DIR, exist_ok=True)

if CLEAN_23_DIR not in sys.path:
    sys.path.insert(0, CLEAN_23_DIR)
import bt_2to3_v10_clean_master as m23

OUT_JSON = f"{SANDBOX_OUT_DIR}/result_A2_cross_learn_2to3.json"

A_DAILY_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_delisted_daily.parquet"
PARQUET_5M_PATH = f"{SIM_DIR}/data/all_strategies_5m_complete_pit.parquet"
DB_NOTICES_PATH = f"{SIM_DIR}/data/cninfo_notices_5y_pit.db"
PARQUET_TOX_PATH = f"{SIM_DIR}/data/pit_reg_tox_notices_5y_complete.parquet"
KPL_MERGED_PATH = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"
KPL_5Y_PATH = f"{SIM_DIR}/data/kpl_plates_5y_2021_2026_complete.jsonl"
LHB_BUY_PATH = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
LHB_SELL_PATH = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_sell.parquet"
IDX_JSON = f"{BACKTEST_ASTOCK_DIR}/sandbox_lab/index_klines_5y_cache.json"
CSI_CANON_JSON = f"{BACKTEST_ASTOCK_DIR}/clean_rebacktest_20261116/csi300_canonical_20261116.json"

CANON_5Y_START = "2021-11-16"
DATA_END_DT = "2026-11-16"
FEE_RATE = 0.0020

SURF_YZ_3TO4 = re.compile(r"(?:上塘路|财通.*杭州上塘|东方财富.*昌都|佛山|绿景路|苏南|消闲派|国泰君安.*宜昌|开源.*西安西大街)")
SURF_YZ_PURE = re.compile(r"(?:上塘路|财通.*杭州上塘|佛山|绿景路|苏南|消闲派|国泰君安.*宜昌|开源.*西安西大街)")
REG_INC = ["监管工作函", "监管函", "关注函", "重点监控", "停牌核查"]
REG_EXC = ["ST", "回复", "回函", "延期", "核查意见", "复牌", "募集资金", "监事", "独立董事", "保荐"]


def load_daily_and_attach_factors(df, raw_all):
    t0 = time.time()
    print("[1/5] Loading mainboard daily prices (active + delisted) for PIT cross-factors & 5m exit sim...")
    cols = ["date", "ticker", "open", "high", "low", "close", "volume", "amount"]
    d_act = ds.dataset(A_DAILY_PATH, format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2020-12-01"))
    ).to_table().to_pandas()
    parts = [d_act]
    if os.path.exists(A_DELISTED_PATH):
        d_del = ds.dataset(A_DELISTED_PATH, format="parquet").scanner(
            columns=cols, filter=(ds.field("date") >= pd.Timestamp("2020-12-01"))
        ).to_table().to_pandas()
        parts.append(d_del)
    d_all = pd.concat(parts, ignore_index=True)
    d_all["c6"] = d_all["ticker"].astype(str).str[:6]
    d_all = d_all[d_all["c6"].str.startswith(("00", "60")) & (~d_all["ticker"].astype(str).str.endswith(".BJ"))].copy()
    d_all["dt_str"] = d_all["date"].dt.strftime("%Y-%m-%d")
    d_all.sort_values(["c6", "dt_str"], inplace=True)
    d_all.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    d_all.reset_index(drop=True, inplace=True)

    # Unit check on daily volume/amount -> vwap_eod
    chk = d_all[(d_all["dt_str"] >= "2024-01-01") & (d_all["volume"] > 0)].head(100)
    vwap_ratio = (chk["amount"] / chk["volume"] / chk["close"]).median()
    assert 0.90 < vwap_ratio < 1.10, f"amount/volume/close unit mismatch: {vwap_ratio}"

    g = d_all.groupby("c6")
    d_all["pre_c"] = g["close"].shift(1)
    d_all["pct"] = d_all["close"] / d_all["pre_c"] - 1.0
    d_all["o_pct"] = d_all["open"] / d_all["pre_c"] - 1.0
    d_all["zt_px"] = np.floor(d_all["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    d_all["dt_px"] = np.floor(d_all["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    d_all["is_zt"] = (d_all["close"] >= d_all["zt_px"] - 0.01) & (d_all["pct"] >= 0.095) & (d_all["pre_c"] > 0)
    d_all["is_dt"] = (d_all["close"] <= d_all["dt_px"] + 0.01) & (d_all["pct"] <= -0.095) & (d_all["pre_c"] > 0)
    d_all["is_yizi"] = d_all["is_zt"] & (d_all["open"] >= d_all["zt_px"] - 0.01) & (d_all["low"] >= d_all["zt_px"] - 0.01)
    d_all["is_yizi_dt"] = d_all["is_dt"] & (d_all["open"] <= d_all["dt_px"] + 0.01) & (d_all["high"] <= d_all["dt_px"] + 0.01)
    d_all["vwap_eod"] = np.where(d_all["volume"] > 0, d_all["amount"] / d_all["volume"], d_all["close"])

    s_zt = d_all["is_zt"].astype(int)
    s_shift = g["is_zt"].shift(1).fillna(False).astype(bool)
    d_all["streak"] = s_zt.groupby([d_all["c6"], (s_zt != s_shift).cumsum()]).cumsum() * s_zt
    d_all["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)

    all_dts = sorted(d_all["dt_str"].unique())
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (float(r.open), float(r.high), float(r.low), float(r.close), float(r.pre_c) if pd.notna(r.pre_c) else float(r.close),
                           float(r.zt_px) if pd.notna(r.zt_px) else 9999.0, float(r.dt_px) if pd.notna(r.dt_px) else 0.0,
                           bool(r.is_zt), bool(r.is_yizi_dt), float(r.vwap_eod))
        for r in d_all[["c6", "dt_str", "open", "high", "low", "close", "pre_c", "zt_px", "dt_px", "is_zt", "is_yizi_dt", "vwap_eod"]].itertuples(index=False)
    }

    # --- Factor 3a: prev 2b / 3b limit-down stampede on sig_date ---
    prev2b_dt_map = d_all[(d_all["prev_streak"] == 2) & d_all["is_dt"]].groupby("dt_str")["c6"].nunique().to_dict()
    prev3b_dt_map = d_all[(d_all["prev_streak"] == 3) & d_all["is_dt"]].groupby("dt_str")["c6"].nunique().to_dict()
    df["prev_2b_dt_cnt"] = df["sig_date"].map(prev2b_dt_map).fillna(0).astype(int)
    df["prev_3b_dt_cnt"] = df["sig_date"].map(prev3b_dt_map).fillna(0).astype(int)

    # --- Factor 1: LHB on sig_date ---
    lb = pd.read_parquet(LHB_BUY_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL"])
    lb["dt_str"] = lb["TRADE_DATE"].astype(str).str[:10]
    lb["c6"] = lb["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    lb = lb[lb["dt_str"] >= "2021-01-01"].drop_duplicates(subset=["dt_str", "c6", "OPERATEDEPT_NAME"])
    lhb_map = {}
    for (dt, c6), grp in lb.groupby(["dt_str", "c6"], sort=False):
        seats = grp["OPERATEDEPT_NAME"].astype(str).tolist()
        buys = grp["BUY"].fillna(0.0).to_numpy(dtype=float)
        tot_b = float(buys.sum())
        lh_mask = ["拉萨" in s for s in seats]
        lh_cnt = sum(lh_mask)
        lh_buy_sh = float(buys[lh_mask].sum() / tot_b) if tot_b > 0 else 0.0
        surf_34 = any(SURF_YZ_3TO4.search(s) for s in seats)
        surf_pure = any(SURF_YZ_PURE.search(s) for s in seats)
        lhb_map[(dt, c6)] = (1, lh_cnt, lh_buy_sh, int(surf_34), int(surf_pure))

    ls = pd.read_parquet(LHB_SELL_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME"])
    ls["dt_str"] = ls["TRADE_DATE"].astype(str).str[:10]
    ls["c6"] = ls["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    ls = ls[ls["dt_str"] >= "2021-01-01"].drop_duplicates(subset=["dt_str", "c6", "OPERATEDEPT_NAME"])
    lhb_sell_map = {
        (dt, c6): int(any(SURF_YZ_PURE.search(s) for s in grp["OPERATEDEPT_NAME"].astype(str)))
        for (dt, c6), grp in ls.groupby(["dt_str", "c6"], sort=False)
    }

    df["on_lhb_d2"] = [lhb_map.get((sd, c6), (0, 0, 0.0, 0, 0))[0] for sd, c6 in zip(df["sig_date"], df["code"])]
    df["lhb_lh_cnt"] = [lhb_map.get((sd, c6), (0, 0, 0.0, 0, 0))[1] for sd, c6 in zip(df["sig_date"], df["code"])]
    df["lhb_lh_buy_share"] = [lhb_map.get((sd, c6), (0, 0, 0.0, 0, 0))[2] for sd, c6 in zip(df["sig_date"], df["code"])]
    df["surf_yz_buy_34"] = [lhb_map.get((sd, c6), (0, 0, 0.0, 0, 0))[3] for sd, c6 in zip(df["sig_date"], df["code"])]
    df["surf_yz_buy_pure"] = [lhb_map.get((sd, c6), (0, 0, 0.0, 0, 0))[4] for sd, c6 in zip(df["sig_date"], df["code"])]
    df["surf_yz_sell_pure"] = [lhb_sell_map.get((sd, c6), 0) for sd, c6 in zip(df["sig_date"], df["code"])]

    # --- Factor 2: KPL teammates on sig_date & buy_date 09:25 ---
    kpl_stocks_by_dt_plate = defaultdict(list)
    if os.path.exists(KPL_5Y_PATH):
        with open(KPL_5Y_PATH, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                try:
                    obj = json.loads(ln)
                    dt = obj.get("date", "")
                    if dt < "2021-01-01":
                        continue
                    for p in obj.get("plates", []):
                        pn = p.get("plate", "")
                        if not pn or pn in ("其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长", "年报增长", "一季报增长", "中报增长", "次新股"):
                            continue
                        for s in p.get("stocks", []):
                            kpl_stocks_by_dt_plate[(dt, pn)].append(str(s[0]).strip()[:6].zfill(6))
                except Exception:
                    pass

    d_open_info = {
        (r.dt_str, r.c6): (float(r.o_pct), float(r.open) >= float(r.zt_px) - 0.005, int(r.streak))
        for r in d_all[d_all["dt_str"] >= "2021-01-01"][["dt_str", "c6", "o_pct", "open", "zt_px", "streak"]].itertuples(index=False)
        if pd.notna(r.o_pct) and pd.notna(r.zt_px)
    }
    d_streak_sig = {(r.dt_str, r.c6): int(r.streak) for r in d_all[d_all["dt_str"] >= "2021-01-01"][["dt_str", "c6", "streak"]].itertuples(index=False)}

    peers_all_avg = np.zeros(len(df), dtype=float)
    peers_all_cnt = np.zeros(len(df), dtype=int)
    fb_ho_cnt = np.zeros(len(df), dtype=int)
    fb_yz_cnt = np.zeros(len(df), dtype=int)
    for i, (sd, bd, c6, pl) in enumerate(zip(df["sig_date"], df["buy_date"], df["code"], df["plate"])):
        if pl and pl != "其他":
            mates = set(kpl_stocks_by_dt_plate.get((sd, pl), [])) - {c6}
            ops = []
            ho_c = yz_c = 0
            for mc in mates:
                info = d_open_info.get((bd, mc))
                if info is None:
                    continue
                op, is_yz_open, _ = info
                ops.append(op)
                if d_streak_sig.get((sd, mc), 0) == 1:
                    if is_yz_open:
                        yz_c += 1
                    elif op >= 0.020:
                        ho_c += 1
            if ops:
                peers_all_cnt[i] = len(ops)
                peers_all_avg[i] = float(np.mean(ops))
            fb_ho_cnt[i] = ho_c
            fb_yz_cnt[i] = yz_c
    df["plate_zt_peers_cnt"] = peers_all_cnt
    df["plate_zt_peers_open_avg"] = peers_all_avg
    df["plate_fb_ho_cnt"] = fb_ho_cnt
    df["plate_fb_yz_cnt"] = fb_yz_cnt

    # --- Factor 3b: Exchange-level 5-day regulatory monitoring density (strictly <= sig_date) ---
    ex_reg_by_dt = defaultdict(lambda: {"SH": set(), "SZ": set()})
    con_n = sqlite3.connect(f"file:{DB_NOTICES_PATH}?mode=ro", uri=True)
    for sc, pdt, ti in con_n.execute("SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst >= '2020-12-20'"):
        t_str = str(ti or "")
        if any(w in t_str for w in REG_INC) and not any(w in t_str for w in REG_EXC):
            c6 = str(sc)[:6].zfill(6)
            dt_s = str(pdt)[:10]
            if c6.startswith("60"):
                ex_reg_by_dt[dt_s]["SH"].add(c6)
            elif c6.startswith("00"):
                ex_reg_by_dt[dt_s]["SZ"].add(c6)
    con_n.close()
    if os.path.exists(PARQUET_TOX_PATH):
        dft = pd.read_parquet(PARQUET_TOX_PATH)
        for sc, pdt, ti in dft[["sec_code", "pub_datetime_cst", "title"]].itertuples(index=False):
            t_str = str(ti or "")
            if any(w in t_str for w in REG_INC) and not any(w in t_str for w in REG_EXC):
                c6 = str(sc)[:6].zfill(6)
                dt_s = str(pdt)[:10]
                if c6.startswith("60"):
                    ex_reg_by_dt[dt_s]["SH"].add(c6)
                elif c6.startswith("00"):
                    ex_reg_by_dt[dt_s]["SZ"].add(c6)

    ex_reg_5d_cache = {}
    for i, d in enumerate(all_dts):
        if d < "2021-01-01":
            continue
        win_dts = all_dts[max(0, i - 4): i + 1]  # 5 trading days <= sig_date (or calendar 5d: let's check both!)
        sh_u, sz_u = set(), set()
        for wd in win_dts:
            sh_u |= ex_reg_by_dt[wd]["SH"]
            sz_u |= ex_reg_by_dt[wd]["SZ"]
        ex_reg_5d_cache[d] = (len(sh_u), len(sz_u))

    ex_reg_cnt = []
    for sd, c6 in zip(df["sig_date"], df["code"]):
        sh_n, sz_n = ex_reg_5d_cache.get(sd, (0, 0))
        ex_reg_cnt.append(sh_n if c6.startswith("60") else sz_n)
    df["ex_reg_5d_cnt"] = ex_reg_cnt
    df["has_ex_reg"] = df["ex_reg_5d_cnt"] >= 2

    # --- Factor 7: roll20_2to3_seal (strict PIT shift(1)), gap_days, buy_month, CSI300 ---
    # Compute roll20 on raw_all (all 10,848 true 2-boards) and on buyable df
    r_daily = raw_all[raw_all["buyable_open"] & (~raw_all["prev_is_yizi"])].groupby("buy_date", as_index=False).agg(
        n_b=("sealed_3b", "count"), rate_seal=("sealed_3b", "mean")
    ).sort_values("buy_date").reset_index(drop=True)
    r_daily["roll20_2to3_seal"] = r_daily["rate_seal"].shift(1).rolling(20, min_periods=5).mean().fillna(0.25)
    roll20_map = dict(zip(r_daily["buy_date"], r_daily["roll20_2to3_seal"]))
    df["roll20_2to3_seal"] = df["buy_date"].map(roll20_map).fillna(0.25)

    df["gap_days"] = (pd.to_datetime(df["buy_date"]) - pd.to_datetime(df["sig_date"])).dt.days
    df["is_post_holiday_or_mon"] = df["gap_days"] >= 3
    df["buy_month"] = df["buy_date"].str[5:7].astype(int)

    with open(IDX_JSON, encoding="utf-8") as f:
        sh300 = json.load(f)["sh000300"]
    idx_dts = sorted(sh300.keys())
    idx_pos = {d: i for i, d in enumerate(idx_dts)}
    csi_1d_map, csi_5d_map = {}, {}
    for d in idx_dts:
        p = idx_pos[d]
        if p >= 1:
            csi_1d_map[d] = sh300[d] / sh300[idx_dts[p - 1]] - 1.0
        if p >= 5:
            csi_5d_map[d] = sh300[d] / sh300[idx_dts[p - 5]] - 1.0
    df["csi_1d_prev"] = df["sig_date"].map(csi_1d_map).fillna(0.0)
    df["csi_5d_prev"] = df["sig_date"].map(csi_5d_map).fillna(0.0)

    # Assert time anchor on 5m / daily / price checks
    assert (df["sig_date"] < df["buy_date"]).all(), "sig_date must be strictly < buy_date!"
    assert 5.0 < df["prev_close"].median() < 50.0, f"prev_close unit check failed: {df['prev_close'].median()}"
    assert abs(df["ret_opn_cc"].median()) < 0.25, f"ret_opn_cc decimal check failed: {df['ret_opn_cc'].median()}"

    print(f"    Attached cross-strategy factors in {time.time()-t0:.1f}s")
    return df, all_dts, dt_to_idx, price_lookup, sh300


def calc_slice_metrics(sub_raw, sub_slot, csi_pct, rcol="ret_opn_cc"):
    if sub_slot.empty:
        return {
            "raw_n": int(len(sub_raw)), "n": 0, "wr": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "nav_1s": 1.0, "cap10m": 1.0, "eq": 1.0, "trim3": 1.0, "mdd": 0.0,
            "csi_pct": round(csi_pct, 2), "excess_pp": round(-csi_pct, 2),
        }
    rr = sub_slot["net_ret"].to_numpy(dtype=float)
    w, l = rr[rr > 0], rr[rr <= 0]
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else 99.0
    nav = float(np.prod(1.0 + rr))
    trim3 = float(np.prod(1.0 + np.sort(rr)[:-3])) if len(rr) > 3 else 1.0
    ew = float(np.prod(1.0 + sub_raw.groupby("buy_date")[rcol].mean().sort_index().to_numpy())) if len(sub_raw) else 1.0
    pk = cur = 1.0
    mdd = 0.0
    for x in rr:
        cur *= 1.0 + x; pk = max(pk, cur); mdd = max(mdd, (pk - cur) / pk)
    cap = 100.0
    for x in rr:
        cap += min(cap, 1000.0) * float(x)
    return {
        "raw_n": int(len(sub_raw)),
        "n": int(len(rr)),
        "wr": round(float((rr > 0).mean() * 100.0), 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rr.mean() * 100.0), 2),
        "nav_1s": round(nav, 2),
        "cap10m": round(cap / 100.0, 2),
        "eq": round(ew, 2),
        "trim3": round(trim3, 2),
        "mdd": round(mdd * 100.0, 2),
        "csi_pct": round(csi_pct, 2),
        "excess_pp": round((nav - 1.0) * 100.0 - csi_pct, 2),
    }


def eval_2to3_full(gated_all, base_5y_pool, csi, sh300, t_days, day_idx, score_col="score", th=90, extra_gate=None, compute_pbo=False):
    sub_all = gated_all if extra_gate is None else gated_all[extra_gate].copy()
    sub_5y = sub_all[sub_all["buy_date"] >= CANON_5Y_START]

    led_full = m23.sim_single_slot(sub_all[sub_all[score_col] >= th], sc_col=score_col)
    led_5y = m23.sim_single_slot(sub_5y[sub_5y[score_col] >= th], sc_col=score_col)

    win_specs = [
        ("IS_21_23", "2021-01-01", "2023-12-31", -34.16, False),
        ("OOS_24_26", "2024-01-01", DATA_END_DT, csi["近三年(2024-01-01起)"][0], False),
        ("5Y", CANON_5Y_START, DATA_END_DT, csi["全五年(2021-11-16起)"][0], True),
        ("3Y", "2023-11-16", DATA_END_DT, csi["近三年(2023-11-16起)"][0], True),
        ("2026", "2026-01-01", DATA_END_DT, csi["2026全年"][0], True),
        ("2026_07", "2026-07-01", DATA_END_DT, csi["2026年7月以来"][0], True),
        ("2026_10", "2026-10-01", DATA_END_DT, csi["2026年10月以来"][0], True),
    ]
    out = {}
    for wname, sdt, edt, csi_p, use_5y in win_specs:
        sa = sub_all[(sub_all[score_col] >= th) & (sub_all["buy_date"] >= sdt) & (sub_all["buy_date"] <= edt)]
        src_led = led_5y if use_5y else led_full
        ws = src_led[(src_led["buy_date"] >= sdt) & (src_led["buy_date"] <= edt)] if not src_led.empty else pd.DataFrame()
        out[wname] = calc_slice_metrics(sa, ws, csi_p)

    # HLZ t & Monkey & DSR
    if len(led_5y) >= 3:
        hlz = m23.calc_dsr_hlz_monkey_2xfee(led_5y, base_5y_pool, sh300, t_days)
        out["hlz_t_trade"] = hlz["hlz_t_trade_excess"]
        out["hlz_t_daily"] = hlz["hlz_t_daily"]
        out["dsr_M30"] = hlz["dsr_trade_prob"]["M30"]
        out["monkey_p"] = hlz["monkey_5000_p_value"]
    else:
        out["hlz_t_trade"] = 0.0
        out["hlz_t_daily"] = 0.0
        out["dsr_M30"] = 0.0
        out["monkey_p"] = 1.0

    if compute_pbo and len(led_5y) >= 15:
        R_q = np.zeros((len(t_days), 14), dtype=float)
        for r in led_5y.itertuples(index=False):
            i = day_idx.get(r.exit_date)
            if i is not None:
                R_q[i, 0] += r.net_ret
        for v in range(1, 14):
            qv = float(np.quantile(led_5y["score"], 0.05 + (v / 14.0) * 0.40))
            ts = m23.sim_single_slot(sub_5y[sub_5y[score_col] >= qv], sc_col=score_col)
            for r in ts.itertuples(index=False):
                i = day_idx.get(r.exit_date)
                if i is not None:
                    R_q[i, v] += r.net_ret
        lad_ths = [90, 91, 92, 93, 94, 95, 96, 97, 98]
        R_lad = np.zeros((len(t_days), len(lad_ths)), dtype=float)
        for j, t_v in enumerate(lad_ths):
            ts = m23.sim_single_slot(sub_5y[sub_5y[score_col] >= t_v], sc_col=score_col)
            for r in ts.itertuples(index=False):
                i = day_idx.get(r.exit_date)
                if i is not None:
                    R_lad[i, j] += r.net_ret
        out["pbo_q_S8"] = m23.cscv_pbo_eval(R_q, [f"q{i}" for i in range(14)], 8)["pbo_pct"]
        out["pbo_q_S10"] = m23.cscv_pbo_eval(R_q, [f"q{i}" for i in range(14)], 10)["pbo_pct"]
        out["pbo_lad_S8"] = m23.cscv_pbo_eval(R_lad, [f"th{t}" for t in lad_ths], 8)["pbo_pct"]
        out["pbo_lad_S10"] = m23.cscv_pbo_eval(R_lad, [f"th{t}" for t in lad_ths], 10)["pbo_pct"]

    return out


def main():
    t_all = time.time()
    raw_all, df, _ = m23.load_all_clean_data()
    df, all_dts, dt_to_idx, price_lookup, sh300 = load_daily_and_attach_factors(df, raw_all)

    csi = json.load(open(CSI_CANON_JSON, encoding="utf-8"))
    t_days = sorted([d for d in sh300.keys() if CANON_5Y_START <= d <= DATA_END_DT])
    day_idx = {d: i for i, d in enumerate(t_days)}

    gated_all = m23.apply_hard_gates(df)
    gated_all["score"] = m23.score_dataframe(gated_all, base_pts=58)
    base_5y_pool = df[df["buy_date"] >= CANON_5Y_START].copy()

    # Baseline verification assertions
    b_std90 = eval_2to3_full(gated_all, base_5y_pool, csi, sh300, t_days, day_idx, "score", 90, compute_pbo=True)
    b_str96 = eval_2to3_full(gated_all, base_5y_pool, csi, sh300, t_days, day_idx, "score", 96, compute_pbo=False)
    assert b_std90["5Y"]["n"] == 77, f"std90 5Y n mismatch: {b_std90['5Y']['n']}"
    assert b_std90["5Y"]["wr"] == 48.05, f"std90 5Y wr mismatch: {b_std90['5Y']['wr']}"
    assert b_std90["5Y"]["nav_1s"] == 20.32, f"std90 5Y 1S mismatch: {b_std90['5Y']['nav_1s']}"
    assert b_std90["5Y"]["cap10m"] == 19.08, f"std90 5Y Cap10M mismatch: {b_std90['5Y']['cap10m']}"
    assert b_std90["5Y"]["mdd"] == 36.72, f"std90 5Y MDD mismatch: {b_std90['5Y']['mdd']}"
    assert b_str96["5Y"]["n"] == 27 and b_str96["5Y"]["wr"] == 62.96 and b_str96["5Y"]["nav_1s"] == 10.78
    print(f"[PASS BASELINE ASSERT] std90 5Y={b_std90['5Y']} | hlz={b_std90['hlz_t_trade']} pbo_qS10={b_std90['pbo_q_S10']}%")
    print(f"[PASS BASELINE ASSERT] strict96 5Y={b_str96['5Y']}")

    # Helper for bucket IC diagnostics on buyable (6070), gated (3254), and std90 (124)
    def bucket_stats(sub_df, cond_dict):
        out = {}
        is_oos = sub_df["buy_date"] >= "2024-01-01"
        for cname, mask in cond_dict.items():
            s = sub_df[mask]
            s_oos = is_oos[mask]
            res_p = {}
            for p_lbl, pm in [("IS_21_23", ~s_oos), ("OOS_24_26", s_oos), ("ALL_21_26", np.ones(len(s), dtype=bool))]:
                sp = s[pm]
                n = len(sp)
                if n == 0:
                    res_p[p_lbl] = {"n": 0, "wr": 0.0, "mean_pct": 0.0, "seal_rate_pct": 0.0}
                else:
                    r = sp["ret_opn_cc"].to_numpy(dtype=float)
                    res_p[p_lbl] = {
                        "n": int(n),
                        "wr": round(float((r > 0).mean() * 100.0), 2),
                        "mean_pct": round(float(r.mean() * 100.0), 2),
                        "seal_rate_pct": round(float(sp["sealed_3b"].mean() * 100.0), 2),
                    }
            out[cname] = res_p
        return out

    def test_variants(specs, check_strict96=True):
        out = []
        for label, delta_vec, gate_vec in specs:
            g_tmp = gated_all.copy()
            if delta_vec is not None:
                g_tmp["score_mod"] = g_tmp["score"] + delta_vec
            else:
                g_tmp["score_mod"] = g_tmp["score"]
            m90 = eval_2to3_full(g_tmp, base_5y_pool, csi, sh300, t_days, day_idx, "score_mod", 90, extra_gate=gate_vec, compute_pbo=True)
            is_ok = (m90["IS_21_23"]["nav_1s"] >= b_std90["IS_21_23"]["nav_1s"]) and (m90["IS_21_23"]["wr"] >= b_std90["IS_21_23"]["wr"] - 0.5)
            oos_ok = (m90["OOS_24_26"]["nav_1s"] > b_std90["OOS_24_26"]["nav_1s"]) and (m90["OOS_24_26"]["wr"] >= b_std90["OOS_24_26"]["wr"])
            no_hurt_5y = (
                (m90["5Y"]["cap10m"] >= b_std90["5Y"]["cap10m"])
                and (m90["5Y"]["eq"] >= b_std90["5Y"]["eq"])
                and (m90["5Y"]["trim3"] >= b_std90["5Y"]["trim3"])
                and (m90["5Y"]["mdd"] <= b_std90["5Y"]["mdd"] + 0.5)
            )
            item = {
                "variant": label,
                "is_oos_pass_std90": bool(is_ok and oos_ok and no_hurt_5y),
                "std90": m90,
            }
            if check_strict96:
                item["strict96"] = eval_2to3_full(g_tmp, base_5y_pool, csi, sh300, t_days, day_idx, "score_mod", 96, extra_gate=gate_vec, compute_pbo=False)
            out.append(item)
        return out

    print("[2/5] Testing Factors 1-7 bidirectionally on 2to3 V1.0...")
    g = gated_all
    std_sub = g[g["score"] >= 90]
    factors_results = {}

    # 1. LHB Surfing YZ & Lhasa
    surf34 = g["surf_yz_buy_34"].values == 1
    surfp = g["surf_yz_buy_pure"].values == 1
    on_lhb = g["on_lhb_d2"].values == 1
    lh = g["lhb_lh_cnt"].values
    factors_results["F1_LHB_SurfingYZ_and_Lhasa"] = {
        "buckets_df6070": bucket_stats(df, {
            "not_on_lhb": df["on_lhb_d2"] == 0,
            "on_lhb_lh0": (df["on_lhb_d2"] == 1) & (df["lhb_lh_cnt"] == 0),
            "on_lhb_lh1": (df["on_lhb_d2"] == 1) & (df["lhb_lh_cnt"] == 1),
            "on_lhb_lh_ge2": (df["on_lhb_d2"] == 1) & (df["lhb_lh_cnt"] >= 2),
            "on_lhb_lh_ge3": (df["on_lhb_d2"] == 1) & (df["lhb_lh_cnt"] >= 3),
            "surf_yz_buy_pure": df["surf_yz_buy_pure"] == 1,
            "surf_yz_buy_34": df["surf_yz_buy_34"] == 1,
            "surf_yz_sell_pure": df["surf_yz_sell_pure"] == 1,
        }),
        "buckets_gated3254": bucket_stats(g, {
            "not_on_lhb": g["on_lhb_d2"] == 0,
            "on_lhb_lh0": (g["on_lhb_d2"] == 1) & (g["lhb_lh_cnt"] == 0),
            "on_lhb_lh_ge2": (g["on_lhb_d2"] == 1) & (g["lhb_lh_cnt"] >= 2),
            "on_lhb_lh_ge3": (g["on_lhb_d2"] == 1) & (g["lhb_lh_cnt"] >= 3),
            "surf_yz_buy_pure": g["surf_yz_buy_pure"] == 1,
            "surf_yz_buy_34": g["surf_yz_buy_34"] == 1,
        }),
        "v10_variants": test_variants([
            ("3to4_dir_surf34-12_lh0+4_lh>=3-5", np.where(surf34, -12.0, 0.0) + np.where(on_lhb & (lh == 0), 4.0, np.where(lh >= 3, -5.0, 0.0)), None),
            ("3to4_dir_surfpure-12_lh>=2-8", np.where(surfp, -12.0, 0.0) + np.where(lh >= 2, -8.0, 0.0), None),
            ("rev_dir_surfpure+8_lh>=2+6", np.where(surfp, 8.0, 0.0) + np.where(lh >= 2, 6.0, 0.0), None),
            ("filter_drop_surf34", None, ~surf34),
            ("filter_drop_lh>=2", None, ~(lh >= 2)),
        ]),
    }

    # 2. Teammate auction nuke & FB high-open vs FB yizi
    peers_zt = g["plate_zt_peers_open_avg"].values
    peers_zt_c = g["plate_zt_peers_cnt"].values
    peers_2b = g["peers_open_avg_2b"].values
    fb_ho = g["plate_fb_ho_cnt"].values
    fb_yz = g["plate_fb_yz_cnt"].values
    factors_results["F2_Teammates_Nuke_and_FB_Assist_vs_Yizi"] = {
        "buckets_gated3254": bucket_stats(g, {
            "zt_peers_nuke_lt_-1.5%": (g["plate_zt_peers_cnt"] >= 1) & (g["plate_zt_peers_open_avg"] < -0.015),
            "zt_peers_ok_ge_-1.5%": ~((g["plate_zt_peers_cnt"] >= 1) & (g["plate_zt_peers_open_avg"] < -0.015)),
            "peers2b_lt_-1.5%": g["peers_open_avg_2b"] < -0.015,
            "fb_ho>=2_and_fb_yz==0": (g["plate_fb_ho_cnt"] >= 2) & (g["plate_fb_yz_cnt"] == 0),
            "fb_yz>=1": g["plate_fb_yz_cnt"] >= 1,
            "fb_yz==0_fb_ho<2": (g["plate_fb_yz_cnt"] == 0) & (g["plate_fb_ho_cnt"] < 2),
        }),
        "v10_variants": test_variants([
            ("3to4_dir_peers<-1.5%-10_fbho>=2+4_fbyz>=1-7", np.where((peers_zt_c >= 1) & (peers_zt < -0.015), -10.0, 0.0) + np.where((fb_ho >= 2) & (fb_yz == 0), 4.0, 0.0) + np.where(fb_yz >= 1, -7.0, 0.0), None),
            ("only_peers_nuke<-1.5%-10", np.where((peers_zt_c >= 1) & (peers_zt < -0.015), -10.0, 0.0), None),
            ("only_peers_nuke<-1.5%+8(sole_survivor)", np.where((peers_zt_c >= 1) & (peers_zt < -0.015), 8.0, 0.0), None),
            ("only_fbyz>=1-8_vs_fbho>=2+4", np.where(fb_yz >= 1, -8.0, np.where(fb_ho >= 2, 4.0, 0.0)), None),
            ("rev_dir_fbyz>=1+8_fbho>=2-4", np.where(fb_yz >= 1, 8.0, np.where(fb_ho >= 2, -4.0, 0.0)), None),
            ("filter_drop_peers_nuke<-1.5%", None, ~((peers_zt_c >= 1) & (peers_zt < -0.015))),
        ]),
    }

    # 3. Prev 2b/3b DT stampede & Exchange 5-day regulatory monitoring density
    dt2 = g["prev_2b_dt_cnt"].values
    dt3 = g["prev_3b_dt_cnt"].values
    exr = g["has_ex_reg"].values
    factors_results["F3_PrevDT_Stampede_and_ExReg"] = {
        "buckets_gated3254": bucket_stats(g, {
            "prev2b_dt_0": g["prev_2b_dt_cnt"] == 0,
            "prev2b_dt_1": g["prev_2b_dt_cnt"] == 1,
            "prev2b_dt_ge2": g["prev_2b_dt_cnt"] >= 2,
            "prev3b_dt_0": g["prev_3b_dt_cnt"] == 0,
            "prev3b_dt_ge1": g["prev_3b_dt_cnt"] >= 1,
            "prev3b_dt_ge2": g["prev_3b_dt_cnt"] >= 2,
            "ex_reg_true": g["has_ex_reg"] == True,
            "ex_reg_false": g["has_ex_reg"] == False,
        }),
        "v10_variants": test_variants([
            ("3to4_dir_dt3==0+3_dt3>=2-6_exreg-10", np.where(dt3 == 0, 3.0, np.where(dt3 >= 2, -6.0, 0.0)) + np.where(exr, -10.0, 0.0), None),
            ("only_dt2==0+5_dt2>=2-8", np.where(dt2 == 0, 5.0, np.where(dt2 >= 2, -8.0, 0.0)), None),
            ("rev_dir_dt2>=2+8_dt3>=1+6", np.where(dt2 >= 2, 8.0, 0.0) + np.where(dt3 >= 1, 6.0, 0.0), None),
            ("only_exreg-10", np.where(exr, -10.0, 0.0), None),
            ("rev_exreg+8", np.where(exr, 8.0, 0.0), None),
            ("filter_drop_exreg", None, ~exr),
        ]),
    }

    # 4. Absolute stock price elasticity (<=20 vs >32)
    px = g["prev_close"].values
    factors_results["F4_Absolute_Price_Elasticity"] = {
        "buckets_df6070": bucket_stats(df, {
            "px_le_20": df["prev_close"] <= 20.0,
            "px_20_32": df["prev_close"].between(20.0, 32.0, inclusive="right"),
            "px_gt_32": df["prev_close"] > 32.0,
            "px_gt_60": df["prev_close"] > 60.0,
        }),
        "buckets_gated3254": bucket_stats(g, {
            "px_le_20": g["prev_close"] <= 20.0,
            "px_20_32": g["prev_close"].between(20.0, 32.0, inclusive="right"),
            "px_gt_32": g["prev_close"] > 32.0,
            "px_gt_60": g["prev_close"] > 60.0,
        }),
        "v10_variants": test_variants([
            ("3to4_dir_<=20+8_>32-5", np.where(px <= 20.0, 8.0, np.where(px > 32.0, -5.0, 0.0)), None),
            ("rev_dir_>32+8_<=20-6", np.where(px > 32.0, 8.0, np.where(px <= 20.0, -6.0, 0.0)), None),
            ("nonlin_mid20to32+8_ext-5", np.where((px > 20.0) & (px <= 32.0), 8.0, -5.0), None),
            ("filter_drop_px>32", None, px <= 32.0),
            ("filter_only_px<=20", None, px <= 20.0),
        ]),
    }

    # 5. 1to2 3-layer Fake Theme Purifier & Hard-tech Pure Outsider
    evb = g["is_event_basket"].values
    broad_no_sub = (g["is_broad_ind"].values) & (g["d2_sub_cluster_cnt"].fillna(1).values < 2)
    l1_fail = evb | broad_no_sub
    l3_fail = ~g["pass_l3"].values
    d1_dy = g["d1_is_dying_pulse"].values
    out_pure = g["is_pure_outsider"].values
    factors_results["F5_1to2_Purifiers_and_PureOutsider"] = {
        "buckets_df6070": bucket_stats(df, {
            "is_event_basket": df["is_event_basket"] == True,
            "broad_no_sub": (df["is_broad_ind"] == True) & (df["d2_sub_cluster_cnt"] < 2),
            "l3_fail": df["pass_l3"] == False,
            "d1_dying_pulse": df["d1_is_dying_pulse"] == True,
            "is_pure_outsider": df["is_pure_outsider"] == True,
            "clean_pass_all": (~df["is_event_basket"]) & (~((df["is_broad_ind"]) & (df["d2_sub_cluster_cnt"] < 2))) & df["pass_l3"] & (~df["is_pure_outsider"]),
        }),
        "buckets_gated3254": bucket_stats(g, {
            "is_event_basket": g["is_event_basket"] == True,
            "broad_no_sub": (g["is_broad_ind"] == True) & (g["d2_sub_cluster_cnt"] < 2),
            "l3_fail": g["pass_l3"] == False,
            "d1_dying_pulse": g["d1_is_dying_pulse"] == True,
            "is_pure_outsider": g["is_pure_outsider"] == True,
            "clean_pass_all": (~g["is_event_basket"]) & (~((g["is_broad_ind"]) & (g["d2_sub_cluster_cnt"] < 2))) & g["pass_l3"] & (~g["is_pure_outsider"]),
        }),
        "v10_variants": test_variants([
            ("1to2_dir_purify_ev-10_l3-10_out-12", np.where(evb, -10.0, 0.0) + np.where(broad_no_sub, -6.0, 0.0) + np.where(l3_fail, -10.0, 0.0) + np.where(out_pure, -12.0, 0.0), None),
            ("1to2_dir_only_outsider-12", np.where(out_pure, -12.0, 0.0), None),
            ("rev_dir_outsider+10_ev+8(catchup)", np.where(out_pure, 10.0, 0.0) + np.where(evb, 8.0, 0.0), None),
            ("filter_drop_l1_event_basket", None, ~evb),
            ("filter_drop_l3_fail", None, ~l3_fail),
            ("filter_drop_pure_outsider", None, ~out_pure),
            ("only_d1_dying_pulse-8", np.where(d1_dy, -8.0, 0.0), None),
            ("rev_d1_dying_pulse+8", np.where(d1_dy, 8.0, 0.0), None),
        ]),
    }

    # 6. Pioneer words / spark / M&A & hard notices
    has_spark = (g["d2_spark_bonus"].fillna(0).values > 0) | g["d2_is_pioneer_word"].values
    has_new = g["d2_has_new_term"].values | g["d2_own_new_term"].values
    is_kpl_ma = g["d2_is_ma"].values
    has_hard_ntc = g["notice_hard"].values | g["notice_ma"].values
    factors_results["F6_Pioneer_Spark_and_HardCatalyst"] = {
        "buckets_df6070": bucket_stats(df, {
            "d2_spark_or_pioneer": (df["d2_spark_bonus"] > 0) | df["d2_is_pioneer_word"],
            "d2_own_new_term": df["d2_own_new_term"] == True,
            "d2_is_ma_kpl": df["d2_is_ma"] == True,
            "notice_hard_or_ma": df["notice_hard"] | df["notice_ma"],
            "no_catalyst": (~(df["d2_spark_bonus"] > 0)) & (~df["d2_own_new_term"]) & (~df["d2_is_ma"]) & (~df["notice_hard"]),
        }),
        "buckets_gated3254": bucket_stats(g, {
            "d2_spark_or_pioneer": (g["d2_spark_bonus"] > 0) | g["d2_is_pioneer_word"],
            "d2_own_new_term": g["d2_own_new_term"] == True,
            "d2_is_ma_kpl": g["d2_is_ma"] == True,
            "notice_hard_or_ma": g["notice_hard"] | g["notice_ma"],
        }),
        "v10_variants": test_variants([
            ("1to2_dir_spark+6_ownnew+5_ma+6_ntchard+8", np.where(has_spark, 6.0, 0.0) + np.where(g["d2_own_new_term"].values, 5.0, 0.0) + np.where(is_kpl_ma, 6.0, 0.0) + np.where(has_hard_ntc, 8.0, 0.0), None),
            ("rev_dir_sell_news_spark-6_ma-6_ntchard-10", np.where(has_spark, -6.0, 0.0) + np.where(is_kpl_ma, -6.0, 0.0) + np.where(has_hard_ntc, -10.0, 0.0), None),
            ("only_kpl_ma+8", np.where(is_kpl_ma, 8.0, 0.0), None),
            ("only_kpl_ma-8", np.where(is_kpl_ma, -8.0, 0.0), None),
            ("only_own_new+6", np.where(g["d2_own_new_term"].values, 6.0, 0.0), None),
            ("only_own_new-6", np.where(g["d2_own_new_term"].values, -6.0, 0.0), None),
        ]),
    }

    # 7. Sub-factors 7a..7e: clean_brk60, roll20_2to3, gap_days>=3, Jan/May, CSI300 drop
    clean_brk60 = (g["d2_brk_60d"].fillna(False).values == True) & (g["prior_zt_15d"].fillna(0).values == 0) & (g["pre_ret_10d"].fillna(0).values <= 0.18)
    raw_brk60 = g["d2_brk_60d"].fillna(False).values == True
    r20 = g["roll20_2to3_seal"].values
    r20_q30 = float(np.quantile(r20[g["buy_date"] < "2024-01-01"], 0.30))
    r20_q70 = float(np.quantile(r20[g["buy_date"] < "2024-01-01"], 0.70))
    wk = g["is_post_holiday_or_mon"].values
    jm = g["buy_month"].isin([1, 5]).values
    csi_d = (g["csi_1d_prev"].values <= -0.020) | (g["csi_5d_prev"].values <= -0.030)

    factors_results["F7_1to2_and_3to4_Misc_Sensors"] = {
        "roll20_is_q30_q70": [round(r20_q30, 4), round(r20_q70, 4)],
        "buckets_gated3254": bucket_stats(g, {
            "clean_brk60_true": pd.Series(clean_brk60, index=g.index),
            "raw_d2_brk60_true": g["d2_brk_60d"].fillna(False) == True,
            "roll20_low_le_q30": g["roll20_2to3_seal"] <= r20_q30,
            "roll20_mid": g["roll20_2to3_seal"].between(r20_q30, r20_q70, inclusive="neither"),
            "roll20_high_ge_q70": g["roll20_2to3_seal"] >= r20_q70,
            "post_holiday_or_mon": g["is_post_holiday_or_mon"] == True,
            "midweek_tue_fri": g["is_post_holiday_or_mon"] == False,
            "jan_or_may": g["buy_month"].isin([1, 5]),
            "other_months": ~g["buy_month"].isin([1, 5]),
            "csi300_sharp_drop": (g["csi_1d_prev"] <= -0.020) | (g["csi_5d_prev"] <= -0.030),
        }),
        "v10_variants": test_variants([
            ("7a_1to2_dir_clean_brk60+8", np.where(clean_brk60, 8.0, 0.0), None),
            ("7a_rev_dir_clean_brk60-8", np.where(clean_brk60, -8.0, 0.0), None),
            ("7a_raw_d2_brk60+6", np.where(raw_brk60, 6.0, 0.0), None),
            ("7a_raw_d2_brk60-6", np.where(raw_brk60, -6.0, 0.0), None),
            ("7b_contrarian_roll20<=q30+6_>=q70-6", np.where(r20 <= r20_q30, 6.0, np.where(r20 >= r20_q70, -6.0, 0.0)), None),
            ("7b_momentum_roll20>=q70+6_<=q30-6", np.where(r20 >= r20_q70, 6.0, np.where(r20 <= r20_q30, -6.0, 0.0)), None),
            ("7c_1to2_3to4_dir_mon_holiday+5", np.where(wk, 5.0, 0.0), None),
            ("7c_rev_dir_mon_holiday-5", np.where(wk, -5.0, 0.0), None),
            ("7d_3to4_dir_jan_may-6", np.where(jm, -6.0, 0.0), None),
            ("7d_rev_dir_jan_may+6", np.where(jm, 6.0, 0.0), None),
            ("7e_3to4_dir_csi_drop-8", np.where(csi_d, -8.0, 0.0), None),
            ("7e_rev_dir_csi_drop+8", np.where(csi_d, 8.0, 0.0), None),
        ]),
    }

    # ==========================================================================
    # Factor 8: Buy/Sell Point Intersection on 2to3
    # ==========================================================================
    print("[3/5] Loading 5m bars for Factor 8 (Exit intersection: D3 unsealed VWAP & D4+ pm1345 vs vwap1030)...")
    df_5m = pd.read_parquet(PARQUET_5M_PATH)
    df_5m["c6"] = df_5m["c6"].astype(str).str.zfill(6)
    df_5m["hhmm_int"] = df_5m["hhmm_int"].astype(int)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_map = {
        (c6, dt): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False)
    }

    # Precompute D3 intraday & daily features for every row in gated_all
    d3_flags = []
    for r in g.itertuples(index=False):
        c6, bd = r.code, r.buy_date
        b3 = price_lookup.get((c6, bd))
        arr3 = bars_5m_map.get((c6, bd))
        if b3:
            o3, h3, l3, c3, pc3, zt3, dt3, izt3, iyzdt3, vw3 = b3
            c3_lt_vwap = c3 < vw3
            c3_lt_o3 = c3 < o3
        else:
            c3_lt_vwap = c3_lt_o3 = False
        b1030_lt_vw = b1430_lt_vw = None
        if arr3 is not None and len(arr3) >= 12:
            cv = ca = 0.0
            for row5 in arr3:
                cv += row5[5]; ca += row5[6]
                vw = ca / cv if cv > 0 else row5[4]
                if int(row5[0]) == 1030:
                    b1030_lt_vw = (row5[4] < vw)
                if int(row5[0]) == 1430:
                    b1430_lt_vw = (row5[4] < vw)
        d3_flags.append({
            "c3_lt_vwap": c3_lt_vwap,
            "c3_lt_o3": c3_lt_o3,
            "has_d3_5m": arr3 is not None,
            "d3_1030_lt_vw": b1030_lt_vw,
            "d3_1430_lt_vw": b1430_lt_vw,
        })
    df_d3f = pd.DataFrame(d3_flags)

    # Simulate exact exit path from buy_date forward for any (unsealed_mode, sealed_mode)
    def sim_custom_exit(r, unsealed_mode="clean_exit", sealed_mode="pm1345_imm"):
        c6, bd = r.code, r.buy_date
        pos = dt_to_idx.get(bd, -1)
        if pos < 0 or pos >= len(all_dts) - 1:
            return r.ret_opn_cc, r.exit_dt_cc, r.exit_hh_cc
        b3 = price_lookup.get((c6, bd))
        if not b3:
            return r.ret_opn_cc, r.exit_dt_cc, r.exit_hh_cc
        o3, h3, l3, c3, pc3, zt3, dt3, izt3, iyzdt3, vw3 = b3
        buy_px = round(float(r.prev_close) * (1.0 + float(r.open_pct)), 2)

        def run_zt_hold(sp_idx):
            k = sp_idx + 1
            used_imm = False
            n = len(all_dts)
            while k < n and (k - pos <= 15):
                dk = all_dts[k]
                bk = price_lookup.get((c6, dk))
                if not bk:
                    k += 1; continue
                ok, hk, lk, ck, pck, ztk, dtk, iztk, iyzk, _ = bk
                if iyzk:
                    k += 1; continue
                # If previous day was yizi_dt, open sell
                if k > sp_idx + 1:
                    prev_bk = price_lookup.get((c6, all_dts[k - 1]))
                    if prev_bk and prev_bk[8]:
                        return (ok / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 925

                arr = bars_5m_map.get((c6, dk))
                if sealed_mode.startswith("pm1345"):
                    if arr is not None and len(arr) > 0:
                        pk = ok
                        for row5 in arr:
                            hh, bo, bh, bl, bc = int(row5[0]), row5[1], row5[2], row5[3], row5[4]
                            if bh <= dtk + 0.005:
                                continue
                            if hh >= 1345 and pk >= pck * 1.085 and bl <= pck * 1.050 and bc < ztk - 0.01:
                                px = min(bo, pck * 1.050)
                                return (px / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, hh
                            if bh > pk:
                                pk = bh
                elif sealed_mode.startswith("vwap1030"):
                    if arr is not None and len(arr) >= 12:
                        idx_1030 = -1
                        cv = ca = 0.0
                        for bi in range(len(arr)):
                            cv += arr[bi, 5]; ca += arr[bi, 6]
                            if int(arr[bi, 0]) == 1030:
                                idx_1030 = bi; break
                        if idx_1030 >= 0:
                            bc_1030 = arr[idx_1030, 4]
                            vw_1030 = ca / cv if cv > 0 else bc_1030
                            if bc_1030 >= ztk - 0.01:
                                for bi in range(idx_1030 + 1, len(arr) - 1):
                                    if arr[bi, 0] >= 1430 and arr[bi, 4] < ztk - 0.01:
                                        px = float(arr[bi + 1, 1])
                                        return (px / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, int(arr[bi + 1, 0])
                            elif bc_1030 < vw_1030:
                                px = float(arr[idx_1030 + 1, 1]) if idx_1030 + 1 < len(arr) else float(bc_1030)
                                ehh = int(arr[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr) else 1030
                                if px > dtk + 0.005:
                                    return (px / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, ehh

                if iztk:
                    k += 1; continue
                use_imm = ("_imm" in sealed_mode)
                if use_imm and (not used_imm) and (ck > ok) and (ck >= pck):
                    used_imm = True; k += 1; continue
                return (ck / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 1500
            return r.ret_opn_cc, r.exit_dt_cc, r.exit_hh_cc

        if r.sealed_3b:
            if sealed_mode == "baseline_cc":
                return r.ret_opn_cc, r.exit_dt_cc, r.exit_hh_cc
            return run_zt_hold(pos)

        # Unsealed 3-board branch
        if unsealed_mode == "clean_exit":
            return r.ret_opn_cc, r.exit_dt_cc, r.exit_hh_cc

        k = pos + 1
        while k < len(all_dts):
            bk = price_lookup.get((c6, all_dts[k]))
            if bk and not bk[8]:
                break
            k += 1
        if k >= len(all_dts):
            return r.ret_opn_cc, r.exit_dt_cc, r.exit_hh_cc
        dk = all_dts[k]
        ok, hk, lk, ck, pck, ztk, dtk, iztk, iyzk, _ = price_lookup[(c6, dk)]
        if k > pos + 1:
            return (ok / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 925

        if unsealed_mode == "always_d4_open":
            return (ok / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 925
        elif unsealed_mode == "always_d4_close":
            if iztk:
                return run_zt_hold(k)
            return (ck / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 1500
        elif unsealed_mode == "d3_c_lt_vwap_cut0925":
            if (c3 < vw3) or (ok < c3 * 1.005):
                return (ok / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 925
            if iztk:
                return run_zt_hold(k)
            return (ck / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 1500
        elif unsealed_mode == "d3_c_lt_o3_cut0925":
            if (c3 < o3) or (ok < c3 * 1.005):
                return (ok / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 925
            if iztk:
                return run_zt_hold(k)
            return (ck / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 1500
        elif unsealed_mode == "d3_blown_zt_cut0925":
            if bool(r.touch_3b) or (ok < c3 * 1.005):
                return (ok / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 925
            if iztk:
                return run_zt_hold(k)
            return (ck / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 1500
        elif unsealed_mode == "d4_vwap1030_when_hold":
            if ok < c3 * 1.005:
                return (ok / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 925
            arr = bars_5m_map.get((c6, dk))
            if arr is not None and len(arr) >= 12:
                idx_1030 = -1; cv = ca = 0.0
                for bi in range(len(arr)):
                    cv += arr[bi, 5]; ca += arr[bi, 6]
                    if int(arr[bi, 0]) == 1030:
                        idx_1030 = bi; break
                if idx_1030 >= 0:
                    bc1030 = arr[idx_1030, 4]; vw1030 = ca / cv if cv > 0 else bc1030
                    if bc1030 < ztk - 0.01 and bc1030 < vw1030:
                        px = float(arr[idx_1030 + 1, 1]) if idx_1030 + 1 < len(arr) else float(bc1030)
                        ehh = int(arr[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr) else 1030
                        if px > dtk + 0.005:
                            return (px / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, ehh
            if iztk:
                return run_zt_hold(k)
            return (ck / buy_px) * (1.0 - FEE_RATE) - 1.0, dk, 1500
        return r.ret_opn_cc, r.exit_dt_cc, r.exit_hh_cc

    exit_modes_out = []
    for lbl, um, sm in [
        ("Baseline_CleanExit(3to4_pm1345+imm)", "clean_exit", "baseline_cc"),
        ("Verify_ReSim_pm1345+imm", "clean_exit", "pm1345_imm"),
        ("Sealed3b_1to2_vwap1030+1430rush+imm", "clean_exit", "vwap1030_imm"),
        ("Sealed3b_1to2_vwap1030+1430rush_no_imm", "clean_exit", "vwap1030_noimm"),
        ("Sealed3b_Pure_EOD_break+imm", "clean_exit", "eod_imm"),
        ("Sealed3b_Pure_EOD_break_no_imm", "clean_exit", "eod_noimm"),
        ("Unsealed3b_D3_c<vwap_cut0925", "d3_c_lt_vwap_cut0925", "pm1345_imm"),
        ("Unsealed3b_D3_c<o3_cut0925", "d3_c_lt_o3_cut0925", "pm1345_imm"),
        ("Unsealed3b_D3_blown3b_cut0925", "d3_blown_zt_cut0925", "pm1345_imm"),
        ("Unsealed3b_Always_D4_0925_cut", "always_d4_open", "pm1345_imm"),
        ("Unsealed3b_Always_D4_1500_hold", "always_d4_close", "pm1345_imm"),
        ("Unsealed3b_D4_1030_vwap_when_hold", "d4_vwap1030_when_hold", "pm1345_imm"),
    ]:
        g_ex = g.copy()
        res_tuples = [sim_custom_exit(r, um, sm) for r in g_ex.itertuples(index=False)]
        g_ex["ret_opn_cc"] = [t[0] for t in res_tuples]
        g_ex["exit_dt_cc"] = [t[1] for t in res_tuples]
        g_ex["exit_hh_cc"] = [t[2] for t in res_tuples]
        m90 = eval_2to3_full(g_ex, base_5y_pool, csi, sh300, t_days, day_idx, "score", 90, compute_pbo=True)
        m96 = eval_2to3_full(g_ex, base_5y_pool, csi, sh300, t_days, day_idx, "score", 96, compute_pbo=False)
        exit_modes_out.append({"mode": lbl, "std90": m90, "strict96": m96})

    # D3 5m coverage & subset diagnostic for ~sealed_3b
    g_unseal = g[~g["sealed_3b"]].copy().reset_index(drop=True)
    df_d3f_u = df_d3f[~g["sealed_3b"].values].reset_index(drop=True)
    d3_unsealed_diag = {
        "total_gated_unsealed_n": int(len(g_unseal)),
        "d3_5m_covered_n": int(df_d3f_u["has_d3_5m"].sum()),
        "d3_5m_coverage_pct": round(float(df_d3f_u["has_d3_5m"].mean() * 100.0), 2),
        "d3_daily_c3_lt_vwap": bucket_stats(g_unseal, {
            "c3_lt_vwap": df_d3f_u["c3_lt_vwap"],
            "c3_ge_vwap": ~df_d3f_u["c3_lt_vwap"],
            "c3_lt_o3": df_d3f_u["c3_lt_o3"],
            "c3_ge_o3": ~df_d3f_u["c3_lt_o3"],
        }),
    }
    if df_d3f_u["has_d3_5m"].sum() > 0:
        sub5 = g_unseal[df_d3f_u["has_d3_5m"].values].copy().reset_index(drop=True)
        f5 = df_d3f_u[df_d3f_u["has_d3_5m"].values].reset_index(drop=True)
        d3_unsealed_diag["d3_5m_subset_1030_1430"] = {
            "n_1030_lt_vw": int((f5["d3_1030_lt_vw"] == True).sum()),
            "mean_ret_1030_lt_vw": round(float(sub5[f5["d3_1030_lt_vw"] == True]["ret_opn_cc"].mean() * 100.0), 2) if (f5["d3_1030_lt_vw"] == True).sum() else 0.0,
            "n_1030_ge_vw": int((f5["d3_1030_lt_vw"] == False).sum()),
            "mean_ret_1030_ge_vw": round(float(sub5[f5["d3_1030_lt_vw"] == False]["ret_opn_cc"].mean() * 100.0), 2) if (f5["d3_1030_lt_vw"] == False).sum() else 0.0,
            "n_1430_lt_vw": int((f5["d3_1430_lt_vw"] == True).sum()),
            "mean_ret_1430_lt_vw": round(float(sub5[f5["d3_1430_lt_vw"] == True]["ret_opn_cc"].mean() * 100.0), 2) if (f5["d3_1430_lt_vw"] == True).sum() else 0.0,
        }

    out_payload = {
        "meta": {
            "experiment": "ExpA2_CrossLearn_2to3_V10",
            "generated_at": datetime.datetime.now().isoformat(),
            "is_window": "2021-01-04 ~ 2023-12-31",
            "oos_window": "2024-01-01 ~ 2026-11-16",
            "canon_5y_window": f"{CANON_5Y_START} ~ {DATA_END_DT}",
        },
        "baseline_v10": {"std90": b_std90, "strict96": b_str96},
        "factors_1_to_7": factors_results,
        "factor_8_exit_intersection": {
            "exit_modes": exit_modes_out,
            "d3_unsealed_diag": d3_unsealed_diag,
        },
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, ensure_ascii=False, indent=2)
    print(f"Saved {OUT_JSON} in {time.time()-t_all:.1f}s")
    for fk, fv in factors_results.items():
        passes = [v["variant"] for v in fv["v10_variants"] if v["is_oos_pass_std90"]]
        print(f"  {fk}: dual_pass_std90={passes}")


if __name__ == "__main__":
    main()
