#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD038 Shared Portfolio Assembly Engine, Swap Simulator, Exact MTM & DSR/Metrics."""

import math
import os
import sys
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
RD036 = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126"
WAVE1 = f"{RD035}/wave1_base"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
RD028 = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
RD036_P2 = f"{RD036}/part2_other5"

for p in (WAVE1, PARTC_V20, RD028, RD036_P2):
    if p not in sys.path:
        sys.path.insert(0, p)

import _wf_sim_and_metrics as wfm
import step4_mod_rules_and_sim as m1
import tier_priority_engine as tpe
import _common_rd036 as cm

WF_START = "2023-01-03"
WF_END = "2026-11-16"
TRD_DAYS_YEAR = 242.0

EVAL_WINDOWS = [
    ("FULL_5Y", "2021-11-16", WF_END),
    ("WF_2326", WF_START, WF_END),
    ("Y2025_2026", "2025-01-01", WF_END),
    ("Y2026", "2026-01-01", WF_END),
    ("Y2026_H2", "2026-07-01", WF_END),
]

S_HIGH_TIER_SET = {
    "3to4_S(>=102)", "high_S(>=96)", "pry_S(>=175)", "pry_A(165-174)", "2to3_S(>=96)"
}

# Verified multi-trial DSR variance inputs from RD035 (6,945 trials) & RD036 (548 + 525 trials)
DSR_VAR_POOLED = 0.001459
DSR_N_RD035_036A = 7493
DSR_N_CUM_PRIOR = 8018  # 6945 + 548 + 525


def _fee_cols(fee_mode: str, strat: str) -> tuple[str, str, float]:
    if fee_mode == "native":
        fv = 0.0030 if strat == "20cm" else 0.0020
        return "net_ret_native", "mtm_5y_native", fv
    tag = {"030": "030", "050": "050", "080": "080"}[fee_mode]
    fv = float(fee_mode) / 10000.0
    return f"net_ret_{tag}", f"mtm_5y_{tag}", fv


def _sim_20cm_score_df(df20: pd.DataFrame, sc_vec: np.ndarray, thr: float) -> pd.DataFrame:
    """Single-slot 20cm selection with arbitrary score vector and threshold."""
    m = df20["can_buy_hygiene"].fillna(True).to_numpy(bool) & np.isfinite(sc_vec) & (sc_vec >= float(thr))
    sub = df20[m].copy()
    if sub.empty:
        return sub
    sub["_sc_adj"] = sc_vec[m]
    srt = sub.sort_values(["buy_date", "_sc_adj", "code"], ascending=[True, False, True], kind="mergesort")
    t_idx, fd = [], ""
    for r in srt.itertuples():
        if (not fd) or (r.buy_date > fd):
            t_idx.append(r.Index)
            fd = str(r.exit_date)
    return srt.loc[t_idx].copy().reset_index(drop=True)


