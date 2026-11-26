#!/opt/homebrew/bin/python3.13
"""RD035 Wave 1-A Step 3: Build Master 6-Strategy Scorecard+NewFactors Matrix, Exit Bars & Comprehensive PIT Audit.

Produces (under wave1_base/):
  - pools_6strat_master_newfactors_pit.parquet (4,183 rows, all atomic + cross-transplant + 1w new factors + exit bars)
  - pool_{1to2,2to3,3to4,high,pry,20cm}_master_pit.parquet
  - wave1a_factor_catalog_and_pit_audit.json
"""
import gc
import json
import os
import sqlite3
import sys
import time
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = os.path.join(ROOT, "sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125")
OUT_DIR = os.path.join(BASE_DIR, "wave1_base")
CACHE_DIR = os.path.join(BASE_DIR, "_cache")
RD028_DIR = os.path.join(ROOT, "sim-portfolio/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125")
RD034_DIR = os.path.join(ROOT, "sim-portfolio/backtests_astock2/rd034_ashare_3layer_cycles_6strat_20261125")
RD032_DIR = os.path.join(ROOT, "sim-portfolio/backtests_astock2/rd032_6strat_decay_evolution_20261125")
RD016_DIR = os.path.join(ROOT, "sim-portfolio/backtests_astock2/rd016_famous_youzi_seats_20261117")

sys.path.insert(0, RD032_DIR)
from rd032_common import STRATS, load_csi300
from rd032_pool_loader import attach_40_evo_features, load_all_6_pools
import rd032_decay_audit as rd32_audit
import rd032_evolution_scan as rd32_evo

OLDHOT_45_COLS = [
    "list_age",
    "has_active_wave",
    "curr_wave_streak",
    "waves_3y_g15",
    "waves_5y_g15",
    "waves_3y_g20",
    "waves_5y_g20",
    "active_years_3y",
    "active_years_5y",
    "active_2b_years_3y",
    "active_2b_years_5y",
    "zt_cnt_1y",
    "zt_cnt_3y",
    "zt_cnt_5y",
    "streak3_waves_3y",
    "streak3_waves_5y",
    "streak5_waves_5y",
    "max_streak_3y",
    "max_streak_5y",
    "zt_cnt_1y_t1",
    "zt_cnt_3y_t1",
    "waves_3y_g15_t1",
    "waves_5y_g15_t1",
    "cum_turnover_1y",
    "cum_turnover_3y",
    "trap_waves_1y",
    "trap_waves_3y",
    "dd_from_1y_high",
    "dd_from_3y_high",
    "kpl_unique_plates_3y",
    "kpl_unique_plates_5y",
    "kpl_plate_switch_ratio",
    "kpl_top_plate_share",
    "cool_days_since_last_zt",
    "cool_days_since_last_2b",
    "comm_posts_1y",
    "comm_posts_3y",
    "comm_posts_1y_pct",
    "comm_posts_3y_pct",
    "xq_posts_1y_pct",
    "xq_posts_3y_pct",
    "comm_active_month_ratio_1y",
    "comm_active_month_ratio_3y",
    "cool_bin_zt",
    "cool_bin_2b",
]


def _load_base_6strat_and_atomic(end_cutoff: str, sh300, sh_idx, sz_idx, prev_td):
    """Load exact 4,183-row baseline pools <= end_cutoff with ALL 6 strategies' native atomic columns."""
    # 1. Load rd028 clean pools + rd032 atomic loaders
    rd32_pools = load_all_6_pools(end_cutoff, prev_td, sh_idx, sz_idx, rebuild_1to2=False)
    c12_full = pd.read_parquet(os.path.join(RD032_DIR, "cache_1to2_atomic_703.parquet"))
    c12_full = c12_full[c12_full["buy_date"] <= end_cutoff].copy()
    c12_full["code"] = c12_full["code"].astype(str).str.zfill(6)

    frames = []
    parity_checks = {}

    for st in STRATS:
        po = pd.read_parquet(os.path.join(RD028_DIR, f"pool_{st}_oldhot.parquet"))
        po["buy_date"] = po["buy_date"].astype(str).str[:10]
        po["code"] = po["code"].astype(str).str.zfill(6)
        po = po[po["buy_date"] <= end_cutoff].copy().reset_index(drop=True)

        # Standardize core ID / target / meta columns
        po["strategy"] = st
        po["entry_date"] = po["buy_date"]
        po["orig_score"] = po["v20_score"].astype(np.float32)
        po["orig_pass"] = po["is_pass_official"].astype(np.int8)
        po["ret"] = po["net_ret"].astype(np.float32)

        if "buy_price" not in po.columns and "buy_px" in po.columns:
            po["buy_price"] = po["buy_px"]
        if "exit_price" not in po.columns and "exit_px" in po.columns:
            po["exit_price"] = po["exit_px"]
        if "exit_reason" not in po.columns:
            po["exit_reason"] = ""
        if "hold_bars" not in po.columns:
            po["hold_bars"] = po["hold_days"] if "hold_days" in po.columns else np.nan
        if "plate" not in po.columns:
            po["plate"] = ""
        if "sig_date" not in po.columns:
            po["sig_date"] = po["buy_date"].map(prev_td)
        po["sig_date"] = po["sig_date"].fillna(po["buy_date"].map(prev_td)).astype(str).str[:10]

        # Rename RD030 old-hot 45 columns -> oh_*
        for c in OLDHOT_45_COLS:
            if c in po.columns:
                po[f"oh_{c}"] = po[c]

        # Attach 40 RD032 evo_* features strictly <= end_cutoff
        po_evo_dict = attach_40_evo_features({st: po.copy()}, end_cutoff, prev_td, sh_idx, sz_idx)
        po_e = po_evo_dict[st]
        po_e = po_e.loc[:, ~po_e.columns.duplicated()].reset_index(drop=True)
        evo_cols = [c for c in po_e.columns if c.startswith("evo_")]
        for c in evo_cols:
            po[c] = po_e[c].astype(np.float32).values

        # Attach native atomic factors with strategy prefix & parity check
        if st == "1to2":
            m12 = po[["buy_date", "code", "v20_pen", "base_score"]].merge(c12_full, on=["buy_date", "code"], how="left")
            assert len(m12) == len(po)
            m12["atom_v20_fb20_pen"] = (m12["v20_pen"].fillna(0) < 0).astype(np.float32)
            m12["atom_xq_cold"] = (m12["xq_pre_d2"].fillna(0) < 4).astype(np.float32)
            atom_c = [c for c in m12.columns if c.startswith("atom_")] + [
                "s_prior_wk",
                "s_quant_dual",
                "score_active",
                "xq_pre_d2",
                "lhb_lh_cnt_d1",
                "surf_yz_d1",
                "plate_d2_yizi_cnt",
                "d1_seal_tightness",
                "p_sz",
                "s_elo",
                "p_elo",
                "first_seal_time",
                "open_board_count",
            ]
            for c in atom_c:
                po[f"s12_{c}"] = pd.to_numeric(m12[c], errors="coerce").astype(np.float32).values
            diff12 = float((po["base_score"].astype(float) - po["s12_score_active"].astype(float)).abs().max())
            parity_checks["1to2"] = {"base_intercept": "score_active", "max_abs_diff": diff12, "n_atomic": len(atom_c)}
            assert diff12 < 1e-4, f"1to2 atomic parity fail: {diff12}"

        elif st in ("2to3", "3to4", "high", "pry"):
            pr = rd32_pools[st].copy()
            pr["buy_date"] = pr["buy_date"].astype(str).str[:10]
            pr["code"] = pr["code"].astype(str).str.zfill(6)
            af_cols = [c for c in pr.columns if c.startswith("af_")]
            pref = {"2to3": "s23_", "3to4": "s34_", "high": "shigh_", "pry": "spry_"}[st]
            intercept = {"2to3": 60.0, "3to4": 78.0, "high": 60.0, "pry": 100.0}[st]
            mr = po[["buy_date", "code", "base_score"]].merge(pr[["buy_date", "code"] + af_cols], on=["buy_date", "code"], how="left")
            assert len(mr) == len(po) and mr[af_cols[0]].notna().all(), f"{st} atomic join missing!"
            for c in af_cols:
                po[f"{pref}{c}"] = mr[c].astype(np.float32).values
            recon = intercept + mr[af_cols].sum(axis=1)
            diff_r = float((mr["base_score"].astype(float) - recon).abs().max())
            parity_checks[st] = {"base_intercept": intercept, "max_abs_diff": diff_r, "n_atomic": len(af_cols)}
            assert diff_r < 1e-4, f"{st} atomic parity fail: {diff_r}"

        elif st == "20cm":
            f_cols = [f"F0{i}_" + suf for i, suf in [
                (1, "open_gap"),
                (2, "rfm_le20"),
                (3, "dist3d30_ge10"),
                (4, "zt60d_ge2"),
                (5, "seal_ratio_ge10_pen"),
                (6, "inst_net_pos"),
                (7, "mkt10_zt_gt55"),
                (8, "yizi20_siphon_pen"),
                (9, "monday_pen"),
            ]]
            for c in f_cols:
                po[f"s20cm_{c}"] = po[c].astype(np.float32)
            recon = 70.0 + po[f_cols].sum(axis=1)
            diff20 = float((po["base_score"].astype(float) - recon).abs().max())
            parity_checks["20cm"] = {"base_intercept": 70.0, "max_abs_diff": diff20, "n_atomic": len(f_cols)}
            assert diff20 < 1e-4, f"20cm atomic parity fail: {diff20}"

        # Select unified core identifier/target columns + strategy-prefixed/oh/evo columns
        base_keep = [
            "strategy",
            "buy_date",
            "entry_date",
            "exit_date",
            "sig_date",
            "code",
            "name",
            "base_score",
            "v20_score",
            "orig_score",
            "is_pass_official",
            "orig_pass",
            "net_ret",
            "ret",
            "buy_hhmm",
            "exit_hhmm",
            "buy_price",
            "exit_price",
            "sim_ok",
            "open_pct",
            "hold_bars",
            "exit_reason",
            "plate",
            "is_s_tier",
            "is_edge_cand",
            "is_near_line",
            "is_obs_a76",
            "is_standalone_slot1",
            "is_v20_slot1",
            "pool_layer",
            "year",
            "era_tag",
            "is_oos_split",
        ]
        dyn_cols = [
            c
            for c in po.columns
            if c.startswith(("oh_", "evo_", "s12_", "s23_", "s34_", "shigh_", "spry_", "s20cm_"))
        ]
        frames.append(po[base_keep + dyn_cols])

    master = pd.concat(frames, ignore_index=True)
    # Harmonize boolean/int flag dtypes cleanly across 6 pools
    for c in ["is_pass_official", "orig_pass", "sim_ok", "is_s_tier", "is_edge_cand", "is_near_line", "is_obs_a76", "is_standalone_slot1", "is_v20_slot1"]:
        master[c] = master[c].fillna(0).astype(np.int8)
    master["is_oos_split"] = master["is_oos_split"].fillna("").astype(str)
    for c in ["base_score", "v20_score", "orig_score", "net_ret", "ret", "buy_price", "exit_price", "open_pct", "hold_bars"]:
        master[c] = pd.to_numeric(master[c], errors="coerce").astype(np.float32)

    print(f"[Step3] Base+Atomic+OldHot+Evo loaded ({len(master)} rows, parity={ {k: round(v['max_abs_diff'], 7) for k, v in parity_checks.items()} })")
    return master, parity_checks


