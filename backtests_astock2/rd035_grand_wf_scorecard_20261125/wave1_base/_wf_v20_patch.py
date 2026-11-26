#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 V20.0 Empty-Slot Patch Simulator:
  1. `strict_combined_no_peek`: chronological single-slot collision simulation giving V20.0 priority
     when free, and naturally skipping later V20.0 signals while an entered patch trade is still held
     (ZERO peeking at `future_free_days`!).
  2. `empty_slot_standalone`: pure empty-day standalone performance + exact collision diagnostics.
Zero yfinance (D12).
"""
import json
import os
from typing import Optional

import numpy as np
import pandas as pd

import _wf_sim_and_metrics as wfm

DEFAULT_BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"


def load_v20_reference_context(base_dir: str = DEFAULT_BASE_DIR) -> dict:
    """Fast zero-DB load of V20.0 5Y slot calendar, benchmark, 278-trade ledger, and 41 wait events."""
    cal_5y = pd.read_parquet(f"{base_dir}/v20_daily_slot_calendar_5y.parquet")
    cal_ext = pd.read_parquet(f"{base_dir}/v20_daily_slot_calendar_to_20261125.parquet")
    bench = pd.read_parquet(f"{base_dir}/v20_daily_bench_20210104_20261125.parquet")
    ledger = pd.read_parquet(f"{base_dir}/v20_baseline_ledger_278.parquet")
    with open(f"{base_dir}/v20_waits_41.json", encoding="utf-8") as f:
        waits = json.load(f)
    with open(f"{base_dir}/v20_baseline_parity.json", encoding="utf-8") as f:
        parity = json.load(f)
    ledger["mtm_pairs"] = [json.loads(s) for s in ledger["mtm_pairs_json"]]
    return {
        "calendar_5y": cal_5y,
        "calendar_ext": cal_ext,
        "bench": bench,
        "v20_ledger": ledger,
        "v20_waits": waits,
        "parity": parity,
    }


def _build_combined_mtm(
    tr_df: pd.DataFrame,
    cal_dts: list[str],
    patch_mtm_col: Optional[str] = None,
) -> tuple[np.ndarray, float]:
    T = len(cal_dts)
    if tr_df.empty:
        return np.zeros(T, dtype=float), 0.0
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    day_mult = np.ones(T, dtype=float)
    for r in tr_df.itertuples(index=False):
        if r.source == "v20" and hasattr(r, "mtm_pairs") and r.mtm_pairs:
            for d_str, mult in r.mtm_pairs:
                ti = dt_idx.get(d_str)
                if ti is not None:
                    day_mult[ti] *= float(mult)
        elif r.source == "patch" and patch_mtm_col and hasattr(r, patch_mtm_col):
            for ti, mult in getattr(r, patch_mtm_col):
                if 0 <= ti < T:
                    day_mult[ti] *= float(mult)
        else:
            bi = dt_idx.get(str(r.buy_date))
            ei = dt_idx.get(str(r.exit_date))
            if bi is None:
                continue
            if ei is None or ei <= bi:
                day_mult[bi] *= (1.0 + float(r.net_ret))
            else:
                span = ei - bi + 1
                day_mult[bi:ei + 1] *= (1.0 + float(r.net_ret)) ** (1.0 / span)
    dr = day_mult - 1.0
    tr_sub = tr_df[tr_df["buy_date"].isin(dt_idx)]
    tr_nav = float(np.prod(1.0 + tr_sub["net_ret"].to_numpy(float))) if not tr_sub.empty else 1.0
    return dr, abs(float(np.prod(day_mult)) - tr_nav)


def simulate_v20_empty_slot_patch(
    patch_candidates_df: pd.DataFrame,
    v20_ctx: Optional[dict] = None,
    wf_start_dt: str = "2023-01-03",
    end_dt: str = "2026-11-16",
    respect_stier_waits: bool = True,
    score_col: str = "wf_score",
    patch_mtm_col: Optional[str] = None,
) -> dict:
    """
    Honest dual-mode V20.0 empty-slot patch simulation (ZERO peeking at future_free_days).
    Input `patch_candidates_df`: passing buyable candidates (1 or multiple per day; highest score picked).
    """
    if v20_ctx is None:
        v20_ctx = load_v20_reference_context()

    cal_df = v20_ctx["calendar_5y"] if end_dt <= "2026-11-16" else v20_ctx["calendar_ext"]
    cal_win = cal_df[cal_df["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_arr = cal_win["csi300_daily_ret"].to_numpy(float)
    ew_arr = cal_win["alla_ew_daily_ret"].to_numpy(float)
    empty_set = set(cal_win.loc[cal_win["v20_empty_slot"], "trade_date"])
    if respect_stier_waits:
        empty_set -= set(cal_win.loc[cal_win["v20_has_stier_wait"], "trade_date"])

    # Normalize patch candidates (top-1 per day)
    p = patch_candidates_df.copy()
    p["buy_date"] = p["buy_date"].astype(str).str[:10]
    p["exit_date"] = p["exit_date"].astype(str).str[:10]
    p["code"] = p["code"].astype(str).str.zfill(6)
    p = p[p["buy_date"].between(wf_start_dt, end_dt) & (p["exit_date"] > p["buy_date"])].copy()
    if "buy_hhmm" not in p.columns:
        p["buy_hhmm"] = 925
    if "exit_hhmm" not in p.columns:
        p["exit_hhmm"] = 1500
    p["buy_hhmm"] = pd.to_numeric(p["buy_hhmm"], errors="coerce").fillna(925).astype(int)
    p["exit_hhmm"] = pd.to_numeric(p["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
    if score_col not in p.columns:
        p[score_col] = 100.0
    p_top1 = p.sort_values(["buy_date", score_col, "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()

    # --- Mode 2: Empty-Slot Standalone Observation ---
    p_emp = p_top1[p_top1["buy_date"].isin(empty_set)].sort_values("buy_date").reset_index(drop=True)
    _, patch_emp_slot = wfm.select_single_slot_trades(
        p_emp.assign(can_buy_hygiene=True), score_col=score_col, threshold=None, wf_only=False
    )

    v20_led = v20_ctx["v20_ledger"]
    v20_win = v20_led[v20_led["buy_date"].between(wf_start_dt, end_dt)].copy().reset_index(drop=True)
    v20_win["source"] = "v20"

    # Check how many standalone empty-slot trades collide with subsequent V20 trades
    n_collide = 0
    collided_v20_rets = []
    for pr in patch_emp_slot.itertuples(index=False):
        conf = v20_win[
            (v20_win["buy_date"] > pr.buy_date)
            & ((v20_win["buy_date"] < pr.exit_date) | ((v20_win["buy_date"] == pr.exit_date) & (v20_win["buy_hhmm"] <= int(pr.exit_hhmm))))
        ]
        if not conf.empty:
            n_collide += 1
            collided_v20_rets.extend(conf["net_ret"].to_numpy(float).tolist())

    dr_emp, _ = wfm.build_daily_mtm_returns(patch_emp_slot, cal_dts, mtm_col=patch_mtm_col)
    wins = [
        ("FULL_WF", wf_start_dt, end_dt),
        ("Y2023", max(wf_start_dt, "2023-01-01"), "2023-12-31"),
        ("Y2024", "2024-01-01", "2024-12-31"),
        ("Y2025", "2025-01-01", "2025-12-31"),
        ("Y2026", "2026-01-01", end_dt),
        ("Y2025_2026", "2025-01-01", end_dt),
    ]
    emp_metrics = {
        wn: wfm._calc_one_window(patch_emp_slot, p_emp, dr_emp, cal_dts, dt_idx, csi_arr, ew_arr, s, e)
        for wn, s, e in wins if s <= e
    }

    # --- Mode 1: Strict Combined No-Peek Collision Simulation ---
    events = []
    for r in v20_win.itertuples(index=False):
        events.append({
            "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm), "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
            "code": r.code, "strategy": r.strategy, "net_ret": float(r.net_ret),
            "prio_src": 0, "is_wait": False, "source": "v20", "mtm_pairs": r.mtm_pairs,
        })
    if respect_stier_waits:
        for w in v20_ctx["v20_waits"]:
            if wf_start_dt <= w["buy_date"] <= end_dt and w["wait_tier"] in ("3to4_S(>=102)", "high_S(>=96)"):
                events.append({
                    "buy_date": w["buy_date"], "buy_hhmm": 935, "exit_date": w["buy_date"], "exit_hhmm": int(w["cancel_hhmm"]),
                    "code": w["wait_code"], "strategy": w["wait_strategy"], "net_ret": 0.0,
                    "prio_src": 0, "is_wait": True, "source": "v20_wait", "mtm_pairs": [],
                })
    for r in p_top1.itertuples(index=False):
        rec = {
            "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm), "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
            "code": r.code, "strategy": "patch", "net_ret": float(r.net_ret),
            "prio_src": 1, "is_wait": False, "source": "patch", "mtm_pairs": [],
        }
        if patch_mtm_col and hasattr(r, patch_mtm_col):
            rec[patch_mtm_col] = getattr(r, patch_mtm_col)
        events.append(rec)

    ev_df = pd.DataFrame(events).sort_values(["buy_date", "prio_src", "buy_hhmm", "code"], ascending=[True, True, True, True]).reset_index(drop=True)
    # Note: if a V20 trade opens on date d (even at 935/1000 intraday) and a patch trade proposes 925 on date d,
    # v20_empty_slot[d] is ALREADY False so patch NEVER opens on a day V20 opens (V20 always holds priority).
    taken_comb = []
    skipped_v20 = []
    cur_ed, cur_eh = "", 0
    for r in ev_df.itertuples(index=False):
        if r.source == "patch" and r.buy_date not in empty_set:
            continue
        can_enter = (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh)
        if can_enter:
            if not r.is_wait:
                taken_comb.append(r._asdict())
            cur_ed, cur_eh = r.exit_date, int(r.exit_hhmm)
        elif r.source == "v20":
            skipped_v20.append({"buy_date": r.buy_date, "code": r.code, "strategy": r.strategy, "net_ret": float(r.net_ret)})

    comb_df = pd.DataFrame(taken_comb) if taken_comb else pd.DataFrame(columns=["buy_date", "exit_date", "code", "strategy", "net_ret", "source", "mtm_pairs"])
    dr_comb, _ = _build_combined_mtm(comb_df, cal_dts, patch_mtm_col=patch_mtm_col)
    dr_v20_base, _ = _build_combined_mtm(v20_win, cal_dts)

    comb_metrics = {wn: wfm._calc_one_window(comb_df, None, dr_comb, cal_dts, dt_idx, csi_arr, ew_arr, s, e) for wn, s, e in wins if s <= e}
    v20_metrics = {wn: wfm._calc_one_window(v20_win, None, dr_v20_base, cal_dts, dt_idx, csi_arr, ew_arr, s, e) for wn, s, e in wins if s <= e}

    c_fw, b_fw = comb_metrics["FULL_WF"], v20_metrics["FULL_WF"]
    n_patch_in_comb = int((comb_df["source"] == "patch").sum()) if not comb_df.empty else 0
    return {
        "wf_window": f"{wf_start_dt} ~ {end_dt}",
        "mode1_strict_combined_no_peek": {
            "v20_baseline": v20_metrics,
            "combined_with_patch": comb_metrics,
            "n_v20_kept": int((comb_df["source"] == "v20").sum()) if not comb_df.empty else 0,
            "n_patch_added": n_patch_in_comb,
            "n_v20_skipped_by_collision": int(len(skipped_v20)),
            "skipped_v20_net_ret_prod": round(float(np.prod(1.0 + np.array([x["net_ret"] for x in skipped_v20]))) if skipped_v20 else 1.0, 4),
            "skipped_v20_trades": skipped_v20,
            "delta_nav_ratio_full_wf": round(c_fw["nav"] / max(1e-9, b_fw["nav"]), 4),
            "delta_sharpe_full_wf": round(c_fw["daily_sharpe"] - b_fw["daily_sharpe"], 4),
            "delta_mdd_pp_full_wf": round(c_fw["daily_mdd_pct"] - b_fw["daily_mdd_pct"], 2),
        },
        "mode2_empty_slot_standalone": {
            "windows": emp_metrics,
            "n_standalone_empty_trades": int(len(patch_emp_slot)),
            "n_colliding_with_subsequent_v20": int(n_collide),
            "collision_rate_pct": round(n_collide / max(1, len(patch_emp_slot)) * 100.0, 2),
            "collided_v20_prod_impact": round(float(np.prod(1.0 + np.asarray(collided_v20_rets))) if collided_v20_rets else 1.0, 4),
        },
    }
