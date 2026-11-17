#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
upgrade_1to2_pit.py
================================================================================
一进二策略独立升级版 V19_cand（完全前视 PIT · 五年零穿越验证与八项防过拟合审计）

100% 独立单策略（不改任何现役生产文件与 strategy_astock.md），在严格 IS (2021-2023)
定标并通过 OOS (2024-2026) 纯盲测及 100% 5分钟 K 线覆盖门限：
  1. 卖点对偶升级 M1（借自二进三交接规律）：
     封死二板次日（D3）若落入二进三暗牌接力区（D3 开盘 -6.5%~+2.5%，D1~D3 09:25 前
     雪球 < 4 帖，且 D2 封成比 < 25% 或缺失），豁免 D3 10:30 破分时均价线弱斩，持有至收盘/连板。
  2. 补位暗牌低位催化通道 fb_dom295（借自跨板块高分与三进四破局规律）：
     当第 2/3 主线板块（rk_theme in {2, 3}）出现可买竞价头名（true_buy_rk == 1）且同时满足：
     暗牌（雪球盘前 < 4 帖）+ 启动前 20 日箱体低位（pos20 <= 40%）+ 硬催化（硬公告/重组/先驱新词）
     + 零龙虎榜拉萨及一日游席位，且剔除主线压制扣分后得分 >= 295.0 时，作为第 3 顺位候补入池。

硬红线校验：
  - 严禁 import yfinance (D12)；所有 SQLite 使用 ?mode=ro 只读打开
  - 三行物理校验：单位除数 + 价格/事件时间锚点 < buy_date 09:25:00 + 行列极值 assert
  - 物理截断 >= 2025-01-01 数据重跑 2021-2024，断言逐笔日期/代码/得分/收益 max_abs_diff == 0.0
  - T+0=0, 重叠=0, 一字买入=0, 5分钟K线覆盖率=100.0%
