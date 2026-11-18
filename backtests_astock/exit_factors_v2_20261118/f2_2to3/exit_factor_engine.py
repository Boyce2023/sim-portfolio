#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Dynamic cross-strategy exit simulation engine for 二进三 V2.0 (s_2to3).
Zero lookahead, exact float match to s2_2to3_exit/exit_engine.py on Base_V20 and Opt_V21,
supports per-holding-day dynamic exit factor policies on Path 1 (~sealed_3b) and Path 2 (ZT chain).
"""

import os
import sys
import math
from typing import Callable, Any
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"

S2_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_opt_20261118/s2_2to3_exit"
sys.path.insert(0, S2_DIR)
import exit_engine as base_ee

FEE_ROUNDTRIP = base_ee.FEE_ROUNDTRIP
CANON_5Y_START = base_ee.CANON_5Y_START
DATA_AS_OF_EXPECTED = base_ee.DATA_AS_OF_EXPECTED


def sim_exit_policy(
    df: pd.DataFrame,
    sig_factors: dict,
    plook: dict,
    stk_hist: dict,
    b5m: dict,
    all_dts: list,
    dt_idx: dict,
    idx_sh: dict,
    idx_sz: dict,
    base_c_drop: float = 0.065,
    base_c_peak: float = 0.085,
    base_c_start: int = 1345,
    base_hi_open: float = 0.092,
    unsealed_policy: Callable[[Any, dict, dict], str] | None = None,
    zt_day_policy: Callable[[Any, dict, dict, int, int], dict] | None = None,
    imm_policy: Callable[[Any, dict, dict, tuple], bool] | None = None,
    strict_assert: bool = True,
) -> tuple[list, list, list, dict]:
    """
    Simulate exits for all rows in df with optional per-day dynamic policies.
    - unsealed_policy(row, meta, d4_day_f) -> "hold_eod" | "sell_0925" | "vwap_1030" | "vwap_1000" | "vwap_1100" | "tp_050" | "tp_060"
    - zt_day_policy(row, meta, dk_day_f, boards_done, step_from_sp) -> dict of overrides:
        sell_0925 (bool), vwap_1030 (bool), c_start_hhmm, c_peak_th, c_drop_th, c_mode,
        dbl_dev_buf (float|None), tp_pct (float|None), allow_imm (bool), hi_open_th (float|None)
    - imm_policy(row, meta, dk_day_f, bk_tuple) -> bool (True = grant immunity on breaking close)
    """
    rets, eds, ehs = [], [], []
    n_unseal_trig = 0
    n_zt_trig = 0
    n_imm_revoked = 0

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

        buy_px = round(float(r.prev_close) * (1.0 + float(r.open_pct)), 2)
        imap = idx_sh if c6.startswith("60") else idx_sz
        sh_c6 = stk_hist.get(c6)
        sf_entry = sig_factors.get((c6, bd), {"meta": {}, "days": {}})
        meta = sf_entry["meta"]
        days_f = sf_entry["days"]

        def run_zt_hold(sp_idx: int, init_boards: int):
            nonlocal n_zt_trig, n_imm_revoked
            k = sp_idx + 1
            used_imm = False
            boards_done = init_boards
            while k < len(all_dts) and (k - pos <= 18):
                dk = all_dts[k]
                bk = plook.get((c6, dk))
                if not bk:
                    k += 1
                    continue
                ok, hk, lk, ck, pck, ztk, dtk, iztk, idtk, iyzk, iyzdtk, turnk, _ = bk
                if iyzdtk:
                    k += 1
                    continue
                if k > sp_idx + 1:
                    pb = plook.get((c6, all_dts[k - 1]))
                    if pb and (pb[10] or pb[8]):
                        return (ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 925

                day_f = days_f.get(dk, {})
                pol = zt_day_policy(r, meta, day_f, boards_done, k - sp_idx) if zt_day_policy else {}
                if pol.get("triggered", False):
                    n_zt_trig += 1

                # 1. Policy forced 09:25 sell (non-limit-down open)
                if pol.get("sell_0925", False) and (ok > dtk + 0.005):
                    return (ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 925

                # 2. High open exit on D4 (or all_boards if specified)
                hi_th = pol.get("hi_open_th", base_hi_open)
                hi_scope_all = pol.get("hi_open_all_boards", False)
                if hi_th is not None and ((k == pos + 1) or hi_scope_all):
                    op_r = ok / pck - 1.0 if pck > 0 else 0.0
                    if (op_r > hi_th) and (ok < ztk - 0.005) and (ok > dtk + 0.005):
                        return (ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 925

                # 3. Conditional double severe abnormal volatility buffer price
                pl_dev = 99999.0
                dbl_buf = pol.get("dbl_dev_buf", None)
                if dbl_buf is not None:
                    pl_dev = base_ee.get_double_dev_px(sh_c6, dk, all_dts[k - 1], imap, dbl_buf, True)
                    if ok >= pl_dev and ok > dtk + 0.005:
                        return (ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 925

                # 4. Conditional limit take-profit (e.g. > +5% on D4 rotten 3-board)
                tp_pct = pol.get("tp_pct", None)
                tp_px = round(pck * (1.0 + tp_pct), 2) if (tp_pct is not None and pck > 0) else 99999.0
                if tp_pct is not None and ok >= tp_px and ok < ztk - 0.005 and ok > dtk + 0.005:
                    return (ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 925

                # 5. Intraday 5m monitoring
                c_mode = pol.get("c_mode", "grid")
                c_start = pol.get("c_start_hhmm", base_c_start)
                c_peak = pol.get("c_peak_th", base_c_peak)
                c_drop = pol.get("c_drop_th", base_c_drop)
                vwap_1030_on = pol.get("vwap_1030", False)

                arr = b5m.get((c6, dk))
                if arr is not None and len(arr) > 0:
                    pk = ok
                    cv = ca = 0.0
                    seen_1030 = False
                    touched_zt_day = (ok >= ztk - 0.01)

                    for bi in range(len(arr)):
                        row5 = arr[bi]
                        hh, bo, bh, bl, bc, bv, ba = (
                            int(row5[0]), float(row5[1]), float(row5[2]),
                            float(row5[3]), float(row5[4]), float(row5[5]), float(row5[6])
                        )
                        cv += bv; ca += ba
                        vw = ca / cv if cv > 0 else bc

                        if bh <= dtk + 0.005:
                            continue

                        if pl_dev < 99990.0 and bh >= pl_dev:
                            px_d = max(bo, pl_dev)
                            if px_d > dtk + 0.005:
                                return (px_d / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh

                        if tp_pct is not None and bh >= tp_px and max(bo, tp_px) < ztk - 0.005 and max(bo, tp_px) > dtk + 0.005:
                            px_t = max(bo, tp_px)
                            return (px_t / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh

                        if vwap_1030_on and hh == 1030 and not seen_1030:
                            seen_1030 = True
                            if (bc < ztk - 0.01) and (bc < vw):
                                px_x = float(arr[bi + 1, 1]) if bi + 1 < len(arr) else bc
                                hh_x = int(arr[bi + 1, 0]) if bi + 1 < len(arr) else 1030
                                if px_x > dtk + 0.005:
                                    return (px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh_x

                        if c_mode == "grid" and c_start <= 1500 and hh >= c_start:
                            pk_hit = (pk >= ztk - 0.01) if c_peak == "zt" else (pk >= pck * (1.0 + float(c_peak)))
                            if pk_hit and (bc < ztk - 0.01):
                                if c_drop == "vwap":
                                    if bc < vw:
                                        px_x = float(arr[bi + 1, 1]) if bi + 1 < len(arr) else bc
                                        hh_x = int(arr[bi + 1, 0]) if bi + 1 < len(arr) else hh
                                        if px_x > dtk + 0.005:
                                            return (px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh_x
                                elif c_drop == "draw4":
                                    trig = pk * 0.96
                                    if bl <= trig:
                                        px_x = min(bo, trig)
                                        if px_x > dtk + 0.005:
                                            return (px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh
                                else:
                                    trig = pck * (1.0 + float(c_drop))
                                    if bl <= trig:
                                        px_x = min(bo, trig)
                                        if px_x > dtk + 0.005:
                                            return (px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh

                        elif c_mode == "rush1430_after_zt":
                            if hh >= 1430 and touched_zt_day and bc < ztk - 0.01:
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
                    if pl_dev < 99990.0 and hk >= pl_dev and pl_dev > dtk + 0.005:
                        return (pl_dev / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 1030

                if iztk:
                    boards_done += 1
                    k += 1
                    continue
                if idtk:
                    k += 1
                    continue

                # Breaking day EOD immunity check
                base_imm = (ck > ok) and (ck >= pck)
                allow_imm = pol.get("allow_imm", True)
                if imm_policy is not None:
                    imm_ok = imm_policy(r, meta, day_f, bk)
                    if base_imm and not imm_ok:
                        n_imm_revoked += 1
                else:
                    imm_ok = base_imm and allow_imm
                    if base_imm and not allow_imm:
                        n_imm_revoked += 1

                if (not used_imm) and imm_ok:
                    used_imm = True
                    k += 1
                    continue
                return (ck / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 1500
            return float(r.ret_opn_cc), str(r.exit_dt_cc), int(r.exit_hh_cc)

        # Case 1: Sealed 3-board on Buy day (D3)
        if b3[7]:
            rv, edv, ehv = run_zt_hold(pos, 3)
            rets.append(rv); eds.append(edv); ehs.append(ehv)
            continue

        # Case 2: Unsealed 3-board on Buy day (~sealed_3b)
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
            rets.append((ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(925)
            continue

        d4_day_f = days_f.get(dk, {})
        act = unsealed_policy(r, meta, d4_day_f) if unsealed_policy else "hold_eod"
        if act != "hold_eod":
            n_unseal_trig += 1

        if act == "sell_0925":
            rets.append((ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(925)
            continue

        arr4 = b5m.get((c6, dk))
        if act in ("vwap_1030", "vwap_1000", "vwap_1100"):
            target_hh = 1000 if act == "vwap_1000" else (1100 if act == "vwap_1100" else 1030)
            if arr4 is not None and len(arr4) >= 12:
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
                            rets.append((px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(hh_x)
                            continue
        elif act.startswith("tp_"):
            tp_pct = float(act.split("_")[1]) / 1000.0
            tp_px = round(buy_px * (1.0 + tp_pct), 2)
            if ok >= tp_px and ok > dtk + 0.005:
                rets.append((ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(925)
                continue
            if arr4 is not None and len(arr4) > 0:
                hit_tp = False
                for row5 in arr4:
                    hh, bo, bh = int(row5[0]), float(row5[1]), float(row5[2])
                    if bh >= tp_px and max(bo, tp_px) > dtk + 0.005:
                        px_x = max(bo, tp_px)
                        rets.append((px_x / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(hh)
                        hit_tp = True; break
                if hit_tp:
                    continue

        # Standard D4 EOD outcomes
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

    return rets, eds, ehs, {
        "n_unseal_trig": n_unseal_trig,
        "n_zt_trig": n_zt_trig,
        "n_imm_revoked": n_imm_revoked,
    }


def eval_pools(
    df84: pd.DataFrame,
    rets: list,
    eds: list,
    ehs: list,
    csi_canon: dict,
    pools=(84, 86, 90, 96),
) -> dict:
    """Evaluate single-slot, equal-weight, MDD, WR, PLR on IS (early/late/full), OOS, and 5Y for all pools."""
    w = df84.copy()
    w["r_x"] = rets
    w["ed_x"] = eds
    w["eh_x"] = ehs

    win_defs = [
        ("IS_21_23", "2021-01-01", "2023-12-31", -34.16, False),
        ("IS_early", "2021-01-01", "2022-06-30", 0.0, False),
        ("IS_late", "2022-07-01", "2023-12-31", 0.0, False),
        ("OOS_24_26", "2024-01-01", "2026-11-16", csi_canon["近三年(2024-01-01起)"][0], False),
        ("5Y_211116", "2021-11-16", "2026-11-16", csi_canon["全五年(2021-11-16起)"][0], True),
    ]

    out = {}
    for th in pools:
        sub_th = w[w["score_v2"] >= th]
        led_full = base_ee.sim_single_slot(sub_th, "score_v2", "r_x", "ed_x", "eh_x")
        led_5y = base_ee.sim_single_slot(sub_th[sub_th["buy_date"] >= CANON_5Y_START], "score_v2", "r_x", "ed_x", "eh_x")
        t_res = {}
        for wn, sdt, edt, csip, u5 in win_defs:
            led_w = led_5y if u5 else led_full
            led_w = led_w[(led_w["buy_date"] >= sdt) & (led_w["buy_date"] <= edt)] if not led_w.empty else led_w
            sa = sub_th[(sub_th["buy_date"] >= sdt) & (sub_th["buy_date"] <= edt)]
            rr = led_w["net_ret"].to_numpy(dtype=float) if not led_w.empty else np.array([])
            m = base_ee.calc_nav_cap10m(rr)
            ew = float(np.prod(1.0 + sa.groupby("buy_date")["r_x"].mean().sort_index().to_numpy())) if len(sa) else 1.0
            ex3 = float(np.prod(1.0 + np.sort(rr)[:-3])) if len(rr) > 3 else 1.0
            m["eq_nav"] = round(ew, 2)
            m["trim3_nav"] = round(ex3, 2)
            m["raw_n"] = int(len(sa))
            m["excess_slot_pp"] = round(m["ret_pct"] - csip, 2)
            t_res[wn] = m
        out[f"th_{th}"] = t_res
    return out
