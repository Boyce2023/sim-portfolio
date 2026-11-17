#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
expA3_cross_learn_3to4_and_3board_matrix.py
================================================================================
A股一号席独立实证沙盒研究员 A3 独占研究脚本：
  任务一：三进四 V3.4 从 一进二 V18 & 二进三 V1.0 的全部异质因子双向实证（正/反/U型）
          严格遵守 IS(2022-2023) 定方向 -> OOS(2024-2026) 纯盲测 + D15 五期/HLZ t/Cap10M/Trim5
  任务二：一进二 × 二进三 × 三进四 统一口径「16核心共性因子跨板位方向翻转对照总表」
          覆盖 2021-01-04 ~ 2026-11-16 全量沪深10cm非ST真连板非一字可买底座 (IS 2021-2023 vs OOS 2024-2026)

红线铁律：
  - 严禁 import yfinance (D12)
  - 所有 SQLite 连接使用 file:...?mode=ro 只读模式
  - 仅写入 factor_mutual_learning_and_ablation_20261117/ 下独占输出文件
  - 内置三行铁律校验：单位除数 + 价格时间锚点 < buy_date 09:25:00 + 极值与列数 assert
================================================================================
"""
import os
import sys
import re
import json
import time
import math
import bisect
import pickle
import sqlite3
import datetime
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import scipy.stats as stats

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock/factor_mutual_learning_and_ablation_20261117"
os.makedirs(OUT_DIR, exist_ok=True)
OUT_JSON = f"{OUT_DIR}/result_A3_cross_learn_3to4_and_matrix.json"

FEE_RATE = 0.0020
SANDBOX = f"{SIM}/backtests_astock/sandbox_lab"
CLEAN_REF = f"{SIM}/backtests_astock/clean_rebacktest_20261116"

A_DAILY_PQ = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELIST_PQ = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
PARQUET_5M = f"{SIM}/data/all_strategies_5m_complete_pit.parquet"
BARS_34_5M = f"{SIM}/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet"
KPL_MERGED = f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl"
DB_ZT_TAPE = f"{SIM}/data/zt_micro_tape_5y_pit.db"
DB_XQ_GB = f"{SIM}/data/xueqiu_guba_5y_pit.db"
DB_COMM = f"{SIM}/data/astock_community_5y_pit.db"
DB_IR_QA = f"{SIM}/data/cninfo_ir_qa_5y_pit.db"
DB_NOTICES = f"{SIM}/data/cninfo_notices_5y_pit.db"
PQ_REG_TOX = f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet"
LHB_BUY_PQ = f"{SIM}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
HOLDERS_JSON = f"{SANDBOX}/grand_factor_matrix_20261112/pit_top10_all_codes.json"
HOLDERS_FREE_JSON = f"{SANDBOX}/pit_top10_freeholders_cache.json"
CSRC_PIT_CSV = f"{SIM}/data/csrc_industry_pit_clean.csv"
ST_UNIV_JSON = f"{SIM}/data/st_universe.json"
IND_CSV = f"{SIM}/data/industry.csv"
IDX_CACHE_JSON = f"{SANDBOX}/index_klines_5y_cache.json"
CSI_CANON_JSON = f"{CLEAN_REF}/csi300_canonical_20261116.json"
CACHE_3TO4_PKL = f"{SIM}/backtests_astock/special_26q4/3to4_26q4/cache_d_and_p.pkl"
LEDGER_1TO2_CSV = f"{CLEAN_REF}/partB_1to2/ledger_base_1to2_v18.csv"
LEDGER_2TO3_CSV = f"{SIM}/backtests_astock/clean_2to3_v10_20261117/ledger_base_2to3_v10_std90.csv"
LEDGER_3TO4_CSV = f"{CLEAN_REF}/partA_high_3to4/ledger_base_3to4_v34.csv"

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"

NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股",
}
EVENT_BASKET = {
    "并购重组", "股权转让", "资产注入", "国企改革", "央企改革",
    "地方国资改革", "业绩增长", "预盈预增", "摘帽", "回购",
    "增持", "次新股", "高送转", "参股新股", "三季报增长",
    "半年报增长", "年报增长", "一季报增长", "中报增长",
}
CSRC_PURE_OUTSIDER = {
    "A01", "A02", "A03", "A04", "A05", "D44", "D45", "D46", "E47", "E48", "E49", "E50",
    "F51", "F52", "G53", "G54", "G55", "G56", "G58", "G59", "H61", "H62", "K70", "L72",
    "N77", "N78", "C13", "C14", "C15", "C17", "C18", "C19", "C20", "C21", "C22",
}
HARD_TECH_RE = re.compile(
    r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)"
)
MA_PAT = re.compile(r"(?:重组|收购|股权转让|实控人变更|控制权变更|资产注入|借壳|控股|整合|中标|重大合同)")
TECH_PAT = re.compile(r"(?:芯片|半导体|光刻|集成电路|软件|信创|云计算|大数据|人工智能|AI|机器人|智能制造|通信|光通信|卫星|航天|军工|锂电|固态电池|光伏|储能|低空|无人驾驶)")
BAD_NOTICE_PAT = re.compile(r"(?:减持|问询函|监管函|警示函|立案|风险提示|业绩预亏|亏损|计提资产减值|退市风险|终止上市|违规|质押|冻结)")
NEG_NOTICE_PAT = re.compile(r"(?:不存在|不涉及|未筹划|未发现|无应披露|股票交易异常波动|异常波动公告|风险提示|占比极小|敬请广大投资者注意)")
HARD_NOTICE_PAT = re.compile(r"(?:重组|收购|股权转让|控制权|实控人变更|资产注入|借壳|重大合同|中标|战略合作|框架协议|投资设立)")
MA_NOTICE_PAT = re.compile(r"(?:重组|收购|股权转让|控制权变更|实控人变更|资产注入|借壳|重大合同|中标)")


def run_three_line_validation(df_panel: pd.DataFrame, upanel: pd.DataFrame, xq_max_ts: str, ir_violations: int, xq_violations: int):
    """硬编码三行铁律校验：单位除数 + 价格/PIT时间锚点 < buy_date 09:25:00 + 极值与列数 assert"""
    # 1. 单位除数校验: mcap 为亿元 (close * oshare / 1e8), to 为百分比 (turn * 100.0)
    med_mcap = float(df_panel["mcap"].median())
    med_to = float(df_panel["to"].median())
    assert 15.0 <= med_mcap <= 250.0 and 0.5 <= med_to <= 50.0, f"Unit divisor fail: mcap_med={med_mcap}, to_med={med_to}"
    # 2. 时间锚点校验: PIT 帖子与调研严格 < buy_date 09:25:00 且无未来日期泄漏
    assert ir_violations == 0 and xq_violations == 0 and xq_max_ts <= "2026-11-16 23:59:59", f"Time anchor fail: ir={ir_violations}, xq={xq_violations}, max={xq_max_ts}"
    # 3. 极值与列数校验: 候选底池行列规模与收益/开盘涨跌幅物理上下限
    assert df_panel.shape[0] >= 3000000 and df_panel.shape[1] >= 18 and upanel.shape[1] >= 35, f"Shape fail: {df_panel.shape} / {upanel.shape}"
    assert upanel["open_pct"].between(-0.11, 0.11).all() and upanel["ret_cc"].between(-0.55, 3.50).all(), "Extreme return/open_pct out of bounds!"


with open(IDX_CACHE_JSON, "r", encoding="utf-8") as _f:
    IDX_CACHE = json.load(_f)
CSI300_MAP = IDX_CACHE["sh000300"]
SH_MAP = IDX_CACHE["sh000002"]
SZ_MAP = IDX_CACHE["sz399107"]
ALL_CSI_DTS = sorted(CSI300_MAP.keys())


def get_csi300_ret(start_dt: str, end_dt: str) -> float:
    dts = [d for d in ALL_CSI_DTS if start_dt <= d <= end_dt]
    if not dts:
        return 0.0
    prevs = [d for d in ALL_CSI_DTS if d < dts[0]]
    p0 = CSI300_MAP[prevs[-1]] if prevs else CSI300_MAP[dts[0]]
    p1 = CSI300_MAP[dts[-1]]
    return float(p1 / p0 - 1.0)


def calc_strategy_metrics(df_trades: pd.DataFrame, start_dt: str = None, end_dt: str = None) -> dict:
    """严格对齐 D15 / synthesize_master_clean / audit_overfitting_8tests 全指标"""
    if df_trades.empty:
        csi_p = get_csi300_ret(start_dt, end_dt) * 100.0 if (start_dt and end_dt) else 0.0
        return {
            "n": 0, "wr": 0.0, "plr": 0.0, "mean_pct": 0.0, "nav_1s": 1.0,
            "cap10m_1m": 1.0, "cap10m_10m": 1.0, "trim5": 1.0, "mdd_pct": 0.0,
            "csi300_pct": round(csi_p, 2), "excess_pp": round(-csi_p, 2), "hlz_t": 0.0,
        }
    w = df_trades.copy()
    if start_dt:
        w = w[w["buy_date"] >= start_dt]
    if end_dt:
        w = w[w["buy_date"] <= end_dt]
    if w.empty:
        csi_p = get_csi300_ret(start_dt, end_dt) * 100.0 if (start_dt and end_dt) else 0.0
        return {
            "n": 0, "wr": 0.0, "plr": 0.0, "mean_pct": 0.0, "nav_1s": 1.0,
            "cap10m_1m": 1.0, "cap10m_10m": 1.0, "trim5": 1.0, "mdd_pct": 0.0,
            "csi300_pct": round(csi_p, 2), "excess_pp": round(-csi_p, 2), "hlz_t": 0.0,
        }
    rets = w["net_ret"].to_numpy(dtype=float)
    n = len(rets)
    wins, losses = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) and len(losses) and losses.mean() < 0) else (99.0 if len(wins) else 0.0)
    nav_1s = float(np.prod(1.0 + rets))
    pk, cur, mdd = 1.0, 1.0, 0.0
    for x in rets:
        cur *= (1.0 + x)
        pk = max(pk, cur)
        mdd = max(mdd, (pk - cur) / pk)
    cap_1m = 100.0
    cap_10m = 1000.0
    for x in rets:
        cap_1m += min(cap_1m, 1000.0) * float(x)
        cap_10m += min(cap_10m, 1000.0) * float(x)
    sr = np.sort(rets)
    trim5 = float(np.prod(1.0 + sr[:-5])) if n > 5 else 1.0
    s_eff = start_dt or str(w["buy_date"].min())
    e_eff = end_dt or str(w["buy_date"].max())
    csi_p = get_csi300_ret(s_eff, e_eff) * 100.0
    # HLZ t on per-trade excess over CSI300 holding window
    ex = np.array([float(r.net_ret) - get_csi300_ret(str(r.buy_date), str(r.exit_date)) for r in w.itertuples(index=False)], dtype=float)
    hlz_t = float((ex.mean() / ex.std(ddof=1)) * np.sqrt(n)) if (n > 1 and ex.std(ddof=1) > 1e-12) else 0.0
    return {
        "n": int(n),
        "wr": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav_1s": round(nav_1s, 2),
        "cap10m_1m": round(cap_1m / 100.0, 2),
        "cap10m_10m": round(cap_10m / 1000.0, 2),
        "trim5": round(trim5, 2),
        "mdd_pct": round(mdd * 100.0, 2),
        "csi300_pct": round(csi_p, 2),
        "excess_pp": round((nav_1s - 1.0) * 100.0 - csi_p, 2),
        "hlz_t": round(hlz_t, 2),
    }


def eval_five_windows_and_splits(df_trades: pd.DataFrame, is_start: str = "2022-01-04") -> dict:
    specs = [
        ("IS_22_23", is_start, "2023-12-31"),
        ("OOS_24_26", "2024-01-01", "2026-11-16"),
        ("full_5y", "2021-11-15", "2026-11-16"),
        ("recent_3y", "2023-11-16", "2026-11-16"),
        ("year_2026", "2026-01-01", "2026-11-16"),
        ("since_2607", "2026-07-01", "2026-11-16"),
        ("since_2610", "2026-10-01", "2026-11-16"),
    ]
    return {k: calc_strategy_metrics(df_trades, s, e) for k, s, e in specs}


def load_all_pit_sources():
    t0 = time.time()
    print("[1/5] Loading a_daily + a_delisted_daily (2018-2026)...")
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "turn", "oshare"]
    d1 = ds.dataset(A_DAILY_PQ, format="parquet").scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2018-01-01"))).to_table().to_pandas()
    d2 = ds.dataset(A_DELIST_PQ, format="parquet").scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2018-01-01"))).to_table().to_pandas()
    df = pd.concat([d1, d2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60")) & (~df["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    g = df.groupby("c6")
    df["nth"] = g.cumcount()
    df = df[df["nth"] >= 10].copy().reset_index(drop=True)
    g = df.groupby("c6")

    df["adjf"] = np.where(df["close"] > 0, df["adj_close"] / df["close"], 1.0)
    df["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["o_pct"] = df["open"] / df["pre_c"] - 1.0
    df["h_pct"] = df["high"] / df["pre_c"] - 1.0
    df["l_pct"] = df["low"] / df["pre_c"] - 1.0
    df["mcap"] = df["close"] * df["oshare"] / 1e8
    df["to"] = df["turn"] * 100.0
    df["zt_px"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["dt_px"] = np.floor(df["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["pre_c"] > 0) & (df["close"] >= df["zt_px"] - 0.011) & (df["pct"] >= 0.095)
    df["is_dt"] = (df["pre_c"] > 0) & (df["close"] <= df["dt_px"] + 0.011) & (df["pct"] <= -0.095)
    df["touch_zt"] = (df["pre_c"] > 0) & ((df["high"] >= df["zt_px"] - 0.011) | (df["h_pct"] >= 0.098))
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_px"] - 0.011) & (df["low"] >= df["zt_px"] - 0.011)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_px"] + 0.011) & (df["high"] <= df["dt_px"] + 0.011)

    s_zt = df["is_zt"].astype(int)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != g["is_zt"].shift().fillna(False)).cumsum()]).cumsum() * s_zt
    df["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)
    df["prev_is_yizi"] = g["is_yizi"].shift(1).fillna(False)
    df["buyable_open"] = (df["open"] < df["zt_px"] - 0.011) & (df["open"] > df["dt_px"] + 0.011) & (df["pre_c"] > 0)

    # Pre-compute technicals on daily panel for fast d0 lookup
    df["max20"] = g["high"].transform(lambda s: s.rolling(20, min_periods=10).max())
    df["min20"] = g["low"].transform(lambda s: s.rolling(20, min_periods=10).min())
    df["max60"] = g["high"].transform(lambda s: s.rolling(60, min_periods=20).max())
    df["vol_ma5"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    df["zt_cnt20"] = g["is_zt"].transform(lambda s: s.astype(int).rolling(20, min_periods=5).sum())
    df["ret10"] = df["close"] / (g["close"].shift(10) + 1e-6) - 1.0
    df["pos20_today"] = (df["close"] - df["min20"]) / (df["max20"] - df["min20"] + 1e-6)
    df["dd20_today"] = df["close"] / (df["max20"] + 1e-6)
    df["brk60_today"] = df["close"] >= g["max60"].shift(1) - 0.01

    # Load PIT tape + KPL ST sets
    con_tp = sqlite3.connect(f"file:{DB_ZT_TAPE}?mode=ro", uri=True)
    tp_df = pd.read_sql_query("SELECT trade_date, sec_code, sec_name, first_seal_time, seal_amount, open_board_count, plate_name FROM zt_micro_tape", con_tp)
    con_tp.close()
    tp_df["c6"] = tp_df["sec_code"].astype(str).str[:6].str.zfill(6)
    tape_map = {}
    st_pit_pairs = set()
    for r in tp_df.itertuples(index=False):
        tape_map[(r.trade_date, r.c6)] = (str(r.first_seal_time or "99:99:99"), float(r.seal_amount or 0.0), int(r.open_board_count if r.open_board_count is not None else -1))
        if ("ST" in str(r.sec_name).upper()) or ("退" in str(r.sec_name)) or (str(r.plate_name) == "ST板块"):
            st_pit_pairs.add((r.trade_date, r.c6))

    # Build daily market environment map indexed by sig_date (for buy_date lookup)
    print("[2/5] Computing daily market regime & promotion rates + KPL causal engine...")
    sub_env = df[df["dt_str"] >= "2020-06-01"]
    env_rows = []
    stk_day_streak = {}
    for dt, grp in sub_env.groupby("dt_str", sort=True):
        zt_g = grp[grp["is_zt"]]
        for c6_v, st_v in zip(zt_g["c6"].values, zt_g["streak"].values):
            stk_day_streak[(dt, c6_v)] = int(st_v)
        n_zt = int(len(zt_g))
        n_touch = int(grp["touch_zt"].sum())
        seal_r = n_zt / max(1, n_touch)
        max_b = int(zt_g["streak"].max()) if n_zt > 0 else 0
        s1 = grp[(grp["prev_streak"] == 1) & (~grp["prev_is_yizi"])]
        s2 = grp[(grp["prev_streak"] == 2) & (~grp["prev_is_yizi"])]
        s3 = grp[(grp["prev_streak"] == 3) & (~grp["prev_is_yizi"])]
        p12 = float(s1["is_zt"].mean()) if len(s1) > 0 else np.nan
        p23 = float(s2["is_zt"].mean()) if len(s2) > 0 else np.nan
        p34 = float(s3["is_zt"].mean()) if len(s3) > 0 else np.nan
        c34_s = s3[s3["buyable_open"] & (s3["o_pct"] >= 0.03)]
        s34_ho = float(c34_s["is_zt"].mean()) if len(c34_s) > 0 else np.nan
        c12_s = s1[s1["buyable_open"] & (s1["o_pct"] >= 0.055)]
        s12_ho = float(c12_s["is_zt"].mean()) if len(c12_s) > 0 else np.nan
        yz_open = int((grp["open"] >= grp["zt_px"] - 0.011).sum())
        env_rows.append({
            "sig_date": dt, "mkt_zt_prev": n_zt, "mkt_dt_prev": int(grp["is_dt"].sum()),
            "mkt_seal_rate_prev": seal_r, "mkt_maxb_prev": max_b,
            "mkt_p12_prev": p12, "mkt_p23_prev": p23, "mkt_p34_prev": p34,
            "s34_ho": s34_ho, "s12_ho": s12_ho, "mkt_yz_open": yz_open,
        })
    edf = pd.DataFrame(env_rows).sort_values("sig_date").reset_index(drop=True)
    edf["mkt_p12_prev_f"] = edf["mkt_p12_prev"].ffill().fillna(0.20)
    edf["mkt_p23_prev_f"] = edf["mkt_p23_prev"].ffill().fillna(0.30)
    edf["mkt_p34_prev_f"] = edf["mkt_p34_prev"].ffill().fillna(0.35)
    edf["mkt_p12_5d"] = edf["mkt_p12_prev"].rolling(5, min_periods=2).mean().fillna(0.20)
    edf["mkt_p23_5d"] = edf["mkt_p23_prev"].rolling(5, min_periods=2).mean().fillna(0.30)
    edf["mkt_p34_5d"] = edf["mkt_p34_prev"].rolling(5, min_periods=2).mean().fillna(0.35)
    edf["roll20_3to4_seal"] = edf["s34_ho"].rolling(20, min_periods=5).mean().fillna(0.35)
    edf["roll20_1to2_ho_zt"] = edf["s12_ho"].rolling(20, min_periods=5).mean().fillna(0.45)
    env_sig_map = edf.set_index("sig_date").to_dict(orient="index")

    # KPL 8-year causal engine
    sub_stat = df[df["dt_str"] >= "2018-04-01"][["dt_str", "c6", "pct", "is_zt", "touch_zt"]]
    stat_map = {(r.dt_str, r.c6): (float(r.pct), bool(r.is_zt), bool(r.touch_zt)) for r in sub_stat.itertuples(index=False) if pd.notna(r.pct)}
    kpl_by_dt = {}
    with open(KPL_MERGED, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                d = json.loads(ln)
                dt_k = d.get("date", "")
                pls = d.get("plates", [])
                if dt_k and sum(len(p.get("stocks", [])) for p in pls) > 0:
                    kpl_by_dt[dt_k] = pls
    kpl_dates = sorted(kpl_by_dt.keys())

    elo = defaultdict(lambda: 100.0)
    sub_elo = defaultdict(lambda: 100.0)
    plate_last_idx, sub_last_idx = {}, {}
    prev_p, prev_sub = {}, {}
    plate_sz_by_idx = defaultdict(dict)
    hist_hhi = []

    kpl_stock_meta = {}   # (sig_date, c6) -> dict
    kpl_day_meta = {}     # sig_date -> dict
    kpl_plate_stocks = {} # (sig_date, plate) -> list of c6

    for idx, dt in enumerate(kpl_dates):
        plates = kpl_by_dt[dt]
        for pname, c6_list in prev_p.items():
            touches = seals = 0
            rets = []
            for c6 in c6_list:
                st = stat_map.get((dt, c6))
                if st is not None:
                    rets.append(st[0]); seals += int(st[1]); touches += int(st[2])
            if touches >= 2 and (seals / touches) < 0.50:
                elo[pname] -= 12.0 * ((touches - seals) / touches)
            elif rets and float(np.mean(rets)) < -0.025:
                elo[pname] -= 10.0
            elif seals >= 2 and (seals / max(touches, 1)) >= 0.70:
                elo[pname] += min(10.0, 5.0 + seals * 1.2)
            elif rets and float(np.mean(rets)) > 0.025:
                elo[pname] += 6.0
        for sname, c6_list in prev_sub.items():
            touches = seals = 0
            rets = []
            for c6 in c6_list:
                st = stat_map.get((dt, c6))
                if st is not None:
                    rets.append(st[0]); seals += int(st[1]); touches += int(st[2])
            if touches >= 2 and (seals / touches) < 0.50:
                sub_elo[sname] -= 10.0 * ((touches - seals) / touches)
            elif rets and float(np.mean(rets)) < -0.025:
                sub_elo[sname] -= 8.0
            elif seals >= 1 and (seals / max(touches, 1)) >= 0.70:
                sub_elo[sname] += min(9.0, 4.0 + seals * 1.5)
            elif rets and float(np.mean(rets)) > 0.025:
                sub_elo[sname] += 5.0
        for pk in list(elo.keys()):
            if idx - plate_last_idx.get(pk, idx) > 3:
                elo[pk] = 100.0 + (elo[pk] - 100.0) * 0.85
        for sk in list(sub_elo.keys()):
            if idx - sub_last_idx.get(sk, idx) > 3:
                sub_elo[sk] = 100.0 + (sub_elo[sk] - 100.0) * 0.85

        new_prev_p, new_prev_sub = {}, defaultdict(list)
        sz_all, cur_day_sz, noev_list = [], {}, []
        day_stk_plates = defaultdict(list)
        day_stk_s2 = {}
        day_plate_c6 = {}
        for p in plates:
            pname = p.get("plate", "")
            stks_p = p.get("stocks", [])
            sz = len(stks_p)
            for s in stks_p:
                c6 = str(s[0]).strip()[:6].zfill(6)
                nm = str(s[1]) if len(s) > 1 else ""
                if ("ST" in nm.upper()) or ("退" in nm) or (pname == "ST板块"):
                    st_pit_pairs.add((dt, c6))
            if sz == 0 or pname in NON_THEME:
                continue
            cur_day_sz[pname] = sz
            sz_all.append(sz)
            if pname not in EVENT_BASKET:
                noev_list.append((pname, sz))
            plate_sz_by_idx[pname][idx] = sz
            plate_last_idx[pname] = idx
            c6_l = []
            for s in stks_p:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6_l.append(c6)
                s2 = str(s[2]).strip() if len(s) > 2 else ""
                if s2 and s2 not in NON_THEME and s2 != "无":
                    new_prev_sub[s2].append(c6)
                    sub_last_idx[s2] = idx
                    if c6 not in day_stk_s2:
                        day_stk_s2[c6] = s2
                day_stk_plates[c6].append((pname, sz))
            new_prev_p[pname] = c6_l
            day_plate_c6[pname] = c6_l

        tot_s = sum(sz_all)
        hhi_all = sum((x / tot_s) ** 2 for x in sz_all) if tot_s > 0 else 1.0
        hhi_pct = 0.5
        if dt >= "2019-12-01":
            win = hist_hhi[-250:]
            hhi_pct = float(np.mean([1.0 if x <= hhi_all else 0.0 for x in win])) if len(win) >= 20 else 0.5
            hist_hhi.append(hhi_all)

        if dt >= "2020-12-01":
            noev_list.sort(key=lambda x: x[1], reverse=True)
            top1_sz = noev_list[0][1] if noev_list else 0
            rk_noev_map = {pn: i + 1 for i, (pn, _) in enumerate(noev_list)}
            mkt_zt_n = env_sig_map.get(dt, {}).get("mkt_zt_prev", max(tot_s, 1))
            top1_share = top1_sz / max(mkt_zt_n, 1)
            kpl_day_meta[dt] = {
                "hhi": hhi_all, "hhi_pct": hhi_pct,
                "b01_hhi_low_q25": int(hhi_pct <= 0.25),
                "b03_hhi_high_q75": int(hhi_pct >= 0.75),
                "raw_top1_share": top1_share,
            }
            p_metrics = {}
            for pname, sz0 in cur_day_sz.items():
                pdict = plate_sz_by_idx[pname]
                arr65 = np.array([pdict.get(idx - 64 + k, 0) for k in range(65)], dtype=int)
                max_far_20 = int(arr65[65 - 20:65 - 2].max())
                run_ge2 = 0
                for v in arr65[::-1]:
                    if v >= 2:
                        run_ge2 += 1
                    else:
                        break
                pre_end = 65 - run_ge2
                pre_max = int(arr65[max(0, pre_end - 20):pre_end].max()) if pre_end > 0 else 0
                w1_day = run_ge2 if (run_ge2 >= 1 and pre_max < 6) else 0
                has_w2_20 = False
                has_w2_30 = False
                if sz0 >= 4:
                    for win_d, flag_name in [(20, "20"), (30, "30")]:
                        sub_a = arr65[65 - win_d:64]
                        hit = any(sub_a[k] >= 6 and (sub_a[k + 1:] <= 3).sum() >= 2 for k in range(len(sub_a) - 2))
                        if flag_name == "20":
                            has_w2_20 = hit
                        else:
                            has_w2_30 = hit
                c6_list_p = day_plate_c6.get(pname, [])
                kpl_plate_stocks[(dt, pname)] = c6_list_p
                max_stk_p = max((stk_day_streak.get((dt, x), 1) for x in c6_list_p), default=1)
                cnt_ge4_p = sum(1 for x in c6_list_p if stk_day_streak.get((dt, x), 1) >= 4)
                cnt_ge3_p = sum(1 for x in c6_list_p if stk_day_streak.get((dt, x), 1) >= 3)
                cnt_ge2_p = sum(1 for x in c6_list_p if stk_day_streak.get((dt, x), 1) >= 2)
                p_metrics[pname] = {
                    "elo": float(elo[pname]), "sz": int(sz0), "rk_noev": rk_noev_map.get(pname, 99),
                    "w1_day1_3": int(1 <= w1_day <= 3),
                    "w1_fresh20": int(sz0 >= 3 and max_far_20 < 4),
                    "w2_20": int(has_w2_20), "w2_30": int(has_w2_30),
                    "max_stk": max_stk_p, "cnt_ge4": cnt_ge4_p, "cnt_ge3": cnt_ge3_p, "cnt_ge2": cnt_ge2_p,
                }
            for c6, pls in day_stk_plates.items():
                pls_s = sorted(pls, key=lambda x: (-x[1], rk_noev_map.get(x[0], 99)))
                best_p, best_sz = pls_s[0]
                pm = p_metrics[best_p]
                s2_nm = day_stk_s2.get(c6)
                s_elo_v = float(sub_elo[s2_nm]) if s2_nm else pm["elo"]
                kpl_stock_meta[(dt, c6)] = {
                    "plate": best_p, "plate_sz": best_sz, "plate_rk_noev": pm["rk_noev"],
                    "p_elo": pm["elo"], "s_elo": s_elo_v,
                    "w1_day1_3": pm["w1_day1_3"], "w1_fresh20": pm["w1_fresh20"],
                    "w2_reb": int(pm["w2_20"] == 1 or pm["w2_30"] == 1),
                    "elo_ice": int(pm["elo"] <= 95.0 or s_elo_v <= 95.0),
                    "plate_max_stk": pm["max_stk"],
                    "plate_cnt_ge4": pm["cnt_ge4"], "plate_cnt_ge3": pm["cnt_ge3"], "plate_cnt_ge2": pm["cnt_ge2"],
                    "is_event_basket": int(best_p in EVENT_BASKET),
                }
        prev_p, prev_sub = new_prev_p, new_prev_sub

    print("[3/5] Loading Xueqiu, IR-QA, LHB, Holders, CSRC, Notices & 5m bars...")
    # Xueqiu union (xueqiu_guba_5y_pit + astock_community_5y_pit)
    xq_seen = defaultdict(set)
    xq_posts_by_c6 = defaultdict(list)
    xq_max_ts = ""
    con_xq = sqlite3.connect(f"file:{DB_XQ_GB}?mode=ro", uri=True)
    xq_max_ts = str(con_xq.execute("SELECT MAX(created_time_str) FROM xueqiu_posts").fetchone()[0] or "")
    for sym, pid, cts in con_xq.execute("SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE created_time_str >= '2020-12-01'"):
        c6 = str(sym)[:6].zfill(6)
        pid_c = str(pid).replace("xq_", "")
        if pid_c not in xq_seen[c6]:
            xq_seen[c6].add(pid_c)
            xq_posts_by_c6[c6].append(str(cts))
    con_xq.close()
    con_cm = sqlite3.connect(f"file:{DB_COMM}?mode=ro", uri=True)
    for sym, pid, cts in con_cm.execute("SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND pub_datetime_cst >= '2020-12-01'"):
        c6 = str(sym)[:6].zfill(6)
        pid_c = str(pid).replace("xq_", "")
        if pid_c not in xq_seen[c6]:
            xq_seen[c6].add(pid_c)
            xq_posts_by_c6[c6].append(str(cts))
    con_cm.close()
    xq_arr_map = {c6: np.sort(np.array(v, dtype=str)) for c6, v in xq_posts_by_c6.items()}

    # IR-QA (trade_date_avail <= sig_date AND pub_datetime_cst < buy_date 09:25:00)
    con_ir = sqlite3.connect(f"file:{DB_IR_QA}?mode=ro", uri=True)
    ir_rows = con_ir.execute("SELECT sec_code, pub_datetime_cst, trade_date_avail FROM ir_qa WHERE pub_datetime_cst >= '2020-10-01'").fetchall()
    con_ir.close()
    ir_map = defaultdict(list)
    for sc, pdt, av in ir_rows:
        if pdt and av:
            ir_map[str(sc)[:6].zfill(6)].append((str(pdt), str(av)))
    for c6 in ir_map:
        ir_map[c6].sort(key=lambda x: x[0])

    # LHB Lhasa seats
    lhb = pd.read_parquet(LHB_BUY_PQ, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME"])
    lhb["dt"] = lhb["TRADE_DATE"].astype(str).str[:10]
    lhb = lhb[lhb["dt"] >= "2020-12-01"].copy()
    lhb["c6"] = lhb["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    lhb["is_lh"] = lhb["OPERATEDEPT_NAME"].astype(str).str.contains("拉萨", na=False).astype(int)
    lh_grp = lhb.groupby(["dt", "c6"])["is_lh"].sum().to_dict()

    # Holders lock_top10
    holders_map = json.load(open(HOLDERS_JSON, encoding="utf-8"))
    if os.path.exists(HOLDERS_FREE_JSON):
        hf = json.load(open(HOLDERS_FREE_JSON, encoding="utf-8"))
        for c6, lst in hf.items():
            if lst and c6 not in holders_map:
                by_ed = {}
                for it in lst:
                    nd, ed = str(it.get("NOTICE_DATE") or "")[:10], str(it.get("END_DATE") or "")[:10]
                    rt = float(it.get("FREE_HOLDNUM_RATIO") or 0.0)
                    if nd and ed and rt > 0:
                        rec = by_ed.setdefault(ed, [nd, 0.0, 0.0])
                        rec[0] = min(rec[0], nd); rec[1] += rt
                        if rt >= 5.0: rec[2] += rt
                if by_ed:
                    holders_map[c6] = sorted([[v[0], ed, round(min(95.0, v[1]), 2), round(min(95.0, v[2]), 2)] for ed, v in by_ed.items()])

    # CSRC PIT
    df_csrc = pd.read_csv(CSRC_PIT_CSV)
    df_csrc["c6"] = df_csrc["sec_code"].astype(str).str.zfill(6)
    csrc_pit = defaultdict(list)
    for r in df_csrc[["c6", "start_date", "end_date", "industry"]].itertuples(index=False):
        csrc_pit[r.c6].append((str(r.start_date), str(r.end_date), str(r.industry or "")))

    # 5m bars merged (all_strategies_5m_complete_pit + cand_3to4_5m_bars)
    df5_a = pd.read_parquet(PARQUET_5M, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"])
    df5_b = pd.read_parquet(BARS_34_5M, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"])
    df5 = pd.concat([df5_a, df5_b], ignore_index=True)
    df5.drop_duplicates(["c6", "date", "hhmm_int"], keep="first", inplace=True)
    df5.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_map = {
        (c6, d): g_5[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        for (c6, d), g_5 in df5.groupby(["c6", "date"], sort=False)
    }

    print(f"  All PIT sources loaded in {time.time()-t0:.1f}s (5m keys={len(bars_5m_map):,})")
    return {
        "df": df, "tape_map": tape_map, "st_pit_pairs": st_pit_pairs,
        "env_sig_map": env_sig_map, "kpl_stock_meta": kpl_stock_meta,
        "kpl_day_meta": kpl_day_meta, "kpl_plate_stocks": kpl_plate_stocks,
        "stk_day_streak": stk_day_streak, "xq_arr_map": xq_arr_map,
        "xq_max_ts": xq_max_ts, "ir_map": ir_map, "lh_grp": lh_grp,
        "holders_map": holders_map, "csrc_pit": csrc_pit, "bars_5m_map": bars_5m_map,
    }


def _pit_lock(holders_map: dict, c6: str, buy_date: str) -> float:
    valid = [r for r in holders_map.get(c6, []) if str(r[0]) < buy_date]
    if not valid:
        return 38.0
    return float(max(valid, key=lambda x: (str(x[1]), str(x[0])))[2])


def _pit_csrc(csrc_pit: dict, c6: str, buy_date: str) -> str:
    ivs = csrc_pit.get(c6)
    if not ivs:
        return ""
    for s, e, ind in ivs:
        if s <= buy_date <= e:
            return ind
    if buy_date < ivs[0][0]:
        return ivs[0][2]
    return ivs[-1][2]


def _xq_counts(xq_arr_map: dict, c6: str, d_start: str, sig_date: str, buy_date: str) -> tuple[int, int, int]:
    arr = xq_arr_map.get(c6)
    if arr is None or len(arr) == 0:
        return 0, 0, 0
    cut_end = f"{buy_date} 09:25:00"
    p_end = int(np.searchsorted(arr, cut_end, side="left"))
    p_2d = int(np.searchsorted(arr, f"{d_start} 00:00:00", side="left"))
    p_24h = int(np.searchsorted(arr, f"{sig_date} 09:25:00", side="left"))
    p_pre7_lo = int(np.searchsorted(arr, (datetime.date.fromisoformat(d_start) - datetime.timedelta(days=7)).isoformat() + " 00:00:00", side="left"))
    # Time anchor audit: ensure max returned index strictly < buy_date 09:25:00
    viol = 1 if (p_end > 0 and arr[p_end - 1] >= cut_end) else 0
    return max(0, p_end - p_2d), max(0, p_end - p_24h), viol


def _ir_has_20d(ir_map: dict, c6: str, sig_date: str, buy_date: str) -> tuple[int, int]:
    lst = ir_map.get(c6)
    if not lst:
        return 0, 0
    cut_end = f"{buy_date} 09:25:00"
    lo_dt = (datetime.date.fromisoformat(buy_date) - datetime.timedelta(days=20)).isoformat()
    hit, viol = 0, 0
    for pdt, av in lst:
        if pdt >= cut_end:
            break
        if av <= sig_date and pdt[:10] >= lo_dt:
            hit = 1
        if pdt >= cut_end and av <= sig_date and pdt[:10] < buy_date:
            viol += 1
    return hit, viol


def build_unified_3board_panel(pit: dict) -> tuple[pd.DataFrame, dict]:
    t0 = time.time()
    print("[4/5] Building unified 1to2 / 2to3 / 3to4 5Y base panel & Task 2 matrix...")
    df = pit["df"]
    sub = df[df["dt_str"] >= "2020-08-01"].copy()
    bars = {}
    for c6, gc in sub.groupby("c6", sort=False):
        bars[c6] = {
            "dts": gc["dt_str"].values,
            "dpos": {d: i for i, d in enumerate(gc["dt_str"].values)},
            "open": gc["open"].values.astype(float),
            "high": gc["high"].values.astype(float),
            "low": gc["low"].values.astype(float),
            "close": gc["close"].values.astype(float),
            "adjf": gc["adjf"].values.astype(float),
            "pre_c": gc["pre_c"].values.astype(float),
            "pct": gc["pct"].values.astype(float),
            "o_pct": gc["o_pct"].values.astype(float),
            "l_pct": gc["l_pct"].values.astype(float),
            "mcap": gc["mcap"].values.astype(float),
            "to": gc["to"].values.astype(float),
            "amount": gc["amount"].values.astype(float),
            "is_zt": gc["is_zt"].values.astype(bool),
            "is_yizi_dt": gc["is_yizi_dt"].values.astype(bool),
            "pos20_today": gc["pos20_today"].values.astype(float),
            "dd20_today": gc["dd20_today"].values.astype(float),
            "brk60_today": gc["brk60_today"].values.astype(bool),
            "ret10": gc["ret10"].values.astype(float),
            "zt_cnt20": gc["zt_cnt20"].values.astype(float),
        }

    # Buy-date plate open peers map across all prev_streak >= 1 candidates
    cand_raw = df[
        (df["dt_str"] >= "2021-01-04") & (df["dt_str"] <= "2026-11-16")
        & df["prev_streak"].isin([1, 2, 3]) & (~df["prev_is_yizi"]) & df["buyable_open"]
    ].copy()
    cand_raw["sig_date"] = ""
    # Fast sig_date & return simulation via bars dict
    st_pairs = pit["st_pit_pairs"]
    env_sig_map = pit["env_sig_map"]
    kpl_stock_meta = pit["kpl_stock_meta"]
    kpl_day_meta = pit["kpl_day_meta"]
    tape_map = pit["tape_map"]
    xq_arr_map = pit["xq_arr_map"]
    ir_map = pit["ir_map"]
    lh_grp = pit["lh_grp"]
    holders_map = pit["holders_map"]

    rows = []
    ir_viol_tot, xq_viol_tot = 0, 0
    for r in cand_raw.itertuples(index=False):
        c6 = r.c6
        bd = r.dt_str
        b = bars.get(c6)
        if b is None:
            continue
        pos = b["dpos"].get(bd, -1)
        n = len(b["dts"])
        if pos < 3 or pos >= n - 1:
            continue
        k_prev = int(r.prev_streak)
        sd = str(b["dts"][pos - 1])
        if (sd, c6) in st_pairs or (bd, c6) in st_pairs:
            continue
        # d1 = first board of streak, d0 = day before d1
        pos_d1 = pos - k_prev
        pos_d0 = pos_d1 - 1
        if pos_d0 < 1:
            continue
        d1_dt = str(b["dts"][pos_d1])

        # Compute clean relay exit (ret_cc) and model-free T->T+1 close (ret_t1c)
        bpx = float(b["open"][pos])
        adj_b = float(b["adjf"][pos])
        if bpx <= 0 or adj_b <= 0:
            continue

        # T->T+1 close (skipping yizi跌停)
        k1 = pos + 1
        while k1 < n and bool(b["is_yizi_dt"][k1]):
            k1 += 1
        k1 = min(k1, n - 1)
        ret_t1c = (float(b["close"][k1]) * float(b["adjf"][k1])) / (bpx * adj_b) * (1.0 - FEE_RATE) - 1.0

        # Clean relay exit
        if not bool(b["is_zt"][pos]):
            kc = pos + 1
            while kc < n and bool(b["is_yizi_dt"][kc]):
                kc += 1
            kc = min(kc, n - 1)
            if kc > pos + 1:
                ep = float(b["open"][kc])
            elif (float(b["close"][pos]) < bpx) or (float(b["open"][kc]) < float(b["pre_c"][kc]) * 1.005):
                ep = float(b["open"][kc])
            else:
                ep = float(b["close"][kc])
            ret_cc = (ep * float(b["adjf"][kc])) / (bpx * adj_b) * (1.0 - FEE_RATE) - 1.0
        else:
            kc = pos + 1
            while kc < n and bool(b["is_zt"][kc]):
                kc += 1
            while kc < n and bool(b["is_yizi_dt"][kc]):
                kc += 1
            kc = min(kc, n - 1)
            ret_cc = (float(b["close"][kc]) * float(b["adjf"][kc])) / (bpx * adj_b) * (1.0 - FEE_RATE) - 1.0

        env = env_sig_map.get(sd, {})
        km = kpl_stock_meta.get((sd, c6), {})
        kd = kpl_day_meta.get(sd, {})
        fst, seal_amt, opn_cnt = tape_map.get((sd, c6), ("99:99:99", 0.0, -1))
        prev_amt = float(b["amount"][pos - 1])
        sar = (seal_amt / prev_amt) if (seal_amt > 0 and prev_amt > 0) else np.nan
        # Seal sec from 09:30
        seal_sec = np.nan
        if fst and not fst.startswith("99"):
            try:
                hh, mm, ss = [int(x) for x in fst.split(":")[:3]]
                seal_sec = float((hh - 9) * 3600 + (mm - 30) * 60 + ss) if hh < 12 else float(7200 + (hh - 13) * 3600 + mm * 60 + ss)
            except Exception:
                seal_sec = np.nan

        xq_2d, xq_24h, v_xq = _xq_counts(xq_arr_map, c6, d1_dt, sd, bd)
        ir20, v_ir = _ir_has_20d(ir_map, c6, sd, bd)
        ir_viol_tot += v_ir
        xq_viol_tot += v_xq

        lock10 = _pit_lock(holders_map, c6, bd)
        mcap_prev = float(b["mcap"][pos - 1])
        rf_mcap = mcap_prev * max(0.05, 1.0 - lock10 / 100.0)
        prev_to = float(b["to"][pos - 1])
        prev_real_to = prev_to / max(0.05, 1.0 - lock10 / 100.0)

        p20_d0 = float(b["pos20_today"][pos_d0]) if pd.notna(b["pos20_today"][pos_d0]) else 0.5
        ret10_d0 = float(b["ret10"][pos_d0]) if pd.notna(b["ret10"][pos_d0]) else 0.0
        zt20_d0 = float(b["zt_cnt20"][pos_d0]) if pd.notna(b["zt_cnt20"][pos_d0]) else 0.0
        to_d1 = float(b["to"][pos_d1]) if pd.notna(b["to"][pos_d1]) else 10.0
        clean_brk60 = int(bool(b["brk60_today"][pos_d1]) and ret10_d0 <= 0.08 and zt20_d0 == 0 and to_d1 <= 14.0)

        p_max_stk = int(km.get("plate_max_stk", k_prev)) if km else k_prev
        has_higher_bro = int(p_max_stk > k_prev)
        w1_frag = int((km.get("w1_day1_3", 0) == 1 or km.get("w1_fresh20", 0) == 1) and km.get("elo_ice", 0) == 0)

        rows.append({
            "code": c6, "buy_date": bd, "sig_date": sd, "d1_date": d1_dt,
            "board": k_prev, "is_zt_today": int(b["is_zt"][pos]),
            "ret_cc": round(float(ret_cc), 6), "ret_t1c": round(float(ret_t1c), 6),
            "open_pct": float(b["o_pct"][pos]),
            "prev_low_pct": float(b["l_pct"][pos - 1]),
            "px_prev": float(b["close"][pos - 1]),
            "mcap": mcap_prev, "lock_top10": lock10, "real_free_mcap": rf_mcap,
            "prev_to": prev_to, "prev_real_to": prev_real_to,
            "pos20_d0": p20_d0, "clean_brk60": clean_brk60,
            "seal_amt_ratio": sar, "seal_sec": seal_sec, "open_cnt": opn_cnt,
            "xq_cnt_2d": xq_2d, "xq_cnt_24h": xq_24h, "ir_has_20d": ir20,
            "lhasa_seats": int(lh_grp.get((sd, c6), 0)),
            "mkt_zt_prev": int(env.get("mkt_zt_prev", 50)),
            "mkt_maxb_prev": int(env.get("mkt_maxb_prev", 4)),
            "mkt_p12_prev": float(env.get("mkt_p12_prev_f", 0.20)),
            "mkt_p23_prev": float(env.get("mkt_p23_prev_f", 0.30)),
            "mkt_p34_prev": float(env.get("mkt_p34_prev_f", 0.35)),
            "b01_hhi_low_q25": int(kd.get("b01_hhi_low_q25", 0)),
            "b03_hhi_high_q75": int(kd.get("b03_hhi_high_q75", 0)),
            "raw_top1_share": float(kd.get("raw_top1_share", 0.15)),
            "plate": km.get("plate", "其他"),
            "plate_sz": int(km.get("plate_sz", 1)),
            "plate_rk_noev": int(km.get("plate_rk_noev", 99)),
            "p_elo": float(km.get("p_elo", 100.0)),
            "elo_ice": int(km.get("elo_ice", 0)),
            "w1_frag": w1_frag,
            "w2_reb": int(km.get("w2_reb", 0)),
            "has_plate_higher_bro": has_higher_bro,
        })

    upanel = pd.DataFrame(rows)
    run_three_line_validation(df, upanel, pit["xq_max_ts"], ir_viol_tot, xq_viol_tot)
    assert len(upanel) >= 55000, f"Unified 3-board panel too small: {len(upanel)}"

    # Build 16 core factor specs (Top mask vs Bottom mask)
    def make_16_factors(d: pd.DataFrame) -> list:
        seal_dead = (d["seal_amt_ratio"].fillna(0) >= 0.25) | ((d["open_cnt"] == 0) & (d["seal_sec"].fillna(99999) <= 300))
        seal_weak = (d["open_cnt"] >= 1) & ((d["seal_sec"].fillna(0) >= 1800) | (d["seal_amt_ratio"].fillna(1) < 0.05))
        return [
            ("F01_雪球盘前高热(>=4帖 vs 0帖暗牌)", d["xq_cnt_2d"] >= 4, d["xq_cnt_2d"] == 0),
            ("F02_近20日机构调研(有 vs 无)", d["ir_has_20d"] == 1, d["ir_has_20d"] == 0),
            ("F03_全市场离散HHI(低HHI_q25 vs 主线>=30%)", d["b01_hhi_low_q25"] == 1, d["raw_top1_share"] >= 0.30),
            ("F04_昨日2进3晋级率(高>=35% vs 冰点<22%)", d["mkt_p23_prev"] >= 0.35, d["mkt_p23_prev"] < 0.22),
            ("F05_市场最高连板空间(高标>=6板 vs 破局<=4板)", d["mkt_maxb_prev"] >= 6, d["mkt_maxb_prev"] <= 4),
            ("F06_市场涨停温热度(过热>=95家 vs 温热35~85)", d["mkt_zt_prev"] >= 95, d["mkt_zt_prev"].between(35, 85)),
            ("F07_同板块更高连板压制(有老大哥 vs 板块最高)", d["has_plate_higher_bro"] == 1, d["has_plate_higher_bro"] == 0),
            ("F08_题材一二波周期(二波回流 vs 一波脆期)", d["w2_reb"] == 1, d["w1_frag"] == 1),
            ("F09_板块涨停拥挤度(大主线>=8家 vs 温热2~5家)", d["plate_sz"] >= 8, d["plate_sz"].between(2, 5)),
            ("F10_竞价开盘涨幅(+6%~+9.2%高开 vs -2%~+2.5%)", d["open_pct"].between(0.06, 0.092), d["open_pct"].between(-0.02, 0.025)),
            ("F11_前日换手率(高换>25% vs 温和8.5%~18%)", d["prev_to"] > 25.0, d["prev_to"].between(8.5, 18.0)),
            ("F12_前日封单强度(死锁秒板 vs 开板弱封)", seal_dead, seal_weak),
            ("F13_前日深水探底洗盘(low<=-2% vs 全程水上>=0%)", d["prev_low_pct"] <= -0.02, d["prev_low_pct"] >= 0.0),
            ("F14_启动前20日箱体分位(高位>=70% vs 低位<=40%)", d["pos20_d0"] >= 0.70, d["pos20_d0"] <= 0.40),
            ("F15_流通市值弹性(大中盘>90亿 vs 小盘<=45亿)", d["mcap"] > 90.0, d["mcap"] <= 45.0),
            ("F16_锁仓x真换手(lock>=50&真换25~65 vs 双低)", (d["lock_top10"] >= 50.0) & d["prev_real_to"].between(25.0, 65.0), (d["lock_top10"] < 45.0) & (d["real_free_mcap"] < 45.0)),
        ]

    # Compute Task 2 unified comparison matrix across boards 1, 2, 3 and IS / OOS / 5Y
    matrix_rows = []
    f_specs_all = make_16_factors(upanel)
    for f_idx, (fname, _, _) in enumerate(f_specs_all):
        row_out = {"factor": fname, "boards": {}}
        for b_val, b_lbl in [(1, "1to2"), (2, "2to3"), (3, "3to4")]:
            sub_b = upanel[upanel["board"] == b_val].reset_index(drop=True)
            top_m, bot_m = make_16_factors(sub_b)[f_idx][1], make_16_factors(sub_b)[f_idx][2]
            b_stats = {}
            for p_lbl, p_mask in [
                ("IS_21_23", sub_b["buy_date"] <= "2023-12-31"),
                ("OOS_24_26", sub_b["buy_date"] >= "2024-01-01"),
                ("5Y_21_26", sub_b["buy_date"] >= "2021-11-15"),
            ]:
                st_top = sub_b[p_mask & top_m]
                st_bot = sub_b[p_mask & bot_m]
                if len(st_top) >= 5 and len(st_bot) >= 5:
                    wr_top_cc = float((st_top["ret_cc"] > 0).mean() * 100.0)
                    wr_bot_cc = float((st_bot["ret_cc"] > 0).mean() * 100.0)
                    mn_top_cc = float(st_top["ret_cc"].mean() * 100.0)
                    mn_bot_cc = float(st_bot["ret_cc"].mean() * 100.0)
                    wr_top_t1 = float((st_top["ret_t1c"] > 0).mean() * 100.0)
                    wr_bot_t1 = float((st_bot["ret_t1c"] > 0).mean() * 100.0)
                    mn_top_t1 = float(st_top["ret_t1c"].mean() * 100.0)
                    mn_bot_t1 = float(st_bot["ret_t1c"].mean() * 100.0)
                    zt_top = float(st_top["is_zt_today"].mean() * 100.0)
                    zt_bot = float(st_bot["is_zt_today"].mean() * 100.0)
                    b_stats[p_lbl] = {
                        "n_top": int(len(st_top)), "n_bot": int(len(st_bot)),
                        "d_wr_cc": round(wr_top_cc - wr_bot_cc, 2),
                        "d_ret_cc": round(mn_top_cc - mn_bot_cc, 2),
                        "d_wr_t1c": round(wr_top_t1 - wr_bot_t1, 2),
                        "d_ret_t1c": round(mn_top_t1 - mn_bot_t1, 2),
                        "d_zt_rate": round(zt_top - zt_bot, 2),
                        "top_wr_cc": round(wr_top_cc, 2), "bot_wr_cc": round(wr_bot_cc, 2),
                        "top_ret_cc": round(mn_top_cc, 2), "bot_ret_cc": round(mn_bot_cc, 2),
                    }
                else:
                    b_stats[p_lbl] = {"n_top": int(len(st_top)), "n_bot": int(len(st_bot)), "d_wr_cc": None, "d_ret_cc": None}
            row_out["boards"][b_lbl] = b_stats
        matrix_rows.append(row_out)

    # Monotonic ladder trajectories across 1->2->3 boards (open_pct, prev_to, plate_sz, mcap, px_prev)
    ladder_specs = [
        ("open_pct", [
            ("绿开<-2%", lambda d: d["open_pct"] < -0.02),
            ("低开-2~0%", lambda d: d["open_pct"].between(-0.02, 0.0)),
            ("平小高0~3%", lambda d: d["open_pct"].between(0.0, 0.03)),
            ("中强3~6%", lambda d: d["open_pct"].between(0.03, 0.06)),
            ("抢筹6~9.2%", lambda d: d["open_pct"].between(0.06, 0.092)),
        ]),
        ("prev_to", [
            ("缩量<8.5%", lambda d: d["prev_to"] < 8.5),
            ("温和8.5~18%", lambda d: d["prev_to"].between(8.5, 18.0)),
            ("活跃18~31%", lambda d: d["prev_to"].between(18.0, 31.0)),
            ("爆量>31%", lambda d: d["prev_to"] > 31.0),
        ]),
        ("plate_sz", [
            ("独苗1家", lambda d: d["plate_sz"] == 1),
            ("温热2~5家", lambda d: d["plate_sz"].between(2, 5)),
            ("中热6~11家", lambda d: d["plate_sz"].between(6, 11)),
            ("大热>=12家", lambda d: d["plate_sz"] >= 12),
        ]),
        ("mcap", [
            ("微盘<=35亿", lambda d: d["mcap"] <= 35.0),
            ("小盘35~60亿", lambda d: d["mcap"].between(35.0, 60.0)),
            ("中盘60~120亿", lambda d: d["mcap"].between(60.0, 120.0)),
            ("大盘>120亿", lambda d: d["mcap"] > 120.0),
        ]),
        ("px_prev", [
            ("低价<=12元", lambda d: d["px_prev"] <= 12.0),
            ("中低12~20元", lambda d: d["px_prev"].between(12.0, 20.0)),
            ("中高20~32元", lambda d: d["px_prev"].between(20.0, 32.0)),
            ("高价>32元", lambda d: d["px_prev"] > 32.0),
        ]),
    ]
    ladder_out = {}
    for l_name, bins in ladder_specs:
        ladder_out[l_name] = {}
        for b_val, b_lbl in [(1, "1to2"), (2, "2to3"), (3, "3to4")]:
            sub_b = upanel[(upanel["board"] == b_val) & (upanel["buy_date"] >= "2021-11-15")]
            b_bins = []
            for blbl, bfn in bins:
                sb = sub_b[bfn(sub_b)]
                sb_is = sb[sb["buy_date"] <= "2023-12-31"]
                sb_oos = sb[sb["buy_date"] >= "2024-01-01"]
                b_bins.append({
                    "bin": blbl, "n_5y": int(len(sb)),
                    "wr_5y": round(float((sb["ret_cc"] > 0).mean() * 100.0), 2) if len(sb) else 0.0,
                    "ret_5y": round(float(sb["ret_cc"].mean() * 100.0), 2) if len(sb) else 0.0,
                    "ret_is": round(float(sb_is["ret_cc"].mean() * 100.0), 2) if len(sb_is) else 0.0,
                    "ret_oos": round(float(sb_oos["ret_cc"].mean() * 100.0), 2) if len(sb_oos) else 0.0,
                    "zt_rate": round(float(sb["is_zt_today"].mean() * 100.0), 2) if len(sb) else 0.0,
                })
            ladder_out[l_name][b_lbl] = b_bins

    print(f"  Unified 3-board matrix ready ({len(upanel):,} rows) in {time.time()-t0:.1f}s")
    return upanel, {"matrix_16_factors": matrix_rows, "monotonic_ladders": ladder_out, "pool_counts": upanel["board"].value_counts().sort_index().to_dict()}


def enrich_3to4_with_pit(d34: pd.DataFrame, pit: dict, upanel: pd.DataFrame) -> pd.DataFrame:
    """为 cache_d_and_p['df'] 全量 3,152 行无遗漏注入跨策略 PIT 因子与首5m特征"""
    d = d34.copy().reset_index(drop=True)
    d["c6"] = d["code"].astype(str).str.zfill(6)
    d["buy_date"] = d["buy_date"].astype(str)
    d["sig_date"] = d["sig_date"].astype(str)

    # Pre-index daily bars from pit['df'] for d1_date, d3_low_pct, pos20_d0
    df_day = pit["df"]
    sub_day = df_day[df_day["dt_str"] >= "2021-06-01"]
    bars_idx = {}
    for c6, gc in sub_day.groupby("c6", sort=False):
        bars_idx[c6] = {
            "dts": gc["dt_str"].values,
            "dpos": {dt: i for i, dt in enumerate(gc["dt_str"].values)},
            "l_pct": gc["l_pct"].values.astype(float),
            "pos20_today": gc["pos20_today"].values.astype(float),
            "amount": gc["amount"].values.astype(float),
            "close": gc["close"].values.astype(float),
        }

    env_sig_map = pit["env_sig_map"]
    kpl_stock_meta = pit["kpl_stock_meta"]
    kpl_day_meta = pit["kpl_day_meta"]
    tape_map = pit["tape_map"]
    xq_arr_map = pit["xq_arr_map"]
    ir_map = pit["ir_map"]
    bars_5m_map = pit["bars_5m_map"]

    n = len(d)
    xq_2d = np.zeros(n, dtype=int)
    xq_24h = np.zeros(n, dtype=int)
    ir_20d = np.zeros(n, dtype=int)
    b01_hhi = np.zeros(n, dtype=int)
    b03_hhi = np.zeros(n, dtype=int)
    top1_sh = np.zeros(n, dtype=float)
    p12_prev = np.zeros(n, dtype=float)
    p23_prev = np.zeros(n, dtype=float)
    p34_prev = np.zeros(n, dtype=float)
    roll20_34 = np.zeros(n, dtype=float)
    plate_ge4_cnt = np.zeros(n, dtype=int)
    is_plate_uniq_top = np.zeros(n, dtype=int)
    w1_day1_3 = np.zeros(n, dtype=int)
    w1_fresh20 = np.zeros(n, dtype=int)
    w2_reb = np.zeros(n, dtype=int)
    elo_ice = np.zeros(n, dtype=int)
    d3_low_pct = np.zeros(n, dtype=float)
    d3_seal_amt_ratio = np.full(n, np.nan)
    d3_seal_sec = np.full(n, np.nan)
    pos20_d0 = np.full(n, 0.5)
    m5_amt_ratio_d3 = np.full(n, np.nan)
    m5_turn_pct = np.full(n, np.nan)
    m5_ret_0935 = np.full(n, np.nan)
    m5_open_0940 = np.full(n, np.nan)

    for i, r in enumerate(d.itertuples(index=False)):
        c6, sd, bd = r.c6, r.sig_date, r.buy_date
        b = bars_idx.get(c6)
        d1_dt = sd
        if b is not None and sd in b["dpos"]:
            sp = b["dpos"][sd]
            d3_low_pct[i] = float(b["l_pct"][sp])
            d1_pos = max(0, sp - 2)
            d1_dt = str(b["dts"][d1_pos])
            d0_pos = max(0, sp - 3)
            if pd.notna(b["pos20_today"][d0_pos]):
                pos20_d0[i] = float(b["pos20_today"][d0_pos])

        c_2d, c_24h, vx = _xq_counts(xq_arr_map, c6, d1_dt, sd, bd)
        ir20, vi = _ir_has_20d(ir_map, c6, sd, bd)
        assert vx == 0 and vi == 0, f"PIT time anchor breach on 3to4 {c6} {bd}"
        xq_2d[i], xq_24h[i], ir_20d[i] = c_2d, c_24h, ir20

        kd = kpl_day_meta.get(sd, {})
        b01_hhi[i] = int(kd.get("b01_hhi_low_q25", 0))
        b03_hhi[i] = int(kd.get("b03_hhi_high_q75", 0))
        top1_sh[i] = float(kd.get("raw_top1_share", 0.15))

        env = env_sig_map.get(sd, {})
        p12_prev[i] = float(env.get("mkt_p12_prev_f", 0.20))
        p23_prev[i] = float(env.get("mkt_p23_prev_f", 0.30))
        p34_prev[i] = float(env.get("mkt_p34_prev_f", 0.35))
        roll20_34[i] = float(env.get("roll20_3to4_seal", 0.35))

        km = kpl_stock_meta.get((sd, c6), {})
        ge4_c = int(km.get("plate_cnt_ge4", 0))
        p_max_s = int(km.get("plate_max_stk", 3))
        plate_ge4_cnt[i] = ge4_c
        is_plate_uniq_top[i] = 1 if (ge4_c == 0 and p_max_s <= 3) else 0
        w1_day1_3[i] = int(km.get("w1_day1_3", 0))
        w1_fresh20[i] = int(km.get("w1_fresh20", 0))
        w2_reb[i] = int(km.get("w2_reb", 0))
        elo_ice[i] = int(km.get("elo_ice", 0))

        fst, sa, _ = tape_map.get((sd, c6), (str(getattr(r, "first_seal_time", "99:99:99")), float(getattr(r, "seal_amount", 0.0) or 0.0), 0))
        p_amt = float(getattr(r, "prev_amt", 0.0) or 0.0)
        if sa > 0 and p_amt > 0:
            d3_seal_amt_ratio[i] = sa / p_amt
        if fst and not str(fst).startswith("99"):
            try:
                hh, mm, ss = [int(x) for x in str(fst).split(":")[:3]]
                d3_seal_sec[i] = float((hh - 9) * 3600 + (mm - 30) * 60 + ss) if hh < 12 else float(7200 + (hh - 13) * 3600 + mm * 60 + ss)
            except Exception:
                pass

        arr5 = bars_5m_map.get((c6, bd))
        if arr5 is not None and len(arr5) >= 2:
            # First bar (09:35): [hhmm, o, h, l, c, vol, amt]
            if int(arr5[0, 0]) == 935:
                amt0 = float(arr5[0, 6])
                if p_amt > 0:
                    m5_amt_ratio_d3[i] = amt0 / p_amt
                mc = float(getattr(r, "mcap", 0.0) or 0.0)
                if mc > 0:
                    m5_turn_pct[i] = amt0 / (mc * 1e8) * 100.0
                if arr5[0, 1] > 0:
                    m5_ret_0935[i] = arr5[0, 4] / arr5[0, 1] - 1.0
                m5_open_0940[i] = float(arr5[1, 1])

    d["xq_cnt_2d"] = xq_2d
    d["xq_cnt_24h"] = xq_24h
    d["ir_has_20d"] = ir_20d
    d["b01_hhi_low_q25"] = b01_hhi
    d["b03_hhi_high_q75"] = b03_hhi
    d["raw_top1_share"] = top1_sh
    d["mkt_p12_prev"] = p12_prev
    d["mkt_p23_prev"] = p23_prev
    d["mkt_p34_prev"] = p34_prev
    d["roll20_3to4_seal"] = roll20_34
    d["plate_ge4_cnt_sd"] = plate_ge4_cnt
    d["is_plate_unique_top"] = is_plate_uniq_top
    d["w1_frag"] = ((w1_day1_3 == 1) | (w1_fresh20 == 1)) & (elo_ice == 0)
    d["w1_day1_3"] = w1_day1_3
    d["w2_reb"] = w2_reb
    d["elo_ice"] = elo_ice
    d["d3_low_pct"] = d3_low_pct
    d["d3_seal_amt_ratio"] = d3_seal_amt_ratio
    d["d3_seal_sec"] = d3_seal_sec
    d["pos20_d0"] = pos20_d0
    d["m5_amt_ratio_d3"] = m5_amt_ratio_d3
    d["m5_turn_pct"] = m5_turn_pct
    d["m5_ret_0935"] = m5_ret_0935
    d["m5_open_0940"] = m5_open_0940
    return d


def _pool_slice_stats(df_sub: pd.DataFrame, mask_col: pd.Series) -> dict:
    """无偏检验：按 IS(2022-2023) / OOS(2024-2026) / 2026 / 5Y 对比组内与组外胜率与单笔均益"""
    out = {}
    for p_lbl, p_mask in [
        ("IS_22_23", df_sub["buy_date"] <= "2023-12-31"),
        ("OOS_24_26", df_sub["buy_date"] >= "2024-01-01"),
        ("Y2026", df_sub["buy_date"] >= "2026-01-01"),
        ("5Y", df_sub["buy_date"] >= "2022-01-04"),
    ]:
        s_in = df_sub[p_mask & mask_col]
        s_out = df_sub[p_mask & (~mask_col)]
        n_in, n_out = len(s_in), len(s_out)
        wr_in = float((s_in["net_ret"] > 0).mean() * 100.0) if n_in else 0.0
        wr_out = float((s_out["net_ret"] > 0).mean() * 100.0) if n_out else 0.0
        mn_in = float(s_in["net_ret"].mean() * 100.0) if n_in else 0.0
        mn_out = float(s_out["net_ret"].mean() * 100.0) if n_out else 0.0
        out[p_lbl] = {
            "n_in": int(n_in), "n_out": int(n_out),
            "wr_in": round(wr_in, 2), "wr_out": round(wr_out, 2),
            "d_wr": round(wr_in - wr_out, 2) if (n_in and n_out) else None,
            "ret_in": round(mn_in, 2), "ret_out": round(mn_out, 2),
            "d_ret": round(mn_in - mn_out, 2) if (n_in and n_out) else None,
        }
    return out


def run_task1_3to4_cross_learning(pit: dict, upanel: pd.DataFrame) -> dict:
    print("[5/5] Running Task 1: 3to4 V3.4 Cross-Learning (Bidirectional + IS->OOS)...")
    sys.path.insert(0, f"{SIM}/backtests_astock2")
    from core_3to4_5m_engine import _sim_single_slot_chrono

    with open(CACHE_3TO4_PKL, "rb") as f:
        pkg = pickle.load(f)
    d34_raw = pkg["df"]
    p34 = pkg["p_v32"]
    sc_v34 = pkg["sc_v34"].copy()

    d34 = enrich_3to4_with_pit(d34_raw, pit, upanel)
    d34["has_trade"] = [x is not None for x in p34]
    d34["net_ret"] = [float(x["net_ret"]) if x is not None else np.nan for x in p34]
    d34["buy_hhmm"] = [int(x["buy_hhmm"]) if x is not None else 0 for x in p34]
    d34["exit_date"] = [str(x["exit_date"]) if x is not None else "" for x in p34]
    d34["exit_hhmm"] = [int(x["exit_hhmm"]) if x is not None else 0 for x in p34]
    d34["sc_v34"] = sc_v34

    # Assert exact V3.4 baseline parity (88 trades, WR 64.77%, PLR 2.23, 1S 562.10x, Cap10M 62.06x, Trim5 33.05x, MDD 31.25%)
    def eval_v34_variant(sc_arr: np.ndarray, thr: float = 90.0) -> tuple[dict, pd.DataFrame]:
        idx = np.where(sc_arr >= thr)[0]
        recs = [
            dict(
                p34[i],
                score=float(sc_arr[i]),
                priority_score=float(sc_arr[i]) * 10.0 + float(d34["prio_3to4"].iloc[i]) * 0.1,
            )
            for i in idx if p34[i] is not None
        ]
        if not recs:
            return eval_five_windows_and_splits(pd.DataFrame()), pd.DataFrame()
        taken, _, _, _ = _sim_single_slot_chrono(pd.DataFrame(recs))
        led = pd.DataFrame([x._asdict() for x in taken])
        led["code"] = led["code"].astype(str).str.zfill(6)
        assert (led["exit_date"] > led["buy_date"]).all(), "T+0 detected!"
        return eval_five_windows_and_splits(led, is_start="2022-01-04"), led

    base_90_m, base_90_led = eval_v34_variant(sc_v34, 90.0)
    base_102_m, base_102_led = eval_v34_variant(sc_v34, 102.0)
    b5 = base_90_m["full_5y"]
    assert b5["n"] == 88 and abs(b5["wr"] - 64.77) < 0.05 and abs(b5["nav_1s"] - 562.10) < 0.2, f"V3.4 baseline mismatch: {b5}"
    print(f"  [Parity OK] V3.4 std90: {b5['n']}笔 WR={b5['wr']}% PLR={b5['plr']} 1S={b5['nav_1s']}x Cap10M={b5['cap10m_1m']}x Trim5={b5['trim5']}x MDD={b5['mdd_pct']}% HLZ_t={b5['hlz_t']}")

    # Pool A: Full triggered 3to4 core candidates (core & buyable & open 3~9.2% & triggered)
    core_mask = (
        d34["is_10cm_non_st"] & (~d34["prev_is_yizi"]) & d34["buyable_open"]
        & (~d34["has_tox_notice"]) & (~d34["has_stock_reg"])
        & d34["open_pct"].between(0.030, 0.092) & d34["has_trade"]
    )
    pool_core = d34[core_mask].copy().reset_index(drop=True)
    pool_all_trig = d34[d34["has_trade"]].copy().reset_index(drop=True)

    # Define all candidate slices for Items 1..9 + 10b (including 3-bin U/inverted-U checks)
    def make_pool_tests(dp: pd.DataFrame) -> list:
        d3_weak = (dp["open_board_count"] >= 1) & ((dp["d3_seal_sec"].fillna(0) >= 1800) | (dp["d3_seal_amt_ratio"].fillna(1) < 0.05))
        d3_dead = (dp["d3_seal_amt_ratio"].fillna(0) >= 0.25) | ((dp["open_board_count"] == 0) & (dp["d3_seal_sec"].fillna(99999) <= 300))
        return [
            # 1. Xueqiu
            ("1_雪球_0帖暗牌", dp["xq_cnt_2d"] == 0),
            ("1_雪球_1至3帖温热", dp["xq_cnt_2d"].between(1, 3)),
            ("1_雪球_>=4帖高热", dp["xq_cnt_2d"] >= 4),
            ("1_雪球_>=1帖有讨论", dp["xq_cnt_2d"] >= 1),
            ("1_雪球24h_>=2帖", dp["xq_cnt_24h"] >= 2),
            # 2. IR-QA
            ("2_近20日机构调研(ir_has_20d)", dp["ir_has_20d"] == 1),
            ("2_近8日机构调研(has_ir_8d)", dp["has_ir_8d"] == True),
            # 3. HHI vs Top1 share
            ("3_低HHI离散(b01_q25)", dp["b01_hhi_low_q25"] == 1),
            ("3_高HHI集中(b03_q75)", dp["b03_hhi_high_q75"] == 1),
            ("3_单主线>=30%(raw_top1_share)", dp["raw_top1_share"] >= 0.30),
            # 4. Yesterday promotion rates
            ("4_昨1进2冰点(<15%)", dp["mkt_p12_prev"] < 0.15),
            ("4_昨1进2顺风(>=25%)", dp["mkt_p12_prev"] >= 0.25),
            ("4_昨2进3冰点(<25%)", dp["mkt_p23_prev"] < 0.25),
            ("4_昨2进3顺风(>=40%)", dp["mkt_p23_prev"] >= 0.40),
            ("4_昨3进4冰点(<25%)", dp["mkt_p34_prev"] < 0.25),
            ("4_昨3进4顺风(>=45%)", dp["mkt_p34_prev"] >= 0.45),
            # 5. Plate higher brother suppression vs sole plate leader
            ("5_同板块另有>=4板老大哥压制", dp["plate_ge4_cnt_sd"] >= 1),
            ("5_同板块唯一最高身位(无>=4板)", dp["plate_ge4_cnt_sd"] == 0),
            ("5_高标5-7板下_同板块唯一最高", (dp["mkt_max_board_prev"] >= 5) & (dp["plate_ge4_cnt_sd"] == 0)),
            ("5_高标5-7板下_同板块有老大哥", (dp["mkt_max_board_prev"] >= 5) & (dp["plate_ge4_cnt_sd"] >= 1)),
            # 6. Theme lifecycle
            ("6_一波1至3天脆期(w1_day1_3)", dp["w1_day1_3"] == 1),
            ("6_一波脆弱全集(w1_frag)", dp["w1_frag"] == 1),
            ("6_二波回流(w2_reb)", dp["w2_reb"] == 1),
            ("6_冷门破冰(elo<=95)", dp["elo_ice"] == 1),
            # 7. D3 deep shakeout / seal ratio / pos20_d0 / brk60
            ("7_D3盘中深水洗盘(low<-2%)", dp["d3_low_pct"] < -0.02),
            ("7_D3开板弱封(seal_ratio<5%或>30m)", d3_weak),
            ("7_D3死锁封单(seal_ratio>=25%)", dp["d3_seal_amt_ratio"].fillna(0) >= 0.25),
            ("7_D3秒板死锁", d3_dead),
            ("7_启动前20日低位(pos20_d0<=0.40)", dp["pos20_d0"] <= 0.40),
            ("7_60日平台首突(clean_brk60)", dp["clean_brk60"] == True),
            # 8. Lock >= 50% x real_to 25~65%
            ("8_锁仓>=50%&真换手25~65%", (dp["lock_top10"] >= 50.0) & dp["prev_real_to"].between(25.0, 65.0)),
            ("8_真换手<15%缩量筹码", dp["prev_real_to"] < 15.0),
            ("8_V34双低(lock<45&fmcap<45)", (dp["lock_top10"] < 45.0) & (dp["real_free_mcap"] < 45.0)),
            # 9. V18 purifiers + outsider + cap yizi + roll20
            ("9_事件大筐假题材(event_basket)", dp["is_event_basket"] == True),
            ("9_退潮脉冲(dying_pulse)", dp["is_dying_pulse"] == True),
            ("9_硬科技纯外行(pure_outsider)", dp["is_pure_outsider"] == True),
            ("9_伴生一字&流值>90亿", (dp["plate_yizi_cnt"] >= 1) & (dp["mcap"] > 90.0)),
            ("9_3to4滚动20日封板率>=35%", dp["roll20_3to4_seal"] >= 0.35),
            ("9_1to2滚动20日高开封板>=45%", dp["roll20_ho_zt"] >= 0.45),
            # 10b. First 5m bar diagnostic (empirical quartiles: 0.35 / 0.50 / 0.75)
            ("10b_首5m成交额<D3全天35%", dp["m5_amt_ratio_d3"] < 0.35),
            ("10b_首5m成交额35%~75%", dp["m5_amt_ratio_d3"].between(0.35, 0.75)),
            ("10b_首5m成交额>=D3全天75%", dp["m5_amt_ratio_d3"] >= 0.75),
            ("10b_首5m换手率>=6.0%", dp["m5_turn_pct"] >= 6.0),
            ("10b_首5m阳线收涨", dp["m5_ret_0935"] > 0.0),
        ]

    pool_factor_tests = {}
    for nm, msk in make_pool_tests(pool_core):
        pool_factor_tests[nm] = _pool_slice_stats(pool_core, msk)

    # Bidirectional V3.4 scorecard augmentation/ablation tests
    # On valid V3.4 skeleton (sc_v34 > 0), test BOTH positive (+delta) and negative (-delta) modifications!
    v34_skel = sc_v34 > 0
    v34_tests_spec = [
        # (name, delta_array, category)
        ("1a_雪球>=4帖_扣10分(延续2进3毒药)", np.where(d34["xq_cnt_2d"] >= 4, -10.0, 0.0), "1_Xueqiu"),
        ("1b_雪球>=4帖_加8分(反转为3进4人气)", np.where(d34["xq_cnt_2d"] >= 4, 8.0, 0.0), "1_Xueqiu"),
        ("1c_雪球>=1帖_扣6分_vs_0帖暗牌", np.where(d34["xq_cnt_2d"] >= 1, -6.0, 0.0), "1_Xueqiu"),
        ("1d_雪球>=1帖_加6分(有讨论加分)", np.where(d34["xq_cnt_2d"] >= 1, 6.0, 0.0), "1_Xueqiu"),
        ("1e_雪球>=4帖_扣15分(重罚高热毒药)", np.where(d34["xq_cnt_2d"] >= 4, -15.0, 0.0), "1_Xueqiu"),
        ("1f_雪球>=4帖扣18_1至3帖扣8(完全套用2进3)", np.where(d34["xq_cnt_2d"] >= 4, -18.0, np.where(d34["xq_cnt_2d"] >= 1, -8.0, 0.0)), "1_Xueqiu"),
        ("2a_20日机构调研_扣8分(延续2进3排雷)", np.where(d34["ir_has_20d"] == 1, -8.0, 0.0), "2_IR"),
        ("2b_20日机构调研_加6分(延续1进2正向)", np.where(d34["ir_has_20d"] == 1, 6.0, 0.0), "2_IR"),
        ("3a_HHI低离散+6_单主线>=30%扣8(延续2进3)", np.where(d34["b01_hhi_low_q25"] == 1, 6.0, np.where(d34["raw_top1_share"] >= 0.30, -8.0, 0.0)), "3_HHI"),
        ("3b_单主线>=30%+6_低HHI扣6(反转为大主线)", np.where(d34["raw_top1_share"] >= 0.30, 6.0, np.where(d34["b01_hhi_low_q25"] == 1, -6.0, 0.0)), "3_HHI"),
        ("4a_昨2进3冰点<25%+6_顺风>=40%-6(冰点弱转强)", np.where(d34["mkt_p23_prev"] < 0.25, 6.0, np.where(d34["mkt_p23_prev"] >= 0.40, -6.0, 0.0)), "4_Promo"),
        ("4b_昨2进3顺风>=40%+6_冰点<25%-6(情绪顺风)", np.where(d34["mkt_p23_prev"] >= 0.40, 6.0, np.where(d34["mkt_p23_prev"] < 0.25, -6.0, 0.0)), "4_Promo"),
        ("4c_昨3进4冰点<25%+6", np.where(d34["mkt_p34_prev"] < 0.25, 6.0, 0.0), "4_Promo"),
        ("4d_昨3进4顺风>=40%+6", np.where(d34["mkt_p34_prev"] >= 0.40, 6.0, 0.0), "4_Promo"),
        ("5a_同板块有>=4板老大哥_扣8分(延续2进3)", np.where(d34["plate_ge4_cnt_sd"] >= 1, -8.0, 0.0), "5_Brother"),
        ("5b_同板块有>=4板老大哥_加6分(题材跟风补涨)", np.where(d34["plate_ge4_cnt_sd"] >= 1, 6.0, 0.0), "5_Brother"),
        ("5c_全场>=5板但本板块唯一最高+6_有老大哥-8", np.where((d34["mkt_max_board_prev"] >= 5) & (d34["plate_ge4_cnt_sd"] == 0), 6.0, np.where(d34["plate_ge4_cnt_sd"] >= 1, -8.0, 0.0)), "5_Brother"),
        ("6a_二波回流+5_一波1至3天脆期-10(延续2进3)", np.where(d34["w2_reb"] == 1, 5.0, np.where(d34["w1_frag"] == 1, -10.0, 0.0)), "6_Wave"),
        ("6b_一波1至3天+6_二波-6(3进4主做一波龙头)", np.where(d34["w1_day1_3"] == 1, 6.0, np.where(d34["w2_reb"] == 1, -6.0, 0.0)), "6_Wave"),
        ("6c_冷门Elo<=95破冰+6", np.where(d34["elo_ice"] == 1, 6.0, 0.0), "6_Wave"),
        ("6d_冷门Elo<=95破冰-6", np.where(d34["elo_ice"] == 1, -6.0, 0.0), "6_Wave"),
        ("7a_D3深水洗盘low<-2%+5", np.where(d34["d3_low_pct"] < -0.02, 5.0, 0.0), "7_D3Tape"),
        ("7b_D3深水洗盘low<-2%-5", np.where(d34["d3_low_pct"] < -0.02, -5.0, 0.0), "7_D3Tape"),
        ("7c_D3死锁seal_ratio>=25%-8", np.where(d34["d3_seal_amt_ratio"].fillna(0) >= 0.25, -8.0, 0.0), "7_D3Tape"),
        ("7d_D3死锁seal_ratio>=25%+6", np.where(d34["d3_seal_amt_ratio"].fillna(0) >= 0.25, 6.0, 0.0), "7_D3Tape"),
        ("7e_启动前pos20<=0.40+5", np.where(d34["pos20_d0"] <= 0.40, 5.0, 0.0), "7_D3Tape"),
        ("7f_60日平台突破clean_brk60+5", np.where(d34["clean_brk60"], 5.0, 0.0), "7_D3Tape"),
        ("8a_锁仓>=50%&真换手25~65%+6_真换手<15%-6", np.where(d34["prev_real_to"] < 15.0, -6.0, np.where((d34["lock_top10"] >= 50.0) & d34["prev_real_to"].between(25.0, 65.0), 6.0, 0.0)), "8_LockTurn"),
        ("8b_锁仓>=50%&真换手25~65%替代V34双低扣分", np.where((d34["lock_top10"] < 45.0) & (d34["real_free_mcap"] < 45.0), 10.0, 0.0) + np.where((d34["lock_top10"] >= 50.0) & d34["prev_real_to"].between(25.0, 65.0), 6.0, np.where(d34["prev_real_to"] < 15.0, -6.0, 0.0)), "8_LockTurn"),
        ("9a_事件大筐-12_退潮脉冲-12(V18假题材净化)", np.where(d34["is_event_basket"], -12.0, 0.0) + np.where(d34["is_dying_pulse"], -12.0, 0.0), "9_V18Purify"),
        ("9b_硬科技纯外行-15(V18纯外行排雷)", np.where(d34["is_pure_outsider"], -15.0, 0.0), "9_V18Purify"),
        ("9c_伴生一字&流值>90亿-15(V18大市值伴生一字)", np.where((d34["plate_yizi_cnt"] >= 1) & (d34["mcap"] > 90.0), -15.0, 0.0), "9_V18Purify"),
        ("9d_roll20_3to4封板率<30%扣8分", np.where(d34["roll20_3to4_seal"] < 0.30, -8.0, 0.0), "9_V18Purify"),
        ("9e_roll20_3to4封板率>=35%加5分", np.where(d34["roll20_3to4_seal"] >= 0.35, 5.0, 0.0), "9_V18Purify"),
    ]

    base_keys = set(zip(base_90_led["buy_date"], base_90_led["code"]))
    v34_ablation = {}
    is_winners = []
    for tname, delta, cat in v34_tests_spec:
        sc_new = np.where(v34_skel, sc_v34 + delta, -999.0)
        m90, led90 = eval_v34_variant(sc_new, 90.0)
        m102, _ = eval_v34_variant(sc_new, 102.0)
        new_keys = set(zip(led90["buy_date"], led90["code"])) if not led90.empty else set()
        added = [
            f"{r.buy_date} {r.code} {r.name} ({r.net_ret*100:+.1f}%)"
            for r in led90.itertuples(index=False) if (r.buy_date, r.code) not in base_keys
        ] if not led90.empty else []
        dropped = [
            f"{r.buy_date} {r.code} {r.name} ({r.net_ret*100:+.1f}%)"
            for r in base_90_led.itertuples(index=False) if (r.buy_date, r.code) not in new_keys
        ]
        # Check if IS (2022-2023) improved over baseline
        b_is = base_90_m["IS_22_23"]
        n_is = m90["IS_22_23"]
        b_oos = base_90_m["OOS_24_26"]
        n_oos = m90["OOS_24_26"]
        is_gain = (n_is["nav_1s"] > b_is["nav_1s"] * 1.02) or (n_is["wr"] > b_is["wr"] + 1.0 and n_is["nav_1s"] >= b_is["nav_1s"] * 0.95)
        oos_gain = (n_oos["nav_1s"] > b_oos["nav_1s"] * 1.02) or (n_oos["wr"] > b_oos["wr"] + 1.0 and n_oos["nav_1s"] >= b_oos["nav_1s"] * 0.95)
        if is_gain and (added or dropped):
            is_winners.append((tname, delta, cat, is_gain, oos_gain))
        v34_ablation[tname] = {
            "category": cat, "std90": m90, "strict102": m102,
            "is_gain": bool(is_gain), "oos_gain": bool(oos_gain),
            "added_trades": added[:12], "dropped_trades": dropped[:12],
            "added_cnt": len(added), "dropped_cnt": len(dropped),
        }

    # Build strictly IS-validated Cross-Learned Combo (take best non-overlapping IS winner per category)
    chosen_by_cat = {}
    for tname, delta, cat, is_g, oos_g in is_winners:
        cur_m = v34_ablation[tname]["std90"]["IS_22_23"]["nav_1s"]
        if cat not in chosen_by_cat or cur_m > chosen_by_cat[cat][2]:
            chosen_by_cat[cat] = (tname, delta, cur_m)

    combo_delta = np.zeros(len(d34), dtype=float)
    combo_names = []
    for cat, (tname, delta, _) in sorted(chosen_by_cat.items()):
        combo_delta += delta
        combo_names.append(tname)
    sc_combo = np.where(v34_skel, sc_v34 + combo_delta, -999.0)
    combo_90_m, combo_90_led = eval_v34_variant(sc_combo, 90.0)
    combo_102_m, _ = eval_v34_variant(sc_combo, 102.0)

    # Test clean cross-learned combinations + CSCV PBO (S=8, threshold ladder 88..98)
    clean_combos = {}
    combo_defs = {
        "Combo1_xq4_neg10": np.where(d34["xq_cnt_2d"] >= 4, -10.0, 0.0),
        "Combo2_xq4_neg10_pos20_pos5": np.where(d34["xq_cnt_2d"] >= 4, -10.0, 0.0) + np.where(d34["pos20_d0"] <= 0.40, 5.0, 0.0),
        "Combo3_xq4_neg10_event12": np.where(d34["xq_cnt_2d"] >= 4, -10.0, 0.0) + np.where(d34["is_event_basket"], -12.0, 0.0),
        "Combo4_xq4_neg10_pos20_event12": np.where(d34["xq_cnt_2d"] >= 4, -10.0, 0.0) + np.where(d34["pos20_d0"] <= 0.40, 5.0, 0.0) + np.where(d34["is_event_basket"], -12.0, 0.0),
        "Combo5_xq4_neg15_pos20_pos5": np.where(d34["xq_cnt_2d"] >= 4, -15.0, 0.0) + np.where(d34["pos20_d0"] <= 0.40, 5.0, 0.0),
    }
    t_days_34 = sorted([dt for dt in ALL_CSI_DTS if "2022-01-04" <= dt <= "2026-11-16"])
    day_idx_34 = {dt: ii for ii, dt in enumerate(t_days_34)}
    for cname, cdelta in [("V34_baseline", np.zeros(len(d34), dtype=float))] + list(combo_defs.items()):
        sc_c = np.where(v34_skel, sc_v34 + cdelta, -999.0)
        cm90, cled90 = eval_v34_variant(sc_c, 90.0)
        cm102, _ = eval_v34_variant(sc_c, 102.0)
        # CSCV PBO on threshold ladder [88, 90, 92, 94, 96, 98]
        ths_lad = [88, 90, 92, 94, 96, 98]
        R_lad = np.zeros((len(t_days_34), len(ths_lad)), dtype=float)
        for j, thv in enumerate(ths_lad):
            _, tl = eval_v34_variant(sc_c, float(thv))
            for rr in tl.itertuples(index=False):
                ii = day_idx_34.get(str(rr.exit_date))
                if ii is not None:
                    R_lad[ii, j] += float(rr.net_ret)
        n_g = 8
        gs = len(t_days_34) // n_g
        gidx = [list(range(i * gs, (i + 1) * gs if i < n_g - 1 else len(t_days_34))) for i in range(n_g)]
        import itertools as _it
        omegas = []
        for te in _it.combinations(range(n_g), n_g // 2):
            trg = [k for k in range(n_g) if k not in te]
            tri = [x for k in trg for x in gidx[k]]
            tei = [x for k in te for x in gidx[k]]
            rt, re = R_lad[tri], R_lad[tei]
            st = np.where(rt.std(0, ddof=1) > 1e-12, rt.mean(0) / rt.std(0, ddof=1), 0.0)
            se = np.where(re.std(0, ddof=1) > 1e-12, re.mean(0) / re.std(0, ddof=1), 0.0)
            b = int(np.argmax(st))
            omegas.append(float(np.mean(se > se[b])))
        pbo_pct = round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2)
        clean_combos[cname] = {"std90": cm90, "strict102": cm102, "cscv_pbo_S8_pct": pbo_pct}

    return {
        "d34": d34, "p34": p34, "sc_v34": sc_v34,
        "baseline_std90": base_90_m, "baseline_strict102": base_102_m,
        "pool_core_n": int(len(pool_core)), "pool_all_trig_n": int(len(pool_all_trig)),
        "pool_factor_tests": pool_factor_tests,
        "v34_ablation": v34_ablation,
        "is_calibrated_combo": {
            "selected_components_from_IS_only": combo_names,
            "std90": combo_90_m, "strict102": combo_102_m,
        },
        "clean_cross_combos": clean_combos,
    }


def _sim_1to2_v18_exit_on_5m(bars_c: dict, start_k: int, buy_px: float, adj_b: float, bars_5m_map: dict, c6: str, mode: str):
    """在 1to2 / 2to3 / 3to4 共同的 Day4+ 持仓节点模拟 V18_1030vwap_1430 vs V34_pm1345"""
    dts = bars_c["dts"]
    n = len(dts)
    k = start_k
    imm = False
    while k < n:
        if bool(bars_c["is_yizi_dt"][k]):
            k += 1
            continue
        dc = str(dts[k])
        ok, pck, clk, ztk = float(bars_c["open"][k]), float(bars_c["pre_c"][k]), float(bars_c["close"][k]), float(bars_c["zt_px"][k])
        dtk = round(pck * 0.90, 2)
        if k > start_k and bool(bars_c["is_yizi_dt"][k - 1]):
            return dc, ok, (ok * float(bars_c["adjf"][k])) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, 925
        arr = bars_5m_map.get((c6, dc))
        if mode == "pm1345":
            if arr is not None and len(arr) > 0:
                pk = ok
                for row in arr:
                    hh, bo, bh, bl, bc = int(row[0]), row[1], row[2], row[3], row[4]
                    if bh <= dtk + 0.005:
                        continue
                    if hh >= 1345 and pk >= pck * 1.085 and bl <= pck * 1.050 and bc < ztk - 0.01:
                        spx = float(min(bo, pck * 1.050))
                        return dc, spx, (spx * float(bars_c["adjf"][k])) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, hh
                    if bh > pk:
                        pk = bh
            if bool(bars_c["is_zt"][k]):
                k += 1
                continue
            if (not imm) and (clk > ok) and (clk >= pck):
                imm = True
                k += 1
                continue
            return dc, clk, (clk * float(bars_c["adjf"][k])) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, 1500
        elif mode == "vwap1030_1430":
            if arr is not None and len(arr) >= 12:
                idx_1030 = -1
                cv, ca = 0.0, 0.0
                for bi in range(len(arr)):
                    cv += arr[bi, 5]
                    ca += arr[bi, 6]
                    if int(arr[bi, 0]) == 1030:
                        idx_1030 = bi
                        break
                if idx_1030 >= 0:
                    bc_1030 = arr[idx_1030, 4]
                    vwap = ca / cv if cv > 0 else bc_1030
                    if bc_1030 >= ztk - 0.01:
                        for bi in range(idx_1030 + 1, len(arr) - 1):
                            if int(arr[bi, 0]) >= 1430 and arr[bi, 4] < ztk - 0.01:
                                spx = float(arr[bi + 1, 1])
                                return dc, spx, (spx * float(bars_c["adjf"][k])) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, int(arr[bi + 1, 0])
                        if bool(bars_c["is_zt"][k]):
                            k += 1
                            continue
                        return dc, clk, (clk * float(bars_c["adjf"][k])) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, 1500
                    elif bc_1030 < vwap:
                        spx = float(arr[idx_1030 + 1, 1]) if idx_1030 + 1 < len(arr) else float(bc_1030)
                        hh_ex = int(arr[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr) else 1030
                        return dc, spx, (spx * float(bars_c["adjf"][k])) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, hh_ex
            if bool(bars_c["is_zt"][k]):
                k += 1
                continue
            if (not imm) and (clk >= pck * 1.02) and (k + 1 < n):
                imm = True
                k += 1
                continue
            return dc, clk, (clk * float(bars_c["adjf"][k])) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, 1500
    k = n - 1
    return str(dts[k]), float(bars_c["close"][k]), (float(bars_c["close"][k]) * float(bars_c["adjf"][k])) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, 1500


def run_task1_item10_exec_intersection(pit: dict, t1: dict) -> dict:
    print("[Item 10] Running entry/exit intersection mutual learning (1to2 / 2to3 / 3to4)...")
    sys.path.insert(0, f"{SIM}/backtests_astock2")
    from core_3to4_5m_engine import sim_exit_5m, _sim_single_slot_chrono

    df_day = pit["df"]
    sub = df_day[df_day["dt_str"] >= "2021-09-01"].copy()
    bars_map = {}
    for c6, gc in sub.groupby("c6", sort=False):
        bars_map[c6] = {
            "dts": gc["dt_str"].values,
            "date_to_pos": {d: i for i, d in enumerate(gc["dt_str"].values)},
            "open": gc["open"].values.astype(float),
            "high": gc["high"].values.astype(float),
            "low": gc["low"].values.astype(float),
            "close": gc["close"].values.astype(float),
            "adjf": gc["adjf"].values.astype(float),
            "pre_c": gc["pre_c"].values.astype(float),
            "zt_px": gc["zt_px"].values.astype(float),
            "is_zt": gc["is_zt"].values.astype(bool),
            "is_yizi_dt": gc["is_yizi_dt"].values.astype(bool),
        }
    bars_5m_map = pit["bars_5m_map"]

    # 10(a)-1: 1to2 V18 trades holding past Day3 ZT (entering Day4+) -> 10:30 VWAP vs 3to4 pm1345
    l12 = pd.read_csv(LEDGER_1TO2_CSV)
    l12["code"] = l12["code"].astype(str).str.zfill(6)
    overlap_12_orig, overlap_12_pm1345 = [], []
    all_12_pm1345 = []
    for r in l12.itertuples(index=False):
        c6, bd = r.code, str(r.buy_date)
        bc = bars_map.get(c6)
        orig_row = {"buy_date": bd, "exit_date": str(r.exit_date), "net_ret": float(r.net_ret), "code": c6, "name": r.name}
        if bc is None or bd not in bc["date_to_pos"]:
            all_12_pm1345.append(orig_row)
            continue
        p2 = bc["date_to_pos"][bd]
        p3 = p2 + 1
        # Check if sealed 2nd board on d2 and sealed 3rd board on d3 and exited on/after d4
        if p3 + 1 < len(bc["dts"]) and bool(bc["is_zt"][p2]) and bool(bc["is_zt"][p3]) and str(r.exit_date) >= str(bc["dts"][p3 + 1]):
            overlap_12_orig.append(orig_row)
            ed_n, _, nr_n, _ = _sim_1to2_v18_exit_on_5m(bc, p3 + 1, float(r.buy_price), float(bc["adjf"][p2]), bars_5m_map, c6, "pm1345")
            new_row = {"buy_date": bd, "exit_date": ed_n, "net_ret": float(nr_n), "code": c6, "name": r.name}
            overlap_12_pm1345.append(new_row)
            all_12_pm1345.append(new_row)
        else:
            all_12_pm1345.append(orig_row)

    # 10(a)-2: 2to3 V1.0 trades sealing 3rd board -> pm1345 (V1.0) vs 1to2 vwap1030_1430
    l23 = pd.read_csv(LEDGER_2TO3_CSV)
    l23["code"] = l23["code"].astype(str).str.zfill(6)
    o23_orig, o23_vwap = [], []
    for r in l23.itertuples(index=False):
        c6, bd = r.code, str(r.buy_date)
        bc = bars_map.get(c6)
        orig_row = {"buy_date": bd, "exit_date": str(r.exit_date), "net_ret": float(r.net_ret), "code": c6, "name": r.name}
        if bc is not None and bd in bc["date_to_pos"] and bool(r.sealed_3b):
            p3 = bc["date_to_pos"][bd]
            if p3 + 1 < len(bc["dts"]):
                o23_orig.append(orig_row)
                ed_v, _, nr_v, _ = _sim_1to2_v18_exit_on_5m(bc, p3 + 1, float(r.buy_price), float(bc["adjf"][p3]), bars_5m_map, c6, "vwap1030_1430")
                o23_vwap.append({"buy_date": bd, "exit_date": ed_v, "net_ret": float(nr_v), "code": c6, "name": r.name})

    # 10(a)-3: 3to4 V3.4 (88 trades) AND full 3to4 triggered pool (1069) exit mode comparison
    d34, p34, sc_v34 = t1["d34"], t1["p34"], t1["sc_v34"]
    exit_cmp_3to4 = {}
    for emode in ("pm1345_5m", "vwap1030_5m", "vwap1030_blast_5m", "eod_break_5m", "feishu_5m_strict"):
        recs_v34, recs_pool = [], []
        for i, r in enumerate(d34.itertuples(index=False)):
            tr = p34[i]
            if tr is None:
                continue
            c6, bd = str(r.code).zfill(6), str(r.buy_date)
            bc = bars_map.get(c6)
            if bc is None or bd not in bc["date_to_pos"]:
                continue
            pos = bc["date_to_pos"][bd]
            bpx = float(tr["buy_price"])
            ed, spx, adjs, hb, ehh = sim_exit_5m(c6, bc, pos, bars_5m_map, exit_mode=emode, day5_unsealed_mode="cut_weak", use_yang_imm=True)
            nr = (spx * adjs) / (bpx * float(bc["adjf"][pos])) * (1.0 - FEE_RATE) - 1.0
            rec = {
                "code": c6, "name": r.name, "buy_date": bd, "buy_hhmm": int(tr["buy_hhmm"]),
                "buy_price": bpx, "exit_date": ed, "exit_hhmm": int(ehh), "exit_price": spx,
                "hold_bars": int(hb), "net_ret": float(nr),
                "priority_score": float(sc_v34[i]) * 10.0 + float(r.prio_3to4) * 0.1,
            }
            recs_pool.append(rec)
            if sc_v34[i] >= 90.0:
                recs_v34.append(rec)
        t_v34, _, _, _ = _sim_single_slot_chrono(pd.DataFrame(recs_v34))
        df_v34_e = pd.DataFrame([x._asdict() for x in t_v34])
        df_pool_e = pd.DataFrame(recs_pool)
        exit_cmp_3to4[emode] = {
            "v34_std90": eval_five_windows_and_splits(df_v34_e, is_start="2022-01-04"),
            "pool_is_wr": round(float((df_pool_e[df_pool_e["buy_date"] <= "2023-12-31"]["net_ret"] > 0).mean() * 100.0), 2),
            "pool_is_mean": round(float(df_pool_e[df_pool_e["buy_date"] <= "2023-12-31"]["net_ret"].mean() * 100.0), 2),
            "pool_oos_wr": round(float((df_pool_e[df_pool_e["buy_date"] >= "2024-01-01"]["net_ret"] > 0).mean() * 100.0), 2),
            "pool_oos_mean": round(float(df_pool_e[df_pool_e["buy_date"] >= "2024-01-01"]["net_ret"].mean() * 100.0), 2),
        }

    # 10(b): First 5m bar (09:35) causal execution filter on 3to4 V3.4 (for op < 6.5%, delay to 09:40 open after 09:35 bar closes)
    causal_0935_tests = {}
    for lbl, mode_f in [
        ("baseline_touch65_1130", "base"),
        ("causal_0935_wait0940_all_op_lt65", "wait0940_all"),
        ("causal_0935_amt_ge_35pct_d3", "amt_ge_35"),
        ("causal_0935_amt_ge_50pct_d3", "amt_ge_50"),
        ("causal_0935_amt_lt_75pct_d3", "amt_lt_75"),
        ("causal_0935_amt_35_75pct_d3", "amt_35_75"),
        ("causal_0935_turn_ge_5pct", "turn_ge_5"),
        ("causal_0935_turn_lt_9pct", "turn_lt_9"),
        ("causal_0935_green_candle_ret_gt0", "green_0935"),
    ]:
        recs = []
        for i, r in enumerate(d34.itertuples(index=False)):
            if sc_v34[i] < 90.0 or p34[i] is None:
                continue
            tr = dict(p34[i])
            c6, bd = str(r.code).zfill(6), str(r.buy_date)
            if mode_f != "base" and float(r.open_pct) < 0.065:
                arr5 = bars_5m_map.get((c6, bd))
                bc = bars_map.get(c6)
                if arr5 is None or len(arr5) < 2 or bc is None or bd not in bc["date_to_pos"]:
                    continue
                pos = bc["date_to_pos"][bd]
                pc = float(bc["pre_c"][pos])
                zt = float(bc["zt_px"][pos])
                trig = pc * 1.065
                ar_d3 = float(r.m5_amt_ratio_d3) if pd.notna(r.m5_amt_ratio_d3) else 0.0
                tp_5m = float(r.m5_turn_pct) if pd.notna(r.m5_turn_pct) else 0.0
                ret_0935 = float(r.m5_ret_0935) if pd.notna(r.m5_ret_0935) else 0.0
                if mode_f == "amt_ge_35" and ar_d3 < 0.35:
                    continue
                if mode_f == "amt_ge_50" and ar_d3 < 0.50:
                    continue
                if mode_f == "amt_lt_75" and ar_d3 >= 0.75:
                    continue
                if mode_f == "amt_35_75" and not (0.35 <= ar_d3 <= 0.75):
                    continue
                if mode_f == "turn_ge_5" and tp_5m < 5.0:
                    continue
                if mode_f == "turn_lt_9" and tp_5m >= 9.0:
                    continue
                if mode_f == "green_0935" and ret_0935 <= 0.0:
                    continue
                # Must trigger at or after 09:40 (strictly after 09:35 bar closes)
                fill_px, fill_hh = None, None
                for row in arr5[1:]:
                    hh = int(row[0])
                    if hh > 1130:
                        break
                    if row[3] >= zt - 0.005:
                        continue
                    if row[2] >= trig:
                        cand_px = float(max(row[1], trig))
                        if cand_px < zt - 0.005:
                            fill_px, fill_hh = cand_px, hh
                            break
                if fill_px is None:
                    continue
                ed, spx, adjs, hb, ehh = sim_exit_5m(c6, bc, pos, bars_5m_map, exit_mode="pm1345_5m", day5_unsealed_mode="cut_weak", use_yang_imm=True)
                tr["buy_price"] = fill_px
                tr["buy_hhmm"] = fill_hh
                tr["exit_date"] = ed
                tr["exit_hhmm"] = ehh
                tr["exit_price"] = spx
                tr["net_ret"] = (spx * adjs) / (fill_px * float(bc["adjf"][pos])) * (1.0 - FEE_RATE) - 1.0
            tr["score"] = float(sc_v34[i])
            tr["priority_score"] = float(sc_v34[i]) * 10.0 + float(r.prio_3to4) * 0.1
            recs.append(tr)
        tk, _, _, _ = _sim_single_slot_chrono(pd.DataFrame(recs))
        df_tk = pd.DataFrame([x._asdict() for x in tk])
        causal_0935_tests[lbl] = eval_five_windows_and_splits(df_tk, is_start="2022-01-04")

    return {
        "1to2_overlap_day4_exit_switch": {
            "overlap_n": len(overlap_12_orig),
            "overlap_subset_V18_vwap1030": calc_strategy_metrics(pd.DataFrame(overlap_12_orig)),
            "overlap_subset_3to4_pm1345": calc_strategy_metrics(pd.DataFrame(overlap_12_pm1345)),
            "full_96_V18_orig": eval_five_windows_and_splits(l12, is_start="2021-12-01"),
            "full_96_V18_day4_pm1345": eval_five_windows_and_splits(pd.DataFrame(all_12_pm1345), is_start="2021-12-01"),
        },
        "2to3_overlap_day4_exit_switch": {
            "overlap_n": len(o23_orig),
            "overlap_subset_V10_pm1345": calc_strategy_metrics(pd.DataFrame(o23_orig)),
            "overlap_subset_V18_vwap1030": calc_strategy_metrics(pd.DataFrame(o23_vwap)),
        },
        "3to4_exit_rule_comparison": exit_cmp_3to4,
        "3to4_first5m_0935_causal_exec": causal_0935_tests,
    }


def main():
    t_start = time.time()
    pit = load_all_pit_sources()
    upanel, task2 = build_unified_3board_panel(pit)
    t1 = run_task1_3to4_cross_learning(pit, upanel)
    item10 = run_task1_item10_exec_intersection(pit, t1)

    # Remove bulky DataFrames before JSON dump
    t1_clean = {k: v for k, v in t1.items() if k not in ("d34", "p34", "sc_v34")}
    result = {
        "meta": {
            "script": "expA3_cross_learn_3to4_and_3board_matrix.py",
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_as_of_date": "2026-11-16",
            "xq_db_max_ts": pit["xq_max_ts"],
            "elapsed_sec": round(time.time() - t_start, 2),
        },
        "task1_3to4_cross_learning": t1_clean,
        "task1_item10_exec_intersection": item10,
        "task2_3board_unified_matrix": task2,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[DONE] Saved {OUT_JSON} in {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
