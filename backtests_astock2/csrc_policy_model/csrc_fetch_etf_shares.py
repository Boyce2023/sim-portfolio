#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Fetch full verified 21 National-Team-held ETFs (2025AR Top-10 verified):
1. Daily unadjusted & qfq OHLCV (Eastmoney via akshare, NO_PROXY="*")
2. Daily official shares from SSE (2012-2026) & SZSE (2016-2026)
"""
import os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
os.environ["NO_PROXY"] = "*"

import numpy as np
import pandas as pd
import requests
import akshare as ak

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/national_team"
os.makedirs(OUT_DIR, exist_ok=True)

# 21 ETFs verified from 2025 Annual Report Top-10 Holders (code -> (name, exch, idx_grp, team, nt_pct_25ar))
ETFS = {
    # Team 1: Large-Cap Core (9)
    "510300": ("华泰柏瑞沪深300ETF", "SSE", "CSI300", "T1", 0.8296),
    "510310": ("易方达沪深300ETF", "SSE", "CSI300", "T1", 0.8549),
    "510330": ("华夏沪深300ETF", "SSE", "CSI300", "T1", 0.8914),
    "159919": ("嘉实沪深300ETF", "SZSE", "CSI300", "T1", 0.8766),
    "510050": ("华夏上证50ETF", "SSE", "SSE50", "T1", 0.8605),
    "510180": ("华安上证180ETF", "SSE", "SSE180", "T1", 0.9193),
    "510230": ("国泰上证180金融ETF", "SSE", "SSE180FIN", "T1", 0.7759),
    "159901": ("易方达深证100ETF", "SZSE", "SZ100", "T1", 0.4693),
    "510100": ("易方达上证50ETF", "SSE", "SSE50", "T1", 0.0583),
    # Team 2: Mid/Small/Growth Diffusion (11)
    "560010": ("广发中证1000ETF", "SSE", "CSI1000", "T2", 0.9186),
    "512100": ("南方中证1000ETF", "SSE", "CSI1000", "T2", 0.8643),
    "159845": ("华夏中证1000ETF", "SZSE", "CSI1000", "T2", 0.8615),
    "159629": ("富国中证1000ETF", "SZSE", "CSI1000", "T2", 0.8574),
    "510500": ("南方中证500ETF", "SSE", "CSI500", "T2", 0.7591),
    "512500": ("华夏中证500ETF", "SSE", "CSI500", "T2", 0.6734),
    "159922": ("嘉实中证500ETF", "SZSE", "CSI500", "T2", 0.4606),
    "159915": ("易方达创业板ETF", "SZSE", "CHINEXT", "T2", 0.5403),
    "159952": ("广发创业板ETF", "SZSE", "CHINEXT", "T2", 0.1689),
    "588080": ("易方达科创50ETF", "SSE", "STAR50", "T2", 0.4195),
    "588050": ("工银科创50ETF", "SSE", "STAR50", "T2", 0.1178),
    # Team 3: Guoxin / Chengtong SOE Specialized (1)
    "560170": ("南方央企科技引领ETF", "SSE", "SOETECH", "T3", 0.6630),
}
SSE_CODES = {k for k, v in ETFS.items() if v[1] == "SSE"}
SZSE_CODES = [k for k, v in ETFS.items() if v[1] == "SZSE"]


def fetch_etf_prices():
    frames = []
    for code, (name, exch, idx_grp, team, nt_w) in ETFS.items():
        raw = ak.fund_etf_hist_em(symbol=code, period="daily", start_date="20100101", end_date="20261119", adjust="")
        qfq = ak.fund_etf_hist_em(symbol=code, period="daily", start_date="20100101", end_date="20261119", adjust="qfq")
        raw = raw.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount", "涨跌幅": "pct_chg"})
        qfq = qfq.rename(columns={"日期": "date", "收盘": "close_qfq"})[["date", "close_qfq"]]
        df = raw.merge(qfq, on="date", how="left")
        df["code"], df["name"], df["exch"], df["idx_grp"], df["team"], df["nt_w"] = code, name, exch, idx_grp, team, nt_w
        df["split_ratio"] = df["close_qfq"] / df["close"].replace(0, np.nan)
        frames.append(df[["date", "code", "name", "exch", "idx_grp", "team", "nt_w", "open", "high", "low", "close", "close_qfq", "split_ratio", "volume", "amount", "pct_chg"]])
        print(f"Price {code} ({name}): {len(df)} rows [{df['date'].min()} -> {df['date'].max()}]")
    out = pd.concat(frames, ignore_index=True)
    out.to_parquet(os.path.join(OUT_DIR, "etf_daily_prices.parquet"), index=False)
    return out


def fetch_sse_shares(trade_dates):
    cache_p = os.path.join(OUT_DIR, "sse_shares_cache.parquet")
    done_dates, old_df = set(), pd.DataFrame()
    if os.path.exists(cache_p):
        tmp = pd.read_parquet(cache_p)
        # Only reuse cache if all 14 SSE_CODES are already represented in the schema
        if SSE_CODES.issubset(set(tmp["code"].unique())):
            old_df = tmp[tmp["code"].isin(SSE_CODES)].copy()
            done_dates = set(old_df["date"].unique())
    todo = [d for d in trade_dates if "2012-01-04" <= d <= "2026-11-17" and d not in done_dates]
    print(f"SSE shares todo dates: {len(todo)} (cached {len(done_dates)}, target codes={len(SSE_CODES)})")
    if not todo:
        return old_df

    def one_day(dt):
        s = requests.Session()
        s.headers.update({"Referer": "https://www.sse.com.cn/", "User-Agent": "Mozilla/5.0"})
        for _ in range(3):
            try:
                r = s.get("https://query.sse.com.cn/commonQuery.do", params={"isPagination": "false", "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L", "STAT_DATE": dt}, timeout=12)
                rows = []
                for x in r.json().get("result", []):
                    c = str(x.get("SEC_CODE", "")).strip()
                    if c in SSE_CODES:
                        try:
                            vol_wan = float(str(x.get("TOT_VOL", "0")).replace(",", ""))
                        except Exception:
                            vol_wan = np.nan
                        rows.append({"date": dt, "code": c, "shares_wan": vol_wan})
                return rows
            except Exception:
                time.sleep(0.3)
        return []

    new_rows = []
    with ThreadPoolExecutor(max_workers=14) as ex:
        futs = [ex.submit(one_day, d) for d in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            new_rows.extend(fut.result())
            if i % 600 == 0:
                print(f"  SSE fetched {i}/{len(todo)} dates...")

    res_df = pd.concat([old_df, pd.DataFrame(new_rows)], ignore_index=True).drop_duplicates(["date", "code"]).sort_values(["code", "date"])
    res_df.to_parquet(cache_p, index=False)
    print(f"SSE shares saved: {len(res_df)} rows across {res_df['code'].nunique()} codes")
    return res_df


def fetch_szse_shares():
    cache_p = os.path.join(OUT_DIR, "szse_shares_cache.parquet")
    windows, cur, end_t = [], pd.Timestamp("2016-12-01"), pd.Timestamp("2026-11-18")
    while cur <= end_t:
        nxt = min(end_t, cur + pd.Timedelta(days=60))
        windows.append((cur.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")))
        cur = nxt + pd.Timedelta(days=1)

    def fetch_win(code, d1, d2):
        s = requests.Session()
        s.headers.update({"Referer": "https://fund.szse.cn/", "User-Agent": "Mozilla/5.0"})
        rows, page = [], 1
        while True:
            js = None
            for _ in range(3):
                try:
                    r = s.get("https://fund.szse.cn/api/report/ShowReport/data", params={"SHOWTYPE": "JSON", "CATALOGID": "fund_jjgm", "TABKEY": "tab1", "txtDm": code, "txtStart": d1, "txtEnd": d2, "PAGENO": page}, timeout=12)
                    js = r.json()[0]
                    break
                except Exception:
                    time.sleep(0.3)
            if not js or not js.get("data"):
                break
            for it in js["data"]:
                try:
                    val = float(str(it.get("current_size", "0")).replace(",", ""))
                except Exception:
                    val = np.nan
                rows.append({"date": it["size_date"], "code": code, "shares_wan": val})
            if page >= int(js["metadata"].get("pagecount", 1)):
                break
            page += 1
        return rows

    all_rows = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(fetch_win, c, d1, d2) for c in SZSE_CODES for (d1, d2) in windows]
        for fut in as_completed(futs):
            all_rows.extend(fut.result())
    df = pd.DataFrame(all_rows).drop_duplicates(["date", "code"]).sort_values(["code", "date"])
    df.to_parquet(cache_p, index=False)
    print(f"SZSE shares saved: {len(df)} rows across {df['code'].nunique()} codes [{df['date'].min()} -> {df['date'].max()}]")
    return df


if __name__ == "__main__":
    p_df = fetch_etf_prices()
    td_cal = sorted(p_df["date"].unique().tolist())
    fetch_sse_shares(td_cal)
    fetch_szse_shares()
