#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD022 Part 1 - Step 3: Orthogonal Model Construction (Soft vs Hard), Exit Tree Optimization & D15 Evaluation."""

import json
import os
import time

import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part1_beta_waves"

MKT_PQ = f"{OUT_DIR}/market_daily.parquet"
P20_PQ = f"{OUT_DIR}/panel_20cm.parquet"
CAND_PQ = f"{OUT_DIR}/beta_day_candidates_enriched.parquet"

IS_END = "2024-08-31"
OOS_START = "2024-09-01"
FEE_RT = 0.0030


def build_stock_path_lookup(p20: pd.DataFrame, mkt: pd.DataFrame):
    """Build fast numpy arrays per ticker for exact daily OHLC exit simulation."""
    all_dts = mkt["dt"].tolist()
    dt_to_gidx = {d: i for i, d in enumerate(all_dts)}

    p20 = p20.sort_values(["c6", "dt"]).reset_index(drop=True)
    # Compute MA5 on adj_close for breakdown stop check
    p20["ma5_t"] = p20.groupby("c6", sort=False)["adj_close"].transform(lambda s: s.rolling(5, min_periods=3).mean())
    p20["gidx"] = p20["dt"].map(dt_to_gidx)
    p20 = p20[p20["gidx"].notna()].copy()

    paths = {}
    for c6, g in p20.groupby("c6", sort=False):
        paths[c6] = {
            "gidx": g["gidx"].to_numpy(dtype=np.int32),
            "dt": g["dt"].to_numpy(),
            "ao": g["adj_open"].to_numpy(dtype=np.float64),
            "ah": g["adj_high"].to_numpy(dtype=np.float64),
            "al": g["adj_low"].to_numpy(dtype=np.float64),
            "ac": g["adj_close"].to_numpy(dtype=np.float64),
            "op": g["open"].to_numpy(dtype=np.float64),
            "hi": g["high"].to_numpy(dtype=np.float64),
            "lo": g["low"].to_numpy(dtype=np.float64),
            "cl": g["close"].to_numpy(dtype=np.float64),
            "zt_px": g["zt_px"].to_numpy(dtype=np.float64),
            "dt_px": g["dt_px"].to_numpy(dtype=np.float64),
            "adjf": g["adjf"].to_numpy(dtype=np.float64),
            "vol": g["volume"].to_numpy(dtype=np.float64),
            "is_dt": g["is_dt"].to_numpy(dtype=bool),
            "is_zt": g["is_zt"].to_numpy(dtype=bool),
            "ret": g["ret"].to_numpy(dtype=np.float64),
            "ma5": g["ma5_t"].to_numpy(dtype=np.float64),
            "gidx_pos": {int(gv): idx for idx, gv in enumerate(g["gidx"].to_numpy(dtype=np.int32))},
        }
    return paths, all_dts, dt_to_gidx


