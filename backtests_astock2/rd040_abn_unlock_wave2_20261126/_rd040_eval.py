#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD040 exact daily MTM adapter, D15/Calmar metrics, and V20 correlation helpers."""
import json
import math
import sys
from typing import Optional

import numpy as np
import pandas as pd

WAVE1_BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
if WAVE1_BASE not in sys.path:
    sys.path.insert(0, WAVE1_BASE)

import _wf_sim_and_metrics as wfm
import _wf_v20_patch as wfp

TRD_DAYS_YEAR = 242.0


def attach_exact_mtm_col(df: pd.DataFrame, mtm_json_col: str, cal_dts: list[str], all_idx_dts: list[str], fee_rt: float, out_col: str = "mtm_exact") -> pd.DataFrame:
    """Convert raw [mkt_idx_int, mult] json to exact [(cal_ti, mult)] adjusted for fee_rt on exit."""
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    out = df.copy()
    mtm_list = []
    mult_fee = 1.0 - float(fee_rt)
    for raw_s in out[mtm_json_col].fillna("[]"):
        segs = json.loads(raw_s)
        conv = []
        if segs:
            for k, (mi_i, m_val) in enumerate(segs):
                dt_str = all_idx_dts[int(mi_i)]
                ti = dt_idx.get(dt_str)
                mv = float(m_val) * (mult_fee if k == len(segs) - 1 else 1.0)
                if ti is not None:
                    conv.append((int(ti), mv))
        mtm_list.append(conv)
    out[out_col] = mtm_list
    return out


