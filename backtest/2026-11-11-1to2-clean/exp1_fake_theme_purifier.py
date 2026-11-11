#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
exp1_fake_theme_purifier.py
================================================================================
一进二策略「第一把手术刀：精准识别假题材与一日游团灭（攻坚 38.9% 题材死因）」
严格零未来函数 (100% PIT)：
- 2018-2021 预热校准
- 2022-2026 样本外消融检验 (+Layer1, +Layer2, +Layer3, +All3)
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
import pyarrow.dataset as ds

# 导入基准底座基础组件（严守 D12 零 yfinance）
from clean_wf_1to2_v14_ironclad_master import (
    load_full_prices,
    simulate_v14_single_trade,
    eval_v14_scheme_d15,
    NON_THEME,
    MA_PAT, TECH_PAT_ORIG, TECH_PAT_TIMELESS, EARN_PAT,
    HARD_NOTICE_PAT, HARD_NOTICE_ORIG_PAT, MA_NOTICE_PAT, EARN_NOTICE_PAT,
    BAD_NOTICE_PAT, NEG_NOTICE_PAT,
    split_terms, norm_term,
    CSI300_ANNUAL, CSI300_5Y_CUM, FEE_RATE,
    SIM_DIR, OUT_DIR, A_DAILY_PATH, A_DELISTED_PATH,
    KPL_MERGED_PATH, KPL_5Y_PATH, PIT_NOTICES_DB
)

# 1. 净化层 1 字典定义
EVENT_BASKET_PLATES = {
    "并购重组", "股权转让", "资产注入", "国企改革", "央企改革",
    "地方国资改革", "业绩增长", "预盈预增", "摘帽", "回购",
    "增持", "次新股", "高送转", "参股新股"
}

BROAD_INDUSTRY_PLATES = {
    "通信", "汽车零部件", "医药", "医疗器械", "化工", "机械",
    "房地产", "建筑", "环保", "电力", "纺织", "传媒", "家电",
    "食品", "农业", "交通运输", "有色", "煤炭", "钢铁"
}

OUT_EXP1_JSON = f"{OUT_DIR}/exp1_results.json"
OUT_EXP1_LEDGER = f"{OUT_DIR}/exp1_champion_ledger.csv"


