#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Live single-slot evaluation: +-5/+-10/+-15 & filter, IS-best -> OOS/2026 blind, BH-FDR, CSCV PBO, D15 & 6-Gate check."""
import itertools
import math
import numpy as np
import pandas as pd
import scipy.stats as stats
from trackB1_pools_and_sim import CANON_WINDOWS, sim_strategy_slot
from trackB1_eval_pool import bh_fdr

TRD_DAYS_YEAR = 242.0


def get_csi_ret(sh300: dict, all_dts: list[str], s_dt: str, e_dt: str) -> float:
    dts = [d for d in all_dts if s_dt <= d <= e_dt]
    if not dts: return 0.0
    prevs = [d for d in all_dts if d < dts[0]]
    p0 = sh300[prevs[-1]] if prevs else sh300[dts[0]]
    return float((sh300[dts[-1]] / p0 - 1.0) * 100.0)


def compute_mtm_and_windows(slot_df, raw_df, cal_dts, dt_to_idx, sh300, all_dts, csi_cache):
    T = len(cal_dts)
    day_mult = np.ones(T, dtype=float)
    if not slot_df.empty:
        for segs in slot_df["_mtm"]:
            for t, val in segs:
                day_mult[t] *= val
    dr = day_mult - 1.0
    out = {}
    for wn, sd, ed in CANON_WINDOWS:
        csi_p = csi_cache[wn]
        win_idx = [dt_to_idx[d] for d in cal_dts if sd <= d <= ed]
        dr_w = dr[win_idx] if win_idx else np.zeros(1)
        tw = len(dr_w)
        cum_d = np.cumprod(1.0 + dr_w)
        pk_d = np.maximum.accumulate(np.insert(cum_d, 0, 1.0))[1:]
        mdd_mtm = float(np.max((pk_d - cum_d) / pk_d) * 100.0) if tw > 0 else 0.0
        sd_d = float(np.std(dr_w, ddof=1)) if tw > 1 else 0.0
        sharpe = float(np.mean(dr_w) / sd_d * math.sqrt(TRD_DAYS_YEAR)) if sd_d > 1e-12 else 0.0
        ss = slot_df[(slot_df["buy_date"] >= sd) & (slot_df["buy_date"] <= ed)] if not slot_df.empty else slot_df
        sr = raw_df[(raw_df["buy_date"] >= sd) & (raw_df["buy_date"] <= ed)] if not raw_df.empty else raw_df
        eq_nav = float(np.prod(1.0 + sr.groupby("buy_date")["net_ret"].mean().to_numpy(float))) if not sr.empty else 1.0
        if ss.empty:
            out[wn] = {"trades": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0, "nav_1s": 1.0,
                       "ex3_nav": 1.0, "ex5_nav": 1.0, "mdd_mtm_pct": round(mdd_mtm, 2),
                       "mdd_tr_pct": 0.0, "sharpe": round(sharpe, 3), "eq_nav": round(eq_nav, 4),
                       "csi_pct": round(csi_p, 2), "excess_1s_pp": round(-csi_p, 2),
                       "excess_eq_pp": round((eq_nav - 1.0) * 100.0 - csi_p, 2)}
            continue
        rets = ss["net_ret"].to_numpy(float)
        w, l = rets[rets > 0], rets[rets < 0]
        plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l)) else (99.0 if len(w) else 0.0)
        nav = float(np.prod(1.0 + rets))
        s_r = np.sort(rets)
        ex3 = float(np.prod(1.0 + s_r[:-3])) if len(rets) > 3 else 1.0
        ex5 = float(np.prod(1.0 + s_r[:-5])) if len(rets) > 5 else 1.0
        ct = np.cumprod(1.0 + rets); pt = np.maximum.accumulate(np.insert(ct, 0, 1.0))[1:]
        mdd_tr = float(np.max((pt - ct) / pt) * 100.0)
        out[wn] = {
            "trades": int(len(rets)), "wr_pct": round(float((rets > 0).mean() * 100.0), 2),
            "plr": round(plr, 2), "mean_pct": round(float(rets.mean() * 100.0), 2),
            "nav_1s": round(nav, 4), "ex3_nav": round(ex3, 4), "ex5_nav": round(ex5, 4),
            "mdd_mtm_pct": round(mdd_mtm, 2), "mdd_tr_pct": round(mdd_tr, 2),
            "sharpe": round(sharpe, 3), "eq_nav": round(eq_nav, 4),
            "csi_pct": round(csi_p, 2), "excess_1s_pp": round((nav - 1.0) * 100.0 - csi_p, 2),
            "excess_eq_pp": round((eq_nav - 1.0) * 100.0 - csi_p, 2),
        }
    return out, dr


