#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_rebacktest_v18_clean.py
================================================================================
Wave 2 · Part B: 一进二 · 五年基础版 V18 干净真账全量重跑引擎
(Base 1to2 V18 Clean Re-Backtest Engine)

数据输入：
  1. 5分钟 K 线：sim-portfolio/data/all_strategies_5m_complete_pit.parquet (253.8万根，100% 覆盖)
  2. 机构调研：sim-portfolio/data/cninfo_ir_qa_5y_pit.db (42,149条，只读模式)
  3. 监管/毒丸/澄清公告：sim-portfolio/data/pit_reg_tox_notices_5y_complete.parquet (44,913条)
  4. 行业去穿越：sim-portfolio/data/csrc_industry_pit_clean.csv (PIT 行业映射)
  5. 日线行情：a_daily.parquet + a_delisted_daily.parquet (含全部退市股)

输出目录：
  sim-portfolio/backtests_astock/clean_rebacktest_20261116/partB_1to2/
    - ledger_base_1to2_v18.csv
    - summary_base_1to2_v18.json
    - ledger_base_1to2_v18_since_2022.csv (兼容对照版)

铁律：
  - 严禁 import yfinance (D12 铁律)
  - 严格保持 V18 原始规则不变 (常规 304.8分 / 高潮 329.8分)
  - 5分钟线 100% 覆盖，0 笔退化
  - 核验 T+0=0, 重叠=0, 一字买入=0