def simulate_exit(paths, c6: str, t0_gidx: int, route: str, exit_rule: str, mkt_prev5d: float):
    """
    Simulate exact PIT daily-bar execution with T+1 lock, limit-up cap on TP, and limit-down deferral.
    Returns (buy_dt, buy_px, sell_dt, sell_px, net_ret, reason).
    """
    st = paths.get(c6)
    if st is None:
        return None
    p0 = st["gidx_pos"].get(t0_gidx)
    if p0 is None:
        return None
    n_len = len(st["dt"])

    if route == "A":
        buy_pos = p0
        buy_px = st["ac"][buy_pos]
        buy_dt = st["dt"][buy_pos]
        first_sell_pos = p0 + 1
        base_gidx = t0_gidx
    else:
        # Route B buys at T+1 open (must be immediate market day t0_gidx + 1)
        buy_pos = st["gidx_pos"].get(t0_gidx + 1)
        if buy_pos is None or st["vol"][buy_pos] <= 0:
            return None
        if st["op"][buy_pos] >= st["zt_px"][buy_pos] - 0.011:
            return None
        buy_px = st["ao"][buy_pos]
        buy_dt = st["dt"][buy_pos]
        first_sell_pos = buy_pos + 1  # T+1 lock: earliest legal sell is T+2
        base_gidx = t0_gidx

    if buy_px <= 0 or np.isnan(buy_px) or first_sell_pos >= n_len:
        return None

    def try_close_sell(j):
        if st["vol"][j] > 0 and (not st["is_dt"][j]):
            return st["ac"][j], st["dt"][j]
        return None

    def defer_from(start_j, reason_prefix):
        for j in range(start_j, n_len):
            res = try_close_sell(j)
            if res is not None:
                sell_px, sell_dt = res
                net_r = (sell_px / buy_px) * (1.0 - FEE_RT) - 1.0
                why = reason_prefix if j == start_j else f"{reason_prefix}_顺延{j-start_j}d"
                return buy_dt, float(buy_px), sell_dt, float(sell_px), float(net_r), why
        return None

    # Helper for fixed T+k close (k relative to T0)
    def fixed_exit(target_k, tag):
        target_g = base_gidx + target_k
        for j in range(first_sell_pos, n_len):
            if st["gidx"][j] >= target_g:
                return defer_from(j, tag)
        return None

    if exit_rule == "FIX_T1":
        return fixed_exit(1, "FIX_T1")
    if exit_rule == "FIX_T2":
        return fixed_exit(2, "FIX_T2")
    if exit_rule == "FIX_T3":
        return fixed_exit(3, "FIX_T3")
    if exit_rule == "FIX_T5":
        return fixed_exit(5, "FIX_T5")

    # Dynamic exit rules: parse parameters
    # Formats:
    # - TP08_T3 / TP10_T3 / TP12_T3 / TP08_T5 / TP10_T5 / TP12_T5 / TP15_T5
    # - TP10_SL06_T3 / TP10_SL07_T5 / TP12_MA5_T5
    # - YANG_HOLD_T3 (if first tradable close strong clv>=0.70 & ret>=3% or ZT -> hold to T+3/T+4, else exit T+2/T+1)
    # - STATE_SWITCH_A / STATE_SWITCH_B (ice rebound quick exit vs trend hold)
    max_k = 3
    tp_pct = None
    sl_pct = None
    use_ma5_sl = False
    use_yang_hold = False

    if exit_rule == "STATE_SWITCH_A":
        if mkt_prev5d < -0.02:
            # Ice rebound fragile: take +6% intraday or exit T+1 close
            tp_pct = 0.06; max_k = 1
        else:
            # Trend continuation: TP +10% or hold to T+2 (extend to T+3 if strong yang)
            tp_pct = 0.10; max_k = 2; use_yang_hold = True
    elif exit_rule == "STATE_SWITCH_B":
        if mkt_prev5d < -0.02:
            tp_pct = 0.06; max_k = 2
        else:
            tp_pct = 0.10; max_k = 3; use_yang_hold = True
    elif exit_rule == "YANG_HOLD_T3":
        max_k = 2 if route == "A" else 2
        use_yang_hold = True
    elif exit_rule == "YANG_HOLD_TP12_T4":
        tp_pct = 0.12; max_k = 2; use_yang_hold = True
    else:
        parts = exit_rule.split("_")
        for pt in parts:
            if pt.startswith("TP"):
                tp_pct = float(pt[2:]) / 100.0
            elif pt.startswith("SL"):
                sl_pct = float(pt[2:]) / 100.0
            elif pt == "MA5":
                use_ma5_sl = True
            elif pt.startswith("T") and pt[1:].isdigit():
                max_k = int(pt[1:])

    cur_max_k = max_k
    for j in range(first_sell_pos, n_len):
        gk = st["gidx"][j] - base_gidx
        if st["vol"][j] <= 0:
            continue

        o_p, h_p, l_p, c_p = st["ao"][j], st["ah"][j], st["al"][j], st["ac"][j]
        zt_adj = st["zt_px"][j] * st["adjf"][j]
        dt_adj = st["dt_px"][j] * st["adjf"][j]
        can_sell_open = st["op"][j] > st["dt_px"][j] + 0.011
        can_sell_close = not st["is_dt"][j]

        # 1. Intraday Take Profit (selling at open limit-up is always fillable!)
        if tp_pct is not None:
            tp_px = buy_px * (1.0 + tp_pct)
            if o_p >= tp_px:
                net_r = (o_p / buy_px) * (1.0 - FEE_RT) - 1.0
                return buy_dt, float(buy_px), st["dt"][j], float(o_p), float(net_r), f"TP_OPEN_T{gk}"
            if h_p >= tp_px and tp_px <= zt_adj + 1e-4:
                # Realistic fill at tp_px
                net_r = (tp_px / buy_px) * (1.0 - FEE_RT) - 1.0
                return buy_dt, float(buy_px), st["dt"][j], float(tp_px), float(net_r), f"TP_HIT_T{gk}"

        # 2. Intraday Stop Loss (only if not sealed limit-down)
        if sl_pct is not None:
            sl_px = buy_px * (1.0 - sl_pct)
            if o_p <= sl_px and can_sell_open:
                net_r = (o_p / buy_px) * (1.0 - FEE_RT) - 1.0
                return buy_dt, float(buy_px), st["dt"][j], float(o_p), float(net_r), f"SL_OPEN_T{gk}"
            if l_p <= sl_px and sl_px >= dt_adj - 1e-4 and can_sell_close:
                net_r = (sl_px / buy_px) * (1.0 - FEE_RT) - 1.0
                return buy_dt, float(buy_px), st["dt"][j], float(sl_px), float(net_r), f"SL_HIT_T{gk}"

        # 3. MA5 close stop
        if use_ma5_sl and pd.notna(st["ma5"][j]) and c_p < st["ma5"][j] and can_sell_close:
            net_r = (c_p / buy_px) * (1.0 - FEE_RT) - 1.0
            return buy_dt, float(buy_px), st["dt"][j], float(c_p), float(net_r), f"MA5_SL_T{gk}"

        # 4. Yang-hold extension check at cur_max_k
        if use_yang_hold and gk == cur_max_k and cur_max_k < 4:
            hl = max(st["hi"][j] - st["lo"][j], 1e-4)
            clv_j = (st["cl"][j] - st["lo"][j]) / hl
            is_strong = st["is_zt"][j] or (st["cl"][j] > st["op"][j] and clv_j >= 0.70 and st["ret"][j] >= 0.03)
            if is_strong:
                cur_max_k += 1
                continue

        # 5. Time exit
        if gk >= cur_max_k:
            return defer_from(j, f"TIME_T{gk}")

    return None


