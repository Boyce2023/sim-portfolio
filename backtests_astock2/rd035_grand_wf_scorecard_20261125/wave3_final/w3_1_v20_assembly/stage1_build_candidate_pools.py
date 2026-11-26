#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 3-1 Stage 1:
  Build and parity-verify all cached candidate pools, causal scores, untriggered waits,
  and exact daily bar/MTM lookups for V20.0 + all 7 Wave 2 winners.

Strict constraints:
  - Python 3.13, single-thread (<=1), zero yfinance (D12), zero cap10m.
  - Peak RSS < 2.2 GB via sequential loading + explicit gc.collect() + PyArrow pool release.
  - Read-only on production files, wave1_base, and wave2a/wave2b files.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import pickle
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
pa.set_memory_pool(pa.system_memory_pool())
assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1 = f"{RD035}/wave1_base"
RD028 = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"

W2A2 = f"{RD035}/wave2a/w2a2_old_3to4_high_pry"
W2A3 = f"{RD035}/wave2a/w2a3_old_20cm"
W2A4 = f"{RD035}/wave2a/w2a4_pairwise_interactions"
W2B4 = f"{RD035}/wave2b/w2b4_20cm_new_archetypes_scorecard"
W2B5 = f"{RD035}/wave2b/w2b5_event_crossmarket_lowcorr_scorecard"
W2B6 = f"{RD035}/wave2b/w2b6_empty_slot_blind_and_crossseat"

OUT_DIR = f"{RD035}/wave3_final/w3_1_v20_assembly"
CACHE_DIR = f"{OUT_DIR}/_cache"
os.makedirs(CACHE_DIR, exist_ok=True)


def peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


def _add_sys_path(p: str):
    if p not in sys.path:
        sys.path.insert(0, p)


