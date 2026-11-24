#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_part1_scope.py
================================================================================
热点高分题材买基本面大票/容量中军 — 5年 PIT 全谱系范围与持有期回测 (Part 1)

硬性红线保障:
1. 100% 本地只读，严禁 import yfinance / baostock / 任何联网 API (D12)。
2. 严禁修改任何生产脚本、strategy_astock.md 或 portfolio_state.json。
3. 全量 A 股主板+创业板+科创板 (00/60/30/688)，剔除 .BJ 与 PIT ST 股票。
4. 严格复权计算收益 (adj_close = close / qfq_factor; pre_c = close.shift(1)*adjf.shift(1)/adjf)。
5. 严格按 fast_1to2_today.py 滚动 PIT 算法 (2018年起预热至T日) 计算 sc_clean, rk_c, sz, r5_zts。
6. 严格 PIT [T-365天, T] 股票题材归属 + CSRC PIT 行业标注 + T+1 开盘买入(剔除停牌/无成交/一字涨停)
   + 双边 0.20% 成本 + 卖出日一字跌停/停牌顺延。
7. 严格按 D15 四必核产出：日等权 MTM 净值与日均收益、单仓轮动复利净值、胜率、盈亏比、回撤、
   IS / OOS / 3Y / 2026 及剔除 924 救市日 (2024-09-24~2024-10-08) 对照与沪深300净超额。
