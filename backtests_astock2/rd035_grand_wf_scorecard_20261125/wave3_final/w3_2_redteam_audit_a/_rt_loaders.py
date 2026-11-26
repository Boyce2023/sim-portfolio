#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Read-only trade ledger loaders & parity verifiers for RD035 Wave 3-2 Red Team Audit A."""
import gc, json, os, pickle, sys
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1 = f"{RD035}/wave1_base"
W2A2 = f"{RD035}/wave2a/w2a2_old_3to4_high_pry"
W2A3 = f"{RD035}/wave2a/w2a3_old_20cm"
W2A4 = f"{RD035}/wave2a/w2a4_pairwise_interactions"
W2B1 = f"{RD035}/wave2b/w2b1_20cm_surge10_19_scorecard"
W2B4 = f"{RD035}/wave2b/w2b4_20cm_new_archetypes_scorecard"
W2B5 = f"{RD035}/wave2b/w2b5_event_crossmarket_lowcorr_scorecard"
W2B6 = f"{RD035}/wave2b/w2b6_empty_slot_blind_and_crossseat"


def _std(df: pd.DataFrame, base_fee: float, tag: str) -> pd.DataFrame:
    d = df.copy().reset_index(drop=True)
    d["buy_date"] = d["buy_date"].astype(str).str[:10]
    d["exit_date"] = d["exit_date"].astype(str).str[:10]
    d["code"] = d["code"].astype(str).str.zfill(6)
    d["net_ret"] = pd.to_numeric(d["net_ret"], errors="coerce").astype(float)
    if "gross_ret" in d.columns and d["gross_ret"].notna().all():
        d["gross_ret"] = pd.to_numeric(d["gross_ret"], errors="coerce").astype(float)
    elif "strategy" in d.columns and tag == "2b_w2a4_V20Comb_MechNative_d10":
        bf = np.where(d["strategy"] == "20cm", 0.0030, 0.0020)
        d["gross_ret"] = (1.0 + d["net_ret"]) / (1.0 - bf) - 1.0
    elif "strategy" in d.columns and tag == "2c_w2a4_Road2_Melee":
        bf = np.where(d["strategy"] == "20cm", 0.0030, 0.0020)
        d["gross_ret"] = (1.0 + d["net_ret"]) / (1.0 - bf) - 1.0
    else:
        d["gross_ret"] = (1.0 + d["net_ret"]) / (1.0 - base_fee) - 1.0
    d["base_fee"] = float(base_fee)
    d["variant_key"] = tag
    return d


def load_w2a3_ledgers() -> dict[str, pd.DataFrame]:
    sys.path.insert(0, W2A3)
    import w2a3_lib as lib
    import _wf_sim_and_metrics as wfm

    p20, meta = lib.load_w2a3_data()
    df_h = wfm.prepare_hygiene_and_net_ret(p20, fee_rt=0.0030)
    df_h["wf_in_window"] = df_h["buy_date"] >= "2023-01-03"
    f6 = df_h["s20cm_F06_inst_net_pos"].to_numpy(float)
    mkt10 = df_h["mkt10_zt_est_t1"].to_numpy(float)
    df_h["v20_cold50"] = np.where(mkt10 < 50.0, df_h["v20_score"].to_numpy(float) - f6, df_h["v20_score"].to_numpy(float))
    feat_delta_auc = list(dict.fromkeys(meta["entry_num"] + meta["xtr_fixed"] + meta["auc_cols"]))

    sc_c50, _ = lib.run_causal_scorecard_ext(
        df_h, feat_delta_auc, mode="delta_patch", wf_start_date="2023-01-03",
        min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
        shrink_tau=20.0, max_delta=15, orig_score_col="v20_cold50", max_corr_orig=0.70,
        min_discrete_bin_cnt=15,
    )
    _, sl_f06 = wfm.select_single_slot_trades(df_h, score_col="v20_cold50", threshold=80.0, wf_only=True)
    _, sl_s80 = wfm.select_single_slot_trades(sc_c50, score_col="wf_score", threshold=80.0, wf_only=True)
    _, sl_b82 = wfm.select_single_slot_trades(df_h, score_col="v20_score", threshold=82.0, wf_only=True)
    _, sl_b80 = wfm.select_single_slot_trades(df_h, score_col="v20_score", threshold=80.0, wf_only=True)
    sl_s84 = pd.read_parquet(f"{W2A3}/w2a3_best_trades.parquet")

    del p20, df_h, sc_c50
    gc.collect()
    return {
        "1a_w2a3_F06_COLD50_thr80": _std(sl_f06, 0.0030, "1a_w2a3_F06_COLD50_thr80"),
        "1b_w2a3_CLEAN_B_cold50_d15_S84": _std(sl_s84, 0.0030, "1b_w2a3_CLEAN_B_cold50_d15_S84"),
        "1c_w2a3_CLEAN_B_cold50_d15_S80": _std(sl_s80, 0.0030, "1c_w2a3_CLEAN_B_cold50_d15_S80"),
        "1r_w2a3_BASE_V11_S82": _std(sl_b82, 0.0030, "1r_w2a3_BASE_V11_S82"),
        "1r_w2a3_BASE_V11_S80": _std(sl_b80, 0.0030, "1r_w2a3_BASE_V11_S80"),
    }


