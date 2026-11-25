#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V3.0 National Team Rescue & Institutional Hedge 5-Dimension Live + EOD Scorer (0~100, Base=20).
Covers:
  Dim 1: 10 Core Broad ETFs (5 T1 incl. 159919 + 5 T2 incl. 588000) & 22-ETF Total Pool
  Dim 2: 16 National Team Heavyweights (4 Squads) -> True Resonance vs Fake Support Divergence
  Dim 3: Stock Index Futures (IF0 / IH0 / IC0 / IM0) Basis & RD019 Panic Trap Filter
  Dim 4: 3-Layer Institutional Redemption (IOPV, Fund-8 Dump, SSE Sector-9 5d, LHB 5d) + F153/F154/F156
  Dim 5: Market Drawdown/Overheat Context & PIT Official Policy Announcements
Strictly NO yfinance (D12 compliant). Zero cap10m metrics.
"""
import argparse, json, os, re, sqlite3, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import requests

os.environ["NO_PROXY"] = "*"

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
from csrc_fetch_etf_shares import ETFS, OUT_DIR as NT_DIR

DATA_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data"
CACHE_DIR = os.path.join(NT_DIR, "v3_cache")

CORE10_T1 = [
    ("sh510300", "华泰300"), ("sh510310", "易方达300"), ("sh510330", "华夏300"),
    ("sz159919", "嘉实300"), ("sh510050", "华夏50"),
]
CORE10_T2 = [
    ("sh510500", "南方500"), ("sh512100", "南方1000"), ("sz159915", "创业板ETF"),
    ("sh588000", "华夏科创50"), ("sh588080", "易方达科创50"),
]
CORE10_CODES = {s[-6:] for s, _ in CORE10_T1 + CORE10_T2}
T1_CORE_CODES = {s[-6:] for s, _ in CORE10_T1}
T2_CORE_CODES = {s[-6:] for s, _ in CORE10_T2}

NT16_SQUADS = {
    "银行方阵": [("sh601398", "工商银行"), ("sh601288", "农业银行"), ("sh601988", "中国银行"), ("sh601939", "建设银行"), ("sh600036", "招商银行")],
    "能源央企红利": [("sh601857", "中国石油"), ("sh600028", "中国石化"), ("sh600941", "中国移动"), ("sh601088", "中国神华"), ("sh600900", "长江电力")],
    "保险白酒券商": [("sh601318", "中国平安"), ("sh601628", "中国人寿"), ("sh600519", "贵州茅台"), ("sh600030", "中信证券")],
    "双创核心权重": [("sz300750", "宁德时代"), ("sh688981", "中芯国际")],
}
NT16_LIST = [(s, nm, sq) for sq, items in NT16_SQUADS.items() for s, nm in items]
BIG4_OIL_SYMS = ["sh601398", "sh601288", "sh601988", "sh601939", "sh601857", "sh600028"]

SECTOR_SSE_ETFS = [
    ("588000", "科创50ETF"), ("512000", "券商ETF"), ("512880", "证券ETF"), ("512480", "半导体ETF"),
    ("512010", "医药ETF"), ("512690", "酒ETF"), ("515030", "新能车ETF"), ("515790", "光伏ETF"),
    ("510880", "红利ETF"), ("512800", "银行ETF"),
]
SEC9_CODES = {c for c, _ in SECTOR_SSE_ETFS if c != "588000"}

IOPV_WATCH = [
    ("sh510300", "300ETF", "宽基"), ("sh510050", "50ETF", "宽基"), ("sh510500", "500ETF", "宽基"),
    ("sh512100", "1000ETF", "宽基"), ("sz159915", "创业板ETF", "宽基"), ("sh588000", "科创50ETF", "宽基"),
    ("sh512000", "券商ETF", "行业"), ("sh512880", "证券ETF", "行业"), ("sh512480", "半导体ETF", "行业"),
    ("sh512010", "医药ETF", "行业"), ("sh512690", "酒ETF", "行业"), ("sh515030", "新能车ETF", "行业"),
    ("sh510880", "红利ETF", "行业"), ("sz159995", "芯片ETF", "行业"),
]

FUND8_HWS = [
    ("sz300750", "宁德时代"), ("sz300308", "中际旭创"), ("sz300274", "阳光电源"), ("sh688256", "寒武纪"),
    ("sz300059", "东方财富"), ("sz002475", "立讯精密"), ("sh603259", "药明康德"), ("sz000858", "五粮液"),
]

INDICES_SYMS = [
    ("sh000001", "上证指数"), ("sh000016", "上证50"), ("sh000300", "沪深300"),
    ("sh000905", "中证500"), ("sh000852", "中证1000"), ("sh000688", "科创50"), ("sz399006", "创业板指"),
]


def trading_elapsed_fraction(now: datetime) -> float:
    m = now.hour * 60 + now.minute
    if m < 9 * 60 + 30:
        return 1.0
    if m <= 11 * 60 + 30:
        mins = m - (9 * 60 + 30)
    elif m < 13 * 60:
        mins = 120
    elif m <= 15 * 60:
        mins = 120 + (m - 13 * 60)
    else:
        mins = 240
    return max(0.05, min(1.0, mins / 240.0))


def is_third_friday(dt: datetime) -> bool:
    return dt.weekday() == 4 and 15 <= dt.day <= 21


def _fetch_qt_batch(syms: list) -> dict:
    out = {}
    url = "http://qt.gtimg.cn/q=" + ",".join(syms)
    try:
        raw = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5, proxies={"http": None, "https": None}).content.decode("gbk", "ignore")
        for ln in raw.strip().splitlines():
            m = re.match(r"v_(\w+)=\"([^\"]*)\"", ln.strip())
            if not m:
                continue
            sym = m.group(1)
            ps = m.group(2).split("~")
            if len(ps) < 38:
                continue
            def _f(idx):
                try:
                    return float(ps[idx]) if ps[idx] not in ("", "-") else np.nan
                except Exception:
                    return np.nan
            out[sym] = {
                "code": ps[2], "name": ps[1].replace(" ", ""),
                "now": _f(3), "prev": _f(4), "open": _f(5),
                "pct": _f(32), "high": _f(33), "low": _f(34),
                "amt_yi": (_f(37) / 1e4) if pd.notna(_f(37)) else np.nan,
                "disc_pct": _f(77) if len(ps) > 77 else np.nan,
                "iopv": _f(78) if len(ps) > 78 else np.nan,
                "date": f"{ps[30][:4]}-{ps[30][4:6]}-{ps[30][6:8]}" if len(ps) > 30 and len(ps[30]) >= 8 else "",
            }
    except Exception:
        pass
    return out


def _fetch_futures_live() -> dict:
    out = {}
    try:
        r = requests.get(
            "https://hq.sinajs.cn/list=CFF_RE_IF0,CFF_RE_IH0,CFF_RE_IC0,CFF_RE_IM0",
            headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
            timeout=5, proxies={"http": None, "https": None},
        )
        r.encoding = "gbk"
        for ln in r.text.strip().splitlines():
            m = re.match(r'var hq_str_CFF_RE_(\w+)="([^"]*)"', ln.strip())
            if not m:
                continue
            ps = m.group(2).split(",")
            if len(ps) >= 15:
                def _f(i):
                    try:
                        return float(ps[i])
                    except Exception:
                        return np.nan
                now_p, prev_s = _f(3), _f(13)
                out[m.group(1)] = {
                    "open": _f(0), "high": _f(1), "low": _f(2), "now": now_p,
                    "vol": _f(4), "amt": _f(5), "oi": _f(6),
                    "prev_settle": prev_s, "prev_close": _f(14),
                    "pct": ((now_p / prev_s - 1.0) * 100.0) if (pd.notna(now_p) and pd.notna(prev_s) and prev_s > 0) else np.nan,
                }
    except Exception:
        pass
    return out


def _fetch_1m_bars(sym: str):
    """Fetch today's 1-minute bars: EastMoney trends2 primary -> Sina 1m -> Tencent ifzq."""
    # 1. EastMoney trends2
    try:
        secid = ("1." if sym.startswith("sh") else "0.") + sym[-6:]
        u = f"https://push2.eastmoney.com/api/qt/stock/trends2/get?fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58&secid={secid}"
        j = requests.get(u, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}, timeout=4, proxies={"http": None, "https": None}).json()
        d = j.get("data") or {}
        trends = d.get("trends") or []
        if trends:
            prev_c = float(d.get("preClose") or 0.0)
            rows = []
            for t in trends:
                ps = t.split(",")
                hhmm = ps[0][11:16].replace(":", "")
                if hhmm < "0930":
                    continue
                px = float(ps[2])
                amt = float(ps[6])
                rows.append((hhmm, px, amt))
            if rows:
                return sym, prev_c, rows
    except Exception:
        pass
    # 2. Sina 1m KLine fallback
    try:
        u = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol={sym}&scale=1&ma=no&datalen=260"
        txt = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=4, proxies={"http": None, "https": None}).text
        i, j = txt.find("["), txt.rfind("]")
        bars = json.loads(txt[i:j + 1]) if i >= 0 and j > i else []
        if bars:
            latest_d = bars[-1]["day"][:10]
            rows = []
            prev_c = np.nan
            for b in bars:
                if b["day"][:10] == latest_d:
                    rows.append((b["day"][11:16].replace(":", ""), float(b["close"]), float(b["volume"]) * float(b["close"])))
                else:
                    prev_c = float(b["close"])
            if rows:
                return sym, prev_c, rows
    except Exception:
        pass
    # 3. Tencent ifzq fallback
    try:
        u = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={sym}"
        j = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=4, proxies={"http": None, "https": None}).json()
        d = j["data"][sym]
        prev_c = float(d["qt"][sym][4])
        rows, prev_v = [], 0.0
        for b in d["data"]["data"]:
            ps = b.split(" ")
            hhmm, px, cum_v = ps[0], float(ps[1]), float(ps[2])
            dv = max(0.0, cum_v - prev_v)
            prev_v = cum_v
            rows.append((hhmm, px, dv * px * 100.0))
        if rows:
            return sym, prev_c, rows
    except Exception:
        pass
    return sym, np.nan, []


