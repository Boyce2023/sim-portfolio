#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part 2: Conditional Order Trigger-Price & Fixed Limit-Cap Optimization Re-Backtest
under 3-Tier Velocity Slippage (Slow 0% / Medium +0.5% / Fast +1.0%) across:
  1. 1to2 V20 (full 198 passing rows / 164 top-1 dates, cancel 11:30)
  2. 3to4 V4.1 (full 128 passing rows / 123 dates, cancel 10:30)
  3. High V5.1 (full 52 passing rows incl. 28 green opens & 6 untriggered, cancel 11:30)

Hard rules: ZERO import yfinance (D12); ZERO cap10m; strict IS (<=2024-06-30),
blind OOS (>=2024-07-04), Near3Y (>=2023-11-16), Y2026 (>=2026-01-01), FULL.
Only recommend changing current trigger if IS + OOS + 2026 all beat current AND CSCV PBO < 25%.
"""
import json
import os
import sys
import time
import warnings
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

from trigger_opt_engine import (
    CANON_WINDOWS,
    FEE_RATE,
    OUT_DIR,
    PART1_DIR,
    SIM,
    calc_cscv_pbo_matrix,
    evaluate_variant_d15,
    exec_intraday_vel_or_cap,
    load_all_5m_and_daily,
    sanitize_json,
    sf,
)
from part2_loaders import build_1to2_full_pool, build_3to4_full_pool, build_high_full_pool


def verify_slot_cleanliness(df_slot: pd.DataFrame, dmap: dict, label: str, allow_same_day_after_0925: bool = True) -> None:
    if df_slot.empty:
        return
    assert (df_slot["exit_date"] > df_slot["buy_date"]).all(), f"[{label}] T+0 violation"
    prev_ed, prev_eh = "", 0
    for r in df_slot.itertuples(index=False):
        c6, bd, ed = str(r.c6).zfill(6), str(r.buy_date), str(r.exit_date)
        bh, eh = int(r.buy_hhmm), int(r.exit_hhmm)
        if prev_ed:
            assert (bd > prev_ed) or (allow_same_day_after_0925 and bd == prev_ed and bh > prev_eh), (
                f"[{label}] Slot overlap: prev {prev_ed}@{prev_eh} vs {bd}@{bh}"
            )
        prev_ed, prev_eh = ed, eh
        bb = dmap[(c6, bd)]
        eb = dmap[(c6, ed)]
        assert not (bb["open"] >= bb["zt_px"] - 0.005 and bb["low"] >= bb["zt_px"] - 0.005), f"[{label}] Yizi buy {c6} {bd}"
        assert float(r.eff_buy_price) <= bb["zt_px"] + 1e-4, f"[{label}] Eff buy > zt_px {c6} {bd}"
        assert not (eh >= 1455 and eb["is_dt_exact"]), f"[{label}] 15:00 DT exit {c6} {ed}"


def summarize_exec_outcomes(outcomes: list[dict], filled_rows: list[dict], unfill_hypo_rets: list[dict]) -> dict:
    tot = len(outcomes)
    cnt = {}
    for o in outcomes:
        cnt[o["status"]] = cnt.get(o["status"], 0) + 1
    tiers = {}
    slips, ogt = [], 0
    for o in outcomes:
        if o["status"] in ("filled_0925", "filled_intraday"):
            vt = o["vel_tier"]
            tiers[vt] = tiers.get(vt, 0) + 1
            slips.append(o["real_slip"])
            if o.get("open_gt_trig"):
                ogt += 1
    n_trig_attempt = cnt.get("filled_0925", 0) + cnt.get("filled_intraday", 0) + cnt.get("missed_cap", 0)
    n_missed = cnt.get("missed_cap", 0)
    n_fast_filled_or_miss = sum(1 for o in outcomes if o.get("vel_tier") == "fast")
    missed_wins = sum(1 for x in unfill_hypo_rets if x["hypo_ret_vel"] > 0)
    missed_losses = sum(1 for x in unfill_hypo_rets if x["hypo_ret_vel"] <= 0)
    return {
        "pool_total": tot,
        "status_counts": cnt,
        "filled_total": len(filled_rows),
        "vel_tiers_filled": tiers,
        "trigger_attempt_count": n_trig_attempt,
        "missed_cap_count": n_missed,
        "miss_rate_vs_triggered_pct": sf(n_missed / n_trig_attempt * 100.0 if n_trig_attempt else 0.0, 2),
        "fast_events_total": n_fast_filled_or_miss,
        "miss_rate_vs_fast_pct": sf(n_missed / n_fast_filled_or_miss * 100.0 if n_fast_filled_or_miss else 0.0, 2),
        "avg_real_slip_filled_bps": sf(np.mean(slips) * 10000.0 if slips else 0.0, 2),
        "open_gt_trig_filled": ogt,
        "missed_hypo_wins": missed_wins,
        "missed_hypo_losses": missed_losses,
        "missed_hypo_mean_ret_pct": sf(np.mean([x["hypo_ret_vel"] for x in unfill_hypo_rets]) * 100.0 if unfill_hypo_rets else 0.0, 2),
        "missed_trades_sample": unfill_hypo_rets[:12],
    }


def eval_1to2_variant(
    df_all: pd.DataFrame,
    bars_5m: dict,
    dmap: dict,
    cal_5y: list[str],
    dt_idx_5y: dict,
    sh300: dict,
    all_sh_dts: list[str],
    trig_mode: str,
    o_mult: float,
    p_mult: float,
    force_0925: bool = False,
    keep_mon_direct: bool = True,
    cap_pct: float | None = None,
    force_pb_fast: bool = False,
) -> tuple[dict, np.ndarray, pd.DataFrame]:
    """Run one 1to2 V20 trigger variant on full 198-row pool (top-1 slot per date + equal-weight full pool)."""
    filled_rows, outcomes, hypo_misses = [], [], []
    # Also compute sell-5 reference for missed cap trades to measure exact missed PnL
    top1_keys = set(zip(df_all.groupby("buy_date").head(1)["buy_date"], df_all.groupby("buy_date").head(1)["c6"]))

    for r in df_all.itertuples(index=False):
        use_0925 = force_0925 or (keep_mon_direct and bool(r.default_do_direct))
        if trig_mode == "open_only":
            ntrig = r.open_d * o_mult
        elif trig_mode == "max_op":
            ntrig = max(round(r.open_d * o_mult, 2), round(r.d1_close * p_mult, 2))
        else:
            ntrig = r.open_d

        arr = bars_5m.get((r.c6, r.buy_date))
        res = exec_intraday_vel_or_cap(
            arr, r.open_d, r.pre_c, r.zt_px, ntrig, 1130,
            force_0925=use_0925, cap_pct=cap_pct, force_pullback_if_fast=force_pb_fast,
            round_trig_2dec=True, match_3to4_open_floor=False, trig_eps=1e-4,
        )
        outcomes.append(res)
        is_top1 = (r.buy_date, r.c6) in top1_keys

        if res["status"] in ("filled_0925", "filled_intraday"):
            eff_b = float(res["eff_buy"])
            pre_b = float(res["pre_slip_px"])
            # Match upgrade_1to2_pit round(..., 4) before vel ratio for exact Part 1 parity
            ret_pre = round((r.exit_price / pre_b) * r.adj_ratio * (1.0 - FEE_RATE) - 1.0, 4)
            ret_vel = round((1.0 + ret_pre) * (pre_b / eff_b) - 1.0, 8)
            filled_rows.append({
                "buy_date": r.buy_date, "c6": r.c6, "code": r.c6, "name": r.name,
                "buy_hhmm": int(res["buy_hhmm"]), "pre_slip_px": pre_b, "eff_buy_price": eff_b,
                "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm), "exit_price": r.exit_price,
                "exit_at_open": bool(r.exit_at_open), "sv": float(r.sv), "score": float(r.score),
                "net_ret_pre": ret_pre, "net_ret": ret_vel, "is_top1": is_top1,
                "vel_tier": res["vel_tier"], "is_zt_hit": bool(res["is_zt_hit"]),
                "is_zt_sealed": bool(res["is_zt_sealed"]),
            })
        elif res["status"] == "missed_cap" and is_top1:
            # Hypothetical return under sell-5 sweep for this missed top-1 candidate
            eff_s5 = float(res["eff_sell5"])
            tp_s5 = float(res["trig_px"])
            r_pre_h = round((r.exit_price / tp_s5) * r.adj_ratio * (1.0 - FEE_RATE) - 1.0, 4)
            r_vel_h = round((1.0 + r_pre_h) * (tp_s5 / eff_s5) - 1.0, 4)
            hypo_misses.append({
                "buy_date": r.buy_date, "code": r.c6, "name": r.name,
                "trig_px": tp_s5, "eff_sell5": eff_s5, "cap_px": float(res["cap_px"]),
                "hypo_ret_vel": r_vel_h, "zt_sealed": bool(res["is_zt_sealed"]),
            })

    df_pool = pd.DataFrame(filled_rows)
    # Single-slot strict top-1 selection per date (no rank-2 fallback on untriggered/missed top-1)
    top1_map = {}
    if not df_pool.empty:
        for r in df_pool[df_pool["is_top1"]].itertuples(index=False):
            top1_map[r.buy_date] = r

    taken = []
    fdt, fopen = "", False
    # Iterate over all 164 top-1 candidate dates in sorted order (09:25 exit frees cash for >=09:35 intraday, not 09:25 auction)
    for d2 in sorted(df_all["buy_date"].unique()):
        cand = top1_map.get(d2)
        if cand is not None:
            bh = int(cand.buy_hhmm)
            if fdt == "" or d2 > fdt or (d2 == fdt and fopen and bh > 925):
                taken.append(cand._asdict())
                fdt, fopen = str(cand.exit_date), bool(cand.exit_at_open)

    df_slot = pd.DataFrame(taken)
    verify_slot_cleanliness(df_slot, dmap, f"1to2:{trig_mode}:{cap_pct}", allow_same_day_after_0925=True)
    exec_st = summarize_exec_outcomes(outcomes, filled_rows, hypo_misses)
    d15, dr = evaluate_variant_d15(df_slot, df_pool, exec_st, cal_5y, dt_idx_5y, sh300, all_sh_dts, dmap, "net_ret", "eff_buy_price")
    return d15, dr, df_slot


def eval_3to4_variant(
    df_all: pd.DataFrame,
    bars_5m: dict,
    dmap: dict,
    cal_5y: list[str],
    dt_idx_5y: dict,
    sh300: dict,
    all_sh_dts: list[str],
    p_mult: float,
    force_0925: bool = False,
    cap_pct: float | None = None,
    force_pb_fast: bool = False,
) -> tuple[dict, np.ndarray, pd.DataFrame]:
    """Run one 3to4 V4.1 trigger variant on full 128-row pool (10:30 cancel)."""
    filled_rows, outcomes, hypo_misses = [], [], []
    # For fixed limit cap, track if multi-candidate date (5/123 dates) misses rank-1 priority
    missed_on_dt = set()

    for r in df_all.itertuples(index=False):
        ntrig = r.pre_c * p_mult
        arr = bars_5m.get((r.c6, r.buy_date))
        res = exec_intraday_vel_or_cap(
            arr, r.open_d, r.pre_c, r.zt_px, ntrig, 1030,
            force_0925=force_0925, cap_pct=cap_pct, force_pullback_if_fast=force_pb_fast,
            round_trig_2dec=False, match_3to4_open_floor=True, trig_eps=0.0,
        )
        outcomes.append(res)
        if res["status"] in ("filled_0925", "filled_intraday"):
            eff_b = float(res["eff_buy"])
            pre_b = float(res["pre_slip_px"])
            # Match Part 1: dt_deferred uses rounded buy_px (2 dec), non-deferred uses unrounded orig_buy_px on current 1.065
            use_orig_unround = (not force_0925 and abs(p_mult - 1.065) < 1e-9 and pd.notna(r.orig_buy_px) and res["buy_hhmm"] == r.orig_buy_hhmm)
            if r.dt_deferred:
                base_b_denom = pre_b
                ret_pre = round((r.exit_price_raw / base_b_denom) * r.adj_ratio * (1.0 - FEE_RATE) - 1.0, 6)
            else:
                base_b_denom = float(r.orig_buy_px) if use_orig_unround else pre_b
                ret_pre = round((r.exit_price_raw * r.adj_ratio_cache) / base_b_denom * (1.0 - FEE_RATE) - 1.0, 6)
            ret_vel = round((1.0 + ret_pre) * (pre_b / eff_b) - 1.0, 8)
            filled_rows.append({
                "buy_date": r.buy_date, "c6": r.c6, "code": r.c6, "name": r.name,
                "buy_hhmm": int(res["buy_hhmm"]), "pre_slip_px": pre_b, "eff_buy_price": eff_b,
                "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm), "exit_price": r.exit_price,
                "priority_score": float(r.priority_score), "score": int(r.score),
                "net_ret_pre": ret_pre, "net_ret": ret_vel,
                "vel_tier": res["vel_tier"], "is_zt_hit": bool(res["is_zt_hit"]),
                "is_zt_sealed": bool(res["is_zt_sealed"]),
            })
        elif res["status"] == "missed_cap":
            missed_on_dt.add((r.buy_date, r.c6))
            eff_s5 = float(res["eff_sell5"])
            tp_s5 = float(res["trig_px"])
            if r.dt_deferred:
                r_pre_h = round((r.exit_price_raw / tp_s5) * r.adj_ratio * (1.0 - FEE_RATE) - 1.0, 6)
            else:
                base_denom = float(r.orig_buy_px) if (abs(p_mult - 1.065) < 1e-9 and pd.notna(r.orig_buy_px)) else tp_s5
                r_pre_h = round((r.exit_price_raw * r.adj_ratio_cache) / base_denom * (1.0 - FEE_RATE) - 1.0, 6)
            r_vel_h = round((1.0 + r_pre_h) * (tp_s5 / eff_s5) - 1.0, 4)
            hypo_misses.append({
                "buy_date": r.buy_date, "code": r.c6, "name": r.name,
                "trig_px": tp_s5, "eff_sell5": eff_s5, "cap_px": float(res["cap_px"]),
                "hypo_ret_vel": r_vel_h, "zt_sealed": bool(res["is_zt_sealed"]),
            })

    df_pool = pd.DataFrame(filled_rows)
    taken = []
    if not df_pool.empty:
        srt = df_pool.sort_values(["buy_date", "buy_hhmm", "priority_score", "c6"], ascending=[True, True, False, True])
        fdt, fhh = "", 0
        for r in srt.itertuples(index=False):
            if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
                taken.append(r._asdict())
                fdt, fhh = str(r.exit_date), int(r.exit_hhmm)

    df_slot = pd.DataFrame(taken)
    verify_slot_cleanliness(df_slot, dmap, f"3to4:{p_mult}:{cap_pct}", allow_same_day_after_0925=True)
    exec_st = summarize_exec_outcomes(outcomes, filled_rows, hypo_misses)
    d15, dr = evaluate_variant_d15(df_slot, df_pool, exec_st, cal_5y, dt_idx_5y, sh300, all_sh_dts, dmap, "net_ret", "eff_buy_price")
    return d15, dr, df_slot


def eval_high_variant(
    df_all: pd.DataFrame,
    bars_5m: dict,
    dmap: dict,
    cal_5y: list[str],
    dt_idx_5y: dict,
    sh300: dict,
    all_sh_dts: list[str],
    g_mult: float,
    force_0925: bool = False,
    cap_pct: float | None = None,
    force_pb_fast: bool = False,
    cb_mode: str = "NoCB",
) -> tuple[dict, np.ndarray, pd.DataFrame]:
    """
    Run one High V5.1 trigger variant on full 52-row pool (24 red/flat @09:25 + 28 green opens).
    cb_mode: 'NoCB' | 'CausalCB' | 'Matched42CB'
    """
    filled_rows, outcomes, hypo_misses = [], [], []
    for r in df_all.itertuples(index=False):
        is_rf = bool(r.is_red_flat)
        use_0925 = force_0925 or is_rf
        ntrig = r.open_d if use_0925 else round(r.open_d * g_mult, 2)
        arr = bars_5m.get((r.c6, r.buy_date))
        res = exec_intraday_vel_or_cap(
            arr, r.open_d, r.pre_c, r.zt_px, ntrig, 1130,
            force_0925=use_0925, cap_pct=cap_pct, force_pullback_if_fast=force_pb_fast,
            round_trig_2dec=True, match_3to4_open_floor=True, trig_eps=0.0,
        )
        outcomes.append(res)
        if res["status"] in ("filled_0925", "filled_intraday"):
            eff_b = float(res["eff_buy"])
            pre_b = float(res["pre_slip_px"])
            # Match Part 1 ledger_high_v51_clean.csv precision
            ret_pre = round((r.exit_price_raw / pre_b) * r.adj_ratio * (1.0 - FEE_RATE) - 1.0, 6)
            ret_vel = round((1.0 + ret_pre) * (pre_b / eff_b) - 1.0, 8)
            pre_def_ret = (r.pre_defer_e_px / pre_b) * r.adj_ratio * (1.0 - FEE_RATE) - 1.0
            filled_rows.append({
                "buy_date": r.buy_date, "c6": r.c6, "code": r.c6, "name": r.name,
                "buy_hhmm": int(res["buy_hhmm"]), "pre_slip_px": pre_b, "eff_buy_price": eff_b,
                "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm), "exit_price": r.exit_price,
                "eo": bool(r.eo), "b_open_h": bool(res["buy_hhmm"] == 925), "score": int(r.score),
                "net_ret_pre": ret_pre, "net_ret": ret_vel, "pre_defer_ret": float(pre_def_ret),
                "vel_tier": res["vel_tier"], "is_zt_hit": bool(res["is_zt_hit"]),
                "is_zt_sealed": bool(res["is_zt_sealed"]),
            })
        elif res["status"] == "missed_cap":
            eff_s5 = float(res["eff_sell5"])
            tp_s5 = float(res["trig_px"])
            r_pre_h = round((r.exit_price_raw / tp_s5) * r.adj_ratio * (1.0 - FEE_RATE) - 1.0, 6)
            r_vel_h = round((1.0 + r_pre_h) * (tp_s5 / eff_s5) - 1.0, 4)
            hypo_misses.append({
                "buy_date": r.buy_date, "code": r.c6, "name": r.name,
                "trig_px": tp_s5, "eff_sell5": eff_s5, "cap_px": float(res["cap_px"]),
                "hypo_ret_vel": r_vel_h, "zt_sealed": bool(res["is_zt_sealed"]),
            })

    df_pool = pd.DataFrame(filled_rows)
    taken = []
    if not df_pool.empty:
        srt = df_pool.sort_values(["buy_date", "score", "c6"], ascending=[True, False, True])
        fd, peo, cl, sk = "", False, 0, False
        for r in srt.itertuples(index=False):
            if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not bool(r.b_open_h))):
                rv = float(r.net_ret)
                # Matched42CB evaluates CB trigger on pre-defer pre_slip return (matching v51_ledger_42)
                rv_cb = float(r.pre_defer_ret) if cb_mode == "Matched42CB" else rv
                if cb_mode in ("CausalCB", "Matched42CB") and sk:
                    fd, peo = str(r.exit_date), bool(r.eo)
                    if rv_cb > 0.0:
                        sk, cl = False, 0
                    continue
                taken.append(r._asdict())
                fd, peo = str(r.exit_date), bool(r.eo)
                if cb_mode in ("CausalCB", "Matched42CB"):
                    if rv_cb < -0.02:
                        cl += 1
                        if cl >= 2:
                            sk = True
                    elif rv_cb > 0.0:
                        cl = 0

    df_slot = pd.DataFrame(taken)
    verify_slot_cleanliness(df_slot, dmap, f"high:{cb_mode}:{g_mult}:{cap_pct}", allow_same_day_after_0925=True)
    exec_st = summarize_exec_outcomes(outcomes, filled_rows, hypo_misses)
    d15, dr = evaluate_variant_d15(df_slot, df_pool, exec_st, cal_5y, dt_idx_5y, sh300, all_sh_dts, dmap, "net_ret", "eff_buy_price")
    return d15, dr, df_slot


def check_recommendation(grid_dict: dict, base_key: str, pbo_mtm_s10: float, pbo_ed_s10: float) -> dict:
    """Strict rule: Only recommend changing trigger if IS + OOS + Y2026 ALL beat baseline AND PBO < 25%."""
    base = grid_dict[base_key]["windows"]
    beaters = []
    for k, v in grid_dict.items():
        if k == base_key or "cap" in k:
            continue
        w = v["windows"]
        beats_is = w["IS"]["nav_1s"] > base["IS"]["nav_1s"] and w["IS"]["daily_sharpe"] >= base["IS"]["daily_sharpe"] - 0.05
        beats_oos = w["OOS"]["nav_1s"] > base["OOS"]["nav_1s"] and w["OOS"]["daily_sharpe"] >= base["OOS"]["daily_sharpe"] - 0.05
        beats_26 = w["Y2026"]["nav_1s"] > base["Y2026"]["nav_1s"]
        if beats_is and beats_oos and beats_26:
            beaters.append({
                "variant": k,
                "is_nav_ratio": sf(w["IS"]["nav_1s"] / max(1e-6, base["IS"]["nav_1s"]), 4),
                "oos_nav_ratio": sf(w["OOS"]["nav_1s"] / max(1e-6, base["OOS"]["nav_1s"]), 4),
                "y26_nav_ratio": sf(w["Y2026"]["nav_1s"] / max(1e-6, base["Y2026"]["nav_1s"]), 4),
            })
    pbo_ok = (pbo_mtm_s10 < 25.0) and (pbo_ed_s10 < 25.0)
    recommend_change = (len(beaters) > 0) and pbo_ok
    return {
        "base_key": base_key,
        "all_3_windows_nav_beaters": beaters,
        "cscv_mtm_s10_pbo_pct": pbo_mtm_s10,
        "cscv_exitdate_s10_pbo_pct": pbo_ed_s10,
        "pbo_lt_25pct": pbo_ok,
        "recommend_change_trigger": recommend_change,
    }


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    print("[1/4] Loading merged 5m bars (incl. baostock patch) & daily truth...")
    sh300, all_sh_dts, cal_5y, dt_idx_5y, bars_5m, dmap = load_all_5m_and_daily()

    # =========================================================================
    # 1. 一进二 V20
    # =========================================================================
    print("[2/4] Building & testing 1to2 V20 full pool (198 rows / 164 top-1 dates)...")
    df12_all, df12_top1, ctx_bars_12 = build_1to2_full_pool(bars_5m, dmap)
    for k, v in ctx_bars_12.items():
        if k not in bars_5m:
            bars_5m[k] = v

    grid_12_specs = [
        ("auc_0925", "auc", 1.0, 1.0, True, True, None, False),
        ("open_1005", "open_only", 1.005, 1.0, False, True, None, False),
        ("open_1008", "open_only", 1.008, 1.0, False, True, None, False),
        ("max_o1005_p1055", "max_op", 1.005, 1.055, False, True, None, False),
        ("max_o1008_p1060", "max_op", 1.008, 1.060, False, True, None, False),
        ("current_o1012_p1065", "max_op", 1.012, 1.065, False, True, None, False),
        ("max_o1015_p1065", "max_op", 1.015, 1.065, False, True, None, False),
        ("max_o1020_p1070", "max_op", 1.020, 1.070, False, True, None, False),
        ("max_o1012_p1075", "max_op", 1.012, 1.075, False, True, None, False),
        ("current_no_mon_direct", "max_op", 1.012, 1.065, False, False, None, False),
    ]
    cap_12_specs = [
        ("current_cap_p05", "max_op", 1.012, 1.065, False, True, 0.005, False),
        ("current_cap_p08", "max_op", 1.012, 1.065, False, True, 0.008, False),
        ("current_cap_p10_vel", "max_op", 1.012, 1.065, False, True, 0.010, False),
        ("current_cap_p10_fastpb", "max_op", 1.012, 1.065, False, True, 0.010, True),
        ("o1005_p1055_cap_p05", "max_op", 1.005, 1.055, False, True, 0.005, False),
        ("o1005_p1055_cap_p08", "max_op", 1.005, 1.055, False, True, 0.008, False),
        ("o1015_p1065_cap_p05", "max_op", 1.015, 1.065, False, True, 0.005, False),
    ]

    res12_grid, dr12_grid, slot12_grid = {}, {}, {}
    for lbl, tm, om, pm, f0, km, cp, fpb in grid_12_specs + cap_12_specs:
        d15, dr, sl = eval_1to2_variant(df12_all, bars_5m, dmap, cal_5y, dt_idx_5y, sh300, all_sh_dts, tm, om, pm, f0, km, cp, fpb)
        res12_grid[lbl] = d15
        if lbl in [x[0] for x in grid_12_specs[:9]]:
            dr12_grid[lbl] = dr
            slot12_grid[lbl] = sl

    # Parity assert vs Part 1 1to2 baseline (92 trades / 264.4965x)
    c12_full = res12_grid["current_o1012_p1065"]["windows"]["FULL"]
    assert c12_full["trades"] == 92 and abs(c12_full["nav_1s"] - 264.4965) < 0.02, c12_full
    print(f"  [1to2 Parity PASS] trades={c12_full['trades']}, FULL={c12_full['nav_1s']:.4f}x, OOS={res12_grid['current_o1012_p1065']['windows']['OOS']['nav_1s']:.4f}x")
    pbo12 = calc_cscv_pbo_matrix(dr12_grid, "current_o1012_p1065", cal_5y, slot12_grid, "net_ret")
    verdict12 = check_recommendation(res12_grid, "current_o1012_p1065", pbo12["daily_mtm_cscv"]["S10"]["pbo_pct"], pbo12["exit_date_cscv"]["S10"]["pbo_pct"])

    # =========================================================================
    # 2. 三进四 V4.1
    # =========================================================================
    print("[3/4] Building & testing 3to4 V4.1 full pool (128 rows / 123 dates)...")
    df34_all = build_3to4_full_pool(bars_5m, dmap)
    grid_34_specs = [
        ("auc_0925", 1.000, True, None, False),
        ("max_p1050_o", 1.050, False, None, False),
        ("max_p1055_o", 1.055, False, None, False),
        ("max_p1060_o", 1.060, False, None, False),
        ("current_p1065_o", 1.065, False, None, False),
        ("max_p1070_o", 1.070, False, None, False),
        ("max_p1075_o", 1.075, False, None, False),
        ("max_p1080_o", 1.080, False, None, False),
    ]
    cap_34_specs = [
        ("current_cap_p05", 1.065, False, 0.005, False),
        ("current_cap_p08", 1.065, False, 0.008, False),
        ("current_cap_p10_vel", 1.065, False, 0.010, False),
        ("current_cap_p10_fastpb", 1.065, False, 0.010, True),
        ("p1055_cap_p05", 1.055, False, 0.005, False),
        ("p1055_cap_p08", 1.055, False, 0.008, False),
        ("p1070_cap_p05", 1.070, False, 0.005, False),
    ]

    res34_grid, dr34_grid, slot34_grid = {}, {}, {}
    for lbl, pm, f0, cp, fpb in grid_34_specs + cap_34_specs:
        d15, dr, sl = eval_3to4_variant(df34_all, bars_5m, dmap, cal_5y, dt_idx_5y, sh300, all_sh_dts, pm, f0, cp, fpb)
        res34_grid[lbl] = d15
        if lbl in [x[0] for x in grid_34_specs]:
            dr34_grid[lbl] = dr
            slot34_grid[lbl] = sl

    c34_full = res34_grid["current_p1065_o"]["windows"]["FULL"]
    assert c34_full["trades"] == 95 and abs(c34_full["nav_1s"] - 376.4798) < 0.05, c34_full
    print(f"  [3to4 Parity PASS] trades={c34_full['trades']}, FULL={c34_full['nav_1s']:.4f}x, OOS={res34_grid['current_p1065_o']['windows']['OOS']['nav_1s']:.4f}x")
    pbo34 = calc_cscv_pbo_matrix(dr34_grid, "current_p1065_o", cal_5y, slot34_grid, "net_ret")
    verdict34 = check_recommendation(res34_grid, "current_p1065_o", pbo34["daily_mtm_cscv"]["S10"]["pbo_pct"], pbo34["exit_date_cscv"]["S10"]["pbo_pct"])

    # =========================================================================
    # 3. 高标首阴 V5.1
    # =========================================================================
    print("[4/4] Building & testing High V5.1 full pool (52 rows incl. 28 green opens & 6 untriggered)...")
    dfh_all = build_high_full_pool(bars_5m, dmap)
    grid_h_specs = [
        ("auc_0925_all", 1.000, True, None, False),
        ("green_o1005_m100", 1.005, False, None, False),
        ("green_o1010_m050", 1.010, False, None, False),
        ("current_o1015", 1.015, False, None, False),
        ("green_o1020_p050", 1.020, False, None, False),
        ("green_o1025_p100", 1.025, False, None, False),
    ]
    cap_h_specs = [
        ("current_cap_p05", 1.015, False, 0.005, False),
        ("current_cap_p08", 1.015, False, 0.008, False),
        ("current_cap_p10_vel", 1.015, False, 0.010, False),
        ("current_cap_p10_fastpb", 1.015, False, 0.010, True),
        ("green_o1005_cap_p05", 1.005, False, 0.005, False),
        ("green_o1010_cap_p05", 1.010, False, 0.005, False),
    ]

    high_by_cb = {}
    for cbm in ("Matched42CB", "NoCB", "CausalCB"):
        rh_grid, drh_grid, sloth_grid = {}, {}, {}
        for lbl, gm, f0, cp, fpb in grid_h_specs + cap_h_specs:
            d15, dr, sl = eval_high_variant(dfh_all, bars_5m, dmap, cal_5y, dt_idx_5y, sh300, all_sh_dts, gm, f0, cp, fpb, cb_mode=cbm)
            rh_grid[lbl] = d15
            if lbl in [x[0] for x in grid_h_specs]:
                drh_grid[lbl] = dr
                sloth_grid[lbl] = sl
        pbo_h = calc_cscv_pbo_matrix(drh_grid, "current_o1015", cal_5y, sloth_grid, "net_ret")
        verdict_h = check_recommendation(rh_grid, "current_o1015", pbo_h["daily_mtm_cscv"]["S10"]["pbo_pct"], pbo_h["exit_date_cscv"]["S10"]["pbo_pct"])
        high_by_cb[cbm] = {"grid": rh_grid, "cscv_pbo": pbo_h, "verdict": verdict_h}

    ch_full = high_by_cb["Matched42CB"]["grid"]["current_o1015"]["windows"]["FULL"]
    assert ch_full["trades"] == 42 and abs(ch_full["nav_1s"] - 12.8943) < 0.02, ch_full
    print(f"  [High Parity PASS] Matched42CB trades={ch_full['trades']}, FULL={ch_full['nav_1s']:.4f}x | NoCB trades={high_by_cb['NoCB']['grid']['current_o1015']['windows']['FULL']['trades']}, FULL={high_by_cb['NoCB']['grid']['current_o1015']['windows']['FULL']['nav_1s']:.4f}x")

    summary = sanitize_json({
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 2),
            "yfinance_imported": "yfinance" in sys.modules,
            "windows_definition": {wn: f"{sd} ~ {ed}" for wn, sd, ed in CANON_WINDOWS},
            "pool_sizes": {
                "1to2_v20": {"passing_rows": int(len(df12_all)), "top1_dates": int(len(df12_top1)), "currently_untriggered_top1": 54, "missing_5m": 0},
                "3to4_v41": {"passing_rows": int(len(df34_all)), "unique_dates": int(df34_all["buy_date"].nunique()), "currently_untriggered": 13, "missing_5m": 0},
                "high_v51": {"passing_rows": int(len(dfh_all)), "red_flat_0925": int(dfh_all["is_red_flat"].sum()), "green_opens": int((~dfh_all["is_red_flat"]).sum()), "currently_untriggered_green": 6, "missing_5m": 0},
            },
        },
        "s1_1to2_v20": {"grid": res12_grid, "cscv_pbo": pbo12, "verdict": verdict12},
        "s2_3to4_v41": {"grid": res34_grid, "cscv_pbo": pbo34, "verdict": verdict34},
        "s3_high_v51": {
            "primary_matched42cb": high_by_cb["Matched42CB"],
            "nocb_continuous": high_by_cb["NoCB"],
            "causal_cb": high_by_cb["CausalCB"],
        },
    })

    raw_json = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)
    low_j = raw_json.lower()
    assert "cap10m" not in low_j and "cap1000w" not in low_j and "1000万" not in raw_json, "FORBIDDEN string found!"
    assert "yfinance" not in sys.modules, "D12 VIOLATION!"

    out_json = f"{OUT_DIR}/part2_trigger_summary.json"
    with open(out_json, "w", encoding="utf-8") as f:
        f.write(raw_json)
    print(f"DONE in {summary['meta']['elapsed_sec']}s -> {out_json} ({len(raw_json)} bytes)")


if __name__ == "__main__":
    main()
