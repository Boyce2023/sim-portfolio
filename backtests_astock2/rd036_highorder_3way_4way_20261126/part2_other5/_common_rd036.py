#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD036-B Shared Core (`_common_rd036.py`) for 5 V20.0 Strategies:
  `1to2`, `2to3`, `3to4`, `high`, `pry`
Provides:
  - Read-only loaders for wave1_base & rd028 simulation metadata
  - Exact close-to-close daily MTM builder (NO multi-day geometric smoothing)
  - Parity-verified single-slot simulators (0.20% parity + 0.30%/0.50%/0.80% friction + >=2亿 liquidity)
  - Unified V20.0 6-strategy combined single-slot incremental evaluator (unified 0.30% baseline)
  - Full anti-overfit metric suite (exact MTM Sharpe, 8 windows incl. 26H2, ex-top5, 1000x perm, paired t, DSR, CSCV PBO)
  - Physical truncation zero-leakage proof at 2024-12-31

Zero yfinance (D12). Zero cap10m. Threads <= 2. Read-only on rd035 and production scripts.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import itertools
import json
import math
import pickle
import resource
import sys
import warnings
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
from scipy import stats

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035_BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1 = f"{RD035_BASE}/wave1_base"
W2A1_DIR = f"{RD035_BASE}/wave2a/w2a1_old_1to2_2to3"
W2A4_DIR = f"{RD035_BASE}/wave2a/w2a4_pairwise_interactions"
RD028 = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
OUT_DIR = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5"
CACHE_DIR = f"{OUT_DIR}/_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

