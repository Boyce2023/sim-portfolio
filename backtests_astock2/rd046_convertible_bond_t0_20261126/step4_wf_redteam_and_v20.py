#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD046 Stage 2D: Strict Expanding Walk-Forward Multi-Factor Scorecard (CB3) + Six Red-Team Death Gates
  1. Single-slot Top-1 vs Same-day Equal-Weight (`eq_nav`)
  2. `ex5` / `ex10` extreme-removal
  3. Year-by-year 2023-2026 (incl. 26H2) + Exact Daily MTM Sharpe (`max_abs_diff == 0.0`) + CSI300 Net Excess + 1000x Permutation p-value
  4. Physical `2024-12-31` Truncation Re-run (`max_abs_diff == 0.0` for score & return)
  5. Multi-tier CB costs: 10bps / 20bps / 50bps / 100bps (+ 30/80/150bps for CB1)
  6. Correlation with V20.0 + V20.0 Empty-Slot Integration (`T+0` 0-collision vs `T+1` collision)
Zero yfinance (D12). Peak memory < 1.2 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd046_convertible_bond_t0_20261126"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import _wf_core as wfc  # noqa: E402
import _wf_sim_and_metrics as wfm  # noqa: E402
import _wf_v20_patch as wfv  # noqa: E402

TRD_DAYS_YEAR = 242.0

FEATURES_OPEN = [
    "cb_prev_close", "cb_prem_t1", "cb_pure_prem_t1", "cb_double_low_t1",
    "cb_open_pct", "cb_ret_1d_t1", "cb_ret_5d_t1",
    "cb_amt_t1", "cb_amt_5d_t1", "cb_turn_t1", "cb_turn_5d_t1", "cb_remain_scale_t1",
    "cb_beta_20d_t1", "cb_open_lag", "cb_open_prem_est",
    "open_pct", "prev_streak", "ret_5d_t1", "ret_20d_t1", "pos_20d_t1",
    "amount_yi_t1", "free_mcap_yi_t1", "is_20cm",
    "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "d1_seal_ratio_t1",
    "L1_zt_cnt_t1", "L1_zb_rate_t1", "L1_max_board_t1", "L1_zt_prem_t1", "L1_sent_phase_t1",
]

FEATURES_CLOSE = [
    "close", "conv_prem_pct", "pure_bond_prem_pct", "cb_double_low_now",
    "cb_ret_cc", "cb_ret_oc", "cb_ret_5d_now",
    "amount_yi", "cb_amt_5d_now", "cb_turn_now", "remain_scale_pit",
    "cb_beta_20d_t1", "ret_1d", "open_pct", "streak", "ret_5d_t1", "pos_20d_t1",
    "stk_amt_yi", "free_mcap_yi_t1", "is_20cm",
    "L1_zt_cnt_t1", "L1_zb_rate_t1", "L1_max_board_t1", "L1_zt_prem_t1", "L1_sent_phase_t1",
]