def _fetch_sina_daily(sym: str, datalen: int = 90) -> list:
    try:
        u = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol={sym}&scale=240&ma=no&datalen={datalen}"
        txt = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=5, proxies={"http": None, "https": None}).text
        i, j = txt.find("["), txt.rfind("]")
        bars = json.loads(txt[i:j + 1]) if i >= 0 and j > i else []
        return [
            {"date": b["day"][:10], "open": float(b["open"]), "high": float(b["high"]), "low": float(b["low"]),
             "close": float(b["close"]), "vol": float(b["volume"]), "amt": float(b["volume"]) * float(b["close"])}
            for b in bars
        ]
    except Exception:
        return []


def _fetch_if0_daily() -> pd.DataFrame:
    try:
        u = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var/InnerFuturesNewService.getDailyKLine?symbol=IF0"
        txt = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=5, proxies={"http": None, "https": None}).text
        i, j = txt.find("["), txt.rfind("]")
        bars = json.loads(txt[i:j + 1]) if i >= 0 and j > i else []
        if bars:
            df = pd.DataFrame(bars[-90:])
            df = df.rename(columns={"d": "date", "o": "open", "h": "high", "l": "low", "c": "close", "v": "vol"})
            df["date"] = df["date"].astype(str).str[:10]
            for c in ["open", "high", "low", "close", "vol"]:
                df[c] = df[c].astype(float)
            return df[["date", "open", "high", "low", "close", "vol"]].sort_values("date").reset_index(drop=True)
    except Exception:
        pass
    try:
        import akshare as ak
        df = ak.futures_main_sina(symbol="IF0", start_date=(datetime.now() - timedelta(days=120)).strftime("%Y%m%d"), end_date=datetime.now().strftime("%Y%m%d"))
        df["date"] = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d")
        return df[["date", "开盘价", "最高价", "最低价", "收盘价", "成交量"]].rename(columns={
            "开盘价": "open", "最高价": "high", "最低价": "low", "收盘价": "close", "成交量": "vol"
        }).sort_values("date").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _fetch_sse_shares_day(dt: str, target_codes: set) -> dict:
    try:
        r = requests.get(
            "https://query.sse.com.cn/commonQuery.do",
            params={"isPagination": "false", "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L", "STAT_DATE": dt},
            headers={"Referer": "https://www.sse.com.cn/", "User-Agent": "Mozilla/5.0"},
            timeout=6, proxies={"http": None, "https": None},
        )
        return {
            str(x.get("SEC_CODE", "")).strip(): float(str(x.get("TOT_VOL", "0")).replace(",", ""))
            for x in r.json().get("result", [])
            if str(x.get("SEC_CODE", "")).strip() in target_codes
        }
    except Exception:
        return {}


def _fetch_lhb_5d() -> tuple:
    try:
        import akshare as ak
        beg = (datetime.now() - timedelta(days=15)).strftime("%Y%m%d")
        end = datetime.now().strftime("%Y%m%d")
        jg = ak.stock_lhb_jgmmtj_em(start_date=beg, end_date=end)
        if jg is not None and len(jg):
            jg["date"] = pd.to_datetime(jg["上榜日期"]).dt.strftime("%Y-%m-%d")
            g = jg.groupby("date").agg(
                n=("代码", "count"),
                buy=("机构买入总额", "sum"),
                sell=("机构卖出总额", "sum"),
                net=("机构买入净额", "sum"),
            ).reset_index().sort_values("date")
            rows = [{"date": str(r["date"]), "n": int(r["n"]), "net_yi": round(float(r["net"] / 1e8), 2)} for _, r in g.tail(6).iterrows()]
            return rows, round(float(g.tail(5)["net"].sum() / 1e8), 2), str(g["date"].iloc[-1])
    except Exception:
        pass
    return [], np.nan, ""


def _check_official_nt_5d(today_str: str, settled_dt: str) -> tuple:
    cut_7d = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    ev_p = os.path.join(NT_DIR, "nt_official_events.json")
    hits_intra, hits_eod = [], []
    if os.path.exists(ev_p):
        evs = json.load(open(ev_p, encoding="utf-8"))
        for e in evs:
            if e.get("cat") != "NT_OFFICIAL_ENTRY":
                continue
            ed = str(e.get("event_date", ""))
            sl = str(e.get("slot", "")).upper()
            if ed >= cut_7d:
                if ed < today_str or sl in ("BMO", "INTRADAY"):
                    hits_intra.append(f"{ed} {e.get('title','')[:40]}")
                if ed <= settled_dt:
                    hits_eod.append(f"{ed} {e.get('title','')[:40]}")

    db_p = os.path.join(DATA_DIR, "flash_news_5y_pit.db")
    if os.path.exists(db_p):
        try:
            con = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
            kws = "(title LIKE '%中央汇金%增持%' OR title LIKE '%中国国新%增持%' OR title LIKE '%中国诚通%增持%' OR title LIKE '%汇金%买入%' OR title LIKE '%启动%互换便利%' OR title LIKE '%平准基金%')"
            rows = con.execute(f"SELECT pub_datetime_cst, title FROM flash_news WHERE pub_datetime_cst >= '{cut_7d}' AND {kws} ORDER BY pub_datetime_cst DESC LIMIT 10").fetchall()
            con.close()
            for dt_s, title in rows:
                d_part = str(dt_s)[:10]
                if any(b in str(title) for b in ["严正声明", "专题", "研讨"]):
                    continue
                if d_part < today_str or str(dt_s)[11:16] < "15:00":
                    hits_intra.append(f"{d_part} {str(title)[:40]}")
                if d_part <= settled_dt:
                    hits_eod.append(f"{d_part} {str(title)[:40]}")
        except Exception:
            pass
    return list(dict.fromkeys(hits_intra)), list(dict.fromkeys(hits_eod))


def _tier_label(score: int) -> str:
    if score >= 75:
        return ">=75 真底重手救市"
    if score >= 60:
        return "60~74 准救市试探"
    if score >= 40:
        return "40~59 脉冲维稳"
    return "<40 无救市/观望"


