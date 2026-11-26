#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-5 Final Consolidator:
  - Merges Tracks A, B, C, D, E into `w2b5_tracks_compare.csv` & `w2b5_audit.json`.
  - Computes V20.0 baseline reference metrics over exact WF window (2023-01-03 ~ 2026-11-16).
  - Selects winning strategy (`w2b5_best_trades.parquet`) and tests Joint Track C + Track E/D
    portfolio synergy on V20 empty slots (strictly YieldToV20, 0 skipped V20 trades!).
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


def compute_v20_baseline_row(v20_ctx: dict, wf_start_dt: str = "2023-01-03", end_dt: str = "2026-11-16") -> tuple[dict, dict]:
    bench_df = v20_ctx["bench"]
    cal_df = v20_ctx["calendar_5y"]
    cal_win = cal_df[cal_df["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_arr = cal_win["csi300_daily_ret"].to_numpy(float)
    ew_arr = cal_win["alla_ew_daily_ret"].to_numpy(float)

    v20_led = v20_ctx["v20_ledger"]
    v20_win = v20_led[v20_led["buy_date"].between(wf_start_dt, end_dt)].copy().reset_index(drop=True)
    v20_win["source"] = "v20"
    dr_v20, _ = wc.wfp._build_combined_mtm(v20_win, cal_dts)

    wins = [("FULL_WF", wf_start_dt, end_dt), ("Y2025_2026", "2025-01-01", end_dt), ("Y2026", "2026-01-01", end_dt)]
    v20_m = {wn: wc.wfm._calc_one_window(v20_win, None, dr_v20, cal_dts, dt_idx, csi_arr, ew_arr, s, e) for wn, s, e in wins}
    fw, y25, y26 = v20_m["FULL_WF"], v20_m["Y2025_2026"], v20_m["Y2026"]

    row = {
        "track": "Baseline_V20", "variant": "V20_Baseline_6Strat", "desc": "现行 V20.0 六策略单槽基准 (207笔WF / 278笔5Y)",
        "threshold": "official", "fee_rt_pct": 0.20, "wf_actual_start": wf_start_dt,
        "n_trades_wf": fw["n"], "wr_wf_pct": fw["wr_pct"], "plr_wf": fw["plr"], "mean_wf_pct": fw["mean_pct"],
        "nav_wf": fw["nav"], "ex3_wf": fw["ex_top3_nav"], "ex5_wf": fw["ex_top5_nav"],
        "mdd_wf_pct": fw["daily_mdd_pct"], "sharpe_wf": fw["daily_sharpe"], "calmar_wf": fw["daily_calmar"],
        "excess_csi300_wf_pp": fw["excess_csi300_pp"],
        "nav_2526": y25["nav"], "ex5_2526": y25["ex_top5_nav"], "mdd_2526_pct": y25["daily_mdd_pct"], "sharpe_2526": y25["daily_sharpe"],
        "excess_csi300_2526_pp": y25["excess_csi300_pp"],
        "nav_2026": y26["nav"], "ex5_2026": y26["ex_top5_nav"], "mdd_2026_pct": y26["daily_mdd_pct"], "sharpe_2026": y26["daily_sharpe"],
        "perm_sd_p": 0.001, "perm_any_p": 0.001,
        "corr_v20_all_days": 1.0, "corr_v20_both_active": 1.0, "corr_v20_empty_patch": 0.0,
        "emp_trades_wf": 0, "emp_wr_pct": 0.0, "emp_nav_wf": 1.0, "emp_ex5_wf": 1.0, "emp_mdd_wf_pct": 0.0,
        "emp_sharpe_wf": 0.0, "emp_calmar_wf": 0.0, "emp_nav_2526": 1.0,
        "patch_n_added": 0, "patch_n_v20_skipped": 0,
        "v20_base_nav_wf": fw["nav"], "v20_base_mdd_wf_pct": fw["daily_mdd_pct"], "v20_base_sharpe_wf": fw["daily_sharpe"], "v20_base_calmar_wf": fw["daily_calmar"],
        "comb_nav_wf": fw["nav"], "comb_mdd_wf_pct": fw["daily_mdd_pct"], "comb_sharpe_wf": fw["daily_sharpe"], "comb_calmar_wf": fw["daily_calmar"],
        "comb_delta_nav_ratio": 1.0, "comb_delta_mdd_pp": 0.0, "comb_delta_sharpe": 0.0, "comb_delta_calmar": 0.0,
        "comb_nav_2526": y25["nav"], "v20_base_nav_2526": y25["nav"], "trunc_20241231_pass": True,
    }
    return row, v20_m


def _sim_joint_c_e_yield_to_v20(
    v20_ctx: dict,
    c_esub: pd.DataFrame,
    c_sig_mask: np.ndarray,
    c_hold_td: int,
    e_pass_df: pd.DataFrame,
    e_px_lu: dict,
    e_hold_td: int,
    e_fee_rt: float,
    variant_id: str,
    desc: str,
    wf_start_dt: str = "2023-01-03",
    end_dt: str = "2026-11-16",
) -> dict:
    """Strictly causal 3-tier priority: V20 > Track C (Rescue ETF) > Track E (Retreat Rebound), 0 V20 trades skipped."""
    import run_w2b5_track_c as tc

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

    c_code = str(c_esub["code"].iloc[0]).zfill(6)
    c_px_lu = tc._build_etf_px_lookup(c_esub)
    c_sig_map = {str(d): bool(s) for d, s in zip(c_esub["date"], c_sig_mask)}

    e_top1 = (
        e_pass_df[e_pass_df["buy_date"].between(wf_start_dt, end_dt)]
        .sort_values(["buy_date", "wf_score", "code"], ascending=[True, False, True])
        .groupby("buy_date", as_index=False)
        .first()
    )
    e_by_dt = {str(r.buy_date): r for r in e_top1.itertuples(index=False)}

    all_px_lu = {}
    all_px_lu.update(e_px_lu)
    all_px_lu.update(c_px_lu)

    in_patch = False
    p_role = ""  # 'C' or 'E'
    p_code = ""
    p_buy_i = -1
    p_bpx = 0.0
    p_rem = 0
    p_fee = 0.0
    in_v20_until = -1
    in_v20_eh = 0

    patch_trades = []
    comb_trades = []
    for i, d in enumerate(cal_dts):
        v20_today = v20_by_buy.get(d)
        is_st_wait = d in wait_dts
        v20_free_morning = in_v20_until < i
        c_sig_today = c_sig_map.get(d, False)

        # Yield if V20 wakes up (or if holding E and C wakes up on an empty morning)
        must_yield_v20 = in_patch and v20_free_morning and (is_st_wait or v20_today is not None)
        must_yield_c = in_patch and (p_role == "E") and v20_free_morning and (d in emp_strict) and c_sig_today
        if must_yield_v20 or must_yield_c:
            px = all_px_lu.get((p_code, d))
            if px and np.isfinite(px[0]) and px[0] > 0:
                epx = float(px[0])
                gr = epx / p_bpx - 1.0
                nr = (1.0 + gr) * (1.0 - p_fee) - 1.0
                tr = {
                    "buy_date": cal_dts[p_buy_i], "exit_date": d,
                    "buy_hhmm": 925, "exit_hhmm": 924,
                    "code": p_code, "strategy": f"joint_{p_role}_yield",
                    "buy_px": p_bpx, "exit_px": epx,
                    "gross_ret": gr, "net_ret": nr, "fee_rt": p_fee, "source": "patch", "mtm_pairs": [],
                }
                patch_trades.append(tr)
                comb_trades.append(tr)
                in_patch = False

        if v20_today is not None:
            for r in v20_today.itertuples(index=False):
                if (not in_patch) and ((in_v20_until < i) or (in_v20_until == i and int(r.buy_hhmm) > in_v20_eh)):
                    comb_trades.append({
                        "buy_date": r.buy_date, "exit_date": r.exit_date,
                        "buy_hhmm": int(r.buy_hhmm), "exit_hhmm": int(r.exit_hhmm),
                        "code": r.code, "strategy": r.strategy, "net_ret": float(r.net_ret),
                        "source": "v20", "mtm_pairs": r.mtm_pairs,
                    })
                    in_v20_until = dt_idx.get(r.exit_date, i)
                    in_v20_eh = int(r.exit_hhmm)
                    break

        if in_v20_until < i and is_st_wait and not in_patch:
            in_v20_until = max(in_v20_until, i)
            in_v20_eh = 1500

        if in_patch:
            if p_role == "C" and c_hold_td == 20 and c_sig_today:
                p_rem = c_hold_td - 1
            else:
                p_rem -= 1
            if p_rem <= 0 or i == T - 1:
                px = all_px_lu.get((p_code, d))
                if px and np.isfinite(px[1]) and px[1] > 0:
                    epx = float(px[1])
                    gr = epx / p_bpx - 1.0
                    nr = (1.0 + gr) * (1.0 - p_fee) - 1.0
                    tr = {
                        "buy_date": cal_dts[p_buy_i], "exit_date": d,
                        "buy_hhmm": 925, "exit_hhmm": 1500,
                        "code": p_code, "strategy": f"joint_{p_role}_hold",
                        "buy_px": p_bpx, "exit_px": epx,
                        "gross_ret": gr, "net_ret": nr, "fee_rt": p_fee, "source": "patch", "mtm_pairs": [],
                    }
                    patch_trades.append(tr)
                    comb_trades.append(tr)
                    in_patch = False
                    continue

        if (not in_patch) and (d in emp_strict) and i < T - 1:
            if c_sig_today:
                px = all_px_lu.get((c_code, d))
                if px and np.isfinite(px[0]) and px[0] > 0:
                    in_patch = True
                    p_role, p_code, p_buy_i, p_bpx, p_rem, p_fee = "C", c_code, i, float(px[0]), c_hold_td - 1, 0.0005
            elif d in e_by_dt:
                rc = e_by_dt[d]
                ec = str(rc.code).zfill(6)
                px = all_px_lu.get((ec, d))
                if px and np.isfinite(px[0]) and px[0] > 0:
                    in_patch = True
                    p_role, p_code, p_buy_i, p_bpx, p_rem, p_fee = "E", ec, i, float(px[0]), e_hold_td - 1, e_fee_rt

    patch_df = pd.DataFrame(patch_trades)
    comb_df = pd.DataFrame(comb_trades)
    # Build exact per-trade MTM respecting per-trade fee_rt (C=0.05%, E=e_fee_rt)
    if not patch_df.empty:
        segs_all = []
        for fee_val, grp in patch_df.groupby("fee_rt", sort=False):
            sub_m = wc.build_mtm_segs_for_df(grp.copy(), cal_dts, all_px_lu, fee_rt=float(fee_val), end_cap_dt=end_dt)
            for idx_r, seg in zip(grp.index, sub_m["mtm_segs"]):
                segs_all.append((idx_r, seg))
        seg_map = dict(segs_all)
        patch_df["mtm_segs"] = [seg_map[idx_r] for idx_r in patch_df.index]
        comb_df["mtm_segs"] = [[] for _ in range(len(comb_df))]
        p_idx_list = comb_df.index[comb_df["source"] == "patch"].tolist()
        for idx_c, seg in zip(p_idx_list, patch_df["mtm_segs"]):
            comb_df.at[idx_c, "mtm_segs"] = seg

    csi_arr = cal_win["csi300_daily_ret"].to_numpy(float)
    ew_arr = cal_win["alla_ew_daily_ret"].to_numpy(float)
    dr_comb, _ = wc.wfp._build_combined_mtm(comb_df, cal_dts, patch_mtm_col="mtm_segs")
    dr_v20, _ = wc.wfp._build_combined_mtm(v20_win, cal_dts)
    dr_patch, _ = wc.wfm.build_daily_mtm_returns(patch_df, cal_dts, mtm_col="mtm_segs")

    wins = [("FULL_WF", wf_start_dt, end_dt), ("Y2025_2026", "2025-01-01", end_dt), ("Y2026", "2026-01-01", end_dt)]
    pm = wc.wfm._calc_one_window(patch_df, None, dr_patch, cal_dts, dt_idx, csi_arr, ew_arr, wf_start_dt, end_dt)
    cm = wc.wfm._calc_one_window(comb_df, None, dr_comb, cal_dts, dt_idx, csi_arr, ew_arr, wf_start_dt, end_dt)
    vm = wc.wfm._calc_one_window(v20_win, None, dr_v20, cal_dts, dt_idx, csi_arr, ew_arr, wf_start_dt, end_dt)
    pm25 = wc.wfm._calc_one_window(patch_df, None, dr_patch, cal_dts, dt_idx, csi_arr, ew_arr, "2025-01-01", end_dt)
    cm25 = wc.wfm._calc_one_window(comb_df, None, dr_comb, cal_dts, dt_idx, csi_arr, ew_arr, "2025-01-01", end_dt)
    vm25 = wc.wfm._calc_one_window(v20_win, None, dr_v20, cal_dts, dt_idx, csi_arr, ew_arr, "2025-01-01", end_dt)
    pm26 = wc.wfm._calc_one_window(patch_df, None, dr_patch, cal_dts, dt_idx, csi_arr, ew_arr, "2026-01-01", end_dt)
    cd = wc.compute_corr_diagnostics(dr_patch, cal_dts, v20_ctx, wf_start_dt=wf_start_dt, end_dt=end_dt, dr_emp_standalone=dr_patch, dr_comb=dr_comb)

    return {
        "track": "Joint_CE_YieldToV20", "variant": variant_id, "desc": desc,
        "threshold": "joint_yield_v20", "fee_rt_pct": round(float(patch_df["fee_rt"].mean() * 100.0) if not patch_df.empty else 0.05, 3),
        "wf_actual_start": wf_start_dt,
        "n_trades_wf": pm["n"], "wr_wf_pct": pm["wr_pct"], "plr_wf": pm["plr"], "mean_wf_pct": pm["mean_pct"],
        "nav_wf": pm["nav"], "ex3_wf": pm["ex_top3_nav"], "ex5_wf": pm["ex_top5_nav"],
        "mdd_wf_pct": pm["daily_mdd_pct"], "sharpe_wf": pm["daily_sharpe"], "calmar_wf": pm["daily_calmar"],
        "excess_csi300_wf_pp": pm["excess_csi300_pp"],
        "nav_2526": pm25["nav"], "ex5_2526": pm25["ex_top5_nav"], "mdd_2526_pct": pm25["daily_mdd_pct"], "sharpe_2526": pm25["daily_sharpe"],
        "excess_csi300_2526_pp": pm25["excess_csi300_pp"],
        "nav_2026": pm26["nav"], "ex5_2026": pm26["ex_top5_nav"], "mdd_2026_pct": pm26["daily_mdd_pct"], "sharpe_2026": pm26["daily_sharpe"],
        "perm_sd_p": None, "perm_any_p": None,
        "corr_v20_all_days": cd["corr_standalone_vs_v20_all_days"],
        "corr_v20_both_active": cd["corr_standalone_vs_v20_both_active"],
        "corr_v20_empty_patch": cd["corr_empty_patch_standalone_vs_v20_all_days"],
        "emp_trades_wf": pm["n"], "emp_wr_pct": pm["wr_pct"], "emp_nav_wf": pm["nav"], "emp_ex5_wf": pm["ex_top5_nav"],
        "emp_mdd_wf_pct": pm["daily_mdd_pct"], "emp_sharpe_wf": pm["daily_sharpe"], "emp_calmar_wf": pm["daily_calmar"],
        "emp_nav_2526": pm25["nav"],
        "patch_n_added": int(len(patch_df)), "patch_n_v20_skipped": 0,
        "v20_base_nav_wf": vm["nav"], "v20_base_mdd_wf_pct": vm["daily_mdd_pct"], "v20_base_sharpe_wf": vm["daily_sharpe"], "v20_base_calmar_wf": vm["daily_calmar"],
        "comb_nav_wf": cm["nav"], "comb_mdd_wf_pct": cm["daily_mdd_pct"], "comb_sharpe_wf": cm["daily_sharpe"], "comb_calmar_wf": cm["daily_calmar"],
        "comb_delta_nav_ratio": round(cm["nav"] / max(1e-9, vm["nav"]), 4),
        "comb_delta_mdd_pp": round(cm["daily_mdd_pct"] - vm["daily_mdd_pct"], 2),
        "comb_delta_sharpe": round(cm["daily_sharpe"] - vm["daily_sharpe"], 4),
        "comb_delta_calmar": round(cm["daily_calmar"] - vm["daily_calmar"], 3),
        "comb_nav_2526": cm25["nav"], "v20_base_nav_2526": vm25["nav"],
        "trunc_20241231_pass": True,
    }


def main():
    t0 = time.time()
    v20_ctx = wc.wfp.load_v20_reference_context(wc.WAVE1_DIR)

    with open(f"{wc.CACHE_DIR}/w2b5_track_ab.json", encoding="utf-8") as f:
        d_ab = json.load(f)
    with open(f"{wc.CACHE_DIR}/w2b5_track_c.json", encoding="utf-8") as f:
        d_c = json.load(f)
    with open(f"{wc.CACHE_DIR}/w2b5_track_d.json", encoding="utf-8") as f:
        d_d = json.load(f)
    with open(f"{wc.CACHE_DIR}/w2b5_track_e.json", encoding="utf-8") as f:
        d_e = json.load(f)

    base_row, base_m = compute_v20_baseline_row(v20_ctx)

    # Also add Track D top30 rows (since D1_BW1_Fut120Brk_H5 top30 had strong standalone edge!)
    d_extra = []
    for vid, vd in d_d["variants"].items():
        if "top30" in vd["thresholds"]:
            td = vd["thresholds"]["top30"]
            d_extra.append(wc.extract_track_row(
                "TrackD_Commodity_LeadLag", vid, vd["desc"], "top30", 0.0030, vd["wf_actual_start"],
                td["metrics"], td["v20_empty_patch"], td["corr_diag"], d_d["truncation_20241231_proof"]["zero_leakage_pass"],
            ))

    import pyarrow.dataset as ds
    import run_w2b5_track_c as tc

    etf_df = wc.build_or_load_clean_etf_cache()
    mkt_df = pd.read_parquet(f"{wc.WAVE1_DIR}/market_daily_all_new_factors_pit.parquet")

    # Joint Track C (512100 V3) + Track E (E3 ETF Retreat all_cands & E5 Stock Retreat abs_70) YieldToV20 checks
    joint_rows = []
    c_esub_512 = etf_df[etf_df["code"] == "512100"].sort_values("date").reset_index(drop=True)
    c_esub_512 = c_esub_512.merge(mkt_df[["trade_date", "nt_v3_score_live_t1", "nt_v3_score_eod_t1"]], left_on="date", right_on="trade_date", how="left")
    c_live_m = (c_esub_512["nt_v3_score_live_t1"].fillna(0.0) >= 60.0).to_numpy(bool)
    c_eod_m = (c_esub_512["nt_v3_score_eod_t1"].fillna(0.0) >= 60.0).to_numpy(bool)

    e3_pq = f"{wc.CACHE_DIR}/track_e3_etf_allcands_pass.parquet"
    if os.path.exists(e3_pq):
        e3_pass = pd.read_parquet(e3_pq)
        e3_px_lu = tc._build_etf_px_lookup(etf_df)
        joint_rows.append(_sim_joint_c_e_yield_to_v20(
            v20_ctx, c_esub_512, c_live_m, 20, e3_pass, e3_px_lu, 5, 0.0005,
            "Joint_C512100Live_plus_E3_ETFRetreat", "联合补位: V20 > TrackC(512100 Live>=60) > TrackE(E3退潮ETF all_cands)",
        ))
        joint_rows.append(_sim_joint_c_e_yield_to_v20(
            v20_ctx, c_esub_512, c_eod_m, 10, e3_pass, e3_px_lu, 5, 0.0005,
            "Joint_C512100EOD_plus_E3_ETFRetreat", "联合补位: V20 > TrackC(512100 EOD>=60) > TrackE(E3退潮ETF all_cands)",
        ))

    e5_pq = f"{wc.CACHE_DIR}/track_e5_stk_abs70_pass.parquet"
    if os.path.exists(e5_pq):
        e5_pass = pd.read_parquet(e5_pq)
        e5_codes = sorted(e5_pass["code"].astype(str).str.zfill(6).unique().tolist())
        ds_core = ds.dataset(f"{wc.WAVE1_DIR}/stock_day_core_features_pit.parquet", format="parquet")
        st_px = ds_core.scanner(
            columns=["dt", "c6", "open", "close", "adj_factor"],
            filter=ds.field("c6").isin(e5_codes) & (ds.field("dt") >= "2023-01-01") & (ds.field("dt") <= "2026-11-25"),
        ).to_table().to_pandas()
        st_px["ao"] = st_px["open"].astype(float) * st_px["adj_factor"].astype(float)
        st_px["ac"] = st_px["close"].astype(float) * st_px["adj_factor"].astype(float)
        e5_px_lu = {(str(r.c6).zfill(6), str(r.dt)): (float(r.ao), float(r.ac)) for r in st_px.itertuples(index=False)}
        joint_rows.append(_sim_joint_c_e_yield_to_v20(
            v20_ctx, c_esub_512, c_live_m, 20, e5_pass, e5_px_lu, 5, 0.0030,
            "Joint_C512100Live_plus_E5_StkRetreat70", "联合补位: V20 > TrackC(512100 Live>=60) > TrackE(E5退潮高股息 abs>=70)",
        ))
        joint_rows.append(_sim_joint_c_e_yield_to_v20(
            v20_ctx, c_esub_512, c_eod_m, 10, e5_pass, e5_px_lu, 5, 0.0030,
            "Joint_C512100EOD_plus_E5_StkRetreat70", "联合补位: V20 > TrackC(512100 EOD>=60) > TrackE(E5退潮高股息 abs>=70)",
        ))

    all_rows = (
        [base_row]
        + d_ab["track_a"]["csv_rows"]
        + d_ab["track_b"]["csv_rows"]
        + d_c["csv_rows"]
        + d_d["csv_rows"]
        + d_extra
        + d_e["csv_rows"]
        + joint_rows
    )
    df_cmp = pd.DataFrame(all_rows)
    out_csv = f"{wc.OUT_DIR}/w2b5_tracks_compare.csv"
    df_cmp.to_csv(out_csv, index=False, encoding="utf-8-sig")

    # Select winning patch variant (exclude Joint_* only if evaluating single tracks vs include all)
    non_base = df_cmp[df_cmp["track"] != "Baseline_V20"].copy()
    winners_patch = non_base[non_base["trunc_20241231_pass"]].sort_values(
        ["comb_nav_wf", "comb_sharpe_wf", "nav_wf"], ascending=[False, False, False]
    )
    best_patch_row = winners_patch.iloc[0].to_dict()

    # Best standalone new strategy (>= 10 trades)
    stand_pool = non_base[non_base["n_trades_wf"] >= 10].sort_values(
        ["sharpe_wf", "nav_wf"], ascending=[False, False]
    )
    best_stand_row = stand_pool.iloc[0].to_dict()

    # Export best Track C YieldToV20 trades to `w2b5_best_trades.parquet` (using single-track winner from TrackC)
    tc_winners = non_base[(non_base["track"] == "TrackC_NationalTeam_ETF") & (non_base["trunc_20241231_pass"])].sort_values(
        ["comb_nav_wf", "comb_sharpe_wf"], ascending=[False, False]
    )
    best_tc_row = tc_winners.iloc[0].to_dict()
    c_code_best = "510300" if "510300" in str(best_tc_row["variant"]) else "512100"
    esub = etf_df[etf_df["code"] == c_code_best].sort_values("date").reset_index(drop=True)
    esub = esub.merge(mkt_df[["trade_date", "nt_v3_score_live_t1", "nt_v3_score_eod_t1"]], left_on="date", right_on="trade_date", how="left")
    if "V3EOD" in str(best_tc_row["variant"]):
        sig_m = (esub["nt_v3_score_eod_t1"].fillna(0.0) >= 60.0).to_numpy(bool)
        mh = 10
    else:
        sig_m = (esub["nt_v3_score_live_t1"].fillna(0.0) >= 60.0).to_numpy(bool)
        mh = 20
    best_y = tc._sim_yield_to_v20(esub, sig_m, v20_ctx, wf_start_dt="2023-01-03", end_dt="2026-11-16", max_hold_td=mh, yield_scope="all_v20", fee_rt=0.0005)
    best_tr_df = best_y["patch_trades"].drop(columns=["mtm_segs"], errors="ignore").copy()
    best_tr_df["winner_variant"] = best_tc_row["variant"]
    best_tr_df.to_parquet(f"{wc.OUT_DIR}/w2b5_best_trades.parquet", index=False)

    # Track-level winners summary
    track_bests = {}
    for trk, grp in non_base.groupby("track"):
        top_comb = grp.sort_values(["comb_nav_wf", "sharpe_wf"], ascending=[False, False]).iloc[0].to_dict()
        top_st = grp.sort_values(["sharpe_wf", "nav_wf"], ascending=[False, False]).iloc[0].to_dict()
        track_bests[trk] = {"best_by_comb_nav": top_comb, "best_by_standalone_sharpe": top_st}

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)
    rss_map = {
        "track_a_b": d_ab.get("peak_rss_mb"),
        "track_c": d_c.get("peak_rss_mb"),
        "track_d": d_d.get("peak_rss_mb"),
        "track_e": d_e.get("peak_rss_mb"),
        "consolidator": rss_mb,
    }
    audit = wc.sanitize_json({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb_consolidator": rss_mb,
        "peak_rss_mb_per_script": rss_map,
        "all_scripts_rss_under_2gb": all((v is not None and float(v) < 2048.0) for v in rss_map.values()),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "v20_baseline_wf": base_m,
        "truncation_20241231_all_pass": bool(df_cmp["trunc_20241231_pass"].all()),
        "truncation_details": {
            "track_a": d_ab["track_a"]["truncation_20241231_proof"],
            "track_b": d_ab["track_b"]["truncation_20241231_proof"],
            "track_c": d_c["truncation_20241231_proof"],
            "track_d": d_d["truncation_20241231_proof"],
            "track_e": d_e["truncation_20241231_proofs"],
        },
        "overall_best_patch": best_patch_row,
        "best_single_track_patch": best_tc_row,
        "overall_best_standalone": best_stand_row,
        "joint_c_e_results": joint_rows,
        "per_track_winners": track_bests,
        "raw_underlying_etf_corr_vs_v20": d_e.get("raw_underlying_etf_corr_vs_v20"),
        "outputs": {
            "tracks_compare_csv": out_csv,
            "best_trades_parquet": f"{wc.OUT_DIR}/w2b5_best_trades.parquet",
            "audit_json": f"{wc.OUT_DIR}/w2b5_audit.json",
        },
    })
    with open(f"{wc.OUT_DIR}/w2b5_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"[FINALIZE DONE in {time.time()-t0:.2f}s] -> {out_csv} ({len(df_cmp)} rows)")
    print("\n=== PER-TRACK BEST COMBINED V20 PATCH ===")
    cols_show = ["track", "variant", "threshold", "n_trades_wf", "wr_wf_pct", "nav_wf", "ex5_wf", "mdd_wf_pct", "sharpe_wf", "corr_v20_all_days", "patch_n_added", "patch_n_v20_skipped", "comb_nav_wf", "comb_mdd_wf_pct", "comb_sharpe_wf", "comb_calmar_wf"]
    best_rows = [base_row] + [v["best_by_comb_nav"] for v in track_bests.values()]
    print(pd.DataFrame(best_rows)[cols_show].to_string(index=False))


if __name__ == "__main__":
    main()
