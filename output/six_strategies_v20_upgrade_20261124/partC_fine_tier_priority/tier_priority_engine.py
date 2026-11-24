#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part C: Six-Strategy Fine-Tier Collision Priority Optimizer & Strict IS->OOS Blind Tester.

Clean reusable CLI accepting 6 strategy clean ledger CSVs.
Strict rules:
  - 100% local read-only on inputs; NEVER imports yfinance (D12).
  - ZERO cap10m calculation or mention anywhere.
  - Strict physical causality: buy_date > prev_exit_date or (buy_date == prev_exit_date and buy_hhmm > prev_exit_hhmm).
  - All tier parameters, rankings, and Empirical Bayes shrinkage weights fitted ONLY on IS (<= is_end),
    then frozen without modification on blind OOS (>= oos_start) and 2026 (>= y26_start).
"""

import argparse
import itertools
import json
import math
import os
import pickle
import sys
import time
import warnings
from typing import Callable, Optional

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

warnings.filterwarnings("ignore", category=FutureWarning)
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
PC_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
V11_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
MW1_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high"
MW2_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry"
MW3_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part3_1to2"
OUT_DEFAULT = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority/partC_baseline_tier_priority.json"

DEFAULT_CSVS = {
    "3to4": f"{PC_DIR}/ledger_3to4_v41_clean.csv",
    "high": f"{PC_DIR}/ledger_high_v51_clean.csv",
    "pry": f"{PC_DIR}/ledger_pry_v21_ss165_clean.csv",
    "2to3": f"{PC_DIR}/ledger_2to3_v21_opt_std90_clean.csv",
    "1to2": f"{PC_DIR}/ledger_1to2_v19_clean.csv",
    "20cm": f"{V11_DIR}/final_v11_ledger.csv",
}

STRAT_ORDER = ["3to4", "high", "pry", "2to3", "1to2", "20cm"]
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
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def assign_physical_tier(strategy: str, score: float) -> str:
    sc = float(score)
    if strategy == "3to4":
        return "3to4_S(>=102)" if sc >= 102.0 else "3to4_A(90-101)"
    if strategy == "high":
        return "high_S(>=96)" if sc >= 96.0 else "high_A(88-95)"
    if strategy == "pry":
        return "pry_S(>=175)" if sc >= 175.0 else "pry_A(165-174)"
    if strategy == "2to3":
        return "2to3_S(>=96)" if sc >= 96.0 else "2to3_A(90-95)"
    if strategy == "1to2":
        if sc >= 340.0:
            return "1to2_S(>=340)"
        if sc >= 304.8:
            return "1to2_A(304.8-339.9)"
        return "1to2_FB(295-304.7)"
    if strategy == "20cm":
        return "20cm_S(>=82)" if sc >= 82.0 else "20cm_A(76-81)"
    raise ValueError(f"Unknown strategy: {strategy}")


def load_strategy_csv(strategy: str, path: str, start_dt: str, end_dt: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    c6_col = "c6" if ("c6" in df.columns and "code" not in df.columns) else "code"
    df["code"] = df[c6_col].astype(str).str.strip().str.zfill(6)
    df["buy_date"] = df["buy_date"].astype(str).str[:10]
    df["exit_date"] = df["exit_date"].astype(str).str[:10]
    df = df[df["buy_date"].between(start_dt, end_dt)].copy()
    if "buy_hhmm" not in df.columns:
        df["buy_hhmm"] = 925
    if "exit_hhmm" not in df.columns:
        df["exit_hhmm"] = 1500
    df["buy_hhmm"] = pd.to_numeric(df["buy_hhmm"], errors="coerce").fillna(925).astype(int)
    df["exit_hhmm"] = pd.to_numeric(df["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
    df["score"] = pd.to_numeric(df["score"], errors="coerce").astype(float)
    df["net_ret"] = pd.to_numeric(df["net_ret"], errors="coerce").astype(float)
    if "name" not in df.columns:
        df["name"] = ""
    df["name"] = df["name"].fillna("").astype(str)
    if "buy_px" in df.columns and "buy_price" not in df.columns:
        df["buy_price_val"] = pd.to_numeric(df["buy_px"], errors="coerce").astype(float)
        df["is_adj_px"] = True
    elif "buy_price" in df.columns:
        df["buy_price_val"] = pd.to_numeric(df["buy_price"], errors="coerce").astype(float)
        df["is_adj_px"] = False
    else:
        df["buy_price_val"] = np.nan
        df["is_adj_px"] = False
    df["strategy"] = strategy
    df["tier"] = [assign_physical_tier(strategy, sc) for sc in df["score"]]
    df["is_untrig"] = False
    cols = [
        "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
        "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig",
    ]
    return df[cols].reset_index(drop=True)


def load_daily_bars(codes: set[str]) -> tuple[dict, dict, list[str]]:
    with open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", "r", encoding="utf-8") as f:
        sh300 = json.load(f)["sh000300"]
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp("2021-10-01")
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    df_b = pd.concat([da, dd], ignore_index=True)
    df_b["c6"] = df_b["ticker"].astype(str).str[:6]
    df_b = df_b[df_b["c6"].isin(codes)].copy()
    df_b["dt"] = df_b["date"].dt.strftime("%Y-%m-%d")
    df_b.sort_values(["c6", "dt"], inplace=True)
    df_b.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    df_b["adjf"] = np.where((df_b["close"] > 0) & (df_b["adj_close"] > 0), df_b["adj_close"] / df_b["close"], 1.0)
    bar_lu = {
        (r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf))
        for r in df_b.itertuples(index=False)
    }
    return sh300, bar_lu, sorted(sh300.keys())


def build_untriggered_baseline_pool(triggered_df: pd.DataFrame, start_dt: str, end_dt: str) -> pd.DataFrame:
    """Extract real 09:25 pre-trigger conditional order candidates that never hit intraday trigger."""
    rows = []
    # 1. 3to4 (>=90, buy_px is None)
    p34_pkl = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4/pit_exit_cache_full.pkl"
    if os.path.exists(p34_pkl):
        c34 = pickle.load(open(p34_pkl, "rb"))
        cand34 = c34["cand_df"].copy()
        cand34["score"] = c34["sc_v40"]
        d34_dts = set(triggered_df[triggered_df["strategy"] == "3to4"]["buy_date"])
        u34 = []
        for i in cand34.index:
            bd = str(cand34.loc[i, "buy_date"])
            if cand34.loc[i, "score"] >= 90.0 and c34["buy_entries"][i]["buy_px"] is None and start_dt <= bd <= end_dt and bd not in d34_dts:
                u34.append({
                    "buy_date": bd, "buy_hhmm": 935, "exit_date": bd, "exit_hhmm": 1030,
                    "code": str(cand34.loc[i, "code"]).zfill(6), "name": str(cand34.loc[i, "name"]),
                    "strategy": "3to4", "score": float(cand34.loc[i, "score"]),
                })
        if u34:
            u34_df = pd.DataFrame(u34).sort_values(["buy_date", "score"], ascending=[True, False]).groupby("buy_date", as_index=False).first()
            rows.append(u34_df)

    # 2. High V5.1 (sc5_1>=88, green open never hitting 1.015*open before 11:30)
    hd_script = f"{SIM}/backtests_astock/sandbox_lab/golden_regime_20261113/sub2_03_golden_relaxation_backtest.py"
    if os.path.exists(hd_script):
        a2_assets = f"{SIM}/backtests_astock2/assets"
        if a2_assets not in sys.path:
            sys.path.insert(0, a2_assets)
        src = "\n".join(open(hd_script, encoding="utf-8").read().splitlines()[:192]).replace('r["d1_to"] > 38.0', 'r["d1_to"] > 35.0')
        g_ns = {"__name__": "eng"}
        exec(src, g_ns)
        dfr, sim_trade = g_ns["dfr"], g_ns["sim_trade"]
        dhd_dts = set(triggered_df[triggered_df["strategy"] == "high"]["buy_date"])
        sub_hd = dfr[(dfr["sc5_1"] >= 88) & dfr["buy_date"].between(start_dt, end_dt)].sort_values(["buy_date", "sc5_1"], ascending=[True, False]).groupby("buy_date", as_index=False).first()
        uhd = []
        for r in sub_hd.itertuples():
            bd = str(r.buy_date)
            if sim_trade(r, "morn_cond", "S_hold_d3") is None and bd not in dhd_dts:
                uhd.append({
                    "buy_date": bd, "buy_hhmm": 935, "exit_date": bd, "exit_hhmm": 1130,
                    "code": str(r.code).zfill(6), "name": str(r.name),
                    "strategy": "high", "score": float(r.sc5_1),
                })
        if uhd:
            rows.append(pd.DataFrame(uhd))

    # 3. 1to2 V19 (base_pass_v19 & ~sim_ok)
    pt12_pq = f"{MW3_DIR}/_cache_pretrig_pool.parquet"
    if os.path.exists(pt12_pq):
        pt12 = pd.read_parquet(pt12_pq)
        d12_dts = set(triggered_df[triggered_df["strategy"] == "1to2"]["buy_date"])
        v19_pt = pt12[pt12["base_pass_v19"] & pt12["buy_date"].between(start_dt, end_dt)].sort_values(["buy_date", "sv_base", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
        u12 = v19_pt[(~v19_pt["sim_ok"]) & (~v19_pt["buy_date"].isin(d12_dts))][["buy_date", "code", "name", "base_score"]].copy()
        if not u12.empty:
            u12["buy_hhmm"] = 935
            u12["exit_date"] = u12["buy_date"]
            u12["exit_hhmm"] = 1130
            u12["strategy"] = "1to2"
            u12.rename(columns={"base_score": "score"}, inplace=True)
            rows.append(u12)

    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    out["code"] = out["code"].astype(str).str.zfill(6)
    out["name"] = out["name"].fillna("").astype(str)
    out["tier"] = [assign_physical_tier(r.strategy, r.score) for r in out.itertuples(index=False)]
    out["net_ret"] = 0.0
    out["buy_price_val"] = np.nan
    out["is_adj_px"] = False
    out["is_untrig"] = True
    return out[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig"]]


def run_single_slot(
    pool_df: pd.DataFrame,
    prio_fn: Callable[[pd.DataFrame], np.ndarray],
    untrig_df: Optional[pd.DataFrame] = None,
    timing_mode: str = "naive",
) -> tuple[pd.DataFrame, list[dict]]:
    """
    Strictly causal single-slot rotation engine.
    timing_mode:
      - 'naive': triggered pool only (no untriggered waits)
      - 'reserve_all': untriggered higher-priority conditional orders reserve 09:25 slot up to cancel_hhmm (1030/1130)
      - 'confirmed_0925_first': confirmed 09:25 fills always beat unconfirmed intraday conditional orders (>925)
      - 's_tier_reserve_only': confirmed 09:25 fills OR S-tier conditional orders (3to4_S, high_S) precede A-tier conditional orders
    """
    use_ut = (untrig_df is not None and not untrig_df.empty and timing_mode in ("reserve_all", "s_tier_reserve_only"))
    df = pd.concat([pool_df, untrig_df], ignore_index=True) if use_ut else pool_df.copy()
    df["prio"] = prio_fn(df)
    df = df[df["prio"] < 999].copy()
    if df.empty:
        return pd.DataFrame(), []

    if timing_mode == "confirmed_0925_first":
        df["phase"] = np.where(df["buy_hhmm"] == 925, 0, 1)
    elif timing_mode == "s_tier_reserve_only":
        is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"])
        df["phase"] = np.where((df["buy_hhmm"] == 925) | is_s_cond, 0, 1)
    else:
        df["phase"] = 0

    srt = df.sort_values(
        ["buy_date", "phase", "prio", "score", "buy_hhmm", "code"],
        ascending=[True, True, True, False, True, True],
    ).reset_index(drop=True)

    # Index triggered 09:25 options per day to log real missed 09:25 opportunity cost on untriggered waits
    trig_0925_by_dt = {}
    for dt, grp in srt[(~srt["is_untrig"]) & (srt["buy_hhmm"] == 925)].groupby("buy_date"):
        trig_0925_by_dt[dt] = grp[["strategy", "tier", "code", "name", "score", "net_ret", "prio", "phase"]].to_dict("records")

    taken, waits = [], []
    cur_ed, cur_eh = "", 0
    for r in srt.itertuples(index=False):
        if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh):
            if r.is_untrig:
                skipped_0925 = [
                    x for x in trig_0925_by_dt.get(r.buy_date, [])
                    if (x["phase"], x["prio"]) > (r.phase, r.prio)
                ]
                waits.append({
                    "buy_date": r.buy_date,
                    "wait_strategy": r.strategy,
                    "wait_tier": r.tier,
                    "wait_code": r.code,
                    "wait_name": r.name,
                    "wait_score": round(float(r.score), 1),
                    "cancel_hhmm": int(r.exit_hhmm),
                    "missed_0925_candidates": skipped_0925,
                })
                cur_ed = r.exit_date
                cur_eh = int(r.exit_hhmm)
            else:
                taken.append(r._asdict())
                cur_ed = r.exit_date
                cur_eh = int(r.exit_hhmm)

    res = pd.DataFrame(taken)
    if not res.empty:
        assert (res["exit_date"] > res["buy_date"]).all(), "T+0 violation detected!"
        for i in range(1, len(res)):
            p, c = res.iloc[i - 1], res.iloc[i]
            assert (c["buy_date"], int(c["buy_hhmm"])) > (p["exit_date"], int(p["exit_hhmm"])), f"Slot overlap at {i}"
    return res, waits


def build_daily_mtm_series(df_tr: pd.DataFrame, cal_dts: list[str], dt_to_idx: dict, bar_lu: dict) -> tuple[np.ndarray, float]:
    T = len(cal_dts)
    day_mult = np.ones(T, dtype=float)
    if df_tr.empty:
        return np.zeros(T, dtype=float), 0.0
    for r in df_tr.itertuples(index=False):
        bi = dt_to_idx.get(r.buy_date)
        ei = dt_to_idx.get(r.exit_date)
        if bi is None:
            continue
        bb = bar_lu.get((r.code, r.buy_date))
        if r.is_adj_px and pd.notna(r.buy_price_val):
            b_adj = float(r.buy_price_val)
        elif (not r.is_adj_px) and pd.notna(r.buy_price_val) and bb is not None:
            b_adj = float(r.buy_price_val) * bb[4]
        elif bb is not None:
            b_adj = bb[1] * bb[4]
        else:
            b_adj = 1.0
        if b_adj <= 0:
            b_adj = 1.0
        prev_v, last_c = b_adj, b_adj
        end_loop = ei if (ei is not None and ei > bi) else T
        for t in range(bi, end_loop):
            bt = bar_lu.get((r.code, cal_dts[t]))
            cur_c = (bt[1] * bt[4]) if bt else last_c
            if cur_c <= 0:
                cur_c = last_c
            day_mult[t] *= (cur_c / prev_v)
            prev_v, last_c = cur_c, cur_c
        if ei is not None and ei > bi:
            day_mult[ei] *= (b_adj * (1.0 + float(r.net_ret))) / prev_v
    daily_r = day_mult - 1.0
    mtm_nav = float(np.prod(day_mult))
    tr_nav = float(np.prod(1.0 + df_tr["net_ret"].to_numpy(float)))
    return daily_r, abs(mtm_nav - tr_nav)


def get_csi_ret(sh300: dict, all_sh_dts: list[str], sdt: str, edt: str) -> float:
    prevs = [d for d in all_sh_dts if d < sdt]
    posts = [d for d in all_sh_dts if d <= edt]
    p0 = sh300[prevs[-1]] if prevs else sh300[all_sh_dts[0]]
    p1 = sh300[posts[-1]]
    return float((p1 / p0 - 1.0) * 100.0)


def calc_window_metrics(
    df_tr: pd.DataFrame,
    full_daily_r: np.ndarray,
    cal_dts: list[str],
    dt_to_idx: dict,
    sh300: dict,
    all_sh_dts: list[str],
    sdt: str,
    edt: str,
) -> dict:
    csi_pct = get_csi_ret(sh300, all_sh_dts, sdt, edt)
    sub = df_tr[(df_tr["buy_date"] >= sdt) & (df_tr["buy_date"] <= edt)] if not df_tr.empty else pd.DataFrame()
    win_idx = [dt_to_idx[d] for d in cal_dts if sdt <= d <= edt]
    dr = full_daily_r[win_idx] if win_idx else np.zeros(1)
    T = len(dr)

    mtm_nav = float(np.prod(1.0 + dr))
    cum_d = np.cumprod(1.0 + dr)
    pk_d = np.maximum.accumulate(np.insert(cum_d, 0, 1.0))[1:]
    daily_mdd = float(np.max((pk_d - cum_d) / pk_d) * 100.0) if T > 0 else 0.0
    sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (mtm_nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if (T > 0 and mtm_nav > 0) else -100.0
    calmar = (cagr / daily_mdd) if daily_mdd > 1e-6 else 0.0

    if sub.empty:
        return {
            "n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "nav": 1.0, "ret_pct": 0.0, "mtm_nav": round(mtm_nav, 4),
            "ex_top5_nav": 1.0, "daily_mdd_pct": round(daily_mdd, 2), "trade_mdd_pct": 0.0,
            "daily_sharpe": round(sharpe, 3), "daily_calmar": round(calmar, 2),
            "csi300_pct": round(csi_pct, 2), "excess_csi300_pp": round(-csi_pct, 2),
        }

    rets = sub["net_ret"].to_numpy(float)
    w, l = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    tr_nav = float(np.prod(1.0 + rets))
    ex5 = float(np.prod(1.0 + np.sort(rets)[:-5])) if len(rets) > 5 else 1.0
    cum_t = np.cumprod(1.0 + rets)
    pk_t = np.maximum.accumulate(np.insert(cum_t, 0, 1.0))[1:]
    trade_mdd = float(np.max((pk_t - cum_t) / pk_t) * 100.0)

    return {
        "n": int(len(rets)),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav": round(tr_nav, 4),
        "ret_pct": round((tr_nav - 1.0) * 100.0, 2),
        "mtm_nav": round(mtm_nav, 4),
        "ex_top5_nav": round(ex5, 4),
        "daily_mdd_pct": round(daily_mdd, 2),
        "trade_mdd_pct": round(trade_mdd, 2),
        "daily_sharpe": round(sharpe, 3),
        "daily_calmar": round(calmar, 2),
        "csi300_pct": round(csi_pct, 2),
        "excess_csi300_pp": round((tr_nav - 1.0) * 100.0 - csi_pct, 2),
    }


def compute_collision_map(pool_df: pd.DataFrame, dt_to_idx: dict, is_end: str) -> dict:
    """Comprehensive 6-strategy collision map, cross-day shadowing, and IS/OOS tier statistics."""
    df = pool_df.copy()
    df["hold_td"] = df["exit_date"].map(dt_to_idx) - df["buy_date"].map(dt_to_idx)
    df["hold_cd"] = (pd.to_datetime(df["exit_date"]) - pd.to_datetime(df["buy_date"])).dt.days

    by_dt_mult = df.groupby("buy_date")["strategy"].apply(list)
    mult_hist = by_dt_mult.apply(len).value_counts().sort_index().to_dict()

    # Exact pairwise same-day collisions & holding-period shadowing
    s_sets = {s: set(df[df["strategy"] == s]["buy_date"]) for s in STRAT_ORDER}
    s_dfs = {s: df[df["strategy"] == s] for s in STRAT_ORDER}
    sameday_mat = {s1: {} for s1 in STRAT_ORDER}
    shadow_mat = {s1: {} for s1 in STRAT_ORDER}
    for s1 in STRAT_ORDER:
        for s2 in STRAT_ORDER:
            if s1 == s2:
                sameday_mat[s1][s2] = 0
                shadow_mat[s1][s2] = 0
                continue
            sameday_mat[s1][s2] = len(s_sets[s1] & s_sets[s2])
            cnt = 0
            for r1 in s_dfs[s1].itertuples(index=False):
                for r2 in s_dfs[s2].itertuples(index=False):
                    if (r1.buy_date, int(r1.buy_hhmm)) <= (r2.buy_date, int(r2.buy_hhmm)) <= (r1.exit_date, int(r1.exit_hhmm)):
                        cnt += 1
            shadow_mat[s1][s2] = cnt

    multi_combos = {}
    for d, lst in by_dt_mult.items():
        if len(lst) >= 3:
            key = "+".join(sorted(lst))
            multi_combos[key] = multi_combos.get(key, 0) + 1

    # Physical tier stats across IS / OOS / FULL
    tier_order_canon = [
        "3to4_S(>=102)", "3to4_A(90-101)",
        "high_S(>=96)", "high_A(88-95)",
        "pry_S(>=175)", "pry_A(165-174)",
        "2to3_S(>=96)", "2to3_A(90-95)",
        "1to2_S(>=340)", "1to2_A(304.8-339.9)", "1to2_FB(295-304.7)",
        "20cm_S(>=82)", "20cm_A(76-81)",
    ]
    tier_profiles = {}
    for t in tier_order_canon:
        sub = df[df["tier"] == t]
        if sub.empty:
            tier_profiles[t] = {"IS": {"n": 0}, "OOS": {"n": 0}, "FULL": {"n": 0}}
            continue
        tp_w = {}
        for wlbl, m in [("IS", sub[sub["buy_date"] <= is_end]), ("OOS", sub[sub["buy_date"] > is_end]), ("FULL", sub)]:
            r = m["net_ret"].to_numpy(float)
            n = len(r)
            if n == 0:
                tp_w[wlbl] = {"n": 0}
                continue
            w, l = r[r > 0], r[r <= 0]
            plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else 99.0
            ht = float(m["hold_td"].mean())
            hc = float(m["hold_cd"].mean())
            mn = float(r.mean() * 100.0)
            sd = float(r.std(ddof=1)) if n > 1 else 0.0
            sr_t = float(r.mean() / sd) if sd > 1e-12 else 0.0
            tp_w[wlbl] = {
                "n": int(n),
                "wr_pct": round(float((r > 0).mean() * 100.0), 2),
                "mean_pct": round(mn, 2),
                "plr": round(plr, 2),
                "hold_trd_days": round(ht, 2),
                "hold_cal_days": round(hc, 2),
                "daily_eff_pct_per_td": round(mn / max(ht, 1.0), 2),
                "trade_sharpe": round(sr_t, 3),
                "solo_nav": round(float(np.prod(1.0 + r)), 3),
            }
        tier_profiles[t] = tp_w

    # 1to2 vs 20cm collision sub-analysis
    s12 = df[df["strategy"] == "1to2"].copy()
    d20_map = df[df["strategy"] == "20cm"].set_index("buy_date")["score"].to_dict()
    s12["c20_sc"] = s12["buy_date"].map(d20_map)
    s12["hit_grp"] = np.where(s12["c20_sc"].isna(), "no_20cm", np.where(s12["c20_sc"] >= 82.0, "hit_20cm_S82", "hit_20cm_A76_81"))
    duality_1to2 = {}
    for g, sub in s12.groupby("hit_grp"):
        duality_1to2[g] = {}
        for wlbl, m in [("IS", sub[sub["buy_date"] <= is_end]), ("OOS", sub[sub["buy_date"] > is_end]), ("FULL", sub)]:
            r = m["net_ret"].to_numpy(float)
            duality_1to2[g][wlbl] = {
                "n": int(len(r)),
                "wr_pct": round(float((r > 0).mean() * 100.0), 2) if len(r) else 0.0,
                "mean_pct": round(float(r.mean() * 100.0), 2) if len(r) else 0.0,
                "nav": round(float(np.prod(1.0 + r)), 4) if len(r) else 1.0,
            }

    return {
        "total_signals_5y": int(len(df)),
        "unique_signal_dates": int(len(by_dt_mult)),
        "multiplicity_distribution": {str(k): int(v) for k, v in mult_hist.items()},
        "multi_way_combos_ge3": multi_combos,
        "pairwise_same_day_matrix": sameday_mat,
        "pairwise_cross_day_shadow_matrix": shadow_mat,
        "tier_profiles_is_oos_full": tier_profiles,
        "duality_1to2_vs_20cm": duality_1to2,
    }


def fit_is_models(is_df: pd.DataFrame, cal_dts: list[str], dt_to_idx: dict, bar_lu: dict, is_end: str) -> dict:
    """Strictly fit Empirical Bayes models & Coordinate-Ascent ladders on IS data only."""
    d = is_df.copy()
    d["hold_td"] = np.maximum(1, d["exit_date"].map(dt_to_idx) - d["buy_date"].map(dt_to_idx))
    d["log_ret"] = np.log1p(d["net_ret"])

    grand_lr = float(d["log_ret"].mean())
    grand_ht = float(d["hold_td"].mean())
    strat_priors = {}
    for st, grp in d.groupby("strategy"):
        n_s = len(grp)
        strat_priors[st] = (
            float((grp["log_ret"].sum() + 5.0 * grand_lr) / (n_s + 5.0)),
            float((grp["hold_td"].sum() + 5.0 * grand_ht) / (n_s + 5.0)),
        )

    eb_table = {}
    for t, grp in d.groupby("tier"):
        st = grp["strategy"].iloc[0]
        p_lr, p_ht = strat_priors[st]
        n_t = len(grp)
        k_t = 10.0
        eb_lr = float((grp["log_ret"].sum() + k_t * p_lr) / (n_t + k_t))
        eb_ht = float((grp["hold_td"].sum() + k_t * p_ht) / (n_t + k_t))
        raw_lr = float(grp["log_ret"].mean())
        raw_ht = float(grp["hold_td"].mean())
        raw_mn = float(grp["net_ret"].mean())
        eb_table[t] = {
            "n_is": int(n_t),
            "raw_mean_pct": round(raw_mn * 100.0, 2),
            "raw_daily_eff_pct": round((raw_mn / raw_ht) * 100.0, 2),
            "eb_trade_log_ret_pct": round(eb_lr * 100.0, 2),
            "eb_daily_eff_pct": round((eb_lr / eb_ht) * 100.0, 2),
            "eb_lr_val": eb_lr,
            "eb_eff_val": eb_lr / eb_ht,
            "raw_mn_val": raw_mn,
            "raw_eff_val": raw_mn / raw_ht,
        }

    # Coordinate ascent on IS (starting from S2C split, excluding negative-IS 20cm_A)
    tiers_present = [t for t in eb_table if t != "20cm_A(76-81)"]
    s2c_order = [
        "3to4_S(>=102)", "3to4_A(90-101)", "high_S(>=96)", "high_A(88-95)",
        "pry_S(>=175)", "pry_A(165-174)", "2to3_S(>=96)", "2to3_A(90-95)",
        "1to2_S(>=340)", "1to2_A(304.8-339.9)", "1to2_FB(295-304.7)", "20cm_S(>=82)",
    ]
    init_ca = [t for t in s2c_order if t in tiers_present]
    is_dts = [dt for dt in cal_dts if dt <= is_end]
    is_idx = {dt: i for i, dt in enumerate(is_dts)}

    def eval_is_obj(order_list: list[str], metric: str) -> float:
        pm = {t: i + 1 for i, t in enumerate(order_list)}
        tr_s, _ = run_single_slot(d, lambda df_: df_["tier"].map(pm).fillna(999).to_numpy())
        if tr_s.empty:
            return -999.0
        if metric == "nav":
            return float(np.prod(1.0 + tr_s["net_ret"].to_numpy(float)))
        dr, _ = build_daily_mtm_series(tr_s, is_dts, is_idx, bar_lu)
        sd = float(np.std(dr, ddof=1))
        sr = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
        if metric == "sharpe":
            return sr
        cum = np.cumprod(1.0 + dr)
        pk = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
        mdd = float(np.max((pk - cum) / pk) * 100.0)
        cagr = (float(cum[-1]) ** (TRD_DAYS_YEAR / len(is_dts)) - 1.0) * 100.0
        return cagr / mdd if mdd > 1e-6 else 0.0

    def run_coord_ascent(start_ord: list[str], metric: str) -> tuple[list[str], list[list[str]]]:
        cur = list(start_ord)
        best_v = eval_is_obj(cur, metric)
        history = [list(cur)]
        for _ in range(15):
            best_cand = None
            for i in range(len(cur)):
                for j in range(i + 1, len(cur)):
                    cand = list(cur)
                    cand[i], cand[j] = cand[j], cand[i]
                    v = eval_is_obj(cand, metric)
                    if v > best_v + 1e-6:
                        best_v = v
                        best_cand = cand
            if best_cand is None:
                break
            cur = best_cand
            history.append(list(cur))
        return cur, history

    ca_nav, ca_nav_hist = run_coord_ascent(init_ca, "nav")
    ca_sr, ca_sr_hist = run_coord_ascent(init_ca, "sharpe")

    return {
        "eb_table": eb_table,
        "rank_raw_eff": [t for t, _ in sorted(eb_table.items(), key=lambda x: x[1]["raw_eff_val"], reverse=True) if t != "20cm_A(76-81)"],
        "rank_raw_mean": [t for t, _ in sorted(eb_table.items(), key=lambda x: x[1]["raw_mn_val"], reverse=True) if t != "20cm_A(76-81)"],
        "rank_eb_eff": [t for t, _ in sorted(eb_table.items(), key=lambda x: x[1]["eb_eff_val"], reverse=True) if t != "20cm_A(76-81)"],
        "rank_eb_lr": [t for t, _ in sorted(eb_table.items(), key=lambda x: x[1]["eb_lr_val"], reverse=True) if t != "20cm_A(76-81)"],
        "rank_eb_lr_with20A": [t for t, _ in sorted(eb_table.items(), key=lambda x: x[1]["eb_lr_val"], reverse=True)],
        "ca_nav": ca_nav,
        "ca_nav_hist": ca_nav_hist,
        "ca_sharpe": ca_sr,
        "ca_sharpe_hist": ca_sr_hist,
    }


def cscv_pbo_eval(daily_returns_dict: dict[str, np.ndarray], S_list=(8, 10)) -> dict:
    names = list(daily_returns_dict.keys())
    R = np.column_stack([daily_returns_dict[n] for n in names])
    out = {}
    i_s2c = names.index("C1_S2C_20cmS82_P6") if "C1_S2C_20cmS82_P6" in names else 0
    i_s3b = names.index("C2_S3B_20cmS82_P5") if "C2_S3B_20cmS82_P5" in names else 0

    for S in S_list:
        gs = len(R) // S
        gidx = [list(range(i * gs, (i + 1) * gs if i < S - 1 else len(R))) for i in range(S)]
        omegas, beat_s2c, beat_s3b = [], [], []
        win_cnt = {nm: 0 for nm in names}
        for te in itertools.combinations(range(S), S // 2):
            trg = [k for k in range(S) if k not in te]
            rt = R[[x for k in trg for x in gidx[k]]]
            re_ = R[[x for k in te for x in gidx[k]]]
            sdt, sde = rt.std(0, ddof=1), re_.std(0, ddof=1)
            st = np.divide(rt.mean(0), sdt, out=np.zeros_like(sdt), where=sdt > 1e-12)
            se = np.divide(re_.mean(0), sde, out=np.zeros_like(sde), where=sde > 1e-12)
            b = int(np.argmax(st))
            win_cnt[names[b]] += 1
            omegas.append(float(np.mean(se > se[b])))
            beat_s2c.append(bool(se[b] >= se[i_s2c]))
            beat_s3b.append(bool(se[b] >= se[i_s3b]))
        om_arr = np.array(omegas)
        out[f"S{S}"] = {
            "combinations": len(omegas),
            "pbo_pct": round(float(np.mean(om_arr > 0.50) * 100.0), 2),
            "mean_omega": round(float(np.mean(om_arr)), 4),
            "is_winner_beat_s2c_oos_pct": round(float(np.mean(beat_s2c) * 100.0), 2),
            "is_winner_beat_s3b_oos_pct": round(float(np.mean(beat_s3b) * 100.0), 2),
            "is_winners": {k: v for k, v in win_cnt.items() if v > 0},
        }
    return out


def purged_5fold_cv(
    pool_df: pd.DataFrame,
    untrig_df: pd.DataFrame,
    cal_dts: list[str],
    dt_to_idx: dict,
    bar_lu: dict,
) -> dict:
    """5-Fold Purged & Embargoed CV where IS-fitted paradigms re-fit inside each 4-fold purged training set."""
    df = pool_df.copy()
    df["b_idx"] = df["buy_date"].map(dt_to_idx)
    df["e_idx"] = df["exit_date"].map(dt_to_idx)
    T = len(cal_dts)
    step = T // 5
    folds = [(k * step, (k + 1) * step - 1 if k < 4 else T - 1) for k in range(5)]

    s2c_m = {"3to4_S(>=102)":1,"3to4_A(90-101)":1,"high_S(>=96)":2,"high_A(88-95)":2,"pry_S(>=175)":3,"pry_A(165-174)":3,"2to3_S(>=96)":4,"2to3_A(90-95)":4,"1to2_S(>=340)":5,"1to2_A(304.8-339.9)":5,"1to2_FB(295-304.7)":5,"20cm_S(>=82)":6,"20cm_A(76-81)":999}
    s3b_m = {"3to4_S(>=102)":1,"3to4_A(90-101)":1,"high_S(>=96)":2,"high_A(88-95)":2,"pry_S(>=175)":3,"pry_A(165-174)":3,"2to3_S(>=96)":4,"2to3_A(90-95)":4,"20cm_S(>=82)":5,"1to2_S(>=340)":6,"1to2_A(304.8-339.9)":6,"1to2_FB(295-304.7)":6,"20cm_A(76-81)":999}
    sg1_m = {"3to4_S(>=102)":1,"3to4_A(90-101)":1,"high_S(>=96)":2,"high_A(88-95)":2,"pry_S(>=175)":3,"pry_A(165-174)":3,"2to3_S(>=96)":4,"2to3_A(90-95)":4,"1to2_S(>=340)":5,"20cm_S(>=82)":6,"1to2_A(304.8-339.9)":7,"1to2_FB(295-304.7)":8,"20cm_A(76-81)":999}

    methods = [
        "C1_S2C", "C2_S3B", "P1C_1to2Split",
        "P1A_RawTradeMean_Refit", "P2A_EB_DailyEff_Refit", "P2B_EB_TradeRet_Refit",
        "P3_S2C_STierReserve",
    ]
    res_by_m = {m: [] for m in methods}

    for fi, (fs, fe) in enumerate(folds, 1):
        tr_mask = (df["e_idx"] < fs) | (df["b_idx"] > fe + EMBARGO_DAYS)
        te_mask = (df["b_idx"] >= fs) & (df["b_idx"] <= fe)
        tr_df = df[tr_mask].copy()
        te_df = df[te_mask].copy()
        ut_te = untrig_df[untrig_df["buy_date"].between(cal_dts[fs], cal_dts[fe])].copy() if (untrig_df is not None and not untrig_df.empty) else pd.DataFrame()

        # Fit EB & Raw on tr_df
        tr_df["hold_td"] = np.maximum(1, tr_df["e_idx"] - tr_df["b_idx"])
        tr_df["log_ret"] = np.log1p(tr_df["net_ret"])
        gl = float(tr_df["log_ret"].mean())
        gh = float(tr_df["hold_td"].mean())
        sp_l = {st: (g["log_ret"].sum() + 5.0 * gl) / (len(g) + 5.0) for st, g in tr_df.groupby("strategy")}
        sp_h = {st: (g["hold_td"].sum() + 5.0 * gh) / (len(g) + 5.0) for st, g in tr_df.groupby("strategy")}
        eb_l = {t: (g["log_ret"].sum() + 10.0 * sp_l[g["strategy"].iloc[0]]) / (len(g) + 10.0) for t, g in tr_df.groupby("tier")}
        eb_h = {t: (g["hold_td"].sum() + 10.0 * sp_h[g["strategy"].iloc[0]]) / (len(g) + 10.0) for t, g in tr_df.groupby("tier")}

        pm_raw = {t: i + 1 for i, (t, _) in enumerate(sorted(tr_df.groupby("tier"), key=lambda x: x[1]["net_ret"].mean(), reverse=True)) if t != "20cm_A(76-81)"}
        pm_eb_eff = {t: i + 1 for i, (t, _) in enumerate(sorted({t: eb_l[t] / eb_h[t] for t in eb_l}.items(), key=lambda x: x[1], reverse=True)) if t != "20cm_A(76-81)"}
        pm_eb_lr = {t: i + 1 for i, (t, _) in enumerate(sorted(eb_l.items(), key=lambda x: x[1], reverse=True)) if t != "20cm_A(76-81)"}

        specs = [
            ("C1_S2C", s2c_m, "naive"),
            ("C2_S3B", s3b_m, "naive"),
            ("P1C_1to2Split", sg1_m, "naive"),
            ("P1A_RawTradeMean_Refit", pm_raw, "naive"),
            ("P2A_EB_DailyEff_Refit", pm_eb_eff, "naive"),
            ("P2B_EB_TradeRet_Refit", pm_eb_lr, "naive"),
            ("P3_S2C_STierReserve", s2c_m, "s_tier_reserve_only"),
        ]
        for m_nm, pm, tmode in specs:
            tr_f, _ = run_single_slot(te_df, lambda d_, _pm=pm: d_["tier"].map(_pm).fillna(999).to_numpy(), untrig_df=ut_te, timing_mode=tmode)
            dr_full, _ = build_daily_mtm_series(tr_f, cal_dts, dt_to_idx, bar_lu)
            dr_f = dr_full[fs: fe + 1]
            nav_f = float(np.prod(1.0 + tr_f["net_ret"].to_numpy(float))) if not tr_f.empty else 1.0
            sd_f = float(np.std(dr_f, ddof=1)) if len(dr_f) > 1 else 0.0
            sr_f = float(np.mean(dr_f) / sd_f * math.sqrt(TRD_DAYS_YEAR)) if sd_f > 1e-12 else 0.0
            res_by_m[m_nm].append({
                "fold": fi,
                "window": f"{cal_dts[fs]}~{cal_dts[fe]}",
                "n": int(len(tr_f)),
                "nav": round(nav_f, 3),
                "sharpe": round(sr_f, 3),
            })

    summary = {}
    for m_nm, flist in res_by_m.items():
        navs = [x["nav"] for x in flist]
        srs = [x["sharpe"] for x in flist]
        summary[m_nm] = {
            "mean_fold_sharpe": round(float(np.mean(srs)), 3),
            "prod_5fold_nav": round(float(np.prod(navs)), 2),
            "min_fold_nav": round(float(min(navs)), 3),
            "folds": flist,
        }
    return summary


def evaluate_all_schemes(
    pool_df: pd.DataFrame,
    untrig_df: pd.DataFrame,
    cal_dts: list[str],
    dt_to_idx: dict,
    bar_lu: dict,
    sh300: dict,
    all_sh_dts: list[str],
    start_dt: str,
    end_dt: str,
    is_end: str,
    oos_start: str,
    y26_start: str,
) -> dict:
    is_df = pool_df[pool_df["buy_date"] <= is_end].copy()
    is_fit = fit_is_models(is_df, cal_dts, dt_to_idx, bar_lu, is_end)

    d20_any_dts = set(pool_df[pool_df["strategy"] == "20cm"]["buy_date"])
    d20_a_dts = set(pool_df[pool_df["tier"] == "20cm_A(76-81)"]["buy_date"])

    def map_fn(pmap: dict) -> Callable[[pd.DataFrame], np.ndarray]:
        return lambda d: d["tier"].map(pmap).fillna(999).to_numpy()

    s_5strat = {"3to4_S(>=102)":1,"3to4_A(90-101)":1,"high_S(>=96)":2,"high_A(88-95)":2,"pry_S(>=175)":3,"pry_A(165-174)":3,"2to3_S(>=96)":4,"2to3_A(90-95)":4,"1to2_S(>=340)":5,"1to2_A(304.8-339.9)":5,"1to2_FB(295-304.7)":5,"20cm_S(>=82)":999,"20cm_A(76-81)":999}
    s2c = {"3to4_S(>=102)":1,"3to4_A(90-101)":1,"high_S(>=96)":2,"high_A(88-95)":2,"pry_S(>=175)":3,"pry_A(165-174)":3,"2to3_S(>=96)":4,"2to3_A(90-95)":4,"1to2_S(>=340)":5,"1to2_A(304.8-339.9)":5,"1to2_FB(295-304.7)":5,"20cm_S(>=82)":6,"20cm_A(76-81)":999}
    s3b = {"3to4_S(>=102)":1,"3to4_A(90-101)":1,"high_S(>=96)":2,"high_A(88-95)":2,"pry_S(>=175)":3,"pry_A(165-174)":3,"2to3_S(>=96)":4,"2to3_A(90-95)":4,"20cm_S(>=82)":5,"1to2_S(>=340)":6,"1to2_A(304.8-339.9)":6,"1to2_FB(295-304.7)":6,"20cm_A(76-81)":999}
    s2b_a76 = {**s2c, "20cm_A(76-81)": 7}
    s3_a76 = {**s3b, "20cm_A(76-81)": 7}
    sg1_12split = {"3to4_S(>=102)":1,"3to4_A(90-101)":1,"high_S(>=96)":2,"high_A(88-95)":2,"pry_S(>=175)":3,"pry_A(165-174)":3,"2to3_S(>=96)":4,"2to3_A(90-95)":4,"1to2_S(>=340)":5,"20cm_S(>=82)":6,"1to2_A(304.8-339.9)":7,"1to2_FB(295-304.7)":8,"20cm_A(76-81)":999}

    def list_to_map(ord_list: list[str]) -> dict:
        return {t: i + 1 for i, t in enumerate(ord_list)}

    p1a_eff_m = list_to_map(is_fit["rank_raw_eff"])
    p1a_mn_m = list_to_map(is_fit["rank_raw_mean"])
    p1b_nav_m = list_to_map(is_fit["ca_nav"])
    p1b_sr_m = list_to_map(is_fit["ca_sharpe"])
    p2a_eb_eff_m = list_to_map(is_fit["rank_eb_eff"])
    p2b_eb_lr_m = list_to_map(is_fit["rank_eb_lr"])
    p2b_eb_lr_a_m = list_to_map(is_fit["rank_eb_lr_with20A"])

    def fn_s2c_drop12_20a(d: pd.DataFrame) -> np.ndarray:
        p = d["tier"].map(s2c).fillna(999).to_numpy()
        return np.where((d["strategy"] == "1to2") & d["buy_date"].isin(d20_a_dts), 999, p)

    def fn_p2b_hit20_deg(d: pd.DataFrame) -> np.ndarray:
        p = d["tier"].map(p2b_eb_lr_m).fillna(999).to_numpy()
        return np.where((d["strategy"] == "1to2") & d["buy_date"].isin(d20_any_dts), 50, p)

    schemes_spec = [
        ("C0_V191_5Strat", "原五策略基线（无20cm）", map_fn(s_5strat), "naive"),
        ("C1_S2C_20cmS82_P6", "粗排 S2C（20cm_S82 第6顺位）", map_fn(s2c), "naive"),
        ("C2_S3B_20cmS82_P5", "粗排 S3B（20cm_S82 第5顺位压一进二）", map_fn(s3b), "naive"),
        ("C3_S2B_20cmA76_P6", "粗排 S2B（含20cm_A76 第6/7顺位）", map_fn(s2b_a76), "naive"),
        ("C4_S3_20cmA76_P5", "粗排 S3（含20cm_A76 压一进二）", map_fn(s3_a76), "naive"),
        ("P1A_RawDailyEff", "范式1A：IS日均资金效率E[r]/hold_td直排（剔20cm_A）", map_fn(p1a_eff_m), "naive"),
        ("P1A_RawTradeMean", "范式1A：IS笔均期望收益直排（剔20cm_A）", map_fn(p1a_mn_m), "naive"),
        ("P1B_CoordAscent_NAV", "范式1B：IS坐标上升优化NAV（过拟合对照）", map_fn(p1b_nav_m), "naive"),
        ("P1B_CoordAscent_Sharpe", "范式1B：IS坐标上升优化Sharpe（过拟合对照）", map_fn(p1b_sr_m), "naive"),
        ("P1C_Surgical_1to2Split", "范式1C：微创分档（1to2>=340 > 20cm_S82 > 1to2<340）", map_fn(sg1_12split), "naive"),
        ("P1C_S2C_Drop12on20A", "范式1C：S2C + 撞20cm_A76日放弃1to2", fn_s2c_drop12_20a, "naive"),
        ("P2A_EB_DailyEff", "范式2A：IS经验贝叶斯日均效率打分（剔20cm_A）", map_fn(p2a_eb_eff_m), "naive"),
        ("P2B_EB_TradeRet", "范式2B：IS经验贝叶斯单笔对数期望打分（剔20cm_A）", map_fn(p2b_eb_lr_m), "naive"),
        ("P2B_EB_TradeRet_withA", "范式2B：IS经验贝叶斯单笔期望打分（含20cm_A垫底）", map_fn(p2b_eb_lr_a_m), "naive"),
        ("P2C_EB_TradeRet_Hit20Deg", "范式2C：P2B + 1to2撞20cm>=76降级", fn_p2b_hit20_deg, "naive"),
        ("P3_S2C_ReserveAll", "范式3-模式①：S2C 09:25信号即占位（含72次未触发条件单）", map_fn(s2c), "reserve_all"),
        ("P3_S3B_ReserveAll", "范式3-模式①：S3B 09:25信号即占位（含未触发条件单）", map_fn(s3b), "reserve_all"),
        ("P3_P2B_ReserveAll", "范式3-模式①：P2B经验贝叶斯 09:25信号即占位", map_fn(p2b_eb_lr_m), "reserve_all"),
        ("P3_S2C_Confirmed0925First", "范式3-模式②A：09:25确定买全优于盘中条件单", map_fn(s2c), "confirmed_0925_first"),
        ("P3_S2C_STierReserveOnly", "范式3-模式②B：仅3to4_S/high_S占位，A档条件单让位09:25确定买", map_fn(s2c), "s_tier_reserve_only"),
        ("P3_1to2Split_STierRes", "范式3-模式②B：1to2分档 + 仅S档条件单占位", map_fn(sg1_12split), "s_tier_reserve_only"),
    ]

    wins = [("FULL", start_dt, end_dt), ("IS", start_dt, is_end), ("OOS", oos_start, end_dt), ("Y2026", y26_start, end_dt)]
    results = {}
    daily_r_map = {}

    for sid, desc, pfn, tmode in schemes_spec:
        tr_df, waits = run_single_slot(pool_df, pfn, untrig_df=untrig_df, timing_mode=tmode)
        dr_full, nav_diff = build_daily_mtm_series(tr_df, cal_dts, dt_to_idx, bar_lu)
        assert nav_diff < 1e-3, f"MTM nav reconciliation mismatch for {sid}: {nav_diff}"
        daily_r_map[sid] = dr_full

        w_metrics = {
            wlbl: calc_window_metrics(tr_df, dr_full, cal_dts, dt_to_idx, sh300, all_sh_dts, sdt, edt)
            for wlbl, sdt, edt in wins
        }

        missed_all = [x for w in waits for x in w["missed_0925_candidates"]]
        missed_rets = np.array([x["net_ret"] for x in missed_all], dtype=float)
        results[sid] = {
            "desc": desc,
            "timing_mode": tmode,
            "metrics": w_metrics,
            "by_strategy": tr_df["strategy"].value_counts().to_dict() if not tr_df.empty else {},
            "by_tier": tr_df["tier"].value_counts().to_dict() if not tr_df.empty else {},
            "untriggered_waits_summary": {
                "wait_events_count": len(waits),
                "missed_0925_trades_count": len(missed_all),
                "missed_0925_wr_pct": round(float((missed_rets > 0).mean() * 100.0), 2) if len(missed_rets) else 0.0,
                "missed_0925_mean_pct": round(float(missed_rets.mean() * 100.0), 2) if len(missed_rets) else 0.0,
                "missed_0925_compounded_nav": round(float(np.prod(1.0 + missed_rets)), 4) if len(missed_rets) else 1.0,
                "missed_0925_examples": [
                    {
                        "buy_date": w["buy_date"],
                        "waited_for": f"{w['wait_strategy']}({w['wait_tier']},score={w['wait_score']})",
                        "missed_0925": [
                            f"{m['strategy']}({m['tier']},{m['code']}{m['name']},ret={m['net_ret']*100:+.2f}%)"
                            for m in w["missed_0925_candidates"]
                        ],
                    }
                    for w in waits if w["missed_0925_candidates"]
                ],
            },
        }

    # CSCV PBO on wide paradigm grid vs overfit-stress grid vs surgical grid
    wide_keys = [
        "C1_S2C_20cmS82_P6", "C2_S3B_20cmS82_P5", "C3_S2B_20cmA76_P6", "C4_S3_20cmA76_P5",
        "P1A_RawDailyEff", "P1A_RawTradeMean", "P1B_CoordAscent_NAV", "P1B_CoordAscent_Sharpe",
        "P2A_EB_DailyEff", "P2B_EB_TradeRet", "P2B_EB_TradeRet_withA",
        "P1C_Surgical_1to2Split", "P3_S2C_Confirmed0925First", "P3_S2C_STierReserveOnly",
    ]
    ca_stress_keys = ["C1_S2C_20cmS82_P6", "C2_S3B_20cmS82_P5", "P1B_CoordAscent_NAV", "P1B_CoordAscent_Sharpe", "P1A_RawDailyEff"]
    surg_keys = ["C1_S2C_20cmS82_P6", "C2_S3B_20cmS82_P5", "P1C_Surgical_1to2Split", "P1C_S2C_Drop12on20A", "P2B_EB_TradeRet", "P3_S2C_STierReserveOnly"]

    cscv_all = cscv_pbo_eval({k: daily_r_map[k] for k in wide_keys})
    cscv_ca = cscv_pbo_eval({k: daily_r_map[k] for k in ca_stress_keys})
    cscv_surg = cscv_pbo_eval({k: daily_r_map[k] for k in surg_keys})
    purged_cv = purged_5fold_cv(pool_df, untrig_df, cal_dts, dt_to_idx, bar_lu)

    return {
        "is_fitted_models": is_fit,
        "schemes": results,
        "overfitting_audits": {
            "cscv_wide_14_paradigms": cscv_all,
            "cscv_coord_ascent_stress": cscv_ca,
            "cscv_low_dof_surgical": cscv_surg,
            "purged_5fold_refit_cv": purged_cv,
        },
    }


def load_full_top1_cross_check(start_dt: str, end_dt: str) -> pd.DataFrame:
    """Optional cross-check using unfiltered daily-top1 pools (non-self-1-slot-filtered)."""
    def _l(st, fn, cond, tie_cols, tie_asc, sc_col="base_score", c6="code"):
        d = pd.read_csv(fn)
        d["code"] = d[c6].astype(str).str.zfill(6)
        d["buy_date"] = d["buy_date"].astype(str).str[:10]
        d["exit_date"] = d["exit_date"].astype(str).str[:10]
        d = d[cond(d) & d["buy_date"].between(start_dt, end_dt)].copy()
        d["score"] = pd.to_numeric(d[sc_col], errors="coerce").astype(float)
        d["strategy"] = st
        if "buy_hhmm" not in d.columns:
            d["buy_hhmm"] = 925
        if "exit_hhmm" not in d.columns:
            d["exit_hhmm"] = 1500
        d["buy_price_val"] = pd.to_numeric(d["buy_px"] if "buy_px" in d.columns else d["buy_price"], errors="coerce").astype(float)
        d["is_adj_px"] = ("buy_px" in d.columns) and ("buy_price" not in d.columns)
        d = d.sort_values(["buy_date"] + tie_cols, ascending=[True] + tie_asc).groupby("buy_date", as_index=False).first()
        d["tier"] = [assign_physical_tier(st, sc) for sc in d["score"]]
        d["is_untrig"] = False
        return d[["buy_date","buy_hhmm","exit_date","exit_hhmm","code","name","strategy","tier","score","net_ret","buy_price_val","is_adj_px","is_untrig"]]

    p34 = _l("3to4", f"{MW1_DIR}/pool_3to4_full_clean.csv", lambda d: d["base_score"] >= 90, ["base_score", "prio_tie", "code"], [False, False, True])
    phd = _l("high", f"{MW1_DIR}/pool_high_full_clean.csv", lambda d: d["base_score"] >= 88, ["base_score", "code"], [False, True])
    ppr = load_strategy_csv("pry", f"{PC_DIR}/ledger_pry_v21_top1_clean.csv", start_dt, end_dt)
    ppr = ppr.sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    p23 = _l("2to3", f"{MW2_DIR}/pool_2to3_full_clean.csv", lambda d: d["base_score"] >= 90, ["base_score", "open_pct", "code"], [False, True, True])
    p12 = _l("1to2", f"{MW3_DIR}/pool_1to2_full_clean.csv", lambda d: d["is_v19_day_top1"], ["base_score", "code"], [False, True])
    p20 = pd.read_csv(f"{V11_DIR}/final_v11_all_scored_signals.csv")
    p20 = p20[(p20["score"] >= 76) & p20["buy_date"].between(start_dt, end_dt)].copy()
    p20["code"] = p20["c6"].astype(str).str.zfill(6)
    p20["buy_hhmm"] = 925
    p20["exit_hhmm"] = np.where(p20["exit_reason"].str.contains("open|gap|tp|dev93"), 1030, 1500)
    p20["strategy"] = "20cm"
    p20["buy_price_val"] = pd.to_numeric(p20["buy_px"], errors="coerce").astype(float)
    p20["is_adj_px"] = True
    p20 = p20.sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    p20["tier"] = [assign_physical_tier("20cm", sc) for sc in p20["score"]]
    p20["is_untrig"] = False
    p20 = p20[["buy_date","buy_hhmm","exit_date","exit_hhmm","code","name","strategy","tier","score","net_ret","buy_price_val","is_adj_px","is_untrig"]]
    return pd.concat([p34, phd, ppr, p23, p12, p20], ignore_index=True)


def main():
    parser = argparse.ArgumentParser(description="Six-Strategy Fine-Tier Collision Priority Optimizer & Blind OOS Validator")
    parser.add_argument("--csv-3to4", default=DEFAULT_CSVS["3to4"])
    parser.add_argument("--csv-high", default=DEFAULT_CSVS["high"])
    parser.add_argument("--csv-pry", default=DEFAULT_CSVS["pry"])
    parser.add_argument("--csv-2to3", default=DEFAULT_CSVS["2to3"])
    parser.add_argument("--csv-1to2", default=DEFAULT_CSVS["1to2"])
    parser.add_argument("--csv-20cm", default=DEFAULT_CSVS["20cm"])
    parser.add_argument("--start-date", default="2021-11-16")
    parser.add_argument("--end-date", default="2026-11-16")
    parser.add_argument("--is-end", default="2024-08-31")
    parser.add_argument("--oos-start", default="2024-09-01")
    parser.add_argument("--y26-start", default="2026-01-01")
    parser.add_argument("--skip-untriggered", action="store_true")
    parser.add_argument("--skip-top1-crosscheck", action="store_true")
    parser.add_argument("--out-json", default=OUT_DEFAULT)
    args = parser.parse_args()

    t0 = time.time()
    csv_map = {
        "3to4": args.csv_3to4, "high": args.csv_high, "pry": args.csv_pry,
        "2to3": args.csv_2to3, "1to2": args.csv_1to2, "20cm": args.csv_20cm,
    }
    pool6 = pd.concat([load_strategy_csv(st, p, args.start_date, args.end_date) for st, p in csv_map.items()], ignore_index=True)

    untrig_df = pd.DataFrame()
    if not args.skip_untriggered:
        untrig_df = build_untriggered_baseline_pool(pool6, args.start_date, args.end_date)

    top1_df = pd.DataFrame()
    if not args.skip_top1_crosscheck and os.path.exists(f"{MW1_DIR}/pool_3to4_full_clean.csv"):
        top1_df = load_full_top1_cross_check(args.start_date, args.end_date)

    all_codes = set(pool6["code"].unique())
    if not top1_df.empty:
        all_codes.update(top1_df["code"].unique())

    sh300, bar_lu, all_sh_dts = load_daily_bars(all_codes)
    cal_dts = [d for d in all_sh_dts if args.start_date <= d <= args.end_date]
    dt_to_idx = {d: i for i, d in enumerate(cal_dts)}

    cmap = compute_collision_map(pool6, dt_to_idx, args.is_end)
    primary_eval = evaluate_all_schemes(
        pool6, untrig_df, cal_dts, dt_to_idx, bar_lu, sh300, all_sh_dts,
        args.start_date, args.end_date, args.is_end, args.oos_start, args.y26_start,
    )

    cross_check_eval = {}
    if not top1_df.empty:
        untrig_top1 = build_untriggered_baseline_pool(top1_df, args.start_date, args.end_date) if not args.skip_untriggered else pd.DataFrame()
        cross_check_eval = evaluate_all_schemes(
            top1_df, untrig_top1, cal_dts, dt_to_idx, bar_lu, sh300, all_sh_dts,
            args.start_date, args.end_date, args.is_end, args.oos_start, args.y26_start,
        )

    out_obj = sanitize_json({
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 2),
            "d12_yfinance_imported": "yfinance" in sys.modules,
            "windows": {
                "FULL": f"{args.start_date} ~ {args.end_date}",
                "IS": f"{args.start_date} ~ {args.is_end}",
                "OOS": f"{args.oos_start} ~ {args.end_date}",
                "Y2026": f"{args.y26_start} ~ {args.end_date}",
            },
            "csi300_returns_pct": {
                "FULL": round(get_csi_ret(sh300, all_sh_dts, args.start_date, args.end_date), 2),
                "IS": round(get_csi_ret(sh300, all_sh_dts, args.start_date, args.is_end), 2),
                "OOS": round(get_csi_ret(sh300, all_sh_dts, args.oos_start, args.end_date), 2),
                "Y2026": round(get_csi_ret(sh300, all_sh_dts, args.y26_start, args.end_date), 2),
            },
            "input_csvs": csv_map,
            "untriggered_conditional_counts": untrig_df["strategy"].value_counts().to_dict() if not untrig_df.empty else {},
        },
        "collision_map": cmap,
        "primary_exact_6csv": primary_eval,
        "crosscheck_full_daily_top1": cross_check_eval,
    })

    os.makedirs(os.path.dirname(os.path.abspath(args.out_json)), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out_obj, f, ensure_ascii=False, indent=2)

    print(f"[DONE in {time.time() - t0:.2f}s] Saved -> {args.out_json}")
    print("\n=== PRIMARY EXACT-6-CSV SUMMARY (Zero cap10m) ===")
    for sid, v in out_obj["primary_exact_6csv"]["schemes"].items():
        m_f, m_i, m_o, m_y = v["metrics"]["FULL"], v["metrics"]["IS"], v["metrics"]["OOS"], v["metrics"]["Y2026"]
        print(f"  {sid:26s} | n={m_f['n']:3d} WR={m_f['wr_pct']:5.1f}% PLR={m_f['plr']:4.2f} FULL={m_f['nav']:11,.1f}x Ex5={m_f['ex_top5_nav']:9,.1f}x MDD={m_f['daily_mdd_pct']:5.2f}% SR={m_f['daily_sharpe']:5.3f} Cal={m_f['daily_calmar']:5.2f} | IS={m_i['nav']:8,.1f}x | OOS={m_o['nav']:7,.1f}x(WR={m_o['wr_pct']:4.1f}%,Ex5={m_o['ex_top5_nav']:5,.1f}x,SR={m_o['daily_sharpe']:4.2f},Cal={m_o['daily_calmar']:5.1f}) | Y26={m_y['nav']:5.2f}x")


if __name__ == "__main__":
    main()
