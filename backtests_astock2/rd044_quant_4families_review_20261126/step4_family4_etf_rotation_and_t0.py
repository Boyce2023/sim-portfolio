#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD044 Step 4 — Family 4: A-Share Core ETF Rotation (Momentum*R2, Multi-Asset Risk Parity)
& V20.0 Empty-Slot Zero-Collision T+0 ETF Cash Enhancement.
Zero yfinance (D12). Strict listing-date + 65d warmup guard. 5bps & 15bps cost tiers.
"""
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

RD044_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd044_quant_4families_review_20261126"
if RD044_DIR not in sys.path:
    sys.path.insert(0, RD044_DIR)

import _rd044_common as cm

CACHE_DIR = cm.CACHE_DIR


def load_etf_matrices(end_dt: str = "2026-11-25") -> dict:
    """Load cached 19 ETFs QFQ bars aligned to full trading calendar (2020-06-01 .. end_dt)."""
    df = pd.read_parquet(f"{RD044_DIR}/etf_daily_qfq_cache.parquet")
    df = df[df["dt"] <= end_dt].sort_values(["code", "dt"]).reset_index(drop=True)

    bench_ctx = cm.load_bench_and_v20(end_dt="2026-11-24" if end_dt >= "2026-11-24" else end_dt)
    eval_dts = bench_ctx["cal_dts"]  # starts 2021-01-04
    all_dts = sorted(df["dt"].unique())
    dt_map = {d: i for i, d in enumerate(all_dts)}

    codes = sorted(df["code"].unique())
    c_map = {c: i for i, c in enumerate(codes)}
    meta = df.groupby("code").first()[["name", "category", "is_t0"]].to_dict("index")

    N_D, N_E = len(all_dts), len(codes)
    op = np.full((N_D, N_E), np.nan, dtype=np.float64)
    cl = np.full((N_D, N_E), np.nan, dtype=np.float64)
    vol = np.full((N_D, N_E), np.nan, dtype=np.float64)
    elig = np.zeros((N_D, N_E), dtype=bool)

    for c, g in df.groupby("code", sort=False):
        j = c_map[c]
        g = g.sort_values("dt").reset_index(drop=True)
        for k, row in enumerate(g.itertuples(index=False)):
            ti = dt_map[row.dt]
            op[ti, j] = row.open
            cl[ti, j] = row.close
            vol[ti, j] = row.volume
            # Strictly require >= 65 prior trading bars before eligible for 60d mom/vol
            if k >= 65 and row.open > 0 and row.close > 0 and row.volume > 0:
                elig[ti, j] = True

    # Forward-fill close for MTM valuation on rare missing dates
    cl_ff = cl.copy()
    for j in range(N_E):
        last = np.nan
        for i in range(N_D):
            if np.isfinite(cl_ff[i, j]):
                last = cl_ff[i, j]
            else:
                cl_ff[i, j] = last

    # Compute strictly T-1 causal features:
    # 1. Trailing 20d & 60d slope*R2 of log(close) up to t-1
    # 2. Trailing 20d & 60d simple return up to t-1
    # 3. Trailing 60d annualized volatility up to t-1
    mom_r2_20 = np.full((N_D, N_E), np.nan, dtype=np.float64)
    mom_r2_60 = np.full((N_D, N_E), np.nan, dtype=np.float64)
    ret_20 = np.full((N_D, N_E), np.nan, dtype=np.float64)
    ret_60 = np.full((N_D, N_E), np.nan, dtype=np.float64)
    vol_60 = np.full((N_D, N_E), np.nan, dtype=np.float64)

    def _slope_r2(y_arr):
        n = len(y_arr)
        x = np.arange(n, dtype=np.float64)
        xm = x - x.mean()
        ym = y_arr - y_arr.mean()
        xx = float(np.dot(xm, xm))
        yy = float(np.dot(ym, ym))
        xy = float(np.dot(xm, ym))
        if xx <= 1e-12 or yy <= 1e-12:
            return 0.0
        b = xy / xx
        r2 = (xy * xy) / (xx * yy)
        return (math.exp(b * 242.0) - 1.0) * r2

    for j in range(N_E):
        c_ser = cl_ff[:, j]
        r1 = np.zeros(N_D, dtype=np.float64)
        ok_r = (np.arange(N_D) > 0) & np.isfinite(c_ser)
        for i in range(1, N_D):
            if np.isfinite(c_ser[i]) and np.isfinite(c_ser[i - 1]) and c_ser[i - 1] > 0:
                r1[i] = c_ser[i] / c_ser[i - 1] - 1.0

        for t in range(65, N_D):
            if not elig[t, j]:
                continue
            w20 = c_ser[t - 20 : t]
            w60 = c_ser[t - 60 : t]
            if np.all(np.isfinite(w20) & (w20 > 0)):
                mom_r2_20[t, j] = _slope_r2(np.log(w20))
                ret_20[t, j] = c_ser[t - 1] / c_ser[t - 21] - 1.0 if t >= 21 and np.isfinite(c_ser[t - 21]) else np.nan
            if np.all(np.isfinite(w60) & (w60 > 0)):
                mom_r2_60[t, j] = _slope_r2(np.log(w60))
                ret_60[t, j] = c_ser[t - 1] / c_ser[t - 61] - 1.0 if t >= 61 and np.isfinite(c_ser[t - 61]) else np.nan
                vol_60[t, j] = float(np.std(r1[t - 60 : t], ddof=1) * math.sqrt(242.0))

    return {
        "all_dts": all_dts,
        "dt_map": dt_map,
        "eval_dts": eval_dts,
        "codes": codes,
        "c_map": c_map,
        "meta": meta,
        "open": op,
        "close": cl_ff,
        "elig": elig,
        "mom_r2_20": mom_r2_20,
        "mom_r2_60": mom_r2_60,
        "ret_20": ret_20,
        "ret_60": ret_60,
        "vol_60": vol_60,
    }


def simulate_etf_weights(
    em: dict,
    target_weights_fn,
    rebal_days: int = 10,
    fee_rt: float = 0.0005,
    start_dt: str = "2021-01-04",
    end_dt: str = "2026-11-24",
) -> dict:
    """
    Exact daily open-to-open ETF portfolio simulator aligned to eval_dts.
    Only trades weight deltas on rebalance days; pays half of `fee_rt` on buys and half on sells.
    """
    all_dts = em["all_dts"]
    dt_map = em["dt_map"]
    eval_dts = [d for d in em["eval_dts"] if start_dt <= d <= end_dt]
    N_E = len(em["codes"])
    op = em["open"]
    cl = em["close"]
    elig = em["elig"]

    fee_side = 0.5 * fee_rt
    qty = np.zeros(N_E, dtype=np.float64)
    cash = 1.0
    nav_prev = 1.0

    T_ev = len(eval_dts)
    dr = np.zeros(T_ev, dtype=np.float64)
    to_d = np.zeros(T_ev, dtype=np.float64)
    act_d = np.zeros(T_ev, dtype=bool)
    w_hist = np.zeros((T_ev, N_E), dtype=np.float64)

    for idx, d in enumerate(eval_dts):
        t = dt_map.get(d)
        if t is None:
            continue
        traded = 0.0
        if idx % rebal_days == 0:
            tgt_w = target_weights_fn(t, em)  # shape (N_E,), sum <= 1.0
            # Value current portfolio at open[t]
            px_o = np.where(np.isfinite(op[t]) & (op[t] > 0), op[t], cl[t])
            tot_open = cash + float(np.sum(qty * np.nan_to_num(px_o, nan=0.0)))
            # Sell overweight
            for j in range(N_E):
                if not np.isfinite(px_o[j]) or px_o[j] <= 0:
                    continue
                cur_v = qty[j] * px_o[j]
                want_v = tgt_w[j] * tot_open
                if cur_v > want_v + 1e-8:
                    sell_v = cur_v - want_v
                    dq = min(qty[j], sell_v / px_o[j])
                    qty[j] -= dq
                    traded += dq * px_o[j]
                    cash += dq * px_o[j] * (1.0 - fee_side)
            # Buy underweight
            wants = []
            for j in range(N_E):
                if tgt_w[j] <= 0 or not elig[t, j] or not np.isfinite(px_o[j]) or px_o[j] <= 0:
                    continue
                cur_v = qty[j] * px_o[j]
                want_v = tgt_w[j] * tot_open
                if want_v > cur_v + 1e-8:
                    wants.append((j, px_o[j], want_v - cur_v))
            tot_w_need = sum(x[2] for x in wants)
            if tot_w_need > 1e-9 and cash > 1e-9:
                sc = min(1.0, cash / (tot_w_need * (1.0 + fee_side)))
                for j, px, wv in wants:
                    sp = wv * sc
                    qty[j] += sp / px
                    traded += sp
                    cash -= sp * (1.0 + fee_side)

        px_c = np.nan_to_num(cl[t], nan=0.0)
        pos_v = float(np.sum(qty * px_c))
        nav_now = cash + pos_v
        dr[idx] = nav_now / nav_prev - 1.0 if nav_prev > 0 else 0.0
        to_d[idx] = traded / (2.0 * nav_prev) if nav_prev > 0 else 0.0
        act_d[idx] = pos_v > 0.01 * nav_now
        if nav_now > 0:
            w_hist[idx] = (qty * px_c) / nav_now
        nav_prev = nav_now

    return {"dr": dr, "to_daily": to_d, "act_mask": act_d, "w_hist": w_hist, "eval_dts": eval_dts}


def run_v20_t0_cash_enhancement(em: dict, bench_ctx: dict, end_dt: str = "2026-11-24") -> list[dict]:
    """
    Compare T+0 ETFs (518880 Gold, 511010 Bond, 513100 Nasdaq, 513180 HSTECH, and Mom-Selected T0)
    vs T+1 ETF (510300 CSI300) on V20.0 empty days across 3 honest physical execution boundaries:
      1. Intraday_T0_ZeroCollision: buy T0 ETF at 09:30 open -> sell at 14:55 close on V20 empty days (0 collisions).
      2. Overnight_FreeSlot_NoWait: hold across v20_empty_strict_no_stier_wait streaks, sell at close BEFORE V20 reentry vs
         Strict_0925_CashLock (holding into V20 09:25 day blocks V20 morning buy!).
    """
    v20_cal = bench_ctx["v20_cal"]
    v20_cal = v20_cal[v20_cal["trade_date"].between("2021-11-16", end_dt)].sort_values("trade_date").reset_index(drop=True)
    dts = v20_cal["trade_date"].tolist()
    v20_dr = v20_cal["v20_daily_ret"].fillna(0.0).to_numpy(float)
    v20_occ = v20_cal["v20_occupied"].to_numpy(bool)
    v20_emp = v20_cal["v20_empty_slot"].to_numpy(bool)
    v20_wait = v20_cal["v20_has_wait"].to_numpy(bool)
    v20_stier_wait = v20_cal["v20_has_stier_wait"].to_numpy(bool)
    v20_buy_hhmm = v20_cal["v20_buy_hhmm"].fillna(0).to_numpy(int)

    # Map ETF open/close onto dts
    dt_map = em["dt_map"]
    c_map = em["c_map"]
    op = em["open"]
    cl = em["close"]
    elig = em["elig"]

    def _stats_v20(arr):
        nv = float(np.prod(1.0 + arr))
        cv = np.concatenate([[1.0], np.cumprod(1.0 + arr)])
        pk = np.maximum.accumulate(cv)
        mdd = float(np.max((pk - cv) / pk) * 100.0)
        sd = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
        sh = float(np.mean(arr) / sd * math.sqrt(242.0)) if sd > 1e-12 else 0.0
        cagr = (nv ** (242.0 / len(arr)) - 1.0) * 100.0 if nv > 0 else -100.0
        return nv, cagr, sh, mdd

    wf_idx = [i for i, d in enumerate(dts) if d >= "2023-01-03"]
    base_nv, base_cagr, base_sh, base_mdd = _stats_v20(v20_dr[wf_idx])

    out = []
    # Test individual T+0 ETFs & T+1 CSI300 & Momentum-selected T+0
    test_etfs = ["511010", "518880", "513100", "513180", "510300", "MOM_T0_BEST"]
    t0_pool = ["511010", "518880", "513100", "513180"]

    for code in test_etfs:
        is_t0 = (code != "510300")
        for fee in [0.0005, 0.0015]:
            # Mode 1: Pure Intraday (09:30 -> 14:55) ONLY possible for T+0! (T+1 cannot sell same day!)
            if is_t0:
                emp_ret_intra = np.zeros(len(dts), dtype=float)
                comb_intra = v20_dr.copy()
                n_trig = 0
                for i, d in enumerate(dts):
                    if not v20_emp[i]:
                        continue
                    ti = dt_map[d]
                    pick_c = code
                    if code == "MOM_T0_BEST":
                        # Pick highest 20d return among eligible T0 ETFs
                        best_c, best_m = "511010", -1e9
                        for tc in t0_pool:
                            tj = c_map[tc]
                            if elig[ti, tj] and np.isfinite(em["ret_20"][ti, tj]) and em["ret_20"][ti, tj] > best_m:
                                best_m = em["ret_20"][ti, tj]
                                pick_c = tc
                    j = c_map[pick_c]
                    if elig[ti, j] and op[ti, j] > 0 and cl[ti, j] > 0:
                        r_i = (cl[ti, j] / op[ti, j]) * (1.0 - fee) - 1.0
                        emp_ret_intra[i] = r_i
                        comb_intra[i] = r_i
                        n_trig += 1
                nv, cagr, sh, mdd = _stats_v20(comb_intra[wf_idx])
                emp_wf_nv = float(np.prod(1.0 + emp_ret_intra[wf_idx]))
                out.append({
                    "mode": "Intraday_T0_ZeroCollision",
                    "etf": code, "is_t0": is_t0, "fee_bps": int(round(fee * 10000)),
                    "n_days_active_5y": n_trig, "v20_collisions": 0,
                    "empty_only_wf_nav": round(emp_wf_nv, 4),
                    "combined_wf_nav": round(nv, 2), "nav_ratio_vs_v20": round(nv / base_nv, 4),
                    "combined_wf_sharpe": round(sh, 3), "delta_sharpe": round(sh - base_sh, 3),
                    "combined_wf_mdd": round(mdd, 2),
                })

            # Mode 2: Overnight Hold Across Empty Streaks (honest 09:25 cash-lock collision simulation!)
            # If you buy ETF on empty day t (at 14:55 close if no wait, or 09:30 open) and hold overnight to sell at t+1 09:30 open:
            # - If V20 enters at t+1 09:25 call auction (v20_buy_hhmm == 925):
            #   Since you are STILL holding the ETF through t+1 09:25, your cash is locked at 09:25 -> MISS that V20 entry!
            # - If V20 enters at t+1 intraday (>= 930):
            #   A T+0 OR T+1 ETF bought on day t CAN be sold at t+1 09:30 open -> cash is IMMEDIATELY free for t+1 intraday buy!
            #   HOWEVER, if you bought the ETF at t 09:30 and V20 triggered intraday ON DAY t itself:
            #   T+0 ETF sells intraday on day t (0 collision on day t!), whereas T+1 ETF CANNOT sell on day t!
            # Let's simulate honest chronological Multi-day Empty-Streak Hold (buy t open when v20_empty_slot, sell next day open;
            # if next day t+1 has v20 09:25 buy -> collides & blocks V20 trade for the duration of that V20 trade!).
            if fee == 0.0005:  # test strict collision ledger at realistic 5bps
                v20_led = pd.read_parquet(f"{cm.BASE_DIR}/v20_baseline_ledger_278.parquet")
                v20_by_entry = {r.buy_date: r for r in v20_led.itertuples(index=False)}
                comb_ov = np.zeros(len(dts), dtype=float)
                emp_ov = np.zeros(len(dts), dtype=float)
                held_etf = None
                v20_lock_until = ""
                n_collided_v20 = 0
                i = 0
                while i < len(dts):
                    d = dts[i]
                    ti = dt_map[d]
                    # Check if holding ETF overnight from yesterday
                    if held_etf is not None:
                        j = c_map[held_etf]
                        # Return from yesterday close to today open (sell at open)
                        prev_c = cl[dt_map[dts[i - 1]], j]
                        cur_o = op[ti, j]
                        ov_r = (cur_o / prev_c) - 1.0 - 0.5 * fee if (prev_c > 0 and cur_o > 0) else 0.0
                        held_etf = None
                        # Check if V20 wanted to buy at 09:25 TODAY!
                        v20_tr = v20_by_entry.get(d)
                        if v20_tr is not None and int(v20_tr.buy_hhmm) <= 925:
                            # Collision! Cash was locked in ETF at 09:25 auction!
                            n_collided_v20 += 1
                            comb_ov[i] = ov_r
                            emp_ov[i] = ov_r
                            v20_lock_until = ""  # missed V20 trade, slot remains free today
                            i += 1
                            continue
                        elif v20_tr is not None and int(v20_tr.buy_hhmm) > 925:
                            # V20 buys intraday! ETF sold at 09:30 open freed cash for V20!
                            comb_ov[i] = (1.0 + ov_r) * (1.0 + v20_dr[i]) - 1.0
                            emp_ov[i] = ov_r
                            v20_lock_until = str(v20_tr.exit_date)
                            i += 1
                            continue
                        else:
                            # V20 is empty today too: we sold at open (or keep holding)
                            comb_ov[i] = ov_r
                            emp_ov[i] = ov_r
                    # Not blocked by overnight ETF at 09:25 -> check V20 status
                    if d <= v20_lock_until or v20_occ[i]:
                        comb_ov[i] += v20_dr[i]
                        i += 1
                        continue
                    # V20 is empty today -> buy ETF at 14:55 close? Wait: if buy at close today, earn overnight to t+1 open!
                    pick_c = code
                    if code == "MOM_T0_BEST":
                        best_c, best_m = "511010", -1e9
                        for tc in t0_pool:
                            tj = c_map[tc]
                            if elig[ti, tj] and np.isfinite(em["ret_20"][ti, tj]) and em["ret_20"][ti, tj] > best_m:
                                best_m = em["ret_20"][ti, tj]
                                pick_c = tc
                    j = c_map[pick_c]
                    if elig[ti, j]:
                        held_etf = pick_c
                        comb_ov[i] -= 0.5 * fee
                        emp_ov[i] -= 0.5 * fee
                    i += 1

                nv2, cagr2, sh2, mdd2 = _stats_v20(comb_ov[wf_idx])
                emp2_nv = float(np.prod(1.0 + emp_ov[wf_idx]))
                out.append({
                    "mode": "Overnight_Strict_0925_CashLock",
                    "etf": code, "is_t0": is_t0, "fee_bps": 5,
                    "n_days_active_5y": int((np.abs(emp_ov) > 1e-9).sum()), "v20_collisions": n_collided_v20,
                    "empty_only_wf_nav": round(emp2_nv, 4),
                    "combined_wf_nav": round(nv2, 2), "nav_ratio_vs_v20": round(nv2 / base_nv, 4),
                    "combined_wf_sharpe": round(sh2, 3), "delta_sharpe": round(sh2 - base_sh, 3),
                    "combined_wf_mdd": round(mdd2, 2),
                })

    return out


def run_family4(end_dt: str = "2026-11-24", run_trunc_check: bool = True) -> dict:
    t0 = time.time()
    bench_ctx = cm.load_bench_and_v20(end_dt=end_dt)
    em = load_etf_matrices(end_dt="2026-11-25" if end_dt >= "2026-11-24" else end_dt)
    codes = em["codes"]
    c_map = em["c_map"]
    N_E = len(codes)

    # Pool excluding 513330 (keep exact 18 requested ETFs, with 513180 HSTECH; also test 511010 as offensive vs hedge)
    pool_18_all = [c for c in codes if c != "513330"]
    pool_17_risky = [c for c in pool_18_all if c != "511010"]  # 511010 reserved as safe haven
    rp_6 = ["510300", "512100", "510880", "513100", "518880", "511010"]

    results = []
    daily_series = {}

    def _add_res(tag: str, cat: str, sim: dict, fee: float, extra: dict = None):
        ev = cm.evaluate_daily_series(sim["dr"], bench_ctx, turnover_daily=sim["to_daily"], active_mask=sim["act_mask"])
        row = {
            "family": "F4_ETF",
            "strategy_id": tag,
            "subtype": cat,
            "fee_bps": int(round(fee * 10000)),
            "windows": ev,
        }
        if extra:
            row.update(extra)
        results.append(row)
        daily_series[tag] = sim["dr"]
        return row

    # 1. ETF_MOM: Slope*R2 (20d, 60d, or blended 20d+60d) Top 2 / Top 3, Reb 5/10/20, Abs Mom Switch to 511010
    def _make_mom_fn(score_type: str, top_k: int, abs_filter: bool, hedge_code: str = "511010"):
        def _fn(t, e_mat):
            w = np.zeros(N_E, dtype=np.float64)
            cands = []
            for c in (pool_17_risky if abs_filter else pool_18_all):
                j = c_map[c]
                if not e_mat["elig"][t, j]:
                    continue
                if score_type == "R2_20":
                    sc = e_mat["mom_r2_20"][t, j]
                    ab = e_mat["ret_20"][t, j]
                elif score_type == "R2_60":
                    sc = e_mat["mom_r2_60"][t, j]
                    ab = e_mat["ret_60"][t, j]
                else:  # Blended 20+60
                    s1, s2 = e_mat["mom_r2_20"][t, j], e_mat["mom_r2_60"][t, j]
                    sc = 0.5 * s1 + 0.5 * s2 if (np.isfinite(s1) and np.isfinite(s2)) else np.nan
                    ab = e_mat["ret_20"][t, j]
                if np.isfinite(sc):
                    cands.append((sc, j, ab))
            cands.sort(key=lambda x: -x[0])
            picks = cands[:top_k]
            if not picks:
                w[c_map[hedge_code]] = 1.0
                return w
            slot_w = 1.0 / len(picks)
            hj = c_map[hedge_code]
            for sc, j, ab in picks:
                if abs_filter and (not np.isfinite(ab) or ab <= 0.0):
                    w[hj] += slot_w
                else:
                    w[j] += slot_w
            return w
        return _fn

    for sc_t in ["R2_20", "R2_60", "R2_20_60"]:
        for tk in [2, 3]:
            for reb in [5, 10, 20]:
                for ab_sw in [True, False]:
                    for fee in [0.0005, 0.0015]:
                        tag = f"F4_MOM_{sc_t}_K{tk}_H{reb}_{'AbsBond' if ab_sw else 'Raw'}_{int(fee*10000)}bp"
                        sim = simulate_etf_weights(em, _make_mom_fn(sc_t, tk, ab_sw), rebal_days=reb, fee_rt=fee, end_dt=end_dt)
                        _add_res(tag, "ETF_MOM", sim, fee, {"top_k": tk, "rebal_days": reb, "abs_filter": ab_sw})

    # 2. ETF_RP: 6-Asset Risk Parity (60d inv-vol) & Bond-Capped RP & Trend-RP
    def _make_rp_fn(bond_cap: float = 1.0, trend_filter: bool = False):
        def _fn(t, e_mat):
            w = np.zeros(N_E, dtype=np.float64)
            inv_v = {}
            for c in rp_6:
                j = c_map[c]
                v = e_mat["vol_60"][t, j]
                if e_mat["elig"][t, j] and np.isfinite(v) and v > 1e-4:
                    inv_v[j] = 1.0 / v
            if not inv_v:
                return w
            tot = sum(inv_v.values())
            for j, iv in inv_v.items():
                w[j] = iv / tot
            # Apply optional bond cap (redistribute excess pro-rata to non-bond assets)
            bj = c_map["511010"]
            if bond_cap < 1.0 and w[bj] > bond_cap:
                excess = w[bj] - bond_cap
                w[bj] = bond_cap
                other_sum = sum(w[j] for j in inv_v if j != bj)
                if other_sum > 0:
                    for j in inv_v:
                        if j != bj:
                            w[j] += excess * (w[j] / other_sum)
            # Apply optional 60d trend cut on risky assets (half weight -> bond if ret_60 < 0)
            if trend_filter:
                for c in rp_6:
                    if c in ("511010", "518880"):
                        continue
                    j = c_map[c]
                    r60 = e_mat["ret_60"][t, j]
                    if np.isfinite(r60) and r60 < 0.0:
                        cut = 0.5 * w[j]
                        w[j] -= cut
                        w[bj] += cut
            return w
        return _fn

    for bcap, tf, nm in [(1.0, False, "Pure60d"), (0.50, False, "BondCap50"), (0.40, True, "BondCap40_Trend")]:
        for reb in [10, 20]:
            for fee in [0.0005, 0.0015]:
                sim = simulate_etf_weights(em, _make_rp_fn(bcap, tf), rebal_days=reb, fee_rt=fee, end_dt=end_dt)
                _add_res(f"F4_RP_{nm}_H{reb}_{int(fee*10000)}bp", "ETF_RP", sim, fee, {"rebal_days": reb})

    # 3. Also test Standalone Equal-Weight Core Portfolio & Gold+Bond+Nasdaq Benchmark
    def _ew_6(t, e_mat):
        w = np.zeros(N_E, dtype=np.float64)
        avail = [c_map[c] for c in rp_6 if e_mat["elig"][t, c_map[c]]]
        for j in avail:
            w[j] = 1.0 / len(avail)
        return w
    sim_ew6 = simulate_etf_weights(em, _ew_6, rebal_days=20, fee_rt=0.0005, end_dt=end_dt)
    _add_res("F4_BENCH_EW6_H20_5bp", "ETF_BENCH", sim_ew6, 0.0005)

    # 4. V20.0 Empty-Slot T+0 Cash Enhancement
    t0_cash_res = run_v20_t0_cash_enhancement(em, bench_ctx, end_dt=end_dt)

    # Physical truncation 2024-12-31 check on best MOM and best RP
    mom_5bp = [r for r in results if r["subtype"] == "ETF_MOM" and r["fee_bps"] == 5]
    best_mom = max(mom_5bp, key=lambda r: r["windows"]["WF_OOS"]["sharpe"])
    rp_5bp = [r for r in results if r["subtype"] == "ETF_RP" and r["fee_bps"] == 5]
    best_rp = max(rp_5bp, key=lambda r: r["windows"]["WF_OOS"]["sharpe"])

    trunc_audit = {}
    if run_trunc_check:
        em_tr = load_etf_matrices(end_dt="2024-12-31")
        # Parse best_mom params
        parts = best_mom["strategy_id"].split("_")
        sc_t = parts[2] + "_" + parts[3] if parts[2] == "R2" and parts[3] in ("20", "60") and parts[4] != "60" else "R2_20_60"
        tk = best_mom["top_k"]
        reb = best_mom["rebal_days"]
        ab_sw = best_mom["abs_filter"]
        sim_tr = simulate_etf_weights(em_tr, _make_mom_fn(sc_t, tk, ab_sw), rebal_days=reb, fee_rt=0.0005, end_dt="2024-12-31")
        n_tr = len(sim_tr["eval_dts"])
        diff_m = float(np.max(np.abs(daily_series[best_mom["strategy_id"]][:n_tr] - sim_tr["dr"][:n_tr])))
        trunc_audit = {"strategy_id": best_mom["strategy_id"], "n_days_to_20241231": int(n_tr), "max_abs_ret_diff": diff_m, "passed": diff_m == 0.0}
        print(f"[Family4] 2024-12-31 Physical Truncation Check ({best_mom['strategy_id']}): max_abs_diff={diff_m}")

    np.savez_compressed(f"{CACHE_DIR}/f4_daily_returns.npz", cal_dts=np.array(bench_ctx["cal_dts"]), **{k: v for k, v in daily_series.items()})
    out_obj = {
        "family": "F4_ETF",
        "elapsed_sec": round(time.time() - t0, 1),
        "best_mom": best_mom["strategy_id"],
        "best_rp": best_rp["strategy_id"],
        "physical_truncation_20241231": trunc_audit,
        "t0_cash_enhancement": t0_cash_res,
        "results": results,
    }
    with open(f"{CACHE_DIR}/f4_results.json", "w", encoding="utf-8") as f:
        json.dump(out_obj, f, ensure_ascii=False, indent=2)

    print("\n=== FAMILY 4 TOP OOS SUMMARY (WF 2023-01-03..2026-11-24) ===")
    for r in sorted(results, key=lambda x: -x["windows"]["WF_OOS"]["sharpe"])[:12]:
        w = r["windows"]["WF_OOS"]
        print(f"{r['strategy_id']:42s} | CAGR={w['cagr_pct']:6.2f}% | Sh={w['sharpe']:5.3f} | MDD={w['mdd_pct']:5.2f}% | Cal={w['calmar']:5.2f} | TO={w['ann_turnover_pct']:5.0f}%")
    print("\n=== FAMILY 4 V20.0 EMPTY-SLOT T0 ENHANCEMENT ===")
    for r in t0_cash_res:
        print(f"{r['mode']:30s} | {r['etf']:11s} | {r['fee_bps']:2d}bp | col={r['v20_collisions']:2d} | empNAV={r['empty_only_wf_nav']:.4f} | combRatio={r['nav_ratio_vs_v20']:.4f} | dSh={r['delta_sharpe']:+.3f}")
    return out_obj


if __name__ == "__main__":
    run_family4()
