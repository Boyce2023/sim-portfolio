#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-6 Common Loader, Exact Float64 Parity Context, Multi-Slot MTM Simulator & Anti-Overfit Evaluator.
Strictly read-only on wave1_base/ and production files. Zero yfinance (D12).
"""
import json
import math
import os
import sys
from collections import defaultdict
from typing import Callable, Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1_DIR = f"{RD035_DIR}/wave1_base"
RD028_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
OUT_DIR = f"{RD035_DIR}/wave2a/w2a6_portfolio_priority_and_slots"
os.makedirs(OUT_DIR, exist_ok=True)

for p in (WAVE1_DIR, RD028_DIR, PARTC_V20):
    if p not in sys.path:
        sys.path.insert(0, p)

import _wf_sim_and_metrics as wfm
import _wf_v20_patch as wfp
import step4_mod_rules_and_sim as m1
import tier_priority_engine as tpe

TRD_DAYS_YEAR = 242.0
STRAT_ORDER = ["3to4", "high", "pry", "2to3", "1to2", "20cm"]

CANON_S2C_TIER_MAP = {
    "3to4_S(>=102)": 1, "3to4_A(90-101)": 1,
    "high_S(>=96)": 2, "high_A(88-95)": 2,
    "pry_S(>=175)": 3, "pry_A(165-174)": 3,
    "2to3_S(>=96)": 4, "2to3_A(90-95)": 4,
    "1to2_S(>=340)": 5, "1to2_A(304.8-339.9)": 5, "1to2_FB(295-304.7)": 5,
    "20cm_S(>=82)": 6, "20cm_A(76-81)": 999,
}

CANON_S2C_STRAT_PRIO = {"3to4": 1, "high": 2, "pry": 3, "2to3": 4, "1to2": 5, "20cm": 6}


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


def build_kpl_pit_theme_map(cal_5y: list[str], end_dt: str = "2026-11-16") -> dict[tuple[str, str], str]:
    """
    For each (stock_code, buy_date), return the most recent KPL plate observed strictly BEFORE buy_date
    (within trailing 10 trading days), ensuring zero lookahead.
    """
    kpl_path = f"{SIM}/data/kpl_plates_5y_2021_2026_complete.jsonl"
    if not os.path.exists(kpl_path):
        return {}
    by_dt_stock = defaultdict(list)
    with open(kpl_path, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            d = json.loads(ln)
            dt = str(d.get("date", ""))[:10]
            if not dt or dt > end_dt:
                continue
            for p in d.get("plates", []):
                pname = str(p.get("plate", "")).strip()
                if not pname:
                    continue
                for st in p.get("stocks", []):
                    c6 = str(st[0]).zfill(6)
                    by_dt_stock[c6].append((dt, pname))
    for c6 in by_dt_stock:
        by_dt_stock[c6].sort(key=lambda x: x[0])
    return by_dt_stock


def lookup_kpl_plate_t1(kpl_by_c6: dict, code: str, buy_date: str, max_gap_days: int = 14) -> str:
    arr = kpl_by_c6.get(str(code).zfill(6))
    if not arr:
        return ""
    # Find latest entry with dt < buy_date
    best_dt, best_p = "", ""
    for dt, pname in arr:
        if dt < buy_date:
            best_dt, best_p = dt, pname
        else:
            break
    if not best_dt:
        return ""
    # Check calendar gap
    gap = (pd.Timestamp(buy_date) - pd.Timestamp(best_dt)).days
    return best_p if gap <= max_gap_days else ""


def load_w2a6_context() -> dict:
    """
    Load exact float64 pools, bars, 5Y calendar, benchmark, master PIT matrix (4183x604),
    and verify 100% V20.0 baseline parity (278 trades, 69,134,091.51x).
    """
    v20_ctx = wfp.load_v20_reference_context(WAVE1_DIR)
    master = pd.read_parquet(f"{WAVE1_DIR}/pools_6strat_master_newfactors_pit.parquet")
    master["buy_date"] = master["buy_date"].astype(str).str[:10]
    master["exit_date"] = master["exit_date"].astype(str).str[:10]
    master["code"] = master["code"].astype(str).str.zfill(6)

    with open(f"{WAVE1_DIR}/wave1a_factor_catalog_and_pit_audit.json", encoding="utf-8") as f:
        catalog = json.load(f)

    codes = set(master["code"].unique())
    sh300, all_sh_dts, cal_full, cal_5y, bar_lu = m1.load_calendars_and_bars(codes)
    pools = m1.load_pools_oldhot(cal_full, cal_5y, bar_lu)
    untrig_base = m1.load_untrig_with_oldhot()

    # Exact parity check against v20_baseline_ledger_278.parquet
    tr_base, waits_base = m1.run_combined_v20(pools, untrig_base, {})
    v20_ref = v20_ctx["v20_ledger"]
    assert len(tr_base) == len(v20_ref) == 278, f"Parity len fail: {len(tr_base)}"
    assert list(zip(tr_base["buy_date"], tr_base["code"], tr_base["strategy"])) == list(
        zip(v20_ref["buy_date"], v20_ref["code"], v20_ref["strategy"])
    ), "Parity trade sequence mismatch"
    max_ret_diff = float(np.max(np.abs(tr_base["net_ret"].to_numpy(float) - v20_ref["net_ret"].to_numpy(float))))
    nav_base = float(np.prod(1.0 + tr_base["net_ret"].to_numpy(float)))
    assert max_ret_diff < 1e-9, f"Parity ret diff={max_ret_diff}"
    assert abs(nav_base - 69134091.5067) < 1e-3, f"Parity nav={nav_base}"
    assert len(waits_base) == 41, f"Parity waits={len(waits_base)}"

    # Build float64 full master pool with MTM_5Y segments + KPL T-1 plate + CSRC ind
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    kpl_by_c6 = build_kpl_pit_theme_map(cal_5y)

    # Map float64 net_ret, mtm_5y, buy_price_val, is_adj_px, v51_cb_loss from pools[st]
    f64_rows = {}
    for st, df_st in pools.items():
        for r in df_st.itertuples(index=False):
            key = (st, str(r.buy_date)[:10], str(r.code).zfill(6))
            f64_rows[key] = {
                "net_ret_f64": float(r.net_ret),
                "mtm_5y": r.mtm_5y,
                "buy_price_val": float(r.buy_price_val) if pd.notna(r.buy_price_val) else np.nan,
                "is_adj_px": bool(r.is_adj_px),
                "v51_cb_loss": bool(getattr(r, "v51_cb_loss", False)),
                "dt_deferred": bool(getattr(r, "dt_deferred", False)),
                "b_open_h": bool(getattr(r, "b_open_h", False)),
                "eo": bool(getattr(r, "eo", False)),
            }

    master_5y = master[master["buy_date"].between("2021-11-16", "2026-11-16")].copy().reset_index(drop=True)
    nr64, mtm_list, kpl_t1 = [], [], []
    for r in master_5y.itertuples(index=False):
        key = (r.strategy, r.buy_date, r.code)
        rec = f64_rows.get(key)
        if rec:
            nr64.append(rec["net_ret_f64"])
            mtm_list.append(rec["mtm_5y"])
        else:
            nr64.append(float(r.net_ret) if pd.notna(r.net_ret) else np.nan)
            mtm_list.append(())
        p_t1 = lookup_kpl_plate_t1(kpl_by_c6, r.code, r.buy_date)
        if not p_t1 and str(r.plate).strip() not in ("", "其他", "nan", "None"):
            p_t1 = str(r.plate).strip()
        kpl_t1.append(p_t1)

    master_5y["net_ret_f64"] = nr64
    master_5y["mtm_5y"] = mtm_list
    master_5y["kpl_plate_t1"] = kpl_t1

    # Also build pass_pool_f64 (all official passing signals >=82 for 20cm) & slot_pool_f64 (exact V20.0 preslot pool: cm20_thr=76.0)
    pass_parts, slot_parts = [], []
    trig_dts_slot = {}
    for st in STRAT_ORDER:
        df_st = pools[st]
        d_vec = np.zeros(len(df_st), dtype=float)
        p_df_82, _ = m1.sim_standalone(st, df_st, d_vec, high_cb_mode="v51_exact", cm20_thr=82.0)
        _, s_df = m1.sim_standalone(st, df_st, d_vec, high_cb_mode="v51_exact", cm20_thr=(76.0 if st == "20cm" else 82.0))
        trig_dts_slot[st] = set(s_df[s_df["buy_date"].between("2021-11-16", "2026-11-16")]["buy_date"])
        for label, sub in (("pass", p_df_82), ("slot", s_df)):
            sub_c = sub[sub["buy_date"].between("2021-11-16", "2026-11-16")].copy()
            if sub_c.empty:
                continue
            sc_s = sub_c["_sc_adj"] if "_sc_adj" in sub_c.columns else sub_c["v20_score"]
            sub_c["score"] = [round(float(x), 1) for x in sc_s] if st == "1to2" else sc_s.astype(float)
            sub_c["tier"] = [tpe.assign_physical_tier(st, sc) for sc in sub_c["score"]]
            sub_c["is_untrig"] = False
            cols = [
                "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
                "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px",
                "is_untrig", "mtm_5y", "open_pct",
            ]
            for c in cols:
                if c not in sub_c.columns:
                    sub_c[c] = np.nan
            if label == "pass":
                pass_parts.append(sub_c[cols])
            else:
                slot_parts.append(sub_c[cols])

    pass_pool_64 = pd.concat(pass_parts, ignore_index=True)
    slot_pool_64 = pd.concat(slot_parts, ignore_index=True)
    # Attach kpl_plate_t1 & sd_csrc_ind_id onto pass_pool_64 and slot_pool_64
    meta_map = {
        (r.strategy, r.buy_date, r.code): (r.kpl_plate_t1, r.sd_csrc_ind_id, float(r.sd_amp_20d_t1) if pd.notna(r.sd_amp_20d_t1) else np.nan)
        for r in master_5y[["strategy", "buy_date", "code", "kpl_plate_t1", "sd_csrc_ind_id", "sd_amp_20d_t1"]].itertuples(index=False)
    }
    for df_x in (pass_pool_64, slot_pool_64):
        df_x["kpl_plate_t1"] = [meta_map.get((r.strategy, r.buy_date, r.code), ("", np.nan, np.nan))[0] for r in df_x.itertuples(index=False)]
        df_x["csrc_ind_id"] = [meta_map.get((r.strategy, r.buy_date, r.code), ("", np.nan, np.nan))[1] for r in df_x.itertuples(index=False)]
        df_x["amp_20d_t1"] = [meta_map.get((r.strategy, r.buy_date, r.code), ("", np.nan, np.nan))[2] for r in df_x.itertuples(index=False)]

    # Filter untrig_base cleanly matching m1.run_combined_v20
    ut_clean = untrig_base[untrig_base["buy_date"].between("2021-11-16", "2026-11-16")].copy()
    ut_parts = []
    for st_u in ("3to4", "high", "1to2"):
        sub_u = ut_clean[(ut_clean["strategy"] == st_u) & (~ut_clean["buy_date"].isin(trig_dts_slot.get(st_u, set())))].copy()
        thr_u = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[st_u]
        sub_u = sub_u[sub_u["score"] >= thr_u].copy()
        if not sub_u.empty:
            sub_u["tier"] = [tpe.assign_physical_tier(st_u, sc) for sc in sub_u["score"]]
            sub_u = sub_u.sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
            ut_parts.append(sub_u)
    untrig_clean = pd.concat(ut_parts, ignore_index=True) if ut_parts else pd.DataFrame()
    if not untrig_clean.empty:
        untrig_clean["is_untrig"] = True
        untrig_clean["net_ret"] = 0.0
        untrig_clean["buy_price_val"] = np.nan
        untrig_clean["is_adj_px"] = False

    # Benchmark arrays aligned to cal_5y
    cal_df_5y = v20_ctx["calendar_5y"].sort_values("trade_date").reset_index(drop=True)
    assert cal_df_5y["trade_date"].tolist() == cal_5y

    return {
        "v20_ctx": v20_ctx,
        "master": master,
        "master_5y": master_5y,
        "catalog": catalog,
        "pools_oldhot": pools,
        "untrig_base": untrig_clean,
        "pass_pool_64": pass_pool_64,
        "slot_pool_64": slot_pool_64,
        "tr_base": tr_base,
        "waits_base": waits_base,
        "cal_5y": cal_5y,
        "idx_5y": idx_5y,
        "cal_df_5y": cal_df_5y,
        "csi_5y": cal_df_5y["csi300_daily_ret"].to_numpy(float),
        "ew_5y": cal_df_5y["alla_ew_daily_ret"].to_numpy(float),
        "bar_lu": bar_lu,
        "sh300": sh300,
        "all_sh_dts": all_sh_dts,
        "parity_info": {
            "n_trades": int(len(tr_base)),
            "nav": round(nav_base, 4),
            "max_ret_diff": max_ret_diff,
            "waits_count": int(len(waits_base)),
        },
    }


def simulate_multi_slot_mtm(
    pool_df: pd.DataFrame,
    rank_fn: Callable[[pd.DataFrame], pd.DataFrame],
    cal_5y: list[str],
    idx_5y: dict[str, int],
    n_slots: int = 1,
    slot_frac_fn: Optional[Callable[[list, int, dict], list[float]]] = None,
    untrig_df: Optional[pd.DataFrame] = None,
    timing_mode: str = "s_tier_reserve_only",
    max_per_strat_per_day: int = 1,
    rebal_mode: str = "dyn_equity",
) -> dict:
    """
    Exact causal multi-slot portfolio simulator with zero leverage (sum(active weights) <= 1.0)
    and exact daily MTM tracking from precomputed `mtm_5y` segment multipliers.

    When n_slots=1, slot_frac_fn=None, max_per_strat_per_day=1, timing_mode='s_tier_reserve_only',
    and rank_fn uses canonical S2C, it reproduces exact V20.0 278 trades & 69,134,091.5067x!
    """
    T = len(cal_5y)
    # Build combined candidate + untriggered frame
    use_ut = (untrig_df is not None and not untrig_df.empty and timing_mode in ("reserve_all", "s_tier_reserve_only", "s_tier_plus_1to2S", "s_tier_3to4S_only"))
    df = pd.concat([pool_df, untrig_df], ignore_index=True) if use_ut else pool_df.copy()
    df["buy_date"] = df["buy_date"].astype(str).str[:10]
    df["exit_date"] = df["exit_date"].astype(str).str[:10]
    df["buy_hhmm"] = df["buy_hhmm"].astype(int)
    df["exit_hhmm"] = df["exit_hhmm"].astype(int)
    if "is_untrig" not in df.columns:
        df["is_untrig"] = False

    # Rank candidates (must add 'prio' column; prio >= 999 excluded)
    df = rank_fn(df)
    df = df[df["prio"] < 999].copy()
    if df.empty:
        return {"trades_df": pd.DataFrame(), "dr_5y": np.zeros(T), "waits": [], "nav_equity": 1.0}

    if timing_mode == "confirmed_0925_first":
        df["phase"] = np.where(df["buy_hhmm"] == 925, 0, 1)
    elif timing_mode == "s_tier_reserve_only":
        is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"])
        df["phase"] = np.where((df["buy_hhmm"] == 925) | is_s_cond, 0, 1)
    elif timing_mode == "s_tier_plus_1to2S":
        is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)", "1to2_S(>=340)"])
        df["phase"] = np.where((df["buy_hhmm"] == 925) | is_s_cond, 0, 1)
    elif timing_mode == "s_tier_3to4S_only":
        is_s_cond = df["tier"].isin(["3to4_S(>=102)"])
        df["phase"] = np.where((df["buy_hhmm"] == 925) | is_s_cond, 0, 1)
    else:
        df["phase"] = 0

    df = df.sort_values(
        ["buy_date", "phase", "prio", "score", "buy_hhmm", "code"],
        ascending=[True, True, True, False, True, True],
        kind="mergesort",
    ).reset_index(drop=True)

    # Enforce max_per_strat_per_day for non-untrig if requested (e.g. 1 per strategy per day, except when picking 2nd best)
    by_day = {d: grp for d, grp in df.groupby("buy_date", sort=False)}

    # Active positions / waits in slots
    # Each slot item: dict(exit_date, exit_hhmm, is_wait, val, mult_map, weight, code, strategy)
    slots = []
    cash = 1.0
    nav_curve = np.ones(T, dtype=float)
    dr_5y = np.zeros(T, dtype=float)
    taken_trades = []
    waits = []
    prev_eq = 1.0

    for ti, dt in enumerate(cal_5y):
        # 1. Keep track of slots that already exited before today (< dt) - they should already be cleared
        # Check today's candidates sorted in order
        grp = by_day.get(dt)
        if grp is not None and not grp.empty:
            # Determine eligible candidates today respecting max_per_strat_per_day and no duplicate code
            held_codes = {s["code"] for s in slots if not s["is_wait"]}
            cand_rows = []
            strat_cnt = defaultdict(int)
            for r in grp.itertuples(index=False):
                if r.code in held_codes:
                    continue
                if not r.is_untrig:
                    if strat_cnt[r.strategy] >= max_per_strat_per_day:
                        continue
                    strat_cnt[r.strategy] += 1
                cand_rows.append(r)

            # Process candidates chronologically/by priority; note same-day exit->reentry at buy_hhmm > exit_hhmm
            # Group intraday events? Since slots may exit on dt at exit_hhmm, sort today's slot exits and candidate entries!
            # Check slot availability for a given buy_hhmm
            def _free_exiting_slots(bh):
                nonlocal cash, slots
                still = []
                for s in slots:
                    if (s["exit_date"] < dt) or (s["exit_date"] == dt and s["exit_hhmm"] < bh):
                        if not s["is_wait"]:
                            # Apply exit-day multiplier right at exit_hhmm before freeing cash
                            m_today = s["mult_map"].get(ti, 1.0)
                            s["val"] *= m_today
                            s["applied_days"].add(ti)
                            cash += s["val"]
                    else:
                        still.append(s)
                slots = still

            # First apply any exits strictly < dt (should be none, defensive)
            _free_exiting_slots(0)

            # Determine free slots at 0925 / per candidate buy_hhmm
            # When n_slots > 1, decide target fractions for today's openings
            accepted_today = []
            # To compute target fractions cleanly on today's free slots, iterate candidates in order
            # Note: if a candidate is accepted with buy_hhmm=925, it takes one slot; if wait is accepted, it blocks 1 slot up to cancel_hhmm
            for r in cand_rows:
                _free_exiting_slots(int(r.buy_hhmm))
                n_busy = len(slots)
                if n_busy >= n_slots:
                    continue
                # Check if same code was already accepted today
                if any((not s["is_wait"]) and s["code"] == r.code for s in slots):
                    continue
                if r.is_untrig:
                    waits.append({
                        "buy_date": dt, "wait_strategy": r.strategy, "wait_tier": r.tier,
                        "wait_code": r.code, "wait_score": float(r.score), "cancel_hhmm": int(r.exit_hhmm),
                    })
                    slots.append({
                        "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
                        "is_wait": True, "val": 0.0, "mult_map": {}, "code": r.code,
                        "strategy": r.strategy, "applied_days": set(),
                    })
                else:
                    accepted_today.append(r)
                    # Reserve slot placeholder (weight assigned below or immediately)
                    mmap = {t_i: float(mult) for t_i, mult in r.mtm_5y} if hasattr(r, "mtm_5y") and r.mtm_5y else {}
                    slots.append({
                        "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
                        "is_wait": False, "val": 0.0, "mult_map": mmap, "code": r.code,
                        "strategy": r.strategy, "applied_days": set(), "_row": r,
                    })

            if accepted_today:
                # Current total equity before new allocations (cash + open non-wait slots)
                eq_now = cash + sum(s["val"] for s in slots if not s["is_wait"])
                new_slots = [s for s in slots if "_row" in s]
                k_new = len(new_slots)
                if slot_frac_fn is not None:
                    fracs = slot_frac_fn(accepted_today, n_slots, {"dt": dt, "ti": ti, "eq": eq_now, "cash": cash, "n_busy_existing": len(slots) - k_new, "cand_rows": cand_rows})
                else:
                    # Default equal per-slot target: 1.0 / n_slots of current equity
                    fracs = [1.0 / n_slots] * k_new

                for s, frac in zip(new_slots, fracs):
                    r = s.pop("_row")
                    target_alloc = min(cash, max(0.0, float(frac) * eq_now))
                    if target_alloc <= 1e-12:
                        # Cannot fund -> drop slot
                        slots.remove(s)
                        continue
                    cash -= target_alloc
                    s["val"] = target_alloc
                    rec = {
                        "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm),
                        "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
                        "code": r.code, "name": getattr(r, "name", ""),
                        "strategy": r.strategy, "tier": r.tier,
                        "score": float(r.score), "net_ret": float(r.net_ret),
                        "alloc_weight": round(target_alloc / max(1e-12, eq_now), 6),
                        "mtm_5y": getattr(r, "mtm_5y", ()),
                    }
                    taken_trades.append(rec)

        # 2. End-of-day MTM update for all active non-wait positions that haven't applied day ti yet
        # Also release any positions (or waits) whose exit_date == dt (at end of day, after applying day ti MTM)
        still_eod = []
        for s in slots:
            if not s["is_wait"] and ti not in s["applied_days"]:
                m_today = s["mult_map"].get(ti, 1.0)
                s["val"] *= m_today
                s["applied_days"].add(ti)
            if s["exit_date"] <= dt:
                if not s["is_wait"]:
                    cash += s["val"]
            else:
                still_eod.append(s)
        slots = still_eod

        eq_eod = cash + sum(s["val"] for s in slots if not s["is_wait"])
        nav_curve[ti] = eq_eod
        dr_5y[ti] = eq_eod / prev_eq - 1.0
        prev_eq = eq_eod

    tr_df = pd.DataFrame(taken_trades)
    return {
        "trades_df": tr_df,
        "dr_5y": dr_5y,
        "nav_curve": nav_curve,
        "nav_equity": float(nav_curve[-1]),
        "waits": waits,
    }


def evaluate_portfolio_windows(
    trades_df: pd.DataFrame,
    dr_5y: np.ndarray,
    ctx: dict,
    cand_pool_df: Optional[pd.DataFrame] = None,
    perm_n: int = 1000,
    seed: int = 20261125,
) -> dict:
    """Evaluate 5Y, WF (2023-2026), OOS (2025-2026), Y2026, and IS (2021-2024) + 1000x perm."""
    cal_5y = ctx["cal_5y"]
    idx_5y = ctx["idx_5y"]
    csi_arr = ctx["csi_5y"]
    ew_arr = ctx["ew_5y"]
    if cand_pool_df is None:
        cand_pool_df = ctx["pass_pool_64"].assign(can_buy_hygiene=True)

    windows = [
        ("Y5", "2021-11-16", "2026-11-16"),
        ("WF_2023_2026", "2023-01-03", "2026-11-16"),
        ("Y2025_2026", "2025-01-01", "2026-11-16"),
        ("Y2026", "2026-01-01", "2026-11-16"),
        ("IS_2021_2024", "2021-11-16", "2024-12-31"),
    ]
    res = {}
    for wname, sdt, edt in windows:
        win_pos = [idx_5y[d] for d in cal_5y if sdt <= d <= edt]
        T = len(win_pos)
        dr = dr_5y[win_pos]
        csi_r = csi_arr[win_pos]
        ew_r = ew_arr[win_pos]
        csi_pct = (float(np.prod(1.0 + csi_r)) - 1.0) * 100.0
        alla_pct = (float(np.prod(1.0 + ew_r)) - 1.0) * 100.0

        mtm_nav = float(np.prod(1.0 + dr))
        curve = np.concatenate([[1.0], np.cumprod(1.0 + dr)])
        pk = np.maximum.accumulate(curve)
        daily_mdd = float(np.max((pk - curve) / pk) * 100.0)
        sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
        sharpe = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
        cagr = (mtm_nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if mtm_nav > 0 else -100.0
        calmar = (cagr / daily_mdd) if daily_mdd > 1e-6 else 0.0

        sub = trades_df[trades_df["buy_date"].between(sdt, edt)] if (trades_df is not None and not trades_df.empty) else pd.DataFrame()
        if sub.empty:
            res[wname] = {
                "n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
                "nav": round(mtm_nav, 4), "mtm_nav": round(mtm_nav, 4),
                "ex_top3_nav": 1.0, "ex_top5_nav": 1.0,
                "daily_mdd_pct": round(daily_mdd, 2), "trade_mdd_pct": 0.0,
                "daily_sharpe": round(sharpe, 3), "daily_calmar": round(calmar, 2),
                "cagr_pct": round(cagr, 2), "csi300_pct": round(csi_pct, 2),
                "excess_csi300_pp": round((mtm_nav - 1.0) * 100.0 - csi_pct, 2),
                "excess_alla_ew_pp": round((mtm_nav - 1.0) * 100.0 - alla_pct, 2),
                "exposure_pct": 0.0,
            }
            continue

        raw_rets = sub["net_ret"].to_numpy(float)
        # Effective portfolio return per trade (weighted by alloc_weight if fractional!)
        weights = sub["alloc_weight"].to_numpy(float) if "alloc_weight" in sub.columns else np.ones(len(sub))
        eff_rets = raw_rets * weights
        w_pos, w_neg = raw_rets[raw_rets > 0], raw_rets[raw_rets <= 0]
        wr = float((raw_rets > 0).mean() * 100.0)
        plr = float(w_pos.mean() / abs(w_neg.mean())) if (len(w_pos) and len(w_neg) and w_neg.mean() < 0) else (99.0 if len(w_pos) else 0.0)

        # For ex_top5, drop top 5 highest portfolio-impact trades and re-evaluate daily MTM or compound effective return
        sr_eff = np.sort(eff_rets)
        ex3_approx = float(mtm_nav / np.prod(1.0 + sr_eff[-3:])) if len(sr_eff) > 3 else 1.0
        ex5_approx = float(mtm_nav / np.prod(1.0 + sr_eff[-5:])) if len(sr_eff) > 5 else 1.0
        # When single-slot full weight (all weights == 1.0), exact match to prod(1+sr[:-5])
        if np.allclose(weights, 1.0):
            sr_raw = np.sort(raw_rets)
            ex3_approx = float(np.prod(1.0 + sr_raw[:-3])) if len(sr_raw) > 3 else 1.0
            ex5_approx = float(np.prod(1.0 + sr_raw[:-5])) if len(sr_raw) > 5 else 1.0
            tr_nav = float(np.prod(1.0 + raw_rets))
        else:
            tr_nav = mtm_nav

        tc = np.concatenate([[1.0], np.cumprod(1.0 + eff_rets)])
        tp = np.maximum.accumulate(tc)
        tr_mdd = float(np.max((tp - tc) / tp) * 100.0)

        # Active days (union of holding intervals)
        held_mask = np.zeros(len(cal_5y), dtype=bool)
        for r in sub.itertuples(index=False):
            bi = idx_5y.get(str(r.buy_date))
            ei = idx_5y.get(str(r.exit_date))
            if bi is not None and ei is not None:
                held_mask[bi:ei + 1] = True
        act_days = int(held_mask[win_pos].sum())
        exp_pct = act_days / max(1, T) * 100.0

        res[wname] = {
            "n": int(len(sub)), "wr_pct": round(wr, 2), "plr": round(plr, 2),
            "mean_pct": round(float(raw_rets.mean() * 100.0), 2),
            "eff_mean_pct": round(float(eff_rets.mean() * 100.0), 2),
            "nav": round(tr_nav, 4), "mtm_nav": round(mtm_nav, 4),
            "ex_top3_nav": round(ex3_approx, 4), "ex_top5_nav": round(ex5_approx, 4),
            "daily_mdd_pct": round(daily_mdd, 2), "trade_mdd_pct": round(tr_mdd, 2),
            "daily_sharpe": round(sharpe, 3), "daily_calmar": round(calmar, 2),
            "cagr_pct": round(cagr, 2), "csi300_pct": round(csi_pct, 2),
            "excess_csi300_pp": round((tr_nav - 1.0) * 100.0 - csi_pct, 2),
            "excess_alla_ew_pp": round((tr_nav - 1.0) * 100.0 - alla_pct, 2),
            "active_days": act_days, "exposure_pct": round(exp_pct, 2),
        }

    perm_5y = wfm.perm_test_trading_days(trades_df, cand_pool_df, "2021-11-16", "2026-11-16", n_perm=perm_n, seed=seed) if (perm_n > 0 and not trades_df.empty) else {}
    perm_wf = wfm.perm_test_trading_days(trades_df, cand_pool_df, "2023-01-03", "2026-11-16", n_perm=perm_n, seed=seed) if (perm_n > 0 and not trades_df.empty) else {}
    return {"windows": res, "perm_5y": perm_5y, "perm_wf": perm_wf}


if __name__ == "__main__":
    ctx = load_w2a6_context()
    print("[PARITY PASS]", ctx["parity_info"])
    # Test simulate_multi_slot_mtm parity against tr_base
    sim0 = simulate_multi_slot_mtm(
        ctx["slot_pool_64"],
        lambda d: d.assign(prio=d["tier"].map(CANON_S2C_TIER_MAP).fillna(999)),
        ctx["cal_5y"], ctx["idx_5y"],
        n_slots=1, untrig_df=ctx["untrig_base"][ctx["untrig_base"]["buy_date"].between("2021-11-16", "2026-11-16")],
        timing_mode="s_tier_reserve_only", max_per_strat_per_day=1,
    )
    tr0 = sim0["trades_df"]
    print(f"[MULTI-SLOT SIM PARITY] n={len(tr0)}, eq_nav={sim0['nav_equity']:.4f}, waits={len(sim0['waits'])}")
    assert len(tr0) == 278
    assert list(zip(tr0["buy_date"], tr0["code"], tr0["strategy"])) == list(zip(ctx["tr_base"]["buy_date"], ctx["tr_base"]["code"], ctx["tr_base"]["strategy"]))
    assert abs(sim0["nav_equity"] - 69134091.5067) < 1e-2, f"Nav mismatch: {sim0['nav_equity']}"
    print("[EXACT MULTI-SLOT PARITY VERIFIED]")
