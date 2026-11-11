
def _fetch_today_plates_fallback(latest_dt: str) -> list:
    d1_ymd = latest_dt.replace('-', '')
    url = (
        'https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&'
        'field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004&'
        f'filter=HS,GEM2STAR&order_field=330324&order_type=0&date={d1_ymd}'
    )
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    info_list = []
    try:
        raw = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
        d = json.loads(raw)
        info_list = d.get('data', {}).get('info', [])
    except Exception as e:
        pass

    norm_rules = [
        (re.compile(r'(人形机器人|机器人|具身智能|灵巧手)'), '机器人概念'),
        (re.compile(r'(商业航天|卫星|航天|太空)'), '商业航天'),
        (re.compile(r'(AI漫剧|AI短剧|短剧|短剧出海|短剧互动)'), '短剧游戏'),
        (re.compile(r'(AI眼镜|端侧AI|AI应用|AI营销|人工智能|大模型)'), '人工智能'),
        (re.compile(r'(PCB|覆铜板|高频高速)'), 'PCB概念'),
        (re.compile(r'(光伏|TOPCon|HJT|钙钛矿)'), '光伏'),
        (re.compile(r'(低空经济|eVTOL|无人机|飞行汽车)'), '低空经济'),
        (re.compile(r'(重组|控制权变更|股权转让|资产注入|收购)'), '并购重组'),
        (re.compile(r'(芯片|半导体|光刻|存储芯片|先进封装)'), '芯片'),
        (re.compile(r'(算力|CPO|液冷|光模块)'), '算力'),
        (re.compile(r'(消费电子|智能穿戴|苹果概念)'), '消费电子'),
        (re.compile(r'(汽车零部件|电子皮肤|汽车电子|减速器)'), '汽车零部件'),
        (re.compile(r'(锂电|固态电池|动力电池|钠电池)'), '锂电池'),
        (re.compile(r'(天然气|燃气|油气)'), '天然气'),
        (re.compile(r'(煤炭|焦煤)'), '煤炭'),
        (re.compile(r'(农业|种植|粮食|种业)'), '农业'),
    ]

    plate_dict = defaultdict(list)
    for item in info_list:
        c6 = str(item.get('code', '')).strip()[:6]
        name = str(item.get('name', '')).strip()
        r_type = str(item.get('reason_type', '')).strip()
        if not c6 or not name:
            continue
        assigned = False
        for pat, norm_name in norm_rules:
            if pat.search(r_type) or pat.search(name):
                plate_dict[norm_name].append([c6, name, norm_name, r_type])
                assigned = True
                break
        if not assigned:
            parts = [p.strip() for p in re.split(r'[+、,，/]', r_type) if p.strip()]
            first_p = parts[0] if parts else '其他'
            if first_p in NON_THEME or '增长' in first_p or '扭亏' in first_p:
                first_p = parts[1] if len(parts) > 1 else '其他'
            plate_dict[first_p].append([c6, name, first_p, r_type])

    out_plates = [{'plate': k, 'stocks': v} for k, v in plate_dict.items()]
    out_plates.sort(key=lambda x: len(x['stocks']), reverse=True)
    return out_plates

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_1to2_today.py — 「一进二定式 M2」盘后/盘前预缓存与盘中 1 秒极速裁决引擎
用法：
  1. /opt/homebrew/bin/python3.13 scripts/fast_1to2_today.py --sync-all
     依次同步近期东财公告库 (notices.db)、15:15后同步开盘啦涨停题材库 (kpl_plates_v2.jsonl)、
     刷新雪球社区新概念库 (astock_concepts.json)，最后构建 1to2_premarket_cache.json。
  2. /opt/homebrew/bin/python3.13 scripts/fast_1to2_today.py --build-cache
     读取 5 大底座（若 15:05 后 parquet 尚未含今日日线，自动并发拉腾讯实时收盘快照无缝补齐今日日线），
     计算全市场题材 Elo 与先验分 s_prior、换手首板静态筹码底分 s_q_base 与硬门槛 gate_ok，落盘缓存。
  3. /opt/homebrew/bin/python3.13 scripts/fast_1to2_today.py --premarket
     09:00 / 09:15 前秒读缓存，输出今日题材热度 Top 10 与过门槛候选股盘前预评分排行及 09:25 过线竞价条件。
  4. /opt/homebrew/bin/python3.13 scripts/fast_1to2_today.py
     09:25:03 及盘中极速模式（< 1.5s），秒读缓存 + 拉腾讯实时竞价/盘口，输出最终总分与点火触发买价。