def _attach_bars_abn_rd25_and_exit_bars(master: pd.DataFrame, end_cutoff: str, full_cal: np.ndarray, prev_td_map: dict):
    """Compute generalized ABN 30d200 features, RD025 extra features, and forward exit bars (b0, tp1..tp4)."""
    t0 = time.time()
    pool_codes = set(master["code"].unique())

    cols_bar = ["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "turn"]
    df_a = pd.read_parquet(os.path.join(ROOT, "sim-portfolio/data/cn_hk_price_db/a_daily.parquet"), columns=cols_bar)
    df_d = pd.read_parquet(os.path.join(ROOT, "sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"), columns=cols_bar)
    bars = pd.concat([df_a, df_d], ignore_index=True)
    del df_a, df_d
    gc.collect()

    bars["c6"] = bars["ticker"].astype(str).str[:6]
    suf = bars["ticker"].astype(str).str[-3:]
    bars["dt"] = pd.to_datetime(bars["date"]).dt.strftime("%Y-%m-%d")
    bars = bars[
        bars["c6"].isin(pool_codes)
        & suf.isin([".SH", ".SZ"])
        & (bars["dt"] >= "2020-09-01")
        & (bars["dt"] <= end_cutoff)
        & (bars["close"] > 0)
        & (bars["adj_close"] > 0)
    ].copy()
    bars = bars.sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    # Compute causal daily indicators for ABN / RD25 / Exit Bars
    with open(os.path.join(ROOT, "sim-portfolio/data/st_universe.json")) as f:
        d_st = json.load(f)
    st_set = set(str(x)[-6:] for x in (d_st.get("codes", d_st) if isinstance(d_st, dict) else d_st))

    g = bars.groupby("c6", sort=False)
    prev_adj = g["adj_close"].shift(1)
    prev_close_raw = prev_adj * (bars["close"] / bars["adj_close"])
    bars["adj_factor"] = (bars["adj_close"] / bars["close"]).astype(np.float32)
    bars["ret_1d"] = ((bars["adj_close"] / prev_adj - 1.0) * 100.0).astype(np.float32)
    bars["open_pct_b"] = ((bars["open"] / prev_close_raw - 1.0) * 100.0).astype(np.float32)
    hl = (bars["high"] - bars["low"]).values
    bars["clv"] = np.where(hl > 1e-6, (bars["close"].values - bars["low"].values) / hl, 0.5).astype(np.float32)
    bars["amp_1d"] = np.where(prev_close_raw > 0, hl / prev_close_raw * 100.0, np.nan).astype(np.float32)
    bars["body_pct"] = np.where(bars["open"] > 0, (bars["close"] - bars["open"]) / bars["open"] * 100.0, 0.0).astype(np.float32)

    is_20 = bars["c6"].str.startswith(("30", "688", "689")).values
    is_st = bars["c6"].isin(st_set).values
    lim = np.where(is_20, 0.20, np.where(is_st & (bars["dt"].values < "2026-07-06"), 0.05, 0.10))
    zt_px = np.round(prev_close_raw.values * (1.0 + lim), 2)
    dt_px = np.round(prev_close_raw.values * (1.0 - lim), 2)
    vp = prev_close_raw.notna().values & (prev_close_raw.values > 0)
    non_st = ~is_st

    bars["is_zt"] = (vp & non_st & (bars["close"].values >= zt_px - 1e-4) & (bars["close"].values >= bars["high"].values - 1e-4)).astype(np.int8)
    bars["is_dt"] = (vp & non_st & (bars["close"].values <= dt_px + 1e-4) & (bars["close"].values <= bars["low"].values - 1e-4)).astype(np.int8)
    bars["is_yizi_zt"] = ((bars["is_zt"] == 1) & (bars["open"].values >= zt_px - 1e-4) & (bars["low"].values >= zt_px - 1e-4)).astype(np.int8)
    bars["is_yizi_dt"] = ((bars["is_dt"] == 1) & (bars["open"].values <= dt_px + 1e-4) & (bars["high"].values <= dt_px + 1e-4)).astype(np.int8)

    # K-line flags on bar itself (used as T-1 -> d1 on buy_date)
    is_green_close = (bars["close"].values > prev_close_raw.values)
    is_c_gt_o = (bars["close"].values > bars["open"].values)
    bars["k_is_yang"] = is_c_gt_o.astype(np.int8)
    bars["k_is_fake_yin"] = ((~is_c_gt_o) & is_green_close).astype(np.int8)
    bars["k_is_true_yin"] = ((~is_c_gt_o) & (~is_green_close)).astype(np.int8)
    bars["k_upper_shad"] = np.where(hl > 1e-6, (bars["high"].values - np.maximum(bars["open"].values, bars["close"].values)) / hl, 0.0).astype(np.float32)
    bars["k_lower_shad"] = np.where(hl > 1e-6, (np.minimum(bars["open"].values, bars["close"].values) - bars["low"].values) / hl, 0.0).astype(np.float32)

    # Yang streak, zt_streak, rolling 5d/10d/30d/60d features
    c6_v = bars["c6"].values
    zt_v = bars["is_zt"].values
    yg_v = bars["k_is_yang"].values
    streak = np.zeros(len(bars), dtype=np.int16)
    ystk = np.zeros(len(bars), dtype=np.int16)
    cs, cy, pc = 0, 0, ""
    for i in range(len(bars)):
        if c6_v[i] != pc:
            cs, cy, pc = 0, 0, c6_v[i]
        cs = cs + 1 if zt_v[i] else 0
        cy = cy + 1 if yg_v[i] else 0
        streak[i] = cs
        ystk[i] = cy
    bars["streak"] = streak
    bars["yang_streak"] = ystk

    g2 = bars.groupby("c6", sort=False)
    bars["ma5"] = g2["adj_close"].transform(lambda s: s.rolling(5, min_periods=3).mean())
    bars["ma10"] = g2["adj_close"].transform(lambda s: s.rolling(10, min_periods=5).mean())
    bars["amp5_avg"] = g2["amp_1d"].transform(lambda s: s.rolling(5, min_periods=3).mean())
    h5 = g2["adj_close"].transform(lambda s: s.rolling(5, min_periods=3).max())
    l5 = g2["adj_close"].transform(lambda s: s.rolling(5, min_periods=3).min())
    bars["box5_range"] = np.where(l5 > 0, (h5 - l5) / l5 * 100.0, np.nan).astype(np.float32)
    bars["dist_ma5_pct"] = ((bars["adj_close"] / bars["ma5"] - 1.0) * 100.0).astype(np.float32)
    bars["above_ma5"] = (bars["adj_close"] > bars["ma5"]).astype(np.int8)
    bars["above_ma10"] = (bars["adj_close"] > bars["ma10"]).astype(np.int8)
    bars["zt_days_30d"] = g2["is_zt"].transform(lambda s: s.rolling(30, min_periods=1).sum()).astype(np.int16)
    bars["zt_days_60d"] = g2["is_zt"].transform(lambda s: s.rolling(60, min_periods=1).sum()).astype(np.int16)
    bars["max_streak_30d"] = g2["streak"].transform(lambda s: s.rolling(30, min_periods=1).max()).astype(np.int16)
    min_prev2 = g2["adj_close"].transform(lambda s: s.rolling(2, min_periods=1).min().shift(1))
    bars["dist_3d30"] = ((1.30 * min_prev2 / bars["adj_close"] - 1.0) * 100.0).astype(np.float32)

    # Index lookup per (c6, dt) for ultra-fast T-1 & T..T+4 extraction
    bar_idx = {}
    for ck, grp in bars.groupby("c6", sort=False):
        bar_idx[ck] = (grp["dt"].values, grp.index.values)

    n_m = len(master)
    # Allocate ABN & RD25 arrays
    abn_cols = {
        "abn_d1_is_yang": np.full(n_m, np.nan, dtype=np.float32),
        "abn_d1_is_fake_yin": np.full(n_m, np.nan, dtype=np.float32),
        "abn_d1_is_true_yin": np.full(n_m, np.nan, dtype=np.float32),
        "abn_d1_upper_shadow": np.full(n_m, np.nan, dtype=np.float32),
        "abn_d1_lower_shadow": np.full(n_m, np.nan, dtype=np.float32),
        "abn_amp5_avg_t1": np.full(n_m, np.nan, dtype=np.float32),
        "abn_box5_range_t1": np.full(n_m, np.nan, dtype=np.float32),
        "abn_above_ma5_t1": np.full(n_m, np.nan, dtype=np.float32),
        "abn_above_ma10_t1": np.full(n_m, np.nan, dtype=np.float32),
        "abn_dist_ma5_pct_t1": np.full(n_m, np.nan, dtype=np.float32),
        "abn_zt_days_30d_t1": np.full(n_m, np.nan, dtype=np.float32),
        "abn_max_streak_30d_t1": np.full(n_m, np.nan, dtype=np.float32),
        "rd25_prev_yang_streak": np.full(n_m, np.nan, dtype=np.float32),
        "rd25_dist_3d30_t1": np.full(n_m, np.nan, dtype=np.float32),
        "rd25_d1_body_pct": np.full(n_m, np.nan, dtype=np.float32),
        "rd25_zt_days_60d_t1": np.full(n_m, np.nan, dtype=np.float32),
    }

    bar_slots = ["b0", "tp1", "tp2", "tp3", "tp4"]
    bar_num_fields = ["open", "high", "low", "close", "adj_factor", "clv", "open_pct", "ret_1d", "is_zt", "is_dt", "is_yizi_zt", "is_yizi_dt", "streak"]
    bar_out = {}
    for sl in bar_slots:
        bar_out[f"bar_{sl}_dt"] = np.full(n_m, "", dtype=object)
        for fld in bar_num_fields:
            bar_out[f"bar_{sl}_{fld}"] = np.full(n_m, np.nan, dtype=np.float32)
        if sl != "b0":
            bar_out[f"bar_{sl}_ret_vs_buy_open_pct"] = np.full(n_m, np.nan, dtype=np.float32)
            bar_out[f"bar_{sl}_ret_vs_buy_px_pct"] = np.full(n_m, np.nan, dtype=np.float32)

    b_arr = {
        "dt": bars["dt"].values,
        "open": bars["open"].values,
        "high": bars["high"].values,
        "low": bars["low"].values,
        "close": bars["close"].values,
        "adj_factor": bars["adj_factor"].values,
        "clv": bars["clv"].values,
        "open_pct": bars["open_pct_b"].values,
        "ret_1d": bars["ret_1d"].values,
        "is_zt": bars["is_zt"].values,
        "is_dt": bars["is_dt"].values,
        "is_yizi_zt": bars["is_yizi_zt"].values,
        "is_yizi_dt": bars["is_yizi_dt"].values,
        "streak": bars["streak"].values,
        "k_is_yang": bars["k_is_yang"].values,
        "k_is_fake_yin": bars["k_is_fake_yin"].values,
        "k_is_true_yin": bars["k_is_true_yin"].values,
        "k_upper_shad": bars["k_upper_shad"].values,
        "k_lower_shad": bars["k_lower_shad"].values,
        "amp5_avg": bars["amp5_avg"].values,
        "box5_range": bars["box5_range"].values,
        "above_ma5": bars["above_ma5"].values,
        "above_ma10": bars["above_ma10"].values,
        "dist_ma5_pct": bars["dist_ma5_pct"].values,
        "zt_days_30d": bars["zt_days_30d"].values,
        "zt_days_60d": bars["zt_days_60d"].values,
        "max_streak_30d": bars["max_streak_30d"].values,
        "yang_streak": bars["yang_streak"].values,
        "dist_3d30": bars["dist_3d30"].values,
        "body_pct": bars["body_pct"].values,
    }

    m_strat = master["strategy"].values
    m_buy_px = master["buy_price"].values
    for i, (ck, bd) in enumerate(zip(master["code"].values, master["buy_date"].values)):
        tup = bar_idx.get(ck)
        if tup is None:
            continue
        dts_s, idxs_s = tup
        p = int(np.searchsorted(dts_s, bd))
        # T-1 bar for ABN/RD25 (strictly < bd)
        p_t1 = p - 1 if p > 0 else -1
        if p_t1 >= 0:
            ri = idxs_s[p_t1]
            abn_cols["abn_d1_is_yang"][i] = b_arr["k_is_yang"][ri]
            abn_cols["abn_d1_is_fake_yin"][i] = b_arr["k_is_fake_yin"][ri]
            abn_cols["abn_d1_is_true_yin"][i] = b_arr["k_is_true_yin"][ri]
            abn_cols["abn_d1_upper_shadow"][i] = b_arr["k_upper_shad"][ri]
            abn_cols["abn_d1_lower_shadow"][i] = b_arr["k_lower_shad"][ri]
            abn_cols["abn_amp5_avg_t1"][i] = b_arr["amp5_avg"][ri]
            abn_cols["abn_box5_range_t1"][i] = b_arr["box5_range"][ri]
            abn_cols["abn_above_ma5_t1"][i] = b_arr["above_ma5"][ri]
            abn_cols["abn_above_ma10_t1"][i] = b_arr["above_ma10"][ri]
            abn_cols["abn_dist_ma5_pct_t1"][i] = b_arr["dist_ma5_pct"][ri]
            abn_cols["abn_zt_days_30d_t1"][i] = b_arr["zt_days_30d"][ri]
            abn_cols["abn_max_streak_30d_t1"][i] = b_arr["max_streak_30d"][ri]
            abn_cols["rd25_prev_yang_streak"][i] = b_arr["yang_streak"][ri]
            abn_cols["rd25_dist_3d30_t1"][i] = b_arr["dist_3d30"][ri]
            abn_cols["rd25_d1_body_pct"][i] = b_arr["body_pct"][ri]
            abn_cols["rd25_zt_days_60d_t1"][i] = b_arr["zt_days_60d"][ri]

        # Exit bars: b0 if dts_s[p] == bd
        if p < len(dts_s) and dts_s[p] == bd:
            b0_adj_fac = b_arr["adj_factor"][idxs_s[p]]
            b0_adj_open = b_arr["open"][idxs_s[p]] * b0_adj_fac
            # 20cm buy_price is already forward-adjusted buy_px; 10cm buy_price is raw
            bp_v = float(m_buy_px[i]) if np.isfinite(m_buy_px[i]) else np.nan
            b0_adj_buy_px = bp_v if (m_strat[i] == "20cm") else (bp_v * b0_adj_fac if np.isfinite(bp_v) else np.nan)
            for off, sl in enumerate(bar_slots):
                pk = p + off
                if pk < len(dts_s):
                    rk = idxs_s[pk]
                    bar_out[f"bar_{sl}_dt"][i] = b_arr["dt"][rk]
                    for fld in bar_num_fields:
                        bar_out[f"bar_{sl}_{fld}"][i] = b_arr[fld][rk]
                    adj_c_k = b_arr["close"][rk] * b_arr["adj_factor"][rk]
                    if sl != "b0" and b0_adj_open > 0:
                        bar_out[f"bar_{sl}_ret_vs_buy_open_pct"][i] = (adj_c_k / b0_adj_open - 1.0) * 100.0
                    if sl != "b0" and np.isfinite(b0_adj_buy_px) and b0_adj_buy_px > 0:
                        bar_out[f"bar_{sl}_ret_vs_buy_px_pct"][i] = (adj_c_k / b0_adj_buy_px - 1.0) * 100.0

    for k, v in abn_cols.items():
        master[k] = v
    for k, v in bar_out.items():
        master[k] = v

    # Fill missing open_pct (e.g., pry) from bar_b0_open_pct / 100.0
    miss_op = master["open_pct"].isna() & master["bar_b0_open_pct"].notna()
    master.loc[miss_op, "open_pct"] = (master.loc[miss_op, "bar_b0_open_pct"] / 100.0).astype(np.float32)

    master["rd25_open_vs_d1_body"] = np.where(
        master["rd25_d1_body_pct"].abs() >= 1.0,
        (master["open_pct"] * 100.0) / master["rd25_d1_body_pct"].abs(),
        (master["open_pct"] * 100.0),
    ).astype(np.float32)

    del bars
    gc.collect()

    # Community 3d pre-open (Xueqiu & Guba < buy_date 09:25) & CNINFO Catalysts / IR exact 8d/20d pre-open
    cal_idx = {d: i for i, d in enumerate(full_cal)}
    code_list_sql = ",".join(f"'{c}'" for c in sorted(pool_codes))

    def _count_preopen_window(df_ev, c6_col, ts_col, win_days):
        pub_dt = df_ev[ts_col].astype(str).str[:10].values
        pub_hm = df_ev[ts_col].astype(str).str[11:19].values
        ok = pub_dt <= end_cutoff
        pos = np.searchsorted(full_cal, pub_dt[ok], side="left")
        on_same = (pos < len(full_cal)) & (full_cal[np.minimum(pos, len(full_cal) - 1)] == pub_dt[ok])
        eff = np.where(on_same & (pub_hm[ok] >= "09:25:00"), pos + 1, pos)
        sub_c = df_ev[c6_col].values[ok]
        valid_e = eff < len(full_cal)
        tmp = pd.DataFrame({"c6": sub_c[valid_e], "eff": eff[valid_e]}).sort_values(["c6", "eff"])
        ev_map = {ck: g["eff"].values for ck, g in tmp.groupby("c6", sort=False)}
        out = np.zeros(n_m, dtype=np.float32)
        bd_idx = master["buy_date"].map(cal_idx).fillna(-1).values.astype(np.int32)
        for i, (ck, bi) in enumerate(zip(master["code"].values, bd_idx)):
            if bi < 0 or ck not in ev_map:
                continue
            a = ev_map[ck]
            out[i] = float(np.searchsorted(a, bi, side="right") - np.searchsorted(a, bi - (win_days - 1), side="left"))
        return out

    con_cm = sqlite3.connect(f"file:{os.path.join(ROOT, 'sim-portfolio/data/astock_community_5y_pit.db')}?mode=ro", uri=True)
    cm_df = pd.read_sql_query(
        f"SELECT symbol, source, pub_datetime_cst FROM community_posts WHERE symbol IN ({code_list_sql}) AND pub_datetime_cst >= '2021-01-01' AND substr(pub_datetime_cst,1,10) <= ?",
        con_cm,
        params=(end_cutoff,),
    )
    con_cm.close()
    cm_df["c6"] = cm_df["symbol"].astype(str).str.zfill(6)
    master["rd25_xq_3d_pre"] = _count_preopen_window(cm_df[cm_df["source"] == "xueqiu"], "c6", "pub_datetime_cst", 3)
    master["rd25_gb_3d_pre"] = _count_preopen_window(cm_df[cm_df["source"].isin(["guba", "eastmoney_guba"])], "c6", "pub_datetime_cst", 3)
    del cm_df

    con_cn = sqlite3.connect(f"file:{os.path.join(ROOT, 'sim-portfolio/data/cninfo_notices_5y_pit.db')}?mode=ro", uri=True)
    cn_df = pd.read_sql_query(
        f"SELECT sec_code, title, pub_datetime_cst FROM notices WHERE sec_code IN ({code_list_sql}) AND substr(pub_datetime_cst,1,10) <= ? AND (title LIKE '%业绩%' OR title LIKE '%预增%' OR title LIKE '%中标%' OR title LIKE '%合同%' OR title LIKE '%订单%' OR title LIKE '%重组%' OR title LIKE '%收购%' OR title LIKE '%并购%')",
        con_cn,
        params=(end_cutoff,),
    )
    con_cn.close()
    cn_df["c6"] = cn_df["sec_code"].astype(str).str.zfill(6)
    t_str = cn_df["title"].astype(str)
    master["rd25_cat_earn_any_3d"] = (_count_preopen_window(cn_df[t_str.str.contains("业绩|预增", regex=True)], "c6", "pub_datetime_cst", 3) > 0).astype(np.float32)
    master["rd25_cat_cont_3d"] = (_count_preopen_window(cn_df[t_str.str.contains("中标|合同|订单", regex=True)], "c6", "pub_datetime_cst", 3) > 0).astype(np.float32)
    master["rd25_cat_ma_5d"] = (_count_preopen_window(cn_df[t_str.str.contains("重组|收购|并购", regex=True)], "c6", "pub_datetime_cst", 5) > 0).astype(np.float32)
    del cn_df

    con_ir = sqlite3.connect(f"file:{os.path.join(ROOT, 'sim-portfolio/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db')}?mode=ro", uri=True)
    ir_df = pd.read_sql_query(
        f"SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE sec_code IN ({code_list_sql}) AND substr(pub_datetime_cst,1,10) <= ?",
        con_ir,
        params=(end_cutoff,),
    )
    con_ir.close()
    ir_df["c6"] = ir_df["sec_code"].astype(str).str.zfill(6)
    master["_tmp_ir_8d_pre"] = _count_preopen_window(ir_df, "c6", "pub_datetime_cst", 8)
    master["_tmp_ir_20d_pre"] = _count_preopen_window(ir_df, "c6", "pub_datetime_cst", 20)
    del ir_df

    # 5-day LHB inst_net, lhasa ratio, & famous youzi net (strictly <= prev_dt from Step 2 LHB cache)
    lhb_p = os.path.join(CACHE_DIR, f"lhb_stockday_5y_pit_{end_cutoff.replace('-', '')}.parquet")
    lhb = pd.read_parquet(lhb_p)
    lhb["d_idx"] = lhb["dt"].map(cal_idx).fillna(-1).astype(np.int32)
    lhb = lhb[(lhb["c6"].isin(pool_codes)) & (lhb["d_idx"] >= 0)].sort_values(["c6", "d_idx"]).reset_index(drop=True)
    # 1d LHB on prev_dt
    master["prev_dt"] = master["buy_date"].map(prev_td_map)
    lhb_1d = lhb.rename(columns={"dt": "prev_dt", "lhb_net_yi": "yz_lhb_net_yi_t1", "lhb_buy_yi": "yz_lhb_buy_yi_t1"})
    master = master.merge(lhb_1d[["prev_dt", "c6", "yz_lhb_net_yi_t1", "yz_lhb_buy_yi_t1"]], left_on=["prev_dt", "code"], right_on=["prev_dt", "c6"], how="left").drop(columns=["c6"])
    master["yz_lhb_net_yi_t1"] = master["yz_lhb_net_yi_t1"].fillna(0.0).astype(np.float32)
    master["yz_lhb_buy_yi_t1"] = master["yz_lhb_buy_yi_t1"].fillna(0.0).astype(np.float32)

    lhb_map = {}
    for ck, grp in lhb.groupby("c6", sort=False):
        lhb_map[ck] = (
            grp["d_idx"].values,
            grp["lhb_inst_net_yi"].values,
            grp["lhb_lhasa_share"].values,
            np.where(grp["lhb_has_good_yz"].values > 0, grp["lhb_net_yi"].values, 0.0),
        )
    pdt_idx = master["prev_dt"].map(cal_idx).fillna(-1).values.astype(np.int32)
    inst5 = np.zeros(n_m, dtype=np.float32)
    lasa5 = np.zeros(n_m, dtype=np.float32)
    famyz5 = np.zeros(n_m, dtype=np.float32)
    for i, (ck, pi) in enumerate(zip(master["code"].values, pdt_idx)):
        if pi < 0 or ck not in lhb_map:
            continue
        da, ina, lsa, fma = lhb_map[ck]
        r = int(np.searchsorted(da, pi, side="right"))
        l = int(np.searchsorted(da, pi - 4, side="left"))
        if r > l:
            inst5[i] = float(ina[l:r].sum())
            lasa5[i] = float(lsa[l:r].mean())
            famyz5[i] = float(fma[l:r].sum())
    master["abn_lhb_inst_net_5d_t1"] = inst5
    master["abn_lhb_lasa_ratio_5d_t1"] = lasa5
    master["yz_famous_net_5d_t1"] = famyz5

    # THS PIT Youzi icons T-1 (date == prev_dt <= end_cutoff)
    ths = pd.read_parquet(
        os.path.join(RD016_DIR, "ths_pit_youzi_5y.parquet"),
        columns=["date", "stock_code", "all_inflow", "cap_inflow", "cap_count", "n_capital_icons"],
    )
    ths["prev_dt"] = pd.to_datetime(ths["date"]).dt.strftime("%Y-%m-%d")
    ths["code"] = ths["stock_code"].astype(str).str.zfill(6)
    ths = ths[(ths["prev_dt"] <= end_cutoff) & (ths["code"].isin(pool_codes))].drop_duplicates(["prev_dt", "code"], keep="first")
    ths["yz_thm_all_inflow_t1"] = (ths["all_inflow"].fillna(0) / 1e8).astype(np.float32)
    ths["yz_thm_cap_inflow_t1"] = (ths["cap_inflow"].fillna(0) / 1e8).astype(np.float32)
    ths["yz_thm_cap_cnt_t1"] = ths["cap_count"].fillna(0).astype(np.float32)
    ths["yz_thm_n_icons_t1"] = ths["n_capital_icons"].fillna(0).astype(np.float32)
    master = master.merge(
        ths[["prev_dt", "code", "yz_thm_all_inflow_t1", "yz_thm_cap_inflow_t1", "yz_thm_cap_cnt_t1", "yz_thm_n_icons_t1"]],
        on=["prev_dt", "code"],
        how="left",
    )
    for c in ["yz_thm_all_inflow_t1", "yz_thm_cap_inflow_t1", "yz_thm_cap_cnt_t1", "yz_thm_n_icons_t1"]:
        master[c] = master[c].fillna(0.0).astype(np.float32)

    print(f"[Step3] ABN+RD25+LHB+ExitBars done in {time.time()-t0:.1f}s")
    return master


def build_master(end_cutoff: str = "2026-11-25"):
    t0 = time.time()
    print(f"\n[Step3] === Building 6-strategy Master Matrix up to {end_cutoff} ===")
    sh300, sh_idx, sz_idx, dts, prev_td = load_csi300()
    full_cal = np.array(dts)

    # 1. Base 6 strategies + native atomic factors + RD030 Old-Hot + RD032 40 Evo
    master, parity_checks = _load_base_6strat_and_atomic(end_cutoff, sh300, sh_idx, sz_idx, prev_td)

    # 2. Attach RD034 L2 & L3 cycle factors (strictly excluding L1_* since L1 comes from Step 1 market_daily)
    rd34 = pd.read_parquet(os.path.join(RD034_DIR, "pools_6strat_with_3layer_cycles.parquet"))
    rd34["buy_date"] = rd34["buy_date"].astype(str).str[:10]
    rd34["code"] = rd34["code"].astype(str).str.zfill(6)
    rd34 = rd34[rd34["buy_date"] <= end_cutoff].copy()
    l23_cols = [c for c in rd34.columns if c.startswith(("L2_", "L3_"))]
    n_base = len(master)
    master = master.merge(rd34[["strategy", "buy_date", "code"] + l23_cols], on=["strategy", "buy_date", "code"], how="left")
    assert len(master) == n_base, f"RD034 merge fanout: {len(master)} vs {n_base}"
    for c in l23_cols:
        if c not in ("L2_ind_name_t1", "L2_kpl_plate_t1"):
            master[c] = pd.to_numeric(master[c], errors="coerce").astype(np.float32)

    # 3. Attach Step 2 Stock-Day Core T-1/pre features (prefixed sd_*)
    sd_df = pd.read_parquet(os.path.join(OUT_DIR, "stock_day_core_features_pit.parquet"))
    sd_df["c6"] = sd_df["c6"].astype(str)
    sd_df["dt"] = sd_df["dt"].astype(str)
    sd_df = sd_df[sd_df["dt"] <= end_cutoff].copy()
    # Cross-sectional T-1 real free mcap percentile for rd25_rfm_pct_all20_t1
    sd_20 = sd_df[sd_df["is_20cm"] == 1][["dt", "c6", "free_mcap_yi_t1"]].copy()
    sd_20["rd25_rfm_pct_all20_t1"] = sd_20.groupby("dt")["free_mcap_yi_t1"].rank(pct=True).astype(np.float32)
    # Also cross-sectional percentile across ALL stocks
    sd_df["rd25_rfm_pct_all_t1"] = sd_df.groupby("dt")["free_mcap_yi_t1"].rank(pct=True).astype(np.float32)

    sd_t1_cols = [
        "prev_close_raw",
        "mcap_yi_t1",
        "lock_top10_pct_pre",
        "free_mcap_yi_t1",
        "real_turn_pct_t1",
        "amount_yi_t1",
        "ret_1d_t1",
        "ret_5d_t1",
        "ret_20d_t1",
        "bias10_t1",
        "bias20_t1",
        "pos_20d_t1",
        "pos_60d_t1",
        "pos_250d_t1",
        "dd_20d_t1",
        "amp_20d_t1",
        "amp_comp_20v60_t1",
        "vol_ratio5_t1",
        "turn_5_20_t1",
        "overhang_pct_t1",
        "hr10d_space_t1",
        "hr30d_space_t1",
        "down_streak_t1",
        "prev_streak",
        "prev_clv",
        "d1_open_pct",
        "prev_is_broken_zt",
        "prev_is_yizi_zt",
        "is_20cm",
        "is_st_pit",
        "d1_seal_ratio_t1",
        "d1_open_board_cnt_t1",
        "d1_first_seal_hhmm_t1",
        "kpl_in_t1",
        "kpl_rank_t1",
        "kpl_zt1_t1",
        "kpl_zt3_t1",
        "kpl_streak_t1",
        "kpl_days_30d_t1",
        "csrc_ind_id",
        "csrc_ind_ex5_t1",
        "csrc_ind_ex20_t1",
        "csrc_ind_rank20_t1",
        "csrc_ind_zt_share5_t1",
        "csrc_ind_amt_pct250_t1",
        "lhb_on_t1",
        "lhb_bayes_t2_t1",
        "lhb_inst_net_yi_t1",
        "lhb_lhasa_share_t1",
        "lhb_has_good_yz_t1",
        "lhb_has_surf_yz_t1",
        "lhb_has_quant_t1",
        "lhb_cnt_5d_t1",
        "tox_reg_30d_pre",
        "abn_notice_30d_pre",
        "ir_cnt_30d_pre",
        "comm_ring_tier",
        "comm_driver_ret20_t1",
        "comm_driver_pct5y_t1",
        "rd25_rfm_pct_all_t1",
    ]
    sd_sub = sd_df[["c6", "dt"] + sd_t1_cols].rename(
        columns={c: (f"sd_{c}" if not c.startswith("rd25_") else c) for c in sd_t1_cols}
    )
    master = master.merge(sd_sub, left_on=["code", "buy_date"], right_on=["c6", "dt"], how="left").drop(columns=["c6", "dt"])
    master = master.merge(sd_20[["dt", "c6", "rd25_rfm_pct_all20_t1"]], left_on=["buy_date", "code"], right_on=["dt", "c6"], how="left").drop(columns=["c6", "dt"])
    del sd_df, sd_sub, sd_20
    gc.collect()

    # 4. Attach ABN, RD25, LHB 5d, THS, and Exit Bars (b0, tp1..tp4)
    master = _attach_bars_abn_rd25_and_exit_bars(master, end_cutoff, full_cal, prev_td)

    # 5. Attach Step 1 Market Daily New Factors (119 cols on buy_date == trade_date)
    # For truncation test at 2024-12-31, market_daily is ALREADY proven max_abs_diff == 0.0 at 2024-12-31!
    mkt = pd.read_parquet(os.path.join(OUT_DIR, "market_daily_all_new_factors_pit.parquet"))
    mkt = mkt[mkt["trade_date"] <= end_cutoff].copy()
    mkt_cols = [c for c in mkt.columns if c != "trade_date"]
    master = master.merge(mkt, left_on="buy_date", right_on="trade_date", how="left").drop(columns=["trade_date"])

    # 6. Unified Cross-Strategy Atomic Transplant Matrix (xtr_*, 36 binary flags across ALL 4,183 rows)
    open_rank = master.groupby(["strategy", "buy_date"])["open_pct"].rank(ascending=False, method="min")
    b_month = pd.to_datetime(master["buy_date"]).dt.month
    xtr = {
        "xtr_px_le20": (master["sd_prev_close_raw"] <= 20.0),
        "xtr_open_sweet_4_8": ((master["open_pct"] >= 0.04) & (master["open_pct"] <= 0.082)),
        "xtr_open_green": (master["open_pct"] < 0.0),
        "xtr_open_deep_neg3": (master["open_pct"] <= -0.03),
        "xtr_open_top3": (open_rank <= 3),
        "xtr_dd20_deep_15": (master["sd_dd_20d_t1"] <= -15.0),
        "xtr_pos20_low_35": (master["sd_pos_20d_t1"] <= 0.35),
        "xtr_bias10_le_m15": (master["sd_bias10_t1"] <= -15.0),
        "xtr_bias20_le_m22": (master["sd_bias20_t1"] <= -22.0),
        "xtr_down4": (master["sd_down_streak_t1"] >= 4),
        "xtr_vr15": (master["sd_vol_ratio5_t1"] >= 1.5),
        "xtr_fmcap_le20": (master["sd_free_mcap_yi_t1"] <= 20.0),
        "xtr_fmcap_le25": (master["sd_free_mcap_yi_t1"] <= 25.0),
        "xtr_lock50": (master["sd_lock_top10_pct_pre"] >= 50.0),
        "xtr_zero_lhasa_t1": ((master["sd_lhb_on_t1"] == 1) & (master["sd_lhb_lhasa_share_t1"] == 0.0)),
        "xtr_lhasa_gt25_t1": (master["sd_lhb_lhasa_share_t1"] > 0.25),
        "xtr_inst_net_pos_t1": (master["sd_lhb_inst_net_yi_t1"] > 0.0),
        "xtr_surf_yz_t1": (master["sd_lhb_has_surf_yz_t1"] == 1),
        "xtr_quant_in_t1": (master["sd_lhb_has_quant_t1"] == 1),
        "xtr_has_ir_8d": (master["_tmp_ir_8d_pre"] > 0),
        "xtr_has_ir_20d": (master["_tmp_ir_20d_pre"] > 0),
        "xtr_ex_reg_30d": ((master["sd_tox_reg_30d_pre"] + master["sd_abn_notice_30d_pre"]) > 0),
        "xtr_mkt_zt_warm_35_85": ((master["L1_zt_cnt_t1"] >= 35) & (master["L1_zt_cnt_t1"] <= 85)),
        "xtr_mkt_zt_gt55": (master["L1_zt_cnt_t1"] > 55),
        "xtr_mkt_climax_95": (master["L1_zt_cnt_t1"] >= 95),
        "xtr_mkt_seal_80": ((1.0 - master["L1_zb_rate_t1"]) >= 0.80),
        "xtr_mkt_0925_zt_12": (master["mkt_0925_zt_cnt"] >= 12),
        "xtr_monday": (master["L1_weekday"] == 0),
        "xtr_jan_may": b_month.isin([1, 5]),
        "xtr_seal_am": ((master["sd_d1_first_seal_hhmm_t1"] > 0) & (master["sd_d1_first_seal_hhmm_t1"] < 1130)),
        "xtr_seal_ratio_ge10": (master["sd_d1_seal_ratio_t1"] >= 0.10),
        "xtr_d1_yizi": (master["sd_prev_is_yizi_zt"] == 1),
        "xtr_d1_is_yang": (master["abn_d1_is_yang"] == 1),
        "xtr_kpl_zt_ge4": (master["sd_kpl_zt1_t1"] >= 4),
        "xtr_zt60d_ge2": (master["rd25_zt_days_60d_t1"] >= 2),
        "xtr_kpl_max_streak_ge5": (master["oh_max_streak_3y"] >= 5),
        "xtr_dist3d30_ge10": (master["rd25_dist_3d30_t1"] >= 10.0),
    }
    for k, cond in xtr.items():
        master[k] = cond.fillna(False).astype(np.float32)

    master = master.drop(columns=["_tmp_ir_8d_pre", "_tmp_ir_20d_pre", "prev_dt"])
    master = master.sort_values(["strategy", "buy_date", "code"]).reset_index(drop=True)

    # Ensure compact float32 on numeric non-identifier cols
    id_str_cols = {
        "strategy", "buy_date", "entry_date", "exit_date", "sig_date", "code", "name",
        "exit_reason", "plate", "pool_layer", "era_tag", "is_oos_split",
        "oh_cool_bin_zt", "oh_cool_bin_2b", "L2_ind_name_t1", "L2_kpl_plate_t1",
        "bar_b0_dt", "bar_tp1_dt", "bar_tp2_dt", "bar_tp3_dt", "bar_tp4_dt",
    }
    for c in master.columns:
        if c not in id_str_cols and c not in (
            "is_pass_official", "orig_pass", "sim_ok", "is_s_tier", "is_edge_cand", "is_near_line",
            "is_obs_a76", "is_standalone_slot1", "is_v20_slot1", "year",
        ):
            if master[c].dtype == np.float64 or str(master[c].dtype).startswith("int"):
                master[c] = pd.to_numeric(master[c], errors="coerce").astype(np.float32)
        elif c in id_str_cols:
            master[c] = master[c].fillna("").astype(str)

    print(f"[Step3] Built Master ({master.shape}) in {time.time()-t0:.1f}s")
    return master, parity_checks


def build_catalog_and_audit(master: pd.DataFrame, parity_checks: dict, trunc_audit: dict):
    """Build complete wave1a_factor_catalog_and_pit_audit.json combining Steps 1, 2, and 3."""
    with open(os.path.join(OUT_DIR, "_audit_step1_market.json")) as f:
        a1 = json.load(f)
    with open(os.path.join(OUT_DIR, "_audit_step2_stockday.json")) as f:
        a2 = json.load(f)

    # Atomic descriptions lookup from rd032_decay_audit.FACTOR_SPECS
    fs_desc = {}
    pref_map = {"1to2": "s12_", "2to3": "s23_", "3to4": "s34_", "high": "shigh_", "pry": "spry_", "20cm": "s20cm_"}
    for st, items in rd32_audit.FACTOR_SPECS.items():
        pr = pref_map[st]
        for code_id, col_name, sign, desc_cn, pts in items:
            fs_desc[f"{pr}{col_name}"] = {"source": f"V20_ATOMIC_{st}", "definition": f"[{st}] {desc_cn} (权重{pts}, 方向{sign})", "lag": "T-1 / pre-09:25 (V20 scorecard)", "role": "native_atomic_factor"}

    evo_desc = rd32_evo.EVO_LABELS

    def _classify_col(c: str):
        if c in fs_desc:
            return fs_desc[c]
        if c.startswith(("s12_", "s23_", "s34_", "shigh_", "spry_", "s20cm_")):
            st_tag = c.split("_")[0]
            return {"source": f"V20_ATOMIC_{st_tag}", "definition": f"V20 strategy raw/auxiliary atomic field {c}", "lag": "T-1 / pre-09:25", "role": "native_atomic_factor"}
        if c.startswith("bar_"):
            return {"source": "EXECUTION_BAR_SIM", "definition": f"Forward execution bar field {c} (exit-tree simulation only, NOT entry feature)", "lag": "Post-entry bar T..T+4", "role": "exit_bar_simulation"}
        if c.startswith("xtr_"):
            return {"source": "CROSS_STRATEGY_TRANSPLANT", "definition": f"Unified cross-strategy transplant atomic rule {c} evaluated across all 4,183 rows", "lag": "T-1 / pre-09:25", "role": "cross_transplant_factor"}
        if c.startswith("oh_"):
            return {"source": "RD030_OLD_HOT_6DIM", "definition": f"RD030 6-dim old-hot stock history {c[3:]}", "lag": "T-1 close PIT", "role": "entry_feature"}
        if c.startswith("L1_"):
            return {"source": "RD034_3LAYER_L1_MARKET", "definition": f"RD034 Layer-1 market/style/calendar {c}", "lag": "T-1 close / deterministic calendar", "role": "entry_feature"}
        if c.startswith("L2_"):
            return {"source": "RD034_3LAYER_L2_IND_KPL", "definition": f"RD034 Layer-2 industry/KPL lifecycle {c}", "lag": "T-1 close PIT", "role": "entry_feature"}
        if c.startswith("L3_"):
            return {"source": "RD034_3LAYER_L3_STOCK", "definition": f"RD034 Layer-3 stock cycle {c}", "lag": "T-1 close PIT", "role": "entry_feature"}
        if c.startswith("evo_"):
            return {"source": "RD032_EVO_40", "definition": f"RD032 evolution candidate: {evo_desc.get(c, c)}", "lag": "T-1 / pre-09:25", "role": "entry_feature"}
        if c.startswith("abn_"):
            return {"source": "ABN_30D200_48FACTORS", "definition": f"Generalized 30d200 factor {c[4:]}", "lag": "T-1 close PIT", "role": "entry_feature"}
        if c.startswith("yz_"):
            return {"source": "RD016_FAMOUS_YOUZI_5Y", "definition": f"Rebuilt 5Y LHB/THS youzi signal {c[3:]}", "lag": "T-1 close PIT (settled <= T-1)", "role": "entry_feature"}
        if c.startswith("sd_"):
            return {"source": "RD035_STOCK_DAY_CORE", "definition": f"5Y stock-day core PIT feature {c[3:]}", "lag": "T-1 / pre-09:25", "role": "entry_feature"}
        if c.startswith("rd25_"):
            return {"source": "RD025_CROSS_FACTOR_FUSION", "definition": f"RD025 TrackB1/B2/TrackA stock feature {c[5:]}", "lag": "T-1 / < 09:25 CST", "role": "entry_feature"}
        if c.startswith(("mkt_", "mkt20_")):
            lag_s = "T 09:25 auction" if "0925" in c else "T-1 close PIT"
            return {"source": "RD025_MARKET_MICRO_0925", "definition": f"Market microstructure / 09:25 auction {c}", "lag": lag_s, "role": "entry_feature"}
        if c.startswith("us_"):
            return {"source": "US_TO_ASHARE_OVERNIGHT", "definition": f"US overnight settled benchmark factor {c}", "lag": "US close < T 09:30 CST", "role": "entry_feature"}
        if c.startswith("comm_"):
            return {"source": "COMMODITIES_LEADLAG_3RING", "definition": f"Commodity/BDI/extreme-reversal signal {c}", "lag": "Futures/BDI < T", "role": "entry_feature"}
        if c.startswith("nt_"):
            return {"source": "NT_V3_MANTRA_RD027", "definition": f"National Team V3 / Mantra daily signal {c}", "lag": "T-1 close PIT", "role": "entry_feature"}
        if c.startswith(("macro_", "wp_", "pol_")):
            return {"source": "CHINA_MACRO_POLICY_RD027", "definition": f"Macro pain / waterpool / policy event {c}", "lag": "T-1 / M+1_17d / tradable_date<=T", "role": "entry_feature"}
        if c.startswith("th_"):
            return {"source": "THEORY_15Y_CAUSAL", "definition": f"15Y causal style/tech/macro theory pulse {c}", "lag": "T-1 close / deterministic month", "role": "entry_feature"}
        return {"source": "BASELINE_ID_OR_TARGET", "definition": f"Pool baseline key/score/return/metadata {c}", "lag": "Baseline / post-exit target", "role": "identifier_or_target"}

    # Missingness summary on master
    master_miss = {c: round(float(master[c].isna().mean()), 6) for c in master.columns}
    catalog = {}
    role_counts = {}
    source_counts = {}
    for c in master.columns:
        meta = _classify_col(c)
        meta["dtype"] = str(master[c].dtype)
        meta["missing_rate_6strat_master"] = master_miss[c]
        catalog[c] = meta
        role_counts[meta["role"]] = role_counts.get(meta["role"], 0) + 1
        source_counts[meta["source"]] = source_counts.get(meta["source"], 0) + 1

    # Also catalog stock_day_core_features_pit columns
    sd_catalog = {}
    for c, mr in a2["missing_rates"].items():
        sd_catalog[c] = {"missing_rate_5y_stockday": mr, "lag": "T bar" if c in ("open","high","low","close","adj_factor","amount_yi","turn_pct","ret_1d","open_pct","clv","is_zt","hit_zt","is_broken_zt","is_yizi_zt","is_dt","is_yizi_dt","streak") else "T-1 / pre-09:25 PIT"}

    audit_all = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "deliverables": {
            "market_daily": {"path": a1["file"], "rows": a1["rows"], "cols": a1["n_features"] + 1, "date_range": [a1["date_min"], a1["date_max"]], "size_mb": a1["size_mb"]},
            "stock_day_core": {"path": a2["file"], "rows": a2["rows"], "cols": a2["cols"], "date_range": [a2["date_min"], a2["date_max"]], "size_mb": a2["size_mb"], "read_ram_gb": a2["read_ram_gb"]},
            "pools_6strat_master": {"path": os.path.join(OUT_DIR, "pools_6strat_master_newfactors_pit.parquet"), "rows": int(len(master)), "cols": int(len(master.columns)), "strategy_counts": {k: int(v) for k, v in master["strategy"].value_counts().to_dict().items()}, "size_mb": round(os.path.getsize(os.path.join(OUT_DIR, "pools_6strat_master_newfactors_pit.parquet")) / 1024 / 1024, 3)},
        },
        "pit_truncation_2024_12_31_proof": {
            "market_daily_max_abs_diff": a1["truncation_2024_12_31_max_abs_diff"],
            "stock_day_core_max_abs_diff": a2["truncation_2024_12_31_max_abs_diff"],
            "pools_6strat_entry_factors_max_abs_diff": trunc_audit["entry_max_abs_diff"],
            "pools_6strat_exit_bars_settled_le_cutoff_max_abs_diff": trunc_audit["settled_bars_max_abs_diff"],
            "all_zero_diff_passed": bool(
                a1["truncation_2024_12_31_max_abs_diff"] == 0.0
                and a2["truncation_2024_12_31_max_abs_diff"] == 0.0
                and trunc_audit["entry_max_abs_diff"] == 0.0
                and trunc_audit["settled_bars_max_abs_diff"] == 0.0
            ),
        },
        "v20_atomic_scorecard_parity": parity_checks,
        "column_role_counts_master": role_counts,
        "source_counts_master": source_counts,
        "market_daily_nonzero_missingness": a1["nonzero_missing_rates"],
        "stock_day_core_catalog": sd_catalog,
        "master_factor_catalog": catalog,
    }

    audit_path = os.path.join(OUT_DIR, "wave1a_factor_catalog_and_pit_audit.json")
    with open(audit_path, "w") as f:
        json.dump(audit_all, f, indent=2, ensure_ascii=False)
    print(f"[Step3] Saved comprehensive audit & catalog -> {audit_path}")
    return audit_all