def build_bundle_pools(cache: dict, cfg: dict, fee_mode: str = "030") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build combined 6-strategy pool + untriggered waits matching exact causality config."""
    pools_ext = cache["pools_ext"]
    ut_raw = cache["ut_full_raw"]
    o5 = cache["other5_variants"]
    sc20 = cache["sc20_aligned"]

    s20_cfg = cfg.get("s20", "base_76")
    parts = []
    trig_dts = {}

    for st in cm.ALL6:
        df = pools_ext[st].copy()
        rc, mc, _ = _fee_cols(fee_mode, st)
        df["net_ret"] = df[rc]
        df["mtm_use"] = df[mc]

        if st == "20cm":
            if s20_cfg == "base_76":
                _, sl = m1.sim_standalone("20cm", df, np.zeros(len(df)), cm20_thr=76.0)
                sl["score"] = sl["orig_score"].astype(float)
                sl["tier"] = [tpe.assign_physical_tier("20cm", x) for x in sl["score"]]
            elif s20_cfg == "base_82_clean":
                _, sl = m1.sim_standalone("20cm", df, np.zeros(len(df)), cm20_thr=82.0)
                sl["score"] = sl["orig_score"].astype(float)
                sl["tier"] = [tpe.assign_physical_tier("20cm", x) for x in sl["score"]]
            else:
                # Pre-WF (<2023-01-03) matches exact V20.0 baseline unless cold50_5y
                if s20_cfg == "cold50_5y":
                    sl = _sim_20cm_score_df(df, sc20["cold50"], 80.0)
                    sl["score"] = sl["_sc_adj"].astype(float)
                else:
                    _, sl_pre76 = m1.sim_standalone("20cm", df, np.zeros(len(df)), cm20_thr=76.0)
                    sl_pre = sl_pre76[(sl_pre76["buy_date"] < WF_START) & (sl_pre76["orig_score"] >= 82.0)].copy()
                    sl_pre["score"] = sl_pre["orig_score"].astype(float)
                    if s20_cfg == "base_80_wf":
                        sv = np.where(df["buy_date"] >= WF_START, df["orig_score"].to_numpy(float), -999.0)
                    elif s20_cfg == "cold50_wf":
                        sv = np.where(df["buy_date"] >= WF_START, sc20["cold50"], -999.0)
                    else:
                        sv = np.where(df["buy_date"] >= WF_START, sc20[s20_cfg], -999.0)
                    sl_wf = _sim_20cm_score_df(df, sv, float(cfg.get("s20_thr", 80.0)))
                    sl_wf["score"] = sl_wf["_sc_adj"].astype(float)
                    sl = pd.concat([sl_pre, sl_wf], ignore_index=True)
                sl["tier"] = "20cm_S(>=82)"  # Eligible passing 20cm in V20 at priority 6
        else:
            vkey = {
                "3to4": cfg.get("s34", "base"),
                "2to3": cfg.get("s23", "base"),
                "high": cfg.get("shi", "base"),
                "pry": cfg.get("spr", "base"),
                "1to2": cfg.get("s12", "base"),
            }[st]
            if vkey == "base":
                _, sl = cm.sim_strategy(st, df, df["orig_score"].to_numpy(float), wf_only=False)
                sc_col = sl["orig_score"].to_numpy(float)
            else:
                vcfg = o5[st][vkey]
                _, sl = cm.sim_strategy(st, df, vcfg["score"], mask=vcfg["mask"], wf_only=False)
                sc_col = sl["_sc_adj"].to_numpy(float) if "_sc_adj" in sl.columns else sl["orig_score"].to_numpy(float)
            sl["score"] = [round(float(x), 1) for x in sc_col] if st == "1to2" else sc_col.astype(float)
            sl["tier"] = [tpe.assign_physical_tier(st, sc) for sc in sl["score"]]

        sl = sl[sl["buy_date"].between("2021-11-16", WF_END)].copy()
        sl["strategy"] = st
        sl["is_untrig"] = False
        if "buy_price_val" not in sl.columns:
            sl["buy_price_val"] = pd.to_numeric(sl.get("buy_price", np.nan), errors="coerce")
        if "is_adj_px" not in sl.columns:
            sl["is_adj_px"] = False
        trig_dts[st] = set(sl["buy_date"])
        keep_cols = [
            "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
            "strategy", "tier", "score", "net_ret", "mtm_use", "buy_price_val", "is_adj_px", "is_untrig",
        ]
        parts.append(sl[keep_cols])

    pool6 = pd.concat(parts, ignore_index=True)

    # Untriggered conditional waits
    ut_parts = []
    for st_u in ("3to4", "high", "1to2"):
        sub_u = ut_raw[(ut_raw["strategy"] == st_u) & (~ut_raw["buy_date"].isin(trig_dts.get(st_u, set())))].copy()
        thr_u = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[st_u]
        sub_u = sub_u[sub_u["score"] >= thr_u].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
        if not sub_u.empty:
            sub_u["tier"] = [tpe.assign_physical_tier(st_u, sc) for sc in sub_u["score"]]
            ut_parts.append(sub_u)
    ut_df = pd.concat(ut_parts, ignore_index=True) if ut_parts else pd.DataFrame()
    if not ut_df.empty:
        ut_df["is_untrig"] = True
        ut_df["net_ret"] = 0.0
        ut_df["mtm_use"] = [() for _ in range(len(ut_df))]
        ut_df["buy_price_val"] = np.nan
        ut_df["is_adj_px"] = False
        ut_df = ut_df[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "mtm_use", "buy_price_val", "is_adj_px", "is_untrig"]]
    return pool6, ut_df


def _recompute_mtm_0925(c6: str, b0_dt: str, tp1_dt: str, r_0925: float, st_info: dict, cal_5y: list[str], idx_5y: dict, swap_close_lu: dict) -> tuple:
    bi, ei = idx_5y.get(b0_dt), idx_5y.get(tp1_dt)
    if bi is None or ei is None or ei <= bi:
        return ((ei if ei is not None else bi), 1.0 + r_0925) if bi is not None else ()
    b_adj = float(st_info["buy_adj"])
    prev_v = b_adj
    segs = []
    for t in range(bi, ei):
        cur_c = swap_close_lu.get((c6, cal_5y[t]), prev_v)
        segs.append((t, cur_c / prev_v))
        prev_v = cur_c
    segs.append((ei, (b_adj * (1.0 + r_0925)) / prev_v))
    return tuple(segs)


def run_bundle_sim(cache: dict, cfg: dict, fee_mode: str = "030") -> dict:
    """Run exact causal 5Y single-slot simulation with optional w2a5 09:25 swap & w2a6 priority/wait."""
    cal_5y = cache["cal_5y"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    b0_lu = cache["b0_lu"]
    swap_close_lu = cache["swap_close_lu"]

    pool6, ut_df = build_bundle_pools(cache, cfg, fee_mode=fee_mode)
    w2a6_mode = cfg.get("w2a6", "s_tier_reserve_only")
    w2a5_mode = cfg.get("w2a5", "none")

    df = pd.concat([pool6, ut_df], ignore_index=True) if not ut_df.empty else pool6.copy()
    df["prio"] = df["tier"].map(m1.S2C_MAP).fillna(999).astype(int)
    df = df[df["prio"] < 999].copy()

    if w2a6_mode == "s_tier_reserve_only":
        is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"])
        df["phase"] = np.where((df["buy_hhmm"] == 925) | is_s_cond, 0, 1)
    elif w2a6_mode == "s_tier_plus_1to2S":
        is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)", "1to2_S(>=340)"])
        df["phase"] = np.where((df["buy_hhmm"] == 925) | is_s_cond, 0, 1)
    elif w2a6_mode == "trig_1to2S_phase0_no_wait":
        is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"]) | ((~df["is_untrig"]) & (df["tier"] == "1to2_S(>=340)"))
        df["phase"] = np.where((df["buy_hhmm"] == 925) | is_s_cond, 0, 1)
    else:
        raise ValueError(f"Unknown w2a6_mode: {w2a6_mode}")

    srt = df.sort_values(["buy_date", "phase", "prio", "score", "buy_hhmm", "code"], ascending=[True, True, True, False, True, True], kind="mergesort").reset_index(drop=True)
    by_dt = {dt: grp for dt, grp in srt.groupby("buy_date", sort=False)}

    taken = []
    waits = []
    swaps = []
    cur_hold = None
    cur_ed, cur_eh = "", 0

    for dt in cal_5y:
        grp = by_dt.get(dt)
        did_swap = False

        # Step 1: Check w2a5 T+1 09:25 weak-red swap if enabled
        if w2a5_mode != "none" and cur_hold is not None and (cur_ed > dt or (cur_ed == dt and cur_eh > 925)):
            if cur_hold["strategy"] in ("1to2", "2to3"):
                st_info = b0_lu.get((cur_hold["strategy"], cur_hold["code"], cur_hold["buy_date"]))
                if st_info and st_info["tp1_dt"] == dt and st_info["sellable_0925"] and st_info["b0_red_close"] and (0.5 <= st_info["op1_pct"] <= 2.5):
                    best_cand = None
                    if grp is not None:
                        for cr in grp.itertuples(index=False):
                            if w2a5_mode == "S_HighTier_0925":
                                ok = cr.tier in S_HIGH_TIER_SET
                            elif w2a5_mode == "StrictHigherPrio_0925":
                                ok = (int(cr.prio) < int(cur_hold["prio"])) or (int(cr.prio) == int(cur_hold["prio"]) and float(cr.score) > float(cur_hold["score"]))
                            else:
                                ok = False
                            if ok:
                                best_cand = cr
                                break
                    if best_cand is not None:
                        _, _, fv = _fee_cols(fee_mode, cur_hold["strategy"])
                        r_0925 = (1.0 + st_info["gross_0925"]) * (1.0 - fv) - 1.0
                        orig_ret = float(cur_hold["net_ret"])
                        cur_hold["exit_date"] = dt
                        cur_hold["exit_hhmm"] = 925
                        cur_hold["net_ret"] = float(r_0925)
                        cur_hold["mtm_use"] = _recompute_mtm_0925(cur_hold["code"], cur_hold["buy_date"], dt, r_0925, st_info, cal_5y, idx_5y, swap_close_lu)
                        did_swap = True
                        swaps.append({
                            "swap_date": dt, "old_strat": cur_hold["strategy"], "old_code": cur_hold["code"],
                            "old_name": cur_hold["name"], "old_orig_ret": round(orig_ret * 100, 2),
                            "old_0925_ret": round(r_0925 * 100, 2), "new_strat": best_cand.strategy,
                            "new_tier": best_cand.tier, "new_code": best_cand.code, "new_name": best_cand.name,
                            "new_is_untrig": bool(best_cand.is_untrig), "new_ret": round(float(best_cand.net_ret) * 100, 2),
                        })
                        if not bool(best_cand.is_untrig):
                            new_rec = best_cand._asdict()
                            new_rec["swapped_in"] = True
                            taken.append(new_rec)
                            cur_hold = new_rec
                            cur_ed, cur_eh = str(new_rec["exit_date"]), int(new_rec["exit_hhmm"])
                        else:
                            waits.append({"buy_date": dt, "wait_strategy": best_cand.strategy, "wait_tier": best_cand.tier, "wait_code": best_cand.code, "from_swap": True})
                            cur_hold = None
                            cur_ed, cur_eh = str(best_cand.exit_date), int(best_cand.exit_hhmm)

        if did_swap or grp is None:
            continue

        # Step 2: Normal entry
        for r in grp.itertuples(index=False):
            if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh):
                if r.is_untrig:
                    waits.append({"buy_date": r.buy_date, "wait_strategy": r.strategy, "wait_tier": r.tier, "wait_code": r.code, "from_swap": False})
                    cur_hold = None
                    cur_ed, cur_eh = str(r.exit_date), int(r.exit_hhmm)
                else:
                    rec = r._asdict()
                    rec["swapped_in"] = False
                    taken.append(rec)
                    cur_hold = rec
                    cur_ed, cur_eh = str(rec["exit_date"]), int(rec["exit_hhmm"])
                break

    tr_df = pd.DataFrame(taken)
    if not tr_df.empty:
        assert (tr_df["exit_date"] > tr_df["buy_date"]).all(), "T+0 violation"
        for i in range(1, len(tr_df)):
            p, c = tr_df.iloc[i - 1], tr_df.iloc[i]
            if bool(c.get("swapped_in", False)):
                assert (c["buy_date"], int(c["buy_hhmm"])) >= (p["exit_date"], int(p["exit_hhmm"])), f"Swap overlap at {i}"
            else:
                assert (c["buy_date"], int(c["buy_hhmm"])) > (p["exit_date"], int(p["exit_hhmm"])), f"Overlap at {i}"

    # Build exact 5Y daily MTM series
    T = len(cal_5y)
    day_mult = np.ones(T, dtype=float)
    if not tr_df.empty:
        for r in tr_df.itertuples(index=False):
            segs = getattr(r, "mtm_use", None)
            if segs:
                for ti, mult in segs:
                    if 0 <= int(ti) < T:
                        day_mult[int(ti)] *= float(mult)
            else:
                bi, ei = idx_5y.get(r.buy_date), idx_5y.get(r.exit_date)
                if bi is not None and ei is not None and ei > bi:
                    span = ei - bi + 1
                    day_mult[bi : ei + 1] *= (1.0 + float(r.net_ret)) ** (1.0 / span)
    dr_5y = day_mult - 1.0
    nav_5y_tr = float(np.prod(1.0 + tr_df["net_ret"].to_numpy(float))) if not tr_df.empty else 1.0
    mtm_diff_5y = abs(float(np.prod(day_mult)) - nav_5y_tr)

    # Check WF MTM separately (confirm zero cross-boundary trades across 2022-12-30 -> 2023-01-03)
    wf_off = idx_5y[WF_START]
    tr_wf = tr_df[tr_df["buy_date"] >= WF_START] if not tr_df.empty else tr_df
    dr_wf = dr_5y[wf_off:]
    nav_wf_tr = float(np.prod(1.0 + tr_wf["net_ret"].to_numpy(float))) if not tr_wf.empty else 1.0
    mtm_diff_wf = abs(float(np.prod(1.0 + dr_wf)) - nav_wf_tr)

    return {
        "trades_df": tr_df,
        "waits": waits,
        "swaps": swaps,
        "pool6": pool6,
        "ut_df": ut_df,
        "dr_5y": dr_5y,
        "dr_wf": dr_wf,
        "mtm_diff_5y": float(mtm_diff_5y),
        "mtm_diff_wf": float(mtm_diff_wf),
    }


def evaluate_bundle(
    name: str,
    group: str,
    sim_res: dict,
    cache: dict,
    ref_dr_wf: Optional[np.ndarray] = None,
    perm_n: int = 1000,
) -> dict:
    """Compute full 5-window metrics, 1000x permutation test, and paired-t vs V20."""
    cal_5y = cache["cal_5y"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    bench = cache["bench_5y"]
    csi_5y = bench["csi300_daily_ret"].to_numpy(float)
    ew_5y = bench["alla_ew_daily_ret"].to_numpy(float)
    tr_df = sim_res["trades_df"]
    dr_5y = sim_res["dr_5y"]
    dr_wf = sim_res["dr_wf"]

    windows = {}
    for wn, sdt, edt in EVAL_WINDOWS:
        windows[wn] = wfm._calc_one_window(tr_df, None, dr_5y, cal_5y, idx_5y, csi_5y, ew_5y, sdt, edt)

    perm_wf = {"same_day_p_nav": np.nan, "any_cand_day_p_nav": np.nan}
    if perm_n > 0 and not tr_df.empty:
        tr_wf = tr_df[tr_df["buy_date"] >= WF_START]
        perm_wf = wfm.perm_test_trading_days(tr_wf, cache["master_cand_perm"], WF_START, WF_END, n_perm=perm_n, seed=20261126)

    paired = {"paired_t": 0.0, "paired_p_2sided": 1.0, "paired_p_1sided": 0.5, "n_diff_days": 0, "corr": 1.0}
    if ref_dr_wf is not None:
        dd = dr_wf - ref_dr_wf
        nz = np.abs(dd) > 1e-12
        sd = float(np.std(dd, ddof=1))
        T_wf = len(dr_wf)
        t_stat = float(np.mean(dd) / (sd / math.sqrt(T_wf))) if sd > 1e-12 else 0.0
        p2 = float(2.0 * stats.t.sf(abs(t_stat), df=T_wf - 1)) if sd > 1e-12 else 1.0
        p1 = float(stats.t.sf(t_stat, df=T_wf - 1)) if sd > 1e-12 else 0.5
        corr = float(np.corrcoef(dr_wf, ref_dr_wf)[0, 1]) if (np.std(dr_wf) > 1e-12 and np.std(ref_dr_wf) > 1e-12) else 1.0
        paired = {
            "paired_t": round(t_stat, 3),
            "paired_p_2sided": round(p2, 4),
            "paired_p_1sided": round(p1, 4),
            "n_diff_days": int(nz.sum()),
            "corr": round(corr, 4),
        }

    return {
        "name": name,
        "group": group,
        "mtm_diff_5y": round(sim_res["mtm_diff_5y"], 9),
        "mtm_diff_wf": round(sim_res["mtm_diff_wf"], 9),
        "n_waits": len(sim_res["waits"]),
        "n_swaps": len(sim_res["swaps"]),
        "windows": windows,
        "perm_wf": perm_wf,
        "vs_v20_wf": paired,
    }
