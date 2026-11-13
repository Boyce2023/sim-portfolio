#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Agent 4 & 5 Grand Factor Matrix & Parameter Grid Sweeper (First-Board 0-to-1 & Limit-Down Pry / Anti-Nuclear)
Strict D15 4-Pillar Evaluation:
  - 0.20% round-trip fee (FEE_RATE = 0.0020)
  - Strict T+1 delivery, limit-down yizi deferral to first tradable unsealed day
  - All touched-then-resealed/fried limit-up/down trades 100% included in denominator
  - 5-Window Multi-Period: Full 5Y (2022-2026), Ex-2025 4Y, Recent 3Y, Recent 1Y, Since Jul 2026
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

# =============================================================================
# PART 1: AGENT 5 HELPER FUNCTIONS (LIMIT-DOWN PRY / OVERSOLD REVERSAL)
# =============================================================================
PRY_EXIT_MODES = [
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

PRY_ENTRY_MODES = [
    "open_0925",      # 09:25 buyable_open
    "pry_dt",         # Open at limit down, intraday pry high > dt_px + 0.02 -> buy at dt_px + 0.02
    "right_open15",   # Buyable open, wait intraday surge >= open * 1.015 -> buy at round(open*1.015, 2)
    "right_red",      # Buyable open, wait intraday turn red high >= pre_c * 1.002 -> buy at pre_c*1.002
    "open_or_pry",    # Either buyable_open at 09:25 OR limit-down open pried intraday at dt_px + 0.02
]


def _is_locked_limit_down_bar(op, hi, lo, cl, pc, is_yz_dt_flag):
    if is_yz_dt_flag:
        return True
    if pc > 0 and (op == hi == lo == cl) and (cl / pc - 1.0 <= -0.044):
        return True
    return False


def sim_pry_exit(b, pos, buy_px, tp_pct, max_hold, mode):
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
            continue
        tradable_step += 1
        last_tradable_idx = idx
        op, hi, lo, cl, pc, dt_px = opens[idx], highs[idx], lows[idx], closes[idx], pre_cs[idx], dt_pxs[idx]
        if _is_locked_limit_down_bar(op, hi, lo, cl, pc, bool(is_yz_dts[idx])):
            continue

        adj_i = adjfs[idx]
        op_adj = op * adj_i
        hi_adj = hi * adj_i
        cl_adj = cl * adj_i

        if mode == "next_open":
            return dts[idx], op_adj / buy_adj - 1.0 - FEE_RATE, step, True
        elif mode == "next_close":
            if bool(is_dts[idx]) or (op == lo and abs(cl / (pc + 1e-9) - 0.95) <= 0.006):
                continue
            return dts[idx], cl_adj / buy_adj - 1.0 - FEE_RATE, step, False
        else:
            if tradable_step > max_hold:
                return dts[idx], op_adj / buy_adj - 1.0 - FEE_RATE, step, True
            tp_target = buy_adj * (1.0 + tp_pct)
            if op_adj >= tp_target:
                return dts[idx], op_adj / buy_adj - 1.0 - FEE_RATE, step, True
            if hi_adj >= tp_target:
                return dts[idx], tp_pct - FEE_RATE, step, False
            if tradable_step == max_hold:
                if bool(is_dts[idx]) or (hi <= pc * 1.055 and lo >= pc * 0.944 and abs(cl / (pc + 1e-9) - 0.95) <= 0.005 and cl == lo):
                    continue
                return dts[idx], cl_adj / buy_adj - 1.0 - FEE_RATE, step, False

    if last_tradable_idx < 0 and dts[pos] < "2026-10-20":
        return dts[-1], -0.70 - FEE_RATE, n - 1 - pos, False
    end_i = last_tradable_idx if last_tradable_idx >= 0 else (n - 1)
    ret = (closes[end_i] * adjfs[end_i]) / buy_adj - 1.0 - FEE_RATE
    if dts[end_i] < "2026-10-20" and _is_locked_limit_down_bar(
        opens[end_i], highs[end_i], lows[end_i], closes[end_i], pre_cs[end_i], bool(is_yz_dts[end_i])
    ):
        ret = min(ret, -0.70 - FEE_RATE)
    return dts[end_i], ret, max(1, end_i - pos), False


def precompute_pry_matrix(df: pd.DataFrame, cb: dict):
    t0 = time.time()
    N = len(df)
    pre = {}
    for em in PRY_ENTRY_MODES:
        pre[em] = {
            "valid": np.zeros(N, dtype=bool),
            "buy_at_open": np.zeros(N, dtype=bool),
            "buy_px": np.zeros(N, dtype=float),
            "day0_ret": np.zeros(N, dtype=float),
            "exits": {
                ex_name: {
                    "exit_date": np.empty(N, dtype=object),
                    "net_ret": np.zeros(N, dtype=float),
                    "hold_bars": np.zeros(N, dtype=int),
                    "exit_at_open": np.zeros(N, dtype=bool),
                }
                for ex_name, _, _, _ in PRY_EXIT_MODES
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

        em_specs = {}
        if real_buyable_open:
            em_specs["open_0925"] = (op, True)
            trig15 = np.round(op * 1.015, 2)
            if trig15 <= op:
                trig15 = op + 0.01
            if trig15 < zt_px - 0.005 and hi >= trig15:
                em_specs["right_open15"] = (trig15, False)
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

        px_cache = {}
        for em, (bpx, bao) in em_specs.items():
            d = pre[em]
            d["valid"][i] = True
            d["buy_at_open"][i] = bao
            d["buy_px"][i] = bpx
            d["day0_ret"][i] = cl / bpx - 1.0
            if bpx not in px_cache:
                res_ex = {}
                for ex_name, tp_p, mh, md in PRY_EXIT_MODES:
                    res_ex[ex_name] = sim_pry_exit(b, pos, bpx, tp_p, mh, md)
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
    print(f"[+] Agent 5: Precomputed 5 entries x 14 exits across {N:,} rows in {time.time()-t0:.2f}s")
    return pre


def eval_fast_pry(df: pd.DataFrame, pre: dict, mask: np.ndarray, entry_mode: str, exit_mode: str,
                   prio_arr: np.ndarray, max_per_day: int = 0) -> dict:
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


def compact_record_pry(vid: str, group: str, desc: str, entry_m: str, exit_m: str, ev: dict) -> dict:
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
        "strategy": "Pry_LimitDown",
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
    }


# =============================================================================
# PART 2: AGENT 4 HELPER FUNCTIONS (FIRST-BOARD 0-TO-1)
# =============================================================================
def precompute_firstboard_matrix(df: pd.DataFrame, cb: dict):
    t0 = time.time()
    N = len(df)
    codes = df["code"].values
    bds = df["buy_date"].values
    touch_zt = df["touch_zt_today"].values
    open_pct = df["open_pct"].values
    h_pct = df["h_pct"].values

    a_valid = touch_zt.astype(bool)
    a_bpx = np.zeros(N)
    a_next_op_ret = np.zeros(N)
    a_next_op_dt = np.empty(N, dtype=object)
    a_relay_ret = np.zeros(N)
    a_relay_dt = np.empty(N, dtype=object)

    b_valid = (open_pct >= 0.015) & (open_pct <= 0.060) & (h_pct >= 0.065)
    b_bpx = np.zeros(N)
    b_next_op_ret = np.zeros(N)
    b_next_op_dt = np.empty(N, dtype=object)
    b_relay_ret = np.zeros(N)
    b_relay_dt = np.empty(N, dtype=object)
    b_tp3h2_ret = np.zeros(N)
    b_tp3h2_dt = np.empty(N, dtype=object)

    for i in range(N):
        is_a, is_b = a_valid[i], b_valid[i]
        if not (is_a or is_b):
            continue
        c = codes[i]
        bd = bds[i]
        b = cb.get(c)
        if not b:
            a_valid[i] = b_valid[i] = False
            continue
        pos = b["date_to_pos"].get(bd)
        n = len(b["dts"])
        if pos is None or pos >= n - 1:
            a_valid[i] = b_valid[i] = False
            continue

        op = float(b["open"][pos])
        pre = float(b["pre_c"][pos])
        zt = float(b["zt_px"][pos])
        hi = float(b["high"][pos])
        adj_b = float(b["adjf"][pos])
        is_zt_day = bool(b["is_zt"][pos])

        k = pos + 1
        while k < n and b["is_yizi_dt"][k]:
            k += 1
        k = min(k, n - 1)
        next_op = float(b["open"][k])
        adj_k = float(b["adjf"][k])

        if not is_zt_day:
            re_dt = b["dts"][k]
            if b["close"][pos] < b["open"][pos] or next_op < float(b["pre_c"][k]) * 1.005:
                ep_re = next_op
                adj_re = adj_k
            else:
                ep_re = float(b["close"][k])
                adj_re = adj_k
        else:
            curr = pos + 1
            while curr < n and b["is_zt"][curr]:
                curr += 1
            while curr < n and b["is_yizi_dt"][curr]:
                curr += 1
            curr = min(curr, n - 1)
            re_dt = b["dts"][curr]
            ep_re = float(b["close"][curr])
            adj_re = float(b["adjf"][curr])

        if is_a:
            bpx_a = zt
            a_bpx[i] = bpx_a
            a_next_op_ret[i] = (next_op * adj_k) / (bpx_a * adj_b) * (1.0 - FEE_RATE) - 1.0
            a_next_op_dt[i] = b["dts"][k]
            a_relay_ret[i] = (ep_re * adj_re) / (bpx_a * adj_b) * (1.0 - FEE_RATE) - 1.0
            a_relay_dt[i] = re_dt

        if is_b:
            trig = min(zt, max(round(op * 1.012, 2), round(pre * 1.065, 2)))
            if hi < trig or trig >= zt - 0.01:
                b_valid[i] = False
            else:
                bpx_b = op if op >= trig else trig
                b_bpx[i] = bpx_b
                b_next_op_ret[i] = (next_op * adj_k) / (bpx_b * adj_b) * (1.0 - FEE_RATE) - 1.0
                b_next_op_dt[i] = b["dts"][k]
                b_relay_ret[i] = (ep_re * adj_re) / (bpx_b * adj_b) * (1.0 - FEE_RATE) - 1.0
                b_relay_dt[i] = re_dt

                target = bpx_b * 1.03
                ep_tp, dt_tp, adj_tp = float(b["close"][k]), b["dts"][k], adj_k
                for step in range(1, min(3, n - pos)):
                    idx = pos + step
                    if b["is_yizi_dt"][idx]:
                        continue
                    ar = float(b["adjf"][idx]) / adj_b
                    if float(b["open"][idx]) * ar >= target:
                        ep_tp, dt_tp, adj_tp = float(b["open"][idx]), b["dts"][idx], float(b["adjf"][idx])
                        break
                    if float(b["high"][idx]) * ar >= target:
                        ep_tp, dt_tp, adj_tp = target / ar, b["dts"][idx], float(b["adjf"][idx])
                        break
                    if step == 2:
                        ep_tp, dt_tp, adj_tp = float(b["close"][idx]), b["dts"][idx], float(b["adjf"][idx])
                b_tp3h2_ret[i] = (ep_tp * adj_tp) / (bpx_b * adj_b) * (1.0 - FEE_RATE) - 1.0
                b_tp3h2_dt[i] = dt_tp

    res = {
        "A": {
            "valid": a_valid,
            "bpx": a_bpx,
            "next_open": {"ret": a_next_op_ret, "exit_date": a_next_op_dt},
            "relay": {"ret": a_relay_ret, "exit_date": a_relay_dt},
        },
        "B": {
            "valid": b_valid,
            "bpx": b_bpx,
            "next_open": {"ret": b_next_op_ret, "exit_date": b_next_op_dt},
            "relay": {"ret": b_relay_ret, "exit_date": b_relay_dt},
            "tp3_h2": {"ret": b_tp3h2_ret, "exit_date": b_tp3h2_dt},
        },
    }
    print(f"[+] Agent 4: Precomputed Buy A & B across {N:,} rows in {time.time()-t0:.2f}s")
    return res


def eval_fast_fb(df: pd.DataFrame, pre_fb: dict, mask: np.ndarray, buy_type: str, exit_type: str,
                 prio_arr: np.ndarray) -> dict:
    sub_m = pre_fb[buy_type]["valid"] & mask
    idx = np.flatnonzero(sub_m)
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
            "fried_rate_pct": 0.0,
            "_tdf": pd.DataFrame(),
        }

    ex_d = pre_fb[buy_type][exit_type]
    tdf = pd.DataFrame({
        "code": df["code"].values[idx],
        "name": df["name"].values[idx],
        "buy_date": df["buy_date"].values[idx],
        "exit_date": ex_d["exit_date"][idx],
        "net_ret": ex_d["ret"][idx],
        "hold_bars": 1,
        "priority_score": prio_arr[idx],
        "is_zt_today": df["is_zt_today"].values[idx],
    })

    d15 = evaluate_d15_full(tdf)
    is_m = _slice_metrics(tdf[(tdf["buy_date"] >= "2022-01-04") & (tdf["buy_date"] <= "2024-12-31")], "2022-01-04", "2024-12-31")
    oos_m = _slice_metrics(tdf[(tdf["buy_date"] >= "2025-01-02") & (tdf["buy_date"] <= "2026-11-10")], "2025-01-02", "2026-11-10")

    raw_rets = tdf["net_ret"].values
    fried_rate = float((~tdf["is_zt_today"]).mean() * 100.0)

    return {
        "d15": d15,
        "is_22_24": is_m,
        "oos_25_26": oos_m,
        "raw_mean_pct": round(float(raw_rets.mean() * 100.0), 2),
        "raw_wr_pct": round(float((raw_rets > 0).mean() * 100.0), 2),
        "fried_rate_pct": round(fried_rate, 2),
        "_tdf": tdf,
    }


def compact_record_fb(vid: str, group: str, desc: str, buy_type: str, exit_type: str, ev: dict) -> dict:
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
        "strategy": "FirstBoard_0to1",
        "desc": desc,
        "buy_type": buy_type,
        "exit_type": exit_type,
        "raw_n": f5["raw_n"],
        "raw_wr": ev["raw_wr_pct"],
        "raw_mean_pct": ev["raw_mean_pct"],
        "fried_rate_pct": ev["fried_rate_pct"],
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
        "ex2025_nav": ex25["single_nav"],
        "r3y_nav": r3["single_nav"],
        "r1y_nav": r1["single_nav"],
        "jul26_nav": jul26["single_nav"],
        "is_single_nav": ism["single_nav"],
        "is_wr": ism["wr"],
        "oos_single_nav": oosm["single_nav"],
        "oos_wr": oosm["wr"],
    }


