#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD022 Part 1 - Step 1: Historical 20cm Waves, PIT Golden Beta Days & 6-Dim Micro-Truth Dissection."""

import bisect
import datetime
import json
import os
import sqlite3
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part1_beta_waves"

MKT_PQ = f"{OUT_DIR}/market_daily.parquet"
P20_PQ = f"{OUT_DIR}/panel_20cm.parquet"
KPL_JSONL = f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl"
LHB_PQ = f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117/clean_lhb_5y.parquet"
BAYES_PQ = f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117/bayes_seat_scores_d1_5y.parquet"
TOX_PQ = f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet"
NOTICES_DB = f"{SIM}/data/cninfo_notices_5y_pit.db"
IR_DB = f"{SIM}/data/cninfo_ir_qa_5y_pit.db"
XQ_DB = f"{SIM}/data/xueqiu_guba_5y_pit.db"
ZT_DB = f"{SIM}/data/zt_micro_tape_5y_pit.db"

NAMED_WAVES = [
    ("W1_2021.05_08_锂电半导体", "2021-05-06", "2021-08-31"),
    ("W2_2022.05_06_光伏汽车", "2022-04-27", "2022-07-05"),
    ("W3_2023.02_05_AI_CPO", "2023-01-30", "2023-05-31"),
    ("W4_2024.02_超跌反弹", "2024-02-06", "2024-03-15"),
    ("W5_2024.09_11_924牛市", "2024-09-24", "2024-11-15"),
    ("W6_2025.02_DS机器人", "2025-02-05", "2025-03-14"),
    ("W7_2025.07_09_科技主升", "2025-07-01", "2025-09-30"),
    ("W8_2026.02_春躁脉冲", "2026-02-02", "2026-03-10"),
    ("W9_2026.07_暑期波段", "2026-07-01", "2026-07-31"),
    ("W10_2026.11_近期波段", "2026-11-02", "2026-11-23"),
]

# IS calibrated positive/negative seat codes from RD016
IS_GOOD_CODES = {
    "10430845", "10102873", "10046704", "10023415", "10026767", "10142874",
    "10122927", "10045035", "10025390", "10147201", "10318896",
}


