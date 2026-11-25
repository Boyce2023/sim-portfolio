#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Full-pool evaluation: Spearman IC, incremental IC, collinearity, group spread & BH-FDR q-values."""
import numpy as np
import pandas as pd
import scipy.stats as stats


def bh_fdr(p_vals: list[float]) -> list[float]:
    arr = np.asarray([1.0 if (p is None or np.isnan(p)) else float(p) for p in p_vals], dtype=float)
    m = len(arr)
    if m == 0:
        return []
    order = np.argsort(arr)
    ranked = arr[order]
    q = np.empty(m, dtype=float)
    prev = 1.0
    for i in range(m - 1, -1, -1):
        val = min(prev, ranked[i] * m / (i + 1.0))
        q[i] = val
        prev = val
    out = np.empty(m, dtype=float)
    out[order] = np.clip(q, 0.0, 1.0)
    return [round(float(x), 6) for x in out]


def _win_masks(df: pd.DataFrame) -> dict[str, np.ndarray]:
    bd = df["buy_date"].to_numpy()
    return {
        "FULL": (bd >= "2021-11-16") & (bd <= "2026-11-16"),
        "IS": (bd >= "2021-11-16") & (bd <= "2024-06-30"),
        "OOS": (bd >= "2024-07-04") & (bd <= "2026-11-16"),
        "Y2026": (bd >= "2026-01-01") & (bd <= "2026-11-16"),
    }


def _spearman_and_inc(x: np.ndarray, base_s: np.ndarray, y: np.ndarray, buy_dates: np.ndarray = None):
    valid = np.isfinite(x) & np.isfinite(base_s) & np.isfinite(y)
    xv, bv, yv = x[valid], base_s[valid], y[valid]
    if len(xv) < 8 or np.unique(xv).size < 2:
        return {"n": int(len(xv)), "ic": None, "p": 1.0, "inc_ic": None, "inc_p": 1.0, "ic_day": None, "p_day": 1.0, "n_days": 0}
    r, p = stats.spearmanr(xv, yv)
    # Date-clustered (daily-mean) Spearman IC to avoid clustered-date N inflation on macro/pry factors
    ic_day, p_day, n_days = None, 1.0, 0
    if buy_dates is not None:
        dv = pd.DataFrame({"dt": buy_dates[valid], "x": xv, "y": yv}).groupby("dt", sort=False).mean()
        n_days = int(len(dv))
        if n_days >= 8 and dv["x"].nunique() >= 2:
            rd, pd_v = stats.spearmanr(dv["x"].to_numpy(), dv["y"].to_numpy())
            ic_day = round(float(rd), 4) if np.isfinite(rd) else None
            p_day = round(float(pd_v), 6) if np.isfinite(pd_v) else 1.0
    if np.unique(bv).size < 2:
        return {"n": int(len(xv)), "ic": round(float(r), 4), "p": round(float(p), 6),
                "inc_ic": round(float(r), 4), "inc_p": round(float(p), 6),
                "ic_day": ic_day, "p_day": p_day, "n_days": n_days}
    # Exact partial Spearman correlation r_{XY.B} avoiding tie-splitting leakage on sparse binary X
    r_xb, _ = stats.spearmanr(xv, bv)
    r_yb, _ = stats.spearmanr(yv, bv)
    denom = float(np.sqrt(max(1e-12, (1.0 - r_xb ** 2) * (1.0 - r_yb ** 2))))
    ir = float(np.clip((r - r_xb * r_yb) / denom, -0.9999, 0.9999))
    df_t = max(1, len(xv) - 3)
    t_inc = ir * np.sqrt(df_t / max(1e-12, 1.0 - ir ** 2))
    ip = float(2.0 * stats.t.sf(abs(t_inc), df=df_t))
    return {
        "n": int(len(xv)),
        "ic": round(float(r), 4),
        "p": round(float(p), 6),
        "inc_ic": round(float(ir), 4),
        "inc_p": round(float(ip), 6),
        "ic_day": ic_day, "p_day": p_day, "n_days": n_days,
    }


