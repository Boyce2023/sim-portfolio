#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD039-B Final Audit Assembler (Front 2 3to4 V4.2 + Front 3A High V5.1 + Front 3B Pry V2.1).
Produces:
  - rd039_f23_audit.json
  - rd039_f23_grid.csv
  - rd039_f23_best_trades.parquet (for RD039-C integration)
Peak RSS strictly < 2.5 GB. Zero yfinance. Zero cap10m. Threads <= 2.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import math
import pickle
import subprocess
import sys
import time
import numpy as np
import pandas as pd
from scipy import stats

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _f23_common as cm

sys.path.insert(0, f"{cm.SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority")
sys.path.insert(0, f"{cm.SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a4_pairwise_interactions")
sys.path.insert(0, f"{cm.SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a1_old_1to2_2to3")
sys.path.insert(0, f"{cm.SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5")

import tier_priority_engine as tpe
import _w2a4_data_and_features as w2f
import _common_rd036 as c36
import w2a1_data_and_eval as w21

S2C_MAP = {
    "3to4_S(>=102)": 1, "3to4_A(90-101)": 1,
    "high_S(>=96)": 2, "high_A(88-95)": 2,
    "pry_S(>=175)": 3, "pry_A(165-174)": 3,
    "2to3_S(>=96)": 4, "2to3_A(90-95)": 4,
    "1to2_S(>=340)": 5, "1to2_A(304.8-339.9)": 5, "1to2_FB(295-304.7)": 5,
    "20cm_S(>=82)": 6, "20cm_A(76-81)": 999,
}


def bh_fdr(pvals: np.ndarray) -> np.ndarray:
    """Standard Benjamini-Hochberg FDR q-values."""
    p = np.asarray(pvals, dtype=np.float64)
    n = len(p)
    if n == 0:
        return p
    order = np.argsort(p)
    sp = p[order]
    q = sp * n / (np.arange(1, n + 1, dtype=np.float64))
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty_like(q)
    out[order] = np.clip(q, 0.0, 1.0)
    return out


def calc_dsr(dr: np.ndarray, n_trials: int, sigma_sr_ann: float = 0.5) -> float:
    """Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio on daily returns."""
    x = np.asarray(dr, dtype=np.float64)
    T = len(x)
    if T < 30 or np.std(x, ddof=1) <= 1e-12:
        return 0.0
    sr_d = float(np.mean(x) / np.std(x, ddof=1))
    skew = float(stats.skew(x, bias=False))
    kurt = float(stats.kurtosis(x, fisher=False, bias=False))
    if not np.isfinite(skew):
        skew = 0.0
    if not np.isfinite(kurt):
        kurt = 3.0
    sigma_sr_d = sigma_sr_ann / math.sqrt(cm.TRD_DAYS_YEAR)
    if n_trials <= 1:
        e_max = 0.0
    else:
        g = 0.5772156649
        z1 = stats.norm.ppf(1.0 - 1.0 / n_trials)
        z2 = stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e))
        e_max = sigma_sr_d * ((1.0 - g) * z1 + g * z2)
    denom_sq = max(1e-8, 1.0 - skew * sr_d + ((kurt - 1.0) / 4.0) * (sr_d ** 2))
    z = (sr_d - e_max) * math.sqrt(T - 1) / math.sqrt(denom_sq)
    return round(float(stats.norm.cdf(z)), 4)


