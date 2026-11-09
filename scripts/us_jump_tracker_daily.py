#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股全时间段近半年跳涨监测（每日自动更新版）
目标文件: ~/Desktop/Track/1_活表/1_选股_美股2026中报财报日涨跌.xlsx

核心规格（2026-11-09 Buwen 定）:
1. 直接在原 Q2 表上扩展为全时间段单日跳涨（收盘对收盘 >= +10.0%，剔除拆股与假打印）
2. 滚动保留近半年（183 个自然日）数据，最新跳涨排最上（同日按当日涨幅降序）
3. 专门注明由于财报引发的跳涨，在 D 列「财报季」精确标注如 26Q1 / 26Q2 / 26Q3 / 26Q4，非财报跳涨留空
4. 100% 保持原表格式与用户资产：
   - 保留原表样式索引（等线 11pt、表头加粗无底色无边框、J2/L2 黄格阈值、I/K 红白绿色阶、125% 缩放、冻结窗格）
   - 永久提取并继承 Buwen 手工红字代码、黄底代码、A2 批注行及 U 列手写业务笔记
   - ZIP 字节级无损保留「股价复盘」（含折线图 chart1.xml）与「SaaS界面」（含 5 张截图）等用户自建标签页
"""

import concurrent.futures as cf
import datetime as dt
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import warnings
import xml.etree.ElementTree as ET
import zipfile
import zoneinfo
from collections import Counter, defaultdict
from xml.sax.saxutils import escape as xml_escape

import numpy as np
import openpyxl
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

ET_TZ = zoneinfo.ZoneInfo("America/New_York")
CST_TZ = zoneinfo.ZoneInfo("Asia/Shanghai")

TARGET_XLSX = os.path.expanduser("~/Desktop/Track/1_活表/1_选股_美股2026中报财报日涨跌.xlsx")
ARCHIVE_DIR = os.path.expanduser("~/Desktop/Track/1_活表/_归档_底稿与旧版")
NEXUS_BACKUP_DIR = os.path.expanduser("~/.claude/nexus/backups/2026-11-09")
CACHE_DIR = os.path.expanduser("~/claude-projects/sim-portfolio/data/us_jump_tracker_cache")
PDB_PRICES_DIR = os.path.expanduser("~/claude-projects/sim-portfolio/data/us_price_db/prices")
D1019_DIR = os.path.expanduser("~/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19")

WINDOW_DAYS = 183
JUMP_THRESHOLD = 0.10
MIN_MCAP_B = 5.0

SEC_UA = {"User-Agent": "Buwen Deng research buwendeng@gmail.com"}
NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# ── 1. 用户批注与格式资产无损继承 ───────────────────────────────────────
def harvest_user_assets(xlsx_path: str, cache_dir: str) -> dict:
    """每次写入前先读取现有工作簿，把用户的红字/黄底/U列手写介绍/A2横幅/J2L2阈值永久固化到 JSON"""
    os.makedirs(cache_dir, exist_ok=True)
    ann_path = os.path.join(cache_dir, "user_annotations.json")
    state = {
        "a2_banner": "好一点的板块，主要是软件、生命科学、油、黄金、brokers、半导体设备、电信",
        "thresh_dn": -0.03,
        "thresh_up": 0.03,
        "red_tickers": [],
        "red_yellow_tickers": [],
        "user_notes": {},
        "auto_notes": {},
        "q2_sector_tags": {},
        "q2_verified_earnings": {},  # ticker -> rday (26Q2)
    }
    if os.path.exists(ann_path):
        try:
            saved = json.load(open(ann_path, "r", encoding="utf-8"))
            for k in state:
                if k in saved:
                    state[k] = saved[k]
        except Exception:
            pass

    if not os.path.exists(xlsx_path):
        return state

    wb = openpyxl.load_workbook(xlsx_path, data_only=False)
    if "10_财报日涨跌全表" not in wb.sheetnames:
        return state
    ws = wb["10_财报日涨跌全表"]

    a2 = ws.cell(2, 1).value
    if a2 and isinstance(a2, str) and a2.strip():
        state["a2_banner"] = a2.strip()
    j2 = ws.cell(2, 10).value
    l2 = ws.cell(2, 12).value
    if isinstance(j2, (int, float)) and -0.5 < j2 < 0:
        state["thresh_dn"] = float(j2)
    if isinstance(l2, (int, float)) and 0 < l2 < 0.5:
        state["thresh_up"] = float(l2)

    red_set = set(state["red_tickers"])
    ry_set = set(state["red_yellow_tickers"])
    is_initial_q2 = "2026H1" in str(ws.cell(1, 1).value or "")

    for r in range(5, ws.max_row + 1):
        tk_val = ws.cell(r, 1).value
        if not tk_val:
            continue
        tk = str(tk_val).strip().upper()
        c_tag = ws.cell(r, 3).value
        if c_tag and isinstance(c_tag, str) and c_tag.strip():
            state["q2_sector_tags"].setdefault(tk, c_tag.strip())

        if is_initial_q2:
            rday_v = ws.cell(r, 5).value
            if rday_v:
                state["q2_verified_earnings"][tk] = str(rday_v)[:10]

        c1 = ws.cell(r, 1)
        is_red = bool(c1.font and c1.font.color and c1.font.color.rgb == "FFFF0000")
        is_yel = bool(c1.fill and c1.fill.fill_type == "solid" and c1.fill.fgColor and c1.fill.fgColor.rgb == "FFFFFF00")
        if is_yel:
            ry_set.add(tk)
            red_set.discard(tk)
        elif is_red and tk not in ry_set:
            red_set.add(tk)

        u_val = ws.cell(r, 21).value
        if u_val and isinstance(u_val, str) and u_val.strip():
            u_str = u_val.strip()
            # 若为初始 Q2 表中的 106 条手写介绍，或与上次自动填充不同，则永久归为用户手写资产
            if is_initial_q2 or state["auto_notes"].get(tk) != u_str:
                state["user_notes"][tk] = u_str

    state["red_tickers"] = sorted(red_set)
    state["red_yellow_tickers"] = sorted(ry_set)
    json.dump(state, open(ann_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return state


# ── 2. 板块 Tag 映射（严格对齐 Buwen 的 22 个精简英文 Tag） ─────────────
def map_buwen_sector_tag(tk: str, industry: str, sector: str, q2_tags: dict) -> str:
    if tk in ("MSTR", "COIN", "MARA", "RIOT", "CLSK", "WULF", "HUT", "CIFR", "BITF", "IREN", "CORZ", "BTDR", "GLXY"):
        return "Bitcoin"
    if tk in q2_tags and q2_tags[tk]:
        return q2_tags[tk]
    ind = (industry or "").lower()
    sec = (sector or "").lower()

    if any(k in ind for k in ["bitcoin", "crypto", "blockchain"]):
        return "Bitcoin"
    if any(k in ind for k in ["semiconductor", "solar", "electronic component", "scientific & technical instrument", " wafer"]):
        if "solar" in ind:
            return "Semis"
        return "Semis"
    if any(k in ind for k in ["software", "cyber", "cloud", "information technology"]):
        if "information technology services" in ind or "consulting" in ind:
            return "ITServices"
        return "Software"
    if "information technology services" in ind:
        return "ITServices"
    if any(k in ind for k in ["internet content", "internet retail", "electronic gaming", "interactive media"]):
        return "Internet"
    if any(k in ind for k in ["credit services", "payment", "financial data & stock exchanges"]) and any(w in ind for w in ["credit", "payment"]):
        return "Payments"
    if any(k in ind for k in ["medical", "diagnostics", "health information", "healthcare plans", "medical care", "biotechnology: laboratory", "instruments"]):
        return "Medtech"
    if any(k in ind for k in ["biotechnology", "drug manufacturers", "pharmaceutical"]):
        return "Pharma"
    if any(k in ind for k in ["aerospace", "defense"]):
        return "Defense"
    if any(k in ind for k in ["bank", "capital markets", "asset management", "financial data", "broker", "financial conglomerates", "mortgage"]):
        return "Banks"
    if "insurance" in ind:
        return "Insurance"
    if any(k in ind for k in ["oil & gas", "uranium", "coal", "thermal", "energy"]):
        return "Energy"
    if "utilities" in sec or "utilities" in ind or "nuclear" in ind or "independent power" in ind:
        return "Utilities"
    if "real estate" in sec or "reit" in ind or "real estate" in ind:
        return "Property"
    if any(k in ind for k in ["lodging", "resorts", "travel", "airlines", "cruise", "leisure", "gambling"]):
        if "airlines" in ind:
            return "Travel"
        return "Travel"
    if any(k in ind for k in ["railroads", "trucking", "marine shipping", "integrated freight", "air freight", "logistics"]):
        return "Transport"
    if any(k in ind for k in ["auto manufacturers", "auto parts", "auto & truck", "recreational vehicles"]):
        return "Auto"
    if any(k in ind for k in ["entertainment", "broadcasting", "telecom", "advertising", "publishing"]):
        return "Media"
    if any(k in ind for k in ["computer hardware", "consumer electronics", "communication equipment"]):
        return "Devices"
    if "basic materials" in sec or any(k in ind for k in ["gold", "silver", "copper", "steel", "aluminum", "chemicals", "specialty chemicals", "building materials", "agricultural", "lithium", "mining", "packaging"]):
        return "Materials"
    if any(k in sec for k in ["consumer cyclical", "consumer defensive"]) or any(k in ind for k in ["retail", "apparel", "restaurants", "beverages", "packaged foods", "household", "personal products", "footwear", "furnishings", "residential construction"]):
        return "Consumer"
    if "healthcare" in sec:
        return "Medtech"
    if "financial" in sec:
        return "Banks"
    if "technology" in sec:
        return "Software"
    if "communication" in sec:
        return "Media"
    return "Industrials"


# ── 3. 股票池与日线行情装配（本地价格库 + NASDAQ 实时增补 + Yahoo 增量） ──
def fetch_nasdaq_screener(cache_dir: str) -> dict:
    scr_path = os.path.join(cache_dir, "nasdaq_screener.json")
    today_str = str(dt.date.today())
    cached_rows = {}
    if os.path.exists(scr_path):
        try:
            obj = json.load(open(scr_path, "r", encoding="utf-8"))
            cached_rows = obj.get("data") or {}
            if obj.get("date") == today_str and len(cached_rows) > 1000:
                return cached_rows
        except Exception:
            pass
    for att in range(2):
        try:
            req = urllib.request.Request(
                "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=8000&download=true",
                headers=NASDAQ_HEADERS,
            )
            rows = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))["data"]["rows"]
            out = {}
            for r in rows:
                sym = str(r.get("symbol") or "").strip()
                if not sym or "^" in sym or "/" in sym:
                    continue
                nm = str(r.get("name") or "")
                low = nm.lower()
                if any(w in low for w in ["warrant", "right", "preferred", "depositary shares rep", "units", "notes due", "debenture"]):
                    continue
                try:
                    mc = float(r.get("marketCap") or 0) / 1e9
                    px = float(str(r.get("lastsale") or "0").replace("$", "").replace(",", ""))
                    pct_s = str(r.get("pctchange") or "").replace("%", "").strip()
                    pct = float(pct_s) / 100.0 if pct_s else None
                except Exception:
                    continue
                tk = sym.replace(".", "-").upper()
                out[tk] = {
                    "t": tk,
                    "name": nm,
                    "mc_b": round(mc, 2),
                    "last": px,
                    "pct": pct,
                    "sector": str(r.get("sector") or ""),
                    "industry": str(r.get("industry") or ""),
                }
            if len(out) > 1000:
                json.dump({"date": today_str, "data": out}, open(scr_path, "w", encoding="utf-8"))
            return out
        except Exception:
            time.sleep(2 * (att + 1))
    return cached_rows


def load_all_prices(universe_tks: list, cache_dir: str):
    """读取 us_price_db + 增补股票日线，确保对齐至最新美股已收盘交易日"""
    # 锚定 SPY 最新收盘交易日
    spy_df = yf.Ticker("SPY").history(period="15d", auto_adjust=False)
    spy_close = spy_df["Close"].dropna()
    target_last_day = pd.Timestamp(spy_close.index[-1].date())

    series_map = {}
    stale_or_missing = []

    for tk in universe_tks:
        pq = os.path.join(PDB_PRICES_DIR, f"{tk}.parquet")
        if os.path.exists(pq):
            try:
                df = pd.read_parquet(pq, columns=["close", "adj_close", "volume"])
                df = df.dropna(subset=["close"])
                if not df.empty:
                    df.index = pd.to_datetime([d.date() if hasattr(d, "date") else pd.Timestamp(d).date() for d in df.index])
                    df = df[~df.index.duplicated(keep="last")].sort_index()
                    # 只取近 14 个月算 52 周高点与 6 个月跳涨，极致省内存
                    df = df[df.index >= pd.Timestamp("2025-09-01")]
                    series_map[tk] = df
                    if df.index[-1] < target_last_day:
                        stale_or_missing.append(tk)
                    continue
            except Exception:
                pass
        stale_or_missing.append(tk)

    # 读取本地 extra_prices 缓存
    extra_pkl = os.path.join(cache_dir, "extra_prices.pkl")
    extra_cache = pd.read_pickle(extra_pkl) if os.path.exists(extra_pkl) else {}

    still_need_full = []
    still_need_recent = []
    checked_today = extra_cache.get("_checked_date") == str(dt.date.today())
    for tk in stale_or_missing:
        if tk in extra_cache and isinstance(extra_cache[tk], pd.DataFrame) and not extra_cache[tk].empty:
            df_ex = extra_cache[tk]
            if tk not in series_map or df_ex.index[-1] > series_map[tk].index[-1]:
                series_map[tk] = df_ex
            if series_map[tk].index[-1] >= target_last_day or checked_today:
                continue
            still_need_recent.append(tk)
        elif tk in series_map:
            if not checked_today:
                still_need_recent.append(tk)
        elif not checked_today:
            still_need_full.append(tk)
        if False:
            df = extra_cache[tk]
            series_map[tk] = df
            if df.index[-1] < target_last_day:
                still_need_recent.append(tk)
        else:
            still_need_full.append(tk)

    def batch_pull(tks: list, start_date: str):
        if not tks:
            return
        for i in range(0, len(tks), 80):
            batch = tks[i:i + 80]
            for att in range(3):
                try:
                    raw = yf.download(
                        batch,
                        start=start_date,
                        progress=False,
                        auto_adjust=False,
                        threads=True,
                        group_by="ticker",
                    )
                    if raw is None or raw.empty:
                        break
                    for btk in batch:
                        try:
                            sub = raw[btk] if len(batch) > 1 else raw
                            sub = sub[["Close", "Adj Close", "Volume"]].rename(
                                columns={"Close": "close", "Adj Close": "adj_close", "Volume": "volume"}
                            )
                            sub = sub.dropna(subset=["close"])
                            if sub.empty:
                                continue
                            sub.index = pd.to_datetime([d.date() for d in sub.index])
                            sub = sub[~sub.index.duplicated(keep="last")].sort_index()
                            if btk in series_map and start_date > "2025-10-01":
                                old = series_map[btk]
                                merged = pd.concat([old[old.index < sub.index[0]], sub]).sort_index()
                                merged = merged[~merged.index.duplicated(keep="last")]
                                series_map[btk] = merged
                            else:
                                series_map[btk] = sub
                            extra_cache[btk] = series_map[btk]
                        except Exception:
                            continue
                    break
                except Exception:
                    time.sleep(3 * (att + 1))

    if still_need_full:
        print(f"[行情] 首次补拉全段日线: {len(still_need_full)} 只...")
        batch_pull(still_need_full, "2025-09-01")
    if still_need_recent:
        start_recent = str((target_last_day - pd.Timedelta(days=12)).date())
        print(f"[行情] 增量补齐最新交易日 ({target_last_day.date()}): {len(still_need_recent)} 只...")
        batch_pull(still_need_recent, start_recent)

    extra_cache["_checked_date"] = str(dt.date.today())
    pd.to_pickle(extra_cache, extra_pkl)
    return series_map, target_last_day


# ── 4. 财报日与财报季度（26Q1 / 26Q2 / 26Q3 / 26Q4）三重权威交叉核验 ──────
def period_end_to_qlabel(period_date: dt.date) -> str:
    """统一物理财季边界映射，100% 兼容标准自然季、NVDA/CRM(1/4/7/10)、零售4-5-4(8月初=Q2)与MU/ORCL(8月末=Q3)"""
    y, m, d = period_date.year, period_date.month, period_date.day
    if (2, 11) <= (m, d) <= (5, 15):
        return f"{y % 100:02d}Q1"
    elif (5, 16) <= (m, d) <= (8, 10):
        return f"{y % 100:02d}Q2"
    elif (8, 11) <= (m, d) <= (11, 10):
        return f"{y % 100:02d}Q3"
    elif (m, d) >= (11, 11):
        return f"{y % 100:02d}Q4"
    else:
        return f"{(y - 1) % 100:02d}Q4"


def nasdaq_fq_to_qlabel(fq_str: str, edate_str: str) -> str:
    """把 NASDAQ 日历的 'Jun/2026', 'Aug/2026' + 披露日 转为精确的 26Q2 / 26Q3"""
    ed = dt.date.fromisoformat(edate_str[:10])
    if fq_str and "/" in fq_str:
        parts = fq_str.strip().split("/")
        mon_s = parts[0][:3].lower()
        if mon_s in MONTH_MAP and parts[1].isdigit():
            m = MONTH_MAP[mon_s]
            y = int(parts[1])
            if m in (3, 4):
                return f"{y % 100:02d}Q1"
            if m in (6, 7):
                return f"{y % 100:02d}Q2"
            if m in (9, 10):
                return f"{y % 100:02d}Q3"
            if m == 12:
                return f"{y % 100:02d}Q4"
            if m == 1:
                return f"{(y - 1) % 100:02d}Q4"
            # 2, 5, 8, 11 月利用披露日区分月初结账（零售52周历）与月末结账（MU/ORCL/COST）
            if m == 5:
                return f"{y % 100:02d}Q1" if ed <= dt.date(y, 6, 12) else f"{y % 100:02d}Q2"
            if m == 8:
                return f"{y % 100:02d}Q2" if ed <= dt.date(y, 9, 5) else f"{y % 100:02d}Q3"
            if m == 11:
                return f"{y % 100:02d}Q3" if ed <= dt.date(y, 12, 10) else f"{y % 100:02d}Q4"
            if m == 2:
                return f"{(y - 1) % 100:02d}Q4" if ed <= dt.date(y, 3, 12) else f"{y % 100:02d}Q1"
    # 兜底：按披露日期推算对应财报季
    y, m, d = ed.year, ed.month, ed.day
    if (3, 16) <= (m, d) <= (6, 15):
        return f"{y % 100:02d}Q1"
    elif (6, 16) <= (m, d) <= (9, 15):
        return f"{y % 100:02d}Q2"
    elif (9, 16) <= (m, d) <= (12, 15):
        return f"{y % 100:02d}Q3"
    elif (m, d) >= (12, 16):
        return f"{y % 100:02d}Q4"
    else:
        return f"{(y - 1) % 100:02d}Q4"


def update_nasdaq_earnings_calendar(start_date: dt.date, end_date: dt.date, cache_dir: str) -> dict:
    """增量更新 NASDAQ 每日财报日历缓存 {date_str: [rows]}"""
    cal_path = os.path.join(cache_dir, "nasdaq_earnings_cal.json")
    cal = json.load(open(cal_path, "r", encoding="utf-8")) if os.path.exists(cal_path) else {}

    # 首次运行时直接吸收 跳涨板块_2026-10-19/earn_cal.json 中已抓好的 08-24..10-16 数据
    seed_cal = os.path.join(D1019_DIR, "earn_cal.json")
    if not cal and os.path.exists(seed_cal):
        by_d = defaultdict(list)
        for r in json.load(open(seed_cal, "r", encoding="utf-8")):
            if r.get("_date"):
                by_d[r["_date"]].append({
                    "symbol": str(r.get("symbol") or "").strip().replace(".", "-").upper(),
                    "time": str(r.get("time") or ""),
                    "fq": str(r.get("fiscalQuarterEnding") or r.get("fq") or ""),
                })
        cal.update(by_d)

    need_dates = []
    cur = start_date
    recent_cutoff = end_date - dt.timedelta(days=3)
    while cur <= end_date:
        if cur.weekday() < 5:
            ds = str(cur)
            if ds not in cal or cur >= recent_cutoff:
                need_dates.append(ds)
        cur += dt.timedelta(days=1)

    if need_dates:
        print(f"[财报日历] 同步 NASDAQ 官方财报日历: {len(need_dates)} 个交易日...")
        def fetch_one_day(ds: str):
            for att in range(3):
                try:
                    url = f"https://api.nasdaq.com/api/calendar/earnings?date={ds}"
                    req = urllib.request.Request(url, headers=NASDAQ_HEADERS)
                    j = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
                    rows = (j.get("data") or {}).get("rows") or []
                    slim = []
                    for r in rows:
                        slim.append({
                            "symbol": str(r.get("symbol") or "").strip().replace(".", "-").upper(),
                            "time": str(r.get("time") or ""),
                            "fq": str(r.get("fiscalQuarterEnding") or ""),
                        })
                    return ds, slim
                except Exception:
                    time.sleep(2 * (att + 1))
            return ds, None

        with cf.ThreadPoolExecutor(max_workers=6) as ex:
            for ds, rows in ex.map(fetch_one_day, need_dates):
                if rows is not None:
                    cal[ds] = rows
        json.dump(cal, open(cal_path, "w", encoding="utf-8"), ensure_ascii=False)

    return cal


def update_sec_8k_for_jump_tickers(jump_tickers: list, latest_jump_by_tk: dict, cache_dir: str) -> dict:
    """对发生跳涨的个股拉取 SEC EDGAR 8-K Item 2.02 精确时间戳与 10-Q/10-K reportDate"""
    sec_path = os.path.join(cache_dir, "sec_8k_earnings.json")
    sec_cache = json.load(open(sec_path, "r", encoding="utf-8")) if os.path.exists(sec_path) else {}

    cik_path = os.path.join(cache_dir, "sec_cik_map.json")
    cik_map = {}
    if os.path.exists(cik_path) and (time.time() - os.path.getmtime(cik_path) < 7 * 86400):
        cik_map = json.load(open(cik_path, "r", encoding="utf-8"))
    else:
        try:
            raw = urllib.request.urlopen(urllib.request.Request("https://www.sec.gov/files/company_tickers.json", headers=SEC_UA), timeout=40).read()
            ct = json.loads(raw.decode("utf-8"))
            cik_map = {str(v["ticker"]).replace(".", "-").upper(): int(v["cik_str"]) for v in ct.values()}
            json.dump(cik_map, open(cik_path, "w", encoding="utf-8"))
        except Exception as e:
            print(f"[SEC] CIK 映射拉取警告: {e}")

    to_fetch = []
    for tk in jump_tickers:
        if tk not in cik_map:
            continue
        cached = sec_cache.get(tk)
        last_j = latest_jump_by_tk.get(tk, "")
        if not cached or cached.get("asof", "") < last_j:
            to_fetch.append(tk)

    if to_fetch:
        print(f"[SEC 8-K] 核验跳涨股 8-K Item 2.02 财报时间戳: {len(to_fetch)} 只...")
        asof_today = str(dt.date.today())

        def pull_sec_one(tk: str):
            cik = cik_map[tk]
            for att in range(3):
                try:
                    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
                    raw = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=40).read()
                    rc = json.loads(raw.decode("utf-8"))["filings"]["recent"]
                    e202 = []
                    q_periods = []
                    for fm, fd, rd, it, acc in zip(
                        rc.get("form", []),
                        rc.get("filingDate", []),
                        rc.get("reportDate", []),
                        rc.get("items", []),
                        rc.get("acceptanceDateTime", []),
                    ):
                        if fd < "2026-04-01":
                            continue
                        if fm in ("8-K", "8-K/A") and "2.02" in str(it or ""):
                            try:
                                u = dt.datetime.fromisoformat(acc.replace("Z", "+00:00")).astimezone(ET_TZ)
                                e202.append({
                                    "date_et": str(u.date()),
                                    "time_et": u.strftime("%H:%M"),
                                    "report_date": str(rd or ""),
                                })
                            except Exception:
                                e202.append({"date_et": fd, "time_et": "16:30", "report_date": str(rd or "")})
                        elif fm in ("10-Q", "10-K", "20-F", "40-F") and rd:
                            q_periods.append({"filing_date": fd, "report_date": rd, "form": fm})
                    time.sleep(0.12)
                    return tk, {"asof": asof_today, "e202": e202, "q_periods": q_periods}
                except Exception:
                    time.sleep(1.5 * (att + 1))
            return tk, None

        with cf.ThreadPoolExecutor(max_workers=5) as ex:
            for tk, data in ex.map(pull_sec_one, to_fetch):
                if data is not None:
                    sec_cache[tk] = data
        json.dump(sec_cache, open(sec_path, "w", encoding="utf-8"), ensure_ascii=False)

    return sec_cache


def build_earnings_reaction_lookup(
    jump_tickers: list,
    trading_days: pd.DatetimeIndex,
    nasdaq_cal: dict,
    sec_cache: dict,
    q2_verified: dict,
) -> dict:
    """
    构建 (ticker, reaction_day_str) -> (quarter_label, session_str) 精确字典
    同时支持盘前（<16:00 ET 当日反应）与盘后（>=16:00 ET 次一交易日反应）
    """
    def next_tday(d_str: str, inclusive: bool = True):
        ts = pd.Timestamp(d_str[:10])
        idx = trading_days.searchsorted(ts, side="left" if inclusive else "right")
        return str(trading_days[idx].date()) if idx < len(trading_days) else None

    lookup = {}  # (tk, rday_str) -> (qlabel, session)
    tentative_keys = set()

    # 1) 先载入 NASDAQ 官方日历（含财季截止月 fq，覆盖 ADR/FPI 与美股本土公司）
    nasdaq_fq_hint = {}  # (tk, edate_str) -> qlabel
    for ds, rows in nasdaq_cal.items():
        for r in rows:
            tk = str(r.get("symbol") or "").strip().replace(".", "-").upper()
            tm = r.get("time", "")
            fq = r.get("fq") or r.get("fiscalQuarterEnding") or ""
            qlab = nasdaq_fq_to_qlabel(fq, ds)
            nasdaq_fq_hint[(tk, ds)] = qlab
            if tm == "time-pre-market":
                rd = next_tday(ds, inclusive=True)
                if rd:
                    lookup[(tk, rd)] = (qlab, "盘前")
                    tentative_keys.discard((tk, rd))
            elif tm == "time-after-hours":
                rd = next_tday(ds, inclusive=False)
                if rd:
                    lookup[(tk, rd)] = (qlab, "盘后")
                    tentative_keys.discard((tk, rd))
            else:
                # time-not-supplied: 暂记候选，稍后 SEC 8-K 会清除假候选并覆盖精确反应日；若无 8-K（如 FPI），同时覆盖当日与次日反应
                rd_same = next_tday(ds, inclusive=True)
                rd_next = next_tday(ds, inclusive=False)
                if rd_same and (tk, rd_same) not in lookup:
                    lookup[(tk, rd_same)] = (qlab, "盘前")
                    tentative_keys.add((tk, rd_same))
                if rd_next and (tk, rd_next) not in lookup:
                    lookup[(tk, rd_next)] = (qlab, "盘后")
                    tentative_keys.add((tk, rd_next))

    # 2) 叠加 SEC EDGAR 8-K Item 2.02（分钟级精确时间戳 + 10-Q/10-K reportDate 校验）
    for tk in jump_tickers:
        sc = sec_cache.get(tk)
        if not sc:
            continue
        q_periods = sc.get("q_periods", [])
        for ev in sc.get("e202", []):
            d_et = ev["date_et"]
            t_et = ev["time_et"]
            same = t_et < "16:00"
            rd = next_tday(d_et, inclusive=same)
            if not rd:
                continue
            sess = "盘前" if t_et < "09:30" else ("盘中" if same else "盘后")

            # 优先匹配同次财报前后 15 天内提交的 10-Q/10-K reportDate
            qlab = None
            ed_dt = dt.date.fromisoformat(d_et)
            best_qp = None
            for qp in q_periods:
                try:
                    f_dt = dt.date.fromisoformat(qp["filing_date"])
                    if -5 <= (f_dt - ed_dt).days <= 20:
                        best_qp = dt.date.fromisoformat(qp["report_date"])
                        break
                except Exception:
                    continue
            if best_qp:
                qlab = period_end_to_qlabel(best_qp)
            else:
                # 查前后 1 天的 NASDAQ fq 提示
                for delta in (0, -1, 1):
                    cand_d = str(ed_dt + dt.timedelta(days=delta))
                    if (tk, cand_d) in nasdaq_fq_hint:
                        qlab = nasdaq_fq_hint[(tk, cand_d)]
                        break
            if not qlab:
                qlab = nasdaq_fq_to_qlabel("", d_et)

            for delta in (-2, -1, 0, 1, 2):
                cand_rd = str(ed_dt + dt.timedelta(days=delta))
                if (tk, cand_rd) in tentative_keys:
                    lookup.pop((tk, cand_rd), None)
                    tentative_keys.discard((tk, cand_rd))
            lookup[(tk, rd)] = (qlab, sess)

    # 3) 注入原 Q2 表已人工验证的 26Q2 反应日锚点
    for tk, rd in q2_verified.items():
        if rd >= "2026-05-01":
            lookup.setdefault((tk, rd), ("26Q2", "盘后"))

    return lookup


# ── 5. 公司元数据、USD 财务指标与精简中文主业补齐 ────────────────────────
def fetch_fx_to_usd() -> dict:
    fx = {"USD": 1.0}
    pairs = {
        "TWD": "TWDUSD=X", "EUR": "EURUSD=X", "JPY": "JPYUSD=X", "GBP": "GBPUSD=X",
        "CNY": "CNYUSD=X", "CAD": "CADUSD=X", "CHF": "CHFUSD=X", "DKK": "DKKUSD=X",
        "SEK": "SEKUSD=X", "AUD": "AUDUSD=X", "KRW": "KRWUSD=X", "INR": "INRUSD=X",
        "BRL": "BRLUSD=X", "ILS": "ILSUSD=X", "MXN": "MXNUSD=X", "HKD": "HKDUSD=X",
        "SGD": "SGDUSD=X", "NOK": "NOKUSD=X", "ZAR": "ZARUSD=X", "ARS": "ARSUSD=X",
    }
    try:
        raw = yf.download(list(pairs.values()), period="5d", progress=False, auto_adjust=False)["Close"]
        for ccy, sym in pairs.items():
            if sym in raw.columns:
                s = raw[sym].dropna()
                if not s.empty:
                    fx[ccy] = float(s.iloc[-1])
    except Exception:
        pass
    # 稳健兜底汇率（仅当雅虎汇率序列偶发为空时生效）
    fallbacks = {
        "TWD": 0.0315, "EUR": 1.08, "JPY": 0.0066, "GBP": 1.29, "CNY": 0.139,
        "CAD": 0.72, "CHF": 1.13, "DKK": 0.145, "SEK": 0.095, "AUD": 0.66,
        "KRW": 0.00073, "INR": 0.0119, "BRL": 0.175, "ILS": 0.27, "HKD": 0.128,
    }
    for k, v in fallbacks.items():
        fx.setdefault(k, v)
    return fx


INDUSTRY_ZH_SHORT = {
    "Semiconductors": "半导体芯片",
    "Semiconductor Equipment & Materials": "半导体设备材料",
    "Software - Infrastructure": "基础设施软件",
    "Software - Application": "企业应用软件",
    "Information Technology Services": "IT咨询与外包",
    "Computer Hardware": "计算机与服务器",
    "Communication Equipment": "通信与网络设备",
    "Electronic Components": "电子元器件",
    "Scientific & Technical Instruments": "科学精密仪器",
    "Solar": "光伏组件与逆变器",
    "Internet Content & Information": "互联网内容平台",
    "Internet Retail": "电商平台",
    "Electronic Gaming & Multimedia": "游戏与数字娱乐",
    "Biotechnology": "创新生物医药",
    "Drug Manufacturers - General": "大型跨国制药",
    "Drug Manufacturers - Specialty & Generic": "特色与仿制药",
    "Diagnostics & Research": "基因诊断与CRO",
    "Medical Devices": "医疗器械",
    "Medical Instruments & Supplies": "医疗耗材与器械",
    "Health Information Services": "医疗数字化服务",
    "Healthcare Plans": "医疗保险管理",
    "Medical Care Facilities": "连锁医疗服务",
    "Aerospace & Defense": "航空航天与军工",
    "Specialty Industrial Machinery": "专用工业机械",
    "Engineering & Construction": "工程总包与基建",
    "Electrical Equipment & Parts": "电网与电气设备",
    "Building Products & Equipment": "暖通与建材设备",
    "Farm & Heavy Construction Machinery": "工程与农用机械",
    "Banks - Regional": "区域商业银行",
    "Banks - Diversified": "大型综合银行",
    "Capital Markets": "投行与券商资管",
    "Asset Management": "资产管理机构",
    "Financial Data & Stock Exchanges": "交易所与金融数据",
    "Credit Services": "支付与消费信贷",
    "Oil & Gas E&P": "油气勘探开发",
    "Oil & Gas Midstream": "油气管道储运",
    "Oil & Gas Equipment & Services": "油服与钻完井",
    "Oil & Gas Refining & Marketing": "炼油与成品油",
    "Uranium": "天然铀矿开采",
    "Gold": "金矿开采",
    "Copper": "铜矿开采",
    "Other Industrial Metals & Mining": "工业金属矿业",
    "Specialty Chemicals": "特种化学品",
    "Utilities - Independent Power Producers": "独立发电与核电",
    "Utilities - Regulated Electric": "公用事业电网",
    "Auto Manufacturers": "整车制造",
    "Auto Parts": "汽车零部件",
    "Apparel Retail": "品牌服饰零售",
    "Specialty Retail": "专业连锁零售",
    "Restaurants": "连锁餐饮",
    "Travel Services": "在线旅游预订",
    "Airlines": "航空客运",
    "Marine Shipping": "远洋航运",
    "Trucking": "公路货运物流",
}


def update_financials_and_meta(
    jump_tickers: list,
    latest_jump_by_tk: dict,
    nasdaq_map: dict,
    cache_dir: str,
) -> dict:
    """拉取并缓存跳涨个股的最新季度营收（折算百万美元）、净利率%、报告期末、市值与业务简介"""
    fin_path = os.path.join(cache_dir, "financials_meta.json")
    fin_cache = json.load(open(fin_path, "r", encoding="utf-8")) if os.path.exists(fin_path) else {}

    # 载入本地已有 tags.json / desc_cache.json / info.json 加速并提升中文主业准确度
    tags_1019 = {}
    desc_1019 = {}
    info_1019 = {}
    for fn, target in [("tags.json", tags_1019), ("desc_cache.json", desc_1019), ("info.json", info_1019)]:
        fp = os.path.join(D1019_DIR, fn)
        if os.path.exists(fp):
            try:
                target.update(json.load(open(fp, "r", encoding="utf-8")))
            except Exception:
                pass

    today_str = str(dt.date.today())
    stale_cutoff = str(dt.date.today() - dt.timedelta(days=7))
    to_fetch = []
    for tk in jump_tickers:
        c = fin_cache.get(tk)
        lj = latest_jump_by_tk.get(tk, "")
        if not c or c.get("fetched_at", "") < stale_cutoff or c.get("fetched_at", "") < lj:
            to_fetch.append(tk)

    if to_fetch:
        print(f"[基本面] 更新跳涨股最新季报营收/净利率/市值 (含跨币种折 USD): {len(to_fetch)} 只...")
        fx = fetch_fx_to_usd()

        def fetch_fin_one(tk: str):
            for att in range(2):
                try:
                    yt = yf.Ticker(tk)
                    inf = yt.info or {}
                    ccy = str(inf.get("financialCurrency") or "USD").upper()
                    rate = fx.get(ccy, 1.0)

                    q_end, q_rev_m, q_nm = None, None, None
                    qi = yt.quarterly_income_stmt
                    if qi is not None and not qi.empty:
                        for col in qi.columns:
                            rev = None
                            for rk in ("Total Revenue", "Operating Revenue"):
                                if rk in qi.index and pd.notna(qi.loc[rk, col]):
                                    rev = float(qi.loc[rk, col])
                                    break
                            if rev and rev > 0:
                                q_end = str(col)[:10]
                                q_rev_m = round((rev * rate) / 1e6, 1)
                                ni = None
                                for nk in ("Net Income", "Net Income Common Stockholders"):
                                    if nk in qi.index and pd.notna(qi.loc[nk, col]):
                                        ni = float(qi.loc[nk, col])
                                        break
                                if ni is not None:
                                    q_nm = float(ni / rev)
                                break

                    mc_b = None
                    if inf.get("marketCap"):
                        mc_b = round(float(inf["marketCap"]) / 1e9, 1)
                    elif tk in nasdaq_map and nasdaq_map[tk].get("mc_b"):
                        mc_b = round(float(nasdaq_map[tk]["mc_b"]), 1)

                    return tk, {
                        "fetched_at": today_str,
                        "name": str(inf.get("longName") or inf.get("shortName") or nasdaq_map.get(tk, {}).get("name") or tk),
                        "sector": str(inf.get("sector") or info_1019.get(tk, {}).get("sector") or nasdaq_map.get(tk, {}).get("sector") or ""),
                        "industry": str(inf.get("industry") or info_1019.get(tk, {}).get("industry") or nasdaq_map.get(tk, {}).get("industry") or ""),
                        "q_end": q_end,
                        "q_rev_m": q_rev_m,
                        "q_nm": q_nm,
                        "mc_b": mc_b,
                        "ccy": ccy,
                    }
                except Exception:
                    time.sleep(1.0)
            return tk, {
                "fetched_at": today_str,
                "name": str(info_1019.get(tk, {}).get("longName") or nasdaq_map.get(tk, {}).get("name") or tk),
                "sector": str(info_1019.get(tk, {}).get("sector") or nasdaq_map.get(tk, {}).get("sector") or ""),
                "industry": str(info_1019.get(tk, {}).get("industry") or nasdaq_map.get(tk, {}).get("industry") or ""),
                "q_end": None,
                "q_rev_m": None,
                "q_nm": None,
                "mc_b": nasdaq_map.get(tk, {}).get("mc_b"),
                "ccy": "USD",
            }

        with cf.ThreadPoolExecutor(max_workers=10) as ex:
            for tk, rec in ex.map(fetch_fin_one, to_fetch):
                fin_cache[tk] = rec
        json.dump(fin_cache, open(fin_path, "w", encoding="utf-8"), ensure_ascii=False)

    # 实时用当日 NASDAQ 市值刷新 mc_b（保证每日市值鲜活）
    for tk in jump_tickers:
        if tk in fin_cache and tk in nasdaq_map and nasdaq_map[tk].get("mc_b"):
            fin_cache[tk]["mc_b"] = round(float(nasdaq_map[tk]["mc_b"]), 1)
        # 组装自动精简中文主业（供无用户手写笔记的标的兜底）
        if tk in fin_cache:
            zh = (
                (tags_1019.get(tk) or {}).get("zhuye")
                or (tags_1019.get(tk) or {}).get("what")
                or (desc_1019.get(tk) or {}).get("what")
                or INDUSTRY_ZH_SHORT.get(fin_cache[tk].get("industry", ""), "")
            )
            zh = str(zh or "").replace("-", " ").replace("—", " ").strip()
            fin_cache[tk]["auto_zh"] = zh

    return fin_cache


# ── 6. OOXML 字节级无损写入引擎（100% 保护其他 Sheet/图表/截图） ────────
class SharedStringTable:
    """原字节流零重序列化，仅在 </sst> 前追加新字符串，确保索引 0..N-1 与命名空间 100% 原生无损"""
    def __init__(self, xml_bytes: bytes):
        self.ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        self.orig_xml = xml_bytes.decode("utf-8")
        assert self.orig_xml.rstrip().endswith("</sst>"), "Unexpected sharedStrings tail"
        root = ET.fromstring(xml_bytes)
        si_list = root.findall(f"{{{self.ns}}}si")
        self.orig_len = len(si_list)
        self.appended_xml = []
        self.str_to_idx = {}
        for idx, si in enumerate(si_list):
            t_el = si.find(f"{{{self.ns}}}t")
            if t_el is not None and len(list(si)) == 1:
                txt_val = t_el.text or ""
                self.str_to_idx.setdefault(txt_val, idx)

    def idx(self, s: str) -> int:
        s = "" if s is None else str(s)
        if s in self.str_to_idx:
            return self.str_to_idx[s]
        new_i = self.orig_len + len(self.appended_xml)
        esc = xml_escape(s)
        preserve = ' xml:space="preserve"' if (s.startswith(" ") or s.endswith(" ") or "\n" in s) else ""
        self.appended_xml.append(f"<si><t{preserve}>{esc}</t></si>")
        self.str_to_idx[s] = new_i
        return new_i

    def to_bytes(self) -> bytes:
        total_u = self.orig_len + len(self.appended_xml)
        cut = self.orig_xml.rfind("</sst>")
        prefix = self.orig_xml[:cut]
        prefix = re.sub(r'uniqueCount="\d+"', f'uniqueCount="{total_u}"', prefix, count=1)
        prefix = re.sub(r'count="\d+"', f'count="{total_u}"', prefix, count=1)
        return (prefix + "".join(self.appended_xml) + "</sst>").encode("utf-8")


def cell_s(coord: str, sst: SharedStringTable, val: str, style_id=None) -> str:
    if val is None or val == "":
        return ""
    s_attr = f' s="{style_id}"' if style_id is not None else ""
    return f'<c r="{coord}"{s_attr} t="s"><v>{sst.idx(val)}</v></c>'


def cell_n(coord: str, val, style_id=None) -> str:
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        return ""
    s_attr = f' s="{style_id}"' if style_id is not None else ""
    if isinstance(val, int):
        return f'<c r="{coord}"{s_attr}><v>{val}</v></c>'
    return f'<c r="{coord}"{s_attr}><v>{repr(float(val))}</v></c>'


def cell_f_num(coord: str, formula: str, cached_val: float, style_id=None) -> str:
    s_attr = f' s="{style_id}"' if style_id is not None else ""
    v_tag = "" if (cached_val is None or np.isnan(cached_val)) else f"<v>{repr(float(cached_val))}</v>"
    return f'<c r="{coord}"{s_attr}><f>{xml_escape(formula)}</f>{v_tag}</c>'


def cell_f_str(coord: str, formula: str, cached_str: str, style_id=None) -> str:
    s_attr = f' s="{style_id}"' if style_id is not None else ""
    return f'<c r="{coord}"{s_attr} t="str"><f>{xml_escape(formula)}</f><v>{xml_escape(cached_str)}</v></c>'


def render_sheet1_cover(sst: SharedStringTable, w0_str: str, asof_str: str, total_rows: int, uniq_tks: int, earn_rows: int) -> bytes:
    kv = [
        ("类型", "选股 · 每日更新活表"),
        ("市场", "美股（市值 50 亿美元以上及重点跟踪池）"),
        ("监测范围", f"近半年滚动窗口（{w0_str} 至 {asof_str}），全时间段单日跳涨 10% 以上"),
        ("财报标注", f"共 {total_rows} 次跳涨（{uniq_tks} 家公司），其中财报跳涨 {earn_rows} 次（D 列标明如 26Q2、26Q3）"),
        ("负责与刷新", "us · 每日美股收盘后自动更新"),
        ("最后更新", str(dt.date.today())),
    ]
    rows_xml = [f'<row r="1" spans="2:3" ht="20"><c r="B1" s="28" t="s"><v>{sst.idx(f"美股近半年全时间段跳涨监测（含财报季标注） · {total_rows}次")}</v></c></row>']
    for idx, (k, v) in enumerate(kv):
        r = 3 + idx
        s_v = "30" if idx == 4 else "29"
        rows_xml.append(
            f'<row r="{r}" spans="2:3" ht="18">'
            f'{cell_s(f"B{r}", sst, k, 29)}'
            f'{cell_s(f"C{r}", sst, v, s_v)}'
            f'</row>'
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="B1:C{2 + len(kv)}"/>'
        '<sheetViews><sheetView showGridLines="0" workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr baseColWidth="10" defaultColWidth="8.83203125" defaultRowHeight="15"/>'
        '<cols>'
        '<col min="1" max="1" width="1.83203125" customWidth="1"/>'
        '<col min="2" max="2" width="14" customWidth="1"/>'
        '<col min="3" max="3" width="90" customWidth="1"/>'
        '</cols>'
        f'<sheetData>{"".join(rows_xml)}</sheetData>'
        '<pageMargins left="0.75" right="0.75" top="1" bottom="1" header="0.5" footer="0.5"/>'
        '</worksheet>'
    )
    return xml.encode("utf-8")


def render_sheet2_main(
    sst: SharedStringTable,
    records: list,
    user_state: dict,
    w0_str: str,
    asof_str: str,
) -> bytes:
    """严格按原表 21 列坐标系与样式索引渲染主表（D列财报季与E列跳涨日显式展开，其余隐藏列维持原状）"""
    red_set = set(user_state["red_tickers"])
    ry_set = set(user_state["red_yellow_tickers"])
    thresh_dn = user_state["thresh_dn"]
    thresh_up = user_state["thresh_up"]

    title_str = f"美股近半年跳涨监测（全时间段单日涨10%以上，财报季单独标注），{w0_str} 至 {asof_str}"
    rows_xml = []

    # Row 1: Title
    rows_xml.append(f'<row r="1" spans="1:21">{cell_s("A1", sst, title_str)}</row>')

    # Row 2: Buwen's A2 banner + I2:L2 yellow thresholds
    rows_xml.append(
        f'<row r="2" spans="1:21">'
        f'{cell_s("A2", sst, user_state["a2_banner"])}'
        f'{cell_s("I2", sst, "跌幅标准")}'
        f'{cell_n("J2", thresh_dn, 20)}'
        f'{cell_s("K2", sst, "涨幅标准")}'
        f'{cell_n("L2", thresh_up, 20)}'
        f'</row>'
    )

    # Row 4: Exact 21-column headers matching Buwen's schema (D4=财报季, E4=跳涨日)
    headers = [
        ("A4", "代码", 3), ("B4", "公司", 3), ("C4", "板块Tag", 3),
        ("D4", "财报季", 3), ("E4", "跳涨日", 3), ("F4", "时点", 3),
        ("G4", "前日收盘$", 4), ("H4", "跳涨日收盘$", 4), ("I4", "当日涨跌%", 4),
        ("J4", "现价$", 4), ("K4", "跳涨后至今%", 4), ("L4", "结局", 4),
        ("M4", "距52周高%", 4), ("N4", "口径", 4),
        ("O4", "报告期末", 12), ("P4", "季度营收$M", 12), ("Q4", "净利率%", 12),
        ("R4", "市值$B", 12), ("S4", "财务口径", 12),
    ]
    rows_xml.append('<row r="4" spans="1:21">' + "".join(cell_s(c, sst, h, st) for c, h, st in headers) + '</row>')

    # Rows 5..N: Data rows (latest date on top, descending by jump %)
    for idx, rec in enumerate(records):
        r = 5 + idx
        tk = rec["tk"]
        ab_style = 19 if tk in ry_set else (18 if tk in red_set else 1)

        # 计算结局缓存值（与公式 100% 一致）
        pct = rec["c"] / rec["pc"] - 1.0
        since = rec["now"] / rec["c"] - 1.0
        off52 = rec["now"] / rec["hi52"] - 1.0 if rec["hi52"] > 0 else 0.0
        if rec["date"] >= asof_str:
            outcome = "待观察"
        elif since > thresh_up and pct > thresh_dn:
            outcome = "守住，续涨"
        elif since < thresh_dn and pct > thresh_up:
            outcome = "当日上涨，回吐"
        elif since > thresh_up and pct < thresh_dn:
            outcome = "当日下跌，反涨"
        elif since < thresh_dn:
            outcome = "下跌"
        else:
            outcome = "持平"

        f_outcome = (
            f'IF(E{r}>="{asof_str}","待观察",'
            f'IF(AND(K{r}>$L$2,I{r}>$J$2),"守住，续涨",'
            f'IF(AND(K{r}<$J$2,I{r}>$L$2),"当日上涨，回吐",'
            f'IF(AND(K{r}>$L$2,I{r}<$J$2),"当日下跌，反涨",'
            f'IF(K{r}<$J$2,"下跌","持平")))))'
        )

        c_parts = [
            cell_s(f"A{r}", sst, tk, ab_style),
            cell_s(f"B{r}", sst, rec["name"], ab_style),
            cell_s(f"C{r}", sst, rec["tag"], 1),
            cell_s(f"D{r}", sst, rec["qlabel"], 1) if rec["qlabel"] else "",
            cell_s(f"E{r}", sst, rec["date"], 1),
            cell_s(f"F{r}", sst, rec["session"], 1) if rec["session"] else "",
            cell_n(f"G{r}", round(rec["pc"], 4), 5),
            cell_n(f"H{r}", round(rec["c"], 4), 5),
            cell_f_num(f"I{r}", f"H{r}/G{r}-1", pct, 2),
            cell_n(f"J{r}", round(rec["now"], 4), 5),
            cell_f_num(f"K{r}", f"J{r}/H{r}-1", since, 2),
            cell_f_str(f"L{r}", f_outcome, outcome, 11),
            cell_f_num(f"M{r}", f"J{r}/{round(rec['hi52'], 2)}-1", off52, 2),
            cell_s(f"N{r}", sst, "财报跳涨" if rec["qlabel"] else "日常跳涨", 1),
            cell_s(f"O{r}", sst, rec["q_end"], 13) if rec["q_end"] else "",
            cell_n(f"P{r}", rec["q_rev_m"], 14) if rec["q_rev_m"] is not None else "",
            cell_n(f"Q{r}", rec["q_nm"], 15) if rec["q_nm"] is not None else "",
            cell_n(f"R{r}", rec["mc_b"], 16) if rec["mc_b"] is not None else "",
            cell_s(f"S{r}", sst, rec["fin_caliber"], 13) if rec["fin_caliber"] else "",
            cell_s(f"U{r}", sst, rec["note"], None) if rec["note"] else "",
        ]
        rows_xml.append(f'<row r="{r}" spans="1:21">{"".join(p for p in c_parts if p)}</row>')

    last_r = max(5, 4 + len(records))
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="A1:U{last_r}"/>'
        '<sheetViews>'
        '<sheetView tabSelected="1" zoomScale="125" zoomScaleNormal="271" workbookViewId="0">'
        '<pane xSplit="2" ySplit="4" topLeftCell="C5" activePane="bottomRight" state="frozen"/>'
        '<selection pane="topRight"/><selection pane="bottomLeft"/>'
        '<selection pane="bottomRight" activeCell="C5" sqref="C5"/>'
        '</sheetView>'
        '</sheetViews>'
        '<sheetFormatPr baseColWidth="10" defaultColWidth="8.83203125" defaultRowHeight="15"/>'
        '<cols>'
        '<col min="1" max="1" width="8" customWidth="1"/>'
        '<col min="2" max="2" width="30" customWidth="1"/>'
        '<col min="3" max="3" width="11" customWidth="1"/>'
        '<col min="4" max="4" width="9.5" customWidth="1"/>'
        '<col min="5" max="5" width="11.8" customWidth="1"/>'
        '<col min="6" max="6" width="7.33203125" hidden="1" customWidth="1"/>'
        '<col min="7" max="7" width="9.83203125" customWidth="1"/>'
        '<col min="8" max="8" width="12" customWidth="1"/>'
        '<col min="9" max="9" width="13" customWidth="1"/>'
        '<col min="10" max="10" width="11" customWidth="1"/>'
        '<col min="11" max="11" width="13" customWidth="1"/>'
        '<col min="12" max="12" width="15.1640625" customWidth="1"/>'
        '<col min="13" max="15" width="12" hidden="1" customWidth="1"/>'
        '<col min="16" max="16" width="13" customWidth="1"/>'
        '<col min="17" max="17" width="10" customWidth="1"/>'
        '<col min="18" max="18" width="11" customWidth="1"/>'
        '<col min="19" max="19" width="12" hidden="1" customWidth="1"/>'
        '<col min="20" max="20" width="4" customWidth="1"/>'
        '<col min="21" max="21" width="46" customWidth="1"/>'
        '</cols>'
        f'<sheetData>{"".join(rows_xml)}</sheetData>'
        f'<autoFilter ref="A4:U{last_r}"/>'
        f'<conditionalFormatting sqref="I5:I{last_r}">'
        '<cfRule type="colorScale" priority="2"><colorScale>'
        '<cfvo type="min"/><cfvo type="percentile" val="50"/><cfvo type="max"/>'
        '<color rgb="FFF8696B"/><color rgb="FFFCFCFF"/><color rgb="FF63BE7B"/>'
        '</colorScale></cfRule></conditionalFormatting>'
        f'<conditionalFormatting sqref="K5:K{last_r}">'
        '<cfRule type="colorScale" priority="1"><colorScale>'
        '<cfvo type="min"/><cfvo type="percentile" val="50"/><cfvo type="max"/>'
        '<color rgb="FFF8696B"/><color rgb="FFFCFCFF"/><color rgb="FF63BE7B"/>'
        '</colorScale></cfRule></conditionalFormatting>'
        '<pageMargins left="0.75" right="0.75" top="1" bottom="1" header="0.5" footer="0.5"/>'
        '</worksheet>'
    )
    return xml.encode("utf-8")


def render_sheet4_segment(sst: SharedStringTable, records: list, asof_str: str) -> bytes:
    """同步刷新第 4 张表 segment（按板块聚合近半年跳涨表现，剔除尚无后续观察窗口的最新日样本）"""
    by_tag = defaultdict(list)
    for rec in records:
        by_tag[rec["tag"]].append(rec)

    sorted_tags = sorted(by_tag.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    rows_xml = [
        f'<row r="1" spans="1:8">{cell_s("A1", sst, "切片分析(瘦身版): 板块×跳涨后续表现, 用于判什么板块跳涨后拿得住", 6)}</row>',
        f'<row r="2" spans="1:8">{cell_s("A2", sst, f"自动重算@最新收盘 {asof_str}; 当日=跳涨日涨幅, 至今=现价对跳涨日收盘", 7)}</row>',
        '<row r="4" spans="1:8">'
        + cell_s("A4", sst, "板块Tag", 6)
        + cell_s("B4", sst, "跳涨次数", 8)
        + cell_s("C4", sst, "财报跳涨数", 8)
        + cell_s("D4", sst, "当日涨幅中位", 8)
        + cell_s("E4", sst, "跳涨后至今中位", 8)
        + cell_s("F4", sst, "至今留存占比", 8)
        + cell_s("G4", sst, "守住续涨(>3%)", 8)
        + cell_s("H4", sst, "回吐(<-3%)", 8)
        + '</row>',
    ]

    for idx, (tag, items) in enumerate(sorted_tags):
        r = 5 + idx
        obs = [x for x in items if x["date"] < asof_str] or items
        d0 = [x["c"] / x["pc"] - 1.0 for x in items]
        d1 = [x["now"] / x["c"] - 1.0 for x in obs]
        n_earn = sum(1 for x in items if x["qlabel"])
        med0 = round(float(np.median(d0)), 4)
        med1 = round(float(np.median(d1)), 4)
        win_rate = round(float(sum(1 for v in d1 if v > 0) / len(d1)), 4)
        n_hold = sum(1 for v in d1 if v > 0.03)
        n_fade = sum(1 for v in d1 if v < -0.03)
        rows_xml.append(
            f'<row r="{r}" spans="1:8">'
            f'{cell_s(f"A{r}", sst, tag, 6)}'
            f'{cell_n(f"B{r}", len(items), 8)}'
            f'{cell_n(f"C{r}", n_earn, 8)}'
            f'{cell_n(f"D{r}", med0, 9)}'
            f'{cell_n(f"E{r}", med1, 9)}'
            f'{cell_n(f"F{r}", win_rate, 9)}'
            f'{cell_n(f"G{r}", n_hold, 8)}'
            f'{cell_n(f"H{r}", n_fade, 8)}'
            f'</row>'
        )

    last_r = max(5, 4 + len(sorted_tags))
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="A1:H{last_r}"/>'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr baseColWidth="10" defaultColWidth="8.83203125" defaultRowHeight="15"/>'
        '<cols>'
        '<col min="1" max="1" width="20" customWidth="1"/>'
        '<col min="2" max="8" width="16" customWidth="1"/>'
        '</cols>'
        f'<sheetData>{"".join(rows_xml)}</sheetData>'
        f'<autoFilter ref="A4:H{last_r}"/>'
        f'<conditionalFormatting sqref="D5:D{last_r}">'
        '<cfRule type="colorScale" priority="3"><colorScale>'
        '<cfvo type="min"/><cfvo type="percentile" val="50"/><cfvo type="max"/>'
        '<color rgb="FFF8696B"/><color rgb="FFFCFCFF"/><color rgb="FF63BE7B"/>'
        '</colorScale></cfRule></conditionalFormatting>'
        f'<conditionalFormatting sqref="E5:E{last_r}">'
        '<cfRule type="colorScale" priority="1"><colorScale>'
        '<cfvo type="min"/><cfvo type="percentile" val="50"/><cfvo type="max"/>'
        '<color rgb="FFF8696B"/><color rgb="FFFCFCFF"/><color rgb="FF63BE7B"/>'
        '</colorScale></cfRule></conditionalFormatting>'
        f'<conditionalFormatting sqref="F5:F{last_r}">'
        '<cfRule type="colorScale" priority="2"><colorScale>'
        '<cfvo type="min"/><cfvo type="percentile" val="50"/><cfvo type="max"/>'
        '<color rgb="FFF8696B"/><color rgb="FFFCFCFF"/><color rgb="FF63BE7B"/>'
        '</colorScale></cfRule></conditionalFormatting>'
        '<pageMargins left="0.75" right="0.75" top="1" bottom="1" header="0.5" footer="0.5"/>'
        '</worksheet>'
    )
    return xml.encode("utf-8")


def write_lossless_xlsx(
    src_xlsx: str,
    dst_xlsx: str,
    records: list,
    user_state: dict,
    w0_str: str,
    asof_str: str,
):
    """基于原 ZIP 容器只替换 sheet1/sheet2/sheet4 与追加后的 sharedStrings，其余文件字节级原封不动"""
    tmp_out = dst_xlsx + ".tmp"
    with zipfile.ZipFile(src_xlsx, "r") as zin:
        sst = SharedStringTable(zin.read("xl/sharedStrings.xml"))
        earn_cnt = sum(1 for r in records if r["qlabel"])
        uniq_cnt = len({r["tk"] for r in records})

        s1_bytes = render_sheet1_cover(sst, w0_str, asof_str, len(records), uniq_cnt, earn_cnt)
        s2_bytes = render_sheet2_main(sst, records, user_state, w0_str, asof_str)
        s4_bytes = render_sheet4_segment(sst, records, asof_str)
        sst_bytes = sst.to_bytes()

        with zipfile.ZipFile(tmp_out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                fn = item.filename
                if fn == "xl/calcChain.xml":
                    # 移除旧行数 calcChain，让 Excel 打开时静默根据缓存值与公式自建，零修复弹窗
                    continue
                data = zin.read(fn)
                if fn == "[Content_Types].xml":
                    txt = data.decode("utf-8")
                    txt = re.sub(r'<Override[^>]*PartName="/xl/calcChain\.xml"[^>]*/?>', "", txt)
                    data = txt.encode("utf-8")
                elif fn == "xl/_rels/workbook.xml.rels":
                    txt = data.decode("utf-8")
                    txt = re.sub(r'<Relationship[^>]*Target="calcChain\.xml"[^>]*/?>', "", txt)
                    data = txt.encode("utf-8")
                elif fn == "xl/workbook.xml":
                    # 强制在部分未缓存环境打开时自动全簿重算，同时保留全部工作表定义
                    txt = data.decode("utf-8")
                    if "fullCalcOnLoad" not in txt:
                        txt = txt.replace("<calcPr ", '<calcPr fullCalcOnLoad="1" ')
                    data = txt.encode("utf-8")
                elif fn == "xl/sharedStrings.xml":
                    data = sst_bytes
                elif fn == "xl/worksheets/sheet1.xml":
                    data = s1_bytes
                elif fn == "xl/worksheets/sheet2.xml":
                    data = s2_bytes
                elif fn == "xl/worksheets/sheet4.xml":
                    data = s4_bytes
                zout.writestr(item, data)

    os.replace(tmp_out, dst_xlsx)


# ── 7. 主流程执行 ────────────────────────────────────────────────────────
def main():
    dry_out = None
    if "--dry" in sys.argv:
        dry_out = sys.argv[sys.argv.index("--dry") + 1]

    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    os.makedirs(NEXUS_BACKUP_DIR, exist_ok=True)

    # 备份原始文件（首次升级必存 nexus/backups，每日首次运行归档进 _归档_底稿与旧版）
    orig_bak = os.path.join(NEXUS_BACKUP_DIR, "1_选股_美股2026中报财报日涨跌_orig_20261109.xlsx")
    if os.path.exists(TARGET_XLSX) and not os.path.exists(orig_bak):
        shutil.copy2(TARGET_XLSX, orig_bak)
        print(f"[备份] 已保存原始 Q2 工作簿至 {orig_bak}")

    if not dry_out and os.path.exists(TARGET_XLSX):
        mtime_date = dt.date.fromtimestamp(os.path.getmtime(TARGET_XLSX))
        if mtime_date < dt.date.today():
            stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
            arch_path = os.path.join(ARCHIVE_DIR, f"1_选股_美股2026中报财报日涨跌_{stamp}.xlsx")
            shutil.copy2(TARGET_XLSX, arch_path)
            print(f"[归档] 已备份上一版活表至 {arch_path}")

    # Step 1: 无损提取用户手写笔记、红字、黄底与阈值设置
    user_state = harvest_user_assets(TARGET_XLSX, CACHE_DIR)

    # Step 2: 构建全市场监测股票池（us_price_db 1392只 + 原Q2表全部标的 + NASDAQ实时市值>=50亿美元标的）
    pdb_tks = {os.path.basename(f).replace(".parquet", "") for f in glob.glob(os.path.join(PDB_PRICES_DIR, "*.parquet"))}
    q2_tks = set(user_state["q2_sector_tags"].keys())
    nasdaq_map = fetch_nasdaq_screener(CACHE_DIR)
    live_5b = {tk for tk, v in nasdaq_map.items() if v["mc_b"] >= MIN_MCAP_B and v["last"] >= 5.0}
    extra_pkl_u = os.path.join(CACHE_DIR, "extra_prices.pkl")
    extra_tks = {k for k in (pd.read_pickle(extra_pkl_u).keys() if os.path.exists(extra_pkl_u) else []) if isinstance(k, str) and not k.startswith("_")}
    fin_pkl_u = os.path.join(CACHE_DIR, "financials_meta.json")
    fin_5b_tks = {k for k, v in (json.load(open(fin_pkl_u)).items() if os.path.exists(fin_pkl_u) else []) if (v.get("mc_b") or 0) >= MIN_MCAP_B}
    universe = sorted((pdb_tks | q2_tks | live_5b | extra_tks | fin_5b_tks) - {"CCZ"})
    print(f"[股票池] 合计监测 {len(universe)} 只美股 (价格库 {len(pdb_tks)} | 原Q2池 {len(q2_tks)} | 实时50亿+ {len(live_5b)})")

    # Step 3: 加载并增量补齐日线至最新交易日
    series_map, asof_ts = load_all_prices(universe, CACHE_DIR)
    asof_date = asof_ts.date()
    w0_date = asof_date - dt.timedelta(days=WINDOW_DAYS)
    asof_str = str(asof_date)
    w0_str = str(w0_date)
    w0_ts = pd.Timestamp(w0_date)
    print(f"[窗口] 滚动近半年窗口: {w0_str} 至 {asof_str}")

    # Step 4: 全时间段单日跳涨（>= +10.0%）检测 + 拆股/脏数据过滤
    raw_jumps = []
    latest_jump_by_tk = {}
    all_trading_days = set()

    for tk in universe:
        df = series_map.get(tk)
        if df is None or len(df) < 5:
            continue
        all_trading_days.update(df.index)
        c_ser = df["close"]
        ac_ser = df["adj_close"] if "adj_close" in df.columns else c_ser
        v_ser = df["volume"] if "volume" in df.columns else pd.Series(np.nan, index=df.index)

        ret = c_ser.pct_change(fill_method=None)
        adj_ret = ac_ser.pct_change(fill_method=None)
        vol_ma20 = v_ser.rolling(20, min_periods=8).mean().shift(1)

        win_ret = ret[ret.index >= w0_ts]
        hits = win_ret[win_ret >= JUMP_THRESHOLD]
        if hits.empty:
            continue

        now_px = float(c_ser.iloc[-1])
        hi52 = float(c_ser.iloc[-253:].max())

        for d_ts, pct_val in hits.items():
            loc = df.index.get_loc(d_ts)
            if loc == 0:
                continue
            pc = float(c_ser.iloc[loc - 1])
            c_px = float(c_ser.iloc[loc])
            if pc <= 0 or np.isnan(pc):
                continue

            # 过滤 1: 未复权分拆/特殊分红导致的假跳变
            ar = float(adj_ret.iloc[loc]) if pd.notna(adj_ret.iloc[loc]) else float(pct_val)
            if abs(float(pct_val) - ar) > 0.15 and ar < JUMP_THRESHOLD:
                continue

            # 过滤 2: 次日立即反向吞没且无成交量放大的脏数据打印（如 MNST 8/06）
            vr = float(v_ser.iloc[loc] / vol_ma20.iloc[loc]) if (pd.notna(vol_ma20.iloc[loc]) and vol_ma20.iloc[loc] > 0) else np.nan
            nxt_r = float(ret.iloc[loc + 1]) if (loc + 1 < len(ret) and pd.notna(ret.iloc[loc + 1])) else np.nan
            if (not np.isnan(nxt_r)) and nxt_r <= -0.8 * float(pct_val) / (1.0 + float(pct_val)) and (np.isnan(vr) or vr < 1.5):
                continue

            ds = str(d_ts.date())
            raw_jumps.append({
                "tk": tk,
                "date": ds,
                "pc": pc,
                "c": c_px,
                "pct": float(pct_val),
                "now": now_px,
                "hi52": max(hi52, c_px, now_px),
            })
            if ds > latest_jump_by_tk.get(tk, ""):
                latest_jump_by_tk[tk] = ds

    trading_days = pd.DatetimeIndex(sorted(all_trading_days))
    jump_tickers = sorted({j["tk"] for j in raw_jumps})
    print(f"[跳涨扫描] 检出近半年跳涨事件 {len(raw_jumps)} 次，涉及 {len(jump_tickers)} 家公司")

    # Step 5: 财报季度精确归因（NASDAQ 官方日历 + SEC EDGAR 8-K Item 2.02 + 10-Q/10-K reportDate）
    cal_start = w0_date - dt.timedelta(days=5)
    nasdaq_cal = update_nasdaq_earnings_calendar(cal_start, asof_date, CACHE_DIR)
    sec_cache = update_sec_8k_for_jump_tickers(jump_tickers, latest_jump_by_tk, CACHE_DIR)
    earn_lookup = build_earnings_reaction_lookup(
        jump_tickers, trading_days, nasdaq_cal, sec_cache, user_state["q2_verified_earnings"]
    )

    # Step 6: 基本面财务指标（USD 口径）与中文主业/用户笔记装配
    fin_meta = update_financials_and_meta(jump_tickers, latest_jump_by_tk, nasdaq_map, CACHE_DIR)

    records = []
    new_auto_notes = dict(user_state.get("auto_notes", {}))
    for j in raw_jumps:
        tk = j["tk"]
        ds = j["date"]
        qlabel, sess = earn_lookup.get((tk, ds), ("", ""))
        fm = fin_meta.get(tk, {})
        tag = map_buwen_sector_tag(tk, fm.get("industry", ""), fm.get("sector", ""), user_state["q2_sector_tags"])

        q_end = fm.get("q_end") or ""
        fin_cal = ""
        if q_end:
            try:
                days_lag = (asof_date - dt.date.fromisoformat(q_end)).days
                fin_cal = "本期" if days_lag <= 135 else "滞后一期"
            except Exception:
                fin_cal = "本期"

        if tk in user_state["user_notes"]:
            note = user_state["user_notes"][tk]
        else:
            note = fm.get("auto_zh", "")
            if note:
                new_auto_notes[tk] = note

        records.append({
            "tk": tk,
            "name": fm.get("name") or nasdaq_map.get(tk, {}).get("name") or tk,
            "tag": tag,
            "qlabel": qlabel,
            "date": ds,
            "session": sess,
            "pc": j["pc"],
            "c": j["c"],
            "pct": j["pct"],
            "now": j["now"],
            "hi52": j["hi52"],
            "q_end": q_end,
            "q_rev_m": fm.get("q_rev_m"),
            "q_nm": fm.get("q_nm"),
            "mc_b": fm.get("mc_b"),
            "fin_caliber": fin_cal,
            "note": note,
        })

    # 最新跳涨日在最上，同一日按当日涨幅降序
    records.sort(key=lambda r: (r["date"], r["pct"]), reverse=True)

    # 持久化 auto_notes 以便下次区分用户新写笔记
    user_state["auto_notes"] = new_auto_notes
    json.dump(
        user_state,
        open(os.path.join(CACHE_DIR, "user_annotations.json"), "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )

    out_path = dry_out if dry_out else TARGET_XLSX
    write_lossless_xlsx(TARGET_XLSX, out_path, records, user_state, w0_str, asof_str)

    q_dist = Counter(r["qlabel"] for r in records if r["qlabel"])
    print(
        f"[完成] 已写入 {out_path}\n"
        f"  窗口: {w0_str} ~ {asof_str} | 总跳涨: {len(records)} 次 ({len(jump_tickers)} 家)\n"
        f"  财报跳涨: {sum(q_dist.values())} 次 -> {dict(sorted(q_dist.items()))} | 日常非财报跳涨: {len(records) - sum(q_dist.values())} 次"
    )


if __name__ == "__main__":
    main()
