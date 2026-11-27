#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD048 Wave 2 Step 3 Helpers: Mode B Portfolio Math, Comovement Audit, Streak Redline & Master Export."""
import json
import numpy as np
import pandas as pd
import _rd048_w2_lib as w2

def build_gem4_daily_returns(df_var: pd.DataFrame, cal_5y: list, cal_end: str = "2026-11-16", allow_fee_scale: bool = False) -> tuple[np.ndarray, pd.DataFrame]:
    """Build exact daily return series on cal_5y for a Gem4 IF/ETF variant."""
    idx = {d: i for i, d in enumerate(cal_5y)}
    T = len(cal_5y)
    sub = df_var[(df_var["buy_date"] >= "2021-11-16") & (df_var["exit_date"] <= cal_end)].copy().reset_index(drop=True)
    mult = np.ones(T, dtype=float)
    for r in sub.itertuples(index=False):
        segs = json.loads(r.mtm_pairs_json)
        p = 1.0
        parsed = []
        for dt_s, dr in segs:
            ti = idx.get(str(dt_s)[:10])
            if ti is not None:
                m = 1.0 + float(dr)
                p *= m
                parsed.append((ti, m))
        tgt = 1.0 + float(r.net_ret)
        tol = 0.02 if allow_fee_scale else 1e-4 * max(1.0, abs(tgt))
        if parsed and p > 0 and abs(p - tgt) < tol:
            parsed[-1] = (parsed[-1][0], parsed[-1][1] * (tgt / p))
        for ti, m in parsed:
            mult[ti] *= m
    dr = mult - 1.0
    nav_tr = float(np.prod(1.0 + sub["net_ret"].to_numpy(float))) if not sub.empty else 1.0
    assert abs(float(np.prod(1.0 + dr)) - nav_tr) < 1e-8, f"Gem4 MTM mismatch: {np.prod(1+dr)} vs {nav_tr}"
    return dr, sub

def calc_mode_b_accounting(dr_stk: np.ndarray, dr_fut: np.ndarray, w_fut: float, cal_5y: list) -> dict:
    """Compute FixedWeight_DailyRebal, Quarterly_Rebal, and NoRebal_Separate daily return series."""
    T = len(cal_5y)
    # 1) Daily fixed weight
    dr_fixed = (1.0 - w_fut) * dr_stk + w_fut * dr_fut
    # 2) Quarterly rebalance at end of each calendar quarter
    dr_q = np.zeros(T, dtype=float)
    v_s, v_f = 1.0 - w_fut, w_fut
    prev_tot = 1.0
    q_tags = [f"{d[:4]}-Q{(int(d[5:7]) - 1) // 3 + 1}" for d in cal_5y]
    for i in range(T):
        v_s *= (1.0 + dr_stk[i])
        v_f *= (1.0 + dr_fut[i])
        tot = v_s + v_f
        dr_q[i] = tot / prev_tot - 1.0
        if i + 1 < T and q_tags[i + 1] != q_tags[i]:
            v_s, v_f = (1.0 - w_fut) * tot, w_fut * tot
        prev_tot = tot
    # 3) Never rebalanced separate buckets
    dr_noreb = np.zeros(T, dtype=float)
    ns, nf = 1.0 - w_fut, w_fut
    p_tot = 1.0
    for i in range(T):
        ns *= (1.0 + dr_stk[i])
        nf *= (1.0 + dr_fut[i])
        tot = ns + nf
        dr_noreb[i] = tot / p_tot - 1.0
        p_tot = tot
    return {"FixedWeight_DailyRebal": dr_fixed, "Quarterly_Rebal": dr_q, "NoRebal_Separate": dr_noreb}

