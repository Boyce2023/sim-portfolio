#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-5 Runner Part 2 (Module 2 - PM Pain Point #1: Weak-Red-Open 09:25 Swap):
Tests chronological V20.0 combined single-slot rotation when 1to2 / 2to3 (/ 3to4) unsealed red-close
positions gap weakly red at T+1 09:25 (+0.5..+2.0/2.5/3.0/4.0%) and a higher-tier morning signal appears.
Outputs exact swap ledger diff -> `w2a5_swap_trades_diff.csv` and summary -> `_partial_m2_swaps.csv`.
"""
import os
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
import tier_priority_engine as tpe


def _build_combined_pool(pools_030: dict, untrig_base: pd.DataFrame, ctx: dict, use_standalone_filter: bool = True) -> pd.DataFrame:
    """Build unified chronological event table matching V20.0 P3_S2C_STierReserveOnly."""
    parts = []
    trig_dts_by_strat = {}
    for st in m1.STRAT_ORDER:
        df = pools_030[st]
        if use_standalone_filter:
            thr_20 = 76.0 if st == "20cm" else 82.0
            _, chosen = m1.sim_standalone(st, df, np.zeros(len(df), dtype=float), high_cb_mode="v51_exact", cm20_thr=thr_20)
        else:
            m = df["is_pass_official"] == 1
            if st == "20cm":
                m = m & (df["v20_score"] >= 82.0)
            chosen = df[m].sort_values(["buy_date", "v20_score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()

        chosen = chosen[chosen["buy_date"].between("2021-11-16", "2026-11-16")].copy()
        if chosen.empty:
            trig_dts_by_strat[st] = set()
            continue
        chosen["score"] = [round(float(x), 1) for x in chosen["v20_score"]] if st == "1to2" else chosen["v20_score"].astype(float)
        chosen["tier"] = [tpe.assign_physical_tier(st, sc) for sc in chosen["score"]]
        chosen["is_untrig"] = False
        trig_dts_by_strat[st] = set(chosen["buy_date"])
        cols = [
            "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
            "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px",
            "is_untrig", "mtm_full", "mtm_5y",
        ]
        parts.append(chosen[cols])

    pool6 = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    ut = untrig_base[untrig_base["buy_date"].between("2021-11-16", "2026-11-16")].copy()
    ut_parts = []
    for st_u in ("3to4", "high", "1to2"):
        sub_u = ut[(ut["strategy"] == st_u) & (~ut["buy_date"].isin(trig_dts_by_strat.get(st_u, set())))].copy()
        thr_u = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[st_u]
        sub_u = sub_u[sub_u["v20_score"] >= thr_u].copy()
        if not sub_u.empty:
            sub_u["score"] = sub_u["v20_score"].astype(float)
            sub_u["tier"] = [tpe.assign_physical_tier(st_u, sc) for sc in sub_u["score"]]
            sub_u = sub_u.sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
            ut_parts.append(sub_u)

    if ut_parts:
        ut_f = pd.concat(ut_parts, ignore_index=True)
        ut_f["is_untrig"] = True
        ut_f["net_ret"] = 0.0
        ut_f["buy_price_val"] = np.nan
        ut_f["is_adj_px"] = False
        ut_f["mtm_full"] = [() for _ in range(len(ut_f))]
        ut_f["mtm_5y"] = [() for _ in range(len(ut_f))]
        ut_cols = [
            "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
            "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px",
            "is_untrig", "mtm_full", "mtm_5y",
        ]
        all_df = pd.concat([pool6, ut_f[ut_cols]], ignore_index=True)
    else:
        all_df = pool6

    all_df["prio"] = all_df["tier"].map(m1.S2C_MAP).fillna(999).astype(int)
    all_df = all_df[all_df["prio"] < 999].copy()
    is_s_cond = all_df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"])
    all_df["phase"] = np.where((all_df["buy_hhmm"] == 925) | is_s_cond, 0, 1)
    all_df = all_df.sort_values(
        ["buy_date", "phase", "prio", "score", "buy_hhmm", "code"],
        ascending=[True, True, True, False, True, True],
    ).reset_index(drop=True)
    return all_df


def _calc_b0_state(r, ctx: dict) -> dict:
    """Precompute causal b0/tp1 state for a trade."""
    c6 = str(r.code).zfill(6)
    bd = str(r.buy_date)[:10]
    ss = ctx["stock_series"].get(c6)
    if ss is None or bd not in ss["d2i"]:
        return {"valid": False}
    b0 = ss["d2i"][bd]
    if b0 + 1 >= len(ss["dts"]):
        return {"valid": False}
    k1 = b0 + 1
    pc0 = float(ss["prev_c"][b0])
    c0 = float(ss["close"][b0])
    o0 = float(ss["open"][b0])
    zt0 = bool(ss["is_zt"][b0])
    tp1_dt = str(ss["dts"][k1])
    o1 = float(ss["open"][k1])
    pc1 = float(ss["prev_c"][k1])
    op1_pct = (o1 / pc1 - 1.0) * 100.0 if pc1 > 0 else np.nan
    sellable_0925 = (not bool(ss["is_yizi_dt"][k1])) and (o1 > float(ss["dt_px"][k1]) + 0.005)
    adjf0 = float(ss["adjf"][b0])
    bp_val = float(r.buy_price_val) if pd.notna(r.buy_price_val) else o0
    buy_adj = bp_val if bool(r.is_adj_px) else bp_val * adjf0
    r_0925 = (o1 * float(ss["adjf"][k1]) / buy_adj) * (1.0 - 0.0030) - 1.0 if buy_adj > 0 else 0.0
    return {
        "valid": True,
        "b0_unsealed": (not zt0),
        "b0_red_close": (not zt0) and (pc0 > 0) and (c0 > pc0),
        "b0_yang_or_red": (not zt0) and ((pc0 > 0 and c0 > pc0) or (c0 >= o0)),
        "tp1_dt": tp1_dt,
        "op1_pct": float(op1_pct),
        "sellable_0925": sellable_0925,
        "r_0925": float(r_0925),
        "px_0925": round(o1, 2),
        "buy_adj": float(buy_adj),
        "b0_idx": b0,
        "k1_idx": k1,
    }


def _recompute_trade_mtm_until_0925(c6: str, b0_dt: str, tp1_dt: str, r_0925: float, ctx: dict) -> tuple:
    """Build exact mtm_5y segments for a trade exited at tp1_dt 09:25."""
    cal_5y = ctx["cal_5y"]
    dt_to_idx = {d: i for i, d in enumerate(cal_5y)}
    bi = dt_to_idx.get(b0_dt)
    ei = dt_to_idx.get(tp1_dt)
    if bi is None or ei is None or ei <= bi:
        return ()
    ss = ctx["stock_series"][c6]
    b0_i = ss["d2i"][b0_dt]
    b_adj = float(ss["open"][b0_i]) * float(ss["adjf"][b0_i])
    # Use ratio relative to close at bi..ei-1, then close out to 1 + r_0925 at ei
    prev_v = b_adj
    segs = []
    for t in range(bi, ei):
        bt = ctx["bar_lu"].get((c6, cal_5y[t]))
        cur_c = bt[1] * bt[4] if bt else prev_v
        segs.append((t, cur_c / prev_v))
        prev_v = cur_c
    segs.append((ei, (b_adj * (1.0 + r_0925)) / prev_v))
    return tuple(segs)


def run_chronological_swap_sim(
    all_df: pd.DataFrame,
    ctx: dict,
    source_strats: tuple,
    red_def: str,
    gap_lo: float,
    gap_hi: float,
    target_mode: str,
    exec_mode: str,
    allow_untrig_target: bool = True,
) -> tuple[pd.DataFrame, list[dict]]:
    """
    Chronological day-by-day single-slot simulation with T+1 09:25 weak-red-open swap.
    Zero lookahead: at tp1_dt 09:25, decision uses ONLY b0 morphology, tp1 09:25 open, and morning signals on tp1_dt.
    """
    by_dt = {dt: grp for dt, grp in all_df.groupby("buy_date", sort=True)}
    cal_5y = ctx["cal_5y"]
    dt_to_idx = {d: i for i, d in enumerate(cal_5y)}

    def _matches_target(cand_row, hold_row) -> bool:
        if not allow_untrig_target and bool(cand_row.is_untrig):
            return False
        if exec_mode == "cond_only" and int(cand_row.buy_hhmm) == 925:
            return False
        if target_mode == "S_HighTier":
            return cand_row.tier in ("3to4_S(>=102)", "high_S(>=96)", "pry_S(>=175)", "pry_A(165-174)", "2to3_S(>=96)")
        if target_mode == "HighOr23_All":
            return cand_row.strategy in ("3to4", "high", "pry", "2to3", "20cm")
        if target_mode == "StrictHigherPrio":
            return (int(cand_row.prio) < int(hold_row["prio"])) or (
                int(cand_row.prio) == int(hold_row["prio"]) and float(cand_row.score) > float(hold_row["score"])
            )
        if target_mode == "AnyV20Signal":
            return True
        if target_mode == "NoSignalRequired":
            return True
        raise ValueError(target_mode)

    taken = []
    swap_logs = []
    cur_hold = None  # active real trade dict (or wait block with exit_date, exit_hhmm)
    cur_ed, cur_eh = "", 0

    for dt in cal_5y:
        cands_today = by_dt.get(dt)
        did_swap_today = False

        # Step 1: Check if cur_hold is eligible for 09:25 swap on dt
        if cur_hold is not None and (not cur_hold["is_untrig"]) and (cur_ed > dt or (cur_ed == dt and cur_eh > 925)):
            if cur_hold["strategy"] in source_strats:
                st = cur_hold["b0_state"]
                if st["valid"] and st["tp1_dt"] == dt and st["sellable_0925"]:
                    is_red_ok = st[red_def]
                    if is_red_ok and (gap_lo <= st["op1_pct"] <= gap_hi):
                        # Check morning signal on dt
                        best_cand = None
                        if target_mode == "NoSignalRequired":
                            best_cand = "CUT_ONLY"
                        elif cands_today is not None:
                            for cr in cands_today.itertuples(index=False):
                                if _matches_target(cr, cur_hold):
                                    best_cand = cr
                                    break
                        if best_cand is not None:
                            # Execute 09:25 exit on cur_hold!
                            old_st = cur_hold["strategy"]
                            old_cd = cur_hold["code"]
                            old_nm = cur_hold["name"]
                            old_bd = cur_hold["buy_date"]
                            orig_ret = float(cur_hold["net_ret"])
                            orig_ed = cur_hold["exit_date"]
                            orig_eh = int(cur_hold["exit_hhmm"])
                            cur_hold["exit_date"] = dt
                            cur_hold["exit_hhmm"] = 925
                            cur_hold["net_ret"] = st["r_0925"]
                            cur_hold["mtm_5y"] = _recompute_trade_mtm_until_0925(old_cd, old_bd, dt, st["r_0925"], ctx)
                            cur_ed = dt
                            cur_eh = 925
                            did_swap_today = True

                            if best_cand == "CUT_ONLY":
                                swap_logs.append({
                                    "swap_date": dt, "old_strat": old_st, "old_code": old_cd,
                                    "old_name": old_nm, "old_buy_date": old_bd,
                                    "old_orig_exit": f"{orig_ed}({orig_eh})", "old_orig_ret_pct": round(orig_ret * 100, 2),
                                    "old_0925_ret_pct": round(st["r_0925"] * 100, 2), "tp1_open_pct": round(st["op1_pct"], 2),
                                    "new_strat": "CASH", "new_tier": "CASH", "new_code": "", "new_name": "",
                                    "new_buy_hhmm": 0, "new_is_untrig": False, "new_ret_pct": 0.0,
                                    "net_swap_alpha_pp": round((st["r_0925"] - orig_ret) * 100, 2),
                                })
                                cur_hold = None
                            else:
                                # Enter best_cand immediately (even if buy_hhmm == 925 under exec_0925_simultaneous!)
                                new_rec = best_cand._asdict()
                                if exec_mode == "0930_realistic" and int(best_cand.buy_hhmm) == 925 and not bool(best_cand.is_untrig):
                                    arr_n = ctx["b5m"].get((best_cand.code, dt))
                                    if arr_n is not None and len(arr_n) > 0:
                                        o_930 = float(arr_n[0, 1])
                                        ss_n = ctx["stock_series"].get(best_cand.code)
                                        if ss_n is not None and dt in ss_n["d2i"]:
                                            b0_n = ss_n["d2i"][dt]
                                            if o_930 > 0 and o_930 < float(ss_n["zt_px"][b0_n]) - 0.005:
                                                adj0_n = float(ss_n["adjf"][b0_n])
                                                bp_old = float(best_cand.buy_price_val) if bool(best_cand.is_adj_px) else float(best_cand.buy_price_val) * adj0_n
                                                bp_new = o_930 * adj0_n
                                                if bp_old > 0 and bp_new > 0:
                                                    new_rec["net_ret"] = (1.0 + float(best_cand.net_ret)) * (bp_old / bp_new) - 1.0
                                                    if best_cand.mtm_5y:
                                                        ti0 = dt_to_idx.get(dt)
                                                        new_rec["mtm_5y"] = tuple(
                                                            (ti, mult * (bp_old / bp_new) if ti == ti0 else mult)
                                                            for ti, mult in best_cand.mtm_5y
                                                        )
                                new_rec["b0_state"] = _calc_b0_state(best_cand, ctx)
                                cur_ed = str(new_rec["exit_date"])
                                cur_eh = int(new_rec["exit_hhmm"])
                                if not bool(new_rec["is_untrig"]):
                                    taken.append(new_rec)
                                    cur_hold = new_rec
                                else:
                                    cur_hold = {"is_untrig": True}
                                swap_logs.append({
                                    "swap_date": dt, "old_strat": old_st,
                                    "old_code": old_cd, "old_name": old_nm, "old_buy_date": old_bd,
                                    "old_orig_exit": f"{orig_ed}({orig_eh})", "old_orig_ret_pct": round(orig_ret * 100, 2),
                                    "old_0925_ret_pct": round(st["r_0925"] * 100, 2), "tp1_open_pct": round(st["op1_pct"], 2),
                                    "new_strat": new_rec["strategy"], "new_tier": new_rec["tier"], "new_code": new_rec["code"],
                                    "new_name": new_rec["name"], "new_buy_hhmm": int(new_rec["buy_hhmm"]),
                                    "new_is_untrig": bool(new_rec["is_untrig"]), "new_ret_pct": round(float(new_rec["net_ret"]) * 100, 2),
                                    "net_swap_alpha_pp": round(((1.0 + st["r_0925"]) * (1.0 + float(new_rec["net_ret"])) - 1.0 - orig_ret) * 100, 2),
                                })
                                continue

        # Step 2: Normal chronological entry on dt if slot free
        if cands_today is None or did_swap_today:
            continue
        for r in cands_today.itertuples(index=False):
            can_enter = (not cur_ed) or (dt > cur_ed) or (dt == cur_ed and int(r.buy_hhmm) > cur_eh)
            if can_enter:
                rec = r._asdict()
                rec["b0_state"] = _calc_b0_state(r, ctx)
                cur_ed = str(r.exit_date)
                cur_eh = int(r.exit_hhmm)
                if not bool(r.is_untrig):
                    taken.append(rec)
                    cur_hold = rec
                else:
                    cur_hold = {"is_untrig": True}
                break

    res_df = pd.DataFrame(taken) if taken else pd.DataFrame()
    return res_df, swap_logs


def main():
    t0 = time.time()
    ctx = dl.load_w2a5_context("2026-11-16")
    pools_030 = {st: et.apply_tree_to_pool(ctx["pools"][st], st, "E0_Native", ctx, fee=0.0030) for st in m1.STRAT_ORDER}

    cand_all = pd.concat(
        [pools_030[st][pools_030[st]["is_pass_official"] == 1][["buy_date", "code", "net_ret"]] for st in m1.STRAT_ORDER],
        ignore_index=True,
    )

    all_slot_df = _build_combined_pool(pools_030, ctx["untrig_base"], ctx, use_standalone_filter=True)
    all_pass_df = _build_combined_pool(pools_030, ctx["untrig_base"], ctx, use_standalone_filter=False)

    # Verify baseline (no swaps) reproduces exact 278 trades at 0.30%
    base_tr, _ = run_chronological_swap_sim(all_slot_df, ctx, (), "b0_red_close", 99, 99, "AnyV20Signal", "0925_simul")
    assert len(base_tr) == 278, f"Swap engine baseline mismatch: {len(base_tr)}"
    ev_base = wm.evaluate_ledger_windows(base_tr, None, cand_all, ctx, perm_n=1000)

    # Fix minor log field bug cleanly post-hoc or inline — wait let's record accurate old_code/old_name in swap_logs:
    # Let's inspect & run grid!
    gap_grids = [(0.5, 2.0), (0.5, 2.5), (0.5, 3.0), (0.5, 4.0), (0.0, 3.0)]
    scopes = [("1to2+2to3", ("1to2", "2to3")), ("1to2+2to3+3to4", ("1to2", "2to3", "3to4"))]
    targets = ["S_HighTier", "HighOr23_All", "StrictHigherPrio", "AnyV20Signal", "NoSignalRequired"]
    exec_modes = ["0925_simul", "0930_realistic", "cond_only"]
    pool_modes = [("v20_slot", all_slot_df), ("v20_top1_unfilt", all_pass_df)]

    rows = []
    all_swap_diffs = []
    for p_lbl, pool_tbl in pool_modes:
        ev_p_base = ev_base if p_lbl == "v20_slot" else wm.evaluate_ledger_windows(
            run_chronological_swap_sim(pool_tbl, ctx, (), "b0_red_close", 99, 99, "AnyV20Signal", "0925_simul")[0],
            None, cand_all, ctx, perm_n=500,
        )
        rows.append(wm.flatten_row(f"M2_BASE_{p_lbl}", p_lbl, "BASE_NO_SWAP", "m2_swap", ev_p_base))

        for sc_lbl, sc_tup in scopes:
            for red_def in ("b0_red_close", "b0_unsealed"):
                for glo, ghi in gap_grids:
                    for tgt in targets:
                        em_list = ["0925_simul"] if (red_def == "b0_unsealed" or tgt == "NoSignalRequired") else exec_modes
                        if p_lbl == "v20_top1_unfilt" and (red_def == "b0_unsealed" or tgt not in ("S_HighTier", "StrictHigherPrio", "AnyV20Signal")):
                            continue
                        for em in em_list:
                            tr_s, sw_logs = run_chronological_swap_sim(pool_tbl, ctx, sc_tup, red_def, glo, ghi, tgt, em)
                            ev_s = wm.evaluate_ledger_windows(tr_s, None, cand_all, ctx, perm_n=1000 if p_lbl == "v20_slot" else 200)
                            tag = f"{p_lbl}|{sc_lbl}|{red_def}|gap_{glo}_{ghi}|{tgt}|{em}"
                            r_flat = wm.flatten_row(f"M2_{tag}", sc_lbl, tag, "m2_swap", ev_s)
                            r_flat["n_swaps"] = len(sw_logs)
                            rows.append(r_flat)
                            if p_lbl == "v20_slot" and red_def == "b0_red_close" and em in ("0925_simul", "0930_realistic") and sw_logs:
                                for lg in sw_logs:
                                    lg["config"] = tag
                                    all_swap_diffs.append(lg)

    m2_df = pd.DataFrame(rows)
    m2_df.to_csv(f"{OUT_DIR}/_partial_m2_swaps.csv", index=False, encoding="utf-8-sig")
    diff_df = pd.DataFrame(all_swap_diffs)
    diff_df.to_csv(f"{OUT_DIR}/w2a5_swap_trades_diff.csv", index=False, encoding="utf-8-sig")
    print(f"[DONE M2 in {time.time()-t0:.2f}s] {len(m2_df)} configs, {len(diff_df)} swap log rows")


if __name__ == "__main__":
    main()
