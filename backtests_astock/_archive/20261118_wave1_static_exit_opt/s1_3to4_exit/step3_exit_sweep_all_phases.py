#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step3_exit_sweep_all_phases.py
四阶段正交卖点全谱系大扫描 (阶段 A/B/C/D, 共 350+ 变体)
铁律：
  1. 首先在 IS (2021-11-15 ~ 2023-12-31) 上做全量筛选、早晚子段 (2022 vs 2023) 同向正增益检验与 ±20% 邻域平滑检验；
  2. 严格区分单仓 (1S) 与 全信号等权 (RAW/EQ) 双口径，消除单仓槽位漂移假象；
  3. 同步检查收盘精确跌停 (is_dt_exact) 不可卖拦截与 T+1 / 零未来函数。
"""

import os
import sys
import json
import time
import pickle
import math
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_opt_20261118/s1_3to4_exit"
CACHE_PKL = f"{OUT_DIR}/cache_3to4_exit.pkl"
UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, UPG_DIR)
import upgrade_3to4_pit as u34

FEE_RATE = 0.0020


def get_double_dev_px_pit(c6: str, cb: dict, cp: int, sh_map: dict, sz_map: dict, ratio: float = 0.93) -> tuple[float, float]:
    """
    严格 PIT 双严重异动计算（盘前 09:25 仅使用昨日收盘指数 I_ref = imap[dts[cp-1]]）：
    返回 (缓冲限价 pl_buf, 100%/200%触线绝对价 pl_100)
    """
    if cp < 1:
        return 99999.0, 99999.0
    imap = sh_map if c6.startswith("60") else sz_map
    sd = cb["dts"][cp - 1]
    ir = imap.get(sd)
    if not ir:
        return 99999.0, 99999.0
    disc = 1.0 - ratio
    bp_buf = 99999.0
    bp_100 = 99999.0
    adj_cp = cb["adjf"][cp]
    for k in range(1, min(11, cp + 1)):
        p = cp - k
        bi = imap.get(cb["dts"][p])
        bc = cb["close"][p] * cb["adjf"][p] / adj_cp
        if bi and bc > 0:
            idx_ret = ir / bi - 1.0
            bp_buf = min(bp_buf, bc * (1.0 + (1.0 - disc) + idx_ret))
            bp_100 = min(bp_100, bc * (2.0 + idx_ret))
    for k in range(1, min(31, cp + 1)):
        p = cp - k
        bi = imap.get(cb["dts"][p])
        bc = cb["close"][p] * cb["adjf"][p] / adj_cp
        if bi and bc > 0:
            idx_ret = ir / bi - 1.0
            bp_buf = min(bp_buf, bc * (1.0 + (2.0 - disc) + idx_ret))
            bp_100 = min(bp_100, bc * (3.0 + idx_ret))
    return float(bp_buf), float(bp_100)


def count_xq_before(xq_arr_map: dict, c6: str, d1_dt: str, target_dt: str) -> int:
    arr = xq_arr_map.get(c6)
    if arr is None or len(arr) == 0:
        return 0
    end_cut = f"{target_dt} 09:25:00"
    beg_cut = f"{d1_dt} 00:00:00"
    p_end = int(np.searchsorted(arr, end_cut, side="left"))
    p_beg = int(np.searchsorted(arr, beg_cut, side="left"))
    return max(0, p_end - p_beg)


def sim_exit_param(entry: dict, cache: dict, cfg: dict) -> tuple:
    """
    参数化全谱系卖出模拟引擎。
    返回 (exit_dt, sell_px, adjf_s, hold_bars, exit_hhmm, reason, is_dt_exact_flag)
    """
    c6 = entry["code"]
    pos = entry["pos"]
    cb = cache["code_bars_ext"][c6]
    bars_5m = cache["bars_5m_map"]
    sh_map = cache["sh_map"]
    sz_map = cache["sz_map"]
    xq_map = cache["xq_arr_map"]
    n = len(cb["dts"])

    enforce_dt_exact = cfg.get("enforce_dt_exact", False)

    # Stage A config
    a_mode = cfg.get("a_mode", "baseline")  # baseline / no_cut / big_yin / c4_ge_p4 / open_thr / 1030_vwap / dark_exempt / ...
    a_open_thr = cfg.get("a_open_thr", 0.005)
    a_yin_thr = cfg.get("a_yin_thr", -0.03)
    a_dark_src = cfg.get("a_dark_src", "prebuy")  # prebuy or d5

    # Stage B config
    b_gap_thr = cfg.get("b_gap_thr", None)        # e.g. 0.088 / 0.090 / 0.092 / 0.095
    b_gap_scope = cfg.get("b_gap_scope", "first")  # first (k==start_p+1), any, ge5b (sealed>=5), ge6b (sealed>=6)
    b_dev_ratio = cfg.get("b_dev_ratio", None)    # 0.93, 0.96, 0.98
    b_dev_min_boards = cfg.get("b_dev_min_boards", 4)  # 4=all, 5=ge5b(6b day+), 6=ge6b(7b day+), 7=ge7b(8b day+)
    b_dev_dyn_hr = cfg.get("b_dev_dyn_hr", None)  # e.g. 0.06 for F62 mode

    # Stage C config
    c_mode = cfg.get("c_mode", "grid")  # grid / 1to2_vwap / grid_plus_1430rush / none
    c_start = cfg.get("c_start", 1345)
    c_peak_type = cfg.get("c_peak_type", "pct")  # pct / zt
    c_peak_val = cfg.get("c_peak_val", 0.085)
    c_drop_type = cfg.get("c_drop_type", "pct")  # pct / vwap / dd
    c_drop_val = cfg.get("c_drop_val", 0.050)
    c_1430_rush = cfg.get("c_1430_rush", False)

    # Stage D config
    d_mode = cfg.get("d_mode", "baseline")  # baseline / zero / pct_ge_2 / yang_only / yang_to_cap / ...
    d_to_cap = cfg.get("d_to_cap", 35.0)
    d_imm_next_cut = cfg.get("d_imm_next_cut", None)  # e.g. -0.030 or "1030_vwap"
    d_max_imm = cfg.get("d_max_imm", 1)

    def _run_zt_hold(start_p: int, init_boards: int):
        k = start_p + 1
        imm_cnt = 0
        just_used_imm = False
        boards = init_boards
        while k < n:
            if bool(cb["is_yizi_dt"][k]):
                k += 1
                continue
            dt_s = cb["dts"][k]
            ok = float(cb["open"][k])
            hk = float(cb["high"][k])
            pck = float(cb["pre_c"][k])
            clk = float(cb["close"][k])
            ztk = float(cb["zt_px"][k])
            dtk = round(pck * 0.90, 2)
            tok = float(cb["to"][k])

            # 前一日若一字跌停（或收盘跌停顺延），今日开盘立走
            if k > start_p + 1 and bool(cb["is_yizi_dt"][k - 1]):
                return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "yizi_dt_open", False
            if enforce_dt_exact and k > start_p + 1 and bool(cb["is_dt_exact"][k - 1]):
                return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "dt_exact_open", False

            # Stage D: 免死次日早盘弱斩/VWAP检测
            if just_used_imm and d_imm_next_cut is not None:
                if isinstance(d_imm_next_cut, float):
                    if pck > 0 and (ok / pck - 1.0) < d_imm_next_cut:
                        return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "imm_next_open_cut", False

            # Stage B1: 极高开兑现
            if b_gap_thr is not None and pck > 0:
                gap = ok / pck - 1.0
                scope_ok = (
                    (b_gap_scope == "first" and k == start_p + 1)
                    or (b_gap_scope == "any")
                    or (b_gap_scope == "ge5b" and boards >= 5)
                    or (b_gap_scope == "ge6b" and boards >= 6)
                )
                if scope_ok and (gap > b_gap_thr) and (ok < ztk - 0.005):
                    return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "b1_gap_exit", False

            # Stage B2: 双严重异动缓冲限价止盈
            if b_dev_ratio is not None:
                pl_buf, pl_100 = get_double_dev_px_pit(c6, cb, k, sh_map, sz_map, b_dev_ratio)
                hr_today = (pl_100 / pck - 1.0) if (pck > 0 and pl_100 < 99990.0) else 999.0
                board_ok = boards >= b_dev_min_boards
                dyn_ok = (b_dev_dyn_hr is not None) and (hr_today < b_dev_dyn_hr)
                if board_ok or dyn_ok:
                    if ok >= pl_buf and ok > dtk + 0.005:
                        return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "b2_dev_open", False
                    arr_d = bars_5m.get((c6, dt_s))
                    if arr_d is not None and len(arr_d) > 0:
                        for row in arr_d:
                            hh_d, bo_d, bh_d = int(row[0]), float(row[1]), float(row[2])
                            if bh_d <= dtk + 0.005:
                                continue
                            if bh_d >= pl_buf:
                                fill_p = min(ztk, max(bo_d, pl_buf))
                                return dt_s, fill_p, float(cb["adjf"][k]), k - pos, hh_d, "b2_dev_5m", False
                    elif hk >= pl_buf and hk > dtk + 0.005:
                        return dt_s, min(ztk, pl_buf), float(cb["adjf"][k]), k - pos, 1030, "b2_dev_day", False

            # Stage C: 5分钟盘中护利
            arr = bars_5m.get((c6, dt_s))
            if arr is not None and len(arr) > 0:
                if c_mode == "1to2_vwap":
                    idx_1030, cum_v, cum_a = -1, 0.0, 0.0
                    for bi in range(len(arr)):
                        cum_v += float(arr[bi, 5])
                        cum_a += float(arr[bi, 6])
                        if int(arr[bi, 0]) == 1030:
                            idx_1030 = bi
                            break
                    if idx_1030 >= 0:
                        bc_1030 = float(arr[idx_1030, 4])
                        vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                        if bc_1030 >= ztk - 0.01:
                            for bi in range(idx_1030 + 1, len(arr) - 1):
                                if int(arr[bi, 0]) >= 1430 and float(arr[bi, 4]) < ztk - 0.01:
                                    px = float(arr[bi + 1, 1])
                                    if px > dtk + 0.005:
                                        return dt_s, px, float(cb["adjf"][k]), k - pos, int(arr[bi + 1, 0]), "c_1to2_1430rush", False
                        elif bc_1030 < vwap_1030:
                            px = float(arr[idx_1030 + 1, 1]) if idx_1030 + 1 < len(arr) else bc_1030
                            ehh = int(arr[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr) else 1030
                            if px > dtk + 0.005:
                                return dt_s, px, float(cb["adjf"][k]), k - pos, ehh, "c_1to2_1030vwap", False
                elif c_mode != "none":
                    # 统一网格引擎 + 可选 14:30 炸板抢跑 + 免死次日10:30 VWAP
                    peak = ok
                    cum_v = 0.0
                    cum_a = 0.0
                    touched_zt_pre1430 = (ok >= ztk - 0.01)
                    for bi, row in enumerate(arr):
                        hh = int(row[0])
                        bo, bh, bl, bc = float(row[1]), float(row[2]), float(row[3]), float(row[4])
                        bv, ba = float(row[5]), float(row[6])
                        cum_v += bv
                        cum_a += ba
                        vwap_now = (cum_a / cum_v) if cum_v > 0 else bc

                        if bh <= dtk + 0.005:
                            continue

                        # 免死次日 10:30 VWAP 弱走
                        if just_used_imm and d_imm_next_cut == "1030_vwap" and hh == 1030:
                            if bc < ztk - 0.01 and bc < vwap_now:
                                px = float(arr[bi + 1, 1]) if bi + 1 < len(arr) else bc
                                ehh = int(arr[bi + 1, 0]) if bi + 1 < len(arr) else 1030
                                if px > dtk + 0.005:
                                    return dt_s, px, float(cb["adjf"][k]), k - pos, ehh, "imm_next_1030vwap", False

                        # 14:30后炸板立即抢跑
                        if c_1430_rush and hh >= 1430 and touched_zt_pre1430 and bc < ztk - 0.01 and bi + 1 < len(arr):
                            px = float(arr[bi + 1, 1])
                            if px > dtk + 0.005:
                                return dt_s, px, float(cb["adjf"][k]), k - pos, int(arr[bi + 1, 0]), "c_1430_rush", False

                        # 三维微观护利网格检查 (c_start < 9999)
                        if c_start < 9999 and hh >= c_start:
                            peak_ok = (peak >= ztk - 0.01) if c_peak_type == "zt" else (peak >= pck * (1.0 + c_peak_val))
                            if peak_ok and bc < ztk - 0.01:
                                if c_drop_type == "pct":
                                    trig = pck * (1.0 + c_drop_val)
                                    if bl <= trig:
                                        px = min(bo, trig)
                                        return dt_s, px, float(cb["adjf"][k]), k - pos, hh, "c_grid_pct", False
                                elif c_drop_type == "dd":
                                    trig = peak * (1.0 - c_drop_val)
                                    if bl <= trig:
                                        px = min(bo, trig)
                                        return dt_s, px, float(cb["adjf"][k]), k - pos, hh, "c_grid_dd", False
                                elif c_drop_type == "vwap":
                                    if bc < vwap_now:
                                        px = float(arr[bi + 1, 1]) if bi + 1 < len(arr) else bc
                                        ehh = int(arr[bi + 1, 0]) if bi + 1 < len(arr) else hh
                                        if px > dtk + 0.005 or (bi + 1 < len(arr) and float(arr[bi + 1, 2]) > dtk + 0.005):
                                            return dt_s, px, float(cb["adjf"][k]), k - pos, ehh, "c_grid_vwap", False

                        if bh > peak:
                            peak = bh
                        if bc >= ztk - 0.01 or bh >= ztk - 0.01:
                            touched_zt_pre1430 = True

            if bool(cb["is_zt"][k]):
                boards += 1
                just_used_imm = False
                k += 1
                continue

            if enforce_dt_exact and bool(cb["is_dt_exact"][k]):
                just_used_imm = False
                k += 1
                continue

            # Stage D: 断板免死金牌判定
            imm_ok = False
            if imm_cnt < d_max_imm:
                if d_mode == "baseline" or d_mode == "true_yang_pct0":
                    imm_ok = (clk > ok) and (clk >= pck)
                elif d_mode == "zero":
                    imm_ok = False
                elif d_mode == "pct_ge_2":
                    imm_ok = (clk >= pck * 1.02)
                elif d_mode == "true_yang_pct_ge_2":
                    imm_ok = (clk > ok) and (clk >= pck * 1.02)
                elif d_mode == "true_yang_only":
                    imm_ok = (clk > ok)
                elif d_mode == "true_yang_to_cap":
                    imm_ok = (clk > ok) and (clk >= pck) and (tok <= d_to_cap)
                elif d_mode == "yang_only_to_cap":
                    imm_ok = (clk > ok) and (tok <= d_to_cap)

            if imm_ok:
                imm_cnt += 1
                just_used_imm = True
                k += 1
                continue

            return dt_s, clk, float(cb["adjf"][k]), max(1, k - pos), 1500, "d_eod_close", bool(cb["is_dt_exact"][k])

        k_end = n - 1
        return cb["dts"][k_end], float(cb["close"][k_end]), float(cb["adjf"][k_end]), max(1, k_end - pos), 1500, "end_data", False

    # Branch 1: Day4 未封死四板 -> Stage A
    if not bool(cb["is_zt"][pos]):
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        k = min(k, n - 1)
        o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
        o5, p5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
        dtk5 = round(p5 * 0.90, 2)
        ztk5 = float(cb["zt_px"][k])
        dt_s5 = cb["dts"][k]

        if k > pos + 1:
            return dt_s5, o5, float(cb["adjf"][k]), k - pos, 925, "a_yizi_dt_open", False

        o5_pct = (o5 / p5 - 1.0) if p5 > 0 else 0.0
        c4_pct = (c4 / p4 - 1.0) if p4 > 0 else 0.0

        # 决定是否 09:25 斩
        do_open_cut = False
        if a_mode == "baseline":
            do_open_cut = not ((c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005))
        elif a_mode == "no_cut":
            do_open_cut = False
        elif a_mode == "big_yin":
            do_open_cut = (c4_pct <= a_yin_thr)
        elif a_mode == "c4_lt_p4_only":
            do_open_cut = (c4 < p4)
        elif a_mode == "c4_lt_p4_or_open":
            do_open_cut = not ((c4 >= p4) and (o5_pct >= a_open_thr))
        elif a_mode == "open_thr_with_c4":
            do_open_cut = not ((c4 >= o4) and (c4 >= p4) and (o5_pct >= a_open_thr))
        elif a_mode == "open_thr_only":
            do_open_cut = (o5_pct < a_open_thr)
        elif a_mode == "dark_exempt_cutweak":
            base_cut = not ((c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005))
            if a_dark_src == "prebuy":
                xq_cnt = entry["xq_cnt_2d"]
            else:
                xq_cnt = count_xq_before(xq_map, c6, entry["d1_date"], dt_s5)
            exempt = (xq_cnt < 4) and (-0.065 <= o5_pct <= 0.025)
            do_open_cut = base_cut and (not exempt)
        elif a_mode in ("1030_vwap_all", "1030_vwap_exempt_dark", "1030_vwap_on_baseweak", "1030_vwap_on_basehold"):
            # 先决定 09:25 斩否
            if a_mode == "1030_vwap_on_basehold":
                do_open_cut = not ((c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005))
            else:
                do_open_cut = False

        if do_open_cut:
            return dt_s5, o5, float(cb["adjf"][k]), max(1, k - pos), 925, "a_d5_open_cut", False

        # 如果留过 09:25 且使用 10:30 VWAP 检视
        if a_mode in ("1030_vwap_all", "1030_vwap_exempt_dark", "1030_vwap_on_baseweak", "1030_vwap_on_basehold"):
            exempt_vwap = False
            if a_mode == "1030_vwap_exempt_dark":
                xq_cnt = entry["xq_cnt_2d"] if a_dark_src == "prebuy" else count_xq_before(xq_map, c6, entry["d1_date"], dt_s5)
                exempt_vwap = (xq_cnt < 4) and (-0.065 <= o5_pct <= 0.025)
            if not exempt_vwap:
                arr5 = bars_5m.get((c6, dt_s5))
                if arr5 is not None and len(arr5) >= 12:
                    idx_1030, cv, ca = -1, 0.0, 0.0
                    for bi in range(len(arr5)):
                        cv += float(arr5[bi, 5])
                        ca += float(arr5[bi, 6])
                        if int(arr5[bi, 0]) == 1030:
                            idx_1030 = bi
                            break
                    if idx_1030 >= 0:
                        bc_1030 = float(arr5[idx_1030, 4])
                        vwap_1030 = ca / cv if cv > 0 else bc_1030
                        if (bc_1030 < ztk5 - 0.01) and (bc_1030 < vwap_1030):
                            px = float(arr5[idx_1030 + 1, 1]) if idx_1030 + 1 < len(arr5) else bc_1030
                            ehh = int(arr5[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr5) else 1030
                            if px > dtk5 + 0.005:
                                return dt_s5, px, float(cb["adjf"][k]), max(1, k - pos), ehh, "a_d5_1030_vwap_cut", False

        if bool(cb["is_zt"][k]):
            return _run_zt_hold(k, 4)

        if enforce_dt_exact and bool(cb["is_dt_exact"][k]):
            m = k + 1
            while m < n and bool(cb["is_yizi_dt"][m]):
                m += 1
            m = min(m, n - 1)
            return cb["dts"][m], float(cb["open"][m]), float(cb["adjf"][m]), m - pos, 925, "a_d5_dt_exact_delay", False

        return dt_s5, c5, float(cb["adjf"][k]), max(1, k - pos), 1500, "a_d5_eod_close", bool(cb["is_dt_exact"][k])

    # Branch 2: Day4 封死四板 -> Stage B/C/D
    return _run_zt_hold(pos, 4)


def evaluate_variant(cache: dict, cfg: dict, label: str, thr: float = 90.0) -> dict:
    code_bars = cache["code_bars_ext"]
    recs = []
    dt_exact_cnt = 0
    for e in cache["buy_entries"]:
        if not e["skel"] or e["sc_v40"] < thr or e["buy_px"] is None:
            continue
        pos = e["pos"]
        cb = code_bars[e["code"]]
        ex_dt, spx, adjs, hb, shh, rsn, dt_ex = sim_exit_param(e, cache, cfg)
        if dt_ex:
            dt_exact_cnt += 1
        nr = (spx * adjs) / (e["buy_px"] * float(cb["adjf"][pos])) * (1.0 - FEE_RATE) - 1.0
        recs.append({
            "code": e["code"],
            "name": e["name"],
            "buy_date": e["buy_date"],
            "buy_hhmm": e["buy_hhmm"],
            "buy_price": round(e["buy_px"], 2),
            "exit_date": ex_dt,
            "exit_hhmm": shh,
            "exit_price": round(spx, 2),
            "hold_bars": hb,
            "net_ret": float(nr),
            "score": int(round(e["sc_v40"])),
            "priority_score": e["priority_score"],
            "reason": rsn,
            "is_dt_exact_exit": dt_ex,
        })
    raw_df = pd.DataFrame(recs)
    slot_df = u34.sim_single_slot(raw_df)

    def _stats(r_sub: pd.DataFrame, s_sub: pd.DataFrame, s_dt: str, e_dt: str) -> dict:
        sr = r_sub[(r_sub["buy_date"] >= s_dt) & (r_sub["buy_date"] <= e_dt)]
        ss = s_sub[(s_sub["buy_date"] >= s_dt) & (s_sub["buy_date"] <= e_dt)]
        # Raw (EQ) stats
        rn = int(len(sr))
        if rn > 0:
            r_rets = sr["net_ret"].to_numpy(dtype=float)
            r_wr = float((r_rets > 0).mean() * 100.0)
            r_w, r_l = r_rets[r_rets > 0], r_rets[r_rets <= 0]
            r_plr = float(r_w.mean() / abs(r_l.mean())) if (len(r_w) and len(r_l) and r_l.mean() < 0) else 99.0
            r_mean = float(r_rets.mean() * 100.0)
            eq_nav = float(np.prod(1.0 + sr.groupby("buy_date")["net_ret"].mean().sort_index().to_numpy()))
        else:
            r_wr = r_plr = r_mean = 0.0
            eq_nav = 1.0

        # 1S stats
        sn = int(len(ss))
        if sn > 0:
            s_rets = ss["net_ret"].to_numpy(dtype=float)
            s_wr = float((s_rets > 0).mean() * 100.0)
            s_w, s_l = s_rets[s_rets > 0], s_rets[s_rets <= 0]
            s_plr = float(s_w.mean() / abs(s_l.mean())) if (len(s_w) and len(s_l) and s_l.mean() < 0) else 99.0
            s_mean = float(s_rets.mean() * 100.0)
            nav_1s = float(np.prod(1.0 + s_rets))
            pk, cur, mdd = 1.0, 1.0, 0.0
            for x in s_rets:
                cur *= 1.0 + x
                pk = max(pk, cur)
                mdd = max(mdd, (pk - cur) / pk)
            calmar = ((nav_1s - 1.0) / mdd) if mdd > 1e-6 else 999.0
            srt_r = np.sort(s_rets)
            t3 = float(np.prod(1.0 + srt_r[:-3])) if len(srt_r) > 3 else 1.0
            t5 = float(np.prod(1.0 + srt_r[:-5])) if len(srt_r) > 5 else 1.0
        else:
            s_wr = s_plr = s_mean = mdd = 0.0
            nav_1s = t3 = t5 = 1.0
            calmar = 0.0
        return {
            "raw_n": rn, "raw_wr": round(r_wr, 2), "raw_plr": round(r_plr, 2),
            "raw_mean": round(r_mean, 2), "eq_nav": round(eq_nav, 4),
            "n_1s": sn, "wr_1s": round(s_wr, 2), "plr_1s": round(s_plr, 2),
            "mean_1s": round(s_mean, 2), "nav_1s": round(nav_1s, 4),
            "mdd": round(mdd * 100.0, 2), "calmar": round(calmar, 3),
            "t3": round(t3, 4), "t5": round(t5, 4),
        }

    return {
        "label": label,
        "cfg": cfg,
        "dt_exact_exit_cnt": dt_exact_cnt,
        "IS": _stats(raw_df, slot_df, "2021-11-15", "2023-12-31"),
        "IS_2022": _stats(raw_df, slot_df, "2022-01-01", "2022-12-31"),
        "IS_2023": _stats(raw_df, slot_df, "2023-01-01", "2023-12-31"),
        "OOS": _stats(raw_df, slot_df, "2024-01-01", "2026-11-16"),
        "ALL_5Y": _stats(raw_df, slot_df, "2021-11-15", "2026-11-16"),
        "Y26": _stats(raw_df, slot_df, "2026-01-01", "2026-11-16"),
        "raw_df": raw_df,
        "slot_df": slot_df,
    }


def main():
    t0 = time.time()
    with open(CACHE_PKL, "rb") as f:
        cache = pickle.load(f)

    # 0. 首先硬核验 BASELINE 逐笔 0.0 误差
    base_res = evaluate_variant(cache, {"a_mode": "baseline"}, "BASE_V40", 90.0)
    ref_std = pd.read_csv(f"{UPG_DIR}/ledger_upg_3to4_std.csv", dtype={"code": str})
    cur = base_res["slot_df"].reset_index(drop=True)
    assert len(cur) == len(ref_std)
    assert np.max(np.abs(cur["net_ret"].round(6) - ref_std["net_ret"])) == 0.0
    print(f"[ENGINE VERIFY 0.0 DIFF] BASE_V40 95 trades 1S={base_res['ALL_5Y']['nav_1s']}x, IS={base_res['IS']['nav_1s']}x, OOS={base_res['OOS']['nav_1s']}x, dt_exact_exits={base_res['dt_exact_exit_cnt']}")

    # 额外检查：如严格开启 enforce_dt_exact=True，baseline 自己会改变多少笔？
    base_dt_res = evaluate_variant(cache, {"a_mode": "baseline", "enforce_dt_exact": True}, "BASE_V40_DT_EXACT", 90.0)
    print(f"[DT_EXACT CHECK] BASE with enforce_dt_exact=True: ALL 1S={base_dt_res['ALL_5Y']['nav_1s']}x, IS={base_dt_res['IS']['nav_1s']}x, OOS={base_dt_res['OOS']['nav_1s']}x")

    # 构建四阶段全实验清单 (全部在 baseline 之上做正交单因素改动)
    experiments = []

    # --- Phase A (Day4 未封死四板) ---
    experiments.append(("A", "A0_baseline_cut_weak", {"a_mode": "baseline"}))
    experiments.append(("A", "A1_2to3_no_0925_cut", {"a_mode": "no_cut"}))
    experiments.append(("A", "A1b_2to3_no_0925_cut_dtex", {"a_mode": "no_cut", "enforce_dt_exact": True}))
    experiments.append(("A", "A2_2to3_big_yin_neg3", {"a_mode": "big_yin", "a_yin_thr": -0.03}))
    experiments.append(("A", "A3_2to3_big_yin_neg5", {"a_mode": "big_yin", "a_yin_thr": -0.05}))
    experiments.append(("A", "A3b_2to3_big_yin_neg3_dtex", {"a_mode": "big_yin", "a_yin_thr": -0.03, "enforce_dt_exact": True}))
    experiments.append(("A", "A4a_1to2_c4_lt_p4_only", {"a_mode": "c4_lt_p4_only"}))
    experiments.append(("A", "A4b_1to2_c4_lt_p4_or_o05", {"a_mode": "c4_lt_p4_or_open", "a_open_thr": 0.005}))
    experiments.append(("A", "A5a_1to2_d5_1030_vwap_all", {"a_mode": "1030_vwap_all"}))
    experiments.append(("A", "A5b_1to2_d5_1030_vwap_hold", {"a_mode": "1030_vwap_on_basehold"}))
    experiments.append(("A", "A6a_dark_exempt_prebuy", {"a_mode": "dark_exempt_cutweak", "a_dark_src": "prebuy"}))
    experiments.append(("A", "A6b_dark_exempt_d5_0925", {"a_mode": "dark_exempt_cutweak", "a_dark_src": "d5"}))
    experiments.append(("A", "A6c_dark_exempt_1030vwap", {"a_mode": "1030_vwap_exempt_dark", "a_dark_src": "d5"}))
    for thr_v in [-0.030, -0.010, 0.000, 0.005, 0.010, 0.020]:
        lbl_t = f"{thr_v*100:+.1f}".replace("+", "p").replace("-", "n").replace(".", "")
        experiments.append(("A", f"A7_c4ok_o5thr_{lbl_t}", {"a_mode": "open_thr_with_c4", "a_open_thr": thr_v}))
        experiments.append(("A", f"A8_only_o5thr_{lbl_t}", {"a_mode": "open_thr_only", "a_open_thr": thr_v}))

    # --- Phase B (封死四板后 极高开兑现 & 双严重异动限价) ---
    for g_thr in [0.085, 0.088, 0.090, 0.092, 0.095]:
        gn = int(round(g_thr * 1000))
        experiments.append(("B1", f"B1_gap{gn}_first_next", {"b_gap_thr": g_thr, "b_gap_scope": "first"}))
        experiments.append(("B1", f"B1_gap{gn}_any_board", {"b_gap_thr": g_thr, "b_gap_scope": "any"}))
        experiments.append(("B1", f"B1_gap{gn}_ge5b", {"b_gap_thr": g_thr, "b_gap_scope": "ge5b"}))
        experiments.append(("B1", f"B1_gap{gn}_ge6b", {"b_gap_thr": g_thr, "b_gap_scope": "ge6b"}))

    for ratio in [0.93, 0.96, 0.98]:
        rn = int(round(ratio * 100))
        experiments.append(("B2", f"B2_dev{rn}_all_boards", {"b_dev_ratio": ratio, "b_dev_min_boards": 4}))
        experiments.append(("B2", f"B2_dev{rn}_ge5b_6bday", {"b_dev_ratio": ratio, "b_dev_min_boards": 5}))
        experiments.append(("B2", f"B2_dev{rn}_ge6b_7bday", {"b_dev_ratio": ratio, "b_dev_min_boards": 6}))
        experiments.append(("B2", f"B2_dev{rn}_ge7b_8bday", {"b_dev_ratio": ratio, "b_dev_min_boards": 7}))
        experiments.append(("B2", f"B2_dev{rn}_ge6b_or_hr6", {"b_dev_ratio": ratio, "b_dev_min_boards": 6, "b_dev_dyn_hr": 0.06}))

    # --- Phase C (连板持有期 5m 护利微观全网格) ---
    experiments.append(("C_peer", "C_1to2_1030vwap_1430rush", {"c_mode": "1to2_vwap"}))
    experiments.append(("C_peer", "C_base1345_plus_1430rush", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.050, "c_1430_rush": True}))
    experiments.append(("C_peer", "C_none_plus_1430rush", {"c_mode": "grid", "c_start": 9999, "c_1430_rush": True}))
    experiments.append(("C", "C_only_1455_close_none", {"c_mode": "none"}))

    starts = [1030, 1115, 1300, 1330, 1345, 1400, 1415, 1430]
    peaks = [("p75", "pct", 0.075), ("p80", "pct", 0.080), ("p85", "pct", 0.085), ("p90", "pct", 0.090), ("pzt", "zt", 0.0)]
    drops = [
        ("d30", "pct", 0.030), ("d40", "pct", 0.040), ("d50", "pct", 0.050), ("d60", "pct", 0.060),
        ("dvwap", "vwap", 0.0), ("dd35", "dd", 0.035), ("dd45", "dd", 0.045),
    ]
    for st in starts:
        for pn, pt, pv in peaks:
            for dn, dt_t, dv in drops:
                experiments.append((
                    "C", f"C_{st}_{pn}_{dn}",
                    {"c_mode": "grid", "c_start": st, "c_peak_type": pt, "c_peak_val": pv, "c_drop_type": dt_t, "c_drop_val": dv}
                ))

    # --- Phase D (断板免死金牌网格) ---
    experiments.append(("D", "D0_baseline_yang_pct0", {"d_mode": "baseline"}))
    experiments.append(("D", "D1_zero_immunity", {"d_mode": "zero"}))
    experiments.append(("D", "D2a_1to2_pct_ge_2", {"d_mode": "pct_ge_2"}))
    experiments.append(("D", "D2b_yang_and_pct_ge_2", {"d_mode": "true_yang_pct_ge_2"}))
    experiments.append(("D", "D3_true_yang_only_anypct", {"d_mode": "true_yang_only"}))
    for to_cap in [25.0, 30.0, 35.0, 40.0]:
        experiments.append(("D", f"D4_yang_pct0_to_{int(to_cap)}", {"d_mode": "true_yang_to_cap", "d_to_cap": to_cap}))
        experiments.append(("D", f"D4b_yang_any_to_{int(to_cap)}", {"d_mode": "yang_only_to_cap", "d_to_cap": to_cap}))
    for ocut in [-0.050, -0.030, -0.020, 0.000]:
        oc_lbl = f"{ocut*100:+.0f}".replace("+", "p").replace("-", "n")
        experiments.append(("D", f"D5_imm_next_opencut_{oc_lbl}", {"d_mode": "baseline", "d_imm_next_cut": ocut}))
    experiments.append(("D", "D6_imm_next_1030vwap", {"d_mode": "baseline", "d_imm_next_cut": "1030_vwap"}))
    experiments.append(("D", "D7_max_imm_2", {"d_mode": "baseline", "d_max_imm": 2}))

    print(f"Total variants to evaluate: {len(experiments)}")
    all_rows = []
    results_map = {}
    for phase, lbl, cfg in experiments:
        r = evaluate_variant(cache, cfg, lbl, 90.0)
        results_map[lbl] = r
        row = {
            "phase": phase,
            "label": lbl,
            "dt_ex": r["dt_exact_exit_cnt"],
            # IS
            "IS_raw_n": r["IS"]["raw_n"],
            "IS_raw_wr": r["IS"]["raw_wr"],
            "IS_raw_mean": r["IS"]["raw_mean"],
            "IS_eq_nav": r["IS"]["eq_nav"],
            "IS_1s_n": r["IS"]["n_1s"],
            "IS_1s_wr": r["IS"]["wr_1s"],
            "IS_1s_plr": r["IS"]["plr_1s"],
            "IS_1s_nav": r["IS"]["nav_1s"],
            "IS_mdd": r["IS"]["mdd"],
            "IS_calmar": r["IS"]["calmar"],
            "IS22_1s_nav": r["IS_2022"]["nav_1s"],
            "IS22_eq_nav": r["IS_2022"]["eq_nav"],
            "IS23_1s_nav": r["IS_2023"]["nav_1s"],
            "IS23_eq_nav": r["IS_2023"]["eq_nav"],
            # OOS
            "OOS_raw_wr": r["OOS"]["raw_wr"],
            "OOS_raw_mean": r["OOS"]["raw_mean"],
            "OOS_eq_nav": r["OOS"]["eq_nav"],
            "OOS_1s_n": r["OOS"]["n_1s"],
            "OOS_1s_wr": r["OOS"]["wr_1s"],
            "OOS_1s_plr": r["OOS"]["plr_1s"],
            "OOS_1s_nav": r["OOS"]["nav_1s"],
            "OOS_mdd": r["OOS"]["mdd"],
            "OOS_calmar": r["OOS"]["calmar"],
            # 5Y
            "5Y_eq_nav": r["ALL_5Y"]["eq_nav"],
            "5Y_1s_n": r["ALL_5Y"]["n_1s"],
            "5Y_1s_wr": r["ALL_5Y"]["wr_1s"],
            "5Y_1s_plr": r["ALL_5Y"]["plr_1s"],
            "5Y_1s_nav": r["ALL_5Y"]["nav_1s"],
            "5Y_mdd": r["ALL_5Y"]["mdd"],
            "5Y_t3": r["ALL_5Y"]["t3"],
            "5Y_t5": r["ALL_5Y"]["t5"],
            "Y26_1s_nav": r["Y26"]["nav_1s"],
            "Y26_eq_nav": r["Y26"]["eq_nav"],
        }
        all_rows.append(row)

    df_res = pd.DataFrame(all_rows)
    df_res.to_csv(f"{OUT_DIR}/sweep_all_phases_raw.csv", index=False, encoding="utf-8-sig")
    print(f"[SWEEP DONE] {len(df_res)} variants completed in {time.time()-t0:.1f}s -> saved sweep_all_phases_raw.csv")

    # 严格仅按 IS 排名输出每个阶段的 Top 诊断（绝对只看 IS 列来展示初步结论！）
    base_is = df_res[df_res["label"] == "A0_baseline_cut_weak"].iloc[0]
    print(f"\n[IS BASELINE] IS_1s_nav={base_is['IS_1s_nav']}x, IS_eq_nav={base_is['IS_eq_nav']}x, IS_mdd={base_is['IS_mdd']}%, IS_calmar={base_is['IS_calmar']}, IS22_1s={base_is['IS22_1s_nav']}x (eq={base_is['IS22_eq_nav']}x), IS23_1s={base_is['IS23_1s_nav']}x (eq={base_is['IS23_eq_nav']}x)")

    for ph in ["A", "B1", "B2", "C_peer", "C", "D"]:
        sub = df_res[df_res["phase"] == ph].copy()
        # IS-only composite check: IS_1s_nav, IS_eq_nav, IS22/23同向正增益
        sub["is_2sub_gain"] = (
            (sub["IS22_eq_nav"] >= base_is["IS22_eq_nav"] - 1e-6)
            & (sub["IS23_eq_nav"] >= base_is["IS23_eq_nav"] - 1e-6)
            & (sub["IS_eq_nav"] > base_is["IS_eq_nav"] + 1e-4)
        )
        sub["is_1s_2sub_gain"] = (
            (sub["IS22_1s_nav"] >= base_is["IS22_1s_nav"] - 1e-6)
            & (sub["IS23_1s_nav"] >= base_is["IS23_1s_nav"] - 1e-6)
            & (sub["IS_1s_nav"] > base_is["IS_1s_nav"] + 1e-4)
        )
        print(f"\n=== Phase {ph} TOP by IS_1s_nav (IS-ONLY VIEW) ===")
        cols_is = ["label", "dt_ex", "IS_1s_n", "IS_1s_wr", "IS_1s_plr", "IS_1s_nav", "IS_mdd", "IS_calmar", "IS_eq_nav", "IS22_1s_nav", "IS23_1s_nav", "IS22_eq_nav", "IS23_eq_nav", "is_2sub_gain", "is_1s_2sub_gain"]
        print(sub.sort_values(["IS_1s_nav", "IS_eq_nav"], ascending=False)[cols_is].head(12).to_string(index=False))


if __name__ == "__main__":
    main()