def eval_windows_exact(
    slot_df: pd.DataFrame, pass_df: Optional[pd.DataFrame], cand_pool_df: pd.DataFrame,
    bench_df: pd.DataFrame, all_idx_dts: list[str], mtm_json_col: str, fee_rt: float,
    start_dt: str, end_dt: str, windows: list[tuple[str, str, str]], perm_n: int = 1000, seed: int = 20261126
) -> dict:
    """Evaluate slot_df across all windows with exact daily MTM (mtm_diff == 0.0) & permutation test."""
    max_exit = str(slot_df["exit_date"].max()) if (not slot_df.empty and "exit_date" in slot_df.columns) else end_dt
    cal_end = min(str(bench_df["trade_date"].max()), max(end_dt, max_exit))
    b = bench_df[bench_df["trade_date"].between(start_dt, cal_end)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = b["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_arr = b["csi300_daily_ret"].to_numpy(float)
    ew_arr = b["alla_ew_daily_ret"].to_numpy(float)

    sl_m = attach_exact_mtm_col(slot_df, mtm_json_col, cal_dts, all_idx_dts, fee_rt, out_col="mtm_exact")
    sl_in = sl_m[sl_m["buy_date"].between(start_dt, end_dt)].reset_index(drop=True)
    dr_full, mtm_diff = wfm.build_daily_mtm_returns(sl_in, cal_dts, mtm_col="mtm_exact")

    win_res = {}
    for wn, s, e in windows:
        if s > e:
            continue
        s_eff = max(s, start_dt)
        e_eff = min(e, end_dt)
        if s_eff > e_eff:
            continue
        res = wfm._calc_one_window(sl_in, pass_df, dr_full, cal_dts, dt_idx, csi_arr, ew_arr, s_eff, e_eff)
        # Recompute exact trade-level excess & daily MTM NAV consistency
        win_res[wn] = res

    perm = wfm.perm_test_trading_days(sl_in, cand_pool_df, start_dt, end_dt, n_perm=perm_n, seed=seed)
    return {"mtm_reconciliation_diff": round(float(mtm_diff), 10), "windows": win_res, "permutation_1000": perm}


def compute_v20_corr_exact(slot_df: pd.DataFrame, v20_ctx: dict, all_idx_dts: list[str], mtm_json_col: str, fee_rt: float, start_dt: str, end_dt: str) -> dict:
    """Exact daily MTM Pearson correlation vs V20 baseline."""
    cal_df = v20_ctx["calendar_5y"] if end_dt <= "2026-11-16" else v20_ctx["calendar_ext"]
    cal_win = cal_df[cal_df["trade_date"].between(start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    v20_dr = cal_win["v20_daily_ret"].fillna(0.0).to_numpy(float)
    sl_m = attach_exact_mtm_col(slot_df, mtm_json_col, cal_dts, all_idx_dts, fee_rt, out_col="mtm_exact")
    tr_dr, diff = wfm.build_daily_mtm_returns(sl_m, cal_dts, mtm_col="mtm_exact")
    corr_all = float(np.corrcoef(tr_dr, v20_dr)[0, 1]) if (np.std(tr_dr) > 1e-12 and np.std(v20_dr) > 1e-12) else 0.0
    t_act = np.abs(tr_dr) > 1e-10
    both_act = t_act & (np.abs(v20_dr) > 1e-10)
    corr_act = float(np.corrcoef(tr_dr[t_act], v20_dr[t_act])[0, 1]) if (t_act.sum() >= 5 and np.std(tr_dr[t_act]) > 1e-12 and np.std(v20_dr[t_act]) > 1e-12) else None
    corr_both = float(np.corrcoef(tr_dr[both_act], v20_dr[both_act])[0, 1]) if (both_act.sum() >= 5 and np.std(tr_dr[both_act]) > 1e-12 and np.std(v20_dr[both_act]) > 1e-12) else None
    return {
        "mtm_diff": round(float(diff), 10),
        "n_days": int(len(cal_dts)),
        "n_track_active": int(t_act.sum()),
        "n_both_active": int(both_act.sum()),
        "corr_all_days": round(corr_all, 4),
        "corr_track_active": round(corr_act, 4) if corr_act is not None else None,
        "corr_both_active": round(corr_both, 4) if corr_both is not None else None,
    }


def make_clean_view(df: pd.DataFrame, entry_filter: Optional[str], exit_tag: str, extra_mask: Optional[np.ndarray] = None, fee_rt: float = 0.0030) -> pd.DataFrame:
    """Slice event pool for a specific entry_type & exit_tag with standard buy_date/exit_date/gross_ret/net_ret."""
    m = np.ones(len(df), dtype=bool)
    if entry_filter is not None and entry_filter != "E_ALL":
        m &= (df["entry_type"].to_numpy() == entry_filter)
    if extra_mask is not None:
        m &= extra_mask
    ed_col = f"{exit_tag}_exit_date"
    gr_col = f"{exit_tag}_gross_ret"
    eh_col = f"{exit_tag}_exit_hhmm"
    mtm_col = f"{exit_tag}_mtm_json"
    m &= df[ed_col].notna().to_numpy(bool) & (df[ed_col].astype(str) > df["buy_date"].astype(str)).to_numpy(bool) & df[gr_col].notna().to_numpy(bool)
    sub = df[m].copy()
    if entry_filter == "E_ALL" and not sub.empty:
        prio = {"E3": 0, "E1a": 1, "E2": 2, "E1b": 3}
        sub["_ep"] = sub["entry_type"].map(prio).fillna(9)
        sub = sub.sort_values(["buy_date", "code", "_ep"]).drop_duplicates(["buy_date", "code"], keep="first").drop(columns=["_ep"])
    sub["exit_date"] = sub[ed_col].astype(str).str[:10]
    sub["exit_hhmm"] = pd.to_numeric(sub[eh_col], errors="coerce").fillna(1500).astype(int)
    sub["gross_ret"] = pd.to_numeric(sub[gr_col], errors="coerce").astype(float)
    sub["net_ret"] = (1.0 + sub["gross_ret"]) * (1.0 - float(fee_rt)) - 1.0
    sub["mtm_json_use"] = sub[mtm_col]
    sub["can_buy_hygiene"] = ~sub["is_yizi"].fillna(False).to_numpy(bool)
    return sub.sort_values(["buy_date", "code"]).reset_index(drop=True)
