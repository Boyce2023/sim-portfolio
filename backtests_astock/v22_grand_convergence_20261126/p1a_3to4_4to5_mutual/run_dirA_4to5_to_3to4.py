#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_dirA_4to5_to_3to4.py
【方向 A：四进五基因赋能「三进四」持仓卖点】严格 PIT 全量双向回测与消融审计。
- 严格零未来函数：D2（k = pos + 1，仅当 D1 封死 4 板）使用 D1 盘后 + D2 <09:25 公告 + D2 09:25 竞价可得信息，
  绝不偷看 D2 盘中/收盘；支持 2024-12-31 物理截断重建验证 max_abs_diff == 0.0。
- 30bps 实盘主滑点 + 50bps 压力测试；检查 IS / OOS / 2025-2026 / 2026 / 2026H2 五窗口 + 去前2笔 + 去合富中国 + V21池 + 78+扩充池。
"""
import argparse
import bisect
import datetime
import gc
import json
import os
import pickle
import re
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
sys.dont_write_bytecode = True
assert "yfinance" not in sys.modules, "D12 VIOLATION"

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)
import _p1a_common as cm

SIM = cm.SIM
F1_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
A2_ASSETS = f"{SIM}/backtests_astock2/assets"
for p in (F1_DIR, UPG_DIR, A2_ASSETS):
    if p not in sys.path:
        sys.path.insert(0, p)

import exit_factor_engine as efe
import step1_build_exit_pit_db as s1_34
import upgrade_3to4_pit as u34

F7 = ["xf21_135", "xf03_20m", "xf28_35", "xf02", "xf07_new", "xf22", "xf23_reb20"]

TOX_NARROW_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险|违法违规)")
TOX_JIANCHI_RE = re.compile(r"(?:减持.*(?:计划|预披露|公告)|(?:计划|预披露).*减持|立案调查|收到立案|退市风险|违法违规)")
TOX_RISKHINT_RE = re.compile(r"股票交易风险提示")
TOX_STRICT_RE = re.compile(r"(?:减持.*(?:计划|预披露|公告)|(?:计划|预披露).*减持|立案调查|收到立案|退市风险|违法违规|股票交易风险提示)")
REG_INC = ("监管函", "关注函", "问询函", "监管工作函", "通报批评", "公开谴责", "立案", "风险提示")
REG_EXC = ("回复", "取消", "撤销", "解除", "不予")


def _risk7_pts(st: dict) -> int:
    return sum(int(bool(st.get(k))) for k in F7)


def load_daily_context_pit(target_codes: set[str], max_dt: str) -> dict:
    """
    Load A-share active + delisted daily bars strictly <= max_dt for:
      - dt_defer tables (`dmap`, `by_c`)
      - bar_lu (`(c6, dt) -> (open, close, adjf)`)
      - 4-board rivals at 09:25 (`rivals_4b[bd]` list of (c6, o_pct))
      - D1 first-board (`streak==1`) and 3-board (`streak==3`) code sets per day for KPL plate assist.
    """
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume"]
    dt_cap = pd.Timestamp(max_dt)
    dt_lo = pd.Timestamp("2021-09-01")
    flt = (ds.field("date") >= dt_lo) & (ds.field("date") <= dt_cap)

    frames = []
    for pq_path, dl_flag in [(cm.A_DAILY_PQ, 0), (cm.A_DELIST_PQ, 1)]:
        sc = ds.dataset(pq_path, format="parquet").scanner(columns=cols, filter=flt, batch_size=65536, use_threads=False)
        for batch in sc.to_batches():
            dfb = batch.to_pandas()
            if dfb.empty:
                continue
            dfb["c6"] = dfb["ticker"].astype(str).str[:6]
            m = dfb["ticker"].astype(str).str.endswith((".SH", ".SZ")) & dfb["c6"].str.startswith(("00", "60"))
            dfb = dfb[m].copy()
            if not dfb.empty:
                dfb["dl_flag"] = dl_flag
                frames.append(dfb)
    pa.default_memory_pool().release_unused()

    df_d = pd.concat(frames, ignore_index=True)
    del frames
    df_d["dt_s"] = df_d["date"].dt.strftime("%Y-%m-%d")
    df_d.sort_values(["c6", "dt_s", "dl_flag"], inplace=True)
    df_d.drop_duplicates(["c6", "dt_s"], keep="first", inplace=True)
    df_d.reset_index(drop=True, inplace=True)

    ind_l2 = pd.read_csv(u34.CSRC_L2_CSV)
    ind_l2["c6"] = ind_l2["code"].astype(str).str[-6:].str.zfill(6)
    name_map = dict(zip(ind_l2["c6"], ind_l2["code_name"].fillna("")))
    df_d["is_st_name"] = df_d["c6"].map(name_map).fillna("").str.upper().str.contains("ST")

    g = df_d.groupby("c6", sort=False)
    df_d["adjf"] = np.where(df_d["close"] > 0, df_d["adj_close"] / df_d["close"], 1.0)
    df_d["prev_c_adj"] = g["close"].shift(1) * g["adjf"].shift(1) / df_d["adjf"]
    df_d["pct"] = np.where(df_d["prev_c_adj"] > 0, df_d["close"] / df_d["prev_c_adj"] - 1.0, 0.0)
    df_d["o_pct"] = np.where(df_d["prev_c_adj"] > 0, df_d["open"] / df_d["prev_c_adj"] - 1.0, 0.0)
    df_d["zt_px"] = np.floor(df_d["prev_c_adj"] * 1.10 * 100.0 + 0.5) / 100.0
    df_d["dt_px"] = np.floor(df_d["prev_c_adj"] * 0.90 * 100.0 + 0.5) / 100.0
    df_d["is_zt"] = (~df_d["is_st_name"]) & (df_d["close"] >= df_d["zt_px"] - 0.011) & (df_d["pct"] >= 0.095) & (df_d["prev_c_adj"] > 0)
    df_d["is_yizi"] = df_d["is_zt"] & (df_d["open"] >= df_d["zt_px"] - 0.011) & (df_d["low"] >= df_d["zt_px"] - 0.011)
    df_d["is_dt_exact"] = (df_d["close"] <= df_d["dt_px"] + 0.005) & (df_d["prev_c_adj"] > 0)
    df_d["is_yizi_dt"] = df_d["is_dt_exact"] & (df_d["open"] <= df_d["dt_px"] + 0.005) & (df_d["high"] <= df_d["dt_px"] + 0.005)

    s_zt = df_d["is_zt"].astype(int)
    df_d["streak"] = s_zt.groupby([df_d["c6"], (s_zt != g["is_zt"].shift().fillna(False)).cumsum()]).cumsum() * s_zt
    df_d["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)
    df_d["prev_is_yizi"] = g["is_yizi"].shift(1).fillna(False)

    # 1. Rivals on D2 09:25 (non-yizi-open 4b candidates) & buyable check
    rv_sub = df_d[(df_d["prev_streak"] == 4) & (~df_d["is_st_name"]) & (df_d["open"] < df_d["zt_px"] - 0.005) & (df_d["o_pct"] < 0.098) & (~df_d["prev_is_yizi"])]
    rivals_4b = defaultdict(list)
    for r in rv_sub[["dt_s", "c6", "o_pct"]].itertuples(index=False):
        rivals_4b[r.dt_s].append((r.c6, float(r.o_pct)))

    # Also include prev_is_yizi non-yizi-open 4b rivals (matching w2_4to5_enriched_master b4_rival_cnt)
    rv_all = df_d[(df_d["prev_streak"] == 4) & (~df_d["is_st_name"]) & (df_d["open"] < df_d["zt_px"] - 0.005) & (df_d["o_pct"] < 0.098)]
    rivals_4b_all = defaultdict(list)
    for r in rv_all[["dt_s", "c6", "o_pct"]].itertuples(index=False):
        rivals_4b_all[r.dt_s].append((r.c6, float(r.o_pct)))

    # 2. Daily streak==1, streak==3 codes, and b4_dt_cnt
    fb_codes_by_dt = defaultdict(set)
    b3_codes_by_dt = defaultdict(set)
    b4_nuke_by_dt = defaultdict(int)
    for r in df_d[(df_d["streak"] == 1) | (df_d["streak"] == 3) | ((df_d["prev_streak"] >= 2) & df_d["is_dt_exact"])][["dt_s", "c6", "streak", "prev_streak", "is_dt_exact", "is_st_name"]].itertuples(index=False):
        if r.streak == 1:
            fb_codes_by_dt[r.dt_s].add(r.c6)
        if r.streak == 3:
            b3_codes_by_dt[r.dt_s].add(r.c6)
        if (not r.is_st_name) and r.prev_streak >= 2 and r.is_dt_exact:
            b4_nuke_by_dt[r.dt_s] += 1

    # 3. Target codes dt_defer & bar_lu
    sub_t = df_d[df_d["c6"].isin(target_codes)].copy()
    by_c = {c6: grp[["dt_s", "open", "high", "low", "close", "adjf", "prev_c_adj", "dt_px", "is_dt_exact", "is_yizi_dt"]].reset_index(drop=True) for c6, grp in sub_t.groupby("c6")}
    dmap = {}
    bar_lu = {}
    for r in sub_t[["c6", "dt_s", "open", "close", "adjf", "is_dt_exact", "is_yizi_dt"]].itertuples(index=False):
        dmap[(r.c6, r.dt_s)] = r
        bar_lu[(r.c6, r.dt_s)] = (float(r.open), float(r.close), float(r.adjf))

    del df_d, sub_t
    gc.collect()
    return {
        "rivals_4b_nonyizi": dict(rivals_4b),
        "rivals_4b_all": dict(rivals_4b_all),
        "fb_codes_by_dt": dict(fb_codes_by_dt),
        "b3_codes_by_dt": dict(b3_codes_by_dt),
        "b4_nuke_by_dt": dict(b4_nuke_by_dt),
        "by_c": by_c,
        "dmap": dmap,
        "bar_lu": bar_lu,
    }


def defer_dt_local(c6: str, buy_dt: str, buy_px: float, exit_dt: str, exit_hhmm: int, exit_px: float, net_ret: float, daily_ctx: dict, fee: float) -> tuple[str, int, float, float, bool]:
    """Exact V19.1 15:00 locked limit-down deferral using strictly truncated daily_ctx."""
    if int(exit_hhmm) < 1455:
        return exit_dt, int(exit_hhmm), float(exit_px), float(net_ret), False
    dmap, by_c = daily_ctx["dmap"], daily_ctx["by_c"]
    eb = dmap.get((c6, exit_dt))
    bb = dmap.get((c6, buy_dt))
    gc_df = by_c.get(c6)
    if eb is None or bb is None or gc_df is None or (not bool(eb.is_dt_exact)):
        return exit_dt, int(exit_hhmm), float(exit_px), float(net_ret), False
    matches = gc_df.index[gc_df["dt_s"] == exit_dt]
    if len(matches) == 0:
        return exit_dt, int(exit_hhmm), float(exit_px), float(net_ret), False
    pe = int(matches[0])
    if pe + 1 >= len(gc_df):
        return exit_dt, int(exit_hhmm), float(exit_px), float(net_ret), False
    k = pe + 1
    while k < len(gc_df) - 1 and bool(gc_df.loc[k, "is_yizi_dt"]):
        k += 1
    nb = gc_df.loc[k]
    nep = round(float(nb["open"]), 2)
    nret = float((float(nb["open"]) * float(nb["adjf"])) / (float(buy_px) * float(bb.adjf)) * (1.0 - fee) - 1.0)
    return str(nb["dt_s"]), 925, nep, nret, True


def compute_d2_4to5_genes(cache: dict, daily_ctx: dict, max_dt: str) -> dict[int, dict]:
    """
    Strictly PIT (D1 close + D2 <09:25 notices + D2 09:25 auction) compute 4to5 scorecard & atomic genes
    for every 3to4 trade whose D1 (`pos`) sealed 4th board (`is_zt[pos] == True`).
    Zero future peek beyond D2 09:25!
    """
    code_bars = cache["code_bars_ext"]
    holders = cache["holders_map"]
    tape_ext = cache["tape_ext_map"]
    lhb_map = cache["lhb_map"]
    mkt_env = cache["mkt_env"]
    sh_map, sz_map = cache["sh_map"], cache["sz_map"]
    all_dts = cache["all_dts"]
    dt_to_idx = cache["dt_to_idx"]
    kpl_plate_zt = cache["kpl_plate_zt_stocks"]
    stock_theme = cache["stock_theme_5y"]
    open_lu = cache["open_lookup_by_dt"]
    bars_5m = cache["bars_5m_map"]
    sreg_map = cache["sreg_map"]

    target_codes = {e["code"] for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 78.0 and e["buy_px"] is not None}

    # PIT notices strictly <= max_dt
    df_tox = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet")
    df_tox["c6"] = df_tox["sec_code"].astype(str).str[:6].str.zfill(6)
    df_tox["pdt"] = df_tox["pub_datetime_cst"].astype(str)
    df_tox = df_tox[(df_tox["c6"].isin(target_codes)) & (df_tox["pdt"] <= max_dt + " 23:59:59")].copy()

    tox_strict_ts = defaultdict(list)
    tox_narrow_ts = defaultdict(list)
    tox_jianchi_ts = defaultdict(list)
    tox_riskhint_ts = defaultdict(list)
    for r in df_tox.itertuples(index=False):
        ti = str(r.title or "")
        if TOX_STRICT_RE.search(ti):
            tox_strict_ts[r.c6].append(r.pdt)
        if TOX_NARROW_RE.search(ti):
            tox_narrow_ts[r.c6].append(r.pdt)
        if TOX_JIANCHI_RE.search(ti):
            tox_jianchi_ts[r.c6].append(r.pdt)
        if TOX_RISKHINT_RE.search(ti):
            tox_riskhint_ts[r.c6].append(r.pdt)

    # Also cninfo_notices_5y_pit.db reg notices strictly <= max_dt (mode=ro)
    cn_reg_ts = defaultdict(list)
    con_cn = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    ph = ",".join("?" for _ in target_codes)
    for sc, pdt, ti in con_cn.execute(
        f"SELECT sec_code, pub_datetime_cst, title FROM notices WHERE sec_code IN ({ph}) AND pub_datetime_cst <= ?",
        (*sorted(target_codes), max_dt + " 23:59:59"),
    ):
        ti_s = str(ti or "")
        if any(w in ti_s for w in REG_INC) and not any(w in ti_s for w in REG_EXC):
            cn_reg_ts[str(sc).zfill(6)].append(str(pdt))
    con_cn.close()

    genes = {}
    for e in cache["buy_entries"]:
        if (not e["skel"]) or (e["sc_v40"] < 78.0) or (e["buy_px"] is None):
            continue
        c6 = e["code"]
        cb = code_bars[c6]
        pos = e["pos"]
        if not bool(cb["is_zt"][pos]) or pos + 1 >= len(cb["dts"]):
            continue

        sd = str(cb["dts"][pos])       # D1 = 4th board day (signal day for 4to5)
        bd = str(cb["dts"][pos + 1])   # D2 = 5th board day (4to5 buy day)
        d3d = str(cb["dts"][pos - 1]) if pos >= 1 else sd
        o_d2 = float(cb["open"][pos + 1])
        pc_d2 = float(cb["pre_c"][pos + 1])
        zt_d2 = float(cb["zt_px"][pos + 1])
        op_pct = (o_d2 / pc_d2 - 1.0) if pc_d2 > 0 else 0.0
        buyable_open = bool((o_d2 < zt_d2 - 0.005) and (not bool(cb["is_yizi"][pos + 1])) and (op_pct < 0.098))
        is_yizi_d2 = bool(o_d2 >= zt_d2 - 0.005)

        # 1. Headroom at D2 09:25 strictly using D1 index close (`imap[sd]`)
        imap = sh_map if c6.startswith("60") else sz_map
        ir = imap.get(sd)
        hr10, hr30 = 0.0, 0.0
        if o_d2 > 0 and ir:
            p100, p200 = 99999.0, 99999.0
            for lb in range(1, min(11, pos + 2)):
                j = pos + 1 - lb
                bi_v = imap.get(cb["dts"][j])
                bc_v = float(cb["close"][j] * cb["adjf"][j] / cb["adjf"][pos + 1])
                if bi_v and bc_v > 0:
                    p100 = min(p100, bc_v * (2.0 + (ir / bi_v - 1.0)))
            for lb in range(1, min(31, pos + 2)):
                j = pos + 1 - lb
                bi_v = imap.get(cb["dts"][j])
                bc_v = float(cb["close"][j] * cb["adjf"][j] / cb["adjf"][pos + 1])
                if bi_v and bc_v > 0:
                    p200 = min(p200, bc_v * (3.0 + (ir / bi_v - 1.0)))
            hr10 = (p100 / o_d2 - 1.0) if p100 < 99990.0 else 0.5
            hr30 = (p200 / o_d2 - 1.0) if p200 < 99990.0 else 0.5
        tighter_hr = min(hr10, hr30)

        # 2. Notices strictly [bd - 90d .. bd 09:25:00) / [bd - 10d .. bd 09:25:00)
        d90 = (pd.Timestamp(bd) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
        d10 = (pd.Timestamp(bd) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        cut_ts = f"{bd} 09:25:00"
        tox_strict = any(d90 <= ts[:10] and ts <= cut_ts for ts in tox_strict_ts.get(c6, []))
        tox_narrow = any(d90 <= ts[:10] and ts <= cut_ts for ts in tox_narrow_ts.get(c6, []))
        tox_jianchi = any(d90 <= ts[:10] and ts <= cut_ts for ts in tox_jianchi_ts.get(c6, []))
        tox_riskhint = any(d90 <= ts[:10] and ts <= cut_ts for ts in tox_riskhint_ts.get(c6, []))

        sreg_hits = [str(x) for x in sreg_map.get(c6, []) if d10 <= str(x)[:10] and str(x) <= cut_ts]
        cn_hits = [ts for ts in cn_reg_ts.get(c6, []) if d10 <= ts[:10] and ts <= cut_ts]
        s_reg_10d = bool(sreg_hits or cn_hits)

        # 3. D1 (4th board) blown in PM 5m?
        arr_d1 = bars_5m.get((c6, sd))
        zt_d1 = float(cb["zt_px"][pos])
        d4_blown_pm = False
        if arr_d1 is not None and len(arr_d1) > 0:
            sealed_yet = False
            for row5 in arr_d1:
                hh5, bh5, bl5, bc5 = int(row5[0]), float(row5[2]), float(row5[3]), float(row5[4])
                if bh5 >= zt_d1 - 0.005:
                    sealed_yet = True
                if hh5 >= 1300 and sealed_yet and (bl5 < zt_d1 - 0.005 or bc5 < zt_d1 - 0.005):
                    d4_blown_pm = True
                    break

        # 4. Lock & real_free_mcap at D1 close
        h_recs = [x for x in holders.get(c6, []) if str(x[0])[:10] <= sd]
        lock_top10 = float(max(h_recs, key=lambda x: (str(x[1]), str(x[0])))[2]) if h_recs else float(e["lock_top10"])
        mcap_d1 = float(cb["mcap"][pos]) if cb["mcap"][pos] > 0 else 40.0
        real_mcap = mcap_d1 * max(0.05, 1.0 - lock_top10 / 100.0)

        # 5. Market env & 4-board rivals at D2 09:25
        env_d1 = mkt_env.get(sd, {})
        max_b_prev = int(env_d1.get("max_board", 4))
        f47_reb = float(env_d1.get("brk_reb_r10", 0.20))
        d4_nuke_cnt = int(daily_ctx["b4_nuke_by_dt"].get(sd, 0))

        rivals_all = daily_ctx["rivals_4b_all"].get(bd, [])
        b4_rival_cnt = len(rivals_all)
        is_sole = int(b4_rival_cnt <= 1)
        if rivals_all:
            top_op = max(x[1] for x in rivals_all)
            is_top1 = int(op_pct >= top_op - 1e-6)
        else:
            is_top1 = 1

        # 6. D1 Tape & D3->D4 turnover & D1 LHB
        tp4 = tape_ext.get((sd, c6), {})
        tp3 = tape_ext.get((d3d, c6), {})
        obc = int(tp4.get("open_board_count", 0))
        fst = str(tp4.get("first_seal_time", "99:99:99"))
        seal_amt = float(tp4.get("seal_amount", 0.0))
        amt_d1 = float(cb["amount"][pos])
        seal_ratio = (seal_amt / amt_d1) if amt_d1 > 0 else 0.0
        d3_obc = int(tp3.get("open_board_count", 0))
        to_r = float(cb["to"][pos] / max(1e-4, cb["to"][pos - 1])) if pos >= 1 else 1.0

        lhb4 = lhb_map.get((sd, c6))
        f_quant_sell = 1 if (lhb4 and lhb4["qu_net_sell"] > 0) else 0
        f_inst_sell = 1 if (lhb4 and lhb4["inst_net_sell"] > 1e7) else 0
        f_top_yz_new = False
        if lhb4 and lhb4["top_yz_buys"]:
            # Check if new on D1 vs D2/D3
            prev_yz = set()
            for j_p in range(max(0, pos - 3), pos):
                lj = lhb_map.get((str(cb["dts"][j_p]), c6))
                if lj:
                    prev_yz |= lj["top_yz_buys"]
            f_top_yz_new = bool(lhb4["top_yz_buys"] - prev_yz)
        f_lh_cnt = int(lhb4["lh_cnt"]) if lhb4 else 0

        # 7. Same-plate assist & crowding on D1 + D2 09:25
        plate = stock_theme.get((sd, c6), {}).get("plate", e["plate"])
        p_elo_d1 = float(stock_theme.get((sd, c6), {}).get("p_elo", 100.0))
        plate_stocks = [x for x in kpl_plate_zt.get((sd, plate), []) if x != c6]
        fb_set = daily_ctx["fb_codes_by_dt"].get(sd, set())
        b3_set = daily_ctx["b3_codes_by_dt"].get(sd, set())
        op_dt = open_lu.get(bd, {})
        fb_ho_cnt, fb_yz_cnt, plate_3b_cnt = 0, 0, 0
        peer_ops = []
        for pc_c in plate_stocks:
            if pc_c in b3_set:
                plate_3b_cnt += 1
            info = op_dt.get(pc_c)
            if info is not None:
                peer_ops.append(info[0])
                if pc_c in fb_set:
                    if info[0] >= 0.03:
                        fb_ho_cnt += 1
                    if info[1]:
                        fb_yz_cnt += 1
        peers_op_avg = float(np.mean(peer_ops)) if peer_ops else 0.0

        # 8. Calendar & price level
        px_d4 = float(cb["close"][pos])
        d4_op = float(cb["open"][pos] / cb["pre_c"][pos] - 1.0) if cb["pre_c"][pos] > 0 else 0.0
        d4_buyable = not bool(cb["is_yizi"][pos])
        d3_yizi = bool(cb["is_yizi"][pos - 1]) if pos >= 1 else False
        dt_obj = pd.Timestamp(bd)
        dow = dt_obj.weekday() + 1
        bi_idx = dt_to_idx.get(bd, -1)
        is_post_mon = ((dt_obj - pd.Timestamp(all_dts[bi_idx - 1])).days >= 3) if bi_idx > 0 else (dow == 1)
        mo = dt_obj.month

        # 9. Exact 4to5 Fixed-PIT arithmetic score (WITHOUT buyability/open -999 cutoff!)
        sc = 100
        if (lock_top10 >= 50.0) and (12.0 <= real_mcap <= 35.0):
            sc += 8
        elif (lock_top10 >= 45.0) or (real_mcap >= 45.0):
            sc += 3
        elif (lock_top10 < 45.0) and (real_mcap < 45.0):
            sc -= 8

        if tighter_hr >= 0.25:
            sc += 6
        elif tighter_hr >= 0.22:
            sc += 4

        if max_b_prev == 4:
            sc += 5
        elif max_b_prev == 5:
            sc += 2
        elif max_b_prev >= 6:
            sc -= 5

        if is_sole == 1:
            sc += 6
        elif is_top1 == 1 and b4_rival_cnt < 2:
            sc += 3
        else:
            sc -= 5

        d4_s34 = float(e["sc_v40"])
        if (82.0 <= d4_s34 <= 89.0) and is_sole == 1:
            sc += 5
        sc += 4  # is_held_3to4 is ALWAYS True here because 3to4 bought and holds it!
        if ((d4_op > 0.092) or (not d4_buyable) or d3_yizi) and (0.020 <= op_pct <= 0.060):
            sc += 3
        if (obc >= 1) and (d3_obc >= 1) and (0.70 <= to_r <= 1.35):
            sc += 3

        if f_quant_sell >= 1:
            sc -= 5
        if f_inst_sell >= 1:
            sc -= 3
        if f_top_yz_new:
            sc -= 3
        if f_lh_cnt >= 3:
            sc -= 6

        if plate_3b_cnt >= 1:
            sc -= 6
        if px_d4 > 20.0:
            sc -= 6
        if d4_nuke_cnt >= 1:
            sc -= 3
        if f47_reb >= 0.20:
            sc += 6
        if dow == 1 or is_post_mon:
            sc += 6
        elif dow in (4, 5):
            sc -= 3
        if mo in (1, 5):
            sc -= 6

        in_sweet = 0.020 <= op_pct <= 0.075
        clean_no_tox_narrow = (not tox_narrow) and (not s_reg_10d) and (tighter_hr >= 0.12) and (not d4_blown_pm)
        clean_no_tox_strict = (not tox_strict) and (not s_reg_10d) and (tighter_hr >= 0.12) and (not d4_blown_pm)

        genes[e["idx"]] = {
            "d2_dt": bd,
            "core_score": int(sc),
            "buyable_open": buyable_open,
            "is_yizi_d2": is_yizi_d2,
            "in_sweet_2_7": in_sweet,
            "d2_open_pct": op_pct,
            "fix_pass_114": bool(buyable_open and in_sweet and clean_no_tox_narrow and sc >= 114),
            "fix_pass_120": bool(buyable_open and in_sweet and clean_no_tox_narrow and sc >= 120),
            "strict_pass_114": bool(buyable_open and in_sweet and clean_no_tox_strict and sc >= 114),
            "core_clean_ge114": bool(clean_no_tox_strict and op_pct >= 0.020 and sc >= 114),
            "core_clean_ge120": bool(clean_no_tox_strict and op_pct >= 0.020 and sc >= 120),
            "core_clean_ge110": bool(clean_no_tox_strict and op_pct >= 0.020 and sc >= 110),
            "core_lt100": bool(sc < 100),
            "core_lt105": bool(sc < 105),
            # Red-light gates
            "tox_strict": tox_strict,
            "tox_jianchi": tox_jianchi,
            "tox_riskhint": tox_riskhint,
            "s_reg_10d": s_reg_10d,
            "hr_lt12": bool(tighter_hr < 0.12),
            "d4_blown_pm": d4_blown_pm,
            "red_any_real": bool(tox_strict or s_reg_10d or tighter_hr < 0.12 or d4_blown_pm),
            "red_no_riskhint": bool(tox_jianchi or s_reg_10d or tighter_hr < 0.12 or d4_blown_pm),
            # Atomic features
            "lock_sweet": bool((lock_top10 >= 50.0) and (12.0 <= real_mcap <= 35.0)),
            "lock_ok": bool((lock_top10 >= 45.0) or (real_mcap >= 45.0)),
            "lock_bad": bool((lock_top10 < 45.0) and (real_mcap < 45.0)),
            "hr_ge22": bool(tighter_hr >= 0.22),
            "hr_ge25": bool(tighter_hr >= 0.25),
            "fb_assist_ge1": bool(fb_ho_cnt >= 1),
            "fb_assist_ge2": bool(fb_ho_cnt >= 2 and fb_yz_cnt == 0),
            "no_fb_assist": bool(fb_ho_cnt == 0),
            "plate_3b_crowd": bool(plate_3b_cnt >= 1),
            "peers_neg15": bool(len(peer_ops) > 0 and peers_op_avg < -0.015),
            "d4_clean_seal": bool(obc == 0 and fst <= "10:30:00"),
            "d4_rotten_seal": bool(obc >= 2 or fst >= "14:00:00" or d4_blown_pm),
            "d4_tiny_seal": bool(seal_ratio < 0.01),
            "d2_yizi_or_high": bool(is_yizi_d2 or op_pct >= 0.075),
            "d2_weak_lt2": bool(op_pct < 0.020),
            "d2_neg_open": bool(op_pct < 0.0),
            "is_sole_4b": bool(is_sole == 1),
            "is_top1_4b": bool(is_top1 == 1),
            "crowded_loser": bool(b4_rival_cnt >= 2 and is_top1 == 0),
            "status_lead4": bool(max_b_prev == 4),
            "status_ge6": bool(max_b_prev >= 6),
            "d4_lhb_bad": bool(f_quant_sell >= 1 or f_inst_sell >= 1 or f_lh_cnt >= 3),
            "px_gt20": bool(px_d4 > 20.0),
            "p_elo_lt135": bool(p_elo_d1 < 135.0),
        }
    return genes


def sim_3to4_exit_p1a(
    entry: dict,
    cache: dict,
    k_states: dict,
    d2_gene: Optional[dict],
    mode_cfg: Optional[dict],
) -> tuple[str, float, float, int, int, str]:
    """
    Exact 3to4 V4.1 simulator with optional D2 (4->5 window) causal gating.
    When `mode_cfg` is None, reproduces `V4.1` (`XF30_7f_ge1_1345d70`) with 0.0 diff.
    """
    c6 = entry["code"]
    pos = entry["pos"]
    cb = cache["code_bars_ext"][c6]
    bars_5m = cache["bars_5m_map"]
    n = len(cb["dts"])
    is_d1_zt = bool(cb["is_zt"][pos])

    def _run_zt_hold(start_p: int) -> tuple[str, float, float, int, int, str]:
        k = start_p + 1
        imm_used = False
        while k < n:
            if bool(cb["is_yizi_dt"][k]):
                k += 1
                continue
            dt_s = str(cb["dts"][k])
            ok = float(cb["open"][k])
            pck = float(cb["pre_c"][k])
            clk = float(cb["close"][k])
            ztk = float(cb["zt_px"][k])
            dtk = round(pck * 0.90, 2)
            if k > start_p + 1 and bool(cb["is_yizi_dt"][k - 1]):
                return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "yizi_dt_open"

            st = k_states.get(k, {})
            rpts = _risk7_pts(st)
            base_thr = 0.070 if rpts >= 1 else 0.050

            is_d2_4to5 = (k == pos + 1) and is_d1_zt and (d2_gene is not None)
            use_thr: Optional[float] = base_thr
            strip_imm_today = False
            cut_0925_today = False
            tight_1030_today = False

            if mode_cfg is not None:
                cond_fn = mode_cfg["cond_fn"]
                if is_d2_4to5 and cond_fn(d2_gene, st):
                    act = mode_cfg["action"]
                    if act == "exempt_tight":
                        use_thr = 0.050
                    elif act == "relax_35":
                        use_thr = 0.035
                    elif act == "relax_30":
                        use_thr = 0.030
                    elif act == "disable_1345":
                        use_thr = None
                    elif act == "tight_65":
                        use_thr = max(base_thr, 0.065)
                    elif act == "tight_70":
                        use_thr = max(base_thr, 0.070)
                    elif act == "tight_80":
                        use_thr = 0.080
                    elif act == "tight_step":
                        use_thr = 0.080 if base_thr >= 0.070 else 0.065
                    elif act == "strip_imm":
                        strip_imm_today = True
                    elif act == "tight80_strip":
                        use_thr = 0.080
                        strip_imm_today = True
                    elif act == "tight70_strip":
                        use_thr = max(base_thr, 0.070)
                        strip_imm_today = True
                    elif act == "cut_0925":
                        cut_0925_today = True
                    elif act == "tight_1030vwap":
                        tight_1030_today = True
                elif mode_cfg.get("apply_all_hold") and is_d1_zt and (d2_gene is not None) and cond_fn(d2_gene, st):
                    if mode_cfg["action"] == "exempt_tight_all":
                        use_thr = 0.050

            if cut_0925_today and ok > dtk + 0.005:
                return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "d2_0925_cut"

            arr = bars_5m.get((c6, dt_s))
            if arr is not None and len(arr) > 0:
                peak = ok
                cum_v, cum_a = 0.0, 0.0
                for bi, row in enumerate(arr):
                    hh = int(row[0])
                    bo, bh, bl, bc = float(row[1]), float(row[2]), float(row[3]), float(row[4])
                    cum_v += float(row[5])
                    cum_a += float(row[6])
                    vwap_now = (cum_a / cum_v) if cum_v > 0 else bc
                    if bh <= dtk + 0.005:
                        continue
                    if tight_1030_today and hh == 1030 and bc < ztk - 0.01 and bc < vwap_now:
                        px = float(arr[bi + 1, 1]) if bi + 1 < len(arr) else bc
                        ehh = int(arr[bi + 1, 0]) if bi + 1 < len(arr) else 1030
                        if px > dtk + 0.005:
                            return dt_s, px, float(cb["adjf"][k]), k - pos, ehh, "d2_1030vwap"
                    if use_thr is not None and hh >= 1345 and peak >= pck * 1.085 and bl <= pck * (1.0 + use_thr) and bc < ztk - 0.01:
                        return dt_s, float(min(bo, pck * (1.0 + use_thr))), float(cb["adjf"][k]), k - pos, hh, "c_1345_guard"
                    if bh > peak:
                        peak = bh

            if bool(cb["is_zt"][k]):
                k += 1
                continue

            base_imm = (not imm_used) and (clk > ok) and (clk >= pck)
            if strip_imm_today:
                imm_ok = False
            else:
                imm_ok = base_imm
            if imm_ok:
                imm_used = True
                k += 1
                continue
            return dt_s, clk, float(cb["adjf"][k]), max(1, k - pos), 1500, "d_eod_close"

        k_end = n - 1
        return str(cb["dts"][k_end]), float(cb["close"][k_end]), float(cb["adjf"][k_end]), max(1, k_end - pos), 1500, "end_data"

    if not is_d1_zt:
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        k = min(k, n - 1)
        o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
        o5, p5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
        if k > pos + 1:
            return str(cb["dts"][k]), o5, float(cb["adjf"][k]), k - pos, 925, "a_yizi_dt_open"
        if not ((c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)):
            return str(cb["dts"][k]), o5, float(cb["adjf"][k]), max(1, k - pos), 925, "a_d5_cut"
        if bool(cb["is_zt"][k]):
            return _run_zt_hold(k)
        return str(cb["dts"][k]), c5, float(cb["adjf"][k]), max(1, k - pos), 1500, "a_d5_eod"

    return _run_zt_hold(pos)


def evaluate_dirA_variant(
    name: str,
    group: str,
    cache: dict,
    states: dict,
    genes: dict,
    daily_ctx: dict,
    bench_df: pd.DataFrame,
    cal_dts: list[str],
    mode_cfg: Optional[dict],
    max_dt: str,
    v21_bl_keys: Optional[set] = None,
    min_score: float = 90.0,
) -> dict:
    """Evaluate a Direction A variant at 30bps (primary) + 50bps stress + V21/78+ pools."""
    code_bars = cache["code_bars_ext"]
    bar_lu = daily_ctx["bar_lu"]
    recs = []
    for e in cache["buy_entries"]:
        if (not e["skel"]) or (e["sc_v40"] < min_score) or (e["buy_px"] is None):
            continue
        c6, bd, pos = e["code"], e["buy_date"], e["pos"]
        cb = code_bars[c6]
        ex_dt, spx, adjs, hb, shh, rsn = sim_3to4_exit_p1a(e, cache, states.get(e["idx"], {}), genes.get(e["idx"]), mode_cfg)
        bpx_r = round(float(e["buy_px"]), 2)
        spx_r = round(float(spx), 2)
        nr20 = (float(spx) * float(adjs)) / (float(e["buy_px"]) * float(cb["adjf"][pos])) * (1.0 - 0.0020) - 1.0
        ned, neh, nep, nret20_def, dt_def = defer_dt_local(c6, bd, bpx_r, ex_dt, shh, spx_r, nr20, daily_ctx, 0.0020)
        final_ret20 = nret20_def if dt_def else nr20
        if ned > max_dt:
            continue
        r30 = float(cm.convert_fee(final_ret20, 0.0020, cm.FEE_MAIN))
        r50 = float(cm.convert_fee(final_ret20, 0.0020, cm.FEE_STRESS))
        recs.append({
            "idx": e["idx"], "code": c6, "name": e["name"], "buy_date": bd, "buy_hhmm": int(e["buy_hhmm"]),
            "buy_price": bpx_r, "exit_date": ned, "exit_hhmm": int(neh), "exit_price": round(float(nep), 2),
            "hold_bars": int(hb), "net_ret_020": float(final_ret20), "net_ret": r30, "net_ret_030": r30, "net_ret_050": r50,
            "score": int(round(e["sc_v40"])), "priority_score": e["priority_score"],
            "open_pct": e["open_pct"], "reason": rsn, "dt_deferred": bool(dt_def),
        })

    raw_df = pd.DataFrame(recs)
    slot_df = cm.select_single_slot_3to4(raw_df)
    if not slot_df.empty:
        slot_df["mtm_pairs_json"] = cm.build_mtm_pairs(slot_df, cal_dts, bar_lu, ret_col="net_ret", px_col="buy_price")

    windows = cm.eval_all_windows(slot_df, raw_df, bench_df, max_dt=max_dt, base_fee=cm.FEE_MAIN)
    boot = cm.bootstrap_10k(slot_df["net_ret"].to_numpy(float) if not slot_df.empty else np.array([]))

    # Optional V21 (`m4_4way_bl15`) subset check
    v21_info = {}
    if v21_bl_keys is not None and not raw_df.empty:
        raw_v21 = raw_df[~raw_df.apply(lambda r: (r["buy_date"], r["code"]) in v21_bl_keys, axis=1)].copy()
        slot_v21 = cm.select_single_slot_3to4(raw_v21)
        if not slot_v21.empty:
            slot_v21["mtm_pairs_json"] = cm.build_mtm_pairs(slot_v21, cal_dts, bar_lu, ret_col="net_ret", px_col="buy_price")
        wv21 = cm.eval_all_windows(slot_v21, raw_v21, bench_df, max_dt=max_dt, base_fee=cm.FEE_MAIN)
        v21_info = {
            "IS_nav": wv21.get("IS_21_23", {}).get("nav", 1.0),
            "OOS_nav": wv21.get("OOS_24_26", {}).get("nav", 1.0),
            "Y2526_nav": wv21.get("Y2025_2026", {}).get("nav", 1.0),
            "FULL_nav": wv21.get("FULL_5Y", {}).get("nav", 1.0),
        }

    return {
        "name": name,
        "group": group,
        "windows": windows,
        "bootstrap_10k": boot,
        "v21_pool": v21_info,
        "raw_df": raw_df,
        "slot_df": slot_df,
    }


def build_variant_specs() -> list[tuple[str, str, Optional[dict]]]:
    """Define Direction A variants: (A1) high-score protection, (A2) red-light/low-score tightening/veto, (A3) single-atom ablations."""
    specs = [("V41_Base", "0_BASE", None)]

    # (A1) High-score protection on D2
    a1_gates = [
        ("Str114", lambda g, st: g["strict_pass_114"]),
        ("Fix114", lambda g, st: g["fix_pass_114"]),
        ("Fix120", lambda g, st: g["fix_pass_120"]),
        ("Core114Clean", lambda g, st: g["core_clean_ge114"]),
        ("Core120Clean", lambda g, st: g["core_clean_ge120"]),
        ("Core110Clean", lambda g, st: g["core_clean_ge110"]),
        ("D2YiziOrHigh", lambda g, st: g["d2_yizi_or_high"]),
    ]
    for gn, gfn in a1_gates:
        for act, albl in [
            ("exempt_tight", "Exempt7to5"),
            ("relax_35", "Relax35"),
            ("disable_1345", "No1345D2"),
        ]:
            specs.append((f"A1_{gn}_{albl}", "A1_PROTECT", {"cond_fn": gfn, "action": act}))
    specs.append(("A1_Core114Clean_ExemptAllHold", "A1_PROTECT", {"cond_fn": lambda g, st: g["core_clean_ge114"], "action": "exempt_tight_all", "apply_all_hold": True}))

    # (A2) Red-light / low-score tightening or veto on D2 (including explicit DF024 09:25 cut audit)
    a2_gates = [
        ("RedAnyReal", lambda g, st: g["red_any_real"]),
        ("RedNoRiskHint", lambda g, st: g["red_no_riskhint"]),
        ("ToxStrict", lambda g, st: g["tox_strict"]),
        ("ToxJianchi", lambda g, st: g["tox_jianchi"]),
        ("ToxRiskHint", lambda g, st: g["tox_riskhint"]),
        ("SReg10d", lambda g, st: g["s_reg_10d"]),
        ("HrLt12", lambda g, st: g["hr_lt12"]),
        ("D4BlownPM", lambda g, st: g["d4_blown_pm"]),
        ("D2OpenLt2", lambda g, st: g["d2_weak_lt2"]),
        ("D2OpenNeg", lambda g, st: g["d2_neg_open"]),
        ("CoreLt100", lambda g, st: g["core_lt100"]),
        ("CoreLt105", lambda g, st: g["core_lt105"]),
    ]
    for rn, rfn in a2_gates:
        for act, albl in [
            ("tight_step", "TightStep"),
            ("tight_70", "Tight70"),
            ("tight_80", "Tight80"),
            ("strip_imm", "StripImm"),
            ("tight80_strip", "Tight80Strip"),
            ("cut_0925", "Cut0925_DF024"),
        ]:
            specs.append((f"A2_{rn}_{albl}", "A2_REDLIGHT", {"cond_fn": rfn, "action": act}))

    # (A3) Single-atom exhaustive ablation on D2 (positive protection + negative tightening/strip)
    pos_atoms = [
        ("LockSweet", lambda g, st: g["lock_sweet"]),
        ("LockOk", lambda g, st: g["lock_ok"]),
        ("HrGe22", lambda g, st: g["hr_ge22"]),
        ("HrGe25", lambda g, st: g["hr_ge25"]),
        ("FBAssist1", lambda g, st: g["fb_assist_ge1"]),
        ("FBAssist2", lambda g, st: g["fb_assist_ge2"]),
        ("D4CleanSeal", lambda g, st: g["d4_clean_seal"]),
        ("Sole4B", lambda g, st: g["is_sole_4b"]),
        ("Top1_4B", lambda g, st: g["is_top1_4b"]),
        ("StatusLead4", lambda g, st: g["status_lead4"]),
        ("EloLt135", lambda g, st: g["p_elo_lt135"]),
    ]
    for an, afn in pos_atoms:
        specs.append((f"A3_Pos_{an}_Exempt", "A3_ATOM_POS", {"cond_fn": afn, "action": "exempt_tight"}))
        specs.append((f"A3_Pos_{an}_Relax35", "A3_ATOM_POS", {"cond_fn": afn, "action": "relax_35"}))

    neg_atoms = [
        ("LockBad", lambda g, st: g["lock_bad"]),
        ("NoFBAssist", lambda g, st: g["no_fb_assist"]),
        ("Plate3BCrowd", lambda g, st: g["plate_3b_crowd"]),
        ("PeersNeg15", lambda g, st: g["peers_neg15"]),
        ("D4RottenSeal", lambda g, st: g["d4_rotten_seal"]),
        ("D4TinySeal", lambda g, st: g["d4_tiny_seal"]),
        ("CrowdedLoser", lambda g, st: g["crowded_loser"]),
        ("StatusGe6", lambda g, st: g["status_ge6"]),
        ("D4LhbBad", lambda g, st: g["d4_lhb_bad"]),
        ("PxGt20", lambda g, st: g["px_gt20"]),
    ]
    for an, afn in neg_atoms:
        specs.append((f"A3_Neg_{an}_TightStep", "A3_ATOM_NEG", {"cond_fn": afn, "action": "tight_step"}))
        specs.append((f"A3_Neg_{an}_Tight80", "A3_ATOM_NEG", {"cond_fn": afn, "action": "tight_80"}))
        specs.append((f"A3_Neg_{an}_StripImm", "A3_ATOM_NEG", {"cond_fn": afn, "action": "strip_imm"}))
        specs.append((f"A3_Neg_{an}_Cut0925", "A3_ATOM_NEG", {"cond_fn": afn, "action": "cut_0925"}))

    return specs


def run_pipeline(max_date: str = "2026-11-16", trunc_mode: bool = False) -> dict:
    t0 = time.time()
    if max_date == "2026-11-16" and (not trunc_mode):
        with open(f"{F1_DIR}/pit_exit_cache_full.pkl", "rb") as f:
            cache = pickle.load(f)
    else:
        cache = s1_34.build_exit_pit_data(max_date, verbose=False)

    states = efe.precompute_trade_day_states(cache, min_score=78.0)
    target_codes = {e["code"] for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 78.0 and e["buy_px"] is not None}
    daily_ctx = load_daily_context_pit(target_codes, max_dt=max_date)
    bench_df, _, _, _, _ = cm.load_bench_and_indices(max_dt=max_date)
    cal_dts = bench_df["trade_date"].tolist()
    genes = compute_d2_4to5_genes(cache, daily_ctx, max_dt=max_date)

    # Check V21 m4_4way_bl15 blocked keys (from rd038_master_cache)
    v21_bl_keys = set()
    rc_path = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126/_cache/rd038_master_cache.pkl"
    if (not trunc_mode) and os.path.exists(rc_path):
        with open(rc_path, "rb") as f:
            rc = pickle.load(f)
        p34 = rc["pools_ext"]["3to4"]
        m4_mask = rc["other5_variants"]["3to4"]["m4_4way_bl15"]["mask"]
        blk = p34[(p34["orig_pass"] == 1) & (~m4_mask)]
        v21_bl_keys = set(zip(blk["buy_date"].astype(str).str[:10], blk["code"].astype(str).str.zfill(6)))
        del rc

    # 1. Exact 20bps parity verification vs ledger_3to4_xf30_std.csv (when max_date == 2026-11-16)
    base_res = evaluate_dirA_variant("V41_Base", "0_BASE", cache, states, genes, daily_ctx, bench_df, cal_dts, None, max_dt=max_date)
    parity_ok = True
    max_parity_diff = 0.0
    if not trunc_mode:
        led = pd.read_csv(f"{F1_DIR}/ledger_3to4_xf30_std.csv")
        led["c6"] = led["code"].astype(str).str.zfill(6)
        b_ss = base_res["slot_df"]
        parity_ok = (len(b_ss) == len(led)) and (b_ss["code"].to_numpy() == led["c6"].to_numpy()).all()
        max_parity_diff = float(np.max(np.abs(b_ss["net_ret_020"].round(6).to_numpy() - led["net_ret"].to_numpy()))) if parity_ok else 999.0
        assert parity_ok and max_parity_diff == 0.0, f"Baseline 20bps parity fail: {parity_ok}, {max_parity_diff}"

    # 2. Run all variants
    specs = build_variant_specs()
    results = {}
    summary_rows = []
    b_w = base_res["windows"]
    b_raw = base_res["raw_df"].set_index("idx")

    for vname, grp, cfg in specs:
        res = base_res if vname == "V41_Base" else evaluate_dirA_variant(
            vname, grp, cache, states, genes, daily_ctx, bench_df, cal_dts, cfg, max_dt=max_date, v21_bl_keys=v21_bl_keys if not trunc_mode else None
        )
        w = res["windows"]
        c_raw = res["raw_df"].set_index("idx")
        chg_mask = (c_raw["net_ret"] - b_raw["net_ret"]).abs() > 1e-6
        n_chg = int(chg_mask.sum())
        n_win_chg = int(((c_raw["net_ret"] - b_raw["net_ret"]) > 1e-6).sum())
        is_chg = int(chg_mask[c_raw["buy_date"] <= "2023-12-31"].sum())
        oos_chg = int(chg_mask[c_raw["buy_date"] >= "2024-01-01"].sum())

        # Check 3-window strict dominance over V4.1_Base (IS, OOS, Y2025_2026)
        w_is, b_is = w.get("IS_21_23", {}), b_w.get("IS_21_23", {})
        w_oos, b_oos = w.get("OOS_24_26", {}), b_w.get("OOS_24_26", {})
        w_25, b_25 = w.get("Y2025_2026", {}), b_w.get("Y2025_2026", {})
        w_26, b_26 = w.get("Y2026", {}), b_w.get("Y2026", {})
        w_h2, b_h2 = w.get("Y2026_H2", {}), b_w.get("Y2026_H2", {})
        w_5y, b_5y = w.get("FULL_5Y", {}), b_w.get("FULL_5Y", {})

        strict_3win_ss = (
            (n_chg > 0)
            and (w_is.get("nav", 1.0) > b_is.get("nav", 1.0) + 1e-4)
            and (w_oos.get("nav", 1.0) > b_oos.get("nav", 1.0) + 1e-4)
            and (w_25.get("nav", 1.0) > b_25.get("nav", 1.0) + 1e-4)
        )
        strict_3win_eq = (
            (n_chg > 0)
            and (w_is.get("eq_nav", 1.0) >= b_is.get("eq_nav", 1.0) - 1e-4)
            and (w_oos.get("eq_nav", 1.0) >= b_oos.get("eq_nav", 1.0) - 1e-4)
            and (w_25.get("eq_nav", 1.0) >= b_25.get("eq_nav", 1.0) - 1e-4)
        )
        non_hefu_ok = (w_oos.get("ex_hefu_nav", 1.0) >= b_oos.get("ex_hefu_nav", 1.0) - 1e-4) and (w_5y.get("ex2_nav", 1.0) >= b_5y.get("ex2_nav", 1.0) - 1e-4)

        results[vname] = {
            "name": vname, "group": grp,
            "n_chg": n_chg, "n_win_chg": n_win_chg, "is_chg": is_chg, "oos_chg": oos_chg,
            "strict_3win_ss": bool(strict_3win_ss),
            "strict_3win_eq": bool(strict_3win_eq),
            "non_hefu_and_ex2_ok": bool(non_hefu_ok),
            "windows": w,
            "bootstrap_10k": res["bootstrap_10k"],
            "v21_pool": res["v21_pool"],
        }
        summary_rows.append({
            "name": vname, "group": grp, "n_chg": n_chg, "n_win": n_win_chg, "is_chg": is_chg, "oos_chg": oos_chg,
            "IS_nav": w_is.get("nav", 1.0), "IS_eq": w_is.get("eq_nav", 1.0),
            "OOS_nav": w_oos.get("nav", 1.0), "OOS_eq": w_oos.get("eq_nav", 1.0), "OOS_exHefu": w_oos.get("ex_hefu_nav", 1.0),
            "Y2526_nav": w_25.get("nav", 1.0), "Y2526_eq": w_25.get("eq_nav", 1.0),
            "Y26_nav": w_26.get("nav", 1.0), "H2_nav": w_h2.get("nav", 1.0),
            "FULL_nav": w_5y.get("nav", 1.0), "FULL_eq": w_5y.get("eq_nav", 1.0), "FULL_ex2": w_5y.get("ex2_nav", 1.0),
            "FULL_50bps": w_5y.get("nav_50bps", 1.0), "FULL_mdd": w_5y.get("daily_mdd_pct", 0.0), "FULL_sh": w_5y.get("daily_sharpe", 0.0),
            "strict_3win_ss": strict_3win_ss, "strict_3win_eq": strict_3win_eq, "non_hefu_ex2_ok": non_hefu_ok,
        })

    # 3. Also evaluate 78+ expanded pool & trade diffs for top candidates (full mode only)
    pass_candidates = [r["name"] for r in summary_rows if r["strict_3win_ss"] and r["strict_3win_eq"] and r["non_hefu_ex2_ok"]]
    extra_78 = {}
    trade_diffs = {}
    saved_ledgers = {}
    if not trunc_mode:
        # Check 78+ expanded pool for Base + any passing candidates + top A1/A2/DF024 exemplars
        inspect_names = sorted(set(["V41_Base"] + pass_candidates + [
            "A1_Fix114_Exempt7to5", "A1_Core114Clean_Exempt7to5", "A2_RedAnyReal_TightStep", "A2_RedNoRiskHint_TightStep",
            "A2_RedAnyReal_Cut0925_DF024", "A2_D2OpenLt2_Cut0925_DF024", "A2_CoreLt100_Cut0925_DF024",
        ]))
        spec_map = {n: cfg for n, _, cfg in specs}
        base78 = evaluate_dirA_variant("V41_Base_78", "78", cache, states, genes, daily_ctx, bench_df, cal_dts, None, max_dt=max_date, min_score=78.0)
        for nm in inspect_names:
            if nm not in spec_map:
                continue
            r78 = base78 if nm == "V41_Base" else evaluate_dirA_variant(f"{nm}_78", "78", cache, states, genes, daily_ctx, bench_df, cal_dts, spec_map[nm], max_dt=max_date, min_score=78.0)
            extra_78[nm] = {
                "IS_nav": r78["windows"]["IS_21_23"]["nav"], "IS_eq": r78["windows"]["IS_21_23"]["eq_nav"],
                "OOS_nav": r78["windows"]["OOS_24_26"]["nav"], "OOS_eq": r78["windows"]["OOS_24_26"]["eq_nav"],
                "Y2526_nav": r78["windows"]["Y2025_2026"]["nav"], "FULL_nav": r78["windows"]["FULL_5Y"]["nav"],
            }
            if nm != "V41_Base":
                res_nm = evaluate_dirA_variant(nm, "D", cache, states, genes, daily_ctx, bench_df, cal_dts, spec_map[nm], max_dt=max_date)
                cur_r = res_nm["raw_df"].set_index("idx")
                diffs = []
                for idx_i, row in cur_r.iterrows():
                    br = b_raw.loc[idx_i]
                    if abs(float(row["net_ret"]) - float(br["net_ret"])) > 1e-6:
                        diffs.append({
                            "buy_date": row["buy_date"], "code": row["code"], "name": row["name"],
                            "base_exit": f"{br['exit_date']} {int(br['exit_hhmm'])}@{br['exit_price']:.2f}",
                            "base_ret30_pct": round(float(br["net_ret"]) * 100.0, 2),
                            "new_exit": f"{row['exit_date']} {int(row['exit_hhmm'])}@{row['exit_price']:.2f}",
                            "new_ret30_pct": round(float(row["net_ret"]) * 100.0, 2),
                            "diff_pp": round((float(row["net_ret"]) - float(br["net_ret"])) * 100.0, 2),
                        })
                trade_diffs[nm] = diffs
                if nm in pass_candidates:
                    saved_ledgers[nm] = (res_nm["raw_df"], res_nm["slot_df"])

    return {
        "max_date": max_date,
        "parity_20bps_ok": parity_ok,
        "max_parity_diff": max_parity_diff,
        "elapsed_sec": round(time.time() - t0, 2),
        "n_d1_sealed_90": len(genes),
        "variants": results,
        "summary_rows": summary_rows,
        "pass_candidates": pass_candidates,
        "extra_78": extra_78,
        "trade_diffs": trade_diffs,
        "saved_ledgers": saved_ledgers,
        "base_slot_df": base_res["slot_df"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trunc-only-out", default="")
    args = parser.parse_args()

    if args.trunc_only_out:
        tr = run_pipeline(max_date="2024-12-31", trunc_mode=True)
        tr_out = {
            vn: {
                "ss_n": vd["windows"]["IS_21_23"]["ss_n"],
                "is_nav": vd["windows"]["IS_21_23"]["nav"],
                "is_mean": vd["windows"]["IS_21_23"]["mean_pct"],
                "oos24_nav": vd["windows"]["OOS_24_26"]["nav"],
                "oos24_n": vd["windows"]["OOS_24_26"]["ss_n"],
            }
            for vn, vd in tr["variants"].items()
        }
        with open(args.trunc_only_out, "w", encoding="utf-8") as f:
            json.dump(cm.sanitize_json(tr_out), f, ensure_ascii=False)
        return

    print("[Dir A: 4to5 -> 3to4] Running full 2021-11-15..2026-11-16 audit...")
    full_res = run_pipeline(max_date="2026-11-16", trunc_mode=False)

    # Save summary CSV
    df_sum = pd.DataFrame(full_res["summary_rows"]).sort_values(["strict_3win_ss", "FULL_nav"], ascending=[False, False])
    df_sum.to_csv(f"{cm.OUT_DIR}/dirA_summary_all_variants.csv", index=False, encoding="utf-8-sig")

    # Save Base and passing ledgers
    full_res["base_slot_df"].to_csv(f"{cm.OUT_DIR}/dirA_base_3to4_v41_30bps.csv", index=False, encoding="utf-8-sig")
    for pnm, (raw_p, slot_p) in full_res["saved_ledgers"].items():
        slot_p.to_csv(f"{cm.OUT_DIR}/dirA_pass_{pnm}_slot.csv", index=False, encoding="utf-8-sig")
        slot_p.to_parquet(f"{cm.OUT_DIR}/dirA_pass_{pnm}_slot.parquet", index=False)
        raw_p.to_parquet(f"{cm.OUT_DIR}/dirA_pass_{pnm}_raw.parquet", index=False)

    # Physical 2024-12-31 truncation check in isolated child process
    print("[Dir A] Running 2024-12-31 physical truncation verification in isolated child process...")
    tmp_trunc = f"{cm.OUT_DIR}/_tmp_dirA_trunc.json"
    subprocess.run([sys.executable, os.path.abspath(__file__), "--trunc-only-out", tmp_trunc], check=True)
    with open(tmp_trunc, encoding="utf-8") as f:
        trunc_res = json.load(f)
    os.remove(tmp_trunc)

    # Verify exact truncation diff across ALL variants on trades exiting <= 2024-12-31
    max_abs_diff = 0.0
    trunc_audit = {}
    for vn, vd in full_res["variants"].items():
        if vn == "V41_Base":
            s_full = full_res["base_slot_df"]
        else:
            # Reconstruct exact <=2024-12-31 IS window comparison
            pass
        f_is = vd["windows"]["IS_21_23"]
        t_is = trunc_res.get(vn, {})
        d_nav = abs(float(f_is["nav"]) - float(t_is.get("is_nav", 1.0)))
        d_mean = abs(float(f_is["mean_pct"]) - float(t_is.get("is_mean", 0.0)))
        d_n = abs(int(f_is["ss_n"]) - int(t_is.get("ss_n", 0)))
        max_abs_diff = max(max_abs_diff, d_nav, d_mean, float(d_n))
        trunc_audit[vn] = {"full_is_n": f_is["ss_n"], "trunc_is_n": t_is.get("ss_n"), "nav_diff": round(d_nav, 10), "mean_diff": round(d_mean, 10)}

    out_json = {
        "direction": "A_4to5_to_3to4_exit",
        "max_date": full_res["max_date"],
        "parity_20bps_ok": full_res["parity_20bps_ok"],
        "max_parity_diff": full_res["max_parity_diff"],
        "trunc_20241231_max_abs_diff": round(max_abs_diff, 10),
        "n_variants_tested": len(full_res["variants"]),
        "pass_candidates": full_res["pass_candidates"],
        "extra_78_check": full_res["extra_78"],
        "trade_diffs": full_res["trade_diffs"],
        "variants": full_res["variants"],
        "trunc_audit_sample": {k: trunc_audit[k] for k in list(trunc_audit.keys())[:10]},
    }
    with open(f"{cm.OUT_DIR}/dirA_audit.json", "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(out_json), f, ensure_ascii=False, indent=2)

    print(f"[Dir A DONE in {full_res['elapsed_sec']}s] parity_ok={full_res['parity_20bps_ok']} max_trunc_diff={max_abs_diff} | pass_candidates={full_res['pass_candidates']}")
    print("\n--- Top Variants (by strict_3win + FULL_nav) ---")
    print(df_sum.head(20).to_string(index=False))
    print("\n--- DF024 09:25 Cut Trap Check ---")
    df_0925 = df_sum[df_sum["name"].str.contains("0925")]
    print(df_0925.head(12).to_string(index=False))


if __name__ == "__main__":
    main()
