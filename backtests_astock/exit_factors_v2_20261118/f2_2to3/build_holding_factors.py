#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Build strictly causal (PIT) holding-period cross-strategy exit factor cache
for 二进三 V2.0 (`score_v2 >= 84`, covering Std90, Strict96, and Exp84 pools).

Strict PIT guarantees:
1. All LHB, KPL, daily price/vol, index, reg/tox/clarify/IR, and Xueqiu/Guba data
   are physically truncated to <= cutoff_date when cutoff_date is specified.
2. Every decision-day feature at `dec_dt 09:25:00` uses ONLY:
   - Market/stock closes & LHB & micro-tape from <= prev_dt (strictly < dec_dt)
   - Notices, reg, IR Q&A, Xueqiu, Guba strictly < f"{dec_dt} 09:25:00"
   - Live 09:25 auction open prices at `dec_dt 09:25:00`
3. D12 strictly enforced: zero yfinance import; all SQLite opened with ?mode=ro.
"""

import os
import sys
import re
import glob
import json
import time
import pickle
import bisect
import sqlite3
import datetime
import argparse
from collections import defaultdict, Counter

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM}/data"
S2_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s2_2to3_exit"
SANDBOX = f"{SIM}/backtests_astock/sandbox_lab"
OUT_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f2_2to3"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"

CACHE_2TO3_IN = f"{S2_DIR}/_cache_2to3_pit_20261116.pkl"
SUPP_5M_IN = f"{S2_DIR}/_cache_5m_supplement_bs.pkl"

A_DAILY_PQ = f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PQ = f"{DATA_DIR}/cn_hk_price_db/a_delisted_daily.parquet"
KPL_MERGED_JL = f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl"
LHB_BUY_PQ = f"{SIM}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
LHB_SELL_PQ = f"{SIM}/backtest/2026-10-20-lhasa/lhb_sell.parquet"
PQ_REG_TOX = f"{DATA_DIR}/pit_reg_tox_notices_5y_complete.parquet"
DB_NOTICES = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
DB_IR_QA = f"{DATA_DIR}/cninfo_ir_qa_5y_pit.db"
DB_XQ_GB = f"{DATA_DIR}/xueqiu_guba_5y_pit.db"
DB_COMM = f"{DATA_DIR}/astock_community_5y_pit.db"
DB_ZT_TAPE = f"{DATA_DIR}/zt_micro_tape_5y_pit.db"
ZDJK_GLOB = f"{DATA_DIR}/kpl/zdjk/*.json"
HOLDERS_JSON = f"{SANDBOX}/grand_factor_matrix_20261112/pit_top10_all_codes.json"
PART1_PKL = f"{SANDBOX}/high_dragon_scorecard_20261113/part1_cache.pkl"
IDX_JSON = f"{SANDBOX}/index_klines_5y_cache.json"
CSI_CANON_JSON = f"{SIM}/backtests_astock/clean_rebacktest_20261116/csi300_canonical_20261116.json"
CSRC_PIT_CSV = f"{DATA_DIR}/csrc_industry_pit_clean.csv"
CAND_01_PQ = f"{SANDBOX}/grand_factor_matrix_20261112/cand_0to1_firstboard.parquet"

# Regexes aligned with V5.1 / V4.0 / V19 (including 国泰君安 -> 国泰海通 rename in 2025-2026)
RE_LHASA = re.compile(r"(?:拉萨|东方财富证券.*拉萨)")
RE_INST = re.compile(r"机构专用")
RE_DAY_SURF = re.compile(
    r"(?:上塘路|杭州上塘|宜昌沿江大道|宜昌珍珠路|(?:国泰君安|国泰海通).*宜昌|"
    r"佛山|绿景路|季华六路|季华五路|消闲派|苏南|江阴.*营业部|苏州.*营业部|东方财富.*昌都|开源.*西安西大街)"
)
RE_TOP_YOUZI = re.compile(
    r"(?:大连金马路|大连黄河路|六一中路|天津东丽开发区二纬路|北京东直门南大街|北京广渠门内大街|"
    r"上海江苏路|上海建国西路|杭州延安路|兴业证券.*陕西分公司|西安朱雀大街|"
    r"南京太平南路|宁波桑田路|上海宛平南路|上海红宝石路|上海茅台路|宁波和源路|北京长椿街)"
)
RE_QUANT = re.compile(
    r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中金.*上海分公司|中信.*上海分公司|"
    r"高盛|瑞银|开源.*西安西大街|(?:国泰君安|国泰海通).*总部|摩根大通)"
)

REG_INC_RE = re.compile(r"(?:监管工作函|监管函|关注函|重点监控|停牌核查)")
REG_EXC_RE = re.compile(r"(?:ST|回复|回函|延期|核查意见|复牌|募集资金|监事|独立董事|保荐)")
CLARIFY_RE = re.compile(r"(?:澄清|不存在|不涉及|未筹划)")
TOX_RISK_RE = re.compile(r"(?:严重异常波动|风险提示|减持计划|股东减持|立案调查|收到立案|退市风险)")
ABN_RE = re.compile(r"(?:异常波动|严重异常波动)")
NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股",
}


def _time_to_sec(tstr: str) -> float | None:
    if not tstr or len(tstr) < 5 or str(tstr).startswith("99"):
        return None
    parts = str(tstr).strip().split(":")
    try:
        hh, mm = int(parts[0]), int(parts[1])
        ss = int(parts[2]) if len(parts) > 2 else 0
        if hh < 9 or (hh == 9 and mm < 30):
            return 0.0
        if hh < 12:
            return float((hh - 9) * 3600 + (mm - 30) * 60 + ss)
        return float(7200 + (hh - 13) * 3600 + mm * 60 + ss)
    except Exception:
        return None


def _load_full_daily(cutoff_date: str):
    cols = ["date", "ticker", "open", "high", "low", "close", "volume", "amount", "turn", "oshare"]
    flt = (ds.field("date") >= pd.Timestamp("2018-01-01")) & (ds.field("date") <= pd.Timestamp(cutoff_date))
    d1 = ds.dataset(A_DAILY_PQ, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    d2 = ds.dataset(A_DELISTED_PQ, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da = pd.concat([d1, d2], ignore_index=True)
    da["c6"] = da["ticker"].astype(str).str[:6]
    da = da[da["c6"].str.startswith(("00", "60")) & (~da["ticker"].astype(str).str.endswith(".BJ"))].copy()
    da["dt"] = da["date"].dt.strftime("%Y-%m-%d")
    da = da[da["dt"] <= cutoff_date].copy()
    da.sort_values(["c6", "dt"], inplace=True)
    da.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    da.reset_index(drop=True, inplace=True)

    g = da.groupby("c6")
    da["pre_c"] = g["close"].shift(1)
    da["pct"] = da["close"] / da["pre_c"] - 1.0
    da["o_pct"] = da["open"] / da["pre_c"] - 1.0
    da["l_pct"] = da["low"] / da["pre_c"] - 1.0
    da["zt_px"] = np.floor(da["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    da["dt_px"] = np.floor(da["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    da["is_zt"] = (da["pre_c"] > 0) & (da["close"] >= da["zt_px"] - 0.01) & (da["pct"] >= 0.095)
    da["touch_zt"] = (da["pre_c"] > 0) & (da["high"] >= da["zt_px"] - 0.01)
    da["is_dt_exact"] = (da["pre_c"] > 0) & (da["close"] <= da["dt_px"] + 0.001) & (da["pct"] <= -0.095)
    da["is_dt_open"] = (da["pre_c"] > 0) & (da["open"] <= da["dt_px"] + 0.005)
    da["is_yizi"] = da["is_zt"] & (da["open"] >= da["zt_px"] - 0.01) & (da["low"] >= da["zt_px"] - 0.01)
    da["is_yizi_dt"] = da["is_dt_exact"] & (da["open"] <= da["dt_px"] + 0.001) & (da["high"] <= da["dt_px"] + 0.001)

    s_zt = da["is_zt"].astype(int)
    s_shift = g["is_zt"].shift(1).fillna(False).astype(bool)
    da["streak"] = s_zt.groupby([da["c6"], (s_zt != s_shift).cumsum()]).cumsum() * s_zt
    da["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)
    da["prev_is_zt"] = s_shift
    da["prev_is_yizi"] = g["is_yizi"].shift(1).fillna(False).astype(bool)
    da["to_pct"] = da["turn"] * 100.0
    da["mcap"] = da["close"] * da["oshare"] / 1e8
    da["mcap"] = np.where(
        da["mcap"] > 0, da["mcap"],
        np.where(da["turn"] > 0, da["amount"] / da["turn"] / 1e8, 50.0)
    )
    return da


def _build_kpl_causal(da: pd.DataFrame, cutoff_date: str):
    """Causal KPL plate Elo & daily plate member lists strictly <= cutoff_date."""
    kpl_by_dt = {}
    with open(KPL_MERGED_JL, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            obj = json.loads(ln)
            dt_k = obj.get("date", "")
            if dt_k and dt_k <= cutoff_date:
                pls = obj.get("plates", [])
                if sum(len(x.get("stocks", [])) for x in pls) > 0:
                    kpl_by_dt[dt_k] = pls
    kpl_dts = sorted(kpl_by_dt.keys())
    sub = da[da["dt"].isin(set(kpl_dts))][["dt", "c6", "pct", "is_zt", "touch_zt", "streak"]]
    stat_map = {
        (r.dt, r.c6): (float(r.pct), bool(r.is_zt), bool(r.touch_zt), int(r.streak))
        for r in sub.itertuples(index=False) if pd.notna(r.pct)
    }

    elo = defaultdict(lambda: 100.0)
    plate_last_idx = {}
    prev_p = {}
    # Store causal metadata for >= 2021-01-01
    # kpl_stk[(dt, c6)] = {"plate": main_plate, "p_sz": sz, "p_elo": elo_v, "all_plates": [...], "max_stk": max_s}
    # kpl_plate_members[(dt, plate)] = list of c6
    kpl_stk = {}
    kpl_plate_members = {}

    for idx, dt in enumerate(kpl_dts):
        for pn, c6l in prev_p.items():
            t = s = 0
            rs = []
            for c6 in c6l:
                st = stat_map.get((dt, c6))
                if st is not None:
                    rs.append(st[0]); s += int(st[1]); t += int(st[2])
            if t >= 2 and (s / t) < 0.50:
                elo[pn] -= 12.0 * ((t - s) / t)
            elif rs and float(np.mean(rs)) < -0.025:
                elo[pn] -= 10.0
            elif s >= 2 and (s / max(t, 1)) >= 0.70:
                elo[pn] += min(10.0, 5.0 + s * 1.2)
            elif rs and float(np.mean(rs)) > 0.025:
                elo[pn] += 6.0

        for pk in list(elo):
            if idx - plate_last_idx.get(pk, idx) > 3:
                elo[pk] = 100.0 + (elo[pk] - 100.0) * 0.85

        np_p = {}
        day_stk_plates = defaultdict(list)
        for p in kpl_by_dt[dt]:
            pn = p.get("plate", "")
            stks = p.get("stocks", [])
            if not stks or pn in NON_THEME:
                continue
            sz = len(stks)
            plate_last_idx[pn] = idx
            c6l = [str(s[0]).strip()[:6].zfill(6) for s in stks]
            np_p[pn] = c6l
            if dt >= "2020-12-01":
                kpl_plate_members[(dt, pn)] = c6l
                max_stk = max((stat_map.get((dt, c), (0.0, False, False, 0))[3] for c in c6l), default=0)
                for c in c6l:
                    day_stk_plates[c].append((sz, float(elo[pn]), pn, max_stk))

        if dt >= "2020-12-01":
            for c, plist in day_stk_plates.items():
                plist.sort(key=lambda x: (x[0], x[1]), reverse=True)
                best_sz, best_elo, best_pn, best_ms = plist[0]
                kpl_stk[(dt, c)] = {
                    "plate": best_pn,
                    "p_sz": best_sz,
                    "p_elo": best_elo,
                    "max_stk": best_ms,
                    "all_plates": [x[2] for x in plist],
                }
        prev_p = np_p

    return kpl_stk, kpl_plate_members


def _load_lhb_maps(cutoff_date: str, da_amt_map: dict):
    """Load LHB buy/sell deduplicated per day (prefer 1-day board over 3-day board; preserve multiple 机构专用)."""
    cols_b = ["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL", "NET", "EXPLANATION", "TRADE_ID"]
    cols_s = ["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL", "NET", "EXPLANATION", "TRADE_ID"]

    lb = pd.read_parquet(LHB_BUY_PQ, columns=cols_b)
    lb["dt"] = lb["TRADE_DATE"].astype(str).str[:10]
    lb = lb[(lb["dt"] >= "2020-11-01") & (lb["dt"] <= cutoff_date)].copy()
    lb["c6"] = lb["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    lb["is_3d"] = lb["EXPLANATION"].astype(str).str.contains("连续三个交易日", na=False)

    ls = pd.read_parquet(LHB_SELL_PQ, columns=cols_s)
    ls["dt"] = ls["TRADE_DATE"].astype(str).str[:10]
    ls = ls[(ls["dt"] >= "2020-11-01") & (ls["dt"] <= cutoff_date)].copy()
    ls["c6"] = ls["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    ls["is_3d"] = ls["EXPLANATION"].astype(str).str.contains("连续三个交易日", na=False)

    # For each (dt, c6), pick 1-day TRADE_ID(s) if any exist, else 3-day TRADE_ID
    has_1d_b = set(zip(lb.loc[~lb["is_3d"], "dt"], lb.loc[~lb["is_3d"], "c6"]))
    lb = lb[~(lb["is_3d"] & lb.set_index(["dt", "c6"]).index.isin(has_1d_b))].copy()
    lb = lb.drop_duplicates(subset=["dt", "c6", "OPERATEDEPT_NAME", "BUY", "SELL"])

    has_1d_s = set(zip(ls.loc[~ls["is_3d"], "dt"], ls.loc[~ls["is_3d"], "c6"]))
    ls = ls[~(ls["is_3d"] & ls.set_index(["dt", "c6"]).index.isin(has_1d_s))].copy()
    ls = ls.drop_duplicates(subset=["dt", "c6", "OPERATEDEPT_NAME", "BUY", "SELL"])

    buy_by_dc = defaultdict(list)
    for r in lb.itertuples(index=False):
        buy_by_dc[(r.dt, r.c6)].append((str(r.OPERATEDEPT_NAME), float(r.BUY or 0.0), float(r.SELL or 0.0), float(r.NET or 0.0)))

    sell_by_dc = defaultdict(list)
    for r in ls.itertuples(index=False):
        sell_by_dc[(r.dt, r.c6)].append((str(r.OPERATEDEPT_NAME), float(r.BUY or 0.0), float(r.SELL or 0.0), float(r.NET or 0.0)))

    all_keys = set(buy_by_dc.keys()) | set(sell_by_dc.keys())
    lhb_stats = {}
    for k in all_keys:
        dt, c6 = k
        b_rows = buy_by_dc.get(k, [])
        s_rows = sell_by_dc.get(k, [])
        day_amt = max(float(da_amt_map.get(k, 0.0)), 1.0)

        # Unique buy seat names for Lhasa count (consistent with V4.0 / V5.1)
        tot_b = sum(x[1] for x in b_rows)
        lh_b = sum(x[1] for x in b_rows if RE_LHASA.search(x[0]))
        lh_cnt = len({x[0] for x in b_rows if RE_LHASA.search(x[0])})
        lh_ratio = (lh_b / tot_b) if tot_b > 0 else 0.0

        daysurf_buy = any(RE_DAY_SURF.search(x[0]) for x in b_rows)
        top_yz_buy_names = {x[0] for x in b_rows if RE_TOP_YOUZI.search(x[0])}
        top_yz_sell_names = {x[0] for x in s_rows if RE_TOP_YOUZI.search(x[0])}
        top_yz_sell_net_neg = any(RE_TOP_YOUZI.search(x[0]) and x[3] < 0 for x in s_rows)

        # Institutional net across unique (name, buy, sell) rows from combined buy+sell (avoid double counting if same row appears in both)
        seen_inst = set()
        inst_net = 0.0
        inst_cnt = 0
        for nm, bv, sv, nv in (b_rows + s_rows):
            if RE_INST.search(nm):
                sig_t = (round(bv, 1), round(sv, 1))
                if sig_t not in seen_inst:
                    seen_inst.add(sig_t)
                    inst_net += (bv - sv)
                    inst_cnt += 1
        inst_sell_cnt = sum(1 for x in s_rows if RE_INST.search(x[0]))

        # Quant seats
        seen_q = set()
        q_net = 0.0
        q_buy_cnt = 0
        q_sell_cnt = 0
        q_both_t = False
        for nm, bv, sv, nv in b_rows:
            if RE_QUANT.search(nm):
                q_buy_cnt += 1
                if sv > 0 and bv > 0:
                    q_both_t = True
                if nm not in seen_q:
                    seen_q.add(nm)
                    q_net += (bv - sv)
        for nm, bv, sv, nv in s_rows:
            if RE_QUANT.search(nm):
                q_sell_cnt += 1
                if sv > 0 and bv > 0:
                    q_both_t = True
                if nm not in seen_q:
                    seen_q.add(nm)
                    q_net += (bv - sv)

        max_seat_buy = max((x[1] for x in b_rows), default=0.0)
        max_seat_net = max((x[3] for x in b_rows), default=0.0)
        max_seat_buy_amt_ratio = max_seat_buy / day_amt
        max_seat_net_amt_ratio = max_seat_net / day_amt
        max_seat_lhb_share = (max_seat_buy / tot_b) if tot_b > 0 else 0.0

        lhb_stats[k] = {
            "on_lhb": True,
            "lh_cnt": lh_cnt,
            "lh_buy_ratio": lh_ratio,
            "daysurf_buy": daysurf_buy,
            "inst_cnt": inst_cnt,
            "inst_sell_cnt": inst_sell_cnt,
            "inst_net": inst_net,
            "inst_net_sell": (inst_cnt > 0 and inst_net < 0),
            "top_yz_buy_names": top_yz_buy_names,
            "top_yz_sell_names": top_yz_sell_names,
            "top_yz_buy": bool(top_yz_buy_names),
            "top_yz_sell": bool(top_yz_sell_names),
            "top_yz_sell_neg": top_yz_sell_net_neg,
            "max_seat_buy_amt_ratio": max_seat_buy_amt_ratio,
            "max_seat_net_amt_ratio": max_seat_net_amt_ratio,
            "max_seat_lhb_share": max_seat_lhb_share,
            "quant_cnt": len(seen_q),
            "quant_sell_cnt": q_sell_cnt,
            "quant_net": q_net,
            "quant_dump": (q_sell_cnt > 0 and q_net < 0) or q_both_t,
        }
    return lhb_stats


def _load_notices_and_reg(cutoff_date: str, target_c6: set[str]):
    """Load strictly PIT reg, clarify, tox, abnormal, ex_reg, and IR Q&A timestamps <= cutoff_date."""
    end_cut = f"{cutoff_date} 23:59:59"

    # 1. Exchange reg & stock reg from part1_cache (<= min(2026-11-12, cutoff_date)) + pit_reg_tox + cninfo + zdjk
    stk_reg_ts = defaultdict(list)     # c6 -> sorted list of "YYYY-MM-DD HH:MM:SS"
    clarify_ts = defaultdict(list)     # c6 -> sorted list of "YYYY-MM-DD HH:MM:SS"
    tox_ts = defaultdict(list)         # c6 -> sorted list of "YYYY-MM-DD HH:MM:SS"
    abn_ts = defaultdict(list)         # c6 -> sorted list of "YYYY-MM-DD HH:MM:SS"
    ex_reg_raw = {"SH": set(), "SZ": set()}  # (dt10, c6)

    # Use part1_cache up to cutoff_date for historical 2021-2026-11-12 s_reg / ex_reg alignment
    if os.path.exists(PART1_PKL):
        with open(PART1_PKL, "rb") as f:
            pkg = pickle.load(f)
        for c6, dts in pkg[10].items():
            cc = str(c6).zfill(6)
            for dt_x in dts:
                d10 = str(dt_x)[:10]
                if d10 <= cutoff_date and cc in target_c6:
                    stk_reg_ts[cc].append(d10 + " 08:00:00")
        for ex_k in ("SH", "SZ"):
            for idx_e, d_x in enumerate(pkg[11].get(ex_k, [])):
                d10 = str(d_x)[:10]
                if d10 <= cutoff_date:
                    ex_reg_raw[ex_k].add((d10, f"HIST_{ex_k}_{idx_e}"))

    # Supplement & full 2021-2026 from pit_reg_tox_notices_5y_complete.parquet
    rt = pd.read_parquet(PQ_REG_TOX, columns=["sec_code", "pub_datetime_cst", "title"])
    rt["pdt"] = rt["pub_datetime_cst"].astype(str)
    rt = rt[rt["pdt"] <= end_cut].copy()
    for sc, pdt, ti in zip(rt["sec_code"].astype(str), rt["pdt"], rt["title"].astype(str)):
        c6 = sc[:6].zfill(6)
        is_reg = bool(REG_INC_RE.search(ti) and (not REG_EXC_RE.search(ti)))
        if is_reg and c6.startswith(("00", "60")):
            ex_k = "SH" if c6.startswith("60") else "SZ"
            # Supplement after 2026-11-12 (or deduplicated across 7 days later)
            if pdt[:10] > "2026-11-12":
                ex_reg_raw[ex_k].add((pdt[:10], c6))
        if c6 not in target_c6:
            continue
        if is_reg:
            stk_reg_ts[c6].append(pdt)
        if CLARIFY_RE.search(ti):
            clarify_ts[c6].append(pdt)
        if TOX_RISK_RE.search(ti):
            tox_ts[c6].append(pdt)
        if ABN_RE.search(ti):
            abn_ts[c6].append(pdt)

    # Also check cninfo_notices_5y_pit.db for any notices missing from pit_reg_tox (especially 2021/2025/2026)
    con_n = sqlite3.connect(f"file:{DB_NOTICES}?mode=ro", uri=True)
    for sc, pdt, ti in con_n.execute(
        "SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst >= '2020-12-01' AND pub_datetime_cst <= ?",
        (end_cut,),
    ):
        c6 = str(sc)[:6].zfill(6)
        if c6 not in target_c6:
            continue
        pdt_s = str(pdt)
        ts = str(ti or "")
        if REG_INC_RE.search(ts) and (not REG_EXC_RE.search(ts)):
            stk_reg_ts[c6].append(pdt_s)
        if CLARIFY_RE.search(ts):
            clarify_ts[c6].append(pdt_s)
        if TOX_RISK_RE.search(ts):
            tox_ts[c6].append(pdt_s)
        if ABN_RE.search(ts):
            abn_ts[c6].append(pdt_s)
    con_n.close()

    # KPL zdjk JSON files (strictly file date & start_date <= cutoff_date)
    for zf in glob.glob(ZDJK_GLOB):
        bn = os.path.basename(zf)[:8]
        fdt = f"{bn[:4]}-{bn[4:6]}-{bn[6:8]}" if len(bn) == 8 and bn.isdigit() else "1990-01-01"
        if fdt > cutoff_date:
            continue
        try:
            items = json.load(open(zf, encoding="utf-8")).get("List", [])
            for it in items:
                c6 = str(it[0]).zfill(6)
                dt_z = str(it[2])[:10]
                if dt_z <= cutoff_date and c6 in target_c6:
                    stk_reg_ts[c6].append(dt_z + " 08:00:00")
        except Exception:
            pass

    # Dedup timestamps per stock (within same day/title duplicate across DBs)
    def _dedup_ts(mp):
        out = {}
        for c6, lst in mp.items():
            # Dedup exact same day+minute or date
            seen_d = set()
            clean = []
            for x in sorted(set(lst)):
                # Avoid double-counting identical event on same date from part1_cache + parquet
                key = (x[:10], x[11:16] if len(x) >= 16 else "00:00")
                if x[:10] not in seen_d or x[11:16] != "08:00":
                    clean.append(x)
                    seen_d.add(x[:10])
            out[c6] = np.sort(np.array(clean, dtype=str))
        return out

    # For abnormal cnt, keep at most 1 per (c6, date)
    abn_dedup = {}
    for c6, lst in abn_ts.items():
        dts_u = sorted({x[:10]: x for x in sorted(lst)}.values())
        abn_dedup[c6] = np.sort(np.array(dts_u, dtype=str))

    ex_reg_sorted = {}
    for ex_k in ("SH", "SZ"):
        # Deduplicate >2026-11-12 items by 7d per stock, keep historical sorted list
        hist_dts = sorted([d for d, tag in ex_reg_raw[ex_k] if tag.startswith("HIST_")])
        sup_items = sorted([(d, c) for d, c in ex_reg_raw[ex_k] if not tag_is_hist(c)])
        seen_c = {}
        sup_dts = []
        for d, c in sup_items:
            if c not in seen_c or (pd.Timestamp(d) - seen_c[c]).days > 7:
                seen_c[c] = pd.Timestamp(d)
                sup_dts.append(d)
        ex_reg_sorted[ex_k] = np.sort(np.array(sorted(hist_dts + sup_dts), dtype=str))

    # IR Q&A
    con_ir = sqlite3.connect(f"file:{DB_IR_QA}?mode=ro", uri=True)
    ir_map = defaultdict(list)
    for sc, pdt in con_ir.execute(
        "SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE pub_datetime_cst IS NOT NULL AND pub_datetime_cst <= ?",
        (end_cut,),
    ):
        c6 = str(sc)[:6].zfill(6)
        if c6 in target_c6:
            ir_map[c6].append(str(pdt))
    con_ir.close()
    ir_arr = {c6: np.sort(np.unique(v).astype(str)) for c6, v in ir_map.items()}

    return _dedup_ts(stk_reg_ts), _dedup_ts(clarify_ts), _dedup_ts(tox_ts), abn_dedup, ex_reg_sorted, ir_arr


def tag_is_hist(c: str) -> bool:
    return c.startswith("HIST_")


def _load_community_maps(cutoff_date: str, target_c6: set[str]):
    """Load strictly PIT Xueqiu & Guba posts <= cutoff_date 23:59:59 for target_c6."""
    end_cut = f"{cutoff_date} 23:59:59"
    xq_seen = defaultdict(set)
    xq_ts = defaultdict(list)
    gb_seen = defaultdict(set)
    gb_ts = defaultdict(list)

    placeholders = ",".join("?" for _ in target_c6)
    c6_tuple = tuple(sorted(target_c6))

    con_xg = sqlite3.connect(f"file:{DB_XQ_GB}?mode=ro", uri=True)
    for sym, pid, cts in con_xg.execute(
        f"SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE substr(symbol,1,6) IN ({placeholders}) AND created_time_str >= '2020-10-01' AND created_time_str <= ?",
        c6_tuple + (end_cut,),
    ):
        c6 = str(sym)[:6].zfill(6)
        pid_c = str(pid).replace("xq_", "")
        if cts and pid_c not in xq_seen[c6]:
            xq_seen[c6].add(pid_c)
            xq_ts[c6].append(str(cts))

    for sc, pid, pt in con_xg.execute(
        f"SELECT sec_code, post_id, pub_time FROM guba_posts WHERE substr(sec_code,1,6) IN ({placeholders}) AND pub_time >= '2020-10-01' AND pub_time <= ?",
        c6_tuple + (end_cut,),
    ):
        c6 = str(sc)[:6].zfill(6)
        pid_c = str(pid)
        if pt and pid_c not in gb_seen[c6]:
            gb_seen[c6].add(pid_c)
            gb_ts[c6].append(str(pt))
    con_xg.close()

    con_cm = sqlite3.connect(f"file:{DB_COMM}?mode=ro", uri=True)
    for src, sym, pid, pdt in con_cm.execute(
        f"SELECT source, symbol, post_id, pub_datetime_cst FROM community_posts WHERE substr(symbol,1,6) IN ({placeholders}) AND pub_datetime_cst >= '2020-10-01' AND pub_datetime_cst <= ?",
        c6_tuple + (end_cut,),
    ):
        c6 = str(sym)[:6].zfill(6)
        if not pdt:
            continue
        if src == "xueqiu":
            pid_c = str(pid).replace("xq_", "")
            if pid_c not in xq_seen[c6]:
                xq_seen[c6].add(pid_c)
                xq_ts[c6].append(str(pdt))
        else:
            pid_c = str(pid)
            if pid_c not in gb_seen[c6]:
                gb_seen[c6].add(pid_c)
                gb_ts[c6].append(str(pdt))
    con_cm.close()

    xq_arr = {c6: np.sort(np.array(v, dtype=str)) for c6, v in xq_ts.items()}
    gb_arr = {c6: np.sort(np.array(v, dtype=str)) for c6, v in gb_ts.items()}
    return xq_arr, gb_arr


def _cnt_ts(arr: np.ndarray | None, t0: str, t1: str) -> int:
    if arr is None or len(arr) == 0:
        return 0
    return int(np.searchsorted(arr, t1, side="left") - np.searchsorted(arr, t0, side="left"))


def build_cache(cutoff_date: str = "2026-11-16", out_name: str = "_cache_holding_factors_full.pkl"):
    t0 = time.time()
    print(f"[build_holding_factors] Building PIT cache (cutoff={cutoff_date})...")

    d = pickle.load(open(CACHE_2TO3_IN, "rb"))
    supp = pickle.load(open(SUPP_5M_IN, "rb"))
    g_all = d["gated_all"].copy()
    sub84 = g_all[g_all["score_v2"] >= 84].copy().reset_index(drop=True)
    if cutoff_date < "2026-11-16":
        sub84 = sub84[sub84["buy_date"] <= cutoff_date].copy().reset_index(drop=True)

    target_c6 = set(sub84["code"].astype(str).str.zfill(6))
    print(f"  Signals >=84: {len(sub84)}, unique stocks: {len(target_c6)}")

    # 1. Full daily price table <= cutoff_date (active + delisted)
    da = _load_full_daily(cutoff_date)
    all_dts = sorted(da["dt"].unique())
    dt_idx = {x: i for i, x in enumerate(all_dts)}

    # Index klines truncated <= cutoff_date
    idx_raw = json.load(open(IDX_JSON, encoding="utf-8"))
    csi_map = {k: float(v) for k, v in idx_raw["sh000300"].items() if k <= cutoff_date}
    idx_sh = {k: float(v) for k, v in idx_raw["sh000002"].items() if k <= cutoff_date}
    idx_sz = {k: float(v) for k, v in idx_raw["sz399107"].items() if k <= cutoff_date}
    # Forward-fill missing dates if any
    for mp in (csi_map, idx_sh, idx_sz):
        lv = None
        for dt_k in all_dts:
            if dt_k in mp:
                lv = mp[dt_k]
            elif lv is not None:
                mp[dt_k] = lv

    # 2. Causal KPL plate map
    kpl_stk, kpl_plate_members = _build_kpl_causal(da, cutoff_date)

    # 3. Daily ecosystem & 09:25 auction lookup across full market
    print("  Computing daily market ecosystem & 09:25 mates open...")
    env_day = {}
    brk_dt_hist = []
    hd_reb_hist = []
    prev_broken_hd = []  # c6 list of prev_streak>=4 & ~is_zt on yesterday

    # Fast lookup for daily open_pct, is_zt, is_dt_open, streak, amount, turn
    da_2020 = da[da["dt"] >= "2020-11-01"].copy()
    da_amt_map = {(r.dt, r.c6): float(r.amount) for r in da_2020[["dt", "c6", "amount"]].itertuples(index=False) if pd.notna(r.amount)}
    day_open_dt_map = {}  # (dt, c6) -> (o_pct, is_dt_open, is_zt, prev_is_zt, prev_streak, streak)

    for r in da_2020[["dt", "c6", "o_pct", "is_dt_open", "is_zt", "prev_is_zt", "prev_streak", "streak"]].itertuples(index=False):
        day_open_dt_map[(r.dt, r.c6)] = (
            float(r.o_pct) if pd.notna(r.o_pct) else 0.0,
            bool(r.is_dt_open),
            bool(r.is_zt),
            bool(r.prev_is_zt),
            int(r.prev_streak),
            int(r.streak),
        )

    # Pre-group da_2020 by dt for fast daily env
    for dt_k, grp in da_2020.groupby("dt", sort=True):
        zt_g = grp[grp["is_zt"]]
        n_zt = int(len(zt_g))
        n_touch = int(grp["touch_zt"].sum())
        seal_r = float(n_zt / n_touch) if n_touch > 0 else 0.55
        max_b = int(zt_g["streak"].max()) if n_zt > 0 else 0
        b3_dt = int(((grp["prev_streak"] >= 3) & grp["is_dt_exact"]).sum())

        # Market-wide open avg at dt_k 09:25 of yesterday's ZT & yesterday's 1-board
        prev_zt_g = grp[grp["prev_is_zt"] & grp["o_pct"].notna()]
        prev_fb_g = grp[(grp["prev_streak"] == 1) & grp["o_pct"].notna()]
        mkt_zt_open_avg = float(prev_zt_g["o_pct"].mean()) if not prev_zt_g.empty else 0.0
        mkt_fb_open_avg = float(prev_fb_g["o_pct"].mean()) if not prev_fb_g.empty else 0.0

        # Trailing 10d high-dragon broken limit-down rate (V5.1 brk_r10)
        ge4_brk = grp[(grp["prev_streak"] >= 4) & (~grp["is_zt"])]
        brk_dt_hist.append((int(ge4_brk["is_dt_exact"].sum()), int(len(ge4_brk))))
        w10_b = brk_dt_hist[-10:]
        brk_dt_r10 = float(sum(x[0] for x in w10_b) / max(1, sum(x[1] for x in w10_b)))

        # Trailing 10d true next-day rebound rate among previous day's broken >=4b
        if prev_broken_hd:
            sub_reb = grp[grp["c6"].isin(prev_broken_hd)]
            reb_ok = int((sub_reb["pct"] > 0).sum())
            reb_tot = int(len(sub_reb))
            hd_reb_hist.append((reb_ok, reb_tot))
        else:
            hd_reb_hist.append((0, 0))
        w10_r = hd_reb_hist[-10:]
        hd_reb_r10 = float(sum(x[0] for x in w10_r) / max(1, sum(x[1] for x in w10_r))) if sum(x[1] for x in w10_r) > 0 else 0.30
        prev_broken_hd = ge4_brk["c6"].tolist()

        # CSI 1d & 5d
        p_idx = dt_idx[dt_k]
        c_now = csi_map.get(dt_k, 4000.0)
        c_1 = csi_map.get(all_dts[max(0, p_idx - 1)], c_now)
        c_5 = csi_map.get(all_dts[max(0, p_idx - 5)], c_now)
        csi_1d = float(c_now / c_1 - 1.0) if c_1 > 0 else 0.0
        csi_5d = float(c_now / c_5 - 1.0) if c_5 > 0 else 0.0

        env_day[dt_k] = {
            "n_zt": n_zt,
            "seal_rate": seal_r,
            "max_board": max_b,
            "b3_dt": b3_dt,
            "brk_dt_r10": brk_dt_r10,
            "hd_reb_r10": hd_reb_r10,
            "mkt_zt_open_avg": mkt_zt_open_avg,
            "mkt_fb_open_avg": mkt_fb_open_avg,
            "csi_1d": csi_1d,
            "csi_5d": csi_5d,
        }

    # 4. LHB maps (full market <= cutoff_date)
    print("  Loading LHB buy/sell...")
    lhb_stats = _load_lhb_maps(cutoff_date, da_amt_map)

    # 5. Notices, Reg, Clarify, Tox, Abnormal, Ex_Reg, IR Q&A
    print("  Loading Notices / Reg / Tox / IR...")
    stk_reg_ts, clarify_ts, tox_ts, abn_ts, ex_reg_sorted, ir_arr = _load_notices_and_reg(cutoff_date, target_c6)

    # 6. Community Xueqiu & Guba
    print("  Loading Xueqiu & Guba...")
    xq_arr, gb_arr = _load_community_maps(cutoff_date, target_c6)

    # 7. Micro tape <= cutoff_date
    print("  Loading zt_micro_tape...")
    con_tp = sqlite3.connect(f"file:{DB_ZT_TAPE}?mode=ro", uri=True)
    df_tp = pd.read_sql_query(
        "SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape WHERE trade_date >= '2020-12-01' AND trade_date <= ?",
        con_tp, params=(cutoff_date,),
    )
    con_tp.close()
    tape_map = {}
    for r in df_tp.itertuples(index=False):
        c6 = str(r.sec_code)[:6].zfill(6)
        fst = str(r.first_seal_time or "99:99:99")
        sec = _time_to_sec(fst)
        sa = float(r.seal_amount or 0.0)
        obc = int(r.open_board_count if pd.notna(r.open_board_count) else 0)
        amt_d = da_amt_map.get((str(r.trade_date), c6), 1e8)
        tape_map[(str(r.trade_date), c6)] = {
            "fst": fst,
            "seal_sec": sec if sec is not None else 99999.0,
            "seal_amt": sa,
            "seal_amt_ratio": sa / max(amt_d, 1.0),
            "open_cnt": obc,
        }

    # 8. Build V4.0 (3to4) counterparty info for all D4 attempts where D3 was sealed_3b
    print("  Computing 3to4 V4.0 counterparty scores for sealed D3 candidates...")
    with open(HOLDERS_JSON, encoding="utf-8") as f:
        holders_raw = json.load(f)
    holders_map = {
        c6: [rec for rec in lst if str(rec[0])[:10] <= cutoff_date]
        for c6, lst in holders_raw.items()
    }

    # First-board plate stats for 3to4 T04/T19 (causally computed from da_2020 + kpl_stk!)
    # On each day d_prev, find all first-board ZT stocks (streak == 1), look up their next-day (d_next) open_pct & is_yizi
    fb_rows = da_2020[da_2020["streak"] == 1][["dt", "c6"]].copy()
    fb_next_info = {}
    for d_i in range(len(all_dts) - 1):
        d_prev, d_nxt = all_dts[d_i], all_dts[d_i + 1]
        if d_prev < "2020-12-01":
            continue
        # Only stocks that were streak==1 on d_prev
        pass

    # Build (d_nxt, plate) -> (fb_ho_cnt, fb_yz_cnt) and (d_nxt, plate) -> peers_open_avg
    # Also compute market-wide 3-board buyable max open_pct on each d_nxt for T13 is_top1_3b_open!
    b3_day_max_op = {}
    for d_i in range(len(all_dts) - 1):
        d_prev, d_nxt = all_dts[d_i], all_dts[d_i + 1]
        if d_prev < "2020-12-01":
            continue
    da_sub_3b = da_2020[(da_2020["prev_streak"] == 3) & (~da_2020["prev_is_yizi"]) & (da_2020["open"] < da_2020["zt_px"] - 0.011) & (da_2020["open"] > da_2020["dt_px"] + 0.011) & (da_2020["pre_c"] > 0)]
    b3_day_max_op = da_sub_3b.groupby("dt")["o_pct"].max().to_dict()

    # Precompute daily FB and ZT plate open stats on d_nxt using kpl_plate_members on d_prev
    # Cache on demand during target holding days!

    # 9. Build target stock daily records & holding-day factor dictionary!
    print("  Assembling per-holding-day factor table for all >=84 signals...")
    da_tgt = da[da["c6"].isin(target_c6)].copy().sort_values(["c6", "dt"]).reset_index(drop=True)
    # Add rolling pre5 / pre20 amount and ma5 for target stocks
    gt = da_tgt.groupby("c6")
    da_tgt["ma5"] = gt["close"].transform(lambda s: s.rolling(5, min_periods=3).mean())
    da_tgt["amt_ma5_prev"] = gt["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    da_tgt["amt_ma20_prev"] = gt["amount"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).mean())
    da_tgt["d2_open"] = gt["open"].shift(1)
    da_tgt["d2_close"] = gt["close"].shift(1)

    tgt_day_map = {}
    for r in da_tgt.itertuples(index=False):
        tgt_day_map[(r.c6, r.dt)] = {
            "open": float(r.open), "high": float(r.high), "low": float(r.low), "close": float(r.close),
            "pre_c": float(r.pre_c) if pd.notna(r.pre_c) else float(r.close),
            "zt_px": float(r.zt_px) if pd.notna(r.zt_px) else 9999.0,
            "dt_px": float(r.dt_px) if pd.notna(r.dt_px) else 0.0,
            "o_pct": float(r.o_pct) if pd.notna(r.o_pct) else 0.0,
            "l_pct": float(r.l_pct) if pd.notna(r.l_pct) else 0.0,
            "pct": float(r.pct) if pd.notna(r.pct) else 0.0,
            "to_pct": float(r.to_pct) if pd.notna(r.to_pct) else 0.0,
            "amount": float(r.amount) if pd.notna(r.amount) else 1e8,
            "mcap": float(r.mcap) if pd.notna(r.mcap) else 50.0,
            "is_zt": bool(r.is_zt),
            "is_dt_exact": bool(r.is_dt_exact),
            "is_yizi": bool(r.is_yizi),
            "is_yizi_dt": bool(r.is_yizi_dt),
            "streak": int(r.streak),
            "ma5": float(r.ma5) if pd.notna(r.ma5) else float(r.close),
            "amt_ma5_prev": float(r.amt_ma5_prev) if pd.notna(r.amt_ma5_prev) else float(r.amount),
            "amt_ma20_prev": float(r.amt_ma20_prev) if pd.notna(r.amt_ma20_prev) else float(r.amount),
            "d2_open": float(r.d2_open) if pd.notna(r.d2_open) else float(r.open),
            "d2_close": float(r.d2_close) if pd.notna(r.d2_close) else float(r.close),
        }

    # Pre-index mates & plate stats per (prev_dt, dec_dt, plate)
    zt_by_dt = {}
    fb_by_dt = {}
    for dt_k, grp in da_2020[da_2020["is_zt"]].groupby("dt"):
        zt_by_dt[dt_k] = grp["c6"].tolist()
        fb_by_dt[dt_k] = grp[grp["streak"] == 1]["c6"].tolist()

    # Precompute deterministic exchange abnormal volatility trigger events (2d/3d cum excess vs index >= +20%)
    idx_sh_s = {d: float(idx_sh.get(d, 1.0)) for d in all_dts}
    idx_sz_s = {d: float(idx_sz.get(d, 1.0)) for d in all_dts}
    abn_calc_events = {}  # c6 -> list of dt strings where 2d or 3d excess >= 20%
    for c6_t, grp_t in da_tgt.groupby("c6", sort=False):
        dts_c = grp_t["dt"].tolist()
        cls_c = grp_t["close"].tolist()
        imap_c = idx_sh_s if c6_t.startswith("60") else idx_sz_s
        evs = []
        last_ev_idx = -99
        for i in range(3, len(dts_c)):
            # Exchange rule resets after trigger; check 2d and 3d windows since last trigger
            hit = False
            for w in (2, 3):
                if i - w >= max(0, last_ev_idx):
                    p0, p1 = cls_c[i - w], cls_c[i]
                    b0, b1 = imap_c.get(dts_c[i - w], 1.0), imap_c.get(dts_c[i], 1.0)
                    if p0 > 0 and b0 > 0:
                        stk_r = p1 / p0 - 1.0
                        idx_r = b1 / b0 - 1.0
                        if (stk_r - idx_r) >= 0.198:
                            hit = True
                            break
            if hit:
                evs.append(dts_c[i])
                last_ev_idx = i
        abn_calc_events[c6_t] = np.array(evs, dtype=str)

    def _get_mates_and_fb(prev_dt: str, dec_dt: str, plate: str, self_c6: str, sd_fallback: str = ""):
        # All ZT stocks on prev_dt in same plate (excluding self_c6)
        members = set(kpl_plate_members.get((prev_dt, plate), []))
        zt_prev_set = set(zt_by_dt.get(prev_dt, []))
        fb_prev_set = set(fb_by_dt.get(prev_dt, []))

        mate_ops = []
        any_dt_open = False
        for mc in (members & zt_prev_set):
            if mc == self_c6:
                continue
            info = day_open_dt_map.get((dec_dt, mc))
            if info is not None:
                mate_ops.append(info[0])
                if info[1]:
                    any_dt_open = True
        mates_cnt = len(mate_ops)
        mates_avg = float(np.mean(mate_ops)) if mate_ops else 0.0

        # Also D2/sd plate mates' open at dec_dt (for ~sealed_3b when D3 had 0 plate ZTs)
        sd_mate_ops = []
        if sd_fallback and plate not in NON_THEME:
            sd_members = set(kpl_plate_members.get((sd_fallback, plate), []))
            for mc in sd_members:
                if mc == self_c6:
                    continue
                info = day_open_dt_map.get((dec_dt, mc))
                if info is not None:
                    sd_mate_ops.append(info[0])
                    if info[1]:
                        any_dt_open = True
        sd_mates_cnt = len(sd_mate_ops)
        sd_mates_avg = float(np.mean(sd_mate_ops)) if sd_mate_ops else 0.0

        fb_ho = 0
        fb_yz = 0
        for fc in (members & fb_prev_set):
            info = day_open_dt_map.get((dec_dt, fc))
            if info is not None:
                if info[0] >= 0.03:
                    fb_ho += 1
                if info[0] >= 0.095:
                    fb_yz += 1
        return mates_cnt, mates_avg, any_dt_open, fb_ho, fb_yz, sd_mates_cnt, sd_mates_avg

    # Build per-signal holding dict:
    # sig_factors[(c6, bd)] = {"meta": {...}, "days": {dec_dt: {...}}}
    sig_factors = {}
    for row in sub84.itertuples(index=False):
        c6 = str(row.code).zfill(6)
        bd = str(row.buy_date)
        sd = str(row.sig_date)
        d1_dt = str(row.d1_date)
        pos = dt_idx.get(bd, -1)
        if pos < 0 or pos >= len(all_dts) - 1:
            continue

        ex_k = "SH" if c6.startswith("60") else "SZ"
        val_h = [x for x in holders_map.get(c6, []) if str(x[0])[:10] <= sd]
        lock10 = float(max(val_h, key=lambda x: (str(x[1]), str(x[0])))[2]) if val_h else 38.0
        pos20_d0 = float(row.pos_20d_d0) if pd.notna(getattr(row, "pos_20d_d0", np.nan)) else 0.50
        xq_pre_buy = int(getattr(row, "xq_cnt_tot", 0) or 0)

        # Guba pre-D1 baseline: average daily posts in [d1-10d, d1-1d]
        d1_dt_obj = datetime.date.fromisoformat(d1_dt)
        gb_base_cnt = _cnt_ts(gb_arr.get(c6), (d1_dt_obj - datetime.timedelta(days=10)).isoformat() + " 00:00:00", f"{d1_dt} 00:00:00")
        gb_base_daily = max(gb_base_cnt / 7.0, 1.0)

        # D3 (buy day) stats
        d3_bar = tgt_day_map.get((c6, bd))
        d3_tape = tape_map.get((bd, c6), {})
        d3_seal_sec = float(d3_tape.get("seal_sec", 99999.0))
        d3_open_cnt = int(d3_tape.get("open_cnt", 0))
        d3_seal_amt_ratio = float(d3_tape.get("seal_amt_ratio", 0.0))

        d3_meta = {}
        if d3_bar:
            c3, o3, h3, l3, pc3 = d3_bar["close"], d3_bar["open"], d3_bar["high"], d3_bar["low"], d3_bar["pre_c"]
            d2_mid = 0.5 * (d3_bar["d2_open"] + d3_bar["d2_close"])
            upper_sh = (h3 - max(o3, c3)) / max(pc3, 0.01)
            d3_meta = {
                "sealed_3b": bool(row.sealed_3b),
                "d3_yin": bool(c3 < o3),
                "d3_red_yang": bool(c3 > o3 and c3 >= pc3),
                "d3_red_dip": bool(c3 > o3 and l3 < pc3),
                "d3_upper_sh": float(upper_sh),
                "d3_tombstone": bool((c3 < o3) and (upper_sh >= 0.04 or bool(row.touch_3b))),
                "d3_below_d2_mid": bool(c3 < d2_mid),
                "d3_below_ma5": bool(c3 < d3_bar["ma5"]),
                "d3_vol_ratio5": float(d3_bar["amount"] / max(d3_bar["amt_ma5_prev"], 1.0)),
                "d3_vol_ratio20": float(d3_bar["amount"] / max(d3_bar["amt_ma20_prev"], 1.0)),
                "d3_turn": float(d3_bar["to_pct"]),
                "d3_seal_sec": d3_seal_sec,
                "d3_open_cnt": d3_open_cnt,
                "d3_seal_amt_ratio": d3_seal_amt_ratio,
                "d3_rotten_seal": bool(row.sealed_3b) and ((d3_seal_sec < 90000.0 and d3_seal_sec >= 12600.0) or d3_open_cnt >= 3 or (d3_seal_amt_ratio > 0 and d3_seal_amt_ratio < 0.015)),
                "d3_late1400_seal": bool(row.sealed_3b) and ((d3_seal_sec < 90000.0 and d3_seal_sec >= 10800.0) or d3_open_cnt >= 3 or (d3_seal_amt_ratio > 0 and d3_seal_amt_ratio < 0.015)),
                "d3_early_hard_seal": bool(row.sealed_3b) and (d3_seal_sec <= 3600.0 and d3_open_cnt == 0),
            }

        # Track cumulative top youzi buyers from D2 (sd) onwards
        lhb_d2 = lhb_stats.get((sd, c6), {})
        cum_top_yz_buyers = set(lhb_d2.get("top_yz_buy_names", set()))

        days_dict = {}
        end_k = min(len(all_dts) - 1, pos + 18)
        for k in range(pos + 1, end_k + 1):
            dec_dt = all_dts[k]
            prev_dt = all_dts[k - 1]
            env_prev = env_day.get(prev_dt, {})
            prev_bar = tgt_day_map.get((c6, prev_dt), {})
            dec_bar = tgt_day_map.get((c6, dec_dt), {})

            # Plate on prev_dt (fallback to sd plate)
            kp = kpl_stk.get((prev_dt, c6))
            if kp is None:
                kp = kpl_stk.get((sd, c6), {"plate": str(row.plate), "p_sz": int(row.plate_sz), "p_elo": 100.0, "max_stk": 0})
            plate_use = kp["plate"]
            p_sz_use = int(kp["p_sz"])
            p_elo_use = float(kp["p_elo"])
            our_stk_prev = int(prev_bar.get("streak", 0))
            has_higher_mate = bool(kp["max_stk"] > our_stk_prev and our_stk_prev > 0)

            mates_cnt, mates_open_avg, any_mate_dt_open, fb_ho_cnt, fb_yz_cnt, sd_mates_cnt, sd_mates_open_avg = _get_mates_and_fb(prev_dt, dec_dt, plate_use, c6, sd)

            # LHB of prev_dt (known at dec_dt 09:25)
            lhb_p = lhb_stats.get((prev_dt, c6), {})
            top_yz_sold = set(lhb_p.get("top_yz_sell_names", set()))
            top_yz_bought = set(lhb_p.get("top_yz_buy_names", set()))
            top_yz_dumped = bool((cum_top_yz_buyers & top_yz_sold) or lhb_p.get("top_yz_sell_neg", False))
            cum_top_yz_buyers = (cum_top_yz_buyers | top_yz_bought) - top_yz_sold
            top_yz_locked = bool(len(cum_top_yz_buyers) > 0 and not top_yz_dumped)

            # Notices & reg strictly < dec_dt 09:25:00
            dec_cut = f"{dec_dt} 09:25:00"
            bd_cut = f"{bd} 09:25:00"
            prev_cut = f"{prev_dt} 09:25:00"
            dm10_dt = all_dts[max(0, k - 11)]
            dm5_dt = all_dts[max(0, k - 5)]

            sreg_hold = _cnt_ts(stk_reg_ts.get(c6), bd_cut, dec_cut) > 0
            sreg_10d = _cnt_ts(stk_reg_ts.get(c6), f"{dm10_dt} 00:00:00", dec_cut) > 0
            clarify_hold = _cnt_ts(clarify_ts.get(c6), f"{sd} 00:00:00", dec_cut) > 0
            tox_hold = _cnt_ts(tox_ts.get(c6), bd_cut, dec_cut) > 0
            abn_cnt_10d = _cnt_ts(abn_ts.get(c6), f"{dm10_dt} 00:00:00", dec_cut)
            ir_hold = _cnt_ts(ir_arr.get(c6), bd_cut, dec_cut) > 0
            ir_5d = _cnt_ts(ir_arr.get(c6), f"{dm5_dt} 00:00:00", dec_cut) > 0

            # Ex reg 5d strictly <= prev_dt (before dec_dt 09:25)
            ex_arr = ex_reg_sorted.get(ex_k)
            ex_reg5_cnt = int(np.searchsorted(ex_arr, prev_dt, side="right") - np.searchsorted(ex_arr, dm5_dt, side="left")) if ex_arr is not None else 0
            abn_c_arr = abn_calc_events.get(c6)
            abn_calc_10d = int(np.searchsorted(abn_c_arr, prev_dt, side="right") - np.searchsorted(abn_c_arr, dm10_dt, side="left")) if abn_c_arr is not None else 0

            # Xueqiu & Guba strictly < dec_dt 09:25:00
            xq_new_hold = _cnt_ts(xq_arr.get(c6), bd_cut, dec_cut)
            xq_cum_all = _cnt_ts(xq_arr.get(c6), f"{d1_dt} 00:00:00", dec_cut)
            gb_day = _cnt_ts(gb_arr.get(c6), prev_cut, dec_cut)
            gb_spike_ratio = float(gb_day / gb_base_daily)

            # Prev day turn & real turn
            prev_turn = float(prev_bar.get("to_pct", 0.0))
            prev_real_turn = prev_turn / max(0.05, 1.0 - lock10 / 100.0)

            # 3to4 V4.0 counterparty score on D4 (k == pos + 1 when sealed_3b == True)
            v40_score_d4 = np.nan
            v40_veto_d4 = False
            is_top1_3b_d4 = False
            if k == pos + 1 and bool(row.sealed_3b):
                d4_op = float(dec_bar.get("o_pct", 0.0))
                is_top1_3b_d4 = bool(d4_op >= float(b3_day_max_op.get(dec_dt, 9.9)) - 1e-5)
                px_d3 = float(prev_bar.get("close", 15.0))
                mcap_d3 = float(prev_bar.get("mcap", 50.0))
                rf_mcap_d3 = mcap_d3 * max(0.05, 1.0 - lock10 / 100.0)
                lock_bad = (lock10 < 45.0) and (rf_mcap_d3 < 45.0)
                fst_int = int(str(d3_tape.get("fst", "99:99:99")).replace(":", "")[:4]) if d3_tape.get("fst", "99:99:99")[:2].isdigit() else 9999
                m_zt_p = int(env_prev.get("n_zt", 50))
                m_mb_p = int(env_prev.get("max_board", 4))
                p_3b_dt = int(env_prev.get("b3_dt", 0))
                c1d = float(env_prev.get("csi_1d", 0.0))
                c5d = float(env_prev.get("csi_5d", 0.0))
                mon_b = int(dec_dt[5:7]) in (1, 5)
                lh_d3 = int(lhb_p.get("lh_cnt", 0))
                syz_d3 = bool(lhb_p.get("daysurf_buy", False))

                sc40 = 78.0
                sc40 += 8.0 if px_d3 <= 20.0 else 0.0
                sc40 += 8.0 if m_mb_p <= 4 else 0.0
                sc40 += 5.0 if (35 <= m_zt_p <= 85) else 0.0
                sc40 += 4.0 if (fb_ho_cnt >= 2 and fb_yz_cnt == 0) else 0.0
                sc40 += 4.0 if lh_d3 == 0 else 0.0
                sc40 += 3.0 if p_elo_use >= 115.0 else 0.0
                sc40 += 3.0 if p_3b_dt == 0 else 0.0
                sc40 += 3.0 if (9.5 <= prev_turn <= 28.0) else 0.0
                sc40 += 3.0 if (936 <= fst_int <= 1030) else 0.0
                sc40 -= 12.0 if ex_reg5_cnt >= 1 else 0.0
                sc40 -= 12.0 if syz_d3 else 0.0
                sc40 -= 12.0 if (not is_top1_3b_d4) else 0.0
                sc40 -= 10.0 if (mates_cnt >= 1 and mates_open_avg < -0.015) else 0.0
                sc40 -= 10.0 if lock_bad else 0.0
                sc40 -= 10.0 if (not (8.5 <= prev_turn <= 31.0)) else 0.0
                sc40 -= 8.0 if (c1d <= -0.020 or c5d <= -0.030) else 0.0
                sc40 -= 7.0 if fb_yz_cnt >= 1 else 0.0
                sc40 -= 5.0 if lh_d3 >= 3 else 0.0
                sc40 -= 4.0 if p_3b_dt >= 2 else 0.0
                sc40 -= 4.0 if mon_b else 0.0
                sc40 += 5.0 if pos20_d0 <= 0.40 else 0.0
                sc40 -= 15.0 if xq_cum_all >= 4 else 0.0
                v40_score_d4 = sc40
                v40_veto_d4 = bool(sreg_10d or tox_hold or d3_open_cnt == 0 or (d4_op < 0.030) or (d4_op > 0.092))

            # V5.1 High-Dragon Break Judge at dec_dt 15:00 (when stock breaks on dec_dt!)
            # Strictly <= dec_dt 15:00: dec_bar candle/turn, env_prev (k-1), ex_reg5_cnt (< dec_dt 09:25), lhb_p (k-1 LHB)
            dec_turn = float(dec_bar.get("to_pct", 0.0))
            dec_ty = bool(dec_bar.get("close", 0.0) > dec_bar.get("open", 0.0))
            dec_dip4 = bool(dec_bar.get("l_pct", 0.0) <= -0.04 and dec_ty)
            dec_dip6 = bool(dec_bar.get("l_pct", 0.0) <= -0.06 and dec_ty)
            v51_pass_basic = (
                dec_ty
                and (dec_turn <= 35.0)
                and (not sreg_10d)
                and (not tox_hold)
                and (ex_reg5_cnt < 2)
                and (int(lhb_p.get("lh_cnt", 0)) < 3)
            )
            v51_sc = 60.0
            v51_sc += 12.0 if float(env_prev.get("brk_dt_r10", 0.0)) >= 0.20 else -8.0
            v51_sc += 10.0 if int(env_prev.get("n_zt", 50)) < 70 else (-10.0 if int(env_prev.get("n_zt", 50)) >= 95 else 0.0)
            v51_sc += 8.0 if float(env_prev.get("csi_5d", 0.0)) >= -0.005 else (-10.0 if float(env_prev.get("csi_5d", 0.0)) < -0.025 else 0.0)
            v51_sc += 6.0 if (p_elo_use < 135.0) else 0.0
            v51_sc += 6.0 if int(lhb_p.get("lh_cnt", 0)) == 0 else (-10.0 if int(lhb_p.get("lh_cnt", 0)) == 2 else 0.0)
            v51_sc -= 6.0 if bool(lhb_p.get("inst_net_sell", False)) else 0.0
            v51_sc += 5.0 if dec_dip6 else 0.0
            v51_sc += 5.0 if bool(lhb_p.get("daysurf_buy", False)) is False else -6.0
            v51_sc += 5.0 if top_yz_locked else 0.0

            days_dict[dec_dt] = {
                "step_from_buy": k - pos,
                "dec_open_pct": float(dec_bar.get("o_pct", 0.0)),
                # Cat 1
                "v40_score_d4": v40_score_d4,
                "v40_veto_d4": v40_veto_d4,
                "is_top1_3b_d4": is_top1_3b_d4,
                "v51_pass_basic": v51_pass_basic,
                "v51_break_sc": v51_sc,
                "dec_turn": dec_turn,
                "dec_dip4": dec_dip4,
                "dec_dip6": dec_dip6,
                # Cat 2: LHB prev_dt
                "on_lhb": bool(lhb_p.get("on_lhb", False)),
                "lh_cnt": int(lhb_p.get("lh_cnt", 0)),
                "lh_buy_ratio": float(lhb_p.get("lh_buy_ratio", 0.0)),
                "daysurf_buy": bool(lhb_p.get("daysurf_buy", False)),
                "inst_net_sell": bool(lhb_p.get("inst_net_sell", False)),
                "inst_net": float(lhb_p.get("inst_net", 0.0)),
                "top_yz_locked": top_yz_locked,
                "top_yz_dump": top_yz_dumped,
                "max_seat_buy_amt_ratio": float(lhb_p.get("max_seat_buy_amt_ratio", 0.0)),
                "max_seat_net_amt_ratio": float(lhb_p.get("max_seat_net_amt_ratio", 0.0)),
                "max_seat_lhb_share": float(lhb_p.get("max_seat_lhb_share", 0.0)),
                "quant_dump": bool(lhb_p.get("quant_dump", False)),
                # Cat 3: Notices & Reg < dec_dt 09:25
                "sreg_hold": sreg_hold,
                "sreg_10d": sreg_10d,
                "clarify_hold": clarify_hold,
                "tox_hold": tox_hold,
                "clarify_or_tox": bool(clarify_hold or tox_hold),
                "ex_reg5_cnt": ex_reg5_cnt,
                "abn_cnt_10d": abn_cnt_10d,
                "abn_calc_10d": abn_calc_10d,
                "ir_hold": ir_hold,
                "ir_5d": ir_5d,
                # Cat 4: Community < dec_dt 09:25
                "xq_pre_buy": xq_pre_buy,
                "xq_new_hold": xq_new_hold,
                "xq_cum_all": xq_cum_all,
                "gb_day": gb_day,
                "gb_spike_ratio": gb_spike_ratio,
                # Cat 5: Ecosystem
                "mates_cnt": mates_cnt,
                "mates_open_avg": mates_open_avg,
                "sd_mates_cnt": sd_mates_cnt,
                "sd_mates_open_avg": sd_mates_open_avg,
                "any_mate_dt_open": any_mate_dt_open,
                "plate_sz_prev": p_sz_use,
                "mkt_zt_open_avg": float(env_prev.get("mkt_zt_open_avg", 0.0)) if False else float(env_day.get(dec_dt, {}).get("mkt_zt_open_avg", 0.0)),
                "mkt_fb_open_avg": float(env_day.get(dec_dt, {}).get("mkt_fb_open_avg", 0.0)),
                "mkt_zt_prev": int(env_prev.get("n_zt", 50)),
                "mkt_seal_prev": float(env_prev.get("seal_rate", 0.55)),
                "brk_dt_r10": float(env_prev.get("brk_dt_r10", 0.0)),
                "hd_reb_r10": float(env_prev.get("hd_reb_r10", 0.30)),
                "csi_1d_prev": float(env_prev.get("csi_1d", 0.0)),
                "csi_5d_prev": float(env_prev.get("csi_5d", 0.0)),
                "p_elo_prev": p_elo_use,
                "has_higher_mate": has_higher_mate,
                # Cat 6: Turnover & Micro
                "prev_turn": prev_turn,
                "prev_real_turn": prev_real_turn,
            }

        sig_factors[(c6, bd)] = {"meta": d3_meta, "days": days_dict}

    # Build fast plook, stk_hist, b5m1, b5m2 for target_c6
    sys.path.insert(0, S2_DIR)
    import exit_engine as ee
    da_sub = da[da["c6"].isin(target_c6)].copy()
    plook, stk_hist = ee.build_lookups(da_sub)
    b5m1 = {k: v for k, v in d["b5m_need"].items() if k[1] <= cutoff_date}
    b5m2 = {**b5m1, **{k: v for k, v in supp["supp_5m"].items() if k[1] <= cutoff_date}}

    csi_canon = json.load(open(CSI_CANON_JSON, encoding="utf-8"))
    pkg = {
        "cutoff_date": cutoff_date,
        "sub84": sub84,
        "sig_factors": sig_factors,
        "all_dts": all_dts,
        "dt_idx": dt_idx,
        "plook": plook,
        "stk_hist": stk_hist,
        "b5m1": b5m1,
        "b5m2": b5m2,
        "idx_sh": idx_sh,
        "idx_sz": idx_sz,
        "sh300": csi_map,
        "csi_canon": csi_canon,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    out_p = f"{OUT_DIR}/{out_name}"
    with open(out_p, "wb") as f:
        pickle.dump(pkg, f)
    print(f"[build_holding_factors] Saved {out_p} in {time.time()-t0:.1f}s!")
    return pkg


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cutoff", default="2026-11-16")
    parser.add_argument("--out", default="_cache_holding_factors_full.pkl")
    args = parser.parse_args()
    build_cache(args.cutoff, args.out)
