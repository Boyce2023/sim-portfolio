#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import os, re, json, sqlite3, urllib.request
from collections import defaultdict, Counter
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock2/p6_small_strategies_20261116"
A_DAILY = f"{PROJECT_ROOT}/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELIST = f"{PROJECT_ROOT}/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_16_21 = f"{PROJECT_ROOT}/sim-portfolio/data/kpl_plates_2016_2021.jsonl"
KPL_18_26 = f"{PROJECT_ROOT}/sim-portfolio/data/kpl_plates_2018_2026_merged.jsonl"
PIT_NOTICES = f"{PROJECT_ROOT}/sim-portfolio/data/cninfo_notices_5y_pit.db"
OLD_NOTICES = f"{PROJECT_ROOT}/sim-portfolio/backtest/2026-08-24-daban/notices.db"
ZT_TAPE = f"{PROJECT_ROOT}/sim-portfolio/data/zt_micro_tape_5y_pit.db"
IDX_CACHE = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
IND_CSV = f"{PROJECT_ROOT}/sim-portfolio/data/industry.csv"

MA_PAT = re.compile(r"(重大资产重组|控制权变更|实控人变更|筹划控制权|借壳|要约收购|筹划重大资产|购买资产并募集配套资金.*复牌|发行股份及支付现金购买资产预案|协议转让.*控制权)")
MA_EXC = re.compile(r"(解除限售|限售股上市|募集资金账户注销|业绩承诺补偿)")
POISON_PAT = re.compile(r"(立案调查|被立案|涉嫌违法|大额减持|清仓减持|业绩预亏|巨亏|计提大额减值|重大亏损|退市风险)")
BAD_KPL = ("并购重组", "股权转让", "实控人变更", "借壳", "壳资源", "ST板块", "摘帽")

SEASONS = [
    (f"{y}/{str(y+1)[2:]}", f"{y}-10-15", f"{y+1}-01-31", f"{y}-10-15", f"{y+1}-01-15")
    for y in range(2016, 2026)
]

def load_hs300_10y():
    hs = {}
    if os.path.exists(IDX_CACHE):
        with open(IDX_CACHE) as f:
            hs.update(json.load(f).get("sh000300", {}))
    try:
        for span in [("2016-01-01", "2021-12-31"), ("2022-01-01", "2026-11-16")]:
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000300,day,{span[0]},{span[1]},1600,"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8"))
            bars = raw.get("data", {}).get("sh000300", {}).get("day", [])
            for b in bars:
                hs[b[0]] = float(b[2])
    except Exception as e:
        print("HS300 fetch fallback:", e)
    s = pd.Series(hs, dtype=float)
    s.index = pd.to_datetime(s.index)
    return s.sort_index()

def load_meta():
    df_ind = pd.read_csv(IND_CSV)
    name_map = dict(zip(df_ind["code"].str[3:], df_ind["code_name"]))
    date_plate = {}
    stock_season_tags = defaultdict(Counter)
    for kp in [KPL_16_21, KPL_18_26]:
        if not os.path.exists(kp):
            continue
        with open(kp, errors="ignore") as f:
            for ln in f:
                try:
                    d = json.loads(ln)
                except Exception:
                    continue
                dt = d.get("date", "")
                if len(dt) < 10:
                    continue
                yr, mo = int(dt[:4]), int(dt[5:7])
                s_yr = yr if mo >= 10 else (yr - 1 if mo <= 2 else -1)
                p_dict = {}
                for pl in d.get("plates", []):
                    pn = pl.get("plate", "").strip()
                    if not pn:
                        continue
                    codes = []
                    for s in pl.get("stocks", []):
                        c6 = str(s[0])[-6:]
                        codes.append(c6)
                        sub = str(s[2]) if len(s) > 2 else ""
                        if 2016 <= s_yr <= 2025:
                            stock_season_tags[(s_yr, c6)][f"{pn}/{sub}"] += 1
                    p_dict[pn] = codes
                date_plate[dt] = p_dict

    tape_dict = defaultdict(dict)
    conn = sqlite3.connect(f"file:{ZT_TAPE}?mode=ro", uri=True)
    for dt, c6, pn, rsn in conn.execute("SELECT trade_date, sec_code, plate_name, reason_desc FROM zt_micro_tape"):
        tape_dict[dt][c6] = (pn or "", rsn or "")
    conn.close()

    ma_dates = defaultdict(list)
    poison_dates = defaultdict(list)
    st_dates = defaultdict(list)
    for dbp, sql in [
        (PIT_NOTICES, "SELECT trade_date_avail, sec_code, title, ann_type FROM notices"),
        (OLD_NOTICES, "SELECT ndate, code, title, ntype FROM notice"),
    ]:
        if not os.path.exists(dbp):
            continue
        c = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
        for dt, c6, t, at in c.execute(sql):
            txt = f"{t} {at}"
            c6 = str(c6)[-6:]
            if MA_PAT.search(txt) and not MA_EXC.search(txt):
                ma_dates[c6].append(str(dt)[:10])
            if POISON_PAT.search(txt):
                poison_dates[c6].append(str(dt)[:10])
            if "实施退市风险警示" in txt or "实施其他风险警示" in txt or "股票交易异常波动" in txt and "ST" in txt:
                st_dates[c6].append(str(dt)[:10])
        c.close()
    for dmap in (ma_dates, poison_dates, st_dates):
        for k in dmap:
            dmap[k] = sorted(set(dmap[k]))
    return name_map, date_plate, stock_season_tags, tape_dict, ma_dates, poison_dates

def load_seasonal_prices():
    cols = ["date", "ticker", "open", "high", "low", "close", "amount", "volume", "turn", "oshare"]
    parts = []
    for p in [A_DAILY, A_DELIST]:
        if not os.path.exists(p):
            continue
        dset = ds.dataset(p, format="parquet")
        for y in range(2016, 2026):
            flt = (ds.field("date") >= pd.Timestamp(f"{y}-08-15")) & (ds.field("date") <= pd.Timestamp(f"{y+1}-03-10"))
            tb = dset.scanner(columns=cols, filter=flt).to_table().to_pandas()
            tb["season_yr"] = y
            parts.append(tb)
    df = pd.concat(parts, ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60")) & (~df["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["season_yr", "c6", "dt_str"], inplace=True)
    df.drop_duplicates(subset=["season_yr", "c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df