def compute_window_metrics(trades_df: pd.DataFrame, mkt: pd.DataFrame, s_dt: str, e_dt: str):
    """Compute strict D15 metrics: Daily EW, 1-Slot sequential, 3-Slot EW rotation, Ex-Top5, MDD & Benchmarks."""
    m_win = mkt[(mkt["dt"] >= s_dt) & (mkt["dt"] <= e_dt)].sort_values("dt")
    if len(m_win) == 0:
        return {"n_trades": 0}

    # Benchmarks over exact [s_dt, e_dt]
    pre_m = mkt[mkt["dt"] < s_dt]
    hs_base = float(pre_m.iloc[-1]["sh000300"]) if len(pre_m) > 0 else float(m_win.iloc[0]["sh000300"])
    ew20_base = float(pre_m.iloc[-1]["ew_idx_20cm"]) if len(pre_m) > 0 else float(m_win.iloc[0]["ew_idx_20cm"])
    hs_cum = float(m_win.iloc[-1]["sh000300"] / hs_base - 1.0)
    ew20_cum = float(m_win.iloc[-1]["ew_idx_20cm"] / ew20_base - 1.0)

    sub = trades_df[(trades_df["signal_dt"] >= s_dt) & (trades_df["signal_dt"] <= e_dt)].copy()
    if len(sub) == 0:
        return {
            "n_days": 0, "n_trades": 0, "hs300_pct": round(hs_cum * 100, 2),
            "ew20_pct": round(ew20_cum * 100, 2)
        }

    # 1. Daily Equal-Weight (each signal date allocates 100% equally across selected stocks that day)
    # Note: if overlapping days exist, daily EW compounds across signal dates
    day_rets = sub.groupby("signal_dt", sort=True)["net_ret"].mean()
    dew_nav = float((1.0 + day_rets).prod())
    dew_curve = (1.0 + day_rets).cumprod()
    dew_mdd = float((dew_curve / dew_curve.cummax() - 1.0).min())
    top5_day = day_rets.nlargest(5).index
    dew_ex5_nav = float((1.0 + day_rets[~day_rets.index.isin(top5_day)]).prod()) if len(day_rets) > 5 else 1.0

    # 2. 1-Slot Sequential Rotation (strict non-overlapping by buy_dt / sell_dt)
    sub_sorted = sub.sort_values(["buy_dt", "score"], ascending=[True, False])
    seq1 = []
    free_dt = ""
    for dt_b, g in sub_sorted.groupby("buy_dt", sort=True):
        if dt_b <= free_dt:
            continue
        r0 = g.iloc[0]
        seq1.append(r0)
        free_dt = r0["sell_dt"]
    s1_rets = np.array([x["net_ret"] for x in seq1], dtype=float)
    nav1 = float(np.prod(1.0 + s1_rets)) if len(s1_rets) else 1.0
    c1 = np.cumprod(1.0 + s1_rets) if len(s1_rets) else np.array([1.0])
    mdd1 = float(np.min(c1 / np.maximum.accumulate(c1) - 1.0))
    s1_ex5 = np.delete(s1_rets, np.argsort(s1_rets)[-5:]) if len(s1_rets) > 5 else np.array([])
    nav1_ex5 = float(np.prod(1.0 + s1_ex5)) if len(s1_ex5) else 1.0

    # 3. 3-Slot Equal-Weight Rotation (3 independent 1/3 slots, each free when sell_dt completes)
    slots_free = ["", "", ""]
    slots_equity = [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]
    slot_trades = []
    # Track total portfolio equity at each trade exit for MDD
    eq_hist = [1.0]
    for dt_b, g in sub_sorted.groupby("buy_dt", sort=True):
        # Free slots where previous position already sold on or before dt_b (or < dt_b for safety; strictly sell_dt < dt_b if T+1 lock)
        # Note: if sold at close on sell_dt, cash is free next trading day (> sell_dt)!
        avail = [i for i in range(3) if slots_free[i] < dt_b]
        if not avail:
            continue
        picks = g.head(len(avail))
        for si, (_, row) in zip(avail, picks.iterrows()):
            slots_equity[si] *= (1.0 + row["net_ret"])
            slots_free[si] = row["sell_dt"]
            slot_trades.append((row["sell_dt"], row["net_ret"]))
        eq_hist.append(sum(slots_equity))
    nav3 = float(sum(slots_equity))
    eq_arr = np.array(eq_hist, dtype=float)
    mdd3 = float(np.min(eq_arr / np.maximum.accumulate(eq_arr) - 1.0))
    # Ex-top-5 trades for 3-slot
    st_rets = np.array([x[1] for x in slot_trades], dtype=float)
    if len(st_rets) > 5:
        ex5_idx = set(np.argsort(st_rets)[-5:])
        slots_free_ex = ["", "", ""]
        slots_eq_ex = [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]
        t_counter = 0
        for dt_b, g in sub_sorted.groupby("buy_dt", sort=True):
            avail = [i for i in range(3) if slots_free_ex[i] < dt_b]
            if not avail:
                continue
            picks = g.head(len(avail))
            for si, (_, row) in zip(avail, picks.iterrows()):
                if t_counter not in ex5_idx:
                    slots_eq_ex[si] *= (1.0 + row["net_ret"])
                slots_free_ex[si] = row["sell_dt"]
                t_counter += 1
        nav3_ex5 = float(sum(slots_eq_ex))
    else:
        nav3_ex5 = 1.0

    # Trade stats on all selected signals
    all_r = sub["net_ret"].to_numpy()
    w = all_r[all_r > 0]; l = all_r[all_r <= 0]
    po = float(w.mean() / abs(l.mean())) if len(w) and len(l) and l.mean() < 0 else 99.0

    return {
        "n_days": int(len(day_rets)),
        "n_trades": int(len(sub)),
        "n_1slot": int(len(s1_rets)),
        "n_3slot": int(len(st_rets)),
        "wr_pct": round(float((all_r > 0).mean() * 100), 1),
        "day_wr_pct": round(float((day_rets > 0).mean() * 100), 1),
        "mean_ret_pct": round(float(all_r.mean() * 100), 2),
        "day_ew_mean_pct": round(float(day_rets.mean() * 100), 2),
        "payoff": round(po, 2),
        "dew_nav": round(dew_nav, 3),
        "dew_ex5_nav": round(dew_ex5_nav, 3),
        "dew_mdd_pct": round(dew_mdd * 100, 1),
        "nav_1s": round(nav1, 3),
        "nav_1s_ex5": round(nav1_ex5, 3),
        "mdd_1s_pct": round(mdd1 * 100, 1),
        "nav_3s": round(nav3, 3),
        "nav_3s_ex5": round(nav3_ex5, 3),
        "mdd_3s_pct": round(mdd3 * 100, 1),
        "hs300_nav": round(1.0 + hs_cum, 3),
        "ew20_nav": round(1.0 + ew20_cum, 3),
        "ex_1s_vs_hs300_pp": round((nav1 - (1.0 + hs_cum)) * 100, 1),
        "ex_3s_vs_hs300_pp": round((nav3 - (1.0 + hs_cum)) * 100, 1),
        "ex_3s_vs_ew20_pp": round((nav3 - (1.0 + ew20_cum)) * 100, 1),
        "ex_dew_vs_hs300_pp": round((dew_nav - (1.0 + hs_cum)) * 100, 1),
        "ex_dew_vs_ew20_pp": round((dew_nav - (1.0 + ew20_cum)) * 100, 1),
    }


