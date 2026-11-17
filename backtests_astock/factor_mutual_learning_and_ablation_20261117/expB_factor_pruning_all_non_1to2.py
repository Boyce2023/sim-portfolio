#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
expB_factor_pruning_all_non_1to2.py
================================================================================
A股一号席独立实证沙盒研究员 B:
严格贯彻「一进二 V16 -> V17」科学剪枝四步法，对除一进二以外全部 5 个策略:
  1. 高标首阴 V5.1 (22因子, 42笔带熔断 & 44笔纯单仓双口径, 修正买日封板才挂93%单)
  2. 三进四 V3.4 (23因子 = 10加 + 13扣, 88笔)
  3. 二进三 V1.0 (14因子, 77笔)
  4. 超跌撬板 V1.0 (10因子, 16单仓 / 25日)
  5. 四进五 V2.0 研发池 (18条细分规则 / 7维, 15笔)
执行双口径 LOFO (α原阈值直删 / β仅IS校准阈值盲测OOS)、四分类画像、
严格无偷看 IS 贪心后向剪枝 (P1瘦身版 & P2极简骨架版)、D15五期+统计学+组合联动验证。
================================================================================
"""
import os
import sys
import re
import json
import math
import time
import pickle
import itertools
import warnings
from collections import defaultdict
import numpy as np
import pandas as pd
import scipy.stats as stats

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
CLEAN_REF = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/factor_mutual_learning_and_ablation_20261117"
OUT_JSON = f"{OUT_DIR}/result_B_factor_pruning_all_non_1to2.json"
os.makedirs(OUT_DIR, exist_ok=True)

FEE_RATE = 0.0020
UNIT_PCT_DIV = 100.0
UNIT_YI_DIV = 1e8
DATA_AS_OF_ANCHOR = "2026-11-16"

# 三行核心数据与单位硬校验
IDX_ALL = json.load(open(f"{SANDBOX}/index_klines_5y_cache.json", "r", encoding="utf-8"))
CSI_MAP, SH_IDX_MAP, SZ_IDX_MAP = IDX_ALL["sh000300"], IDX_ALL["sh000002"], IDX_ALL["sz399107"]
CSI_CANON = json.load(open(f"{CLEAN_REF}/csi300_canonical_20261116.json", "r", encoding="utf-8"))
assert abs(1.0 / UNIT_PCT_DIV - 0.01) < 1e-12 and UNIT_YI_DIV == 1e8 and FEE_RATE == 0.0020
assert "2021-11-15" in CSI_MAP and DATA_AS_OF_ANCHOR in CSI_MAP and CSI_MAP[DATA_AS_OF_ANCHOR] > 1000.0
assert len(CSI_ALL_DAYS := sorted([d for d in CSI_MAP if "2021-11-15" <= d <= DATA_AS_OF_ANCHOR])) == 1213

ALL_IDX_DATES = sorted(CSI_MAP.keys())


def get_csi_ret_pct(s_dt: str, e_dt: str) -> float:
    dts = [d for d in ALL_IDX_DATES if s_dt <= d <= e_dt]
    if not dts:
        return 0.0
    prevs = [d for d in ALL_IDX_DATES if d < dts[0]]
    p0 = CSI_MAP[prevs[-1]] if prevs else CSI_MAP[dts[0]]
    p1 = CSI_MAP[dts[-1]]
    return float((p1 / p0 - 1.0) * 100.0)


def get_bench_ret_dec(bd: str, ed: str) -> float:
    prevs = [d for d in ALL_IDX_DATES if d < bd]
    p0 = CSI_MAP[prevs[-1]] if prevs else CSI_MAP[ALL_IDX_DATES[0]]
    p1 = CSI_MAP.get(ed, CSI_MAP[ALL_IDX_DATES[-1]])
    return float(p1 / p0 - 1.0)


def calc_period_metrics(raw_df: pd.DataFrame, slot_df: pd.DataFrame, s_dt: str, e_dt: str, csi_pct: float = None, pry_top1_eq: bool = False) -> dict:
    if csi_pct is None:
        csi_pct = get_csi_ret_pct(s_dt, e_dt)
    sub_r = raw_df[(raw_df["buy_date"] >= s_dt) & (raw_df["buy_date"] <= e_dt)] if not raw_df.empty else raw_df
    sub_s = slot_df[(slot_df["buy_date"] >= s_dt) & (slot_df["buy_date"] <= e_dt)] if not slot_df.empty else slot_df
    if sub_s.empty:
        return {
            "raw_n": int(len(sub_r)), "single_n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "nav_1s": 1.0, "cap10m_mult": 1.0, "cap1000w_mult": 1.0, "eq_nav": 1.0,
            "trim3_nav": 1.0, "trim5_nav": 1.0, "mdd_pct": 0.0,
            "csi300_pct": round(csi_pct, 2), "excess_1s_pp": round(-csi_pct, 2),
        }
    rets = sub_s["net_ret"].to_numpy(dtype=float)
    wins, losses = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) and len(losses) and losses.mean() < 0) else (99.0 if len(wins) else 0.0)
    nav_1s = float(np.prod(1.0 + rets))
    pk, cur, mdd = 1.0, 1.0, 0.0
    for x in rets:
        cur *= (1.0 + x)
        pk = max(pk, cur)
        mdd = max(mdd, (pk - cur) / pk)
    # 100万起千万封顶 (Cap10M) 与 1000万平铺封顶
    cap100, cap1000 = 100.0, 1000.0
    for x in rets:
        cap100 += min(cap100, 1000.0) * float(x)
        cap1000 += min(cap1000, 1000.0) * float(x)
    if pry_top1_eq and not sub_r.empty:
        top1 = sub_r.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
        eq_nav = float(np.prod(1.0 + top1["net_ret"].to_numpy(dtype=float)))
    elif not sub_r.empty:
        eq_nav = float(np.prod(1.0 + sub_r.groupby("buy_date")["net_ret"].mean().sort_index().to_numpy(dtype=float)))
    else:
        eq_nav = 1.0
    sr = np.sort(rets)
    trim3 = float(np.prod(1.0 + sr[:-3])) if len(sr) > 3 else 1.0
    trim5 = float(np.prod(1.0 + sr[:-5])) if len(sr) > 5 else 1.0
    return {
        "raw_n": int(len(sub_r)),
        "single_n": int(len(rets)),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav_1s": round(nav_1s, 3),
        "cap10m_mult": round(cap100 / 100.0, 3),
        "cap1000w_mult": round(cap1000 / 1000.0, 3),
        "eq_nav": round(eq_nav, 3),
        "trim3_nav": round(trim3, 3),
        "trim5_nav": round(trim5, 3),
        "mdd_pct": round(mdd * 100.0, 2),
        "csi300_pct": round(csi_pct, 2),
        "excess_1s_pp": round((nav_1s - 1.0) * 100.0 - csi_pct, 2),
    }


def eval_all_windows(raw_df: pd.DataFrame, slot_df: pd.DataFrame, is_start: str = "2022-01-01", s5_start: str = "2021-11-15", pry_top1_eq: bool = False) -> dict:
    specs = [
        ("IS", is_start, "2023-12-31", None),
        ("OOS_24_26", "2024-01-01", "2026-11-16", CSI_CANON["近三年(2024-01-01起)"][0]),
        ("5Y", s5_start, "2026-11-16", CSI_CANON["全五年(2021-11-16起)"][0]),
        ("Past_3Y", "2023-11-16", "2026-11-16", CSI_CANON["近三年(2023-11-16起)"][0]),
        ("2026", "2026-01-01", "2026-11-16", CSI_CANON["2026全年"][0]),
        ("Oct_plus", "2026-10-01", "2026-11-16", CSI_CANON["2026年10月以来"][0]),
    ]
    return {w: calc_period_metrics(raw_df, slot_df, sd, ed, cp, pry_top1_eq=pry_top1_eq) for w, sd, ed, cp in specs}


def calc_dsr_hlz_bootstrap(slot_5y: pd.DataFrame) -> dict:
    n = len(slot_5y)
    if n < 2:
        return {"hlz_t": 0.0, "dsr_m150": 0.0, "dsr_m30": 0.0, "boot_5pct_excess_pct": 0.0}
    ex = np.array([float(r.net_ret) - get_bench_ret_dec(str(r.buy_date), str(r.exit_date)) for r in slot_5y.itertuples(index=False)], dtype=float)
    std_ex = float(np.std(ex, ddof=1))
    sr_tr = float(np.mean(ex) / std_ex) if std_ex > 1e-12 else 0.0
    hlz_t = float(sr_tr * np.sqrt(n))
    skew = float(stats.skew(ex, bias=False)) if n > 2 else 0.0
    kurt = float(stats.kurtosis(ex, fisher=False, bias=False)) if n > 3 else 3.0
    if math.isnan(kurt) or kurt < 1.0:
        kurt = 3.0
    gamma = 0.5772156649
    dsr_out = {}
    for M in (30, 150):
        sr0 = (1.0 / np.sqrt(max(n - 1, 1))) * (
            (1.0 - gamma) * stats.norm.ppf(1.0 - 1.0 / M) + gamma * stats.norm.ppf(1.0 - 1.0 / (M * np.e))
        )
        denom = np.sqrt(max(1e-12, 1.0 - skew * sr_tr + ((kurt - 1.0) / 4.0) * (sr_tr ** 2)))
        dsr_out[M] = round(float(stats.norm.cdf((sr_tr - sr0) * np.sqrt(max(n - 1, 1)) / denom)), 4)
    rng = np.random.default_rng(20261117)
    b_means = np.array([np.mean(ex[rng.integers(0, n, size=n)]) for _ in range(2000)], dtype=float)
    return {
        "hlz_t": round(hlz_t, 2),
        "dsr_m150": dsr_out[150],
        "dsr_m30": dsr_out[30],
        "boot_5pct_excess_pct": round(float(np.percentile(b_means, 5) * 100.0), 2),
    }


def _cscv_pbo_matrix(R: np.ndarray, n_groups: int = 10) -> dict:
    n_days = R.shape[0]
    gs = n_days // n_groups
    gidx = [list(range(i * gs, (i + 1) * gs if i < n_groups - 1 else n_days)) for i in range(n_groups)]
    combos = list(itertools.combinations(range(n_groups), n_groups // 2))
    omegas = []
    for te in combos:
        trg = [k for k in range(n_groups) if k not in te]
        tri = [x for k in trg for x in gidx[k]]
        tei = [x for k in te for x in gidx[k]]
        rt, re = R[tri], R[tei]
        sd_t, sd_e = rt.std(0, ddof=1), re.std(0, ddof=1)
        st = np.divide(rt.mean(0), sd_t, out=np.zeros_like(sd_t), where=sd_t > 1e-12)
        se = np.divide(re.mean(0), sd_e, out=np.zeros_like(sd_e), where=sd_e > 1e-12)
        b = int(np.argmax(st))
        omegas.append(float(np.mean(se > se[b])))
    return {"pbo_pct": round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2), "mean_rank_oos": round(float(np.mean(omegas)), 4)}


def calc_cscv_pbo_s10(cand_5y: pd.DataFrame, scores_5y: np.ndarray, thresh: float, sim_fn, slot_5y: pd.DataFrame) -> dict:
    day_idx = {d: i for i, d in enumerate(CSI_ALL_DAYS)}
    n_days = len(CSI_ALL_DAYS)

    def _to_daily(led: pd.DataFrame) -> np.ndarray:
        arr = np.zeros(n_days, dtype=float)
        if not led.empty:
            for r in led.itertuples(index=False):
                i = day_idx.get(str(r.exit_date))
                if i is not None:
                    arr[i] += float(r.net_ret)
        return arr

    # 1. Quantile variants matching audit_overfitting_8tests & bt_2to3_v10_clean_master
    Rq = np.zeros((n_days, 14), dtype=float)
    Rq[:, 0] = _to_daily(slot_5y)
    if not slot_5y.empty and "score" in slot_5y.columns:
        sc_led = slot_5y["score"].to_numpy(dtype=float)
        for v in range(1, 14):
            qv = float(np.quantile(sc_led, 0.05 + (v / 14.0) * 0.40))
            sub = cand_5y[scores_5y >= qv].copy()
            sub["score"] = scores_5y[scores_5y >= qv]
            Rq[:, v] = _to_daily(sim_fn(sub))
    else:
        for v in range(1, 14):
            Rq[:, v] = Rq[:, 0]
    pbo_q = _cscv_pbo_matrix(Rq, 10)

    # 2. Threshold ladder around thresh [T-4 .. T+4]
    th_grid = [thresh + d for d in (-4, -3, -2, -1, 0, 1, 2, 3, 4)]
    cols_l = []
    for th in th_grid:
        m = scores_5y >= th
        if m.sum() == 0:
            continue
        sub = cand_5y[m].copy()
        sub["score"] = scores_5y[m]
        cols_l.append(_to_daily(sim_fn(sub)))
    if len(cols_l) >= 2:
        Rl = np.column_stack(cols_l)
        pbo_l = _cscv_pbo_matrix(Rl, 10)
    else:
        pbo_l = {"pbo_pct": 0.0, "mean_rank_oos": 0.5}
    return {"pbo_s10_quantile_pct": pbo_q["pbo_pct"], "pbo_s10_ladder_pct": pbo_l["pbo_pct"], "mean_rank_oos_q": pbo_q["mean_rank_oos"]}


def calibrate_threshold_is(df_is: pd.DataFrame, scores_is: np.ndarray, sim_fn, base_raw_n: int, base_1s_n: int, t_base: float, expected_shift: float) -> int:
    best_t, best_loss = int(t_base), 1e18
    for t in range(int(t_base) - 35, int(t_base) + 25):
        m = scores_is >= t
        rn = int(m.sum())
        if rn == 0:
            sn = 0
        else:
            sub = df_is[m].copy()
            sub["score"] = scores_is[m]
            sn = len(sim_fn(sub))
        loss = abs(rn - base_raw_n) * 10.0 + abs(sn - base_1s_n) * 3.0 + abs(t - (t_base - round(expected_shift))) * 0.05 + (0.001 if t != t_base else 0.0)
        if loss < best_loss:
            best_loss = loss
            best_t = t
    return best_t


def eval_variant(df_cand: pd.DataFrame, comp: np.ndarray, base_pts: float, active_idx: list, thresh: float, sim_fn, is_start: str, s5_start: str, pry_top1_eq: bool = False) -> tuple:
    sc = np.full(len(df_cand), float(base_pts), dtype=float)
    if active_idx:
        sc = sc + comp[:, active_idx].sum(axis=1)
    m = sc >= thresh
    raw_pass = df_cand[m].copy()
    raw_pass["score"] = sc[m]
    slot_all = sim_fn(raw_pass)
    wins = eval_all_windows(raw_pass, slot_all, is_start=is_start, s5_start=s5_start, pry_top1_eq=pry_top1_eq)
    m5 = df_cand["buy_date"].to_numpy() >= s5_start
    cand_5y = df_cand[m5].copy()
    sc_5y = sc[m5]
    raw_5y = raw_pass[raw_pass["buy_date"] >= s5_start]
    slot_5y = sim_fn(raw_5y) if not raw_5y.empty else pd.DataFrame()
    stats_ex = calc_dsr_hlz_bootstrap(slot_5y)
    pbo = calc_cscv_pbo_s10(cand_5y, sc_5y, thresh, sim_fn, slot_5y)
    return wins, {**stats_ex, **pbo}, raw_pass, slot_all, sc


def _aligned_spread(comp_col: np.ndarray, ret_arr: np.ndarray) -> float:
    if len(ret_arr) < 4 or np.std(comp_col) < 1e-12:
        return 0.0
    hi = comp_col > np.median(comp_col) if (comp_col.max() > 0 and comp_col.min() < 0) else (
        comp_col > 0 if comp_col.max() > 0 else comp_col >= 0
    )
    if hi.sum() == 0 or (~hi).sum() == 0:
        return 0.0
    return float((ret_arr[hi].mean() - ret_arr[~hi].mean()) * 100.0)


def run_strategy_ablation(
    strat_key: str,
    strat_label: str,
    df_cand: pd.DataFrame,
    comp: np.ndarray,
    factor_names: list,
    base_pts: float,
    t_base: float,
    sim_fn,
    target_p2: int,
    is_start: str = "2022-01-01",
    s5_start: str = "2021-11-15",
    pry_top1_eq: bool = False,
) -> dict:
    t0 = time.time()
    n_rows, n_fac = comp.shape
    assert len(df_cand) == n_rows and len(factor_names) == n_fac
    all_idx = list(range(n_fac))

    # 1. Baseline evaluation
    w_base, st_base, raw_base, slot_base, sc_base = eval_variant(
        df_cand, comp, base_pts, all_idx, t_base, sim_fn, is_start, s5_start, pry_top1_eq=pry_top1_eq
    )
    print(f"\n[{strat_label}] Base(K={n_fac}, T>={t_base}): 5Y={w_base['5Y']['single_n']}b WR={w_base['5Y']['wr_pct']}% 1S={w_base['5Y']['nav_1s']}x Cap10M={w_base['5Y']['cap10m_mult']}x MDD={w_base['5Y']['mdd_pct']}% | OOS={w_base['OOS_24_26']['single_n']}b {w_base['OOS_24_26']['nav_1s']}x | HLZ_t={st_base['hlz_t']} PBO_q={st_base['pbo_s10_quantile_pct']}%")

    is_mask = (df_cand["buy_date"].to_numpy() <= "2023-12-31") & (df_cand["buy_date"].to_numpy() >= is_start)
    oos_mask = df_cand["buy_date"].to_numpy() >= "2024-01-01"
    is_early_mask = is_mask & (df_cand["buy_date"].to_numpy() <= "2022-12-31")
    is_late_mask = is_mask & (df_cand["buy_date"].to_numpy() >= "2023-01-01")
    df_is = df_cand[is_mask].copy().reset_index(drop=True)
    comp_is = comp[is_mask]
    ret_all = df_cand["net_ret"].to_numpy(dtype=float)

    base_is_raw_n = w_base["IS"]["raw_n"]
    base_is_1s_n = w_base["IS"]["single_n"]
    base_is_1s = max(w_base["IS"]["nav_1s"], 1e-4)
    base_is_eq = max(w_base["IS"]["eq_nav"], 1e-4)
    base_is_wr = w_base["IS"]["wr_pct"]
    base_is_mdd = w_base["IS"]["mdd_pct"]
    base_is_pool_mean = float(df_is.loc[(base_pts + comp_is.sum(axis=1)) >= t_base, "net_ret"].mean()) if base_is_raw_n > 0 else 0.0

    # 2. Dual-mode LOFO + 4-category classification
    lofo_list = []
    counts_by_cat = defaultdict(int)
    for k in range(n_fac):
        keep = [j for j in all_idx if j != k]
        # 口径 α: 原阈值直删
        wa, _, _, _, _ = eval_variant(df_cand, comp, base_pts, keep, t_base, sim_fn, is_start, s5_start, pry_top1_eq=pry_top1_eq)
        # 口径 β: 仅在 IS 校准整数阈值后盲测 OOS
        sc_is_k = base_pts + comp_is[:, keep].sum(axis=1)
        mu_is_k = float(comp_is[:, k].mean())
        t_beta = calibrate_threshold_is(df_is, sc_is_k, sim_fn, base_is_raw_n, base_is_1s_n, t_base, mu_is_k)
        wb, stb, _, _, _ = eval_variant(df_cand, comp, base_pts, keep, t_beta, sim_fn, is_start, s5_start, pry_top1_eq=pry_top1_eq)

        sp_is_e = _aligned_spread(comp[is_early_mask, k], ret_all[is_early_mask])
        sp_is_l = _aligned_spread(comp[is_late_mask, k], ret_all[is_late_mask])
        sp_is = _aligned_spread(comp[is_mask, k], ret_all[is_mask])
        sp_oos = _aligned_spread(comp[oos_mask, k], ret_all[oos_mask])
        hit_is = float((comp[is_mask, k] != 0).mean() * 100.0)
        hit_oos = float((comp[oos_mask, k] != 0).mean() * 100.0)

        d_is_b = (wb["IS"]["nav_1s"] / base_is_1s) - 1.0
        d_oos_b = (wb["OOS_24_26"]["nav_1s"] / max(w_base["OOS_24_26"]["nav_1s"], 1e-4)) - 1.0
        d_oos_cap_b = (wb["OOS_24_26"]["cap10m_mult"] / max(w_base["OOS_24_26"]["cap10m_mult"], 1e-4)) - 1.0
        d_5y_b = (wb["5Y"]["nav_1s"] / max(w_base["5Y"]["nav_1s"], 1e-4)) - 1.0
        d_5y_eq_b = (wb["5Y"]["eq_nav"] / max(w_base["5Y"]["eq_nav"], 1e-4)) - 1.0
        d_is_a = (wa["IS"]["nav_1s"] / base_is_1s) - 1.0
        d_oos_a = (wa["OOS_24_26"]["nav_1s"] / max(w_base["OOS_24_26"]["nav_1s"], 1e-4)) - 1.0
        d_5y_a = (wa["5Y"]["nav_1s"] / max(w_base["5Y"]["nav_1s"], 1e-4)) - 1.0
        d_5y_eq_a = (wa["5Y"]["eq_nav"] / max(w_base["5Y"]["eq_nav"], 1e-4)) - 1.0
        d_wr_oos_b = wb["OOS_24_26"]["wr_pct"] - w_base["OOS_24_26"]["wr_pct"]
        d_mdd_oos_b = wb["OOS_24_26"]["mdd_pct"] - w_base["OOS_24_26"]["mdd_pct"]

        zero_loss_a = (
            abs(wa["5Y"]["raw_n"] - w_base["5Y"]["raw_n"]) <= 2
            and abs(wa["5Y"]["single_n"] - w_base["5Y"]["single_n"]) <= 1
            and abs(d_5y_a) < 0.03 and abs(d_oos_a) < 0.03 and abs(d_is_a) < 0.03 and abs(d_5y_eq_a) < 0.03
        )
        zero_loss_b = (
            abs(wb["5Y"]["raw_n"] - w_base["5Y"]["raw_n"]) <= 2
            and abs(wb["5Y"]["single_n"] - w_base["5Y"]["single_n"]) <= 1
            and abs(d_5y_b) < 0.03 and abs(d_oos_b) < 0.03 and abs(d_is_b) < 0.03 and abs(d_5y_eq_b) < 0.03
            and abs(sp_oos) < 5.0 and d_oos_a > -0.10
        )
        raw_explosion_b = wb["5Y"]["raw_n"] > (w_base["5Y"]["raw_n"] * 1.35 + 2)
        alpha_collapse_with_pos_oos = (d_5y_a < -0.25 and d_oos_a < -0.20 and sp_oos > 2.0)
        helps_oos_b = (
            not raw_explosion_b
            and not alpha_collapse_with_pos_oos
            and (d_oos_b > 0.02 or d_oos_cap_b > 0.02 or (d_wr_oos_b > 1.0 and d_mdd_oos_b <= 0.5))
        )
        hurts_oos_b = (d_oos_b < -0.02 or d_oos_cap_b < -0.02)

        if zero_loss_a or zero_loss_b:
            cat = "零损共线冗余 Zero-Loss Redundant"
        elif alpha_collapse_with_pos_oos:
            cat = "承重墙 Core"
        elif helps_oos_b and d_is_b < -0.05:
            cat = "周期摇摆项 Regime-Flip"
        elif hurts_oos_b and d_is_b > 0.05:
            cat = "周期摇摆项 Regime-Flip"
        elif helps_oos_b and d_is_b >= -0.05:
            cat = "过拟合/负效拖累 Toxic/Noise"
        else:
            cat = "承重墙 Core"
        counts_by_cat[cat] += 1

        lofo_list.append({
            "idx": k,
            "name": factor_names[k],
            "category": cat,
            "hit_is_pct": round(hit_is, 1),
            "hit_oos_pct": round(hit_oos, 1),
            "raw_spread_is_early_pp": round(sp_is_e, 2),
            "raw_spread_is_late_pp": round(sp_is_l, 2),
            "raw_spread_is_pp": round(sp_is, 2),
            "raw_spread_oos_pp": round(sp_oos, 2),
            "alpha": {
                "thresh": t_base,
                "is_n": wa["IS"]["single_n"], "is_wr": wa["IS"]["wr_pct"], "is_1s": wa["IS"]["nav_1s"],
                "oos_n": wa["OOS_24_26"]["single_n"], "oos_wr": wa["OOS_24_26"]["wr_pct"], "oos_1s": wa["OOS_24_26"]["nav_1s"], "oos_cap10m": wa["OOS_24_26"]["cap10m_mult"], "oos_eq": wa["OOS_24_26"]["eq_nav"], "oos_mdd": wa["OOS_24_26"]["mdd_pct"],
                "5y_n": wa["5Y"]["single_n"], "5y_wr": wa["5Y"]["wr_pct"], "5y_1s": wa["5Y"]["nav_1s"], "5y_cap10m": wa["5Y"]["cap10m_mult"], "5y_eq": wa["5Y"]["eq_nav"], "5y_trim3": wa["5Y"]["trim3_nav"], "5y_mdd": wa["5Y"]["mdd_pct"],
            },
            "beta_is_calibrated": {
                "thresh": t_beta,
                "is_n": wb["IS"]["single_n"], "is_wr": wb["IS"]["wr_pct"], "is_1s": wb["IS"]["nav_1s"],
                "oos_n": wb["OOS_24_26"]["single_n"], "oos_wr": wb["OOS_24_26"]["wr_pct"], "oos_1s": wb["OOS_24_26"]["nav_1s"], "oos_cap10m": wb["OOS_24_26"]["cap10m_mult"], "oos_eq": wb["OOS_24_26"]["eq_nav"], "oos_trim3": wb["OOS_24_26"]["trim3_nav"], "oos_mdd": wb["OOS_24_26"]["mdd_pct"],
                "5y_n": wb["5Y"]["single_n"], "5y_wr": wb["5Y"]["wr_pct"], "5y_1s": wb["5Y"]["nav_1s"], "5y_cap10m": wb["5Y"]["cap10m_mult"], "5y_eq": wb["5Y"]["eq_nav"], "5y_trim3": wb["5Y"]["trim3_nav"], "5y_mdd": wb["5Y"]["mdd_pct"],
                "hlz_t": stb["hlz_t"], "dsr_m150": stb["dsr_m150"], "pbo_q": stb["pbo_s10_quantile_pct"],
            },
        })

    # 3. 严格无偷看 IS-Only 后向逐步剪枝 -> P1 (零损+共线瘦身) & P2 (极简骨架)
    def eval_is_only(active_idx: list, thresh: float) -> tuple:
        sc_is = base_pts + (comp_is[:, active_idx].sum(axis=1) if active_idx else 0.0)
        m = sc_is >= thresh
        if m.sum() == 0:
            return {"raw_n": 0, "single_n": 0, "wr_pct": 0.0, "nav_1s": 0.01, "eq_nav": 0.01, "mdd_pct": 99.0, "pool_mean": -1.0}
        sub = df_is[m].copy()
        sub["score"] = sc_is[m]
        sl = sim_fn(sub)
        pm = calc_period_metrics(sub, sl, is_start, "2023-12-31", pry_top1_eq=pry_top1_eq)
        pm["pool_mean"] = float(sub["net_ret"].mean())
        return pm

    # P1: 一进二 V16->V17 风格零损+共线+IS明确拖累手术式瘦身 (严格基于IS<=2023候选集重合度+单因子不伤IS，绝不拆核心承重墙)
    active_p1 = list(all_idx)
    t_p1 = int(t_base)
    p1_log = []
    cur_is = eval_is_only(active_p1, t_p1)
    base_is_raw_set = set(np.where((base_pts + comp_is.sum(axis=1)) >= t_base)[0])
    cur_is_raw_set = set(base_is_raw_set)
    # 预先记录每个因子在单因子 IS LOFO (口径α+β) 及 IS 分段下的表现，防误删 IS 核心承重墙
    is_core_set = set()
    for item in lofo_list:
        a_is = item["alpha"]["is_1s"]
        b_is = item["beta_is_calibrated"]["is_1s"]
        b_wr = item["beta_is_calibrated"]["is_wr"]
        sp_e = item["raw_spread_is_early_pp"]
        sp_l = item["raw_spread_is_late_pp"]
        sp_all = item["raw_spread_is_pp"]
        hit_i = item["hit_is_pct"]
        if (
            a_is < base_is_1s * 0.96
            or b_is < base_is_1s * 0.96
            or b_wr < base_is_wr - 1.5
            or (sp_e > 1.0 and sp_l > 1.0)
            or (sp_all > 1.5 and hit_i >= 10.0 and sp_e >= 0.0 and sp_l >= 0.0)
        ):
            is_core_set.add(item["idx"])
    max_cum_zd_diff = 0 if base_is_raw_n < 12 else 1
    cum_mu_drift = 0.0
    max_p1_drops = max(2, n_fac - max(target_p2 + 2, int(round(n_fac * 0.55))))
    while len(p1_log) < max_p1_drops:
        best_cand = None
        for f in active_p1:
            if f in is_core_set:
                continue
            sp_e = _aligned_spread(comp[is_early_mask, f], ret_all[is_early_mask])
            sp_l = _aligned_spread(comp[is_late_mask, f], ret_all[is_late_mask])
            sp_all_is = _aligned_spread(comp[is_mask, f], ret_all[is_mask])
            hit_is = float((comp[is_mask, f] != 0).mean() * 100.0)
            mu_is_f = float(comp_is[:, f].mean())
            rem = [j for j in active_p1 if j != f]
            sc_rem = base_pts + comp_is[:, rem].sum(axis=1)
            rem_same_set = set(np.where(sc_rem >= t_p1)[0])
            cum_diff_same = len(rem_same_set ^ base_is_raw_set)
            step_diff_same = len(rem_same_set ^ cur_is_raw_set)
            m_same = eval_is_only(rem, t_p1)
            cond_zero_loss = (
                abs(cum_mu_drift + mu_is_f) <= 2.0
                and abs(mu_is_f) <= 2.0
                and cum_diff_same <= max_cum_zd_diff
                and step_diff_same <= max_cum_zd_diff
                and abs(m_same["single_n"] - base_is_1s_n) <= max_cum_zd_diff
                and m_same["nav_1s"] >= 0.995 * base_is_1s
                and m_same["eq_nav"] >= 0.995 * base_is_eq
                and m_same["wr_pct"] >= base_is_wr - 0.5
            )
            if cond_zero_loss:
                t_cal, m_cand, tag, cand_set, next_drift = t_p1, m_same, "zero_loss", rem_same_set, cum_mu_drift + mu_is_f
            else:
                if sp_all_is > 1.5 and (sp_e >= 0.0 and sp_l >= 0.0):
                    continue
                t_cal = calibrate_threshold_is(df_is, sc_rem, sim_fn, base_is_raw_n, base_is_1s_n, t_p1, mu_is_f)
                rem_cal_set = set(np.where(sc_rem >= t_cal)[0])
                cum_diff_cal = len(rem_cal_set ^ base_is_raw_set)
                m_cand = eval_is_only(rem, t_cal)
                cond_is_drag = (
                    cum_diff_cal <= max(1, int(round(0.08 * base_is_raw_n)))
                    and m_cand["nav_1s"] >= max(base_is_1s, cur_is["nav_1s"] * 0.998)
                    and m_cand["eq_nav"] >= base_is_eq * 1.000
                    and m_cand["wr_pct"] >= base_is_wr
                    and m_cand["mdd_pct"] <= base_is_mdd + 0.5
                    and abs(m_cand["single_n"] - base_is_1s_n) <= max(1, int(round(0.08 * base_is_1s_n)))
                    and m_cand["pool_mean"] >= base_is_pool_mean - 0.001
                )
                if not cond_is_drag:
                    continue
                tag, cand_set = "is_noise_or_collinear", rem_cal_set
                next_drift = cum_mu_drift + mu_is_f - float(t_p1 - t_cal)
            util = (m_cand["nav_1s"] / base_is_1s) + 0.5 * (m_cand["eq_nav"] / base_is_eq) + 0.02 * (m_cand["wr_pct"] - base_is_wr) + (0.5 if cond_zero_loss else 0.0)
            if best_cand is None or util > best_cand[0]:
                best_cand = (util, f, rem, t_cal, m_cand, cond_zero_loss, tag, cand_set, next_drift)
        if best_cand is None:
            break
        _, f_drop, active_p1, t_p1, cur_is, zd, tag, cur_is_raw_set, cum_mu_drift = best_cand
        p1_log.append({"dropped": factor_names[f_drop], "t_is_locked": int(t_p1), "reason": tag, "zero_diff": bool(zd), "is_1s": cur_is["nav_1s"], "is_wr": cur_is["wr_pct"]})

    # P2: continue IS greedy pruning down to target_p2 preserving IS backbone & candidate stability
    active_p2 = list(active_p1)
    t_p2 = int(t_p1)
    p2_log = []
    while len(active_p2) > target_p2:
        best_cand = None
        for f in active_p2:
            rem = [j for j in active_p2 if j != f]
            sc_rem = base_pts + comp_is[:, rem].sum(axis=1)
            t_cal = calibrate_threshold_is(df_is, sc_rem, sim_fn, base_is_raw_n, base_is_1s_n, t_p2, float(comp_is[:, f].mean()))
            m_cand = eval_is_only(rem, t_cal)
            cal_is_set = set(np.where(sc_rem >= t_cal)[0])
            jaccard_loss = len(cal_is_set ^ base_is_raw_set) / max(1, len(base_is_raw_set))
            sp_e = _aligned_spread(comp[is_early_mask, f], ret_all[is_early_mask])
            sp_l = _aligned_spread(comp[is_late_mask, f], ret_all[is_late_mask])
            sp_all_is = _aligned_spread(comp[is_mask, f], ret_all[is_mask])
            hit_is = float((comp[is_mask, f] != 0).mean() * 100.0)
            backbone_pen = 0.60 if f in is_core_set else (0.40 if (sp_e > 0.5 and sp_l > 0.5) else (0.25 if (sp_all_is > 1.0 and hit_is >= 10.0) else 0.0))
            util = (
                0.5 * math.log(max(m_cand["nav_1s"], 0.1))
                + 0.4 * math.log(max(m_cand["eq_nav"], 0.1))
                + 4.0 * (m_cand["pool_mean"] - base_is_pool_mean)
                + 0.015 * (m_cand["wr_pct"] - base_is_wr)
                - 0.01 * max(0.0, m_cand["mdd_pct"] - base_is_mdd)
                - 0.35 * jaccard_loss
                - backbone_pen
            )
            if best_cand is None or util > best_cand[0]:
                best_cand = (util, f, rem, t_cal, m_cand)
        if best_cand is None:
            break
        _, f_drop, active_p2, t_p2, m_p2 = best_cand
        p2_log.append({"dropped": factor_names[f_drop], "t_is_locked": int(t_p2), "is_1s": m_p2["nav_1s"], "is_wr": m_p2["wr_pct"]})

    # Blind OOS + Full 5Y evaluation of P1 and P2
    w_p1, st_p1, raw_p1, slot_p1, _ = eval_variant(df_cand, comp, base_pts, active_p1, t_p1, sim_fn, is_start, s5_start, pry_top1_eq=pry_top1_eq)
    w_p2, st_p2, raw_p2, slot_p2, _ = eval_variant(df_cand, comp, base_pts, active_p2, t_p2, sim_fn, is_start, s5_start, pry_top1_eq=pry_top1_eq)

    print(f"  -> P1(K={len(active_p1)}/{n_fac}, T>={t_p1}): 5Y={w_p1['5Y']['single_n']}b WR={w_p1['5Y']['wr_pct']}% 1S={w_p1['5Y']['nav_1s']}x Cap10M={w_p1['5Y']['cap10m_mult']}x MDD={w_p1['5Y']['mdd_pct']}% | OOS={w_p1['OOS_24_26']['single_n']}b WR={w_p1['OOS_24_26']['wr_pct']}% {w_p1['OOS_24_26']['nav_1s']}x | HLZ_t={st_p1['hlz_t']} PBO_q={st_p1['pbo_s10_quantile_pct']}%")
    print(f"  -> P2(K={len(active_p2)}/{n_fac}, T>={t_p2}): 5Y={w_p2['5Y']['single_n']}b WR={w_p2['5Y']['wr_pct']}% 1S={w_p2['5Y']['nav_1s']}x Cap10M={w_p2['5Y']['cap10m_mult']}x MDD={w_p2['5Y']['mdd_pct']}% | OOS={w_p2['OOS_24_26']['single_n']}b WR={w_p2['OOS_24_26']['wr_pct']}% {w_p2['OOS_24_26']['nav_1s']}x | HLZ_t={st_p2['hlz_t']} PBO_q={st_p2['pbo_s10_quantile_pct']}%")

    # 4. 全样本事后诊断上限 (非盲测): 哪些因子在 2024-2026 OOS 造成拖累及具体误杀/放行票
    oos_drags = []
    base_oos_keys = set(zip(slot_base[slot_base["buy_date"] >= "2024-01-01"]["buy_date"], slot_base[slot_base["buy_date"] >= "2024-01-01"]["code"])) if not slot_base.empty else set()
    for item in lofo_list:
        if item["category"] == "承重墙 Core":
            continue
        b = item["beta_is_calibrated"]
        d_cap = b["oos_cap10m"] - w_base["OOS_24_26"]["cap10m_mult"]
        d_1s = b["oos_1s"] - w_base["OOS_24_26"]["nav_1s"]
        if d_cap > 0.01 or d_1s > 0.02:
            keep = [j for j in all_idx if j != item["idx"]]
            _, _, _, slot_k, _ = eval_variant(df_cand, comp, base_pts, keep, b["thresh"], sim_fn, is_start, s5_start, pry_top1_eq=pry_top1_eq)
            sl_oos_k = slot_k[slot_k["buy_date"] >= "2024-01-01"] if not slot_k.empty else pd.DataFrame()
            k_keys = set(zip(sl_oos_k["buy_date"], sl_oos_k["code"])) if not sl_oos_k.empty else set()
            admitted = []
            for r in sl_oos_k.itertuples(index=False):
                if (r.buy_date, r.code) not in base_oos_keys:
                    admitted.append({"buy_date": r.buy_date, "code": r.code, "name": str(r.name), "net_ret_pct": round(float(r.net_ret) * 100.0, 2)})
            dropped = []
            for r in (slot_base[slot_base["buy_date"] >= "2024-01-01"].itertuples(index=False) if not slot_base.empty else []):
                if (r.buy_date, r.code) not in k_keys:
                    dropped.append({"buy_date": r.buy_date, "code": r.code, "name": str(r.name), "net_ret_pct": round(float(r.net_ret) * 100.0, 2)})
            oos_drags.append({
                "factor": item["name"],
                "category": item["category"],
                "delta_oos_cap10m": round(d_cap, 3),
                "delta_oos_1s": round(d_1s, 3),
                "oos_wr_after": b["oos_wr"],
                "missed_winners_when_kept": sorted([x for x in admitted if x["net_ret_pct"] > 0], key=lambda x: -x["net_ret_pct"])[:5],
                "avoided_losers_when_pruned": sorted([x for x in dropped if x["net_ret_pct"] <= 0], key=lambda x: x["net_ret_pct"])[:5],
            })
    oos_drags.sort(key=lambda x: -(x["delta_oos_1s"] + x["delta_oos_cap10m"]))

    return {
        "strategy_key": strat_key,
        "strategy_label": strat_label,
        "n_factors_orig": n_fac,
        "n_factors_p1": len(active_p1),
        "n_factors_p2": len(active_p2),
        "t_base": int(t_base),
        "t_p1": int(t_p1),
        "t_p2": int(t_p2),
        "category_counts": dict(counts_by_cat),
        "kept_factors_p1": [factor_names[i] for i in active_p1],
        "pruned_factors_p1": [factor_names[i] for i in all_idx if i not in active_p1],
        "kept_factors_p2": [factor_names[i] for i in active_p2],
        "pruned_factors_p2": [factor_names[i] for i in all_idx if i not in active_p2],
        "p1_greedy_log": p1_log,
        "p2_greedy_log": p2_log,
        "versions": {
            "Original": {"windows": w_base, "stats": st_base},
            "P1_Pruned": {"windows": w_p1, "stats": st_p1},
            "P2_Minimal": {"windows": w_p2, "stats": st_p2},
        },
        "lofo_factors": lofo_list,
        "posthoc_oos_drag_diagnostic_NOT_BLIND": oos_drags[:8],
        "_ledgers": {"orig": slot_base, "p1": slot_p1, "p2": slot_p2},
        "elapsed_sec": round(time.time() - t0, 2),
    }


# ==============================================================================
# Strategy 1: 高标首阴 V5.1 (22因子, 42笔带熔断 & 44笔纯单仓双口径)
# ==============================================================================
def prepare_high_dragon():
    hdir = f"{SANDBOX}/high_dragon_scorecard_20261113"
    (_, _, _, code_bars, _, _, _, _, _, _, _, _, _, _, _, _) = pickle.load(open(f"{hdir}/part1_cache.pkl", "rb"))
    df119 = pd.read_pickle(f"{hdir}/v5_enriched_119.pkl")
    assert df119.shape[0] == 119 and df119.shape[1] >= 130, f"Unexpected v5_enriched_119 shape: {df119.shape}"

    df_5m_pit = pd.read_parquet(f"{ROOT}/sim-portfolio/data/all_strategies_5m_complete_pit.parquet")
    df_5m_pit.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    pit_5m_map = {
        (c6, d): g[["hhmm_int", "open", "high", "low", "close"]].to_numpy(dtype=float)
        for (c6, d), g in df_5m_pit.groupby(["c6", "date"], sort=False)
    }
    sub2_5m = pickle.load(open(f"{hdir}/sub2_5m_bars_cache.pkl", "rb"))
    sub2_5m_map = {(k[0], k[2]): v for k, v in sub2_5m.items()}

    def get_5m(c6: str, dt: str):
        arr = pit_5m_map.get((c6, dt))
        if arr is not None and len(arr) > 0:
            return arr
        v = sub2_5m_map.get((c6, dt))
        if isinstance(v, pd.DataFrame) and not v.empty:
            sub = v[v["date"] == dt]
            if not sub.empty:
                hh = sub["hhmm"].str.replace(":", "").astype(int).values
                return np.column_stack([hh, sub["open"].values, sub["high"].values, sub["low"].values, sub["close"].values])
        return None

    def get_double_dev_px(bars, cp, imap, disc=0.07):
        cd = bars["dts"][cp]
        ir = imap.get(cd)
        if not ir:
            return 99999.0
        bp = 99999.0
        for k in range(1, min(11, cp + 1)):
            p = cp - k
            bi, bc = imap.get(bars["dts"][p]), bars["close"][p]
            if bi and bc > 0:
                bp = min(bp, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
        for k in range(1, min(31, cp + 1)):
            p = cp - k
            bi, bc = imap.get(bars["dts"][p]), bars["close"][p]
            if bi and bc > 0:
                bp = min(bp, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
        return bp

    # V5.1 hard gates (fast_high_dragon_today.py)
    gate = (
        (~df119["s_reg"].astype(bool))
        & (~df119["tox"].astype(bool))
        & (df119["ex_reg5"] < 2)
        & (df119["d1_to"] <= 35.0)
        & (df119["lh1"] < 3)
        & (df119["op2"].between(-0.065, 0.045))
    )
    sub = df119[gate].copy().reset_index(drop=True)

    rows_sim = []
    keep_idx = []
    for i, r in sub.iterrows():
        c6 = str(r.code).zfill(6)
        bars = code_bars[c6]
        d2p = bars["p"][r.buy_date]
        b_op, zt_px = float(bars["open"][d2p]), float(bars["zt_px"][d2p])
        if b_op >= zt_px - 0.011:
            continue
        if r.op2 >= 0.0:
            b_px, b_hhmm, b_open_h = b_op, 925, True
        else:
            ipx = round(b_op * 1.015, 2)
            if ipx >= zt_px - 0.011:
                continue
            arr_b = get_5m(c6, r.buy_date)
            if arr_b is None or len(arr_b) == 0:
                continue
            hit = False
            for row in arr_b:
                if int(row[0]) > 1130:
                    break
                if row[2] >= ipx:
                    b_hhmm, b_px = int(row[0]), float(max(row[1], ipx))
                    hit = True
                    break
            if not hit:
                continue
            b_open_h = False

        # 干净卖出: 仅当买日封涨停(bars["is_zt"][d2p])才从次日起挂93%双异动止盈单
        imap = SH_IDX_MAP if r.ex == "SH" else SZ_IDX_MAP
        n_b = len(bars["dts"])

        def run_zt_loop(start_p: int):
            imm = False
            for step in range(1, 8):
                p = start_p + step
                if p >= n_b:
                    break
                pl = get_double_dev_px(bars, p, imap, 0.07)
                e_op, e_cl = float(bars["open"][p]), float(bars["close"][p])
                if e_op >= pl:
                    return p, e_op, 925, True
                arr_e = get_5m(c6, bars["dts"][p])
                if arr_e is not None and len(arr_e) > 0:
                    for erow in arr_e:
                        if erow[2] >= pl:
                            return p, float(max(erow[1], pl)), int(erow[0]), False
                elif float(bars["high"][p]) >= pl:
                    return p, float(pl), 1030, False
                if not bars["is_zt"][p]:
                    if (not imm) and (e_cl > e_op):
                        imm = True
                        continue
                    while p < n_b - 1 and bars["is_yizi_dt"][p]:
                        p += 1
                    return p, float(bars["close"][p]), 1455, False
            p_end = min(start_p + 5, n_b - 1)
            return p_end, float(bars["close"][p_end]), 1455, False

        if bars["is_zt"][d2p]:
            ep, epx, e_hhmm, eo = run_zt_loop(d2p)
        else:
            p = min(d2p + 1, n_b - 1)
            while p < n_b - 1 and bars["is_yizi_dt"][p]:
                p += 1
            if bars["is_zt"][p]:
                ep, epx, e_hhmm, eo = run_zt_loop(p)
            else:
                ep, epx, e_hhmm, eo = p, float(bars["close"][p]), 1455, False

        net_ret = (epx * bars["adjf"][ep]) / (b_px * bars["adjf"][d2p]) * (1.0 - FEE_RATE) - 1.0
        keep_idx.append(i)
        rows_sim.append({
            "code": c6, "name": str(r.name), "buy_date": str(r.buy_date), "buy_hhmm": int(b_hhmm),
            "buy_price": round(b_px, 2), "exit_date": str(bars["dts"][ep]), "exit_hhmm": int(e_hhmm),
            "exit_price": round(epx, 2), "net_ret": float(net_ret), "b_open_h": bool(b_open_h),
            "eo": bool(eo), "open_pct": float(r.op2),
        })

    sub_ok = sub.iloc[keep_idx].reset_index(drop=True)
    df_cand = pd.DataFrame(rows_sim)
    assert len(df_cand) >= 60 and df_cand["open_pct"].abs().max() < 0.25

    factor_names = [
        "H01_反包率生态brk_r10(+12/-8)",
        "H02_昨涨停家数n_zt(+10/-10)",
        "H03_沪深300_5日趋势csi5(+8/-10)",
        "H04_D1首阴绿开承接d1_op(+8)",
        "H05_D2竞价窗口op2(+8/+6)",
        "H06_D0零炸板紧密度d0_tight(+6)",
        "H07_板块Elo非过热且非独大(+6)",
        "H08_D1龙虎榜拉萨数lh1(+6/-10)",
        "H09_D1机构席位in1(-6)",
        "H10_绝对股价档位<=20/>35(+5/-10)",
        "H11_换手成龙连板数>=4/<=2(+5/-5)",
        "H12_D1深水撬起<=-6%(+5)",
        "H13_V51锁仓>=45或真流通>=45亿(+6/-6)",
        "H14_D1量化做T且少拉萨(+4)",
        "H15_1年/3年>=5板老妖记忆(+6/+3)",
        "H16_老题材熟票vs蹭新概念(+3/-5)",
        "H17_D0顶级游资D1锁仓(+5)",
        "H18_D1拉萨买额占比>=20%(-10)",
        "H19_D1龙虎榜净买入为正(-5)",
        "H20_D0一日游席位买入(-6)",
        "H21_D0_0935前秒封(-5)",
        "H22_D0硬科技热词(-4)",
    ]
    comp = np.zeros((len(sub_ok), 22), dtype=float)
    comp[:, 0] = np.where(sub_ok["brk_r10"] >= 0.20, 12.0, -8.0)
    comp[:, 1] = np.where(sub_ok["n_zt"] < 70, 10.0, np.where(sub_ok["n_zt"] >= 95, -10.0, 0.0))
    comp[:, 2] = np.where(sub_ok["csi5"] >= -0.005, 8.0, np.where(sub_ok["csi5"] < -0.025, -10.0, 0.0))
    comp[:, 3] = np.where(sub_ok["d1_op"] < 0.0, 8.0, 0.0)
    comp[:, 4] = np.where(sub_ok["op2"] < 0.0, 8.0, np.where(sub_ok["op2"] <= 0.025, 6.0, 0.0))
    comp[:, 5] = np.where((sub_ok["obc"] == 0) & (sub_ok["d0_tight"] >= 35.0), 6.0, 0.0)
    comp[:, 6] = np.where((sub_ok["pelo"] < 135.0) & (~sub_ok["dom"].astype(bool)), 6.0, 0.0)
    comp[:, 7] = np.where(sub_ok["lh1"] == 0, 6.0, np.where(sub_ok["lh1"] == 2, -10.0, 0.0))
    comp[:, 8] = np.where(sub_ok["in1"] >= 1, -6.0, 0.0)
    comp[:, 9] = np.where(sub_ok["low_price_le20"].astype(bool), 5.0, np.where(sub_ok["high_price_gt35"].astype(bool), -10.0, 0.0))
    comp[:, 10] = np.where(sub_ok["turn_boards_ge4"].astype(bool), 5.0, np.where(sub_ok["turn_boards_cnt"] <= 2, -5.0, 0.0))
    comp[:, 11] = np.where(sub_ok["d1_deep_dip_le6"].astype(bool), 5.0, 0.0)
    comp[:, 12] = np.where((sub_ok["lock"] >= 45.0) | (sub_ok["fmcap"] >= 45.0), 6.0, -6.0)
    comp[:, 13] = np.where((sub_ok["qu1"] >= 1) & (sub_ok["lh1"] <= 1), 4.0, 0.0)
    comp[:, 14] = np.where(sub_ok["kpl_hist_1y_has_ge5"].astype(bool), 6.0, np.where(sub_ok["kpl_hist_3y_has_ge5"].astype(bool), 3.0, 0.0))
    comp[:, 15] = np.where(sub_ok["kpl_old_stock_old_theme"].astype(bool), 3.0, np.where(sub_ok["kpl_old_stock_new_theme"].astype(bool), -5.0, 0.0))
    comp[:, 16] = np.where(sub_ok["lhb_d0_top_locked"].astype(bool), 5.0, 0.0)
    comp[:, 17] = np.where(sub_ok["lhb_d1_lhasa_heavy"].astype(bool), -10.0, 0.0)
    comp[:, 18] = np.where(sub_ok["lhb_d1_net_positive"].astype(bool), -5.0, 0.0)
    comp[:, 19] = np.where(sub_ok["lhb_d0_day_surf_buy"].astype(bool), -6.0, 0.0)
    comp[:, 20] = np.where(sub_ok["kpl_d0_seal_early_0935"].astype(bool), -5.0, 0.0)
    comp[:, 21] = np.where(sub_ok["kpl_reason_tech"].astype(bool), -4.0, 0.0)

    def make_sim(use_cb: bool):
        def _sim(sub_d: pd.DataFrame) -> pd.DataFrame:
            if sub_d.empty:
                return pd.DataFrame()
            tdf = sub_d.sort_values(["buy_date", "score"], ascending=[True, False])
            taken, fd, peo, cl, sk = [], "", False, 0, False
            for r in tdf.itertuples(index=False):
                if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not r.b_open_h)):
                    if use_cb and sk:
                        fd, peo = r.exit_date, r.eo
                        if r.net_ret > 0:
                            sk, cl = False, 0
                        continue
                    taken.append(r._asdict())
                    fd, peo = r.exit_date, r.eo
                    if r.net_ret < -0.02:
                        cl += 1
                        if cl >= 2:
                            sk = True
                    elif r.net_ret > 0:
                        cl = 0
            return pd.DataFrame(taken)
        return _sim

    sim_44 = make_sim(False)
    sim_42 = make_sim(True)
    # 核对 42笔(16.39x) 与 44笔(15.17x) 口径
    sc_full = 60.0 + comp.sum(axis=1)
    p88 = df_cand[sc_full >= 88].copy()
    p88["score"] = sc_full[sc_full >= 88]
    l44, l42 = sim_44(p88), sim_42(p88)
    assert len(l44) == 44 and abs(np.prod(1.0 + l44["net_ret"]) - 15.17) < 0.02, f"High44 mismatch: {len(l44)} {np.prod(1.0 + l44['net_ret'])}"
    assert len(l42) == 42 and abs(np.prod(1.0 + l42["net_ret"]) - 16.39) < 0.02, f"High42 mismatch: {len(l42)} {np.prod(1.0 + l42['net_ret'])}"
    return df_cand, comp, factor_names, 60.0, 88, sim_44, sim_42


# ==============================================================================
# Strategy 2: 三进四 V3.4 (23因子 = 10加 + 13扣, 88笔)
# ==============================================================================
def prepare_3to4():
    pkg = pickle.load(open(f"{ROOT}/sim-portfolio/backtests_astock/special_26q4/3to4_26q4/cache_d_and_p.pkl", "rb"))
    df, p_list, sc_pkg = pkg["df"], pkg["p_v32"], pkg["sc_v34"]
    assert df.shape == (3152, 128), f"Unexpected 3to4 shape: {df.shape}"

    gate = (
        df["is_10cm_non_st"].astype(bool)
        & (~df["prev_is_yizi"].astype(bool))
        & df["buyable_open"].astype(bool)
        & (~df["has_tox_notice"].astype(bool))
        & (~df["has_stock_reg"].astype(bool))
        & (df["open_board_count"] >= 1)
        & df["open_pct"].between(0.030, 0.092)
        & np.array([p is not None for p in p_list], dtype=bool)
    )
    idxs = np.where(gate)[0]
    sub = df.iloc[idxs].copy().reset_index(drop=True)
    recs = [p_list[i] for i in idxs]
    df_cand = pd.DataFrame({
        "code": [str(x["code"]).zfill(6) for x in recs],
        "name": [str(x["name"]) for x in recs],
        "buy_date": [str(x["buy_date"]) for x in recs],
        "buy_hhmm": [int(x["buy_hhmm"]) for x in recs],
        "buy_price": [float(x["buy_price"]) for x in recs],
        "exit_date": [str(x["exit_date"]) for x in recs],
        "exit_hhmm": [int(x["exit_hhmm"]) for x in recs],
        "exit_price": [float(x["exit_price"]) for x in recs],
        "net_ret": [float(x["net_ret"]) for x in recs],
        "prio_3to4": sub["prio_3to4"].to_numpy(dtype=float),
        "open_pct": sub["open_pct"].to_numpy(dtype=float),
    })
    assert len(df_cand) == 355 and df_cand["open_pct"].abs().max() < 0.25

    fs = pd.to_numeric(sub["first_seal_time"].astype(str).str.replace(":", "").str[:4], errors="coerce").fillna(9999).astype(int)
    b_mon = pd.to_numeric(sub["buy_date"].astype(str).str[5:7], errors="coerce").fillna(0).astype(int)
    # 兼容 _is_post_holiday_or_monday 逻辑
    post_hol = sub["is_post_holiday_or_mon"].astype(bool)

    factor_names = [
        "T01_三板收盘<=20元(+8)",
        "T02_前日最高板<=4板破局(+8)",
        "T03_前日涨停35至85家温热(+5)",
        "T04_同题材首板高开>=2且0一字(+4)",
        "T05_三板零拉萨席位(+4)",
        "T06_八年题材热度>=115(+3)",
        "T07_前日三板零跌停(+3)",
        "T08_三板换手9.5至28%黄金带(+3)",
        "T09_三板0936至1030封板(+3)",
        "T10_周一或节后跨周末发酵(+2)",
        "T11_交易所重点监控期(-12)",
        "T12_一日游砸盘席位买入(-12)",
        "T13_非同日可买三板竞价头名(-12)",
        "T14_前日涨停>=95家过热(-10)",
        "T15_同题材队友竞价均值<-1.5%(-10)",
        "T16_锁仓<45%且真实流值<45亿(-10)",
        "T17_三板换手越界8.5~31%之外(-10)",
        "T18_沪深300急杀2%或5日破3%(-8)",
        "T19_同题材首板顶一字>=1家(-7)",
        "T20_三板股价>32元(-5)",
        "T21_三板拉萨>=3家扎堆(-5)",
        "T22_前日三板跌停>=2家(-4)",
        "T23_1月或5月日历退潮窗(-4)",
    ]
    comp = np.zeros((len(sub), 23), dtype=float)
    comp[:, 0] = np.where(sub["px_d3"] <= 20.0, 8.0, 0.0)
    comp[:, 1] = np.where(sub["mkt_max_board_prev"] <= 4, 8.0, 0.0)
    comp[:, 2] = np.where(sub["mkt_zt_prev"].between(35, 85), 5.0, 0.0)
    comp[:, 3] = np.where((sub["plate_fb_ho_cnt"] >= 2) & (sub["plate_fb_yz_cnt"] == 0), 4.0, 0.0)
    comp[:, 4] = np.where(sub["lhb_lh_cnt"] == 0, 4.0, 0.0)
    comp[:, 5] = np.where(sub["p_elo"] >= 115.0, 3.0, 0.0)
    comp[:, 6] = np.where(sub["prev_3b_dt_cnt"] == 0, 3.0, 0.0)
    comp[:, 7] = np.where(sub["prev_to"].between(9.5, 28.0), 3.0, 0.0)
    comp[:, 8] = np.where(fs.between(936, 1030), 3.0, 0.0)
    comp[:, 9] = np.where(post_hol, 2.0, 0.0)
    comp[:, 10] = np.where(sub["has_ex_reg"].astype(bool), -12.0, 0.0)
    comp[:, 11] = np.where(sub["surf_yz_buy"].astype(bool), -12.0, 0.0)
    comp[:, 12] = np.where(~sub["is_top1_3b_open"].astype(bool), -12.0, 0.0)
    comp[:, 13] = np.where(sub["mkt_zt_prev"] >= 95, -10.0, 0.0)
    comp[:, 14] = np.where(sub["plate_peers_open_avg"] < -0.015, -10.0, 0.0)
    comp[:, 15] = np.where((sub["lock_top10"] < 45.0) & (sub["real_free_mcap"] < 45.0), -10.0, 0.0)
    comp[:, 16] = np.where(~sub["prev_to"].between(8.5, 31.0), -10.0, 0.0)
    comp[:, 17] = np.where((sub["csi_1d_prev"] <= -0.020) | (sub["csi_5d_prev"] <= -0.030), -8.0, 0.0)
    comp[:, 18] = np.where(sub["plate_fb_yz_cnt"] >= 1, -7.0, 0.0)
    comp[:, 19] = np.where(sub["px_d3"] > 32.0, -5.0, 0.0)
    comp[:, 20] = np.where(sub["lhb_lh_cnt"] >= 3, -5.0, 0.0)
    comp[:, 21] = np.where(sub["prev_3b_dt_cnt"] >= 2, -4.0, 0.0)
    comp[:, 22] = np.where(b_mon.isin([1, 5]), -4.0, 0.0)

    assert np.all(78.0 + comp.sum(axis=1) == sc_pkg[idxs]), "3to4 23-factor sum != sc_v34!"

    def sim_3to4(sub_d: pd.DataFrame) -> pd.DataFrame:
        if sub_d.empty:
            return pd.DataFrame()
        w = sub_d.copy()
        w["_prio"] = w["score"].to_numpy(dtype=float) * 10.0 + w["prio_3to4"].to_numpy(dtype=float) * 0.1
        srt = w.sort_values(["buy_date", "buy_hhmm", "_prio"], ascending=[True, True, False])
        taken, free_dt, free_hh = [], "", 0
        for r in srt.itertuples(index=False):
            if free_dt == "" or r.buy_date > free_dt or (r.buy_date == free_dt and int(r.buy_hhmm) > free_hh):
                d_row = r._asdict()
                d_row.pop("_prio", None)
                taken.append(d_row)
                free_dt, free_hh = r.exit_date, int(r.exit_hhmm)
        return pd.DataFrame(taken)

    sc_full = 78.0 + comp.sum(axis=1)
    p90 = df_cand[sc_full >= 90].copy()
    p90["score"] = sc_full[sc_full >= 90]
    l88 = sim_3to4(p90)
    assert len(l88) == 88 and abs(np.prod(1.0 + l88["net_ret"]) - 562.10) < 0.05, f"3to4 mismatch: {len(l88)} {np.prod(1.0 + l88['net_ret'])}"
    return df_cand, comp, factor_names, 78.0, 90, sim_3to4


# ==============================================================================
# Strategy 3: 二进三 V1.0 (14因子, 77笔)
# ==============================================================================
def prepare_2to3():
    d23_dir = f"{ROOT}/sim-portfolio/backtests_astock/clean_2to3_v10_20261117/data_pit"
    raw_all = pd.read_parquet(f"{d23_dir}/clean_2to3_5y.parquet")
    wa = pd.read_parquet(f"{d23_dir}/factors_a.parquet")
    wb = pd.read_parquet(f"{d23_dir}/factors_b.parquet")
    wc = pd.read_parquet(f"{d23_dir}/factors_c.parquet")
    assert len(raw_all) == 10848 and str(raw_all["exit_dt_cc"].max()) == DATA_AS_OF_ANCHOR

    base = raw_all[raw_all["buyable_open"] & (~raw_all["prev_is_yizi"]) & (~raw_all["has_tox_90d"])].copy()
    assert len(base) == 6070
    wc_cols = [c for c in wc.columns if c not in ("code", "buy_date") and c not in base.columns]
    df = (
        base.merge(wa, on=["code", "buy_date"], how="inner")
        .merge(wb, on=["code", "buy_date"], how="inner")
        .merge(wc[["code", "buy_date"] + wc_cols], on=["code", "buy_date"], how="inner")
    )
    gate = (~df["has_reg_10d"]) & df["open_pct"].between(-0.065, 0.025) & (df["plate_sz"] < 15)
    d = df[gate].copy().reset_index(drop=True)
    assert len(d) >= 1500 and d["open_pct"].abs().max() < 0.25

    elo_ice = (d["a22_elo_ice_lt95"] == 1) | (d["d2_s_elo"] <= 95)
    w1_frag = ((d["c15_w1_day1_3"] == 1) | (d["c02_w1_fresh_20d_lt4_ge3"] == 1)) & (~elo_ice)
    w2_reb = (d["c21_w2_reb_20d_ge6"] == 1) | (d["c22_w2_reb_30d_ge6"] == 1)
    mid_warm = d["plate_rk_noev"].between(3, 7) | d["plate_sz"].between(2, 6)
    hot_crowd = ((d["plate_rk_noev"] <= 2) & (d["plate_sz"] >= 7)) | (d["plate_sz"] >= 12)
    both_low = (d["mkt_p12_prev"] < 0.18) & (d["mkt_p23_prev"] < 0.28)
    d2_weak_late = (d["d2_open_cnt_tape"] >= 1) & (
        (d["d2_seal_sec"].fillna(0) >= 1800) | (d["d2_seal_amt_ratio"].fillna(1) < 0.05)
    )
    d2_fast_zero = (d["d2_open_cnt_tape"] == 0) & (d["d2_seal_sec"].fillna(99999) <= 300)

    comp = np.zeros((len(d), 14), dtype=float)
    comp[:, 0] = np.where(d["b01_hhi_low_q25"] == 1, 6.0, np.where(d["raw_top1_share"] >= 0.30, -10.0, 0.0))
    comp[:, 1] = np.where(both_low, 8.0, np.where(d["mkt_p23_prev"] < 0.28, 5.0, 0.0))
    comp[:, 2] = np.where(d["mkt_maxb_prev"] <= 3, 6.0, 0.0)
    comp[:, 3] = np.where(hot_crowd, -10.0, np.where(mid_warm, 5.0, 0.0))
    comp[:, 4] = np.where(elo_ice, 8.0, 0.0)
    comp[:, 5] = np.where(w1_frag, -16.0, np.where(w2_reb, 5.0, 0.0))
    comp[:, 6] = np.where(d["plate_3b_cnt_sd"] >= 1, -8.0, 0.0)
    comp[:, 7] = np.where(d["xq_cnt_tot"] == 0, 0.0, np.where(d["xq_cnt_tot"] >= 4, -18.0, -10.0))
    comp[:, 8] = np.where(d["ir_has_20d"] == 1, -10.0, 0.0)
    comp[:, 9] = np.where(d["d2_low_pct"] <= -0.02, 6.0, 0.0)
    comp[:, 10] = np.where(d["d2_seal_amt_ratio"].fillna(0) >= 0.25, -16.0, np.where(d2_fast_zero, -8.0, np.where(d2_weak_late, 6.0, 0.0)))
    comp[:, 11] = np.where(d["pos_20d_d0"].fillna(0.5) <= 0.40, 6.0, 0.0)
    comp[:, 12] = np.where(d["d2_real_turn"].fillna(30.0) < 15.0, -8.0, np.where((d["lock_top10"].fillna(0) >= 50.0) & d["d2_real_turn"].fillna(0).between(25.0, 65.0), 8.0, 0.0))
    comp[:, 13] = np.where(d["open_pct"] < 0.0, 5.0, 0.0)

    factor_names = [
        "E01_HHI离散或单极集中(+6/-10)",
        "E02_昨晋级率低迷分歧(+8/+5)",
        "E03_昨最高板<=3板压制(+6)",
        "E04_板块温热或过热拥挤(+5/-10)",
        "E05_板块极寒Elo<=95破冰(+8)",
        "E06_一波脆弱vs二波回流(-16/+5)",
        "E07_同板块3板+老大哥压制(-8)",
        "E08_雪球暗牌零帖vs吹票(0/-10/-18)",
        "E09_近20日机构调研排雷(-10)",
        "E10_D2盘中深水洗盘<=-2%(+6)",
        "E11_D2开板弱封单vs死锁秒板(+6/-8/-16)",
        "E12_启动前20日箱体低位<=0.40(+6)",
        "E13_锁仓>=50%&换手25~65%(+8/-8)",
        "E14_D3竞价绿开承接<0%(+5)",
    ]

    df_cand = pd.DataFrame({
        "code": d["code"].astype(str).str.zfill(6),
        "name": d["name"].astype(str),
        "buy_date": d["buy_date"].astype(str),
        "buy_hhmm": 925,
        "exit_date": d["exit_dt_cc"].astype(str),
        "exit_hhmm": d["exit_hh_cc"].astype(int),
        "net_ret": d["ret_opn_cc"].astype(float),
        "open_pct": d["open_pct"].astype(float),
        "plate_sz": d["plate_sz"].astype(int),
    })

    def sim_2to3(sub_d: pd.DataFrame) -> pd.DataFrame:
        if sub_d.empty:
            return pd.DataFrame()
        srt = sub_d.sort_values(["buy_date", "score", "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True])
        taken, fdt, fhh = [], "", 0
        for r in srt.itertuples(index=False):
            if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and 925 > fhh):
                taken.append(r._asdict())
                fdt, fhh = r.exit_date, int(r.exit_hhmm)
        return pd.DataFrame(taken)

    sc_full = 58.0 + comp.sum(axis=1)
    p90_5y = df_cand[(df_cand["buy_date"] >= "2021-11-16") & (sc_full >= 90)].copy()
    p90_5y["score"] = sc_full[(df_cand["buy_date"] >= "2021-11-16") & (sc_full >= 90)]
    l77 = sim_2to3(p90_5y)
    assert len(l77) == 77 and abs(np.prod(1.0 + l77["net_ret"]) - 20.32) < 0.05, f"2to3 mismatch: {len(l77)} {np.prod(1.0 + l77['net_ret'])}"
    return df_cand, comp, factor_names, 58.0, 90, sim_2to3


# ==============================================================================
# Strategy 4: 超跌撬板 V1.0 (10因子, 16单仓 / 25日)
# ==============================================================================
def prepare_pry():
    p5_dir = f"{ROOT}/sim-portfolio/backtests_astock2/p5_full_pry_universe"
    gfm_dir = f"{SANDBOX}/grand_factor_matrix_20261112"
    df = pd.read_parquet(f"{p5_dir}/full_pry_master_enriched.parquet")
    cb = pickle.load(open(f"{gfm_dir}/code_bars_5y.pkl", "rb"))["code_bars"]
    l1 = pd.read_csv(f"{p5_dir}/v1_oversold_pry_165_strict_ledger.csv")
    l1["code"] = l1["code"].astype(str).str.zfill(6)
    l1["c6"] = l1["code"]
    assert df.shape == (65911, 158)

    n = len(df)
    c6_v, ds_v = df["c6"].values, df["sig_date"].values
    bias10 = np.zeros(n, dtype=np.float32)
    down_streak = np.zeros(n, dtype=np.int16)
    is_yang = np.zeros(n, dtype=bool)
    for i in range(n):
        d = cb.get(c6_v[i])
        if d is None:
            continue
        p = d["date_to_pos"].get(ds_v[i])
        if p is None:
            continue
        op, cl = d["open"][p], d["close"][p]
        is_yang[i] = cl > op
        if p >= 9:
            bias10[i] = cl / np.mean(d["close"][p - 9: p + 1]) - 1.0
        st, k = 0, p - 1
        while k >= 0 and d["close"][k] < d["pre_c"][k]:
            st += 1
            k -= 1
        down_streak[i] = st
    df["bias10"] = bias10
    df["down_streak"] = down_streak
    df["is_yang"] = is_yang

    gate = (
        (~df["is_st_or_delist"].values)
        & (df["pre_c"].values >= 2.0)
        & (~df["n_poison90"].fillna(False).values)
        & (~df["n_del90"].fillna(False).values)
        & (~df["n_inv90"].fillna(False).values)
        & df["prev_touch_dt"].fillna(False).values.astype(bool)
        & (~df["prev_is_dt"].fillna(True).values.astype(bool))
        & (df["prev_zt20"].fillna(0).values == 0)
        & (df["prev_c_ma20"].fillna(0).values <= -0.15)
        & (df["prev_dd20"].fillna(1.0).values <= 0.80)
        & (df["o_pct"].values >= 0.0)
        & (df["o_pct"].values <= 0.05)
    )
    sub = df[gate].copy().reset_index(drop=True)
    assert len(sub) == 830 and sub["o_pct"].abs().max() < 0.25

    def first_sellable(d, start_pos):
        L = len(d["dts"])
        p = start_pos
        while p < L - 1 and d["is_yizi_dt"][p]:
            p += 1
        return min(p, L - 1)

    def sim_x10_strict(d, p0, buy_px, dyn_tp):
        L = len(d["dts"])
        if p0 + 1 >= L or buy_px <= 0:
            return np.nan, ""
        o, h, c, dt_px, is_zt, is_yz_dt, dts, adjf = (
            d["open"], d["high"], d["close"], d["dt_px"], d["is_zt"], d["is_yizi_dt"], d["dts"], d["adjf"]
        )
        day0_reseal = (c[p0] <= dt_px[p0] + 0.005)
        if day0_reseal:
            ps = first_sellable(d, p0 + 1)
            s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
            return float((s_px * adjf[ps]) / (buy_px * adjf[p0]) * (1.0 - FEE_RATE) - 1.0), str(dts[ps])
        if is_zt[p0]:
            cur = p0
            while cur < L - 1:
                nxt = cur + 1
                if is_yz_dt[nxt]:
                    nxt2 = first_sellable(d, nxt)
                    s_px = o[nxt2] if o[nxt2] > dt_px[nxt2] + 0.005 else c[nxt2]
                    return float((s_px * adjf[nxt2]) / (buy_px * adjf[p0]) * (1.0 - FEE_RATE) - 1.0), str(dts[nxt2])
                if is_zt[nxt]:
                    cur = nxt
                    continue
                return float((c[nxt] * adjf[nxt]) / (buy_px * adjf[p0]) * (1.0 - FEE_RATE) - 1.0), str(dts[nxt])
            return float((c[cur] * adjf[cur]) / (buy_px * adjf[p0]) * (1.0 - FEE_RATE) - 1.0), str(dts[cur])
        tp_px = round(buy_px * (1.0 + dyn_tp), 2)
        end_p = min(L - 1, p0 + 4)
        for k in range(p0 + 1, end_p + 1):
            if is_yz_dt[k]:
                continue
            if o[k] >= tp_px:
                return float((o[k] * adjf[k]) / (buy_px * adjf[p0]) * (1.0 - FEE_RATE) - 1.0), str(dts[k])
            if h[k] >= tp_px:
                return float((tp_px * adjf[k]) / (buy_px * adjf[p0]) * (1.0 - FEE_RATE) - 1.0), str(dts[k])
        ps = first_sellable(d, end_p)
        return float((c[ps] * adjf[ps]) / (buy_px * adjf[p0]) * (1.0 - FEE_RATE) - 1.0), str(dts[ps])

    rets, edts, valid_idx = [], [], []
    for i, r in sub.iterrows():
        d = cb.get(r["c6"])
        if d is None:
            continue
        p0 = d["date_to_pos"].get(r["dt_str"])
        if p0 is None or p0 + 1 >= len(d["dts"]):
            continue
        if bool(d["is_yizi"][p0]) or float(d["open"][p0]) >= float(d["zt_px"][p0]) - 0.011:
            continue
        dyn_tp = float(np.clip(0.45 * abs(float(r["prev_ret10"])), 0.06, 0.16))
        rv, ed = sim_x10_strict(d, p0, float(r["open"]), dyn_tp)
        if not np.isnan(rv) and ed:
            valid_idx.append(i)
            rets.append(rv)
            edts.append(ed)

    sub_v = sub.iloc[valid_idx].copy().reset_index(drop=True)
    df_cand = pd.DataFrame({
        "code": sub_v["c6"].astype(str).str.zfill(6),
        "name": sub_v["name"].astype(str),
        "buy_date": sub_v["dt_str"].astype(str),
        "buy_hhmm": 925,
        "exit_date": edts,
        "exit_hhmm": 1500,
        "net_ret": rets,
        "bias10": sub_v["bias10"].astype(float),
        "open_pct": sub_v["o_pct"].astype(float),
    })

    factor_names = [
        "P01_bias10<=-15%(+20)",
        "P02_连阴down_streak>=4(+15)",
        "P03_c_ma20<=-22%(+15)",
        "P04_真实流值<=25亿(+15)",
        "P05_0925涨停>=12家(+15)",
        "P06_昨翘板收真阳(+10)",
        "P07_昨量比>=1.5倍(+10)",
        "P08_锁仓>=50%(+10)",
        "P09_昨龙虎榜机构买(+10)",
        "P10_昨拉萨买额占比>25%(-20)",
    ]
    comp = np.zeros((len(sub_v), 10), dtype=float)
    comp[:, 0] = np.where(sub_v["bias10"].values <= -0.15, 20.0, 0.0)
    comp[:, 1] = np.where(sub_v["down_streak"].values >= 4, 15.0, 0.0)
    comp[:, 2] = np.where(sub_v["prev_c_ma20"].fillna(0).values <= -0.22, 15.0, 0.0)
    comp[:, 3] = np.where(sub_v["real_free_mcap"].fillna(999).values <= 25.0, 15.0, 0.0)
    comp[:, 4] = np.where(sub_v["mkt_open_zt_0925"].fillna(0).values >= 12, 15.0, 0.0)
    comp[:, 5] = np.where(sub_v["is_yang"].values, 10.0, 0.0)
    comp[:, 6] = np.where(sub_v["prev_vr"].fillna(0).values >= 1.5, 10.0, 0.0)
    comp[:, 7] = np.where(sub_v["lock_top10"].fillna(0).values >= 50.0, 10.0, 0.0)
    comp[:, 8] = np.where(sub_v["inst_buy_prev"].fillna(0).values > 0, 10.0, 0.0)
    comp[:, 9] = np.where(sub_v["lhasa_sh_prev"].fillna(0).values > 0.25, -20.0, 0.0)

    # 验证与 v1_oversold_pry_165_strict_ledger 100% 对齐
    sc_full = 100.0 + comp.sum(axis=1)
    m165 = df_cand[sc_full >= 165].copy()
    m165["score"] = sc_full[sc_full >= 165]
    merged_chk = l1.merge(m165, on=["buy_date", "code"], suffixes=("_ref", "_sim"))
    assert len(merged_chk) == 435 and (merged_chk["net_ret_ref"] - merged_chk["net_ret_sim"]).abs().max() < 1e-4

    def sim_pry(sub_d: pd.DataFrame) -> pd.DataFrame:
        if sub_d.empty:
            return pd.DataFrame()
        srt = sub_d.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True])
        taken, free_after = [], ""
        for r in srt.itertuples(index=False):
            if free_after == "" or r.buy_date > free_after:
                taken.append(r._asdict())
                free_after = r.exit_date
        return pd.DataFrame(taken)

    l16 = sim_pry(m165)
    assert len(l16) == 16 and abs(np.prod(1.0 + l16["net_ret"]) - 1.9411) < 0.01
    return df_cand, comp, factor_names, 100.0, 165, sim_pry


# ==============================================================================
# Strategy 5: 四进五 V2.0 研发池 (18条细分规则 / 7维, 15笔)
# ==============================================================================
def prepare_4to5():
    df_raw = pd.read_parquet(f"{ROOT}/sim-portfolio/backtests_astock2/p3_deep_100/w2_4to5_enriched_master.parquet")
    holders = json.load(open(f"{SANDBOX}/grand_factor_matrix_20261112/pit_top10_all_codes.json", "r"))
    df_tox = pd.read_parquet(f"{ROOT}/sim-portfolio/data/pit_reg_tox_notices_5y_complete.parquet")
    tox_re = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险|违法违规)")
    df_real_tox = df_tox[df_tox["title"].astype(str).str.contains(tox_re)].copy()
    df_real_tox["c6"] = df_real_tox["sec_code"].astype(str).str[:6].str.zfill(6)

    keep_rows = []
    comp_rows = []
    ref_scores = []
    for _, row in df_raw.iterrows():
        r = row.to_dict()
        if not (r.get("buyable_open") == True):
            continue
        c6_val = str(r["code"]).zfill(6)
        bd = str(r["buy_date"])
        d90 = (pd.Timestamp(bd) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
        t_sub = df_real_tox[(df_real_tox["c6"] == c6_val) & (df_real_tox["pub_datetime_cst"] >= d90) & (df_real_tox["pub_datetime_cst"] <= bd + " 09:25:00")]
        if not t_sub.empty:
            continue
        if r.get("f_s_reg_10d", False) or (r.get("has_stock_reg", 0) > 0):
            continue
        hr_pit = float(r.get("tighter_headroom_pit", 0.0))
        if hr_pit < 0.12:
            continue
        if r.get("d4_blown_pm_5m", False) or r.get("d4_blown_pm_proxy", False):
            continue
        op_pct = float(r.get("open_pct", 0.0))
        if op_pct < 0.020 or op_pct > 0.075:
            continue

        raw_h = holders.get(c6_val, [])
        sd = str(r["sig_date"])
        h_list = [x for x in raw_h if isinstance(x, (list, tuple)) and len(x) > 2 and str(x[0]) <= sd]
        if h_list:
            lock_top10 = float(max(h_list, key=lambda x: str(x[1]))[2])
        else:
            h_dict = [x for x in raw_h if isinstance(x, dict) and str(x.get("ann_date", "")) <= sd]
            lock_top10 = float(h_dict[-1].get("top10_ratio", 0.0)) if h_dict else 0.0
        oshare = float(r.get("oshare", 0.0))
        c_px = float(r.get("close", r.get("px_d4", 0.0)))
        real_mcap = float(c_px * oshare * (1.0 - lock_top10 / 100.0) / 1e8) if oshare > 0 else float(r.get("real_free_mcap", 20.0))

        c_vec = np.zeros(18, dtype=float)
        if (lock_top10 >= 50.0) and (12.0 <= real_mcap <= 35.0): c_vec[0] = 8.0
        elif (lock_top10 >= 45.0) or (real_mcap >= 45.0): c_vec[0] = 3.0
        elif (lock_top10 < 45.0) and (real_mcap < 45.0): c_vec[0] = -8.0
        if hr_pit >= 0.25: c_vec[1] = 6.0
        elif hr_pit >= 0.22: c_vec[1] = 4.0
        max_b = int(r.get("mkt_max_board_prev", 0))
        if max_b == 4: c_vec[2] = 5.0
        elif max_b == 5: c_vec[2] = 2.0
        elif max_b >= 6: c_vec[2] = -5.0
        is_sole = int(r.get("is_sole_4b", 0)) == 1
        if is_sole: c_vec[3] = 6.0
        elif int(r.get("is_top1_4b_open", 0)) == 1 and int(r.get("b4_rival_cnt", 0)) < 2: c_vec[3] = 3.0
        else: c_vec[3] = -5.0
        d4_s34 = float(r.get("d4_v34_score", -999))
        if (82.0 <= d4_s34 <= 89.0) and is_sole: c_vec[4] = 5.0
        if bool(r.get("is_held_3to4", False)): c_vec[5] = 4.0
        d4_op = float(r.get("d4_open_pct", 0.0))
        d4_buyable = bool(r.get("d4_buyable_open", True))
        d3_yizi = bool(r.get("d3_prev_is_yizi", False))
        if ((d4_op > 0.092) or (not d4_buyable) or d3_yizi) and (0.020 <= op_pct <= 0.060): c_vec[6] = 3.0
        obc = int(r.get("open_board_count", 0))
        d3_obc = int(r.get("d3_open_board_count", 0))
        to_r = float(r.get("to_ratio_d4_d3", 1.0))
        if (obc >= 1) and (d3_obc >= 1) and (0.70 <= to_r <= 1.35): c_vec[7] = 3.0
        if int(r.get("f_d4_quant_sell", 0)) >= 1: c_vec[8] = -5.0
        if int(r.get("f52_d4_inst_sell", 0)) >= 1: c_vec[9] = -3.0
        if bool(r.get("f50_d4_top_yz_new_buy", False)): c_vec[10] = -3.0
        if int(r.get("f51_d4_lh_cnt", 0)) >= 3: c_vec[11] = -6.0
        if int(r.get("plate_3b_cnt", 0)) >= 1: c_vec[12] = -6.0
        if float(r.get("px_d4", 0.0)) > 20.0: c_vec[13] = -6.0
        if int(r.get("d4_mkt_nuke_cnt", 0)) >= 1: c_vec[14] = -3.0
        if float(r.get("f47_reb_zt_r10", 0.0)) >= 0.20: c_vec[15] = 6.0
        dow = pd.Timestamp(bd).weekday() + 1
        if dow == 1: c_vec[16] = 6.0
        elif dow in (4, 5): c_vec[16] = -3.0
        mo = pd.Timestamp(bd).month
        if mo in (1, 5): c_vec[17] = -6.0

        keep_rows.append({
            "code": c6_val, "name": str(r["name"]), "buy_date": bd, "buy_hhmm": 925,
            "exit_date": str(r["exdt_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"]),
            "exit_hhmm": 1500, "net_ret": float(r["ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"]),
            "open_pct": op_pct,
        })
        comp_rows.append(c_vec)
        ref_scores.append(100.0 + float(c_vec.sum()))

    df_cand = pd.DataFrame(keep_rows)
    comp = np.vstack(comp_rows)
    assert len(df_cand) == 254 and df_cand["open_pct"].abs().max() < 0.25

    factor_names = [
        "F01_锁仓与真流通容量(+8/+3/-8)",
        "F02_双异动余量>=25%/22%(+6/+4)",
        "F03_昨最高板压制4/5/>=6(+5/+2/-5)",
        "F04_四板独苗vs竞价头名(+6/+3/-5)",
        "F05_三板V34得分82~89且独苗(+5)",
        "F06_三进四持仓延伸(+4)",
        "F07_三板一字/强开接力甜区(+3)",
        "F08_三四板充分开板换手过渡(+3)",
        "F09_D4量化席位卖出(-5)",
        "F10_D4机构席位卖出(-3)",
        "F11_D4顶级游资新买(-3)",
        "F12_D4拉萨>=3家(-6)",
        "F13_同板块3板老大哥存在(-6)",
        "F14_D4股价>20元(-6)",
        "F15_D4全市场核按钮>=1(-3)",
        "F16_反包温度计brk>=20%(+6)",
        "F17_星期一vs周四五(+6/-3)",
        "F18_1月或5月退潮窗(-6)",
    ]

    def sim_4to5(sub_d: pd.DataFrame) -> pd.DataFrame:
        if sub_d.empty:
            return pd.DataFrame()
        srt = sub_d.sort_values(["buy_date", "score"], ascending=[True, False])
        taken, free_after = [], ""
        for r in srt.itertuples(index=False):
            if free_after == "" or r.buy_date > free_after:
                taken.append(r._asdict())
                free_after = r.exit_date
        return pd.DataFrame(taken)

    sc_full = 100.0 + comp.sum(axis=1)
    p120 = df_cand[sc_full >= 120].copy()
    p120["score"] = sc_full[sc_full >= 120]
    l15 = sim_4to5(p120)
    assert len(l15) == 15 and abs(np.prod(1.0 + l15["net_ret"]) - 9.4712) < 0.02, f"4to5 mismatch: {len(l15)} {np.prod(1.0 + l15['net_ret'])}"
    return df_cand, comp, factor_names, 100.0, 120, sim_4to5


# ==============================================================================
# 组合顺位联动验证 (高标 > 三进四 > 超跌撬板 > 一进二V18 > 二进三)
# ==============================================================================
def run_portfolio_synergy(results_map: dict) -> dict:
    df_12 = pd.read_csv(f"{CLEAN_REF}/partB_1to2/ledger_base_1to2_v18.csv")
    std_12 = pd.DataFrame({
        "buy_date": df_12["buy_date"].astype(str),
        "exit_date": df_12["exit_date"].astype(str),
        "buy_hhmm": df_12["buy_hhmm"].astype(int),
        "exit_hhmm": df_12["exit_hhmm"].astype(int),
        "code": df_12["code"].astype(str).str.zfill(6),
        "name": df_12["name"].astype(str),
        "net_ret": df_12["net_ret"].astype(float),
        "score": df_12["score"].astype(float),
        "strategy": "一进二_V18",
        "priority": 4,
    })

    def to_std(led: pd.DataFrame, tag: str, prio: int, s_min: str = "2021-11-16") -> pd.DataFrame:
        if led.empty:
            return pd.DataFrame()
        w = led[led["buy_date"] >= s_min].copy()
        return pd.DataFrame({
            "buy_date": w["buy_date"].astype(str),
            "exit_date": w["exit_date"].astype(str),
            "buy_hhmm": w["buy_hhmm"].astype(int) if "buy_hhmm" in w.columns else 925,
            "exit_hhmm": w["exit_hhmm"].astype(int) if "exit_hhmm" in w.columns else 1500,
            "code": w["code"].astype(str).str.zfill(6),
            "name": w["name"].astype(str),
            "net_ret": w["net_ret"].astype(float),
            "score": w["score"].astype(float),
            "strategy": tag,
            "priority": prio,
        })

    def sim_port(pool_df: pd.DataFrame) -> dict:
        srt = pool_df.sort_values(["buy_date", "priority", "score", "buy_hhmm"], ascending=[True, True, False, True])
        picked, cur_ed, cur_eh = [], "", 0
        for r in srt.itertuples(index=False):
            if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and r.buy_hhmm > cur_eh):
                picked.append(r._asdict())
                cur_ed, cur_eh = r.exit_date, int(r.exit_hhmm)
        sl = pd.DataFrame(picked)
        out = {}
        for wn, sd, cp in [
            ("5Y", "2021-11-15", CSI_CANON["全五年(2021-11-16起)"][0]),
            ("OOS_24_26", "2024-01-01", CSI_CANON["近三年(2024-01-01起)"][0]),
            ("2026", "2026-01-01", CSI_CANON["2026全年"][0]),
        ]:
            m = calc_period_metrics(pool_df, sl, sd, "2026-11-16", cp)
            sub_s = sl[sl["buy_date"] >= sd]
            m["strategy_counts"] = sub_s["strategy"].value_counts().to_dict() if not sub_s.empty else {}
            out[wn] = m
        return out

    def build_combo(ver_map: dict, high_key: str = "high_cb42") -> pd.DataFrame:
        p_h = to_std(results_map[high_key]["_ledgers"][ver_map["high"]], f"高标_{ver_map['high']}", 1)
        p_34 = to_std(results_map["3to4"]["_ledgers"][ver_map["3to4"]], f"三进四_{ver_map['3to4']}", 2)
        p_pry = to_std(results_map["pry"]["_ledgers"][ver_map["pry"]], f"撬板_{ver_map['pry']}", 3)
        p_23 = to_std(results_map["2to3"]["_ledgers"][ver_map["2to3"]], f"二进三_{ver_map['2to3']}", 5, s_min="2021-11-16")
        return pd.concat([p_h, p_34, p_pry, std_12, p_23], ignore_index=True)

    configs = {
        "All_Original_CB42": ({"high": "orig", "3to4": "orig", "pry": "orig", "2to3": "orig"}, "high_cb42"),
        "All_P1_Pruned_CB42": ({"high": "p1", "3to4": "p1", "pry": "p1", "2to3": "p1"}, "high_cb42"),
        "All_P2_Minimal_CB42": ({"high": "p2", "3to4": "p2", "pry": "p2", "2to3": "p2"}, "high_cb42"),
        "Swap_High_P1_Only": ({"high": "p1", "3to4": "orig", "pry": "orig", "2to3": "orig"}, "high_cb42"),
        "Swap_3to4_P1_Only": ({"high": "orig", "3to4": "p1", "pry": "orig", "2to3": "orig"}, "high_cb42"),
        "Swap_Pry_P1_Only": ({"high": "orig", "3to4": "orig", "pry": "p1", "2to3": "orig"}, "high_cb42"),
        "Swap_2to3_P1_Only": ({"high": "orig", "3to4": "orig", "pry": "orig", "2to3": "p1"}, "high_cb42"),
        "All_Original_NoCB44": ({"high": "orig", "3to4": "orig", "pry": "orig", "2to3": "orig"}, "high_nocb44"),
        "All_P1_Pruned_NoCB44": ({"high": "p1", "3to4": "p1", "pry": "p1", "2to3": "p1"}, "high_nocb44"),
    }
    return {cname: sim_port(build_combo(vmap, hk)) for cname, (vmap, hk) in configs.items()}


def sanitize(obj):
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items() if k != "_ledgers"}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        if math.isnan(obj):
            return None
        if math.isinf(obj):
            return 999.0 if obj > 0 else -999.0
        return float(obj)
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def main():
    t_start = time.time()
    print("=" * 90)
    print("Exp B: 非一进二全策略双口径 LOFO 消融 + IS无偷看科学剪枝 (P1瘦身 / P2极简)")
    print("=" * 90)

    df_h, c_h, fn_h, bp_h, th_h, sim_h44, sim_h42 = prepare_high_dragon()
    df_34, c_34, fn_34, bp_34, th_34, sim_34 = prepare_3to4()
    df_23, c_23, fn_23, bp_23, th_23, sim_23 = prepare_2to3()
    df_pry, c_pry, fn_pry, bp_pry, th_pry, sim_pry = prepare_pry()
    df_45, c_45, fn_45, bp_45, th_45, sim_45 = prepare_4to5()

    results = {}
    results["high_nocb44"] = run_strategy_ablation(
        "high_nocb44", "高标首阴_V5.1_纯单仓44笔口径(无熔断)", df_h, c_h, fn_h, bp_h, th_h, sim_h44, target_p2=10, is_start="2022-01-01", s5_start="2021-11-15"
    )
    results["high_cb42"] = run_strategy_ablation(
        "high_cb42", "高标首阴_V5.1_实盘42笔口径(连亏熔断)", df_h, c_h, fn_h, bp_h, th_h, sim_h42, target_p2=10, is_start="2022-01-01", s5_start="2021-11-15"
    )
    results["3to4"] = run_strategy_ablation(
        "3to4", "三进四_V3.4(23因子)", df_34, c_34, fn_34, bp_34, th_34, sim_34, target_p2=12, is_start="2022-01-01", s5_start="2021-11-15"
    )
    results["2to3"] = run_strategy_ablation(
        "2to3", "二进三_V1.0(14因子)", df_23, c_23, fn_23, bp_23, th_23, sim_23, target_p2=8, is_start="2021-01-01", s5_start="2021-11-16"
    )
    results["pry"] = run_strategy_ablation(
        "pry", "超跌撬板_V1.0(10因子)", df_pry, c_pry, fn_pry, bp_pry, th_pry, sim_pry, target_p2=5, is_start="2022-01-01", s5_start="2021-11-15", pry_top1_eq=True
    )
    results["4to5"] = run_strategy_ablation(
        "4to5", "四进五_V2.0研发池(18规则/7维)", df_45, c_45, fn_45, bp_45, th_45, sim_45, target_p2=8, is_start="2022-01-01", s5_start="2021-11-15"
    )

    port_synergy = run_portfolio_synergy(results)
    print("\n=== 5策略纯单仓组合顺位联动验证 (高标 > 三进四 > 撬板 > 一进二 > 二进三) ===")
    for cname, pdata in port_synergy.items():
        w5, wo, w26 = pdata["5Y"], pdata["OOS_24_26"], pdata["2026"]
        print(f"  {cname:24s} | 5Y: {w5['single_n']:3d}b WR={w5['wr_pct']:5.1f}% 1S={w5['nav_1s']:10.2f}x Cap10M={w5['cap10m_mult']:7.2f}x MDD={w5['mdd_pct']:5.1f}% | OOS: {wo['single_n']:3d}b WR={wo['wr_pct']:5.1f}% 1S={wo['nav_1s']:7.2f}x | 26: {w26['single_n']:2d}b {w26['nav_1s']:5.2f}x")

    payload = {
        "metadata": {
            "script": "expB_factor_pruning_all_non_1to2.py",
            "data_as_of_anchor": DATA_AS_OF_ANCHOR,
            "fee_rate": FEE_RATE,
            "methodology": "一进二V16->V17科学剪枝四步法: 双口径LOFO(α原阈值直删 / β仅IS校准阈值盲测OOS) + 四分类 + 严格无偷看IS贪心后向剪枝(P1零损瘦身 / P2极简骨架) + D15五期/HLZ/DSR/CSCV-PBO(S=10)/5策略组合联动",
            "total_elapsed_sec": round(time.time() - t_start, 2),
        },
        "strategies": sanitize(results),
        "portfolio_synergy": sanitize(port_synergy),
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n[DONE] Saved full pruning & ablation audit to {OUT_JSON} in {time.time() - t_start:.2f}s")


if __name__ == "__main__":
    main()
