#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD042 Shared Exit Simulator, Exact Daily MTM Evaluator (`mtm_diff == 0.0`),
Walk-Forward Scorecard Runner, Multi-Friction/Liquidity Stress, and 2024-12-31 Truncation Proof.
Zero yfinance (D12). Zero cap10m.
"""
import json
import math
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

WAVE1_BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
if WAVE1_BASE not in sys.path:
    sys.path.insert(0, WAVE1_BASE)

import wf_scorecard_engine as wf  # noqa: E402
import _wf_sim_and_metrics as wfm  # noqa: E402

TRD_DAYS_YEAR = 242.0


def build_mtm_gross_pairs(
    op: np.ndarray,
    cl: np.ndarray,
    af: np.ndarray,
    dts: np.ndarray,
    b_idx: int,
    ex_idx: int,
    ex_px: float,
) -> list[list]:
    """Build exact [dt_str, gross_mult] pairs so prod(gross_mult) == 1 + gross_ret."""
    if ex_idx <= b_idx or op[b_idx] <= 0 or ex_px <= 0 or af[b_idx] <= 0 or af[ex_idx] <= 0:
        return []
    pairs = []
    ac_b = cl[b_idx] * af[b_idx]
    ao_b = op[b_idx] * af[b_idx]
    pairs.append([str(dts[b_idx]), float(ac_b / ao_b)])
    for k in range(b_idx + 1, ex_idx):
        ac_prev = cl[k - 1] * af[k - 1]
        ac_cur = cl[k] * af[k]
        pairs.append([str(dts[k]), float(ac_cur / ac_prev)])
    ac_ex_prev = cl[ex_idx - 1] * af[ex_idx - 1]
    aex = ex_px * af[ex_idx]
    pairs.append([str(dts[ex_idx]), float(aex / ac_ex_prev)])
    return pairs


def simulate_exits_generic(
    b: int,
    n: int,
    op: np.ndarray,
    hi: np.ndarray,
    lo: np.ndarray,
    cl: np.ndarray,
    af: np.ndarray,
    ac: np.ndarray,
    dts: np.ndarray,
    zt: np.ndarray,
    dt_f: np.ndarray,
    yzd: np.ndarray,
    ma5: np.ndarray,
) -> dict:
    """
    Simulate 6 causal exit rules from buy_idx b (09:25 open buy), respecting T+1 and limit-down deferral:
      - S1_hold1c, S2_hold2c, S3_hold3c, S4_hold5c
      - S5_zt_ride (ride consecutive ZT to first break close; if non-ZT day0, exit b+1 open if weak else close)
      - S6_ma5_stop (break below MA5 close within [b+1..b+5], else b+5 close)
    """
    buy_px = op[b]
    if b + 1 >= n or buy_px <= 0 or af[b] <= 0:
        return {}
    b_ac = buy_px * af[b]
    out = {}

    def _finish_close(target_k: int, tag: str):
        if target_k >= n:
            return
        k = target_k
        while k < n - 1 and yzd[k]:
            k += 1
        if yzd[k]:
            return
        if k > target_k:
            ex_px, ehh, rsn = op[k], 925, f"{tag}_dt_open"
        elif dt_f[k] and k + 1 < n:
            k2 = k + 1
            while k2 < n - 1 and yzd[k2]:
                k2 += 1
            if yzd[k2]:
                return
            ex_px, ehh, rsn = op[k2], 925, f"{tag}_dt_next_open"
            k = k2
        else:
            ex_px, ehh, rsn = cl[k], 1500, tag
        if ex_px <= 0 or af[k] <= 0:
            return
        gr = (ex_px * af[k]) / b_ac - 1.0
        mtm = build_mtm_gross_pairs(op, cl, af, dts, b, k, ex_px)
        out[tag] = {
            "exit_date": str(dts[k]),
            "exit_hhmm": int(ehh),
            "gross_ret": float(gr),
            "reason": rsn,
            "mtm_gross": mtm,
        }

    for h, nm in ((1, "S1_hold1c"), (2, "S2_hold2c"), (3, "S3_hold3c"), (5, "S4_hold5c")):
        _finish_close(b + h, nm)

    # S5_zt_ride
    if not zt[b]:
        k = b + 1
        while k < n - 1 and yzd[k]:
            k += 1
        if not yzd[k] and op[k] > 0 and cl[k] > 0:
            d0_r = ac[b] / b_ac - 1.0
            d1_or = (op[k] * af[k]) / ac[b] - 1.0
            if d0_r <= -0.02 or cl[b] < op[b] or d1_or <= -0.035:
                ex_px, ehh, rsn = op[k], 925, "nonzt_next_open"
            else:
                if dt_f[k] and k + 1 < n:
                    k2 = k + 1
                    while k2 < n - 1 and yzd[k2]:
                        k2 += 1
                    if not yzd[k2]:
                        ex_px, ehh, rsn, k = op[k2], 925, "nonzt_dt_next_open", k2
                    else:
                        ex_px, ehh, rsn = cl[k], 1500, "nonzt_next_close"
                else:
                    ex_px, ehh, rsn = cl[k], 1500, "nonzt_next_close"
            gr = (ex_px * af[k]) / b_ac - 1.0
            out["S5_zt_ride"] = {
                "exit_date": str(dts[k]),
                "exit_hhmm": int(ehh),
                "gross_ret": float(gr),
                "reason": rsn,
                "mtm_gross": build_mtm_gross_pairs(op, cl, af, dts, b, k, ex_px),
            }
    else:
        k = b + 1
        while k < n:
            if zt[k]:
                k += 1
                continue
            orig_k = k
            while k < n - 1 and yzd[k]:
                k += 1
            if yzd[k]:
                break
            if k > orig_k:
                ex_px, ehh, rsn = op[k], 925, "delayed_dt_open"
            elif dt_f[k] and k + 1 < n:
                k2 = k + 1
                while k2 < n - 1 and yzd[k2]:
                    k2 += 1
                if yzd[k2]:
                    break
                ex_px, ehh, rsn, k = op[k2], 925, "zt_break_dt_next_open", k2
            else:
                ex_px, ehh, rsn = cl[k], 1500, "zt_break_close"
            gr = (ex_px * af[k]) / b_ac - 1.0
            out["S5_zt_ride"] = {
                "exit_date": str(dts[k]),
                "exit_hhmm": int(ehh),
                "gross_ret": float(gr),
                "reason": rsn,
                "mtm_gross": build_mtm_gross_pairs(op, cl, af, dts, b, k, ex_px),
            }
            break

    # S6_ma5_stop
    k_ma = -1
    for off in range(1, 6):
        k = b + off
        if k >= n:
            break
        if np.isfinite(ma5[k]) and cl[k] < ma5[k] * 0.998:
            k_ma = k
            break
    if k_ma == -1 and b + 5 < n:
        k_ma = b + 5
    if k_ma > b:
        _finish_close(k_ma, "S6_ma5_stop")

    return out


def attach_exact_mtm_col(
    df: pd.DataFrame,
    mtm_json_col: str,
    cal_dts: list[str],
    fee_rt: float,
    out_col: str = "mtm_exact",
) -> pd.DataFrame:
    """Convert raw [dt_str, gross_mult] json into exact [(cal_ti, net_mult)] with half-fee entry & rest exit."""
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


def make_clean_view(
    df: pd.DataFrame,
    entry_filter: Optional[str],
    exit_tag: str,
    extra_mask: Optional[np.ndarray] = None,
    fee_rt: float = 0.0030,
) -> pd.DataFrame:
    """Slice event dataframe for one entry_type & exit_tag with standard columns."""
    m = np.ones(len(df), dtype=bool)
    if entry_filter is not None and entry_filter != "ALL":
        m &= (df["entry_type"].to_numpy() == entry_filter)
    if extra_mask is not None:
        m &= extra_mask
    ed_col = f"{exit_tag}_exit_date"
    gr_col = f"{exit_tag}_gross_ret"
    eh_col = f"{exit_tag}_exit_hhmm"
    mtm_col = f"{exit_tag}_mtm_json"
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


def eval_windows_exact(
    slot_df: pd.DataFrame,
    pass_df: Optional[pd.DataFrame],
    cand_pool_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    mtm_json_col: str,
    fee_rt: float,
    start_dt: str,
    end_dt: str,
    windows: list[tuple[str, str, str]],
    perm_n: int = 1000,
    seed: int = 20261126,
) -> dict:
    """Evaluate single-slot trades across windows with exact MTM (mtm_diff == 0.0) & permutation test."""
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
        if s > e:
            continue
        s_eff = max(s, start_dt)
        e_eff = min(e, end_dt)
        if s_eff > e_eff:
            continue
        win_res[wn] = wfm._calc_one_window(sl_in, pass_df, dr_full, cal_dts, dt_idx, csi_arr, ew_arr, s_eff, e_eff)

    perm = wfm.perm_test_trading_days(sl_in, cand_pool_df, start_dt, end_dt, n_perm=perm_n, seed=seed)
    return {"mtm_reconciliation_diff": round(float(mtm_diff), 10), "windows": win_res, "permutation_1000": perm}


def compute_v20_corr_exact(
    slot_df: pd.DataFrame,
    v20_ctx: dict,
    mtm_json_col: str,
    fee_rt: float,
    start_dt: str,
    end_dt: str = "2026-11-16",
) -> dict:
    """Exact daily MTM Pearson correlation vs V20 baseline."""
    cal_df = v20_ctx["calendar_5y"] if end_dt <= "2026-11-16" else v20_ctx["calendar_ext"]
    cal_win = cal_df[cal_df["trade_date"].between(start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    v20_dr = cal_win["v20_daily_ret"].fillna(0.0).to_numpy(float)
    sl_sub = slot_df[slot_df["buy_date"].between(start_dt, end_dt)] if not slot_df.empty else slot_df
    sl_m = attach_exact_mtm_col(sl_sub, mtm_json_col, cal_dts, fee_rt, out_col="mtm_exact")
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


def evaluate_wf_track(
    track_id: str,
    df_view: pd.DataFrame,
    feature_cols: list[str],
    v20_ctx: dict,
    liq_col: str,
    liq_thresholds: tuple[float, ...],
    wf_start_req: str = "2023-01-03",
    end_dt: str = "2026-11-25",
    thresholds: tuple = ("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80),
    run_trunc: bool = False,
    min_warmup_trades: int = 50,
    min_warmup_trades_rare: int = 35,
    min_warmup_months: int = 12,
    perm_n: int = 1000,
    extra_eval_windows: Optional[list[tuple[str, str, str]]] = None,
) -> tuple[dict, list[dict], dict]:
    """Run expanding WF 0..100 scorecard (exit_date < t) + stress tests + V20 empty-slot patch + truncation."""
    t0 = time.time()
    res = wf.run_wf_scorecard_new_strategy(
        df_view,
        feature_cols=feature_cols,
        v20_ctx=v20_ctx,
        wf_start_date=wf_start_req,
        end_date=end_dt,
        min_warmup_trades=min_warmup_trades,
        min_warmup_trades_rare=min_warmup_trades_rare,
        min_warmup_months=min_warmup_months,
        recalc_freq="daily",
        top_k=12,
        min_k=5,
        max_corr=0.65,
        min_t_stat=1.0,
        shrink_tau=20.0,
        fee_rt=0.0030,
        gross_ret_col="gross_ret",
        thresholds=thresholds,
        eval_v20_patch=False,
        perm_n=50,
        seed=20261126,
    )
    actual_wf_start = res["meta"]["wf_actual_start"] or wf_start_req
    bench_df = v20_ctx["bench"]
    scored_df = res["scored_df"]
    wf_cands = scored_df[scored_df["wf_in_window"]].copy()

    trunc_res = None
    if run_trunc and not wf_cands.empty and (df_view["buy_date"] <= "2024-12-31").sum() >= min_warmup_trades_rare:
        trunc_res = wf.verify_truncation_zero_leakage(
            df_view,
            feature_cols,
            mode="A",
            cutoff="2024-12-31",
            score_threshold="top20",
            v20_ctx=v20_ctx,
            wf_start_date=wf_start_req,
            end_date=end_dt,
            min_warmup_trades=min_warmup_trades,
            min_warmup_trades_rare=min_warmup_trades_rare,
            min_warmup_months=min_warmup_months,
            recalc_freq="daily",
            top_k=12,
            min_k=5,
            max_corr=0.65,
            min_t_stat=1.0,
            shrink_tau=20.0,
            fee_rt=0.0030,
            gross_ret_col="gross_ret",
        )

    exact_wins = [
        ("FULL_WF", actual_wf_start, end_dt),
        ("Y2025_2026", "2025-01-01", end_dt),
        ("Y2026", "2026-01-01", end_dt),
        ("Y2026_H2", "2026-07-01", end_dt),
    ]
    if extra_eval_windows:
        exact_wins.extend(extra_eval_windows)
    cal_df = v20_ctx["calendar_5y"]
    patch_end = "2026-11-16"
    patch_cal_dts = cal_df[cal_df["trade_date"].between(actual_wf_start, patch_end)].sort_values("trade_date")["trade_date"].tolist()

    csv_rows, thr_details = [], {}
    for th in thresholds:
        tname = str(th) if not isinstance(th, (int, float)) else f"abs_{int(th)}"
        tr = res["threshold_results"][tname]
        slot_df, pass_df = tr["slot_df"].copy(), tr["pass_df"].copy()

        ev30 = eval_windows_exact(slot_df, pass_df, wf_cands, bench_df, "mtm_json_use", 0.0030, actual_wf_start, end_dt, exact_wins, perm_n=perm_n)
        ev50 = eval_windows_exact(
            slot_df.assign(net_ret=(1.0 + slot_df["gross_ret"]) * (1.0 - 0.0050) - 1.0),
            pass_df.assign(net_ret=(1.0 + pass_df["gross_ret"]) * (1.0 - 0.0050) - 1.0),
            wf_cands.assign(net_ret=(1.0 + wf_cands["gross_ret"]) * (1.0 - 0.0050) - 1.0),
            bench_df, "mtm_json_use", 0.0050, actual_wf_start, end_dt, exact_wins[:2], perm_n=30,
        )
        ev80 = eval_windows_exact(
            slot_df.assign(net_ret=(1.0 + slot_df["gross_ret"]) * (1.0 - 0.0080) - 1.0),
            pass_df.assign(net_ret=(1.0 + pass_df["gross_ret"]) * (1.0 - 0.0080) - 1.0),
            wf_cands.assign(net_ret=(1.0 + wf_cands["gross_ret"]) * (1.0 - 0.0080) - 1.0),
            bench_df, "mtm_json_use", 0.0080, actual_wf_start, end_dt, exact_wins[:2], perm_n=30,
        )

        liq_res = {}
        for lthr in liq_thresholds:
            lkey = f"liq_{lthr}"
            lpass = pass_df[pass_df[liq_col] >= lthr].copy() if (not pass_df.empty and liq_col in pass_df.columns) else pd.DataFrame()
            _, lslot = wfm.select_single_slot_trades(lpass, score_col="wf_score", threshold=None, wf_only=False) if not lpass.empty else (lpass, lpass)
            evl = eval_windows_exact(lslot, lpass, wf_cands, bench_df, "mtm_json_use", 0.0030, actual_wf_start, end_dt, exact_wins[:2], perm_n=30)
            liq_res[lkey] = evl["windows"].get("FULL_WF", {})

        v20_corr = compute_v20_corr_exact(slot_df, v20_ctx, "mtm_json_use", 0.0030, actual_wf_start, patch_end)
        patch_res = None
        if not pass_df.empty and th != "all_cands" and actual_wf_start <= patch_end:
            p_sub = pass_df[pass_df["buy_date"] <= patch_end].copy()
            if not p_sub.empty:
                p_mtm = attach_exact_mtm_col(p_sub, "mtm_json_use", patch_cal_dts, 0.0030, out_col="mtm_patch_exact")
                patch_res = wf.simulate_v20_empty_slot_patch(
                    p_mtm, v20_ctx=v20_ctx, wf_start_dt=actual_wf_start, end_dt=patch_end,
                    score_col="wf_score", patch_mtm_col="mtm_patch_exact",
                )

        fw = ev30["windows"].get("FULL_WF", {})
        y2526 = ev30["windows"].get("Y2025_2026", {})
        y26 = ev30["windows"].get("Y2026", {})
        y26h2 = ev30["windows"].get("Y2026_H2", {})
        fw50 = ev50["windows"].get("FULL_WF", {})
        fw80 = ev80["windows"].get("FULL_WF", {})
        perm = ev30["permutation_1000"]
        m1 = patch_res["mode1_strict_combined_no_peek"] if patch_res else None
        m2 = patch_res["mode2_empty_slot_standalone"] if patch_res else None

        row = {
            "section": "WF_SCORECARD",
            "track": track_id,
            "threshold": tname,
            "wf_start": actual_wf_start,
            "n_pass": int(len(pass_df)),
            "n_trades": fw.get("n", 0),
            "wr_pct": fw.get("wr_pct", 0.0),
            "plr": fw.get("plr", 0.0),
            "mean_pct": fw.get("mean_pct", 0.0),
            "nav_30": fw.get("nav", 1.0),
            "ex3_30": fw.get("ex_top3_nav", 1.0),
            "ex5_30": fw.get("ex_top5_nav", 1.0),
            "mdd_pct": fw.get("daily_mdd_pct", 0.0),
            "sharpe": fw.get("daily_sharpe", 0.0),
            "calmar": fw.get("daily_calmar", 0.0),
            "mtm_diff": ev30["mtm_reconciliation_diff"],
            "excess_csi300_pp": fw.get("excess_csi300_pp", 0.0),
            "excess_alla_ew_pp": fw.get("excess_alla_ew_pp", 0.0),
            "nav_50": fw50.get("nav", 1.0),
            "ex5_50": fw50.get("ex_top5_nav", 1.0),
            "nav_80": fw80.get("nav", 1.0),
            "ex5_80": fw80.get("ex_top5_nav", 1.0),
            "n_2526": y2526.get("n", 0),
            "nav_2526": y2526.get("nav", 1.0),
            "ex5_2526": y2526.get("ex_top5_nav", 1.0),
            "n_y26": y26.get("n", 0),
            "nav_y26": y26.get("nav", 1.0),
            "n_26h2": y26h2.get("n", 0),
            "nav_26h2": y26h2.get("nav", 1.0),
            "perm_sd_p": perm.get("same_day_p_nav", 1.0),
            "perm_any_p": perm.get("any_cand_day_p_nav", 1.0),
            "corr_v20_all": v20_corr["corr_all_days"],
            "corr_v20_act": v20_corr["corr_track_active"],
            "v20_comb_delta_ratio": m1.get("delta_nav_ratio_full_wf") if m1 else None,
            "v20_comb_delta_sharpe": m1.get("delta_sharpe_full_wf") if m1 else None,
            "v20_patch_added_n": m1.get("n_patch_added") if m1 else None,
            "v20_skipped_n": m1.get("n_v20_skipped_by_collision") if m1 else None,
            "emp_n": m2["windows"]["FULL_WF"].get("n") if m2 else None,
            "emp_nav": m2["windows"]["FULL_WF"].get("nav") if m2 else None,
            "emp_ex5": m2["windows"]["FULL_WF"].get("ex_top5_nav") if m2 else None,
            "trunc_pass": trunc_res["zero_leakage_pass"] if trunc_res else None,
        }
        for lkey, lval in liq_res.items():
            row[f"{lkey}_n"] = lval.get("n", 0)
            row[f"{lkey}_nav"] = lval.get("nav", 1.0)
            row[f"{lkey}_ex5"] = lval.get("ex_top5_nav", 1.0)
        if extra_eval_windows:
            for ewn, _, _ in extra_eval_windows:
                ewd = ev30["windows"].get(ewn, {})
                row[f"{ewn}_n"] = ewd.get("n", 0)
                row[f"{ewn}_nav"] = ewd.get("nav", 1.0)
                row[f"{ewn}_ex5"] = ewd.get("ex_top5_nav", 1.0)
                row[f"{ewn}_sharpe"] = ewd.get("daily_sharpe", 0.0)
        csv_rows.append(row)

        thr_details[tname] = {
            "ev30": ev30,
            "ev50_fw": fw50,
            "ev80_fw": fw80,
            "liq_fw": liq_res,
            "v20_corr": v20_corr,
            "v20_patch_m1": ({k: v for k, v in m1.items() if k != "skipped_v20_trades"} if m1 else None),
            "v20_patch_m2": m2,
        }

    latest_card = res["meta"]["latest_scorecard"]
    audit = {
        "track": track_id,
        "elapsed_sec": round(time.time() - t0, 2),
        "n_rows": int(len(df_view)),
        "n_features": int(len(feature_cols)),
        "wf_actual_start": actual_wf_start,
        "truncation_20241231": trunc_res,
        "latest_factors": (
            [{k: f[k] for k in ("name", "t_cluster", "shape", "budget_pts", "bin_pts", "bin_cnts", "bin_wr_pct", "bin_mean_pct")} for f in latest_card["factors"]]
            if latest_card else []
        ),
        "thresholds": thr_details,
    }
    return audit, csv_rows, res