def load_w2a4_ledgers() -> dict[str, pd.DataFrame]:
    s20 = pd.read_parquet(f"{W2A4}/w2a4_best_20cm_standalone_trades.parquet")
    comb = pd.read_parquet(f"{W2A4}/w2a4_best_trades.parquet")
    r2 = pd.read_parquet(f"{W2A4}/w2a4_best_road2_trades.parquet")
    v20 = pd.read_parquet(f"{WAVE1}/v20_baseline_ledger_278.parquet")
    v20_wf = v20[v20["buy_date"] >= "2023-01-03"].copy()
    return {
        "2a_w2a4_20cm_MechNative_d15": _std(s20, 0.0030, "2a_w2a4_20cm_MechNative_d15"),
        "2b_w2a4_V20Comb_MechNative_d10": _std(comb, 0.0030, "2b_w2a4_V20Comb_MechNative_d10"),
        "2c_w2a4_Road2_Melee": _std(r2, 0.0030, "2c_w2a4_Road2_Melee"),
        "2r_V20_Baseline_WF": _std(v20_wf, 0.0020, "2r_V20_Baseline_WF"),
    }


def load_w2a2_ledgers() -> dict[str, pd.DataFrame]:
    sys.path.insert(0, W2A2)
    import _w2a2_common as cm
    import run_w2a2_modules_1_to_4 as r14
    import wf_scorecard_engine as wf

    bt = pd.read_parquet(f"{W2A2}/w2a2_best_trades.parquet")
    v20_ctx = wf.load_v20_reference_context(WAVE1)
    pm34, _ = cm.load_master_pool_with_exec("3to4")
    fg34 = cm.get_feature_groups(pm34, "3to4")
    _, m4_det = r14.run_module4_minefield_dragon(
        "3to4", pm34, fg34["all_with_native"], v20_ctx, mine_loss_thr=-0.07,
        blacklist_qs=(15,), use_declustered=True, wf_start_date="2023-01-03",
    )
    sc34 = m4_det["scored_df"].copy()
    is_blk = sc34["wf_mine_score"] >= sc34["wf_mine_thr_15"]
    sc34["can_buy_hygiene"] = sc34["can_buy_hygiene"] & (~is_blk.fillna(False))
    _, sl_m4 = cm.sim_strategy_custom("3to4", sc34, "orig_score", cm.ORIG_THRESHOLDS["3to4"], wf_only=True)

    return {
        "3a_w2a2_3to4_M4_MineBL15_Orig": _std(sl_m4, 0.0030, "3a_w2a2_3to4_M4_MineBL15_Orig"),
        "3r_w2a2_3to4_baseline_wf": _std(bt[bt["variant_tag"] == "3to4_baseline_wf"], 0.0030, "3r_w2a2_3to4_baseline_wf"),
        "3b_w2a2_pry_M1_WF_DropNeg_tm05": _std(bt[bt["variant_tag"] == "pry_M1_WF_DropNeg_tm05"], 0.0030, "3b_w2a2_pry_M1_WF_DropNeg_tm05"),
        "3r_w2a2_pry_baseline_wf": _std(bt[bt["variant_tag"] == "pry_baseline_wf"], 0.0030, "3r_w2a2_pry_baseline_wf"),
        "3c_w2a2_3to4_M2_XTR_ModeB_d10": _std(bt[bt["variant_tag"] == "3to4_M2_XTR_ModeB_d10"], 0.0030, "3c_w2a2_3to4_M2_XTR_ModeB_d10"),
        "3d_w2a2_high_relax_best_wf": _std(bt[bt["variant_tag"] == "high_relax_best_wf"], 0.0030, "3d_w2a2_high_relax_best_wf"),
    }


