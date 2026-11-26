#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 shared exact MTM evaluator, exit simulators, and V20 correlation/patch engine."""
import json
import math
import sys
from typing import Optional
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

WAVE1_BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
if WAVE1_BASE not in sys.path:
    sys.path.insert(0, WAVE1_BASE)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm


def build_mtm_pairs_dt(
    op: np.ndarray, cl: np.ndarray, af: np.ndarray, dts: np.ndarray,
    b_idx: int, ex_idx: int, ex_px: float, buy_at_close: bool = False,
) -> list[list]:
    """Exact [dt_str, gross_mult] daily MTM segments so prod == 1 + gross_ret."""
    if ex_idx <= b_idx or af[b_idx] <= 0 or af[ex_idx] <= 0 or ex_px <= 0:
        return []
    pairs = []
    if not buy_at_close:
        if op[b_idx] <= 0:
            return []
        pairs.append([str(dts[b_idx]), float((cl[b_idx] * af[b_idx]) / (op[b_idx] * af[b_idx]))])
    for k in range(b_idx + 1, ex_idx):
        pairs.append([str(dts[k]), float((cl[k] * af[k]) / (cl[k - 1] * af[k - 1]))])
    pairs.append([str(dts[ex_idx]), float((ex_px * af[ex_idx]) / (cl[ex_idx - 1] * af[ex_idx - 1]))])
    return pairs


def attach_exact_mtm_col(df: pd.DataFrame, mtm_json_col: str, cal_dts: list[str], fee_rt: float, out_col: str = "mtm_exact") -> pd.DataFrame:
    out = df.copy()
    if out.empty or mtm_json_col not in out.columns:
        out[out_col] = [[] for _ in range(len(out))]
        return out
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    f_buy = float(fee_rt) * 0.5
    f_sell_mult = (1.0 - float(fee_rt)) / (1.0 - f_buy)
    mtm_list = []
    for raw_s in out[mtm_json_col].fillna("[]"):
        segs = json.loads(raw_s) if isinstance(raw_s, str) and raw_s else []
        conv = []
        if segs:
            last_i = len(segs) - 1
            for k, (dt_str, m_val) in enumerate(segs):
                ti = dt_idx.get(str(dt_str)[:10])
                mv = float(m_val)
                if k == 0:
                    mv *= (1.0 - f_buy)
                if k == last_i:
                    mv *= f_sell_mult
                if ti is not None:
                    conv.append((int(ti), mv))
        mtm_list.append(conv)
    out[out_col] = mtm_list
    return out