def calc_cscv_pbo(daily_mat: np.ndarray, s_blocks: int = 10) -> float:
    t_len, n_cfg = daily_mat.shape
    if n_cfg < 2: return 0.0
    gs = t_len // s_blocks
    gidx = [list(range(i * gs, (i + 1) * gs if i < s_blocks - 1 else t_len)) for i in range(s_blocks)]
    omegas = []
    for te in itertools.combinations(range(s_blocks), s_blocks // 2):
        tri = [x for k in range(s_blocks) if k not in te for x in gidx[k]]
        tei = [x for k in te for x in gidx[k]]
        rt, re_ = daily_mat[tri], daily_mat[tei]
        sd_t, sd_e = rt.std(0, ddof=1), re_.std(0, ddof=1)
        st = np.divide(rt.mean(0), sd_t, out=np.zeros_like(sd_t), where=sd_t > 1e-12)
        se = np.divide(re_.mean(0), sd_e, out=np.zeros_like(sd_e), where=sd_e > 1e-12)
        b = int(np.argmax(st))
        omegas.append(float(np.mean(se > se[b])))
    return round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2)


def build_is_perturbations(df: pd.DataFrame, fac: str) -> list[tuple[str, np.ndarray, np.ndarray | None]]:
    x = df[fac].to_numpy(float)
    is_m = (df["buy_date"] <= "2024-06-30").to_numpy()
    xis = x[is_m & np.isfinite(x)]
    uniq = np.unique(x[np.isfinite(x)])
    z = np.zeros(len(x), dtype=float)
    if set(uniq).issubset({0.0, 1.0}):
        rules = [(f"+{w}", w * x, None) for w in (5, 10, 15)] + [(f"-{w}", -w * x, None) for w in (5, 10, 15)]
        rules += [("filter_keep_1", z, (x == 1)), ("filter_skip_1", z, (x != 1))]
    elif set(uniq).issubset({-1.0, 0.0, 1.0}):
        rules = [(f"+{w}*state", w * x, None) for w in (5, 10, 15)] + [(f"-{w}*state", -w * x, None) for w in (5, 10, 15)]
        rules += [("filter_skip_neg1", z, (x != -1)), ("filter_skip_pos1", z, (x != 1))]
    else:
        if len(xis) < 10 or np.std(xis) < 1e-12:
            return []
        med = float(np.median(xis))
        std = float(np.std(xis))
        q75, q25 = float(np.quantile(xis, 0.75)), float(np.quantile(xis, 0.25))
        u = np.clip((np.nan_to_num(x, nan=med) - med) / max(std, 1e-9), -1.0, 1.0)
        rules = [(f"+{w}_lin", w * u, None) for w in (5, 10, 15)] + [(f"-{w}_lin", -w * u, None) for w in (5, 10, 15)]
        if q75 > med:
            rules.append(("filter_skip_hi75", z, (x <= q75)))
        else:
            rules.append(("filter_skip_gt0", z, (x <= 0)))
        if q25 < med:
            rules.append(("filter_skip_lo25", z, (x >= q25)))
        else:
            rules.append(("filter_skip_lt0", z, (x >= 0)))
    return rules