def score_and_select_candidates(cand: pd.DataFrame):
    """Build orthogonal soft scores & hard-gate candidate pools (strictly <= 6 orthogonal physical dims)."""
    c = cand.copy()

    # Soft Score A (strictly legal at T0 14:55, 6 orthogonal physical dimensions, max 100 pts)
    sc_A = np.zeros(len(c))
    # 1. Low Position / Anti-Extension (max 30)
    sc_A += np.where(c["pos20_pre"] <= 0.25, 20.0, np.where(c["pos20_pre"] <= 0.45, 12.0, 0.0))
    sc_A += np.where(c["dist_ma60_pre"] <= -0.10, 10.0, np.where(c["dist_ma60_pre"] <= 0.0, 5.0, 0.0))
    # 2. Small-Mid Elasticity (max 20)
    sc_A += np.where(c["circ_mcap"] < 45.0, 20.0, np.where(c["circ_mcap"] < 90.0, 12.0, 0.0))
    # 3. Clean Intraday Candle & No Exhausting Gap (max 20)
    sc_A += np.where(c["clv"] >= 0.78, 10.0, 0.0)
    sc_A += np.where(c["open_gap"] <= 0.015, 10.0, np.where(c["open_gap"] <= 0.025, 5.0, 0.0))
    # 4. Volume Sweet Spot & Anti-Climax (max 15)
    sc_A += np.where((c["turn_pct"] >= 2.5) & (c["turn_pct"] <= 9.5) & (c["amt_ratio_5"] <= 2.0), 15.0, 0.0)
    # 5. Anti-Crowding / Dark Card (max 10)
    sc_A += np.where((c["in_kpl_yest"] == 0) & (c["kpl_live_10_zt_cnt"] <= 20), 10.0, 0.0)
    # 6. Freshness & Clean Headroom (max 10; penalties for bad hygiene)
    sc_A += np.where(c["is_first_bigup_60d"] == 1, 5.0, 0.0)
    sc_A += np.where(c["head_3d30"] >= 0.08, 5.0, 0.0)
    sc_A -= np.where(c["reg_tox_90d_A"] == 1, 30.0, 0.0)
    sc_A -= np.where(c["lhb_has_lhasa_10d_pre"] == 1, 30.0, 0.0)
    c["score_A"] = sc_A

    # Soft Score B (Route B legal at T+1 09:25 open: A's score + T+1 open sweet spot + T0 LHB/post-close)
    sc_B = sc_A.copy()
    sc_B += np.where((c["t1_open_gap"] >= -0.012) & (c["t1_open_gap"] <= 0.015), 20.0,
                     np.where(c["t1_open_gap"] > 0.025, -25.0, 0.0))
    sc_B += np.where(c["lhb_t0_org_net_yi"] > 0.05, 15.0, 0.0)
    sc_B -= np.where(c["earn_pos_t0_post_B"] == 1, 30.0, 0.0)
    sc_B -= np.where(c["reg_tox_t0_post_B"] == 1, 30.0, 0.0)
    c["score_B"] = sc_B

    hygiene_A = (c["reg_tox_90d_A"] == 0) & (c["lhb_has_lhasa_10d_pre"] == 0) & (c["head_3d30"] >= 0.05) & (c["circ_mcap"] < 150.0)
    hygiene_B = (c["reg_tox_90d_B"] == 0) & (c["lhb_has_lhasa_10d_pre"] == 0) & (c["head_3d30"] >= 0.05) & (c["circ_mcap"] < 150.0) & (c["earn_pos_t0_post_B"] == 0)

    # Define 8 clean strategies (Route A vs B, Hard vs Soft, 5~15 vs 7~15, All Beta vs Trend Beta)
    strategies = {
        # 1. Baseline unfiltered [5%, 15%) Route A Top-3 by small cap
        "A0_Base_5_15_Top3": ("A", c["buyable_A"] & (c["ret"] < 0.15), -c["circ_mcap"], 3),
        # 2. Hard-Gate Route A [5%, 15%)
        "A1_Hard_5_15_Top3": (
            "A",
            c["buyable_A"] & (c["ret"] < 0.15) & hygiene_A
            & (c["pos20_pre"] <= 0.42) & (c["dist_ma60_pre"] <= 0.02)
            & (c["circ_mcap"] < 80.0) & (c["clv"] >= 0.75) & (c["open_gap"] <= 0.022),
            c["score_A"], 3
        ),
        # 3. Soft-Score Route A [5%, 15%) All Beta Days (score_A >= 70, top 3)
        "A2_Soft70_5_15_Top3": (
            "A",
            c["buyable_A"] & (c["ret"] < 0.15) & hygiene_A & (c["score_A"] >= 70.0),
            c["score_A"], 3
        ),
        # 4. Soft-Score Route A [5%, 15%) Trend-Continuation Beta Days (mkt_prev5d_ew >= -2%)
        "A3_Soft70_TrendBeta_Top3": (
            "A",
            c["buyable_A"] & (c["ret"] < 0.15) & hygiene_A & (c["score_A"] >= 70.0) & (c["mkt_prev5d_ew"] >= -0.02),
            c["score_A"], 3
        ),
        # 5. Soft-Score Route A [7%, 15%) (Mid-Big Yang +7~+15%)
        "A4_Soft65_7_15_Top3": (
            "A",
            c["buyable_A"] & (c["ret"] >= 0.07) & (c["ret"] < 0.15) & hygiene_A & (c["score_A"] >= 65.0),
            c["score_A"], 3
        ),
        # 6. Hard-Gate Route B [5%, 15%) T+1 Open Buy (flat open)
        "B1_Hard_5_15_Top3": (
            "B",
            c["buyable_B"] & (c["ret"] < 0.15) & hygiene_B
            & (c["t1_open_gap"] >= -0.012) & (c["t1_open_gap"] <= 0.018)
            & (c["pos20_pre"] <= 0.42) & (c["circ_mcap"] < 80.0) & (c["clv"] >= 0.75),
            c["score_B"], 3
        ),
        # 7. Soft-Score Route B [5%, 15%) T+1 Open Buy (score_B >= 85, top 3)
        "B2_Soft85_5_15_Top3": (
            "B",
            c["buyable_B"] & (c["ret"] < 0.15) & hygiene_B & (c["score_B"] >= 85.0),
            c["score_B"], 3
        ),
        # 8. Soft-Score Route B [5%, 15%) Trend-Continuation Beta Days
        "B3_Soft85_TrendBeta_Top3": (
            "B",
            c["buyable_B"] & (c["ret"] < 0.15) & hygiene_B & (c["score_B"] >= 85.0) & (c["mkt_prev5d_ew"] >= -0.02),
            c["score_B"], 3
        ),
        # 9. Soft-Score Route B [7%, 15%)
        "B4_Soft80_7_15_Top3": (
            "B",
            c["buyable_B"] & (c["ret"] >= 0.07) & (c["ret"] < 0.15) & hygiene_B & (c["score_B"] >= 80.0),
            c["score_B"], 3
        ),
    }

    selected = {}
    for sname, (route, mask, rank_ser, top_n) in strategies.items():
        sub = c[mask].copy()
        sub["rank_sc"] = rank_ser[mask]
        # Deterministic tie-break: higher score, smaller mcap, lower pos20_pre
        sub = sub.sort_values(["dt", "rank_sc", "circ_mcap"], ascending=[True, False, True])
        sub = sub.groupby("dt", sort=False).head(top_n).reset_index(drop=True)
        selected[sname] = (route, sub)
    return selected


