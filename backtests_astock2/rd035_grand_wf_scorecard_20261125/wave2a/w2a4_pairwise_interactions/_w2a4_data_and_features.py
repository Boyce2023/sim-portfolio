#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-4 Module 1:
  - Load master 6-strategy pool + oldhot simulation columns (read-only).
  - Extract strictly causal (< buy_date 09:25:00) 1d/3d/1y Xueqiu & Guba burst counts.
  - Precompute exact daily MTM segment multipliers aligned to v20_daily_bench calendar.
  - Construct ~115 strictly T-1 / pre-09:25 mechanism-driven nonlinear interaction features.
  - Provide vectorized, strictly causal (exit_date < t) Top-20 single-factor & 20x19/2
    pairwise quadrant/product interaction learner with multiple-testing guardrails.

Zero yfinance (D12). Deterministic & 100% truncation-invariant at 2024-12-31.
"""
import bisect
import json
import math
import os
import sqlite3
import sys
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
DB_XQ_GB = f"{SIM}/data/xueqiu_guba_5y_pit.db"
DB_COMM = f"{SIM}/data/astock_community_5y_pit.db"
A_DAILY = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"

STRATS = ["1to2", "2to3", "3to4", "high", "pry", "20cm"]

SIM_NEEDED_COLS = {
    "1to2": ["elig_t1", "thr_vec", "elig_t2", "elig_mon", "elig_dom295", "sc_t3_pen", "rk_theme", "t1_dom_plate", "plate", "exit_at_open"],
    "2to3": ["open_pct", "plate_sz", "buy_hhmm", "exit_hhmm"],
    "3to4": ["prio_tie", "buy_hhmm", "exit_hhmm"],
    "high": ["dt_deferred", "b_open_h", "eo"],
    "pry": ["bias10"],
    "20cm": ["buy_px"],
}


def load_master_with_sim_cols(end_cutoff: str = "2026-11-25") -> pd.DataFrame:
    """Load 4,183-row master matrix <= end_cutoff and attach per-strategy sim cols cleanly."""
    master = pd.read_parquet(f"{WAVE1_DIR}/pools_6strat_master_newfactors_pit.parquet")
    master["buy_date"] = master["buy_date"].astype(str).str[:10]
    master["exit_date"] = master["exit_date"].astype(str).str[:10]
    master["code"] = master["code"].astype(str).str.zfill(6)
    if end_cutoff is not None:
        master = master[master["buy_date"] <= end_cutoff].copy().reset_index(drop=True)
    master["sim_ok"] = master["sim_ok"].fillna(0).astype(bool)
    return master


def attach_strategy_sim_cols(df_strat: pd.DataFrame, strat: str) -> pd.DataFrame:
    """Attach exact oldhot simulation fields required by m1.sim_standalone."""
    sub = df_strat.copy().reset_index(drop=True)
    sub["buy_date"] = sub["buy_date"].astype(str).str[:10]
    sub["exit_date"] = sub["exit_date"].astype(str).str[:10]
    sub["code"] = sub["code"].astype(str).str.zfill(6)
    sub["sim_ok"] = sub["sim_ok"].fillna(0).astype(bool)

    oh = pd.read_parquet(f"{RD028_DIR}/pool_{strat}_oldhot.parquet")
    oh["buy_date"] = oh["buy_date"].astype(str).str[:10]
    oh["code"] = oh["code"].astype(str).str.zfill(6)
    needed = SIM_NEEDED_COLS.get(strat, [])
    add_cols = [c for c in needed if c not in sub.columns]
    if add_cols:
        sub = sub.merge(oh[["buy_date", "code"] + add_cols], on=["buy_date", "code"], how="left")
    if strat == "high":
        sub["v51_cb_loss"] = (pd.to_numeric(sub["net_ret"], errors="coerce").to_numpy(float) < -0.02) & (~sub["dt_deferred"].fillna(False).to_numpy(bool))
    return sub


def attach_pit_community_1d_burst(
    df: pd.DataFrame,
    cal_dts: list[str],
    end_cutoff: str = "2026-11-25",
) -> pd.DataFrame:
    """
    Extract strictly pre-09:25 PIT Xueqiu & Guba 1d/3d/250d counts from xueqiu_guba_5y_pit.db
    and astock_community_5y_pit.db, bounded by <= end_cutoff so truncation at 2024-12-31 is exact.
    Window [prev_td 09:25:00, buy_date 09:25:00) for 1d burst, and [T-3 09:25:00, buy_date 09:25:00) for 3d.
    """
    out = df.copy()
    codes = sorted(out["code"].unique())
    if not codes:
        for c in ("w24_xq_1d_pre", "w24_xq_3d_pre", "w24_xq_1y_pre", "w24_gb_1d_pre", "w24_gb_3d_pre", "w24_comm_1d_pre"):
            out[c] = np.float32(0.0)
        return out

    code_sql = ",".join(f"'{c}'" for c in codes)
    cal_sorted = sorted([d for d in cal_dts if d <= end_cutoff])
    cal_idx = {d: i for i, d in enumerate(cal_sorted)}

    c1 = sqlite3.connect(f"file:{DB_XQ_GB}?mode=ro", uri=True)
    xq1 = pd.read_sql_query(
        f"SELECT CAST(post_id AS TEXT) AS pid, symbol AS c6, created_time_str AS ts "
        f"FROM xueqiu_posts WHERE symbol IN ({code_sql}) AND created_time_str >= '2020-01-01' "
        f"AND substr(created_time_str,1,10) <= ?",
        c1,
        params=(end_cutoff,),
    )
    # SQL-side aggregation on 7.5M guba_posts to keep RSS < 500MB
    gb1_agg = pd.read_sql_query(
        f"SELECT sec_code AS c6, substr(pub_time,1,10) AS dt, "
        f"CASE WHEN substr(pub_time,12,8) >= '09:25:00' THEN 1 ELSE 0 END AS after_open, "
        f"COUNT(*) AS cnt "
        f"FROM guba_posts WHERE sec_code IN ({code_sql}) AND pub_time >= '2020-01-01' "
        f"AND pub_time <= ? "
        f"GROUP BY sec_code, substr(pub_time,1,10), after_open",
        c1,
        params=(f"{end_cutoff} 23:59:59",),
    )
    gb1_agg["c6"] = gb1_agg["c6"].astype(str).str.zfill(6)

    c2 = sqlite3.connect(f"file:{DB_COMM}?mode=ro", uri=True)
    cp2 = pd.read_sql_query(
        f"SELECT post_id AS pid, source, symbol AS c6, pub_datetime_cst AS ts "
        f"FROM community_posts WHERE symbol IN ({code_sql}) AND pub_datetime_cst >= '2020-01-01' "
        f"AND substr(pub_datetime_cst,1,10) <= ?",
        c2,
        params=(end_cutoff,),
    )
    c2.close()

    # Deduplicate xueqiu
    cp2_xq = cp2[cp2["source"] == "xueqiu"].copy()
    cp2_xq["pid"] = cp2_xq["pid"].astype(str).str.replace("xueqiu_", "", regex=False)
    xq_all = pd.concat([xq1, cp2_xq[["pid", "c6", "ts"]]], ignore_index=True).drop_duplicates(["pid"])
    xq_all["c6"] = xq_all["c6"].astype(str).str.zfill(6)

    # Deduplicate cp2 guba against guba_posts cleanly in SQLite without loading 4.26M rows
    cp2_gb = cp2[cp2["source"].isin(["eastmoney_guba", "guba"])].copy()
    cp2_gb["pid_clean"] = (
        cp2_gb["pid"].astype(str).str.replace("eastmoney_guba_", "", regex=False).str.replace("guba_", "", regex=False)
    )
    cp2_gb = cp2_gb.drop_duplicates(["pid_clean"])
    existing_pids = set()
    pids_list = cp2_gb["pid_clean"].tolist()
    for i in range(0, len(pids_list), 20000):
        chunk = pids_list[i : i + 20000]
        ph = ",".join("?" for _ in chunk)
        for (pid_hit,) in c1.execute(f"SELECT post_id FROM guba_posts WHERE post_id IN ({ph}) AND pub_time <= ?", chunk + [f"{end_cutoff} 23:59:59"]):
            existing_pids.add(str(pid_hit))
    c1.close()
    cp2_gb_new = cp2_gb[~cp2_gb["pid_clean"].isin(existing_pids)].copy()
    cp2_gb_new["c6"] = cp2_gb_new["c6"].astype(str).str.zfill(6)
    cp2_gb_new["dt"] = cp2_gb_new["ts"].astype(str).str[:10]
    cp2_gb_new["after_open"] = (cp2_gb_new["ts"].astype(str).str[11:19] >= "09:25:00").astype(np.int8)
    gb2_agg = cp2_gb_new.groupby(["c6", "dt", "after_open"], as_index=False).size().rename(columns={"size": "cnt"})

    gb_comb = pd.concat([gb1_agg, gb2_agg], ignore_index=True).groupby(["c6", "dt", "after_open"], as_index=False)["cnt"].sum()

    def _map_to_eff_day_idx_ts(ts_series: pd.Series) -> np.ndarray:
        s = ts_series.astype(str)
        dt = s.str[:10].to_numpy()
        hm = s.str[11:19].to_numpy()
        pos = np.searchsorted(cal_sorted, dt, side="left")
        n_c = len(cal_sorted)
        same_d = (pos < n_c) & (np.array(cal_sorted)[np.minimum(pos, n_c - 1)] == dt)
        return np.where(same_d & (hm >= "09:25:00"), pos + 1, pos)

    def _build_xq_map(ev_df: pd.DataFrame) -> dict[str, np.ndarray]:
        if ev_df.empty:
            return {}
        eff = _map_to_eff_day_idx_ts(ev_df["ts"])
        ok = eff < len(cal_sorted)
        tmp = pd.DataFrame({"c6": ev_df["c6"].to_numpy()[ok], "eff": eff[ok]}).sort_values(["c6", "eff"])
        return {ck: g["eff"].to_numpy(np.int32) for ck, g in tmp.groupby("c6", sort=False)}

    def _build_gb_agg_map(agg_df: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        if agg_df.empty:
            return {}
        dt_arr = agg_df["dt"].to_numpy()
        ao_arr = agg_df["after_open"].to_numpy(np.int8)
        pos = np.searchsorted(cal_sorted, dt_arr, side="left")
        n_c = len(cal_sorted)
        same_d = (pos < n_c) & (np.array(cal_sorted)[np.minimum(pos, n_c - 1)] == dt_arr)
        eff = np.where(same_d & (ao_arr == 1), pos + 1, pos)
        ok = eff < n_c
        tmp = pd.DataFrame({"c6": agg_df["c6"].to_numpy()[ok], "eff": eff[ok], "cnt": agg_df["cnt"].to_numpy(np.int32)[ok]})
        tmp = tmp.groupby(["c6", "eff"], as_index=False)["cnt"].sum().sort_values(["c6", "eff"])
        out_m = {}
        for ck, g in tmp.groupby("c6", sort=False):
            eff_v = g["eff"].to_numpy(np.int32)
            cnt_cs = np.concatenate(([0], np.cumsum(g["cnt"].to_numpy(np.int32))))
            out_m[ck] = (eff_v, cnt_cs)
        return out_m

    xq_map = _build_xq_map(xq_all)
    gb_map = _build_gb_agg_map(gb_comb)

    bd_idx = out["buy_date"].map(cal_idx).fillna(-1).to_numpy(np.int32)
    c_arr = out["code"].to_numpy()
    n = len(out)

    xq_1d = np.zeros(n, dtype=np.float32)
    xq_3d = np.zeros(n, dtype=np.float32)
    xq_1y = np.zeros(n, dtype=np.float32)
    gb_1d = np.zeros(n, dtype=np.float32)
    gb_3d = np.zeros(n, dtype=np.float32)

    for i in range(n):
        bi = int(bd_idx[i])
        if bi < 0:
            continue
        ck = c_arr[i]
        xa = xq_map.get(ck)
        if xa is not None:
            r = int(np.searchsorted(xa, bi, side="right"))
            l1 = int(np.searchsorted(xa, bi, side="left"))
            l3 = int(np.searchsorted(xa, bi - 2, side="left"))
            l1y = int(np.searchsorted(xa, bi - 242, side="left"))
            r1y = int(np.searchsorted(xa, bi - 5, side="left"))
            xq_1d[i] = float(r - l1)
            xq_3d[i] = float(r - l3)
            xq_1y[i] = float(max(0, r1y - l1y))
        ga = gb_map.get(ck)
        if ga is not None:
            geff, gcs = ga
            r = int(np.searchsorted(geff, bi, side="right"))
            l1 = int(np.searchsorted(geff, bi, side="left"))
            l3 = int(np.searchsorted(geff, bi - 2, side="left"))
            gb_1d[i] = float(gcs[r] - gcs[l1])
            gb_3d[i] = float(gcs[r] - gcs[l3])

    out["w24_xq_1d_pre"] = xq_1d
    out["w24_xq_3d_pre"] = xq_3d
    out["w24_xq_1y_pre"] = xq_1y
    out["w24_gb_1d_pre"] = gb_1d
    out["w24_gb_3d_pre"] = gb_3d
    out["w24_comm_1d_pre"] = (xq_1d + gb_1d).astype(np.float32)
    return out


def precompute_exact_mtm_col(
    df: pd.DataFrame,
    cal_dts: list[str],
    end_cutoff: Optional[str] = None,
) -> list[tuple]:
    """
    Compute exact daily MTM segment multipliers `(t_idx, mult)` aligned to `cal_dts`
    (matching wf_scorecard_engine.build_daily_mtm_returns(mtm_col=...)).
    Strictly uses bars in [buy_date, exit_date] <= end_cutoff.
    """
    codes = sorted(df["code"].astype(str).str.zfill(6).unique())
    cols = ["date", "ticker", "open", "close", "adj_close", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp("2020-12-01")
    if end_cutoff is not None:
        flt = flt & (ds.field("date") <= pd.Timestamp(end_cutoff))
    da = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(A_DELISTED, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    dp = pd.concat([da, dd], ignore_index=True)
    del da, dd
    dp["c6"] = dp["ticker"].astype(str).str[:6]
    dp = dp[dp["c6"].isin(codes) & dp["ticker"].astype(str).str.endswith((".SH", ".SZ"))].copy()
    dp["dt"] = dp["date"].dt.strftime("%Y-%m-%d")
    dp = dp.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    dp["adjf"] = np.where((dp["close"] > 0) & (dp["adj_close"] > 0), dp["adj_close"] / dp["close"], 1.0)
    bar_lu = {
        (r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf))
        for r in dp.itertuples(index=False)
    }
    del dp
    import gc
    gc.collect()

    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    T = len(cal_dts)
    segs_all = []
    for r in df.itertuples(index=False):
        sim_ok = bool(getattr(r, "sim_ok", True))
        nr = float(r.net_ret) if pd.notna(r.net_ret) else np.nan
        if (not sim_ok) or (not np.isfinite(nr)):
            segs_all.append(())
            continue
        bi = dt_idx.get(str(r.buy_date)[:10])
        ei = dt_idx.get(str(r.exit_date)[:10])
        if bi is None or ei is None or ei <= bi:
            segs_all.append(())
            continue
        c6 = str(r.code).zfill(6)
        bdt = str(r.buy_date)[:10]
        bb = bar_lu.get((c6, bdt))
        strat = str(getattr(r, "strategy", ""))
        bp_val = getattr(r, "buy_px", np.nan) if strat == "20cm" and hasattr(r, "buy_px") else getattr(r, "buy_price", np.nan)
        if strat == "20cm" and pd.notna(bp_val):
            b_adj = float(bp_val)
        elif pd.notna(bp_val) and bb is not None:
            b_adj = float(bp_val) * bb[4]
        elif bb is not None:
            b_adj = bb[1] * bb[4]
        else:
            b_adj = 1.0
        if b_adj <= 0:
            b_adj = 1.0
        prev_v, last_c = b_adj, b_adj
        segs = []
        for t in range(bi, min(ei, T)):
            bt = bar_lu.get((c6, cal_dts[t]))
            cur_c = (bt[1] * bt[4]) if (bt is not None and bt[1] > 0) else last_c
            if cur_c <= 0:
                cur_c = last_c
            segs.append((t, cur_c / prev_v))
            prev_v, last_c = cur_c, cur_c
        if ei < T:
            segs.append((ei, (b_adj * (1.0 + nr)) / prev_v))
        segs_all.append(tuple(segs))
    return segs_all


def build_mechanism_interactions(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], dict[str, dict]]:
    """
    Build ~115 strictly T-1 / pre-09:25 mechanism-driven nonlinear interaction features.
    Every feature depends purely on row-level T-1/pre-09:25 values -> 100% truncation-invariant.
    Returns (df_with_ix, ix_cols, ix_meta).
    """
    out = df.copy()
    ix_meta: dict[str, dict] = {}
    new_cols: dict[str, np.ndarray] = {}

    def _s(col: str, default: float = np.nan) -> np.ndarray:
        if col not in out.columns:
            return np.full(len(out), default, dtype=np.float64)
        arr = pd.to_numeric(out[col], errors="coerce").to_numpy(dtype=np.float64)
        if not np.isnan(default):
            arr = np.where(np.isfinite(arr), arr, default)
        return arr

    def _add(name: str, arr: np.ndarray, cat: str, desc: str):
        arr_c = np.where(np.isfinite(arr), arr, np.nan).astype(np.float32)
        new_cols[name] = arr_c
        ix_meta[name] = {"category": cat, "description": desc}

    # Normalized core building blocks (strictly T-1 / < 09:25)
    open_pct_pct = _s("open_pct") * 100.0
    d1_open_pct = _s("sd_d1_open_pct")
    d1_ret = _s("sd_ret_1d_t1")
    ret5 = _s("sd_ret_5d_t1")
    ret20 = _s("sd_ret_20d_t1")
    bias10 = _s("sd_bias10_t1")
    bias20 = _s("sd_bias20_t1")
    pos20 = _s("sd_pos_20d_t1")
    pos60 = _s("L3_pos_60d_t1")
    pos250 = _s("L3_pos_250d_t1")
    dd20 = _s("sd_dd_20d_t1")
    dd1y = _s("oh_dd_from_1y_high")
    amp_comp = _s("L3_amp_comp_20v60_t1")
    sd_amp_comp = _s("sd_amp_comp_20v60_t1")
    nh60 = _s("L3_newhigh_cnt60_t1", 0.0)
    turn20 = _s("L3_cum_turn20_t1")
    real_turn = _s("sd_real_turn_pct_t1")
    vr5 = _s("sd_vol_ratio5_t1")
    t520 = _s("sd_turn_5_20_t1")
    overhang = _s("sd_overhang_pct_t1")
    hr10 = _s("sd_hr10d_space_t1")
    hr30 = _s("sd_hr30d_space_t1")
    fmcap = _s("sd_free_mcap_yi_t1")
    rfm_pct = _s("rd25_rfm_pct_all_t1")
    lock_pct = _s("sd_lock_top10_pct_pre", 35.0)
    amt_yi = _s("sd_amount_yi_t1")
    px_raw = _s("sd_prev_close_raw")
    down_stk = _s("sd_down_streak_t1", 0.0)
    prev_stk = _s("sd_prev_streak", 0.0)
    prev_clv = _s("sd_prev_clv", 0.5)
    is_20cm = _s("sd_is_20cm", 0.0)
    seal_ratio = _s("sd_d1_seal_ratio_t1", 0.0)
    first_seal = _s("sd_d1_first_seal_hhmm_t1", -1.0)
    open_bcnt = _s("sd_d1_open_board_cnt_t1", 0.0)
    prev_broken = _s("sd_prev_is_broken_zt", 0.0)

    # Old-hot & community
    xq_1d = _s("w24_xq_1d_pre", 0.0)
    xq_3d = _s("w24_xq_3d_pre", 0.0)
    xq_1y = _s("w24_xq_1y_pre", 0.0)
    gb_1d = _s("w24_gb_1d_pre", 0.0)
    gb_3d = _s("w24_gb_3d_pre", 0.0)
    comm_1d = _s("w24_comm_1d_pre", 0.0)
    comm_1y = _s("oh_comm_posts_1y", 0.0)
    comm_1y_pct = _s("oh_comm_posts_1y_pct", 0.5)
    xq_1y_pct = _s("oh_xq_posts_1y_pct", 0.4)
    comm_actm = _s("oh_comm_active_month_ratio_1y", 0.0)
    waves_3y = _s("oh_waves_3y_g15", 0.0)
    zt_1y = _s("oh_zt_cnt_1y", 0.0)
    trap_3y = _s("oh_trap_waves_3y", 0.0)
    cool_zt = _s("oh_cool_days_since_last_zt", 180.0)
    kpl_plates = _s("oh_kpl_unique_plates_3y", 0.0)
    kpl_top_sh = _s("oh_kpl_top_plate_share", 0.5)

    # LHB / Youzi / ABN / RD25
    bayes = _s("sd_lhb_bayes_t2_t1", 0.0)
    inst_net = _s("sd_lhb_inst_net_yi_t1", 0.0)
    lhasa_sh = _s("sd_lhb_lhasa_share_t1", 0.0)
    good_yz = _s("sd_lhb_has_good_yz_t1", 0.0)
    surf_yz = _s("sd_lhb_has_surf_yz_t1", 0.0)
    quant_in = _s("sd_lhb_has_quant_t1", 0.0)
    fam_yz5 = _s("yz_famous_net_5d_t1", 0.0)
    thm_cap = _s("yz_thm_cap_inflow_t1", 0.0)
    lhb_buy = _s("yz_lhb_buy_yi_t1", 0.0)

    is_yang = _s("abn_d1_is_yang", 0.0)
    is_fakeyin = _s("abn_d1_is_fake_yin", 0.0)
    is_trueyin = _s("abn_d1_is_true_yin", 0.0)
    up_shad = _s("abn_d1_upper_shadow", 0.0)
    lo_shad = _s("abn_d1_lower_shadow", 0.0)
    box5 = _s("abn_box5_range_t1")
    dist_ma5 = _s("abn_dist_ma5_pct_t1")
    yang_stk = _s("rd25_prev_yang_streak", 0.0)
    d1_body = _s("rd25_d1_body_pct", 0.0)
    dist_3d30 = _s("rd25_dist_3d30_t1", 0.0)
    zt_60d = _s("rd25_zt_days_60d_t1", 0.0)
    open_vs_body = _s("rd25_open_vs_d1_body", 0.0)

    # Catalysts / reg / IR
    ir_30d = _s("sd_ir_cnt_30d_pre", 0.0)
    tox_30d = _s("sd_tox_reg_30d_pre", 0.0)
    abn_30d = _s("sd_abn_notice_30d_pre", 0.0)
    cat_earn = _s("rd25_cat_earn_any_3d", 0.0)
    cat_cont = _s("rd25_cat_cont_3d", 0.0)
    cat_ma = _s("rd25_cat_ma_5d", 0.0)

    # L2 Industry & KPL
    ind_ex5 = _s("L2_ind_ex5_t1", 0.0)
    ind_ex20 = _s("L2_ind_ex20_t1", 0.0)
    ind_rank20 = _s("L2_ind_rank20_t1", 15.0)
    ind_pos60 = _s("L2_ind_pos60_t1", 0.5)
    ind_amt_pct = _s("L2_ind_amt_pct250_t1", 0.5)
    ind_zt_sh5 = _s("L2_ind_zt_share5_t1", 0.0)
    ind_upstk = _s("L2_ind_up_streak_t1", 0.0)
    kpl_zt1 = _s("L2_kpl_zt1_t1", 0.0)
    kpl_zt20 = _s("L2_kpl_zt20_t1", 0.0)
    kpl_stk = _s("L2_kpl_streak_t1", 0.0)
    kpl_crowd = _s("L2_kpl_crowd_t1", 0.0)
    kpl_peak = _s("L2_kpl_peak_ratio_t1", 0.0)
    kpl_wave60 = _s("L2_kpl_wave_cnt60_t1", 0.0)

    # L1 Market & Micro & Macro & US
    zt_cnt = _s("L1_zt_cnt_t1", 50.0)
    dt_cnt = _s("L1_dt_cnt_t1", 5.0)
    zt_dt_lr = _s("L1_zt_dt_logratio_t1", 1.0)
    zb_rate = _s("L1_zb_rate_t1", 30.0)
    max_brd = _s("L1_max_board_t1", 5.0)
    lb_cnt = _s("L1_lianban_cnt_t1", 10.0)
    zt_prem = _s("L1_zt_prem_t1", 0.0)
    lb_promo = _s("L1_lb_promo_t1", 20.0)
    damian = _s("L1_duanban_damian_t1", 15.0)
    zt_mom = _s("L1_zt_mom3v20_t1", 1.0)
    sent_ph = _s("L1_sent_phase_t1", 3.0)
    smb5 = _s("L1_smb_5d_t1", 0.0)
    smb20 = _s("L1_smb_20d_t1", 0.0)
    brd5 = _s("L1_breadth_5d_t1", 0.5)
    brd20 = _s("L1_breadth_20d_t1", 0.5)
    amt_r20 = _s("L1_amt_ratio20_t1", 1.0)
    amt_r5v60 = _s("L1_amt_ratio5v60_t1", 1.0)
    ew_bias20 = _s("L1_ew_bias20_t1", 0.0)
    mkt_ma20_pct = _s("mkt_pct_above_ma20_t1", 0.5)
    mkt_ma60_pct = _s("mkt_pct_above_ma60_t1", 0.5)
    mkt_turn_pct = _s("mkt_turn_pct_3y_t1", 0.5)
    mkt_erp_5y = _s("mkt_erp_csi300_pct_5y_t1", 0.5)
    mkt_margin = _s("mkt_margin_to_float_pct_t1", 2.0)
    mkt_yizi_cnt = _s("mkt_yizi_zt_cnt_t1", 5.0)
    mkt_0925_zt = _s("mkt_0925_zt_cnt", 5.0)
    mkt_0925_gap = _s("mkt_0925_avg_gap_pct", 0.0)
    csi_ma20_dist = _s("th_tech_csi300_ma20_dist_t1", 0.0)
    csi_ma20_60 = _s("th_tech_csi300_ma20_60_spread_t1", 0.0)
    sh_shell = _s("th_style_shell_spread_20d_t1", 0.0)
    sh_rev = _s("th_style_rev_20d_spread_t1", 0.0)
    sh_mom = _s("th_style_mom_60d_spread_t1", 0.0)
    nt_v3 = _s("nt_v3_score_live_t1", 0.0)
    etf_spk = _s("nt_etf22_amt_spike_t1", 1.0)
    hw16 = _s("nt_hw16_sync_cnt_t1", 0.0)
    fund8_dump = _s("nt_fund8_dump_cnt_t1", 0.0)
    us_ixic1 = _s("us_ixic_ret1d_on", 0.0)
    us_gspc1 = _s("us_gspc_ret1d_on", 0.0)
    us_rut1 = _s("us_rut_ret1d_on", 0.0)
    us_rut_sp5 = _s("us_rut_vs_gspc_5d_on", 0.0)
    us_vix_chg = _s("us_vix_chg1d_on", 0.0)
    cu_au = _s("comm_cu_au_ratio_ret20_t1", 0.0)
    comm_ring = _s("sd_comm_ring_tier", 0.0)
    comm_cyc = _s("comm_cu_ret5d_t1", 0.0) + _s("comm_au_ret5d_t1", 0.0) + _s("comm_al_ret5d_t1", 0.0)
    pol_rescue = _s("pol_rescue_signal_10d", 0.0)
    pol_crack = _s("pol_crackdown_signal_10d", 0.0)
    earn_win = _s("L1_is_earn_win", 0.0)
    earn_apr = _s("L1_is_earn_apr", 0.0)
    pre_hol = _s("L1_is_pre_hol2", 0.0)
    mon_end = _s("L1_is_month_end3", 0.0)
    is_monday = (pd.to_datetime(out["buy_date"]).dt.weekday == 0).to_numpy(dtype=np.float64)

    # =========================================================================
    # GROUP A: Scissors / Ratios (剪刀差/比值类, 28 features)
    # =========================================================================
    xq_1y_daily = xq_1y / 237.0
    comm_1y_daily = comm_1y / 242.0

    _add("ix_xq_burst_1d_vs_1y", np.log1p(xq_1d) / np.log1p(xq_1y_daily * 10.0 + 0.5), "A_scissors", "雪球1日爆发÷1年日均基线对数比")
    _add("ix_xq_burst_3d_vs_1y", (xq_3d + 0.1) / (xq_1y_daily * 3.0 + 0.5), "A_scissors", "雪球3日爆发÷1年热度基线")
    _add("ix_comm_burst_1d_vs_1y", comm_1d / (comm_1y_daily + 0.5), "A_scissors", "社区总帖1日爆发÷1年日均基线")
    _add("ix_comm_new_narrative_break", ((comm_1d >= 2.0) & (comm_1y_pct <= 0.45)).astype(float), "A_scissors", "低1年基线+突发社区破圈二元")
    _add("ix_comm_oldhot_crowded_trap", np.log1p(comm_1d) * comm_1y_pct, "A_scissors", "高1年老热股+高1日跟风接盘拥挤度")
    _add("ix_xq_to_gb_smart_ratio", (xq_1d + 0.2) / (gb_1d + 2.0), "A_scissors", "雪球聪敏讨论÷股吧散户密度")
    _add("ix_xq_burst_x_low_comm1y", np.log1p(xq_1d + gb_1d * 0.2) * (1.0 - comm_1y_pct), "A_scissors", "突发讨论×低历史热度")

    _add("ix_atr_comp_x_pos60", (1.0 - amp_comp) * pos60, "A_scissors", "ATR波动压缩度×60日平台位置")
    _add("ix_atr_comp_brk60_flag", ((amp_comp <= 0.60) & (pos60 >= 0.85)).astype(float), "A_scissors", "ATR压缩(<0.60)×60日平台突破(>=0.85)")
    _add("ix_atr_comp_x_nh60", (1.0 - sd_amp_comp) * np.log1p(nh60), "A_scissors", "波动压缩×60日新高次数")
    _add("ix_atr_comp_x_vr5", (1.0 - amp_comp) * np.log1p(vr5), "A_scissors", "波动压缩×5日放量倍数")

    _add("ix_ind_crowd_x_brd5_div", ind_amt_pct * (1.0 - brd5), "A_scissors", "行业成交占比250d分位×市场5日宽度背离(us#4)")
    _add("ix_ind_crowd_minus_brd5", ind_amt_pct - brd5, "A_scissors", "行业成交拥挤分位−5日宽度剪刀差(us#4)")
    _add("ix_ind_crowd_peak_div_flag", ((ind_amt_pct >= 0.85) & (brd5 < 0.45)).astype(float), "A_scissors", "行业极端拥挤(>85%)且宽度转弱(<45%)见顶扣分")
    _add("ix_ind_cold_x_atr_brk", (1.0 - ind_amt_pct) * (1.0 - amp_comp) * pos60, "A_scissors", "低拥挤行业×波动压缩×60日突破")
    _add("ix_ind_crowd_x_ind_ex5", ind_amt_pct * ind_ex5, "A_scissors", "行业成交拥挤×行业5日超额")

    _add("ix_small_fmcap_x_kpl_zt", (1.0 / np.log1p(np.maximum(fmcap, 1.0))) * np.log1p(kpl_zt1), "A_scissors", "小自由流值×强主线昨日涨停数")
    _add("ix_small_fmcap_x_ind_zt", (1.0 - rfm_pct) * ind_zt_sh5, "A_scissors", "低自由流值分位×行业涨停占比")
    _add("ix_fmcap_x_kpl_zt_sweet", ((fmcap <= 25.0) & (kpl_zt1 >= 5.0)).astype(float), "A_scissors", "小微自由流(<=25亿)×主线涨停>=5")

    _add("ix_deep_open_x_ice", np.maximum(0.0, -open_pct_pct) * (sent_ph <= 2.0), "A_scissors", "深水低开幅度×昨日冰点/修复情绪")
    _add("ix_deep_open_x_main", np.maximum(0.0, -open_pct_pct) * np.isin(sent_ph, [3.0, 4.0]), "A_scissors", "深水低开幅度×昨日主升/高潮情绪")
    _add("ix_open_x_sent_center", open_pct_pct * (sent_ph - 3.0), "A_scissors", "竞价高开幅度×情绪阶段偏离")
    _add("ix_open_per_zt_heat", open_pct_pct / (zt_cnt / 60.0 + 0.5), "A_scissors", "竞价溢价÷昨日涨停热度")

    _add("ix_turn20_x_dd1y", np.log1p(np.maximum(turn20, 0.0)) * np.maximum(0.0, -dd1y), "A_scissors", "20日累计换手×距1年高点深套回撤")
    _add("ix_turn20_per_dd1y", turn20 / (np.abs(dd1y) + 0.05), "A_scissors", "20日换手÷1年回撤(高位强换手浓度)")
    _add("ix_bayes_x_cool_log", bayes * np.log1p(np.maximum(cool_zt, 0.0)), "A_scissors", "游资贝叶斯得分×老热股冷却期")
    _add("ix_bayes_x_dormant", bayes * ((waves_3y >= 2.0) & (cool_zt > 90.0)), "A_scissors", "游资贝叶斯×沉睡>90天老妖再起")

    _add("ix_us_ixic_minus_open", us_ixic1 - open_pct_pct, "A_scissors", "纳指隔夜动量−A股09:25竞价缺口(us#1)")
    _add("ix_us_gspc_minus_open", us_gspc1 - open_pct_pct, "A_scissors", "标普隔夜动量−A股09:25竞价缺口(us#1)")
    _add("ix_us_rut_minus_mktgap", us_rut1 - mkt_0925_gap, "A_scissors", "罗素小盘隔夜−A股全市场09:25均缺口")
    _add("ix_us_up_ashare_tame", (us_ixic1 >= 1.2) * np.maximum(0.0, 2.0 - open_pct_pct), "A_scissors", "美股大涨但A股温和未抢跑缺口")

    # =========================================================================
    # GROUP B: Cross-Board Position & Sentiment Conditionals (跨板位与情绪, 28 features)
    # =========================================================================
    _add("ix_maxbrd_x_stock_stk", max_brd * (prev_stk + 1.0), "B_board_sent", "昨日高标高度×个股板位")
    _add("ix_maxbrd_headroom", max_brd - prev_stk, "B_board_sent", "昨日最高板与个股板位高度差")
    _add("ix_zbrate_x_boardpos", zb_rate * (prev_stk + 1.0), "B_board_sent", "昨日炸板率×个股板位")
    _add("ix_damian_x_boardpos", damian * (prev_stk + 1.0), "B_board_sent", "昨日断板大面率×个股板位")
    _add("ix_zbrate_x_high_open", zb_rate * np.maximum(0.0, open_pct_pct), "B_board_sent", "高炸板率×今日高开幅度")
    _add("ix_damian_x_deep_open", damian * np.maximum(0.0, -open_pct_pct), "B_board_sent", "高大面率×今日低开深度")
    _add("ix_lb_promo_x_boardpos", lb_promo * prev_stk, "B_board_sent", "连板晋级率×个股连板数")

    _add("ix_kpl_zt_x_peak_ratio", kpl_zt1 * kpl_peak, "B_board_sent", "同题材昨日涨停数×题材龙头高度占比")
    _add("ix_kpl_zt_x_leader_stk", np.log1p(kpl_zt1) * kpl_stk, "B_board_sent", "同题材昨日涨停数×题材最高板连板数")
    _add("ix_kpl_zt_x_stock_stk", np.log1p(kpl_zt1) * (prev_stk + 1.0), "B_board_sent", "同题材昨日涨停数×个股板位")
    _add("ix_kpl_zt_accel_ratio", (kpl_zt1 + 0.5) / (kpl_zt20 / 20.0 + 0.5), "B_board_sent", "题材昨日涨停爆发÷20日日均加速比")
    _add("ix_kpl_leader_x_open", (kpl_peak >= 0.8) * (prev_broken == 0.0) * open_pct_pct, "B_board_sent", "题材前排龙头状态×今日开盘")
    _add("ix_kpl_crowd_x_open", kpl_crowd * open_pct_pct, "B_board_sent", "题材拥挤度×今日开盘")
    _add("ix_kpl_wave60_x_dd1y", kpl_wave60 * np.maximum(0.0, -dd1y), "B_board_sent", "题材60日波次×个股回撤")

    _add("ix_csima_x_smb20_x_open", np.sign(csi_ma20_dist) * smb20 * open_pct_pct, "B_board_sent", "大盘MA20状态×小微盘风格差×个股开盘")
    _add("ix_csima_spread_x_smb5_x_open", (csi_ma20_60 > 0).astype(float) * smb5 * open_pct_pct, "B_board_sent", "大盘多头排列×5日风格差×个股开盘")
    _add("ix_bull_mkt_x_small_mcap", (mkt_ma20_pct >= 0.50) * (1.0 - rfm_pct), "B_board_sent", "市场MA20宽度>=50%×小自由流")
    _add("ix_bear_mkt_x_deep_open", (mkt_ma60_pct < 0.35) * np.maximum(0.0, -open_pct_pct), "B_board_sent", "弱市MA60宽度<35%×深水低开")
    _add("ix_smb20_x_fmcap_match", smb20 * (0.5 - rfm_pct), "B_board_sent", "小微盘风格占优×标的大小匹配")
    _add("ix_smb5_x_20cm", smb5 * is_20cm, "B_board_sent", "5日小微盘风格差×20cm属性")

    _add("ix_open_excess_vs_mkt0925", open_pct_pct - mkt_0925_gap, "B_board_sent", "个股09:25缺口−全市场09:25均缺口")
    _add("ix_open_minus_d1ret", open_pct_pct - d1_ret, "B_board_sent", "今日竞价−昨日涨跌幅")
    _add("ix_open_minus_ztprem", open_pct_pct - zt_prem, "B_board_sent", "今日竞价−昨日涨停溢价均值")
    _add("ix_mkt0925_zt_x_open", np.log1p(mkt_0925_zt) * open_pct_pct, "B_board_sent", "09:25一字涨停数×个股开盘")
    _add("ix_mkt_yizi_share_x_open", (mkt_yizi_cnt / (zt_cnt + 1.0)) * open_pct_pct, "B_board_sent", "昨日一字板占比×今日开盘")
    _add("ix_ice_x_oversold_bias10", (sent_ph <= 2.0) * np.maximum(0.0, -bias10), "B_board_sent", "冰点情绪×超跌负乖离")
    _add("ix_climax_x_overbought", (zt_cnt >= 90.0) * np.maximum(0.0, bias20), "B_board_sent", "高潮情绪×高正乖离追高风险")
    _add("ix_sent_x_zt_mom", sent_ph * zt_mom, "B_board_sent", "情绪周期×涨停3日vs20日动量")

    # =========================================================================
    # GROUP C: Youzi / Chips / Old-Hot / K-line / Catalyst / Macro (59 features)
    # =========================================================================
    _add("ix_inst_minus_lhasa", inst_net - lhasa_sh * 2.0, "C_youzi_chip", "机构净买−拉萨散户净剪刀差")
    _add("ix_famous_yz_x_no_lhasa", np.tanh(fam_yz5) * (1.0 - lhasa_sh), "C_youzi_chip", "5日知名游资净买×去拉萨纯净度")
    _add("ix_thm_cap_pct_fmcap", thm_cap / (np.maximum(fmcap, 1.0) + 5.0), "C_youzi_chip", "昨日游资主力净流入÷自由流通市值")
    _add("ix_lhb_buy_pct_amt", lhb_buy / (np.maximum(amt_yi, 0.1) + 0.1), "C_youzi_chip", "龙虎榜买额÷昨日成交额占比")
    _add("ix_lock_x_real_turn", (lock_pct / 100.0) * real_turn, "C_youzi_chip", "前十大锁仓率×真实换手率")
    _add("ix_real_turn_per_vr5", real_turn / (np.maximum(vr5, 0.2) + 0.2), "C_youzi_chip", "真实换手÷5日量比")
    _add("ix_good_yz_x_clean_trap", good_yz * (trap_3y <= 1.0).astype(float), "C_youzi_chip", "良性游资席位×低坑人历史")
    _add("ix_surf_yz_x_lhasa", surf_yz * lhasa_sh, "C_youzi_chip", "一日游席位×拉萨席位占比")
    _add("ix_quant_x_turn", quant_in * np.log1p(np.maximum(real_turn, 0.0)), "C_youzi_chip", "量化席位×高换手")
    _add("ix_seal_tight_x_mkt_seal", seal_ratio * (100.0 - zb_rate) / 100.0, "C_youzi_chip", "个股封单比×市场封板率")
    _add("ix_early_seal_x_kpl", ((first_seal > 0) & (first_seal <= 1030)) * np.log1p(kpl_zt1), "C_youzi_chip", "早盘封板×题材涨停强度")
    _add("ix_late_seal_x_high_open", (first_seal >= 1400) * np.maximum(0.0, open_pct_pct), "C_youzi_chip", "尾盘烂板×次日高开接盘")
    _add("ix_open_bcnt_x_open", open_bcnt * open_pct_pct, "C_youzi_chip", "昨日炸板次数×今日开盘")

    _add("ix_waves_x_dd1y", waves_3y * np.maximum(0.0, -dd1y), "C_oldhot_space", "3年脉冲波次×距1年高点回撤")
    _add("ix_waves_per_cool", waves_3y / np.log1p(np.maximum(cool_zt, 0.0)), "C_oldhot_space", "3年波次÷冷却天数(高频老油条密度)")
    _add("ix_trap_x_overhang", trap_3y * overhang, "C_oldhot_space", "3年坑人波次×套牢盘比例")
    _add("ix_kpl_cham_x_comm1y", kpl_plates * comm_1y_pct, "C_oldhot_space", "开盘啦题材马甲数×1年社区热度分位")
    _add("ix_kpl_focus_x_theme_zt", kpl_top_sh * np.log1p(kpl_zt1), "C_oldhot_space", "题材专一度×当前题材涨停数")
    _add("ix_hr_min_space", np.minimum(np.clip(hr10, -20.0, 80.0), np.clip(hr30, -20.0, 150.0)), "C_oldhot_space", "10日/30日严重异动空间瓶颈最小值")
    _add("ix_hr10_tight_x_open", (hr10 <= 12.0).astype(float) * open_pct_pct, "C_oldhot_space", "逼近10日100%异动线×高开风险")
    _add("ix_clean_high_pos250", (1.0 - overhang) * pos250, "C_oldhot_space", "低套牢盘×250日高位强趋势")
    _add("ix_pos250_minus_pos20", pos250 - pos20, "C_oldhot_space", "250日长强−20日短回踩剪刀差")
    _add("ix_act_pos_per_turn", _s("L3_act_x_pos_t1", 0.0) / (_s("L3_turn20_pct250_t1", 0.5) + 0.1), "C_oldhot_space", "活跃度×位置÷换手分位")
    _add("ix_zt1y_vs_kpl_zt", (zt_1y + 1.0) / (kpl_zt1 + 1.0), "C_oldhot_space", "个股1年涨停数÷当前题材涨停数")
    _add("ix_px_le20_x_fmcap", (px_raw <= 20.0).astype(float) * (1.0 - rfm_pct), "C_oldhot_space", "低价<=20元×小自由流值")

    _add("ix_d1_clv_x_open", prev_clv * open_pct_pct, "C_kline_micro", "昨日收盘位置CLV×今日竞价")
    _add("ix_d1_upshad_x_open", up_shad * open_pct_pct, "C_kline_micro", "昨日上影线×今日竞价")
    _add("ix_d1_loshad_x_deepopen", lo_shad * np.maximum(0.0, -open_pct_pct), "C_kline_micro", "昨日下影承接×今日低开")
    _add("ix_fakeyin_x_open", is_fakeyin * open_pct_pct, "C_kline_micro", "昨日假阴真强×今日开盘")
    _add("ix_trueyin_x_open", is_trueyin * open_pct_pct, "C_kline_micro", "昨日真阴×今日开盘反核幅度")
    _add("ix_dist_ma5_x_vr5", dist_ma5 * np.log1p(np.maximum(vr5, 0.0)), "C_kline_micro", "偏离MA5幅度×5日量比")
    _add("ix_box5_tight_x_vr5", (1.0 / (np.maximum(box5, 0.5) + 1.0)) * np.log1p(np.maximum(vr5, 0.0)), "C_kline_micro", "5日极窄箱体×放量启动")
    _add("ix_down_stk_x_bias10", down_stk * np.maximum(0.0, -bias10), "C_kline_micro", "连阴天数×负乖离(撬板/反抽张力)")
    _add("ix_yang_stk_x_body", yang_stk * d1_body, "C_kline_micro", "连阳天数×昨日实体涨幅")
    _add("ix_open_body_x_vr5", open_vs_body * np.log1p(np.maximum(vr5, 0.0)), "C_kline_micro", "开盘相对昨日实体×5日量比")
    _add("ix_dist3d30_x_zt60", dist_3d30 * np.log1p(zt_60d), "C_kline_micro", "3日30%空间×60日涨停天数")
    _add("ix_t520_x_dd20", t520 * np.maximum(0.0, -dd20), "C_kline_micro", "5日/20日换手比×20日回撤")

    _add("ix_ir_x_low_comm", np.log1p(ir_30d) * (1.0 - comm_1y_pct), "C_cat_reg", "30日机构调研×低散户热度(研究脑洞#2)")
    _add("ix_ir_x_low_pos60", (ir_30d > 0).astype(float) * (1.0 - pos60), "C_cat_reg", "机构调研×低位潜伏")
    has_cat = ((cat_earn + cat_cont + cat_ma) > 0).astype(float)
    _add("ix_cat_x_low_ret20", has_cat * np.clip(-ret20, -30.0, 30.0), "C_cat_reg", "硬催化公告×近20日未抢跑")
    _add("ix_tox_reg_x_high_ret20", ((tox_30d + abn_30d) > 0).astype(float) * np.maximum(0.0, ret20), "C_cat_reg", "监管/异常公告×高位涨幅排雷")
    _add("ix_earn_win_x_cat", earn_win * (cat_earn > 0).astype(float), "C_cat_reg", "财报窗口×业绩预增公告")
    _add("ix_earn_apr_x_small", earn_apr * (1.0 - rfm_pct), "C_cat_reg", "4月业绩雷期×小微盘")

    _add("ix_nt_v3_x_sent", nt_v3 * (3.0 - sent_ph), "C_macro_us", "国家队V3脉冲×市场情绪偏离")
    _add("ix_etf_spike_x_smb5", etf_spk * smb5, "C_macro_us", "权重ETF放量虹吸×小微盘5日差")
    _add("ix_hw16_x_mkt_amt", hw16 * amt_r20, "C_macro_us", "国家队护盘同步度×市场量能")
    _add("ix_fund8_dump_x_pos250", fund8_dump * pos250, "C_macro_us", "公募高位砸盘数×个股250日高位")
    _add("ix_us_vix_chg_x_open", us_vix_chg * open_pct_pct, "C_macro_us", "VIX隔夜变化×A股开盘")
    _add("ix_us_rut_x_ashare_smb", us_rut_sp5 * smb20, "C_macro_us", "美股大小盘风格×A股大小盘风格")
    _add("ix_cu_au_x_ind_ex20", cu_au * ind_ex20, "C_macro_us", "铜金比风险偏好×行业20日超额")
    _add("ix_comm_ring_x_cyc", comm_ring * np.sign(comm_cyc), "C_macro_us", "资源三环属性×外盘商品5日方向")
    _add("ix_amt_r5v60_x_turnpct", amt_r5v60 * mkt_turn_pct, "C_macro_us", "市场短长量能比×3年换手分位")
    _add("ix_erp_x_ice", mkt_erp_5y * (sent_ph <= 2.0).astype(float), "C_macro_us", "股债性价比分位×市场冰点")
    _add("ix_margin_x_climax", mkt_margin * (zt_cnt >= 80.0).astype(float), "C_macro_us", "融资占比×情绪高潮")
    _add("ix_pol_rescue_x_ice", pol_rescue * (sent_ph <= 2.0).astype(float), "C_macro_us", "政策救市信号×冰点")
    _add("ix_pol_crack_x_stk", pol_crack * prev_stk, "C_macro_us", "政策敲打信号×高连板")
    _add("ix_sh_shell_x_fmcap", sh_shell * (1.0 - rfm_pct), "C_macro_us", "壳价值风格脉冲×小自由流")
    _add("ix_sh_rev_x_ret20", sh_rev * (-ret20), "C_macro_us", "反转风格脉冲×近20日超跌")
    _add("ix_sh_mom_x_ret20", sh_mom * ret20, "C_macro_us", "动量风格脉冲×近20日涨幅")
    _add("ix_brd_mom_x_ztmom", (brd5 - brd20) * zt_mom, "C_macro_us", "宽度动量×涨停动量")
    _add("ix_ew_bias20_x_open", ew_bias20 * open_pct_pct, "C_macro_us", "等权MA20乖离×个股开盘")
    _add("ix_ztdt_lr_x_open", zt_dt_lr * open_pct_pct, "C_macro_us", "涨跌停对数比×个股开盘")
    _add("ix_ind_ex5_vs_ex20", ind_ex5 - ind_ex20 / 4.0, "C_macro_us", "行业5日vs20日超额加速度")
    _add("ix_ind_rank_x_pos60", (1.0 / (np.maximum(ind_rank20, 0.0) + 1.0)) * pos60, "C_macro_us", "行业排名倒数×个股60日位置")
    _add("ix_ind_upstk_x_brd5_inv", ind_upstk * (1.0 - brd5), "C_macro_us", "行业连阳×市场宽度背离")
    _add("ix_prehol_x_open", pre_hol * open_pct_pct, "C_macro_us", "节前效应×个股开盘")
    _add("ix_monthend_x_small", mon_end * (1.0 - rfm_pct), "C_macro_us", "月末效应×小微盘")
    _add("ix_mkt_seal80_fix", (100.0 - zb_rate >= 80.0).astype(float), "C_macro_us", "全市场封板率>=80%(修复scale)")
    _add("ix_monday_fix", is_monday, "C_macro_us", "周一效应(修复L1_weekday)")
    _add("ix_seal80_x_stk", (100.0 - zb_rate >= 80.0).astype(float) * (prev_stk + 1.0), "C_macro_us", "高封板环境×板位")
    _add("ix_monday_x_open", is_monday * open_pct_pct, "C_macro_us", "周一效应×开盘幅度")

    ix_df = pd.DataFrame(new_cols, index=out.index)
    out = pd.concat([out, ix_df], axis=1)
    return out, list(new_cols.keys()), ix_meta


def select_base_single_factors_for_dyn(df: pd.DataFrame, strat: Optional[str] = None) -> list[str]:
    """
    Pick clean non-leaking, non-redundant T-1/pre-09:25 base numeric single factors from master
    for causal exit_date < t Top-20 x 19/2 pairwise interaction discovery.
    Removes duplicate clones across sd_/L3_/L2_ prefixes and sparse (<5%) indicators.
    """
    exclude_exact = {
        "strategy", "buy_date", "entry_date", "exit_date", "sig_date", "code", "name",
        "base_score", "v20_score", "orig_score", "is_pass_official", "orig_pass",
        "net_ret", "ret", "buy_hhmm", "exit_hhmm", "buy_price", "exit_price", "sim_ok",
        "hold_bars", "exit_reason", "plate", "is_s_tier", "is_edge_cand", "is_near_line",
        "is_obs_a76", "is_standalone_slot1", "is_v20_slot1", "pool_layer", "year",
        "era_tag", "is_oos_split", "can_buy_hygiene", "mtm_full", "buy_px",
        "elig_t1", "thr_vec", "elig_t2", "elig_mon", "elig_dom295", "sc_t3_pen",
        "rk_theme", "t1_dom_plate", "exit_at_open", "plate_sz", "prio_tie",
        "dt_deferred", "b_open_h", "eo", "v51_cb_loss", "bias10",
        # Redundant cross-prefix clones (keep canonical versions)
        "sd_pos_60d_t1", "sd_pos_250d_t1", "sd_amp_comp_20v60_t1", "sd_overhang_pct_t1",
        "sd_bias20_t1", "sd_csrc_ind_ex5_t1", "sd_csrc_ind_ex20_t1", "sd_csrc_ind_rank20_t1",
        "sd_csrc_ind_zt_share5_t1", "sd_csrc_ind_amt_pct250_t1", "sd_csrc_ind_id",
        "sd_kpl_zt1_t1", "sd_kpl_zt3_t1", "sd_kpl_streak_t1", "sd_is_st_pit", "sd_prev_is_yizi_zt",
        "oh_zt_cnt_1y_t1", "oh_zt_cnt_3y_t1", "oh_waves_3y_g15_t1", "oh_waves_5y_g15_t1",
        "L1_weekday", "rd25_xq_3d_pre", "rd25_gb_3d_pre",
    }
    valid_prefixes = (
        "oh_", "L1_", "L2_", "L3_", "sd_", "rd25_", "abn_", "yz_",
        "mkt_", "mkt20_", "th_", "nt_", "us_", "comm_", "macro_", "wp_", "pol_", "xtr_", "w24_",
    )
    cols = []
    if "open_pct" in df.columns:
        cols.append("open_pct")
    for c in df.columns:
        if c in exclude_exact or c.startswith(("bar_", "ix_", "strat_")):
            continue
        if c.startswith(valid_prefixes):
            if pd.api.types.is_numeric_dtype(df[c]):
                if float(df[c].isna().mean()) <= 0.25 and float(df[c].std()) > 1e-6:
                    # Skip hyper-sparse binary dummies (<3% positive rate)
                    uniq = df[c].dropna().unique()
                    if len(uniq) <= 2 and float((df[c] > uniq.min()).mean()) < 0.03:
                        continue
                    cols.append(c)
    return cols


# =============================================================================
# Vectorized Strictly-Causal (exit_date < t) Top-20 x 19/2 Pairwise Learner
# =============================================================================

def _batch_cluster_t_stats(u: np.ndarray, Z: np.ndarray, g_inv: np.ndarray, G: int) -> np.ndarray:
    """
    Fast vectorized Liang-Zeger / CGM cluster-robust OLS t-stats for u ~ 1 + z_j across all F columns of Z.
    Assumes Z has finite values (or pre-imputed/masked separately); handles columns cleanly.
    """
    n, F = Z.shape
    if n < 20 or G < 5 or F == 0:
        return np.zeros(F, dtype=np.float64)
    du = u - np.mean(u)
    dz = Z - np.mean(Z, axis=0, keepdims=True)
    szz = np.einsum("ij,ij->j", dz, dz)
    sduz = du @ dz
    with np.errstate(divide="ignore", invalid="ignore"):
        beta = np.where(szz > 1e-12, sduz / szz, 0.0)
    # eps_ij = du_i - beta_j * dz_ij -> sum_cluster(dz_ij * eps_ij) = sum_cluster(dz_ij * du_i) - beta_j * sum_cluster(dz_ij^2)
    # Using bincount via one-hot or loop over G? Matrix multiply with group indicator!
    # Since M <= 4183 and G <= 1000, sparse or dense G_ind? Even simpler: np.add.at or matrix G_one_hot!
    # Wait: if G=600, F=760, a (G, M) matrix is 600*4000*8 = 19MB -> two BLAS matmuls take < 1ms!
    # Let's construct G_oh (G, n) or loop if G is tiny.
    G_oh = np.zeros((G, n), dtype=np.float64)
    G_oh[g_inv, np.arange(n)] = 1.0
    sg_duz = G_oh @ (dz * du[:, None])       # (G, F)
    sg_dz2 = G_oh @ (dz * dz)                # (G, F)
    sg = sg_duz - sg_dz2 * beta[None, :]     # (G, F)
    sum_sg2 = np.einsum("ij,ij->j", sg, sg)  # (F,)
    var_b = (G / max(1, G - 1)) * sum_sg2 / np.maximum(szz * szz, 1e-18)
    valid = (szz > 1e-12) & (var_b > 1e-18)
    t_out = np.zeros(F, dtype=np.float64)
    t_out[valid] = beta[valid] / np.sqrt(var_b[valid])
    return t_out


def fit_causal_interaction_scorecard(
    X_mech_tr: np.ndarray,
    X_base_tr: np.ndarray,
    y_ret: np.ndarray,
    y_win: np.ndarray,
    day_ids: np.ndarray,
    mech_names: list[str],
    base_names: list[str],
    mode: str = "scorecard_0_100",
    top_k: int = 12,
    min_k: int = 5,
    max_corr: float = 0.65,
    min_t_stat: float = 1.2,
    min_t_stat_dyn: float = 2.6,
    min_synergy_t: float = 1.6,
    shrink_tau: float = 20.0,
    max_delta: int = 15,
    orig_score_train: Optional[np.ndarray] = None,
    max_corr_orig: Optional[float] = 0.70,
    top_base_k: int = 20,
    max_dyn_keep: int = 25,
) -> dict:
    """
    Strictly inside training window (exit_date < t):
      1. Screen single base factors, keep top `top_base_k` (20) orthogonalized (|r|<=0.85).
      2. Compute training medians/IQRs/signs on those 20, generate all 20*19/2 = 190 pairs
         across 4 nonlinear forms (HiA_HiB, HiA_LoB, LoA_HiB, zA*zB) -> 760 dynamic interactions.
      3. Enforce multiple-testing hurdle (|t_cluster| >= min_t_stat_dyn AND incremental synergy
         |t_resid| >= min_synergy_t after controlling for linear zA + zB!). Keep top `max_dyn_keep`.
      4. Combine static mechanism interactions (`X_mech_tr`) + surviving dynamic pairs,
         and fit transparent integer scorecard using exact same `_wf_core` rules.
    """
    import _wf_core as wfc

    M, F_mech = X_mech_tr.shape
    F_base = X_base_tr.shape[1]
    mu0_all = float(np.mean(y_ret))
    wr0_all = float(np.mean(y_win))
    sd_all = max(1e-5, float(np.std(y_ret, ddof=1))) if M > 1 else 0.05
    u_all = 0.6 * (y_ret - mu0_all) / sd_all + 0.4 * (y_win - wr0_all) / 0.25
    _, g_inv = np.unique(day_ids, return_inverse=True)
    G = int(g_inv.max()) + 1
    min_valid_n = max(35, int(0.45 * M))

    # --- Step 1: Vectorized base single factor screen on exit_date < t ---
    dyn_pairs_meta = []
    X_dyn_tr = np.empty((M, 0), dtype=np.float64)

    if F_base >= 2 and M >= 40 and G >= 5:
        fin_mask = np.isfinite(X_base_tr)
        cnt_valid = fin_mask.sum(axis=0)
        # Impute NaNs with training median solely for fast initial vectorized t-screen
        col_meds = np.nanmedian(X_base_tr, axis=0)
        col_meds = np.where(np.isfinite(col_meds), col_meds, 0.0)
        Xb_imp = np.where(fin_mask, X_base_tr, col_meds[None, :])
        col_stds = np.std(Xb_imp, axis=0)
        ok_b = (cnt_valid >= min_valid_n) & (col_stds > 1e-9)
        ok_idx = np.where(ok_b)[0]

        if len(ok_idx) >= 2:
            t_base = _batch_cluster_t_stats(u_all, Xb_imp[:, ok_idx], g_inv, G)
            order = np.argsort(-np.abs(t_base), kind="mergesort")
            sel_base = []
            for oi in order:
                j = int(ok_idx[oi])
                xj = Xb_imp[:, j]
                ok_c = True
                for sj, _, _, _, _, _ in sel_base:
                    xs = Xb_imp[:, sj]
                    r = abs(float(np.corrcoef(xj, xs)[0, 1]))
                    if r > 0.85:
                        ok_c = False
                        break
                if ok_c:
                    med_j = float(col_meds[j])
                    xj_all = Xb_imp[:, j]
                    n_gt_med = int(np.sum(xj_all > med_j))
                    if n_gt_med >= 15 and (M - n_gt_med) >= 15:
                        thr_j = med_j
                    else:
                        mean_j = float(np.mean(xj_all))
                        n_gt_mean = int(np.sum(xj_all > mean_j))
                        if n_gt_mean >= 15 and (M - n_gt_mean) >= 15:
                            thr_j = mean_j
                        else:
                            continue
                    q25, q75 = np.percentile(xj_all, [25.0, 75.0])
                    iqr_j = float(q75 - q25)
                    if iqr_j <= 1e-9:
                        iqr_j = max(1e-6, float(col_stds[j]))
                    tj = float(t_base[oi])
                    sgn_j = 1.0 if tj >= 0 else -1.0
                    sel_base.append((j, med_j, thr_j, iqr_j, sgn_j, tj))
                    if len(sel_base) >= top_base_k:
                        break

            K_sel = len(sel_base)
            if K_sel >= 2:
                # Build standardized z and high/low quadrant indicators for the K_sel <= 20 factors
                Z_top = np.empty((M, K_sel), dtype=np.float64)
                HI_top = np.empty((M, K_sel), dtype=bool)
                for p_i, (j, med_j, thr_j, iqr_j, sgn_j, _) in enumerate(sel_base):
                    xj = np.where(np.isfinite(X_base_tr[:, j]), X_base_tr[:, j], med_j)
                    zj = np.clip((xj - med_j) / iqr_j, -3.0, 3.0) * sgn_j
                    Z_top[:, p_i] = zj
                    HI_top[:, p_i] = xj > thr_j

                # All K_sel * (K_sel - 1) / 2 pairs -> 5 nonlinear forms (4 quadrants + product)
                pair_cols = []
                pair_specs = []
                for a in range(K_sel):
                    za, ha = Z_top[:, a], HI_top[:, a]
                    na_name = base_names[sel_base[a][0]]
                    ta_val = abs(sel_base[a][5])
                    for b in range(a + 1, K_sel):
                        zb, hb = Z_top[:, b], HI_top[:, b]
                        nb_name = base_names[sel_base[b][0]]
                        tb_val = abs(sel_base[b][5])
                        max_single_t = max(ta_val, tb_val)

                        # 4 symmetric quadrants + continuous standardized product
                        c_hh = (ha & hb).astype(np.float64)
                        c_hl = (ha & (~hb)).astype(np.float64)
                        c_lh = ((~ha) & hb).astype(np.float64)
                        c_ll = ((~ha) & (~hb)).astype(np.float64)
                        c_pr = za * zb

                        min_cell = max(30, int(0.05 * M))
                        for tag, vec in [("HiHi", c_hh), ("HiLo", c_hl), ("LoHi", c_lh), ("LoLo", c_ll), ("Prod", c_pr)]:
                            if tag != "Prod":
                                s_v = float(vec.sum())
                                if s_v < min_cell or (M - s_v) < min_cell:
                                    continue
                            else:
                                # Guard Prod against >95% spike at zero/median (sparse corner explosion)
                                n_nonmed = int(np.sum(np.abs(vec - float(np.median(vec))) > 1e-6))
                                if n_nonmed < min_cell or float(np.std(vec)) <= 1e-6:
                                    continue
                            pair_cols.append(vec)
                            pair_specs.append((a, b, tag, f"dyn_{tag}__{na_name}__x__{nb_name}", max_single_t))

                if pair_cols:
                    P_mat = np.column_stack(pair_cols)
                    t_pairs = _batch_cluster_t_stats(u_all, P_mat, g_inv, G)
                    # Closed-form 2-regressor Gram-Schmidt orthogonalization for synergy test (100x faster than lstsq)
                    Zc = Z_top - np.mean(Z_top, axis=0, keepdims=True)
                    cand_dyn = []
                    for pi_idx, t_p in enumerate(t_pairs):
                        if abs(t_p) < min_t_stat_dyn:
                            continue
                        a, b, tag, pname, max_single_t = pair_specs[pi_idx]
                        p_col = P_mat[:, pi_idx]
                        pc = p_col - np.mean(p_col)
                        za = Zc[:, a]
                        zb = Zc[:, b]
                        saa = float(np.dot(za, za))
                        sbb = float(np.dot(zb, zb))
                        sab = float(np.dot(za, zb))
                        sap = float(np.dot(za, pc))
                        sbp = float(np.dot(zb, pc))
                        det = saa * sbb - sab * sab
                        if det > 1e-12:
                            b_a = (sbb * sap - sab * sbp) / det
                            b_b = (saa * sbp - sab * sap) / det
                            resid = pc - b_a * za - b_b * zb
                        else:
                            resid = pc - (sap / max(saa, 1e-12)) * za
                        if float(np.std(resid)) < 1e-6:
                            continue
                        t_syn = float(_batch_cluster_t_stats(u_all, resid[:, None], g_inv, G)[0])
                        if abs(t_syn) >= min_synergy_t:
                            cand_dyn.append((abs(t_p), abs(t_syn), pi_idx, a, b, tag, pname))

                    cand_dyn.sort(key=lambda x: (-x[0], -x[1], x[6]))
                    cand_dyn = cand_dyn[:max_dyn_keep]
                    if cand_dyn:
                        X_dyn_tr = np.column_stack([P_mat[:, c[2]] for c in cand_dyn])
                        for _, t_syn, _, a, b, tag, pname in cand_dyn:
                            j_a, med_a, thr_a, iqr_a, sgn_a, _ = sel_base[a]
                            j_b, med_b, thr_b, iqr_b, sgn_b, _ = sel_base[b]
                            dyn_pairs_meta.append({
                                "name": pname,
                                "tag": tag,
                                "j_a": j_a, "med_a": med_a, "thr_a": thr_a, "iqr_a": iqr_a, "sgn_a": sgn_a,
                                "j_b": j_b, "med_b": med_b, "thr_b": thr_b, "iqr_b": iqr_b, "sgn_b": sgn_b,
                                "t_synergy": round(t_syn, 3),
                            })

    # Filter static mechanism features for >=5% non-median support on current M rows (prevents sparse-bin t=26 flukes)
    min_supp = max(25, int(0.04 * M))
    valid_mech_idx = []
    for jm in range(F_mech):
        col = X_mech_tr[:, jm]
        fin = np.isfinite(col)
        if int(fin.sum()) < min_valid_n:
            continue
        cv = col[fin]
        n_nm = int(np.sum(np.abs(cv - float(np.median(cv))) > 1e-6))
        if n_nm >= min_supp:
            valid_mech_idx.append(jm)
    # Keep strategy dummies (strat_*) even if slightly smaller? Actually keep all passing >= min_supp!
    X_mech_filt = X_mech_tr[:, valid_mech_idx]
    mech_filt_names = [mech_names[jm] for jm in valid_mech_idx]

    # Combine static mechanism features + surviving causal dynamic interactions
    X_comb = np.hstack([X_mech_filt, X_dyn_tr]) if X_dyn_tr.shape[1] > 0 else X_mech_filt
    comb_names = mech_filt_names + [d["name"] for d in dyn_pairs_meta]

    card = wfc.fit_causal_scorecard(
        X_comb,
        y_ret,
        y_win,
        day_ids,
        feature_names=comb_names,
        mode=mode,
        top_k=top_k,
        min_k=min_k,
        max_corr=max_corr,
        min_t_stat=min_t_stat,
        shrink_tau=shrink_tau,
        max_delta=max_delta,
        orig_score_train=orig_score_train,
        max_corr_orig=max_corr_orig,
    )
    # Map col_idx back to original indices in (X_mech_tr + X_dyn_tr) for score_with_interaction_card!
    for f in card.get("factors", []):
        ci = f["col_idx"]
        if ci < len(valid_mech_idx):
            f["col_idx"] = valid_mech_idx[ci]
        else:
            f["col_idx"] = F_mech + (ci - len(valid_mech_idx))
    card["n_mech_feats"] = int(F_mech)
    card["n_dyn_surviving"] = int(len(dyn_pairs_meta))
    card["dyn_pairs_meta"] = dyn_pairs_meta
    return card


def score_with_interaction_card(
    X_mech_rows: np.ndarray,
    X_base_rows: np.ndarray,
    card: dict,
) -> np.ndarray:
    """Evaluate frozen causal card (including dynamic Top-20x19/2 pair specs) on new rows."""
    import _wf_core as wfc

    n = X_mech_rows.shape[0]
    dyn_meta = card.get("dyn_pairs_meta", [])
    if dyn_meta:
        dyn_cols = []
        for d in dyn_meta:
            xa = np.where(np.isfinite(X_base_rows[:, d["j_a"]]), X_base_rows[:, d["j_a"]], d["med_a"])
            xb = np.where(np.isfinite(X_base_rows[:, d["j_b"]]), X_base_rows[:, d["j_b"]], d["med_b"])
            ha = xa > d["thr_a"]
            hb = xb > d["thr_b"]
            tag = d["tag"]
            if tag == "HiHi":
                vec = (ha & hb).astype(np.float64)
            elif tag == "HiLo":
                vec = (ha & (~hb)).astype(np.float64)
            elif tag == "LoHi":
                vec = ((~ha) & hb).astype(np.float64)
            elif tag == "LoLo":
                vec = ((~ha) & (~hb)).astype(np.float64)
            else:
                za = np.clip((xa - d["med_a"]) / d["iqr_a"], -3.0, 3.0) * d["sgn_a"]
                zb = np.clip((xb - d["med_b"]) / d["iqr_b"], -3.0, 3.0) * d["sgn_b"]
                vec = za * zb
            dyn_cols.append(vec)
        X_comb = np.hstack([X_mech_rows, np.column_stack(dyn_cols)])
    else:
        X_comb = X_mech_rows
    return wfc.score_candidates_with_card(X_comb, card)


def run_expanding_interaction_loop(
    df: pd.DataFrame,
    mech_cols: list[str],
    base_cols: list[str],
    mode: str = "scorecard_0_100",
    wf_start_date: str = "2023-01-03",
    min_warmup_trades: int = 80,
    min_warmup_trades_rare: int = 60,
    min_warmup_months: int = 18,
    recalc_freq: str = "daily",
    top_k: int = 12,
    min_k: int = 5,
    max_corr: float = 0.65,
    min_t_stat: float = 1.2,
    min_t_stat_dyn: float = 2.6,
    min_synergy_t: float = 1.6,
    shrink_tau: float = 20.0,
    max_delta: int = 15,
    orig_score_col: Optional[str] = None,
    max_corr_orig: Optional[float] = 0.70,
    top_base_k: int = 20,
    max_dyn_keep: int = 25,
) -> tuple[pd.DataFrame, dict]:
    """
    Day-by-day expanding WF loop combining static mechanism interactions and
    causal exit_date < t Top-20x19/2 pairwise discovery. 100% truncation-invariant.
    """
    import _wf_core as wfc

    n = len(df)
    if n == 0:
        out = df.copy()
        out["wf_in_window"] = False
        out["wf_score"] = np.nan
        return out, {"wf_actual_start": None, "snapshots": []}

    buy_dts = df["buy_date"].astype(str).str[:10].to_numpy()
    exit_dts = df["exit_date"].astype(str).str[:10].to_numpy()
    codes = df["code"].astype(str).str.zfill(6).to_numpy()
    y_ret = df["net_ret"].to_numpy(dtype=np.float64)
    y_win = (y_ret > 0.0).astype(np.float64)

    can_buy = np.ones(n, dtype=bool)
    if "is_yizi" in df.columns:
        can_buy &= (~df["is_yizi"].fillna(False).to_numpy(bool))
    if "can_buy" in df.columns:
        can_buy &= df["can_buy"].fillna(True).to_numpy(bool)
    if "sim_ok" in df.columns:
        can_buy &= df["sim_ok"].fillna(True).to_numpy(bool)
    can_buy &= np.isfinite(y_ret)

    X_mech = df[mech_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    X_base = df[base_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64) if base_cols else np.empty((n, 0), dtype=np.float64)
    orig_arr = pd.to_numeric(df[orig_score_col], errors="coerce").to_numpy(dtype=np.float64) if (orig_score_col and orig_score_col in df.columns) else None

    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_to_id = {d: i for i, d in enumerate(uniq_dts)}
    day_ids_all = np.array([dt_to_id[d] for d in buy_dts], dtype=np.int32)

    buyable_idx = np.where(can_buy)[0]
    exit_order = sorted(buyable_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i]))
    exit_order_arr = np.asarray(exit_order, dtype=np.int64)
    exit_dts_sorted = exit_dts[exit_order_arr]

    X_m_exit = X_mech[exit_order_arr]
    X_b_exit = X_base[exit_order_arr]
    r_exit = y_ret[exit_order_arr]
    w_exit = y_win[exit_order_arr]
    d_exit = day_ids_all[exit_order_arr]
    orig_exit = orig_arr[exit_order_arr] if orig_arr is not None else None

    first_buy_dt = buy_dts[buyable_idx].min()
    rare_fallback_dt = wfc._add_months(str(first_buy_dt), min_warmup_months)

    by_dt_rows = {}
    for i in buyable_idx:
        by_dt_rows.setdefault(buy_dts[i], []).append(i)
    sorted_trade_dts = sorted(by_dt_rows.keys())

    wf_in_win = np.zeros(n, dtype=bool)
    wf_score = np.full(n, np.nan, dtype=np.float64)
    wf_delta = np.zeros(n, dtype=np.float64)
    thr_t30 = np.full(n, np.nan, dtype=np.float64)
    thr_t20 = np.full(n, np.nan, dtype=np.float64)
    thr_t10 = np.full(n, np.nan, dtype=np.float64)
    thr_t5 = np.full(n, np.nan, dtype=np.float64)

    ptr = 0
    n_exit_tot = len(exit_order_arr)
    started = False
    wf_actual_start = None
    current_card = None
    last_ptr = -1
    last_month = ""
    last_snap_month = ""
    snapshots = []
    n_rebuilds = 0

    for t in sorted_trade_dts:
        while ptr < n_exit_tot and exit_dts_sorted[ptr] < t:
            ptr += 1
        if t < wf_start_date:
            continue
        if not started:
            if (ptr >= min_warmup_trades) or (t >= rare_fallback_dt and ptr >= min_warmup_trades_rare):
                started = True
                wf_actual_start = t
            else:
                continue

        need_rebuild = (
            current_card is None
            or (recalc_freq == "daily" and ptr > last_ptr)
            or (recalc_freq == "monthly" and t[:7] != last_month)
        )
        if need_rebuild:
            current_card = fit_causal_interaction_scorecard(
                X_m_exit[:ptr],
                X_b_exit[:ptr],
                r_exit[:ptr],
                w_exit[:ptr],
                d_exit[:ptr],
                mech_names=mech_cols,
                base_names=base_cols,
                mode=mode,
                top_k=top_k,
                min_k=min_k,
                max_corr=max_corr,
                min_t_stat=min_t_stat,
                min_t_stat_dyn=min_t_stat_dyn,
                min_synergy_t=min_synergy_t,
                shrink_tau=shrink_tau,
                max_delta=max_delta,
                orig_score_train=(orig_exit[:ptr] if orig_exit is not None else None),
                max_corr_orig=max_corr_orig,
                top_base_k=top_base_k,
                max_dyn_keep=max_dyn_keep,
            )
            last_ptr = ptr
            last_month = t[:7]
            n_rebuilds += 1
            if t[:7] != last_snap_month:
                snap = {k: v for k, v in current_card.items() if k != "dyn_pairs_meta"}
                snapshots.append({"as_of_date": t, **snap})
                last_snap_month = t[:7]

        rows_t = np.asarray(by_dt_rows[t], dtype=np.int64)
        sc_t = score_with_interaction_card(X_mech[rows_t], X_base[rows_t], current_card)
        wf_in_win[rows_t] = True
        if mode == "scorecard_0_100":
            wf_score[rows_t] = sc_t.astype(np.float64)
            thr_t30[rows_t] = current_card.get("train_score_q70_top30", 55)
            thr_t20[rows_t] = current_card.get("train_score_q80_top20", 60)
            thr_t10[rows_t] = current_card.get("train_score_q90_top10", 68)
            thr_t5[rows_t] = current_card.get("train_score_q95_top5", 73)
        else:
            wf_delta[rows_t] = sc_t.astype(np.float64)
            if orig_arr is not None:
                wf_score[rows_t] = orig_arr[rows_t] + sc_t.astype(np.float64)

    out = df.copy()
    out["can_buy_hygiene"] = can_buy
    out["wf_in_window"] = wf_in_win
    if mode == "scorecard_0_100":
        out["wf_score"] = wf_score
        out["wf_thr_top30"] = thr_t30
        out["wf_thr_top20"] = thr_t20
        out["wf_thr_top10"] = thr_t10
        out["wf_thr_top5"] = thr_t5
    else:
        out["wf_delta_score"] = wf_delta
        if orig_arr is not None:
            out["wf_new_score"] = np.where(wf_in_win, orig_arr + wf_delta, orig_arr)

    latest_snap = {k: v for k, v in current_card.items() if k != "dyn_pairs_meta"} if current_card else None
    meta = {
        "mode": mode,
        "recalc_freq": recalc_freq,
        "wf_start_date_req": wf_start_date,
        "wf_actual_start": wf_actual_start,
        "n_rebuilds": n_rebuilds,
        "n_buyable_total": int(len(buyable_idx)),
        "n_wf_candidates": int(wf_in_win.sum()),
        "latest_scorecard": latest_snap,
        "snapshots": snapshots,
    }
    return out, meta
