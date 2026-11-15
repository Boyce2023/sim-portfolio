#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四进五 5 分钟 K 线回补与落地模块 (<=150 行)"""
import os, sys, time, pickle, sqlite3, datetime as dt
from collections import defaultdict
from multiprocessing import Pool
import pandas as pd
import baostock as bs

CAND_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/cand_high_dragon.parquet"
BARS_PKL = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p2_4to5"
OUT_PARQUET = f"{OUT_DIR}/cand_4to5_5m_bars.parquet"

def collect_needed():
    df = pd.read_parquet(CAND_PATH)
    d4 = df[df["prev_streak"] == 4].copy()
    with open(BARS_PKL, "rb") as f: cb_map = pickle.load(f)["code_bars"]
    needed = set()
    for r in d4.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        if not c6.startswith(("00", "60")) or "ST" in str(r.name).upper() or not bool(r.buyable_open): continue
        cb = cb_map.get(c6)
        if cb is None: continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or cb["pre_c"][pos] <= 0 or (cb["zt_px"][pos] / cb["pre_c"][pos] < 1.085): continue
        n = len(cb["dts"])
        needed.add((c6, bd))
        k = pos + 1
        while k < n and bool(cb["is_zt"][k]): needed.add((c6, cb["dts"][k])); k += 1
        while k < n and bool(cb["is_yizi_dt"][k]): needed.add((c6, cb["dts"][k])); k += 1
        if k < n: needed.add((c6, cb["dts"][k]))
    return needed

def load_cached(needed):
    chunks, found = [], set()
    f_3to4 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet"
    if os.path.exists(f_3to4):
        d = pd.read_parquet(f_3to4)
        m = pd.MultiIndex.from_frame(d[["c6", "date"]]).isin(needed)
        sub = d[m][["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"]].copy()
        if not sub.empty: chunks.append(sub); found |= set(zip(sub["c6"], sub["date"]))
    f_v15 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cand_5m_bars_v15_complete.parquet"
    if os.path.exists(f_v15) and (needed - found):
        d = pd.read_parquet(f_v15)
        d["c6"] = d["c6"].astype(str).str.zfill(6)
        m = pd.MultiIndex.from_frame(d[["c6", "date"]]).isin(needed - found)
        sub = d[m][["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"]].copy()
        if not sub.empty: chunks.append(sub); found |= set(zip(sub["c6"], sub["date"]))
    f_db = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/firstboard_5m_5y_pit.db"
    rem = needed - found
    if os.path.exists(f_db) and rem:
        rem_codes = sorted({c for c, _ in rem})
        conn = sqlite3.connect(f"file:{f_db}?mode=ro", uri=True)
        qm = ",".join(["?"] * len(rem_codes))
        sql = f"SELECT sec_code, substr(bar_time,1,10) as dt, substr(bar_time,12,2)||substr(bar_time,15,2) as hhmm, open, high, low, close, volume, amount FROM firstboard_5m_bars WHERE sec_code IN ({qm})"
        df_db = pd.read_sql_query(sql, conn, params=rem_codes)
        conn.close()
        if not df_db.empty:
            df_db["c6"], df_db["date"] = df_db["sec_code"].astype(str).str.zfill(6), df_db["dt"].astype(str)
            m = pd.MultiIndex.from_frame(df_db[["c6", "date"]]).isin(rem)
            sub = df_db.loc[m, ["c6", "date", "hhmm", "open", "high", "low", "close", "volume", "amount"]].copy()
            if not sub.empty:
                sub["hhmm_int"] = pd.to_numeric(sub["hhmm"], errors="coerce").fillna(0).astype(int)
                chunks.append(sub[["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"]])
                found |= set(zip(sub["c6"], sub["date"]))
    return chunks, found

def _fetch_worker(args):
    wid, tasks = args
    bs.common.contants.BAOSTOCK_SERVER_IP = "114.94.20.42"
    lg = bs.login()
    if lg.error_code != "0": return []
    out = []
    for c6, w_start, w_end, tg_dts in tasks:
        bs_code = ("sh." if c6.startswith("6") else "sz.") + c6
        tset = set(tg_dts)
        for _ in range(3):
            try:
                rs = bs.query_history_k_data_plus(bs_code, "date,time,open,high,low,close,volume,amount", start_date=w_start, end_date=w_end, frequency="5", adjustflag="3")
                if rs.error_code == "0":
                    while rs.next():
                        r = rs.get_row_data()
                        if r[0] not in tset: continue
                        t_raw = str(r[1])
                        out.append((c6, r[0], int(t_raw[8:12]) if len(t_raw)>=12 else 0, float(r[2] or 0), float(r[3] or 0), float(r[4] or 0), float(r[5] or 0), float(r[6] or 0), float(r[7] or 0)))
                    break
                time.sleep(0.3); bs.login()
            except Exception:
                time.sleep(0.5)
                try: bs.login()
                except Exception: pass
    bs.logout()
    return out

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    needed = collect_needed()
    chunks, found = load_cached(needed)
    rem = needed - found
    print(f"[Prep] Needed: {len(needed)}, Cached: {len(found)}, Rem to fetch: {len(rem)}")
    if rem:
        by_code = defaultdict(list)
        for c6, d_str in sorted(rem): by_code[c6].append(d_str)
        windows = []
        for c6, d_list in sorted(by_code.items()):
            ws, we, tg = d_list[0], d_list[0], {d_list[0]}
            for d in d_list[1:]:
                if (dt.date.fromisoformat(d) - dt.date.fromisoformat(we)).days <= 14: we = d; tg.add(d)
                else: windows.append((c6, ws, we, sorted(tg))); ws = d; we = d; tg = {d}
            windows.append((c6, ws, we, sorted(tg)))
        n_w = 6
        tasks = [windows[i::n_w] for i in range(n_w)]
        with Pool(n_w) as p:
            res = p.map(_fetch_worker, [(i+1, tasks[i]) for i in range(n_w)])
        fetched = [row for sl in res for row in sl]
        if fetched:
            df_fet = pd.DataFrame(fetched, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"])
            chunks.append(df_fet)
            found |= set(zip(df_fet["c6"], df_fet["date"]))
    df_all = pd.concat(chunks, ignore_index=True).drop_duplicates(subset=["c6", "date", "hhmm_int"]).sort_values(["c6", "date", "hhmm_int"])
    df_all.to_parquet(OUT_PARQUET, index=False)
    print(f"[Done] Total saved {len(df_all)} bars for {len(found & needed)}/{len(needed)} needed pairs -> {OUT_PARQUET}")

if __name__ == "__main__":
    main()