def run_slot_fusion_audit(pools, factor_cols, pool_ic_records, cal_dts, dt_to_idx, sh300, all_dts):
    csi_cache = {wn: get_csi_ret(sh300, all_dts, sd, ed) for wn, sd, ed in CANON_WINDOWS}
    ic_lookup = {(r["strategy"], r["factor"]): r for r in pool_ic_records}
    baselines = {}
    base_drs = {}
    base_keys = {}
    slot_results = []

    for strat in ("1to2", "3to4", "high", "2to3", "pry"):
        df = pools[strat]
        raw_b, sl_b = sim_strategy_slot(strat, df, np.zeros(len(df)))
        bm, b_dr = compute_mtm_and_windows(sl_b, raw_b, cal_dts, dt_to_idx, sh300, all_dts, csi_cache)
        baselines[strat] = bm
        base_drs[strat] = b_dr
        base_keys[strat] = set(zip(sl_b["buy_date"], sl_b["code"]))
        strat_all_drs = [b_dr]

        for fac in factor_cols:
            rules = build_is_perturbations(df, fac)
            fac_drs = [b_dr]
            cands = []
            for r_lbl, delta, emask in rules:
                raw_c, sl_c = sim_strategy_slot(strat, df, delta, emask)
                cur_keys = set(zip(sl_c["buy_date"], sl_c["code"]))
                chg_n = len(base_keys[strat] ^ cur_keys)
                cm, c_dr = compute_mtm_and_windows(sl_c, raw_c, cal_dts, dt_to_idx, sh300, all_dts, csi_cache)
                fac_drs.append(c_dr)
                strat_all_drs.append(c_dr)
                # Paired daily MTM diff t-test vs baseline
                diff_d = c_dr - b_dr
                nz = diff_d[np.abs(diff_d) > 1e-12]
                if len(nz) >= 5 and np.std(nz, ddof=1) > 1e-12:
                    t_d, p_d = stats.ttest_1samp(nz, 0.0)
                    p_diff = float(p_d)
                else:
                    t_d, p_diff = 0.0, 1.0
                cands.append({"rule": r_lbl, "changed_trades": chg_n, "added": len(cur_keys - base_keys[strat]),
                              "dropped": len(base_keys[strat] - cur_keys), "metrics": cm, "p_diff_mtm": p_diff,
                              "t_diff_mtm": round(float(t_d), 3), "dr_idx": len(fac_drs) - 1})
            if not cands:
                ic_r = ic_lookup[(strat, fac)]
                slot_results.append({
                    "strategy": strat, "factor": fac, "best_is_rule": "NONE_CONST",
                    "changed_trades": 0, "added": 0, "dropped": 0, "metrics": bm,
                    "p_diff_mtm": 1.0, "t_diff_mtm": 0.0, "pbo_factor_s8": 0.0, "pbo_factor_s10": 0.0,
                    "corr_with_base": ic_r["corr_with_base"], "q_ic_FULL": ic_r["q_ic_FULL"],
                    "q_ic_IS": ic_r["q_ic_IS"], "q_ic_OOS": ic_r["q_ic_OOS"], "q_inc_FULL": ic_r["q_inc_FULL"],
                    "q_ic_day_FULL": ic_r["q_ic_day_FULL"],
                    "gates_ex_fdr": {"g1_is": False, "g2_oos": False, "g3_2026": False, "g4_chg5": False, "g5_pbo25": True, "g6_nocol": True},
                    "all_rules": [],
                })
                continue
            # Pick IS-best candidate among changed_trades >= 5 & IS activity >= 0.7 * base_IS
            min_is = max(5, int(math.floor(0.70 * bm["IS"]["trades"])))
            valid_c = [c for c in cands if c["changed_trades"] >= 5 and c["metrics"]["IS"]["trades"] >= min_is]
            if not valid_c:
                valid_c = [c for c in cands if c["changed_trades"] >= 5]
            if not valid_c:
                valid_c = cands
            best = max(valid_c, key=lambda c: (c["metrics"]["IS"]["nav_1s"], c["metrics"]["IS"]["sharpe"]))
            mat_f = np.column_stack(fac_drs)
            pbo_s8 = calc_cscv_pbo(mat_f, 8)
            pbo_s10 = calc_cscv_pbo(mat_f, 10)
            ic_r = ic_lookup[(strat, fac)]
            # 6 Promotion Gates
            g1 = (best["metrics"]["IS"]["nav_1s"] > bm["IS"]["nav_1s"] + 1e-6) and (best["metrics"]["IS"]["sharpe"] > bm["IS"]["sharpe"] + 1e-6)
            g2 = (best["metrics"]["OOS"]["nav_1s"] > bm["OOS"]["nav_1s"] + 1e-6) and (best["metrics"]["OOS"]["sharpe"] > bm["OOS"]["sharpe"] + 1e-6)
            g3 = (best["metrics"]["Y2026"]["nav_1s"] >= 1.0) and (best["metrics"]["Y2026"]["mdd_mtm_pct"] <= bm["Y2026"]["mdd_mtm_pct"] + 1e-4)
            g4 = best["changed_trades"] >= 5
            g5_pbo = (pbo_s10 < 25.0)
            g6_col = abs(ic_r["corr_with_base"]) < 0.30
            slot_results.append({
                "strategy": strat, "factor": fac, "best_is_rule": best["rule"],
                "changed_trades": best["changed_trades"], "added": best["added"], "dropped": best["dropped"],
                "metrics": best["metrics"], "p_diff_mtm": round(best["p_diff_mtm"], 6),
                "t_diff_mtm": best["t_diff_mtm"], "pbo_factor_s8": pbo_s8, "pbo_factor_s10": pbo_s10,
                "corr_with_base": ic_r["corr_with_base"], "q_ic_FULL": ic_r["q_ic_FULL"],
                "q_ic_IS": ic_r["q_ic_IS"], "q_ic_OOS": ic_r["q_ic_OOS"], "q_inc_FULL": ic_r["q_inc_FULL"],
                "q_ic_day_FULL": ic_r["q_ic_day_FULL"],
                "gates_ex_fdr": {"g1_is": g1, "g2_oos": g2, "g3_2026": g3, "g4_chg5": g4, "g5_pbo25": g5_pbo, "g6_nocol": g6_col},
                "all_rules": [{k: v for k, v in c.items() if k != "dr_idx"} for c in cands],
            })
        strat_pbo_global_s10 = calc_cscv_pbo(np.column_stack(strat_all_drs), 10)
        baselines[strat]["global_pool_pbo_s10"] = strat_pbo_global_s10

    # BH-FDR across all 300 IS-best slot diff tests
    q_slot = bh_fdr([r["p_diff_mtm"] for r in slot_results])
    for r, qs in zip(slot_results, q_slot):
        r["q_slot_diff_mtm"] = qs
        fdr_ok = (min(r["q_ic_FULL"], r["q_inc_FULL"], qs) < 0.10)
        r["gates"] = {**r["gates_ex_fdr"], "g5_fdr10": fdr_ok}
        r["promoted"] = all(r["gates"].values())
    return baselines, slot_results
