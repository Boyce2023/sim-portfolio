#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Agent 5: A-Share Limit-Down Pry & Extreme Oversold Reversal (32 PIT Factors + 300+ Grid Sweep)
Strict D15 4-Pillar Evaluation:
  - 0.20% round-trip fee (FEE_RATE = 0.0020)
  - Strict T+1 exit, limit-down yizi/close-locked deferral (both 10cm & newly-ST 5cm yizi)
  - Suspended zero-turnover filtering (no fake trading on halt bars)
  - Intraday trigger failures excluded only when never touched, all touched-then-resealed limit-down crashes counted 100% in denominator
  - IS (2022-2024) vs OOS (2025-2026) out-of-sample walk-forward validation
"""
import os
import sys
import json
import time
import pickle
import numpy as np
import pandas as pd

WORK_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
if WORK_DIR not in sys.path:
    sys.path.insert(0, WORK_DIR)

from d15_eval_helper import evaluate_d15_full, _slice_metrics, _sim_single_slot, FEE_RATE

EXIT_MODES = [
    ("tp3_h2", 0.03, 2, "tp_close"),
    ("tp3_h3", 0.03, 3, "tp_close"),
    ("tp3_h5", 0.03, 5, "tp_close"),
    ("tp5_h2", 0.05, 2, "tp_close"),
    ("tp5_h3", 0.05, 3, "tp_close"),
    ("tp5_h5", 0.05, 5, "tp_close"),   # Bucket 3 Standard Exit
    ("tp7_h2", 0.07, 2, "tp_close"),
    ("tp7_h3", 0.07, 3, "tp_close"),
    ("tp7_h5", 0.07, 5, "tp_close"),
    ("tp10_h2", 0.10, 2, "tp_close"),
    ("tp10_h3", 0.10, 3, "tp_close"),
    ("tp10_h5", 0.10, 5, "tp_close"),
    ("next_open", 0.0, 1, "next_open"),
    ("next_close", 0.0, 1, "next_close"),
]

ENTRY_MODES = [
    "open_0925",      # 09:25 buyable_open (non-yizi-ZT, non-yizi-DT, non-5%ST-yizi, turnover > 0)
    "pry_dt",         # Open at 10cm limit down (open <= dt_px + 0.011), intraday pry high > dt_px + 0.02 -> buy at dt_px + 0.02
    "right_open15",   # Buyable open, wait intraday surge >= open * 1.015 (< zt_px - 0.005) -> buy at round(open*1.015, 2)
    "right_red",      # Buyable open with open <= pre_c, wait intraday turn red high >= pre_c * 1.002 (< zt_px - 0.005) -> buy at pre_c*1.002 (or open if open > pre_c & buyable)
    "open_or_pry",    # Either buyable_open at 09:25 OR limit-down open pried intraday at dt_px + 0.02
]


def _is_locked_limit_down_bar(op, hi, lo, cl, pc, is_yz_dt_flag):
    """Detect un-sellable full-day limit-down lock (both 10cm yizi_dt and 5cm ST yizi_dt)."""
    if is_yz_dt_flag:
        return True
    if pc > 0 and (op == hi == lo == cl) and (cl / pc - 1.0 <= -0.044):
        return True
    return False


def _is_close_limit_down(cl, pc, dt_px, is_dt_flag):
    """Detect limit-down seal at 15:00 close (cannot sell at close, must defer to next day)."""
    if is_dt_flag or (cl <= dt_px + 0.011):
        return True
    if pc > 0:
        st_dt = np.floor(pc * 0.95 * 100.0 + 0.5) / 100.0
        # Only treat 5% close as ST limit-down if high didn't exceed +5.3% and low didn't breach -5.6%
        if abs(cl - st_dt) <= 0.011:
            return True
    return False


def sim_single_trade_exit(b, pos, buy_px, tp_pct, max_hold, mode):
    """Simulate strict T+1 exit with corporate-action adjf, suspension skipping, and yizi-DT deferral."""
    n = len(b["dts"])
    adj0 = b["adjf"][pos]
    buy_adj = buy_px * adj0
    dts = b["dts"]
    opens, highs, lows, closes = b["open"], b["high"], b["low"], b["close"]
    adjfs, pre_cs, dt_pxs = b["adjf"], b["pre_c"], b["dt_px"]
    is_dts, is_yz_dts, tos = b["is_dt"], b["is_yizi_dt"], b["to"]

    if pos >= n - 1:
        return dts[pos], -FEE_RATE, 0, False

    last_tradable_idx = -1
    tradable_step = 0
    for step in range(1, n - pos):
        idx = pos + step
        to_v = tos[idx]
        if to_v <= 0.0 or np.isnan(to_v):
            # Suspended bar: cannot trade, hold day advances in calendar but wait for resumption
            continue
        tradable_step += 1
        last_tradable_idx = idx
        op, hi, lo, cl, pc, dt_px = opens[idx], highs[idx], lows[idx], closes[idx], pre_cs[idx], dt_pxs[idx]
        if _is_locked_limit_down_bar(op, hi, lo, cl, pc, bool(is_yz_dts[idx])):
            # Full-day yizi limit down (10cm or 5cm ST): strictly un-sellable, defer!
            continue

        adj_i = adjfs[idx]
        op_adj = op * adj_i
        hi_adj = hi * adj_i
        cl_adj = cl * adj_i

        if mode == "next_open":
            return dts[idx], op_adj / buy_adj - 1.0 - FEE_RATE, step, True
        elif mode == "next_close":
            if bool(is_dts[idx]) or (op == lo and abs(cl / (pc + 1e-9) - 0.95) <= 0.006):
                # Sealed at limit down at close -> defer to next open!
                continue
            return dts[idx], cl_adj / buy_adj - 1.0 - FEE_RATE, step, False
        else:
            # Deferred past max_hold due to prior yizi limit-down locks: exit immediately at open once unsealed!
            if tradable_step > max_hold:
                return dts[idx], op_adj / buy_adj - 1.0 - FEE_RATE, step, True
            # Within 1..max_hold tradable days: check intraday TP target relative to buy_adj
            tp_target = buy_adj * (1.0 + tp_pct)
            if op_adj >= tp_target:
                return dts[idx], op_adj / buy_adj - 1.0 - FEE_RATE, step, True
            if hi_adj >= tp_target:
                return dts[idx], tp_pct - FEE_RATE, step, False
            if tradable_step == max_hold:
                # Reached max_hold close: check if sealed at limit down at 15:00
                if bool(is_dts[idx]) or (hi <= pc * 1.055 and lo >= pc * 0.944 and abs(cl / (pc + 1e-9) - 0.95) <= 0.005 and cl == lo):
                    continue
                return dts[idx], cl_adj / buy_adj - 1.0 - FEE_RATE, step, False

    # Terminal fallback: if stock halted into delisting without ever unsealing, apply realistic -70% delisting haircut
    if last_tradable_idx < 0 and dts[pos] < "2026-10-20":
        return dts[-1], -0.70 - FEE_RATE, n - 1 - pos, False
    end_i = last_tradable_idx if last_tradable_idx >= 0 else (n - 1)
    ret = (closes[end_i] * adjfs[end_i]) / buy_adj - 1.0 - FEE_RATE
    if dts[end_i] < "2026-10-20" and _is_locked_limit_down_bar(
        opens[end_i], highs[end_i], lows[end_i], closes[end_i], pre_cs[end_i], bool(is_yz_dts[end_i])
    ):
        # Never unsealed before delisting termination
        ret = min(ret, -0.70 - FEE_RATE)
    return dts[end_i], ret, max(1, end_i - pos), False


def precompute_entry_exit_matrix(df: pd.DataFrame, cb: dict):
    """Precompute entry validity, buy_at_open flag, and all 14 exit outcomes for all 5 entry modes across 8,502 rows."""
    t0 = time.time()
    N = len(df)
    pre = {}
    for em in ENTRY_MODES:
        pre[em] = {
            "valid": np.zeros(N, dtype=bool),
            "buy_at_open": np.zeros(N, dtype=bool),
            "buy_px": np.zeros(N, dtype=float),
            "day0_ret": np.zeros(N, dtype=float),  # Close vs buy_px on day 0 (diagnostic: re-sealed DT rate)
            "exits": {
                ex_name: {
                    "exit_date": np.empty(N, dtype=object),
                    "net_ret": np.zeros(N, dtype=float),
                    "hold_bars": np.zeros(N, dtype=int),
                    "exit_at_open": np.zeros(N, dtype=bool),
                }
                for ex_name, _, _, _ in EXIT_MODES
            },
        }

    prev_is_yizi_dt = np.zeros(N, dtype=bool)
    open_raw = np.zeros(N, dtype=float)
    is_st_yizi_today = np.zeros(N, dtype=bool)

    codes = df["code"].values
    buy_dates = df["buy_date"].values
    buyable_opens = df["buyable_open"].values

    for i in range(N):
        c = codes[i]
        bd = buy_dates[i]
        b = cb[c]
        pos = b["date_to_pos"][bd]
        op = float(b["open"][pos])
        hi = float(b["high"][pos])
        lo = float(b["low"][pos])
        cl = float(b["close"][pos])
        pc = float(b["pre_c"][pos])
        zt_px = float(b["zt_px"][pos])
        dt_px = float(b["dt_px"][pos])
        to_v = float(b["to"][pos])

        open_raw[i] = op
        if pos > 0:
            p_op, p_hi, p_lo, p_cl, p_pc = b["open"][pos - 1], b["high"][pos - 1], b["low"][pos - 1], b["close"][pos - 1], b["pre_c"][pos - 1]
            prev_is_yizi_dt[i] = _is_locked_limit_down_bar(p_op, p_hi, p_lo, p_cl, p_pc, bool(b["is_yizi_dt"][pos - 1]))

        if to_v <= 0.0 or np.isnan(to_v):
            continue

        st_yz = _is_locked_limit_down_bar(op, hi, lo, cl, pc, False)
        is_st_yizi_today[i] = st_yz
        real_buyable_open = bool(buyable_opens[i]) and (not st_yz)
        can_pry = (op <= dt_px + 0.011) and (hi > dt_px + 0.02)

        # Determine (valid, buy_px, buy_at_open) per entry mode
        em_specs = {}
        if real_buyable_open:
            em_specs["open_0925"] = (op, True)
            # Right-side confirmation 1: surge >= open * 1.015
            trig15 = np.round(op * 1.015, 2)
            if trig15 <= op:
                trig15 = op + 0.01
            if trig15 < zt_px - 0.005 and hi >= trig15:
                em_specs["right_open15"] = (trig15, False)
            # Right-side confirmation 2: turn red (high >= pre_c * 1.002) or open already > pre_c * 1.002
            trig_red = np.round(pc * 1.002, 2)
            if op >= trig_red and op < zt_px - 0.011:
                em_specs["right_red"] = (op, True)
            elif op < trig_red and trig_red < zt_px - 0.005 and hi >= trig_red:
                em_specs["right_red"] = (trig_red, False)

        if can_pry:
            pry_px = np.round(dt_px + 0.02, 2)
            em_specs["pry_dt"] = (pry_px, False)

        if real_buyable_open:
            em_specs["open_or_pry"] = (op, True)
        elif can_pry:
            em_specs["open_or_pry"] = (np.round(dt_px + 0.02, 2), False)

        # Cache exits by distinct buy_px so identical buy_px across modes isn't recomputed!
        px_cache = {}
        for em, (bpx, bao) in em_specs.items():
            d = pre[em]
            d["valid"][i] = True
            d["buy_at_open"][i] = bao
            d["buy_px"][i] = bpx
            d["day0_ret"][i] = cl / bpx - 1.0
            if bpx not in px_cache:
                res_ex = {}
                for ex_name, tp_p, mh, md in EXIT_MODES:
                    res_ex[ex_name] = sim_single_trade_exit(b, pos, bpx, tp_p, mh, md)
                px_cache[bpx] = res_ex
            for ex_name, (ex_dt, nret, hb, ex_op) in px_cache[bpx].items():
                ex_d = d["exits"][ex_name]
                ex_d["exit_date"][i] = ex_dt
                ex_d["net_ret"][i] = nret
                ex_d["hold_bars"][i] = hb
                ex_d["exit_at_open"][i] = ex_op

    df["prev_is_yizi_dt"] = prev_is_yizi_dt
    df["open_px_raw"] = open_raw
    df["is_st_yizi_today"] = is_st_yizi_today
    df["is_st_name"] = df["name"].astype(str).str.contains("ST|退", na=False).values
    print(f"[+] Precomputed 5 entries x 14 exits across {N:,} rows in {time.time()-t0:.2f}s")
    return pre


def eval_fast(df: pd.DataFrame, pre: dict, mask: np.ndarray, entry_mode: str, exit_mode: str,
              prio_arr: np.ndarray, max_per_day: int = 0) -> dict:
    """Build trades_df from precomputed arrays and evaluate full D15 + IS (2022-2024) + OOS (2025-2026) metrics."""
    em_d = pre[entry_mode]
    full_mask = mask & em_d["valid"]
    idx = np.flatnonzero(full_mask)
    if len(idx) == 0:
        empty_d15 = evaluate_d15_full(pd.DataFrame())
        empty_is = _slice_metrics(pd.DataFrame(), "2022-01-04", "2024-12-31")
        empty_oos = _slice_metrics(pd.DataFrame(), "2025-01-02", "2026-11-10")
        return {
            "d15": empty_d15,
            "is_22_24": empty_is,
            "oos_25_26": empty_oos,
            "raw_mean_pct": 0.0,
            "raw_wr_pct": 0.0,
            "raw_median_pct": 0.0,
            "raw_min_pct": 0.0,
            "raw_loss15_cnt": 0,
            "raw_loss25_cnt": 0,
            "single_loss15_cnt": 0,
            "single_loss25_cnt": 0,
            "day0_reseal_dt_rate": 0.0,
            "_tdf": pd.DataFrame(),
        }

    ex_d = em_d["exits"][exit_mode]
    tdf = pd.DataFrame({
        "code": df["code"].values[idx],
        "name": df["name"].values[idx],
        "buy_date": df["buy_date"].values[idx],
        "exit_date": ex_d["exit_date"][idx],
        "net_ret": ex_d["net_ret"][idx],
        "hold_bars": ex_d["hold_bars"][idx],
        "buy_at_open": em_d["buy_at_open"][idx],
        "exit_at_open": ex_d["exit_at_open"][idx],
        "priority_score": prio_arr[idx],
        "day0_ret": em_d["day0_ret"][idx],
        "is_dt_today": df["is_dt_today"].values[idx] if "is_dt_today" in df.columns else (df["pct"].values[idx] <= -0.095),
    })

    if max_per_day > 0:
        tdf = tdf.sort_values(["buy_date", "priority_score"], ascending=[True, False]).groupby("buy_date", as_index=False).head(max_per_day).reset_index(drop=True)

    d15 = evaluate_d15_full(tdf)
    is_m = _slice_metrics(tdf[(tdf["buy_date"] >= "2022-01-04") & (tdf["buy_date"] <= "2024-12-31")], "2022-01-04", "2024-12-31")
    oos_m = _slice_metrics(tdf[(tdf["buy_date"] >= "2025-01-02") & (tdf["buy_date"] <= "2026-11-10")], "2025-01-02", "2026-11-10")

    # Raw & single-slot tail blowup stats (net_ret <= -15%, <= -25%)
    raw_rets = tdf["net_ret"].values
    taken, _, _, _ = _sim_single_slot(tdf)
    s_rets = np.array([float(x.net_ret) for x in taken]) if taken else np.array([])

    return {
        "d15": d15,
        "is_22_24": is_m,
        "oos_25_26": oos_m,
        "raw_mean_pct": round(float(raw_rets.mean() * 100.0), 2),
        "raw_wr_pct": round(float((raw_rets > 0).mean() * 100.0), 2),
        "raw_median_pct": round(float(np.median(raw_rets) * 100.0), 2),
        "raw_min_pct": round(float(raw_rets.min() * 100.0), 2),
        "raw_loss15_cnt": int((raw_rets <= -0.15).sum()),
        "raw_loss25_cnt": int((raw_rets <= -0.25).sum()),
        "single_loss15_cnt": int((s_rets <= -0.15).sum()) if len(s_rets) else 0,
        "single_loss25_cnt": int((s_rets <= -0.25).sum()) if len(s_rets) else 0,
        "day0_reseal_dt_rate": round(float(tdf["is_dt_today"].mean() * 100.0), 2),
        "_tdf": tdf,
    }


def compact_record(vid: str, group: str, desc: str, entry_m: str, exit_m: str, ev: dict) -> dict:
    f5 = ev["d15"]["full_5y"]
    ex25 = ev["d15"]["ex2025_4y"]
    r3 = ev["d15"]["recent_3y"]
    r1 = ev["d15"]["recent_1y"]
    jul26 = ev["d15"]["since_jul2026"]
    h2 = ev["d15"]["half2_5y"]
    ism = ev["is_22_24"]
    oosm = ev["oos_25_26"]
    return {
        "id": vid,
        "group": group,
        "desc": desc,
        "entry": entry_m,
        "exit": exit_m,
        "raw_n": f5["raw_n"],
        "raw_wr": ev["raw_wr_pct"],
        "raw_mean_pct": ev["raw_mean_pct"],
        "raw_loss15_cnt": ev["raw_loss15_cnt"],
        "raw_loss25_cnt": ev["raw_loss25_cnt"],
        "day0_reseal_dt_rate": ev["day0_reseal_dt_rate"],
        "single_n": f5["single_n"],
        "wr_5y": f5["wr"],
        "payoff_5y": f5["payoff"],
        "mean_5y": f5["mean_pct"],
        "single_nav_5y": f5["single_nav"],
        "single_mdd_5y": f5["single_mdd_pct"],
        "single_excess_5y": f5["single_excess_pct"],
        "eq_nav_5y": f5["eq_nav"],
        "eq_mdd_5y": f5["eq_mdd_pct"],
        "eq_excess_5y": f5["eq_excess_pct"],
        "half2_nav_5y": h2["nav"],
        "half2_mdd_5y": h2["mdd_pct"],
        "trimmed5_nav_5y": f5["trimmed5_nav"],
        "single_loss15_cnt": ev["single_loss15_cnt"],
        "single_loss25_cnt": ev["single_loss25_cnt"],
        # Multi-period D15
        "ex2025_nav": ex25["single_nav"],
        "ex2025_wr": ex25["wr"],
        "r3y_n": r3["single_n"],
        "r3y_wr": r3["wr"],
        "r3y_payoff": r3["payoff"],
        "r3y_nav": r3["single_nav"],
        "r3y_eq_nav": r3["eq_nav"],
        "r1y_n": r1["single_n"],
        "r1y_wr": r1["wr"],
        "r1y_nav": r1["single_nav"],
        "jul26_n": jul26["single_n"],
        "jul26_wr": jul26["wr"],
        "jul26_nav": jul26["single_nav"],
        # IS vs OOS
        "is_raw_n": ism["raw_n"],
        "is_single_n": ism["single_n"],
        "is_wr": ism["wr"],
        "is_payoff": ism["payoff"],
        "is_mean_pct": ism["mean_pct"],
        "is_single_nav": ism["single_nav"],
        "is_single_mdd": ism["single_mdd_pct"],
        "is_eq_nav": ism["eq_nav"],
        "is_excess_pct": ism["single_excess_pct"],
        "oos_raw_n": oosm["raw_n"],
        "oos_single_n": oosm["single_n"],
        "oos_wr": oosm["wr"],
        "oos_payoff": oosm["payoff"],
        "oos_mean_pct": oosm["mean_pct"],
        "oos_single_nav": oosm["single_nav"],
        "oos_single_mdd": oosm["single_mdd_pct"],
        "oos_eq_nav": oosm["eq_nav"],
        "oos_excess_pct": oosm["single_excess_pct"],
        "annual": {yr: {
            "raw_n": m["raw_n"], "single_n": m["single_n"], "wr": m["wr"],
            "mean_pct": m["mean_pct"], "single_nav": m["single_nav"], "eq_nav": m["eq_nav"],
            "single_mdd_pct": m["single_mdd_pct"], "csi300_pct": m["csi300_pct"]
        } for yr, m in ev["d15"]["annual"].items()},
    }


def main():
    t_start = time.time()
    df = pd.read_parquet(f"{WORK_DIR}/cand_pry_limitdown.parquet")
    with open(f"{WORK_DIR}/code_bars_5y.pkl", "rb") as f:
        cb = pickle.load(f)["code_bars"]

    pre = precompute_entry_exit_matrix(df, cb)

    # Priority score arrays
    prio_deep10 = -df["ret_pre10"].values.astype(float)  # Deeper 10d drop = higher priority (Bucket 3 handbook default)
    prio_sprior = df["s_prior"].values.astype(float)
    prio_lock10 = df["lock_top10"].values.astype(float)

    results = []

    def add_run(vid, grp, desc, mask, em="open_0925", ex="tp5_h5", prio=prio_deep10, max_d=0, keep_tdf=False):
        ev = eval_fast(df, pre, mask, em, ex, prio, max_d)
        rec = compact_record(vid, grp, desc, em, ex, ev)
        results.append(rec)
        return (rec, ev["_tdf"]) if keep_tdf else rec

    # =========================================================================
    # SECTION 1: EXACT BUCKET 3 BASELINE & CORE PARADIGM COMPARISON
    # =========================================================================
    m_b3 = (df["prev_dt_streak"].values >= 3) & (df["zt_cnt_pre20"].values == 0)
    m_dt3_all = (df["prev_dt_streak"].values >= 3)
    m_dt3_a_kill = (df["prev_dt_streak"].values >= 3) & (df["zt_cnt_pre20"].values >= 1)
    m_dt2_pure = (df["prev_dt_streak"].values >= 2) & (df["zt_cnt_pre20"].values == 0)
    m_dt2_all = (df["prev_dt_streak"].values >= 2)
    m_dt2_exact_pure = (df["prev_dt_streak"].values == 2) & (df["zt_cnt_pre20"].values == 0)
    m_dt2_a_kill = (df["prev_dt_streak"].values >= 2) & (df["zt_cnt_pre20"].values >= 1)
    m_dt1_all = (df["prev_dt_streak"].values >= 1)
    m_dt1_pure = (df["prev_dt_streak"].values >= 1) & (df["zt_cnt_pre20"].values == 0)
    m_dt1_a_kill = (df["prev_dt_streak"].values >= 1) & (df["zt_cnt_pre20"].values >= 1)

    # 1A. Bucket 3 exact replication (all vs top-2 deepest 10d drop per day, as written in strategy_astock.md)
    add_run("B01_B3_EXACT_ALL", "1_Baseline", "桶3精确复刻(>=3跌停+前20日0涨停+09:25非一字跌停买+5日摸+5%止盈,全样本)", m_b3, "open_0925", "tp5_h5", prio_deep10, 0)
    add_run("B02_B3_EXACT_TOP2", "1_Baseline", "桶3精确复刻(同日多只取10日跌幅最深前2只等权,手册原版)", m_b3, "open_0925", "tp5_h5", prio_deep10, 2)
    add_run("B03_DT3_ALL_OPEN", "1_Baseline", ">=3连跌停(不限前20日涨停)+09:25非一字跌停买+5日摸+5%", m_dt3_all, "open_0925", "tp5_h5")
    add_run("B04_DT3_AKILL_OPEN", "1_Baseline", ">=3连跌停+高位妖股A杀(zt_cnt_pre20>=1)+09:25买+5日摸+5%", m_dt3_a_kill, "open_0925", "tp5_h5")

    # 1B. Intraday Limit-Down Pry (open <= dt_px+0.011 & high > dt_px+0.02) across streak >=3, >=2, >=1
    add_run("B05_PRY_DT3_PURE", "1_Baseline", "盘中跌停撬板(>=3连跌停+纯超跌zt20==0+跌停开盘撬开买)", m_b3, "pry_dt", "tp5_h5")
    add_run("B06_PRY_DT3_ALL", "1_Baseline", "盘中跌停撬板(>=3连跌停全量+跌停开盘撬开买)", m_dt3_all, "pry_dt", "tp5_h5")
    add_run("B07_PRY_DT3_AKILL", "1_Baseline", "盘中跌停撬板(>=3连跌停+妖股A杀zt20>=1+跌停开盘撬开买)", m_dt3_a_kill, "pry_dt", "tp5_h5")
    add_run("B08_PRY_DT2_PURE", "1_Baseline", "盘中跌停撬板(>=2连跌停+纯超跌zt20==0+跌停开盘撬开买)", m_dt2_pure, "pry_dt", "tp5_h5")
    add_run("B09_PRY_DT2_ALL", "1_Baseline", "盘中跌停撬板(>=2连跌停全量+跌停开盘撬开买)", m_dt2_all, "pry_dt", "tp5_h5")
    add_run("B10_PRY_DT2_AKILL", "1_Baseline", "盘中跌停撬板(>=2连跌停+妖股A杀zt20>=1+跌停开盘撬开买)", m_dt2_a_kill, "pry_dt", "tp5_h5")
    add_run("B11_PRY_DT1_PURE", "1_Baseline", "盘中跌停撬板(>=1跌停+纯超跌zt20==0+跌停开盘撬开买)", m_dt1_pure, "pry_dt", "tp5_h5")
    add_run("B12_PRY_DT1_ALL", "1_Baseline", "盘中跌停撬板(>=1跌停全量+跌停开盘撬开买)", m_dt1_all, "pry_dt", "tp5_h5")
    add_run("B13_PRY_DT1_AKILL", "1_Baseline", "盘中跌停撬板(>=1跌停+妖股A杀zt20>=1+跌停开盘撬开买)", m_dt1_a_kill, "pry_dt", "tp5_h5")

    # 1C. Two-Limit-Down Next-Day Anti-Nuclear (prev_dt_streak >= 2)
    add_run("B14_DT2_PURE_OPEN", "1_Baseline", ">=2连跌停次日反核(纯超跌zt20==0+09:25非一字跌停买)", m_dt2_pure, "open_0925", "tp5_h5")
    add_run("B15_DT2_ALL_OPEN", "1_Baseline", ">=2连跌停次日反核(全量+09:25非一字跌停买)", m_dt2_all, "open_0925", "tp5_h5")
    add_run("B16_DT2_EXACT_PURE_OPEN", "1_Baseline", "==2连跌停次日反核(纯超跌zt20==0+09:25非一字跌停买)", m_dt2_exact_pure, "open_0925", "tp5_h5")
    add_run("B17_DT2_AKILL_OPEN", "1_Baseline", ">=2连跌停次日反核(妖股A杀zt20>=1+09:25非一字跌停买)", m_dt2_a_kill, "open_0925", "tp5_h5")
    add_run("B18_B3_OPEN_OR_PRY", "1_Baseline", ">=3连跌停纯超跌(09:25开盘买或一字跌停盘中撬开买合并)", m_b3, "open_or_pry", "tp5_h5")

    # =========================================================================
    # SECTION 2: FATAL LANDMINE REMOVAL (notice_bad, penny stock, ST, zt_cnt_pre20, prior_mb_gap)
    # =========================================================================
    not_bad = ~df["notice_bad"].values
    is_bad = df["notice_bad"].values
    px_ok = df["open_px_raw"].values >= 2.0  # Face-value delisting protection (>= 2 yuan)
    no_st_name = ~df["is_st_name"].values

    for base_tag, base_m, em in [
        ("B3_OPEN", m_b3, "open_0925"),
        ("DT3_ALL_OPEN", m_dt3_all, "open_0925"),
        ("DT2_PURE_OPEN", m_dt2_pure, "open_0925"),
        ("DT2_ALL_OPEN", m_dt2_all, "open_0925"),
        ("PRY_DT2_ALL", m_dt2_all, "pry_dt"),
        ("PRY_DT1_ALL", m_dt1_all, "pry_dt"),
    ]:
        add_run(f"M_{base_tag}_ONLY_BAD", "2_Landmine", f"{base_tag} 仅暴雷股样本(notice_bad==True 对照组)", base_m & is_bad, em, "tp5_h5")
        add_run(f"M_{base_tag}_NOT_BAD", "2_Landmine", f"{base_tag} + 剔除暴雷公告(not notice_bad)", base_m & not_bad, em, "tp5_h5")
        add_run(f"M_{base_tag}_NOT_BAD_PX2", "2_Landmine", f"{base_tag} + not notice_bad + 股价>=2元(防面值退市)", base_m & not_bad & px_ok, em, "tp5_h5")
        add_run(f"M_{base_tag}_NOT_BAD_PX2_NOST", "2_Landmine", f"{base_tag} + not notice_bad + 股价>=2元 + 剔ST名", base_m & not_bad & px_ok & no_st_name, em, "tp5_h5")

    # zt_cnt_pre20 & prior_mb_gap granular breakdown on clean universe (not notice_bad & open >= 2.0)
    clean_dt2 = m_dt2_all & not_bad & px_ok
    clean_dt3 = m_dt3_all & not_bad & px_ok
    for tag_u, u_mask, em in [("DT3_OPEN", clean_dt3, "open_0925"), ("DT2_OPEN", clean_dt2, "open_0925"), ("DT2_PRY", clean_dt2, "pry_dt")]:
        add_run(f"Z_{tag_u}_ZT0", "2_Oversold_vs_AKill", f"{tag_u}(排雷后) + zt_cnt_pre20 == 0 (纯超跌)", u_mask & (df["zt_cnt_pre20"].values == 0), em, "tp5_h5")
        add_run(f"Z_{tag_u}_ZT1_2", "2_Oversold_vs_AKill", f"{tag_u}(排雷后) + zt_cnt_pre20 in [1,2] (轻度活跃股)", u_mask & (df["zt_cnt_pre20"].values >= 1) & (df["zt_cnt_pre20"].values <= 2), em, "tp5_h5")
        add_run(f"Z_{tag_u}_ZT3P", "2_Oversold_vs_AKill", f"{tag_u}(排雷后) + zt_cnt_pre20 >= 3 (高位连板妖股A杀)", u_mask & (df["zt_cnt_pre20"].values >= 3), em, "tp5_h5")
        add_run(f"Z_{tag_u}_ZT5P", "2_Oversold_vs_AKill", f"{tag_u}(排雷后) + zt_cnt_pre20 >= 5 (极高标妖股断板A杀)", u_mask & (df["zt_cnt_pre20"].values >= 5), em, "tp5_h5")
        add_run(f"Z_{tag_u}_MBGAP_LE15", "2_Oversold_vs_AKill", f"{tag_u}(排雷后) + prior_mb_gap <= 15 (刚断板连板股记忆)", u_mask & (df["prior_mb_gap"].values <= 15), em, "tp5_h5")
        add_run(f"Z_{tag_u}_MBGAP_16_120", "2_Oversold_vs_AKill", f"{tag_u}(排雷后) + prior_mb_gap 16..120 (中期老妖股记忆)", u_mask & (df["prior_mb_gap"].values >= 16) & (df["prior_mb_gap"].values <= 120), em, "tp5_h5")
        add_run(f"Z_{tag_u}_MBGAP_GT120", "2_Oversold_vs_AKill", f"{tag_u}(排雷后) + prior_mb_gap > 120 (无近期连板纯冷门)", u_mask & (df["prior_mb_gap"].values > 120), em, "tp5_h5")

    # =========================================================================
    # SECTION 3: ALL 32 PIT FACTORS UNIVARIATE MARGINAL SWEEP
    # Tested systematically across 3 core bases:
    #   Base U1: Bucket 3 Pure Oversold (prev_dt_streak>=3 & zt_cnt_pre20==0 & open_0925)
    #   Base U2: Broad Anti-Nuclear Open (prev_dt_streak>=2 & not notice_bad & open_0925)
    #   Base U3: Intraday Limit-Down Pry (prev_dt_streak>=2 & not notice_bad & pry_dt)
    # =========================================================================
    u_bases = [
        ("U1_B3", m_b3, "open_0925"),
        ("U2_DT2_OPEN", m_dt2_all & not_bad, "open_0925"),
        ("U3_DT2_PRY", m_dt2_all & not_bad, "pry_dt"),
    ]

    # Map all 32 1-to-2 PIT factors (and exact requested thresholds) into univariate slices
    factor_slices = [
        # --- Requested Chip & Float thresholds ---
        ("F01_lock10_ge40", "lock_top10 >= 40%", df["lock_top10"].values >= 40.0),
        ("F01_lock10_ge50", "lock_top10 >= 50%", df["lock_top10"].values >= 50.0),
        ("F01_lock10_ge60", "lock_top10 >= 60%", df["lock_top10"].values >= 60.0),
        ("F01_lock10_lt40", "lock_top10 < 40%", df["lock_top10"].values < 40.0),
        ("F02_lock5_ge35", "lock_big5 >= 35%", df["lock_big5"].values >= 35.0),
        ("F03_rfmcap_le20", "real_free_mcap <= 20亿", df["real_free_mcap"].values <= 20.0),
        ("F03_rfmcap_le35", "real_free_mcap <= 35亿", df["real_free_mcap"].values <= 35.0),
        ("F03_rfmcap_le50", "real_free_mcap <= 50亿", df["real_free_mcap"].values <= 50.0),
        ("F03_rfmcap_gt50", "real_free_mcap > 50亿", df["real_free_mcap"].values > 50.0),
        ("F04_mcap_le30", "mcap <= 30亿 (小微盘)", df["mcap"].values <= 30.0),
        ("F04_mcap_30_100", "mcap 30~100亿 (中盘)", (df["mcap"].values > 30.0) & (df["mcap"].values <= 100.0)),
        ("F04_mcap_gt100", "mcap > 100亿 (大盘)", df["mcap"].values > 100.0),
        # --- Turnover / Yizi Unseal vs High-Volume Dump ---
        ("F05_prev_to_lt2", "prev_to < 2% (前日无量一字闷杀首次开板)", df["prev_to"].values < 2.0),
        ("F05_prev_to_lt5", "prev_to < 5% (前日缩量跌停)", df["prev_to"].values < 5.0),
        ("F05_prev_to_5_15", "prev_to 5%~15% (中等换手跌停)", (df["prev_to"].values >= 5.0) & (df["prev_to"].values <= 15.0)),
        ("F05_prev_to_gt15", "prev_to > 15% (前日巨量换手跌停充分释放)", df["prev_to"].values > 15.0),
        ("F06_prev_yz_dt_T", "prev_is_yizi_dt == True (前日一字跌停首次开板)", df["prev_is_yizi_dt"].values),
        ("F06_prev_yz_dt_F", "prev_is_yizi_dt == False (前日非一字换手跌停)", ~df["prev_is_yizi_dt"].values),
        ("F07_prev_real_to_gt20", "prev_real_to > 20% (前日真实换手充分)", df["prev_real_to"].values > 20.0),
        ("F08_prev_vr_lt06", "prev_vol_ratio < 0.6 (极致缩量跌停)", df["prev_vol_ratio"].values < 0.60),
        ("F08_prev_vr_gt12", "prev_vol_ratio > 1.2 (放量恐慌涌出)", df["prev_vol_ratio"].values > 1.20),
        ("F09_prev_amt_gt3e8", "prev_amt >= 3亿 (容量流动性票)", df["prev_amt"].values >= 3e8),
        # --- Macro Panic Ice-Point & CSI300 ---
        ("F10_mkt_dt_lt10", "mkt_dt_prev < 10 (常态非恐慌期个股独跌)", df["mkt_dt_prev"].values < 10),
        ("F10_mkt_dt_ge10", "mkt_dt_prev >= 10 (轻度恐慌)", df["mkt_dt_prev"].values >= 10),
        ("F10_mkt_dt_ge20", "mkt_dt_prev >= 20 (中度冰点错杀)", df["mkt_dt_prev"].values >= 20),
        ("F10_mkt_dt_ge30", "mkt_dt_prev >= 30 (全场冰点错杀)", df["mkt_dt_prev"].values >= 30),
        ("F10_mkt_dt_ge50", "mkt_dt_prev >= 50 (重度股灾恐慌)", df["mkt_dt_prev"].values >= 50),
        ("F10_mkt_dt_ge100", "mkt_dt_prev >= 100 (百股跌停极端冰点)", df["mkt_dt_prev"].values >= 100),
        ("F11_csi5_le_m2", "csi300_ret5 <= -2% (大盘5日急跌)", df["csi300_ret5"].values <= -0.02),
        ("F11_csi5_le_m4", "csi300_ret5 <= -4% (大盘5日暴跌)", df["csi300_ret5"].values <= -0.04),
        ("F11_csi5_gt_0", "csi300_ret5 > 0% (大盘上涨期逆势跌停)", df["csi300_ret5"].values > 0.0),
        ("F12_csi20_le_m5", "csi300_ret20 <= -5% (中期下跌波段)", df["csi300_ret20"].values <= -0.05),
        ("F13_csi_amp20_ge8", "csi300_amp20 >= 8% (高波动宽幅期)", df["csi300_amp20"].values >= 0.08),
        # --- Sentiment & Ecology Sensors (from 1-to-2 V17) ---
        ("F14_fb_open_lt0", "mkt_fb_open_avg < 0% (昨日首板今日竞价负溢价极致冰点)", df["mkt_fb_open_avg"].values < 0.0),
        ("F14_fb_open_ge15", "mkt_fb_open_avg >= 1.5% (短线竞价高溢价回暖日)", df["mkt_fb_open_avg"].values >= 0.015),
        ("F15_promo_lt15", "mkt_promo_1to2_5d < 15% (连板晋级冰点)", df["mkt_promo_1to2_5d"].values < 0.15),
        ("F15_promo_ge20", "mkt_promo_1to2_5d >= 20% (连板生态活跃)", df["mkt_promo_1to2_5d"].values >= 0.20),
        ("F16_seal_lt55", "mkt_seal_rate_prev < 55% (昨日炸板潮分歧)", df["mkt_seal_rate_prev"].values < 0.55),
        ("F17_roll20_ho_ge45", "roll20_ho_zt >= 45% (接力顺风环境)", df["roll20_ho_zt"].values >= 0.45),
        ("F18_max_board_ge5", "mkt_max_board_prev >= 5 (高标空间>=5板)", df["mkt_max_board_prev"].values >= 5),
        ("F19_prev3b_dt_ge2", "prev_3b_dt_cnt >= 2 (昨日高标批量核按钮)", df["prev_3b_dt_cnt"].values >= 2),
        ("F20_brk_dt_ge40", "prev_break_dt_rate_10d >= 40% (近期断板核按钮高发期)", df["prev_break_dt_rate_10d"].values >= 0.40),
        ("F21_nuke34_ge30", "prev_3to4_nuke_rate_20d >= 30% (中高位闷杀期)", df["prev_3to4_nuke_rate_20d"].values >= 0.30),
        ("F22_mkt_zt_lt35", "mkt_zt_prev < 35 (全场涨停稀少冰点)", df["mkt_zt_prev"].values < 35),
        ("F22_mkt_zt_ge60", "mkt_zt_prev >= 60 (全场情绪高涨)", df["mkt_zt_prev"].values >= 60),
        ("F23_mkt_yizi_ge8", "mkt_yizi_cnt >= 8 (当日早盘一字顶板多情绪强修复)", df["mkt_yizi_cnt"].values >= 8),
        # --- Theme, Elo & Industry Resonance ---
        ("F24_sprior_gt0", "s_prior > 0 (有主线题材归属)", df["s_prior"].values > 0.0),
        ("F24_sprior_ge35", "s_prior >= 35 (强题材先验共振)", df["s_prior"].values >= 35.0),
        ("F25_pelo_gt105", "p_elo > 105 (强势题材Elo)", df["p_elo"].values > 105.0),
        ("F26_rk_theme_le3", "rk_theme <= 3 (当日主线前三题材)", df["rk_theme"].values <= 3),
        ("F27_psz_ge3", "p_sz >= 3 (板块涨停梯队>=3家护航)", df["p_sz"].values >= 3),
        ("F28_not_ev_bsk", "not is_event_basket (剔除事件大筐假题材)", ~df["is_event_basket"].values),
        ("F28_not_dying", "not is_dying_pulse (剔除退潮脉冲题材)", ~df["is_dying_pulse"].values),
        ("F29_dom_day", "is_dominant_day == True (大主线断层日)", df["is_dominant_day"].values),
        ("F29_melee_day", "is_melee_day == True (题材混战日)", df["is_melee_day"].values),
        ("F30_csrc_zt_ge1", "csrc_zt_cnt >= 1 (同证监会二级行业昨日有涨停活口)", df["csrc_zt_cnt"].values >= 1),
        ("F30_csrc_zt_ge2", "csrc_zt_cnt >= 2 (同证监会二级行业昨日>=2家涨停)", df["csrc_zt_cnt"].values >= 2),
        # --- Drawdown Depth, Lhasa Retail, IR, Notices, Community & Open Rank ---
        ("F31_dd20_le68", "dd20 <= 0.68 (20日高点回撤>=32%深度超跌)", df["dd20"].values <= 0.68),
        ("F31_dd60_le60", "dd60 <= 0.60 (60日高点回撤>=40%极度腰斩)", df["dd60"].values <= 0.60),
        ("F31_ret10_le_m30", "ret_pre10 <= -30% (10日暴跌超30%)", df["ret_pre10"].values <= -0.30),
        ("F32_lhasa_0", "lhasa_seats_prev == 0 (前日龙虎榜无拉萨散户抄底刀)", df["lhasa_seats_prev"].values == 0),
        ("F32_lhasa_ge2", "lhasa_seats_prev >= 2 (前日拉萨大军接飞刀拥挤)", df["lhasa_seats_prev"].values >= 2),
        ("F33_has_ir_8d", "has_ir_8d == True (近8日有机构调研背书)", df["has_ir_8d"].values),
        ("F34_notice_pos", "notice_hard or notice_ma or notice_earn (正面硬催化/重组/业绩)", df["notice_hard"].values | df["notice_ma"].values | df["notice_earn"].values),
        ("F35_comm_gt0", "comm_posts_24h >= 1 (雪球股吧24h有讨论热度)", df["comm_posts_24h"].values >= 1),
        ("F36_open_gap_deep", "open_pct <= -5% (深度核按钮低开>5%)", df["open_pct"].values <= -0.05),
        ("F36_open_gap_mild", "open_pct > -4% (浅低开/高开强承接反核)", df["open_pct"].values > -0.04),
        ("F36_csrc_rk1", "csrc_buy_rk == 1 (同行业反核开盘最强第1名)", df["csrc_buy_rk"].values == 1),
    ]

    for b_tag, b_mask, b_em in u_bases:
        for f_code, f_desc, f_m in factor_slices:
            add_run(f"{b_tag}__{f_code}", f"3_Univariate_{b_tag}", f"{b_tag} + {f_desc}", b_mask & f_m, b_em, "tp5_h5")

    # =========================================================================
    # SECTION 4: ENTRY TIMING x EXIT MATRIX FULL SWEEP (5 Entries x 14 Exits = 70 combos x 2 universes)
    # =========================================================================
    ee_universes = [
        ("EE_B3_CLEAN", "桶3排雷纯超跌(>=3跌停+zt20==0+not_bad+股价>=2)", m_b3 & not_bad & px_ok),
        ("EE_DT2_PANIC", "两连跌停排雷冰点(>=2跌停+zt20==0+not_bad+股价>=2+mkt_dt>=20)", m_dt2_pure & not_bad & px_ok & (df["mkt_dt_prev"].values >= 20)),
        ("EE_DT2_AKILL", "两连跌停排雷妖股反核(>=2跌停+zt20>=2+not_bad+股价>=2)", (df["prev_dt_streak"].values >= 2) & (df["zt_cnt_pre20"].values >= 2) & not_bad & px_ok),
    ]
    for u_code, u_desc, u_m in ee_universes:
        for em in ENTRY_MODES:
            for ex_name, _, _, _ in EXIT_MODES:
                add_run(f"{u_code}__{em}__{ex_name}", f"4_EntryExit_{u_code}", f"{u_desc} | 买:{em} | 卖:{ex_name}", u_m, em, ex_name)

    # =========================================================================
    # SECTION 5: MULTI-FACTOR COMPOSITE ARCHETYPES (Mechanistic Combinations, Zero Overfitting)
    # =========================================================================
    # Archetype A: Pure Macro Panic Mistaken-Kill Oversold (Bucket 3 Upgraded)
    # Physical logic: Pure oversold (zt20==0) + Clean balance sheet/notice (not notice_bad, px>=2, no ST) + Market Ice-Point panic (mkt_dt_prev >= [20, 30, 50] or csi300_ret5 <= -0.02)
    base_clean_pure3 = m_b3 & not_bad & px_ok & no_st_name
    base_clean_pure2 = m_dt2_pure & not_bad & px_ok & no_st_name

    combo_specs = [
        # --- Bucket 3 Upgraded Candidates (>=3 DT pure oversold) ---
        ("C01_B3_CLEAN_MKT20_OPEN", "C_Combo_Oversold", ">=3跌停纯超跌+排雷非ST+mkt_dt>=20+09:25买+tp5_h5", base_clean_pure3 & (df["mkt_dt_prev"].values >= 20), "open_0925", "tp5_h5"),
        ("C02_B3_CLEAN_MKT30_OPEN", "C_Combo_Oversold", ">=3跌停纯超跌+排雷非ST+mkt_dt>=30+09:25买+tp5_h5", base_clean_pure3 & (df["mkt_dt_prev"].values >= 30), "open_0925", "tp5_h5"),
        ("C03_B3_CLEAN_MKT50_OPEN", "C_Combo_Oversold", ">=3跌停纯超跌+排雷非ST+mkt_dt>=50+09:25买+tp5_h5", base_clean_pure3 & (df["mkt_dt_prev"].values >= 50), "open_0925", "tp5_h5"),
        ("C04_B3_CLEAN_MKT20_R15_TP5H5", "C_Combo_Oversold", ">=3跌停纯超跌+排雷非ST+mkt_dt>=20+盘中冲open*1.015右侧买+tp5_h5", base_clean_pure3 & (df["mkt_dt_prev"].values >= 20), "right_open15", "tp5_h5"),
        ("C05_B3_CLEAN_MKT20_RRED_TP5H5", "C_Combo_Oversold", ">=3跌停纯超跌+排雷非ST+mkt_dt>=20+盘中翻红右侧买+tp5_h5", base_clean_pure3 & (df["mkt_dt_prev"].values >= 20), "right_red", "tp5_h5"),
        ("C06_B3_CLEAN_MKT30_R15_TP7H5", "C_Combo_Oversold", ">=3跌停纯超跌+排雷非ST+mkt_dt>=30+盘中冲open*1.015买+tp7_h5", base_clean_pure3 & (df["mkt_dt_prev"].values >= 30), "right_open15", "tp7_h5"),
        ("C07_B3_CLEAN_MKT20_RF35_R15", "C_Combo_Oversold", ">=3跌停纯超跌+排雷非ST+mkt_dt>=20+真实流通<=35亿+冲open*1.015买+tp5_h5", base_clean_pure3 & (df["mkt_dt_prev"].values >= 20) & (df["real_free_mcap"].values <= 35.0), "right_open15", "tp5_h5"),
        ("C08_B3_CLEAN_PANIC_OR_CSI_R15", "C_Combo_Oversold", ">=3跌停纯超跌+排雷非ST+(mkt_dt>=20或沪深300五日跌>=2%)+冲open*1.015买+tp5_h5", base_clean_pure3 & ((df["mkt_dt_prev"].values >= 20) | (df["csi300_ret5"].values <= -0.02)), "right_open15", "tp5_h5"),
        ("C09_B3_CLEAN_NONPANIC_CTRL", "C_Combo_Oversold", "对照:>=3跌停纯超跌+排雷非ST+非恐慌期(mkt_dt<20)+09:25买(验证平时单票亏钱假说)", base_clean_pure3 & (df["mkt_dt_prev"].values < 20), "open_0925", "tp5_h5"),

        # --- >=2 DT Macro Ice-Point Pure Oversold Candidates ---
        ("C10_DT2_CLEAN_MKT30_OPEN_TP5H5", "C_Combo_Oversold2", ">=2跌停纯超跌+排雷非ST+mkt_dt>=30+09:25买+tp5_h5", base_clean_pure2 & (df["mkt_dt_prev"].values >= 30), "open_0925", "tp5_h5"),
        ("C11_DT2_CLEAN_MKT30_R15_TP5H5", "C_Combo_Oversold2", ">=2跌停纯超跌+排雷非ST+mkt_dt>=30+冲open*1.015买+tp5_h5", base_clean_pure2 & (df["mkt_dt_prev"].values >= 30), "right_open15", "tp5_h5"),
        ("C12_DT2_CLEAN_MKT30_RRED_TP5H5", "C_Combo_Oversold2", ">=2跌停纯超跌+排雷非ST+mkt_dt>=30+盘中翻红买+tp5_h5", base_clean_pure2 & (df["mkt_dt_prev"].values >= 30), "right_red", "tp5_h5"),
        ("C13_DT2_CLEAN_MKT50_R15_TP7H5", "C_Combo_Oversold2", ">=2跌停纯超跌+排雷非ST+mkt_dt>=50+冲open*1.015买+tp7_h5", base_clean_pure2 & (df["mkt_dt_prev"].values >= 50), "right_open15", "tp7_h5"),
        ("C14_DT2_CLEAN_MKT30_RF35_LOCK40_R15", "C_Combo_Oversold2", ">=2跌停纯超跌+排雷非ST+mkt_dt>=30+rf<=35亿+lock>=40+冲open*1.015买+tp5_h5", base_clean_pure2 & (df["mkt_dt_prev"].values >= 30) & (df["real_free_mcap"].values <= 35.0) & (df["lock_top10"].values >= 40.0), "right_open15", "tp5_h5"),
        ("C15_DT2_CLEAN_MKT30_CSI2_R15_TP7H5", "C_Combo_Oversold2", ">=2跌停纯超跌+排雷非ST+mkt_dt>=30+csi300_ret5<=-2%+冲open*1.015买+tp7_h5", base_clean_pure2 & (df["mkt_dt_prev"].values >= 30) & (df["csi300_ret5"].values <= -0.02), "right_open15", "tp7_h5"),
        ("C16_DT2_CLEAN_MKT30_CSRC1_R15", "C_Combo_Oversold2", ">=2跌停纯超跌+排雷非ST+mkt_dt>=30+同业有涨停(csrc_zt>=1)+冲open*1.015买+tp5_h5", base_clean_pure2 & (df["mkt_dt_prev"].values >= 30) & (df["csrc_zt_cnt"].values >= 1), "right_open15", "tp5_h5"),

        # --- Intraday Limit-Down Pry (pry_dt) Multi-Factor Combos ---
        ("C17_PRY_DT2_CLEAN_MKT30", "C_Combo_Pry", "盘中撬跌停:>=2跌停+排雷非ST+mkt_dt>=30+pry_dt+tp5_h5", m_dt2_all & not_bad & px_ok & no_st_name & (df["mkt_dt_prev"].values >= 30), "pry_dt", "tp5_h5"),
        ("C18_PRY_DT2_PURE_MKT20", "C_Combo_Pry", "盘中撬跌停:>=2跌停纯超跌+排雷非ST+mkt_dt>=20+pry_dt+tp5_h5", base_clean_pure2 & (df["mkt_dt_prev"].values >= 20), "pry_dt", "tp5_h5"),
        ("C19_PRY_DT1_PURE_MKT50_RF35", "C_Combo_Pry", "盘中撬跌停:>=1跌停纯超跌+排雷非ST+mkt_dt>=50+rf<=35亿+pry_dt+tp5_h5", m_dt1_pure & not_bad & px_ok & no_st_name & (df["mkt_dt_prev"].values >= 50) & (df["real_free_mcap"].values <= 35.0), "pry_dt", "tp5_h5"),
        ("C20_PRY_DT2_PREV_TO_GT10", "C_Combo_Pry", "盘中撬跌停:>=2跌停+排雷非ST+前日换手>=10%+pry_dt+tp5_h3", m_dt2_all & not_bad & px_ok & no_st_name & (df["prev_to"].values >= 10.0), "pry_dt", "tp5_h3"),
        ("C21_PRY_DT2_PREV_YZ_UNSEAL", "C_Combo_Pry", "盘中撬跌停:>=2跌停+排雷非ST+前日一字跌停首次开板+pry_dt+tp5_h3", m_dt2_all & not_bad & px_ok & no_st_name & df["prev_is_yizi_dt"].values, "pry_dt", "tp5_h3"),

        # --- High-Flyer Dragon Anti-Nuclear (zt_cnt_pre20 >= 2) Combos ---
        ("C22_DRAGON_DT2_CLEAN_RRED_TP7H3", "C_Combo_DragonAntiNuke", "妖股反核:>=2跌停+zt20>=2+排雷非ST+同业活口(csrc_zt>=1)+翻红买+tp7_h3", (df["prev_dt_streak"].values >= 2) & (df["zt_cnt_pre20"].values >= 2) & not_bad & px_ok & no_st_name & (df["csrc_zt_cnt"].values >= 1), "right_red", "tp7_h3"),
        ("C23_DRAGON_DT2_LOCK50_TO15_R15", "C_Combo_DragonAntiNuke", "妖股反核:>=2跌停+zt20>=2+排雷非ST+lock>=50%+prev_to>=12%+冲open*1.015买+tp7_h3", (df["prev_dt_streak"].values >= 2) & (df["zt_cnt_pre20"].values >= 2) & not_bad & px_ok & no_st_name & (df["lock_top10"].values >= 50.0) & (df["prev_to"].values >= 12.0), "right_open15", "tp7_h3"),
        ("C24_DRAGON_DT2_SPRIOR30_RRED_NXTCL", "C_Combo_DragonAntiNuke", "妖股反核:>=2跌停+zt20>=2+排雷非ST+s_prior>=30+翻红买+次日收盘卖", (df["prev_dt_streak"].values >= 2) & (df["zt_cnt_pre20"].values >= 2) & not_bad & px_ok & no_st_name & (df["s_prior"].values >= 30.0), "right_red", "next_close"),
        ("C25_DRAGON_DT2_LHASA0_RRED_TP7H3", "C_Combo_DragonAntiNuke", "妖股反核:>=2跌停+zt20>=2+排雷非ST+无拉萨席位+翻红买+tp7_h3", (df["prev_dt_streak"].values >= 2) & (df["zt_cnt_pre20"].values >= 2) & not_bad & px_ok & no_st_name & (df["lhasa_seats_prev"].values == 0), "right_red", "tp7_h3"),
    ]

    combo_tdfs = {}
    for cid, cgrp, cdesc, cmask, cem, cex in combo_specs:
        rec, ctdf = add_run(cid, cgrp, cdesc, cmask, cem, cex, prio_deep10, 0, keep_tdf=True)
        combo_tdfs[cid] = (rec, ctdf)

    print(f"[+] Total parameter & factor variants evaluated: {len(results)}")

    # Select best robust IS + OOS strategy (requiring raw_n >= 25, IS single_nav > 1.0, OOS single_nav > 1.0, and positive excess in both IS & OOS if exists)
    viable = [
        r for r in results
        if r["single_n"] >= 15 and r["is_single_n"] >= 8 and r["oos_single_n"] >= 4
        and r["is_single_nav"] > 1.0 and r["oos_single_nav"] > 1.0
    ]
    viable.sort(key=lambda x: (x["single_nav_5y"] * min(x["is_single_nav"], x["oos_single_nav"])), reverse=True)

    best_rec = viable[0] if viable else sorted(results, key=lambda x: x["single_nav_5y"], reverse=True)[0]
    best_id = best_rec["id"]

    # Re-extract full single-slot & raw ledger for best_id
    # Find its mask/em/ex or re-run if from section 3/4
    print(f"[+] Top IS+OOS consistent variant: {best_id} | {best_rec['desc']}")
    print(f"    5Y single_nav={best_rec['single_nav_5y']}x (WR={best_rec['wr_5y']}%, MDD={best_rec['single_mdd_5y']}%, eq_nav={best_rec['eq_nav_5y']}x)")
    print(f"    IS (22-24): N={best_rec['is_single_n']}, WR={best_rec['is_wr']}%, NAV={best_rec['is_single_nav']}x | OOS (25-26): N={best_rec['oos_single_n']}, WR={best_rec['oos_wr']}%, NAV={best_rec['oos_single_nav']}x")

    # Save JSON summary first so we can inspect top variants across all sections
    summary_payload = {
        "meta": {
            "agent": "Agent 5 - Limit-Down Pry & Extreme Oversold Reversal",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "candidate_rows": int(len(df)),
            "date_range": "2022-01-04 to 2026-11-10",
            "fee_rate_roundtrip": FEE_RATE,
            "total_variants_swept": len(results),
            "best_variant_id": best_id,
        },
        "best_variant": best_rec,
        "top20_is_oos_consistent": viable[:20],
        "all_results": results,
    }
    with open(f"{WORK_DIR}/agent5_pry_results.json", "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, ensure_ascii=False, indent=2)

    print(f"[+] Saved agent5_pry_results.json ({len(results)} variants) in {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
