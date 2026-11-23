#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Read-only Red-Team Code Parity & Data Integrity Audit Verification Script (2026-11-23).
Strictly read-only: NEVER writes to production caches, DBs, or portfolio_state.json.
"""
from __future__ import annotations

import contextlib
import datetime
import glob
import io
import json
import os
import sqlite3
import subprocess
import sys

sys.dont_write_bytecode = True
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 VIOLATION"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
DATA = f"{SIM}/data"
SCRIPTS = f"{SIM}/scripts"
OUT_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partB1_code_parity_audit"
os.makedirs(OUT_DIR, exist_ok=True)

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def test_cli_help() -> dict:
    targets = [
        "fast_high_dragon_today.py",
        "fast_3to4_today.py",
        "fast_pry_today.py",
        "fast_2to3_today.py",
        "fast_1to2_today.py",
        "daily_3strategies_score_report.py",
        "fast_26q4_special_today.py",
        "execute_trade.py",
    ]
    res = {}
    for s in targets:
        p = subprocess.run([sys.executable, f"{SCRIPTS}/{s}", "--help"], capture_output=True, text=True, timeout=15)
        res[s] = {
            "returncode": p.returncode,
            "stderr_tail": p.stderr.strip().splitlines()[-3:] if p.stderr else [],
        }
    return res


def inspect_caches_and_portfolio() -> dict:
    cache_files = [
        "1to2_premarket_cache.json",
        "3to4_premarket_cache.json",
        "high_dragon_premarket_cache.json",
        "pry_premarket_cache.json",
        "2to3_premarket_cache.json",
    ]
    c_info = {}
    for fn in cache_files:
        fp = f"{DATA}/{fn}"
        if not os.path.exists(fp):
            c_info[fn] = {"exists": False}
            continue
        js = json.load(open(fp, encoding="utf-8"))
        c_info[fn] = {
            "version": js.get("version"),
            "built_at": js.get("built_at") or js.get("generated_at"),
            "sig_or_asof": js.get("as_of_d1") or js.get("d3_date") or js.get("d1_date") or js.get("sig_date") or js.get("data_as_of_date"),
            "next_or_buy_date": js.get("next_trade_date") or js.get("buy_date") or js.get("next_dt"),
            "used_ths_plate_fallback": js.get("used_ths_plate_fallback"),
            "candidates_cnt": len(js.get("candidates") or []),
            "mtime": datetime.datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M:%S"),
        }

    ps_p = f"{SIM}/portfolio_state.json"
    ps = json.load(open(ps_p, encoding="utf-8"))
    cn = ps.get("accounts", {}).get("a_share", {})
    cn_pos = []
    for p in cn.get("positions", []):
        cn_pos.append({
            "ticker": p.get("ticker"),
            "name": p.get("name"),
            "shares": p.get("shares"),
            "avg_cost": p.get("avg_cost"),
            "strategy_id": p.get("strategy_id"),
            "book": p.get("book"),
            "entry_date": p.get("entry_date"),
        })
    return {
        "caches": c_info,
        "a_share_cash": cn.get("cash"),
        "a_share_positions": cn_pos,
    }


def check_data_sources_and_st() -> dict:
    out = {}

    # 1. zt_micro_tape NULL open_board_count + THS open_num null
    con_tp = sqlite3.connect(f"file:{DATA}/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    null_all = con_tp.execute("SELECT COUNT(*), SUM(CASE WHEN open_board_count IS NULL THEN 1 ELSE 0 END), SUM(CASE WHEN open_board_count = 0 THEN 1 ELSE 0 END) FROM zt_micro_tape").fetchone()
    null_recent = con_tp.execute("SELECT trade_date, sec_code, sec_name, continuous_plate_tag, open_board_count FROM zt_micro_tape WHERE (trade_date >= '2026-11-10' AND (open_board_count IS NULL OR continuous_plate_tag LIKE '%3%')) OR sec_name LIKE '%盛剑%'").fetchall()
    con_tp.close()

    ths_nulls = []
    shengjian_ths = []
    for fp in sorted(glob.glob(f"{DATA}/ths_limit_up_daily/2026-11-*.json"))[-15:]:
        js = json.load(open(fp, encoding="utf-8"))
        dt = js.get("date")
        n_tot = len(js.get("stocks", []))
        n_null = sum(1 for s in js.get("stocks", []) if s.get("open_num") is None)
        s3 = [(s.get("code"), s.get("name"), s.get("high_days"), s.get("open_num")) for s in js.get("stocks", []) if "3" in str(s.get("high_days", ""))]
        for s in js.get("stocks", []):
            if "盛剑" in str(s.get("name", "")):
                shengjian_ths.append({"date": dt, "code": s.get("code"), "name": s.get("name"), "high_days": s.get("high_days"), "open_num": s.get("open_num")})
        ths_nulls.append({"date": dt, "total": n_tot, "open_num_null": n_null, "sample_3b": s3[:8]})
    out["zt_micro_tape"] = {"total_null_zero": null_all, "recent_rows": null_recent[:25], "ths_open_num_nulls": ths_nulls[-10:], "shengjian_ths": shengjian_ths}

    # 2. cninfo_notices_5y_pit.db trade_date_avail > pub_date + 5d
    con_nt = sqlite3.connect(f"file:{DATA}/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    nt_stats = con_nt.execute("""
        SELECT
          COUNT(*) as total_rows,
          MAX(pub_datetime_cst) as max_pub,
          MAX(trade_date_avail) as max_avail,
          SUM(CASE WHEN date(trade_date_avail) > date(substr(pub_datetime_cst,1,10), '+5 days') THEN 1 ELSE 0 END) as gt5d,
          SUM(CASE WHEN date(trade_date_avail) > date(substr(pub_datetime_cst,1,10), '+12 days') THEN 1 ELSE 0 END) as gt12d,
          SUM(CASE WHEN trade_date_avail < substr(pub_datetime_cst,1,10) THEN 1 ELSE 0 END) as avail_lt_pub
        FROM notices
    """).fetchone()
    gt5d_by_mm = con_nt.execute("""
        SELECT strftime('%m', substr(pub_datetime_cst,1,10)) mm, COUNT(*), MIN(julianday(trade_date_avail)-julianday(substr(pub_datetime_cst,1,10))), MAX(julianday(trade_date_avail)-julianday(substr(pub_datetime_cst,1,10)))
        FROM notices
        WHERE date(trade_date_avail) > date(substr(pub_datetime_cst,1,10), '+5 days')
        GROUP BY mm ORDER BY COUNT(*) DESC
    """).fetchall()
    gt12d_sample = con_nt.execute("""
        SELECT sec_code, pub_datetime_cst, trade_date_avail, title
        FROM notices
        WHERE date(trade_date_avail) > date(substr(pub_datetime_cst,1,10), '+12 days')
        LIMIT 10
    """).fetchall()
    con_nt.close()
    out["cninfo_notices"] = {"stats": nt_stats, "gt5d_by_month": gt5d_by_mm, "gt12d_sample": gt12d_sample}

    # 3. Two cninfo_ir_qa_5y_pit.db comparison + community DBs
    ir_a = sqlite3.connect(f"file:{DATA}/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    ir_b = sqlite3.connect(f"file:{SIM}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    ra = ir_a.execute("SELECT COUNT(*), MAX(pub_datetime_cst), MAX(trade_date_avail) FROM ir_qa").fetchone()
    rb = ir_b.execute("SELECT COUNT(*), MAX(pub_datetime_cst), MAX(trade_date_avail) FROM ir_qa").fetchone()
    ir_a.close()
    ir_b.close()

    xq_db = sqlite3.connect(f"file:{DATA}/xueqiu_guba_5y_pit.db?mode=ro", uri=True)
    xq_mx = xq_db.execute("SELECT COUNT(*), MAX(created_time_str) FROM xueqiu_posts").fetchone()
    gb_mx = xq_db.execute("SELECT COUNT(*), MAX(pub_time) FROM guba_posts").fetchone()
    xq_db.close()

    cm_db = sqlite3.connect(f"file:{DATA}/astock_community_5y_pit.db?mode=ro", uri=True)
    cm_mx = cm_db.execute("SELECT source, COUNT(*), MAX(pub_datetime_cst) FROM community_posts GROUP BY source").fetchall()
    cm_db.close()

    comm_json_p = f"{ROOT}/news-dashboard/output/astock_community.json"
    comm_info = {}
    if os.path.exists(comm_json_p):
        cjs = json.load(open(comm_json_p, encoding="utf-8"))
        ts_list = [str(x.get("time") or "") for x in cjs if x.get("time")]
        comm_info = {
            "count": len(cjs),
            "min_time": min(ts_list) if ts_list else "",
            "max_time": max(ts_list) if ts_list else "",
            "mtime": datetime.datetime.fromtimestamp(os.path.getmtime(comm_json_p)).strftime("%Y-%m-%d %H:%M:%S"),
        }

    out["ir_and_community"] = {
        "ir_data_stale": ra,
        "ir_bt2_active": rb,
        "xq_guba_db": {"xq": xq_mx, "guba": gb_mx},
        "community_pit_db": cm_mx,
        "astock_community_json": comm_info,
    }

    # 4. st_universe.json check + a_daily turn unit + recent adjf shifts
    st_js = json.load(open(f"{DATA}/st_universe.json", encoding="utf-8"))
    st_set = {str(x)[:6].zfill(6) for x in st_js.get("codes", [])}

    # Check live Tencent on THS or a_daily latest ST names via csrc_industry_l2 & recent THS/tencent sample
    df_a = ds.dataset(f"{DATA}/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(
        columns=["date", "ticker", "close", "adj_close", "turn", "oshare"],
        filter=(ds.field("date") >= pd.Timestamp("2026-10-01")),
    ).to_table().to_pandas()
    df_a["c6"] = df_a["ticker"].astype(str).str[:6]
    df_a = df_a[df_a["c6"].str.startswith(("00", "60")) & (~df_a["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df_a["dt_str"] = df_a["date"].dt.strftime("%Y-%m-%d")
    df_a.sort_values(["c6", "dt_str"], inplace=True)
    df_a["adjf"] = np.where(df_a["close"] > 0, df_a["adj_close"] / df_a["close"], 1.0)
    df_a["adjf_chg"] = (df_a["adjf"] / df_a.groupby("c6")["adjf"].shift(1) - 1.0).abs()
    ex_divs = df_a[df_a["adjf_chg"] > 0.005][["dt_str", "c6", "adjf_chg"]].head(15).to_dict("records")

    # Check ST codes in Tencent latest snapshot across all active 00/60 codes not in st_set
    latest_dt_a = df_a["dt_str"].max()
    active_c6 = sorted(df_a[df_a["dt_str"] == latest_dt_a]["c6"].unique().tolist())
    from fast_pry_today import fetch_tencent_parallel
    q_all = fetch_tencent_parallel(active_c6, max_workers=24, batch_size=80)
    live_st_codes = {c for c, v in q_all.items() if "ST" in str(v.get("name", "")).upper()}
    missed_by_st_json = sorted(live_st_codes - st_set)
    extra_in_st_json = sorted(st_set - live_st_codes)

    out["st_and_daily_checks"] = {
        "st_universe_meta": {"built_or_keys": [k for k in st_js.keys() if k != "codes"], "as_of": st_js.get("as_of") or st_js.get("date") or st_js.get("updated_at"), "count": len(st_set)},
        "tencent_live_st_count_in_00_60": len(live_st_codes),
        "missed_by_st_json_cnt": len(missed_by_st_json),
        "missed_by_st_json_sample": [(c, q_all[c]["name"]) for c in missed_by_st_json[:15]],
        "extra_in_st_json_cnt": len(extra_in_st_json),
        "a_daily_turn_stats": {
            "median": round(float(df_a["turn"].median()), 6),
            "p95": round(float(df_a["turn"].quantile(0.95)), 6),
            "max": round(float(df_a["turn"].max()), 6),
            "latest_date": latest_dt_a,
        },
        "recent_adjf_shifts_gt_0_5pct": ex_divs,
    }
    return out


def check_sina_kline_bug() -> dict:
    from fast_high_dragon_today import fetch_sina_kline, fetch_tencent_batch, calc_double_dev_for_stock
    from astock_intraday_check import fetch_sina_kline as ic_sina, fetch_tencent_quotes as ic_tx, analyze_one as ic_analyze, fetch_abnormal_notices as ic_not

    sym = "sh600519"
    kl = fetch_sina_kline(sym, datalen=10)
    q = fetch_tencent_batch([sym, "sh000002", "sh000300"])
    today_s = datetime.date.today().isoformat()
    last_bar_day = kl[-1]["day"] if kl else ""

    # Compare calc_double_dev_for_stock vs astock_intraday_check on a high-beta stock (e.g. from cache or 600838/000001/601869)
    test_code = "600838"
    hd_dev = calc_double_dev_for_stock(test_code)
    tsym = ("sh" if test_code.startswith("6") else "sz") + test_code
    isym = "sh000002" if test_code.startswith("6") else "sz399107"
    iq = ic_tx([tsym, isym])
    ikl = {tsym: ic_sina(tsym, 36), isym: ic_sina(isym, 36)}
    ic_res = ic_analyze(test_code, iq, ikl, [], None)

    return {
        "now_cst": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sina_last_bar_day": last_bar_day,
        "sina_includes_today": last_bar_day == today_s,
        "probe_600838_hd_w10_base_day": hd_dev.get("w10", {}).get("base_day"),
        "probe_600838_hd_tighter_93": hd_dev.get("tighter_93"),
        "probe_600838_ic_w10_base_day": ic_res.get("today_10d_100", {}).get("base_day"),
        "probe_600838_ic_w10_p93": ic_res.get("today_10d_100", {}).get("p_93"),
    }


def replay_scoring_parity() -> dict:
    out = {}

    # 1. 2to3 parity: evaluate_2to3_candidate vs upgrade_2to3_pit.compute_v20_components
    sys.path.insert(0, f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117")
    import upgrade_2to3_pit as u23
    from fast_2to3_today import evaluate_2to3_candidate

    rng = np.random.default_rng(20261123)
    n_test = 1500
    rows_u23 = []
    diffs_23 = 0
    max_diff_23 = 0
    for i in range(n_test):
        b01 = int(rng.choice([0, 1]))
        top1_sh = float(rng.choice([0.1, 0.2999, 0.30, 0.45]))
        p12 = float(rng.choice([0.10, 0.1799, 0.18, 0.30]))
        p23 = float(rng.choice([0.15, 0.2799, 0.28, 0.40]))
        maxb = int(rng.choice([2, 3, 4, 6]))
        rk_noev = int(rng.choice([1, 2, 3, 7, 8]))
        psz = int(rng.choice([1, 2, 6, 7, 11, 12, 14, 15]))
        a22 = int(rng.choice([0, 1]))
        s_elo = float(rng.choice([90.0, 95.0, 95.1, 105.0]))
        p3b = int(rng.choice([0, 1, 2]))
        xq_cnt = int(rng.choice([0, 1, 3, 4, 7]))
        ir20 = int(rng.choice([0, 1]))
        d2_lp = float(rng.choice([-0.05, -0.02, -0.019, 0.0]))
        d2_sar = rng.choice([None, 0.03, 0.0499, 0.05, 0.2499, 0.25, 0.40])
        d2_sec = rng.choice([None, 60.0, 300.0, 301.0, 1799.0, 1800.0, 12599.0, 12600.0])
        d2_ocnt = rng.choice([None, 0, 1, 2])
        pos20 = rng.choice([None, 0.20, 0.40, 0.4001, 0.80])
        d2_rturn = rng.choice([None, 10.0, 14.99, 15.0, 24.9999, 25.0, 65.0, 70.0])
        lock10 = rng.choice([None, 30.0, 49.99, 50.0, 65.0])
        op = float(rng.choice([-0.065, -0.01, -0.0001, 0.0, 0.025, 0.03]))
        u1 = bool(rng.choice([False, True]))
        u2 = bool(rng.choice([False, True]))
        u3 = bool(rng.choice([False, True]))
        u5 = bool(rng.choice([False, True]))

        elo_ice_c = int((a22 == 1) or (s_elo <= 95.0))
        cand = {
            "ths_tag": "2天2板", "prev_is_yizi": False, "has_tox_90d": False, "has_reg_10d": False,
            "plate_sz": psz, "b01_hhi_low_q25": b01, "raw_top1_share": top1_sh,
            "mkt_p12_prev": p12, "mkt_p23_prev": p23, "mkt_maxb_prev": maxb, "plate_rk_noev": rk_noev,
            "a22_elo_ice_lt95": a22, "d2_s_elo": s_elo, "plate_3b_cnt_sd": p3b,
            "xq_cnt_tot": xq_cnt, "ir_has_20d": ir20, "d2_low_pct": d2_lp,
            "d2_seal_amt_ratio": d2_sar, "d2_seal_sec": d2_sec, "d2_open_cnt_tape": d2_ocnt,
            "pos_20d_d0": pos20, "d2_real_turn": d2_rturn, "lock_top10": lock10,
            "is_pure_outsider_causal": u1, "d2_own_new_term": u2, "d1_is_dying_pulse": u3, "d1_is_yizi": u5,
        }
        ev = evaluate_2to3_candidate(cand, op, True)
        rows_u23.append({
            "b01_hhi_low_q25": b01, "raw_top1_share": top1_sh, "mkt_p12_prev": p12, "mkt_p23_prev": p23,
            "mkt_maxb_prev": maxb, "plate_rk_noev": rk_noev, "plate_sz": psz, "elo_ice_causal": elo_ice_c,
            "plate_3b_cnt_sd": p3b, "xq_cnt_tot": xq_cnt, "ir_has_20d": ir20, "d2_low_pct": d2_lp,
            "d2_seal_amt_ratio": np.nan if d2_sar is None else d2_sar,
            "d2_seal_sec": np.nan if d2_sec is None else d2_sec,
            "d2_open_cnt_tape": -1 if d2_ocnt is None else d2_ocnt,
            "pos_20d_d0": np.nan if pos20 is None else pos20,
            "d2_real_turn": np.nan if d2_rturn is None else d2_rturn,
            "lock_top10": np.nan if lock10 is None else lock10,
            "open_pct": op,
            "is_pure_outsider_causal": u1, "d2_own_new_term": u2, "d1_is_dying_pulse": u3,
            "d2_seal_sec_causal": np.nan if d2_sec is None else d2_sec,
            "d1_is_yizi": u5,
            "ev_score": ev["score"],
        })
    df_u23 = pd.DataFrame(rows_u23)
    comp20 = u23.compute_v20_components(df_u23)
    u23_scores = 60 + comp20.sum(axis=1).astype(int)
    diff_arr_23 = np.abs(u23_scores - df_u23["ev_score"].to_numpy())
    diffs_23 = int((diff_arr_23 > 0).sum())
    max_diff_23 = int(diff_arr_23.max())
    out["2to3_v20_parity"] = {"tested": n_test, "mismatches": diffs_23, "max_abs_diff": max_diff_23}

    # 2. 3to4 parity: score_single_3to4_v40_row vs upgrade_3to4_pit formula across synthetic boundary grid (n=1500)
    from live_3to4_v40_engine import score_single_3to4_v40_row
    diff_34 = 0
    for i in range(n_test):
        is_10 = bool(rng.choice([True, False], p=[0.9, 0.1]))
        prev_yz = bool(rng.choice([False, True], p=[0.9, 0.1]))
        buyable = bool(rng.choice([True, False], p=[0.9, 0.1]))
        tox = bool(rng.choice([False, True], p=[0.95, 0.05]))
        sreg = bool(rng.choice([False, True], p=[0.95, 0.05]))
        obc = int(rng.choice([0, 1, 2, 3]))
        op = float(rng.choice([0.029, 0.030, 0.055, 0.092, 0.093]))
        top1 = bool(rng.choice([True, False]))
        lock10 = float(rng.choice([38.0, 44.99, 45.0, 60.0]))
        rfm = float(rng.choice([20.0, 44.99, 45.0, 80.0]))
        to = float(rng.choice([8.4, 8.5, 9.4, 9.5, 20.0, 28.0, 28.1, 31.0, 31.1]))
        fst = str(rng.choice(["09:35:59", "09:36:00", "10:30:00", "10:30:01", "14:00:00"]))
        px_d3 = float(rng.choice([19.9, 20.0, 20.1, 33.0]))
        maxb = int(rng.choice([3, 4, 5]))
        pelo = float(rng.choice([114.9, 115.0, 135.0]))
        mzt = int(rng.choice([34, 35, 60, 85, 86, 96]))
        ereg = bool(rng.choice([False, True]))
        surf = bool(rng.choice([False, True]))
        lh = int(rng.choice([0, 1, 2, 3, 4]))
        fb_ho = int(rng.choice([0, 1, 2, 3]))
        fb_yz = int(rng.choice([0, 1]))
        peers_op = float(rng.choice([-0.02, -0.0151, -0.015, 0.01]))
        dt3 = int(rng.choice([0, 1, 2, 3]))
        csi1 = float(rng.choice([-0.021, -0.020, -0.019, 0.0]))
        csi5 = float(rng.choice([-0.031, -0.030, -0.029, 0.0]))
        bmon = int(rng.choice([1, 2, 5, 11]))
        bd = f"2026-{bmon:02d}-10"
        pos20 = float(rng.choice([0.39, 0.40, 0.41, 0.80]))
        xq2 = int(rng.choice([0, 3, 4, 5]))

        r_in = {
            "is_10cm_non_st": is_10, "prev_is_yizi": prev_yz, "buyable_open": buyable,
            "has_tox_notice": tox, "has_stock_reg": sreg, "open_board_count": obc,
            "open_pct": op, "is_top1_3b_open": top1, "lock_top10": lock10,
            "real_free_mcap": rfm, "prev_to": to, "first_seal_time": fst,
            "px_d3": px_d3, "mkt_max_board_prev": maxb, "p_elo": pelo,
            "mkt_zt_prev": mzt, "has_ex_reg": ereg, "surf_yz_buy": surf,
            "lhb_lh_cnt": lh, "plate_fb_ho_cnt": fb_ho, "plate_fb_yz_cnt": fb_yz,
            "plate_peers_open_avg": peers_op, "prev_3b_dt_cnt": dt3,
            "csi_1d_prev": csi1, "csi_5d_prev": csi5, "buy_date": bd,
            "pos20_d0": pos20, "xq_cnt_2d": xq2,
        }
        res_live = score_single_3to4_v40_row(r_in)

        # Backtest upgrade_3to4_pit lines 909-955 exact replica
        skel_bt = is_10 and (not prev_yz) and buyable and (not tox) and (not sreg) and (obc >= 1) and (0.030 <= op <= 0.092)
        if not skel_bt:
            bt_sc = -999
        else:
            fs_i = int(fst.replace(":", "")[:4])
            lock_bad = (lock10 < 45.0) and (rfm < 45.0)
            bt_sc = 78
            bt_sc += 8 if px_d3 <= 20.0 else 0
            bt_sc += 8 if maxb <= 4 else 0
            bt_sc += 5 if 35 <= mzt <= 85 else 0
            bt_sc += 4 if (fb_ho >= 2 and fb_yz == 0) else 0
            bt_sc += 4 if lh == 0 else 0
            bt_sc += 3 if pelo >= 115.0 else 0
            bt_sc += 3 if dt3 == 0 else 0
            bt_sc += 3 if (9.5 <= to <= 28.0) else 0
            bt_sc += 3 if (936 <= fs_i <= 1030) else 0
            bt_sc += -12 if ereg else 0
            bt_sc += -12 if surf else 0
            bt_sc += -12 if (not top1) else 0
            bt_sc += -10 if peers_op < -0.015 else 0
            bt_sc += -10 if lock_bad else 0
            bt_sc += -10 if not (8.5 <= to <= 31.0) else 0
            bt_sc += -8 if (csi1 <= -0.020 or csi5 <= -0.030) else 0
            bt_sc += -7 if fb_yz >= 1 else 0
            bt_sc += -5 if lh >= 3 else 0
            bt_sc += -4 if dt3 >= 2 else 0
            bt_sc += -4 if bmon in (1, 5) else 0
            bt_sc += 5 if pos20 <= 0.40 else 0
            bt_sc += -15 if xq2 >= 4 else 0
        if res_live["passed_skeleton"] != skel_bt or res_live["score"] != bt_sc:
            diff_34 += 1
    out["3to4_v40_parity"] = {"tested": n_test, "mismatches": diff_34}

    # 3. 1to2 parity + coordinator vs standalone divergences on real current 1to2_premarket_cache.json
    c1 = json.load(open(f"{DATA}/1to2_premarket_cache.json", encoding="utf-8"))
    from fast_1to2_today import evaluate_1to2_v19_df, check_live as f12_check_live
    import fast_26q4_special_today as f26

    # Test with synthetic mock_open (e.g. first 2 candidates)
    cands1 = c1.get("candidates", [])
    mock_map = {}
    if len(cands1) >= 2:
        mock_map[cands1[0]["c6"]] = 0.045
        mock_map[cands1[1]["c6"]] = 0.096  # test 9.6% non-yizi edge!
    quotes_12 = {}
    for x in cands1:
        c6 = x["c6"]
        pre = float(x["pre_c"])
        op = mock_map.get(c6, 0.035)
        opx = round(pre * (1.0 + op), 2)
        quotes_12[c6] = {
            "name": x.get("name", c6), "pre": pre, "open": opx, "low": opx, "high": opx, "cur": opx,
            "q_dt": c1.get("next_dt", "2099-01-01"),
            "open_pct": op, "price": opx, "pre_c": pre, "cur_pct": op,
            "zt_px": float(np.floor(pre * 1.10 * 100.0 + 0.5) / 100.0), "is_yizi": False,
        }
    buf = io.StringIO()
    mock_str = ",".join(f"{x['c6']}={mock_map.get(x['c6'], 0.035)}" for x in cands1)
    mock_all = {x["c6"]: mock_map.get(x["c6"], 0.035) for x in cands1}
    with contextlib.redirect_stdout(buf):
        df_eval, _ = evaluate_1to2_v19_df(c1, quotes_12, mock_map=mock_all)
    buf_live = io.StringIO()
    with contextlib.redirect_stdout(buf_live):
        f12_check_live(mock_open=mock_str)
    live_txt = buf_live.getvalue()
    eval_wins = df_eval[df_eval["ok"]].sort_values("rank_sv", ascending=False)[["c6", "tot_v18", "track_label"]].to_dict("records") if not df_eval.empty else []
    live_winner_line = [ln for ln in live_txt.splitlines() if "唯一锁定头名" in ln or "无过线头名" in ln]
    # Also check the code-level check_live vs evaluate_1to2_v19_df difference on fb_dom295 (~tot_v18 omission)
    src_f12 = open(f"{SCRIPTS}/fast_1to2_today.py", encoding="utf-8").read().splitlines()
    line1721 = src_f12[1720] if len(src_f12) > 1720 else ""
    line1994 = src_f12[1993] if len(src_f12) > 1993 else ""

    # 4. Test fast_26q4_special_today.py mock_open bug on HD (stale is_yizi retained!) & 3to4 9.5%~9.8% peer bug
    hd_fake_cache = {"as_of_d1": "2026-11-20", "candidates": [{"code": "600999", "name": "TEST_HD", "static_score": 88, "is_vetoed": False, "veto_reasons": []}]}
    hd_quotes = {"600999": {"code": "600999", "name": "TEST_HD", "price": 10.0, "pre_c": 10.0, "open": 10.2, "open_pct": 0.02, "cur_pct": 0.02, "zt_px": 11.0, "is_yizi": True, "q_dt": "9999-12-31"}}
    sr_st = f26.load_sr_state()
    hd_mock_res = f26.evaluate_high_dragon_26q4(hd_fake_cache, hd_quotes, sr_st)

    # Check 3to4 9.6% non-yizi peer handling in fast_26q4 vs live_3to4 vs daily_3strategies
    c3_fake = {
        "d3_date": "2026-11-20",
        "env": {"mkt_max_board_prev": 3, "mkt_zt_prev": 50, "prev_3b_dt_cnt": 0, "csi_1d_prev": 0.0, "csi_5d_prev": 0.0},
        "candidates": [{
            "code": "600888", "name": "TEST_34", "px_d3": 10.0, "is_10cm_non_st": True, "prev_is_yizi": False,
            "has_tox_notice": False, "has_stock_reg": False, "open_board_count": 1, "prev_to": 15.0,
            "lock_top10": 55.0, "real_free_mcap": 50.0, "first_seal_time": "10:00:00", "p_elo": 120.0,
            "has_ex_reg": False, "surf_yz_buy": False, "lhb_lh_cnt": 0, "pos20_d0": 0.30, "xq_cnt_2d": 0,
            "plate_fb_codes": ["000111"], "plate_zt_codes": [], "buy_date": "2026-11-23",
        }],
    }
    q3_fake = {
        "600888": {"code": "600888", "name": "TEST_34", "open": 10.50, "price": 10.50, "pre_c": 10.0, "open_pct": 0.05, "zt_px": 11.0, "is_yizi": False, "q_dt": "2026-11-23"},
        "000111": {"code": "000111", "name": "PEER_FB", "open": 10.96, "price": 10.96, "pre_c": 10.0, "open_pct": 0.096, "zt_px": 11.0, "is_yizi": False, "q_dt": "2026-11-23"},
    }
    r3_26q4 = f26.evaluate_3to4_26q4(c3_fake, q3_fake, sr_st)

    out["coordinator_and_1to2_replay"] = {
        "1to2_eval_wins": eval_wins,
        "1to2_live_winner_line": live_winner_line,
        "1to2_src_line1721": line1721.strip(),
        "1to2_src_line1994": line1994.strip(),
        "26q4_hd_mock_stale_yizi_vetoed": hd_mock_res[0]["is_vetoed"],
        "26q4_hd_mock_veto_reasons": hd_mock_res[0]["veto_reasons"],
        "26q4_3to4_fb_peer_96pct_nonyizi_ignored": r3_26q4[0]["breakdown_str"],
    }
    return out


def main():
    report = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cli_help": test_cli_help(),
        "caches_and_portfolio": inspect_caches_and_portfolio(),
        "sina_kline_bug": check_sina_kline_bug(),
        "data_sources": check_data_sources_and_st(),
        "parity_replay": replay_scoring_parity(),
    }
    out_p = f"{OUT_DIR}/audit_parity_verify_result.json"
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"[SAVED] {out_p}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
