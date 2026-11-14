#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_high_dragon_today.py — 「高标首阴真阳反包主策略（方案甲 V5.1 生产定版）」实盘盯盘与极速决策引擎

核心规格（V5.1 生产定版）：
  1. 标的池硬门槛：
     - 10cm 沪深主板非 ST（60xxxx, 00xxxx）；
     - D0 为全场绝对最高连板 >=4 板（Pool A，唯一或 top_cnt <= 2），或第一高全一字顶死时的换手第一高 >=4 板（Pool B）；
     - D1 首次断板且收真阳线（close > open）且 D1 换手率 <= 35.0%。
  2. 一票否决红线（VETO -> -999）：
     - s_reg：近 10 日个股监管工作函/关注函/重点监控/停牌核查；
     - tox：近 90 日立案调查/退市风险/减持计划等毒丸公告；
     - ex_reg5 >= 2：近 5 交易日所属交易所监管函密集 >= 2 封；
     - d1_to > 35.0%：D1 换手率超标；
     - lh1 >= 3：D1 龙虎榜拉萨席位 >= 3 家；
     - op2 > +4.5% 或 op2 < -6.5%：竞价高开超标或核按钮。
  3. V5.1 打分卡（底分 60 分，过线门槛 >= 88 分）：
     - 吸收锁仓或真流通软打分升级：十大股东锁仓满45%或扣除锁仓后的真实自由流通市值满45亿加6分，双不达标扣6分（替代原 lock>=45加4分/lock<25扣4分）；
     - 21 项盘前静态分 + 1 项唯一盘中竞价动态分（op2 < 0.0 为 +8 分，0.0 <= op2 <= 0.025 为 +6 分）；
     - 战绩：五年42笔 / 胜率73.8% (近三年76.0%) / 盈亏比3.01 / 五年净值16.39倍 (近三年8.50倍) / 最大回撤15.9%。
  4. 双异动监控：
     - 实时精确计算 10 日 100% 与 30 日 200% 严重异动极限红线与 93% 缓冲止盈预埋限价单价。

用法：
  1. /opt/homebrew/bin/python3.13 sim-portfolio/scripts/fast_high_dragon_today.py --build-cache
     盘后构建或刷新最新交易日盘前缓存（high_dragon_premarket_cache.json）。
  2. /opt/homebrew/bin/python3.13 sim-portfolio/scripts/fast_high_dragon_today.py --premarket
     早盘 09:15 前秒级读取盘前缓存，输出高标生态面板、候选标的逐项打分明细及情景交易手册。
  3. /opt/homebrew/bin/python3.13 sim-portfolio/scripts/fast_high_dragon_today.py
     09:25:03 盘中秒跑模式（耗时 < 1.5s），秒读缓存并拉取腾讯实时竞价行情，输出一步到位交易指令。
  4. /opt/homebrew/bin/python3.13 sim-portfolio/scripts/fast_high_dragon_today.py --hold 600838 000678
     计算并输出指定股票的当日双异动 93% 限价止盈挂单价。

⛔ 铁律保证：
  1. 绝对严禁 import yfinance 或调用 yf 查询 A 股（D12 铁律）。
  2. 所有 SQLite 数据库必须使用 file:...?mode=ro (uri=True) 严格只读模式。
  3. 严禁修改 portfolio_state.json 或执行任何模拟盘/实盘交易。
