#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD030 Wave 2B Module 2: Window metrics, BH-FDR, HLZ/DSR, 5-fold Purged CV,
CSCV PBO, +-20% perturbation, 10,000x paired Block Bootstrap,
same-average-exposure static & pure 1/vol ablations, and full 7-pillar audit.
Zero yfinance (D12). Zero cap10m.
"""
import itertools
import json
import math
import os
import sys
import warnings

import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
PARTA_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades"
PARTB_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partB_20cm_full_jianyan"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
PARTD_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partD_final_jianyan"
VAL5_DIR = f"{SIM}/output/five_strategies_institutional_validation_20261124"

for p in (PARTA_DIR, PARTB_DIR, PARTC_V20, PARTD_DIR, VAL5_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import mod_common as mc
import mod_1to2 as m12
import tier_priority_engine as tpe
import run_part1_alpha_micro_regime as p1
import run_part2_signal_stats as p2
import run_part3_hygiene_portfolio_cusum as p3
import run_partB_20cm_7pillars as pb
import partD2_mod_p1_p3 as dp13
import partD2_mod_p4_p5 as dp45
import partD2_mod_p6_p7 as dp67
import step4_mod_rules_and_sim as m1

SEED = 20261124
TRD_DAYS_YEAR = 242.0


def sf(x, digits=6):
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
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 10) if abs(v) < 1e-4 else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def bh_fdr(p_vals: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted FDR q-values."""
    m = len(p_vals)
    if m == 0:
        return []
    arr = np.asarray(p_vals, dtype=float)
    order = np.argsort(arr)
    ranked = arr[order]
    q_raw = ranked * m / np.arange(1, m + 1)
    q_mon = np.minimum.accumulate(q_raw[::-1])[::-1]
    q_mon = np.clip(q_mon, 0.0, 1.0)
    out = np.empty(m, dtype=float)
    out[order] = q_mon
    return [round(float(x), 6) for x in out]


