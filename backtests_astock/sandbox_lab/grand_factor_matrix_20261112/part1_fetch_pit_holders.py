#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Backfill 100% PIT Top-10 Freeholders (Eastmoney RPT_F10_EH_FREEHOLDERS) for all 2022-2026 multi-board & pry stocks."""
import os, json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
SANDBOX = f"{BASE}/backtests_astock/sandbox_lab"
OUT_DIR = f"{SANDBOX}/grand_factor_matrix_20261112"
os.makedirs(OUT_DIR, exist_ok=True)
OUT_JSON = f"{OUT_DIR}/pit_top10_all_codes.json"


def fetch_batch(codes):
    q = ",".join(f'"{c}"' for c in codes)
    flt = urllib.parse.quote(f'(SECURITY_CODE in ({q}))(END_DATE>=\'2021-06-30\')')
    out = []
    page = 1
    while page <= 12:
        url = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get?"
            "reportName=RPT_F10_EH_FREEHOLDERS&columns=SECURITY_CODE,END_DATE,NOTICE_DATE,HOLDER_RANK,FREE_HOLDNUM_RATIO"
            f"&filter={flt}&pageSize=500&pageNumber={page}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=8).read().decode("utf-8")
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
    base_idx = json.load(open(f"{SANDBOX}/pit_top10_summary.json", "r", encoding="utf-8"))
    if os.path.exists(OUT_JSON):
        saved = json.load(open(OUT_JSON, "r", encoding="utf-8"))
        base_idx.update(saved)

    cols = ["date", "ticker", "close", "adj_close"]
    a1 = pd.read_parquet(f"{BASE}/data/cn_hk_price_db/a_daily.parquet", columns=cols, filters=[("date", ">=", pd.Timestamp("2021-11-01"))])
    a2 = pd.read_parquet(f"{BASE}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=cols, filters=[("date", ">=", pd.Timestamp("2021-11-01"))])
    df = pd.concat([a1, a2], ignore_index=True)
    df["code"] = df["ticker"].str[:6]
    df = df[df["ticker"].str.endswith((".SH", ".SZ")) & df["code"].str.startswith(("00", "60"))].sort_values(["code", "date"]).drop_duplicates(["code", "date"])
    g = df.groupby("code")
    adjf = df["adj_close"] / df["close"]
    prevc = g["close"].shift(1) * adjf.groupby(df["code"]).shift(1) / adjf
    pct = df["close"] / prevc - 1.0
    zt = (df["close"] >= (prevc * 1.10).round(2) - 0.011) & (pct >= 0.095) & prevc.notna()
    dt = (df["close"] <= (prevc * 0.90).round(2) + 0.011) & (pct <= -0.095) & prevc.notna()

    s_zt = zt.astype(int)
    df["st"] = s_zt.groupby([df["code"], (s_zt != s_zt.groupby(df["code"]).shift()).cumsum()]).cumsum() * s_zt
    s_dt = dt.astype(int)
    df["dst"] = s_dt.groupby([df["code"], (s_dt != s_dt.groupby(df["code"]).shift()).cumsum()]).cumsum() * s_dt

    sub = df[df["date"] >= pd.Timestamp("2022-01-01")]
    target_codes = sorted(set(sub[(sub["st"] >= 2) | (sub["dst"] >= 2)]["code"].unique()) - set(base_idx.keys()))
    print(f"[*] Existing PIT holders: {len(base_idx)}, need backfill: {len(target_codes)}")

    if target_codes:
        batches = [target_codes[i:i + 15] for i in range(0, len(target_codes), 15)]
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
            base_idx[c] = sorted([[v[0], ed, round(min(95.0, v[1]), 2), round(min(95.0, v[2]), 2)] for ed, v in ed_map.items()])

    json.dump(base_idx, open(OUT_JSON, "w", encoding="utf-8"))
    print(f"[+] Saved {len(base_idx)} PIT holder series to {OUT_JSON} in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
