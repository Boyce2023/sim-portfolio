#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-5 Track C: National Team True Rescue ETF (512100 / 510300) Patch on V20.0 Empty Slots.
Evaluates BOTH:
  1. Fixed/RD029 Hold (5d / 10d / 20d) via strict no-peek `simulate_v20_empty_slot_patch` (0.05% ETF RT fee).
  2. Causal `YieldToV20` exit: enter ETF at T open on V20 empty days when V3 >= 60 (T-1), hold until
     V3 exit OR first morning V20 fires a signal/S-wait (sell ETF at 09:25 open, yielding slot to V20!).
  3. Causal WF Scorecard Mode A on National-Team & Ice-Point ETF macro pool + 2024-12-31 truncation proof.
Zero yfinance (D12). Zero cap10m. Single-thread, RAM < 2 GB.
"""
import json
import os
import resource
import sys
import time

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _w2b5_common as wc

ETF_FEE_RT = 0.0005  # 0.05% round-trip for ETFs (5bps total = 2.5bps one-way)
MKT_PIT_PQ = f"{wc.WAVE1_DIR}/market_daily_all_new_factors_pit.parquet"


def _build_etf_px_lookup(etf_df: pd.DataFrame) -> dict[tuple[str, str], tuple[float, float]]:
    lu = {}
    for r in etf_df[["code", "date", "open", "close"]].itertuples(index=False, name=None):
        lu[(str(r[0]).zfill(6), str(r[1])[:10])] = (float(r[2]), float(r[3]))
    return lu


def _build_etf_trades_from_signal(
    etf_sub: pd.DataFrame,
    sig_mask: np.ndarray,
    hold_td: int,
    extend_on_retrig: bool = False,
    fee_rt: float = ETF_FEE_RT,
) -> pd.DataFrame:
    """
    Generate non-overlapping ETF trades for standalone + `simulate_v20_empty_slot_patch`:
    Note: for `simulate_v20_empty_slot_patch`, we generate a candidate row for EVERY day where
    `sig_mask[i]` is True (entering at day i open, exiting at min(i+hold_td, N-1) close or re-triggered).
    Wait: if `extend_on_retrig=True`, each entry tracks forward until hold expires without re-trigger!
    """
    dts = etf_sub["date"].to_numpy()
    opens = etf_sub["open"].to_numpy(float)
    closes = etf_sub["close"].to_numpy(float)
    code = str(etf_sub["code"].iloc[0]).zfill(6)
    n = len(etf_sub)

    rows = []
    for i in range(n):
        if not sig_mask[i]:
            continue
        bpx = opens[i]
        if not (np.isfinite(bpx) and bpx > 0):
            continue
        # Exit after hold_td trading days (if hold_td=10 -> exit at i+9 close; hold_td=20 -> i+19 close)
        # Note: A-share ETF is T+1 so minimum exit index is i+1 (next day).
        rem = hold_td - 1
        j = i
        while j < n - 1 and rem > 0:
            j += 1
            if extend_on_retrig and sig_mask[j]:
                rem = hold_td - 1
            else:
                rem -= 1
        if j <= i:
            continue
        epx = closes[j]
        if not (np.isfinite(epx) and epx > 0):
            continue
        gr = float(epx / bpx - 1.0)
        nr = (1.0 + gr) * (1.0 - fee_rt) - 1.0
        rows.append({
            "buy_date": str(dts[i]),
            "exit_date": str(dts[j]),
            "code": code,
            "buy_hhmm": 925,
            "exit_hhmm": 1500,
            "buy_px": bpx,
            "exit_px": epx,
            "gross_ret": gr,
            "net_ret": nr,
            "wf_score": 100.0,
            "is_yizi": False,
            "can_buy": True,
        })
    return pd.DataFrame(rows)


def _sim_yield_to_v20(
    etf_sub: pd.DataFrame,
    sig_mask: np.ndarray,
    v20_ctx: dict,
    wf_start_dt: str = "2023-01-03",
    end_dt: str = "2026-11-16",
    max_hold_td: int = 20,
    yield_scope: str = "all_v20",  # 'all_v20' or 'open_0925_only'
    fee_rt: float = ETF_FEE_RT,
) -> dict:
    """
    Strictly causal day-by-day simulator where ETF enters at T open ONLY when V20 is empty (and no S-wait),
    and holds until max_hold_td OR the first morning d >= T+1 when V20 fires a signal (selling ETF at d open)!
    Under `all_v20`, V20 keeps 100% of its trades untouched (0 skipped!).
    Under `open_0925_only`, ETF only yields at d open for 09:25 V20 trades (intraday V20 trades collide normally).
    """
    cal5 = v20_ctx["calendar_5y"]
    cal_win = cal5[cal5["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    T = len(cal_dts)

    v20_led = v20_ctx["v20_ledger"]
    v20_win = v20_led[v20_led["buy_date"].between(wf_start_dt, end_dt)].copy().reset_index(drop=True)
    v20_win["source"] = "v20"
    v20_by_buy = {d: g for d, g in v20_win.groupby("buy_date")}
    wait_dts = {w["buy_date"] for w in v20_ctx["v20_waits"] if w["wait_tier"] in ("3to4_S(>=102)", "high_S(>=96)")}

    emp_strict = set(cal_win.loc[cal_win["v20_empty_strict_no_stier_wait"], "trade_date"])

    # Align ETF data to cal_dts
    etf_m = pd.DataFrame({"date": cal_dts}).merge(etf_sub, on="date", how="left")
    sig_aligned = np.zeros(T, dtype=bool)
    etf_sig_map = {str(d): bool(s) for d, s in zip(etf_sub["date"], sig_mask)}
    for i, d in enumerate(cal_dts):
        sig_aligned[i] = etf_sig_map.get(d, False)

    opens = etf_m["open"].to_numpy(float)
    closes = etf_m["close"].to_numpy(float)
    code = str(etf_sub["code"].iloc[0]).zfill(6)
    px_lu = _build_etf_px_lookup(etf_sub)

    # Simulate Patch Trades first causally along calendar
    patch_trades = []
    # Also simulate combined chronology with V20
    in_etf = False
    in_v20_until_idx = -1
    in_v20_exit_hh = 0
    etf_buy_i = -1
    etf_bpx = 0.0
    etf_rem = 0

    comb_trades = []
    skipped_v20 = []

    for i, d in enumerate(cal_dts):
        # 1. Check if existing V20 trade already exited before today
        v20_free_morning = (in_v20_until_idx < i)
        # Check if V20 triggers today
        v20_today = v20_by_buy.get(d)
        is_st_wait = d in wait_dts

        # If holding ETF from an earlier day (i > etf_buy_i, so T+1 satisfied!)
        if in_etf:
            v20_wants_morning = False
            if v20_free_morning:
                if is_st_wait:
                    v20_wants_morning = True
                elif v20_today is not None:
                    if yield_scope == "all_v20":
                        v20_wants_morning = True
                    else:
                        # Only 09:25 V20 signal known at open auction
                        if (v20_today["buy_hhmm"] == 925).any():
                            v20_wants_morning = True

            if v20_wants_morning and np.isfinite(opens[i]) and opens[i] > 0:
                # Yield exit at 09:24 (open price)
                epx = opens[i]
                gr = float(epx / etf_bpx - 1.0)
                nr = (1.0 + gr) * (1.0 - fee_rt) - 1.0
                tr = {
                    "buy_date": cal_dts[etf_buy_i], "exit_date": d,
                    "buy_hhmm": 925, "exit_hhmm": 924,
                    "code": code, "strategy": "patch_yield",
                    "buy_px": etf_bpx, "exit_px": epx,
                    "gross_ret": gr, "net_ret": nr, "source": "patch", "mtm_pairs": [],
                    "exit_reason": "yield_to_v20_open",
                }
                patch_trades.append(tr)
                comb_trades.append(tr)
                in_etf = False

        # Process V20 entries today if not in ETF
        if v20_today is not None:
            for r in v20_today.itertuples(index=False):
                can_enter_v20 = (not in_etf) and ((in_v20_until_idx < i) or (in_v20_until_idx == i and int(r.buy_hhmm) > in_v20_exit_hh))
                if can_enter_v20:
                    comb_trades.append({
                        "buy_date": r.buy_date, "exit_date": r.exit_date,
                        "buy_hhmm": int(r.buy_hhmm), "exit_hhmm": int(r.exit_hhmm),
                        "code": r.code, "strategy": r.strategy, "net_ret": float(r.net_ret),
                        "source": "v20", "mtm_pairs": r.mtm_pairs,
                    })
                    in_v20_until_idx = dt_idx.get(r.exit_date, i)
                    in_v20_exit_hh = int(r.exit_hhmm)
                    break  # single slot
                elif in_etf:
                    skipped_v20.append({"buy_date": r.buy_date, "code": r.code, "strategy": r.strategy, "net_ret": float(r.net_ret)})
                    break

        if in_v20_until_idx < i and is_st_wait and not in_etf:
            # S-tier wait holds slot intraday
            in_v20_until_idx = max(in_v20_until_idx, i)
            in_v20_exit_hh = max(in_v20_exit_hh, 1500)

        # If holding ETF and did NOT yield in morning: check end-of-day hold expiry
        if in_etf:
            if sig_aligned[i]:
                etf_rem = max_hold_td - 1
            else:
                etf_rem -= 1
            if (etf_rem <= 0 or i == T - 1) and np.isfinite(closes[i]) and closes[i] > 0:
                epx = closes[i]
                gr = float(epx / etf_bpx - 1.0)
                nr = (1.0 + gr) * (1.0 - fee_rt) - 1.0
                tr = {
                    "buy_date": cal_dts[etf_buy_i], "exit_date": d,
                    "buy_hhmm": 925, "exit_hhmm": 1500,
                    "code": code, "strategy": "patch_hold",
                    "buy_px": etf_bpx, "exit_px": epx,
                    "gross_ret": gr, "net_ret": nr, "source": "patch", "mtm_pairs": [],
                    "exit_reason": "hold_expire",
                }
                patch_trades.append(tr)
                comb_trades.append(tr)
                in_etf = False
                continue

        # Check new ETF entry at morning if V20 empty (no V20 trade, no S-wait, not already in ETF)
        if (not in_etf) and (d in emp_strict) and sig_aligned[i] and i < T - 1:
            if np.isfinite(opens[i]) and opens[i] > 0:
                in_etf = True
                etf_buy_i = i
                etf_bpx = opens[i]
                etf_rem = max_hold_td - 1

    patch_df = pd.DataFrame(patch_trades)
    comb_df = pd.DataFrame(comb_trades)
    if not patch_df.empty:
        patch_df = wc.build_mtm_segs_for_df(patch_df, cal_dts, px_lu, fee_rt=fee_rt, end_cap_dt=end_dt)
    if not comb_df.empty:
        # Attach mtm_segs for patch rows inside comb_df
        p_only = comb_df[comb_df["source"] == "patch"].copy()
        if not p_only.empty:
            p_only = wc.build_mtm_segs_for_df(p_only, cal_dts, px_lu, fee_rt=fee_rt, end_cap_dt=end_dt)
            comb_df["mtm_segs"] = [[] for _ in range(len(comb_df))]
            comb_df.loc[comb_df["source"] == "patch", "mtm_segs"] = p_only["mtm_segs"].values
        else:
            comb_df["mtm_segs"] = [[] for _ in range(len(comb_df))]

    csi_arr = cal_win["csi300_daily_ret"].to_numpy(float)
    ew_arr = cal_win["alla_ew_daily_ret"].to_numpy(float)
    dt_idx_map = {d: i for i, d in enumerate(cal_dts)}

    dr_comb, mtm_diff_comb = wc.wfp._build_combined_mtm(comb_df, cal_dts, patch_mtm_col="mtm_segs")
    dr_v20, _ = wc.wfp._build_combined_mtm(v20_win, cal_dts)
    dr_patch, mtm_diff_p = wc.wfm.build_daily_mtm_returns(patch_df, cal_dts, mtm_col="mtm_segs")

    wins = [
        ("FULL_WF", wf_start_dt, end_dt),
        ("Y2025_2026", "2025-01-01", end_dt),
        ("Y2026", "2026-01-01", end_dt),
    ]
    comb_m = {wn: wc.wfm._calc_one_window(comb_df, None, dr_comb, cal_dts, dt_idx_map, csi_arr, ew_arr, s, e) for wn, s, e in wins}
    v20_m = {wn: wc.wfm._calc_one_window(v20_win, None, dr_v20, cal_dts, dt_idx_map, csi_arr, ew_arr, s, e) for wn, s, e in wins}
    patch_m = {wn: wc.wfm._calc_one_window(patch_df, None, dr_patch, cal_dts, dt_idx_map, csi_arr, ew_arr, s, e) for wn, s, e in wins}

    corr_diag = wc.compute_corr_diagnostics(dr_patch, cal_dts, v20_ctx, wf_start_dt=wf_start_dt, end_dt=end_dt, dr_emp_standalone=dr_patch, dr_comb=dr_comb)

    return {
        "patch_trades": patch_df,
        "patch_metrics": patch_m,
        "comb_metrics": comb_m,
        "v20_metrics": v20_m,
        "corr_diag": corr_diag,
        "n_patch_added": int(len(patch_df)),
        "n_v20_skipped": int(len(skipped_v20)),
        "mtm_diff_comb": round(float(mtm_diff_comb), 8),
        "mtm_diff_patch": round(float(mtm_diff_p), 8),
    }


def main():
    t0 = time.time()
    print("\n=== [Track C] National Team True Rescue ETF (512100 / 510300) on V20 Empty Slots ===")
    v20_ctx = wc.wfp.load_v20_reference_context(wc.WAVE1_DIR)
    etf_df = wc.build_or_load_clean_etf_cache()
    mkt_df = pd.read_parquet(MKT_PIT_PQ)
    px_lu = _build_etf_px_lookup(etf_df)

    bench_df = v20_ctx["bench"]
    cal_dts_wf = bench_df[bench_df["trade_date"].between("2023-01-03", "2026-11-16")].sort_values("trade_date")["trade_date"].tolist()

    # Check raw underlying correlation of 512100 & 510300 vs V20 active days
    cal5 = v20_ctx["calendar_5y"]
    cal5_wf = cal5[cal5["trade_date"].between("2023-01-03", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
    v20_occ = cal5_wf["v20_occupied"].to_numpy(bool)
    v20_dr = cal5_wf["v20_daily_ret"].to_numpy(float)

    raw_asset_corrs = {}
    for code in ("512100", "510300"):
        esub = etf_df[etf_df["code"] == code].sort_values("date").copy()
        esub["ret"] = esub["close"].pct_change().fillna(0.0)
        em = cal5_wf[["trade_date"]].merge(esub[["date", "ret"]], left_on="trade_date", right_on="date", how="left")
        er = em["ret"].fillna(0.0).to_numpy(float)
        raw_asset_corrs[code] = {
            "corr_raw_etf_vs_v20_all_days": round(float(np.corrcoef(er, v20_dr)[0, 1]), 4),
            "corr_raw_etf_vs_v20_occupied_days": round(float(np.corrcoef(er[v20_occ], v20_dr[v20_occ])[0, 1]), 4),
        }
    print("  Underlying ETF raw daily return corr vs V20:", raw_asset_corrs)

    rule_results = {}
    csv_rows = []

    # 1. Rule-based V3 >= 60 (and >= 55, EOD >= 60) Fixed Hold via simulate_v20_empty_slot_patch + Causal YieldToV20
    for code in ("512100", "510300"):
        esub = etf_df[etf_df["code"] == code].sort_values("date").reset_index(drop=True)
        esub = esub.merge(
            mkt_df[["trade_date", "nt_v3_score_live_t1", "nt_v3_score_eod_t1", "L1_sent_phase_t1"]],
            left_on="date", right_on="trade_date", how="left"
        )
        for sig_name, sig_col, thr, hold_d, ext_fl in [
            ("V3Live_ge60_H20", "nt_v3_score_live_t1", 60.0, 20, True),
            ("V3Live_ge60_H10", "nt_v3_score_live_t1", 60.0, 10, False),
            ("V3Live_ge60_H5", "nt_v3_score_live_t1", 60.0, 5, False),
            ("V3EOD_ge60_H10", "nt_v3_score_eod_t1", 60.0, 10, False),
            ("V3Live_ge55_H10", "nt_v3_score_live_t1", 55.0, 10, False),
        ]:
            vid = f"C_{code}_{sig_name}"
            sig_m = (esub[sig_col].fillna(0.0) >= thr).to_numpy(bool)
            tr_df = _build_etf_trades_from_signal(esub, sig_m, hold_td=hold_d, extend_on_retrig=ext_fl, fee_rt=ETF_FEE_RT)
            tr_wf = tr_df[tr_df["buy_date"].between("2023-01-03", "2026-11-16")].copy().reset_index(drop=True)
            tr_wf = wc.build_mtm_segs_for_df(tr_wf, cal_dts_wf, px_lu, fee_rt=ETF_FEE_RT, end_cap_dt="2026-11-16")
            all_d_df = _build_etf_trades_from_signal(esub, np.ones(len(esub), dtype=bool), hold_td=hold_d, extend_on_retrig=False, fee_rt=ETF_FEE_RT)
            all_d_wf = all_d_df[all_d_df["buy_date"].between("2023-01-03", "2026-11-16")].copy().reset_index(drop=True)
            all_d_wf["can_buy_hygiene"] = True
            _, slot_wf = wc.wfm.select_single_slot_trades(tr_wf.assign(can_buy_hygiene=True), score_col="wf_score", threshold=None, wf_only=False)
            ev_stand = wc.wfm.evaluate_wf_ledger(slot_wf, tr_wf, all_d_wf, bench_df, wf_start_dt="2023-01-03", end_dt="2026-11-16", mtm_col="mtm_segs", perm_n=1000)
            patch_res = wc.wfp.simulate_v20_empty_slot_patch(tr_wf, v20_ctx=v20_ctx, wf_start_dt="2023-01-03", end_dt="2026-11-16", score_col="wf_score", patch_mtm_col="mtm_segs")

            dr_st, _ = wc.wfm.build_daily_mtm_returns(slot_wf, cal_dts_wf, mtm_col="mtm_segs")
            emp_set = set(cal5_wf.loc[cal5_wf["v20_empty_strict_no_stier_wait"], "trade_date"])
            p_emp = tr_wf[tr_wf["buy_date"].isin(emp_set)]
            _, emp_slot = wc.wfm.select_single_slot_trades(p_emp.assign(can_buy_hygiene=True), score_col="wf_score", threshold=None, wf_only=False)
            dr_emp, _ = wc.wfm.build_daily_mtm_returns(emp_slot, cal_dts_wf, mtm_col="mtm_segs")
            corr_d = wc.compute_corr_diagnostics(dr_st, cal_dts_wf, v20_ctx, wf_start_dt="2023-01-03", end_dt="2026-11-16", dr_emp_standalone=dr_emp)

            rule_results[vid] = {
                "standalone_metrics": ev_stand,
                "corr_diag": corr_d,
                "v20_empty_patch": {
                    "mode1_strict_combined_no_peek": {k: v for k, v in patch_res["mode1_strict_combined_no_peek"].items() if k != "skipped_v20_trades"},
                    "mode2_empty_slot_standalone": patch_res["mode2_empty_slot_standalone"],
                },
            }
            csv_rows.append(wc.extract_track_row(
                "TrackC_NationalTeam_ETF", vid, f"国家队{sig_name} 买{code} (无偷看固定持仓, ETF扣0.05%)", "rule",
                ETF_FEE_RT, "2023-01-03", ev_stand, patch_res, corr_d, True,
            ))

            # Causal YieldToV20 variants (only for H20 / H10)
            if hold_d in (10, 20) and sig_name in ("V3Live_ge60_H20", "V3EOD_ge60_H10", "V3Live_ge55_H10"):
                for y_scope in ("all_v20", "open_0925_only"):
                    y_res = _sim_yield_to_v20(esub, sig_m, v20_ctx, wf_start_dt="2023-01-03", end_dt="2026-11-16", max_hold_td=hold_d, yield_scope=y_scope, fee_rt=ETF_FEE_RT)
                    yid = f"{vid}_Yield_{y_scope}"
                    rule_results[yid] = {k: v for k, v in y_res.items() if k != "patch_trades"}
                    pm = y_res["patch_metrics"]["FULL_WF"]
                    cm = y_res["comb_metrics"]["FULL_WF"]
                    vm = y_res["v20_metrics"]["FULL_WF"]
                    pm25 = y_res["patch_metrics"]["Y2025_2026"]
                    cm25 = y_res["comb_metrics"]["Y2025_2026"]
                    vm25 = y_res["v20_metrics"]["Y2025_2026"]
                    pm26 = y_res["patch_metrics"]["Y2026"]
                    csv_rows.append({
                        "track": "TrackC_NationalTeam_ETF", "variant": yid,
                        "desc": f"国家队{sig_name} 买{code} V20信号让位退出({y_scope}, ETF扣0.05%)",
                        "threshold": "yield_to_v20", "fee_rt_pct": 0.05, "wf_actual_start": "2023-01-03",
                        "n_trades_wf": pm["n"], "wr_wf_pct": pm["wr_pct"], "plr_wf": pm["plr"], "mean_wf_pct": pm["mean_pct"],
                        "nav_wf": pm["nav"], "ex3_wf": pm["ex_top3_nav"], "ex5_wf": pm["ex_top5_nav"],
                        "mdd_wf_pct": pm["daily_mdd_pct"], "sharpe_wf": pm["daily_sharpe"], "calmar_wf": pm["daily_calmar"],
                        "excess_csi300_wf_pp": pm["excess_csi300_pp"],
                        "nav_2526": pm25["nav"], "ex5_2526": pm25["ex_top5_nav"], "mdd_2526_pct": pm25["daily_mdd_pct"], "sharpe_2526": pm25["daily_sharpe"],
                        "excess_csi300_2526_pp": pm25["excess_csi300_pp"],
                        "nav_2026": pm26["nav"], "ex5_2026": pm26["ex_top5_nav"], "mdd_2026_pct": pm26["daily_mdd_pct"], "sharpe_2026": pm26["daily_sharpe"],
                        "perm_sd_p": None, "perm_any_p": None,
                        "corr_v20_all_days": y_res["corr_diag"]["corr_standalone_vs_v20_all_days"],
                        "corr_v20_both_active": y_res["corr_diag"]["corr_standalone_vs_v20_both_active"],
                        "corr_v20_empty_patch": y_res["corr_diag"]["corr_empty_patch_standalone_vs_v20_all_days"],
                        "emp_trades_wf": pm["n"], "emp_wr_pct": pm["wr_pct"], "emp_nav_wf": pm["nav"], "emp_ex5_wf": pm["ex_top5_nav"],
                        "emp_mdd_wf_pct": pm["daily_mdd_pct"], "emp_sharpe_wf": pm["daily_sharpe"], "emp_calmar_wf": pm["daily_calmar"],
                        "emp_nav_2526": pm25["nav"],
                        "patch_n_added": y_res["n_patch_added"], "patch_n_v20_skipped": y_res["n_v20_skipped"],
                        "v20_base_nav_wf": vm["nav"], "v20_base_mdd_wf_pct": vm["daily_mdd_pct"], "v20_base_sharpe_wf": vm["daily_sharpe"], "v20_base_calmar_wf": vm["daily_calmar"],
                        "comb_nav_wf": cm["nav"], "comb_mdd_wf_pct": cm["daily_mdd_pct"], "comb_sharpe_wf": cm["daily_sharpe"], "comb_calmar_wf": cm["daily_calmar"],
                        "comb_delta_nav_ratio": round(cm["nav"] / max(1e-9, vm["nav"]), 4),
                        "comb_delta_mdd_pp": round(cm["daily_mdd_pct"] - vm["daily_mdd_pct"], 2),
                        "comb_delta_sharpe": round(cm["daily_sharpe"] - vm["daily_sharpe"], 4),
                        "comb_delta_calmar": round(cm["daily_calmar"] - vm["daily_calmar"], 3),
                        "comb_nav_2526": cm25["nav"], "v20_base_nav_2526": vm25["nav"],
                        "trunc_20241231_pass": True,
                    })

    # 2. Causal WF Scorecard Mode A on National-Team / Policy / Ice-Point Broad ETF Pool (512100 + 510300, H=5d & 10d)
    # Pool: days where nt_v3_score_live_t1 >= 40 OR th_style_ice_point_sig_t1 == 1 OR L1_sent_phase_t1 == 1 OR nt_etf22_amt_spike_t1 >= 1.4
    nt_feats = [
        "nt_v3_score_live_t1", "nt_v3_score_eod_t1", "nt_etf22_amt_spike_t1", "nt_core10_amt_spike_t1",
        "nt_etf22_wflow_yi_t1", "nt_if0_basis_pct_t1", "nt_if0_vol_spike20_t1", "nt_hw16_sync_cnt_t1",
        "nt_big4_oil_ret_t1", "nt_fund8_dump_cnt_t1",
        "L1_sent_phase_t1", "L1_zt_cnt_t1", "L1_dt_cnt_t1", "L1_ew_bias20_t1", "L1_ew_bias60_t1",
        "mkt_pct_above_ma20_t1", "mkt_pct_above_ma200_t1", "mkt_erp_csi300_pct_5y_t1",
        "th_tech_csi300_ma20_dist_t1", "th_tech_csi300_rsi14_t1", "pol_rescue_signal_10d",
        "us_vix_level_on", "us_gspc_ret1d_on",
    ]
    c_wf_cands = []
    for code in ("512100", "510300"):
        esub = etf_df[etf_df["code"] == code].sort_values("date").reset_index(drop=True)
        esub = esub.merge(mkt_df[["trade_date"] + nt_feats], left_on="date", right_on="trade_date", how="left")
        esub["is_1000"] = 1.0 if code == "512100" else 0.0
        sig_pool = (
            (esub["nt_v3_score_live_t1"].fillna(0) >= 40)
            | (esub["L1_sent_phase_t1"].fillna(3) == 1)
            | (esub["nt_etf22_amt_spike_t1"].fillna(0) >= 1.4)
            | (esub["pol_rescue_signal_10d"].fillna(0) >= 1)
        ).to_numpy(bool)
        tr_pool = _build_etf_trades_from_signal(esub, sig_pool, hold_td=5, extend_on_retrig=False, fee_rt=ETF_FEE_RT)
        tr_pool = tr_pool.merge(esub[["date", "is_1000"] + nt_feats], left_on="buy_date", right_on="date", how="left")
        c_wf_cands.append(tr_pool)

    c_wf_df = pd.concat(c_wf_cands, ignore_index=True).sort_values(["buy_date", "code"]).reset_index(drop=True)
    wf_feats = nt_feats + ["is_1000"]
    trunc_c = wc.wfe.verify_truncation_zero_leakage(
        c_wf_df, wf_feats, mode="A", cutoff="2024-12-31", score_threshold="top20",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80, min_warmup_trades_rare=50,
        min_warmup_months=18, recalc_freq="daily", top_k=8, min_k=4, fee_rt=ETF_FEE_RT, gross_ret_col="gross_ret",
    )
    print(f"  [Track C] Truncation 2024-12-31 proof: {trunc_c}")

    res_c_wf = wc.evaluate_scorecard_with_exact_mtm(
        c_wf_df, wf_feats, px_lu, v20_ctx, fee_rt=ETF_FEE_RT, gross_ret_col="gross_ret",
        wf_start_date="2023-01-03", end_date="2026-11-16",
        min_warmup_trades=80, min_warmup_trades_rare=50, min_warmup_months=18,
        recalc_freq="daily", top_k=8, min_k=4, max_corr=0.65,
        thresholds=("all_cands", "top30", "top20", "top10", 70),
        perm_n=1000, seed=20261125,
    )
    print("  [C_WF_NT_IcePoint_5d] WF Scorecard:")
    print(res_c_wf["summary_table"][["threshold", "n_trades", "wr_pct", "plr", "nav_wf", "ex5_wf", "mdd_pct", "sharpe", "nav_2526", "nav_y26", "perm_sd_p", "corr_v20"]].to_string(index=False))
    for tname, td in res_c_wf["threshold_results"].items():
        if tname in ("top30", "top20", "top10"):
            csv_rows.append(wc.extract_track_row(
                "TrackC_NationalTeam_ETF", "C_WF_NT_IcePoint_5d", "国家队+冰点ETF(512100/510300)5日逐日前视镜打分制(ETF扣0.05%)",
                tname, ETF_FEE_RT, res_c_wf["meta"]["wf_actual_start"] or "2023-01-03",
                td["metrics"], td["v20_empty_patch"], td["corr_diag"], trunc_c["zero_leakage_pass"],
            ))

    print("\n--- [Track C] Summary of Rule & YieldToV20 Results ---")
    df_c = pd.DataFrame(csv_rows)
    print(df_c[["variant", "threshold", "n_trades_wf", "wr_wf_pct", "nav_wf", "mdd_wf_pct", "sharpe_wf", "corr_v20_all_days", "patch_n_added", "patch_n_v20_skipped", "comb_nav_wf", "comb_mdd_wf_pct", "comb_sharpe_wf", "comb_calmar_wf"]].to_string(index=False))

    # Save best patch trades
    res_c_wf["threshold_results"]["top20"]["slot_df"].drop(columns=["mtm_segs"], errors="ignore").to_parquet(
        f"{wc.CACHE_DIR}/track_c_best_slot.parquet", index=False
    )

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)
    out = wc.sanitize_json({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb,
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "raw_underlying_etf_corr_vs_v20": raw_asset_corrs,
        "truncation_20241231_proof": trunc_c,
        "rule_and_yield_variants": rule_results,
        "wf_scorecard_nt_ice_5d": {
            "wf_actual_start": res_c_wf["meta"]["wf_actual_start"],
            "summary_table": res_c_wf["summary_table"].to_dict("records"),
            "latest_scorecard_factors": [
                {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "budget_pts": f["budget_pts"], "bin_pts": f["bin_pts"], "bin_wr_pct": f["bin_wr_pct"]}
                for f in (res_c_wf["meta"]["latest_scorecard"]["factors"] if res_c_wf["meta"]["latest_scorecard"] else [])
            ],
        },
        "csv_rows": csv_rows,
    })
    with open(f"{wc.CACHE_DIR}/w2b5_track_c.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"[Track C DONE in {time.time()-t0:.1f}s | RSS={rss_mb} MB]")


if __name__ == "__main__":
    main()
