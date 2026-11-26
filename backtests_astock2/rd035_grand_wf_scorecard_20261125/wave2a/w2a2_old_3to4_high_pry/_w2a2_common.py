#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Shared utilities for RD035 Wave 2A-2 (`3to4`, `high`, `pry`):
  - Baseline parity verification (0.20%) & strict 0.30% round-trip friction conversion
  - Unified standalone slot simulator for both Mode B (orig_score + delta) and Mode A (0..100 scorecard)
  - Exact V20.0 combined single-slot replacement evaluator (with strict causal priority collision)
  - Day-declustered (`1/N_day` weighted) causal scorecard learner for heavily clustered pools (`pry`)
  - Dedicated Minefield (<= -7%) vs Dragon-Hunting physical split evaluator

Zero yfinance (D12). Zero cap10m. Read-only on wave1_base and production scripts.
"""
import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import json
import math
import sys
from typing import Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
OUT_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a2_old_3to4_high_pry"
os.makedirs(OUT_DIR, exist_ok=True)

for p in (WAVE1_BASE, RD028_DIR, PARTC_V20):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_core as wfc
import _wf_sim_and_metrics as wfm
import step4_mod_rules_and_sim as m1
import tier_priority_engine as tpe

ORIG_THRESHOLDS = {"3to4": 90.0, "high": 88.0, "pry": 165.0}
BASE_INTERCEPTS = {"3to4": 78.0, "high": 60.0, "pry": 100.0}
ATOMIC_PREFIXES = {"3to4": "s34_af_", "high": "shigh_af_", "pry": "spry_af_"}
EXPECTED_PARITY = {
    "3to4": {"n": 95, "nav": 616.1818},
    "high": {"n": 42, "nav": 14.7494},
    "pry": {"n": 16, "nav": 2.4400},
}


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


def convert_020_to_030(net_ret_020: np.ndarray | pd.Series) -> np.ndarray:
    """Convert net_ret calculated at 0.20% round-trip fee to strict 0.30% round-trip fee."""
    arr = np.asarray(net_ret_020, dtype=float)
    return (1.0 + arr) / 0.9980 * 0.9970 - 1.0


def load_master_pool_with_exec(strat: str) -> tuple[pd.DataFrame, dict]:
    """Load wave1_base master pool for `strat`, attach rd028 execution tie-break columns, verify 0.20% parity."""
    pm = pd.read_parquet(f"{WAVE1_BASE}/pool_{strat}_master_pit.parquet")
    pm["buy_date"] = pm["buy_date"].astype(str).str[:10]
    pm["exit_date"] = pm["exit_date"].astype(str).str[:10]
    pm["code"] = pm["code"].astype(str).str.zfill(6)

    po = pd.read_parquet(f"{RD028_DIR}/pool_{strat}_oldhot.parquet")
    po["buy_date"] = po["buy_date"].astype(str).str[:10]
    po["code"] = po["code"].astype(str).str.zfill(6)
    extra_cols = [c for c in po.columns if c not in pm.columns]
    pm = pm.merge(po[["buy_date", "code"] + extra_cols], on=["buy_date", "code"], how="left")

    if strat == "high":
        pm["v51_cb_loss"] = (pm["net_ret"].to_numpy(float) < -0.02) & (~pm["dt_deferred"].to_numpy(bool))

    # Strict 0.20% baseline parity check
    _, slot_020 = m1.sim_standalone(strat, pm, np.zeros(len(pm)), high_cb_mode="v51_exact")
    nav_020 = float(np.prod(1.0 + slot_020["net_ret"].to_numpy(float)))
    exp = EXPECTED_PARITY[strat]
    assert len(slot_020) == exp["n"], f"{strat} parity n={len(slot_020)} != {exp['n']}"
    assert abs(nav_020 - exp["nav"]) < 1e-3, f"{strat} parity nav={nav_020} != {exp['nav']}"

    # Strict atomic reconstruction parity check
    af_cols = sorted([c for c in pm.columns if c.startswith(ATOMIC_PREFIXES[strat])])
    recon = BASE_INTERCEPTS[strat] + pm[af_cols].sum(axis=1)
    af_diff = float((pm["orig_score"].astype(float) - recon).abs().max())
    assert af_diff < 1e-4, f"{strat} atomic sum diff={af_diff}"

    # Preserve 0.20% return, set canonical net_ret to strict 0.30% friction
    pm["net_ret_020"] = pm["net_ret"].astype(float)
    pm["net_ret_030"] = convert_020_to_030(pm["net_ret_020"])
    pm["net_ret"] = pm["net_ret_030"]
    pm["is_yizi"] = pd.to_numeric(pm["open_pct"], errors="coerce").fillna(0.0) >= 0.095
    pm["can_buy_hygiene"] = (~pm["is_yizi"]) & (pm["sim_ok"].fillna(1).astype(int) == 1) & pm["net_ret"].notna()

    parity_info = {
        "strategy": strat,
        "pool_rows": int(len(pm)),
        "unique_buy_days": int(pm["buy_date"].nunique()),
        "baseline_020_n": int(len(slot_020)),
        "baseline_020_nav": round(nav_020, 4),
        "expected_n": exp["n"],
        "expected_nav": exp["nav"],
        "atomic_cols_count": len(af_cols),
        "atomic_recon_max_diff": round(af_diff, 8),
        "parity_pass": True,
    }
    return pm, parity_info


def get_feature_groups(df: pd.DataFrame, strat: str) -> dict[str, list[str]]:
    """Return strictly entry-time PIT feature groups (NO bar_*, NO other-strategy af_*)."""
    with open(f"{WAVE1_BASE}/wave1a_factor_catalog_and_pit_audit.json", encoding="utf-8") as f:
        cat = json.load(f)["master_factor_catalog"]

    native_af = sorted([c for c in df.columns if c.startswith(ATOMIC_PREFIXES[strat])])
    xtr_cols = sorted([c for c, v in cat.items() if v["role"] == "cross_transplant_factor" and c in df.columns])
    entry_num = sorted([
        c for c, v in cat.items()
        if v["role"] == "entry_feature" and v["dtype"] != "object" and c in df.columns
    ])
    return {
        "native_af": native_af,
        "xtr": xtr_cols,
        "entry_330": entry_num,
        "all_new_367": entry_num + xtr_cols,
        "all_with_native": native_af + entry_num + xtr_cols,
    }


def sim_strategy_custom(
    strat: str,
    df: pd.DataFrame,
    score_col: str,
    threshold: float | str | None,
    wf_only: bool = True,
    high_cb_mode: str = "v51_exact",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Exact single-slot simulation preserving each strategy's physical execution & tie-break rules:
      - `3to4`: sort by buy_date, buy_hhmm, score*10 + prio_tie*0.1; slot check (bd > ed or bd==ed & bh > eh)
      - `high`: sort by buy_date, score DESC; slot check (bd > ed or bd==ed & prev_eo & not b_open_h) + optional 2-loss CB
      - `pry`: sort by buy_date, score DESC, bias10 ASC; slot check (bd > ed)
    """
    m = df["can_buy_hygiene"].fillna(True).to_numpy(bool)
    if wf_only and "wf_in_window" in df.columns:
        m &= df["wf_in_window"].fillna(False).to_numpy(bool)
    m &= df[score_col].notna().to_numpy(bool)

    if threshold is not None:
        if isinstance(threshold, str):
            tv = pd.to_numeric(df[threshold], errors="coerce").to_numpy(float)
            m &= np.isfinite(tv) & (df[score_col].to_numpy(float) >= tv)
        else:
            m &= df[score_col].to_numpy(float) >= float(threshold)

    sub = df[m].copy()
    if sub.empty:
        return sub, sub

    sub["_sc_use"] = sub[score_col].to_numpy(float)
    if strat == "3to4":
        pt = pd.to_numeric(sub["prio_tie"], errors="coerce").fillna(0.0).to_numpy(float)
        sub["_prio"] = sub["_sc_use"] * 10.0 + pt * 0.1
        srt = sub.sort_values(["buy_date", "buy_hhmm", "_prio", "code"], ascending=[True, True, False, True], kind="mergesort")
        t_idx, fdt, fhh = [], "", 0
        for r in srt.itertuples():
            if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
                t_idx.append(r.Index)
                fdt, fhh = str(r.exit_date), int(r.exit_hhmm)
        return sub.reset_index(drop=True), srt.loc[t_idx].copy().reset_index(drop=True)

    if strat == "high":
        srt = sub.sort_values(["buy_date", "_sc_use", "code"], ascending=[True, False, True], kind="mergesort")
        t_idx, fd, peo, cl, sk = [], "", False, 0, False
        for r in srt.itertuples():
            if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not bool(r.b_open_h))):
                if high_cb_mode != "none" and sk:
                    fd, peo = str(r.exit_date), bool(r.eo)
                    if float(r.net_ret) > 0.0:
                        sk, cl = False, 0
                    continue
                t_idx.append(r.Index)
                fd, peo = str(r.exit_date), bool(r.eo)
                if high_cb_mode == "v51_exact" and "v51_cb_loss" in srt.columns:
                    is_cb_loss = bool(r.v51_cb_loss)
                else:
                    is_cb_loss = float(r.net_ret) < -0.02
                if is_cb_loss:
                    cl += 1
                    sk = (cl >= 2)
                elif float(r.net_ret) > 0.0:
                    cl = 0
        return sub.reset_index(drop=True), srt.loc[t_idx].copy().reset_index(drop=True)

    # pry
    b10 = pd.to_numeric(sub["bias10"], errors="coerce").fillna(0.0).to_numpy(float) if "bias10" in sub.columns else np.zeros(len(sub))
    sub["_bias10"] = b10
    srt = sub.sort_values(["buy_date", "_sc_use", "_bias10", "code"], ascending=[True, False, True, True], kind="mergesort")
    t_idx, fdt = [], ""
    for r in srt.itertuples():
        if (not fdt) or (r.buy_date > fdt):
            t_idx.append(r.Index)
            fdt = str(r.exit_date)
    return sub.reset_index(drop=True), srt.loc[t_idx].copy().reset_index(drop=True)


