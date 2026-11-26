#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD030 Wave 2A: 6 V20.0 Strategies (+ temp5b) x 3 Pool Layers x 6-Dim Old-Hot
Nonlinear (4-5 tier + Quadratic + Permutation + BH-FDR), Horse-Race Decomposition,
and Era/Year Time-Effect Audit.

Hard rules:
  - ZERO yfinance (D12); assert "yfinance" not in sys.modules.
  - Strictly read-only on all production files, strategy_astock.md, and Wave 1 parquets.
  - Pure compounding & equal-weight evaluation + CSI 300 excess return (D15).
  - Explicit min_group_n >= 30 & 15%-85% balance audit, sample_warning="N<30",
    date-clustered SEs, 2,000x permutation p_perm, v20_score control, and BH-FDR.
"""
import json
import math
import os
import sys
import time
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WORK_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
INPUT_PQ = f"{WORK_DIR}/pools_6strat_with_oldhot.parquet"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"

OUT_JSON = f"{WORK_DIR}/wave2a_6strat_oldhot_matrix.json"
OUT_CSV = f"{WORK_DIR}/wave2a_fdr_survivors.csv"

MAIN_STRATS = ["1to2", "2to3", "3to4", "high", "pry", "20cm"]
ALL_STRATS = MAIN_STRATS + ["temp5b"]
PRIMARY_LAYERS = ["L1_all_cand", "L2_pass_off", "L3_edge_straddle"]
ALL_LAYERS = ["L1_all_cand", "L2_pass_off", "L2b_slot1", "L3_edge_straddle", "L3b_edge_below"]
N_PERM = 2000
RNG_SEED = 20261125

COOL_ORDER = ["never", "<=30d", "31~90d", "91~180d", "181~365d", ">365d"]

# 6-Dimension 18-indicator specification
INDICATOR_SPECS = [
    # Dim A: Historical wave count & active years
    {"dim": "A", "col": "waves_3y_g15", "kind": "num",
     "bins": [-1, 0, 2, 5, 9, 999], "labels": ["0(new)", "1~2", "3~5", "6~9", ">=10"]},
    {"dim": "A", "col": "active_years_5y", "kind": "num",
     "bins": [-1, 0, 1, 2, 3, 9], "labels": ["0(new)", "1yr", "2yr", "3yr", "4~5yr"]},
    # Dim B: Historical ZT counts & max streak
    {"dim": "B", "col": "zt_cnt_3y", "kind": "num",
     "bins": [-1, 0, 4, 9, 19, 999], "labels": ["0(new)", "1~4", "5~9", "10~19", ">=20"]},
    {"dim": "B", "col": "zt_cnt_1y", "kind": "num",
     "bins": [-1, 0, 2, 5, 10, 999], "labels": ["0", "1~2", "3~5", "6~10", ">10"]},
    {"dim": "B", "col": "max_streak_5y", "kind": "num",
     "bins": [-1, 0, 1, 2, 4, 999], "labels": ["0", "1b", "2b", "3~4b", ">=5b"]},
    {"dim": "B", "col": "streak3_waves_5y", "kind": "num",
     "bins": [-1, 0, 1, 2, 999], "labels": ["0", "1", "2", ">=3"]},
    # Dim C: Long-term community attention
    {"dim": "C", "col": "comm_posts_1y_pct", "kind": "num",
     "bins": [-0.01, 0.2, 0.4, 0.6, 0.8, 1.01], "labels": ["Q1(0~20%)", "Q2(20~40%)", "Q3(40~60%)", "Q4(60~80%)", "Q5(80~100%)"]},
    {"dim": "C", "col": "comm_posts_3y_pct", "kind": "num",
     "bins": [-0.01, 0.2, 0.4, 0.6, 0.8, 1.01], "labels": ["Q1(0~20%)", "Q2(20~40%)", "Q3(40~60%)", "Q4(60~80%)", "Q5(80~100%)"]},
    {"dim": "C", "col": "comm_active_month_ratio_3y", "kind": "num",
     "bins": [-0.01, 0.05, 0.20, 0.35, 0.50, 1.01], "labels": ["<=5%", "5~20%", "20~35%", "35~50%", ">50%"]},
    # Dim D: Chip turnover & trapped overhang
    {"dim": "D", "col": "cum_turnover_1y", "kind": "num",
     "bins": [-0.01, 4.0, 7.0, 11.0, 17.0, 999.0], "labels": ["<=4x", "4~7x", "7~11x", "11~17x", ">17x"]},
    {"dim": "D", "col": "trap_waves_3y", "kind": "num",
     "bins": [-1, 0, 1, 2, 4, 99], "labels": ["0", "1", "2", "3~4", ">=5"]},
    {"dim": "D", "col": "dd_from_1y_high", "kind": "num",
     "bins": [-99.0, -0.50, -0.35, -0.20, -0.05, 1.0], "labels": ["<=-50%", "-50~-35%", "-35~-20%", "-20~-5%", ">-5%(hi)"]},
    {"dim": "D", "col": "dd_from_3y_high", "kind": "num",
     "bins": [-99.0, -0.60, -0.45, -0.30, -0.10, 1.0], "labels": ["<=-60%", "-60~-45%", "-45~-30%", "-30~-10%", ">-10%(hi)"]},
    # Dim E: Theme purity & plate switching
    {"dim": "E", "col": "kpl_unique_plates_5y", "kind": "num",
     "bins": [-1, 0, 2, 4, 7, 999], "labels": ["0", "1~2", "3~4", "5~7", ">=8"]},
    {"dim": "E", "col": "kpl_plate_switch_ratio", "kind": "num",
     "bins": [-0.01, 0.25, 0.55, 0.7499, 1.01], "labels": ["<=0.25(pure)", "0.25~0.55", "0.55~0.75", ">=0.75(switch)"]},
    {"dim": "E", "col": "kpl_top_plate_share", "kind": "num",
     "bins": [-0.01, 0.35, 0.50, 0.67, 0.85, 1.01], "labels": ["<=35%", "35~50%", "50~67%", "67~85%", ">85%(core)"]},
    # Dim F: Cooling windows (log1p continuous on non-never + 6-bin categorical table)
    {"dim": "F", "col": "cool_days_since_last_zt", "kind": "cool", "bin_col": "cool_bin_zt"},
    {"dim": "F", "col": "cool_days_since_last_2b", "kind": "cool", "bin_col": "cool_bin_2b"},
]

HORSE_RACE_DIMS = [
    ("A_waves_3y", "waves_3y_g15"),
    ("B_zt_cnt_3y", "zt_cnt_3y"),
    ("C_comm_1y_pct", "comm_posts_1y_pct"),
    ("D_dd_1y_high", "dd_from_1y_high"),
    ("D_trap_3y", "trap_waves_3y"),
    ("D_turn_1y", "cum_turnover_1y"),
    ("E_switch_ratio", "kpl_plate_switch_ratio"),
    ("E_uniq_plates_5y", "kpl_unique_plates_5y"),
    ("F_log_cool_zt", "log_cool_zt"),
    ("S_v20_score", "v20_score"),
]


def sf(v: Any, digits: int = 4) -> float | None:
    if v is None:
        return None
    fv = float(v)
    if math.isnan(fv) or math.isinf(fv):
        return None
    return round(fv, digits)


def bh_fdr(pvals: np.ndarray) -> np.ndarray:
    """Standard Benjamini-Hochberg FDR q-values preserving NaNs."""
    out = np.full(len(pvals), np.nan, dtype=float)
    valid = np.isfinite(pvals)
    m = int(valid.sum())
    if m == 0:
        return out
    pv = np.clip(pvals[valid], 0.0, 1.0)
    order = np.argsort(pv)
    ranks = np.arange(1, m + 1, dtype=float)
    q_sorted = pv[order] * m / ranks
    q_sorted = np.minimum.accumulate(q_sorted[::-1])[::-1]
    q_sorted = np.clip(q_sorted, 0.0, 1.0)
    q_valid = np.empty(m, dtype=float)
    q_valid[order] = q_sorted
    out[valid] = q_valid
    return out


def load_data_and_benchmark() -> tuple[pd.DataFrame, dict[str, float], list[str], dict[str, str]]:
    idx_raw = json.load(open(IDX_JSON, encoding="utf-8"))
    sh300 = {k: float(v) for k, v in idx_raw["sh000300"].items()}
    all_sh_dts = sorted(sh300.keys())
    prev_td = {all_sh_dts[i]: all_sh_dts[i - 1] for i in range(1, len(all_sh_dts))}

    df = pd.read_parquet(INPUT_PQ)
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["buy_date"] = df["buy_date"].astype(str).str[:10]
    df["exit_date"] = df["exit_date"].astype(str).str[:10]

    # Precompute concurrent CSI 300 return for every valid simulated trade
    csi_r = np.full(len(df), np.nan, dtype=float)
    sim_mask = df["sim_ok"].to_numpy(bool) & df["net_ret"].notna().to_numpy(bool)
    bds = df["buy_date"].to_numpy()
    eds = df["exit_date"].to_numpy()
    for i in np.flatnonzero(sim_mask):
        p0_dt = prev_td.get(bds[i])
        if p0_dt is not None and eds[i] in sh300:
            csi_r[i] = sh300[eds[i]] / sh300[p0_dt] - 1.0
    df["csi_trade_ret"] = csi_r
    df["excess_trade_ret"] = df["net_ret"].astype(float) - df["csi_trade_ret"]
    df["log_cool_zt"] = np.log1p(df["cool_days_since_last_zt"].astype(float))
    df["log_cool_2b"] = np.log1p(df["cool_days_since_last_2b"].astype(float))
    df["is_never_zt"] = (df["cool_bin_zt"] == "never").astype(float)
    return df, sh300, all_sh_dts, prev_td


def get_layer_mask(df: pd.DataFrame, strat: str, layer: str) -> pd.Series:
    base = (df["strategy"] == strat) & df["sim_ok"].astype(bool) & df["net_ret"].notna()
    if layer == "L1_all_cand":
        return base
    if layer == "L2_pass_off":
        return base & df["is_pass_official"].astype(bool)
    if layer == "L2b_slot1":
        return base & df["is_standalone_slot1"].astype(bool)
    if layer == "L3_edge_straddle":
        if strat == "20cm":
            return base & df["v20_score"].between(72.0, 86.0)
        return base & (df["is_near_line"].astype(bool) | (df["is_pass_official"].astype(bool) & (~df["is_s_tier"].astype(bool))))
    if layer == "L3b_edge_below":
        return base & df["is_edge_cand"].astype(bool)
    raise ValueError(f"Unknown layer: {layer}")


def span_csi_pct(sub: pd.DataFrame, sh300: dict[str, float], all_sh_dts: list[str], prev_td: dict[str, str]) -> float | None:
    if sub.empty:
        return None
    sdt = str(sub["buy_date"].min())
    edt = str(sub["exit_date"].max())
    p0_dt = prev_td.get(sdt)
    if p0_dt is None:
        prevs = [d for d in all_sh_dts if d < sdt]
        p0_dt = prevs[-1] if prevs else all_sh_dts[0]
    if edt not in sh300:
        posts = [d for d in all_sh_dts if d <= edt]
        edt = posts[-1] if posts else all_sh_dts[-1]
    return float((sh300[edt] / sh300[p0_dt] - 1.0) * 100.0)


def slot1_subset_comp(sub: pd.DataFrame, sh300: dict[str, float], all_sh_dts: list[str], prev_td: dict[str, str]) -> tuple[int, float | None, float | None]:
    if sub.empty:
        return 0, None, None
    srt = sub.sort_values(["buy_date", "buy_hhmm", "v20_score", "code"], ascending=[True, True, False, True])
    taken = []
    fdt, fhh = "", 0
    for r in srt.itertuples(index=False):
        if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
            taken.append(r)
            fdt, fhh = r.exit_date, int(r.exit_hhmm)
    if not taken:
        return 0, None, None
    tdf = pd.DataFrame(taken)
    rets = tdf["net_ret"].to_numpy(float)
    comp_pct = (float(np.prod(1.0 + rets)) - 1.0) * 100.0
    csi_p = span_csi_pct(tdf, sh300, all_sh_dts, prev_td)
    ex_pp = comp_pct - csi_p if csi_p is not None else None
    return int(len(tdf)), sf(comp_pct, 2), sf(ex_pp, 2)


def eval_slice_metrics(sub: pd.DataFrame, sh300: dict[str, float], all_sh_dts: list[str], prev_td: dict[str, str]) -> dict:
    n = int(len(sub))
    if n == 0:
        return {"n": 0}
    rets = sub["net_ret"].to_numpy(float)
    exs = sub["excess_trade_ret"].to_numpy(float)
    w = rets[rets > 0]
    l = rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) > 0 and len(l) > 0 and l.mean() < 0) else (99.0 if len(w) > 0 else 0.0)

    # By-date equal-weight compounding
    day_g = sub.groupby("buy_date", sort=True)
    day_r = day_g["net_ret"].mean().to_numpy(float)
    day_ex = day_g["excess_trade_ret"].mean().to_numpy(float)
    ew_comp_pct = (float(np.prod(1.0 + day_r)) - 1.0) * 100.0
    csi_p = span_csi_pct(sub, sh300, all_sh_dts, prev_td)
    ew_ex_pp = ew_comp_pct - csi_p if csi_p is not None else None

    s1_n, s1_comp_pct, s1_ex_pp = slot1_subset_comp(sub, sh300, all_sh_dts, prev_td)

    return {
        "n": n,
        "unique_dates": int(sub["buy_date"].nunique()),
        "wr_pct": sf(wr, 2),
        "plr": sf(plr, 2),
        "mean_ret_pct": sf(np.mean(rets) * 100.0, 3),
        "median_ret_pct": sf(np.median(rets) * 100.0, 3),
        "mean_trade_ex_csi300_pct": sf(np.nanmean(exs) * 100.0, 3),
        "ew_date_mean_pct": sf(np.mean(day_r) * 100.0, 3),
        "ew_date_ex_csi300_mean_pct": sf(np.nanmean(day_ex) * 100.0, 3),
        "ew_date_comp_ret_pct": sf(ew_comp_pct, 2),
        "csi300_span_pct": sf(csi_p, 2),
        "ew_date_excess_csi300_pp": sf(ew_ex_pp, 2),
        "slot1_n": s1_n,
        "slot1_comp_ret_pct": s1_comp_pct,
        "slot1_excess_csi300_pp": s1_ex_pp,
    }


def _safe_ols(y: np.ndarray, X: np.ndarray, clusters: np.ndarray):
    """Fit OLS returning HC3 and date-clustered t/p stats safely with rank/collinearity guards."""
    keep_cols = [0]
    for j in range(1, X.shape[1]):
        cand = X[:, keep_cols + [j]]
        if np.std(X[:, j]) > 1e-10 and np.linalg.matrix_rank(cand) > len(keep_cols):
            keep_cols.append(j)
    Xk = X[:, keep_cols]
    n, k = Xk.shape
    if n <= k + 2:
        return None
    mod = sm.OLS(y, Xk)
    try:
        r_hc3 = mod.fit(cov_type="HC3", use_t=True)
        if not np.all(np.isfinite(r_hc3.bse)):
            r_hc3 = mod.fit(cov_type="HC1", use_t=True)
    except Exception:
        r_hc3 = mod.fit(cov_type="HC1", use_t=True)

    n_cl = len(np.unique(clusters))
    try:
        if n_cl >= k + 2:
            r_cl = mod.fit(cov_type="cluster", cov_kwds={"groups": clusters}, use_t=True)
            if not np.all(np.isfinite(r_cl.bse)):
                r_cl = r_hc3
        else:
            r_cl = r_hc3
    except Exception:
        r_cl = r_hc3

    return {"keep_cols": keep_cols, "r_hc3": r_hc3, "r_cl": r_cl, "n_clusters": n_cl}


def perm_spearman_and_fwl(
    x: np.ndarray,
    y: np.ndarray,
    z_ctrl: np.ndarray | None,
    rng: np.random.Generator,
    n_perm: int = N_PERM,
) -> dict:
    """Vectorized 2,000x permutation test for Spearman rho & FWL quadratic partial R^2."""
    n = len(y)
    if n < 8 or np.std(x) < 1e-12 or np.std(y) < 1e-12:
        return {
            "spearman_r": None, "spearman_p": None, "p_perm_spearman": None,
            "p_perm_quad": None, "p_perm_quad_ctrl": None,
        }

    rho, sp_p = stats.spearmanr(x, y)
    rx = stats.rankdata(x).astype(float)
    ry = stats.rankdata(y).astype(float)
    rx0 = rx - rx.mean()
    ry0 = ry - ry.mean()
    rx_u = rx0 / np.linalg.norm(rx0)
    ry_u = ry0 / np.linalg.norm(ry0)

    # Generate permutation index matrix [n, n_perm]
    perm_idx = np.argsort(rng.random((n, n_perm)), axis=0)
    ry_perm = ry_u[perm_idx]
    perm_rhos = rx_u @ ry_perm
    p_perm_sp = float((np.sum(np.abs(perm_rhos) >= abs(float(rho)) - 1e-12) + 1.0) / (n_perm + 1.0))

    # FWL exact quadratic permutation (uncontrolled & score-controlled)
    z = (x - np.mean(x)) / np.std(x)
    z2 = z ** 2

    def _fwl_perm_p(covs: np.ndarray, target: np.ndarray) -> float | None:
        if np.linalg.matrix_rank(covs) < covs.shape[1]:
            return None
        Q, _ = np.linalg.qr(covs)
        t_perp = target - Q @ (Q.T @ target)
        t_norm = np.linalg.norm(t_perp)
        if t_norm < 1e-10:
            return None
        t_u = t_perp / t_norm

        y_perp = y - Q @ (Q.T @ y)
        y_n = np.linalg.norm(y_perp)
        if y_n < 1e-10:
            return None
        obs_r = abs(float(np.dot(t_u, y_perp) / y_n))

        yp = y[perm_idx]
        yp_perp = yp - Q @ (Q.T @ yp)
        yp_norms = np.linalg.norm(yp_perp, axis=0)
        valid_p = yp_norms > 1e-10
        if not valid_p.any():
            return None
        pr = np.abs((t_u @ yp_perp[:, valid_p]) / yp_norms[valid_p])
        return float((np.sum(pr >= obs_r - 1e-12) + 1.0) / (int(valid_p.sum()) + 1.0))

    cov_unc = np.column_stack([np.ones(n), z])
    p_perm_q = _fwl_perm_p(cov_unc, z2)

    p_perm_qc = None
    if z_ctrl is not None and np.std(z_ctrl) > 1e-10:
        zc = (z_ctrl - np.mean(z_ctrl)) / np.std(z_ctrl)
        cov_c = np.column_stack([np.ones(n), z, zc])
        p_perm_qc = _fwl_perm_p(cov_c, z2)

    return {
        "spearman_r": sf(rho, 4),
        "spearman_p": sf(sp_p, 6),
        "p_perm_spearman": sf(p_perm_sp, 5),
        "p_perm_quad": sf(p_perm_q, 5),
        "p_perm_quad_ctrl": sf(p_perm_qc, 5),
    }


def analyze_continuous_nonlinear(
    sub: pd.DataFrame,
    x_vals: np.ndarray,
    rng: np.random.Generator,
) -> dict:
    """Run Spearman, permutation, linear/quadratic OLS (HC3 + date cluster), and score-controlled tests."""
    y = sub["net_ret"].to_numpy(float)
    sc = sub["v20_score"].to_numpy(float)
    cl = sub["buy_date"].to_numpy()
    n = len(y)

    if n < 10 or np.std(x_vals) < 1e-10 or np.std(y) < 1e-10:
        return {"n_valid": int(n), "insufficient_var": True}

    perm_res = perm_spearman_and_fwl(x_vals, y, sc, rng, N_PERM)

    z = (x_vals - np.mean(x_vals)) / np.std(x_vals)
    z2 = z ** 2
    has_sc = np.std(sc) > 1e-10
    z_sc = (sc - np.mean(sc)) / np.std(sc) if has_sc else np.zeros(n)

    # 1. Pure Linear OLS: y ~ 1 + z
    res_l = _safe_ols(y, np.column_stack([np.ones(n), z]), cl)
    # 2. Pure Quadratic OLS: y ~ 1 + z + z^2
    res_q = _safe_ols(y, np.column_stack([np.ones(n), z, z2]), cl)
    # 3. Controlled Quadratic OLS: y ~ 1 + z + z^2 + z_sc
    X_c = np.column_stack([np.ones(n), z, z2, z_sc]) if has_sc else np.column_stack([np.ones(n), z, z2])
    res_qc = _safe_ols(y, X_c, cl)
    # 4. Controlled Linear OLS: y ~ 1 + z + z_sc
    X_lc = np.column_stack([np.ones(n), z, z_sc]) if has_sc else np.column_stack([np.ones(n), z])
    res_lc = _safe_ols(y, X_lc, cl)

    def _ext(fit_obj, col_idx):
        if fit_obj is None or col_idx not in fit_obj["keep_cols"]:
            return None, None, None, None, None
        pos = fit_obj["keep_cols"].index(col_idx)
        rh, rc = fit_obj["r_hc3"], fit_obj["r_cl"]
        return (
            sf(rc.params[pos], 5),
            sf(rh.tvalues[pos], 3),
            sf(rh.pvalues[pos], 6),
            sf(rc.tvalues[pos], 3),
            sf(rc.pvalues[pos], 6),
        )

    b_l, t_l_hc3, p_l_hc3, t_l_cl, p_l_cl = _ext(res_l, 1)
    _, _, _, t_l_ctrl_cl, p_l_ctrl_cl = _ext(res_lc, 1)
    b_qlin, _, _, t_qlin_cl, p_qlin_cl = _ext(res_q, 1)
    b_q, t_q_hc3, p_q_hc3, t_q_cl, p_q_cl = _ext(res_q, 2)
    b_q_ctrl, t_q_ctrl_hc3, p_q_ctrl_hc3, t_q_ctrl_cl, p_q_ctrl_cl = _ext(res_qc, 2)
    b_ql_ctrl, _, _, t_ql_ctrl_cl, p_ql_ctrl_cl = _ext(res_qc, 1)

    # Joint 2-df F-test for [z, z^2] = 0 in controlled model (guard against small N/cluster covariance collapse)
    p_joint_ctrl_cl = None
    if res_qc is not None and n >= 30 and res_qc["n_clusters"] >= 20 and 1 in res_qc["keep_cols"] and 2 in res_qc["keep_cols"]:
        k_qc = len(res_qc["keep_cols"])
        R = np.zeros((2, k_qc))
        R[0, res_qc["keep_cols"].index(1)] = 1.0
        R[1, res_qc["keep_cols"].index(2)] = 1.0
        try:
            p_joint_ctrl_cl = sf(float(res_qc["r_cl"].f_test(R).pvalue), 6)
        except Exception:
            p_joint_ctrl_cl = None

    # Peak location check inside [p10, p90] for U / inverted-U classification
    z_p10, z_p90 = float(np.quantile(z, 0.10)), float(np.quantile(z, 0.90))
    vertex_z = None
    interior_vertex = False
    if b_ql_ctrl is not None and b_q_ctrl is not None and abs(b_q_ctrl) > 1e-8:
        vertex_z = -b_ql_ctrl / (2.0 * b_q_ctrl)
        interior_vertex = (z_p10 <= vertex_z <= z_p90)
    elif b_qlin is not None and b_q is not None and abs(b_q) > 1e-8:
        vertex_z = -b_qlin / (2.0 * b_q)
        interior_vertex = (z_p10 <= vertex_z <= z_p90)

    # Date-collapsed Spearman check (collapsing same-day trades to avoid day-clustering inflation)
    tmp = pd.DataFrame({"dt": cl, "x": x_vals, "y": y})
    dt_agg = tmp.groupby("dt", as_index=False).mean()
    if len(dt_agg) >= 8 and dt_agg["x"].std() > 1e-10 and dt_agg["y"].std() > 1e-10:
        r_dt, p_dt = stats.spearmanr(dt_agg["x"], dt_agg["y"])
    else:
        r_dt, p_dt = np.nan, np.nan

    # Partial Spearman rank correlation controlling for v20_score
    if has_sc:
        rx = stats.rankdata(x_vals).astype(float)
        ry = stats.rankdata(y).astype(float)
        rs = stats.rankdata(sc).astype(float)
        rx_r = rx - np.polyval(np.polyfit(rs, rx, 1), rs)
        ry_r = ry - np.polyval(np.polyfit(rs, ry, 1), rs)
        if np.std(rx_r) > 1e-10 and np.std(ry_r) > 1e-10:
            p_sp_r, p_sp_p = stats.spearmanr(rx_r, ry_r)
        else:
            p_sp_r, p_sp_p = np.nan, np.nan
    else:
        p_sp_r, p_sp_p = np.nan, np.nan

    return {
        "n_valid": int(n),
        "n_date_clusters": int(len(np.unique(cl))),
        "insufficient_var": False,
        **perm_res,
        "partial_spearman_r_ctrl": sf(p_sp_r, 4),
        "partial_spearman_p_ctrl": sf(p_sp_p, 6),
        "date_collapsed_n": int(len(dt_agg)),
        "date_collapsed_spearman_r": sf(r_dt, 4),
        "date_collapsed_spearman_p": sf(p_dt, 6),
        "beta_lin": b_l,
        "t_lin_hc3": t_l_hc3,
        "p_lin_hc3": p_l_hc3,
        "t_lin_cl": t_l_cl,
        "p_lin_cl": p_l_cl,
        "t_lin_ctrl_cl": t_l_ctrl_cl,
        "p_lin_ctrl_cl": p_l_ctrl_cl,
        "beta_quad": b_q,
        "t_quad_hc3": t_q_hc3,
        "p_quad_hc3": p_q_hc3,
        "t_quad_cl": t_q_cl,
        "p_quad_cl": p_q_cl,
        "beta_quad_ctrl": b_q_ctrl,
        "t_quad_ctrl_hc3": t_q_ctrl_hc3,
        "p_quad_ctrl_hc3": p_q_ctrl_hc3,
        "t_quad_ctrl_cl": t_q_ctrl_cl,
        "p_quad_ctrl_cl": p_q_ctrl_cl,
        "p_joint_ctrl_cl": p_joint_ctrl_cl,
        "vertex_z": sf(vertex_z, 3),
        "interior_vertex": bool(interior_vertex),
    }


def classify_shape(cont: dict, q_lin_v: float | None, q_quad_v: float | None, q_joint_v: float | None) -> str:
    """Classify shape into inverted_u / u_shape / monotone_inc / monotone_dec / null."""
    if cont.get("insufficient_var"):
        return "insufficient_var"
    pq = q_quad_v if (q_quad_v is not None and not np.isnan(q_quad_v)) else cont.get("p_quad_ctrl_cl")
    pl = q_lin_v if (q_lin_v is not None and not np.isnan(q_lin_v)) else cont.get("p_lin_ctrl_cl")
    pj = q_joint_v if (q_joint_v is not None and not np.isnan(q_joint_v)) else cont.get("p_joint_ctrl_cl")

    # Check raw vs FDR significance separately via caller; here classify raw shape AND FDR shape
    bq = cont.get("beta_quad_ctrl") or cont.get("beta_quad")
    bl = cont.get("beta_lin")
    if pq is not None and pq < 0.10 and cont.get("interior_vertex") and bq is not None:
        return "inverted_u" if bq < 0 else "u_shape"
    if (pl is not None and pl < 0.10) or (pj is not None and pj < 0.10):
        if bl is not None:
            return "monotone_inc" if bl > 0 else "monotone_dec"
    return "null"


def check_balance_and_bins(
    sub: pd.DataFrame,
    spec: dict,
    sh300: dict[str, float],
    all_sh_dts: list[str],
    prev_td: dict[str, str],
) -> tuple[list[dict], dict, list[dict]]:
    """Compute fixed semantic bin table, binary balance audit, and fallback quintile table if needed."""
    col = spec["col"]
    kind = spec["kind"]

    if kind == "cool":
        bcol = spec["bin_col"]
        cat_s = pd.Categorical(sub[bcol], categories=COOL_ORDER, ordered=True)
        labels = COOL_ORDER
        sub_valid = sub[sub[col].notna()].copy()
    else:
        sub_valid = sub[sub[col].notna()].copy()
        cat_s = pd.cut(sub_valid[col], bins=spec["bins"], labels=spec["labels"])
        labels = spec["labels"]

    # Bin table
    bin_rows = []
    tot_n = len(sub) if kind == "cool" else len(sub_valid)
    src_df = sub if kind == "cool" else sub_valid
    for lbl in labels:
        m = (cat_s == lbl)
        b_df = src_df[m]
        if len(b_df) == 0:
            bin_rows.append({"bin": str(lbl), "n": 0, "pct": 0.0})
        else:
            met = eval_slice_metrics(b_df, sh300, all_sh_dts, prev_td)
            met["bin"] = str(lbl)
            met["pct"] = sf(len(b_df) / tot_n * 100.0, 2) if tot_n > 0 else 0.0
            bin_rows.append(met)

    non_empty_ns = [r["n"] for r in bin_rows if r["n"] > 0]
    min_bin_n = min(non_empty_ns) if non_empty_ns else 0
    bins_ge30 = sum(1 for r in bin_rows if r["n"] >= 30)

    # Balanced binary split check at median (on valid numeric values)
    v_num = sub_valid[col].astype(float)
    if len(v_num) >= 2 and v_num.std() > 1e-10:
        med = float(v_num.median())
        hi = sub_valid[v_num > med]
        lo = sub_valid[v_num <= med]
        if len(hi) == 0 or len(lo) == 0:
            hi = sub_valid[v_num >= med]
            lo = sub_valid[v_num < med]
        min_bin2_n = min(len(hi), len(lo))
        min_bin2_pct = min_bin2_n / len(sub_valid) * 100.0
        balance_ok = (min_bin2_n >= 30) and (15.0 <= min_bin2_pct <= 85.0)
        hi_mean = sf(hi["net_ret"].mean() * 100.0, 3) if len(hi) else None
        lo_mean = sf(lo["net_ret"].mean() * 100.0, 3) if len(lo) else None
        diff_hi_lo = sf((hi["net_ret"].mean() - lo["net_ret"].mean()) * 100.0, 3) if (len(hi) and len(lo)) else None
    else:
        min_bin2_n, min_bin2_pct, balance_ok = 0, 0.0, False
        hi_mean, lo_mean, diff_hi_lo = None, None, None

    warn_flags = []
    if len(sub_valid) < 30:
        warn_flags.append("N<30")
    if not balance_ok and len(sub_valid) >= 30:
        warn_flags.append(f"BINARY_MIN_N={min_bin2_n}({min_bin2_pct:.1f}%)")
    if min_bin_n < 15:
        warn_flags.append(f"MIN_TIER_N={min_bin_n}<15")

    balance_info = {
        "n_total_layer": int(len(sub)),
        "n_valid": int(len(sub_valid)),
        "missing_pct": sf((1.0 - len(sub_valid) / max(len(sub), 1)) * 100.0, 2),
        "populated_bins": len(non_empty_ns),
        "bins_ge_30": bins_ge30,
        "min_bin_n": int(min_bin_n),
        "binary_min_group_n": int(min_bin2_n),
        "binary_min_group_pct": sf(min_bin2_pct, 2),
        "binary_balance_pass": bool(balance_ok),
        "binary_hi_mean_pct": hi_mean,
        "binary_lo_mean_pct": lo_mean,
        "binary_diff_hi_minus_lo_pp": diff_hi_lo,
        "sample_warning": ";".join(warn_flags) if warn_flags else "OK",
    }

    # Within-pool balanced quantile bins if semantic bins are sparse/skewed
    q_rows = []
    if len(sub_valid) >= 40 and v_num.nunique() >= 5:
        try:
            q_cat = pd.qcut(v_num, q=5, duplicates="drop")
            for iv in q_cat.cat.categories:
                q_df = sub_valid[q_cat == iv]
                met = eval_slice_metrics(q_df, sh300, all_sh_dts, prev_td)
                met["bin"] = str(iv)
                met["pct"] = sf(len(q_df) / len(sub_valid) * 100.0, 2)
                q_rows.append(met)
        except Exception:
            q_rows = []

    return bin_rows, balance_info, q_rows


def run_module1(df: pd.DataFrame, sh300: dict, all_sh_dts: list, prev_td: dict, rng: np.random.Generator) -> tuple[dict, pd.DataFrame]:
    """Module 1: 6 Strategies x 5 Layers (3 Primary + 2 Companion) x 18 Indicators + BH-FDR."""
    print("[Module 1] Running 6 strategies x 5 layers x 18 indicators (2,000x perm + quadratic + score ctrl)...")
    records = []
    detail_tree: dict[str, dict] = {}

    for strat in MAIN_STRATS:
        detail_tree[strat] = {}
        for layer in ALL_LAYERS:
            mask = get_layer_mask(df, strat, layer)
            sub = df[mask].copy()
            base_met = eval_slice_metrics(sub, sh300, all_sh_dts, prev_td)
            detail_tree[strat][layer] = {"baseline": base_met, "indicators": {}}

            for spec in INDICATOR_SPECS:
                col = spec["col"]
                kind = spec["kind"]
                bin_rows, bal_info, q_rows = check_balance_and_bins(sub, spec, sh300, all_sh_dts, prev_td)

                if kind == "cool":
                    valid_sub = sub[sub[col].notna()].copy()
                    x_vals = np.log1p(valid_sub[col].to_numpy(float))
                else:
                    valid_sub = sub[sub[col].notna()].copy()
                    x_vals = valid_sub[col].to_numpy(float)

                cont = analyze_continuous_nonlinear(valid_sub, x_vals, rng)

                # Categorical ANOVA / cluster F-test across populated cooling bins (ref = largest group; min_n>=10, min_cl>=8)
                cat_f_p = None
                if kind == "cool" and len(sub) >= 30:
                    bcol = spec["bin_col"]
                    vc = sub.groupby(bcol, observed=True).agg(n=("net_ret", "size"), cl=("buy_date", "nunique"))
                    valid_cats = [c for c in COOL_ORDER if c in vc.index and vc.loc[c, "n"] >= 10 and vc.loc[c, "cl"] >= 8]
                    if len(valid_cats) >= 2:
                        sub_cat = sub[sub[bcol].isin(valid_cats)].copy()
                        if len(sub_cat) >= 30 and sub_cat["buy_date"].nunique() >= 20:
                            ref_cat = max(valid_cats, key=lambda c: int(vc.loc[c, "n"]))
                            other_cats = [c for c in valid_cats if c != ref_cat]
                            X_cols = [np.ones(len(sub_cat))] + [(sub_cat[bcol] == c).to_numpy(float) for c in other_cats]
                            X_cat = np.column_stack(X_cols)
                            fit_cat = _safe_ols(sub_cat["net_ret"].to_numpy(float), X_cat, sub_cat["buy_date"].to_numpy())
                            if fit_cat is not None and len(fit_cat["keep_cols"]) > 1:
                                R = np.zeros((len(fit_cat["keep_cols"]) - 1, len(fit_cat["keep_cols"])))
                                for r_i in range(len(fit_cat["keep_cols"]) - 1):
                                    R[r_i, r_i + 1] = 1.0
                                try:
                                    cat_f_p = sf(float(fit_cat["r_cl"].f_test(R).pvalue), 6)
                                except Exception:
                                    cat_f_p = None

                raw_shape = classify_shape(cont, None, None, None)

                cell_obj = {
                    "dim": spec["dim"],
                    "indicator": col,
                    "sample_audit": bal_info,
                    "continuous_tests": cont,
                    "cat_anova_cluster_p": cat_f_p,
                    "raw_shape_p10": raw_shape,
                    "bins": bin_rows,
                    "quintile_bins": q_rows,
                }
                detail_tree[strat][layer]["indicators"][col] = cell_obj

                records.append({
                    "strategy": strat,
                    "layer": layer,
                    "is_primary_layer": layer in PRIMARY_LAYERS,
                    "dim": spec["dim"],
                    "indicator": col,
                    "n_layer": bal_info["n_total_layer"],
                    "n_valid": bal_info["n_valid"],
                    "n_date_clusters": cont.get("n_date_clusters", 0),
                    "min_bin_n": bal_info["min_bin_n"],
                    "binary_min_group_n": bal_info["binary_min_group_n"],
                    "binary_balance_pass": bal_info["binary_balance_pass"],
                    "sample_warning": bal_info["sample_warning"],
                    "binary_diff_pp": bal_info["binary_diff_hi_minus_lo_pp"],
                    "spearman_r": cont.get("spearman_r"),
                    "spearman_p": cont.get("spearman_p"),
                    "p_perm_spearman": cont.get("p_perm_spearman"),
                    "partial_spearman_r_ctrl": cont.get("partial_spearman_r_ctrl"),
                    "partial_spearman_p_ctrl": cont.get("partial_spearman_p_ctrl"),
                    "date_collapsed_r": cont.get("date_collapsed_spearman_r"),
                    "date_collapsed_p": cont.get("date_collapsed_spearman_p"),
                    "beta_lin": cont.get("beta_lin"),
                    "t_lin_hc3": cont.get("t_lin_hc3"),
                    "t_lin_cl": cont.get("t_lin_cl"),
                    "p_lin_cl": cont.get("p_lin_cl"),
                    "t_lin_ctrl_cl": cont.get("t_lin_ctrl_cl"),
                    "p_lin_ctrl_cl": cont.get("p_lin_ctrl_cl"),
                    "beta_quad": cont.get("beta_quad"),
                    "t_quad_hc3": cont.get("t_quad_hc3"),
                    "t_quad_cl": cont.get("t_quad_cl"),
                    "p_quad_cl": cont.get("p_quad_cl"),
                    "beta_quad_ctrl": cont.get("beta_quad_ctrl"),
                    "t_quad_ctrl_hc3": cont.get("t_quad_ctrl_hc3"),
                    "t_quad_ctrl_cl": cont.get("t_quad_ctrl_cl"),
                    "p_quad_ctrl_cl": cont.get("p_quad_ctrl_cl"),
                    "p_perm_quad": cont.get("p_perm_quad"),
                    "p_perm_quad_ctrl": cont.get("p_perm_quad_ctrl"),
                    "p_joint_ctrl_cl": cont.get("p_joint_ctrl_cl"),
                    "cat_anova_cluster_p": cat_f_p,
                    "vertex_z": cont.get("vertex_z"),
                    "interior_vertex": cont.get("interior_vertex", False),
                    "raw_shape": raw_shape,
                })

    res_df = pd.DataFrame(records)

    # BH-FDR over Primary 3 Layers (6 x 3 x 18 = 324 tests) and All 5 Layers (540 tests)
    prim_m = res_df["is_primary_layer"].to_numpy(bool)
    p_cols = ["p_perm_spearman", "p_lin_ctrl_cl", "p_quad_ctrl_cl", "p_joint_ctrl_cl", "date_collapsed_p", "cat_anova_cluster_p"]
    q_names = ["q_spearman_prim3", "q_lin_ctrl_prim3", "q_quad_ctrl_prim3", "q_joint_ctrl_prim3", "q_date_coll_prim3", "q_cat_anova_prim3"]
    for pc, qn in zip(p_cols, q_names):
        arr = np.full(len(res_df), np.nan)
        arr[prim_m] = bh_fdr(res_df.loc[prim_m, pc].to_numpy(float))
        res_df[qn] = np.round(arr, 6)

    for pc, qn in zip(p_cols, ["q_spearman_all5", "q_lin_ctrl_all5", "q_quad_ctrl_all5", "q_joint_ctrl_all5", "q_date_coll_all5", "q_cat_anova_all5"]):
        res_df[qn] = np.round(bh_fdr(res_df[pc].to_numpy(float)), 6)

    # Best conservative primary q-value across Spearman / Controlled Joint (min of joint & spearman FDR)
    res_df["q_best_prim3"] = res_df[["q_spearman_prim3", "q_joint_ctrl_prim3", "q_quad_ctrl_prim3", "q_lin_ctrl_prim3", "q_cat_anova_prim3"]].min(axis=1)
    res_df["q_best_all5"] = res_df[["q_spearman_all5", "q_joint_ctrl_all5", "q_quad_ctrl_all5", "q_lin_ctrl_all5", "q_cat_anova_all5"]].min(axis=1)

    # FDR-confirmed shape classification
    fdr_shapes = []
    for r in res_df.itertuples(index=False):
        q_use_quad = r.q_quad_ctrl_prim3 if r.is_primary_layer else r.q_quad_ctrl_all5
        q_use_lin = r.q_lin_ctrl_prim3 if r.is_primary_layer else r.q_lin_ctrl_all5
        q_use_sp = r.q_spearman_prim3 if r.is_primary_layer else r.q_spearman_all5
        q_use_jt = r.q_joint_ctrl_prim3 if r.is_primary_layer else r.q_joint_ctrl_all5
        if pd.notna(q_use_quad) and q_use_quad < 0.10 and r.interior_vertex and pd.notna(r.beta_quad_ctrl):
            fdr_shapes.append("inverted_u" if r.beta_quad_ctrl < 0 else "u_shape")
        elif (pd.notna(q_use_lin) and q_use_lin < 0.10) or (pd.notna(q_use_sp) and q_use_sp < 0.10) or (pd.notna(q_use_jt) and q_use_jt < 0.10):
            sign_ref = r.t_lin_ctrl_cl if pd.notna(r.t_lin_ctrl_cl) else r.spearman_r
            if pd.notna(sign_ref):
                fdr_shapes.append("monotone_inc" if sign_ref > 0 else "monotone_dec")
            else:
                fdr_shapes.append("null")
        else:
            fdr_shapes.append("null")
    res_df["fdr_shape_q10"] = fdr_shapes

    # Propagate q-values back into detail_tree
    for r in res_df.itertuples(index=False):
        cell = detail_tree[r.strategy][r.layer]["indicators"][r.indicator]
        cell["fdr"] = {
            "q_spearman_prim3": sf(r.q_spearman_prim3, 5),
            "q_lin_ctrl_prim3": sf(r.q_lin_ctrl_prim3, 5),
            "q_quad_ctrl_prim3": sf(r.q_quad_ctrl_prim3, 5),
            "q_joint_ctrl_prim3": sf(r.q_joint_ctrl_prim3, 5),
            "q_date_coll_prim3": sf(r.q_date_coll_prim3, 5),
            "q_best_prim3": sf(r.q_best_prim3, 5),
            "q_best_all5": sf(r.q_best_all5, 5),
            "fdr_shape_q10": r.fdr_shape_q10,
        }

    return detail_tree, res_df


def run_horse_race_ols(sub: pd.DataFrame, dep_col: str = "net_ret") -> dict:
    """Multivariate OLS horse-race with HC3 & date-clustered SEs + Leave-One-Out delta R^2."""
    n = len(sub)
    if n < 25:
        return {"n": int(n), "sample_warning": "N<25_SKIP_MULTIVAR"}

    w = sub.copy()
    w["is_kpl_na"] = w["kpl_plate_switch_ratio"].isna().astype(float)
    w["kpl_plate_switch_ratio"] = w["kpl_plate_switch_ratio"].fillna(w["kpl_plate_switch_ratio"].median() if w["kpl_plate_switch_ratio"].notna().any() else 0.5)
    w["log_cool_zt_filled"] = w["log_cool_zt"].fillna(w["log_cool_zt"].median() if w["log_cool_zt"].notna().any() else 4.0)

    cov_specs = [
        ("A_waves_3y", "waves_3y_g15"),
        ("B_zt_cnt_3y", "zt_cnt_3y"),
        ("C_comm_1y_pct", "comm_posts_1y_pct"),
        ("D_dd_1y_high", "dd_from_1y_high"),
        ("D_trap_3y", "trap_waves_3y"),
        ("D_turn_1y", "cum_turnover_1y"),
        ("E_switch_ratio", "kpl_plate_switch_ratio"),
        ("E_uniq_plates_5y", "kpl_unique_plates_5y"),
        ("F_log_cool_zt", "log_cool_zt_filled"),
        ("F_is_never_zt", "is_never_zt"),
        ("S_v20_score", "v20_score"),
    ]

    # Build standardized design matrix; drop zero-variance or collinear columns cleanly
    y = w[dep_col].to_numpy(float)
    valid_y = np.isfinite(y)
    w, y = w[valid_y].copy(), y[valid_y]
    cl = w["buy_date"].to_numpy()
    if len(y) < 25:
        return {"n": int(len(y)), "sample_warning": "N<25_SKIP_MULTIVAR"}

    used_names = []
    cols_z = [np.ones(len(y))]
    for lbl, cname in cov_specs:
        v = w[cname].to_numpy(float)
        sd = float(np.nanstd(v))
        if sd > 1e-10 and np.all(np.isfinite(v)):
            zv = (v - np.mean(v)) / sd
            cand = np.column_stack(cols_z + [zv])
            if np.linalg.matrix_rank(cand) > len(cols_z):
                cols_z.append(zv)
                used_names.append(lbl)

    X = np.column_stack(cols_z)
    fit = _safe_ols(y, X, cl)
    if fit is None:
        return {"n": int(len(y)), "sample_warning": "RANK_OR_DOF_FAIL"}

    rh, rc = fit["r_hc3"], fit["r_cl"]
    full_r2 = float(rc.rsquared)
    adj_r2 = float(rc.rsquared_adj)

    # VIF & Leave-one-out delta R^2
    coef_table = []
    for idx_pos, k_idx in enumerate(fit["keep_cols"]):
        if k_idx == 0:
            continue
        name = used_names[k_idx - 1]
        X_drop = np.delete(X[:, fit["keep_cols"]], idx_pos, axis=1)
        r2_drop = float(sm.OLS(y, X_drop).fit().rsquared) if X_drop.shape[1] >= 1 else 0.0
        # VIF
        Xk_j = X[:, fit["keep_cols"]][:, idx_pos]
        try:
            r2_vif = float(sm.OLS(Xk_j, X_drop).fit().rsquared)
            vif = 1.0 / max(1.0 - r2_vif, 1e-4)
        except Exception:
            vif = None
        coef_table.append({
            "feature": name,
            "beta_std": sf(rc.params[idx_pos], 5),
            "t_hc3": sf(rh.tvalues[idx_pos], 3),
            "p_hc3": sf(rh.pvalues[idx_pos], 6),
            "t_cluster_dt": sf(rc.tvalues[idx_pos], 3),
            "p_cluster_dt": sf(rc.pvalues[idx_pos], 6),
            "delta_r2_pct": sf((full_r2 - r2_drop) * 100.0, 3),
            "vif": sf(vif, 2),
        })

    coef_table.sort(key=lambda d: abs(d["t_cluster_dt"] or 0.0), reverse=True)
    return {
        "n": int(len(y)),
        "n_date_clusters": int(fit["n_clusters"]),
        "dep_col": dep_col,
        "r2_pct": sf(full_r2 * 100.0, 2),
        "adj_r2_pct": sf(adj_r2 * 100.0, 2),
        "sample_warning": "LOW_CLUSTERS" if fit["n_clusters"] < 30 else "OK",
        "coefs": coef_table,
    }


def run_2x2_interactions(sub: pd.DataFrame, strat: str, sh300: dict, all_sh_dts: list, prev_td: dict) -> dict:
    """Double-sort cross tables dissecting Old-Hot x Overhang / Cooling / Theme-Purity."""
    if len(sub) < 30:
        return {"n": int(len(sub)), "sample_warning": "N<30"}

    w = sub.copy()
    w["hot_freq"] = np.where(w["waves_3y_g15"] >= 6, "HiFreq(>=6w)", "LoFreq(<=5w)")
    # Strategy-adapted drawdown threshold (pry never exceeds -20%, so split pry at -48%)
    dd_thr = -0.48 if strat == "pry" else -0.20
    dd_lbl = f">{int(dd_thr*100)}%(NearHi)" if strat != "pry" else ">-48%(MidDD)"
    dd_lo_lbl = f"<={int(dd_thr*100)}%(DeepTrap)"
    w["trap_depth"] = np.where(w["dd_from_1y_high"] > dd_thr, dd_lbl, dd_lo_lbl)

    w["cool_3bin"] = np.where(
        w["cool_bin_zt"] == "<=30d", "Hot(<=30d)",
        np.where(w["cool_bin_zt"].isin(["31~90d", "91~180d"]), "Mid(31~180d)", "Cold(>180d/never)")
    )
    w["purity_bin"] = np.where(
        w["kpl_plate_switch_ratio"].isna(), "NA",
        np.where(w["kpl_plate_switch_ratio"] <= 0.25, "Pure(<=0.25)",
                 np.where(w["kpl_plate_switch_ratio"] < 0.75, "Mix(0.25~0.75)", "Switch(>=0.75)"))
    )

    def _cross_tbl(rcol: str, ccol: str, order_r: list[str], order_c: list[str]) -> dict:
        cells = []
        for rv in order_r:
            for cv in order_c:
                cell = w[(w[rcol] == rv) & (w[ccol] == cv)]
                if len(cell) == 0:
                    cells.append({"row": rv, "col": cv, "n": 0})
                else:
                    m = eval_slice_metrics(cell, sh300, all_sh_dts, prev_td)
                    m["row"], m["col"] = rv, cv
                    cells.append(m)
        # Formal interaction test on binary/numeric contrast inside HighFreq subset
        hi_sub = w[w[rcol] == order_r[-1]]
        contrast = None
        if len(hi_sub) >= 20:
            g1 = hi_sub[hi_sub[ccol] == order_c[0]]
            g2 = hi_sub[hi_sub[ccol] == order_c[-1]]
            if len(g1) >= 5 and len(g2) >= 5:
                # Date-clustered regression of net_ret ~ I(col == order_c[-1]) within HiFreq
                x_dum = (hi_sub[ccol].isin([order_c[-1]])).to_numpy(float)
                sub_2 = hi_sub[hi_sub[ccol].isin([order_c[0], order_c[-1]])]
                if len(sub_2) >= 10:
                    xd = (sub_2[ccol] == order_c[-1]).to_numpy(float)
                    fit_c = _safe_ols(sub_2["net_ret"].to_numpy(float), np.column_stack([np.ones(len(sub_2)), xd]), sub_2["buy_date"].to_numpy())
                    t_c = sf(fit_c["r_cl"].tvalues[1], 3) if fit_c and 1 in fit_c["keep_cols"] else None
                    p_c = sf(fit_c["r_cl"].pvalues[1], 5) if fit_c and 1 in fit_c["keep_cols"] else None
                    contrast = {
                        "within_group": order_r[-1],
                        "compare": f"{order_c[-1]} minus {order_c[0]}",
                        "n_a": int(len(g1)), "n_b": int(len(g2)),
                        "diff_mean_pp": sf((g2["net_ret"].mean() - g1["net_ret"].mean()) * 100.0, 2),
                        "diff_ex_csi_pp": sf((g2["excess_trade_ret"].mean() - g1["excess_trade_ret"].mean()) * 100.0, 2),
                        "t_cluster_dt": t_c, "p_cluster_dt": p_c,
                    }
        return {"cells": cells, "hifreq_contrast": contrast}

    return {
        "freq_x_trap": _cross_tbl("hot_freq", "trap_depth", ["LoFreq(<=5w)", "HiFreq(>=6w)"], [dd_lo_lbl, dd_lbl]),
        "freq_x_cool": _cross_tbl("hot_freq", "cool_3bin", ["LoFreq(<=5w)", "HiFreq(>=6w)"], ["Hot(<=30d)", "Mid(31~180d)", "Cold(>180d/never)"]),
        "freq_x_purity": _cross_tbl("hot_freq", "purity_bin", ["LoFreq(<=5w)", "HiFreq(>=6w)"], ["Pure(<=0.25)", "Mix(0.25~0.75)", "Switch(>=0.75)"]),
        "cool_x_trap": _cross_tbl("cool_3bin", "trap_depth", ["Hot(<=30d)", "Mid(31~180d)", "Cold(>180d/never)"], [dd_lo_lbl, dd_lbl]),
    }


def run_module2(df: pd.DataFrame, sh300: dict, all_sh_dts: list, prev_td: dict) -> dict:
    """Module 2: Horse-race OLS decomposition + 2x2 interaction tables across all 6 strategies (+ pooled)."""
    print("[Module 2] Running multivariate Horse-Race & 2x2 Mechanism Decomposition...")
    out = {}
    for strat in MAIN_STRATS:
        out[strat] = {}
        for layer in ["L1_all_cand", "L2_pass_off", "L3_edge_straddle"]:
            sub = df[get_layer_mask(df, strat, layer)].copy()
            out[strat][layer] = {
                "ols_net_ret": run_horse_race_ols(sub, "net_ret"),
                "ols_excess_csi300": run_horse_race_ols(sub, "excess_trade_ret"),
                "interactions": run_2x2_interactions(sub, strat, sh300, all_sh_dts, prev_td),
            }

    # Pooled 6-strategy horse-race with strategy fixed effects
    out["POOLED_6STRAT"] = {}
    for layer in ["L1_all_cand", "L2_pass_off", "L3_edge_straddle"]:
        parts = [df[get_layer_mask(df, s, layer)].copy() for s in MAIN_STRATS]
        p_df = pd.concat(parts, ignore_index=True)
        # Demean net_ret & v20_score within strategy for clean pooled horse-race (strategy FE)
        p_df["net_ret_fe"] = p_df["net_ret"] - p_df.groupby("strategy")["net_ret"].transform("mean")
        p_df["ex_ret_fe"] = p_df["excess_trade_ret"] - p_df.groupby("strategy")["excess_trade_ret"].transform("mean")
        p_df["v20_score"] = p_df.groupby("strategy")["v20_score"].transform(
            lambda s: (s - s.mean()) / max(s.std(), 1e-6)
        )
        out["POOLED_6STRAT"][layer] = {
            "ols_net_ret_strat_fe": run_horse_race_ols(p_df, "net_ret_fe"),
            "ols_excess_csi300_strat_fe": run_horse_race_ols(p_df, "ex_ret_fe"),
        }
    return out


def run_module3(df: pd.DataFrame) -> dict:
    """Module 3: Market Era (21-23 Bear vs 24-26 Active), IS vs OOS, Y2026 & Year-by-Year stability."""
    print("[Module 3] Running Era / IS-OOS / Year-by-Year time stability audit...")
    core_cols = [
        ("waves_3y_g15", "num"),
        ("zt_cnt_3y", "num"),
        ("comm_posts_1y_pct", "num"),
        ("dd_from_1y_high", "num"),
        ("trap_waves_3y", "num"),
        ("cum_turnover_1y", "num"),
        ("kpl_plate_switch_ratio", "num"),
        ("cool_days_since_last_zt", "cool"),
    ]

    def _slice_stats(s_df: pd.DataFrame, cname: str, kind: str) -> dict:
        v = s_df[s_df[cname].notna()].copy()
        if len(v) < 10:
            return {"n": int(len(v)), "spearman_r": None, "spearman_p": None, "hi_minus_lo_pp": None}
        x = np.log1p(v[cname].to_numpy(float)) if kind == "cool" else v[cname].to_numpy(float)
        y = v["net_ret"].to_numpy(float)
        if np.std(x) < 1e-10 or np.std(y) < 1e-10:
            return {"n": int(len(v)), "spearman_r": None, "spearman_p": None, "hi_minus_lo_pp": None}
        r, p = stats.spearmanr(x, y)
        med = float(np.median(x))
        hi, lo = y[x > med], y[x <= med]
        if len(hi) == 0 or len(lo) == 0:
            hi, lo = y[x >= med], y[x < med]
        diff_pp = sf((np.mean(hi) - np.mean(lo)) * 100.0, 2) if (len(hi) > 0 and len(lo) > 0) else None
        return {
            "n": int(len(v)),
            "spearman_r": sf(r, 4),
            "spearman_p": sf(p, 5),
            "hi_minus_lo_pp": diff_pp,
            "mean_ret_pct": sf(np.mean(y) * 100.0, 2),
        }

    out = {}
    for strat in MAIN_STRATS:
        out[strat] = {}
        for layer in ["L1_all_cand", "L2_pass_off", "L3_edge_straddle"]:
            sub = df[get_layer_mask(df, strat, layer)].copy()
            if len(sub) < 20:
                out[strat][layer] = {"n": int(len(sub)), "skipped": "N<20"}
                continue
            ind_time = {}
            for cname, kind in core_cols:
                bear = sub[sub["era_tag"] == "2021_2023_bear"]
                act = sub[sub["era_tag"] == "2024_2026_active"]
                is_d = sub[sub["is_oos_split"] == "IS"]
                oos_d = sub[sub["is_oos_split"] == "OOS"]
                y26 = sub[sub["year"] == 2026]

                s_bear = _slice_stats(bear, cname, kind)
                s_act = _slice_stats(act, cname, kind)
                s_is = _slice_stats(is_d, cname, kind)
                s_oos = _slice_stats(oos_d, cname, kind)
                s_26 = _slice_stats(y26, cname, kind)

                yearly = {}
                for yr in sorted(sub["year"].unique()):
                    yearly[str(int(yr))] = _slice_stats(sub[sub["year"] == yr], cname, kind)

                # Interaction p-value: x * I(2024_2026_active) and x * I(OOS)
                def _inter_p(flag_col: str, flag_val: str) -> tuple[float | None, float | None]:
                    vv = sub[sub[cname].notna()].copy()
                    if len(vv) < 25:
                        return None, None
                    xv = np.log1p(vv[cname].to_numpy(float)) if kind == "cool" else vv[cname].to_numpy(float)
                    if np.std(xv) < 1e-10:
                        return None, None
                    xz = (xv - np.mean(xv)) / np.std(xv)
                    d_f = (vv[flag_col] == flag_val).to_numpy(float)
                    if np.std(d_f) < 1e-10:
                        return None, None
                    fit_i = _safe_ols(vv["net_ret"].to_numpy(float), np.column_stack([np.ones(len(vv)), xz, d_f, xz * d_f]), vv["buy_date"].to_numpy())
                    if fit_i and 3 in fit_i["keep_cols"]:
                        pos = fit_i["keep_cols"].index(3)
                        return sf(fit_i["r_cl"].tvalues[pos], 3), sf(fit_i["r_cl"].pvalues[pos], 5)
                    return None, None

                t_era_int, p_era_int = _inter_p("era_tag", "2024_2026_active")
                t_oos_int, p_oos_int = _inter_p("is_oos_split", "OOS")

                # Consistency flag
                r_b, r_a = s_bear.get("spearman_r"), s_act.get("spearman_r")
                r_i, r_o = s_is.get("spearman_r"), s_oos.get("spearman_r")
                era_same = (r_b is not None and r_a is not None and (r_b * r_a > 0))
                oos_same = (r_i is not None and r_o is not None and (r_i * r_o > 0))

                ind_time[cname] = {
                    "bear_21_23": s_bear,
                    "active_24_26": s_act,
                    "IS_21_24": s_is,
                    "OOS_25_26": s_oos,
                    "Y2026": s_26,
                    "yearly": yearly,
                    "era_interaction_t_cl": t_era_int,
                    "era_interaction_p_cl": p_era_int,
                    "oos_interaction_t_cl": t_oos_int,
                    "oos_interaction_p_cl": p_oos_int,
                    "era_same_sign": bool(era_same),
                    "oos_same_sign": bool(oos_same),
                }
            out[strat][layer] = ind_time
    return out


def run_module4_temp5b(df: pd.DataFrame, sh300: dict, all_sh_dts: list, prev_td: dict, rng: np.random.Generator) -> dict:
    """Module 4: Independent <<临时策略：五板>> (temp5b) appendix strictly >= 2026-07-01."""
    print("[Module 4] Running independent <<临时策略：五板>> (temp5b, strictly >= 2026-07-01) audit...")
    t5_raw = df[df["strategy"] == "temp5b"].copy()
    assert str(t5_raw["buy_date"].min()) >= "2026-07-01", f"temp5b leakage before 2026-07-01: {t5_raw['buy_date'].min()}"
    assert str(t5_raw["sig_date"].min()) >= "2026-07-01", f"temp5b sig_date leakage: {t5_raw['sig_date'].min()}"

    t5_res = t5_raw[t5_raw["sim_ok"].astype(bool) & t5_raw["net_ret"].notna()].copy()
    t5_pass_all = t5_raw[t5_raw["is_pass_official"].astype(bool)].copy()
    t5_unselected = t5_raw[~t5_raw["is_pass_official"].astype(bool)].copy()
    t5_immature = t5_pass_all[~t5_pass_all["sim_ok"].astype(bool)].copy()

    base_met = eval_slice_metrics(t5_res, sh300, all_sh_dts, prev_td)
    base_met["total_pool_rows"] = int(len(t5_raw))
    base_met["official_selected_rows"] = int(len(t5_pass_all))
    base_met["resolved_trades"] = int(len(t5_res))
    base_met["immature_unfinished"] = int(len(t5_immature))
    base_met["unselected_open_gt5_5"] = int(len(t5_unselected))
    base_met["sample_warning"] = "SMALL_SAMPLE_N34_EXPLORATORY_ONLY"

    # Profile comparison: temp5b vs high vs 3to4, plus winners vs losers, selected vs unselected
    prof_cols = [
        "waves_3y_g15", "active_years_5y", "zt_cnt_3y", "zt_cnt_1y", "max_streak_5y",
        "comm_posts_1y_pct", "comm_posts_3y_pct", "cum_turnover_1y", "trap_waves_3y",
        "dd_from_1y_high", "kpl_unique_plates_5y", "kpl_plate_switch_ratio", "cool_days_since_last_zt",
    ]
    t5_win = t5_res[t5_res["net_ret"] > 0]
    t5_los = t5_res[t5_res["net_ret"] <= 0]
    high_s = df[(df["strategy"] == "high") & df["sim_ok"]]
    s34_s = df[(df["strategy"] == "3to4") & df["sim_ok"]]

    profile_comp = {}
    for pc in prof_cols:
        profile_comp[pc] = {
            "temp5b_resolved_med": sf(t5_res[pc].median(), 3),
            "temp5b_resolved_mean": sf(t5_res[pc].mean(), 3),
            "temp5b_winners_med": sf(t5_win[pc].median(), 3),
            "temp5b_losers_med": sf(t5_los[pc].median(), 3),
            "temp5b_selected36_med": sf(t5_pass_all[pc].median(), 3),
            "temp5b_unselected9_med": sf(t5_unselected[pc].median(), 3),
            "high_62_med": sf(high_s[pc].median(), 3),
            "3to4_318_med": sf(s34_s[pc].median(), 3),
        }

    # Univariate Spearman + 2,000x perm + quadratic + score-controlled OLS + median binary split
    uni_tests = []
    for spec in INDICATOR_SPECS:
        col, kind = spec["col"], spec["kind"]
        v = t5_res[t5_res[col].notna()].copy()
        x = np.log1p(v[col].to_numpy(float)) if kind == "cool" else v[col].to_numpy(float)
        cont = analyze_continuous_nonlinear(v, x, rng)

        # Balanced median split (with explicit N<30 warning)
        if len(v) >= 10 and np.std(x) > 1e-10:
            med = float(np.median(x))
            hi = v[x > med]
            lo = v[x <= med]
            if len(hi) == 0 or len(lo) == 0:
                hi, lo = v[x >= med], v[x < med]
            hi_m = eval_slice_metrics(hi, sh300, all_sh_dts, prev_td)
            lo_m = eval_slice_metrics(lo, sh300, all_sh_dts, prev_td)
        else:
            hi_m, lo_m = {"n": 0}, {"n": 0}

        # Cool bin breakdown for Dim F
        bin_rows = []
        if kind == "cool":
            for b in COOL_ORDER:
                sub_b = t5_res[t5_res[spec["bin_col"]] == b]
                if len(sub_b) > 0:
                    bm = eval_slice_metrics(sub_b, sh300, all_sh_dts, prev_td)
                    bm["bin"] = b
                    bin_rows.append(bm)

        uni_tests.append({
            "dim": spec["dim"],
            "indicator": col,
            "sample_warning": "N<30_PER_GROUP_SMALL_SAMPLE",
            "n_valid": int(len(v)),
            "spearman_r": cont.get("spearman_r"),
            "p_perm_spearman": cont.get("p_perm_spearman"),
            "partial_spearman_r_ctrl": cont.get("partial_spearman_r_ctrl"),
            "t_lin_ctrl_cl": cont.get("t_lin_ctrl_cl"),
            "p_lin_ctrl_cl": cont.get("p_lin_ctrl_cl"),
            "t_quad_ctrl_cl": cont.get("t_quad_ctrl_cl"),
            "p_quad_ctrl_cl": cont.get("p_quad_ctrl_cl"),
            "p_perm_quad": cont.get("p_perm_quad"),
            "hi_split": hi_m,
            "lo_split": lo_m,
            "cool_bins": bin_rows if bin_rows else None,
        })

    # BH-FDR within temp5b 18 exploratory indicators
    sp_p = np.array([u["p_perm_spearman"] if u["p_perm_spearman"] is not None else np.nan for u in uni_tests])
    ql_p = np.array([u["p_lin_ctrl_cl"] if u["p_lin_ctrl_cl"] is not None else np.nan for u in uni_tests])
    qq_p = np.array([u["p_quad_ctrl_cl"] if u["p_quad_ctrl_cl"] is not None else np.nan for u in uni_tests])
    q_sp = bh_fdr(sp_p)
    q_ql = bh_fdr(ql_p)
    q_qq = bh_fdr(qq_p)
    for i, u in enumerate(uni_tests):
        u["q_spearman_temp5b"] = sf(q_sp[i], 5)
        u["q_lin_ctrl_temp5b"] = sf(q_ql[i], 5)
        u["q_quad_ctrl_temp5b"] = sf(q_qq[i], 5)

    # Full case reconciliation table (resolved top winners, worst losers, and immature)
    srt_res = t5_res.sort_values("net_ret", ascending=False)
    def _pack_cases(sub_c: pd.DataFrame) -> list[dict]:
        rows = []
        for r in sub_c.itertuples(index=False):
            rows.append({
                "code": r.code, "name": r.name, "sig_date": r.sig_date, "buy_date": r.buy_date,
                "exit_date": r.exit_date, "net_ret_pct": sf(r.net_ret * 100.0, 2) if pd.notna(r.net_ret) else None,
                "selected_height": int(r.base_score),
                "waves_3y_g15": int(r.waves_3y_g15), "zt_cnt_3y": int(r.zt_cnt_3y),
                "comm_posts_1y_pct": sf(r.comm_posts_1y_pct, 3),
                "dd_from_1y_high_pct": sf(r.dd_from_1y_high * 100.0, 2),
                "trap_waves_3y": int(r.trap_waves_3y),
                "kpl_plate_switch_ratio": sf(r.kpl_plate_switch_ratio, 3),
                "cool_days_since_last_zt": sf(r.cool_days_since_last_zt, 0),
                "cool_bin_zt": r.cool_bin_zt,
            })
        return rows

    return {
        "strict_date_window": {"min_buy_date": str(t5_raw["buy_date"].min()), "max_buy_date": str(t5_raw["buy_date"].max())},
        "baseline_summary": base_met,
        "profile_comparison": profile_comp,
        "exploratory_18_indicators": uni_tests,
        "typical_case_reconciliation": {
            "top_8_winners": _pack_cases(srt_res.head(8)),
            "worst_8_losers": _pack_cases(srt_res.tail(8).iloc[::-1]),
            "immature_unfinished": _pack_cases(t5_immature),
            "unselected_open_gt5_5": _pack_cases(t5_unselected),
        },
    }


def main():
    t0 = time.time()
    rng = np.random.default_rng(RNG_SEED)
    df, sh300, all_sh_dts, prev_td = load_data_and_benchmark()
    print(f"[RD030 Wave 2A] Loaded {len(df):,} rows across {df['strategy'].nunique()} pools.")

    m1_tree, fdr_df = run_module1(df, sh300, all_sh_dts, prev_td, rng)
    m2_res = run_module2(df, sh300, all_sh_dts, prev_td)
    m3_res = run_module3(df)
    m4_res = run_module4_temp5b(df, sh300, all_sh_dts, prev_td, rng)

    # Summarize FDR survivors vs raw false positives
    prim_df = fdr_df[fdr_df["is_primary_layer"]].copy()
    raw_hits_prim = prim_df[
        (prim_df["p_perm_spearman"] < 0.05)
        | (prim_df["p_quad_ctrl_cl"] < 0.05)
        | (prim_df["p_lin_ctrl_cl"] < 0.05)
        | (prim_df["p_joint_ctrl_cl"] < 0.05)
    ]
    surv_q05 = prim_df[prim_df["q_best_prim3"] < 0.05].sort_values("q_best_prim3")
    surv_q10 = prim_df[prim_df["q_best_prim3"] < 0.10].sort_values("q_best_prim3")
    false_pos = raw_hits_prim[raw_hits_prim["q_best_prim3"] >= 0.10].sort_values("q_best_prim3")

    # Sort full CSV by (is_primary_layer desc, q_best_prim3 asc, q_best_all5 asc)
    fdr_df_sorted = fdr_df.sort_values(
        ["is_primary_layer", "q_best_prim3", "q_best_all5", "strategy", "layer"],
        ascending=[False, True, True, True, True],
        na_position="last",
    )
    fdr_df_sorted.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    summary_fdr = {
        "primary_3layers_total_tests": int(len(prim_df)),
        "all_5layers_total_tests": int(len(fdr_df)),
        "raw_p05_hits_in_prim3": int(len(raw_hits_prim)),
        "fdr_survivors_q05_in_prim3": int(len(surv_q05)),
        "fdr_survivors_q10_in_prim3": int(len(surv_q10)),
        "raw_p05_knocked_out_false_positives": int(len(false_pos)),
        "survivors_q10_list": surv_q10[[
            "strategy", "layer", "dim", "indicator", "n_valid", "n_date_clusters",
            "sample_warning", "spearman_r", "p_perm_spearman", "date_collapsed_r", "date_collapsed_p",
            "t_lin_ctrl_cl", "t_quad_ctrl_cl", "p_joint_ctrl_cl",
            "q_spearman_prim3", "q_lin_ctrl_prim3", "q_quad_ctrl_prim3", "q_joint_ctrl_prim3",
            "q_date_coll_prim3", "q_best_prim3", "fdr_shape_q10",
        ]].to_dict(orient="records"),
        "all5layers_survivors_q10_list": fdr_df[fdr_df["q_best_all5"] < 0.10].sort_values("q_best_all5")[[
            "strategy", "layer", "dim", "indicator", "n_valid", "n_date_clusters",
            "sample_warning", "spearman_r", "p_perm_spearman", "date_collapsed_r", "date_collapsed_p",
            "t_lin_ctrl_cl", "t_quad_ctrl_cl", "q_best_all5", "fdr_shape_q10",
        ]].to_dict(orient="records"),
        "knocked_out_false_positives_top30": false_pos.head(30)[[
            "strategy", "layer", "dim", "indicator", "n_valid", "spearman_r",
            "p_perm_spearman", "p_lin_ctrl_cl", "p_quad_ctrl_cl", "q_best_prim3", "raw_shape",
        ]].to_dict(orient="records"),
    }

    payload = {
        "meta": {
            "task": "RD030 Wave 2A: 6 V20.0 Strategies (+ temp5b) x 3+2 Pool Layers x 6-Dim Old-Hot Nonlinear & Time Audit",
            "input_parquet": INPUT_PQ,
            "n_perm": N_PERM,
            "rng_seed": RNG_SEED,
            "elapsed_sec": round(time.time() - t0, 2),
        },
        "fdr_summary": summary_fdr,
        "module1_nonlinear_matrix": m1_tree,
        "module2_horse_race_and_interactions": m2_res,
        "module3_time_effects": m3_res,
        "module4_temp5b_appendix": m4_res,
    }
    def _clean_json(obj):
        if isinstance(obj, dict):
            return {k: _clean_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_clean_json(v) for v in obj]
        if isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        if isinstance(obj, (np.integer, int)):
            return int(obj)
        if isinstance(obj, (np.floating, float)):
            fv = float(obj)
            return None if (math.isnan(fv) or math.isinf(fv)) else fv
        if obj is pd.NA or pd.isna(obj) if not isinstance(obj, (str, bytes)) else False:
            return None
        return obj

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(_clean_json(payload), f, ensure_ascii=False, indent=2, allow_nan=False)

    print(
        f"[DONE in {time.time()-t0:.1f}s] Saved {OUT_JSON} & {OUT_CSV} | "
        f"prim3={len(prim_df)} tests, raw_p<0.05={len(raw_hits_prim)}, "
        f"BH-FDR q<0.05={len(surv_q05)}, q<0.10={len(surv_q10)}, knocked_out={len(false_pos)}"
    )


if __name__ == "__main__":
    main()
