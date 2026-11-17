#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三进四全样本（2022-01-04 至 2026-11-10 主板10cm非ST非一字可买）真实5分钟K线回补与落盘脚本
数据源优先级：
  1. 本地只读缓存复用：
     - sim-portfolio/data/cand_5m_bars_v15_complete.parquet
     - sim-portfolio/data/firstboard_5m_5y_pit.db (mode=ro)
     - sim-portfolio/backtests_astock2/data_5y/firstboard_5m_5y_pit.db (mode=ro)
  2. 缺失窗口从 Baostock 官方 5 分钟接口补齐（严禁 yfinance，严禁日线插值伪造）
输出：
  /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet
"""
import os
import sys
import time
import pickle
import sqlite3
import datetime as dt
from collections import defaultdict
from multiprocessing import Pool

import numpy as np
import pandas as pd
import baostock as bs

bs.common.contants.BAOSTOCK_SERVER_IP = "114.94.20.42"

CAND_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/cand_3to4.parquet"
BARS_PKL = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl"
V15_5M_PARQUET = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cand_5m_bars_v15_complete.parquet"
DB_5M_A = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/firstboard_5m_5y_pit.db"
DB_5M_B = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/data_5y/firstboard_5m_5y_pit.db"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/data_5y"
OUT_PARQUET = os.path.join(OUT_DIR, "cand_3to4_5m_bars.parquet")


def collect_needed_pairs():
    df = pd.read_parquet(CAND_PATH)
    with open(BARS_PKL, "rb") as f:
        cb_map = pickle.load(f)["code_bars"]

    needed_pairs = set()
    clean_cand_cnt = 0
    for r in df.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        bd = str(r.buy_date)
        if not c6.startswith(("00", "60")):
            continue
        if "ST" in str(r.name).upper():
            continue
        if bool(r.prev_is_yizi) or (not bool(r.buyable_open)):
            continue
        cb = cb_map.get(c6)
        if cb is None:
            continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0:
            continue
        pre_c = float(cb["pre_c"][pos])
        zt_px = float(cb["zt_px"][pos])
        if pre_c <= 0 or (zt_px / pre_c < 1.085):
            continue

        clean_cand_cnt += 1
        n = len(cb["dts"])
        needed_pairs.add((c6, bd))

        if not bool(cb["is_zt"][pos]):
            k = pos + 1
            while k < n and bool(cb["is_yizi_dt"][k]):
                needed_pairs.add((c6, cb["dts"][k]))
                k += 1
            if k < n:
                needed_pairs.add((c6, cb["dts"][k]))
        else:
            k = pos + 1
            while k < n and bool(cb["is_zt"][k]):
                needed_pairs.add((c6, cb["dts"][k]))
                k += 1
            while k < n and bool(cb["is_yizi_dt"][k]):
                needed_pairs.add((c6, cb["dts"][k]))
                k += 1
            if k < n:
                needed_pairs.add((c6, cb["dts"][k]))

    return needed_pairs, clean_cand_cnt


def load_local_cached_bars(needed_pairs):
    chunks = []
    found_pairs = set()

    if os.path.exists(OUT_PARQUET):
        df_old = pd.read_parquet(OUT_PARQUET)
        if not df_old.empty:
            chunks.append(df_old[["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"]])
            found_pairs |= set(zip(df_old["c6"], df_old["date"]))
            print(f"[Cache] Existing OUT_PARQUET matched {len(found_pairs & needed_pairs)} pairs")

    if os.path.exists(V15_5M_PARQUET):
        df_v15 = pd.read_parquet(V15_5M_PARQUET, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"])
        df_v15["c6"] = df_v15["c6"].astype(str).str.zfill(6)
        mask = pd.MultiIndex.from_frame(df_v15[["c6", "date"]]).isin(needed_pairs - found_pairs)
        sub = df_v15[mask].copy()
        if not sub.empty:
            chunks.append(sub)
            found_pairs |= set(zip(sub["c6"], sub["date"]))
            print(f"[Cache] After V15_5M_PARQUET: {len(found_pairs & needed_pairs)} pairs")

    for db_path, tbl in [(DB_5M_A, "firstboard_5m_bars"), (DB_5M_B, "firstboard_5m_kline")]:
        rem = needed_pairs - found_pairs
        if not rem or not os.path.exists(db_path):
            continue
        rem_codes = sorted({c for c, _ in rem})
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        q_marks = ",".join(["?"] * len(rem_codes))
        sql = f"SELECT sec_code, substr(bar_time,1,10) as dt, substr(bar_time,12,2)||substr(bar_time,15,2) as hhmm, open, high, low, close, volume, amount FROM {tbl} WHERE sec_code IN ({q_marks})"
        df_db = pd.read_sql_query(sql, conn, params=rem_codes)
        conn.close()
        if not df_db.empty:
            df_db["c6"] = df_db["sec_code"].astype(str).str.zfill(6)
            df_db["date"] = df_db["dt"].astype(str)
            mask = pd.MultiIndex.from_frame(df_db[["c6", "date"]]).isin(rem)
            sub = df_db.loc[mask, ["c6", "date", "hhmm", "open", "high", "low", "close", "volume", "amount"]].copy()
            if not sub.empty:
                sub["hhmm_int"] = pd.to_numeric(sub["hhmm"], errors="coerce").fillna(0).astype(int)
                chunks.append(sub[["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"]])
                found_pairs |= set(zip(sub["c6"], sub["date"]))
                print(f"[Cache] After {os.path.basename(db_path)} ({tbl}): {len(found_pairs & needed_pairs)} pairs")

    return chunks, found_pairs


def build_merged_windows(missing_pairs, max_gap_days=14):
    by_code = defaultdict(list)
    for c6, d_str in sorted(missing_pairs):
        by_code[c6].append(d_str)

    windows = []
    for c6, d_list in sorted(by_code.items()):
        w_start = d_list[0]
        w_end = d_list[0]
        target_set = {d_list[0]}
        for d_cur in d_list[1:]:
            gap = (dt.date.fromisoformat(d_cur) - dt.date.fromisoformat(w_end)).days
            if gap <= max_gap_days:
                w_end = d_cur
                target_set.add(d_cur)
            else:
                windows.append((c6, w_start, w_end, sorted(target_set)))
                w_start = d_cur
                w_end = d_cur
                target_set = {d_cur}
        windows.append((c6, w_start, w_end, sorted(target_set)))
    return windows


def _worker_fetch(args):
    worker_id, task_slice = args
    bs.common.contants.BAOSTOCK_SERVER_IP = "114.94.20.42"
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"Worker {worker_id} Baostock login failed: {lg.error_msg}")

    out_rows = []
    t0 = time.time()
    for idx, (c6, w_start, w_end, target_dts) in enumerate(task_slice, 1):
        bs_code = ("sh." if c6.startswith("6") else "sz.") + c6
        target_set = set(target_dts)
        ok = False
        for attempt in range(3):
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,time,open,high,low,close,volume,amount",
                    start_date=w_start,
                    end_date=w_end,
                    frequency="5",
                    adjustflag="3",
                )
                if rs.error_code == "0":
                    while rs.next():
                        row = rs.get_row_data()
                        r_dt = row[0]
                        if r_dt not in target_set:
                            continue
                        t_raw = str(row[1])
                        hhmm_int = int(t_raw[8:12]) if len(t_raw) >= 12 else 0
                        out_rows.append((
                            c6,
                            r_dt,
                            hhmm_int,
                            float(row[2] or 0.0),
                            float(row[3] or 0.0),
                            float(row[4] or 0.0),
                            float(row[5] or 0.0),
                            float(row[6] or 0.0),
                            float(row[7] or 0.0),
                        ))
                    ok = True
                    break
                else:
                    time.sleep(0.3 * (attempt + 1))
                    bs.login()
            except Exception:
                time.sleep(0.5 * (attempt + 1))
                try:
                    bs.login()
                except Exception:
                    pass
        if idx % 150 == 0 or idx == len(task_slice):
            el = time.time() - t0
            print(f"[Worker {worker_id}] {idx}/{len(task_slice)} windows ({idx/max(el,0.1):.1f} win/s), rows={len(out_rows)}", flush=True)

    bs.logout()
    return out_rows


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    needed_pairs, clean_cnt = collect_needed_pairs()
    print(f"[Init] Clean 10cm non-ST 3to4 candidates: {clean_cnt}, total needed (c6, date) pairs: {len(needed_pairs)}")

    chunks, found_pairs = load_local_cached_bars(needed_pairs)
    missing_pairs = needed_pairs - found_pairs
    print(f"[Init] Missing (c6, date) pairs to fetch from Baostock: {len(missing_pairs)}")

    if missing_pairs:
        windows = build_merged_windows(missing_pairs, max_gap_days=14)
        print(f"[Fetch] Merged into {len(windows)} contiguous range queries across 2 polite workers...")
        n_workers = 2
        slices = [windows[i::n_workers] for i in range(n_workers)]
        t0 = time.time()
        with Pool(processes=n_workers) as pool:
            res_lists = pool.map(_worker_fetch, [(i, slices[i]) for i in range(n_workers)])
        all_new = [r for sub in res_lists for r in sub]
        print(f"[Fetch] Pulled {len(all_new)} 5-minute bars in {time.time()-t0:.1f}s")
        if all_new:
            df_new = pd.DataFrame(
                all_new,
                columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
            )
            chunks.append(df_new)

    if not chunks:
        raise RuntimeError("No 5m bars collected!")

    df_all = pd.concat(chunks, ignore_index=True)
    df_all.drop_duplicates(subset=["c6", "date", "hhmm_int"], keep="last", inplace=True)
    df_all.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    df_all.reset_index(drop=True, inplace=True)
    df_all.to_parquet(OUT_PARQUET, index=False)

    final_pairs = set(zip(df_all["c6"], df_all["date"]))
    cov = len(final_pairs & needed_pairs) / max(len(needed_pairs), 1) * 100.0
    still_missing = sorted(needed_pairs - final_pairs)
    print(f"[Done] Saved {len(df_all):,} 5m bars to {OUT_PARQUET}")
    print(f"[Done] Coverage: {len(final_pairs & needed_pairs)}/{len(needed_pairs)} ({cov:.2f}%), still_missing={len(still_missing)}")
    if still_missing[:10]:
        print(f"[Done] Sample missing (e.g. full-day suspension): {still_missing[:10]}")


if __name__ == "__main__":
    main()
