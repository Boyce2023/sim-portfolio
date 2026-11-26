#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD040 event extraction (4 entries x 7 exits), exact daily MTM & causal ST/10d-dev verification."""
import json
import math
import numpy as np


def _calc_mtm_pairs(op: np.ndarray, cl: np.ndarray, af: np.ndarray, mi: np.ndarray,
                    b_idx: int, ex_idx: int, ex_px: float, fee_rt: float) -> list[list]:
    """Build exact daily MTM segment multipliers [trade_date_idx_or_str] so prod == (1+net_ret)."""
    # Store [mkt_idx_int, mult] -> converts cleanly to date/pos in simulator
    if ex_idx <= b_idx or op[b_idx] <= 0 or ex_px <= 0:
        return []
    pairs = []
    m0 = (cl[b_idx] * af[b_idx]) / (op[b_idx] * af[b_idx])
    pairs.append([int(mi[b_idx]), float(m0)])
    for k in range(b_idx + 1, ex_idx):
        mk = (cl[k] * af[k]) / (cl[k - 1] * af[k - 1])
        pairs.append([int(mi[k]), float(mk)])
    mex = (ex_px * af[ex_idx]) / (cl[ex_idx - 1] * af[ex_idx - 1]) * (1.0 - float(fee_rt))
    pairs.append([int(mi[ex_idx]), float(mex)])
    return pairs


def simulate_exits_for_buy(
    b: int, n: int, op: np.ndarray, hi: np.ndarray, lo: np.ndarray, cl: np.ndarray, af: np.ndarray,
    ac: np.ndarray, mi: np.ndarray, dts: np.ndarray, zt: np.ndarray, dt_f: np.ndarray, yzd: np.ndarray,
    imap: dict, floor_arr: np.ndarray, chain: np.ndarray, ma5: np.ndarray
) -> dict:
    """Compute all 7 causal exit rules from buy_idx b (09:25 open buy), respecting T+1 & DT deferral."""
    buy_px = op[b]
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
        gr = (ex_px * af[k]) / b_ac - 1.0
        mtm = _calc_mtm_pairs(op, cl, af, mi, b, k, ex_px, 0.0)
        out[tag] = {"exit_idx": k, "exit_date": str(dts[k]), "exit_hhmm": ehh, "gross_ret": float(gr), "reason": rsn, "mtm_gross": mtm}

    # S1..S4: Fixed 1, 2, 3, 5 trading days close
    for h, nm in ((1, "S1_hold1c"), (2, "S2_hold2c"), (3, "S3_hold3c"), (5, "S4_hold5c")):
        _finish_close(b + h, nm)

    # S5: Break below MA5 close stop (from b+1 up to b+5 close)
    k_ma = -1
    for off in range(1, 6):
        k = b + off
        if k >= n:
            break
        if np.isfinite(ma5[k]) and cl[k] < ma5[k] * 0.998:
            k_ma = k
            break
    if k_ma == -1 and b + 5 < n:
        k_ma = b + 5
    if k_ma > b:
        _finish_close(k_ma, "S5_ma5_stop")

    # S6: Hit 95% 10d dev red-line take-profit (causal p95 from k-1) else b+5 close
    sold_95 = False
    for off in range(1, 6):
        k = b + off
        if k >= n:
            break
        fl_m = mi[floor_arr[k]]
        iprev = imap.get(str(dts[k - 1]))
        # Exact p95 using chain[k-1] / chain[kb]: (ac_k / ac_kb - 1) - (chain[k-1]*1.0 / chain[kb] - 1) >= 0.95
        cands = []
        if iprev:
            for kb in range(max(0, k - 10), k):
                if mi[kb] < fl_m:
                    continue
                cands.append(ac[kb] / af[k] * (0.95 + chain[k - 1] / chain[kb]))
        if cands:
            p95 = math.ceil(min(cands) * 100.0 - 1e-8) / 100.0
            if op[k] >= p95 and not yzd[k]:
                gr = (op[k] * af[k]) / b_ac - 1.0
                mtm = _calc_mtm_pairs(op, cl, af, mi, b, k, op[k], 0.0)
                out["S6_abn95_tp"] = {"exit_idx": k, "exit_date": str(dts[k]), "exit_hhmm": 925, "gross_ret": float(gr), "reason": "95_gap_open", "mtm_gross": mtm}
                sold_95 = True
                break
            if hi[k] >= p95 + 0.01 - 1e-9:
                gr = (p95 * af[k]) / b_ac - 1.0
                mtm = _calc_mtm_pairs(op, cl, af, mi, b, k, p95, 0.0)
                out["S6_abn95_tp"] = {"exit_idx": k, "exit_date": str(dts[k]), "exit_hhmm": 1030, "gross_ret": float(gr), "reason": "95_tick", "mtm_gross": mtm}
                sold_95 = True
                break
    if not sold_95 and b + 5 < n:
        _finish_close(b + 5, "S6_abn95_tp")

    # S7: Lianban / ZT ride (if ZT on buy day ride until break; else sell b+1 open if weak or close)
    if not zt[b]:
        k = b + 1
        while k < n - 1 and yzd[k]:
            k += 1
        if not yzd[k]:
            d0_r = ac[b] / b_ac - 1.0
            d1_or = (op[k] * af[k]) / ac[b] - 1.0
            if d0_r <= -0.02 or cl[b] < op[b] or d1_or <= -0.035:
                ex_px, ehh, rsn = op[k], 925, "nonzt_next_open"
            else:
                ex_px, ehh, rsn = cl[k], 1500, "nonzt_next_close"
            gr = (ex_px * af[k]) / b_ac - 1.0
            out["S7_lianban"] = {"exit_idx": k, "exit_date": str(dts[k]), "exit_hhmm": ehh, "gross_ret": float(gr), "reason": rsn, "mtm_gross": _calc_mtm_pairs(op, cl, af, mi, b, k, ex_px, 0.0)}
    else:
        k = b + 1
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
            out["S7_lianban"] = {"exit_idx": k, "exit_date": str(dts[k]), "exit_hhmm": ehh, "gross_ret": float(gr), "reason": rsn, "mtm_gross": _calc_mtm_pairs(op, cl, af, mi, b, k, ex_px, 0.0)}
            break
    return out


