#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Fetch ONLY missing 5m bars needed for exit evaluation on score_v2 >= 86 (and all >=90):
- For sealed_3b == False: only D4 (or up to D6 if D4/D5 is zt/yizi_dt), plus D3..ed_v2+3
- For sealed_3b == True: D4..min(ed_v2+5, buy_date+18)
Saves strictly inside s2_2to3_exit/_cache_5m_supplement_bs.pkl.
"""
import os, sys, time, pickle
import numpy as np
import pandas as pd
import baostock as bs

assert "yfinance" not in sys.modules
bs.common.contants.BAOSTOCK_SERVER_IP = "114.94.20.42"

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_opt_20261118/s2_2to3_exit"
CACHE_IN = f"{OUT_DIR}/_cache_2to3_pit_20261116.pkl"
SUPP_OUT = f"{OUT_DIR}/_cache_5m_supplement_bs.pkl"

def main():
    t0 = time.time()
    d = pickle.load(open(CACHE_IN, "rb"))
    g = d["gated_all"]
    b5m = d["b5m_need"]
    da = d["da_need"]
    all_dts = d["all_dts"]
    dt_idx = {x: i for i, x in enumerate(all_dts)}

    pl_zt = {(r.c6, r.dt): (bool(r.is_zt), bool(r.is_yizi_dt), bool(r.is_dt_exact)) for r in da.itertuples(index=False)}
    sub = g[g["score_v2"] >= 86].copy()

    # Check qfq_factor invariance on ACTUAL hold period (buy_date .. ed_v2 + 3)
    qfq_map = {(r.c6, r.dt): float(r.qfq_factor) for r in da.itertuples(index=False) if pd.notna(r.qfq_factor)}
    qfq_changes = []
    queries = []
    miss_total = 0
    for r in sub.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        p0 = dt_idx.get(str(r.buy_date), -1)
        if p0 < 0:
            continue
        p_end = dt_idx.get(str(r.ed_v2), p0 + 1)
        # If sealed_3b or D4 reversed ZT, fetch up to p_end + 4 (max p0+18); else D4..max(p_end+1, p0+2)
        end_k = min(len(all_dts) - 1, max(p_end + 4, p0 + 12) if (r.sealed_3b or (p_end > p0 + 1)) else (p0 + 2))
        q0 = qfq_map.get((c6, str(r.buy_date)))
        for k in range(p0 + 1, p_end + 1):
            qk = qfq_map.get((c6, all_dts[k]))
            if q0 and qk and abs(qk / q0 - 1.0) > 1e-4:
                qfq_changes.append((str(r.buy_date), c6, str(r.name), all_dts[k], q0, qk))

        missing_dts = []
        for k in range(p0 + 1, end_k + 1):
            dk = all_dts[k]
            arr = b5m.get((c6, dk))
            if arr is None or len(arr) < 12:
                missing_dts.append(dk)
        if missing_dts:
            miss_total += len(missing_dts)
            queries.append((c6, missing_dts[0], missing_dts[-1], set(missing_dts)))

    print(f"Signals >=86: {len(sub)}, hold qfq_changes={len(qfq_changes)}, missing_days={miss_total} in {len(queries)} queries", flush=True)
    for qc in qfq_changes:
        print("  HOLD_QFQ_CHG:", qc, flush=True)

    bs.login()
    supp = {}
    failed_pairs = []
    for idx, (c6, d_s, d_e, target_dts) in enumerate(queries, 1):
        bs_code = f"sh.{c6}" if c6.startswith(("60", "68")) else f"sz.{c6}"
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,time,open,high,low,close,volume,amount",
            start_date=d_s,
            end_date=d_e,
            frequency="5",
            adjustflag="3",
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        got_dts = set()
        if rows:
            df_r = pd.DataFrame(rows, columns=["date", "time", "open", "high", "low", "close", "volume", "amount"])
            df_r["hhmm_int"] = df_r["time"].str[8:12].astype(int)
            for col in ["open", "high", "low", "close", "volume", "amount"]:
                df_r[col] = pd.to_numeric(df_r[col], errors="coerce").fillna(0.0)
            for dt_k, grp in df_r.groupby("date"):
                if dt_k in target_dts and len(grp) >= 12:
                    grp = grp.sort_values("hhmm_int")
                    supp[(c6, dt_k)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
                    got_dts.add(dt_k)
        for dt_m in (target_dts - got_dts):
            failed_pairs.append((c6, dt_m))
        if idx % 25 == 0 or idx == len(queries):
            print(f"  progress {idx}/{len(queries)} | fetched_days={len(supp)} | elapsed={time.time()-t0:.1f}s", flush=True)
    bs.logout()

    da_close = {(r.c6, r.dt): float(r.close) for r in da.itertuples(index=False)}
    max_diff = 0.0
    mismatch_cnt = 0
    for (c6, dt_k), arr in supp.items():
        dc = da_close.get((c6, dt_k))
        if dc is not None:
            df_c = abs(arr[-1, 4] - dc)
            if df_c > 0.02:
                mismatch_cnt += 1
            if df_c > max_diff:
                max_diff = df_c

    with open(SUPP_OUT, "wb") as f:
        pickle.dump({"supp_5m": supp, "failed_pairs": failed_pairs, "qfq_changes": qfq_changes}, f)
    print(f"Done in {time.time()-t0:.1f}s! Fetched {len(supp)} days, failed={len(failed_pairs)}, max_close_diff={max_diff:.4f}, mismatch={mismatch_cnt}", flush=True)

if __name__ == "__main__":
    main()