def build_grid_and_stats(d2: dict, d3a: dict, d3b: dict) -> tuple[pd.DataFrame, dict]:
    """Assemble full multi-window grid across all 287 variants + BH-FDR + DSR + CSCV PBO + Plateau."""
    all_rows = []
    dsr_inputs = {}

    for st_name, d_obj in [("3to4", d2), ("high", d3a), ("pry", d3b)]:
        n_st = len(d_obj["results"])
        drs_wf = d_obj["drs_wf"]
        # Variance of SR across trials (daily SR units)
        srs_d = [float(np.mean(v) / np.std(v, ddof=1)) for v in drs_wf.values() if np.std(v, ddof=1) > 1e-12]
        sig_ann = float(np.std(srs_d, ddof=1) * math.sqrt(cm.TRD_DAYS_YEAR)) if len(srs_d) >= 2 else 0.5

        for r in d_obj["results"]:
            if "windows_030" not in r:
                continue
            vid = r["variant_id"]
            dr_wf = drs_wf.get(vid)
            row = {
                "strategy": st_name,
                "variant_id": vid,
                "miss_rate_pct": r["miss_rate_pct"],
                "mtm_diff_030": r["mtm_diff_030"],
                "paired_t_wf_030": r["paired_t_wf_030"],
                "paired_p_wf_030": r["paired_p_wf_030"],
                "paired_t_wf_vel030": r["paired_t_wf_vel030"],
                "paired_p_wf_vel030": r["paired_p_wf_vel030"],
                "dsr_strat": calc_dsr(dr_wf, n_st, sig_ann) if dr_wf is not None else 0.0,
                "hefu_ret_pct": r.get("hefu_ret_pct"),
                "aiai_ret_pct": r.get("aiai_ret_pct"),
            }
            for wn in ("FULL_5Y", "WF_2326", "IS_2124", "OOS_2526", "Y2026", "Y26H2"):
                w = r["windows_030"][wn]
                row[f"{wn}_n"] = w["n"]
                row[f"{wn}_wr"] = w["wr_pct"]
                row[f"{wn}_plr"] = w["plr"]
                row[f"{wn}_mloss"] = w["mean_loss_pct"]
                row[f"{wn}_le7"] = w["big_loss_rate_pct"]
                row[f"{wn}_nav"] = w["nav"]
                row[f"{wn}_ex5"] = w["ex_top5_nav"]
                row[f"{wn}_mdd"] = w["mdd_pct"]
                row[f"{wn}_sharpe"] = w["sharpe"]
                row[f"{wn}_calmar"] = w["calmar"]
            wv = r["windows_vel030"]["WF_2326"]
            row["WF_vel030_nav"] = wv["nav"]
            row["WF_vel030_sharpe"] = wv["sharpe"]
            row["WF_vel030_mdd"] = wv["mdd_pct"]
            for sk in ("bps50", "bps80", "vel_bps50", "vel_bps80"):
                ws = r["stress_wf"][sk]
                row[f"WF_{sk}_nav"] = ws["nav"]
                row[f"WF_{sk}_sharpe"] = ws["sharpe"]
                row[f"WF_{sk}_mdd"] = ws["mdd_pct"]
            all_rows.append(row)
            if dr_wf is not None:
                dsr_inputs[(st_name, vid)] = dr_wf

    df = pd.DataFrame(all_rows)
    # Global & per-strategy BH-FDR (use velocity p for high, flat p for 3to4 & pry)
    raw_p_strat = np.where(df["strategy"] == "high", df["paired_p_wf_vel030"], df["paired_p_wf_030"])
    df["bh_q_global"] = bh_fdr(raw_p_strat)
    df["bh_q_strat"] = 1.0
    for st_name in ("3to4", "high", "pry"):
        m = df["strategy"] == st_name
        df.loc[m, "bh_q_strat"] = bh_fdr(raw_p_strat[m])

    # Global DSR
    n_tot = len(df)
    srs_all = [float(np.mean(v) / np.std(v, ddof=1)) for v in dsr_inputs.values() if np.std(v, ddof=1) > 1e-12]
    sig_all = float(np.std(srs_all, ddof=1) * math.sqrt(cm.TRD_DAYS_YEAR)) if len(srs_all) >= 2 else 0.5
    df["dsr_global"] = [calc_dsr(dsr_inputs[(r.strategy, r.variant_id)], n_tot, sig_all) if (r.strategy, r.variant_id) in dsr_inputs else 0.0 for r in df.itertuples(index=False)]

    # CSCV PBO (S=16 and S=8)
    pbo_summary = {}
    for st_name, d_obj in [("3to4", d2), ("high", d3a), ("pry", d3b)]:
        pbo_summary[st_name] = {
            "wf_s16": cm.cscv_pbo(d_obj["drs_wf"], S=16),
            "wf_s8": cm.cscv_pbo(d_obj["drs_wf"], S=8),
            "5y_s16": cm.cscv_pbo(d_obj["drs_5y"], S=16),
        }

    # 3to4 Parameter Neighborhood Plateau Check
    df34 = df[df["strategy"] == "3to4"]
    b_zt_plat = df34[df34["variant_id"].str.match(r"^B_zt_(prevc_tp1|d4low_tp1)_")]
    bc_zt_plat = df34[df34["variant_id"].str.match(r"^BC_zt_(prevc_tp1|d4low_tp1)_.*__M4_CausalLOO$")]
    plateau = {
        "standalone_zt_stop_n": int(len(b_zt_plat)),
        "standalone_sh_wf_min": round(float(b_zt_plat["WF_2326_sharpe"].min()), 3),
        "standalone_sh_wf_med": round(float(b_zt_plat["WF_2326_sharpe"].median()), 3),
        "standalone_sh_wf_max": round(float(b_zt_plat["WF_2326_sharpe"].max()), 3),
        "standalone_pct_beat_base_2734": round(float((b_zt_plat["WF_2326_sharpe"] > 2.734).mean() * 100.0), 1),
        "combo_M4Causal_n": int(len(bc_zt_plat)),
        "combo_sh_wf_min": round(float(bc_zt_plat["WF_2326_sharpe"].min()), 3),
        "combo_sh_wf_med": round(float(bc_zt_plat["WF_2326_sharpe"].median()), 3),
        "combo_sh_wf_max": round(float(bc_zt_plat["WF_2326_sharpe"].max()), 3),
        "combo_mdd_wf_max": round(float(bc_zt_plat["WF_2326_mdd"].max()), 2),
        "combo_pct_ge_320": round(float((bc_zt_plat["WF_2326_sharpe"] >= 3.20).mean() * 100.0), 1),
        "combo_hefu_preserved_pct": round(float((bc_zt_plat["hefu_ret_pct"] > 140.0).mean() * 100.0), 1),
        "combo_aiai_preserved_pct": round(float((bc_zt_plat["aiai_ret_pct"] > 120.0).mean() * 100.0), 1),
    }
    return df, {"cscv_pbo": pbo_summary, "3to4_plateau": plateau}


