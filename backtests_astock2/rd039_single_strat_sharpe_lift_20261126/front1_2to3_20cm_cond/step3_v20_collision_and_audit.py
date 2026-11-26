#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD039-A Front 1 Step 3:
  1. Mechanism Decomposition (slippage/chase cost vs untriggered filter vs ZT miss vs strict-seal stress).
  2. Module 3: Physical `09:25 sell-old + >=09:35 buy-new` collision analysis (Standalone + Full V20.0 6-strat portfolio).
  3. Module 4: 2024-12-31 physical truncation IS->OOS blind test, 1000x Perm, Parameter Plateau, CSCV PBO.
  4. Generate final `rd039_f1_audit.json` (Peak RSS < 2.5 GB, zero yfinance, zero cap10m).
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import math
import pickle
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

pa.set_cpu_count(2)
pa.set_io_thread_count(2)
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028 = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
RD036_P1 = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part1_20cm"
OUT_DIR = f"{SIM}/backtests_astock2/rd039_single_strat_sharpe_lift_20261126/front1_2to3_20cm_cond"

for p in (OUT_DIR, WAVE1, RD028, PARTC_V20, RD036_P1):
    if p not in sys.path:
        sys.path.insert(0, p)

import cond_exec_lib as cel
import step2_run_cond_grid as s2
import _wf_v20_patch as wfp
import step4_mod_rules_and_sim as m1
import tier_priority_engine as tpe
import rd036_lib as lib20