def eval_v20_combined_replacement(
    strat_name: str,
    new_slot_df: pd.DataFrame,
    v20_ctx: dict,
    wf_start_dt: str = "2023-01-03",
    end_dt: str = "2026-11-16",
    s_tier_cutoff: Optional[float] = None,
    score_col: str = "_sc_use",
) -> dict:
    """
    Replace `strat_name` inside the 6-strategy V20.0 combined portfolio over [wf_start_dt, end_dt]
    using V20.0 priority map `S2C_MAP` and S-tier waits from the other 5 strategies.
    Reports BOTH raw V20.0 baseline (0.20%) and apples-to-apples baseline (0.30% on `strat_name`).
    """
    cal_df = v20_ctx["calendar_5y"]
    cal_win = cal_df[cal_df["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_arr = cal_win["csi300_daily_ret"].to_numpy(float)
    ew_arr = cal_win["alla_ew_daily_ret"].to_numpy(float)

    v20_led = v20_ctx["v20_ledger"]
    v20_win = v20_led[v20_led["buy_date"].between(wf_start_dt, end_dt)].copy().reset_index(drop=True)
    v20_win["source"] = "v20"

    # Baseline 0.20% MTM
    dr_base020, _ = _build_ledger_mtm(v20_win, cal_dts)
    m_base020 = wfm._calc_one_window(v20_win, None, dr_base020, cal_dts, dt_idx, csi_arr, ew_arr, wf_start_dt, end_dt)

    # Baseline with 0.30% friction applied to target `strat_name` for fair comparison
    v20_leg030 = v20_win.copy()
    mask_st = v20_leg030["strategy"] == strat_name
    if mask_st.any():
        v20_leg030.loc[mask_st, "net_ret"] = convert_020_to_030(v20_leg030.loc[mask_st, "net_ret"])
        # Recompute mtm_pairs last leg scale slightly for exact reconciliation
        new_pairs = []
        for r in v20_leg030.itertuples(index=False):
            if r.strategy == strat_name and r.mtm_pairs:
                ps = [list(x) for x in r.mtm_pairs]
                ps[-1][1] = float(ps[-1][1]) / 0.9980 * 0.9970
                new_pairs.append(ps)
            else:
                new_pairs.append(r.mtm_pairs)
        v20_leg030["mtm_pairs"] = new_pairs
    dr_base030, _ = _build_ledger_mtm(v20_leg030, cal_dts)
    m_base030 = wfm._calc_one_window(v20_leg030, None, dr_base030, cal_dts, dt_idx, csi_arr, ew_arr, wf_start_dt, end_dt)

    # Build combined candidate pool: other 5 strategies from v20_win + new_slot_df for `strat_name`
    others = v20_win[v20_win["strategy"] != strat_name].copy()
    others["is_untrig"] = False
    others["buy_price_val"] = np.nan
    others["is_adj_px"] = False

    ns = new_slot_df[new_slot_df["buy_date"].between(wf_start_dt, end_dt)].copy()
    if not ns.empty:
        sc_vals = pd.to_numeric(ns.get(score_col, ns.get("wf_score", ns.get("orig_score", 90.0))), errors="coerce").fillna(90.0).to_numpy(float)
        if s_tier_cutoff is not None:
            is_s = sc_vals >= float(s_tier_cutoff)
            s_lbl = {"3to4": "3to4_S(>=102)", "high": "high_S(>=96)", "pry": "pry_S(>=175)"}[strat_name]
            a_lbl = {"3to4": "3to4_A(90-101)", "high": "high_A(88-95)", "pry": "pry_A(165-174)"}[strat_name]
            ns["tier"] = [s_lbl if f else a_lbl for f in is_s]
        else:
            ns["tier"] = [tpe.assign_physical_tier(strat_name, sc) for sc in sc_vals]
        ns["strategy"] = strat_name
        ns["score"] = sc_vals
        if "name" not in ns.columns:
            ns["name"] = ""
        ns["is_untrig"] = False
        ns["buy_price_val"] = np.nan
        ns["is_adj_px"] = False
        ns["source"] = "new_strat"
        ns["mtm_pairs"] = [[] for _ in range(len(ns))]

    keep_cols = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig"]
    parts = [others[keep_cols]] + ([ns[keep_cols]] if not ns.empty else [])
    pool_c = pd.concat(parts, ignore_index=True)

    # Untriggered S-tier waits from other strategies (keep baseline waits for untouched strategies)
    ut_rows = []
    for w in v20_ctx["v20_waits"]:
        if wf_start_dt <= w["buy_date"] <= end_dt and w["wait_strategy"] != strat_name:
            ut_rows.append({
                "buy_date": w["buy_date"], "buy_hhmm": 935, "exit_date": w["buy_date"], "exit_hhmm": int(w["cancel_hhmm"]),
                "code": w["wait_code"], "name": "", "strategy": w["wait_strategy"], "tier": w["wait_tier"],
                "score": 100.0, "net_ret": 0.0, "buy_price_val": np.nan, "is_adj_px": False, "is_untrig": True,
            })
    ut_df = pd.DataFrame(ut_rows) if ut_rows else None

    tr_c, _ = tpe.run_single_slot(
        pool_c,
        lambda d: d["tier"].map(m1.S2C_MAP).fillna(999).to_numpy(),
        untrig_df=ut_df,
        timing_mode="s_tier_reserve_only",
    )
    # Restore mtm_pairs for untouched strategies
    mtm_lu = {(r.strategy, r.buy_date, r.code): r.mtm_pairs for r in others.itertuples(index=False)}
    if not tr_c.empty:
        tr_c["source"] = np.where(tr_c["strategy"] == strat_name, "new_strat", "v20")
        tr_c["mtm_pairs"] = [mtm_lu.get((r.strategy, r.buy_date, r.code), []) for r in tr_c.itertuples(index=False)]

    dr_new, _ = _build_ledger_mtm(tr_c, cal_dts)
    m_new = wfm._calc_one_window(tr_c, None, dr_new, cal_dts, dt_idx, csi_arr, ew_arr, wf_start_dt, end_dt)
    n_target_comb = int((tr_c["strategy"] == strat_name).sum()) if not tr_c.empty else 0

    return {
        "v20_comb_base_020_nav": m_base020["nav"],
        "v20_comb_base_leg030_nav": m_base030["nav"],
        "v20_comb_base_leg030_sharpe": m_base030["daily_sharpe"],
        "v20_comb_base_leg030_mdd": m_base030["daily_mdd_pct"],
        "v20_comb_new_nav": m_new["nav"],
        "v20_comb_new_n": m_new["n"],
        "v20_comb_new_target_n": n_target_comb,
        "v20_comb_new_sharpe": m_new["daily_sharpe"],
        "v20_comb_new_mdd": m_new["daily_mdd_pct"],
        "v20_comb_delta_ratio_vs_leg030": round(m_new["nav"] / max(1e-9, m_base030["nav"]), 4),
        "v20_comb_delta_ratio_vs_020": round(m_new["nav"] / max(1e-9, m_base020["nav"]), 4),
        "v20_comb_delta_sharpe": round(m_new["daily_sharpe"] - m_base030["daily_sharpe"], 4),
        "v20_comb_delta_mdd_pp": round(m_new["daily_mdd_pct"] - m_base030["daily_mdd_pct"], 2),
    }


def _build_ledger_mtm(tr_df: pd.DataFrame, cal_dts: list[str]) -> tuple[np.ndarray, float]:
    T = len(cal_dts)
    if tr_df.empty:
        return np.zeros(T, dtype=float), 0.0
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    day_mult = np.ones(T, dtype=float)
    for r in tr_df.itertuples(index=False):
        mp = getattr(r, "mtm_pairs", None)
        if mp:
            for d_str, mult in mp:
                ti = dt_idx.get(d_str)
                if ti is not None:
                    day_mult[ti] *= float(mult)
        else:
            bi = dt_idx.get(str(r.buy_date))
            ei = dt_idx.get(str(r.exit_date))
            if bi is None:
                continue
            if ei is None or ei <= bi:
                day_mult[bi] *= (1.0 + float(r.net_ret))
            else:
                span = ei - bi + 1
                day_mult[bi:ei + 1] *= (1.0 + float(r.net_ret)) ** (1.0 / span)
    dr = day_mult - 1.0
    tr_sub = tr_df[tr_df["buy_date"].isin(dt_idx)]
    tr_nav = float(np.prod(1.0 + tr_sub["net_ret"].to_numpy(float))) if not tr_sub.empty else 1.0
    return dr, abs(float(np.prod(day_mult)) - tr_nav)


def summarize_eval_row(
    strat: str,
    module: str,
    variant_id: str,
    pass_df: pd.DataFrame,
    slot_df: pd.DataFrame,
    wf_cands: pd.DataFrame,
    v20_ctx: dict,
    wf_start_dt: str,
    end_dt: str = "2026-11-16",
    perm_n: int = 1000,
    s_tier_cutoff: Optional[float] = None,
    score_col: str = "_sc_use",
    empty_patch_res: Optional[dict] = None,
) -> tuple[dict, dict]:
    """Compute standardized WF evaluation + V20 combined replacement + return compact row + full detail."""
    ev = wf.evaluate_wf_ledger(
        slot_df, pass_df, wf_cands, v20_ctx["bench"],
        wf_start_dt=wf_start_dt, end_dt=end_dt, perm_n=perm_n, seed=20261125,
    )
    comb = eval_v20_combined_replacement(
        strat_name=strat if strat in ("3to4", "high", "pry") else "high",
        new_slot_df=slot_df,
        v20_ctx=v20_ctx,
        wf_start_dt=wf_start_dt,
        end_dt=min(end_dt, "2026-11-16"),
        s_tier_cutoff=s_tier_cutoff,
        score_col=score_col,
    )
    fw = ev["windows"].get("FULL_WF", {})
    y2526 = ev["windows"].get("Y2025_2026", {})
    y26 = ev["windows"].get("Y2026", {})
    pm = ev["permutation_1000"]

    ep_ratio = None
    if empty_patch_res is not None:
        ep_ratio = empty_patch_res["mode1_strict_combined_no_peek"]["delta_nav_ratio_full_wf"]

    row = {
        "strategy": strat,
        "module": module,
        "variant_id": variant_id,
        "wf_start": wf_start_dt,
        "wf_end": end_dt,
        "n_pass": int(len(pass_df)),
        "n_trades": fw.get("n", 0),
        "wr_pct": fw.get("wr_pct", 0.0),
        "plr": fw.get("plr", 0.0),
        "mean_pct": fw.get("mean_pct", 0.0),
        "nav_wf": fw.get("nav", 1.0),
        "ex3_wf": fw.get("ex_top3_nav", 1.0),
        "ex5_wf": fw.get("ex_top5_nav", 1.0),
        "daily_mdd_pct": fw.get("daily_mdd_pct", 0.0),
        "trade_mdd_pct": fw.get("trade_mdd_pct", 0.0),
        "sharpe": fw.get("daily_sharpe", 0.0),
        "excess_csi300_pp": fw.get("excess_csi300_pp", 0.0),
        "excess_alla_ew_pp": fw.get("excess_alla_ew_pp", 0.0),
        "n_2526": y2526.get("n", 0),
        "nav_2526": y2526.get("nav", 1.0),
        "ex5_2526": y2526.get("ex_top5_nav", 1.0),
        "excess_csi_2526_pp": y2526.get("excess_csi300_pp", 0.0),
        "n_y26": y26.get("n", 0),
        "nav_y26": y26.get("nav", 1.0),
        "perm_sd_p": pm.get("same_day_p_nav", 1.0),
        "perm_any_p": pm.get("any_cand_day_p_nav", 1.0),
        **comb,
        "v20_empty_patch_delta_ratio": ep_ratio,
    }
    return row, {"metrics": ev, "v20_comb": comb, "empty_patch": empty_patch_res}


# =============================================================================
# Day-Declustered (1/N_day Weighted) Causal Scorecard for Clustered Pools (pry)
# =============================================================================

def _weighted_quantile(values: np.ndarray, weights: np.ndarray, qs: list[float]) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    v = values[order]
    w = weights[order]
    cdf = (np.cumsum(w) - 0.5 * w) / np.sum(w)
    return np.interp(qs, cdf, v)


def _weighted_cluster_t(u: np.ndarray, z: np.ndarray, w: np.ndarray, day_ids: np.ndarray) -> float:
    """Cluster-robust WLS t-stat clustered by buy_date with inverse-day-size weights."""
    n = len(u)
    if n < 20:
        return 0.0
    sw = float(np.sum(w))
    if sw <= 1e-12:
        return 0.0
    mz = float(np.sum(w * z)) / sw
    mu = float(np.sum(w * u)) / sw
    dz = z - mz
    du = u - mu
    szz = float(np.sum(w * dz * dz))
    if szz <= 1e-12:
        return 0.0
    beta = float(np.sum(w * dz * du)) / szz
    eps = du - beta * dz
    _, g_inv = np.unique(day_ids, return_inverse=True)
    G = int(g_inv.max()) + 1
    if G < 5:
        return 0.0
    sg = np.bincount(g_inv, weights=w * dz * eps, minlength=G)
    var_b = (G / max(1, G - 1)) * float(np.dot(sg, sg)) / (szz * szz)
    if var_b <= 1e-18:
        return 0.0
    return float(beta / math.sqrt(var_b))


def fit_declustered_causal_scorecard(
    X_train: np.ndarray,
    y_ret: np.ndarray,
    y_win: np.ndarray,
    day_ids: np.ndarray,
    feature_names: list[str],
    mode: str = "scorecard_0_100",
    top_k: int = 10,
    min_k: int = 4,
    max_corr: float = 0.65,
    min_t_stat: float = 1.0,
    shrink_tau: float = 10.0,
    max_delta: int = 15,
    orig_score_train: Optional[np.ndarray] = None,
    max_corr_orig: Optional[float] = None,
    target_mode: str = "utility",
) -> dict:
    """
    Day-declustered causal scorecard: every unique `buy_date` gets equal total weight `1.0`
    (`w_i = 1 / count_on_day[buy_date_i]`) so single crash days (like 2024-02-07 with 286 stocks)
    cannot hijack quantile edges, shrinkage baselines, or score percentiles!
    Also supports `target_mode`:
      - 'utility': 0.6*z(ret) + 0.4*z(win)
      - 'minefield': binary tail-loss y_ret (where y_ret passed in IS y_mine in {0,1})
      - 'dragon': upside tail 0.5*z(ret>=0.10) + 0.5*z(ret)
    """
    M, F = X_train.shape
    _, g_inv = np.unique(day_ids, return_inverse=True)
    day_cnts = np.bincount(g_inv)
    w_day = 1.0 / np.maximum(1.0, day_cnts[g_inv].astype(float))
    G_tot = int(day_cnts.shape[0])

    mu0_all = float(np.average(y_ret, weights=w_day))
    wr0_all = float(np.average(y_win, weights=w_day))
    min_valid_n = max(25, int(0.45 * M))

    candidates = []
    for j in range(F):
        col = X_train[:, j]
        valid = np.isfinite(col)
        nv = int(valid.sum())
        if nv < min_valid_n:
            continue
        xv = col[valid]
        if float(np.std(xv)) < 1e-12:
            continue
        rv = y_ret[valid]
        wv = y_win[valid]
        dv = day_ids[valid]
        # Re-normalize day weights on valid rows
        _, gv_inv = np.unique(dv, return_inverse=True)
        if int(gv_inv.max()) + 1 < 8:
            continue
        vcnts = np.bincount(gv_inv)
        w = 1.0 / np.maximum(1.0, vcnts[gv_inv].astype(float))

        mu0 = float(np.average(rv, weights=w))
        wr0 = float(np.average(wv, weights=w))
        sd_r = max(1e-5, float(np.sqrt(np.average((rv - mu0) ** 2, weights=w))))

        if target_mode == "minefield":
            u_util = (rv - mu0) / sd_r
        elif target_mode == "dragon":
            big = (rv >= 0.10).astype(float)
            b0 = float(np.average(big, weights=w))
            u_util = 0.5 * (big - b0) / 0.30 + 0.5 * (rv - mu0) / sd_r
        else:
            u_util = 0.6 * (rv - mu0) / sd_r + 0.4 * (wv - wr0) / 0.25

        uniq = np.unique(xv)
        if len(uniq) <= 3:
            edges = uniq.astype(float)
            b_idx = np.searchsorted(edges, xv, side="left")
            is_discrete = True
            B = len(edges)
            if B < 2:
                continue
            raw_c_disc = np.bincount(b_idx, minlength=B)
            w_c_disc = np.bincount(b_idx, weights=w, minlength=B)
            if np.any(raw_c_disc < 5) or np.any(w_c_disc < 2.0):
                continue
        else:
            q33, q67 = _weighted_quantile(xv, w, [1.0 / 3.0, 2.0 / 3.0])
            if q67 <= q33 + 1e-12:
                q50 = float(_weighted_quantile(xv, w, [0.5])[0])
                b_idx = (xv > q50).astype(int)
                if b_idx.sum() < 5 or (nv - b_idx.sum()) < 5:
                    b_idx = (xv >= q50).astype(int)
                if b_idx.sum() < 5 or (nv - b_idx.sum()) < 5:
                    continue
                edges = np.array([q50], dtype=float)
                B = 2
            else:
                b_idx = np.where(xv <= q33, 0, np.where(xv <= q67, 1, 2))
                w_cnts = np.bincount(b_idx, weights=w, minlength=3)
                if np.any(w_cnts < 2.0) or np.any(np.bincount(b_idx, minlength=3) < 5):
                    q50 = float(_weighted_quantile(xv, w, [0.5])[0])
                    b_idx = (xv > q50).astype(int)
                    if b_idx.sum() < 5 or (nv - b_idx.sum()) < 5:
                        continue
                    edges = np.array([q50], dtype=float)
                    B = 2
                else:
                    edges = np.array([float(q33), float(q67)], dtype=float)
                    B = 3
            is_discrete = False

        w_cnts = np.bincount(b_idx, weights=w, minlength=B)
        raw_cnts = np.bincount(b_idx, minlength=B)
        w_sum_r = np.bincount(b_idx, weights=w * rv, minlength=B)
        w_sum_w = np.bincount(b_idx, weights=w * wv, minlength=B)
        shr_dr = (w_sum_r + shrink_tau * mu0) / (w_cnts + shrink_tau) - mu0
        shr_dw = (w_sum_w + shrink_tau * wr0) / (w_cnts + shrink_tau) - wr0

        if target_mode == "minefield":
            eff = shr_dr / sd_r
        else:
            eff = 0.6 * (shr_dr / sd_r) + 0.4 * (shr_dw / 0.25)

        if B == 3:
            z_lin = b_idx.astype(float) - 1.0
            t_lin = _weighted_cluster_t(u_util, z_lin, w, dv)
            z_quad = np.where(b_idx == 1, 1.0, -0.5)
            t_quad = _weighted_cluster_t(u_util, z_quad, w, dv)
            if abs(t_quad) >= max(1.5, abs(t_lin) + 0.35):
                t_eff = t_quad
                shape = "nonmonotone"
            else:
                lo_e, hi_e = min(eff[0], eff[2]), max(eff[0], eff[2])
                eff[1] = float(np.clip(eff[1], lo_e, hi_e))
                if abs(eff[2] - eff[0]) < 1e-12:
                    eff[2] += 1e-9 if t_lin >= 0 else -1e-9
                t_eff = t_lin
                shape = "monotone_up" if eff[2] >= eff[0] else "monotone_down"
        else:
            z_bin = b_idx.astype(float)
            t_eff = _weighted_cluster_t(u_util, z_bin, w, dv)
            shape = "binary_up" if eff[-1] >= eff[0] else "binary_down"

        if max_corr_orig is not None and orig_score_train is not None:
            ov = orig_score_train[valid]
            m_ov = np.isfinite(ov)
            if m_ov.sum() >= 25 and np.std(ov[m_ov]) > 1e-12 and np.std(xv[m_ov]) > 1e-12:
                r_orig = abs(float(np.corrcoef(xv[m_ov], ov[m_ov])[0, 1]))
                if r_orig > max_corr_orig:
                    continue

        candidates.append({
            "col_idx": j,
            "name": feature_names[j],
            "abs_t": abs(float(t_eff)),
            "t_cluster": round(float(t_eff), 3),
            "shape": shape,
            "is_discrete": is_discrete,
            "edges": edges,
            "B": B,
            "eff": eff,
            "cnts": raw_cnts.tolist(),
            "w_cnts": [round(float(x), 2) for x in w_cnts],
            "bin_wr_pct": [round(float(w_sum_w[b] / max(1e-9, w_cnts[b]) * 100.0), 2) for b in range(B)],
            "bin_mean_pct": [round(float(w_sum_r[b] / max(1e-9, w_cnts[b]) * 100.0), 2) for b in range(B)],
        })

    candidates.sort(key=lambda c: (-c["abs_t"], c["col_idx"]))

    def _sel(cands_list):
        sel = []
        for c in cands_list:
            j = c["col_idx"]
            xj = X_train[:, j]
            ok = True
            for s in sel:
                xs = X_train[:, s["col_idx"]]
                both = np.isfinite(xj) & np.isfinite(xs)
                if both.sum() >= 20 and np.std(xj[both]) > 1e-12 and np.std(xs[both]) > 1e-12:
                    if abs(float(np.corrcoef(xj[both], xs[both])[0, 1])) > max_corr:
                        ok = False
                        break
            if ok:
                sel.append(c)
                if len(sel) >= top_k:
                    break
        return sel

    strong = [c for c in candidates if c["abs_t"] >= min_t_stat]
    selected = _sel(strong)
    if len(selected) < min_k and len(candidates) > len(selected):
        used = {s["col_idx"] for s in selected}
        rem = [c for c in candidates if c["col_idx"] not in used]
        for c in rem:
            j = c["col_idx"]
            xj = X_train[:, j]
            ok = True
            for s in selected:
                xs = X_train[:, s["col_idx"]]
                both = np.isfinite(xj) & np.isfinite(xs)
                if both.sum() >= 20 and np.std(xj[both]) > 1e-12 and np.std(xs[both]) > 1e-12:
                    if abs(float(np.corrcoef(xj[both], xs[both])[0, 1])) > max_corr:
                        ok = False
                        break
            if ok:
                selected.append(c)
                if len(selected) >= min_k:
                    break

    if not selected:
        return {"mode": mode, "n_train": M, "n_days_train": G_tot, "factors": [], "train_mu0_pct": round(mu0_all * 100.0, 2)}

    t_weights = np.array([min(4.0, max(0.25, c["abs_t"])) for c in selected], dtype=float)
    budget_tot = 100 if mode == "scorecard_0_100" else int(max_delta)
    budgets = wfc._largest_remainder_int(t_weights, budget_tot)

    factors_out = []
    for c, bgt in zip(selected, budgets):
        eff = c["eff"]
        emin, emax = float(np.min(eff)), float(np.max(eff))
        if mode == "scorecard_0_100":
            if emax > emin + 1e-12:
                pts = [int(round((float(e) - emin) / (emax - emin) * bgt)) for e in eff]
            else:
                pts = [int(round(0.5 * bgt)) for _ in eff]
            nan_pt = int(round(0.5 * bgt))
        else:
            emean = float(np.average(eff, weights=np.array(c["w_cnts"], dtype=float)))
            span = max(1e-12, float(np.max(np.abs(eff - emean))))
            pts = [int(round((float(e) - emean) / span * bgt)) for e in eff]
            nan_pt = 0
        factors_out.append({
            "col_idx": c["col_idx"],
            "name": c["name"],
            "t_cluster": c["t_cluster"],
            "shape": c["shape"],
            "budget_pts": int(bgt),
            "is_discrete": c["is_discrete"],
            "edges": c["edges"].tolist(),
            "bin_pts": pts,
            "nan_pt": nan_pt,
            "bin_cnts": c["cnts"],
            "bin_w_cnts": c["w_cnts"],
            "bin_wr_pct": c["bin_wr_pct"],
            "bin_mean_pct": c["bin_mean_pct"],
        })

    card = {
        "mode": mode,
        "n_train": int(M),
        "n_days_train": int(G_tot),
        "train_mu0_pct": round(mu0_all * 100.0, 2),
        "train_wr0_pct": round(wr0_all * 100.0, 2),
        "factors": factors_out,
    }
    if mode == "scorecard_0_100":
        tr_scores = wfc.score_candidates_with_card(X_train, card).astype(float)
        q70, q75, q80, q85, q90, q95 = _weighted_quantile(tr_scores, w_day, [0.70, 0.75, 0.80, 0.85, 0.90, 0.95])
        card["train_score_q70_top30"] = int(math.ceil(float(q70)))
        card["train_score_q75_top25"] = int(math.ceil(float(q75)))
        card["train_score_q80_top20"] = int(math.ceil(float(q80)))
        card["train_score_q85_top15"] = int(math.ceil(float(q85)))
        card["train_score_q90_top10"] = int(math.ceil(float(q90)))
        card["train_score_q95_top5"] = int(math.ceil(float(q95)))
    return card


def run_declustered_wf_loop(
    df: pd.DataFrame,
    feature_cols: list[str],
    mode: str = "scorecard_0_100",
    wf_start_date: str = "2023-01-03",
    min_warmup_trades: int = 60,
    min_warmup_days: int = 20,
    top_k: int = 10,
    min_k: int = 4,
    max_corr: float = 0.65,
    min_t_stat: float = 1.0,
    shrink_tau: float = 10.0,
    max_delta: int = 15,
    orig_score_col: Optional[str] = "orig_score",
    max_corr_orig: Optional[float] = None,
    target_mode: str = "utility",
    mine_loss_thr: float = -0.07,
) -> tuple[pd.DataFrame, dict]:
    """
    Strictly causal (exit_date < t) day-declustered expanding WF scoring loop.
    Guarantees zero truncation leakage and supports utility / minefield / dragon targets.
    """
    n = len(df)
    buy_dts = df["buy_date"].astype(str).str[:10].to_numpy()
    exit_dts = df["exit_date"].astype(str).str[:10].to_numpy()
    codes = df["code"].astype(str).str.zfill(6).to_numpy()
    raw_ret = df["net_ret"].to_numpy(dtype=np.float64)

    if target_mode == "minefield":
        y_ret = (raw_ret <= mine_loss_thr).astype(np.float64)
        y_win = y_ret.copy()
    else:
        y_ret = raw_ret
        y_win = (raw_ret > 0.0).astype(np.float64)

    can_buy = df["can_buy_hygiene"].fillna(True).to_numpy(bool) & np.isfinite(raw_ret)
    X_all = df[feature_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    orig_arr = pd.to_numeric(df[orig_score_col], errors="coerce").to_numpy(dtype=np.float64) if (orig_score_col and orig_score_col in df.columns) else None

    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_to_id = {d: i for i, d in enumerate(uniq_dts)}
    day_ids_all = np.array([dt_to_id[d] for d in buy_dts], dtype=np.int32)

    buyable_idx = np.where(can_buy)[0]
    exit_order = sorted(buyable_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i]))
    exit_order_arr = np.asarray(exit_order, dtype=np.int64)
    exit_dts_sorted = exit_dts[exit_order_arr]
    X_exit = X_all[exit_order_arr]
    r_exit = y_ret[exit_order_arr]
    w_exit = y_win[exit_order_arr]
    d_exit = day_ids_all[exit_order_arr]
    orig_exit = orig_arr[exit_order_arr] if orig_arr is not None else None

    by_dt_rows = {}
    for i in buyable_idx:
        by_dt_rows.setdefault(buy_dts[i], []).append(i)
    sorted_trade_dts = sorted(by_dt_rows.keys())

    wf_in_win = np.zeros(n, dtype=bool)
    wf_score = np.full(n, np.nan, dtype=np.float64)
    wf_delta = np.zeros(n, dtype=np.float64)
    thr_cols = {k: np.full(n, np.nan, dtype=np.float64) for k in ("q70", "q75", "q80", "q85", "q90", "q95")}

    ptr = 0
    n_exit_tot = len(exit_order_arr)
    started = False
    wf_actual_start = None
    current_card = None
    last_ptr = -1
    seen_days = set()
    n_rebuilds = 0

    for t in sorted_trade_dts:
        while ptr < n_exit_tot and exit_dts_sorted[ptr] < t:
            seen_days.add(int(d_exit[ptr]))
            ptr += 1
        if t < wf_start_date:
            continue
        if not started:
            if ptr >= min_warmup_trades and len(seen_days) >= min_warmup_days:
                started = True
                wf_actual_start = t
            else:
                continue

        if current_card is None or ptr > last_ptr:
            current_card = fit_declustered_causal_scorecard(
                X_exit[:ptr], r_exit[:ptr], w_exit[:ptr], d_exit[:ptr],
                feature_names=feature_cols,
                mode=mode, top_k=top_k, min_k=min_k, max_corr=max_corr,
                min_t_stat=min_t_stat, shrink_tau=shrink_tau, max_delta=max_delta,
                orig_score_train=(orig_exit[:ptr] if orig_exit is not None else None),
                max_corr_orig=max_corr_orig,
                target_mode=target_mode,
            )
            last_ptr = ptr
            n_rebuilds += 1

        rows_t = np.asarray(by_dt_rows[t], dtype=np.int64)
        sc_t = wfc.score_candidates_with_card(X_all[rows_t], current_card)
        wf_in_win[rows_t] = True
        if mode == "scorecard_0_100":
            wf_score[rows_t] = sc_t.astype(np.float64)
            thr_cols["q70"][rows_t] = current_card.get("train_score_q70_top30", 55)
            thr_cols["q75"][rows_t] = current_card.get("train_score_q75_top25", 58)
            thr_cols["q80"][rows_t] = current_card.get("train_score_q80_top20", 60)
            thr_cols["q85"][rows_t] = current_card.get("train_score_q85_top15", 64)
            thr_cols["q90"][rows_t] = current_card.get("train_score_q90_top10", 68)
            thr_cols["q95"][rows_t] = current_card.get("train_score_q95_top5", 73)
        else:
            wf_delta[rows_t] = sc_t.astype(np.float64)
            if orig_arr is not None:
                wf_score[rows_t] = orig_arr[rows_t] + sc_t.astype(np.float64)

    out = df.copy()
    out["wf_in_window"] = wf_in_win
    if mode == "scorecard_0_100":
        out["wf_score"] = wf_score
        out["wf_thr_top30"] = thr_cols["q70"]
        out["wf_thr_top25"] = thr_cols["q75"]
        out["wf_thr_top20"] = thr_cols["q80"]
        out["wf_thr_top15"] = thr_cols["q85"]
        out["wf_thr_top10"] = thr_cols["q90"]
        out["wf_thr_top5"] = thr_cols["q95"]
    else:
        out["wf_delta_score"] = wf_delta
        if orig_arr is not None:
            out["wf_new_score"] = np.where(wf_in_win, orig_arr + wf_delta, orig_arr)

    meta = {
        "mode": f"declustered_{mode}_{target_mode}",
        "wf_actual_start": wf_actual_start,
        "n_rebuilds": n_rebuilds,
        "n_wf_candidates": int(wf_in_win.sum()),
        "latest_scorecard": current_card,
    }
    return out, meta