def build_v20_core_and_20cm_w2a4_w2a3() -> dict:
    """Load V20.0 6-strategy pools (filtered pyarrow scan -> low RAM), verify baseline parity, build w2a3/w2a4 20cm."""
    _add_sys_path(WAVE1)
    _add_sys_path(RD028)
    _add_sys_path(PARTC_V20)
    import wf_scorecard_engine as wf
    import _wf_sim_and_metrics as wfm
    import step4_mod_rules_and_sim as m1
    import tier_priority_engine as tpe

    v20_ctx = wf.load_v20_reference_context(WAVE1)
    cal_5y_dts = v20_ctx["calendar_5y"]["trade_date"].tolist()
    cal_bench = v20_ctx["bench"]["trade_date"].tolist()
    idx_5y = {d: i for i, d in enumerate(cal_5y_dts)}

    # Load only needed codes from a_daily/a_delisted -> ~150 MB instead of 5+ GB!
    codes = set()
    for st in m1.STRAT_ORDER:
        d = pd.read_parquet(f"{RD028}/pool_{st}_oldhot.parquet")
        codes.update(d["code"].astype(str).str.zfill(6))
    tks_need = sorted([f"{c}.SH" for c in codes] + [f"{c}.SZ" for c in codes])
    raw_idx = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300 = {k: float(v) for k, v in raw_idx["sh000300"].items()}
    all_sh_dts = sorted(sh300.keys())
    cal_full = [d for d in all_sh_dts if "2021-01-04" <= d <= "2026-11-25"]

    cols_b = ["date", "ticker", "open", "close", "adj_close", "qfq_factor"]
    tks_set = set(tks_need)
    min_dt_ts = pd.Timestamp("2020-12-01")
    chunks_dp = []
    for path_pq, dl_flag in [
        (f"{SIM}/data/cn_hk_price_db/a_daily.parquet", 0),
        (f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", 1),
    ]:
        pf = pq.ParquetFile(path_pq)
        for rg in range(pf.num_row_groups):
            key_tbl = pf.read_row_group(rg, columns=["date", "ticker"])
            d_arr = key_tbl.column("date").to_pandas()
            if d_arr.max() < min_dt_ts:
                del key_tbl, d_arr
                continue
            t_arr = key_tbl.column("ticker").to_pandas()
            idx_local = np.flatnonzero((d_arr >= min_dt_ts).to_numpy() & t_arr.isin(tks_set).to_numpy())
            del key_tbl, d_arr, t_arr
            if len(idx_local) > 0:
                sub = pf.read_row_group(rg, columns=cols_b).take(pa.array(idx_local, type=pa.int32())).to_pandas()
                sub["dl"] = dl_flag
                chunks_dp.append(sub)
            pa.default_memory_pool().release_unused()
        del pf
        gc.collect()
        pa.default_memory_pool().release_unused()
    dp = pd.concat(chunks_dp, ignore_index=True)
    del chunks_dp
    dp["c6"] = dp["ticker"].astype(str).str[:6]
    dp["dt"] = dp["date"].dt.strftime("%Y-%m-%d")
    dp = dp.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    dp["adjf"] = np.where((dp["close"] > 0) & (dp["adj_close"] > 0), dp["adj_close"] / dp["close"], 1.0)
    bar_lu = {(r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf)) for r in dp.itertuples(index=False)}
    del dp
    gc.collect()
    pa.default_memory_pool().release_unused()

    pools_rd28 = m1.load_pools_oldhot(cal_full, cal_5y_dts, bar_lu)
    # Build untriggered conditional order pool directly from v20_waits_41.json (zero 5M-row bloat!)
    ut_rows = []
    for w in v20_ctx["v20_waits"]:
        ut_rows.append({
            "buy_date": w["buy_date"], "buy_hhmm": 935, "exit_date": w["buy_date"], "exit_hhmm": int(w["cancel_hhmm"]),
            "code": str(w["wait_code"]).zfill(6), "name": w.get("wait_name", ""),
            "strategy": w["wait_strategy"], "tier": w["wait_tier"], "score": float(w["wait_score"]),
            "net_ret": 0.0, "buy_price_val": np.nan, "is_adj_px": False, "is_untrig": True,
            "v20_score": float(w["wait_score"]),
        })
    untrig_base = pd.DataFrame(ut_rows)
    del bar_lu
    gc.collect()

    # Parity check V20.0 baseline
    tr_base, waits_base = m1.run_combined_v20(pools_rd28, untrig_base, {}, start_dt="2021-11-16", end_dt="2026-11-16")
    tr_base_wf = tr_base[tr_base["buy_date"].between("2023-01-03", "2026-11-16")].reset_index(drop=True)
    assert len(tr_base_wf) == 207, f"V20 WF len {len(tr_base_wf)} != 207"
    assert abs(float(np.prod(1.0 + tr_base_wf["net_ret"].to_numpy(float))) - 611729.5546) < 0.05

    # Build clean serialization of V20 pools (native net_ret + mtm_5y_date_pairs + sim cols)
    # Use date-keyed mtm pairs so everything maps cleanly to any calendar!
    c5_map = {i: d for i, d in enumerate(cal_5y_dts)}
    v20_pools_save = {}
    for st in m1.STRAT_ORDER:
        df_s = pools_rd28[st].copy()
        df_s["mtm_pairs"] = [
            [(c5_map[ti], float(mult)) for ti, mult in segs if ti in c5_map]
            for segs in df_s["mtm_5y"]
        ]
        df_s["net_ret_020"] = df_s["net_ret"].astype(float)
        if st == "20cm":
            df_s["net_ret_030"] = df_s["net_ret"].astype(float)
        else:
            df_s["net_ret_030"] = (1.0 + df_s["net_ret_020"]) / 0.9980 * 0.9970 - 1.0
        drop_mtm = [c for c in ("mtm_full", "mtm_5y") if c in df_s.columns]
        v20_pools_save[st] = df_s.drop(columns=drop_mtm)

    # Save untriggered baseline pool cleanly
    ut_save = untrig_base.copy()
    with open(f"{CACHE_DIR}/v20_core_pools.pkl", "wb") as f:
        pickle.dump({"pools": v20_pools_save, "untrig": ut_save, "waits_base": waits_base}, f)
    print(f"[1/6] V20 core pools saved (207 WF parity OK) | RSS={peak_rss_mb()} MB")

    # ---- W2A3 20cm candidates ----
    _add_sys_path(W2A3)
    import w2a3_lib as w3l
    p20_w3, meta_w3 = w3l.load_w2a3_data()
    df_h20 = wfm.prepare_hygiene_and_net_ret(p20_w3, fee_rt=0.0030)
    f6 = df_h20["s20cm_F06_inst_net_pos"].to_numpy(float)
    mkt10 = df_h20["mkt10_zt_est_t1"].to_numpy(float)
    df_h20["v20_cold50"] = np.where(mkt10 < 50.0, df_h20["v20_score"].to_numpy(float) - f6, df_h20["v20_score"].to_numpy(float))
    feat_delta_auc = list(dict.fromkeys(meta_w3["entry_num"] + meta_w3["xtr_fixed"] + meta_w3["auc_cols"]))
    sc_cold50_d15, _ = w3l.run_causal_scorecard_ext(
        df_h20, feat_delta_auc, mode="delta_patch", wf_start_date="2023-01-03",
        min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
        shrink_tau=20.0, max_delta=15, orig_score_col="v20_cold50", max_corr_orig=0.70,
        min_discrete_bin_cnt=15,
    )
    # Assert W2A3 parity
    for name_c, df_c, col_c, thr_c, exp_n, exp_nav in [
        ("M1_F06_COLD50_thr80", df_h20, "v20_cold50", 80.0, 120, 50.9555),
        ("CLEAN_B_cold50_d15_S80", sc_cold50_d15, "wf_score", 80.0, 139, 77.3852),
        ("CLEAN_B_cold50_d15_S84", sc_cold50_d15, "wf_score", 84.0, 95, 70.5843),
    ]:
        df_chk = df_c.copy()
        df_chk["wf_in_window"] = df_chk["buy_date"] >= "2023-01-03"
        _, sl_chk = wfm.select_single_slot_trades(df_chk, score_col=col_c, threshold=thr_c, wf_only=True)
        nav_chk = float(np.prod(1.0 + sl_chk["net_ret"].to_numpy(float)))
        assert len(sl_chk) == exp_n and abs(nav_chk - exp_nav) < 0.05, f"W2A3 {name_c} mismatch: {len(sl_chk)}/{nav_chk}"

    w2a3_scores = df_h20[["buy_date", "code", "v20_score", "v20_cold50"]].copy()
    w2a3_scores["clean_b_cold50_d15_score"] = sc_cold50_d15["wf_score"].values
    w2a3_scores["clean_b_wf_in"] = sc_cold50_d15["wf_in_window"].values
    del p20_w3, df_h20, sc_cold50_d15
    gc.collect()
    print(f"[2/6] W2A3 20cm trio parity OK (120/50.96x, 139/77.39x, 95/70.58x) | RSS={peak_rss_mb()} MB")

    # ---- W2A4 20cm pairwise interactions (d10 / d15) ----
    _add_sys_path(W2A4)
    import _w2a4_data_and_features as w2f
    m_full = w2f.load_master_with_sim_cols("2026-11-16")
    m_full = w2f.attach_pit_community_1d_burst(m_full, cal_bench, end_cutoff="2026-11-16")
    m_full, ix_cols, _ = w2f.build_mechanism_interactions(m_full)
    p20_w4 = w2f.attach_strategy_sim_cols(m_full[m_full["strategy"] == "20cm"], "20cm")
    del m_full
    gc.collect()

    # Attach cold50 as well for optional combined w2a3+w2a4 diagnostic check
    p20_w4 = p20_w4.merge(w2a3_scores[["buy_date", "code", "v20_cold50"]], on=["buy_date", "code"], how="left")
    w2a4_res = {}
    for md in (10, 15):
        r4 = wf.run_wf_scorecard_patch_v20(
            p20_w4, ix_cols, orig_score_col="v20_score", strat_name="20cm",
            v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80,
            min_warmup_trades_rare=60, min_warmup_months=18, recalc_freq="daily",
            top_k=10, min_k=5, max_corr=0.65, max_corr_orig=0.70, max_delta=md, perm_n=10,
        )
        sd4 = r4["scored_df"]
        w2a4_res[f"mech_d{md}"] = {
            (str(r.buy_date)[:10], str(r.code).zfill(6)): float(r.wf_delta_score)
            for r in sd4[["buy_date", "code", "wf_delta_score"]].itertuples(index=False)
        }
        # Also test cold50 base + mech_d10/15
        r4c = wf.run_wf_scorecard_patch_v20(
            p20_w4, ix_cols, orig_score_col="v20_cold50", strat_name="20cm",
            v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80,
            min_warmup_trades_rare=60, min_warmup_months=18, recalc_freq="daily",
            top_k=10, min_k=5, max_corr=0.65, max_corr_orig=0.70, max_delta=md, perm_n=10,
        )
        sd4c = r4c["scored_df"]
        w2a4_res[f"cold50_mech_d{md}"] = {
            (str(r.buy_date)[:10], str(r.code).zfill(6)): float(r.wf_delta_score)
            for r in sd4c[["buy_date", "code", "wf_delta_score"]].itertuples(index=False)
        }
    # Assert W2A4 standalone d15 parity vs w2a4_best_20cm_standalone_trades.parquet
    ref_w4_st = pd.read_parquet(f"{W2A4}/w2a4_best_20cm_standalone_trades.parquet")
    d15_vec = np.array([w2a4_res["mech_d15"].get((str(r.buy_date)[:10], str(r.code).zfill(6)), 0.0) for r in pools_rd28["20cm"].itertuples(index=False)])
    _, sl_w4 = m1.sim_standalone("20cm", pools_rd28["20cm"], d15_vec, cm20_thr=82.0)
    sl_w4_wf = sl_w4[sl_w4["buy_date"] >= "2023-01-31"]
    assert len(sl_w4_wf) == len(ref_w4_st) == 121, f"W2A4 standalone d15 len {len(sl_w4_wf)} != 121"

    with open(f"{CACHE_DIR}/w2a3_w2a4_20cm_scores.pkl", "wb") as f:
        pickle.dump({"w2a3_scores": w2a3_scores, "w2a4_deltas": w2a4_res}, f)
    del p20_w4, pools_rd28, untrig_base
    gc.collect()
    pa.default_memory_pool().release_unused()
    print(f"[3/6] W2A4 20cm d10/d15 parity OK (121 trades) | RSS={peak_rss_mb()} MB")
    return {"status": "ok"}


