#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD024 Pillar 6 (Data Hygiene & Implicit Leakage) + Pillar 7 (Portfolio Contribution,
Shadow Reconciliation & CUSUM/SPRT Decay Monitoring Redlines) Institutional Audit.

Strict Read-Only Constraints:
  - D12: Never import yfinance.
  - All SQLite databases opened strictly with ?mode=ro.
  - Zero edits to production scripts, strategy_astock.md, clean ledgers, or portfolio_state.json.
"""
import json
import math
import os
import sqlite3
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
PARTC = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
OUT_DIR = f"{SIM}/output/five_strategies_institutional_validation_20261124"
OUT_JSON = f"{OUT_DIR}/part3_hygiene_portfolio_cusum.json"

DATA_DIR = f"{SIM}/data"
A_DAILY_PQ = f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet"
A_DELIST_PQ = f"{DATA_DIR}/cn_hk_price_db/a_delisted_daily.parquet"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
HOLDERS_JSON = f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
DB_NOTICES_PIT = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
DB_IR_DATA = f"{DATA_DIR}/cninfo_ir_qa_5y_pit.db"
DB_IR_A2 = f"{SIM}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db"
DB_COMM = f"{DATA_DIR}/astock_community_5y_pit.db"
DB_XQ_GB = f"{DATA_DIR}/xueqiu_guba_5y_pit.db"
DB_ZT_TAPE = f"{DATA_DIR}/zt_micro_tape_5y_pit.db"
DB_NOTICES_OLD = f"{SIM}/backtest/2026-08-24-daban/notices.db"
PORTFOLIO_STATE = f"{SIM}/portfolio_state.json"

STRAT_SPECS = [
    ("3to4", "三进四V4.1", 1, "ledger_3to4_v41_clean.csv"),
    ("high", "高标首阴V5.1", 2, "ledger_high_v51_clean.csv"),
    ("pry_ss165", "超跌撬板V2.1", 3, "ledger_pry_v21_ss165_clean.csv"),
    ("2to3", "二进三V2.1", 4, "ledger_2to3_v21_opt_std90_clean.csv"),
    ("1to2", "一进二V19", 5, "ledger_1to2_v19_clean.csv"),
]
COMB_FILE = "ledger_combined_5strat_v191_slot1_clean.csv"
PRY_TOP1_FILE = "ledger_pry_v21_top1_clean.csv"
TRD_DAYS_YEAR = 242.0
EMBARGO_DAYS = 3


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def norm_ledger(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["code"] = d["code"].astype(str).str.strip().str.zfill(6)
    d["buy_date"] = d["buy_date"].astype(str).str[:10]
    d["exit_date"] = d["exit_date"].astype(str).str[:10]
    d["buy_hhmm"] = pd.to_numeric(d.get("buy_hhmm", 925), errors="coerce").fillna(925).astype(int)
    d["exit_hhmm"] = pd.to_numeric(d.get("exit_hhmm", 1500), errors="coerce").fillna(1500).astype(int)
    d["net_ret"] = pd.to_numeric(d["net_ret"], errors="coerce").astype(float)
    d.sort_values(["buy_date", "buy_hhmm", "code"], inplace=True)
    d.reset_index(drop=True, inplace=True)
    return d


def load_daily_panel():
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp("2021-10-01")
    da = ds.dataset(A_DAILY_PQ, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(A_DELIST_PQ, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    df = pd.concat([da, dd], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60")) & (~df["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df["dt"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt"], inplace=True)
    df.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)
    df["adjf"] = np.where((df["close"] > 0) & (df["adj_close"] > 0), df["adj_close"] / df["close"], 1.0)
    return df


def audit_pillar6_1_raw_vs_qfq(df_daily: pd.DataFrame, ledgers: dict) -> dict:
    sub5y = df_daily[df_daily["dt"] >= "2021-11-15"].copy()
    g = sub5y.groupby("c6")
    qfq_ratio = g["qfq_factor"].shift(1) / sub5y["qfq_factor"]
    adjf_ratio = sub5y["adjf"] / g["adjf"].shift(1)
    qfq_neq1 = (np.abs(sub5y["qfq_factor"] - 1.0) > 1e-6)
    ex_jumps = qfq_ratio.notna() & (np.abs(qfq_ratio - 1.0) > 1e-4)
    mismatch_cnt = int((qfq_ratio.notna() & adjf_ratio.notna() & (np.abs(qfq_ratio - adjf_ratio) > 1e-3)).sum())

    bar_lu = {
        (r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf))
        for r in df_daily[["c6", "dt", "open", "close", "adj_close", "qfq_factor", "adjf"]].itertuples(index=False)
    }

    samples = {}
    for code, dt in [("002919", "2023-05-31"), ("600262", "2024-07-26"), ("002930", "2025-06-24")]:
        b = bar_lu.get((code, dt))
        if b:
            samples[f"{code}@{dt}"] = {
                "raw_close": round(b[1], 4), "adj_close_qfq": round(b[2], 4),
                "qfq_factor": round(b[3], 6), "distortion_pct": round((b[2] / b[1] - 1.0) * 100.0, 2),
            }

    ledger_exdiv = {}
    for lname, df_l in ledgers.items():
        ex_list = []
        max_err = 0.0
        bad_cnt = 0
        for r in df_l.itertuples(index=False):
            bb = bar_lu.get((r.code, r.buy_date))
            eb = bar_lu.get((r.code, r.exit_date))
            if not bb or not eb:
                continue
            qr = bb[3] / eb[3] if eb[3] > 0 else 1.0
            if hasattr(r, "buy_price") and hasattr(r, "exit_price"):
                exp_r = (float(r.exit_price) / float(r.buy_price)) * qr * 0.9980 - 1.0
                err = abs(exp_r - float(r.net_ret))
                max_err = max(max_err, err)
                if err > 0.005:
                    bad_cnt += 1
            if abs(qr - 1.0) > 1e-4:
                ex_list.append({
                    "code": r.code, "name": getattr(r, "name", ""),
                    "buy_date": r.buy_date, "exit_date": r.exit_date,
                    "qfq_b": round(bb[3], 5), "qfq_e": round(eb[3], 5),
                    "qfq_ratio": round(qr, 5), "net_ret_pct": round(float(r.net_ret) * 100.0, 2),
                })
        ledger_exdiv[lname] = {
            "n_trades": int(len(df_l)), "ex_div_trades_count": len(ex_list),
            "ex_div_ret_mismatch_gt50bps": bad_cnt, "max_ret_diff_bps": round(max_err * 10000.0, 2),
            "ex_div_trades": ex_list,
        }

    code_audit = [
        {
            "strategy": "s_3to4 (三进四 V4.1)",
            "prod_files": ["live_3to4_v40_engine.py", "fast_3to4_today.py"],
            "raw_price_thresholds": "live_3to4_v40_engine.py:873 (px_d3 raw close<=20元), 846 (mcap=close*osh/1e8)",
            "adj_pre_c_limit_calc": "live_3to4_v40_engine.py:594-602 & fast_3to4_today.py:222-227 (uses adjf.shift(1)/adjf for pre_c & zt_px)",
            "backtest_refs": "upgrade_3to4_pit.py:514-522,858,868 (adjf pre_c & exit ret; raw px_d3 & mcap)",
            "residual_issues": [
                "live_3to4_v40_engine.py:608-610,1159-1161 & upgrade_3to4_pit.py:532-534 compute 20d low/high/pos20_today on unadjusted OHLC instead of adjf-adjusted series."
            ],
            "qfq_price_threshold_leak": False,
        },
        {
            "strategy": "s_high (高标首阴 V5.1)",
            "prod_files": ["fast_high_dragon_today.py"],
            "raw_price_thresholds": "fast_high_dragon_today.py:859 (price_tier<=20/>35 raw close), 391,887 (mcap=close*oshare/1e8)",
            "adj_pre_c_limit_calc": "fast_high_dragon_today.py:393-403 (uses adjf for pre_c & zt_price)",
            "backtest_refs": "build_pit_cache.py:40-48 & part2a_daily_and_env.py:35-46 (adjf pre_c, raw mcap); sub2_03_golden_relaxation_backtest.py:164 & build_high_data.py:85 (adjf exit ret)",
            "residual_issues": [
                "fast_high_dragon_today.py:1009-1010 computes premarket fallback zt_price_d2/dt_price_d2 from raw c_close without D2 ex-div factor.",
                "fast_high_dragon_today.py:205-218 & sub2_03_golden_relaxation_backtest.py:95-101 compute 10d/30d double-dev thresholds on unadjusted closes (fixed in f1_3to4/exit_factor_engine.py:57,65)."
            ],
            "qfq_price_threshold_leak": False,
        },
        {
            "strategy": "s_pry (超跌撬板 V2.1)",
            "prod_files": ["fast_pry_today.py"],
            "raw_price_thresholds": "fast_pry_today.py:283 (raw close>=2.0), 311 (fmcap=close*oshare*(1-lock)/1e8)",
            "adj_pre_c_limit_calc": "fast_pry_today.py:187-191,362-366 (uses adjf for pre_c & zt_px/dt_px)",
            "backtest_refs": "part2a_daily_and_env.py:35-46 & backtest_30_factors.py:105,136-137 (tp_px & eod checks use adjf[p0]/adjf[k])",
            "residual_issues": [
                "fast_pry_today.py:286-287,312,414 & part2a_daily_and_env.py:64-71 & build_full_36k_pry_master.py:87-116 compute ma10/ma20/max20/ret10(dyn_tp) on unadjusted closes."
            ],
            "qfq_price_threshold_leak": False,
        },
        {
            "strategy": "s_2to3 (二进三 V2.1)",
            "prod_files": ["fast_2to3_today.py"],
            "raw_price_thresholds": "fast_2to3_today.py:1105 (prev_close raw close); turn-based d2_real_turn invariant to split",
            "adj_pre_c_limit_calc": "fast_2to3_today.py:705-713 (uses adjf for pre_c & zt_10), 1032-1035 (pos_20d_d0 properly uses high*adjf, low*adjf, adj_close)",
            "backtest_refs": "upgrade_2to3_pit.py:130,147 & build_holding_factors.py:111,125 (omitted adj_close, causing 002919 & 600262 ex-div errors; patched in calibrate_v191_clean_ledgers.py:249-271)",
            "residual_issues": [
                "Clean ledger v191 already patched ex-div 002919 (+12.41%) & 600262 (-4.40%); production fast_2to3_today.py already uses adjf cleanly."
            ],
            "qfq_price_threshold_leak": False,
        },
        {
            "strategy": "s_1to2 (一进二 V19)",
            "prod_files": ["fast_1to2_today.py", "clean_wf_1to2_v14_ironclad_master.py"],
            "raw_price_thresholds": "fast_1to2_today.py:1148 (raw close<=60.0), 240 (mcap=close*oshare/1e8)",
            "adj_pre_c_limit_calc": "fast_1to2_today.py:233-246 (_recompute_adjf_technicals uses adjf for pre_c & zt_price)",
            "backtest_refs": "upgrade_1to2_pit.py:162,219 (used unadjusted pre_c & raw exit ratio, patched 002930 ex-div in calibrate_v191_clean_ledgers.py:278-285)",
            "residual_issues": [
                "fast_1to2_today.py:257-266 & upgrade_1to2_pit.py:188-196 compute 5d/10d/20d/60d highs, lows, and pos20 on unadjusted prices.",
                "clean_wf_1to2_v14_ironclad_master.py:117-122 (used only as import helper; fast_1to2_today.py:707 overrides pre_c with _recompute_adjf_technicals) has unadjusted pre_c."
            ],
            "qfq_price_threshold_leak": False,
        },
    ]

    return {
        "parquet_5y_stats": {
            "window": "2021-11-15 ~ " + str(sub5y["dt"].max()),
            "mainboard_rows": int(len(sub5y)),
            "unique_tickers": int(sub5y["c6"].nunique()),
            "rows_qfq_neq_1": int(qfq_neq1.sum()),
            "rows_qfq_neq_1_pct": round(float(qfq_neq1.mean() * 100.0), 2),
            "ex_div_jump_events": int(ex_jumps.sum()),
            "tickers_with_ex_div": int(sub5y.loc[ex_jumps, "c6"].nunique()),
            "adjf_vs_qfq_formula_mismatch": mismatch_cnt,
            "qfq_distortion_examples": samples,
        },
        "clean_ledgers_ex_div_verification": ledger_exdiv,
        "code_audit_by_strategy": code_audit,
    }


def audit_pillar6_2_reporting_lag() -> dict:
    db_stats = {}

    con = sqlite3.connect(f"file:{DB_NOTICES_PIT}?mode=ro", uri=True)
    n_tot, dt_min, dt_max, n_post15, n_pre0925, n_avail_lt_pub, n_bt_eq = con.execute(
        """SELECT count(*), min(pub_datetime_cst), max(pub_datetime_cst),
           sum(case when substr(pub_datetime_cst,12,8)>='15:00:00' then 1 else 0 end),
           sum(case when substr(pub_datetime_cst,12,8)<'09:25:00' then 1 else 0 end),
           sum(case when trade_date_avail < substr(pub_datetime_cst,1,10) then 1 else 0 end),
           sum(case when substr(pub_datetime_cst,12,8)>='15:00:00' and trade_date_avail <= substr(pub_datetime_cst,1,10) then 1 else 0 end)
           FROM notices"""
    ).fetchone()
    n_midnight = con.execute("SELECT sum(case when substr(pub_datetime_cst,12,8)='00:00:00' then 1 else 0 end) FROM notices").fetchone()[0]
    dup_titles = con.execute("SELECT count(*) - count(distinct sec_code || '|' || title) FROM notices").fetchone()[0]
    bt_dates = con.execute(
        "SELECT substr(pub_datetime_cst,1,10), count(*) FROM notices WHERE substr(pub_datetime_cst,12,8)>='15:00:00' AND trade_date_avail <= substr(pub_datetime_cst,1,10) GROUP BY 1"
    ).fetchall()
    con.close()
    db_stats["cninfo_notices_5y_pit"] = {
        "rows": int(n_tot), "span": f"{dt_min} ~ {dt_max}",
        "post_1500_count": int(n_post15), "post_1500_pct": round(n_post15 / n_tot * 100.0, 2),
        "pre_0925_count": int(n_pre0925), "pre_0925_pct": round(n_pre0925 / n_tot * 100.0, 2),
        "intraday_0925_1500_count": int(n_tot - n_post15 - n_pre0925),
        "intraday_pct": round((n_tot - n_post15 - n_pre0925) / n_tot * 100.0, 2),
        "trade_date_avail_lt_pub_date": int(n_avail_lt_pub),
        "post15_avail_le_pub_anomaly_count": int(n_bt_eq),
        "post15_avail_le_pub_dates": {str(d): int(c) for d, c in bt_dates},
        "midnight_000000_timestamps": int(n_midnight),
        "duplicate_sec_title_rows": int(dup_titles),
    }

    for key, p in [("cninfo_ir_qa_data", DB_IR_DATA), ("cninfo_ir_qa_a2", DB_IR_A2)]:
        if os.path.exists(p):
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            r = c.execute(
                """SELECT count(*), min(pub_datetime_cst), max(pub_datetime_cst),
                   sum(case when substr(pub_datetime_cst,12,8)>='15:00:00' then 1 else 0 end),
                   sum(case when substr(pub_datetime_cst,12,8)='00:00:00' then 1 else 0 end),
                   sum(case when substr(pub_datetime_cst,12,8)>='15:00:00' and trade_date_avail <= substr(pub_datetime_cst,1,10) then 1 else 0 end)
                   FROM ir_qa"""
            ).fetchone()
            c.close()
            db_stats[key] = {
                "rows": int(r[0]), "span": f"{r[1]} ~ {r[2]}", "post_1500_pct": round(r[3] / r[0] * 100.0, 2),
                "midnight_000000_timestamps": int(r[4]), "post15_avail_le_pub_anomaly": int(r[5]),
            }

    for key, p, sql in [
        ("astock_community_5y_pit", DB_COMM, "SELECT count(*), min(pub_datetime_cst), max(pub_datetime_cst) FROM community_posts"),
        ("xueqiu_guba_5y_pit", DB_XQ_GB, "SELECT count(*), min(created_time_str), max(created_time_str) FROM xueqiu_posts"),
        ("zt_micro_tape_5y_pit", DB_ZT_TAPE, "SELECT count(*), min(trade_date), max(trade_date), sum(case when open_board_count=0 then 1 else 0 end), sum(case when open_board_count is null then 1 else 0 end) FROM zt_micro_tape"),
        ("notices_old_date_only", DB_NOTICES_OLD, "SELECT count(*), min(ndate), max(ndate) FROM notice"),
    ]:
        if os.path.exists(p):
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            r = c.execute(sql).fetchone()
            c.close()
            d_obj = {"rows": int(r[0]), "span": f"{r[1]} ~ {r[2]}"}
            if key == "zt_micro_tape_5y_pit":
                d_obj["open_board_count_zero"] = int(r[3])
                d_obj["open_board_count_null"] = int(r[4])
            db_stats[key] = d_obj

    holders = json.load(open(HOLDERS_JSON, encoding="utf-8"))
    lags, dirty_recs = [], []
    neg_lag = 0
    for code, lst in holders.items():
        for rec in lst:
            nd, ed = str(rec[0])[:10], str(rec[1])[:10]
            if nd < "2000-01-01":
                dirty_recs.append({"code": code, "notice_date": nd, "end_date": ed, "lock10": rec[2]})
            elif nd < ed:
                neg_lag += 1
            else:
                lags.append((pd.Timestamp(nd) - pd.Timestamp(ed)).days)
    db_stats["pit_top10_all_codes"] = {
        "codes": len(holders), "records": int(len(lags) + len(dirty_recs) + neg_lag),
        "all_pipelines_filter_by": "NOTICE_DATE (x[0]), NOT END_DATE (x[1])",
        "notice_date_lt_end_date": int(neg_lag),
        "dirty_notice_date_lt_2000": len(dirty_recs), "dirty_examples": dirty_recs,
        "reporting_lag_days": {
            "min": int(np.min(lags)), "p10": float(np.percentile(lags, 10)),
            "median": float(np.median(lags)), "p90": float(np.percentile(lags, 90)),
            "max": int(np.max(lags)),
        },
    }

    truncation_audit = [
        {"component": "CNINFO & Tox Notices (3to4/2to3/1to2)", "verdict": "PIT_PASS_WITH_LEGACY_FALLBACK_RISK",
         "detail": "PIT queries enforce pub_datetime_cst < buy_date 09:25:00 (live_3to4_v40_engine.py:673,694; fast_2to3_today.py:403,430,475,511; fast_1to2_today.py:788-790; upgrade_3to4_pit.py:817). RISK: fallback notices.db stores date-only ndate and fast_2to3_today.py:404,496 / fast_1to2_today.py:763 query ndate <= buy_date (would admit same-day post-close notices if run post-close); fast_high_dragon_today.py:489,503,726,733,743 omits upper date bound in build_premarket_cache."},
        {"component": "IR Q&A (2to3/1to2)", "verdict": "PIT_PASS",
         "detail": "Dual copies synced (42,178 rows through 2026-11-23). fast_2to3_today.py:632-633 enforces pub_datetime_cst < buy_date 09:25:00; fast_1to2_today.py:860 uses <= next_dt 09:25:00 (1s boundary)."},
        {"component": "Xueqiu & Community", "verdict": "PIT_PASS",
         "detail": "xueqiu_guba_5y_pit.db stopped at 2026-11-13, bridged by astock_community_5y_pit.db + astock_community.json with hard clamp < buy_date 09:25:00 (live_3to4_v40_engine.py:278-340; fast_2to3_today.py:563-620; fast_1to2_today.py:907-943)."},
        {"component": "Top-10 Freeholders Lockup", "verdict": "PIT_PASS_WITH_6_DIRTY_DATES",
         "detail": "All 5 strategies align strictly on NOTICE_DATE x[0] <= sig_date / < buy_date (live_3to4:835, fast_high:878, fast_pry:305, fast_2to3:1079, upgrade_3to4:788, part2b:18). 0 records have NOTICE_DATE < END_DATE; median lag = 30d. 6 records carry 1900-01-01 sentinel notice_date."},
        {"component": "LHB & KPL & CSRC", "verdict": "PIT_PASS_CSRC_FALLBACK",
         "detail": "LHB & KPL strictly use <= sig_date (T-1 post-close). Backtests & fast_2to3/fast_1to2 use interval-based csrc_industry_pit_clean.csv (fast_1to2:114-146 falls back to static csrc_industry_l2.csv only if missing)."},
    ]
    return {"db_empirical_audit": db_stats, "code_truncation_audit": truncation_audit}


def build_daily_mtm_series(df_led: pd.DataFrame, cal_dts: list[str], dt_to_idx: dict, bar_map: dict) -> tuple[np.ndarray, dict]:
    """Build exact daily mark-to-market return series aligned with cal_dts so prod(1+r_t) == prod(1+net_ret)."""
    T = len(cal_dts)
    eq_factor = np.ones(T, dtype=float)
    d = norm_ledger(df_led)
    if d.empty:
        return np.zeros(T, dtype=float), {"nav_diff": 0.0, "active_days": 0}

    # Build day-level timeline via wealth tracking so same-day exit->entry sequences cleanly
    # Start wealth = 1.0 at index -1
    day_mult = np.ones(T, dtype=float)
    has_px = ("buy_price" in d.columns) and ("exit_price" in d.columns)

    for r in d.itertuples(index=False):
        bi = dt_to_idx.get(r.buy_date)
        ei = dt_to_idx.get(r.exit_date)
        if bi is None or ei is None or ei <= bi:
            continue
        bb = bar_map.get((r.code, r.buy_date))
        b_adj_px = (float(r.buy_price) * bb[4]) if (has_px and bb) else (bb[1] * bb[4] if bb else 1.0)
        if b_adj_px <= 0:
            b_adj_px = 1.0

        # Track adjusted close path across [bi .. ei-1]
        prev_val = b_adj_px
        last_close_adj = b_adj_px
        for t in range(bi, ei):
            bt = bar_map.get((r.code, cal_dts[t]))
            cur_close_adj = (bt[1] * bt[4]) if bt else last_close_adj
            if cur_close_adj <= 0:
                cur_close_adj = last_close_adj
            day_mult[t] *= (cur_close_adj / prev_val)
            prev_val = cur_close_adj
            last_close_adj = cur_close_adj

        # On exit day ei, final trade multiplier from entry must equal (1 + r.net_ret)
        target_end_val = b_adj_px * (1.0 + float(r.net_ret))
        day_mult[ei] *= (target_end_val / prev_val)

    daily_ret = day_mult - 1.0
    nav_mtm = float(np.prod(day_mult))
    nav_led = float(np.prod(1.0 + d["net_ret"].to_numpy(float)))
    return daily_ret, {
        "nav_mtm": nav_mtm, "nav_ledger": nav_led,
        "nav_abs_diff": abs(nav_mtm - nav_led),
        "active_days": int(np.sum(np.abs(daily_ret) > 1e-12)),
    }


def metrics_from_daily_and_trades(daily_r: np.ndarray, tr_rets: np.ndarray, csi_pct: float) -> dict:
    T = len(daily_r)
    nav = float(np.prod(1.0 + daily_r)) if T > 0 else 1.0
    cagr = (nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if (T > 0 and nav > 0) else -100.0
    cum_d = np.cumprod(1.0 + daily_r)
    pk_d = np.maximum.accumulate(np.insert(cum_d, 0, 1.0))[1:]
    mdd_d = float(np.max((pk_d - cum_d) / pk_d) * 100.0) if T > 0 else 0.0
    mu_d = float(np.mean(daily_r)) if T > 0 else 0.0
    sd_d = float(np.std(daily_r, ddof=1)) if T > 1 else 0.0
    sharpe_d = (mu_d / sd_d) * math.sqrt(TRD_DAYS_YEAR) if sd_d > 1e-12 else 0.0
    down_d = np.minimum(0.0, daily_r)
    down_dev = math.sqrt(float(np.mean(down_d ** 2))) if T > 0 else 0.0
    sortino_d = (mu_d / down_dev) * math.sqrt(TRD_DAYS_YEAR) if down_dev > 1e-12 else 0.0
    calmar_d = (cagr / mdd_d) if mdd_d > 1e-9 else 0.0
    ann_vol = sd_d * math.sqrt(TRD_DAYS_YEAR) * 100.0

    n = len(tr_rets)
    if n > 0:
        w, l = tr_rets[tr_rets > 0], tr_rets[tr_rets <= 0]
        wr = float(len(w) / n * 100.0)
        plr = float(w.mean() / abs(l.mean())) if (len(w) > 0 and len(l) > 0 and l.mean() < 0) else (99.0 if len(w) > 0 else 0.0)
        cum_t = np.cumprod(1.0 + tr_rets)
        pk_t = np.maximum.accumulate(np.insert(cum_t, 0, 1.0))[1:]
        mdd_t = float(np.max((pk_t - cum_t) / pk_t) * 100.0)
        tr_mean = float(tr_rets.mean() * 100.0)
        tr_sd = float(tr_rets.std(ddof=1)) if n > 1 else 0.0
        tr_sr = float(tr_rets.mean() / tr_sd) if tr_sd > 1e-12 else 0.0
    else:
        wr, plr, mdd_t, tr_mean, tr_sr = 0.0, 0.0, 0.0, 0.0, 0.0

    return {
        "trades": int(n), "wr_pct": round(wr, 2), "plr": round(plr, 2),
        "trade_mean_pct": round(tr_mean, 2), "trade_sharpe": round(tr_sr, 3),
        "total_nav": round(nav, 4), "cagr_pct": round(cagr, 2),
        "ann_vol_pct": round(ann_vol, 2), "daily_mdd_pct": round(mdd_d, 2),
        "trade_mdd_pct": round(mdd_t, 2), "daily_sharpe": round(sharpe_d, 3),
        "daily_sortino": round(sortino_d, 3), "calmar": round(calmar_d, 3),
        "csi300_excess_pp": round((nav - 1.0) * 100.0 - csi_pct, 2),
    }


def audit_pillar6_3_purged_cv(ledgers: dict, daily_mtm: dict, cal_dts: list[str], dt_to_idx: dict) -> dict:
    T = len(cal_dts)
    fold_bounds = []
    step = T // 5
    for k in range(5):
        s = k * step
        e = (k + 1) * step - 1 if k < 4 else T - 1
        fold_bounds.append((s, e))

    out = {}
    for key in ["3to4", "high", "pry_ss165", "2to3", "1to2", "comb_v191"]:
        d = ledgers[key].copy()
        d["b_idx"] = d["buy_date"].map(dt_to_idx)
        d["e_idx"] = d["exit_date"].map(dt_to_idx)
        dr = daily_mtm[key]

        full_tr = d["net_ret"].to_numpy(float)
        full_tr_sd = float(full_tr.std(ddof=1)) if len(full_tr) > 1 else 0.0
        full_d_sd = float(dr.std(ddof=1)) if T > 1 else 0.0
        full_stats = {
            "n": int(len(full_tr)),
            "trade_mean_pct": round(float(full_tr.mean() * 100.0), 2),
            "trade_sharpe": round(float(full_tr.mean() / full_tr_sd), 3) if full_tr_sd > 0 else 0.0,
            "daily_mtm_ann_mean_pct": round(float(dr.mean() * TRD_DAYS_YEAR * 100.0), 2),
            "daily_mtm_sharpe_ann": round(float(dr.mean() / full_d_sd * math.sqrt(TRD_DAYS_YEAR)), 3) if full_d_sd > 0 else 0.0,
        }

        folds_res = []
        oos_pooled_rets = []
        for fi, (fs, fe) in enumerate(fold_bounds, 1):
            te_mask = (d["b_idx"] >= fs) & (d["b_idx"] <= fe)
            # Raw train: buy_date not in fold
            raw_tr_mask = ~te_mask
            # Strict Purged & Embargoed train:
            # 1) Pre-test train trades must exit strictly before f_start (e_idx < fs)
            # 2) Post-test train trades must buy strictly after f_end + embargo (b_idx > fe + EMBARGO_DAYS)
            purged_tr_mask = (d["e_idx"] < fs) | (d["b_idx"] > fe + EMBARGO_DAYS)
            purged_cnt = int((raw_tr_mask & (~purged_tr_mask)).sum())

            d_te = d[te_mask]
            te_rets = d_te["net_ret"].to_numpy(float)
            oos_pooled_rets.extend(te_rets.tolist())
            te_dr = dr[fs : fe + 1]
            te_d_sd = float(te_dr.std(ddof=1)) if len(te_dr) > 1 else 0.0
            te_d_sr = float(te_dr.mean() / te_d_sd * math.sqrt(TRD_DAYS_YEAR)) if te_d_sd > 1e-12 else 0.0

            tr_raw_m = float(d.loc[raw_tr_mask, "net_ret"].mean() * 100.0) if raw_tr_mask.any() else 0.0
            tr_prg_m = float(d.loc[purged_tr_mask, "net_ret"].mean() * 100.0) if purged_tr_mask.any() else 0.0
            te_t_sd = float(te_rets.std(ddof=1)) if len(te_rets) > 1 else 0.0

            folds_res.append({
                "fold": fi,
                "window": f"{cal_dts[fs]} ~ {cal_dts[fe]}",
                "n_test": int(len(te_rets)),
                "n_train_raw": int(raw_tr_mask.sum()),
                "n_train_purged": int(purged_tr_mask.sum()),
                "purged_embargoed_samples": purged_cnt,
                "train_raw_mean_pct": round(tr_raw_m, 2),
                "train_purged_mean_pct": round(tr_prg_m, 2),
                "test_wr_pct": round(float((te_rets > 0).mean() * 100.0), 2) if len(te_rets) else 0.0,
                "test_trade_mean_pct": round(float(te_rets.mean() * 100.0), 2) if len(te_rets) else 0.0,
                "test_trade_sharpe": round(float(te_rets.mean() / te_t_sd), 3) if te_t_sd > 1e-12 else 0.0,
                "test_fold_nav": round(float(np.prod(1.0 + te_rets)), 4) if len(te_rets) else 1.0,
                "test_daily_mtm_sharpe_ann": round(te_d_sr, 3),
            })

        fold_means = [f["test_trade_mean_pct"] for f in folds_res if f["n_test"] > 0]
        fold_d_srs = [f["test_daily_mtm_sharpe_ann"] for f in folds_res]
        fold_navs = [f["test_fold_nav"] for f in folds_res]
        pos_folds = sum(1 for f in folds_res if f["test_fold_nav"] > 1.0)
        worst_by_nav = min(folds_res, key=lambda f: f["test_fold_nav"])
        worst_by_sr = min(folds_res, key=lambda f: f["test_daily_mtm_sharpe_ann"])
        pooled_arr = np.array(oos_pooled_rets, dtype=float)

        out[key] = {
            "embargo_trading_days": EMBARGO_DAYS,
            "full_sample": full_stats,
            "cv_summary": {
                "mean_fold_trade_mean_pct": round(float(np.mean(fold_means)), 2) if fold_means else 0.0,
                "pooled_oos_trade_mean_pct": round(float(pooled_arr.mean() * 100.0), 2) if len(pooled_arr) else 0.0,
                "mean_fold_daily_sharpe_ann": round(float(np.mean(fold_d_srs)), 3),
                "sharpe_diff_full_minus_cv_mean": round(full_stats["daily_mtm_sharpe_ann"] - float(np.mean(fold_d_srs)), 3),
                "worst_fold_by_nav": {"fold": worst_by_nav["fold"], "window": worst_by_nav["window"], "nav": worst_by_nav["test_fold_nav"], "trade_mean_pct": worst_by_nav["test_trade_mean_pct"]},
                "worst_fold_by_daily_sharpe": {"fold": worst_by_sr["fold"], "window": worst_by_sr["window"], "daily_sharpe": worst_by_sr["test_daily_mtm_sharpe_ann"]},
                "positive_folds_count": int(pos_folds),
                "positive_folds_pct": round(pos_folds / 5.0 * 100.0, 1),
                "total_purged_across_5folds": int(sum(f["purged_embargoed_samples"] for f in folds_res)),
            },
            "folds": folds_res,
        }
    return out


def audit_pillar7_1_correlations(daily_mtm: dict, cal_dts: list[str], sh300: dict) -> dict:
    keys = ["3to4", "high", "pry_ss165", "2to3", "1to2"]
    df_r = pd.DataFrame({k: daily_mtm[k] for k in keys}, index=cal_dts)

    # CSI 300 daily returns aligned on cal_dts
    all_sh_dts = sorted(sh300.keys())
    idx_start_pos = all_sh_dts.index(cal_dts[0])
    prev_close0 = float(sh300[all_sh_dts[idx_start_pos - 1]]) if idx_start_pos > 0 else float(sh300[cal_dts[0]])
    csi_vals = np.array([float(sh300[d]) for d in cal_dts], dtype=float)
    csi_prev = np.concatenate([[prev_close0], csi_vals[:-1]])
    csi_ret = csi_vals / csi_prev - 1.0

    def _corr_pack(sub_df: pd.DataFrame) -> dict:
        p_mat = sub_df.corr(method="pearson").fillna(0.0).round(4)
        s_mat = sub_df.corr(method="spearman").fillna(0.0).round(4)
        vals = p_mat.to_numpy()
        off_diag = [vals[i, j] for i in range(len(keys)) for j in range(i + 1, len(keys))]
        return {
            "n_days": int(len(sub_df)),
            "pearson": {k: {k2: float(p_mat.loc[k, k2]) for k2 in keys} for k in keys},
            "spearman": {k: {k2: float(s_mat.loc[k, k2]) for k2 in keys} for k in keys},
            "mean_pairwise_pearson": round(float(np.mean(off_diag)), 4),
            "max_pairwise_pearson": round(float(np.max(off_diag)), 4),
        }

    # Conditioned subsets
    q10_thr = float(np.quantile(csi_ret, 0.10))
    csi_worst10_mask = csi_ret <= q10_thr
    any_loss_mask = (df_r < 0.0).any(axis=1)
    any_active_mask = (df_r.abs() > 1e-12).any(axis=1)

    # Pairwise active-union and pairwise loss-conditioned correlations
    pair_active_p, pair_downside_p = {k: {} for k in keys}, {k: {} for k in keys}
    for i, k1 in enumerate(keys):
        for j, k2 in enumerate(keys):
            if i == j:
                pair_active_p[k1][k2] = 1.0
                pair_downside_p[k1][k2] = 1.0
            else:
                m_act = (df_r[k1].abs() > 1e-12) | (df_r[k2].abs() > 1e-12)
                m_dn = (df_r[k1] < 0.0) | (df_r[k2] < 0.0)
                c_a = df_r.loc[m_act, k1].corr(df_r.loc[m_act, k2]) if m_act.sum() >= 3 else 0.0
                c_d = df_r.loc[m_dn, k1].corr(df_r.loc[m_dn, k2]) if m_dn.sum() >= 3 else 0.0
                pair_active_p[k1][k2] = round(0.0 if pd.isna(c_a) else float(c_a), 4)
                pair_downside_p[k1][k2] = round(0.0 if pd.isna(c_d) else float(c_d), 4)

    # Simultaneous losses & drawdowns across the 5 strategies
    loss_cnt_per_day = (df_r < -1e-6).sum(axis=1)
    nav_df = (1.0 + df_r).cumprod()
    dd_df = nav_df / nav_df.cummax() - 1.0
    dd5_cnt_per_day = (dd_df < -0.05).sum(axis=1)

    csi_worst10_perf = {}
    for k in keys:
        sub_s = df_r.loc[csi_worst10_mask, k]
        act_s = sub_s[sub_s.abs() > 1e-12]
        csi_worst10_perf[k] = {
            "active_days": int(len(act_s)),
            "all_worst10_mean_bps": round(float(sub_s.mean() * 10000.0), 2),
            "active_mean_pct": round(float(act_s.mean() * 100.0), 2) if len(act_s) else 0.0,
        }

    return {
        "full_5y_calendar": _corr_pack(df_r),
        "any_active_days_only": _corr_pack(df_r[any_active_mask]),
        "pairwise_union_active_pearson": pair_active_p,
        "downside_csi300_worst10pct": {
            "csi_q10_threshold_pct": round(q10_thr * 100.0, 2),
            **_corr_pack(df_r[csi_worst10_mask]),
            "strategy_exposure_in_crash": csi_worst10_perf,
        },
        "downside_any_strategy_loss_days": _corr_pack(df_r[any_loss_mask]),
        "pairwise_either_loss_pearson": pair_downside_p,
        "simultaneous_blowup_check": {
            "days_ge1_loss": int((loss_cnt_per_day >= 1).sum()),
            "days_ge2_simultaneous_loss": int((loss_cnt_per_day >= 2).sum()),
            "days_ge3_simultaneous_loss": int((loss_cnt_per_day >= 3).sum()),
            "max_simultaneous_losing_strategies": int(loss_cnt_per_day.max()),
            "days_ge2_in_gt5pct_dd": int((dd5_cnt_per_day >= 2).sum()),
            "days_ge3_in_gt5pct_dd": int((dd5_cnt_per_day >= 3).sum()),
        },
    }


def run_1slot_sim_exact(df_pool: pd.DataFrame) -> pd.DataFrame:
    """Exact replica of calibrate_v191_clean_ledgers / partB2 run_1slot_sim (buy_date ASC, priority ASC, score DESC, buy_hhmm ASC)."""
    s = df_pool.sort_values(
        ["buy_date", "priority", "score", "buy_hhmm"],
        ascending=[True, True, False, True],
    ).reset_index(drop=True)
    taken = []
    free_dt, free_hh = "", 0
    for r in s.itertuples(index=False):
        if free_dt == "" or r.buy_date > free_dt or (r.buy_date == free_dt and int(r.buy_hhmm) > free_hh):
            taken.append(r._asdict())
            free_dt = str(r.exit_date)
            free_hh = int(r.exit_hhmm)
    return pd.DataFrame(taken)


def audit_pillar7_2_loo(ledgers: dict, daily_mtm: dict, cal_dts: list[str], dt_to_idx: dict, bar_map: dict, csi_5y_pct: float) -> dict:
    # Method A: Realistic Single-Slot 5-Priority V19.1 (uses pry_top1 in pool just like calibrate_v191_clean_ledgers.py:305)
    cols_c = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "priority", "score", "buy_price", "exit_price", "net_ret"]
    pools_map = {
        "3to4": ledgers["3to4"].assign(strategy="三进四V4.1", priority=1)[cols_c],
        "high": ledgers["high"].assign(strategy="高标首阴V5.1", priority=2)[cols_c],
        "pry": ledgers["pry_top1"].assign(strategy="超跌撬板V2.1", priority=3)[cols_c],
        "2to3": ledgers["2to3"].assign(strategy="二进三V2.1", priority=4)[cols_c],
        "1to2": ledgers["1to2"].assign(strategy="一进二V19", priority=5)[cols_c],
    }

    base_pool = pd.concat(list(pools_map.values()), ignore_index=True)
    base_comb = run_1slot_sim_exact(base_pool)
    assert len(base_comb) == len(ledgers["comb_v191"]), f"Comb mismatch: {len(base_comb)} vs {len(ledgers['comb_v191'])}"
    assert (base_comb["code"].to_numpy() == ledgers["comb_v191"]["code"].to_numpy()).all(), "Comb code sequence mismatch!"

    base_dr, nav_chk = build_daily_mtm_series(base_comb, cal_dts, dt_to_idx, bar_map)
    assert nav_chk["nav_abs_diff"] < 1e-4, nav_chk
    base_m = metrics_from_daily_and_trades(base_dr, base_comb["net_ret"].to_numpy(float), csi_5y_pct)
    base_m["by_strategy"] = base_comb["strategy"].value_counts().to_dict()

    loo_1slot = {}
    for drop_k in ["3to4", "high", "pry", "2to3", "1to2"]:
        sub_pool = pd.concat([v for k, v in pools_map.items() if k != drop_k], ignore_index=True)
        sim_df = run_1slot_sim_exact(sub_pool)
        dr, chk = build_daily_mtm_series(sim_df, cal_dts, dt_to_idx, bar_map)
        assert chk["nav_abs_diff"] < 1e-4, (drop_k, chk)
        m = metrics_from_daily_and_trades(dr, sim_df["net_ret"].to_numpy(float), csi_5y_pct)
        m["by_strategy"] = sim_df["strategy"].value_counts().to_dict()
        m["marginal_delta_sharpe"] = round(base_m["daily_sharpe"] - m["daily_sharpe"], 4)
        m["marginal_delta_calmar"] = round(base_m["calmar"] - m["calmar"], 4)
        m["marginal_delta_mdd_pp"] = round(base_m["daily_mdd_pct"] - m["daily_mdd_pct"], 2)
        m["nav_multiplier_contrib"] = round(base_m["total_nav"] / max(m["total_nav"], 1e-9), 2)
        loo_1slot[f"drop_{drop_k}"] = m

    # Method B: Equal-Weight Daily MTM Portfolio (5 standalone sleeves)
    keys_ew = ["3to4", "high", "pry_ss165", "2to3", "1to2"]
    r_mat = np.column_stack([daily_mtm[k] for k in keys_ew])
    ew_base_r = r_mat.mean(axis=1)
    ew_base_m = metrics_from_daily_and_trades(ew_base_r, np.array([]), csi_5y_pct)
    ew_base_m.pop("trades"); ew_base_m.pop("wr_pct"); ew_base_m.pop("plr"); ew_base_m.pop("trade_mean_pct"); ew_base_m.pop("trade_sharpe"); ew_base_m.pop("trade_mdd_pct")

    loo_ew = {}
    for idx_drop, drop_k in enumerate(keys_ew):
        rem_idx = [i for i in range(5) if i != idx_drop]
        dr_loo = r_mat[:, rem_idx].mean(axis=1)
        m = metrics_from_daily_and_trades(dr_loo, np.array([]), csi_5y_pct)
        for col in ("trades", "wr_pct", "plr", "trade_mean_pct", "trade_sharpe", "trade_mdd_pct"):
            m.pop(col)
        m["marginal_delta_sharpe"] = round(ew_base_m["daily_sharpe"] - m["daily_sharpe"], 4)
        m["marginal_delta_calmar"] = round(ew_base_m["calmar"] - m["calmar"], 4)
        m["marginal_delta_mdd_pp"] = round(ew_base_m["daily_mdd_pct"] - m["daily_mdd_pct"], 2)
        m["nav_multiplier_contrib"] = round(ew_base_m["total_nav"] / max(m["total_nav"], 1e-9), 4)
        loo_ew[f"drop_{drop_k}"] = m

    return {
        "single_slot_5priority_v191": {"baseline": base_m, "leave_one_out": loo_1slot},
        "equal_weight_5sleeves_daily": {"baseline": ew_base_m, "leave_one_out": loo_ew},
    }


def audit_pillar7_3_shadow_reconcile(ledgers: dict) -> dict:
    ps = json.load(open(PORTFOLIO_STATE, encoding="utf-8"))
    acc_cn = ps.get("accounts", {}).get("a_share", {})
    tlog = ps.get("trade_log", [])
    cn_trades = [t for t in tlog if str(t.get("account", "")) == "a_share" or (not str(t.get("ticker", "")).isalpha())]
    v191_sids = {"s_3to4", "s_high", "s_pry", "s_2to3", "s_1to2"}
    v191_trades = [t for t in cn_trades if t.get("strategy_id") in v191_sids or str(t.get("date", ""))[:10] >= "2026-11-16"]
    t_000011_log = [t for t in cn_trades if "000011" in str(t.get("ticker", ""))]

    ledger_000011 = {k: int((df["code"] == "000011").sum()) for k, df in ledgers.items()}
    recent_legacy = [
        {
            "id": t.get("id"), "date": t.get("date"), "ticker": t.get("ticker"),
            "name": t.get("name"), "action": t.get("action"),
            "shares": t.get("shares"), "price": t.get("price"),
            "strategy_id": t.get("strategy_id"),
            "pnl_pct": t.get("pnl_pct"),
            "reason_prefix": str(t.get("reason", ""))[:80],
        }
        for t in cn_trades[-5:]
    ]

    return {
        "v191_live_sim_trade_count": len(v191_trades),
        "v191_live_sim_window": "2026-11-16 ~ 2026-11-24",
        "current_a_share_positions": len(acc_cn.get("positions", [])),
        "current_a_share_cash_cny": acc_cn.get("cash"),
        "current_a_share_return_pct": acc_cn.get("return_pct"),
        "legacy_cn_trade_count_total": len(cn_trades),
        "last_legacy_cn_trade_date": cn_trades[-1].get("date") if cn_trades else None,
        "recent_legacy_cn_trades": recent_legacy,
        "code_000011_in_trade_log_count": len(t_000011_log),
        "code_000011_in_clean_ledgers": ledger_000011,
        "statistical_inference_verdict": (
            "样本不足尚无法做统计推断：V19.1 五策略自 2026-11-16 上线至 2026-11-24 实盘/模拟盘成交 N=0 笔；"
            "最近一笔 A 股成交为旧四分仓 2026-11-11/12 的 002578 闽发铝业 (sole_leader, strategy_id=None, "
            "重复记账买2次274,600股@6.27 -> 卖549,200股@5.98, 净亏 -4.63%)；000011 深物业A 在实盘流水与6份五年干净账本中出现均为 0 次。"
        ),
    }


def _sim_cusum_mc(rng, rets_h1: np.ndarray, k_ref: float, h_grid: np.ndarray, n_5y: int, n_mc: int = 5000, max_arl_len: int = 12000):
    """Single-pass multi-threshold vectorized bootstrap MC for Tabular CUSUM S_t = max(0, S_{t-1} + k_ref - r_t)."""
    mu_1 = float(rets_h1.mean())
    rets_h0 = rets_h1 - mu_1  # exact mean=0 failure shift preserving empirical variance/skewness
    n_pool = len(rets_h1)
    n_h = len(h_grid)
    paths_h1 = rets_h1[rng.integers(0, n_pool, size=(n_mc, max_arl_len))]
    paths_h0 = rets_h0[rng.integers(0, n_pool, size=(n_mc, 400))]

    hit1 = np.full((n_h, n_mc), max_arl_len + 1, dtype=int)
    s1 = np.zeros(n_mc, dtype=float)
    for t in range(max_arl_len):
        s1 = np.maximum(0.0, s1 + k_ref - paths_h1[:, t])
        smax = float(s1.max())
        if smax < h_grid[0]:
            continue
        for j, hv in enumerate(h_grid):
            if hv > smax:
                break
            upd = (hit1[j] > max_arl_len) & (s1 >= hv)
            if upd.any():
                hit1[j, upd] = t + 1
        if (hit1[-1] <= max_arl_len).all():
            break

    hit0 = np.full((n_h, n_mc), 401, dtype=int)
    s0 = np.zeros(n_mc, dtype=float)
    for t in range(400):
        s0 = np.maximum(0.0, s0 + k_ref - paths_h0[:, t])
        smax = float(s0.max())
        if smax < h_grid[0]:
            continue
        for j, hv in enumerate(h_grid):
            if hv > smax:
                break
            upd = (hit0[j] > 400) & (s0 >= hv)
            if upd.any():
                hit0[j, upd] = t + 1
        if (hit0[-1] <= 400).all():
            break

    records = []
    for j, hv in enumerate(h_grid):
        fa5 = float((hit1[j] <= n_5y).mean())
        a0 = float(hit1[j].mean())
        cens = float((hit1[j] > max_arl_len).mean() * 100.0)
        a0_pois = float(-n_5y / math.log(max(1e-6, 1.0 - fa5))) if 0.0 < fa5 < 1.0 else a0
        a1 = float(hit0[j].mean())
        d20 = float((hit0[j] <= 20).mean())
        d30 = float((hit0[j] <= 30).mean())
        records.append({
            "h": round(float(hv), 4),
            "fa_5y_pct": round(fa5 * 100.0, 2),
            "arl0": round(a0, 1),
            "arl0_censored_pct": round(cens, 2),
            "arl0_poisson_est": round(a0_pois, 1),
            "arl1": round(a1, 1),
            "det_20tr_pct": round(d20 * 100.0, 1),
            "det_30tr_pct": round(d30 * 100.0, 1),
        })
    return records


def audit_pillar7_4_cusum_sprt(ledgers: dict) -> dict:
    rng = np.random.default_rng(20261124)
    out = {}
    for key in ["3to4", "high", "pry_ss165", "2to3", "1to2", "comb_v191"]:
        d = ledgers[key]
        rets = d["net_ret"].to_numpy(float)
        n = len(rets)
        mu_1 = float(rets.mean())
        sd = float(rets.std(ddof=1))
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        p_1 = float(len(wins) / n)
        avg_w = float(wins.mean())
        avg_l = float(losses.mean())
        plr = avg_w / abs(avg_l)
        be_wr = 1.0 / (1.0 + plr)
        p_0 = max(0.45, be_wr)

        # Historical max consecutive losses
        mc_hist, cur_c = 0, 0
        for r in rets:
            cur_c = cur_c + 1 if r <= 0 else 0
            mc_hist = max(mc_hist, cur_c)

        # 1. One-sided Tabular CUSUM: S_t = max(0, S_{t-1} + (k_ref - r_t)), k_ref = mu_1 / 2
        k_ref = 0.5 * mu_1
        # Search grid of h in raw shortfall units (from 0.5*sd to 9.5*sd)
        h_grid = np.linspace(max(0.10, 0.5 * sd), max(0.80, 9.5 * sd), 46)
        grid_res = _sim_cusum_mc(rng, rets, k_ref, h_grid, n, n_mc=5000, max_arl_len=12000)

        # Red Halt: first h satisfying BOTH ARL0 >= 250 AND 5Y FA < 5.0%
        red_cands = [g for g in grid_res if g["arl0"] >= 250.0 and g["fa_5y_pct"] < 5.0]
        assert red_cands, f"CUSUM Red grid insufficient for {key}"
        red_pick = red_cands[0]
        # Yellow Warn: first h satisfying ARL0 >= 250 and 5Y FA <= 15.0% (earlier warning before red)
        yel_cands = [g for g in grid_res if g["arl0"] >= 250.0 and g["fa_5y_pct"] <= 15.0]
        yel_pick = yel_cands[0] if (yel_cands and yel_cands[0]["h"] < red_pick["h"]) else red_pick

        # Historical CUSUM replay
        def replay_cusum(h_val: float):
            s, mx, hits = 0.0, 0.0, []
            for idx_r, r in enumerate(rets):
                s = max(0.0, s + k_ref - float(r))
                mx = max(mx, s)
                if s >= h_val:
                    hits.append((int(idx_r + 1), str(d.iloc[idx_r]["exit_date"]), round(s * 100.0, 2)))
                    s = 0.0
            return round(mx * 100.0, 2), hits

        hist_max_s, hist_red_hits = replay_cusum(red_pick["h"])
        _, hist_yel_hits = replay_cusum(yel_pick["h"])

        # 2. Wald SPRT (Bernoulli WR: p0 vs p1 AND Gaussian return LLR: mu0=0 vs mu1)
        llr_win_b = math.log(p_0 / p_1) if p_1 > p_0 else -0.01
        llr_loss_b = math.log((1.0 - p_0) / (1.0 - p_1)) if p_1 > p_0 else 0.01
        b_yel_hi = math.log(0.90 / 0.10)  # ln(9) = 2.1972
        b_red_hi = math.log(0.95 / 0.05)  # ln(19) = 2.9444
        consec_yel_bern = math.ceil(b_yel_hi / llr_loss_b)
        consec_red_bern = math.ceil(b_red_hi / llr_loss_b)

        # Gaussian return LLR SPRT step: llr_t = (mu_1 / sd^2) * (mu_1/2 - r_t)
        # Positive favours H0 (decay mu=0)
        def replay_sprt_ret(thr: float):
            w, mx, hits = 0.0, 0.0, 0
            coef = mu_1 / (sd * sd)
            for r in rets:
                w = max(0.0, w + coef * (k_ref - float(r)))
                mx = max(mx, w)
                if w >= thr:
                    hits += 1
                    w = 0.0
            return round(mx, 3), hits

        sprt_mx_hist, sprt_red_hist = replay_sprt_ret(b_red_hi)
        _, sprt_yel_hist = replay_sprt_ret(b_yel_hi)

        # Consec losses under Gaussian LLR assuming typical loss = avg_l:
        step_avg_loss = (mu_1 / (sd * sd)) * (k_ref - avg_l)
        consec_yel_ret = max(1, math.ceil(b_yel_hi / step_avg_loss))
        consec_red_ret = max(1, math.ceil(b_red_hi / step_avg_loss))

        # 3. Calibrate PM-executable rolling-N window rules via 5000 MC (control 5Y FA < 5% for Red, ~10-15% for Yellow)
        roll_N = 10 if n <= 25 else (15 if n <= 50 else 20)
        # Simulate empirical H1 rolling-N paths
        h1_idx = rng.integers(0, n, size=(5000, n))
        h1_paths = rets[h1_idx]
        if n >= roll_N:
            csum = np.cumsum(np.insert(h1_paths, 0, 0.0, axis=1), axis=1)
            rm_h1 = (csum[:, roll_N:] - csum[:, :-roll_N]) / roll_N
            min_rm_h1 = rm_h1.min(axis=1)
            cwin = np.cumsum(np.insert((h1_paths > 0).astype(int), 0, 0, axis=1), axis=1)
            rw_h1 = (cwin[:, roll_N:] - cwin[:, :-roll_N]) / roll_N
            min_rw_h1 = rw_h1.min(axis=1)
            y_red = float(np.percentile(min_rm_h1, 5.0))
            y_yel = float(np.percentile(min_rm_h1, 15.0))
            z_red = float(np.percentile(min_rw_h1, 5.0))
            z_yel = float(np.percentile(min_rw_h1, 15.0))
            if z_yel <= z_red + 1e-6:
                z_yel = min(p_0, round((round(z_red * roll_N) + 1) / roll_N, 4))
        else:
            # For pry_ss165 (n=16 < 20), roll_N = 10 already <= 16
            y_red, y_yel, z_red, z_yel = -0.02, 0.0, p_0 - 0.10, p_0

        # Consecutive loss MC under H1 over 5Y N trades: find smallest X such that P(max streak >= X in N trades | H1) < 5%
        streak_max_h1 = np.zeros(5000, dtype=int)
        cur_s = np.zeros(5000, dtype=int)
        is_l_h1 = h1_paths <= 0
        for t in range(n):
            cur_s = np.where(is_l_h1[:, t], cur_s + 1, 0)
            streak_max_h1 = np.maximum(streak_max_h1, cur_s)
        x_consec_red = int(np.percentile(streak_max_h1, 96)) + 1
        x_consec_red = max(x_consec_red, mc_hist + 1)
        x_consec_yel = max(2 if n <= 50 else 3, x_consec_red - 1)

        out[key] = {
            "empirical_h1": {
                "n_trades": int(n), "mu_1_pct": round(mu_1 * 100.0, 2), "sigma_pct": round(sd * 100.0, 2),
                "snr": round(mu_1 / sd, 3), "win_rate_p1_pct": round(p_1 * 100.0, 2),
                "avg_win_pct": round(avg_w * 100.0, 2), "avg_loss_pct": round(avg_l * 100.0, 2),
                "plr": round(plr, 2), "breakeven_wr_pct": round(be_wr * 100.0, 2),
                "h0_p0_wr_pct": round(p_0 * 100.0, 2), "hist_max_consec_losses": int(mc_hist),
            },
            "tabular_cusum_mc5000": {
                "k_ref_pct": round(k_ref * 100.0, 2),
                "k_sigma_units": round(k_ref / sd, 3),
                "yellow_warning": {
                    "h_shortfall_pct": round(yel_pick["h"] * 100.0, 2),
                    "h_sigma_units": round(yel_pick["h"] / sd, 2),
                    "arl0_trades": yel_pick["arl0"], "fa_5y_pct": yel_pick["fa_5y_pct"],
                    "arl1_trades_to_detect_h0": yel_pick["arl1"],
                    "det_within_20tr_pct": yel_pick["det_20tr_pct"],
                    "hist_5y_triggers": len(hist_yel_hits),
                },
                "red_halt": {
                    "h_shortfall_pct": round(red_pick["h"] * 100.0, 2),
                    "h_sigma_units": round(red_pick["h"] / sd, 2),
                    "arl0_trades": red_pick["arl0"],
                    "arl0_censored_pct": red_pick["arl0_censored_pct"],
                    "arl0_poisson_est": red_pick["arl0_poisson_est"],
                    "fa_5y_pct": red_pick["fa_5y_pct"],
                    "arl1_trades_to_detect_h0": red_pick["arl1"],
                    "det_within_20tr_pct": red_pick["det_20tr_pct"],
                    "det_within_30tr_pct": red_pick["det_30tr_pct"],
                    "hist_5y_max_S_pct": hist_max_s,
                    "hist_5y_triggers": len(hist_red_hits),
                },
            },
            "wald_sprt": {
                "yellow_alpha_beta_010_upper": round(b_yel_hi, 4),
                "red_alpha_beta_005_upper": round(b_red_hi, 4),
                "bernoulli_wr_llr": {
                    "p0_pct": round(p_0 * 100.0, 2), "p1_pct": round(p_1 * 100.0, 2),
                    "llr_win": round(llr_win_b, 4), "llr_loss": round(llr_loss_b, 4),
                    "consec_losses_yellow": int(consec_yel_bern),
                    "consec_losses_red": int(consec_red_bern),
                },
                "return_gaussian_llr": {
                    "consec_avg_losses_yellow": int(consec_yel_ret),
                    "consec_avg_losses_red": int(consec_red_ret),
                    "hist_5y_max_W": sprt_mx_hist,
                    "hist_5y_yellow_hits": sprt_yel_hist,
                    "hist_5y_red_hits": sprt_red_hist,
                },
            },
            "pm_executable_redlines": {
                "rolling_N_trades": roll_N,
                "yellow_half_size_rule": (
                    f"连续亏损 >= {x_consec_yel} 笔，或滚动最近 {roll_N} 笔均收益 < {y_yel*100:.2f}%，"
                    f"或滚动 {roll_N} 笔胜率 < {z_yel*100:.1f}% -> 降至半仓/警告黄灯"
                ),
                "red_circuit_breaker_rule": (
                    f"连续亏损 >= {x_consec_red} 笔，或滚动最近 {roll_N} 笔均收益 < {y_red*100:.2f}%，"
                    f"或滚动 {roll_N} 笔胜率 < {z_red*100:.1f}%，或 CUSUM 累计亏空 S_t >= {red_pick['h']*100:.1f}% -> 停机熔断复核"
                ),
                "consec_loss_yellow": int(x_consec_yel),
                "consec_loss_red": int(x_consec_red),
                "rolling_mean_yellow_pct": round(y_yel * 100.0, 2),
                "rolling_mean_red_pct": round(y_red * 100.0, 2),
                "rolling_wr_yellow_pct": round(z_yel * 100.0, 1),
                "rolling_wr_red_pct": round(z_red * 100.0, 1),
            },
        }
    return out


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    sh300 = json.load(open(IDX_JSON, encoding="utf-8"))["sh000300"]
    all_sh_dts = sorted(sh300.keys())
    cal_dts = [d for d in all_sh_dts if "2021-11-15" <= d <= "2026-11-16"]
    dt_to_idx = {d: i for i, d in enumerate(cal_dts)}

    prev_dts = [d for d in all_sh_dts if d < "2021-11-15"]
    csi_5y_pct = (sh300["2026-11-16"] / sh300[prev_dts[-1]] - 1.0) * 100.0

    # Load all clean ledgers
    ledgers = {}
    for key, _, _, fn in STRAT_SPECS:
        ledgers[key] = norm_ledger(pd.read_csv(f"{PARTC}/{fn}", dtype={"code": str}))
    ledgers["pry_top1"] = norm_ledger(pd.read_csv(f"{PARTC}/{PRY_TOP1_FILE}", dtype={"code": str}))
    ledgers["comb_v191"] = norm_ledger(pd.read_csv(f"{PARTC}/{COMB_FILE}", dtype={"code": str}))
    ledgers["3to4_strict102"] = norm_ledger(pd.read_csv(f"{PARTC}/ledger_3to4_v41_strict102_clean_ref.csv", dtype={"code": str}))
    ledgers["high_m42"] = norm_ledger(pd.read_csv(f"{PARTC}/ledger_high_v51_m42_clean_ref.csv", dtype={"code": str}))

    print("[1/5] Loading daily price panel (a_daily + a_delisted_daily)...")
    df_daily = load_daily_panel()
    bar_lu = {
        (r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf))
        for r in df_daily[["c6", "dt", "open", "close", "adj_close", "qfq_factor", "adjf"]].itertuples(index=False)
    }

    print("[2/5] Running Pillar 6.1 (raw vs qfq) & 6.2 (reporting lag)...")
    p6_1 = audit_pillar6_1_raw_vs_qfq(df_daily, ledgers)
    p6_2 = audit_pillar6_2_reporting_lag()

    print("[3/5] Building exact daily MTM series & running Pillar 6.3 Purged-Embargoed 5-Fold CV...")
    daily_mtm = {}
    mtm_checks = {}
    for k in ["3to4", "high", "pry_ss165", "pry_top1", "2to3", "1to2", "comb_v191"]:
        dr, chk = build_daily_mtm_series(ledgers[k], cal_dts, dt_to_idx, bar_lu)
        assert chk["nav_abs_diff"] < 1e-4, (k, chk)
        daily_mtm[k] = dr
        mtm_checks[k] = chk
    p6_3 = audit_pillar6_3_purged_cv(ledgers, daily_mtm, cal_dts, dt_to_idx)

    print("[4/5] Running Pillar 7.1 Correlations, 7.2 LOO & 7.3 Shadow Reconciliation...")
    p7_1 = audit_pillar7_1_correlations(daily_mtm, cal_dts, sh300)
    p7_2 = audit_pillar7_2_loo(ledgers, daily_mtm, cal_dts, dt_to_idx, bar_lu, csi_5y_pct)
    p7_3 = audit_pillar7_3_shadow_reconcile(ledgers)

    print("[5/5] Running Pillar 7.4 5,000-run MC CUSUM & Wald SPRT calibration...")
    p7_4 = audit_pillar7_4_cusum_sprt(ledgers)

    out = sanitize_json({
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "calendar_window": f"{cal_dts[0]} ~ {cal_dts[-1]}",
            "trading_days_5y": len(cal_dts),
            "csi300_5y_pct": round(csi_5y_pct, 2),
            "elapsed_sec": round(time.time() - t0, 2),
            "d12_yfinance_imported": "yfinance" in sys.modules,
            "daily_mtm_nav_reconciliation": mtm_checks,
        },
        "pillar6_hygiene": {
            "raw_vs_qfq_audit": p6_1,
            "reporting_lag_initial_value_audit": p6_2,
            "purged_embargoed_5fold_cv": p6_3,
        },
        "pillar7_portfolio_cusum": {
            "daily_mtm_correlation_and_tail": p7_1,
            "loo_marginal_contribution": p7_2,
            "shadow_portfolio_reconciliation": p7_3,
            "cusum_sprt_redlines": p7_4,
        },
    })

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[DONE] Saved {OUT_JSON} in {time.time()-t0:.2f}s")


if __name__ == "__main__":
    main()