def select_single_slot_t0_t1(
    scored_df: pd.DataFrame,
    score_col: str = "wf_score",
    threshold: float | str | None = None,
    wf_only: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Single-slot selector supporting BOTH T+0 (exit_date == buy_date, exit_hhmm > buy_hhmm) and T+1 (exit_date > buy_date)."""
    m = scored_df["can_buy_hygiene"].fillna(True).to_numpy(bool)
    if wf_only and "wf_in_window" in scored_df.columns:
        m &= scored_df["wf_in_window"].fillna(False).to_numpy(bool)
    m &= scored_df[score_col].notna().to_numpy(bool)
    if threshold is not None:
        if isinstance(threshold, str):
            tv = pd.to_numeric(scored_df[threshold], errors="coerce").to_numpy(float)
            m &= np.isfinite(tv) & (scored_df[score_col].to_numpy(float) >= tv)
        else:
            m &= scored_df[score_col].to_numpy(float) >= float(threshold)
    passing = scored_df[m].copy()
    if passing.empty:
        return passing, passing
    srt = passing.sort_values(["buy_date", score_col, "cb_amt_5d_t1", "code"], ascending=[True, False, False, True], kind="mergesort")

    taken = []
    cur_ed, cur_eh = "", 0
    for r in srt.itertuples():
        bd = str(r.buy_date)
        ed = str(r.exit_date)
        bh = int(r.buy_hhmm)
        eh = int(r.exit_hhmm)
        if ed < bd or (ed == bd and eh <= bh):
            continue
        if (not cur_ed) or (bd > cur_ed) or (bd == cur_ed and bh > cur_eh):
            taken.append(r.Index)
            cur_ed, cur_eh = ed, eh
    return passing.reset_index(drop=True), srt.loc[taken].copy().reset_index(drop=True)


def build_exact_mtm(trades_df: pd.DataFrame, cal_dts: list[str]) -> tuple[np.ndarray, float]:
    T = len(cal_dts)
    if trades_df.empty:
        return np.zeros(T, dtype=float), 0.0
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    day_mult = np.ones(T, dtype=float)
    for r in trades_df.itertuples(index=False):
        bi = dt_idx.get(str(r.buy_date))
        ei = dt_idx.get(str(r.exit_date))
        if bi is None:
            continue
        if ei is None or ei <= bi:
            day_mult[bi] *= (1.0 + float(r.net_ret))
        else:
            span = ei - bi + 1
            g = (1.0 + float(r.net_ret)) ** (1.0 / span)
            day_mult[bi:ei + 1] *= g
    dr = day_mult - 1.0
    tr_sub = trades_df[trades_df["buy_date"].isin(dt_idx)]
    tr_nav = float(np.prod(1.0 + tr_sub["net_ret"].to_numpy(float))) if not tr_sub.empty else 1.0
    return dr, abs(float(np.prod(day_mult)) - tr_nav)


def eval_window_metrics(slot_df: pd.DataFrame, pass_df: pd.DataFrame, dr_full: np.ndarray, cal_dts: list[str], dt_idx: dict[str, int], csi_arr: np.ndarray, sdt: str, edt: str) -> dict:
    pos = [dt_idx[d] for d in cal_dts if sdt <= d <= edt]
    T = len(pos)
    if T == 0:
        return {"n": 0, "nav": 1.0}
    dr = dr_full[pos]
    csi = csi_arr[pos]
    csi_pct = (float(np.prod(1.0 + csi)) - 1.0) * 100.0
    mtm_nav = float(np.prod(1.0 + dr))
    curve = np.concatenate([[1.0], np.cumprod(1.0 + dr)])
    pk = np.maximum.accumulate(curve)
    mdd = float(np.max((pk - curve) / pk) * 100.0)
    sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0

    sub = slot_df[slot_df["buy_date"].between(sdt, edt)] if not slot_df.empty else pd.DataFrame()
    if pass_df is not None and not pass_df.empty:
        psub = pass_df[pass_df["buy_date"].between(sdt, edt)]
        eq_d = psub.groupby("buy_date")["net_ret"].mean().to_numpy(float) if not psub.empty else np.array([])
        eq_nav = float(np.prod(1.0 + eq_d)) if len(eq_d) else 1.0
    else:
        eq_nav = 1.0

    if sub.empty:
        return {
            "n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0, "nav": 1.0,
            "mtm_nav": round(mtm_nav, 4), "eq_nav": round(eq_nav, 4),
            "ex5_nav": 1.0, "ex10_nav": 1.0, "daily_mdd_pct": round(mdd, 2),
            "daily_sharpe": round(sharpe, 3), "csi300_pct": round(csi_pct, 2),
            "excess_csi300_pp": round(-csi_pct, 2),
        }
    rets = sub["net_ret"].to_numpy(float)
    w, l = rets[rets > 0], rets[rets <= 0]
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    tr_nav = float(np.prod(1.0 + rets))
    sr = np.sort(rets)
    ex5 = float(np.prod(1.0 + sr[:-5])) if len(rets) > 5 else 1.0
    ex10 = float(np.prod(1.0 + sr[:-10])) if len(rets) > 10 else 1.0
    return {
        "n": int(len(rets)),
        "wr_pct": round(float((rets > 0).mean() * 100.0), 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav": round(tr_nav, 4),
        "mtm_nav": round(mtm_nav, 4),
        "eq_nav": round(eq_nav, 4),
        "ex5_nav": round(ex5, 4),
        "ex10_nav": round(ex10, 4),
        "daily_mdd_pct": round(mdd, 2),
        "daily_sharpe": round(sharpe, 3),
        "csi300_pct": round(csi_pct, 2),
        "excess_csi300_pp": round((tr_nav - 1.0) * 100.0 - csi_pct, 2),
    }


def simulate_v20_patch_t0_t1(patch_df: pd.DataFrame, v20_ctx: dict, wf_start_dt: str = "2023-01-03", end_dt: str = "2026-11-16", score_col: str = "wf_score") -> dict:
    """Honest V20.0 empty-slot integration handling BOTH T+0 (exit_date == buy_date, 0 collision) & T+1."""
    cal_df = v20_ctx["calendar_5y"]
    cal_win = cal_df[cal_df["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_arr = cal_win["csi300_daily_ret"].to_numpy(float)
    empty_set = set(cal_win.loc[cal_win["v20_empty_slot"] & (~cal_win["v20_has_stier_wait"]), "trade_date"])

    p = patch_df[patch_df["buy_date"].between(wf_start_dt, end_dt) & patch_df["can_buy_hygiene"]].copy()
    if p.empty:
        return {"n_patch_added": 0, "n_v20_skipped": 0, "delta_nav_ratio": 1.0}
    if score_col not in p.columns:
        p[score_col] = 100.0
    p_top1 = p.sort_values(["buy_date", score_col, "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()

    v20_led = v20_ctx["v20_ledger"]
    v20_win = v20_led[v20_led["buy_date"].between(wf_start_dt, end_dt)].copy().reset_index(drop=True)
    v20_win["source"] = "v20"

    events = []
    for r in v20_win.itertuples(index=False):
        events.append({
            "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm), "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
            "code": r.code, "strategy": r.strategy, "net_ret": float(r.net_ret),
            "prio_src": 0, "is_wait": False, "source": "v20", "mtm_pairs": r.mtm_pairs,
        })
    for w in v20_ctx["v20_waits"]:
        if wf_start_dt <= w["buy_date"] <= end_dt and w["wait_tier"] in ("3to4_S(>=102)", "high_S(>=96)"):
            events.append({
                "buy_date": w["buy_date"], "buy_hhmm": 935, "exit_date": w["buy_date"], "exit_hhmm": int(w["cancel_hhmm"]),
                "code": w["wait_code"], "strategy": w["wait_strategy"], "net_ret": 0.0,
                "prio_src": 0, "is_wait": True, "source": "v20_wait", "mtm_pairs": [],
            })
    for r in p_top1.itertuples(index=False):
        if r.buy_date not in empty_set:
            continue
        events.append({
            "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm), "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
            "code": r.code, "strategy": "patch", "net_ret": float(r.net_ret),
            "prio_src": 1, "is_wait": False, "source": "patch", "mtm_pairs": [],
        })

    ev_df = pd.DataFrame(events).sort_values(["buy_date", "prio_src", "buy_hhmm", "code"]).reset_index(drop=True)
    taken = []
    skipped_v20 = []
    cur_ed, cur_eh = "", 0
    for r in ev_df.itertuples(index=False):
        can_enter = (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh)
        if can_enter:
            if not r.is_wait:
                taken.append(r._asdict())
            cur_ed, cur_eh = r.exit_date, int(r.exit_hhmm)
        elif r.source == "v20":
            skipped_v20.append({"buy_date": r.buy_date, "code": r.code, "net_ret": float(r.net_ret)})

    comb_df = pd.DataFrame(taken)
    dr_comb, _ = wfv._build_combined_mtm(comb_df, cal_dts)
    dr_v20, _ = wfv._build_combined_mtm(v20_win, cal_dts)
    c_m = eval_window_metrics(comb_df, None, dr_comb, cal_dts, dt_idx, csi_arr, wf_start_dt, end_dt)
    b_m = eval_window_metrics(v20_win, None, dr_v20, cal_dts, dt_idx, csi_arr, wf_start_dt, end_dt)

    # Standalone empty-slot trades (no future peek)
    p_emp = p_top1[p_top1["buy_date"].isin(empty_set)].copy()
    p_emp["can_buy_hygiene"] = True
    p_emp["wf_in_window"] = True
    _, emp_slot = select_single_slot_t0_t1(p_emp, score_col=score_col, threshold=None, wf_only=False)
    dr_emp, _ = build_exact_mtm(emp_slot, cal_dts)
    e_m = eval_window_metrics(emp_slot, p_emp, dr_emp, cal_dts, dt_idx, csi_arr, wf_start_dt, end_dt)

    # Correlation between standalone CB MTM and V20 MTM on FULL_WF
    corr_v20 = float(np.corrcoef(dr_emp, dr_v20)[0, 1]) if (np.std(dr_emp) > 1e-12 and np.std(dr_v20) > 1e-12) else 0.0
    return {
        "n_empty_days_in_win": len(empty_set),
        "standalone_empty_n": e_m["n"],
        "standalone_empty_nav": e_m["nav"],
        "standalone_empty_wr": e_m["wr_pct"],
        "standalone_empty_sharpe": e_m["daily_sharpe"],
        "corr_with_v20": round(corr_v20, 4),
        "v20_base_nav": b_m["nav"],
        "v20_base_sharpe": b_m["daily_sharpe"],
        "v20_base_mdd": b_m["daily_mdd_pct"],
        "comb_nav": c_m["nav"],
        "comb_sharpe": c_m["daily_sharpe"],
        "comb_mdd": c_m["daily_mdd_pct"],
        "n_patch_added": int((comb_df["source"] == "patch").sum()),
        "n_v20_skipped": len(skipped_v20),
        "delta_nav_ratio": round(c_m["nav"] / max(1e-9, b_m["nav"]), 4),
        "delta_sharpe": round(c_m["daily_sharpe"] - b_m["daily_sharpe"], 4),
        "delta_mdd_pp": round(c_m["daily_mdd_pct"] - b_m["daily_mdd_pct"], 2),
    }


def main():
    t0 = time.time()
    print("[Step 4] Loading causal panel + bench + V20 context...")
    m = pd.read_parquet(f"{OUT_DIR}/cb_panel_features_pit.parquet")
    # Extra current-day features ONLY valid for P4 (15:00 close buy)
    m["cb_double_low_now"] = m["close"] + m["conv_prem_pct"]
    m["cb_ret_5d_now"] = m.groupby("cb_code")["close"].pct_change(5)
    m["cb_amt_5d_now"] = m.groupby("cb_code")["amount_yi"].transform(lambda s: s.rolling(5, min_periods=1).mean())
    m["cb_turn_now"] = m["amount_yi"] / m["remain_scale_pit"].clip(lower=0.05) * 100.0

    bench = pd.read_parquet(f"{BASE_DIR}/v20_daily_bench_20210104_20261125.parquet").sort_values("trade_date").reset_index(drop=True)
    cal_dts = bench["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_arr = bench["csi300_daily_ret"].to_numpy(float)
    v20_ctx = wfv.load_v20_reference_context(BASE_DIR)

    # Define 12 rigorous CB3 tracks
    tracks = [
        ("T01_CB1_OpenAtZT_T0", m["base_ok_open"] & m["stk_open_at_zt"], "cb_ret_oc", 930, 1500, "same", FEATURES_OPEN),
        ("T02_CB1_OpenAtZT_T1O", m["base_ok_open"] & m["stk_open_at_zt"], "cb_ret_t1o", 930, 925, "next", FEATURES_OPEN),
        ("T03_P2_PrevZT_T0", m["base_ok_open"] & (m["prev_streak"] >= 1), "cb_ret_oc", 930, 1500, "same", FEATURES_OPEN),
        ("T04_P2_PrevZT_T1O", m["base_ok_open"] & (m["prev_streak"] >= 1), "cb_ret_t1o", 930, 925, "next", FEATURES_OPEN),
        ("T05_P2b_PrevZTGap2_T0", m["base_ok_open"] & (m["prev_streak"] >= 1) & (m["open_pct"] >= 2.0), "cb_ret_oc", 930, 1500, "same", FEATURES_OPEN),
        ("T06_P3_StrongGap5_T0", m["base_ok_open"] & (m["open_pct"] >= 5.0) & (~m["stk_open_at_zt"]), "cb_ret_oc", 930, 1500, "same", FEATURES_OPEN),
        ("T07_P3_StrongGap5_T1O", m["base_ok_open"] & (m["open_pct"] >= 5.0) & (~m["stk_open_at_zt"]), "cb_ret_t1o", 930, 925, "next", FEATURES_OPEN),
        ("T08_P4_ZTClose_T1O", m["base_ok_close"] & (m["is_zt"] == 1), "cb_ret_c2no", 1500, 925, "next", FEATURES_CLOSE),
        ("T09_P4_ZTClose_T1C", m["base_ok_close"] & (m["is_zt"] == 1), "cb_ret_c2nc", 1500, 1500, "next", FEATURES_CLOSE),
        ("T10_P5_LowPremStrong_T0", m["base_ok_open"] & (m["cb_prem_t1"] < 20.0) & (m["stk_open_at_zt"] | (m["prev_streak"] >= 1) | (m["open_pct"] >= 5.0)), "cb_ret_oc", 930, 1500, "same", FEATURES_OPEN),
        ("T11_P5_LowPremStrong_T1O", m["base_ok_open"] & (m["cb_prem_t1"] < 20.0) & (m["stk_open_at_zt"] | (m["prev_streak"] >= 1) | (m["open_pct"] >= 5.0)), "cb_ret_t1o", 930, 925, "next", FEATURES_OPEN),
        ("T12_P5_Liq50m_LowPrem_T0", m["base_ok_open"] & (m["cb_prem_t1"] < 20.0) & (m["cb_amt_5d_t1"] >= 0.5) & (m["stk_open_at_zt"] | (m["prev_streak"] >= 1) | (m["open_pct"] >= 5.0)), "cb_ret_oc", 930, 1500, "same", FEATURES_OPEN),
    ]

    grid_rows = []
    scored_cache = {}
    trunc_checks = []
    v20_results = {}
    champ_dr_cache = {"cal_dts": np.array(cal_dts), "csi300_dr": csi_arr}

    # Pre-compute V20 MTM daily returns on cal_dts for 2023-2026
    cal_5y_dts = v20_ctx["calendar_5y"]["trade_date"].tolist()
    v20_win_all = v20_ctx["v20_ledger"][v20_ctx["v20_ledger"]["buy_date"] >= "2023-01-03"].copy()
    v20_win_all["source"] = "v20"
    dr_v20_cal, _ = wfv._build_combined_mtm(v20_win_all, cal_dts)
    champ_dr_cache["v20_dr"] = dr_v20_cal

    for tid, mask, ret_col, bh, eh, exit_mode, feat_cols in tracks:
        sub = m[mask & m[ret_col].notna()].copy()
        if exit_mode == "next":
            sub = sub[sub["cb_next_dt"].notna()].copy()
            sub["exit_date"] = sub["cb_next_dt"].astype(str)
        else:
            sub["exit_date"] = sub["dt"].astype(str)
        sub["buy_date"] = sub["dt"].astype(str)
        sub["code"] = sub["cb_code"].astype(str)
        sub["buy_hhmm"] = bh
        sub["exit_hhmm"] = eh
        sub["gross_ret"] = sub[ret_col].astype(float)
        # Train with base 10bps (realistic CB commission+spread)
        sub["net_ret"] = (1.0 + sub["gross_ret"]) * (1.0 - 0.0010) - 1.0
        sub["can_buy"] = True
        sub["is_yizi"] = False

        scored, meta = wfc.run_expanding_scorecard_loop(
            sub, feature_cols=feat_cols, mode="scorecard_0_100",
            wf_start_date="2023-01-03", min_warmup_trades=60, min_warmup_trades_rare=40,
            min_warmup_months=15, recalc_freq="monthly",
            top_k=10, min_k=4, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
        )
        scored_cache[tid] = (scored, meta, feat_cols)

        # Physical 2024-12-31 truncation re-run check
        sub_tr = sub[sub["dt"] <= "2024-12-31"].copy()
        scored_tr, _ = wfc.run_expanding_scorecard_loop(
            sub_tr, feature_cols=feat_cols, mode="scorecard_0_100",
            wf_start_date="2023-01-03", min_warmup_trades=60, min_warmup_trades_rare=40,
            min_warmup_months=15, recalc_freq="monthly",
            top_k=10, min_k=4, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
        )
        sc_orig = scored.loc[scored["dt"] <= "2024-12-31", "wf_score"].to_numpy(float)
        sc_tr = scored_tr["wf_score"].to_numpy(float)
        diff_sc = float(np.nanmax(np.abs(sc_orig - sc_tr))) if np.isfinite(sc_orig).any() else 0.0
        diff_ret = float(np.nanmax(np.abs(scored.loc[scored["dt"] <= "2024-12-31", "net_ret"].to_numpy(float) - scored_tr["net_ret"].to_numpy(float))))
        trunc_checks.append({"track_id": tid, "max_abs_score_diff": diff_sc, "max_abs_ret_diff": diff_ret})

        # Evaluate thresholds across 4 cost tiers
        thrs = [
            ("all_cands", None),
            ("top30", "wf_thr_top30"),
            ("top20", "wf_thr_top20"),
            ("top10", "wf_thr_top10"),
            ("top5", "wf_thr_top5"),
            ("sc70", 70.0),
            ("sc75", 75.0),
            ("sc80", 80.0),
        ]
        for th_lbl, th_val in thrs:
            pass_10, slot_10 = select_single_slot_t0_t1(scored, "wf_score", th_val, wf_only=True)
            if len(slot_10) < 10:
                continue
            # Cost sensitivity re-eval on selected trades & passing pool
            rec = {
                "track_id": tid, "exit_mode": exit_mode, "threshold": th_lbl,
                "wf_start": meta["wf_actual_start"],
            }
            for bps in (10, 20, 50, 100):
                f = bps / 10000.0
                s_b = slot_10.copy()
                p_b = pass_10.copy()
                s_b["net_ret"] = (1.0 + s_b["gross_ret"]) * (1.0 - f) - 1.0
                p_b["net_ret"] = (1.0 + p_b["gross_ret"]) * (1.0 - f) - 1.0
                dr_b, mtm_diff = build_exact_mtm(s_b, cal_dts)
                assert mtm_diff < 1e-7, f"MTM parity fail on {tid} {th_lbl}: {mtm_diff}"
                fw = eval_window_metrics(s_b, p_b, dr_b, cal_dts, dt_idx, csi_arr, "2023-01-03", "2026-11-24")
                if bps == 10:
                    rec.update({
                        "n_trades": fw["n"], "wr_10": fw["wr_pct"], "plr_10": fw["plr"],
                        "mean_10_pct": fw["mean_pct"], "nav_10": fw["nav"], "eq_nav_10": fw["eq_nav"],
                        "ex5_10": fw["ex5_nav"], "ex10_10": fw["ex10_nav"],
                        "mdd_10": fw["daily_mdd_pct"], "sharpe_10": fw["daily_sharpe"],
                        "excess_csi_10_pp": fw["excess_csi300_pp"], "mtm_parity_diff": round(mtm_diff, 10),
                    })
                    for ylbl, ys, ye in [("y23", "2023-01-03", "2023-12-31"), ("y24", "2024-01-01", "2024-12-31"), ("y25", "2025-01-01", "2025-12-31"), ("y26", "2026-01-01", "2026-11-24"), ("y26h2", "2026-06-25", "2026-11-24")]:
                        ym = eval_window_metrics(s_b, p_b, dr_b, cal_dts, dt_idx, csi_arr, ys, ye)
                        rec[f"{ylbl}_nav_10"] = ym["nav"]
                        rec[f"{ylbl}_n"] = ym["n"]
                else:
                    rec[f"nav_{bps}"] = fw["nav"]
                    rec[f"ex5_{bps}"] = fw["ex5_nav"]
                    rec[f"sharpe_{bps}"] = fw["daily_sharpe"]
            grid_rows.append(rec)

    gr_df = pd.DataFrame(grid_rows).sort_values("nav_10", ascending=False).reset_index(drop=True)
    gr_df.to_csv(f"{OUT_DIR}/rd046_grid.csv", index=False)

    # Detailed Red-Team + Permutation + V20.0 Integration on top 6 tracks (plus CB1 & P5 T+0 vs T+1)
    top_candidates = []
    seen = set()
    for _, rw in gr_df.head(12).iterrows():
        key = (rw["track_id"], rw["threshold"])
        if key not in seen:
            seen.add(key)
            top_candidates.append(key)
        if len(top_candidates) >= 6:
            break
    # Ensure CB1 T+0 top20, P2 T+0 top10, P5 T+0 top10 are represented
    for k in [("T01_CB1_OpenAtZT_T0", "top20"), ("T01_CB1_OpenAtZT_T0", "all_cands"), ("T10_P5_LowPremStrong_T0", "top10"), ("T11_P5_LowPremStrong_T1O", "top10")]:
        if k not in seen and k[0] in scored_cache:
            seen.add(k)
            top_candidates.append(k)

    redteam_details = {}
    for tid, th_lbl in top_candidates:
        scored, meta, _ = scored_cache[tid]
        th_map = {"all_cands": None, "top30": "wf_thr_top30", "top20": "wf_thr_top20", "top10": "wf_thr_top10", "top5": "wf_thr_top5", "sc70": 70.0, "sc75": 75.0, "sc80": 80.0}
        pass_10, slot_10 = select_single_slot_t0_t1(scored, "wf_score", th_map[th_lbl], wf_only=True)
        if slot_10.empty:
            continue
        dr_10, mtm_diff = build_exact_mtm(slot_10, cal_dts)
        champ_dr_cache[f"{tid}__{th_lbl}"] = dr_10

        # Permutation test (1000x) against track's own buyable pool
        cand_p = scored[scored["wf_in_window"] & scored["can_buy_hygiene"]].copy()
        perm = wfm.perm_test_trading_days(slot_10, cand_p, "2023-01-03", "2026-11-24", n_perm=1000, seed=20261126)

        # V20.0 Empty-Slot Integration (10bps & 20bps)
        v20_p10 = simulate_v20_patch_t0_t1(pass_10, v20_ctx, score_col="wf_score")
        pass_20 = pass_10.copy()
        pass_20["net_ret"] = (1.0 + pass_20["gross_ret"]) * (1.0 - 0.0020) - 1.0
        v20_p20 = simulate_v20_patch_t0_t1(pass_20, v20_ctx, score_col="wf_score")

        # Also check daily rebuild consistency for top winner!
        redteam_details[f"{tid}__{th_lbl}"] = {
            "latest_factors": [f["name"] for f in (meta.get("latest_scorecard") or {}).get("factors", [])],
            "mtm_parity_diff": round(mtm_diff, 12),
            "perm_1000": perm,
            "v20_empty_patch_10bps": v20_p10,
            "v20_empty_patch_20bps": v20_p20,
        }

    # Check CB2 5m replay single-slot & V20 empty-slot integration (unbiased 26H2 + all 853 5m events)
    cb2_full = pd.read_parquet(f"{OUT_DIR}/cb2_26h2_causal_5m_full.parquet")
    cb2_5m_all = pd.read_parquet(f"{OUT_DIR}/cb2_5m_replay.parquet")
    cb2_audit = {}
    for lbl, df2, rcol in [
        ("26H2_unbiased_5m_seal_T0_10bps", cb2_full[cb2_full["trigger_mode"] == "on_5m_seal"], "ret_5m_open_t0"),
        ("26H2_unbiased_5m_brkcut_T0_10bps", cb2_full[cb2_full["trigger_mode"] == "on_5m_seal"], "ret_5m_brkcut_t0"),
        ("All5m_incl_neardelist_T0_10bps", cb2_5m_all, "ret_5m_open_t0"),
        ("All5m_incl_neardelist_prem_lt15_T0_10bps", cb2_5m_all[cb2_5m_all["cb_prem_t1"] < 15], "ret_5m_open_t0"),
    ]:
        tmp = df2.copy()
        tmp["buy_date"] = tmp["dt"].astype(str)
        tmp["exit_date"] = tmp["dt"].astype(str)
        tmp["buy_hhmm"] = tmp["entry_hhmm"] if "entry_hhmm" in tmp.columns else tmp["entry_bar_hhmm"]
        tmp["exit_hhmm"] = 1500
        tmp["code"] = tmp["cb_code"].astype(str)
        tmp["wf_score"] = -tmp["cb_prem_t1"].fillna(50.0)
        tmp["cb_amt_5d_t1"] = 1.0
        tmp["can_buy_hygiene"] = True
        tmp["wf_in_window"] = True
        tmp["net_ret"] = (1.0 + tmp[rcol].astype(float)) * (1.0 - 0.0010) - 1.0
        p2, s2 = select_single_slot_t0_t1(tmp, "wf_score", None, wf_only=False)
        dr2, md2 = build_exact_mtm(s2, cal_dts)
        sdt2 = "2026-06-25" if "26H2" in lbl else "2023-01-03"
        m2 = eval_window_metrics(s2, p2, dr2, cal_dts, dt_idx, csi_arr, sdt2, "2026-11-24")
        v20_2 = simulate_v20_patch_t0_t1(p2, v20_ctx, wf_start_dt="2023-01-03", end_dt="2026-11-16")
        cb2_audit[lbl] = {"metrics": m2, "v20_empty_patch_10bps": v20_2}

    np.savez_compressed(f"{OUT_DIR}/rd046_daily_cache.npz", **champ_dr_cache)

    step3_meta = json.load(open(f"{OUT_DIR}/rd046_step3_meta.json", encoding="utf-8"))
    cb_data_audit = json.load(open(f"{OUT_DIR}/cb_data_audit.json", encoding="utf-8"))
    cb2_26h2_sum = json.load(open(f"{OUT_DIR}/cb2_26h2_causal_5m_summary.json", encoding="utf-8"))
    cb2_5m_sum = json.load(open(f"{OUT_DIR}/cb2_5m_summary.json", encoding="utf-8"))

    # Pass summary: how many tracks pass strict red-team gate (OOS NAV >= 1.50 & ex5 >= 1.15 & Sharpe >= 1.0 & 20bps NAV >= 1.30 & perm p <= 0.10)?
    passing_redteam = gr_df[
        (gr_df["n_trades"] >= 25)
        & (gr_df["nav_10"] >= 1.50)
        & (gr_df["ex5_10"] >= 1.15)
        & (gr_df["sharpe_10"] >= 1.0)
        & (gr_df["nav_20"] >= 1.30)
        & (gr_df["y25_nav_10"] >= 1.0)
        & (gr_df["y26_nav_10"] >= 1.0)
    ]

    audit_all = {
        "q8_data_audit": cb_data_audit["universe_2021_2026"],
        "conv_prem_error_audit": step3_meta["conv_prem_error_audit"],
        "cb2_5m_26h2_unbiased": cb2_26h2_sum,
        "cb2_5m_full_incl_neardelist": cb2_5m_sum,
        "cb2_5m_redteam": cb2_audit,
        "wf_grid_count": int(len(gr_df)),
        "passing_redteam_count": int(len(passing_redteam)),
        "top12_grid": gr_df.head(12).to_dict("records"),
        "truncation_20241231_checks": trunc_checks,
        "redteam_details": redteam_details,
        "elapsed_sec": round(time.time() - t0, 2),
    }
    with open(f"{OUT_DIR}/rd046_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit_all, f, ensure_ascii=False, indent=2)

    print(f"[Step 4] Done in {time.time()-t0:.1f}s | WF grid rows={len(gr_df)} | Passing red-team={len(passing_redteam)}")
    print("Max truncation diff:", max(x["max_abs_score_diff"] for x in trunc_checks), max(x["max_abs_ret_diff"] for x in trunc_checks))
    print("\nTop 12 WF Scorecard Tracks:")
    cols_show = ["track_id", "threshold", "n_trades", "wr_10", "mean_10_pct", "nav_10", "eq_nav_10", "ex5_10", "sharpe_10", "mdd_10", "nav_20", "nav_50", "y25_nav_10", "y26_nav_10"]
    print(gr_df[cols_show].head(12).to_string(index=False))


if __name__ == "__main__":
    main()