⛔ 铁律：严禁 import yfinance (D12)；纯只读与缓存生成，严禁触碰 portfolio_state.json 或执行任何交易。
"""
import os
import sys
import re
import json
import time
import sqlite3
import datetime
import argparse
import subprocess
import urllib.request
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT_DIR = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT_DIR}/sim-portfolio"
ND_DIR = f"{ROOT_DIR}/news-dashboard"

PARQUET_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_daily.parquet"
UNIVERSE_PATH = f"{SIM_DIR}/data/cn_hk_price_db/universe_codes.json"
KPL_PATH = f"{ND_DIR}/output/kpl_plates_v2.jsonl"
VOCAB_PATH = f"{ND_DIR}/output/astock_concept_vocab.json"
CONCEPTS_PATH = f"{ND_DIR}/output/astock_concepts.json"
PRIORITY_TERMS_PATH = f"{SIM_DIR}/data/1to2_priority_terms.json"
NOTICES_DB_PATH = f"{SIM_DIR}/backtest/2026-08-24-daban/notices.db"
CACHE_PATH = f"{SIM_DIR}/data/1to2_premarket_cache.json"
SYNC_NOTICES_SCRIPT = f"{SIM_DIR}/scripts/sync_notices_db.py"

sys.path.insert(0, ND_DIR)
try:
    from astock_concept_vocab import split_terms
except Exception:
    def split_terms(s):
        out = set()
        for part in re.split(r"[+、,，/；;]", s or ""):
            part = part.strip()
            if not part:
                continue
            out.add(part)
            for x in re.split(r"[()（）]", part):
                x = x.strip()
                if x:
                    out.add(x)
        return {t for t in out if 2 <= len(t) <= 20}

NON_THEME = {"其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长", "年报增长", "一季报增长", "次新股"}
MA_PAT = re.compile(r"(重组|收购|股权转让|实控人变更|控制权变更|资产注入|借壳|控股|整合|中标|重大合同)")
TECH_PAT = re.compile(
    r"(AI|算力|机器人|芯片|半导体|光刻|低空|商业航天|卫星|太空|固态电池|量子|脑机|大模型|具身智能|"
    r"华为|鸿蒙|无人驾驶|智驾|游戏|影之刃|黑神话|CPO|光模块|液冷|HBM|数据要素|深海|核聚变)"
)
EARN_PAT = re.compile(r"(业绩|预增|扭亏|季报|年报|半年报|分红)")

HARD_NOTICE_PAT = re.compile(
    r"(重组|收购|股权转让|控制权|实控人变更|资产注入|借壳|重大合同|中标|战略合作|框架协议|投资设立|"
    r"算力|机器人|芯片|卫星|人工智能|固态电池|低空)"
)
MA_NOTICE_PAT = re.compile(r"(重组|收购|股权转让|控制权变更|实控人变更|资产注入|借壳|重大合同|中标)")
EARN_NOTICE_PAT = re.compile(r"(业绩预增|业绩快报|扭亏为盈|半年度业绩|年度业绩|季度业绩)")
BAD_NOTICE_PAT = re.compile(r"(减持|问询函|监管函|警示函|立案|风险提示|业绩预亏|计提资产减值|退市风险|终止上市|违规)")


def _norm_term(t: str) -> str:
    t = re.sub(r"（.*?）|\(.*?\)", "", t or "")
    return re.sub(r"[\s·\-_()（）“”\"'《》/]", "", t).lower().removesuffix("概念")


def _fetch_tencent_batch(q_codes):
    url = "http://qt.gtimg.cn/q=" + ",".join(q_codes)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    txt = urllib.request.urlopen(req, timeout=6).read().decode("gbk", errors="ignore")
    out = {}
    for ln in txt.strip().splitlines():
        if '="' not in ln:
            continue
        k, v = ln.split('="', 1)
        p = v.strip('";').split("~")
        if len(p) > 45:
            c6 = k[-6:]
            op = float(p[5] or 0)
            cur = float(p[3] or 0)
            pre = float(p[4] or 0)
            high = float(p[33] or 0)
            low = float(p[34] or 0)
            amt_yuan = float(p[37] or 0) * 10000.0
            turn_dec = float(p[38] or 0) / 100.0
            circ_mcap_yi = float(p[44] or 0)
            dt_raw = str(p[30] or "").strip()[:8]
            out[c6] = {
                "name": str(p[1] or "").strip(),
                "open": op,
                "cur": cur,
                "pre": pre,
                "high": high,
                "low": low,
                "amount": amt_yuan,
                "turn": turn_dec,
                "circ_mcap_yi": circ_mcap_yi,
                "dt_ymd": dt_raw,
                "bid1": float(p[9] or 0),
            }
    return out


def _patch_today_daily_if_needed(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """
    若当前在交易日 15:05 之后且 a_daily.parquet 尚未包含今日收盘日线，
    自动并发拉取腾讯 qt.gtimg.cn 实时收盘快照补齐沪深主板今日日线（确保 16:30 预缓存零滞后）。
    """
    now = datetime.datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    today_ymd = now.strftime("%Y%m%d")
    max_dt = str(df["date"].max())[:10]
    if max_dt >= today_str or now.weekday() >= 5 or (now.hour == 15 and now.minute < 5) or now.hour < 15:
        return df, False

    last_rows = df.groupby("ticker").tail(1)
    tk_map = {r.ticker[:6]: (r.ticker, r.oshare) for r in last_rows[["ticker", "oshare"]].itertuples(index=False)}
    all_c6 = sorted(tk_map.keys())
    batches = []
    for i in range(0, len(all_c6), 400):
        chunk = all_c6[i : i + 400]
        batches.append([("sh" + c if c.startswith("6") else "sz" + c) for c in chunk])

    live_all = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_fetch_tencent_batch, b) for b in batches]
        for fut in as_completed(futs):
            try:
                live_all.update(fut.result())
            except Exception:
                pass

    new_rows = []
    ts_today = pd.Timestamp(today_str)
    for c6, (ticker, last_oshare) in tk_map.items():
        lv = live_all.get(c6)
        if not lv or lv["dt_ymd"] != today_ymd or lv["cur"] <= 0 or lv["open"] <= 0:
            continue
        close_p = lv["cur"]
        oshare = (lv["circ_mcap_yi"] * 1e8 / close_p) if (lv["circ_mcap_yi"] > 0 and close_p > 0) else last_oshare
        new_rows.append(
            {
                "date": ts_today,
                "ticker": ticker,
                "open": lv["open"],
                "high": max(lv["high"], lv["open"], close_p),
                "low": min(lv["low"] if lv["low"] > 0 else lv["open"], lv["open"], close_p),
                "close": close_p,
                "amount": lv["amount"],
                "oshare": oshare,
                "turn": lv["turn"],
            }
        )

    if len(new_rows) < 1000:
        return df, False

    add_df = pd.DataFrame(new_rows)
    df = pd.concat([df, add_df], ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
    return df, True


def _fetch_today_plates_fallback(latest_dt: str, fb_df: pd.DataFrame = None) -> list:
    """
    当 kpl_plates_v2.jsonl 当日 plates 为空或缺失时，
    通过同花顺涨停池 API + 历史板块规范词聚合当日涨停股板块。
    """
    d1_ymd = latest_dt.replace('-', '')
    url = (
        'https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&'
        'field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004&'
        f'filter=HS,GEM2STAR&order_field=330324&order_type=0&date={d1_ymd}'
    )
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'})
    info_list = []
    try:
        raw = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
        d = json.loads(raw)
        info_list = d.get('data', {}).get('info', [])
    except Exception as e:
        print(f'[fallback] 拉取同花顺涨停池异常: {e}')

    # 标准规范题材映射规则
    norm_rules = [
        (re.compile(r'(人形机器人|机器人|具身智能|灵巧手)'), '机器人概念'),
        (re.compile(r'(商业航天|卫星|航天|太空)'), '商业航天'),
        (re.compile(r'(AI漫剧|AI短剧|短剧|短剧出海|短剧互动)'), '短剧游戏'),
        (re.compile(r'(AI眼镜|端侧AI|AI应用|AI营销|人工智能|大模型)'), '人工智能'),
        (re.compile(r'(PCB|覆铜板|高频高速)'), 'PCB概念'),
        (re.compile(r'(光伏|TOPCon|HJT|钙钛矿)'), '光伏'),
        (re.compile(r'(低空经济|eVTOL|无人机|飞行汽车)'), '低空经济'),
        (re.compile(r'(重组|控制权变更|股权转让|资产注入|收购)'), '并购重组'),
        (re.compile(r'(芯片|半导体|光刻|存储芯片|先进封装)'), '芯片'),
        (re.compile(r'(算力|CPO|液冷|光模块)'), '算力'),
        (re.compile(r'(消费电子|智能穿戴|苹果概念)'), '消费电子'),
        (re.compile(r'(汽车零部件|电子皮肤|汽车电子|减速器)'), '汽车零部件'),
        (re.compile(r'(锂电|固态电池|动力电池|钠电池)'), '锂电池'),
        (re.compile(r'(天然气|燃气|油气)'), '天然气'),
        (re.compile(r'(煤炭|焦煤)'), '煤炭'),
        (re.compile(r'(农业|种植|粮食|种业)'), '农业'),
    ]

    plate_dict = defaultdict(list)
    for item in info_list:
        c6 = str(item.get('code', '')).strip()[:6]
        name = str(item.get('name', '')).strip()
        r_type = str(item.get('reason_type', '')).strip()
        high_days = str(item.get('high_days', '')).strip()
        if not c6 or not name:
            continue

        assigned = False
        for pat, norm_name in norm_rules:
            if pat.search(r_type) or pat.search(name):
                plate_dict[norm_name].append([c6, name, norm_name, r_type])
                assigned = True
                break

        if not assigned:
            # 尝试直接使用第一个拆分词
            parts = [p.strip() for p in re.split(r'[+、,，/]', r_type) if p.strip()]
            first_p = parts[0] if parts else '其他'
            if first_p in NON_THEME or '增长' in first_p or '扭亏' in first_p:
                first_p = parts[1] if len(parts) > 1 else '其他'
            plate_dict[first_p].append([c6, name, first_p, r_type])

    out_plates = []
    for pname, st_list in plate_dict.items():
        out_plates.append({
            'plate': pname,
            'stocks': st_list
        })
    # 按股票数量排序
    out_plates.sort(key=lambda x: len(x['stocks']), reverse=True)
    return out_plates


def build_cache(verbose: bool = True) -> dict:
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "amount", "oshare", "turn"]
    df = pd.read_parquet(PARQUET_PATH, columns=cols)
    df = df[~df["ticker"].str.endswith(".BJ")].copy()
    is_10pct = ~(df["ticker"].str.startswith("30") | df["ticker"].str.startswith("68"))
    df = df[is_10pct & (df["date"] >= "2026-05-01")].sort_values(["ticker", "date"]).reset_index(drop=True)

    df, patched_today = _patch_today_daily_if_needed(df)

    g = df.groupby("ticker")
    df["pre_c"] = g["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["o_pct"] = df["open"] / df["pre_c"] - 1.0
    df["h_pct"] = df["high"] / df["pre_c"] - 1.0
    df["l_pct"] = df["low"] / df["pre_c"] - 1.0
    df["mcap"] = df["close"] * df["oshare"] / 1e8
    df["to"] = df["turn"] * 100.0
    df["zt_price"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["dt_price"] = np.floor(df["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_price"] - 0.01) & (df["pct"] >= 0.095)
    df["is_dt"] = (df["close"] <= df["dt_price"] + 0.01) & (df["pct"] <= -0.095)
    df["touch_zt"] = (df["high"] >= df["zt_price"] - 0.01) | (df["h_pct"] >= 0.098)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_price"] - 0.01) & (df["low"] >= df["zt_price"] - 0.01)
    df["c6"] = df["ticker"].str[:6]
    df["dt_str"] = df["date"].astype(str).str[:10]
    df["prev_zt"] = g["is_zt"].shift(1).fillna(False)
    df["prev2_zt"] = g["is_zt"].shift(2).fillna(False)
    df["is_1to2_day"] = df["prev_zt"] & (~df["prev2_zt"])

    # 在首板当日 D1 收盘计算静态特征（对应次日 D2 的 d0 = D1的前一日，d1 = D1首板当日）
    df["f_d0_close"] = g["close"].shift(1)
    df["f_d0_pct"] = g["pct"].shift(1)
    df["f_ret_pre10"] = df["f_d0_close"] / g["close"].shift(11) - 1.0
    df["f_max20_d0"] = g["high"].rolling(20, min_periods=10).max().reset_index(level=0, drop=True).groupby(df["ticker"]).shift(1)
    df["f_max60_d0"] = g["high"].rolling(60, min_periods=20).max().reset_index(level=0, drop=True).groupby(df["ticker"]).shift(1)
    df["f_min20_d0"] = g["low"].rolling(20, min_periods=10).min().reset_index(level=0, drop=True).groupby(df["ticker"]).shift(1)
    df["f_dd20_d0"] = df["f_d0_close"] / df["f_max20_d0"]
    df["f_dd60_d0"] = df["f_d0_close"] / df["f_max60_d0"]
    df["f_pos20_d0"] = (df["f_d0_close"] - df["f_min20_d0"]) / (df["f_max20_d0"] - df["f_min20_d0"] + 1e-6)
    df["f_vol_ma5_d0"] = g["amount"].rolling(5, min_periods=2).mean().reset_index(level=0, drop=True).groupby(df["ticker"]).shift(1)
    df["f_d1_vol_ratio"] = df["amount"] / (df["f_vol_ma5_d0"] + 1e-6)
    df["zt_int"] = df["is_zt"].astype(int)
    df["f_zt_cnt_pre20"] = g["zt_int"].rolling(20, min_periods=5).sum().reset_index(level=0, drop=True).groupby(df["ticker"]).shift(1)

    latest_dt = str(df["dt_str"].max())
    d1_df = df[df["dt_str"] == latest_dt]
    d1_1to2 = d1_df[d1_df["is_1to2_day"]]
    mkt_d1_zt_cnt = int(d1_df["is_zt"].sum())
    mkt_d1_dt_cnt = int(d1_df["is_dt"].sum())
    mkt_1to2_touch = int(d1_1to2["touch_zt"].sum())
    mkt_1to2_seal = int(d1_1to2["is_zt"].sum())
    mkt_d1_1to2_seal_rate = float(mkt_1to2_seal / mkt_1to2_touch) if mkt_1to2_touch > 0 else 0.55
    tot_thr = 255 if mkt_d1_1to2_seal_rate > 0.75 else 230

    # 计算过去 5 个交易日全市场主板首板次日自然晋级率均值
    all_dts = sorted(df["dt_str"].unique())
    recent_5_dts = all_dts[-5:]
    promo_rates_5d = []
    for d_item in recent_5_dts:
        sub_d = df[df["dt_str"] == d_item]
        sub_1to2_cnt = int(sub_d["is_1to2_day"].sum())
        sub_seal_cnt = int((sub_d["is_1to2_day"] & sub_d["is_zt"]).sum())
        r = (sub_seal_cnt / sub_1to2_cnt) if sub_1to2_cnt > 0 else 0.0
        promo_rates_5d.append(r)
    mkt_1to2_promo_ma5 = float(np.mean(promo_rates_5d)) if promo_rates_5d else 0.20

    fb_df = d1_df[d1_df["is_zt"] & (~d1_df["prev_zt"])].copy()

    # 读取雪球新概念库 + 人工优先词表
    xq_concepts = {}
    noise_terms = set()
    if os.path.exists(CONCEPTS_PATH):
        ac_json = json.load(open(CONCEPTS_PATH, encoding="utf-8"))
        xq_concepts = ac_json.get("concepts", {})
        xq_judged = {**ac_json.get("judged", {}), **ac_json.get("judged_v2", {})}
        noise_terms = {k for k, v in xq_judged.items() if isinstance(v, dict) and v.get("c") == "noise"}

    priority_terms = set()
    if os.path.exists(PRIORITY_TERMS_PATH):
        try:
            pt_data = json.load(open(PRIORITY_TERMS_PATH, encoding="utf-8"))
            for item in pt_data.get("terms", []):
                if isinstance(item, str) and item.strip():
                    priority_terms.add(_norm_term(item.strip()))
                elif isinstance(item, dict) and item.get("term"):
                    priority_terms.add(_norm_term(str(item["term"]).strip()))
        except Exception:
            pass

    latest_date_obj = datetime.date.fromisoformat(latest_dt)
    cutoff_15d = (latest_date_obj - datetime.timedelta(days=15)).isoformat()
    xq_new_15d = set(priority_terms)
    for k, v in xq_concepts.items():
        if k in noise_terms:
            continue
        fs = str(v.get("first_seen") or "")[:10]
        if fs >= cutoff_15d:
            xq_new_15d.add(_norm_term(v.get("term") or k))
            xq_new_15d.add(k)

    # 读取全量 KPL 历史构建词频首次出现与 2026-05-01 起动态 Elo
    all_kpl_days = [json.loads(ln) for ln in open(KPL_PATH, encoding="utf-8") if ln.strip()]
    all_kpl_days.sort(key=lambda x: x["date"])

    term_seen_days = Counter()
    term_first_dt = {}
    term_last_idx = {}

    # 先快速预热 2026-05-01 之前的词频与首次出现日期
    pre_kpl = [d for d in all_kpl_days if d["date"] < "2026-05-01"]
    post_kpl = [d for d in all_kpl_days if "2026-05-01" <= d["date"] <= latest_dt]

    # 若当日在 kpl_plates_v2.jsonl 中缺失或 plates 为空，自动通过同花顺涨停池与规范题材双源补齐
    has_today_plates = False
    if post_kpl and post_kpl[-1]["date"] == latest_dt and len(post_kpl[-1].get("plates", [])) > 0:
        has_today_plates = True
    if not has_today_plates:
        today_plates = _fetch_today_plates_fallback(latest_dt, fb_df)
        if post_kpl and post_kpl[-1]["date"] == latest_dt:
            post_kpl[-1]["plates"] = today_plates
        else:
            post_kpl.append({"date": latest_dt, "plates": today_plates})
        print(f"[fallback] 已通过同花顺涨停池双源合成今日 {latest_dt} 板块数: {len(today_plates)}")

    for idx_pre, d in enumerate(pre_kpl):
        dt = d["date"]
        for p in d.get("plates", []):
            pname = p.get("plate", "")
            if pname in NON_THEME:
                continue
            for s in p.get("stocks", []):
                r_short = str(s[2]) if len(s) > 2 else ""
                for t in set(split_terms(pname)) | set(split_terms(r_short)):
                    if len(t) >= 2 and _norm_term(t) not in noise_terms:
                        term_seen_days[t] += 1
                        if t not in term_first_dt:
                            term_first_dt[t] = dt
                        term_last_idx[t] = idx_pre - len(pre_kpl)

    day_stock_map = {
        (r.dt_str, r.c6): (r.is_zt, r.touch_zt, r.is_yizi, r.pct, r.mcap, r.to)
        for r in df[["dt_str", "c6", "is_zt", "touch_zt", "is_yizi", "pct", "mcap", "to"]].itertuples(index=False)
    }

    elo = defaultdict(lambda: 100.0)
    plate_recent_zts = defaultdict(list)
    plate_last_idx = {}
    prev_day_plate_stocks = {}
    stock_theme_d1 = {}
    theme_board = []

    for day_idx, d in enumerate(post_kpl):
        dt = d["date"]
        plates = d.get("plates", [])
        for pname, c6_list in prev_day_plate_stocks.items():
            touches, seals, rets = 0, 0, []
            for c6 in c6_list:
                st = day_stock_map.get((dt, c6))
                if st is not None:
                    rets.append(st[3])
                    if st[1]:
                        touches += 1
                    if st[0]:
                        seals += 1
            if touches >= 2 and (seals / touches) < 0.50:
                elo[pname] -= 12.0 * ((touches - seals) / touches)
            elif rets and np.mean(rets) < -0.025:
                elo[pname] -= 10.0
            elif seals >= 2 and (seals / max(touches, 1)) >= 0.70:
                elo[pname] += min(10.0, 5.0 + seals * 1.2)
            elif rets and np.mean(rets) > 0.025:
                elo[pname] += 6.0

        for p_name in list(elo.keys()):
            if day_idx - plate_last_idx.get(p_name, day_idx) > 3:
                elo[p_name] = 100.0 + (elo[p_name] - 100.0) * 0.85

        new_prev_stocks, plate_scores, plate_meta = {}, {}, {}
        for p in plates:
            pname = p.get("plate", "")
            if pname in NON_THEME:
                continue
            stocks = p.get("stocks", [])
            sz = len(stocks)
            if sz == 0:
                continue
            c6_list = []
            n_ma, n_tech, n_earn, n_big_mcap, n_yizi, n_new_term, spark_bonus = 0, 0, 0, 0, 0, 0, 0.0
            new_terms_hit = set()
            spark_terms_hit = set()
            for s in stocks:
                c6 = str(s[0]).strip()[:6]
                c6_list.append(c6)
                r_short = str(s[2]) if len(s) > 2 else ""
                r_long = str(s[3]) if len(s) > 3 else ""
                txt = f"{pname} {r_short} {r_long}"
                if MA_PAT.search(txt):
                    n_ma += 1
                if TECH_PAT.search(txt):
                    n_tech += 1
                if EARN_PAT.search(txt):
                    n_earn += 1
                terms = set(split_terms(pname)) | set(split_terms(r_short))
                for t in terms:
                    nt = _norm_term(t)
                    if len(t) >= 2 and nt not in noise_terms:
                        prev_cnt = term_seen_days[t]
                        prev_idx = term_last_idx.get(t, -9999)
                        f_dt = term_first_dt.get(t, dt)
                        if prev_cnt == 0 or f_dt >= cutoff_15d or nt in xq_new_15d:
                            n_new_term += 1
                            new_terms_hit.add(t)
                        elif 5 <= (day_idx - prev_idx) <= 45 and prev_cnt <= 5:
                            spark_bonus = max(spark_bonus, 6.0)
                            spark_terms_hit.add(t)
                        term_seen_days[t] += 1
                        if t not in term_first_dt:
                            term_first_dt[t] = dt
                        term_last_idx[t] = day_idx
                st = day_stock_map.get((dt, c6))
                if st is not None:
                    if st[4] >= 150.0:
                        n_big_mcap += 1
                    if st[2]:
                        n_yizi += 1

            new_prev_stocks[pname] = c6_list
            plate_last_idx[pname] = day_idx
            recent_5d_zts = sum(cnt for idx_p, cnt in plate_recent_zts[pname] if day_idx - idx_p <= 5)
            plate_recent_zts[pname].append((day_idx, sz))

            score = (
                elo[pname]
                + min(sz, 15) * 1.8
                + min(recent_5d_zts, 30) * 0.35
                + (8.0 if n_ma > 0 else 0.0)
                + (6.0 if (TECH_PAT.search(pname) or n_tech >= max(1, sz // 2)) else 0.0)
                + (5.0 if n_new_term > 0 else 0.0)
                + spark_bonus
                + min(n_yizi * 4.0, 8.0)
                - (n_earn / sz) * 12.0
                - (n_big_mcap / sz) * 10.0
            )
            plate_scores[pname] = score
            plate_meta[pname] = {
                "plate": pname,
                "score": round(float(score), 2),
                "elo": round(float(elo[pname]), 2),
                "sz": int(sz),
                "recent_5d_zts": int(recent_5d_zts),
                "n_yizi": int(n_yizi),
                "n_ma": int(n_ma),
                "n_tech": int(n_tech),
                "n_earn": int(n_earn),
                "has_new_term": bool(n_new_term > 0),
                "new_terms": sorted(new_terms_hit)[:5],
                "spark_bonus": float(spark_bonus),
                "spark_terms": sorted(spark_terms_hit)[:5],
                "stocks": [str(s[1]).strip() for s in stocks[:8]],
            }

        prev_day_plate_stocks = new_prev_stocks
        if dt == post_kpl[-1]["date"]:
            ranked_p = sorted(plate_scores.keys(), key=lambda k: plate_scores[k], reverse=True)
            rk_map = {k: i + 1 for i, k in enumerate(ranked_p)}
            top2_sc = plate_scores[ranked_p[1]] if len(ranked_p) >= 2 else 100.0
            for pname in ranked_p:
                m = plate_meta[pname]
                rk = rk_map[pname]
                gap = (m["score"] - top2_sc) if rk == 1 else 0.0
                m["elo_rk"] = rk
                m["score_gap_vs_top2"] = round(float(gap), 2)
                # 板块代表性先验分（不含个股自身公告加分）
                base_pri = (
                    (28 if rk == 1 else (16 if rk == 2 else (8 if rk == 3 else 0)))
                    + (18 if m["sz"] >= 4 else (10 if m["sz"] >= 2 else -15))
                    + (15 if m["has_new_term"] else 0)
                    + (10 if m["spark_bonus"] > 0 else 0)
                    + (16 if (TECH_PAT.search(pname) or m["n_tech"] >= max(1, m["sz"] // 2)) else 0)
                    + (12 if gap >= 20 else 0)
                    + float(np.clip((m["score"] - 100.0) * 0.25, 0.0, 25.0))
                )
                m["plate_base_s_prior"] = round(float(base_pri), 1)
                theme_board.append(m)

            for p in plates:
                pname = p.get("plate", "")
                if pname not in rk_map:
                    continue
                m = plate_meta[pname]
                rk = rk_map[pname]
                for s in p.get("stocks", []):
                    c6 = str(s[0]).strip()[:6]
                    r_short = str(s[2]) if len(s) > 2 else ""
                    r_long = str(s[3]) if len(s) > 3 else ""
                    txt = f"{pname} {r_short} {r_long}"
                    cur_prev = stock_theme_d1.get(c6)
                    if cur_prev is None or m["score"] > cur_prev["theme_score"]:
                        stock_theme_d1[c6] = {
                            "name": str(s[1]).strip(),
                            "plate": pname,
                            "elo_rk": rk,
                            "theme_score": m["score"],
                            "elo": m["elo"],
                            "score_gap_vs_top2": m["score_gap_vs_top2"],
                            "p_sz": m["sz"],
                            "has_new_term": m["has_new_term"],
                            "new_terms": m["new_terms"],
                            "spark_bonus": m["spark_bonus"],
                            "is_ma": bool(MA_PAT.search(txt)),
                            "is_tech": bool(TECH_PAT.search(txt)),
                            "is_earn": bool(EARN_PAT.search(txt)),
                            "r_short": r_short,
                        }

    # 读取 notices.db 近 3 日（含晚间预披露次日/周末/周一日期）公告判定
    notice_start = (latest_date_obj - datetime.timedelta(days=4)).isoformat()
    notice_end = (latest_date_obj + datetime.timedelta(days=4)).isoformat()
    stock_notices = defaultdict(lambda: {"notice_hard": False, "notice_bad": False, "notice_ma": False, "notice_earn": False, "titles": []})
    if os.path.exists(NOTICES_DB_PATH):
        conn = sqlite3.connect(NOTICES_DB_PATH)
        c6_tuple = tuple(fb_df["c6"].unique().tolist())
        if c6_tuple:
            placeholders = ",".join(["?"] * len(c6_tuple))
            q = f"SELECT code, ndate, title FROM notice WHERE ndate >= ? AND ndate <= ? AND code IN ({placeholders})"
            for code, ndate, title in conn.execute(q, (notice_start, notice_end, *c6_tuple)).fetchall():
                c6 = str(code).strip()[:6]
                t_s = str(title or "").strip()
                info = stock_notices[c6]
                if HARD_NOTICE_PAT.search(t_s):
                    info["notice_hard"] = True
                if MA_NOTICE_PAT.search(t_s):
                    info["notice_ma"] = True
                if EARN_NOTICE_PAT.search(t_s):
                    info["notice_earn"] = True
                if BAD_NOTICE_PAT.search(t_s):
                    info["notice_bad"] = True
                if len(info["titles"]) < 3:
                    info["titles"].append(f"[{ndate}] {t_s[:45]}")
        conn.close()

    # 若 KPL 未覆盖某只首板股票名称，用腾讯批量补名称
    missing_name_codes = [c for c in fb_df["c6"].tolist() if c not in stock_theme_d1]
    fallback_names = {}
    if missing_name_codes:
        try:
            q_c = [("sh" + c if c.startswith("6") else "sz" + c) for c in missing_name_codes]
            lv_map = _fetch_tencent_batch(q_c)
            fallback_names = {k: v["name"] for k, v in lv_map.items()}
        except Exception:
            pass

    candidates = []
    for _, r in fb_df.iterrows():
        c6 = r["c6"]
        t_info = stock_theme_d1.get(
            c6,
            {
                "name": fallback_names.get(c6, ""),
                "plate": "其他",
                "elo_rk": 99,
                "theme_score": 95.0,
                "elo": 100.0,
                "score_gap_vs_top2": 0.0,
                "p_sz": 1,
                "has_new_term": False,
                "new_terms": [],
                "spark_bonus": 0.0,
                "is_ma": False,
                "is_tech": False,
                "is_earn": False,
                "r_short": "",
            },
        )
        n_info = stock_notices[c6]
        sname = t_info["name"] or fallback_names.get(c6, "")
        is_st = "ST" in sname.upper()
        is_ma = bool(t_info["is_ma"] or n_info["notice_ma"])
        is_tech = bool(t_info["is_tech"])
        is_earn = bool(t_info["is_earn"])
        notice_hard = bool(n_info["notice_hard"])
        notice_bad = bool(n_info["notice_bad"])

        elo_rk = int(t_info["elo_rk"])
        p_sz = int(t_info["p_sz"])
        has_new_term = bool(t_info["has_new_term"])
        spark_bonus = float(t_info["spark_bonus"])
        gap_top2 = float(t_info["score_gap_vs_top2"])
        t_score = float(t_info["theme_score"])

        s_prior = (
            (28 if elo_rk == 1 else (16 if elo_rk == 2 else (8 if elo_rk == 3 else 0)))
            + (18 if p_sz >= 4 else (10 if p_sz >= 2 else -15))
            + (15 if has_new_term else 0)
            + (10 if spark_bonus > 0 else 0)
            + (18 if notice_hard else 0)
            + (18 if is_ma else 0)
            + (16 if is_tech else 0)
            + (12 if gap_top2 >= 20.0 else 0)
            + float(np.clip((t_score - 100.0) * 0.25, 0.0, 25.0))
        )

        mcap = float(r["mcap"])
        amt = float(r["amount"])
        dd20 = float(r["f_dd20_d0"]) if pd.notna(r["f_dd20_d0"]) else 0.90
        dd60 = float(r["f_dd60_d0"]) if pd.notna(r["f_dd60_d0"]) else 0.85
        pos20 = float(r["f_pos20_d0"]) if pd.notna(r["f_pos20_d0"]) else 0.50
        d0_pct = float(r["f_d0_pct"]) if pd.notna(r["f_d0_pct"]) else 0.0
        ret10 = float(r["f_ret_pre10"]) if pd.notna(r["f_ret_pre10"]) else 0.0
        to = float(r["to"])
        vol_ratio = float(r["f_d1_vol_ratio"]) if pd.notna(r["f_d1_vol_ratio"]) else 1.5
        zt_pre20 = int(r["f_zt_cnt_pre20"]) if pd.notna(r["f_zt_cnt_pre20"]) else 0

        sc_mcap = 28 if 60 <= mcap <= 155 else (10 if 40 <= mcap < 60 else (-20 if mcap < 35 else 0))
        sc_amt = 18 if 2.2e8 <= amt <= 15e8 else (-25 if amt < 1.8e8 else -10)
        sc_dd20 = 42 if dd20 <= 0.82 else (32 if dd20 <= 0.86 else (18 if dd20 <= 0.90 else (-40 if dd20 > 0.95 else 0)))
        sc_dd60 = 18 if dd60 <= 0.76 else (10 if dd60 <= 0.82 else (-15 if dd60 > 0.92 else 0))
        sc_nshape = 22 if (zt_pre20 >= 1 and dd20 <= 0.86) else (-20 if (zt_pre20 >= 1 and dd20 > 0.92) else 0)
        sc_pos20 = 25 if pos20 <= 0.30 else (12 if pos20 <= 0.45 else (-35 if pos20 > 0.75 else 0))
        sc_d0 = 25 if d0_pct <= -0.010 else (15 if d0_pct <= 0.005 else (-35 if d0_pct > 0.030 else 0))
        sc_ret10 = 15 if ret10 <= 0.05 else (-35 if ret10 > 0.18 else 0)
        sc_to = 15 if to <= 9.0 else (8 if to <= 15.0 else (-25 if to > 18.0 else 0))
        sc_vol = 15 if vol_ratio <= 1.75 else (-15 if vol_ratio > 2.3 else 0)
        sc_mkt_seal = 18 if mkt_d1_1to2_seal_rate < 0.64 else (-25 if mkt_d1_1to2_seal_rate >= 0.72 else 0)
        sc_mkt_dt = 12 if mkt_d1_dt_cnt <= 6 else (-15 if mkt_d1_dt_cnt >= 15 else 0)
        sc_mkt_zt = 12 if mkt_d1_zt_cnt >= 45 else (-18 if mkt_d1_zt_cnt < 35 else 0)

        s_q_base = (
            sc_mcap + sc_amt + sc_dd20 + sc_dd60 + sc_nshape + sc_pos20
            + sc_d0 + sc_ret10 + sc_to + sc_vol + sc_mkt_seal + sc_mkt_dt + sc_mkt_zt
        )

        gate_ok = bool(
            (not is_st)
            and (not bool(r["is_yizi"]))
            and (not is_earn)
            and (not notice_bad)
            and (18.0 <= mcap <= 220.0)
            and (to <= 20.0)
            and (not (zt_pre20 >= 4 and pos20 > 0.38))
        )

        static_tot = float(s_prior + s_q_base)
        need_auc = int(max(0, np.ceil(tot_thr - static_tot), np.ceil(140.0 - s_q_base)))

        candidates.append(
            {
                "ticker": str(r["ticker"]),
                "c6": c6,
                "name": sname,
                "d1_date": latest_dt,
                "pre_c": round(float(r["close"]), 2),
                "mcap": round(mcap, 2),
                "amount_yi": round(amt / 1e8, 2),
                "to": round(to, 2),
                "is_yizi": bool(r["is_yizi"]),
                "is_st": is_st,
                "plate": t_info["plate"],
                "r_short": t_info.get("r_short", ""),
                "elo_rk": elo_rk,
                "theme_score": round(t_score, 2),
                "elo": round(float(t_info["elo"]), 2),
                "p_sz": p_sz,
                "has_new_term": has_new_term,
                "new_terms": t_info.get("new_terms", []),
                "spark_bonus": spark_bonus,
                "is_ma": is_ma,
                "is_tech": is_tech,
                "is_earn": is_earn,
                "notice_hard": notice_hard,
                "notice_bad": notice_bad,
                "notice_titles": n_info["titles"],
                "dd20_d0": round(dd20, 3),
                "dd60_d0": round(dd60, 3),
                "pos20_d0": round(pos20, 3),
                "d0_pct": round(d0_pct, 4),
                "ret_pre10": round(ret10, 4),
                "vol_ratio": round(vol_ratio, 2),
                "zt_cnt_pre20": zt_pre20,
                "s_prior": round(float(s_prior), 1),
                "s_q_base": round(float(s_q_base), 1),
                "static_tot": round(static_tot, 1),
                "need_auc": need_auc,
                "gate_ok": gate_ok,
            }
        )

    candidates.sort(key=lambda x: (x["gate_ok"] and x["s_prior"] >= 35, x["static_tot"]), reverse=True)

    cache_obj = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "d1_date": latest_dt,
        "patched_today_from_tencent": patched_today,
        "mkt_sentiment": {
            "d1_zt_cnt": mkt_d1_zt_cnt,
            "d1_dt_cnt": mkt_d1_dt_cnt,
            "d1_1to2_seal_rate": round(mkt_d1_1to2_seal_rate, 3),
            "d1_1to2_promo_ma5": round(mkt_1to2_promo_ma5, 4),
            "tot_thr": tot_thr,
        },
        "theme_board": theme_board,
        "candidates": candidates,
        "elapsed_sec": round(time.time() - t0, 2),
    }

    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp_p = CACHE_PATH + ".tmp"
    with open(tmp_p, "w", encoding="utf-8") as f:
        json.dump(cache_obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp_p, CACHE_PATH)

    if verbose:
        print(
            f"[build-cache] 基准首板日={latest_dt} (腾讯补今日日线={patched_today}) | "
            f"题材数={len(theme_board)} | 首板候选={len(candidates)} "
            f"(过硬门槛且题材>=35分: {sum(1 for c in candidates if c['gate_ok'] and c['s_prior'] >= 35)}只) | "
            f"耗时={cache_obj['elapsed_sec']:.2f}s"
        )
        print_premarket(cache_obj)

    return cache_obj


def _auc_requirement_desc(need_auc: int) -> str:
    if need_auc <= 45:
        return f"竞价需>={need_auc}分：09:25高开+3.0%~+8.2%且拿板块竞价第1即可直接过线"
    if need_auc <= 55:
        return f"竞价需>={need_auc}分：09:25高开+4.0%~+8.2%且拿板块竞价第1即可过线"
    if need_auc <= 77:
        return f"竞价需>={need_auc}分：高开+4.0%~+8.2%拿板块第1 + 领先同题材第2名>=1%~2%(或全场前6)"
    if need_auc <= 97:
        return f"竞价需>={need_auc}分：高开+4.0%~+8.2%拿板块第1 + 全场前3 + 断层领先>=2%(接近满分97)"
    return f"竞价需>={need_auc}分(>满分97)：静态底分不足，除非板块其他票极端低开否则难达标"


def print_premarket(cache_obj: dict = None):
    t0 = time.time()
    if cache_obj is None:
        if not os.path.exists(CACHE_PATH):
            print("未找到盘后预缓存，请先运行 --build-cache")
            return
        cache_obj = json.load(open(CACHE_PATH, encoding="utf-8"))

    d1_date = cache_obj.get("d1_date", "")
    gen_at = cache_obj.get("generated_at", "")
    mkt = cache_obj.get("mkt_sentiment", {})
    themes = cache_obj.get("theme_board", [])
    cands = cache_obj.get("candidates", [])

    d1_seal_rate = float(mkt.get("d1_1to2_seal_rate", 0.55))
    promo_ma5 = float(mkt.get("d1_1to2_promo_ma5", 0.20))
    tot_thr = int(mkt.get("tot_thr") or (255 if d1_seal_rate > 0.75 else 230))
    gate_note = "【高潮次日保护已触发：总分门槛提至 255 分】" if tot_thr == 255 else "【常规门槛：总分 230 分】"

    print(
        f"=== 一进二定式 M2 盘前预评分缓存 (首板基准日: {d1_date} | 生成: {gen_at}) ==="
    )
    print(
        f"市场情绪底分项: D1涨停={mkt.get('d1_zt_cnt')}家 | D1跌停={mkt.get('d1_dt_cnt')}家 | "
        f"D1一进二封板率={d1_seal_rate*100:.1f}% | 近5日自然晋级率MA5={promo_ma5*100:.1f}% | 生效总分门槛={tot_thr}分 {gate_note}"
    )
    if promo_ma5 < 0.13:
        print(f"⚠️ 近5日全市场一进二自然晋级率 {promo_ma5*100:.1f}% < 13.0%（极端冰点熔断线），暂停开仓")
    print("\n【一、今日题材热度 Top 10 打分表（先验门槛 >= 35 分过线）】")
    for t in themes[:10]:
        pass_flag = "过线" if t.get("plate_base_s_prior", 0) >= 35 else "未过(需个股硬公告/重组加分)"
        new_tag = f" [新词:{','.join(t.get('new_terms', [])[:2])}]" if t.get("has_new_term") else ""
        spark_tag = " [星火+10]" if t.get("spark_bonus", 0) > 0 else ""
        print(
            f"  #{t['elo_rk']:02d} {t['plate']:<10s} | 综合分={t['score']:6.1f} (Elo={t['elo']:5.1f}) | "
            f"首板家数={t['sz']:2d} (一字={t['n_yizi']}) | 板块基础先验={t.get('plate_base_s_prior', 0):4.0f} ({pass_flag}){new_tag}{spark_tag}"
        )

    valid_cands = [c for c in cands if c.get("gate_ok") and c.get("s_prior", 0) >= 35]
    valid_cands.sort(key=lambda x: x["static_tot"], reverse=True)
    print(
        f"\n【二、昨日换手首板过硬门槛且题材分 >= 35 候选股盘前预评分排行（共 {len(valid_cands)} 只，当前生效总分门槛: {tot_thr} 分）】"
    )
    for i, c in enumerate(valid_cands, 1):
        tags = []
        if c.get("is_ma"):
            tags.append("重组/合同+18")
        if c.get("notice_hard"):
            tags.append("硬公告+18")
        if c.get("is_tech"):
            tags.append("硬科技+16")
        if c.get("has_new_term"):
            tags.append("新词+15")
        tag_str = f" [{','.join(tags)}]" if tags else ""
        need_auc = int(max(0, np.ceil(tot_thr - c["static_tot"]), np.ceil(140.0 - c["s_q_base"])))
        req_desc = _auc_requirement_desc(need_auc)
        print(
            f"  {i:02d}. {c['ticker']} {c['name']:<6s} | {c['plate']:<8s}(#{c['elo_rk']}) | "
            f"静态总分={c['static_tot']:5.0f} (题材={c['s_prior']:3.0f} + 静态筹码={c['s_q_base']:4.0f}) | "
            f"市值={c['mcap']:5.1f}亿 换手={c['to']:4.1f}% 回撤dd20={c['dd20_d0']:.2f}{tag_str}\n"
            f"      └─ {req_desc}"
        )
    print(f"[premarket] 读取打印耗时={time.time()-t0:.3f}s")


def check_live():
    t0 = time.time()
    if not os.path.exists(CACHE_PATH):
        print("未找到盘后预缓存，请先运行 --build-cache")
        return
    cache_obj = json.load(open(CACHE_PATH, encoding="utf-8"))
    cands = cache_obj.get("candidates", [])
    if not cands:
        print("今日无符合条件的一进二候选。")
        return

    mkt = cache_obj.get("mkt_sentiment", {})
    d1_seal_rate = float(mkt.get("d1_1to2_seal_rate", 0.55))
    promo_ma5 = float(mkt.get("d1_1to2_promo_ma5", 0.20))
    tot_thr = int(mkt.get("tot_thr") or (255 if d1_seal_rate > 0.75 else 230))
    gate_note = "【高潮次日保护触发：门槛 255 分】" if tot_thr == 255 else "【常规门槛：230 分】"

    promo_freeze = False
    if promo_ma5 < 0.13:
        promo_freeze = True
        print(f"⚠️ 近5日全市场一进二自然晋级率 {promo_ma5*100:.1f}% < 13.0%（极端冰点熔断线），暂停开仓")

    q_codes = [("sh" + c["c6"] if c["c6"].startswith("6") else "sz" + c["c6"]) for c in cands]
    txt = urllib.request.urlopen("http://qt.gtimg.cn/q=" + ",".join(q_codes), timeout=5).read().decode("gbk", errors="ignore")
    live = {}
    for ln in txt.strip().splitlines():
        if '="' not in ln:
            continue
        k, v = ln.split('="', 1)
        p = v.strip('";').split("~")
        if len(p) > 35:
            op = float(p[5] or 0) or float(p[9] or 0) or float(p[3] or 0)
            live[k[-6:]] = {
                "name": p[1],
                "pre": float(p[4] or 0),
                "open": op,
                "high": float(p[33] or 0),
                "cur": float(p[3] or 0),
            }
    for c in cands:
        lv = live.get(c["c6"], {})
        pre = lv.get("pre") or c["pre_c"]
        op = lv.get("open", 0)
        c["o_pct"] = (op / pre - 1.0) if (op > 0 and pre > 0) else -0.99
        c["open_p"] = op
        c["high_p"] = lv.get("high", 0)
        c["cur_p"] = lv.get("cur", 0)
        zt_p = np.floor(pre * 1.10 * 100 + 0.5) / 100
        c["trig_p"] = min(zt_p, max(op * 1.012, pre * 1.065)) if op > 0 else zt_p
    df = pd.DataFrame(cands)

    # 09:25 量化核按钮日空仓闸：计算昨日换手首板候选池在今日 09:25 的平均开盘涨幅
    valid_opens = df[df["open_p"] > 0]["o_pct"]
    prev_zt_auc_avg = float(valid_opens.mean()) if len(valid_opens) > 0 else 0.0
    nuclear_halt = False
    if len(valid_opens) > 0 and prev_zt_auc_avg < 0.0:
        nuclear_halt = True
        print(f"⚠️ 今日昨日首板竞价均值 {prev_zt_auc_avg*100:+.2f}% < 0%，触发量化核按钮日保护，全天空仓")

    df["mkt_open_rk"] = df["o_pct"].rank(ascending=False, method="min")
    df["theme_open_rk"] = df.groupby("plate")["o_pct"].rank(ascending=False, method="min")
    p2 = df.groupby("plate")["o_pct"].apply(lambda s: s.nlargest(2).iloc[-1] if len(s) >= 2 else -0.05).to_dict()
    df["open_lead"] = np.where(df["theme_open_rk"] == 1, df["o_pct"] - df["plate"].map(p2), 0.0)
    auc_bonus = (
        np.where(df["theme_open_rk"] == 1, 35, np.where(df["theme_open_rk"] == 2, 5, -25))
        + np.where(df["mkt_open_rk"] <= 3, 20, np.where(df["mkt_open_rk"] <= 6, 12, 0))
        + np.where(df["open_lead"] >= 0.020, 22, np.where(df["open_lead"] >= 0.010, 12, 0))
        + np.where(df["o_pct"].between(0.040, 0.082), 20, np.where(df["o_pct"].between(0.030, 0.040), 10, 0))
    )
    df["s_quant"] = df["s_q_base"] + auc_bonus
    df["tot"] = df["s_prior"] + df["s_quant"]
    df["ok"] = (
        df["gate_ok"]
        & df["o_pct"].between(0.030, 0.082)
        & (df["s_prior"] >= 35)
        & (df["s_quant"] >= 140)
        & (df["tot"] >= tot_thr)
        & (~nuclear_halt)
        & (~promo_freeze)
    )

    print(
        f"=== 一进二定式 M2 实时裁决 | 当前生效总分门槛: {tot_thr} 分 {gate_note} | "
        f"昨日首板竞价均值={prev_zt_auc_avg*100:+.2f}% | 近5日自然晋级率MA5={promo_ma5*100:.1f}% ==="
    )
    for _, r in df.sort_values(["ok", "tot"], ascending=[False, False]).head(10).iterrows():
        print(
            f"OK={int(r['ok'])} | {r['ticker']} {r['name']} | {r['plate']}(t_rk={int(r['theme_open_rk'])},m_rk={int(r['mkt_open_rk'])}) "
            f"| 总分={r['tot']:.0f}(先验{r['s_prior']:.0f}+量化{r['s_quant']:.0f}) | 开盘={r['open_p']:.2f}({r['o_pct']*100:+.2f}%) "
            f"| 点火买价={r['trig_p']:.2f} | 现价={r['cur_p']:.2f}(最高{r['high_p']:.2f})"
        )
    print(f"[live] 基准日={cache_obj.get('d1_date')} | 实时打分总耗时={time.time()-t0:.3f}s")


def sync_all():
    t_start = time.time()
    step_times = {}

    # Step 1: 同步近期东财公告库
    s1 = time.time()
    print("[sync-all 1/4] 同步东财全市场公告库 (sync_notices_db.py --recent)...", flush=True)
    subprocess.run([sys.executable, SYNC_NOTICES_SCRIPT, "--recent"], check=False, timeout=90)
    step_times["1_notices_db"] = round(time.time() - s1, 2)

    # Step 2: 若当前时间 >= 15:15，拉取当日开盘啦涨停题材梯队
    s2 = time.time()
    now = datetime.datetime.now()
    if (now.hour > 15) or (now.hour == 15 and now.minute >= 15):
        print("[sync-all 2/4] 当前 >= 15:15，同步开盘啦今日涨停题材 (astock_concept_vocab.py --today)...", flush=True)
        try:
            subprocess.run(
                [sys.executable, f"{ND_DIR}/astock_concept_vocab.py", "--today"],
                check=False,
                timeout=90,
            )
        except Exception as e:
            print(f"  ⚠️ astock_concept_vocab.py 异常: {e}", flush=True)
    else:
        print("[sync-all 2/4] 当前 < 15:15，跳过开盘啦盘后涨停接口拉取。", flush=True)
    step_times["2_kpl_vocab"] = round(time.time() - s2, 2)

    # Step 3: 增量刷新雪球/社区与同花顺实时涨停原因新词 (加 --skip-extract --dry 避免阻塞重写飞书文档，超时保护 45s)
    s3 = time.time()
    print("[sync-all 3/4] 刷新社区与涨停原因新概念库 (astock_concepts.py --skip-extract --dry)...", flush=True)
    try:
        subprocess.run(
            [sys.executable, f"{ND_DIR}/astock_concepts.py", "--skip-extract", "--dry"],
            check=False,
            timeout=45,
        )
    except Exception as e:
        print(f"  ⚠️ astock_concepts.py 超时或异常 (已降级使用现有词库): {e}", flush=True)
    step_times["3_concepts"] = round(time.time() - s3, 2)

    # Step 4: 构建盘前预评分缓存
    s4 = time.time()
    print("[sync-all 4/4] 构建一进二盘前预评分缓存 (--build-cache)...", flush=True)
    build_cache(verbose=True)
    step_times["4_build_cache"] = round(time.time() - s4, 2)

    tot_sec = round(time.time() - t_start, 2)
    print(f"[sync-all] 全部完成! 分步耗时={step_times} | 总耗时={tot_sec:.2f}s", flush=True)


def main():
    ap = argparse.ArgumentParser(description="一进二定式 M2 预缓存与盘中极速裁决引擎")
    ap.add_argument("--sync-all", action="store_true", help="同步公告+KPL+新词并构建预评分缓存")
    ap.add_argument("--build-cache", action="store_true", help="构建盘前预评分缓存 1to2_premarket_cache.json")
    ap.add_argument("--premarket", action="store_true", help="秒读缓存打印今日题材热度与候选预评分表")
    args = ap.parse_args()

    if args.sync_all:
        sync_all()
    elif args.build_cache:
        build_cache(verbose=True)
    elif args.premarket:
        print_premarket()
    else:
        check_live()


if __name__ == "__main__":
    main()