def eval_slice_exact(
    slot_df: pd.DataFrame, pass_df: Optional[pd.DataFrame], cand_pool_df: pd.DataFrame,
    bench_df: pd.DataFrame, mtm_json_col: str, fee_rt: float,
    start_dt: str, end_dt: str, windows: list[tuple[str, str, str]],
    perm_n: int = 200, seed: int = 20261126,
) -> dict:
    max_exit = str(slot_df["exit_date"].max()) if (not slot_df.empty and "exit_date" in slot_df.columns) else end_dt
    cal_end = min(str(bench_df["trade_date"].max()), max(end_dt, max_exit))
    b = bench_df[bench_df["trade_date"].between(start_dt, cal_end)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = b["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_arr = b["csi300_daily_ret"].to_numpy(float)
    ew_arr = b["alla_ew_daily_ret"].to_numpy(float)

    sl_m = attach_exact_mtm_col(slot_df, mtm_json_col, cal_dts, fee_rt, out_col="mtm_exact")
    sl_in = sl_m[sl_m["buy_date"].between(start_dt, end_dt)].reset_index(drop=True) if not sl_m.empty else sl_m
    dr_full, mtm_diff = wfm.build_daily_mtm_returns(sl_in, cal_dts, mtm_col="mtm_exact")
    win_res = {}
    for wn, s, e in windows:
        se, ee = max(s, start_dt), min(e, end_dt)
        if se <= ee:
            win_res[wn] = wfm._calc_one_window(sl_in, pass_df, dr_full, cal_dts, dt_idx, csi_arr, ew_arr, se, ee)
    perm = wfm.perm_test_trading_days(sl_in, cand_pool_df, start_dt, end_dt, n_perm=perm_n, seed=seed)
    return {"mtm_reconciliation_diff": round(float(mtm_diff), 10), "windows": win_res, "permutation": perm}


def compute_v20_corr_and_patch(
    pass_df: pd.DataFrame, slot_df: pd.DataFrame, v20_ctx: dict,
    mtm_json_col: str, fee_rt: float, start_dt: str, end_dt: str = "2026-11-16",
    score_col: str = "wf_score",
) -> dict:
    cal_df = v20_ctx["calendar_5y"] if end_dt <= "2026-11-16" else v20_ctx["calendar_ext"]
    cal_win = cal_df[cal_df["trade_date"].between(start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    v20_dr = cal_win["v20_daily_ret"].fillna(0.0).to_numpy(float)

    sl_sub = slot_df[slot_df["buy_date"].between(start_dt, end_dt)] if not slot_df.empty else slot_df
    sl_m = attach_exact_mtm_col(sl_sub, mtm_json_col, cal_dts, fee_rt, out_col="mtm_exact")
    tr_dr, diff = wfm.build_daily_mtm_returns(sl_m, cal_dts, mtm_col="mtm_exact")
    corr_all = float(np.corrcoef(tr_dr, v20_dr)[0, 1]) if (np.std(tr_dr) > 1e-12 and np.std(v20_dr) > 1e-12) else 0.0
    t_act = np.abs(tr_dr) > 1e-10
    corr_act = float(np.corrcoef(tr_dr[t_act], v20_dr[t_act])[0, 1]) if (t_act.sum() >= 5 and np.std(tr_dr[t_act]) > 1e-12 and np.std(v20_dr[t_act]) > 1e-12) else None

    patch_res = None
    p_sub = pass_df[pass_df["buy_date"].between(start_dt, end_dt)].copy() if not pass_df.empty else pd.DataFrame()
    if not p_sub.empty:
        p_mtm = attach_exact_mtm_col(p_sub, mtm_json_col, cal_dts, fee_rt, out_col="mtm_patch_exact")
        if score_col not in p_mtm.columns:
            p_mtm[score_col] = 100.0
        patch_res = wf.simulate_v20_empty_slot_patch(
            p_mtm, v20_ctx=v20_ctx, wf_start_dt=start_dt, end_dt=end_dt,
            score_col=score_col, patch_mtm_col="mtm_patch_exact",
        )
    return {
        "mtm_diff": round(float(diff), 10),
        "corr_all_days": round(corr_all, 4),
        "corr_track_active": round(corr_act, 4) if corr_act is not None else None,
        "patch_m1": (patch_res["mode1_strict_combined_no_peek"] if patch_res else None),
        "patch_m2": (patch_res["mode2_empty_slot_standalone"] if patch_res else None),
    }


def make_clean_view(df: pd.DataFrame, exit_tag: str, mask: Optional[np.ndarray] = None, fee_rt: float = 0.0030) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    m = np.ones(len(df), dtype=bool)
    if mask is not None:
        m &= mask
    ed_col, gr_col, eh_col, mtm_col = f"{exit_tag}_exit_date", f"{exit_tag}_gross_ret", f"{exit_tag}_exit_hhmm", f"{exit_tag}_mtm_json"
    if ed_col not in df.columns or gr_col not in df.columns:
        return pd.DataFrame()
    m &= df[ed_col].notna().to_numpy(bool) & (df[ed_col].astype(str) > df["buy_date"].astype(str)).to_numpy(bool) & df[gr_col].notna().to_numpy(bool)
    sub = df[m].copy()
    if sub.empty:
        return sub
    sub["exit_date"] = sub[ed_col].astype(str).str[:10]
    sub["exit_hhmm"] = pd.to_numeric(sub[eh_col], errors="coerce").fillna(1500).astype(int)
    sub["gross_ret"] = pd.to_numeric(sub[gr_col], errors="coerce").astype(float)
    sub["net_ret"] = (1.0 + sub["gross_ret"]) * (1.0 - float(fee_rt)) - 1.0
    sub["mtm_json_use"] = sub[mtm_col]
    sub["can_buy_hygiene"] = ~sub["is_yizi"].fillna(False).to_numpy(bool)
    return sub.sort_values(["buy_date", "code"]).drop_duplicates(["buy_date", "code"], keep="first").reset_index(drop=True)