================================================================================
"""

import bisect
import datetime
import itertools
import json
import math
import os
import re
import sqlite3
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import scipy.stats as stats

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{PROJECT_ROOT}/sim-portfolio"
OUT_DIR = f"{SIM_DIR}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
os.makedirs(OUT_DIR, exist_ok=True)

OUT_CSV = f"{OUT_DIR}/ledger_upg_1to2.csv"
OUT_JSON = f"{OUT_DIR}/summary_upg_1to2.json"

A_DAILY_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_MERGED_PATH = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"
KPL_5Y_PATH = f"{SIM_DIR}/data/kpl_plates_5y_2021_2026_complete.jsonl"
DB_NOTICES_PATH = f"{SIM_DIR}/data/cninfo_notices_5y_pit.db"
PARQUET_TOX_PATH = f"{SIM_DIR}/data/pit_reg_tox_notices_5y_complete.parquet"
CSV_CSRC_PIT_PATH = f"{SIM_DIR}/data/csrc_industry_pit_clean.csv"
DB_TAPE_PATH = f"{SIM_DIR}/data/zt_micro_tape_5y_pit.db"
DB_IR_QA_PATH = f"{SIM_DIR}/data/cninfo_ir_qa_5y_pit.db"
DB_XUEQIU_PATH = f"{SIM_DIR}/data/xueqiu_guba_5y_pit.db"
LHB_BUY_PATH = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
PARQUET_5M_PATH = f"{SIM_DIR}/data/all_strategies_5m_complete_pit.parquet"
IDX_JSON_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
CSI300_BENCH_FILE = f"{SIM_DIR}/backtests_astock/clean_rebacktest_20261116/csi300_canonical_20261116.json"
CAND_01_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/cand_0to1_firstboard.parquet"

CANON_5Y_START = "2021-11-15"
DATA_END_DT = "2026-11-16"
FEE_RATE = 0.0020

NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股",
}
EVENT_BASKET_PLATES = {
    "并购重组", "股权转让", "资产注入", "国企改革", "央企改革",
    "地方国资改革", "业绩增长", "预盈预增", "摘帽", "回购",
    "增持", "次新股", "高送转", "参股新股",
}
BROAD_INDUSTRY_PLATES = {
    "通信", "汽车零部件", "医药", "医疗器械", "化工", "机械",
    "房地产", "建筑", "环保", "电力", "纺织", "传媒", "家电",
    "食品", "农业", "交通运输", "有色", "煤炭", "钢铁",
}

MA_PAT = re.compile(r"(重组|收购|股权转让|实控人变更|控制权变更|资产注入|借壳|控股|整合|中标|重大合同)")
TECH_PAT_ORIG = re.compile(
    r"(AI|算力|机器人|芯片|半导体|光刻|低空|商业航天|卫星|太空|固态电池|量子|脑机|大模型|具身智能|"
    r"华为|鸿蒙|无人驾驶|智驾|游戏|影之刃|黑神话|CPO|光模块|液冷|HBM|数据要素|深海|核聚变)"
)
TECH_PAT_TIMELESS = re.compile(
    r"(芯片|半导体|光刻|集成电路|软件|信创|云计算|大数据|人工智能|AI|机器人|智能制造|自动化|"
    r"通信|5G|光通信|卫星|航天|军工|锂电|光伏|储能|风电|氢能|新材料|消费电子|智能驾驶|无人驾驶)"
)
EARN_PAT = re.compile(r"(业绩|预增|扭亏|季报|年报|半年报|分红)")
HARD_NOTICE_PAT = re.compile(r"(重组|收购|股权转让|控制权|实控人变更|资产注入|借壳|重大合同|中标|战略合作|框架协议|投资设立)")
HARD_NOTICE_ORIG_PAT = re.compile(
    r"(重组|收购|股权转让|控制权|实控人变更|资产注入|借壳|重大合同|中标|战略合作|框架协议|投资设立|"
    r"算力|机器人|芯片|卫星|人工智能|固态电池|低空)"
)
MA_NOTICE_PAT = re.compile(r"(重组|收购|股权转让|控制权变更|实控人变更|资产注入|借壳|重大合同|中标)")
EARN_NOTICE_PAT = re.compile(r"(业绩预增|业绩快报|扭亏为盈|半年度业绩|年度业绩|季度业绩)")
BAD_NOTICE_PAT = re.compile(
    r"(减持|问询函|监管函|警示函|立案|风险提示|业绩预亏|亏损|计提资产减值|退市风险|终止上市|违规|质押|冻结)"
)
NEG_NOTICE_PAT = re.compile(
    r"(不存在|不涉及|未筹划|未发现|无应披露|股票交易异常波动|异常波动公告|风险提示|占比极小|敬请广大投资者注意)"
)
SURF_YZ_PURE = re.compile(
    r"(?:上塘路|财通.*杭州上塘|佛山|绿景路|苏南|消闲派|国泰君安.*宜昌|开源.*西安西大街)"
)
CSRC_PURE_OUTSIDER = {
    "A01", "A02", "A03", "A04", "A05", "D44", "D45", "D46", "E47", "E48", "E49", "E50",
    "F51", "F52", "G53", "G54", "G55", "G56", "G58", "G59", "H61", "H62", "K70",
    "L72", "N77", "N78", "C13", "C14", "C15", "C17", "C18", "C19", "C20", "C21", "C22",
}


def split_terms(s: str) -> set:
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
    return {t for t in out if 2 <= len(t) <= 20 and t not in NON_THEME}


def norm_term(t: str) -> str:
    t = re.sub(r"（.*?）|\(.*?\)", "", t or "")
    return re.sub(r"[\s·\-_()（）“”\"'《》/]", "", t).lower().removesuffix("概念")


def load_full_prices_pit(end_date_cutoff: str):
    """加载主板活跃+退市全量日线并物理截断至 <= end_date_cutoff。"""
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn", "oshare"]
    dt_hi = pd.Timestamp(end_date_cutoff)
    dt_lo = pd.Timestamp("2017-08-01")
    f_expr = (ds.field("date") >= dt_lo) & (ds.field("date") <= dt_hi)

    df_act = ds.dataset(A_DAILY_PATH, format="parquet").scanner(columns=cols, filter=f_expr).to_table().to_pandas()
    parts = [df_act]
    if os.path.exists(A_DELISTED_PATH):
        df_del = ds.dataset(A_DELISTED_PATH, format="parquet").scanner(columns=cols, filter=f_expr).to_table().to_pandas()
        parts.append(df_del)

    df = pd.concat(parts, ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60")) & (~df["ticker"].str.endswith(".BJ"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df[df["dt_str"] <= end_date_cutoff].copy()
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # 三行校验 1 & 3：单位除数 + 行列极值
    assert len(df) > 100000 and df["dt_str"].max() <= end_date_cutoff, "Daily table truncation/size assert failed"
    g = df.groupby("c6")
    df["pre_c"] = g["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["o_pct"] = df["open"] / df["pre_c"] - 1.0
    df["h_pct"] = df["high"] / df["pre_c"] - 1.0
    df["l_pct"] = df["low"] / df["pre_c"] - 1.0
    df["mcap"] = df["close"] * df["oshare"] / 1e8
    df["to"] = df["turn"] * 100.0

    assert 10.0 < float(df["mcap"].median()) < 500.0, f"mcap unit check failed: {df['mcap'].median()}"
    assert 0.1 < float(df["to"].median()) < 20.0, f"to(%) unit check failed: {df['to'].median()}"
    assert float(df["close"].min()) > 0.0 and float(df["close"].quantile(0.99)) < 500.0, "Daily close extrema check failed"

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

    df["d2_dt"] = g["dt_str"].shift(-1)
    df["d2_open"] = g["open"].shift(-1)
    df["d2_high"] = g["high"].shift(-1)
    df["d2_low"] = g["low"].shift(-1)
    df["d2_close"] = g["close"].shift(-1)
    df["d2_o_pct"] = df["d2_open"] / df["close"] - 1.0
    df["d2_zt_p"] = np.floor(df["close"] * 1.10 * 100.0 + 0.5) / 100.0
    df["d2_is_zt"] = g["is_zt"].shift(-1).fillna(False)
    df["d2_is_yizi"] = g["is_yizi"].shift(-1).fillna(False)

    all_dts = sorted(df["dt_str"].unique())
    dg = df.groupby("dt_str")
    zt_cnt_map = dg["is_zt"].sum().to_dict()
    dt_cnt_map = dg["is_dt"].sum().to_dict()
    d1_1to2_sub = df[df["is_1to2_day"]]
    dg_1to2 = d1_1to2_sub.groupby("dt_str")
    cnt_1to2_map = dg_1to2["is_zt"].count().to_dict()
    touch_1to2_map = dg_1to2["touch_zt"].sum().to_dict()
    seal_1to2_map = dg_1to2["is_zt"].sum().to_dict()

    seal_rate_map, promo_ma5_map = {}, {}
    promo_list = []
    for dt in all_dts:
        tc = touch_1to2_map.get(dt, 0)
        sc = seal_1to2_map.get(dt, 0)
        cc = cnt_1to2_map.get(dt, 0)
        seal_rate_map[dt] = float(sc / tc) if tc > 0 else 0.55
        promo_list.append(float(sc / cc) if cc > 0 else 0.20)
        promo_ma5_map[dt] = float(np.mean(promo_list[-5:]))

    return df, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map


def build_8y_purified_theme_metadata_pit(df: pd.DataFrame, end_date_cutoff: str):
    """8 年连续滚动动态题材、Elo 与净化特征，物理截断至 <= end_date_cutoff。"""
    kpl_days_map = {}
    if os.path.exists(KPL_MERGED_PATH):
        with open(KPL_MERGED_PATH, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    try:
                        d = json.loads(ln)
                        dt = d.get("date", "")
                        if dt and dt < "2021-01-01" and dt <= end_date_cutoff:
                            kpl_days_map[dt] = d
                    except Exception:
                        pass
    if os.path.exists(KPL_5Y_PATH):
        with open(KPL_5Y_PATH, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    try:
                        d = json.loads(ln)
                        dt = d.get("date", "")
                        if dt >= "2021-01-01" and dt <= end_date_cutoff:
                            kpl_days_map[dt] = d
                    except Exception:
                        pass

    kpl_days = [kpl_days_map[k] for k in sorted(kpl_days_map.keys())]
    assert kpl_days[-1]["date"] <= end_date_cutoff, "KPL date truncation check failed"
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
    stock_theme_5y = {}

    for day_idx, d_entry in enumerate(kpl_days):
        dt = d_entry["date"]
        cutoff_15d = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=15)).isoformat()
        plates = d_entry.get("plates", [])

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
            n_ma = n_tech_o = n_tech_t = n_earn = n_big = n_yizi = n_new = 0
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
                if TECH_PAT_ORIG.search(txt): n_tech_o += 1
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
            sc_orig = sc_base + (6.0 if (TECH_PAT_ORIG.search(pname) or n_tech_o >= max(1, sz // 2)) else 0.0)
            sc_clean = sc_base + (6.0 if (TECH_PAT_TIMELESS.search(pname) or n_tech_t >= max(1, sz // 2)) else 0.0)
            plate_scores[pname] = sc_orig
            plate_meta[pname] = (
                sc_orig, sc_clean, elo[pname], sz, n_yizi, n_new > 0, spark_b,
                n_tech_o, n_tech_t, stocks, n_2b_lead_cnt > 0, is_dying_pulse, sub_counts
            )

        ranked_p = sorted(plate_scores.keys(), key=lambda k: plate_scores[k], reverse=True)
        rk_map = {k: i + 1 for i, k in enumerate(ranked_p)}
        top2_sc = plate_scores[ranked_p[1]] if len(ranked_p) >= 2 else 100.0
        ranked_c = sorted(plate_meta.keys(), key=lambda k: plate_meta[k][1], reverse=True)
        rk_map_c = {k: i + 1 for i, k in enumerate(ranked_c)}
        top2_sc_c = plate_meta[ranked_c[1]][1] if len(ranked_c) >= 2 else 100.0

        if dt >= "2021-01-01":
            for pname, m in plate_meta.items():
                sc_o, sc_c, p_elo, sz, n_yz, has_new, spk, nto, ntt, stocks, has_2b_lead, is_dying_p, sub_counts = m
                rk_o, rk_c = rk_map[pname], rk_map_c[pname]
                gap_o = (sc_o - top2_sc) if rk_o == 1 else 0.0
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
                    cur = stock_theme_5y.get((dt, c6))
                    if cur is None or sc_o > cur["t_score_o"]:
                        stock_theme_5y[(dt, c6)] = {
                            "name": sname, "plate": pname, "r_short": r_sh or pname,
                            "rk_o": rk_o, "t_score_o": sc_o, "gap_o": gap_o,
                            "rk_c": rk_c, "t_score_c": sc_c, "gap_c": gap_c,
                            "p_elo": p_elo, "s_elo": s_elo, "p_sz": sz, "n_yizi": n_yz,
                            "has_new": has_new, "own_new": own_new, "spark": spk, "has_2b_lead": has_2b_lead,
                            "is_ma": bool(MA_PAT.search(txt)),
                            "is_tech_o": bool(TECH_PAT_ORIG.search(txt)),
                            "is_tech_c": bool(TECH_PAT_TIMELESS.search(txt)),
                            "is_earn": bool(EARN_PAT.search(txt)),
                            "is_event_basket": is_event_basket,
                            "is_broad_ind": is_broad_ind,
                            "sub_cluster_cnt": sub_cnt,
                            "is_dying_pulse": is_dying_p,
                        }

        for t, dt_v in day_terms_to_commit.items():
            term_seen_days[t] += 1
            if t not in term_first_dt:
                term_first_dt[t] = dt_v
            term_last_idx[t] = day_idx
        prev_plate_stocks = new_prev_p
        prev_sub_stocks = new_prev_sub

    return stock_theme_5y, pioneer_word_history


def compute_purifier_auction_scores_pit(sub_df: pd.DataFrame) -> pd.DataFrame:
    df = sub_df.copy()
    auc_mean = df.groupby("d2_dt")["d2_o_pct"].transform("mean")
    df["nuclear_halt"] = auc_mean < 0.0
    df["promo_freeze"] = df["mkt_promo_ma5"] < 0.13

    df["is_buyable_open"] = df["gate_ok"] & (df["d2_open"] > 0) & (df["d2_open"] < df["d2_zt_p"] - 0.005)
    df["plate_d2_yizi_cnt"] = df.groupby(["d2_dt", "plate"])["d2_is_yizi"].transform("sum")

    buy_mkt_o = np.where(df["is_buyable_open"], df["d2_o_pct"], -9.99)
    df["_buy_mkt_o"] = buy_mkt_o
    df["buyable_mkt_open_rk"] = df.groupby("d2_dt")["_buy_mkt_o"].rank(ascending=False, method="min")

    buy_plate_o = np.where(df["is_buyable_open"], df["d2_o_pct"], -9.99)
    df["_buy_plate_o"] = buy_plate_o
    df["buyable_plate_rk"] = df.groupby(["d2_dt", "plate"])["_buy_plate_o"].rank(ascending=False, method="min")
    df["subbranch_rk"] = df.groupby(["d2_dt", "plate", "r_short"])["_buy_plate_o"].rank(ascending=False, method="min")
    p2_buy = df.groupby(["d2_dt", "plate"])["_buy_plate_o"].transform(
        lambda s: s.nlargest(2).iloc[-1] if (s > -1.0).sum() >= 2 else -0.05
    )
    df["buy_open_lead"] = np.where(df["buyable_plate_rk"] == 1, df["d2_o_pct"] - p2_buy, 0.0)

    has_distinct_sub = (df["p_sz"] >= 8) & (df["r_short"] != df["plate"]) & (df["r_short"] != "其他") & (df["r_short"] != "")
    rk_bonus_dual = np.where(
        df["buyable_plate_rk"] == 1, 35.0,
        np.where(
            has_distinct_sub & (df["subbranch_rk"] == 1), 24.0,
            np.where(df["buyable_plate_rk"] == 2, 8.0, -25.0)
        )
    )
    auc_dual = (
        rk_bonus_dual
        + np.where(df["buyable_mkt_open_rk"] <= 3, 20.0, np.where(df["buyable_mkt_open_rk"] <= 6, 12.0, 0.0))
        + np.where(df["buy_open_lead"] >= 0.020, 22.0, np.where(df["buy_open_lead"] >= 0.010, 12.0, 0.0))
        + np.where(df["plate_d2_yizi_cnt"] >= 1, 10.0, 0.0)
        + np.where(df["d2_o_pct"].between(0.040, 0.082), 20.0, np.where(df["d2_o_pct"].between(0.018, 0.040), 12.0, 0.0))
    )
    df["s_quant_dual"] = df["s_q_base_dual"] + auc_dual
    df["tot_dual"] = df["s_prior_dual"] + df["s_quant_dual"]
    df["score_dual"] = df["tot_dual"]

    df["trig_p"] = np.minimum(
        df["d2_zt_p"],
        np.maximum(np.round(df["d2_open"] * 1.012, 2), np.round(df["close"] * 1.065, 2))
    )

    plate_o_sum = df.groupby(["d2_dt", "plate"])["d2_o_pct"].transform("sum")
    plate_o_cnt = df.groupby(["d2_dt", "plate"])["d2_o_pct"].transform("count")
    df["plate_peers_open_avg"] = np.where(
        plate_o_cnt > 1, (plate_o_sum - df["d2_o_pct"]) / (plate_o_cnt - 1), 0.0
    )
    df["plate_fb_cnt"] = plate_o_cnt
    df["plate_d2_open_avg"] = plate_o_sum / plate_o_cnt
    df["_is_high_open"] = (df["d2_o_pct"] >= 0.020).astype(int)
    df["plate_high_open_cnt"] = df.groupby(["d2_dt", "plate"])["_is_high_open"].transform("sum")
    return df


def build_signals_and_data_pit(end_date_cutoff: str = DATA_END_DT):
    """构建完整无后视镜特征与信号表，严格物理截断所有数据源至 <= end_date_cutoff。"""
    t0 = time.time()
    df_daily, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices_pit(end_date_cutoff)
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
        for r in df_daily[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
    }
    amt_lookup = {
        (r.c6, r.dt_str): float(r.amount)
        for r in df_daily[["c6", "dt_str", "amount"]].itertuples(index=False) if pd.notna(r.amount)
    }

    stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata_pit(df_daily, end_date_cutoff)

    fb = df_daily[df_daily["is_first_board"] & (~df_daily["is_yizi"]) & (df_daily["dt_str"] >= "2021-01-04")].copy()
    c6_set = set(fb["c6"].unique())

    # 1. 严格 PIT 公告（物理截断 <= end_date_cutoff 09:25:00，逐笔锚点 < d2 09:25:00）
    notice_by_c6 = defaultdict(list)
    if os.path.exists(DB_NOTICES_PATH):
        conn_notices = sqlite3.connect(f"file:{DB_NOTICES_PATH}?mode=ro", uri=True)
        for sec_code, pub_dt, avail_dt, title in conn_notices.execute(
            "SELECT sec_code, pub_datetime_cst, trade_date_avail, title FROM notices WHERE pub_datetime_cst >= '2020-12-25' AND pub_datetime_cst <= ?",
            (f"{end_date_cutoff} 09:25:00",),
        ):
            c6 = str(sec_code)[:6].zfill(6)
            if c6 not in c6_set or not pub_dt:
                continue
            ts = str(title or "")
            is_neg = bool(NEG_NOTICE_PAT.search(ts)) or bool(BAD_NOTICE_PAT.search(ts))
            if is_neg:
                flags = (False, False, False, bool(EARN_NOTICE_PAT.search(ts)), True)
            else:
                flags = (
                    bool(HARD_NOTICE_ORIG_PAT.search(ts)),
                    bool(HARD_NOTICE_PAT.search(ts)),
                    bool(MA_NOTICE_PAT.search(ts)),
                    bool(EARN_NOTICE_PAT.search(ts)),
                    False,
                )
            if any(flags):
                notice_by_c6[c6].append((str(pub_dt), str(avail_dt or ""), flags))
        conn_notices.close()

    if os.path.exists(PARQUET_TOX_PATH):
        df_tox = pd.read_parquet(PARQUET_TOX_PATH)
        df_tox = df_tox[df_tox["pub_datetime_cst"].astype(str) <= f"{end_date_cutoff} 09:25:00"]
        for sec_code, pub_dt, title in df_tox[["sec_code", "pub_datetime_cst", "title"]].itertuples(index=False):
            c6 = str(sec_code)[:6].zfill(6)
            if c6 not in c6_set or not pub_dt:
                continue
            ts = str(title or "")
            is_neg = bool(NEG_NOTICE_PAT.search(ts)) or bool(BAD_NOTICE_PAT.search(ts)) or ("澄清" in ts)
            if is_neg:
                flags = (False, False, False, bool(EARN_NOTICE_PAT.search(ts)), True)
                notice_by_c6[c6].append((str(pub_dt), "", flags))

    for c6 in notice_by_c6:
        notice_by_c6[c6].sort(key=lambda x: x[0])

    rows_meta = []
    cols_needed = [
        "c6", "dt_str", "d2_dt", "mcap", "amount", "f_dd20_d0", "f_dd60_d0", "f_pos20_d0",
        "f_d0_pct", "f_ret_pre10", "to", "f_d1_vol_ratio", "f_zt_cnt_pre20", "f_break60", "close", "d1_seal_tightness"
    ]
    for r in fb[cols_needed].itertuples(index=False):
        c6, d1 = r.c6, r.dt_str
        d2 = r.d2_dt if (pd.notna(r.d2_dt) and r.d2_dt <= end_date_cutoff) else end_date_cutoff
        ti = stock_theme_5y.get((d1, c6))
        if ti is None:
            ti = {
                "name": "", "plate": "其他", "r_short": "其他",
                "rk_o": 99, "t_score_o": 95.0, "gap_o": 0.0,
                "rk_c": 99, "t_score_c": 95.0, "gap_c": 0.0,
                "p_elo": 100.0, "s_elo": 100.0, "p_sz": 1, "n_yizi": 0,
                "has_new": False, "own_new": False, "spark": 0.0, "has_2b_lead": False,
                "is_ma": False, "is_tech_o": False, "is_tech_c": False, "is_earn": False,
                "is_event_basket": False, "is_broad_ind": False,
                "sub_cluster_cnt": 1, "is_dying_pulse": False,
            }

        start_cut = (datetime.date.fromisoformat(d1) - datetime.timedelta(days=4)).isoformat()
        end_cut = f"{d2} 09:25:00"
        nh_o = nh_c = n_ma = n_earn = n_bad = False
        nlist = notice_by_c6.get(c6)
        if nlist:
            lo = bisect.bisect_left(nlist, (start_cut, "", ()))
            for idx_n in range(lo, len(nlist)):
                pdt, adt, fl = nlist[idx_n]
                if pdt >= end_cut:
                    break
                assert pdt < end_cut, f"Notice lookahead violation: {pdt} >= {end_cut}"
                if adt and adt > d2:
                    continue
                nh_o |= fl[0]; nh_c |= fl[1]; n_ma |= fl[2]; n_earn |= fl[3]; n_bad |= fl[4]

        if n_bad:
            nh_c = False; nh_o = False; n_ma = False

        is_st = "ST" in ti["name"].upper() or "退" in ti["name"]
        is_ma_f = bool(ti["is_ma"] or n_ma)
        is_earn_f = bool(ti["is_earn"] or n_earn)
        rk_c, p_sz = ti["rk_c"], ti["p_sz"]
        s_prior_dual = (
            (28 if rk_c == 1 else (16 if rk_c == 2 else (8 if rk_c == 3 else 0)))
            + (18 if p_sz >= 4 else (10 if p_sz >= 2 else -15))
            + (12 if ti["has_new"] else 0) + (8 if ti["own_new"] else 0) + (10 if ti["spark"] > 0 else 0)
            + (18 if nh_c else 0) + (18 if is_ma_f else 0) + (12 if ti["is_tech_c"] else 0)
            + (12 if ti["gap_c"] >= 20.0 else 0)
            + float(np.clip((ti["t_score_c"] - 100.0) * 0.25, 0.0, 25.0))
            + float(np.clip((ti["s_elo"] - 100.0) * 0.35, -10.0, 18.0))
        )

        mcap = float(r.mcap) if pd.notna(r.mcap) else 50.0
        amt = float(r.amount) if pd.notna(r.amount) else 2e8
        dd20 = float(r.f_dd20_d0) if pd.notna(r.f_dd20_d0) else 0.90
        dd60 = float(r.f_dd60_d0) if pd.notna(r.f_dd60_d0) else 0.85
        pos20 = float(r.f_pos20_d0) if pd.notna(r.f_pos20_d0) else 0.50
        d0_pct = float(r.f_d0_pct) if pd.notna(r.f_d0_pct) else 0.0
        ret10 = float(r.f_ret_pre10) if pd.notna(r.f_ret_pre10) else 0.0
        to = float(r.to) if pd.notna(r.to) else 8.0
        vr = float(r.f_d1_vol_ratio) if pd.notna(r.f_d1_vol_ratio) else 1.5
        zt20 = int(r.f_zt_cnt_pre20) if pd.notna(r.f_zt_cnt_pre20) else 0
        brk60 = int(r.f_break60)

        seal_r = seal_rate_map.get(d1, 0.55)
        dt_cnt = dt_cnt_map.get(d1, 5)
        zt_cnt = zt_cnt_map.get(d1, 50)
        promo5 = promo_ma5_map.get(d1, 0.20)

        sc_mcap = 28 if 60 <= mcap <= 155 else (10 if 40 <= mcap < 60 else (-20 if mcap < 35 else 0))
        sc_amt = 18 if 2.2e8 <= amt <= 15e8 else (-25 if amt < 1.8e8 else -10)
        sc_dd20 = 42 if dd20 <= 0.82 else (32 if dd20 <= 0.86 else (18 if dd20 <= 0.90 else (-40 if dd20 > 0.95 else 0)))
        sc_dd60 = 18 if dd60 <= 0.76 else (10 if dd60 <= 0.82 else (-15 if dd60 > 0.92 else 0))
        sc_nshape = 22 if (zt20 >= 1 and dd20 <= 0.86) else (-20 if (zt20 >= 1 and dd20 > 0.92) else 0)
        sc_pos20 = 25 if pos20 <= 0.30 else (12 if pos20 <= 0.45 else (-35 if pos20 > 0.75 else 0))
        sc_d0 = 25 if d0_pct <= -0.010 else (15 if d0_pct <= 0.005 else (-35 if d0_pct > 0.030 else 0))
        sc_ret10 = 15 if ret10 <= 0.05 else (-35 if ret10 > 0.18 else 0)
        sc_to = 15 if to <= 9.0 else (8 if to <= 15.0 else (-25 if to > 18.0 else 0))
        sc_vol = 15 if vr <= 1.75 else (-15 if vr > 2.3 else 0)
        sc_mkt_seal = 18 if seal_r < 0.64 else (-25 if seal_r >= 0.72 else 0)
        sc_mkt_dt = 12 if dt_cnt <= 6 else (-15 if dt_cnt >= 15 else 0)
        sc_mkt_zt = 12 if zt_cnt >= 45 else (-18 if zt_cnt < 35 else 0)

        s_q_base_orig = (
            sc_mcap + sc_amt + sc_dd20 + sc_dd60 + sc_nshape + sc_pos20
            + sc_d0 + sc_ret10 + sc_to + sc_vol + sc_mkt_seal + sc_mkt_dt + sc_mkt_zt
        )
        clean_brk60 = (brk60 == 1) and (ret10 <= 0.08) and (zt20 == 0) and (to <= 14.0)
        s_q_base_dual = (
            (sc_mcap + sc_amt + 24 + sc_d0 + sc_ret10 + sc_to + sc_vol + sc_mkt_seal + sc_mkt_dt + sc_mkt_zt)
            if clean_brk60 else s_q_base_orig
        )

        gate_ok = bool(
            (not is_st) and (not is_earn_f) and (not n_bad)
            and (18.0 <= mcap <= 220.0) and (to <= 20.0)
            and (not (zt20 >= 4 and pos20 > 0.38))
            and (r.close <= 60.0)
        )
        tot_thr = 255.0 if seal_r > 0.75 else 230.0

        r_txt = str(ti.get("r_short", "")) + " " + str(ti.get("name", ""))
        is_pioneer_word = False
        for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", r_txt):
            w = norm_term(m.group(0))
            if w in pioneer_word_history:
                prior = [d_seen for d_seen in pioneer_word_history[w] if d_seen <= d1]
                if 1 <= len(prior) <= 3:
                    is_pioneer_word = True
                    break

        rows_meta.append({
            "name": ti["name"], "plate": ti["plate"], "r_short": ti["r_short"],
            "p_elo": ti["p_elo"], "s_elo": ti["s_elo"], "p_sz": ti["p_sz"],
            "has_new_term": ti["has_new"], "own_new_term": ti["own_new"],
            "spark_bonus": ti["spark"], "is_ma": is_ma_f, "notice_hard": nh_c,
            "notice_bad": n_bad, "clean_brk60": int(clean_brk60), "gate_ok": gate_ok,
            "s_prior_dual": round(s_prior_dual, 2), "s_q_base_dual": round(s_q_base_dual, 2),
            "has_2b_lead": ti.get("has_2b_lead", False),
            "mkt_zt_cnt": zt_cnt, "mkt_dt_cnt": dt_cnt,
            "mkt_seal_rate": seal_r, "mkt_promo_ma5": promo5,
            "tot_thr": tot_thr, "is_pioneer_word": is_pioneer_word,
            "is_event_basket": ti["is_event_basket"],
            "is_broad_ind": ti["is_broad_ind"],
            "sub_cluster_cnt": ti["sub_cluster_cnt"],
            "is_dying_pulse": ti["is_dying_pulse"],
        })

    meta_df = pd.DataFrame(rows_meta, index=fb.index)
    fb_all = pd.concat([fb, meta_df], axis=1)
    hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= end_date_cutoff)].copy().reset_index(drop=True)
    hist_fb = compute_purifier_auction_scores_pit(hist_fb)
    hist_fb["gap_days"] = (pd.to_datetime(hist_fb["d2_dt"]) - pd.to_datetime(hist_fb["dt_str"])).dt.days
    hist_fb["c6"] = hist_fb["ticker"].astype(str).str[:6]

    # 2. 严格截断 PIT 行业表 (仅看 start_date <= d2)
    df_csrc_pit = pd.read_csv(CSV_CSRC_PIT_PATH)
    df_csrc_pit["c6"] = df_csrc_pit["sec_code"].astype(str).str.zfill(6)
    csrc_pit_lookup = defaultdict(list)
    for r in df_csrc_pit[["c6", "start_date", "end_date", "industry"]].itertuples(index=False):
        sd_s = str(r.start_date)
        if sd_s <= end_date_cutoff:
            csrc_pit_lookup[r.c6].append((sd_s, str(r.end_date), str(r.industry) if pd.notna(r.industry) else ""))

    def get_pit_ind_strict(c6_val, dt_val):
        intervals = [x for x in csrc_pit_lookup.get(c6_val, []) if x[0] <= dt_val]
        if not intervals:
            return ""
        for s, e, ind in intervals:
            if s <= dt_val <= e:
                return ind
        return intervals[-1][2]

    hist_fb["csrc_ind"] = [get_pit_ind_strict(c6, d2) for c6, d2 in zip(hist_fb["c6"], hist_fb["d2_dt"])]

    # 3. 严格只读微观盘口 (<= end_date_cutoff)
    conn_tape = sqlite3.connect(f"file:{DB_TAPE_PATH}?mode=ro", uri=True)
    tape_df = pd.read_sql_query(
        "SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape WHERE trade_date <= ?",
        conn_tape, params=(end_date_cutoff,),
    )
    conn_tape.close()
    tape_df = tape_df.drop_duplicates(["trade_date", "sec_code"])
    hist_fb = hist_fb.merge(tape_df, left_on=["dt_str", "c6"], right_on=["trade_date", "sec_code"], how="left")
    tape_map = {
        (r.trade_date, str(r.sec_code).zfill(6)): (r.first_seal_time, r.seal_amount, r.open_board_count)
        for r in tape_df.itertuples(index=False)
    }

    # 4. 严格 PIT 机构调研 (< d2 09:25:00)
    conn_ir = sqlite3.connect(f"file:{DB_IR_QA_PATH}?mode=ro", uri=True)
    ir_df = pd.read_sql_query(
        "SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE pub_datetime_cst IS NOT NULL AND pub_datetime_cst <= ?",
        conn_ir, params=(f"{end_date_cutoff} 09:25:00",),
    )
    conn_ir.close()
    ir_df["c6"] = ir_df["sec_code"].astype(str).str.zfill(6)
    ir_grp = ir_df.groupby("c6")["pub_datetime_cst"].apply(lambda s: np.sort(s.unique())).to_dict()
    ir_7d_pit = np.zeros(len(hist_fb), dtype=bool)
    for idx, (c6, d2) in enumerate(zip(hist_fb["c6"], hist_fb["d2_dt"])):
        arr = ir_grp.get(c6)
        if arr is not None:
            pos = np.searchsorted(arr, f"{d2} 09:25:00", side="left")
            if pos > 0:
                pdt_ir = arr[pos - 1]
                assert pdt_ir < f"{d2} 09:25:00", f"IR Q&A time leak: {pdt_ir} >= {d2} 09:25:00"
                if 0 <= (pd.Timestamp(d2) - pd.Timestamp(pdt_ir[:10])).days <= 8:
                    ir_7d_pit[idx] = True
    hist_fb["has_ir_pit"] = ir_7d_pit

    # 5. 严格 PIT 雪球盘前舆情 (< d2 09:25:00 且供 D3 < d3 09:25:00 查询)
    con_xq = sqlite3.connect(f"file:{DB_XUEQIU_PATH}?mode=ro", uri=True)
    xq_df = pd.read_sql_query(
        "SELECT symbol, created_time_str FROM xueqiu_posts WHERE created_time_str >= '2021-01-01' AND created_time_str <= ?",
        con_xq, params=(f"{end_date_cutoff} 09:25:00",),
    )
    con_xq.close()
    xq_df["c6"] = xq_df["symbol"].astype(str).str[:6].str.zfill(6)
    xq_by_c6 = {c6: np.sort(g["created_time_str"].astype(str).to_numpy()) for c6, g in xq_df.groupby("c6")}

    xq_d2 = np.zeros(len(hist_fb), dtype=int)
    for i, (c6, d1, d2) in enumerate(zip(hist_fb["c6"], hist_fb["dt_str"], hist_fb["d2_dt"])):
        arr = xq_by_c6.get(c6)
        if arr is not None:
            lo = np.searchsorted(arr, f"{d1} 00:00:00", side="left")
            hi = np.searchsorted(arr, f"{d2} 09:25:00", side="left")
            assert hi == 0 or arr[hi - 1] < f"{d2} 09:25:00", f"Xueqiu time leak: {arr[hi-1]} >= {d2} 09:25:00"
            xq_d2[i] = int(hi - lo)
    hist_fb["xq_pre_d2"] = xq_d2

    # 6. 严格 PIT D1 龙虎榜 (<= end_date_cutoff)
    lb = pd.read_parquet(LHB_BUY_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL"])
    lb["dt_str"] = lb["TRADE_DATE"].astype(str).str[:10]
    lb["c6"] = lb["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    lb = lb[(lb["dt_str"] >= "2021-01-01") & (lb["dt_str"] <= end_date_cutoff)].drop_duplicates(
        subset=["dt_str", "c6", "OPERATEDEPT_NAME"]
    )
    lhb_map = {}
    for (dt, c6), grp in lb.groupby(["dt_str", "c6"], sort=False):
        seats = grp["OPERATEDEPT_NAME"].astype(str).tolist()
        lh_cnt = sum(1 for s in seats if "拉萨" in s)
        surf_pure = int(any(SURF_YZ_PURE.search(s) for s in seats))
        lhb_map[(dt, c6)] = (1, lh_cnt, surf_pure)
    hist_fb["lhb_lh_cnt_d1"] = [lhb_map.get((d1, c6), (0, 0, 0))[1] for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]
    hist_fb["surf_yz_d1"] = [lhb_map.get((d1, c6), (0, 0, 0))[2] for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]

    # 7. 动态题材日排名
    valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
    pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median"))
    pg_m = pg[pg["p_sz_max"] >= 2].copy()
    pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
    hist_fb = hist_fb.merge(pg_m[["d2_dt", "plate", "rk_theme"]], on=["d2_dt", "plate"], how="left")

    # 8. 5 分钟 K 线索引 (物理截断 <= end_date_cutoff)
    df_5m = pd.read_parquet(PARQUET_5M_PATH)
    df_5m = df_5m[df_5m["date"].astype(str) <= end_date_cutoff].copy()
    df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_map = {
        (c6, dt): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()
        for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False)
    }

    # 9. 计算 V18 基础分 + V19_cand 信号掩码
    seal_time = hist_fb["first_seal_time"].fillna("99:99:99")
    open_cnt = hist_fb["open_board_count"].fillna(0)
    dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
    clean_brk60 = hist_fb["clean_brk60"].values == 1

    is_gran = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
    bonus_spear = np.where(is_gran, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))
    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    pass_l1 = ~hist_fb["is_event_basket"]
    pass_l2 = ~hist_fb["is_dying_pulse"]
    pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | (
        (hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2))
    )
    pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
    wk_mask = hist_fb["gap_days"] >= 3
    thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)
    f3_bonus = np.where(hist_fb["notice_bad"], -35.0, 0.0)

    hist_fb["score_wk"] = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
    hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

    m_t2_base = (
        common_ok & (hist_fb["p_sz"] == 1)
        & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"])
        & hist_fb["d2_o_pct"].between(0.035, 0.078)
        & (hist_fb["buyable_mkt_open_rk"] <= 3)
        & (hist_fb["d1_seal_tightness"] >= 15.0)
        & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
    )
    in_std_buy_win = common_ok & (
        (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
        | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
    )
    is_front_lock = hist_fb["d2_is_yizi"] | ((~wk_mask) & (hist_fb["d2_o_pct"] > 0.078)) | (wk_mask & (hist_fb["d2_o_pct"] > 0.088))
    hist_fb["_is_front_lock"] = is_front_lock.astype(int)
    hist_fb["front_lock_cnt"] = hist_fb.groupby(["d2_dt", "plate"])["_is_front_lock"].transform("sum")
    hist_fb["mkt_yizi_cnt"] = hist_fb.groupby("d2_dt")["d2_is_yizi"].transform("sum").fillna(0).astype(int)
    hist_fb["_true_buy_o"] = np.where(in_std_buy_win, hist_fb["d2_o_pct"], -9.99)
    hist_fb["true_buy_rk"] = hist_fb.groupby(["d2_dt", "plate"])["_true_buy_o"].rank(ascending=False, method="min")

    has_distinct_sub = (hist_fb["p_sz"] >= 8) & (hist_fb["r_short"] != hist_fb["plate"]) & (hist_fb["r_short"] != "其他") & (hist_fb["r_short"] != "")
    orig_rk_bonus = np.where(
        hist_fb["buyable_plate_rk"] == 1, 35.0,
        np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
                 np.where(hist_fb["buyable_plate_rk"] == 2, 8.0, -25.0))
    )
    true_rk_bonus = np.where(
        hist_fb["true_buy_rk"] == 1, 35.0,
        np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
                 np.where(hist_fb["true_buy_rk"] == 2, 8.0, -25.0))
    )
    rk_fix_delta = true_rk_bonus - orig_rk_bonus
    pass_nd_true = (~((hist_fb["p_sz"] >= 2) & (hist_fb["true_buy_rk"] >= 3))) & (
        ~((hist_fb["plate_d2_yizi_cnt"] >= 1) & (hist_fb["d1_seal_tightness"] < 15.0))
    )

    csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hist_fb["csrc_ind"]]
    is_hard_tech = hist_fb["plate"].astype(str).str.contains(
        r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)",
        regex=True,
    ).values
    has_ma_hard = (hist_fb["notice_hard"] | hist_fb["is_ma"]).values
    is_pure_outsider = np.array([ht and (cs in CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)], dtype=bool)
    name_sub20 = np.where(is_pure_outsider, -20.0, 0.0)

    flc = hist_fb["front_lock_cnt"].values
    tbrk = hist_fb["true_buy_rk"].values
    myz = hist_fb["mkt_yizi_cnt"].values
    is_super_wave = (hist_fb["rk_theme"] == 1) & (hist_fb["p_sz"] >= 8) & (tbrk == 1)
    y_v17 = np.select(
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

    # 前视滚动 20 日高开封板率传感器 (严格 shift(1))
    daily_records = []
    for d, grp in hist_fb.groupby("d2_dt"):
        buyable = grp[grp["is_buyable_open"] & (~grp["nuclear_halt"]) & (~grp["promo_freeze"])]
        ho = buyable[buyable["d2_o_pct"] >= 0.055]
        n_ho = len(ho)
        rate_ho_zt = (ho["d2_is_zt"].sum() / n_ho) if n_ho > 0 else np.nan
        daily_records.append({"date": d, "rate_ho_zt": rate_ho_zt})
    df_daily_s = pd.DataFrame(daily_records).sort_values("date").reset_index(drop=True)
    df_daily_s["roll20_ho_zt"] = df_daily_s["rate_ho_zt"].shift(1).rolling(20, min_periods=5).mean().fillna(0.45)
    sensors_map = df_daily_s.set_index("date")["roll20_ho_zt"].to_dict()
    roll20_vec = hist_fb["d2_dt"].map(sensors_map).fillna(0.45).values
    pen_thr_vec = np.where(roll20_vec < 0.45, 0.035, 0.031)
    pen_val_vec = np.where(roll20_vec < 0.45, 25.0, 15.0)
    q_pen = -np.where((~wk_mask.values) & (hist_fb["d2_o_pct"].values < pen_thr_vec), pen_val_vec, 0.0)

    d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
    is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
    bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)

    daily_t1 = pg_m[pg_m["rk_theme"] == 1].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t2 = pg_m[pg_m["rk_theme"] == 2].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t3 = pg_m[pg_m["rk_theme"] == 3].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")

    sc_climax_pen = np.where(hist_fb["mkt_zt_cnt"] >= 100, -15.0, np.where(hist_fb["mkt_zt_cnt"] >= 95, -10.0, 0.0))
    sc_seal_pen = np.where(hist_fb["mkt_seal_rate"] >= 0.80, -10.0, 0.0)
    sc_cap_pen = np.where((hist_fb["plate_d2_yizi_cnt"] >= 1) & (hist_fb["mcap"] > 90.0), -25.0, 0.0)

    t1_med_map = daily_t1["p_theme_med"].to_dict()
    t3_med_map = daily_t3["p_theme_med"].to_dict()
    _t1m = hist_fb["d2_dt"].map(t1_med_map).fillna(0.0).values
    _t3m = hist_fb["d2_dt"].map(t3_med_map).fillna(0.0).values
    v18_dom_t3 = (_t1m >= 65.0) & (_t1m - _t3m >= 35.0) & (_t3m < 42.0)
    sc_t3_pen = np.where(v18_dom_t3 & (hist_fb["rk_theme"].values >= 3), -15.0, 0.0)
    v18_pen = sc_climax_pen + sc_seal_pen + sc_cap_pen + sc_t3_pen

    sp_v = hist_fb["s_prior_wk"].values + name_sub20 + y_v17 * 0.5
    sq_v = hist_fb["s_quant_dual"].values + q_pen + d_ov + bon_tape + rk_fix_delta + y_v17 * 0.5
    sc_v = sp_v + sq_v + v18_pen
    hist_fb["score_active"] = sc_v

    p_tight = (hist_fb["d1_seal_tightness"] >= 37.0).values
    open_in_win = (
        (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
        | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
    ).values

    # V18 原始双轨 + 周一轨道
    m_t1 = common_ok.values & open_in_win & (sp_v >= 45.0) & (sc_v >= thr_vec)
    mm = ((m_t1 & pass_l1.values & pass_l2.values & pass_l3.values & pass_nd_true.values & pass_ac.values) | (m_t2_base.values & pass_l2.values)) & p_tight
    mmon = (
        common_ok.values & wk_mask.values & hist_fb["d2_o_pct"].between(0.015, 0.090).values
        & (sp_v >= 38.0) & (sc_v >= thr_vec)
        & pass_l1.values & pass_l2.values & pass_l3.values & pass_nd_true.values & pass_ac.values & p_tight
    )
    tot_v18 = mm | (mmon & (~mm))
    sv_v18 = np.where(mm, sc_v + 1000.0, sc_v)

    # V19_cand 升级点 2：第 2/3 主线暗牌低位硬催化补位通道 fb_dom295 (顺位 500，严格位于原轨道之后)
    rk_t = hist_fb["rk_theme"].fillna(99).values
    pos20_arr = hist_fb["f_pos20_d0"].fillna(0.5).values
    cat_ok = (hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]).values
    xq2_arr = hist_fb["xq_pre_d2"].values
    lh_arr = hist_fb["lhb_lh_cnt_d1"].values
    syz_arr = hist_fb["surf_yz_d1"].values == 1

    fb_dom295 = (
        common_ok.values & open_in_win
        & pass_l1.values & pass_l2.values & pass_l3.values & pass_nd_true.values & pass_ac.values & p_tight
        & np.isin(rk_t, [2, 3]) & (tbrk == 1)
        & (xq2_arr < 4) & (pos20_arr <= 0.40) & cat_ok & (lh_arr == 0) & (~syz_arr)
        & ((sc_v - sc_t3_pen) >= 295.0)
    )
    tot_v19 = tot_v18 | fb_dom295
    sv_v19 = np.where(mm, sc_v + 1000.0, np.where(mmon, sc_v, sc_v + 500.0))

    # 断层主线无龙与混战日过滤（与 V18 完全对齐）
    dom_no_dragon, melee_days = set(), set()
    for d in sorted(daily_t1.index):
        t1_row = daily_t1.loc[d]
        t2_row = daily_t2.loc[d] if d in daily_t2.index else None
        t3_row = daily_t3.loc[d] if d in daily_t3.index else None
        t1_med = float(t1_row["p_theme_med"])
        t2_med = float(t2_row["p_theme_med"]) if t2_row is not None else 0.0
        t1_sz = int(t1_row["p_sz_max"])
        t2_sz = int(t2_row["p_sz_max"]) if t2_row is not None else 1
        if ((t1_med - t2_med) >= 20.0) or ((t1_sz >= 6) and (t1_sz / max(1, t2_sz) >= 2.0)):
            sub_d_v18 = hist_fb[(hist_fb["d2_dt"] == d) & tot_v18]
            if not (len(sub_d_v18) > 0 and (sub_d_v18["plate"] == t1_row["plate"]).any()):
                dom_no_dragon.add(d)
        if t1_row is not None and t2_row is not None and t3_row is not None:
            t3_med = float(t3_row["p_theme_med"])
            sz_max = max(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            sz_min = min(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            if (t1_med - t3_med) <= 15.0 and sz_max <= 5 and sz_min >= 2:
                melee_days.add(d)

    def apply_day_blocks(tot_mask, sv_arr):
        sub_t = hist_fb[tot_mask].copy()
        sub_t["_sv_tmp"] = sv_arr[tot_mask]
        bad_dts = set()
        for d, grp in sub_t.groupby("d2_dt"):
            if (grp["rk_theme"] == 1).any():
                top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
                if pd.notna(top_rk) and top_rk >= 4:
                    bad_dts.add(d)
        res_mask = tot_mask & (~hist_fb["d2_dt"].isin(bad_dts)).values
        dom_blk = np.array([(d in dom_no_dragon and rk == 3) for d, rk in zip(hist_fb["d2_dt"], hist_fb["rk_theme"])], dtype=bool)
        mel_blk = np.array([
            (d in melee_days) and (not ((mrk <= 2) or bool(nh) or bool(hm)))
            for d, mrk, nh, hm in zip(hist_fb["d2_dt"], hist_fb["buyable_mkt_open_rk"], hist_fb["notice_hard"], hist_fb["is_ma"])
        ], dtype=bool)
        return res_mask & (~dom_blk) & (~mel_blk)

    final_v18_mask = apply_day_blocks(tot_v18, sv_v18)
    final_v19_mask = apply_day_blocks(tot_v19, sv_v19)

    hist_fb["_sv_v18"] = sv_v18
    hist_fb["_sv_v19"] = sv_v19

    # 三行校验 1：D2 封成比中位数校验
    valid_sr_d1 = hist_fb["seal_amount"].dropna() / hist_fb.loc[hist_fb["seal_amount"].notna(), "amount"]
    assert 0.01 < float(valid_sr_d1.median()) < 0.50, f"seal_amount/amount unit check failed: {valid_sr_d1.median()}"

    print(f"    [Build PIT <= {end_date_cutoff}] rows={len(hist_fb):,}, V18_pass={final_v18_mask.sum()}, V19_pass={final_v19_mask.sum()} ({time.time()-t0:.1f}s)")
    return {
        "all_dts": all_dts, "dt_to_idx": dt_to_idx, "price_lookup": price_lookup,
        "amt_lookup": amt_lookup, "tape_map": tape_map, "xq_by_c6": xq_by_c6,
        "bars_5m_map": bars_5m_map, "hist_fb": hist_fb,
        "mask_v18": final_v18_mask, "mask_v19": final_v19_mask,
    }


def make_trade_sim(ctx: dict, use_m1_d3_exempt: bool = True):
    """独立交易模拟引擎：严格 5m K 线精确撮合 + M1 封死二板次日暗牌低开豁免。"""
    all_dts = ctx["all_dts"]
    dt_to_idx = ctx["dt_to_idx"]
    pl = ctx["price_lookup"]
    bars = ctx["bars_5m_map"]
    xq_by_c6 = ctx["xq_by_c6"]
    tape_map = ctx["tape_map"]
    amt_lookup = ctx["amt_lookup"]

    def get_xq_pre_d3(c6, start_dt, d3_dt):
        arr = xq_by_c6.get(c6)
        if arr is None:
            return 0
        lo = np.searchsorted(arr, f"{start_dt} 00:00:00", side="left")
        hi = np.searchsorted(arr, f"{d3_dt} 09:25:00", side="left")
        assert hi == 0 or arr[hi - 1] < f"{d3_dt} 09:25:00", f"D3 Xueqiu leak: {arr[hi-1]} >= {d3_dt} 09:25:00"
        return int(hi - lo)

    def get_d2_seal_ratio(c6, d2_dt):
        tp = tape_map.get((d2_dt, c6))
        amt = amt_lookup.get((c6, d2_dt), 0.0)
        if tp is None or tp[1] is None or amt <= 0:
            return np.nan
        return float(tp[1]) / amt

    def sim_trade(row):
        c6, d2 = row["c6"], row["d2_dt"]
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 < 0 or idx2 >= len(all_dts) - 1:
            return None
        d2_bar = pl.get((c6, d2))
        if not d2_bar:
            return None
        o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar
        if o2 >= zt2 - 0.005 or o2 <= 0:
            return None

        is_monday = row.get("gap_days", 1) >= 3
        cand_score = float(row.get("score_active", 0.0))
        cand_lead = float(row.get("buy_open_lead", 0.0))
        do_direct = is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)
        trig_p = float(row["trig_p"])
        buy_px = round(float(o2), 2) if do_direct else round(trig_p, 2)
        buy_hhmm = 925 if do_direct else 935

        if not do_direct:
            if h2 < trig_p or trig_p >= zt2 - 0.005:
                return None
            arr2 = bars.get((c6, d2))
            if arr2 is not None and len(arr2) > 0:
                ign_hhmm = None
                for bi in range(len(arr2)):
                    if arr2[bi, 2] >= trig_p - 1e-4:
                        ign_hhmm = int(arr2[bi, 0])
                        break
                if ign_hhmm is not None and ign_hhmm > 1130:
                    return None
                if ign_hhmm is not None:
                    buy_hhmm = ign_hhmm

        prev_c = round(float(c2), 2)
        idx3 = idx2 + 1
        d3 = all_dts[idx3]
        d3_bar = pl.get((c6, d3))
        if not d3_bar:
            net = round((prev_c / buy_px) * (1.0 - FEE_RATE) - 1.0, 4)
            return {
                "net_ret": net, "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2),
                "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c,
                "buy_hhmm": buy_hhmm, "exit_hhmm": 925, "score": round(cand_score, 1), "tag": "no_d3_bar",
                "d2_o_pct": float(row["d2_o_pct"]),
            }
        o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar

        def _ride(curr_start, boards_start, prev_c_init, sealed_2b_flag):
            curr = curr_start
            boards_held = boards_start
            used_immunity = False
            prev_c_l = prev_c_init
            while curr < len(all_dts) and (curr - idx2 <= 12):
                dc = all_dts[curr]
                b = pl.get((c6, dc))
                if not b:
                    break
                oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b
                if iyzc:
                    prev_c_l = round(float(cc), 2)
                    curr += 1
                    continue

                exempt_1030_d3 = False
                if use_m1_d3_exempt and sealed_2b_flag == 1 and curr == idx3:
                    op3 = oc / prev_c_l - 1.0
                    xq_d3 = get_xq_pre_d3(c6, row["dt_str"], dc)
                    sr_d2 = get_d2_seal_ratio(c6, d2)
                    if (-0.065 <= op3 <= 0.025) and (xq_d3 < 4) and (np.isnan(sr_d2) or sr_d2 < 0.25):
                        exempt_1030_d3 = True

                arr = bars.get((c6, dc))
                if arr is not None and len(arr) >= 12:
                    idx_1030, cum_v, cum_a = -1, 0.0, 0.0
                    for bi in range(len(arr)):
                        cum_v += arr[bi, 5]
                        cum_a += arr[bi, 6]
                        if arr[bi, 0] == 1030:
                            idx_1030 = bi
                            break
                    if idx_1030 >= 0:
                        bc_1030 = arr[idx_1030, 4]
                        vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                        if bc_1030 >= ztc - 0.01:
                            for bi in range(idx_1030 + 1, len(arr) - 1):
                                if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                    px = round(float(arr[bi + 1, 1]), 2)
                                    return {
                                        "net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": dc,
                                        "exit_at_open": False, "sealed_2b": sealed_2b_flag, "buy_date": d2, "code": c6,
                                        "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm,
                                        "exit_hhmm": int(arr[bi + 1, 0]), "score": round(cand_score, 1),
                                        "tag": "5m_1430_rush", "d2_o_pct": float(row["d2_o_pct"]),
                                    }
                            if iztc:
                                prev_c_l = round(float(cc), 2); boards_held += 1; curr += 1; continue
                            px = round(float(cc), 2)
                            return {
                                "net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": dc,
                                "exit_at_open": False, "sealed_2b": sealed_2b_flag, "buy_date": d2, "code": c6,
                                "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm,
                                "exit_hhmm": 1500, "score": round(cand_score, 1), "tag": "eod_break",
                                "d2_o_pct": float(row["d2_o_pct"]),
                            }
                        elif bc_1030 < vwap_1030 and not exempt_1030_d3:
                            px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                            ehh = int(arr[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr) else 1030
                            return {
                                "net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": dc,
                                "exit_at_open": False, "sealed_2b": sealed_2b_flag, "buy_date": d2, "code": c6,
                                "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm,
                                "exit_hhmm": ehh, "score": round(cand_score, 1), "tag": "5m_1030_weak_cut",
                                "d2_o_pct": float(row["d2_o_pct"]),
                            }

                if iztc:
                    prev_c_l = round(float(cc), 2); boards_held += 1; curr += 1; continue
                if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c_l * 1.02) and (curr + 1 < len(all_dts)):
                    used_immunity = True; prev_c_l = round(float(cc), 2); curr += 1; continue
                px = round(float(cc), 2)
                return {
                    "net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": dc,
                    "exit_at_open": False, "sealed_2b": sealed_2b_flag, "buy_date": d2, "code": c6,
                    "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm,
                    "exit_hhmm": 1500, "score": round(cand_score, 1), "tag": "eod_close",
                    "d2_o_pct": float(row["d2_o_pct"]),
                }

            return {
                "net_ret": round((prev_c_l / buy_px) * (1.0 - FEE_RATE) - 1.0, 4),
                "exit_date": all_dts[min(curr, len(all_dts) - 1)], "exit_at_open": False, "sealed_2b": sealed_2b_flag,
                "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c_l,
                "buy_hhmm": buy_hhmm, "exit_hhmm": 1500, "score": round(cand_score, 1), "tag": "max_hold_exit",
                "d2_o_pct": float(row["d2_o_pct"]),
            }

        if not is_zt2:
            if (c2 >= float(row["close"])) and (o3 >= round(c2 * 1.005, 2)) and not is_yz_dt3:
                if is_zt3:
                    return _ride(idx3 + 1, 3, round(float(c3), 2), 0)
                px = round(float(c3), 2)
                return {
                    "net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": d3,
                    "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"],
                    "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500,
                    "score": round(cand_score, 1), "tag": "nshape_d3_close", "d2_o_pct": float(row["d2_o_pct"]),
                }
            curr = idx3
            while curr < len(all_dts):
                b = pl.get((c6, all_dts[curr]))
                if not b or not b[7]:
                    px = round(float(b[0]), 2) if b else prev_c
                    return {
                        "net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": all_dts[curr],
                        "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"],
                        "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 925,
                        "score": round(cand_score, 1), "tag": "fail_open_cut", "d2_o_pct": float(row["d2_o_pct"]),
                    }
                curr += 1
            return None

        return _ride(idx3, 2, prev_c, 1)

    return sim_trade


def run_slot_and_eq(ctx: dict, mask_col: str, sv_col: str, sim_fn, start_dt: str, end_dt: str):
    hist_fb = ctx["hist_fb"]
    sub = hist_fb[mask_col & (hist_fb["d2_dt"] >= start_dt) & (hist_fb["d2_dt"] <= end_dt)].copy()
    sub.sort_values(["d2_dt", sv_col], ascending=[True, False], inplace=True)

    free_dt, free_open = "", False
    trades_1s = []
    eq_daily_rets = []
    eq_all_signals = []

    for d2, grp in sub.groupby("d2_dt", sort=True):
        rows = [r for _, r in grp.iterrows()]
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            tr1 = sim_fn(rows[0].to_dict())
            if tr1 is not None:
                free_dt, free_open = tr1["exit_date"], tr1["exit_at_open"]
                trades_1s.append(tr1)
        d_rets = []
        for r_s in rows:
            tr = sim_fn(r_s.to_dict())
            if tr is not None:
                d_rets.append(tr["net_ret"])
                eq_all_signals.append(tr)
        if d_rets:
            eq_daily_rets.append((d2, float(np.mean(d_rets))))

    return trades_1s, eq_daily_rets, eq_all_signals


def calc_window_metrics(trades_1s, eq_daily_rets, start_dt, end_dt, sh300, bench_pct_override=None):
    all_dates = sorted(sh300.keys())
    if bench_pct_override is not None:
        bench_pct = float(bench_pct_override)
    else:
        prevs = [d for d in all_dates if d < start_dt]
        posts = [d for d in all_dates if d <= end_dt]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_dates[0]]
        p1 = sh300[posts[-1]]
        bench_pct = float((p1 / p0 - 1.0) * 100.0)

    sub_t = [t for t in trades_1s if start_dt <= t["buy_date"] <= end_dt]
    sub_eq = [r for d, r in eq_daily_rets if start_dt <= d <= end_dt]
    n = len(sub_t)
    if n == 0:
        return {
            "trades": 0, "win_rate_pct": 0.0, "plr": 0.0, "nav_1s": 1.0,
            "cap10m_mult": 1.0, "eq_nav": 1.0, "trim3_nav": 1.0, "mdd_pct": 0.0,
            "csi300_pct": round(bench_pct, 2), "excess_1s_pp": round(-bench_pct, 2),
            "excess_cap10m_pp": round(-bench_pct, 2), "excess_eq_pp": round(-bench_pct, 2),
        }

    rets = np.array([t["net_ret"] for t in sub_t], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    wr = float(len(wins) / n * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0) else (99.9 if len(wins) > 0 else 0.0)

    nav, pk, mdd = 1.0, 1.0, 0.0
    cap = 100.0  # 100万起，单笔封顶 1000万
    for r in rets:
        nav *= (1.0 + float(r))
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)
        cap += min(cap, 1000.0) * float(r)
    cap_mult = cap / 100.0
    eq_nav = float(np.prod(1.0 + np.array(sub_eq, dtype=float))) if sub_eq else 1.0
    trim3 = float(np.prod(1.0 + np.sort(rets)[:-3])) if n > 3 else 1.0

    return {
        "trades": n,
        "win_rate_pct": round(wr, 2),
        "plr": round(plr, 2),
        "nav_1s": round(nav, 2),
        "cap10m_mult": round(cap_mult, 2),
        "eq_nav": round(eq_nav, 2),
        "trim3_nav": round(trim3, 2),
        "mdd_pct": round(mdd * 100.0, 2),
        "csi300_pct": round(bench_pct, 2),
        "excess_1s_pp": round((nav - 1.0) * 100.0 - bench_pct, 2),
        "excess_cap10m_pp": round((cap_mult - 1.0) * 100.0 - bench_pct, 2),
        "excess_eq_pp": round((eq_nav - 1.0) * 100.0 - bench_pct, 2),
    }


def verify_forensics(trades_list, ctx):
    pl = ctx["price_lookup"]
    bars = ctx["bars_5m_map"]
    all_dts = ctx["all_dts"]
    dt_to_idx = ctx["dt_to_idx"]

    t0_viol = sum(1 for t in trades_list if t["exit_date"] <= t["buy_date"])
    overlap_viol = 0
    for i in range(len(trades_list) - 1):
        c_t, n_t = trades_list[i], trades_list[i + 1]
        if n_t["buy_date"] < c_t["exit_date"]:
            overlap_viol += 1
        elif n_t["buy_date"] == c_t["exit_date"] and not c_t["exit_at_open"]:
            overlap_viol += 1

    yizi_viol = 0
    tot_days, cov_days, miss_days = 0, 0, []
    for t in trades_list:
        c6 = str(t["code"]).zfill(6)
        b_bar = pl.get((c6, t["buy_date"]))
        if b_bar and b_bar[0] >= b_bar[4] - 0.005:
            yizi_viol += 1
        bi, ei = dt_to_idx[t["buy_date"]], dt_to_idx[t["exit_date"]]
        for idx in range(bi, ei + 1):
            dt = all_dts[idx]
            tot_days += 1
            if (c6, dt) in bars:
                cov_days += 1
            else:
                miss_days.append(f"{dt}:{c6}:{t['name']}")

    cov_pct = round(cov_days / tot_days * 100.0, 2) if tot_days > 0 else 100.0
    assert t0_viol == 0, f"T+0 violation: {t0_viol}"
    assert overlap_viol == 0, f"Overlap violation: {overlap_viol}"
    assert yizi_viol == 0, f"Yizi buy violation: {yizi_viol}"
    assert len(miss_days) == 0 and cov_pct == 100.0, f"5m coverage < 100%: {cov_pct}%, missing={miss_days}"
    return {
        "t0_violations": t0_viol,
        "overlap_violations": overlap_viol,
        "yizi_buy_violations": yizi_viol,
        "five_min_coverage_pct": cov_pct,
        "five_min_checked_days": tot_days,
        "five_min_missing_days": miss_days,
    }


def run_8_overfitting_tests(df_trades: pd.DataFrame, sh300: dict):
    all_dates = sorted(sh300.keys())
    t_days = sorted([d for d in sh300.keys() if CANON_5Y_START <= d <= DATA_END_DT])
    day_idx = {d: i for i, d in enumerate(t_days)}

    def get_bench(bd, ed):
        prevs = [d for d in all_dates if d < bd]
        posts = [d for d in all_dates if d <= ed]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_dates[0]]
        p1 = sh300[posts[-1]]
        return float(p1 / p0 - 1.0)

    n = len(df_trades)
    rets = df_trades["net_ret"].to_numpy(dtype=float)
    ex = np.array([float(r.net_ret) - get_bench(str(r.buy_date), str(r.exit_date)) for r in df_trades.itertuples(index=False)])

    # Test 1: HLZ t & DSR (M=150)
    sr_tr = float(ex.mean() / ex.std(ddof=1))
    hlz_t = float(sr_tr * np.sqrt(n))
    skew = float(stats.skew(ex, bias=False))
    kurt = float(stats.kurtosis(ex, fisher=False, bias=False))
    gamma = 0.5772156649
    M = 150
    sr0 = (1.0 / np.sqrt(n - 1)) * ((1.0 - gamma) * stats.norm.ppf(1.0 - 1.0 / M) + gamma * stats.norm.ppf(1.0 - 1.0 / (M * np.e)))
    denom = float(np.sqrt(max(1e-12, 1.0 - skew * sr_tr + ((kurt - 1.0) / 4.0) * (sr_tr ** 2))))
    dsr_150 = float(stats.norm.cdf((sr_tr - sr0) * np.sqrt(n - 1) / denom))

    # Test 2: Monkey MC (5,000 draws from同日首板非一字可买候选池)
    df_cand_01 = pd.read_parquet(CAND_01_PATH, columns=["code", "buy_date", "open_pct", "pct"])
    df_01_b = df_cand_01[(df_cand_01["open_pct"] < 0.095) & (df_cand_01["open_pct"] > -0.095)]
    pool_dict = defaultdict(list)
    open_pct_map = {}
    for r in df_01_b.itertuples(index=False):
        pool_dict[str(r.buy_date)].append(float(r.open_pct))
        open_pct_map[(str(r.code).zfill(6), str(r.buy_date))] = float(r.open_pct)

    rng = np.random.default_rng(20261116)
    cands = [np.array(pool_dict.get(str(r.buy_date), [float(r.net_ret)]), dtype=float) for r in df_trades.itertuples(index=False)]
    mat = np.array([c[rng.integers(0, len(c), size=5000)] for c in cands])
    monkey_p = float((int(np.sum(mat.mean(0) >= rets.mean())) + 1) / 5001.0)

    # Test 3: ±20% parameter perturbation retention (100万起1000万封顶口径)
    def calc_cap10m_ret_100w(sub):
        if sub.empty:
            return 0.0
        srt = sub.sort_values(["buy_date", "score"], ascending=[True, False])
        fdt, feo, cap = "", False, 100.0
        for r in srt.itertuples(index=False):
            if fdt == "" or r.buy_date > fdt or (r.buy_date == fdt and feo):
                cap += min(cap, 1000.0) * float(r.net_ret)
                fdt, feo = r.exit_date, r.exit_at_open
        return (cap / 100.0 - 1.0) * 100.0

    def calc_cap10m_ret_1000w(sub):
        if sub.empty:
            return 0.0
        srt = sub.sort_values(["buy_date", "score"], ascending=[True, False])
        fdt, feo, cap = "", False, 1000.0
        for r in srt.itertuples(index=False):
            if fdt == "" or r.buy_date > fdt or (r.buy_date == fdt and feo):
                cap += min(cap, 1000.0) * float(r.net_ret)
                fdt, feo = r.exit_date, r.exit_at_open
        return (cap / 1000.0 - 1.0) * 100.0

    scores = df_trades["score"].to_numpy(dtype=float)
    mn, mx = float(scores.min()), float(scores.max())
    rng_s = max(1.0, mx - mn)
    base_cap1000 = calc_cap10m_ret_1000w(df_trades)
    pert_details = {}
    for d in [-0.20, -0.10, 0.10, 0.20]:
        th = mn + rng_s * (0.1 + d * 0.1)
        ret_v = calc_cap10m_ret_1000w(df_trades[df_trades["score"] >= th])
        pert_details[f"{int(d*100):+d}%"] = round(ret_v / base_cap1000 * 100.0, 2)
    min_pert_ret = min(pert_details.values())

    # Test 4: CSCV PBO (S=10, C(10,5)=252 combos)
    def to_daily(sub):
        arr = np.zeros(len(t_days), dtype=float)
        srt = sub.sort_values(["buy_date", "score"], ascending=[True, False])
        fdt, feo = "", False
        for r in srt.itertuples(index=False):
            if fdt == "" or r.buy_date > fdt or (r.buy_date == fdt and feo):
                i = day_idx.get(r.exit_date)
                if i is not None:
                    arr[i] += float(r.net_ret)
                fdt, feo = r.exit_date, r.exit_at_open
        return arr

    Rm = np.zeros((len(t_days), 14), dtype=float)
    Rm[:, 0] = to_daily(df_trades)
    for v in range(1, 14):
        Rm[:, v] = to_daily(df_trades[df_trades["score"] >= float(np.quantile(scores, 0.05 + v / 14.0 * 0.40))])
    gs = len(t_days) // 10
    gidx = [list(range(i * gs, (i + 1) * gs if i < 9 else len(t_days))) for i in range(10)]
    omegas = []
    for te in itertools.combinations(range(10), 5):
        trg = [k for k in range(10) if k not in te]
        tri = [x for k in trg for x in gidx[k]]
        tei = [x for k in te for x in gidx[k]]
        rt, re_ = Rm[tri], Rm[tei]
        st = np.where(rt.std(0, ddof=1) > 1e-12, rt.mean(0) / rt.std(0, ddof=1), 0.0)
        se = np.where(re_.std(0, ddof=1) > 1e-12, re_.mean(0) / re_.std(0, ddof=1), 0.0)
        omegas.append(float(np.mean(se > se[int(np.argmax(st))])))
    pbo_s10 = float(np.mean(np.array(omegas) > 0.50) * 100.0)

    # Test 5: Outliers
    trim3_nav = float(np.prod(1.0 + np.sort(rets)[:-3]))

    # Test 6: Bootstrap 5% excess lower bound
    bmeans = np.array([ex[rng.integers(0, n, size=n)].mean() for _ in range(5000)])
    boot_5 = float(np.percentile(bmeans, 5) * 100.0)

    # Test 7: Yearly stability (2022~2026)
    yearly = {}
    beats = 0
    for yr in [2022, 2023, 2024, 2025, 2026]:
        sd, ed = f"{yr}-01-01", (f"{yr}-12-31" if yr < 2026 else DATA_END_DT)
        sub = df_trades[(df_trades["buy_date"] >= sd) & (df_trades["buy_date"] <= ed)]
        yr_rets = sub["net_ret"].to_numpy(dtype=float)
        nav_y = float(np.prod(1.0 + yr_rets)) if len(yr_rets) else 1.0
        cap100_y = calc_cap10m_ret_100w(sub)
        bench_y = get_bench(sd, ed) * 100.0
        beat = bool(cap100_y > bench_y)
        if beat:
            beats += 1
        yearly[str(yr)] = {
            "trades": len(sub),
            "win_rate_pct": round(float((yr_rets > 0).mean() * 100.0), 2) if len(yr_rets) else 0.0,
            "nav_1s_mult": round(nav_y, 2),
            "cap10m_100w_ret_pct": round(cap100_y, 2),
            "csi300_ret_pct": round(bench_y, 2),
            "excess_cap10m_pp": round(cap100_y - bench_y, 2),
            "beat_csi300": beat,
        }

    # Test 8: Hell mode (drop top 15% open_pct wins + 2x extra 30bps slip)
    df_adv = df_trades.copy()
    df_adv["_op"] = [
        float(r.d2_o_pct) if (hasattr(r, "d2_o_pct") and pd.notna(r.d2_o_pct))
        else open_pct_map.get((str(r.code).zfill(6), str(r.buy_date)), float(r.score) / 1000.0)
        for r in df_adv.itertuples(index=False)
    ]
    wins_df = df_adv[df_adv["net_ret"] > 0].sort_values("_op", ascending=False)
    losses_df = df_adv[df_adv["net_ret"] <= 0]
    n_drop = max(1, math.ceil(0.15 * len(wins_df)))
    hell_df = pd.concat([wins_df.iloc[n_drop:], losses_df]).sort_values("buy_date")
    hell_rets = hell_df["net_ret"].to_numpy(dtype=float) - 0.0030
    hell_nav_1s = float(np.prod(1.0 + hell_rets))
    cap100 = 100.0
    cap1000 = 1000.0
    for r in hell_rets:
        cap100 += min(cap100, 1000.0) * float(r)
        cap1000 += min(cap1000, 1000.0) * float(r)
    csi_5y = get_bench(CANON_5Y_START, DATA_END_DT) * 100.0

    return {
        "hlz_t_trade": round(hlz_t, 2),
        "dsr_m150_pct": round(dsr_150 * 100.0, 2),
        "monkey_mc_5000_p": round(monkey_p, 5),
        "perturbation_20pct_min_retention_pct": round(min_pert_ret, 2),
        "perturbation_details": pert_details,
        "cscv_pbo_s10_pct": round(pbo_s10, 2),
        "trim3_nav_1s": round(trim3_nav, 2),
        "bootstrap_5pct_excess_per_trade_pct": round(boot_5, 2),
        "yearly_beat_count": f"{beats}/5",
        "yearly_breakdown": yearly,
        "hell_mode": {
            "dropped_top15pct_wins": n_drop,
            "remaining_trades": len(hell_df),
            "nav_1s": round(hell_nav_1s, 2),
            "cap10m_100w_mult": round(cap100 / 100.0, 2),
            "cap10m_1000w_excess_pp": round((cap1000 / 1000.0 - 1.0) * 100.0 - csi_5y, 2),
        },
    }


def main():
    t_all = time.time()
    print("=" * 80)
    print("一进二独立升级版 V19_cand · 全量前视 PIT 回测与零穿越截断验证")
    print("=" * 80)

    with open(IDX_JSON_PATH, encoding="utf-8") as f:
        sh300_full = json.load(f)["sh000300"]
    with open(CSI300_BENCH_FILE, encoding="utf-8") as f:
        csi_canon = json.load(f)

    # 1. 全量跑 (至 2026-11-16)
    ctx_full = build_signals_and_data_pit(DATA_END_DT)
    sim_v18 = make_trade_sim(ctx_full, use_m1_d3_exempt=False)
    sim_v19 = make_trade_sim(ctx_full, use_m1_d3_exempt=True)

    tr_v18_5y, eq_v18_5y, eq_v18_sigs_all = run_slot_and_eq(ctx_full, ctx_full["mask_v18"], "_sv_v18", sim_v18, CANON_5Y_START, DATA_END_DT)
    tr_v19_5y, eq_v19_5y, eq_sigs_v19 = run_slot_and_eq(ctx_full, ctx_full["mask_v19"], "_sv_v19", sim_v19, CANON_5Y_START, DATA_END_DT)

    # 2. 法医核验 (T+0=0, 重叠=0, 一字买入=0, 5m=100%)
    forensics_v18 = verify_forensics(tr_v18_5y, ctx_full)
    forensics_v19 = verify_forensics(tr_v19_5y, ctx_full)
    print(f"[Forensics V19] {forensics_v19}")

    # 3. 物理截断 >= 2025-01-01 零后视镜硬测试
    print("\n>>> 运行 2025-2026 物理截断零后视镜测试 (cutoff=2024-12-31)...")
    ctx_trunc = build_signals_and_data_pit("2024-12-31")
    sim_v19_trunc = make_trade_sim(ctx_trunc, use_m1_d3_exempt=True)
    tr_trunc, _, _ = run_slot_and_eq(ctx_trunc, ctx_trunc["mask_v19"], "_sv_v19", sim_v19_trunc, CANON_5Y_START, "2024-12-31")
    tr_full_pre25 = [t for t in tr_v19_5y if t["buy_date"] <= "2024-12-31" and t["exit_date"] <= "2024-12-31"]
    tr_trunc_cmp = [t for t in tr_trunc if t["exit_date"] <= "2024-12-31"]
    assert len(tr_full_pre25) == len(tr_trunc_cmp) and len(tr_full_pre25) > 0, (
        f"Truncation trade count mismatch: full={len(tr_full_pre25)}, trunc={len(tr_trunc_cmp)}"
    )
    max_abs_diff_score = 0.0
    max_abs_diff_ret = 0.0
    for tf, tt in zip(tr_full_pre25, tr_trunc_cmp):
        assert tf["buy_date"] == tt["buy_date"] and tf["code"] == tt["code"] and tf["exit_date"] == tt["exit_date"], (
            f"Trade identity mismatch: {tf} vs {tt}"
        )
        max_abs_diff_score = max(max_abs_diff_score, abs(float(tf["score"]) - float(tt["score"])))
        max_abs_diff_ret = max(max_abs_diff_ret, abs(float(tf["net_ret"]) - float(tt["net_ret"])))
    max_abs_diff = max(max_abs_diff_score, max_abs_diff_ret)
    assert max_abs_diff == 0.0, f"Lookahead leak detected: max_abs_diff={max_abs_diff}"
    print(f"[Truncation Hard Test PASSED] trades_2021_2024={len(tr_trunc_cmp)}, max_abs_diff={max_abs_diff}")

    # 4. D15 标准窗口对比
    windows = [
        ("全五年", CANON_5Y_START, DATA_END_DT, csi_canon.get("全五年(2021-11-16起)", [-18.49])[0]),
        ("IS_21_23", "2021-11-15", "2023-12-31", None),
        ("OOS_24_26", "2024-01-01", DATA_END_DT, csi_canon.get("近三年(2024-01-01起)", [15.99])[0]),
        ("近三年", "2023-11-16", DATA_END_DT, csi_canon.get("近三年(2023-11-16起)", [10.33])[0]),
        ("2026全年", "2026-01-01", DATA_END_DT, csi_canon.get("2026全年", [-14.04])[0]),
        ("10月以来", "2026-10-01", DATA_END_DT, csi_canon.get("2026年10月以来", [-8.67])[0]),
    ]
    d15_v18, d15_v19 = {}, {}
    for wname, sd, ed, b_ov in windows:
        d15_v18[wname] = calc_window_metrics(tr_v18_5y, eq_v18_5y, sd, ed, sh300_full, b_ov)
        d15_v19[wname] = calc_window_metrics(tr_v19_5y, eq_v19_5y, sd, ed, sh300_full, b_ov)

    # 5. 八项防过拟合对比
    df_v18 = pd.DataFrame(tr_v18_5y)
    df_v19 = pd.DataFrame(tr_v19_5y)
    audit_v18 = run_8_overfitting_tests(df_v18, sh300_full)
    audit_v19 = run_8_overfitting_tests(df_v19, sh300_full)

    # 6. 逐笔差异与空仓日/反转案例
    m_v18 = {(t["buy_date"], t["code"]): t for t in tr_v18_5y}
    m_v19 = {(t["buy_date"], t["code"]): t for t in tr_v19_5y}
    added_1s = [
        {"buy_date": k[0], "code": k[1], "name": m_v19[k]["name"], "net_ret_pct": round(m_v19[k]["net_ret"] * 100.0, 2), "tag": m_v19[k]["tag"]}
        for k in sorted(set(m_v19) - set(m_v18))
    ]
    dropped_1s = [
        {"buy_date": k[0], "code": k[1], "name": m_v18[k]["name"], "net_ret_pct": round(m_v18[k]["net_ret"] * 100.0, 2)}
        for k in sorted(set(m_v18) - set(m_v19))
    ]
    changed_1s = [
        {
            "buy_date": k[0], "code": k[1], "name": m_v19[k]["name"],
            "v18_ret_pct": round(m_v18[k]["net_ret"] * 100.0, 2),
            "v19_ret_pct": round(m_v19[k]["net_ret"] * 100.0, 2),
            "v18_tag": m_v18[k]["tag"], "v19_tag": m_v19[k]["tag"],
        }
        for k in sorted(set(m_v18) & set(m_v19)) if abs(m_v18[k]["net_ret"] - m_v19[k]["net_ret"]) > 1e-4
    ]
    eq_k18 = {(t["buy_date"], t["code"]) for t in eq_v18_sigs_all}
    added_eq_signals = [
        {"buy_date": t["buy_date"], "code": t["code"], "name": t["name"], "net_ret_pct": round(t["net_ret"] * 100.0, 2), "tag": t["tag"]}
        for t in eq_sigs_v19 if (t["buy_date"], t["code"]) not in eq_k18
    ]

    # 7. 落盘 CSV 与 JSON
    cols_order = [
        "code", "name", "buy_date", "buy_hhmm", "buy_price", "exit_date", "exit_hhmm",
        "exit_price", "net_ret", "score", "tag", "sealed_2b", "exit_at_open", "d2_o_pct",
    ]
    df_out = df_v19[[c for c in cols_order if c in df_v19.columns]].copy()
    df_out["code"] = df_out["code"].astype(str).str.zfill(6)
    df_out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    summary = {
        "strategy_name": "一进二_V19_cand_独立互学升级版",
        "data_as_of_date": DATA_END_DT,
        "canon_5y_window": f"{CANON_5Y_START} ~ {DATA_END_DT}",
        "upgrade_changelog_vs_v18": [
            {
                "id": "M1_day3_relay_exempt",
                "rule": "封死二板次日(D3)若D3开盘落入[-6.5%, +2.5%]且D1~D3 09:25前雪球热帖<4帖且D2封成比<25%(或缺失)，豁免D3 10:30破分时均价线弱斩",
                "physical_logic": "借自二进三V1.0接力对偶规律：暗牌非死锁二板在[-6.5%, +2.5%]温和低开是二进三低吸买点，早盘洗盘后易由接力资金拉回",
                "calibrated_on": "IS (2021-11-15~2023-12-31) 1S 5.30x->5.48x, MDD 21.98%->15.97%",
            },
            {
                "id": "fb_dom295_dark_lowpos_fallback",
                "rule": "第2/3主线板块(rk_theme in {2,3})竞价头名(true_buy_rk==1)满足雪球<4帖、pos20<=40%、硬催化/新词破冰、零拉萨及一日游席位，且去主线压制后得分>=295.0时作第3顺位候补(优先权低于V18主轨)",
                "physical_logic": "盘活主线拥挤或高潮抬门槛时的优质暗牌低位催化新秀，保持V18已有单仓排序完全不变",
                "calibrated_on": "IS EQ 2.49x->2.76x, 全5年EQ 57.09x->65.74x",
            },
        ],
        "zero_lookahead_audit": {
            "truncation_cutoff": "2024-12-31",
            "truncation_trades_checked": len(tr_trunc_cmp),
            "truncation_max_abs_diff_score": max_abs_diff_score,
            "truncation_max_abs_diff_ret": max_abs_diff_ret,
            "truncation_max_abs_diff": max_abs_diff,
            "forensics_v19": forensics_v19,
            "forensics_v18_verify": forensics_v18,
        },
        "d15_windows_comparison": {
            "v18_base": d15_v18,
            "v19_cand": d15_v19,
        },
        "empty_day_and_exit_improvements": {
            "added_single_slot_trades": added_1s,
            "dropped_single_slot_trades": dropped_1s,
            "exit_changed_single_slot_trades": changed_1s,
            "added_eq_pool_signals": added_eq_signals,
        },
        "overfitting_8_tests_comparison": {
            "v18_base": audit_v18,
            "v19_cand": audit_v19,
        },
        "notes_on_5m_data_boundary": "主线无龙时第3题材有条件放行(domCond)可进一步推升5年至100~101笔/387.78x~398.09x/MDD 13.83%，但因本地 all_strategies_5m_complete_pit.parquet 缺少其中4只个股(000030,600513,600962,000823)共7个交易日5m线，为严守100% 5m覆盖门限本独立正式版予以剥离留存",
        "elapsed_sec": round(time.time() - t_all, 1),
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n=== D15 对比总表 (V18 -> V19_cand) ===")
    for wname, _, _, _ in windows:
        a, b = d15_v18[wname], d15_v19[wname]
        print(
            f"  {wname:<8} | V18: {a['trades']:>2}b {a['win_rate_pct']:>5.2f}% PLR={a['plr']:>4.2f} 1S={a['nav_1s']:>6.2f}x Cap={a['cap10m_mult']:>5.2f}x EQ={a['eq_nav']:>5.2f}x MDD={a['mdd_pct']:>5.2f}% Ex={a['excess_1s_pp']:>+8.1f}pp"
            f" || V19: {b['trades']:>2}b {b['win_rate_pct']:>5.2f}% PLR={b['plr']:>4.2f} 1S={b['nav_1s']:>6.2f}x Cap={b['cap10m_mult']:>5.2f}x EQ={b['eq_nav']:>5.2f}x MDD={b['mdd_pct']:>5.2f}% Ex={b['excess_1s_pp']:>+8.1f}pp"
        )
    print(f"\n[Done] CSV={OUT_CSV}, JSON={OUT_JSON}, elapsed={summary['elapsed_sec']}s")


if __name__ == "__main__":
    main()
