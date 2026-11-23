#!/usr/bin/env python3
"""RD021 Step 1: Build clean 10Y (2015-01-01 ~ 2026-11-20) stock + futures/spot data cache.
Strictly NO yfinance imports (D12). Reads local parquets + AKShare Sina + FRED CSV.
"""
import json, subprocess
from pathlib import Path
import akshare as ak
import numpy as np
import pandas as pd

OUT_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/commodities_leadlag_10y_20261123/data_cache")
OUT_DIR.mkdir(parents=True, exist_ok=True)

A_STOCKS = [
    "002714.SZ", "300498.SZ",              # 生猪: 牧原股份, 温氏股份
    "002460.SZ", "002466.SZ", "000792.SZ", # 碳酸锂: 赣锋锂业, 天齐锂业, 盐湖股份
    "601899.SH", "603993.SH",              # 铜: 紫金矿业, 洛阳钼业
    "600938.SH", "601857.SH",              # 石油: 中国海油, 中国石油
    "600547.SH", "600988.SH",              # 黄金: 山东黄金, 赤峰黄金
    "601088.SH", "000983.SZ", "601699.SH", # 煤炭: 中国神华, 山西焦煤, 潞安环能
]
US_STOCKS = ["FCX", "XOM", "NEM", "RGLD", "ALB", "SQM"]
CN_FUTURES = ["AU0", "CU0", "SC0", "JM0", "J0", "LH0", "LC0", "ZC0"]
GLOBAL_FUTURES = {"GC_F": "GC_F.parquet", "CL_F": "CL_F.parquet", "BZ_F": "BZ_F.parquet", "HG_F": "HG_F.parquet"}
START_DT, END_DT = pd.Timestamp("2015-01-01"), pd.Timestamp("2026-11-20")

