#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-5 Track A (30d200% Day30-31 48-Factor Scorecard) & Track B (Famous Youzi Bayes LHB Divergence).
Zero yfinance (D12). Zero cap10m. Single-thread, RAM < 2 GB. Strict exit_date < t & 2024-12-31 truncation proof.
"""
import gc
import json
import os
import resource
import sys
import time

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _w2b5_common as wc

ABN_DIR = f"{wc.SIM}/backtests_astock2/abn_30d200_day30_31_factors_20261125"
RD016_DIR = f"{wc.SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117"
STOCK_CORE_PQ = f"{wc.WAVE1_DIR}/stock_day_core_features_pit.parquet"
MKT_PIT_PQ = f"{wc.WAVE1_DIR}/market_daily_all_new_factors_pit.parquet"

if ABN_DIR not in sys.path:
    sys.path.insert(0, ABN_DIR)
import step5_d31_build_panel_and_is_explore as abn_s5


def run_track_a(v20_ctx: dict, mkt_df: pd.DataFrame) -> dict:
    t0 = time.time()
    print("\n=== [Track A] 30d200% Day30-31 48-Factor Causal WF Scorecard ===")
    ev_enr = pd.read_parquet(f"{ABN_DIR}/events_hold_d31_enriched.parquet")
    ev_48 = pd.read_parquet(f"{ABN_DIR}/events_hold_48factors.parquet")
    assert len(ev_enr) == len(ev_48), "Mismatch between enriched and 48factors"

    # Build px_lookup from f1..f20 bars inside events_hold_d31_enriched (exact adjusted open/close)
    px_lookup = {}
    for r in ev_enr.itertuples(index=False):
        c6 = str(r.c6).zfill(6)
        # Also D30 bar
        if pd.notna(r.d30_close_raw):
            px_lookup[(c6, str(r.d30_date))] = (float(r.f1_ao) / (1.0 + float(r.d31_gap) / 100.0), float(r.f1_ao) / (1.0 + float(r.d31_gap) / 100.0))
        ak = int(r.avail_k)
        for k in range(1, ak + 1):
            dt_k = getattr(r, f"f{k}_date")
            ao_k = getattr(r, f"f{k}_ao")
            ac_k = getattr(r, f"f{k}_ac")
            if dt_k and pd.notna(ao_k) and pd.notna(ac_k):
                px_lookup[(c6, str(dt_k))] = (float(ao_k), float(ac_k))

    # Strict PIT features available at D30 14:55 (NO post-close D30 LHB, NO D31 features)
    d30_pit_feats = [
        "is_20", "peak_dev30", "end_dev30", "win_max_any", "relief_1d_pp", "relief_3d_pp",
        "dd_at_d30", "d30_pct", "d30_close_zt", "d30_is_yang", "d30_is_fake_yin", "d30_is_true_yin",
        "d30_upper_shadow", "d30_lower_shadow", "d30_clv", "d30_body",
        "amp5_avg", "box5_range", "vol_shrink_5_20", "vol_d30_to_5", "d30_turn_pct", "turn5_avg_pct",
        "above_ma5", "above_ma10", "dist_ma5_pct", "dist_ma10_pct",
        "max_streak_30d", "zt_days_30d", "days_since_last_zt", "d30_touch_zt_unsealed", "d30_ret_5d",
        "had_susp_30d", "mcap_yi", "mcap_rel250", "d30_amount_yi", "amount5_avg_yi",
        "kpl_in_1d_d29", "kpl_in_3d_d29", "kpl_in_5d_d29", "kpl_in_10d_d29", "kpl_in_30d_d29",
        "kpl_days_30d_d29", "has_real_theme_d29", "theme_zt_d29", "theme_zt_5d_d29",
        "theme_trend_up_d29", "theme_low_assist_d29", "is_theme_leader_d29",
        "theme_zt_d30_live", "theme_low_assist_d30", "top10_free_lock_pct",
        "reg_inquiry_10d", "reg_inquiry_30d", "reg_abn_cnt_30d",
        "lhb_cnt_5d_d29", "lhb_inst_net_5d_d29", "lhb_inst_buy_5d_d29",
        "lhb_lasa_ratio_5d_d29", "lhb_famous_yz_net_5d_d29",
        "mkt_zt_cnt_d29", "mkt_dt_cnt_d29", "mkt_amt_tril_d29", "hs300_ret5_d30", "hs300_ret20_d30",
        "d30_weekday", "in_peak_pool", "in_end_pool",
    ]
    # Additional PIT features unlocked by D31 09:25 (post-close D30 + D31 auction)
    d31_extra_feats = [
        "lhb_on_d30", "lhb_d30_inst_net", "lhb_d30_lasa_ratio", "d30_lhb_yz_net",
        "kpl_in_d30", "kpl_theme_zt_d30", "d30_kpl_zt_cnt",
        "mkt_zt_cnt_d30", "mkt_dt_cnt_d30", "mkt_amt_tril_d30", "mkt_amt_rel250", "mkt_max_streak_d30",
        "reg_abn_d31_0925", "reg_inq_d31_0925",
        "d31_gap", "d31_open_zt", "d31_mkt10_opzt", "d31_mkt20_opzt", "d31_weekday",
        "L1_sent_phase_t1", "L1_zt_cnt_t1", "L1_duanban_damian_t1", "mkt_0925_zt_cnt", "mkt_0925_avg_gap_pct",
    ]
    d30_pit_feats = [c for c in d30_pit_feats if c in ev_enr.columns]
    d31_pit_feats = d30_pit_feats + [c for c in d31_extra_feats if c in ev_enr.columns or c in mkt_df.columns]

    # Join market_daily PIT onto ev_enr by d31_date
    ev_m = ev_enr.merge(
        mkt_df[["trade_date", "L1_sent_phase_t1", "L1_zt_cnt_t1", "L1_duanban_damian_t1", "mkt_0925_zt_cnt", "mkt_0925_avg_gap_pct"]],
        left_on="d31_date", right_on="trade_date", how="left"
    )
    for col in ev_m.columns:
        if ev_m[col].dtype == bool:
            ev_m[col] = ev_m[col].astype(np.int8)

    # Variant A1: D31 Open -> E1_D32_TP12 (0.30% fee)
    tr_e1 = abn_s5.sim_exit_tree(ev_enr, "E1_D32_TP12", cfg={"tp": 0.12}, fee=0.0030, entry_mode="d31_open")
    tr_e1 = tr_e1.merge(
        ev_m[["c6", "d30_date"] + [c for c in d31_pit_feats if c not in tr_e1.columns]],
        on=["c6", "d30_date"], how="left"
    )
    tr_e1["code"] = tr_e1["c6"].astype(str).str.zfill(6)
    tr_e1["buy_hhmm"] = 925
    tr_e1["exit_hhmm"] = 1500
    tr_e1["is_yizi"] = False

    # Variant A2: D31 Open -> D32 Close (0.30% fee)
    ev_a2 = ev_m[ev_m["d31_buyable"].astype(bool) & ev_m["r31o_d32c_f30"].notna()].copy()
    ev_a2["code"] = ev_a2["c6"].astype(str).str.zfill(6)
    ev_a2["buy_date"] = ev_a2["d31_date"].astype(str).str[:10]
    ev_a2["exit_date"] = ev_a2["exdt_31o_d32c"].astype(str).str[:10]
    ev_a2["net_ret"] = ev_a2["r31o_d32c_f30"].astype(float)
    ev_a2["buy_px"] = ev_a2["f1_ao"].astype(float)
    ev_a2["exit_px"] = ev_a2["f2_ac"].astype(float)
    ev_a2["buy_hhmm"] = 925
    ev_a2["exit_hhmm"] = 1500
    ev_a2["is_yizi"] = False

    # Variant A3: D31 Open -> D33 Close (0.30% fee)
    ev_a3 = ev_m[ev_m["d31_buyable"].astype(bool) & ev_m["r31o_d33c_f30"].notna()].copy()
    ev_a3["code"] = ev_a3["c6"].astype(str).str.zfill(6)
    ev_a3["buy_date"] = ev_a3["d31_date"].astype(str).str[:10]
    ev_a3["exit_date"] = ev_a3["exdt_31o_d33c"].astype(str).str[:10]
    ev_a3["net_ret"] = ev_a3["r31o_d33c_f30"].astype(float)
    ev_a3["buy_px"] = ev_a3["f1_ao"].astype(float)
    ev_a3["exit_px"] = ev_a3["f3_ac"].astype(float)
    ev_a3["buy_hhmm"] = 925
    ev_a3["exit_hhmm"] = 1500
    ev_a3["is_yizi"] = False

    # Variant A4: D30 Close -> D32 Close (0.30% fee, strict <= D30 14:55 features)
    ev_a4 = ev_m[ev_m["d30_buyable"].astype(bool) & ev_m["r30c_d32c_f30"].notna()].copy()
    ev_a4["code"] = ev_a4["c6"].astype(str).str.zfill(6)
    ev_a4["buy_date"] = ev_a4["d30_date"].astype(str).str[:10]
    ev_a4["exit_date"] = ev_a4["exdt_30c_d32c"].astype(str).str[:10]
    ev_a4["net_ret"] = ev_a4["r30c_d32c_f30"].astype(float)
    ev_a4["buy_hhmm"] = 1455
    ev_a4["exit_hhmm"] = 1500
    ev_a4["is_yizi"] = False

    # Variant A5: 10cm only D31 Open -> E1_D32_TP12
    tr_a5 = tr_e1[tr_e1["is_20"] == 0].copy().reset_index(drop=True)

    variants = [
        ("A1_D31_Open_E1TP12", "30d200% D31开盘买+次日冲高12%止盈/收盘出 (全市场)", tr_e1, d31_pit_feats, 60, 40),
        ("A2_D31_Open_D32c", "30d200% D31开盘买->D32收盘出 (全市场)", ev_a2, d31_pit_feats, 60, 40),
        ("A3_D31_Open_D33c", "30d200% D31开盘买->D33收盘出 (全市场)", ev_a3, d31_pit_feats, 60, 40),
        ("A4_D30_Close_D32c", "30d200% D30尾盘买->D32收盘出 (纯<=D30特征)", ev_a4, d30_pit_feats, 50, 35),
        ("A5_D31_10cm_E1TP12", "30d200% 仅10cm主板 D31开盘买+E1TP12", tr_a5, [c for c in d31_pit_feats if c != "is_20"], 45, 30),
    ]

    track_res = {}
    csv_rows = []
    trunc_a = wc.wfe.verify_truncation_zero_leakage(
        tr_e1, d31_pit_feats, mode="A", cutoff="2024-12-31", score_threshold="top20",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=60, min_warmup_trades_rare=40,
        min_warmup_months=18, recalc_freq="daily", top_k=8, min_k=4, fee_rt=0.0030,
    )
    print(f"  [Track A] Truncation 2024-12-31 proof: {trunc_a}")

    for vid, desc, df_v, fcols, mw, mwr in variants:
        res = wc.evaluate_scorecard_with_exact_mtm(
            df_v, fcols, px_lookup, v20_ctx, fee_rt=0.0030,
            wf_start_date="2023-01-03", end_date="2026-11-16",
            min_warmup_trades=mw, min_warmup_trades_rare=mwr, min_warmup_months=18,
            recalc_freq="daily", top_k=8, min_k=4, max_corr=0.65,
            thresholds=("all_cands", "top30", "top20", "top10", 70, 75),
            perm_n=1000, seed=20261125,
        )
        print(f"  [{vid}] start={res['meta']['wf_actual_start']}, cands={len(df_v)}")
        print(res["summary_table"][["threshold", "n_trades", "wr_pct", "plr", "nav_wf", "ex5_wf", "mdd_pct", "sharpe", "nav_2526", "nav_y26", "perm_sd_p", "corr_v20"]].to_string(index=False))

        wf_start = res["meta"]["wf_actual_start"] or "2023-01-03"
        th_out = {}
        for tname, td in res["threshold_results"].items():
            vp = td["v20_empty_patch"]
            th_out[tname] = {
                "metrics": td["metrics"],
                "corr_diag": td["corr_diag"],
                "v20_empty_patch": {
                    "mode1_strict_combined_no_peek": {k: v for k, v in vp["mode1_strict_combined_no_peek"].items() if k != "skipped_v20_trades"},
                    "mode2_empty_slot_standalone": vp["mode2_empty_slot_standalone"],
                } if vp else None,
            }
            if tname in ("all_cands", "top30", "top20", "top10", "abs_70"):
                csv_rows.append(wc.extract_track_row(
                    "TrackA_30d200_Day30_31", vid, desc, tname, 0.0030, wf_start,
                    td["metrics"], vp, td["corr_diag"], trunc_a["zero_leakage_pass"],
                ))

        track_res[vid] = {
            "desc": desc,
            "n_total_cands": int(len(df_v)),
            "wf_actual_start": wf_start,
            "n_daily_rebuilds": res["meta"]["n_rebuilds"],
            "summary_table": res["summary_table"].to_dict("records"),
            "thresholds": th_out,
            "latest_scorecard_factors": [
                {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "budget_pts": f["budget_pts"], "bin_pts": f["bin_pts"], "bin_wr_pct": f["bin_wr_pct"], "bin_mean_pct": f["bin_mean_pct"]}
                for f in (res["meta"]["latest_scorecard"]["factors"] if res["meta"]["latest_scorecard"] else [])
            ],
            "best_slot_df": res["threshold_results"]["top20"]["slot_df"],
        }

    print(f"[Track A DONE in {time.time()-t0:.1f}s]")
    return {"truncation_20241231_proof": trunc_a, "variants": track_res, "csv_rows": csv_rows}


def run_track_b(v20_ctx: dict, mkt_df: pd.DataFrame) -> dict:
    t0 = time.time()
    print("\n=== [Track B] Famous Youzi Bayes LHB Next-Day Divergence WF Scorecard ===")

    import pyarrow as pa

    # 1. Pass 1: Load ONLY minimal pre-filter columns for lhb_on_t1 == 1 (keeps Arrow/Pandas RSS < 300 MB)
    ds_core = ds.dataset(STOCK_CORE_PQ, format="parquet")
    p1_cols = [
        "dt", "c6", "open_pct", "is_20cm", "is_yizi_zt", "is_yizi_dt",
        "lhb_bayes_t2_t1", "lhb_has_good_yz_t1",
    ]
    p1_chunks = []
    for batch in ds_core.scanner(
        columns=p1_cols,
        filter=(ds.field("lhb_on_t1") == 1) & (ds.field("is_st_pit") == 0) & (ds.field("dt") <= "2026-11-17"),
        use_threads=False,
    ).to_batches():
        p1_chunks.append(batch.to_pandas())
    lhb_p1 = pd.concat(p1_chunks, ignore_index=True)
    del p1_chunks
    pa.default_memory_pool().release_unused()
    lhb_p1["dt"] = lhb_p1["dt"].astype(str)
    lhb_p1["c6"] = lhb_p1["c6"].astype(str).str.zfill(6)

    # Map dt -> prev_dt using full benchmark trading calendar
    cal_all = sorted(mkt_df["trade_date"].astype(str).unique().tolist())
    prev_dt_map = {cal_all[i]: cal_all[i - 1] for i in range(1, len(cal_all))}
    lhb_p1["prev_dt"] = lhb_p1["dt"].map(prev_dt_map)

    # Enrich Pass 1 with ths_pit_youzi_5y & bayes_seat_scores_d1_5y strictly on prev_dt (T-1)
    ths = pd.read_parquet(f"{RD016_DIR}/ths_pit_youzi_5y.parquet")
    ths["prev_dt"] = ths["date"].astype(str).str[:10]
    ths["c6"] = ths["stock_code"].astype(str).str.zfill(6)
    ths = ths.sort_values(["prev_dt", "c6", "is_three"]).drop_duplicates(["prev_dt", "c6"], keep="first")
    ths["ths_cap_inflow_yi"] = pd.to_numeric(ths["cap_inflow"], errors="coerce").fillna(0.0) / 1e8
    ths["ths_cap_count"] = pd.to_numeric(ths["cap_count"], errors="coerce").fillna(0.0)
    ths["ths_org_inflow_yi"] = pd.to_numeric(ths["org_inflow"], errors="coerce").fillna(0.0) / 1e8
    ths["ths_org_count"] = pd.to_numeric(ths["org_count"], errors="coerce").fillna(0.0)
    ths["ths_all_inflow_yi"] = pd.to_numeric(ths["all_inflow"], errors="coerce").fillna(0.0) / 1e8

    byz = pd.read_parquet(f"{RD016_DIR}/bayes_seat_scores_d1_5y.parquet")
    byz["prev_dt"] = byz["date"].astype(str).str[:10]
    byz["c6"] = byz["stock_code"].astype(str).str.zfill(6)
    byz["is_net_buy"] = (byz["NET"] > 0).astype(int)
    byz_agg = byz.groupby(["prev_dt", "c6"], as_index=False).agg(
        byz_max_t2=("b_t2", "max"),
        byz_max_c=("b_c", "max"),
        byz_mean_t2=("b_t2", "mean"),
        byz_net_pos_cnt=("is_net_buy", "sum"),
        byz_max_net_yi=("NET", lambda s: float(s.max()) / 1e8),
    )
    del ths["date"], ths["stock_code"], byz
    gc.collect()

    lhb_p1 = lhb_p1.merge(
        ths[["prev_dt", "c6", "is_three", "ths_cap_inflow_yi", "ths_cap_count", "ths_org_inflow_yi", "ths_org_count", "ths_all_inflow_yi"]],
        on=["prev_dt", "c6"], how="left",
    ).merge(byz_agg, on=["prev_dt", "c6"], how="left")
    del ths, byz_agg
    for c in ["ths_cap_inflow_yi", "ths_cap_count", "ths_org_inflow_yi", "ths_org_count", "ths_all_inflow_yi",
              "byz_max_t2", "byz_max_c", "byz_mean_t2", "byz_net_pos_cnt", "byz_max_net_yi", "is_three"]:
        lhb_p1[c] = lhb_p1[c].fillna(0.0).astype(np.float32)

    # Exact Track B union filter BEFORE fetching 52 remaining columns & price history (~77k -> ~8k rows)
    lim_p1 = np.where(lhb_p1["is_20cm"].to_numpy(bool), 0.194, 0.094)
    opct_p1 = lhb_p1["open_pct"].to_numpy(float)
    m_buyable_p1 = (
        (lhb_p1["is_yizi_zt"].to_numpy(int) == 0)
        & (lhb_p1["is_yizi_dt"].to_numpy(int) == 0)
        & np.isfinite(opct_p1)
        & (opct_p1 < lim_p1)
        & (opct_p1 > -lim_p1)
    )
    m_div_p1 = (opct_p1 >= -0.06) & (opct_p1 <= 0.045)
    m_yz_p1 = (
        (lhb_p1["lhb_has_good_yz_t1"].to_numpy(float) == 1)
        | (lhb_p1["lhb_bayes_t2_t1"].to_numpy(float) > 0.002)
        | (lhb_p1["ths_cap_inflow_yi"].to_numpy(float) > 0)
        | (lhb_p1["byz_max_t2"].to_numpy(float) > 0.5)
    )
    lhb_p1 = lhb_p1[m_buyable_p1 & (m_div_p1 | m_yz_p1)].copy().reset_index(drop=True)
    cand_codes = sorted(lhb_p1["c6"].unique().tolist())
    cand_pair_set = set(zip(lhb_p1["c6"], lhb_p1["dt"]))
    min_lhb_dt = str(lhb_p1["dt"].min())
    print(f"  Prefiltered LHB union candidates: {len(lhb_p1)} rows across {len(cand_codes)} codes (min_dt={min_lhb_dt})")

    # Pass 2: Stream remaining feature columns in 2 column-halves & release Arrow pool every batch
    p2_a = [
        "dt", "c6", "open", "close", "adj_factor", "ret_1d", "is_st_pit", "is_zt", "is_dt",
        "mcap_yi_t1", "amount_yi_t1", "ret_1d_t1", "prev_clv", "prev_streak", "prev_is_broken_zt", "prev_is_yizi_zt",
        "overhang_pct_t1", "hr10d_space_t1", "down_streak_t1", "pos_20d_t1", "pos_60d_t1", "pos_250d_t1",
        "dd_20d_t1", "amp_20d_t1", "bias10_t1", "bias20_t1",
    ]
    p2_b = [
        "dt", "c6", "ret_5d_t1", "ret_20d_t1", "vol_ratio5_t1", "turn_5_20_t1", "real_turn_pct_t1",
        "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1", "lhb_has_surf_yz_t1", "lhb_has_quant_t1", "lhb_cnt_5d_t1",
        "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "d1_seal_ratio_t1",
        "waves_3y_g15_t1", "zt_cnt_1y_t1", "max_streak_3y", "cum_turnover_1y", "trap_waves_3y",
        "dd_from_3y_high", "cool_days_since_last_zt", "kpl_in_t1", "kpl_days_30d_t1", "kpl_zt3_t1",
        "csrc_ind_ex5_t1", "csrc_ind_rank20_t1", "abn_notice_30d_pre", "tox_reg_30d_pre",
    ]

    def _stream_p2(cols_sub):
        chunks = []
        for batch in ds_core.scanner(
            columns=cols_sub,
            filter=(ds.field("lhb_on_t1") == 1) & (ds.field("is_st_pit") == 0) & (ds.field("c6").isin(cand_codes)) & (ds.field("dt") <= "2026-11-17"),
            use_threads=False,
        ).to_batches():
            bdf = batch.to_pandas()
            bdf["dt"] = bdf["dt"].astype(str)
            bdf["c6"] = bdf["c6"].astype(str).str.zfill(6)
            keep_m = [((c, d) in cand_pair_set) for c, d in zip(bdf["c6"], bdf["dt"])]
            if any(keep_m):
                chunks.append(bdf[keep_m].copy())
            del bdf, batch
            pa.default_memory_pool().release_unused()
        return pd.concat(chunks, ignore_index=True)

    lhb_p2a = _stream_p2(p2_a)
    lhb_p2b = _stream_p2(p2_b)
    lhb_df = lhb_p1.merge(lhb_p2a, on=["c6", "dt"], how="inner").merge(lhb_p2b, on=["c6", "dt"], how="inner")
    del lhb_p1, lhb_p2a, lhb_p2b
    gc.collect()

    # 2. Stream minimal price bars ONLY within [cand_dt, cand_dt + 20 trading days] via cal_all dict (zero pd.to_datetime copies)
    cal_idx_map = {d: i for i, d in enumerate(cal_all)}
    cand_win_idx = {}
    for c6_v, d_v in zip(lhb_df["c6"], lhb_df["dt"]):
        ci = cal_idx_map.get(d_v)
        if ci is not None:
            cand_win_idx.setdefault(c6_v, []).append(ci)
    cand_win_idx = {k: np.array(sorted(set(v)), dtype=np.int32) for k, v in cand_win_idx.items()}

    px_chunks = []
    for batch in ds_core.scanner(
        columns=["dt", "c6", "open", "close", "adj_factor", "is_yizi_dt", "is_dt"],
        filter=ds.field("c6").isin(cand_codes) & (ds.field("dt") >= min_lhb_dt) & (ds.field("dt") <= "2026-11-25"),
        use_threads=False,
    ).to_batches():
        c6_list = [str(x).zfill(6) for x in batch.column("c6").to_pylist()]
        dt_list = [str(x) for x in batch.column("dt").to_pylist()]
        keep_m = np.zeros(len(c6_list), dtype=bool)
        for idx_r, (c_v, d_v) in enumerate(zip(c6_list, dt_list)):
            arr = cand_win_idx.get(c_v)
            if arr is None:
                continue
            ci = cal_idx_map.get(d_v)
            if ci is None:
                continue
            pos = int(np.searchsorted(arr, ci, side="right")) - 1
            if pos >= 0 and (ci - arr[pos]) <= 15:
                keep_m[idx_r] = True
        if keep_m.any():
            sub_b = batch.filter(pa.array(keep_m)).to_pandas()
            sub_b["dt"] = sub_b["dt"].astype(str)
            sub_b["c6"] = sub_b["c6"].astype(str).str.zfill(6)
            px_chunks.append(sub_b)
        del batch
        pa.default_memory_pool().release_unused()
    px_df = pd.concat(px_chunks, ignore_index=True)
    del px_chunks, cand_win_idx
    gc.collect()
    px_df = px_df.sort_values(["c6", "dt"]).reset_index(drop=True)
    px_df["ao"] = px_df["open"].astype(float) * px_df["adj_factor"].astype(float)
    px_df["ac"] = px_df["close"].astype(float) * px_df["adj_factor"].astype(float)

    # Build lightweight per-stock price arrays WITHOUT per-stock dicts
    stk_arrays = {}
    for c6, g in px_df.groupby("c6", sort=False):
        stk_arrays[c6] = (
            g["dt"].to_numpy(),
            g["ao"].to_numpy(float),
            g["ac"].to_numpy(float),
            g["is_yizi_dt"].to_numpy(bool),
            g["is_dt"].to_numpy(bool),
        )
    del px_df
    gc.collect()

    # Merge strictly T-1 & 09:25 market features
    mkt_keep = [
        "trade_date", "L1_zt_cnt_t1", "L1_dt_cnt_t1", "L1_zb_rate_t1", "L1_max_board_t1",
        "L1_duanban_damian_t1", "L1_sent_phase_t1", "L1_ew_bias20_t1",
        "mkt_0925_zt_cnt", "mkt_0925_dt_cnt", "mkt_0925_avg_gap_pct", "mkt_amt_tril_t1",
    ]
    lhb_df = lhb_df.merge(mkt_df[mkt_keep], left_on="dt", right_on="trade_date", how="left")

    # 4. Compute exact T+1 close (hold_bars=1 after buy_date) & T+2 close exits with limit-down deferral
    def _attach_exit(df_in: pd.DataFrame, hold_td: int = 1) -> pd.DataFrame:
        # hold_td = 1 means buy on day t (pos) open, exit on pos+1 close (T+2 in LHB terms)
        ex_dts, bpxs, epxs, grets, valids = [], [], [], [], []
        for r in df_in[["c6", "dt", "is_20cm", "is_yizi_zt", "is_yizi_dt", "open_pct"]].itertuples(index=False, name=None):
            c6, dt_v, is20, yz_zt, yz_dt, opct = r
            lim = 0.194 if is20 else 0.094
            if yz_zt or yz_dt or not np.isfinite(opct) or opct >= lim or opct <= -lim:
                ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan); valids.append(False)
                continue
            tup = stk_arrays.get(c6)
            if tup is None:
                ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan); valids.append(False)
                continue
            dts_s, ao_s, ac_s, yz_dt_s, dt_s = tup
            pos = int(np.searchsorted(dts_s, dt_v))
            if pos >= len(dts_s) or dts_s[pos] != dt_v or pos + hold_td >= len(dts_s):
                ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan); valids.append(False)
                continue
            b_px = ao_s[pos]
            if not (np.isfinite(b_px) and b_px > 0):
                ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan); valids.append(False)
                continue
            ex_pos = pos + hold_td
            # Defer if limit-down locked (or dt) up to +6 trading days
            while ex_pos < len(dts_s) - 1 and ex_pos < pos + hold_td + 6 and (yz_dt_s[ex_pos] or dt_s[ex_pos]):
                ex_pos += 1
            e_px = ac_s[ex_pos]
            if not (np.isfinite(e_px) and e_px > 0):
                ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan); valids.append(False)
                continue
            ex_dts.append(str(dts_s[ex_pos]))
            bpxs.append(float(b_px))
            epxs.append(float(e_px))
            grets.append(float(e_px / b_px - 1.0))
            valids.append(True)

        out = df_in.copy()
        out["buy_date"] = out["dt"]
        out["code"] = out["c6"]
        out["exit_date"] = ex_dts
        out["buy_px"] = bpxs
        out["exit_px"] = epxs
        out["gross_ret"] = grets
        out["buy_hhmm"] = 925
        out["exit_hhmm"] = 1500
        out["is_yizi"] = False
        out["can_buy"] = valids
        return out[out["can_buy"]].copy().reset_index(drop=True)

    b_t1 = _attach_exit(lhb_df, hold_td=1)
    b_t2 = _attach_exit(lhb_df, hold_td=2)

    # Populate px_lookup ONLY for (c6, d) spans covered by b_t1 / b_t2 with d >= 2023-01-01
    px_lookup = {}
    for df_span in (b_t1, b_t2):
        for c6_v, bdt_v, edt_v in zip(df_span["c6"], df_span["buy_date"], df_span["exit_date"]):
            if edt_v < "2023-01-01":
                continue
            tup = stk_arrays.get(c6_v)
            if tup is None:
                continue
            dts_s, ao_s, ac_s, _, _ = tup
            bi = int(np.searchsorted(dts_s, bdt_v))
            ei = int(np.searchsorted(dts_s, edt_v))
            if bi >= len(dts_s) or dts_s[bi] != bdt_v or ei >= len(dts_s) or dts_s[ei] != edt_v:
                continue
            for k in range(bi, ei + 1):
                dk = str(dts_s[k])
                if dk >= "2023-01-01" and (c6_v, dk) not in px_lookup:
                    px_lookup[(c6_v, dk)] = (float(ao_s[k]), float(ac_s[k]))
    del stk_arrays, lhb_df
    gc.collect()

    feature_cols = [
        "lhb_bayes_t2_t1", "byz_max_t2", "byz_max_c", "byz_mean_t2", "byz_net_pos_cnt", "byz_max_net_yi",
        "ths_cap_inflow_yi", "ths_cap_count", "ths_org_inflow_yi", "ths_org_count", "ths_all_inflow_yi", "is_three",
        "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1", "lhb_has_good_yz_t1", "lhb_has_surf_yz_t1", "lhb_has_quant_t1", "lhb_cnt_5d_t1",
        "open_pct", "is_20cm", "mcap_yi_t1", "amount_yi_t1", "ret_1d_t1", "prev_clv", "prev_streak", "prev_is_broken_zt",
        "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "d1_seal_ratio_t1",
        "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "dd_20d_t1", "amp_20d_t1", "bias10_t1", "ret_5d_t1", "ret_20d_t1",
        "vol_ratio5_t1", "turn_5_20_t1", "real_turn_pct_t1",
        "waves_3y_g15_t1", "zt_cnt_1y_t1", "max_streak_3y", "trap_waves_3y", "cool_days_since_last_zt",
        "kpl_in_t1", "kpl_days_30d_t1", "kpl_zt3_t1", "csrc_ind_ex5_t1", "csrc_ind_rank20_t1",
        "abn_notice_30d_pre", "tox_reg_30d_pre",
        "L1_zt_cnt_t1", "L1_dt_cnt_t1", "L1_zb_rate_t1", "L1_duanban_damian_t1", "L1_sent_phase_t1",
        "mkt_0925_zt_cnt", "mkt_0925_avg_gap_pct",
    ]

    # Sub-pools for Track B:
    # B1: Full market LHB Divergence (-6% <= open_pct <= +4.5%)
    m_div = (b_t1["open_pct"] >= -0.06) & (b_t1["open_pct"] <= 0.045)
    m_yz = (b_t1["lhb_has_good_yz_t1"] == 1) | (b_t1["lhb_bayes_t2_t1"] > 0.002) | (b_t1["ths_cap_inflow_yi"] > 0) | (b_t1["byz_max_t2"] > 0.5)
    b1_all_div = b_t1[m_div].copy().reset_index(drop=True)
    b2_yz_div = b_t1[m_div & m_yz].copy().reset_index(drop=True)
    b3_yz_10cm = b_t1[m_div & m_yz & (b_t1["is_20cm"] == 0)].copy().reset_index(drop=True)
    b4_yz_all_open = b_t1[m_yz].copy().reset_index(drop=True)

    m_div2 = (b_t2["open_pct"] >= -0.06) & (b_t2["open_pct"] <= 0.045)
    m_yz2 = (b_t2["lhb_has_good_yz_t1"] == 1) | (b_t2["lhb_bayes_t2_t1"] > 0.002) | (b_t2["ths_cap_inflow_yi"] > 0) | (b_t2["byz_max_t2"] > 0.5)
    b5_yz_div_t2 = b_t2[m_div2 & m_yz2].copy().reset_index(drop=True)
    del b_t1, b_t2
    gc.collect()

    print(f"  Pool sizes: B1_all_div={len(b1_all_div)}, B2_yz_div={len(b2_yz_div)}, B3_yz_10cm={len(b3_yz_10cm)}, B4_yz_all={len(b4_yz_all_open)}, B5_yz_t2={len(b5_yz_div_t2)}")

    # Physical truncation 2024-12-31 on B2_yz_div (daily recalc)
    trunc_b = wc.wfe.verify_truncation_zero_leakage(
        b2_yz_div, feature_cols, mode="A", cutoff="2024-12-31", score_threshold="top10",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=120, min_warmup_trades_rare=80,
        min_warmup_months=18, recalc_freq="daily", top_k=12, min_k=5, fee_rt=0.0030, gross_ret_col="gross_ret",
    )
    print(f"  [Track B] Truncation 2024-12-31 proof: {trunc_b}")

    variants = [
        ("B1_All_LHB_Div_T1c", "全市场非一字LHB次日分歧(-6%~+4.5%)买->次日收盘出", b1_all_div, "monthly"),
        ("B2_YouziBayes_Div_T1c", "大游资/贝叶斯正席位LHB次日分歧(-6%~+4.5%)买->次日收盘出", b2_yz_div, "daily"),
        ("B3_YouziBayes_10cm_Div", "10cm主板大游资/贝叶斯次日分歧(-6%~+4.5%)买->次日收盘出", b3_yz_10cm, "daily"),
        ("B4_YouziBayes_AllOpen", "大游资/贝叶斯LHB全非一字开盘买->次日收盘出", b4_yz_all_open, "daily"),
        ("B5_YouziBayes_Div_H3d", "大游资/贝叶斯LHB次日分歧买->T+2收盘(3天)出", b5_yz_div_t2, "daily"),
    ]

    track_res = {}
    csv_rows = []
    for vid, desc, df_v, rf in variants:
        res = wc.evaluate_scorecard_with_exact_mtm(
            df_v, feature_cols, px_lookup, v20_ctx, fee_rt=0.0030, gross_ret_col="gross_ret",
            wf_start_date="2023-01-03", end_date="2026-11-16",
            min_warmup_trades=120, min_warmup_trades_rare=80, min_warmup_months=18,
            recalc_freq=rf, top_k=12, min_k=5, max_corr=0.65,
            thresholds=("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80),
            perm_n=1000, seed=20261125,
        )
        print(f"  [{vid}] ({rf}) start={res['meta']['wf_actual_start']}, cands={len(df_v)}")
        print(res["summary_table"][["threshold", "n_trades", "wr_pct", "plr", "nav_wf", "ex5_wf", "mdd_pct", "sharpe", "nav_2526", "nav_y26", "perm_sd_p", "corr_v20"]].to_string(index=False))

        wf_start = res["meta"]["wf_actual_start"] or "2023-01-03"
        th_out = {}
        for tname, td in res["threshold_results"].items():
            vp = td["v20_empty_patch"]
            th_out[tname] = {
                "metrics": td["metrics"],
                "corr_diag": td["corr_diag"],
                "v20_empty_patch": {
                    "mode1_strict_combined_no_peek": {k: v for k, v in vp["mode1_strict_combined_no_peek"].items() if k != "skipped_v20_trades"},
                    "mode2_empty_slot_standalone": vp["mode2_empty_slot_standalone"],
                } if vp else None,
            }
            if tname in ("all_cands", "top20", "top10", "top5", "abs_75"):
                csv_rows.append(wc.extract_track_row(
                    "TrackB_Youzi_LHB_Div", vid, desc, tname, 0.0030, wf_start,
                    td["metrics"], vp, td["corr_diag"], trunc_b["zero_leakage_pass"],
                ))

        track_res[vid] = {
            "desc": desc,
            "recalc_freq": rf,
            "n_total_cands": int(len(df_v)),
            "wf_actual_start": wf_start,
            "n_daily_rebuilds": res["meta"]["n_rebuilds"],
            "summary_table": res["summary_table"].to_dict("records"),
            "thresholds": th_out,
            "latest_scorecard_factors": [
                {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "budget_pts": f["budget_pts"], "bin_pts": f["bin_pts"], "bin_wr_pct": f["bin_wr_pct"], "bin_mean_pct": f["bin_mean_pct"]}
                for f in (res["meta"]["latest_scorecard"]["factors"] if res["meta"]["latest_scorecard"] else [])
            ],
            "best_slot_df": res["threshold_results"]["top10"]["slot_df"],
        }
        del res
        gc.collect()

    print(f"[Track B DONE in {time.time()-t0:.1f}s]")
    return {"truncation_20241231_proof": trunc_b, "variants": track_res, "csv_rows": csv_rows}


def main():
    t_all = time.time()
    v20_ctx = wc.wfp.load_v20_reference_context(wc.WAVE1_DIR)
    mkt_df = pd.read_parquet(MKT_PIT_PQ)

    res_a = run_track_a(v20_ctx, mkt_df)
    res_a["variants"]["A1_D31_Open_E1TP12"]["best_slot_df"].drop(columns=["mtm_segs"], errors="ignore").to_parquet(
        f"{wc.CACHE_DIR}/track_a_best_slot.parquet", index=False
    )
    for v in res_a["variants"].values():
        v.pop("best_slot_df", None)
    gc.collect()

    res_b = run_track_b(v20_ctx, mkt_df)
    res_b["variants"]["B2_YouziBayes_Div_T1c"]["best_slot_df"].drop(columns=["mtm_segs"], errors="ignore").to_parquet(
        f"{wc.CACHE_DIR}/track_b_best_slot.parquet", index=False
    )
    for v in res_b["variants"].values():
        v.pop("best_slot_df", None)

    import resource
    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)
    out = wc.sanitize_json({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t_all, 2),
        "peak_rss_mb": rss_mb,
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "track_a": res_a,
        "track_b": res_b,
    })
    with open(f"{wc.CACHE_DIR}/w2b5_track_ab.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"\n[ALL TRACK A+B DONE in {time.time()-t_all:.1f}s | Peak RSS={rss_mb} MB]")


if __name__ == "__main__":
    main()
