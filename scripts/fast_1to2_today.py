#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_1to2_today.py — 「一进二生产主策略定版 V17 精简增强版」（96笔 / 249.04倍单仓 / 60.19倍等权 / 66.7%胜率 / 2.80盈亏比 / 16.1%回撤 · 2026-11-12）

核心升级（V17 相对 V16）：
  1. 【新增跨年硬规则一（规则 α）】断层主线无过线头名股时，禁止退选第三题材标的 (rk_theme == 3)。
  2. 【新增跨年硬规则二（规则 β）】三大题材混战日 (极差<=15分且规模2~5家)，候选股必须卡全场竞价前二或具备公告硬催化/并购。
  3. 【新增前视生态规则三（规则 γ）】t-1 滚动前20日高开封板率传感器 roll20_ho_zt < 45% 时，周二至周五弱开惩罚上调至 <3.5% 扣 25 分。
  4. 【物理剪除 5 项零损冗余规则】
     - 去掉 f3_bonus 中 notice_hard 二次 +8.0 分（保留 s_prior_dual 里的 +18 分）；
     - 去掉 yizi_gran 中普通独苗一字榜首 +5.0 分与次席 -10.0 分（保留 myz in [1,2] 黄金共振 +8.0 分）；
     - 去掉 pass_l1 中宽泛旧行业独立拦截门，仅保留 not is_event_basket；
     - 去掉主通道与周一通道 s_quant >= 150.0 / 145.0 单项底线（由总分 304.8 分底线覆盖）；
     - 保留 plate_d2_yizi_cnt >= 1 的 +10 分与 14:30 炸板抢跑铁律！

用法：
  1. /opt/homebrew/bin/python3.13 scripts/fast_1to2_today.py --sync-all
     依次同步近期东财公告库 (notices.db)、15:15后同步开盘啦涨停题材 (astock_concept_vocab.py)、
     增量抓取社区新帖与新概念抽取、自动归档当日雪球概念快照与同花顺全量涨停池、
     合并读取 8年全量开盘啦库 + 增量，最后构建 1to2_premarket_cache.json。
  2. /opt/homebrew/bin/python3.13 scripts/fast_1to2_today.py --build-cache
     读取 2017-08 至今全量日线（若 15:05 后 parquet 尚未含今日日线，自动并发拉腾讯实时收盘快照无缝补齐今日日线），
     严格运行 8 年动态题材与破冰新词历史追踪、计算三层净化、先验分 s_prior、筹码双通道静态底分 s_q_base、
     微观盘口加分、机构调研加分与净化门 purifier_ok，落盘缓存。
  3. /opt/homebrew/bin/python3.13 scripts/fast_1to2_today.py --premarket
     09:00 / 09:15 前秒读缓存，输出今日题材热度 Top 10 与过门槛候选股盘前预评分排行及 09:25 过线竞价条件（常规 304.8分 / 高潮 329.8分）。
  4. /opt/homebrew/bin/python3.13 scripts/fast_1to2_today.py
     09:25:03 及盘中极速模式（< 1.0s），秒读缓存 + 拉腾讯实时竞价/盘口，输出最终总分与点火触发买价 trig_p。

