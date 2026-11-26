#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD034 Step 2: Comprehensive Dual (Linear + 5-Quantile Nonlinear) Scan across
All 6 V20.0 Strategies (L1_cand / L2_pass / L2b_slot1) + V20.0 Combined (N=278),
Yearly Consistency (2021~2026, IS vs OOS vs Y2026), BH-FDR, and V20.0 Absorption Attribution.

Hard rules:
  - ZERO yfinance (D12).
  - Read-only on production scripts and strategy_astock.md.
"""
import json
import math
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock2/rd034_ashare_3layer_cycles_6strat_20261125"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"

STRAT_ORDER = ["1to2", "2to3", "3to4", "high", "pry", "20cm"]
N_PERM = 2000
SEED = 20261125

# Full 61-factor dictionary with layer, Chinese name, kind (cont/cat/ord)
FACTOR_SPECS = [
    # Layer 1: Market Sentiment (13)
    ("L1_zt_cnt_t1", "L1_市场", "T-1全市场涨停家数", "cont"),
    ("L1_nat_zt_cnt_t1", "L1_市场", "T-1非一字自然涨停家数", "cont"),
    ("L1_dt_cnt_t1", "L1_市场", "T-1全市场跌停家数", "cont"),
    ("L1_zt_dt_logratio_t1", "L1_市场", "T-1涨跌停比(对数)", "cont"),
    ("L1_zb_rate_t1", "L1_市场", "T-1全市场炸板率%", "cont"),
    ("L1_max_board_t1", "L1_市场", "T-1空间板最高连板高度", "cont"),
    ("L1_lianban_cnt_t1", "L1_市场", "T-1二板及以上连板总数", "cont"),
    ("L1_zt_prem_t1", "L1_市场", "T-1昨日涨停今日平均溢价率%", "cont"),
    ("L1_lb_promo_t1", "L1_市场", "T-1昨日连板今日晋级率%", "cont"),
    ("L1_duanban_damian_t1", "L1_市场", "T-1昨日断板今日大面率%", "cont"),
    ("L1_zt_mom3v20_t1", "L1_市场", "T-1近3日vs20日涨停动量", "cont"),
    ("L1_zt_pct60_t1", "L1_市场", "T-1涨停家数60日滚动分位", "cont"),
    ("L1_sent_phase_t1", "L1_市场", "T-1情绪五态(冰点/修复/主升/高潮/退潮)", "cat"),
    # Layer 1: Style, Breadth, Turnover (7)
    ("L1_smb_5d_t1", "L1_市场", "微盘减大盘5日收益差%", "cont"),
    ("L1_smb_20d_t1", "L1_市场", "微盘减大盘20日收益差%", "cont"),
    ("L1_smb_60d_t1", "L1_市场", "微盘减大盘60日收益差%", "cont"),
    ("L1_breadth_5d_t1", "L1_市场", "全市场上涨比例5日均值", "cont"),
    ("L1_breadth_20d_t1", "L1_市场", "全市场上涨比例20日均值", "cont"),
    ("L1_amt_ratio20_t1", "L1_市场", "T-1全市场成交额/20日均量", "cont"),
    ("L1_amt_ratio5v60_t1", "L1_市场", "5日均额/60日均额", "cont"),
    # Layer 1: Index Trend & Volatility (7)
    ("L1_ew_bias20_t1", "L1_市场", "全A等权指数MA20乖离率%", "cont"),
    ("L1_ew_bias60_t1", "L1_市场", "全A等权指数MA60乖离率%", "cont"),
    ("L1_ew_bias250_t1", "L1_市场", "全A等权指数MA250乖离率%", "cont"),
    ("L1_ew_ret20_t1", "L1_市场", "全A等权指数20日涨幅%", "cont"),
    ("L1_ew_vol20_t1", "L1_市场", "全A等权指数20日波动率%", "cont"),
    ("L1_ew_pos60_t1", "L1_市场", "全A等权指数60日高低位置", "cont"),
    ("L1_csi_bias60_t1", "L1_市场", "沪深300MA60乖离率%", "cont"),
    # Layer 1: Calendar & Earnings Windows (6)
    ("L1_is_earn_win", "L1_市场", "财报窗口分段(0常/1一月/2四月/3中报/4三季)", "cat"),
    ("L1_is_earn_any", "L1_市场", "是否处于财报季窗口(0/1)", "cat"),
    ("L1_is_earn_apr", "L1_市场", "是否处于4月年季报雷区(0/1)", "cat"),
    ("L1_is_month_end3", "L1_市场", "是否月末最后3天(0/1)", "cat"),
    ("L1_is_pre_hol2", "L1_市场", "是否长假前2天(0/1)", "cat"),
    ("L1_weekday", "L1_市场", "星期几效应(1~5)", "cat"),
    # Layer 2: CSRC Industry Rotation & Crowding (11)
    ("L2_ind_ex5_t1", "L2_行业题材", "所属行业5日相对全市场超额%", "cont"),
    ("L2_ind_ex20_t1", "L2_行业题材", "所属行业20日相对全市场超额%", "cont"),
    ("L2_ind_ex60_t1", "L2_行业题材", "所属行业60日相对全市场超额%", "cont"),
    ("L2_ind_ex120_t1", "L2_行业题材", "所属行业120日相对全市场超额%", "cont"),
    ("L2_ind_rank20_t1", "L2_行业题材", "所属行业20日全行业横截面排名", "cont"),
    ("L2_ind_rank60_t1", "L2_行业题材", "所属行业60日全行业横截面排名", "cont"),
    ("L2_ind_pos60_t1", "L2_行业题材", "所属行业60日区间价格位置", "cont"),
    ("L2_ind_pos250_t1", "L2_行业题材", "所属行业250日区间价格位置", "cont"),
    ("L2_ind_amt_pct250_t1", "L2_行业题材", "所属行业成交占比250日分位(拥挤度)", "cont"),
    ("L2_ind_zt_share5_t1", "L2_行业题材", "所属行业近5日涨停占比%", "cont"),
    ("L2_ind_up_streak_t1", "L2_行业题材", "所属行业连续跑赢市场天数", "cont"),
    # Layer 2: KPL Theme Lifecycle (7)
    ("L2_kpl_zt1_t1", "L2_行业题材", "T-1核心题材当日涨停数", "cont"),
    ("L2_kpl_zt3_t1", "L2_行业题材", "核心题材近3日累计涨停数", "cont"),
    ("L2_kpl_zt20_t1", "L2_行业题材", "核心题材近20日累计涨停数", "cont"),
    ("L2_kpl_streak_t1", "L2_行业题材", "核心题材连续爆发天数(>=3涨停)", "cont"),
    ("L2_kpl_crowd_t1", "L2_行业题材", "T-1核心题材涨停占全市场比%", "cont"),
    ("L2_kpl_peak_ratio_t1", "L2_行业题材", "T-1核心题材相对20日峰值比", "cont"),
    ("L2_kpl_wave_cnt60_t1", "L2_行业题材", "核心题材60日内爆发波次数", "cont"),
    # Layer 3: Individual Stock Position, Vol Compression, Chip & Size (18)
    ("L3_pos_60d_t1", "L3_个股", "T-1收盘相对60日区间位置", "cont"),
    ("L3_pos_250d_t1", "L3_个股", "T-1收盘相对250日区间位置", "cont"),
    ("L3_pos_750d_t1", "L3_个股", "T-1收盘相对3年区间位置", "cont"),
    ("L3_dd_250d_t1", "L3_个股", "T-1距250日高点回撤%", "cont"),
    ("L3_off_low_250d_t1", "L3_个股", "T-1距250日低点累计涨幅%", "cont"),
    ("L3_bias20_t1", "L3_个股", "T-1个股MA20乖离率%", "cont"),
    ("L3_bias60_t1", "L3_个股", "T-1个股MA60乖离率%", "cont"),
    ("L3_ma_bull_score_t1", "L3_个股", "T-1均线多头排列得分(0~4)", "cat"),
    ("L3_prewave_rng20_t1", "L3_个股", "启动前20日振幅%", "cont"),
    ("L3_amp_comp_20v60_t1", "L3_个股", "启动前20日/60日振幅压缩比", "cont"),
    ("L3_newhigh_cnt60_t1", "L3_个股", "近60日创250日新高次数", "cont"),
    ("L3_turn5_pct250_t1", "L3_个股", "5日均换手在过去250日分位", "cont"),
    ("L3_turn20_pct250_t1", "L3_个股", "20日均换手在过去250日分位", "cont"),
    ("L3_cum_turn20_t1", "L3_个股", "近20日累计换手率%", "cont"),
    ("L3_overhang_pct_t1", "L3_个股", "近1年上方套牢盘成交额占比%", "cont"),
    ("L3_mcap_pct_t1", "L3_个股", "T-1流通市值全市场横截面分位", "cont"),
    ("L3_zt_cnt250_t1", "L3_个股", "过去250日涨停总次数", "cont"),
    ("L3_act_x_pos_t1", "L3_个股", "股性活跃度×250日位置交互项", "cont"),
]

SENT_LABELS = {1: "1_冰点", 2: "2_修复", 3: "3_主升", 4: "4_高潮", 5: "5_退潮"}
EARN_LABELS = {0: "0_常态", 1: "1_1月预告", 2: "2_4月年季报", 3: "3_中报", 4: "4_三季报"}


def sf(x, digits=4):
    if x is None:
        return None
    v = float(x)
    return None if (math.isnan(v) or math.isinf(v)) else round(v, digits)


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


def bh_fdr(pvals: list[float]) -> list[float]:
    n = len(pvals)
    if n == 0:
        return []
    arr = np.asarray([1.0 if (p is None or np.isnan(p)) else float(p) for p in pvals])
    order = np.argsort(arr)
    ranked = arr[order]
    q = np.empty(n, dtype=float)
    min_q = 1.0
    for i in range(n - 1, -1, -1):
        val = ranked[i] * n / (i + 1)
        min_q = min(min_q, val)
        q[i] = min_q
    out = np.empty(n, dtype=float)
    out[order] = np.clip(q, 0.0, 1.0)
    return [round(float(x), 6) for x in out]


def safe_ols_cluster(y: np.ndarray, X: np.ndarray, clusters: np.ndarray):
    keep = [0]
    for j in range(1, X.shape[1]):
        if np.std(X[:, j]) > 1e-10 and np.linalg.matrix_rank(X[:, keep + [j]]) > len(keep):
            keep.append(j)
    Xk = X[:, keep]
    n, k = Xk.shape
    if n <= k + 3 or len(np.unique(clusters)) < k + 2:
        return None
    mod = sm.OLS(y, Xk)
    try:
        res = mod.fit(cov_type="cluster", cov_kwds={"groups": clusters}, use_t=True)
        if not np.all(np.isfinite(res.bse)):
            res = mod.fit(cov_type="HC3", use_t=True)
    except Exception:
        try:
            res = mod.fit(cov_type="HC1", use_t=True)
        except Exception:
            return None
    return keep, res


def perm_extreme_contrast(y: np.ndarray, group_codes: np.ndarray, n_groups: int, rng: np.random.Generator) -> tuple[float | None, float | None, str]:
    """
    2,000x permutation test for max contrast among:
      - Q_last - Q_first (monotone spread)
      - Q_first - mid_group
      - Q_last - mid_group
      - extremes(first & last) - mid_group (U / inverted-U)
    Returns (obs_contrast_pp, p_perm, contrast_name).
    """
    n = len(y)
    if n < 25 or n_groups < 3:
        return None, None, ""
    counts = np.bincount(group_codes, minlength=n_groups)
    if np.sum(counts >= 5) < 3:
        return None, None, ""
    valid_g = np.where(counts >= 5)[0]
    g_lo, g_hi = int(valid_g[0]), int(valid_g[-1])
    g_mids = valid_g[1:-1]

    def _calc_contrasts(arr_y: np.ndarray):
        sums = np.bincount(group_codes, weights=arr_y, minlength=n_groups)
        means = sums / np.maximum(1, counts)
        m_lo = means[g_lo]
        m_hi = means[g_hi]
        m_mid = np.sum(sums[g_mids]) / max(1, int(np.sum(counts[g_mids])))
        m_ext = (sums[g_lo] + sums[g_hi]) / max(1, int(counts[g_lo] + counts[g_hi]))
        c1 = m_hi - m_lo
        c2 = m_lo - m_mid
        c3 = m_hi - m_mid
        c4 = m_ext - m_mid
        return np.array([c1, c2, c3, c4], dtype=float)

    obs_c = _calc_contrasts(y)
    abs_c = np.abs(obs_c)
    best_i = int(np.argmax(abs_c))
    obs_max = float(abs_c[best_i])
    c_names = ["Q5-Q1", "Q1-Mid", "Q5-Mid", "Extremes-Mid"]

    # Vectorized permutation matrix using argsort of random
    # Keep memory small by doing batches of 500
    ge_cnt = 0
    for b_sz in (500, 500, 500, 500):
        idx = np.argsort(rng.random((n, b_sz)), axis=0)
        yp = y[idx]  # (n, b_sz)
        # Group sums for each permutation
        g_sums = np.zeros((n_groups, b_sz), dtype=float)
        for g in valid_g:
            g_sums[g] = yp[group_codes == g].sum(axis=0)
        m_lo = g_sums[g_lo] / counts[g_lo]
        m_hi = g_sums[g_hi] / counts[g_hi]
        m_mid = g_sums[g_mids].sum(axis=0) / np.sum(counts[g_mids])
        m_ext = (g_sums[g_lo] + g_sums[g_hi]) / (counts[g_lo] + counts[g_hi])
        max_p = np.maximum.reduce([np.abs(m_hi - m_lo), np.abs(m_lo - m_mid), np.abs(m_hi - m_mid), np.abs(m_ext - m_mid)])
        ge_cnt += int(np.sum(max_p >= obs_max - 1e-12))

    p_perm = (ge_cnt + 1.0) / (2000.0 + 1.0)
    return sf(obs_c[best_i] * 100.0, 2), sf(p_perm, 5), c_names[best_i]


def perm_cat_spread(y: np.ndarray, group_codes: np.ndarray, n_groups: int, rng: np.random.Generator) -> tuple[float | None, float | None]:
    counts = np.bincount(group_codes, minlength=n_groups)
    valid_g = np.where(counts >= 5)[0]
    if len(valid_g) < 2 or len(y) < 15:
        return None, None
    sums = np.bincount(group_codes, weights=y, minlength=n_groups)
    means = sums[valid_g] / counts[valid_g]
    obs_sp = float(np.max(means) - np.min(means))
    ge_cnt = 0
    n = len(y)
    for b_sz in (500, 500, 500, 500):
        idx = np.argsort(rng.random((n, b_sz)), axis=0)
        yp = y[idx]
        g_means = np.vstack([yp[group_codes == g].mean(axis=0) for g in valid_g])
        sp_p = g_means.max(axis=0) - g_means.min(axis=0)
        ge_cnt += int(np.sum(sp_p >= obs_sp - 1e-12))
    return sf(obs_sp * 100.0, 2), sf((ge_cnt + 1.0) / 2001.0, 5)


def analyze_one_pair(
    sub: pd.DataFrame,
    fcol: str,
    flayer: str,
    fcn: str,
    fkind: str,
    target_id: str,
    rng: np.random.Generator,
) -> tuple[dict, dict | None]:
    """Full linear + nonlinear + yearly + IS/OOS + v20_score correlation analysis for (target, factor)."""
    s_valid = sub[sub[fcol].notna()].copy()
    n = len(s_valid)
    miss_pct = sf((1.0 - n / max(1, len(sub))) * 100.0, 2)

    base_rec = {
        "target": target_id,
        "factor": fcol,
        "layer": flayer,
        "factor_cn": fcn,
        "kind": fkind,
        "n_total": int(len(sub)),
        "n_valid": int(n),
        "missing_pct": miss_pct,
        "n_dates": int(s_valid["buy_date"].nunique()) if n else 0,
    }
    if n < 20 or s_valid[fcol].nunique() < 2:
        return {**base_rec, "insufficient": True}, None

    y = s_valid["net_ret"].to_numpy(float)
    x = s_valid[fcol].to_numpy(float)
    ex = s_valid["excess_trade_ret"].to_numpy(float)
    sc = s_valid["v20_score"].to_numpy(float)
    cl = s_valid["buy_date"].to_numpy()

    # Correlation with v20_score (absorption diagnostic)
    if np.std(sc) > 1e-10 and np.std(x) > 1e-10:
        r_v20, p_v20 = stats.spearmanr(x, sc)
    else:
        r_v20, p_v20 = np.nan, np.nan

    # Linear tests (Spearman + Date-Agg Spearman + Clustered OLS + Score-Controlled OLS)
    sp_r, sp_p = stats.spearmanr(x, y) if np.std(x) > 1e-10 else (np.nan, 1.0)
    dt_df = pd.DataFrame({"dt": cl, "x": x, "y": y}).groupby("dt", as_index=False).mean()
    if len(dt_df) >= 12 and dt_df["x"].std() > 1e-10:
        dt_r, dt_p = stats.spearmanr(dt_df["x"], dt_df["y"])
    else:
        dt_r, dt_p = np.nan, 1.0

    z = (x - np.mean(x)) / np.std(x) if np.std(x) > 1e-10 else np.zeros(n)
    z2 = z ** 2
    has_sc = np.std(sc) > 1e-10
    z_sc = (sc - np.mean(sc)) / np.std(sc) if has_sc else np.zeros(n)

    fit_l = safe_ols_cluster(y, np.column_stack([np.ones(n), z]), cl)
    t_lin, p_lin, b_lin = None, 1.0, None
    if fit_l is not None and 1 in fit_l[0]:
        pos = fit_l[0].index(1)
        b_lin = sf(fit_l[1].params[pos] * 100.0, 3)
        t_lin = sf(fit_l[1].tvalues[pos], 3)
        p_lin = float(fit_l[1].pvalues[pos])

    X_lc = np.column_stack([np.ones(n), z, z_sc]) if has_sc else np.column_stack([np.ones(n), z])
    fit_lc = safe_ols_cluster(y, X_lc, cl)
    t_lctrl, p_lctrl = None, 1.0
    if fit_lc is not None and 1 in fit_lc[0]:
        pos = fit_lc[0].index(1)
        t_lctrl = sf(fit_lc[1].tvalues[pos], 3)
        p_lctrl = float(fit_lc[1].pvalues[pos])

    # Quadratic & Joint 2-df F-test (controlling for v20_score)
    X_qc = np.column_stack([np.ones(n), z, z2, z_sc]) if has_sc else np.column_stack([np.ones(n), z, z2])
    fit_qc = safe_ols_cluster(y, X_qc, cl)
    t_quad_c, p_quad_c, b_quad_c, p_joint_c, int_vtx = None, 1.0, None, 1.0, False
    if fit_qc is not None and 2 in fit_qc[0]:
        k_qc = len(fit_qc[0])
        p2 = fit_qc[0].index(2)
        b_quad_c = float(fit_qc[1].params[p2])
        t_quad_c = sf(fit_qc[1].tvalues[p2], 3)
        p_quad_c = float(fit_qc[1].pvalues[p2])
        if 1 in fit_qc[0]:
            p1 = fit_qc[0].index(1)
            b1 = float(fit_qc[1].params[p1])
            if abs(b_quad_c) > 1e-8:
                vtx = -b1 / (2.0 * b_quad_c)
                int_vtx = bool(np.quantile(z, 0.10) <= vtx <= np.quantile(z, 0.90))
            if n >= 30 and len(np.unique(cl)) >= 20:
                R = np.zeros((2, k_qc))
                R[0, p1] = 1.0
                R[1, p2] = 1.0
                try:
                    p_joint_c = float(fit_qc[1].f_test(R).pvalue)
                except Exception:
                    p_joint_c = 1.0

    # Nonlinear 5-quantile / categorical grouping
    bin_rows = []
    kw_p = 1.0
    ext_diff_pp, p_perm_ext, ext_label = None, 1.0, ""
    if fkind == "cont" and s_valid[fcol].nunique() >= 5 and n >= 30:
        try:
            q_cat = pd.qcut(s_valid[fcol], q=5, duplicates="drop")
            codes = q_cat.cat.codes.to_numpy()
            cats = list(q_cat.cat.categories)
            groups_kw = []
            for gi, iv in enumerate(cats):
                m = codes == gi
                if m.sum() == 0:
                    continue
                yy = y[m]
                ee = ex[m]
                groups_kw.append(yy)
                bin_rows.append({
                    "bin": f"Q{gi+1}",
                    "range": str(iv),
                    "n": int(m.sum()),
                    "wr_pct": sf((yy > 0).mean() * 100.0, 1),
                    "mean_ret_pct": sf(yy.mean() * 100.0, 2),
                    "med_ret_pct": sf(np.median(yy) * 100.0, 2),
                    "ex_csi_pct": sf(np.nanmean(ee) * 100.0, 2),
                })
            if len(groups_kw) >= 2 and all(len(g) >= 2 for g in groups_kw):
                _, kw_p = stats.kruskal(*groups_kw)
            ext_diff_pp, p_perm_ext, ext_label = perm_extreme_contrast(y, codes, len(cats), rng)
        except Exception:
            pass
    else:
        # Categorical or discrete levels
        uniq_vals = sorted(s_valid[fcol].unique())
        val_map = {v: i for i, v in enumerate(uniq_vals)}
        codes = np.array([val_map[v] for v in s_valid[fcol]], dtype=int)
        groups_kw = []
        for gi, uv in enumerate(uniq_vals):
            m = codes == gi
            yy = y[m]
            ee = ex[m]
            if len(yy) >= 2:
                groups_kw.append(yy)
            lbl = SENT_LABELS.get(int(uv), str(uv)) if fcol == "L1_sent_phase_t1" else (EARN_LABELS.get(int(uv), str(uv)) if fcol == "L1_is_earn_win" else str(int(uv) if float(uv).is_integer() else uv))
            bin_rows.append({
                "bin": lbl,
                "n": int(m.sum()),
                "wr_pct": sf((yy > 0).mean() * 100.0, 1),
                "mean_ret_pct": sf(yy.mean() * 100.0, 2),
                "med_ret_pct": sf(np.median(yy) * 100.0, 2),
                "ex_csi_pct": sf(np.nanmean(ee) * 100.0, 2),
            })
        if len(groups_kw) >= 2:
            _, kw_p = stats.kruskal(*groups_kw)
        ext_diff_pp, p_perm_ext = perm_cat_spread(y, codes, len(uniq_vals), rng)
        ext_label = "Max-Min_Cat"

    # Temporal stability: IS (<=2024-12-31), OOS (>=2025-01-01), Y2026 (>=2026-01-01), and yearly 2021..2026
    s_valid["yr"] = s_valid["buy_date"].str[:4]
    def _slice_stat(df_sl: pd.DataFrame) -> dict:
        if len(df_sl) < 8 or df_sl[fcol].std() < 1e-10:
            return {"n": int(len(df_sl)), "r": None, "p": None, "hi_lo_pp": None}
        r_s, p_s = stats.spearmanr(df_sl[fcol], df_sl["net_ret"])
        # Quick Q5-Q1 or Hi-Lo split at median
        med_v = df_sl[fcol].median()
        hi = df_sl[df_sl[fcol] > med_v]["net_ret"]
        lo = df_sl[df_sl[fcol] <= med_v]["net_ret"]
        if len(hi) == 0 or len(lo) == 0:
            hi = df_sl[df_sl[fcol] >= med_v]["net_ret"]
            lo = df_sl[df_sl[fcol] < med_v]["net_ret"]
        diff_hl = (hi.mean() - lo.mean()) * 100.0 if (len(hi) >= 3 and len(lo) >= 3) else None
        return {"n": int(len(df_sl)), "r": sf(r_s, 3), "p": sf(p_s, 5), "hi_lo_pp": sf(diff_hl, 2)}

    is_st = _slice_stat(s_valid[s_valid["buy_date"] <= "2024-12-31"])
    oos_st = _slice_stat(s_valid[s_valid["buy_date"] >= "2025-01-01"])
    y26_st = _slice_stat(s_valid[s_valid["buy_date"] >= "2026-01-01"])

    yearly = {}
    same_dir_yrs = 0
    valid_yrs = 0
    main_sign = 1 if (sp_r is not None and sp_r > 0) else -1
    for yr in ("2021", "2022", "2023", "2024", "2025", "2026"):
        ys = _slice_stat(s_valid[s_valid["yr"] == yr])
        yearly[yr] = ys
        if ys["r"] is not None:
            valid_yrs += 1
            if (ys["r"] > 0 and main_sign > 0) or (ys["r"] < 0 and main_sign < 0):
                same_dir_yrs += 1

    # Shape classification
    shape = "null"
    p_min_raw = min(
        p_lin if np.isfinite(p_lin) else 1.0,
        kw_p if np.isfinite(kw_p) else 1.0,
        p_perm_ext if (p_perm_ext is not None and np.isfinite(p_perm_ext)) else 1.0,
        p_joint_c if np.isfinite(p_joint_c) else 1.0,
    )
    if p_min_raw < 0.05:
        if fkind == "cat":
            shape = "categorical_diff"
        elif p_quad_c < 0.05 and int_vtx and b_quad_c is not None:
            shape = "inverted_u" if b_quad_c < 0 else "u_shape"
        elif p_lin < 0.05 or (sp_p is not None and sp_p < 0.05):
            shape = "monotone_inc" if (sp_r > 0) else "monotone_dec"
        elif p_perm_ext is not None and p_perm_ext < 0.05:
            shape = f"nonlinear_{ext_label}"

    rec = {
        **base_rec,
        "insufficient": False,
        "spearman_r": sf(sp_r, 4),
        "spearman_p": sf(sp_p, 6),
        "date_agg_spearman_r": sf(dt_r, 4),
        "date_agg_spearman_p": sf(dt_p, 6),
        "beta_lin_pp_per_sd": b_lin,
        "t_lin_cl": t_lin,
        "p_lin_cl": sf(p_lin, 6),
        "t_lin_ctrl_v20_cl": t_lctrl,
        "p_lin_ctrl_v20_cl": sf(p_lctrl, 6),
        "t_quad_ctrl_cl": t_quad_c,
        "p_quad_ctrl_cl": sf(p_quad_c, 6),
        "p_joint_ctrl_cl": sf(p_joint_c, 6),
        "interior_vertex": int_vtx,
        "kw_p": sf(kw_p, 6),
        "ext_contrast_label": ext_label,
        "ext_contrast_pp": ext_diff_pp,
        "p_perm_ext": p_perm_ext,
        "p_min_raw": sf(p_min_raw, 6),
        "shape_raw": shape,
        "r_with_v20_score": sf(r_v20, 4),
        "p_with_v20_score": sf(p_v20, 6),
        "is_r": is_st["r"], "is_p": is_st["p"], "is_hilo_pp": is_st["hi_lo_pp"],
        "oos_r": oos_st["r"], "oos_p": oos_st["p"], "oos_hilo_pp": oos_st["hi_lo_pp"],
        "y26_r": y26_st["r"], "y26_p": y26_st["p"], "y26_hilo_pp": y26_st["hi_lo_pp"],
        "is_oos_same_sign": bool(is_st["r"] is not None and oos_st["r"] is not None and (is_st["r"] * oos_st["r"] > 0)),
        "yr_consistent": f"{same_dir_yrs}/{valid_yrs}",
        "same_dir_yrs": int(same_dir_yrs),
        "valid_yrs": int(valid_yrs),
    }
    detail = {"bins": bin_rows, "yearly": yearly, "is": is_st, "oos": oos_st, "y2026": y26_st}
    return rec, detail


def build_v20_regime_firing_table(df_all6: pd.DataFrame, mkt_df: pd.DataFrame) -> list[dict]:
    """
    Attribution Test B: Over the canonical 5Y trading calendar (2021-11-16 ~ 2026-11-16, 1,212 days),
    measure how often V20.0 Combined & 6 individual strategies fire / stay empty across adverse regimes!
    """
    m5 = mkt_df[mkt_df["dt"].between("2021-11-16", "2026-11-16")].copy().reset_index(drop=True)
    # Compute rolling 60d/250d thresholds strictly or factual regime definitions
    zb_q80 = float(m5["L1_zb_rate_t1"].quantile(0.80))
    smb_q20 = float(m5["L1_smb_20d_t1"].quantile(0.20))
    smb_q80 = float(m5["L1_smb_20d_t1"].quantile(0.80))

    comb_entries = df_all6[df_all6["is_v20_slot1"].astype(bool)].copy()
    pass_entries = df_all6[df_all6["is_pass_official"].astype(bool)].copy()

    regimes = [
        ("情绪五态: 冰点", m5["L1_sent_phase_t1"] == 1),
        ("情绪五态: 修复", m5["L1_sent_phase_t1"] == 2),
        ("情绪五态: 主升", m5["L1_sent_phase_t1"] == 3),
        ("情绪五态: 高潮", m5["L1_sent_phase_t1"] == 4),
        ("情绪五态: 退潮", m5["L1_sent_phase_t1"] == 5),
        ("昨日全市场涨停 < 25家 (极冷)", m5["L1_zt_cnt_t1"] < 25),
        ("昨日全市场涨停 >= 80家 (极热)", m5["L1_zt_cnt_t1"] >= 80),
        (f"昨日炸板率高企 (>={zb_q80:.1f}%)", m5["L1_zb_rate_t1"] >= zb_q80),
        ("昨日跌停潮 (>=20家非ST跌停)", m5["L1_dt_cnt_t1"] >= 20),
        ("4月年季报雷区 (04-15~04-30)", m5["L1_is_earn_apr"] == 1),
        ("全财报季窗口 (1/4/7-8/10月)", m5["L1_is_earn_any"] == 1),
        ("长假前2个交易日", m5["L1_is_pre_hol2"] == 1),
        ("月末最后3个交易日", m5["L1_is_month_end3"] == 1),
        ("市场MA60深度空头 (<-5%)", m5["L1_ew_bias60_t1"] < -5.0),
        ("市场MA60强势多头 (>+5%)", m5["L1_ew_bias60_t1"] > 5.0),
        (f"风格极不利微盘 (微盘20日跑输<={smb_q20:.1f}%)", m5["L1_smb_20d_t1"] <= smb_q20),
        (f"风格微盘狂热 (微盘20日跑赢>={smb_q80:.1f}%)", m5["L1_smb_20d_t1"] >= smb_q80),
        ("全期基准 (全部1212天)", pd.Series(True, index=m5.index)),
    ]

    rows = []
    for rname, rmask in regimes:
        dts = set(m5[rmask]["dt"])
        nd = len(dts)
        if nd == 0:
            continue
        c_sub = comb_entries[comb_entries["buy_date"].isin(dts)]
        p_sub = pass_entries[pass_entries["buy_date"].isin(dts)]
        pass_days = p_sub["buy_date"].nunique()
        rets = c_sub["net_ret"].to_numpy(float)
        by_st = {}
        for st in STRAT_ORDER:
            ss = c_sub[c_sub["strategy"] == st]
            sr = ss["net_ret"].to_numpy(float)
            by_st[st] = {
                "n": int(len(sr)),
                "per_100d": sf(len(sr) / nd * 100.0, 2),
                "wr_pct": sf((sr > 0).mean() * 100.0, 1) if len(sr) else None,
                "mean_pct": sf(sr.mean() * 100.0, 2) if len(sr) else None,
            }
        rows.append({
            "regime": rname,
            "n_days": int(nd),
            "days_pct": sf(nd / len(m5) * 100.0, 1),
            "any_pass_signal_day_pct": sf(pass_days / nd * 100.0, 1),
            "comb_n": int(len(rets)),
            "comb_entries_per_100d": sf(len(rets) / nd * 100.0, 2),
            "comb_wr_pct": sf((rets > 0).mean() * 100.0, 1) if len(rets) else None,
            "comb_mean_ret_pct": sf(rets.mean() * 100.0, 2) if len(rets) else None,
            "comb_med_ret_pct": sf(np.median(rets) * 100.0, 2) if len(rets) else None,
            "by_strategy_comb": by_st,
        })
    return rows


def main():
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    print("[Step 2] Loading pools with 3-layer cycles & CSI300 benchmark...")
    idx_raw = json.load(open(IDX_JSON, encoding="utf-8"))
    sh300 = {k: float(v) for k, v in idx_raw["sh000300"].items()}
    all_sh_dts = sorted(sh300.keys())
    prev_td = {all_sh_dts[i]: all_sh_dts[i - 1] for i in range(1, len(all_sh_dts))}

    df = pd.read_parquet(f"{OUT_DIR}/pools_6strat_with_3layer_cycles.parquet")
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["buy_date"] = df["buy_date"].astype(str).str[:10]
    df["exit_date"] = df["exit_date"].astype(str).str[:10]

    mkt_df = pd.read_parquet(f"{OUT_DIR}/rd034_market_daily_pit.parquet")

    # Compute concurrent CSI300 excess per trade
    csi_r = np.full(len(df), np.nan, dtype=float)
    sim_mask = df["sim_ok"].to_numpy(bool) & df["net_ret"].notna().to_numpy(bool)
    bds = df["buy_date"].to_numpy()
    eds = df["exit_date"].to_numpy()
    for i in np.flatnonzero(sim_mask):
        p0 = prev_td.get(bds[i])
        if p0 is not None and eds[i] in sh300:
            csi_r[i] = sh300[eds[i]] / sh300[p0] - 1.0
    df["csi_trade_ret"] = csi_r
    df["excess_trade_ret"] = df["net_ret"].astype(float) - df["csi_trade_ret"]

    # Build target masks: 6 strats x (L1_cand, L2_pass, L2b_slot1) + comb_278
    targets = []
    for st in STRAT_ORDER:
        base_m = (df["strategy"] == st) & df["sim_ok"].astype(bool) & df["net_ret"].notna()
        targets.append((f"{st}__L1_cand", df[base_m].copy()))
        targets.append((f"{st}__L2_pass", df[base_m & df["is_pass_official"].astype(bool)].copy()))
        targets.append((f"{st}__L2b_slot1", df[base_m & df["is_standalone_slot1"].astype(bool)].copy()))
    targets.append(("comb_278__slot1", df[df["sim_ok"].astype(bool) & df["net_ret"].notna() & df["is_v20_slot1"].astype(bool)].copy()))

    print(f"  Scanning {len(targets)} targets x {len(FACTOR_SPECS)} factors = {len(targets)*len(FACTOR_SPECS)} cells...")
    all_records = []
    bin_details = {}  # Only store detailed bins/yearly for top hits or all comb_278 + L2b_slot1 + significant hits

    for t_id, t_df in targets:
        t_recs = []
        for fcol, flayer, fcn, fkind in FACTOR_SPECS:
            rec, det = analyze_one_pair(t_df, fcol, flayer, fcn, fkind, t_id, rng)
            t_recs.append(rec)
            if det is not None and (
                t_id == "comb_278__slot1"
                or t_id.endswith("__L2_pass")
                or (not rec.get("insufficient") and (rec["p_min_raw"] is not None and rec["p_min_raw"] < 0.05))
            ):
                bin_details[f"{t_id}::{fcol}"] = det

        # Within-target BH-FDR across the ~60 factors
        valid_idx = [i for i, r in enumerate(t_recs) if not r.get("insufficient")]
        for pfield, qfield in [
            ("p_lin_cl", "q_within_lin"),
            ("kw_p", "q_within_kw"),
            ("p_perm_ext", "q_within_perm_ext"),
            ("p_min_raw", "q_within_min_raw"),
        ]:
            pvals = [t_recs[i][pfield] if t_recs[i].get(pfield) is not None else 1.0 for i in valid_idx]
            qvals = bh_fdr(pvals)
            for idx_pos, qv in zip(valid_idx, qvals):
                t_recs[idx_pos][qfield] = qv
        all_records.extend(t_recs)

    # Global BH-FDR across entire experiment matrix
    valid_g = [i for i, r in enumerate(all_records) if not r.get("insufficient")]
    for pfield, qfield in [
        ("p_lin_cl", "q_global_lin"),
        ("kw_p", "q_global_kw"),
        ("p_perm_ext", "q_global_perm_ext"),
    ]:
        pvals = [all_records[i][pfield] if all_records[i].get(pfield) is not None else 1.0 for i in valid_g]
        qvals = bh_fdr(pvals)
        for idx_pos, qv in zip(valid_g, qvals):
            all_records[idx_pos][qfield] = qv

    mat_df = pd.DataFrame(all_records)
    csv_path = f"{OUT_DIR}/rd034_factor_matrix_all6.csv"
    mat_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # Attribution Analysis A: L1_cand vs L2_pass vs L2b_slot1 & correlation with v20_score
    abs_rows = []
    rec_lu = {(r["target"], r["factor"]): r for r in all_records}
    for fcol, flayer, fcn, fkind in FACTOR_SPECS:
        # Check which strategies had significant signal in L1_cand or L2_pass or comb_278
        comb_r = rec_lu.get(("comb_278__slot1", fcol), {})
        strats_hit = []
        v20_corrs = []
        for st in STRAT_ORDER:
            c_rec = rec_lu.get((f"{st}__L1_cand", fcol), {})
            p_rec = rec_lu.get((f"{st}__L2_pass", fcol), {})
            s_rec = rec_lu.get((f"{st}__L2b_slot1", fcol), {})
            rv = c_rec.get("r_with_v20_score")
            pv = c_rec.get("p_with_v20_score")
            if rv is not None and pv is not None and pv < 0.05:
                v20_corrs.append(f"{st}:{rv:+.2f}")
            for lbl, r_obj in [("cand", c_rec), ("pass", p_rec), ("slot1", s_rec)]:
                if not r_obj.get("insufficient") and r_obj.get("p_min_raw", 1.0) < 0.01:
                    strats_hit.append(f"{st}({lbl}):r={r_obj.get('spearman_r')},p={r_obj.get('p_min_raw')}")
        abs_rows.append({
            "factor": fcol, "layer": flayer, "factor_cn": fcn,
            "comb_r": comb_r.get("spearman_r"), "comb_p_min": comb_r.get("p_min_raw"),
            "comb_q_within": comb_r.get("q_within_min_raw"),
            "comb_ext_pp": comb_r.get("ext_contrast_pp"),
            "comb_is_oos_same": comb_r.get("is_oos_same_sign"),
            "comb_yr_consist": comb_r.get("yr_consistent"),
            "absorbed_into_v20_score_in_cand": v20_corrs,
            "strong_hits_p_lt_001": strats_hit,
        })

    # Attribution Analysis B: V20.0 firing rates across regimes
    firing_table = build_v20_regime_firing_table(df, mkt_df)

    # Summarize survivors by layer & target (q_within_lin < 0.15 or q_within_perm_ext < 0.15 or q_within_kw < 0.15)
    survivors_within_fdr15 = [
        r for r in all_records
        if not r.get("insufficient")
        and (
            (r.get("q_within_lin", 1.0) <= 0.15)
            or (r.get("q_within_kw", 1.0) <= 0.15)
            or (r.get("q_within_perm_ext", 1.0) <= 0.15)
        )
    ]
    survivors_within_fdr15.sort(key=lambda x: min(x.get("q_within_lin", 1.0), x.get("q_within_kw", 1.0), x.get("q_within_perm_ext", 1.0)))

    survivors_global_fdr15 = [
        r for r in all_records
        if not r.get("insufficient")
        and (
            (r.get("q_global_lin", 1.0) <= 0.15)
            or (r.get("q_global_kw", 1.0) <= 0.15)
            or (r.get("q_global_perm_ext", 1.0) <= 0.15)
        )
    ]

    # Top IS-only signals in L2_pass / L1_cand / L2b_slot1 / comb_278 for Step 3 blind test
    is_top_cands = []
    for r in all_records:
        if r.get("insufficient"):
            continue
        if r.get("is_p") is not None and r["is_p"] < 0.05 and abs(r.get("is_r") or 0) >= 0.08:
            is_top_cands.append(r)

    audit = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 2),
            "n_targets": len(targets),
            "n_factors": len(FACTOR_SPECS),
            "n_cells": len(all_records),
            "n_perm": N_PERM,
            "n_within_fdr_15_survivors": len(survivors_within_fdr15),
            "n_global_fdr_15_survivors": len(survivors_global_fdr15),
        },
        "layer_summary": {
            ly: {
                "n_factors": sum(1 for _, l, _, _ in FACTOR_SPECS if l == ly),
                "within_fdr15_hits_slot1_or_comb": sum(1 for r in survivors_within_fdr15 if r["layer"] == ly and ("slot1" in r["target"])),
                "within_fdr15_hits_pass": sum(1 for r in survivors_within_fdr15 if r["layer"] == ly and ("L2_pass" in r["target"])),
                "within_fdr15_hits_cand": sum(1 for r in survivors_within_fdr15 if r["layer"] == ly and ("L1_cand" in r["target"])),
            }
            for ly in ("L1_市场", "L2_行业题材", "L3_个股")
        },
        "survivors_within_fdr15": survivors_within_fdr15,
        "survivors_global_fdr15": survivors_global_fdr15,
        "comb_278_all_factors": sorted(
            [r for r in all_records if r["target"] == "comb_278__slot1" and not r.get("insufficient")],
            key=lambda x: x.get("p_min_raw", 1.0),
        ),
        "v20_absorption_by_factor": abs_rows,
        "v20_regime_firing_table": firing_table,
        "bin_and_yearly_details": bin_details,
    }

    out_json = f"{OUT_DIR}/rd034_step2_scan_audit.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(sanitize_json(audit), f, ensure_ascii=False, indent=2)

    print(f"[DONE Step 2 in {time.time()-t0:.1f}s] Saved {csv_path} & {out_json}")
    print(f"  Within-target FDR<=0.15 hits: {len(survivors_within_fdr15)} | Global FDR<=0.15 hits: {len(survivors_global_fdr15)}")
    print("\n=== Top comb_278 factors (p_min_raw < 0.05) ===")
    for r in audit["comb_278_all_factors"][:15]:
        if r["p_min_raw"] < 0.10:
            print(f"  {r['layer']} | {r['factor']:22s} | r={r['spearman_r']} p_lin={r['p_lin_cl']} kw_p={r['kw_p']} ext={r['ext_contrast_pp']}pp({r['ext_contrast_label']}, p={r['p_perm_ext']}) q_w={r['q_within_min_raw']} | IS/OOS={r['is_r']}/{r['oos_r']} Y26={r['y26_r']} yrs={r['yr_consistent']}")
    print("\n=== Top L2_pass & L2b_slot1 & L1_cand Within-Target FDR<=0.15 Survivors ===")
    for r in survivors_within_fdr15[:25]:
        print(f"  {r['target']:16s} | {r['factor']:22s} | n={r['n_valid']:4d} | r={r['spearman_r']} p_lin={r['p_lin_cl']} ext={r['ext_contrast_pp']}pp p_ext={r['p_perm_ext']} q_lin={r['q_within_lin']} q_ext={r['q_within_perm_ext']} q_kw={r['q_within_kw']} | IS/OOS={r['is_r']}/{r['oos_r']} Y26={r['y26_r']} yrs={r['yr_consistent']} | v20_r={r['r_with_v20_score']}")


if __name__ == "__main__":
    main()