for p in (WAVE1, RD028, PARTC_V20, W2A1_DIR, W2A4_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _wf_core as wfc
import _wf_sim_and_metrics as wfm
import wf_scorecard_engine as wfe
import step4_mod_rules_and_sim as m1
import tier_priority_engine as tpe
import _w2a4_data_and_features as w2f

OTHER5 = ["1to2", "2to3", "3to4", "high", "pry"]
ALL6 = ["3to4", "high", "pry", "2to3", "1to2", "20cm"]
TRD_DAYS_YEAR = 242.0
WF_START = "2023-01-03"
WF_END = "2026-11-16"

ORIG_THRESHOLDS = {"1to2": None, "2to3": 90.0, "3to4": 90.0, "high": 88.0, "pry": 165.0, "20cm": 82.0}
EXPECTED_PARITY_020 = {
    "1to2": (92, 474.3511),
    "2to3": (95, 404.7082),
    "3to4": (95, 616.1818),
    "high": (42, 14.7494),
    "pry": (16, 2.4400),
    "20cm": (199, 468.2894),
}
BASE_INTERCEPTS = {"2to3": 60.0, "3to4": 78.0, "high": 60.0, "pry": 100.0}
ATOMIC_PREFIXES = {
    "1to2": "s12_atom_",
    "2to3": "s23_af_",
    "3to4": "s34_af_",
    "high": "shigh_af_",
    "pry": "spry_af_",
}
MIN_LEAF_MAP = {"1to2": 25, "2to3": 25, "pry": 25, "3to4": 20, "high": 12}
MIN_DAYS_MAP = {"1to2": 8, "2to3": 8, "pry": 5, "3to4": 8, "high": 5}

WINDOWS = [
    ("FULL_WF", WF_START, WF_END),
    ("Y2023", WF_START, "2023-12-31"),
    ("Y2024", "2024-01-01", "2024-12-31"),
    ("Y2025", "2025-01-01", "2025-12-31"),
    ("Y2526", "2025-01-01", WF_END),
    ("Y2026", "2026-01-01", WF_END),
    ("Y26H1", "2026-01-01", "2026-06-30"),
    ("Y26H2", "2026-07-01", WF_END),
]


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
    if isinstance(obj, np.ndarray):
        return sanitize_json(obj.tolist())
    return obj


def convert_fee(ret_020: np.ndarray | pd.Series | float, fee_rt: float) -> np.ndarray | float:
    """Convert net_ret from 0.20% round-trip baseline to arbitrary `fee_rt` (0.0030, 0.0050, 0.0080)."""
    return (1.0 + ret_020) / 0.9980 * (1.0 - float(fee_rt)) - 1.0


def scale_mtm_segs(segs: tuple, ret_020: float, ret_new: float) -> tuple:
    """Adjust only the final exit-day multiplier of precomputed exact MTM segments for a new fee."""
    if not segs or not np.isfinite(ret_020) or (1.0 + ret_020) <= 1e-12:
        return segs
    lst = list(segs)
    ti, mult = lst[-1]
    lst[-1] = (ti, float(mult) * ((1.0 + float(ret_new)) / (1.0 + float(ret_020))))
    return tuple(lst)


def preload_exact_bars(pool_dfs: list[pd.DataFrame], v20_ledger: pd.DataFrame, cal_5y: list[str]) -> dict:
    """Load ONLY (code, dt) daily bars needed for exact close-to-close MTM across all pools + V20 ledger."""
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    T = len(cal_5y)
    needed_pairs = set()
    needed_codes = set()
    for df in list(pool_dfs) + [v20_ledger]:
        if df is None or df.empty:
            continue
        for r in df[["code", "buy_date", "exit_date"]].itertuples(index=False):
            c = str(r.code).zfill(6)
            bi = idx_5y.get(str(r.buy_date)[:10])
            ei = idx_5y.get(str(r.exit_date)[:10])
            if bi is None:
                continue
            ei_use = ei if (ei is not None and ei >= bi) else (T - 1)
            needed_codes.add(c)
            for t in range(bi, min(ei_use + 1, T)):
                needed_pairs.add((c, cal_5y[t]))

    tks = sorted({f"{c}.SH" for c in needed_codes} | {f"{c}.SZ" for c in needed_codes})
    cols = ["date", "ticker", "open", "close", "adj_close"]
    flt = (ds.field("date") >= pd.Timestamp("2021-11-01")) & (ds.field("date") <= pd.Timestamp("2026-11-25")) & ds.field("ticker").isin(tks)
    bar_lu = {}
    for pq_path, dl_flag in [(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", 0), (f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", 1)]:
        scanner = ds.dataset(pq_path, format="parquet").scanner(columns=cols, filter=flt, batch_size=65536)
        for batch in scanner.to_batches():
            dfb = batch.to_pandas()
            if dfb.empty:
                continue
            c6s = dfb["ticker"].astype(str).str[:6]
            dts = pd.to_datetime(dfb["date"]).dt.strftime("%Y-%m-%d")
            keep = [((c, d) in needed_pairs) for c, d in zip(c6s, dts)]
            if not any(keep):
                continue
            sub = dfb.loc[keep]
            for c, d, op, cl, acl in zip(c6s.loc[keep], dts.loc[keep], sub["open"], sub["close"], sub["adj_close"]):
                k = (c, d)
                if dl_flag == 0 or k not in bar_lu:
                    adjf = (float(acl) / float(cl)) if (cl > 0 and acl > 0) else 1.0
                    bar_lu[k] = (float(op), float(cl), adjf)
    gc.collect()
    pa.default_memory_pool().release_unused()
    return bar_lu


def build_mtm_segments_5y(df: pd.DataFrame, cal_5y: list[str], bar_lu: dict, is_20cm: bool = False) -> list[tuple]:
    """Build exact close-to-close daily MTM segment multipliers `(cal_5y_idx, mult)` at 0.20% ret."""
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    T = len(cal_5y)
    segs_all = []
    for r in df.itertuples(index=False):
        if "sim_ok" in df.columns and not bool(r.sim_ok):
            segs_all.append(())
            continue
        nr = float(r.net_ret_020) if hasattr(r, "net_ret_020") else float(r.net_ret)
        if not np.isfinite(nr):
            segs_all.append(())
            continue
        bd = str(r.buy_date)[:10]
        ed = str(r.exit_date)[:10]
        bi = idx_5y.get(bd)
        ei = idx_5y.get(ed)
        if bi is None:
            segs_all.append(())
            continue
        c6 = str(r.code).zfill(6)
        bb = bar_lu.get((c6, bd))
        bp_val = getattr(r, "buy_px", np.nan) if (is_20cm and hasattr(r, "buy_px")) else getattr(r, "buy_price", np.nan)
        if is_20cm and pd.notna(bp_val):
            b_adj = float(bp_val)
        elif pd.notna(bp_val) and bb is not None:
            b_adj = float(bp_val) * bb[2]
        elif bb is not None:
            b_adj = bb[1] * bb[2]
        else:
            b_adj = 1.0
        if not np.isfinite(b_adj) or b_adj <= 0:
            b_adj = 1.0

        prev_v, last_c = b_adj, b_adj
        end_loop = ei if (ei is not None and ei > bi) else T
        segs = []
        for t in range(bi, min(end_loop, T)):
            bt = bar_lu.get((c6, cal_5y[t]))
            cur_c = (bt[1] * bt[2]) if (bt is not None and bt[1] > 0) else last_c
            if cur_c <= 0:
                cur_c = last_c
            segs.append((t, cur_c / prev_v))
            prev_v, last_c = cur_c, cur_c
        if ei is not None and ei > bi and ei < T:
            segs.append((ei, (b_adj * (1.0 + nr)) / prev_v))
        segs_all.append(tuple(segs))
    return segs_all


def _build_1to2_contrib(df: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    cols = sorted([c for c in df.columns if c.startswith("s12_atom_")])
    cb = (df["s12_atom_clean_brk60"].fillna(0).to_numpy(float) == 1.0)
    mcap = df["s12_atom_mcap"].fillna(50.0).to_numpy(float)
    amt = df["s12_atom_amt"].fillna(2e8).to_numpy(float)
    dd20 = df["s12_atom_dd20"].fillna(0.9).to_numpy(float)
    pos20 = df["s12_atom_pos20"].fillna(0.5).to_numpy(float)
    to = df["s12_atom_to"].fillna(8.0).to_numpy(float)
    vr = df["s12_atom_vr"].fillna(1.5).to_numpy(float)

    fixed_w = {
        "s12_atom_pure_outsider": -20.0, "s12_atom_is_gran": 15.0, "s12_atom_s_elo_hot": 10.0,
        "s12_atom_s_elo_cold": -10.0, "s12_atom_wk_mask": 10.0, "s12_atom_rk_theme_1": 28.0,
        "s12_atom_p_sz_ge4": 18.0, "s12_atom_hard_cat": 18.0,
        "s12_atom_dd20_deep": np.where(cb, 0.0, np.where(dd20 <= 0.82, 42.0, 32.0)),
        "s12_atom_clean_brk60": 24.0, "s12_atom_true_buy_rk1": 35.0, "s12_atom_mkt_open_top3": 20.0,
        "s12_atom_open_sweet": 20.0, "s12_atom_front_lock1": 8.0, "s12_atom_front_lock_crowd": -15.0,
        "s12_atom_tight_open1": 5.0, "s12_atom_has_ir": 5.0, "s12_atom_cap_yizi_gt90": -25.0,
        "s12_atom_climax_95": -10.0, "s12_atom_seal_80": -10.0, "s12_atom_v20_fb20_pen": -25.0,
        "s12_atom_xq_cold": 0.0,
    }
    mat = np.zeros((len(df), len(cols)), dtype=np.float64)
    for j, c in enumerate(cols):
        if c == "s12_atom_mcap":
            mat[:, j] = np.where((mcap >= 60) & (mcap <= 155), 28.0, np.where((mcap >= 40) & (mcap < 60), 10.0, np.where(mcap < 35, -20.0, 0.0)))
        elif c == "s12_atom_amt":
            mat[:, j] = np.where((amt >= 2.2e8) & (amt <= 15e8), 18.0, np.where(amt < 1.8e8, -25.0, -10.0))
        elif c == "s12_atom_dd20":
            mat[:, j] = np.where(cb, 0.0, np.where(dd20 <= 0.82, 42.0, np.where(dd20 <= 0.86, 32.0, np.where(dd20 <= 0.90, 18.0, np.where(dd20 > 0.95, -40.0, 0.0)))))
        elif c == "s12_atom_pos20":
            mat[:, j] = np.where(cb, 0.0, np.where(pos20 <= 0.30, 25.0, np.where(pos20 <= 0.45, 12.0, np.where(pos20 > 0.75, -35.0, 0.0))))
        elif c == "s12_atom_to":
            mat[:, j] = np.where(to <= 9.0, 15.0, np.where(to <= 15.0, 8.0, np.where(to > 18.0, -25.0, 0.0)))
        elif c == "s12_atom_vr":
            mat[:, j] = np.where(vr <= 1.75, 15.0, np.where(vr > 2.3, -15.0, 0.0))
        elif c == "s12_atom_dd20_deep":
            mat[:, j] = df[c].fillna(0).to_numpy(float) * fixed_w[c]
        else:
            mat[:, j] = df[c].fillna(0).to_numpy(float) * float(fixed_w[c])
    return cols, mat


def build_or_load_cache(force_rebuild: bool = False) -> dict:
    """Build or load cached enriched pools, exact MTM segments, and V20 context (< 1.5GB RSS)."""
    cache_path = f"{CACHE_DIR}/rd036_other5_bundle.pkl"
    if (not force_rebuild) and os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    v20_ctx = wfe.load_v20_reference_context(WAVE1)
    cal_5y = v20_ctx["calendar_5y"]["trade_date"].tolist()
    cal_full_dts = v20_ctx["bench"]["trade_date"].tolist()
    cal_wf = [d for d in cal_5y if WF_START <= d <= WF_END]
    wf_off = cal_5y.index(cal_wf[0])
    T_wf = len(cal_wf)

    with open(f"{WAVE1}/wave1a_factor_catalog_and_pit_audit.json", encoding="utf-8") as f:
        cat = json.load(f)["master_factor_catalog"]

    # Load 6-strat master, attach 1d community burst + 130 mech interactions once
    m_full = w2f.load_master_with_sim_cols("2026-11-25")
    m_full = w2f.attach_pit_community_1d_burst(m_full, cal_full_dts, end_cutoff="2026-11-25")
    m_full, ix_cols, ix_meta = w2f.build_mechanism_interactions(m_full)
    m_full["mkt10_zt_est_t1"] = (m_full["L1_zt_cnt_t1"] - m_full["mkt20_zt_cnt_t1"]).astype(np.float32)

    pools = {}
    atom_info = {}
    for st in ALL6:
        sub = m_full[m_full["strategy"] == st].sort_values(["buy_date", "code"]).reset_index(drop=True)
        sub = w2f.attach_strategy_sim_cols(sub, st)
        # Attach extra rd028 fields if not already attached (e.g., buy_price, open_pct, prev_is_yizi, buyable_open)
        oh = pd.read_parquet(f"{RD028}/pool_{st}_oldhot.parquet").sort_values(["buy_date", "code"]).reset_index(drop=True)
        oh["buy_date"] = oh["buy_date"].astype(str).str[:10]
        oh["code"] = oh["code"].astype(str).str.zfill(6)
        extra_oh = [c for c in ["buy_price", "prev_is_yizi", "buyable_open", "v20_pen"] if c in oh.columns and c not in sub.columns]
        if extra_oh:
            sub = sub.merge(oh[["buy_date", "code"] + extra_oh], on=["buy_date", "code"], how="left")
        sub["net_ret_020"] = pd.to_numeric(sub["net_ret"], errors="coerce").astype(np.float64)
        sub["net_ret_030"] = convert_fee(sub["net_ret_020"], 0.0030)
        sub["net_ret_050"] = convert_fee(sub["net_ret_020"], 0.0050)
        sub["net_ret_080"] = convert_fee(sub["net_ret_020"], 0.0080)
        sub["net_ret"] = sub["net_ret_030"]
        if st == "20cm":
            is_yz = pd.to_numeric(sub["open_pct"], errors="coerce").fillna(0.0) >= 0.195
        else:
            is_yz = pd.to_numeric(sub["open_pct"], errors="coerce").fillna(0.0) >= 0.095
            if "prev_is_yizi" in sub.columns:
                is_yz = is_yz | sub["prev_is_yizi"].fillna(False).to_numpy(bool)
        sub["is_yizi"] = is_yz.astype(bool)
        sub["can_buy_hygiene"] = (~sub["is_yizi"]) & sub["sim_ok"].fillna(True).to_numpy(bool) & sub["net_ret"].notna()
        sub["is_liq_2yi"] = pd.to_numeric(sub["sd_amount_yi_t1"], errors="coerce").fillna(0.0) >= 2.0
        pools[st] = sub

        if st in OTHER5:
            if st == "1to2":
                acols, amat = _build_1to2_contrib(sub)
            else:
                acols = sorted([c for c in sub.columns if c.startswith(ATOMIC_PREFIXES[st])])
                amat = sub[acols].fillna(0.0).to_numpy(np.float64)
            atom_info[st] = {"cols": acols, "contrib_mat": amat}

    del m_full
    gc.collect()

    # Preload bars once and build exact 5Y MTM segments (at 0.20%, 0.30%, 0.50%, 0.80%)
    bar_lu = preload_exact_bars(list(pools.values()), v20_ctx["v20_ledger"], cal_5y)
    for st, df in pools.items():
        segs_020 = build_mtm_segments_5y(df, cal_5y, bar_lu, is_20cm=(st == "20cm"))
        df["mtm_5y_020"] = segs_020
        df["mtm_wf_020"] = [tuple((ti - wf_off, mult) for ti, mult in s if 0 <= (ti - wf_off) < T_wf) for s in segs_020]
        df["mtm_wf_030"] = [scale_mtm_segs(s, r20, r30) for s, r20, r30 in zip(df["mtm_wf_020"], df["net_ret_020"], df["net_ret_030"])]
        df["mtm_wf_050"] = [scale_mtm_segs(s, r20, r50) for s, r20, r50 in zip(df["mtm_wf_020"], df["net_ret_020"], df["net_ret_050"])]
        df["mtm_wf_080"] = [scale_mtm_segs(s, r20, r80) for s, r20, r80 in zip(df["mtm_wf_020"], df["net_ret_020"], df["net_ret_080"])]

    # Verify 100% 0.20% baseline parity on all 6 strategies + V20 combined
    parity = verify_baselines_020(pools, v20_ctx)

    # Feature group lists (strictly entry-time PIT, zero leakage)
    xtr_cols = sorted([c for c, v in cat.items() if v["role"] == "cross_transplant_factor" and c in pools["1to2"].columns])
    entry_num = sorted([c for c, v in cat.items() if v["role"] == "entry_feature" and v["dtype"] != "object" and c in pools["1to2"].columns])
    base_dyn_cols = w2f.select_base_single_factors_for_dyn(pools["1to2"])
    # Ensure mkt10_zt_est_t1 is in base_dyn_cols
    if "mkt10_zt_est_t1" not in base_dyn_cols:
        base_dyn_cols.append("mkt10_zt_est_t1")

    # Prebuild baseline WF 0.30% slots for all 6 strategies & V20 combined 0.30% reference
    import w2a1_data_and_eval as w21_de
    untrig = w21_de._load_untrig_lean(pools)

    base_slots_030 = {}
    for st in ALL6:
        _, sl = sim_strategy(st, pools[st], pools[st]["orig_score"].to_numpy(float), wf_only=False)
        sl = sl[sl["buy_date"].between(WF_START, WF_END)].copy().reset_index(drop=True)
        sl["score"] = sl["orig_score"].astype(float)
        sl["tier"] = [tpe.assign_physical_tier(st, sc) for sc in sl["score"]]
        sl["net_ret"] = sl["net_ret_030"]
        base_slots_030[st] = sl

    # Load csi1000 daily returns if available for extra benchmark context
    cal_wf_df = v20_ctx["calendar_5y"]
    cal_wf_df = cal_wf_df[cal_wf_df["trade_date"].between(WF_START, WF_END)].sort_values("trade_date").reset_index(drop=True)

    bundle = {
        "pools": pools,
        "atom_info": atom_info,
        "untrig": untrig,
        "v20_ctx": v20_ctx,
        "cal_5y": cal_5y,
        "cal_wf": cal_wf,
        "cal_wf_df": cal_wf_df,
        "ix_cols": ix_cols,
        "ix_meta": ix_meta,
        "xtr_cols": xtr_cols,
        "entry_num": entry_num,
        "base_dyn_cols": base_dyn_cols,
        "parity_020": parity,
        "base_slots_030": base_slots_030,
    }
    bundle["base_comb_030"] = eval_v20_combined(bundle, {}, fee_rt=0.0030)

    with open(cache_path, "wb") as f:
        pickle.dump(bundle, f)
    return bundle


def sim_strategy(
    strat: str,
    df: pd.DataFrame,
    score_vec: np.ndarray,
    thr: float | np.ndarray | None = None,
    mask: Optional[np.ndarray] = None,
    wf_only: bool = True,
    high_cb_mode: str = "v51_exact",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Unified exact single-slot simulator for `1to2`, `2to3`, `3to4`, `high`, `pry`, `20cm`."""
    sc = np.asarray(score_vec, dtype=np.float64)
    if strat == "1to2":
        tv = df["thr_vec"].to_numpy(float) if thr is None else np.broadcast_to(np.asarray(thr, float), len(df))
        m_t1 = df["elig_t1"].to_numpy(bool) & (sc >= tv)
        m_t2 = df["elig_t2"].to_numpy(bool)
        m_mon = df["elig_mon"].to_numpy(bool) & (sc >= tv)
        m_dom = df["elig_dom295"].to_numpy(bool) & ((sc - df["sc_t3_pen"].to_numpy(float)) >= 295.0)
        tot_v18 = m_t1 | m_t2 | m_mon
        tot_v19 = tot_v18 | m_dom
        if wf_only and "wf_in_window" in df.columns:
            wf_m = df["wf_in_window"].fillna(False).to_numpy(bool)
            tot_v19 &= wf_m
            tot_v18 &= wf_m
        elif wf_only:
            wf_m = (df["buy_date"] >= WF_START).to_numpy(bool)
            tot_v19 &= wf_m
            tot_v18 &= wf_m
        if mask is not None:
            mk = np.asarray(mask, dtype=bool)
            tot_v19 &= mk
            tot_v18 &= mk
        if not tot_v19.any():
            return df.iloc[:0].copy(), df.iloc[:0].copy()
        sv = np.where(m_t1 | m_t2, sc + 1000.0, np.where(m_mon, sc, sc + 500.0))
        sub = df[tot_v19].copy()
        sub["_sv"] = sv[tot_v19]
        sub["_sc_adj"] = sc[tot_v19]
        sub["_is_v18"] = tot_v18[tot_v19]
        bad_dts, dom_no_d = set(), set()
        for d, grp in sub.groupby("buy_date", sort=False):
            if (grp["rk_theme"] == 1).any() and grp.sort_values("_sv", ascending=False).iloc[0]["rk_theme"] >= 4:
                bad_dts.add(d)
            t1_p = grp["t1_dom_plate"].iloc[0]
            if t1_p:
                v18g = grp[grp["_is_v18"]]
                if not (len(v18g) > 0 and (v18g["plate"] == t1_p).any()):
                    dom_no_d.add(d)
        keep = (~sub["buy_date"].isin(bad_dts)) & (~(sub["buy_date"].isin(dom_no_d) & (sub["rk_theme"] == 3)))
        sub = sub[keep].sort_values(["buy_date", "_sv", "code"], ascending=[True, False, True], kind="mergesort")
        taken_idx, fdt, fop = [], "", False
        for d2, grp in sub.groupby("buy_date", sort=True):
            if fdt == "" or d2 > fdt or (d2 == fdt and fop):
                top = grp.iloc[0]
                if bool(top["sim_ok"]) and bool(top["can_buy_hygiene"]):
                    taken_idx.append(top.name)
                    fdt, fop = str(top["exit_date"]), bool(top["exit_at_open"])
        pass_df = sub[sub["sim_ok"].astype(bool) & sub["can_buy_hygiene"].astype(bool)].copy().reset_index(drop=True)
        slot_df = sub.loc[taken_idx].copy().reset_index(drop=True) if taken_idx else sub.iloc[:0].copy()
        return pass_df, slot_df

    thr_use = ORIG_THRESHOLDS[strat] if thr is None else thr
    m = df["can_buy_hygiene"].fillna(True).to_numpy(bool) & np.isfinite(sc)
    if isinstance(thr_use, np.ndarray):
        m &= (sc >= thr_use)
    else:
        m &= (sc >= float(thr_use))
    if wf_only:
        if "wf_in_window" in df.columns:
            m &= df["wf_in_window"].fillna(False).to_numpy(bool)
        else:
            m &= (df["buy_date"] >= WF_START).to_numpy(bool)
    if mask is not None:
        m &= np.asarray(mask, dtype=bool)
    sub = df[m].copy()
    if sub.empty:
        return sub, sub
    sub["_sc_adj"] = sc[m]

    if strat == "2to3":
        srt = sub.sort_values(["buy_date", "_sc_adj", "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True], kind="mergesort")
        t_idx, fdt, fhh = [], "", 0
        for r in srt.itertuples():
            if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
                t_idx.append(r.Index)
                fdt, fhh = str(r.exit_date), int(r.exit_hhmm)
        return srt.reset_index(drop=True), srt.loc[t_idx].copy().reset_index(drop=True)

    if strat == "3to4":
        pt = pd.to_numeric(sub["prio_tie"], errors="coerce").fillna(0.0).to_numpy(float)
        sub["_prio"] = sub["_sc_adj"] * 10.0 + pt * 0.1
        srt = sub.sort_values(["buy_date", "buy_hhmm", "_prio", "code"], ascending=[True, True, False, True], kind="mergesort")
        t_idx, fdt, fhh = [], "", 0
        for r in srt.itertuples():
            if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
                t_idx.append(r.Index)
                fdt, fhh = str(r.exit_date), int(r.exit_hhmm)
        return sub.reset_index(drop=True), srt.loc[t_idx].copy().reset_index(drop=True)

    if strat == "high":
        srt = sub.sort_values(["buy_date", "_sc_adj", "code"], ascending=[True, False, True], kind="mergesort")
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
                is_cb = bool(r.v51_cb_loss) if (high_cb_mode == "v51_exact" and "v51_cb_loss" in srt.columns) else (float(r.net_ret) < -0.02)
                if is_cb:
                    cl += 1
                    sk = (cl >= 2)
                elif float(r.net_ret) > 0.0:
                    cl = 0
        return sub.reset_index(drop=True), srt.loc[t_idx].copy().reset_index(drop=True)

    if strat == "pry":
        b10 = pd.to_numeric(sub["bias10"], errors="coerce").fillna(0.0).to_numpy(float) if "bias10" in sub.columns else np.zeros(len(sub))
        sub["_bias10"] = b10
        srt = sub.sort_values(["buy_date", "_sc_adj", "_bias10", "code"], ascending=[True, False, True, True], kind="mergesort")
        t_idx, fdt = [], ""
        for r in srt.itertuples():
            if (not fdt) or (r.buy_date > fdt):
                t_idx.append(r.Index)
                fdt = str(r.exit_date)
        return sub.reset_index(drop=True), srt.loc[t_idx].copy().reset_index(drop=True)

    # 20cm
    srt = sub.sort_values(["buy_date", "_sc_adj", "code"], ascending=[True, False, True], kind="mergesort")
    t_idx, fd = [], ""
    for r in srt.itertuples():
        if (not fd) or (r.buy_date > fd):
            t_idx.append(r.Index)
            fd = str(r.exit_date)
    return sub.reset_index(drop=True), srt.loc[t_idx].copy().reset_index(drop=True)


def verify_baselines_020(pools: dict[str, pd.DataFrame], v20_ctx: dict) -> dict:
    """Assert 100% baseline parity at 0.20% round-trip cost for all 6 strategies."""
    rep = {}
    for st, (exp_n, exp_nav) in EXPECTED_PARITY_020.items():
        df = pools[st].copy()
        df["net_ret"] = df["net_ret_020"]
        _, sl = sim_strategy(st, df, df["orig_score"].to_numpy(float), wf_only=False)
        nav = float(np.prod(1.0 + sl["net_ret"].to_numpy(float)))
        assert len(sl) == exp_n, f"{st} parity n={len(sl)} != {exp_n}"
        assert abs(nav - exp_nav) < 0.05, f"{st} parity nav={nav} != {exp_nav}"
        rep[st] = {"n": int(len(sl)), "nav_020": round(nav, 4), "pass": True}
    return rep


def build_exact_dr(slot_df: pd.DataFrame, T_wf: int, mtm_col: str = "mtm_wf_030", ret_col: str = "net_ret_030") -> tuple[np.ndarray, float]:
    """Compute exact close-to-close daily MTM return array of length T_wf (936 trading days)."""
    if slot_df.empty:
        return np.zeros(T_wf, dtype=np.float64), 0.0
    day_mult = np.ones(T_wf, dtype=np.float64)
    for segs in slot_df[mtm_col]:
        for ti, mult in segs:
            if 0 <= ti < T_wf:
                day_mult[ti] *= float(mult)
    dr = day_mult - 1.0
    rets = slot_df[ret_col].to_numpy(float) if ret_col in slot_df.columns else slot_df["net_ret"].to_numpy(float)
    tr_nav = float(np.prod(1.0 + rets))
    return dr, abs(float(np.prod(day_mult)) - tr_nav)


def compute_window_metrics(
    dr: np.ndarray,
    slot_df: pd.DataFrame,
    cal_wf: list[str],
    csi_arr: np.ndarray,
    ew_arr: np.ndarray,
    s_dt: str,
    e_dt: str,
    ret_col: str = "net_ret_030",
) -> dict:
    mask = np.array([(s_dt <= d <= e_dt) for d in cal_wf], dtype=bool)
    T_w = int(mask.sum())
    if T_w == 0:
        return {"n": 0, "nav": 1.0, "sharpe": 0.0, "mdd_pct": 0.0}
    dw = dr[mask]
    c3 = csi_arr[mask]
    ew = ew_arr[mask]
    mtm_nav = float(np.prod(1.0 + dw))
    c3_pct = (float(np.prod(1.0 + c3)) - 1.0) * 100.0
    ew_pct = (float(np.prod(1.0 + ew)) - 1.0) * 100.0

    sd = float(np.std(dw, ddof=1)) if T_w > 1 else 0.0
    sharpe = float(np.mean(dw) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    curve = np.concatenate([[1.0], np.cumprod(1.0 + dw)])
    pk = np.maximum.accumulate(curve)
    mdd = float(np.max((pk - curve) / pk) * 100.0)
    cagr = (mtm_nav ** (TRD_DAYS_YEAR / T_w) - 1.0) * 100.0 if mtm_nav > 0 else -100.0

    sub = slot_df[slot_df["buy_date"].between(s_dt, e_dt)] if (slot_df is not None and not slot_df.empty) else pd.DataFrame()
    if sub.empty:
        return {
            "n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0, "nav": 1.0, "mtm_nav": round(mtm_nav, 4),
            "ex_top3_nav": 1.0, "ex_top5_nav": 1.0, "mdd_pct": round(mdd, 2), "sharpe": round(sharpe, 3),
            "cagr_pct": round(cagr, 2), "excess_csi300_pp": round(-c3_pct, 2), "excess_ew_pp": round(-ew_pct, 2),
        }
    rets = sub[ret_col].to_numpy(float) if ret_col in sub.columns else sub["net_ret"].to_numpy(float)
    w, l = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    tr_nav = float(np.prod(1.0 + rets))
    sr = np.sort(rets)
    ex3 = float(np.prod(1.0 + sr[:-3])) if len(rets) > 3 else 1.0
    ex5 = float(np.prod(1.0 + sr[:-5])) if len(rets) > 5 else 1.0
    return {
        "n": int(len(rets)), "wr_pct": round(wr, 2), "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav": round(tr_nav, 4), "mtm_nav": round(mtm_nav, 4),
        "ex_top3_nav": round(ex3, 4), "ex_top5_nav": round(ex5, 4),
        "mdd_pct": round(mdd, 2), "sharpe": round(sharpe, 3), "cagr_pct": round(cagr, 2),
        "excess_csi300_pp": round((tr_nav - 1.0) * 100.0 - c3_pct, 2),
        "excess_ew_pp": round((tr_nav - 1.0) * 100.0 - ew_pct, 2),
    }


def eval_v20_combined(bundle: dict, replace_slots: dict[str, pd.DataFrame], fee_rt: float = 0.0030) -> dict:
    """Plug modified strategy slot_df(s) into V20.0 6-strategy pure single-slot engine over WF [2023-01-03..2026-11-16]."""
    cal_wf_df = bundle["cal_wf_df"]
    cal_wf = bundle["cal_wf"]
    T_wf = len(cal_wf)
    csi_arr = cal_wf_df["csi300_daily_ret"].to_numpy(float)
    ew_arr = cal_wf_df["alla_ew_daily_ret"].to_numpy(float)
    mtm_col = {0.0030: "mtm_wf_030", 0.0050: "mtm_wf_050", 0.0080: "mtm_wf_080"}.get(round(fee_rt, 4), "mtm_wf_030")
    ret_col = {0.0030: "net_ret_030", 0.0050: "net_ret_050", 0.0080: "net_ret_080"}.get(round(fee_rt, 4), "net_ret_030")

    parts = []
    trig_dts = {}
    cols = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", mtm_col]
    for st in ALL6:
        if st in replace_slots:
            df = replace_slots[st]
            df = df[df["buy_date"].between(WF_START, WF_END)].copy()
            if not df.empty:
                df["strategy"] = st
                if "_sc_adj" in df.columns:
                    df["score"] = df["_sc_adj"].astype(float)
                elif "score" not in df.columns:
                    df["score"] = df["orig_score"].astype(float)
                df["tier"] = [tpe.assign_physical_tier(st, sc) for sc in df["score"]]
                df["net_ret"] = df[ret_col] if ret_col in df.columns else convert_fee(df["net_ret_020"], fee_rt)
                if mtm_col not in df.columns:
                    df[mtm_col] = [scale_mtm_segs(s, r20, nr) for s, r20, nr in zip(df["mtm_wf_020"], df["net_ret_020"], df["net_ret"])]
                parts.append(df[cols])
            trig_dts[st] = set(df["buy_date"]) if not df.empty else set()
        else:
            sl = bundle["base_slots_030"][st].copy()
            sl["net_ret"] = sl[ret_col] if ret_col in sl.columns else convert_fee(sl["net_ret_020"], fee_rt)
            if mtm_col not in sl.columns:
                sl[mtm_col] = [scale_mtm_segs(s, r20, nr) for s, r20, nr in zip(sl["mtm_wf_020"], sl["net_ret_020"], sl["net_ret"])]
            trig_dts[st] = set(sl["buy_date"])
            parts.append(sl[cols])

    pool6 = pd.concat(parts, ignore_index=True)
    pool6["buy_price_val"] = np.nan
    pool6["is_adj_px"] = False
    pool6["is_untrig"] = False

    ut = bundle["untrig"][bundle["untrig"]["buy_date"].between(WF_START, WF_END)].copy()
    ut_parts = []
    for st_u in ("3to4", "high", "1to2"):
        sub_u = ut[(ut["strategy"] == st_u) & (~ut["buy_date"].isin(trig_dts.get(st_u, set())))].copy()
        if sub_u.empty:
            continue
        thr_u = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[st_u]
        sub_u = sub_u[sub_u["score"] >= thr_u].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
        ut_parts.append(sub_u)
    ut_final = pd.concat(ut_parts, ignore_index=True) if ut_parts else pd.DataFrame()
    if not ut_final.empty:
        ut_final["is_untrig"] = True
        ut_final["net_ret"] = 0.0
        ut_final["buy_price_val"] = np.nan
        ut_final["is_adj_px"] = False
        ut_final = ut_final[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig"]]

    mtm_map = {(r.strategy, r.buy_date, r.code): getattr(r, mtm_col) for r in pool6.itertuples(index=False)}
    tr_df, _ = tpe.run_single_slot(
        pool6.drop(columns=[mtm_col]),
        lambda d: d["tier"].map(m1.S2C_MAP).fillna(999).to_numpy(),
        untrig_df=ut_final,
        timing_mode="s_tier_reserve_only",
    )
    if tr_df.empty:
        return {"n": 0, "nav_wf": 1.0, "sharpe": 0.0, "mdd_pct": 0.0, "nav_2526": 1.0, "nav_y26": 1.0, "nav_26h2": 1.0}
    tr_df[mtm_col] = [mtm_map[(r.strategy, r.buy_date, r.code)] for r in tr_df.itertuples(index=False)]
    dr_comb, _ = build_exact_dr(tr_df, T_wf, mtm_col=mtm_col, ret_col="net_ret")
    fw = compute_window_metrics(dr_comb, tr_df, cal_wf, csi_arr, ew_arr, WF_START, WF_END, ret_col="net_ret")
    y2526 = compute_window_metrics(dr_comb, tr_df, cal_wf, csi_arr, ew_arr, "2025-01-01", WF_END, ret_col="net_ret")
    y26 = compute_window_metrics(dr_comb, tr_df, cal_wf, csi_arr, ew_arr, "2026-01-01", WF_END, ret_col="net_ret")
    y26h2 = compute_window_metrics(dr_comb, tr_df, cal_wf, csi_arr, ew_arr, "2026-07-01", WF_END, ret_col="net_ret")
    target_n = int((tr_df["strategy"] == list(replace_slots.keys())[0]).sum()) if len(replace_slots) == 1 else int(len(tr_df))
    return {
        "n": fw["n"], "n_target_strat": target_n,
        "nav_wf": fw["nav"], "ex5_wf": fw["ex_top5_nav"], "mdd_pct": fw["mdd_pct"], "sharpe": fw["sharpe"],
        "nav_2526": y2526["nav"], "nav_y26": y26["nav"], "nav_26h2": y26h2["nav"],
        "dr_comb": dr_comb,
    }


def perm_test_fast(slot_df: pd.DataFrame, cand_wf_df: pd.DataFrame, n_perm: int = 1000, seed: int = 20261126, ret_col: str = "net_ret_030") -> dict:
    """Fast 1,000x trading-day permutation test (same-day stock pick & any-candidate-day timing+pick)."""
    n_tr = len(slot_df)
    if n_tr < 3 or cand_wf_df.empty:
        return {"same_day_p_nav": 1.0, "any_cand_day_p_nav": 1.0}
    rng = np.random.default_rng(seed)
    obs_rets = slot_df[ret_col].to_numpy(float) if ret_col in slot_df.columns else slot_df["net_ret"].to_numpy(float)
    obs_nav = float(np.prod(1.0 + obs_rets))
    by_dt = {d: g[ret_col].to_numpy(float) for d, g in cand_wf_df.groupby("buy_date")}
    day_arrs = list(by_dt.values())
    n_days = len(day_arrs)

    same_cols = [by_dt.get(d, obs_rets)[rng.integers(0, len(by_dt.get(d, obs_rets)), size=n_perm)] for d in slot_df["buy_date"]]
    sd_mat = np.column_stack(same_cols)
    p_sd = float((np.sum(np.prod(1.0 + sd_mat, axis=1) >= obs_nav - 1e-12) + 1) / (n_perm + 1))

    # Fast vectorized any-day sampling
    d_choices = rng.integers(0, n_days, size=(n_perm, n_tr))
    max_len = max(len(a) for a in day_arrs)
    pad_arr = np.zeros((n_days, max_len), dtype=np.float64)
    day_lens = np.empty(n_days, dtype=np.int32)
    for di, a in enumerate(day_arrs):
        L = len(a)
        day_lens[di] = L
        pad_arr[di, :L] = a
    col_idx = (rng.random((n_perm, n_tr)) * day_lens[d_choices]).astype(np.int32)
    any_mat = pad_arr[d_choices, col_idx]
    p_any = float((np.sum(np.prod(1.0 + any_mat, axis=1) >= obs_nav - 1e-12) + 1) / (n_perm + 1))
    return {"same_day_p_nav": round(p_sd, 4), "any_cand_day_p_nav": round(p_any, 4)}


def evaluate_variant_complete(
    bundle: dict,
    strat: str,
    module: str,
    variant_id: str,
    pass_df: pd.DataFrame,
    slot_df: pd.DataFrame,
    perm_n: int = 1000,
    eval_comb: bool = True,
    eval_liq: bool = True,
    liq_replay_fn=None,
) -> tuple[dict, np.ndarray]:
    """
    Evaluate any variant on EXACT daily MTM across:
      - 0.30% primary (FULL_WF, Y2023..Y2026, Y2526, Y26H1, Y26H2, ex_top3, ex_top5)
      - 0.50% and 0.80% slippage stress
      - >= 2亿 liquidity sensitivity
      - 1000x perm + paired t-test vs strategy's V20 0.30% baseline
      - V20 combined 6-strat single-slot incremental delta
    Returns (summary_row, dr_exact_030).
    """
    cal_wf_df = bundle["cal_wf_df"]
    cal_wf = bundle["cal_wf"]
    T_wf = len(cal_wf)
    csi_arr = cal_wf_df["csi300_daily_ret"].to_numpy(float)
    ew_arr = cal_wf_df["alla_ew_daily_ret"].to_numpy(float)

    s_wf = slot_df[slot_df["buy_date"].between(WF_START, WF_END)].copy().reset_index(drop=True)
    p_wf = pass_df[pass_df["buy_date"].between(WF_START, WF_END)].copy().reset_index(drop=True)
    if not s_wf.empty and "net_ret_020" not in s_wf.columns:
        # Ensure slippage cols exist
        s_wf["net_ret_020"] = s_wf["net_ret"]
    if not s_wf.empty:
        s_wf["net_ret_030"] = convert_fee(s_wf["net_ret_020"], 0.0030)
        s_wf["net_ret_050"] = convert_fee(s_wf["net_ret_020"], 0.0050)
        s_wf["net_ret_080"] = convert_fee(s_wf["net_ret_020"], 0.0080)

    dr_030, mtm_diff = build_exact_dr(s_wf, T_wf, "mtm_wf_030", "net_ret_030")
    dr_050, _ = build_exact_dr(s_wf, T_wf, "mtm_wf_050", "net_ret_050")
    dr_080, _ = build_exact_dr(s_wf, T_wf, "mtm_wf_080", "net_ret_080")

    w_res = {wn: compute_window_metrics(dr_030, s_wf, cal_wf, csi_arr, ew_arr, s, e, "net_ret_030") for wn, s, e in WINDOWS}
    fw050 = compute_window_metrics(dr_050, s_wf, cal_wf, csi_arr, ew_arr, WF_START, WF_END, "net_ret_050")
    fw080 = compute_window_metrics(dr_080, s_wf, cal_wf, csi_arr, ew_arr, WF_START, WF_END, "net_ret_080")

    # Liquidity >= 2亿 sensitivity
    if eval_liq and not s_wf.empty:
        if liq_replay_fn is not None:
            s_liq = liq_replay_fn()
        else:
            s_liq = s_wf[s_wf["is_liq_2yi"].fillna(False)].copy()
        dr_liq, _ = build_exact_dr(s_liq, T_wf, "mtm_wf_030", "net_ret_030")
        fw_liq = compute_window_metrics(dr_liq, s_liq, cal_wf, csi_arr, ew_arr, WF_START, WF_END, "net_ret_030")
    else:
        fw_liq = {"n": 0, "nav": 1.0, "sharpe": 0.0, "wr_pct": 0.0}

    # Permutation test
    df_pool = bundle["pools"][strat]
    cand_wf = df_pool[(df_pool["buy_date"].between(WF_START, WF_END)) & df_pool["can_buy_hygiene"]]
    pm = perm_test_fast(s_wf, cand_wf, n_perm=perm_n, ret_col="net_ret_030") if perm_n > 0 else {"same_day_p_nav": np.nan, "any_cand_day_p_nav": np.nan}

    # Paired t-test vs strategy V20 0.30% baseline
    b_slot = bundle["base_slots_030"][strat]
    dr_base, _ = build_exact_dr(b_slot, T_wf, "mtm_wf_030", "net_ret_030")
    diff = dr_030 - dr_base
    sd_diff = float(np.std(diff, ddof=1))
    paired_t = float(np.mean(diff) / (sd_diff / math.sqrt(T_wf))) if sd_diff > 1e-12 else 0.0
    paired_p1 = float(stats.t.sf(paired_t, df=T_wf - 1)) if paired_t > -50 else 1.0

    # V20 combined
    if eval_comb:
        comb = eval_v20_combined(bundle, {strat: s_wf}, fee_rt=0.0030)
        bc = bundle["base_comb_030"]
        comb_ratio = round(comb["nav_wf"] / max(1e-9, bc["nav_wf"]), 4)
        comb_sh_d = round(comb["sharpe"] - bc["sharpe"], 4)
        comb_mdd_d = round(comb["mdd_pct"] - bc["mdd_pct"], 2)
        comb_2526_r = round(comb["nav_2526"] / max(1e-9, bc["nav_2526"]), 4)
        comb_26_r = round(comb["nav_y26"] / max(1e-9, bc["nav_y26"]), 4)
        comb_26h2_r = round(comb["nav_26h2"] / max(1e-9, bc["nav_26h2"]), 4)
        comb_n_st = comb["n_target_strat"]
    else:
        comb_ratio = comb_sh_d = comb_mdd_d = comb_2526_r = comb_26_r = comb_26h2_r = np.nan
        comb_n_st = np.nan

    fw = w_res["FULL_WF"]
    row = {
        "strategy": strat,
        "module": module,
        "variant_id": variant_id,
        "n_pass": int(len(p_wf)),
        "n_trades": fw["n"],
        "wr_pct": fw["wr_pct"],
        "plr": fw["plr"],
        "mean_pct": fw["mean_pct"],
        "nav_wf": fw["nav"],
        "ex3_wf": fw["ex_top3_nav"],
        "ex5_wf": fw["ex_top5_nav"],
        "mdd_pct": fw["mdd_pct"],
        "exact_mtm_sharpe": fw["sharpe"],
        "excess_csi300_pp": fw["excess_csi300_pp"],
        "excess_ew_pp": fw["excess_ew_pp"],
        "mtm_diff": round(mtm_diff, 6),
        "nav_2023": w_res["Y2023"]["nav"],
        "nav_2024": w_res["Y2024"]["nav"],
        "nav_2025": w_res["Y2025"]["nav"],
        "n_2526": w_res["Y2526"]["n"],
        "wr_2526": w_res["Y2526"]["wr_pct"],
        "nav_2526": w_res["Y2526"]["nav"],
        "ex5_2526": w_res["Y2526"]["ex_top5_nav"],
        "n_2026": w_res["Y2026"]["n"],
        "wr_2026": w_res["Y2026"]["wr_pct"],
        "nav_2026": w_res["Y2026"]["nav"],
        "n_26h2": w_res["Y26H2"]["n"],
        "wr_26h2": w_res["Y26H2"]["wr_pct"],
        "nav_26h2": w_res["Y26H2"]["nav"],
        "nav_50bps": fw050["nav"],
        "sharpe_50bps": fw050["sharpe"],
        "nav_80bps": fw080["nav"],
        "sharpe_80bps": fw080["sharpe"],
        "n_liq2yi": fw_liq["n"],
        "nav_liq2yi": fw_liq["nav"],
        "sharpe_liq2yi": fw_liq["sharpe"],
        "perm_sd_p": pm["same_day_p_nav"],
        "perm_any_p": pm["any_cand_day_p_nav"],
        "paired_t": round(paired_t, 3),
        "paired_p_1sided": round(paired_p1, 5),
        "comb_nav_ratio": comb_ratio,
        "comb_sharpe_delta": comb_sh_d,
        "comb_mdd_delta": comb_mdd_d,
        "comb_2526_ratio": comb_2526_r,
        "comb_2026_ratio": comb_26_r,
        "comb_26h2_ratio": comb_26h2_r,
        "comb_n_strat": comb_n_st,
    }
    return row, dr_030


def calc_dsr(dr: np.ndarray, n_trials: int, var_sr_daily: float, sr_bench_daily: float = 0.0) -> dict:
    x = np.asarray(dr, dtype=float)
    T = len(x)
    if T < 10 or np.std(x, ddof=1) <= 1e-12:
        return {"sr_ann": 0.0, "sr0_ann": 0.0, "dsr": 0.0}
    mu = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    sr = mu / sd
    g3 = float(stats.skew(x, bias=True))
    g4 = float(stats.kurtosis(x, fisher=False, bias=True))
    gamma_em = 0.5772156649015329
    if n_trials <= 1 or var_sr_daily <= 0.0:
        sr0 = sr_bench_daily
    else:
        z1 = float(stats.norm.ppf(1.0 - 1.0 / n_trials))
        z2 = float(stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e)))
        sr0 = sr_bench_daily + math.sqrt(var_sr_daily) * ((1.0 - gamma_em) * z1 + gamma_em * z2)
    denom_in = max(1e-12, (1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * (sr ** 2)) / max(1, T - 1))
    z_dsr = (sr - sr0) / math.sqrt(denom_in)
    return {
        "sr_ann": round(sr * math.sqrt(TRD_DAYS_YEAR), 3),
        "sr0_ann": round(sr0 * math.sqrt(TRD_DAYS_YEAR), 3),
        "dsr": round(float(stats.norm.cdf(z_dsr)), 4),
    }


def cscv_pbo(mat_dict: dict[str, np.ndarray], S: int = 16, target_names: Optional[list[str]] = None) -> dict:
    """Exact Combinatorially Symmetrically Cross-Validated PBO."""
    names = list(mat_dict.keys())
    if len(names) < 2:
        return {"n_variants": len(names), "S": S, "pbo": np.nan}
    M_full = np.column_stack([np.asarray(mat_dict[k], dtype=float) for k in names])
    keep = np.std(M_full, axis=0, ddof=1) > 1e-12
    names = [nm for nm, kp in zip(names, keep) if kp]
    M = M_full[:, keep]
    K = len(names)
    if K < 2:
        return {"n_variants": K, "S": S, "pbo": np.nan}
    T_tot = M.shape[0]
    L = T_tot // S
    if L < 10:
        return {"n_variants": K, "S": S, "pbo": np.nan}
    T_use = L * S
    M = M[T_tot - T_use :, :]
    blocks = M.reshape(S, L, K)
    blk_sum = blocks.sum(axis=1)
    blk_sum2 = (blocks ** 2).sum(axis=1)
    tot_sum = blk_sum.sum(axis=0)
    tot_sum2 = blk_sum2.sum(axis=0)

    half = S // 2
    combos = list(itertools.combinations(range(S), half))
    n_splits = len(combos)
    ind = np.zeros((n_splits, S), dtype=float)
    for r_i, cmb in enumerate(combos):
        ind[r_i, list(cmb)] = 1.0
    n_is = half * L
    n_oos = T_use - n_is

    is_sum = ind @ blk_sum
    is_sum2 = ind @ blk_sum2
    is_mu = is_sum / n_is
    is_sd = np.sqrt(np.maximum(0.0, (is_sum2 - n_is * (is_mu ** 2)) / max(1, n_is - 1)))
    is_sr = np.where(is_sd > 1e-12, is_mu / np.maximum(is_sd, 1e-12) * math.sqrt(TRD_DAYS_YEAR), -999.0)

    oos_sum = tot_sum[None, :] - is_sum
    oos_sum2 = tot_sum2[None, :] - is_sum2
    oos_mu = oos_sum / n_oos
    oos_sd = np.sqrt(np.maximum(0.0, (oos_sum2 - n_oos * (oos_mu ** 2)) / max(1, n_oos - 1)))
    oos_sr = np.where(oos_sd > 1e-12, oos_mu / np.maximum(oos_sd, 1e-12) * math.sqrt(TRD_DAYS_YEAR), 0.0)

    win_idx = np.argmax(is_sr, axis=1)
    win_oos_sr = oos_sr[np.arange(n_splits), win_idx]
    ranks = np.empty(n_splits, dtype=float)
    for r_i in range(n_splits):
        row = oos_sr[r_i]
        wv = win_oos_sr[r_i]
        n_lt = float(np.sum(row < wv))
        n_eq = float(np.sum(row == wv))
        ranks[r_i] = (n_lt + 0.5 * (n_eq + 1.0)) / (K + 1.0)
    ranks_c = np.clip(ranks, 1e-4, 1.0 - 1e-4)
    logits = np.log(ranks_c / (1.0 - ranks_c))
    pbo = float(np.mean(logits <= 0.0))

    per_cand = {}
    name_to_j = {nm: j for j, nm in enumerate(names)}
    for nm in (target_names or names):
        if nm not in name_to_j:
            continue
        j = name_to_j[nm]
        m_win = win_idx == j
        per_cand[nm] = {
            "pct_is_win": round(float(m_win.mean() * 100.0), 2),
            "all_mean_oos_sr": round(float(np.mean(oos_sr[:, j])), 3),
            "all_prob_oos_neg": round(float(np.mean(oos_sr[:, j] <= 0.0)), 4),
            "win_pbo": round(float(np.mean(logits[m_win] <= 0.0)), 4) if m_win.any() else None,
        }
    return {"n_variants": K, "S": S, "n_splits": n_splits, "pbo": round(pbo, 4), "per_candidate": per_cand}
