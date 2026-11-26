#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-5 Unified Metrics & V20.0 End-to-End Combined Evaluator.
Computes 5Y, 2023-2026, 2025-2026, 2026 metrics + ex5 + MDD + Sharpe + CSI300 Excess + 1000x Perm p-values.
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)

WAVE1 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
for p in (WAVE1, RD028):
    if p not in sys.path:
        sys.path.insert(0, p)

import _wf_sim_and_metrics as wfm
import _wf_v20_patch as wfp
import step4_mod_rules_and_sim as m1

WINDOWS_4 = [
    ("Y5", "2021-11-16", "2026-11-16"),
    ("WF_23_26", "2023-01-03", "2026-11-16"),
    ("OOS_25_26", "2025-01-01", "2026-11-16"),
    ("Y2026", "2026-01-01", "2026-11-16"),
]


def evaluate_ledger_windows(
    slot_df: pd.DataFrame,
    pass_df: pd.DataFrame | None,
    cand_pool_df: pd.DataFrame | None,
    ctx: dict,
    windows: list[tuple[str, str, str]] = WINDOWS_4,
    mtm_col: str | None = "mtm_5y",
    perm_n: int = 1000,
    seed: int = 20261125,
) -> dict:
    """Evaluate standalone or combined ledger across 4 canonical windows + 1000x permutation test."""
    bench_df = ctx["v20_ctx"]["bench"]
    cal_dts = ctx["cal_5y"]
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    b_sub = bench_df.set_index("trade_date").reindex(cal_dts)
    csi_arr = b_sub["csi300_daily_ret"].fillna(0.0).to_numpy(float)
    ew_arr = b_sub["alla_ew_daily_ret"].fillna(0.0).to_numpy(float)

    sdf = slot_df.copy()
    if not sdf.empty:
        sdf["buy_date"] = sdf["buy_date"].astype(str).str[:10]
        sdf["exit_date"] = sdf["exit_date"].astype(str).str[:10]
        sdf["code"] = sdf["code"].astype(str).str.zfill(6)
        sdf = sdf[sdf["buy_date"].between(cal_dts[0], cal_dts[-1])].copy().reset_index(drop=True)

    # Use segment MTM directly via m1.daily_mtm_from_segs if tuple-based mtm_5y exists
    if mtm_col and (not sdf.empty) and (mtm_col in sdf.columns):
        dr_full, mtm_diff = m1.daily_mtm_from_segs(sdf, len(cal_dts), mtm_col)
    else:
        dr_full, mtm_diff = wfm.build_daily_mtm_returns(sdf, cal_dts, mtm_col=None)

    pdf = None
    if pass_df is not None and not pass_df.empty:
        pdf = pass_df.copy()
        pdf["buy_date"] = pdf["buy_date"].astype(str).str[:10]
        pdf["code"] = pdf["code"].astype(str).str.zfill(6)
        pdf = pdf[pdf["buy_date"].between(cal_dts[0], cal_dts[-1])].copy()

    out = {"mtm_diff": round(float(mtm_diff), 8), "windows": {}}
    for wn, sdt, edt in windows:
        edt_c = min(edt, cal_dts[-1])
        if sdt > edt_c:
            continue
        m = wfm._calc_one_window(sdf, pdf, dr_full, cal_dts, dt_idx, csi_arr, ew_arr, sdt, edt_c)
        sub_w = sdf[sdf["buy_date"].between(sdt, edt_c)] if not sdf.empty else sdf
        if not sub_w.empty:
            ht = [
                max(1, dt_idx.get(str(r.exit_date), 0) - dt_idx.get(str(r.buy_date), 0))
                for r in sub_w.itertuples(index=False)
                if str(r.buy_date) in dt_idx and str(r.exit_date) in dt_idx
            ]
            m["avg_hold_td"] = round(float(np.mean(ht)) if ht else 1.0, 2)
        else:
            m["avg_hold_td"] = 0.0
        out["windows"][wn] = m

    if cand_pool_df is not None and not cand_pool_df.empty and perm_n > 0:
        cp = cand_pool_df.copy()
        cp["buy_date"] = cp["buy_date"].astype(str).str[:10]
        cp["code"] = cp["code"].astype(str).str.zfill(6)
        cp["can_buy_hygiene"] = True
        out["perm_5y"] = wfm.perm_test_trading_days(sdf, cp, cal_dts[0], cal_dts[-1], n_perm=perm_n, seed=seed)
        out["perm_wf"] = wfm.perm_test_trading_days(sdf, cp, "2023-01-03", cal_dts[-1], n_perm=perm_n, seed=seed)
    return out


def flatten_row(label: str, strat: str, tree_id: str, scope: str, ev: dict) -> dict:
    """Flatten 4-window metrics + perm into a crisp CSV-ready row."""
    row = {
        "label": label,
        "scope": scope,
        "strategy": strat,
        "exit_tree": tree_id,
    }
    for wn, _, _ in WINDOWS_4:
        w = ev["windows"].get(wn, {})
        row[f"{wn}_n"] = w.get("n", 0)
        row[f"{wn}_wr"] = w.get("wr_pct", 0.0)
        row[f"{wn}_plr"] = w.get("plr", 0.0)
        row[f"{wn}_mean"] = w.get("mean_pct", 0.0)
        row[f"{wn}_nav"] = w.get("nav", 1.0)
        row[f"{wn}_ex5"] = w.get("ex_top5_nav", 1.0)
        row[f"{wn}_mdd"] = w.get("daily_mdd_pct", 0.0)
        row[f"{wn}_sharpe"] = w.get("daily_sharpe", 0.0)
        row[f"{wn}_excess_csi_pp"] = w.get("excess_csi300_pp", 0.0)
        row[f"{wn}_hold_td"] = w.get("avg_hold_td", 0.0)
    p5 = ev.get("perm_5y", {})
    pw = ev.get("perm_wf", {})
    row["perm5y_sd_p"] = p5.get("same_day_p_nav", np.nan)
    row["perm5y_any_p"] = p5.get("any_cand_day_p_nav", np.nan)
    row["permwf_sd_p"] = pw.get("same_day_p_nav", np.nan)
    row["permwf_any_p"] = pw.get("any_cand_day_p_nav", np.nan)
    return row