def _group_spread(x: np.ndarray, y: np.ndarray, ref_is: np.ndarray):
    valid = np.isfinite(x) & np.isfinite(y)
    xv, yv = x[valid], y[valid]
    if len(xv) < 10 or np.unique(xv).size < 2:
        return {"n_hi": 0, "n_lo": 0, "spread_pp": None, "welch_t": None, "welch_p": 1.0}
    uniq = np.unique(xv)
    if len(uniq) <= 3:
        hi_m = (xv == uniq.max())
        lo_m = (xv == uniq.min())
    else:
        xis = ref_is[np.isfinite(ref_is)]
        if len(xis) >= 15 and (xis == 0).mean() > 0.60:
            hi_m = (xv > 0)
            lo_m = (xv <= 0)
            if hi_m.sum() < 5 or lo_m.sum() < 5:
                q_hi = np.quantile(xis, 0.75)
                hi_m = (xv >= q_hi)
                lo_m = (xv < q_hi)
        else:
            ref = xis if len(xis) >= 15 else xv
            q33, q67 = np.quantile(ref, 0.3333), np.quantile(ref, 0.6667)
            if q67 > q33:
                hi_m = (xv >= q67)
                lo_m = (xv <= q33)
            else:
                med = np.median(ref)
                hi_m = (xv > med)
                lo_m = (xv <= med)
    rh, rl = yv[hi_m], yv[lo_m]
    if len(rh) < 3 or len(rl) < 3:
        return {"n_hi": int(len(rh)), "n_lo": int(len(rl)), "spread_pp": None, "welch_t": None, "welch_p": 1.0}
    t_v, p_v = stats.ttest_ind(rh, rl, equal_var=False)
    return {
        "n_hi": int(len(rh)), "n_lo": int(len(rl)),
        "mean_hi_pct": round(float(rh.mean() * 100.0), 3),
        "mean_lo_pct": round(float(rl.mean() * 100.0), 3),
        "wr_hi_pct": round(float((rh > 0).mean() * 100.0), 2),
        "wr_lo_pct": round(float((rl > 0).mean() * 100.0), 2),
        "spread_pp": round(float((rh.mean() - rl.mean()) * 100.0), 3),
        "welch_t": round(float(t_v), 3) if np.isfinite(t_v) else 0.0,
        "welch_p": round(float(p_v), 6) if np.isfinite(p_v) else 1.0,
    }


def evaluate_all_pools_ic_spread(pools: dict, factor_cols: list[str]) -> list[dict]:
    records = []
    for strat, df in pools.items():
        sub = df[df["sim_ok"]].copy() if strat == "1to2" else df
        wmasks = _win_masks(sub)
        base_s = sub["v20_score"].to_numpy(float)
        y = sub["net_ret"].to_numpy(float)
        bd_arr = sub["buy_date"].to_numpy()
        for fac in factor_cols:
            x = sub[fac].to_numpy(float)
            # Collinearity with existing scorecard
            v_col = np.isfinite(x) & np.isfinite(base_s)
            if v_col.sum() >= 10 and np.unique(x[v_col]).size >= 2 and np.unique(base_s[v_col]).size >= 2:
                cr, cp = stats.spearmanr(x[v_col], base_s[v_col])
                col_r = round(float(cr), 4)
            else:
                col_r = 0.0
            ic_w, sp_w = {}, {}
            ref_is = x[wmasks["IS"]]
            for wn, m in wmasks.items():
                ic_w[wn] = _spearman_and_inc(x[m], base_s[m], y[m], bd_arr[m])
                sp_w[wn] = _group_spread(x[m], y[m], ref_is)
            records.append({
                "strategy": strat, "factor": fac, "corr_with_base": col_r,
                "ic": ic_w, "spread": sp_w,
            })

    # BH-FDR across all 300 (strategy x factor) tests
    for p_key, q_key in [("ic_FULL", "q_ic_FULL"), ("ic_IS", "q_ic_IS"), ("ic_OOS", "q_ic_OOS"), ("inc_FULL", "q_inc_FULL"), ("sp_FULL", "q_sp_FULL"), ("day_FULL", "q_ic_day_FULL")]:
        if p_key.startswith("ic_"):
            wn = p_key.split("_")[1]
            pvals = [r["ic"][wn]["p"] for r in records]
        elif p_key == "inc_FULL":
            pvals = [r["ic"]["FULL"]["inc_p"] for r in records]
        elif p_key == "day_FULL":
            pvals = [r["ic"]["FULL"]["p_day"] for r in records]
        else:
            pvals = [r["spread"]["FULL"]["welch_p"] for r in records]
        qvals = bh_fdr(pvals)
        for r, qv in zip(records, qvals):
            r[q_key] = qv
    return records