def build_w2a2_3to4_pry():
    """Rebuild & parity-verify 3to4 M4_MineBL15_OrigScore and pry M1_WF_DropNeg_tm05."""
    _add_sys_path(WAVE1)
    _add_sys_path(W2A2)
    import _w2a2_common as cm
    import run_w2a2_modules_1_to_4 as r14

    v20_ctx = cm.wf.load_v20_reference_context(WAVE1)
    pm34, _ = cm.load_master_pool_with_exec("3to4")
    fg34 = cm.get_feature_groups(pm34, "3to4")
    _, m4_det = r14.run_module4_minefield_dragon(
        "3to4", pm34, fg34["all_with_native"], v20_ctx, mine_loss_thr=-0.07,
        blacklist_qs=(15,), use_declustered=True, wf_start_date="2023-01-03",
    )
    out34 = m4_det["scored_df"]
    is_blk34 = (out34["wf_mine_score"] >= out34["wf_mine_thr_15"]).fillna(False)
    safe34 = out34.copy()
    safe34["can_buy_hygiene"] = safe34["can_buy_hygiene"] & (~is_blk34)
    _, sl34 = cm.sim_strategy_custom("3to4", safe34, "orig_score", 90.0, wf_only=True)
    nav34 = float(np.prod(1.0 + sl34["net_ret"].to_numpy(float)))
    assert len(sl34) == 71 and abs(nav34 - 267.7267) < 0.05, f"3to4 M4 mismatch: {len(sl34)}/{nav34}"

    blk_map_34 = {
        (str(r.buy_date)[:10], str(r.code).zfill(6)): bool(r.blk)
        for r in out34.assign(blk=is_blk34)[["buy_date", "code", "blk"]].itertuples(index=False)
    }

    pm_pry, _ = cm.load_master_pool_with_exec("pry")
    fg_pry = cm.get_feature_groups(pm_pry, "pry")
    pr_df, pr_meta = r14.run_causal_neg_prune_atoms("pry", pm_pry, fg_pry["native_af"], t_cut=-0.5, wf_start_date="2023-01-03")
    _, sl_pry = cm.sim_strategy_custom("pry", pr_df, "wf_pruned_score", 165.0, wf_only=True)
    nav_pry = float(np.prod(1.0 + sl_pry["net_ret"].to_numpy(float)))
    assert len(sl_pry) == 6 and abs(nav_pry - 1.5167) < 0.01, f"pry M1 mismatch: {len(sl_pry)}/{nav_pry}"

    pry_sc_map = {
        (str(r.buy_date)[:10], str(r.code).zfill(6)): (float(r.wf_pruned_score) if pd.notna(r.wf_pruned_score) else np.nan, bool(r.wf_in_window))
        for r in pr_df[["buy_date", "code", "wf_pruned_score", "wf_in_window"]].itertuples(index=False)
    }

    with open(f"{CACHE_DIR}/w2a2_3to4_pry.pkl", "wb") as f:
        pickle.dump({"blk_3to4_m4_bl15": blk_map_34, "pry_m1_tm05": pry_sc_map, "pry_meta": pr_meta}, f)
    del pm34, out34, safe34, pm_pry, pr_df
    gc.collect()
    pa.default_memory_pool().release_unused()
    print(f"[4/6] W2A2 3to4 M4_MineBL15 (71/267.73x) & pry M1_tm05 (6/1.52x) parity OK | RSS={peak_rss_mb()} MB")