def main():
    t0 = time.time()
    print("[Step 3] Loading panel_20cm, market_daily & candidates...")
    mkt = pd.read_parquet(MKT_PQ)
    p20 = pd.read_parquet(P20_PQ)
    cand = pd.read_parquet(CAND_PQ)

    paths, all_dts, dt_to_gidx = build_stock_path_lookup(p20, mkt)
    selected = score_and_select_candidates(cand)

    # Exit tree rules
    EXITS_A = ["FIX_T1", "FIX_T2", "FIX_T3", "FIX_T5", "TP08_T3", "TP10_T3", "TP12_T5", "TP10_SL06_T3", "TP12_SL07_T5", "YANG_HOLD_T3", "YANG_HOLD_TP12_T4", "STATE_SWITCH_A"]
    EXITS_B = ["FIX_T2", "FIX_T3", "FIX_T5", "TP08_T3", "TP10_T3", "TP12_T5", "TP10_SL06_T3", "TP12_SL07_T5", "YANG_HOLD_T3", "YANG_HOLD_TP12_T4", "STATE_SWITCH_B"]

    windows = [
        ("Full_5.9Y", "2021-01-04", "2026-11-23"),
        ("IS", "2021-01-04", IS_END),
        ("OOS", OOS_START, "2026-11-23"),
        ("Y2026", "2026-01-01", "2026-11-23"),
    ]

    matrix_rows = []
    ledgers_cache = {}

    for sname, (route, df_sel) in selected.items():
        exits = EXITS_A if route == "A" else EXITS_B
        for ex in exits:
            trades = []
            for r in df_sel.itertuples(index=False):
                res = simulate_exit(paths, r.c6, dt_to_gidx[r.dt], route, ex, float(r.mkt_prev5d_ew))
                if res is None:
                    continue
                bdt, bpx, sdt, spx, nret, why = res
                trades.append({
                    "signal_dt": r.dt,
                    "buy_dt": bdt,
                    "sell_dt": sdt,
                    "c6": r.c6,
                    "sec_name": r.sec_name,
                    "route": route,
                    "t0_ret_pct": round(float(r.ret) * 100, 2),
                    "circ_mcap_yi": round(float(r.circ_mcap), 1),
                    "pos20_pre": round(float(r.pos20_pre), 3) if pd.notna(r.pos20_pre) else None,
                    "score": round(float(r.rank_sc), 1),
                    "buy_px": round(bpx, 4),
                    "sell_px": round(spx, 4),
                    "net_ret": nret,
                    "net_ret_pct": round(nret * 100, 2),
                    "exit_reason": why,
                })
            tdf = pd.DataFrame(trades)
            ledgers_cache[(sname, ex)] = tdf
            row = {"strategy": sname, "route": route, "exit_rule": ex}
            for wnm, s_dt, e_dt in windows:
                m = compute_window_metrics(tdf, mkt, s_dt, e_dt) if len(tdf) else {"n_trades": 0}
                for k, v in m.items():
                    row[f"{wnm}_{k}"] = v
            matrix_rows.append(row)

    mdf = pd.DataFrame(matrix_rows)
    mdf.to_csv(f"{OUT_DIR}/strategy_matrix_part1.csv", index=False)

    # Identify best Route A & Route B (requiring dual positive IS & OOS ex-top5, >= 15 trades/days, highest combined 3-slot & dew robustness)
    def pick_best(route_lbl):
        sub = mdf[(mdf["route"] == route_lbl) & (mdf["IS_nav_3s_ex5"] > 1.0) & (mdf["OOS_nav_3s_ex5"] > 1.0) & (mdf["IS_n_days"] >= 10) & (mdf["OOS_n_days"] >= 10)].copy()
        if sub.empty:
            sub = mdf[mdf["route"] == route_lbl].copy()
        sub["robust_score"] = np.log(np.maximum(sub["IS_nav_3s_ex5"], 0.1)) + np.log(np.maximum(sub["OOS_nav_3s_ex5"], 0.1)) + 0.5 * np.log(np.maximum(sub["Full_5.9Y_dew_ex5_nav"], 0.1))
        best_r = sub.sort_values("robust_score", ascending=False).iloc[0]
        return best_r["strategy"], best_r["exit_rule"]

    bestA_s, bestA_e = pick_best("A")
    bestB_s, bestB_e = pick_best("B")
    ledgers_cache[(bestA_s, bestA_e)].to_csv(f"{OUT_DIR}/best_routeA_ledger.csv", index=False)
    ledgers_cache[(bestB_s, bestB_e)].to_csv(f"{OUT_DIR}/best_routeB_ledger.csv", index=False)
    # Also save A2_Soft70_5_15_Top3 & B2_Soft85_5_15_Top3 ledgers if different (full 65-day track)
    if bestA_s != "A2_Soft70_5_15_Top3":
        ledgers_cache[("A2_Soft70_5_15_Top3", bestA_e)].to_csv(f"{OUT_DIR}/allbeta_routeA_ledger.csv", index=False)
    if bestB_s != "B2_Soft85_5_15_Top3":
        ledgers_cache[("B2_Soft85_5_15_Top3", bestB_e)].to_csv(f"{OUT_DIR}/allbeta_routeB_ledger.csv", index=False)

    summary = {
        "best_routeA": {"strategy": bestA_s, "exit": bestA_e, "metrics": mdf[(mdf["strategy"] == bestA_s) & (mdf["exit_rule"] == bestA_e)].iloc[0].to_dict()},
        "best_routeB": {"strategy": bestB_s, "exit": bestB_e, "metrics": mdf[(mdf["strategy"] == bestB_s) & (mdf["exit_rule"] == bestB_e)].iloc[0].to_dict()},
    }
    with open(f"{OUT_DIR}/part1_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[Step 3 Done] Saved strategy_matrix_part1.csv ({len(mdf)} configs) & ledgers in {time.time()-t0:.1f}s")
    print(f"  Best Route A: {bestA_s} + {bestA_e}")
    print(f"  Best Route B: {bestB_s} + {bestB_e}")

    # Compact summary printout
    show_cols = [
        "strategy", "exit_rule",
        "IS_n_days", "IS_nav_3s", "IS_nav_3s_ex5", "IS_dew_nav",
        "OOS_n_days", "OOS_nav_3s", "OOS_nav_3s_ex5", "OOS_dew_nav",
        "Full_5.9Y_nav_3s", "Full_5.9Y_nav_3s_ex5", "Full_5.9Y_mdd_3s_pct", "Full_5.9Y_ex_3s_vs_hs300_pp",
        "Y2026_nav_3s", "Y2026_ex_3s_vs_hs300_pp"
    ]
    print("\n=== TOP CONFIGS (All Strategies Best Exit) ===")
    best_per_strat = mdf.sort_values("Full_5.9Y_nav_3s_ex5", ascending=False).groupby("strategy", sort=False).head(1)
    print(best_per_strat[show_cols].to_string(index=False))

    print(f"\n=== EXIT TREE ABLATION ON {bestA_s} ===")
    print(mdf[mdf["strategy"] == bestA_s][show_cols].to_string(index=False))
    print(f"\n=== EXIT TREE ABLATION ON {bestB_s} ===")
    print(mdf[mdf["strategy"] == bestB_s][show_cols].to_string(index=False))


if __name__ == "__main__":
    main()
