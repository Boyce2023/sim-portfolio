#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Helper library for csrc_national_team_monitor.py (21 verified NT ETFs, SSE/SZSE shares, Sina quotes, official NT news)."""
import os, re, sqlite3, sys
os.environ["NO_PROXY"] = "*"
from datetime import datetime
import numpy as np
import pandas as pd
import requests
import akshare as ak

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from csrc_fetch_etf_shares import ETFS, OUT_DIR as NT_DIR

DATA_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data"


def fetch_recent_etf_and_update_shares(lookback_days: int = 60):
    now = datetime.now()
    beg = (now - pd.Timedelta(days=lookback_days + 40)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    px_list = []
    for code, (name, exch, grp, team, nt_w) in ETFS.items():
        df = ak.fund_etf_hist_em(symbol=code, period="daily", start_date=beg, end_date=end, adjust="")
        df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交额": "amount", "涨跌幅": "pct_chg"})
        df["code"], df["name"], df["exch"], df["idx_grp"], df["team"], df["nt_w"] = code, name, exch, grp, team, nt_w
        px_list.append(df[["date", "code", "name", "exch", "idx_grp", "team", "nt_w", "open", "high", "low", "close", "amount", "pct_chg"]])
    px = pd.concat(px_list, ignore_index=True)
    all_dates = sorted(px["date"].unique().tolist())

    sse_p = os.path.join(NT_DIR, "sse_shares_cache.parquet")
    sse_old = pd.read_parquet(sse_p)
    sse_done = set(sse_old["date"].unique())
    today_str = now.strftime("%Y-%m-%d")
    recent_dates = [d for d in all_dates[-15:] if d not in sse_done and (d < today_str or now.hour >= 19)]
    sse_codes = {c for c, v in ETFS.items() if v[1] == "SSE"}
    new_sse = []
    for dt in recent_dates:
        try:
            r = requests.get("https://query.sse.com.cn/commonQuery.do", params={"isPagination": "false", "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L", "STAT_DATE": dt}, headers={"Referer": "https://www.sse.com.cn/", "User-Agent": "Mozilla/5.0"}, timeout=10)
            for x in r.json().get("result", []):
                c = str(x.get("SEC_CODE", "")).strip()
                if c in sse_codes:
                    new_sse.append({"date": dt, "code": c, "shares_wan": float(str(x.get("TOT_VOL", "0")).replace(",", ""))})
        except Exception:
            pass
    sse_all = pd.concat([sse_old, pd.DataFrame(new_sse)], ignore_index=True).drop_duplicates(["date", "code"])
    if new_sse:
        sse_all.to_parquet(sse_p, index=False)

    szse_p = os.path.join(NT_DIR, "szse_shares_cache.parquet")
    szse_old = pd.read_parquet(szse_p)
    d1, d2 = (now - pd.Timedelta(days=35)).strftime("%Y-%m-%d"), today_str
    new_sz = []
    for c, v in ETFS.items():
        if v[1] != "SZSE":
            continue
        try:
            r = requests.get("https://fund.szse.cn/api/report/ShowReport/data", params={"SHOWTYPE": "JSON", "CATALOGID": "fund_jjgm", "TABKEY": "tab1", "txtDm": c, "txtStart": d1, "txtEnd": d2, "PAGENO": 1}, headers={"Referer": "https://fund.szse.cn/", "User-Agent": "Mozilla/5.0"}, timeout=10)
            for it in r.json()[0].get("data", []):
                new_sz.append({"date": it["size_date"], "code": c, "shares_wan": float(str(it.get("current_size", "0")).replace(",", ""))})
        except Exception:
            pass
    szse_all = pd.concat([szse_old, pd.DataFrame(new_sz)], ignore_index=True).drop_duplicates(["date", "code"])
    if new_sz:
        szse_all.to_parquet(szse_p, index=False)

    sh = pd.concat([sse_all, szse_all], ignore_index=True).drop_duplicates(["date", "code"])
    df = px.merge(sh, on=["date", "code"], how="left").sort_values(["code", "date"]).reset_index(drop=True)
    df["prev_sh"] = df.groupby("code")["shares_wan"].shift(1)
    df["net_flow_yi"] = np.where(df["pct_chg"].abs() > 25, 0.0, (df["shares_wan"] - df["prev_sh"]) * 1e4 * df["close"] / 1e8)
    df["nt_w_flow_yi"] = df["net_flow_yi"] * df["nt_w"].astype(float)
    return df


def fetch_sina_realtime_quotes():
    syms = "sh000001,sh000300,sh000852,sh000016,sh601398,sh601939,sh601288,sh601988,sh601857,sh600028,sh600941"
    r = requests.get(f"https://hq.sinajs.cn/list={syms}", headers={"Referer": "https://finance.sina.com.cn"}, timeout=8)
    r.encoding = "gbk"
    out = {}
    for ln in r.text.strip().splitlines():
        m = re.match(r'var hq_str_(\w+)="([^"]*)"', ln)
        if not m:
            continue
        ps = m.group(2).split(",")
        if len(ps) > 5:
            prev_c, cur = float(ps[2]), float(ps[3])
            out[m.group(1)] = {"name": ps[0], "open": float(ps[1]), "prev": prev_c, "now": cur, "high": float(ps[4]), "low": float(ps[5]), "pct": (cur / prev_c - 1) * 100 if prev_c > 0 else 0.0}
    return out


def scan_recent_nt_news(days: int = 30):
    cut = (datetime.now() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    hits = []
    kws_db = "(title LIKE '%中央汇金%' OR title LIKE '%汇金资管%' OR title LIKE '%中国国新%' OR title LIKE '%国新投资%' OR title LIKE '%中国诚通%' OR title LIKE '%诚旸投资%' OR title LIKE '%互换便利%' OR title LIKE '%全国社保%' OR title LIKE '%证金公司%')"
    for db_name, tbl in [("flash_news_5y_pit.db", "flash_news"), ("cninfo_notices_5y_pit.db", "notices")]:
        p = os.path.join(DATA_DIR, db_name)
        if os.path.exists(p):
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            sql = f"SELECT pub_datetime_cst, title FROM {tbl} WHERE pub_datetime_cst >= '{cut}' AND {kws_db} ORDER BY pub_datetime_cst DESC LIMIT 80"
            for dt, title in con.execute(sql).fetchall():
                t = str(title)
                if any(b in t for b in ["龙虎榜", "港股通", "南向", "北向", "主力资金", "社保缴纳", "医保", "退休金"]):
                    continue
                hits.append({"dt": str(dt), "src": db_name.split("_")[0], "title": t[:82]})
            con.close()
    try:
        em = ak.stock_info_global_em()
        kws = ["中央汇金", "汇金资管", "中国国新", "国新投资", "中国诚通", "诚旸投资", "证金公司", "互换便利", "全国社保", "国家队"]
        sub = em[em["标题"].fillna("").str.contains("|".join(kws)) | em["摘要"].fillna("").str.contains("|".join(kws))]
        for _, r in sub.iterrows():
            t = str(r["标题"])
            if any(b in f"{t} {r['摘要']}" for b in ["主力资金", "龙虎榜", "港股通", "南向", "北向", "社保缴纳", "医保"]):
                continue
            hits.append({"dt": str(r["发布时间"]), "src": "eastmoney_live", "title": t[:82]})
    except Exception:
        pass
    seen, clean = set(), []
    for h in sorted(hits, key=lambda x: x["dt"], reverse=True):
        k = (h["dt"][:10], h["title"][:18])
        if k not in seen:
            seen.add(k)
            clean.append(h)
    return clean[:20]


def fetch_intraday_5m_pulses(target_date: str):
    import json, urllib.request
    watch = ["sh510300", "sh510330", "sz159919", "sh510500", "sh512100", "sz159915", "sh588080"]
    pulses = {}
    for sym in watch:
        try:
            u = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol={sym}&scale=5&ma=no&datalen=50"
            txt = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=4).read().decode("utf-8", "ignore")
            i, j = txt.find("["), txt.rfind("]")
            bars = [b for b in json.loads(txt[i:j+1]) if b["day"].startswith(target_date)]
            # Exclude incomplete last 1-min bar if volume is tiny
            valid = [b for b in bars[:-1]] if len(bars) > 4 and float(bars[-1]["volume"]) < 0.2 * float(bars[-2]["volume"]) else bars
            vols = [float(b["volume"]) for b in valid]
            if len(vols) < 4:
                continue
            med_v = float(np.median(vols))
            best = max(valid, key=lambda b: float(b["volume"]))
            max_mult = float(best["volume"]) / max(1.0, med_v)
            max_amt_yi = float(best["volume"]) * float(best["close"]) / 1e8
            burst_20m_yi = 0.0
            for idx_b in range(max(0, len(valid) - 12), len(valid)):
                w4 = valid[max(0, idx_b - 3):idx_b + 1]
                burst_20m_yi = max(burst_20m_yi, sum(float(x["volume"]) * float(x["close"]) / 1e8 for x in w4))
            pulses[sym[-6:]] = {
                "peak_hhmm": best["day"][11:16],
                "max_5m_mult": round(max_mult, 2),
                "peak_5m_amt_yi": round(max_amt_yi, 2),
                "recent_20m_burst_yi": round(burst_20m_yi, 2),
            }
        except Exception:
            pass
    return pulses