def _compute_score_breakdown(ctx: dict, mode: str) -> dict:
    """Compute exact V3.0 Pure-Integer Score (0~100, Base=20) with full item breakdown."""
    score = 20
    items = [("BASE", "基础底分", 20, "纯整数打分卡底分")]

    def add(dim: str, label: str, pts: int, detail: str):
        nonlocal score
        score += pts
        items.append((dim, label, pts, detail))

    # --- Dim 5: Context & Official Policy ---
    is_weak = ctx.get("is_weak", False)
    is_deep = ctx.get("is_deep", False)
    is_high = ctx.get("is_high", False)
    is_bubble = ctx.get("is_bubble", False)
    if is_high:
        add("D5_背景与政策", "高位过热扣分", -18, f"300在MA20之上且20日涨{ctx.get('c300_ret20',0):+.1f}%")
        if is_bubble:
            add("D5_背景与政策", "极度狂热加扣", -6, "20日涨幅>=15%")
    else:
        if is_weak:
            add("D5_背景与政策", "弱势护盘背景", 6, ctx.get("weak_reason", "低于MA20或60日回撤<=-6%"))
        if is_deep:
            add("D5_背景与政策", "深跌加速区间", 4, f"60日回撤={ctx.get('c300_dd60',0):.1f}%<=-8%")
    if ctx.get("official_hits"):
        add("D5_背景与政策", "近5日官方明牌增持", 12, ctx["official_hits"][0])

    # --- Dim 1: Broad ETF Pool (10 Core + 22 Total) ---
    spk = ctx.get("etf_spike", 0.0)
    pullup = ctx.get("c300_pullup", 0.0)
    if mode == "live":
        if spk >= 2.0:
            add("D1_宽基ETF池", "宽基成交爆量>=2.0x", 16, f"核心10/全池量比={spk:.2f}x")
        elif spk >= 1.5:
            add("D1_宽基ETF池", "宽基成交放量1.5~2.0x", 10, f"核心10/全池量比={spk:.2f}x")
        elif spk >= 1.2 and pullup >= 0.8:
            add("D1_宽基ETF池", "温和放量叠加下影拉起", 4, f"量比={spk:.2f}x, 拉起={pullup:+.2f}%")
        if spk >= 1.5 and pullup >= 0.8:
            add("D1_宽基ETF池", "放量长下影确认", 4, f"300低点拉起={pullup:+.2f}%")
        t1_c, t2_c = ctx.get("t1_cnt16", 0), ctx.get("t2_cnt16", 0)
        if t1_c >= 2 and t2_c >= 2:
            add("D1_宽基ETF池", "一二队盘中同步共振", 8, f"一队{t1_c}/5, 二队{t2_c}/5放量>=1.6x")
        elif (t1_c + t2_c) >= 5:
            add("D1_宽基ETF池", "10核心半数以上同步放量", 6, f"合计{t1_c+t2_c}/10只>=1.6x")
        elif t1_c >= 2 and t2_c == 0:
            add("D1_宽基ETF池", "一队偏心抽血预警", -4, f"一队{t1_c}/5放量但二队0/5")
        if ctx.get("lag_5d_wflow", 0.0) >= 150.0:
            add("D1_宽基ETF池", "近5日已披露延续托底", 4, f"截至上日5日纯净={ctx['lag_5d_wflow']:+.1f}亿>=150亿")
    else:
        if spk >= 2.0:
            add("D1_宽基ETF池", "宽基成交爆量>=2.0x", 12, f"核心10/全池量比={spk:.2f}x")
        elif spk >= 1.5:
            add("D1_宽基ETF池", "宽基成交放量1.5~2.0x", 7, f"核心10/全池量比={spk:.2f}x")
        elif spk >= 1.2 and pullup >= 0.8:
            add("D1_宽基ETF池", "温和放量叠加下影拉起", 3, f"量比={spk:.2f}x, 拉起={pullup:+.2f}%")
        if spk >= 1.5 and pullup >= 0.8:
            add("D1_宽基ETF池", "放量长下影确认", 3, f"300低点拉起={pullup:+.2f}%")
        wf, wpct = ctx.get("wflow_yi", 0.0), ctx.get("wflow_pct_aum", 0.0)
        if wf >= 90.0 or wpct >= 1.5:
            add("D1_宽基ETF池", "官宣单日重手净申购", 12, f"纯净={wf:+.1f}亿 (占AUM {wpct:+.2f}%)")
        elif wf >= 40.0 or wpct >= 0.7:
            add("D1_宽基ETF池", "官宣单日中等净申购", 7, f"纯净={wf:+.1f}亿 (占AUM {wpct:+.2f}%)")
        if ctx.get("wflow_5d_yi", 0.0) >= 150.0:
            add("D1_宽基ETF池", "5日纯净累计>=150亿", 4, f"5日纯净={ctx['wflow_5d_yi']:+.1f}亿")
        t1f, t2f = ctx.get("t1_flow_yi", 0.0), ctx.get("t2_flow_yi", 0.0)
        if t1f >= 50.0 and t2f >= 25.0:
            add("D1_宽基ETF池", "F152一二队官方份额共振", 6, f"一队{t1f:+.1f}亿 & 二队{t2f:+.1f}亿")
        elif t1f >= 75.0 and t2f < 15.0:
            add("D1_宽基ETF池", "F151一队偏心抽血小盘", -5, f"一队{t1f:+.1f}亿但二队{t2f:+.1f}亿")

    # --- Dim 2: 16 National Team Heavyweights (4 Squads) ---
    hw_cnt, sq_cnt = ctx.get("hw16_sync_cnt", 0), ctx.get("sq_active_cnt", 0)
    b4o, c1k = ctx.get("big4_oil_pct", 0.0), ctx.get("csi1000_pct", 0.0)
    if spk >= 1.5 and hw_cnt >= 4:
        add("D2_16核心权重", "权重与ETF同步真护盘", 10, f"{hw_cnt}/16只权重放量止跌且横跨{sq_cnt}/4大方阵")
        if hw_cnt >= 8 and sq_cnt >= 3:
            add("D2_16核心权重", "全权重多方阵大共振", 4, f"{hw_cnt}/16只齐动, {sq_cnt}大方阵协同")
    elif spk < 1.3 and (((b4o - c1k) >= 2.0) or (b4o >= 0.8 and c1k <= -0.8)):
        add("D2_16核心权重", "假护盘抽血警报", -10, f"银行石油{b4o:+.2f}% vs 中证1000 {c1k:+.2f}% 且ETF量比{spk:.2f}x")

    # --- Dim 3: Index Futures Linkage ---
    if_spk = ctx.get("if0_spike", 0.0)
    if_bas = ctx.get("if0_basis_pct", 0.0)
    bas_c1 = ctx.get("if0_basis_chg1", 0.0)
    is_del = ctx.get("is_deliv", False)
    if spk >= 1.8 and if_spk >= 1.5 and (not is_del):
        add("D3_股指期货联动", "RD019期现双爆量恐慌陷阱", -10, f"ETF={spk:.2f}x叠加IF0={if_spk:.2f}x(非交割日)")
    elif spk >= 1.8 and if_spk < 1.5 and (not is_del):
        add("D3_股指期货联动", "纯净现货护盘(期指未踩踏)", 6, f"ETF={spk:.2f}x而IF0={if_spk:.2f}x<1.5x")
    if spk >= 1.5 and if_bas <= -0.5:
        add("D3_股指期货联动", "放量护盘遇IF0深贴水", 5, f"IF0贴水{if_bas:+.2f}%<=-0.5%(空头拥挤)")
    if spk >= 1.5 and if_bas <= -0.1 and bas_c1 >= 0.25:
        add("D3_股指期货联动", "贴水基差单日明显走强", 3, f"基差单日变化{bas_c1:+.2f}%")
    if (is_weak and if_bas >= 0.0) or (if_bas >= 0.30):
        add("D3_股指期货联动", "期指升水/零贴水预警", -5, f"IF0基差={if_bas:+.2f}%")

    # --- Dim 4: Institutional & Redemption Pressure ---
    f8_cnt = ctx.get("fund8_dump_cnt", 0)
    if f8_cnt >= 3:
        add("D4_机构赎回压力", "公募8重仓放量砸盘", -6, f"{f8_cnt}/8只重仓放量下跌")
    if mode == "live":
        iopv_cnt = ctx.get("iopv_deep_disc_cnt", 0)
        if iopv_cnt >= 3:
            add("D4_机构赎回压力", "ETF实时IOPV深折价", -5, f"{iopv_cnt}/14只ETF折价<=-0.25%")
        s9_lag, lhb_lag = ctx.get("lag_sec9_5d", 0.0), ctx.get("lag_lhb_5d", 0.0)
        if s9_lag <= -35.0 or (pd.notna(lhb_lag) and lhb_lag <= -40.0):
            add("D4_机构赎回压力", "已披露行业ETF/机构净卖出", -4, f"行业9ETF 5日={s9_lag:+.1f}亿, 龙虎榜5日={lhb_lag:+.1f}亿")
    else:
        s9_5d, lhb_5d = ctx.get("sec9_5d_yi", 0.0), ctx.get("lhb_5d_yi", 0.0)
        if s9_5d <= -35.0:
            add("D4_机构赎回压力", "上交所行业ETF 5日净赎回", -4, f"9行业ETF 5日={s9_5d:+.1f}亿")
        if pd.notna(lhb_5d) and lhb_5d <= -40.0:
            add("D4_机构赎回压力", "龙虎榜机构5日净卖出", -4, f"机构专用5日={lhb_5d:+.1f}亿")
        wf = ctx.get("wflow_yi", 0.0)
        if wf <= -80.0:
            add("D4_机构赎回压力", "F154单日纯净重手净赎回", -12, f"单日纯净={wf:+.1f}亿<=-80亿")
        elif ctx.get("nt_tapering_stop", False):
            add("D4_机构赎回压力", "F153连买后停手断档", -5, f"连买后转净流出{wf:+.1f}亿")
        if ctx.get("wflow_5d_yi", 0.0) <= -250.0:
            add("D4_机构赎回压力", "F156五日纯净连续撤离", -8, f"5日纯净={ctx['wflow_5d_yi']:+.1f}亿<=-250亿")

    final_score = int(np.clip(score, 0, 100))
    return {
        "score": final_score,
        "raw_score": score,
        "tier": _tier_label(final_score),
        "items": [{"dim": d, "label": l, "pts": p, "detail": dt} for d, l, p, dt in items],
    }