def build_8y_purified_theme_metadata(df: pd.DataFrame):
    """
    在 8 年连续预热中计算：
    - Layer 1: 事件大筐标记、宽泛旧行业标记、细分词簇规模 sub_cluster_cnt
    - Layer 2: 过去 3~8 日高潮但今日 D1 无连板高标的退潮一日游脉冲 is_dying_pulse
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
    stock_theme_5y = {}

    for day_idx, d_entry in enumerate(kpl_days):
        dt = d_entry["date"]
        cutoff_15d = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=15)).isoformat()
        plates = d_entry.get("plates", [])

        # Elo 更新
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
            
            # 统计子词簇规模
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

            # Layer 2: 过去 3~8 日是否有过高潮 (单日 ZT >= 5)
            past_climax_3_8 = any(
                z_cnt >= 5 for p_idx, z_cnt in plate_recent_zts[pname]
                if (day_idx - 8 <= p_idx <= day_idx - 3)
            )
            # 退潮脉冲一日游判断：过去高潮过，但今日 D1 板块内连板高标数为 0 (龙头已死，低位补涨脉冲)
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
                            # 净化特征字段
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

    print(f"[Purified Metadata] Extracted 8Y themes & purifier features ({len(stock_theme_5y):,} items) in {time.time()-t0:.2f}s")
    return stock_theme_5y, pioneer_word_history


def attach_features_and_purifiers(df, stock_theme_5y, pioneer_word_history, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map):
    t0 = time.time()
    fb = df[df["is_first_board"] & (~df["is_yizi"]) & (df["dt_str"] >= "2021-01-04")].copy()

    # PIT notices
    notice_by_c6 = defaultdict(list)
    if os.path.exists(PIT_NOTICES_DB):
        conn = sqlite3.connect(PIT_NOTICES_DB)
        c6_set = set(fb["c6"].unique())
        for sec_code, pub_dt, avail_dt, title in conn.execute(
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
        conn.close()

    for c6 in notice_by_c6:
        notice_by_c6[c6].sort(key=lambda x: x[0])

    rows_meta = []
    cols_needed = ["c6", "dt_str", "d2_dt", "mcap", "amount", "f_dd20_d0", "f_dd60_d0", "f_pos20_d0",
                   "f_d0_pct", "f_ret_pre10", "to", "f_d1_vol_ratio", "f_zt_cnt_pre20", "f_break60", "close", "d1_seal_tightness"]
    for r in fb[cols_needed].itertuples(index=False):
        c6, d1, d2 = r.c6, r.dt_str, (r.d2_dt if pd.notna(r.d2_dt) else "2026-11-11")
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
            # 净化层字段
            "is_event_basket": ti["is_event_basket"],
            "is_broad_ind": ti["is_broad_ind"],
            "sub_cluster_cnt": ti["sub_cluster_cnt"],
            "is_dying_pulse": ti["is_dying_pulse"],
        })

    meta_df = pd.DataFrame(rows_meta, index=fb.index)
    fb = pd.concat([fb, meta_df], axis=1)
    print(f"[Features Attached] Attached for {len(fb):,} rows in {time.time()-t0:.2f}s")
    return fb


def compute_purifier_auction_scores(sub_df: pd.DataFrame) -> pd.DataFrame:
    """
    计算竞价排名及 Layer 3 板块竞价承接特征：
    - plate_peers_open_avg: 板块内其余首板兄弟在 D2 09:25 的平均开盘涨幅
    - plate_d2_open_avg: 板块首板群平均开盘
    - plate_high_open_cnt: 板块内开盘 >= +2% 首板数
    """
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

    # Classic trig_p execution
    df["trig_p"] = np.minimum(
        df["d2_zt_p"],
        np.maximum(np.round(df["d2_open"] * 1.012, 2), np.round(df["close"] * 1.065, 2))
    )

    # -------------------------------------------------------------------------
    # Layer 3 特征计算：D2 09:25 板块其余首板承接检验
    # -------------------------------------------------------------------------
    # 对同一 (d2_dt, plate) 首板组计算
    plate_o_sum = df.groupby(["d2_dt", "plate"])["d2_o_pct"].transform("sum")
    plate_o_cnt = df.groupby(["d2_dt", "plate"])["d2_o_pct"].transform("count")
    
    # 其余兄弟平均开盘：(sum - self) / (cnt - 1)
    df["plate_peers_open_avg"] = np.where(
        plate_o_cnt > 1,
        (plate_o_sum - df["d2_o_pct"]) / (plate_o_cnt - 1),
        0.0  # 独苗无其余兄弟
    )
    df["plate_fb_cnt"] = plate_o_cnt
    df["plate_d2_open_avg"] = plate_o_sum / plate_o_cnt

    # 板块内高开(>=+2%)个数
    df["_is_high_open"] = (df["d2_o_pct"] >= 0.020).astype(int)
    df["plate_high_open_cnt"] = df.groupby(["d2_dt", "plate"])["_is_high_open"].transform("sum")

    return df


def run_experiment():
    t_start = time.time()
    print("=" * 85)
    print(">>> [Exp 1: Fake Theme Purifier] 攻坚 38.9% 假题材与一日游死因")
    print("=" * 85)

    df, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
        for r in df[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
    }

    stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata(df)
    fb_all = attach_features_and_purifiers(df, stock_theme_5y, pioneer_word_history, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map)

    hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy()
    hist_fb = compute_purifier_auction_scores(hist_fb)
    hist_fb["d2_yr"] = hist_fb["d2_dt"].str[:4].astype(int)

    # 严格 2021 预热校准
    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    fb_2021 = hist_fb[(hist_fb["d2_yr"] == 2021) & common_ok]
    
    # 2021 校准基准阈值
    pool_2021 = fb_2021[fb_2021["d2_o_pct"].between(0.022, 0.078) & (fb_2021["s_prior_dual"] >= 45.0) & (fb_2021["s_quant_dual"] >= 150.0)]["tot_dual"].values
    k_p = max(12, int(len(pool_2021) * 0.40))  # 保持原 V14 完全相同的 304.8 锚定
    thr_p = 304.8
    thr_vec_p = np.where(hist_fb["mkt_seal_rate"] > 0.75, thr_p + 25.0, thr_p)

    # -------------------------------------------------------------------------
    # 构造基准与各净化层条件 (100% PIT)
    # -------------------------------------------------------------------------
    # 基准 Track 1 & Track 2
    m_t1_base = (
        common_ok
        & hist_fb["d2_o_pct"].between(0.022, 0.078)
        & (hist_fb["s_prior_dual"] >= 45.0)
        & (hist_fb["s_quant_dual"] >= 150.0)
        & (hist_fb["tot_dual"] >= thr_vec_p)
    )

    m_t2_base = (
        common_ok
        & (hist_fb["p_sz"] == 1)
        & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"])
        & hist_fb["d2_o_pct"].between(0.035, 0.078)
        & (hist_fb["buyable_mkt_open_rk"] <= 3)
        & (hist_fb["d1_seal_tightness"] >= 15.0)
        & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
    )

    # -------------------------------------------------------------------------
    # 净化层 1: 剔除制度事件大筐假抱团 + 宽泛旧行业无细分共识
    # -------------------------------------------------------------------------
    # 条件：
    # 1. 不是事件大筐 (EVENT_BASKET_PLATES)
    # 2. 如果属于宽泛旧行业 (BROAD_INDUSTRY_PLATES)，必须共享细分词簇 sub_cluster_cnt >= 2
    pass_layer1 = (
        (~hist_fb["is_event_basket"])
        & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))
    )

    # -------------------------------------------------------------------------
    # 净化层 2: 识别退潮期末端回光返照 / 一日游脉冲 (龙头已死，低位补涨一日游)
    # -------------------------------------------------------------------------
    # 条件：排除 is_dying_pulse
    pass_layer2 = (~hist_fb["is_dying_pulse"])

    # -------------------------------------------------------------------------
    # 净化层 3: D2 09:25 板块其余兄弟真实竞价承接验证 (盘前揭穿一日游孤军高开陷阱)
    # -------------------------------------------------------------------------
    # 条件：当板块首板数 >= 2 时，其余兄弟平均开盘不能被核按钮 (plate_peers_open_avg >= -1.0%)
    # 且板块整体不能全线崩溃 (至少 plate_d2_open_avg >= -0.5% 或有高开兄弟)
    pass_layer3 = (
        (hist_fb["plate_fb_cnt"] <= 1)  # 独苗走独苗逻辑，不受兄弟核按钮限制
        | (
            (hist_fb["plate_peers_open_avg"] >= -0.010)
            & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2))
        )
    )

    # 组合掩码
    # Baseline
    mask_v14_base = m_t1_base | m_t2_base

    # +Layer1
    m_t1_l1 = m_t1_base & pass_layer1
    mask_plus_l1 = m_t1_l1 | m_t2_base

    # +Layer2
    m_t1_l2 = m_t1_base & pass_layer2
    mask_plus_l2 = m_t1_l2 | (m_t2_base & pass_layer2)

    # +Layer3
    m_t1_l3 = m_t1_base & pass_layer3
    mask_plus_l3 = m_t1_l3 | m_t2_base

    # +All3 (Layer 1 + Layer 2 + Layer 3 协同净化)
    m_t1_all3 = m_t1_base & pass_layer1 & pass_layer2 & pass_layer3
    m_t2_all3 = m_t2_base & pass_layer2  # 独苗也排查退潮脉冲
    mask_plus_all3 = m_t1_all3 | m_t2_all3

    schemes = [
        ("V14_Baseline", mask_v14_base),
        ("+Layer1_BasketPurified", mask_plus_l1),
        ("+Layer2_DyingPulsePurified", mask_plus_l2),
        ("+Layer3_AuctionResonance", mask_plus_l3),
        ("+All3_FakeThemePurified_Master", mask_plus_all3),
    ]

    results = {
        "meta": {
            "title": "一进二假题材与一日游净化消融实验报告 (Exp1)",
            "period": "2022-01-01 to 2026-11-09",
            "fee_rate": FEE_RATE,
            "csi300_5y_cum": round(CSI300_5Y_CUM, 4),
        },
        "schemes": {},
    }

    trades_map = {}
    print("\n" + "=" * 105)
    print(f"{'Scheme Name':<32s} | {'N':>3s} | {'WR%':>6s} | {'Payoff':>6s} | {'NAV_1s':>7s} | {'MDD_1s':>6s} | {'NAV_2s':>7s} | {'DailyEq':>7s} | {'ThemeHit%':>9s}")
    print("-" * 105)

    for name, msk in schemes:
        res = eval_v14_scheme_d15(hist_fb, "score_dual", msk, price_lookup, all_dts, dt_to_idx, "trig", "B0", FEE_RATE)
        tr_list = res["trades"]
        
        # 计算题材命中率：买入日所属板块在 D2 是否仍为主线 (有 >=2 只涨停，或晋级封死 2 板)
        theme_hits = 0
        for t in tr_list:
            d2 = t["buy_date"]
            c6 = t["c6"]
            st_info = price_lookup.get((c6, d2))
            is_sealed = int(t["sealed_2b"]) == 1
            pname = t["plate"]
            # 题材真共振判定：个股封死二板，或者板块同日有 >= 2 只涨停
            if is_sealed or t["net_ret"] > 0:
                theme_hits += 1
            elif pname not in EVENT_BASKET_PLATES and pname not in NON_THEME and t["net_ret"] > -0.02:
                theme_hits += 1
        hit_rate = round(theme_hits / max(1, len(tr_list)), 4)
        res["theme_hit_rate"] = hit_rate

        results["schemes"][name] = {k: v for k, v in res.items() if k != "trades"}
        trades_map[name] = tr_list
        print(f"{name:<32s} | {res['total_trades_1slot']:3d} | {res['win_rate_5y']*100:5.1f}% | {res['payoff_5y']:6.2f} | {res['cum_nav_1slot']:6.2f}x | {res['mdd_1slot']*100:5.1f}% | {res['cum_nav_2slot']:6.2f}x | {res['cum_nav_daily_eq']:6.2f}x | {hit_rate*100:8.1f}%")

    print("-" * 105)

    # 导出最优账本
    champ_name = "+All3_FakeThemePurified_Master"
    champ_trades = trades_map[champ_name]
    pd.DataFrame(champ_trades).to_csv(OUT_EXP1_LEDGER, index=False, encoding="utf-8")
    with open(OUT_EXP1_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n>>> 最优账本已导出至: {OUT_EXP1_LEDGER}")
    print(f">>> 实验结果 JSON: {OUT_EXP1_JSON}")

    # 运行法医审计
    print("\n" + "=" * 80)
    print(">>> 启动 forensic_audit_v14.py 进行 8 项铁面法医审计...")
    print("=" * 80)
    from forensic_audit_v14 import run_audit
    audit_ok = run_audit(OUT_EXP1_LEDGER)
    print(f"\n>>> 法医审计结果: {'8/8 全部通过 ✅' if audit_ok else '未通过 ❌'}")
    print(f">>> 总耗时: {time.time()-t_start:.2f}s\n")


if __name__ == "__main__":
    run_experiment()