def main():
    meta = {"as_of_date": "2026-11-20", "series": {}}

    # 1. A-share stocks from local a_daily.parquet (use adj_close)
    sub_a = pd.read_parquet(
        "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet",
        columns=["date", "ticker", "open", "close", "adj_close"],
        filters=[("ticker", "in", A_STOCKS)],
    )
    sub_a["date"] = pd.to_datetime(sub_a["date"])
    sub_a = sub_a[(sub_a["date"] >= START_DT) & (sub_a["date"] <= END_DT)].sort_values(["ticker", "date"])
    sub_a["adj_open"] = sub_a["open"] * (sub_a["adj_close"] / sub_a["close"].replace(0, np.nan))
    a_close = sub_a.pivot_table(index="date", columns="ticker", values="adj_close", aggfunc="last").sort_index()
    a_open = sub_a.pivot_table(index="date", columns="ticker", values="adj_open", aggfunc="last").sort_index()
    a_close.to_parquet(OUT_DIR / "a_stocks_close.parquet")
    a_open.to_parquet(OUT_DIR / "a_stocks_open.parquet")
    for c in A_STOCKS:
        s = a_close[c].dropna() if c in a_close.columns else pd.Series(dtype=float)
        meta["series"][c] = {
            "n": len(s), "start": str(s.index.min())[:10], "end": str(s.index.max())[:10],
            "max_1d_abs_ret": round(float(s.pct_change().abs().max()), 4) if len(s) > 2 else 0.0,
        }

    # 2. US stocks from local all_daily.parquet
    us_df = pd.read_parquet(
        "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/all_daily.parquet",
        columns=["date", "ticker", "open", "close", "adj_close"],
        filters=[("ticker", "in", US_STOCKS)],
    )
    us_df["date"] = pd.to_datetime(us_df["date"])
    us_df = us_df[(us_df["date"] >= START_DT) & (us_df["date"] <= END_DT)]
    us_close = us_df.pivot_table(index="date", columns="ticker", values="adj_close", aggfunc="last").sort_index()
    us_close.to_parquet(OUT_DIR / "us_stocks_close.parquet")
    for c in US_STOCKS:
        s = us_close[c].dropna()
        meta["series"][c] = {
            "n": len(s), "start": str(s.index.min())[:10], "end": str(s.index.max())[:10],
            "max_1d_abs_ret": round(float(s.pct_change().abs().max()), 4),
        }

    # 3. Global futures from local us_price_db/commodities/
    gf_dict = {}
    for k, fn in GLOBAL_FUTURES.items():
        df = pd.read_parquet(f"/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/commodities/{fn}")
        idx = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df["date"])
        s = pd.Series(pd.to_numeric(df["close"], errors="coerce").values, index=idx).sort_index()
        s = s[(s.index >= START_DT) & (s.index <= END_DT)].dropna()
        gf_dict[k] = s
        meta["series"][k] = {"n": len(s), "start": str(s.index.min())[:10], "end": str(s.index.max())[:10], "min": round(float(s.min()), 2), "max": round(float(s.max()), 2)}
    pd.DataFrame(gf_dict).to_parquet(OUT_DIR / "global_futures_close.parquet")

    # 4. Domestic futures from AKShare Sina
    cn_dict = {}
    for sym in CN_FUTURES:
        df = ak.futures_zh_daily_sina(symbol=sym)
        df["date"] = pd.to_datetime(df["date"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        s = df.set_index("date")["close"].sort_index()
        s = s[(s.index >= START_DT) & (s.index <= END_DT)].dropna()
        cn_dict[sym] = s
        meta["series"][sym] = {"n": len(s), "start": str(s.index.min())[:10], "end": str(s.index.max())[:10], "min": round(float(s.min()), 2), "max": round(float(s.max()), 2)}
    pd.DataFrame(cn_dict).to_parquet(OUT_DIR / "cn_futures_close.parquet")

    # 5. Hog spot (weekly 2015~2026) + Newcastle Thermal Coal (FRED monthly) + HS300
    hog = ak.index_hog_spot_price()
    hog["date"] = pd.to_datetime(hog["日期"])
    hog["spot_price"] = pd.to_numeric(hog["成交均价"], errors="coerce").fillna(pd.to_numeric(hog["指数"], errors="coerce"))
    hog_s = hog.set_index("date")["spot_price"].sort_index()
    hog_s = hog_s[(hog_s.index >= START_DT) & (hog_s.index <= END_DT)].dropna()
    hog_s.to_frame("hog_spot").to_parquet(OUT_DIR / "hog_spot_weekly.parquet")
    meta["series"]["HOG_SPOT"] = {"n": len(hog_s), "start": str(hog_s.index.min())[:10], "end": str(hog_s.index.max())[:10], "freq": "weekly"}

    r = subprocess.run(["curl", "-sm", "15", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=PCOALAUUSDM"], capture_output=True, text=True)
    rows = []
    for ln in r.stdout.strip().splitlines()[1:]:
        p = ln.split(",")
        if len(p) == 2 and p[1] not in ("", "."):
            rows.append((pd.to_datetime(p[0]), float(p[1])))
    coal_m = pd.DataFrame(rows, columns=["date", "newcastle_coal"]).set_index("date").sort_index()
    coal_m = coal_m[(coal_m.index >= START_DT) & (coal_m.index <= END_DT)]
    coal_m.to_parquet(OUT_DIR / "newcastle_coal_monthly.parquet")
    meta["series"]["NEWCASTLE_COAL"] = {"n": len(coal_m), "start": str(coal_m.index.min())[:10], "end": str(coal_m.index.max())[:10], "freq": "monthly"}

    hs = ak.stock_zh_index_daily(symbol="sh000300")
    hs["date"] = pd.to_datetime(hs["date"])
    hs["close"] = pd.to_numeric(hs["close"], errors="coerce")
    hs_s = hs.set_index("date")["close"].sort_index()
    hs_s = hs_s[(hs_s.index >= START_DT) & (hs_s.index <= END_DT)].dropna()
    hs_s.to_frame("sh000300").to_parquet(OUT_DIR / "sh000300.parquet")
    meta["series"]["sh000300"] = {"n": len(hs_s), "start": str(hs_s.index.min())[:10], "end": str(hs_s.index.max())[:10]}

    with open(OUT_DIR / "data_manifest.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(json.dumps(meta["series"], ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
