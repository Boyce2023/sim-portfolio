#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD039-A Front 1 Step 2:
  1. Run 100%-local-5m covered subset benchmark control (strict zero-guess disclosure).
  2. Run full trigger x cancel_hhmm x multi-cand mode grid across all 4 targets:
     - 2to3_V21 (`v20_score >= 90`)
     - 20cm_S82 (`v20_score >= 82`)
     - 20cm_Stack (`RD036 Stack_c50_Avg_CB15_MN15_R3W12_S80`)
     - 20cm_Blend (`RD036 Blend_c50_Half_CB15_MN15_S80`)
  3. Compute 3-tier velocity slippage + 30/50/80bps + flat friction + strict-seal-ZT stress,
     across FULL_ALL, FULL_5Y, IS_TRUNC(<=2024-12-31), WF(2023-2026), Y2025_2026, Y2026, Y2026H2.
  4. Save `rd039_f1_cond_grid.csv` and `_cache_step2_results.pkl`.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import pickle
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd039_single_strat_sharpe_lift_20261126/front1_2to3_20cm_cond"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import cond_exec_lib as cel

PATH_CACHE_IN = f"{OUT_DIR}/_cache_rd039_f1_inputs.pkl"
PATH_STEP2_OUT = f"{OUT_DIR}/_cache_step2_results.pkl"
PATH_GRID_CSV = f"{OUT_DIR}/rd039_f1_cond_grid.csv"
CANCELS = (945, 1000, 1030, 1130, 1430)


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def build_specs_for_target(target: str) -> list[tuple[str, str, str, int, object]]:
    """Return list of (variant_id, family, kind, cancel_hhmm, param)."""
    specs = [("B0_auc_0925", "0_BASELINE", "auc_0925", 925, None)]
    is_2to3 = (target == "2to3_V21")

    # 1. open + X%
    x_list = [0.5, 1.0, 1.5, 2.0, 3.0] if is_2to3 else [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0]
    for xp in x_list:
        mult = 1.0 + xp / 100.0
        tag = f"op_p{int(round(xp * 10)):02d}"
        for ch in CANCELS:
            specs.append((f"{tag}_c{ch}", "1_OPEN_PCT", "open_mult", ch, mult))

    # 2. 翻红确认
    if is_2to3:
        fh_modes = [
            ("fh_0_allow0925", {"pc_mult": 1.000, "allow_0925": True, "op_floor": None}),
            ("fh_p05_allow0925", {"pc_mult": 1.005, "allow_0925": True, "op_floor": None}),
            ("fh_0_wait0935", {"pc_mult": 1.000, "allow_0925": False, "op_floor": None}),
            ("fh_0_op05", {"pc_mult": 1.000, "allow_0925": False, "op_floor": 1.005}),
            ("fh_0_op10", {"pc_mult": 1.000, "allow_0925": False, "op_floor": 1.010}),
        ]
    else:
        fh_modes = [
            ("fh_0", {"pc_mult": 1.000, "allow_0925": False, "op_floor": None}),
            ("fh_p05", {"pc_mult": 1.005, "allow_0925": False, "op_floor": None}),
        ]
    for fnm, fpar in fh_modes:
        for ch in CANCELS:
            specs.append((f"{fnm}_c{ch}", "2_FANHONG", "prev_close_mult", ch, fpar))

    # 3. 突破首 5m / 前 10m 高点
    for ch in CANCELS:
        if ch >= 945:
            specs.append((f"brk5m_p01_c{ch}", "3_BRK_5M_10M", "brk_5m_hi", ch, {"pad": 0.01}))
            specs.append((f"brk5m_eq_c{ch}", "3_BRK_5M_10M", "brk_5m_hi", ch, {"pad": 0.00}))
        if ch >= 1000:
            specs.append((f"brk10m_p01_c{ch}", "3_BRK_5M_10M", "brk_10m_hi", ch, {"pad": 0.01}))
            specs.append((f"brk10m_eq_c{ch}", "3_BRK_5M_10M", "brk_10m_hi", ch, {"pad": 0.00}))

    # 4. 混合分段条件单
    if is_2to3:
        hyb_list = ["lowFH_hi0925", "lowFH_hiOp10", "lowOp20_hiOp10", "lowOp20_hi0925", "deepFH_midOp15_hiOp05"]
        hkind = "hybrid_23"
    else:
        hyb_list = ["deepOp30_shOp15", "deepOp40_shOp20", "deepFH_shOp20", "deepOp30_shBrk5m"]
        hkind = "hybrid_20"
    for hm in hyb_list:
        for ch in CANCELS:
            if "Brk5m" in hm and ch < 945:
                continue
            specs.append((f"hyb_{hm}_c{ch}", "4_HYBRID", hkind, ch, hm))

    return specs