def load_w2b5_ledgers() -> dict[str, pd.DataFrame]:
    sys.path.insert(0, W2B5)
    import _w2b5_common as wc
    import run_w2b5_track_c as tc

    v20_ctx = wc.wfp.load_v20_reference_context(WAVE1)
    etf_df = wc.build_or_load_clean_etf_cache()
    mkt_df = pd.read_parquet(f"{WAVE1}/market_daily_all_new_factors_pit.parquet")
    esub = etf_df[etf_df["code"] == "512100"].sort_values("date").reset_index(drop=True)
    esub = esub.merge(mkt_df[["trade_date", "nt_v3_score_live_t1", "nt_v3_score_eod_t1"]], left_on="date", right_on="trade_date", how="left")
    sig_m = (esub["nt_v3_score_eod_t1"].fillna(0.0) >= 60.0).to_numpy(bool)
    y_open = tc._sim_yield_to_v20(esub, sig_m, v20_ctx, wf_start_dt="2023-01-03", end_dt="2026-11-16", max_hold_td=10, yield_scope="open_0925_only", fee_rt=0.0005)
    c_best = pd.read_parquet(f"{W2B5}/w2b5_best_trades.parquet")

    # Rebuild D1_BW1_Fut120Brk_H5 cleanly (same logic as run_w2b5_track_d.py)
    comm_dir = f"{SIM}/output/extreme_commodities_3ring_backtest_20261125"
    with open(f"{comm_dir}/three_ring_mapping.json", encoding="utf-8") as f:
        trm = json.load(f)
    stock_map = {}
    for sym, info in trm["commodities"].items():
        drv = info.get("driver", sym)
        for tier, key in ((1, "ring1"), (2, "ring2"), (3, "ring3")):
            for tk in info.get(key, []):
                c6 = str(tk)[:6].zfill(6)
                if c6 not in stock_map or tier < stock_map[c6][0]:
                    stock_map[c6] = (tier, sym, drv)
    mapped_codes = sorted(stock_map.keys())
    cf = pd.read_parquet(f"{comm_dir}/data_cache/cn_futures_close.parquet")
    gf = pd.read_parquet(f"{comm_dir}/data_cache/global_futures_close.parquet")
    all_fut = pd.concat([cf, gf], axis=1).sort_index()
    all_fut.index = pd.to_datetime(all_fut.index).strftime("%Y-%m-%d")
    all_fut = all_fut[all_fut.index >= "2015-01-01"].copy()
    used_drivers = sorted(set(v[2] for v in stock_map.values() if v[2] in all_fut.columns))
    cal_ts = pd.DataFrame({"dt": sorted(mkt_df["trade_date"].astype(str).unique()), "dt_ts": pd.to_datetime(sorted(mkt_df["trade_date"].astype(str).unique()))}).sort_values("dt_ts")
    drv_panels = {}
    for drv in used_drivers:
        s = all_fut[drv].dropna()
        if len(s) < 150:
            continue
        hi120 = s.rolling(120, min_periods=60).max().shift(1)
        brk120 = (s / hi120 - 1.0) * 100.0
        hit20 = (brk120 >= 0.0).rolling(20, min_periods=1).max()
        vals = s.to_numpy(float)
        pct5y = np.full(len(vals), np.nan)
        for i in range(180, len(vals)):
            pct5y[i] = float(np.mean(vals[max(0, i - 1259) : i + 1] <= vals[i]))
        df_d = pd.DataFrame({"fut_ts": pd.to_datetime(s.index), "fut_ret5": (s.pct_change(5) * 100.0).values, "fut_ret20": (s.pct_change(20) * 100.0).values, "fut_ret60": (s.pct_change(60) * 100.0).values, "fut_brk120": brk120.values, "fut_hit120_20d": hit20.values, "fut_pct5y": pct5y}).sort_values("fut_ts")
        drv_panels[drv] = pd.merge_asof(cal_ts, df_d, left_on="dt_ts", right_on="fut_ts", direction="backward", allow_exact_matches=False).set_index("dt")[["fut_ret5", "fut_ret20", "fut_ret60", "fut_brk120", "fut_hit120_20d", "fut_pct5y"]]

    cols = ["dt", "c6", "open", "close", "adj_factor", "ret_1d", "open_pct", "is_st_pit", "is_20cm", "is_yizi_zt", "is_yizi_dt", "is_dt", "mcap_yi_t1", "amount_yi_t1", "ret_1d_t1", "ret_5d_t1", "ret_20d_t1", "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "dd_20d_t1", "amp_20d_t1", "vol_ratio5_t1", "turn_5_20_t1", "real_turn_pct_t1", "down_streak_t1", "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "ir_cnt_30d_pre", "abn_notice_30d_pre"]
    st_df = ds.dataset(f"{WAVE1}/stock_day_core_features_pit.parquet").scanner(columns=cols, filter=ds.field("c6").isin(mapped_codes) & (ds.field("dt") <= "2026-11-25")).to_table().to_pandas()
    st_df["dt"] = st_df["dt"].astype(str)
    st_df["c6"] = st_df["c6"].astype(str).str.zfill(6)
    st_df = st_df.sort_values(["c6", "dt"]).reset_index(drop=True)
    st_df["ao"] = st_df["open"].astype(float) * st_df["adj_factor"].astype(float)
    st_df["ac"] = st_df["close"].astype(float) * st_df["adj_factor"].astype(float)
    st_df["stk_ret60_t1"] = ((st_df.groupby("c6", sort=False)["ac"].shift(1) / st_df.groupby("c6", sort=False)["ac"].shift(61) - 1.0) * 100.0).astype(np.float32)
    st_df["comm_ring_tier"] = [stock_map[c][0] for c in st_df["c6"]]
    st_df["driver"] = [stock_map[c][2] for c in st_df["c6"]]
    fut_all = pd.concat([fdf.reset_index().assign(driver=drv) for drv, fdf in drv_panels.items()], ignore_index=True)
    st_df = st_df.merge(fut_all, on=["driver", "dt"], how="left")
    st_df["lag_spread_20d"] = st_df["fut_ret20"] - st_df["ret_20d_t1"]
    st_df["lag_spread_60d"] = st_df["fut_ret60"] - st_df["stk_ret60_t1"]
    st_df = st_df.merge(mkt_df[["trade_date", "L1_sent_phase_t1", "L1_zt_cnt_t1", "L1_ew_bias20_t1", "mkt_pct_above_ma20_t1", "comm_cu_au_ratio_ret20_t1", "us_dxy_ret5d_on", "comm_bdi_ret20_t1"]], left_on="dt", right_on="trade_date", how="left")
    stk_arrays = {c6: (g["dt"].to_numpy(), {d: i for i, d in enumerate(g["dt"].to_numpy())}, g["ao"].to_numpy(float), g["ac"].to_numpy(float), g["is_yizi_dt"].to_numpy(bool), g["is_dt"].to_numpy(bool)) for c6, g in st_df.groupby("c6", sort=False)}
    cand = st_df[(st_df["fut_hit120_20d"] >= 1.0) & (st_df["stk_ret60_t1"] < 15.0) & (st_df["comm_ring_tier"].isin([1, 2]))].copy()
    lim = np.where(cand["is_20cm"] == 1, 0.194, 0.094)
    cand = cand[(cand["is_st_pit"] == 0) & (cand["is_yizi_zt"] == 0) & (cand["is_yizi_dt"] == 0) & cand["open_pct"].notna() & (cand["open_pct"] < lim) & (cand["open_pct"] > -lim)].copy().reset_index(drop=True)
    ex_dts, bpxs, epxs, grets, ok = [], [], [], [], []
    for c6, dv in zip(cand["c6"], cand["dt"]):
        dts_s, d_map, ao_s, ac_s, yz_dt, dt_s = stk_arrays[c6]
        pos = d_map.get(dv)
        if pos is None or pos + 4 >= len(dts_s) or not (np.isfinite(ao_s[pos]) and ao_s[pos] > 0):
            ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan); ok.append(False); continue
        ep = pos + 4
        while ep < len(dts_s) - 1 and ep < pos + 10 and (yz_dt[ep] or dt_s[ep]):
            ep += 1
        if not (np.isfinite(ac_s[ep]) and ac_s[ep] > 0):
            ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan); ok.append(False); continue
        ex_dts.append(str(dts_s[ep])); bpxs.append(float(ao_s[pos])); epxs.append(float(ac_s[ep])); grets.append(float(ac_s[ep] / ao_s[pos] - 1.0)); ok.append(True)
    cand["buy_date"], cand["code"], cand["exit_date"], cand["buy_px"], cand["exit_px"], cand["gross_ret"] = cand["dt"], cand["c6"], ex_dts, bpxs, epxs, grets
    cand = cand[pd.Series(ok).values & (cand["exit_date"] > cand["buy_date"])].copy().reset_index(drop=True)
    fcols = ["comm_ring_tier", "fut_ret5", "fut_ret20", "fut_ret60", "fut_brk120", "fut_hit120_20d", "fut_pct5y", "stk_ret60_t1", "ret_20d_t1", "ret_5d_t1", "ret_1d_t1", "lag_spread_20d", "lag_spread_60d", "open_pct", "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "dd_20d_t1", "amp_20d_t1", "vol_ratio5_t1", "turn_5_20_t1", "real_turn_pct_t1", "down_streak_t1", "mcap_yi_t1", "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "ir_cnt_30d_pre", "abn_notice_30d_pre", "L1_sent_phase_t1", "L1_zt_cnt_t1", "mkt_pct_above_ma20_t1", "comm_cu_au_ratio_ret20_t1", "us_dxy_ret5d_on"]
    res_d1 = wc.wfe.run_wf_scorecard_new_strategy(cand, fcols, v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date="2026-11-16", min_warmup_trades=100, min_warmup_trades_rare=60, min_warmup_months=18, recalc_freq="daily", top_k=10, min_k=4, max_corr=0.65, fee_rt=0.0030, gross_ret_col="gross_ret", thresholds=("top30", "top10"), eval_v20_patch=False, perm_n=10)
    d1_t30 = res_d1["threshold_results"]["top30"]["slot_df"]
    d1_t10 = res_d1["threshold_results"]["top10"]["slot_df"]
    del st_df, cand, stk_arrays
    gc.collect()
    return {
        "4a_w2b5_512100_V3EOD_YieldAllV20": _std(c_best, 0.0005, "4a_w2b5_512100_V3EOD_YieldAllV20"),
        "4a2_w2b5_512100_V3EOD_YieldOpen0925": _std(y_open["patch_trades"], 0.0005, "4a2_w2b5_512100_V3EOD_YieldOpen0925"),
        "4b_w2b5_D1_BW1_H5_top30": _std(d1_t30, 0.0030, "4b_w2b5_D1_BW1_H5_top30"),
        "4c_w2b5_D1_BW1_H5_top10": _std(d1_t10, 0.0030, "4c_w2b5_D1_BW1_H5_top10"),
    }


