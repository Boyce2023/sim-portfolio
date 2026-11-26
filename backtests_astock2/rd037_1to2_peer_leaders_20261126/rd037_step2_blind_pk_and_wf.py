#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD037 Step 2: Comprehensive 1-on-1 Blind PK, Walk-Forward Scorecard Selection,
2024-12-31 Physical Truncation Zero-Leakage Proof, and V20.0 Integration Tests.

Zero yfinance (D12). Zero cap10m. Threads <= 1. Peak RSS < 2.0 GB.
"""
import gc
import json
import math
import os
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa

warnings.filterwarnings("ignore")

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
pa.set_cpu_count(1)
pa.set_io_thread_count(1)

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd037_1to2_peer_leaders_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import _wf_v20_patch as wfp

TRD_DAYS_YEAR = 242.0


def _sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def build_exact_mtm_pairs_for_df(df: pd.DataFrame, seg_col: str, fee_rt: float, dt_to_cal_i: dict, cal_dts: list[str]) -> list:
    """Convert raw gross `mtm_segs_json` into exact `(cal_idx, net_mult)` tuples aligned to `cal_dts`."""
    # Map global cal_5y index (from step1) -> local cal_dts index
    raw_idx = json.load(open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
    all_cal = sorted(raw_idx["sh000300"].keys())
    cal_5y = [d for d in all_cal if "2021-01-04" <= d <= "2026-11-25"]
    g_to_local = {gi: dt_to_cal_i[d] for gi, d in enumerate(cal_5y) if d in dt_to_cal_i}

    out_segs = []
    for s_json in df[seg_col]:
        if not s_json:
            out_segs.append(())
            continue
        arr = json.loads(s_json) if isinstance(s_json, str) else s_json
        if not arr:
            out_segs.append(())
            continue
        loc = []
        for idx_k, (g_di, mult) in enumerate(arr):
            li = g_to_local.get(int(g_di))
            m_val = float(mult) * (1.0 - float(fee_rt)) if idx_k == 0 else float(mult)
            if li is not None:
                loc.append((li, m_val))
        out_segs.append(tuple(loc))
    return out_segs


def eval_custom_windows(
    slot_df: pd.DataFrame,
    pass_df: pd.DataFrame,
    cand_pool_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    windows: list[tuple[str, str, str]],
    mtm_col: str = "mtm_pairs",
    perm_start: str = "2021-11-16",
    perm_end: str = "2026-11-16",
    perm_n: int = 1000,
    seed: int = 20261126,
) -> dict:
    """Evaluate exact daily MTM & trade stats across arbitrary windows (5Y, WF, 25-26, 26, 26H2)."""
    min_s = min(s for _, s, _ in windows)
    max_e = max(e for _, _, e in windows)
    b = bench_df[bench_df["trade_date"].between(min_s, max_e)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = b["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_arr = b["csi300_daily_ret"].to_numpy(float)
    ew_arr = b["alla_ew_daily_ret"].to_numpy(float)

    # Re-index mtm_pairs to local cal_dts if needed or pass cal_dts-aligned pairs
    dr_full, mtm_diff = wfm.build_daily_mtm_returns(slot_df, cal_dts, mtm_col=mtm_col)
    win_res = {}
    for wn, s, e in windows:
        if s <= e:
            win_res[wn] = wfm._calc_one_window(slot_df, pass_df, dr_full, cal_dts, dt_idx, csi_arr, ew_arr, s, e)

    perm = wfm.perm_test_trading_days(slot_df, cand_pool_df, perm_start, perm_end, n_perm=perm_n, seed=seed) if perm_n > 0 else {}
    return {
        "mtm_reconciliation_diff": round(float(mtm_diff), 8),
        "windows": win_res,
        "permutation_1000": perm,
    }


def eval_1to2_benchmarks(v20_ctx: dict, bench_df: pd.DataFrame, cal_dts_full: list[str], dt_idx_full: dict) -> dict:
    """Compute exact 1to2_Self benchmarks (Live92 0.20%, Live92 0.30%, Live92_0925, Live92_Intraday, OrigPass, Wide_P1_All)."""
    p1 = pd.read_parquet(f"{BASE_DIR}/pool_1to2_master_pit.parquet")
    p1["buy_date"] = p1["buy_date"].astype(str).str[:10]
    p1["exit_date"] = p1["exit_date"].astype(str).str[:10]
    p1["code"] = p1["code"].astype(str).str.zfill(6)

    # Use V20 actual MTM builder from bar_lu or exact ledger mtm_pairs for V20 trades; for non-V20, geometric MTM fallback or exact bar_lu
    # Actually we can get exact MTM via wfm.build_daily_mtm_returns (or for V20 ledger exact mtm_pairs)!
    v20_led = v20_ctx["v20_ledger"]
    v20_1to2 = v20_led[v20_led["strategy"] == "1to2"].copy()

    wins_5y = [
        ("FULL_5Y", "2021-11-16", "2026-11-16"),
        ("WF_2326", "2023-01-03", "2026-11-16"),
        ("Y2025_2026", "2025-01-01", "2026-11-16"),
        ("Y2026", "2026-01-01", "2026-11-16"),
        ("Y2026_H2", "2026-07-01", "2026-11-16"),
    ]
    out = {}

    # 1. Live92 official (0.20% fee) and fee-parity (0.30% fee)
    s92 = p1[p1["is_standalone_slot1"] == 1].sort_values("buy_date").reset_index(drop=True)
    for tag, sub_df, fee_adj in [
        ("1to2_Live92_Official_020", s92, 0.0),
        ("1to2_Live92_FeeParity_030", s92, 0.0010),
        ("1to2_Live92_0925Sub_030", s92[s92["buy_hhmm"] == 925].copy(), 0.0010),
        ("1to2_Live92_IntradaySub_030", s92[s92["buy_hhmm"] > 925].copy(), 0.0010),
        ("1to2_V20Slot43_Official_020", p1[p1["is_v20_slot1"] == 1].sort_values("buy_date").copy(), 0.0),
    ]:
        d_sub = sub_df.copy()
        d_sub["net_ret"] = (1.0 + d_sub["net_ret"].astype(float)) * (1.0 - fee_adj) - 1.0
        d_sub["can_buy_hygiene"] = True
        ev = eval_custom_windows(d_sub, d_sub, d_sub, bench_df, wins_5y, mtm_col=None, perm_start="2021-11-16", perm_end="2026-11-16", perm_n=100)
        out[tag] = ev

    # 2. OrigPass single-slot & Wide_P1_All buyable single-slot (score >= 304.8 or all)
    op = p1[p1["orig_pass"] == 1].copy()
    op["can_buy_hygiene"] = True
    op_pass, op_slot = wfm.select_single_slot_trades(op, score_col="v20_score", threshold=None, wf_only=False)
    out["1to2_OrigPass_Slot1_020"] = eval_custom_windows(op_slot, op_pass, op, bench_df, wins_5y, mtm_col=None, perm_n=100)

    wp = p1[p1["sim_ok"] == 1].copy()
    wp["can_buy_hygiene"] = True
    wp_pass, wp_slot = wfm.select_single_slot_trades(wp, score_col="v20_score", threshold=None, wf_only=False)
    out["1to2_WideP1_SimOk_Slot1_020"] = eval_custom_windows(wp_slot, wp_pass, wp, bench_df, wins_5y, mtm_col=None, perm_n=100)
    return out


def run_blind_pk(v20_ctx: dict, bench_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Run exhaustive 1-on-1 blind PK across Anchor Pools x Peer Classes x Entry x Hold H (chunked per pool <0.8GB)."""
    t0 = time.time()
    import pyarrow.parquet as pq
    pf_pk = pq.ParquetFile(f"{CACHE_DIR}/anchor_peer_1to1_all.parquet")
    print(f"[BlindPK] Total rows={pf_pk.metadata.num_rows:,} | RSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9:.3f}GB")

    cal_5y_bench = bench_df[bench_df["trade_date"].between("2021-11-16", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
    cal_dts_5y = cal_5y_bench["trade_date"].tolist()
    dt_idx_5y = {d: i for i, d in enumerate(cal_dts_5y)}

    wins_5y = [
        ("FULL_5Y", "2021-11-16", "2026-11-16"),
        ("WF_2326", "2023-01-03", "2026-11-16"),
        ("Y2025_2026", "2025-01-01", "2026-11-16"),
        ("Y2026", "2026-01-01", "2026-11-16"),
        ("Y2026_H2", "2026-07-01", "2026-11-16"),
    ]

    raw_idx = json.load(open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
    all_cal = sorted(raw_idx["sh000300"].keys())
    cal_5y_all = [d for d in all_cal if "2021-01-04" <= d <= "2026-11-25"]
    g_to_local_5y = {gi: dt_idx_5y[d] for gi, d in enumerate(cal_5y_all) if d in dt_idx_5y}

    rows_summary = []
    anti_leak_diag = {}

    pool_list = [
        "Anchor_Live92", "Anchor_OrigPass", "Anchor_Wide_P1_Ge305", "Anchor_Wide_P1_All",
        "Anchor_Wide_HF_Ge305", "Anchor_Wide_HF_Ge275", "Anchor_Missed_YiziOver", "Anchor_Missed_Untrig",
    ]

    for pool_nm in pool_list:
        pk_p = pd.read_parquet(f"{CACHE_DIR}/anchor_peer_1to1_all.parquet", filters=[("anchor_pool", "==", pool_nm)])
        if pk_p.empty:
            continue
        if pool_nm == "Anchor_Live92":
            l0 = pk_p[pk_p["is_0925_known"] == 1].copy()
            l0["anchor_pool"] = "Anchor_Live92_0925Sub"
            li = pk_p[pk_p["is_0925_known"] == 0].copy()
            li["anchor_pool"] = "Anchor_Live92_IntradaySub"
            pk_p = pd.concat([pk_p, l0, li], ignore_index=True)

        grp_cols = ["anchor_pool", "peer_class", "agg_mode", "entry_mode", "hold_h"]
        for (ap, pc, am, em, hh), grp in pk_p.groupby(grp_cols, sort=False):
            is_causal_track = not (em == "T0_Open" and ap in ("Anchor_Live92", "Anchor_Live92_IntradaySub", "Anchor_OrigPass", "Anchor_Missed_Untrig"))
            n_total_sig = len(grp)
            n_buyable = int((grp["can_buy"] == 1).sum())
            buyable_df = grp[grp["can_buy"] == 1].copy()
            if buyable_df.empty:
                continue

            for fee_rt in ([0.0030, 0.0050] if am in ("Top1_Cascade", "Top3_EW") and hh in (1, 2, 3) else [0.0030]):
                sub = buyable_df.copy()
                sub["net_ret"] = (1.0 + sub["gross_ret"].astype(float)) * (1.0 - fee_rt) - 1.0
                sub["can_buy_hygiene"] = True
                mtm_list = []
                for s_json in sub["mtm_segs_json"]:
                    arr = json.loads(s_json)
                    loc = []
                    for idx_k, (g_di, mult) in enumerate(arr):
                        li = g_to_local_5y.get(int(g_di))
                        m_val = float(mult) * (1.0 - fee_rt) if idx_k == 0 else float(mult)
                        if li is not None:
                            loc.append((li, m_val))
                    mtm_list.append(tuple(loc))
                sub["mtm_pairs"] = mtm_list

                _, slot_df = wfm.select_single_slot_trades(sub, score_col="anchor_score", threshold=None, wf_only=False)
                p_n = 1000 if (is_causal_track and fee_rt == 0.0030 and am == "Top1_Cascade" and ap in (
                    "Anchor_Live92", "Anchor_Live92_0925Sub", "Anchor_Live92_IntradaySub",
                    "Anchor_Wide_P1_Ge305", "Anchor_Wide_HF_Ge305", "Anchor_Missed_YiziOver", "Anchor_Missed_Untrig"
                )) else 0
                ev = eval_custom_windows(
                    slot_df, sub, sub, cal_5y_bench, wins_5y,
                    mtm_col="mtm_pairs", perm_start="2021-11-16", perm_end="2026-11-16", perm_n=p_n
                )

                f5 = ev["windows"]["FULL_5Y"]
                wf_w = ev["windows"]["WF_2326"]
                y25 = ev["windows"]["Y2025_2026"]
                y26 = ev["windows"]["Y2026"]
                h2 = ev["windows"]["Y2026_H2"]

                rows_summary.append({
                    "track_type": "BLIND_PK",
                    "anchor_pool": ap,
                    "peer_class": pc,
                    "agg_mode": am,
                    "entry_mode": em,
                    "hold_h": int(hh),
                    "fee_bps": int(round(fee_rt * 10000)),
                    "is_causal": int(is_causal_track),
                    "n_signals": int(n_total_sig),
                    "n_buyable": int(n_buyable),
                    "buyable_pct": round(n_buyable / max(1, n_total_sig) * 100.0, 2),
                    "n_slot_5y": f5.get("n", 0),
                    "wr_5y": f5.get("wr_pct", 0.0),
                    "plr_5y": f5.get("plr", 0.0),
                    "mean_5y": f5.get("mean_pct", 0.0),
                    "nav_5y": f5.get("nav", 1.0),
                    "eq_nav_5y": f5.get("eq_nav", 1.0),
                    "ex3_5y": f5.get("ex_top3_nav", 1.0),
                    "ex5_5y": f5.get("ex_top5_nav", 1.0),
                    "mdd_5y": f5.get("daily_mdd_pct", 0.0),
                    "sharpe_5y": f5.get("daily_sharpe", 0.0),
                    "excess_csi_5y": f5.get("excess_csi300_pp", 0.0),
                    "n_wf": wf_w.get("n", 0),
                    "wr_wf": wf_w.get("wr_pct", 0.0),
                    "mean_wf": wf_w.get("mean_pct", 0.0),
                    "nav_wf": wf_w.get("nav", 1.0),
                    "ex5_wf": wf_w.get("ex_top5_nav", 1.0),
                    "mdd_wf": wf_w.get("daily_mdd_pct", 0.0),
                    "sharpe_wf": wf_w.get("daily_sharpe", 0.0),
                    "excess_csi_wf": wf_w.get("excess_csi300_pp", 0.0),
                    "n_2526": y25.get("n", 0),
                    "wr_2526": y25.get("wr_pct", 0.0),
                    "mean_2526": y25.get("mean_pct", 0.0),
                    "nav_2526": y25.get("nav", 1.0),
                    "n_2026": y26.get("n", 0),
                    "wr_2026": y26.get("wr_pct", 0.0),
                    "mean_2026": y26.get("mean_pct", 0.0),
                    "nav_2026": y26.get("nav", 1.0),
                    "excess_csi_2026": y26.get("excess_csi300_pp", 0.0),
                    "n_26h2": h2.get("n", 0),
                    "wr_26h2": h2.get("wr_pct", 0.0),
                    "mean_26h2": h2.get("mean_pct", 0.0),
                    "nav_26h2": h2.get("nav", 1.0),
                    "perm_sd_p": ev["permutation_1000"].get("same_day_p_nav", np.nan) if p_n > 0 else np.nan,
                    "perm_any_p": ev["permutation_1000"].get("any_cand_day_p_nav", np.nan) if p_n > 0 else np.nan,
                    "mtm_diff": ev["mtm_reconciliation_diff"],
                })

                if not is_causal_track and fee_rt == 0.0030 and am == "Top1_Cascade" and hh == 1:
                    anti_leak_diag[f"{ap}__{pc}__T0_Open_LEAKY"] = {
                        "note": "INVALID intraday lookahead (78/92 trades unknown at 09:25)",
                        "nav_5y": f5.get("nav", 1.0),
                        "wr_5y": f5.get("wr_pct", 0.0),
                    }
        del pk_p
        gc.collect()
        pa.default_memory_pool().release_unused()

    res_df = pd.DataFrame(rows_summary)
    print(f"[BlindPK] Evaluated {len(res_df)} rows in {time.time()-t0:.1f}s | RSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9:.3f}GB")
    return res_df, anti_leak_diag


def run_wf_scorecards(v20_ctx: dict, bench_df: pd.DataFrame) -> tuple[list[dict], dict, pd.DataFrame]:
    """Run strict exit_date < t Walk-Forward Scorecard across combined & per-peer-class tracks."""
    t0 = time.time()
    wf_raw = pd.read_parquet(f"{CACHE_DIR}/wf_peer_candidates_all.parquet")
    print(f"[WF] Loaded wf_peer_candidates_all {wf_raw.shape} | RSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9:.3f}GB")

    # Feature sets strictly partitioned by entry timestamp!
    feats_0925 = [
        "peer_ret_1d_t1", "peer_ret_5d_t1", "peer_ret_20d_t1",
        "peer_pos_20d_t1", "peer_pos_60d_t1", "peer_pos_250d_t1",
        "peer_dd_20d_t1", "peer_bias10_t1", "peer_bias20_t1", "peer_overhang_t1",
        "peer_zt20_t1", "peer_zt60_t1", "peer_cool_days_zt",
        "peer_open_pct_t0", "peer_open_minus_anc",
        "anchor_score", "anchor_s_prior", "anchor_s_quant", "anchor_open_pct",
        "anchor_p_sz", "anchor_rk_theme", "anchor_d1_tight", "anchor_front_lock", "anchor_yizi_cnt",
        "peer_kpl_on_t1", "peer_kpl_60", "peer_kpl_1y", "peer_kpl_3y",
        "peer_ind_ex5_t1", "peer_ind_ex20_t1", "peer_ind_rk20_t1", "peer_ind_zt_sh5_t1",
        "peer_free_mcap_log", "peer_amt20_log", "peer_vol_ratio5_t1", "peer_turn_5_20_t1",
        "peer_real_turn_t1", "peer_amp_20d_t1", "peer_zt_3y_t1", "peer_waves_3y_t1",
        "peer_yz3y_t1", "peer_yz1y_t1", "peer_comm_pct", "peer_xq_pct",
        "peer_lhb_bayes_t1", "peer_lhb_inst_t1", "peer_lhb_goodyz_t1",
        "is_20cm", "role_oldyz", "role_oldyz_sm", "role_recact", "role_inst", "role_ind1",
        "mkt_zt_cnt_t1", "mkt_zb_rate_t1", "mkt_zt_prem_t1", "mkt_amt_ratio20_t1",
        "mkt_ew_bias20_t1", "mkt_abv_ma20_t1", "mkt_0925_gap", "us_ixic_1d_on", "nt_v3_eod_t1",
    ]
    feats_t0_close = feats_0925 + ["anchor_zt_t0", "anchor_ret_t0", "peer_ret_1d_t0"]
    feats_t1_open = feats_t0_close + ["entry_open_pct"]

    cal_wf_bench = bench_df[bench_df["trade_date"].between("2023-01-03", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
    cal_dts_wf = cal_wf_bench["trade_date"].tolist()
    dt_idx_wf = {d: i for i, d in enumerate(cal_dts_wf)}

    raw_idx = json.load(open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
    all_cal = sorted(raw_idx["sh000300"].keys())
    cal_5y_all = [d for d in all_cal if "2021-01-04" <= d <= "2026-11-25"]
    g_to_local_wf = {gi: dt_idx_wf[d] for gi, d in enumerate(cal_5y_all) if d in dt_idx_wf}

    wf_rows_summary = []
    wf_audits = {}
    best_slot_df = pd.DataFrame()
    best_score = -999.0

    # Define experiment specs: (name, anchor_filter, role_filter, entry_mode, hold_h, fee_rt)
    specs = []
    for em in ("T0_Open", "T0_Close", "T1_Open"):
        for h in (1, 2, 3, 5):
            specs.append((f"AllPeers_{em}_H{h}_Ge275", "all_ge275", None, em, h, 0.0030))
        for h in (1, 2):
            specs.append((f"AllPeers_{em}_H{h}_Ge305", "hf_ge305", None, em, h, 0.0030))
            specs.append((f"AllPeers_{em}_H{h}_P1All", "p1_all", None, em, h, 0.0030))

    # Individual role scorecards at H=1, 2, 3
    for role_col, role_lbl in [
        ("role_oldyz", "Peer1A_OldYouzi"),
        ("role_oldyz_sm", "Peer1B_OldYouziSM"),
        ("role_recact", "Peer2_RecActive"),
        ("role_inst", "Peer3_InstBig"),
        ("role_ind1", "Peer4_IndLead1"),
    ]:
        for em in ("T0_Open", "T0_Close", "T1_Open"):
            for h in (1, 2, 3):
                specs.append((f"{role_lbl}_{em}_H{h}", "all_ge275", role_col, em, h, 0.0030))

    trunc_proofs = []
    for sp_name, anc_flt, role_col, em, h, fee_rt in specs:
        sub = wf_raw[wf_raw["entry_mode"] == em].copy()
        if anc_flt == "hf_ge305":
            sub = sub[sub["in_hf_ge305"] == 1]
        elif anc_flt == "p1_all":
            sub = sub[sub["in_p1_all"] == 1]
        if role_col is not None:
            sub = sub[sub[role_col] == 1]

        sub["exit_date"] = sub[f"exit_date_H{h}"]
        sub["gross_ret"] = sub[f"gross_ret_H{h}"]
        sub = sub[sub["exit_date"].notna() & sub["gross_ret"].notna()].copy().reset_index(drop=True)
        if len(sub) < 120:
            continue

        fcols = feats_0925 if em == "T0_Open" else (feats_t0_close if em == "T0_Close" else feats_t1_open)
        if role_col is not None:
            fcols = [c for c in fcols if not c.startswith("role_")]

        rec_freq = "daily" if (role_col is None or h in (1, 2)) else "monthly"
        p_n_wf = 1000 if (role_col is None or h == 1) else 300
        res = wf.run_wf_scorecard_new_strategy(
            sub,
            feature_cols=fcols,
            v20_ctx=v20_ctx,
            wf_start_date="2023-01-03",
            end_date="2026-11-16",
            min_warmup_trades=80,
            min_warmup_trades_rare=60,
            min_warmup_months=18,
            recalc_freq=rec_freq,
            top_k=10,
            min_k=5,
            max_corr=0.65,
            min_t_stat=1.0,
            shrink_tau=20.0,
            fee_rt=fee_rt,
            gross_ret_col="gross_ret",
            tie_col="anchor_score",
            mtm_col=None,
            thresholds=("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80),
            eval_v20_patch=False,
            perm_n=p_n_wf,
            seed=20261126,
        )

        actual_wf_start = res["meta"].get("wf_actual_start") or "2023-01-03"
        cal_act = bench_df[bench_df["trade_date"].between(actual_wf_start, "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
        cal_dts_act = cal_act["trade_date"].tolist()
        dt_idx_act = {d: i for i, d in enumerate(cal_dts_act)}
        g_to_act = {gi: dt_idx_act[d] for gi, d in enumerate(cal_5y_all) if d in dt_idx_act}
        wins_act = [
            ("FULL_WF", actual_wf_start, "2026-11-16"),
            ("Y2025_2026", "2025-01-01", "2026-11-16"),
            ("Y2026", "2026-01-01", "2026-11-16"),
            ("Y2026_H2", "2026-07-01", "2026-11-16"),
        ]

        # Re-compute exact daily MTM & V20 empty-slot patch aligned cleanly to actual_wf_start
        for th_key, tr in res["threshold_results"].items():
            slot_df = tr["slot_df"].copy()
            pass_df = tr["pass_df"].copy()
            if not slot_df.empty:
                mtm_s = []
                for s_json in slot_df[f"mtm_segs_H{h}"]:
                    arr = json.loads(s_json)
                    mtm_s.append(tuple((g_to_act[int(g_di)], float(mult) * (1.0 - fee_rt) if ik == 0 else float(mult))
                                       for ik, (g_di, mult) in enumerate(arr) if int(g_di) in g_to_act))
                slot_df["mtm_pairs_act"] = mtm_s
            else:
                slot_df["mtm_pairs_act"] = []

            ev_exact = eval_custom_windows(
                slot_df, pass_df, sub[sub["buy_date"] >= actual_wf_start],
                bench_df, wins_act, mtm_col="mtm_pairs_act", perm_n=0
            )
            fw = ev_exact["windows"].get("FULL_WF", {})
            y25 = ev_exact["windows"].get("Y2025_2026", {})
            y26 = ev_exact["windows"].get("Y2026", {})
            h2_res = ev_exact["windows"].get("Y2026_H2", {})

            vp = None
            if not pass_df.empty and th_key != "all_cands":
                p_mtm = []
                for s_json in pass_df[f"mtm_segs_H{h}"]:
                    arr = json.loads(s_json)
                    p_mtm.append(tuple((g_to_act[int(g_di)], float(mult) * (1.0 - fee_rt) if ik == 0 else float(mult))
                                       for ik, (g_di, mult) in enumerate(arr) if int(g_di) in g_to_act))
                pass_df["mtm_pairs_act"] = p_mtm
                vp = wfp.simulate_v20_empty_slot_patch(
                    pass_df, v20_ctx=v20_ctx, wf_start_dt=actual_wf_start, end_dt="2026-11-16",
                    score_col="wf_score", patch_mtm_col="mtm_pairs_act",
                )

            ev = tr["metrics"]
            vp_ratio = vp["mode1_strict_combined_no_peek"]["delta_nav_ratio_full_wf"] if vp else np.nan
            vp_emp_nav = vp["mode2_empty_slot_standalone"]["windows"]["FULL_WF"].get("nav", np.nan) if vp else np.nan
            vp_emp_n = vp["mode2_empty_slot_standalone"]["n_standalone_empty_trades"] if vp else 0

            row_rec = {
                "track_type": "WF_SCORECARD",
                "spec_name": sp_name,
                "anchor_filter": anc_flt,
                "role_filter": role_col or "ALL_PEERS",
                "entry_mode": em,
                "hold_h": int(h),
                "threshold": th_key,
                "fee_bps": int(round(fee_rt * 10000)),
                "n_pass": tr["n_passing_cands"],
                "n_slot": fw.get("n", 0),
                "wr_wf": fw.get("wr_pct", 0.0),
                "plr_wf": fw.get("plr", 0.0),
                "mean_wf": fw.get("mean_pct", 0.0),
                "nav_wf": fw.get("nav", 1.0),
                "eq_nav_wf": fw.get("eq_nav", 1.0),
                "ex3_wf": fw.get("ex_top3_nav", 1.0),
                "ex5_wf": fw.get("ex_top5_nav", 1.0),
                "mdd_wf": fw.get("daily_mdd_pct", 0.0),
                "sharpe_wf": fw.get("daily_sharpe", 0.0),
                "excess_csi_wf": fw.get("excess_csi300_pp", 0.0),
                "n_2526": y25.get("n", 0),
                "wr_2526": y25.get("wr_pct", 0.0),
                "mean_2526": y25.get("mean_pct", 0.0),
                "nav_2526": y25.get("nav", 1.0),
                "n_2026": y26.get("n", 0),
                "wr_2026": y26.get("wr_pct", 0.0),
                "mean_2026": y26.get("mean_pct", 0.0),
                "nav_2026": y26.get("nav", 1.0),
                "excess_csi_2026": y26.get("excess_csi300_pp", 0.0),
                "n_26h2": h2_res.get("n", 0),
                "wr_26h2": h2_res.get("wr_pct", 0.0),
                "mean_26h2": h2_res.get("mean_pct", 0.0),
                "nav_26h2": h2_res.get("nav", 1.0),
                "perm_sd_p": ev["permutation_1000"].get("same_day_p_nav", 1.0),
                "perm_any_p": ev["permutation_1000"].get("any_cand_day_p_nav", 1.0),
                "v20_comb_ratio": vp_ratio,
                "v20_emp_nav": vp_emp_nav,
                "v20_emp_n": vp_emp_n,
                "mtm_diff": ev_exact["mtm_reconciliation_diff"],
            }
            wf_rows_summary.append(row_rec)

            # Track best WF candidate for stress test & truncation check
            if th_key != "all_cands" and fw.get("n", 0) >= 25:
                sc_rank = float(fw.get("nav", 1.0)) * min(1.5, max(0.5, float(fw.get("ex_top5_nav", 1.0))))
                if sc_rank > best_score:
                    best_score = sc_rank
                    best_slot_df = slot_df.copy()
                    best_spec = (sp_name, th_key, sub, fcols, em, h)

        # Save last scorecard factor snapshot for interpretability
        latest_card = res["meta"].get("latest_scorecard") or {}
        if sp_name.startswith("AllPeers_") and h in (1, 2):
            wf_audits[sp_name] = {
                "wf_actual_start": res["meta"].get("wf_actual_start"),
                "n_rebuilds": res["meta"].get("n_rebuilds"),
                "last_card_factors": latest_card.get("factors", []),
            }
            print(f"  [WF] {sp_name} ({rec_freq}, start={actual_wf_start}) done | elapsed={time.time()-t0:.1f}s")

    # Physical truncation verification (2024-12-31) on top AllPeers tracks (all 3 entry modes)
    for em_check in ("T0_Open", "T0_Close", "T1_Open"):
        sub_c = wf_raw[wf_raw["entry_mode"] == em_check].copy()
        sub_c["exit_date"] = sub_c["exit_date_H1"]
        sub_c["gross_ret"] = sub_c["gross_ret_H1"]
        sub_c = sub_c[sub_c["exit_date"].notna() & sub_c["gross_ret"].notna()].copy().reset_index(drop=True)
        fc_c = feats_0925 if em_check == "T0_Open" else (feats_t0_close if em_check == "T0_Close" else feats_t1_open)
        tp = wf.verify_truncation_zero_leakage(
            sub_c, fc_c, mode="A", cutoff="2024-12-31", score_threshold="top20",
            v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80, min_warmup_trades_rare=60,
            min_warmup_months=18, recalc_freq="daily", top_k=10, min_k=5, max_corr=0.65,
            min_t_stat=1.0, shrink_tau=20.0, fee_rt=0.0030, gross_ret_col="gross_ret", tie_col="anchor_score"
        )
        trunc_proofs.append({"entry_mode": em_check, **tp})
        print(f"[TruncProof {em_check}] max_score_diff={tp['max_abs_score_diff']} | max_ret_diff={tp['max_abs_ret_diff']} | PASS={tp['zero_leakage_pass']}")

    # Also run 0.50% fee stress test on the best WF spec if valid
    stress_res = {}
    if best_score > -900:
        sp_n, th_k, sub_b, fcols_b, em_b, h_b = best_spec
        res_50 = wf.run_wf_scorecard_new_strategy(
            sub_b, feature_cols=fcols_b, v20_ctx=v20_ctx, wf_start_date="2023-01-03",
            end_date="2026-11-16", min_warmup_trades=80, min_warmup_trades_rare=60,
            min_warmup_months=18, recalc_freq="daily", top_k=10, min_k=5, max_corr=0.65,
            min_t_stat=1.0, shrink_tau=20.0, fee_rt=0.0050, gross_ret_col="gross_ret",
            tie_col="anchor_score", thresholds=tuple(dict.fromkeys([th_k, "top20", "top10"])), eval_v20_patch=True, perm_n=500
        )
        stress_res = {
            "best_spec": sp_n,
            "best_thr": th_k,
            "summary_50bps": res_50["summary_table"].to_dict(orient="records"),
        }

    wf_df_out = pd.DataFrame(wf_rows_summary)
    print(f"[WF] Completed {len(specs)} specs in {time.time()-t0:.1f}s | RSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9:.3f}GB")
    return trunc_proofs, {"cards": wf_audits, "stress_50bps": stress_res}, wf_df_out


def run_v20_integration_tests(v20_ctx: dict, bench_df: pd.DataFrame, pk_raw: pd.DataFrame, wf_df_raw: pd.DataFrame) -> dict:
    """
    Answer Question 3:
      3A. Missed-Leader Rescue (Anchor_Missed_YiziOver & Anchor_Missed_Untrig) standalone + V20 empty-slot injection.
      3B. Replace V20's 43 1to2 trades with Peer1..4 inside V20 6-strategy single-slot rotation!
    """
    cal_5y = v20_ctx["calendar_5y"]
    cal_win = cal_5y[cal_5y["trade_date"].between("2021-11-16", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_arr = cal_win["csi300_daily_ret"].to_numpy(float)
    ew_arr = cal_win["alla_ew_daily_ret"].to_numpy(float)

    raw_idx = json.load(open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
    all_cal = sorted(raw_idx["sh000300"].keys())
    cal_5y_all = [d for d in all_cal if "2021-01-04" <= d <= "2026-11-25"]
    g_to_local = {gi: dt_idx[d] for gi, d in enumerate(cal_5y_all) if d in dt_idx}

    v20_led = v20_ctx["v20_ledger"].copy()
    v20_5y = v20_led[v20_led["buy_date"].between("2021-11-16", "2026-11-16")].copy()
    v20_5y["source"] = "v20"
    dr_v20, _ = wfp._build_combined_mtm(v20_5y, cal_dts)

    wins_5y = [
        ("FULL_5Y", "2021-11-16", "2026-11-16"),
        ("WF_2326", "2023-01-03", "2026-11-16"),
        ("Y2025_2026", "2025-01-01", "2026-11-16"),
        ("Y2026", "2026-01-01", "2026-11-16"),
    ]
    v20_base_metrics = {wn: wfm._calc_one_window(v20_5y, None, dr_v20, cal_dts, dt_idx, csi_arr, ew_arr, s, e) for wn, s, e in wins_5y}

    # 3A: Missed Leader Empty-Slot Patch (WF window 2023-2026)
    missed_patches = {}
    for ap, em, hh in [
        ("Anchor_Missed_YiziOver", "T0_Open", 1),
        ("Anchor_Missed_YiziOver", "T0_Close", 1),
        ("Anchor_Missed_YiziOver", "T1_Open", 1),
        ("Anchor_Missed_Untrig", "T0_Close", 1),
        ("Anchor_Missed_Untrig", "T1_Open", 1),
    ]:
        for pc in ("Peer1A_OldYouzi_KPL", "Peer2_RecentActive_KPL", "Peer3A_InstBigCap_KPL100", "Peer4_IndLeader1"):
            sub = pk_raw[(pk_raw["anchor_pool"] == ap) & (pk_raw["peer_class"] == pc) &
                         (pk_raw["agg_mode"] == "Top1_Cascade") & (pk_raw["entry_mode"] == em) &
                         (pk_raw["hold_h"] == hh) & (pk_raw["can_buy"] == 1)].copy()
            if sub.empty:
                continue
            sub["net_ret"] = (1.0 + sub["gross_ret"].astype(float)) * (1.0 - 0.0030) - 1.0
            sub["wf_score"] = sub["anchor_score"]
            # Check empty slot patch in WF 2023-2026
            patch_res = wfp.simulate_v20_empty_slot_patch(
                sub, v20_ctx=v20_ctx, wf_start_dt="2023-01-03", end_dt="2026-11-16",
                respect_stier_waits=True, score_col="wf_score"
            )
            m1 = patch_res["mode1_strict_combined_no_peek"]
            m2 = patch_res["mode2_empty_slot_standalone"]
            missed_patches[f"{ap}__{pc}__{em}_H{hh}"] = {
                "n_patch_added": m1["n_patch_added"],
                "n_v20_skipped": m1["n_v20_skipped_by_collision"],
                "delta_nav_ratio_wf": m1["delta_nav_ratio_full_wf"],
                "delta_sharpe_wf": m1["delta_sharpe_full_wf"],
                "emp_standalone_n": m2["n_standalone_empty_trades"],
                "emp_standalone_nav": m2["windows"]["FULL_WF"].get("nav", 1.0),
                "emp_standalone_wr": m2["windows"]["FULL_WF"].get("wr_pct", 0.0),
            }

    # 3B: Replace V20's 43 1to2 trades with same-day Peer Leader
    # For each of the 43 V20 1to2 trades, check buy_hhmm: if > 925, ONLY T0_Close or T1_Open is causal!
    v20_other = v20_5y[v20_5y["strategy"] != "1to2"].copy()
    v20_1to2 = v20_5y[v20_5y["strategy"] == "1to2"].copy()
    p1_live = pk_raw[pk_raw["anchor_pool"] == "Anchor_Live92"].copy()

    replace_res = {}
    for pc in ("Peer1A_OldYouzi_KPL", "Peer2_RecentActive_KPL", "Peer3A_InstBigCap_KPL100", "Peer4_IndLeader1"):
        for em in ("T0_Close", "T1_Open"):
            for hh in (1, 2):
                cand_r = p1_live[(p1_live["peer_class"] == pc) & (p1_live["agg_mode"] == "Top1_Cascade") &
                                 (p1_live["entry_mode"] == em) & (p1_live["hold_h"] == hh) &
                                 (p1_live["can_buy"] == 1)].copy()
                cand_map = {r.anchor_date: r for r in cand_r.itertuples(index=False)}
                # Simulate chronological 6-strat single-slot keeping V20 priority, replacing 1to2 slots
                events = []
                for r in v20_other.itertuples(index=False):
                    events.append({
                        "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm),
                        "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
                        "code": r.code, "strategy": r.strategy, "net_ret": float(r.net_ret),
                        "source": "v20", "mtm_pairs": r.mtm_pairs,
                    })
                for r in v20_1to2.itertuples(index=False):
                    pr = cand_map.get(r.buy_date)
                    if pr is None:
                        continue
                    nr = (1.0 + float(pr.gross_ret)) * (1.0 - 0.0030) - 1.0
                    arr = json.loads(pr.mtm_segs_json)
                    pairs = [(cal_dts[g_to_local[int(g_di)]], float(mult) * (1.0 - 0.0030) if ik == 0 else float(mult))
                             for ik, (g_di, mult) in enumerate(arr) if int(g_di) in g_to_local]
                    events.append({
                        "buy_date": pr.buy_date, "buy_hhmm": int(pr.buy_hhmm),
                        "exit_date": pr.exit_date, "exit_hhmm": int(pr.exit_hhmm),
                        "code": pr.code, "strategy": f"peer_{pc}", "net_ret": nr,
                        "source": "v20", "mtm_pairs": pairs,
                    })
                ev_df = pd.DataFrame(events).sort_values(["buy_date", "buy_hhmm", "code"]).reset_index(drop=True)
                taken = []
                cur_ed, cur_eh = "", 0
                for r in ev_df.itertuples(index=False):
                    if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh):
                        taken.append(r._asdict())
                        cur_ed, cur_eh = r.exit_date, int(r.exit_hhmm)
                t_df = pd.DataFrame(taken)
                dr_rep, _ = wfp._build_combined_mtm(t_df, cal_dts)
                rep_m = {wn: wfm._calc_one_window(t_df, None, dr_rep, cal_dts, dt_idx, csi_arr, ew_arr, s, e) for wn, s, e in wins_5y}
                replace_res[f"{pc}__{em}_H{hh}"] = {
                    "n_peer_taken": int(t_df["strategy"].str.startswith("peer_").sum()),
                    "nav_5y_ratio_vs_v20": round(rep_m["FULL_5Y"]["nav"] / v20_base_metrics["FULL_5Y"]["nav"], 4),
                    "nav_wf_ratio_vs_v20": round(rep_m["WF_2326"]["nav"] / v20_base_metrics["WF_2326"]["nav"], 4),
                    "nav_2026_ratio_vs_v20": round(rep_m["Y2026"]["nav"] / v20_base_metrics["Y2026"]["nav"], 4),
                    "sharpe_5y": rep_m["FULL_5Y"]["daily_sharpe"],
                    "mdd_5y": rep_m["FULL_5Y"]["daily_mdd_pct"],
                }

    return {
        "v20_baseline": v20_base_metrics,
        "missed_leader_empty_slot_patches": missed_patches,
        "replace_1to2_in_v20": replace_res,
    }


def main():
    t0 = time.time()
    v20_ctx = wfp.load_v20_reference_context(BASE_DIR)
    bench_df = v20_ctx["bench"]
    cal_5y_bench = bench_df[bench_df["trade_date"].between("2021-11-16", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
    cal_dts_5y = cal_5y_bench["trade_date"].tolist()
    dt_idx_5y = {d: i for i, d in enumerate(cal_dts_5y)}

    print("[1/4] Computing 1to2_Self exact benchmarks ...")
    self_bms = eval_1to2_benchmarks(v20_ctx, cal_5y_bench, cal_dts_5y, dt_idx_5y)

    print("[2/4] Running 1-on-1 Blind PK Matrix ...")
    blind_cache = f"{CACHE_DIR}/blind_pk_cache.parquet"
    leak_cache = f"{CACHE_DIR}/anti_leak_cache.json"
    if os.path.exists(blind_cache) and os.path.exists(leak_cache):
        blind_df = pd.read_parquet(blind_cache)
        anti_leak_diag = json.load(open(leak_cache, encoding="utf-8"))
        print(f"[BlindPK] Loaded cached {len(blind_df)} rows")
    else:
        blind_df, anti_leak_diag = run_blind_pk(v20_ctx, bench_df)
        blind_df.to_parquet(blind_cache, index=False)
        with open(leak_cache, "w", encoding="utf-8") as f:
            json.dump(_sanitize(anti_leak_diag), f, ensure_ascii=False, indent=2)

    print("[3/4] Running Walk-Forward Scorecard & 2024-12-31 Truncation Check ...")
    trunc_proofs, wf_extra, wf_df = run_wf_scorecards(v20_ctx, bench_df)

    print("[4/4] Running V20.0 Integration Tests (Missed Rescue + Replace 1to2) ...")
    pk_raw = pd.read_parquet(
        f"{CACHE_DIR}/anchor_peer_1to1_all.parquet",
        filters=[("anchor_pool", "in", ["Anchor_Missed_YiziOver", "Anchor_Missed_Untrig", "Anchor_Live92"])],
    )
    v20_int = run_v20_integration_tests(v20_ctx, bench_df, pk_raw, wf_df)

    # Combine blind_df + wf_df into `rd037_peer_matrix.csv`
    matrix_df = pd.concat([blind_df, wf_df], ignore_index=True, sort=False)
    matrix_path = f"{OUT_DIR}/rd037_peer_matrix.csv"
    matrix_df.to_csv(matrix_path, index=False)

    rss_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9
    audit = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 2),
            "peak_rss_gb": round(rss_gb, 3),
            "n_matrix_rows": int(len(matrix_df)),
            "n_blind_rows": int(len(blind_df)),
            "n_wf_rows": int(len(wf_df)),
        },
        "benchmarks_1to2_self": self_bms,
        "anti_leakage_diagnostic": anti_leak_diag,
        "truncation_zero_leakage_2024_12_31": trunc_proofs,
        "wf_scorecard_details": wf_extra,
        "v20_integration": v20_int,
    }
    audit_path = f"{OUT_DIR}/rd037_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(_sanitize(audit), f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] Saved {matrix_path} ({len(matrix_df)} rows) & {audit_path} | elapsed={time.time()-t0:.1f}s | Peak RSS={rss_gb:.3f} GB")
    assert rss_gb < 2.0, f"Peak RSS {rss_gb:.3f} GB >= 2.0 GB!"


if __name__ == "__main__":
    main()
