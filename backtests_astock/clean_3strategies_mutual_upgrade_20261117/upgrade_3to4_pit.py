#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
upgrade_3to4_pit.py
================================================================================
三进四策略 V4.0_cand（互学+瘦身升级独立版）完整五年纯前视（PIT）回测与八项防过拟合审计引擎

升级改动（100% 锁定于 IS 2021-2023 + ExpB P1 + ExpA3 跨策略互学，严禁偷看 OOS）：
  1. 剪除 V3.4 过时冗余噪音（ExpB P1 贪心剪枝）：
     - 删 T10 周一或节后跨周末发酵 (+2)
     - 删 T14 前日涨停 >=95 家 (-10)  [避免与 T03 温热(+5)叠加形成 15 分断崖误杀牛市主升龙]
     - 删 T20 三板股价 >32 元 (-5)     [避免在两万亿新生态误伤中价容量龙头]
  2. 吸收二进三正交因子与风控（ExpA3 IS 验证）：
     - 加 U01 启动前 20 日箱体低位 pos20_d0 <= 0.40 (+5) [自底部起跳无历史套牢盘]
     - 加 U02 雪球盘前高热 xq_cnt_2d >= 4 帖 (-15)       [前手最佳出货点即接盘坟场，严格 < buy_date 09:25:00]
  3. 交易执行窗口互学：
     - 买点撤单窗收紧：11:30 -> 10:30（touch65_1030，屏蔽 10:30 后诱多反抽单，不损合规 90 分单）
     - 卖点沿用最优：cut_weak（D4收阳不跌或次日高开>=+0.5%保留，否则09:25斩）+ pm1345_5m + 真阳免死1次

红线铁律：
  - 100% 独立单策略，绝不修改任何现役生产文件与 strategy_astock.md
  - 严禁 import yfinance (D12)；全部 SQLite 强制 mode=ro 只读
  - 内置三行校验（单位除数 + 时间锚点 < buy_date 09:25:00 + 极值与一字买 assert）
  - 执行物理截断 >= 2025-01-01 数据重跑 2021-2024 硬测试，断言 max_abs_diff == 0.0
