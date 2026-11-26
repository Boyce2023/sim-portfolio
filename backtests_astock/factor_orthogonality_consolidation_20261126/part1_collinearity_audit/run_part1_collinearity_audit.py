#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part 1: Exhaustive Collinearity, VIF, Partial Contribution (OLS + Ridge + LOO),
Berkson Paradox Audit, and Hierarchical Clustering Compression across all 6 V20.0 Strategies.

Strictly read-only on production files & RD035/RD036/RD038 caches. Zero yfinance (D12).
Outputs under:
  sim-portfolio/backtests_astock/factor_orthogonality_consolidation_20261126/part1_collinearity_audit/
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.linear_model import Ridge, RidgeCV

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD036_OTHER5_DIR = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5"
RD035_WAVE1_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD038_CACHE_PKL = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126/_cache/rd038_master_cache.pkl"
OUT_DIR = f"{SIM}/backtests_astock/factor_orthogonality_consolidation_20261126/part1_collinearity_audit"
os.makedirs(OUT_DIR, exist_ok=True)

if RD036_OTHER5_DIR not in sys.path:
    sys.path.insert(0, RD036_OTHER5_DIR)

import _common_rd036 as cm  # noqa: E402

STRATS = ["1to2", "2to3", "3to4", "high", "pry", "20cm"]
TRD_DAYS_YEAR = 242.0

EXTRA_LABELS_1TO2 = {
    "s12_atom_mcap": ("1T_AUX_mcap", "总市值甜区(60至155亿+28/40至60亿+10/<35亿-20)", "+28/+10/-20", +1),
    "s12_atom_amt": ("1T_AUX_amt", "首板成交额甜区(2.2至15亿+18/<1.8亿-25)", "+18/-25/-10", +1),
    "s12_atom_dd20": ("1T_AUX_dd20", "前20日回撤深度(<=0.82+42/<=0.86+32/>0.95-40)", "+42/+32/+18/-40", +1),
    "s12_atom_pos20": ("1T_AUX_pos20", "前20日箱体位置(<=0.30+25/<=0.45+12/>0.75-35)", "+25/+12/-35", +1),
    "s12_atom_to": ("1T_AUX_to", "首板换手率甜区(<=9%+15/<=15%+8/>18%-25)", "+15/+8/-25", +1),
    "s12_atom_vr": ("1T_AUX_vr", "首板量比甜区(<=1.75+15/>2.3-15)", "+15/-15", +1),
    "s12_atom_xq_cold": ("1T_AUX_xq_cold", "雪球盘前冷门暗牌(<4帖)", "0(门控)", +1),
}


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return sanitize_json(obj.tolist())
    return obj


def load_factor_metadata() -> tuple[dict, dict]:
    cat_path = f"{RD035_WAVE1_DIR}/wave1a_factor_catalog_and_pit_audit.json"
    with open(cat_path, encoding="utf-8") as f:
        mc = json.load(f)["master_factor_catalog"]

    rd032_dir = f"{SIM}/backtests_astock2/rd032_6strat_decay_evolution_20261125"
    if rd032_dir not in sys.path:
        sys.path.insert(0, rd032_dir)
    import rd032_decay_audit as rd32_audit  # noqa: E402

    pref_map = {"1to2": "s12_", "2to3": "s23_", "3to4": "s34_", "high": "shigh_", "pry": "spry_", "20cm": "s20cm_"}
    meta = {}
    for st, items in rd32_audit.FACTOR_SPECS.items():
        pr = pref_map[st]
        for fid, col_name, sign, desc_cn, pts in items:
            full_col = f"{pr}{col_name}"
            meta[full_col] = {
                "factor_id": fid,
                "label_cn": desc_cn,
                "weight_desc": str(pts),
                "intended_sign": int(sign),
            }
    for c, (fid, desc_cn, pts, sign) in EXTRA_LABELS_1TO2.items():
        meta[c] = {
            "factor_id": fid,
            "label_cn": desc_cn,
            "weight_desc": pts,
            "intended_sign": int(sign),
        }
    return meta, mc


def describe_pair_mechanism(st: str, ca: str, cb: str, scope: str, rp_a: float, rp_p: float) -> str:
    """Provide concise Chinese physical/statistical mechanism for each correlated pair."""
    s = {ca, cb}
    if scope == "PASS_ONLY_BERKSON":
        return f"伯克森截断偏误(Berkson paradox): 全池近零相关(r={rp_a:+.2f})，仅因过线条件 sum(F)>=阈值 诱发负/假相关(过线r={rp_p:+.2f})"
    if s == {"s12_atom_dd20", "s12_atom_dd20_deep"}:
        return "rd036贡献矩阵Bug导致同源字段dd20<=0.86重复计分两遍(+42/+32)"
    if s <= {"s12_atom_dd20", "s12_atom_dd20_deep", "s12_atom_pos20", "s12_atom_clean_brk60"}:
        if "s12_atom_clean_brk60" in s:
            return "形态互斥机制: 60日平台突破处于高位，与深跌低位(dd20/pos20)互斥并替代其加分"
        return "同源位置维度重复计分: 20日回撤深度(dd20)与20日箱体位置(pos20)高度同源"
    if s == {"s12_atom_amt", "s12_atom_mcap"}:
        return "体量流动性同源: 成交额甜区与总市值甜区正相关"
    if s == {"s12_atom_mkt_open_top3", "s12_atom_open_sweet"}:
        return "竞价高开强度重叠: 4%~8.2%高开甜区自然更易排入全场高开前三"
    if s == {"s34_af_07", "s34_af_14"}:
        return "同源字段分段重复计分: 同一三板换手率(prev_to)同时拆为[9.5,28]加3分与越界扣10分"
    if s == {"s34_af_06", "s34_af_18"}:
        return "同源字段分段重复计分: 同一前日三板跌停家数(prev_3b_dt_cnt)拆为0家加3分与>=2家扣4分"
    if s == {"s34_af_04", "s34_af_17"}:
        return "同源字段分段重复计分: 同一三板拉萨席位家数(lhb_lh_cnt)拆为0家加4分与>=3家扣5分"
    if s == {"shigh_af_d1_lh_hvy", "shigh_af_lh1_zero"}:
        return "同源拉萨席位重复计分: 首阴零拉萨(+6/-10)与首阴拉萨占比过重(-10)高度重合"
    if s == {"shigh_af_d1_dip6", "shigh_af_d1_op_neg"}:
        return "盘中路径因果共生: 首阴绿开承接更易探底至-6%以下形成大长腿"
    if s == {"shigh_af_d1_net_pos", "shigh_af_qu_in"} or s == {"shigh_af_d1_net_pos", "shigh_af_inst_pen"}:
        return "龙虎榜资金席位结构共振: 机构/量化参与同日龙虎榜净买入分布"
    if s == {"shigh_af_d0_tight", "shigh_af_d1_dip6"} or s == {"shigh_af_d0_tight", "shigh_af_d1_op_neg"} or s == {"shigh_af_d0_early", "shigh_af_d0_tight"}:
        return "封板强度与次日分歧反向耦合: D0秒板紧封后次日多高开而少见绿开深水洗盘"
    if s == {"shigh_af_d0_early", "shigh_af_d1_op_neg"}:
        return "高板秒封次日分歧绿开频率较高(情绪预期差)"
    if s == {"shigh_af_pelo_cool", "shigh_af_turn_b4"}:
        return "连板周期阶段反向: 换手4板以上老龙头往往处于题材过热或主线独大阶段"
    if s == {"spry_af_is_yang", "spry_af_mkt_zt12"}:
        return "大盘强修复市场温度共振: 早盘竞价涨停>=12家时，撬板资金更易收出真阳"
    if s == {"spry_af_bias10", "spry_af_ma20_22"} or ("spry_af_down4" in s and ("spry_af_bias10" in s or "spry_af_ma20_22" in s)):
        return "超跌深度同源堆叠: 10日乖离、20日乖离与连阴4天均衡量同一极度超跌维度"
    if s == {"s20cm_F02_rfm_le20", "s20cm_F05_seal_ratio_ge10_pen"}:
        return "自由流值与封成比物理分母反相关: 盘子<=20亿的小票封单额占成交额比例更易>=10%(r=-0.252)"
    if rp_a < 0:
        return "交易条件反向耦合或结构互斥(物理负相关)"
    return "同维度市场情绪/资金特征共变(物理正相关)"