# =============================================================================
# MAIN SWEEP EXECUTION
# =============================================================================
def main():
    t_start = time.time()
    print("[+] Loading input data...")
    df_pry = pd.read_parquet(f"{WORK_DIR}/cand_pry_limitdown.parquet")
    df_fb = pd.read_parquet(f"{WORK_DIR}/cand_0to1_firstboard.parquet")
    with open(f"{WORK_DIR}/code_bars_5y.pkl", "rb") as f:
        cb = pickle.load(f)["code_bars"]

    # -------------------------------------------------------------------------
    # PART 1: AGENT 5 (LIMIT-DOWN PRY / OVERSOLD REVERSAL) SWEEP
    # -------------------------------------------------------------------------
    pre_pry = precompute_pry_matrix(df_pry, cb)
    prio_deep10 = -df_pry["ret_pre10"].values.astype(float)
    pry_results = []
    saved_tdfs_pry = {}

    def add_pry(vid, grp, desc, mask, em="open_0925", ex="tp5_h5", prio=prio_deep10, max_d=0, save_tdf=False):
        ev = eval_fast_pry(df_pry, pre_pry, mask, em, ex, prio, max_d)
        rec = compact_record_pry(vid, grp, desc, em, ex, ev)
        pry_results.append(rec)
        if save_tdf or vid in ["U3_DT2_PRY__F12_csi20_le_m5", "M_DT2_PURE_OPEN_NOT_BAD", "B01_B3_EXACT_ALL"]:
            saved_tdfs_pry[vid] = ev["_tdf"]
        return rec

    # Section 1: Bucket 3 replication & baselines
    m_b3 = (df_pry["prev_dt_streak"].values >= 3) & (df_pry["zt_cnt_pre20"].values == 0)
    m_dt3_all = (df_pry["prev_dt_streak"].values >= 3)
    m_dt3_akill = (df_pry["prev_dt_streak"].values >= 3) & (df_pry["zt_cnt_pre20"].values >= 1)
    m_dt2_pure = (df_pry["prev_dt_streak"].values >= 2) & (df_pry["zt_cnt_pre20"].values == 0)
    m_dt2_all = (df_pry["prev_dt_streak"].values >= 2)
    m_dt2_akill = (df_pry["prev_dt_streak"].values >= 2) & (df_pry["zt_cnt_pre20"].values >= 1)
    m_dt1_all = (df_pry["prev_dt_streak"].values >= 1)

    add_pry("B01_B3_EXACT_ALL", "1_Baseline", "桶3精确复刻(>=3跌停+前20日0涨停+09:25非一字跌停买+5日摸+5%止盈,全样本)", m_b3, "open_0925", "tp5_h5", prio_deep10, 0, save_tdf=True)
    add_pry("B02_B3_EXACT_TOP2", "1_Baseline", "桶3精确复刻(同日多只取10日跌幅最深前2只等权,手册原版)", m_b3, "open_0925", "tp5_h5", prio_deep10, 2)
    add_pry("B03_DT3_ALL_OPEN", "1_Baseline", ">=3连跌停(不限前20日涨停)+09:25非一字跌停买+5日摸+5%", m_dt3_all, "open_0925", "tp5_h5")
    add_pry("B04_DT3_AKILL_OPEN", "1_Baseline", ">=3连跌停+妖股A杀(zt_cnt_pre20>=1)+09:25买+5日摸+5%", m_dt3_akill, "open_0925", "tp5_h5")
    add_pry("B05_PRY_DT3_PURE", "1_Baseline", "盘中跌停撬板(>=3连跌停+纯超跌zt20==0+跌停开盘撬开买)", m_b3, "pry_dt", "tp5_h5")
    add_pry("B06_PRY_DT3_ALL", "1_Baseline", "盘中跌停撬板(>=3连跌停全量+跌停开盘撬开买)", m_dt3_all, "pry_dt", "tp5_h5")
    add_pry("B07_PRY_DT3_AKILL", "1_Baseline", "盘中跌停撬板(>=3连跌停+妖股A杀zt20>=1+跌停开盘撬开买)", m_dt3_akill, "pry_dt", "tp5_h5")
    add_pry("B08_PRY_DT2_PURE", "1_Baseline", "盘中跌停撬板(>=2连跌停+纯超跌zt20==0+跌停开盘撬开买)", m_dt2_pure, "pry_dt", "tp5_h5")
    add_pry("B09_PRY_DT2_ALL", "1_Baseline", "盘中跌停撬板(>=2连跌停全量+跌停开盘撬开买)", m_dt2_all, "pry_dt", "tp5_h5")
    add_pry("B10_PRY_DT2_AKILL", "1_Baseline", "盘中跌停撬板(>=2连跌停+妖股A杀zt20>=1+跌停开盘撬开买)", m_dt2_akill, "pry_dt", "tp5_h5")
    add_pry("B14_DT2_PURE_OPEN", "1_Baseline", ">=2连跌停次日反核(纯超跌zt20==0+09:25非一字跌停买)", m_dt2_pure, "open_0925", "tp5_h5")
    add_pry("B15_DT2_ALL_OPEN", "1_Baseline", ">=2连跌停次日反核(全量+09:25非一字跌停买)", m_dt2_all, "open_0925", "tp5_h5")
    add_pry("B16_DT2_EXACT_PURE_OPEN", "1_Baseline", "==2连跌停次日反核(纯超跌zt20==0+09:25非一字跌停买)", (df_pry["prev_dt_streak"].values == 2) & (df_pry["zt_cnt_pre20"].values == 0), "open_0925", "tp5_h5")
    add_pry("B17_DT2_AKILL_OPEN", "1_Baseline", ">=2连跌停次日反核(妖股A杀zt20>=1+09:25非一字跌停买)", m_dt2_akill, "open_0925", "tp5_h5")

    # Section 2: Notice_bad, Penny Stock, ST
    not_bad = ~df_pry["notice_bad"].values
    px_ok = df_pry["open_px_raw"].values >= 2.0
    no_st = ~df_pry["is_st_name"].values
    clean_dt2 = m_dt2_pure & not_bad & px_ok & no_st
    clean_dt3 = m_b3 & not_bad & px_ok & no_st

    add_pry("M_DT2_PURE_OPEN_NOT_BAD", "2_Landmine", ">=2跌停纯超跌+09:25买+剔除暴雷公告(not notice_bad)", m_dt2_pure & not_bad, "open_0925", "tp5_h5", save_tdf=True)
    add_pry("M_DT2_PURE_OPEN_CLEAN", "2_Landmine", ">=2跌停纯超跌+09:25买+not_bad+股价>=2+非ST", clean_dt2, "open_0925", "tp5_h5", save_tdf=True)
    add_pry("M_DT3_B3_CLEAN", "2_Landmine", "桶3升级版(>=3跌停纯超跌+not_bad+股价>=2+非ST)", clean_dt3, "open_0925", "tp5_h5", save_tdf=True)

    # Section 3: Univariate factor sweep across all 32 factors on U2 (open) & U3 (pry)
    factor_slices_pry = [
        ("F01_lock10_ge40", "lock_top10 >= 40%", df_pry["lock_top10"].values >= 40.0),
        ("F01_lock10_ge50", "lock_top10 >= 50%", df_pry["lock_top10"].values >= 50.0),
        ("F01_lock10_ge60", "lock_top10 >= 60%", df_pry["lock_top10"].values >= 60.0),
        ("F02_lock5_ge35", "lock_big5 >= 35%", df_pry["lock_big5"].values >= 35.0),
        ("F03_rfmcap_le20", "real_free_mcap <= 20亿", df_pry["real_free_mcap"].values <= 20.0),
        ("F03_rfmcap_le35", "real_free_mcap <= 35亿", df_pry["real_free_mcap"].values <= 35.0),
        ("F03_rfmcap_le50", "real_free_mcap <= 50亿", df_pry["real_free_mcap"].values <= 50.0),
        ("F04_mcap_le30", "mcap <= 30亿", df_pry["mcap"].values <= 30.0),
        ("F04_mcap_30_100", "mcap 30~100亿", (df_pry["mcap"].values > 30.0) & (df_pry["mcap"].values <= 100.0)),
        ("F05_prev_to_lt2", "prev_to < 2%", df_pry["prev_to"].values < 2.0),
        ("F05_prev_to_lt5", "prev_to < 5%", df_pry["prev_to"].values < 5.0),
        ("F05_prev_to_gt10", "prev_to >= 10%", df_pry["prev_to"].values >= 10.0),
        ("F06_prev_yz_dt_T", "prev_is_yizi_dt == True (前日一字跌停开板)", df_pry["prev_is_yizi_dt"].values),
        ("F07_prev_real_to_gt20", "prev_real_to > 20%", df_pry["prev_real_to"].values > 20.0),
        ("F08_prev_vr_lt06", "prev_vol_ratio < 0.6", df_pry["prev_vol_ratio"].values < 0.60),
        ("F08_prev_vr_gt12", "prev_vol_ratio > 1.2", df_pry["prev_vol_ratio"].values > 1.20),
        ("F09_prev_amt_gt3e8", "prev_amt >= 3亿", df_pry["prev_amt"].values >= 3e8),
        ("F10_mkt_dt_ge10", "mkt_dt_prev >= 10", df_pry["mkt_dt_prev"].values >= 10),
        ("F10_mkt_dt_ge20", "mkt_dt_prev >= 20 (全场冰点)", df_pry["mkt_dt_prev"].values >= 20),
        ("F10_mkt_dt_ge30", "mkt_dt_prev >= 30 (极端恐慌)", df_pry["mkt_dt_prev"].values >= 30),
        ("F10_mkt_dt_ge50", "mkt_dt_prev >= 50 (股灾级恐慌)", df_pry["mkt_dt_prev"].values >= 50),
        ("F11_csi5_le_m2", "csi300_ret5 <= -2%", df_pry["csi300_ret5"].values <= -0.02),
        ("F11_csi5_le_m4", "csi300_ret5 <= -4%", df_pry["csi300_ret5"].values <= -0.04),
        ("F12_csi20_le_m5", "csi300_ret20 <= -5% (中期大跌)", df_pry["csi300_ret20"].values <= -0.05),
        ("F13_csi_amp20_ge8", "csi300_amp20 >= 8%", df_pry["csi300_amp20"].values >= 0.08),
        ("F14_fb_open_lt0", "mkt_fb_open_avg < 0%", df_pry["mkt_fb_open_avg"].values < 0.0),
        ("F15_promo_lt15", "mkt_promo_1to2_5d < 15%", df_pry["mkt_promo_1to2_5d"].values < 0.15),
        ("F16_seal_lt55", "mkt_seal_rate_prev < 55%", df_pry["mkt_seal_rate_prev"].values < 0.55),
        ("F17_roll20_ho_ge45", "roll20_ho_zt >= 45%", df_pry["roll20_ho_zt"].values >= 0.45),
        ("F18_max_board_ge5", "mkt_max_board_prev >= 5", df_pry["mkt_max_board_prev"].values >= 5),
        ("F19_prev3b_dt_ge2", "prev_3b_dt_cnt >= 2", df_pry["prev_3b_dt_cnt"].values >= 2),
        ("F20_brk_dt_ge40", "prev_break_dt_rate_10d >= 40%", df_pry["prev_break_dt_rate_10d"].values >= 0.40),
        ("F22_mkt_zt_lt35", "mkt_zt_prev < 35", df_pry["mkt_zt_prev"].values < 35),
        ("F23_mkt_yizi_ge8", "mkt_yizi_cnt >= 8", df_pry["mkt_yizi_cnt"].values >= 8),
        ("F24_sprior_gt0", "s_prior > 0", df_pry["s_prior"].values > 0.0),
        ("F24_sprior_ge35", "s_prior >= 35", df_pry["s_prior"].values >= 35.0),
        ("F25_pelo_gt105", "p_elo > 105", df_pry["p_elo"].values > 105.0),
        ("F26_rk_theme_le3", "rk_theme <= 3", df_pry["rk_theme"].values <= 3),
        ("F27_psz_ge3", "p_sz >= 3", df_pry["p_sz"].values >= 3),
        ("F30_csrc_zt_ge1", "csrc_zt_cnt >= 1", df_pry["csrc_zt_cnt"].values >= 1),
        ("F30_csrc_zt_ge2", "csrc_zt_cnt >= 2", df_pry["csrc_zt_cnt"].values >= 2),
        ("F31_dd20_le68", "dd20 <= 0.68", df_pry["dd20"].values <= 0.68),
        ("F31_ret10_le_m30", "ret_pre10 <= -30%", df_pry["ret_pre10"].values <= -0.30),
        ("F32_lhasa_0", "lhasa_seats_prev == 0", df_pry["lhasa_seats_prev"].values == 0),
        ("F33_has_ir_8d", "has_ir_8d == True", df_pry["has_ir_8d"].values),
        ("F34_notice_pos", "notice_hard/ma/earn", df_pry["notice_hard"].values | df_pry["notice_ma"].values | df_pry["notice_earn"].values),
    ]

    for f_code, f_desc, f_m in factor_slices_pry:
        add_pry(f"U2_DT2_OPEN__{f_code}", "3_Univariate_Open", f"DT2_OPEN + {f_desc}", m_dt2_pure & not_bad & f_m, "open_0925", "tp5_h5")
        add_pry(f"U3_DT2_PRY__{f_code}", "3_Univariate_Pry", f"DT2_PRY + {f_desc}", m_dt2_all & not_bad & f_m, "pry_dt", "tp5_h5")
        add_pry(f"U1_B3_OPEN__{f_code}", "3_Univariate_B3", f"B3_OPEN + {f_desc}", m_b3 & not_bad & f_m, "open_0925", "tp5_h5")

    # Section 4: Grid sweeps (Entry x Exit) on 3 universes (5 x 14 = 70 x 2 = 140 combos)
    for em in PRY_ENTRY_MODES:
        for ex_name, _, _, _ in PRY_EXIT_MODES:
            add_pry(f"GRID_PANIC__{em}__{ex_name}", "4_Grid_Panic", f"两连跌停排雷冰点(mkt_dt>=20) | {em} | {ex_name}", clean_dt2 & (df_pry["mkt_dt_prev"].values >= 20), em, ex_name)
            add_pry(f"GRID_B3_CLEAN__{em}__{ex_name}", "4_Grid_B3", f"桶3排雷(not_bad) | {em} | {ex_name}", clean_dt3, em, ex_name)

    print(f"[+] Agent 5 evaluated {len(pry_results)} variants.")

    # -------------------------------------------------------------------------
    # PART 2: AGENT 4 (FIRST-BOARD 0-TO-1) SWEEP
    # -------------------------------------------------------------------------
    pre_fb = precompute_firstboard_matrix(df_fb, cb)
    prio_sprior = df_fb["s_prior"].values.astype(float)
    fb_results = []
    saved_tdfs_fb = {}

    def add_fb(vid, grp, desc, mask, btype="B", ex="relay", prio=prio_sprior, save_tdf=False):
        ev = eval_fast_fb(df_fb, pre_fb, mask, btype, ex, prio)
        rec = compact_record_fb(vid, grp, desc, btype, ex, ev)
        fb_results.append(rec)
        if save_tdf or vid in ["FB_A01_DABAN_RELAY_ALL", "FB_B02_HALFWAY_NEXTOP_ALL", "FB_B__prev_to_lt5_tp3h2", "FB_COMBO_THEME_IR8D_NEXTOP"]:
            saved_tdfs_fb[vid] = ev["_tdf"]
        return rec

    # Baselines for Buy A & Buy B
    m_all_fb = np.ones(len(df_fb), dtype=bool)
    add_fb("FB_A01_DABAN_RELAY_ALL", "1_FB_Baseline", "打首板排/扫板基准(全量样本,含全部炸板,连板持有断板卖)", m_all_fb, "A", "relay", save_tdf=True)
    add_fb("FB_A02_DABAN_NEXTOP_ALL", "1_FB_Baseline", "打首板排/扫板基准(全量样本,次日开盘卖)", m_all_fb, "A", "next_open")
    add_fb("FB_B01_HALFWAY_RELAY_ALL", "1_FB_Baseline", "半路右侧点火基准(开盘1.5%~6.0%,摸6.5%买,连板持有断板卖)", m_all_fb, "B", "relay")
    add_fb("FB_B02_HALFWAY_NEXTOP_ALL", "1_FB_Baseline", "半路右侧点火基准(次日开盘卖,全量样本)", m_all_fb, "B", "next_open", save_tdf=True)
    add_fb("FB_B03_HALFWAY_TP3H2_ALL", "1_FB_Baseline", "半路右侧点火基准(次日起摸+3%止盈或第2日收盘卖)", m_all_fb, "B", "tp3_h2")

    clean_fb = ~df_fb["notice_bad"].values

    fb_factor_slices = [
        ("clean_brk60", "60日平台首突(clean_brk60)", df_fb["clean_brk60"].values),
        ("dd20_le82", "回撤适中(dd20 <= 0.82)", df_fb["dd20"].values <= 0.82),
        ("notice_hard_ma", "硬催化/重组公告(notice_hard or notice_ma)", df_fb["notice_hard"].values | df_fb["notice_ma"].values),
        ("has_ir_8d", "近8日机构调研(has_ir_8d)", df_fb["has_ir_8d"].values),
        ("sprior_ge35", "主线题材先验(s_prior >= 35)", df_fb["s_prior"].values >= 35.0),
        ("sprior_ge50", "强主线题材先验(s_prior >= 50)", df_fb["s_prior"].values >= 50.0),
        ("sprior_ge70", "绝对主线断层(s_prior >= 70)", df_fb["s_prior"].values >= 70.0),
        ("pelo_gt105", "强势题材Elo(p_elo > 105)", df_fb["p_elo"].values > 105.0),
        ("csrc_zt_ge3", "同业昨日>=3家涨停(csrc_zt_cnt >= 3)", df_fb["csrc_zt_cnt"].values >= 3),
        ("csrc_zt_ge5", "同业昨日>=5家涨停(csrc_zt_cnt >= 5)", df_fb["csrc_zt_cnt"].values >= 5),
        ("lock10_ge50", "十大股东锁仓>=50%", df_fb["lock_top10"].values >= 50.0),
        ("rfmcap_le35", "真实流通市值<=35亿", df_fb["real_free_mcap"].values <= 35.0),
        ("rfmcap_le25", "真实流通市值<=25亿(小盘)", df_fb["real_free_mcap"].values <= 25.0),
        ("promo_ge18_max5", "连板顺风(promo>=18% & max_board>=5)", (df_fb["mkt_promo_1to2_5d"].values >= 0.18) & (df_fb["mkt_max_board_prev"].values >= 5)),
        ("dom_gap_ge20", "大主线断层日(dom_gap >= 20)", df_fb["dom_gap"].values >= 20.0),
        ("lhasa_0", "前日龙虎榜无拉萨席位", df_fb["lhasa_seats_prev"].values == 0),
        ("prev_to_lt5", "前日换手<5%(首板放量启动)", df_fb["prev_to"].values < 5.0),
        ("prev_to_gt10", "前日换手>10%(活跃温床)", df_fb["prev_to"].values > 10.0),
        ("mkt_dt_lt10", "市场情绪非恐慌(mkt_dt < 10)", df_fb["mkt_dt_prev"].values < 10),
        ("mkt_dt_ge20", "市场逆势独立首板(mkt_dt >= 20)", df_fb["mkt_dt_prev"].values >= 20),
        ("csi5_gt0", "大盘5日上升期(csi5 > 0)", df_fb["csi300_ret5"].values > 0.0),
    ]

    for f_code, f_desc, f_m in fb_factor_slices:
        add_fb(f"FB_A__{f_code}_relay", "2_FB_Factor_A", f"打首板 + {f_desc} (断板卖)", clean_fb & f_m, "A", "relay")
        add_fb(f"FB_A__{f_code}_nextop", "2_FB_Factor_A", f"打首板 + {f_desc} (次日开盘卖)", clean_fb & f_m, "A", "next_open")
        add_fb(f"FB_B__{f_code}_relay", "3_FB_Factor_B", f"半路点火 + {f_desc} (断板卖)", clean_fb & f_m, "B", "relay")
        add_fb(f"FB_B__{f_code}_nextop", "3_FB_Factor_B", f"半路点火 + {f_desc} (次日开盘卖)", clean_fb & f_m, "B", "next_open")
        add_fb(f"FB_B__{f_code}_tp3h2", "3_FB_Factor_B", f"半路点火 + {f_desc} (摸+3%止盈)", clean_fb & f_m, "B", "tp3_h2", save_tdf=(f_code == "prev_to_lt5"))

    combo_fb = [
        ("FB_COMBO_THEME_RF35_ENV", "4_FB_Combos", "半路点火+主线s_prior>=35+真实流通<=35亿+连板环境顺风", clean_fb & (df_fb["s_prior"].values >= 35) & (df_fb["real_free_mcap"].values <= 35) & (df_fb["mkt_promo_1to2_5d"].values >= 0.18), "B", "next_open"),
        ("FB_COMBO_THEME_CSRC3_NEXTOP", "4_FB_Combos", "半路点火+主线s_prior>=35+同业>=3家涨停+次日开盘卖", clean_fb & (df_fb["s_prior"].values >= 35) & (df_fb["csrc_zt_cnt"].values >= 3), "B", "next_open"),
        ("FB_COMBO_THEME_IR8D_NEXTOP", "4_FB_Combos", "半路点火+主线s_prior>=30+近8日机构调研+次日开盘卖", clean_fb & (df_fb["s_prior"].values >= 30) & (df_fb["has_ir_8d"].values), "B", "next_open"),
        ("FB_COMBO_NOTICE_HARD_NEXTOP", "4_FB_Combos", "半路点火+硬催化公告(notice_hard/ma)+次日开盘卖", clean_fb & (df_fb["notice_hard"].values | df_fb["notice_ma"].values), "B", "next_open"),
        ("FB_COMBO_BRK60_DD82_RELAY", "4_FB_Combos", "打首板+60日平台首突+回撤适中(dd20<=0.82)+断板卖", clean_fb & (df_fb["clean_brk60"].values) & (df_fb["dd20"].values <= 0.82), "A", "relay"),
    ]
    for cid, cgrp, cdesc, cmask, cbtype, cex in combo_fb:
        add_fb(cid, cgrp, cdesc, cmask, cbtype, cex, save_tdf=True)

    print(f"[+] Agent 4 evaluated {len(fb_results)} variants.")

    # -------------------------------------------------------------------------
    # PART 3: SELECT BEST MODELS & SAVE LEDGERS & JSON
    # -------------------------------------------------------------------------
    best_pry_elite = [r for r in pry_results if r["id"] == "U3_DT2_PRY__F12_csi20_le_m5"][0]
    best_pry_expanded = [r for r in pry_results if r["id"] == "M_DT2_PURE_OPEN_NOT_BAD"][0]

    tdf_pry_best = saved_tdfs_pry.get("U3_DT2_PRY__F12_csi20_le_m5")
    if tdf_pry_best is not None and not tdf_pry_best.empty:
        taken_pry, _, _, _ = _sim_single_slot(tdf_pry_best)
        tdf_pry_out = pd.DataFrame(taken_pry)
        tdf_pry_out.to_csv(f"{WORK_DIR}/agent5_pry_best_ledger.csv", index=False, encoding="utf-8-sig")
        print(f"[+] Saved agent5_pry_best_ledger.csv with {len(tdf_pry_out)} single-slot trades.")

    best_fb_rec = sorted(fb_results, key=lambda x: x["single_nav_5y"], reverse=True)[0]
    tdf_fb_best = saved_tdfs_fb.get(best_fb_rec["id"])
    if tdf_fb_best is None or tdf_fb_best.empty:
        tdf_fb_best = saved_tdfs_fb.get("FB_A01_DABAN_RELAY_ALL", pd.DataFrame())
    if not tdf_fb_best.empty:
        taken_fb, _, _, _ = _sim_single_slot(tdf_fb_best)
        tdf_fb_out = pd.DataFrame(taken_fb)
        tdf_fb_out.to_csv(f"{WORK_DIR}/agent4_0to1_best_ledger.csv", index=False, encoding="utf-8-sig")
        print(f"[+] Saved agent4_0to1_best_ledger.csv with {len(tdf_fb_out)} single-slot trades.")

    summary_payload = {
        "meta": {
            "title": "Agent 4 & 5 Grand Factor Matrix & Parameter Grid Sweeper",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "fee_rate_roundtrip": FEE_RATE,
            "total_pry_variants": len(pry_results),
            "total_fb_variants": len(fb_results),
            "total_variants": len(pry_results) + len(fb_results),
            "runtime_seconds": round(time.time() - t_start, 2),
        },
        "agent5_pry": {
            "best_elite": best_pry_elite,
            "best_expanded": best_pry_expanded,
            "baseline_bucket3": [r for r in pry_results if r["id"] == "B01_B3_EXACT_ALL"][0],
            "top10": sorted(pry_results, key=lambda x: x["single_nav_5y"], reverse=True)[:10],
            "all_results": pry_results,
        },
        "agent4_firstboard": {
            "best_variant": best_fb_rec,
            "baseline_daban": [r for r in fb_results if r["id"] == "FB_A01_DABAN_RELAY_ALL"][0],
            "baseline_halfway": [r for r in fb_results if r["id"] == "FB_B02_HALFWAY_NEXTOP_ALL"][0],
            "top10": sorted(fb_results, key=lambda x: x["single_nav_5y"], reverse=True)[:10],
            "all_results": fb_results,
        },
    }

    with open(f"{WORK_DIR}/agent45_firstboard_and_pry_results.json", "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, ensure_ascii=False, indent=2)

    print(f"[+] Saved agent45_firstboard_and_pry_results.json ({len(pry_results)+len(fb_results)} total variants) in {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
