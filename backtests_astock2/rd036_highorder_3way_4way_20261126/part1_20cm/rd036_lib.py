#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD036-A Shared Causal Engine, Lean V20.0 Context, MTM/Slippage/CSCV/DSR Evaluators,
and 3-Way / 4-Way / Shallow-Tree Discovery Engines for 20cm Deep-Open Strategy.

Strict guarantees:
  - exit_date < t causal boundary for all dynamic screens, discretizations, trees, and scorecards
  - Zero yfinance (D12), zero cap10m
  - Threads <= 2, Peak RSS < 2.0 GB
  - Exact daily bar MTM returns (mtm_reconciliation_diff < 1e-6, zero geometric smoothing)
"""
import gc
import itertools
import json
import math
import os
import sys
import warnings
from typing import Optional

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "2")

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
from scipy import stats
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.tree import DecisionTreeRegressor

pa.set_cpu_count(2)
pa.set_io_thread_count(2)

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
W2A3_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a3_old_20cm"
W2A4_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a4_pairwise_interactions"
OUT_DIR = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part1_20cm"

for p in (WAVE1_DIR, RD028_DIR, PARTC_V20, W2A3_DIR, W2A4_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _wf_core as wfc
import _wf_sim_and_metrics as wfm
import wf_scorecard_engine as wf
import step4_mod_rules_and_sim as m1
import tier_priority_engine as tpe
import w2a3_lib as w23
import _w2a4_data_and_features as w24

TRD_DAYS_YEAR = 242.0
WF_START_DT = "2023-01-03"
WF_END_DT = "2026-11-16"


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def _build_needed_bar_lu(rows_df: pd.DataFrame, cal_dts: list[str], end_cutoff: Optional[str] = None) -> dict:
    """Load ONLY bars for (c6, dt) actually falling inside [buy_date, exit_date] -> keeps RSS < 1.2GB."""
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    needed_pairs = set()
    needed_codes = set()
    needed_dts = set()
    for r in rows_df.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        bi = dt_idx.get(str(r.buy_date)[:10])
        ei = dt_idx.get(str(r.exit_date)[:10])
        if bi is None:
            continue
        if ei is None:
            ei = bi
        needed_codes.add(c6)
        for t in range(bi, min(ei + 1, len(cal_dts))):
            dt_s = cal_dts[t]
            if end_cutoff is None or dt_s <= end_cutoff:
                needed_pairs.add((c6, dt_s))
                needed_dts.add(dt_s)

    tks = sorted([f"{c}.SH" for c in needed_codes] + [f"{c}.SZ" for c in needed_codes])
    min_dt = min(needed_dts) if needed_dts else "2021-01-01"
    max_dt = max(needed_dts) if needed_dts else "2026-11-25"
    cols = ["date", "ticker", "open", "close", "adj_close", "qfq_factor"]
    bar_lu = {}
    ds_a = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet")
    ds_d = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet")
    for i in range(0, len(tks), 250):
        tk_chunk = tks[i : i + 250]
        flt = (
            (ds.field("date") >= pd.Timestamp(min_dt))
            & (ds.field("date") <= pd.Timestamp(max_dt))
            & (ds.field("ticker").isin(tk_chunk))
        )
        da = ds_a.scanner(columns=cols, filter=flt).to_table().to_pandas()
        dd = ds_d.scanner(columns=cols, filter=flt).to_table().to_pandas()
        da["dl"], dd["dl"] = 0, 1
        dp = pd.concat([da, dd], ignore_index=True)
        del da, dd
        if dp.empty:
            continue
        dp["c6"] = dp["ticker"].astype(str).str[:6]
        dp["dt"] = dp["date"].dt.strftime("%Y-%m-%d")
        dp = dp[dp["ticker"].astype(str).str.endswith((".SH", ".SZ"))].copy()
        # Filter down to exact needed (c6, dt) pairs immediately to keep memory tiny
        keep_mask = [(c, d) in needed_pairs for c, d in zip(dp["c6"], dp["dt"])]
        dp = dp[keep_mask].copy()
        if dp.empty:
            continue
        dp = dp.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
        dp["adjf"] = np.where((dp["close"] > 0) & (dp["adj_close"] > 0), dp["adj_close"] / dp["close"], 1.0)
        for r in dp.itertuples(index=False):
            bar_lu[(r.c6, r.dt)] = (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf))
        del dp
    gc.collect()
    pa.default_memory_pool().release_unused()
    return bar_lu


def load_20cm_enriched_data(end_cutoff: Optional[str] = None) -> tuple[pd.DataFrame, dict]:
    """
    Load 20cm master PIT pool <= end_cutoff, attach:
      - 09:25 same-theme auction features (`auc_*`)
      - Pre-09:25 Xueqiu/Guba 1d/3d/1y burst (`w24_*`)
      - 130 mechanism pairwise interactions (`ix_*`)
      - `buy_px`, `gross_ret`, `net_ret_30`, `net_ret_50`, `net_ret_80`
      - Exact date-keyed daily MTM segment lists (`segs_30`, `segs_50`, `segs_80`)
    """
    p20, meta = w23.load_w2a3_data(end_cutoff=end_cutoff)
    oh20 = pd.read_parquet(f"{RD028_DIR}/pool_20cm_oldhot.parquet", columns=["buy_date", "code", "buy_px", "gross_ret"])
    oh20["buy_date"] = oh20["buy_date"].astype(str).str[:10]
    oh20["code"] = oh20["code"].astype(str).str.zfill(6)
    p20 = p20.merge(oh20, on=["buy_date", "code"], how="left")

    bench = pd.read_parquet(f"{WAVE1_DIR}/v20_daily_bench_20210104_20261125.parquet")
    cal_dts = bench["trade_date"].tolist()
    if end_cutoff is not None:
        cal_dts_cut = [d for d in cal_dts if d <= end_cutoff]
    else:
        cal_dts_cut = cal_dts

    p20 = w24.attach_pit_community_1d_burst(p20, cal_dts_cut, end_cutoff=end_cutoff or "2026-11-25")
    p20, ix_cols, ix_meta = w24.build_mechanism_interactions(p20)

    # Hygiene and friction variants (30bps default already in p20["net_ret"], verify against gross_ret)
    p20 = wfm.prepare_hygiene_and_net_ret(p20, fee_rt=0.0030)
    gr = p20["gross_ret"].to_numpy(float)
    p20["net_ret_30"] = p20["net_ret"].to_numpy(float)
    p20["net_ret_50"] = (1.0 + gr) * (1.0 - 0.0050) - 1.0
    p20["net_ret_80"] = (1.0 + gr) * (1.0 - 0.0080) - 1.0

    # Cold-day F06 adjustment variants (<40, <45, <50, <55)
    f6 = p20["s20cm_F06_inst_net_pos"].to_numpy(float)
    v20_sc = p20["v20_score"].to_numpy(float)
    mkt10 = p20["mkt10_zt_est_t1"].to_numpy(float)
    for cut in (40, 45, 50, 55):
        p20[f"v20_cold{cut}"] = np.where(mkt10 < float(cut), v20_sc - f6, v20_sc)

    # Build exact date-keyed daily MTM segments
    bar_lu = _build_needed_bar_lu(p20, cal_dts, end_cutoff=end_cutoff)
    dt_idx_full = {d: i for i, d in enumerate(cal_dts)}
    segs_30, segs_50, segs_80 = [], [], []
    for r in p20.itertuples(index=False):
        bi = dt_idx_full.get(r.buy_date)
        ei = dt_idx_full.get(r.exit_date)
        if bi is None or ei is None or ei <= bi:
            segs_30.append(()); segs_50.append(()); segs_80.append(())
            continue
        c6 = r.code
        b_adj = float(r.buy_px) if pd.notna(r.buy_px) else 1.0
        if b_adj <= 0:
            b_adj = 1.0
        prev_v, last_c = b_adj, b_adj
        head = []
        for t in range(bi, ei):
            bt = bar_lu.get((c6, cal_dts[t]))
            cur_c = (bt[1] * bt[4]) if (bt is not None and bt[1] > 0) else last_c
            if cur_c <= 0:
                cur_c = last_c
            head.append((cal_dts[t], cur_c / prev_v))
            prev_v, last_c = cur_c, cur_c
        ed_str = cal_dts[ei]
        segs_30.append(tuple(head + [(ed_str, (b_adj * (1.0 + float(r.net_ret_30))) / prev_v)]))
        segs_50.append(tuple(head + [(ed_str, (b_adj * (1.0 + float(r.net_ret_50))) / prev_v)]))
        segs_80.append(tuple(head + [(ed_str, (b_adj * (1.0 + float(r.net_ret_80))) / prev_v)]))
    del bar_lu
    gc.collect()
    pa.default_memory_pool().release_unused()

    p20["segs_30"] = segs_30
    p20["segs_50"] = segs_50
    p20["segs_80"] = segs_80

    # Clean atomic + past-1-week new factors pool (exclude s20cm_F*, ix_*, bar_*, target/leaky cols)
    base_dyn = w24.select_base_single_factors_for_dyn(p20)
    extra_clean = [c for c in meta["auc_cols"] + ["mkt10_zt_est_t1", "xtr_fix_monday", "xtr_fix_lock50_evo", "xtr_fix_mkt_seal80"] if c in p20.columns]
    atomic_cols = list(dict.fromkeys(base_dyn + extra_clean))
    # Verify zero leaky columns
    for c in atomic_cols:
        assert not c.startswith(("bar_", "ix_", "s20cm_", "v20_", "orig_")), f"Forbidden col in atomic_cols: {c}"
        assert c not in ("net_ret", "ret", "gross_ret", "exit_date", "exit_price", "hold_bars"), f"Leaky col: {c}"

    meta_out = {
        **meta,
        "ix_cols": ix_cols,
        "ix_meta": ix_meta,
        "atomic_cols": atomic_cols,
        "feat_clean_b": list(dict.fromkeys(meta["entry_num"] + meta["xtr_fixed"] + meta["auc_cols"])),
        "feat_union_cb_mech": list(dict.fromkeys(meta["entry_num"] + meta["xtr_fixed"] + meta["auc_cols"] + ix_cols)),
    }
    return p20, meta_out


def load_lean_v20_comb_context() -> dict:
    """
    Lean V20.0 6-strategy context (<1.2GB RSS) reproducing exact 278 trades / 69,134,091.51x 5Y / 611,729.55x WF.
    """
    wf_ctx = wf.load_v20_reference_context(WAVE1_DIR)
    raw_idx = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300 = {k: float(v) for k, v in raw_idx["sh000300"].items()}
    all_sh_dts = sorted(sh300.keys())
    cal_5y = [d for d in all_sh_dts if "2021-11-16" <= d <= "2026-11-16"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}

    other_parts = []
    trig_dts_other = {}
    for st in ("3to4", "high", "pry", "2to3", "1to2"):
        df = pd.read_parquet(f"{RD028_DIR}/pool_{st}_oldhot.parquet")
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["buy_date"] = df["buy_date"].astype(str).str[:10]
        df["exit_date"] = df["exit_date"].astype(str).str[:10]
        df["buy_price_val"] = df["buy_price"].astype(float)
        df["is_adj_px"] = False
        if st == "high":
            df["v51_cb_loss"] = (df["net_ret"].to_numpy(float) < -0.02) & (~df["dt_deferred"].to_numpy(bool))
        _, slot_df = m1.sim_standalone(st, df, np.zeros(len(df)), high_cb_mode="v51_exact")
        chosen = slot_df[slot_df["buy_date"].between("2021-11-16", "2026-11-16")].copy()
        chosen["score"] = [round(float(x), 1) for x in chosen["v20_score"]] if st == "1to2" else chosen["v20_score"]
        chosen["tier"] = [tpe.assign_physical_tier(st, sc) for sc in chosen["score"]]
        chosen["is_untrig"] = False
        trig_dts_other[st] = set(chosen["buy_date"])
        other_parts.append(chosen)
    other_pool5 = pd.concat(other_parts, ignore_index=True)

    p20_old = pd.read_parquet(f"{RD028_DIR}/pool_20cm_oldhot.parquet")
    p20_old["code"] = p20_old["code"].astype(str).str.zfill(6)
    p20_old["buy_date"] = p20_old["buy_date"].astype(str).str[:10]
    p20_old["exit_date"] = p20_old["exit_date"].astype(str).str[:10]
    p20_old["exit_hhmm"] = np.where(p20_old["exit_reason"].astype(str).str.contains("open|gap|tp"), 1030, 1500)
    p20_old["buy_price_val"] = p20_old["buy_px"].astype(float)
    p20_old["is_adj_px"] = True

    all_need_rows = pd.concat([other_pool5[["code", "buy_date", "exit_date"]], p20_old[["code", "buy_date", "exit_date"]]], ignore_index=True)
    bar_lu = _build_needed_bar_lu(all_need_rows, cal_5y)

    other_pool5["mtm_5y"] = m1.precompute_mtm_segments(other_pool5, cal_5y, idx_5y, bar_lu, is_20cm_adj=False)
    p20_old["mtm_5y"] = m1.precompute_mtm_segments(p20_old, cal_5y, idx_5y, bar_lu, is_20cm_adj=True)
    del bar_lu
    gc.collect()
    pa.default_memory_pool().release_unused()

    cols_keep = [
        "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
        "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig", "mtm_5y",
    ]
    other_pool5 = other_pool5[cols_keep].copy()

    # Lean untriggered conditional orders (no 3.7GB old_hot merge!)
    PARTC_DIR = m1.PARTC_DIR
    PARTA_DIR = m1.PARTA_DIR
    V11_DIR = m1.V11_DIR
    pool6_csv = pd.concat([
        tpe.load_strategy_csv("3to4", f"{PARTC_DIR}/ledger_3to4_v41_clean.csv", "2021-11-16", "2026-11-16"),
        tpe.load_strategy_csv("high", f"{PARTC_DIR}/ledger_high_v51_clean.csv", "2021-11-16", "2026-11-16"),
        tpe.load_strategy_csv("pry", f"{PARTC_DIR}/ledger_pry_v21_ss165_clean.csv", "2021-11-16", "2026-11-16"),
        tpe.load_strategy_csv("2to3", f"{PARTC_DIR}/ledger_2to3_v21_opt_std90_clean.csv", "2021-11-16", "2026-11-16"),
        tpe.load_strategy_csv("1to2", f"{PARTA_DIR}/ledger_1to2_v20_cand.csv", "2021-11-16", "2026-11-16"),
        tpe.load_strategy_csv("20cm", f"{V11_DIR}/final_v11_ledger.csv", "2021-11-16", "2026-11-16"),
    ], ignore_index=True)
    ut = tpe.build_untriggered_baseline_pool(pool6_csv, "2021-11-16", "2026-11-16")
    ut_parts = []
    for st_u in ("3to4", "high", "1to2"):
        sub_u = ut[(ut["strategy"] == st_u) & (~ut["buy_date"].isin(trig_dts_other[st_u]))].copy()
        thr_u = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[st_u]
        sub_u = sub_u[sub_u["score"] >= thr_u].copy()
        if not sub_u.empty:
            sub_u["tier"] = [tpe.assign_physical_tier(st_u, sc) for sc in sub_u["score"]]
            sub_u = sub_u.sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
            ut_parts.append(sub_u)
    ut_final = pd.concat(ut_parts, ignore_index=True) if ut_parts else pd.DataFrame()
    if not ut_final.empty:
        ut_final["is_untrig"] = True
        ut_final["net_ret"] = 0.0
        ut_final["buy_price_val"] = np.nan
        ut_final["is_adj_px"] = False
        ut_final = ut_final[
            ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
             "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig"]
        ]

    p20_map = {}
    for r in p20_old.itertuples(index=False):
        p20_map[(r.buy_date, r.code)] = (r.mtm_5y, float(r.buy_price_val), int(r.exit_hhmm), float(r.net_ret))

    return {
        "wf_ctx": wf_ctx,
        "cal_5y": cal_5y,
        "idx_5y": idx_5y,
        "sh300": sh300,
        "all_sh_dts": all_sh_dts,
        "other_pool5": other_pool5,
        "ut_final": ut_final,
        "p20_old": p20_old,
        "p20_map": p20_map,
    }


def _map_segs_to_wf_idx(slot_df: pd.DataFrame, segs_col: str, wf_idx: dict[str, int]) -> list[tuple]:
    return [
        tuple((wf_idx[d], float(m)) for d, m in segs if d in wf_idx)
        for segs in slot_df[segs_col]
    ]


def evaluate_variant_fast(
    name: str,
    family: str,
    df_scored: pd.DataFrame,
    score_col: str,
    threshold: float | str,
    bench_df: pd.DataFrame,
    wf_cands: pd.DataFrame,
    veto_mask: Optional[np.ndarray] = None,
    perm_n: int = 0,
    v20_comb_ctx: Optional[dict] = None,
    v20_base_comb: Optional[dict] = None,
) -> dict:
    """
    Fast, exact daily MTM evaluation across 30bps/50bps/80bps + >=2yi liquidity + optional perm & V20 comb.
    Returns summary dict + daily MTM return vector `dr_30` (for CSCV PBO, DSR, paired t-test).
    """
    d = df_scored.copy()
    if veto_mask is not None:
        d["can_buy_hygiene"] = d["can_buy_hygiene"].to_numpy(bool) & (~np.asarray(veto_mask, dtype=bool))
    pass_df, slot_df = wfm.select_single_slot_trades(d, score_col=score_col, threshold=threshold, wf_only=True)
    if not slot_df.empty:
        slot_df["score"] = slot_df[score_col]

    b = bench_df[bench_df["trade_date"].between(WF_START_DT, WF_END_DT)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = b["trade_date"].tolist()
    dt_idx = {dt: i for i, dt in enumerate(cal_dts)}
    csi_arr = b["csi300_daily_ret"].to_numpy(float)
    ew_arr = b["alla_ew_daily_ret"].to_numpy(float)

    def _run_friction(sl_df: pd.DataFrame, ret_col: str, segs_col: str) -> tuple[dict, np.ndarray]:
        if sl_df.empty:
            dr = np.zeros(len(cal_dts), dtype=float)
            wins = {
                wn: wfm._calc_one_window(sl_df, None, dr, cal_dts, dt_idx, csi_arr, ew_arr, s, e)
                for wn, s, e in [
                    ("FULL_WF", WF_START_DT, WF_END_DT),
                    ("Y2023", WF_START_DT, "2023-12-31"),
                    ("Y2024", "2024-01-01", "2024-12-31"),
                    ("Y2025", "2025-01-01", "2025-12-31"),
                    ("Y2025_2026", "2025-01-01", WF_END_DT),
                    ("Y2026", "2026-01-01", WF_END_DT),
                    ("Y2026H2", "2026-07-01", WF_END_DT),
                ]
            }
            return wins, dr
        sl = sl_df.copy()
        sl["net_ret"] = sl[ret_col].to_numpy(float)
        sl["_mtm_wf"] = _map_segs_to_wf_idx(sl, segs_col, dt_idx)
        dr, mtm_diff = wfm.build_daily_mtm_returns(sl, cal_dts, mtm_col="_mtm_wf")
        tr_nav = float(np.prod(1.0 + sl["net_ret"].to_numpy(float)))
        assert mtm_diff / max(1.0, tr_nav) < 1e-6, f"{name} ({ret_col}) MTM diff={mtm_diff}, tr_nav={tr_nav}"
        wins = {
            wn: wfm._calc_one_window(sl, None, dr, cal_dts, dt_idx, csi_arr, ew_arr, s, e)
            for wn, s, e in [
                ("FULL_WF", WF_START_DT, WF_END_DT),
                ("Y2023", WF_START_DT, "2023-12-31"),
                ("Y2024", "2024-01-01", "2024-12-31"),
                ("Y2025", "2025-01-01", "2025-12-31"),
                ("Y2025_2026", "2025-01-01", WF_END_DT),
                ("Y2026", "2026-01-01", WF_END_DT),
                ("Y2026H2", "2026-07-01", WF_END_DT),
            ]
        }
        return wins, dr

    w30, dr30 = _run_friction(slot_df, "net_ret_30", "segs_30")
    w50, _ = _run_friction(slot_df, "net_ret_50", "segs_50")
    w80, _ = _run_friction(slot_df, "net_ret_80", "segs_80")

    # >= 2亿 liquidity subset (causal re-run of single-slot selection after >= 2亿 filter!)
    d_liq = d.copy()
    d_liq["can_buy_hygiene"] = d_liq["can_buy_hygiene"].to_numpy(bool) & (d_liq["sd_amount_yi_t1"].fillna(0.0).to_numpy(float) >= 2.0)
    _, slot_liq = wfm.select_single_slot_trades(d_liq, score_col=score_col, threshold=threshold, wf_only=True)
    w_liq, _ = _run_friction(slot_liq, "net_ret_30", "segs_30")

    perm = wfm.perm_test_trading_days(slot_df, wf_cands, WF_START_DT, WF_END_DT, n_perm=perm_n, seed=20261126) if perm_n > 0 else None
    comb = w23.eval_v20_combined_replacement(v20_comb_ctx, slot_df, wf_start_dt=WF_START_DT, end_dt=WF_END_DT) if v20_comb_ctx is not None else None

    rets = slot_df["net_ret_30"].to_numpy(float) if not slot_df.empty else np.array([])
    bl_cnt = int(np.sum(rets <= -0.07)) if len(rets) else 0
    bl_pct = round(bl_cnt / max(1, len(rets)) * 100.0, 2)

    fw = w30["FULL_WF"]
    y2526 = w30["Y2025_2026"]
    y26 = w30["Y2026"]
    h2 = w30["Y2026H2"]

    row = {
        "variant": name,
        "family": family,
        "n_pass": int(len(pass_df)),
        "n_wf": fw["n"],
        "wr_wf": fw["wr_pct"],
        "plr_wf": fw["plr"],
        "mean_wf": fw["mean_pct"],
        "nav_wf": fw["nav"],
        "ex3_wf": fw["ex_top3_nav"],
        "ex5_wf": fw["ex_top5_nav"],
        "mdd_wf": fw["daily_mdd_pct"],
        "sharpe_wf": fw["daily_sharpe"],
        "calmar_wf": fw["daily_calmar"],
        "excess_csi_wf": fw["excess_csi300_pp"],
        "excess_ew_wf": fw["excess_alla_ew_pp"],
        "big_loss_m7_pct": bl_pct,
        "nav_23": w30["Y2023"]["nav"],
        "nav_24": w30["Y2024"]["nav"],
        "nav_25": w30["Y2025"]["nav"],
        "n_2526": y2526["n"],
        "wr_2526": y2526["wr_pct"],
        "nav_2526": y2526["nav"],
        "ex5_2526": y2526["ex_top5_nav"],
        "mdd_2526": y2526["daily_mdd_pct"],
        "sharpe_2526": y2526["daily_sharpe"],
        "n_26": y26["n"],
        "wr_26": y26["wr_pct"],
        "nav_26": y26["nav"],
        "n_26h2": h2["n"],
        "wr_26h2": h2["wr_pct"],
        "nav_26h2": h2["nav"],
        "mdd_26h2": h2["daily_mdd_pct"],
        # Slippage 50bps & 80bps
        "nav_50bps": w50["FULL_WF"]["nav"],
        "ex5_50bps": w50["FULL_WF"]["ex_top5_nav"],
        "sharpe_50bps": w50["FULL_WF"]["daily_sharpe"],
        "nav_2526_50bps": w50["Y2025_2026"]["nav"],
        "nav_80bps": w80["FULL_WF"]["nav"],
        "ex5_80bps": w80["FULL_WF"]["ex_top5_nav"],
        "sharpe_80bps": w80["FULL_WF"]["daily_sharpe"],
        "nav_2526_80bps": w80["Y2025_2026"]["nav"],
        # >=2yi liquidity
        "n_liq2y": w_liq["FULL_WF"]["n"],
        "wr_liq2y": w_liq["FULL_WF"]["wr_pct"],
        "nav_liq2y": w_liq["FULL_WF"]["nav"],
        "sharpe_liq2y": w_liq["FULL_WF"]["daily_sharpe"],
        "nav_2526_liq2y": w_liq["Y2025_2026"]["nav"],
    }
    if perm is not None:
        row["perm_sd_p"] = perm["same_day_p_nav"]
        row["perm_any_p"] = perm["any_cand_day_p_nav"]
    if comb is not None:
        cw, c2526, ch2 = comb["FULL_WF"], comb["Y2025_2026"], comb["Y2026H2"]
        row["comb_wf_nav"] = cw["nav"]
        row["comb_wf_mdd"] = cw["daily_mdd_pct"]
        row["comb_wf_sharpe"] = cw["daily_sharpe"]
        row["comb_wf_n20"] = cw["n_20cm"]
        row["comb_2526_nav"] = c2526["nav"]
        row["comb_26h2_nav"] = ch2["nav"]
        if v20_base_comb is not None:
            row["comb_wf_nav_ratio"] = round(cw["nav"] / max(1e-9, v20_base_comb["FULL_WF"]["nav"]), 4)
            row["comb_2526_nav_ratio"] = round(c2526["nav"] / max(1e-9, v20_base_comb["Y2025_2026"]["nav"]), 4)
            row["comb_26h2_nav_ratio"] = round(ch2["nav"] / max(1e-9, v20_base_comb["Y2026H2"]["nav"]), 4)

    return {
        "row": row,
        "dr30": dr30,
        "slot_df": slot_df,
        "pass_df": pass_df,
        "windows_30bps": w30,
        "windows_50bps": w50,
        "windows_80bps": w80,
        "windows_liq2y": w_liq,
        "perm": perm,
        "comb": comb,
    }


def compute_paired_t_and_dsr(
    dr_var: np.ndarray,
    dr_base: np.ndarray,
    slot_var: pd.DataFrame,
    slot_base: pd.DataFrame,
    n_trials_grid: int,
    grid_daily_srs: list[float],
) -> dict:
    """
    Compute exact daily MTM paired t-test vs baseline + trade-level overlap comparison
    + Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014) across real N_trials_grid & conservative N.
    """
    diff = dr_var - dr_base
    T = len(diff)
    sd_diff = float(np.std(diff, ddof=1)) if T > 1 else 0.0
    t_daily = float(np.mean(diff) / (sd_diff / math.sqrt(T))) if sd_diff > 1e-12 else 0.0
    p_daily_1s = float(stats.t.sf(t_daily, df=T - 1)) if T > 1 else 1.0
    p_daily_2s = float(2.0 * stats.t.sf(abs(t_daily), df=T - 1)) if T > 1 else 1.0

    # Active-days paired t-test (days where either variant or baseline holds a position)
    act = (dr_var != 0.0) | (dr_base != 0.0)
    na = int(act.sum())
    if na >= 10 and float(np.std(diff[act], ddof=1)) > 1e-12:
        t_act = float(np.mean(diff[act]) / (np.std(diff[act], ddof=1) / math.sqrt(na)))
        p_act_2s = float(2.0 * stats.t.sf(abs(t_act), df=na - 1))
    else:
        t_act, p_act_2s = 0.0, 1.0

    # Deflated Sharpe Ratio (exact daily MTM returns, T=936 days)
    sd_v = float(np.std(dr_var, ddof=1)) if T > 1 else 0.0
    sr_daily = float(np.mean(dr_var) / sd_v) if sd_v > 1e-12 else 0.0
    sr_ann = sr_daily * math.sqrt(TRD_DAYS_YEAR)
    sk = float(stats.skew(dr_var, bias=False)) if T > 2 else 0.0
    ku = max(1.0, float(stats.kurtosis(dr_var, fisher=False, bias=False))) if T > 3 else 3.0
    den = math.sqrt(max(1e-12, 1.0 - sk * sr_daily + ((ku - 1.0) / 4.0) * (sr_daily ** 2)))

    gm = 0.5772156649
    # Cross-sectional std of daily SR across grid trials (Bailey & Lopez de Prado 2014 Eq. 8)
    sr_grid_arr = np.asarray(grid_daily_srs, dtype=float)
    std_sr_grid = float(np.std(sr_grid_arr, ddof=1)) if len(sr_grid_arr) > 2 else (1.0 / math.sqrt(max(1, T - 1)))

    def _dsr_for(n_tr: int, std_sr: float) -> float:
        if n_tr <= 1:
            sr0 = 0.0
        else:
            sr0 = std_sr * ((1.0 - gm) * stats.norm.ppf(1.0 - 1.0 / n_tr) + gm * stats.norm.ppf(1.0 - 1.0 / (n_tr * math.e)))
        z = (sr_daily - sr0) * math.sqrt(max(1, T - 1)) / den
        return round(float(stats.norm.cdf(z)), 4)

    return {
        "t_daily_mtm_vs_base": round(t_daily, 3),
        "p_daily_mtm_1s": round(p_daily_1s, 4),
        "p_daily_mtm_2s": round(p_daily_2s, 4),
        "t_active_days_vs_base": round(t_act, 3),
        "p_active_days_2s": round(p_act_2s, 4),
        "n_active_union_days": na,
        "daily_sr": round(sr_daily, 5),
        "ann_sr": round(sr_ann, 3),
        "daily_skew": round(sk, 3),
        "daily_kurt": round(ku, 3),
        "dsr_exact_grid_N": _dsr_for(n_trials_grid, std_sr_grid),
        "dsr_null_grid_N": _dsr_for(n_trials_grid, 1.0 / math.sqrt(max(1, T - 1))),
        "dsr_null_N500": _dsr_for(500, 1.0 / math.sqrt(max(1, T - 1))),
        "dsr_null_N2000": _dsr_for(2000, 1.0 / math.sqrt(max(1, T - 1))),
        "n_trials_grid": int(n_trials_grid),
        "grid_sr_std_daily": round(std_sr_grid, 5),
    }


def compute_cscv_pbo(dr_matrix: np.ndarray, names: list[str], n_blocks: int = 10) -> dict:
    """
    Combinatorially Symmetric Cross-Validation (Bailey et al. 2017) on exact daily MTM return matrix (T x N).
    Splits T days into S=10 chronological blocks -> C(10, 5) = 252 balanced IS/OOS splits.
    """
    T, N = dr_matrix.shape
    if N < 2 or T < n_blocks * 10:
        return {"pbo_pct": 100.0, "n_models": int(N), "n_splits": 0}

    gs = T // n_blocks
    blocks = [list(range(i * gs, (i + 1) * gs if i < n_blocks - 1 else T)) for i in range(n_blocks)]
    omegas = []
    logits = []
    is_best_names = []
    oos_ranks_of_is_best = []
    for te_blocks in itertools.combinations(range(n_blocks), n_blocks // 2):
        te_set = set(te_blocks)
        tri = [x for k in range(n_blocks) if k not in te_set for x in blocks[k]]
        tei = [x for k in range(n_blocks) if k in te_set for x in blocks[k]]
        rt = dr_matrix[tri]
        re = dr_matrix[tei]
        st_sd = rt.std(axis=0, ddof=1)
        se_sd = re.std(axis=0, ddof=1)
        st = np.divide(rt.mean(axis=0), st_sd, out=np.zeros(N), where=st_sd > 1e-12)
        se = np.divide(re.mean(axis=0), se_sd, out=np.zeros(N), where=se_sd > 1e-12)
        b = int(np.argmax(st))
        # Relative rank of IS-winner in OOS: higher rank = better; omega = fraction of models strictly worse or rank/(N+1)
        # Bailey et al.: omega_bar = rank(se[b]) / (N + 1); logit < 0 <=> omega_bar < 0.5 <=> frac_better > 0.5
        n_better = float(np.sum(se > se[b]))
        n_ties = float(np.sum(se == se[b])) - 1.0
        frac_better = (n_better + 0.5 * max(0.0, n_ties)) / N
        omega_bar = 1.0 - frac_better
        omega_clipped = min(1.0 - 1e-6, max(1e-6, omega_bar))
        omegas.append(frac_better)
        logits.append(math.log(omega_clipped / (1.0 - omega_clipped)))
        is_best_names.append(names[b])
        oos_ranks_of_is_best.append(omega_bar)

    pbo_pct = float(np.mean(np.array(omegas) > 0.50) * 100.0)
    return {
        "n_models": int(N),
        "n_blocks": int(n_blocks),
        "n_splits": int(len(omegas)),
        "pbo_pct": round(pbo_pct, 2),
        "median_oos_pct_rank": round(float(np.median(oos_ranks_of_is_best) * 100.0), 2),
        "mean_logit": round(float(np.mean(logits)), 3),
        "is_best_top3_freq": pd.Series(is_best_names).value_counts().head(5).to_dict(),
    }


# =============================================================================
# MODULE 2 & 3: STRICTLY CAUSAL (exit_date < t) 3-WAY, 4-WAY & SHALLOW TREES
# =============================================================================

def _ols_residual_t_stat(u: np.ndarray, target_col: np.ndarray, controls: list[np.ndarray], g_inv: np.ndarray, G: int) -> float:
    """Cluster-robust t-stat of `target_col` after orthogonalizing against [1, controls...]."""
    X_ctrl = np.column_stack([np.ones(len(u), dtype=np.float64)] + [c.astype(np.float64) for c in controls])
    coef, _, _, _ = np.linalg.lstsq(X_ctrl, target_col.astype(np.float64), rcond=None)
    resid = target_col.astype(np.float64) - X_ctrl @ coef
    if float(np.std(resid)) < 1e-8:
        return 0.0
    return float(w24._batch_cluster_t_stats(u, resid[:, None], g_inv, G)[0])


def fit_causal_3way_and_4way_rules(
    X_tr: np.ndarray,
    y_ret: np.ndarray,
    y_win: np.ndarray,
    day_ids: np.ndarray,
    feat_names: list[str],
    top_base_k: int = 25,
    max_base_corr: float = 0.70,
    min_leaf_3way: int = 25,
    min_pct_3way: float = 0.05,
    min_t_3way: float = 2.5,
    min_syn_t_3way: float = 1.5,
    min_cond_t_3way: float = 1.1,
    min_leaf_4way: int = 20,
    min_t_4way: float = 2.8,
    min_syn_t_4way: float = 1.5,
    max_rules_keep: int = 24,
    enable_4way: bool = True,
) -> dict:
    """
    Strictly inside exit_date < t:
      1. Screen orthogonal Top `top_base_k` (25) atomic + past-1w new factors.
      2. Discretize each factor into {Hi (> thr), Lo (<= thr)} strictly using training medians/means.
      3. Exhaustively test all C(25, 3) * 8 = 18,400 3-way AND gates (`A & B & C`):
           - Require leaf >= max(min_leaf_3way, int(min_pct_3way * M))
           - Require |t_cluster(u, ABC)| >= min_t_3way
           - Require strict positive synergy (or negative minefield):
             a) mean_ret(ABC) & u(ABC) strictly outperform ALL 1-way (A,B,C) & ALL 2-way (AB,AC,BC)
             b) Pure 3-way ANOVA residual t_stat (controlling for 1 + A + B + C + AB + AC + BC) >= min_syn_t_3way in same direction
             c) Conditional cluster t-stat inside EACH sub-2-way (ABC vs AB&~C, AC&~B, BC&~A) >= min_cond_t_3way in same direction
      4. Optionally expand Top seed 3-way gates (cnt >= 40) with 4th orthogonal factor D -> 4-way (`A & B & C & D`):
           - Require leaf >= min_leaf_4way (20), |t_cluster| >= min_t_4way
           - Strictly outperform ALL four 3-way subsets (ABC, ABD, ACD, BCD) & conditional t(ABCD vs ABC&~D) >= min_syn_t_4way
    """
    M, F = X_tr.shape
    mu0 = float(np.mean(y_ret))
    wr0 = float(np.mean(y_win))
    sd_r = max(1e-5, float(np.std(y_ret, ddof=1))) if M > 1 else 0.05
    u_all = 0.6 * (y_ret - mu0) / sd_r + 0.4 * (y_win - wr0) / 0.25
    _, g_inv = np.unique(day_ids, return_inverse=True)
    G = int(g_inv.max()) + 1
    min_valid_n = max(35, int(0.45 * M))

    if M < 50 or G < 5 or F < 3:
        return {"selected_base": [], "rules_3way": [], "rules_4way": [], "X_3way": np.empty((M, 0)), "X_4way": np.empty((M, 0))}

    fin_mask = np.isfinite(X_tr)
    cnt_valid = fin_mask.sum(axis=0)
    col_meds = np.nanmedian(X_tr, axis=0)
    col_meds = np.where(np.isfinite(col_meds), col_meds, 0.0)
    X_imp = np.where(fin_mask, X_tr, col_meds[None, :])
    col_stds = np.std(X_imp, axis=0)
    ok_idx = np.where((cnt_valid >= min_valid_n) & (col_stds > 1e-9))[0]

    if len(ok_idx) < 3:
        return {"selected_base": [], "rules_3way": [], "rules_4way": [], "X_3way": np.empty((M, 0)), "X_4way": np.empty((M, 0))}

    t_base = w24._batch_cluster_t_stats(u_all, X_imp[:, ok_idx], g_inv, G)
    order = np.argsort(-np.abs(t_base), kind="mergesort")

    min_cell_1w = max(min_leaf_3way, int(0.08 * M))
    sel_base = []
    for oi in order:
        j = int(ok_idx[oi])
        xj = X_imp[:, j]
        ok_c = True
        for s in sel_base:
            r = abs(float(np.corrcoef(xj, X_imp[:, s["col_idx"]])[0, 1]))
            if r > max_base_corr:
                ok_c = False
                break
        if not ok_c:
            continue
        med_j = float(col_meds[j])
        n_gt_med = int(np.sum(xj > med_j))
        if n_gt_med >= min_cell_1w and (M - n_gt_med) >= min_cell_1w:
            thr_j = med_j
        else:
            mean_j = float(np.mean(xj))
            n_gt_mean = int(np.sum(xj > mean_j))
            if n_gt_mean >= min_cell_1w and (M - n_gt_mean) >= min_cell_1w:
                thr_j = mean_j
            else:
                continue
        sel_base.append({
            "col_idx": j,
            "name": feat_names[j],
            "med": med_j,
            "thr": thr_j,
            "t_1w": float(t_base[oi]),
        })
        if len(sel_base) >= top_base_k:
            break

    K = len(sel_base)
    if K < 3:
        return {"selected_base": sel_base, "rules_3way": [], "rules_4way": [], "X_3way": np.empty((M, 0)), "X_4way": np.empty((M, 0))}

    # Build K*(2 states) boolean predicate matrix: state 0 = Lo (<= thr), state 1 = Hi (> thr)
    P_bool = np.empty((K, 2, M), dtype=bool)
    P_f = np.empty((K, 2, M), dtype=np.float64)
    u_1w = np.empty((K, 2), dtype=np.float64)
    r_1w = np.empty((K, 2), dtype=np.float64)
    for k_i, sb in enumerate(sel_base):
        j = sb["col_idx"]
        xv = np.where(np.isfinite(X_tr[:, j]), X_tr[:, j], sb["med"])
        hi = xv > sb["thr"]
        lo = ~hi
        P_bool[k_i, 0] = lo
        P_bool[k_i, 1] = hi
        P_f[k_i, 0] = lo.astype(np.float64)
        P_f[k_i, 1] = hi.astype(np.float64)
        u_1w[k_i, 0] = float(np.mean(u_all[lo]))
        u_1w[k_i, 1] = float(np.mean(u_all[hi]))
        r_1w[k_i, 0] = float(np.mean(y_ret[lo]))
        r_1w[k_i, 1] = float(np.mean(y_ret[hi]))

    min_cell_3w = max(min_leaf_3way, int(min_pct_3way * M))

    # Precompute 2-way masks & stats for all a < b
    pair_masks = {}
    pair_stats = {}
    for a in range(K):
        for sa in (0, 1):
            ma = P_bool[a, sa]
            for b in range(a + 1, K):
                for sb in (0, 1):
                    mab = ma & P_bool[b, sb]
                    cnt2 = int(mab.sum())
                    if cnt2 >= min_cell_3w:
                        pair_masks[(a, sa, b, sb)] = mab
                        pair_stats[(a, sa, b, sb)] = (float(np.mean(u_all[mab])), float(np.mean(y_ret[mab])))

    # Generate all 3-way AND cells hitting >= min_cell_3w and non-trivial (M - cnt >= min_cell_3w)
    # Fast vectorization: for each (a, sa, b, sb) passing min_cell_3w, intersect with P_bool[b+1:, :, :]
    cand_cols = []
    cand_meta = []
    for (a, sa, b, sb), mab in pair_masks.items():
        if b >= K - 1:
            continue
        # Intersect mab (M,) with P_bool[b+1:, :, :] -> shape ((K-1-b)*2, M)
        rem_b = P_bool[b + 1 :].reshape(-1, M)
        inter = rem_b & mab[None, :]
        cnts = inter.sum(axis=1)
        ok_m = (cnts >= min_cell_3w) & ((M - cnts) >= min_cell_3w)
        if not np.any(ok_m):
            continue
        u_2_ab, r_2_ab = pair_stats[(a, sa, b, sb)]
        for idx_r in np.where(ok_m)[0]:
            dc, sc = divmod(int(idx_r), 2)
            c = b + 1 + dc
            st_ac = pair_stats.get((a, sa, c, sc))
            st_bc = pair_stats.get((b, sb, c, sc))
            if st_ac is None or st_bc is None:
                continue
            vec_bool = inter[idx_r]
            u3 = float(np.mean(u_all[vec_bool]))
            r3 = float(np.mean(y_ret[vec_bool]))
            max_u_sub = max(u_1w[a, sa], u_1w[b, sb], u_1w[c, sc], u_2_ab, st_ac[0], st_bc[0])
            min_u_sub = min(u_1w[a, sa], u_1w[b, sb], u_1w[c, sc], u_2_ab, st_ac[0], st_bc[0])
            max_r_sub = max(r_1w[a, sa], r_1w[b, sb], r_1w[c, sc], r_2_ab, st_ac[1], st_bc[1])
            min_r_sub = min(r_1w[a, sa], r_1w[b, sb], r_1w[c, sc], r_2_ab, st_ac[1], st_bc[1])
            is_pos = (u3 > max_u_sub + 1e-6) and (r3 > max_r_sub + 1e-6)
            is_neg = (u3 < min_u_sub - 1e-6) and (r3 < min_r_sub - 1e-6)
            if not (is_pos or is_neg):
                continue
            cand_cols.append(vec_bool.astype(np.float64))
            cand_meta.append((a, sa, b, sb, c, sc, int(cnts[idx_r]), u3, r3, 1 if is_pos else -1))

    rules_3way = []
    X_3way = np.empty((M, 0), dtype=np.float64)
    if cand_cols:
        C_mat = np.column_stack(cand_cols)
        t_3w = w24._batch_cluster_t_stats(u_all, C_mat, g_inv, G)
        # Filter by |t_3w| >= min_t_3way & matching sign, sort deterministically before exact OLS ANOVA check
        strong_idx = [
            i for i, t_v in enumerate(t_3w)
            if (cand_meta[i][9] == 1 and t_v >= min_t_3way) or (cand_meta[i][9] == -1 and t_v <= -min_t_3way)
        ]
        strong_idx.sort(key=lambda i: (-abs(t_3w[i]), cand_meta[i][0], cand_meta[i][2], cand_meta[i][4], cand_meta[i][1], cand_meta[i][3], cand_meta[i][5]))

        # Exact saturated 3-way ANOVA synergy + conditional sub-2-way check on top 120 strong candidates
        surv_3w = []
        for idx_c in strong_idx[:120]:
            a, sa, b, sb, c, sc, cnt3, u3, r3, sgn_dir = cand_meta[idx_c]
            v3 = C_mat[:, idx_c]
            va, vb, vc = P_f[a, sa], P_f[b, sb], P_f[c, sc]
            vab = pair_masks[(a, sa, b, sb)].astype(np.float64)
            vac = pair_masks[(a, sa, c, sc)].astype(np.float64)
            vbc = pair_masks[(b, sb, c, sc)].astype(np.float64)

            t_anova = _ols_residual_t_stat(u_all, v3, [va, vb, vc, vab, vac, vbc], g_inv, G)
            if sgn_dir == 1 and t_anova < min_syn_t_3way:
                continue
            if sgn_dir == -1 and t_anova > -min_syn_t_3way:
                continue

            # Conditional check inside each sub-2-way: ABC vs AB&~C, AC&~B, BC&~A
            cond_ts = []
            ok_cond = True
            for m2 in (pair_masks[(a, sa, b, sb)], pair_masks[(a, sa, c, sc)], pair_masks[(b, sb, c, sc)]):
                sub_z = (v3[m2] > 0.5).astype(np.float64)
                if len(sub_z) - int(sub_z.sum()) < 8:
                    ok_cond = False
                    break
                _, g_sub = np.unique(day_ids[m2], return_inverse=True)
                G_sub = int(g_sub.max()) + 1
                if G_sub < 5:
                    ok_cond = False
                    break
                tc = float(w24._batch_cluster_t_stats(u_all[m2], sub_z[:, None], g_sub, G_sub)[0])
                if (sgn_dir == 1 and tc < min_cond_t_3way) or (sgn_dir == -1 and tc > -min_cond_t_3way):
                    ok_cond = False
                    break
                cond_ts.append(tc)
            if not ok_cond:
                continue

            s_lab = lambda k_i, st_i: f"{sel_base[k_i]['name']}({'Hi' if st_i==1 else 'Lo'})"
            rname = f"3W_{'POS' if sgn_dir==1 else 'NEG'}__{s_lab(a,sa)}__AND__{s_lab(b,sb)}__AND__{s_lab(c,sc)}"
            surv_3w.append({
                "name": rname,
                "order": 3,
                "dir": "POS" if sgn_dir == 1 else "NEG",
                "terms": [
                    {"col_idx": sel_base[a]["col_idx"], "name": sel_base[a]["name"], "med": sel_base[a]["med"], "thr": sel_base[a]["thr"], "state": sa},
                    {"col_idx": sel_base[b]["col_idx"], "name": sel_base[b]["name"], "med": sel_base[b]["med"], "thr": sel_base[b]["thr"], "state": sb},
                    {"col_idx": sel_base[c]["col_idx"], "name": sel_base[c]["name"], "med": sel_base[c]["med"], "thr": sel_base[c]["thr"], "state": sc},
                ],
                "cnt": cnt3,
                "support_pct": round(cnt3 / M * 100.0, 2),
                "mean_ret_pct": round(r3 * 100.0, 2),
                "win_rate_pct": round(float(np.mean(y_win[v3 > 0.5]) * 100.0), 2),
                "crash_m7_pct": round(float(np.mean(y_ret[v3 > 0.5] <= -0.07) * 100.0), 2),
                "t_cluster": round(float(t_3w[idx_c]), 3),
                "t_anova_synergy": round(float(t_anova), 3),
                "min_cond_t": round(float(min(abs(x) for x in cond_ts)), 3),
                "vec": v3,
                "abc_idx": (a, sa, b, sb, c, sc),
            })

        # Keep balanced top positive & negative rules (up to max_rules_keep)
        pos_3 = [r for r in surv_3w if r["dir"] == "POS"][: max_rules_keep // 2 + 4]
        neg_3 = [r for r in surv_3w if r["dir"] == "NEG"][: max_rules_keep // 2 + 4]
        chosen_3 = (pos_3 + neg_3)[:max_rules_keep]
        if chosen_3:
            X_3way = np.column_stack([r["vec"] for r in chosen_3])
            rules_3way = [{k: v for k, v in r.items() if k != "vec"} for r in chosen_3]

    # --- MODULE 3: 4-Way Forward Expansion from Top High-Frequency 3-Way Seeds ---
    rules_4way = []
    X_4way = np.empty((M, 0), dtype=np.float64)
    if enable_4way and rules_3way:
        # Select seeds with cnt >= max(35, min_leaf_4way + 15)
        seeds = [r for r in surv_3w if r["cnt"] >= max(35, min_leaf_4way + 15)][:20]
        cand4_cols, cand4_meta = [], []
        seen_4keys = set()
        for r3_obj in seeds:
            a, sa, b, sb, c, sc = r3_obj["abc_idx"]
            m_abc = r3_obj["vec"] > 0.5
            sgn_dir = 1 if r3_obj["dir"] == "POS" else -1
            u_abc = float(np.mean(u_all[m_abc]))
            r_abc = float(np.mean(y_ret[m_abc]))
            used_k = {a, b, c}
            for d in range(K):
                if d in used_k:
                    continue
                for sd_s in (0, 1):
                    key4 = tuple(sorted([(a, sa), (b, sb), (c, sc), (d, sd_s)]))
                    if key4 in seen_4keys:
                        continue
                    seen_4keys.add(key4)
                    m_abcd = m_abc & P_bool[d, sd_s]
                    cnt4 = int(m_abcd.sum())
                    if cnt4 < min_leaf_4way or (M - cnt4) < min_leaf_4way:
                        continue
                    # Also check the other three 3-way subsets exist and compare
                    m_abd = P_bool[a, sa] & P_bool[b, sb] & P_bool[d, sd_s]
                    m_acd = P_bool[a, sa] & P_bool[c, sc] & P_bool[d, sd_s]
                    m_bcd = P_bool[b, sb] & P_bool[c, sc] & P_bool[d, sd_s]
                    u_subs = [u_abc, float(np.mean(u_all[m_abd])), float(np.mean(u_all[m_acd])), float(np.mean(u_all[m_bcd]))]
                    r_subs = [r_abc, float(np.mean(y_ret[m_abd])), float(np.mean(y_ret[m_acd])), float(np.mean(y_ret[m_bcd]))]
                    u4 = float(np.mean(u_all[m_abcd]))
                    r4 = float(np.mean(y_ret[m_abcd]))
                    if sgn_dir == 1 and not (u4 > max(u_subs) + 1e-6 and r4 > max(r_subs) + 1e-6):
                        continue
                    if sgn_dir == -1 and not (u4 < min(u_subs) - 1e-6 and r4 < min(r_subs) - 1e-6):
                        continue
                    # Conditional t-test inside m_abc: ABCD vs ABC&~D
                    sub_z = m_abcd[m_abc].astype(np.float64)
                    if len(sub_z) - int(sub_z.sum()) < 8:
                        continue
                    _, g_sub = np.unique(day_ids[m_abc], return_inverse=True)
                    G_sub = int(g_sub.max()) + 1
                    if G_sub < 5:
                        continue
                    t_4vs3 = float(w24._batch_cluster_t_stats(u_all[m_abc], sub_z[:, None], g_sub, G_sub)[0])
                    if (sgn_dir == 1 and t_4vs3 < min_syn_t_4way) or (sgn_dir == -1 and t_4vs3 > -min_syn_t_4way):
                        continue
                    cand4_cols.append(m_abcd.astype(np.float64))
                    cand4_meta.append((key4, cnt4, u4, r4, sgn_dir, t_4vs3))

        if cand4_cols:
            C4_mat = np.column_stack(cand4_cols)
            t_4w = w24._batch_cluster_t_stats(u_all, C4_mat, g_inv, G)
            ok4 = [
                i for i, tv in enumerate(t_4w)
                if (cand4_meta[i][4] == 1 and tv >= min_t_4way) or (cand4_meta[i][4] == -1 and tv <= -min_t_4way)
            ]
            ok4.sort(key=lambda i: (-abs(t_4w[i]), cand4_meta[i][0]))
            chosen_4 = []
            for idx4 in ok4[:max_rules_keep]:
                key4, cnt4, u4, r4, sgn_dir, t_4vs3 = cand4_meta[idx4]
                v4 = C4_mat[:, idx4]
                terms4 = [
                    {"col_idx": sel_base[k_i]["col_idx"], "name": sel_base[k_i]["name"], "med": sel_base[k_i]["med"], "thr": sel_base[k_i]["thr"], "state": st_i}
                    for k_i, st_i in key4
                ]
                lbl4 = "__AND__".join(f"{t['name']}({'Hi' if t['state']==1 else 'Lo'})" for t in terms4)
                chosen_4.append({
                    "name": f"4W_{'POS' if sgn_dir==1 else 'NEG'}__{lbl4}",
                    "order": 4,
                    "dir": "POS" if sgn_dir == 1 else "NEG",
                    "terms": terms4,
                    "cnt": cnt4,
                    "support_pct": round(cnt4 / M * 100.0, 2),
                    "mean_ret_pct": round(r4 * 100.0, 2),
                    "win_rate_pct": round(float(np.mean(y_win[v4 > 0.5]) * 100.0), 2),
                    "crash_m7_pct": round(float(np.mean(y_ret[v4 > 0.5] <= -0.07) * 100.0), 2),
                    "t_cluster": round(float(t_4w[idx4]), 3),
                    "t_4vs3_synergy": round(float(t_4vs3), 3),
                    "vec": v4,
                })
            if chosen_4:
                X_4way = np.column_stack([r["vec"] for r in chosen_4])
                rules_4way = [{k: v for k, v in r.items() if k != "vec"} for r in chosen_4]

    return {
        "selected_base": sel_base,
        "rules_3way": rules_3way,
        "rules_4way": rules_4way,
        "X_3way": X_3way,
        "X_4way": X_4way,
    }


def _eval_rule_list_on_rows(X_rows: np.ndarray, rules: list[dict]) -> np.ndarray:
    """Evaluate frozen list of 3-way or 4-way rules on arbitrary rows."""
    n = X_rows.shape[0]
    if not rules:
        return np.empty((n, 0), dtype=np.float64)
    cols = []
    for r in rules:
        m = np.ones(n, dtype=bool)
        for t in r["terms"]:
            xv = X_rows[:, t["col_idx"]]
            xv = np.where(np.isfinite(xv), xv, t["med"])
            m &= (xv > t["thr"]) if t["state"] == 1 else (xv <= t["thr"])
        cols.append(m.astype(np.float64))
    return np.column_stack(cols)


def run_causal_highorder_and_tree_wf(
    df: pd.DataFrame,
    atomic_cols: list[str],
    extra_static_cols: Optional[list[str]] = None,
    wf_start_date: str = WF_START_DT,
    min_warmup_trades: int = 80,
    deltas: tuple[int, ...] = (8, 12, 15),
    enable_4way: bool = True,
) -> dict:
    """
    Single strictly causal (exit_date < t) daily-expanding WF loop that fits & evaluates:
      - 3-way AND rules (`Rule3Way`) -> delta in [-d, +d]
      - 4-way AND rules (`Rule4Way`) -> delta in [-d, +d]
      - 3-way + extra_static (`Rule3Way_Plus_Static`) -> delta in [-d, +d]
      - Shallow causal DecisionTree (max_depth=3, min_samples_leaf=25, EB leaf shrinkage) -> delta in [-d, +d]
      - Shallow causal GBDT (max_depth=3, min_samples_leaf=25, n_est=25, lr=0.05) -> delta in [-d, +d]
      - Depth-4 DecisionTree (max_depth=4, min_samples_leaf=20, EB leaf shrinkage) -> delta in [-d, +d]
      - Depth-4 GBDT (max_depth=4, min_samples_leaf=20, n_est=25, lr=0.05) -> delta in [-d, +d]
    Guarantees 100% truncation invariance at any cutoff.
    """
    df_h = wfm.prepare_hygiene_and_net_ret(df, fee_rt=0.0030)
    n = len(df_h)
    buy_dts = df_h["buy_date"].astype(str).str[:10].to_numpy()
    exit_dts = df_h["exit_date"].astype(str).str[:10].to_numpy()
    codes = df_h["code"].astype(str).str.zfill(6).to_numpy()
    y_ret = df_h["net_ret"].to_numpy(dtype=np.float64)
    y_win = (y_ret > 0.0).astype(np.float64)
    can_buy = df_h["can_buy_hygiene"].to_numpy(bool)

    X_atom = df_h[atomic_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    X_stat = df_h[extra_static_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64) if extra_static_cols else np.empty((n, 0), dtype=np.float64)
    stat_names = list(extra_static_cols) if extra_static_cols else []

    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_to_id = {d: i for i, d in enumerate(uniq_dts)}
    day_ids = np.array([dt_to_id[d] for d in buy_dts], dtype=np.int32)

    buyable_idx = np.where(can_buy)[0]
    exit_order = sorted(buyable_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i]))
    exit_arr = np.asarray(exit_order, dtype=np.int64)
    exit_dts_s = exit_dts[exit_arr]

    by_dt_rows = {}
    for i in buyable_idx:
        by_dt_rows.setdefault(buy_dts[i], []).append(i)

    models_list = ["Rule3Way", "Rule4Way", "Rule3Way_Static", "DT_D3", "GBDT_D3", "DT_D4", "GBDT_D4"]
    raw_z = {m: np.full(n, np.nan, dtype=np.float64) for m in ("DT_D3", "GBDT_D3", "DT_D4", "GBDT_D4")}
    rule_deltas = {(m, d): np.zeros(n, dtype=np.float64) for m in ("Rule3Way", "Rule4Way", "Rule3Way_Static") for d in deltas}
    wf_in_win = np.zeros(n, dtype=bool)

    ptr, last_ptr = 0, -1
    n_ex = len(exit_arr)
    started, wf_actual_start = False, None
    cur_state = None
    rule_freq_3w, rule_freq_4w = {}, {}
    tree_rule_snaps = []
    n_rebuilds = 0
    last_snap_m = ""

    for t in sorted(by_dt_rows.keys()):
        while ptr < n_ex and exit_dts_s[ptr] < t:
            ptr += 1
        if t < wf_start_date:
            continue
        if not started:
            if ptr >= min_warmup_trades:
                started = True
                wf_actual_start = t
            else:
                continue

        if cur_state is None or ptr > last_ptr:
            tr_idx = exit_arr[:ptr]
            X_a_tr = X_atom[tr_idx]
            X_s_tr = X_stat[tr_idx]
            r_tr = y_ret[tr_idx]
            w_tr = y_win[tr_idx]
            d_tr = day_ids[tr_idx]

            # 1. Fit 3-way & 4-way nonlinear AND rules
            res_ho = fit_causal_3way_and_4way_rules(
                X_a_tr, r_tr, w_tr, d_tr, atomic_cols,
                top_base_k=25, max_base_corr=0.70,
                min_leaf_3way=25, min_pct_3way=0.05, min_t_3way=2.5, min_syn_t_3way=1.5, min_cond_t_3way=1.1,
                min_leaf_4way=20, min_t_4way=2.8, min_syn_t_4way=1.5,
                max_rules_keep=24, enable_4way=enable_4way,
            )

            # Build mode='delta_patch' scorecards for Rule3Way, Rule4Way, Rule3Way_Static
            cards_ho = {}
            for d_cap in deltas:
                # Rule3Way
                if res_ho["X_3way"].shape[1] > 0:
                    c3 = wfc.fit_causal_scorecard(
                        res_ho["X_3way"], r_tr, w_tr, d_tr,
                        feature_names=[r["name"] for r in res_ho["rules_3way"]],
                        mode="delta_patch", top_k=8, min_k=1, max_corr=0.65,
                        min_t_stat=1.5, shrink_tau=20.0, max_delta=d_cap,
                    )
                else:
                    c3 = {"mode": "delta_patch", "factors": []}
                cards_ho[("Rule3Way", d_cap)] = c3

                # Rule4Way
                if res_ho["X_4way"].shape[1] > 0:
                    c4 = wfc.fit_causal_scorecard(
                        res_ho["X_4way"], r_tr, w_tr, d_tr,
                        feature_names=[r["name"] for r in res_ho["rules_4way"]],
                        mode="delta_patch", top_k=8, min_k=1, max_corr=0.65,
                        min_t_stat=1.5, shrink_tau=20.0, max_delta=d_cap,
                    )
                else:
                    c4 = {"mode": "delta_patch", "factors": []}
                cards_ho[("Rule4Way", d_cap)] = c4

                # Rule3Way + Static (CLEAN_B + Mech130 filtered for >=15 discrete support)
                if X_s_tr.shape[1] > 0:
                    min_v = max(35, int(0.45 * len(X_s_tr)))
                    keep_s = []
                    for js in range(X_s_tr.shape[1]):
                        col_j = X_s_tr[:, js]
                        xv = col_j[np.isfinite(col_j)]
                        if len(xv) < min_v:
                            continue
                        uniq, cnts = np.unique(xv, return_counts=True)
                        if len(uniq) <= 3 and (len(cnts) < 2 or int(np.sort(cnts)[-2]) < 15):
                            continue
                        keep_s.append(js)
                    X_comb_tr = np.hstack([X_s_tr[:, keep_s], res_ho["X_3way"]]) if res_ho["X_3way"].shape[1] > 0 else X_s_tr[:, keep_s]
                    names_comb = [stat_names[js] for js in keep_s] + [r["name"] for r in res_ho["rules_3way"]]
                    c3s = wfc.fit_causal_scorecard(
                        X_comb_tr, r_tr, w_tr, d_tr, feature_names=names_comb,
                        mode="delta_patch", top_k=10, min_k=5, max_corr=0.65,
                        min_t_stat=1.0, shrink_tau=20.0, max_delta=d_cap,
                    )
                    n_ks = len(keep_s)
                    for fac in c3s.get("factors", []):
                        if fac["col_idx"] < n_ks:
                            fac["col_idx"] = keep_s[fac["col_idx"]]
                        else:
                            fac["col_idx"] = X_s_tr.shape[1] + (fac["col_idx"] - n_ks)
                else:
                    c3s = {"mode": "delta_patch", "factors": []}
                cards_ho[("Rule3Way_Static", d_cap)] = c3s

            # 2. Fit shallow causal trees (max_depth=3 min_leaf=25, max_depth=4 min_leaf=20) on Top 25 orthogonal factors
            sel_b = res_ho["selected_base"]
            tree_models = {}
            if len(sel_b) >= 3:
                b_cols = [sb["col_idx"] for sb in sel_b]
                b_meds = np.array([sb["med"] for sb in sel_b], dtype=np.float64)
                X_tr_b = np.where(np.isfinite(X_a_tr[:, b_cols]), X_a_tr[:, b_cols], b_meds[None, :])
                mu0_tr = float(np.mean(r_tr))
                wr0_tr = float(np.mean(w_tr))
                sd_tr = max(1e-5, float(np.std(r_tr, ddof=1)))
                # Winsorize utility gently at [-3.5, +3.5] to prevent single +40% outlier leaf hijack
                u_tr = np.clip(0.6 * (r_tr - mu0_tr) / sd_tr + 0.4 * (w_tr - wr0_tr) / 0.25, -3.5, 3.5)

                for tname, depth, mleaf, kind in [
                    ("DT_D3", 3, 25, "dt"),
                    ("GBDT_D3", 3, 25, "gbdt"),
                    ("DT_D4", 4, 20, "dt"),
                    ("GBDT_D4", 4, 20, "gbdt"),
                ]:
                    if kind == "dt":
                        mdl = DecisionTreeRegressor(max_depth=depth, min_samples_leaf=mleaf, random_state=20261126)
                        mdl.fit(X_tr_b, u_tr)
                        # Empirical Bayes leaf shrinkage (tau=20)
                        leaf_ids = mdl.apply(X_tr_b)
                        leaf_eb = {}
                        for lid in np.unique(leaf_ids):
                            m_l = (leaf_ids == lid)
                            cnt_l = int(m_l.sum())
                            leaf_eb[int(lid)] = float(np.sum(u_tr[m_l]) / (cnt_l + 20.0))
                        pred_tr = np.array([leaf_eb[int(lid)] for lid in leaf_ids], dtype=np.float64)
                        scale = max(1e-4, float(np.percentile(np.abs(pred_tr), 95)))
                        tree_models[tname] = {"kind": "dt", "mdl": mdl, "leaf_eb": leaf_eb, "mu": 0.0, "scale": scale, "b_cols": b_cols, "b_meds": b_meds, "b_names": [sb["name"] for sb in sel_b]}
                    else:
                        mdl = GradientBoostingRegressor(
                            max_depth=depth, min_samples_leaf=mleaf, n_estimators=25,
                            learning_rate=0.05, subsample=0.80, max_features=0.70, random_state=20261126,
                        )
                        mdl.fit(X_tr_b, u_tr)
                        pred_tr = mdl.predict(X_tr_b)
                        mu_p = float(np.mean(pred_tr))
                        scale = max(1e-4, float(np.percentile(np.abs(pred_tr - mu_p), 95)))
                        tree_models[tname] = {"kind": "gbdt", "mdl": mdl, "mu": mu_p, "scale": scale, "b_cols": b_cols, "b_meds": b_meds, "b_names": [sb["name"] for sb in sel_b]}

            cur_state = {"res_ho": res_ho, "cards_ho": cards_ho, "tree_models": tree_models}
            last_ptr = ptr
            n_rebuilds += 1

            # Record rule frequencies at monthly granularity (for diagnostics, zero leakage)
            if t[:7] != last_snap_m:
                last_snap_m = t[:7]
                for r in res_ho["rules_3way"]:
                    rule_freq_3w[r["name"]] = rule_freq_3w.get(r["name"], 0) + 1
                for r in res_ho["rules_4way"]:
                    rule_freq_4w[r["name"]] = rule_freq_4w.get(r["name"], 0) + 1
                if "DT_D3" in tree_models:
                    tree_rule_snaps.append({"as_of": t, "n_train": int(ptr), "dt_d3_top_features": _extract_dt_rules_summary(tree_models["DT_D3"])})

        # Score today's candidates t
        rows_t = np.asarray(by_dt_rows[t], dtype=np.int64)
        wf_in_win[rows_t] = True
        X_a_t = X_atom[rows_t]
        X_s_t = X_stat[rows_t]
        r3_list = cur_state["res_ho"]["rules_3way"]
        r4_list = cur_state["res_ho"]["rules_4way"]
        X_3_t = _eval_rule_list_on_rows(X_a_t, r3_list)
        X_4_t = _eval_rule_list_on_rows(X_a_t, r4_list)
        X_3s_t = np.hstack([X_s_t, X_3_t]) if (X_s_t.shape[1] > 0 and X_3_t.shape[1] > 0) else (X_s_t if X_s_t.shape[1] > 0 else X_3_t)

        for d_cap in deltas:
            rule_deltas[("Rule3Way", d_cap)][rows_t] = wfc.score_candidates_with_card(X_3_t, cur_state["cards_ho"][("Rule3Way", d_cap)]).astype(float) if X_3_t.shape[1] > 0 else 0.0
            rule_deltas[("Rule4Way", d_cap)][rows_t] = wfc.score_candidates_with_card(X_4_t, cur_state["cards_ho"][("Rule4Way", d_cap)]).astype(float) if X_4_t.shape[1] > 0 else 0.0
            rule_deltas[("Rule3Way_Static", d_cap)][rows_t] = wfc.score_candidates_with_card(X_3s_t, cur_state["cards_ho"][("Rule3Way_Static", d_cap)]).astype(float) if X_3s_t.shape[1] > 0 else 0.0

        for tname, tm in cur_state["tree_models"].items():
            X_tb = np.where(np.isfinite(X_a_t[:, tm["b_cols"]]), X_a_t[:, tm["b_cols"]], tm["b_meds"][None, :])
            if tm["kind"] == "dt":
                lids = tm["mdl"].apply(X_tb)
                raw_p = np.array([tm["leaf_eb"].get(int(lid), 0.0) for lid in lids], dtype=np.float64)
            else:
                raw_p = tm["mdl"].predict(X_tb)
            raw_z[tname][rows_t] = np.clip((raw_p - tm["mu"]) / tm["scale"], -1.0, 1.0)

    return {
        "df_h": df_h,
        "wf_in_win": wf_in_win,
        "wf_actual_start": wf_actual_start,
        "n_rebuilds": n_rebuilds,
        "rule_deltas": rule_deltas,
        "raw_z": raw_z,
        "latest_state": cur_state,
        "rule_freq_3w": rule_freq_3w,
        "rule_freq_4w": rule_freq_4w,
        "tree_rule_snaps": tree_rule_snaps,
    }


def _extract_dt_rules_summary(tm: dict) -> list[dict]:
    tree_ = tm["mdl"].tree_
    fnames = tm["b_names"]
    eb = tm["leaf_eb"]
    rules = []

    def recurse(node, conds):
        if tree_.feature[node] >= 0:
            fname = fnames[tree_.feature[node]]
            thr = round(float(tree_.threshold[node]), 4)
            recurse(tree_.children_left[node], conds + [f"{fname} <= {thr}"])
            recurse(tree_.children_right[node], conds + [f"{fname} > {thr}"])
        else:
            cnt = int(tree_.n_node_samples[node])
            val = round(float(eb.get(int(node), 0.0)), 4)
            rules.append({"leaf_id": int(node), "n": cnt, "eb_u": val, "rule": " & ".join(conds)})

    recurse(0, [])
    rules.sort(key=lambda x: -abs(x["eb_u"]))
    return rules


def run_mode_b_multi_grid(
    df_h: pd.DataFrame,
    feat_cols: list[str],
    orig_cols: list[str],
    deltas: tuple[int, ...],
    wf_start_date: str = WF_START_DT,
    min_warmup_trades: int = 80,
    top_k: int = 10,
    min_k: int = 5,
    max_corr: float = 0.65,
    max_corr_orig: float = 0.70,
    min_t_stat: float = 1.0,
    shrink_tau: float = 20.0,
    min_discrete_bin_cnt: int = 15,
) -> tuple[dict[tuple[str, int], np.ndarray], dict[str, dict]]:
    """
    Exact bit-for-bit equivalent of running `w23.run_causal_scorecard_ext(..., mode='delta_patch')`
    for every `(orig_col, max_delta)` pair, but computes feature binning & cluster t-stats ONCE per day
    instead of len(orig_cols) * len(deltas) times (15-20x faster, 0.0 difference!).
    """
    n = len(df_h)
    buy_dts = df_h["buy_date"].astype(str).str[:10].to_numpy()
    exit_dts = df_h["exit_date"].astype(str).str[:10].to_numpy()
    codes = df_h["code"].astype(str).str.zfill(6).to_numpy()
    y_ret = df_h["net_ret"].to_numpy(dtype=np.float64)
    y_win = (y_ret > 0.0).astype(np.float64)
    can_buy = df_h["can_buy_hygiene"].to_numpy(bool)

    X_all = df_h[feat_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    orig_arrays = {oc: pd.to_numeric(df_h[oc], errors="coerce").to_numpy(dtype=np.float64) for oc in orig_cols}

    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_to_id = {d: i for i, d in enumerate(uniq_dts)}
    day_ids = np.array([dt_to_id[d] for d in buy_dts], dtype=np.int32)

    buyable_idx = np.where(can_buy)[0]
    exit_order = sorted(buyable_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i]))
    exit_arr = np.asarray(exit_order, dtype=np.int64)
    exit_dts_s = exit_dts[exit_arr]

    by_dt_rows = {}
    for i in buyable_idx:
        by_dt_rows.setdefault(buy_dts[i], []).append(i)

    delta_out = {(oc, md): np.zeros(n, dtype=np.float64) for oc in orig_cols for md in deltas}
    latest_cards = {}

    ptr, last_ptr = 0, -1
    n_ex = len(exit_arr)
    started = False
    cur_cards = None

    for t in sorted(by_dt_rows.keys()):
        while ptr < n_ex and exit_dts_s[ptr] < t:
            ptr += 1
        if t < wf_start_date:
            continue
        if not started:
            if ptr >= min_warmup_trades:
                started = True
            else:
                continue

        if cur_cards is None or ptr > last_ptr:
            tr_idx = exit_arr[:ptr]
            X_tr_full = X_all[tr_idx]
            r_tr = y_ret[tr_idx]
            w_tr = y_win[tr_idx]
            d_tr = day_ids[tr_idx]
            M = len(tr_idx)

            if min_discrete_bin_cnt > 0:
                min_valid = max(35, int(0.45 * M))
                keep_idx = []
                for j in range(X_tr_full.shape[1]):
                    col_j = X_tr_full[:, j]
                    xv = col_j[np.isfinite(col_j)]
                    if len(xv) < min_valid:
                        continue
                    uniq, cnts = np.unique(xv, return_counts=True)
                    if len(uniq) <= 3 and (len(cnts) < 2 or int(np.sort(cnts)[-2]) < min_discrete_bin_cnt):
                        continue
                    keep_idx.append(j)
                if not keep_idx:
                    keep_idx = list(range(X_tr_full.shape[1]))
            else:
                keep_idx = list(range(X_tr_full.shape[1]))

            # Compute base scorecard ONCE without orig_corr filter to extract all binned candidates
            X_tr = X_tr_full[:, keep_idx]
            # Call fit_causal_scorecard with top_k=len(keep_idx) max_corr=1.0? No, wait:
            # Running fit_causal_scorecard once with orig=None gives candidates ONLY up to top_k after corr pruning.
            # Instead, compute candidate list once cleanly matching _wf_core.fit_causal_scorecard lines 88-195!
            mu0 = float(np.mean(r_tr))
            wr0 = float(np.mean(w_tr))
            min_valid_n = max(35, int(0.45 * M))
            cands = []
            for j_sub, j_orig in enumerate(keep_idx):
                col = X_tr[:, j_sub]
                valid = np.isfinite(col)
                nv = int(valid.sum())
                if nv < min_valid_n:
                    continue
                xv = col[valid]
                if float(np.std(xv)) < 1e-12:
                    continue
                rv = r_tr[valid]
                wv = w_tr[valid]
                dv = d_tr[valid]
                mu_v = float(np.mean(rv))
                wr_v = float(np.mean(wv))
                sd_r = max(1e-5, float(np.std(rv, ddof=1)))
                u_util = 0.6 * (rv - mu_v) / sd_r + 0.4 * (wv - wr_v) / 0.25

                uniq = np.unique(xv)
                if len(uniq) <= 3:
                    edges = uniq.astype(float)
                    b_idx = np.searchsorted(edges, xv, side="left")
                    is_discrete = True
                    B = len(edges)
                    if B < 2:
                        continue
                else:
                    q33, q67 = np.percentile(xv, [33.3333333, 66.6666667])
                    if q67 <= q33 + 1e-12:
                        q50 = float(np.median(xv))
                        b_idx = (xv > q50).astype(int)
                        if b_idx.sum() < 8 or (nv - b_idx.sum()) < 8:
                            b_idx = (xv >= q50).astype(int)
                        if b_idx.sum() < 8 or (nv - b_idx.sum()) < 8:
                            continue
                        edges = np.array([q50], dtype=float)
                        B = 2
                    else:
                        b_idx = np.where(xv <= q33, 0, np.where(xv <= q67, 1, 2))
                        cnts = np.bincount(b_idx, minlength=3)
                        if np.any(cnts < 8):
                            q50 = float(np.median(xv))
                            b_idx = (xv > q50).astype(int)
                            if b_idx.sum() < 8 or (nv - b_idx.sum()) < 8:
                                continue
                            edges = np.array([q50], dtype=float)
                            B = 2
                        else:
                            edges = np.array([float(q33), float(q67)], dtype=float)
                            B = 3
                    is_discrete = False

                cnts = np.bincount(b_idx, minlength=B)
                sum_r = np.bincount(b_idx, weights=rv, minlength=B)
                sum_w = np.bincount(b_idx, weights=wv, minlength=B)
                shr_dr = (sum_r + shrink_tau * mu_v) / (cnts + shrink_tau) - mu_v
                shr_dw = (sum_w + shrink_tau * wr_v) / (cnts + shrink_tau) - wr_v
                eff = 0.6 * (shr_dr / sd_r) + 0.4 * (shr_dw / 0.25)

                if B == 3:
                    z_lin = b_idx.astype(float) - 1.0
                    t_lin = wfc._cluster_t_stat(u_util, z_lin, dv)
                    z_quad = np.where(b_idx == 1, 1.0, -0.5)
                    t_quad = wfc._cluster_t_stat(u_util, z_quad, dv)
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
                    t_eff = wfc._cluster_t_stat(u_util, z_bin, dv)
                    shape = "binary_up" if eff[-1] >= eff[0] else "binary_down"

                cands.append({
                    "col_idx": j_orig,
                    "col_sub": j_sub,
                    "valid": valid,
                    "xv": xv,
                    "name": feat_cols[j_orig],
                    "abs_t": abs(float(t_eff)),
                    "t_cluster": round(float(t_eff), 3),
                    "shape": shape,
                    "is_discrete": is_discrete,
                    "edges": edges,
                    "B": B,
                    "eff": eff,
                    "cnts": cnts.tolist(),
                    "bin_wr_pct": [round(float(sum_w[b] / cnts[b] * 100.0), 2) for b in range(B)],
                    "bin_mean_pct": [round(float(sum_r[b] / cnts[b] * 100.0), 2) for b in range(B)],
                })

            cands.sort(key=lambda c: (-c["abs_t"], c["col_sub"]))

            # Select orthogonal pool per distinct orig_corr-filtered signature
            sel_cache = {}
            cur_cards = {}
            for oc in orig_cols:
                o_tr = orig_arrays[oc][tr_idx]
                kept_mask = []
                for c in cands:
                    ov = o_tr[c["valid"]]
                    m_ov = np.isfinite(ov)
                    ok_o = True
                    if m_ov.sum() >= 30 and np.std(ov[m_ov]) > 1e-12 and np.std(c["xv"][m_ov]) > 1e-12:
                        if abs(float(np.corrcoef(c["xv"][m_ov], ov[m_ov])[0, 1])) > max_corr_orig:
                            ok_o = False
                    kept_mask.append(ok_o)
                sig = tuple(kept_mask)
                if sig not in sel_cache:
                    cands_f = [c for c, ok in zip(cands, kept_mask) if ok]
                    strong = [c for c in cands_f if c["abs_t"] >= min_t_stat]
                    sel = []
                    for c in strong:
                        xj = X_tr_full[:, c["col_idx"]]
                        ok_c = True
                        for s in sel:
                            xs = X_tr_full[:, s["col_idx"]]
                            both = np.isfinite(xj) & np.isfinite(xs)
                            if both.sum() >= 25:
                                a, b = xj[both], xs[both]
                                if np.std(a) > 1e-12 and np.std(b) > 1e-12 and abs(float(np.corrcoef(a, b)[0, 1])) > max_corr:
                                    ok_c = False
                                    break
                        if ok_c:
                            sel.append(c)
                            if len(sel) >= top_k:
                                break
                    if len(sel) < min_k and len(cands_f) > len(sel):
                        used = {s["col_idx"] for s in sel}
                        for c in cands_f:
                            if c["col_idx"] in used:
                                continue
                            xj = X_tr_full[:, c["col_idx"]]
                            ok_c = True
                            for s in sel:
                                xs = X_tr_full[:, s["col_idx"]]
                                both = np.isfinite(xj) & np.isfinite(xs)
                                if both.sum() >= 25 and np.std(xj[both]) > 1e-12 and np.std(xs[both]) > 1e-12:
                                    if abs(float(np.corrcoef(xj[both], xs[both])[0, 1])) > max_corr:
                                        ok_c = False
                                        break
                            if ok_c:
                                sel.append(c)
                                if len(sel) >= min_k:
                                    break
                    sel_cache[sig] = sel

                sel_oc = sel_cache[sig]
                t_weights = np.array([min(4.0, max(0.25, c["abs_t"])) for c in sel_oc], dtype=float)
                for md in deltas:
                    if not sel_oc:
                        card_om = {"mode": "delta_patch", "n_train": M, "factors": [], "train_mu0_pct": round(mu0 * 100.0, 2), "train_wr0_pct": round(wr0 * 100.0, 2)}
                    else:
                        budgets = wfc._largest_remainder_int(t_weights, int(md))
                        facs = []
                        for c, bgt in zip(sel_oc, budgets):
                            eff = c["eff"]
                            emean = float(np.average(eff, weights=np.array(c["cnts"], dtype=float)))
                            span = max(1e-12, float(np.max(np.abs(eff - emean))))
                            pts = [int(round((float(e) - emean) / span * bgt)) for e in eff]
                            facs.append({
                                "col_idx": c["col_idx"],
                                "name": c["name"],
                                "t_cluster": c["t_cluster"],
                                "shape": c["shape"],
                                "budget_pts": int(bgt),
                                "is_discrete": c["is_discrete"],
                                "edges": c["edges"].tolist(),
                                "bin_pts": pts,
                                "nan_pt": 0,
                                "bin_cnts": c["cnts"],
                                "bin_wr_pct": c["bin_wr_pct"],
                                "bin_mean_pct": c["bin_mean_pct"],
                            })
                        card_om = {
                            "mode": "delta_patch",
                            "n_train": int(M),
                            "train_mu0_pct": round(mu0 * 100.0, 2),
                            "train_wr0_pct": round(wr0 * 100.0, 2),
                            "factors": facs,
                        }
                    cur_cards[(oc, md)] = card_om
                    latest_cards[f"{oc}_d{md}"] = card_om
            last_ptr = ptr

        rows_t = np.asarray(by_dt_rows[t], dtype=np.int64)
        X_t = X_all[rows_t]
        for (oc, md), card_om in cur_cards.items():
            delta_out[(oc, md)][rows_t] = wfc.score_candidates_with_card(X_t, card_om).astype(np.float64)

    return delta_out, latest_cards

