#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-5 Shared Helper, Clean ETF Cache Builder, Exact MTM & V20 Correlation Evaluator.
Zero yfinance (D12). Zero cap10m. Single-thread, low-RAM (< 2 GB). Read-only on wave1_base/.
"""
import json
import math
import os
import sys
from typing import Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1_DIR = f"{RD035_DIR}/wave1_base"
OUT_DIR = f"{RD035_DIR}/wave2b/w2b5_event_crossmarket_lowcorr_scorecard"
CACHE_DIR = f"{OUT_DIR}/cache"
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

if WAVE1_DIR not in sys.path:
    sys.path.insert(0, WAVE1_DIR)

import wf_scorecard_engine as wfe
import _wf_sim_and_metrics as wfm
import _wf_v20_patch as wfp

TRD_DAYS_YEAR = 242.0


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def build_or_load_clean_etf_cache(force_refresh: bool = False) -> pd.DataFrame:
    """
    Build clean split-adjusted daily OHLCV cache for broad/dividend/gold/bank ETFs up to 2026-11-24/25.
    Core4 (510050, 510300, 510500, 512100) come directly from RD029 true HFQ cache.
    518880 (Gold), 510880 (Dividend), 512890 (Div Low-Vol), 512800 (Bank), 511010 (Treasury),
    159915 (ChiNext), 588000 (STAR50) come from local caches + Sina ETF hist (NO yfinance!).
    """
    cache_pq = f"{CACHE_DIR}/w2b5_etf_clean_2020_20261125.parquet"
    if os.path.exists(cache_pq) and not force_refresh:
        return pd.read_parquet(cache_pq)

    import akshare as ak
    os.environ["NO_PROXY"] = "*"

    rows = []
    c4 = pd.read_parquet(f"{ROOT}/output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/cache/core4_etfs_to_20261125.parquet")
    c4 = c4[c4["date"] >= "2019-01-01"].copy()
    name_map = {"510050": "上证50ETF", "510300": "沪深300ETF", "510500": "中证500ETF", "512100": "中证1000ETF"}
    for code, g in c4.groupby("code"):
        g = g.sort_values("date").reset_index(drop=True)
        for r in g.itertuples(index=False):
            rows.append({
                "date": str(r.date)[:10],
                "code": str(code).zfill(6),
                "name": name_map[str(code)],
                "group": "broad",
                "open": float(r.open_hfq),
                "high": float(r.high_hfq),
                "low": float(r.low_hfq),
                "close": float(r.close_hfq),
                "volume": float(r.volume),
                "amount": float(r.amount),
            })

    extra_specs = [
        ("sh518880", "518880", "黄金ETF", "gold", []),
        ("sh510880", "510880", "红利ETF", "dividend", []),
        ("sh512890", "512890", "红利低波ETF", "dividend", [("2021-10-25", 0.5)]),
        ("sh512800", "512800", "银行ETF", "dividend", [("2025-07-07", 0.5)]),
        ("sh511010", "511010", "国债ETF", "bond", []),
        ("sz159915", "159915", "创业板ETF", "broad", []),
        ("sh588000", "588000", "科创50ETF", "broad", []),
    ]
    for sym, code, nm, grp, splits in extra_specs:
        df = ak.fund_etf_hist_sina(symbol=sym)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df[df["date"] >= "2019-01-01"].sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
        mult = np.ones(len(df), dtype=float)
        for sp_dt, sp_ratio in splits:
            mult = np.where(df["date"].values >= sp_dt, mult * (1.0 / sp_ratio), mult)
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float) * mult
        r1 = df["close"].pct_change().dropna()
        max_abs = float(r1.abs().max()) if len(r1) else 0.0
        assert max_abs <= 0.22, f"{sym} unadjusted split detected: max_abs_ret={max_abs}"
        for r in df.itertuples(index=False):
            rows.append({
                "date": r.date,
                "code": code,
                "name": nm,
                "group": grp,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
                "amount": float(r.amount),
            })

    out = pd.DataFrame(rows).sort_values(["code", "date"]).reset_index(drop=True)
    out.to_parquet(cache_pq, index=False, compression="snappy")
    return out


def build_mtm_segs_for_df(
    trades_df: pd.DataFrame,
    cal_dts: list[str],
    px_lookup: dict[tuple[str, str], tuple[float, float]],
    fee_rt: float = 0.0030,
    end_cap_dt: Optional[str] = None,
) -> pd.DataFrame:
    """
    Attach exact `mtm_segs` column (list of (t_i, daily_mult) relative to `cal_dts`)
    using true daily close/open from `px_lookup[(code, date)] = (open_adj, close_adj)`.
    """
    out = trades_df.copy()
    if out.empty:
        out["mtm_segs"] = pd.Series(dtype=object)
        return out

    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    T = len(cal_dts)
    fee_b = fee_rt / 2.0
    fee_s = fee_rt / 2.0
    segs_list = []

    for r in out.itertuples(index=False):
        bd = str(r.buy_date)
        ed = str(r.exit_date)
        code = str(r.code).zfill(6)
        net_r = float(r.net_ret)
        bi = dt_idx.get(bd)
        if bi is None:
            segs_list.append([])
            continue
        ed_use = min(ed, end_cap_dt) if end_cap_dt else ed
        ei = dt_idx.get(ed_use)
        if ei is None:
            # Find last date <= ed_use in cal_dts
            pos = int(np.searchsorted(cal_dts, ed_use, side="right")) - 1
            ei = max(bi, min(T - 1, pos))

        if ei <= bi:
            segs_list.append([(bi, 1.0 + net_r)])
            continue

        bpx = getattr(r, "buy_px", np.nan)
        epx = getattr(r, "exit_px", np.nan)
        exact_possible = (end_cap_dt is None or ed <= end_cap_dt) and np.isfinite(bpx) and np.isfinite(epx) and bpx > 0 and epx > 0
        closes = []
        if exact_possible:
            for k in range(bi, ei):
                px = px_lookup.get((code, cal_dts[k]))
                if px is None or not (np.isfinite(px[1]) and px[1] > 0):
                    exact_possible = False
                    break
                closes.append(float(px[1]))

        if exact_possible and len(closes) == (ei - bi):
            segs = [(bi, (closes[0] / float(bpx)) * (1.0 - fee_b))]
            for j in range(1, len(closes)):
                segs.append((bi + j, closes[j] / closes[j - 1]))
            segs.append((ei, (float(epx) / closes[-1]) * (1.0 - fee_s)))
            prod_m = 1.0
            for _, mv in segs:
                prod_m *= mv
            target_m = 1.0 + net_r
            if prod_m > 0 and abs(prod_m - target_m) > 1e-12:
                segs[-1] = (ei, segs[-1][1] * (target_m / prod_m))
        else:
            span = ei - bi + 1
            g = (1.0 + net_r) ** (1.0 / span)
            segs = [(k, g) for k in range(bi, ei + 1)]
        segs_list.append(segs)

    out["mtm_segs"] = segs_list
    return out


def compute_corr_diagnostics(
    dr_track: np.ndarray,
    cal_dts: list[str],
    v20_ctx: dict,
    wf_start_dt: str,
    end_dt: str = "2026-11-16",
    dr_emp_standalone: Optional[np.ndarray] = None,
    dr_comb: Optional[np.ndarray] = None,
) -> dict:
    """Compute honest daily return correlation between Track and V20.0 across WF window."""
    cal5 = v20_ctx["calendar_5y"]
    sub_cal = cal5[cal5["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    dt_to_pos = {d: i for i, d in enumerate(cal_dts)}
    valid_mask = sub_cal["trade_date"].isin(dt_to_pos).to_numpy(bool)
    sub_cal = sub_cal[valid_mask].reset_index(drop=True)
    idx_pos = [dt_to_pos[d] for d in sub_cal["trade_date"]]
    v20_dr = sub_cal["v20_daily_ret"].to_numpy(float)
    v20_occ = sub_cal["v20_occupied"].to_numpy(bool)
    trk_dr = dr_track[idx_pos]

    def _safe_corr(a, b):
        if len(a) < 5 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
            return 0.0
        return round(float(np.corrcoef(a, b)[0, 1]), 4)

    trk_act = np.abs(trk_dr) > 1e-12
    either_act = trk_act | v20_occ
    both_act = trk_act & v20_occ

    out = {
        "n_days": int(len(v20_dr)),
        "corr_standalone_vs_v20_all_days": _safe_corr(trk_dr, v20_dr),
        "corr_standalone_vs_v20_either_active": _safe_corr(trk_dr[either_act], v20_dr[either_act]),
        "corr_standalone_vs_v20_both_active": _safe_corr(trk_dr[both_act], v20_dr[both_act]),
        "n_both_active_days": int(both_act.sum()),
        "n_track_active_days": int(trk_act.sum()),
    }
    if dr_emp_standalone is not None:
        emp_dr = dr_emp_standalone[idx_pos]
        out["corr_empty_patch_standalone_vs_v20_all_days"] = _safe_corr(emp_dr, v20_dr)
    if dr_comb is not None:
        comb_dr = dr_comb[idx_pos]
        out["corr_combined_vs_v20_all_days"] = _safe_corr(comb_dr, v20_dr)
    return out


def evaluate_scorecard_with_exact_mtm(
    cand_df: pd.DataFrame,
    feature_cols: list[str],
    px_lookup: dict[tuple[str, str], tuple[float, float]],
    v20_ctx: dict,
    fee_rt: float = 0.0030,
    gross_ret_col: Optional[str] = None,
    wf_start_date: str = "2023-01-03",
    end_date: str = "2026-11-16",
    min_warmup_trades: int = 80,
    min_warmup_trades_rare: int = 50,
    min_warmup_months: int = 18,
    recalc_freq: str = "daily",
    top_k: int = 10,
    min_k: int = 4,
    max_corr: float = 0.65,
    thresholds: tuple = ("all_cands", "top30", "top20", "top10", 70, 75),
    perm_n: int = 1000,
    seed: int = 20261125,
) -> dict:
    """
    Run `wf_scorecard_engine.run_wf_scorecard_new_strategy`, then upgrade all passing/slot
    ledgers with exact bar-level `mtm_segs` aligned to `actual_wf_start..end_date`,
    re-evaluate `evaluate_wf_ledger`, `simulate_v20_empty_slot_patch`, and V20 daily correlations.
    """
    res = wfe.run_wf_scorecard_new_strategy(
        cand_df, feature_cols, v20_ctx=v20_ctx,
        wf_start_date=wf_start_date, end_date=end_date,
        min_warmup_trades=min_warmup_trades, min_warmup_trades_rare=min_warmup_trades_rare,
        min_warmup_months=min_warmup_months, recalc_freq=recalc_freq,
        top_k=top_k, min_k=min_k, max_corr=max_corr, fee_rt=fee_rt,
        gross_ret_col=gross_ret_col, mtm_col=None,
        thresholds=thresholds, eval_v20_patch=False, perm_n=10, seed=seed,
    )
    actual_wf_start = res["meta"]["wf_actual_start"] or wf_start_date
    scored_df = res["scored_df"]
    wf_cands = scored_df[scored_df["wf_in_window"]].copy()
    bench_df = v20_ctx["bench"]
    b_win = bench_df[bench_df["trade_date"].between(actual_wf_start, end_date)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = b_win["trade_date"].tolist()

    enhanced = {}
    summary_rows = []
    for tname, tres in res["threshold_results"].items():
        pass_df = build_mtm_segs_for_df(tres["pass_df"], cal_dts, px_lookup, fee_rt=fee_rt, end_cap_dt=end_date)
        slot_df = build_mtm_segs_for_df(tres["slot_df"], cal_dts, px_lookup, fee_rt=fee_rt, end_cap_dt=end_date)

        ev = wfm.evaluate_wf_ledger(
            slot_df, pass_df, wf_cands, bench_df,
            wf_start_dt=actual_wf_start, end_dt=end_date,
            mtm_col="mtm_segs", perm_n=perm_n, seed=seed,
        )
        dr_standalone, _ = wfm.build_daily_mtm_returns(slot_df, cal_dts, mtm_col="mtm_segs")

        patch_res = None
        dr_emp_standalone = None
        if not pass_df.empty and tname != "all_cands":
            patch_res = wfp.simulate_v20_empty_slot_patch(
                pass_df, v20_ctx=v20_ctx, wf_start_dt=actual_wf_start, end_dt=min(end_date, "2026-11-16"),
                score_col="wf_score", patch_mtm_col="mtm_segs",
            )
            # Recompute empty-slot standalone dr for correlation check
            cal5 = v20_ctx["calendar_5y"]
            emp_set = set(cal5.loc[cal5["v20_empty_strict_no_stier_wait"] & cal5["trade_date"].between(actual_wf_start, min(end_date, "2026-11-16")), "trade_date"])
            p_top1 = pass_df.sort_values(["buy_date", "wf_score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
            p_emp = p_top1[p_top1["buy_date"].isin(emp_set)].copy()
            _, patch_emp_slot = wfm.select_single_slot_trades(p_emp.assign(can_buy_hygiene=True), score_col="wf_score", threshold=None, wf_only=False)
            dr_emp_standalone, _ = wfm.build_daily_mtm_returns(patch_emp_slot, cal_dts, mtm_col="mtm_segs")

        corr_diag = compute_corr_diagnostics(
            dr_standalone, cal_dts, v20_ctx, wf_start_dt=actual_wf_start,
            end_dt=min(end_date, "2026-11-16"), dr_emp_standalone=dr_emp_standalone,
        )

        enhanced[tname] = {
            "threshold_name": tname,
            "n_passing_cands": int(len(pass_df)),
            "metrics": ev,
            "v20_empty_patch": patch_res,
            "corr_diag": corr_diag,
            "slot_df": slot_df,
            "pass_df": pass_df,
        }
        fw = ev["windows"].get("FULL_WF", {})
        y2526 = ev["windows"].get("Y2025_2026", {})
        y26 = ev["windows"].get("Y2026", {})
        p_sd = ev["permutation_1000"]["same_day_p_nav"]
        p_any = ev["permutation_1000"]["any_cand_day_p_nav"]
        summary_rows.append({
            "threshold": tname,
            "n_pass": int(len(pass_df)),
            "n_trades": fw.get("n", 0),
            "wr_pct": fw.get("wr_pct", 0.0),
            "plr": fw.get("plr", 0.0),
            "mean_pct": fw.get("mean_pct", 0.0),
            "nav_wf": fw.get("nav", 1.0),
            "ex3_wf": fw.get("ex_top3_nav", 1.0),
            "ex5_wf": fw.get("ex_top5_nav", 1.0),
            "mdd_pct": fw.get("daily_mdd_pct", 0.0),
            "sharpe": fw.get("daily_sharpe", 0.0),
            "calmar": fw.get("daily_calmar", 0.0),
            "excess_csi_pp": fw.get("excess_csi300_pp", 0.0),
            "nav_2526": y2526.get("nav", 1.0),
            "ex5_2526": y2526.get("ex_top5_nav", 1.0),
            "nav_y26": y26.get("nav", 1.0),
            "perm_sd_p": p_sd,
            "perm_any_p": p_any,
            "corr_v20": corr_diag["corr_standalone_vs_v20_all_days"],
        })

    return {
        "mode": res["mode"],
        "elapsed_sec": res["elapsed_sec"],
        "meta": res["meta"],
        "scored_df": scored_df,
        "threshold_results": enhanced,
        "summary_table": pd.DataFrame(summary_rows),
    }


def extract_track_row(
    track_id: str,
    variant_id: str,
    desc: str,
    thr_name: str,
    fee_rt: float,
    wf_actual_start: str,
    ev_metrics: dict,
    patch_res: Optional[dict],
    corr_diag: dict,
    trunc_pass: bool,
    extra: Optional[dict] = None,
) -> dict:
    """Standardize metrics row for w2b5_tracks_compare.csv."""
    fw = ev_metrics["windows"].get("FULL_WF", {})
    y2526 = ev_metrics["windows"].get("Y2025_2026", {})
    y26 = ev_metrics["windows"].get("Y2026", {})
    perm = ev_metrics.get("permutation_1000", {})

    m1 = patch_res.get("mode1_strict_combined_no_peek", {}) if patch_res else {}
    m2 = patch_res.get("mode2_empty_slot_standalone", {}) if patch_res else {}
    b_fw = m1.get("v20_baseline", {}).get("FULL_WF", {})
    c_fw = m1.get("combined_with_patch", {}).get("FULL_WF", {})
    c_2526 = m1.get("combined_with_patch", {}).get("Y2025_2026", {})
    b_2526 = m1.get("v20_baseline", {}).get("Y2025_2026", {})
    e_fw = m2.get("windows", {}).get("FULL_WF", {})
    e_2526 = m2.get("windows", {}).get("Y2025_2026", {})

    row = {
        "track": track_id,
        "variant": variant_id,
        "desc": desc,
        "threshold": thr_name,
        "fee_rt_pct": round(fee_rt * 100.0, 3),
        "wf_actual_start": wf_actual_start,
        "n_trades_wf": fw.get("n", 0),
        "wr_wf_pct": fw.get("wr_pct", 0.0),
        "plr_wf": fw.get("plr", 0.0),
        "mean_wf_pct": fw.get("mean_pct", 0.0),
        "nav_wf": fw.get("nav", 1.0),
        "ex3_wf": fw.get("ex_top3_nav", 1.0),
        "ex5_wf": fw.get("ex_top5_nav", 1.0),
        "mdd_wf_pct": fw.get("daily_mdd_pct", 0.0),
        "sharpe_wf": fw.get("daily_sharpe", 0.0),
        "calmar_wf": fw.get("daily_calmar", 0.0),
        "excess_csi300_wf_pp": fw.get("excess_csi300_pp", 0.0),
        "nav_2526": y2526.get("nav", 1.0),
        "ex5_2526": y2526.get("ex_top5_nav", 1.0),
        "mdd_2526_pct": y2526.get("daily_mdd_pct", 0.0),
        "sharpe_2526": y2526.get("daily_sharpe", 0.0),
        "excess_csi300_2526_pp": y2526.get("excess_csi300_pp", 0.0),
        "nav_2026": y26.get("nav", 1.0),
        "ex5_2026": y26.get("ex_top5_nav", 1.0),
        "mdd_2026_pct": y26.get("daily_mdd_pct", 0.0),
        "sharpe_2026": y26.get("daily_sharpe", 0.0),
        "perm_sd_p": perm.get("same_day_p_nav", 1.0),
        "perm_any_p": perm.get("any_cand_day_p_nav", 1.0),
        "corr_v20_all_days": corr_diag.get("corr_standalone_vs_v20_all_days"),
        "corr_v20_both_active": corr_diag.get("corr_standalone_vs_v20_both_active"),
        "corr_v20_empty_patch": corr_diag.get("corr_empty_patch_standalone_vs_v20_all_days"),
        "emp_trades_wf": e_fw.get("n", 0),
        "emp_wr_pct": e_fw.get("wr_pct", 0.0),
        "emp_nav_wf": e_fw.get("nav", 1.0),
        "emp_ex5_wf": e_fw.get("ex_top5_nav", 1.0),
        "emp_mdd_wf_pct": e_fw.get("daily_mdd_pct", 0.0),
        "emp_sharpe_wf": e_fw.get("daily_sharpe", 0.0),
        "emp_calmar_wf": e_fw.get("daily_calmar", 0.0),
        "emp_nav_2526": e_2526.get("nav", 1.0),
        "patch_n_added": m1.get("n_patch_added", 0),
        "patch_n_v20_skipped": m1.get("n_v20_skipped_by_collision", 0),
        "v20_base_nav_wf": b_fw.get("nav", 1.0),
        "v20_base_mdd_wf_pct": b_fw.get("daily_mdd_pct", 0.0),
        "v20_base_sharpe_wf": b_fw.get("daily_sharpe", 0.0),
        "v20_base_calmar_wf": b_fw.get("daily_calmar", 0.0),
        "comb_nav_wf": c_fw.get("nav", 1.0),
        "comb_mdd_wf_pct": c_fw.get("daily_mdd_pct", 0.0),
        "comb_sharpe_wf": c_fw.get("daily_sharpe", 0.0),
        "comb_calmar_wf": c_fw.get("daily_calmar", 0.0),
        "comb_delta_nav_ratio": m1.get("delta_nav_ratio_full_wf", 1.0),
        "comb_delta_mdd_pp": m1.get("delta_mdd_pp_full_wf", 0.0),
        "comb_delta_sharpe": m1.get("delta_sharpe_full_wf", 0.0),
        "comb_delta_calmar": round(c_fw.get("daily_calmar", 0.0) - b_fw.get("daily_calmar", 0.0), 3) if c_fw else 0.0,
        "comb_nav_2526": c_2526.get("nav", 1.0),
        "v20_base_nav_2526": b_2526.get("nav", 1.0),
        "trunc_20241231_pass": bool(trunc_pass),
    }
    if extra:
        row.update(extra)
    return row