================================================================================
"""

import os
import re
import json
import time
import bisect
import datetime
from collections import defaultdict, Counter

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT_DIR = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT_DIR}/sim-portfolio"
OUT_DIR = f"{SIM_DIR}/backtests_astock/hot_theme_largecap_audit_20261123/part1_scope"

A_DAILY_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_MERGED_PATH = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"
KPL_5Y_PATH = f"{SIM_DIR}/data/kpl_plates_5y_2021_2026_complete.jsonl"
KPL_V2_PATH = f"{ROOT_DIR}/news-dashboard/output/kpl_plates_v2.jsonl"
CSRC_PIT_PATH = f"{SIM_DIR}/data/csrc_industry_pit_clean.csv"
ST_UNIV_PATH = f"{SIM_DIR}/data/st_universe.json"
INDEX_CACHE_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
CSI_CANONICAL_PATH = f"{SIM_DIR}/backtests_astock/clean_rebacktest_20261116/csi300_canonical_20261116.json"
PREMARKET_CACHE_PATH = f"{SIM_DIR}/data/1to2_premarket_cache.json"

START_SIG_DT = "2021-11-15"
END_DT = "2026-11-23"
FEE_RATE = 0.0020
HALF_FEE = 0.0010

# ===== fast_1to2_today.py / clean_wf_1to2_v14 exact patterns =====
NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股"
}
MA_PAT = re.compile(r"(重组|收购|股权转让|实控人变更|控制权变更|资产注入|借壳|控股|整合|中标|重大合同)")
TECH_PAT_TIMELESS = re.compile(
    r"(芯片|半导体|光刻|集成电路|软件|信创|云计算|大数据|人工智能|AI|机器人|智能制造|自动化|"
    r"通信|5G|光通信|卫星|航天|军工|锂电|光伏|储能|风电|氢能|新材料|消费电子|智能驾驶|无人驾驶)"
)
EARN_PAT = re.compile(r"(业绩|预增|扭亏|季报|年报|半年报|分红)")


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


# ===== 题材分类字典 =====
PAT_TECH = re.compile(
    r"(机器人|芯片|半导体|人工智能|AI|算力|光通信|光模块|CPO|PCB|印制电路板|卫星|航天|低空|"
    r"锂电|固态电池|钠电池|PET铜箔|光伏|储能|风电|氢能|军工|智能驾驶|无人驾驶|车路云|车联网|"
    r"消费电子|华为|鸿蒙|海思|数字经济|信创|国产软件|云计算|量子|脑机|端侧|AIGC|VR/AR/MR|"
    r"虚拟现实|元宇宙|元器件|面板|5G|通信|智能电网|特高压|充电桩|电源|液冷|新能源汽车|"
    r"汽车零部件|汽车类|智能汽车|比亚迪|高端制造|工业母机|新型工业化|新材料|核电|科创板|"
    r"摩尔线程|物理AI|金融科技|机器视觉|传感器|数据要素|web3\.0|东数西算|铜箔|存储|光刻|"
    r"电机|减速器|高压快充|超充|网约车|自动驾驶|数字货币|移动支付)"
)
PAT_TECH_CORE = re.compile(
    r"(机器人|芯片|半导体|人工智能|AI|算力|光通信|光模块|CPO|PCB|印制电路板|卫星|航天|低空|"
    r"锂电|固态电池|钠电池|光伏|储能|风电|氢能|军工|智能驾驶|无人驾驶|消费电子|华为|鸿蒙|海思|"
    r"信创|国产软件|云计算|量子|脑机|端侧|AIGC|5G|通信|液冷|物理AI|光刻|存储|摩尔线程)"
)
PAT_APPLIANCE = re.compile(r"(家电|热泵|厨电|白电)")
PAT_CONS_DEF = re.compile(
    r"(家电|热泵|食品|饮料|零售|医药|医疗|病毒防治|疫苗|农业|猪肉|水产|农药|供销社|"
    r"酿酒|白酒|旅游|服装|家纺|医美|家居|装修家具|教育|养老|多胎|生育|文创|体育|冰雪|"
    r"美容|消费|文化传媒|传媒|游戏|网红经济|平台经济|电子商务|跨境电商|外卖|首发经济|"
    r"幽门螺杆菌|NMN|烟草|中药|互联网彩票|预制菜|小红书|抖音|电子烟)"
)
PAT_CONS_CORE = re.compile(
    r"(家电|热泵|食品|饮料|零售|医药|医疗|病毒防治|疫苗|农业|猪肉|水产|农药|供销社|"
    r"酿酒|白酒|旅游|服装|家纺|医美|家居|装修家具|教育|养老|多胎|生育|美容|消费|中药|预制菜)"
)
PAT_CYC_FIN = re.compile(
    r"(有色|稀土|黄金|化工|煤炭|地产|房地产|券商|证券|银行|金融|保险|石油|石化|"
    r"天然气|油气|燃气|钢铁|水泥|基础建设|基建|建筑|电力|绿色电力|水电站|航运|港口|"
    r"集装箱|物流|环保|造纸|非金属材料|燃气轮机|轨道交通|热力|破净|压缩机|石英|金刚石|"
    r"钛白粉|磷化工|化纤|制冷剂|民爆|地下管网|水利|农机|化肥)"
)


def classify_plate_flags(pn: str) -> dict:
    s = pn.strip()
    m = re.match(r"^(.+?)\((.+?)\)$", s)
    inner = m.group(2) if m else ""
    is_app = bool(PAT_APPLIANCE.search(s))
    if inner and PAT_APPLIANCE.search(inner):
        cat = "CONS_DEF"
    elif PAT_TECH.search(s):
        cat = "TECH"
    elif PAT_CONS_DEF.search(s):
        cat = "CONS_DEF"
    elif PAT_CYC_FIN.search(s):
        cat = "CYC_FIN"
    else:
        cat = "EVENT_OTHER"
    return {
        "cat": cat,
        "is_app": is_app,
        "is_tech_core": bool(PAT_TECH_CORE.search(s)) and not (inner and PAT_APPLIANCE.search(inner)),
        "is_cons_core": bool(PAT_CONS_CORE.search(s)),
    }


def extract_plate_aliases(raw_pn: str) -> set:
    """提取历史KPL板块名的匹配键，用于[T-365d, T]无前视成分股归属。"""
    s = raw_pn.strip()
    if not s or s in NON_THEME:
        return set()
    out = {s}
    parts = [p.strip() for p in re.split(r"[,，]", s) if p.strip()]
    for part in parts:
        if part not in NON_THEME:
            out.add(part)
        m = re.match(r"^(.+?)\((.+?)\)$", part)
        if m:
            outer, inner = m.group(1).strip(), m.group(2).strip()
            if inner and inner not in NON_THEME:
                out.add(inner)
            # 防止地产链(家电)把纯家电股误归入地产链，仅当inner非家电/家居时保留outer
            if outer and outer not in NON_THEME and not (outer == "地产链" and inner in ("家电", "装修家具")):
                out.add(outer)
    return out


def query_aliases_for_today_plate(raw_pn: str) -> list:
    s = raw_pn.strip()
    m = re.match(r"^(.+?)\((.+?)\)$", s)
    if m:
        outer, inner = m.group(1).strip(), m.group(2).strip()
        keys = [s]
        if inner and inner not in NON_THEME:
            keys.append(inner)
        if outer and outer not in NON_THEME and outer == inner.replace("概念", ""):
            keys.append(outer)
        elif outer in ("PCB概念", "端侧AI", "智能驾驶", "锂电池", "算力", "通信", "汽车类"):
            keys.append(outer)
        return list(dict.fromkeys(keys))
    if "," in s or "，" in s:
        return [s] + [p.strip() for p in re.split(r"[,，]", s) if p.strip() and p.strip() not in NON_THEME]
    return [s]


# ===== CSRC PIT 行业与 ST 判定 =====
CSRC_TECH_CODES = {"C34", "C35", "C36", "C37", "C38", "C39", "C40", "I63", "I64", "I65", "M73", "M74", "M75"}
CSRC_CONS_CODES = {
    "A01", "A02", "A03", "A04", "A05",
    "C13", "C14", "C15", "C17", "C18", "C19", "C20", "C21", "C22", "C23", "C24", "C27",
    "F51", "F52", "H61", "H62", "P82", "P83", "Q84", "R86", "R87", "R88", "R89"
}
CSRC_CYC_CODES = {
    "B06", "B07", "B08", "B09", "B10", "B11",
    "C25", "C26", "C28", "C29", "C30", "C31", "C32", "C33",
    "D44", "D45", "D46", "E47", "E48", "E49", "E50",
    "G53", "G54", "G55", "G56", "G58", "G59", "G60",
    "J66", "J67", "J68", "J69", "K70", "L71", "L72", "N76", "N77", "N78"
}


def load_csrc_pit():
    df_c = pd.read_csv(CSRC_PIT_PATH, dtype=str).fillna("")
    col_code = "sec_code" if "sec_code" in df_c.columns else "code"
    df_c["c6"] = df_c[col_code].astype(str).str[-6:].str.zfill(6)
    csrc_iv = defaultdict(list)
    for r in df_c[["c6", "start_date", "end_date", "industry", "code_name"]].itertuples(index=False):
        csrc_iv[r.c6].append((str(r.start_date)[:10], str(r.end_date)[:10], str(r.industry), str(r.code_name)))
    for c6 in csrc_iv:
        csrc_iv[c6].sort(key=lambda x: (x[0], x[1]))
    with open(ST_UNIV_PATH, encoding="utf-8") as f:
        st_snap = set(json.load(f).get("codes", []))
    return csrc_iv, st_snap


def get_csrc_pit_info(csrc_iv, st_snap, kpl_st_set_on_dt: set, c6: str, dt: str):
    """返回 (industry_str, csrc_code3, csrc_group, is_st_pit)"""
    ivs = csrc_iv.get(c6)
    ind = ""
    cname = ""
    if ivs:
        chosen = ivs[-1]
        for sd, ed, iv_ind, iv_nm in ivs:
            if sd <= dt <= ed:
                chosen = (sd, ed, iv_ind, iv_nm)
                break
            if dt < sd:
                chosen = (sd, ed, iv_ind, iv_nm)
                break
        ind = chosen[2]
        cname = chosen[3]
    code3 = ind[:3] if len(ind) >= 3 else "UNK"
    if code3 in CSRC_TECH_CODES:
        grp = "CSRC_TECH"
    elif code3 in CSRC_CONS_CODES:
        grp = "CSRC_CONS_MED"
    elif code3 in CSRC_CYC_CODES:
        grp = "CSRC_CYC_FIN"
    else:
        grp = "CSRC_OTHER"

    is_st = False
    if "ST" in cname.upper() or "退" in cname:
        is_st = True
    if c6 in kpl_st_set_on_dt:
        is_st = True
    if dt >= "2026-11-16" and c6 in st_snap:
        is_st = True
    return ind, code3, grp, is_st


def load_prices_and_panels():
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare"]
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2017-08-01"))).to_table().to_pandas()
    parts = [df_act]
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format="parquet")
        df_del = ds_del.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2017-08-01"))).to_table().to_pandas()
        parts.append(df_del)

    df = pd.concat(parts, ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60", "30", "688")) & (~df["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # 复权系数 adjf = adj_close / close = 1 / qfq_factor
    df["adjf"] = np.where((df["close"] > 0) & df["adj_close"].notna() & (df["adj_close"] > 0), df["adj_close"] / df["close"], 1.0)
    df["adj_open"] = df["open"] * df["adjf"]
    df["adj_high"] = df["high"] * df["adjf"]
    df["adj_low"] = df["low"] * df["adjf"]

    g = df.groupby("c6", sort=False)
    df["oshare"] = g["oshare"].ffill()
    df["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["h_pct"] = df["high"] / df["pre_c"] - 1.0
    df["mcap"] = df["close"] * df["oshare"] / 1e8
    df["bar_num"] = g.cumcount()

    # 均线按个股实际交易日计算 (严格截至T日收盘，无前视)
    df["ma5"] = g["adj_close"].rolling(5, min_periods=5).mean().reset_index(level=0, drop=True)
    df["ma10"] = g["adj_close"].rolling(10, min_periods=10).mean().reset_index(level=0, drop=True)

    # 板块涨跌停规则 (00/60/302=10%, 300/301/688=20%; 上市前5日无涨跌幅限制)
    c6_arr = df["c6"].to_numpy()
    is_20_board = np.array([c.startswith(("300", "301", "688")) for c in c6_arr], dtype=bool)
    lim_pct = np.where(is_20_board, 0.20, 0.10)
    pre_c = df["pre_c"].to_numpy()
    zt_px = np.floor(pre_c * (1.0 + lim_pct) * 100.0 + 0.5) / 100.0
    dt_px = np.floor(pre_c * (1.0 - lim_pct) * 100.0 + 0.5) / 100.0

    is_first5 = (df["bar_num"].to_numpy() < 5)
    valid_pre = np.isfinite(pre_c) & (pre_c > 0) & (~is_first5)
    op = df["open"].to_numpy()
    hi = df["high"].to_numpy()
    lo = df["low"].to_numpy()
    cl = df["close"].to_numpy()
    pct = df["pct"].to_numpy()
    hpct = df["h_pct"].to_numpy()
    vol = df["volume"].to_numpy()
    amt = df["amount"].to_numpy()

    df["zt_px"] = zt_px
    df["dt_px"] = dt_px
    df["is_zt"] = valid_pre & (cl >= zt_px - 0.005) & (pct >= lim_pct - 0.005)
    df["touch_zt"] = valid_pre & ((hi >= zt_px - 0.005) | (hpct >= lim_pct - 0.002))
    df["is_yizi"] = valid_pre & (op >= zt_px - 0.005) & (lo >= op - 1e-6)
    df["is_yizi_dt"] = valid_pre & (cl <= dt_px + 0.005) & (hi <= lo + 1e-6)
    df["is_tradable"] = (vol > 0) & (amt > 0) & (op > 0) & (cl > 0) & np.isfinite(df["adj_close"].to_numpy())

    print(f"[Data] Loaded {len(df):,} rows ({df['c6'].nunique()} stocks, {df['dt_str'].min()}~{df['dt_str'].max()}) in {time.time()-t0:.2f}s", flush=True)
    return df


def load_kpl_days():
    kpl_days_map = {}
    for p, min_dt, keep_bigger in [
        (KPL_MERGED_PATH, "", False),
        (KPL_5Y_PATH, "2021-01-01", False),
        (KPL_V2_PATH, "", True),
    ]:
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                d = json.loads(ln)
                dt = d.get("date", "")
                if not dt or (min_dt and dt < min_dt):
                    continue
                if keep_bigger and dt in kpl_days_map and len(d.get("plates", [])) < len(kpl_days_map[dt].get("plates", [])):
                    continue
                kpl_days_map[dt] = d
    return [kpl_days_map[k] for k in sorted(kpl_days_map.keys())]


def run_kpl_pit_and_build_candidates(df: pd.DataFrame, kpl_days: list, csrc_iv, st_snap):
    """
    1. 严格按 fast_1to2_today.py (00/60 Elo 口径) 从 2018 滚动计算每日 sc_clean, rk_c, sz, r5_zts。
    2. 校验 2026-11-23 与 1to2_premarket_cache.json 一致性。
    3. 对 2021-11-15 ~ 2026-11-20 构建严格 PIT [T-365d, T] 大票(mcap>=100亿)候选池。
    """
    t0 = time.time()
    kpl_dt_set = {d["date"] for d in kpl_days}

    # 00/60 Elo 校准切片（对齐 fast_1to2_today.py）
    sub_elo = df[df["dt_str"].isin(kpl_dt_set) & df["c6"].str.startswith(("00", "60"))][
        ["dt_str", "c6", "is_zt", "touch_zt", "is_yizi", "pct", "mcap"]
    ]
    day_stock_map = {
        (r.dt_str, r.c6): (r.is_zt, r.touch_zt, r.is_yizi, r.pct, r.mcap)
        for r in sub_elo.itertuples(index=False)
    }

    # 全市场 >=2021-11-15 当日大票行索引，便于O(1)提取每日候选
    df_bt = df[(df["dt_str"] >= START_SIG_DT) & (df["dt_str"] <= END_DT)].copy()
    day_big_rows = defaultdict(dict)
    for r in df_bt[df_bt["mcap"] >= 100.0][
        ["dt_str", "c6", "pct", "amount", "mcap", "is_zt", "is_tradable"]
    ].itertuples(index=False):
        day_big_rows[r.dt_str][r.c6] = (float(r.pct), float(r.amount), float(r.mcap), bool(r.is_zt), bool(r.is_tradable))

    elo = defaultdict(lambda: 100.0)
    plate_recent_zts = defaultdict(list)
    plate_last_idx = {}
    prev_plate_stocks = {}
    term_seen_days = Counter()
    term_first_dt, term_last_idx = {}, {}

    # 滚动 365 天 KPL 股票-板块归属窗口: alias -> {c6: list of (dt_str, dt_ord)}
    # 用滑动队列维护 [T-365d, T]
    from collections import deque
    hist_queue = deque()  # elements: (dt_ord, dt_str, alias_name, c6)
    alias_stock_dates = defaultdict(lambda: defaultdict(list))  # alias -> c6 -> [dt_str, ...]

    # PIT ST 滚动标记: 在 ST板块 出现且之后未出现在 ST摘帽 的股票
    kpl_st_active = set()

    records = []
    parity_20261123 = []

    for day_idx, d_entry in enumerate(kpl_days):
        dt = d_entry["date"]
        dt_date = datetime.date.fromisoformat(dt)
        dt_ord = dt_date.toordinal()
        cutoff_15d = (dt_date - datetime.timedelta(days=15)).isoformat()
        cutoff_365_ord = dt_ord - 365

        # 清理超过365天的历史记录 (严格 [T-365, T])
        while hist_queue and hist_queue[0][0] < cutoff_365_ord:
            _, _, old_al, old_c6 = hist_queue.popleft()
            lst = alias_stock_dates[old_al][old_c6]
            if lst:
                lst.pop(0)
                if not lst:
                    del alias_stock_dates[old_al][old_c6]

        # 1. Elo 更新
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

        for p_k in list(elo.keys()):
            if day_idx - plate_last_idx.get(p_k, day_idx) > 3:
                elo[p_k] = 100.0 + (elo[p_k] - 100.0) * 0.85

        new_prev_p = {}
        plate_meta = {}
        day_terms_to_commit = {}
        st_today_kpl = set()
        today_plate_c6_set = defaultdict(set)

        plates = d_entry.get("plates", [])
        for p in plates:
            pname = p.get("plate", "")
            stocks = p.get("stocks", [])
            if pname == "ST板块":
                for s in stocks:
                    c6 = str(s[0]).strip()[:6].zfill(6)
                    st_today_kpl.add(c6)
                    kpl_st_active.add(c6)
                continue
            if pname == "ST摘帽":
                for s in stocks:
                    c6 = str(s[0]).strip()[:6].zfill(6)
                    kpl_st_active.discard(c6)

            if pname in NON_THEME:
                continue
            sz = len(stocks)
            if sz == 0:
                continue

            c6_list = []
            n_ma = n_tech_t = n_earn = n_big = n_yizi = n_new = 0
            spark_b = 0.0
            aliases = extract_plate_aliases(pname)

            for s in stocks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                sname = str(s[1]).strip() if len(s) > 1 else ""
                if "ST" in sname.upper() or "退" in sname:
                    st_today_kpl.add(c6)
                c6_list.append(c6)
                today_plate_c6_set[pname].add(c6)
                for al in aliases:
                    hist_queue.append((dt_ord, dt, al, c6))
                    alias_stock_dates[al][c6].append(dt)

                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                r_lg = str(s[3]).strip() if len(s) > 3 else ""
                txt = f"{pname} {r_sh} {r_lg}"
                if MA_PAT.search(txt): n_ma += 1
                if TECH_PAT_TIMELESS.search(txt): n_tech_t += 1
                if EARN_PAT.search(txt): n_earn += 1

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
            r5_zts = sum(cnt for idx_p, cnt in plate_recent_zts[pname] if day_idx - idx_p <= 5)
            plate_recent_zts[pname].append((day_idx, sz))
            sc_base = (
                elo[pname] + min(sz, 15) * 1.8 + min(r5_zts, 30) * 0.35
                + (8.0 if n_ma > 0 else 0.0) + (5.0 if n_new > 0 else 0.0)
                + spark_b + min(n_yizi * 4.0, 8.0) - (n_earn / sz) * 12.0 - (n_big / sz) * 10.0
            )
            sc_clean = sc_base + (6.0 if (TECH_PAT_TIMELESS.search(pname) or n_tech_t >= max(1, sz // 2)) else 0.0)
            plate_meta[pname] = (sc_clean, elo[pname], sz, r5_zts)

        ranked_c = sorted(plate_meta.keys(), key=lambda k: plate_meta[k][0], reverse=True)
        rk_map_c = {k: i + 1 for i, k in enumerate(ranked_c)}

        if dt == "2026-11-23":
            parity_20261123 = [
                {"rk": i + 1, "plate": pn, "sc_clean": round(float(plate_meta[pn][0]), 2),
                 "elo": round(float(plate_meta[pn][1]), 2), "sz": int(plate_meta[pn][2])}
                for i, pn in enumerate(ranked_c[:10])
            ]

        # 2. 在样本期内提取当日热门题材的 PIT 大票候选
        if START_SIG_DT <= dt < END_DT and dt in day_big_rows:
            big_map = day_big_rows[dt]
            st_union_today = st_today_kpl | kpl_st_active

            # 对每个当日活跃题材收集 [T-365d, T] 大票成员
            # 先筛选与研究相关的热门题材 (rk_c <= 5 or sc_clean >= 100 or sz >= 3) 以免无意义杂毛膨胀内存
            # 注意: sz_3_9 要求 sz>=3, rk_c<=2 或 sc_clean>=120 都自动落入 (sz>=1 且 rk_c<=10 或 sc>=110)
            for pname in ranked_c:
                sc_c, p_elo, sz, r5 = plate_meta[pname]
                rk_c = rk_map_c[pname]
                if not (rk_c <= 5 or sc_c >= 110.0 or sz >= 3):
                    continue

                q_keys = query_aliases_for_today_plate(pname)
                # 合并所有匹配别名的股票历史出现记录
                pool_c6_stats = {}  # c6 -> (in_today, last_dt, total_hits)
                td_set = today_plate_c6_set.get(pname, set())
                for c6 in td_set:
                    if c6 in big_map:
                        pool_c6_stats[c6] = [1, dt, 1]

                for qk in q_keys:
                    c6_dict = alias_stock_dates.get(qk)
                    if not c6_dict:
                        continue
                    for c6, dlist in c6_dict.items():
                        if c6 not in big_map:
                            continue
                        last_d = dlist[-1]
                        cnt_d = len(dlist)
                        if c6 not in pool_c6_stats:
                            pool_c6_stats[c6] = [1 if c6 in td_set else 0, last_d, cnt_d]
                        else:
                            if last_d > pool_c6_stats[c6][1]:
                                pool_c6_stats[c6][1] = last_d
                            pool_c6_stats[c6][2] = max(pool_c6_stats[c6][2], cnt_d)

                if not pool_c6_stats:
                    continue

                # 过滤 PIT ST 与当日不可交易停牌股(amount<=0)，并按当日成交额排序计算板块第1/2-3名中军
                cands_in_plate = []
                for c6, (in_td, last_d, hit_c) in pool_c6_stats.items():
                    pct_v, amt_v, mcap_v, is_zt_v, is_trad_v = big_map[c6]
                    if not is_trad_v or amt_v <= 0:
                        continue
                    ind_s, code3, csrc_grp, is_st = get_csrc_pit_info(csrc_iv, st_snap, st_union_today, c6, dt)
                    if is_st:
                        continue
                    cands_in_plate.append((c6, pct_v, amt_v, mcap_v, is_zt_v, in_td, last_d, hit_c, code3, csrc_grp))

                if not cands_in_plate:
                    continue

                # 按当日成交额降序计算板块内中军排名 (100亿+口径 & 200亿+口径)
                cands_in_plate.sort(key=lambda x: x[2], reverse=True)
                rk200 = 0
                pflags = classify_plate_flags(pname)
                for rk100_0, item in enumerate(cands_in_plate):
                    c6, pct_v, amt_v, mcap_v, is_zt_v, in_td, last_d, hit_c, code3, csrc_grp = item
                    rk100 = rk100_0 + 1
                    if mcap_v >= 200.0:
                        rk200 += 1
                        rk200_val = rk200
                    else:
                        rk200_val = 999
                    records.append({
                        "dt": dt,
                        "c6": c6,
                        "plate": pname,
                        "rk_c": rk_c,
                        "sc_clean": float(sc_c),
                        "sz": sz,
                        "r5_zts": r5,
                        "theme_cat": pflags["cat"],
                        "is_app": pflags["is_app"],
                        "is_tech_core": pflags["is_tech_core"],
                        "is_cons_core": pflags["is_cons_core"],
                        "mcap": mcap_v,
                        "amt_yi": amt_v / 1e8,
                        "pct": pct_v,
                        "is_zt": is_zt_v,
                        "in_today_kpl": in_td,
                        "last_seen_dt": last_d,
                        "hit_365d": hit_c,
                        "amt_rk_100": rk100,
                        "amt_rk_200": rk200_val,
                        "csrc_code3": code3,
                        "csrc_grp": csrc_grp,
                    })

        for t, dt_v in day_terms_to_commit.items():
            term_seen_days[t] += 1
            if t not in term_first_dt:
                term_first_dt[t] = dt_v
            term_last_idx[t] = day_idx
        prev_plate_stocks = new_prev_p

    cand_df = pd.DataFrame(records)
    print(f"[KPL+Pool] Built {len(cand_df):,} (T, plate, bigcap) candidate rows across {cand_df['dt'].nunique()} days in {time.time()-t0:.2f}s", flush=True)
    return cand_df, parity_20261123


def build_market_matrices_and_precompute_exits(df: pd.DataFrame, cand_df: pd.DataFrame):
    """
    构建密集二维市场矩阵 (n_stocks x n_cal_days)，并在 T+1 严格过滤不可买样本后，
    预先算出每个唯一可买 (T, c6) 在 8 种出场模式下的 (exit_cal_idx, net_ret, exit_is_close)。
    """
    t0 = time.time()
    # 日历从 2021-11-01 到 2026-11-23
    df_win = df[df["dt_str"] >= "2021-11-01"].copy()
    cal_dts = sorted(df_win["dt_str"].unique())
    cal_to_idx = {d: i for i, d in enumerate(cal_dts)}
    n_cal = len(cal_dts)
    max_cal_idx = n_cal - 1

    cand_c6s = sorted(cand_df["c6"].unique())
    c6_to_sid = {c: i for i, c in enumerate(cand_c6s)}
    n_stk = len(cand_c6s)

    df_sub = df_win[df_win["c6"].isin(c6_to_sid)].copy()
    df_sub["sid"] = df_sub["c6"].map(c6_to_sid).astype(np.int32)
    df_sub["cid"] = df_sub["dt_str"].map(cal_to_idx).astype(np.int32)

    adj_open = np.full((n_stk, n_cal), np.nan, dtype=np.float64)
    adj_close = np.full((n_stk, n_cal), np.nan, dtype=np.float64)
    ma5_arr = np.full((n_stk, n_cal), np.nan, dtype=np.float64)
    ma10_arr = np.full((n_stk, n_cal), np.nan, dtype=np.float64)
    has_bar = np.zeros((n_stk, n_cal), dtype=bool)
    tradable = np.zeros((n_stk, n_cal), dtype=bool)
    yizi_buy = np.zeros((n_stk, n_cal), dtype=bool)
    yizi_sell = np.zeros((n_stk, n_cal), dtype=bool)

    sids = df_sub["sid"].to_numpy()
    cids = df_sub["cid"].to_numpy()
    adj_open[sids, cids] = df_sub["adj_open"].to_numpy()
    adj_close[sids, cids] = df_sub["adj_close"].to_numpy()
    ma5_arr[sids, cids] = df_sub["ma5"].to_numpy()
    ma10_arr[sids, cids] = df_sub["ma10"].to_numpy()
    has_bar[sids, cids] = True
    tradable[sids, cids] = df_sub["is_tradable"].to_numpy()
    yizi_buy[sids, cids] = df_sub["is_yizi"].to_numpy()
    yizi_sell[sids, cids] = df_sub["is_yizi_dt"].to_numpy()

    # 为每日 MTM 构造前向填充的 adj_close 以及 (r_on, r_id)
    adj_close_ff = adj_close.copy()
    for d in range(1, n_cal):
        m = np.isnan(adj_close_ff[:, d])
        adj_close_ff[m, d] = adj_close_ff[m, d - 1]

    r_on = np.zeros((n_stk, n_cal), dtype=np.float64)
    r_id = np.zeros((n_stk, n_cal), dtype=np.float64)
    valid_on = tradable[:, 1:] & np.isfinite(adj_open[:, 1:]) & (adj_open[:, 1:] > 0) & np.isfinite(adj_close_ff[:, :-1]) & (adj_close_ff[:, :-1] > 0)
    r_on[:, 1:] = np.where(valid_on, adj_open[:, 1:] / adj_close_ff[:, :-1] - 1.0, 0.0)
    valid_id = tradable & np.isfinite(adj_open) & (adj_open > 0) & np.isfinite(adj_close) & (adj_close > 0)
    r_id = np.where(valid_id, adj_close / adj_open - 1.0, 0.0)

    # 提取唯一 (T, c6) 检查 T+1 可买性并预计算 8 种出场结果
    uniq = cand_df[["dt", "c6"]].drop_duplicates().copy()
    uniq["sid"] = uniq["c6"].map(c6_to_sid).astype(np.int32)
    uniq["sig_cid"] = uniq["dt"].map(cal_to_idx).astype(np.int32)
    uniq["buy_cid"] = uniq["sig_cid"] + 1

    u_sid = uniq["sid"].to_numpy()
    u_bid = uniq["buy_cid"].to_numpy()

    in_range = u_bid <= max_cal_idx
    t1_trad = np.zeros(len(uniq), dtype=bool)
    t1_yizi = np.zeros(len(uniq), dtype=bool)
    t1_trad[in_range] = tradable[u_sid[in_range], u_bid[in_range]]
    t1_yizi[in_range] = yizi_buy[u_sid[in_range], u_bid[in_range]]
    buyable = in_range & t1_trad & (~t1_yizi)

    attrition = {
        "total_unique_sig_pairs": int(len(uniq)),
        "buyable": int(buyable.sum()),
        "dropped_t1_suspended_or_novol": int((in_range & (~t1_trad)).sum()),
        "dropped_t1_yizi_limitup": int((in_range & t1_trad & t1_yizi).sum()),
        "dropped_out_of_range": int((~in_range).sum()),
    }
    print(f"[T+1 Execution Filter] {attrition}", flush=True)

    # 只保留可买样本并映射到 trade_id
    uniq_ok = uniq[buyable].copy().reset_index(drop=True)
    uniq_ok["trade_uid"] = np.arange(len(uniq_ok), dtype=np.int32)

    EXIT_MODES = ["H1", "H3", "H5", "H10", "H20", "MA5", "MA10", "SL7_MA10"]
    HOLD_OFFSETS = {"H1": 1, "H3": 3, "H5": 5, "H10": 10, "H20": 20}
    n_u = len(uniq_ok)
    ex_cid = {m: np.full(n_u, -1, dtype=np.int32) for m in EXIT_MODES}
    ex_ret = {m: np.full(n_u, np.nan, dtype=np.float64) for m in EXIT_MODES}
    ex_is_close = {m: np.ones(n_u, dtype=bool) for m in EXIT_MODES}

    ok_sids = uniq_ok["sid"].to_numpy()
    ok_bids = uniq_ok["buy_cid"].to_numpy()

    for i in range(n_u):
        s = ok_sids[i]
        b = ok_bids[i]
        buy_px = adj_open[s, b]
        # 该股票在 b 之后最后一个有交易的日期 (防退市无限停牌)
        # 1) 固定持有期 H1, H3, H5, H10, H20
        for hm, offset in HOLD_OFFSETS.items():
            target = b + offset
            if target > max_cal_idx:
                continue
            d = target
            while d <= max_cal_idx and not (tradable[s, d] and (not yizi_sell[s, d])):
                d += 1
            if d > max_cal_idx:
                # 若到期末仍停牌/一字跌停，回退找 b 之后最后可估价日按收盘计，若无则跳过
                continue
            sell_px = adj_close[s, d]
            ex_cid[hm][i] = d
            ex_ret[hm][i] = sell_px / buy_px - 1.0 - FEE_RATE
            ex_is_close[hm][i] = True

        # 2) 趋势离场 MA5 / MA10 / SL7_MA10 (最早从 T+1 收盘 k=b 检查，次日 k+1 开盘卖)
        # 追踪三者同时触发状态
        done_ma5 = False
        done_ma10 = False
        done_sl7 = False
        last_valid_d = b
        for k in range(b, max_cal_idx + 1):
            if tradable[s, k]:
                last_valid_d = k
            else:
                continue
            c_px = adj_close[s, k]
            m5 = ma5_arr[s, k]
            m10 = ma10_arr[s, k]
            cum_r = c_px / buy_px - 1.0

            if (not done_ma5) and np.isfinite(m5) and (c_px < m5):
                # 次日开盘卖，若停牌或一字跌停顺延
                sd = k + 1
                while sd <= max_cal_idx and not (tradable[s, sd] and (not yizi_sell[s, sd])):
                    sd += 1
                if sd <= max_cal_idx:
                    ex_cid["MA5"][i] = sd
                    ex_ret["MA5"][i] = adj_open[s, sd] / buy_px - 1.0 - FEE_RATE
                    ex_is_close["MA5"][i] = False
                else:
                    ex_cid["MA5"][i] = last_valid_d
                    ex_ret["MA5"][i] = adj_close[s, last_valid_d] / buy_px - 1.0 - FEE_RATE
                    ex_is_close["MA5"][i] = True
                done_ma5 = True

            if (not done_ma10) and np.isfinite(m10) and (c_px < m10):
                sd = k + 1
                while sd <= max_cal_idx and not (tradable[s, sd] and (not yizi_sell[s, sd])):
                    sd += 1
                if sd <= max_cal_idx:
                    ex_cid["MA10"][i] = sd
                    ex_ret["MA10"][i] = adj_open[s, sd] / buy_px - 1.0 - FEE_RATE
                    ex_is_close["MA10"][i] = False
                else:
                    ex_cid["MA10"][i] = last_valid_d
                    ex_ret["MA10"][i] = adj_close[s, last_valid_d] / buy_px - 1.0 - FEE_RATE
                    ex_is_close["MA10"][i] = True
                done_ma10 = True

            if (not done_sl7) and ((cum_r <= -0.07) or (np.isfinite(m10) and (c_px < m10))):
                sd = k + 1
                while sd <= max_cal_idx and not (tradable[s, sd] and (not yizi_sell[s, sd])):
                    sd += 1
                if sd <= max_cal_idx:
                    ex_cid["SL7_MA10"][i] = sd
                    ex_ret["SL7_MA10"][i] = adj_open[s, sd] / buy_px - 1.0 - FEE_RATE
                    ex_is_close["SL7_MA10"][i] = False
                else:
                    ex_cid["SL7_MA10"][i] = last_valid_d
                    ex_ret["SL7_MA10"][i] = adj_close[s, last_valid_d] / buy_px - 1.0 - FEE_RATE
                    ex_is_close["SL7_MA10"][i] = True
                done_sl7 = True

            if done_ma5 and done_ma10 and done_sl7:
                break

        # 期末仍未触发离场者，按最后交易日收盘 MTM 计价
        if not done_ma5:
            ex_cid["MA5"][i] = last_valid_d
            ex_ret["MA5"][i] = adj_close[s, last_valid_d] / buy_px - 1.0 - FEE_RATE
            ex_is_close["MA5"][i] = True
        if not done_ma10:
            ex_cid["MA10"][i] = last_valid_d
            ex_ret["MA10"][i] = adj_close[s, last_valid_d] / buy_px - 1.0 - FEE_RATE
            ex_is_close["MA10"][i] = True
        if not done_sl7:
            ex_cid["SL7_MA10"][i] = last_valid_d
            ex_ret["SL7_MA10"][i] = adj_close[s, last_valid_d] / buy_px - 1.0 - FEE_RATE
            ex_is_close["SL7_MA10"][i] = True

    # 把 trade_uid 贴回 cand_df，过滤掉 T+1 不可买行
    cand_df = cand_df.merge(uniq_ok[["dt", "c6", "trade_uid", "sid", "sig_cid", "buy_cid"]], on=["dt", "c6"], how="inner")
    print(f"[Precompute Exits] {n_u:,} buyable (T, c6) x 8 exits computed in {time.time()-t0:.2f}s. Cand rows={len(cand_df):,}", flush=True)

    mkt = {
        "cal_dts": cal_dts,
        "cal_to_idx": cal_to_idx,
        "n_cal": n_cal,
        "r_on": r_on,
        "r_id": r_id,
        "u_sid": ok_sids,
        "u_bid": ok_bids,
        "u_sig_cid": uniq_ok["sig_cid"].to_numpy(),
        "ex_cid": ex_cid,
        "ex_ret": ex_ret,
        "ex_is_close": ex_is_close,
    }
    return cand_df, mkt, attrition


def build_benchmark_windows(cal_dts: list):
    with open(INDEX_CACHE_PATH, encoding="utf-8") as f:
        idx_data = json.load(f)
    sh300 = idx_data["sh000300"]
    sza = idx_data["sz399107"]

    # 确保对齐 cal_dts
    def series_on_cal(series_map):
        arr = np.zeros(len(cal_dts), dtype=np.float64)
        last_v = None
        # 找 2021-11-01 前最近一个交易日
        prevs = [k for k in sorted(series_map.keys()) if k < cal_dts[0]]
        if prevs:
            last_v = series_map[prevs[-1]]
        for i, d in enumerate(cal_dts):
            if d in series_map:
                last_v = series_map[d]
            arr[i] = last_v if last_v is not None else np.nan
        return arr

    csi_px = series_on_cal(sh300)
    sza_px = series_on_cal(sza)
    csi_daily_ret = np.zeros(len(cal_dts), dtype=np.float64)
    sza_daily_ret = np.zeros(len(cal_dts), dtype=np.float64)
    csi_daily_ret[1:] = csi_px[1:] / csi_px[:-1] - 1.0
    sza_daily_ret[1:] = sza_px[1:] / sza_px[:-1] - 1.0

    # 窗口定义 (以 buy_date 对齐: 全五年始于 2021-11-16, 即信号 2021-11-15 次日开盘买入)
    cal_arr = np.array(cal_dts)
    WINDOWS = [
        ("5y", "2021-11-16", "2026-11-23", False),
        ("is", "2021-11-16", "2023-12-31", False),
        ("oos", "2024-01-01", "2026-11-23", False),
        ("3y", "2023-11-16", "2026-11-23", False),
        ("2026", "2026-01-01", "2026-11-23", False),
        ("5y_ex924", "2021-11-16", "2026-11-23", True),
        ("oos_ex924", "2024-01-01", "2026-11-23", True),
    ]
    win_meta = {}
    is_924 = (cal_arr >= "2024-09-24") & (cal_arr <= "2024-10-08")
    for wname, s_dt, e_dt, ex924 in WINDOWS:
        m_day = (cal_arr >= s_dt) & (cal_arr <= e_dt)
        m_bench = m_day & (~is_924) if ex924 else m_day
        csi_r = float(np.prod(1.0 + csi_daily_ret[m_bench]) - 1.0) * 100.0
        sza_r = float(np.prod(1.0 + sza_daily_ret[m_bench]) - 1.0) * 100.0
        csi_raw_r = float(np.prod(1.0 + csi_daily_ret[m_day]) - 1.0) * 100.0
        s_idx = int(np.argmax(m_day))
        e_idx = int(len(cal_arr) - 1 - np.argmax(m_day[::-1]))
        win_meta[wname] = {
            "start": s_dt, "end": e_dt, "ex924": ex924,
            "s_idx": s_idx, "e_idx": e_idx,
            "m_day": m_day, "m_bench": m_bench,
            "csi_pct": round(csi_r, 2),
            "csi_raw_pct": round(csi_raw_r, 2),
            "sza_pct": round(sza_r, 2),
        }
    return win_meta, is_924


def compute_mtm_daily_returns(uids, exit_mode: str, mkt: dict) -> np.ndarray:
    """向量化计算给定 trade_uid 集合的每日 1x 资金等权 MTM 净收益率序列 (长度 n_cal)。"""
    n_cal = mkt["n_cal"]
    if len(uids) == 0:
        return np.zeros(n_cal, dtype=np.float64), np.zeros(n_cal, dtype=np.int32)

    sids = mkt["u_sid"][uids]
    bids = mkt["u_bid"][uids]
    eids = mkt["ex_cid"][exit_mode][uids]
    is_cl = mkt["ex_is_close"][exit_mode][uids]

    # 1. Overnight segments: d in [b+1, e]
    lens_on = eids - bids  # always >= 1 for H>=1 or trend exits
    valid_on = lens_on > 0
    if np.any(valid_on):
        l_on = lens_on[valid_on]
        tot_on = int(l_on.sum())
        tr_idx_on = np.repeat(np.where(valid_on)[0], l_on)
        # day offsets 1 .. lens_on
        starts = np.cumsum(l_on) - l_on
        offsets = np.arange(tot_on) - np.repeat(starts, l_on) + 1
        d_on = bids[tr_idx_on] + offsets
        s_on = sids[tr_idx_on]
        r_on_vals = mkt["r_on"][s_on, d_on].copy()
        # 若在开盘卖出 (not is_cl)，在 d == eids 扣除卖出半边成本 HALF_FEE
        is_exit_on = (d_on == eids[tr_idx_on]) & (~is_cl[tr_idx_on])
        r_on_vals[is_exit_on] -= HALF_FEE
        sum_on = np.bincount(d_on, weights=r_on_vals, minlength=n_cal)
        cnt_on = np.bincount(d_on, minlength=n_cal)
    else:
        sum_on = np.zeros(n_cal, dtype=np.float64)
        cnt_on = np.zeros(n_cal, dtype=np.int32)

    # 2. Intraday segments: d in [b, e] if is_cl else [b, e-1]
    e_id_end = np.where(is_cl, eids, eids - 1)
    lens_id = e_id_end - bids + 1
    valid_id = lens_id > 0
    if np.any(valid_id):
        l_id = lens_id[valid_id]
        tot_id = int(l_id.sum())
        tr_idx_id = np.repeat(np.where(valid_id)[0], l_id)
        starts_id = np.cumsum(l_id) - l_id
        offsets_id = np.arange(tot_id) - np.repeat(starts_id, l_id)
        d_id = bids[tr_idx_id] + offsets_id
        s_id = sids[tr_idx_id]
        r_id_vals = mkt["r_id"][s_id, d_id].copy()
        # 买入日 b 扣半边买入手续费 HALF_FEE
        is_entry_id = (d_id == bids[tr_idx_id])
        r_id_vals[is_entry_id] -= HALF_FEE
        # 若在收盘卖出 (is_cl)，在 d == eids 扣卖出手续费 HALF_FEE
        is_exit_id = is_cl[tr_idx_id] & (d_id == eids[tr_idx_id])
        r_id_vals[is_exit_id] -= HALF_FEE
        sum_id = np.bincount(d_id, weights=r_id_vals, minlength=n_cal)
        cnt_id = np.bincount(d_id, minlength=n_cal)
    else:
        sum_id = np.zeros(n_cal, dtype=np.float64)
        cnt_id = np.zeros(n_cal, dtype=np.int32)

    r_on_day = np.divide(sum_on, cnt_on, out=np.zeros(n_cal, dtype=np.float64), where=(cnt_on > 0))
    r_id_day = np.divide(sum_id, cnt_id, out=np.zeros(n_cal, dtype=np.float64), where=(cnt_id > 0))
    daily_ret = (1.0 + r_on_day) * (1.0 + r_id_day) - 1.0
    active_cnt = np.maximum(cnt_on, cnt_id)
    return daily_ret, active_cnt


def eval_single_slot(uids_sorted, bids_sorted, eids_sorted, rets_sorted, s_idx, e_idx, is_924_cid=None, ex924=False):
    """单仓轮动复利评估 (严格 buy_idx > prev_exit_idx 零重叠)。"""
    cur_exit = -1
    sel_rets = []
    for i in range(len(uids_sorted)):
        b = bids_sorted[i]
        if b < s_idx or b > e_idx:
            continue
        e = eids_sorted[i]
        if ex924 and is_924_cid is not None:
            # 严格剔除 [signal_cid, exit_cid] 与 924 救市区间有任意重叠的交易
            if np.any(is_924_cid[max(0, b - 1): min(len(is_924_cid), e + 1)]):
                continue
        if b > cur_exit:
            sel_rets.append(rets_sorted[i])
            cur_exit = e
    n = len(sel_rets)
    if n == 0:
        return 0, 0.0, 0.0, 0.0, 0.0
    arr = np.array(sel_rets, dtype=np.float64)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    wr = float(len(wins) / n * 100.0)
    wlr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (99.9 if len(wins) > 0 else 0.0)
    nav = np.cumprod(1.0 + arr)
    peaks = np.maximum.accumulate(np.insert(nav, 0, 1.0))[1:]
    mdd = float(np.max((peaks - nav) / peaks) * 100.0)
    ret_pct = float((nav[-1] - 1.0) * 100.0)
    return n, round(ret_pct, 2), round(wr, 2), round(wlr, 2), round(mdd, 2)


def eval_entry_set(cand_sub: pd.DataFrame, mkt: dict, win_meta: dict, is_924: np.ndarray, meta_cols: dict):
    """对一个已过滤+去重好的候选集，批量评估 8 种出场模式的全维度 D15 指标。"""
    # 按单仓轮动优先级排序: (buy_cid asc, sc_clean desc, amt_yi desc)
    cand_sorted = cand_sub.sort_values(["buy_cid", "sc_clean", "amt_yi"], ascending=[True, False, False])
    all_uids = cand_sorted["trade_uid"].to_numpy()
    all_bids = mkt["u_bid"][all_uids]
    all_sigs = mkt["u_sig_cid"][all_uids]
    n_sig_days = int(cand_sorted["dt"].nunique())

    rows_out = []
    for em in ["H1", "H3", "H5", "H10", "H20", "MA5", "MA10", "SL7_MA10"]:
        eids_all = mkt["ex_cid"][em][all_uids]
        rets_all = mkt["ex_ret"][em][all_uids]
        valid = (eids_all >= 0) & np.isfinite(rets_all)
        if valid.sum() < 5:
            continue

        uids = all_uids[valid]
        bids = all_bids[valid]
        sigs = all_sigs[valid]
        eids = eids_all[valid]
        rets = rets_all[valid]

        # 全量日等权 MTM
        daily_ret, active_cnt = compute_mtm_daily_returns(uids, em, mkt)

        # 严格剔除924救市区间任意重叠交易的交易子集 (用于 Ex924 MTM & 笔级校验)
        no_924_overlap = np.ones(len(uids), dtype=bool)
        s_924 = int(np.argmax(is_924))
        e_924 = int(len(is_924) - 1 - np.argmax(is_924[::-1]))
        # 重叠条件: sig_cid <= e_924 且 exit_cid >= s_924
        no_924_overlap = ~((sigs <= e_924) & (eids >= s_924))
        daily_ret_ex924, active_cnt_ex924 = compute_mtm_daily_returns(uids[no_924_overlap], em, mkt)

        row = dict(meta_cols)
        row["exit_mode"] = em
        row["n_sig_days"] = n_sig_days

        for wname in ["5y", "is", "oos", "3y", "2026", "5y_ex924", "oos_ex924"]:
            wm = win_meta[wname]
            si, ei = wm["s_idx"], wm["e_idx"]
            ex924 = wm["ex924"]

            if ex924:
                t_mask = (bids >= si) & (bids <= ei) & no_924_overlap
                dr_arr = daily_ret_ex924[wm["m_bench"]]
                ac_arr = active_cnt_ex924[wm["m_bench"]]
            else:
                t_mask = (bids >= si) & (bids <= ei)
                dr_arr = daily_ret[wm["m_day"]]
                ac_arr = active_cnt[wm["m_day"]]

            t_rets = rets[t_mask]
            nt = int(len(t_rets))
            if nt > 0:
                wins = t_rets[t_rets > 0]
                losses = t_rets[t_rets <= 0]
                wr = float(len(wins) / nt * 100.0)
                wlr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (99.9 if len(wins) > 0 else 0.0)
                avg_r = float(t_rets.mean() * 100.0)
                med_r = float(np.median(t_rets) * 100.0)
            else:
                wr = wlr = avg_r = med_r = 0.0

            nav_eq_curve = np.cumprod(1.0 + dr_arr)
            if len(nav_eq_curve) > 0:
                eq_ret = float((nav_eq_curve[-1] - 1.0) * 100.0)
                peaks = np.maximum.accumulate(np.insert(nav_eq_curve, 0, 1.0))[1:]
                eq_mdd = float(np.max((peaks - nav_eq_curve) / peaks) * 100.0)
                eq_daily_bps = float(dr_arr.mean() * 10000.0)
                act_mask = ac_arr > 0
                eq_act_bps = float(dr_arr[act_mask].mean() * 10000.0) if np.any(act_mask) else 0.0
            else:
                eq_ret = eq_mdd = eq_daily_bps = eq_act_bps = 0.0

            sn, s_ret, s_wr, s_wlr, s_mdd = eval_single_slot(
                uids, bids, eids, rets, si, ei, is_924_cid=is_924, ex924=ex924
            )

            csi_b = wm["csi_pct"]
            row[f"n_{wname}"] = nt
            row[f"wr_{wname}"] = round(wr, 2)
            row[f"wlr_{wname}"] = round(wlr, 2)
            row[f"avg_{wname}"] = round(avg_r, 3)
            row[f"med_{wname}"] = round(med_r, 3)
            row[f"eq_ret_{wname}"] = round(eq_ret, 2)
            row[f"eq_bps_{wname}"] = round(eq_daily_bps, 2)
            row[f"eq_act_bps_{wname}"] = round(eq_act_bps, 2)
            row[f"eq_mdd_{wname}"] = round(eq_mdd, 2)
            row[f"eq_ex_csi_{wname}"] = round(eq_ret - csi_b, 2)
            row[f"slot_n_{wname}"] = sn
            row[f"slot_ret_{wname}"] = s_ret
            row[f"slot_wr_{wname}"] = s_wr
            row[f"slot_wlr_{wname}"] = s_wlr
            row[f"slot_mdd_{wname}"] = s_mdd
            row[f"slot_ex_csi_{wname}"] = round(s_ret - csi_b, 2)
            if ex924:
                row[f"eq_ex_rawcsi_{wname}"] = round(eq_ret - wm["csi_raw_pct"], 2)

        rows_out.append(row)
    return rows_out


def build_grid_configs():
    """构建覆盖全部四个必测维度的系统性配置网格 (去重后约 ~2500 个入口配置 x 8 出场)."""
    configs = []
    seen = set()

    def add_cfg(group, heat, cat, csrc, mcap, amt, pct, pos):
        key = (heat, cat, csrc, mcap, amt, pct, pos)
        if key not in seen:
            seen.add(key)
            configs.append({
                "slice_group": group,
                "heat_rule": heat,
                "theme_cat": cat,
                "csrc_align": csrc,
                "mcap_bucket": mcap,
                "min_amt": amt,
                "pct_pattern": pct,
                "plate_pos": pos,
            })

    HEATS_MAIN = ["rk1", "rk1_2", "sc120", "sc135", "sc150"]
    HEATS_SZ = ["sz_3_9", "sz_10_19", "sz_20_35", "sz_gt35"]
    HEATS_ALL = ["ALL_HOT"] + HEATS_MAIN + HEATS_SZ
    MCAPS = ["ge100", "100_200", "200_400", "400_800", "800plus", "ge200", "ge300"]
    MCAPS_CORE = ["ge100", "ge200", "ge300", "400_800", "800plus"]
    PCTS = ["ALL", "A_ZT", "A_GE7_NOZT", "A_5_95", "A_STRONG", "B_2_5", "B_LT2"]
    CATS = ["ALL", "TECH", "CONS_DEF", "CYC_FIN"]
    CATS_EXT = ["ALL", "TECH", "TECH_CORE", "CONS_DEF", "CONS_CORE", "APPLIANCE", "CYC_FIN"]

    # 1. 题材热度 x 市值全谱
    for h in HEATS_ALL:
        for m in MCAPS:
            add_cfg("1_HEAT_X_MCAP", h, "ALL", "ALL", m, 0, "ALL", "ALL")

    # 2. 题材热度 x 题材类别 x 核心市值
    for h in HEATS_ALL:
        for c in CATS_EXT:
            for m in MCAPS_CORE:
                add_cfg("2_HEAT_X_CAT", h, c, "ALL", m, 0, "ALL", "ALL")

    # 3. 题材热度 x 个股启动形态 x 市值
    for h in ["rk1", "rk1_2", "sc120", "sc135", "sc150", "sz_10_19", "sz_20_35", "sz_gt35"]:
        for p in PCTS:
            for m in MCAPS:
                add_cfg("3_HEAT_X_PCT", h, "ALL", "ALL", m, 0, p, "ALL")

    # 4. 核心三维矩阵: 题材类别 x 热度 x 启动形态 x 市值
    for c in ["TECH", "CONS_DEF", "CYC_FIN"]:
        for h in ["rk1", "rk1_2", "sc120", "sc135", "sc150", "sz_gt35"]:
            for p in PCTS:
                for m in ["ge100", "ge200", "ge300", "800plus"]:
                    add_cfg("4_CAT_HEAT_PCT", h, c, "ALL", m, 0, p, "ALL")

    # 5. 板块内中军位置 (第1中军 vs 第2~3名 vs 200亿+内第1中军)
    for pos in ["TOP1", "TOP2_3", "TOP1_200"]:
        for c in CATS:
            for h in ["rk1", "rk1_2", "sc120", "sc135", "sc150", "sz_gt35"]:
                for p in ["ALL", "A_STRONG", "A_ZT", "A_GE7_NOZT", "B_2_5", "B_LT2"]:
                    for m in (["ge200", "ge300"] if pos == "TOP1_200" else ["ge100", "ge200", "ge300"]):
                        add_cfg("5_POS_LEADER", h, c, "ALL", m, 0, p, pos)

    # 6. 成交额门槛 (>=5 / >=10 / >=20亿) x 市值 x 启动形态
    for amt in [5, 10, 20]:
        for c in CATS:
            for h in ["rk1", "rk1_2", "sc135", "sz_gt35"]:
                for m in MCAPS_CORE:
                    for p in ["ALL", "A_STRONG", "A_ZT", "A_GE7_NOZT", "B_LT2"]:
                        add_cfg("6_AMT_LIQUIDITY", h, c, "ALL", m, amt, p, "ALL")

    # 7. CSRC 行业对齐验证 (真科技大票 vs 跨界概念杂牌大票)
    for csrc in ["ALIGNED", "MISMATCH"]:
        for c in ["TECH", "CONS_DEF", "CYC_FIN"]:
            for h in ["rk1_2", "sc120", "sc135", "sc150"]:
                for m in ["ge100", "ge200", "ge300"]:
                    for p in ["ALL", "A_STRONG", "B_LT2"]:
                        add_cfg("7_CSRC_ALIGN", h, c, csrc, m, 0, p, "ALL")

    # 8. 家电专题 & 超级高潮专题 (sz>35)
    for h in ["ALL_HOT", "rk1_2", "sc120", "sz_3_9", "sz_10_19"]:
        for m in ["ge100", "ge200", "ge300"]:
            for p in ["ALL", "A_STRONG", "B_2_5", "B_LT2"]:
                for pos in ["ALL", "TOP1", "TOP2_3"]:
                    add_cfg("8_APPLIANCE_SPECIAL", h, "APPLIANCE", "ALL", m, 0, p, pos)

    return configs


def apply_filters_and_dedup(cand_df: pd.DataFrame, masks: dict, cfg: dict):
    m = masks["heat"][cfg["heat_rule"]] & masks["cat"][cfg["theme_cat"]] & masks["mcap"][cfg["mcap_bucket"]]
    if cfg["min_amt"] > 0:
        m = m & masks["amt"][cfg["min_amt"]]
    if cfg["pct_pattern"] != "ALL":
        m = m & masks["pct"][cfg["pct_pattern"]]
    if cfg["plate_pos"] != "ALL":
        m = m & masks["pos"][cfg["plate_pos"]]
    if cfg["csrc_align"] != "ALL":
        m = m & masks["csrc"][cfg["csrc_align"]]

    sub = cand_df.loc[m, ["dt", "c6", "trade_uid", "buy_cid", "sc_clean", "amt_yi", "hit_365d", "last_seen_dt"]]
    if len(sub) < 5:
        return None
    # 支持一票多题材但同日去重: 同日同一只票若命中多个达标热门题材，保留题材分最高的一条
    sub = sub.sort_values(["dt", "c6", "sc_clean", "hit_365d", "last_seen_dt"], ascending=[True, True, False, False, False])
    sub = sub.drop_duplicates(subset=["dt", "c6"], keep="first")
    if len(sub) < 5:
        return None
    return sub


def main():
    t_start = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 80)
    print(">>> 启动【热点高分题材买大票/中军 5年PIT全谱系范围与持有期回测 (Part 1)】")

    df = load_prices_and_panels()
    kpl_days = load_kpl_days()
    csrc_iv, st_snap = load_csrc_pit()

    cand_df, parity_20261123 = run_kpl_pit_and_build_candidates(df, kpl_days, csrc_iv, st_snap)

    # 校验与 1to2_premarket_cache.json 题材分一致性
    cache_top5 = []
    if os.path.exists(PREMARKET_CACHE_PATH):
        with open(PREMARKET_CACHE_PATH, encoding="utf-8") as f:
            tb = json.load(f).get("theme_board", [])[:5]
            cache_top5 = [{"rk": x["elo_rk"], "plate": x["plate"], "sc_clean": x["score"], "elo": x["elo"], "sz": x["sz"]} for x in tb]
    print("[Parity Check 2026-11-23 Top 5]")
    print("  Ours :", parity_20261123[:5])
    print("  Cache:", cache_top5)

    cand_df, mkt, attrition = build_market_matrices_and_precompute_exits(df, cand_df)
    del df  # 释放主价格表内存

    win_meta, is_924 = build_benchmark_windows(mkt["cal_dts"])

    # 预构建全部布尔掩码加速网格过滤
    rk = cand_df["rk_c"].to_numpy()
    sc = cand_df["sc_clean"].to_numpy()
    sz = cand_df["sz"].to_numpy()
    cat = cand_df["theme_cat"].to_numpy()
    mcap = cand_df["mcap"].to_numpy()
    amt = cand_df["amt_yi"].to_numpy()
    pct = cand_df["pct"].to_numpy()
    is_zt = cand_df["is_zt"].to_numpy()
    rk100 = cand_df["amt_rk_100"].to_numpy()
    rk200 = cand_df["amt_rk_200"].to_numpy()
    cgrp = cand_df["csrc_grp"].to_numpy()
    is_app = cand_df["is_app"].to_numpy()

    # CSRC 对齐判定: TECH<->CSRC_TECH, CONS_DEF<->(CSRC_CONS_MED | (C38 & 家电)), CYC_FIN<->CSRC_CYC_FIN
    is_c38 = (cand_df["csrc_code3"].to_numpy() == "C38")
    aligned = (
        ((cat == "TECH") & (cgrp == "CSRC_TECH"))
        | ((cat == "CONS_DEF") & ((cgrp == "CSRC_CONS_MED") | (is_c38 & is_app)))
        | ((cat == "CYC_FIN") & (cgrp == "CSRC_CYC_FIN"))
    )

    masks = {
        "heat": {
            "ALL_HOT": np.ones(len(cand_df), dtype=bool),
            "rk1": rk == 1,
            "rk1_2": rk <= 2,
            "sc120": sc >= 120.0,
            "sc135": sc >= 135.0,
            "sc150": sc >= 150.0,
            "sz_3_9": (sz >= 3) & (sz <= 9),
            "sz_10_19": (sz >= 10) & (sz <= 19),
            "sz_20_35": (sz >= 20) & (sz <= 35),
            "sz_gt35": sz > 35,
        },
        "cat": {
            "ALL": np.ones(len(cand_df), dtype=bool),
            "TECH": cat == "TECH",
            "TECH_CORE": cand_df["is_tech_core"].to_numpy(),
            "CONS_DEF": cat == "CONS_DEF",
            "CONS_CORE": cand_df["is_cons_core"].to_numpy(),
            "APPLIANCE": is_app,
            "CYC_FIN": cat == "CYC_FIN",
        },
        "mcap": {
            "ge100": mcap >= 100.0,
            "100_200": (mcap >= 100.0) & (mcap < 200.0),
            "200_400": (mcap >= 200.0) & (mcap < 400.0),
            "400_800": (mcap >= 400.0) & (mcap < 800.0),
            "800plus": mcap >= 800.0,
            "ge200": mcap >= 200.0,
            "ge300": mcap >= 300.0,
        },
        "amt": {
            5: amt >= 5.0,
            10: amt >= 10.0,
            20: amt >= 20.0,
        },
        "pct": {
            "A_ZT": is_zt,
            "A_GE7_NOZT": (pct >= 0.07) & (~is_zt),
            "A_5_95": (pct >= 0.05) & (pct < 0.095) & (~is_zt),
            "A_STRONG": pct >= 0.05,
            "B_2_5": (pct >= 0.02) & (pct < 0.05),
            "B_LT2": pct < 0.02,
        },
        "pos": {
            "TOP1": rk100 == 1,
            "TOP2_3": (rk100 >= 2) & (rk100 <= 3),
            "TOP1_200": rk200 == 1,
        },
        "csrc": {
            "ALIGNED": aligned,
            "MISMATCH": ~aligned,
        },
    }

    configs = build_grid_configs()
    print(f"[Grid] Evaluating {len(configs)} unique entry configurations x 8 exit modes...", flush=True)

    all_rows = []
    t_eval = time.time()
    for idx_c, cfg in enumerate(configs):
        sub = apply_filters_and_dedup(cand_df, masks, cfg)
        if sub is None:
            continue
        rows = eval_entry_set(sub, mkt, win_meta, is_924, cfg)
        all_rows.extend(rows)
        if (idx_c + 1) % 500 == 0:
            print(f"  ... processed {idx_c+1}/{len(configs)} configs -> {len(all_rows)} rows ({time.time()-t_eval:.1f}s)", flush=True)

    res_df = pd.DataFrame(all_rows)
    grid_csv_path = f"{OUT_DIR}/grid_results.csv"
    res_df.to_csv(grid_csv_path, index=False)
    print(f"[Grid Done] Saved {len(res_df):,} grid rows to {grid_csv_path} in {time.time()-t_eval:.1f}s", flush=True)

    # 生成结构化 summary_part1.json
    bench_summary = {
        w: {k: v for k, v in wm.items() if k not in ("m_day", "m_bench")}
        for w, wm in win_meta.items()
    }
    bench_summary["csi1000_note"] = (
        "5年完整中证1000(sh000852)本地缺失(仅attr_index_sh000852.json含2026-06-15~08-24共50日, 且红线严禁联网API),"
        "故主基准以sh000300(沪深300)为核心硬基准, 并附sz399107(深证A指)作中小盘对照。"
    )

    # 提取关键维度切片与极值核查
    def top_slices(df_in, min_n=30, sort_col="eq_ex_csi_5y", n=15, ascending=False):
        f = df_in[df_in["n_5y"] >= min_n]
        if f.empty:
            return []
        return f.sort_values(sort_col, ascending=ascending).head(n).to_dict("records")

    # 抽样极值核查: 从最强和最差稳定切片 (n>=30) 核验代表性样本
    summary = {
        "meta": {
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t_start, 2),
            "universe": "00/60/30/688 excl .BJ and PIT ST (a_daily + a_delisted_daily)",
            "signal_window": f"{START_SIG_DT} ~ 2026-11-20 (buy T+1 up to {END_DT})",
            "fee_rate": FEE_RATE,
            "t1_attrition": attrition,
            "parity_20261123_ours_top5": parity_20261123[:5],
            "parity_20261123_cache_top5": cache_top5,
            "total_grid_rows": int(len(res_df)),
        },
        "benchmarks": bench_summary,
        "marginal_heat_H5_H10_H20": res_df[
            (res_df["slice_group"] == "1_HEAT_X_MCAP") & (res_df["mcap_bucket"].isin(["ge100", "ge200", "ge300", "800plus"])) & (res_df["exit_mode"].isin(["H1", "H5", "H10", "H20", "MA10"]))
        ].to_dict("records"),
        "heat_x_cat_ge200": res_df[
            (res_df["slice_group"] == "2_HEAT_X_CAT") & (res_df["mcap_bucket"] == "ge200") & (res_df["exit_mode"].isin(["H1", "H5", "H10", "H20", "MA10"]))
        ].to_dict("records"),
        "top15_by_eq_excess_5y_n30": top_slices(res_df, min_n=30, sort_col="eq_ex_csi_5y", n=15, ascending=False),
        "top15_by_slot_excess_5y_n30": top_slices(res_df, min_n=30, sort_col="slot_ex_csi_5y", n=15, ascending=False),
        "top15_by_eq_excess_ex924_n30": top_slices(res_df, min_n=30, sort_col="eq_ex_csi_5y_ex924", n=15, ascending=False),
        "bottom15_by_eq_excess_5y_n30": top_slices(res_df, min_n=30, sort_col="eq_ex_csi_5y", n=15, ascending=True),
        "top15_by_oos_excess_n20": top_slices(res_df[res_df["n_oos"] >= 20], min_n=20, sort_col="eq_ex_csi_oos", n=15, ascending=False),
        "appliance_special": res_df[
            (res_df["slice_group"] == "8_APPLIANCE_SPECIAL") & (res_df["plate_pos"].isin(["ALL", "TOP1"])) & (res_df["exit_mode"].isin(["H1", "H5", "H10", "MA10"]))
        ].to_dict("records"),
    }

    sum_path = f"{OUT_DIR}/summary_part1.json"
    with open(sum_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[All Done] Saved summary to {sum_path}. Total elapsed: {time.time()-t_start:.2f}s", flush=True)


if __name__ == "__main__":
    main()