def load_w2b6_ledgers() -> dict[str, pd.DataFrame]:
    e3 = pd.read_parquet(f"{W2B6}/w2b6_best_trades.parquet")
    with open(f"{W2B6}/_modE_results.pkl", "rb") as f:
        dE = pickle.load(f)["results"]
    with open(f"{W2B6}/_modC_results.pkl", "rb") as f:
        dC = pickle.load(f)
    with open(f"{W2B6}/_modB_results.pkl", "rb") as f:
        dB = pickle.load(f)
    mE = {r["track_id"]: r["best_slot_df"] for r in dE}
    mC = {r["track_id"]: r["best_slot_df"] for r in dC}
    mB = {r["track_id"]: r["best_slot_df"] for r in dB}
    return {
        "5a_w2b6_ModE_E3_Mingmen_H1_top5": _std(e3, 0.0030, "5a_w2b6_ModE_E3_Mingmen_H1_top5"),
        "5a2_w2b6_ModE_E3b_NoZT_H1_top10": _std(mE["ModE_E3b_Mingmen_NoZT_H1"], 0.0030, "5a2_w2b6_ModE_E3b_NoZT_H1_top10"),
        "5b_w2b6_ModC_C1_EarnPre_H3_top20": _std(mC["ModC_C1_EarnPre_NoRun_H3"], 0.0030, "5b_w2b6_ModC_C1_EarnPre_H3_top20"),
        "5b2_w2b6_ModC_C1_EarnPre_H1_top10": _std(mC["ModC_C1_EarnPre_NoRun_H1"], 0.0030, "5b2_w2b6_ModC_C1_EarnPre_H1_top10"),
        "5c_w2b6_ModB_B1_IR_H3_abs70": _std(mB["ModB_B1_IR_AllClean_H3"], 0.0030, "5c_w2b6_ModB_B1_IR_H3_abs70"),
        "5c2_w2b6_ModB_B1_IR_H5_abs75": _std(mB["ModB_B1_IR_AllClean_H5"], 0.0030, "5c2_w2b6_ModB_B1_IR_H5_abs75"),
    }