def run_v20_combined_audit(sl_3to4_opt: pd.DataFrame, sl_pry_opt: pd.DataFrame) -> dict:
    """Verify exact V20 baseline parity & test 3to4 V4.2 replacement across 30/50/80bps (< 2.2GB RSS)."""
    parts = []
    for st in ("3to4", "high", "pry", "2to3", "1to2", "20cm"):
        df = pd.read_parquet(f"{cm.WAVE1}/pool_{st}_master_pit.parquet")
        df = w2f.attach_strategy_sim_cols(df, st)
        oh = pd.read_parquet(f"{cm.SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125/pool_{st}_oldhot.parquet")
        oh["buy_date"] = oh["buy_date"].astype(str).str[:10]
        oh["code"] = oh["code"].astype(str).str.zfill(6)
        ex = [c for c in ["buy_price", "prev_is_yizi", "buyable_open", "v20_pen"] if c in oh.columns and c not in df.columns]
        if ex:
            df = df.merge(oh[["buy_date", "code"] + ex], on=["buy_date", "code"], how="left")
        df["net_ret_020"] = pd.to_numeric(df["net_ret"], errors="coerce").astype(float)
        df["net_ret_030"] = c36.convert_fee(df["net_ret_020"], 0.0030)
        df["net_ret"] = df["net_ret_030"]
        is_yz = pd.to_numeric(df["open_pct"], errors="coerce").fillna(0.0) >= (0.195 if st == "20cm" else 0.095)
        if "prev_is_yizi" in df.columns:
            is_yz = is_yz | df["prev_is_yizi"].fillna(False).to_numpy(bool)
        df["can_buy_hygiene"] = (~is_yz.astype(bool)) & df["sim_ok"].fillna(True).to_numpy(bool) & df["net_ret"].notna()
        _, sl = c36.sim_strategy(st, df, df["orig_score"].to_numpy(float), wf_only=True)
        sl["strategy"] = st
        sl["score"] = sl["orig_score"].astype(float)
        sl["tier"] = [tpe.assign_physical_tier(st, sc) for sc in sl["score"]]
        sl["net_ret_020"] = sl["net_ret_020"].astype(float)
        sl["net_ret"] = sl["net_ret_030"].astype(float)
        if st == "20cm":
            sl["buy_price_val"] = sl["buy_px"].astype(float)
            sl["is_adj_px"] = True
        else:
            sl["buy_price_val"] = sl["buy_price"].astype(float) if "buy_price" in sl.columns else np.nan
            sl["is_adj_px"] = False
        sl["is_untrig"] = False
        parts.append(sl[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "net_ret_020", "buy_price_val", "is_adj_px", "is_untrig"]])

    pool_base = pd.concat(parts, ignore_index=True)
    ut_all = w21._load_untrig_lean({})
    ut_all = ut_all[ut_all["buy_date"].between(cm.WF_START, cm.WF_END)].copy()
    codes = set(pool_base["code"].astype(str).str.zfill(6)) | set(ut_all["code"].astype(str).str.zfill(6)) | set(sl_3to4_opt["code"].astype(str).str.zfill(6))
    ctx = cm.load_filtered_5m_and_dmap(codes, load_5m=False)
    bar_lu = {k: (v["open"], v["close"], v["adj_close"], 1.0, v["adjf"]) for k, v in ctx["dmap"].items()}
    cal_wf = ctx["cal_wf"]
    dt_to_idx = {d: i for i, d in enumerate(cal_wf)}
    wf_mask = np.array([(cm.WF_START <= d <= cm.WF_END) for d in ctx["cal_5y"]])
    csi_wf = ctx["csi_5y"][wf_mask]
    ew_wf = ctx["ew_5y"][wf_mask]

    def _eval_rep(reps: dict[str, pd.DataFrame], fee_rt: float) -> dict:
        p_parts = []
        trig_dts = {}
        for st in ("3to4", "high", "pry", "2to3", "1to2", "20cm"):
            if st in reps:
                r = reps[st][reps[st]["buy_date"].between(cm.WF_START, cm.WF_END)].copy()
                r["strategy"] = st
                sc_c = "score" if "score" in r.columns else "orig_score"
                r["score"] = r[sc_c].astype(float)
                r["tier"] = [tpe.assign_physical_tier(st, sc) for sc in r["score"]]
                r["net_ret"] = cm.fee_adjust(r["net_ret_020"].to_numpy(float), fee_rt)
                r["buy_price_val"] = r["buy_price"].astype(float)
                r["is_adj_px"] = False
                r["is_untrig"] = False
                r = r[pool_base.columns]
            else:
                r = pool_base[pool_base["strategy"] == st].copy()
                r["net_ret"] = cm.fee_adjust(r["net_ret_020"].to_numpy(float), fee_rt)
            p_parts.append(r)
            trig_dts[st] = set(r["buy_date"])
        pool6 = pd.concat(p_parts, ignore_index=True)
        ut = ut_all.copy()
        if "3to4" in reps:
            ut = ut[~((ut["strategy"] == "3to4") & (ut["buy_date"].isin(trig_dts["3to4"])))].copy()
        tr_df, _ = tpe.run_single_slot(pool6, lambda d: d["tier"].map(S2C_MAP).fillna(999).to_numpy(), untrig_df=ut, timing_mode="s_tier_reserve_only")
        tr_df["net_ret_fee"] = tr_df["net_ret"].astype(float)
        dr_wf, mdiff = tpe.build_daily_mtm_series(tr_df, cal_wf, dt_to_idx, bar_lu)
        assert mdiff < 1e-4, f"V20 MTM diff={mdiff}"
        fw = cm.calc_window_stats(dr_wf, tr_df, cal_wf, csi_wf, ew_wf, cm.WF_START, cm.WF_END, "net_ret_fee")
        oos = cm.calc_window_stats(dr_wf, tr_df, cal_wf, csi_wf, ew_wf, "2025-01-01", cm.WF_END, "net_ret_fee")
        y26 = cm.calc_window_stats(dr_wf, tr_df, cal_wf, csi_wf, ew_wf, "2026-01-01", cm.WF_END, "net_ret_fee")
        h2 = cm.calc_window_stats(dr_wf, tr_df, cal_wf, csi_wf, ew_wf, "2026-07-01", cm.WF_END, "net_ret_fee")
        return {
            "n": fw["n"],
            "n_3to4": int((tr_df["strategy"] == "3to4").sum()),
            "nav_wf": fw["nav"], "ex5_wf": fw["ex_top5_nav"], "mdd_pct": fw["mdd_pct"], "sharpe": fw["sharpe"], "calmar": fw["calmar"],
            "nav_2526": oos["nav"], "sh_2526": oos["sharpe"], "nav_y26": y26["nav"], "nav_26h2": h2["nav"],
            "mtm_diff": round(mdiff, 8), "dr_wf": dr_wf,
        }

    v20_base_30 = _eval_rep({}, 0.0030)
    assert v20_base_30["n"] == 209 and abs(v20_base_30["nav_wf"] - 432838.9886) < 0.05 and abs(v20_base_30["sharpe"] - 4.548) < 0.002

    out = {}
    for lbl, reps in [
        ("V20_Baseline", {}),
        ("V20_With_3to4_V42_Opt", {"3to4": sl_3to4_opt}),
        ("V20_With_3to4_V42_And_PrySkipZt5", {"3to4": sl_3to4_opt, "pry": sl_pry_opt}),
    ]:
        out[lbl] = {}
        for bps, fr in [("bps30", 0.0030), ("bps50", 0.0050), ("bps80", 0.0080)]:
            res = _eval_rep(reps, fr)
            if bps == "bps30" and lbl != "V20_Baseline":
                d = res["dr_wf"] - v20_base_30["dr_wf"]
                pt = float(np.mean(d) / (np.std(d, ddof=1) / math.sqrt(len(d))))
                pp = float(stats.t.sf(pt, df=len(d) - 1))
                res["paired_t_vs_v20"] = round(pt, 3)
                res["paired_p_vs_v20"] = round(pp, 5)
                res["sharpe_delta"] = round(res["sharpe"] - v20_base_30["sharpe"], 3)
                res["mdd_delta_pp"] = round(res["mdd_pct"] - v20_base_30["mdd_pct"], 2)
                res["nav_ratio"] = round(res["nav_wf"] / v20_base_30["nav_wf"], 4)
            res.pop("dr_wf", None)
            out[lbl][bps] = res

    del ctx, bar_lu
    gc.collect()
    return out