def eval_daily_series(name: str, group: str, dr_5y: np.ndarray, ref_dr_wf: np.ndarray, cache: dict, tr_proxy: pd.DataFrame, ref_cash_wf: np.ndarray = None) -> dict:
    """Evaluate exact 5-window MTM stats on any daily return series; overwrite trade-only nav with true MTM nav."""
    cal_5y = cache["cal_5y"]
    idx = {d: i for i, d in enumerate(cal_5y)}
    wf_off = idx[w2.eng.WF_START]
    dr_wf = dr_5y[wf_off:]
    sim_res = {"trades_df": tr_proxy, "dr_5y": dr_5y, "dr_wf": dr_wf, "mtm_diff_5y": 0.0, "mtm_diff_wf": 0.0, "waits": [], "swaps": []}
    ev = w2.eng.evaluate_bundle(name, group, sim_res, cache, ref_dr_wf=ref_dr_wf, perm_n=0)
    for wn, sdt, edt in w2.eng.EVAL_WINDOWS:
        w = ev["windows"][wn]
        w["nav"] = w["mtm_nav"]
        pos = [idx[d] for d in cal_5y if sdt <= d <= edt]
        dr_w = dr_5y[pos]
        w["ex_top5_nav"] = round(float(np.prod(1.0 + np.sort(dr_w)[:-5])), 4) if len(dr_w) > 5 else w["mtm_nav"]
    if ref_cash_wf is not None:
        dd = dr_wf - ref_cash_wf
        sd = float(np.std(dd, ddof=1))
        t_c = float(np.mean(dd) / (sd / np.sqrt(len(dr_wf)))) if sd > 1e-12 else 0.0
        ev["t_vs_cash_wf"] = round(t_c, 3)
    return ev

def audit_crash_window_comovement(tr_stk: pd.DataFrame, dr_stk: np.ndarray, df_fut: pd.DataFrame, cal_5y: list, w_fut: float = 0.15) -> dict:
    """Audit stock vs IF behavior across every rescue window and find worst combined single days."""
    idx = {d: i for i, d in enumerate(cal_5y)}
    dr_fut, _ = build_gem4_daily_returns(df_fut, cal_5y, "2026-11-16")
    dr_comb = (1.0 - w_fut) * dr_stk + w_fut * dr_fut
    # Map each day to active stock trade info
    day_stk = {}
    for r in tr_stk.itertuples(index=False):
        bi, ei = idx.get(r.buy_date), idx.get(r.exit_date)
        if bi is not None and ei is not None:
            for ti in range(bi, ei + 1):
                day_stk[cal_5y[ti]] = f"{r.name}({r.strategy},{float(r.net_ret)*100:.1f}%)"
    sub = df_fut[(df_fut["buy_date"] >= "2021-11-16") & (df_fut["exit_date"] <= "2026-11-16")].copy()
    win_rows, co_held, co_loss_win = [], 0, 0
    for r in sub.itertuples(index=False):
        bi, ei = idx[r.buy_date], idx[r.exit_date]
        stk_win_ret = float(np.prod(1.0 + dr_stk[bi : ei + 1]) - 1.0)
        comb_win_ret = float(np.prod(1.0 + dr_comb[bi : ei + 1]) - 1.0)
        held_list = sorted({day_stk[cal_5y[ti]] for ti in range(bi, ei + 1) if cal_5y[ti] in day_stk})
        if held_list:
            co_held += 1
        if stk_win_ret < 0 and float(r.net_ret) < 0:
            co_loss_win += 1
        win_rows.append({
            "buy_date": r.buy_date, "exit_date": r.exit_date, "if_ret_pct": round(float(r.net_ret) * 100.0, 2),
            "stk_win_ret_pct": round(stk_win_ret * 100.0, 2), "comb_win_ret_pct": round(comb_win_ret * 100.0, 2),
            "held_stocks": "; ".join(held_list) if held_list else "EMPTY_CASH",
        })
    # Day-level inside IF active windows
    act_mask = np.abs(dr_fut) > 1e-12
    co_loss_days = int(np.sum(act_mask & (dr_stk < 0) & (dr_fut < 0)))
    # Top 5 worst combined days across 5Y (and separately within IF active days)
    worst_all_idx = np.argsort(dr_comb)[:5]
    worst_act_idx = np.argsort(np.where(act_mask, dr_comb, 1.0))[:5]
    def _pack_days(inds):
        return [{"date": cal_5y[i], "comb_pct": round(dr_comb[i]*100, 2), "stk_pct": round(dr_stk[i]*100, 2),
                 "fut_pct": round(dr_fut[i]*100, 2), "stk_pos": day_stk.get(cal_5y[i], "EMPTY")} for i in inds]
    return {
        "n_windows": len(win_rows), "co_held_windows": co_held, "co_loss_windows": co_loss_win,
        "if_active_days": int(np.sum(act_mask)), "co_loss_days": co_loss_days,
        "worst5_combined_days_5y": _pack_days(worst_all_idx),
        "worst5_if_active_days": _pack_days(worst_act_idx),
        "windows_detail": win_rows,
    }

