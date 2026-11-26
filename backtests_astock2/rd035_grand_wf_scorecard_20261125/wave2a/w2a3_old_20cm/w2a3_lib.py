#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Shared causal library for RD035 Wave 2A-3 (20cm deep-open V1.1 overhaul)."""
import gc
import json
import math
import os
import sys
from typing import Optional

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

pa.set_cpu_count(2)
pa.set_io_thread_count(2)

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
OUT_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a3_old_20cm"

for p in (WAVE1_BASE, RD028_DIR, PARTC_V20):
    if p not in sys.path:
        sys.path.insert(0, p)

import _wf_core as wfc
import _wf_sim_and_metrics as wfm
import wf_scorecard_engine as wf
import step4_mod_rules_and_sim as m1
import tier_priority_engine as tpe

F9_COLS = [
    "s20cm_F01_open_gap", "s20cm_F02_rfm_le20", "s20cm_F03_dist3d30_ge10",
    "s20cm_F04_zt60d_ge2", "s20cm_F05_seal_ratio_ge10_pen", "s20cm_F06_inst_net_pos",
    "s20cm_F07_mkt10_zt_gt55", "s20cm_F08_yizi20_siphon_pen", "s20cm_F09_monday_pen",
]


def load_w2a3_data(end_cutoff: Optional[str] = None) -> tuple[pd.DataFrame, dict]:
    """Load 20cm pool, attach strictly PIT 09:25 same-theme 10cm/20cm auction features."""
    p20 = pd.read_parquet(f"{WAVE1_BASE}/pool_20cm_master_pit.parquet")
    p20["buy_date"] = p20["buy_date"].astype(str).str[:10]
    p20["exit_date"] = p20["exit_date"].astype(str).str[:10]
    p20["sig_date"] = p20["sig_date"].astype(str).str[:10]
    p20["code"] = p20["code"].astype(str).str.zfill(6)
    if end_cutoff is not None:
        p20 = p20[p20["buy_date"] <= end_cutoff].copy().reset_index(drop=True)

    with open(f"{WAVE1_BASE}/wave1a_factor_catalog_and_pit_audit.json", encoding="utf-8") as f:
        cat = json.load(f)
    mc = cat["master_factor_catalog"]

    # Attach 09:25 same-theme 10cm/20cm auction features strictly <= max buy_date
    buy_dts = sorted(p20["buy_date"].unique().tolist())
    sig_set = set(p20["sig_date"].unique().tolist())
    cols_sd = [
        "dt", "c6", "open_pct", "is_20cm", "is_st_pit",
        "prev_streak", "csrc_ind_id", "amount_yi_t1",
    ]
    sd = ds.dataset(f"{WAVE1_BASE}/stock_day_core_features_pit.parquet").scanner(
        columns=cols_sd,
        filter=(ds.field("dt").isin(buy_dts)) & (ds.field("prev_streak") >= 1) & (ds.field("is_st_pit") == 0),
    ).to_table().to_pandas()
    sd["dt"] = sd["dt"].astype(str)
    sd["c6"] = sd["c6"].astype(str).str.zfill(6)

    kpl_by_dt_plate = {}
    kpl_by_dt_code = {}
    with open(f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            kdt = str(obj["date"])[:10]
            if kdt not in sig_set:
                continue
            for pl in obj.get("plates", []):
                pname = str(pl.get("plate", ""))
                stks = [str(s[0])[-6:].zfill(6) for s in pl.get("stocks", []) if s]
                if stks and pname:
                    kpl_by_dt_plate[(kdt, pname)] = stks
                    for c in stks:
                        kpl_by_dt_code.setdefault((kdt, c), []).append(pname)

    sd_by_dt = {}
    for dt_v, grp in sd[sd["is_st_pit"] == 0].groupby("dt", sort=False):
        m10, m20, by_ind10 = {}, {}, {}
        all_lb10 = []
        for r in grp.itertuples(index=False):
            tup = (float(r.open_pct), int(r.prev_streak), float(r.amount_yi_t1 or 0.0), int(r.csrc_ind_id))
            if r.is_20cm == 0:
                m10[r.c6] = tup
                if r.prev_streak >= 1:
                    by_ind10.setdefault(int(r.csrc_ind_id), []).append(tup)
                if r.prev_streak >= 2:
                    all_lb10.append(tup)
            else:
                if r.prev_streak >= 1:
                    m20[r.c6] = tup
        sd_by_dt[dt_v] = (m10, m20, by_ind10, all_lb10)

    auc_rows = []
    for r in p20.itertuples(index=False):
        bd, sdt, ck = r.buy_date, r.sig_date, r.code
        ind_id = int(r.sd_csrc_ind_id) if pd.notna(r.sd_csrc_ind_id) else -1
        m10, m20, by_ind10, all_lb10 = sd_by_dt.get(bd, ({}, {}, {}, []))
        plates = kpl_by_dt_code.get((sdt, ck), [])
        if not plates and getattr(r, "L2_kpl_plate_t1", ""):
            plates = [str(r.L2_kpl_plate_t1)]

        peers10, peers20 = {}, {}
        for pl in plates:
            for pc in kpl_by_dt_plate.get((sdt, pl), []):
                if pc in m10 and m10[pc][1] >= 1:
                    peers10[pc] = m10[pc]
                if pc != ck and pc in m20:
                    peers20[pc] = m20[pc]
        p10_list = list(peers10.values())
        if not p10_list and ind_id in by_ind10:
            p10_list = by_ind10[ind_id]

        if p10_list:
            max_stk = max(x[1] for x in p10_list)
            ldrs = [x for x in p10_list if x[1] == max_stk]
            ldr_op = float(np.mean([x[0] for x in ldrs]))
            lb_list = [x for x in p10_list if x[1] >= 2]
            lb_ldr_op = float(np.mean([x[0] for x in lb_list if x[1] == max(y[1] for y in lb_list)])) if lb_list else np.nan
            p10_mean = float(np.mean([x[0] for x in p10_list]))
            n10 = len(p10_list)
            nuke_r = sum(1 for x in p10_list if x[0] <= -5.0) / n10
            strong_r = sum(1 for x in p10_list if x[0] >= 5.0) / n10
            has_yizi10 = float(any(x[0] >= 9.5 for x in p10_list))
        else:
            max_stk, ldr_op, lb_ldr_op, p10_mean = 0.0, np.nan, np.nan, np.nan
            n10, nuke_r, strong_r, has_yizi10 = 0, np.nan, np.nan, 0.0

        p20_list = list(peers20.values())
        has_yizi20_thm = float(any(x[0] >= 19.5 for x in p20_list)) if p20_list else 0.0
        p20_mean = float(np.mean([x[0] for x in p20_list])) if p20_list else np.nan

        if all_lb10:
            m_stk = max(x[1] for x in all_lb10)
            m_ldrs = [x[0] for x in all_lb10 if x[1] == m_stk]
            mkt_ldr_op = float(np.mean(m_ldrs))
            mkt_nuke_r = sum(1 for x in all_lb10 if x[0] <= -5.0) / len(all_lb10)
        else:
            mkt_ldr_op, mkt_nuke_r = np.nan, np.nan

        own_op_pct = float(r.open_pct) * 100.0
        auc_rows.append({
            "auc_thm10_n_peers": float(n10),
            "auc_thm10_max_streak": float(max_stk),
            "auc_thm10_ldr_open_pct": ldr_op,
            "auc_thm10_lb_ldr_open_pct": lb_ldr_op,
            "auc_thm10_peer_mean_open": p10_mean,
            "auc_thm10_nuke_ratio": nuke_r,
            "auc_thm10_strong_ratio": strong_r,
            "auc_thm10_has_yizi_open": has_yizi10,
            "auc_thm20_has_yizi_open": has_yizi20_thm,
            "auc_thm20_peer_mean_open": p20_mean,
            "auc_mkt10_ldr_open_pct": mkt_ldr_op,
            "auc_mkt10_lb_nuke_ratio": mkt_nuke_r,
            "auc_rel_gap_vs_thm10": (own_op_pct - ldr_op) if np.isfinite(ldr_op) else np.nan,
            "auc_rel_gap_vs_mkt": own_op_pct - float(r.mkt_0925_avg_gap_pct),
        })

    auc_df = pd.DataFrame(auc_rows)
    for c in auc_df.columns:
        p20[c] = auc_df[c].astype(np.float32).values

    # Clean derived aliases strictly PIT
    p20["mkt10_zt_est_t1"] = (p20["L1_zt_cnt_t1"] - p20["mkt20_zt_cnt_t1"]).astype(np.float32)
    p20["xtr_fix_monday"] = (p20["L1_weekday"] == 1).astype(np.float32)
    p20["xtr_fix_lock50_evo"] = (p20["evo_lock_top10"] >= 50.0).astype(np.float32)
    p20["xtr_fix_mkt_seal80"] = ((100.0 - p20["L1_zb_rate_t1"]) >= 80.0).astype(np.float32)

    entry_num = [
        c for c, info in mc.items()
        if info["role"] == "entry_feature" and pd.api.types.is_numeric_dtype(p20[c])
        and p20[c].isna().mean() <= 0.55 and p20[c].nunique(dropna=True) >= 2
    ]
    xtr_cols = [c for c, info in mc.items() if info["role"] == "cross_transplant_factor"]
    xtr_active = [c for c in xtr_cols if p20[c].nunique(dropna=True) >= 2]
    auc_cols = list(auc_df.columns)
    fix_xtr_cols = ["xtr_fix_monday", "xtr_fix_lock50_evo", "xtr_fix_mkt_seal80"]

    meta = {
        "f9_cols": F9_COLS,
        "xtr_all": xtr_cols,
        "xtr_active": xtr_active,
        "xtr_fixed": xtr_active + fix_xtr_cols,
        "entry_num": entry_num,
        "auc_cols": auc_cols,
    }
    return p20, meta


def load_v20_comb_context() -> dict:
    """Load V20.0 6-strategy context once for true pure single-slot combined increment."""
    codes = set()
    for st in m1.STRAT_ORDER:
        d = pd.read_parquet(f"{RD028_DIR}/pool_{st}_oldhot.parquet")
        codes.update(d["code"].astype(str).str.zfill(6))
    tks_need = sorted([f"{c}.SH" for c in codes] + [f"{c}.SZ" for c in codes])
    raw_idx = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300 = {k: float(v) for k, v in raw_idx["sh000300"].items()}
    all_sh_dts = sorted(sh300.keys())
    cal_full = [d for d in all_sh_dts if "2021-01-04" <= d <= "2026-11-25"]
    cal_5y = [d for d in all_sh_dts if "2021-11-16" <= d <= "2026-11-16"]
    cols_b = ["date", "ticker", "open", "close", "adj_close", "qfq_factor"]
    flt_b = (ds.field("date") >= pd.Timestamp("2020-12-01")) & ds.field("ticker").isin(tks_need)
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols_b, filter=flt_b).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols_b, filter=flt_b).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    dp = pd.concat([da, dd], ignore_index=True)
    del da, dd
    dp["c6"] = dp["ticker"].astype(str).str[:6]
    dp["dt"] = dp["date"].dt.strftime("%Y-%m-%d")
    dp = dp.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    dp["adjf"] = np.where((dp["close"] > 0) & (dp["adj_close"] > 0), dp["adj_close"] / dp["close"], 1.0)
    bar_lu = {
        (r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf))
        for r in dp.itertuples(index=False)
    }
    del dp
    gc.collect()
    pa.default_memory_pool().release_unused()
    pools = m1.load_pools_oldhot(cal_full, cal_5y, bar_lu)
    del bar_lu
    gc.collect()
    pa.default_memory_pool().release_unused()
    untrig = m1.load_untrig_with_oldhot()
    wf_ctx = wf.load_v20_reference_context(WAVE1_BASE)

    # Precompute non-20cm V20 slot parts (identical across all 20cm variants)
    other_parts = []
    trig_dts_other = {}
    for st in ("3to4", "high", "pry", "2to3", "1to2"):
        _, slot_df = m1.sim_standalone(st, pools[st], np.zeros(len(pools[st])), high_cb_mode="v51_exact")
        chosen = slot_df[slot_df["buy_date"].between("2021-11-16", "2026-11-16")].copy()
        chosen["score"] = [round(float(x), 1) for x in chosen["v20_score"]] if st == "1to2" else chosen["v20_score"]
        chosen["tier"] = [tpe.assign_physical_tier(st, sc) for sc in chosen["score"]]
        chosen["is_untrig"] = False
        trig_dts_other[st] = set(chosen["buy_date"])
        cols = [
            "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
            "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px",
            "is_untrig", "mtm_full", "mtm_5y",
        ]
        other_parts.append(chosen[cols])

    ut = untrig[untrig["buy_date"].between("2021-11-16", "2026-11-16")].copy()
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

    # Map (buy_date, code) -> 20cm mtm_5y and buy_price_val from pools["20cm"]
    p20_old = pools["20cm"]
    p20_map = {}
    for r in p20_old.itertuples(index=False):
        p20_map[(r.buy_date, r.code)] = (r.mtm_5y, float(r.buy_price_val), int(r.exit_hhmm), float(r.net_ret))

    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    ctx = {
        "wf_ctx": wf_ctx,
        "cal_5y": cal_5y,
        "idx_5y": idx_5y,
        "sh300": sh300,
        "all_sh_dts": all_sh_dts,
        "other_pool5": pd.concat(other_parts, ignore_index=True),
        "ut_final": ut_final,
        "p20_old": p20_old,
        "p20_map": p20_map,
    }
    return ctx


