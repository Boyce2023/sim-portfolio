#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_20cm_deepopen_today.py — 20cm 首板深水错杀反抽 V1.1 生产实盘引擎 (s_20cm_deepopen)
严格 100% 对齐 strategy_20cm_deepopen_v11_pm_handover.md 与 v11_core.py：
  1. 标的池：30/688/689 非ST 昨日 20cm 非一字首板（上市>10日、收盘>=2元、成交额>=1亿、近90日零毒丸、近10日零监管函）。
  2. 空仓熔断：昨日全市场非ST 20cm 涨停 >= 16 家，全天空仓熔断禁止开仓。
  3. 09:25 硬门与9项评分 (Base=70, S档>=82入六策略单仓09:25直买, A档76~81仅观察不入单仓)：
     - F01 低开甜区 [-7.0%, -3.0%] +4 / 核按钮 <-8.0% -10 (硬窗 [-10.0%, -3.0%])
     - F02 扣除前十大锁仓后真实自由流值 <= 20亿 +4
     - F03 距3日30%严重异动红线余量 >= 10% +4 (基于 sz399107 / sh000300)
     - F04 近60日 20cm 涨停次数 >= 2 +5
     - F05 T0 封单额/成交额 >= 10% 却次日深低开 -5
     - F06 T0 龙虎榜机构专用净买入 > 0 +5
     - F07 T0 全市场10cm涨停 > 70 +7 / > 55 +4
     - F08 T+1 09:25 全场出现 >= 1 只 20cm 一字涨停 -5
     - F09 T+1 买入日为周一 -8
  4. 四分支动态卖树与 inst_dt 持仓风控开关（含 +0.30% 盘中限价止盈穿价缓冲）。

⛔ 铁律保证：
  1. 严禁 import yfinance 查询 A 股（D12）。
  2. 所有 SQLite 数据库一律 file:...?mode=ro 只读打开。
  3. 严禁触碰 portfolio_state.json 或执行任何下单操作。
