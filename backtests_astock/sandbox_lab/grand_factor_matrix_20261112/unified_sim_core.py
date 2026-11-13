#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Unified 32-Factor x 6-Strategy Marginal Lift & Parameter Sensitivity Matrix (100% Apple-to-Apple Ground Truth)."""
import os, sys, json, time, pickle
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from d15_eval_helper import FEE_RATE

with open(f"{CUR_DIR}/code_bars_5y.pkl", "rb") as _f:
    _PKG = pickle.load(_f)
CODE_BARS = _PKG["code_bars"]
IDX_KLINES = _PKG["idx_klines"]


def _exit_after_unsealed_or_hold(c6: str, buy_dt: str, buy_px: float, mode: str):
    cb = CODE_BARS.get(c6)
    if cb is None:
        return None
    pos = cb["date_to_pos"].get(buy_dt, -1)
    n = len(cb["dts"])
    if pos < 0 or pos >= n - 1:
        return None
    adj_b = cb["adjf"][pos]
    if buy_px <= 0 or adj_b <= 0:
        return None

    # Mode: '3to4_feishu' (4-branch break exit)
    if mode == "3to4_feishu":
        if not cb["is_zt"][pos]:
            # Day4 unsealed -> Day5 +2% or close (carry forward if yizi_dt)
            k = pos + 1
            while k < n and cb["is_yizi_dt"][k]:
                k += 1
            if k >= n:
                k = n - 1
            pc = cb["pre_c"][k]
            if cb["open"][k] >= pc * 1.02:
                ep = cb["open"][k]
            elif cb["high"][k] >= pc * 1.02:
                ep = pc * 1.02
            else:
                ep = cb["close"][k]
            return cb["dts"][k], (ep * cb["adjf"][k]) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, k - pos
        k = pos + 1
        while k < n and cb["is_zt"][k]:
            k += 1
        if k >= n:
            k = n - 1
        while k < n and cb["is_yizi_dt"][k]:
            k += 1
        if k >= n:
            k = n - 1
        pc = cb["pre_c"][k]
        ok, hk, lk, ck = cb["open"][k], cb["high"][k], cb["low"][k], cb["close"][k]
        if (ok / pc - 1.0 < 0.015) and (hk >= pc * 1.03):
            ep = max(ok, pc * 1.03)
        elif (hk >= pc * 1.09) and (lk <= pc * 1.065) and (ok > pc * 1.015):
            ep = pc * 1.065
        else:
            ep = ck
        return cb["dts"][k], (ep * cb["adjf"][k]) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, k - pos

    # Mode: '5ban_feishu' (93% yidong early line or Day+3 = 4th holding day close)
    if mode == "5ban_feishu":
        idx_map = IDX_KLINES["sh000002"] if c6.startswith("60") else IDX_KLINES["sz399107"]
        max_k = min(n - 1, pos + 3)
        ep, ex_k = None, max_k
        for k in range(pos + 1, max_k + 1):
            if cb["is_yizi_dt"][k]:
                if k == max_k:
                    while ex_k < n and cb["is_yizi_dt"][ex_k]:
                        ex_k += 1
                    ex_k = min(ex_k, n - 1)
                    ep = cb["open"][ex_k]
                continue
            kd = cb["dts"][k]
            iref = idx_map.get(kd)
            p93 = None
            if iref:
                for back in range(1, min(10, k) + 1):
                    bd = cb["dts"][k - back]
                    bc = cb["close"][k - back] * cb["adjf"][k - back] / cb["adjf"][k]
                    bi = idx_map.get(bd)
                    if bi and bc > 0:
                        cand_p = bc * (1.93 + (iref / bi - 1.0))
                        if p93 is None or cand_p < p93:
                            p93 = cand_p
            if p93 is not None and p93 > cb["pre_c"][k] and cb["high"][k] >= p93:
                ep = max(cb["open"][k], min(p93, cb["high"][k]))
                ex_k = k
                break
        if ep is None:
            ep = cb["close"][ex_k]
        return cb["dts"][ex_k], (ep * cb["adjf"][ex_k]) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, max(1, ex_k - pos)

    # Mode: 'pry_5pct_5d' (touch +5% within 5 days or Day+5 close)
    if mode == "pry_5pct_5d":
        target = buy_px * 1.05
        max_k = min(n - 1, pos + 5)
        ep, ex_k = None, max_k
        for k in range(pos + 1, max_k + 1):
            if cb["is_yizi_dt"][k]:
                continue
            adj_ratio = cb["adjf"][k] / adj_b
            if cb["open"][k] * adj_ratio >= target:
                ep, ex_k = cb["open"][k], k; break
            if cb["high"][k] * adj_ratio >= target:
                ep, ex_k = target / adj_ratio, k; break
        if ep is None:
            while ex_k < n and cb["is_yizi_dt"][ex_k]:
                ex_k += 1
            ex_k = min(ex_k, n - 1)
            ep = cb["close"][ex_k]
        return cb["dts"][ex_k], (ep * cb["adjf"][ex_k]) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, max(1, ex_k - pos)

    # Mode: 'relay_std' (hold while ZT, exit on first unsealed day close; if unsealed on buy day, exit next day close/open<0.5%)
    if not cb["is_zt"][pos]:
        k = pos + 1
        while k < n and cb["is_yizi_dt"][k]:
            k += 1
        k = min(k, n - 1)
        ep = cb["open"][k] if (cb["close"][pos] < cb["open"][pos] or cb["open"][k] < cb["pre_c"][k] * 1.005) else cb["close"][k]
        return cb["dts"][k], (ep * cb["adjf"][k]) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, max(1, k - pos)
    k = pos + 1
    while k < n and cb["is_zt"][k]:
        k += 1
    while k < n and cb["is_yizi_dt"][k]:
        k += 1
    k = min(k, n - 1)
    return cb["dts"][k], (cb["close"][k] * cb["adjf"][k]) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, max(1, k - pos)