def load_w2b4_and_w2b1_ledgers() -> dict[str, pd.DataFrame]:
    sys.path.insert(0, W2B4)
    import w2b4_lib as lib4
    import w2b4_run_all as ra4

    a5_80 = pd.read_parquet(f"{W2B4}/w2b4_best_trades.parquet")
    a1_75 = pd.read_parquet(f"{W2B4}/w2b4_best_a1_abs75_trades.parquet")
    mdf, all_fcols, _ = lib4.build_w2b4_candidate_pool("2026-11-16")
    pure_stk, _ = ra4.get_feature_scopes(all_fcols)
    sub_df, vf_cols = lib4.prepare_track_df(mdf, mdf["track_A"].to_numpy(bool), exit_mode="v11", end_dt="2026-11-16", all_feat_cols=pure_stk)
    df_h = lib4.wfm.prepare_hygiene_and_net_ret(sub_df, fee_rt=0.0030, gross_ret_col="gross_ret")
    sc4, _ = lib4.wfc.run_expanding_scorecard_loop(
        df_h, feature_cols=vf_cols, mode="scorecard_0_100", wf_start_date="2023-01-03",
        min_warmup_trades=80, min_warmup_trades_rare=60, min_warmup_months=18,
        recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
    )
    _, a5_85 = lib4.wfm.select_single_slot_trades(sc4, score_col="wf_score", threshold=85.0, wf_only=True)
    del mdf, sub_df, df_h, sc4
    gc.collect()
    pa.default_memory_pool().release_unused()

    sys.path.insert(0, W2B1)
    import w2b1_core_lib as lib1
    import w2b1_mine_and_dragon as md1
    import wf_scorecard_engine as wf1

    df1 = pd.read_parquet(f"{W2B1}/w2b1_cand_pool_pit.parquet")
    core_fcols = [c for c in lib1.CORE_96_FEATURES if c in df1.columns]
    v20_ctx = wf1.load_v20_reference_context(WAVE1)
    sub1 = lib1.slice_pool_entry_exit(df1, "P0_Full", "E1_all", "X2_T2_Close")
    out30 = md1.run_two_step_pipeline(sub1, core_fcols, v20_ctx, mine_mode="t1t2_7pct", recalc_freq="daily", top_k_mine=10, top_k_dragon=15, blacklist_pct=20.0, perm_n=10, eval_v20=False)
    sl30 = out30["dragon_res"]["threshold_results"]["top10"]["slot_df"]

    sub50 = sub1.copy()
    sub50["net_ret"] = (1.0 + sub50["gross_ret"].astype(float)) * (1.0 - 0.0050) - 1.0
    out50 = md1.run_two_step_pipeline(sub50, core_fcols, v20_ctx, mine_mode="t1t2_7pct", recalc_freq="daily", top_k_mine=10, top_k_dragon=15, blacklist_pct=20.0, perm_n=10, eval_v20=False)
    sl50 = out50["dragon_res"]["threshold_results"]["top10"]["slot_df"]
    del df1, sub1, sub50, out30, out50
    gc.collect()

    return {
        "6a_w2b4_A5_v11_PURE_abs80": _std(a5_80, 0.0030, "6a_w2b4_A5_v11_PURE_abs80"),
        "6b_w2b4_A5_v11_PURE_abs85": _std(a5_85, 0.0030, "6b_w2b4_A5_v11_PURE_abs85"),
        "6c_w2b4_A1_h1_PURE_abs75": _std(a1_75, 0.0030, "6c_w2b4_A1_h1_PURE_abs75"),
        "7a_w2b1_ModeM_P0_E1_X2_k15_30bps": _std(sl30, 0.0030, "7a_w2b1_ModeM_P0_E1_X2_k15_30bps"),
        "7b_w2b1_ModeM_P0_E1_X2_k15_50bps_rescore": _std(sl50, 0.0050, "7b_w2b1_ModeM_P0_E1_X2_k15_50bps_rescore"),
    }
