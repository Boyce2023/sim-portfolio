#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_task1_rolling_leapfrog.py — Task 1: V20 Portfolio Mechanism 1 Audit
Causal Rolling Sharpe & Rolling Win-Rate + Confidence Leapfrog (>=1.50 / 2.00 / 2.50,
Unrestricted vs Tier1-Protected vs 0925-Protected, Warmup-guarded vs Fallback) on V22.
Zero yfinance (D12). Read-only on production scripts.
"""
import json
import math
import os
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

import _audit_utils as au


def _build_1to2_thr_lookup(c_p2: dict) -> dict[tuple[str, str], float]:
    d12 = c_p2["pools_ext"]["1to2"]
    lu = {}
    date_thr = {}
    for r in d12[["buy_date", "code", "thr_vec"]].itertuples(index=False):
        bd = str(r.buy_date)[:10]
        c6 = str(r.code).zfill(6)
        tv = float(r.thr_vec) if pd.notna(r.thr_vec) else 304.8
        lu[(bd, c6)] = tv
        date_thr[bd] = tv
    return lu, date_thr


def _build_standalone_history(mp: pd.DataFrame, thr12_lu: dict, date12_thr: dict) -> dict[str, list[tuple[str, float, float]]]:
    """
    Build strictly causal standalone passing triggered history per strategy:
    list of (exit_date, buy_date, score_excess, net_ret) sorted by (exit_date, buy_date, code).
    """
    # Use daily top-1 standalone triggered per strategy (matching seasonal_rolling_sr_state.json semantics)
    hist: dict[str, list[tuple[str, float, float]]] = {}
    trig = mp[~mp["is_untrig"]].copy()
    for st, grp in trig.groupby("strategy"):
        if st == "4to5":
            continue
        # Daily top-1 standalone passing trade
        srt = grp.sort_values(["buy_date", "s2c_prio", "score", "buy_hhmm", "code"], ascending=[True, True, False, True, True], kind="mergesort")
        top1 = srt.groupby("buy_date", as_index=False).first()
        # Sort by exit_date for strictly causal bisect/lookup exit_date < dt
        recs = []
        for r in top1.itertuples(index=False):
            sc = float(r.score)
            thr = {
                "3to4": 90.0, "high": 88.0, "pry": 165.0, "2to3": 90.0, "20cm": 80.0,
            }.get(st, thr12_lu.get((str(r.buy_date)[:10], str(r.code).zfill(6)), date12_thr.get(str(r.buy_date)[:10], 304.8)))
            recs.append((str(r.exit_date)[:10], str(r.buy_date)[:10], sc, thr, float(r.net_ret)))
        recs.sort(key=lambda x: (x[0], x[1]))
        hist[st] = recs
    return hist


def _precompute_daily_strategy_stats(
    cal_5y: list[str],
    hist: dict[str, list[tuple[str, float, float]]],
    metric_mode: str = "sr",
    recent_ddof: int = 1,
    wr_scale: float = 1.0,
) -> dict[tuple[str, str], dict]:
    """Strictly causal (exit_date < dt) expanding std, prior SR/WR, recent-10 SR/WR, blended weight."""
    stats_lu: dict[tuple[str, str], dict] = {}
    for st, recs in hist.items():
        ptr = 0
        n_tot = len(recs)
        scores_closed: list[float] = []
        rets_closed: list[float] = []
        for dt in cal_5y:
            while ptr < n_tot and recs[ptr][0] < dt:
                _, _, sc, _, nr = recs[ptr]
                scores_closed.append(sc)
                rets_closed.append(nr)
                ptr += 1
            nc = len(rets_closed)
            if nc >= 5:
                sc_std = max(1.0, float(np.std(scores_closed, ddof=1)))
            else:
                sc_std = 10.0

            if metric_mode == "sr":
                if nc >= 5:
                    s_all = float(np.std(rets_closed, ddof=1))
                    prior_m = float(np.clip(np.mean(rets_closed) / s_all, -2.0, 3.0)) if s_all > 1e-6 else 0.0
                    r10 = rets_closed[-10:]
                    s10 = float(np.std(r10, ddof=recent_ddof)) if len(r10) >= 3 else s_all
                    rec10_m = float(np.clip(np.mean(r10) / s10, -2.0, 3.0)) if s10 > 1e-6 else prior_m
                    blended = 0.5 * prior_m + 0.5 * rec10_m
                else:
                    blended = 0.5
            elif metric_mode == "wr":
                if nc >= 5:
                    wins = [1.0 if r > 0.0 else 0.0 for r in rets_closed]
                    prior_m = float(np.mean(wins))
                    rec10_m = float(np.mean(wins[-10:]))
                    blended = (0.5 * prior_m + 0.5 * rec10_m) * wr_scale
                else:
                    blended = 0.5 * wr_scale
            elif metric_mode == "wr_centered":
                if nc >= 5:
                    wins = [1.0 if r > 0.0 else 0.0 for r in rets_closed]
                    prior_m = float(np.mean(wins))
                    rec10_m = float(np.mean(wins[-10:]))
                    blended = (0.5 * prior_m + 0.5 * rec10_m - 0.5) * wr_scale
                else:
                    blended = 0.0
            else:
                raise ValueError(metric_mode)

            stats_lu[(dt, st)] = {"n_closed": nc, "std": sc_std, "blended": blended}
    return stats_lu


def _subslot_key(row) -> str:
    st = str(row.strategy)
    if st in ("3to4", "high"):
        if str(row.tier) in ("3to4_S(>=102)", "high_S(>=96)"):
            return f"{st}_S"
        return f"{st}_Ad" if int(row.buy_hhmm) == 925 else f"{st}_Ac"
    if st == "1to2":
        return "1to2_d" if int(row.buy_hhmm) == 925 else "1to2_c"
    return st


def run_leapfrog_sim(
    mp: pd.DataFrame,
    cal_5y: list[str],
    stats_lu: dict[tuple[str, str], dict],
    thr12_lu: dict[tuple[str, str], float],
    date12_thr: dict[str, float],
    delta_thr: float = 1.50,
    protect_tier1: bool = False,
    protect_0925: bool = False,
    min_closed: int = 0,
    strict_3tier: bool = False,
) -> dict:
    """Exact causal V22 single-slot simulation with V20 rk_prio confidence leapfrog."""
    df = mp.copy()
    is_45 = (df["strategy"] == "4to5").to_numpy(bool)
    is_t1 = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"]).to_numpy(bool)
    is_p0 = (df["buy_hhmm"].to_numpy(int) == 925) | is_t1
    s2c_p = df["s2c_prio"].to_numpy(int)
    if strict_3tier:
        base_rk = np.where(is_t1, s2c_p, np.where(is_p0, 10 + s2c_p, 100 + s2c_p))
    else:
        base_rk = np.where(is_p0, s2c_p, 100 + s2c_p)
    df["rk"] = np.where(is_45, 900, base_rk)
    df["is_t1"] = is_t1
    df["subslot"] = [_subslot_key(r) for r in df.itertuples(index=False)]

    # Pre-sort identically to p5.run_priority_sim
    df = df.sort_values(["buy_date", "rk", "score", "buy_hhmm", "code"], ascending=[True, True, False, True, True], kind="mergesort").reset_index(drop=True)
    by_dt: dict[str, list] = {}
    cols = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "bucket", "score", "net_ret", "mtm_use", "is_untrig", "rk", "is_t1", "subslot"]
    for r in df[cols].itertuples(index=False, name="Row"):
        by_dt.setdefault(r.buy_date, []).append(r)

    def _calc_rk_prio(r, dt: str) -> tuple[float, int]:
        st = r.strategy
        info = stats_lu.get((dt, st), {"n_closed": 0, "std": 10.0, "blended": 0.5})
        thr = {
            "3to4": 90.0, "high": 88.0, "pry": 165.0, "2to3": 90.0, "20cm": 80.0,
        }.get(st, thr12_lu.get((r.buy_date, r.code), date12_thr.get(r.buy_date, 304.8)))
        sc = float(r.score)
        if st == "1to2" and sc < thr:
            z = (sc - 295.0) / info["std"] - 5.0
        else:
            z = (sc - thr) / info["std"]
        return round(z + info["blended"], 6), int(info["n_closed"])

    taken = []
    waits = []
    leap_events = []
    cur_ed, cur_eh = "", 0

    for dt in cal_5y:
        grp = by_dt.get(dt)
        if not grp:
            continue
        elig = [r for r in grp if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and r.buy_hhmm > cur_eh)]
        if not elig:
            continue

        elig_v21 = [r for r in elig if r.strategy != "4to5"]
        if not elig_v21:
            chosen = elig[0]  # 4to5 empty-fill Pos5
        else:
            # Build top_all (top-1 per subslot by Base order, matching daily_3strategies_score_report L447-484)
            seen_sub = set()
            top_all = []
            for r in elig_v21:
                if r.subslot not in seen_sub:
                    seen_sub.add(r.subslot)
                    rk_p, n_cl = _calc_rk_prio(r, dt)
                    top_all.append((r, rk_p, n_cl))

            by_ord_r, by_ord_rk, by_ord_nc = top_all[0]
            chosen = by_ord_r
            if delta_thr < 900.0 and len(top_all) >= 2:
                # Pick highest rk_prio; tie-break by Base order
                by_conv_r, by_conv_rk, by_conv_nc = max(top_all, key=lambda x: (x[1], -x[0].rk))
                can_jump = (by_conv_r is not by_ord_r) and ((by_conv_rk - by_ord_rk) >= delta_thr - 1e-12)
                if can_jump and protect_tier1 and by_ord_r.is_t1:
                    can_jump = False
                if can_jump and protect_0925 and (int(by_ord_r.buy_hhmm) == 925) and (int(by_conv_r.buy_hhmm) > 925):
                    can_jump = False
                if can_jump and min_closed > 0 and ((by_ord_nc < min_closed) or (by_conv_nc < min_closed)):
                    can_jump = False
                if can_jump:
                    chosen = by_conv_r
                    leap_events.append({
                        "date": dt,
                        "from_strat": by_ord_r.strategy, "from_code": by_ord_r.code, "from_score": float(by_ord_r.score),
                        "from_rk": round(by_ord_rk, 3), "from_untrig": bool(by_ord_r.is_untrig), "from_ret": round(float(by_ord_r.net_ret) * 100.0, 2),
                        "to_strat": by_conv_r.strategy, "to_code": by_conv_r.code, "to_score": float(by_conv_r.score),
                        "to_rk": round(by_conv_rk, 3), "to_untrig": bool(by_conv_r.is_untrig), "to_ret": round(float(by_conv_r.net_ret) * 100.0, 2),
                    })

        if chosen.is_untrig:
            waits.append({"buy_date": chosen.buy_date, "strategy": chosen.strategy, "code": chosen.code, "score": float(chosen.score)})
        else:
            taken.append(chosen)
        cur_ed, cur_eh = chosen.exit_date, int(chosen.exit_hhmm)

    T = len(cal_5y)
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    day_mult = np.ones(T, dtype=float)
    for r in taken:
        segs = r.mtm_use
        if segs:
            for ti, mult in segs:
                if 0 <= int(ti) < T:
                    day_mult[int(ti)] *= float(mult)
        else:
            bi, ei = idx_5y.get(r.buy_date), idx_5y.get(r.exit_date)
            if bi is not None and ei is not None and ei > bi:
                span = ei - bi + 1
                day_mult[bi : ei + 1] *= (1.0 + float(r.net_ret)) ** (1.0 / span)

    dr_5y = day_mult - 1.0
    tr_df = pd.DataFrame([{
        "buy_date": r.buy_date, "buy_hhmm": r.buy_hhmm, "exit_date": r.exit_date, "exit_hhmm": r.exit_hhmm,
        "code": r.code, "name": r.name, "strategy": r.strategy, "tier": r.tier, "bucket": r.bucket,
        "score": r.score, "net_ret": r.net_ret, "mtm_use": r.mtm_use,
    } for r in taken])

    nav_5y_tr = float(np.prod(1.0 + tr_df["net_ret"].to_numpy(float))) if not tr_df.empty else 1.0
    mtm_diff_5y = abs(float(np.prod(day_mult)) - nav_5y_tr)
    wf_off = idx_5y[au.v22.eng.WF_START]
    dr_wf = dr_5y[wf_off:]
    tr_wf = tr_df[tr_df["buy_date"] >= au.v22.eng.WF_START] if not tr_df.empty else tr_df
    nav_wf_tr = float(np.prod(1.0 + tr_wf["net_ret"].to_numpy(float))) if not tr_wf.empty else 1.0
    mtm_diff_wf = abs(float(np.prod(1.0 + dr_wf)) - nav_wf_tr)

    return {
        "trades_df": tr_df, "waits": waits, "dr_5y": dr_5y, "dr_wf": dr_wf,
        "mtm_diff_5y": mtm_diff_5y, "mtm_diff_wf": mtm_diff_wf, "leap_events": leap_events,
    }


def main():
    t0 = time.time()
    assets = au.load_all_assets()
    cal_5y = assets["cal_5y"]
    thr12_lu, date12_thr = _build_1to2_thr_lookup(assets["c_p2"])

    hist030 = _build_standalone_history(assets["mp030"], thr12_lu, date12_thr)
    hist050 = _build_standalone_history(assets["mp050"], thr12_lu, date12_thr)
    histpt = _build_standalone_history(assets["mp_pt030"], thr12_lu, date12_thr)

    stats_modes = {
        "SR_d1": (_precompute_daily_strategy_stats(cal_5y, hist030, "sr", 1), _precompute_daily_strategy_stats(cal_5y, hist050, "sr", 1), _precompute_daily_strategy_stats(cal_5y, histpt, "sr", 1)),
        "SR_d0": (_precompute_daily_strategy_stats(cal_5y, hist030, "sr", 0), _precompute_daily_strategy_stats(cal_5y, hist050, "sr", 0), _precompute_daily_strategy_stats(cal_5y, histpt, "sr", 0)),
        "WR_01": (_precompute_daily_strategy_stats(cal_5y, hist030, "wr", 1, 1.0), _precompute_daily_strategy_stats(cal_5y, hist050, "wr", 1, 1.0), _precompute_daily_strategy_stats(cal_5y, histpt, "wr", 1, 1.0)),
        "WR_c2": (_precompute_daily_strategy_stats(cal_5y, hist030, "wr_centered", 1, 2.0), _precompute_daily_strategy_stats(cal_5y, hist050, "wr_centered", 1, 2.0), _precompute_daily_strategy_stats(cal_5y, histpt, "wr_centered", 1, 2.0)),
    }

    # Verify delta_thr=999 reproduces Base exactly
    chk = run_leapfrog_sim(assets["mp030"], cal_5y, stats_modes["SR_d1"][0], thr12_lu, date12_thr, delta_thr=999.0)
    assert len(chk["trades_df"]) == len(assets["base_030"]["trades_df"]) == 276
    assert float(np.max(np.abs(chk["dr_5y"] - assets["base_030"]["dr_5y"]))) < 1e-12

    specs = []
    # 1. Exact V20 SR (ddof=1 & ddof=0) and WR across 1.50 / 2.00 / 2.50, Unrestricted vs ProtectTier1 vs Protect0925
    for mname in ("SR_d1", "WR_01", "WR_c2"):
        for dthr in (1.50, 2.00, 2.50):
            specs.append((f"T1_{mname}_Unres_{dthr:.2f}", mname, dthr, False, False, 10, f"Causal {mname} Unrestricted leap>={dthr:.2f} (warmup>=10)"))
            specs.append((f"T1_{mname}_ProtT1_{dthr:.2f}", mname, dthr, True, False, 10, f"Causal {mname} ProtectTier1 leap>={dthr:.2f} (warmup>=10)"))
            if dthr == 1.50:
                specs.append((f"T1_{mname}_ProtT1_925_{dthr:.2f}", mname, dthr, True, True, 10, f"Causal {mname} ProtectTier1+0925 leap>={dthr:.2f} (warmup>=10)"))
                specs.append((f"T1_{mname}_Unres_NoWarm_{dthr:.2f}", mname, dthr, False, False, 0, f"Causal {mname} Unrestricted leap>={dthr:.2f} (no warmup guard)"))
    # Also add SR_d0 (V20 ddof=0 quirk) at 1.50 & 2.00
    specs.append(("T1_SR_d0_Unres_1.50", "SR_d0", 1.50, False, False, 10, "Causal SR_ddof0 Unrestricted leap>=1.50 (warmup>=10)"))
    specs.append(("T1_SR_d0_ProtT1_1.50", "SR_d0", 1.50, True, False, 10, "Causal SR_ddof0 ProtectTier1 leap>=1.50 (warmup>=10)"))

    results = {}
    rows = []
    for vid, mname, dthr, pt1, p925, mc, desc in specs:
        st030, st050, stpt = stats_modes[mname]
        s030 = run_leapfrog_sim(assets["mp030"], cal_5y, st030, thr12_lu, date12_thr, delta_thr=dthr, protect_tier1=pt1, protect_0925=p925, min_closed=mc)
        s050 = run_leapfrog_sim(assets["mp050"], cal_5y, st050, thr12_lu, date12_thr, delta_thr=dthr, protect_tier1=pt1, protect_0925=p925, min_closed=mc)
        spt = run_leapfrog_sim(assets["mp_pt030"], cal_5y, stpt, thr12_lu, date12_thr, delta_thr=dthr, protect_tier1=pt1, protect_0925=p925, min_closed=mc)
        ev = au.evaluate_variant_complete(vid, "TASK1_ROLLING_LEAPFROG", desc, s030, s050, spt, assets, n_perm=1000)
        ev["n_leap_events"] = len(s030["leap_events"])
        ev["leap_events_sample"] = s030["leap_events"][:15]
        ev["row"]["n_leaps"] = len(s030["leap_events"])
        results[vid] = ev
        rows.append(ev["row"])

    df_res = pd.DataFrame(rows)
    df_res.to_csv(f"{au.OUT_DIR}/task1_rolling_leapfrog.csv", index=False, encoding="utf-8-sig")
    out_json = au.v22.sanitize_json({
        "task": "Task 1: V20 Seasonal Rolling WR/Sharpe + Confidence Leapfrog",
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "pass_all_4_gates": [r["variant"] for r in rows if r["PASS_ALL_4_GATES"]],
        "rows": rows,
        "details": results,
    })
    with open(f"{au.OUT_DIR}/task1_rolling_leapfrog.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)

    cols = ["variant", "n_trades", "n_leaps", "5Y_nav", "5Y_mdd", "5Y_sh", "IS_nav", "OOS_nav", "WF_nav", "Y26_nav", "ex_both_5Y", "ex_both_WF", "ex_both_IS", "ex_both_OOS", "PASS_ALL_4_GATES"]
    print(df_res[cols].to_string(index=False))
    print("TASK 1 PASSERS:", [r["variant"] for r in rows if r["PASS_ALL_4_GATES"]])


if __name__ == "__main__":
    main()
