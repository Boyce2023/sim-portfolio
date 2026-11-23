#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part 2 Audit: Market Water T-1 Factors Integrated into Scoring Rules for:
  1. 二进三 V2.1 (pool_2to3_full_clean.csv, base >= 65, threshold >= 90, step W in {0,2,4,6,8,10})
  2. 超跌撬板 V2.1 (pool_pry_full_clean.csv, base >= 120, threshold >= 165, step W in {0,5,10,15,20,25})

Strict anti-overfitting design:
  - 5 factors: F1(zb_rate), F2(max_b_drop5), F3(dt_3d), F4(prem_3d), F_comp(v2_idx)
  - 3 modes: bonus_only, penalty_only, bidir
  - 2 shapes: discrete (sweet/danger step) & linear (continuous mapping on [0,100] sub-score centered at 50)
  - IS (<= 2023-12-31) strictly selects optimal parameters; OOS (2024-01-01 ~ 2026-11-12/16) & 2026 blind check
  - CSCV PBO (S=8, S=10), left/right W neighborhood smoothness, Trim3/Trim5, full D15 vs CSI 300
"""
import os
import sys
import json
import math
import itertools
import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 violation!"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"

FACTORS = ["F1_zb_rate", "F2_max_b_drop5", "F3_dt_3d", "F4_prem_3d", "F_comp_v2_idx"]
MODES = ["bonus_only", "penalty_only", "bidir"]
SHAPES = ["discrete", "linear"]


def calc_delta(df: pd.DataFrame, factor: str, mode: str, shape: str, weight: float) -> np.ndarray:
    if weight == 0:
        return np.zeros(len(df), dtype=float)

    if factor == "F1_zb_rate":
        v = df["zb_rate_t1"].to_numpy(dtype=float)
        sweet = (v >= 25.0) & (v <= 40.0)
        danger = (v < 25.0) | (v > 40.0)
        s_cont = df["s_zb_t1"].to_numpy(dtype=float)
    elif factor == "F2_max_b_drop5":
        v = df["max_b_drop5_t1"].to_numpy(dtype=float)
        sweet = v >= 2.0
        danger = v <= 0.0
        s_cont = df["s_mb_t1"].to_numpy(dtype=float)
    elif factor == "F3_dt_3d":
        v = df["dt_3d_t1"].to_numpy(dtype=float)
        sweet = v >= 40.0
        danger = v <= 12.0
        s_cont = df["s_dt_t1"].to_numpy(dtype=float)
    elif factor == "F4_prem_3d":
        v = df["prem_3d_t1"].to_numpy(dtype=float)
        sweet = v <= 1.0
        danger = v > 3.0
        s_cont = df["s_p3_t1"].to_numpy(dtype=float)
    elif factor == "F_comp_v2_idx":
        v = df["v2_idx_t1"].to_numpy(dtype=float)
        sweet = v >= 65.0
        danger = v < 45.0
        s_cont = df["v2_idx_t1"].to_numpy(dtype=float)
    else:
        raise ValueError(factor)

    if shape == "discrete":
        if mode == "bonus_only":
            return np.where(sweet, float(weight), 0.0)
        elif mode == "penalty_only":
            return np.where(danger, -float(weight), 0.0)
        else:
            return np.where(sweet, float(weight), np.where(danger, -float(weight), 0.0))
    else:
        u = (s_cont - 50.0) / 50.0  # in [-1, 1]
        if mode == "bonus_only":
            return float(weight) * np.maximum(0.0, u)
        elif mode == "penalty_only":
            return -float(weight) * np.maximum(0.0, -u)
        else:
            return float(weight) * u


def run_single_slot(sub: pd.DataFrame, strat: str) -> pd.DataFrame:
    if sub.empty:
        return pd.DataFrame(columns=["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "base_score", "adj_score", "net_ret"])
    if strat == "2to3":
        srt = sub.sort_values(["buy_date", "adj_score", "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True])
        taken = []
        free_dt, free_hh = "", 0
        for r in srt.itertuples(index=False):
            if (not free_dt) or (r.buy_date > free_dt) or (r.buy_date == free_dt and int(r.buy_hhmm) > free_hh):
                taken.append({
                    "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm),
                    "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
                    "code": r.code, "name": r.name,
                    "base_score": float(r.base_score), "adj_score": float(r.adj_score),
                    "net_ret": float(r.net_ret),
                })
                free_dt, free_hh = r.exit_date, int(r.exit_hhmm)
    else:  # pry
        srt = sub.sort_values(["buy_date", "adj_score", "bias10", "code"], ascending=[True, False, True, True])
        taken = []
        free_dt = ""
        for r in srt.itertuples(index=False):
            if (not free_dt) or (r.buy_date > free_dt):
                taken.append({
                    "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm),
                    "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
                    "code": r.code, "name": r.name,
                    "base_score": float(r.base_score), "adj_score": float(r.adj_score),
                    "net_ret": float(r.net_ret),
                })
                free_dt = r.exit_date
    return pd.DataFrame(taken)


def calc_metrics(rr: np.ndarray, eq_rr: np.ndarray, csi_pct: float, raw_cnt: int) -> dict:
    n = len(rr)
    eq_nav = float(np.prod(1.0 + eq_rr)) if len(eq_rr) > 0 else 1.0
    if n == 0:
        return {
            "raw_n": int(raw_cnt), "n": 0, "wr": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "nav": 1.0, "ret_pct": 0.0, "mdd": 0.0, "eq_nav": round(eq_nav, 4),
            "trim3_nav": 1.0, "trim5_nav": 1.0, "csi_pct": round(csi_pct, 2),
            "excess_pp": round(-csi_pct, 2), "eq_excess_pp": round((eq_nav - 1.0) * 100.0 - csi_pct, 2),
            "calmar": 0.0,
        }
    w, l = rr[rr > 0], rr[rr <= 0]
    wr = float((rr > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    nc = np.cumprod(1.0 + rr)
    pk = np.maximum.accumulate(np.insert(nc, 0, 1.0))[1:]
    mdd = float(np.max((pk - nc) / pk) * 100.0)
    nav = float(nc[-1])
    ret_pct = (nav - 1.0) * 100.0
    sr = np.sort(rr)
    t3 = float(np.prod(1.0 + sr[:-3])) if n > 3 else 1.0
    t5 = float(np.prod(1.0 + sr[:-5])) if n > 5 else 1.0
    calmar = ret_pct / mdd if mdd > 0.01 else (ret_pct if ret_pct > 0 else 0.0)
    return {
        "raw_n": int(raw_cnt),
        "n": int(n),
        "wr": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rr.mean() * 100.0), 2),
        "nav": round(nav, 4),
        "ret_pct": round(ret_pct, 2),
        "mdd": round(mdd, 2),
        "eq_nav": round(eq_nav, 4),
        "trim3_nav": round(t3, 4),
        "trim5_nav": round(t5, 4),
        "csi_pct": round(csi_pct, 2),
        "excess_pp": round(ret_pct - csi_pct, 2),
        "eq_excess_pp": round((eq_nav - 1.0) * 100.0 - csi_pct, 2),
        "calmar": round(calmar, 3),
    }


def get_csi_ret(sh300: dict, all_dts: list[str], s_dt: str, e_dt: str) -> float:
    prevs = [d for d in all_dts if d < s_dt]
    p0 = sh300[prevs[-1]] if prevs else sh300[all_dts[0]]
    p1s = [d for d in all_dts if d <= e_dt]
    p1 = sh300[p1s[-1]]
    return float((p1 / p0 - 1.0) * 100.0)


def cscv_pbo(R: np.ndarray, n_groups: int) -> dict:
    n_days = R.shape[0]
    gs = n_days // n_groups
    gidx = [list(range(i * gs, (i + 1) * gs if i < n_groups - 1 else n_days)) for i in range(n_groups)]
    combos = list(itertools.combinations(range(n_groups), n_groups // 2))
    omegas, logits = [], []
    for te in combos:
        tri = [x for k in range(n_groups) if k not in te for x in gidx[k]]
        tei = [x for k in te for x in gidx[k]]
        rt, re_ = R[tri], R[tei]
        st_std = rt.std(0, ddof=1)
        se_std = re_.std(0, ddof=1)
        st = np.where(st_std > 1e-12, rt.mean(0) / st_std, 0.0)
        se = np.where(se_std > 1e-12, re_.mean(0) / se_std, 0.0)
        b = int(np.argmax(st))
        rk = float(np.mean(se > se[b]))
        omegas.append(rk)
        w = max(1e-4, min(1.0 - 1e-4, rk))
        logits.append(math.log(w / (1.0 - w)))
    return {
        "n_groups": n_groups,
        "n_combos": len(combos),
        "n_configs": int(R.shape[1]),
        "pbo_pct": round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2),
        "mean_rank_oos": round(float(np.mean(omegas)), 4),
        "logits_mean": round(float(np.mean(logits)), 4),
    }


def eval_config_full(pool: pd.DataFrame, strat: str, thr: float, delta: np.ndarray,
                     sh300: dict, all_dts: list[str], wins: list[tuple]) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    w = pool.copy()
    w["adj_score"] = w["base_score"].to_numpy(dtype=float) + delta
    elig = w[w["adj_score"] >= thr].copy()
    led = run_single_slot(elig, strat)

    res = {}
    for wname, s_dt, e_dt, csi_p in wins:
        el_w = elig[(elig["buy_date"] >= s_dt) & (elig["buy_date"] <= e_dt)]
        eq_rr = el_w.groupby("buy_date")["net_ret"].mean().sort_index().to_numpy(dtype=float) if len(el_w) else np.array([])
        led_w = led[(led["buy_date"] >= s_dt) & (led["buy_date"] <= e_dt)] if not led.empty else led
        rr = led_w["net_ret"].to_numpy(dtype=float) if not led_w.empty else np.array([])
        res[wname] = calc_metrics(rr, eq_rr, csi_p, len(el_w))
    return res, led, elig


def audit_strategy(strat: str, pool_path: str, thr: float, weights: list[int], sh300: dict, all_dts: list[str]) -> dict:
    pool = pd.read_csv(pool_path, dtype={"code": str})
    pool["code"] = pool["code"].astype(str).str.zfill(6)
    pool["buy_date"] = pool["buy_date"].astype(str).str[:10]
    pool["exit_date"] = pool["exit_date"].astype(str).str[:10]

    # Window definitions (note OOS_1112 as prompt asks AND OOS_1116 canonical V19.1)
    start_5y = "2021-11-16"
    wins = [
        ("IS", start_5y, "2023-12-31", get_csi_ret(sh300, all_dts, start_5y, "2023-12-31")),
        ("OOS_1112", "2024-01-01", "2026-11-12", get_csi_ret(sh300, all_dts, "2024-01-01", "2026-11-12")),
        ("OOS_1116", "2024-01-01", "2026-11-16", get_csi_ret(sh300, all_dts, "2024-01-01", "2026-11-16")),
        ("2026_1112", "2026-01-01", "2026-11-12", get_csi_ret(sh300, all_dts, "2026-01-01", "2026-11-12")),
        ("2026_1116", "2026-01-01", "2026-11-16", get_csi_ret(sh300, all_dts, "2026-01-01", "2026-11-16")),
        ("3Y_1112", "2023-11-16", "2026-11-12", get_csi_ret(sh300, all_dts, "2023-11-16", "2026-11-12")),
        ("3Y_1116", "2023-11-16", "2026-11-16", get_csi_ret(sh300, all_dts, "2023-11-16", "2026-11-16")),
        ("5Y_1112", start_5y, "2026-11-12", get_csi_ret(sh300, all_dts, start_5y, "2026-11-12")),
        ("5Y_1116", start_5y, "2026-11-16", get_csi_ret(sh300, all_dts, start_5y, "2026-11-16")),
    ]

    # Single-factor signal correlations on pool (IS vs OOS, eligible vs full pool)
    corrs = {}
    elig_base = pool[pool["base_score"] >= thr]
    for sub_name, sub_df in [("full_pool", pool), ("base_eligible", elig_base)]:
        corrs[sub_name] = {}
        for fac, col in [("F1_zb_rate", "zb_rate_t1"), ("F2_max_b_drop5", "max_b_drop5_t1"),
                         ("F3_dt_3d", "dt_3d_t1"), ("F4_prem_3d", "prem_3d_t1"), ("F_comp_v2_idx", "v2_idx_t1")]:
            use_col = "s_zb_t1" if fac == "F1_zb_rate" else col
            sign_note = "prem_3d negative=good" if fac == "F4_prem_3d" else "higher=good"
            c_rec = {"note": sign_note}
            for wn, msk in [("ALL", sub_df["buy_date"] >= start_5y),
                            ("IS", sub_df["buy_date"] <= "2023-12-31"),
                            ("OOS", sub_df["buy_date"] >= "2024-01-01")]:
                sd = sub_df[msk]
                if len(sd) >= 5 and sd[use_col].nunique() > 1:
                    r_sp, p_sp = stats.spearmanr(sd[use_col], sd["net_ret"])
                    c_rec[wn] = {"n": int(len(sd)), "spearman": round(float(r_sp), 4), "p": round(float(p_sp), 4)}
                else:
                    c_rec[wn] = {"n": int(len(sd)), "spearman": 0.0, "p": 1.0}
            corrs[sub_name][fac] = c_rec

    # Baseline (W=0)
    base_metrics, base_led, base_elig = eval_config_full(pool, strat, thr, np.zeros(len(pool)), sh300, all_dts, wins)
    base_keys = set(zip(base_led["buy_date"], base_led["code"]))

    # Trading day index for PBO matrix (canonical 5Y days from first pool date or start_5y to 2026-11-12)
    t_start = start_5y if strat == "2to3" else pool["buy_date"].min()
    t_days = [d for d in all_dts if t_start <= d <= "2026-11-16"]
    day_idx = {d: i for i, d in enumerate(t_days)}

    def led_to_day_vec(led_df: pd.DataFrame) -> np.ndarray:
        v = np.zeros(len(t_days), dtype=float)
        for r in led_df.itertuples(index=False):
            di = day_idx.get(r.exit_date)
            if di is not None:
                v[di] += float(r.net_ret)
        return v

    all_configs = []
    daily_vecs = [led_to_day_vec(base_led)]  # index 0 = Baseline

    min_is_n = 20 if strat == "2to3" else 5
    nz_weights = [w for w in weights if w > 0]
    step_sz = nz_weights[0]

    for fac in FACTORS:
        for mode in MODES:
            for shape in SHAPES:
                for w_val in nz_weights:
                    delta = calc_delta(pool, fac, mode, shape, w_val)
                    m_res, led, elig = eval_config_full(pool, strat, thr, delta, sh300, all_dts, wins)
                    cur_keys = set(zip(led["buy_date"], led["code"]))
                    added_n = len(cur_keys - base_keys)
                    dropped_n = len(base_keys - cur_keys)
                    is_keys_base = set(zip(base_led[base_led["buy_date"] <= "2023-12-31"]["buy_date"], base_led[base_led["buy_date"] <= "2023-12-31"]["code"]))
                    is_keys_cur = set(zip(led[led["buy_date"] <= "2023-12-31"]["buy_date"], led[led["buy_date"] <= "2023-12-31"]["code"]))
                    is_changed = len(is_keys_base ^ is_keys_cur)

                    rec = {
                        "id": f"{fac}|{mode}|{shape}|W{w_val}",
                        "factor": fac, "mode": mode, "shape": shape, "weight": w_val,
                        "is_changed": is_changed,
                        "total_added": added_n, "total_dropped": dropped_n,
                        "metrics": m_res,
                        "_vec_idx": len(daily_vecs),
                    }
                    all_configs.append(rec)
                    daily_vecs.append(led_to_day_vec(led))

    R_full = np.column_stack(daily_vecs)  # (T_days, 151)
    pbo_full_s8 = cscv_pbo(R_full, 8)
    pbo_full_s10 = cscv_pbo(R_full, 10)

    # Strict IS selection: ONLY look at metrics["IS"]!
    def is_rank_key(c):
        mis = c["metrics"]["IS"]
        valid = 1 if mis["n"] >= min_is_n else 0
        # Primary: IS single-slot NAV, tie-break: lower MDD, higher IS eq_nav, smaller weight, discrete before linear
        return (valid, mis["nav"], -mis["mdd"], mis["eq_nav"], -c["weight"], 1 if c["shape"] == "discrete" else 0)

    def lookup_cfg(fac, mode, shape, w_val):
        if w_val == 0:
            return {"id": "BASELINE|W0", "weight": 0, "metrics": base_metrics}
        for c in all_configs:
            if c["factor"] == fac and c["mode"] == mode and c["shape"] == shape and c["weight"] == w_val:
                return c
        return None

    per_factor_is_best = {}
    for fac in FACTORS:
        f_cfgs = [c for c in all_configs if c["factor"] == fac]
        # Best non-zero in IS
        best_nz = max(f_cfgs, key=is_rank_key)
        # Also check best among configs that actually changed IS trades (if any)
        changed_cfgs = [c for c in f_cfgs if c["is_changed"] > 0]
        best_chg = max(changed_cfgs, key=is_rank_key) if changed_cfgs else best_nz

        # Per-factor PBO (30 configs + Baseline = 31)
        f_idxs = [0] + [c["_vec_idx"] for c in f_cfgs]
        R_fac = R_full[:, f_idxs]
        pbo_f_s8 = cscv_pbo(R_fac, 8)
        pbo_f_s10 = cscv_pbo(R_fac, 10)

        # Left/Right W neighborhood around best_nz (along same mode & shape)
        w_best = best_nz["weight"]
        neigh = []
        for w_try in weights:
            nc = lookup_cfg(fac, best_nz["mode"], best_nz["shape"], w_try)
            neigh.append({
                "weight": w_try,
                "is_n": nc["metrics"]["IS"]["n"], "is_nav": nc["metrics"]["IS"]["nav"], "is_wr": nc["metrics"]["IS"]["wr"],
                "is_eq_nav": nc["metrics"]["IS"]["eq_nav"],
                "oos_n": nc["metrics"]["OOS_1112"]["n"], "oos_nav": nc["metrics"]["OOS_1112"]["nav"], "oos_wr": nc["metrics"]["OOS_1112"]["wr"],
                "oos_eq_nav": nc["metrics"]["OOS_1112"]["eq_nav"],
                "y26_nav": nc["metrics"]["2026_1112"]["nav"],
                "all_5y_nav": nc["metrics"]["5Y_1116"]["nav"],
            })

        # Compute trade diff details for best_nz vs baseline
        d_best = calc_delta(pool, fac, best_nz["mode"], best_nz["shape"], best_nz["weight"])
        _, led_best, _ = eval_config_full(pool, strat, thr, d_best, sh300, all_dts, wins)
        best_keys = set(zip(led_best["buy_date"], led_best["code"]))
        added_trades = led_best[[(bd, cd) not in base_keys for bd, cd in zip(led_best["buy_date"], led_best["code"])]].to_dict(orient="records")
        dropped_trades = base_led[[(bd, cd) not in best_keys for bd, cd in zip(base_led["buy_date"], base_led["code"])]].to_dict(orient="records")

        # Also check best IS by daily equal-weight (eq_nav) for cross-validation
        best_eq_is = max(f_cfgs, key=lambda c: (c["metrics"]["IS"]["eq_nav"], -c["weight"]))

        per_factor_is_best[fac] = {
            "is_best_nz": {k: v for k, v in best_nz.items() if k != "_vec_idx"},
            "is_best_changed": {k: v for k, v in best_chg.items() if k != "_vec_idx"},
            "is_best_eq": {k: v for k, v in best_eq_is.items() if k != "_vec_idx"},
            "beats_baseline_in_is": bool(best_nz["metrics"]["IS"]["nav"] > base_metrics["IS"]["nav"]),
            "beats_baseline_in_oos": bool(best_nz["metrics"]["OOS_1112"]["nav"] > base_metrics["OOS_1112"]["nav"]),
            "pbo_s8": pbo_f_s8,
            "pbo_s10": pbo_f_s10,
            "neighborhood_curve": neigh,
            "added_trades_sample": added_trades[:12],
            "dropped_trades_sample": dropped_trades[:12],
        }

    overall_best_is = max(all_configs, key=is_rank_key)
    overall_best_eq_is = max(all_configs, key=lambda c: (c["metrics"]["IS"]["eq_nav"], -c["weight"]))

    # Also summarize mode-level (bonus_only / penalty_only / bidir) IS->OOS behavior
    mode_summary = {}
    for mode in MODES:
        m_cfgs = [c for c in all_configs if c["mode"] == mode]
        bm = max(m_cfgs, key=is_rank_key)
        is_beat_pct = float(np.mean([c["metrics"]["IS"]["nav"] > base_metrics["IS"]["nav"] for c in m_cfgs]) * 100.0)
        oos_beat_pct = float(np.mean([c["metrics"]["OOS_1112"]["nav"] > base_metrics["OOS_1112"]["nav"] for c in m_cfgs]) * 100.0)
        eq_oos_beat_pct = float(np.mean([c["metrics"]["OOS_1112"]["eq_nav"] > base_metrics["OOS_1112"]["eq_nav"] for c in m_cfgs]) * 100.0)
        mode_summary[mode] = {
            "n_configs": len(m_cfgs),
            "is_beat_base_pct": round(is_beat_pct, 1),
            "oos_ss_beat_base_pct": round(oos_beat_pct, 1),
            "oos_eq_beat_base_pct": round(eq_oos_beat_pct, 1),
            "is_best_id": bm["id"],
            "is_best_is_nav": bm["metrics"]["IS"]["nav"],
            "is_best_oos_nav": bm["metrics"]["OOS_1112"]["nav"],
            "is_best_2026_nav": bm["metrics"]["2026_1112"]["nav"],
        }

    return {
        "strategy": strat,
        "base_threshold": thr,
        "weights_grid": weights,
        "pool_rows": int(len(pool)),
        "pool_days": int(pool["buy_date"].nunique()),
        "baseline": base_metrics,
        "correlations": corrs,
        "pbo_all_151_s8": pbo_full_s8,
        "pbo_all_151_s10": pbo_full_s10,
        "overall_is_best": {k: v for k, v in overall_best_is.items() if k != "_vec_idx"},
        "overall_is_eq_best": {k: v for k, v in overall_best_eq_is.items() if k != "_vec_idx"},
        "mode_summary": mode_summary,
        "per_factor_is_best": per_factor_is_best,
        "all_configs_compact": [
            {
                "id": c["id"], "factor": c["factor"], "mode": c["mode"], "shape": c["shape"], "weight": c["weight"],
                "is_n": c["metrics"]["IS"]["n"], "is_nav": c["metrics"]["IS"]["nav"], "is_eq": c["metrics"]["IS"]["eq_nav"],
                "oos_n": c["metrics"]["OOS_1112"]["n"], "oos_nav": c["metrics"]["OOS_1112"]["nav"], "oos_eq": c["metrics"]["OOS_1112"]["eq_nav"],
                "y26_nav": c["metrics"]["2026_1112"]["nav"], "all5y_nav": c["metrics"]["5Y_1116"]["nav"],
            }
            for c in all_configs
        ],
    }


def main():
    sh300 = json.load(open(IDX_JSON, encoding="utf-8"))["sh000300"]
    all_dts = sorted(sh300.keys())

    res_2to3 = audit_strategy("2to3", f"{OUT_DIR}/pool_2to3_full_clean.csv", 90.0, [0, 2, 4, 6, 8, 10], sh300, all_dts)
    res_pry = audit_strategy("pry", f"{OUT_DIR}/pool_pry_full_clean.csv", 165.0, [0, 5, 10, 15, 20, 25], sh300, all_dts)

    out = {"two_to_three": res_2to3, "pry": res_pry}
    with open(f"{OUT_DIR}/results_part2_2to3_pry.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    for label, r in [("2TO3", res_2to3), ("PRY", res_pry)]:
        b = r["baseline"]
        print(f"\n=== {label} BASELINE === IS: n={b['IS']['n']} WR={b['IS']['wr']}% NAV={b['IS']['nav']}x EQ={b['IS']['eq_nav']}x MDD={b['IS']['mdd']}% | OOS(to 1112): n={b['OOS_1112']['n']} WR={b['OOS_1112']['wr']}% NAV={b['OOS_1112']['nav']}x EQ={b['OOS_1112']['eq_nav']}x Ex={b['OOS_1112']['excess_pp']:+.1f}pp | 2026: n={b['2026_1112']['n']} NAV={b['2026_1112']['nav']}x | 5Y(1116): {b['5Y_1116']['nav']}x")
        print(f"  PBO(151) S8={r['pbo_all_151_s8']['pbo_pct']}% S10={r['pbo_all_151_s10']['pbo_pct']}% | Modes={r['mode_summary']}")
        for fac, fd in r["per_factor_is_best"].items():
            c = fd["is_best_nz"]
            m = c["metrics"]
            print(f"  {fac:15s} -> {c['id']:38s} | IS:{m['IS']['n']}b/{m['IS']['nav']}x(eq {m['IS']['eq_nav']}x) | OOS:{m['OOS_1112']['n']}b/{m['OOS_1112']['nav']}x(eq {m['OOS_1112']['eq_nav']}x, Ex {m['OOS_1112']['excess_pp']:+.1f}pp) | 2026:{m['2026_1112']['nav']}x | 5Y:{m['5Y_1116']['nav']}x | PBO_S8={fd['pbo_s8']['pbo_pct']}%")


if __name__ == "__main__":
    main()
