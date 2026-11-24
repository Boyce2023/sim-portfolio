#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part D1: Comprehensive Institutional 7-Pillar + Anti-Overfitting Dual-Suite Validation
for Upgraded 1to2 V20 (`ledger_1to2_v20_cand.csv`, 92 trades, 474.35x) vs Original 1to2 V19 (97 trades, 332.72x).

Hard Rules Enforced:
  1. 100% local read-only; ZERO import yfinance (D12); ZERO network calls; all SQLite mode=ro.
  2. ZERO cap10m / cap1000w / 1000万封顶 calculation or mention anywhere.
  3. Outputs strictly inside sim-portfolio/output/six_strategies_v20_upgrade_20261124/partD_final_jianyan/.
"""
import itertools
import json
import math
import os
import sys
import time
import warnings
from datetime import datetime, timezone

sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partD_final_jianyan"
os.makedirs(OUT_DIR, exist_ok=True)

VAL5_DIR = f"{SIM}/output/five_strategies_institutional_validation_20261124"
PARTA_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades"
PARTC_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
MW3_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part3_1to2"
V11_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
V1_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"

for p in (VAL5_DIR, PARTA_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
import pandas as pd
import scipy.stats as stats
import run_part1_alpha_micro_regime as p1
import run_part2_signal_stats as p2
import run_part3_hygiene_portfolio_cusum as p3
import mod_common as mc
import mod_1to2 as m12

SEED = 20261124
BOOT_B = 5000
START_DATE = "2021-11-16"
END_DATE = "2026-11-16"
ORIG_FEE_RT = 0.0020
ORIG_FEE_OW_BPS = 10.0


def sf(x, digits=6):
    if x is None:
        return None
    v = float(x)
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, digits)


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def sim_1to2_from_pretrig(pretrig: pd.DataFrame, delta: np.ndarray, skip_mask: np.ndarray | None = None,
                          force_base: bool = False) -> tuple[pd.DataFrame, list[tuple[str, float]], np.ndarray]:
    """Reconstruct exact 1to2 single-slot & daily-EW trades from _cache_pretrig_pool with full daily gate checks."""
    pt = pretrig.copy()
    if force_base:
        keep_full = pt["base_pass_v19"].to_numpy(dtype=bool)
        if skip_mask is not None:
            keep_full = keep_full & (~skip_mask)
        sub = pt[keep_full].copy()
        sub["_sv"] = sub["sv_base"]
        sub["_sc_eff"] = sub["base_score"]
    else:
        sc_adj = pt["base_score"].to_numpy(dtype=float) + delta
        m_t1 = pt["elig_t1"].to_numpy(dtype=bool) & (sc_adj >= pt["thr_vec"].to_numpy(dtype=float))
        m_t2 = pt["elig_t2"].to_numpy(dtype=bool)
        m_mon = pt["elig_mon"].to_numpy(dtype=bool) & (sc_adj >= pt["thr_vec"].to_numpy(dtype=float))
        m_dom = pt["elig_dom295"].to_numpy(dtype=bool) & ((sc_adj - pt["sc_t3_pen"].to_numpy(dtype=float)) >= 295.0)
        tot_v18 = m_t1 | m_t2 | m_mon
        tot_v19 = tot_v18 | m_dom
        sv = np.where(m_t1 | m_t2, sc_adj + 1000.0, np.where(m_mon, sc_adj, sc_adj + 500.0))

        sub_all = pt[tot_v19].copy()
        sub_all["_sv"] = sv[tot_v19]
        sub_all["_is_v18"] = tot_v18[tot_v19]
        sub_all["_sc_eff"] = sc_adj[tot_v19]

        bad_dts, dom_no_dragon = set(), set()
        for d, grp in sub_all.groupby("buy_date", sort=False):
            if (grp["rk_theme"] == 1).any():
                top_rk = grp.sort_values("_sv", ascending=False).iloc[0]["rk_theme"]
                if pd.notna(top_rk) and top_rk >= 4:
                    bad_dts.add(d)
            t1_p = grp["t1_dom_plate"].iloc[0]
            if t1_p:
                v18_g = grp[grp["_is_v18"]]
                if not (len(v18_g) > 0 and (v18_g["plate"] == t1_p).any()):
                    dom_no_dragon.add(d)
        keep_sub = (~sub_all["buy_date"].isin(bad_dts)) & (~(sub_all["buy_date"].isin(dom_no_dragon) & (sub_all["rk_theme"] == 3)))
        sub = sub_all[keep_sub].copy()
        keep_full = np.zeros(len(pt), dtype=bool)
        keep_full[sub.index.to_numpy()] = True
        if skip_mask is not None:
            keep_full = keep_full & (~skip_mask)
            sub = sub[(~skip_mask)[sub.index.to_numpy()]].copy()

    if sub.empty:
        return pd.DataFrame(), [], np.zeros(len(pt), dtype=bool)

    sub.sort_values(["buy_date", "_sv", "code"], ascending=[True, False, True], inplace=True)
    picked, free_dt, free_open = [], "", False
    eq_daily = []
    for d2, grp in sub.groupby("buy_date", sort=True):
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            top = grp.iloc[0]
            if bool(top["sim_ok"]):
                row_d = top.to_dict()
                row_d["score"] = round(float(row_d["_sc_eff"]), 1)
                picked.append(row_d)
                free_dt = str(top["exit_date"])
                free_open = bool(top["exit_at_open"])
        ok_g = grp[grp["sim_ok"]]
        if not ok_g.empty:
            eq_daily.append((d2, float(ok_g["net_ret"].mean())))

    df_pk = pd.DataFrame(picked)
    if not df_pk.empty:
        df_pk["c6"] = df_pk["code"].astype(str).str.zfill(6)
    return df_pk, eq_daily, keep_full


def run_old_overfitting_suite(pt: pd.DataFrame, fb20_dts: set[str], v20_df: pd.DataFrame, v19_df: pd.DataFrame,
                              pool_df: pd.DataFrame, sh300: dict, all_dts: list[str],
                              by_c: dict, cal_dates: list[str]) -> dict:
    print("[2/7] Running anti-overfitting dual-suite (V20 vs V19, PBO, Monkey, +-20%, 2025-01-01 truncation)...")
    rng = np.random.default_rng(SEED)
    m_cln = pt["buy_date"].isin(fb20_dts).to_numpy(dtype=bool)

    def _eval_variant(label: str, delta: np.ndarray, skip_m=None, force_base: bool = False):
        tr_df, eq_d, _ = sim_1to2_from_pretrig(pt, delta, skip_mask=skip_m, force_base=force_base)
        tr_list = tr_df.to_dict("records")
        wins = mc.all_windows_metrics(tr_list, eq_d, sh300, all_dts)
        tv, dsr150 = mc.hlz_and_dsr150(tr_list, sh300, all_dts, m_trials=150)
        _, dsr30 = mc.hlz_and_dsr150(tr_list, sh300, all_dts, m_trials=30)
        _, dsr200 = mc.hlz_and_dsr150(tr_list, sh300, all_dts, m_trials=200)
        # Daily MTM stats
        daily_s, _, _, _ = p1.compute_daily_mtm(tr_df, by_c, cal_dates, allow_overlap=False)
        d_arr = daily_s.to_numpy(dtype=float)
        csi_arr = np.array([sh300[d] / sh300[all_dts[all_dts.index(d) - 1]] - 1.0 for d in cal_dates], dtype=float)
        d_ex = d_arr - csi_arr
        hlz_d = float(d_ex.mean() / d_ex.std(ddof=1) * math.sqrt(len(d_ex))) if d_ex.std(ddof=1) > 1e-12 else 0.0
        cum_d = np.cumprod(1.0 + d_arr)
        pk_d = np.maximum.accumulate(np.insert(cum_d, 0, 1.0))[1:]
        mdd_d = float(np.max((pk_d - cum_d) / pk_d) * 100.0)
        return {
            "label": label,
            "windows": wins,
            "daily_mtm_mdd_pct": sf(mdd_d, 2),
            "hlz_t_trade": tv,
            "hlz_t_daily": sf(hlz_d, 2),
            "dsr_M30": dsr30,
            "dsr_M150": dsr150,
            "dsr_M200": dsr200,
        }, tr_list, tr_df

    res_v20, tr20_list, tr20_df = _eval_variant("1to2_V20", np.where(m_cln, -25.0, 0.0))
    res_v19, tr19_list, tr19_df = _eval_variant("1to2_V19", np.zeros(len(pt)), force_base=True)
    assert len(tr20_df) == len(v20_df) == 92
    assert np.max(np.abs(tr20_df["net_ret"].to_numpy() - v20_df["net_ret"].to_numpy())) < 1e-12
    assert len(tr19_df) == len(v19_df) == 97
    assert np.max(np.abs(tr19_df["net_ret"].to_numpy() - v19_df["net_ret"].to_numpy())) < 1e-12

    # Monkey MC (5,000x) on full_pool_447 & same_day_pool_447
    pool_rets = pool_df["net_ret"].to_numpy(dtype=float)
    by_dt_pool = {dt: grp["net_ret"].to_numpy(dtype=float) for dt, grp in pool_df.groupby("buy_date")}

    def _monkey(tr_df_in: pd.DataFrame):
        rets = tr_df_in["net_ret"].to_numpy(dtype=float)
        n = len(rets)
        act_mean = float(rets.mean())
        act_nav = float(np.prod(1.0 + rets))
        # A: full pool 447 bootstrap
        idx_full = rng.integers(0, len(pool_rets), size=(5000, n))
        draws_full = pool_rets[idx_full]
        p_full_mean = float((np.sum(draws_full.mean(axis=1) >= act_mean) + 1) / 5001.0)
        p_full_nav = float((np.sum(np.prod(1.0 + draws_full, axis=1) >= act_nav) + 1) / 5001.0)
        # B: same-day pool draw (fallback to full pool if only 1/0 on date)
        day_cands = [by_dt_pool.get(str(bd), pool_rets) for bd in tr_df_in["buy_date"]]
        draws_sd = np.column_stack([c[rng.integers(0, len(c), size=5000)] for c in day_cands])
        p_sd_mean = float((np.sum(draws_sd.mean(axis=1) >= act_mean) + 1) / 5001.0)
        p_sd_nav = float((np.sum(np.prod(1.0 + draws_sd, axis=1) >= act_nav) + 1) / 5001.0)
        return {
            "n": int(n),
            "actual_mean_pct": sf(act_mean * 100.0, 2),
            "actual_nav": sf(act_nav, 2),
            "pool447_mean_pct": sf(pool_rets.mean() * 100.0, 2),
            "full_pool447_p_mean": sf(p_full_mean, 5),
            "full_pool447_p_nav": sf(p_full_nav, 5),
            "same_day_pool_p_mean": sf(p_sd_mean, 5),
            "same_day_pool_p_nav": sf(p_sd_nav, 5),
        }

    # +-20% penalty perturbation (-20 / -25 / -30 + 0/-15/-35/SKIP)
    pen_grid, pen_trs = [], []
    for w in (0, 15, 20, 25, 30, 35):
        r_w, tr_w, _ = _eval_variant(f"fb20cln(-{w})", np.where(m_cln, -float(w), 0.0))
        pen_grid.append(r_w)
        pen_trs.append(tr_w)
    r_skip, _, _ = _eval_variant("fb20cln(SKIP)", np.zeros(len(pt)), skip_m=m_cln)
    pen_grid.append(r_skip)

    # +-20% score-margin perturbation inside V20 around 304.8 (margin vs 295 ~ 10pt -> +-2/+-4)
    sc_v20 = tr20_df["score"].to_numpy(dtype=float)
    thr_q14_v20 = [tr20_df.to_dict("records")] + [
        tr20_df[tr20_df["score"] >= float(np.quantile(sc_v20, 0.05 + (v / 14.0) * 0.40))].to_dict("records")
        for v in range(1, 14)
    ]
    sc_v19 = tr19_df["score"].to_numpy(dtype=float)
    thr_q14_v19 = [tr19_df.to_dict("records")] + [
        tr19_df[tr19_df["score"] >= float(np.quantile(sc_v19, 0.05 + (v / 14.0) * 0.40))].to_dict("records")
        for v in range(1, 14)
    ]

    # Threshold ladder inside V20 (295..318)
    v20_thr_trs, v19_thr_trs = [], []
    v20_thr_pert = []
    pt_v20_sc = pt["base_score"].to_numpy(dtype=float) - np.where(m_cln, 25.0, 0.0)
    for thr_d in (-6.0, -3.0, 0.0, 3.0, 6.0):
        # Shift effective threshold via opposite constant delta on score
        r_th, tr_th, _ = _eval_variant(f"v20_thr_shift({thr_d:+.0f})", np.where(m_cln, -25.0, 0.0) - thr_d)
        v20_thr_pert.append(r_th)
        v20_thr_trs.append(tr_th)
        _, tr_th19, _ = _eval_variant(f"v19_thr_shift({thr_d:+.0f})", np.full(len(pt), -thr_d))
        v19_thr_trs.append(tr_th19)

    pbo = {
        "fb20cln_penalty_grid_7": {"S8": mc.calc_cscv_pbo(pen_trs, all_dts, 8), "S10": mc.calc_cscv_pbo(pen_trs, all_dts, 10)},
        "v20_score_q14": {"S8": mc.calc_cscv_pbo(thr_q14_v20, all_dts, 8), "S10": mc.calc_cscv_pbo(thr_q14_v20, all_dts, 10)},
        "v19_score_q14": {"S8": mc.calc_cscv_pbo(thr_q14_v19, all_dts, 8), "S10": mc.calc_cscv_pbo(thr_q14_v19, all_dts, 10)},
        "v20_thr_ladder_5": {"S8": mc.calc_cscv_pbo(v20_thr_trs, all_dts, 8), "S10": mc.calc_cscv_pbo(v20_thr_trs, all_dts, 10)},
        "v19_thr_ladder_5": {"S8": mc.calc_cscv_pbo(v19_thr_trs, all_dts, 8), "S10": mc.calc_cscv_pbo(v19_thr_trs, all_dts, 10)},
    }

    # Physical 2025-01-01 truncation proof on V20 (zero future data <= 2024-12-31)
    hf_t, inv_t, sc_t, _, _ = m12.build_1to2_ctx_and_cache("2024-12-31")
    fb20_tr = {d for d, c in mc.build_fb20_cln_dates_pit("2024-12-31").items() if c >= 2}
    _, tr_t, _, _ = m12.run_1to2_variant(hf_t, inv_t, sc_t, np.where(hf_t["d2_dt"].isin(fb20_tr).to_numpy(), -25.0, 0.0))
    f24 = sorted([t for t in tr20_list if str(t["exit_date"]) <= "2024-12-31"], key=lambda x: (x["buy_date"], x["code"]))
    t24 = sorted([t for t in tr_t if str(t["exit_date"]) <= "2024-12-31"], key=lambda x: (x["buy_date"], x["code"]))
    assert len(f24) == len(t24), f"Trunc len mismatch: {len(f24)} vs {len(t24)}"
    trunc_diff = max(abs(float(a["net_ret"]) - float(b["net_ret"])) for a, b in zip(f24, t24))
    assert trunc_diff == 0.0, f"Truncation mismatch: {trunc_diff}"

    return {
        "V20": res_v20,
        "V19": res_v19,
        "monkey_mc_5000": {"V20": _monkey(tr20_df), "V19": _monkey(tr19_df)},
        "cscv_pbo": pbo,
        "penalty_perturbation_pm20": pen_grid,
        "score_threshold_perturbation": v20_thr_pert,
        "truncation_20250101_v20": {"trades_exiting_le_20241231": len(t24), "max_abs_diff": float(trunc_diff), "pass": trunc_diff == 0.0},
    }


def run_pillar2_clean(led_df: pd.DataFrame, by_c: dict, cal_dates: list[str], bars_5m: dict, zt_tape: pd.DataFrame) -> dict:
    """Exact Pillar 2 institutional capacity, fill stress, adverse selection & +5m/+15m delay (ZERO cap10m)."""
    dt_to_idx = {d: i for i, d in enumerate(cal_dates)}
    n_days = len(cal_dates)
    day_base = [[] for _ in range(n_days)]
    trade_items = []
    for r in led_df.itertuples(index=False):
        bar = by_c[r.c6]
        p0, pe = bar["dt_to_pos"][r.buy_date], bar["dt_to_pos"][r.exit_date]
        b_adj = float(r.buy_price) * bar["adjf"][p0]
        e_adj = float(r.exit_price) * bar["adjf"][pe]
        gfs, idxs = [], []
        for k in range(p0, pe + 1):
            idxs.append(dt_to_idx[bar["dt"][k]])
            if k == p0:
                gfs.append(bar["adj_close"][k] / b_adj)
            elif k < pe:
                gfs.append(bar["adj_close"][k] / bar["adj_close"][k - 1])
            else:
                gfs.append(e_adj / bar["adj_close"][k - 1])
        pg = float(np.prod(gfs))
        sc = math.sqrt((1.0 + float(r.net_ret)) / pg) if pg > 0 else 1.0
        gfs[0] *= sc
        gfs[-1] *= sc
        pos_list = []
        for d_idx, mult in zip(idxs, gfs):
            pos_list.append((d_idx, len(day_base[d_idx])))
            day_base[d_idx].append(mult)
        sig_b = bar["vol20_m1"][p0]
        sig_e = bar["vol20_m1"][pe]
        sig_b = 0.04 if (np.isnan(sig_b) or sig_b <= 0) else float(sig_b)
        sig_e = 0.04 if (np.isnan(sig_e) or sig_e <= 0) else float(sig_e)
        trade_items.append({
            "d0": pos_list[0][0], "pos0": pos_list[0][1],
            "dk": pos_list[-1][0], "posk": pos_list[-1][1],
            "sig_b": sig_b, "sig_e": sig_e,
            "v_b": float(bar["amount"][p0]), "v_e": float(bar["amount"][pe]),
            "net_ret": float(r.net_ret),
        })

    q_grid = [1e6, 3e6, 5e6, 1e7, 2e7, 5e7, 1e8]
    ac_results = {}
    base_0 = p1.eval_ac_metrics(trade_items, day_base, n_days, False, Q=0.0, Y=0.50)
    for Y in (0.50, 0.70):
        grid_out = {}
        for Q in q_grid:
            m = p1.eval_ac_metrics(trade_items, day_base, n_days, False, Q=Q, Y=Y)
            grid_out[f"{int(Q // 1e4)}w"] = {
                "nav_5y": round(m["nav_5y"], 4), "cagr_pct": round(m["cagr_pct"], 2),
                "sharpe": round(m["sharpe"], 3), "avg_trade_ret_pct": round(m["avg_trade_ret_pct"], 3),
                "avg_rt_impact_bps": round(m["avg_rt_impact_bps"], 1),
            }
        ac_results[f"Y_{Y:.2f}"] = {
            "grid": grid_out,
            "breakeven_cap_wan": p1.bisect_capacity(lambda q: p1.eval_ac_metrics(trade_items, day_base, n_days, False, q, Y)["nav_5y"], 1.0),
            "half_cagr_cap_wan": p1.bisect_capacity(lambda q: p1.eval_ac_metrics(trade_items, day_base, n_days, False, q, Y)["cagr_pct"], 0.5 * base_0["cagr_pct"]),
            "half_simple_profit_cap_wan": p1.bisect_capacity(lambda q: p1.eval_ac_metrics(trade_items, day_base, n_days, False, q, Y)["nav_5y"] - 1.0, 0.5 * (base_0["nav_5y"] - 1.0)),
        }

    dyn_comp = {}
    for q0 in (1e6, 5e6):
        nav_cur = 1.0
        for it in trade_items:
            q_t = q0 * nav_cur
            ib = min(0.95, 0.50 * it["sig_b"] * math.sqrt(q_t / it["v_b"])) if it["v_b"] > 0 else 0.95
            ie = min(0.95, 0.50 * it["sig_e"] * math.sqrt(q_t / it["v_e"])) if it["v_e"] > 0 else 0.95
            nav_cur *= (1.0 + it["net_ret"]) * (1.0 - ib) * (1.0 - ie)
        dyn_comp[f"q0_{int(q0 // 1e4)}w_uncapped"] = round(nav_cur, 4)

    rng = np.random.default_rng(SEED)
    rets_arr = led_df["net_ret"].to_numpy(dtype=float)
    n_tr = len(rets_arr)
    fill_stress = {}
    for p_fill in (0.50, 0.70):
        masks = rng.random((2000, n_tr)) < p_fill
        mults = np.where(masks, 1.0 + rets_arr[None, :], 1.0)
        paths = np.concatenate([np.ones((2000, 1)), np.cumprod(mults, axis=1)], axis=1)
        term_navs = paths[:, -1]
        cagrs = ((term_navs ** (252.0 / n_days)) - 1.0) * 100.0
        mdds = (1.0 - paths / np.maximum.accumulate(paths, axis=1)).max(axis=1) * 100.0
        fill_stress[f"fill_{int(p_fill * 100)}pct"] = {
            "nav_5y_median": round(float(np.median(term_navs)), 4),
            "nav_5y_p05": round(float(np.quantile(term_navs, 0.05)), 4),
            "nav_5y_p95": round(float(np.quantile(term_navs, 0.95)), 4),
            "cagr_median_pct": round(float(np.median(cagrs)), 2),
            "cagr_p05_pct": round(float(np.quantile(cagrs, 0.05)), 2),
            "mdd_median_pct": round(float(np.median(mdds)), 2),
            "mdd_p95_pct": round(float(np.quantile(mdds, 0.95)), 2),
        }

    seal_map = {(zr.sec_code, zr.trade_date): (int(zr.first_seal_ts or 9999999999), -float(zr.seal_amount or 0.0)) for zr in zt_tape.itertuples(index=False)}
    idx_ret_desc = np.argsort(-rets_arr, kind="mergesort")
    seal_keys, seal_cov = [], 0
    for r in led_df.itertuples(index=False):
        bar = by_c[r.c6]
        p0 = bar["dt_to_pos"][r.buy_date]
        dt_m1 = bar["dt"][p0 - 1] if p0 > 0 else r.buy_date
        sk = seal_map.get((r.c6, r.buy_date)) or seal_map.get((r.c6, dt_m1))
        if sk is not None:
            seal_cov += 1
            seal_keys.append((0, sk[1]))
        else:
            seal_keys.append((1, -float(r.net_ret)))
    idx_seal_desc = sorted(range(n_tr), key=lambda i: seal_keys[i])

    def _trim_s(km):
        sr = rets_arr[km]
        return {"n_rem": int(len(sr)), "n_dropped": int(n_tr - len(sr)), "wr_pct": round(float((sr > 0).mean() * 100.0), 2),
                "avg_ret_pct": round(float(sr.mean() * 100.0), 3), "nav_5y": round(float(np.prod(1.0 + sr)), 4)}

    adverse = {"by_net_ret": {}, "by_seal_amount_queue_proxy": {"seal_tape_cov": f"{seal_cov}/{n_tr}"}}
    for pct in (10, 20):
        kd = max(1, int(round(n_tr * pct / 100.0)))
        mr = np.ones(n_tr, dtype=bool); mr[idx_ret_desc[:kd]] = False
        ms = np.ones(n_tr, dtype=bool); ms[idx_seal_desc[:kd]] = False
        adverse["by_net_ret"][f"drop_top_{pct}pct"] = _trim_s(mr)
        adverse["by_seal_amount_queue_proxy"][f"drop_top_{pct}pct"] = _trim_s(ms)

    n_cov = sum((r.c6, r.buy_date) in bars_5m for r in led_df.itertuples(index=False))
    delay_out = {
        "delay_1m": "MISSING_LOCAL_DATA (本地无任何A股1分钟K线数据，仅存5分钟K线)",
        "five_m_buy_coverage_count": int(n_cov), "five_m_total_trades": int(n_tr),
        "five_m_buy_coverage_pct": round(n_cov / n_tr * 100.0, 1) if n_tr else 0.0,
        "five_m_data_status": "COMPLETE_100PCT" if n_cov == n_tr else f"PARTIAL_LOCAL_5M_DATA ({n_cov}/{n_tr})",
    }
    for step_lbl, shift_bars in (("plus_5m", 1), ("plus_15m", 3)):
        r_cz, r_cs, r_bc = [], [], []
        n_m_cls, n_m_low = 0, 0
        for r in led_df.itertuples(index=False):
            arr = bars_5m.get((r.c6, r.buy_date))
            if arr is None or len(arr) == 0:
                continue
            r_bc.append(float(r.net_ret))
            bd = by_c[r.c6]
            p0, pe = bd["dt_to_pos"][r.buy_date], bd["dt_to_pos"][r.exit_date]
            zt_px = float(bd["zt_px"][p0])
            hh_arr = arr[:, 0].astype(int)
            if int(r.buy_hhmm) <= 925:
                tgt_idx = shift_bars - 1
            else:
                pa = np.where(hh_arr >= int(r.buy_hhmm))[0]
                tgt_idx = min(len(arr) - 1, (int(pa[0]) if len(pa) else 0) + shift_bars)
            db = arr[tgt_idx]
            if (not np.isnan(zt_px)) and (db[3] >= zt_px - 0.011):
                n_m_low += 1
            if (not np.isnan(zt_px)) and (db[4] >= zt_px - 0.011):
                n_m_cls += 1
                r_cz.append(0.0)
            else:
                nr = (float(r.exit_price) / float(db[4])) * (bd["qfq"][p0] / bd["qfq"][pe]) * 0.9980 - 1.0
                r_cz.append(nr); r_cs.append(nr)
        def _sd(lst):
            a = np.array(lst, dtype=float)
            return {"n": int(len(a)), "wr_pct": round(float((a > 0).mean() * 100.0), 2), "avg_ret_pct": round(float(a.mean() * 100.0), 3), "nav_5y": round(float(np.prod(1.0 + a)), 4)} if len(a) else {"n": 0}
        delay_out[step_lbl] = {"covered_base_stats": _sd(r_bc), "missed_zt_close_count": int(n_m_cls), "missed_zt_strict_low_count": int(n_m_low),
                               "covered_missed_as_zero": _sd(r_cz), "covered_missed_skipped": _sd(r_cs)}

    vb_arr = np.array([it["v_b"] for it in trade_items], dtype=float) / 1e4
    ve_arr = np.array([it["v_e"] for it in trade_items], dtype=float) / 1e4
    v5_list = []
    for r in led_df.itertuples(index=False):
        a5 = bars_5m.get((r.c6, r.buy_date))
        if a5 is not None and len(a5) > 0:
            hh = 935 if int(r.buy_hhmm) <= 925 else int(r.buy_hhmm)
            i5 = np.where(a5[:, 0] >= hh)[0]
            v5_list.append(float(a5[i5[0] if len(i5) else 0, 6]) / 1e4)
    v_guard = {
        "v_buy_wan_min": round(float(np.min(vb_arr)), 1), "v_buy_wan_p10": round(float(np.quantile(vb_arr, 0.10)), 1), "v_buy_wan_median": round(float(np.median(vb_arr)), 1),
        "v_exit_wan_min": round(float(np.min(ve_arr)), 1), "v_exit_wan_p10": round(float(np.quantile(ve_arr, 0.10)), 1), "v_exit_wan_median": round(float(np.median(ve_arr)), 1),
        "cap_10pct_adv_p10_wan": round(float(min(np.quantile(vb_arr, 0.10), np.quantile(ve_arr, 0.10)) * 0.10), 1),
        "cap_5pct_adv_p10_wan": round(float(min(np.quantile(vb_arr, 0.10), np.quantile(ve_arr, 0.10)) * 0.05), 1),
        "v_entry_5m_cov": f"{len(v5_list)}/{n_tr}",
        "v_entry_5m_wan_p10": round(float(np.quantile(v5_list, 0.10)), 1) if v5_list else None,
        "v_entry_5m_wan_median": round(float(np.median(v5_list)), 1) if v5_list else None,
        "cap_20pct_5m_p10_wan": round(float(np.quantile(v5_list, 0.10) * 0.20), 1) if v5_list else None,
    }
    return {
        "baseline_unconstrained": {"nav_5y": round(base_0["nav_5y"], 4), "cagr_pct": round(base_0["cagr_pct"], 2), "sharpe": round(base_0["sharpe"], 3)},
        "liquidity_participation_guardrails": v_guard, "almgren_chriss": ac_results,
        "dynamic_compounding_sensitivity_Y050_uncapped": dyn_comp, "random_fill_2000mc": fill_stress,
        "adverse_selection": adverse, "entry_delay": delay_out,
    }


def calc_breakeven_cost_clean(net_rets: np.ndarray, csi_5y_ret: float) -> dict:
    """Breakeven one-way bps & friction sensitivity grid (ZERO cap10m)."""
    n = len(net_rets)
    gross_mult = (1.0 + net_rets) / (1.0 - ORIG_FEE_RT)
    gross_rets = gross_mult - 1.0
    arith_gross_mean = float(np.mean(gross_rets))
    geom_gross_mult = math.exp(float(np.mean(np.log(np.maximum(1e-9, gross_mult)))))
    c_arith_ow = 0.5 * (1.0 - 1.0 / (1.0 + arith_gross_mean))
    c_geom_ow = 0.5 * (1.0 - 1.0 / geom_gross_mult)
    target_per = (1.0 + csi_5y_ret) ** (1.0 / n) if n > 0 else 1.0
    c_csi_ow = 0.5 * (1.0 - target_per / geom_gross_mult)
    c_arith_slip_ow = arith_gross_mean / (2.0 + arith_gross_mean)
    c_geom_slip_ow = (geom_gross_mult - 1.0) / (geom_gross_mult + 1.0)

    sens_grid = []
    for ow_bps in (10, 25, 50, 100, 150, 200, 300):
        rt = 2.0 * ow_bps / 10000.0
        r_c = gross_mult * (1.0 - rt) - 1.0
        sens_grid.append({
            "one_way_bps": ow_bps, "round_trip_bps": 2 * ow_bps,
            "arith_mean_pct": sf(r_c.mean() * 100.0, 3),
            "nav_5y": sf(float(np.prod(1.0 + r_c)), 4),
        })
    return {
        "original_deducted_rt_bps": ORIG_FEE_RT * 10000.0, "original_deducted_ow_bps": ORIG_FEE_OW_BPS,
        "gross_arith_mean_pct": sf(arith_gross_mean * 100.0, 3), "gross_geom_mean_pct": sf((geom_gross_mult - 1.0) * 100.0, 3),
        "breakeven_ow_arith_bps": sf(c_arith_ow * 10000.0, 1), "breakeven_ow_geom_5y_bps": sf(c_geom_ow * 10000.0, 1),
        "breakeven_ow_beat_csi300_bps": sf(c_csi_ow * 10000.0, 1),
        "breakeven_ow_slip_ratio_arith_bps": sf(c_arith_slip_ow * 10000.0, 1),
        "breakeven_ow_slip_ratio_geom_bps": sf(c_geom_slip_ow * 10000.0, 1),
        "safety_margin_vs_10bps_ow_geom": sf((c_geom_ow * 10000.0) / ORIG_FEE_OW_BPS, 2),
        "cost_sensitivity_grid": sens_grid,
    }


def run_pillar4_1to2(is_v20: bool, led_df: pd.DataFrame, pool_df: pd.DataFrame, pt: pd.DataFrame,
                     fb20_dts: set[str], by_c_p2: dict, sh300: dict, all_sh_dts: list[str], csi_5y_ret: float) -> dict:
    df_p = pool_df.copy()
    df_p["code"] = df_p["code"].astype(str).str.zfill(6)
    df_p["buy_date"] = df_p["buy_date"].astype(str).str[:10]
    m_fb = df_p["buy_date"].isin(fb20_dts).to_numpy(dtype=bool)
    if is_v20:
        df_p["eff_score"] = df_p["base_score"].to_numpy(dtype=float) - np.where(m_fb, 25.0, 0.0)
        # Merge exact V20 pass_gate from pretrig simulation
        m_cln_pt = pt["buy_date"].isin(fb20_dts).to_numpy(dtype=bool)
        _, _, keep_v20 = sim_1to2_from_pretrig(pt, np.where(m_cln_pt, -25.0, 0.0))
        v20_keys = set(zip(pt.loc[keep_v20, "buy_date"].astype(str), pt.loc[keep_v20, "code"].astype(str).str.zfill(6)))
        pass_gate = np.array([(r.buy_date, r.code) in v20_keys for r in df_p.itertuples(index=False)], dtype=bool)
        sc_col = "eff_score"
        thr = 304.8
        pool_note = "全量可成交一进二候选池 (N=447), V20 口径: fb20_cln>=2 日 score -25"
    else:
        df_p["eff_score"] = df_p["base_score"].to_numpy(dtype=float)
        pass_gate = df_p["base_pass_v19"].to_numpy(dtype=bool)
        sc_col = "eff_score"
        thr = 304.8
        pool_note = "全量可成交一进二候选池 (N=447), 原 V19 口径"

    ic_full = p2.calc_ic_block(df_p, sc_col, "net_ret", min_period_n=4, min_roll_n=10)
    sc_arr = df_p[sc_col].to_numpy(dtype=float)
    rt_arr = df_p["net_ret"].to_numpy(dtype=float)
    q5_val = p2.calc_quantile_bins(sc_arr, rt_arr, 5, "value_qcut")
    q5_bal = p2.calc_quantile_bins(sc_arr, rt_arr, 5, "rank_balanced")
    d10_val = p2.calc_quantile_bins(sc_arr, rt_arr, 10, "value_qcut")
    cal_full = p2.calc_classification_calibration(df_p, sc_col)

    def _pf(mask_b):
        p1_r, p0_r = rt_arr[mask_b], rt_arr[~mask_b]
        tp, pp = stats.ttest_ind(p1_r, p0_r, equal_var=False) if (len(p1_r) > 1 and len(p0_r) > 1) else (0.0, 1.0)
        return {"n_pass": int(len(p1_r)), "wr_pass_pct": sf((p1_r > 0).mean() * 100.0, 2), "mean_pass_pct": sf(p1_r.mean() * 100.0, 3),
                "n_fail": int(len(p0_r)), "wr_fail_pct": sf((p0_r > 0).mean() * 100.0, 2), "mean_fail_pct": sf(p0_r.mean() * 100.0, 3),
                "pass_minus_fail_pp": sf((p1_r.mean() - p0_r.mean()) * 100.0, 3), "welch_t": sf(tp, 3), "welch_p": sf(pp, 6)}

    rets_tr = led_df["net_ret"].to_numpy(dtype=float)
    within_led = {
        "ic_and_decay": p2.calc_ic_block(led_df, "score", "net_ret", min_period_n=4, min_roll_n=10),
        "monotonicity_q5_value": p2.calc_quantile_bins(led_df["score"].to_numpy(float), rets_tr, 5, "value_qcut"),
        "monotonicity_q5_balanced": p2.calc_quantile_bins(led_df["score"].to_numpy(float), rets_tr, 5, "rank_balanced"),
        "classification_calibration": p2.calc_classification_calibration(led_df, "score"),
    }
    return {
        "candidate_pool_analysis": {
            "pool_status": "full_candidate_pool", "pool_note": pool_note,
            "ic_and_decay": ic_full, "monotonicity_q5_value": q5_val, "monotonicity_q5_balanced": q5_bal,
            "monotonicity_d10_value": d10_val,
            "pass_vs_fail_score3048": _pf(sc_arr >= thr),
            "pass_vs_fail_full_gate": _pf(pass_gate),
            "classification_calibration": cal_full,
        },
        "within_ledger_analysis": within_led,
        "breakeven_transaction_cost": calc_breakeven_cost_clean(rets_tr, csi_5y_ret),
        "holding_period_decay": p2.calc_holding_decay(led_df, by_c_p2, sh300, all_sh_dts),
    }


def build_1to2_v20_wrc_family(pt: pd.DataFrame, fb20_dts: set[str], a76_dts: set[str], daily_v20: np.ndarray,
                              t_days: list[str], day_idx: dict, by_c_p2: dict, mtm_cache: dict) -> tuple[np.ndarray, dict]:
    """Construct V20 multiple-testing family (col 0 = V20 active rule + penalty variants + 180 T-1 water variants)."""
    cols_list = [daily_v20]
    m_cln = pt["buy_date"].isin(fb20_dts).to_numpy(dtype=bool)
    m_a76 = pt["buy_date"].isin(a76_dts).to_numpy(dtype=bool)
    base_delta = np.where(m_cln, -25.0, 0.0)

    for w in (0, 5, 10, 15, 20, 30, 35, 40):
        tr, _, _ = sim_1to2_from_pretrig(pt, np.where(m_cln, -float(w), 0.0))
        dv, _ = p2.trades_to_daily_mtm(tr, t_days, day_idx, by_c_p2, mtm_cache)
        cols_list.append(dv)
    tr_sk, _, _ = sim_1to2_from_pretrig(pt, np.zeros(len(pt)), skip_mask=m_cln)
    cols_list.append(p2.trades_to_daily_mtm(tr_sk, t_days, day_idx, by_c_p2, mtm_cache)[0])

    for w in (5, 10, 15, 20, 25, 30):
        tr, _, _ = sim_1to2_from_pretrig(pt, np.where(m_a76, -float(w), 0.0))
        cols_list.append(p2.trades_to_daily_mtm(tr, t_days, day_idx, by_c_p2, mtm_cache)[0])
    for w in (8, 10, 12, 15, 18):
        tr, _, _ = sim_1to2_from_pretrig(pt, np.where(m_a76, -float(w), 0.0) + np.where(m_cln, -float(w), 0.0))
        cols_list.append(p2.trades_to_daily_mtm(tr, t_days, day_idx, by_c_p2, mtm_cache)[0])

    for fid in ("F1", "F2", "F3", "F4", "F_comp"):
        for mode in ("plus", "minus", "bidir"):
            for shape in ("discrete", "linear"):
                for step in (5, 10, 15, 20, 25, 30):
                    d_w = p2._water_delta(pt, fid, mode, shape, float(step))
                    tr, _, _ = sim_1to2_from_pretrig(pt, base_delta + d_w)
                    cols_list.append(p2.trades_to_daily_mtm(tr, t_days, day_idx, by_c_p2, mtm_cache)[0])

    mat_full = np.column_stack(cols_list)
    seen, uniq_idx = {}, []
    for j in range(mat_full.shape[1]):
        h = hash(mat_full[:, j].round(10).tobytes())
        if h not in seen:
            seen[h] = j
            uniq_idx.append(j)
    mat_uniq = mat_full[:, uniq_idx]
    return mat_uniq, {
        "family_description": "1to2 V20 candidate family: V20 active + 20 fb20cln/a76/joint penalty rules + 180 T-1 market water variants on V20",
        "M_total_rules": int(mat_full.shape[1]),
        "M_unique_series": int(mat_uniq.shape[1]),
    }


def run_pillar5_1to2(is_v20: bool, led_df: pd.DataFrame, daily_mtm: np.ndarray, csi_daily: np.ndarray,
                     sh300: dict, all_sh_dts: list[str], W_dict: dict, pt: pd.DataFrame, pools: dict,
                     ledgers_p2: dict, fb20_dts: set[str], a76_dts: set[str],
                     t_days: list[str], day_idx: dict, by_c_p2: dict, mtm_cache: dict) -> dict:
    rng = np.random.default_rng(SEED)
    rets_tr = led_df["net_ret"].to_numpy(dtype=float)
    n_tr = len(rets_tr)
    trades_per_year = float(n_tr) / 5.0
    daily_ex = daily_mtm - csi_daily
    tr_csi = np.array([p2.get_csi_period_ret(sh300, all_sh_dts, r.buy_date, r.exit_date) for r in led_df.itertuples(index=False)], dtype=float)
    psr_block = {
        "daily_mtm_basis": {"annualize_days": 252, "vs_zero": p2.calc_psr_mintrl(daily_mtm, 252.0, 1.0), "vs_csi300": p2.calc_psr_mintrl(daily_ex, 252.0, 1.0)},
        "trade_level_basis": {"trades_per_year_5y": sf(trades_per_year, 2), "vs_zero": p2.calc_psr_mintrl(rets_tr, trades_per_year, 1.0),
                              "vs_csi300_holding": p2.calc_psr_mintrl(rets_tr - tr_csi, trades_per_year, 1.0)},
    }
    if is_v20:
        mat_M, fam_meta = build_1to2_v20_wrc_family(pt, fb20_dts, a76_dts, daily_mtm, t_days, day_idx, by_c_p2, mtm_cache)
    else:
        mat_M, fam_meta = p2.build_rule_family_matrix("1to2_v19", led_df, daily_mtm, pools, pt, ledgers_p2, t_days, day_idx, by_c_p2, mtm_cache)
    wrc_spa = {
        "family_meta": {**fam_meta, "politis_white_opt_L_days": sf(p2.politis_white_opt_block_len(daily_mtm), 2)},
        "vs_cash0": p2.run_wrc_and_spa(mat_M, W_dict, L_main=10),
        "vs_csi300": p2.run_wrc_and_spa(mat_M - csi_daily[:, None], W_dict, L_main=10),
    }
    bca_m = p2.bca_bootstrap_ci(rets_tr * 100.0, B=BOOT_B, alpha=0.05, rng=rng)
    bca_w = p2.bca_bootstrap_ci((rets_tr > 0).astype(float) * 100.0, B=BOOT_B, alpha=0.05, rng=rng)
    w_lo, w_hi = p2.wilson_ci_95(int((rets_tr > 0).sum()), n_tr)
    bca_w["wilson_95_ci_pct"] = [sf(w_lo * 100.0, 2), sf(w_hi * 100.0, 2)]
    seq_kelly = p2.calc_runs_autocorr_kelly(rets_tr, rng=rng)
    return {
        "psr_and_mintrl": psr_block, "multiple_testing_wrc_spa": wrc_spa,
        "bca_bootstrap_95ci": {"mean_net_ret_pct": {**bca_m, "excludes_zero": bool(bca_m["ci_95_low"] > 0)}, "win_rate_pct": bca_w},
        **seq_kelly,
    }


def run_pillar6_7_1to2(v20_df: pd.DataFrame, v19_df: pd.DataFrame, sh300: dict, all_dts: list[str]) -> tuple[dict, dict]:
    print("[6/7] Running Pillar 6 (Hygiene & 5-Fold Purged CV) & Pillar 7 (6-Strat Corr w/ S82, LOO & CUSUM/SPRT)...")
    cal_5y = [d for d in all_dts if START_DATE <= d <= END_DATE]
    cal_p3 = [d for d in all_dts if "2021-11-15" <= d <= END_DATE]
    dt_idx_p3 = {d: i for i, d in enumerate(cal_p3)}
    prev_p3 = [d for d in all_dts if d < "2021-11-15"]
    csi_p3_pct = (sh300[END_DATE] / sh300[prev_p3[-1]] - 1.0) * 100.0

    # Load remaining 5 strategies + pry_top1 + A76 ref
    def _n10(fn):
        return p3.norm_ledger(pd.read_csv(f"{PARTC_DIR}/{fn}", dtype={"code": str}))

    l34, lh, lpry_ss, lpry_t1, l23 = _n10("ledger_3to4_v41_clean.csv"), _n10("ledger_high_v51_clean.csv"), _n10("ledger_pry_v21_ss165_clean.csv"), _n10("ledger_pry_v21_top1_clean.csv"), _n10("ledger_2to3_v21_opt_std90_clean.csv")
    lv20 = p3.norm_ledger(v20_df)
    lv19 = p3.norm_ledger(v19_df)

    def _load20(fn):
        d = pd.read_csv(f"{V11_DIR}/{fn}", dtype={"c6": str})
        d["code"] = d["c6"].astype(str).str.zfill(6)
        d["buy_date"] = d["buy_date"].astype(str).str[:10]
        d["exit_date"] = d["exit_date"].astype(str).str[:10]
        d["net_ret"] = pd.to_numeric(d["net_ret_eval"], errors="coerce").astype(float)
        d["buy_hhmm"] = pd.to_numeric(d["buy_hhmm"], errors="coerce").fillna(925).astype(int)
        d["exit_hhmm"] = pd.to_numeric(d["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
        d = d[d["buy_date"].between(START_DATE, END_DATE)].copy().sort_values(["buy_date", "buy_hhmm", "code"]).reset_index(drop=True)
        return d

    l_s82 = _load20("final_v11_ledger_S82.csv")
    l_a76 = _load20("final_v11_ledger.csv")
    codes_needed = set().union(*[set(x["code"]) for x in (l34, lh, lpry_ss, lpry_t1, l23, lv20, lv19, l_s82, l_a76)])

    # Load all active+delisted 10cm & 20cm daily bars for required codes
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    import pyarrow.dataset as ds
    flt = ds.field("date") >= pd.Timestamp("2021-10-01")
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    df_all = pd.concat([da, dd], ignore_index=True)
    df_all["c6"] = df_all["ticker"].astype(str).str[:6]
    df_all = df_all[df_all["c6"].isin(codes_needed) & (~df_all["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df_all["dt"] = df_all["date"].dt.strftime("%Y-%m-%d")
    df_all.sort_values(["c6", "dt"], inplace=True)
    df_all.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    df_all.reset_index(drop=True, inplace=True)
    df_all["adjf"] = np.where((df_all["close"] > 0) & (df_all["adj_close"] > 0), df_all["adj_close"] / df_all["close"], 1.0)
    bar_lu = {
        (r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf))
        for r in df_all[["c6", "dt", "open", "close", "adj_close", "qfq_factor", "adjf"]].itertuples(index=False)
    }

    # 20cm exact daily MTM on cal_p3 (buy_px / exit_px are adj_close)
    def _mtm_20cm(d20):
        T = len(cal_p3)
        mult = np.ones(T, dtype=float)
        for r in d20.itertuples(index=False):
            bi, ei = dt_idx_p3[r.buy_date], dt_idx_p3[r.exit_date]
            prev_val = float(r.buy_px)
            for t in range(bi, ei):
                bt = bar_lu.get((r.code, cal_p3[t]))
                cur_adj = bt[2] if bt else prev_val
                mult[t] *= (cur_adj / prev_val)
                prev_val = cur_adj
            target_end = float(r.buy_px) * (1.0 + float(r.net_ret))
            mult[ei] *= (target_end / prev_val)
        dr = mult - 1.0
        nav_m = float(np.prod(mult))
        nav_l = float(np.prod(1.0 + d20["net_ret"].to_numpy(float)))
        assert abs(nav_m - nav_l) < 1e-4, (nav_m, nav_l)
        return dr

    # Ex-div check for V20 & V19
    exdiv_audit = {}
    for nm, ld in [("1to2_V20", lv20), ("1to2_V19", lv19)]:
        ex_list, max_err, bad = [], 0.0, 0
        for r in ld.itertuples(index=False):
            bb, eb = bar_lu.get((r.code, r.buy_date)), bar_lu.get((r.code, r.exit_date))
            if bb and eb:
                qr = bb[3] / eb[3]
                err = abs((float(r.exit_price) / float(r.buy_price)) * qr * 0.9980 - 1.0 - float(r.net_ret))
                max_err = max(max_err, err)
                if err > 0.005:
                    bad += 1
                if abs(qr - 1.0) > 1e-4:
                    ex_list.append({"code": r.code, "name": getattr(r, "name", ""), "buy_date": r.buy_date, "exit_date": r.exit_date,
                                    "qfq_ratio": round(qr, 5), "net_ret_pct": round(float(r.net_ret) * 100.0, 2)})
        exdiv_audit[nm] = {"n_trades": int(len(ld)), "ex_div_trades_count": len(ex_list), "ex_div_ret_mismatch_gt50bps": bad,
                           "max_ret_diff_bps": round(max_err * 10000.0, 2), "ex_div_trades": ex_list}

    # Build daily MTM (on cal_p3) for all sleeves
    daily_p3 = {}
    for k, ld in [("3to4", l34), ("high", lh), ("pry_ss165", lpry_ss), ("2to3", l23), ("1to2_V20", lv20), ("1to2_V19", lv19)]:
        dr, chk = p3.build_daily_mtm_series(ld, cal_p3, dt_idx_p3, bar_lu)
        assert chk["nav_abs_diff"] < 1e-4, (k, chk)
        daily_p3[k] = dr
    daily_p3["20cm_S82"] = _mtm_20cm(l_s82)
    daily_p3["20cm_A76"] = _mtm_20cm(l_a76)

    # Purged & Embargoed 5-fold CV (embargo = 3 trading days) for V20 vs V19
    T3 = len(cal_p3)
    step3 = T3 // 5
    fold_bounds = [(k * step3, (k + 1) * step3 - 1 if k < 4 else T3 - 1) for k in range(5)]
    purged_cv = {}
    for nm, ld in [("1to2_V20", lv20), ("1to2_V19", lv19)]:
        d = ld.copy()
        d["b_idx"] = d["buy_date"].map(dt_idx_p3)
        d["e_idx"] = d["exit_date"].map(dt_idx_p3)
        dr = daily_p3[nm]
        ftr = d["net_ret"].to_numpy(float)
        ftr_sd = float(ftr.std(ddof=1))
        fd_sd = float(dr.std(ddof=1))
        full_st = {
            "n": int(len(ftr)), "trade_mean_pct": round(float(ftr.mean() * 100.0), 2),
            "trade_sharpe": round(float(ftr.mean() / ftr_sd), 3),
            "daily_mtm_ann_mean_pct": round(float(dr.mean() * 242.0 * 100.0), 2),
            "daily_mtm_sharpe_ann": round(float(dr.mean() / fd_sd * math.sqrt(242.0)), 3),
        }
        folds = []
        for fi, (fs, fe) in enumerate(fold_bounds, 1):
            tem = (d["b_idx"] >= fs) & (d["b_idx"] <= fe)
            raw_tr = ~tem
            prg_tr = (d["e_idx"] < fs) | (d["b_idx"] > fe + 3)
            ter = d.loc[tem, "net_ret"].to_numpy(float)
            tedr = dr[fs : fe + 1]
            tesd = float(tedr.std(ddof=1)) if len(tedr) > 1 else 0.0
            tetsd = float(ter.std(ddof=1)) if len(ter) > 1 else 0.0
            folds.append({
                "fold": fi, "window": f"{cal_p3[fs]} ~ {cal_p3[fe]}",
                "n_test": int(len(ter)), "n_train_raw": int(raw_tr.sum()), "n_train_purged": int(prg_tr.sum()),
                "purged_embargoed_samples": int((raw_tr & (~prg_tr)).sum()),
                "train_raw_mean_pct": round(float(d.loc[raw_tr, "net_ret"].mean() * 100.0), 2),
                "train_purged_mean_pct": round(float(d.loc[prg_tr, "net_ret"].mean() * 100.0), 2),
                "test_wr_pct": round(float((ter > 0).mean() * 100.0), 2) if len(ter) else 0.0,
                "test_trade_mean_pct": round(float(ter.mean() * 100.0), 2) if len(ter) else 0.0,
                "test_trade_sharpe": round(float(ter.mean() / tetsd), 3) if tetsd > 1e-12 else 0.0,
                "test_fold_nav": round(float(np.prod(1.0 + ter)), 4) if len(ter) else 1.0,
                "test_daily_mtm_sharpe_ann": round(float(tedr.mean() / tesd * math.sqrt(242.0)), 3) if tesd > 1e-12 else 0.0,
            })
        f_means = [f["test_trade_mean_pct"] for f in folds if f["n_test"] > 0]
        f_dsrs = [f["test_daily_mtm_sharpe_ann"] for f in folds]
        pos_f = sum(1 for f in folds if f["test_fold_nav"] > 1.0)
        purged_cv[nm] = {
            "embargo_trading_days": 3, "full_sample": full_st,
            "cv_summary": {
                "mean_fold_trade_mean_pct": round(float(np.mean(f_means)), 2),
                "pooled_oos_trade_mean_pct": round(float(ftr.mean() * 100.0), 2),
                "mean_fold_daily_sharpe_ann": round(float(np.mean(f_dsrs)), 3),
                "sharpe_diff_full_minus_cv_mean": round(full_st["daily_mtm_sharpe_ann"] - float(np.mean(f_dsrs)), 3),
                "worst_fold_by_nav": min(folds, key=lambda x: x["test_fold_nav"]),
                "worst_fold_by_daily_sharpe": min(folds, key=lambda x: x["test_daily_mtm_sharpe_ann"]),
                "positive_folds_count": int(pos_f), "positive_folds_pct": round(pos_f / 5.0 * 100.0, 1),
                "total_purged_across_5folds": int(sum(f["purged_embargoed_samples"] for f in folds)),
            },
            "folds": folds,
        }

    p6_out = {"raw_vs_qfq_exdiv_audit": exdiv_audit, "purged_embargoed_5fold_cv": purged_cv}

    # Pillar 7.1: 6-Strategy Correlation on cal_5y (1,212 trading days: 2021-11-16..2026-11-16)
    idx_5y = [dt_idx_p3[d] for d in cal_5y]
    csi_5y_vec = np.array([sh300[d] / sh300[all_dts[all_dts.index(d) - 1]] - 1.0 for d in cal_5y], dtype=float)
    q10_thr = float(np.quantile(csi_5y_vec, 0.10))
    w10_mask = csi_5y_vec <= q10_thr

    def _corr_suite(lbl_12: str, key_12: str):
        keys = ["3to4", "high", "pry_ss165", "2to3", lbl_12, "20cm_S82"]
        mp = {"3to4": "3to4", "high": "high", "pry_ss165": "pry_ss165", "2to3": "2to3", lbl_12: key_12, "20cm_S82": "20cm_S82"}
        df_r = pd.DataFrame({k: daily_p3[mp[k]][idx_5y] for k in keys}, index=cal_5y)
        any_act = (df_r.abs() > 1e-12).any(axis=1)
        any_loss = (df_r < 0.0).any(axis=1)
        def _pack(sub):
            pm = sub.corr("pearson").fillna(0.0).round(4)
            sm = sub.corr("spearman").fillna(0.0).round(4)
            vals = pm.to_numpy()
            off = [vals[i, j] for i in range(len(keys)) for j in range(i + 1, len(keys))]
            return {"n_days": int(len(sub)), "pearson": pm.to_dict(), "spearman": sm.to_dict(),
                    "mean_pairwise_pearson": round(float(np.mean(off)), 4), "max_pairwise_pearson": round(float(np.max(off)), 4)}
        pair_12 = {}
        for k_other in keys + ["20cm_A76"]:
            s_other = daily_p3[mp[k_other]][idx_5y] if k_other in mp else daily_p3[k_other][idx_5y]
            s_12 = df_r[lbl_12].to_numpy()
            m_u = (np.abs(s_12) > 1e-12) | (np.abs(s_other) > 1e-12)
            m_dn = (s_12 < 0) | (s_other < 0)
            pair_12[k_other] = {
                "full_5y_pearson": sf(np.corrcoef(s_12, s_other)[0, 1], 4),
                "union_active_pearson": sf(np.corrcoef(s_12[m_u], s_other[m_u])[0, 1], 4) if m_u.sum() >= 3 else 0.0,
                "either_loss_pearson": sf(np.corrcoef(s_12[m_dn], s_other[m_dn])[0, 1], 4) if m_dn.sum() >= 3 else 0.0,
                "csi_worst10pct_pearson": sf(np.corrcoef(s_12[w10_mask], s_other[w10_mask])[0, 1], 4),
            }
        loss_cnt = (df_r < -1e-6).sum(axis=1)
        nav_df = (1.0 + df_r).cumprod()
        dd_df = nav_df / nav_df.cummax() - 1.0
        dd5_cnt = (dd_df < -0.05).sum(axis=1)
        return {
            "1to2_vs_each_peer": pair_12,
            "full_5y_calendar": _pack(df_r),
            "any_active_days_only": _pack(df_r[any_act]),
            "downside_csi300_worst10pct": {"csi_q10_thr_pct": round(q10_thr * 100.0, 2), **_pack(df_r[w10_mask])},
            "downside_any_loss_days": _pack(df_r[any_loss]),
            "simultaneous_blowup_check": {
                "days_ge1_loss": int((loss_cnt >= 1).sum()), "days_ge2_simultaneous_loss": int((loss_cnt >= 2).sum()),
                "days_ge3_simultaneous_loss": int((loss_cnt >= 3).sum()), "max_simultaneous_losing_strategies": int(loss_cnt.max()),
                "days_ge2_in_gt5pct_dd": int((dd5_cnt >= 2).sum()), "days_ge3_in_gt5pct_dd": int((dd5_cnt >= 3).sum()),
            },
        }

    # Pillar 7.2: Equal-Weight 6-strat & 5-strat LOO + Single-slot 5-strat & 6-strat (ZERO cap10m)
    csi_5y_pct = (float(np.prod(1.0 + csi_5y_vec)) - 1.0) * 100.0
    def _ew_m(arr):
        m = p3.metrics_from_daily_and_trades(arr, np.array([]), csi_5y_pct)
        for c in ("trades", "wr_pct", "plr", "trade_mean_pct", "trade_sharpe", "trade_mdd_pct"):
            m.pop(c)
        return m

    ew_base_no12 = _ew_m(np.column_stack([daily_p3[k][idx_5y] for k in ["3to4", "high", "pry_ss165", "2to3", "20cm_S82"]]).mean(axis=1))
    ew6_v20 = _ew_m(np.column_stack([daily_p3[k][idx_5y] for k in ["3to4", "high", "pry_ss165", "2to3", "1to2_V20", "20cm_S82"]]).mean(axis=1))
    ew6_v19 = _ew_m(np.column_stack([daily_p3[k][idx_5y] for k in ["3to4", "high", "pry_ss165", "2to3", "1to2_V19", "20cm_S82"]]).mean(axis=1))
    ew5_v20 = _ew_m(np.column_stack([daily_p3[k][idx_5y] for k in ["3to4", "high", "pry_ss165", "2to3", "1to2_V20"]]).mean(axis=1))
    ew5_v19 = _ew_m(np.column_stack([daily_p3[k][idx_5y] for k in ["3to4", "high", "pry_ss165", "2to3", "1to2_V19"]]).mean(axis=1))

    cols_s = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "priority", "score", "buy_price", "exit_price", "net_ret"]
    l_s82_s = l_s82.assign(strategy="20cm_S82", buy_price=l_s82["buy_px"], exit_price=l_s82["exit_px"])
    base_4 = {
        "3to4": l34.assign(strategy="三进四V4.1", priority=1)[cols_s],
        "high": lh.assign(strategy="高标首阴V5.1", priority=2)[cols_s],
        "pry": lpry_t1.assign(strategy="超跌撬板V2.1", priority=3)[cols_s],
        "2to3": l23.assign(strategy="二进三V2.1", priority=4)[cols_s],
    }
    def _run1s(df_in, is_20cm_adj=False):
        sim = p3.run_1slot_sim_exact(df_in)
        if is_20cm_adj:
            # Compute daily MTM directly across 10cm (raw) and 20cm (adj) trades
            mult = np.ones(len(cal_p3), dtype=float)
            for r in sim.itertuples(index=False):
                bi, ei = dt_idx_p3[r.buy_date], dt_idx_p3[r.exit_date]
                bb = bar_lu.get((r.code, r.buy_date))
                prev_v = float(r.buy_price) if r.strategy == "20cm_S82" else (float(r.buy_price) * bb[4] if bb else 1.0)
                for t in range(bi, ei):
                    bt = bar_lu.get((r.code, cal_p3[t]))
                    cur_v = bt[2] if bt else prev_v
                    mult[t] *= (cur_v / prev_v)
                    prev_v = cur_v
                mult[ei] *= ((float(r.buy_price) if r.strategy == "20cm_S82" else float(r.buy_price) * bb[4]) * (1.0 + float(r.net_ret)) / prev_v)
            assert abs(float(np.prod(mult)) - float(np.prod(1.0 + sim["net_ret"].to_numpy(float)))) < 1e-4
            dr = mult - 1.0
        else:
            dr, chk = p3.build_daily_mtm_series(sim, cal_p3, dt_idx_p3, bar_lu)
            assert chk["nav_abs_diff"] < 1e-4, chk
        m = p3.metrics_from_daily_and_trades(dr[idx_5y], sim["net_ret"].to_numpy(float), csi_5y_pct)
        m["by_strategy"] = sim["strategy"].value_counts().to_dict()
        return m, sim

    m_5s_no12, _ = _run1s(pd.concat(list(base_4.values()), ignore_index=True))
    m_5s_v19, sim_5s_v19 = _run1s(pd.concat(list(base_4.values()) + [lv19.assign(strategy="一进二V19", priority=5)[cols_s]], ignore_index=True))
    m_5s_v20, sim_5s_v20 = _run1s(pd.concat(list(base_4.values()) + [lv20.assign(strategy="一进二V20", priority=5)[cols_s]], ignore_index=True))
    m_6s_v20_s82p5, _ = _run1s(pd.concat(list(base_4.values()) + [l_s82_s.assign(priority=5)[cols_s], lv20.assign(strategy="一进二V20", priority=6)[cols_s]], ignore_index=True), is_20cm_adj=True)
    m_6s_v20_12p5, _ = _run1s(pd.concat(list(base_4.values()) + [lv20.assign(strategy="一进二V20", priority=5)[cols_s], l_s82_s.assign(priority=6)[cols_s]], ignore_index=True), is_20cm_adj=True)
    m_6s_v19_s82p5, _ = _run1s(pd.concat(list(base_4.values()) + [l_s82_s.assign(priority=5)[cols_s], lv19.assign(strategy="一进二V19", priority=6)[cols_s]], ignore_index=True), is_20cm_adj=True)

    # Pillar 7.4: CUSUM / SPRT redlines for 1to2_V20, 1to2_V19, comb_5s_V20, comb_5s_V191
    cusum_res = p3.audit_pillar7_4_cusum_sprt({
        "3to4": l34, "high": lh, "pry_ss165": lpry_ss, "2to3": l23,
        "1to2": lv20, "comb_v191": sim_5s_v20,
    })
    cusum_v19 = p3.audit_pillar7_4_cusum_sprt({
        "3to4": l34, "high": lh, "pry_ss165": lpry_ss, "2to3": l23,
        "1to2": lv19, "comb_v191": sim_5s_v19,
    })

    p7_out = {
        "correlation_6strat_with_1to2_V20": _corr_suite("1to2_V20", "1to2_V20"),
        "correlation_6strat_with_1to2_V19": _corr_suite("1to2_V19", "1to2_V19"),
        "portfolio_contribution": {
            "equal_weight_6sleeves": {"with_1to2_V20": ew6_v20, "with_1to2_V19": ew6_v19, "drop_1to2": ew_base_no12,
                                      "v20_marginal_delta_sharpe": round(ew6_v20["daily_sharpe"] - ew_base_no12["daily_sharpe"], 4),
                                      "v20_vs_v19_delta_sharpe": round(ew6_v20["daily_sharpe"] - ew6_v19["daily_sharpe"], 4)},
            "equal_weight_5_10cm_sleeves": {"with_1to2_V20": ew5_v20, "with_1to2_V19": ew5_v19},
            "single_slot_5strat_10cm": {"with_1to2_V20": m_5s_v20, "with_1to2_V19": m_5s_v19, "drop_1to2": m_5s_no12},
            "single_slot_6strat_incl_S82": {"v20_S82_P5_1to2_P6": m_6s_v20_s82p5, "v20_1to2_P5_S82_P6": m_6s_v20_12p5, "v19_S82_P5_1to2_P6": m_6s_v19_s82p5},
        },
        "cusum_sprt_redlines": {
            "1to2_V20": cusum_res["1to2"],
            "1to2_V19": cusum_v19["1to2"],
            "comb_5strat_V20": cusum_res["comb_v191"],
            "comb_5strat_V191": cusum_v19["comb_v191"],
        },
    }
    return p6_out, p7_out


def main():
    t0 = time.time()
    print("[1/7] Loading market calendar, 5-factor universe, regime matrix, and 1to2 V20/V19 ledgers...")
    cal_dates, sh300, csi_s = p1.load_calendar_and_csi300()
    all_dts = sorted(sh300.keys())
    df_u, tot_amt, zt_tape = p1.load_daily_universe(cal_dates)
    factors, extra, fac_summary = p1.build_5_factors(df_u, cal_dates, all_dts, zt_tape, csi_s)
    by_c = p1.build_by_c_lookup(df_u)
    pool_by_dt, q_lookup = p1.prepare_matched_pools(df_u, cal_dates)
    reg_df = p1.build_regime_table(cal_dates, all_dts, tot_amt, zt_tape, df_u)
    del df_u

    def _load_1to2(path):
        d = pd.read_csv(path, dtype={"code": str})
        d["code"] = d["code"].astype(str).str.strip().str.zfill(6)
        d["c6"] = d["code"]
        d["buy_date"] = d["buy_date"].astype(str).str[:10]
        d["exit_date"] = d["exit_date"].astype(str).str[:10]
        d["buy_hhmm"] = pd.to_numeric(d["buy_hhmm"], errors="coerce").fillna(925).astype(int)
        d["exit_hhmm"] = pd.to_numeric(d["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
        d["net_ret"] = pd.to_numeric(d["net_ret"], errors="coerce").astype(float)
        d["score"] = pd.to_numeric(d["score"], errors="coerce").astype(float)
        d.sort_values(["buy_date", "buy_hhmm", "c6"], inplace=True)
        return d.reset_index(drop=True)

    v20_df = _load_1to2(f"{PARTA_DIR}/ledger_1to2_v20_cand.csv")
    v19_df = _load_1to2(f"{PARTC_DIR}/ledger_1to2_v19_clean.csv")
    pool_df = pd.read_csv(f"{MW3_DIR}/pool_1to2_full_clean.csv", dtype={"code": str})
    pool_df["code"] = pool_df["code"].astype(str).str.zfill(6)
    pool_df["buy_date"] = pool_df["buy_date"].astype(str).str[:10]

    pt = pd.read_parquet(f"{MW3_DIR}/_cache_pretrig_pool.parquet")
    pt["code"] = pt["code"].astype(str).str.zfill(6)
    pt["buy_date"] = pt["buy_date"].astype(str).str[:10]
    pt["exit_date"] = pt["exit_date"].astype(str).str[:10]
    pt = pt[pt["buy_date"] >= START_DATE].copy().reset_index(drop=True)

    p1cln = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet", columns=["f1_dt", "f1_o_pct", "mkt20_zt_cnt"])
    fb20_parq = set(p1cln[(p1cln["f1_o_pct"] <= -0.03) & (p1cln["mkt20_zt_cnt"] < 16) & (p1cln["f1_dt"] <= END_DATE)].groupby("f1_dt").size().loc[lambda s: s >= 2].index.astype(str))
    fb20_pit = {d for d, c in mc.build_fb20_cln_dates_pit(END_DATE).items() if c >= 2}
    assert fb20_parq == fb20_pit, f"fb20_cln PIT mismatch: {fb20_parq ^ fb20_pit}"
    s20 = pd.read_csv(f"{V11_DIR}/final_v11_all_scored_signals.csv", dtype={"c6": str})
    a76_dts = set(s20[s20["score"] >= 76.0]["buy_date"].astype(str))

    anti_ovf = run_old_overfitting_suite(pt, fb20_pit, v20_df, v19_df, pool_df, sh300, all_dts, by_c, cal_dates)

    target_pairs = {(r.c6, r.buy_date) for r in pd.concat([v20_df, v19_df]).itertuples(index=False)}
    bars_5m = p1.load_targeted_5m_bars(target_pairs)

    print("[3/7] Running Pillars 1, 2, 3 for 1to2 V20 and 1to2 V19...")
    p123_out = {}
    daily_p1_map = {}
    for sk, ld in [("1to2_V20", v20_df), ("1to2_V19", v19_df)]:
        daily_s, active_flag, nav_mtm, nav_led = p1.compute_daily_mtm(ld, by_c, cal_dates, allow_overlap=False)
        daily_p1_map[sk] = daily_s
        p1_reg = p1.run_pillar1_regressions(sk, ld, daily_s, active_flag, factors, extra, cal_dates)
        p1_mc = p1.run_matched_control("1to2_V19", ld, pool_by_dt, q_lookup, by_c)
        p2_res = run_pillar2_clean(ld, by_c, cal_dates, bars_5m, zt_tape)
        p3_res = p1.run_pillar3(sk, ld, daily_s, reg_df, csi_s, cal_dates)
        p123_out[sk] = {
            "n_trades": int(len(ld)), "n_active_days": int(active_flag.sum()),
            "nav_ledger": round(nav_led, 4), "nav_daily_mtm": round(nav_mtm, 4),
            "pillar1_alpha_attribution": {"regressions": p1_reg, "matched_control": p1_mc},
            "pillar2_micro_capacity": p2_res,
            "pillar3_regime_stress_bootstrap": p3_res,
        }

    print("[4/7] Loading P2 price DB & building Stationary Bootstrap weights (B=5000, L=10/5/20)...")
    codes_p2 = set(v20_df["code"]) | set(v19_df["code"]) | set(pool_df["code"]) | set(pt["code"])
    sh300_p2, all_sh_dts, t_days, day_idx, csi_daily, by_c_p2 = p2.load_market_and_prices(codes_p2)
    csi_5y_ret = float(np.prod(1.0 + csi_daily) - 1.0)
    W_dict = {L: p2.stationary_bootstrap_weights(len(t_days), BOOT_B, float(L), np.random.default_rng(SEED)) for L in (10, 5, 20)}

    print("[5/7] Running Pillars 4 & 5 for 1to2 V20 and 1to2 V19...")
    p45_out = {}
    mtm_cache = {}
    for sk, is_v20, ld in [("1to2_V20", True, v20_df), ("1to2_V19", False, v19_df)]:
        d_mtm, nav_diff = p2.trades_to_daily_mtm(ld, t_days, day_idx, by_c_p2, mtm_cache, allow_overlap=False)
        assert nav_diff < 1e-4, (sk, nav_diff)
        p4_res = run_pillar4_1to2(is_v20, ld, pool_df, pt, fb20_pit, by_c_p2, sh300_p2, all_sh_dts, csi_5y_ret)
        p5_res = run_pillar5_1to2(is_v20, ld, d_mtm, csi_daily, sh300_p2, all_sh_dts, W_dict, pt, {}, {}, fb20_pit, a76_dts, t_days, day_idx, by_c_p2, mtm_cache)
        p45_out[sk] = {"pillar4_signal_and_turnover": p4_res, "pillar5_statistical_confidence_and_sequence": p5_res}

    p6_out, p7_out = run_pillar6_7_1to2(v20_df, v19_df, sh300, all_dts)

    print("[7/7] Assembling JSON & enforcing hard audit gates...")
    results = sanitize_json({
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window": f"{START_DATE} ~ {END_DATE}",
            "n_trading_days": len(cal_dates),
            "csi300_5y_ret_pct": round(csi_5y_ret * 100.0, 2),
            "seed": SEED,
            "yfinance_imported": "yfinance" in sys.modules,
            "one_minute_bars_status": "MISSING_LOCAL_DATA (本地无任何A股1分钟K线数据，仅存5分钟K线)",
            "v20_rule": "fb20_cln>=2 -> score -25 (92 trades, 100% 5m coverage)",
            "factor_summary": fac_summary,
            "elapsed_sec": round(time.time() - t0, 2),
        },
        "anti_overfitting_old_suite": anti_ovf,
        "pillars_1_to_5": {
            sk: {**p123_out[sk], **p45_out[sk]} for sk in ("1to2_V20", "1to2_V19")
        },
        "pillar6_hygiene_and_purged_cv": p6_out,
        "pillar7_portfolio_and_cusum": p7_out,
    })

    raw_json = json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False)
    low_j = raw_json.lower()
    assert "cap10m" not in low_j and "cap1000w" not in low_j and "1000万" not in raw_json, "FORBIDDEN cap10m found!"
    assert "yfinance" not in sys.modules, "D12 violation!"

    out_path = f"{OUT_DIR}/partD1_1to2_v20_jianyan.json"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(raw_json)
    print(f"DONE in {results['metadata']['elapsed_sec']}s -> {out_path} ({os.path.getsize(out_path)} bytes)")


if __name__ == "__main__":
    main()