def eval_target_spec(
    target: str,
    pool_df: pd.DataFrame,
    sc_col: str,
    bars_map: dict,
    dmap: dict,
    bench_df: pd.DataFrame,
    cal_dts: list[str],
    spec: tuple,
    multi_mode: str,
    strict_seal_miss: bool = False,
    allow_0925_unlock: bool = True,
) -> tuple[dict, pd.DataFrame, np.ndarray, pd.DataFrame]:
    """Run one (target, spec, multi_mode) simulation and compute full window/friction metrics."""
    vid, fam, kind, ch, param = spec
    is_2to3 = (target == "2to3_V21")

    # Sort candidates by exact original priority order per date
    if is_2to3:
        srt_cand = pool_df.sort_values(
            ["buy_date", sc_col, "open_pct", "plate_sz", "code"],
            ascending=[True, False, True, True, True],
            kind="mergesort",
        ).reset_index(drop=True)
    else:
        srt_cand = pool_df.sort_values(
            ["buy_date", sc_col, "code"],
            ascending=[True, False, True],
            kind="mergesort",
        ).reset_index(drop=True)

    # Execute bar-by-bar simulation per candidate row
    cand_rows = []
    for rank_idx, g in enumerate(srt_cand.groupby("buy_date", sort=True)):
        bd, grp = g
        for r_i, r in enumerate(grp.itertuples(index=False)):
            if multi_mode == "rank1_only" and r_i > 0:
                continue
            arr = bars_map.get((r.code, r.buy_date))
            res = cel.simulate_bar_execution(
                arr, float(r.open_d), float(r.pre_c), float(r.zt_px), float(r.open_pct),
                kind, ch, param,
            )
            st = res["status"]
            if strict_seal_miss and res.get("strict_seal_missed", False):
                st = "missed_zt"

            row_d = {
                "buy_date": r.buy_date,
                "exit_date": r.exit_date,
                "code": r.code,
                "name": r.name,
                "score": float(getattr(r, sc_col)),
                "open_d": float(r.open_d),
                "pre_c": float(r.pre_c),
                "zt_px": float(r.zt_px),
                "open_pct": float(r.open_pct),
                "gross_ret_orig": float(r.gross_ret),
                "exit_hhmm": int(r.exit_hhmm),
                "rank_in_day": int(r_i + 1),
                "status": st,
                "buy_hhmm": int(res.get("buy_hhmm", 0)),
                "eff_buy_vel": float(res.get("eff_buy_vel", np.nan)),
                "eff_buy_flat": float(res.get("eff_buy_flat", np.nan)),
                "real_slip": float(res.get("real_slip", 0.0)),
                "vel_tier": str(res.get("vel_tier", "")),
                "is_zt_sealed_bar": bool(res.get("is_zt_sealed_bar", False)),
            }
            if st in ("filled_0925", "filled_intraday"):
                ebv = row_d["eff_buy_vel"]
                ebf = row_d["eff_buy_flat"]
                gv = (1.0 + row_d["gross_ret_orig"]) * (row_d["open_d"] / ebv) - 1.0
                gf = (1.0 + row_d["gross_ret_orig"]) * (row_d["open_d"] / ebf) - 1.0
                row_d["net_ret_vel_30"] = (1.0 + gv) * 0.9970 - 1.0
                row_d["net_ret_vel_50"] = (1.0 + gv) * 0.9950 - 1.0
                row_d["net_ret_vel_80"] = (1.0 + gv) * 0.9920 - 1.0
                row_d["net_ret_flat_30"] = (1.0 + gf) * 0.9970 - 1.0
                row_d["net_ret_flat_50"] = (1.0 + gf) * 0.9950 - 1.0
                row_d["net_ret_flat_80"] = (1.0 + gf) * 0.9920 - 1.0
            else:
                for k_n in ("net_ret_vel_30", "net_ret_vel_50", "net_ret_vel_80", "net_ret_flat_30", "net_ret_flat_50", "net_ret_flat_80"):
                    row_d[k_n] = np.nan
            cand_rows.append(row_d)

    cand_df = pd.DataFrame(cand_rows)
    filled_df = cand_df[cand_df["status"].isin(("filled_0925", "filled_intraday"))].copy()

    # Chronological single-slot selection:
    # For rank1_only, order by buy_date; for first_touch_prio, order by (buy_date, buy_hhmm, rank_in_day)
    taken = []
    n_0925_unlocked = 0
    if not filled_df.empty:
        srt_f = filled_df.sort_values(["buy_date", "buy_hhmm", "rank_in_day", "code"], ascending=[True, True, True, True])
        cur_ed, cur_eh = "", 0
        for bd, grp in srt_f.groupby("buy_date", sort=True):
            for r in grp.itertuples(index=False):
                if not cur_ed or bd > cur_ed:
                    can_enter = True
                elif bd == cur_ed:
                    # 09:25 exit frees cash for >=09:35 intraday conditional buy (if unlocked enabled)
                    if allow_0925_unlock and cur_eh == 925 and int(r.buy_hhmm) > 925:
                        can_enter = True
                        n_0925_unlocked += 1
                    elif is_2to3 and cur_eh > 925 and int(r.buy_hhmm) > cur_eh:
                        can_enter = True
                    else:
                        can_enter = False
                else:
                    can_enter = False
                if can_enter:
                    taken.append(r._asdict())
                    cur_ed = str(r.exit_date)
                    # Note: for 20cm B3_gap_tp, physical exit is 09:25; for 2to3, exact exit_hhmm
                    cur_eh = int(r.exit_hhmm)
                    break

    slot_df = pd.DataFrame(taken)

    # Exact daily MTM across cal_dts
    b_win = bench_df[bench_df["trade_date"].isin(set(cal_dts))].sort_values("trade_date").reset_index(drop=True)
    cal_use = b_win["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_use)}
    csi_arr = b_win["csi300_daily_ret"].to_numpy(float)
    ew_arr = b_win["alla_ew_daily_ret"].to_numpy(float)

    dr_v30, diff_v30 = cel.build_exact_daily_mtm(slot_df, cal_use, dmap, "net_ret_vel_30", "eff_buy_vel")
    dr_v50, diff_v50 = cel.build_exact_daily_mtm(slot_df, cal_use, dmap, "net_ret_vel_50", "eff_buy_vel")
    dr_v80, diff_v80 = cel.build_exact_daily_mtm(slot_df, cal_use, dmap, "net_ret_vel_80", "eff_buy_vel")
    dr_f30, diff_f30 = cel.build_exact_daily_mtm(slot_df, cal_use, dmap, "net_ret_flat_30", "eff_buy_flat")
    assert max(diff_v30, diff_v50, diff_v80, diff_f30) < 1e-6, (vid, diff_v30, diff_v50, diff_v80, diff_f30)

    # Windows
    min_dt = cal_use[0]
    max_dt = cal_use[-1]
    win_specs = [("PRIMARY", min_dt, max_dt)]
    if min_dt <= "2021-11-16":
        win_specs.append(("FULL_5Y", "2021-11-16", max_dt))
    if min_dt <= "2023-01-03":
        win_specs.append(("WF", "2023-01-03", max_dt))
        win_specs.append(("IS_TRUNC", min_dt, "2024-12-31"))
        if min_dt <= "2021-11-16":
            win_specs.append(("IS_5Y_TRUNC", "2021-11-16", "2024-12-31"))
    win_specs.extend([
        ("Y2025_2026", "2025-01-01", max_dt),
        ("Y2026", "2026-01-01", max_dt),
        ("Y2026H2", "2026-07-01", max_dt),
    ])

    win_res = {}
    for wname, s, e in win_specs:
        win_res[wname] = {
            "vel_30": cel.calc_window_metrics(slot_df, dr_v30, cal_use, dt_idx, csi_arr, ew_arr, s, e, "net_ret_vel_30"),
            "vel_50": cel.calc_window_metrics(slot_df, dr_v50, cal_use, dt_idx, csi_arr, ew_arr, s, e, "net_ret_vel_50"),
            "vel_80": cel.calc_window_metrics(slot_df, dr_v80, cal_use, dt_idx, csi_arr, ew_arr, s, e, "net_ret_vel_80"),
            "flat_30": cel.calc_window_metrics(slot_df, dr_f30, cal_use, dt_idx, csi_arr, ew_arr, s, e, "net_ret_flat_30"),
        }

    # Execution funnel stats (for primary window)
    n_pass_tot = len(pool_df)
    n_dates_pass = pool_df["buy_date"].nunique()
    # In rank1_only, denominator is dates_pass; in first_touch_prio, check both
    st_cnt = cand_df["status"].value_counts().to_dict()
    n_fill = int(st_cnt.get("filled_0925", 0) + st_cnt.get("filled_intraday", 0))
    n_miss = int(st_cnt.get("missed_zt", 0))
    n_untrig = int(st_cnt.get("untriggered", 0))
    n_trig_att = n_fill + n_miss
    miss_rate_trig = round(n_miss / max(1, n_trig_att) * 100.0, 2)
    miss_rate_all = round(n_miss / max(1, len(cand_df)) * 100.0, 2)
    fill_rate_day = round(cand_df[cand_df["status"].isin(("filled_0925", "filled_intraday"))]["buy_date"].nunique() / max(1, n_dates_pass) * 100.0, 2)

    wf_key = "WF" if "WF" in win_res else "PRIMARY"
    p_wf30 = win_res[wf_key]["vel_30"]
    p_pr30 = win_res["PRIMARY"]["vel_30"]
    p_5y30 = win_res.get("FULL_5Y", win_res["PRIMARY"])["vel_30"]
    p_is30 = win_res.get("IS_TRUNC", {}).get("vel_30", {})
    p_2526 = win_res["Y2025_2026"]["vel_30"]
    p_26 = win_res["Y2026"]["vel_30"]
    p_h2 = win_res["Y2026H2"]["vel_30"]

    summary_row = {
        "target": target,
        "multi_mode": multi_mode,
        "variant": vid,
        "family": fam,
        "kind": kind,
        "cancel_hhmm": ch,
        "n_pass_rows": int(n_pass_tot),
        "n_pass_days": int(n_dates_pass),
        "day_fill_rate_pct": fill_rate_day,
        "cand_filled": n_fill,
        "cand_missed_zt": n_miss,
        "cand_untriggered": n_untrig,
        "zt_miss_rate_vs_trig_pct": miss_rate_trig,
        "zt_miss_rate_vs_all_pct": miss_rate_all,
        "n_0925_unlocked": int(n_0925_unlocked),
        "mtm_diff_max": float(max(diff_v30, diff_v50, diff_v80, diff_f30)),
        # Primary / 5Y
        "n_prim": p_pr30["n"], "wr_prim": p_pr30["wr_pct"], "plr_prim": p_pr30["plr"],
        "mean_prim": p_pr30["mean_pct"], "nav_prim": p_pr30["nav"], "ex5_prim": p_pr30["ex5_nav"],
        "mdd_prim": p_pr30["mdd_pct"], "sharpe_prim": p_pr30["sharpe"], "calmar_prim": p_pr30["calmar"],
        "bl_m7_prim": p_pr30["big_loss_m7_pct"], "pct_0935_prim": p_pr30["pct_0935plus"],
        "avg_slip_bps_prim": p_pr30["avg_slip_bps"],
        # 5Y
        "n_5y": p_5y30["n"], "nav_5y": p_5y30["nav"], "ex5_5y": p_5y30["ex5_nav"],
        "mdd_5y": p_5y30["mdd_pct"], "sharpe_5y": p_5y30["sharpe"],
        # WF (2023-2026)
        "n_wf": p_wf30["n"], "wr_wf": p_wf30["wr_pct"], "plr_wf": p_wf30["plr"],
        "mean_wf": p_wf30["mean_pct"], "nav_wf": p_wf30["nav"], "ex5_wf": p_wf30["ex5_nav"],
        "mdd_wf": p_wf30["mdd_pct"], "sharpe_wf": p_wf30["sharpe"], "calmar_wf": p_wf30["calmar"],
        "bl_m7_wf": p_wf30["big_loss_m7_pct"],
        # IS_TRUNC (<=2024-12-31)
        "n_is": p_is30.get("n", 0), "nav_is": p_is30.get("nav", 1.0),
        "mdd_is": p_is30.get("mdd_pct", 0.0), "sharpe_is": p_is30.get("sharpe", 0.0),
        # 2025-2026 / 2026 / 2026H2
        "n_2526": p_2526["n"], "wr_2526": p_2526["wr_pct"], "nav_2526": p_2526["nav"],
        "ex5_2526": p_2526["ex5_nav"], "mdd_2526": p_2526["mdd_pct"], "sharpe_2526": p_2526["sharpe"],
        "n_26": p_26["n"], "wr_26": p_26["wr_pct"], "nav_26": p_26["nav"], "sharpe_26": p_26["sharpe"],
        "n_26h2": p_h2["n"], "wr_26h2": p_h2["wr_pct"], "nav_26h2": p_h2["nav"], "mdd_26h2": p_h2["mdd_pct"],
        # Friction stresses on WF
        "nav_wf_vel50": win_res[wf_key]["vel_50"]["nav"],
        "sharpe_wf_vel50": win_res[wf_key]["vel_50"]["sharpe"],
        "nav_wf_vel80": win_res[wf_key]["vel_80"]["nav"],
        "sharpe_wf_vel80": win_res[wf_key]["vel_80"]["sharpe"],
        "nav_wf_flat30": win_res[wf_key]["flat_30"]["nav"],
        "sharpe_wf_flat30": win_res[wf_key]["flat_30"]["sharpe"],
    }

    return summary_row, slot_df, dr_v30, cand_df, win_res


def run_local_covered_control(cache: dict) -> dict:
    """100% locally-covered subset control strictly on raw `all_strategies_5m_complete_pit.parquet` rows."""
    df20 = cache["df20"]
    bars_loc = cache["bars_5m_local"]
    dmap = cache["dmap"]
    bench_df = cache["bench_df"]
    cal_full = cache["cal_full"]

    sub_s82 = df20[df20["can_buy_hygiene"] & (df20["sc_v20"] >= 82.0) & df20["has_local_5m"]].copy()
    sub_all = df20[df20["can_buy_hygiene"] & df20["has_local_5m"]].copy()
    specs = [
        ("B0_auc_0925", "0_BASELINE", "auc_0925", 925, None),
        ("op_p10_c1030", "1_OPEN_PCT", "open_mult", 1030, 1.010),
        ("op_p20_c1030", "1_OPEN_PCT", "open_mult", 1030, 1.020),
        ("op_p30_c1130", "1_OPEN_PCT", "open_mult", 1130, 1.030),
        ("fh_0_c1130", "2_FANHONG", "prev_close_mult", 1130, {"pc_mult": 1.0, "allow_0925": False}),
        ("brk5m_p01_c1130", "3_BRK_5M_10M", "brk_5m_hi", 1130, {"pad": 0.01}),
    ]
    out = {}
    for lbl, sub in [("20cm_S82_local90", sub_s82), ("20cm_All_local188", sub_all)]:
        rows = []
        for sp in specs:
            sr, _, _, _, _ = eval_target_spec("20cm_S82", sub, "sc_v20", bars_loc, dmap, bench_df, cal_full, sp, "rank1_only")
            rows.append({
                "variant": sp[0], "n": sr["n_prim"], "wr_pct": sr["wr_prim"], "plr": sr["plr_prim"],
                "mean_pct": sr["mean_prim"], "nav": sr["nav_prim"], "mdd_pct": sr["mdd_prim"],
                "sharpe": sr["sharpe_prim"], "zt_miss_pct": sr["zt_miss_rate_vs_trig_pct"],
            })
        out[lbl] = {"n_local_rows": int(len(sub)), "results": rows}
    return out


def main():
    t0 = time.time()
    print("[Step 2] Loading cache from Step 1 ...")
    with open(PATH_CACHE_IN, "rb") as f:
        cache = pickle.load(f)

    p23_90 = cache["p23_90"].copy()
    p23_90["gross_ret"] = p23_90["gross_ret"].astype(float)
    df20 = cache["df20"].copy()
    bars_full = cache["bars_5m_full"]
    dmap = cache["dmap"]
    bench_df = cache["bench_df"]
    cal_full = cache["cal_full"]
    cal_5y = cache["cal_5y"]
    cal_wf = cache["cal_wf"]

    # Patch 20cm exit_hhmm for B3_gap_tp physically to 925 for collision test (while keeping baseline parity)
    df20_phys = df20.copy()
    df20_phys["exit_hhmm"] = np.where(df20_phys["exit_reason"].astype(str).str.contains("gap_tp"), 925, df20_phys["exit_hhmm"])

    # 1. Local 5m covered control
    print("[Step 2] Running 100%-local-5m covered subset control ...")
    local_ctrl = run_local_covered_control(cache)
    for k, v in local_ctrl.items():
        print(f"  {k} (n={v['n_local_rows']}): " + " | ".join(f"{r['variant']}:n={r['n']}/nav={r['nav']}x/sh={r['sharpe']}" for r in v["results"]))

    # 2. Target configs
    targets = [
        ("2to3_V21", p23_90, "v20_score", cal_5y),
        ("20cm_S82", df20_phys[df20_phys["can_buy_hygiene"] & (df20_phys["sc_v20"] >= 82.0)].copy(), "sc_v20", cal_full),
        ("20cm_Stack", df20_phys[df20_phys["can_buy_hygiene"] & (df20_phys["buy_date"] >= "2023-01-03") & (df20_phys["sc_stack"] >= 80.0)].copy(), "sc_stack", cal_wf),
        ("20cm_Blend", df20_phys[df20_phys["can_buy_hygiene"] & (df20_phys["buy_date"] >= "2023-01-03") & (df20_phys["sc_blend"] >= 80.0)].copy(), "sc_blend", cal_wf),
    ]

    all_grid_rows = []
    store = {"local_ctrl": local_ctrl, "targets": {}}

    for tgt, pool_t, sc_col, cal_t in targets:
        t_tgt = time.time()
        specs = build_specs_for_target(tgt)
        print(f"\n[Step 2] Running {tgt}: pool={len(pool_t)} rows, {len(specs)} specs x 2 multi-modes ...")
        tgt_res = {"variants": {}, "dr_wf": {}, "base_key": "B0_auc_0925__rank1_only"}
        dr_wf_map = {}

        # Align WF index slice on cal_t
        wf_dts = [d for d in cal_t if d >= "2023-01-03"]
        wf_slice = [i for i, d in enumerate(cal_t) if d >= "2023-01-03"]

        for multi_mode in ("rank1_only", "first_touch_prio"):
            for sp in specs:
                vid = sp[0]
                if vid == "B0_auc_0925" and multi_mode == "first_touch_prio":
                    continue  # baseline 09:25 is identical rank1
                key = f"{vid}__{multi_mode}"
                sr, sl, dr_t, cand_df, win_res = eval_target_spec(
                    tgt, pool_t, sc_col, bars_full, dmap, bench_df, cal_t, sp, multi_mode
                )
                dr_wf = dr_t[wf_slice]
                dr_wf_map[key] = dr_wf
                sr["variant_key"] = key
                all_grid_rows.append(sr)
                tgt_res["variants"][key] = {
                    "row": sr,
                    "slot_df": sl,
                    "cand_df": cand_df[["buy_date", "code", "status", "net_ret_vel_30", "is_zt_sealed_bar"]].copy(),
                    "win_res": win_res,
                    "dr_full": dr_t,
                    "dr_wf": dr_wf,
                }

        # Paired-t vs B0_auc_0925__rank1_only (on WF) + strict-seal-miss check on top variants
        dr_base = dr_wf_map["B0_auc_0925__rank1_only"]
        for r in all_grid_rows:
            if r["target"] != tgt:
                continue
            pt = cel.compute_paired_t(dr_wf_map[r["variant_key"]], dr_base)
            r["t_wf_vs_0925"] = pt["t_daily_vs_0925"]
            r["p_wf_vs_0925"] = pt["p_daily_vs_0925_2s"]
            r["t_act_vs_0925"] = pt["t_active_vs_0925"]

        # CSCV PBO (Global per target & by trigger family, across rank1_only & first_touch_prio)
        k_all = [k for k in dr_wf_map if not k.startswith("B0_")]
        mat_all = np.column_stack([dr_wf_map[k] for k in k_all])
        cscv_s10 = cel.compute_cscv_pbo(mat_all, k_all, n_blocks=10)
        cscv_s8 = cel.compute_cscv_pbo(mat_all, k_all, n_blocks=8)
        cscv_fam = {}
        df_t = pd.DataFrame([r for r in all_grid_rows if r["target"] == tgt and r["variant"] != "B0_auc_0925"])
        for fam_nm, grp in df_t.groupby("family"):
            fk = grp["variant_key"].tolist()
            if len(fk) >= 3:
                cscv_fam[fam_nm] = cel.compute_cscv_pbo(np.column_stack([dr_wf_map[k] for k in fk]), fk, n_blocks=10)

        tgt_res["cscv_global_s10"] = cscv_s10
        tgt_res["cscv_global_s8"] = cscv_s8
        tgt_res["cscv_by_family"] = cscv_fam
        tgt_res["cal_t"] = cal_t
        tgt_res["wf_dts"] = wf_dts
        store["targets"][tgt] = tgt_res

        # Print top 3 by Sharpe WF & baseline
        b_row = [r for r in all_grid_rows if r["target"] == tgt and r["variant"] == "B0_auc_0925"][0]
        print(f"  [BASE {tgt}] n_wf={b_row['n_wf']}, wr={b_row['wr_wf']}%, nav_wf={b_row['nav_wf']}x, mdd={b_row['mdd_wf']}%, sh={b_row['sharpe_wf']}, nav_2526={b_row['nav_2526']}x")
        top3 = df_t.sort_values(["sharpe_wf", "nav_wf"], ascending=False).head(4)
        for _, tr in top3.iterrows():
            print(f"    TOP {tr['variant_key']:38s} | n={tr['n_wf']:3d} miss={tr['zt_miss_rate_vs_trig_pct']:4.1f}% wr={tr['wr_wf']:5.1f}% nav={tr['nav_wf']:6.2f}x mdd={tr['mdd_wf']:5.2f}% sh={tr['sharpe_wf']:5.3f} (t={tr['t_wf_vs_0925']:+.2f}) | 2526={tr['nav_2526']:5.2f}x")
        print(f"  CSCV Global S10 PBO={cscv_s10['pbo_pct']}% | Elapsed={time.time()-t_tgt:.1f}s | RSS={rss_mb()}MB")

    df_grid = pd.DataFrame(all_grid_rows)
    df_grid.to_csv(PATH_GRID_CSV, index=False)
    with open(PATH_STEP2_OUT, "wb") as f:
        pickle.dump(store, f)
    print(f"\n[Step 2 DONE in {time.time()-t0:.1f}s | Grid rows={len(df_grid)} | Peak RSS={rss_mb()}MB]")


if __name__ == "__main__":
    main()