"""

import argparse
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
import bisect
import datetime
import glob
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden!"

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM}/data"
V11_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
PART2_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"

CACHE_FILE = f"{DATA_DIR}/20cm_deepopen_premarket_cache.json"
A_DAILY = f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet"
A_DELISTED = f"{DATA_DIR}/cn_hk_price_db/a_delisted_daily.parquet"
ZT_TAPE_DB = f"{DATA_DIR}/zt_micro_tape_5y_pit.db"
PIT_NOTICES_DB = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
NOTICES_DB = f"{SIM}/backtest/2026-08-24-daban/notices.db"
NOTICES_ALT_DB = f"{DATA_DIR}/notices.db"
REG_TOX_PQ = f"{DATA_DIR}/pit_reg_tox_notices_5y_complete.parquet"
ZDJK_GLOB = f"{DATA_DIR}/kpl/zdjk/*.json"
THS_ZT_DIR = f"{DATA_DIR}/ths_limit_up_daily"
ST_UNIVERSE = f"{DATA_DIR}/st_universe.json"
IDX_CACHE = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
TOP10_20CM = f"{PART2_DIR}/pit_top10_20cm_summary.json"
LHB_BUY_PQ = f"{SIM}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
LHB_SELL_PQ = f"{SIM}/backtest/2026-10-20-lhasa/lhb_sell.parquet"
CSRC_L2_CSV = f"{DATA_DIR}/csrc_industry_l2.csv"
LEDGER_S82_CSV = f"{V11_DIR}/final_v11_ledger_S82.csv"
LEDGER_A76_CSV = f"{V11_DIR}/final_v11_ledger.csv"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

ST_ON_RE = re.compile(r"(?:^(?:\*?ST|S\*?ST)|(?:股票交易|股票)(?:被)?实施(?:退市|其他)风险警示|进入退市整理期|作出.*终止上市)")
ST_EXC_RE = re.compile(r"(?:可能被实施|不实施|未实施|免于实施|申请撤销|撤销.*风险警示)")
ST_REV_RE = re.compile(r"(?:撤销(?:退市|其他)风险警示|股票交易撤销.*风险警示)")
TOX_RE = re.compile(r"(?:减持计划|股东减持|减持股份|立案调查|收到立案|退市风险|违法违规|业绩预亏|预亏)")
REG_RE = re.compile(r"(?:监管工作函|监管函|关注函|重点监控|停牌核查|严重异常波动)")
REG_EXC = re.compile(r"(?:回复|回函|延期|核查意见|复牌|募集资金|监事|独立董事|保荐)")
LHB_CAT_EXPLAIN_RE = re.compile(r"(?:10个交易日|30个交易日|严重异常)")
LHB_CAT_NAMES = {"自然人", "中小投资者", "其他自然人", "机构投资者", "深股通投资者", "机构", "沪股通", "投资者分类"}

S_THR = 82.0
A_THR = 76.0
TP_BUF = 0.0030


def _mkt_prefix(c6: str) -> str:
    return "sh" if str(c6).startswith(("5", "6", "9")) else "sz"


def _shift_cal(dt_s: str, days: int) -> str:
    return (datetime.date.fromisoformat(dt_s) + datetime.timedelta(days=days)).isoformat()


def _cnt_ts(arr: list | None, lo: str, hi: str) -> int:
    return max(0, bisect.bisect_left(arr, hi) - bisect.bisect_left(arr, lo)) if arr else 0


def _is_st_at(st_tl: dict, c6: str, cut_ts: str) -> int:
    tl = st_tl.get(c6)
    if not tl:
        return 0
    idx = bisect.bisect_left(tl[0], cut_ts)
    return int(tl[1][idx - 1]) if idx > 0 else 0


def _is_20cm_code(c6: str) -> bool:
    return str(c6).zfill(6).startswith(("30", "688", "689"))


def _probe_tencent_close_date() -> tuple[str, int]:
    try:
        req = urllib.request.Request("http://qt.gtimg.cn/q=sh000001", headers=UA)
        raw = urllib.request.urlopen(req, timeout=3).read().decode("gbk", errors="ignore")
        p = raw.split('="', 1)[1].split("~")
        dt14 = str(p[30]).strip() if len(p) > 30 else ""
        q_dt = f"{dt14[:4]}-{dt14[4:6]}-{dt14[6:8]}" if len(dt14) >= 8 and dt14[:8].isdigit() else ""
        q_hhmm = int(dt14[8:12]) if len(dt14) >= 12 and dt14[8:12].isdigit() else 0
        return q_dt, q_hhmm
    except Exception:
        return "", 0


def fetch_tencent_quotes(symbols_or_codes: list[str], batch_size: int = 80, max_workers: int = 24) -> dict[str, dict]:
    if not symbols_or_codes:
        return {}
    syms = []
    for x in symbols_or_codes:
        s = str(x).strip()
        if s.startswith(("sh", "sz")):
            syms.append(s)
        else:
            c6 = s[-6:].zfill(6)
            syms.append(_mkt_prefix(c6) + c6)
    syms = sorted(set(syms))
    chunks = [syms[i:i + batch_size] for i in range(0, len(syms), batch_size)]

    def _chunk(ch: list[str]) -> dict[str, dict]:
        out = {}
        url = "http://qt.gtimg.cn/q=" + ",".join(ch)
        req = urllib.request.Request(url, headers=UA)
        for _ in range(3):
            try:
                raw = urllib.request.urlopen(req, timeout=4).read().decode("gbk", errors="ignore")
                for ln in raw.strip().splitlines():
                    if '="' not in ln:
                        continue
                    lhs, rhs = ln.split('="', 1)
                    sym = lhs.split("_")[-1].strip()
                    p = rhs.strip('";').split("~")
                    if len(p) > 38:
                        c6 = (p[2].strip() or sym[-6:]).zfill(6)
                        cur = float(p[3] or 0.0)
                        pre = float(p[4] or 0.0)
                        op = float(p[5] or 0.0)
                        hi = float(p[33] or 0.0) or cur
                        lo = float(p[34] or 0.0) or cur
                        amt = float(p[37] or 0.0) * 10000.0
                        trn = float(p[38] or 0.0) / 100.0
                        b1 = float(p[10] or 0.0) if len(p) > 10 else 0.0
                        s1 = float(p[20] or 0.0) if len(p) > 20 else 0.0
                        dt8 = str(p[30]).strip()[:8] if len(p) > 30 else ""
                        q_dt = f"{dt8[:4]}-{dt8[4:6]}-{dt8[6:8]}" if len(dt8) == 8 and dt8.isdigit() else ""
                        lim = 1.20 if _is_20cm_code(c6) else 1.10
                        vol_sh = float(p[6] or 0.0) * 100.0
                        op_px = op
                        op_pct = (op_px / pre - 1.0) if (pre > 0 and op_px > 0) else -1.0
                        cur_pct = (cur / pre - 1.0) if (pre > 0 and cur > 0) else 0.0
                        zt_px = float(np.floor(pre * lim * 100.0 + 0.5) / 100.0) if pre > 0 else 999.0
                        dt_px = float(np.floor(pre * (2.0 - lim) * 100.0 + 0.5) / 100.0) if pre > 0 else 0.0
                        zt_pct_thr = 0.195 if _is_20cm_code(c6) else 0.095
                        is_yizi = bool(op_px > 0 and (op_px >= zt_px - 0.011 or (b1 > 0 and s1 == 0 and op_pct >= zt_pct_thr)) and (lo <= 0 or hi == lo or op_px >= zt_px - 0.011))
                        rec = {
                            "code": c6, "symbol": sym, "name": p[1].strip(),
                            "open": op_px, "cur": cur, "close": cur, "high": hi, "low": lo,
                            "pre": pre, "pre_c": pre, "volume": vol_sh, "amount": amt, "turn": trn,
                            "b1": b1, "s1": s1, "q_dt": q_dt,
                            "opct": op_pct, "open_pct": op_pct, "cpct": cur_pct, "cur_pct": cur_pct,
                            "zt_px": zt_px, "dt_px": dt_px, "is_yizi": is_yizi,
                        }
                        out[c6] = rec
                        out[sym] = rec
                if out:
                    return out
            except Exception:
                pass
        return out

    if len(chunks) == 1:
        return _chunk(chunks[0])
    res = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for f in as_completed([ex.submit(_chunk, ch) for ch in chunks]):
            res.update(f.result())
    return res


def _fetch_tencent_qfq_kline(symbol: str, datalen: int = 35) -> list[dict]:
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{datalen},qfq"
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=4).read().decode("utf-8", errors="ignore")
        d = json.loads(raw).get("data", {}).get(symbol, {})
        rows = d.get("qfqday") or d.get("day") or []
        return [
            {"dt": str(r[0])[:10], "open": float(r[1]), "close": float(r[2]), "high": float(r[3]), "low": float(r[4])}
            for r in rows if len(r) >= 5
        ]
    except Exception:
        return []


def _fetch_eastmoney_top10_20cm_single(c6: str) -> list[list]:
    flt = urllib.parse.quote(f'(SECURITY_CODE="{c6}")(END_DATE>="2020-06-30")')
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get?"
        "reportName=RPT_F10_EH_FREEHOLDERS&columns=SECURITY_CODE,END_DATE,NOTICE_DATE,FREE_HOLDNUM_RATIO"
        f"&filter={flt}&pageSize=500&pageNumber=1"
    )
    try:
        js = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=4).read().decode("utf-8", errors="ignore"))
        rows = (js.get("result") or {}).get("data") or []
        by_ed = {}
        for it in rows:
            nd = str(it.get("NOTICE_DATE") or "")[:10]
            ed = str(it.get("END_DATE") or "")[:10]
            rt = float(it.get("FREE_HOLDNUM_RATIO") or 0.0)
            if nd >= "2000-01-01" and ed and rt > 0:
                rec = by_ed.setdefault(ed, [nd, 0.0, 0.0])
                rec[0] = min(rec[0], nd)
                rec[1] += rt
                if rt >= 5.0:
                    rec[2] += rt
        return sorted([[v[0], ed, round(min(95.0, v[1]), 2), round(min(95.0, v[2]), 2)] for ed, v in by_ed.items()])
    except Exception:
        return []


def _compute_lhb_inst_net_by_date(dt_str: str, codes_filter: set[str] | None = None) -> tuple[dict[str, float], bool]:
    """
    Strictly deduplicate BUY/SELL parquet tables on (TRADE_ID, OPERATEDEPT_NAME, BUY, SELL),
    prefer non-3-day single-day IDs (is_three == 0), return {c6: inst_net_wan}.
    """
    b_map, s_map = defaultdict(list), defaultdict(list)
    has_dt = False
    cols = ["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL", "EXPLANATION", "TRADE_ID"]
    for pq, dst, is_b in [(LHB_BUY_PQ, b_map, True), (LHB_SELL_PQ, s_map, False)]:
        if not os.path.exists(pq):
            continue
        try:
            ldf = pd.read_parquet(pq, columns=cols)
            ldf["dt"] = ldf["TRADE_DATE"].astype(str).str[:10]
            sub = ldf[ldf["dt"] == dt_str]
            if not sub.empty:
                has_dt = True
            if codes_filter is not None:
                sub = sub[sub["SECURITY_CODE"].astype(str).str[:6].str.zfill(6).isin(codes_filter)]
            for r in sub.itertuples(index=False):
                c6 = str(r.SECURITY_CODE)[:6].zfill(6)
                bv = 0.0 if (r.BUY is None or pd.isna(r.BUY)) else float(r.BUY)
                sv = 0.0 if (r.SELL is None or pd.isna(r.SELL)) else float(r.SELL)
                dst[c6].append((
                    str(r.TRADE_ID or ""),
                    str(r.EXPLANATION or ""),
                    str(r.OPERATEDEPT_NAME or "").strip(),
                    bv,
                    sv,
                ))
        except Exception as e:
            print(f"[WARN] fast_20cm LHB parquet error ({pq}): {e}", file=sys.stderr)

    out = {}
    for c6 in set(b_map) | set(s_map):
        b_tid, meta, bcnt = defaultdict(list), {}, Counter()
        for tid, exp, dept, bv, sv in b_map[c6]:
            if LHB_CAT_EXPLAIN_RE.search(exp) or dept in LHB_CAT_NAMES:
                continue
            key = (tid, dept, round(bv, 2), round(sv, 2))
            bcnt[key] += 1
            b_tid[tid].append((dept, bv, sv))
            is3 = 1 if "连续" in exp else 0
            if tid not in meta:
                meta[tid] = [is3, bv + sv]
            else:
                meta[tid][1] += bv + sv
        merged = defaultdict(list, {k: list(v) for k, v in b_tid.items()})
        for tid, exp, dept, bv, sv in s_map[c6]:
            if LHB_CAT_EXPLAIN_RE.search(exp) or dept in LHB_CAT_NAMES:
                continue
            key = (tid, dept, round(bv, 2), round(sv, 2))
            if bcnt[key] > 0:
                bcnt[key] -= 1
                continue
            merged[tid].append((dept, bv, sv))
            is3 = 1 if "连续" in exp else 0
            if tid not in meta:
                meta[tid] = [is3, bv + sv]
            else:
                meta[tid][1] += bv + sv
        if not meta:
            continue
        best_tid = min(meta.items(), key=lambda kv: (kv[1][0], -kv[1][1], kv[0]))[0]
        inst_net = sum((bv - sv) for d, bv, sv in merged[best_tid] if "机构专用" in d) / 1e4
        out[c6] = round(float(inst_net), 2)
    return out, has_dt


def _fetch_lhb_inst_net_online(c6: str, dt_str: str) -> float:
    b_rows, s_rows = [], []
    for side, dst in [("BUY", b_rows), ("SELL", s_rows)]:
        url = (
            f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_BILLBOARD_DAILYDETAILS{side}"
            f"&columns=TRADE_DATE,SECURITY_CODE,OPERATEDEPT_NAME,BUY,SELL,EXPLANATION,TRADE_ID"
            f"&filter=(SECURITY_CODE%3D%22{c6}%22)&sortColumns=TRADE_DATE&sortTypes=-1&pageNumber=1&pageSize=60&source=WEB&client=WEB"
        )
        try:
            js = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=4).read().decode("utf-8", errors="ignore"))
            for it in (js.get("result") or {}).get("data") or []:
                if str(it.get("TRADE_DATE", ""))[:10] == dt_str:
                    dst.append((
                        str(it.get("TRADE_ID") or ""),
                        str(it.get("EXPLANATION") or ""),
                        str(it.get("OPERATEDEPT_NAME") or "").strip(),
                        0.0 if (it.get("BUY") is None or pd.isna(it.get("BUY"))) else float(it.get("BUY")),
                        0.0 if (it.get("SELL") is None or pd.isna(it.get("SELL"))) else float(it.get("SELL")),
                    ))
        except Exception:
            pass
    if not b_rows and not s_rows:
        return 0.0
    b_tid, meta, bcnt = defaultdict(list), {}, Counter()
    for tid, exp, dept, bv, sv in b_rows:
        if LHB_CAT_EXPLAIN_RE.search(exp) or dept in LHB_CAT_NAMES:
            continue
        bcnt[(tid, dept, round(bv, 2), round(sv, 2))] += 1
        b_tid[tid].append((dept, bv, sv))
        is3 = 1 if "连续" in exp else 0
        if tid not in meta:
            meta[tid] = [is3, bv + sv]
        else:
            meta[tid][1] += bv + sv
    merged = defaultdict(list, {k: list(v) for k, v in b_tid.items()})
    for tid, exp, dept, bv, sv in s_rows:
        if LHB_CAT_EXPLAIN_RE.search(exp) or dept in LHB_CAT_NAMES:
            continue
        key = (tid, dept, round(bv, 2), round(sv, 2))
        if bcnt[key] > 0:
            bcnt[key] -= 1
            continue
        merged[tid].append((dept, bv, sv))
        is3 = 1 if "连续" in exp else 0
        if tid not in meta:
            meta[tid] = [is3, bv + sv]
        else:
            meta[tid][1] += bv + sv
    if not meta:
        return 0.0
    best_tid = min(meta.items(), key=lambda kv: (kv[1][0], -kv[1][1], kv[0]))[0]
    return round(sum((bv - sv) for d, bv, sv in merged[best_tid] if "机构专用" in d) / 1e4, 2)


def _fetch_ths_limit_up(dt_str: str) -> dict[str, dict]:
    p = f"{THS_ZT_DIR}/{dt_str}.json"
    stocks = []
    if os.path.exists(p):
        try:
            stocks = json.load(open(p, encoding="utf-8")).get("stocks", []) or []
        except Exception:
            stocks = []
    if not stocks:
        ymd = dt_str.replace("-", "")
        url = (
            "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&"
            "field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004&"
            f"filter=HS,GEM2STAR&order_field=330324&order_type=0&date={ymd}"
        )
        try:
            stocks = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=6).read().decode("utf-8", errors="ignore")).get("data", {}).get("info", []) or []
        except Exception:
            stocks = []
    return {str(s.get("code", ""))[:6].zfill(6): s for s in stocks if s.get("code")}


def build_premarket_cache(verbose: bool = True, as_of_date: str = "") -> dict:
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn"]
    cutoff_cal = (datetime.date.today() - datetime.timedelta(days=200)).isoformat()
    if as_of_date:
        cutoff_cal = _shift_cal(as_of_date, -200)
    flt = ds.field("date") >= pd.Timestamp(cutoff_cal)
    df_a = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    if as_of_date and os.path.exists(A_DELISTED):
        df_d = ds.dataset(A_DELISTED, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
        df_a = pd.concat([df_a, df_d], ignore_index=True)

    df_a["c6"] = df_a["ticker"].astype(str).str[:6]
    df_a["dt"] = df_a["date"].dt.strftime("%Y-%m-%d")
    if as_of_date:
        df_a = df_a[df_a["dt"] <= as_of_date].copy()
    df_a = df_a[df_a["ticker"].str.endswith((".SH", ".SZ")) & (df_a["close"] > 0) & (df_a["adj_close"] > 0)].copy()
    df_a.sort_values(["c6", "dt"], inplace=True)
    df_a.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    df_a.reset_index(drop=True, inplace=True)

    max_p_date = df_a["dt"].max()
    patched_today = False
    if not as_of_date:
        now = datetime.datetime.now()
        q_dt, q_hhmm = _probe_tencent_close_date()
        if now.weekday() < 5 and q_dt > max_p_date and q_hhmm >= 1505:
            last_sub = df_a[(df_a["dt"] == max_p_date) & df_a["c6"].str.startswith(("00", "60", "30", "688", "689"))]
            c_list = last_sub["c6"].tolist()
            tk_map = dict(zip(last_sub["c6"], last_sub["ticker"]))
            osh_map = dict(zip(last_sub["c6"], last_sub["oshare"]))
            lv_map = fetch_tencent_quotes(c_list, batch_size=80, max_workers=24)
            patch_rows = []
            for c in c_list:
                q = lv_map.get(c)
                if q and q.get("q_dt") == q_dt and q.get("close", 0) > 0:
                    osh = float(osh_map.get(c, 0.0) or 0.0)
                    px = float(q["close"])
                    turn_v = float(q["turn"]) if q.get("turn", 0) > 0 else ((q["amount"] / (px * osh)) if osh > 0 else 0.0)
                    patch_rows.append({
                        "date": pd.Timestamp(q_dt), "ticker": tk_map[c],
                        "open": q["open"], "high": q["high"], "low": q["low"], "close": px,
                        "adj_close": px, "volume": max(1.0, float(q.get("volume") or 1.0)), "amount": q["amount"], "oshare": osh, "turn": turn_v,
                        "c6": c, "dt": q_dt,
                    })
            if len(patch_rows) >= 3500:
                df_a = pd.concat([df_a, pd.DataFrame(patch_rows)], ignore_index=True)
                df_a.drop_duplicates(["c6", "dt"], keep="last", inplace=True)
                df_a.sort_values(["c6", "dt"], inplace=True)
                df_a.reset_index(drop=True, inplace=True)
                patched_today = True

    all_dts = sorted(df_a["dt"].unique())
    latest_dt = all_dts[-1]
    sig_ts = pd.Timestamp(latest_dt)
    nxt_buy_date = (sig_ts + pd.Timedelta(days=(3 if sig_ts.weekday() == 4 else 1))).strftime("%Y-%m-%d")
    nxt_weekday = datetime.date.fromisoformat(nxt_buy_date).weekday()
    is_monday = (nxt_weekday == 0)

    # Full history bar count for accurate list_age > 10 on active 20cm stocks
    hist_age_map = {}
    try:
        t_age = ds.dataset(A_DAILY, format="parquet").scanner(
            columns=["ticker"], filter=ds.field("date") <= pd.Timestamp(latest_dt)
        ).to_table().to_pandas()
        t_age["c6"] = t_age["ticker"].astype(str).str[:6]
        t_age = t_age[t_age["c6"].str.startswith(("30", "688", "689"))]
        hist_age_map = t_age.groupby("c6").size().to_dict()
        if patched_today:
            for c in hist_age_map:
                hist_age_map[c] += 1
    except Exception:
        pass

    # F07: Mkt 10cm ZT count on latest_dt (matching v11_core.py:160-167)
    d10 = df_a[df_a["c6"].str.startswith(("00", "60")) & (df_a["dt"] >= _shift_cal(latest_dt, -20))].copy()
    g10 = d10.groupby("c6", sort=False)
    s10 = d10["adj_close"] / d10["close"]
    pac10 = g10["adj_close"].shift(1)
    r10 = d10["adj_close"] / pac10 - 1.0
    ztp10 = np.floor((pac10 / s10) * 1.10 * 100.0 + 0.5) / 100.0
    d10["is_zt"] = (pac10 > 0) & (d10["close"] >= ztp10 - 0.011) & (r10 >= 0.095) & (r10.abs() <= 0.12)
    mkt10_zt_cnt = int(d10[d10["dt"] == latest_dt]["is_zt"].sum())

    # 20cm universe calculations (30/688/689)
    df = df_a[df_a["c6"].str.startswith(("30", "688", "689"))].copy().reset_index(drop=True)
    g = df.groupby("c6", sort=False)
    sc_ratio = df["adj_close"] / df["close"]
    df["ao"] = df["open"] * sc_ratio
    df["ac"] = df["adj_close"]
    df["prev_ac"] = g["ac"].shift(1)
    df["ret"] = df["ac"] / df["prev_ac"] - 1.0
    df["o_pct"] = df["ao"] / df["prev_ac"] - 1.0
    df["abn_ret"] = df["ret"].abs() > 0.22
    df["bar_cnt"] = df["c6"].map(lambda c: hist_age_map.get(c, 999))
    df["tradable"] = (df["volume"] > 0) & (df["open"] > 0) & (df["bar_cnt"] > 10) & (~df["abn_ret"])
    prev_ex = df["prev_ac"] / sc_ratio
    df["zt_px"] = np.floor(prev_ex * 1.20 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["prev_ac"] > 0) & (df["close"] >= df["zt_px"] - 0.011) & (df["ret"] >= 0.195) & (~df["abn_ret"])
    df["is_yizi_zt"] = df["is_zt"] & (df["low"] == df["high"]) & (df["o_pct"] >= 0.195)
    s_zt = df["is_zt"].astype(int)
    s_sh = g["is_zt"].shift(1).fillna(False).astype(bool)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != s_sh).cumsum()]).cumsum() * s_zt
    df["ret3"] = df["ac"] / g["ac"].shift(3) - 1.0
    est_sh = np.where(df["oshare"].fillna(0) > 0, df["oshare"], np.where(df["turn"] > 0, df["volume"] / df["turn"], np.nan))
    df["mcap"] = est_sh * df["close"] / 1e8
    df["zt_cnt_60d"] = g["is_zt"].transform(lambda s: s.rolling(60, min_periods=1).sum())

    # Index 3-day return (sz399107 primary, sh000300 fallback)
    idx_r3 = 0.0
    if os.path.exists(IDX_CACHE):
        try:
            idx_json = json.load(open(IDX_CACHE, "r", encoding="utf-8"))
            sz_m = {k: float(v) for k, v in idx_json.get("sz399107", {}).items() if k <= latest_dt}
            sh_m = {k: float(v) for k, v in idx_json.get("sh000300", {}).items() if k <= latest_dt}
            if patched_today and latest_dt not in sz_m:
                qk = fetch_tencent_quotes(["sz399107", "sh000300"])
                if qk.get("sz399107", {}).get("q_dt") == latest_dt and qk["sz399107"]["close"] > 0:
                    sz_m[latest_dt] = float(qk["sz399107"]["close"])
                if qk.get("sh000300", {}).get("q_dt") == latest_dt and qk["sh000300"]["close"] > 0:
                    sh_m[latest_dt] = float(qk["sh000300"]["close"])
            idx_dts = sorted(sz_m.keys())
            if len(idx_dts) >= 4 and idx_dts[-1] == latest_dt:
                idx_r3 = float(sz_m[idx_dts[-1]] / sz_m[idx_dts[-4]] - 1.0)
            else:
                sh_dts = sorted(sh_m.keys())
                if len(sh_dts) >= 4:
                    idx_r3 = float(sh_m[sh_dts[-1]] / sh_m[sh_dts[-4]] - 1.0)
        except Exception as e:
            print(f"[WARN] index cache read error: {e}", file=sys.stderr)

    # ST timeline + tox(90d) + reg(10d) strictly < nxt_buy_date 09:25:00
    d_latest = df[df["dt"] == latest_dt].copy()
    all20_active = set(d_latest["c6"].unique())
    st_ev = defaultdict(list)
    zt_tape_seal = {}
    name_map = {}

    if os.path.exists(CSRC_L2_CSV):
        try:
            nm_df = pd.read_csv(CSRC_L2_CSV, usecols=["code", "code_name"]).fillna("")
            for rc, rn in zip(nm_df["code"], nm_df["code_name"]):
                name_map[str(rc)[-6:].zfill(6)] = str(rn).strip()
        except Exception:
            pass

    if os.path.exists(ZT_TAPE_DB):
        con_z = sqlite3.connect(f"file:{ZT_TAPE_DB}?mode=ro", uri=True)
        try:
            for td, sc, nm, sa in con_z.execute(
                "SELECT trade_date, sec_code, sec_name, seal_amount FROM zt_micro_tape "
                "WHERE trade_date >= ? AND trade_date <= ? AND (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%')",
                (_shift_cal(latest_dt, -120), latest_dt),
            ):
                c6 = str(sc).zfill(6)
                s = str(nm or "").strip()
                if s:
                    st_ev[c6].append((f"{td} 15:00:00", 1 if ("ST" in s.upper() or "退" in s) else 0))
                    name_map[c6] = s
                if str(td) == latest_dt:
                    zt_tape_seal[c6] = float(sa or 0.0)
        finally:
            con_z.close()

    ths_map = _fetch_ths_limit_up(latest_dt)
    for c6, it in ths_map.items():
        if _is_20cm_code(c6) and it.get("name"):
            name_map[c6] = str(it["name"]).strip()
            if c6 not in zt_tape_seal and it.get("order_amount") is not None:
                zt_tape_seal[c6] = float(it["order_amount"] or 0.0)

    tox_m, reg_m = defaultdict(list), defaultdict(list)
    cut_90 = f"{_shift_cal(latest_dt, -90)} 00:00:00"
    cut_hi_ts = f"{nxt_buy_date} 09:25:00"
    cut_t1c = f"{nxt_buy_date} 09:00:00"

    if os.path.exists(PIT_NOTICES_DB):
        con_n = sqlite3.connect(f"file:{PIT_NOTICES_DB}?mode=ro", uri=True)
        try:
            for sc, ti, ts in con_n.execute(
                "SELECT sec_code, title, pub_datetime_cst FROM notices "
                "WHERE pub_datetime_cst >= ? AND pub_datetime_cst < ? AND (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%')",
                (cut_90[:10], cut_hi_ts),
            ):
                c6, ts_s, t_s = str(sc).zfill(6), str(ts)[:19], str(ti or "")
                if c6 in all20_active:
                    if ST_REV_RE.search(t_s) and "不" not in t_s[:10]:
                        st_ev[c6].append((ts_s, 0))
                    elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s):
                        st_ev[c6].append((ts_s, 1))
                    if TOX_RE.search(t_s):
                        tox_m[c6].append(ts_s)
                    if REG_RE.search(t_s) and not REG_EXC.search(t_s):
                        reg_m[c6].append(ts_s)
        finally:
            con_n.close()

    for p_ndb in (NOTICES_DB, NOTICES_ALT_DB):
        if os.path.exists(p_ndb) and os.path.getsize(p_ndb) > 0:
            con_nd = sqlite3.connect(f"file:{p_ndb}?mode=ro", uri=True)
            try:
                for sc, nd, ti in con_nd.execute(
                    "SELECT code, ndate, title FROM notice WHERE ndate >= ? AND ndate < ? AND (code LIKE '30%' OR code LIKE '688%' OR code LIKE '689%')",
                    (cut_90[:10], nxt_buy_date),
                ):
                    c6, nd_s, t_s = str(sc)[:6].zfill(6), str(nd)[:10], str(ti or "")
                    ts_s = f"{nd_s} 08:00:00"
                    if c6 in all20_active:
                        if TOX_RE.search(t_s):
                            tox_m[c6].append(ts_s)
                        if REG_RE.search(t_s) and not REG_EXC.search(t_s):
                            reg_m[c6].append(ts_s)
            finally:
                con_nd.close()
            break

    if os.path.exists(REG_TOX_PQ):
        rt = pd.read_parquet(REG_TOX_PQ, columns=["sec_code", "pub_datetime_cst", "title"])
        rt["c6"] = rt["sec_code"].astype(str).str[:6].str.zfill(6)
        rt = rt[(rt["pub_datetime_cst"].astype(str) >= cut_90) & (rt["pub_datetime_cst"].astype(str) < cut_hi_ts) & rt["c6"].isin(all20_active)]
        for r in rt.itertuples(index=False):
            t_s, ts_s = str(r.title or ""), str(r.pub_datetime_cst)[:19]
            if ST_REV_RE.search(t_s):
                st_ev[r.c6].append((ts_s, 0))
            elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s):
                st_ev[r.c6].append((ts_s, 1))
            if TOX_RE.search(t_s):
                tox_m[r.c6].append(ts_s)
            if REG_RE.search(t_s) and not REG_EXC.search(t_s):
                reg_m[r.c6].append(ts_s)

    for zf in glob.glob(ZDJK_GLOB):
        try:
            for it in json.load(open(zf, encoding="utf-8")).get("List", []):
                c6, d_z = str(it[0]).zfill(6), str(it[2])[:10]
                if c6 in all20_active and d_z < nxt_buy_date:
                    reg_m[c6].append(f"{d_z} 08:00:00")
        except Exception:
            pass

    st_2026 = {str(x)[:6].zfill(6) for x in json.load(open(ST_UNIVERSE, encoding="utf-8")).get("codes", [])} if os.path.exists(ST_UNIVERSE) else set()
    st_tl = {k: ([x[0] for x in sorted(v)], [x[1] for x in sorted(v)]) for k, v in st_ev.items()}
    for m in (tox_m, reg_m):
        for k in list(m.keys()):
            m[k] = sorted(set(m[k]))

    def _is_clean_non_st(c6: str) -> bool:
        if c6 in st_2026:
            return False
        nm = name_map.get(c6, "")
        if "ST" in nm.upper() or "退" in nm:
            return False
        return _is_st_at(st_tl, c6, f"{latest_dt} 15:00:00") == 0 and _is_st_at(st_tl, c6, cut_t1c) == 0

    mkt20_zt_cnt = int(sum(1 for r in d_latest[d_latest["is_zt"]].itertuples(index=False) if _is_clean_non_st(r.c6)))
    halt_ge16 = bool(mkt20_zt_cnt >= 16)

    fb_sub = d_latest[
        d_latest["tradable"] & (d_latest["close"] >= 2.0) & d_latest["is_zt"]
        & (d_latest["streak"] == 1) & (~d_latest["is_yizi_zt"]) & (d_latest["amount"] >= 1e8)
    ].copy().sort_values("c6")

    cand_codes = {r.c6 for r in fb_sub.itertuples(index=False)}
    missing_names = [c for c in cand_codes if not name_map.get(c)]
    if missing_names and not as_of_date:
        q_nm = fetch_tencent_quotes(missing_names)
        for c, v in q_nm.items():
            if len(c) == 6 and v.get("name"):
                name_map[c] = v["name"]

    t10 = json.load(open(TOP10_20CM, encoding="utf-8")) if os.path.exists(TOP10_20CM) else {}
    lhb_map, lhb_has_dt = _compute_lhb_inst_net_by_date(latest_dt, codes_filter=cand_codes)

    all_20cm_codes = [
        [r.c6, round(float(r.close), 2)]
        for r in d_latest.itertuples(index=False)
        if _is_clean_non_st(r.c6)
    ]

    candidates = []
    tox_start = f"{_shift_cal(latest_dt, -90)} 00:00:00"
    reg_start = f"{_shift_cal(latest_dt, -10)} 00:00:00"
    now_hm = datetime.datetime.now().hour * 100 + datetime.datetime.now().minute

    for r in fb_sub.itertuples(index=False):
        c6 = r.c6
        if not _is_clean_non_st(c6):
            continue
        has_tox = _cnt_ts(tox_m.get(c6), tox_start, cut_t1c) > 0
        has_reg = _cnt_ts(reg_m.get(c6), reg_start, cut_t1c) > 0

        recs = [x for x in t10.get(c6, []) if "2000-01-01" <= str(x[0]) < latest_dt]
        if not recs and c6 not in t10 and (not as_of_date):
            recs = [x for x in _fetch_eastmoney_top10_20cm_single(c6) if "2000-01-01" <= str(x[0]) < latest_dt]
        best_ed, lock_val = "", np.nan
        for nd, ed, l10, _ in recs:
            if str(ed) >= best_ed:
                best_ed, lock_val = str(ed), float(l10)
        lock_pct = 40.0 if np.isnan(lock_val) else float(np.clip(lock_val, 0.0, 95.0))
        mcap_yi = float(r.mcap) if pd.notna(r.mcap) else 50.0
        real_free_mcap = round(mcap_yi * (1.0 - lock_pct / 100.0), 2)

        ret3_v = float(r.ret3) if pd.notna(r.ret3) else 0.20
        dist_3d30 = round(0.30 - (ret3_v - idx_r3), 4)
        zt_cnt_60d = int(r.zt_cnt_60d) if pd.notna(r.zt_cnt_60d) else 1
        seal_amt = zt_tape_seal.get(c6, 0.0)
        zt_seal_ratio = round(seal_amt / float(r.amount), 4) if r.amount > 0 else 0.0

        inst_net = lhb_map.get(c6)
        if inst_net is None:
            inst_net = _fetch_lhb_inst_net_online(c6, latest_dt) if (not lhb_has_dt and not as_of_date and now_hm >= 1700) else 0.0

        f02 = 4 if real_free_mcap <= 20.0 else 0
        f03 = 4 if dist_3d30 >= 0.10 else 0
        f04 = 5 if zt_cnt_60d >= 2 else 0
        f05 = -5 if zt_seal_ratio >= 0.10 else 0
        f06 = 5 if inst_net > 0.0 else 0
        f07 = 7 if mkt10_zt_cnt > 70 else (4 if mkt10_zt_cnt > 55 else 0)
        f09 = -8 if is_monday else 0
        static_score = 70 + f02 + f03 + f04 + f05 + f06 + f07 + f09

        candidates.append({
            "code": c6,
            "name": name_map.get(c6, c6),
            "sig_date": latest_dt,
            "buy_date": nxt_buy_date,
            "prev_close": round(float(r.close), 2),
            "amount_yi": round(float(r.amount) / 1e8, 2),
            "mcap_yi": round(mcap_yi, 2),
            "lock_pct": round(lock_pct, 2),
            "real_free_mcap": real_free_mcap,
            "dist_3d30": dist_3d30,
            "zt_cnt_60d": zt_cnt_60d,
            "zt_seal_ratio": zt_seal_ratio,
            "lhb_inst_net": round(float(inst_net), 2),
            "mkt10_zt_cnt": mkt10_zt_cnt,
            "is_monday": is_monday,
            "has_tox_90d": bool(has_tox),
            "has_reg_10d": bool(has_reg),
            "static_score": int(static_score),
            "static_factors": {
                "F02_rfm": f02, "F03_dist3d30": f03, "F04_zt60d": f04,
                "F05_seal10": f05, "F06_inst": f06, "F07_mkt10": f07, "F09_mon": f09,
            },
        })

    candidates.sort(key=lambda x: (-x["static_score"], x["code"]))
    cache = {
        "version": "20CM_DEEPOPEN_V11_PROD_20261124",
        "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sig_date": latest_dt,
        "data_as_of_date": latest_dt,
        "buy_date": nxt_buy_date,
        "is_monday": is_monday,
        "patched_today": patched_today,
        "mkt20_zt_cnt": mkt20_zt_cnt,
        "halt_ge16": halt_ge16,
        "mkt10_zt_cnt": mkt10_zt_cnt,
        "idx_r3_sz399107": round(idx_r3, 5),
        "candidates": candidates,
        "all_20cm_codes": all_20cm_codes,
    }
    if not as_of_date:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = CACHE_FILE + ".tmp"
        json.dump(cache, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        os.replace(tmp, CACHE_FILE)
    if verbose:
        halt_s = f"🚨触发空仓熔断(>=16)" if halt_ge16 else "✅未熔断(<16)"
        print(
            f"[+] 20cm深水错杀 V1.1 盘前缓存已生成 (sig_date={latest_dt} -> buy_date={nxt_buy_date}, 耗时{time.time()-t0:.2f}s): "
            f"昨日20cm涨停={mkt20_zt_cnt}家[{halt_s}] | 昨日10cm涨停={mkt10_zt_cnt}家 | 非一字首板候选={len(candidates)}只"
        )
    return cache


def evaluate_20cm_candidates(
    cache: dict,
    q_map: dict[str, dict],
    all20_q_map: dict[str, dict] | None = None,
    mock_map: dict[str, float] | None = None,
    scan_f08_on_q: bool = True,
) -> tuple[list[dict], dict]:
    """唯一真源 09:25 实时评分器：供 fast_20cm_deepopen_today.py 与 daily_3strategies_score_report.py 共享调用。"""
    mock_map = mock_map or {}
    sig_date = str(cache.get("sig_date") or cache.get("data_as_of_date") or "")
    cands = cache.get("candidates", [])
    mkt20_zt_cnt = int(cache.get("mkt20_zt_cnt", 0))
    halt_ge16 = bool(cache.get("halt_ge16", mkt20_zt_cnt >= 16))
    is_monday = bool(cache.get("is_monday", False))

    # F08: 09:25 全场 20cm 一字涨停家数
    f1_mkt20_0925_zt = 0
    all20_valid_cnt = 0
    scan_src = all20_q_map if all20_q_map is not None else (q_map if scan_f08_on_q else None)
    meta20_pre = {str(it[0]).zfill(6): float(it[1]) for it in cache.get("all_20cm_codes", []) if len(it) >= 2}
    if (scan_src is not None) or mock_map:
        src_map = scan_src or {}
        iter_items = list(meta20_pre.items()) if all20_q_map is not None else [(c["code"], c["prev_close"]) for c in cands]
        seen_f08 = set()
        for c6, pre_ref in iter_items:
            seen_f08.add(c6)
            if c6 in mock_map:
                if float(mock_map[c6]) >= 0.195:
                    f1_mkt20_0925_zt += 1
                continue
            v = src_map.get(c6, {})
            q_dt = str(v.get("q_dt") or "")
            if sig_date and q_dt and q_dt <= sig_date:
                continue
            nm = str(v.get("name", ""))
            if "ST" in nm.upper() or "退" in nm:
                continue
            opx = float(v.get("open", 0.0) or 0.0)
            pc = float(v.get("pre") or v.get("pre_c") or pre_ref or 0.0)
            if opx > 0 and pc > 0:
                all20_valid_cnt += 1
                zt_px = float(np.floor(pc * 1.20 * 100.0 + 0.5) / 100.0)
                op_pct_i = opx / pc - 1.0
                if opx >= zt_px - 0.011 and op_pct_i >= 0.195:
                    f1_mkt20_0925_zt += 1
        for mk, mv in mock_map.items():
            if mk not in seen_f08 and _is_20cm_code(mk) and float(mv) >= 0.195:
                f1_mkt20_0925_zt += 1

    f08_pen = -5 if f1_mkt20_0925_zt >= 1 else 0
    results = []
    for c in cands:
        c6 = c["code"]
        lv = q_map.get(c6, {})
        nm = str(c.get("name") or lv.get("name") or c6)
        vetos = []
        if halt_ge16:
            vetos.append(f"空仓熔断(昨日20cm涨停{mkt20_zt_cnt}>=16)")
        if c.get("has_tox_90d"):
            vetos.append("近90日毒丸公告")
        if c.get("has_reg_10d"):
            vetos.append("近10日监管函")
        if "ST" in nm.upper() or "退" in nm:
            vetos.append("ST/退市剔除")

        pre_c = float(c["prev_close"])
        is_live = False
        if c6 in mock_map:
            is_live = True
            op_pct = float(mock_map[c6])
            op_px = round(pre_c * (1.0 + op_pct), 2)
            cur_px, cur_pct = op_px, op_pct
            zt_px = float(np.floor(pre_c * 1.20 * 100.0 + 0.5) / 100.0)
            is_yizi = bool(op_pct >= 0.195)
        else:
            q_dt = str(lv.get("q_dt") or "")
            is_live = bool(lv and ((not sig_date) or (q_dt > sig_date)) and float(lv.get("open", 0.0) or 0.0) > 0)
            if is_live:
                pre_c = float(lv.get("pre") or lv.get("pre_c") or pre_c)
                op_px = float(lv.get("open", 0.0) or 0.0)
                op_pct = (op_px / pre_c - 1.0) if pre_c > 0 else -1.0
                cur_px = float(lv.get("cur") or lv.get("close") or op_px)
                cur_pct = (cur_px / pre_c - 1.0) if (pre_c > 0 and cur_px > 0) else 0.0
                zt_px = float(np.floor(pre_c * 1.20 * 100.0 + 0.5) / 100.0)
                is_yizi = bool(lv.get("is_yizi", False) or (op_px >= zt_px - 0.011 and float(lv.get("low", 0.0) or 0.0) == float(lv.get("high", 0.0) or 0.0)))
            else:
                op_px, op_pct = 0.0, 0.0
                cur_px = float(lv.get("cur") or lv.get("close") or pre_c)
                cur_pct = float(lv.get("cpct") or lv.get("cur_pct") or 0.0)
                is_yizi = False

        if not is_live:
            vetos.append("盘后待明日09:25竞价")
        else:
            if is_yizi:
                vetos.append("一字涨停不可买")
            if not (-0.10 <= op_pct <= -0.030):
                vetos.append(f"今开{op_pct*100:+.2f}%出[-10%,-3%]")

        f01 = (-10 if op_pct < -0.080 else (4 if -0.070 <= op_pct <= -0.030 else 0)) if is_live else 0
        total_score = int(c["static_score"] + f01 + f08_pen)
        gates_ok = (len(vetos) == 0)
        passed_s = bool(gates_ok and total_score >= S_THR)
        passed_a_only = bool(gates_ok and A_THR <= total_score < S_THR)

        if not gates_ok:
            tier = "⛔熔断/未过门"
        elif passed_s:
            tier = "★S档(>=82可入单仓09:25直买)"
        elif passed_a_only:
            tier = "👀A档(76~81仅观察不入单仓)"
        else:
            tier = f"⛔未过线({total_score}<76)"

        b3_tp_pct = round(float(np.clip(1.5 * abs(op_pct), 0.06, 0.15)) * 100.0, 2) if is_live else 9.0
        results.append({
            **c,
            "name": nm,
            "is_live": is_live,
            "is_yizi": is_yizi,
            "open_px": round(op_px, 2),
            "open_pct": op_pct,
            "cur_px": round(cur_px, 2),
            "cur_pct": cur_pct,
            "f01_open_gap": f01,
            "f08_yizi20_siphon": f08_pen,
            "score": total_score,
            "gates_ok": gates_ok,
            "passed_S": passed_s,
            "passed_A_only": passed_a_only,
            "passed_base": passed_s,
            "tier_label": tier,
            "veto_reasons": vetos,
            "b3_tp_pct": b3_tp_pct,
        })

    results.sort(key=lambda x: (-int(x["passed_S"]), -int(x["passed_A_only"]), -x["score"], x["code"]))
    return results, {
        "sig_date": sig_date,
        "mkt20_zt_cnt": mkt20_zt_cnt,
        "halt_ge16": halt_ge16,
        "is_monday": is_monday,
        "f1_mkt20_0925_zt": f1_mkt20_0925_zt,
        "f08_pen": f08_pen,
        "all20_valid_cnt": all20_valid_cnt,
    }


def _print_exit_tree_rules() -> None:
    print("\n【20cm 首板深水错杀 V1.1 四分支动态卖树与 inst_dt 风控开关 (+0.30%穿价缓冲)】")
    print("  1. 分支① D1涨停      : 次日起续骑涨停，首个非涨停日收盘卖（20cm跌停顺延至首个可卖日收盘）。")
    print("  2. 分支② D1强真阳    : 收盘较开盘>=+6%且CLV>=0.65 -> D2挂相对D1收盘+12%限价止盈(穿价high>=target*1.003); 无风控未触持至D3。")
    print("  3. 分支③ D1温和震荡  : D2盘前挂自适应限价 clip(1.5*|低开|, 6%, 15%) (穿价*1.003)，未触则D2收盘清。")
    print("  4. 分支④ D1深阴/跌停 : 收盘较开盘<=-5%或跌停 -> 严禁D2 09:25恐慌斩仓，持至D2收盘平仓（跌停顺延）。")
    print("  5. inst_dt 风控开关  : D1盘后机构净卖>2000万 或 20cm跌停>=3家 或 10cm跌停>=20家 -> 止盈上限压紧至+7%并关闭分支② D3延持。")


def print_premarket(cache: dict) -> None:
    sig_date = cache.get("sig_date", "")
    buy_date = cache.get("buy_date", "")
    mkt20 = int(cache.get("mkt20_zt_cnt", 0))
    halt = bool(cache.get("halt_ge16", mkt20 >= 16))
    mkt10 = int(cache.get("mkt10_zt_cnt", 0))
    is_mon = bool(cache.get("is_monday", False))
    cands = cache.get("candidates", [])

    print("=" * 96)
    print(f"【20cm 首板深水错杀反抽 V1.1 (s_20cm_deepopen) · 盘前推演面板】基准D0={sig_date} -> 买入日={buy_date}")
    halt_desc = f"🚨 昨日20cm涨停={mkt20}家 >= 16家【触发绝对空仓熔断！今日全天禁开仓】" if halt else f"✅ 昨日20cm涨停={mkt20}家 < 16家（正常允许观察竞价）"
    print(f"生态与日历: {halt_desc} | 昨日10cm涨停={mkt10}家 | 周一扣8分={'是(-8)' if is_mon else '否(0)'}")
    print("=" * 96)
    if not cands:
        print("  昨日无满足硬门槛的 20cm 非一字首板候选（非ST/成交额>=1亿/收>=2元）。")
    else:
        for i, c in enumerate(cands, 1):
            st_sc = int(c["static_score"])
            # Evaluate sweet zone [-7%,-3%] (+4) with and without F08 (-5)
            s_sweet_clean = st_sc + 4
            s_sweet_siphon = st_sc + 4 - 5
            s_edge_clean = st_sc
            need_list = []
            if halt:
                need_list.append("🚨已熔断")
            else:
                if c.get("has_tox_90d"):
                    need_list.append("⛔90日毒丸")
                if c.get("has_reg_10d"):
                    need_list.append("⛔10日监管")
                if not need_list:
                    if s_sweet_siphon >= S_THR:
                        need_list.append(f"甜区[-7%,-3%]稳进S档(>={S_THR:.0f},无惧虹吸)")
                    elif s_sweet_clean >= S_THR:
                        need_list.append(f"甜区[-7%,-3%]且无20cm一字虹吸可达S档({s_sweet_clean}>={S_THR:.0f})")
                    elif s_sweet_clean >= A_THR:
                        need_list.append(f"甜区[-7%,-3%]最高A档观察({s_sweet_clean},仅观察不入单仓)")
                    else:
                        need_list.append(f"底分不足(甜区最高{s_sweet_clean}<76)")
            sf = c.get("static_factors", {})
            fac_s = f"rfm={c['real_free_mcap']:.1f}亿({sf.get('F02_rfm',0):+d}) dist30={c['dist_3d30']*100:.1f}%({sf.get('F03_dist3d30',0):+d}) zt60={c['zt_cnt_60d']}({sf.get('F04_zt60d',0):+d}) 封成={c['zt_seal_ratio']*100:.1f}%({sf.get('F05_seal10',0):+d}) 机构={c['lhb_inst_net']:+.0f}万({sf.get('F06_inst',0):+d})"
            print(
                f"  {i:02d}|{c['code']} {c['name']:<6s}|昨收{c['prev_close']:>6.2f}|额{c['amount_yi']:>5.1f}亿|静态底分={st_sc:2d}|"
                f"甜区[{s_sweet_siphon}~{s_sweet_clean}]|{'；'.join(need_list)}"
            )
            print(f"     {fac_s}")
    _print_exit_tree_rules()


def run_hold_check(raw_code: str, buy_date_arg: str = "", buy_px_arg: float = 0.0) -> None:
    c6 = str(raw_code).strip()[-6:].zfill(6)
    sym = _mkt_prefix(c6) + c6
    now_dt = datetime.datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d")

    kl = _fetch_tencent_qfq_kline(sym, datalen=20)
    q_one = fetch_tencent_quotes([sym]).get(c6, {})
    bars_map = {b["dt"]: b for b in kl}
    if q_one.get("q_dt") and q_one.get("close", 0) > 0:
        bars_map[q_one["q_dt"]] = {
            "dt": q_one["q_dt"], "open": float(q_one["open"]),
            "close": float(q_one["close"]), "high": float(q_one["high"]), "low": float(q_one["low"]),
        }
    dts = sorted(bars_map.keys())
    buy_date = buy_date_arg.strip() or (q_one.get("q_dt") or today_str)
    if buy_date not in bars_map and dts:
        buy_date = dts[-1]
    b_idx = dts.index(buy_date) if buy_date in dts else len(dts) - 1
    sig_date = dts[b_idx - 1] if b_idx >= 1 else ""

    b_d1 = bars_map.get(buy_date, {})
    b_d0 = bars_map.get(sig_date, {})
    d0_c = float(b_d0.get("close") or q_one.get("pre_c") or 0.0)
    d1_o = float(b_d1.get("open") or buy_px_arg or 0.0)
    d1_h = float(b_d1.get("high") or d1_o)
    d1_l = float(b_d1.get("low") or d1_o)
    d1_c = float(b_d1.get("close") or q_one.get("close") or d1_o)
    buy_px = float(buy_px_arg) if buy_px_arg > 0 else d1_o
    op_gap = (d1_o / d0_c - 1.0) if (d0_c > 0 and d1_o > 0) else -0.05
    d1_body = (d1_c / d1_o - 1.0) if (d1_o > 0 and d1_c > 0) else 0.0
    d1_clv = (d1_c - d1_l) / (d1_h - d1_l) if d1_h > d1_l else 0.5
    d1_zt_px = float(np.floor(d0_c * 1.20 * 100.0 + 0.5) / 100.0) if d0_c > 0 else 999.0
    d1_dt_px = float(np.floor(d0_c * 0.80 * 100.0 + 0.5) / 100.0) if d0_c > 0 else 0.0
    d1_is_zt = bool(d0_c > 0 and d1_c >= d1_zt_px - 0.011 and (d1_c / d0_c - 1.0) >= 0.195)
    d1_is_dt = bool(d0_c > 0 and d1_c <= d1_dt_px + 0.011 and (d1_c / d0_c - 1.0) <= -0.195)

    # inst_dt check on buy_date (or latest active trading date)
    ref_dt = q_one.get("q_dt") or today_str
    st_2026 = {str(x)[:6].zfill(6) for x in json.load(open(ST_UNIVERSE, encoding="utf-8")).get("codes", [])} if os.path.exists(ST_UNIVERSE) else set()
    mkt20_dt_cnt = mkt10_dt_cnt = 0
    try:
        max_pq_dt = sorted(ds.dataset(A_DAILY).scanner(columns=["date"], filter=ds.field("date") >= pd.Timestamp(_shift_cal(today_str, -20))).to_table().column("date").to_pylist())[-1].strftime("%Y-%m-%d")
        sub_codes_df = ds.dataset(A_DAILY).scanner(columns=["ticker"], filter=ds.field("date") == pd.Timestamp(max_pq_dt)).to_table().to_pandas()
        sub_codes_df["c6"] = sub_codes_df["ticker"].astype(str).str[:6]
        all_act_codes = [c for c in sub_codes_df[sub_codes_df["c6"].str.startswith(("00", "60", "30", "688", "689"))]["c6"].tolist() if c not in st_2026]
        q_all = fetch_tencent_quotes(all_act_codes)
        for ck, qv in q_all.items():
            if len(ck) != 6 or qv.get("q_dt") != ref_dt:
                continue
            nm_q = str(qv.get("name", ""))
            if "ST" in nm_q.upper() or "退" in nm_q:
                continue
            px_q, pc_q = float(qv.get("close", 0.0) or 0.0), float(qv.get("pre_c", 0.0) or 0.0)
            if px_q <= 0 or pc_q <= 0:
                continue
            if _is_20cm_code(ck):
                if px_q <= float(np.floor(pc_q * 0.80 * 100.0 + 0.5) / 100.0) + 0.011 and (px_q / pc_q - 1.0) <= -0.195:
                    mkt20_dt_cnt += 1
            else:
                if px_q <= float(np.floor(pc_q * 0.90 * 100.0 + 0.5) / 100.0) + 0.011 and (px_q / pc_q - 1.0) <= -0.095:
                    mkt10_dt_cnt += 1
    except Exception as e:
        print(f"[WARN] 实时跌停环境统计失败: {e}", file=sys.stderr)

    lhb_d1_map, has_d1_lhb = _compute_lhb_inst_net_by_date(buy_date, codes_filter={c6})
    d1_inst_net = lhb_d1_map.get(c6)
    if d1_inst_net is None and not has_d1_lhb:
        d1_inst_net = _fetch_lhb_inst_net_online(c6, buy_date)
    d1_inst_net = float(d1_inst_net or 0.0)
    risk_hit = bool((d1_inst_net < -2000.0) or (mkt20_dt_cnt >= 3) or (mkt10_dt_cnt >= 20))

    if d1_is_zt:
        branch = "B1_D1涨停续骑（次日起首个非涨停日收盘卖，跌停顺延）"
        tp_rate = None
    elif (d1_body <= -0.05) or d1_is_dt:
        branch = "B4_D1深阴/跌停（严禁D2 09:25恐慌斩仓，持至D2收盘平仓）"
        tp_rate = None
    elif (d1_body >= 0.06) and (d1_clv >= 0.65):
        tp_rate = 0.07 if risk_hit else 0.12
        branch = f"B2_D1强真阳（D2挂+{tp_rate*100:.0f}%止盈；{'已触发inst_dt关闭D3延持->D2收盘清' if risk_hit else '未触则延持至D3'}）"
    else:
        raw_b3 = float(np.clip(1.5 * abs(op_gap), 0.06, 0.15))
        tp_rate = min(raw_b3, 0.07) if risk_hit else raw_b3
        branch = f"B3_D1温和震荡（D2挂自适应+{tp_rate*100:.2f}%止盈，未触则D2收盘清）"

    print("=" * 96)
    print(f"【20cm 深水错杀 V1.1 持仓动态卖树核查】{c6} {q_one.get('name', c6)} | 买日D1={buy_date} | 买价={buy_px:.2f}元")
    print(f"D0={sig_date} 收={d0_c:.2f} | D1低开={op_gap*100:+.2f}% | D1 O/H/L/C={d1_o:.2f}/{d1_h:.2f}/{d1_l:.2f}/{d1_c:.2f} | 实体={d1_body*100:+.2f}% CLV={d1_clv:.3f}")
    print(f"[inst_dt 风控开关]: D1机构净买={d1_inst_net:+.1f}万 (<-2000万触发) | {ref_dt} 20cm跌停={mkt20_dt_cnt}家(>=3触发) | 10cm跌停={mkt10_dt_cnt}家(>=20触发) -> {'🚨已触发(止盈封顶+7%且禁D3延持)' if risk_hit else '✅未触发(正常参数)'}")
    print(f"[当前卖树分支]: {branch}")
    if tp_rate is not None and d1_c > 0:
        tp_px = round(d1_c * (1.0 + tp_rate), 2)
        d2_zt = float(np.floor(d1_c * 1.20 * 100.0 + 0.5) / 100.0)
        pen_px = round(min(tp_px * (1.0 + TP_BUF), d2_zt - 0.01), 2)
        print(f"★【D2 盘前限价止盈挂单】: {tp_px:.2f} 元 (相对D1收 {d1_c:.2f} +{tp_rate*100:.2f}%) | 严格+0.30%穿价确认价={pen_px:.2f} 元 (涨停={d2_zt:.2f})")
    print("=" * 96)


def main():
    ap = argparse.ArgumentParser(description="20cm 首板深水错杀反抽 V1.1 生产实盘引擎 (s_20cm_deepopen)")
    ap.add_argument("--build-cache", action="store_true", help="构建盘前缓存 20cm_deepopen_premarket_cache.json")
    ap.add_argument("--premarket", action="store_true", help="早盘盘前推演与静态底分面板")
    ap.add_argument("--mock-open", type=str, default="", help="模拟竞价涨幅，如 '300006=-0.055'")
    ap.add_argument("--hold", type=str, default="", help="持仓四分支动态卖树与 inst_dt 开关核查")
    ap.add_argument("--buy-date", type=str, default="", help="可选：配合 --hold 指定买入日期")
    ap.add_argument("--buy-px", type=float, default=0.0, help="可选：配合 --hold 指定买入价")
    ap.add_argument("--as-of", type=str, default="", help="可选：历史指定收盘日内存验算")
    ap.add_argument("--date", type=str, default="", help="查询 V1.1 历史台账指定买日")
    ap.add_argument("--recent", type=int, default=0, help="查询 V1.1 历史台账最近 N 笔")
    ap.add_argument("--all-a", action="store_true", help="查询台账时使用 A档>=76 全账（默认S档>=82）")
    args = ap.parse_args()

    if args.hold:
        run_hold_check(args.hold, buy_date_arg=args.buy_date, buy_px_arg=args.buy_px)
        return

    if args.date or args.recent > 0:
        csv_p = LEDGER_A76_CSV if args.all_a else LEDGER_S82_CSV
        df_l = pd.read_csv(csv_p, dtype={"c6": str})
        df_l["c6"] = df_l["c6"].str.zfill(6)
        sub = df_l[df_l["buy_date"] == args.date] if args.date else df_l.sort_values("buy_date").tail(args.recent)
        print(sub[["buy_date", "exit_date", "c6", "score", "open_pct", "net_ret", "exit_reason", "risk_hit"]].to_string(index=False))
        return

    if args.as_of:
        cache = build_premarket_cache(verbose=True, as_of_date=args.as_of)
        print_premarket(cache)
        return

    if args.build_cache or not os.path.exists(CACHE_FILE):
        cache = build_premarket_cache(verbose=True)
        if args.build_cache:
            return
    else:
        cache = json.load(open(CACHE_FILE, "r", encoding="utf-8"))

    if args.premarket:
        print_premarket(cache)
        return

    t0 = time.time()
    cands = cache.get("candidates", [])
    mock_map = {}
    if args.mock_open:
        for pair in args.mock_open.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                mock_map[k.strip()[-6:].zfill(6)] = float(v.strip())

    q_cand = fetch_tencent_quotes([c["code"] for c in cands]) if cands else {}
    all20_q = None
    if cands and not cache.get("halt_ge16", False):
        all_codes = [str(it[0]).zfill(6) for it in cache.get("all_20cm_codes", [])]
        if all_codes:
            all20_q = fetch_tencent_quotes(all_codes)

    rows, meta = evaluate_20cm_candidates(cache, q_cand, all20_q_map=all20_q, mock_map=mock_map)
    print("=" * 96)
    print(
        f"【20cm 首板深水错杀反抽 V1.1 · 09:25 实时裁决】D0={meta['sig_date']} | 昨日20cm涨停={meta['mkt20_zt_cnt']}家"
        f"{' 🚨空仓熔断(>=16)' if meta['halt_ge16'] else ''} | 今日09:25 20cm一字={meta['f1_mkt20_0925_zt']}家(F08={meta['f08_pen']:+d}) | 耗时{time.time()-t0:.2f}s"
    )
    winners_s = [r for r in rows if r["passed_S"]]
    obs_a = [r for r in rows if r["passed_A_only"]]
    if meta["halt_ge16"]:
        print(f"`🚨[s_20cm_deepopen] 昨日20cm涨停 {meta['mkt20_zt_cnt']} 家 >= 16 家，触发全天空仓熔断！`")
    elif winners_s:
        w = winners_s[0]
        print(
            f"`🎯[s_20cm_deepopen S档>=82 第6顺位09:25直买] {w['code']} {w['name']} {w['score']}分 | "
            f"今开 {w['open_px']:.2f}元 ({w['open_pct']*100:+.2f}%) | B3参考止盈 +{w['b3_tp_pct']:.2f}%`"
        )
    else:
        print("`⛔[s_20cm_deepopen] 今日无 S档>=82 过线标的，20cm单仓空仓。`")
    if obs_a:
        print(f"👀[A档76~81仅观察不入单仓]: " + "，".join(f"{r['code']} {r['name']}({r['score']}分,今开{r['open_pct']*100:+.2f}%)" for r in obs_a))
    print("=" * 96)
    for i, r in enumerate(rows, 1):
        v_s = "；".join(r["veto_reasons"]) if r["veto_reasons"] else "门禁全过"
        op_s = f"{r['open_pct']*100:+.2f}%" if r["is_live"] else "待09:25"
        print(f"  {i:02d}|{r['code']}|{r['name']}|底分{r['static_score']}|F01={r['f01_open_gap']:+d}|F08={r['f08_yizi20_siphon']:+d}|总分{r['score']:2d}|今开{op_s}|{r['tier_label']}|{v_s}")
    _print_exit_tree_rules()


if __name__ == "__main__":
    main()
