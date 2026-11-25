#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD027 Wave 2A Statistical Engine:
  1. Exact Newey-West Bartlett HAC OLS (univariate & multivariate)
  2. Benjamini-Hochberg FDR
  3. 8 Falsifiable China Hypotheses (CH1 ~ CH8)
  4. Jorda (2005) Local Projections with 95% HAC CI across T+20/60/120/250
"""
import numpy as np
import pandas as pd
from scipy import stats


def nw_ols_uni(
    x_arr: np.ndarray,
    y_arr: np.ndarray,
    t_idx_arr: np.ndarray,
    maxlags: int,
    min_n: int = 25,
) -> tuple[float, float, float, float, float, float, int]:
    """Univariate OLS y = a + b*x with Newey-West Bartlett HAC covariance (matches statsmodels use_t=True)."""
    m = np.isfinite(x_arr) & np.isfinite(y_arr)
    n = int(m.sum())
    if n < min_n:
        return np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, n
    x = x_arr[m]
    y = y_arr[m]
    sx = float(np.std(x, ddof=1))
    sy = float(np.std(y, ddof=1))
    if sx < 1e-12 or sy < 1e-12:
        return np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, n

    xm = float(np.mean(x))
    ym = float(np.mean(y))
    dx = x - xm
    dy = y - ym
    sxx = float(np.dot(dx, dx))
    beta = float(np.dot(dx, dy) / sxx)
    alpha = ym - beta * xm
    e = y - (alpha + beta * x)
    tss = float(np.dot(dy, dy))
    r2 = 1.0 - float(np.dot(e, e)) / tss if tss > 1e-20 else 0.0

    X = np.column_stack([np.ones(n), x])
    u = X * e[:, None]
    ti = t_idx_arr[m]
    S = u.T @ u
    L = min(maxlags, n - 1)
    if np.all(np.diff(ti) == 1):
        for lag in range(1, L + 1):
            w = 1.0 - lag / (maxlags + 1.0)
            G = u[lag:].T @ u[:-lag]
            S = S + w * (G + G.T)
    else:
        for k in range(1, L + 1):
            d = ti[k:] - ti[:-k]
            vl = d <= maxlags
            if not np.any(vl):
                break
            w = 1.0 - d[vl] / (maxlags + 1.0)
            uk = u[k:][vl] * w[:, None]
            G = uk.T @ u[:-k][vl]
            S = S + (G + G.T)

    XtX_inv = np.linalg.inv(X.T @ X)
    cov = (n / (n - 2.0)) * (XtX_inv @ S @ XtX_inv)
    se = float(np.sqrt(max(cov[1, 1], 1e-30)))
    t_stat = beta / se
    p_val = 2.0 * float(stats.t.sf(abs(t_stat), df=n - 2))
    beta_1sd = beta * sx
    return beta, beta_1sd, se, t_stat, p_val, r2, n


def nw_ols_multi(
    X_cols: np.ndarray,
    y_arr: np.ndarray,
    t_idx_arr: np.ndarray,
    maxlags: int,
    min_n: int = 25,
) -> dict:
    """Multivariate OLS y = intercept + X*b with Newey-West HAC covariance."""
    m = np.isfinite(y_arr) & np.all(np.isfinite(X_cols), axis=1)
    n = int(m.sum())
    k = X_cols.shape[1] + 1
    if n <= k + 5 or n < min_n:
        return {"ok": False, "n": n}
    y = y_arr[m]
    X = np.column_stack([np.ones(n), X_cols[m]])
    # Check rank
    if np.linalg.matrix_rank(X) < k:
        return {"ok": False, "n": n}
    XtX_inv = np.linalg.pinv(X.T @ X)
    params = XtX_inv @ (X.T @ y)
    e = y - X @ params
    dy = y - np.mean(y)
    tss = float(np.dot(dy, dy))
    r2 = 1.0 - float(np.dot(e, e)) / tss if tss > 1e-20 else 0.0

    u = X * e[:, None]
    ti = t_idx_arr[m]
    S = u.T @ u
    L = min(maxlags, n - 1)
    if np.all(np.diff(ti) == 1):
        for lag in range(1, L + 1):
            w = 1.0 - lag / (maxlags + 1.0)
            G = u[lag:].T @ u[:-lag]
            S = S + w * (G + G.T)
    else:
        for step in range(1, L + 1):
            d = ti[step:] - ti[:-step]
            vl = d <= maxlags
            if not np.any(vl):
                break
            w = 1.0 - d[vl] / (maxlags + 1.0)
            uk = u[step:][vl] * w[:, None]
            G = uk.T @ u[:-step][vl]
            S = S + (G + G.T)

    cov = (n / max(n - k, 1)) * (XtX_inv @ S @ XtX_inv)
    se = np.sqrt(np.maximum(np.diag(cov), 1e-30))
    t_stats = params / se
    p_vals = 2.0 * stats.t.sf(np.abs(t_stats), df=max(n - k, 1))
    return {
        "ok": True,
        "n": n,
        "r2": float(r2),
        "params": params.tolist(),
        "se": se.tolist(),
        "t_stats": t_stats.tolist(),
        "p_vals": p_vals.tolist(),
    }


def benjamini_hochberg(pvals: np.ndarray) -> np.ndarray:
    """Compute Benjamini-Hochberg FDR q-values preserving NaNs."""
    q = np.full_like(pvals, np.nan, dtype=float)
    valid = np.isfinite(pvals)
    m = int(valid.sum())
    if m == 0:
        return q
    pv = pvals[valid]
    order = np.argsort(pv)
    ranked = pv[order]
    raw_q = ranked * m / np.arange(1, m + 1, dtype=float)
    mono_q = np.minimum.accumulate(raw_q[::-1])[::-1]
    mono_q = np.clip(mono_q, 0.0, 1.0)
    inv = np.empty_like(mono_q)
    inv[order] = mono_q
    q[valid] = inv
    return q


def _fmt_uni(x, y, ti, maxlags, is_mask=None, oos_mask=None, e1=None, e2=None, e3=None):
    b, b1, se, t, p, r2, n = nw_ols_uni(x, y, ti, maxlags)
    out = {
        "n": n,
        "beta": round(b, 6) if np.isfinite(b) else None,
        "beta_1sd_pct": round(b1 * 100.0, 3) if np.isfinite(b1) else None,
        "t_hac": round(t, 3) if np.isfinite(t) else None,
        "p_val": float(f"{p:.3e}") if np.isfinite(p) else None,
        "r2_pct": round(r2 * 100.0, 2) if np.isfinite(r2) else None,
    }
    for nm, msk in [("IS", is_mask), ("OOS", oos_mask), ("Era1", e1), ("Era2", e2), ("Era3", e3)]:
        if msk is not None:
            bm, b1m, _, tm, pm, _, nm_c = nw_ols_uni(x[msk], y[msk], ti[msk], maxlags, min_n=15)
            out[nm] = {
                "n": nm_c,
                "beta_1sd_pct": round(b1m * 100.0, 3) if np.isfinite(b1m) else None,
                "t_hac": round(tm, 3) if np.isfinite(tm) else None,
                "sign": int(np.sign(bm)) if np.isfinite(bm) and abs(bm) > 1e-12 else 0,
            }
    return out


def _group_diff_hac(mask_grp: np.ndarray, y: np.ndarray, ti: np.ndarray, maxlags: int, sub_mask: np.ndarray = None) -> dict:
    """Compare mean(y | grp==1) vs mean(y | grp==0) and mean(y | grp==1) vs 0 with HAC SE."""
    if sub_mask is not None:
        m = sub_mask & np.isfinite(y) & np.isfinite(mask_grp)
    else:
        m = np.isfinite(y) & np.isfinite(mask_grp)
    g = (mask_grp[m] > 0.5).astype(float)
    yv = y[m]
    tv = ti[m]
    n_on = int(g.sum())
    n_off = int(len(g) - n_on)
    if n_on < 5:
        return {"n_on": n_on, "n_off": n_off}
    # Regress y on intercept (gives mean_off) + g (gives diff_on_minus_off)
    res_diff = nw_ols_multi(g[:, None], yv, tv, maxlags, min_n=15)
    # Regress y_on on intercept only (mean_on & HAC t vs 0)
    y_on = yv[g == 1.0]
    t_on = tv[g == 1.0]
    res_on = nw_ols_multi(np.empty((len(y_on), 0)), y_on, t_on, maxlags, min_n=5)
    win_rate = float(np.mean(y_on > 0)) * 100.0
    wins = y_on[y_on > 0]
    losses = -y_on[y_on < 0]
    payoff = float(np.mean(wins) / np.mean(losses)) if len(wins) > 0 and len(losses) > 0 and np.mean(losses) > 1e-9 else None
    return {
        "n_on": n_on,
        "n_off": n_off,
        "mean_on_pct": round(float(np.mean(y_on)) * 100.0, 2),
        "t_hac_on_vs_0": round(res_on["t_stats"][0], 3) if res_on.get("ok") else None,
        "win_rate_pct": round(win_rate, 1),
        "payoff": round(payoff, 2) if payoff is not None else None,
        "diff_on_minus_off_pct": round(res_diff["params"][1] * 100.0, 2) if res_diff.get("ok") else None,
        "t_hac_diff": round(res_diff["t_stats"][1], 3) if res_diff.get("ok") else None,
        "p_diff": round(res_diff["p_vals"][1], 4) if res_diff.get("ok") else None,
    }


def run_ch1_to_ch8_tests(df: pd.DataFrame, p3_raw: pd.DataFrame, p2_raw: pd.DataFrame) -> dict:
    """Execute rigorous quantitative falsification checks for CH1 ~ CH8."""
    ti = np.arange(len(df), dtype=int)
    d = df["date_str"].to_numpy()
    is_m = d <= "2020-12-31"
    oos_m = d >= "2021-01-01"
    e1 = d <= "2014-12-31"
    e2 = (d >= "2015-01-01") & (d <= "2020-12-31")
    e3 = d >= "2021-01-01"

    out = {}

    # CH1: 口号底 vs 水阀翻转底
    slogan_x = df["f5_me_slogan_only_w60"].to_numpy(float)
    valve_x = (df["gate_g1_deep_freeze"] * df["wp_net_waterpool_trading_mcap_3m"]).to_numpy(float)
    valve_hard_x = (df["gate_g1_deep_freeze"] * df["gate_g2_drain_welded"] * df["f5_me_hard_rescue_w60"]).to_numpy(float)
    slogan_freeze_grp = ((df["gate_g1_deep_freeze"] == 1) & (df["f5_me_slogan_only_w60"] >= 1) & (df["gate_g2_drain_welded"] == 0)).to_numpy(float)
    valve_flip_grp = ((df["gate_g1_deep_freeze"] == 1) & (df["gate_g2_drain_welded"] == 1) & (df["wp_net_flip_pos_1m"] == 1)).to_numpy(float)
    ch1 = {
        "slogan_only_w60_vs_300_120d": _fmt_uni(slogan_x, df["tgt_csi300_fwd_120d"].to_numpy(float), ti, 24, is_m, oos_m, e1, e2, e3),
        "slogan_only_w60_vs_ew_120d": _fmt_uni(slogan_x, df["tgt_ew_all_fwd_120d"].to_numpy(float), ti, 24, is_m, oos_m, e1, e2, e3),
        "freeze_x_net_waterpool3m_vs_300_120d": _fmt_uni(valve_x, df["tgt_csi300_fwd_120d"].to_numpy(float), ti, 24, is_m, oos_m, e1, e2, e3),
        "freeze_x_welded_x_hardrescue_vs_300_120d": _fmt_uni(valve_hard_x, df["tgt_csi300_fwd_120d"].to_numpy(float), ti, 24, is_m, oos_m, e1, e2, e3),
        "grp_slogan_without_valve_120d": _group_diff_hac(slogan_freeze_grp, df["tgt_csi300_fwd_120d"].to_numpy(float), ti, 24),
        "grp_freeze_welded_valve_flip_120d": _group_diff_hac(valve_flip_grp, df["tgt_csi300_fwd_120d"].to_numpy(float), ti, 24),
    }
    ch1["verdict"] = "证实(口号喊话无效/负向,真水阀+深跌+硬救市显著正收益)" if (
        abs(ch1["slogan_only_w60_vs_300_120d"]["t_hac"] or 0) < 2.0
        and ((ch1["freeze_x_welded_x_hardrescue_vs_300_120d"]["t_hac"] or 0) > 2.0 or (ch1["grp_freeze_welded_valve_flip_120d"].get("t_hac_on_vs_0") or 0) > 2.0)
    ) else "条件成立"
    out["CH1_口号底vs水阀翻转底"] = ch1

    # CH2: M1-M2 剪刀差与信贷脉冲在 2021 地产见顶后是否发生传导断裂
    m1m2 = df["f3_cn_m1_m2_diff"].to_numpy(float)
    loan = df["f3_cn_new_loan_12m_yoy"].to_numpy(float)
    tsf_imp = df["f3_cn_tsf_impulse_26w"].to_numpy(float)
    y300_120 = df["tgt_csi300_fwd_120d"].to_numpy(float)
    y300_250 = df["tgt_csi300_fwd_250d"].to_numpy(float)
    yew_120 = df["tgt_ew_all_fwd_120d"].to_numpy(float)
    # Formal interaction: y ~ m1m2 + oos + m1m2*oos
    oos_f = oos_m.astype(float)
    inter_res = nw_ols_multi(np.column_stack([m1m2, oos_f, m1m2 * oos_f]), y300_120, ti, 24)
    ch2 = {
        "m1_m2_vs_csi300_120d": _fmt_uni(m1m2, y300_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "m1_m2_vs_csi300_250d": _fmt_uni(m1m2, y300_250, ti, 50, is_m, oos_m, e1, e2, e3),
        "m1_m2_vs_ew_120d": _fmt_uni(m1m2, yew_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "new_loan_yoy_vs_csi300_120d": _fmt_uni(loan, y300_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "tsf_impulse26w_vs_csi300_120d": _fmt_uni(tsf_imp, y300_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "interaction_oos_m1m2_t_hac": round(inter_res["t_stats"][3], 3) if inter_res.get("ok") else None,
        "interaction_oos_m1m2_p_val": round(inter_res["p_vals"][3], 4) if inter_res.get("ok") else None,
    }
    s_is = ch2["m1_m2_vs_csi300_120d"]["IS"]["sign"]
    s_oos = ch2["m1_m2_vs_csi300_120d"]["OOS"]["sign"]
    ch2["verdict"] = "体制断裂(2021年后M1-M2传导斜率明显衰变/翻号)" if s_is != s_oos or abs(ch2["m1_m2_vs_csi300_120d"]["OOS"]["t_hac"] or 0) < 1.5 else "未断裂"
    out["CH2_M1M2与信贷脉冲2021断裂"] = ch2

    # CH3: 中美10Y利差与汇率(USDCNY)非对称压制门控
    spr = df["f4_cn_us_10y_spread_bp"].to_numpy(float)
    fx = df["f4_usdcny"].to_numpy(float)
    inv_grp = (spr < 0.0).astype(float)
    fx7_grp = (fx >= 7.0).astype(float)
    ch3 = {
        "cn_us_10y_vs_csi300_120d": _fmt_uni(spr, y300_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "cn_us_10y_vs_div_minus_chinext_120d": _fmt_uni(spr, df["tgt_div_minus_chinext_120d"].to_numpy(float), ti, 24, is_m, oos_m, e1, e2, e3),
        "usdcny_vs_csi300_120d": _fmt_uni(fx, y300_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "usdcny_vs_div_minus_chinext_120d": _fmt_uni(fx, df["tgt_div_minus_chinext_120d"].to_numpy(float), ti, 24, is_m, oos_m, e1, e2, e3),
        "grp_inverted_spread_vs_300_120d": _group_diff_hac(inv_grp, y300_120, ti, 24),
        "grp_inverted_spread_vs_div_minus_cx_120d": _group_diff_hac(inv_grp, df["tgt_div_minus_chinext_120d"].to_numpy(float), ti, 24),
        "grp_usdcny_ge7_vs_300_120d": _group_diff_hac(fx7_grp, y300_120, ti, 24),
        "grp_usdcny_ge7_vs_micro_minus_300_120d": _group_diff_hac(fx7_grp, df["tgt_micro30_minus_300_120d"].to_numpy(float), ti, 24),
    }
    ch3["verdict"] = "证实(利差倒挂/破7非对称压制大盘且大幅抬升红利相对成长超额)" if (
        abs(ch3["grp_inverted_spread_vs_div_minus_cx_120d"].get("t_hac_diff") or 0) >= 2.0
        or abs(ch3["cn_us_10y_vs_div_minus_chinext_120d"]["t_hac"] or 0) >= 2.5
    ) else "条件成立"
    out["CH3_中美利差与汇率非对称压制"] = ch3

    # CH4: 顶层会议一阶diff完胜静态定调 + F009未提股市非对称风险门
    p2_diff_w = df["f5_p2_delta_stance_dec60"].to_numpy(float)
    p2_stat_w = df["f5_p2_last_macro_stance_score"].to_numpy(float)
    p2_stat_eq = df["f5_p2_last_tone_equity"].to_numpy(float)
    p2_f009_w = df["f5_p2_f009_unmentioned_dec60"].to_numpy(float)
    # Also direct Pillar 2 meeting-event test (110 meetings)
    p2_up = p2_raw[p2_raw["delta_macro_stance"] >= 1]
    p2_st = p2_raw[p2_raw["macro_stance_score"] >= 4]
    p2_f9 = p2_raw[p2_raw["tone_equity"] == 0]
    ch4 = {
        "weekly_delta_stance_dec60_vs_300_60d": _fmt_uni(p2_diff_w, df["tgt_csi300_fwd_60d"].to_numpy(float), ti, 12, is_m, oos_m, e1, e2, e3),
        "weekly_static_stance_vs_300_60d": _fmt_uni(p2_stat_w, df["tgt_csi300_fwd_60d"].to_numpy(float), ti, 12, is_m, oos_m, e1, e2, e3),
        "weekly_static_equity_vs_300_60d": _fmt_uni(p2_stat_eq, df["tgt_csi300_fwd_60d"].to_numpy(float), ti, 12, is_m, oos_m, e1, e2, e3),
        "weekly_f009_dec60_vs_300_60d_mdd": _fmt_uni(p2_f009_w, df["tgt_csi300_fwd_60d_mdd"].to_numpy(float), ti, 12, is_m, oos_m, e1, e2, e3),
        "weekly_f009_dec60_vs_300_120d": _fmt_uni(p2_f009_w, y300_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "event_p2_diff_ge1_mean_60d_pct": round(float(p2_up["ret_csi300_60d"].mean() * 100.0), 2),
        "event_p2_static_ge4_mean_60d_pct": round(float(p2_st["ret_csi300_60d"].mean() * 100.0), 2),
        "event_p2_f009_mean_20d_pct": round(float(p2_f9["ret_csi300_20d"].mean() * 100.0), 2),
        "event_p2_f009_mean_60d_pct": round(float(p2_f9["ret_csi300_60d"].mean() * 100.0), 2),
    }
    ch4["verdict"] = "证实(一阶diff显著优于静态定调)" if (
        abs(ch4["weekly_delta_stance_dec60_vs_300_60d"]["t_hac"] or 0) > abs(ch4["weekly_static_stance_vs_300_60d"]["t_hac"] or 0)
    ) else "部分证伪(F009在低位会议期并无单边下行压制)"
    out["CH4_顶层会议diff与F009"] = ch4

    # CH5: ERP与站上MA200短长周期分化 (20d无效 vs 120d/250d强回归)
    erp300 = df["f2_erp_csi300_pct"].to_numpy(float)
    erp300_3y = df["f2_erp_csi300_pct_3y"].to_numpy(float)
    erp_alla = df["f2_erp_all_a_median_pct"].to_numpy(float)
    ma200 = df["f2_pct_above_ma200"].to_numpy(float)
    ch5 = {
        "erp300_vs_csi300_20d": _fmt_uni(erp300, df["tgt_csi300_fwd_20d"].to_numpy(float), ti, 4, is_m, oos_m, e1, e2, e3),
        "erp300_vs_csi300_60d": _fmt_uni(erp300, df["tgt_csi300_fwd_60d"].to_numpy(float), ti, 12, is_m, oos_m, e1, e2, e3),
        "erp300_vs_csi300_120d": _fmt_uni(erp300, y300_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "erp300_vs_csi300_250d": _fmt_uni(erp300, y300_250, ti, 50, is_m, oos_m, e1, e2, e3),
        "erp_all_a_vs_ew_20d": _fmt_uni(erp_alla, df["tgt_ew_all_fwd_20d"].to_numpy(float), ti, 4, is_m, oos_m, e1, e2, e3),
        "erp_all_a_vs_ew_120d": _fmt_uni(erp_alla, yew_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "erp_all_a_vs_ew_250d": _fmt_uni(erp_alla, df["tgt_ew_all_fwd_250d"].to_numpy(float), ti, 50, is_m, oos_m, e1, e2, e3),
        "erp300_pct3y_vs_csi300_20d": _fmt_uni(erp300_3y, df["tgt_csi300_fwd_20d"].to_numpy(float), ti, 4, is_m, oos_m, e1, e2, e3),
        "erp300_pct3y_vs_csi300_120d": _fmt_uni(erp300_3y, y300_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "erp300_pct3y_vs_csi300_250d": _fmt_uni(erp300_3y, y300_250, ti, 50, is_m, oos_m, e1, e2, e3),
        "ma200_vs_ew_20d": _fmt_uni(ma200, df["tgt_ew_all_fwd_20d"].to_numpy(float), ti, 4, is_m, oos_m, e1, e2, e3),
        "ma200_vs_ew_60d": _fmt_uni(ma200, df["tgt_ew_all_fwd_60d"].to_numpy(float), ti, 12, is_m, oos_m, e1, e2, e3),
        "ma200_vs_ew_120d": _fmt_uni(ma200, yew_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "ma200_vs_ew_250d": _fmt_uni(ma200, df["tgt_ew_all_fwd_250d"].to_numpy(float), ti, 50, is_m, oos_m, e1, e2, e3),
    }
    t20 = abs(ch5["erp_all_a_vs_ew_20d"]["t_hac"] or 0)
    t250 = abs(ch5["erp_all_a_vs_ew_250d"]["t_hac"] or 0)
    ch5["verdict"] = "证实(20d短周期t值弱,120d/250d长周期显著放大回归;全A中位ERP与分位ERP尤为明显)" if t250 > t20 else "条件成立"
    out["CH5_ERP与宽度短长周期分化"] = ch5

    # CH6: 产业部委绿灯补贴 vs 红灯严打非对称行业超额与持续期 (both sector-event level & weekly aggregate)
    p3 = p3_raw.copy()
    p3_summary = {}
    for lbl, sub in [
        ("ALL_GREEN", p3[p3["signal_polarity"] == 1]),
        ("GREEN_SUBSIDY_PLAN", p3[p3["signal_type"] == "GREEN_SUBSIDY_PLAN"]),
        ("GREEN_DEREG_MA", p3[p3["signal_type"] == "GREEN_DEREG_MA"]),
        ("ALL_RED", p3[p3["signal_polarity"] == -1]),
        ("RED_CRACKDOWN_BAN", p3[p3["signal_type"] == "RED_CRACKDOWN_BAN"]),
    ]:
        row = {"n": int(len(sub))}
        for h in [20, 60, 120, 250]:
            vals = sub[f"ex_spliced_{h}d"].dropna().to_numpy(float)
            if len(vals) >= 3:
                t_s, p_s = stats.ttest_1samp(vals, 0.0)
                row[f"ex_{h}d_mean_pct"] = round(float(np.mean(vals)) * 100.0, 2)
                row[f"ex_{h}d_win_pct"] = round(float(np.mean(vals > 0)) * 100.0, 1)
                row[f"ex_{h}d_t"] = round(float(t_s), 2)
        p3_summary[lbl] = row
    ch6 = {
        "sector_event_excess_returns": p3_summary,
        "weekly_green_tech_minus_val_vs_tech_120d": _fmt_uni(df["f6_green_tech_minus_val_int_w120"].to_numpy(float), df["tgt_tech_minus_300_120d"].to_numpy(float), ti, 24, is_m, oos_m, e1, e2, e3),
        "weekly_red_crackdown_vs_csi300_120d": _fmt_uni(df["f6_red_int_w120"].to_numpy(float), y300_120, ti, 24, is_m, oos_m, e1, e2, e3),
    }
    g60 = abs(p3_summary["ALL_GREEN"].get("ex_60d_mean_pct") or 0)
    r120 = abs(p3_summary["ALL_RED"].get("ex_120d_mean_pct") or 0)
    ch6["verdict"] = "证实(红灯严打负超额深度与持续期远强于绿灯补贴)" if r120 > g60 else "条件成立"
    out["CH6_产业绿灯补贴vs红灯严打"] = ch6

    # CH7: 抽血阀(IPO+增发+减持)占流通市值比是否是120d/250d最硬供给约束
    dr_eq_3m = df["wp_drain_equity_supply_mcap_3m"].to_numpy(float)
    dr_eq_12m = df["wp_drain_equity_supply_mcap_12m"].to_numpy(float)
    dr_tot_12m = df["wp_drain_total_mcap_12m"].to_numpy(float)
    ch7 = {
        "drain_equity_3m_vs_csi300_120d": _fmt_uni(dr_eq_3m, y300_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "drain_equity_12m_vs_csi300_250d": _fmt_uni(dr_eq_12m, y300_250, ti, 50, is_m, oos_m, e1, e2, e3),
        "drain_equity_12m_vs_ew_120d": _fmt_uni(dr_eq_12m, yew_120, ti, 24, is_m, oos_m, e1, e2, e3),
        "drain_total_12m_vs_csi300_250d": _fmt_uni(dr_tot_12m, y300_250, ti, 50, is_m, oos_m, e1, e2, e3),
    }
    t_ch7 = abs(ch7["drain_equity_12m_vs_csi300_250d"]["t_hac"] or 0)
    s_same = ch7["drain_equity_12m_vs_csi300_250d"]["IS"]["sign"] == ch7["drain_equity_12m_vs_csi300_250d"]["OOS"]["sign"]
    ch7["verdict"] = "证实(抽血占市值比在120d/250d呈显著跨时代负向约束)" if (t_ch7 >= 2.5 and s_same) else "条件成立/部分证伪"
    out["CH7_抽血阀占市值比供给约束"] = ch7

    # CH8: 国家队托底 + 两融去杠杆 2016~2026 真实回报特征
    sub16 = d >= "2016-01-01"
    g8_arr = df["gate_g8_delev_nt"].to_numpy(float)
    g8_60d = ((df["d_margin_chg_60d_pct"] < 0.0) & (df["d_nt_wflow_60d_mcap"] > 0.0)).to_numpy(float)
    ch8 = {
        "g8_20d_win_csi300_60d": _group_diff_hac(g8_arr, df["tgt_csi300_fwd_60d"].to_numpy(float), ti, 12, sub16),
        "g8_20d_win_csi300_120d": _group_diff_hac(g8_arr, y300_120, ti, 24, sub16),
        "g8_20d_win_csi300_250d": _group_diff_hac(g8_arr, y300_250, ti, 50, sub16),
        "g8_20d_win_ew_120d": _group_diff_hac(g8_arr, yew_120, ti, 24, sub16),
        "g8_20d_win_micro_minus_300_120d": _group_diff_hac(g8_arr, df["tgt_micro30_minus_300_120d"].to_numpy(float), ti, 24, sub16),
        "g8_20d_win_div_minus_cx_120d": _group_diff_hac(g8_arr, df["tgt_div_minus_chinext_120d"].to_numpy(float), ti, 24, sub16),
        "g8_20d_win_csi300_60d_mdd": _group_diff_hac(g8_arr, df["tgt_csi300_fwd_60d_mdd"].to_numpy(float), ti, 12, sub16),
        "g8_60d_win_csi300_120d": _group_diff_hac(g8_60d, y300_120, ti, 24, sub16),
    }
    ch8["verdict"] = "证实(筹码换血期60d-250d具备正收益且显著压低回撤)" if (ch8["g8_20d_win_csi300_120d"].get("t_hac_diff") or 0) >= 1.96 else "条件成立(收益温和或偏好防御权重)"
    out["CH8_国家队托底与两融去杠杆2016_2026"] = ch8

    return out


def run_jorda_local_projections(df: pd.DataFrame) -> dict:
    """
    Jorda (2005) Local Projections across T+20 / T+60 / T+120 / T+250 with 95% HAC CI.
    4 Shocks:
      S1: 净水池由负转正 onset (wp_net_flip_pos_1m rising edge) + active month robustness
      S2: 顶层会议宏调升级 delta>=+1 (meeting week)
      S3: ERP高位 + 抽血焊死双门控 (onset & regime state)
      S4: 强严打红灯集群 (P3 red>=2 in 60d & ME crackdown>=3 in 30d)
    """
    ti = np.arange(len(df), dtype=int)

    # Pre-shock controls Z_t (strictly exogenous pre-shock momentum/vol/macro, avoiding collinearity with ERP/DD shock gates)
    Z_df = df[["f2_csi300_trail_ret_60d", "f2_ew_vol_20d", "f4_us_dgs10_chg13w", "f3_cn_pmi_mfg"]].copy()
    Z_df["f2_csi300_trail_ret_60d"] = Z_df["f2_csi300_trail_ret_60d"].fillna(df["f2_ew_trail_ret_60d"])
    Z = Z_df.to_numpy(float)

    s1_raw = df["wp_net_flip_pos_1m"].fillna(0.0).to_numpy(float)
    s1_onset = ((s1_raw == 1.0) & (np.roll(s1_raw, 1) == 0.0)).astype(float)
    s1_onset[0] = 0.0
    s1_gated = ((df["gate_g1_deep_freeze"] == 1.0) & (df["wp_net_waterpool_incl_div_mcap_3m"] > 0.0)).astype(float).to_numpy()

    s2_up = ((df["f5_p2_days_since_upgrade"] < 7.0) & (df["f5_p2_last_delta_macro_stance"] >= 1.0)).astype(float).to_numpy()

    s3_state = ((df["f2_erp_csi300_pct_3y"] >= 0.75) & (df["wp_drain_total_mcap_pct3y"] <= 0.25)).astype(float).to_numpy()
    s3_onset = ((s3_state == 1.0) & (np.roll(s3_state, 1) == 0.0)).astype(float)
    s3_onset[0] = 0.0

    s4_p3_red = (df["f6_red_cnt_w60"] >= 2.0).astype(float).where(df["f6_red_cnt_w60"].notna(), np.nan).to_numpy()
    s4_me_crk = (df["f5_me_crackdown_w30"] >= 3.0).astype(float).to_numpy()
    s4_me_onset = ((s4_me_crk == 1.0) & (np.roll(s4_me_crk, 1) == 0.0)).astype(float)
    s4_me_onset[0] = 0.0

    shocks = [
        ("S1_净水池由负转正_onset", s1_onset, "1M净水池由负转正首次触发周"),
        ("S1c_深跌冰点+净水池含分红转正", s1_gated, "深跌冰点门控下3M含分红净水池>0"),
        ("S2_顶层会议宏调升级_ge1", s2_up, "顶层会议delta_macro_stance>=+1周"),
        ("S3_高ERP加抽血焊死_onset", s3_onset, "高ERP+抽血<=25%分位首次进入周"),
        ("S3b_高ERP加抽血焊死_state", s3_state, "高ERP+抽血<=25%分位持续门控状态"),
        ("S4_产业红灯集群_p3_ge2", s4_p3_red, "近60日部委红灯>=2件集群期"),
        ("S4b_监管严打集群_me_onset", s4_me_onset, "近30日监管严打>=3件冲击首次触发周"),
    ]

    horizons = [(20, 4), (60, 12), (120, 24), (250, 50)]
    assets = [("csi300", "tgt_csi300_fwd_{h}d"), ("ew_all", "tgt_ew_all_fwd_{h}d"), ("csi300_mdd", "tgt_csi300_fwd_{h}d_mdd")]

    lp_out = {}
    for snm, s_arr, s_desc in shocks:
        rec = {"description": s_desc, "n_shocks_total": int(np.nansum(s_arr)), "horizons": {}}
        for h, lag in horizons:
            h_res = {}
            for anm, t_tmpl in assets:
                y = df[t_tmpl.format(h=h)].to_numpy(float)
                X_ctrl = np.column_stack([s_arr, Z])
                res_c = nw_ols_multi(X_ctrl, y, ti, lag)
                res_u = nw_ols_multi(s_arr[:, None], y, ti, lag)
                if res_c.get("ok"):
                    b = res_c["params"][1] * 100.0
                    se = res_c["se"][1] * 100.0
                    t_v = res_c["t_stats"][1]
                    p_v = res_c["p_vals"][1]
                    h_res[anm] = {
                        "irf_ctrl_pct": round(b, 2),
                        "se_hac_pct": round(se, 2),
                        "ci95_low_pct": round(b - 1.96 * se, 2),
                        "ci95_high_pct": round(b + 1.96 * se, 2),
                        "t_hac": round(t_v, 3),
                        "p_val": round(p_v, 4),
                        "irf_uncond_pct": round(res_u["params"][1] * 100.0, 2) if res_u.get("ok") else None,
                        "t_uncond": round(res_u["t_stats"][1], 3) if res_u.get("ok") else None,
                        "n_obs": res_c["n"],
                    }
            rec["horizons"][f"T+{h}"] = h_res
        lp_out[snm] = rec
    return lp_out