def get_official_v20_comb_metrics(v20_comb_ctx: dict, wf_start_dt: str = "2023-01-03", end_dt: str = "2026-11-16") -> dict:
    """Compute official V20.0 baseline combined metrics directly from v20_baseline_ledger_278."""
    v20_led = v20_comb_ctx["wf_ctx"]["v20_ledger"].copy()
    cal_5y = v20_comb_ctx["cal_5y"]
    idx_5y = v20_comb_ctx["idx_5y"]
    p20_map = v20_comb_ctx["p20_map"]
    # Build exact daily MTM via mtm_pairs
    T = len(cal_5y)
    day_mult = np.ones(T, dtype=float)
    for r in v20_led.itertuples(index=False):
        for d_str, mult in r.mtm_pairs:
            ti = idx_5y.get(d_str)
            if ti is not None:
                day_mult[ti] *= float(mult)
    dr_5y = day_mult - 1.0
    out = {}
    for wname, sdt, edt in [
        ("FULL_5Y", "2021-11-16", end_dt),
        ("FULL_WF", wf_start_dt, end_dt),
        ("Y2025_2026", "2025-01-01", end_dt),
        ("Y2026", "2026-01-01", end_dt),
        ("Y2026H2", "2026-07-01", end_dt),
    ]:
        m = tpe.calc_window_metrics(v20_led, dr_5y, cal_5y, idx_5y, v20_comb_ctx["sh300"], v20_comb_ctx["all_sh_dts"], sdt, edt)
        m["n_20cm"] = int(((v20_led["strategy"] == "20cm") & v20_led["buy_date"].between(sdt, edt)).sum())
        out[wname] = m
    return out


