#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step1_build_cache_and_verify.py
复现 V4.0 baseline (95笔/1799.99x & 31笔/16.72x) 逐笔 0.0 误差，
并抽取相关标的的全量微观卖出仿真数据包缓存到 s1_3to4_exit/cache_3to4_exit.pkl。
"""

import os
import sys
import json
import time
import pickle
import sqlite3
from collections import defaultdict

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 VIOLATION"

UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_opt_20261118/s1_3to4_exit"
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, UPG_DIR)
import upgrade_3to4_pit as u34


def verify_baseline(res_full: dict) -> dict:
    with open(u34.CSI_CANON_JSON, "r", encoding="utf-8") as f:
        csi_canon = json.load(f)

    raw_std, slot_std = u34.extract_raw_and_slot(res_full, res_full["sc_v40"], 90.0, "p_1030")
    raw_str, slot_str = u34.extract_raw_and_slot(res_full, res_full["sc_v40"], 102.0, "p_1030")

    ref_std = pd.read_csv(f"{UPG_DIR}/ledger_upg_3to4_std.csv", dtype={"code": str})
    ref_str = pd.read_csv(f"{UPG_DIR}/ledger_upg_3to4_strict.csv", dtype={"code": str})
    ref_std["code"] = ref_std["code"].str.zfill(6)
    ref_str["code"] = ref_str["code"].str.zfill(6)

    for lbl, cur, ref in [("std90", slot_std, ref_std), ("strict102", slot_str, ref_str)]:
        assert len(cur) == len(ref), f"{lbl} len mismatch: {len(cur)} vs {len(ref)}"
        cur_r = cur.reset_index(drop=True)
        assert (cur_r["code"] == ref["code"]).all(), f"{lbl} code mismatch"
        assert (cur_r["buy_date"] == ref["buy_date"]).all(), f"{lbl} buy_date mismatch"
        assert (cur_r["buy_hhmm"] == ref["buy_hhmm"]).all(), f"{lbl} buy_hhmm mismatch"
        assert (cur_r["exit_date"] == ref["exit_date"]).all(), f"{lbl} exit_date mismatch"
        assert (cur_r["exit_hhmm"] == ref["exit_hhmm"]).all(), f"{lbl} exit_hhmm mismatch"
        diff_ret = np.max(np.abs(cur_r["net_ret"].round(6) - ref["net_ret"]))
        diff_bpx = np.max(np.abs(cur_r["buy_price"] - ref["buy_price"]))
        diff_epx = np.max(np.abs(cur_r["exit_price"] - ref["exit_price"]))
        assert diff_ret == 0.0 and diff_bpx == 0.0 and diff_epx == 0.0, (
            f"{lbl} numeric mismatch: ret={diff_ret}, bpx={diff_bpx}, epx={diff_epx}"
        )

    m_std = u34._calc_metrics_window(
        raw_std, slot_std, res_full["csi_map"], res_full["all_csi_dts"],
        "2021-11-15", "2026-11-16", csi_canon["全五年(2021-11-16起)"][0]
    )
    m_str = u34._calc_metrics_window(
        raw_str, slot_str, res_full["csi_map"], res_full["all_csi_dts"],
        "2021-11-15", "2026-11-16", csi_canon["全五年(2021-11-16起)"][0]
    )
    print(f"[BASELINE VERIFIED 0.0 DIFF] std90: N={m_std['single_n']}, WR={m_std['win_rate_pct']}%, PLR={m_std['plr']}, 1S={m_std['single_slot_nav']}x, EQ={m_std['daily_equal_weight_nav']}x, MDD={m_std['max_drawdown_pct']}%")
    print(f"[BASELINE VERIFIED 0.0 DIFF] strict102: N={m_str['single_n']}, WR={m_str['win_rate_pct']}%, PLR={m_str['plr']}, 1S={m_str['single_slot_nav']}x, EQ={m_str['daily_equal_weight_nav']}x, MDD={m_str['max_drawdown_pct']}%")
    return {"std90": m_std, "strict102": m_str}


def build_extended_cache(res_full: dict, max_date: str = "2026-11-16") -> dict:
    t0 = time.time()
    cand_df = res_full["cand_df"].copy()
    skel = res_full["skel"]
    sc_v40 = res_full["sc_v40"]
    sc_v34 = res_full["sc_v34"]

    # 所有骨架池标的（含所有可能进入>=80..102的标的，以防后续做邻域与LOFO检查）
    target_codes = set(cand_df.loc[res_full["raw_core"], "code"].unique()) | set(cand_df["code"].unique())

    # 1. 加载扩展日线字段 (含 turn, amount, volume, is_dt 等) 严格 <= max_date
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn"]
    dt_cap = pd.Timestamp(max_date)
    d1 = ds.dataset(u34.A_DAILY_PQ, format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2021-01-01")) & (ds.field("date") <= dt_cap)
    ).to_table().to_pandas()
    d2 = ds.dataset(u34.A_DELIST_PQ, format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2021-01-01")) & (ds.field("date") <= dt_cap)
    ).to_table().to_pandas()
    df = pd.concat([d1, d2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].astype(str).str.endswith((".SH", ".SZ")) & df["c6"].isin(target_codes)].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    g = df.groupby("c6")
    df["adjf"] = np.where(df["close"] > 0, df["adj_close"] / df["close"], 1.0)
    df["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["to"] = df["turn"] * u34.UNIT_PCT_DIV
    df["zt_price"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["dt_price"] = np.floor(df["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_price"] - 0.011) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
    df["is_dt"] = (df["close"] <= df["dt_price"] + 0.011) & (df["pct"] <= -0.095) & (df["pre_c"] > 0)
    df["is_dt_exact"] = (df["close"] <= df["dt_price"] + 0.005) & (df["pre_c"] > 0)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_price"] - 0.011) & (df["low"] >= df["zt_price"] - 0.011)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_price"] + 0.011) & (df["high"] <= df["dt_price"] + 0.011)

    # 只保留 >= 2021-08-01 的日线数组供 30 日双异动回溯及卖出循环
    sub = df[df["dt_str"] >= "2021-08-01"].copy()
    code_bars_ext = {}
    for c6, gc in sub.groupby("c6", sort=False):
        code_bars_ext[c6] = {
            "dts": gc["dt_str"].values,
            "date_to_pos": {d: i for i, d in enumerate(gc["dt_str"].values)},
            "open": gc["open"].values.astype(float),
            "high": gc["high"].values.astype(float),
            "low": gc["low"].values.astype(float),
            "close": gc["close"].values.astype(float),
            "adjf": gc["adjf"].values.astype(float),
            "pre_c": gc["pre_c"].values.astype(float),
            "zt_px": gc["zt_price"].values.astype(float),
            "dt_px": gc["dt_price"].values.astype(float),
            "to": gc["to"].values.astype(float),
            "amount": gc["amount"].values.astype(float),
            "volume": gc["volume"].values.astype(float),
            "is_zt": gc["is_zt"].values.astype(bool),
            "is_dt": gc["is_dt"].values.astype(bool),
            "is_dt_exact": gc["is_dt_exact"].values.astype(bool),
            "is_yizi": gc["is_yizi"].values.astype(bool),
            "is_yizi_dt": gc["is_yizi_dt"].values.astype(bool),
        }

    # 2. 指数全量字典 (<= max_date)
    with open(u34.IDX_JSON, "r", encoding="utf-8") as f:
        idx_raw = json.load(f)
    sh_map = {k: float(v) for k, v in idx_raw["sh000002"].items() if k <= max_date}
    sz_map = {k: float(v) for k, v in idx_raw["sz399107"].items() if k <= max_date}
    csi_map = {k: float(v) for k, v in idx_raw["sh000300"].items() if k <= max_date}
    all_csi_dts = sorted(csi_map.keys())

    # 3. 5m K 线（仅 target_codes, <= max_date）
    df_5m_a = ds.dataset(u34.BARS_ALL_5M, format="parquet").scanner(
        columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
        filter=(ds.field("date") <= max_date),
    ).to_table().to_pandas()
    df_5m_b = ds.dataset(u34.BARS_34_5M, format="parquet").scanner(
        columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
        filter=(ds.field("date") <= max_date),
    ).to_table().to_pandas()
    df_5m = pd.concat([df_5m_a, df_5m_b], ignore_index=True)
    df_5m = df_5m[df_5m["c6"].isin(target_codes)].copy()
    df_5m.drop_duplicates(["c6", "date", "hhmm_int"], keep="first", inplace=True)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_map = {
        (c6, d): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        for (c6, d), grp in df_5m.groupby(["c6", "date"], sort=False)
    }

    # 4. 雪球时间数组（严格 mode=ro & <= max_date 23:59:59），用于任意持仓日盘前暗牌检验
    xq_seen = defaultdict(set)
    xq_posts = defaultdict(list)
    con_xq = sqlite3.connect(f"file:{u34.DB_XQ_GB}?mode=ro", uri=True)
    for sym, pid, cts in con_xq.execute(
        "SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE created_time_str >= '2021-10-01' AND created_time_str <= ?",
        (f"{max_date} 23:59:59",),
    ):
        c6 = str(sym)[:6].zfill(6)
        if c6 in target_codes and cts:
            pid_c = str(pid).replace("xq_", "")
            if pid_c not in xq_seen[c6]:
                xq_seen[c6].add(pid_c)
                xq_posts[c6].append(str(cts))
    con_xq.close()
    con_cm = sqlite3.connect(f"file:{u34.DB_COMM}?mode=ro", uri=True)
    for sym, pid, cts in con_cm.execute(
        "SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND pub_datetime_cst >= '2021-10-01' AND pub_datetime_cst <= ?",
        (f"{max_date} 23:59:59",),
    ):
        c6 = str(sym)[:6].zfill(6)
        if c6 in target_codes and cts:
            pid_c = str(pid).replace("xq_", "")
            if pid_c not in xq_seen[c6]:
                xq_seen[c6].add(pid_c)
                xq_posts[c6].append(str(cts))
    con_cm.close()
    xq_arr_map = {c6: np.sort(np.array(v, dtype=str)) for c6, v in xq_posts.items()}

    # 5. 对每一行 cand_df，提取买点信息（固定买点 1030 及原始 p_1030）
    buy_entries = []
    for i, r in enumerate(cand_df.itertuples(index=False)):
        c6 = str(r.code)
        bd = str(r.buy_date)
        cb = code_bars_ext.get(c6)
        pos = cb["date_to_pos"].get(bd, -1) if cb else -1
        bpx, bhh = None, None
        if bool(r.is_10cm_non_st) and bool(r.buyable_open) and cb is not None and 0 <= pos < len(cb["dts"]) - 1:
            bpx, bhh = u34._sim_buy_5m(c6, bd, cb, pos, bars_5m_map, 1030)
        # 核对与原 res_full["p_1030"][i] 买价/买点时间完全一致
        orig = res_full["p_1030"][i]
        if orig is not None:
            assert bpx is not None and round(bpx, 2) == orig["buy_price"] and bhh == orig["buy_hhmm"], (
                f"Buy mismatch at {bd} {c6}: {bpx}/{bhh} vs {orig['buy_price']}/{orig['buy_hhmm']}"
            )
        else:
            assert bpx is None, f"Buy mismatch at {bd} {c6}: got {bpx} vs None"

        buy_entries.append({
            "idx": i,
            "code": c6,
            "name": str(r.name),
            "sig_date": str(r.sig_date),
            "buy_date": bd,
            "d1_date": str(cb["dts"][max(0, pos - 3)]) if (cb and pos >= 3) else str(r.sig_date),
            "pos": pos,
            "buy_px": bpx,
            "buy_hhmm": bhh,
            "skel": bool(skel[i]),
            "sc_v40": float(sc_v40[i]),
            "sc_v34": float(sc_v34[i]),
            "priority_score": float(sc_v40[i]) * 10.0 + float(r.prio_3to4) * 0.1,
            "open_pct": float(r.open_pct),
            "pos20_d0": float(r.pos20_d0),
            "xq_cnt_2d": int(r.xq_cnt_2d),
            "has_5m_buy": bool(r.has_5m_buy),
            "has_5m_exit": bool(r.has_5m_exit),
            "orig_p1030": orig,
        })

    cache = {
        "max_date": max_date,
        "cand_df": cand_df,
        "skel": skel,
        "raw_core": res_full["raw_core"],
        "comp_v40": res_full["comp_v40"],
        "sc_v40": sc_v40,
        "sc_v34": sc_v34,
        "buy_entries": buy_entries,
        "code_bars_ext": code_bars_ext,
        "bars_5m_map": bars_5m_map,
        "sh_map": sh_map,
        "sz_map": sz_map,
        "csi_map": csi_map,
        "all_csi_dts": all_csi_dts,
        "xq_arr_map": xq_arr_map,
    }
    out_pkl = f"{OUT_DIR}/cache_3to4_exit.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[CACHE SAVED] {out_pkl} ({os.path.getsize(out_pkl)/1024/1024:.2f} MB) in {time.time()-t0:.1f}s")
    return cache


if __name__ == "__main__":
    res_full = u34.run_causal_pipeline("2026-11-16", verbose=True)
    verify_baseline(res_full)
    build_extended_cache(res_full, "2026-11-16")
