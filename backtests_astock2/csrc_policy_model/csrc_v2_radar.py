#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V2.0 Upgrade Module for National Team & Institutional Redemption Monitor (RD010 / RD019).
1. 1-minute cross-asset synchronized basket radar (Team 1/2 ETFs + 10 state heavyweights) -> 4 regimes + L0~L3 ladder.
2. 3-layer Institutional Redemption Radar:
   - Layer 1 (Settled Official): SSE 10 flagship non-NT institutional/sector ETF 1d & 5d net shares flow.
   - Layer 2 (Live Intraday Proxy): Real-time ETF IOPV premium/discount (p77) + 8 public-fund heavyweights 14:00+ dump detector.
   - Layer 3 (Settled LHB): Eastmoney daily Institutional Seat (机构专用) 5-day net buy/sell.
   - Honest boundary: Off-exchange active mutual funds have NO public daily redemption data (quarterly reports only).
"""
import json, os, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import requests

os.environ["NO_PROXY"] = "*"

T1_ETFS = [("sh510300", "华泰300"), ("sh510310", "易方达300"), ("sh510330", "华夏300"), ("sh510050", "上证50")]
T2_ETFS = [("sh510500", "南方500"), ("sh512100", "南方1000"), ("sz159915", "创业板ETF"), ("sh588080", "易方达科创50")]
STATE_HWS = [
    ("sh601857", "中国石油"), ("sh600028", "中国石化"), ("sh601398", "工商银行"),
    ("sh601288", "农业银行"), ("sh601988", "中国银行"), ("sh601318", "中国平安"),
    ("sh600519", "贵州茅台"), ("sh600941", "中国移动"), ("sh601088", "中国神华"), ("sh600900", "长江电力"),
]
SECTOR_SSE_ETFS = [
    ("588000", "科创50ETF"), ("512000", "券商ETF"), ("512880", "证券ETF"), ("512480", "半导体ETF"),
    ("512010", "医药ETF"), ("512690", "酒ETF"), ("515030", "新能车ETF"), ("515790", "光伏ETF"),
    ("510880", "红利ETF"), ("512800", "银行ETF"),
]
IOPV_WATCH = [
    ("sh510300", "300ETF", "宽基"), ("sh510050", "50ETF", "宽基"), ("sh510500", "500ETF", "宽基"),
    ("sh512100", "1000ETF", "宽基"), ("sz159915", "创业板ETF", "宽基"), ("sh588000", "科创50ETF", "宽基"),
    ("sh512000", "券商ETF", "行业"), ("sh512880", "证券ETF", "行业"), ("sh512480", "半导体ETF", "行业"),
    ("sh512010", "医药ETF", "行业"), ("sh512690", "酒ETF", "行业"), ("sh515030", "新能车ETF", "行业"),
    ("sh510880", "红利ETF", "行业"), ("sz159995", "芯片ETF", "行业"),
]
FUND_HEAVYWEIGHTS = [
    ("sz300750", "宁德时代"), ("sz300308", "中际旭创"), ("sz300274", "阳光电源"), ("sh688256", "寒武纪"),
    ("sz300059", "东方财富"), ("sz002475", "立讯精密"), ("sh603259", "药明康德"), ("sz000858", "五粮液"),
]


def _fetch_1m_bars(sym: str):
    try:
        u = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={sym}"
        j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=5).read().decode())
        d = j["data"][sym]
        prev_c = float(d["qt"][sym][4])
        bars = d["data"]["data"]
        rows, prev_v = [], 0.0
        for b in bars:
            ps = b.split(" ")
            hhmm, px, cum_v = ps[0], float(ps[1]), float(ps[2])
            dv = max(0.0, cum_v - prev_v)
            prev_v = cum_v
            rows.append((hhmm, px, dv * px * 100.0))
        return sym, prev_c, rows
    except Exception:
        return sym, np.nan, []


def fetch_v2_1m_sync_radar(proj_spike: float = np.nan, csi300_pct: float = np.nan):
    all_items = [(s, n, "T1") for s, n in T1_ETFS] + [(s, n, "T2") for s, n in T2_ETFS] + [(s, n, "HW") for s, n in STATE_HWS]
    res_map = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        for sym, prev_c, rows in ex.map(lambda x: _fetch_1m_bars(x[0]), all_items):
            if rows:
                res_map[sym] = (prev_c, rows)
    if not res_map:
        return {"ok": False, "regime": "分钟数据获取失败", "alert_level": "L0"}

    # Build aligned minute timeline & per-symbol baseline (AM avg if PM bars exist, else median)
    all_mins = sorted({r[0] for _, rows in res_map.values() for r in rows})
    meta = {s: (n, grp) for s, n, grp in all_items}
    sym_stats = {}
    for sym, (prev_c, rows) in res_map.items():
        am_amts = [a for t, _, a in rows if t <= "1130"]
        base = float(np.mean(am_amts)) if len(am_amts) >= 20 else float(np.median([a for _, _, a in rows]))
        base = max(base, 1e5)
        by_t = {t: (px, amt) for t, px, amt in rows}
        sym_stats[sym] = {"prev_c": prev_c, "base": base, "by_t": by_t, "last_px": rows[-1][1]}

    # 5-min sliding window synchronization scan (skip first 15 mins opening auction noise)
    scan_mins = [m for m in all_mins if m >= "0945"]
    best_win = None
    best_score = -1.0
    for i in range(len(scan_mins)):
        w_mins = scan_mins[max(0, i - 4):i + 1]
        if len(w_mins) < 3:
            continue
        t1_hits, t2_hits, hw_hits = [], [], []
        t1_yi = t2_yi = hw_yi = 0.0
        for sym, st in sym_stats.items():
            name, grp = meta[sym]
            pts = [st["by_t"][m] for m in w_mins if m in st["by_t"]]
            if not pts:
                continue
            max_mult = max(a / st["base"] for _, a in pts)
            w_amt_yi = sum(a for _, a in pts) / 1e8
            w_ret = (pts[-1][0] / pts[0][0] - 1.0) * 100.0 if pts[0][0] > 0 else 0.0
            if grp == "T1":
                t1_yi += w_amt_yi
                if max_mult >= 4.0:
                    t1_hits.append((name, round(max_mult, 1), round(w_amt_yi, 2)))
            elif grp == "T2":
                t2_yi += w_amt_yi
                if max_mult >= 4.0:
                    t2_hits.append((name, round(max_mult, 1), round(w_amt_yi, 2)))
            else:
                hw_yi += w_amt_yi
                if max_mult >= 2.5 and w_ret >= -0.05:
                    hw_hits.append((name, round(max_mult, 1), round(w_ret, 2)))
        score = len(t1_hits) * 3.0 + len(t2_hits) * 3.0 + len(hw_hits) * 1.2 + min(10.0, (t1_yi + t2_yi) / 5.0)
        if score > best_score:
            best_score = score
            best_win = {
                "window": f"{w_mins[0][:2]}:{w_mins[0][2:]}至{w_mins[-1][:2]}:{w_mins[-1][2:]}",
                "t1_hits": sorted(t1_hits, key=lambda x: -x[1]),
                "t2_hits": sorted(t2_hits, key=lambda x: -x[1]),
                "hw_hits": sorted(hw_hits, key=lambda x: -x[1]),
                "t1_yi": round(t1_yi, 2), "t2_yi": round(t2_yi, 2), "hw_yi": round(hw_yi, 2),
                "etf_burst_yi": round(t1_yi + t2_yi, 2),
            }

    n1, n2, nh = len(best_win["t1_hits"]), len(best_win["t2_hits"]), len(best_win["hw_hits"])
    burst = best_win["etf_burst_yi"]
    if n1 >= 2 and n2 >= 2:
        regime = "一二队全面共振托底"
    elif n1 >= 2 and n2 == 0:
        regime = "一队护蓝筹抽血小盘"
    elif n2 >= 2 and n1 <= 1:
        regime = "二队定向托中小盘（权重协同）" if nh >= 3 else "二队单点脉冲托中小盘"
    elif nh >= 4 and (n1 + n2) == 0:
        regime = "单边权重硬撑（无ETF配合）"
    elif (n1 + n2) >= 1 and nh >= 3:
        regime = "局部ETF与权重协同试探"
    else:
        regime = "常态震荡（无多标的同步脉冲）"

    ps = 0.0 if pd.isna(proj_spike) else float(proj_spike)
    if ps >= 2.0 and (pd.isna(csi300_pct) or csi300_pct <= 0.5):
        level = "L3 十年铁律真底预警（21只池全天预计量比>=2.0x）"
    elif ps >= 1.5 or (n1 + n2 >= 3 and burst >= 30.0):
        level = "L2 准爆量试探护盘（量比1.5x至2.0x或大额同步脉冲）"
    elif (n1 + n2 >= 2) or (burst >= 10.0 and nh >= 3):
        level = "L1 盘中脉冲托底（分钟级爆量，全天量比未达2.0x真底门槛）"
    else:
        level = "L0 常态静默"

    return {"ok": True, "regime": regime, "alert_level": level, "best_window": best_win, "latest_hhmm": f"{all_mins[-1][:2]}:{all_mins[-1][2:]}"}


def fetch_institutional_redemption_radar(settled_dates: list):
    out = {"sector_etf_flows": [], "sector_1d_yi": 0.0, "sector_5d_yi": 0.0, "iopv_rows": [], "fund_hw_rows": [], "lhb_org_5d": [], "lhb_5d_net_yi": np.nan}
    # 1. Live ETF IOPV Premium/Discount via Tencent qt (p77=discount%, p78=IOPV)
    px_map = {}
    try:
        syms = ",".join(s for s, _, _ in IOPV_WATCH)
        raw = urllib.request.urlopen(urllib.request.Request(f"http://qt.gtimg.cn/q={syms}", headers={"User-Agent": "Mozilla/5.0"}), timeout=5).read().decode("gbk", "ignore")
        wmeta = {s[-6:]: (nm, cat) for s, nm, cat in IOPV_WATCH}
        for ln in raw.strip().splitlines():
            ps = ln.split("~")
            if len(ps) > 78 and ps[2] in wmeta:
                nm, cat = wmeta[ps[2]]
                px = float(ps[3]) if ps[3] else np.nan
                px_map[ps[2]] = px
                disc = float(ps[77]) if ps[77] not in ("", "-") else np.nan
                out["iopv_rows"].append({"code": ps[2], "name": nm, "cat": cat, "pct": round(float(ps[32]), 2), "amt_yi": round(float(ps[37]) / 1e4, 1), "disc_pct": round(disc, 2) if pd.notna(disc) else np.nan})
    except Exception:
        pass

    # 2. Settled Official SSE 10 Non-NT Institutional/Sector ETF 1d & 5d net shares flow
    if len(settled_dates) >= 6:
        d_last, d_prev, d_5ago = settled_dates[-1], settled_dates[-2], settled_dates[-6]
        sec_codes = {c for c, _ in SECTOR_SSE_ETFS}

        def _sse_day(dt):
            try:
                r = requests.get("https://query.sse.com.cn/commonQuery.do", params={"isPagination": "false", "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L", "STAT_DATE": dt}, headers={"Referer": "https://www.sse.com.cn/", "User-Agent": "Mozilla/5.0"}, timeout=8)
                return {str(x.get("SEC_CODE", "")).strip(): float(str(x.get("TOT_VOL", "0")).replace(",", "")) for x in r.json().get("result", []) if str(x.get("SEC_CODE", "")).strip() in sec_codes}
            except Exception:
                return {}

        with ThreadPoolExecutor(max_workers=3) as ex:
            sh_last, sh_prev, sh_5ago = list(ex.map(_sse_day, [d_last, d_prev, d_5ago]))
        # Fetch missing prices for 515790/512800 if not in IOPV_WATCH
        miss = [f"sh{c}" for c, _ in SECTOR_SSE_ETFS if c not in px_map]
        if miss:
            try:
                raw_m = urllib.request.urlopen(urllib.request.Request(f"http://qt.gtimg.cn/q={','.join(miss)}", headers={"User-Agent": "Mozilla/5.0"}), timeout=5).read().decode("gbk", "ignore")
                for ln in raw_m.strip().splitlines():
                    ps = ln.split("~")
                    if len(ps) > 4:
                        px_map[ps[2]] = float(ps[3])
            except Exception:
                pass
        s1_tot = s5_tot = 0.0
        for c, nm in SECTOR_SSE_ETFS:
            px = px_map.get(c, np.nan)
            if pd.isna(px) or c not in sh_last:
                continue
            f1 = (sh_last[c] - sh_prev.get(c, sh_last[c])) * 1e4 * px / 1e8
            f5 = (sh_last[c] - sh_5ago.get(c, sh_last[c])) * 1e4 * px / 1e8
            s1_tot += f1
            s5_tot += f5
            out["sector_etf_flows"].append({"code": c, "name": nm, "flow_1d_yi": round(f1, 2), "flow_5d_yi": round(f5, 2)})
        out["sector_1d_yi"], out["sector_5d_yi"] = round(s1_tot, 2), round(s5_tot, 2)
        out["sector_dates"] = (d_5ago, d_last)

    # 3. Public-Fund 8 Heavyweights Afternoon Dump Detector (14:00+ passive redemption proxy)
    with ThreadPoolExecutor(max_workers=8) as ex:
        for (sym, nm), (_, prev_c, rows) in zip(FUND_HEAVYWEIGHTS, ex.map(lambda x: _fetch_1m_bars(x[0]), FUND_HEAVYWEIGHTS)):
            if not rows:
                continue
            am = [a for t, _, a in rows if t <= "1130"]
            pm14 = [(t, px, a) for t, px, a in rows if t >= "1400"]
            p1400 = pm14[0][1] if pm14 else rows[-1][1]
            p_now = rows[-1][1]
            am_avg = float(np.mean(am)) if am else 1.0
            pm_avg = float(np.mean([a for _, _, a in pm14])) if pm14 else 0.0
            out["fund_hw_rows"].append({
                "code": sym[-6:], "name": nm,
                "day_pct": round((p_now / prev_c - 1.0) * 100.0, 2) if prev_c > 0 else 0.0,
                "pm14_pct": round((p_now / p1400 - 1.0) * 100.0, 2) if p1400 > 0 else 0.0,
                "pm14_vol_ratio": round(pm_avg / max(1.0, am_avg), 2),
            })

    # 4. Daily LHB Institutional Seat (机构专用) 5-Day Net Flow
    try:
        import akshare as ak
        beg = (datetime.now() - timedelta(days=12)).strftime("%Y%m%d")
        end = datetime.now().strftime("%Y%m%d")
        jg = ak.stock_lhb_jgmmtj_em(start_date=beg, end_date=end)
        if jg is not None and len(jg):
            g = jg.groupby("上榜日期").agg(n=("代码", "count"), buy=("机构买入总额", "sum"), sell=("机构卖出总额", "sum"), net=("机构买入净额", "sum")).reset_index().sort_values("上榜日期").tail(5)
            out["lhb_org_5d"] = [{"date": str(r["上榜日期"]), "n": int(r["n"]), "buy_yi": round(r["buy"] / 1e8, 2), "sell_yi": round(r["sell"] / 1e8, 2), "net_yi": round(r["net"] / 1e8, 2)} for _, r in g.iterrows()]
            out["lhb_5d_net_yi"] = round(float(g["net"].sum() / 1e8), 2)
    except Exception:
        pass

    # Synthesis Verdict for Institutional Redemption Pressure
    deep_disc = [r for r in out["iopv_rows"] if pd.notna(r["disc_pct"]) and r["disc_pct"] <= -0.25]
    dump_hws = [r for r in out["fund_hw_rows"] if r["pm14_pct"] <= -1.5 and r["pm14_vol_ratio"] >= 1.2]
    med_disc = float(np.nanmedian([r["disc_pct"] for r in out["iopv_rows"]])) if out["iopv_rows"] else 0.0
    if len(deep_disc) >= 4 or len(dump_hws) >= 5 or out["sector_5d_yi"] <= -150:
        verdict = "高赎回压力预警（ETF深度折价或公募重仓尾盘放量踩踏）"
    elif len(deep_disc) >= 2 or out["sector_5d_yi"] <= -50 or (pd.notna(out["lhb_5d_net_yi"]) and out["lhb_5d_net_yi"] <= -80):
        verdict = "温和净赎回承压（局部ETF折价或阶段净流出，未见踩踏）"
    else:
        verdict = "常态无踩踏（ETF折溢价平稳，公募重仓尾盘缩量，无集中被动赎回迹象）"
    out["verdict"] = verdict
    out["med_disc_pct"] = round(med_disc, 2)
    out["deep_disc_cnt"] = len(deep_disc)
    out["dump_hw_cnt"] = len(dump_hws)
    out["boundary_note"] = "主动权益场外公募无公开日频赎回数据（仅季报披露），盘中由ETF实时折溢价与公募八大重仓尾盘量价代理。"
    return out
