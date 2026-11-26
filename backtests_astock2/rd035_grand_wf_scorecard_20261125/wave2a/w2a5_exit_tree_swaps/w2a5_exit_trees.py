#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-5 Unified Exit Tree Library (13 Exit Trees + Module 3 Dynamic Guards).
Strictly causal, zero lookahead, full ex-div adj_factor handling, full limit-down deferral,
and 0.30% round-trip cost by default.
"""
import os
import sys
import numpy as np
import pandas as pd

WAVE1 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
for p in (WAVE1, RD028):
    if p not in sys.path:
        sys.path.insert(0, p)

import step4_mod_rules_and_sim as m1

TREE_CATALOG = [
    ("E0_Native", "各策略现行V20.0原版卖出树(统一0.30%扣费)"),
    ("E1a_20cm_Exact", "移植20cm四分支卖出树(原版6%/12%/-5%阈值)"),
    ("E1b_20cm_Scaled", "移植20cm四分支卖出树(按10cm/20cm板幅等比例缩放)"),
    ("E2_1to2_SealOrRed", "移植1to2卖出树(封板留+未封红开留绿开0925走+1030均线+1430炸板)"),
    ("E3_3to4_StrictRed", "移植3to4卖出树(买日阳红且次日高开>=0.5%留+1345回落守门)"),
    ("E4_2to3_HoldT1_HiOpen", "移植2to3卖出树(未封拿T+1收盘+封板高开>9.2%走+1345回落守门)"),
    ("E5_High_DoubleDev", "移植high卖出树(双异动93%限价止盈+连板阳线豁免+未封T+1收盘)"),
    ("E6_Pry_DecD_Max4d", "移植pry卖出树(D0跌停早走+未封4日递减止盈与-1.5%弱走)"),
    ("E7_T1_Close_Flat", "极简T+1 15:00全平(跌停顺延, 零隔夜连板)"),
    ("E8_T2_Open_Flat", "统一T+2 09:25开盘平仓(跌停顺延)"),
    ("E9_T2_Close_Flat", "统一T+2 15:00收盘平仓(跌停顺延)"),
    ("E10_TrailTP_Stop5", "动态次日冲高移动止盈(5%+回撤3.5%)+买价-5%止损+封板连板"),
    ("E11_BreakPrevClose", "次日09:25低开破昨收走+盘中跌破昨收-2%止损+封板连板"),
]


def _double_dev_px_causal(c6: str, ss: dict, kp: int, sh_idx: dict, sz_idx: dict, ratio: float = 0.93) -> float:
    """Strictly causal double severe abnormal deviation limit price using idx[dts[kp-1]]."""
    if kp < 1:
        return 99999.0
    imap = sh_idx if c6.startswith("60") else sz_idx
    ir = imap.get(str(ss["dts"][kp - 1]))
    if not ir:
        return 99999.0
    disc = 1.0 - ratio
    adj_k = float(ss["adjf"][kp])
    bp = 99999.0
    for m in range(1, min(11, kp + 1)):
        p = kp - m
        bi = imap.get(str(ss["dts"][p]))
        bc = float(ss["close"][p]) * float(ss["adjf"][p]) / adj_k
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
    for m in range(1, min(31, kp + 1)):
        p = kp - m
        bi = imap.get(str(ss["dts"][p]))
        bc = float(ss["close"][p]) * float(ss["adjf"][p]) / adj_k
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
    return float(bp)


def _defer_yizi_dt(ss: dict, start_k: int) -> int:
    n = len(ss["dts"])
    k = min(start_k, n - 1)
    while k < n - 1 and ss["is_yizi_dt"][k]:
        k += 1
    return k


def _finish_close(ss: dict, k: int, b0_idx: int, buy_adj: float, fee: float, reason: str):
    """Exit at EOD k, automatically deferring if EOD exact limit-down."""
    if ss["is_dt"][k]:
        kd = _defer_yizi_dt(ss, min(k + 1, len(ss["dts"]) - 1))
        px = float(ss["open"][kd]) if kd > k else float(ss["close"][kd])
        hh = 925 if kd > k else 1500
        ed = str(ss["dts"][kd])
        nr = (px * float(ss["adjf"][kd]) / buy_adj) * (1.0 - fee) - 1.0
        return ed, hh, round(px, 2), float(nr), f"{reason}|dt_defer", True
    px = float(ss["close"][k])
    ed = str(ss["dts"][k])
    nr = (px * float(ss["adjf"][k]) / buy_adj) * (1.0 - fee) - 1.0
    return ed, 1500, round(px, 2), float(nr), reason, False


def _finish_px(ss: dict, k: int, px_raw: float, hh: int, buy_adj: float, fee: float, reason: str, dt_def: bool = False):
    ed = str(ss["dts"][k])
    nr = (float(px_raw) * float(ss["adjf"][k]) / buy_adj) * (1.0 - fee) - 1.0
    return ed, int(hh), round(float(px_raw), 2), float(nr), reason, dt_def


def _ride_zt_chain(
    c6: str, ss: dict, start_k: int, b0_idx: int, buy_adj: float, fee: float, ctx: dict,
    imm_mode: str = "none", hi_open_th: float | None = None, dbl_dev_ratio: float | None = None,
    intraday_mode: str = "none", m1_exempt: bool = False, xq_pre: float = 99.0, init_boards: int = 1,
    max_k_off: int = 12,
):
    """Generic causal ZT chain rider starting at start_k + 1."""
    n = len(ss["dts"])
    b5m = ctx["b5m"]
    sh_idx, sz_idx = ctx["sh_idx"], ctx["sz_idx"]
    k = start_k + 1
    used_imm = False
    boards = init_boards
    while k < n and (k - b0_idx <= max_k_off):
        if ss["is_yizi_dt"][k]:
            k += 1
            continue
        if k > start_k + 1 and ss["is_dt"][k - 1]:
            return _finish_px(ss, k, ss["open"][k], 925, buy_adj, fee, "prev_dt_defer_open", True)

        ok, hk, lk, ck = float(ss["open"][k]), float(ss["high"][k]), float(ss["low"][k]), float(ss["close"][k])
        pck, ztk, dtk = float(ss["prev_c"][k]), float(ss["zt_px"][k]), float(ss["dt_px"][k])
        dk = str(ss["dts"][k])
        lim_k = float(ss["lim"][k])

        if hi_open_th is not None and k == b0_idx + 1 and pck > 0:
            op_r = ok / pck - 1.0
            if op_r > hi_open_th and ok < ztk - 0.005 and ok > dtk + 0.005:
                return _finish_px(ss, k, ok, 925, buy_adj, fee, "hi_open_925")

        pl_dev = 99999.0
        if dbl_dev_ratio is not None:
            pl_dev = _double_dev_px_causal(c6, ss, k, sh_idx, sz_idx, dbl_dev_ratio)
            if ok >= pl_dev and ok > dtk + 0.005:
                return _finish_px(ss, k, ok, 925, buy_adj, fee, "dbl_dev_open")

        arr = b5m.get((c6, dk))
        if arr is not None and len(arr) >= 6:
            if pl_dev < 99990.0:
                for row5 in arr:
                    hh, bo, bh = int(row5[0]), float(row5[1]), float(row5[2])
                    if bh > dtk + 0.005 and bh >= pl_dev:
                        px_d = max(bo, pl_dev)
                        if px_d > dtk + 0.005:
                            return _finish_px(ss, k, px_d, hh, buy_adj, fee, "dbl_dev_intraday")

            if intraday_mode == "1to2_vwap":
                idx_1030, cv, ca = -1, 0.0, 0.0
                for bi in range(len(arr)):
                    cv += float(arr[bi, 5]); ca += float(arr[bi, 6])
                    if int(arr[bi, 0]) == 1030:
                        idx_1030 = bi; break
                if idx_1030 >= 0:
                    bc30 = float(arr[idx_1030, 4])
                    vw30 = ca / cv if cv > 0 else bc30
                    if bc30 >= ztk - 0.01:
                        for bi in range(idx_1030 + 1, len(arr) - 1):
                            if int(arr[bi, 0]) >= 1430 and float(arr[bi, 4]) < ztk - 0.01:
                                px_x = float(arr[bi + 1, 1])
                                if px_x > dtk + 0.005:
                                    return _finish_px(ss, k, px_x, int(arr[bi + 1, 0]), buy_adj, fee, "5m_1430_rush")
                    elif bc30 < vw30 and not (m1_exempt and k == b0_idx + 1 and pck > 0 and (-0.065 <= (ok / pck - 1.0) <= 0.025) and xq_pre < 4):
                        px_x = float(arr[idx_1030 + 1, 1]) if idx_1030 + 1 < len(arr) else bc30
                        hh_x = int(arr[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr) else 1030
                        if px_x > dtk + 0.005:
                            return _finish_px(ss, k, px_x, hh_x, buy_adj, fee, "5m_1030_vwap")

            elif intraday_mode in ("3to4_guard", "2to3_guard"):
                pk_th = 0.085 * (lim_k / 0.10)
                drp_th = (0.050 if intraday_mode == "3to4_guard" else 0.065) * (lim_k / 0.10)
                pk = ok
                for bi in range(len(arr)):
                    hh, bo, bh, bl, bc = int(arr[bi, 0]), float(arr[bi, 1]), float(arr[bi, 2]), float(arr[bi, 3]), float(arr[bi, 4])
                    if bh <= dtk + 0.005:
                        continue
                    if hh >= 1345 and pck > 0 and pk >= pck * (1.0 + pk_th) and bl <= pck * (1.0 + drp_th) and bc < ztk - 0.01:
                        px_x = min(bo, pck * (1.0 + drp_th))
                        if px_x > dtk + 0.005:
                            return _finish_px(ss, k, px_x, hh, buy_adj, fee, f"5m_{intraday_mode}")
                    if bh > pk:
                        pk = bh
        else:
            if pl_dev < 99990.0 and hk >= pl_dev and pl_dev > dtk + 0.005:
                return _finish_px(ss, k, pl_dev, 1030, buy_adj, fee, "dbl_dev_daily")

        if ss["is_zt"][k]:
            boards += 1
            k += 1
            continue
        if not used_imm:
            if imm_mode == "true_yang_ge0" and ck > ok and ck >= pck:
                used_imm = True; k += 1; continue
            if imm_mode == "yang" and ck > ok:
                used_imm = True; k += 1; continue
            if imm_mode == "pct_ge2" and boards >= 2 and ck >= pck * 1.02:
                used_imm = True; k += 1; continue
        return _finish_close(ss, k, b0_idx, buy_adj, fee, "zt_break_eod")

    kd = min(k, n - 1)
    return _finish_close(ss, kd, b0_idx, buy_adj, fee, "max_hold_eod")


def _try_tp(ss: dict, k: int, tp_px: float, b5m_arr: np.ndarray | None, tp_buf: float = 0.003):
    """Try gap-open or intraday TP at bar k."""
    ok, hk, dtk, ztk = float(ss["open"][k]), float(ss["high"][k]), float(ss["dt_px"][k]), float(ss["zt_px"][k])
    if ok >= tp_px and ok > dtk + 0.005:
        return True, ok, 925, "gap_tp"
    if b5m_arr is not None and len(b5m_arr) > 0:
        for row5 in b5m_arr:
            hh, bo, bh = int(row5[0]), float(row5[1]), float(row5[2])
            if bh >= tp_px and max(bo, tp_px) > dtk + 0.005:
                return True, max(bo, tp_px), hh, "intraday_tp_5m"
    else:
        need_hk = min(tp_px * (1.0 + tp_buf), ztk - 1e-4)
        if hk >= need_hk and tp_px > dtk + 0.005:
            return True, tp_px, 1030, "intraday_tp"
    return False, np.nan, 0, ""


def simulate_single_trade_exit(r, strat: str, tree_id: str, ctx: dict, fee: float = 0.0030) -> tuple:
    """Simulate a single candidate trade under `tree_id`. Returns (ed, eh, ep, net_ret, rsn, dt_def)."""
    if tree_id == "E0_Native":
        nat_fee = 0.0030 if strat == "20cm" else 0.0020
        nr = (1.0 + float(r.native_net_ret)) / (1.0 - nat_fee) * (1.0 - fee) - 1.0
        dt_d = bool(getattr(r, "dt_deferred", False)) if strat == "high" else False
        return str(r.native_exit_date), int(r.native_exit_hhmm), float(r.native_exit_price), float(nr), "native", dt_d

    c6 = str(r.code).zfill(6)
    bd = str(r.buy_date)[:10]
    ss = ctx["stock_series"].get(c6)
    if ss is None or bd not in ss["d2i"]:
        nat_fee = 0.0030 if strat == "20cm" else 0.0020
        nr = (1.0 + float(r.native_net_ret)) / (1.0 - nat_fee) * (1.0 - fee) - 1.0
        return str(r.native_exit_date), int(r.native_exit_hhmm), float(r.native_exit_price), float(nr), "no_series", False

    b0 = ss["d2i"][bd]
    n = len(ss["dts"])
    if b0 + 1 >= n:
        return _finish_close(ss, b0, b0, float(ss["close"][b0]) * float(ss["adjf"][b0]), fee, "end_of_data")

    adjf0 = float(ss["adjf"][b0])
    bp_val = float(r.buy_price_val) if pd.notna(r.buy_price_val) else float(ss["open"][b0])
    buy_adj = bp_val if bool(r.is_adj_px) else bp_val * adjf0
    if buy_adj <= 0:
        buy_adj = float(ss["open"][b0]) * adjf0

    o0, h0, l0, c0 = float(ss["open"][b0]), float(ss["high"][b0]), float(ss["low"][b0]), float(ss["close"][b0])
    pc0 = float(ss["prev_c"][b0]) if np.isfinite(ss["prev_c"][b0]) else o0
    lim0 = float(ss["lim"][b0])
    zt0 = bool(ss["is_zt"][b0])
    dt0 = bool(ss["is_dt"][b0])
    clv0 = (c0 - l0) / (h0 - l0) if (h0 - l0) > 1e-6 else 0.5
    body0 = (c0 / o0 - 1.0) if o0 > 0 else 0.0
    op0_pct = (o0 / pc0 - 1.0) if pc0 > 0 else 0.0

    k1 = _defer_yizi_dt(ss, b0 + 1)
    if k1 > b0 + 1:
        return _finish_px(ss, k1, ss["open"][k1], 925, buy_adj, fee, "tp1_yizi_dt_defer", True)
    o1, c1, pc1 = float(ss["open"][k1]), float(ss["close"][k1]), float(ss["prev_c"][k1])
    op1_pct = (o1 / pc1 - 1.0) if pc1 > 0 else 0.0
    dk1 = str(ss["dts"][k1])

    if tree_id in ("E1a_20cm_Exact", "E1b_20cm_Scaled"):
        sc = 1.0 if (tree_id == "E1a_20cm_Exact" or lim0 >= 0.15) else 0.5
        if zt0:
            return _ride_zt_chain(c6, ss, b0, b0, buy_adj, fee, ctx, imm_mode="none", max_k_off=10)
        risk_hit = bool(ctx.get("mkt_tp1_risk", {}).get(dk1, False))
        b4_body = -0.05 * sc
        b2_body = 0.06 * sc
        b2_tp = (min(0.12, 0.07) if risk_hit else 0.12) * sc
        if body0 <= b4_body or dt0:
            return _finish_close(ss, k1, b0, buy_adj, fee, "B4_d2_close")
        if body0 >= b2_body and clv0 >= 0.65:
            tp_px = c0 * (adjf0 / float(ss["adjf"][k1])) * (1.0 + b2_tp)
            hit, px_h, hh_h, r_h = _try_tp(ss, k1, tp_px, ctx["b5m"].get((c6, dk1)) if strat != "20cm" else None)
            if hit:
                return _finish_px(ss, k1, px_h, hh_h, buy_adj, fee, f"B2_{r_h}")
            if risk_hit:
                return _finish_close(ss, k1, b0, buy_adj, fee, "B2_d2_risk_close")
            if ss["is_zt"][k1]:
                return _ride_zt_chain(c6, ss, k1, b0, buy_adj, fee, ctx, imm_mode="none", max_k_off=10)
            k2 = min(k1 + 1, n - 1)
            if k2 > k1:
                if ss["is_yizi_dt"][k2]:
                    kd = _defer_yizi_dt(ss, k2)
                    return _finish_px(ss, kd, ss["open"][kd], 925, buy_adj, fee, "B2_d3_defer", True)
                tp_px2 = c1 * (float(ss["adjf"][k1]) / float(ss["adjf"][k2])) * (1.0 + b2_tp)
                hit2, px2, hh2, r2 = _try_tp(ss, k2, tp_px2, ctx["b5m"].get((c6, str(ss["dts"][k2]))) if strat != "20cm" else None)
                if hit2:
                    return _finish_px(ss, k2, px2, hh2, buy_adj, fee, f"B2_d3_{r2}")
                return _finish_close(ss, k2, b0, buy_adj, fee, "B2_d3_close")
            return _finish_close(ss, k1, b0, buy_adj, fee, "B2_d2_close")
        tp3_base = max(0.06 * sc, min(0.15 * sc, abs(op0_pct) * (1.5 if sc == 1.0 else 0.75)))
        tp3 = min(tp3_base, 0.07 * sc) if risk_hit else tp3_base
        tp_px3 = c0 * (adjf0 / float(ss["adjf"][k1])) * (1.0 + tp3)
        hit3, px3, hh3, r3 = _try_tp(ss, k1, tp_px3, ctx["b5m"].get((c6, dk1)) if strat != "20cm" else None)
        if hit3:
            return _finish_px(ss, k1, px3, hh3, buy_adj, fee, f"B3_{r3}")
        return _finish_close(ss, k1, b0, buy_adj, fee, "B3_d2_close")

    if tree_id == "E2_1to2_SealOrRed":
        xq_v, sr_v = ctx.get("xq_m1_map", {}).get((strat, bd, c6), (0.0, np.nan))
        m1_ok = (xq_v < 4.0) and (np.isnan(sr_v) or sr_v < 0.25)
        if zt0:
            return _ride_zt_chain(c6, ss, b0, b0, buy_adj, fee, ctx, imm_mode="pct_ge2", intraday_mode="1to2_vwap", m1_exempt=m1_ok, xq_pre=xq_v, init_boards=2)
        if c0 >= pc0 and op1_pct >= 0.005:
            if ss["is_zt"][k1]:
                return _ride_zt_chain(c6, ss, k1, b0, buy_adj, fee, ctx, imm_mode="pct_ge2", intraday_mode="1to2_vwap", m1_exempt=False, init_boards=2)
            return _finish_close(ss, k1, b0, buy_adj, fee, "1to2_unseal_red_eod")
        return _finish_px(ss, k1, o1, 925, buy_adj, fee, "1to2_fail_open_cut")

    if tree_id == "E3_3to4_StrictRed":
        if zt0:
            return _ride_zt_chain(c6, ss, b0, b0, buy_adj, fee, ctx, imm_mode="true_yang_ge0", intraday_mode="3to4_guard")
        if c0 >= o0 and c0 >= pc0 and op1_pct >= 0.005:
            if ss["is_zt"][k1]:
                return _ride_zt_chain(c6, ss, k1, b0, buy_adj, fee, ctx, imm_mode="true_yang_ge0", intraday_mode="3to4_guard")
            return _finish_close(ss, k1, b0, buy_adj, fee, "3to4_unseal_eod")
        return _finish_px(ss, k1, o1, 925, buy_adj, fee, "3to4_cut_weak_925")

    if tree_id == "E4_2to3_HoldT1_HiOpen":
        hi_th = 0.092 * (lim0 / 0.10)
        if zt0:
            return _ride_zt_chain(c6, ss, b0, b0, buy_adj, fee, ctx, imm_mode="true_yang_ge0", hi_open_th=hi_th, intraday_mode="2to3_guard", init_boards=2)
        if ss["is_zt"][k1]:
            return _ride_zt_chain(c6, ss, k1, b0, buy_adj, fee, ctx, imm_mode="true_yang_ge0", hi_open_th=None, intraday_mode="2to3_guard", init_boards=1)
        return _finish_close(ss, k1, b0, buy_adj, fee, "2to3_unseal_t1_eod")

    if tree_id == "E5_High_DoubleDev":
        if zt0:
            return _ride_zt_chain(c6, ss, b0, b0, buy_adj, fee, ctx, imm_mode="yang", dbl_dev_ratio=0.93, max_k_off=8)
        if ss["is_zt"][k1]:
            return _ride_zt_chain(c6, ss, k1, b0, buy_adj, fee, ctx, imm_mode="yang", dbl_dev_ratio=0.93, max_k_off=8)
        return _finish_close(ss, k1, b0, buy_adj, fee, "high_unseal_t1_eod")

    if tree_id == "E6_Pry_DecD_Max4d":
        if zt0:
            return _ride_zt_chain(c6, ss, b0, b0, buy_adj, fee, ctx, imm_mode="none", max_k_off=10)
        if dt0:
            return _finish_px(ss, k1, o1, 925, buy_adj, fee, "pry_d0_dt_925")
        tp_sched = [None, 0.08 * (lim0 / 0.10), 0.05 * (lim0 / 0.10), 0.02 * (lim0 / 0.10)]
        end_k = min(n - 1, b0 + 4)
        for off, kk in enumerate(range(b0 + 1, end_k + 1), start=1):
            if ss["is_yizi_dt"][kk]:
                continue
            tp_r = tp_sched[min(off - 1, 3)]
            if tp_r is not None:
                tp_px = (buy_adj / float(ss["adjf"][kk])) * (1.0 + tp_r)
                hit_p, px_p, hh_p, r_p = _try_tp(ss, kk, tp_px, None)
                if hit_p:
                    return _finish_px(ss, kk, px_p, hh_p, buy_adj, fee, f"pry_t{off}_{r_p}")
            if ss["is_zt"][kk]:
                return _ride_zt_chain(c6, ss, kk, b0, buy_adj, fee, ctx, imm_mode="none", max_k_off=10)
            if kk < end_k:
                ck_a = float(ss["close"][kk]) * float(ss["adjf"][kk])
                cp_a = float(ss["close"][kk - 1]) * float(ss["adjf"][kk - 1])
                if off in (1, 2) and ck_a < cp_a * 0.985:
                    return _finish_close(ss, kk, b0, buy_adj, fee, f"pry_t{off}_eod_cut")
        kd = _defer_yizi_dt(ss, end_k)
        if ss["is_zt"][kd]:
            return _ride_zt_chain(c6, ss, kd, b0, buy_adj, fee, ctx, imm_mode="none", max_k_off=10)
        return _finish_close(ss, kd, b0, buy_adj, fee, "pry_t4_close")

    if tree_id == "E7_T1_Close_Flat":
        return _finish_close(ss, k1, b0, buy_adj, fee, "t1_close_flat")

    if tree_id == "E8_T2_Open_Flat":
        k2 = _defer_yizi_dt(ss, min(k1 + 1, n - 1))
        return _finish_px(ss, k2, ss["open"][k2], 925, buy_adj, fee, "t2_open_flat", k2 > b0 + 2)

    if tree_id == "E9_T2_Close_Flat":
        k2 = _defer_yizi_dt(ss, min(k1 + 1, n - 1))
        return _finish_close(ss, k2, b0, buy_adj, fee, "t2_close_flat")

    if tree_id == "E10_TrailTP_Stop5":
        sc = lim0 / 0.10
        if not zt0 and op1_pct < -0.03 * sc:
            return _finish_px(ss, k1, o1, 925, buy_adj, fee, "trail_open_gap_cut")
        arr = ctx["b5m"].get((c6, dk1))
        dtk1, ztk1 = float(ss["dt_px"][k1]), float(ss["zt_px"][k1])
        stop_px = (buy_adj / float(ss["adjf"][k1])) * (1.0 - 0.05 * sc)
        if o1 <= stop_px and o1 > dtk1 + 0.005:
            return _finish_px(ss, k1, o1, 925, buy_adj, fee, "trail_open_stop5")
        if arr is not None and len(arr) >= 4:
            pk = o1
            for row5 in arr:
                hh, bo, bh, bl, bc = int(row5[0]), float(row5[1]), float(row5[2]), float(row5[3]), float(row5[4])
                if bh <= dtk1 + 0.005:
                    continue
                if bh > pk:
                    pk = bh
                if pc1 > 0 and pk >= pc1 * (1.0 + 0.05 * sc) and bc < ztk1 - 0.01:
                    trig = pk * (1.0 - 0.035 * sc)
                    if bl <= trig:
                        px_x = min(bo, trig)
                        if px_x > dtk1 + 0.005:
                            return _finish_px(ss, k1, px_x, hh, buy_adj, fee, "trail_tp_5m")
                if bl <= stop_px:
                    px_x = min(bo, stop_px)
                    if px_x > dtk1 + 0.005:
                        return _finish_px(ss, k1, px_x, hh, buy_adj, fee, "trail_stop5_5m")
        if ss["is_zt"][k1]:
            return _ride_zt_chain(c6, ss, k1, b0, buy_adj, fee, ctx, imm_mode="none")
        return _finish_close(ss, k1, b0, buy_adj, fee, "trail_t1_eod")

    if tree_id == "E11_BreakPrevClose":
        if not zt0 and op1_pct < 0.0:
            return _finish_px(ss, k1, o1, 925, buy_adj, fee, "brk_pc_open_925")
        arr = ctx["b5m"].get((c6, dk1))
        dtk1, ztk1 = float(ss["dt_px"][k1]), float(ss["zt_px"][k1])
        if (not zt0) and arr is not None and len(arr) >= 4 and pc1 > 0:
            stop_pc = pc1 * 0.98
            for row5 in arr:
                hh, bo, bh, bl, bc = int(row5[0]), float(row5[1]), float(row5[2]), float(row5[3]), float(row5[4])
                if hh >= 1000 and bh > dtk1 + 0.005 and bl <= stop_pc and bc < ztk1 - 0.01:
                    px_x = min(bo, stop_pc)
                    if px_x > dtk1 + 0.005:
                        return _finish_px(ss, k1, px_x, hh, buy_adj, fee, "brk_pc_m2_5m")
        if ss["is_zt"][k1]:
            return _ride_zt_chain(c6, ss, k1, b0, buy_adj, fee, ctx, imm_mode="none")
        return _finish_close(ss, k1, b0, buy_adj, fee, "brk_pc_t1_eod")

    raise ValueError(f"Unknown tree_id: {tree_id}")


def apply_tree_to_pool(pool_df: pd.DataFrame, strat: str, tree_id: str, ctx: dict, fee: float = 0.0030, rebuild_mtm: bool = True) -> pd.DataFrame:
    """Apply `tree_id` across all official passing rows in `pool_df` and refresh MTM segments."""
    df = pool_df.copy()
    is_pass = df["is_pass_official"].to_numpy(bool)
    ed_arr = df["exit_date"].astype(str).to_numpy(dtype=object)
    eh_arr = df["exit_hhmm"].to_numpy(dtype=int)
    ep_arr = df["exit_price"].to_numpy(dtype=float)
    nr_arr = df["net_ret"].to_numpy(dtype=float)
    rs_arr = df["exit_reason"].astype(str).to_numpy(dtype=object) if "exit_reason" in df.columns else np.full(len(df), "", dtype=object)
    dt_def_arr = np.zeros(len(df), dtype=bool)

    for idx, r in enumerate(df.itertuples(index=False)):
        if not is_pass[idx]:
            continue
        ed, eh, ep, nr, rsn, dt_d = simulate_single_trade_exit(r, strat, tree_id, ctx, fee=fee)
        ed_arr[idx], eh_arr[idx], ep_arr[idx], nr_arr[idx], rs_arr[idx], dt_def_arr[idx] = ed, eh, ep, nr, rsn, dt_d

    df["exit_date"] = ed_arr
    df["exit_hhmm"] = eh_arr
    df["exit_price"] = ep_arr
    df["net_ret"] = nr_arr
    df["exit_reason"] = rs_arr
    if "exit_at_open" in df.columns:
        df["exit_at_open"] = (eh_arr == 925)
    if "eo" in df.columns:
        df["eo"] = (eh_arr == 925)
    if strat == "high":
        df["v51_cb_loss"] = (nr_arr < -0.02) & (~dt_def_arr)

    if rebuild_mtm:
        idx_full = {d: i for i, d in enumerate(ctx["cal_full"])}
        idx_5y = {d: i for i, d in enumerate(ctx["cal_5y"])}
        df["mtm_full"] = m1.precompute_mtm_segments(df, ctx["cal_full"], idx_full, ctx["bar_lu"], is_20cm_adj=(strat == "20cm"))
        df["mtm_5y"] = m1.precompute_mtm_segments(df, ctx["cal_5y"], idx_5y, ctx["bar_lu"], is_20cm_adj=(strat == "20cm"))
    return df