def eval_v20_combined_replacement(
    v20_comb_ctx: dict,
    new_20cm_slot_wf: pd.DataFrame,
    wf_start_dt: str = "2023-01-03",
    end_dt: str = "2026-11-16",
) -> dict:
    """Replace 20cm leg (>= wf_start_dt) in V20.0 combined single-slot engine and report WF + 2526 + 26H2."""
    p20_old = v20_comb_ctx["p20_old"]
    p20_map = v20_comb_ctx["p20_map"]
    cal_5y = v20_comb_ctx["cal_5y"]
    idx_5y = v20_comb_ctx["idx_5y"]

    # Pre-WF 20cm matches exact V20.0 baseline (< wf_start_dt, using cm20_thr=76 pre-slot + S82 filter)
    _, base_s76 = m1.sim_standalone("20cm", p20_old, np.zeros(len(p20_old)), cm20_thr=76.0)
    pre_20 = base_s76[base_s76["buy_date"].between("2021-11-16", wf_start_dt) & (base_s76["buy_date"] < wf_start_dt) & (base_s76["v20_score"] >= 82.0)].copy()
    pre_20["score"] = pre_20["v20_score"]
    pre_20["tier"] = "20cm_S(>=82)"
    pre_20["is_untrig"] = False

    # WF 20cm from new_20cm_slot_wf
    nw = new_20cm_slot_wf[new_20cm_slot_wf["buy_date"].between(wf_start_dt, end_dt)].copy()
    nw["strategy"] = "20cm"
    nw["tier"] = "20cm_S(>=82)"  # Eligible slot in V20 at priority 6
    nw["is_untrig"] = False
    if "score" not in nw.columns:
        nw["score"] = 85.0
    mtm_5y_list, bpx_list, ehh_list, nr_list = [], [], [], []
    for r in nw.itertuples(index=False):
        tup = p20_map.get((r.buy_date, r.code))
        if tup is not None:
            mtm_5y_list.append(tup[0])
            bpx_list.append(tup[1])
            ehh_list.append(tup[2])
            nr_list.append(tup[3])
        else:
            mtm_5y_list.append(())
            bpx_list.append(float(getattr(r, "buy_price", 1.0)))
            ehh_list.append(1500)
            nr_list.append(float(r.net_ret))
    nw["mtm_5y"] = mtm_5y_list
    nw["buy_price_val"] = bpx_list
    nw["exit_hhmm"] = ehh_list
    nw["net_ret"] = nr_list
    nw["is_adj_px"] = True
    nw["buy_hhmm"] = 925

    cols = [
        "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
        "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig", "mtm_5y",
    ]
    c20 = pd.concat([pre_20[cols], nw[cols]], ignore_index=True)
    p6 = pd.concat([v20_comb_ctx["other_pool5"][cols], c20], ignore_index=True)

    mtm_map = {(r.strategy, r.buy_date, r.code): r.mtm_5y for r in p6.itertuples(index=False)}
    tr_df, _ = tpe.run_single_slot(
        p6.drop(columns=["mtm_5y"]),
        lambda d: d["tier"].map(m1.S2C_MAP).fillna(999).to_numpy(),
        untrig_df=v20_comb_ctx["ut_final"],
        timing_mode="s_tier_reserve_only",
    )
    tr_df["mtm_5y"] = [mtm_map[(r.strategy, r.buy_date, r.code)] for r in tr_df.itertuples(index=False)]
    dr_5y, mtm_diff = m1.daily_mtm_from_segs(tr_df, len(cal_5y), "mtm_5y")
    tot_nav = float(np.prod(1.0 + tr_df["net_ret"].to_numpy(float))) if not tr_df.empty else 1.0
    assert (mtm_diff / max(1.0, tot_nav)) < 1e-6, f"Combined MTM diff={mtm_diff} / {tot_nav}"

    out = {}
    for wname, sdt, edt in [
        ("FULL_5Y", "2021-11-16", end_dt),
        ("FULL_WF", wf_start_dt, end_dt),
        ("Y2025_2026", "2025-01-01", end_dt),
        ("Y2026", "2026-01-01", end_dt),
        ("Y2026H2", "2026-07-01", end_dt),
    ]:
        m = tpe.calc_window_metrics(tr_df, dr_5y, cal_5y, idx_5y, v20_comb_ctx["sh300"], v20_comb_ctx["all_sh_dts"], sdt, edt)
        sub_20 = tr_df[(tr_df["strategy"] == "20cm") & tr_df["buy_date"].between(sdt, edt)]
        m["n_20cm"] = int(len(sub_20))
        out[wname] = m
    return out