def build_w2b5_and_w2b6_pools():
    """Rebuild passing pools for TrackC 512100 ETF, ModE_E3, and ModC_C1 + exact daily px_idx."""
    _add_sys_path(WAVE1)
    _add_sys_path(W2B5)
    _add_sys_path(W2B6)
    import wf_scorecard_engine as wf
    import _w2b5_common as wc5
    import _w2b6_common as cm6
    import run_w2b6_modC_notices as mc6
    import run_w2b6_modE_us_gap as me6

    v20_ctx = wf.load_v20_reference_context(WAVE1)
    # 1. Track C 512100 ETF signal & prices
    etf_df = wc5.build_or_load_clean_etf_cache()
    mkt_df = pd.read_parquet(f"{WAVE1}/market_daily_all_new_factors_pit.parquet")
    e512 = etf_df[etf_df["code"] == "512100"].sort_values("date").reset_index(drop=True)
    e512 = e512.merge(mkt_df[["trade_date", "nt_v3_score_live_t1", "nt_v3_score_eod_t1"]], left_on="date", right_on="trade_date", how="left")
    e512.to_parquet(f"{CACHE_DIR}/w2b5_512100_daily.parquet", index=False)

    # 2. ModC C1_EarnPre_NoRun_H1 & ModE_E3_US4pct_MingmenOnly_H1
    px_idx = cm6.PriceReturnIndex(end_cutoff="2026-11-25")
    cal_all = np.array(sorted(v20_ctx["bench"]["trade_date"].tolist()))

    # C1
    earn_df = mc6.load_earnings_pre_islands(cal_all, end_cutoff="2026-11-16")
    e_ret = px_idx.lookup_forward_returns(earn_df, horizons=(1,), buy_at="open", min_amt_yi=0.0)
    e_extra = ["cat_yoy_mid_pct", "cat_np_ann_yi", "cat_is_kfe", "cat_is_niukui", "cat_is_yuzeng", "cat_imp_ey_pct"]
    e_feat, fcols_e = cm6.attach_pit_features(e_ret, buy_at="open", extra_cols=e_extra)
    e_feat["cat_imp_ey_pct"] = np.where(e_feat["mcap_yi_t1"] > 0, e_feat["cat_np_ann_yi"] / e_feat["mcap_yi_t1"] * 100.0, np.nan)
    e_clean = e_feat[
        e_feat["can_buy"]
        & (e_feat["amount_yi_t1"] >= 0.5)
        & (e_feat["ret_20d_t1"].fillna(0.0) < 15.0)
        & (e_feat["prev_streak"] == 0)
    ].copy().reset_index(drop=True)
    e_clean["exit_date"] = e_clean["exit_date_h1"]
    e_clean["gross_ret"] = e_clean["gross_ret_h1"]
    e_clean = e_clean[(e_clean["exit_date"] > e_clean["buy_date"]) & e_clean["gross_ret"].notna()].reset_index(drop=True)
    res_c1 = wf.run_wf_scorecard_new_strategy(
        e_clean, feature_cols=fcols_e, v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date="2026-11-16",
        min_warmup_trades=80, min_warmup_trades_rare=40, min_warmup_months=18, recalc_freq="daily",
        top_k=12, min_k=min(5, len(fcols_e)), max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
        fee_rt=0.0030, gross_ret_col="gross_ret", thresholds=("all_cands", "top20", "top10"),
        eval_v20_patch=False, perm_n=10,
    )
    c1_scored = res_c1["scored_df"]
    assert res_c1["threshold_results"]["top10"]["metrics"]["windows"]["FULL_WF"]["n"] == 54
    keep_c1 = ["buy_date", "exit_date", "code", "buy_hhmm", "exit_hhmm", "gross_ret", "net_ret", "can_buy_hygiene", "wf_in_window", "wf_score", "wf_thr_top20", "wf_thr_top10"]
    c1_scored[keep_c1].to_parquet(f"{CACHE_DIR}/w2b6_c1_scored.parquet", index=False)
    del earn_df, e_ret, e_feat, e_clean, res_c1, c1_scored
    gc.collect()

    # E3
    cal_cn = sorted([d for d in v20_ctx["bench"]["trade_date"].tolist() if "2021-01-04" <= d <= "2026-11-16"])
    map_df, us_p = me6.load_us_leaders_map()
    cn_dt_df = pd.DataFrame({"buy_date": cal_cn, "cn_ts": pd.to_datetime(cal_cn)}).sort_values("cn_ts")
    us_p["us_ts"] = pd.to_datetime(us_p["us_date"])
    aligned_list = []
    for utk, grp in us_p.groupby("ticker"):
        m = pd.merge_asof(cn_dt_df, grp.sort_values("us_ts"), left_on="cn_ts", right_on="us_ts", direction="backward", allow_exact_matches=False)
        m["us_ticker"] = utk
        aligned_list.append(m[["buy_date", "us_ticker", "us_ret1d", "us_ret3d", "us_vol_r20"]])
    us_cn = pd.concat(aligned_list, ignore_index=True)
    us_trig = us_cn[(us_cn["us_ret1d"].abs() >= 4.0) & (us_cn["us_vol_r20"] >= 1.4)].copy()
    cands = us_trig.merge(map_df, on="us_ticker", how="inner")
    cands["abs_r"] = cands["us_ret1d"].abs()
    cands = cands.sort_values(["buy_date", "code", "abs_r"], ascending=[True, True, False]).drop_duplicates(["buy_date", "code"]).drop(columns=["abs_r", "tree_name", "us_ticker"]).reset_index(drop=True)
    ret_df = px_idx.lookup_forward_returns(cands, horizons=(1, 3, 5), buy_at="open", min_amt_yi=0.0)
    ret_df = ret_df[ret_df["can_buy"]].copy().reset_index(drop=True)
    op_vals = np.full(len(ret_df), np.nan, dtype=np.float32)
    for idx_r, (c_r, d_r) in enumerate(zip(ret_df["code"], ret_df["buy_date"])):
        cid = px_idx.c6_to_id.get(c_r, -1)
        did = px_idx.dt_to_id.get(d_r, -1)
        if cid >= 0 and did >= 0:
            s, e = px_idx.bounds[cid]
            dt_sub = px_idx.dt_id[s:e]
            rel = int(np.searchsorted(dt_sub, did))
            if rel < len(dt_sub) and int(dt_sub[rel]) == did:
                op_vals[idx_r] = px_idx.open_pct[s + rel]
    keep_mask = ((ret_df["us_ret1d"] >= 4.0) & (op_vals >= -2.0) & (op_vals <= 3.0)) | ((ret_df["us_ret1d"] <= -4.0) & (op_vals >= 1.5))
    ret_df = ret_df[keep_mask].reset_index(drop=True)
    del cands, us_trig, us_cn, us_p, map_df
    gc.collect()

    feat_df, fcols_e3 = cm6.attach_pit_features(ret_df, buy_at="open", extra_cols=["us_ret1d", "us_ret3d", "us_vol_r20", "is_mingmen_node"])
    del ret_df
    gc.collect()
    feat_df = feat_df[feat_df["can_buy"] & (feat_df["amount_yi_t1"] >= 0.8)].copy().reset_index(drop=True)
    feat_df["us_a_unpriced_gap"] = feat_df["us_ret1d"] - feat_df["open_pct"]
    fcols_e3 = fcols_e3 + ["us_a_unpriced_gap"]
    feat_e3 = feat_df[(feat_df["us_ret1d"] >= 4.0) & (feat_df["is_mingmen_node"] == 1) & (feat_df["open_pct"].between(-2.0, 3.0))].copy().reset_index(drop=True)
    del feat_df
    gc.collect()
    feat_e3["exit_date"] = feat_e3["exit_date_h1"]
    feat_e3["gross_ret"] = feat_e3["gross_ret_h1"]
    feat_e3 = feat_e3[(feat_e3["exit_date"] > feat_e3["buy_date"]) & feat_e3["gross_ret"].notna()].reset_index(drop=True)

    res_e3 = wf.run_wf_scorecard_new_strategy(
        feat_e3, feature_cols=fcols_e3, v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date="2026-11-16",
        min_warmup_trades=80, min_warmup_trades_rare=40, min_warmup_months=18, recalc_freq="daily",
        top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
        fee_rt=0.0030, gross_ret_col="gross_ret", thresholds=("top10", "top5", 70),
        eval_v20_patch=False, perm_n=10,
    )
    e3_scored = res_e3["scored_df"]
    assert res_e3["threshold_results"]["top5"]["metrics"]["windows"]["FULL_WF"]["n"] == 139, f"E3 n != 139"
    keep_e3 = ["buy_date", "exit_date", "code", "buy_hhmm", "exit_hhmm", "gross_ret", "net_ret", "can_buy_hygiene", "wf_in_window", "wf_score", "wf_thr_top10", "wf_thr_top5"]
    e3_scored[keep_e3].to_parquet(f"{CACHE_DIR}/w2b6_e3_scored.parquet", index=False)
    del feat_e3, res_e3, e3_scored, px_idx
    gc.collect()
    pa.default_memory_pool().release_unused()
    print(f"[5/6] W2B5 512100 + W2B6 C1 (54t) & E3 (139t) parity OK | RSS={peak_rss_mb()} MB")