def run_v3_scoring(settled_df_21: pd.DataFrame = None, settled_agg_21: pd.DataFrame = None) -> dict:
    t_start = time.time()
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # 1. Batch real-time Tencent qt (all indices + 22 ETFs + IOPV watch + 16 HW + 8 Fund HW)
    all_qt_syms = sorted(set(
        [s for s, _ in INDICES_SYMS] +
        [s for s, _ in CORE10_T1 + CORE10_T2] +
        [("sh" if v[1] == "SSE" else "sz") + c for c, v in ETFS.items()] +
        [s for s, _, _ in IOPV_WATCH] +
        [f"sh{c}" for c, _ in SECTOR_SSE_ETFS] +
        [s for s, _, _ in NT16_LIST] +
        [s for s, _ in FUND8_HWS]
    ))

    # Parallel network wave: qt + futures + 1m bars(33) + daily klines(36) + LHB + SSE extra shares
    bar_1m_syms = sorted(set([s for s, _ in CORE10_T1 + CORE10_T2] + [s for s, _, _ in NT16_LIST] + [s for s, _ in FUND8_HWS]))
    daily_syms = sorted(set(["sh000300"] + bar_1m_syms))

    with ThreadPoolExecutor(max_workers=24) as ex:
        fut_qt = ex.submit(_fetch_qt_batch, all_qt_syms)
        fut_futures_live = ex.submit(_fetch_futures_live)
        fut_if0_hist = ex.submit(_fetch_if0_daily)
        fut_lhb = ex.submit(_fetch_lhb_5d)
        futs_1m = {s: ex.submit(_fetch_1m_bars, s) for s in bar_1m_syms}
        futs_daily = {s: ex.submit(_fetch_sina_daily, s, 85 if s == "sh000300" else 35) for s in daily_syms}

        qt = fut_qt.result()
        fut_live = fut_futures_live.result()
        if0_hist = fut_if0_hist.result()
        lhb_rows, lhb_5d_net, lhb_last_dt = fut_lhb.result()
        bars_1m = {s: f.result() for s, f in futs_1m.items()}
        daily_hist = {s: f.result() for s, f in futs_daily.items()}

    # Determine effective live date & elapsed fraction
    c300_q = qt.get("sh000300", {})
    live_dt = c300_q.get("date") or today_str
    is_live_day = (live_dt == today_str) and (now.hour * 60 + now.minute >= 9 * 60 + 30)
    frac = trading_elapsed_fraction(now) if is_live_day else 1.0

    # 2. Load/Update SSE Extra10 Shares + 21-ETF settled shares for EOD score
    sse_sh_p = os.path.join(NT_DIR, "sse_shares_cache.parquet")
    szse_sh_p = os.path.join(NT_DIR, "szse_shares_cache.parquet")
    sse_ex_p = os.path.join(CACHE_DIR, "sse_extra10_shares.parquet")
    sh_sse = pd.read_parquet(sse_sh_p) if os.path.exists(sse_sh_p) else pd.DataFrame()
    sh_szse = pd.read_parquet(szse_sh_p) if os.path.exists(szse_sh_p) else pd.DataFrame()
    sh_ex = pd.read_parquet(sse_ex_p) if os.path.exists(sse_ex_p) else pd.DataFrame()

    # Check if settled_df_21 was passed from monitor; if not, compute from cache + Sina
    c300_bars = [b for b in daily_hist.get("sh000300", []) if b["date"] < live_dt]
    if not c300_bars and os.path.exists(os.path.join(CACHE_DIR, "indices_to_20261124.parquet")):
        idx_c = pd.read_parquet(os.path.join(CACHE_DIR, "indices_to_20261124.parquet"))
        c300_bars = idx_c[(idx_c["symbol"] == "sh000300") & (idx_c["date"] < live_dt)].tail(85).to_dict(orient="records")

    settled_dates_all = sorted(sh_sse["date"].unique().tolist()) if not sh_sse.empty else [b["date"] for b in c300_bars[-10:]]
    last_settled_dt = settled_dates_all[-1]

    # Fetch any missing recent SSE extra10 dates (for 588000 & 9 sector ETFs) concurrently
    extra_codes = {c for c, _ in SECTOR_SSE_ETFS}
    done_ex = set(sh_ex["date"].unique()) if not sh_ex.empty else set()
    recent_need = [d for d in settled_dates_all[-10:] if d not in done_ex]
    if recent_need:
        with ThreadPoolExecutor(max_workers=6) as ex:
            res_ex = list(ex.map(lambda dt: (dt, _fetch_sse_shares_day(dt, extra_codes)), recent_need))
        add_ex = [{"date": dt, "code": c, "shares_wan": v} for dt, mp in res_ex for c, v in mp.items()]
        if add_ex:
            sh_ex = pd.concat([sh_ex, pd.DataFrame(add_ex)], ignore_index=True).drop_duplicates(["date", "code"]).sort_values(["code", "date"])
            sh_ex.to_parquet(sse_ex_p, index=False)

    # Fetch missing recent daily bars for 9 sector ETFs if last_settled_dt > cache
    etf_ex_p = os.path.join(CACHE_DIR, "etf_extra10_to_20261124.parquet")
    etf_ex_df = pd.read_parquet(etf_ex_p) if os.path.exists(etf_ex_p) else pd.DataFrame()
    if etf_ex_df.empty or etf_ex_df["date"].max() < last_settled_dt:
        with ThreadPoolExecutor(max_workers=10) as ex:
            ex_bars = list(ex.map(lambda x: (x[0], x[1], _fetch_sina_daily("sh" + x[0], 35)), SECTOR_SSE_ETFS))
        new_ex_px = []
        for code, nm, bars in ex_bars:
            for b in bars:
                if b["date"] <= last_settled_dt:
                    new_ex_px.append({"date": b["date"], "code": code, "name": nm, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "volume": b["vol"], "amount": b["amt"], "pct_chg": np.nan})
        if new_ex_px:
            etf_ex_df = pd.concat([etf_ex_df, pd.DataFrame(new_ex_px)], ignore_index=True).drop_duplicates(["date", "code"], keep="last").sort_values(["code", "date"])
            etf_ex_df["pct_chg"] = etf_ex_df.groupby("code")["close"].pct_change() * 100.0

    # --- Compute Settled EOD Context for last_settled_dt ---
    # 1) Sector 9 ETFs 5d net flow (split-safe)
    sec9_rows = []
    sec9_1d_yi = sec9_5d_yi = 0.0
    sec_dates_6 = sorted([d for d in sh_ex["date"].unique() if d <= last_settled_dt])[-6:]
    if len(sec_dates_6) >= 2:
        sec_m = etf_ex_df[etf_ex_df["date"].isin(sec_dates_6)].merge(sh_ex[sh_ex["date"].isin(sec_dates_6)], on=["date", "code"], how="inner").sort_values(["code", "date"])
        sec_m["prev_sh"] = sec_m.groupby("code")["shares_wan"].shift(1)
        sec_m["sh_ret"] = sec_m["shares_wan"] / sec_m["prev_sh"] - 1.0
        sec_m["is_split"] = (sec_m["pct_chg"].abs() > 22) | ((sec_m["sh_ret"].abs() > 0.35) & (sec_m["pct_chg"].abs() > 15))
        sec_m["flow_yi"] = np.where(sec_m["is_split"], 0.0, (sec_m["shares_wan"] - sec_m["prev_sh"]) * 1e4 * sec_m["close"] / 1e8)
        for code, nm in SECTOR_SSE_ETFS:
            sub = sec_m[sec_m["code"] == code].sort_values("date")
            if len(sub) >= 2:
                f1 = float(sub[sub["date"] == last_settled_dt]["flow_yi"].sum())
                f5 = float(sub["flow_yi"].iloc[1:].sum())
                sec9_rows.append({"code": code, "name": nm, "flow_1d_yi": round(f1, 2), "flow_5d_yi": round(f5, 2)})
                if code in SEC9_CODES:
                    sec9_1d_yi += f1
                    sec9_5d_yi += f5

    # 2) 21+1 NT ETFs settled metrics up to last_settled_dt
    e588_px = etf_ex_df[etf_ex_df["code"] == "588000"].copy()
    e588_px["exch"], e588_px["idx_grp"], e588_px["team"], e588_px["nt_w"] = "SSE", "STAR50", "T2", 0.25
    e588_sh = sh_ex[sh_ex["code"] == "588000"]
    e588_df = e588_px.merge(e588_sh, on=["date", "code"], how="left").sort_values("date")
    e588_df["prev_sh"] = e588_df["shares_wan"].shift(1)
    e588_df["net_flow_yi"] = np.where(e588_df["pct_chg"].abs() > 25, 0.0, (e588_df["shares_wan"] - e588_df["prev_sh"]) * 1e4 * e588_df["close"] / 1e8)
    e588_df["nt_w_flow_yi"] = e588_df["net_flow_yi"] * 0.25

    if settled_df_21 is not None and not settled_df_21.empty:
        etf22_df = pd.concat([settled_df_21, e588_df[settled_df_21.columns.intersection(e588_df.columns)]], ignore_index=True)
    else:
        px21_c = pd.read_parquet(os.path.join(CACHE_DIR, "etf21_to_20261124.parquet"))
        sh21 = pd.concat([sh_sse, sh_szse], ignore_index=True).drop_duplicates(["date", "code"])
        m21 = px21_c[px21_c["date"] >= "2026-09-01"].merge(sh21, on=["date", "code"], how="left").sort_values(["code", "date"])
        m21["prev_sh"] = m21.groupby("code")["shares_wan"].shift(1)
        m21["net_flow_yi"] = np.where(m21["pct_chg"].abs() > 25, 0.0, (m21["shares_wan"] - m21["prev_sh"]) * 1e4 * m21["close"] / 1e8)
        m21["nt_w_flow_yi"] = m21["net_flow_yi"] * m21["nt_w"].astype(float)
        etf22_df = pd.concat([m21, e588_df[m21.columns.intersection(e588_df.columns)]], ignore_index=True)

    etf22_s = etf22_df[etf22_df["date"] <= last_settled_dt].copy()
    etf22_s["aum_yi"] = etf22_s["shares_wan"] * 1e4 * etf22_s["close"] / 1e8
    agg22 = etf22_s.groupby("date").agg(
        tot_amt_yi=("amount", lambda s: s.sum() / 1e8),
        wflow_yi=("nt_w_flow_yi", "sum"),
        aum_yi=("aum_yi", "sum"),
        t1_flow_yi=("net_flow_yi", lambda s: s[etf22_s.loc[s.index, "team"] == "T1"].sum()),
        t2_flow_yi=("net_flow_yi", lambda s: s[etf22_s.loc[s.index, "team"] == "T2"].sum()),
        n_sh=("shares_wan", lambda s: int(s.notna().sum())),
    ).reset_index().sort_values("date")
    c10_s = etf22_s[etf22_s["code"].isin(CORE10_CODES)].groupby("date")["amount"].sum().rename("core10_amt_yi").reset_index()
    c10_s["core10_amt_yi"] = c10_s["core10_amt_yi"] / 1e8
    agg22 = agg22.merge(c10_s, on="date", how="left")
    agg22["e22_spike"] = agg22["tot_amt_yi"] / agg22["tot_amt_yi"].rolling(20, min_periods=5).median().shift(1)
    agg22["c10_spike"] = agg22["core10_amt_yi"] / agg22["core10_amt_yi"].rolling(20, min_periods=5).median().shift(1)
    agg22["wflow_5d"] = agg22["wflow_yi"].rolling(5, min_periods=1).sum()
    consec, c_run = [], 0
    for v, nsh in zip(agg22["wflow_yi"].fillna(0), agg22["n_sh"].fillna(0)):
        c_run = c_run + 1 if (nsh > 0 and v >= 30.0) else 0
        consec.append(c_run)
    agg22["nt_tapering_stop"] = ((pd.Series(consec).shift(1).fillna(0) >= 3) & (agg22["wflow_5d"].shift(1).fillna(0) >= 220.0) & (agg22["wflow_yi"] <= 0.0)).astype(int)

    # Settled EOD row
    eod_row = agg22[agg22["date"] == last_settled_dt].iloc[-1]
    prev_aum = float(agg22[agg22["date"] < last_settled_dt]["aum_yi"].iloc[-1]) if len(agg22) >= 2 else float(eod_row["aum_yi"])
    eod_wflow_pct = (float(eod_row["wflow_yi"]) / prev_aum * 100.0) if prev_aum > 0 else 0.0

    # --- Compute Live Intraday Context (today = live_dt) ---
    # Core 10 20d baselines (strictly < live_dt)
    core10_rows = []
    t1_cnt16 = t2_cnt16 = 0
    core10_live_amt = 0.0
    core10_med20_sum = 0.0
    for sym, nm in CORE10_T1 + CORE10_T2:
        code = sym[-6:]
        grp = "一队" if code in T1_CORE_CODES else "二队"
        q = qt.get(sym, {})
        cur_amt = float(q.get("amt_yi") or 0.0)
        core10_live_amt += cur_amt
        bars_d = [b for b in daily_hist.get(sym, []) if b["date"] < live_dt]
        med20 = float(np.median([b["amt"] / 1e8 for b in bars_d[-20:]])) if len(bars_d) >= 5 else np.nan
        if pd.isna(med20):
            sub_c = etf22_s[etf22_s["code"] == code].tail(20)
            med20 = float(sub_c["amount"].median() / 1e8) if len(sub_c) else np.nan
        if pd.notna(med20):
            core10_med20_sum += med20
        proj_amt = cur_amt / frac
        spk_i = proj_amt / med20 if (pd.notna(med20) and med20 > 0) else 0.0
        if spk_i >= 1.6:
            if code in T1_CORE_CODES:
                t1_cnt16 += 1
            else:
                t2_cnt16 += 1
        # 5-min sync pulse from 1m bars
        _, _, m_bars = bars_1m.get(sym, (sym, np.nan, []))
        peak_5m_mult = 0.0
        peak_hhmm = ""
        if len(m_bars) >= 15:
            am_a = [a for hh, _, a in m_bars if hh <= "1130"]
            base_m = max(1e5, float(np.mean(am_a)) if len(am_a) >= 15 else float(np.median([a for _, _, a in m_bars])))
            for idx_m in range(4, len(m_bars)):
                w5 = m_bars[idx_m - 4:idx_m + 1]
                mult = max(a / base_m for _, _, a in w5)
                if mult > peak_5m_mult:
                    peak_5m_mult = mult
                    peak_hhmm = w5[-1][0]
        core10_rows.append({
            "code": code, "name": nm, "team": grp, "pct": round(float(q.get("pct") or 0.0), 2),
            "amt_yi": round(cur_amt, 2), "proj_spike": round(spk_i, 2),
            "peak_5m_mult": round(peak_5m_mult, 1), "peak_hhmm": peak_hhmm,
        })

    # Total 22-ETF live turnover spike
    etf22_live_amt = sum(float(qt.get(("sh" if v[1] == "SSE" else "sz") + c, {}).get("amt_yi") or 0.0) for c, v in ETFS.items()) + float(qt.get("sh588000", {}).get("amt_yi") or 0.0)
    etf22_med20 = float(agg22[agg22["date"] < live_dt]["tot_amt_yi"].tail(20).median()) if len(agg22[agg22["date"] < live_dt]) >= 5 else np.nan
    core10_med20_agg = float(agg22[agg22["date"] < live_dt]["core10_amt_yi"].tail(20).median()) if len(agg22[agg22["date"] < live_dt]) >= 5 else core10_med20_sum
    core10_proj_spike = (core10_live_amt / frac) / core10_med20_agg if core10_med20_agg > 0 else 0.0
    etf22_proj_spike = (etf22_live_amt / frac) / etf22_med20 if (pd.notna(etf22_med20) and etf22_med20 > 0) else 0.0
    live_etf_spike = max(core10_proj_spike, etf22_proj_spike)

    # 16 Heavyweights live evaluation + 1m sync window
    hw16_rows = []
    hw16_sync_cnt = 0
    sq_hits = {sq: 0 for sq in NT16_SQUADS}
    for sym, nm, sq in NT16_LIST:
        q = qt.get(sym, {})
        now_p, prev_p, lo_p = float(q.get("now") or 0.0), float(q.get("prev") or 0.0), float(q.get("low") or 0.0)
        pct = float(q.get("pct") or 0.0)
        cur_amt = float(q.get("amt_yi") or 0.0)
        pullup = ((now_p - lo_p) / prev_p * 100.0) if prev_p > 0 else 0.0
        bars_d = [b for b in daily_hist.get(sym, []) if b["date"] < live_dt]
        med20 = float(np.median([b["amt"] / 1e8 for b in bars_d[-20:]])) if len(bars_d) >= 5 else np.nan
        spk_i = (cur_amt / frac) / med20 if (pd.notna(med20) and med20 > 0) else 0.0
        is_sync = (spk_i >= 1.4) and (pct >= 0.0 or pullup >= 1.2)
        if is_sync:
            hw16_sync_cnt += 1
            sq_hits[sq] += 1
        hw16_rows.append({
            "code": sym[-6:], "name": nm, "squad": sq, "pct": round(pct, 2),
            "pullup_pct": round(pullup, 2), "proj_spike": round(spk_i, 2), "is_sync": bool(is_sync),
        })
    sq_active_cnt = sum(1 for v in sq_hits.values() if v >= 1)
    big4_oil_pct = float(np.nanmean([qt.get(s, {}).get("pct", np.nan) for s in BIG4_OIL_SYMS]))
    csi1000_pct = float(qt.get("sh000852", {}).get("pct", 0.0) or 0.0)

    # 1m cross-asset best 5m resonance window (10 Core ETFs + 16 Heavyweights)
    m_meta = {s: (nm, "T1") for s, nm in CORE10_T1}
    m_meta.update({s: (nm, "T2") for s, nm in CORE10_T2})
    m_meta.update({s: (nm, "HW") for s, nm, _ in NT16_LIST})
    sym_1m_stats = {}
    for sym, (nm, grp) in m_meta.items():
        _, _, m_bars = bars_1m.get(sym, (sym, np.nan, []))
        if not m_bars:
            continue
        am_a = [a for hh, _, a in m_bars if hh <= "1130"]
        base_m = max(1e5, float(np.mean(am_a)) if len(am_a) >= 15 else float(np.median([a for _, _, a in m_bars])))
        sym_1m_stats[sym] = {"base": base_m, "by_t": {hh: (px, a) for hh, px, a in m_bars}}
    all_mins = sorted({hh for st in sym_1m_stats.values() for hh in st["by_t"] if hh >= "0945"})
    best_win = {"window": "-", "t1_hits": [], "t2_hits": [], "hw_hits": [], "etf_burst_yi": 0.0}
    best_w_sc = -1.0
    for i in range(len(all_mins)):
        wm = all_mins[max(0, i - 4):i + 1]
        if len(wm) < 3:
            continue
        t1h, t2h, hwh = [], [], []
        etf_yi = 0.0
        for sym, st in sym_1m_stats.items():
            nm, grp = m_meta[sym]
            pts = [st["by_t"][m] for m in wm if m in st["by_t"]]
            if not pts:
                continue
            mult = max(a / st["base"] for _, a in pts)
            amt_yi = sum(a for _, a in pts) / 1e8
            ret_w = (pts[-1][0] / pts[0][0] - 1.0) * 100.0 if pts[0][0] > 0 else 0.0
            if grp == "T1":
                etf_yi += amt_yi
                if mult >= 4.0:
                    t1h.append((nm, round(mult, 1), round(amt_yi, 2)))
            elif grp == "T2":
                etf_yi += amt_yi
                if mult >= 4.0:
                    t2h.append((nm, round(mult, 1), round(amt_yi, 2)))
            else:
                if mult >= 2.5 and ret_w >= -0.05:
                    hwh.append((nm, round(mult, 1), round(ret_w, 2)))
        sc = len(t1h) * 3.0 + len(t2h) * 3.0 + len(hwh) * 1.2 + min(10.0, etf_yi / 5.0)
        if sc > best_w_sc:
            best_w_sc = sc
            best_win = {
                "window": f"{wm[0][:2]}:{wm[0][2:]}至{wm[-1][:2]}:{wm[-1][2:]}",
                "t1_hits": sorted(t1h, key=lambda x: -x[1]),
                "t2_hits": sorted(t2h, key=lambda x: -x[1]),
                "hw_hits": sorted(hwh, key=lambda x: -x[1]),
                "etf_burst_yi": round(etf_yi, 2),
            }

    # Dim 3: Futures Basis & Volume Spike (Live + Settled)
    spot_map = {"IF0": "sh000300", "IH0": "sh000016", "IC0": "sh000905", "IM0": "sh000852"}
    fut_basis_rows = {}
    for fsym, ssym in spot_map.items():
        fq = fut_live.get(fsym, {})
        sq = qt.get(ssym, {})
        fp, sp = fq.get("now", np.nan), sq.get("now", np.nan)
        bas = ((fp / sp - 1.0) * 100.0) if (pd.notna(fp) and pd.notna(sp) and sp > 0) else np.nan
        fut_basis_rows[fsym] = {
            "fut_now": round(float(fp), 2) if pd.notna(fp) else None,
            "spot_now": round(float(sp), 2) if pd.notna(sp) else None,
            "basis_pct": round(float(bas), 2) if pd.notna(bas) else None,
            "fut_pct": round(float(fq.get("pct") or 0.0), 2),
            "vol": int(fq.get("vol") or 0),
        }
    if0_bars = if0_hist[if0_hist["date"] < live_dt] if not if0_hist.empty else pd.DataFrame()
    if len(if0_bars) < 10 and os.path.exists(os.path.join(CACHE_DIR, "futures_to_20261124.parquet")):
        f_c = pd.read_parquet(os.path.join(CACHE_DIR, "futures_to_20261124.parquet"))
        if0_bars = f_c[f_c["date"] < live_dt][["date", "IF0_close", "IF0_vol"]].rename(columns={"IF0_close": "close", "IF0_vol": "vol"})
    if0_med20 = float(if0_bars.tail(20)["vol"].median()) if len(if0_bars) >= 5 else np.nan
    if0_live_vol = float(fut_live.get("IF0", {}).get("vol") or 0.0)
    if0_proj_spike = (if0_live_vol / frac) / if0_med20 if (pd.notna(if0_med20) and if0_med20 > 0) else 0.0
    if0_live_bas = fut_basis_rows["IF0"]["basis_pct"] or 0.0

    prev_c300 = c300_bars[-1]["close"] if c300_bars else np.nan
    prev_if0_c = float(if0_bars.iloc[-1]["close"]) if len(if0_bars) else np.nan
    prev_if0_bas = ((prev_if0_c / prev_c300 - 1.0) * 100.0) if (pd.notna(prev_if0_c) and pd.notna(prev_c300) and prev_c300 > 0) else 0.0
    if0_bas_chg1 = if0_live_bas - prev_if0_bas

    # Dim 4: Live IOPV + Fund-8 Heavyweights
    iopv_rows = []
    for sym, nm, cat in IOPV_WATCH:
        q = qt.get(sym, {})
        disc = q.get("disc_pct", np.nan)
        iopv_rows.append({"code": sym[-6:], "name": nm, "cat": cat, "pct": round(float(q.get("pct") or 0.0), 2), "disc_pct": round(float(disc), 2) if pd.notna(disc) else None})
    iopv_deep_cnt = sum(1 for r in iopv_rows if r["disc_pct"] is not None and r["disc_pct"] <= -0.25)

    fund8_rows = []
    fund8_dump_cnt = 0
    for sym, nm in FUND8_HWS:
        q = qt.get(sym, {})
        now_p, op_p = float(q.get("now") or 0.0), float(q.get("open") or 0.0)
        cur_amt = float(q.get("amt_yi") or 0.0)
        oc_pct = ((now_p / op_p - 1.0) * 100.0) if op_p > 0 else 0.0
        bars_d = [b for b in daily_hist.get(sym, []) if b["date"] < live_dt]
        med20 = float(np.median([b["amt"] / 1e8 for b in bars_d[-20:]])) if len(bars_d) >= 5 else np.nan
        spk_i = (cur_amt / frac) / med20 if (pd.notna(med20) and med20 > 0) else 0.0
        _, _, m_bars = bars_1m.get(sym, (sym, np.nan, []))
        pm14_pct, pm14_vr = 0.0, 0.0
        if m_bars:
            am_a = [a for hh, _, a in m_bars if hh <= "1130"]
            pm14 = [(hh, px, a) for hh, px, a in m_bars if hh >= "1400"]
            if pm14:
                pm14_pct = (pm14[-1][1] / pm14[0][1] - 1.0) * 100.0 if pm14[0][1] > 0 else 0.0
                pm14_vr = float(np.mean([a for _, _, a in pm14])) / max(1.0, float(np.mean(am_a)) if am_a else 1.0)
        is_dump = ((oc_pct <= -2.0 and spk_i >= 1.2) or (pm14_pct <= -1.5 and pm14_vr >= 1.2))
        if is_dump:
            fund8_dump_cnt += 1
        fund8_rows.append({"code": sym[-6:], "name": nm, "day_pct": round(float(q.get("pct") or 0.0), 2), "oc_pct": round(oc_pct, 2), "pm14_pct": round(pm14_pct, 2), "proj_spike": round(spk_i, 2), "is_dump": bool(is_dump)})

    # Dim 5: Market Context + Official News (Live)
    c300_now = float(c300_q.get("now") or (c300_bars[-1]["close"] if c300_bars else 0.0))
    c300_prev = float(c300_q.get("prev") or (c300_bars[-1]["close"] if c300_bars else 0.0))
    c300_low = float(c300_q.get("low") or c300_now)
    c300_pullup = ((c300_now - c300_low) / c300_prev * 100.0) if c300_prev > 0 else 0.0
    closes_live = [b["close"] for b in c300_bars[-59:]] + [c300_now]
    ma20_live = float(np.mean(closes_live[-20:])) if len(closes_live) >= 20 else c300_now
    dd60_live = (c300_now / max(closes_live) - 1.0) * 100.0 if closes_live else 0.0
    ret20_live = (c300_now / closes_live[-21] - 1.0) * 100.0 if len(closes_live) >= 21 else 0.0

    off_intra, off_eod = _check_official_nt_5d(live_dt, last_settled_dt)

    live_ctx = {
        "is_weak": (c300_now < ma20_live) or (dd60_live <= -6.0),
        "is_deep": dd60_live <= -8.0,
        "is_high": (c300_now > ma20_live) and (ret20_live >= 5.0),
        "is_bubble": (c300_now > ma20_live) and (ret20_live >= 15.0),
        "weak_reason": f"300={c300_now:.1f} vs MA20={ma20_live:.1f}, 60日回撤={dd60_live:.1f}%",
        "c300_dd60": dd60_live, "c300_ret20": ret20_live,
        "official_hits": off_intra,
        "etf_spike": live_etf_spike,
        "c300_pullup": c300_pullup,
        "t1_cnt16": t1_cnt16, "t2_cnt16": t2_cnt16,
        "lag_5d_wflow": float(eod_row["wflow_5d"]),
        "hw16_sync_cnt": hw16_sync_cnt, "sq_active_cnt": sq_active_cnt,
        "big4_oil_pct": big4_oil_pct, "csi1000_pct": csi1000_pct,
        "if0_spike": if0_proj_spike, "if0_basis_pct": if0_live_bas, "if0_basis_chg1": if0_bas_chg1,
        "is_deliv": is_third_friday(datetime.strptime(live_dt, "%Y-%m-%d")),
        "fund8_dump_cnt": fund8_dump_cnt,
        "iopv_deep_disc_cnt": iopv_deep_cnt,
        "lag_sec9_5d": sec9_5d_yi, "lag_lhb_5d": lhb_5d_net,
    }
    live_res = _compute_score_breakdown(live_ctx, mode="live")

    # --- Compute Settled EOD Score on last_settled_dt ---
    # Compute historical indicators on last_settled_dt cleanly
    c300_s_bars = [b for b in c300_bars if b["date"] <= last_settled_dt]
    if not c300_s_bars and len(c300_bars):
        c300_s_bars = c300_bars
    if c300_s_bars and c300_s_bars[-1]["date"] == last_settled_dt:
        s_bar = c300_s_bars[-1]
        s_prev = c300_s_bars[-2]["close"] if len(c300_s_bars) >= 2 else s_bar["close"]
        s_pullup = ((s_bar["close"] - s_bar["low"]) / s_prev * 100.0) if s_prev > 0 else 0.0
        s_closes = [b["close"] for b in c300_s_bars[-60:]]
        s_ma20 = float(np.mean(s_closes[-20:])) if len(s_closes) >= 20 else s_bar["close"]
        s_dd60 = (s_bar["close"] / max(s_closes) - 1.0) * 100.0
        s_ret20 = (s_bar["close"] / s_closes[-21] - 1.0) * 100.0 if len(s_closes) >= 21 else 0.0
        s_c300_c = s_bar["close"]
    else:
        s_c300_c, s_ma20, s_dd60, s_ret20, s_pullup = c300_now, ma20_live, dd60_live, ret20_live, 0.0

    # EOD 16 heavyweights + 8 fund dump + IF0 on last_settled_dt
    eod_hw_cnt = 0
    eod_sq_hits = {sq: 0 for sq in NT16_SQUADS}
    eod_b4o = []
    for sym, nm, sq in NT16_LIST:
        bs = [b for b in daily_hist.get(sym, []) if b["date"] <= last_settled_dt]
        if len(bs) >= 6:
            cur_b, prv_b = bs[-1], bs[-2]
            med20_b = float(np.median([x["amt"] for x in bs[-21:-1]]))
            ret_b = (cur_b["close"] / prv_b["close"] - 1.0) * 100.0
            pu_b = (cur_b["close"] - cur_b["low"]) / prv_b["close"] * 100.0
            spk_b = cur_b["amt"] / med20_b if med20_b > 0 else 0.0
            if spk_b >= 1.4 and (ret_b >= 0.0 or pu_b >= 1.2):
                eod_hw_cnt += 1
                eod_sq_hits[sq] += 1
            if sym in BIG4_OIL_SYMS:
                eod_b4o.append(ret_b)
    eod_sq_cnt = sum(1 for v in eod_sq_hits.values() if v >= 1)

    eod_f8_cnt = 0
    for sym, _ in FUND8_HWS:
        bs = [b for b in daily_hist.get(sym, []) if b["date"] <= last_settled_dt]
        if len(bs) >= 6:
            cur_b = bs[-1]
            med20_b = float(np.median([x["amt"] for x in bs[-21:-1]]))
            oc_b = (cur_b["close"] / cur_b["open"] - 1.0) * 100.0 if cur_b["open"] > 0 else 0.0
            if oc_b <= -2.0 and (cur_b["amt"] / med20_b if med20_b > 0 else 0.0) >= 1.2:
                eod_f8_cnt += 1

    if0_s = if0_hist[if0_hist["date"] <= last_settled_dt] if not if0_hist.empty else pd.DataFrame()
    if len(if0_s) >= 6:
        if0_s_spk = float(if0_s.iloc[-1]["vol"]) / float(if0_s.iloc[-21:-1]["vol"].median())
        if0_s_bas = ((float(if0_s.iloc[-1]["close"]) / s_c300_c - 1.0) * 100.0) if s_c300_c > 0 else 0.0
        prev_c3_2 = c300_s_bars[-2]["close"] if len(c300_s_bars) >= 2 else s_c300_c
        prev_if_2 = float(if0_s.iloc[-2]["close"])
        if0_s_bc1 = if0_s_bas - ((prev_if_2 / prev_c3_2 - 1.0) * 100.0 if prev_c3_2 > 0 else 0.0)
    else:
        if0_s_spk, if0_s_bas, if0_s_bc1 = 1.0, 0.0, 0.0

    # csi1000 settled pct
    c1k_bars = _fetch_sina_daily("sh000852", 10)
    c1k_s = [b for b in c1k_bars if b["date"] <= last_settled_dt]
    c1k_s_pct = ((c1k_s[-1]["close"] / c1k_s[-2]["close"] - 1.0) * 100.0) if len(c1k_s) >= 2 else 0.0

    eod_spk = max(float(eod_row["c10_spike"] or 0.0), float(eod_row["e22_spike"] or 0.0))
    eod_ctx = {
        "is_weak": (s_c300_c < s_ma20) or (s_dd60 <= -6.0),
        "is_deep": s_dd60 <= -8.0,
        "is_high": (s_c300_c > s_ma20) and (s_ret20 >= 5.0),
        "is_bubble": (s_c300_c > s_ma20) and (s_ret20 >= 15.0),
        "weak_reason": f"300={s_c300_c:.1f} vs MA20={s_ma20:.1f}, 60日回撤={s_dd60:.1f}%",
        "c300_dd60": s_dd60, "c300_ret20": s_ret20,
        "official_hits": off_eod,
        "etf_spike": eod_spk, "c300_pullup": s_pullup,
        "wflow_yi": float(eod_row["wflow_yi"]), "wflow_pct_aum": eod_wflow_pct,
        "wflow_5d_yi": float(eod_row["wflow_5d"]),
        "t1_flow_yi": float(eod_row["t1_flow_yi"]), "t2_flow_yi": float(eod_row["t2_flow_yi"]),
        "hw16_sync_cnt": eod_hw_cnt, "sq_active_cnt": eod_sq_cnt,
        "big4_oil_pct": float(np.mean(eod_b4o)) if eod_b4o else 0.0, "csi1000_pct": c1k_s_pct,
        "if0_spike": if0_s_spk, "if0_basis_pct": if0_s_bas, "if0_basis_chg1": if0_s_bc1,
        "is_deliv": is_third_friday(datetime.strptime(last_settled_dt, "%Y-%m-%d")),
        "fund8_dump_cnt": eod_f8_cnt,
        "sec9_5d_yi": sec9_5d_yi, "lhb_5d_yi": lhb_5d_net,
        "nt_tapering_stop": bool(int(eod_row["nt_tapering_stop"]) == 1),
    }
    eod_res = _compute_score_breakdown(eod_ctx, mode="eod")

    elapsed = round(time.time() - t_start, 2)
    return {
        "elapsed_sec": elapsed,
        "live_date": live_dt,
        "settled_date": last_settled_dt,
        "elapsed_frac": round(frac, 3),
        "live_score": live_res,
        "settled_eod_score": eod_res,
        "dim1_core10": core10_rows,
        "dim1_live_spike": round(live_etf_spike, 2),
        "dim1_core10_live_amt_yi": round(core10_live_amt, 2),
        "dim1_etf22_live_amt_yi": round(etf22_live_amt, 2),
        "dim1_t1_cnt16": t1_cnt16, "dim1_t2_cnt16": t2_cnt16,
        "dim1_best_5m_window": best_win,
        "dim1_eod_summary": {
            "wflow_1d_yi": round(float(eod_row["wflow_yi"]), 1),
            "wflow_5d_yi": round(float(eod_row["wflow_5d"]), 1),
            "t1_1d_yi": round(float(eod_row["t1_flow_yi"]), 1),
            "t2_1d_yi": round(float(eod_row["t2_flow_yi"]), 1),
            "wflow_pct_aum": round(eod_wflow_pct, 2),
            "nt_tapering_stop": bool(int(eod_row["nt_tapering_stop"]) == 1),
        },
        "dim2_hw16_rows": hw16_rows,
        "dim2_hw16_sync_cnt": hw16_sync_cnt,
        "dim2_sq_active_cnt": sq_active_cnt,
        "dim2_big4_oil_pct": round(big4_oil_pct, 2),
        "dim2_csi1000_pct": round(csi1000_pct, 2),
        "dim3_futures": fut_basis_rows,
        "dim3_if0_proj_spike": round(if0_proj_spike, 2),
        "dim3_if0_basis_chg1": round(if0_bas_chg1, 2),
        "dim4_iopv_rows": iopv_rows,
        "dim4_iopv_deep_cnt": iopv_deep_cnt,
        "dim4_fund8_rows": fund8_rows,
        "dim4_fund8_dump_cnt": fund8_dump_cnt,
        "dim4_sec9_1d_yi": round(sec9_1d_yi, 2),
        "dim4_sec9_5d_yi": round(sec9_5d_yi, 2),
        "dim4_sec_etf_rows": sec9_rows,
        "dim4_lhb_5d_yi": lhb_5d_net,
        "dim4_lhb_rows": lhb_rows,
        "dim5_context": {
            "c300_now": round(c300_now, 2), "ma20": round(ma20_live, 2),
            "dd60_pct": round(dd60_live, 2), "ret20_pct": round(ret20_live, 2),
            "pullup_pct": round(c300_pullup, 2), "official_intra": off_intra, "official_eod": off_eod,
        },
    }