def extract_stock_events(
    c6: str, g_arr: dict, st_mask: np.ndarray, dev_d: dict, imap: dict
) -> list[dict]:
    """Scan one stock causally to extract E1a, E1b, E2, E3 unlock-wave2 candidate events."""
    dts, op, hi, lo, cl, af = g_arr["dts"], g_arr["op"], g_arr["hi"], g_arr["lo"], g_arr["cl"], g_arr["af"]
    r1, opct, amt, trn = g_arr["r1"], g_arr["opct"], g_arr["amt"], g_arr["trn"]
    zt, dt_f, yzz, yzd = g_arr["zt"], g_arr["dt_f"], g_arr["yzz"], g_arr["yzd"]
    age, pc_raw = g_arr["age"], g_arr["pc_raw"]
    ac, ah, mi, chain = dev_d["ac"], dev_d["ah"], dev_d["mi"], dev_d["chain"]
    dev_c, dev_h, proj_flat, open_dev, floor_arr = dev_d["dev_c"], dev_d["dev_h"], dev_d["proj_flat"], dev_d["open_dev"], dev_d["floor_arr"]
    n = len(dts)
    if n < 25:
        return []

    ma5 = np.full(n, np.nan)
    ma10 = np.full(n, np.nan)
    for idx in range(4, n):
        ma5[idx] = np.mean(ac[idx - 4:idx + 1]) / af[idx]
    for idx in range(9, n):
        ma10[idx] = np.mean(ac[idx - 9:idx + 1]) / af[idx]

    events = []
    last_b = {"E1a": -99, "E1b": -99, "E2": -99, "E3": -99}

    for b in range(15, n - 1):
        b_dt = str(dts[b])
        if b_dt < "2021-01-04":
            continue
        if st_mask[b] or age[b] <= 45 or pc_raw[b] < 1.5 or yzz[b] or yzd[b]:
            continue
        if mi[b] - mi[b - 1] > 3:  # Skip direct long-suspension resumption opening day
            continue

        sig = b - 1
        # Search high-pressure window [b-10 .. b-1] strictly prior to b (causal!)
        win_lo = max(0, b - 10)
        win_devs = dev_c[win_lo:b]
        hp_idxs = [win_lo + k for k in range(len(win_devs)) if win_devs[k] >= 85.0 and not st_mask[win_lo + k]]
        if not hp_idxs:
            continue
        p_first, p_last = hp_idxs[0], hp_idxs[-1]
        adj_days = b - p_first
        if adj_days < 2 or adj_days > 9:
            continue
        # Require at least 2 ZT days in the buildup [max(0, p_first-10) .. p_last]
        zt_cnt_wave = int(np.sum(zt[max(0, p_first - 10):p_last + 1]))
        if zt_cnt_wave < 2:
            continue

        peak_dev = float(np.max(dev_c[p_first:p_last + 1]))
        peak_h_dev = float(np.max(dev_h[p_first:p_last + 1]))
        was_hit_100 = 1 if peak_dev >= 100.0 else 0
        peak_ac_hp = float(np.max(ac[p_first:b]))
        peak_amt_hp = float(np.max(amt[max(0, p_first - 2):p_last + 1]))
        dd_from_peak_t1 = float(ac[sig] / peak_ac_hp - 1.0) if peak_ac_hp > 0 else 0.0
        if dd_from_peak_t1 < -0.25:
            continue

        # Wave-start low (pre-runup min close 15d before p_first) & retracement ratio
        pre_lo = float(np.min(ac[max(0, p_first - 15):p_first])) if p_first > 0 else ac[0]
        wave_gain = peak_ac_hp / pre_lo - 1.0 if pre_lo > 0 else 0.5
        retrace_frac = (peak_ac_hp - ac[sig]) / max(1e-6, peak_ac_hp - pre_lo) if peak_ac_hp > pre_lo else 0.0

        rel_actual_sig = peak_dev - float(dev_c[sig])
        rel_proj_b = peak_dev - float(proj_flat[b])
        rel_proj_prev = peak_dev - float(proj_flat[sig])
        vol_shrink_sig = float(amt[sig] / max(1e-4, peak_amt_hp))
        amt_ratio3_sig = float(amt[sig] / max(1e-4, float(np.mean(amt[max(0, sig - 3):sig]))))
        above_ma5 = 1.0 if (np.isfinite(ma5[sig]) and cl[sig] >= ma5[sig] * 0.995) else 0.0
        above_ma10 = 1.0 if (np.isfinite(ma10[sig]) and cl[sig] >= ma10[sig] * 0.995) else 0.0
        room_open_b = 100.0 - float(open_dev[b])

        # Entry checks (strictly causal T-1 or 09:25 open at b)
        is_e1a = (
            (b - p_last <= 3) and (proj_flat[sig] >= 78.0 or dev_c[sig] >= 80.0)
            and (proj_flat[b] <= 84.0) and (rel_proj_b >= 12.0) and (b - last_b["E1a"] >= 8)
        )
        is_e1b = (
            (b - p_last >= 1) and ((rel_actual_sig >= 15.0) or (dev_c[sig] <= 75.0))
            and not ((peak_dev - dev_c[sig - 1] >= 15.0) or (dev_c[sig - 1] <= 75.0))
            and (b - last_b["E1b"] >= 8)
        )
        is_e2 = (
            ((rel_proj_b >= 12.0 and proj_flat[b] <= 84.0) or rel_actual_sig >= 15.0 or dev_c[sig] <= 78.0)
            and (vol_shrink_sig <= 0.85) and (dd_from_peak_t1 >= -0.15) and (not dt_f[sig])
            and (-5.0 <= opct[b] <= 2.0) and (b - last_b["E2"] >= 8)
        )
        hp_high_cl = float(np.max(ac[p_first:sig])) if sig > p_first else ac[p_first]
        is_e3 = (
            (b - p_first >= 3) and (dd_from_peak_t1 >= -0.20)
            and (rel_proj_prev >= 10.0 or dev_c[sig] <= 90.0)
            and (cl[sig] > op[sig]) and (r1[sig] >= 3.0) and (amt_ratio3_sig >= 1.15)
            and (ac[sig] >= hp_high_cl * 0.985) and (b - last_b["E3"] >= 8)
        )

        hit_types = [t for t, fl in (("E1a", is_e1a), ("E1b", is_e1b), ("E2", is_e2), ("E3", is_e3)) if fl]
        if not hit_types:
            continue

        ex_res = simulate_exits_for_buy(b, n, op, hi, lo, cl, af, ac, mi, dts, zt, dt_f, yzd, imap, floor_arr, chain, ma5)
        if not ex_res:
            continue

        base_info = {
            "code": c6, "sig_date": str(dts[sig]), "buy_date": b_dt, "buy_hhmm": 925, "buy_px": round(float(op[b]), 3),
            "is_yizi": False, "abn_peak_dev10": round(peak_dev, 3), "abn_peak_h_dev10": round(peak_h_dev, 3),
            "abn_was_hit_100": int(was_hit_100), "abn_hp_days": int(len(hp_idxs)), "abn_adj_days": int(adj_days),
            "abn_days_since_hp": int(b - p_last), "abn_zt_cnt_wave": int(zt_cnt_wave),
            "abn_sig_dev10": round(float(dev_c[sig]), 3), "abn_proj_flat_b": round(float(proj_flat[b]), 3),
            "abn_rel_actual_pp": round(rel_actual_sig, 3), "abn_rel_proj_pp": round(rel_proj_b, 3),
            "abn_room_open_b": round(room_open_b, 3), "abn_dd_peak_t1_pct": round(dd_from_peak_t1 * 100.0, 3),
            "abn_retrace_frac": round(retrace_frac, 4), "abn_wave_gain_pct": round(wave_gain * 100.0, 2),
            "abn_vol_shrink": round(vol_shrink_sig, 4), "abn_amt_ratio3": round(amt_ratio3_sig, 4),
            "abn_above_ma5": float(above_ma5), "abn_above_ma10": float(above_ma10),
            "abn_sig_amt_yi": round(float(amt[sig]), 3), "abn_open_pct": round(float(opct[b]), 3),
            "abn_sig_ret1d": round(float(r1[sig]), 3),
        }
        for et in hit_types:
            last_b[et] = b
        for et in hit_types:
            rec = dict(base_info)
            rec["entry_type"] = et
            for sname, sdict in ex_res.items():
                rec[f"{sname}_exit_date"] = sdict["exit_date"]
                rec[f"{sname}_exit_hhmm"] = sdict["exit_hhmm"]
                rec[f"{sname}_gross_ret"] = sdict["gross_ret"]
                rec[f"{sname}_reason"] = sdict["reason"]
                rec[f"{sname}_mtm_json"] = json.dumps(sdict["mtm_gross"])
            events.append(rec)
    return events