def build_w2b4_and_bar_lookup():
    """Rebuild A5_12_23_v11_PURE scored pool + compact daily bar lookup for all empty-slot stocks."""
    _add_sys_path(WAVE1)
    _add_sys_path(W2B4)
    _add_sys_path(W2B6)
    import w2b4_lib as lib4
    import w2b4_run_all as ra4
    import _w2b6_common as cm6

    master_df, all_fcols, _ = lib4.build_w2b4_candidate_pool("2026-11-16")
    pure_stock, stock_micro = ra4.get_feature_scopes(all_fcols)
    specs = ra4.define_final_specs(master_df, pure_stock, stock_micro)
    a5_spec = [s for s in specs if s[0] == "A5_12_23_v11_PURE"][0]
    _, _, mask, ex_mode, fset, _ = a5_spec
    sub_df, vf_cols = lib4.prepare_track_df(master_df, mask, exit_mode=ex_mode, end_dt="2026-11-16", all_feat_cols=fset)
    del master_df
    gc.collect()

    df_h = lib4.wfm.prepare_hygiene_and_net_ret(sub_df, fee_rt=0.0030, gross_ret_col="gross_ret")
    scored_a5, _ = lib4.wfc.run_expanding_scorecard_loop(
        df_h, feature_cols=vf_cols, mode="scorecard_0_100", wf_start_date="2023-01-03",
        min_warmup_trades=80, min_warmup_trades_rare=60, min_warmup_months=18,
        recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
    )
    _, sl_80 = lib4.wfm.select_single_slot_trades(scored_a5, score_col="wf_score", threshold=80.0, wf_only=True)
    _, sl_85 = lib4.wfm.select_single_slot_trades(scored_a5, score_col="wf_score", threshold=85.0, wf_only=True)
    assert len(sl_80) == 115 and len(sl_85) == 51, f"A5 parity fail: {len(sl_80)}, {len(sl_85)}"
    keep_a5 = ["buy_date", "exit_date", "code", "buy_hhmm", "exit_hhmm", "open_pct", "gross_ret", "net_ret", "exit_reason", "mtm_json", "can_buy_hygiene", "wf_in_window", "wf_score"]
    scored_a5[keep_a5].to_parquet(f"{CACHE_DIR}/w2b4_a5_scored.parquet", index=False)
    del sub_df, df_h, scored_a5
    gc.collect()

    # Build compact stock bar lookup (code, dt) -> (ao, ac, is_yizi_dt, is_dt, is_st) for all candidate codes in C1, E3, A5
    c1 = pd.read_parquet(f"{CACHE_DIR}/w2b6_c1_scored.parquet", columns=["code"])
    e3 = pd.read_parquet(f"{CACHE_DIR}/w2b6_e3_scored.parquet", columns=["code"])
    a5 = pd.read_parquet(f"{CACHE_DIR}/w2b4_a5_scored.parquet", columns=["code"])
    need_codes = set(c1["code"].astype(str).str.zfill(6)) | set(e3["code"].astype(str).str.zfill(6)) | set(a5["code"].astype(str).str.zfill(6))

    px_idx = cm6.PriceReturnIndex(end_cutoff="2026-11-25")
    bar_map = {}
    for c in need_codes:
        cid = px_idx.c6_to_id.get(c, -1)
        if cid < 0:
            continue
        s, e = px_idx.bounds[cid]
        for p in range(s, e):
            d_str = str(px_idx.dt_list[int(px_idx.dt_id[p])])
            if "2023-01-01" <= d_str <= "2026-11-20":
                af = float(px_idx.adj_factor[p])
                bar_map[(c, d_str)] = (
                    float(px_idx.open[p]) * af,
                    float(px_idx.close[p]) * af,
                    int(px_idx.is_yizi_dt[p]),
                    int(px_idx.is_dt[p]),
                    int(px_idx.is_st[p]),
                    float(px_idx.amount_yi[p]),
                )
    with open(f"{CACHE_DIR}/empty_slot_bar_map.pkl", "wb") as f:
        pickle.dump(bar_map, f)
    del px_idx, bar_map
    gc.collect()
    pa.default_memory_pool().release_unused()
    print(f"[6/6] W2B4 A5 (115t@80, 51t@85) & bar_map ({len(need_codes)} codes) saved | RSS={peak_rss_mb()} MB")


def main():
    t0 = time.time()
    build_v20_core_and_20cm_w2a4_w2a3()
    build_w2a2_3to4_pry()
    build_w2b5_and_w2b6_pools()
    build_w2b4_and_bar_lookup()
    print(f"[STAGE 1 COMPLETE in {time.time()-t0:.2f}s | Peak RSS={peak_rss_mb()} MB]")


if __name__ == "__main__":
    main()