TRD_DAYS_YEAR = 242.0


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def decompose_mechanism(
    tgt: str,
    pool_t: pd.DataFrame,
    sc_col: str,
    base_slot: pd.DataFrame,
    var_slot: pd.DataFrame,
    var_cand: pd.DataFrame,
    bars_full: dict,
    dmap: dict,
    bench_df: pd.DataFrame,
    cal_t: list[str],
    spec: tuple,
    multi_mode: str,
    wf_start: str = "2023-01-03",
) -> dict:
    """Decompose why conditional order differs from 09:25 baseline on WF (and FULL)."""
    base_wf = base_slot[base_slot["buy_date"] >= wf_start].copy()
    var_wf = var_slot[var_slot["buy_date"] >= wf_start].copy()
    cand_wf = var_cand[var_cand["buy_date"] >= wf_start].copy()

    b_keys = {(r.buy_date, r.code): r for r in base_wf.itertuples(index=False)}
    v_keys = {(r.buy_date, r.code): r for r in var_wf.itertuples(index=False)}

    # Matched same trades (entered in BOTH baseline and conditional)
    common = sorted(set(b_keys.keys()) & set(v_keys.keys()))
    chase_bps_list, slip_bps_list, tot_drag_bps_list = [], [], []
    common_b_rets, common_v_rets = [], []
    for k in common:
        rb, rv = b_keys[k], v_keys[k]
        chase_bps = (rv.eff_buy_flat / rb.open_d - 1.0) * 10000.0
        slip_bps = (rv.eff_buy_vel / rv.eff_buy_flat - 1.0) * 10000.0
        drag_bps = (rv.eff_buy_vel / rb.open_d - 1.0) * 10000.0
        chase_bps_list.append(chase_bps)
        slip_bps_list.append(slip_bps)
        tot_drag_bps_list.append(drag_bps)
        common_b_rets.append(float(rb.net_ret_vel_30))
        common_v_rets.append(float(rv.net_ret_vel_30))

    # Dropped baseline trades (in base_wf, NOT in var_wf)
    dropped = [b_keys[k] for k in sorted(set(b_keys.keys()) - set(v_keys.keys()))]
    cand_status_map = {(r.buy_date, r.code): r.status for r in cand_wf.itertuples(index=False)}
    drop_untrig, drop_miss_zt, drop_slot_shift = [], [], []
    for rb in dropped:
        st = cand_status_map.get((rb.buy_date, rb.code), "slot_or_rank1_skip")
        ret_v = float(rb.net_ret_vel_30)
        if st == "untriggered":
            drop_untrig.append(ret_v)
        elif st == "missed_zt":
            drop_miss_zt.append(ret_v)
        else:
            drop_slot_shift.append(ret_v)

    # Added trades (in var_wf, NOT in base_wf)
    added = [v_keys[k] for k in sorted(set(v_keys.keys()) - set(b_keys.keys()))]
    add_rets = [float(rv.net_ret_vel_30) for rv in added]

    def _sum_rets(arr):
        if not arr:
            return {"n": 0, "wr_pct": 0.0, "mean_pct": 0.0, "prod_nav": 1.0}
        a = np.asarray(arr, float)
        return {
            "n": int(len(a)),
            "wr_pct": round(float((a > 0).mean() * 100.0), 2),
            "mean_pct": round(float(a.mean() * 100.0), 2),
            "prod_nav": round(float(np.prod(1.0 + a)), 4),
        }

    # Strict ZT-seal-bar miss sensitivity
    sr_strict, sl_strict, _, _, _ = s2.eval_target_spec(
        tgt, pool_t, sc_col, bars_full, dmap, bench_df, cal_t, spec, multi_mode, strict_seal_miss=True
    )

    # Unlock 09:25 disabled sensitivity
    sr_nounlock, _, _, _, _ = s2.eval_target_spec(
        tgt, pool_t, sc_col, bars_full, dmap, bench_df, cal_t, spec, multi_mode, allow_0925_unlock=False
    )

    return {
        "common_trades": {
            "n": len(common),
            "avg_chase_open_to_trig_bps": round(float(np.mean(chase_bps_list)), 1) if chase_bps_list else 0.0,
            "avg_vel_slip_bps": round(float(np.mean(slip_bps_list)), 1) if slip_bps_list else 0.0,
            "avg_total_entry_drag_bps": round(float(np.mean(tot_drag_bps_list)), 1) if tot_drag_bps_list else 0.0,
            "base_prod_nav": round(float(np.prod(1.0 + np.asarray(common_b_rets))), 4) if common_b_rets else 1.0,
            "cond_prod_nav": round(float(np.prod(1.0 + np.asarray(common_v_rets))), 4) if common_v_rets else 1.0,
        },
        "dropped_from_base_wf": {
            "untriggered": _sum_rets(drop_untrig),
            "missed_zt": _sum_rets(drop_miss_zt),
            "slot_shift_or_other": _sum_rets(drop_slot_shift),
        },
        "added_in_cond_wf": _sum_rets(add_rets),
        "strict_seal_zt_miss_stress": {
            "n_wf": sr_strict["n_wf"],
            "zt_miss_rate_pct": sr_strict["zt_miss_rate_vs_trig_pct"],
            "nav_wf": sr_strict["nav_wf"],
            "sharpe_wf": sr_strict["sharpe_wf"],
            "mdd_wf": sr_strict["mdd_wf"],
        },
        "disable_0925_unlock_control": {
            "n_wf": sr_nounlock["n_wf"],
            "nav_wf": sr_nounlock["nav_wf"],
            "sharpe_wf": sr_nounlock["sharpe_wf"],
        },
    }


