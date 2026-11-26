#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 Track 1 event extraction (V2_A exact unlock, V2_B pre-unlock tail hug, V2_C E1a rebuild)."""
import json
import sys
import numpy as np

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

RD045_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd045_abn_v2_bse_v2_refinement_20261126"
if RD045_DIR not in sys.path:
    sys.path.insert(0, RD045_DIR)
import _rd045_abn_sim as abn_sim


def extract_v2_stock_events(c6: str, g_arr: dict, st_mask: np.ndarray, dev_d: dict, cn_sev_dts: set[str]) -> list[dict]:
    dts, op, hi, lo, cl, af = g_arr["dts"], g_arr["op"], g_arr["hi"], g_arr["lo"], g_arr["cl"], g_arr["af"]
    r1, opct, amt, trn = g_arr["r1"], g_arr["opct"], g_arr["amt"], g_arr["trn"]
    zt, dt_f, yzz, yzd = g_arr["zt"], g_arr["dt_f"], g_arr["yzz"], g_arr["yzd"]
    age, pc_raw, stk = g_arr["age"], g_arr["pc_raw"], g_arr["stk"]
    ac, mi = dev_d["ac"], dev_d["mi"]
    dev_c, proj_flat = dev_d["dev_c"], dev_d["proj_flat"]
    n = len(dts)
    if n < 25:
        return []

    mg_pre, mg_eod, nxt_mg = abn_sim.compute_mg100_arrays(dts, dev_d, cn_sev_dts)
    ma5 = np.full(n, np.nan)
    ma10 = np.full(n, np.nan)
    for idx in range(4, n):
        ma5[idx] = np.mean(ac[idx - 4:idx + 1]) / af[idx]
    for idx in range(9, n):
        ma10[idx] = np.mean(ac[idx - 9:idx + 1]) / af[idx]

    events = []
    last_b = {"V2_A": -99, "V2_B": -99, "V2_C": -99}

    for b in range(15, n - 1):
        b_dt = str(dts[b])
        if b_dt < "2021-01-04":
            continue
        if st_mask[b] or age[b] <= 45 or pc_raw[b] < 1.5:
            continue
        if mi[b] - mi[b - 1] > 3:
            continue

        # Prior Wave-1 high-pressure window [b-12 .. b-1] for V2_A/V2_C (and [b-10 .. b] for V2_B)
        win_lo = max(0, b - 12)
        hp_open = [u for u in range(win_lo, b) if dev_c[u] >= 84.0 and not st_mask[u]]

        # Check V2_A and V2_C (09:25 open buys)
        can_open = (not yzz[b]) and (not yzd[b]) and (op[b] > 0)
        is_v2a = is_v2c = False
        if can_open and hp_open:
            pf_o, pl_o = hp_open[0], hp_open[-1]
            buildup_lo = max(0, pf_o - 10)
            ms_o = int(np.max(stk[buildup_lo:pl_o + 1])) if pl_o >= buildup_lo else 0
            zt_o = int(np.sum(zt[buildup_lo:pl_o + 1]))
            if ms_o >= 2 or zt_o >= 2:
                is_v2a = (mg_pre[b - 1] <= 6.0) and (mg_pre[b] >= 9.5) and (b - last_b["V2_A"] >= 6)
                pk_o = float(np.max(dev_c[pf_o:pl_o + 1]))
                is_v2c = (
                    (b - pl_o <= 3) and (proj_flat[b - 1] >= 78.0 or dev_c[b - 1] >= 80.0)
                    and (proj_flat[b] <= 84.0) and (pk_o - proj_flat[b] >= 12.0)
                    and (pk_o < 100.0) and (-6.0 <= opct[b] <= 5.0) and (b - last_b["V2_C"] >= 6)
                )

        # Check V2_B (close/tail buy on day b itself!)
        zt_px_b = np.floor(pc_raw[b] * 1.10 * 100.0 + 0.5) / 100.0
        dt_px_b = np.floor(pc_raw[b] * 0.90 * 100.0 + 0.5) / 100.0
        can_tail = (cl[b] < zt_px_b - 0.005) and (cl[b] > dt_px_b + 0.005) and (cl[b] > 0)
        is_v2b = False
        if can_tail and (80.0 <= dev_c[b] < 100.0) and (mg_pre[b] <= 6.0) and (nxt_mg[b] >= 9.5) and (b - last_b["V2_B"] >= 6):
            hp_tail = [u for u in range(max(0, b - 10), b + 1) if dev_c[u] >= 84.0 and not st_mask[u]]
            if hp_tail:
                pf_t, pl_t = hp_tail[0], hp_tail[-1]
                buildup_t = max(0, pf_t - 10)
                if int(np.max(stk[buildup_t:pl_t + 1])) >= 2 or int(np.sum(zt[buildup_t:pl_t + 1])) >= 2:
                    is_v2b = True

        if not (is_v2a or is_v2b or is_v2c):
            continue

        # Emit separate records for open-buy (V2_A/V2_C -> sig=b-1) and tail-buy (V2_B -> sig=b)
        for et, flag, is_tail in (("V2_A", is_v2a, False), ("V2_C", is_v2c, False), ("V2_B", is_v2b, True)):
            if not flag:
                continue
            sig = b if is_tail else (b - 1)
            hp_use = [u for u in range(max(0, sig - 10), sig + 1) if dev_c[u] >= 84.0 and not st_mask[u]]
            if not hp_use:
                continue
            pf_u, pl_u = hp_use[0], hp_use[-1]
            blo_u = max(0, pf_u - 10)
            ms_wave = int(np.max(stk[blo_u:pl_u + 1]))
            # Wave-1 consecutive board peak day t0 (last day achieving max streak in buildup)
            stk_slice = stk[blo_u:pl_u + 1]
            t0_rel = int(np.where(stk_slice == ms_wave)[0][-1]) if len(stk_slice) else 0
            t0_idx = blo_u + t0_rel
            peak_dev = float(np.max(dev_c[pf_u:pl_u + 1]))
            peak_ac = float(np.max(ac[pf_u:sig + 1]))
            peak_amt = float(np.max(amt[max(0, pf_u - 2):pl_u + 1]))
            dd_peak = float((ac[sig] / peak_ac - 1.0) * 100.0) if peak_ac > 0 else 0.0
            if dd_peak < -25.0:
                continue

            ex_res = abn_sim.simulate_exits_v2(b, n, op, hi, lo, cl, af, ac, dts, zt, dt_f, yzd, ma5, buy_at_close=is_tail)
            if not ex_res:
                continue

            last_b[et] = b
            rec = {
                "entry_type": et,
                "code": c6,
                "buy_date": b_dt,
                "sig_date": str(dts[sig]),
                "wave1_peak_dt": str(dts[t0_idx]),
                "wave1_start_dt": str(dts[max(0, blo_u)]),
                "buy_hhmm": 1500 if is_tail else 925,
                "buy_px": round(float(cl[b] if is_tail else op[b]), 3),
                "is_yizi": False,
                "abn_max_streak_wave": ms_wave,
                "abn_zt_cnt_wave": int(np.sum(zt[blo_u:pl_u + 1])),
                "abn_peak_dev10": round(peak_dev, 3),
                "abn_was_hit_100": int(peak_dev >= 100.0),
                "abn_sig_dev10": round(float(dev_c[sig]), 3),
                "abn_mg100_prev": round(float(mg_pre[b - 1]), 3),
                "abn_mg100_b": round(float(mg_pre[b]), 3),
                "abn_mg100_eod_b": round(float(mg_eod[b]), 3),
                "abn_next_mg100_b": round(float(nxt_mg[b]), 3),
                "abn_unlock_jump": round(float((nxt_mg[b] - mg_pre[b]) if is_tail else (mg_pre[b] - mg_pre[b - 1])), 3),
                "abn_hug_gap_pp": round(float(mg_eod[b] - r1[b]), 3),
                "abn_dd_peak_pct": round(dd_peak, 3),
                "abn_vol_shrink": round(float(amt[sig] / max(1e-4, peak_amt)), 4),
                "abn_above_ma5": float(1.0 if (np.isfinite(ma5[sig]) and cl[sig] >= ma5[sig] * 0.995) else 0.0),
                "abn_above_ma10": float(1.0 if (np.isfinite(ma10[sig]) and cl[sig] >= ma10[sig] * 0.995) else 0.0),
                "abn_sig_amt_yi": round(float(amt[sig]), 3),
                "abn_open_pct": round(float(opct[b]), 3),
                "abn_sig_ret1d": round(float(r1[sig]), 3),
                "abn_sig_clv": round(float((cl[sig] - lo[sig]) / max(1e-6, hi[sig] - lo[sig])), 4),
                "abn_sig_dt": int(dt_f[sig]),
            }
            for sname, sdict in ex_res.items():
                rec[f"{sname}_exit_date"] = sdict["exit_date"]
                rec[f"{sname}_exit_hhmm"] = sdict["exit_hhmm"]
                rec[f"{sname}_gross_ret"] = sdict["gross_ret"]
                rec[f"{sname}_reason"] = sdict["reason"]
                rec[f"{sname}_mtm_json"] = json.dumps(sdict["mtm_gross"])
            events.append(rec)
    return events
