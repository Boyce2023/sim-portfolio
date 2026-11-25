#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Full-pool builders for 1to2 V20, 3to4 V4.1, and High V5.1 (including all untriggered pre-market passing candidates).
ZERO import yfinance (D12).
"""
import os
import pickle
import sys
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

from trigger_opt_engine import (
    SIM, PARTA_DIR, UPG_DIR, ABL_DIR, MW1_DIR, MW3_DIR, F1_DIR, GOLD_DIR, A2_ASSETS,
    FEE_RATE, exec_intraday_vel_or_cap,
)

for p in (PARTA_DIR, UPG_DIR, ABL_DIR, F1_DIR, A2_ASSETS, f"{SIM}/scripts"):
    if p not in sys.path:
        sys.path.insert(0, p)

import mod_common as mc
import mod_1to2 as m12
import upgrade_1to2_pit as u12
import exit_factor_engine as efe
import step4_audit_trunc_and_report as s4
from v191_dt_defer_helper import load_dt_defer_tables, defer_eod_limit_down, calc_adj_net_ret


def build_1to2_full_pool(bars_5m: dict, dmap_en: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Build all 198 passing V20 candidates across 164 top-1 dates (2021-11-16 ~ 2026-11-16)
    with full precomputed exit targets (buy-price independent) + exact Part 1 ledger parity check.
    """
    ctx = u12.build_signals_and_data_pit("2026-11-16")
    # Patch bars_5m_map with full local + baostock _patch_5m_bars so ALL untriggered hold days have 100% 5m
    ctx_bars = ctx["bars_5m_map"]
    for k, arr in bars_5m.items():
        if k not in ctx_bars:
            ctx_bars[k] = arr

    import run_ablation as ra12
    by_c, dmap_ab = ra12.load_daily_truth_and_adj()
    ra12.enrich_local_5m_map(ctx, dmap_ab)

    hf = ctx["hist_fb"].copy()
    inv = ra12.prepare_invariants(hf)
    fb20_dts = {d for d, c in mc.build_fb20_cln_dates_pit("2026-11-16").items() if c >= 2}
    m_fb = hf["d2_dt"].isin(fb20_dts).to_numpy()
    delta = np.where(m_fb, -25.0, 0.0)

    # Reconstruct exact V20 mask + sv (matching mod_1to2.run_1to2_variant 100%)
    sc_new = inv["sc_v"] + delta
    nb = (~hf["notice_bad"]).to_numpy()
    pac = (hf["p_sz"].to_numpy() <= 35.0) & nb
    pt = (hf["d1_seal_tightness"].to_numpy() >= 37.0)
    m_t1 = inv["common_ok"] & inv["open_in_win"] & (inv["sp_v"] >= 45.0) & (sc_new >= inv["thr_vec"])
    mm = ((m_t1 & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & pac) | (inv["m_t2_base"] & inv["pass_l2"])) & pt
    mmon = (inv["common_ok"] & inv["wk_mask"] & hf["d2_o_pct"].between(0.015, 0.090).to_numpy() & (inv["sp_v"] >= 38.0)
            & (sc_new >= inv["thr_vec"]) & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"] & pac & pt)
    tot18 = mm | (mmon & (~mm))
    fb295 = (inv["common_ok"] & inv["open_in_win"] & inv["pass_l1"] & inv["pass_l2"] & inv["pass_l3"] & inv["pass_nd_true"]
             & pac & pt & np.isin(inv["rk_t"], [2, 3]) & (inv["tbrk"] == 1) & (inv["xq2_arr"] < 4)
             & (inv["pos20_arr"] <= 0.40) & inv["cat_ok"] & (inv["lh_arr"] == 0) & (~inv["syz_arr"]) & ((sc_new - inv["sc_t3_pen"]) >= 295.0))
    tot19 = tot18 | fb295
    sv = np.where(mm, sc_new + 1000.0, np.where(mmon, sc_new, sc_new + 500.0))

    dt1, dt2, dt3 = inv["daily_t1"], inv["daily_t2"], inv["daily_t3"]
    dom_nd, melee = set(), set()
    for d in sorted(dt1.index):
        r1 = dt1.loc[d]; r2 = dt2.loc[d] if d in dt2.index else None; r3 = dt3.loc[d] if d in dt3.index else None
        m1, m2 = float(r1["p_theme_med"]), float(r2["p_theme_med"]) if r2 is not None else 0.0
        s1, s2 = int(r1["p_sz_max"]), int(r2["p_sz_max"]) if r2 is not None else 1
        if ((m1 - m2) >= 20.0) or ((s1 >= 6) and (s1 / max(1, s2) >= 2.0)):
            sd = hf[(hf["d2_dt"] == d) & tot18]
            if not (len(sd) > 0 and (sd["plate"] == r1["plate"]).any()):
                dom_nd.add(d)
        if r1 is not None and r2 is not None and r3 is not None:
            m3 = float(r3["p_theme_med"])
            if (m1 - m3) <= 15.0 and max(s1, s2, int(r3["p_sz_max"])) <= 5 and min(s1, s2, int(r3["p_sz_max"])) >= 2:
                melee.add(d)

    sub_t = hf[tot19].copy()
    sub_t["_sv"] = sv[tot19]
    bad_dts = set()
    for d, grp in sub_t.groupby("d2_dt"):
        if (grp["rk_theme"] == 1).any():
            trk = grp.sort_values("_sv", ascending=False).iloc[0]["rk_theme"]
            if pd.notna(trk) and trk >= 4:
                bad_dts.add(d)
    fmask = tot19 & (~hf["d2_dt"].isin(bad_dts)).to_numpy()
    dom_blk = np.array([(d in dom_nd and rk == 3) for d, rk in zip(hf["d2_dt"], hf["rk_theme"])], dtype=bool)
    mel_blk = np.array([(d in melee) and (not ((mrk <= 2) or bool(nh) or bool(hm))) for d, mrk, nh, hm in zip(hf["d2_dt"], hf["buyable_mkt_open_rk"], hf["notice_hard"], hf["is_ma"])], dtype=bool)
    m5y = ((hf["d2_dt"] >= "2021-11-16") & (hf["d2_dt"] <= "2026-11-16")).to_numpy()
    fmask = fmask & (~dom_blk) & (~mel_blk) & m5y
    hf["v20_sc_new"] = sc_new
    hf["v20_sv"] = sv

    all_dts = ctx["all_dts"]
    dt_to_idx = ctx["dt_to_idx"]
    pl = ctx["price_lookup"]
    xq_by_c6 = ctx["xq_by_c6"]
    tape_map = ctx["tape_map"]
    amt_lookup = ctx["amt_lookup"]

    def _get_xq_pre_d3(c6, start_dt, d3_dt):
        arr = xq_by_c6.get(c6)
        if arr is None:
            return 0
        lo = np.searchsorted(arr, f"{start_dt} 00:00:00", side="left")
        hi = np.searchsorted(arr, f"{d3_dt} 09:25:00", side="left")
        return int(hi - lo)

    def _get_d2_seal_ratio(c6, d2_dt):
        tp = tape_map.get((d2_dt, c6))
        amt = amt_lookup.get((c6, d2_dt), 0.0)
        if tp is None or tp[1] is None or amt <= 0:
            return np.nan
        return float(tp[1]) / amt

    def _compute_exit_info(row: dict) -> dict:
        c6, d2 = str(row["c6"]).zfill(6), str(row["d2_dt"])
        idx2 = dt_to_idx[d2]
        d2_bar = pl[(c6, d2)]
        o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar
        prev_c = round(float(c2), 2)
        idx3 = idx2 + 1
        d3 = all_dts[idx3]
        d3_bar = pl.get((c6, d3))
        if not d3_bar:
            ex_dt, ex_hhmm, ex_px, ex_open, tag = d3, 925, prev_c, True, "no_d3_bar"
        else:
            o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar

            def _ride(curr_start, boards_start, prev_c_init, sealed_2b_flag):
                curr = curr_start
                boards_held = boards_start
                used_immunity = False
                prev_c_l = prev_c_init
                while curr < len(all_dts) and (curr - idx2 <= 12):
                    dc = all_dts[curr]
                    b = pl.get((c6, dc))
                    if not b:
                        break
                    oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b
                    if iyzc:
                        prev_c_l = round(float(cc), 2)
                        curr += 1
                        continue
                    exempt_1030_d3 = False
                    if sealed_2b_flag == 1 and curr == idx3:
                        op3 = oc / prev_c_l - 1.0
                        xq_d3 = _get_xq_pre_d3(c6, row["dt_str"], dc)
                        sr_d2 = _get_d2_seal_ratio(c6, d2)
                        if (-0.065 <= op3 <= 0.025) and (xq_d3 < 4) and (np.isnan(sr_d2) or sr_d2 < 0.25):
                            exempt_1030_d3 = True
                    arr = ctx_bars.get((c6, dc))
                    if arr is not None and len(arr) >= 12:
                        idx_1030, cum_v, cum_a = -1, 0.0, 0.0
                        for bi in range(len(arr)):
                            cum_v += arr[bi, 5]
                            cum_a += arr[bi, 6]
                            if arr[bi, 0] == 1030:
                                idx_1030 = bi
                                break
                        if idx_1030 >= 0:
                            bc_1030 = arr[idx_1030, 4]
                            vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                            if bc_1030 >= ztc - 0.01:
                                for bi in range(idx_1030 + 1, len(arr) - 1):
                                    if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                        return dc, int(arr[bi + 1, 0]), round(float(arr[bi + 1, 1]), 2), False, "5m_1430_rush"
                                if iztc:
                                    prev_c_l = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                return dc, 1500, round(float(cc), 2), False, "eod_break"
                            elif bc_1030 < vwap_1030 and not exempt_1030_d3:
                                px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                                ehh = int(arr[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr) else 1030
                                return dc, ehh, px, False, "5m_1030_weak_cut"
                    if iztc:
                        prev_c_l = round(float(cc), 2); boards_held += 1; curr += 1; continue
                    if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c_l * 1.02) and (curr + 1 < len(all_dts)):
                        used_immunity = True; prev_c_l = round(float(cc), 2); curr += 1; continue
                    return dc, 1500, round(float(cc), 2), False, "eod_close"
                return all_dts[min(curr, len(all_dts) - 1)], 1500, prev_c_l, False, "max_hold_exit"

            if not is_zt2:
                if (c2 >= float(row["close"])) and (o3 >= round(c2 * 1.005, 2)) and not is_yz_dt3:
                    if is_zt3:
                        ex_dt, ex_hhmm, ex_px, ex_open, tag = _ride(idx3 + 1, 3, round(float(c3), 2), 0)
                    else:
                        ex_dt, ex_hhmm, ex_px, ex_open, tag = d3, 1500, round(float(c3), 2), False, "nshape_d3_close"
                else:
                    curr = idx3
                    while curr < len(all_dts):
                        b = pl.get((c6, all_dts[curr]))
                        if not b or not b[7]:
                            px = round(float(b[0]), 2) if b else prev_c
                            ex_dt, ex_hhmm, ex_px, ex_open, tag = all_dts[curr], 925, px, True, "fail_open_cut"
                            break
                        curr += 1
            else:
                ex_dt, ex_hhmm, ex_px, ex_open, tag = _ride(idx3, 2, prev_c, 1)

        # V19.1 15:00 limit-down deferral + adjf ratio
        eb = dmap_ab.get((c6, ex_dt))
        if eb is not None and ex_hhmm >= 1455 and bool(eb.is_dt_exact):
            gc = by_c[c6]
            hits = gc.index[gc["dt_s"] == ex_dt]
            if len(hits) > 0:
                k = hits[0] + 1
                while k < len(gc) - 1 and bool(gc.loc[k, "is_yizi_dt"]):
                    k += 1
                if k < len(gc):
                    nb = gc.loc[k]
                    ex_dt, ex_hhmm, ex_px, ex_open, tag = str(nb.dt_s), 925, round(float(nb.open), 2), True, "eod_dt_defer_open"

        bb = dmap_ab[(c6, d2)]
        eb2 = dmap_ab[(c6, ex_dt)]
        adj_ratio = float(eb2.adjf) / float(bb.adjf) if bb.adjf > 0 else 1.0
        # Check 5m full coverage across hold days
        bi, ei = dt_to_idx[d2], dt_to_idx[ex_dt]
        miss_hold = [all_dts[i] for i in range(bi, ei + 1) if (c6, all_dts[i]) not in ctx_bars]
        return {
            "exit_date": ex_dt, "exit_hhmm": int(ex_hhmm), "exit_price": round(float(ex_px), 2),
            "exit_at_open": bool(ex_open), "tag": tag, "adj_ratio": float(adj_ratio),
            "miss_hold_5m": miss_hold,
        }

    records = []
    miss_5m_all = []
    for rdict in hf[fmask].to_dict("records"):
        ex = _compute_exit_info(rdict)
        if ex["miss_hold_5m"]:
            miss_5m_all.append((str(rdict["d2_dt"]), str(rdict["c6"]).zfill(6), ex["miss_hold_5m"]))
        c6 = str(rdict["c6"]).zfill(6)
        bd = str(rdict["d2_dt"])
        db = dmap_en[(c6, bd)]
        cand_sc = float(rdict["v20_sc_new"])
        cand_lead = float(rdict["buy_open_lead"])
        is_mon = bool(rdict["gap_days"] >= 3)
        do_dir_def = is_mon and (cand_sc >= 310.0) and (cand_lead >= 0.025)
        records.append({
            "buy_date": bd,
            "c6": c6,
            "code": c6,
            "name": str(rdict["name"]),
            "score": round(cand_sc, 1),
            "sv": float(rdict["v20_sv"]),
            "d1_close": float(rdict["close"]),
            "pre_c": float(db["pre_c"]),
            "open_d": float(rdict["d2_open"]),
            "zt_px": float(db["zt_px"]),
            "gap_days": int(rdict["gap_days"]),
            "buy_open_lead": cand_lead,
            "default_do_direct": do_dir_def,
            **{k: v for k, v in ex.items() if k != "miss_hold_5m"},
        })

    df_all = pd.DataFrame(records).sort_values(["buy_date", "sv", "c6"], ascending=[True, False, True]).reset_index(drop=True)
    df_top1 = df_all.groupby("buy_date", sort=True).head(1).reset_index(drop=True)
    assert len(df_all) == 198 and len(df_top1) == 164, (len(df_all), len(df_top1))
    assert len(miss_5m_all) == 0, f"1to2 missing hold 5m: {miss_5m_all[:5]}"
    return df_all, df_top1, ctx_bars


def build_3to4_full_pool(bars_5m: dict, dmap_en: dict) -> pd.DataFrame:
    """
    Build all 128 pre-market eligible 3to4 V4.1 candidates (sc_v40 >= 90, 123 unique dates,
    115 triggered + 13 untriggered) with exact V4.1 exits for ALL 128 rows.
    """
    with open(f"{F1_DIR}/pit_exit_cache_full.pkl", "rb") as f:
        cache = pickle.load(f)

    # Patch cache bars_5m_map ONLY for keys not belonging to already-triggered entries (preserves 100% Part 1 exit parity on 115 rows while enabling 100% 5m exits on the 13 untriggered rows)
    untrig_c6_set = {str(e["code"]).zfill(6) for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0 and e["buy_px"] is None}
    trig_keys_excl = {(str(e["code"]).zfill(6), str(e["buy_date"])) for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0 and e["buy_px"] is not None}
    for k, arr in bars_5m.items():
        if k not in cache["bars_5m_map"] and (k[0] in untrig_c6_set) and (k not in trig_keys_excl) and k not in {("002896", "2022-08-03"), ("603887", "2024-10-31")}:
            cache["bars_5m_map"][k] = arr

    cache_all = dict(cache)
    patched_entries = []
    for e in cache["buy_entries"]:
        ec = dict(e)
        if ec["skel"] and ec["sc_v40"] >= 90.0 and ec["buy_px"] is None:
            ec["buy_px"] = 1.0  # temporary non-None solely so precompute_trade_day_states computes k_states
        patched_entries.append(ec)
    cache_all["buy_entries"] = patched_entries

    states = efe.precompute_trade_day_states(cache_all, min_score=90.0)
    rfn_v41 = lambda st, ctx: {"tight_1345_thr": 0.070 if s4.risk7_score(st) >= 1 else 0.050}
    dt_tables = load_dt_defer_tables()
    code_bars = cache["code_bars_ext"]
    cand_df = cache["cand_df"]

    rows = []
    for e in cache["buy_entries"]:
        if (not e["skel"]) or (e["sc_v40"] < 90.0):
            continue
        bd = str(e["buy_date"])
        if bd > "2026-11-16" or bd < "2021-11-16":
            continue
        c6 = str(e["code"]).zfill(6)
        pos = e["pos"]
        cb = code_bars[c6]
        ex_dt, spx, adjs, hb, shh, rsn = efe.sim_exit_with_rule(e, cache_all, states.get(e["idx"], {}), rfn_v41)
        spx_r = round(float(spx), 2)
        adj_b = float(cb["adjf"][pos])
        adj_e = float(adjs)

        # Check eod limit-down deferral using defer_eod_limit_down helper (with dummy buy_px if needed, then compute adj_ratio)
        dummy_bp = float(e["buy_px"]) if e["buy_px"] is not None else round(float(cb["open"][pos]), 2)
        nr_tmp = (float(spx) * adj_e) / (dummy_bp * adj_b) * (1.0 - FEE_RATE) - 1.0
        ned, neh, nep, _, dt_def = defer_eod_limit_down(c6, bd, round(dummy_bp, 2), ex_dt, shh, spx_r, nr_tmp, dt_tables, FEE_RATE)

        db_b = dmap_en[(c6, bd)]
        db_e = dmap_en[(c6, ned)]
        adj_ratio = float(db_e["adjf"]) / float(db_b["adjf"]) if db_b["adjf"] > 0 else 1.0

        rows.append({
            "buy_date": bd,
            "c6": c6,
            "code": c6,
            "name": str(e["name"]),
            "score": int(round(e["sc_v40"])),
            "prio_tie": float(cand_df["prio_3to4"].iloc[e["idx"]]),
            "priority_score": float(e["sc_v40"] * 10.0 + float(cand_df["prio_3to4"].iloc[e["idx"]]) * 0.1),
            "pre_c": float(db_b["pre_c"]),
            "open_d": float(cb["open"][pos]),
            "zt_px": float(db_b["zt_px"]),
            "orig_buy_px": float(e["buy_px"]) if e["buy_px"] is not None else np.nan,
            "orig_buy_hhmm": int(e["buy_hhmm"]) if e["buy_hhmm"] is not None else 0,
            "exit_date": str(ned),
            "exit_hhmm": int(neh),
            "exit_price": round(float(nep), 2),
            "exit_price_raw": float(nep) if dt_def else float(spx),
            "adj_ratio": float(adj_ratio),
            "adj_ratio_cache": float(db_e["adjf"] / adj_b if dt_def else adj_e / adj_b),
            "dt_deferred": bool(dt_def),
            "exit_reason": rsn,
        })

    df = pd.DataFrame(rows).sort_values(["buy_date", "priority_score", "c6"], ascending=[True, False, True]).reset_index(drop=True)
    assert len(df) == 128 and df["buy_date"].nunique() == 123, (len(df), df["buy_date"].nunique())
    return df


def build_high_full_pool(bars_5m: dict, dmap_en: dict) -> pd.DataFrame:
    """
    Build all 52 pre-market eligible High V5.1 candidates (sc5_1 >= 88, 24 red/flat + 28 green opens incl. 6 untriggered)
    with exact S_hold_d3 + 93% double-dev + limit-down deferral exits for ALL 52 rows.
    """
    src = "\n".join(open(f"{GOLD_DIR}/sub2_03_golden_relaxation_backtest.py", encoding="utf-8").read().splitlines()[:192])
    src = src.replace('r["d1_to"] > 38.0', 'r["d1_to"] > 35.0')
    G = {"__name__": "eng"}
    exec(src, G)
    dfr, code_bars, SH_MAP, SZ_MAP, get_double_dev_px = G["dfr"], G["code_bars"], G["SH_MAP"], G["SZ_MAP"], G["get_double_dev_px"]
    dt_tables = load_dt_defer_tables()

    rows = []
    for r in dfr[dfr["sc5_1"] >= 88].itertuples():
        c6 = str(r.code).zfill(6)
        bd = str(r.buy_date)
        if bd > "2026-11-16" or bd < "2021-11-16":
            continue
        bars = code_bars[c6]
        d2p = bars["p"][bd]
        b_op = float(bars["open"][d2p])
        db_b = dmap_en[(c6, bd)]
        zt_px = float(db_b["zt_px"])
        imap = SH_MAP if c6.startswith("60") else SZ_MAP
        n = len(bars["dts"])

        def run_zt_loop(start_p):
            imm = False
            for step in range(1, 8):
                p = start_p + step
                if p >= n:
                    break
                pl = get_double_dev_px(bars, p, imap, 0.07)
                if bars["open"][p] >= pl:
                    return p, float(bars["open"][p]), True
                if bars["high"][p] >= pl:
                    return p, float(pl), False
                if not bars["is_zt"][p]:
                    if (not imm) and (bars["close"][p] > bars["open"][p]):
                        imm = True
                        continue
                    while p < n - 1 and bars["is_yizi_dt"][p]:
                        p += 1
                    return p, float(bars["close"][p]), False
            p_end = min(start_p + 5, n - 1)
            return p_end, float(bars["close"][p_end]), False

        if bars["is_zt"][d2p]:
            ep, _, eo = run_zt_loop(d2p)
        else:
            p = min(d2p + 1, n - 1)
            while p < n - 1 and bars["is_yizi_dt"][p]:
                p += 1
            if bars["is_zt"][p]:
                ep, _, eo = run_zt_loop(p)
            else:
                ep, _, eo = p, float(bars["close"][p]), False

        e_dt = str(bars["dts"][ep])
        arr_e = bars_5m.get((c6, e_dt))
        sealed_b = bool(bars["is_zt"][d2p])
        chained_zt = (not sealed_b) and (ep > d2p + 1) and any(bool(bars["is_zt"][mid]) for mid in range(d2p + 1, ep))
        pl = get_double_dev_px(bars, ep, imap, 0.07) if (sealed_b or chained_zt) else 99999.0

        if eo:
            e_hhmm, e_px = 925, float(bars["open"][ep])
        else:
            hit_dev = False
            if pl < 99990.0 and arr_e is not None and len(arr_e) > 0:
                for row_e in arr_e:
                    if row_e[2] >= pl:
                        e_hhmm = int(row_e[0])
                        e_px = float(max(row_e[1], pl))
                        hit_dev = True
                        break
            if not hit_dev:
                if pl < 99990.0 and float(bars["high"][ep]) >= pl:
                    e_hhmm, e_px = 1030, float(pl)
                else:
                    e_hhmm, e_px = 1500, float(bars["close"][ep])

        nr_tmp = (e_px * float(bars["adjf"][ep])) / (b_op * float(bars["adjf"][d2p])) * (1.0 - FEE_RATE) - 1.0
        ned, neh, nep, _, dt_def = defer_eod_limit_down(c6, bd, round(b_op, 2), e_dt, e_hhmm, e_px, nr_tmp, dt_tables, FEE_RATE)
        db_e = dmap_en[(c6, ned)]
        adj_ratio = float(db_e["adjf"]) / float(db_b["adjf"]) if db_b["adjf"] > 0 else 1.0

        rows.append({
            "buy_date": bd,
            "c6": c6,
            "code": c6,
            "name": str(r.name),
            "score": int(r.sc5_1),
            "op2": float(r.op2),
            "is_red_flat": bool(r.op2 >= 0.0),
            "pre_c": float(db_b["pre_c"]),
            "open_d": float(b_op),
            "zt_px": float(zt_px),
            "exit_date": str(ned),
            "exit_hhmm": int(neh),
            "exit_price": round(float(nep), 2),
            "exit_price_raw": float(nep) if dt_def else float(e_px),
            "eo": bool(neh == 925),
            "adj_ratio": float(adj_ratio),
            "dt_deferred": bool(dt_def),
            "pre_defer_exit_date": e_dt,
            "pre_defer_e_px": float(e_px),
        })

    df = pd.DataFrame(rows).sort_values(["buy_date", "score", "c6"], ascending=[True, False, True]).reset_index(drop=True)
    assert len(df) == 52 and df["buy_date"].nunique() == 52, (len(df), df["buy_date"].nunique())
    return df