def bootstrap_streak_redline(rets: np.ndarray, n_boot: int = 4000, seed: int = 48) -> dict:
    """Compute empirical max losing streak and bootstrap P95/P99 stop-loss streak redline."""
    r = np.asarray(rets, dtype=float)
    n = len(r)
    if n == 0:
        return {"n": 0, "emp_max_loss_streak": 0, "boot_p95_streak": 0, "boot_p99_streak": 0}
    def _max_streak(arr):
        cur, mx = 0, 0
        for x in arr:
            if x <= 0:
                cur += 1
                mx = max(mx, cur)
            else:
                cur = 0
        return mx
    emp_mx = _max_streak(r)
    rng = np.random.default_rng(seed)
    idx_m = rng.integers(0, n, size=(n_boot, n))
    streaks = [_max_streak(r[row]) for row in idx_m]
    return {"n": int(n), "emp_max_loss_streak": int(emp_mx), "boot_p95_streak": int(np.percentile(streaks, 95)), "boot_p99_streak": int(np.percentile(streaks, 99))}

def dedupe_single_slot(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Apply sequential non-overlapping single-slot execution filter to raw candidates."""
    srt = df_raw.sort_values(["buy_date", "score", "code"], ascending=[True, False, True])
    keep, cur_ed = [], ""
    for i, r in srt.iterrows():
        if (not cur_ed) or (str(r["buy_date"]) > cur_ed):
            keep.append(i)
            cur_ed = str(r["exit_date"])
    return srt.loc[keep].copy().reset_index(drop=True)

def overlay_mode_a_on_stock_ledger(cache: dict, tr_stk: pd.DataFrame, ep_fut: pd.DataFrame, lag_s2f: int, lag_f2s: int, fee_mode: str = "030") -> tuple[pd.DataFrame, list]:
    """Overlay Mode A empty-day IF onto an already-upgraded stock ledger (e.g. V21+G1) respecting real transfer lag."""
    cal_5y = cache["cal_5y"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    by_dt_b = {dt: grp for dt, grp in tr_stk.sort_values(["buy_date", "buy_hhmm", "code"]).groupby("buy_date", sort=False)}
    by_dt_e = {dt: grp for dt, grp in ep_fut.sort_values(["buy_date", "code"]).groupby("buy_date", sort=False)} if not ep_fut.empty else {}
    taken, cur_ed, cur_eh, last_s_ti, last_f_ti = [], "", 0, -999, -999
    for ti, dt in enumerate(cal_5y):
        picked = False
        grp_b = by_dt_b.get(dt)
        if grp_b is not None:
            for r in grp_b.itertuples(index=False):
                if lag_f2s > 0 and ti < last_f_ti + lag_f2s:
                    continue
                if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh):
                    taken.append(r._asdict())
                    cur_ed, cur_eh = str(r.exit_date), int(r.exit_hhmm)
                    last_s_ti = idx_5y.get(cur_ed, ti)
                    picked = True
                    break
        if picked:
            continue
        grp_e = by_dt_e.get(dt)
        if grp_e is not None and not (lag_s2f > 0 and ti < last_s_ti + lag_s2f):
            for r in grp_e.itertuples(index=False):
                if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh):
                    taken.append(r._asdict())
                    cur_ed, cur_eh = str(r.exit_date), int(r.exit_hhmm)
                    last_f_ti = idx_5y.get(cur_ed, ti)
                    break
    return pd.DataFrame(taken), []