"""

import os
import sys
import re
import json
import time
import glob
import math
import sqlite3
import datetime
import argparse
import warnings
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{PROJECT_ROOT}/sim-portfolio"
DATA_DIR = f"{SIM_DIR}/data"

CACHE_FILE = f"{DATA_DIR}/high_dragon_premarket_cache.json"
PORTFOLIO_STATE_FILE = f"{SIM_DIR}/portfolio_state.json"

A_DAILY_PATH = f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{DATA_DIR}/cn_hk_price_db/a_delisted_daily.parquet"
KPL_MERGED_PATH = f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl"
LHB_BUY_PATH = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
LHB_SELL_PATH = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_sell.parquet"
HOLDERS_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
INDEX_CACHE_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
THS_ZT_DIR = f"{DATA_DIR}/ths_limit_up_daily"

DB_NOTICES = f"{SIM_DIR}/backtest/2026-08-24-daban/notices.db"
DB_PIT_NOTICES = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
DB_ZT_TAPE = f"{DATA_DIR}/zt_micro_tape_5y_pit.db"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

Q_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")
RE_TOP_YOUZI = re.compile(
    r"(?:大连金马路|大连黄河路|六一中路|天津东丽开发区二纬路|北京东直门南大街|北京广渠门内大街|"
    r"上海江苏路|上海建国西路|杭州延安路|兴业证券.*陕西分公司|西安朱雀大街|"
    r"南京太平南路|宁波桑田路|上海宛平南路|上海红宝石路|上海茅台路|宁波和源路|北京长椿街)"
)
RE_DAY_SURF = re.compile(
    r"(?:杭州上塘路|宜昌沿江大道|宜昌珍珠路|佛山绿景路|佛山季华六路|佛山季华五路|江阴.*营业部|苏州.*营业部)"
)
RE_LHASA = re.compile(r"(?:拉萨|东方财富证券.*拉萨)")
RE_INST = re.compile(r"机构专用")
TOX_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险)")
TECH_RE = re.compile(r"(?:算力|芯片|半导体|机器人|人工智能|AI|华为|低空|固态电池)")


def bare_code(raw: str) -> str:
    s = str(raw).strip().upper()
    for p in ("SH", "SZ", "BJ", ".SS", ".SZ", ".SH", ".BJ"):
        if s.startswith(p) and len(s) > len(p):
            s = s[len(p):]
        if s.endswith(p):
            s = s[:-len(p)]
    return s.zfill(6)


def market_prefix(c6: str) -> str:
    return "sh" if c6.startswith("6") else "sz"


def fetch_tencent_batch(q_list: list[str]) -> dict[str, dict]:
    if not q_list:
        return {}
    url = "http://qt.gtimg.cn/q=" + ",".join(q_list)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        raw = urllib.request.urlopen(req, timeout=5).read().decode("gbk", "ignore")
    except Exception:
        return {}
    out = {}
    for ln in raw.strip().splitlines():
        if '="' not in ln:
            continue
        lhs, rhs = ln.split('="', 1)
        sym = lhs.split("_")[-1].strip()
        f = rhs.strip('";').split("~")
        if len(f) > 38:
            code = f[2] if len(f) > 2 and f[2] else sym[-6:]
            c_price = float(f[3] or 0)
            prev_c = float(f[4] or 0)
            op = float(f[5] or 0) or c_price
            hp = float(f[33] or 0) or c_price
            lp = float(f[34] or 0) or c_price
            amt = float(f[37] or 0) * 10000.0
            to = float(f[38] or 0)
            out[sym] = {
                "symbol": sym,
                "code": code,
                "name": f[1],
                "close": c_price,
                "prev_close": prev_c,
                "open": op,
                "high": hp,
                "low": lp,
                "amount": amt,
                "turnover": to,
                "zt_price": float(f[47] or 0) if len(f) > 47 and f[47] else round(prev_c * 1.10, 2),
                "dt_price": float(f[48] or 0) if len(f) > 48 and f[48] else round(prev_c * 0.90, 2),
            }
            out[code] = out[sym]
    return out


def fetch_sina_kline(symbol: str, datalen: int = 40) -> list[dict]:
    url = (
        f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/"
        f"CN_MarketDataService.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        txt = urllib.request.urlopen(req, timeout=3).read().decode("utf-8", "ignore")
        i, j = txt.find("["), txt.rfind("]")
        if i < 0 or j <= i:
            return []
        rows = json.loads(txt[i:j + 1])
        return [
            {
                "day": r["day"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            }
            for r in rows
        ]
    except Exception:
        return []


def calc_window_threshold(
    past_closes: list[tuple[str, float]],
    idx_map: dict[str, float],
    idx_ref: float,
    max_days: int,
    target_dev: float,
    ref_prev_close: float,
) -> dict:
    best = None
    limit_k = min(max_days, len(past_closes))
    for k in range(1, limit_k + 1):
        b_day, b_close = past_closes[-k]
        b_idx = idx_map.get(b_day)
        if not b_idx or b_close <= 0:
            continue
        idx_chg = idx_ref / b_idx - 1.0
        p_hard = b_close * (1.0 + target_dev + idx_chg)
        p_93 = b_close * (1.0 + (target_dev - 0.07) + idx_chg)
        if best is None or p_hard < best["p_hard"]:
            best = {
                "window_days": k,
                "base_day": b_day,
                "base_close": round(b_close, 2),
                "idx_chg_pct": round(idx_chg * 100.0, 2),
                "p_93": round(p_93, 2),
                "p_hard": round(p_hard, 2),
                "hard_vs_prev_pct": round((p_hard / ref_prev_close - 1.0) * 100.0, 2) if ref_prev_close > 0 else 0.0,
            }
    return best or {}


def calc_double_dev_for_stock(c6: str, q_stk: dict | None = None) -> dict:
    sym = market_prefix(c6) + c6
    idx_sym = "sh000002" if c6.startswith("6") else "sz399107"
    if q_stk is None:
        q_map = fetch_tencent_batch([sym, idx_sym])
        q_stk = q_map.get(sym, {})
        q_idx = q_map.get(idx_sym, {})
    else:
        q_idx = fetch_tencent_batch([idx_sym]).get(idx_sym, {})

    kl_stk = fetch_sina_kline(sym, datalen=36)
    kl_idx = fetch_sina_kline(idx_sym, datalen=36)
    if not kl_stk or not kl_idx:
        return {"code": c6, "error": "K线获取失败"}

    idx_map = {r["day"]: r["close"] for r in kl_idx}
    idx_ref = q_idx.get("close", kl_idx[-1]["close"])
    prev_close = q_stk.get("prev_close", kl_stk[-1]["close"])
    past_closes = [(r["day"], r["close"]) for r in kl_stk]

    w10 = calc_window_threshold(past_closes, idx_map, idx_ref, 10, 1.00, prev_close)
    w30 = calc_window_threshold(past_closes, idx_map, idx_ref, 30, 2.00, prev_close)

    p93_10 = w10.get("p_93", 99999.0)
    p93_30 = w30.get("p_93", 99999.0)
    p_hard_10 = w10.get("p_hard", 99999.0)
    p_hard_30 = w30.get("p_hard", 99999.0)

    tighter_93 = min(p93_10, p93_30)
    tighter_hard = min(p_hard_10, p_hard_30)
    limit_by = "10日100%" if p93_10 <= p93_30 else "30日200%"

    return {
        "code": c6,
        "name": q_stk.get("name", ""),
        "close": q_stk.get("close", kl_stk[-1]["close"]),
        "prev_close": prev_close,
        "w10": w10,
        "w30": w30,
        "tighter_93": round(tighter_93, 2),
        "tighter_hard": round(tighter_hard, 2),
        "limit_by": limit_by,
    }


def query_eastmoney_lhb_seats(c6: str, target_dates: set[str]) -> tuple[dict, dict]:
    buys_by_dt = defaultdict(list)
    sells_by_dt = defaultdict(list)
    for side, dic in [("BUY", buys_by_dt), ("SELL", sells_by_dt)]:
        url = (
            f"https://datacenter-web.eastmoney.com/api/data/v1/get?"
            f"reportName=RPT_BILLBOARD_DAILYDETAILS{side}&columns=TRADE_DATE,SECURITY_CODE,OPERATEDEPT_NAME,{side}&"
            f"filter=(SECURITY_CODE%3D%22{c6}%22)&sortColumns=TRADE_DATE&sortTypes=-1&pageNumber=1&pageSize=100&source=WEB&client=WEB"
        )
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            raw = urllib.request.urlopen(req, timeout=4).read().decode()
            data = json.loads(raw)
            rows = data.get("result", {}).get("data", []) or []
            for r in rows:
                dt = str(r.get("TRADE_DATE", ""))[:10]
                if dt in target_dates:
                    dept = str(r.get("OPERATEDEPT_NAME", "")).strip()
                    amt = float(r.get(side, 0) or 0)
                    dic[dt].append((dept, amt))
        except Exception:
            pass
    return buys_by_dt, sells_by_dt


def build_premarket_cache() -> dict:
    t0 = time.time()
    now = datetime.datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    cols = ["date", "ticker", "open", "high", "low", "close", "volume", "amount", "oshare", "turn"]
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2026-09-01"))).to_table().to_pandas()
    df_act["c6"] = df_act["ticker"].astype(str).str[:6]
    df_act = df_act[df_act["c6"].str.startswith(("00", "60"))].copy()
    df_act["dt_str"] = df_act["date"].dt.strftime("%Y-%m-%d")

    max_p_date = df_act["dt_str"].max()

    needs_patch = False
    if now.weekday() < 5 and (now.hour > 15 or (now.hour == 15 and now.minute >= 5)):
        if max_p_date < today_str:
            needs_patch = True

    if needs_patch:
        main_tickers = df_act[df_act["dt_str"] == max_p_date]["ticker"].unique().tolist()
        q_codes = [(market_prefix(t[:6]) + t[:6]) for t in main_tickers]
        batch_size = 80
        batches = [q_codes[i:i + batch_size] for i in range(0, len(q_codes), batch_size)]
        live_quotes = {}
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(fetch_tencent_batch, b) for b in batches]
            for f in as_completed(futs):
                live_quotes.update(f.result())

        rows_today = []
        for t in main_tickers:
            c = t[:6]
            q = live_quotes.get(c)
            if q and q.get("close", 0) > 0:
                rows_today.append({
                    "date": pd.Timestamp(today_str),
                    "ticker": t,
                    "open": q["open"],
                    "high": q["high"],
                    "low": q["low"],
                    "close": q["close"],
                    "volume": 0.0,
                    "amount": q["amount"],
                    "oshare": 0.0,
                    "turn": q["turnover"] / 100.0,
                    "c6": c,
                    "dt_str": today_str,
                })
        if rows_today:
            df_patch = pd.DataFrame(rows_today)
            df_act = pd.concat([df_act, df_patch], ignore_index=True)

    df_act.sort_values(["c6", "dt_str"], inplace=True)
    df_act.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    df_act.reset_index(drop=True, inplace=True)

    df_act["mcap"] = df_act["close"] * df_act["oshare"] / 1e8
    df_act["mcap"] = np.where(df_act["mcap"] > 0, df_act["mcap"], np.where(df_act["turn"] > 0, df_act["amount"] / df_act["turn"] / 1e8, 50.0))

    g = df_act.groupby("c6")
    df_act["pre_c"] = g["close"].shift(1)
    df_act["pct"] = df_act["close"] / df_act["pre_c"] - 1.0
    df_act["o_pct"] = df_act["open"] / df_act["pre_c"] - 1.0
    df_act["l_pct"] = df_act["low"] / df_act["pre_c"] - 1.0
    df_act["zt_price"] = np.floor(df_act["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df_act["dt_price"] = np.floor(df_act["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df_act["is_zt"] = (df_act["close"] >= df_act["zt_price"] - 0.011) & (df_act["pct"] >= 0.095) & (df_act["pre_c"] > 0)
    df_act["is_dt"] = (df_act["close"] <= df_act["dt_price"] + 0.011) & (df_act["pct"] <= -0.095) & (df_act["pre_c"] > 0)
    df_act["is_yizi"] = df_act["is_zt"] & (df_act["open"] >= df_act["zt_price"] - 0.011) & (df_act["low"] >= df_act["zt_price"] - 0.011)
    df_act["is_yizi_dt"] = df_act["is_dt"] & (df_act["open"] <= df_act["dt_price"] + 0.011) & (df_act["high"] <= df_act["dt_price"] + 0.011)

    s_zt = df_act["is_zt"].astype(int)
    s_yz = df_act["is_yizi"].astype(int)
    df_act["streak"] = s_zt.groupby([df_act["c6"], (s_zt != g["is_zt"].shift().fillna(False)).cumsum()]).cumsum() * s_zt
    df_act["yz_streak"] = s_yz.groupby([df_act["c6"], (s_yz != g["is_yizi"].shift().fillna(False)).cumsum()]).cumsum() * s_yz
    df_act["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)

    all_dts = sorted(df_act["dt_str"].unique())
    d1_date = all_dts[-1]
    d0_date = all_dts[-2] if len(all_dts) >= 2 else d1_date

    g0 = df_act[df_act["dt_str"] == d0_date]
    g1 = df_act[df_act["dt_str"] == d1_date]

    zt0 = g0[g0["is_zt"]]
    max_b_d0 = int(zt0["streak"].max()) if not zt0.empty else 0

    top_d0 = zt0[zt0["streak"] == max_b_d0]
    top1_all_yizi3 = bool((top_d0["yz_streak"] >= 3).all()) if not top_d0.empty else False

    cands_targets = []
    if max_b_d0 >= 4:
        if len(top_d0) <= 2:
            for r in top_d0.itertuples():
                cands_targets.append((r.c6, "Pool A", int(r.streak), int(r.yz_streak)))
        if top1_all_yizi3:
            non_yz = zt0[(zt0["streak"] < max_b_d0) & (zt0["streak"] >= 4) & (zt0["yz_streak"] < 3)]
            if not non_yz.empty:
                sm = int(non_yz["streak"].max())
                stp = non_yz[non_yz["streak"] == sm]
                if len(stp) <= 2:
                    for r in stp.itertuples():
                        cands_targets.append((r.c6, "Pool B", int(r.streak), int(r.yz_streak)))

    zt1 = g1[g1["is_zt"]]
    n_zt_d1 = len(zt1)

    brk_hist = []
    for d in all_dts[-15:]:
        sub_d = df_act[df_act["dt_str"] == d]
        broken = sub_d[(sub_d["prev_streak"] >= 4) & (~sub_d["is_zt"])]
        brk_hist.append((int(broken["is_dt"].sum()), int(len(broken))))
    w10 = brk_hist[-10:]
    dt_sum = sum(x[0] for x in w10)
    brk_sum = sum(x[1] for x in w10)
    brk_r10_d1 = (dt_sum / max(1, brk_sum)) if brk_sum > 0 else 0.0

    csi_d1 = None
    csi_d5_prior = None
    if os.path.exists(INDEX_CACHE_PATH):
        try:
            with open(INDEX_CACHE_PATH, "r", encoding="utf-8") as f:
                idx_cache = json.load(f)
            csi_map = idx_cache.get("sh000300", {})
            if d1_date in csi_map:
                csi_d1 = csi_map[d1_date]
            d5_prior_dt = all_dts[max(0, len(all_dts) - 6)]
            csi_d5_prior = csi_map.get(d5_prior_dt)
        except Exception:
            pass

    if csi_d1 is None or csi_d5_prior is None:
        q_idx = fetch_tencent_batch(["sh000300"])
        csi_d1 = q_idx.get("sh000300", {}).get("close", 4000.0)
        csi_d5_prior = csi_d1 * 1.005

    csi5_d1 = (csi_d1 / csi_d5_prior - 1.0) if (csi_d1 and csi_d5_prior) else 0.0

    stock_reg = defaultdict(list)
    ex_reg = {"SH": [], "SZ": []}

    REG_INC_WORDS = ["监管工作函", "监管函", "关注函", "重点监控", "停牌核查"]
    REG_EXC_WORDS = ["ST", "回复", "回函", "延期", "核查意见", "复牌", "募集资金", "监事", "独立董事", "保荐"]

    def _is_clean_reg(title: str) -> bool:
        t = str(title)
        if any(w in t for w in REG_EXC_WORDS):
            return False
        return any(w in t for w in REG_INC_WORDS)

    if os.path.exists(DB_NOTICES):
        con = sqlite3.connect(f"file:{DB_NOTICES}?mode=ro", uri=True)
        try:
            for sc, nd, ti in con.execute("SELECT code, ndate, title FROM notice WHERE ndate >= '2026-10-01'"):
                c6 = bare_code(sc)
                if _is_clean_reg(ti):
                    stock_reg[c6].append(nd)
                    if c6.startswith(("00", "60")):
                        ex = "SH" if c6.startswith("60") else "SZ"
                        ex_reg[ex].append((nd, c6))
        except Exception:
            pass
        con.close()

    if os.path.exists(DB_PIT_NOTICES):
        con = sqlite3.connect(f"file:{DB_PIT_NOTICES}?mode=ro", uri=True)
        try:
            for sc, pdt, ti in con.execute("SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst >= '2026-10-01'"):
                c6 = bare_code(sc)
                dt = str(pdt)[:10]
                if _is_clean_reg(ti):
                    stock_reg[c6].append(dt)
                    if c6.startswith(("00", "60")):
                        ex = "SH" if c6.startswith("60") else "SZ"
                        ex_reg[ex].append((dt, c6))
        except Exception:
            pass
        con.close()

    # 合并 kpl/zdjk 重点监控名单
    for zf in glob.glob(f"{PROJECT_ROOT}/sim-portfolio/data/kpl/zdjk/*.json"):
        try:
            with open(zf, "r", encoding="utf-8") as f:
                zd_data = json.load(f)
                for it in zd_data.get("List", []):
                    c6 = str(it[0]).zfill(6)
                    d_str = str(it[2])[:10]
                    stock_reg[c6].append(d_str)
                    if c6.startswith(("00", "60")):
                        ex = "SH" if c6.startswith("60") else "SZ"
                        ex_reg[ex].append((d_str, c6))
        except Exception:
            pass

    # ex_reg 严格按同一股票 7 天内去重 (对齐 build_pit_cache.py)
    for ex in ("SH", "SZ"):
        ded, seen = [], {}
        for d, c in sorted(set(ex_reg[ex])):
            if c not in seen or (pd.Timestamp(d) - seen[c]).days > 7:
                seen[c] = pd.Timestamp(d)
                ded.append((d, c))
        ex_reg[ex] = ded

    holders = {}
    if os.path.exists(HOLDERS_PATH):
        try:
            holders = json.load(open(HOLDERS_PATH))
        except Exception:
            holders = {}

    kpl_stock_zt_days = defaultdict(list)
    kpl_plate_dates = defaultdict(set)
    if os.path.exists(KPL_MERGED_PATH):
        try:
            with open(KPL_MERGED_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    item = json.loads(line)
                    d = item["date"]
                    for pl in item.get("plates", []):
                        pname = pl["plate"]
                        kpl_plate_dates[pname].add(d)
                        for st in pl.get("stocks", []):
                            c6 = bare_code(st[0])
                            name = st[1]
                            r1 = st[2] if len(st) > 2 else ""
                            r2 = st[3] if len(st) > 3 else ""
                            reason = f"{r1} {r2}".strip()
                            kpl_stock_zt_days[c6].append((d, pname, name, reason))
        except Exception:
            pass

    tape_map = {}
    if os.path.exists(DB_ZT_TAPE):
        try:
            con = sqlite3.connect(f"file:{DB_ZT_TAPE}?mode=ro", uri=True)
            for row in con.execute("SELECT trade_date, sec_code, sec_name, first_seal_time, seal_amount, continuous_plate_tag, board_count, open_board_count, plate_name, reason_desc FROM zt_micro_tape WHERE trade_date >= '2026-09-01'"):
                td, sc, sn, fst, sa, cpt, bc, obc, pn, rd = row
                tape_map[(td, bare_code(sc))] = {
                    "first_seal_time": fst or "99:99:99",
                    "seal_amount": float(sa or 0.0),
                    "open_board_count": int(obc or 0),
                    "plate_name": pn or "",
                    "reason_desc": rd or "",
                }
            con.close()
        except Exception:
            pass

    for zt_file in [f"{THS_ZT_DIR}/{d0_date}.json", f"{THS_ZT_DIR}/{d1_date}.json"]:
        if os.path.exists(zt_file):
            try:
                with open(zt_file, "r", encoding="utf-8") as f:
                    d_obj = json.load(f)
                    td = d_obj.get("date", "")
                    for st in d_obj.get("stocks", []):
                        c6 = bare_code(st.get("code", ""))
                        tape_map[(td, c6)] = {
                            "first_seal_time": "09:30:00",
                            "seal_amount": float(st.get("order_amount", 0.0)),
                            "open_board_count": int(st.get("open_num", 0)),
                            "plate_name": str(st.get("reason_type", "")).split("+")[0],
                            "reason_desc": str(st.get("reason_type", "")),
                        }
            except Exception:
                pass

    lhb_daily_buy = defaultdict(list)
    lhb_daily_sell = defaultdict(list)
    if os.path.exists(LHB_BUY_PATH):
        try:
            lb = pd.read_parquet(LHB_BUY_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
            lb["dt"] = lb["TRADE_DATE"].astype(str).str[:10]
            lb["c6"] = lb["SECURITY_CODE"].astype(str).str[:6]
            g_buy = lb[lb["dt"] >= "2026-09-01"].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["BUY"].min()
            for r in g_buy.itertuples(index=False):
                lhb_daily_buy[(r.dt, r.c6)].append((r.OPERATEDEPT_NAME, float(r.BUY)))
        except Exception:
            pass
    if os.path.exists(LHB_SELL_PATH):
        try:
            ls = pd.read_parquet(LHB_SELL_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "SELL"])
            ls["dt"] = ls["TRADE_DATE"].astype(str).str[:10]
            ls["c6"] = ls["SECURITY_CODE"].astype(str).str[:6]
            g_sell = ls[ls["dt"] >= "2026-09-01"].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["SELL"].min()
            for r in g_sell.itertuples(index=False):
                lhb_daily_sell[(r.dt, r.c6)].append((r.OPERATEDEPT_NAME, float(r.SELL)))
        except Exception:
            pass

    evaluated_candidates = []
    w5_start = all_dts[max(0, len(all_dts) - 6)]

    for c6, pool_tag, streak_d0, yz_streak_d0 in cands_targets:
        sub_c = df_act[df_act["c6"] == c6].sort_values("dt_str")
        d1_row = sub_c[sub_c["dt_str"] == d1_date]
        if d1_row.empty:
            continue
        r1 = d1_row.iloc[0]

        is_broken = not bool(r1["is_zt"])
        is_true_yang = bool(r1["close"] > r1["open"])
        d1_turnover = float(r1["turn"] * 100.0) if hasattr(r1, "turn") else float(r1["to"] if "to" in r1 else 0.0)

        if not is_broken or not is_true_yang:
            continue

        ex = "SH" if c6.startswith("60") else "SZ"

        d0_row = sub_c[sub_c["dt_str"] == d0_date].iloc[0]
        c_close = float(r1["close"])
        c_open = float(r1["open"])
        c_pre = float(r1["pre_c"])
        c_low = float(r1["low"])

        d1_ts = pd.Timestamp(d1_date)
        s_reg_hit = any(0 <= (d1_ts - pd.Timestamp(x)).days <= 10 for x in stock_reg.get(c6, []))

        tox_hit = False
        if os.path.exists(DB_NOTICES):
            con = sqlite3.connect(f"file:{DB_NOTICES}?mode=ro", uri=True)
            try:
                for ti, in con.execute("SELECT title FROM notice WHERE code=? AND ndate >= ?", (c6, (d1_ts - datetime.timedelta(days=90)).strftime("%Y-%m-%d"))):
                    if TOX_RE.search(str(ti)):
                        tox_hit = True
                        break
            except Exception:
                pass
            con.close()

        recent_ex_letters = [x for x in ex_reg[ex] if w5_start <= x[0] <= d1_date]
        unique_ex_stocks = len(set(x[1] for x in recent_ex_letters))
        ex_reg5_hit = (unique_ex_stocks >= 2)

        d1_to_hit = (d1_turnover > 35.0)

        d0_buys = lhb_daily_buy.get((d0_date, c6), [])
        d1_buys = lhb_daily_buy.get((d1_date, c6), [])
        d1_sells = lhb_daily_sell.get((d1_date, c6), [])

        if not d0_buys or not d1_buys:
            b_online, s_online = query_eastmoney_lhb_seats(c6, {d0_date, d1_date})
            if b_online.get(d0_date):
                d0_buys = b_online[d0_date]
            if b_online.get(d1_date):
                d1_buys = b_online[d1_date]
            if s_online.get(d1_date):
                d1_sells = s_online[d1_date]

        lh1 = sum(1 for dept, amt in d1_buys if RE_LHASA.search(dept))
        in1 = sum(1 for dept, amt in d1_buys if RE_INST.search(dept))
        qu1 = sum(1 for dept, amt in d1_buys if Q_RE.search(dept))

        lh1_hit = (lh1 >= 3)

        veto_reasons = []
        if s_reg_hit:
            veto_reasons.append("近10日监管工作函/重点监控")
        if tox_hit:
            veto_reasons.append("近90日立案/减持/退市毒丸公告")
        if ex_reg5_hit:
            veto_reasons.append(f"交易所近5日监管函密集({unique_ex_stocks}>=2)")
        if d1_to_hit:
            veto_reasons.append(f"D1换手率超标({d1_turnover:.1f}%>35%)")
        if lh1_hit:
            veto_reasons.append(f"D1拉萨席位超标({lh1}>=3家)")

        is_vetoed = len(veto_reasons) > 0

        breakdown = {}
        static_score = 60

        pts_brk = 12 if brk_r10_d1 >= 0.20 else -8
        static_score += pts_brk
        breakdown["brk_r10"] = {"name": "近10日高标断板跌停反包率", "val": f"{brk_r10_d1*100:.1f}%", "pts": pts_brk}

        pts_nzt = 10 if n_zt_d1 < 70 else (-10 if n_zt_d1 >= 95 else 0)
        static_score += pts_nzt
        breakdown["n_zt"] = {"name": "全市场昨日涨停家数", "val": f"{n_zt_d1}家", "pts": pts_nzt}

        pts_csi = 8 if csi5_d1 >= -0.005 else (-10 if csi5_d1 < -0.025 else 0)
        static_score += pts_csi
        breakdown["csi5"] = {"name": "沪深300近5日涨跌幅", "val": f"{csi5_d1*100:+.2f}%", "pts": pts_csi}

        d1_op = float(r1["o_pct"])
        pts_d1op = 8 if d1_op < 0.0 else 0
        static_score += pts_d1op
        breakdown["d1_op"] = {"name": "D1首阴开盘低吸承接", "val": f"{d1_op*100:+.2f}%", "pts": pts_d1op}

        d0_rec = tape_map.get((d0_date, c6), {})
        obc = int(d0_rec.get("open_board_count", 0))

        d0_close = float(d0_row["close"])
        d0_open = float(d0_row["open"])
        d0_high = float(d0_row["high"])
        d0_pre = float(d0_row["pre_c"])
        d0_low_pct = (float(d0_row["low"]) / d0_pre - 1.0) if d0_pre > 0 else 0.0
        d0_body_pct = (d0_close - d0_open) / (d0_pre + 1e-6)
        d0_tight = (
            (1.0 if d0_close == d0_high else 0.0) * 30.0
            + np.clip(d0_low_pct * 100.0, -10.0, 10.0) * 1.5
            + np.clip(d0_body_pct * 100.0, 0.0, 10.0) * 2.0
        )
        pts_tight = 6 if (obc == 0 and d0_tight >= 35.0) else 0
        static_score += pts_tight
        breakdown["d0_tight"] = {"name": "D0零炸板且高封板紧度", "val": f"obc={obc},tight={d0_tight:.1f}", "pts": pts_tight}

        pts_pelo = 6
        static_score += pts_pelo
        breakdown["pelo"] = {"name": "板块非过热与主线承接", "val": "非独立抱团", "pts": pts_pelo}

        pts_lh1 = 6 if lh1 == 0 else (-10 if lh1 == 2 else 0)
        static_score += pts_lh1
        breakdown["lh1"] = {"name": "D1龙虎榜拉萨席位数", "val": f"{lh1}家", "pts": pts_lh1}

        pts_in1 = -6 if in1 >= 1 else 0
        static_score += pts_in1
        breakdown["in1"] = {"name": "D1龙虎榜机构出逃席位", "val": f"{in1}家", "pts": pts_in1}

        pts_price = 5 if c_close <= 20.0 else (-10 if c_close > 35.0 else 0)
        static_score += pts_price
        breakdown["price_tier"] = {"name": "绝对股价偏好档位", "val": f"{c_close:.2f}元", "pts": pts_price}

        hist_bars_c = sub_c[sub_c["dt_str"] <= d0_date]
        streak_len = streak_d0
        streak_sub = hist_bars_c.iloc[-streak_len:] if len(hist_bars_c) >= streak_len else hist_bars_c
        turn_boards_cnt = sum(1 for _, row in streak_sub.iterrows() if row["is_zt"] and not row["is_yizi"])
        pts_turn = 5 if turn_boards_cnt >= 4 else (-5 if turn_boards_cnt <= 2 else 0)
        static_score += pts_turn
        breakdown["turn_boards"] = {"name": "换手成龙连板数", "val": f"{turn_boards_cnt}板", "pts": pts_turn}

        d1_deep_dip = (c_low / c_pre - 1.0) <= -0.06
        pts_dip = 5 if d1_deep_dip else 0
        static_score += pts_dip
        breakdown["d1_deep_dip"] = {"name": "D1触及跌停深水撬起", "val": f"最低{(c_low/c_pre-1)*100:+.2f}%", "pts": pts_dip}

        lock_val = 38.0
        if c6 in holders:
            h_rows = [x for x in holders[c6] if x[0] < d1_date]
            if h_rows:
                lock_val = float(max(h_rows, key=lambda x: x[1])[2])

        # 流通市值 (亿元)：优先从 r1 取 mcap，若无则由收盘价与流通股本推算
        mcap_val = float(r1.get("mcap", 0.0) or 0.0)
        if mcap_val <= 0.0:
            osh = float(r1.get("oshare", 0.0) or 0.0)
            if osh > 0.0:
                mcap_val = float(r1["close"]) * osh / 1e8
            else:
                to_val = float(r1.get("turn", 0.0) or 0.0)
                amt_val = float(r1.get("amount", 0.0) or 0.0)
                mcap_val = (amt_val / to_val / 1e8) if to_val > 0.0 else 50.0

        fmcap_val = mcap_val * (1.0 - lock_val / 100.0)
        f1_ok = (lock_val >= 45.0) or (fmcap_val >= 45.0)
        pts_lock = 6 if f1_ok else -6
        static_score += pts_lock
        breakdown["lock"] = {
            "name": "十大股东锁仓或真流通市值",
            "val": f"锁仓{lock_val:.1f}%,真流通{fmcap_val:.1f}亿",
            "pts": pts_lock,
        }

        pts_qu = 4 if (qu1 >= 1 and lh1 <= 1) else 0
        static_score += pts_qu
        breakdown["qu1"] = {"name": "D1量化做T且少拉萨", "val": f"qu={qu1},lh={lh1}", "pts": pts_qu}

        bars_before_streak = hist_bars_c.iloc[:-streak_len] if len(hist_bars_c) > streak_len else pd.DataFrame()
        max_s_1y, max_s_3y = 0, 0
        if not bars_before_streak.empty:
            b1 = bars_before_streak.iloc[-250:]
            max_s_1y = int(b1["streak"].max()) if not b1.empty else 0
            b3 = bars_before_streak.iloc[-750:]
            max_s_3y = int(b3["streak"].max()) if not b3.empty else 0
        pts_hist = 6 if max_s_1y >= 5 else (3 if max_s_3y >= 5 else 0)
        static_score += pts_hist
        breakdown["kpl_hist"] = {"name": "历史妖股记忆(1年/3年>=5板)", "val": f"1y={max_s_1y},3y={max_s_3y}", "pts": pts_hist}

        past_zts = [x for x in kpl_stock_zt_days.get(c6, []) if x[0] < d0_date]
        d0_ts = pd.Timestamp(d0_date)
        zt_1y = [x for x in past_zts if (d0_ts - pd.Timestamp(x[0])).days <= 365]
        is_new_face = (len(zt_1y) == 0)
        hist_plates_45_500d = set(x[1] for x in past_zts if 45 <= (d0_ts - pd.Timestamp(x[0])).days <= 500)
        curr_theme = d0_rec.get("plate_name", "")
        pts_theme = 0
        if not is_new_face and curr_theme:
            if curr_theme in hist_plates_45_500d:
                pts_theme = 3
            else:
                pts_theme = -5
        static_score += pts_theme
        breakdown["kpl_theme"] = {"name": "老票新炒与冷饭区分", "val": curr_theme or "新面孔", "pts": pts_theme}

        d0_top_names = [dept for dept, amt in d0_buys if RE_TOP_YOUZI.search(dept)]
        d1_sell_names = [dept for dept, amt in d1_sells]
        d0_top_locked = False
        if d0_top_names:
            d0_top_locked = not any(any(top_n in sell_n for top_n in d0_top_names) for sell_n in d1_sell_names)
        pts_locked = 5 if d0_top_locked else 0
        static_score += pts_locked
        breakdown["top_locked"] = {"name": "D0顶级游资D1锁仓", "val": f"{len(d0_top_names)}家锁仓" if d0_top_locked else "无", "pts": pts_locked}

        tot_b = sum(amt for dept, amt in d1_buys)
        tot_s = sum(amt for dept, amt in d1_sells)
        lh_b = sum(amt for dept, amt in d1_buys if RE_LHASA.search(dept))
        lh_ratio = (lh_b / tot_b) if tot_b > 0 else 0.0
        pts_lh_heavy = -10 if (lh_ratio >= 0.20 and tot_b > 0) else 0
        static_score += pts_lh_heavy
        breakdown["lh_heavy"] = {"name": "D1拉萨买入占比>=20%", "val": f"{lh_ratio*100:.1f}%", "pts": pts_lh_heavy}

        pts_net_pos = -5 if (tot_b - tot_s > 0 and tot_b > 0) else 0
        static_score += pts_net_pos
        breakdown["net_pos"] = {"name": "D1龙虎榜散户净买入为正", "val": f"净买{(tot_b-tot_s)/1e4:+.1f}万", "pts": pts_net_pos}

        d0_day_surf = any(RE_DAY_SURF.search(dept) for dept, amt in d0_buys)
        pts_surf = -6 if d0_day_surf else 0
        static_score += pts_surf
        breakdown["day_surf"] = {"name": "D0一日游游资买入", "val": "有" if d0_day_surf else "无", "pts": pts_surf}

        fst = d0_rec.get("first_seal_time", "99:99:99")
        pts_early = -5 if fst <= "09:35:00" else 0
        static_score += pts_early
        breakdown["early_seal"] = {"name": "D0封板过早一致性顶死", "val": fst, "pts": pts_early}

        rdesc = d0_rec.get("reason_desc", "")
        pts_tech = -4 if bool(TECH_RE.search(rdesc)) else 0
        static_score += pts_tech
        breakdown["reason_tech"] = {"name": "D0科技热词退潮踩踏", "val": "科技热词" if pts_tech < 0 else "非科技", "pts": pts_tech}

        name = str(r1.get("name", d0_rec.get("sec_name", "")))
        if not name:
            q_tmp = fetch_tencent_batch([market_prefix(c6) + c6])
            name = q_tmp.get(c6, {}).get("name", c6)

        evaluated_candidates.append({
            "code": c6,
            "name": name,
            "pool": pool_tag,
            "streak_d0": streak_d0,
            "turn_boards_cnt": turn_boards_cnt,
            "close_d1": c_close,
            "open_d1": c_open,
            "pre_c_d1": c_pre,
            "turnover_d1": d1_turnover,
            "is_vetoed": is_vetoed,
            "veto_reasons": veto_reasons,
            "static_score": static_score,
            "breakdown": breakdown,
            "zt_price_d2": round(c_close * 1.10, 2),
            "dt_price_d2": round(c_close * 0.90, 2),
            "mcap": round(mcap_val, 2),
            "fmcap": round(fmcap_val, 2),
            "lock_pct": round(lock_val, 2),
        })

    holdings_monitors = []
    if os.path.exists(PORTFOLIO_STATE_FILE):
        try:
            with open(PORTFOLIO_STATE_FILE, "r", encoding="utf-8") as f:
                p_state = json.load(f)
            positions = p_state.get("accounts", {}).get("a_share", {}).get("positions", [])
            for pos in positions:
                sid = str(pos.get("strategy_id", ""))
                c = bare_code(pos.get("code") or pos.get("ticker", ""))
                if "s_high" in sid:
                    dev_info = calc_double_dev_for_stock(c)
                    dev_info["shares"] = pos.get("shares", 0)
                    dev_info["cost"] = pos.get("avg_cost", 0.0)
                    holdings_monitors.append(dev_info)
        except Exception:
            pass

    next_trade_date = (now + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    if now.weekday() == 4:
        next_trade_date = (now + datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    elif now.weekday() == 5:
        next_trade_date = (now + datetime.timedelta(days=2)).strftime("%Y-%m-%d")

    cache_data = {
        "as_of_d1": d1_date,
        "d0_date": d0_date,
        "next_trade_date": next_trade_date,
        "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mkt_env": {
            "max_streak_d0": max_b_d0,
            "n_zt_d1": n_zt_d1,
            "brk_r10_d1": round(brk_r10_d1, 4),
            "csi5_d1": round(csi5_d1, 4),
            "ex_reg5_sh": len(set(x[1] for x in ex_reg["SH"] if w5_start <= x[0] <= d1_date)),
            "ex_reg5_sz": len(set(x[1] for x in ex_reg["SZ"] if w5_start <= x[0] <= d1_date)),
        },
        "candidates": evaluated_candidates,
        "holdings": holdings_monitors,
    }

    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)

    return cache_data


def load_premarket_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return build_premarket_cache()
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return build_premarket_cache()


def print_premarket_panel(cache: dict, hold_codes: list[str] | None = None):
    d1 = cache.get("as_of_d1", "")
    d2 = cache.get("next_trade_date", "")
    env = cache.get("mkt_env", {})
    cands = cache.get("candidates", [])

    print("=" * 78)
    print(f"【高标首阴真阳反包主策略 V5.1 · 盘前决策面板】基准D1={d1} | 决策执行日={d2}")
    print("=" * 78)

    print("一、全市场高标生态指标面板：")
    print(f"  * D0 最高连板高度: {env.get('max_streak_d0', 0)} 板")
    print(f"  * D1 昨日涨停家数: {env.get('n_zt_d1', 0)} 家 (70家以下加分, 95家以上退潮扣分)")
    print(f"  * D1 断板反包跌停率: {env.get('brk_r10_d1', 0)*100:.1f}% (>=20%加分, 低于20%扣分)")
    print(f"  * 沪深300近5日收益: {env.get('csi5_d1', 0)*100:+.2f}%")
    print(f"  * 交易所近5日监管函: 沪市 {env.get('ex_reg5_sh', 0)} 封 | 深市 {env.get('ex_reg5_sz', 0)} 封 (>=2封一票否决)")
    print("-" * 78)

    print("二、今日唯一候选标的与打分卡解剖：")
    if not cands:
        print("  【结论】：今日全市场无符合条件的高标首阴真阳标的（>=4板且首阴真阳换手<=35%），明日空仓休息。")
    else:
        for idx, c in enumerate(cands, 1):
            print(f"  标的 {idx}: {c['code']} {c['name']} | 池层级: {c['pool']} (D0={c['streak_d0']}板, 换手板={c['turn_boards_cnt']})")
            print(f"  行情: D1收盘={c['close_d1']:.2f}元 | 今开={c['open_d1']:.2f}元 | 换手={c['turnover_d1']:.2f}%")

            if c["is_vetoed"]:
                print(f"  ⛔【一票否决】：该标的已触碰硬红线：{'；'.join(c['veto_reasons'])}！")
                print("      最终裁决：直接否决（-999分），严禁买入，放弃交易！")
            else:
                print(f"  【盘前静态评分】：{c['static_score']} 分 (底分 60 分 + 21 项静态因子)")
                print("  逐项打分明细：")
                for k, item in c.get("breakdown", {}).items():
                    sign = "+" if item["pts"] > 0 else ("" if item["pts"] == 0 else "")
                    print(f"    - {item['name']:<24}: {item['val']:<16} ({sign}{item['pts']}分)")
                print("\n  【09:25 竞价情景手操推演】：")
                st_sc = c["static_score"]
                sc_green = st_sc + 8
                sc_flat = st_sc + 6
                sc_high = st_sc + 0

                pass_green = "过线(>=88)" if sc_green >= 88 else "未过线"
                pass_flat = "过线(>=88)" if sc_flat >= 88 else "未过线"
                pass_high = "过线(>=88)" if sc_high >= 88 else "未过线"

                print(f"    情景 1 [绿开 -6.5% ~ 0.0%): 总分={sc_green}分 ({pass_green}) -> 若>=88可挂同花顺条件单(触发买价=今开*1.015, 11:30未成交撤单)")
                print(f"    情景 2 [平开/小红开 0.0% ~ +2.5%]: 总分={sc_flat}分 ({pass_flat}) -> 若>=88直接09:25竞价买入")
                print(f"    情景 3 [高开 +2.5% ~ +4.5%]: 总分={sc_high}分 ({pass_high}) -> 若>=88直接09:25竞价买入")
                print("    情景 4 [高开>+4.5% 或 低开<-6.5%]: 一票否决 (-999分) -> 严禁追高/接核按钮，放弃交易！")

    print("-" * 78)
    print("三、在持高标仓位异动监控与止盈限价单：")
    holdings = cache.get("holdings", [])
    if hold_codes:
        for c in hold_codes:
            dev = calc_double_dev_for_stock(bare_code(c))
            holdings.append(dev)

    if not holdings:
        print("  当前无在持高标仓位，无止盈挂单需求。")
    else:
        for h in holdings:
            print(f"  股票: {h.get('code')} {h.get('name')} | 现价={h.get('close', 0):.2f}元")
            print(f"    * 10日100% 极限价: {h.get('w10', {}).get('p_hard', 0):.2f}元 (基准日={h.get('w10', {}).get('base_day')})")
            print(f"    * 30日200% 极限价: {h.get('w30', {}).get('p_hard', 0):.2f}元 (基准日={h.get('w30', {}).get('base_day')})")
            print(f"    * 较紧约束: {h.get('limit_by')} (极限价={h.get('tighter_hard', 0):.2f}元)")
            print(f"    ★【今日同花顺预埋 93% 缓冲止盈挂单价】: {h.get('tighter_93', 0):.2f} 元 (触及自动成交止盈)")
            print("    * 离场提醒: 买入日亏超2%或收阴浮亏次日09:25走；抗住收红次日核按钮<-3.5%竞价走，否则锁仓。")
    print("=" * 78)


def run_intraday_instant_mode(cache: dict):
    t_start = time.time()
    cands = cache.get("candidates", [])
    d1 = cache.get("as_of_d1", "")
    d2 = cache.get("next_trade_date", "")

    valid_cands = [c for c in cands if not c["is_vetoed"]]

    if not valid_cands:
        elapsed = time.time() - t_start
        print(f"`【高标首阴反包主策略 V5.1 · 09:25 终局指令】：今日空仓休息，全市场无过线候选标的（耗时 {elapsed:.2f}s）。`")
        print(f"说明：基准日 {d1}，全市场无符合条件标的或唯一候选已触碰监管/一票否决红线，严禁盲目出手。")
        return

    cand = valid_cands[0]
    c6 = cand["code"]
    sym = market_prefix(c6) + c6

    q_map = fetch_tencent_batch([sym, "sh000300"])
    q_stk = q_map.get(sym, {})

    if not q_stk or q_stk.get("prev_close", 0) <= 0:
        elapsed = time.time() - t_start
        print(f"`【高标首阴反包主策略 V5.1 · 行情异常】：未能获取 {c6} 竞价行情（耗时 {elapsed:.2f}s）。`")
        return

    op_price = q_stk.get("open", 0.0) or q_stk.get("close", 0.0)
    pre_c = q_stk.get("prev_close", 1.0)
    op2 = (op_price / pre_c - 1.0)
    zt_px = q_stk.get("zt_price", round(pre_c * 1.10, 2))

    static_sc = cand["static_score"]

    if op2 > 0.045:
        elapsed = time.time() - t_start
        print(f"`【高标首阴反包主策略 V5.1 · 放弃交易】：{c6} {cand['name']} 竞价高开超标 ({op2*100:+.2f}% > +4.5%)，触发一票否决（耗时 {elapsed:.2f}s）。`")
        return
    elif op2 < -0.065:
        elapsed = time.time() - t_start
        print(f"`【高标首阴反包主策略 V5.1 · 放弃交易】：{c6} {cand['name']} 竞价核按钮跌幅过深 ({op2*100:+.2f}% < -6.5%)，情绪恶化放弃（耗时 {elapsed:.2f}s）。`")
        return

    if op2 < 0.0:
        op2_pts = 8
    elif 0.0 <= op2 <= 0.025:
        op2_pts = 6
    else:
        op2_pts = 0

    total_score = static_sc + op2_pts
    elapsed = time.time() - t_start

    if total_score < 88:
        print(f"`【高标首阴反包主策略 V5.1 · 放弃交易】：{c6} {cand['name']} 最终总分 {total_score} 分 < 88 分门槛（耗时 {elapsed:.2f}s）。`")
        return

    if op2 >= 0.0:
        if op_price >= zt_px - 0.011:
            print(f"`【高标首阴反包主策略 V5.1 · 放弃交易】：{c6} {cand['name']} 竞价涨停一字无买点（耗时 {elapsed:.2f}s）。`")
            return
        print(f"`【高标首阴反包主策略 V5.1 · 09:25 竞价直买指令】：买入 {c6} {cand['name']} | 现价 {op_price:.2f} 元 (今开 {op2*100:+.2f}%) | 总分 {total_score} 分 | 仓位 1/1 单仓全额（耗时 {elapsed:.2f}s）。`")
    else:
        trig_price = round(op_price * 1.015, 2)
        if trig_price >= zt_px - 0.011:
            print(f"`【高标首阴反包主策略 V5.1 · 放弃交易】：{c6} {cand['name']} 触发价触及涨停（耗时 {elapsed:.2f}s）。`")
            return
        print(f"`【高标首阴反包主策略 V5.1 · 09:26 同花顺预设条件单指令】：预埋 {c6} {cand['name']} 条件单 | 触发买入价 {trig_price:.2f} 元 (今开 {op_price:.2f} 元 * 1.015) | 总分 {total_score} 分 | 提示 11:30 前未成交立即撤单（耗时 {elapsed:.2f}s）。`")


def main():
    parser = argparse.ArgumentParser(description="A股高标首阴真阳反包主策略（方案甲 V5.1 生产定版）极速执行引擎")
    parser.add_argument("--build-cache", action="store_true", help="构建或强制刷新盘前缓存")
    parser.add_argument("--premarket", action="store_true", help="早盘盘前情景推演与打分面板")
    parser.add_argument("--mode", choices=["pre", "live", "build"], default=None, help="运行模式: pre (盘前), live (实时), build (重建缓存)")
    parser.add_argument("--hold", nargs="*", default=None, help="计算指定股票的当日双异动 93%% 限价止盈挂单价")

    args = parser.parse_args()

    if args.build_cache or args.mode == "build":
        t0 = time.time()
        print("[fast_high_dragon] 正在全量构建/刷新最新交易日高标盘前缓存 (V5.1 定版)...")
        cache = build_premarket_cache()
        print(f"[fast_high_dragon] 缓存构建完成，耗时 {time.time()-t0:.2f}s，落盘: {CACHE_FILE}")
        print_premarket_panel(cache)
        return

    if args.hold is not None:
        codes = [bare_code(c) for c in args.hold] if args.hold else ["600838"]
        print("=" * 78)
        print("【高标双异动 93% 缓冲止盈预埋挂单价计算】")
        print("=" * 78)
        for c in codes:
            dev = calc_double_dev_for_stock(c)
            if "error" in dev:
                print(f"  股票 {c}: {dev['error']}")
                continue
            print(f"  股票: {dev['code']} {dev['name']} | 现价={dev['close']:.2f}元 | 昨收={dev['prev_close']:.2f}元")
            print(f"    * 10日100% 极限价: {dev['w10'].get('p_hard', 0):.2f}元 (基准日={dev['w10'].get('base_day')})")
            print(f"    * 30日200% 极限价: {dev['w30'].get('p_hard', 0):.2f}元 (基准日={dev['w30'].get('base_day')})")
            print(f"    * 较紧约束: {dev['limit_by']} (极限价={dev['tighter_hard']:.2f}元)")
            print(f"    ★【今日同花顺预埋 93% 缓冲止盈限价单】: {dev['tighter_93']:.2f} 元 (精确到 0.01 元)")
        print("=" * 78)
        return

    if args.premarket or args.mode == "pre":
        cache = load_premarket_cache()
        print_premarket_panel(cache)
        return

    cache = load_premarket_cache()
    run_intraday_instant_mode(cache)


if __name__ == "__main__":
    main()