def main():
    df_full, parity_full = build_master("2026-11-25")
    df_trunc, _ = build_master("2024-12-31")

    # Physical truncation proof at 2024-12-31
    sub_f = df_full[df_full["buy_date"] <= "2024-12-31"].sort_values(["strategy", "buy_date", "code"]).reset_index(drop=True)
    sub_t = df_trunc.sort_values(["strategy", "buy_date", "code"]).reset_index(drop=True)
    assert len(sub_f) == len(sub_t), f"Trunc rows mismatch {len(sub_f)} vs {len(sub_t)}"
    assert (sub_f["strategy"].values == sub_t["strategy"].values).all()
    assert (sub_f["buy_date"].values == sub_t["buy_date"].values).all()
    assert (sub_f["code"].values == sub_t["code"].values).all()

    entry_max_diff = 0.0
    worst_entry = None
    bar_max_diff = 0.0
    worst_bar = None

    for c in df_full.columns:
        if not pd.api.types.is_numeric_dtype(df_full[c]):
            continue
        if c.startswith("bar_tp"):
            # Only compare rows where bar_tp{k}_dt <= 2024-12-31 in full
            sl = c.split("_")[1]
            dt_col = f"bar_{sl}_dt"
            mask_s = (sub_f[dt_col] != "") & (sub_f[dt_col] <= "2024-12-31")
            if mask_s.any():
                a = sub_f.loc[mask_s, c].values.astype(np.float64)
                b = sub_t.loc[mask_s, c].values.astype(np.float64)
                if not np.array_equal(np.isnan(a), np.isnan(b)):
                    d = 999.0
                else:
                    fin = np.isfinite(a) & np.isfinite(b)
                    d = float(np.max(np.abs(a[fin] - b[fin]))) if fin.any() else 0.0
                if d > bar_max_diff:
                    bar_max_diff = d
                    worst_bar = c
            continue

        a = sub_f[c].values.astype(np.float64)
        b = sub_t[c].values.astype(np.float64)
        if not np.array_equal(np.isnan(a), np.isnan(b)):
            d = 999.0
        else:
            fin = np.isfinite(a) & np.isfinite(b)
            d = float(np.max(np.abs(a[fin] - b[fin]))) if fin.any() else 0.0
        if d > entry_max_diff:
            entry_max_diff = d
            worst_entry = c

    print(f"[Step3] 2024-12-31 truncation proof ({len(sub_t)} rows): entry_max_abs_diff={entry_max_diff} (worst={worst_entry}), settled_bar_max_abs_diff={bar_max_diff} (worst={worst_bar})")
    assert entry_max_diff == 0.0, f"Master entry PIT leaked on {worst_entry}: {entry_max_diff}"
    assert bar_max_diff == 0.0, f"Master settled bar mismatch on {worst_bar}: {bar_max_diff}"

    # Write master + 6 per-strategy parquet files
    master_pq = os.path.join(OUT_DIR, "pools_6strat_master_newfactors_pit.parquet")
    df_full.to_parquet(master_pq, index=False, compression="snappy")
    print(f"[Step3] Saved {master_pq} ({df_full.shape}, {round(os.path.getsize(master_pq)/1024/1024, 2)} MB)")
    for st in STRATS:
        sp = os.path.join(OUT_DIR, f"pool_{st}_master_pit.parquet")
        sub = df_full[df_full["strategy"] == st].reset_index(drop=True)
        sub.to_parquet(sp, index=False, compression="snappy")
        print(f"   -> {sp} ({sub.shape})")

    trunc_audit = {
        "trunc_rows": int(len(sub_t)),
        "entry_max_abs_diff": entry_max_diff,
        "settled_bars_max_abs_diff": bar_max_diff,
    }
    build_catalog_and_audit(df_full, parity_full, trunc_audit)


if __name__ == "__main__":
    main()