def print_v3_report(v3: dict):
    ls, es = v3["live_score"], v3["settled_eod_score"]
    print(f"\n=== V3.0 五维国家队救市与机构对冲纯整数打分卡 (抓取耗时 {v3['elapsed_sec']}s) ===")
    print(f"【今日盘中实时分 ({v3['live_date']}, 进度 {v3['elapsed_frac']*100:.0f}%)】总分 = {ls['score']} / 100 -> 【{ls['tier']}】")
    for it in ls["items"]:
        print(f"  {it['pts']:+3d}分 | [{it['dim']}] {it['label']} ({it['detail']})")
    print(f"【最新盘后实锤分 ({v3['settled_date']})】总分 = {es['score']} / 100 -> 【{es['tier']}】")
    for it in es["items"]:
        print(f"  {it['pts']:+3d}分 | [{it['dim']}] {it['label']} ({it['detail']})")

    print(f"\n[V3 维度一 · 10核心宽基ETF] 10核实时{v3['dim1_core10_live_amt_yi']:.1f}亿 / 22池实时{v3['dim1_etf22_live_amt_yi']:.1f}亿 | 量比={v3['dim1_live_spike']:.2f}x | 一队{v3['dim1_t1_cnt16']}/5, 二队{v3['dim1_t2_cnt16']}/5 (>=1.6x)")
    bw = v3["dim1_best_5m_window"]
    print(f"  -> 1分钟同步最佳5m窗({bw['window']}): 10核ETF5m={bw['etf_burst_yi']:.2f}亿 | 一队爆发={len(bw['t1_hits'])} | 二队爆发={len(bw['t2_hits'])} | 16权重同步={len(bw['hw_hits'])}")
    print("  -> 10核心分队明细: " + " | ".join(f"{r['name']}({r['pct']:+.2f}%/{r['proj_spike']:.2f}x)" for r in v3["dim1_core10"]))

    print(f"[V3 维度二 · 16只国家队权重(4大方阵)] 放量同步={v3['dim2_hw16_sync_cnt']}/16 ({v3['dim2_sq_active_cnt']}/4方阵) | 银行石油均值={v3['dim2_big4_oil_pct']:+.2f}% vs 中证1000={v3['dim2_csi1000_pct']:+.2f}%")
    sync_hws = [r for r in v3["dim2_hw16_rows"] if r["is_sync"]]
    if sync_hws:
        print("  -> 放量止跌权重: " + " | ".join(f"{r['name']}({r['pct']:+.2f}%/{r['proj_spike']:.2f}x)" for r in sync_hws[:8]))
    else:
        top_hws = sorted(v3["dim2_hw16_rows"], key=lambda x: -x["pct"])[:6]
        print("  -> 领涨权重样本: " + " | ".join(f"{r['name']}({r['pct']:+.2f}%/{r['proj_spike']:.2f}x)" for r in top_hws))

    f3 = v3["dim3_futures"]
    f_line = " | ".join(f"{k}={v['fut_now']}({v['fut_pct']:+.2f}%, 基差{v['basis_pct']:+.2f}%)" for k, v in f3.items() if v["fut_now"] is not None)
    print(f"[V3 维度三 · 期现联动] IF0预计量比={v3['dim3_if0_proj_spike']:.2f}x | 基差1d变化={v3['dim3_if0_basis_chg1']:+.2f}% | {f_line}")

    c5 = v3["dim5_context"]
    print(f"[V3 维度四 · 机构赎回对冲] IOPV深折价={v3['dim4_iopv_deep_cnt']}/14 | 公募8重仓砸盘={v3['dim4_fund8_dump_cnt']}/8 | 上交所9行业5日={v3['dim4_sec9_5d_yi']:+.1f}亿 | 龙虎榜机构5日={v3['dim4_lhb_5d_yi']:+.1f}亿")
    print(f"[V3 维度五 · 弱势背景与政策] 300={c5['c300_now']:.2f} (vs MA20={c5['ma20']:.2f}, 60日回撤={c5['dd60_pct']:+.2f}%, 20日={c5['ret20_pct']:+.2f}%, 日内拉起={c5['pullup_pct']:+.2f}%) | 近5日官宣={len(c5['official_intra'])}条")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = run_v3_scoring()
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print_v3_report(out)