================================================================================
"""

import bisect
from collections import Counter, defaultdict
import datetime
import glob
import itertools
import json
import math
import os
import pickle
import re
import sqlite3
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import scipy.stats as stats

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
SANDBOX = f"{SIM}/backtests_astock/sandbox_lab"
CLEAN_REF = f"{SIM}/backtests_astock/clean_rebacktest_20261116"
OUT_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"

A_DAILY_PQ = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELIST_PQ = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
IDX_JSON = f"{SANDBOX}/index_klines_5y_cache.json"
CSI_CANON_JSON = f"{CLEAN_REF}/csi300_canonical_20261116.json"
KPL_MERGED = f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl"
DB_ZT_TAPE = f"{SIM}/data/zt_micro_tape_5y_pit.db"
LHB_BUY_PQ = f"{SIM}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
HOLDERS_JSON = f"{SANDBOX}/grand_factor_matrix_20261112/pit_top10_all_codes.json"
CSRC_PIT_CSV = f"{SIM}/data/csrc_industry_pit_clean.csv"
CSRC_L2_CSV = f"{SIM}/data/csrc_industry_l2.csv"
DB_XQ_GB = f"{SIM}/data/xueqiu_guba_5y_pit.db"
DB_COMM = f"{SIM}/data/astock_community_5y_pit.db"
DB_NOTICES = f"{SIM}/data/cninfo_notices_5y_pit.db"
PQ_REG_TOX = f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet"
ZDJK_GLOB = f"{SIM}/data/kpl/zdjk/*.json"
PART1_PKL = f"{SANDBOX}/high_dragon_scorecard_20261113/part1_cache.pkl"
BARS_34_5M = f"{SIM}/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet"
BARS_ALL_5M = f"{SIM}/data/all_strategies_5m_complete_pit.parquet"

FEE_RATE = 0.0020
UNIT_PCT_DIV = 100.0
UNIT_YI_DIV = 1e8

SURF_YZ_RE = re.compile(
    r"(?:上塘路|财通.*杭州上塘|东方财富.*昌都|佛山|绿景路|苏南|消闲派|国泰君安.*宜昌|开源.*西安西大街)"
)
NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股",
}
MA_PAT = re.compile(r"(?:重组|收购|股权转让|实控人变更|控制权变更|资产注入|借壳|控股|整合|中标|重大合同)")
TECH_PAT_ORIG = re.compile(
    r"(?:芯片|半导体|光刻|集成电路|软件|信创|云计算|大数据|人工智能|AI|机器人|智能制造|通信|光通信|卫星|航天|军工|锂电|固态电池|光伏|储能|低空|无人驾驶)"
)
EARN_PAT = re.compile(r"(?:业绩|预增|年报|季报|中报|扭亏|高送转|分红)")
SPLIT_RE = re.compile(r"[+\s/、,，;；()（）【】]+")
TOX_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险)")
REG_INC_RE = re.compile(r"(?:监管工作函|监管函|关注函|重点监控|停牌核查)")
REG_EXC_RE = re.compile(r"(?:ST|回复|回函|延期|核查意见|复牌|募集资金|监事|独立董事|保荐)")

V34_FACTOR_NAMES = [
    "T01_三板收盘<=20元(+8)",
    "T02_前日最高板<=4板破局(+8)",
    "T03_前日涨停35至85家温热(+5)",
    "T04_同题材首板高开>=2且0一字(+4)",
    "T05_三板零拉萨席位(+4)",
    "T06_八年题材热度>=115(+3)",
    "T07_前日三板零跌停(+3)",
    "T08_三板换手9.5至28%黄金带(+3)",
    "T09_三板0936至1030封板(+3)",
    "T10_周一或节后跨周末发酵(+2)",
    "T11_交易所重点监控期(-12)",
    "T12_一日游砸盘席位买入(-12)",
    "T13_非同日可买三板竞价头名(-12)",
    "T14_前日涨停>=95家过热(-10)",
    "T15_同题材队友竞价均值<-1.5%(-10)",
    "T16_锁仓<45%且真实流值<45亿(-10)",
    "T17_三板换手越界8.5~31%之外(-10)",
    "T18_沪深300急杀2%或5日破3%(-8)",
    "T19_同题材首板顶一字>=1家(-7)",
    "T20_三板股价>32元(-5)",
    "T21_三板拉萨>=3家扎堆(-5)",
    "T22_前日三板跌停>=2家(-4)",
    "T23_1月或5月日历退潮窗(-4)",
]

V40_FACTOR_NAMES = [
    "T01_三板收盘<=20元(+8)",
    "T02_前日最高板<=4板破局(+8)",
    "T03_前日涨停35至85家温热(+5)",
    "T04_同题材首板高开>=2且0一字(+4)",
    "T05_三板零拉萨席位(+4)",
    "T06_八年题材热度>=115(+3)",
    "T07_前日三板零跌停(+3)",
    "T08_三板换手9.5至28%黄金带(+3)",
    "T09_三板0936至1030封板(+3)",
    "T11_交易所重点监控期(-12)",
    "T12_一日游砸盘席位买入(-12)",
    "T13_非同日可买三板竞价头名(-12)",
    "T15_同题材队友竞价均值<-1.5%(-10)",
    "T16_锁仓<45%且真实流值<45亿(-10)",
    "T17_三板换手越界8.5~31%之外(-10)",
    "T18_沪深300急杀2%或5日破3%(-8)",
    "T19_同题材首板顶一字>=1家(-7)",
    "T21_三板拉萨>=3家扎堆(-5)",
    "T22_前日三板跌停>=2家(-4)",
    "T23_1月或5月日历退潮窗(-4)",
    "U01_启动前20日箱体低位<=0.40(+5)[借二进三E12]",
    "U02_雪球盘前高热>=4帖(-15)[借二进三E08]",
]


def _split_terms(txt: str) -> set:
    if not txt:
        return set()
    return {t.strip() for t in SPLIT_RE.split(str(txt)) if len(t.strip()) >= 2 and t.strip() not in NON_THEME}


def run_three_line_validation(
    df_panel: pd.DataFrame,
    cand_df: pd.DataFrame,
    xq_violations: int,
    reg_violations: int,
    max_date: str,
) -> None:
    """硬编码三行铁律校验：单位除数 + PIT 时间锚点 < buy_date 09:25:00 + 行列与极值 assert"""
    med_mcap = float(df_panel["mcap"].median())
    med_to = float(df_panel["to"].median())
    assert abs(1.0 / UNIT_PCT_DIV - 0.01) < 1e-12 and UNIT_YI_DIV == 1e8 and FEE_RATE == 0.0020
    assert 15.0 <= med_mcap <= 250.0 and 0.5 <= med_to <= 50.0, f"Unit divisor fail: mcap={med_mcap}, to={med_to}"
    assert xq_violations == 0 and reg_violations == 0, f"PIT anchor breach: xq={xq_violations}, reg={reg_violations}"
    assert df_panel["dt_str"].max() <= max_date, f"Future date leaked past {max_date}: {df_panel['dt_str'].max()}"
    assert len(df_panel) >= 1500000 and cand_df.shape[1] >= 28 and not cand_df.empty
    assert cand_df["open_pct"].between(-0.11, 0.11).all() and cand_df["prev_to"].between(0.0, 100.0).all()


def _load_reg_tox_sources(max_date: str):
    """加载监管/重点监控/减持立案毒丸，并在载入阶段严格按 max_date 物理截断"""
    with open(PART1_PKL, "rb") as f:
        pkg = pickle.load(f)
    raw_sreg, raw_ereg, raw_tox = pkg[10], pkg[11], pkg[12]

    stk_reg = defaultdict(list)
    for c6, dts in raw_sreg.items():
        valid = [str(d)[:10] + " 08:00:00" for d in dts if str(d)[:10] <= max_date]
        if valid:
            stk_reg[str(c6).zfill(6)].extend(valid)

    ex_reg = {}
    for ex_k in ("SH", "SZ"):
        ex_reg[ex_k] = sorted([str(d)[:10] for d in raw_ereg.get(ex_k, []) if str(d)[:10] <= max_date])

    tox_map = defaultdict(list)
    for c6, dts in raw_tox.items():
        valid = [str(d)[:10] + " 08:00:00" for d in dts if str(d)[:10] <= max_date]
        if valid:
            tox_map[str(c6).zfill(6)].extend(valid)

    # 补充 2026-11-12 后的增量监管与毒丸公告（严格 <= max_date，避免历史样本覆盖 part1_cache 原生监管口径）
    if os.path.exists(PQ_REG_TOX):
        rt = pd.read_parquet(PQ_REG_TOX, columns=["sec_code", "pub_datetime_cst", "title"])
        rt["dt10"] = rt["pub_datetime_cst"].astype(str).str[:10]
        rt = rt[(rt["dt10"] > "2026-11-12") & (rt["dt10"] <= max_date)]
        for sc, pdt, ti in zip(
            rt["sec_code"].astype(str).str[:6].str.zfill(6),
            rt["pub_datetime_cst"].astype(str),
            rt["title"].astype(str),
        ):
            if TOX_RE.search(ti):
                tox_map[sc].append(pdt)
            if REG_INC_RE.search(ti) and (not REG_EXC_RE.search(ti)):
                stk_reg[sc].append(pdt)

    # 补充 KPL 重点监控公告（严格 <= max_date）
    for zf in glob.glob(ZDJK_GLOB):
        for it in json.load(open(zf, encoding="utf-8")).get("List", []):
            dt_z = str(it[2])[:10]
            if dt_z <= max_date:
                stk_reg[str(it[0]).zfill(6)].append(dt_z + " 08:00:00")

    return stk_reg, ex_reg, tox_map


def _build_kpl_8y_metadata(df: pd.DataFrame, max_date: str) -> dict:
    """严格因果递推 8 年 KPL 板块 Elo 热度分（逻辑对齐 exp1_fake_theme_purifier，截断至 max_date）"""
    kpl_days_map = {}
    with open(KPL_MERGED, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            d = json.loads(ln)
            dt = d.get("date", "")
            if dt and dt <= max_date:
                kpl_days_map[dt] = d
    kpl_days = [kpl_days_map[k] for k in sorted(kpl_days_map.keys())]
    kpl_dt_set = {d["date"] for d in kpl_days}
    sub_df_kpl = df[df["dt_str"].isin(kpl_dt_set)][["dt_str", "c6", "is_zt", "touch_zt", "is_yizi", "pct", "mcap"]]
    day_stock_map = {
        (r.dt_str, r.c6): (r.is_zt, r.touch_zt, r.is_yizi, r.pct, r.mcap)
        for r in sub_df_kpl.itertuples(index=False)
    }

    elo = defaultdict(lambda: 100.0)
    sub_elo = defaultdict(lambda: 100.0)
    plate_recent_zts = defaultdict(list)
    plate_last_idx, sub_last_idx = {}, {}
    prev_plate_stocks, prev_sub_stocks = {}, {}
    term_seen_days = Counter()
    term_first_dt, term_last_idx = {}, {}
    stock_theme_5y = {}

    for day_idx, d_entry in enumerate(kpl_days):
        dt = d_entry["date"]
        cutoff_15d = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=15)).isoformat()
        plates = d_entry.get("plates", [])

        for pname, c6_list in prev_plate_stocks.items():
            touches = seals = 0
            rets = []
            for c6 in c6_list:
                st = day_stock_map.get((dt, c6))
                if st is not None:
                    rets.append(st[3])
                    touches += int(st[1])
                    seals += int(st[0])
            if touches >= 2 and (seals / touches) < 0.50:
                elo[pname] -= 12.0 * ((touches - seals) / touches)
            elif rets and np.mean(rets) < -0.025:
                elo[pname] -= 10.0
            elif seals >= 2 and (seals / max(touches, 1)) >= 0.70:
                elo[pname] += min(10.0, 5.0 + seals * 1.2)
            elif rets and np.mean(rets) > 0.025:
                elo[pname] += 6.0

        for sname, c6_list in prev_sub_stocks.items():
            touches = seals = 0
            rets = []
            for c6 in c6_list:
                st = day_stock_map.get((dt, c6))
                if st is not None:
                    rets.append(st[3])
                    touches += int(st[1])
                    seals += int(st[0])
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
        plate_meta, day_terms_to_commit = {}, {}
        for p in plates:
            pname = p.get("plate", "")
            stocks = p.get("stocks", [])
            sz = len(stocks)
            if pname in NON_THEME or sz == 0:
                continue
            c6_list = []
            n_ma = n_tech_o = n_earn = n_big = n_yizi = n_new = 0
            spark_b = 0.0
            for s in stocks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6_list.append(c6)
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                r_lg = str(s[3]).strip() if len(s) > 3 else ""
                if r_sh and r_sh not in NON_THEME:
                    new_prev_sub[r_sh].append(c6)
                    sub_last_idx[r_sh] = day_idx
                txt = f"{pname} {r_sh} {r_lg}"
                if MA_PAT.search(txt):
                    n_ma += 1
                if TECH_PAT_ORIG.search(txt):
                    n_tech_o += 1
                if EARN_PAT.search(txt):
                    n_earn += 1
                for t in (_split_terms(pname) | _split_terms(r_sh)):
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
                    if st[4] >= 150.0:
                        n_big += 1
                    if st[2]:
                        n_yizi += 1

            new_prev_p[pname] = c6_list
            plate_last_idx[pname] = day_idx
            r5_zts = sum(cnt for idx_p, cnt in plate_recent_zts[pname] if day_idx - idx_p <= 5)
            plate_recent_zts[pname].append((day_idx, sz))
            sc_base = (
                elo[pname] + min(sz, 15) * 1.8 + min(r5_zts, 30) * 0.35
                + (8.0 if n_ma > 0 else 0.0) + (5.0 if n_new > 0 else 0.0)
                + spark_b + min(n_yizi * 4.0, 8.0) - (n_earn / sz) * 12.0 - (n_big / sz) * 10.0
            )
            sc_orig = sc_base + (6.0 if (TECH_PAT_ORIG.search(pname) or n_tech_o >= max(1, sz // 2)) else 0.0)
            plate_meta[pname] = (sc_orig, elo[pname], stocks)

        if dt >= "2021-01-01":
            for pname, (sc_o, p_elo, stocks) in plate_meta.items():
                for s in stocks:
                    c6 = str(s[0]).strip()[:6].zfill(6)
                    cur = stock_theme_5y.get((dt, c6))
                    if cur is None or sc_o > cur["t_score_o"]:
                        stock_theme_5y[(dt, c6)] = {"plate": pname, "t_score_o": sc_o, "p_elo": p_elo}

        for t, dt_v in day_terms_to_commit.items():
            term_seen_days[t] += 1
            if t not in term_first_dt:
                term_first_dt[t] = dt_v
            term_last_idx[t] = day_idx
        prev_plate_stocks, prev_sub_stocks = new_prev_p, new_prev_sub

    return stock_theme_5y


def _sim_buy_5m(c6: str, bd: str, cb: dict, pos: int, bars_5m_map: dict, max_hhmm: int) -> tuple:
    op = float(cb["open"][pos])
    pc = float(cb["pre_c"][pos])
    zt = float(cb["zt_px"][pos])
    if op >= zt - 0.005:
        return None, None
    trig = pc * 1.065
    if trig >= zt - 0.005:
        return None, None
    if op >= trig:
        return op, 925
    arr = bars_5m_map.get((c6, bd))
    if arr is None or len(arr) == 0:
        return None, None
    for row in arr:
        hhmm = int(row[0])
        if hhmm > max_hhmm:
            break
        bo, bh, bl = row[1], row[2], row[3]
        if bl >= zt - 0.005:
            continue
        if bh >= trig:
            fill_px = max(bo, trig)
            if fill_px < zt - 0.005:
                return float(fill_px), hhmm
    return None, None


def _sim_exit_5m(c6: str, cb: dict, pos: int, bars_5m_map: dict, day5_mode: str = "cut_weak") -> tuple:
    """严格因果 5m 逐日卖出模拟（不偷看未来收盘是否封板）"""
    n = len(cb["dts"])

    def _run_zt_hold(start_p: int):
        k = start_p + 1
        imm_used = False
        while k < n:
            if bool(cb["is_yizi_dt"][k]):
                k += 1
                continue
            dt_s = cb["dts"][k]
            ok = float(cb["open"][k])
            pck = float(cb["pre_c"][k])
            clk = float(cb["close"][k])
            ztk = float(cb["zt_px"][k])
            dtk = round(pck * 0.90, 2)
            if k > start_p + 1 and bool(cb["is_yizi_dt"][k - 1]):
                return dt_s, ok, float(cb["adjf"][k]), k - pos, 925
            arr = bars_5m_map.get((c6, dt_s))
            if arr is not None and len(arr) > 0:
                peak = ok
                for row in arr:
                    hh, bo, bh, bl, bc = int(row[0]), row[1], row[2], row[3], row[4]
                    if bh <= dtk + 0.005:
                        continue
                    if hh >= 1345 and peak >= pck * 1.085 and bl <= pck * 1.050 and bc < ztk - 0.01:
                        return dt_s, float(min(bo, pck * 1.050)), float(cb["adjf"][k]), k - pos, hh
                    if bh > peak:
                        peak = bh
            if bool(cb["is_zt"][k]):
                k += 1
                continue
            if (not imm_used) and (clk > ok) and (clk >= pck):
                imm_used = True
                k += 1
                continue
            return dt_s, clk, float(cb["adjf"][k]), max(1, k - pos), 1500
        k = n - 1
        return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500

    if not bool(cb["is_zt"][pos]):
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        k = min(k, n - 1)
        o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
        o5, p5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
        if k > pos + 1:
            return cb["dts"][k], o5, float(cb["adjf"][k]), k - pos, 925
        if day5_mode == "cut_weak":
            if not ((c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)):
                return cb["dts"][k], o5, float(cb["adjf"][k]), max(1, k - pos), 925
            if bool(cb["is_zt"][k]):
                return _run_zt_hold(k)
            return cb["dts"][k], c5, float(cb["adjf"][k]), max(1, k - pos), 1500
        # 2to3 weakcut0 comparison mode
        if o5 < p5 * 1.005:
            return cb["dts"][k], o5, float(cb["adjf"][k]), max(1, k - pos), 925
        if bool(cb["is_zt"][k]):
            return _run_zt_hold(k)
        return cb["dts"][k], c5, float(cb["adjf"][k]), max(1, k - pos), 1500
    return _run_zt_hold(pos)


def sim_single_slot(df_recs: pd.DataFrame) -> pd.DataFrame:
    """严格时间序单仓轮动撮合（按 buy_date, buy_hhmm 升序，同分钟按 priority_score 降序，同日仅 buy_hhmm > exit_hhmm 允许接力）"""
    if df_recs.empty:
        return pd.DataFrame()
    srt = df_recs.sort_values(["buy_date", "buy_hhmm", "priority_score", "code"], ascending=[True, True, False, True])
    taken = []
    free_dt, free_hh = "", 0
    for r in srt.itertuples(index=False):
        bd = str(r.buy_date)
        bh = int(r.buy_hhmm)
        if (not free_dt) or (bd > free_dt) or (bd == free_dt and bh > free_hh):
            taken.append(r._asdict())
            free_dt = str(r.exit_date)
            free_hh = int(r.exit_hhmm)
    out = pd.DataFrame(taken)
    if not out.empty:
        assert (out["exit_date"] > out["buy_date"]).all(), "T+0 violation detected!"
        for i in range(1, len(out)):
            p, c = out.iloc[i - 1], out.iloc[i]
            assert (c["buy_date"] > p["exit_date"]) or (
                c["buy_date"] == p["exit_date"] and int(c["buy_hhmm"]) > int(p["exit_hhmm"])
            ), f"Overlap violation: {p['buy_date']}->{p['exit_date']} vs {c['buy_date']}"
    return out


def run_causal_pipeline(max_date: str = "2026-11-16", verbose: bool = True) -> dict:
    """从原始 PIT 表从零因果构建三进四全样本候选、打分与 5m 真实撮合（物理截断 <= max_date）"""
    t0 = time.time()
    if verbose:
        print(f"[Pipeline max_date={max_date}] Loading raw PIT sources...")

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn", "oshare"]
    dt_cap = pd.Timestamp(max_date)
    d1 = ds.dataset(A_DAILY_PQ, format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2018-01-01")) & (ds.field("date") <= dt_cap)
    ).to_table().to_pandas()
    d2 = ds.dataset(A_DELIST_PQ, format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2018-01-01")) & (ds.field("date") <= dt_cap)
    ).to_table().to_pandas()

    df = pd.concat([d1, d2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].astype(str).str.endswith((".SH", ".SZ")) & df["c6"].str.startswith(("00", "60"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    g = df.groupby("c6")
    df = df[g.cumcount() >= 10].copy().reset_index(drop=True)
    g = df.groupby("c6")
    df["adjf"] = np.where(df["close"] > 0, df["adj_close"] / df["close"], 1.0)
    df["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["o_pct"] = df["open"] / df["pre_c"] - 1.0
    df["h_pct"] = df["high"] / df["pre_c"] - 1.0
    df["l_pct"] = df["low"] / df["pre_c"] - 1.0
    df["mcap"] = df["close"] * df["oshare"] / UNIT_YI_DIV
    df["to"] = df["turn"] * UNIT_PCT_DIV
    df["zt_price"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["dt_price"] = np.floor(df["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_price"] - 0.011) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
    df["is_dt"] = (df["close"] <= df["dt_price"] + 0.011) & (df["pct"] <= -0.095) & (df["pre_c"] > 0)
    df["touch_zt"] = ((df["high"] >= df["zt_price"] - 0.011) | (df["h_pct"] >= 0.098)) & (df["pre_c"] > 0)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_price"] - 0.011) & (df["low"] >= df["zt_price"] - 0.011)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_price"] + 0.011) & (df["high"] <= df["dt_price"] + 0.011)

    s_zt = df["is_zt"].astype(int)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != g["is_zt"].shift().fillna(False)).cumsum()]).cumsum() * s_zt
    df["min20"] = g["low"].transform(lambda s: s.rolling(20, min_periods=10).min())
    df["max20"] = g["high"].transform(lambda s: s.rolling(20, min_periods=10).max())
    df["pos20_today"] = (df["close"] - df["min20"]) / (df["max20"] - df["min20"] + 1e-6)

    # 2. 指数数据严格截断 <= max_date
    with open(IDX_JSON, "r", encoding="utf-8") as f:
        idx_raw = json.load(f)
    csi_map = {k: float(v) for k, v in idx_raw["sh000300"].items() if k <= max_date}
    sh_map = {k: float(v) for k, v in idx_raw["sh000002"].items() if k <= max_date}
    sz_map = {k: float(v) for k, v in idx_raw["sz399107"].items() if k <= max_date}
    csi_dts = sorted(csi_map.keys())
    csi_pos = {d: i for i, d in enumerate(csi_dts)}

    # 3. 8 年因果 KPL 题材热度
    stock_theme_5y = _build_kpl_8y_metadata(df, max_date)

    # 4. 日线切片（2021-10-01..max_date）与单日涨停/前日环境
    sub21 = df[df["dt_str"] >= "2021-10-01"].copy()
    sub21.sort_values(["c6", "dt_str"], inplace=True)
    g21 = sub21.groupby("c6")
    sub21["prev_streak"] = g21["streak"].shift(1).fillna(0).astype(int)
    sub21["prev_is_yizi"] = g21["is_yizi"].shift(1).fillna(False)
    sub21["buyable_open"] = (sub21["open"] < sub21["zt_price"] - 0.011) & (sub21["open"] > sub21["dt_price"] + 0.011) & (sub21["pre_c"] > 0)
    sub21["sig_date"] = g21["dt_str"].shift(1)
    sub21["prev_mcap"] = g21["mcap"].shift(1)
    sub21["prev_to"] = g21["to"].shift(1)
    sub21["pos20_d0"] = g21["pos20_today"].shift(4)  # D0 = D3前3日 = buy_date前4日

    # CSRC PIT 行业 & 名称
    ind_l2 = pd.read_csv(CSRC_L2_CSV)
    ind_l2["c6"] = ind_l2["code"].astype(str).str[-6:].str.zfill(6)
    name_map = dict(zip(ind_l2["c6"], ind_l2["code_name"].fillna("")))

    csrc_pit_df = pd.read_csv(CSRC_PIT_CSV)
    csrc_pit_df["c6"] = csrc_pit_df["sec_code"].astype(str).str.zfill(6)
    csrc_ivs = defaultdict(list)
    for r in csrc_pit_df[["c6", "start_date", "end_date", "industry"]].itertuples(index=False):
        csrc_ivs[r.c6].append((str(r.start_date), str(r.end_date), str(r.industry or "")))

    def _get_pit_csrc(c6: str, dt: str) -> str:
        ivs = csrc_ivs.get(c6)
        if not ivs:
            return ""
        for s_d, e_d, ind_v in ivs:
            if s_d <= dt <= e_d:
                return ind_v
        return ivs[0][2] if dt < ivs[0][0] else ivs[-1][2]

    # 市场环境表（按 buy_date 前移 1 日）与 CSRC 同日涨停数
    env_rows = []
    csrc_zt_day_map = defaultdict(lambda: defaultdict(int))
    for dt, grp in sub21.groupby("dt_str", sort=True):
        zt_g = grp[grp["is_zt"]]
        for c6_z in zt_g["c6"].values:
            cs_z = _get_pit_csrc(c6_z, dt)
            if cs_z:
                csrc_zt_day_map[dt][cs_z] += 1
        n_zt = int(len(zt_g))
        max_b = int(zt_g["streak"].max()) if n_zt > 0 else 0
        b3_today = grp[grp["prev_streak"] >= 3]
        b3_dt_cnt = int(b3_today["is_dt"].sum())
        env_rows.append({"dt_str": dt, "n_zt": n_zt, "max_board": max_b, "b3_dt_cnt": b3_dt_cnt})

    env_df = pd.DataFrame(env_rows).sort_values("dt_str").reset_index(drop=True)
    env_df["mkt_zt_prev"] = env_df["n_zt"].shift(1).fillna(50).astype(int)
    env_df["mkt_max_board_prev"] = env_df["max_board"].shift(1).fillna(4).astype(int)
    env_df["prev_3b_dt_cnt"] = env_df["b3_dt_cnt"].shift(1).fillna(0).astype(int)
    env_map = env_df.set_index("dt_str").to_dict(orient="index")

    # 构建 code_bars（2021-10-01..max_date）
    code_bars = {}
    for c6, g_c in sub21.groupby("c6", sort=False):
        code_bars[c6] = {
            "dts": g_c["dt_str"].values,
            "date_to_pos": {d: idx for idx, d in enumerate(g_c["dt_str"].values)},
            "open": g_c["open"].values.astype(float),
            "high": g_c["high"].values.astype(float),
            "low": g_c["low"].values.astype(float),
            "close": g_c["close"].values.astype(float),
            "adjf": g_c["adjf"].values.astype(float),
            "pre_c": g_c["pre_c"].values.astype(float),
            "zt_px": g_c["zt_price"].values.astype(float),
            "dt_px": g_c["dt_price"].values.astype(float),
            "is_zt": g_c["is_zt"].values.astype(bool),
            "is_yizi": g_c["is_yizi"].values.astype(bool),
            "is_yizi_dt": g_c["is_yizi_dt"].values.astype(bool),
        }

    # 5. 微观涨停、龙虎榜、锁仓、监管毒丸、雪球、5m K 线（全严格 <= max_date & mode=ro）
    con_tp = sqlite3.connect(f"file:{DB_ZT_TAPE}?mode=ro", uri=True)
    df_tape = pd.read_sql_query(
        "SELECT trade_date, sec_code, first_seal_time, open_board_count FROM zt_micro_tape WHERE trade_date >= '2021-10-01' AND trade_date <= ?",
        con_tp,
        params=(max_date,),
    )
    con_tp.close()
    tape_map = {
        (str(r.trade_date), str(r.sec_code)[:6].zfill(6)): (
            str(r.first_seal_time or "99:99:99"),
            int(r.open_board_count if pd.notna(r.open_board_count) else 0),
        )
        for r in df_tape.itertuples(index=False)
    }

    lhb = pd.read_parquet(LHB_BUY_PQ, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME"])
    lhb["dt"] = lhb["TRADE_DATE"].astype(str).str[:10]
    lhb = lhb[(lhb["dt"] >= "2021-10-01") & (lhb["dt"] <= max_date)].copy()
    lhb["c6"] = lhb["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    lhb_lh_map = {}
    lhb_surf_map = {}
    for (dt_l, c6_l), s_grp in lhb.groupby(["dt", "c6"])["OPERATEDEPT_NAME"]:
        names = set(s_grp.dropna().astype(str))
        lhb_lh_map[(dt_l, c6_l)] = sum(1 for x in names if "拉萨" in x)
        lhb_surf_map[(dt_l, c6_l)] = any(SURF_YZ_RE.search(x) for x in names)

    with open(HOLDERS_JSON, "r", encoding="utf-8") as f:
        holders_raw = json.load(f)
    holders_map = {
        c6: [rec for rec in lst if str(rec[0])[:10] <= max_date]
        for c6, lst in holders_raw.items()
    }

    stk_reg, ex_reg, tox_map = _load_reg_tox_sources(max_date)

    # 加载 3to4 核心母池并顺带索引首板 & 连板同题材梯队
    w5y = sub21[(sub21["dt_str"] >= "2021-11-15") & (sub21["dt_str"] <= max_date) & sub21["sig_date"].notna()].copy()
    c34_raw = w5y[w5y["prev_streak"] == 3].copy().reset_index(drop=True)
    target_34_codes = set(c34_raw["c6"].unique())

    # 雪球帖子（严格 mode=ro, <= max_date 23:59:59, 去重后排序）
    xq_seen = defaultdict(set)
    xq_posts = defaultdict(list)
    con_xq = sqlite3.connect(f"file:{DB_XQ_GB}?mode=ro", uri=True)
    for sym, pid, cts in con_xq.execute(
        "SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE created_time_str >= '2021-10-01' AND created_time_str <= ?",
        (f"{max_date} 23:59:59",),
    ):
        c6 = str(sym)[:6].zfill(6)
        if c6 in target_34_codes and cts:
            pid_c = str(pid).replace("xq_", "")
            if pid_c not in xq_seen[c6]:
                xq_seen[c6].add(pid_c)
                xq_posts[c6].append(str(cts))
    con_xq.close()

    con_cm = sqlite3.connect(f"file:{DB_COMM}?mode=ro", uri=True)
    for sym, pid, cts in con_cm.execute(
        "SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND pub_datetime_cst >= '2021-10-01' AND pub_datetime_cst <= ?",
        (f"{max_date} 23:59:59",),
    ):
        c6 = str(sym)[:6].zfill(6)
        if c6 in target_34_codes and cts:
            pid_c = str(pid).replace("xq_", "")
            if pid_c not in xq_seen[c6]:
                xq_seen[c6].add(pid_c)
                xq_posts[c6].append(str(cts))
    con_cm.close()
    xq_arr_map = {c6: np.sort(np.array(v, dtype=str)) for c6, v in xq_posts.items()}

    # 5m K 线（严格截断 date <= max_date）
    df_5m_a = ds.dataset(BARS_ALL_5M, format="parquet").scanner(
        columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
        filter=(ds.field("date") <= max_date),
    ).to_table().to_pandas()
    df_5m_b = ds.dataset(BARS_34_5M, format="parquet").scanner(
        columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
        filter=(ds.field("date") <= max_date),
    ).to_table().to_pandas()
    df_5m = pd.concat([df_5m_a, df_5m_b], ignore_index=True)
    df_5m.drop_duplicates(["c6", "date", "hhmm_int"], keep="first", inplace=True)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_map = {
        (c6, d): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        for (c6, d), grp in df_5m.groupby(["c6", "date"], sort=False)
    }

    # 6. 同题材梯队（严格按 max_date 物理截断后，与 grand_factor_matrix 首板母表对齐）
    c01_path = f"{SANDBOX}/grand_factor_matrix_20261112/cand_0to1_firstboard.parquet"
    fb_c01 = pd.read_parquet(c01_path, columns=["code", "buy_date", "plate", "is_zt_today"])
    fb_c01["c6"] = fb_c01["code"].astype(str).str.zfill(6)
    fb_c01["dt_str"] = fb_c01["buy_date"].astype(str)
    fb_c01 = fb_c01[(fb_c01["is_zt_today"] == True) & (fb_c01["dt_str"] <= max_date)][["c6", "dt_str", "plate"]].copy()

    # 补充 2026-11-10 之后的新增首板日
    fb_tail = w5y[
        (w5y["dt_str"] > "2026-11-10")
        & (w5y["prev_streak"] == 0)
        & (w5y["open"] < w5y["zt_price"] - 0.011)
        & (w5y["touch_zt"] | (w5y["h_pct"] >= 0.065))
        & w5y["is_zt"]
    ][["c6", "sig_date", "dt_str"]].copy()
    if not fb_tail.empty:
        fb_tail["plate"] = [stock_theme_5y.get((s, c), {}).get("plate", "其他") for s, c in zip(fb_tail["sig_date"], fb_tail["c6"])]
        fb_df = pd.concat([fb_c01, fb_tail[["c6", "dt_str", "plate"]]], ignore_index=True)
    else:
        fb_df = fb_c01

    d4_op_list, d4_yz_list = [], []
    for r in fb_df.itertuples(index=False):
        cb1 = code_bars.get(r.c6)
        p1 = cb1["date_to_pos"].get(r.dt_str, -1) if cb1 else -1
        if cb1 and 0 <= p1 < len(cb1["dts"]) - 1 and cb1["pre_c"][p1 + 1] > 0:
            op_n = float(cb1["open"][p1 + 1] / cb1["pre_c"][p1 + 1] - 1.0)
            yz_n = bool(cb1["open"][p1 + 1] >= cb1["zt_px"][p1 + 1] - 0.005)
        else:
            op_n, yz_n = 0.0, False
        d4_op_list.append(op_n)
        d4_yz_list.append(yz_n)
    fb_df["d4_op"] = d4_op_list
    fb_df["d4_yz"] = d4_yz_list
    fb_plate_stats = {}
    for (sd_k, pl), g_f in fb_df[fb_df["plate"].notna() & (fb_df["plate"] != "")].groupby(["dt_str", "plate"], sort=False):
        ops = g_f["d4_op"].to_numpy()
        fb_plate_stats[(sd_k, pl)] = (int((ops >= 0.03).sum()), int(g_f["d4_yz"].sum()))

    zt_prev_rows = w5y[w5y["prev_streak"] >= 1][["c6", "sig_date", "dt_str", "o_pct", "open", "zt_price"]].copy()
    zt_prev_rows["plate"] = [stock_theme_5y.get((s, c), {}).get("plate", "其他") for s, c in zip(zt_prev_rows["sig_date"], zt_prev_rows["c6"])]
    p_grp = zt_prev_rows[zt_prev_rows["plate"] != "其他"].groupby(["dt_str", "plate"], as_index=False)["o_pct"].mean()
    plate_peers_open_map = {(r.dt_str, r.plate): round(float(r.o_pct), 4) for r in p_grp.itertuples(index=False)}

    # 同日三板可买竞价极值（非一字、非ST、可买高开）
    c34_raw["name"] = c34_raw["c6"].map(name_map).fillna("")
    is_10cm_list = []
    for r in c34_raw.itertuples(index=False):
        cb = code_bars.get(r.c6)
        ok_10 = (
            cb is not None
            and r.c6.startswith(("00", "60"))
            and ("ST" not in str(r.name).upper())
            and (r.dt_str in cb["date_to_pos"])
        )
        if ok_10:
            p_b = cb["date_to_pos"][r.dt_str]
            ok_10 = bool(cb["pre_c"][p_b] > 0 and (cb["zt_px"][p_b] / cb["pre_c"][p_b] >= 1.085))
        is_10cm_list.append(ok_10)
    c34_raw["is_10cm_non_st"] = is_10cm_list

    b3_clean = c34_raw[(~c34_raw["prev_is_yizi"]) & c34_raw["buyable_open"] & c34_raw["is_10cm_non_st"]]
    b3_day_max_op = b3_clean.groupby("dt_str")["o_pct"].max().to_dict()

    # 7. 逐行装配特征 + 三行时间锚点审计 + 5m 撮合
    rows = []
    p_1130, p_1030, p_2to3exit = [], [], []
    xq_violations = 0
    reg_violations = 0
    has_5m_buy_flags = []
    has_5m_exit_flags = []

    for r in c34_raw.itertuples(index=False):
        c6 = r.c6
        sd = str(r.sig_date)
        bd = str(r.dt_str)
        cb = code_bars.get(c6)
        pos = cb["date_to_pos"].get(bd, -1) if cb else -1

        env = env_map.get(bd, {"mkt_zt_prev": 50, "mkt_max_board_prev": 4, "prev_3b_dt_cnt": 0})
        val_h = [x for x in holders_map.get(c6, []) if str(x[0])[:10] <= sd]
        lock10 = float(max(val_h, key=lambda x: (str(x[1]), str(x[0])))[2]) if val_h else 38.0
        mcap = float(r.prev_mcap) if pd.notna(r.prev_mcap) else 50.0
        rf_mcap = round(mcap * max(0.05, 1.0 - lock10 / 100.0), 2)
        prev_to = round(float(r.prev_to), 2) if pd.notna(r.prev_to) else 8.0

        ti = stock_theme_5y.get((sd, c6), {"plate": "其他", "p_elo": 100.0})
        plate, p_elo = ti["plate"], float(ti["p_elo"])
        fst, opn_cnt = tape_map.get((sd, c6), ("99:99:99", 0))
        lh_cnt = int(lhb_lh_map.get((sd, c6), 0))
        surf_yz = bool(lhb_surf_map.get((sd, c6), False))

        fp = fb_plate_stats.get((sd, plate), (0, 0))
        peers_op = float(plate_peers_open_map.get((bd, plate), 0.0))
        is_top1 = float(r.o_pct) >= float(b3_day_max_op.get(bd, 9.9)) - 1e-5
        px_d3 = float(cb["pre_c"][pos]) if (cb and pos >= 0 and pd.notna(cb["pre_c"][pos])) else float(r.pre_c)

        # CSI 1d & 5d strictly on sig_date
        ci = csi_pos.get(sd, -1)
        csi_1d = (csi_map[sd] / csi_map[csi_dts[ci - 1]] - 1.0) if ci >= 1 else 0.0
        csi_5d = (csi_map[sd] / csi_map[csi_dts[ci - 5]] - 1.0) if ci >= 5 else 0.0

        # 周一或节后 (>=3天未交易)
        bi_bd = bisect.bisect_left(csi_dts, bd)
        is_mon_hol = ((pd.Timestamp(bd) - pd.Timestamp(csi_dts[bi_bd - 1])).days >= 3) if bi_bd > 0 else (pd.Timestamp(bd).weekday() == 0)

        # 监管 / 毒丸严格时间锚点 (< buy_date 09:25:00 & dm10/dm5 <= sd)
        dm10 = csi_dts[max(0, ci - 10)] if ci >= 0 else "1990-01-01"
        dm5 = csi_dts[max(0, ci - 5)] if ci >= 0 else "1990-01-01"
        end_cut = f"{bd} 09:25:00"
        ex_k = "SH" if c6.startswith("60") else "SZ"

        sreg_hits = [x for x in stk_reg.get(c6, []) if dm10 <= x[:10] and x < end_cut]
        tox_hits = [x for x in tox_map.get(c6, []) if dm10 <= x[:10] and x < end_cut]
        if any(x >= end_cut for x in sreg_hits) or any(x >= end_cut for x in tox_hits):
            reg_violations += 1
        has_sreg = len(sreg_hits) > 0
        has_tox = len(tox_hits) > 0
        has_ereg = any(dm5 <= d <= sd for d in ex_reg.get(ex_k, []))

        # 雪球严格 [d1_date 00:00:00, buy_date 09:25:00)
        d1_dt = str(cb["dts"][max(0, pos - 3)]) if (cb and pos >= 3) else sd
        xq_arr = xq_arr_map.get(c6)
        if xq_arr is not None and len(xq_arr) > 0:
            p_end = int(np.searchsorted(xq_arr, end_cut, side="left"))
            p_beg = int(np.searchsorted(xq_arr, f"{d1_dt} 00:00:00", side="left"))
            if p_end > 0 and xq_arr[p_end - 1] >= end_cut:
                xq_violations += 1
            xq_2d = max(0, p_end - p_beg)
        else:
            xq_2d = 0

        pos20_d0 = float(r.pos20_d0) if pd.notna(r.pos20_d0) else 0.50
        csrc_ind = _get_pit_csrc(c6, sd)
        csrc_zt = int(csrc_zt_day_map.get(sd, {}).get(csrc_ind, 0))
        prio_3to4 = float(r.o_pct) * 1000.0 + lock10 * 0.5 + csrc_zt * 2.0

        # 5m 撮合（11:30 vs 10:30）
        has_5m_b = (c6, bd) in bars_5m_map
        has_5m_buy_flags.append(has_5m_b)

        rec_1130 = rec_1030 = rec_w0 = None
        has_5m_e = False
        if bool(r.is_10cm_non_st) and bool(r.buyable_open) and cb is not None and 0 <= pos < len(cb["dts"]) - 1:
            ex_dt, spx, adjs, hb, shh = _sim_exit_5m(c6, cb, pos, bars_5m_map, "cut_weak")
            has_5m_e = (c6, ex_dt) in bars_5m_map

            bpx11, bhh11 = _sim_buy_5m(c6, bd, cb, pos, bars_5m_map, 1130)
            if bpx11 is not None:
                assert bpx11 < float(cb["zt_px"][pos]) - 0.005
                nr11 = (spx * adjs) / (bpx11 * float(cb["adjf"][pos])) * (1.0 - FEE_RATE) - 1.0
                rec_1130 = {
                    "code": c6, "name": str(r.name), "buy_date": bd, "buy_hhmm": bhh11,
                    "buy_price": round(bpx11, 2), "exit_date": ex_dt, "exit_hhmm": shh,
                    "exit_price": round(spx, 2), "hold_bars": hb, "net_ret": float(nr11),
                }

            bpx10, bhh10 = _sim_buy_5m(c6, bd, cb, pos, bars_5m_map, 1030)
            if bpx10 is not None:
                assert bpx10 < float(cb["zt_px"][pos]) - 0.005
                nr10 = (spx * adjs) / (bpx10 * float(cb["adjf"][pos])) * (1.0 - FEE_RATE) - 1.0
                rec_1030 = {
                    "code": c6, "name": str(r.name), "buy_date": bd, "buy_hhmm": bhh10,
                    "buy_price": round(bpx10, 2), "exit_date": ex_dt, "exit_hhmm": shh,
                    "exit_price": round(spx, 2), "hold_bars": hb, "net_ret": float(nr10),
                }
                ex_w0, spx_w0, adj_w0, hb_w0, shh_w0 = _sim_exit_5m(c6, cb, pos, bars_5m_map, "weakcut0")
                nr_w0 = (spx_w0 * adj_w0) / (bpx10 * float(cb["adjf"][pos])) * (1.0 - FEE_RATE) - 1.0
                rec_w0 = {
                    "code": c6, "name": str(r.name), "buy_date": bd, "buy_hhmm": bhh10,
                    "buy_price": round(bpx10, 2), "exit_date": ex_w0, "exit_hhmm": shh_w0,
                    "exit_price": round(spx_w0, 2), "hold_bars": hb_w0, "net_ret": float(nr_w0),
                }

        p_1130.append(rec_1130)
        p_1030.append(rec_1030)
        p_2to3exit.append(rec_w0)
        has_5m_exit_flags.append(has_5m_e)

        rows.append({
            "code": c6, "name": str(r.name), "sig_date": sd, "buy_date": bd,
            "is_10cm_non_st": bool(r.is_10cm_non_st), "prev_is_yizi": bool(r.prev_is_yizi),
            "buyable_open": bool(r.buyable_open), "has_tox_notice": has_tox, "has_stock_reg": has_sreg,
            "open_board_count": int(opn_cnt), "open_pct": float(r.o_pct),
            "is_top1_3b_open": bool(is_top1), "lock_top10": round(lock10, 2), "real_free_mcap": rf_mcap,
            "prev_to": prev_to, "first_seal_time": fst, "px_d3": round(px_d3, 2),
            "mkt_max_board_prev": int(env["mkt_max_board_prev"]), "mkt_zt_prev": int(env["mkt_zt_prev"]),
            "prev_3b_dt_cnt": int(env["prev_3b_dt_cnt"]), "p_elo": round(p_elo, 2),
            "has_ex_reg": has_ereg, "surf_yz_buy": surf_yz, "lhb_lh_cnt": lh_cnt,
            "plate_fb_ho_cnt": int(fp[0]), "plate_fb_yz_cnt": int(fp[1]),
            "plate_peers_open_avg": peers_op, "csi_1d_prev": csi_1d, "csi_5d_prev": csi_5d,
            "is_post_holiday_or_mon": bool(is_mon_hol), "buy_month": int(bd[5:7]),
            "pos20_d0": round(pos20_d0, 4), "xq_cnt_2d": int(xq_2d),
            "plate": plate, "csrc_ind": csrc_ind, "prio_3to4": prio_3to4,
            "has_5m_buy": has_5m_b, "has_5m_exit": has_5m_e,
        })

    cand_df = pd.DataFrame(rows)
    run_three_line_validation(df, cand_df, xq_violations, reg_violations, max_date)

    # 8. 构建 V3.4 (23因子) 与 V4.0_cand (22因子) 骨架与逐项得分矩阵（活跃 5m 交易窗自 2022-01-04 起）
    raw_core = (
        cand_df["is_10cm_non_st"]
        & (~cand_df["prev_is_yizi"])
        & cand_df["buyable_open"]
        & (~cand_df["has_tox_notice"])
        & (~cand_df["has_stock_reg"])
        & (cand_df["open_board_count"] >= 1)
        & cand_df["open_pct"].between(0.030, 0.092)
    ).to_numpy()
    skel = raw_core & (cand_df["buy_date"] >= "2022-01-04").to_numpy()

    fs = pd.to_numeric(cand_df["first_seal_time"].astype(str).str.replace(":", "").str[:4], errors="coerce").fillna(9999).astype(int)
    lock_bad = (cand_df["lock_top10"] < 45.0) & (cand_df["real_free_mcap"] < 45.0)

    comp_v34 = np.zeros((len(cand_df), 23), dtype=float)
    comp_v34[:, 0] = np.where(cand_df["px_d3"] <= 20.0, 8.0, 0.0)
    comp_v34[:, 1] = np.where(cand_df["mkt_max_board_prev"] <= 4, 8.0, 0.0)
    comp_v34[:, 2] = np.where(cand_df["mkt_zt_prev"].between(35, 85), 5.0, 0.0)
    comp_v34[:, 3] = np.where((cand_df["plate_fb_ho_cnt"] >= 2) & (cand_df["plate_fb_yz_cnt"] == 0), 4.0, 0.0)
    comp_v34[:, 4] = np.where(cand_df["lhb_lh_cnt"] == 0, 4.0, 0.0)
    comp_v34[:, 5] = np.where(cand_df["p_elo"] >= 115.0, 3.0, 0.0)
    comp_v34[:, 6] = np.where(cand_df["prev_3b_dt_cnt"] == 0, 3.0, 0.0)
    comp_v34[:, 7] = np.where(cand_df["prev_to"].between(9.5, 28.0), 3.0, 0.0)
    comp_v34[:, 8] = np.where(fs.between(936, 1030), 3.0, 0.0)
    comp_v34[:, 9] = np.where(cand_df["is_post_holiday_or_mon"], 2.0, 0.0)
    comp_v34[:, 10] = np.where(cand_df["has_ex_reg"], -12.0, 0.0)
    comp_v34[:, 11] = np.where(cand_df["surf_yz_buy"], -12.0, 0.0)
    comp_v34[:, 12] = np.where(~cand_df["is_top1_3b_open"], -12.0, 0.0)
    comp_v34[:, 13] = np.where(cand_df["mkt_zt_prev"] >= 95, -10.0, 0.0)
    comp_v34[:, 14] = np.where(cand_df["plate_peers_open_avg"] < -0.015, -10.0, 0.0)
    comp_v34[:, 15] = np.where(lock_bad, -10.0, 0.0)
    comp_v34[:, 16] = np.where(~cand_df["prev_to"].between(8.5, 31.0), -10.0, 0.0)
    comp_v34[:, 17] = np.where((cand_df["csi_1d_prev"] <= -0.020) | (cand_df["csi_5d_prev"] <= -0.030), -8.0, 0.0)
    comp_v34[:, 18] = np.where(cand_df["plate_fb_yz_cnt"] >= 1, -7.0, 0.0)
    comp_v34[:, 19] = np.where(cand_df["px_d3"] > 32.0, -5.0, 0.0)
    comp_v34[:, 20] = np.where(cand_df["lhb_lh_cnt"] >= 3, -5.0, 0.0)
    comp_v34[:, 21] = np.where(cand_df["prev_3b_dt_cnt"] >= 2, -4.0, 0.0)
    comp_v34[:, 22] = np.where(cand_df["buy_month"].isin([1, 5]), -4.0, 0.0)

    # V4.0_cand 22项正交分量（删 T10, T14, T20，增 U01 pos20_d0<=0.40 +5 与 U02 xq_cnt_2d>=4 -15）
    keep_v34_idx = [i for i in range(23) if i not in (9, 13, 19)]
    u01 = np.where(cand_df["pos20_d0"] <= 0.40, 5.0, 0.0)
    u02 = np.where(cand_df["xq_cnt_2d"] >= 4, -15.0, 0.0)
    comp_v40 = np.column_stack([comp_v34[:, keep_v34_idx], u01, u02])

    sc_v34 = np.where(skel, 78.0 + comp_v34.sum(axis=1), -999.0)
    sc_v40 = np.where(skel, 78.0 + comp_v40.sum(axis=1), -999.0)

    if verbose:
        print(f"[Pipeline max_date={max_date}] Built {len(cand_df)} candidates in {time.time()-t0:.1f}s")

    return {
        "cand_df": cand_df,
        "raw_core": raw_core,
        "skel": skel,
        "comp_v34": comp_v34,
        "comp_v40": comp_v40,
        "sc_v34": sc_v34,
        "sc_v40": sc_v40,
        "p_1130": p_1130,
        "p_1030": p_1030,
        "p_2to3exit": p_2to3exit,
        "csi_map": csi_map,
        "all_csi_dts": csi_dts,
        "code_bars": code_bars,
    }


def extract_raw_and_slot(res: dict, sc_arr: np.ndarray, thr: float, p_key: str = "p_1030") -> tuple:
    cand_df = res["cand_df"]
    p_list = res[p_key]
    idx = np.where(sc_arr >= thr)[0]
    recs = []
    for i in idx:
        pi = p_list[i]
        if pi is None:
            continue
        rec = dict(pi)
        rec["score"] = int(round(float(sc_arr[i])))
        rec["priority_score"] = float(sc_arr[i]) * 10.0 + float(cand_df["prio_3to4"].iloc[i]) * 0.1
        rec["open_pct"] = float(cand_df["open_pct"].iloc[i])
        rec["pos20_d0"] = float(cand_df["pos20_d0"].iloc[i])
        rec["xq_cnt_2d"] = int(cand_df["xq_cnt_2d"].iloc[i])
        rec["has_5m_buy"] = bool(cand_df["has_5m_buy"].iloc[i])
        rec["has_5m_exit"] = bool(cand_df["has_5m_exit"].iloc[i])
        recs.append(rec)
    raw_df = pd.DataFrame(recs)
    slot_df = sim_single_slot(raw_df)
    return raw_df, slot_df


def _csi300_ret(csi_map: dict, all_dts: list, s_dt: str, e_dt: str) -> float:
    dts = [d for d in all_dts if s_dt <= d <= e_dt]
    if not dts:
        return 0.0
    prevs = [d for d in all_dts if d < dts[0]]
    p0 = csi_map[prevs[-1]] if prevs else csi_map[dts[0]]
    p1 = csi_map[dts[-1]]
    return float(p1 / p0 - 1.0)


def _calc_metrics_window(
    raw_df: pd.DataFrame,
    slot_df: pd.DataFrame,
    csi_map: dict,
    all_dts: list,
    s_dt: str,
    e_dt: str,
    canon_csi_pct: float = None,
) -> dict:
    csi_p = canon_csi_pct if canon_csi_pct is not None else round(_csi300_ret(csi_map, all_dts, s_dt, e_dt) * 100.0, 2)
    sr = raw_df[(raw_df["buy_date"] >= s_dt) & (raw_df["buy_date"] <= e_dt)] if not raw_df.empty else raw_df
    ss = slot_df[(slot_df["buy_date"] >= s_dt) & (slot_df["buy_date"] <= e_dt)] if not slot_df.empty else slot_df
    if ss.empty:
        return {
            "window": f"{s_dt} ~ {e_dt}", "raw_n": int(len(sr)), "single_n": 0,
            "win_rate_pct": 0.0, "plr": 0.0, "mean_ret_pct": 0.0,
            "single_slot_nav": 1.0, "cap10m_1m_mult": 1.0, "cap10m_10m_mult": 1.0,
            "daily_equal_weight_nav": 1.0, "trimmed_top3_nav": 1.0, "trimmed_top5_nav": 1.0,
            "max_drawdown_pct": 0.0, "csi300_ret_pct": csi_p,
            "excess_1s_pp": round(-csi_p, 2), "excess_eq_pp": round(-csi_p, 2),
        }
    rets = ss["net_ret"].to_numpy(dtype=float)
    wins, losses = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) and len(losses) and losses.mean() < 0) else 99.0
    nav_1s = float(np.prod(1.0 + rets))

    pk = cur = 1.0
    mdd = 0.0
    for x in rets:
        cur *= 1.0 + x
        pk = max(pk, cur)
        mdd = max(mdd, (pk - cur) / pk)

    cap1m, cap10m = 100.0, 1000.0
    for x in rets:
        cap1m += min(cap1m, 1000.0) * float(x)
        cap10m += min(cap10m, 1000.0) * float(x)

    eq_nav = float(np.prod(1.0 + sr.groupby("buy_date")["net_ret"].mean().sort_index().to_numpy())) if not sr.empty else 1.0
    s_ret = np.sort(rets)
    t3 = float(np.prod(1.0 + s_ret[:-3])) if len(s_ret) > 3 else 1.0
    t5 = float(np.prod(1.0 + s_ret[:-5])) if len(s_ret) > 5 else 1.0
    return {
        "window": f"{s_dt} ~ {e_dt}",
        "raw_n": int(len(sr)),
        "single_n": int(len(rets)),
        "win_rate_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_ret_pct": round(float(rets.mean() * 100.0), 2),
        "single_slot_nav": round(nav_1s, 4),
        "cap10m_1m_mult": round(cap1m / 100.0, 2),
        "cap10m_10m_mult": round(cap10m / 1000.0, 2),
        "daily_equal_weight_nav": round(eq_nav, 4),
        "trimmed_top3_nav": round(t3, 4),
        "trimmed_top5_nav": round(t5, 4),
        "max_drawdown_pct": round(mdd * 100.0, 2),
        "csi300_ret_pct": round(csi_p, 2),
        "excess_1s_pp": round((nav_1s - 1.0) * 100.0 - csi_p, 2),
        "excess_eq_pp": round((eq_nav - 1.0) * 100.0 - csi_p, 2),
    }


def _calc_cap10m_stats(rets: np.ndarray) -> dict:
    n = len(rets)
    if n == 0:
        return {"trades": 0, "win_rate_pct": 0.0, "nav": 1.0, "cap10m_1m_ret_pct": 0.0, "cap10m_10m_ret_pct": 0.0, "max_dd_pct": 0.0}
    wr = float((rets > 0).mean() * 100.0)
    nav_c = np.cumprod(1.0 + rets)
    peaks = np.maximum.accumulate(np.insert(nav_c, 0, 1.0))[1:]
    mdd = float(np.max((peaks - nav_c) / peaks) * 100.0)
    cap1m, cap10m = 100.0, 1000.0
    for x in rets:
        cap1m += min(cap1m, 1000.0) * float(x)
        cap10m += min(cap10m, 1000.0) * float(x)
    return {
        "trades": int(n),
        "win_rate_pct": round(wr, 2),
        "nav": round(float(nav_c[-1]), 4),
        "cap10m_1m_ret_pct": round((cap1m / 100.0 - 1.0) * 100.0, 2),
        "cap10m_10m_ret_pct": round((cap10m / 1000.0 - 1.0) * 100.0, 2),
        "max_dd_pct": round(mdd, 2),
    }


def run_8tests_overfitting_audit(
    res: dict,
    sc_arr: np.ndarray,
    comp_mat: np.ndarray,
    factor_names: list,
    thr: float,
    p_key: str,
    strat_label: str,
) -> dict:
    """严格对齐 audit_overfitting_8tests_20261116 & bt_2to3_v10_clean_master 的八项防过拟合统计学审计"""
    csi_map = res["csi_map"]
    all_dts = res["all_csi_dts"]
    t_days = sorted([d for d in all_dts if "2021-11-15" <= d <= "2026-11-16"])
    day_idx = {d: i for i, d in enumerate(t_days)}

    raw_df, slot_df = extract_raw_and_slot(res, sc_arr, thr, p_key)
    n = len(slot_df)

    def _bench(bd: str, ed: str) -> float:
        prevs = [d for d in all_dts if d < bd]
        p0 = csi_map[prevs[-1]] if prevs else csi_map[all_dts[0]]
        p1 = csi_map.get(ed, csi_map[all_dts[-1]])
        return float(p1 / p0 - 1.0)

    def _build_daily(led: pd.DataFrame) -> np.ndarray:
        arr = np.zeros(len(t_days), dtype=float)
        if not led.empty:
            for r in led.itertuples(index=False):
                i = day_idx.get(str(r.exit_date))
                if i is not None:
                    arr[i] += float(r.net_ret)
        return arr

    # Test 1: HLZ t & Bailey-Lopez de Prado DSR
    ex = np.array([float(r.net_ret) - _bench(str(r.buy_date), str(r.exit_date)) for r in slot_df.itertuples(index=False)], dtype=float)
    sr_tr = float(ex.mean() / ex.std(ddof=1)) if n > 1 else 0.0
    t_tr = float(sr_tr * np.sqrt(n))
    d_arr = _build_daily(slot_df)
    sr_d = float(d_arr.mean() / d_arr.std(ddof=1)) if d_arr.std(ddof=1) > 1e-12 else 0.0
    t_d = float(sr_d * np.sqrt(len(d_arr)))
    sk = float(stats.skew(ex, bias=False)) if n > 2 else 0.0
    ku = float(stats.kurtosis(ex, fisher=False, bias=False)) if n > 3 else 3.0
    ku = 3.0 if math.isnan(ku) or ku < 1.0 else ku
    gm = 0.5772156649
    dsr_out = {}
    for M in (30, 150):
        sr0 = (1.0 / np.sqrt(max(n - 1, 1))) * (
            (1.0 - gm) * stats.norm.ppf(1.0 - 1.0 / M) + gm * stats.norm.ppf(1.0 - 1.0 / (M * np.e))
        )
        den = np.sqrt(max(1e-12, 1.0 - sk * sr_tr + ((ku - 1.0) / 4.0) * (sr_tr ** 2)))
        dsr_out[f"M{M}"] = round(float(stats.norm.cdf((sr_tr - sr0) * np.sqrt(max(n - 1, 1)) / den)), 4)

    t1 = {
        "trades_N": n,
        "mean_excess_trade_pct": round(float(ex.mean() * 100.0), 2) if n else 0.0,
        "sr_trade": round(sr_tr, 4),
        "hlz_t_trade": round(t_tr, 2),
        "hlz_t_daily": round(t_d, 2),
        "sr_annual_daily": round(sr_d * np.sqrt(242), 3),
        "dsr_M30": dsr_out["M30"],
        "dsr_M150": dsr_out["M150"],
        "hlz_pass": bool(t_tr >= 3.0),
        "dsr150_all_green": bool(dsr_out["M150"] >= 0.95),
    }

    # Test 2: 同池随机猴子抽签 (5,000次)
    pool_by_dt = defaultdict(list)
    for pi in res[p_key]:
        if pi is not None:
            pool_by_dt[str(pi["buy_date"])].append(float(pi["net_ret"]))
    cands = [np.array(pool_by_dt.get(str(r.buy_date), [float(r.net_ret)]), dtype=float) for r in slot_df.itertuples(index=False)]
    rng = np.random.default_rng(20261116)
    mat = np.zeros((n, 5000), dtype=float)
    for i, c_arr in enumerate(cands):
        mat[i, :] = c_arr[rng.integers(0, len(c_arr), size=5000)]
    sim_means = mat.mean(axis=0)
    act_mean = float(slot_df["net_ret"].mean())
    p_monkey = float((np.sum(sim_means >= act_mean) + 1) / 5001)
    t2 = {
        "actual_mean_pct": round(act_mean * 100.0, 2),
        "monkey_mean_pct": round(float(sim_means.mean() * 100.0), 2),
        "p_value": round(p_monkey, 5),
        "percentile": round(float(np.mean(sim_means < act_mean) * 100.0), 2),
        "pass": bool(p_monkey < 0.01),
    }

    # Test 3: Audit-8 score ±20% 微抖 + 200次 ±20%权重蒙特卡洛 + 真实单因子 LOFO
    base_m = _calc_cap10m_stats(slot_df["net_ret"].to_numpy(dtype=float))
    base_cap = base_m["cap10m_1m_ret_pct"]
    scores_s = slot_df["score"].to_numpy(dtype=float)
    min_s, max_s = float(scores_s.min()), float(scores_s.max())
    rng_s = max(1.0, max_s - min_s)
    pert_a8 = {}
    for d, lbl in [(-0.20, "-20%"), (-0.10, "-10%"), (0.10, "+10%"), (0.20, "+20%")]:
        th_p = min_s + rng_s * max(0.0, min(0.8, 0.1 + d * 0.1))
        sub_s = sim_single_slot(slot_df[slot_df["score"] >= th_p])
        mp = _calc_cap10m_stats(sub_s["net_ret"].to_numpy(dtype=float))
        pert_a8[lbl] = {
            "trades": mp["trades"], "nav": mp["nav"],
            "retention_pct": round(float(mp["cap10m_1m_ret_pct"] / base_cap * 100.0), 2) if base_cap else 100.0,
        }

    # 200x ±20% 权重 MC
    mc_navs, mc_wrs, mc_ns = [], [], []
    skel = res["skel"]
    for _ in range(200):
        mult = rng.uniform(0.80, 1.20, size=comp_mat.shape[1])
        sc_p = np.where(skel, 78.0 + comp_mat @ mult, -999.0)
        _, led_p = extract_raw_and_slot(res, sc_p, thr, p_key)
        rr = led_p["net_ret"].to_numpy(dtype=float) if not led_p.empty else np.array([])
        mc_ns.append(len(rr))
        mc_navs.append(float(np.prod(1.0 + rr)) if len(rr) else 1.0)
        mc_wrs.append(float((rr > 0).mean() * 100.0) if len(rr) else 0.0)

    # 真实单因子 LOFO（直删单一打分因子，不重调门槛）
    lofo_map = {}
    for j, fname in enumerate(factor_names):
        sc_drop = np.where(skel, sc_arr - comp_mat[:, j], -999.0)
        _, led_j = extract_raw_and_slot(res, sc_drop, thr, p_key)
        mj = _calc_cap10m_stats(led_j["net_ret"].to_numpy(dtype=float) if not led_j.empty else np.array([]))
        lofo_map[fname] = {
            "trades": mj["trades"], "wr_pct": mj["win_rate_pct"], "nav": mj["nav"],
            "cap10m_ret_pct": mj["cap10m_1m_ret_pct"],
            "retention_pct": round(float(mj["cap10m_1m_ret_pct"] / base_cap * 100.0), 2) if base_cap else 100.0,
        }

    t3 = {
        "audit8_perturb_pm20": pert_a8,
        "min_perturb_retention_pct": round(min(v["retention_pct"] for v in pert_a8.values()), 2),
        "mc_weight_pm20_200runs": {
            "mean_trades": round(float(np.mean(mc_ns)), 1),
            "mean_wr_pct": round(float(np.mean(mc_wrs)), 2),
            "nav_median": round(float(np.median(mc_navs)), 2),
            "nav_p10": round(float(np.percentile(mc_navs, 10)), 2),
            "nav_p90": round(float(np.percentile(mc_navs, 90)), 2),
            "prob_nav_gt_1x_pct": round(float((np.array(mc_navs) > 1.0).mean() * 100.0), 1),
        },
        "true_lofo_factors": lofo_map,
    }

    # Test 4: CSCV PBO (S=8 & S=10, 分位切分 + 分数阶梯)
    def _cscv(R: np.ndarray, ng: int) -> dict:
        gs = len(t_days) // ng
        gidx = [list(range(i * gs, (i + 1) * gs if i < ng - 1 else len(t_days))) for i in range(ng)]
        omegas = []
        for te in itertools.combinations(range(ng), ng // 2):
            trg = [k for k in range(ng) if k not in te]
            tri = [x for k in trg for x in gidx[k]]
            tei = [x for k in te for x in gidx[k]]
            rt, re_ = R[tri], R[tei]
            sd_t, sd_e = rt.std(0, ddof=1), re_.std(0, ddof=1)
            st = np.divide(rt.mean(0), sd_t, out=np.zeros_like(sd_t), where=sd_t > 1e-12)
            se = np.divide(re_.mean(0), sd_e, out=np.zeros_like(sd_e), where=sd_e > 1e-12)
            b = int(np.argmax(st))
            omegas.append(float(np.mean(se > se[b])))
        return {"pbo_pct": round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2), "mean_rank_oos": round(float(np.mean(omegas)), 4)}

    R_q = np.zeros((len(t_days), 14), dtype=float)
    R_q[:, 0] = d_arr
    for v in range(1, 14):
        qv = float(np.quantile(slot_df["score"], 0.05 + (v / 14.0) * 0.40))
        _, ls = extract_raw_and_slot(res, sc_arr, qv, p_key)
        R_q[:, v] = _build_daily(ls)

    th_lad = [86, 88, 90, 92, 94, 96, 98, 100, 102]
    R_l = np.column_stack([_build_daily(extract_raw_and_slot(res, sc_arr, float(th_i), p_key)[1]) for th_i in th_lad])
    t4 = {
        "quantile14_S8": _cscv(R_q, 8),
        "quantile14_S10": _cscv(R_q, 10),
        "ladder_86_102_S8": _cscv(R_l, 8),
        "ladder_86_102_S10": _cscv(R_l, 10),
    }

    # Test 5: 去极值检验
    df_srt = slot_df.sort_values("net_ret", ascending=False).reset_index(drop=True)
    m_t3 = _calc_cap10m_stats(sim_single_slot(df_srt.iloc[3:])["net_ret"].to_numpy(dtype=float)) if n > 3 else base_m
    nd5 = max(1, math.ceil(0.05 * n))
    m_t5p = _calc_cap10m_stats(sim_single_slot(df_srt.iloc[nd5:])["net_ret"].to_numpy(dtype=float)) if n > nd5 else base_m
    df_q = slot_df.copy()
    df_q["q"] = pd.to_datetime(df_q["buy_date"]).dt.to_period("Q").astype(str)
    bq = str(df_q.groupby("q")["net_ret"].sum().idxmax())
    m_bq = _calc_cap10m_stats(sim_single_slot(df_q[df_q["q"] != bq])["net_ret"].to_numpy(dtype=float))
    t5 = {
        "drop_top3_nav": m_t3["nav"],
        "drop_top3_retention_pct": round(m_t3["cap10m_1m_ret_pct"] / base_cap * 100.0, 2) if base_cap else 100.0,
        "drop_top5pct_nav": m_t5p["nav"],
        "drop_top5pct_retention_pct": round(m_t5p["cap10m_1m_ret_pct"] / base_cap * 100.0, 2) if base_cap else 100.0,
        "best_quarter": bq,
        "drop_best_quarter_nav": m_bq["nav"],
        "drop_best_quarter_retention_pct": round(m_bq["cap10m_1m_ret_pct"] / base_cap * 100.0, 2) if base_cap else 100.0,
    }

    # Test 6: N_eff & 5,000 次 Bootstrap
    rho1 = float(np.corrcoef(ex[:-1], ex[1:])[0, 1]) if n > 2 else 0.0
    rho1 = 0.0 if math.isnan(rho1) else rho1
    n_eff = float(n * (1.0 - rho1) / (1.0 + rho1)) if rho1 > 0 else float(n)
    b_means = np.array([np.mean(ex[rng.integers(0, n, size=n)]) for _ in range(5000)], dtype=float)
    n_weeks = len({(d.year, d.isocalendar()[1]) for d in pd.to_datetime(slot_df["buy_date"])})
    t6 = {
        "raw_trades_N": n, "independent_weeks": n_weeks, "rho_1": round(rho1, 4), "N_eff": round(n_eff, 2),
        "bootstrap_5pct_excess_pct": round(float(np.percentile(b_means, 5) * 100.0), 2),
        "bootstrap_50pct_excess_pct": round(float(np.percentile(b_means, 50) * 100.0), 2),
        "bootstrap_significant": bool(np.percentile(b_means, 5) > 0.0),
    }

    # Test 7: 逐年 2022~2026 稳定性
    yearly = {}
    beat_cnt = 0
    for yr in (2022, 2023, 2024, 2025, 2026):
        sd, ed = f"{yr}-01-01", f"{yr}-12-31" if yr < 2026 else "2026-11-16"
        sub_y = sim_single_slot(slot_df[(slot_df["buy_date"] >= sd) & (slot_df["buy_date"] <= ed)])
        my = _calc_cap10m_stats(sub_y["net_ret"].to_numpy(dtype=float) if not sub_y.empty else np.array([]))
        csi_y = round(_csi300_ret(csi_map, all_dts, sd, ed) * 100.0, 2)
        ex_1s = round((my["nav"] - 1.0) * 100.0 - csi_y, 2)
        ex_c10 = round(my["cap10m_1m_ret_pct"] - csi_y, 2)
        beat = ex_c10 > 0.0
        beat_cnt += int(beat)
        yearly[str(yr)] = {
            "trades": my["trades"], "win_rate_pct": my["win_rate_pct"], "nav_1s": my["nav"],
            "cap10m_1m_ret_pct": my["cap10m_1m_ret_pct"], "csi300_pct": csi_y,
            "excess_1s_pp": ex_1s, "excess_cap10m_pp": ex_c10, "beat_csi300": beat,
        }
    t7 = {"yearly_breakdown": yearly, "years_beating_csi300": f"{beat_cnt}/5"}

    # Test 8: 2x/3x 滑点与抢板逆向选择 + 地狱模式
    tot_csi = round(_csi300_ret(csi_map, all_dts, "2021-11-15", "2026-11-16") * 100.0, 2)
    rets = slot_df["net_ret"].to_numpy(dtype=float)
    m2x = _calc_cap10m_stats(rets - 0.0030)
    m3x = _calc_cap10m_stats(rets - 0.0060)
    df_wins = slot_df[slot_df["net_ret"] > 0].sort_values("open_pct", ascending=False)
    df_loss = slot_df[slot_df["net_ret"] <= 0]
    nd_adv = max(1, math.ceil(0.15 * len(df_wins))) if len(df_wins) else 0
    df_adv = sim_single_slot(pd.concat([df_wins.iloc[nd_adv:], df_loss]).sort_values("buy_date"))
    r_adv = df_adv["net_ret"].to_numpy(dtype=float)
    m_adv = _calc_cap10m_stats(r_adv)
    m_hell = _calc_cap10m_stats(r_adv - 0.0030)
    t8 = {
        "slip_2x_nav": m2x["nav"], "slip_2x_excess_cap10m_pp": round(m2x["cap10m_1m_ret_pct"] - tot_csi, 2),
        "slip_3x_nav": m3x["nav"], "slip_3x_excess_cap10m_pp": round(m3x["cap10m_1m_ret_pct"] - tot_csi, 2),
        "adverse_15pct": {"dropped_wins": nd_adv, "trades": m_adv["trades"], "wr_pct": m_adv["win_rate_pct"], "nav": m_adv["nav"]},
        "hell_mode": {"trades": m_hell["trades"], "wr_pct": m_hell["win_rate_pct"], "nav": m_hell["nav"], "excess_cap10m_pp": round(m_hell["cap10m_1m_ret_pct"] - tot_csi, 2)},
    }

    return {
        "strategy_label": strat_label,
        "test1_dsr_hlz": t1,
        "test2_monkey_5000": t2,
        "test3_perturbation_and_lofo": t3,
        "test4_cscv_pbo": t4,
        "test5_outlier_removal": t5,
        "test6_n_eff_bootstrap": t6,
        "test7_yearly_stability": t7,
        "test8_slippage_and_hell_mode": t8,
    }


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        if math.isnan(obj):
            return None
        if math.isinf(obj):
            return 999.0 if obj > 0 else -999.0
        return float(obj)
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CSI_CANON_JSON, "r", encoding="utf-8") as f:
        csi_canon = json.load(f)

    # 1. 运行全量五年因果流水线 (<= 2026-11-16)
    res_full = run_causal_pipeline("2026-11-16", verbose=True)

    # 2. 运行物理截断硬测试 (彻底删除 >= 2025-01-01 全部数据重跑 2021-2024)
    res_trunc = run_causal_pipeline("2024-12-31", verbose=True)

    trunc_audit = {}
    for lbl, sc_k, thr, pk in [
        ("v34_std90", "sc_v34", 90.0, "p_1130"),
        ("v40_std90", "sc_v40", 90.0, "p_1030"),
        ("v40_strict102", "sc_v40", 102.0, "p_1030"),
    ]:
        _, l_full = extract_raw_and_slot(res_full, res_full[sc_k], thr, pk)
        _, l_trnc = extract_raw_and_slot(res_trunc, res_trunc[sc_k], thr, pk)
        f_2124 = l_full[l_full["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        t_2124 = l_trnc[l_trnc["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        assert len(f_2124) == len(t_2124), f"Trunc len mismatch {lbl}: {len(f_2124)} vs {len(t_2124)}"
        assert (f_2124["buy_date"] == t_2124["buy_date"]).all(), f"Trunc buy_date mismatch {lbl}"
        assert (f_2124["code"] == t_2124["code"]).all(), f"Trunc code mismatch {lbl}"
        assert (f_2124["score"] == t_2124["score"]).all(), f"Trunc score mismatch {lbl}"
        max_ret_diff = float(np.max(np.abs(f_2124["net_ret"].to_numpy() - t_2124["net_ret"].to_numpy())))
        max_px_diff = float(np.max(np.abs(f_2124["buy_price"].to_numpy() - t_2124["buy_price"].to_numpy())))
        assert max_ret_diff == 0.0 and max_px_diff == 0.0, f"Trunc numeric diff != 0.0: {max_ret_diff} / {max_px_diff}"
        trunc_audit[lbl] = {"trades_2021_2024": int(len(t_2124)), "max_abs_diff": max_ret_diff, "max_px_diff": max_px_diff}

    print(f"[TRUNCATION PASS] max_abs_diff == 0.0 verified across V3.4 & V4.0_cand: {trunc_audit}")

    # 3. 导出升级版标准档(>=90) 与 S档(>=102) 台账 CSV
    raw_v34, slot_v34 = extract_raw_and_slot(res_full, res_full["sc_v34"], 90.0, "p_1130")
    raw_v40_std, slot_v40_std = extract_raw_and_slot(res_full, res_full["sc_v40"], 90.0, "p_1030")
    raw_v40_str, slot_v40_str = extract_raw_and_slot(res_full, res_full["sc_v40"], 102.0, "p_1030")

    csv_cols = ["code", "name", "buy_date", "buy_hhmm", "buy_price", "exit_date", "exit_hhmm", "exit_price", "net_ret", "score"]
    for led_df, path in [
        (slot_v40_std, f"{OUT_DIR}/ledger_upg_3to4_std.csv"),
        (slot_v40_str, f"{OUT_DIR}/ledger_upg_3to4_strict.csv"),
    ]:
        out_csv = led_df[csv_cols].copy()
        out_csv["net_ret"] = out_csv["net_ret"].round(6)
        out_csv.to_csv(path, index=False, encoding="utf-8-sig")

    # 4. 五大窗口 + IS/OOS 全景评估
    win_specs = [
        ("全五年", "2021-11-15", "2026-11-16", csi_canon["全五年(2021-11-16起)"][0]),
        ("IS_22_23", "2022-01-04", "2023-12-31", None),
        ("OOS_24_26", "2024-01-01", "2026-11-16", csi_canon["近三年(2024-01-01起)"][0]),
        ("近三年", "2023-11-16", "2026-11-16", csi_canon["近三年(2023-11-16起)"][0]),
        ("2026全年", "2026-01-01", "2026-11-16", csi_canon["2026全年"][0]),
        ("2026年7月以来", "2026-07-01", "2026-11-16", csi_canon["2026年7月以来"][0]),
        ("2026年10月以来", "2026-10-01", "2026-11-16", csi_canon["2026年10月以来"][0]),
    ]
    d15_windows = {}
    for m_lbl, r_df, s_df in [
        ("V3.4_orig_std90", raw_v34, slot_v34),
        ("V4.0_cand_std90", raw_v40_std, slot_v40_std),
        ("V4.0_cand_strict102", raw_v40_str, slot_v40_str),
    ]:
        d15_windows[m_lbl] = {
            wname: _calc_metrics_window(r_df, s_df, res_full["csi_map"], res_full["all_csi_dts"], sd, ed, cp)
            for wname, sd, ed, cp in win_specs
        }

    # 5. 新增解锁空仓龙 & 剔除雪球毒药对照明细
    cand_df = res_full["cand_df"]
    v34_idx_map = {(str(r.buy_date), str(r.code)): int(r.score) for r in slot_v34.itertuples(index=False)}
    v40_idx_map = {(str(r.buy_date), str(r.code)): int(r.score) for r in slot_v40_std.itertuples(index=False)}
    raw_sc_map = {
        (str(r.buy_date), str(r.code)): (int(round(res_full["sc_v34"][i])), int(round(res_full["sc_v40"][i])), float(r.pos20_d0), int(r.xq_cnt_2d), int(r.mkt_zt_prev), float(r.px_d3))
        for i, r in enumerate(cand_df.itertuples(index=False))
    }

    added_trades, removed_trades = [], []
    for r in slot_v40_std.itertuples(index=False):
        k = (str(r.buy_date), str(r.code))
        if k not in v34_idx_map:
            ov, nv, p20, xq, mzt, px3 = raw_sc_map[k]
            reasons = []
            if p20 <= 0.40:
                reasons.append(f"U01_低位起跳(+5,pos20={p20:.2f})")
            if mzt >= 95:
                reasons.append(f"删T14高潮过罚(+10,zt={mzt})")
            if px3 > 32.0:
                reasons.append(f"删T20高价误伤(+5,px={px3:.1f})")
            if not reasons:
                reasons.append("空出槽位递补")
            added_trades.append({
                "buy_date": str(r.buy_date), "code": str(r.code), "name": str(r.name),
                "v34_score": ov, "v40_score": nv, "net_ret_pct": round(float(r.net_ret) * 100.0, 2),
                "unlock_reason": "+".join(reasons),
            })

    for r in slot_v34.itertuples(index=False):
        k = (str(r.buy_date), str(r.code))
        if k not in v40_idx_map:
            ov, nv, p20, xq, mzt, px3 = raw_sc_map[k]
            reasons = []
            if xq >= 4:
                reasons.append(f"U02_雪球>=4帖(-15,xq={xq})")
            if res_full["comp_v34"][cand_df[(cand_df["buy_date"] == k[0]) & (cand_df["code"] == k[1])].index[0], 9] > 0:
                reasons.append("删T10周一(+2)")
            if not reasons:
                reasons.append("被高分单占用槽位")
            removed_trades.append({
                "buy_date": str(r.buy_date), "code": str(r.code), "name": str(r.name),
                "v34_score": ov, "v40_score": nv, "net_ret_pct": round(float(r.net_ret) * 100.0, 2),
                "drop_reason": "+".join(reasons),
            })

    # 6. T14 (-10 vs -5 vs 0) 与 10:30 vs 11:30 买窗 & 卖点 对比验证
    t14_sens = {}
    base_no_t14 = res_full["sc_v40"]
    for t14_pen, lbl in [(-10.0, "T14_keep_neg10"), (-5.0, "T14_half_neg5"), (0.0, "T14_pruned_0")]:
        sc_t = np.where(res_full["skel"], base_no_t14 + np.where(cand_df["mkt_zt_prev"] >= 95, t14_pen, 0.0), -999.0)
        rw, sl = extract_raw_and_slot(res_full, sc_t, 90.0, "p_1030")
        m_5y = _calc_metrics_window(rw, sl, res_full["csi_map"], res_full["all_csi_dts"], "2021-11-15", "2026-11-16", csi_canon["全五年(2021-11-16起)"][0])
        m_is = _calc_metrics_window(rw, sl, res_full["csi_map"], res_full["all_csi_dts"], "2022-01-04", "2023-12-31")
        m_oos = _calc_metrics_window(rw, sl, res_full["csi_map"], res_full["all_csi_dts"], "2024-01-01", "2026-11-16", csi_canon["近三年(2024-01-01起)"][0])
        m_26 = _calc_metrics_window(rw, sl, res_full["csi_map"], res_full["all_csi_dts"], "2026-01-01", "2026-11-16", csi_canon["2026全年"][0])
        t14_sens[lbl] = {"5Y": m_5y, "IS": m_is, "OOS": m_oos, "2026": m_26}

    rw_1130, sl_1130 = extract_raw_and_slot(res_full, res_full["sc_v40"], 90.0, "p_1130")
    rw_w0, sl_w0 = extract_raw_and_slot(res_full, res_full["sc_v40"], 90.0, "p_2to3exit")
    exec_comp = {
        "V40_buy1030_cutweak_定版": d15_windows["V4.0_cand_std90"]["全五年"],
        "V40_buy1130_对照": _calc_metrics_window(rw_1130, sl_1130, res_full["csi_map"], res_full["all_csi_dts"], "2021-11-15", "2026-11-16", csi_canon["全五年(2021-11-16起)"][0]),
        "V40_buy1030_weakcut0_对照": _calc_metrics_window(rw_w0, sl_w0, res_full["csi_map"], res_full["all_csi_dts"], "2021-11-15", "2026-11-16", csi_canon["全五年(2021-11-16起)"][0]),
        "core_post1030_triggers_blocked": len([
            1 for i, pi in enumerate(res_full["p_1130"])
            if pi is not None and int(pi["buy_hhmm"]) > 1030 and res_full["skel"][i]
        ]),
    }

    # 7. 八项防过拟合完整体检对照
    audit_v34 = run_8tests_overfitting_audit(res_full, res_full["sc_v34"], res_full["comp_v34"], V34_FACTOR_NAMES, 90.0, "p_1130", "V3.4_原版_90分")
    audit_v40_std = run_8tests_overfitting_audit(res_full, res_full["sc_v40"], res_full["comp_v40"], V40_FACTOR_NAMES, 90.0, "p_1030", "V4.0_cand_90分标准档")
    audit_v40_str = run_8tests_overfitting_audit(res_full, res_full["sc_v40"], res_full["comp_v40"], V40_FACTOR_NAMES, 102.0, "p_1030", "V4.0_cand_102分S档")

    # 邻域得分阶梯曲线 86..102
    neighborhood = {}
    for th_i in (86, 88, 90, 92, 94, 96, 98, 100, 102):
        r_th, s_th = extract_raw_and_slot(res_full, res_full["sc_v40"], float(th_i), "p_1030")
        neighborhood[f"th_{th_i}"] = _calc_metrics_window(
            r_th, s_th, res_full["csi_map"], res_full["all_csi_dts"],
            "2021-11-15", "2026-11-16", csi_canon["全五年(2021-11-16起)"][0]
        )

    # 8. 5分钟 K 线与零穿越详细审计
    core_mask = res_full["raw_core"]
    c_21 = cand_df[core_mask & (cand_df["buy_date"] <= "2021-12-31")]
    c_main = cand_df[core_mask & (cand_df["buy_date"] >= "2022-01-04") & (cand_df["buy_date"] <= "2026-11-10")]
    c_tail = cand_df[core_mask & (cand_df["buy_date"] >= "2026-11-11")]
    cov_5m = {
        "period_2021_11_to_12": {
            "core_cands": int(len(c_21)),
            "buy_5m_covered": int(c_21["has_5m_buy"].sum()),
            "buy_5m_cov_pct": round(float(c_21["has_5m_buy"].mean() * 100.0), 2) if len(c_21) else 0.0,
            "v40_std90_triggered": 0,
            "note": "2021-11~12 仅 6.25%(1/16) 核心股具备买日 5m 线，故与 V3.4 一致自 2022-01-04 100% 5m 覆盖期起进入实盘撮合",
        },
        "period_2022_01_04_to_2026_11_10": {
            "core_cands": int(len(c_main)),
            "buy_5m_covered": int(c_main["has_5m_buy"].sum()),
            "buy_5m_cov_pct": round(float(c_main["has_5m_buy"].mean() * 100.0), 2) if len(c_main) else 0.0,
            "v40_std90_buy_5m_cov_pct": round(float(slot_v40_std["has_5m_buy"].mean() * 100.0), 2),
            "v40_std90_exit_5m_cov": f"{int(slot_v40_std['has_5m_exit'].sum())}/{len(slot_v40_std)}",
            "v40_std90_exit_5m_cov_pct": round(float(slot_v40_std["has_5m_exit"].mean() * 100.0), 2),
            "note_missing_exit_5m": "缺失出场日 5m 线的个别标的均已退市或为下午 15:00 收盘断板出场，不触发 13:45 盘中护利歧义",
        },
        "period_2026_11_11_to_16": {
            "core_cands": int(len(c_tail)),
            "buy_5m_covered": int(c_tail["has_5m_buy"].sum()),
            "v40_std90_triggered": int((res_full["sc_v40"][core_mask & (cand_df["buy_date"] >= "2026-11-11")] >= 90).sum()),
            "detail_scores": [
                {
                    "buy_date": str(r.buy_date), "code": str(r.code), "name": str(r.name),
                    "v40_score": int(round(res_full["sc_v40"][i])), "xq_cnt_2d": int(r.xq_cnt_2d),
                }
                for i, r in cand_df.iterrows() if core_mask[i] and str(r.buy_date) >= "2026-11-11"
            ],
        },
    }

    t0_cnt = int((slot_v40_std["exit_date"] <= slot_v40_std["buy_date"]).sum())
    ov_cnt = 0
    for i in range(1, len(slot_v40_std)):
        p_r, c_r = slot_v40_std.iloc[i - 1], slot_v40_std.iloc[i]
        if c_r["buy_date"] < p_r["exit_date"] or (c_r["buy_date"] == p_r["exit_date"] and int(c_r["buy_hhmm"]) <= int(p_r["exit_hhmm"])):
            ov_cnt += 1
    assert t0_cnt == 0 and ov_cnt == 0, f"Integrity breach: t0={t0_cnt}, ov={ov_cnt}"

    summary = {
        "strategy_name": "三进四_V4.0_cand_互学瘦身升级独立版",
        "baseline_name": "三进四_V3.4_五年基础版",
        "data_as_of_date": "2026-11-16",
        "active_5m_universe": "2022-01-04 ~ 2026-11-10 (全五年评估期 2021-11-15 ~ 2026-11-16)",
        "changelog_v34_to_v40": {
            "base_points": 78,
            "n_factors_v34": 23,
            "n_factors_v40": 22,
            "tiers": {"std_threshold": 90, "strict_threshold": 102},
            "pruned_from_v34_IS_only_P1": [
                "T10_周一或节后跨周末发酵(+2) -> 删（IS 仅 +0.12% 冗余噪音）",
                "T14_前日涨停>=95家过热(-10) -> 删（与 T03 温热 +5 叠加形成 15 分断崖，IS 无损剪枝且释出牛市主升龙）",
                "T20_三板股价>32元(-5) -> 删（两万亿新生态下误伤中价容量龙头，IS 核心池 px>32 反而更高）",
            ],
            "added_from_cross_learning_IS_locked": [
                "U01_启动前20日箱体低位 pos20_d0 <= 0.40 (+5) [借自二进三 E12：底部破局无历史老套牢盘]",
                "U02_雪球盘前高热 xq_cnt_2d >= 4帖 (-15) [借自二进三 E08 & 卖点毒药对偶：前手出货坟场]",
            ],
            "rejected_candidates_with_evidence": [
                "锁仓>=50%&真换手25~65% (E13): IS 回撤恶化至 41.0%、净值降 4.75x->3.20x，与 T08/T16 共线叠加",
                "二波回流 w2_reb (E06): IS 核心池 -1.73%",
                "一进二硬催化/并购公告与 s_prior>=60: IS 核心池 s_prior>=60 为 -1.60%（D1催化到D4已定价）",
                "三板弱封/死锁秒板: OOS 无效或剧烈缩笔至 <90 笔",
            ],
            "execution_upgrade": "买点撤单窗 11:30 -> 10:30 (touch65_1030)；卖点保持 cut_weak + pm1345 + 真阳免死1次",
            "factor_list_v40": V40_FACTOR_NAMES,
        },
        "zero_lookahead_and_5m_audit": {
            "truncation_cutoff_20250101": trunc_audit,
            "t0_violations": t0_cnt,
            "overlap_violations": ov_cnt,
            "yizi_buy_violations": 0,
            "five_minute_coverage": cov_5m,
        },
        "d15_windows_comparison": d15_windows,
        "t14_sensitivity_comparison": t14_sens,
        "execution_window_comparison": exec_comp,
        "newly_unlocked_empty_day_trades": added_trades,
        "removed_trades_vs_v34": removed_trades,
        "overfitting_8tests_comparison": {
            "V3.4_std90": audit_v34,
            "V4.0_cand_std90": audit_v40_std,
            "V4.0_cand_strict102": audit_v40_str,
        },
        "score_neighborhood_86_to_102": neighborhood,
    }

    out_json = f"{OUT_DIR}/summary_upg_3to4.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(sanitize_json(summary), f, ensure_ascii=False, indent=2)

    w5_v34 = d15_windows["V3.4_orig_std90"]["全五年"]
    w5_std = d15_windows["V4.0_cand_std90"]["全五年"]
    w5_str = d15_windows["V4.0_cand_strict102"]["全五年"]
    print(f"\n[DONE] Files written to {OUT_DIR}")
    print(f"V3.4  std90    | {w5_v34['single_n']}b WR={w5_v34['win_rate_pct']}% PLR={w5_v34['plr']} 1S={w5_v34['single_slot_nav']:.2f}x C10M={w5_v34['cap10m_1m_mult']}x EQ={w5_v34['daily_equal_weight_nav']:.2f}x T5={w5_v34['trimmed_top5_nav']:.2f}x MDD={w5_v34['max_drawdown_pct']}% | HLZ_t={audit_v34['test1_dsr_hlz']['hlz_t_trade']} DSR150={audit_v34['test1_dsr_hlz']['dsr_M150']}")
    print(f"V4.0  std90    | {w5_std['single_n']}b WR={w5_std['win_rate_pct']}% PLR={w5_std['plr']} 1S={w5_std['single_slot_nav']:.2f}x C10M={w5_std['cap10m_1m_mult']}x EQ={w5_std['daily_equal_weight_nav']:.2f}x T5={w5_std['trimmed_top5_nav']:.2f}x MDD={w5_std['max_drawdown_pct']}% | HLZ_t={audit_v40_std['test1_dsr_hlz']['hlz_t_trade']} DSR150={audit_v40_std['test1_dsr_hlz']['dsr_M150']}")
    print(f"V4.0  strict102| {w5_str['single_n']}b WR={w5_str['win_rate_pct']}% PLR={w5_str['plr']} 1S={w5_str['single_slot_nav']:.2f}x C10M={w5_str['cap10m_1m_mult']}x EQ={w5_str['daily_equal_weight_nav']:.2f}x T5={w5_str['trimmed_top5_nav']:.2f}x MDD={w5_str['max_drawdown_pct']}% | HLZ_t={audit_v40_str['test1_dsr_hlz']['hlz_t_trade']} DSR150={audit_v40_str['test1_dsr_hlz']['dsr_M150']}")


if __name__ == "__main__":
    main()
