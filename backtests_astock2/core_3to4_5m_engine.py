#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三进四 5 分钟级零未来函数真实时序撮合引擎（含盘中先到先得抢槽位 + 逐日持仓无偷看涨停重演）
"""
import json
import pickle
import numpy as np
import pandas as pd

FEE_RATE = 0.0020
SANDBOX_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab"
MATRIX_DIR = f"{SANDBOX_DIR}/grand_factor_matrix_20261112"
BARS_5M_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet"

with open(f"{SANDBOX_DIR}/index_klines_5y_cache.json", "r", encoding="utf-8") as _f:
    CSI300_MAP = json.load(_f)["sh000300"]


def csi300_ret(start_dt: str, end_dt: str) -> float:
    dts = sorted(k for k in CSI300_MAP.keys() if start_dt <= k <= end_dt)
    if len(dts) < 2:
        return 0.0
    prev_dts = [k for k in CSI300_MAP.keys() if k < dts[0]]
    base_dt = max(prev_dts) if prev_dts else dts[0]
    return float(CSI300_MAP[dts[-1]] / CSI300_MAP[base_dt] - 1.0)


def load_3to4_universe_and_5m():
    df_cands = pd.read_parquet(f"{MATRIX_DIR}/cand_3to4.parquet")
    with open(f"{MATRIX_DIR}/code_bars_5y.pkl", "rb") as f:
        code_bars = pickle.load(f)["code_bars"]

    df_5m = pd.read_parquet(BARS_5M_PATH)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_map = {}
    for (c6, dt_s), grp in df_5m.groupby(["c6", "date"], sort=False):
        bars_5m_map[(c6, dt_s)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)

    # Mark clean 10cm mainboard non-ST
    is_10cm_non_st = []
    for r in df_cands.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        bd = str(r.buy_date)
        cb = code_bars.get(c6)
        if cb is None or (not c6.startswith(("00", "60"))) or ("ST" in str(r.name).upper()):
            is_10cm_non_st.append(False)
            continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or cb["pre_c"][pos] <= 0 or (cb["zt_px"][pos] / cb["pre_c"][pos] < 1.085):
            is_10cm_non_st.append(False)
            continue
        is_10cm_non_st.append(True)
    df_cands["is_10cm_non_st"] = is_10cm_non_st
    return df_cands, code_bars, bars_5m_map


def sim_buy_5m(c6: str, bd: str, cb: dict, pos: int, bars_5m_map: dict, buy_mode: str):
    """Return (buy_px, buy_hhmm) or (None, None) using real 5m bars."""
    op = float(cb["open"][pos])
    pc = float(cb["pre_c"][pos])
    zt = float(cb["zt_px"][pos])
    if op >= zt - 0.005:
        return None, None
    if buy_mode == "open":
        return op, 925

    # Parse trigger params: (min_pct_vs_pc, min_add_vs_op, max_hhmm)
    cfg = {
        "touch7_all": (1.070, 0.0, 1500),
        "touch7_1130": (1.070, 0.0, 1130),
        "touch7_1030": (1.070, 0.0, 1030),
        "touch65_all": (1.065, 0.0, 1500),
        "touch65_1130": (1.065, 0.0, 1130),
        "touch60_1130": (1.060, 0.0, 1130),
        "dyn65_12_1130": (1.065, 0.012, 1130),
        "dyn60_08_1130": (1.060, 0.008, 1130),
    }[buy_mode]
    trig = max(pc * cfg[0], op * (1.0 + cfg[1]))
    max_hhmm = cfg[2]
    if trig >= zt - 0.005:
        return None, None
    if op >= trig:
        return op, 925

    arr = bars_5m_map.get((c6, bd))
    if arr is None or len(arr) == 0:
        return None, None
    for row in arr:
        hhmm = int(row[0])
        if hhmm > max_hhmm:
            break
        bo, bh, bl = row[1], row[2], row[3]
        if bl >= zt - 0.005:
            continue
        if bh >= trig:
            fill_px = max(bo, trig)
            if fill_px < zt - 0.005:
                return float(fill_px), hhmm
    return None, None


def _sim_day_intraday_exit_5m(arr, op_k: float, pre_c_k: float, cl_k: float, zt_k: float, dt_k: float, is_zt_eod: bool, exit_mode: str):
    """
    Strictly causal 5m intraday simulation on holding day k >= pos + 1 (after Day4 sealed ZT).
    Returns (did_exit: bool, sell_px: float, sell_hhmm: int).
    Zero EOD is_zt lookahead: intraday rules fire in real time even if stock later reseals ZT!
    """
    op_pct = op_k / pre_c_k - 1.0

    # Mode 1: Strict Causal Feishu 4-Branch on 5m bars (exposes real shakeouts on low-open weak-to-strong!)
    if exit_mode == "feishu_5m_strict":
        if arr is not None and len(arr) > 0:
            if op_pct < 0.015:
                for row in arr:
                    hhmm, bo, bh, bl = int(row[0]), row[1], row[2], row[3]
                    if bh <= dt_k + 0.005:
                        continue
                    if bh >= pre_c_k * 1.03:
                        return True, float(max(bo, pre_c_k * 1.03)), hhmm
            else:
                surged_109 = (op_k >= pre_c_k * 1.09)
                for row in arr:
                    hhmm, bo, bh, bl, bc = int(row[0]), row[1], row[2], row[3], row[4]
                    if bh <= dt_k + 0.005:
                        continue
                    if surged_109 and bl <= pre_c_k * 1.065:
                        return True, float(min(bo, pre_c_k * 1.065)), hhmm
                    if bh >= pre_c_k * 1.09:
                        # Same-bar bearish plunge from >=+9% to <=+6.5%
                        if bc < bo and bl <= pre_c_k * 1.065 and bc < zt_k - 0.01:
                            return True, float(pre_c_k * 1.065), hhmm
                        if bc < zt_k - 0.01:
                            surged_109 = True
                        else:
                            # Sealed at 5m close, still arm surged_109 in case subsequent bar blasts open <= +6.5%
                            surged_109 = True
        if is_zt_eod:
            return False, 0.0, 0
        return True, float(cl_k), 1500

    # Mode 2: 10:30 Snapshot VWAP + Blown-Board Protection (V17-style, never caps upside at +3%!)
    if exit_mode in ("vwap1030_5m", "vwap1030_blast_5m"):
        if arr is not None and len(arr) >= 4:
            cum_v, cum_a = 0.0, 0.0
            surged_109 = (op_k >= pre_c_k * 1.09)
            n = len(arr)
            for i in range(n - 1):
                hhmm, bo, bh, bl, bc, bv, ba = int(arr[i, 0]), arr[i, 1], arr[i, 2], arr[i, 3], arr[i, 4], arr[i, 5], arr[i, 6]
                cum_v += bv
                cum_a += ba
                vwap = (cum_a / cum_v) if cum_v > 0 else bc

                # Optional post-10:30 blown-board protection if touched +9% and broke both +5.5% & VWAP
                if exit_mode == "vwap1030_blast_5m" and hhmm >= 1000:
                    if surged_109 and (bc < zt_k - 0.01) and (bc <= pre_c_k * 1.055) and (bc < vwap):
                        nxt_o = arr[i + 1, 1]
                        if nxt_o > dt_k + 0.005:
                            return True, float(nxt_o), int(arr[i + 1, 0])

                if bh >= pre_c_k * 1.09:
                    surged_109 = True

                # Single 10:30 snapshot check: if unsealed AND below VWAP (and < +5%), exit at 10:35 open
                if hhmm == 1030:
                    if (bc < zt_k - 0.01) and (bc < vwap) and (bc < pre_c_k * 1.05):
                        nxt_o = arr[i + 1, 1]
                        if nxt_o > dt_k + 0.005:
                            return True, float(nxt_o), int(arr[i + 1, 0])

        if is_zt_eod:
            return False, 0.0, 0
        return True, float(cl_k), 1500

    # Mode 3: Pure EOD Break Exit (Hold as long as EOD seals ZT; sell at EOD close on first unsealed day)
    if exit_mode == "eod_break_5m":
        if is_zt_eod:
            return False, 0.0, 0
        return True, float(cl_k), 1500

    # Mode 4 (V3.2 Default): Afternoon 13:45 Peak>=+8.5% Drop<=+5.0% Profit Guard + EOD Break
    if exit_mode == "pm1345_5m":
        if arr is not None and len(arr) > 0:
            peak = op_k
            for row in arr:
                hhmm, bo, bh, bl, bc = int(row[0]), row[1], row[2], row[3], row[4]
                if bh <= dt_k + 0.005:
                    continue
                if hhmm >= 1345 and peak >= pre_c_k * 1.085 and bl <= pre_c_k * 1.050 and bc < zt_k - 0.01:
                    return True, float(min(bo, pre_c_k * 1.050)), hhmm
                if bh > peak:
                    peak = bh
        if is_zt_eod:
            return False, 0.0, 0
        return True, float(cl_k), 1500

    raise ValueError(f"Unknown exit_mode: {exit_mode}")


def sim_exit_5m(c6: str, cb: dict, pos: int, bars_5m_map: dict, exit_mode: str = "pm1345_5m", day5_unsealed_mode: str = "cut_weak", use_yang_imm: bool = True):
    """
    Simulate complete post-buy holding & exit trajectory on real 5m bars.
    Returns (exit_dt, sell_px, adjf_s, hold_bars, exit_hhmm).
    """
    n = len(cb["dts"])
    is_zt_day4 = bool(cb["is_zt"][pos])

    if not is_zt_day4:
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        if k >= n:
            k = n - 1
            return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500
        if k > pos + 1:
            return cb["dts"][k], float(cb["open"][k]), float(cb["adjf"][k]), k - pos, 925

        dt_s = cb["dts"][k]
        o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
        o5, p5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
        zt5 = float(cb["zt_px"][k])
        dt5 = round(p5 * 0.90, 2)
        arr = bars_5m_map.get((c6, dt_s))

        if day5_unsealed_mode == "cut_weak":
            d4_strong = (c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)
            if not d4_strong:
                return dt_s, o5, float(cb["adjf"][k]), max(1, k - pos), 925
            if bool(cb["is_zt"][k]):
                pos_start = k + 1
            else:
                return dt_s, c5, float(cb["adjf"][k]), max(1, k - pos), 1500
        elif day5_unsealed_mode == "weakcut0":
            if o5 < p5 * 1.00:
                return dt_s, o5, float(cb["adjf"][k]), 1, 925
            pos_start = -1
        elif day5_unsealed_mode == "vwap1030":
            did_ex, spx, shhmm = _sim_day_intraday_exit_5m(arr, o5, p5, c5, zt5, dt5, bool(cb["is_zt"][k]), "vwap1030_5m")
            if did_ex:
                return dt_s, spx, float(cb["adjf"][k]), 1, shhmm
            pos_start = k + 1
        else:
            pos_start = -1

        if day5_unsealed_mode not in ("cut_weak", "vwap1030"):
            if o5 >= p5 * 1.02:
                return dt_s, o5, float(cb["adjf"][k]), 1, 925
            if arr is not None and len(arr) > 0:
                for row in arr:
                    hhmm, bo, bh = int(row[0]), row[1], row[2]
                    if bh <= dt5 + 0.005:
                        continue
                    if bh >= p5 * 1.02:
                        return dt_s, float(max(bo, p5 * 1.02)), float(cb["adjf"][k]), 1, hhmm
            return dt_s, c5, float(cb["adjf"][k]), 1, 1500
    else:
        pos_start = pos + 1

    # Ride streak day by day without peeking at future EOD is_zt!
    k = pos_start
    imm_used = False
    while k < n:
        if bool(cb["is_yizi_dt"][k]):
            k += 1
            continue
        dt_s = cb["dts"][k]
        ok, pck, clk, ztk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k]), float(cb["zt_px"][k])
        dtk = round(pck * 0.90, 2)
        if k > pos_start and bool(cb["is_yizi_dt"][k - 1]):
            return dt_s, ok, float(cb["adjf"][k]), k - pos, 925

        arr = bars_5m_map.get((c6, dt_s))
        did_ex, spx, shhmm = _sim_day_intraday_exit_5m(arr, ok, pck, clk, ztk, dtk, bool(cb["is_zt"][k]), exit_mode)
        if did_ex:
            if shhmm == 1500 and use_yang_imm and (not imm_used) and (clk > ok) and (clk >= pck):
                imm_used = True
                k += 1
                continue
            return dt_s, spx, float(cb["adjf"][k]), max(1, k - pos), shhmm
        k += 1

    k = n - 1
    return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500



def _sim_single_slot_chrono(trades_df: pd.DataFrame):
    if trades_df.empty:
        return [], 1.0, 0.0, 0
    srt = trades_df.sort_values(["buy_date", "buy_hhmm", "priority_score"], ascending=[True, True, False])
    taken = []
    free_dt = ""
    free_hhmm = 0
    nav, pk, mdd = 1.0, 1.0, 0.0
    hold_days = 0
    for r in srt.itertuples(index=False):
        bd = r.buy_date
        b_hhmm = int(r.buy_hhmm)
        can_buy = (free_dt == "") or (bd > free_dt) or (bd == free_dt and b_hhmm > free_hhmm)
        if not can_buy:
            continue
        taken.append(r)
        free_dt = r.exit_date
        free_hhmm = int(r.exit_hhmm)
        nav *= (1.0 + float(r.net_ret))
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)
        hold_days += max(1, int(r.hold_bars))
    return taken, float(nav), float(mdd), int(hold_days)


def _sim_two_half_slots_chrono(trades_df: pd.DataFrame):
    if trades_df.empty:
        return [], 1.0, 0.0, 0
    srt = trades_df.sort_values(["buy_date", "buy_hhmm", "priority_score"], ascending=[True, True, False])
    slot_cap = [0.5, 0.5]
    slot_free_dt = ["", ""]
    slot_free_hhmm = [0, 0]
    pk, mdd = 1.0, 0.0
    taken = []
    used_day_codes = set()
    for r in srt.itertuples(index=False):
        bd, c = r.buy_date, r.code
        b_hhmm = int(r.buy_hhmm)
        if (bd, c) in used_day_codes:
            continue
        chosen = -1
        for s in (0, 1):
            if slot_free_dt[s] == "" or bd > slot_free_dt[s] or (bd == slot_free_dt[s] and b_hhmm > slot_free_hhmm[s]):
                chosen = s
                break
        if chosen < 0:
            continue
        used_day_codes.add((bd, c))
        taken.append(r)
        slot_free_dt[chosen] = r.exit_date
        slot_free_hhmm[chosen] = int(r.exit_hhmm)
        slot_cap[chosen] *= (1.0 + float(r.net_ret))
        tot = slot_cap[0] + slot_cap[1]
        pk = max(pk, tot)
        mdd = max(mdd, (pk - tot) / pk)
    return taken, float(slot_cap[0] + slot_cap[1]), float(mdd), len(taken)


def _sim_daily_eq(trades_df: pd.DataFrame):
    if trades_df.empty:
        return 1.0, 0.0
    by_d = trades_df.groupby("buy_date")["net_ret"].mean().sort_index()
    nav, pk, mdd = 1.0, 1.0, 0.0
    for r in by_d.values:
        nav *= (1.0 + float(r))
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)
    return float(nav), float(mdd)


def _slice_metrics_chrono(sub_df: pd.DataFrame, start_dt: str, end_dt: str):
    bench = csi300_ret(start_dt, end_dt)
    if sub_df.empty:
        return {
            "raw_n": 0, "single_n": 0, "wr": 0.0, "payoff": 0.0, "raw_wr": 0.0, "raw_payoff": 0.0,
            "mean_pct": 0.0, "single_nav": 1.0, "single_mdd_pct": 0.0,
            "half2_n": 0, "half2_nav": 1.0, "half2_mdd_pct": 0.0, "half2_wr": 0.0,
            "eq_nav": 1.0, "eq_mdd_pct": 0.0, "trimmed5_nav": 1.0,
            "csi300_pct": round(bench * 100.0, 2),
            "single_excess_pct": round(-bench * 100.0, 2),
            "half2_excess_pct": round(-bench * 100.0, 2),
            "eq_excess_pct": round(-bench * 100.0, 2),
        }

    taken, s_nav, s_mdd, h_days = _sim_single_slot_chrono(sub_df)
    taken2, h2_nav, h2_mdd, h2_n = _sim_two_half_slots_chrono(sub_df)
    eq_nav, eq_mdd = _sim_daily_eq(sub_df)

    rets = np.array([float(t.net_ret) for t in taken], dtype=float)
    wins, losses = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0) if len(rets) else 0.0
    po = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (99.0 if len(wins) > 0 else 0.0)

    raw_rets = sub_df["net_ret"].to_numpy(dtype=float)
    rw, rl = raw_rets[raw_rets > 0], raw_rets[raw_rets <= 0]
    raw_wr = float((raw_rets > 0).mean() * 100.0) if len(raw_rets) else 0.0
    raw_po = float(rw.mean() / abs(rl.mean())) if (len(rw) > 0 and len(rl) > 0 and rl.mean() < 0) else (99.0 if len(rw) > 0 else 0.0)

    rets2 = np.array([float(t.net_ret) for t in taken2], dtype=float)
    h2_wr = float((rets2 > 0).mean() * 100.0) if len(rets2) else 0.0

    trim_nav = float(np.prod(1.0 + np.sort(rets)[:-5])) if len(rets) > 5 else 1.0

    return {
        "raw_n": int(len(sub_df)), "raw_wr": round(raw_wr, 2), "raw_payoff": round(raw_po, 2),
        "single_n": int(len(rets)), "wr": round(wr, 2), "payoff": round(po, 2),
        "mean_pct": round(float(rets.mean() * 100.0) if len(rets) else 0.0, 2),
        "single_nav": round(s_nav, 3), "single_mdd_pct": round(s_mdd * 100.0, 2),
        "half2_n": int(h2_n), "half2_wr": round(h2_wr, 2),
        "half2_nav": round(h2_nav, 3), "half2_mdd_pct": round(h2_mdd * 100.0, 2),
        "eq_nav": round(eq_nav, 3), "eq_mdd_pct": round(eq_mdd * 100.0, 2),
        "trimmed5_nav": round(trim_nav, 3), "hold_days": int(h_days),
        "csi300_pct": round(bench * 100.0, 2),
        "single_excess_pct": round(((s_nav - 1.0) - bench) * 100.0, 2),
        "half2_excess_pct": round(((h2_nav - 1.0) - bench) * 100.0, 2),
        "eq_excess_pct": round(((eq_nav - 1.0) - bench) * 100.0, 2),
    }


def evaluate_5m_d15(trades_df: pd.DataFrame) -> dict:
    if trades_df is None or len(trades_df) == 0:
        e = _slice_metrics_chrono(pd.DataFrame(), "2022-01-04", "2026-11-10")
        return {"full_5y": e, "ex2025_4y": e, "recent_3y": e, "since_jul2026": e, "annual": {}}
    df = trades_df.copy()
    ann = {
        yr: _slice_metrics_chrono(df[df["buy_date"].str.startswith(yr)], f"{yr}-01-01", f"{yr}-12-31" if yr != "2026" else "2026-11-10")
        for yr in ["2022", "2023", "2024", "2025", "2026"]
    }
    return {
        "full_5y": _slice_metrics_chrono(df[(df["buy_date"] >= "2022-01-04") & (df["buy_date"] <= "2026-11-10")], "2022-01-04", "2026-11-10"),
        "ex2025_4y": _slice_metrics_chrono(df[(df["buy_date"] >= "2022-01-04") & (df["buy_date"] <= "2026-11-10") & (~df["buy_date"].str.startswith("2025"))], "2022-01-04", "2024-12-31"),
        "recent_3y": _slice_metrics_chrono(df[df["buy_date"] >= "2024-01-02"], "2024-01-02", "2026-11-10"),
        "since_jul2026": _slice_metrics_chrono(df[df["buy_date"] >= "2026-07-01"], "2026-07-01", "2026-11-10"),
        "annual": ann,
    }
