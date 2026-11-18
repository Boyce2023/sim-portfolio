#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Unified causal exit simulation engine for 二进三 V2.0 (s_2to3).
Zero lookahead, exact 0.0 match to upgrade_2to3_pit.py on baseline config,
supports full Stage A / B / C / D cross-strategy exit experiments + D15 & 8-test audit.
"""
import os, sys, json, math, itertools
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules

FEE_ROUNDTRIP = 0.0020
CANON_5Y_START = "2021-11-16"
DATA_AS_OF_EXPECTED = "2026-11-16"


@dataclass
class ExitConfig:
    name: str = "Baseline_V20"
    # Stage A: unsealed_3b (~sealed_3b)
    # modes: "base_d4_1500", "v10_cut05", "vwap_1030", "vwap_1000", "vwap_1100",
    #        "vwap_1030_exempt_v1", "vwap_1030_exempt_v2", "vwap_1030_exempt_v3",
    #        "d3_stop_0925", "d3_stop_1030_vwap", "tp_limit"
    unsealed_mode: str = "base_d4_1500"
    d3_stop_pct: float = -0.05       # for d3_stop_0925 / d3_stop_1030_vwap
    d3_stop_dt_only: bool = False    # stop only if D3 exact limit-down
    tp_pct: float = 0.06             # for tp_limit (0.04, 0.06, 0.08, 0.10)
    tp_cond: str = "c3_gt_o3"        # "c3_gt_o3" or "c3_gt_o3_and_c2" or "c3_gt_c2"

    # Stage B: high open & double severe abnormal volatility buffer
    hi_open_th: float | None = 0.092 # None disables; 0.080..0.095
    hi_open_scope: str = "d4_only"   # "d4_only" or "all_boards"
    dbl_dev_buf: float | None = None # None disables; 0.93, 0.96, 0.98
    dbl_dev_min_board: int = 3       # 3=all, 4=attempting 5th, 5=after 5-board, 6=after 6-board
    dbl_dev_causal_prev_idx: bool = True

    # Stage C: intraday 5m protection during sealed hold
    # c_mode: "grid" (start_hhmm + peak_th + drop_th), "1to2_vwap1030_rush1430",
    #         "rush1430_after_zt", "rush1430_after_1030zt", "eod_only"
    c_mode: str = "grid"
    c_start_hhmm: int = 1345         # 1030, 1115, 1315, 1345, 1400, 1415, 1430, 9999
    c_peak_th: float | str = 0.085   # float (0.075..0.090) or "zt"
    c_drop_th: float | str = 0.050   # float (0.020..0.065) or "vwap" or "draw4"
    c_use_1030_vwap_in_1to2: bool = True

    # Stage D: immunity above 3-board
    # d_mode: "true_yang_ge0", "true_yang_any", "pct_ge2", "yang_pct_ge2",
    #         "yang_ge_m3", "yang_ge0_turn35", "yang_turn35", "yang_real_turn35", "no_imm"
    d_mode: str = "true_yang_ge0"


def build_lookups(da_need: pd.DataFrame):
    """Build fast price lookup and stock history index for double abnormal deviation."""
    da = da_need.sort_values(["c6", "dt"]).reset_index(drop=True)
    plook = {}
    stk_hist = {}
    for c6, grp in da.groupby("c6", sort=False):
        dts = grp["dt"].to_numpy()
        opens = grp["open"].to_numpy(dtype=float)
        highs = grp["high"].to_numpy(dtype=float)
        lows = grp["low"].to_numpy(dtype=float)
        closes = grp["close"].to_numpy(dtype=float)
        pre_cs = grp["pre_c"].to_numpy(dtype=float)
        zt_pxs = grp["zt_px"].to_numpy(dtype=float)
        dt_pxs = grp["dt_px"].to_numpy(dtype=float)
        izts = grp["is_zt"].to_numpy(dtype=bool)
        idts = grp["is_dt_exact"].to_numpy(dtype=bool)
        iyzs = grp["is_yizi"].to_numpy(dtype=bool)
        iyzdts = grp["is_yizi_dt"].to_numpy(dtype=bool)
        turns = grp["turn"].to_numpy(dtype=float) if "turn" in grp.columns else np.full(len(grp), np.nan)
        streaks = grp["streak"].to_numpy(dtype=int) if "streak" in grp.columns else np.zeros(len(grp), dtype=int)
        d2i = {str(d): i for i, d in enumerate(dts)}
        stk_hist[c6] = {"dts": dts, "close": closes, "d2i": d2i}
        for i in range(len(dts)):
            pc = float(pre_cs[i]) if not np.isnan(pre_cs[i]) else float(closes[i])
            zp = float(zt_pxs[i]) if not np.isnan(zt_pxs[i]) else 9999.0
            dp = float(dt_pxs[i]) if not np.isnan(dt_pxs[i]) else 0.0
            tr = float(turns[i]) if not np.isnan(turns[i]) else 0.0
            plook[(c6, str(dts[i]))] = (
                float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i]),
                pc, zp, dp, bool(izts[i]), bool(idts[i]), bool(iyzs[i]), bool(iyzdts[i]),
                tr, int(streaks[i]),
            )
    return plook, stk_hist


def get_double_dev_px(stk_hist_c6: dict, dk: str, prev_dk: str, idx_map: dict, buf: float, causal_prev_idx: bool = True) -> float:
    """Compute tighter of 10d+100% and 30d+200% buffered limit price (aligned with s_high V5.1)."""
    if not stk_hist_c6:
        return 99999.0
    cp = stk_hist_c6["d2i"].get(dk)
    if cp is None:
        return 99999.0
    ir = idx_map.get(prev_dk if causal_prev_idx else dk)
    if not ir:
        return 99999.0
    disc = 1.0 - buf
    dts = stk_hist_c6["dts"]
    closes = stk_hist_c6["close"]
    bp = 99999.0
    for m in range(1, min(11, cp + 1)):
        p = cp - m
        bi = idx_map.get(str(dts[p]))
        bc = float(closes[p])
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
    for m in range(1, min(31, cp + 1)):
        p = cp - m
        bi = idx_map.get(str(dts[p]))
        bc = float(closes[p])
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
    return float(bp)


def _check_immunity(d_mode: str, ok: float, ck: float, pck: float, turnk: float, lock10: float) -> bool:
    if d_mode == "true_yang_ge0":
        return (ck > ok) and (ck >= pck)
    if d_mode == "true_yang_any":
        return ck > ok
    if d_mode == "pct_ge2":
        return ck >= pck * 1.02
    if d_mode == "yang_pct_ge2":
        return (ck > ok) and (ck >= pck * 1.02)
    if d_mode == "yang_ge_m3":
        return (ck > ok) and (ck >= pck * 0.97)
    if d_mode == "yang_ge0_turn35":
        return (ck > ok) and (ck >= pck) and (turnk <= 0.35)
    if d_mode == "yang_turn35":
        return (ck > ok) and (turnk <= 0.35)
    if d_mode == "yang_real_turn35":
        rto = turnk / max(0.05, 1.0 - (lock10 / 100.0))
        return (ck > ok) and (ck >= pck) and (rto <= 0.35)
    if d_mode == "no_imm":
        return False
    raise ValueError(f"Unknown d_mode: {d_mode}")


def sim_exit_all(
    df: pd.DataFrame,
    plook: dict,
    stk_hist: dict,
    b5m: dict,
    all_dts: list,
    dt_idx: dict,
    idx_sh: dict,
    idx_sz: dict,
    cfg: ExitConfig,
    strict_assert: bool = True,
) -> tuple[list, list, list, dict]:
    """Simulate exits for all rows in df; return (rets, exit_dates, exit_hhmms, stats)."""
    rets, eds, ehs = [], [], []
    n_miss_5m_d4_unseal = 0
    n_miss_5m_zt_hold = 0
    n_total_d4_unseal = 0
    n_total_zt_days = 0
    n_dbl_dev_triggers = 0
    n_hi_open_triggers = 0
    n_tp_triggers = 0
    n_vwap1030_triggers = 0

    for r in df.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        bd = str(r.buy_date)
        pos = dt_idx.get(bd, -1)
        if pos < 0 or pos >= len(all_dts) - 1:
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        b3 = plook.get((c6, bd))
        if not b3:
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        o3, h3, l3, c3, pc3, zt3, dt3, izt3, idt3, iyz3, iyzdt3, turn3, streak3 = b3
        buy_px = round(float(r.prev_close) * (1.0 + float(r.open_pct)), 2)
        imap = idx_sh if c6.startswith("60") else idx_sz
        sh_c6 = stk_hist.get(c6)
        lock10 = float(getattr(r, "lock_top10", 38.0) if pd.notna(getattr(r, "lock_top10", 38.0)) else 38.0)
        xq_cnt = float(getattr(r, "xq_cnt_tot", 0) if pd.notna(getattr(r, "xq_cnt_tot", 0)) else 0)
        d2_turn = float(getattr(r, "prev_turn", 0.0) if pd.notna(getattr(r, "prev_turn", 0.0)) else 0.0)
        touch_3b = bool(getattr(r, "touch_3b", False))

        def run_zt_hold(sp_idx: int, init_boards: int):
            nonlocal n_miss_5m_zt_hold, n_total_zt_days, n_dbl_dev_triggers, n_hi_open_triggers
            k = sp_idx + 1
            used_imm = False
            boards_done = init_boards
            while k < len(all_dts) and (k - pos <= 18):
                dk = all_dts[k]
                bk = plook.get((c6, dk))
                if not bk:
                    k += 1; continue
                ok, hk, lk, ck, pck, ztk, dtk, iztk, idtk, iyzk, iyzdtk, turnk, _ = bk
                if iyzdtk:
                    k += 1; continue
                if k > sp_idx + 1:
                    pb = plook.get((c6, all_dts[k - 1]))
                    if pb and (pb[10] or pb[8]):
                        return (ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 925

                # Stage B1: High open exit
                if cfg.hi_open_th is not None:
                    scope_ok = (k == pos + 1) if cfg.hi_open_scope == "d4_only" else True
                    if scope_ok:
                        op_r = ok / pck - 1.0 if pck > 0 else 0.0
                        if (op_r > cfg.hi_open_th) and (ok < ztk - 0.005) and (ok > dtk + 0.005):
                            n_hi_open_triggers += 1
                            return (ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 925

                # Stage B2: Double severe abnormal volatility buffer price
                pl_dev = 99999.0
                if (cfg.dbl_dev_buf is not None) and (boards_done >= cfg.dbl_dev_min_board):
                    pl_dev = get_double_dev_px(sh_c6, dk, all_dts[k - 1], imap, cfg.dbl_dev_buf, cfg.dbl_dev_causal_prev_idx)
                    if ok >= pl_dev and ok > dtk + 0.005:
                        n_dbl_dev_triggers += 1
                        return (ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 925

                # Intraday 5m monitoring
                n_total_zt_days += 1
                arr = b5m.get((c6, dk))
                has_5m = (arr is not None and len(arr) > 0)
                if not has_5m:
                    n_miss_5m_zt_hold += 1

                if has_5m:
                    pk = ok
                    cv = ca = 0.0
                    touched_zt_day = (ok >= ztk - 0.01)
                    zt_at_1030 = False
                    seen_1030 = False

                    for bi in range(len(arr)):
                        row5 = arr[bi]
                        hh, bo, bh, bl, bc, bv, ba = (
                            int(row5[0]), float(row5[1]), float(row5[2]),
                            float(row5[3]), float(row5[4]), float(row5[5]), float(row5[6])
                        )
                        cv += bv; ca += ba
                        vw = ca / cv if cv > 0 else bc

                        if bh <= dtk + 0.005:
                            # Limit down locked on this bar; still update pk/touched? pk stays <= dtk
                            continue

                        # Double dev intraday check first (pre-placed limit order)
                        if pl_dev < 99990.0 and bh >= pl_dev:
                            px_d = max(bo, pl_dev)
                            if px_d > dtk + 0.005:
                                n_dbl_dev_triggers += 1
                                return (px_d / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh

                        # Stage C intraday logic
                        if cfg.c_mode == "grid" and cfg.c_start_hhmm <= 1500:
                            if hh >= cfg.c_start_hhmm:
                                pk_hit = (pk >= ztk - 0.01) if cfg.c_peak_th == "zt" else (pk >= pck * (1.0 + float(cfg.c_peak_th)))
                                if pk_hit and (bc < ztk - 0.01):
                                    if cfg.c_drop_th == "vwap":
                                        if bc < vw:
                                            if bi + 1 < len(arr):
                                                px_x = float(arr[bi + 1, 1])
                                                hh_x = int(arr[bi + 1, 0])
                                            else:
                                                px_x, hh_x = bc, hh
                                            if px_x > dtk + 0.005:
                                                return (px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh_x
                                    elif cfg.c_drop_th == "draw4":
                                        trig = pk * 0.96
                                        if bl <= trig:
                                            px_x = min(bo, trig)
                                            if px_x > dtk + 0.005:
                                                return (px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh
                                    else:
                                        trig = pck * (1.0 + float(cfg.c_drop_th))
                                        if bl <= trig:
                                            px_x = min(bo, trig)
                                            if px_x > dtk + 0.005:
                                                return (px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh

                        elif cfg.c_mode == "1to2_vwap1030_rush1430":
                            if hh == 1030 and not seen_1030:
                                seen_1030 = True
                                if bc >= ztk - 0.01:
                                    zt_at_1030 = True
                                elif cfg.c_use_1030_vwap_in_1to2 and (bc < vw):
                                    px_x = float(arr[bi + 1, 1]) if bi + 1 < len(arr) else bc
                                    hh_x = int(arr[bi + 1, 0]) if bi + 1 < len(arr) else hh
                                    if px_x > dtk + 0.005:
                                        return (px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh_x
                            elif seen_1030 and zt_at_1030 and hh >= 1430 and bc < ztk - 0.01:
                                if bi + 1 < len(arr):
                                    px_x = float(arr[bi + 1, 1])
                                    hh_x = int(arr[bi + 1, 0])
                                    if px_x > dtk + 0.005:
                                        return (px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh_x

                        elif cfg.c_mode == "rush1430_after_zt":
                            if hh >= 1430 and touched_zt_day and bc < ztk - 0.01:
                                if bi + 1 < len(arr):
                                    px_x = float(arr[bi + 1, 1])
                                    hh_x = int(arr[bi + 1, 0])
                                    if px_x > dtk + 0.005:
                                        return (px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh_x

                        elif cfg.c_mode == "rush1430_after_1030zt":
                            if hh == 1030:
                                zt_at_1030 = (bc >= ztk - 0.01)
                            if hh >= 1430 and zt_at_1030 and bc < ztk - 0.01:
                                if bi + 1 < len(arr):
                                    px_x = float(arr[bi + 1, 1])
                                    hh_x = int(arr[bi + 1, 0])
                                    if px_x > dtk + 0.005:
                                        return (px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh_x

                        if bh > pk:
                            pk = bh
                        if bh >= ztk - 0.01:
                            touched_zt_day = True
                else:
                    # Fallback if 5m missing and double dev high hit
                    if pl_dev < 99990.0 and hk >= pl_dev and pl_dev > dtk + 0.005:
                        n_dbl_dev_triggers += 1
                        return (pl_dev / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 1030

                if iztk:
                    boards_done += 1
                    k += 1; continue
                if idtk:
                    k += 1; continue
                if (not used_imm) and _check_immunity(cfg.d_mode, ok, ck, pck, turnk, lock10):
                    used_imm = True
                    k += 1; continue
                return (ck / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 1500
            return float(r.ret_opn_cc), str(r.exit_dt_cc), int(r.exit_hh_cc)

        # Case 1: Sealed 3-board on Buy day (Day3)
        if b3[7]:
            rv, edv, ehv = run_zt_hold(pos, 3)
            rets.append(rv); eds.append(edv); ehs.append(ehv)
            continue

        # Case 2: Unsealed 3-board on Buy day (~sealed_3b)
        # First check D3 stop condition (takes effect on first non-yizi_dt day)
        d3_ret_vs_c2 = c3 / float(r.prev_close) - 1.0
        want_d3_stop_0925 = False
        want_d3_stop_1030 = False
        if cfg.unsealed_mode == "d3_stop_0925":
            if cfg.d3_stop_dt_only:
                want_d3_stop_0925 = bool(idt3)
            else:
                want_d3_stop_0925 = (d3_ret_vs_c2 <= cfg.d3_stop_pct) or bool(idt3)
        elif cfg.unsealed_mode == "d3_stop_1030_vwap":
            want_d3_stop_1030 = (d3_ret_vs_c2 <= cfg.d3_stop_pct) or bool(idt3)

        k = pos + 1
        while k < len(all_dts):
            bk = plook.get((c6, all_dts[k]))
            if bk and not bk[10]:
                break
            k += 1
        if k >= len(all_dts):
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        dk = all_dts[k]
        ok, hk, lk, ck, pck, ztk, dtk, iztk, idtk, iyzk, iyzdtk, turnk, _ = plook[(c6, dk)]

        if k > pos + 1:
            # Deferred past yizi_dt on D4 -> sell at first non-yizi_dt open
            rets.append((ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(925)
            continue

        # Here k == pos + 1 (Day4, non-yizi_dt)
        n_total_d4_unseal += 1
        arr4 = b5m.get((c6, dk))
        if arr4 is None or len(arr4) < 12:
            n_miss_5m_d4_unseal += 1

        if cfg.unsealed_mode == "v10_cut05":
            if (ok / c3 - 1.0) < 0.005:
                rets.append((ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(925)
                continue
        elif want_d3_stop_0925:
            rets.append((ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(925)
            continue
        elif cfg.unsealed_mode in ("vwap_1030", "vwap_1000", "vwap_1100",
                                   "vwap_1030_exempt_v1", "vwap_1030_exempt_v2",
                                   "vwap_1030_exempt_v3") or want_d3_stop_1030:
            do_check = True
            if cfg.unsealed_mode == "vwap_1030_exempt_v1":
                do_check = (xq_cnt >= 1) or (c3 < o3)
            elif cfg.unsealed_mode == "vwap_1030_exempt_v2":
                do_check = (xq_cnt >= 4) or (touch_3b and c3 < o3) or (c3 < o3 and turn3 > d2_turn * 1.2)
            elif cfg.unsealed_mode == "vwap_1030_exempt_v3":
                do_check = (c3 < o3)

            target_hh = 1000 if cfg.unsealed_mode == "vwap_1000" else (1100 if cfg.unsealed_mode == "vwap_1100" else 1030)
            if do_check and (arr4 is not None and len(arr4) >= 12):
                idx_t = -1; cv = ca = 0.0
                for bi in range(len(arr4)):
                    cv += float(arr4[bi, 5]); ca += float(arr4[bi, 6])
                    if int(arr4[bi, 0]) == target_hh:
                        idx_t = bi; break
                if idx_t >= 0:
                    bc_t = float(arr4[idx_t, 4])
                    vw_t = ca / cv if cv > 0 else bc_t
                    if (bc_t < ztk - 0.01) and (bc_t < vw_t):
                        px_x = float(arr4[idx_t + 1, 1]) if idx_t + 1 < len(arr4) else bc_t
                        hh_x = int(arr4[idx_t + 1, 0]) if idx_t + 1 < len(arr4) else target_hh
                        if px_x > dtk + 0.005:
                            n_vwap1030_triggers += 1
                            rets.append((px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(hh_x)
                            continue
        elif cfg.unsealed_mode == "tp_limit":
            if cfg.tp_cond == "c3_gt_o3":
                cond_red = (c3 > o3)
            elif cfg.tp_cond == "c3_gt_o3_and_c2":
                cond_red = (c3 > o3) and (c3 > float(r.prev_close))
            else:
                cond_red = (c3 > float(r.prev_close))
            if cond_red:
                tp_px = round(buy_px * (1.0 + cfg.tp_pct), 2)
                if ok >= tp_px and ok > dtk + 0.005:
                    n_tp_triggers += 1
                    rets.append((ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(925)
                    continue
                if arr4 is not None and len(arr4) > 0:
                    hit_tp = False
                    for row5 in arr4:
                        hh, bo, bh = int(row5[0]), float(row5[1]), float(row5[2])
                        if bh >= tp_px and max(bo, tp_px) > dtk + 0.005:
                            px_x = max(bo, tp_px)
                            n_tp_triggers += 1
                            rets.append((px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(hh)
                            hit_tp = True
                            break
                    if hit_tp:
                        continue
                elif hk >= tp_px and tp_px > dtk + 0.005:
                    n_tp_triggers += 1
                    rets.append((tp_px / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(1030)
                    continue

        # Standard D4 EOD outcomes (reversal ZT -> chain, exact limit-down -> defer, else 15:00 close)
        if iztk:
            rv, edv, ehv = run_zt_hold(k, 1)
            rets.append(rv); eds.append(edv); ehs.append(ehv)
        elif idtk:
            m = k + 1
            sold = False
            while m < len(all_dts):
                bm = plook.get((c6, all_dts[m]))
                if bm and not bm[10]:
                    rets.append((bm[0] / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(all_dts[m]); ehs.append(925)
                    sold = True; break
                m += 1
            if not sold:
                rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
        else:
            rets.append((ck / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(1500)

    if strict_assert:
        for idx_i, r in enumerate(df.itertuples(index=False)):
            ed, eh = eds[idx_i], ehs[idx_i]
            bk = plook.get((str(r.code).zfill(6), ed))
            if bk:
                assert not bk[10], f"Sold on yizi_dt violation: {r.code} {ed}"
                if eh == 1500 and ed < all_dts[-1]:
                    assert not bk[8], f"Sold at 15:00 on EOD exact limit-down violation: {r.code} {ed}"

    stats_d = {
        "n_total_d4_unseal": n_total_d4_unseal,
        "n_miss_5m_d4_unseal": n_miss_5m_d4_unseal,
        "n_total_zt_days": n_total_zt_days,
        "n_miss_5m_zt_hold": n_miss_5m_zt_hold,
        "n_dbl_dev_triggers": n_dbl_dev_triggers,
        "n_hi_open_triggers": n_hi_open_triggers,
        "n_tp_triggers": n_tp_triggers,
        "n_vwap1030_triggers": n_vwap1030_triggers,
    }
    return rets, eds, ehs, stats_d


def sim_single_slot(sub: pd.DataFrame, sc_col: str, rcol: str, ecol: str, hcol: str) -> pd.DataFrame:
    if sub.empty:
        return pd.DataFrame()
    srt = sub.sort_values(["buy_date", sc_col, "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True])
    taken, free_dt, free_hh = [], "", 0
    for r in srt.itertuples(index=False):
        bd = str(r.buy_date)
        if (not free_dt) or (bd > free_dt) or (bd == free_dt and 925 > free_hh):
            assert bool(r.buyable_open) and (not bool(r.prev_is_yizi)), f"Yizi buy violation: {r.code} {bd}"
            bp = round(float(r.prev_close) * (1.0 + float(r.open_pct)), 2)
            nr = float(getattr(r, rcol))
            ep = round(bp * (1.0 + nr) / (1.0 - FEE_ROUNDTRIP), 2)
            ed, eh = str(getattr(r, ecol)), int(getattr(r, hcol))
            taken.append({
                "code": str(r.code).zfill(6), "name": str(r.name), "buy_date": bd, "buy_hhmm": 925,
                "buy_price": bp, "exit_date": ed, "exit_hhmm": eh, "exit_price": ep,
                "net_ret": nr, "score": int(round(float(getattr(r, sc_col)))),
                "open_pct": round(float(r.open_pct), 4), "sealed_3b": bool(r.sealed_3b),
                "plate": str(r.plate), "plate_sz": int(r.plate_sz),
            })
            free_dt, free_hh = ed, eh
    out = pd.DataFrame(taken)
    if not out.empty:
        assert (out["exit_date"] > out["buy_date"]).all(), "T+0 violation!"
        for i in range(1, len(out)):
            p, c = out.iloc[i - 1], out.iloc[i]
            assert (c["buy_date"] > p["exit_date"]) or (c["buy_date"] == p["exit_date"] and c["buy_hhmm"] > p["exit_hhmm"]), "Overlap violation!"
    return out


def calc_nav_cap10m(rr: np.ndarray) -> dict:
    n = len(rr)
    if n == 0:
        return {"trades": 0, "win_rate_pct": 0.0, "plr": 0.0, "mean_ret_pct": 0.0, "nav": 1.0, "ret_pct": 0.0, "max_dd_pct": 0.0, "cap10m_mult": 1.0, "cap10m_ret_pct": 0.0}
    w, l = rr[rr > 0], rr[rr <= 0]
    wr = float((rr > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    nc = np.cumprod(1.0 + rr)
    pk = np.maximum.accumulate(np.insert(nc, 0, 1.0))[1:]
    mdd = float(np.max((pk - nc) / pk) * 100.0)
    cap = 1000.0
    for x in rr:
        cap += min(cap, 1000.0) * float(x)
    return {
        "trades": int(n), "win_rate_pct": round(wr, 2), "plr": round(plr, 2),
        "mean_ret_pct": round(float(rr.mean() * 100.0), 2), "nav": round(float(nc[-1]), 2),
        "ret_pct": round((float(nc[-1]) - 1.0) * 100.0, 2), "max_dd_pct": round(mdd, 2),
        "cap10m_mult": round(cap / 1000.0, 2), "cap10m_ret_pct": round((cap / 1000.0 - 1.0) * 100.0, 2),
    }


def eval_variant(df_sub: pd.DataFrame, plook: dict, stk_hist: dict, b5m: dict, all_dts: list, dt_idx: dict,
                 idx_sh: dict, idx_sz: dict, cfg: ExitConfig, csi_map: dict, th_list=(90, 96)) -> dict:
    """Evaluate a single ExitConfig on IS (early/late/full), OOS, and 5Y for Std90 and Strict96."""
    rets, eds, ehs, st = sim_exit_all(df_sub, plook, stk_hist, b5m, all_dts, dt_idx, idx_sh, idx_sz, cfg, strict_assert=True)
    w = df_sub.copy()
    w["r_x"] = rets
    w["ed_x"] = eds
    w["eh_x"] = ehs

    out = {"name": cfg.name, "cfg": asdict(cfg), "coverage_stats": st}
    win_defs = [
        ("IS_21_23", "2021-01-01", "2023-12-31", -34.16),
        ("IS_early", "2021-01-01", "2022-06-30", 0.0),
        ("IS_late", "2022-07-01", "2023-12-31", 0.0),
        ("OOS_24_26", "2024-01-01", "2026-11-16", csi_map["近三年(2024-01-01起)"][0]),
        ("5Y_211116", "2021-11-16", "2026-11-16", csi_map["全五年(2021-11-16起)"][0]),
        ("3Y_231116", "2023-11-16", "2026-11-16", csi_map["近三年(2023-11-16起)"][0]),
        ("2026_YTD", "2026-01-01", "2026-11-16", csi_map["2026全年"][0]),
        ("2026_Jul", "2026-07-01", "2026-11-16", csi_map["2026年7月以来"][0]),
    ]

    for th in th_list:
        sub_th = w[w["score_v2"] >= th]
        led_full = sim_single_slot(sub_th, "score_v2", "r_x", "ed_x", "eh_x")
        led_5y = sim_single_slot(sub_th[sub_th["buy_date"] >= CANON_5Y_START], "score_v2", "r_x", "ed_x", "eh_x")
        t_res = {}
        for wn, sdt, edt, csip in win_defs:
            use_5y = wn in ("5Y_211116", "3Y_231116", "2026_YTD", "2026_Jul")
            led_w = (led_5y if use_5y else led_full)
            led_w = led_w[(led_w["buy_date"] >= sdt) & (led_w["buy_date"] <= edt)] if not led_w.empty else led_w
            sa = sub_th[(sub_th["buy_date"] >= sdt) & (sub_th["buy_date"] <= edt)]
            rr = led_w["net_ret"].to_numpy(dtype=float) if not led_w.empty else np.array([])
            m = calc_nav_cap10m(rr)
            ew = float(np.prod(1.0 + sa.groupby("buy_date")["r_x"].mean().sort_index().to_numpy())) if len(sa) else 1.0
            ex3 = float(np.prod(1.0 + np.sort(rr)[:-3])) if len(rr) > 3 else 1.0
            ex5 = float(np.prod(1.0 + np.sort(rr)[:-5])) if len(rr) > 5 else 1.0
            m["eq_nav"] = round(ew, 2)
            m["trim3_nav"] = round(ex3, 2)
            m["trim5_nav"] = round(ex5, 2)
            m["csi300_pct"] = round(csip, 2)
            m["excess_slot_pp"] = round(m["ret_pct"] - csip, 2)
            t_res[wn] = m
        out[f"th_{th}"] = t_res
    return out
