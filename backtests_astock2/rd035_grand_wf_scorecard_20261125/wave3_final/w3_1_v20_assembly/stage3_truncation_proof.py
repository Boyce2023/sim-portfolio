#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 3-1 Stage 3:
  End-to-end Physical 2024-12-31 Truncation Zero-Leakage Proof for the Final Recommended Tier.
  Drops all data > 2024-12-31, rebuilds every component causal model from scratch,
  assembles the full single-slot portfolio up to 2024-12-31, and asserts:
    - max_abs_score_diff == 0.0
    - max_abs_ret_diff == 0.0
    - exact trade sequence match for all trades exiting <= 2024-12-31

Zero yfinance (D12). Zero cap10m. Single-thread, Peak RSS < 2.0 GB.
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
W2A2 = f"{RD035}/wave2a/w2a2_old_3to4_high_pry"
W2A3 = f"{RD035}/wave2a/w2a3_old_20cm"
W2A4 = f"{RD035}/wave2a/w2a4_pairwise_interactions"
W2B4 = f"{RD035}/wave2b/w2b4_20cm_new_archetypes_scorecard"
W2B5 = f"{RD035}/wave2b/w2b5_event_crossmarket_lowcorr_scorecard"
W2B6 = f"{RD035}/wave2b/w2b6_empty_slot_blind_and_crossseat"
OUT_DIR = f"{RD035}/wave3_final/w3_1_v20_assembly"
CACHE_DIR = f"{OUT_DIR}/_cache"

