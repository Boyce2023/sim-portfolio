#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 Track 1 simulator: exact max_gain_to_100(t), next_mg100(t), V2_A/V2_B/V2_C extraction."""
import json
import sys
import numpy as np

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

RD045_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd045_abn_v2_bse_v2_refinement_20261126"
if RD045_DIR not in sys.path:
    sys.path.insert(0, RD045_DIR)
import _rd045_common as cm


def compute_mg100_arrays(
    dts: np.ndarray, dev_d: dict, cn_sev_dts: set[str]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Strictly causal daily headroom arrays:
      - mg100_pre[t]: max % gain at day t using t-1 index chain (known 09:25 pre-open)
      - mg100_eod[t]: max % gain at day t using realized day-t index chain
      - next_mg100[t]: theoretical max % gain for t+1 known at day t close using chain[t]
    """
    ac, chain, fl = dev_d["ac"], dev_d["chain"], dev_d["floor_arr"]
    dev_c = dev_d["dev_c"]
    n = len(dts)
    mg_pre = np.full(n, 100.0, dtype=np.float64)
    mg_eod = np.full(n, 100.0, dtype=np.float64)
    nxt_mg = np.full(n, 100.0, dtype=np.float64)

    for t in range(1, n):
        lo_b = max(int(fl[t]), t - 10)
        if lo_b <= t - 1 and ac[t - 1] > 0:
            ratios_ac = ac[lo_b:t] / ac[t - 1]
            c_pre = ratios_ac * (1.0 + chain[t - 1] / chain[lo_b:t]) - 1.0
            c_eod = ratios_ac * (1.0 + chain[t] / chain[lo_b:t]) - 1.0
            mg_pre[t] = float(np.min(c_pre) * 100.0)
            mg_eod[t] = float(np.min(c_eod) * 100.0)

        # Next day (t+1) theoretical ceiling known at close of day t
        is_reset_t = (dev_c[t] >= 100.0) or (str(dts[t]) in cn_sev_dts and dev_c[t] >= 95.0)
        if is_reset_t:
            nxt_mg[t] = 100.0
        else:
            lo_n = max(int(fl[t]), t - 9)
            if lo_n <= t and ac[t] > 0:
                ratios_nxt = ac[lo_n:t + 1] / ac[t]
                c_nxt = ratios_nxt * (1.0 + chain[t] / chain[lo_n:t + 1]) - 1.0
                nxt_mg[t] = float(np.min(c_nxt) * 100.0)
    return mg_pre, mg_eod, nxt_mg


def simulate_exits_v2(
    b: int, n: int, op: np.ndarray, hi: np.ndarray, lo: np.ndarray, cl: np.ndarray, af: np.ndarray,
    ac: np.ndarray, dts: np.ndarray, zt: np.ndarray, dt_f: np.ndarray, yzd: np.ndarray, ma5: np.ndarray,
    buy_at_close: bool = False,
) -> dict:
    """Simulate exits from open[b] (buy_at_close=False) or close[b] (buy_at_close=True)."""
    buy_px = cl[b] if buy_at_close else op[b]
    if b + 1 >= n or buy_px <= 0 or af[b] <= 0:
        return {}
    b_ac = buy_px * af[b]
    out = {}

    def _finish_close(target_k: int, tag: str):
        if target_k >= n:
            return
        k = target_k
        while k < n - 1 and yzd[k]:
            k += 1
        if yzd[k]:
            return
        if k > target_k:
            ex_px, ehh, rsn = op[k], 925, f"{tag}_dt_open"
        elif dt_f[k] and k + 1 < n:
            k2 = k + 1
            while k2 < n - 1 and yzd[k2]:
                k2 += 1
            if yzd[k2]:
                return
            ex_px, ehh, rsn = op[k2], 925, f"{tag}_dt_next_open"
            k = k2
        else:
            ex_px, ehh, rsn = cl[k], 1500, tag
        if ex_px <= 0 or af[k] <= 0:
            return
        gr = (ex_px * af[k]) / b_ac - 1.0
        mtm = cm.build_mtm_pairs_dt(op, cl, af, dts, b, k, ex_px, buy_at_close=buy_at_close)
        out[tag] = {"exit_date": str(dts[k]), "exit_hhmm": ehh, "gross_ret": float(gr), "reason": rsn, "mtm_gross": mtm}

    for h, nm in ((1, "S1_hold1c"), (2, "S2_hold2c"), (3, "S3_hold3c")):
        _finish_close(b + h, nm)

    # S5_ma5_trail: hold while close >= MA5*0.998, up to b+10
    k_ma = -1
    for off in range(1, 11):
        k = b + off
        if k >= n:
            break
        if np.isfinite(ma5[k]) and cl[k] < ma5[k] * 0.998:
            k_ma = k
            break
    if k_ma == -1 and b + 10 < n:
        k_ma = b + 10
    if k_ma > b:
        _finish_close(k_ma, "S5_ma5_trail")

    # S7_lianban: ride ZT from b (if open buy) or b+1 (if close buy)
    start_zt = zt[b + 1] if buy_at_close else zt[b]
    if not start_zt:
        k = b + 1
        while k < n - 1 and yzd[k]:
            k += 1
        if not yzd[k]:
            d0_r = ac[b] / b_ac - 1.0
            d1_or = (op[k] * af[k]) / ac[b] - 1.0
            if (not buy_at_close) and (d0_r <= -0.02 or cl[b] < op[b] or d1_or <= -0.035):
                ex_px, ehh, rsn = op[k], 925, "nonzt_next_open"
            elif dt_f[k] and k + 1 < n:
                k2 = k + 1
                while k2 < n - 1 and yzd[k2]:
                    k2 += 1
                if yzd[k2]:
                    return out
                ex_px, ehh, rsn, k = op[k2], 925, "nonzt_dt_open", k2
            else:
                ex_px, ehh, rsn = cl[k], 1500, "nonzt_next_close"
            gr = (ex_px * af[k]) / b_ac - 1.0
            out["S7_lianban"] = {"exit_date": str(dts[k]), "exit_hhmm": ehh, "gross_ret": float(gr), "reason": rsn, "mtm_gross": cm.build_mtm_pairs_dt(op, cl, af, dts, b, k, ex_px, buy_at_close=buy_at_close)}
    else:
        k = (b + 2) if buy_at_close else (b + 1)
        yang_used = False
        while k < n:
            if zt[k]:
                k += 1
                continue
            is_y = (cl[k] > op[k]) and (ac[k] / ac[k - 1] >= 1.015)
            if is_y and not yang_used and k + 1 < n:
                yang_used = True
                k += 1
                continue
            orig_k = k
            while k < n - 1 and yzd[k]:
                k += 1
            if yzd[k]:
                break
            ex_px, ehh, rsn = (op[k], 925, "delayed_dt_open") if k > orig_k else (cl[k], 1500, "zt_break_close")
            gr = (ex_px * af[k]) / b_ac - 1.0
            out["S7_lianban"] = {"exit_date": str(dts[k]), "exit_hhmm": ehh, "gross_ret": float(gr), "reason": rsn, "mtm_gross": cm.build_mtm_pairs_dt(op, cl, af, dts, b, k, ex_px, buy_at_close=buy_at_close)}
            break
    return out
