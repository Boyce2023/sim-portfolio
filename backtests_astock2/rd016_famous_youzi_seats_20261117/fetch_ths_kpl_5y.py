#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Fetch 5Y PIT 10jqka Youzi labels (all 1422 days) + Kaipanla stratified sample cross-check."""

import concurrent.futures
import json
import os
import time
import urllib.request
import pandas as pd

SANDBOX = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd016_famous_youzi_seats_20261117"
LHB_BUY_PQ = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet"
CACHE_10JQKA = f"{SANDBOX}/ths_raw_cache.jsonl"
OUT_THS_PQ = f"{SANDBOX}/ths_pit_youzi_5y.parquet"
OUT_KPL_PQ = f"{SANDBOX}/kpl_sample_crosscheck.parquet"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def fetch_10jqka_day(dt: str, retries: int = 3) -> dict:
    url = f"https://eq.10jqka.com.cn/lhbclient/data/method/indexData/date/{dt}/"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with opener.open(req, timeout=12) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
            if str(obj.get("status_code")) == "0" and isinstance(obj.get("data"), dict):
                return {"date": dt, "ok": True, "data": obj["data"]}
            return {"date": dt, "ok": False, "err": f"status={obj.get('status_code')}"}
        except Exception as e:
            if i == retries - 1:
                return {"date": dt, "ok": False, "err": str(e)}
            time.sleep(0.4 * (i + 1))
    return {"date": dt, "ok": False, "err": "unknown"}


def fetch_kpl_day(dt: str, retries: int = 2) -> dict:
    url = (
        f"https://applhb.kaipanla.com/w1/api/index.php?"
        f"PhoneOSNew=2&UserID=0&VerSion=6.2.30.2&apiv=w47&c=LongHuBang&a=GetStockList&Time={dt}&Type=0"
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with opener.open(req, timeout=12) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
            if str(obj.get("errcode")) == "0":
                return {"date": dt, "ok": True, "list": obj.get("list", [])}
        except Exception as e:
            if i == retries - 1:
                return {"date": dt, "ok": False, "err": str(e)}
            time.sleep(0.4 * (i + 1))
    return {"date": dt, "ok": False, "err": "unknown"}


def main():
    t0 = time.time()
    lhb = pd.read_parquet(LHB_BUY_PQ, columns=["TRADE_DATE"])
    all_dates = sorted(lhb["TRADE_DATE"].astype(str).str[:10].unique().tolist())
    print(f"Total trading dates: {len(all_dates)} ({all_dates[0]} ~ {all_dates[-1]})")

    done = {}
    if os.path.exists(CACHE_10JQKA):
        with open(CACHE_10JQKA, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    if rec.get("ok"):
                        done[rec["date"]] = rec
    todo = [d for d in all_dates if d not in done]
    print(f"Cached 10jqka days: {len(done)}, todo: {len(todo)}")

    if todo:
        with open(CACHE_10JQKA, "a", encoding="utf-8") as fw:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
                futs = {ex.submit(fetch_10jqka_day, d): d for d in todo}
                n_ok, n_fail = 0, 0
                for fut in concurrent.futures.as_completed(futs):
                    res = fut.result()
                    if res.get("ok"):
                        done[res["date"]] = res
                        fw.write(json.dumps(res, ensure_ascii=False) + "\n")
                        n_ok += 1
                    else:
                        n_fail += 1
                        print(f"FAIL 10jqka {res['date']}: {res.get('err')}")
        print(f"Fetched 10jqka ok={n_ok}, fail={n_fail}, elapsed={time.time()-t0:.1f}s")

    # Build normalized parquet from done
    rows = []
    for dt in sorted(done.keys()):
        d = done[dt]["data"]
        cap_map = {}
        for item in d.get("capital", {}).get("list", []):
            key = (str(item.get("stockCode", "")), int(item.get("isThree", 0)))
            cap_map[key] = item
        org_map = {}
        for item in d.get("org", {}).get("list", []):
            key = (str(item.get("stockCode", "")), int(item.get("isThree", 0)))
            org_map[key] = item

        seen_keys = set()
        for item in d.get("all", {}).get("list", []):
            code = str(item.get("stockCode", "")).zfill(6)
            is_three = int(item.get("isThree", 0))
            key = (code, is_three)
            seen_keys.add(key)
            c_it = cap_map.get(key, {})
            o_it = org_map.get(key, {})
            cap_icons = item.get("capitalIcon") or c_it.get("capitalIcon") or []
            dept_icons = item.get("departmentIcon") or c_it.get("departmentIcon") or []
            rows.append({
                "date": dt,
                "stock_code": code,
                "stock_name": str(item.get("stockName", "")),
                "rise": float(item.get("rise") or 0.0),
                "market_id": str(item.get("marketId", "")),
                "is_three": is_three,
                "reason_list": str(item.get("reasonList", "")),
                "all_inflow": float(item.get("inflow") or 0.0),
                "cap_inflow": float(c_it["inflow"]) if "inflow" in c_it and c_it["inflow"] is not None else None,
                "cap_count": int(c_it.get("count") or 0) if c_it else 0,
                "org_inflow": float(o_it["inflow"]) if "inflow" in o_it and o_it["inflow"] is not None else None,
                "org_count": int(o_it.get("count") or 0) if o_it else 0,
                "capital_icons_json": json.dumps(cap_icons, ensure_ascii=False),
                "capital_icons_str": "|".join(cap_icons),
                "n_capital_icons": len(cap_icons),
                "dept_icons_str": "|".join(dept_icons),
            })
        # Check if cap_map/org_map had keys missing from all_list
        for src_name, m in [("cap", cap_map), ("org", org_map)]:
            for key in m:
                if key not in seen_keys:
                    print(f"WARN {dt} {key} in {src_name} not in all")

    df_ths = pd.DataFrame(rows)
    df_ths.to_parquet(OUT_THS_PQ, index=False)
    print(f"Saved {OUT_THS_PQ}: rows={len(df_ths)}, days={df_ths['date'].nunique()}")

    # Stratified Kaipanla sample (~120 days: ~2 per month across 2021-2026 + last 10 days)
    sample_dates = sorted(set(all_dates[::13] + all_dates[-10:]))
    kpl_rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(fetch_kpl_day, sample_dates):
            if res.get("ok"):
                for it in res["list"]:
                    kpl_rows.append({
                        "date": res["date"],
                        "stock_code": str(it.get("ID", "")).zfill(6),
                        "stock_name": str(it.get("Name", "")),
                        "inc_pct_str": str(it.get("IncreaseAmount", "")),
                        "d3": int(it.get("D3") or 0),
                        "buy_in": float(it.get("BuyIn") or 0.0),
                        "join_num": int(it.get("JoinNum") or 0),
                        "turnover": float(it.get("Turnover") or 0.0),
                        "circ_price": float(it.get("CircPrice") or 0.0),
                        "turnover_ratio": float(it.get("TurnoverRatio") or 0.0),
                    })
    df_kpl = pd.DataFrame(kpl_rows)
    df_kpl.to_parquet(OUT_KPL_PQ, index=False)
    print(f"Saved {OUT_KPL_PQ}: rows={len(df_kpl)}, days={df_kpl['date'].nunique()}, total_elapsed={time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