================================================================================
"""

import os
import sys
import re
import json
import time
import bisect
import sqlite3
import datetime
from collections import defaultdict, Counter

import numpy as np
import pandas as pd

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{PROJECT_ROOT}/sim-portfolio"
BACKTEST_CLEAN_DIR = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean"
BACKTEST_ASTOCK_DIR = f"{SIM_DIR}/backtests_astock"
PART_B_DIR = f"{BACKTEST_ASTOCK_DIR}/clean_rebacktest_20261116/partB_1to2"
os.makedirs(PART_B_DIR, exist_ok=True)

if "/tmp" not in sys.path:
    sys.path.insert(0, "/tmp")
if BACKTEST_CLEAN_DIR not in sys.path:
    sys.path.insert(0, BACKTEST_CLEAN_DIR)
if BACKTEST_ASTOCK_DIR not in sys.path:
    sys.path.insert(0, BACKTEST_ASTOCK_DIR)

from clean_wf_1to2_v14_ironclad_master import (
    load_full_prices, FEE_RATE, CSI300_ANNUAL, CSI300_5Y_CUM,
    BAD_NOTICE_PAT, NEG_NOTICE_PAT, HARD_NOTICE_PAT, HARD_NOTICE_ORIG_PAT,
    MA_NOTICE_PAT, EARN_NOTICE_PAT, norm_term
)
from exp1_fake_theme_purifier import (
    build_8y_purified_theme_metadata,
    compute_purifier_auction_scores
)
from master_5y_zero_lookahead_walkforward import evaluate_strategy_master

OUT_CSV = f"{PART_B_DIR}/ledger_base_1to2_v18.csv"
OUT_CSV_2022 = f"{PART_B_DIR}/ledger_base_1to2_v18_since_2022.csv"
OUT_JSON = f"{PART_B_DIR}/summary_base_1to2_v18.json"

PARQUET_5M_PATH = f"{SIM_DIR}/data/all_strategies_5m_complete_pit.parquet"
DB_IR_QA_PATH = f"{SIM_DIR}/data/cninfo_ir_qa_5y_pit.db"
PARQUET_TOX_PATH = f"{SIM_DIR}/data/pit_reg_tox_notices_5y_complete.parquet"
CSV_CSRC_PIT_PATH = f"{SIM_DIR}/data/csrc_industry_pit_clean.csv"
DB_NOTICES_PATH = f"{SIM_DIR}/data/cninfo_notices_5y_pit.db"

# 载入基准指数官方定义
CSI300_BENCH_FILE = f"{BACKTEST_ASTOCK_DIR}/clean_rebacktest_20261116/csi300_canonical_20261116.json"
csi300_benchmarks = {}
if os.path.exists(CSI300_BENCH_FILE):
    with open(CSI300_BENCH_FILE, "r", encoding="utf-8") as f:
        csi300_benchmarks = json.load(f)

print("=" * 80)
print("【Wave 2 · Part B: 一进二 · 五年基础版 V18 干净真账全量重跑】")
print(f"启动时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"输出目录: {PART_B_DIR}")
print("=" * 80)

# ==============================================================================
# 第一步：加载日线与现算 8 年动态题材
# ==============================================================================
t_start = time.time()
print("\n>>> [1/7] 加载主板日线与退市股底座...")
t0 = time.time()
df_daily, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
print(f"    原始日线加载完成: {len(df_daily):,} 行主板日线, 耗时 {time.time()-t0:.2f}s")

dt_to_idx = {d: i for i, d in enumerate(all_dts)}
price_lookup = {
    (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
    for r in df_daily[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
}

print("\n>>> [2/7] 现算 8 年连续滚动动态题材元数据与破冰新词历史...")
t0 = time.time()
stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata(df_daily)
print(f"    8年题材元数据现算完成: {len(stock_theme_5y):,} 条记录, 耗时 {time.time()-t0:.2f}s")

# ==============================================================================
# 第二步：无断档 PIT 公告挂载（整合 cninfo_notices + pit_reg_tox_notices 补齐 2021~2024）
# ==============================================================================
print("\n>>> [3/7] 挂载全量无断档 PIT 监管/毒丸/澄清公告与特征...")
t0 = time.time()

fb = df_daily[df_daily["is_first_board"] & (~df_daily["is_yizi"]) & (df_daily["dt_str"] >= "2021-01-04")].copy()
c6_set = set(fb["c6"].unique())

notice_by_c6 = defaultdict(list)

# 1. 基础公告库 cninfo_notices_5y_pit.db
if os.path.exists(DB_NOTICES_PATH):
    conn_notices = sqlite3.connect(f"file:{DB_NOTICES_PATH}?mode=ro", uri=True)
    for sec_code, pub_dt, avail_dt, title in conn_notices.execute(
        "SELECT sec_code, pub_datetime_cst, trade_date_avail, title FROM notices WHERE pub_datetime_cst >= '2020-12-25'"
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
    print(f"    已加载 cninfo_notices 基础公告: 涉及 {len(notice_by_c6)} 只股票")

# 2. 补齐 2021~2024 全量无断档 pit_reg_tox_notices_5y_complete.parquet
if os.path.exists(PARQUET_TOX_PATH):
    df_tox = pd.read_parquet(PARQUET_TOX_PATH)
    tox_added = 0
    for sec_code, pub_dt, title in df_tox[["sec_code", "pub_datetime_cst", "title"]].itertuples(index=False):
        c6 = str(sec_code)[:6].zfill(6)
        if c6 not in c6_set or not pub_dt:
            continue
        ts = str(title or "")
        is_neg = bool(NEG_NOTICE_PAT.search(ts)) or bool(BAD_NOTICE_PAT.search(ts)) or ("澄清" in ts)
        if is_neg:
            flags = (False, False, False, bool(EARN_NOTICE_PAT.search(ts)), True)
            notice_by_c6[c6].append((str(pub_dt), "", flags))
            tox_added += 1
    print(f"    已补齐 pit_reg_tox_notices: {tox_added:,} 条真实监管/毒丸/澄清公告")

for c6 in notice_by_c6:
    notice_by_c6[c6].sort(key=lambda x: x[0])

# 挂载样本元数据
rows_meta = []
cols_needed = [
    "c6", "dt_str", "d2_dt", "mcap", "amount", "f_dd20_d0", "f_dd60_d0", "f_pos20_d0",
    "f_d0_pct", "f_ret_pre10", "to", "f_d1_vol_ratio", "f_zt_cnt_pre20", "f_break60", "close", "d1_seal_tightness"
]
for r in fb[cols_needed].itertuples(index=False):
    c6, d1, d2 = r.c6, r.dt_str, (r.d2_dt if pd.notna(r.d2_dt) else "2026-11-16")
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
            if pdt > end_cut:
                break
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

# 筛选样本 (覆盖 2021-11-15 至 2026-11-16)
hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-16")].copy().reset_index(drop=True)
hist_fb = compute_purifier_auction_scores(hist_fb)

hist_fb["gap_days"] = (pd.to_datetime(hist_fb["d2_dt"]) - pd.to_datetime(hist_fb["dt_str"])).dt.days
hist_fb["c6"] = hist_fb["ticker"].astype(str).str[:6]
print(f"    特征现算与特征注入完成: {len(hist_fb):,} 个首板样本, 耗时 {time.time()-t0:.2f}s")

# ==============================================================================
# 第三步：挂载去穿越 PIT 行业映射、微观盘口与真实机构调研
# ==============================================================================
print("\n>>> [4/7] 挂载去穿越 PIT 行业表、微观盘口与 5 年真实机构调研...")
t0 = time.time()

# 1. 严格 PIT 行业映射 csrc_industry_pit_clean.csv (消除静态快照穿越)
df_csrc_pit = pd.read_csv(CSV_CSRC_PIT_PATH)
df_csrc_pit["c6"] = df_csrc_pit["sec_code"].astype(str).str.zfill(6)
csrc_pit_lookup = defaultdict(list)
for r in df_csrc_pit[["c6", "start_date", "end_date", "industry"]].itertuples(index=False):
    csrc_pit_lookup[r.c6].append((str(r.start_date), str(r.end_date), str(r.industry) if pd.notna(r.industry) else ""))

def get_pit_ind(c6_val, dt_val):
    intervals = csrc_pit_lookup.get(c6_val)
    if not intervals:
        return ""
    for s, e, ind in intervals:
        if s <= dt_val <= e:
            return ind
    if dt_val < intervals[0][0]:
        return intervals[0][2]
    return intervals[-1][2]

csrc_ind_pit = [get_pit_ind(c6, d2) for c6, d2 in zip(hist_fb["c6"], hist_fb["d2_dt"])]
hist_fb["csrc_ind"] = csrc_ind_pit

# 2. 严格只读挂载首板微观盘口
conn_tape = sqlite3.connect(f"file:{SIM_DIR}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
tape_df = pd.read_sql_query("SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape", conn_tape)
conn_tape.close()
hist_fb = hist_fb.merge(tape_df.drop_duplicates(["trade_date", "sec_code"]), left_on=["dt_str", "c6"], right_on=["trade_date", "sec_code"], how="left")

# 3. 严格 PIT 机构调研 (< D2 09:25:00 CST 且 8 日内)
conn_ir = sqlite3.connect(f"file:{DB_IR_QA_PATH}?mode=ro", uri=True)
ir_df = pd.read_sql_query("SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE pub_datetime_cst IS NOT NULL", conn_ir)
conn_ir.close()
ir_df["c6"] = ir_df["sec_code"].astype(str).str.zfill(6)
ir_grp = ir_df.groupby("c6")["pub_datetime_cst"].apply(lambda s: np.sort(s.unique())).to_dict()

ir_7d_pit = np.zeros(len(hist_fb), dtype=bool)
for idx, (c6, d2) in enumerate(zip(hist_fb["c6"], hist_fb["d2_dt"])):
    arr = ir_grp.get(c6)
    if arr is not None:
        pos = np.searchsorted(arr, f"{d2} 09:25:00", side="left")
        if pos > 0:
            last_dt = arr[pos - 1][:10]
            if 0 <= (pd.Timestamp(d2) - pd.Timestamp(last_dt)).days <= 8:
                ir_7d_pit[idx] = True
hist_fb["has_ir_pit"] = ir_7d_pit

# 4. 动态题材日排名 (rk_theme)
valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median"))
pg_m = pg[pg["p_sz_max"] >= 2].copy()
pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
hist_fb = hist_fb.merge(pg_m[["d2_dt", "plate", "rk_theme"]], on=["d2_dt", "plate"], how="left")

print(f"    特征数据注入完成，耗时 {time.time()-t0:.2f}s")

# ==============================================================================
# 第四步：加载 253.8 万根 5 分钟 K 线底座并建立毫秒级内存索引
# ==============================================================================
print("\n>>> [5/7] 加载完整 5 分钟 K 线底座 (all_strategies_5m_complete_pit.parquet)...")
t0 = time.time()
df_5m = pd.read_parquet(PARQUET_5M_PATH)
df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_map = {}
for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False):
    bars_5m_map[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()
print(f"    5分钟 K 线索引完成: 共 {len(bars_5m_map):,} 个 (股票, 交易日) 分时轨迹, 耗时 {time.time()-t0:.2f}s")

# ==============================================================================
# 第五步：构建 V18 信号特征、前视传感器与纯打分定式
# ==============================================================================
print("\n>>> [6/7] 构建 V18 信号特征与断层主线/混战日判定...")
t0 = time.time()

seal_time = hist_fb["first_seal_time"].fillna("99:99:99")
open_cnt = hist_fb["open_board_count"].fillna(0)
dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
clean_brk60 = hist_fb["clean_brk60"].values == 1

is_granularity = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))

common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])

pass_l1 = ~hist_fb["is_event_basket"]
pass_l2 = ~hist_fb["is_dying_pulse"]
pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
wk_mask = hist_fb["gap_days"] >= 3
thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)

f3_bonus = np.where(hist_fb["notice_bad"], -35.0, 0.0)

hist_fb["score_wk"] = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

m_t2_base = common_ok & (hist_fb["p_sz"] == 1) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]) & hist_fb["d2_o_pct"].between(0.035, 0.078) & (hist_fb["buyable_mkt_open_rk"] <= 3) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))

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

# 名字调性纯外行扣 20 分 (基于 PIT CSRC 行业)
csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hist_fb["csrc_ind"]]
CSRC_PURE_OUTSIDER = {
    "A01","A02","A03","A04","A05",
    "D44","D45","D46",
    "E47","E48","E49","E50",
    "F51","F52",
    "G53","G54","G55","G56","G58","G59",
    "H61","H62",
    "K70",
    "L72","N77","N78",
    "C13","C14","C15","C17","C18","C19","C20","C21","C22"
}
is_hard_tech = hist_fb["plate"].astype(str).str.contains(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)", regex=True).values
has_ma_hard = (hist_fb["notice_hard"] | hist_fb["is_ma"]).values
is_pure_outsider = np.array([ht and (cs in CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)], dtype=bool)
name_sub20 = np.where(is_pure_outsider, -20.0, 0.0)

flc = hist_fb["front_lock_cnt"].values
tbrk = hist_fb["true_buy_rk"].values
myz = hist_fb["mkt_yizi_cnt"].values
is_super_wave = (hist_fb["rk_theme"] == 1) & (hist_fb["p_sz"] >= 8) & (tbrk == 1)

def get_yizi_gran_v17():
    return np.select(
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

y_v17 = get_yizi_gran_v17()

# 前视滚动20日高开封板率传感器 (roll20_ho_zt)
daily_records = []
for d, grp in hist_fb.groupby("d2_dt"):
    buyable = grp[grp["is_buyable_open"] & (~grp["nuclear_halt"]) & (~grp["promo_freeze"])]
    ho = buyable[buyable["d2_o_pct"] >= 0.055]
    n_ho = len(ho)
    rate_ho_zt = (ho["d2_is_zt"].sum() / n_ho) if n_ho > 0 else np.nan
    daily_records.append({"date": d, "rate_ho_zt": rate_ho_zt})
df_daily_s = pd.DataFrame(daily_records).sort_values("date").reset_index(drop=True)
df_daily_s["roll20_ho_zt"] = df_daily_s["rate_ho_zt"].shift(1).rolling(20, min_periods=5).mean().fillna(0.45)
sensors_map = df_daily_s.set_index("date").to_dict(orient="index")

pen_thr_vec = np.zeros(len(hist_fb))
pen_val_vec = np.zeros(len(hist_fb))
for d, s in sensors_map.items():
    ho_rate = s.get("roll20_ho_zt", 0.45)
    if ho_rate < 0.45:
        p_val, p_thr = 25.0, 0.035
    else:
        p_val, p_thr = 15.0, 0.031
    idx_d = (hist_fb["d2_dt"] == d).values
    pen_thr_vec[idx_d] = p_thr
    pen_val_vec[idx_d] = p_val
q_pen = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < pen_thr_vec), pen_val_vec, 0.0)

d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)

daily_t1 = pg_m[pg_m["rk_theme"] == 1].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
daily_t2 = pg_m[pg_m["rk_theme"] == 2].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
daily_t3 = pg_m[pg_m["rk_theme"] == 3].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")

# V18 四大纯打分升级
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

m_t1 = common_ok & open_in_win & (sp_v >= 45.0) & (sc_v >= thr_vec)
mm = ((m_t1 & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac) | (m_t2_base & pass_l2)) & p_tight

mmon = (
    common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090)
    & (sp_v >= 38.0) & (sc_v >= thr_vec)
    & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac & p_tight
)
tot_cand = (mm | (mmon & (~mm))).copy()

dom_no_dragon = set()
melee_days = set()

for d in sorted(daily_t1.index):
    t1_row = daily_t1.loc[d]
    t2_row = daily_t2.loc[d] if d in daily_t2.index else None
    t3_row = daily_t3.loc[d] if d in daily_t3.index else None

    t1_med = float(t1_row["p_theme_med"])
    t2_med = float(t2_row["p_theme_med"]) if t2_row is not None else 0.0
    t1_sz = int(t1_row["p_sz_max"])
    t2_sz = int(t2_row["p_sz_max"]) if t2_row is not None else 1

    diff_1_2 = t1_med - t2_med
    ratio_sz = t1_sz / max(1, t2_sz)
    is_dominant = (diff_1_2 >= 20.0) or ((t1_sz >= 6) and (ratio_sz >= 2.0))

    if is_dominant:
        t1_plate = t1_row["plate"]
        sub_d = hist_fb[hist_fb["d2_dt"] == d]
        sub_d_passed = sub_d[tot_cand[sub_d.index]]
        t1_has_passed = (sub_d_passed["plate"] == t1_plate).any() if len(sub_d_passed) > 0 else False
        if not t1_has_passed:
            dom_no_dragon.add(d)

    if t1_row is not None and t2_row is not None and t3_row is not None:
        t3_med = float(t3_row["p_theme_med"])
        range_top3 = t1_med - t3_med
        sz_max = max(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
        sz_min = min(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
        if range_top3 <= 15.0 and sz_max <= 5 and sz_min >= 2:
            melee_days.add(d)

sv = np.where(mm, sc_v + 1000.0, sc_v)
sub_tot = hist_fb[tot_cand].copy()
sub_tot["_sv_tmp"] = sv[tot_cand]
bad_dts = set()
for d, grp in sub_tot.groupby("d2_dt"):
    if (grp["rk_theme"] == 1).any():
        top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
        if pd.notna(top_rk) and top_rk >= 4:
            bad_dts.add(d)
tot = tot_cand & (~hist_fb["d2_dt"].isin(bad_dts)).values

is_blocked_alpha = np.zeros(len(hist_fb), dtype=bool)
for idx, (d, rk) in enumerate(zip(hist_fb["d2_dt"], hist_fb["rk_theme"])):
    if d in dom_no_dragon and rk == 3:
        is_blocked_alpha[idx] = True
tot = tot & (~is_blocked_alpha)

is_blocked_beta = np.zeros(len(hist_fb), dtype=bool)
for idx, (d, mrk, nh, hm) in enumerate(zip(
    hist_fb["d2_dt"], hist_fb["buyable_mkt_open_rk"], hist_fb["notice_hard"], hist_fb["is_ma"]
)):
    if d in melee_days:
        is_breakout = (mrk <= 2) or bool(nh) or bool(hm)
        if not is_breakout:
            is_blocked_beta[idx] = True
tot = tot & (~is_blocked_beta)

hist_fb["_sv_eval"] = sv
print(f"    V18 候选与纯打分完成，耗时 {time.time()-t0:.2f}s")

# ==============================================================================
# 第六步：严格 5 分钟 K 线交易模拟引擎（含覆盖率核验与精确撮合）
# ==============================================================================
def make_clean_trade_engine(fee=FEE_RATE):
    def sim_trade(row):
        c6, d2 = row["c6"], row["d2_dt"]
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 < 0 or idx2 >= len(all_dts) - 1:
            return None
        d2_bar = price_lookup.get((c6, d2))
        if not d2_bar:
            return None
        o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar
        if o2 >= zt2 - 0.005 or o2 <= 0:
            return None

        is_monday = row.get("gap_days", 1) >= 3
        cand_score = row.get("score_active", row.get("score_0", 0.0))
        cand_lead = row.get("buy_open_lead", 0.0)
        do_direct = is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)
        trig_p = float(row["trig_p"])
        buy_px = round(float(o2), 2) if do_direct else round(trig_p, 2)
        buy_hhmm = 925 if do_direct else 935

        if not do_direct:
            if h2 < trig_p or trig_p >= zt2 - 0.005:
                return None
            # 11:30 上午收盘前未触及点火价则下午撤单不买
            arr2 = bars_5m_map.get((c6, d2))
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
        d3_bar = price_lookup.get((c6, d3))
        if not d3_bar:
            net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
            return {
                "net_ret": net, "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2),
                "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c,
                "buy_hhmm": buy_hhmm, "exit_hhmm": 925, "score": round(cand_score, 1), "tag": "no_d3_bar"
            }
        o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar

        # 分支 1：买入日未封死二板 (N型反包反抽判定)
        if not is_zt2:
            d2_closed_up = (c2 >= float(row["close"]))
            if d2_closed_up and (o3 >= round(c2 * 1.005, 2)) and not is_yz_dt3:
                if is_zt3:
                    curr = idx3 + 1
                    boards_held = 3
                    used_immunity = False
                    prev_c = round(float(c3), 2)
                    while curr < len(all_dts) and (curr - idx2 <= 12):
                        dc = all_dts[curr]
                        b = price_lookup.get((c6, dc))
                        if not b: break
                        oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b
                        if iyzc:
                            prev_c = round(float(cc), 2); curr += 1; continue

                        arr = bars_5m_map.get((c6, dc))
                        if arr is not None and len(arr) >= 12:
                            idx_1030 = -1
                            cum_v, cum_a = 0.0, 0.0
                            for bi in range(len(arr)):
                                cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                                if arr[bi, 0] == 1030:
                                    idx_1030 = bi; break
                            if idx_1030 >= 0:
                                bc_1030 = arr[idx_1030, 4]
                                vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                                if bc_1030 >= ztc - 0.01:
                                    for bi in range(idx_1030 + 1, len(arr) - 1):
                                        if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                            px = round(float(arr[bi + 1, 1]), 2)
                                            exit_hh = int(arr[bi + 1, 0])
                                            return {
                                                "net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc,
                                                "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"],
                                                "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": exit_hh,
                                                "score": round(cand_score, 1), "tag": "5m_1430_rush"
                                            }
                                    if iztc:
                                        prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                    else:
                                        px = round(float(cc), 2)
                                        return {
                                            "net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc,
                                            "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"],
                                            "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500,
                                            "score": round(cand_score, 1), "tag": "eod_break"
                                        }
                                elif bc_1030 < vwap_1030:
                                    px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                                    exit_hh = int(arr[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr) else 1030
                                    return {
                                        "net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc,
                                        "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"],
                                        "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": exit_hh,
                                        "score": round(cand_score, 1), "tag": "5m_1030_weak_cut"
                                    }
                                else:
                                    if iztc:
                                        prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                    if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                                        used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                                    px = round(float(cc), 2)
                                    return {
                                        "net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc,
                                        "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"],
                                        "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500,
                                        "score": round(cand_score, 1), "tag": "eod_close"
                                    }

                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                        px = round(float(cc), 2)
                        return {
                            "net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc,
                            "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"],
                            "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500,
                            "score": round(cand_score, 1), "tag": "eod_close"
                        }
                    return {
                        "net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)],
                        "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"],
                        "buy_price": buy_px, "exit_price": prev_c, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500,
                        "score": round(cand_score, 1), "tag": "max_hold_exit"
                    }
                else:
                    px = round(float(c3), 2)
                    return {
                        "net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": d3,
                        "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"],
                        "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500,
                        "score": round(cand_score, 1), "tag": "nshape_d3_close"
                    }

            curr = idx3
            while curr < len(all_dts):
                b = price_lookup.get((c6, all_dts[curr]))
                if not b or not b[7]:
                    px = round(float(b[0]), 2) if b else prev_c
                    return {
                        "net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[curr],
                        "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"],
                        "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 925,
                        "score": round(cand_score, 1), "tag": "fail_open_cut"
                    }
                curr += 1
            return None

        # 分支 2：买入日封死二板 (主升连板状态机)
        curr = idx3
        boards_held = 2
        used_immunity = False
        while curr < len(all_dts) and (curr - idx2 <= 12):
            dc = all_dts[curr]
            b = price_lookup.get((c6, dc))
            if not b: break
            oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b
            if iyzc:
                prev_c = round(float(cc), 2); curr += 1; continue

            arr = bars_5m_map.get((c6, dc))
            if arr is not None and len(arr) >= 12:
                idx_1030 = -1
                cum_v, cum_a = 0.0, 0.0
                for bi in range(len(arr)):
                    cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                    if arr[bi, 0] == 1030:
                        idx_1030 = bi; break
                if idx_1030 >= 0:
                    bc_1030 = arr[idx_1030, 4]
                    vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                    if bc_1030 >= ztc - 0.01:
                        for bi in range(idx_1030 + 1, len(arr) - 1):
                            if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                px = round(float(arr[bi + 1, 1]), 2)
                                exit_hh = int(arr[bi + 1, 0])
                                return {
                                    "net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc,
                                    "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"],
                                    "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": exit_hh,
                                    "score": round(cand_score, 1), "tag": "5m_1430_rush"
                                }
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        else:
                            px = round(float(cc), 2)
                            return {
                                "net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc,
                                "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"],
                                "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500,
                                "score": round(cand_score, 1), "tag": "eod_break"
                            }
                    elif bc_1030 < vwap_1030:
                        px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                        exit_hh = int(arr[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr) else 1030
                        return {
                            "net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc,
                            "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"],
                            "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": exit_hh,
                            "score": round(cand_score, 1), "tag": "5m_1030_weak_cut"
                        }
                    else:
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                        px = round(float(cc), 2)
                        return {
                            "net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc,
                            "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"],
                            "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500,
                            "score": round(cand_score, 1), "tag": "eod_close"
                        }

            if iztc:
                prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
            if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
            px = round(float(cc), 2)
            return {
                "net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc,
                "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"],
                "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500,
                "score": round(cand_score, 1), "tag": "eod_close"
            }

        return {
            "net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)],
            "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"],
            "buy_price": buy_px, "exit_price": prev_c, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500,
            "score": round(cand_score, 1), "tag": "max_hold_exit"
        }

    return sim_trade

fn_clean = make_clean_trade_engine(fee=FEE_RATE)

# ==============================================================================
# 第七步：执行全量回测与评测导出
# ==============================================================================
print("\n>>> [7/7] 执行 5 年全周期 Walkforward 与指标核验...")

# 1. 全五年标准回测：2021-11-15 至 2026-11-16
r_5y = evaluate_strategy_master(hist_fb, "_sv_eval", tot, fn_clean, start_dt="2021-11-15", end_dt="2026-11-16", desc="Base_1to2_V18_Clean_5Y")

# 2. 兼容 2022-01-04 起算口径（与旧 95 笔逐笔对照）
r_2022 = evaluate_strategy_master(hist_fb, "_sv_eval", tot, fn_clean, start_dt="2022-01-04", end_dt="2026-11-16", desc="Base_1to2_V18_Clean_since_2022")

# 导出全量 5 年台账
df_ledger_5y = pd.DataFrame(r_5y["trades_list"])
df_ledger_5y["code"] = df_ledger_5y["code"].astype(str).str.zfill(6)
cols_order = ["code", "name", "buy_date", "buy_hhmm", "buy_price", "exit_date", "exit_hhmm", "exit_price", "net_ret", "score", "tag", "sealed_2b", "exit_at_open"]
cols_present = [c for c in cols_order if c in df_ledger_5y.columns]
df_ledger_5y = df_ledger_5y[cols_present]
df_ledger_5y.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

# 导出 2022 对照版台账
df_ledger_2022 = pd.DataFrame(r_2022["trades_list"])
df_ledger_2022["code"] = df_ledger_2022["code"].astype(str).str.zfill(6)
cols_present_22 = [c for c in cols_order if c in df_ledger_2022.columns]
df_ledger_2022 = df_ledger_2022[cols_present_22]
df_ledger_2022.to_csv(OUT_CSV_2022, index=False, encoding="utf-8-sig")

print(f"✅ 全量 5 年真账已落盘: {OUT_CSV} ({len(df_ledger_5y)} 笔交易)")
print(f"✅ 2022 对照账本已落盘: {OUT_CSV_2022} ({len(df_ledger_2022)} 笔交易)")

# ==============================================================================
# 第八步：法医级四大防伪核验 (T+0=0, 重叠=0, 一字买入=0, 5m覆盖率=100%)
# ==============================================================================
print("\n" + "=" * 80)
print("【法医级四大防伪严校核验】")
print("=" * 80)

# 1. T+0 违规核验
t0_violations = sum(1 for _, r in df_ledger_5y.iterrows() if r["exit_date"] <= r["buy_date"])
print(f"  * [核验 1] T+0 违规笔数: {t0_violations} 笔 {'(PASSED)' if t0_violations == 0 else '(FAILED)'}")

# 2. 单仓重叠核验
overlap_violations = 0
for i in range(len(df_ledger_5y) - 1):
    curr_t = df_ledger_5y.iloc[i]
    next_t = df_ledger_5y.iloc[i + 1]
    if next_t["buy_date"] < curr_t["exit_date"]:
        overlap_violations += 1
    elif next_t["buy_date"] == curr_t["exit_date"] and not curr_t.get("exit_at_open", False):
        overlap_violations += 1
print(f"  * [核验 2] 单仓槽位重叠笔数: {overlap_violations} 笔 {'(PASSED)' if overlap_violations == 0 else '(FAILED)'}")

# 3. 一字板买入核验
yizi_buy_violations = 0
for _, r in df_ledger_5y.iterrows():
    b_bar = price_lookup.get((str(r["code"]).zfill(6), r["buy_date"]))
    if b_bar:
        o, h, l, c, zt, dt_p, izt, iyz = b_bar
        if o >= zt - 0.005:
            yizi_buy_violations += 1
print(f"  * [核验 3] 一字板买入违规: {yizi_buy_violations} 笔 {'(PASSED)' if yizi_buy_violations == 0 else '(FAILED)'}")

# 4. 5分钟 K 线覆盖率核验 (精准基于成交台账所有交易日)
total_trade_days = 0
covered_trade_days = 0
missing_trade_days = []

for _, r in df_ledger_5y.iterrows():
    c6 = str(r["code"]).zfill(6)
    b_dt = str(r["buy_date"])
    e_dt = str(r["exit_date"])
    b_idx = dt_to_idx.get(b_dt)
    e_idx = dt_to_idx.get(e_dt)
    if b_idx is not None and e_idx is not None:
        for idx in range(b_idx, e_idx + 1):
            dt = all_dts[idx]
            total_trade_days += 1
            if (c6, dt) in bars_5m_map:
                covered_trade_days += 1
            else:
                missing_trade_days.append((c6, r["name"], dt))

cov_pct = (covered_trade_days / total_trade_days * 100) if total_trade_days > 0 else 100.0
print(f"  * [核验 4] 成交笔数 5 分钟 K 线覆盖率: {cov_pct:.2f}% (检查点 {covered_trade_days}/{total_trade_days}, 缺失 {len(missing_trade_days)} 天) {'(PASSED 100.0%)' if len(missing_trade_days) == 0 else '(FLAGGED)'}")

# ==============================================================================
# 第九步：五期 D15 指标计算与对比分析
# ==============================================================================
trades_all = r_5y["trades_list"]

def calc_period_metrics(tl_sub, name, bench_ret_pct=0.0):
    n = len(tl_sub)
    if n == 0:
        return {"period": name, "trades": 0, "win_rate": 0.0, "payoff": 0.0, "nav_mult": 1.0, "mdd_pct": 0.0, "excess_vs_csi300_pct": 0.0}
    rets = [t["net_ret"] for t in tl_sub]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    wr = len(wins) / n * 100
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 1e-4
    payoff = avg_win / avg_loss if avg_loss > 0 else 0.0

    nav, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        nav *= (1.0 + r)
        peak = max(peak, nav)
        mdd = max(mdd, (peak - nav) / peak)
    
    excess = round((nav - 1.0) * 100 - bench_ret_pct, 1)
    return {
        "period": name,
        "trades": n,
        "win_rate": round(wr, 1),
        "payoff": round(payoff, 2),
        "nav_mult": round(nav, 2),
        "mdd_pct": round(mdd * 100, 1),
        "csi300_bench_pct": round(bench_ret_pct, 1),
        "excess_vs_csi300_pct": excess
    }

p_since_oct26 = calc_period_metrics([t for t in trades_all if t["buy_date"] >= "2026-10-01"], "2026年10月以来", bench_ret_pct=csi300_benchmarks.get("2026年10月以来", [-8.67])[0])
p_since_jul26 = calc_period_metrics([t for t in trades_all if t["buy_date"] >= "2026-07-01"], "2026年7月以来", bench_ret_pct=csi300_benchmarks.get("2026年7月以来", [-20.08])[0])
p_year_2026   = calc_period_metrics([t for t in trades_all if t["buy_date"] >= "2026-01-01"], "2026全年", bench_ret_pct=csi300_benchmarks.get("2026全年", [-14.04])[0])
p_3y          = calc_period_metrics([t for t in trades_all if t["buy_date"] >= "2023-11-15"], "近三年(2023-11-15~)", bench_ret_pct=csi300_benchmarks.get("近三年(2023-11-16起)", [10.33])[0])
p_5y          = calc_period_metrics(trades_all, "全五年(2021-11-15~)", bench_ret_pct=csi300_benchmarks.get("全五年(2021-11-16起)", [-18.49])[0])

# 与旧 95 笔逐笔比对 (2022-01-04 起算口径)
OLD_CSV = f"{BACKTEST_ASTOCK_DIR}/full_day_by_day_v18_ledger.csv"
old_trades_set = set()
df_old_ledger = None
if os.path.exists(OLD_CSV):
    df_old_ledger = pd.read_csv(OLD_CSV)
    for _, r in df_old_ledger.iterrows():
        old_trades_set.add((str(r["buy_date"]), str(r["c6"]).zfill(6)))

new_2022_set = {(str(r["buy_date"]), str(r["code"]).zfill(6)) for r in r_2022["trades_list"]}
dropped_vs_old = old_trades_set - new_2022_set
added_vs_old = new_2022_set - old_trades_set

print("\n" + "=" * 80)
print("【五期 D15 绩效总表】")
print("=" * 80)
for p in [p_since_oct26, p_since_jul26, p_year_2026, p_3y, p_5y]:
    print(f"  * {p['period']:<20}: {p['trades']:>3} 笔 | 胜率 {p['win_rate']:>5.1f}% | 盈亏比 {p['payoff']:>4.2f} | 净值 {p['nav_mult']:>8.2f}x | 回撤 {p['mdd_pct']:>5.1f}% | 超额 {p['excess_vs_csi300_pct']:>8.1f}%")

print(f"\n【旧 95 笔逐笔对照分析】:")
print(f"  * 旧版 2022 起算交易笔数: {len(old_trades_set)} 笔")
print(f"  * 新版 2022 起算交易笔数: {len(new_2022_set)} 笔")
print(f"  * 退出交易（由补齐公告毒丸/行业去穿越消除）: {len(dropped_vs_old)} 笔: {dropped_vs_old}")
print(f"  * 新增交易（2026-11-10 后延伸交易）: {len(added_vs_old)} 笔: {added_vs_old}")

# 去极值
rets_5y = [t["net_ret"] for t in trades_all]
sorted_rets = sorted(rets_5y, reverse=True)
trimmed_top5 = float(np.prod([1.0 + r for r in sorted_rets[5:]])) if len(sorted_rets) >= 5 else 1.0

# 连胜与连亏
max_loss_streak, curr_loss_streak = 0, 0
max_win_streak, curr_win_streak = 0, 0
for ret in rets_5y:
    if ret < 0:
        curr_loss_streak += 1
        curr_win_streak = 0
        max_loss_streak = max(max_loss_streak, curr_loss_streak)
    else:
        curr_win_streak += 1
        curr_loss_streak = 0
        max_win_streak = max(max_win_streak, curr_win_streak)

# 逐年拆解 (涵盖 2021 至 2026 全年)
annual_stats_full = {}
for yr in sorted(list({t["buy_date"][:4] for t in trades_all})):
    t_yr = [t for t in trades_all if t["buy_date"][:4] == yr]
    c_nav = 1.0
    for t in t_yr:
        c_nav *= (1.0 + t["net_ret"])
    w_yr = [t["net_ret"] for t in t_yr if t["net_ret"] > 0]
    wr = len(w_yr) / len(t_yr) if t_yr else 0.0
    bench = CSI300_ANNUAL.get(yr, 0.0)
    annual_stats_full[yr] = {
        "trades": len(t_yr),
        "win_rate": round(wr * 100, 1),
        "nav_mult": round(c_nav, 2),
        "annual_ret_pct": round((c_nav - 1.0) * 100, 1),
        "csi300_ret_pct": round(bench * 100, 1),
        "excess_pct": round(((c_nav - 1.0) - bench) * 100, 1)
    }

summary_data = {
    "audit_timestamp": datetime.datetime.now().isoformat(),
    "strategy": "Base_1to2_V18_Clean",
    "version": "V18_CLEAN_REBACKTEST_20261116",
    "status": "PASSED" if (t0_violations == 0 and overlap_violations == 0 and yizi_buy_violations == 0 and len(missing_trade_days) == 0) else "FLAGGED",
    "verification_gates": {
        "t0_violations": t0_violations,
        "overlap_violations": overlap_violations,
        "yizi_buy_violations": yizi_buy_violations,
        "five_min_coverage_pct": round(cov_pct, 2),
        "five_min_missing_days": len(missing_trade_days)
    },
    "comparison_with_old_v18": {
        "old_2022_trades": len(old_trades_set),
        "new_2022_trades": len(new_2022_set),
        "dropped_trades": [f"{dt} {c6}" for dt, c6 in sorted(dropped_vs_old)],
        "added_trades": [f"{dt} {c6}" for dt, c6 in sorted(added_vs_old)]
    },
    "d15_five_periods": {
        "since_2026_10": p_since_oct26,
        "since_2026_07": p_since_jul26,
        "year_2026": p_year_2026,
        "past_3y": p_3y,
        "full_5y": p_5y
    },
    "full_5y_metrics": {
        "trades_count": len(trades_all),
        "win_rate_pct": p_5y["win_rate"],
        "payoff_ratio": p_5y["payoff"],
        "single_slot_nav": p_5y["nav_mult"],
        "daily_eq_nav": r_5y.get("daily_eq", 0.0),
        "max_drawdown_pct": p_5y["mdd_pct"],
        "trimmed_top5_nav": round(trimmed_top5, 2),
        "longest_winning_streak": max_win_streak,
        "longest_losing_streak": max_loss_streak,
        "excess_vs_csi300_pct": p_5y["excess_vs_csi300_pct"],
        "annual_breakdown": annual_stats_full
    }
}

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(summary_data, f, ensure_ascii=False, indent=2)

print(f"\n✅ 完整 D15 汇总 JSON 已落盘: {OUT_JSON}")
print(f"总执行耗时: {time.time()-t_start:.1f}s")