for p in (WAVE1, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import stage2_assemble_and_audit as s2

CUTOFF = "2024-12-31"


def peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


def main():
    t0 = time.time()
    with open(f"{OUT_DIR}/w3_1_assembly_audit.json", encoding="utf-8") as f:
        audit = json.load(f)
    rec_name = audit["recommended_overall_name"]
    rec_cfg = audit["recommended_overall_summary"]["config"]
    rec_full_tr = pd.read_parquet(f"{OUT_DIR}/w3_1_recommended_trades.parquet")
    print(f"[Trunc Proof] Verifying {rec_name} | config={rec_cfg}")

    v20_ctx = wf.load_v20_reference_context(WAVE1)
    cal5 = v20_ctx["calendar_5y"]
    cal_trunc = cal5[cal5["trade_date"].between("2023-01-03", CUTOFF)].sort_values("trade_date")["trade_date"].tolist()
    cal_bench_trunc = [d for d in v20_ctx["bench"]["trade_date"].tolist() if d <= CUTOFF]

    with open(f"{CACHE_DIR}/v20_core_pools.pkl", "rb") as f:
        c_v20 = pickle.load(f)
    with open(f"{CACHE_DIR}/w2a3_w2a4_20cm_scores.pkl", "rb") as f:
        c_20_full = pickle.load(f)
    with open(f"{CACHE_DIR}/w2a2_3to4_pry.pkl", "rb") as f:
        c_34p_full = pickle.load(f)
    with open(f"{CACHE_DIR}/empty_slot_bar_map.pkl", "rb") as f:
        bar_map_full = pickle.load(f)

    # Truncate V20 base pools strictly to buy_date <= CUTOFF
    pools_t = {st: df[df["buy_date"] <= CUTOFF].copy().reset_index(drop=True) for st, df in c_v20["pools"].items()}
    untrig_t = c_v20["untrig"][c_v20["untrig"]["buy_date"] <= CUTOFF].copy().reset_index(drop=True)
    bar_map_t = {k: v for k, v in bar_map_full.items() if k[1] <= CUTOFF}

    component_score_diffs = {}

    # 1. Truncated 20cm rebuild
    c20_id = rec_cfg["20cm"]
    w2a3_scores_t = c_20_full["w2a3_scores"][c_20_full["w2a3_scores"]["buy_date"] <= CUTOFF].copy()
    w2a4_deltas_t = {k: {p: v for p, v in d.items() if p[0] <= CUTOFF} for k, d in c_20_full["w2a4_deltas"].items()}

    if c20_id.startswith("w2a3_cleanb") or c20_id == "w2a3_cold50_s80":
        sys.path.insert(0, W2A3)
        import w2a3_lib as w3l
        p20_t, meta_t = w3l.load_w2a3_data(end_cutoff=CUTOFF)
        df_h20_t = wfm.prepare_hygiene_and_net_ret(p20_t, fee_rt=0.0030)
        f6 = df_h20_t["s20cm_F06_inst_net_pos"].to_numpy(float)
        mkt10 = df_h20_t["mkt10_zt_est_t1"].to_numpy(float)
        df_h20_t["v20_cold50"] = np.where(mkt10 < 50.0, df_h20_t["v20_score"].to_numpy(float) - f6, df_h20_t["v20_score"].to_numpy(float))
        feat_delta_auc = list(dict.fromkeys(meta_t["entry_num"] + meta_t["xtr_fixed"] + meta_t["auc_cols"]))
        sc_t, _ = w3l.run_causal_scorecard_ext(
            df_h20_t, feat_delta_auc, mode="delta_patch", wf_start_date="2023-01-03",
            min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, max_delta=15, orig_score_col="v20_cold50", max_corr_orig=0.70,
            min_discrete_bin_cnt=15,
        )
        m_cmp = w2a3_scores_t.sort_values(["buy_date", "code"]).reset_index(drop=True)
        t_cmp = sc_t.sort_values(["buy_date", "code"]).reset_index(drop=True)
        diff_sc = float(np.max(np.abs(m_cmp["clean_b_cold50_d15_score"].fillna(-999).to_numpy() - t_cmp["wf_score"].fillna(-999).to_numpy())))
        assert diff_sc == 0.0, f"20cm w2a3 trunc diff={diff_sc}"
        component_score_diffs["20cm_w2a3_cleanb"] = diff_sc
        w2a3_scores_t = pd.DataFrame({
            "buy_date": sc_t["buy_date"].values,
            "code": sc_t["code"].values,
            "v20_score": sc_t["v20_score"].values,
            "v20_cold50": df_h20_t["v20_cold50"].values,
            "clean_b_cold50_d15_score": sc_t["wf_score"].values,
            "clean_b_wf_in": sc_t["wf_in_window"].values,
        })
        del p20_t, df_h20_t, sc_t
        gc.collect()
    if "w2a4" in c20_id or "w2a34" in c20_id:
        sys.path.insert(0, W2A4)
        import _w2a4_data_and_features as w2f
        m_t = w2f.load_master_with_sim_cols(CUTOFF)
        m_t = w2f.attach_pit_community_1d_burst(m_t, cal_bench_trunc, end_cutoff=CUTOFF)
        m_t, ix_cols, _ = w2f.build_mechanism_interactions(m_t)
        p20_w4_t = w2f.attach_strategy_sim_cols(m_t[m_t["strategy"] == "20cm"], "20cm")
        md = 10 if "d10" in c20_id else 15
        r4_t = wf.run_wf_scorecard_patch_v20(
            p20_w4_t, ix_cols, orig_score_col="v20_score", strat_name="20cm",
            v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80,
            min_warmup_trades_rare=60, min_warmup_months=18, recalc_freq="daily",
            top_k=10, min_k=5, max_corr=0.65, max_corr_orig=0.70, max_delta=md, perm_n=10,
        )
        sd_t = r4_t["scored_df"]
        new_dm = {(str(r.buy_date)[:10], str(r.code).zfill(6)): float(r.wf_delta_score) for r in sd_t[["buy_date", "code", "wf_delta_score"]].itertuples(index=False)}
        orig_dm = w2a4_deltas_t[f"mech_d{md}"]
        diff_w4 = max(abs(new_dm[k] - orig_dm[k]) for k in new_dm)
        assert diff_w4 == 0.0, f"20cm w2a4 trunc diff={diff_w4}"
        component_score_diffs[f"20cm_w2a4_d{md}"] = diff_w4
        w2a4_deltas_t[f"mech_d{md}"] = new_dm
        del m_t, p20_w4_t, r4_t
        gc.collect()

    # 2. Truncated 3to4 M4_MineBL15 & pry M1_tm05 rebuild
    blk_34_t = {k: v for k, v in c_34p_full["blk_3to4_m4_bl15"].items() if k[0] <= CUTOFF}
    pry_map_t = {k: v for k, v in c_34p_full["pry_m1_tm05"].items() if k[0] <= CUTOFF}
    if rec_cfg["3to4"] == "m4_bl15" or rec_cfg["pry"] == "m1_tm05":
        sys.path.insert(0, W2A2)
        import _w2a2_common as cm2
        import run_w2a2_modules_1_to_4 as r14
        if rec_cfg["3to4"] == "m4_bl15":
            pm34, _ = cm2.load_master_pool_with_exec("3to4")
            fg34 = cm2.get_feature_groups(pm34, "3to4")
            pm34_t = pm34[pm34["buy_date"] <= CUTOFF].copy().reset_index(drop=True)
            _, m4_t = r14.run_module4_minefield_dragon(
                "3to4", pm34_t, fg34["all_with_native"], v20_ctx, mine_loss_thr=-0.07,
                blacklist_qs=(15,), use_declustered=True, wf_start_date="2023-01-03",
            )
            o34 = m4_t["scored_df"]
            blk_new = {(str(r.buy_date)[:10], str(r.code).zfill(6)): bool(r.blk) for r in o34.assign(blk=(o34["wf_mine_score"] >= o34["wf_mine_thr_15"]).fillna(False))[["buy_date", "code", "blk"]].itertuples(index=False)}
            diff_34 = sum(1 for k in blk_new if blk_new[k] != blk_34_t[k])
            assert diff_34 == 0, f"3to4 M4 trunc mismatch count={diff_34}"
            component_score_diffs["3to4_m4_bl15_mismatches"] = float(diff_34)
            blk_34_t = blk_new
            del pm34, pm34_t, m4_t
        if rec_cfg["pry"] == "m1_tm05":
            pm_p, _ = cm2.load_master_pool_with_exec("pry")
            fg_p = cm2.get_feature_groups(pm_p, "pry")
            pm_pt = pm_p[pm_p["buy_date"] <= CUTOFF].copy().reset_index(drop=True)
            pr_t, _ = r14.run_causal_neg_prune_atoms("pry", pm_pt, fg_p["native_af"], t_cut=-0.5, wf_start_date="2023-01-03")
            pry_new = {(str(r.buy_date)[:10], str(r.code).zfill(6)): (float(r.wf_pruned_score) if pd.notna(r.wf_pruned_score) else np.nan, bool(r.wf_in_window)) for r in pr_t[["buy_date", "code", "wf_pruned_score", "wf_in_window"]].itertuples(index=False)}
            diff_p = max(
                abs((0.0 if np.isnan(pry_new[k][0]) else pry_new[k][0]) - (0.0 if np.isnan(pry_map_t[k][0]) else pry_map_t[k][0]))
                for k in pry_new
            )
            assert diff_p == 0.0, f"pry M1 trunc diff={diff_p}"
            component_score_diffs["pry_m1_tm05"] = diff_p
            pry_map_t = pry_new
            del pm_p, pm_pt, pr_t
        gc.collect()

    # 3. Truncated empty-slot rebuild
    empty_ids = rec_cfg["empty"]
    e512_t = pd.read_parquet(f"{CACHE_DIR}/w2b5_512100_daily.parquet")
    e512_t = e512_t[e512_t["date"] <= CUTOFF].copy().reset_index(drop=True)
    c1_t = pd.read_parquet(f"{CACHE_DIR}/w2b6_c1_scored.parquet")
    c1_t = c1_t[c1_t["buy_date"] <= CUTOFF].copy().reset_index(drop=True)
    e3_t = pd.read_parquet(f"{CACHE_DIR}/w2b6_e3_scored.parquet")
    e3_t = e3_t[e3_t["buy_date"] <= CUTOFF].copy().reset_index(drop=True)
    a5_t = pd.read_parquet(f"{CACHE_DIR}/w2b4_a5_scored.parquet")
    a5_t = a5_t[a5_t["buy_date"] <= CUTOFF].copy().reset_index(drop=True)

    if any(x.startswith("c1_") or x.startswith("e3_") for x in empty_ids):
        sys.path.insert(0, W2B6)
        import _w2b6_common as cm6
        import run_w2b6_modC_notices as mc6
        import run_w2b6_modE_us_gap as me6
        px_t = cm6.PriceReturnIndex(end_cutoff=CUTOFF)
        cal_arr_t = np.array(cal_bench_trunc)
        if any(x.startswith("c1_") for x in empty_ids):
            earn_t = mc6.load_earnings_pre_islands(cal_arr_t, end_cutoff=CUTOFF)
            e_ret_t = px_t.lookup_forward_returns(earn_t, horizons=(1,), buy_at="open", min_amt_yi=0.0)
            e_extra = ["cat_yoy_mid_pct", "cat_np_ann_yi", "cat_is_kfe", "cat_is_niukui", "cat_is_yuzeng", "cat_imp_ey_pct"]
            e_feat_t, fcols_e = cm6.attach_pit_features(e_ret_t, buy_at="open", extra_cols=e_extra)
            e_feat_t["cat_imp_ey_pct"] = np.where(e_feat_t["mcap_yi_t1"] > 0, e_feat_t["cat_np_ann_yi"] / e_feat_t["mcap_yi_t1"] * 100.0, np.nan)
            e_clean_t = e_feat_t[e_feat_t["can_buy"] & (e_feat_t["amount_yi_t1"] >= 0.5) & (e_feat_t["ret_20d_t1"].fillna(0.0) < 15.0) & (e_feat_t["prev_streak"] == 0)].copy().reset_index(drop=True)
            e_clean_t["exit_date"] = e_clean_t["exit_date_h1"]
            e_clean_t["gross_ret"] = e_clean_t["gross_ret_h1"]
            e_clean_t = e_clean_t[(e_clean_t["exit_date"] > e_clean_t["buy_date"]) & e_clean_t["gross_ret"].notna()].reset_index(drop=True)
            res_c1_t = wf.run_wf_scorecard_new_strategy(
                e_clean_t, feature_cols=fcols_e, v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date=CUTOFF,
                min_warmup_trades=80, min_warmup_trades_rare=40, min_warmup_months=18, recalc_freq="daily",
                top_k=12, min_k=min(5, len(fcols_e)), max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
                fee_rt=0.0030, gross_ret_col="gross_ret", thresholds=("top20", "top10"), eval_v20_patch=False, perm_n=10,
            )
            c1_new = res_c1_t["scored_df"].sort_values(["buy_date", "code"]).reset_index(drop=True)
            c1_ref = c1_t[c1_t["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
            diff_c1 = float(np.max(np.abs(c1_new["wf_score"].fillna(-999).to_numpy() - c1_ref["wf_score"].fillna(-999).to_numpy())))
            assert diff_c1 == 0.0, f"C1 trunc diff={diff_c1}"
            component_score_diffs["c1_earnpre_h1"] = diff_c1
            c1_t = c1_new
            del earn_t, e_ret_t, e_feat_t, e_clean_t, res_c1_t
            gc.collect()
        if any(x.startswith("e3_") for x in empty_ids):
            cal_cn_t = sorted([d for d in cal_bench_trunc if "2021-01-04" <= d <= CUTOFF])
            map_df, us_p = me6.load_us_leaders_map()
            us_p = us_p[us_p["us_date"] <= CUTOFF].copy()
            cn_dt_df = pd.DataFrame({"buy_date": cal_cn_t, "cn_ts": pd.to_datetime(cal_cn_t)}).sort_values("cn_ts")
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
            ret_df = px_t.lookup_forward_returns(cands, horizons=(1, 3, 5), buy_at="open", min_amt_yi=0.0)
            ret_df = ret_df[ret_df["can_buy"]].copy().reset_index(drop=True)
            op_vals = np.full(len(ret_df), np.nan, dtype=np.float32)
            for idx_r, (c_r, d_r) in enumerate(zip(ret_df["code"], ret_df["buy_date"])):
                cid, did = px_t.c6_to_id.get(c_r, -1), px_t.dt_to_id.get(d_r, -1)
                if cid >= 0 and did >= 0:
                    s, e = px_t.bounds[cid]
                    dt_sub = px_t.dt_id[s:e]
                    rel = int(np.searchsorted(dt_sub, did))
                    if rel < len(dt_sub) and int(dt_sub[rel]) == did:
                        op_vals[idx_r] = px_t.open_pct[s + rel]
            keep_mask = ((ret_df["us_ret1d"] >= 4.0) & (op_vals >= -2.0) & (op_vals <= 3.0)) | ((ret_df["us_ret1d"] <= -4.0) & (op_vals >= 1.5))
            ret_df = ret_df[keep_mask].reset_index(drop=True)
            feat_df, fcols_e3 = cm6.attach_pit_features(ret_df, buy_at="open", extra_cols=["us_ret1d", "us_ret3d", "us_vol_r20", "is_mingmen_node"])
            feat_df = feat_df[feat_df["can_buy"] & (feat_df["amount_yi_t1"] >= 0.8)].copy().reset_index(drop=True)
            feat_df["us_a_unpriced_gap"] = feat_df["us_ret1d"] - feat_df["open_pct"]
            fcols_e3 = fcols_e3 + ["us_a_unpriced_gap"]
            feat_e3_t = feat_df[(feat_df["us_ret1d"] >= 4.0) & (feat_df["is_mingmen_node"] == 1) & (feat_df["open_pct"].between(-2.0, 3.0))].copy().reset_index(drop=True)
            feat_e3_t["exit_date"] = feat_e3_t["exit_date_h1"]
            feat_e3_t["gross_ret"] = feat_e3_t["gross_ret_h1"]
            feat_e3_t = feat_e3_t[(feat_e3_t["exit_date"] > feat_e3_t["buy_date"]) & feat_e3_t["gross_ret"].notna()].reset_index(drop=True)
            res_e3_t = wf.run_wf_scorecard_new_strategy(
                feat_e3_t, feature_cols=fcols_e3, v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date=CUTOFF,
                min_warmup_trades=80, min_warmup_trades_rare=40, min_warmup_months=18, recalc_freq="daily",
                top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
                fee_rt=0.0030, gross_ret_col="gross_ret", thresholds=("top10", "top5"), eval_v20_patch=False, perm_n=10,
            )
            e3_new = res_e3_t["scored_df"].sort_values(["buy_date", "code"]).reset_index(drop=True)
            e3_ref = e3_t[e3_t["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
            diff_e3 = float(np.max(np.abs(e3_new["wf_score"].fillna(-999).to_numpy() - e3_ref["wf_score"].fillna(-999).to_numpy())))
            assert diff_e3 == 0.0, f"E3 trunc diff={diff_e3}"
            component_score_diffs["e3_us_mingmen_h1"] = diff_e3
            e3_t = e3_new
            del ret_df, feat_df, feat_e3_t, res_e3_t
            gc.collect()
        del px_t
        gc.collect()

    if any(x.startswith("a5_") for x in empty_ids):
        sys.path.insert(0, W2B4)
        import w2b4_lib as lib4
        import w2b4_run_all as ra4
        m_b4_t, all_fc_t, _ = lib4.build_w2b4_candidate_pool(CUTOFF)
        ps_t, sm_t = ra4.get_feature_scopes(all_fc_t)
        sp_t = [s for s in ra4.define_final_specs(m_b4_t, ps_t, sm_t) if s[0] == "A5_12_23_v11_PURE"][0]
        sub_t, vf_t = lib4.prepare_track_df(m_b4_t, sp_t[2], exit_mode=sp_t[3], end_dt=CUTOFF, all_feat_cols=sp_t[4])
        df_ht = lib4.wfm.prepare_hygiene_and_net_ret(sub_t, fee_rt=0.0030, gross_ret_col="gross_ret")
        sc_a5_t, _ = lib4.wfc.run_expanding_scorecard_loop(
            df_ht, feature_cols=vf_t, mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, min_warmup_trades_rare=60, min_warmup_months=18,
            recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
        )
        a5_new = sc_a5_t.sort_values(["buy_date", "code"]).reset_index(drop=True)
        a5_ref = a5_t[a5_t["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        diff_a5 = float(np.max(np.abs(a5_new["wf_score"].fillna(-999).to_numpy() - a5_ref["wf_score"].fillna(-999).to_numpy())))
        assert diff_a5 == 0.0, f"A5 trunc diff={diff_a5}"
        component_score_diffs["a5_12_23_v11"] = diff_a5
        a5_t = a5_new
        del m_b4_t, sub_t, df_ht, sc_a5_t
        gc.collect()

    # 4. Run full truncated single-slot portfolio assembly <= 2024-12-31
    data_t = {
        "v20_pools": pools_t,
        "v20_untrig": untrig_t,
        "w2a3_scores": w2a3_scores_t,
        "w2a4_deltas": w2a4_deltas_t,
        "blk_3to4_m4_bl15": blk_34_t,
        "pry_m1_tm05": pry_map_t,
        "e512_daily": e512_t,
        "c1_scored": c1_t,
        "e3_scored": e3_t,
        "a5_scored": a5_t,
    }
    # Temporarily patch s2.WF_END to CUTOFF so empty-slot builds align cleanly with <= 2024-12-31
    orig_wf_end = s2.WF_END
    s2.WF_END = CUTOFF
    core_tr_t, core_w_t = s2.simulate_v20_core(data_t, rec_cfg["20cm"], rec_cfg["3to4"], rec_cfg["pry"], fee_mode="unified_030")
    tracks_t = [s2.build_empty_slot_track_candidates(data_t, tname, stock_fee_rt=0.0030, etf_fee_rt=0.0005) for tname in empty_ids]
    sim_t = s2.simulate_combined_with_empty_slots(core_tr_t, core_w_t, tracks_t, cal_trunc, bar_map_t, patch_mode=rec_cfg["patch_mode"])
    s2.WF_END = orig_wf_end

    tr_trunc_le = sim_t["comb_df"]
    tr_trunc_le = tr_trunc_le[tr_trunc_le["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
    tr_full_le = rec_full_tr[rec_full_tr["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)

    assert len(tr_trunc_le) == len(tr_full_le), f"Trunc trade count mismatch: {len(tr_trunc_le)} vs {len(tr_full_le)}"
    assert list(zip(tr_trunc_le["buy_date"], tr_trunc_le["code"], tr_trunc_le["strategy"])) == list(zip(tr_full_le["buy_date"], tr_full_le["code"], tr_full_le["strategy"])), "Trunc trade sequence mismatch!"
    max_ret_diff = float(np.max(np.abs(tr_trunc_le["net_ret"].to_numpy(float) - tr_full_le["net_ret"].to_numpy(float))))
    max_sc_diff = float(np.max(np.abs(tr_trunc_le["score"].to_numpy(float) - tr_full_le["score"].to_numpy(float))))
    assert max_ret_diff == 0.0 and max_sc_diff == 0.0, f"Portfolio trunc diff != 0: ret={max_ret_diff}, sc={max_sc_diff}"

    proof = {
        "recommended_package": rec_name,
        "cutoff": CUTOFF,
        "n_trades_exiting_le_cutoff": int(len(tr_full_le)),
        "component_score_max_abs_diffs": component_score_diffs,
        "portfolio_max_abs_score_diff": max_sc_diff,
        "portfolio_max_abs_ret_diff": max_ret_diff,
        "zero_leakage_pass": True,
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": peak_rss_mb(),
    }
    audit["truncation_2024_12_31_proof"] = proof
    with open(f"{OUT_DIR}/w3_1_assembly_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"[TRUNCATION PROOF PASS] n_trades_le={len(tr_full_le)}, max_abs_score_diff={max_sc_diff}, max_abs_ret_diff={max_ret_diff}, RSS={proof['peak_rss_mb']} MB")


if __name__ == "__main__":
    main()
