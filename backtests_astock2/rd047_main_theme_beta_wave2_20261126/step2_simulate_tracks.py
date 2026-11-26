#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD047 Step 2: Simulate Track A (Main-Theme Trend Heavyweights) & Track B (Dynamic Theme-Switching Wave-2)
- Pure causal signals at day t close -> T+1 open execution (skip one-word ZT / suspended, defer one-word DT exit).
- Exact slot-cash accounting (zero hidden rebalance friction, zero leverage, exact daily MTM).
- Tests Cash vs 511010 Bond ETF parking, 30bps vs 50bps friction, Dynamic vs Static SW3 ablations,
  and full low-DOF parameter plateau grids.
- Zero yfinance (D12). Peak RAM < 1.5 GB.
"""
import gc
import json
import os
import sys
import time

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

RD047_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd047_main_theme_beta_wave2_20261126"
if RD047_DIR not in sys.path:
    sys.path.insert(0, RD047_DIR)

import _rd047_common as cm


def load_sim_context(tag: str = "full") -> dict:
    meta = json.load(open(f"{cm.CACHE_DIR}/meta_{tag}.json", encoding="utf-8"))
    tn = json.load(open(f"{cm.CACHE_DIR}/theme_names_{tag}.json", encoding="utf-8"))
    px = np.load(f"{cm.CACHE_DIR}/panel_px_{tag}.npz")
    tc = np.load(f"{cm.CACHE_DIR}/panel_tech_{tag}.npz")
    ts = np.load(f"{cm.CACHE_DIR}/theme_scores_{tag}.npz")

    cal_dts = meta["cal_dts"]
    stocks = meta["stocks"]
    all_theme_names = tn["all_theme_names"]
    N_D, N_S = len(cal_dts), len(stocks)

    # Active tradeable open check on day d+1
    is_20cm = px["is_20cm"]
    open_pct = px["open_pct"]
    lim_up_open = np.where(is_20cm, 0.192, 0.094)
    lim_dn_open = np.where(is_20cm, -0.192, -0.094)
    valid_px = px["valid_px"]
    is_st = px["is_st"]

    can_buy_open = valid_px & (~is_st) & (~px["is_yizi_zt"]) & (np.nan_to_num(open_pct, nan=0.0) < lim_up_open)
    can_sell_open = valid_px & (~px["is_yizi_dt"]) & (np.nan_to_num(open_pct, nan=0.0) > lim_dn_open)

    # Precompute SW3 -> theme_id fast check & causal theme overlap for deduplicating Top-1/Top-2 themes
    return {
        "cal_dts": cal_dts,
        "stocks": stocks,
        "N_D": N_D,
        "N_S": N_S,
        "all_theme_names": all_theme_names,
        "n_sw": int(tn["n_sw"]),
        "adj_close": px["adj_close"],
        "adj_open": px["adj_open"],
        "ret_1d": px["ret_1d"],
        "amount_yi": px["amount_yi"],
        "amt20": px["amt20"],
        "mcap_yi_t1": px["mcap_yi_t1"],
        "list_age": px["list_age"],
        "is_st": is_st,
        "is_zt": px["is_zt"],
        "streak": px["streak"],
        "valid_px": valid_px,
        "can_buy_open": can_buy_open,
        "can_sell_open": can_sell_open,
        "ma5": tc["ma5"],
        "ma10": tc["ma10"],
        "ma20": tc["ma20"],
        "hi20": tc["hi20"],
        "ret_3d": tc["ret_3d"],
        "ret_5d": tc["ret_5d"],
        "ret_20d": tc["ret_20d"],
        "max_stk_25d": tc["max_stk_25d"],
        "max_r20_25d": tc["max_r20_25d"],
        "sw3_mat": tc["sw3_mat"],
        "th_active": ts["th_active"],
        "total_score": ts["total_score"],
        "stk_dyn_score": ts["stk_dyn_score"],
        "stk_best_tid": ts["stk_best_tid"],
        "stk_sw3_score": ts["stk_sw3_score"],
        "stk_switched": ts["stk_switched"],
    }


def precompute_track_a_cands(
    ctx: dict,
    kpl_df_path: str,
    thr_list: tuple = (70.0, 75.0, 80.0, 85.0),
) -> dict:
    """
    Precompute daily active theme rankings and per-stock causal tags for Track A
    so grid runs in milliseconds!
    """
    N_D, N_S = ctx["N_D"], ctx["N_S"]
    n_sw = ctx["n_sw"]
    kpl_df = pd.read_parquet(kpl_df_path)
    kpl_by_day_s: dict[int, list[tuple[int, int]]] = {}
    for r in kpl_df.itertuples(index=False):
        kpl_by_day_s.setdefault(int(r.di), []).append((int(r.si), int(r.pid)))

    # Maintain rolling 20d stock->set(tid) causally
    stk_kpl_20d: list[dict[int, int]] = [dict() for _ in range(N_S)]
    th_active = ctx["th_active"]
    tot_sc = ctx["total_score"]
    sw3_mat = ctx["sw3_mat"]

    # For each day d: sorted list of (tid, score) where score >= 65.0
    day_top_themes: list[list[tuple[int, float]]] = [[] for _ in range(N_D)]
    # Also map (d, tid) -> set of member si in [d-19, d] (for KPL) or sw3_mat == tid (for SW3)
    # To deduplicate overlapping KPL tags (e.g. MR/AR/VR), store member bitsets or sets for top 10 themes >= 65
    day_theme_members: list[dict[int, np.ndarray]] = [dict() for _ in range(N_D)]

    # Fast incremental KPL plate -> {si: last_di}
    plate_20d: dict[int, dict[int, int]] = {}

    for d in range(N_D):
        for si_v, pid_v in kpl_by_day_s.get(d, []):
            plate_20d.setdefault(pid_v, {})[si_v] = d
            stk_kpl_20d[si_v][pid_v] = d

        min_d = d - 19
        # Prune stale
        for pid_v in list(plate_20d.keys()):
            pd_m = plate_20d[pid_v]
            for s_k in [s_k for s_k, ld in pd_m.items() if ld < min_d]:
                del pd_m[s_k]
            if not pd_m:
                del plate_20d[pid_v]

        act_ids = np.flatnonzero(th_active[d] & (tot_sc[d] >= 65.0))
        if len(act_ids) == 0:
            continue
        order = act_ids[np.argsort(-tot_sc[d, act_ids])]
        top_list = []
        sw3_d = sw3_mat[d]
        for tid in order[:15]:
            tid_i = int(tid)
            sc_v = float(tot_sc[d, tid_i])
            top_list.append((tid_i, sc_v))
            if tid_i < n_sw:
                mems = np.flatnonzero(sw3_d == tid_i)
            else:
                pid_v = tid_i - n_sw
                mems = np.array(sorted(plate_20d.get(pid_v, {}).keys()), dtype=np.int32)
            day_theme_members[d][tid_i] = mems
        day_top_themes[d] = top_list

    return {
        "day_top_themes": day_top_themes,
        "day_theme_members": day_theme_members,
    }


def simulate_portfolio(
    ctx: dict,
    cands_by_day: list[list[tuple[int, float, int, float]]],  # list per signal day d: [(si, rank_score, theme_id, theme_score)]
    exit_mode: str,             # 'ma10', 'ma15', 'ma20', 'ma5', 'broken_ma5', 'trail12_ma10'
    trail_dd: float | None,     # e.g. 0.10, 0.15, or None
    fade_thr: float | None,     # e.g. 50.0, 55.0 (2 consecutive days < fade_thr) or None
    fade_use_static: bool,
    n_slots: int,
    fee_rt: float,
    bond_dr: np.ndarray | None,
    start_eval_idx: int = 60,   # start after 60d warmup (2021-04-06)
    end_idx: int | None = None,
) -> dict:
    """
    Exact daily slot-cash portfolio simulator (signals at day d close -> execute at d+1 open).
    """
    N_D = ctx["N_D"] if end_idx is None else min(ctx["N_D"], end_idx + 1)
    cal_dts = ctx["cal_dts"]
    stocks = ctx["stocks"]
    th_names = ctx["all_theme_names"]

    adj_c = ctx["adj_close"]
    adj_o = ctx["adj_open"]
    valid_px = ctx["valid_px"]
    can_buy = ctx["can_buy_open"]
    can_sell = ctx["can_sell_open"]
    is_zt = ctx["is_zt"]
    ma5 = ctx["ma5"]
    ma10 = ctx["ma10"]
    ma20 = ctx["ma20"]
    # For ma15 compute on the fly? Better: approximate or compute ma15 quickly once if needed
    # Wait: compute ma15 as exact 15d causal mean only if exit_mode == 'ma15' (or use ctx.setdefault)
    if exit_mode == "ma15" and "ma15" not in ctx:
        # Compute causal ma15 from adj_close ff
        ac_ff = adj_c.copy()
        for d in range(1, ctx["N_D"]):
            m = ~np.isfinite(ac_ff[d])
            ac_ff[d, m] = ac_ff[d - 1, m]
        val = np.isfinite(ac_ff)
        cs_v = np.vstack([np.zeros((1, ctx["N_S"]), dtype=np.float64), np.cumsum(np.where(val, ac_ff, 0.0), axis=0)])
        cs_c = np.vstack([np.zeros((1, ctx["N_S"]), dtype=np.int32), np.cumsum(val.astype(np.int32), axis=0)])
        m15 = np.full((ctx["N_D"], ctx["N_S"]), np.nan, dtype=np.float32)
        for d in range(ctx["N_D"]):
            lo = max(0, d - 14)
            cnt = cs_c[d + 1] - cs_c[lo]
            ok = cnt >= max(1, min(7, d + 1))
            m15[d, ok] = ((cs_v[d + 1, ok] - cs_v[lo, ok]) / cnt[ok]).astype(np.float32)
        ctx["ma15"] = m15

    ma_exit_arr = {
        "ma5": ma5,
        "ma10": ma10,
        "ma15": ctx.get("ma15", ma10),
        "ma20": ma20,
        "broken_ma5": ma5,
        "trail12_ma10": ma10,
        "hold20": ma20,
        "hold10": ma10,
    }[exit_mode]

    stk_th_sc = ctx["stk_sw3_score"] if fade_use_static else ctx["stk_dyn_score"]

    fee_buy = fee_rt * 0.5
    fee_sell_mult = (1.0 - fee_rt) / (1.0 - fee_buy)
    etf_fee_half = 0.00025

    cash = 1.0
    # Active positions: list of dicts
    positions: list[dict] = []
    pending_sells: set[int] = set()  # stock indices scheduled to sell at today's open
    dr = np.zeros(N_D, dtype=np.float64)
    act_mask = np.zeros(N_D, dtype=bool)
    to_daily = np.zeros(N_D, dtype=np.float64)
    closed_trades = []
    prev_nav = 1.0
    prev_bond_w = 0.0

    for d in range(N_D):
        # 1. At day d open: execute pending sells (if tradable & not limit-down), then pending buys from d-1 close
        sell_turnover = 0.0
        buy_turnover = 0.0

        still_held = []
        for pos in positions:
            si = pos["si"]
            if si in pending_sells and can_sell[d, si]:
                # Execute sell at d open
                op_px = float(adj_o[d, si])
                mult_seg = op_px / pos["last_px"]
                pos_val_gross = pos["val"] * mult_seg
                cash_in = pos_val_gross * fee_sell_mult
                sell_turnover += cash_in
                cash += cash_in
                net_ret = (op_px / pos["entry_px"]) * (1.0 - fee_rt) - 1.0
                closed_trades.append({
                    "code": stocks[si],
                    "buy_date": cal_dts[pos["buy_di"]],
                    "exit_date": cal_dts[d],
                    "hold_days": d - pos["buy_di"],
                    "net_ret": round(float(net_ret), 6),
                    "entry_theme": th_names[pos["tid"]] if pos["tid"] >= 0 else "UNK",
                    "entry_theme_score": round(float(pos["th_sc"]), 2),
                    "entry_dyn_score": round(float(ctx["stk_dyn_score"][pos["sig_di"], si]), 2),
                    "entry_sw3_score": round(float(ctx["stk_sw3_score"][pos["sig_di"], si]), 2),
                    "switched": bool(ctx["stk_switched"][pos["sig_di"], si]),
                    "exit_reason": pos["exit_reason"],
                    "slots_cap": n_slots,
                })
                pending_sells.discard(si)
            else:
                still_held.append(pos)
        positions = still_held

        # Execute buys from d-1 signal cands if free slots > 0 and d >= start_eval_idx
        if d >= start_eval_idx and len(positions) < n_slots:
            held_sis = {p["si"] for p in positions}
            cands = cands_by_day[d - 1]
            if cands:
                # Target size per slot based on open-available nav
                open_nav = cash + sum(p["val"] for p in positions)
                for si, rk_sc, tid, th_sc in cands:
                    if len(positions) >= n_slots:
                        break
                    if si in held_sis or (not can_buy[d, si]):
                        continue
                    alloc = min(cash, open_nav / float(n_slots))
                    if alloc < 1e-4:
                        break
                    cash -= alloc
                    buy_turnover += alloc
                    entry_px = float(adj_o[d, si])
                    val_after_fee = alloc * (1.0 - fee_buy)
                    positions.append({
                        "si": si,
                        "buy_di": d,
                        "sig_di": d - 1,
                        "entry_px": entry_px,
                        "last_px": entry_px,
                        "peak_px": entry_px,
                        "val": val_after_fee,
                        "tid": tid,
                        "th_sc": th_sc,
                        "broken_zt": not bool(is_zt[d, si]),
                        "fade_cnt": 0,
                        "exit_reason": "",
                    })
                    held_sis.add(si)

        # 2. Intraday/Close MTM update on day d
        if len(positions) > 0:
            act_mask[d] = True
        for pos in positions:
            si = pos["si"]
            if valid_px[d, si]:
                cl_px = float(adj_c[d, si])
                pos["val"] *= (cl_px / pos["last_px"])
                pos["last_px"] = cl_px
                if cl_px > pos["peak_px"]:
                    pos["peak_px"] = cl_px
                if not bool(is_zt[d, si]):
                    pos["broken_zt"] = True

        # Optional bond ETF return on idle cash after start_eval_idx
        bond_w = 0.0
        bond_pnl = 0.0
        if bond_dr is not None and d >= start_eval_idx and cash > 1e-6:
            # Park idle cash in 511010 Bond ETF
            bond_w = cash / max(prev_nav, 1e-9)
            bond_pnl = cash * float(bond_dr[d])
            cash += bond_pnl
        etf_cost = abs(bond_w - prev_bond_w) * prev_nav * etf_fee_half if bond_dr is not None else 0.0
        cash = max(0.0, cash - etf_cost)
        prev_bond_w = bond_w

        nav_close = cash + sum(p["val"] for p in positions)
        dr[d] = nav_close / max(prev_nav, 1e-12) - 1.0
        to_daily[d] = 0.5 * (buy_turnover + sell_turnover) / max(prev_nav, 1e-12)
        prev_nav = nav_close

        # 3. At day d close: evaluate exit signals for open positions (to execute at d+1 open!)
        if d < N_D - 1:
            for pos in positions:
                si = pos["si"]
                if si in pending_sells:
                    continue
                if not valid_px[d, si]:
                    continue
                cl_px = float(adj_c[d, si])
                reason = ""
                # Check MA or fixed-horizon exit
                if exit_mode == "hold20":
                    if (d - pos["buy_di"]) >= 20:
                        reason = "hold20"
                elif exit_mode == "hold10":
                    if (d - pos["buy_di"]) >= 10:
                        reason = "hold10"
                else:
                    ma_v = float(ma_exit_arr[d, si]) if np.isfinite(ma_exit_arr[d, si]) else 0.0
                    if exit_mode == "broken_ma5":
                        if pos["broken_zt"] and ma_v > 0 and cl_px < ma_v:
                            reason = "broken_ma5"
                    elif ma_v > 0 and cl_px < ma_v:
                        reason = exit_mode

                # Check trailing drawdown
                if (not reason) and (trail_dd is not None):
                    if cl_px < pos["peak_px"] * (1.0 - trail_dd):
                        reason = f"trail_{int(trail_dd*100)}"

                # Check theme fade (2 straight days below fade_thr)
                if (not reason) and (fade_thr is not None):
                    if float(stk_th_sc[d, si]) < fade_thr:
                        pos["fade_cnt"] += 1
                    else:
                        pos["fade_cnt"] = 0
                    if pos["fade_cnt"] >= 2:
                        reason = f"fade_{int(fade_thr)}"

                if reason:
                    pos["exit_reason"] = reason
                    pending_sells.add(si)

    # Record open positions still held at end_idx as open_trades info (not closed, excluded from closed_trades stats)
    return {
        "dr": dr,
        "act_mask": act_mask,
        "to_daily": to_daily,
        "closed_trades": pd.DataFrame(closed_trades),
        "n_open_end": len(positions),
    }


def generate_track_a_cands(
    ctx: dict,
    pre_a: dict,
    thr_main: float = 75.0,
    confirm_days: int = 2,
    n_themes: int = 2,
    min_amt_yi: float = 3.0,
    pick_style: str = "leader",   # 'leader' | 'pullback'
    static_sw3_only: bool = False,
) -> list[list[tuple[int, float, int, float]]]:
    N_D, N_S = ctx["N_D"], ctx["N_S"]
    n_sw = ctx["n_sw"]
    U = ctx["valid_px"] & (~ctx["is_st"]) & (ctx["list_age"] >= 60)
    liq_ok = (ctx["amt20"] >= min_amt_yi) & (ctx["amount_yi"] >= min_amt_yi * 0.8)
    adj_c = ctx["adj_close"]
    ma5 = ctx["ma5"]
    ma10 = ctx["ma10"]
    ma20 = ctx["ma20"]
    ret_1d = ctx["ret_1d"]
    ret_5d = ctx["ret_5d"]
    ret_20d = ctx["ret_20d"]
    amt = ctx["amount_yi"]
    th_sc = ctx["total_score"]
    th_act = ctx["th_active"]

    day_top = pre_a["day_top_themes"]
    day_mems = pre_a["day_theme_members"]
    sw3_mat = ctx["sw3_mat"]
    out = [[] for _ in range(N_D)]

    for d in range(25, N_D):
        top_list = day_top[d]
        if not top_list:
            continue

        # Filter themes meeting thr_main and confirm_days
        # Deduplicate overlapping KPL themes (>70% stock overlap with already chosen theme)
        chosen_themes: list[tuple[int, float]] = []
        chosen_mem_sets: list[set[int]] = []

        # If static_sw3_only, restrict strictly to SW3/CSRC themes (tid < n_sw)
        for tid, sc_v in top_list:
            if static_sw3_only and tid >= n_sw:
                continue
            if sc_v < thr_main:
                break
            # Check confirm_days: in [d - confirm_days + 1 .. d], theme must be active & >= thr_main - 3 (and today >= thr_main)
            if confirm_days >= 2:
                ok_conf = True
                for dd in range(max(0, d - confirm_days + 1), d):
                    if (not th_act[dd, tid]) or float(th_sc[dd, tid]) < (thr_main - 3.0):
                        ok_conf = False
                        break
                if not ok_conf:
                    continue

            if static_sw3_only:
                mems = set(int(x) for x in np.flatnonzero(sw3_mat[d] == tid))
            else:
                mems = set(int(x) for x in day_mems[d].get(tid, []))
            if len(mems) < 4:
                continue

            # Overlap check against already selected themes
            is_dup = False
            for prev_m in chosen_mem_sets:
                inter = len(mems & prev_m)
                if inter / max(1, min(len(mems), len(prev_m))) > 0.65:
                    is_dup = True
                    break
            if is_dup:
                continue

            chosen_themes.append((tid, sc_v))
            chosen_mem_sets.append(mems)
            if len(chosen_themes) >= n_themes:
                break

        if not chosen_themes:
            continue

        # Collect candidates across chosen themes, keeping highest score if stock appears in both
        best_for_si: dict[int, tuple[float, int, float]] = {}
        for rk_th, (tid, t_sc) in enumerate(chosen_themes):
            mems = sorted(chosen_mem_sets[rk_th])
            for si in mems:
                if not (U[d, si] and liq_ok[d, si]):
                    continue
                if not (np.isfinite(ma10[d, si]) and np.isfinite(ma20[d, si]) and np.isfinite(ret_20d[d, si]) and np.isfinite(ret_5d[d, si])):
                    continue
                cl = float(adj_c[d, si])
                m10 = float(ma10[d, si])
                m20 = float(ma20[d, si])
                m5 = float(ma5[d, si]) if np.isfinite(ma5[d, si]) else m10
                r20 = float(ret_20d[d, si])
                r5 = float(ret_5d[d, si])
                r1 = float(ret_1d[d, si]) if np.isfinite(ret_1d[d, si]) else 0.0

                if cl <= m20 or r20 <= 0.03:
                    continue

                if pick_style == "leader":
                    # Trend leader: above MA10 & MA20, positive 20d trend, avoid parabolic exhaustion (>35% in 5d)
                    if cl <= m10 or r5 > 0.35 or r5 < -0.05:
                        continue
                    # Rank score: theme priority + 20d trend + turnover capacity (in log scale)
                    rk = t_sc * 1.5 + min(r20 * 100.0, 50.0) * 0.6 + min(np.log1p(float(amt[d, si])) * 8.0, 35.0)
                elif pick_style == "inst_core":
                    # Non-chasing institutional core: top liquidity/amt20 inside main theme, controlled 5d/20d extension
                    if r5 > 0.15 or r20 > 0.35:
                        continue
                    rk = t_sc * 1.5 + min(np.log1p(float(ctx["amt20"][d, si])) * 15.0, 50.0)
                else:
                    # Pullback & re-start: pulled back near MA5/MA10 recently and turning up today
                    near_ma = any(
                        np.isfinite(ma10[dd, si]) and abs(float(adj_c[dd, si]) / float(ma10[dd, si]) - 1.0) <= 0.04
                        for dd in range(max(0, d - 3), d + 1)
                    )
                    if not (near_ma and r1 > 0.005 and cl >= m5 and r20 >= 0.08):
                        continue
                    rk = t_sc * 1.5 + min(r20 * 100.0, 50.0) * 0.4 + min(np.log1p(float(amt[d, si])) * 8.0, 35.0)

                prev = best_for_si.get(si)
                if prev is None or rk > prev[0]:
                    best_for_si[si] = (rk, tid, t_sc)

        if best_for_si:
            c_list = [(si, v[0], v[1], v[2]) for si, v in best_for_si.items()]
            c_list.sort(key=lambda x: (-x[1], x[0]))
            out[d] = c_list[:15]
    return out


def generate_track_b_cands(
    ctx: dict,
    thr_w2: float = 75.0,
    min_amt_yi: float = 3.0,
    theme_mode: str = "dyn_high",   # 'dyn_high', 'dyn_switch_or_up', 'static_sw3', 'weak_ctrl'
) -> list[list[tuple[int, float, int, float]]]:
    """
    Track B: High-Beta Dynamic Theme-Switching Wave-2 Capture.
    Wave-1: >=3 consecutive ZTs or >=40% 20d surge in [d-24, d-3].
    Pullback/Consolidation: did not collapse below 0.97*MA20, pulled back from 20d high (>=4% off high recently or not in 4+ board blowoff).
    Re-ignition at d: ret_1d >= +3% (or ZT), volume >= 1.15 * amt20, close >= MA10.
    """
    N_D, N_S = ctx["N_D"], ctx["N_S"]
    U = ctx["valid_px"] & (~ctx["is_st"]) & (ctx["list_age"] >= 60)
    liq_ok = (ctx["amt20"] >= min_amt_yi) | (ctx["amount_yi"] >= min_amt_yi * 1.2)
    w1_ok = (ctx["max_stk_25d"] >= 3) | (ctx["max_r20_25d"] >= 0.40)

    adj_c = ctx["adj_close"]
    ma10 = ctx["ma10"]
    ma20 = ctx["ma20"]
    hi20 = ctx["hi20"]
    ret_1d = ctx["ret_1d"]
    is_zt = ctx["is_zt"]
    amt = ctx["amount_yi"]
    amt20 = ctx["amt20"]
    streak = ctx["streak"]

    dyn_sc = ctx["stk_dyn_score"]
    sw3_sc = ctx["stk_sw3_score"]
    best_tid = ctx["stk_best_tid"]
    switched = ctx["stk_switched"]
    sw3_mat = ctx["sw3_mat"]

    # Base structural mask (vectorized!)
    struct_ok = (
        U & liq_ok & w1_ok
        & np.isfinite(ma10) & np.isfinite(ma20) & np.isfinite(hi20)
        & (adj_c >= ma20 * 0.96)
        & (adj_c >= ma10 * 0.99)
        & (streak <= 2)  # Wave-2 re-start, not chasing 5th consecutive limit-up
        & ((np.nan_to_num(ret_1d, nan=-1.0) >= 0.03) | is_zt)
        & (amt >= amt20 * 1.15)
    )
    # Also require it had a real pause/pullback in [d-5, d-1] (not purely uninterrupted vertical run)
    out = [[] for _ in range(N_D)]

    for d in range(25, N_D):
        sis = np.flatnonzero(struct_ok[d])
        if len(sis) == 0:
            continue
        c_list = []
        for si in sis:
            si_i = int(si)
            # Check pause/pullback in [d-8, d-1]: at least 1 day where close <= hi20 * 0.96 or streak == 0 for >=2 days
            lo_p = max(0, d - 8)
            had_pause = (np.sum(streak[lo_p:d, si_i] == 0) >= 2) and (np.min(adj_c[lo_p:d, si_i] / np.maximum(hi20[lo_p:d, si_i], 1e-6)) <= 0.96)
            if not had_pause:
                continue

            d_sc = float(dyn_sc[d, si_i])
            s_sc = float(sw3_sc[d, si_i])
            tid = int(best_tid[d, si_i])
            # Estimate Wave-1 peak theme score over [d-24, d-5]
            w1_th_peak = float(np.max(dyn_sc[max(0, d - 24):max(1, d - 4), si_i]))

            if theme_mode == "dyn_high":
                if d_sc < thr_w2:
                    continue
                t_use, sc_use = tid, d_sc
            elif theme_mode == "dyn_switch_or_up":
                is_up = bool(switched[d, si_i]) or (d_sc >= w1_th_peak - 2.0)
                if not (d_sc >= thr_w2 and is_up):
                    continue
                t_use, sc_use = tid, d_sc
            elif theme_mode == "static_sw3":
                if s_sc < thr_w2:
                    continue
                t_use, sc_use = int(sw3_mat[d, si_i]), s_sc
            elif theme_mode == "weak_ctrl":
                if d_sc >= 60.0:
                    continue
                t_use, sc_use = tid, d_sc
            else:
                continue

            rk = sc_use * 2.0 + (10.0 if switched[d, si_i] else 0.0) + min(float(ret_1d[d, si_i]) * 100.0, 20.0) + min(float(amt[d, si_i]), 30.0) * 0.2
            c_list.append((si_i, rk, t_use, sc_use))

        if c_list:
            c_list.sort(key=lambda x: (-x[1], x[0]))
            out[d] = c_list[:10]
    return out


def summarize_run(sim: dict, bench_ctx: dict, name: str, meta_cols: dict) -> tuple[dict, np.ndarray]:
    ev = cm.evaluate_daily_series(sim["dr"], bench_ctx, active_mask=sim["act_mask"], turnover_daily=sim["to_daily"])
    tr_df = sim["closed_trades"]
    tr_5y = cm.compute_trade_stats(tr_df, cm.FULL_START, cm.EVAL_END)
    tr_wf = cm.compute_trade_stats(tr_df, cm.WF_START, cm.EVAL_END)
    tr_26 = cm.compute_trade_stats(tr_df, "2026-01-01", cm.EVAL_END)
    v20 = cm.compute_v20_corr_and_blend(sim["dr"], bench_ctx, start_dt=cm.WF_START, end_dt=cm.EVAL_END)

    row = dict(meta_cols)
    row["strategy_id"] = name
    for wk in ("FULL_5Y", "WF_OOS", "Y2021", "Y2022", "Y2023", "Y2024", "Y2025", "Y2026", "Y26H2"):
        w = ev.get(wk, {})
        row[f"{wk}_nav"] = w.get("nav", 1.0)
        row[f"{wk}_ret_pct"] = w.get("tot_ret_pct", 0.0)
        row[f"{wk}_sharpe"] = w.get("sharpe", 0.0)
        row[f"{wk}_mdd_pct"] = w.get("mdd_pct", 0.0)
        row[f"{wk}_ex300_pp"] = w.get("excess_csi300_pp", 0.0)
        row[f"{wk}_exp_pct"] = w.get("exposure_pct", 0.0)
    row.update({
        "n_trades_5y": tr_5y["n"],
        "wr_5y": tr_5y["wr_pct"],
        "plr_5y": tr_5y["plr"],
        "avg_hold_5y": tr_5y["avg_hold_days"],
        "top5_profit_share_5y": tr_5y["top5_profit_share_pct"],
        "ex5_nav_5y": tr_5y["ex_top5_trade_nav"],
        "n_trades_26": tr_26["n"],
        "wr_26": tr_26["wr_pct"],
        "v20_corr": v20["corr_all_days"],
        "v20_corr_act": v20["corr_strat_active"],
        "csi_corr": v20["corr_csi300"],
        "blend_70v20_30s_sh": v20["blends"]["daily_70v20_30s"]["sharpe"],
        "blend_70v20_30s_mdd": v20["blends"]["daily_70v20_30s"]["mdd_pct"],
        "blend_50v20_50s_sh": v20["blends"]["daily_50v20_50s"]["sharpe"],
        "blend_50v20_50s_mdd": v20["blends"]["daily_50v20_50s"]["mdd_pct"],
    })
    return row, sim["dr"]


def main():
    t0 = time.time()
    bench_ctx = cm.load_bench_and_v20(end_dt=cm.EVAL_END)
    ctx = load_sim_context(tag="full")
    # Align end_idx strictly to EVAL_END ("2026-11-24")
    end_idx = ctx["cal_dts"].index(cm.EVAL_END)
    start_idx = ctx["cal_dts"].index("2021-04-06")  # 60d warmup
    bond_dr = bench_ctx["bond_511010_dr"]

    pre_a = precompute_track_a_cands(ctx, f"{cm.CACHE_DIR}/kpl_events_full.parquet")
    print(f"[Step2] Precompute Track A done in {time.time()-t0:.1f}s | RSS={cm.rss_mb()}MB")

    rows = []
    dr_store = {}
    cand_cache_a = {}

    # 1. Track A Full Parameter Plateau Grid (thr x exit_ma x slots x liq x style x static_ablation x bond)
    # Core plateau: thr in [70, 75, 80, 85], ma in ['ma10', 'ma15', 'ma20'], slots in [3, 5] (default liq=3亿, leader, cash)
    for thr in (70.0, 75.0, 80.0, 85.0):
        cands = generate_track_a_cands(ctx, pre_a, thr_main=thr, confirm_days=2, n_themes=2, min_amt_yi=3.0, pick_style="leader", static_sw3_only=False)
        cand_cache_a[(thr, 3.0, "leader", False)] = cands
        for ex in ("ma10", "ma15", "ma20"):
            for sl in (3, 5):
                nm = f"A_L_T{int(thr)}_{ex}_K{sl}_3y_Cash_30bp"
                sim = simulate_portfolio(ctx, cands, exit_mode=ex, trail_dd=0.15, fade_thr=50.0, fade_use_static=False, n_slots=sl, fee_rt=0.0030, bond_dr=None, start_eval_idx=start_idx, end_idx=end_idx)
                r, dr = summarize_run(sim, bench_ctx, nm, {"track": "A", "thr": thr, "exit": ex, "slots": sl, "liq": 3.0, "style": "leader", "mode": "Dyn", "park": "Cash", "fee_bp": 30})
                rows.append(r)
                dr_store[nm] = dr[:end_idx + 1]

    # Track A Variants: Bond ETF parking, 5亿 liquidity, Pullback style, Static SW3 ablation, Fade/Trail variations, 50bp stress
    for thr in (75.0, 80.0):
        # Pullback style
        c_pb = generate_track_a_cands(ctx, pre_a, thr_main=thr, confirm_days=2, n_themes=2, min_amt_yi=3.0, pick_style="pullback", static_sw3_only=False)
        # 5亿 liquidity
        c_5y = generate_track_a_cands(ctx, pre_a, thr_main=thr, confirm_days=2, n_themes=2, min_amt_yi=5.0, pick_style="leader", static_sw3_only=False)
        # Static SW3 only
        c_st = generate_track_a_cands(ctx, pre_a, thr_main=thr, confirm_days=2, n_themes=2, min_amt_yi=3.0, pick_style="leader", static_sw3_only=True)
        # Dynamic main base
        c_dy = cand_cache_a[(thr, 3.0, "leader", False)]

        c_inst = generate_track_a_cands(ctx, pre_a, thr_main=thr, confirm_days=2, n_themes=2, min_amt_yi=3.0, pick_style="inst_core", static_sw3_only=False)
        variants = [
            (f"A_L_T{int(thr)}_ma20_K5_3y_Bond_30bp", c_dy, "ma20", 0.15, 50.0, False, 5, 0.0030, bond_dr, {"liq": 3.0, "style": "leader", "mode": "Dyn", "park": "Bond511010", "fee_bp": 30}),
            (f"A_L_T{int(thr)}_ma15_K5_3y_Bond_30bp", c_dy, "ma15", 0.15, 50.0, False, 5, 0.0030, bond_dr, {"liq": 3.0, "style": "leader", "mode": "Dyn", "park": "Bond511010", "fee_bp": 30}),
            (f"A_L_T{int(thr)}_hold20_K5_3y_Cash_30bp", c_dy, "hold20", None, None, False, 5, 0.0030, None, {"liq": 3.0, "style": "leader", "mode": "Dyn", "park": "Cash", "fee_bp": 30}),
            (f"A_Inst_T{int(thr)}_ma20_K5_3y_Cash_30bp", c_inst, "ma20", 0.15, 50.0, False, 5, 0.0030, None, {"liq": 3.0, "style": "inst_core", "mode": "Dyn", "park": "Cash", "fee_bp": 30}),
            (f"A_Inst_T{int(thr)}_hold20_K5_3y_Bond_30bp", c_inst, "hold20", None, None, False, 5, 0.0030, bond_dr, {"liq": 3.0, "style": "inst_core", "mode": "Dyn", "park": "Bond511010", "fee_bp": 30}),
            (f"A_L_T{int(thr)}_ma20_K5_5y_Cash_30bp", c_5y, "ma20", 0.15, 50.0, False, 5, 0.0030, None, {"liq": 5.0, "style": "leader", "mode": "Dyn", "park": "Cash", "fee_bp": 30}),
            (f"A_L_T{int(thr)}_ma20_K5_5y_Bond_30bp", c_5y, "ma20", 0.15, 50.0, False, 5, 0.0030, bond_dr, {"liq": 5.0, "style": "leader", "mode": "Dyn", "park": "Bond511010", "fee_bp": 30}),
            (f"A_PB_T{int(thr)}_ma20_K5_3y_Cash_30bp", c_pb, "ma20", 0.15, 50.0, False, 5, 0.0030, None, {"liq": 3.0, "style": "pullback", "mode": "Dyn", "park": "Cash", "fee_bp": 30}),
            (f"A_StaticSW3_T{int(thr)}_ma20_K5_3y_Cash_30bp", c_st, "ma20", 0.15, 50.0, True, 5, 0.0030, None, {"liq": 3.0, "style": "leader", "mode": "StaticSW3", "park": "Cash", "fee_bp": 30}),
            (f"A_L_T{int(thr)}_ma20_K5_3y_Cash_50bp", c_dy, "ma20", 0.15, 50.0, False, 5, 0.0050, None, {"liq": 3.0, "style": "leader", "mode": "Dyn", "park": "Cash", "fee_bp": 50}),
            (f"A_L_T{int(thr)}_ma20_K5_3y_Bond_50bp", c_dy, "ma20", 0.15, 50.0, False, 5, 0.0050, bond_dr, {"liq": 3.0, "style": "leader", "mode": "Dyn", "park": "Bond511010", "fee_bp": 50}),
        ]
        for nm, c_use, ex, tr, fd, f_st, sl, fee, b_dr, meta_u in variants:
            sim = simulate_portfolio(ctx, c_use, exit_mode=ex, trail_dd=tr, fade_thr=fd, fade_use_static=f_st, n_slots=sl, fee_rt=fee, bond_dr=b_dr, start_eval_idx=start_idx, end_idx=end_idx)
            r, dr = summarize_run(sim, bench_ctx, nm, {"track": "A", "thr": thr, "exit": ex, "slots": sl, **meta_u})
            rows.append(r)
            dr_store[nm] = dr[:end_idx + 1]

    # 2. Track B: Dynamic Theme-Switching Wave-2 Capture
    for thr in (70.0, 75.0, 80.0):
        c_b_dyn = generate_track_b_cands(ctx, thr_w2=thr, min_amt_yi=3.0, theme_mode="dyn_high")
        c_b_sw = generate_track_b_cands(ctx, thr_w2=thr, min_amt_yi=3.0, theme_mode="dyn_switch_or_up")
        for ex, tr_v in [("ma5", 0.12), ("ma10", 0.12), ("broken_ma5", 0.12), ("trail12_ma10", 0.12)]:
            for sl in (3, 5):
                nm = f"B_Dyn_T{int(thr)}_{ex}_K{sl}_Cash_30bp"
                sim = simulate_portfolio(ctx, c_b_dyn, exit_mode=ex, trail_dd=tr_v, fade_thr=None, fade_use_static=False, n_slots=sl, fee_rt=0.0030, bond_dr=None, start_eval_idx=start_idx, end_idx=end_idx)
                r, dr = summarize_run(sim, bench_ctx, nm, {"track": "B", "thr": thr, "exit": ex, "slots": sl, "liq": 3.0, "style": "wave2_dyn", "mode": "Dyn", "park": "Cash", "fee_bp": 30})
                rows.append(r)
                dr_store[nm] = dr[:end_idx + 1]

        # Switch-or-Upgrade, Bond, Static SW3, Weak Control, 50bps stress
        c_b_st = generate_track_b_cands(ctx, thr_w2=thr, min_amt_yi=3.0, theme_mode="static_sw3")
        for nm, c_use, md, b_dr, fee in [
            (f"B_SwUp_T{int(thr)}_ma10_K3_Cash_30bp", c_b_sw, "SwitchOrUp", None, 0.0030),
            (f"B_Dyn_T{int(thr)}_ma10_K3_Bond_30bp", c_b_dyn, "Dyn", bond_dr, 0.0030),
            (f"B_StaticSW3_T{int(thr)}_ma10_K3_Cash_30bp", c_b_st, "StaticSW3", None, 0.0030),
            (f"B_Dyn_T{int(thr)}_ma10_K3_Cash_50bp", c_b_dyn, "Dyn", None, 0.0050),
        ]:
            sim = simulate_portfolio(ctx, c_use, exit_mode="ma10", trail_dd=0.12, fade_thr=None, fade_use_static=(md == "StaticSW3"), n_slots=3, fee_rt=fee, bond_dr=b_dr, start_eval_idx=start_idx, end_idx=end_idx)
            r, dr = summarize_run(sim, bench_ctx, nm, {"track": "B", "thr": thr, "exit": "ma10", "slots": 3, "liq": 3.0, "style": "wave2", "mode": md, "park": "Bond511010" if b_dr is not None else "Cash", "fee_bp": int(fee * 10000)})
            rows.append(r)
            dr_store[nm] = dr[:end_idx + 1]

    # Weak theme control (<60)
    c_b_wk = generate_track_b_cands(ctx, thr_w2=60.0, min_amt_yi=3.0, theme_mode="weak_ctrl")
    sim_wk = simulate_portfolio(ctx, c_b_wk, exit_mode="ma10", trail_dd=0.12, fade_thr=None, fade_use_static=False, n_slots=3, fee_rt=0.0030, bond_dr=None, start_eval_idx=start_idx, end_idx=end_idx)
    r_wk, dr_wk = summarize_run(sim_wk, bench_ctx, "B_WeakThemeCtrl_lt60_ma10_K3_30bp", {"track": "B", "thr": 60, "exit": "ma10", "slots": 3, "liq": 3.0, "style": "wave2", "mode": "WeakCtrl", "park": "Cash", "fee_bp": 30})
    rows.append(r_wk)
    dr_store["B_WeakThemeCtrl_lt60_ma10_K3_30bp"] = dr_wk[:end_idx + 1]

    grid_df = pd.DataFrame(rows)
    grid_df.to_csv(f"{cm.RD047_DIR}/rd047_grid.csv", index=False)
    np.savez(f"{cm.CACHE_DIR}/grid_daily_returns.npz", cal_dts=np.array(ctx["cal_dts"][:end_idx + 1]), **dr_store)
    print(f"[Step2 DONE in {time.time()-t0:.1f}s | RSS={cm.rss_mb()}MB] total_configs={len(grid_df)}")


if __name__ == "__main__":
    main()