def eval_v20_portfolio_collision(cache: dict, store: dict) -> dict:
    """
    Module 3: Physical `09:25 sell-old + >=09:35 buy-new` collision test inside full V20.0 6-strat portfolio.
    Uses lean V20.0 context reproducing exact 278t / 69,134,091.51x (5Y) & 207t / 611,729.55x (WF).
    """
    v20_ctx = wfp.load_v20_reference_context(WAVE1)
    v20_led = v20_ctx["v20_ledger"]
    bench = v20_ctx["bench"]
    raw_idx = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300 = {k: float(v) for k, v in raw_idx["sh000300"].items()}
    all_sh_dts = sorted(sh300.keys())
    cal_5y = [d for d in all_sh_dts if "2021-11-16" <= d <= "2026-11-16"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}

    # Load all 6 oldhot pools & precompute needed daily bars cleanly
    pools_oh = {}
    need_rows = []
    for st in m1.STRAT_ORDER:
        df = pd.read_parquet(f"{RD028}/pool_{st}_oldhot.parquet")
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["buy_date"] = df["buy_date"].astype(str).str[:10]
        df["exit_date"] = df["exit_date"].astype(str).str[:10]
        if st == "20cm":
            df["exit_hhmm"] = np.where(df["exit_reason"].astype(str).str.contains("open|gap|tp"), 1030, 1500)
            df["buy_price_val"] = df["buy_px"].astype(float)
            df["is_adj_px"] = True
        else:
            df["buy_price_val"] = df["buy_price"].astype(float)
            df["is_adj_px"] = False
        if st == "high":
            df["v51_cb_loss"] = (df["net_ret"].to_numpy(float) < -0.02) & (~df["dt_deferred"].to_numpy(bool))
        pools_oh[st] = df
        need_rows.append(df[["code", "buy_date", "exit_date"]])

    bar_lu = lib20._build_needed_bar_lu(pd.concat(need_rows, ignore_index=True), cal_5y)
    for st in m1.STRAT_ORDER:
        pools_oh[st]["mtm_5y"] = m1.precompute_mtm_segments(pools_oh[st], cal_5y, idx_5y, bar_lu, is_20cm_adj=(st == "20cm"))
    del bar_lu
    gc.collect()

    # Lean untriggered pool (3to4 / high / 1to2) from rd034
    ut_raw = pd.read_parquet(f"{SIM}/backtests_astock2/rd034_ashare_3layer_cycles_6strat_20261125/rd034_untrig_with_3layer_cycles.parquet")
    ut_raw["buy_date"] = ut_raw["buy_date"].astype(str).str[:10]
    ut_raw["code"] = ut_raw["code"].astype(str).str.zfill(6)
    ut_raw = ut_raw[ut_raw["buy_date"].between("2021-11-16", "2026-11-16")].copy()

    # Build baseline 6-strat pool
    base_parts = {}
    trig_dts = {}
    for st in m1.STRAT_ORDER:
        thr20 = 76.0 if st == "20cm" else 82.0
        _, sl = m1.sim_standalone(st, pools_oh[st], np.zeros(len(pools_oh[st])), high_cb_mode="v51_exact", cm20_thr=thr20)
        ch = sl[sl["buy_date"].between("2021-11-16", "2026-11-16")].copy()
        ch["strategy"] = st
        ch["score"] = [round(float(x), 1) for x in ch["v20_score"]] if st == "1to2" else ch["v20_score"].astype(float)
        ch["tier"] = [tpe.assign_physical_tier(st, sc) for sc in ch["score"]]
        ch["is_untrig"] = False
        trig_dts[st] = set(ch["buy_date"])
        base_parts[st] = ch[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig", "mtm_5y"]].copy()

    def _make_ut(tr_map):
        parts = []
        for stu in ("3to4", "high", "1to2"):
            su = ut_raw[(ut_raw["strategy"] == stu) & (~ut_raw["buy_date"].isin(tr_map[stu]))].copy()
            thu = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[stu]
            su = su[su["score"] >= thu].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
            if not su.empty:
                su["tier"] = [tpe.assign_physical_tier(stu, sc) for sc in su["score"]]
                parts.append(su)
        utf = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        utf["is_untrig"] = True
        utf["net_ret"] = 0.0
        utf["buy_price_val"] = np.nan
        utf["is_adj_px"] = False
        return utf[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig"]]

    # Verify V20 parity (278t / 69,134,091.51x)
    p6_base = pd.concat(list(base_parts.values()), ignore_index=True)
    ut_base = _make_ut(trig_dts)
    tr_base, _ = tpe.run_single_slot(p6_base.drop(columns=["mtm_5y"]), lambda d: d["tier"].map(m1.S2C_MAP).fillna(999).to_numpy(), untrig_df=ut_base, timing_mode="s_tier_reserve_only")
    assert len(tr_base) == 278 and abs(float(np.prod(1.0 + tr_base["net_ret"])) - 69134091.5067) < 2.0

    # Diagnose 09:25 exit collision days in V20 baseline
    ex_925_dts = set(tr_base.loc[tr_base["exit_hhmm"] == 925, "exit_date"])
    p23_90_dts = set(base_parts["2to3"]["buy_date"])
    p20_82_dts = set(pools_oh["20cm"].loc[pools_oh["20cm"]["v20_score"] >= 82.0, "buy_date"])
    col_23 = sorted(ex_925_dts & p23_90_dts)
    col_20 = sorted(ex_925_dts & p20_82_dts)

    # Also build exact 0.20% converted segments for any conditional slot_df (to match V20 20bps parity, AND compare 30bps!)
    dmap = cache["dmap"]
    def _convert_cond_slot_for_v20(slot_df: pd.DataFrame, st_name: str, is_adj: bool) -> pd.DataFrame:
        sub = slot_df[slot_df["buy_date"].between("2021-11-16", "2026-11-16")].copy()
        if sub.empty:
            return pd.DataFrame(columns=base_parts[st_name].columns)
        # Convert net_ret_vel_30 -> 20bps equivalent for V20 20bps parity
        nr20 = (1.0 + sub["net_ret_vel_30"].to_numpy(float)) / 0.9970 * 0.9980 - 1.0
        sub["net_ret"] = nr20
        sub["strategy"] = st_name
        sub["tier"] = [tpe.assign_physical_tier(st_name, sc) for sc in sub["score"]]
        sub["is_untrig"] = False
        sub["is_adj_px"] = is_adj
        sub["buy_price_val"] = sub["eff_buy_vel"].astype(float)
        # Build exact mtm_5y aligned to cal_5y
        mtm_list = []
        for r in sub.itertuples(index=False):
            bi = idx_5y.get(r.buy_date)
            ei = idx_5y.get(r.exit_date)
            if bi is None or ei is None or ei <= bi:
                mtm_list.append(())
                continue
            bb = dmap.get((r.code, r.buy_date))
            adjf_b = bb["adjf"] if bb else 1.0
            b_adj = float(r.eff_buy_vel) * adjf_b
            prev_v, last_c = b_adj, b_adj
            segs = []
            for t in range(bi, ei):
                bt = dmap.get((r.code, cal_5y[t]))
                cur_c = bt["adj_close"] if (bt and bt["adj_close"] > 0) else last_c
                segs.append((t, cur_c / prev_v))
                prev_v, last_c = cur_c, cur_c
            segs.append((ei, (b_adj * (1.0 + float(r.net_ret))) / prev_v))
            mtm_list.append(tuple(segs))
        sub["mtm_5y"] = mtm_list
        return sub[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig", "mtm_5y"]].copy()

    def _run_v20_test(label: str, rep_23: pd.DataFrame | None, rep_20: pd.DataFrame | None, timing_mode: str = "s_tier_reserve_only") -> dict:
        parts = dict(base_parts)
        tm = dict(trig_dts)
        if rep_23 is not None:
            parts["2to3"] = rep_23
            tm["2to3"] = set(rep_23["buy_date"])
        if rep_20 is not None:
            parts["20cm"] = rep_20
            tm["20cm"] = set(rep_20["buy_date"])
        p6 = pd.concat(list(parts.values()), ignore_index=True)
        mm = {(r.strategy, r.buy_date, r.code): r.mtm_5y for r in p6.itertuples(index=False)}
        ut = _make_ut(tm)
        tr, _ = tpe.run_single_slot(p6.drop(columns=["mtm_5y"]), lambda d: d["tier"].map(m1.S2C_MAP).fillna(999).to_numpy(), untrig_df=ut, timing_mode=timing_mode)
        tr["mtm_5y"] = [mm[(r.strategy, r.buy_date, r.code)] for r in tr.itertuples(index=False)]
        dr, mdiff = m1.daily_mtm_from_segs(tr, len(cal_5y), "mtm_5y")
        m_5y = tpe.calc_window_metrics(tr, dr, cal_5y, idx_5y, sh300, all_sh_dts, "2021-11-16", "2026-11-16")
        m_wf = tpe.calc_window_metrics(tr, dr, cal_5y, idx_5y, sh300, all_sh_dts, "2023-01-03", "2026-11-16")
        m_2526 = tpe.calc_window_metrics(tr, dr, cal_5y, idx_5y, sh300, all_sh_dts, "2025-01-01", "2026-11-16")
        n_0925_same_day = 0
        for i in range(1, len(tr)):
            if tr.iloc[i]["buy_date"] == tr.iloc[i - 1]["exit_date"] and int(tr.iloc[i - 1]["exit_hhmm"]) == 925 and int(tr.iloc[i]["buy_hhmm"]) >= 935:
                if tr.iloc[i]["strategy"] in ("2to3", "20cm"):
                    n_0925_same_day += 1
        return {
            "label": label,
            "timing_mode": timing_mode,
            "n_5y": m_5y["n"], "nav_5y": m_5y["nav"], "mdd_5y": m_5y["daily_mdd_pct"], "sharpe_5y": m_5y["daily_sharpe"],
            "n_wf": m_wf["n"], "nav_wf": m_wf["nav"], "mdd_wf": m_wf["daily_mdd_pct"], "sharpe_wf": m_wf["daily_sharpe"],
            "nav_2526": m_2526["nav"],
            "n_2to3_5y": int((tr["strategy"] == "2to3").sum()),
            "n_20cm_5y": int((tr["strategy"] == "20cm").sum()),
            "n_0925_unlocked_in_v20": int(n_0925_same_day),
            "mtm_diff": round(float(mdiff), 8),
        }

    tests = [
        _run_v20_test("V20_Baseline_0925", None, None, "s_tier_reserve_only"),
        _run_v20_test("V20_Baseline_0925_conf0925", None, None, "confirmed_0925_first"),
    ]

    # Test top 2to3 conditional orders inside V20
    for k23 in ("op_p05_c1130__first_touch_prio", "op_p05_c1130__rank1_only", "hyb_lowOp20_hi0925_c1030__rank1_only", "fh_0_allow0925_c1000__rank1_only"):
        if k23 in store["targets"]["2to3_V21"]["variants"]:
            sl23 = store["targets"]["2to3_V21"]["variants"][k23]["slot_df"]
            rep23 = _convert_cond_slot_for_v20(sl23, "2to3", False)
            tests.append(_run_v20_test(f"2to3::{k23}__s_tier_res", rep23, None, "s_tier_reserve_only"))
            tests.append(_run_v20_test(f"2to3::{k23}__conf0925_first", rep23, None, "confirmed_0925_first"))

    # Test top 20cm S82 conditional orders inside V20
    for k20 in ("op_p10_c1130__rank1_only", "op_p10_c1430__rank1_only", "op_p05_c945__rank1_only"):
        if k20 in store["targets"]["20cm_S82"]["variants"]:
            sl20 = store["targets"]["20cm_S82"]["variants"][k20]["slot_df"]
            rep20 = _convert_cond_slot_for_v20(sl20, "20cm", True)
            tests.append(_run_v20_test(f"20cm_S82::{k20}__s_tier_res", None, rep20, "s_tier_reserve_only"))

    return {
        "v20_baseline_0925_exits_total": int(len(ex_925_dts)),
        "collision_dates_v20_0925exit_vs_2to3": col_23,
        "collision_dates_v20_0925exit_vs_20cm_s82": col_20,
        "v20_portfolio_experiments_20bps": tests,
    }


def main():
    t0 = time.time()
    print("[Step 3] Loading Step 1 & Step 2 caches ...")
    with open(f"{OUT_DIR}/_cache_rd039_f1_inputs.pkl", "rb") as f:
        cache = pickle.load(f)
    with open(f"{OUT_DIR}/_cache_step2_results.pkl", "rb") as f:
        store = pickle.load(f)
    df_grid = pd.read_csv(f"{OUT_DIR}/rd039_f1_cond_grid.csv")

    dmap = cache["dmap"]
    bars_full = cache["bars_5m_full"]
    bench_df = cache["bench_df"]
    p23_90 = cache["p23_90"].copy()
    p23_90["gross_ret"] = p23_90["gross_ret"].astype(float)
    df20_phys = cache["df20"].copy()
    df20_phys["exit_hhmm"] = np.where(df20_phys["exit_reason"].astype(str).str.contains("gap_tp"), 925, df20_phys["exit_hhmm"])

    target_pools = {
        "2to3_V21": (p23_90, "v20_score", cache["cal_5y"]),
        "20cm_S82": (df20_phys[df20_phys["can_buy_hygiene"] & (df20_phys["sc_v20"] >= 82.0)].copy(), "sc_v20", cache["cal_full"]),
        "20cm_Stack": (df20_phys[df20_phys["can_buy_hygiene"] & (df20_phys["buy_date"] >= "2023-01-03") & (df20_phys["sc_stack"] >= 80.0)].copy(), "sc_stack", cache["cal_wf"]),
        "20cm_Blend": (df20_phys[df20_phys["can_buy_hygiene"] & (df20_phys["buy_date"] >= "2023-01-03") & (df20_phys["sc_blend"] >= 80.0)].copy(), "sc_blend", cache["cal_wf"]),
    }

    # 1. Mechanism decomposition, 1000x Perm, IS->OOS Blind Lock, Plateau per target
    per_target_audit = {}
    for tgt in ("2to3_V21", "20cm_S82", "20cm_Stack", "20cm_Blend"):
        print(f"[Step 3] Auditing {tgt} (decomp, 1000x perm, IS->OOS lock, plateau) ...")
        pool_t, sc_col, cal_t = target_pools[tgt]
        specs_map = {sp[0]: sp for sp in s2.build_specs_for_target(tgt)}
        t_data = store["targets"][tgt]
        dt_sub = df_grid[df_grid["target"] == tgt].copy()
        dt_cond = dt_sub[dt_sub["variant"] != "B0_auc_0925"].copy()

        base_key = "B0_auc_0925__rank1_only"
        base_slot = t_data["variants"][base_key]["slot_df"]
        base_cand = t_data["variants"][base_key]["cand_df"]

        # Select finalists: baseline + top 3 by sharpe_wf + best of each family
        fin_keys = [base_key]
        fin_keys.extend(dt_cond.sort_values("sharpe_wf", ascending=False)["variant_key"].head(3).tolist())
        for fam, grp in dt_cond.groupby("family"):
            fin_keys.append(grp.sort_values("sharpe_wf", ascending=False)["variant_key"].iloc[0])
        fin_keys = list(dict.fromkeys(fin_keys))

        finalists = {}
        wf_edt = cal_t[-1]
        for fk in fin_keys:
            vinfo = t_data["variants"][fk]
            vid, mm = fk.split("__")
            sp = specs_map[vid]
            pm_wf = cel.perm_test_1000(vinfo["slot_df"], base_cand, "2023-01-03", wf_edt, "net_ret_vel_30", n_perm=1000, seed=20261126)
            decomp = None
            if fk != base_key:
                decomp = decompose_mechanism(tgt, pool_t, sc_col, base_slot, vinfo["slot_df"], vinfo["cand_df"], bars_full, dmap, bench_df, cal_t, sp, mm)
            finalists[fk] = {
                "metrics_row": vinfo["row"],
                "windows": vinfo["win_res"],
                "perm_1000_wf": pm_wf,
                "mechanism_decomp": decomp,
            }

        # 2024-12-31 physical truncation IS->OOS blind lock (pick top conditional strictly on <=2024-12-31)
        is_best_sh = dt_cond.sort_values(["sharpe_is", "nav_is"], ascending=False).iloc[0]
        is_best_nav = dt_cond.sort_values(["nav_is", "sharpe_is"], ascending=False).iloc[0]
        base_row = dt_sub[dt_sub["variant"] == "B0_auc_0925"].iloc[0]

        # Open+X% x Cancel neighborhood plateau (rank1_only)
        plat = dt_cond[(dt_cond["family"] == "1_OPEN_PCT") & (dt_cond["multi_mode"] == "rank1_only")][
            ["variant", "cancel_hhmm", "n_wf", "wr_wf", "nav_wf", "mdd_wf", "sharpe_wf", "nav_2526", "t_wf_vs_0925"]
        ].to_dict("records")

        per_target_audit[tgt] = {
            "baseline_vs_all_cond_summary": {
                "n_cond_variants_tested": int(len(dt_cond)),
                "n_beat_base_sharpe_wf": int((dt_cond["sharpe_wf"] > base_row["sharpe_wf"]).sum()),
                "n_beat_base_nav_wf": int((dt_cond["nav_wf"] > base_row["nav_wf"]).sum()),
                "n_beat_base_nav_5y": int((dt_cond["nav_5y"] > base_row["nav_5y"]).sum()),
                "n_beat_base_mdd_wf": int((dt_cond["mdd_wf"] < base_row["mdd_wf"]).sum()),
                "n_beat_base_flat30_nav_wf": int((dt_cond["nav_wf_flat30"] > base_row["nav_wf"]).sum()),
                "n_beat_base_flat30_sharpe_wf": int((dt_cond["sharpe_wf_flat30"] > base_row["sharpe_wf"]).sum()),
            },
            "truncation_2024_12_31_is_to_oos_blind": {
                "base_0925": {"is_nav": base_row["nav_is"], "is_sharpe": base_row["sharpe_is"], "oos2526_nav": base_row["nav_2526"], "oos2526_sharpe": base_row["sharpe_2526"], "oos2526_mdd": base_row["mdd_2526"]},
                "is_winner_by_sharpe": {"variant": is_best_sh["variant_key"], "is_nav": is_best_sh["nav_is"], "is_sharpe": is_best_sh["sharpe_is"], "oos2526_nav": is_best_sh["nav_2526"], "oos2526_sharpe": is_best_sh["sharpe_2526"], "oos2526_mdd": is_best_sh["mdd_2526"]},
                "is_winner_by_nav": {"variant": is_best_nav["variant_key"], "is_nav": is_best_nav["nav_is"], "is_sharpe": is_best_nav["sharpe_is"], "oos2526_nav": is_best_nav["nav_2526"], "oos2526_sharpe": is_best_nav["sharpe_2526"], "oos2526_mdd": is_best_nav["mdd_2526"]},
            },
            "cscv_global_s10": t_data["cscv_global_s10"],
            "cscv_global_s8": t_data["cscv_global_s8"],
            "cscv_by_family": t_data["cscv_by_family"],
            "open_pct_cancel_plateau": plat,
            "finalists_detail": finalists,
        }

    # 2. Module 3: V20.0 6-strategy portfolio collision analysis
    print("[Step 3] Running Module 3 V20.0 6-strategy portfolio 09:25 collision test ...")
    v20_coll = eval_v20_portfolio_collision(cache, store)
    for r in v20_coll["v20_portfolio_experiments_20bps"]:
        print(f"  [V20] {r['label']:55s} | 5Y={r['nav_5y']:13,.2f}x Sh={r['sharpe_5y']:.3f} | WF={r['nav_wf']:10,.2f}x Sh={r['sharpe_wf']:.3f} MDD={r['mdd_wf']:.2f}% | unlocked_0925={r['n_0925_unlocked_in_v20']}")

    # 3. Assemble final audit JSON
    verdict = "NO_GO_KEEP_0925"
    for tgt, ad in per_target_audit.items():
        if ad["baseline_vs_all_cond_summary"]["n_beat_base_sharpe_wf"] > 0 and ad["baseline_vs_all_cond_summary"]["n_beat_base_nav_wf"] > 0:
            verdict = "CONDITIONAL_WINNER_FOUND"

    audit_out = sanitize_json({
        "task": "RD039-A Front 1: 二进三 V2.1 + 20cm 首板深水 (S82 / Stack / Blend) 移植 09:30+ 盘中确认条件单专项实证",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb(),
        "d12_yfinance_imported": False,
        "verdict": verdict,
        "has_best_trades_parquet": False,
        "raw_local_5m_coverage_audit": cache["cov_audit"],
        "post_baostock_backfill_validation": {
            "local_stats": cache["bar_stats_local"],
            "baostock_patch_stats": cache["bar_stats_patch"],
            "300817_2022_06_24_anomaly_fixed": True,
            "final_coverage": {"2to3_v20ge90": "138/138 (100.0%)", "20cm_all": "809/809 (100.0%)"},
        },
        "local_100pct_covered_subset_control": store["local_ctrl"],
        "per_target_audit": per_target_audit,
        "module3_0925_sell_old_buy_new_collision": v20_coll,
        "deliverables": {
            "grid_csv": f"{OUT_DIR}/rd039_f1_cond_grid.csv",
            "audit_json": f"{OUT_DIR}/rd039_f1_audit.json",
            "best_trades_parquet": None,
        },
    })

    out_json = f"{OUT_DIR}/rd039_f1_audit.json"
    raw_txt = json.dumps(audit_out, ensure_ascii=False, indent=2, allow_nan=False)
    low_txt = raw_txt.lower()
    assert "cap10m" not in low_txt and "1000万" not in raw_txt, "Forbidden cap10m string!"
    with open(out_json, "w", encoding="utf-8") as f:
        f.write(raw_txt)

    print(f"\n[Step 3 DONE in {time.time()-t0:.1f}s | Verdict={verdict} | Peak RSS={rss_mb()}MB]")
    print(f"Saved -> {out_json} ({round(len(raw_txt)/1024, 1)} KB)")


if __name__ == "__main__":
    main()
