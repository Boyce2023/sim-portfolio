#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-5 Runner Part 1:
  - Module 1: 6 Strategies x 13 Exit Trees Cross-Transplant Matrix (Standalone + V20.0 Combined + All-6 Unified)
  - Module 3: 5m Intraday Blowoff (>=8.5% Peak Fade / Low CLV <0.25, <0.35) Dynamic Risk Control
All unified at 0.30% round-trip cost, zero lookahead, threads<=2.
"""
import os
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
warnings.filterwarnings("ignore", category=FutureWarning)

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a5_exit_tree_swaps"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import w2a5_data_loader as dl
import w2a5_exit_trees as et
import w2a5_metrics as wm
import step4_mod_rules_and_sim as m1


def _run_v20_with_pools(pools_dict: dict, ctx: dict, perm_n: int = 1000) -> tuple[pd.DataFrame, dict]:
    tr_c, _ = m1.run_combined_v20(pools_dict, ctx["untrig_base"], {})
    cand_all = pd.concat(
        [pools_dict[st][pools_dict[st]["is_pass_official"] == 1][["buy_date", "code", "net_ret"]] for st in m1.STRAT_ORDER],
        ignore_index=True,
    )
    ev = wm.evaluate_ledger_windows(tr_c, None, cand_all, ctx, perm_n=perm_n)
    return tr_c, ev


def compute_b0_blowoff_flags(df_p: pd.DataFrame, strat: str, ctx: dict) -> pd.DataFrame:
    """Compute strictly causal b0 intraday blowoff & low-CLV flags (5m exact + daily OHLC)."""
    n = len(df_p)
    daily_h85 = np.zeros(n, dtype=bool)
    daily_clv = np.full(n, 0.5, dtype=float)
    m5_has = np.zeros(n, dtype=bool)
    m5_h85_after = np.zeros(n, dtype=bool)
    m5_clv_after = np.full(n, 0.5, dtype=float)
    m5_pk_drop5 = np.zeros(n, dtype=bool)
    b0_unsealed = np.zeros(n, dtype=bool)

    for i, r in enumerate(df_p.itertuples(index=False)):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)[:10]
        ss = ctx["stock_series"].get(c6)
        if ss is None or bd not in ss["d2i"]:
            continue
        b0 = ss["d2i"][bd]
        if ss["is_zt"][b0]:
            continue
        b0_unsealed[i] = True
        pc0 = float(ss["prev_c"][b0])
        h0, l0, c0 = float(ss["high"][b0]), float(ss["low"][b0]), float(ss["close"][b0])
        lim0 = float(ss["lim"][b0])
        pk_thr = 0.085 * (lim0 / 0.10)
        daily_clv[i] = (c0 - l0) / (h0 - l0) if (h0 - l0) > 1e-6 else 0.5
        daily_h85[i] = (pc0 > 0) and ((h0 / pc0 - 1.0) >= pk_thr)

        arr = ctx["b5m"].get((c6, bd))
        bh = int(getattr(r, "buy_hhmm", 925)) if pd.notna(getattr(r, "buy_hhmm", 925)) else 925
        if arr is not None and len(arr) >= 6:
            m5_has[i] = True
            sub_a = arr[arr[:, 0] >= bh]
            if len(sub_a) == 0:
                sub_a = arr
            ah = float(np.max(sub_a[:, 2]))
            al = float(np.min(sub_a[:, 3]))
            ac = float(sub_a[-1, 4])
            m5_h85_after[i] = (pc0 > 0) and ((ah / pc0 - 1.0) >= pk_thr)
            m5_clv_after[i] = (ac - al) / (ah - al) if (ah - al) > 1e-6 else 0.5
            m5_pk_drop5[i] = (ah > 0) and ((ac / ah - 1.0) <= -0.05 * (lim0 / 0.10))

    return pd.DataFrame({
        "b0_unsealed": b0_unsealed,
        "daily_h85": daily_h85,
        "daily_clv": daily_clv,
        "m5_has": m5_has,
        "m5_h85_after": m5_h85_after,
        "m5_clv_after": m5_clv_after,
        "m5_pk_drop5": m5_pk_drop5,
    })


def apply_m3_guard(
    pool_base: pd.DataFrame, flags: pd.DataFrame, strat: str, ctx: dict,
    cond_mask: np.ndarray, action: str, fee: float = 0.0030,
) -> pd.DataFrame:
    """Apply Module 3 next-day 09:25 / 10:30 guard on flagged unsealed blowoff holdings."""
    df = pool_base.copy()
    is_pass = df["is_pass_official"].to_numpy(bool)
    ed_arr = df["exit_date"].astype(str).to_numpy(dtype=object)
    eh_arr = df["exit_hhmm"].to_numpy(dtype=int)
    ep_arr = df["exit_price"].to_numpy(dtype=float)
    nr_arr = df["net_ret"].to_numpy(dtype=float)
    rs_arr = df["exit_reason"].astype(str).to_numpy(dtype=object) if "exit_reason" in df.columns else np.full(len(df), "", dtype=object)
    dt_def_arr = df["dt_deferred"].to_numpy(bool) if "dt_deferred" in df.columns else np.zeros(len(df), dtype=bool)

    n_trig = 0
    for idx in np.where(is_pass & cond_mask)[0]:
        r = df.iloc[idx]
        c6, bd = str(r.code).zfill(6), str(r.buy_date)[:10]
        ss = ctx["stock_series"].get(c6)
        if ss is None or bd not in ss["d2i"]:
            continue
        b0 = ss["d2i"][bd]
        if b0 + 1 >= len(ss["dts"]):
            continue
        k1 = et._defer_yizi_dt(ss, b0 + 1)
        # Only override if baseline hadn't already exited at k1 09:25
        o1, pc1 = float(ss["open"][k1]), float(ss["prev_c"][k1])
        op1_pct = (o1 / pc1 - 1.0) if pc1 > 0 else 0.0
        adjf0 = float(ss["adjf"][b0])
        bp_val = float(r.buy_price_val) if pd.notna(r.buy_price_val) else float(ss["open"][b0])
        buy_adj = bp_val if bool(r.is_adj_px) else bp_val * adjf0

        trigger = False
        if action == "DirectCut_0925":
            trigger = True
        elif action.startswith("Gate_Open_ge_"):
            thr_pct = float(action.split("_")[-1].replace("pct", "")) / 100.0
            trigger = (op1_pct < thr_pct)
        elif action == "VWAP_1030_Cut":
            dk1 = str(ss["dts"][k1])
            arr = ctx["b5m"].get((c6, dk1))
            if arr is not None and len(arr) >= 6:
                idx30, cv, ca = -1, 0.0, 0.0
                for bi in range(len(arr)):
                    cv += float(arr[bi, 5]); ca += float(arr[bi, 6])
                    if int(arr[bi, 0]) == 1030:
                        idx30 = bi; break
                if idx30 >= 0:
                    bc30 = float(arr[idx30, 4])
                    vw30 = ca / cv if cv > 0 else bc30
                    if bc30 < float(ss["zt_px"][k1]) - 0.01 and bc30 < vw30:
                        px_x = float(arr[idx30 + 1, 1]) if idx30 + 1 < len(arr) else bc30
                        hh_x = int(arr[idx30 + 1, 0]) if idx30 + 1 < len(arr) else 1030
                        if px_x > float(ss["dt_px"][k1]) + 0.005:
                            ed_arr[idx], eh_arr[idx], ep_arr[idx], nr_arr[idx], rs_arr[idx], dt_def_arr[idx] = et._finish_px(
                                ss, k1, px_x, hh_x, buy_adj, fee, f"m3_{action}"
                            )
                            n_trig += 1
                            continue

        if trigger and (str(ed_arr[idx]) > str(ss["dts"][k1]) or (str(ed_arr[idx]) == str(ss["dts"][k1]) and int(eh_arr[idx]) > 925)):
            ed_arr[idx], eh_arr[idx], ep_arr[idx], nr_arr[idx], rs_arr[idx], dt_def_arr[idx] = et._finish_px(
                ss, k1, o1, 925, buy_adj, fee, f"m3_{action}", k1 > b0 + 1
            )
            n_trig += 1

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

    idx_full = {d: i for i, d in enumerate(ctx["cal_full"])}
    idx_5y = {d: i for i, d in enumerate(ctx["cal_5y"])}
    df["mtm_full"] = m1.precompute_mtm_segments(df, ctx["cal_full"], idx_full, ctx["bar_lu"], is_20cm_adj=(strat == "20cm"))
    df["mtm_5y"] = m1.precompute_mtm_segments(df, ctx["cal_5y"], idx_5y, ctx["bar_lu"], is_20cm_adj=(strat == "20cm"))
    df.attrs["n_m3_triggered"] = n_trig
    return df


def main():
    t0 = time.time()
    ctx = dl.load_w2a5_context("2026-11-16")
    print(f"[M1+M3] Context loaded in {time.time()-t0:.2f}s")

    # Baseline 0.30% pools & combined
    pools_base_030 = {st: et.apply_tree_to_pool(ctx["pools"][st], st, "E0_Native", ctx, fee=0.0030) for st in m1.STRAT_ORDER}
    tr_base_030, ev_base_030 = _run_v20_with_pools(pools_base_030, ctx, perm_n=1000)

    # Native parity check
    pools_nat = {st: et.apply_tree_to_pool(ctx["pools"][st], st, "E0_Native", ctx, fee=(0.0030 if st == "20cm" else 0.0020)) for st in m1.STRAT_ORDER}
    tr_nat, ev_nat = _run_v20_with_pools(pools_nat, ctx, perm_n=1000)
    assert len(tr_nat) == 278 and abs(ev_nat["windows"]["Y5"]["nav"] - 69134091.5067) < 1.0

    rows = []
    rows.append(wm.flatten_row("BASE_V20_NATIVE_FEE", "combined", "E0_Native_Fee", "combined_v20", ev_nat))
    rows.append(wm.flatten_row("BASE_V20_UNIFIED_030", "combined", "E0_Native_030", "combined_v20", ev_base_030))

    # ==================== MODULE 1: 6 x 13 Exit Tree Cross Matrix ====================
    print("[M1] Running 6 strategies x 13 exit trees (standalone + V20 combined)...")
    t_m1 = time.time()
    mod_pools_cache = {}
    for st in m1.STRAT_ORDER:
        for tid, tdesc in et.TREE_CATALOG:
            if tid == "E0_Native":
                p_mod = pools_base_030[st]
            else:
                p_mod = et.apply_tree_to_pool(ctx["pools"][st], st, tid, ctx, fee=0.0030)
            mod_pools_cache[(st, tid)] = p_mod

            pass_df, slot_df = m1.sim_standalone(st, p_mod, np.zeros(len(p_mod)))
            ev_solo = wm.evaluate_ledger_windows(slot_df, pass_df, pass_df, ctx, perm_n=1000)
            rows.append(wm.flatten_row(f"M1_SOLO_{st}_{tid}", st, tid, "standalone", ev_solo))

            # Combined V20 impact (swapping ONLY strategy `st` to `tid`)
            if tid == "E0_Native":
                ev_comb = ev_base_030
            else:
                p_dict = dict(pools_base_030)
                p_dict[st] = p_mod
                _, ev_comb = _run_v20_with_pools(p_dict, ctx, perm_n=1000)
            rows.append(wm.flatten_row(f"M1_COMB_{st}_{tid}", st, tid, "combined_v20_single_swap", ev_comb))

    # Also test All-6 Unified Exit Trees (all 6 strategies simultaneously adopt tid)
    for tid, _ in et.TREE_CATALOG:
        if tid == "E0_Native":
            continue
        p_all = {st: mod_pools_cache[(st, tid)] for st in m1.STRAT_ORDER}
        _, ev_all = _run_v20_with_pools(p_all, ctx, perm_n=1000)
        rows.append(wm.flatten_row(f"M1_ALL6_{tid}", "combined_all6", tid, "combined_v20_all6", ev_all))
    print(f"[M1] Completed {len(rows)} matrix rows in {time.time()-t_m1:.2f}s")

    # ==================== MODULE 3: 5m Blowoff & Low-CLV Dynamic Guard ====================
    print("[M3] Running 5m Blowoff & Low-CLV Dynamic Risk Control...")
    t_m3 = time.time()
    flags_by_st = {st: compute_b0_blowoff_flags(pools_base_030[st], st, ctx) for st in m1.STRAT_ORDER}

    m3_specs = [
        ("Cond5m_CLV25", ["1to2", "3to4", "high"], lambda f: f["b0_unsealed"] & f["m5_has"] & f["m5_h85_after"] & (f["m5_clv_after"] < 0.25)),
        ("Cond5m_CLV35", ["1to2", "3to4", "high"], lambda f: f["b0_unsealed"] & f["m5_has"] & f["m5_h85_after"] & (f["m5_clv_after"] < 0.35)),
        ("All6_Daily_CLV25", m1.STRAT_ORDER, lambda f: f["b0_unsealed"] & f["daily_h85"] & (f["daily_clv"] < 0.25)),
        ("All6_Daily_CLV35", m1.STRAT_ORDER, lambda f: f["b0_unsealed"] & f["daily_h85"] & (f["daily_clv"] < 0.35)),
    ]
    m3_actions = ["DirectCut_0925", "Gate_Open_ge_1pct", "Gate_Open_ge_2pct", "Gate_Open_ge_3pct", "Gate_Open_ge_5pct", "VWAP_1030_Cut"]

    m3_details = []
    for cond_name, st_list, mask_fn in m3_specs:
        for act in m3_actions:
            p_dict = dict(pools_base_030)
            tot_trig = 0
            for st in st_list:
                fl = flags_by_st[st]
                cm = mask_fn(fl).to_numpy(bool)
                p_mod = apply_m3_guard(pools_base_030[st], fl, st, ctx, cm, act, fee=0.0030)
                p_dict[st] = p_mod
                tot_trig += int(p_mod.attrs.get("n_m3_triggered", 0))
                if st in ("1to2", "2to3", "3to4"):
                    pass_df, slot_df = m1.sim_standalone(st, p_mod, np.zeros(len(p_mod)))
                    ev_s = wm.evaluate_ledger_windows(slot_df, pass_df, pass_df, ctx, perm_n=500)
                    rows.append(wm.flatten_row(f"M3_SOLO_{st}_{cond_name}_{act}", st, f"{cond_name}|{act}", "m3_standalone", ev_s))
            tr_m3, ev_m3 = _run_v20_with_pools(p_dict, ctx, perm_n=1000)
            rows.append(wm.flatten_row(f"M3_COMB_{cond_name}_{act}", "+".join(st_list), f"{cond_name}|{act}", "m3_combined_v20", ev_m3))
            m3_details.append({
                "cond": cond_name, "action": act, "strategies": st_list, "n_passing_overridden": tot_trig,
                "v20_5y_nav": ev_m3["windows"]["Y5"]["nav"], "v20_2326_nav": ev_m3["windows"]["WF_23_26"]["nav"],
                "v20_2526_nav": ev_m3["windows"]["OOS_25_26"]["nav"], "v20_26_nav": ev_m3["windows"]["Y2026"]["nav"],
                "v20_5y_mdd": ev_m3["windows"]["Y5"]["daily_mdd_pct"], "v20_5y_wr": ev_m3["windows"]["Y5"]["wr_pct"],
            })
    print(f"[M3] Completed in {time.time()-t_m3:.2f}s")

    res_df = pd.DataFrame(rows)
    res_df.to_csv(f"{OUT_DIR}/_partial_m1_m3_matrix.csv", index=False, encoding="utf-8-sig")
    with open(f"{OUT_DIR}/_partial_m3_details.pkl", "wb") as f:
        pickle.dump(m3_details, f)
    print(f"[DONE M1+M3 in {time.time()-t0:.2f}s] Saved {len(res_df)} rows -> _partial_m1_m3_matrix.csv")


if __name__ == "__main__":
    main()