def compute_corr_vif_spectral(X: np.ndarray, cols: list[str]) -> dict:
    n, p = X.shape
    sd = np.std(X, axis=0)
    act_mask = sd > 1e-12
    act_idx = np.where(act_mask)[0]
    act_cols = [cols[i] for i in act_idx]
    p_act = len(act_cols)
    if p_act < 2 or n < 5:
        return {
            "n": int(n), "p_total": int(p), "p_active": int(p_act),
            "act_cols": act_cols, "vifs": {}, "R_pearson": None, "R_spearman": None,
        }

    Xa = X[:, act_idx]
    R_p = np.corrcoef(Xa, rowvar=False)
    R_p = np.nan_to_num(R_p, nan=0.0)
    np.fill_diagonal(R_p, 1.0)

    R_s, _ = stats.spearmanr(Xa, axis=0)
    if np.ndim(R_s) == 0:
        R_s = np.array([[1.0]])
    R_s = np.nan_to_num(R_s, nan=0.0)
    np.fill_diagonal(R_s, 1.0)

    evals = np.linalg.eigvalsh(R_p)
    evals = np.sort(np.maximum(evals, 0.0))[::-1]
    ev_sum = float(evals.sum())
    ev_sq_sum = float((evals ** 2).sum())
    eff_pr = (ev_sum ** 2) / ev_sq_sum if ev_sq_sum > 0 else 0.0
    ev_pos = evals[evals > 1e-12]
    probs = ev_pos / ev_pos.sum()
    eff_ent = float(np.exp(-np.sum(probs * np.log(probs)))) if len(probs) else 0.0
    kaiser_ge1 = int(np.sum(evals >= 1.0))
    cum_var = np.cumsum(evals) / max(ev_sum, 1e-12)
    dim_90 = int(np.searchsorted(cum_var, 0.90) + 1)

    lmin = float(evals[-1])
    lmax = float(evals[0])
    cond_R = float(lmax / lmin) if lmin > 1e-10 else float("inf")
    cond_X = float(math.sqrt(cond_R)) if math.isfinite(cond_R) else float("inf")

    Xs = (Xa - Xa.mean(axis=0)) / sd[act_idx]
    vifs = {}
    for j, c in enumerate(act_cols):
        y_j = Xs[:, j]
        X_oth = np.delete(Xs, j, axis=1)
        coef, *_ = np.linalg.lstsq(X_oth, y_j, rcond=None)
        resid = y_j - X_oth @ coef
        tss = float(np.dot(y_j, y_j))
        rss = float(np.dot(resid, resid))
        r2_j = 1.0 - rss / max(tss, 1e-12)
        vif_j = (1.0 / (1.0 - r2_j)) if (1.0 - r2_j) > 1e-6 else float("inf")
        vifs[c] = float(vif_j)

    off_p = np.abs(R_p[~np.eye(p_act, dtype=bool)])
    return {
        "n": int(n),
        "p_total": int(p),
        "p_active": int(p_act),
        "act_cols": act_cols,
        "R_pearson": R_p,
        "R_spearman": R_s,
        "evals": evals.tolist(),
        "effective_factors_pr": float(eff_pr),
        "effective_factors_entropy": float(eff_ent),
        "kaiser_dim_ge1": kaiser_ge1,
        "pca_90pct_dim": dim_90,
        "cond_num_X_std": cond_X,
        "cond_num_R": cond_R,
        "vifs": vifs,
        "max_vif": float(max(vifs.values())) if vifs else 0.0,
        "n_vif_ge2": int(sum(1 for v in vifs.values() if (not math.isfinite(v)) or v >= 2.0)),
        "mean_abs_r": float(off_p.mean()) if len(off_p) else 0.0,
        "mean_signed_r": float(R_p[~np.eye(p_act, dtype=bool)].mean()) if p_act > 1 else 0.0,
        "max_abs_r": float(off_p.max()) if len(off_p) else 0.0,
        "min_signed_r": float(R_p[~np.eye(p_act, dtype=bool)].min()) if p_act > 1 else 0.0,
        "max_signed_r": float(R_p[~np.eye(p_act, dtype=bool)].max()) if p_act > 1 else 0.0,
    }


def _cluster_uni_t(x: np.ndarray, y: np.ndarray, day_ids: np.ndarray) -> tuple[float, float]:
    n = len(y)
    if n < 8 or np.std(x) < 1e-12 or np.std(y) < 1e-12:
        return np.nan, np.nan
    dx = x - np.mean(x)
    dy = y - np.mean(y)
    sxx = float(np.dot(dx, dx))
    beta = float(np.dot(dx, dy)) / sxx
    eps = dy - beta * dx
    s2 = float(np.dot(eps, eps)) / max(1, n - 2)
    t_ols = beta / math.sqrt(max(1e-18, s2 / sxx))
    _, g_inv = np.unique(day_ids, return_inverse=True)
    G = int(g_inv.max()) + 1
    if G < 4:
        return float(t_ols), float(t_ols)
    sg = np.bincount(g_inv, weights=dx * eps, minlength=G)
    adj = (G / max(1, G - 1)) * ((n - 1) / max(1, n - 2))
    var_cl = adj * float(np.dot(sg, sg)) / (sxx * sxx)
    t_cl = beta / math.sqrt(max(1e-18, var_cl))
    return float(t_ols), float(t_cl)


