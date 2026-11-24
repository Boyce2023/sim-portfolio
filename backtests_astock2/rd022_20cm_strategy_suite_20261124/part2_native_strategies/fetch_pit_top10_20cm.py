#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch 100% PIT Top-10 Freeholders (Eastmoney RPT_F10_EH_FREEHOLDERS) for all 20cm (30/688/689) tickers."""
import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_JSON = f"{OUT_DIR}/pit_top10_20cm_summary.json"
os.makedirs(OUT_DIR, exist_ok=True)


def fetch_batch(codes):
    q = ",".join(f'"{c}"' for c in codes)
    flt = urllib.parse.quote(f"(SECURITY_CODE in ({q}))(END_DATE>='2020-06-30')")
    out = []
    page = 1
    while page <= 15:
        url = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get?"
            "reportName=RPT_F10_EH_FREEHOLDERS&columns=SECURITY_CODE,END_DATE,NOTICE_DATE,HOLDER_RANK,FREE_HOLDNUM_RATIO"
            f"&filter={flt}&pageSize=500&pageNumber={page}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
            js = json.loads(raw)
            res = js.get("result") or {}
            rows = res.get("data") or []
            out.extend(rows)
            pages = int(res.get("pages") or 1)
            if page >= pages or not rows:
                break
            page += 1
        except Exception:
            break
    return out


def main():
    t0 = time.time()
    a1 = pd.read_parquet(f"{BASE}/data/cn_hk_price_db/a_daily.parquet", columns=["ticker"])
    a2 = pd.read_parquet(f"{BASE}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=["ticker"])
    all_tks = pd.concat([a1["ticker"], a2["ticker"]], ignore_index=True).unique()
    codes_20 = sorted({t[:6] for t in all_tks if str(t).startswith(("30", "688", "689"))})
    print(f"[*] Total 20cm codes: {len(codes_20)}")

    base_idx = {}
    if os.path.exists(OUT_JSON):
        base_idx = json.load(open(OUT_JSON, "r", encoding="utf-8"))
    todo = [c for c in codes_20 if c not in base_idx]
    print(f"[*] Existing: {len(base_idx)}, fetching: {len(todo)}")

    if todo:
        batches = [todo[i:i + 15] for i in range(0, len(todo), 15)]
        by_code = {}
        with ThreadPoolExecutor(max_workers=16) as ex:
            futs = [ex.submit(fetch_batch, b) for b in batches]
            for f in as_completed(futs):
                for it in f.result():
                    c = str(it.get("SECURITY_CODE") or "")[:6]
                    nd = str(it.get("NOTICE_DATE") or "")[:10]
                    ed = str(it.get("END_DATE") or "")[:10]
                    rt = float(it.get("FREE_HOLDNUM_RATIO") or 0.0)
                    if c and nd and ed and rt > 0:
                        rec = by_code.setdefault(c, {}).setdefault(ed, [nd, 0.0, 0.0])
                        rec[0] = min(rec[0], nd)
                        rec[1] += rt
                        if rt >= 5.0:
                            rec[2] += rt
        for c, ed_map in by_code.items():
            base_idx[c] = sorted(
                [[v[0], ed, round(min(95.0, v[1]), 2), round(min(95.0, v[2]), 2)] for ed, v in ed_map.items()]
            )

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(base_idx, f, ensure_ascii=False)
    print(f"[+] Saved {len(base_idx)} 20cm PIT top10 series to {OUT_JSON} in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