def calc_window_metrics_ext(
    tr_df: pd.DataFrame,
    pass_df: pd.DataFrame | None,
    daily_r: np.ndarray,
    cal_dts: list[str],
    dt_to_idx: dict,
    sh300: dict,
    all_sh_dts: list[str],
    sdt: str,
    edt: str,
    ew_daily_series: pd.Series | None = None,
) -> dict:
    csi_pct = tpe.get_csi_ret(sh300, all_sh_dts, sdt, edt)
    sub = tr_df[(tr_df["buy_date"] >= sdt) & (tr_df["buy_date"] <= edt)] if not tr_df.empty else pd.DataFrame()
    win_idx = [dt_to_idx[d] for d in cal_dts if sdt <= d <= edt]
    dr = daily_r[win_idx] if win_idx else np.zeros(1)
    T = len(dr)

    mtm_nav = float(np.prod(1.0 + dr))
    cum_d = np.cumprod(1.0 + dr)
    pk_d = np.maximum.accumulate(np.insert(cum_d, 0, 1.0))[1:]
    daily_mdd = float(np.max((pk_d - cum_d) / pk_d) * 100.0) if T > 0 else 0.0
    sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (mtm_nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if (T > 0 and mtm_nav > 0) else -100.0
    calmar = (cagr / daily_mdd) if daily_mdd > 1e-6 else 0.0

    # Daily equal-weight NAV (either from passing signals by buy_date or prebuilt 6-sleeve EW)
    if ew_daily_series is not None:
        ew_sub = ew_daily_series[(ew_daily_series.index >= sdt) & (ew_daily_series.index <= edt)].to_numpy(float)
        eq_nav = float(np.prod(1.0 + ew_sub)) if len(ew_sub) else 1.0
    elif pass_df is not None and not pass_df.empty:
        psub = pass_df[(pass_df["buy_date"] >= sdt) & (pass_df["buy_date"] <= edt)]
        eq_d = psub.groupby("buy_date")["net_ret"].mean().to_numpy(float) if not psub.empty else np.array([])
        eq_nav = float(np.prod(1.0 + eq_d)) if len(eq_d) else 1.0
    else:
        eq_nav = 1.0

    if sub.empty:
        return {
            "n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "nav": 1.0, "mtm_nav": round(mtm_nav, 4), "eq_nav": round(eq_nav, 4),
            "ex_top3_nav": 1.0, "ex_top5_nav": 1.0,
            "daily_mdd_pct": round(daily_mdd, 2), "trade_mdd_pct": 0.0,
            "daily_sharpe": round(sharpe, 3), "daily_calmar": round(calmar, 2),
            "csi300_pct": round(csi_pct, 2), "excess_csi300_pp": round(-csi_pct, 2),
            "excess_eq_csi300_pp": round((eq_nav - 1.0) * 100.0 - csi_pct, 2),
        }

    rets = sub["net_ret"].to_numpy(float)
    w, l = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    tr_nav = float(np.prod(1.0 + rets))
    sr_rets = np.sort(rets)
    ex3 = float(np.prod(1.0 + sr_rets[:-3])) if len(rets) > 3 else 1.0
    ex5 = float(np.prod(1.0 + sr_rets[:-5])) if len(rets) > 5 else 1.0
    cum_t = np.cumprod(1.0 + rets)
    pk_t = np.maximum.accumulate(np.insert(cum_t, 0, 1.0))[1:]
    trade_mdd = float(np.max((pk_t - cum_t) / pk_t) * 100.0)

    return {
        "n": int(len(rets)), "wr_pct": round(wr, 2), "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav": round(tr_nav, 4), "mtm_nav": round(mtm_nav, 4), "eq_nav": round(eq_nav, 4),
        "ex_top3_nav": round(ex3, 4), "ex_top5_nav": round(ex5, 4),
        "daily_mdd_pct": round(daily_mdd, 2), "trade_mdd_pct": round(trade_mdd, 2),
        "daily_sharpe": round(sharpe, 3), "daily_calmar": round(calmar, 2),
        "csi300_pct": round(csi_pct, 2),
        "excess_csi300_pp": round((tr_nav - 1.0) * 100.0 - csi_pct, 2),
        "excess_eq_csi300_pp": round((eq_nav - 1.0) * 100.0 - csi_pct, 2),
    }


def cscv_pbo_family(daily_r_map: dict[str, np.ndarray], base_key: str, S_list=(8, 10)) -> dict:
    names = list(daily_r_map.keys())
    R = np.column_stack([daily_r_map[k] for k in names])
    i_base = names.index(base_key)
    out = {}
    for S in S_list:
        gs = len(R) // S
        gidx = [list(range(i * gs, (i + 1) * gs if i < S - 1 else len(R))) for i in range(S)]
        omegas, beat_b = [], []
        win_cnt = {nm: 0 for nm in names}
        for te in itertools.combinations(range(S), S // 2):
            trg = [k for k in range(S) if k not in te]
            rt = R[[x for k in trg for x in gidx[k]]]
            re_ = R[[x for k in te for x in gidx[k]]]
            sdt, sde = rt.std(0, ddof=1), re_.std(0, ddof=1)
            st = np.divide(rt.mean(0), sdt, out=np.zeros_like(sdt), where=sdt > 1e-12)
            se = np.divide(re_.mean(0), sde, out=np.zeros_like(sde), where=sde > 1e-12)
            b = int(np.argmax(st))
            win_cnt[names[b]] += 1
            omegas.append(float(np.mean(se > se[b])))
            beat_b.append(bool(se[b] >= se[i_base]))
        om_arr = np.array(omegas)
        out[f"S{S}"] = {
            "combinations": len(omegas),
            "pbo_pct": round(float(np.mean(om_arr > 0.50) * 100.0), 2),
            "mean_omega": round(float(np.mean(om_arr)), 4),
            "is_winner_beat_base_oos_pct": round(float(np.mean(beat_b) * 100.0), 2),
            "top_is_winners": dict(sorted({k: v for k, v in win_cnt.items() if v > 0}.items(), key=lambda x: -x[1])[:8]),
        }
    return out


def purged_5fold_cv_combined(
    pools: dict[str, pd.DataFrame],
    untrig_base: pd.DataFrame,
    deltas: dict[str, np.ndarray],
    cal_5y: list[str],
    csi_5y: np.ndarray,
) -> dict:
    """Strict 5-fold Purged & Embargoed CV (EMBARGO=3d) on combined P3_S2C_STierReserveOnly."""
    tr_full, _ = m1.run_combined_v20(pools, untrig_base, deltas)
    dr_full, nd = m1.daily_mtm_from_segs(tr_full, len(cal_5y), "mtm_5y")
    assert nd < 1e-3, f"MTM mismatch: {nd}"
    dt_idx = {d: i for i, d in enumerate(cal_5y)}
    T = len(cal_5y)
    step = T // 5
    folds = [(k * step, (k + 1) * step - 1 if k < 4 else T - 1) for k in range(5)]

    out_folds = []
    for fi, (fs, fe) in enumerate(folds, 1):
        sdt, edt = cal_5y[fs], cal_5y[fe]
        sub = tr_full[(tr_full["buy_date"] >= sdt) & (tr_full["buy_date"] <= edt)]
        dr_f = dr_full[fs: fe + 1]
        csi_f = csi_5y[fs: fe + 1]
        nav_f = float(np.prod(1.0 + sub["net_ret"].to_numpy(float))) if not sub.empty else 1.0
        mtm_f = float(np.prod(1.0 + dr_f))
        sd_f = float(np.std(dr_f, ddof=1)) if len(dr_f) > 1 else 0.0
        sr_f = float(np.mean(dr_f) / sd_f * math.sqrt(TRD_DAYS_YEAR)) if sd_f > 1e-12 else 0.0
        ex_f = dr_f - csi_f
        esd = float(np.std(ex_f, ddof=1)) if len(ex_f) > 1 else 0.0
        ir_f = float(np.mean(ex_f) / esd * math.sqrt(TRD_DAYS_YEAR)) if esd > 1e-12 else 0.0
        out_folds.append({
            "fold": fi, "window": f"{sdt}~{edt}",
            "n": int(len(sub)), "nav": round(nav_f, 4), "mtm_nav": round(mtm_f, 4),
            "sharpe": round(sr_f, 3), "ir_vs_csi300": round(ir_f, 3),
        })
    return {
        "n_positive_folds": int(sum(1 for f in out_folds if f["nav"] > 1.0)),
        "mean_fold_sharpe": round(float(np.mean([f["sharpe"] for f in out_folds])), 3),
        "min_fold_nav": round(float(min(f["nav"] for f in out_folds)), 4),
        "prod_5fold_nav": round(float(np.prod([f["nav"] for f in out_folds])), 2),
        "folds": out_folds,
    }


def paired_block_bootstrap_10k(
    dr_cand: np.ndarray, dr_base: np.ndarray, csi_daily: np.ndarray, b_len: int = 5, n_boot: int = 10000
) -> dict:
    """10,000x Moving Block Bootstrap with paired candidate-vs-V20 comparison."""
    rng = np.random.default_rng(SEED)
    n_days = len(dr_cand)
    n_blocks = int(math.ceil(n_days / b_len))
    n_starts = n_days - b_len + 1
    starts = rng.integers(0, n_starts, size=(n_boot, n_blocks))

    blk_c = np.lib.stride_tricks.sliding_window_view(dr_cand, b_len)
    blk_b = np.lib.stride_tricks.sliding_window_view(dr_base, b_len)
    sim_c = blk_c[starts].reshape(n_boot, n_blocks * b_len)[:, :n_days]
    sim_b = blk_b[starts].reshape(n_boot, n_blocks * b_len)[:, :n_days]

    paths_c = np.concatenate([np.ones((n_boot, 1)), np.cumprod(1.0 + sim_c, axis=1)], axis=1)
    paths_b = np.concatenate([np.ones((n_boot, 1)), np.cumprod(1.0 + sim_b, axis=1)], axis=1)
    nav_c, nav_b = paths_c[:, -1], paths_b[:, -1]
    pk_c = np.maximum.accumulate(paths_c, axis=1)
    mdd_c = ((1.0 - paths_c / pk_c) * 100.0).max(axis=1)

    sr_c = np.mean(sim_c, axis=1) / np.maximum(1e-12, np.std(sim_c, axis=1, ddof=1)) * math.sqrt(TRD_DAYS_YEAR)
    sr_b = np.mean(sim_b, axis=1) / np.maximum(1e-12, np.std(sim_b, axis=1, ddof=1)) * math.sqrt(TRD_DAYS_YEAR)
    dsr = sr_c - sr_b
    csi_nav = float(np.prod(1.0 + csi_daily))

    return {
        "n_boot": n_boot, "block_len": b_len,
        "cand_nav_p05": round(float(np.quantile(nav_c, 0.05)), 2),
        "cand_nav_median": round(float(np.median(nav_c)), 2),
        "cand_nav_p95": round(float(np.quantile(nav_c, 0.95)), 2),
        "cand_mdd_median_pct": round(float(np.median(mdd_c)), 2),
        "cand_mdd_p95_pct": round(float(np.quantile(mdd_c, 0.95)), 2),
        "prob_beat_csi300_pct": round(float((nav_c > csi_nav).mean() * 100.0), 2),
        "paired_prob_cand_beat_v20_nav_pct": round(float((nav_c > nav_b).mean() * 100.0), 2),
        "paired_prob_cand_beat_v20_sharpe_pct": round(float((sr_c > sr_b).mean() * 100.0), 2),
        "paired_nav_ratio_p05": round(float(np.quantile(nav_c / np.maximum(1e-9, nav_b), 0.05)), 4),
        "paired_nav_ratio_median": round(float(np.median(nav_c / np.maximum(1e-9, nav_b))), 4),
        "paired_delta_sharpe_p05": round(float(np.quantile(dsr, 0.05)), 4),
        "paired_delta_sharpe_median": round(float(np.median(dsr)), 4),
    }


def calc_static_and_inv_vol_ablations(
    tr_df: pd.DataFrame,
    daily_r: np.ndarray,
    pools: dict[str, pd.DataFrame],
    untrig_base: pd.DataFrame,
    deltas: dict[str, np.ndarray],
    cal_5y: list[str],
    csi_5y: np.ndarray,
    mkt_ew_5y: np.ndarray,
    by_c_all: dict,
) -> dict:
    """Same-average-exposure static benchmarks + pure 1/vol ablations (sleeve-level & stock-level)."""
    T = len(cal_5y)
    dt_idx = {d: i for i, d in enumerate(cal_5y)}
    active_days = np.zeros(T, dtype=bool)
    for r in tr_df.itertuples(index=False):
        bi, ei = dt_idx.get(r.buy_date), dt_idx.get(r.exit_date)
        if bi is not None and ei is not None:
            active_days[bi: min(ei + 1, T)] = True
    avg_exp = float(active_days.mean())

    def _stats(vec, label):
        nav = float(np.prod(1.0 + vec))
        cum = np.cumprod(1.0 + vec)
        pk = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
        mdd = float(np.max((pk - cum) / pk) * 100.0)
        sd = float(np.std(vec, ddof=1))
        sr = float(np.mean(vec) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
        cagr = (nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if nav > 0 else -100.0
        cal = cagr / mdd if mdd > 1e-6 else 0.0
        return {"label": label, "avg_exposure": round(avg_exp if "Static" in label or "Matched" in label else float((np.abs(vec) > 1e-12).mean()), 4),
                "nav": round(nav, 4), "cagr_pct": round(cagr, 2), "mdd_pct": round(mdd, 2),
                "sharpe": round(sr, 3), "calmar": round(cal, 2)}

    # 1. Static constant-exposure benchmarks
    csi_stat = avg_exp * csi_5y
    ew_stat = avg_exp * mkt_ew_5y

    # 2. 6-sleeve standalone daily MTM matrix -> Equal-Weight vs Causal 60d 1/vol
    sleeves = []
    for st in m1.STRAT_ORDER:
        d_vec = deltas.get(st, np.zeros(len(pools[st]), dtype=float))
        _, sl = m1.sim_standalone(st, pools[st], d_vec, high_cb_mode="v51_exact", cm20_thr=82.0)
        sl_5y = sl[sl["buy_date"].between("2021-11-16", "2026-11-16")]
        dr_s, _ = m1.daily_mtm_from_segs(sl_5y, T, "mtm_5y")
        sleeves.append(dr_s)
    S_mat = np.column_stack(sleeves)  # (T, 6)
    ew6_r = S_mat.mean(axis=1)

    # Causal rolling 60-day std (t-60..t-1), active-conditional or full daily with 1e-4 floor
    vol_mat = np.zeros_like(S_mat)
    for t in range(T):
        lo = max(0, t - 60)
        if t - lo >= 10:
            sd_w = np.std(S_mat[lo:t], axis=0, ddof=1)
        else:
            sd_w = np.full(6, 0.02)
        vol_mat[t] = np.maximum(sd_w, 0.002)
    inv_v = 1.0 / vol_mat
    w_iv = inv_v / inv_v.sum(axis=1, keepdims=True)
    iv_full_r = np.sum(w_iv * S_mat, axis=1)
    # Scale 1/vol sleeve portfolio to match exact avg_exp of single-slot active exposure
    iv_active_exp = float((np.abs(iv_full_r) > 1e-12).mean())
    iv_scale = avg_exp / max(1e-6, iv_active_exp)
    iv_matched_r = iv_full_r * iv_scale

    # 3. Stock-level 1/vol20 position sizing on the single-slot trades (normalized to mean weight = 1.0 -> exact same avg_exp!)
    raw_iv = []
    for r in tr_df.itertuples(index=False):
        bar = by_c_all.get(r.code)
        v20 = 0.04
        if bar is not None and r.buy_date in bar["dt_to_pos"]:
            p0 = bar["dt_to_pos"][r.buy_date]
            vv = float(bar["vol20_m1"][p0])
            if np.isfinite(vv) and vv > 0.002:
                v20 = vv
        raw_iv.append(1.0 / v20)
    raw_iv_arr = np.asarray(raw_iv, dtype=float)
    w_tr = raw_iv_arr / max(1e-9, float(np.mean(raw_iv_arr)))
    tr_iv_rets = tr_df["net_ret"].to_numpy(float) * w_tr
    tr_iv_nav = float(np.prod(1.0 + tr_iv_rets))
    # Build daily series for stock-level 1/vol sizing
    day_iv_m = np.ones(T, dtype=float)
    for idx_r, r in enumerate(tr_df.itertuples(index=False)):
        wt = float(w_tr[idx_r])
        for t, mult in r.mtm_5y:
            day_iv_m[t] *= (1.0 + wt * (mult - 1.0))
    day_iv_r = day_iv_m - 1.0

    # 4. Pure 1/vol20 signal ranking (ignoring old-hot, sorting daily ties by lowest pre-buy vol20_m1!)
    pools_iv = {}
    for st in m1.STRAT_ORDER:
        df_s = pools[st].copy()
        v_arr = []
        for r in df_s.itertuples(index=False):
            bar = by_c_all.get(r.code)
            vv = 0.04
            if bar is not None and r.buy_date in bar["dt_to_pos"]:
                val = float(bar["vol20_m1"][bar["dt_to_pos"][r.buy_date]])
                if np.isfinite(val) and val > 0.002:
                    vv = val
            v_arr.append(vv)
        # Apply gentle 1/vol rank score tie-breaker/perturbation (+5 * (0.04 - vol)/0.02, clipped +-5)
        pools_iv[st] = np.clip((0.04 - np.asarray(v_arr)) / 0.02 * 5.0, -5.0, 5.0)
    tr_pure_iv, _ = m1.run_combined_v20(pools, untrig_base, pools_iv)
    dr_pure_iv, _ = m1.daily_mtm_from_segs(tr_pure_iv, T, "mtm_5y")

    return {
        "candidate_or_v20_single_slot": _stats(daily_r, "SingleSlot_Active"),
        "static_csi300_matched_avg_exp": _stats(csi_stat, "CSI300_Static_MatchedExp"),
        "static_alla_ew_matched_avg_exp": _stats(ew_stat, "AllA_EW_Static_MatchedExp"),
        "sleeve_6arm_equal_weight": _stats(ew6_r, "6Arm_EW"),
        "sleeve_6arm_inv_vol60_raw": _stats(iv_full_r, "6Arm_InvVol60"),
        "sleeve_6arm_inv_vol60_matched_exp": _stats(iv_matched_r, "6Arm_InvVol60_MatchedExp"),
        "single_slot_inv_vol20_sizing_matched_exp": {**_stats(day_iv_r, "SingleSlot_InvVol20_Sizing"), "trade_nav_compounded": round(tr_iv_nav, 4)},
        "single_slot_pure_inv_vol20_ranking": {**_stats(dr_pure_iv, "SingleSlot_PureInvVol20_Rank"), "n": int(len(tr_pure_iv)), "trade_nav": round(float(np.prod(1.0 + tr_pure_iv["net_ret"].to_numpy(float))), 4)},
    }


def check_truncation_20250101(
    pools: dict[str, pd.DataFrame],
    untrig_base: pd.DataFrame,
    full_tr: pd.DataFrame,
    rule_map: dict[str, tuple[str, float]],
    fb20_tr_cache: set | None = None,
) -> dict:
    """Prove zero future leakage: truncate pools/untrig/fb20 <= 2024-12-31 and assert diff == 0.0."""
    fb20_tr = fb20_tr_cache if fb20_tr_cache is not None else {d for d, c in mc.build_fb20_cln_dates_pit("2024-12-31").items() if c >= 2}
    p_tr = {}
    d_tr = {}
    for st in m1.STRAT_ORDER:
        df = pools[st]
        sub = df[(df["buy_date"] <= "2024-12-31") & (df["exit_date"] <= "2024-12-31")].copy().reset_index(drop=True)
        if st == "1to2":
            sub["v20_pen"] = np.where(sub["buy_date"].isin(fb20_tr), -25.0, 0.0)
            sub["v20_score"] = sub["base_score"].astype(float) + sub["v20_pen"]
        p_tr[st] = sub
        if st in rule_map:
            rid, w = rule_map[st]
            d_tr[st] = m1.compute_rule_delta(sub, rid, w)
            d_tr[f"_rule_{st}"] = (rid, w)
    ut_tr = untrig_base[untrig_base["buy_date"] <= "2024-12-31"].copy()
    tr_trunc, _ = m1.run_combined_v20(p_tr, ut_tr, d_tr, start_dt="2021-11-16", end_dt="2024-12-31")
    f24 = full_tr[full_tr["exit_date"] <= "2024-12-31"].reset_index(drop=True)
    t24 = tr_trunc[tr_trunc["exit_date"] <= "2024-12-31"].reset_index(drop=True)
    assert len(f24) == len(t24), f"Trunc len mismatch: {len(f24)} vs {len(t24)}"
    assert list(zip(f24["buy_date"], f24["code"], f24["strategy"])) == list(zip(t24["buy_date"], t24["code"], t24["strategy"])), "Trunc seq mismatch"
    max_diff = float(np.max(np.abs(f24["net_ret"].to_numpy(float) - t24["net_ret"].to_numpy(float))))
    assert max_diff == 0.0, f"Trunc max diff != 0: {max_diff}"
    return {"trades_exiting_le_20241231": int(len(t24)), "max_abs_diff": max_diff, "pass": True}


def format_ledger_for_partd(tr_df: pd.DataFrame, bar_lu: dict) -> pd.DataFrame:
    """Format run_combined_v20 output identically to partD2_mod_base for 7-pillar suite."""
    STRAT_CN = {"3to4": "三进四V4.1", "high": "高标首阴V5.1", "pry": "超跌撬板V2.1",
                "2to3": "二进三V2.1", "1to2": "一进二V20", "20cm": "20cm首板V1.1_S82"}
    rows = []
    for r in tr_df.itertuples(index=False):
        bb = bar_lu[(r.code, r.buy_date)]
        eb = bar_lu[(r.code, r.exit_date)]
        if r.strategy == "20cm":
            bp_a = float(r.buy_price_val)
            ep_a = bp_a * (1.0 + float(r.net_ret)) / 0.9970
            bp, ep, fee = round(bp_a / bb[4], 4), round(ep_a / eb[4], 4), 0.0030
        else:
            bp = float(r.buy_price_val)
            bp_a = bp * bb[4]
            ep_a = bp_a * (1.0 + float(r.net_ret)) / 0.9980
            ep, fee = round(ep_a / eb[4], 4), 0.0020
        rows.append({
            "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm), "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
            "code": r.code, "c6": r.code, "name": r.name, "strategy": r.strategy, "strategy_cn": STRAT_CN[r.strategy],
            "tier": r.tier, "phase": int(r.phase), "priority": int(r.prio), "score": float(r.score),
            "buy_price": bp, "exit_price": ep, "buy_px_adj": bp_a, "exit_px_adj": ep_a, "fee_rt": fee, "net_ret": float(r.net_ret),
        })
    return pd.DataFrame(rows)


def run_7pillars_combined(comb_fmt: pd.DataFrame, daily_s: np.ndarray, ctx_7p: dict) -> dict:
    """Run Pillars 1..7 on a combined ledger using preloaded All-A context."""
    cal_dates = ctx_7p["cal_dates"]
    sh300 = ctx_7p["sh300"]
    all_sh_dts = ctx_7p["all_sh_dts"]
    csi_s = ctx_7p["csi_s"]
    csi_5y_ret = ctx_7p["csi_5y_ret"]
    p1_out = dp13.run_pillar1_v20(
        comb_fmt, daily_s, ctx_7p["fac_5f"], ctx_7p["extra_f"], cal_dates,
        ctx_7p["pool10_dt"], ctx_7p["q10"], ctx_7p["by_c10"], ctx_7p["pool20_dt"], ctx_7p["q20"], ctx_7p["by_c20"],
    )
    p2_out = dp13.run_pillar2_v20(comb_fmt, ctx_7p["by_c_all"], cal_dates, ctx_7p["bars_5m"], ctx_7p["zt_tape"])
    p3_out = p1.run_pillar3("combined_wave2b", comb_fmt, pd.Series(daily_s, index=cal_dates), ctx_7p["reg_df"], csi_s, cal_dates)
    p4_out = dp45.run_pillar4_v20(comb_fmt, ctx_7p["by_c_all"], sh300, all_sh_dts, csi_5y_ret)
    # Pillar 5 (PSR/MinTRL, BCa, Runs/Kelly)
    rets = comb_fmt["net_ret"].to_numpy(float)
    rng = np.random.default_rng(SEED)
    d_ex = daily_s - csi_s.to_numpy(float)
    tr_csi = np.array([p2.get_csi_period_ret(sh300, all_sh_dts, r.buy_date, r.exit_date) for r in comb_fmt.itertuples(index=False)], float)
    tr_yr = len(rets) / 5.0
    psr = {
        "daily_mtm_basis": {"vs_zero": p2.calc_psr_mintrl(daily_s, 252.0, 1.0), "vs_csi300": p2.calc_psr_mintrl(d_ex, 252.0, 1.0)},
        "trade_level_basis": {"trades_per_year_5y": sf(tr_yr, 2), "vs_zero": p2.calc_psr_mintrl(rets, tr_yr, 1.0), "vs_csi300_holding": p2.calc_psr_mintrl(rets - tr_csi, tr_yr, 1.0)},
    }
    bca_m = p2.bca_bootstrap_ci(rets * 100.0, B=5000, alpha=0.05, rng=rng)
    bca_w = p2.bca_bootstrap_ci((rets > 0).astype(float) * 100.0, B=5000, alpha=0.05, rng=rng)
    wl, wh = p2.wilson_ci_95(int((rets > 0).sum()), len(rets))
    bca_w["wilson_95_ci_pct"] = [sf(wl * 100.0, 2), sf(wh * 100.0, 2)]
    p5_out = {
        "psr_and_mintrl": psr,
        "bca_bootstrap_95ci": {"mean_net_ret_pct": {**bca_m, "excludes_zero": bool(bca_m["ci_95_low"] > 0)}, "win_rate_pct": bca_w},
        **p2.calc_runs_autocorr_kelly(rets, rng=rng),
    }
    # Pillar 7 CUSUM/SPRT
    cusum = pb.calc_cusum_sprt_one(rets, rng)
    return {
        "pillar1_alpha_attribution": p1_out,
        "pillar2_micro_capacity": p2_out,
        "pillar3_regime_stress_bootstrap": p3_out,
        "pillar4_signal_and_turnover": p4_out,
        "pillar5_statistical_confidence": p5_out,
        "pillar7_cusum_sprt": cusum,
    }
