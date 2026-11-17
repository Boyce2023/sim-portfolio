#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
v10_pit_and_sim.py — PIT Notices (<= D2 09:25:00) + M2_Clean / DualElo / Hybrid WF Scoring & D15 Simulator
"""
import bisect
import datetime
import sqlite3
import time
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from v10_core_features import (
    PIT_NOTICES_DB, HARD_NOTICE_PAT, HARD_NOTICE_ORIG_PAT,
    MA_NOTICE_PAT, EARN_NOTICE_PAT, BAD_NOTICE_PAT
)

# Official Tencent sh000300 closes verified: 2020=5211.29, 2021=4940.37, 2022=3871.63, 2023=3431.11, 2024=3934.91, 2025=4629.94, 2026-11-10=4059.11
CSI300_ANNUAL = {2022: -0.2163, 2023: -0.1138, 2024: 0.1468, 2025: 0.1766, 2026: -0.1233}
CSI300_5Y_CUM = 4059.11 / 4940.37 - 1.0  # -17.84%
FEE_RATE = 0.0020  # Realistic 0.20% round-trip (stamp + comm + slippage)


def attach_pit_notices_and_scores(df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map):
    t0 = time.time()
    fb = df[df["is_first_board"] & (~df["is_yizi"]) & (df["dt_str"] >= "2021-01-04")].copy()

    # Load PIT notices strictly ordered by pub_datetime_cst
    notice_by_c6 = defaultdict(list)
    if sqlite3:
        conn = sqlite3.connect(PIT_NOTICES_DB)
        c6_set = set(fb["c6"].unique())
        for sec_code, pub_dt, avail_dt, title in conn.execute(
            "SELECT sec_code, pub_datetime_cst, trade_date_avail, title FROM notices WHERE pub_datetime_cst >= '2020-12-25'"
        ):
            c6 = str(sec_code)[:6].zfill(6)
            if c6 not in c6_set or not pub_dt:
                continue
            ts = str(title or "")
            flags = (
                bool(HARD_NOTICE_ORIG_PAT.search(ts)),
                bool(HARD_NOTICE_PAT.search(ts)),
                bool(MA_NOTICE_PAT.search(ts)),
                bool(EARN_NOTICE_PAT.search(ts)),
                bool(BAD_NOTICE_PAT.search(ts)),
            )
            if any(flags):
                notice_by_c6[c6].append((str(pub_dt), str(avail_dt or ""), flags))
        conn.close()
    for c6 in notice_by_c6:
        notice_by_c6[c6].sort(key=lambda x: x[0])

    # Extract per-row theme & PIT notice attributes
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
        # Strict PIT notice check: [d1 - 4 days, d2 + ' 09:25:00'] AND avail_dt <= d2
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

        is_st = "ST" in ti["name"].upper() or "退" in ti["name"]
        is_ma_f = bool(ti["is_ma"] or n_ma)
        is_earn_f = bool(ti["is_earn"] or n_earn)

        # 1. Exact M2_Clean s_prior (with PIT notices!)
        rk_o, p_sz = ti["rk_o"], ti["p_sz"]
        s_prior_orig = (
            (28 if rk_o == 1 else (16 if rk_o == 2 else (8 if rk_o == 3 else 0)))
            + (18 if p_sz >= 4 else (10 if p_sz >= 2 else -15))
            + (15 if ti["has_new"] else 0) + (10 if ti["spark"] > 0 else 0)
            + (18 if nh_o else 0) + (18 if is_ma_f else 0) + (16 if ti["is_tech_o"] else 0)
            + (12 if ti["gap_o"] >= 20.0 else 0)
            + float(np.clip((ti["t_score_o"] - 100.0) * 0.25, 0.0, 25.0))
        )
        # 2. Hindsight-free Dual-Layer Elo s_prior_dual (no 2026 buzzword peeking + sub-theme Elo + own new term)
        rk_c = ti["rk_c"]
        s_prior_dual = (
            (28 if rk_c == 1 else (16 if rk_c == 2 else (8 if rk_c == 3 else 0)))
            + (18 if p_sz >= 4 else (10 if p_sz >= 2 else -15))
            + (12 if ti["has_new"] else 0) + (8 if ti["own_new"] else 0) + (10 if ti["spark"] > 0 else 0)
            + (18 if nh_c else 0) + (18 if is_ma_f else 0) + (12 if ti["is_tech_c"] else 0)
            + (12 if ti["gap_c"] >= 20.0 else 0)
            + float(np.clip((ti["t_score_c"] - 100.0) * 0.25, 0.0, 25.0))
            + float(np.clip((ti["s_elo"] - 100.0) * 0.35, -10.0, 18.0))
        )

        # 3. Static Micro-Chip Base Score s_q_base (Exact M2 vs Dual-Channel Breakout Upgrade)
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
        # Dual-channel compatibility: clean low-slope 60D platform breakout (ret10 <= 8%, zt20 == 0, to <= 14%)
        clean_brk60 = (brk60 == 1) and (ret10 <= 0.08) and (zt20 == 0) and (to <= 14.0)
        if clean_brk60:
            s_q_base_dual = (
                sc_mcap + sc_amt + 24 + sc_d0 + sc_ret10 + sc_to + sc_vol
                + sc_mkt_seal + sc_mkt_dt + sc_mkt_zt
            )
        else:
            s_q_base_dual = s_q_base_orig

        gate_ok = bool(
            (not is_st) and (not is_earn_f) and (not n_bad)
            and (18.0 <= mcap <= 220.0) and (to <= 20.0)
            and (not (zt20 >= 4 and pos20 > 0.38))
        )
        tot_thr = 255.0 if seal_r > 0.75 else 230.0
        rows_meta.append((
            ti["name"], ti["plate"], ti["r_short"], ti["p_elo"], ti["s_elo"], p_sz, ti["n_yizi"],
            int(ti["has_new"]), int(ti["own_new"]), ti["spark"], int(is_ma_f), int(nh_c), int(n_bad),
            s_prior_orig, s_prior_dual, s_q_base_orig, s_q_base_dual, gate_ok,
            seal_r, promo5, tot_thr, int(clean_brk60)
        ))

    mcols = [
        "name", "plate", "r_short", "p_elo", "s_elo", "p_sz", "d1_n_yizi",
        "has_new_term", "own_new_term", "spark_bonus", "is_ma", "notice_hard", "notice_bad",
        "s_prior_orig", "s_prior_dual", "s_q_base_orig", "s_q_base_dual", "gate_ok",
        "mkt_seal_rate", "mkt_promo_ma5", "tot_thr", "clean_brk60"
    ]
    mdf = pd.DataFrame(rows_meta, index=fb.index, columns=mcols)
    fb = pd.concat([fb, mdf], axis=1)
    print(f"[PIT+Static] Scored {len(fb):,} turnover first-boards in {time.time()-t0:.2f}s")
    return fb