def load_kpl_2021_2026():
    """Load KPL plates and map (date, c6) -> list of (plate_name, plate_rank_idx, sub_tag)."""
    kpl_by_dt = {}
    with open(KPL_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            dt = obj.get("date", "")
            if "2021-01-04" <= dt <= "2026-11-23":
                kpl_by_dt[dt] = obj.get("plates", [])
    return kpl_by_dt


def detect_pit_20cm_waves(mkt: pd.DataFrame):
    """Objective PIT detector: 20cm 10d excess vs HS300 >= +6% or 5d avg ZT20 >= 10 or 5d avg bigup10 >= 25."""
    m = mkt[mkt["dt"] >= "2021-01-04"].copy().reset_index(drop=True)
    m["r10_20"] = m["ew_idx_20cm"] / m["ew_idx_20cm"].shift(10) - 1.0
    m["r10_hs"] = m["sh000300"] / m["sh000300"].shift(10) - 1.0
    m["ex10"] = m["r10_20"] - m["r10_hs"]
    m["zt20_ma5"] = m["zt_20cm_cnt"].rolling(5).mean()
    m["big10_ma5"] = m["bigup10_20cm_cnt"].rolling(5).mean()
    active = (m["ex10"] >= 0.06) | (m["zt20_ma5"] >= 10.0) | (m["big10_ma5"] >= 25.0)
    # Merge gaps <= 7 trading days, keep episodes >= 5 trading days
    idx_on = np.where(active)[0]
    episodes = []
    if len(idx_on) > 0:
        s = e = idx_on[0]
        for idx in idx_on[1:]:
            if idx - e <= 7:
                e = idx
            else:
                if e - s + 1 >= 5:
                    episodes.append((s, e))
                s = e = idx
        if e - s + 1 >= 5:
            episodes.append((s, e))
    out = []
    for i, (s, e) in enumerate(episodes, 1):
        sub = m.iloc[s : e + 1]
        r20 = float(m.iloc[e]["ew_idx_20cm"] / m.iloc[max(0, s - 1)]["ew_idx_20cm"] - 1.0)
        rhs = float(m.iloc[e]["sh000300"] / m.iloc[max(0, s - 1)]["sh000300"] - 1.0)
        out.append({
            "pit_wave_id": f"PIT_W{i}",
            "start_dt": m.iloc[s]["dt"],
            "end_dt": m.iloc[e]["dt"],
            "n_days": int(e - s + 1),
            "ew_20cm_ret_pct": round(r20 * 100, 2),
            "hs300_ret_pct": round(rhs * 100, 2),
            "excess_vs_hs300_pp": round((r20 - rhs) * 100, 2),
            "avg_zt20": round(float(sub["zt_20cm_cnt"].mean()), 1),
            "avg_amt_trillion": round(float(sub["tot_amt_trillion"].mean()), 3),
        })
    return out


def main():
    t0 = time.time()
    print("[Step 1] Loading base tables...")
    mkt = pd.read_parquet(MKT_PQ)
    p20 = pd.read_parquet(P20_PQ)

    # Compute rolling technicals needed for Module 1 characterization
    p20 = p20.sort_values(["c6", "dt"]).reset_index(drop=True)
    g = p20.groupby("c6", sort=False)
    p20["ma20"] = g["adj_close"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    p20["prev_ma20"] = g["ma20"].shift(1)
    p20["prev_adj_c_5"] = g["adj_close"].shift(5)
    p20["prev_adj_c_20"] = g["adj_close"].shift(20)
    p20["prev_ret5"] = p20["prev_adj_c"] / p20["prev_adj_c_5"] - 1.0
    p20["prev_ret20"] = p20["prev_adj_c"] / p20["prev_adj_c_20"] - 1.0
    p20["prev_above_ma20"] = p20["prev_adj_c"] > p20["prev_ma20"]

    sub20 = p20[(p20["dt"] >= "2021-01-04") & (p20["dt"] <= "2026-11-23") & p20["is_clean_universe"]].copy()
    sub20["is_bigup"] = sub20["ret"] >= 0.07  # +7%+ 20cm big-up
    sub20["is_10p"] = sub20["ret"] >= 0.10

    # Also load 10cm ZT codes by date from zt_micro_tape for 10cm vs 20cm KPL comparison
    conn_zt = sqlite3.connect(f"file:{ZT_DB}?mode=ro", uri=True)
    zt_df = pd.read_sql_query("SELECT trade_date, sec_code FROM zt_micro_tape WHERE trade_date >= '2021-01-04'", conn_zt)
    conn_zt.close()
    zt10_by_dt = defaultdict(set)
    for dt, sc in zip(zt_df["trade_date"], zt_df["sec_code"]):
        c6 = str(sc)[:6]
        if not c6.startswith(("30", "688", "689")):
            zt10_by_dt[dt].add(c6)

    # Load KPL plates (filtering out NON_THEME generic labels)
    NON_THEME = {
        "其他", "公告", "ST板块", "科创板", "三季报增长", "业绩增长", "半年报增长",
        "年报增长", "一季报增长", "中报增长", "次新股", "新股与次新股", "北交所",
        "预盈预增", "回购", "增持", "高送转", "摘帽",
    }
    print("[Step 1] Loading KPL plates...")
    kpl_by_dt = load_kpl_2021_2026()
    stock_kpl_top = {}  # (dt, c6) -> top plate name
    plate_20_10_by_dt = defaultdict(lambda: Counter())
    for dt, plates in kpl_by_dt.items():
        z10_set = zt10_by_dt.get(dt, set())
        for rk, pl in enumerate(plates):
            pname = pl.get("plate", "")
            if pname in NON_THEME or not pname:
                continue
            for s in pl.get("stocks", []):
                c6 = str(s[0]).strip()[:6].zfill(6)
                if (dt, c6) not in stock_kpl_top:
                    stock_kpl_top[(dt, c6)] = pname
                if c6 in z10_set:
                    plate_20_10_by_dt[dt][pname] += 1

    # Load LHB & Bayes
    print("[Step 1] Loading LHB & Bayes seat scores...")
    lhb = pd.read_parquet(LHB_PQ)
    lhb20 = lhb[lhb["stock_code"].astype(str).str.startswith(("30", "688", "689")) & (lhb["is_three"] == 0)].copy()
    lhb20["is_org"] = lhb20["dept_name"].str.contains("机构专用", na=False) | (lhb20["dept_code"] == "0")
    lhb20["is_lhasa"] = lhb20["dept_name"].str.contains("拉萨", na=False) & (~lhb20["dept_name"].str.contains("东亚", na=False))
    lhb20["is_north"] = lhb20["dept_name"].str.contains("深股通|沪股通", na=False)
    lhb20["is_famous_good"] = lhb20["dept_code"].isin(IS_GOOD_CODES)

    # Per-(dt, c6) LHB summary
    lhb_evt = {}
    for (dt, sc), grp in lhb20.groupby(["date", "stock_code"], sort=False):
        b = grp[grp["side"] == "B"]
        tot_b = float(b["BUY"].sum())
        org_net = float(grp[grp["is_org"]]["NET"].sum())
        org_b = float(b[b["is_org"]]["BUY"].sum())
        lh_b = float(b[b["is_lhasa"]]["BUY"].sum())
        lh_net = float(grp[grp["is_lhasa"]]["NET"].sum())
        north_net = float(grp[grp["is_north"]]["NET"].sum())
        good_b = float(b[b["is_famous_good"]]["BUY"].sum())
        lhb_evt[(dt, sc)] = (tot_b, org_net, org_b, lh_b, lh_net, north_net, good_b)

    # Notices: Positive Earnings Pre-announcement (consistent 2021-2026)
    print("[Step 1] Loading CNINFO Earnings Notices, IR QA, Reg-Tox & Community...")
    conn_n = sqlite3.connect(f"file:{NOTICES_DB}?mode=ro", uri=True)
    earn_pos_by_c6 = defaultdict(list)
    for sc, avail_dt, atype in conn_n.execute(
        "SELECT sec_code, trade_date_avail, ann_type FROM notices WHERE (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%') AND ann_type LIKE '业绩预告:%'"
    ):
        if any(k in str(atype) for k in ("预增", "略增", "扭亏", "减亏")):
            earn_pos_by_c6[str(sc)[:6]].append(str(avail_dt)[:10])
    conn_n.close()
    for c6 in earn_pos_by_c6:
        earn_pos_by_c6[c6].sort()

    # IR QA
    conn_ir = sqlite3.connect(f"file:{IR_DB}?mode=ro", uri=True)
    ir_by_c6 = defaultdict(list)
    for sc, avail_dt in conn_ir.execute(
        "SELECT sec_code, trade_date_avail FROM ir_qa WHERE sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%'"
    ):
        ir_by_c6[str(sc)[:6]].append(str(avail_dt)[:10])
    conn_ir.close()
    for c6 in ir_by_c6:
        ir_by_c6[c6].sort()

    # Reg Tox
    tox = pd.read_parquet(TOX_PQ)
    tox20 = tox[tox["sec_code"].astype(str).str.startswith(("30", "688", "689"))].copy()
    tox20["dt"] = tox20["pub_datetime_cst"].astype(str).str[:10]
    tox_by_c6 = defaultdict(list)
    for sc, dt in zip(tox20["sec_code"], tox20["dt"]):
        tox_by_c6[str(sc)[:6]].append(dt)
    for c6 in tox_by_c6:
        tox_by_c6[c6].sort()

    # Community (STRICTLY restricted to crawled ZT events in crawl_progress!)
    conn_xq = sqlite3.connect(f"file:{XQ_DB}?mode=ro", uri=True)
    # Crawled tasks for guba (only valid 2021-2024!) & xueqiu (all years where task exists)
    gb_df = pd.read_sql_query(
        "SELECT sec_code, pub_time, read_cnt, comment_cnt, d1_date FROM guba_posts WHERE (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%') AND pub_time >= '2020-12-20'",
        conn_xq,
    )
    xq_df = pd.read_sql_query(
        "SELECT symbol, created_time_str, reply_count, d1_date FROM xueqiu_posts WHERE (symbol LIKE '30%' OR symbol LIKE '688%' OR symbol LIKE '689%') AND created_time_str >= '2020-12-20'",
        conn_xq,
    )
    conn_xq.close()

    # Pre-aggregate pre-ZT 3d post counts strictly on (c6, d1_date) pairs present in gb_df / xq_df
    gb_df["pub_d"] = gb_df["pub_time"].str[:10]
    gb_3d = {}
    for (sc, d1), grp in gb_df.groupby(["sec_code", "d1_date"], sort=False):
        d_cut = (datetime.date.fromisoformat(d1) - datetime.timedelta(days=3)).isoformat()
        pre = grp[(grp["pub_d"] >= d_cut) & (grp["pub_time"] < f"{d1} 15:00:00")]
        gb_3d[(sc, d1)] = (len(pre), int(pre["read_cnt"].sum()), int(pre["comment_cnt"].sum()))

    xq_df["pub_d"] = xq_df["created_time_str"].str[:10]
    xq_3d = {}
    for (sc, d1), grp in xq_df.groupby(["symbol", "d1_date"], sort=False):
        d_cut = (datetime.date.fromisoformat(d1) - datetime.timedelta(days=3)).isoformat()
        pre = grp[(grp["pub_d"] >= d_cut) & (grp["created_time_str"] < f"{d1} 15:00:00")]
        xq_3d[(sc, d1)] = len(pre)

    # Helper to count events in [dt - lookback_days, dt - 1] (or <= dt)
    def has_recent(ev_map, c6, dt, days):
        arr = ev_map.get(c6)
        if not arr:
            return False
        lo = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=days)).isoformat()
        i = bisect.bisect_left(arr, lo)
        return i < len(arr) and arr[i] <= dt

    # 1. Objective PIT waves
    pit_waves = detect_pit_20cm_waves(mkt)

    # 2. Dissect Named Waves + Golden Beta Days
    mkt_map = mkt.set_index("dt")
    wave_rows = []
    wave_details = {}

    # Also evaluate Golden Beta Days as a special slice
    beta_dts = set(mkt[(mkt["dt"] >= "2021-01-04") & (mkt["ew_ret_all"] >= 0.02) & (mkt["up_ratio_all"] >= 0.80)]["dt"])
    beta_1t_dts = set(mkt[(mkt["dt"] >= "2021-01-04") & (mkt["ew_ret_all"] >= 0.02) & (mkt["up_ratio_all"] >= 0.80) & (mkt["amt_ma20_trillion"] >= 1.0)]["dt"])

    slices = [(nm, s, e, None) for nm, s, e in NAMED_WAVES] + [
        ("BETA_ALL_全A等权>=2%_红盘>=80%", "2021-01-04", "2026-11-23", beta_dts),
        ("BETA_1T_黄金期(20日均额>=1万亿)", "2021-01-04", "2026-11-23", beta_1t_dts),
    ]

    for wname, s_dt, e_dt, dt_filter in slices:
        if dt_filter is None:
            m_sub = mkt[(mkt["dt"] >= s_dt) & (mkt["dt"] <= e_dt)]
            m_pre = mkt[mkt["dt"] < s_dt].tail(10)
            s_sub = sub20[(sub20["dt"] >= s_dt) & (sub20["dt"] <= e_dt)]
        else:
            m_sub = mkt[mkt["dt"].isin(dt_filter)]
            m_pre = pd.DataFrame()
            s_sub = sub20[sub20["dt"].isin(dt_filter)]

        if len(m_sub) == 0:
            continue

        # Wave cumulative returns (for continuous waves)
        if dt_filter is None:
            idx_prev = mkt[mkt["dt"] < s_dt].iloc[-1]
            r20_cum = float(m_sub.iloc[-1]["ew_idx_20cm"] / idx_prev["ew_idx_20cm"] - 1.0)
            rhs_cum = float(m_sub.iloc[-1]["sh000300"] / idx_prev["sh000300"] - 1.0)
            rcyb_cum = float((1.0 + m_sub["ew_ret_cyb"]).prod() - 1.0)
            rkcb_cum = float((1.0 + m_sub["ew_ret_kcb"]).prod() - 1.0)
        else:
            r20_cum = float(m_sub["ew_ret_20cm"].mean())
            rhs_cum = float(m_sub["sh000300_ret"].mean())
            rcyb_cum = float(m_sub["ew_ret_cyb"].mean())
            rkcb_cum = float(m_sub["ew_ret_kcb"].mean())

        bigup = s_sub[s_sub["is_bigup"]].copy()
        zt20_sub = s_sub[s_sub["is_zt"]].copy()

        # Dim 1: KPL themes (20cm bigup vs 10cm ZT)
        c_20_theme = Counter()
        for dt, c6 in zip(bigup["dt"], bigup["c6"]):
            pl = stock_kpl_top.get((dt, c6))
            if pl:
                c_20_theme[pl] += 1
        c_10_theme = Counter()
        for dt in m_sub["dt"]:
            c_10_theme.update(plate_20_10_by_dt.get(dt, {}))
        top3_20 = c_20_theme.most_common(3)
        top3_10 = [p for p, _ in c_10_theme.most_common(3)]
        overlap_10 = sum(1 for dt, c6 in zip(bigup["dt"], bigup["c6"]) if stock_kpl_top.get((dt, c6)) in top3_10)
        kpl_cov = sum(1 for dt, c6 in zip(bigup["dt"], bigup["c6"]) if (dt, c6) in stock_kpl_top)
        overlap_rate = overlap_10 / max(kpl_cov, 1)

        # Dim 2: LHB buyers on 20cm bigup / ZT
        lhb_matched = [lhb_evt[(dt, c6)] for dt, c6 in zip(bigup["dt"], bigup["c6"]) if (dt, c6) in lhb_evt]
        if lhb_matched:
            tot_b_sum = sum(x[0] for x in lhb_matched)
            org_b_sum = sum(x[2] for x in lhb_matched)
            org_net_sum = sum(x[1] for x in lhb_matched)
            lh_b_sum = sum(x[3] for x in lhb_matched)
            north_net_sum = sum(x[5] for x in lhb_matched)
            good_b_sum = sum(x[6] for x in lhb_matched)
            org_share = org_b_sum / tot_b_sum if tot_b_sum > 0 else 0.0
            lh_share = lh_b_sum / tot_b_sum if tot_b_sum > 0 else 0.0
            good_share = good_b_sum / tot_b_sum if tot_b_sum > 0 else 0.0
            org_net_pos_pct = sum(1 for x in lhb_matched if x[1] > 0) / len(lhb_matched)
        else:
            org_share = lh_share = good_share = org_net_pos_pct = 0.0
            org_net_sum = north_net_sum = 0.0

        # Dim 3: Community heat on ZT events (ONLY within covered ZT pairs!)
        zt_pairs = list(zip(zt20_sub["c6"], zt20_sub["dt"], zt20_sub["retB_t2"]))
        gb_low, gb_high = [], []
        xq_low, xq_high = [], []
        for c6, dt, r_t2 in zt_pairs:
            if (c6, dt) in gb_3d and pd.notna(r_t2):
                cnt = gb_3d[(c6, dt)][0]
                if cnt < 4:
                    gb_low.append(r_t2)
                else:
                    gb_high.append(r_t2)
            if (c6, dt) in xq_3d and pd.notna(r_t2):
                cntx = xq_3d[(c6, dt)]
                if cntx < 4:
                    xq_low.append(r_t2)
                else:
                    xq_high.append(r_t2)

        # Dim 4: Notices (earn_pos 60d), IR QA (30d), Reg-Tox (90d)
        e_flags = [has_recent(earn_pos_by_c6, c6, dt, 60) for c6, dt in zip(bigup["c6"], bigup["dt"])]
        ir_flags = [has_recent(ir_by_c6, c6, dt, 30) for c6, dt in zip(bigup["c6"], bigup["dt"])]
        tox_flags = [has_recent(tox_by_c6, c6, dt, 90) for c6, dt in zip(bigup["c6"], bigup["dt"])]
        bigup["has_earn60"] = e_flags
        bigup["has_ir30"] = ir_flags
        bigup["has_tox90"] = tox_flags

        def mean_ret(mask, col="retA_t2"):
            v = bigup.loc[mask, col].dropna()
            return round(float(v.mean() * 100), 2) if len(v) >= 5 else None

        # Dim 5: Size, turn, position, CYB vs KCB
        cyb_cnt = int((~bigup["is_star"]).sum())
        kcb_cnt = int(bigup["is_star"].sum())

        row = {
            "wave": wname,
            "start_dt": s_dt if dt_filter is None else str(m_sub["dt"].min()),
            "end_dt": e_dt if dt_filter is None else str(m_sub["dt"].max()),
            "n_days": int(len(m_sub)),
            "ew_20cm_pct": round(r20_cum * 100, 2),
            "hs300_pct": round(rhs_cum * 100, 2),
            "excess_20cm_vs_hs300_pp": round((r20_cum - rhs_cum) * 100, 2),
            "cyb_ew_pct": round(rcyb_cum * 100, 2),
            "kcb_ew_pct": round(rkcb_cum * 100, 2),
            "amt_trillion_avg": round(float(m_sub["tot_amt_trillion"].mean()), 3),
            "amt_pre10d_trillion": round(float(m_pre["tot_amt_trillion"].mean()), 3) if len(m_pre) > 0 else None,
            "promo_1to2_avg_pct": round(float(m_sub["yest_1b_promo_rate"].mean() * 100), 1),
            "zt20_daily_avg": round(float(m_sub["zt_20cm_cnt"].mean()), 1),
            "bigup7_n": int(len(bigup)),
            "zt20_n": int(len(zt20_sub)),
            "top3_20cm_kpl": "; ".join(f"{k}({v})" for k, v in top3_20),
            "top3_10cm_kpl": "; ".join(top3_10),
            "kpl_10_20_overlap_pct": round(overlap_rate * 100, 1),
            "lhb_n": int(len(lhb_matched)),
            "lhb_org_buy_share_pct": round(org_share * 100, 1),
            "lhb_org_net_yi": round(org_net_sum / 1e8, 2),
            "lhb_org_net_pos_pct": round(org_net_pos_pct * 100, 1),
            "lhb_famous_good_share_pct": round(good_share * 100, 1),
            "lhb_lhasa_buy_share_pct": round(lh_share * 100, 1),
            "lhb_north_net_yi": round(north_net_sum / 1e8, 2),
            "gb_cov_n": int(len(gb_low) + len(gb_high)),
            "gb_low_lt4_t2_pct": round(float(np.mean(gb_low) * 100), 2) if len(gb_low) >= 5 else None,
            "gb_high_ge4_t2_pct": round(float(np.mean(gb_high) * 100), 2) if len(gb_high) >= 5 else None,
            "xq_cov_n": int(len(xq_low) + len(xq_high)),
            "xq_low_lt4_t2_pct": round(float(np.mean(xq_low) * 100), 2) if len(xq_low) >= 5 else None,
            "xq_high_ge4_t2_pct": round(float(np.mean(xq_high) * 100), 2) if len(xq_high) >= 5 else None,
            "earn_pos60_pct": round(float(np.mean(e_flags) * 100), 1) if len(e_flags) else 0.0,
            "ir_qa30_pct": round(float(np.mean(ir_flags) * 100), 1) if len(ir_flags) else 0.0,
            "reg_tox90_pct": round(float(np.mean(tox_flags) * 100), 1) if len(tox_flags) else 0.0,
            "ir_qa30_t2_pct": mean_ret(bigup["has_ir30"] == True),
            "no_ir30_t2_pct": mean_ret(bigup["has_ir30"] == False),
            "tox90_t2_pct": mean_ret(bigup["has_tox90"] == True),
            "clean_notox_t2_pct": mean_ret(bigup["has_tox90"] == False),
            "med_mcap_yi": round(float(bigup["circ_mcap"].median()), 1) if len(bigup) else None,
            "share_lt50yi_pct": round(float((bigup["circ_mcap"] < 50).mean() * 100), 1) if len(bigup) else None,
            "share_gt150yi_pct": round(float((bigup["circ_mcap"] >= 150).mean() * 100), 1) if len(bigup) else None,
            "med_turn_pct": round(float(bigup["turn"].median() * 100), 2) if len(bigup) else None,
            "med_prev_ret5_pct": round(float(bigup["prev_ret5"].median() * 100), 2) if len(bigup) else None,
            "med_prev_ret20_pct": round(float(bigup["prev_ret20"].median() * 100), 2) if len(bigup) else None,
            "above_ma20_pct": round(float(bigup["prev_above_ma20"].mean() * 100), 1) if len(bigup) else None,
            "cyb_bigup_n": cyb_cnt,
            "kcb_bigup_n": kcb_cnt,
            "kcb_share_pct": round(kcb_cnt / max(len(bigup), 1) * 100, 1),
        }
        wave_rows.append(row)

    # Save outputs
    wdf = pd.DataFrame(wave_rows)
    wdf.to_csv(f"{OUT_DIR}/module1_waves_table.csv", index=False)

    b_df = mkt[(mkt["dt"] >= "2021-01-04") & (mkt["ew_ret_all"] >= 0.02) & (mkt["up_ratio_all"] >= 0.80)].copy()
    b_df.to_csv(f"{OUT_DIR}/module1_beta_days.csv", index=False)

    # Yearly LHB structural evolution across all 20cm big-up days (2021-2026)
    sub20_big = sub20[sub20["is_bigup"]].copy()
    sub20_big["yr"] = sub20_big["dt"].str[:4]
    yr_lhb = []
    for yr, grp in sub20_big.groupby("yr"):
        lm = [lhb_evt[(dt, c6)] for dt, c6 in zip(grp["dt"], grp["c6"]) if (dt, c6) in lhb_evt]
        if lm:
            tb = sum(x[0] for x in lm)
            yr_lhb.append({
                "year": yr, "bigup_n": int(len(grp)), "lhb_n": len(lm),
                "org_buy_share_pct": round(sum(x[2] for x in lm) / tb * 100, 1) if tb else 0,
                "org_net_yi": round(sum(x[1] for x in lm) / 1e8, 2),
                "good_youzi_share_pct": round(sum(x[6] for x in lm) / tb * 100, 1) if tb else 0,
                "lhasa_buy_share_pct": round(sum(x[3] for x in lm) / tb * 100, 1) if tb else 0,
                "kcb_share_pct": round(float(grp["is_star"].mean() * 100), 1),
                "med_mcap_yi": round(float(grp["circ_mcap"].median()), 1),
            })

    summary = {
        "pit_detected_waves": pit_waves,
        "named_waves_6dim": wave_rows,
        "yearly_20cm_structural_shift": yr_lhb,
        "beta_days_summary": {
            "total": int(len(b_df)),
            "is_count": int((b_df["dt"] <= "2024-08-31").sum()),
            "oos_count": int((b_df["dt"] >= "2024-09-01").sum()),
            "golden_1t_count": int((b_df["amt_ma20_trillion"] >= 1.0).sum()),
            "golden_12t_count": int((b_df["amt_ma20_trillion"] >= 1.2).sum()),
        },
        "data_coverage_caveats": [
            "pit_top10_freeholders_cache.json & pit_top10_all_codes.json contain 0 keys for 30/688/689 (00/60 mainboard only).",
            "cninfo_notices_5y_pit.db has complete 2021-2026 coverage for 业绩预告:* only; other ann_types are missing in 2022-2024.",
            "xueqiu_guba_5y_pit.db crawled ONLY ZT stocks (3,362/9,729 20cm ZT pairs), and guba_posts crawl returned 0 results in 2025.",
            "clean_lhb_5y.parquet ends 2026-11-17 (4 trading days prior to 2026-11-23)."
        ],
    }
    with open(f"{OUT_DIR}/module1_waves_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Step 1 Done] Saved module1_waves_summary.json & module1_waves_table.csv in {time.time()-t0:.1f}s")
    print(f"  PIT detected waves: {len(pit_waves)}")
    for pw in pit_waves:
        print("   ", pw)


if __name__ == "__main__":
    main()
