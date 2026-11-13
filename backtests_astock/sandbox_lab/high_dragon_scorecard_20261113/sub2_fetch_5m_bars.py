#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""sub2_fetch_5m_bars.py - 极速拉取 119 笔高标首阴在 D1 至 D2+10 的 5 分钟真实 K 线并落盘缓存"""

import os, time, pickle, pandas as pd
import baostock as bs

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
CACHE_PATH = f"{OUT_DIR}/sub2_5m_bars_cache.pkl"

part1_path = f"{OUT_DIR}/part1_cache.pkl"
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(part1_path, "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/dfr_deep_native.pkl")

# 读取既有缓存
cache = {}
if os.path.exists(CACHE_PATH):
    try:
        cache = pickle.load(open(CACHE_PATH, "rb"))
        print(f"Loaded existing cache with {len(cache)} entries.")
    except Exception as e:
        print(f"Failed to load cache: {e}")

lg = bs.login()
if lg.error_code != '0':
    raise RuntimeError(f"Baostock login failed: {lg.error_msg}")

t0 = time.time()
new_fetched = 0
try:
    for idx, r in enumerate(dfr.itertuples()):
        c6 = str(r.code).zfill(6)
        key = (c6, str(r.d1), str(r.buy_date))
        if key in cache and cache[key] is not None and len(cache[key]) > 0:
            continue
        
        prefix = "sh" if c6.startswith("6") else "sz"
        bs_code = f"{prefix}.{c6}"
        
        # 确定起始日期 D1 与 结束日期 (D2 + 10个交易日)
        start_dt = str(r.d1)
        bars = code_bars.get(c6)
        if bars and r.buy_date in bars["p"]:
            d2_p = bars["p"][r.buy_date]
            end_p = min(d2_p + 10, len(bars["dts"]) - 1)
            end_dt = bars["dts"][end_p]
        else:
            end_dt = (pd.to_datetime(r.buy_date) + pd.Timedelta(days=18)).strftime("%Y-%m-%d")
        
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,time,open,high,low,close,volume,amount",
            start_date=start_dt,
            end_date=end_dt,
            frequency="5"
        )
        
        rows = []
        while (rs.error_code == '0') and rs.next():
            rows.append(rs.get_row_data())
        
        if rows:
            df_k = pd.DataFrame(rows, columns=["date", "time", "open", "high", "low", "close", "volume", "amount"])
            # 格式转换
            df_k["open"] = df_k["open"].astype(float)
            df_k["high"] = df_k["high"].astype(float)
            df_k["low"] = df_k["low"].astype(float)
            df_k["close"] = df_k["close"].astype(float)
            df_k["volume"] = df_k["volume"].astype(float)
            df_k["amount"] = df_k["amount"].astype(float)
            # hhmm: time 格式为 '20220301093500000' -> '09:35'
            df_k["hhmm"] = df_k["time"].str[8:10] + ":" + df_k["time"].str[10:12]
            cache[key] = df_k
            new_fetched += 1
        else:
            print(f"Warning: No rows for {bs_code} {start_dt} to {end_dt}")
            cache[key] = None
        
        if (idx + 1) % 20 == 0:
            print(f"Progress: {idx + 1}/{len(dfr)} fetched (elapsed: {round(time.time() - t0, 1)}s)")
            # 增量落盘
            pickle.dump(cache, open(CACHE_PATH, "wb"))
finally:
    bs.logout()
    pickle.dump(cache, open(CACHE_PATH, "wb"))

print(f"Done! Total entries in cache: {len(cache)}, newly fetched: {new_fetched}, total time: {round(time.time() - t0, 1)}s")