def run_window_regressions(X: np.ndarray, y: np.ndarray, day_ids: np.ndarray, cols: list[str], mask: np.ndarray) -> dict:
    idx = np.where(mask)[0]
    n = len(idx)
    if n < 10:
        return {"n": int(n), "p_active": 0, "factors": {}}

    Xw = X[idx]
    yw = y[idx]
    dw = day_ids[idx]
    y_sd = float(np.std(yw))
    if y_sd < 1e-12:
        return {"n": int(n), "p_active": 0, "factors": {}}
    ys = (yw - np.mean(yw)) / y_sd

    sd = np.std(Xw, axis=0)
    act_mask = sd > 1e-12
    act_idx = np.where(act_mask)[0]
    act_cols = [cols[i] for i in act_idx]
    p_act = len(act_cols)
    if p_act == 0:
        return {"n": int(n), "p_active": 0, "factors": {}}

    Xs = (Xw[:, act_idx] - Xw[:, act_idx].mean(axis=0)) / sd[act_idx]

    Z = np.column_stack([np.ones(n), Xs])
    XtX = Z.T @ Z
    inv_XtX = np.linalg.pinv(XtX)
    beta_ols = inv_XtX @ (Z.T @ ys)
    eps = ys - Z @ beta_ols
    df_res = max(1, n - p_act - 1)
    s2 = float(np.dot(eps, eps)) / df_res
    se_ols = np.sqrt(np.maximum(s2 * np.diag(inv_XtX), 1e-18))

    _, g_inv = np.unique(dw, return_inverse=True)
    G = int(g_inv.max()) + 1
    Ze = Z * eps[:, None]
    Sg = np.zeros((G, p_act + 1))
    np.add.at(Sg, g_inv, Ze)
    meat = Sg.T @ Sg
    adj = (G / max(1, G - 1)) * ((n - 1) / df_res)
    vcov_cl = adj * (inv_XtX @ meat @ inv_XtX)
    se_cl = np.sqrt(np.maximum(np.diag(vcov_cl), 1e-18))

    alpha_prop = max(2.0, 0.20 * n)
    rdg_prop = Ridge(alpha=alpha_prop, fit_intercept=False).fit(Xs, ys)
    rdg_cv = RidgeCV(alphas=np.logspace(-0.5, 3.5, 41), fit_intercept=False).fit(Xs, ys)

    out_factors = {}
    for j, c in enumerate(act_cols):
        xv = Xw[:, act_idx[j]]
        ic_sp, p_sp = stats.spearmanr(xv, yw)
        r_pe, _ = stats.pearsonr(xv, yw)
        ut_ols, ut_cl = _cluster_uni_t(xv, yw, dw)
        hi_m = xv > np.median(xv) if np.unique(xv).size > 2 else (xv == np.max(xv))
        lo_m = ~hi_m
        edge_pp = (float(yw[hi_m].mean() - yw[lo_m].mean()) * 100.0) if (hi_m.any() and lo_m.any()) else np.nan
        wr_edge_pp = (float((yw[hi_m] > 0).mean() - (yw[lo_m] > 0).mean()) * 100.0) if (hi_m.any() and lo_m.any()) else np.nan
        b_o = float(beta_ols[j + 1])
        t_o = b_o / float(se_ols[j + 1])
        t_c = b_o / float(se_cl[j + 1])
        out_factors[c] = {
            "spearman_ic": float(ic_sp),
            "spearman_p": float(p_sp),
            "pearson_r": float(r_pe),
            "uni_t_ols": float(ut_ols),
            "uni_t_cl": float(ut_cl),
            "uni_mean_edge_pp": float(edge_pp) if not np.isnan(edge_pp) else np.nan,
            "uni_wr_edge_pp": float(wr_edge_pp) if not np.isnan(wr_edge_pp) else np.nan,
            "ols_beta": b_o,
            "ols_t_ols": float(t_o),
            "ols_t_cl": float(t_c),
            "ridge_beta": float(rdg_prop.coef_[j]),
            "ridge_cv_beta": float(rdg_cv.coef_[j]),
        }

    return {
        "n": int(n),
        "n_days": int(G),
        "p_active": int(p_act),
        "df_res": int(df_res),
        "ridge_alpha_prop": float(alpha_prop),
        "ridge_cv_alpha": float(rdg_cv.alpha_),
        "factors": out_factors,
    }


