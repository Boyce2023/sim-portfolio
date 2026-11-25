#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Build unified PIT historical dataset cache through 2026-11-24 for V3.0 National Team Scorecard.
Strictly NO yfinance (D12 compliant).
Caches stored in output/csrc_policy_100factors_20261114/national_team/v3_cache/.
"""
import os, time, json, warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
warnings.filterwarnings("ignore")
os.environ["NO_PROXY"] = "*"

import numpy as np
import pandas as pd
import requests
import akshare as ak

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from csrc_fetch_etf_shares import ETFS, OUT_DIR as NT_DIR

CACHE_DIR = os.path.join(NT_DIR, "v3_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
IDX_BASE_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/nt_mantra_backtest_20261120/data_cache/broad_indices_to_20261119.parquet"
ETF_BASE_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/nt_mantra_backtest_20261120/data_cache/etf_daily_to_20261119.parquet"

CORE10_ETFS = {
    "510300": ("华泰300", "SSE", "T1", 0.8296),
    "510310": ("易方达300", "SSE", "T1", 0.8549),
    "510330": ("华夏300", "SSE", "T1", 0.8914),
    "159919": ("嘉实300", "SZSE", "T1", 0.8766),
    "510050": ("华夏上证50", "SSE", "T1", 0.8605),
    "510500": ("南方500", "SSE", "T2", 0.7591),
    "512100": ("南方1000", "SSE", "T2", 0.8643),
    "159915": ("易方达创业板", "SZSE", "T2", 0.5403),
    "588000": ("华夏科创50", "SSE", "T2", 0.2500),
    "588080": ("易方达科创50", "SSE", "T2", 0.4195),
}

SECTOR_SSE_ETFS = [
    ("588000", "科创50ETF"), ("512000", "券商ETF"), ("512880", "证券ETF"), ("512480", "半导体ETF"),
    ("512010", "医药ETF"), ("512690", "酒ETF"), ("515030", "新能车ETF"), ("515790", "光伏ETF"),
    ("510880", "红利ETF"), ("512800", "银行ETF"),
]

NT16_STOCKS = {
    "601398.SH": ("工商银行", "bank"), "601288.SH": ("农业银行", "bank"),
    "601988.SH": ("中国银行", "bank"), "601939.SH": ("建设银行", "bank"),
    "600036.SH": ("招商银行", "bank"),
    "601857.SH": ("中国石油", "energy_soe"), "600028.SH": ("中国石化", "energy_soe"),
    "600941.SH": ("中国移动", "energy_soe"), "601088.SH": ("中国神华", "energy_soe"),
    "600900.SH": ("长江电力", "energy_soe"),
    "601318.SH": ("中国平安", "fin_cons"), "601628.SH": ("中国人寿", "fin_cons"),
    "600519.SH": ("贵州茅台", "fin_cons"), "600030.SH": ("中信证券", "fin_cons"),
    "300750.SZ": ("宁德时代", "growth"), "688981.SH": ("中芯国际", "growth"),
}

FUND8_STOCKS = {
    "300750.SZ": "宁德时代", "300308.SZ": "中际旭创", "300274.SZ": "阳光电源", "688256.SH": "寒武纪",
    "300059.SZ": "东方财富", "002475.SZ": "立讯精密", "603259.SH": "药明康德", "000858.SZ": "五粮液",
}


def build_indices():
    syms = {
        "sh000001": "上证指数", "sh000016": "上证50", "sh000300": "沪深300",
        "sh000905": "中证500", "sh000852": "中证1000", "sh000688": "科创50", "sz399006": "创业板指"
    }
    frames = []
    for sym, nm in syms.items():
        df = ak.stock_zh_index_daily_tx(symbol=sym)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df[(df["date"] >= "2016-01-01") & (df["date"] <= "2026-11-24")].copy()
        df["symbol"] = sym
        df["name"] = nm
        for c in ["open", "high", "low", "close", "amount"]:
            if c in df.columns:
                df[c] = df[c].astype(float)
        frames.append(df[["date", "symbol", "name", "open", "high", "low", "close", "amount"]])
        print(f"  idx {sym}: {len(df)} [{df['date'].min()} -> {df['date'].max()}]")
    out = pd.concat(frames, ignore_index=True)
    out.to_parquet(os.path.join(CACHE_DIR, "indices_to_20261124.parquet"), index=False)
    return out


def build_etfs_and_shares(trade_dates):
    # Base 21 ETFs up to 2026-11-19 + extend to 2026-11-24 + add 588000 and 9 sector ETFs
    etf_base = pd.read_parquet(ETF_BASE_PATH)
    etf_base["date"] = pd.to_datetime(etf_base["date"]).dt.strftime("%Y-%m-%d")
    etf_base = etf_base[etf_base["date"] <= "2026-11-19"].copy()

    ext_rows = []
    for code, (name, exch, grp, team, nt_w) in ETFS.items():
        sym = ("sh" if exch == "SSE" or code.startswith(("51", "56", "58")) else "sz") + code
        df = ak.fund_etf_hist_sina(symbol=sym)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        sub = df[(df["date"] >= "2026-11-18") & (df["date"] <= "2026-11-24")].sort_values("date")
        prev_c = None
        for _, sr in sub.iterrows():
            c = float(sr["close"])
            pct = ((c / prev_c - 1.0) * 100.0) if prev_c else np.nan
            prev_c = c
            if sr["date"] > "2026-11-19":
                ext_rows.append({
                    "date": sr["date"], "code": code, "name": name, "exch": exch,
                    "idx_grp": grp, "team": team, "nt_w": float(nt_w),
                    "open": float(sr["open"]), "high": float(sr["high"]),
                    "low": float(sr["low"]), "close": c, "close_qfq": c,
                    "split_ratio": 1.0, "volume": float(sr["volume"]),
                    "amount": float(sr["amount"]), "pct_chg": pct,
                })
    etf_21 = pd.concat([etf_base, pd.DataFrame(ext_rows)], ignore_index=True)

    # Extra SSE ETFs (588000 + 9 sector ETFs) full history 2019-2026-11-24
    extra_frames = []
    for code, nm in SECTOR_SSE_ETFS:
        df = ak.fund_etf_hist_sina(symbol="sh" + code)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df[(df["date"] >= "2019-01-01") & (df["date"] <= "2026-11-24")].sort_values("date").copy()
        df["code"] = code
        df["name"] = nm
        df["pct_chg"] = df["close"].pct_change() * 100.0
        extra_frames.append(df[["date", "code", "name", "open", "high", "low", "close", "volume", "amount", "pct_chg"]])
    etf_extra = pd.concat(extra_frames, ignore_index=True)
    etf_21.to_parquet(os.path.join(CACHE_DIR, "etf21_to_20261124.parquet"), index=False)
    etf_extra.to_parquet(os.path.join(CACHE_DIR, "etf_extra10_to_20261124.parquet"), index=False)
    print(f"  etf21 max={etf_21['date'].max()}, extra10 max={etf_extra['date'].max()} rows={len(etf_extra)}")

    # Fetch SSE official shares for extra 10 ETFs from 2020-01-01 to 2026-11-24
    extra_codes = {c for c, _ in SECTOR_SSE_ETFS}
    sh_p = os.path.join(CACHE_DIR, "sse_extra10_shares.parquet")
    old_df = pd.read_parquet(sh_p) if os.path.exists(sh_p) else pd.DataFrame()
    done = set(old_df["date"].unique()) if not old_df.empty else set()
    todo = [d for d in trade_dates if "2020-06-01" <= d <= "2026-11-24" and d not in done]
    print(f"  Fetching SSE extra10 shares for {len(todo)} dates...")

    def _one_day(dt):
        s = requests.Session()
        s.headers.update({"Referer": "https://www.sse.com.cn/", "User-Agent": "Mozilla/5.0"})
        for _ in range(3):
            try:
                r = s.get("https://query.sse.com.cn/commonQuery.do",
                          params={"isPagination": "false", "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L", "STAT_DATE": dt},
                          timeout=10)
                rows = []
                for x in r.json().get("result", []):
                    c = str(x.get("SEC_CODE", "")).strip()
                    if c in extra_codes:
                        try:
                            val = float(str(x.get("TOT_VOL", "0")).replace(",", ""))
                        except Exception:
                            val = np.nan
                        rows.append({"date": dt, "code": c, "shares_wan": val})
                return rows
            except Exception:
                time.sleep(0.2)
        return []

    new_rows = []
    if todo:
        with ThreadPoolExecutor(max_workers=20) as ex:
            futs = [ex.submit(_one_day, d) for d in todo]
            for i, fut in enumerate(as_completed(futs), 1):
                new_rows.extend(fut.result())
                if i % 400 == 0:
                    print(f"    SSE extra10 {i}/{len(todo)} done...")
    res_sh = pd.concat([old_df, pd.DataFrame(new_rows)], ignore_index=True).drop_duplicates(["date", "code"]).sort_values(["code", "date"])
    res_sh.to_parquet(sh_p, index=False)
    print(f"  sse_extra10_shares saved: {len(res_sh)} rows [{res_sh['date'].min()} -> {res_sh['date'].max()}]")


def build_futures():
    dfs = []
    for sym in ["IF0", "IH0", "IC0", "IM0"]:
        df = ak.futures_main_sina(symbol=sym, start_date="20160101", end_date="20261125")
        df["date"] = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d")
        df = df[df["date"] <= "2026-11-24"].copy()
        df = df[["date", "开盘价", "最高价", "最低价", "收盘价", "成交量", "持仓量"]].rename(columns={
            "开盘价": f"{sym}_open", "最高价": f"{sym}_high", "最低价": f"{sym}_low",
            "收盘价": f"{sym}_close", "成交量": f"{sym}_vol", "持仓量": f"{sym}_oi",
        })
        for c in df.columns:
            if c != "date":
                df[c] = df[c].astype(float)
        dfs.append(df)
    fut = dfs[0]
    for d in dfs[1:]:
        fut = fut.merge(d, on="date", how="outer")
    fut = fut.sort_values("date").reset_index(drop=True)
    fut.to_parquet(os.path.join(CACHE_DIR, "futures_to_20261124.parquet"), index=False)
    print(f"  futures saved: {len(fut)} [{fut['date'].min()} -> {fut['date'].max()}]")


def build_stocks():
    tks = sorted(set(NT16_STOCKS.keys()) | set(FUND8_STOCKS.keys()))
    ad = pd.read_parquet(A_DAILY_PATH, columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "amount"])
    sub = ad[ad["ticker"].isin(tks)].copy()
    sub["date"] = pd.to_datetime(sub["date"]).dt.strftime("%Y-%m-%d")
    sub = sub[sub["date"] >= "2016-01-01"].sort_values(["ticker", "date"]).reset_index(drop=True)
    sub.to_parquet(os.path.join(CACHE_DIR, "stocks23_to_20261124.parquet"), index=False)
    print(f"  stocks23 saved: {len(sub)} rows, n_tickers={sub['ticker'].nunique()}, max={sub['date'].max()}")


def build_lhb():
    lhb_p = os.path.join(CACHE_DIR, "lhb_org_daily_2020_2026.parquet")
    if os.path.exists(lhb_p):
        old = pd.read_parquet(lhb_p)
        if old["date"].max() >= "2026-11-24":
            print(f"  lhb cache up to date: {old['date'].max()}")
            return
    chunks = [
        ("20200101", "20201231"), ("20210101", "20210630"), ("20210701", "20211231"),
        ("20220101", "20220630"), ("20220701", "20221231"), ("20230101", "20230630"),
        ("20230701", "20231231"), ("20240101", "20240630"), ("20240701", "20241231"),
        ("20250101", "20250630"), ("20250701", "20251231"), ("20260101", "20260630"),
        ("20260701", "20261125"),
    ]
    def _fetch_chunk(c):
        b, e = c
        for _ in range(3):
            try:
                jg = ak.stock_lhb_jgmmtj_em(start_date=b, end_date=e)
                if jg is not None and len(jg):
                    jg["date"] = pd.to_datetime(jg["上榜日期"]).dt.strftime("%Y-%m-%d")
                    g = jg.groupby("date").agg(
                        lhb_n=("代码", "count"),
                        lhb_buy_yi=("机构买入总额", lambda s: s.sum() / 1e8),
                        lhb_sell_yi=("机构卖出总额", lambda s: s.sum() / 1e8),
                        lhb_net_yi=("机构买入净额", lambda s: s.sum() / 1e8),
                    ).reset_index()
                    return g
            except Exception:
                time.sleep(0.5)
        return pd.DataFrame()

    frames = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for res in ex.map(_fetch_chunk, chunks):
            if not res.empty:
                frames.append(res)
    out = pd.concat(frames, ignore_index=True).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    out = out[out["date"] <= "2026-11-24"].copy()
    out.to_parquet(lhb_p, index=False)
    print(f"  lhb saved: {len(out)} days [{out['date'].min()} -> {out['date'].max()}]")


if __name__ == "__main__":
    t0 = time.time()
    print("[1/5] Building indices...")
    idx = build_indices()
    cal_dates = sorted(idx[idx["symbol"] == "sh000300"]["date"].unique().tolist())
    print("[2/5] Building ETFs & SSE extra10 shares...")
    build_etfs_and_shares(cal_dates)
    print("[3/5] Building futures...")
    build_futures()
    print("[4/5] Building 23 heavyweight stocks...")
    build_stocks()
    print("[5/5] Building LHB institutional seats...")
    build_lhb()
    print(f"ALL CACHE BUILT in {time.time()-t0:.1f}s!")
