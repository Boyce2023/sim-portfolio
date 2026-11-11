#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v11_unified_master.py
================================================================================
V11 Unified Master Backtest Engine (2021-2026 Full 5Y + Delisted + PIT Notices)
100% Homologous Absorption of All 8 Live Production Fixes:
1. 8-Year Merged Plate Library (kpl_plates_2018_2026_merged.jsonl) preheating first_seen
2. PIT Notice filtering: excludes clarification/volatility/risk/not exist/not involved/unplanned
3. Cap & Amount scoring: 25<=mcap<=145 (+24), 18<=mcap<25 (+14), mcap>180 (-15); 1.2e8<=amt<=15e8 (+18)
4. Major theme (p_sz>=12) sub-branch (sub_sz>=2) auction #1 gets +15 exempt from deduction; p_sz>=20 crowding -8
5. D2 auction strictly within gate_ok==True & open<zt_p pool; open range 2.8%~7.6%; d1_dt_cnt>=18 market gate
================================================================================
"""
import bisect
import datetime
import json
import os
import re
import sqlite3
import time
import urllib.request
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from v10_core_features import (
    load_full_5y_prices, split_terms, norm_term, NON_THEME,
    MA_PAT, TECH_PAT_ORIG, TECH_PAT_TIMELESS, EARN_PAT,
    KPL_5Y_PATH, PIT_NOTICES_DB, SIM_DIR
)
from v10_pit_and_sim import CSI300_ANNUAL, CSI300_5Y_CUM, FEE_RATE
from v10_backtest_eval import simulate_single_trade

KPL_MERGED_PATH = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"
OUT_DIR = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean"
OUT_JSON = f"{OUT_DIR}/clean_wf_1to2_v11_unified_master_results.json"
OUT_CSV = f"{OUT_DIR}/clean_wf_1to2_v11_unified_master_ledger.csv"

# Fixed PIT notice patterns (100% homologous to fast_1to2_today.py)
HARD_NOTICE_PAT = re.compile(r"(重组|收购|股权转让|控制权|实控人变更|资产注入|借壳|重大合同|中标|战略合作|框架协议|投资设立)")
NEG_NOTICE_PAT = re.compile(r"(不存在|不涉及|未筹划|未发现|无应披露|股票交易异常波动|异常波动公告|风险提示|占比极小|敬请广大投资者注意)")
BAD_NOTICE_PAT = re.compile(r"(减持|问询函|监管函|警示函|立案|风险提示|业绩预亏|计提资产减值|退市风险|终止上市|违规)")
MA_NOTICE_PAT = re.compile(r"(重组|收购|股权转让|控制权变更|实控人变更|资产注入|借壳|重大合同|中标)")
EARN_NOTICE_PAT = re.compile(r"(业绩预增|业绩快报|扭亏为盈|半年度业绩|年度业绩|季度业绩)")


def build_5y_elo_and_candidates_v11(df: pd.DataFrame):
    t0 = time.time()
    g = df.groupby("c6")
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
    df["f_entity"] = (df["close"] - df["open"]) / (df["pre_c"] + 1e-6)

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

    kpl_days = [json.loads(ln) for ln in open(KPL_5Y_PATH, encoding="utf-8") if ln.strip()]
    kpl_days.sort(key=lambda x: x["date"])
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

    # Fix 1: Pre-heat term_first_dt & term_seen_days from 2018-2026 merged plate library
    term_seen_days = Counter()
    term_first_dt, term_last_idx = {}, {}
    if os.path.exists(KPL_MERGED_PATH):
        with open(KPL_MERGED_PATH, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    d = row.get("date", "")
                    for p in row.get("plates", []):
                        pname = p.get("plate", "") or p.get("plate_name", "")
                        for t in split_terms(pname):
                            if t and (t not in term_first_dt or d < term_first_dt[t]):
                                term_first_dt[t] = d
                            if d < "2021-01-01":
                                term_seen_days[t] += 1
                except Exception:
                    pass

    stock_theme_5y = {}

    for day_idx, d_entry in enumerate(kpl_days):
        dt = d_entry["date"]
        cutoff_15d = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=15)).isoformat()
        plates = d_entry.get("plates", [])

        # Post-market Elo adjustments
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
            for s in stocks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6_list.append(c6)
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
            sc_orig = sc_base + (6.0 if (TECH_PAT_ORIG.search(pname) or n_tech_o >= max(1, sz // 2)) else 0.0)
            sc_clean = sc_base + (6.0 if (TECH_PAT_TIMELESS.search(pname) or n_tech_t >= max(1, sz // 2)) else 0.0)
            plate_scores[pname] = sc_orig
            plate_meta[pname] = (sc_orig, sc_clean, elo[pname], sz, n_yizi, n_new > 0, spark_b, n_tech_o, n_tech_t, stocks)

        ranked_p = sorted(plate_scores.keys(), key=lambda k: plate_scores[k], reverse=True)
        rk_map = {k: i + 1 for i, k in enumerate(ranked_p)}
        top2_sc = plate_scores[ranked_p[1]] if len(ranked_p) >= 2 else 100.0
        ranked_c = sorted(plate_meta.keys(), key=lambda k: plate_meta[k][1], reverse=True)
        rk_map_c = {k: i + 1 for i, k in enumerate(ranked_c)}
        top2_sc_c = plate_meta[ranked_c[1]][1] if len(ranked_c) >= 2 else 100.0

        for pname, m in plate_meta.items():
            sc_o, sc_c, p_elo, sz, n_yz, has_new, spk, nto, ntt, stocks = m
            rk_o, rk_c = rk_map[pname], rk_map_c[pname]
            gap_o = (sc_o - top2_sc) if rk_o == 1 else 0.0
            gap_c = (sc_c - top2_sc_c) if rk_c == 1 else 0.0
            for s in stocks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                sname = str(s[1]).strip() if len(s) > 1 else ""
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                r_lg = str(s[3]).strip() if len(s) > 3 else ""
                txt = f"{pname} {r_sh} {r_lg}"
                own_new = any((term_seen_days[t] == 0 or term_first_dt.get(t, dt) >= cutoff_15d) for t in split_terms(r_sh))
                s_elo = sub_elo[r_sh] if (r_sh and r_sh not in NON_THEME) else p_elo
                cur = stock_theme_5y.get((dt, c6))
                if cur is None or sc_o > cur["t_score_o"]:
                    stock_theme_5y[(dt, c6)] = {
                        "name": sname, "plate": pname, "r_short": r_sh or pname,
                        "rk_o": rk_o, "t_score_o": sc_o, "gap_o": gap_o,
                        "rk_c": rk_c, "t_score_c": sc_c, "gap_c": gap_c,
                        "p_elo": p_elo, "s_elo": s_elo, "p_sz": sz, "n_yizi": n_yz,
                        "has_new": has_new, "own_new": own_new, "spark": spk,
                        "is_ma": bool(MA_PAT.search(txt)),
                        "is_tech_o": bool(TECH_PAT_ORIG.search(txt)),
                        "is_tech_c": bool(TECH_PAT_TIMELESS.search(txt)),
                        "is_earn": bool(EARN_PAT.search(txt)),
                    }
        for t, dt_v in day_terms_to_commit.items():
            term_seen_days[t] += 1
            if t not in term_first_dt: term_first_dt[t] = dt_v
            term_last_idx[t] = day_idx
        prev_plate_stocks = new_prev_p
        prev_sub_stocks = new_prev_sub

    print(f"[Elo V11] Built 5Y Dual-Layer Elo & New-Terms across {len(kpl_days)} days ({len(stock_theme_5y):,} stock-days) in {time.time()-t0:.2f}s")
    return df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map


def attach_pit_notices_and_scores_v11(df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map):
    t0 = time.time()
    fb = df[df["is_first_board"] & (~df["is_yizi"]) & (df["dt_str"] >= "2021-01-04")].copy()

    # Fix 2: Strict PIT notice filtering
    notice_by_c6 = defaultdict(list)
    if os.path.exists(PIT_NOTICES_DB):
        conn = sqlite3.connect(PIT_NOTICES_DB)
        c6_set = set(fb["c6"].unique())
        for sec_code, pub_dt, avail_dt, title in conn.execute(
            "SELECT sec_code, pub_datetime_cst, trade_date_avail, title FROM notices WHERE pub_datetime_cst >= '2021-01-01' ORDER BY pub_datetime_cst ASC"
        ):
            c6 = str(sec_code)[:6].zfill(6)
            if c6 not in c6_set or not pub_dt:
                continue
            ts = str(title or "")
            is_neg = bool(NEG_NOTICE_PAT.search(ts))
            is_bad = bool(BAD_NOTICE_PAT.search(ts))
            is_hard = bool(HARD_NOTICE_PAT.search(ts)) and (not is_neg) and (not is_bad)
            is_ma = bool(MA_NOTICE_PAT.search(ts)) and (not is_neg) and (not is_bad)
            is_earn = bool(EARN_NOTICE_PAT.search(ts))

            flags = (is_hard, is_ma, is_earn, is_bad)
            if any(flags):
                notice_by_c6[c6].append((str(pub_dt), str(avail_dt or ""), flags))
        conn.close()

    for c6 in notice_by_c6:
        notice_by_c6[c6].sort(key=lambda x: x[0])

    rows_meta = []
    for r in fb[["c6", "dt_str", "d2_dt", "mcap", "amount", "f_dd20_d0", "f_dd60_d0", "f_pos20_d0",
                 "f_d0_pct", "f_ret_pre10", "to", "f_d1_vol_ratio", "f_zt_cnt_pre20", "f_break60"]].itertuples(index=False):
        c6, d1, d2 = r.c6, r.dt_str, (r.d2_dt if pd.notna(r.d2_dt) else "2026-11-11")
        ti = stock_theme_5y.get((d1, c6))
        if ti is None:
            ti = {
                "name": "", "plate": "其他", "r_short": "其他",
                "rk_o": 99, "t_score_o": 95.0, "gap_o": 0.0,
                "rk_c": 99, "t_score_c": 95.0, "gap_c": 0.0,
                "p_elo": 100.0, "s_elo": 100.0, "p_sz": 1, "n_yizi": 0,
                "has_new": False, "own_new": False, "spark": 0.0,
                "is_ma": False, "is_tech_o": False, "is_tech_c": False, "is_earn": False,
            }

        start_cut = (datetime.date.fromisoformat(d1) - datetime.timedelta(days=4)).isoformat()
        end_cut = f"{d2} 09:25:00"
        nh = n_ma = n_earn = n_bad = False
        nlist = notice_by_c6.get(c6)
        if nlist:
            lo = bisect.bisect_left(nlist, (start_cut, "", ()))
            for idx_n in range(lo, len(nlist)):
                pdt, adt, fl = nlist[idx_n]
                if pdt > end_cut:
                    break
                if adt and adt > d2:
                    continue
                nh |= fl[0]; n_ma |= fl[1]; n_earn |= fl[2]; n_bad |= fl[3]

        is_ma_f = bool(ti["is_ma"] or n_ma)
        is_earn_f = bool(ti["is_earn"] or n_earn)

        rk_c = ti["rk_c"]
        p_sz = ti["p_sz"]
        s_prior_dual = (
            (28 if rk_c == 1 else (16 if rk_c == 2 else (8 if rk_c == 3 else 0)))
            + (18 if p_sz >= 4 else (10 if p_sz >= 2 else -15))
            + (12 if ti["has_new"] else 0) + (8 if ti["own_new"] else 0) + (10 if ti["spark"] > 0 else 0)
            + (18 if nh else 0) + (18 if is_ma_f else 0) + (12 if ti["is_tech_c"] else 0)
            + (12 if ti["gap_c"] >= 20.0 else 0)
            + float(np.clip((ti["t_score_c"] - 100.0) * 0.25, 0.0, 25.0))
            + float(np.clip((ti["s_elo"] - 100.0) * 0.35, -10.0, 18.0))
        )
        # Fix 4: p_sz>=20 crowding -8
        if p_sz >= 20 and not (nh or is_ma_f):
            s_prior_dual -= 8

        # Fix 3: Small Cap & Volume Modifications
        mcap = float(r.mcap) if pd.notna(r.mcap) else 50.0
        amt = float(r.amount) if pd.notna(r.amount) else 2e8
        sc_mcap = 24 if 25.0 <= mcap <= 145.0 else (14 if 18.0 <= mcap < 25.0 else (-15 if mcap > 180.0 else 0))
        sc_amt = 18 if 1.2e8 <= amt <= 15e8 else 0

        dd20 = float(r.f_dd20_d0) if pd.notna(r.f_dd20_d0) else 0.90
        dd60 = float(r.f_dd60_d0) if pd.notna(r.f_dd60_d0) else 0.85
        pos20 = float(r.f_pos20_d0) if pd.notna(r.f_pos20_d0) else 0.50
        d0_pct = float(r.f_d0_pct) if pd.notna(r.f_d0_pct) else 0.0
        ret10 = float(r.f_ret_pre10) if pd.notna(r.f_ret_pre10) else 0.0
        to = float(r.to) if pd.notna(r.to) else 8.0
        vr = float(r.f_d1_vol_ratio) if pd.notna(r.f_d1_vol_ratio) else 1.5
        zt20 = int(r.f_zt_cnt_pre20) if pd.notna(r.f_zt_cnt_pre20) else 0

        sc_dd20 = 24 if dd20 >= 0.95 else (12 if dd20 >= 0.88 else 0)
        sc_dd60 = 18 if dd60 >= 0.92 else (8 if dd60 >= 0.82 else 0)
        sc_pos20 = 16 if pos20 >= 0.85 else (8 if pos20 >= 0.65 else 0)
        sc_d0 = 22 if d0_pct >= 0.098 else (12 if d0_pct >= 0.095 else 0)
        sc_ret10 = 18 if 0.02 <= ret10 <= 0.25 else 0
        sc_to = 16 if 3.0 <= to <= 12.0 else (8 if to < 3.0 or (12.0 < to <= 18.0) else -15)
        sc_vol = 14 if 1.2 <= vr <= 3.5 else 0

        s_q_base_dual = sc_mcap + sc_amt + 24 + sc_d0 + sc_ret10 + sc_to + sc_vol + sc_dd20 + sc_dd60 + sc_pos20

        is_st = "ST" in ti["name"].upper() or "退" in ti["name"]
        gate_ok = bool(
            (not is_st)
            and (not is_earn_f)
            and (not n_bad)
            and (18.0 <= mcap <= 220.0)
            and (to <= 20.0)
            and (not (zt20 >= 4 and pos20 > 0.38))
        )

        rows_meta.append((
            ti["name"], ti["plate"], ti["r_short"], ti["p_elo"], ti["s_elo"], p_sz, ti["n_yizi"],
            ti["has_new"], ti["own_new"], ti["spark"], is_ma_f, nh, n_bad, is_earn_f,
            s_prior_dual, s_q_base_dual, gate_ok
        ))

    meta_cols = [
        "name", "plate", "r_short", "p_elo", "s_elo", "p_sz", "d1_n_yizi",
        "has_new_term", "own_new_term", "spark_bonus", "is_ma", "notice_hard", "notice_bad", "is_earn",
        "s_prior_dual", "s_q_base_dual", "gate_ok"
    ]
    meta_df = pd.DataFrame(rows_meta, index=fb.index, columns=meta_cols)
    fb = pd.concat([fb, meta_df], axis=1)

    fb["d1_zt_cnt"] = fb["dt_str"].map(zt_cnt_map).fillna(50)
    fb["d1_dt_cnt"] = fb["dt_str"].map(dt_cnt_map).fillna(0)
    fb["mkt_seal_rate"] = fb["dt_str"].map(seal_rate_map).fillna(0.65)
    fb["promo_ma5"] = fb["dt_str"].map(promo_ma5_map).fillna(0.25)
    fb["promo_freeze"] = fb["promo_ma5"] < 0.18

    # Fix 5: nuclear_halt includes d1_dt_cnt >= 18
    auc_means = fb.groupby("d2_dt")["d2_o_pct"].mean()
    fb["auc_mean"] = fb["d2_dt"].map(auc_means).fillna(0.0)
    fb["nuclear_halt"] = (fb["auc_mean"] < 0.0) | (fb["d1_dt_cnt"] >= 18)

    fb["trig_p"] = np.minimum(
        fb["d2_zt_p"],
        np.maximum(
            np.round(fb["d2_open"] * 1.012, 2),
            np.round(fb["close"] * 1.065, 2)
        )
    )

    print(f"[PIT & Sim V11] Processed {len(fb):,} 1st-board candidates in {time.time()-t0:.2f}s")
    return fb


def compute_d2_auction_scores_v11(sub_df: pd.DataFrame) -> pd.DataFrame:
    df = sub_df.copy()
    # Fix 4 & 5: Strict buyable pool for auction ranking
    df["is_buyable_open"] = df["gate_ok"] & (df["d2_open"] > 0) & (df["d2_open"] < (df["d2_zt_p"] - 0.005))

    d2_yizi_sum = df.groupby(["d2_dt", "plate"])["d2_is_yizi"].transform("sum")
    df["plate_d2_yizi_cnt"] = d2_yizi_sum.fillna(0)

    df["mkt_open_rk"] = 99
    df["buyable_plate_rk"] = 99
    df["subbranch_rk"] = 99
    df["sub_sz"] = 1
    df["buy_open_lead"] = 0.0

    buy_mask = df["is_buyable_open"]
    if buy_mask.any():
        df_buy = df[buy_mask]
        df.loc[buy_mask, "mkt_open_rk"] = df_buy.groupby("d2_dt")["d2_o_pct"].rank(ascending=False, method="min")
        df.loc[buy_mask, "buyable_plate_rk"] = df_buy.groupby(["d2_dt", "plate"])["d2_o_pct"].rank(ascending=False, method="min")
        df.loc[buy_mask, "subbranch_rk"] = df_buy.groupby(["d2_dt", "plate", "r_short"])["d2_o_pct"].rank(ascending=False, method="min")
        df.loc[buy_mask, "sub_sz"] = df_buy.groupby(["d2_dt", "plate", "r_short"])["d2_o_pct"].transform("count")

        p2 = df_buy.groupby(["d2_dt", "plate"])["d2_o_pct"].apply(
            lambda s: s.nlargest(2).iloc[-1] if len(s) >= 2 else -0.05
        ).to_dict()
        df.loc[buy_mask, "buy_open_lead"] = np.where(
            df.loc[buy_mask, "buyable_plate_rk"] == 1,
            df.loc[buy_mask, "d2_o_pct"] - df.loc[buy_mask].set_index(["d2_dt", "plate"]).index.map(p2),
            0.0
        )

    # Fix 4: Sub-branch exception in major theme (p_sz>=12 & sub_sz>=2 & subbranch_rk==1 & buyable_plate_rk<=5 gets +15)
    conds_theme_rk = [
        df["buyable_plate_rk"] == 1,
        df["buyable_plate_rk"] == 2,
        (df["p_sz"] >= 12) & (df["sub_sz"] >= 2) & (df["subbranch_rk"] == 1) & (df["buyable_plate_rk"] <= 5),
    ]
    choices_theme_rk = [35, 5, 15]
    theme_rk_bonus = np.select(conds_theme_rk, choices_theme_rk, default=-25)

    auc_bonus = (
        theme_rk_bonus
        + np.where(df["mkt_open_rk"] <= 3, 20, np.where(df["mkt_open_rk"] <= 6, 12, 0))
        + np.where(df["buy_open_lead"] >= 0.020, 22, np.where(df["buy_open_lead"] >= 0.010, 12, 0))
        + np.where(df["d2_o_pct"].between(0.038, 0.076), 20, np.where(df["d2_o_pct"].between(0.028, 0.038), 10, 0))
        + np.where((df["buyable_plate_rk"] <= 2) & (df["plate_d2_yizi_cnt"] >= 1), 10, 0)
    )

    df["s_quant_dual"] = df["s_q_base_dual"] + auc_bonus
    df["tot_dual"] = df["s_prior_dual"] + df["s_quant_dual"]
    df["trig_p"] = np.minimum(
        df["d2_zt_p"],
        np.maximum(np.round(df["d2_open"] * 1.012, 2), np.round(df["close"] * 1.065, 2))
    )

    return df


def summarize_trades(tr_list):
    if not tr_list:
        return {"n": 0, "wr": 0.0, "payoff": 0.0, "seal2b": 0.0}
    rets = np.array([t["net_ret"] for t in tr_list])
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = float(len(wins) / len(rets))
    aw = float(wins.mean()) if len(wins) else 0.0
    al = float(abs(losses.mean())) if len(losses) else 0.01
    return {
        "n": int(len(rets)), "wr": round(wr, 4),
        "payoff": round(aw / al if al > 0 else 0.0, 2),
        "seal2b": round(float(np.mean([t["sealed_2b"] for t in tr_list])), 4),
    }


def eval_scheme_d15(sub_df, score_col, cond_mask, price_lookup, all_dts, dt_to_idx, entry_mode="trig", exit_mode="E4", fee=FEE_RATE):
    sub = sub_df[cond_mask].copy()
    if sub.empty:
        return {"total_trades_1slot": 0, "win_rate_5y": 0.0, "payoff_5y": 0.0, "seal_2b_5y": 0.0,
                "cum_nav_1slot": 1.0, "mdd_1slot": 0.0, "cum_nav_2slot": 1.0, "mdd_2slot": 0.0,
                "cum_nav_daily_eq": 1.0, "mdd_daily_eq": 0.0, "csi300_5y_cum": CSI300_5Y_CUM,
                "net_excess_5y_1slot": -CSI300_5Y_CUM, "annual": {}, "trades": []}

    sub.sort_values(["d2_dt", score_col], ascending=[True, False], inplace=True)

    free_dt = ""
    free_open = True
    nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0
    trades_1s = []

    slot_dt = ["", ""]
    slot_open = [False, False]
    slot_cap = [0.5, 0.5]
    peak_2s, mdd_2s = 1.0, 0.0
    trades_2s = []

    eq_daily_rets = []

    for d2, grp in sub.groupby("d2_dt", sort=True):
        rows = [r._asdict() if hasattr(r, "_asdict") else r.to_dict() for _, r in grp.iterrows()]

        # 1-Slot Top-1
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            tr1 = simulate_single_trade(rows[0], price_lookup, all_dts, dt_to_idx, entry_mode, exit_mode, fee)
            if tr1 is not None:
                nav_1s *= (1.0 + tr1["net_ret"])
                peak_1s = max(peak_1s, nav_1s)
                mdd_1s = max(mdd_1s, (peak_1s - nav_1s) / peak_1s)
                free_dt, free_open = tr1["exit_date"], tr1["exit_at_open"]
                trades_1s.append(tr1)

        # 2-Slot Top-2
        for r_cand in rows[:2]:
            s_chosen = -1
            for si in range(2):
                if slot_dt[si] == "" or d2 > slot_dt[si] or (d2 == slot_dt[si] and slot_open[si]):
                    s_chosen = si; break
            if s_chosen != -1:
                tr2 = simulate_single_trade(r_cand, price_lookup, all_dts, dt_to_idx, entry_mode, exit_mode, fee)
                if tr2 is not None:
                    slot_cap[s_chosen] *= (1.0 + tr2["net_ret"])
                    slot_dt[s_chosen], slot_open[s_chosen] = tr2["exit_date"], tr2["exit_at_open"]
                    trades_2s.append(tr2)
        c_nav2 = slot_cap[0] + slot_cap[1]
        peak_2s = max(peak_2s, c_nav2)
        mdd_2s = max(mdd_2s, (peak_2s - c_nav2) / peak_2s)

        # Daily Equal Weight
        day_r = []
        for r_all in rows:
            tra = simulate_single_trade(r_all, price_lookup, all_dts, dt_to_idx, entry_mode, exit_mode, fee)
            if tra is not None:
                day_r.append(tra["net_ret"])
        if day_r:
            eq_daily_rets.append((d2, float(np.mean(day_r))))

    nav_eq, pk_eq, mdd_eq = 1.0, 1.0, 0.0
    for _, mr in eq_daily_rets:
        nav_eq *= (1.0 + mr); pk_eq = max(pk_eq, nav_eq); mdd_eq = max(mdd_eq, (pk_eq - nav_eq) / pk_eq)

    annual = {}
    for yr in [2022, 2023, 2024, 2025, 2026]:
        ys = str(yr)
        yt1 = [t for t in trades_1s if t["buy_date"].startswith(ys)]
        yt2 = [t for t in trades_2s if t["buy_date"].startswith(ys)]
        yeq = [r for d, r in eq_daily_rets if d.startswith(ys)]
        st1 = summarize_trades(yt1)
        ynav1, ypk1, ymdd1 = 1.0, 1.0, 0.0
        for t in yt1:
            ynav1 *= (1.0 + t["net_ret"]); ypk1 = max(ypk1, ynav1); ymdd1 = max(ymdd1, (ypk1 - ynav1) / ypk1)
        ynav2 = float(np.prod([1.0 + 0.5 * t["net_ret"] for t in yt2])) if yt2 else 1.0
        ynaveq = float(np.prod([1.0 + r for r in yeq])) if yeq else 1.0
        bench = CSI300_ANNUAL[yr]
        annual[str(yr)] = {
            "trades_1slot": st1["n"], "win_rate": st1["wr"], "payoff": st1["payoff"], "seal_2b_rate": st1["seal2b"],
            "nav_1slot": round(ynav1, 4), "nav_2slot": round(ynav2, 4), "nav_daily_eq": round(ynaveq, 4),
            "mdd_1slot": round(ymdd1, 4), "csi300": bench, "excess_1slot": round((ynav1 - 1.0) - bench, 4),
        }

    s_all = summarize_trades(trades_1s)
    s_3y = summarize_trades([t for t in trades_1s if t["buy_date"] >= "2024-01-01"])
    s_1y = summarize_trades([t for t in trades_1s if t["buy_date"] >= "2026-01-01"])
    nav_2s_tot = slot_cap[0] + slot_cap[1]

    return {
        "total_trades_1slot": s_all["n"], "win_rate_5y": s_all["wr"], "payoff_5y": s_all["payoff"], "seal_2b_5y": s_all["seal2b"],
        "win_rate_3y": s_3y["wr"], "payoff_3y": s_3y["payoff"],
        "win_rate_2026": s_1y["wr"], "payoff_2026": s_1y["payoff"],
        "cum_nav_1slot": round(nav_1s, 4), "mdd_1slot": round(mdd_1s, 4),
        "cum_nav_2slot": round(nav_2s_tot, 4), "mdd_2slot": round(mdd_2s, 4),
        "cum_nav_daily_eq": round(nav_eq, 4), "mdd_daily_eq": round(mdd_eq, 4),
        "csi300_5y_cum": round(CSI300_5Y_CUM, 4),
        "net_excess_5y_1slot": round((nav_1s - 1.0) - CSI300_5Y_CUM, 4),
        "annual": annual, "trades": trades_1s,
    }


def run_v11_master():
    t0 = time.time()
    print("=== [V11 Master] Loading 5Y Prices & Merged 8Y Plates ===")
    df = load_full_5y_prices()
    df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = build_5y_elo_and_candidates_v11(df)
    fb_all = attach_pit_notices_and_scores_v11(df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map)

    # Historical D2 <= 2026-11-10
    hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy()
    hist_fb = compute_d2_auction_scores_v11(hist_fb)

    all_dts = sorted(df["dt_str"].unique())
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
        for r in df[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
    }

    # Precompute B1 trig targets for Walk-Forward Ridge training
    y_b1 = np.full(len(hist_fb), np.nan)
    for i, (_, r) in enumerate(hist_fb.iterrows()):
        if r["is_buyable_open"] and (0.028 <= r["d2_o_pct"] <= 0.076):
            tr = simulate_single_trade(r, price_lookup, all_dts, dt_to_idx, entry_mode="trig", exit_mode="B1", fee=FEE_RATE)
            if tr is not None:
                y_b1[i] = np.clip(tr["net_ret"], -0.15, 0.35)
    hist_fb["y_b1_trig"] = y_b1
    hist_fb["d2_yr"] = hist_fb["d2_dt"].str[:4].astype(int)

    # Fix 5: V11 Common Filter (0.028 <= o_pct <= 0.076 & nuclear_halt with dt_cnt>=18)
    common_ok = (
        hist_fb["is_buyable_open"]
        & (~hist_fb["nuclear_halt"])
        & (~hist_fb["promo_freeze"])
        & hist_fb["d2_o_pct"].between(0.028, 0.076)
        & (hist_fb["s_prior_dual"] >= 35.0)
        & (hist_fb["s_quant_dual"] >= 140.0)
    )

    # V11 Homologous Production Threshold: 230 Base, 255 Climax (+25 when mkt_seal_rate > 0.75)
    v11_base_thr = 230.0
    print(f"[V11 Production Threshold] Base: {v11_base_thr} (Climax +25 -> {v11_base_thr+25.0})")

    # Expanding Walk-Forward Ridge Model
    ml_feats = [
        "s_prior_dual", "s_q_base_dual", "p_elo", "s_elo", "p_sz", "has_new_term", "own_new_term",
        "spark_bonus", "is_ma", "notice_hard", "mkt_seal_rate", "d2_o_pct",
        "buyable_plate_rk", "subbranch_rk", "mkt_open_rk", "buy_open_lead", "plate_d2_yizi_cnt"
    ]
    for c in ml_feats:
        hist_fb[c] = hist_fb[c].fillna(0.0)

    hist_fb["ml_adj"] = 0.0
    hist_fb["wf_dyn_thr"] = v11_base_thr
    wf_models_2026 = None

    for test_yr in [2022, 2023, 2024, 2025, 2026]:
        tr_domain = (hist_fb["d2_yr"] < test_yr) & common_ok
        tr_fit = tr_domain & hist_fb["y_b1_trig"].notna()
        te_mask = (hist_fb["d2_yr"] == test_yr)
        tr_df, te_df = hist_fb[tr_fit], hist_fb[te_mask]
        if len(tr_df) >= 30 and len(te_df) > 0:
            sc = StandardScaler()
            X_tr = sc.fit_transform(tr_df[ml_feats].values)
            y_tr = tr_df["y_b1_trig"].values
            ridge = Ridge(alpha=50.0).fit(X_tr, y_tr)

            p_tr_all = ridge.predict(sc.transform(hist_fb.loc[tr_domain, ml_feats].values))
            p_mean, p_std = float(np.mean(p_tr_all)), float(np.std(p_tr_all) + 1e-6)
            tr_hyb_scores = hist_fb.loc[tr_domain, "tot_dual"].values + np.clip((p_tr_all - p_mean) / p_std, -2.0, 2.0) * 10.0
            n_yrs = float(test_yr - 2021)
            target_cands = max(18, int(35 * n_yrs))
            wf_thr = float(np.sort(tr_hyb_scores)[-target_cands]) if len(tr_hyb_scores) > target_cands else v11_base_thr

            p_te = ridge.predict(sc.transform(te_df[ml_feats].values))
            z_te = np.clip((p_te - p_mean) / p_std, -2.0, 2.0) * 10.0
            hist_fb.loc[te_mask, "ml_adj"] = z_te
            hist_fb.loc[te_mask, "wf_dyn_thr"] = np.where(te_df["mkt_seal_rate"] > 0.75, wf_thr + 25.0, wf_thr)
            if test_yr == 2026:
                wf_models_2026 = (sc, ridge, p_mean, p_std)

    hist_fb["tot_v11_hybrid"] = hist_fb["tot_dual"] + hist_fb["ml_adj"]

    # Dynamic threshold vector for V11 DualElo
    dyn_thr_dual = np.where(hist_fb["mkt_seal_rate"] > 0.75, v11_base_thr + 25.0, v11_base_thr)
    dyn_thr_top290 = np.where(hist_fb["mkt_seal_rate"] > 0.75, 315.0, 290.0)

    m_dual_230 = common_ok & (hist_fb["tot_dual"] >= dyn_thr_dual)
    m_dual_290 = common_ok & (hist_fb["tot_dual"] >= dyn_thr_top290) & (hist_fb["s_prior_dual"] >= 45.0)
    m_hyb = common_ok & (hist_fb["tot_v11_hybrid"] >= hist_fb["wf_dyn_thr"])

    results = {
        "meta": {
            "fee_rate": FEE_RATE,
            "v11_base_thr": v11_base_thr,
            "csi300_annual": CSI300_ANNUAL,
            "csi300_5y_cum": round(CSI300_5Y_CUM, 4),
        },
        "schemes": {},
    }

    configs = [
        ("V11_DualElo_Live230_Trig_E4", "tot_dual", m_dual_230, "trig", "E4"),
        ("V11_DualElo_Live230_Trig_B1", "tot_dual", m_dual_230, "trig", "B1"),
        ("V11_DualElo_Top290_Trig_E4", "tot_dual", m_dual_290, "trig", "E4"),
        ("V11_DualElo_Top290_Trig_B1", "tot_dual", m_dual_290, "trig", "B1"),
        ("V11_Hybrid_WF_Trig_E4", "tot_v11_hybrid", m_hyb, "trig", "E4"),
        ("V11_Hybrid_WF_Trig_B1", "tot_v11_hybrid", m_hyb, "trig", "B1"),
    ]

    print("\n=== [V11 Unified Master] 5Y D15 Walk-Forward Results (2022-2026) ===")
    for name, scol, msk, em, xm in configs:
        res = eval_scheme_d15(hist_fb, scol, msk, price_lookup, all_dts, dt_to_idx, em, xm, FEE_RATE)
        results["schemes"][name] = {k: v for k, v in res.items() if k != "trades"}
        if "Top290" in name or "Live230" in name:
            results[f"ledger_{name}"] = res["trades"]
        print(
            f"{name:<24s} | N={res['total_trades_1slot']:3d} | WR={res['win_rate_5y']*100:5.1f}% | Payoff={res['payoff_5y']:4.2f} "
            f"| 2B={res['seal_2b_5y']*100:5.1f}% | 1S={res['cum_nav_1slot']:6.2f}x (MDD={res['mdd_1slot']*100:4.1f}%) "
            f"| 2S={res['cum_nav_2slot']:6.2f}x | EQ={res['cum_nav_daily_eq']:6.2f}x | Excess={res['net_excess_5y_1slot']*100:+6.1f}%"
        )

    # Today 2026-11-11 Live Evaluation
    live_fb = fb_all[fb_all["dt_str"] == "2026-11-10"].copy()
    live_fb["d2_dt"] = "2026-11-11"
    q_codes = [("sh" + c if c.startswith("6") else "sz" + c) for c in live_fb["c6"].tolist()]
    live_q = {}
    try:
        txt = urllib.request.urlopen("http://qt.gtimg.cn/q=" + ",".join(q_codes), timeout=5).read().decode("gbk", errors="ignore")
        for ln in txt.strip().splitlines():
            if '="' not in ln: continue
            k, v = ln.split('="', 1); p = v.strip('";').split("~")
            if len(p) > 35:
                live_q[k[-6:]] = (float(p[5] or 0), float(p[33] or 0), float(p[34] or 0), float(p[3] or 0))
    except Exception as e:
        print("Live quote warn:", e)

    live_fb["d2_open"] = [live_q.get(c, (0, 0, 0, 0))[0] for c in live_fb["c6"]]
    live_fb["d2_high"] = [live_q.get(c, (0, 0, 0, 0))[1] for c in live_fb["c6"]]
    live_fb["d2_low"] = [live_q.get(c, (0, 0, 0, 0))[2] for c in live_fb["c6"]]
    live_fb["d2_close"] = [live_q.get(c, (0, 0, 0, 0))[3] for c in live_fb["c6"]]
    live_fb["d2_o_pct"] = np.where(live_fb["close"] > 0, live_fb["d2_open"] / live_fb["close"] - 1.0, 0.0)
    live_fb["d2_zt_p"] = np.floor(live_fb["close"] * 1.10 * 100.0 + 0.5) / 100.0
    live_fb["d2_is_yizi"] = (live_fb["d2_open"] >= live_fb["d2_zt_p"] - 0.01) & (live_fb["d2_low"] >= live_fb["d2_zt_p"] - 0.01)
    live_fb = compute_d2_auction_scores_v11(live_fb)

    lv_thr = np.where(live_fb["mkt_seal_rate"] > 0.75, v11_base_thr + 25.0, v11_base_thr)
    lv_com = (
        live_fb["is_buyable_open"]
        & (~live_fb["nuclear_halt"])
        & (~live_fb["promo_freeze"])
        & live_fb["d2_o_pct"].between(0.028, 0.076)
        & (live_fb["s_prior_dual"] >= 35.0)
        & (live_fb["s_quant_dual"] >= 140.0)
    )
    live_fb["ok_v11"] = lv_com & (live_fb["tot_dual"] >= lv_thr)
    live_fb["hit_trig"] = (live_fb["d2_high"] >= live_fb["trig_p"]) & (live_fb["d2_open"] < live_fb["trig_p"])
    live_fb["intraday_pnl"] = np.where(live_fb["hit_trig"], live_fb["d2_close"] / live_fb["trig_p"] - 1.0, 0.0)

    live_top = live_fb.sort_values(["ok_v11", "tot_dual"], ascending=[False, False]).head(10)
    live_records = []
    print(f"\n=== 2026-11-11 Live V11 Top 10 Candidates (Threshold: {float(lv_thr[0]):.1f}) ===")
    for _, r in live_top.iterrows():
        rec = {
            "c6": r["c6"], "name": r["name"], "plate": r["plate"], "r_short": r["r_short"],
            "gate_ok": bool(r["gate_ok"]), "t_rk": int(r["buyable_plate_rk"]), "m_rk": int(r["mkt_open_rk"]),
            "ok_v11": bool(r["ok_v11"]),
            "tot_dual": round(float(r["tot_dual"]), 1), "s_prior": round(float(r["s_prior_dual"]), 1), "s_quant": round(float(r["s_quant_dual"]), 1),
            "o_pct": round(float(r["d2_o_pct"]), 4), "open_p": round(float(r["d2_open"]), 2),
            "trig_p": round(float(r["trig_p"]), 2), "high_p": round(float(r["d2_high"]), 2), "cur_p": round(float(r["d2_close"]), 2),
            "hit_trig": bool(r["hit_trig"]), "intraday_pnl": round(float(r["intraday_pnl"]), 4)
        }
        live_records.append(rec)
        print(
            f"V11_OK={int(rec['ok_v11'])} | {rec['c6']} {rec['name']:<6s} | {rec['plate']}(t_rk={rec['t_rk']},m_rk={rec['m_rk']}) "
            f"| 总分={rec['tot_dual']:5.1f}(先验{rec['s_prior']:4.1f}+量化{rec['s_quant']:4.1f}) "
            f"| 开盘={rec['open_p']:6.2f}({rec['o_pct']*100:+5.2f}%) 点火={rec['trig_p']:6.2f} 现价={rec['cur_p']:6.2f}"
        )
    results["live_20261111"] = live_records

    all_ledger = []
    for k in ("V11_DualElo_Top290_Trig_E4", "V11_DualElo_Top290_Trig_B1", "V11_DualElo_Live230_Trig_E4", "V11_DualElo_Live230_Trig_B1"):
        for t in results.pop(f"ledger_{k}", []):
            tc = dict(t); tc["scheme"] = k; all_ledger.append(tc)
    pd.DataFrame(all_ledger).to_csv(OUT_CSV, index=False, encoding="utf-8")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[DONE] Saved {OUT_JSON} & {OUT_CSV} in {time.time()-t0:.2f}s")


if __name__ == "__main__":
    run_v11_master()