def calc_26h2_metrics(slot_df: pd.DataFrame, bench_df: pd.DataFrame, end_dt: str = "2026-11-16") -> dict:
    b = bench_df[bench_df["trade_date"].between("2026-07-01", end_dt)].sort_values("trade_date")
    cal_dts = b["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    dr, _ = wfm.build_daily_mtm_returns(slot_df[slot_df["buy_date"] >= "2026-07-01"], cal_dts)
    return wfm._calc_one_window(
        slot_df, None, dr, cal_dts, dt_idx,
        b["csi300_daily_ret"].to_numpy(float), b["alla_ew_daily_ret"].to_numpy(float),
        "2026-07-01", end_dt,
    )


def summarize_variant(
    name: str,
    group: str,
    slot_df: pd.DataFrame,
    pass_df: pd.DataFrame,
    wf_cand_df: pd.DataFrame,
    wf_ctx: dict,
    v20_comb_ctx: Optional[dict] = None,
    v20_base_comb: Optional[dict] = None,
    wf_start_dt: str = "2023-01-03",
    end_dt: str = "2026-11-16",
    perm_n: int = 200,
) -> tuple[dict, dict]:
    """Unified evaluation across FULL_WF, 2526, 2026, 26H2, big-loss rate, perm, and V20 comb."""
    ev = wf.evaluate_wf_ledger(
        slot_df, pass_df, wf_cand_df, wf_ctx["bench"],
        wf_start_dt=wf_start_dt, end_dt=end_dt, perm_n=perm_n, seed=20261125,
    )
    h2 = calc_26h2_metrics(slot_df, wf_ctx["bench"], end_dt=end_dt)
    ev["windows"]["Y2026H2"] = h2

    rets = slot_df["net_ret"].to_numpy(float) if not slot_df.empty else np.array([])
    bl_cnt = int(np.sum(rets <= -0.07)) if len(rets) else 0
    bl_pct = round(bl_cnt / max(1, len(rets)) * 100.0, 2)

    comb = eval_v20_combined_replacement(v20_comb_ctx, slot_df, wf_start_dt=wf_start_dt, end_dt=end_dt) if v20_comb_ctx else None

    fw = ev["windows"]["FULL_WF"]
    y23 = ev["windows"].get("Y2023", {})
    y24 = ev["windows"].get("Y2024", {})
    y25 = ev["windows"].get("Y2025", {})
    y2526 = ev["windows"].get("Y2025_2026", {})
    y26 = ev["windows"].get("Y2026", {})
    pm = ev["permutation_1000"]

    row = {
        "variant": name,
        "group": group,
        "n_pass": int(len(pass_df)),
        "n_wf": fw.get("n", 0),
        "wr_wf": fw.get("wr_pct", 0.0),
        "mean_wf": fw.get("mean_pct", 0.0),
        "plr_wf": fw.get("plr", 0.0),
        "nav_wf": fw.get("nav", 1.0),
        "ex3_wf": fw.get("ex_top3_nav", 1.0),
        "ex5_wf": fw.get("ex_top5_nav", 1.0),
        "mdd_wf": fw.get("daily_mdd_pct", 0.0),
        "sharpe_wf": fw.get("daily_sharpe", 0.0),
        "excess_csi_wf": fw.get("excess_csi300_pp", 0.0),
        "excess_ew_wf": fw.get("excess_alla_ew_pp", 0.0),
        "big_loss_m7_cnt": bl_cnt,
        "big_loss_m7_pct": bl_pct,
        "nav_23": y23.get("nav", 1.0),
        "nav_24": y24.get("nav", 1.0),
        "nav_25": y25.get("nav", 1.0),
        "n_2526": y2526.get("n", 0),
        "wr_2526": y2526.get("wr_pct", 0.0),
        "nav_2526": y2526.get("nav", 1.0),
        "ex5_2526": y2526.get("ex_top5_nav", 1.0),
        "mdd_2526": y2526.get("daily_mdd_pct", 0.0),
        "n_26": y26.get("n", 0),
        "wr_26": y26.get("wr_pct", 0.0),
        "nav_26": y26.get("nav", 1.0),
        "n_26h2": h2.get("n", 0),
        "wr_26h2": h2.get("wr_pct", 0.0),
        "mean_26h2": h2.get("mean_pct", 0.0),
        "plr_26h2": h2.get("plr", 0.0),
        "nav_26h2": h2.get("nav", 1.0),
        "mdd_26h2": h2.get("daily_mdd_pct", 0.0),
        "perm_sd_p": pm.get("same_day_p_nav", 1.0),
        "perm_any_p": pm.get("any_cand_day_p_nav", 1.0),
    }
    if comb is not None:
        cw, c2526, ch2 = comb["FULL_WF"], comb["Y2025_2026"], comb["Y2026H2"]
        row["comb_wf_nav"] = cw["nav"]
        row["comb_wf_mdd"] = cw["daily_mdd_pct"]
        row["comb_wf_sharpe"] = cw["daily_sharpe"]
        row["comb_wf_n20"] = cw["n_20cm"]
        row["comb_2526_nav"] = c2526["nav"]
        row["comb_26h2_nav"] = ch2["nav"]
        if v20_base_comb is not None:
            bw = v20_base_comb["FULL_WF"]
            b2526 = v20_base_comb["Y2025_2026"]
            bh2 = v20_base_comb["Y2026H2"]
            row["comb_wf_nav_ratio"] = round(cw["nav"] / max(1e-9, bw["nav"]), 4)
            row["comb_wf_mdd_diff"] = round(cw["daily_mdd_pct"] - bw["daily_mdd_pct"], 2)
            row["comb_2526_nav_ratio"] = round(c2526["nav"] / max(1e-9, b2526["nav"]), 4)
            row["comb_26h2_nav_ratio"] = round(ch2["nav"] / max(1e-9, bh2["nav"]), 4)
    return row, {"eval": ev, "comb": comb}


def run_causal_scorecard_ext(
    df: pd.DataFrame,
    feature_cols: list[str],
    mode: str = "scorecard_0_100",
    wf_start_date: str = "2023-01-03",
    min_warmup_trades: int = 80,
    top_k: int = 12,
    min_k: int = 5,
    max_corr: float = 0.65,
    min_t_stat: float = 1.0,
    shrink_tau: float = 20.0,
    max_delta: int = 15,
    orig_score_col: Optional[str] = None,
    max_corr_orig: Optional[float] = 0.70,
    target_mode: str = "alpha",
    train_filter_mask: Optional[np.ndarray] = None,
    min_discrete_bin_cnt: int = 0,
) -> tuple[pd.DataFrame, dict]:
    """
    Strictly causal (exit_date < t) expanding WF loop supporting:
      - target_mode='alpha': standard net_ret & win utility, also outputs causal q85 (top15) & Mode B quantiles.
      - target_mode='mine_m7': predicts binary crash (net_ret <= -0.07) -> outputs 0..100 risk score & q75/q80/q85!
    100% truncation-invariant at 2024-12-31.
    """
    df_h = wfm.prepare_hygiene_and_net_ret(df, fee_rt=0.0030)
    n = len(df_h)
    buy_dts = df_h["buy_date"].astype(str).str[:10].to_numpy()
    exit_dts = df_h["exit_date"].astype(str).str[:10].to_numpy()
    codes = df_h["code"].astype(str).str.zfill(6).to_numpy()
    net_ret = df_h["net_ret"].to_numpy(dtype=np.float64)
    can_buy = df_h["can_buy_hygiene"].to_numpy(bool)
    if train_filter_mask is not None:
        can_train = can_buy & np.asarray(train_filter_mask, dtype=bool)
    else:
        can_train = can_buy

    if target_mode == "mine_m7":
        y_ret = (net_ret <= -0.07).astype(np.float64)
        y_win = y_ret.copy()
    else:
        y_ret = net_ret
        y_win = (net_ret > 0.0).astype(np.float64)

    X_all = df_h[feature_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    orig_arr = pd.to_numeric(df_h[orig_score_col], errors="coerce").to_numpy(dtype=np.float64) if orig_score_col else None

    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_to_id = {d: i for i, d in enumerate(uniq_dts)}
    day_ids = np.array([dt_to_id[d] for d in buy_dts], dtype=np.int32)

    train_idx = np.where(can_train)[0]
    exit_order = sorted(train_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i]))
    exit_order_arr = np.asarray(exit_order, dtype=np.int64)
    exit_dts_sorted = exit_dts[exit_order_arr]

    buyable_idx = np.where(can_buy)[0]
    by_dt_rows = {}
    for i in buyable_idx:
        by_dt_rows.setdefault(buy_dts[i], []).append(i)

    wf_in_win = np.zeros(n, dtype=bool)
    wf_score = np.full(n, np.nan, dtype=np.float64)
    wf_delta = np.zeros(n, dtype=np.float64)
    thr_q70 = np.full(n, np.nan)
    thr_q75 = np.full(n, np.nan)
    thr_q80 = np.full(n, np.nan)
    thr_q85 = np.full(n, np.nan)
    thr_q90 = np.full(n, np.nan)

    ptr, last_ptr = 0, -1
    n_ex = len(exit_order_arr)
    started, wf_actual_start, card = False, None, None
    for t in sorted(by_dt_rows.keys()):
        while ptr < n_ex and exit_dts_sorted[ptr] < t:
            ptr += 1
        if t < wf_start_date:
            continue
        if not started:
            if ptr >= min_warmup_trades:
                started = True
                wf_actual_start = t
            else:
                continue
        if card is None or ptr > last_ptr:
            X_tr_cur = X_all[exit_order_arr[:ptr]]
            if min_discrete_bin_cnt > 0:
                min_valid = max(35, int(0.45 * len(X_tr_cur)))
                keep_idx = []
                for j in range(X_tr_cur.shape[1]):
                    col_j = X_tr_cur[:, j]
                    xv = col_j[np.isfinite(col_j)]
                    if len(xv) < min_valid:
                        continue
                    uniq, cnts = np.unique(xv, return_counts=True)
                    if len(uniq) <= 3 and (len(cnts) < 2 or int(np.sort(cnts)[-2]) < min_discrete_bin_cnt):
                        continue
                    keep_idx.append(j)
                if not keep_idx:
                    keep_idx = list(range(X_tr_cur.shape[1]))
            else:
                keep_idx = list(range(X_tr_cur.shape[1]))

            card = wfc.fit_causal_scorecard(
                X_tr_cur[:, keep_idx], y_ret[exit_order_arr[:ptr]],
                y_win[exit_order_arr[:ptr]], day_ids[exit_order_arr[:ptr]],
                feature_names=[feature_cols[j] for j in keep_idx], mode=mode, top_k=top_k, min_k=min_k,
                max_corr=max_corr, min_t_stat=min_t_stat, shrink_tau=shrink_tau,
                max_delta=max_delta,
                orig_score_train=(orig_arr[exit_order_arr[:ptr]] if orig_arr is not None else None),
                max_corr_orig=max_corr_orig,
            )
            for fac in card.get("factors", []):
                fac["col_idx"] = keep_idx[fac["col_idx"]]
            tr_sc = wfc.score_candidates_with_card(X_tr_cur, card)
            if mode == "delta_patch" and orig_arr is not None:
                tr_eff = orig_arr[exit_order_arr[:ptr]] + tr_sc.astype(float)
            else:
                tr_eff = tr_sc.astype(float)
            q70, q75, q80, q85, q90 = [int(math.ceil(float(np.percentile(tr_eff, q)))) for q in (70, 75, 80, 85, 90)]
            last_ptr = ptr

        rows_t = np.asarray(by_dt_rows[t], dtype=np.int64)
        sc_t = wfc.score_candidates_with_card(X_all[rows_t], card).astype(np.float64)
        wf_in_win[rows_t] = True
        if mode == "scorecard_0_100":
            wf_score[rows_t] = sc_t
        else:
            wf_delta[rows_t] = sc_t
            wf_score[rows_t] = orig_arr[rows_t] + sc_t if orig_arr is not None else sc_t
        thr_q70[rows_t], thr_q75[rows_t], thr_q80[rows_t], thr_q85[rows_t], thr_q90[rows_t] = q70, q75, q80, q85, q90

    out = df_h.copy()
    out["wf_in_window"] = wf_in_win
    out["wf_score"] = wf_score
    out["wf_delta_score"] = wf_delta
    out["wf_thr_top30"] = thr_q70
    out["wf_thr_top25"] = thr_q75
    out["wf_thr_top20"] = thr_q80
    out["wf_thr_top15"] = thr_q85
    out["wf_thr_top10"] = thr_q90
    return out, {"wf_actual_start": wf_actual_start, "latest_card": card}