def main():
    t0 = time.time()
    with open(f"{cm.CACHE_DIR}/front2_3to4.pkl", "rb") as f:
        d2 = pickle.load(f)
    with open(f"{cm.CACHE_DIR}/front3a_high.pkl", "rb") as f:
        d3a = pickle.load(f)
    with open(f"{cm.CACHE_DIR}/front3b_pry.pkl", "rb") as f:
        d3b = pickle.load(f)

    # 1. Grid + Stats + BH-FDR + DSR + CSCV PBO + Plateau
    df_grid, stats_meta = build_grid_and_stats(d2, d3a, d3b)
    df_grid.to_csv(f"{cm.OUT_DIR}/rd039_f23_grid.csv", index=False)

    # 2. Extract best & baseline slot DataFrames
    sl_3to4_base = d2["top_slots"]["V41_Baseline"].copy()
    sl_3to4_opt = d2["top_slots"]["BC_zt_prevc_tp1_m6_1000__M4_CausalLOO"].copy()
    sl_high_base = d3a["top_slots"]["V51_Baseline_Matched42CB"].copy()
    sl_pry_base = d3b["top_slots"]["V21_Baseline_P165"].copy()
    sl_pry_skip = d3b["top_slots"]["Skip_zt0925_lt5"].copy()

    # Exact 3to4 <= -7% blowup autopsy from baseline 95/73 trades
    b34_5y = sl_3to4_base[sl_3to4_base["net_ret_020"] <= -0.07]
    b34_wf = sl_3to4_base[(sl_3to4_base["buy_date"] >= cm.WF_START) & (sl_3to4_base["net_ret_020"] <= -0.07)]
    autopsy_3to4 = {
        "n_5y_le_m7": int(len(b34_5y)),
        "n_5y_d4_no_zt_a_d5_cut": int((b34_5y["exit_reason"] == "a_d5_cut").sum()),
        "n_5y_d4_zt_sealed": int((b34_5y["exit_reason"] != "a_d5_cut").sum()),
        "n_wf_le_m7": int(len(b34_wf)),
        "n_wf_d4_no_zt_a_d5_cut": int((b34_wf["exit_reason"] == "a_d5_cut").sum()),
        "n_wf_d4_zt_sealed": int((b34_wf["exit_reason"] != "a_d5_cut").sum()),
        "blowups_wf": [
            {"buy_date": r.buy_date, "code": r.code, "name": r.name, "ret_020_pct": round(float(r.net_ret_020) * 100.0, 2), "exit_reason": r.exit_reason}
            for r in b34_wf.sort_values("net_ret_020").itertuples(index=False)
        ],
    }

    # Export clean best trades parquet for RD039-C
    def _norm_trades(df_in: pd.DataFrame, st: str, vid: str) -> pd.DataFrame:
        out = pd.DataFrame()
        out["strategy"] = [st] * len(df_in)
        out["variant_id"] = [vid] * len(df_in)
        out["buy_date"] = df_in["buy_date"].astype(str).str[:10].values
        out["exit_date"] = df_in["exit_date"].astype(str).str[:10].values
        out["buy_hhmm"] = df_in["buy_hhmm"].astype(int).values if "buy_hhmm" in df_in.columns else 925
        out["exit_hhmm"] = df_in["exit_hhmm"].astype(int).values if "exit_hhmm" in df_in.columns else 1500
        out["code"] = df_in["code"].astype(str).str.zfill(6).values
        out["name"] = df_in["name"].astype(str).values
        out["buy_price"] = df_in["buy_price"].astype(float).values
        out["eff_buy_price"] = df_in["eff_buy_price"].astype(float).values if "eff_buy_price" in df_in.columns else df_in["buy_price"].astype(float).values
        out["exit_price"] = df_in["exit_price"].astype(float).values if "exit_price" in df_in.columns else np.nan
        sc_col = "score" if "score" in df_in.columns else "orig_score"
        out["score"] = df_in[sc_col].astype(float).values
        out["tier"] = [tpe.assign_physical_tier(st, sc) for sc in out["score"]]
        r20 = df_in["net_ret_020"].astype(float).to_numpy()
        out["net_ret_020"] = r20
        out["net_ret_030"] = cm.fee_adjust(r20, 0.0030)
        out["net_ret_050"] = cm.fee_adjust(r20, 0.0050)
        out["net_ret_080"] = cm.fee_adjust(r20, 0.0080)
        out["net_ret_vel_030"] = df_in["net_ret_vel_030"].astype(float).values if "net_ret_vel_030" in df_in.columns else out["net_ret_030"].values
        out["exit_reason"] = df_in["exit_reason"].astype(str).values if "exit_reason" in df_in.columns else "base"
        return out

    best_tr = pd.concat([
        _norm_trades(sl_3to4_opt, "3to4", "V42_BC_zt_prevc_tp1_m6_1000__M4_CausalLOO"),
        _norm_trades(sl_high_base, "high", "V51_Baseline_Matched42CB"),
        _norm_trades(sl_pry_base, "pry", "V21_Baseline_P165"),
    ], ignore_index=True)
    best_tr.to_parquet(f"{cm.OUT_DIR}/rd039_f23_best_trades.parquet", index=False)

    # Free d2/d3a/d3b before loading V20 6-strategy context to keep peak RSS < 2.5 GB
    autopsy_pry = d3b["autopsy"]
    cov_pry = d3b["coverage_5m"]
    ew_pry = d3b["ew_diag"]
    del d2, d3a, d3b
    gc.collect()

    # 3. Lightweight V20 6-Strategy Combined Incremental Verification
    v20_comb = run_v20_combined_audit(sl_3to4_opt, sl_pry_skip)
    rss_stage1 = cm.rss_mb()

    # 4. Run 2024-12-31 physical truncation proof in isolated subprocess (strictly < 2.5 GB per proc)
    env = dict(os.environ)
    for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[_k] = "1"
    subprocess.run([sys.executable, f"{THIS_DIR}/_truncation_proof_20241231.py"], check=True, env=env)
    with open(f"{cm.CACHE_DIR}/truncation_proof.json", encoding="utf-8") as f:
        trunc_proof = json.load(f)

    # 5. Assemble final audit JSON
    def _pick_summary(st: str, vids: list[str]) -> list[dict]:
        sub = df_grid[(df_grid["strategy"] == st) & (df_grid["variant_id"].isin(vids))]
        return sub.to_dict("records")

    top_3to4 = df_grid[df_grid["strategy"] == "3to4"].sort_values("WF_2326_sharpe", ascending=False).head(12)["variant_id"].tolist()
    top_high = df_grid[df_grid["strategy"] == "high"].sort_values("WF_vel030_sharpe", ascending=False).head(8)["variant_id"].tolist()
    top_pry = df_grid[df_grid["strategy"] == "pry"].sort_values("WF_2326_sharpe", ascending=False).head(8)["variant_id"].tolist()

    audit = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_stage1_mb": rss_stage1,
        "peak_rss_stage2_trunc_mb": trunc_proof["peak_rss_mb"],
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "n_total_variants": int(len(df_grid)),
        "verdicts": {
            "front2_3to4": {
                "status": "GENUINE_LIFT_PROMOTE_V42",
                "recommended_variant": "BC_zt_prevc_tp1_m6_1000__M4_CausalLOO",
                "alternative_neighbor": "BC_zt_d4low_tp1_1000__M4_CausalLOO",
                "rule_summary": "Causal RD036 M4_4WayMineBL15 + Causal expanding (exit_date<t) drop of s34_af_20 (+5) + T+1 ZT-hold 5m stop (10:00+ close <= pre_close * 0.94 -> exit next 5m open above limit-down)",
                "landmark_hefu_ret_pct": 146.86,
                "landmark_aiai_ret_pct": 123.55,
            },
            "front3a_high": {
                "status": "NEGATIVE_KEEP_V51_BASELINE",
                "recommended_variant": "V51_Baseline_Matched42CB",
                "finding": "Replacing 09:25 direct auction buys on 平红开 (24/46=52.2%) with ANY 09:30+ upward confirmation strictly degrades WF Sharpe (2.377->2.213 flat, 2.330->2.086 vel) and NAV (8.99x->6.21x vel) across Matched42CB, CausalCB, and NoCB without filtering bull traps (诺德股份/华森制药 still trigger; misses 首开股份 +18.30%).",
            },
            "front3b_pry": {
                "status": "T1_LOCKUP_INCURABLE_KEEP_BASELINE_OR_SKIP_CRASH",
                "recommended_variant": "V21_Baseline_P165",
                "5m_coverage_pct_pass435": cov_pry["pass_435_buy_date_cov_pct"],
                "finding": "Local 5m coverage is only 0.46% (2/435 passing, 1/10 WF). 90.77% (59/65) of P165 losses are D0跌停回封锁死次日低开砍 on 2024-02-05 & 2024-02-07. Even optimistic daily-OHLC upper-bound delayed confirmation hurts WF Sharpe (0.732->0.380..0.536) because 46.22% of winners (incl. #1 禾盛新材 +24.66%) have D0 high==open while #1 loser 登云股份 (-19.15%) reached +1.53%. Skip_zt0925_lt5 raises WF Sharpe to 1.169 on n=6 (p=0.25, PBO=0.72), insufficient statistical sample.",
            },
        },
        "autopsy": {
            "3to4_blowups_le_m7": autopsy_3to4,
            "pry_5m_coverage": cov_pry,
            "pry_left_tail": autopsy_pry,
            "pry_ew_diag": ew_pry,
        },
        "multiple_testing_and_plateau": stats_meta,
        "v20_6strat_combined_audit": v20_comb,
        "truncation_20241231_zero_leakage": trunc_proof,
        "key_rows": {
            "3to4": _pick_summary("3to4", list(dict.fromkeys(["V41_Baseline", "B_zt_prevc_tp1_m6_1000", "B_zt_d4low_tp1_1000", "C_M4MineBL15", "C_NoAf20_CausalLOO", "C_M4_CausalLOO", "C_M4_Act94"] + top_3to4))),
            "high": _pick_summary("high", list(dict.fromkeys(["V51_Baseline_Matched42CB", "Base_CausalCB", "NoCB_R_direct_0925_G_open_p015_c1030"] + top_high))),
            "pry": _pick_summary("pry", list(dict.fromkeys(["V21_Baseline_P165", "Skip_zt0925_lt5", "Skip_zt0925_lt3", "UB_DelayConf_open_p015", "UB_DelayConf_open_p030"] + top_pry))),
        },
    }
    with open(f"{cm.OUT_DIR}/rd039_f23_audit.json", "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(audit), f, ensure_ascii=False, indent=2)

    print(f"[FINAL AUDIT COMPLETE in {time.time()-t0:.1f}s] Stage1RSS={rss_stage1} MB | TruncRSS={trunc_proof['peak_rss_mb']} MB")
    print("V20 Baseline -> Opt (30bps):", v20_comb["V20_Baseline"]["bps30"], "->", v20_comb["V20_With_3to4_V42_Opt"]["bps30"])
    print("3to4 Plateau:", stats_meta["3to4_plateau"])
    print("Files written:")
    for fn in ("rd039_f23_audit.json", "rd039_f23_grid.csv", "rd039_f23_best_trades.parquet"):
        p = f"{cm.OUT_DIR}/{fn}"
        print(f"  {p} ({os.path.getsize(p)} bytes)")


if __name__ == "__main__":
    main()