def eval_5y_slot_windows(df: pd.DataFrame, st: str, score_vec: np.ndarray, cal_5y: list[str]) -> dict:
    _, sl = cm.sim_strategy(st, df, score_vec, wf_only=False)
    sl5 = sl[sl["buy_date"].between(cal_5y[0], cal_5y[-1])].copy()
    T5 = len(cal_5y)
    idx_is = np.array([d <= "2024-12-31" for d in cal_5y], dtype=bool)
    idx_oos = np.array([d >= "2025-01-01" for d in cal_5y], dtype=bool)

    if sl5.empty:
        empty = {"n": 0, "nav": 1.0, "sharpe": 0.0, "wr_pct": 0.0, "mtm_diff": 0.0}
        return {"FULL_5Y": empty, "IS_5Y": empty, "OOS": empty}

    sl5["mtm_5y_030"] = [
        cm.scale_mtm_segs(s, r20, r30)
        for s, r20, r30 in zip(sl5["mtm_5y_020"], sl5["net_ret_020"], sl5["net_ret_030"])
    ]
    dr5, diff5 = cm.build_exact_dr(sl5, T5, mtm_col="mtm_5y_030", ret_col="net_ret_030")

    def _win(sl_sub, dr_sub):
        if sl_sub.empty:
            return {"n": 0, "nav": 1.0, "sharpe": 0.0, "wr_pct": 0.0}
        rr = sl_sub["net_ret_030"].to_numpy(float)
        sd = float(np.std(dr_sub, ddof=1)) if len(dr_sub) > 1 else 0.0
        sh = float(np.mean(dr_sub) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
        return {
            "n": int(len(rr)),
            "nav": float(np.prod(1.0 + rr)),
            "sharpe": float(sh),
            "wr_pct": float((rr > 0).mean() * 100.0),
        }

    res_full = _win(sl5, dr5)
    res_full["mtm_diff"] = float(diff5)
    res_is = _win(sl5[sl5["exit_date"] <= "2024-12-31"], dr5[idx_is])
    res_oos = _win(sl5[sl5["buy_date"] >= "2025-01-01"], dr5[idx_oos])
    return {"FULL_5Y": res_full, "IS_5Y": res_is, "OOS": res_oos}


def _leader_score(row: dict) -> float:
    """Asymmetric tie-broken leadership score within collinear pairs."""
    rf = row["ridge_beta_full"] if row["ridge_beta_full"] is not None else 0.0
    ris = row["ridge_beta_is"] if row["ridge_beta_is"] is not None else 0.0
    roos = row["ridge_beta_oos"] if row["ridge_beta_oos"] is not None else 0.0
    tf = row["ols_t_cl_full"] if row["ols_t_cl_full"] is not None else 0.0
    icf = row["ic_full"] if row["ic_full"] is not None else 0.0
    cnt = row["trigger_count"]
    # Reward positive IS & OOS balance + full t + trigger coverage (rare 2-row flags should yield to 56-row partner)
    both_pos = 0.05 if (ris > 0 and roos > 0) else 0.0
    cov_bonus = 0.03 * min(cnt / 30.0, 1.0)
    return 0.45 * rf + 0.25 * min(ris, roos) + both_pos + 0.015 * tf + 0.10 * icf + cov_bonus


def classify_factor(row: dict) -> tuple[str, str]:
    col = row["factor_col"]
    if col == "s12_atom_dd20_deep":
        return "2_Collinear_Redundant", "rd036贡献矩阵把dd20<=0.86与s12_atom_dd20重复计分(r=+0.915),应去重合并"

    r_f = row["ridge_beta_full"] or 0.0
    r_is = row["ridge_beta_is"]
    r_oos = row["ridge_beta_oos"]
    t_f = row["ols_t_cl_full"] or 0.0
    t_oos = row["ols_t_cl_oos"]
    ic_is = row["ic_is"]
    ic_oos = row["ic_oos"]
    max_r = row["max_abs_r_all"]
    vif = row["vif_all"]
    is_dominated = row.get("is_dominated_in_cluster", False)

    # 1. Poison / Harmful: IS & OOS partial Ridge both negative, or severe OOS poison
    if (r_is is not None and r_oos is not None and r_is < -0.002 and r_oos < -0.002 and r_f < -0.005):
        return "4_Poison_Harmful", f"IS与OOS多元偏Ridge双负(IS={r_is:+.3f},OOS={r_oos:+.3f},全期t={t_f:+.2f})"
    if (r_oos is not None and r_oos <= -0.08 and (t_oos is not None and t_oos <= -1.5) and (r_is is None or r_is <= 0.015)):
        return "4_Poison_Harmful", f"样本外严重反效(OOS Ridge={r_oos:+.3f},t={t_oos:+.2f}),IS亦无正边际({r_is:+.3f})"
    if (ic_is is not None and ic_oos is not None and ic_is < -0.01 and ic_oos < -0.01 and r_f < -0.02):
        return "4_Poison_Harmful", f"IS与OOS单因子IC与偏贡献双负(IC_IS={ic_is:+.3f},IC_OOS={ic_oos:+.3f})"

    # 2. Collinear Redundant: dominated member in a >=0.30 pair or VIF>=2 cluster
    if (max_r >= 0.30 or (vif is not None and vif >= 2.0)) and is_dominated:
        return "2_Collinear_Redundant", f"共线性簇从属因子(max|r|={max_r:.2f},VIF={vif:.2f}),控制兄弟后被吸收/主导(Ridge={r_f:+.3f})"

    # 3. IS-only that decayed to <=0 in OOS (check BEFORE Core override so F06 & F09 are consistent)
    if (r_is is not None and r_oos is not None and r_is >= 0.05 and r_oos <= 0.0):
        return "3_Deadweight_Noise", f"仅IS有效而OOS完全衰减归零(IS Ridge={r_is:+.3f}->OOS={r_oos:+.3f},全期t={t_f:+.2f})"

    # 4. Core Pillar: consistent positive partial contribution in IS & OOS (or strong full + rare OOS n/a)
    if (r_is is not None and r_oos is not None and r_is > 0.008 and r_oos > 0.008 and r_f >= 0.032 and t_f >= 0.90):
        return "1_Core_Pillar", f"IS与OOS偏Ridge双正且稳健(IS={r_is:+.3f},OOS={r_oos:+.3f},全期t={t_f:+.2f})"
    if (r_is is not None and r_oos is not None and r_is > 0.008 and r_oos > 0.008 and r_f >= 0.025 and t_f >= 0.40):
        # Borderline weak t (e.g. 20cm F03 t=+0.81 or pry vr15 t=+0.45): check if t_f < 0.85 -> weak/deadweight?
        if t_f < 0.85 and r_f < 0.04:
            return "3_Deadweight_Noise", f"偏贡献方向虽正但全期统计量极弱(Ridge={r_f:+.3f},t={t_f:+.2f})"
        return "1_Core_Pillar", f"IS与OOS偏Ridge双正(IS={r_is:+.3f},OOS={r_oos:+.3f},全期t={t_f:+.2f})"
    if (r_f >= 0.055 and t_f >= 1.5 and (r_is is None or r_is > 0) and (r_oos is None or r_oos > 0.0)):
        return "1_Core_Pillar", f"全期多元偏贡献显著为正(Ridge={r_f:+.3f},t={t_f:+.2f}),独立增厚有效"

    # 5. Collinear cluster member whose partial beta is weak
    if (max_r >= 0.35 or (vif is not None and vif >= 2.0)) and r_f < 0.04:
        return "2_Collinear_Redundant", f"高共线簇内偏贡献弱(max|r|={max_r:.2f},VIF={vif:.2f},Ridge={r_f:+.3f}),适合与兄弟合并"

    return "3_Deadweight_Noise", f"单看/控制其余因子后偏贡献均近零(全期Ridge={r_f:+.3f},t={t_f:+.2f},IS={r_is:+.3f},OOS={r_oos:+.3f})"


def run_hierarchical_clustering(X: np.ndarray, cols: list[str], diag_map: dict, meta: dict, strat: str) -> dict:
    sd = np.std(X, axis=0)
    act_idx = np.where(sd > 1e-12)[0]
    act_cols = [cols[i] for i in act_idx]
    Xa = X[:, act_idx]
    R = np.corrcoef(Xa, rowvar=False)
    R = np.nan_to_num(R, nan=0.0)
    np.fill_diagonal(R, 1.0)
    D = np.clip(1.0 - np.abs(R), 0.0, 1.0)
    np.fill_diagonal(D, 0.0)
    Z = linkage(squareform(D, checks=False), method="ward")

    sweeps = {}
    best_k = None
    best_score = -1e9
    p_act = len(act_cols)
    for k in (3, 4, 5, 6):
        if k > p_act:
            continue
        lbls = fcluster(Z, t=k, criterion="maxclust")
        clusters = {}
        sums = []
        for cid in range(1, k + 1):
            c_idx = np.where(lbls == cid)[0]
            clusters[cid] = [act_cols[i] for i in c_idx]
            Xs = (Xa[:, c_idx] - Xa[:, c_idx].mean(0)) / np.maximum(Xa[:, c_idx].std(0), 1e-12)
            sums.append(Xs.sum(axis=1))
        S = np.column_stack(sums)
        CS = np.corrcoef(S, rowvar=False)
        off = np.abs(CS[~np.eye(k, dtype=bool)])
        max_inter = float(off.max()) if len(off) else 0.0
        mean_inter = float(off.mean()) if len(off) else 0.0
        sizes = [len(v) for v in clusters.values()]
        target_k = 4 if p_act <= 10 else 5
        # Penalize singletons AND oversized catch-all clusters (>48% of factors)
        oversize_pen = 0.25 * max(0.0, max(sizes) / p_act - 0.48)
        bal_pen = 0.05 * sum(1 for s in sizes if s == 1) + 0.03 * abs(k - target_k) + oversize_pen
        sc = -mean_inter - 0.25 * max_inter - bal_pen
        sweeps[str(k)] = {
            "k": k,
            "sizes": sizes,
            "max_inter_abs_r": round(max_inter, 4),
            "mean_inter_abs_r": round(mean_inter, 4),
            "clusters": clusters,
            "score": round(sc, 4),
        }
        if sc > best_score:
            best_score = sc
            best_k = k

    chosen = sweeps[str(best_k)]
    pillars = []
    col_to_pillar = {}
    for cid, mems in chosen["clusters"].items():
        mems_sorted = sorted(mems, key=lambda c: diag_map.get(c, {}).get("ridge_beta_full", 0.0) or -9.0, reverse=True)
        keep_core = [c for c in mems_sorted if diag_map.get(c, {}).get("factor_class") == "1_Core_Pillar"]
        merge_red = [c for c in mems_sorted if diag_map.get(c, {}).get("factor_class") == "2_Collinear_Redundant"]
        drop_dead = [c for c in mems_sorted if diag_map.get(c, {}).get("factor_class") == "3_Deadweight_Noise"]
        drop_pois = [c for c in mems_sorted if diag_map.get(c, {}).get("factor_class") == "4_Poison_Harmful"]

        rep_pool = keep_core if keep_core else [c for c in mems_sorted if c not in drop_pois]
        if not rep_pool:
            rep_pool = mems_sorted
        rep_names = [meta.get(c, {}).get("label_cn", c).split("(")[0][:10] for c in rep_pool[:2]]
        pname = f"支柱{cid}: " + " / ".join(rep_names)

        m_idx = [act_cols.index(c) for c in mems]
        if len(m_idx) > 1:
            sub_R = np.abs(R[np.ix_(m_idx, m_idx)])
            intra_max = float(sub_R[~np.eye(len(m_idx), dtype=bool)].max())
        else:
            intra_max = 0.0

        pillars.append({
            "pillar_id": f"{strat}_P{cid}",
            "pillar_name": pname,
            "n_raw_members": len(mems),
            "intra_cluster_max_abs_r": round(intra_max, 4),
            "members": mems_sorted,
            "retain_core": keep_core,
            "merge_collinear": merge_red,
            "drop_deadweight": drop_dead,
            "drop_poison": drop_pois,
            "recommended_surviving_count": len(keep_core) + (1 if merge_red and not keep_core else 0),
        })
        for c in mems:
            fc = diag_map.get(c, {}).get("factor_class", "")
            if fc == "4_Poison_Harmful":
                act = "DELETE_POISON"
            elif fc == "3_Deadweight_Noise":
                act = "DROP_DEADWEIGHT"
            elif fc == "2_Collinear_Redundant":
                act = "MERGE_INTO_PILLAR_OR_KEEP_LEADER"
            else:
                act = "KEEP_CORE_PILLAR"
            col_to_pillar[c] = (f"{strat}_P{cid}", pname, act)

    return {
        "recommended_k": int(best_k),
        "max_inter_pillar_abs_r": chosen["max_inter_abs_r"],
        "mean_inter_pillar_abs_r": chosen["mean_inter_abs_r"],
        "sweeps_k3_to_k6": sweeps,
        "pillars": pillars,
        "col_to_pillar": col_to_pillar,
    }


def main():
    t0 = time.time()
    print("[Part 1] Loading read-only bundles & verifying parity ...")
    with open(f"{RD036_OTHER5_DIR}/_cache/rd036_other5_bundle.pkl", "rb") as f:
        bundle = pickle.load(f)
    pq_master = pd.read_parquet(f"{RD035_WAVE1_DIR}/pools_6strat_master_newfactors_pit.parquet")
    with open(RD038_CACHE_PKL, "rb") as f:
        rd038 = pickle.load(f)

    meta, _ = load_factor_metadata()
    cal_5y = bundle["cal_5y"]

    for st in STRATS:
        db = bundle["pools"][st]
        dp = pq_master[pq_master["strategy"] == st]
        d38 = rd038["pools_ext"][st]
        assert len(db) == len(dp) == len(d38), f"Row count mismatch for {st}"
        assert np.nanmax(np.abs(db["orig_score"].to_numpy(float) - dp["orig_score"].to_numpy(float))) < 1e-4
        assert np.nanmax(np.abs(db["net_ret_020"].to_numpy(float) - dp["net_ret"].to_numpy(float))) < 1e-5
    del pq_master, rd038

    audit_json = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sign_convention": "All factor values in regressions & ICs are in scorecard-point space (positive = scorecard awards/retains points, negative = penalty triggered). Positive IC / positive partial beta / positive t ALWAYS indicates the factor adds return in its designed direction.",
        "score_reconstruction_check": {},
        "strategy_summary": {},
        "1to2_supplement_audit": {},
    }

    all_diag_rows = []
    all_pair_rows = []

    for st in STRATS:
        t_st = time.time()
        df = bundle["pools"][st]
        if st == "20cm":
            cols = sorted([c for c in df.columns if c.startswith("s20cm_F")])
            X_raw = df[cols].fillna(0.0).to_numpy(float)
            intercept = 70.0
        else:
            cols = list(bundle["atom_info"][st]["cols"])
            X_raw = bundle["atom_info"][st]["contrib_mat"].copy()
            intercept = cm.BASE_INTERCEPTS.get(st, 0.0)

        recon = intercept + X_raw.sum(axis=1)
        orig_sc = df["orig_score"].to_numpy(float)
        max_abs_diff = float(np.nanmax(np.abs(recon - orig_sc)))
        r2_orig = float(np.corrcoef(recon, orig_sc)[0, 1] ** 2) if np.std(recon) > 0 else 0.0
        audit_json["score_reconstruction_check"][st] = {
            "base_intercept": float(intercept),
            "n_native_factors": len(cols),
            "max_abs_diff_vs_orig_score": round(max_abs_diff, 6),
            "r2_vs_orig_score": round(r2_orig, 6),
        }

        if st == "1to2":
            keep_clean_idx = [i for i, c in enumerate(cols) if c != "s12_atom_dd20_deep"]
            cols_clean = [cols[i] for i in keep_clean_idx]
            X_clean = X_raw[:, keep_clean_idx].copy()
            X_clean[:, cols_clean.index("s12_atom_xq_cold")] = df["s12_atom_xq_cold"].fillna(1.0).to_numpy(float)
            spec_all_raw = compute_corr_vif_spectral(X_raw, cols)
            spec_pass_raw = compute_corr_vif_spectral(X_raw[df["is_pass_official"].to_numpy(bool)], cols)
            spec_all = compute_corr_vif_spectral(X_clean, cols_clean)
            spec_pass = compute_corr_vif_spectral(X_clean[df["is_pass_official"].to_numpy(bool)], cols_clean)
        else:
            cols_clean = cols
            X_clean = X_raw
            spec_all = compute_corr_vif_spectral(X_raw, cols)
            spec_pass = compute_corr_vif_spectral(X_raw[df["is_pass_official"].to_numpy(bool)], cols)
            spec_all_raw = spec_all
            spec_pass_raw = spec_pass

        act_cols_r = spec_all_raw["act_cols"]
        Rp_all = spec_all_raw["R_pearson"]
        Rs_all = spec_all_raw["R_spearman"]
        act_cols_p = spec_pass_raw["act_cols"]
        Rp_pass = spec_pass_raw["R_pearson"]
        Rs_pass = spec_pass_raw["R_spearman"]
        p_idx_map = {c: i for i, c in enumerate(act_cols_p)}

        high_pairs_030 = []
        for i in range(len(act_cols_r)):
            for j in range(i + 1, len(act_cols_r)):
                ca, cb = act_cols_r[i], act_cols_r[j]
                rp_a = float(Rp_all[i, j])
                rs_a = float(Rs_all[i, j])
                if ca in p_idx_map and cb in p_idx_map:
                    pi, pj = p_idx_map[ca], p_idx_map[cb]
                    rp_p = float(Rp_pass[pi, pj])
                    rs_p = float(Rs_pass[pi, pj])
                else:
                    rp_p, rs_p = np.nan, np.nan
                max_a = max(abs(rp_a), abs(rs_a))
                max_p = max(abs(rp_p), abs(rs_p)) if not np.isnan(rp_p) else 0.0
                if max_a >= 0.25 or max_p >= 0.30:
                    if max_a >= 0.25 and max_p >= 0.25:
                        scope = "BOTH"
                    elif max_a >= 0.25:
                        scope = "ALL_ONLY"
                    else:
                        scope = "PASS_ONLY_BERKSON"
                    la = meta.get(ca, {}).get("label_cn", ca)
                    lb = meta.get(cb, {}).get("label_cn", cb)
                    mech = describe_pair_mechanism(st, ca, cb, scope, rp_a, rp_p if not np.isnan(rp_p) else rp_a)
                    pair_row = {
                        "strategy": st,
                        "factor_a": ca,
                        "label_a": la,
                        "factor_b": cb,
                        "label_b": lb,
                        "r_pearson_all": round(rp_a, 4),
                        "r_spearman_all": round(rs_a, 4),
                        "r_pearson_pass": round(rp_p, 4) if not np.isnan(rp_p) else None,
                        "r_spearman_pass": round(rs_p, 4) if not np.isnan(rs_p) else None,
                        "berkson_delta_r": round(rp_p - rp_a, 4) if not np.isnan(rp_p) else None,
                        "flag_ge_030_all": bool(abs(rp_a) >= 0.30 or abs(rs_a) >= 0.30),
                        "source_scope": scope,
                        "physical_mechanism": mech,
                    }
                    all_pair_rows.append(pair_row)
                    if abs(rp_a) >= 0.30 or abs(rs_a) >= 0.30:
                        high_pairs_030.append(pair_row)
        high_pairs_030.sort(key=lambda d: -max(abs(d["r_pearson_all"]), abs(d["r_spearman_all"])))

        valid = df["can_buy_hygiene"].to_numpy(bool) & df["net_ret_030"].notna().to_numpy(bool)
        is_m = valid & (df["exit_date"].to_numpy(str) != "") & (df["exit_date"].to_numpy(str) <= "2024-12-31")
        oos_m = valid & (df["buy_date"].to_numpy(str) >= "2025-01-01")
        pass_m = valid & (df["is_pass_official"].to_numpy(int) == 1)

        y = df["net_ret_030"].fillna(0.0).to_numpy(float)
        dids = pd.factorize(df["buy_date"])[0]

        reg_full = run_window_regressions(X_clean, y, dids, cols_clean, valid)
        reg_is = run_window_regressions(X_clean, y, dids, cols_clean, is_m)
        reg_oos = run_window_regressions(X_clean, y, dids, cols_clean, oos_m)
        reg_pass_f = run_window_regressions(X_clean, y, dids, cols_clean, pass_m)
        reg_pass_is = run_window_regressions(X_clean, y, dids, cols_clean, pass_m & is_m)
        reg_pass_oos = run_window_regressions(X_clean, y, dids, cols_clean, pass_m & oos_m)

        base_sim = eval_5y_slot_windows(df, st, orig_sc, cal_5y)
        b_full_nav = base_sim["FULL_5Y"]["nav"]
        b_full_sh = base_sim["FULL_5Y"]["sharpe"]
        b_is_sh = base_sim["IS_5Y"]["sharpe"]
        b_oos_sh = base_sim["OOS"]["sharpe"]

        loo_res = {}
        for j, c in enumerate(cols):
            pts_j = X_raw[:, j]
            if np.std(pts_j) < 1e-12:
                loo_res[c] = {
                    "raw_n": base_sim["FULL_5Y"]["n"], "raw_d_nav_mult": 1.0,
                    "raw_d_sh_full": 0.0, "raw_d_sh_is": 0.0, "raw_d_sh_oos": 0.0,
                    "ctr_n": base_sim["FULL_5Y"]["n"], "ctr_d_nav_mult": 1.0,
                    "ctr_d_sh_full": 0.0, "ctr_d_sh_is": 0.0, "ctr_d_sh_oos": 0.0,
                }
                continue
            sim_raw = eval_5y_slot_windows(df, st, orig_sc - pts_j, cal_5y)
            pts_ctr = pts_j - float(np.mean(pts_j))
            sim_ctr = eval_5y_slot_windows(df, st, orig_sc - pts_ctr, cal_5y)
            loo_res[c] = {
                "raw_n": sim_raw["FULL_5Y"]["n"],
                "raw_d_nav_mult": sim_raw["FULL_5Y"]["nav"] / max(1e-9, b_full_nav),
                "raw_d_sh_full": sim_raw["FULL_5Y"]["sharpe"] - b_full_sh,
                "raw_d_sh_is": sim_raw["IS_5Y"]["sharpe"] - b_is_sh,
                "raw_d_sh_oos": sim_raw["OOS"]["sharpe"] - b_oos_sh,
                "ctr_n": sim_ctr["FULL_5Y"]["n"],
                "ctr_d_nav_mult": sim_ctr["FULL_5Y"]["nav"] / max(1e-9, b_full_nav),
                "ctr_d_sh_full": sim_ctr["FULL_5Y"]["sharpe"] - b_full_sh,
                "ctr_d_sh_is": sim_ctr["IS_5Y"]["sharpe"] - b_is_sh,
                "ctr_d_sh_oos": sim_ctr["OOS"]["sharpe"] - b_oos_sh,
            }

        act_c = spec_all["act_cols"]
        Rp_c = spec_all["R_pearson"]
        idx_c_map = {c: i for i, c in enumerate(act_c)}

        temp_rows = {}
        for j, c in enumerate(cols):
            if c == "s12_atom_dd20_deep":
                v_all = spec_all_raw["vifs"].get(c, np.nan)
                v_pass = spec_pass_raw["vifs"].get(c, np.nan)
                max_r_a = 0.9151
                partner = "s12_atom_dd20"
                max_r_p = 0.9524
            elif c in idx_c_map:
                ci = idx_c_map[c]
                row_r = np.abs(Rp_c[ci]).copy()
                row_r[ci] = -1.0
                pj = int(np.argmax(row_r))
                max_r_a = float(row_r[pj])
                partner = act_c[pj]
                v_all = spec_all["vifs"].get(c, np.nan)
                v_pass = spec_pass["vifs"].get(c, np.nan)
                if c in spec_pass["vifs"] and partner in spec_pass["act_cols"]:
                    pi_p = spec_pass["act_cols"].index(c)
                    pj_p = spec_pass["act_cols"].index(partner)
                    max_r_p = float(abs(spec_pass["R_pearson"][pi_p, pj_p]))
                else:
                    max_r_p = np.nan
            else:
                v_all, v_pass, max_r_a, partner, max_r_p = np.nan, np.nan, 0.0, "", np.nan

            f_f = reg_full["factors"].get(c, {})
            f_i = reg_is["factors"].get(c, {})
            f_o = reg_oos["factors"].get(c, {})
            fp_f = reg_pass_f["factors"].get(c, {})
            fp_i = reg_pass_is["factors"].get(c, {})
            fp_o = reg_pass_oos["factors"].get(c, {})

            x_vec = X_raw[:, j] if c != "s12_atom_xq_cold" else df["s12_atom_xq_cold"].fillna(1.0).to_numpy(float)
            nz_cnt = int((np.abs(x_vec) > 1e-12).sum())
            fmeta = meta.get(c, {"factor_id": c, "label_cn": c, "weight_desc": "", "intended_sign": 1})
            lr = loo_res[c]

            temp_rows[c] = {
                "strategy": st,
                "factor_col": c,
                "factor_id": fmeta["factor_id"],
                "label_cn": fmeta["label_cn"],
                "weight_desc": fmeta["weight_desc"],
                "intended_sign": fmeta["intended_sign"],
                "trigger_count": nz_cnt,
                "trigger_rate_pct": round(nz_cnt / len(df) * 100.0, 2),
                "mean_pts": round(float(np.mean(X_raw[:, j])), 3),
                "std_pts": round(float(np.std(X_raw[:, j])), 3),
                "vif_all": round(v_all, 3) if np.isfinite(v_all) else None,
                "vif_pass": round(v_pass, 3) if (v_pass is not None and np.isfinite(v_pass)) else None,
                "max_abs_r_all": round(max_r_a, 4),
                "max_corr_partner": partner,
                "max_abs_r_pass": round(max_r_p, 4) if (max_r_p is not None and np.isfinite(max_r_p)) else None,
                "ic_full": f_f.get("spearman_ic"),
                "uni_t_cl_full": f_f.get("uni_t_cl"),
                "uni_mean_edge_pp_full": f_f.get("uni_mean_edge_pp"),
                "ols_beta_full": f_f.get("ols_beta"),
                "ols_t_ols_full": f_f.get("ols_t_ols"),
                "ols_t_cl_full": f_f.get("ols_t_cl"),
                "ridge_beta_full": f_f.get("ridge_beta"),
                "ridge_cv_beta_full": f_f.get("ridge_cv_beta"),
                "ic_pass_full": fp_f.get("spearman_ic"),
                "ic_is": f_i.get("spearman_ic"),
                "uni_t_cl_is": f_i.get("uni_t_cl"),
                "ols_beta_is": f_i.get("ols_beta"),
                "ols_t_cl_is": f_i.get("ols_t_cl"),
                "ridge_beta_is": f_i.get("ridge_beta"),
                "ic_pass_is": fp_i.get("spearman_ic"),
                "ic_oos": f_o.get("spearman_ic"),
                "uni_t_cl_oos": f_o.get("uni_t_cl"),
                "ols_beta_oos": f_o.get("ols_beta"),
                "ols_t_cl_oos": f_o.get("ols_t_cl"),
                "ridge_beta_oos": f_o.get("ridge_beta"),
                "ic_pass_oos": fp_o.get("spearman_ic"),
                "loo_raw_n_full": lr["raw_n"],
                "loo_raw_d_nav_mult_full": round(lr["raw_d_nav_mult"], 4),
                "loo_raw_d_sharpe_full": round(lr["raw_d_sh_full"], 4),
                "loo_raw_d_sharpe_is": round(lr["raw_d_sh_is"], 4),
                "loo_raw_d_sharpe_oos": round(lr["raw_d_sh_oos"], 4),
                "loo_ctr_n_full": lr["ctr_n"],
                "loo_ctr_d_nav_mult_full": round(lr["ctr_d_nav_mult"], 4),
                "loo_ctr_d_sharpe_full": round(lr["ctr_d_sh_full"], 4),
                "loo_ctr_d_sharpe_is": round(lr["ctr_d_sh_is"], 4),
                "loo_ctr_d_sharpe_oos": round(lr["ctr_d_sh_oos"], 4),
            }

        # Asymmetric dominance check inside collinear pairs (|r| >= 0.30)
        for c, row in temp_rows.items():
            pt = row["max_corr_partner"]
            if row["max_abs_r_all"] >= 0.30 and pt in temp_rows:
                my_ls = _leader_score(row)
                pt_ls = _leader_score(temp_rows[pt])
                row["is_dominated_in_cluster"] = bool(pt_ls > my_ls)
            else:
                row["is_dominated_in_cluster"] = False

            fcls, freason = classify_factor(row)
            row["factor_class"] = fcls
            row["classification_reason"] = freason

        clust_res = run_hierarchical_clustering(X_clean, cols_clean, temp_rows, meta, st)
        c2p = clust_res["col_to_pillar"]
        for c in cols:
            row = temp_rows[c]
            if c == "s12_atom_dd20_deep":
                pid, pname, _ = c2p.get("s12_atom_dd20", ("1to2_P1", "支柱1", "MERGE"))
                row["recommended_pillar_id"] = pid
                row["recommended_pillar_name"] = pname
                row["consolidation_action"] = "DROP_DUPLICATE_IN_BUNDLE"
            else:
                pid, pname, act = c2p.get(c, ("", "", ""))
                row["recommended_pillar_id"] = pid
                row["recommended_pillar_name"] = pname
                row["consolidation_action"] = act
            row.pop("is_dominated_in_cluster", None)
            all_diag_rows.append(row)

        cls_lists = {k: [] for k in ("1_Core_Pillar", "2_Collinear_Redundant", "3_Deadweight_Noise", "4_Poison_Harmful")}
        for c in cols:
            cls_lists[temp_rows[c]["factor_class"]].append(c)

        vif_ge2 = [
            {"factor": c, "label_cn": temp_rows[c]["label_cn"], "vif_all": temp_rows[c]["vif_all"], "max_corr_partner": temp_rows[c]["max_corr_partner"], "max_abs_r_all": temp_rows[c]["max_abs_r_all"]}
            for c in cols if (temp_rows[c]["vif_all"] is not None and temp_rows[c]["vif_all"] >= 2.0)
        ]

        audit_json["strategy_summary"][st] = {
            "sample_counts": {
                "n_all_cands": int(len(df)),
                "n_valid_ret": int(valid.sum()),
                "n_is_le_2024": int(is_m.sum()),
                "n_oos_ge_2025": int(oos_m.sum()),
                "n_pass_official": int(df["is_pass_official"].sum()),
                "n_pass_is": int((pass_m & is_m).sum()),
                "n_pass_oos": int((pass_m & oos_m).sum()),
            },
            "dimensions_all_cands": {
                "n_native_factors": len(cols),
                "n_active_factors": spec_all["p_active"],
                "effective_factors_pr": round(spec_all["effective_factors_pr"], 3),
                "effective_factors_entropy": round(spec_all["effective_factors_entropy"], 3),
                "kaiser_dim_ge1": spec_all["kaiser_dim_ge1"],
                "pca_90pct_dim": spec_all["pca_90pct_dim"],
                "cond_num_X_std": round(spec_all["cond_num_X_std"], 3) if math.isfinite(spec_all["cond_num_X_std"]) else None,
                "cond_num_R": round(spec_all["cond_num_R"], 3) if math.isfinite(spec_all["cond_num_R"]) else None,
                "max_vif": round(spec_all["max_vif"], 3),
                "n_vif_ge2": spec_all["n_vif_ge2"],
                "mean_abs_r": round(spec_all["mean_abs_r"], 4),
                "mean_signed_r": round(spec_all["mean_signed_r"], 4),
                "min_signed_r": round(spec_all["min_signed_r"], 4),
                "max_signed_r": round(spec_all["max_signed_r"], 4),
            },
            "dimensions_pass_official": {
                "n_pass": int(df["is_pass_official"].sum()),
                "n_active_factors": spec_pass["p_active"],
                "effective_factors_pr": round(spec_pass["effective_factors_pr"], 3),
                "effective_factors_entropy": round(spec_pass["effective_factors_entropy"], 3),
                "cond_num_X_std": round(spec_pass["cond_num_X_std"], 3) if math.isfinite(spec_pass["cond_num_X_std"]) else None,
                "max_vif": round(spec_pass["max_vif"], 3),
                "mean_signed_r": round(spec_pass["mean_signed_r"], 4),
                "min_signed_r": round(spec_pass["min_signed_r"], 4),
                "max_signed_r": round(spec_pass["max_signed_r"], 4),
            },
            "berkson_paradox_audit": {
                "mean_signed_r_shift_pass_minus_all": round(spec_pass["mean_signed_r"] - spec_all["mean_signed_r"], 4),
                "min_signed_r_shift_pass_minus_all": round(spec_pass["min_signed_r"] - spec_all["min_signed_r"], 4),
                "max_vif_shift_pass_minus_all": round(spec_pass["max_vif"] - spec_all["max_vif"], 3),
                "note": "Conditioning on sum(F_j) >= threshold induces artificial negative correlation across independent factors (Berkson paradox) and masks positive clustering (e.g. pry mean_r +0.109 -> +0.000).",
            },
            "baseline_5y_030": base_sim,
            "regression_meta": {
                "full_df_res": reg_full.get("df_res"),
                "is_df_res": reg_is.get("df_res"),
                "oos_df_res": reg_oos.get("df_res"),
                "ridge_alpha_prop_full": reg_full.get("ridge_alpha_prop"),
                "ridge_cv_alpha_full": reg_full.get("ridge_cv_alpha"),
                "low_df_warning": bool((reg_is.get("df_res") or 99) < 15 or (reg_oos.get("df_res") or 99) < 15),
            },
            "high_corr_pairs_ge_030": high_pairs_030,
            "vif_ge_2_clusters": vif_ge2,
            "factor_classification_counts": {k: len(v) for k, v in cls_lists.items()},
            "factor_lists_by_class": cls_lists,
            "clustering_compression_plan": {k: v for k, v in clust_res.items() if k != "col_to_pillar"},
        }
        print(
            f"  [{st:4s}] p={len(cols):2d} | PR_eff={spec_all['effective_factors_pr']:5.2f} Ent_eff={spec_all['effective_factors_entropy']:5.2f} "
            f"| CondX={spec_all['cond_num_X_std']:4.2f} maxVIF={spec_all['max_vif']:5.2f} | Core={len(cls_lists['1_Core_Pillar'])} "
            f"Redun={len(cls_lists['2_Collinear_Redundant'])} Dead={len(cls_lists['3_Deadweight_Noise'])} Poison={len(cls_lists['4_Poison_Harmful'])} "
            f"| RecPillars={clust_res['recommended_k']} ({time.time()-t_st:.1f}s)"
        )

    df12 = bundle["pools"]["1to2"]
    s12_extra_cols = [
        "s12_s_prior_wk", "s12_s_quant_dual", "s12_d1_seal_tightness", "s12_p_elo",
        "s12_s_elo", "s12_p_sz", "s12_plate_d2_yizi_cnt", "s12_open_board_count",
        "s12_lhb_lh_cnt_d1", "s12_surf_yz_d1", "s12_xq_pre_d2",
    ]
    mat12_raw = bundle["atom_info"]["1to2"]["contrib_mat"]
    cols12_raw = bundle["atom_info"]["1to2"]["cols"]
    spec12_raw = compute_corr_vif_spectral(mat12_raw, cols12_raw)
    extra_corrs = {}
    for ec in s12_extra_cols:
        xv = pd.to_numeric(df12[ec], errors="coerce").to_numpy(float)
        if np.isfinite(xv).sum() < 20 or np.nanstd(xv) < 1e-12:
            continue
        top_hits = []
        for j, ac in enumerate(cols12_raw):
            av = mat12_raw[:, j] if ac != "s12_atom_xq_cold" else df12["s12_atom_xq_cold"].to_numpy(float)
            ok = np.isfinite(xv) & np.isfinite(av)
            if ok.sum() > 20 and np.std(av[ok]) > 1e-12:
                r = float(np.corrcoef(xv[ok], av[ok])[0, 1])
                if abs(r) >= 0.30:
                    top_hits.append({"atom": ac, "r": round(r, 3)})
        top_hits.sort(key=lambda d: -abs(d["r"]))
        if top_hits:
            extra_corrs[ec] = top_hits
    audit_json["1to2_supplement_audit"] = {
        "bundle_28col_max_abs_diff": audit_json["score_reconstruction_check"]["1to2"]["max_abs_diff_vs_orig_score"],
        "bundle_28col_r2": audit_json["score_reconstruction_check"]["1to2"]["r2_vs_orig_score"],
        "bundle_28col_pr_eff": round(spec12_raw["effective_factors_pr"], 3),
        "bundle_28col_cond_x": round(spec12_raw["cond_num_X_std"], 3),
        "bundle_28col_max_vif": round(spec12_raw["max_vif"], 3),
        "root_causes_of_1to2_gap": [
            "1) rd036 _build_1to2_contrib() only maps 28 s12_atom_* fields, omitting multi-tier/continuous components inside s12_s_prior_wk + s12_s_quant_dual (t_score_c, p_elo, s_elo, rk_theme 2/3, p_sz 2-3/1, dd60, nshape, d0_pct, ret10, mkt_seal, mkt_dt, mkt_zt, buy_open_lead, y_v17, q_pen, d_ov, sc_t3_pen) and v20_pen (-25).",
            "2) _build_1to2_contrib() double-counts dd20<=0.86 in BOTH s12_atom_dd20 AND s12_atom_dd20_deep (r=+0.915, inflating max_VIF to 8.32 in raw bundle).",
            "3) _build_1to2_contrib() assigns weight 0.0 to s12_atom_xq_cold (constant 0 in contrib_mat), whereas raw binary s12_atom_xq_cold has mean 0.979 and positive partial edge (IC=+0.057, tCl=+1.97).",
        ],
        "extra_s12_fields_corr_ge_030_with_atoms": extra_corrs,
    }

    df_diag = pd.DataFrame(all_diag_rows)
    df_pairs = pd.DataFrame(all_pair_rows).sort_values(["strategy", "r_pearson_all"], key=lambda s: s.abs() if s.name == "r_pearson_all" else s, ascending=[True, False])

    diag_csv = f"{OUT_DIR}/part1_factor_diagnostics_6strat.csv"
    pairs_csv = f"{OUT_DIR}/part1_collinear_pairs.csv"
    audit_path = f"{OUT_DIR}/part1_collinearity_audit.json"

    df_diag.to_csv(diag_csv, index=False, encoding="utf-8-sig")
    df_pairs.to_csv(pairs_csv, index=False, encoding="utf-8-sig")
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(sanitize_json(audit_json), f, ensure_ascii=False, indent=2)

    print(f"\n[Part 1 DONE in {time.time()-t0:.1f}s]")
    print(f"  Saved: {audit_path}")
    print(f"  Saved: {diag_csv} ({len(df_diag)} rows)")
    print(f"  Saved: {pairs_csv} ({len(df_pairs)} rows)")


if __name__ == "__main__":
    main()