⛔ 铁律保证：
1. ⛔ 绝对严禁 import yfinance 或调用 yf 查询 A 股（D12 铁律）。
2. ⛔ 所有 SQLite 数据库必须使用 file:...?mode=ro (uri=True) 严格只读模式。
3. ⛔ 严禁触碰 portfolio_state.json 或执行任何模拟盘/实盘交易。
"""

import os
import sys
import re
import json
import time
import bisect
import sqlite3
import datetime
import argparse
import subprocess
import urllib.request
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT_DIR = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT_DIR}/sim-portfolio"
ND_DIR = f"{ROOT_DIR}/news-dashboard"
CLEAN_DIR = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean"

if CLEAN_DIR not in sys.path:
    sys.path.insert(0, CLEAN_DIR)

from clean_wf_1to2_v14_ironclad_master import (
    load_full_prices,
    NON_THEME,
    MA_PAT,
    TECH_PAT_TIMELESS,
    EARN_PAT,
    HARD_NOTICE_PAT,
    MA_NOTICE_PAT,
    EARN_NOTICE_PAT,
    BAD_NOTICE_PAT,
    NEG_NOTICE_PAT,
    split_terms,
    norm_term,
    A_DAILY_PATH,
    A_DELISTED_PATH,
    KPL_MERGED_PATH,
    KPL_5Y_PATH,
    PIT_NOTICES_DB,
)
from exp1_fake_theme_purifier import (
    EVENT_BASKET_PLATES,
    BROAD_INDUSTRY_PLATES,
)

# 证监会二级行业映射与纯外行定义 (V16 终极版)
CSRC_INDUSTRY_PATH = f"{SIM_DIR}/data/csrc_industry_l2.csv"
CSRC_INDUSTRY_BACKUP = f"{SIM_DIR}/backtest/2026-10-15-review2022/industry.csv"
CSRC_PURE_OUTSIDER = {
    "A01","A02","A03","A04","A05", # 农林牧渔
    "D44","D45","D46",             # 电力燃气水务
    "E47","E48","E49","E50",       # 建筑装修
    "F51","F52",                   # 批发零售
    "G53","G54","G55","G56","G58","G59", # 交运仓储邮政
    "H61","H62",                   # 住宿餐饮
    "K70",                         # 房地产业
    "L72","N77","N78",             # 商务服务与公共设施
    "C13","C14","C15","C17","C18","C19","C20","C21","C22" # 食品纺织造纸家具轻工
}

def load_csrc_ind_map() -> dict:
    p = CSRC_INDUSTRY_PATH if os.path.exists(CSRC_INDUSTRY_PATH) else CSRC_INDUSTRY_BACKUP
    if os.path.exists(p):
        try:
            df_ind = pd.read_csv(p)
            df_ind["c6"] = df_ind["code"].astype(str).str[-6:]
            return dict(zip(df_ind["c6"], df_ind["industry"].fillna("")))
        except Exception:
            pass
    return {}

# 路径常量
KPL_V2_PATH = f"{ND_DIR}/output/kpl_plates_v2.jsonl"
VOCAB_PATH = f"{ND_DIR}/output/astock_concept_vocab.json"
CONCEPTS_PATH = f"{ND_DIR}/output/astock_concepts.json"
COMMUNITY_PATH = f"{ND_DIR}/output/astock_community.json"
NOTICES_DB_PATH = f"{SIM_DIR}/backtest/2026-08-24-daban/notices.db"
PIT_NOTICES_DB_PATH = f"{SIM_DIR}/data/cninfo_notices_5y_pit.db"
MICRO_TAPE_DB_PATH = f"{SIM_DIR}/data/zt_micro_tape_5y_pit.db"
IR_QA_DB_PATH = f"{SIM_DIR}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db"
CACHE_PATH = f"{SIM_DIR}/data/1to2_premarket_cache.json"
SYNC_NOTICES_SCRIPT = f"{SIM_DIR}/scripts/sync_notices_db.py"


def _fetch_tencent_batch(q_list: list) -> dict:
    url = "http://qt.gtimg.cn/q=" + ",".join(q_list)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    txt = urllib.request.urlopen(req, timeout=8).read().decode("gbk", errors="ignore")
    out = {}
    for ln in txt.strip().splitlines():
        if '="' not in ln:
            continue
        k, v = ln.split('="', 1)
        p = v.strip('";').split("~")
        if len(p) > 35:
            code = k[-6:]
            c_price = float(p[3] or 0)
            op = float(p[5] or 0) or float(p[9] or 0) or c_price
            hp = float(p[33] or 0) or c_price
            lp = float(p[34] or 0) or c_price
            amt = float(p[37] or 0) * 10000.0
            out[code] = {
                "name": p[1],
                "close": c_price,
                "open": op,
                "high": hp,
                "low": lp,
                "amount": amt,
                "pre_c": float(p[4] or 0),
            }
    return out


def _patch_today_daily_if_needed(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """若 15:05 后 parquet 未含今日收盘日线，并发拉取腾讯实时收盘快照无缝补齐"""
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return df, False
    if now.hour < 15 or (now.hour == 15 and now.minute < 5):
        return df, False

    today_str = now.strftime("%Y-%m-%d")
    max_d = str(df["dt_str"].max())[:10]
    if max_d == today_str:
        return df, False

    print(f"[patch] 检测到今日 {today_str} 已收盘但 parquet 最新为 {max_d}，并发拉取腾讯实时收盘快照补齐今日日线...", flush=True)
    all_tickers = df["ticker"].unique().tolist()
    q_codes = [("sh" + t[:6] if t.startswith("6") else "sz" + t[:6]) for t in all_tickers]
    batch_size = 80
    batches = [q_codes[i:i + batch_size] for i in range(0, len(q_codes), batch_size)]

    live_map = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(_fetch_tencent_batch, b) for b in batches]
        for f in as_completed(futs):
            try:
                res = f.result()
                live_map.update(res)
            except Exception:
                pass

    last_bars = df[df["dt_str"] == max_d].copy()
    today_rows = []
    today_ts = pd.Timestamp(today_str)
    for _, r in last_bars.iterrows():
        c6 = r["ticker"][:6]
        lv = live_map.get(c6)
        if not lv or lv["close"] <= 0:
            continue
        c_price = lv["close"]
        amt = lv["amount"]
        oshare = float(r["oshare"])
        turn = (amt / (c_price * oshare)) if (c_price > 0 and oshare > 0) else 0.0
        today_rows.append({
            "date": today_ts,
            "ticker": r["ticker"],
            "open": lv["open"],
            "high": lv["high"],
            "low": lv["low"],
            "close": c_price,
            "adj_close": c_price,
            "volume": float(r["volume"]),
            "amount": amt,
            "turn": turn,
            "oshare": oshare,
            "c6": c6,
            "dt_str": today_str,
        })

    if not today_rows:
        print("  ⚠️ 腾讯快照未拉取到今日有效收盘，沿用历史日线。")
        return df, False

    td_df = pd.DataFrame(today_rows)
    df = pd.concat([df, td_df], ignore_index=True)
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # 重新计算衍生技术特征
    g = df.groupby("c6")
    df["pre_c"] = g["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["o_pct"] = df["open"] / df["pre_c"] - 1.0
    df["h_pct"] = df["high"] / df["pre_c"] - 1.0
    df["l_pct"] = df["low"] / df["pre_c"] - 1.0
    df["mcap"] = df["close"] * df["oshare"] / 1e8
    df["to"] = df["turn"] * 100.0

    df["zt_price"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["dt_price"] = np.floor(df["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_price"] - 0.01) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
    df["is_dt"] = (df["close"] <= df["dt_price"] + 0.01) & (df["pct"] <= -0.095) & (df["pre_c"] > 0)
    df["touch_zt"] = ((df["high"] >= df["zt_price"] - 0.01) | (df["h_pct"] >= 0.098)) & (df["pre_c"] > 0)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_price"] - 0.01) & (df["low"] >= df["zt_price"] - 0.01)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_price"] + 0.01) & (df["high"] <= df["dt_price"] + 0.01)

    df["prev_zt"] = g["is_zt"].shift(1).fillna(False)
    df["prev2_zt"] = g["is_zt"].shift(2).fillna(False)
    df["is_2b_plus"] = df["is_zt"] & df["prev_zt"]
    df["is_1to2_day"] = df["prev_zt"] & (~df["prev2_zt"])
    df["is_first_board"] = df["is_zt"] & (~df["prev_zt"])

    df["f_d0_close"] = g["close"].shift(1)
    df["f_d0_pct"] = g["pct"].shift(1)
    df["f_ret_pre5"] = df["f_d0_close"] / (g["close"].shift(6) + 1e-6) - 1.0
    df["f_ret_pre10"] = df["f_d0_close"] / (g["close"].shift(11) + 1e-6) - 1.0
    df["f_max20_d0"] = g["high"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).max())
    df["f_max60_d0"] = g["high"].transform(lambda s: s.shift(1).rolling(60, min_periods=20).max())
    df["f_min20_d0"] = g["low"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).min())
    df["f_dd20_d0"] = df["f_d0_close"] / (df["f_max20_d0"] + 1e-6)
    df["f_dd60_d0"] = df["f_d0_close"] / (df["f_max60_d0"] + 1e-6)
    df["f_pos20_d0"] = (df["f_d0_close"] - df["f_min20_d0"]) / (df["f_max20_d0"] - df["f_min20_d0"] + 1e-6)
    df["f_vol_ma5_d0"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    df["f_d1_vol_ratio"] = df["amount"] / (df["f_vol_ma5_d0"] + 1e-6)
    df["zt_int"] = df["is_zt"].astype(int)
    df["f_zt_cnt_pre20"] = g["zt_int"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).sum())
    df["f_break60"] = (df["close"] >= df["f_max60_d0"] - 0.01).astype(int)

    # 首板封死干脆度
    df["d1_dip"] = (df["low"] - df["pre_c"]) / (df["pre_c"] + 1e-6)
    df["d1_entity"] = (df["close"] - df["open"]) / (df["pre_c"] + 1e-6)
    vol_ma5 = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    df["d1_vol_ratio"] = df["amount"] / (vol_ma5 + 1e-6)
    df["d1_seal_tightness"] = (
        (df["close"] == df["high"]).astype(int) * 30.0
        + np.clip(df["d1_dip"] * 100.0, -10.0, 10.0) * 1.5
        + np.clip(df["d1_entity"] * 100.0, 0.0, 10.0) * 2.0
        - np.where(df["d1_vol_ratio"] > 4.0, 15.0, 0.0)
    )

    print(f"  ✅ 成功补齐今日 {today_str} 全市场日线 {len(today_rows)} 只，基准日无缝前移至今日收盘！", flush=True)
    return df, True


def _fetch_today_plates_fallback(latest_dt: str) -> list:
    """若 KPL 尚未生成今日题材，从同花顺全量涨停池实时合成标准板块结构"""
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


def build_8y_purified_theme_metadata_complete(df: pd.DataFrame, latest_dt: str) -> tuple[dict, dict, list]:
    """
    8年动态题材与破冰新词历史元数据构建：
    合并 KPL 9年全量库 (<2021) + 5年全量库 (>=2021) + 近期增量 V2 + 当日同花顺 fallback。
    严格执行现行定版算法与三层假题材净化（TECH_PAT_TIMELESS）。
    """
    t0 = time.time()
    kpl_days_map = {}

    if os.path.exists(KPL_MERGED_PATH):
        for ln in open(KPL_MERGED_PATH, encoding="utf-8"):
            if ln.strip():
                try:
                    d = json.loads(ln)
                    dt = d.get("date", "")
                    if dt < "2021-01-01":
                        kpl_days_map[dt] = d
                except Exception:
                    pass

    if os.path.exists(KPL_5Y_PATH):
        for ln in open(KPL_5Y_PATH, encoding="utf-8"):
            if ln.strip():
                try:
                    d = json.loads(ln)
                    dt = d.get("date", "")
                    if dt >= "2021-01-01":
                        kpl_days_map[dt] = d
                except Exception:
                    pass

    if os.path.exists(KPL_V2_PATH):
        for ln in open(KPL_V2_PATH, encoding="utf-8"):
            if ln.strip():
                try:
                    d = json.loads(ln)
                    dt = d.get("date", "")
                    if dt:
                        if dt not in kpl_days_map or len(d.get("plates", [])) >= len(kpl_days_map[dt].get("plates", [])):
                            kpl_days_map[dt] = d
                except Exception:
                    pass

    # 检查 latest_dt 是否存在于 KPL 中，若无则调用同花顺 fallback
    if latest_dt not in kpl_days_map or len(kpl_days_map[latest_dt].get("plates", [])) == 0:
        today_plates = _fetch_today_plates_fallback(latest_dt)
        if today_plates:
            kpl_days_map[latest_dt] = {"date": latest_dt, "plates": today_plates}
            print(f"[fallback] 已通过同花顺涨停池合成今日 {latest_dt} 板块数: {len(today_plates)}")

    kpl_days = [kpl_days_map[k] for k in sorted(kpl_days_map.keys())]
    kpl_dt_set = {d["date"] for d in kpl_days}

    sub_df_kpl = df[df["dt_str"].isin(kpl_dt_set)][["dt_str", "c6", "is_zt", "touch_zt", "is_yizi", "pct", "mcap", "is_2b_plus"]]
    day_stock_map = {
        (r.dt_str, r.c6): (r.is_zt, r.touch_zt, r.is_yizi, r.pct, r.mcap, r.is_2b_plus)
        for r in sub_df_kpl.itertuples(index=False)
    }

    elo = defaultdict(lambda: 100.0)
    sub_elo = defaultdict(lambda: 100.0)
    plate_recent_zts = defaultdict(list)
    plate_last_idx, sub_last_idx = {}, {}
    prev_plate_stocks, prev_sub_stocks = {}, {}
    term_seen_days = Counter()
    term_first_dt, term_last_idx = {}, {}
    pioneer_word_history = defaultdict(set)
    stock_theme_meta = {}
    theme_board_latest = []

    for day_idx, d_entry in enumerate(kpl_days):
        dt = d_entry["date"]
        cutoff_15d = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=15)).isoformat()
        plates = d_entry.get("plates", [])

        # 主板块 Elo 更新
        for pname, c6_list in prev_plate_stocks.items():
            touches, seals, rets = 0, 0, []
            for c6 in c6_list:
                st = day_stock_map.get((dt, c6))
                if st is not None:
                    rets.append(st[3]); touches += int(st[1]); seals += int(st[0])
            if touches >= 2 and (seals / touches) < 0.50:
                elo[pname] -= 12.0 * ((touches - seals) / touches)
            elif rets and np.mean(rets) < -0.025:
                elo[pname] -= 10.0
            elif seals >= 2 and (seals / max(touches, 1)) >= 0.70:
                elo[pname] += min(10.0, 5.0 + seals * 1.2)
            elif rets and np.mean(rets) > 0.025:
                elo[pname] += 6.0

        # 细分分支 sub_elo 更新
        for sname, c6_list in prev_sub_stocks.items():
            touches, seals, rets = 0, 0, []
            for c6 in c6_list:
                st = day_stock_map.get((dt, c6))
                if st is not None:
                    rets.append(st[3]); touches += int(st[1]); seals += int(st[0])
            if touches >= 2 and (seals / touches) < 0.50:
                sub_elo[sname] -= 10.0 * ((touches - seals) / touches)
            elif rets and np.mean(rets) < -0.025:
                sub_elo[sname] -= 8.0
            elif seals >= 1 and (seals / max(touches, 1)) >= 0.70:
                sub_elo[sname] += min(9.0, 4.0 + seals * 1.5)
            elif rets and np.mean(rets) > 0.025:
                sub_elo[sname] += 5.0

        for p_k in list(elo.keys()):
            if day_idx - plate_last_idx.get(p_k, day_idx) > 3:
                elo[p_k] = 100.0 + (elo[p_k] - 100.0) * 0.85
        for s_k in list(sub_elo.keys()):
            if day_idx - sub_last_idx.get(s_k, day_idx) > 3:
                sub_elo[s_k] = 100.0 + (sub_elo[s_k] - 100.0) * 0.85

        new_prev_p, new_prev_sub = {}, defaultdict(list)
        plate_scores, plate_meta = {}, {}
        day_terms_to_commit = {}

        for p in plates:
            pname = p.get("plate", "")
            if pname in NON_THEME:
                continue
            stocks = p.get("stocks", [])
            sz = len(stocks)
            if sz == 0:
                continue

            c6_list = []
            n_ma = n_tech_t = n_earn = n_big = n_yizi = n_new = 0
            spark_b = 0.0
            n_2b_lead_cnt = 0

            sub_counts = Counter()
            for s in stocks:
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                if r_sh and r_sh not in NON_THEME:
                    sub_counts[r_sh] += 1

            for s in stocks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6_list.append(c6)
                st_info = day_stock_map.get((dt, c6))
                if st_info is not None and st_info[5]:
                    n_2b_lead_cnt += 1
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                r_lg = str(s[3]).strip() if len(s) > 3 else ""
                if r_sh and r_sh not in NON_THEME:
                    new_prev_sub[r_sh].append(c6)
                    sub_last_idx[r_sh] = day_idx
                txt = f"{pname} {r_sh} {r_lg}"
                if MA_PAT.search(txt): n_ma += 1
                if TECH_PAT_TIMELESS.search(txt): n_tech_t += 1
                if EARN_PAT.search(txt): n_earn += 1

                for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", txt):
                    w = norm_term(m.group(0))
                    if len(w) >= 3 and w not in NON_THEME:
                        pioneer_word_history[w].add(dt)

                for t in (split_terms(pname) | split_terms(r_sh)):
                    prev_cnt = term_seen_days[t]
                    prev_idx = term_last_idx.get(t, -9999)
                    f_dt = term_first_dt.get(t, dt)
                    if prev_cnt == 0 or f_dt >= cutoff_15d:
                        n_new += 1
                    elif 5 <= (day_idx - prev_idx) <= 45 and prev_cnt <= 5:
                        spark_b = max(spark_b, 6.0)
                    day_terms_to_commit[t] = dt
                st = day_stock_map.get((dt, c6))
                if st is not None:
                    if st[4] >= 150.0: n_big += 1
                    if st[2]: n_yizi += 1

            new_prev_p[pname] = c6_list
            plate_last_idx[pname] = day_idx

            past_climax_3_8 = any(
                z_cnt >= 5 for p_idx, z_cnt in plate_recent_zts[pname]
                if (day_idx - 8 <= p_idx <= day_idx - 3)
            )
            is_dying_pulse = bool(past_climax_3_8 and (n_2b_lead_cnt == 0))

            r5_zts = sum(cnt for idx_p, cnt in plate_recent_zts[pname] if day_idx - idx_p <= 5)
            plate_recent_zts[pname].append((day_idx, sz))
            sc_base = (
                elo[pname] + min(sz, 15) * 1.8 + min(r5_zts, 30) * 0.35
                + (8.0 if n_ma > 0 else 0.0) + (5.0 if n_new > 0 else 0.0)
                + spark_b + min(n_yizi * 4.0, 8.0) - (n_earn / sz) * 12.0 - (n_big / sz) * 10.0
            )
            sc_clean = sc_base + (6.0 if (TECH_PAT_TIMELESS.search(pname) or n_tech_t >= max(1, sz // 2)) else 0.0)
            plate_meta[pname] = (
                sc_clean, elo[pname], sz, n_yizi, n_new > 0, spark_b,
                n_tech_t, stocks, n_2b_lead_cnt > 0, is_dying_pulse, sub_counts
            )

        ranked_c = sorted(plate_meta.keys(), key=lambda k: plate_meta[k][0], reverse=True)
        rk_map_c = {k: i + 1 for i, k in enumerate(ranked_c)}
        top2_sc_c = plate_meta[ranked_c[1]][0] if len(ranked_c) >= 2 else 100.0

        # 当天若为最新交易日，固化板块看板
        if dt == latest_dt or day_idx == len(kpl_days) - 1:
            theme_board_latest = []
            for pname in ranked_c:
                sc_c, p_elo, sz, n_yz, has_new, spk, ntt, stocks, has_2b_lead, is_dying_p, sub_cnts = plate_meta[pname]
                rk_c = rk_map_c[pname]
                gap_c = (sc_c - top2_sc_c) if rk_c == 1 else 0.0
                theme_board_latest.append({
                    "plate": pname,
                    "score": round(float(sc_c), 2),
                    "elo": round(float(p_elo), 2),
                    "elo_rk": rk_c,
                    "score_gap_vs_top2": round(float(gap_c), 2),
                    "sz": int(sz),
                    "n_yizi": int(n_yz),
                    "has_new_term": bool(has_new),
                    "spark_bonus": float(spk),
                    "has_2b_lead": bool(has_2b_lead),
                    "is_event_basket": bool(pname in EVENT_BASKET_PLATES),
                    "is_broad_ind": bool(pname in BROAD_INDUSTRY_PLATES),
                    "is_dying_pulse": bool(is_dying_p),
                    "sub_counts": dict(sub_cnts),
                    "stocks": [str(s[1]).strip() for s in stocks[:8]],
                })

        for pname, m in plate_meta.items():
            sc_c, p_elo, sz, n_yz, has_new, spk, ntt, stocks, has_2b_lead, is_dying_p, sub_counts = m
            rk_c = rk_map_c[pname]
            gap_c = (sc_c - top2_sc_c) if rk_c == 1 else 0.0
            is_event_basket = bool(pname in EVENT_BASKET_PLATES)
            is_broad_ind = bool(pname in BROAD_INDUSTRY_PLATES)

            for s in stocks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                sname = str(s[1]).strip() if len(s) > 1 else ""
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                r_lg = str(s[3]).strip() if len(s) > 3 else ""
                txt = f"{pname} {r_sh} {r_lg}"
                own_new = any((term_seen_days[t] == 0 or term_first_dt.get(t, dt) >= cutoff_15d) for t in split_terms(r_sh + "+" + r_lg))
                s_elo = sub_elo[r_sh] if (r_sh and r_sh not in NON_THEME) else p_elo
                sub_cnt = sub_counts.get(r_sh, 1)

                cur = stock_theme_meta.get((dt, c6))
                if cur is None or sc_c > cur["t_score_c"]:
                    stock_theme_meta[(dt, c6)] = {
                        "name": sname, "plate": pname, "r_short": r_sh or pname,
                        "rk_c": rk_c, "t_score_c": sc_c, "gap_c": gap_c,
                        "p_elo": p_elo, "s_elo": s_elo, "p_sz": sz, "n_yizi": n_yz,
                        "has_new": has_new, "own_new": own_new, "spark": spk, "has_2b_lead": has_2b_lead,
                        "is_ma": bool(MA_PAT.search(txt)),
                        "is_tech_c": bool(TECH_PAT_TIMELESS.search(txt)),
                        "is_earn": bool(EARN_PAT.search(txt)),
                        "is_event_basket": is_event_basket,
                        "is_broad_ind": is_broad_ind,
                        "sub_cluster_cnt": sub_cnt,
                        "is_dying_pulse": is_dying_p,
                    }

        for t, dt_v in day_terms_to_commit.items():
            term_seen_days[t] += 1
            if t not in term_first_dt: term_first_dt[t] = dt_v
            term_last_idx[t] = day_idx
        prev_plate_stocks = new_prev_p
        prev_sub_stocks = new_prev_sub

    print(f"[Purified Metadata] 8年动态题材与破冰词构建完成: {len(stock_theme_meta):,} 条记录, 耗时 {time.time()-t0:.2f}s")
    return stock_theme_meta, pioneer_word_history, theme_board_latest


def build_cache(verbose: bool = True) -> dict:
    """从原始 Parquet 加载日线并现算 8 年动态题材与 S8 完整特征"""
    t0 = time.time()
    print("=" * 80)
    print(">>> [1/4] 从零加载 A 股原始日线与退市股底座...")
    df, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
    df, patched_today = _patch_today_daily_if_needed(df)

    latest_dt = str(df["dt_str"].max())
    all_dts = sorted(df["dt_str"].unique())
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    latest_idx = dt_to_idx[latest_dt]

    # 下一交易日识别与周一/节后识别
    now = datetime.datetime.now()
    d1_date_obj = datetime.date.fromisoformat(latest_dt)
    if latest_idx < len(all_dts) - 1:
        next_dt = all_dts[latest_idx + 1]
    else:
        # 顺延下一个自然交易日（周一至周五）
        cur_d = d1_date_obj + datetime.timedelta(days=1)
        while cur_d.weekday() >= 5:
            cur_d += datetime.timedelta(days=1)
        next_dt = cur_d.isoformat()

    gap_days = (datetime.date.fromisoformat(next_dt) - d1_date_obj).days
    is_monday = gap_days >= 3

    print(f">>> [2/4] 构建 8 年连续滚动动态题材与破冰先锋词元数据 (基准日: {latest_dt} | 下一交易日: {next_dt} | 周一加分={is_monday})...")
    stock_theme_meta, pioneer_word_history, theme_board = build_8y_purified_theme_metadata_complete(df, latest_dt)

    d1_df = df[df["dt_str"] == latest_dt].copy()
    fb_df = d1_df[d1_df["is_first_board"] & (~d1_df["is_yizi"])].copy().reset_index(drop=True)
    c6_tuple = tuple(fb_df["c6"].unique().tolist())

    print(f">>> [3/4] 只读挂载公告库、微观盘口与 PIT 机构调研 (首板候选 {len(fb_df)} 只)...")
    # 1. 公告库只读检索 ([d1 - 4天, 当前时刻])
    notice_start = (d1_date_obj - datetime.timedelta(days=4)).isoformat()
    notice_end = f"{next_dt} 09:25:00"
    stock_notices = defaultdict(lambda: {"notice_hard": False, "notice_bad": False, "notice_ma": False, "notice_earn": False, "notice_neg": False, "titles": []})

    if c6_tuple and os.path.exists(NOTICES_DB_PATH):
        try:
            conn = sqlite3.connect(f"file:{NOTICES_DB_PATH}?mode=ro", uri=True)
            placeholders = ",".join(["?"] * len(c6_tuple))
            q = f"SELECT code, ndate, title FROM notice WHERE ndate >= ? AND ndate <= ? AND code IN ({placeholders})"
            for code, ndate, title in conn.execute(q, (notice_start, notice_end[:10], *c6_tuple)).fetchall():
                c6 = str(code).strip()[:6]
                ts = str(title or "").strip()
                info = stock_notices[c6]
                is_neg = bool(NEG_NOTICE_PAT.search(ts))
                is_bad = bool(BAD_NOTICE_PAT.search(ts))
                if is_neg: info["notice_neg"] = True
                if is_bad: info["notice_bad"] = True
                if HARD_NOTICE_PAT.search(ts) and not is_neg and not is_bad: info["notice_hard"] = True
                if MA_NOTICE_PAT.search(ts) and not is_neg and not is_bad: info["notice_ma"] = True
                if EARN_NOTICE_PAT.search(ts): info["notice_earn"] = True
                if len(info["titles"]) < 3: info["titles"].append(f"[{ndate}] {ts[:45]}")
            conn.close()
        except Exception as e:
            print(f"  ⚠️ notices.db 查询异常: {e}")

    if c6_tuple and os.path.exists(PIT_NOTICES_DB_PATH):
        try:
            conn_pit = sqlite3.connect(f"file:{PIT_NOTICES_DB_PATH}?mode=ro", uri=True)
            placeholders = ",".join(["?"] * len(c6_tuple))
            cutoff_pit = f"{next_dt} 09:25:00"
            q_pit = f"SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst >= ? AND pub_datetime_cst <= ? AND sec_code IN ({placeholders})"
            for code, pub_dt, title in conn_pit.execute(q_pit, (notice_start, cutoff_pit, *c6_tuple)).fetchall():
                c6 = str(code).strip()[:6]
                ts = str(title or "").strip()
                info = stock_notices[c6]
                is_neg = bool(NEG_NOTICE_PAT.search(ts))
                is_bad = bool(BAD_NOTICE_PAT.search(ts))
                if is_neg: info["notice_neg"] = True
                if is_bad: info["notice_bad"] = True
                if HARD_NOTICE_PAT.search(ts) and not is_neg and not is_bad: info["notice_hard"] = True
                if MA_NOTICE_PAT.search(ts) and not is_neg and not is_bad: info["notice_ma"] = True
                if EARN_NOTICE_PAT.search(ts): info["notice_earn"] = True
                entry = f"[{str(pub_dt)[:10]}] {ts[:45]}"
                if len(info["titles"]) < 3 and entry not in info["titles"]: info["titles"].append(entry)
            conn_pit.close()
        except Exception as e:
            print(f"  ⚠️ cninfo_notices_5y_pit.db 查询异常: {e}")

    # 2. 首板微观盘口
    tape_map = {}
    if c6_tuple and os.path.exists(MICRO_TAPE_DB_PATH):
        try:
            conn_tp = sqlite3.connect(f"file:{MICRO_TAPE_DB_PATH}?mode=ro", uri=True)
            ph = ",".join(["?"] * len(c6_tuple))
            for sc, fst, obc in conn_tp.execute(
                f"SELECT sec_code, first_seal_time, open_board_count FROM zt_micro_tape WHERE trade_date = ? AND sec_code IN ({ph})",
                (latest_dt, *c6_tuple),
            ).fetchall():
                tape_map[str(sc)[:6]] = (str(fst or "99:99:99"), int(obc or 0))
            conn_tp.close()
        except Exception:
            pass

    ths_daily_p = f"{SIM_DIR}/data/ths_limit_up_daily/{latest_dt}.json"
    if os.path.exists(ths_daily_p):
        try:
            ths_j = json.load(open(ths_daily_p, encoding="utf-8"))
            for it in ths_j.get("stocks", []):
                c6_t = str(it.get("code", ""))[:6]
                if c6_t and c6_t not in tape_map:
                    fts = it.get("first_limit_up_time")
                    fstr = datetime.datetime.fromtimestamp(int(fts)).strftime("%H:%M:%S") if fts else "99:99:99"
                    tape_map[c6_t] = (fstr, int(it.get("open_num") or 0))
        except Exception:
            pass

    # 3. 严格 PIT 机构调研 (< D2 09:25:00 CST 且 0 <= (D2 - pub_date).days <= 8)
    ir_set = set()
    if c6_tuple and os.path.exists(IR_QA_DB_PATH):
        try:
            conn_ir = sqlite3.connect(f"file:{IR_QA_DB_PATH}?mode=ro", uri=True)
            ph = ",".join(["?"] * len(c6_tuple))
            ir_start = (datetime.date.fromisoformat(next_dt) - datetime.timedelta(days=8)).isoformat()
            ir_end = f"{next_dt} 09:25:00"
            for (sc,) in conn_ir.execute(
                f"SELECT DISTINCT sec_code FROM ir_qa WHERE pub_datetime_cst >= ? AND pub_datetime_cst <= ? AND sec_code IN ({ph})",
                (ir_start, ir_end, *c6_tuple),
            ).fetchall():
                ir_set.add(str(sc)[:6])
            conn_ir.close()
        except Exception:
            pass

    # 情绪指标
    seal_r = float(seal_rate_map.get(latest_dt, 0.55))
    dt_cnt = int(dt_cnt_map.get(latest_dt, 5))
    zt_cnt = int(zt_cnt_map.get(latest_dt, 50))
    promo5 = float(promo_ma5_map.get(latest_dt, 0.20))
    tot_thr = 329.8 if seal_r > 0.75 else 304.8

    # 候选股遍历打分
    print(f">>> [4/4] 逐股严格按 V16 完全体对齐计算先验题材分(含纯外行扣20分)、筹码底分与三层净化门...")
    csrc_map = load_csrc_ind_map()
    candidates = []
    for _, r in fb_df.iterrows():
        c6 = r["c6"]
        ti = stock_theme_meta.get(
            (latest_dt, c6),
            {
                "name": "", "plate": "其他", "r_short": "其他",
                "rk_c": 99, "t_score_c": 95.0, "gap_c": 0.0,
                "p_elo": 100.0, "s_elo": 100.0, "p_sz": 1, "n_yizi": 0,
                "has_new": False, "own_new": False, "spark": 0.0, "has_2b_lead": False,
                "is_ma": False, "is_tech_c": False, "is_earn": False,
                "is_event_basket": False, "is_broad_ind": False,
                "sub_cluster_cnt": 1, "is_dying_pulse": False,
            }
        )
        n_info = stock_notices[c6]
        sname = ti["name"] or str(r.get("name", ""))
        is_st = "ST" in sname.upper() or "退" in sname
        notice_bad = bool(n_info["notice_bad"] or n_info["notice_neg"])
        notice_neg = bool(n_info["notice_neg"])
        notice_hard = bool(n_info["notice_hard"]) and (not notice_bad)
        is_ma = bool((ti["is_ma"] or n_info["notice_ma"]) and (not notice_bad))
        is_tech = bool(ti["is_tech_c"])
        is_earn = bool(ti["is_earn"] or n_info["notice_earn"])

        rk_c = int(ti["rk_c"])
        p_sz = int(ti["p_sz"])
        has_new_term = bool(ti["has_new"])
        own_new = bool(ti["own_new"])
        spark_bonus = float(ti["spark"])
        gap_c = float(ti["gap_c"])
        t_score_c = float(ti["t_score_c"])
        s_elo = float(ti["s_elo"])
        has_2b_lead = bool(ti["has_2b_lead"])
        is_event_basket = bool(ti["is_event_basket"])
        is_broad_ind = bool(ti["is_broad_ind"])
        is_dying_pulse = bool(ti["is_dying_pulse"])
        sub_cluster_cnt = int(ti["sub_cluster_cnt"])

        # 破冰先锋词历史 (1 <= len(prior) <= 3)
        r_txt = str(ti.get("r_short", "")) + " " + str(sname)
        is_pioneer_word = False
        for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", r_txt):
            w = norm_term(m.group(0))
            if w in pioneer_word_history:
                prior = [d_seen for d_seen in pioneer_word_history[w] if d_seen <= latest_dt]
                if 1 <= len(prior) <= 3:
                    is_pioneer_word = True
                    break

        s_prior_dual = (
            (28 if rk_c == 1 else (16 if rk_c == 2 else (8 if rk_c == 3 else 0)))
            + (18 if p_sz >= 4 else (10 if p_sz >= 2 else -15))
            + (12 if has_new_term else 0) + (8 if own_new else 0) + (10 if spark_bonus > 0 else 0)
            + (18 if notice_hard else 0) + (18 if is_ma else 0) + (12 if is_tech else 0)
            + (12 if gap_c >= 20.0 else 0)
            + float(np.clip((t_score_c - 100.0) * 0.25, 0.0, 25.0))
            + float(np.clip((s_elo - 100.0) * 0.35, -10.0, 18.0))
        )

        is_granularity = is_pioneer_word or has_new_term or own_new or (sub_cluster_cnt >= 2)
        bonus_spear = (15.0 if is_granularity else 0.0) + (10.0 if s_elo >= 105.0 else (-10.0 if s_elo <= 95.0 else 0.0))
        # V17 剪除规则 1: f3_bonus 去掉 notice_hard 二次 +8.0 分 (仅保留 s_prior_dual 里的 +18 分与 notice_bad -35.0 分)
        f3_bonus = -35.0 if notice_bad else 0.0
        wk_add = 10.0 if is_monday else 0.0

        # V16 名字与主业调性只做减法：硬科技题材无并购纯外行扣 20 分，好名字零虚加分
        csrc_ind = str(csrc_map.get(c6, ""))
        csrc_sec = csrc_ind[:3] if csrc_ind else "UNK"
        is_hard_tech = bool(re.search(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)", ti["plate"]))
        is_pure_outsider = bool(is_hard_tech and (csrc_sec in CSRC_PURE_OUTSIDER) and (not (notice_hard or is_ma)))
        name_pen = -20.0 if is_pure_outsider else 0.0

        s_prior_wk = s_prior_dual + bonus_spear + wk_add + f3_bonus + name_pen

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
        brk60 = int(r["f_break60"])
        d1_tightness = float(r["d1_seal_tightness"]) if pd.notna(r["d1_seal_tightness"]) else 0.0

        # S8 筹码底分 (超跌最高档削顶至 32 分)
        sc_mcap = 28 if 60 <= mcap <= 155 else (10 if 40 <= mcap < 60 else (-20 if mcap < 35 else 0))
        sc_amt = 18 if 2.2e8 <= amt <= 15e8 else (-25 if amt < 1.8e8 else -10)
        sc_dd20 = 32 if dd20 <= 0.86 else (18 if dd20 <= 0.90 else (-40 if dd20 > 0.95 else 0))
        sc_dd60 = 18 if dd60 <= 0.76 else (10 if dd60 <= 0.82 else (-15 if dd60 > 0.92 else 0))
        sc_nshape = 22 if (zt_pre20 >= 1 and dd20 <= 0.86) else (-20 if (zt_pre20 >= 1 and dd20 > 0.92) else 0)
        sc_pos20 = 25 if pos20 <= 0.30 else (12 if pos20 <= 0.45 else (-35 if pos20 > 0.75 else 0))
        sc_d0 = 25 if d0_pct <= -0.010 else (15 if d0_pct <= 0.005 else (-35 if d0_pct > 0.030 else 0))
        sc_ret10 = 15 if ret10 <= 0.05 else (-35 if ret10 > 0.18 else 0)
        sc_to = 15 if to <= 9.0 else (8 if to <= 15.0 else (-25 if to > 18.0 else 0))
        sc_vol = 15 if vol_ratio <= 1.75 else (-15 if vol_ratio > 2.3 else 0)
        sc_mkt_seal = 18 if seal_r < 0.64 else (-25 if seal_r >= 0.72 else 0)
        sc_mkt_dt = 12 if dt_cnt <= 6 else (-15 if dt_cnt >= 15 else 0)
        sc_mkt_zt = 12 if zt_cnt >= 45 else (-18 if zt_cnt < 35 else 0)

        s_q_base_orig = (
            sc_mcap + sc_amt + sc_dd20 + sc_dd60 + sc_nshape + sc_pos20
            + sc_d0 + sc_ret10 + sc_to + sc_vol + sc_mkt_seal + sc_mkt_dt + sc_mkt_zt
        )
        clean_brk60 = (brk60 == 1) and (ret10 <= 0.08) and (zt_pre20 == 0) and (to <= 14.0)
        s_q_base_dual = (
            sc_mcap + sc_amt + 24 + sc_d0 + sc_ret10 + sc_to + sc_vol
            + sc_mkt_seal + sc_mkt_dt + sc_mkt_zt
        ) if clean_brk60 else s_q_base_orig

        # S5 首板早盘1次开板硬换手加5分 + S6 盘前8日机构调研加5分
        fst_t, ob_cnt = tape_map.get(c6, ("99:99:99", 0))
        is_ht = (ob_cnt == 1) and (fst_t <= "10:30:00") and (d1_tightness >= 38.0)
        has_ir = c6 in ir_set
        s_q_base = s_q_base_dual + (5.0 if is_ht else 0.0) + (5.0 if has_ir else 0.0)

        # 过滤条件 (V17 剪除规则 3: 去掉宽泛旧行业独立拦截，仅保留 not is_event_basket)
        pass_l1 = not is_event_basket
        pass_l2 = not is_dying_pulse
        pass_ac = (p_sz <= 35) and (not notice_bad)
        p_tight = d1_tightness >= 37.0

        gate_ok = bool(
            (not is_st)
            and (not bool(r["is_yizi"]))
            and (not is_earn)
            and (not notice_bad)
            and (18.0 <= mcap <= 220.0)
            and (to <= 20.0)
            and (not (zt_pre20 >= 4 and pos20 > 0.38))
            and (float(r["close"]) <= 60.0)
        )
        purifier_ok = bool(gate_ok and pass_l1 and pass_l2 and pass_ac and p_tight)

        static_tot = float(s_prior_wk + s_q_base)
        # V17 剪除规则 4: 去掉 s_quant >= 150.0 限制，竞价需求仅由总分门槛 tot_thr 决定
        need_auc = int(max(0, np.ceil(tot_thr - static_tot)))

        candidates.append({
            "ticker": str(r["ticker"]),
            "c6": c6,
            "name": sname,
            "d1_date": latest_dt,
            "next_dt": next_dt,
            "gap_days": gap_days,
            "is_monday": is_monday,
            "pre_c": round(float(r["close"]), 2),
            "mcap": round(mcap, 2),
            "amount_yi": round(amt / 1e8, 2),
            "to": round(to, 2),
            "is_yizi": bool(r["is_yizi"]),
            "is_st": is_st,
            "plate": ti["plate"],
            "r_short": ti.get("r_short", ""),
            "elo_rk": rk_c,
            "theme_score": round(t_score_c, 2),
            "elo": round(float(ti["p_elo"]), 2),
            "s_elo": round(float(s_elo), 2),
            "p_sz": p_sz,
            "sub_cluster_cnt": sub_cluster_cnt,
            "has_new_term": has_new_term,
            "own_new": own_new,
            "is_pioneer_word": is_pioneer_word,
            "spark_bonus": spark_bonus,
            "has_2b_lead": has_2b_lead,
            "is_event_basket": is_event_basket,
            "is_broad_ind": is_broad_ind,
            "is_dying_pulse": is_dying_pulse,
            "pass_l1": pass_l1,
            "pass_l2": pass_l2,
            "pass_ac": pass_ac,
            "p_tight": p_tight,
            "purifier_ok": purifier_ok,
            "is_ht": is_ht,
            "has_ir": has_ir,
            "clean_brk60": bool(clean_brk60),
            "d1_tightness": round(d1_tightness, 1),
            "is_ma": is_ma,
            "is_tech": is_tech,
            "is_earn": is_earn,
            "notice_hard": notice_hard,
            "notice_bad": notice_bad,
            "notice_neg": notice_neg,
            "notice_titles": n_info["titles"],
            "dd20_d0": round(dd20, 3),
            "dd60_d0": round(dd60, 3),
            "pos20_d0": round(pos20, 3),
            "d0_pct": round(d0_pct, 4),
            "ret_pre10": round(ret10, 4),
            "vol_ratio": round(vol_ratio, 2),
            "zt_cnt_pre20": zt_pre20,
            "csrc_ind": csrc_ind,
            "is_pure_outsider": is_pure_outsider,
            "name_pen": name_pen,
            "s_prior_dual": round(float(s_prior_dual), 1),
            "s_prior_wk": round(float(s_prior_wk), 1),
            "s_q_base_dual": round(float(s_q_base_dual), 1),
            "s_q_base": round(float(s_q_base), 1),
            "static_tot": round(static_tot, 1),
            "need_auc": need_auc,
            "gate_ok": gate_ok,
        })

    # 计算动态题材日排名 rk_theme 与题材中位数 p_theme_med (用于拦截第4名及以后冷门题材篡位)
    valid_p = [c for c in candidates if c["plate"] != "其他" and (not c["is_event_basket"]) and c["p_sz"] >= 2]
    p_med_map = defaultdict(list)
    p_sz_map = {}
    for c in valid_p:
        p_med_map[c["plate"]].append(c["s_prior_dual"])
        p_sz_map[c["plate"]] = c["p_sz"]
    p_med_sorted = sorted(p_med_map.keys(), key=lambda k: float(np.median(p_med_map[k])), reverse=True)
    rk_theme_map = {k: i + 1 for i, k in enumerate(p_med_sorted)}
    for c in candidates:
        c["rk_theme"] = rk_theme_map.get(c["plate"], 99)
        c["p_theme_med"] = float(round(np.median(p_med_map[c["plate"]]), 2)) if c["plate"] in p_med_map else 0.0

    # V17 规则 α 与 规则 β: 题材结构预判
    t1_plate = p_med_sorted[0] if len(p_med_sorted) >= 1 else ""
    t2_plate = p_med_sorted[1] if len(p_med_sorted) >= 2 else ""
    t3_plate = p_med_sorted[2] if len(p_med_sorted) >= 3 else ""

    t1_med = float(np.median(p_med_map[t1_plate])) if t1_plate else 0.0
    t2_med = float(np.median(p_med_map[t2_plate])) if t2_plate else 0.0
    t3_med = float(np.median(p_med_map[t3_plate])) if t3_plate else 0.0

    t1_sz = p_sz_map.get(t1_plate, 0)
    t2_sz = p_sz_map.get(t2_plate, 1)
    t3_sz = p_sz_map.get(t3_plate, 1)

    is_dominant_t1 = bool((t1_med - t2_med >= 20.0) or ((t1_sz >= 6) and (t1_sz / max(1, t2_sz) >= 2.0)))

    is_melee = False
    if t1_plate and t2_plate and t3_plate:
        sz_max = max(t1_sz, t2_sz, t3_sz)
        sz_min = min(t1_sz, t2_sz, t3_sz)
        if (t1_med - t3_med <= 15.0) and (sz_max <= 5) and (sz_min >= 2):
            is_melee = True

    # V17 规则 γ: 前视滚动20日高开封板率传感器 (roll20_ho_zt)
    fb_hist = df[df["is_first_board"] & (~df["is_yizi"]) & df["d2_dt"].notna() & (df["d2_dt"] <= latest_dt)].copy()
    fb_hist["is_buyable_open"] = (fb_hist["d2_o_pct"] > -0.90) & (~fb_hist["d2_is_yizi"])
    daily_ho_records = []
    for d, grp in fb_hist.groupby("d2_dt"):
        mkt_open_avg = grp[grp["is_buyable_open"]]["d2_o_pct"].mean()
        p_ma5 = promo_ma5_map.get(d, 0.20)
        is_nuclear = mkt_open_avg < 0.0
        is_freeze = p_ma5 < 0.13
        buyable = grp[grp["is_buyable_open"] & (~is_nuclear) & (~is_freeze)]
        ho = buyable[buyable["d2_o_pct"] >= 0.055]
        n_ho = len(ho)
        rate_ho_zt = (ho["d2_is_zt"].sum() / n_ho) if n_ho > 0 else np.nan
        daily_ho_records.append({"date": d, "rate_ho_zt": rate_ho_zt})
    df_daily_s = pd.DataFrame(daily_ho_records).sort_values("date").reset_index(drop=True)
    df_daily_s["roll20_ho_zt"] = df_daily_s["rate_ho_zt"].shift(1).rolling(20, min_periods=5).mean().fillna(0.45)
    roll20_ho_zt = float(df_daily_s["roll20_ho_zt"].iloc[-1]) if len(df_daily_s) > 0 else 0.45

    candidates.sort(key=lambda x: (x["purifier_ok"] and x["s_prior_wk"] >= 38.0, x["static_tot"]), reverse=True)

    cache_obj = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "V17_249x_MASTER_PROD_20261112",
        "d1_date": latest_dt,
        "next_dt": next_dt,
        "gap_days": gap_days,
        "is_monday": is_monday,
        "patched_today_from_tencent": patched_today,
        "mkt_sentiment": {
            "d1_zt_cnt": zt_cnt,
            "d1_dt_cnt": dt_cnt,
            "d1_1to2_seal_rate": round(seal_r, 3),
            "d1_1to2_promo_ma5": round(promo5, 4),
            "roll20_ho_zt": round(roll20_ho_zt, 4),
            "tot_thr": tot_thr,
        },
        "theme_structure": {
            "is_dominant_t1": is_dominant_t1,
            "dom_t1_plate": t1_plate,
            "is_melee": is_melee,
            "t1_med": round(t1_med, 2),
            "t2_med": round(t2_med, 2),
            "t3_med": round(t3_med, 2),
            "t1_sz": t1_sz,
            "t2_sz": t2_sz,
            "t3_sz": t3_sz,
            "themes": {
                p: {
                    "p_theme_med": round(float(np.median(p_med_map[p])), 2),
                    "p_sz": p_sz_map.get(p, 0),
                    "rk_theme": rk_theme_map.get(p, 99)
                }
                for p in p_med_sorted
            }
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
            f"[build-cache] 基准首板日={latest_dt} -> 下一交易日={next_dt} (周一加分={is_monday}) | "
            f"题材数={len(theme_board)} | 首板候选={len(candidates)} "
            f"(净化全过且先验>=38分: {sum(1 for c in candidates if c['purifier_ok'] and c['s_prior_wk'] >= 38)}只) | "
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
    next_dt = cache_obj.get("next_dt", "")
    gap_days = cache_obj.get("gap_days", 1)
    is_monday = cache_obj.get("is_monday", gap_days >= 3)
    gen_at = cache_obj.get("generated_at", "")
    mkt = cache_obj.get("mkt_sentiment", {})
    themes = cache_obj.get("theme_board", [])
    cands = cache_obj.get("candidates", [])

    d1_seal_rate = float(mkt.get("d1_1to2_seal_rate", 0.55))
    promo_ma5 = float(mkt.get("d1_1to2_promo_ma5", 0.20))
    tot_thr = float(mkt.get("tot_thr", 304.8))
    roll20 = float(mkt.get("roll20_ho_zt", 0.45))
    gate_note = "【高潮次日保护已触发：门槛提至 329.8 分】" if tot_thr > 310 else "【常规生效门槛：304.8 分】"
    roll20_str = f"前视高开封板率 roll20_ho_zt={roll20*100:.1f}% -> " + ("【传感器触发弱开加重惩罚: <3.5%扣25分】" if roll20 < 0.45 else "常规弱开: <3.1%扣15分")
    wk_note = "【已识别周一/节后窗口：题材先验自动包含周一 +10 分，放宽子通道 mmon 就绪】" if is_monday else f"【常规交易日：{roll20_str}】"

    print(f"=== 一进二生产主策略 V17 定版盘前预评分 (基准首板日: {d1_date} | 下一交易日: {next_dt} | 生成: {gen_at}) ===")
    print(
        f"市场情绪底分项: D1涨停={mkt.get('d1_zt_cnt')}家 | D1跌停={mkt.get('d1_dt_cnt')}家 | "
        f"D1一进二封板率={d1_seal_rate*100:.1f}% | 近5日自然晋级率MA5={promo_ma5*100:.1f}% | 生效总分门槛={tot_thr:.1f}分 {gate_note}\n"
        f"日期与前视生态: 间隔 {gap_days} 天 {wk_note}"
    )
    if promo_ma5 < 0.13:
        print(f"⚠️ 近5日全市场一进二自然晋级率 {promo_ma5*100:.1f}% < 13.0%（极端冰点熔断线），明日严禁开仓！")

    theme_struct = cache_obj.get("theme_structure", {})
    if theme_struct.get("is_dominant_t1"):
        print(f"🔥【规则 α 预警】断层第一题材【{theme_struct.get('dom_t1_plate')}】领先显著，若该题材内无过线头名股，自动拦截第3题材标的")
    if theme_struct.get("is_melee"):
        print(f"⚔️【规则 β 预警】前三大题材势均力敌混战日 (极差<=15分且规模2~5家)，候选股必须卡全场竞价前二或具备公告硬催化/并购")

    print("\n【一、今日题材热度 Top 10 打分表（净化纯洁分 sc_clean 排序）】")
    for t in themes[:10]:
        purifier_tags = []
        if t.get("is_event_basket"): purifier_tags.append("❌事件大筐拦截")
        if t.get("is_broad_ind"): purifier_tags.append("⚠️宽泛行业")
        if t.get("is_dying_pulse"): purifier_tags.append("❌退潮一日游脉冲拦截")
        if t.get("has_new_term"): purifier_tags.append("15日新词")
        if t.get("spark_bonus", 0) > 0: purifier_tags.append("星火+10")
        if t.get("has_2b_lead"): purifier_tags.append("连板龙在场")
        tag_str = f" [{' '.join(purifier_tags)}]" if purifier_tags else ""
        print(
            f"  #{t['elo_rk']:02d} {t['plate']:<10s} | 综合纯洁分={t['score']:6.1f} (主Elo={t['elo']:5.1f}) | "
            f"首板家数={t['sz']:2d} (一字={t['n_yizi']}) | 龙头={','.join(t.get('stocks', [])[:3])}{tag_str}"
        )

    valid_cands = [c for c in cands if c.get("purifier_ok") and c.get("s_prior_wk", 0) >= (38.0 if is_monday else 45.0)]
    valid_cands.sort(key=lambda x: x["static_tot"], reverse=True)
    print(
        f"\n【二、过硬门槛且题材纯洁候选股盘前预评分排行（共 {len(valid_cands)} 只，当前生效门槛: {tot_thr:.1f} 分）】"
    )
    for i, c in enumerate(valid_cands, 1):
        tags = []
        if c.get("is_pioneer_word"): tags.append("破冰先锋词+15")
        elif c.get("has_new_term"): tags.append("先锋新词+12")
        elif c.get("own_new"): tags.append("专属新词+8")
        if c.get("is_tech"): tags.append("前沿科技+12")
        if c.get("is_ma"): tags.append("重组/合同+18")
        if c.get("notice_hard"): tags.append("硬催化+18")
        if c.get("clean_brk60"): tags.append("60日平台首突+24")
        if c.get("is_ht"): tags.append("首板硬换手+5")
        if c.get("has_ir"): tags.append("机构调研+5")
        if c.get("d1_tightness", 0) >= 37.0: tags.append(f"早盘紧封{c['d1_tightness']:.0f}")
        if c.get("name_pen", 0.0) < 0: tags.append("❌硬科技纯外行-20")
        tag_str = f" [{','.join(tags)}]" if tags else ""
        req_desc = _auc_requirement_desc(c["need_auc"])
        print(
            f"  {i:02d}. {c['ticker']} {c['name']:<6s} | {c['plate']:<8s}(#{c['elo_rk']} sub_elo={c.get('s_elo', c['elo']):.1f}) | "
            f"静态总分={c['static_tot']:5.0f} (题材={c['s_prior_wk']:3.0f} + 筹码={c['s_q_base']:4.0f}) | "
            f"市值={c['mcap']:5.1f}亿 换手={c['to']:4.1f}% 回撤dd20={c['dd20_d0']:.2f}{tag_str}\n"
            f"      └─ {req_desc}"
        )

    print("\n【一进二现行定版离场铁律】")
    print("  1. 买入日未封板：收红且次日 09:25 集合竞价高开 >= +0.5% (且非一字跌停) 才留仓博弱转强；低开或收绿或次日高开不足 0.5%，次日 09:25 集合竞价直接全清！")
    print("  2. 买入日封死二板 (或弱转强封板后)：第 3 天起，只在 10:30 看一眼分时线：")
    print("     - 若 10:30 封死涨停：洗盘不动；但若 14:30 之后炸板，抢跑清仓；若收盘封住则继续持有；")
    print("     - 若 10:30 未封板且跌破分时均价线 (VWAP)：10:35 立即全卖离场；")
    print("     - 若 10:30 站上分时均价线：拿至收盘 (若收盘未封板且未触发免死则 15:00 收盘清仓；满 3 板断板且收涨 >= +2% 免死多拿 1 天)。")
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

    d1_dt_str = cache_obj.get("d1_date", "")
    today_d = datetime.date.today()
    try:
        gap_days = (today_d - datetime.date.fromisoformat(d1_dt_str)).days if d1_dt_str else 1
    except Exception:
        gap_days = 1
    is_monday = gap_days >= 3

    mkt = cache_obj.get("mkt_sentiment", {})
    d1_seal_rate = float(mkt.get("d1_1to2_seal_rate", 0.55))
    promo_ma5 = float(mkt.get("d1_1to2_promo_ma5", 0.20))
    tot_thr = float(mkt.get("tot_thr", 329.8 if d1_seal_rate > 0.75 else 304.8))
    gate_note = "【高潮次日保护触发：门槛 329.8 分】" if tot_thr > 310 else "【常规门槛：304.8 分】"

    promo_freeze = False
    if promo_ma5 < 0.13:
        promo_freeze = True
        print(f"⚠️ 近5日全市场一进二自然晋级率 {promo_ma5*100:.1f}% < 13.0%（极端冰点熔断线），全天空仓")

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
            lp = float(p[34] or 0) or op
            live[k[-6:]] = {
                "name": p[1],
                "pre": float(p[4] or 0),
                "open": op,
                "high": float(p[33] or 0),
                "low": lp,
                "cur": float(p[3] or 0),
            }

    for c in cands:
        lv = live.get(c["c6"], {})
        pre = lv.get("pre") or c["pre_c"]
        op = lv.get("open", 0)
        lp = lv.get("low", op)
        c["o_pct"] = (op / pre - 1.0) if (op > 0 and pre > 0) else -0.99
        c["open_p"] = op
        c["high_p"] = lv.get("high", 0)
        c["cur_p"] = lv.get("cur", 0)
        zt_p = float(np.floor(pre * 1.10 * 100 + 0.5) / 100)
        c["zt_p"] = zt_p
        c["d2_is_yizi"] = bool(op >= zt_p - 0.01 and lp >= zt_p - 0.01)
        c["is_buyable_open"] = bool(c.get("gate_ok", False) and op > 0 and op < zt_p - 0.005)
        c["trig_p"] = min(zt_p, max(round(op * 1.012, 2), round(pre * 1.065, 2))) if op > 0 else zt_p

    df = pd.DataFrame(cands)
    valid_opens = df[df["open_p"] > 0]["o_pct"]
    prev_zt_auc_avg = float(valid_opens.mean()) if len(valid_opens) > 0 else 0.0
    nuclear_halt = False
    if len(valid_opens) > 0 and prev_zt_auc_avg < 0.0:
        nuclear_halt = True
        print(f"⚠️ 今日昨日首板竞价均值 {prev_zt_auc_avg*100:+.2f}% < 0%，触发核按钮保护，全天空仓")

    # 兜底：若缓存中尚未包含 name_pen，动态读取证监会行业补充计算
    if "name_pen" not in df.columns:
        csrc_map = load_csrc_ind_map()
        name_pens = []
        for _, r_cand in df.iterrows():
            c6_t = str(r_cand["c6"])
            cs_ind = str(csrc_map.get(c6_t, ""))
            cs_sec = cs_ind[:3] if cs_ind else "UNK"
            ht = bool(re.search(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)", str(r_cand.get("plate", ""))))
            hm = bool(r_cand.get("notice_hard") or r_cand.get("is_ma"))
            is_out = bool(ht and (cs_sec in CSRC_PURE_OUTSIDER) and (not hm))
            name_pens.append(-20.0 if is_out else 0.0)
        df["name_pen"] = name_pens
    else:
        df["name_pen"] = df["name_pen"].fillna(0.0)

    # 1. 前排锁筹数 (front_lock_cnt) 与全场一字数 (mkt_yizi_cnt)
    is_front_lock = df["d2_is_yizi"] | (
        (not is_monday) & (df["o_pct"] > 0.078)
    ) | (
        is_monday & (df["o_pct"] > 0.088)
    )
    df["_is_front_lock"] = is_front_lock.astype(int)
    df["front_lock_cnt"] = df.groupby("plate")["_is_front_lock"].transform("sum")
    df["plate_d2_yizi_cnt"] = df.groupby("plate")["d2_is_yizi"].transform("sum")
    mkt_yizi_cnt = int(df["d2_is_yizi"].sum())
    df["mkt_yizi_cnt"] = mkt_yizi_cnt

    # 2. 真实可买窗口内部排换手名次 (true_buy_rk)
    in_std_buy_win = df["is_buyable_open"] & (
        (is_monday & df["o_pct"].between(0.020, 0.088))
        | ((not is_monday) & df["o_pct"].between(0.022, 0.078))
    )
    df["_true_buy_o"] = np.where(in_std_buy_win, df["o_pct"], -9.99)
    df["true_buy_rk"] = df.groupby("plate")["_true_buy_o"].rank(ascending=False, method="min")

    df["_buy_o"] = np.where(df["is_buyable_open"], df["o_pct"], -9.99)
    df["mkt_open_rk"] = df["_buy_o"].rank(ascending=False, method="min")
    df["theme_open_rk"] = df.groupby("plate")["_buy_o"].rank(ascending=False, method="min")
    df["subbranch_rk"] = df.groupby(["plate", "r_short"])["_buy_o"].rank(ascending=False, method="min")
    p2 = df.groupby("plate")["_buy_o"].transform(lambda s: s.nlargest(2).iloc[-1] if (s > -1.0).sum() >= 2 else -0.05)
    df["open_lead"] = np.where(df["true_buy_rk"] == 1, df["o_pct"] - p2, 0.0)

    # 3. 真实排位奖励加分 (基于 true_buy_rk)
    has_sub = (df["p_sz"] >= 8) & (df["r_short"] != df["plate"]) & (df["r_short"] != "其他") & (df["r_short"] != "")
    rk_bon = np.where(
        df["true_buy_rk"] == 1, 35.0,
        np.where(has_sub & (df["subbranch_rk"] == 1), 24.0, np.where(df["true_buy_rk"] == 2, 8.0, -25.0))
    )

    # 4. 前排一字细颗粒度阶梯打分 (yizi_gran) (V17 剪除规则 2: 去掉普通独苗一字榜首 +5.0 与次席 -10.0，保留黄金共振 +8.0)
    is_super_wave = (df["rk_theme"] == 1) & (df["p_sz"] >= 8) & (df["true_buy_rk"] == 1)
    has_ma_hard = df["notice_hard"] | df["is_ma"]
    flc = df["front_lock_cnt"]
    tbrk = df["true_buy_rk"]
    myz = df["mkt_yizi_cnt"]

    yizi_gran = np.select(
        [
            (flc == 1) & (tbrk == 1) & np.isin(myz, [1, 2]),
            (flc == 1) & (tbrk == 1),
            (flc == 1) & (tbrk >= 2),
            (flc >= 2) & is_super_wave,
            (flc == 2) & (~is_super_wave),
            (flc >= 3) & (~is_super_wave),
            (flc == 0) & (myz == 0) & (~has_ma_hard),
        ],
        [8.0, 0.0, 0.0, 5.0, -15.0, -22.0, -5.0],
        default=0.0,
    )
    df["yizi_gran"] = yizi_gran

    auc_bonus = (
        rk_bon
        + np.where(df["mkt_open_rk"] <= 3, 20.0, np.where(df["mkt_open_rk"] <= 6, 12.0, 0.0))
        + np.where(df["open_lead"] >= 0.020, 22.0, np.where(df["open_lead"] >= 0.010, 12.0, 0.0))
        + np.where(df["plate_d2_yizi_cnt"] >= 1, 10.0, 0.0)
        + np.where(df["o_pct"].between(0.040, 0.082), 20.0, np.where(df["o_pct"].between(0.018, 0.040), 12.0, 0.0))
    )

    wk_add = 10.0 if is_monday else 0.0
    roll20_ho_zt = float(mkt.get("roll20_ho_zt", 0.45))
    if is_monday:
        weak_pen = 0.0
    else:
        # V17 规则 γ: 前视滚动20日高开封板率传感器
        if roll20_ho_zt < 0.45:
            weak_pen = np.where(df["o_pct"] < 0.035, -25.0, 0.0)
        else:
            weak_pen = np.where(df["o_pct"] < 0.031, -15.0, 0.0)

    # 汇流：yizi_gran 50% 进先验 / 50% 进量化，name_pen 扣进先验 (V17 剪除规则 1: 去掉 notice_hard 二次 +8.0 分)
    df["s_prior_wk"] = df["s_prior_dual"] + df.apply(
        lambda r: (15.0 if (r["is_pioneer_word"] or r["has_new_term"] or r["own_new"] or r["sub_cluster_cnt"] >= 2) else 0.0)
        + (10.0 if r["s_elo"] >= 105.0 else (-10.0 if r["s_elo"] <= 95.0 else 0.0))
        + (-35.0 if r["notice_bad"] else 0.0), axis=1
    ) + wk_add + df["name_pen"] + yizi_gran * 0.5

    df["s_quant"] = df["s_q_base"] + auc_bonus + weak_pen + yizi_gran * 0.5
    df["tot"] = df["s_prior_wk"] + df["s_quant"]

    p_sum = df.groupby("plate")["o_pct"].transform("sum")
    p_cnt = df.groupby("plate")["o_pct"].transform("count")
    peers_avg = np.where(p_cnt > 1, (p_sum - df["o_pct"]) / (p_cnt - 1), 0.0)
    p_avg = p_sum / np.maximum(p_cnt, 1)
    df["_hi_o"] = (df["o_pct"] >= 0.020).astype(int)
    hi_cnt = df.groupby("plate")["_hi_o"].transform("sum")

    pass_l3 = (p_cnt <= 1) | ((peers_avg >= -0.010) & ((p_avg >= -0.005) | (hi_cnt >= 2)))
    pass_nd = (~((df["p_sz"] >= 2) & (df["true_buy_rk"] >= 3))) & (~((df["plate_d2_yizi_cnt"] >= 1) & ((df["mcap"] > 90.0) | (df["d1_tightness"] < 15.0))))
    common_ok = df["is_buyable_open"] if (not nuclear_halt and not promo_freeze) else pd.Series(False, index=df.index)

    o_ok = df["o_pct"].between(0.020, 0.088) if is_monday else df["o_pct"].between(0.022, 0.078)
    # V17 剪除规则 4: 去掉主通道与周一通道 s_quant >= 150.0 / 145.0 单项限制
    m_t1 = common_ok & o_ok & (df["s_prior_wk"] >= 45.0) & (df["tot"] >= tot_thr) & df["purifier_ok"] & pass_l3 & pass_nd
    m_t2 = common_ok & (df["p_sz"] == 1) & (df["is_pioneer_word"] | df["has_new_term"] | df["own_new"] | df["notice_hard"] | df["is_ma"]) & df["o_pct"].between(0.035, 0.078) & (df["mkt_open_rk"] <= 3) & df["pass_l2"] & df["p_tight"] & ((df["dd20_d0"] <= 0.88) | df["clean_brk60"])
    mm = m_t1 | m_t2

    if is_monday:
        mmon = common_ok & df["o_pct"].between(0.015, 0.090) & (df["s_prior_wk"] >= 38.0) & (df["tot"] >= tot_thr) & df["purifier_ok"] & pass_l3 & pass_nd
        tot_mask = mm | (mmon & (~mm))
    else:
        tot_mask = mm

    df["rank_sv"] = np.where(mm, df["tot"] + 1000.0, df["tot"])

    # 防篡位判定：若主线在场(rk_theme==1)，但头名标的属于第4名以后冷门题材，全天空仓
    if tot_mask.any():
        sub_ok = df[tot_mask]
        if (sub_ok["rk_theme"] == 1).any():
            top1_rk = sub_ok.sort_values("rank_sv", ascending=False).iloc[0]["rk_theme"]
            if top1_rk >= 4 and top1_rk < 99:
                tot_mask = pd.Series(False, index=df.index)
                print("⚠️ 主线头名已有过线票但冷门第4名以后题材篡位第一，触发防篡位保护，今日全天空仓")

    # V17 规则 α 与 规则 β 判定
    theme_struct = cache_obj.get("theme_structure", {})
    is_dominant_t1 = bool(theme_struct.get("is_dominant_t1", False))
    dom_t1_plate = theme_struct.get("dom_t1_plate", "")
    is_melee = bool(theme_struct.get("is_melee", False))

    # 规则 α：断层主线无过线头名股时，禁止退选第三题材标的 (rk_theme == 3)
    if is_dominant_t1 and tot_mask.any():
        t1_has_passed = (df[tot_mask]["plate"] == dom_t1_plate).any()
        if not t1_has_passed:
            blocked_alpha = tot_mask & (df["rk_theme"] == 3)
            if blocked_alpha.any():
                print(f"⚠️ 规则 α 触发: 断层第一题材【{dom_t1_plate}】无过线股，拦截第3题材标的 {list(df[blocked_alpha]['name'])}，允许退选第2题材")
                tot_mask = tot_mask & (~(df["rk_theme"] == 3))

    # 规则 β：三大题材混战日卡全场竞价前二或硬催化并购
    if is_melee and tot_mask.any():
        has_catalyst = df["notice_hard"] | df["is_ma"]
        blocked_beta = tot_mask & (~((df["mkt_open_rk"] <= 2) | has_catalyst))
        if blocked_beta.any():
            print(f"⚠️ 规则 β 触发: 三大题材均势混战日，候选股未卡全场竞价前二且无并购硬催化，拦截标的 {list(df[blocked_beta]['name'])}")
            tot_mask = tot_mask & ((df["mkt_open_rk"] <= 2) | has_catalyst)

    df["ok"] = tot_mask
    print(
        f"=== 一进二生产主策略 V17 定版实时裁决 | 门槛: {tot_thr:.1f} 分 {gate_note} | "
        f"昨日首板竞价均值={prev_zt_auc_avg*100:+.2f}% | 近5日晋级率={promo_ma5*100:.1f}% | roll20={roll20_ho_zt*100:.1f}% ==="
    )
    winners = df[df["ok"]].sort_values("rank_sv", ascending=False)
    if len(winners) > 0:
        w = winners.iloc[0]
        do_direct = is_monday and (w["tot"] >= 310.0) and (w["open_lead"] >= 0.025)
        now_hm = datetime.datetime.now().hour * 100 + datetime.datetime.now().minute
        afternoon_warn = " [⚠️当前已过11:30上午收盘，若上午未触及点火价成交则严禁下午追买偷袭拉升]" if (not do_direct and now_hm > 1130) else ""
        act_str = (
            f"周一断层强开，09:25开盘价 {w['open_p']:.2f} 元直接买"
            if do_direct
            else f"严禁竞价直买，仅当上午11:30前向上触及点火价 {w['trig_p']:.2f} 元(<涨停{w['zt_p']:.2f})才买；11:30未点火则下午撤单不买{afternoon_warn}"
        )
        print(f"🎯【今日唯一锁定头名】{w['ticker']} {w['name']} ({w['plate']}) | 总分={w['tot']:.1f} | 执行={act_str}")
    else:
        print("🛡️【今日无过线头名标的，全天空仓休息】")

    for _, r in df.sort_values(["ok", "rank_sv"], ascending=[False, False]).head(10).iterrows():
        print(
            f"OK={int(r['ok'])} | {r['ticker']} {r['name']} | {r['plate']}(t_rk={int(r['theme_open_rk'])},m_rk={int(r['mkt_open_rk'])}) "
            f"| 总分={r['tot']:.1f}(题材{r['s_prior_wk']:.0f}+量化{r['s_quant']:.0f}) | 开盘={r['open_p']:.2f}({r['o_pct']*100:+.2f}%) "
            f"| 点火价={r['trig_p']:.2f} | 现价={r['cur_p']:.2f}(最高{r['high_p']:.2f})"
        )

    print("\n【一进二现行定版离场铁律】")
    print("  1. 买入日未封板：次日 09:25 高开 >= +0.5% 才留仓博弱转强；低开或收绿或次日高开不足 0.5%，09:25 集合竞价直接全清！")
    print("  2. 买入日封死二板 (或弱转强封板后)：第 3 天起，只在 10:30 看一眼分时线：")
    print("     - 10:30 封板：洗盘不动，若 14:30 之后炸板，抢跑清仓；若收盘封住则继续持有；")
    print("     - 10:30 未封板且破均价线：10:35 立即全卖离场；")
    print("     - 10:30 站上均价线：拿至收盘 (满 3 板断板且收涨 >= +2% 免死多拿 1 天)。")
    print(f"[live] 基准日={d1_dt_str} | 实时打分总耗时={time.time()-t0:.3f}s")


def sync_all():
    t_start = time.time()
    step_times = {}

    s1 = time.time()
    print("[sync-all 1/5] 同步东财全市场公告库 (sync_notices_db.py --recent)...", flush=True)
    subprocess.run([sys.executable, SYNC_NOTICES_SCRIPT, "--recent"], check=False, timeout=90)
    step_times["1_notices_db"] = round(time.time() - s1, 2)

    s2 = time.time()
    now = datetime.datetime.now()
    if (now.hour > 15) or (now.hour == 15 and now.minute >= 15):
        print("[sync-all 2/5] 当前 >= 15:15，同步开盘啦今日涨停题材 (astock_concept_vocab.py --today)...", flush=True)
        try:
            subprocess.run([sys.executable, f"{ND_DIR}/astock_concept_vocab.py", "--today"], check=False, timeout=90)
        except Exception as e:
            print(f"  ⚠️ astock_concept_vocab.py 异常: {e}", flush=True)
    else:
        print("[sync-all 2/5] 当前 < 15:15，跳过开盘啦盘后涨停接口拉取。", flush=True)
    step_times["2_kpl_vocab"] = round(time.time() - s2, 2)

    s3 = time.time()
    print("[sync-all 3/5] 刷新雪球社区新概念并归档每日快照...", flush=True)
    try:
        subprocess.run([sys.executable, f"{ND_DIR}/astock_concepts.py", "--skip-extract", "--dry"], check=False, timeout=45)
    except Exception as e:
        print(f"  ⚠️ astock_concepts.py 异常: {e}", flush=True)
    today_str = now.strftime("%Y-%m-%d")
    step_times["3_community_archive"] = round(time.time() - s3, 2)

    s4 = time.time()
    print("[sync-all 4/5] 抓取同花顺全量涨停池并永久归档...", flush=True)
    try:
        ymd = today_str.replace("-", "")
        url = (
            f"https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&"
            "field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004&"
            f"filter=HS,GEM2STAR&order_field=330324&order_type=0&date={ymd}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
        info = resp.get("data", {}).get("info", [])
        if info:
            out_p = f"{SIM_DIR}/data/ths_limit_up_daily/{today_str}.json"
            os.makedirs(os.path.dirname(out_p), exist_ok=True)
            with open(out_p, "w", encoding="utf-8") as f:
                json.dump({"date": today_str, "archived_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "total_count": len(info), "stocks": info}, f, ensure_ascii=False, indent=2)
            print(f"  ✅ 归档同花顺涨停池至 ths_limit_up_daily/{today_str}.json (涨停数: {len(info)}只)", flush=True)
    except Exception as e:
        print(f"  ⚠️ 同花顺涨停池归档异常: {e}", flush=True)
    step_times["4_ths_archive"] = round(time.time() - s4, 2)

    s5 = time.time()
    print("[sync-all 5/5] 构建一进二盘前预评分缓存 (--build-cache)...", flush=True)
    build_cache(verbose=True)
    step_times["5_build_cache"] = round(time.time() - s5, 2)

    tot_sec = round(time.time() - t_start, 2)
    print(f"[sync-all] 全部完成! 分步耗时={step_times} | 总耗时={tot_sec:.2f}s", flush=True)


def main():
    ap = argparse.ArgumentParser(description="一进二现行定版 (211.36倍终极生产定型)")
    ap.add_argument("--sync-all", action="store_true", help="全量同步公告+社区归档+同花顺归档+KPL并构建预评分缓存")
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
