#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD049 Step 2: Cache Exact Official Historical Margin Eligibility (T-1 Closed Exchange Lists)
for ALL candidate trades across V20 & V21 6-strategy pools (SSE queryMargin.do + SZSE AKShare).
Zero yfinance (D12).
"""
import json
import os
import pickle
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import akshare as ak
import pandas as pd
import requests

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
CACHE_DIR = f"{RD049}/_cache"
sys.path.insert(0, RD038)
import _rd038_engine as eng


def main():
    t0 = time.time()
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    reg = pd.read_parquet(f"{CACHE_DIR}/rd049_daily_regime_pit.parquet")
    dts_all = sorted(reg["trade_date"].astype(str).str[:10].unique().tolist())
    prev_dt_map = {dts_all[i]: dts_all[i - 1] for i in range(1, len(dts_all))}

    cfg_v20 = {"s20": "base_76", "s34": "base", "s23": "base", "shi": "base", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}
    cfg_v21 = {"s20": "stack_c50_avg", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15", "shi": "m1_causal_cold_drop40_t0", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}
    p20, _ = eng.build_bundle_pools(cache, cfg_v20)
    p21, _ = eng.build_bundle_pools(cache, cfg_v21)
    all_cands = pd.concat([p20[["code", "buy_date"]], p21[["code", "buy_date"]]], ignore_index=True).drop_duplicates()
    all_cands["code"] = all_cands["code"].astype(str).str.zfill(6)
    all_cands["buy_date"] = all_cands["buy_date"].astype(str).str[:10]
    all_cands["prev_date"] = all_cands["buy_date"].map(prev_dt_map)

    sz_pairs = [(r.code, r.buy_date, r.prev_date) for r in all_cands.itertuples(index=False) if r.code.startswith(("00", "30"))]
    sh_pairs = [(r.code, r.buy_date, r.prev_date) for r in all_cands.itertuples(index=False) if r.code.startswith(("60", "68"))]
    sz_prev_dts = sorted({p for _, _, p in sz_pairs if p})
    sh_prev_dts = sorted({p for _, _, p in sh_pairs if p})
    print(f"Total unique pairs: {len(all_cands)} | SZ prev_dates: {len(sz_prev_dts)} ({len(sz_pairs)} pairs) | SH prev_dates: {len(sh_prev_dts)} ({len(sh_pairs)} pairs)")

    out_json = f"{CACHE_DIR}/rd049_margin_eligibility_cache.json"
    existing = {}
    if os.path.exists(out_json):
        existing = json.load(open(out_json, encoding="utf-8"))

    sz_date_sets = existing.get("sz_date_sets", {})
    sh_date_sets = existing.get("sh_date_sets", {})

    # 1. Fetch SZSE underlying sets by T-1 date
    todo_sz = [d for d in sz_prev_dts if d not in sz_date_sets]
    print(f"Fetching SZSE underlying lists for {len(todo_sz)} dates ...")
    def fetch_sz(dt):
        dt8 = dt.replace("-", "")
        df = ak.stock_margin_underlying_info_szse(date=dt8)
        if df is None or df.empty:
            return dt, []
        # 融资标的 == 'Y' or 当日可融资 == 'Y'
        m = (df["融资标的"].astype(str).str.upper() == "Y")
        return dt, sorted(df.loc[m, "证券代码"].astype(str).str.zfill(6).unique().tolist())

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(fetch_sz, d) for d in todo_sz]
        for f in as_completed(futs):
            try:
                dt, codes = f.result()
                sz_date_sets[dt] = codes
            except Exception as e:
                print("SZ err:", e)

    # 2. Fetch SSE full margin sets by T-1 date (only 2 pages per date!)
    todo_sh = [d for d in sh_prev_dts if d not in sh_date_sets]
    print(f"Fetching SSE margin lists for {len(todo_sh)} dates ...")
    url = "https://query.sse.com.cn/marketdata/tradedata/queryMargin.do"
    hdrs = {"Referer": "https://www.sse.com.cn/", "User-Agent": "Mozilla/5.0"}
    def fetch_sh(dt):
        dt8 = dt.replace("-", "")
        sess = requests.Session()
        codes = set()
        for pno in (1, 2):
            r = sess.get(url, params={
                "isPagination": "true", "tabType": "mxtype", "detailsDate": dt8,
                "stockCode": "", "pageHelp.pageSize": "2000", "pageHelp.pageNo": str(pno),
                "pageHelp.beginPage": str(pno), "pageHelp.endPage": str(pno + 5),
            }, headers=hdrs, timeout=12).json()
            res = r.get("result") or []
            for row in res:
                codes.add(str(row.get("stockCode", "")).zfill(6))
            if len(res) < 2000:
                break
        return dt, sorted(codes)

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(fetch_sh, d) for d in todo_sh]
        for f in as_completed(futs):
            try:
                dt, codes = f.result()
                sh_date_sets[dt] = codes
            except Exception as e:
                print("SH err:", e)

    # Map each (code, buy_date) -> True/False using T-1 closed list
    pair_elig = {}
    for r in all_cands.itertuples(index=False):
        c6 = r.code
        bd = r.buy_date
        pd_t1 = r.prev_date
        if c6.startswith(("00", "30")):
            s = set(sz_date_sets.get(pd_t1, []))
            elig = c6 in s if pd_t1 in sz_date_sets else None
        elif c6.startswith(("60", "68")):
            s = set(sh_date_sets.get(pd_t1, []))
            elig = c6 in s if pd_t1 in sh_date_sets else None
        else:
            elig = False
        pair_elig[f"{c6}|{bd}"] = elig

    n_ok = sum(1 for v in pair_elig.values() if v is True)
    n_no = sum(1 for v in pair_elig.values() if v is False)
    n_na = sum(1 for v in pair_elig.values() if v is None)
    print(f"Margin Cache Done in {time.time()-t0:.1f}s | Eligible={n_ok}, Non-Eligible={n_no}, Missing={n_na}")

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({
            "pair_elig": pair_elig,
            "sz_date_sets": sz_date_sets,
            "sh_date_sets": sh_date_sets,
        }, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
