#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 3-3 Red Team Audit B — Step 2A:
Ultra-lightweight exact close-to-close MTM builder (< 400 MB peak RSS!) + full neighborhood
grid reconstruction for Wave 2A / W2B1 strategies:
  1. 20cm 关F06纯物理 (COLD40/45/50/55 x S78/80/82/84 + DEL + BASE)
  2. 20cm 新因子 Mode B (CLEAN_B v20/cold40/45/50/55 x d8/10/15/20/25 x S78/80/82/84)
  3. 20cm 130机理交互 (W2A4 Mech_Native/Guarded/Dyn20x19 x d8/10/15/20/25)
  4. 三进四排雷分家 (W2A2 BL10/15/20/25 x OrigScore/Dragon)
  5. 撬板删红灯 (W2A2 DropNeg/LOO/ModeB)
  6. 20cm 10-19.8% 阳线 Mode M/A (W2B1 top daily tracks across all thresholds)

Peak RSS < 1.2 GB, threads <= 1, zero yfinance, strictly read-only on Wave 1/2 files.
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
import pyarrow.dataset as ds

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1 = f"{BASE}/wave1_base"
RD028 = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
W2A2_DIR = f"{BASE}/wave2a/w2a2_old_3to4_high_pry"
W2A3_DIR = f"{BASE}/wave2a/w2a3_old_20cm"
W2A4_DIR = f"{BASE}/wave2a/w2a4_pairwise_interactions"
W2B1_DIR = f"{BASE}/wave2b/w2b1_20cm_surge10_19_scorecard"
OUT_DIR = f"{BASE}/wave3_final/w3_3_redteam_audit_b"
os.makedirs(OUT_DIR, exist_ok=True)

for p in (WAVE1, RD028, W2A2_DIR, W2A3_DIR, W2A4_DIR, W2B1_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _wf_sim_and_metrics as wfm
import _wf_core as wfc


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


class CompactNumpyMTM:
    """Exact close-to-close daily MTM builder using compact sorted numpy arrays (< 150 MB RSS)."""

    def __init__(self, cal_dts: list[str], end_cutoff: str = "2026-11-16"):
        self.cal_dts = cal_dts
        self.dt_idx = {d: i for i, d in enumerate(cal_dts)}
        self.T = len(cal_dts)
        self.bar_lu: dict[tuple[str, str], tuple[float, float, float]] = {}
        self.loaded_codes: set[str] = set()
        self.end_cutoff = end_cutoff

    def preload_needed_pairs(self, slot_dfs: list[pd.DataFrame]):
        """Load ONLY (code, dt) bars within [buy_date, exit_date] of actual executed trades."""
        needed_pairs = set()
        needed_codes = set()
        for sdf in slot_dfs:
            if sdf is None or sdf.empty:
                continue
            for r in sdf[["code", "buy_date", "exit_date"]].itertuples(index=False):
                c = str(r.code).zfill(6)
                bi = self.dt_idx.get(str(r.buy_date)[:10])
                ei = self.dt_idx.get(str(r.exit_date)[:10])
                if bi is None or ei is None or ei <= bi:
                    continue
                needed_codes.add(c)
                for t in range(bi, min(ei + 1, self.T)):
                    needed_pairs.add((c, self.cal_dts[t]))

        if not needed_pairs:
            return
        tks = sorted({f"{c}.SH" for c in needed_codes} | {f"{c}.SZ" for c in needed_codes})
        cols = ["date", "ticker", "open", "close", "adj_close"]
        flt = (ds.field("date") >= pd.Timestamp("2022-12-15")) & (ds.field("date") <= pd.Timestamp(self.end_cutoff)) & ds.field("ticker").isin(tks)
        for pq_path, dl_flag in [(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", 0), (f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", 1)]:
            df = ds.dataset(pq_path, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
            if df.empty:
                continue
            df["c6"] = df["ticker"].astype(str).str[:6]
            df["dt"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            # Filter immediately to needed (c6, dt) pairs!
            keep = [((c, d) in needed_pairs) for c, d in zip(df["c6"], df["dt"])]
            sub = df.loc[keep].copy()
            del df
            for r in sub.itertuples(index=False):
                k = (r.c6, r.dt)
                if dl_flag == 0 or k not in self.bar_lu:
                    adjf = (float(r.adj_close) / float(r.close)) if (r.close > 0 and r.adj_close > 0) else 1.0
                    self.bar_lu[k] = (float(r.open), float(r.close), adjf)
        gc.collect()
        pa.default_memory_pool().release_unused()

    def build_daily_ret(
        self,
        slot_df: pd.DataFrame,
        strat_override: str | None = None,
        buy_at_open_override: bool = False,
        fee_rt: float = 0.0030,
    ) -> tuple[np.ndarray, float]:
        T = self.T
        if slot_df.empty:
            return np.zeros(T, dtype=float), 0.0
        day_mult = np.ones(T, dtype=np.float64)
        for r in slot_df.itertuples(index=False):
            nr = float(r.net_ret) if pd.notna(r.net_ret) else np.nan
            if not np.isfinite(nr):
                continue
            bd = str(r.buy_date)[:10]
            ed = str(r.exit_date)[:10]
            bi = self.dt_idx.get(bd)
            ei = self.dt_idx.get(ed)
            if bi is None or ei is None or ei <= bi:
                continue
            c6 = str(r.code).zfill(6)
            bb = self.bar_lu.get((c6, bd))
            st = strat_override or str(getattr(r, "strategy", ""))
            b_adj = np.nan
            if buy_at_open_override and bb is not None and bb[0] > 0:
                b_adj = bb[0] * bb[2] * (1.0 / (1.0 - 0.5 * fee_rt))
            else:
                bp_val = getattr(r, "buy_px", np.nan) if (st == "20cm" and hasattr(r, "buy_px") and pd.notna(getattr(r, "buy_px", np.nan))) else getattr(r, "buy_price", np.nan)
                if st == "20cm" and pd.notna(bp_val):
                    b_adj = float(bp_val)
                elif pd.notna(bp_val) and bb is not None:
                    b_adj = float(bp_val) * bb[2]
                elif bb is not None:
                    b_adj = bb[1] * bb[2]
            if not np.isfinite(b_adj) or b_adj <= 0:
                b_adj = 1.0

            prev_v, last_c = b_adj, b_adj
            for t in range(bi, min(ei, T)):
                bt = self.bar_lu.get((c6, self.cal_dts[t]))
                cur_c = (bt[1] * bt[2]) if (bt is not None and bt[1] > 0) else last_c
                if cur_c <= 0:
                    cur_c = last_c
                day_mult[t] *= (cur_c / prev_v)
                prev_v, last_c = cur_c, cur_c
            if ei < T:
                day_mult[ei] *= ((b_adj * (1.0 + nr)) / prev_v)
        dr = day_mult - 1.0
        tr_sub = slot_df[slot_df["buy_date"].isin(self.dt_idx)]
        tr_nav = float(np.prod(1.0 + tr_sub["net_ret"].to_numpy(float))) if not tr_sub.empty else 1.0
        return dr, abs(float(np.prod(day_mult)) - tr_nav)


def main():
    t0 = time.time()
    import wf_scorecard_engine as wfe
    v20_ctx = wfe.load_v20_reference_context(WAVE1)
    cal5 = v20_ctx["calendar_5y"]
    cal_wf = cal5[cal5["trade_date"].between("2023-01-03", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_wf["trade_date"].tolist()
    bench = v20_ctx["bench"]
    cal_full_dts = bench["trade_date"].tolist()

    raw_tracks = {}  # track -> variant -> (slot_df, strat_ovr, open_ovr)

    # =========================================================================
    # TRACK 1 & 2: W2A3 (20cm F06 Pure Physics + 20cm CLEAN_B Mode B)
    # =========================================================================
    import w2a3_lib as a3lib
    p20, meta20 = a3lib.load_w2a3_data()
    df20 = wfm.prepare_hygiene_and_net_ret(p20, fee_rt=0.0030)
    df20["wf_in_window"] = df20["buy_date"] >= "2023-01-03"
    v20_sc = df20["v20_score"].to_numpy(float)
    f6_vals = df20["s20cm_F06_inst_net_pos"].to_numpy(float)
    mkt10 = df20["mkt10_zt_est_t1"].to_numpy(float)
    sc_no6 = v20_sc - f6_vals

    t1 = {}
    for thr in (76, 78, 80, 82, 84):
        _, s_df = wfm.select_single_slot_trades(df20, score_col="v20_score", threshold=float(thr), wf_only=True)
        t1[f"BASE_V11_S{thr}"] = (s_df, "20cm", False)
    for thr in (78, 80, 82, 84):
        d_tmp = df20.copy(); d_tmp["_sc"] = sc_no6
        _, s_df = wfm.select_single_slot_trades(d_tmp, score_col="_sc", threshold=float(thr), wf_only=True)
        t1[f"M1_F06_DEL_thr{thr}"] = (s_df, "20cm", False)
    for cut in (40, 45, 50, 55):
        d_tmp = df20.copy(); d_tmp["_sc"] = np.where(mkt10 < cut, sc_no6, v20_sc)
        for thr in (78, 80, 82, 84):
            _, s_df = wfm.select_single_slot_trades(d_tmp, score_col="_sc", threshold=float(thr), wf_only=True)
            t1[f"M1_F06_COLD{cut}_thr{thr}"] = (s_df, "20cm", False)
    raw_tracks["20cm_F06_PurePhysics"] = t1
    print(f"  [Track 1 F06] {len(t1)} variants | COLD50_thr80 n={len(t1['M1_F06_COLD50_thr80'][0])} | RSS={rss_mb()} MB")

    feat_delta_auc = list(dict.fromkeys(meta20["entry_num"] + meta20["xtr_fixed"] + meta20["auc_cols"]))
    for c_cut in (40, 45, 50, 55):
        df20[f"v20_cold{c_cut}"] = np.where(mkt10 < float(c_cut), sc_no6, v20_sc)
    t2 = {}
    for btag, orig_c in [("v20", "v20_score"), ("cold40", "v20_cold40"), ("cold45", "v20_cold45"), ("cold50", "v20_cold50"), ("cold55", "v20_cold55")]:
        for md in (8, 10, 15, 20, 25):
            sc_b, _ = a3lib.run_causal_scorecard_ext(
                df20, feat_delta_auc, mode="delta_patch", wf_start_date="2023-01-03",
                min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
                shrink_tau=20.0, max_delta=md, orig_score_col=orig_c, max_corr_orig=0.70,
                min_discrete_bin_cnt=15,
            )
            for th in ("top20", "top15", "top10", 78, 80, 82, 84):
                tname = th if isinstance(th, str) else f"S{th}"
                targ = f"wf_thr_{th}" if isinstance(th, str) else float(th)
                _, s_df = wfm.select_single_slot_trades(sc_b, score_col="wf_score", threshold=targ, wf_only=True)
                t2[f"CLEAN_B_{btag}_d{md}_{tname}"] = (s_df, "20cm", False)
    raw_tracks["20cm_CLEAN_ModeB"] = t2
    print(f"  [Track 2 CLEAN_B] {len(t2)} variants | RSS={rss_mb()} MB")
    del p20, df20, sc_b
    gc.collect()

    # =========================================================================
    # TRACK 3: W2A4 20cm 130 Mech Interactions
    # =========================================================================
    import _w2a4_data_and_features as w2f
    import step4_mod_rules_and_sim as m1
    m20 = w2f.load_master_with_sim_cols("2026-11-25")
    m20 = m20[m20["strategy"] == "20cm"].copy().reset_index(drop=True)
    m20 = w2f.attach_strategy_sim_cols(m20, "20cm")
    m20 = w2f.attach_pit_community_1d_burst(m20, cal_full_dts, end_cutoff="2026-11-25")
    m20, ix_cols, _ = w2f.build_mechanism_interactions(m20)
    base_cols20 = w2f.select_base_single_factors_for_dyn(m20)
    m20_h = wfm.prepare_hygiene_and_net_ret(m20, fee_rt=0.0020)
    if "sim_ok" in m20_h.columns:
        m20_h["sim_ok"] = m20_h["sim_ok"].fillna(False).astype(bool)

    t3 = {}
    _, base20_slot = m1.sim_standalone("20cm", m20_h, np.zeros(len(m20_h)), high_cb_mode="v51_exact", cm20_thr=82.0)
    t3["BASE_20cm_20bps"] = (base20_slot[base20_slot["buy_date"] >= "2023-01-03"].reset_index(drop=True), "20cm", False)
    for md in (8, 10, 15, 20, 25):
        sc_nat, meta_nat = wfc.run_expanding_scorecard_loop(
            m20_h, feature_cols=ix_cols, mode="delta_patch", wf_start_date="2023-01-03",
            min_warmup_trades=80, min_warmup_trades_rare=60, min_warmup_months=18,
            recalc_freq="daily", top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, max_delta=md, orig_score_col="v20_score", max_corr_orig=0.70,
        )
        _, s_nat = m1.sim_standalone("20cm", sc_nat, sc_nat["wf_delta_score"].to_numpy(float), high_cb_mode="v51_exact", cm20_thr=82.0)
        t3[f"std_d{md}_Mech_Native"] = (s_nat[s_nat["buy_date"] >= (meta_nat["wf_actual_start"] or "2023-01-03")].reset_index(drop=True), "20cm", False)

        sc_grd, meta_grd = w2f.run_expanding_interaction_loop(
            m20_h, mech_cols=ix_cols, base_cols=[], mode="delta_patch", wf_start_date="2023-01-03",
            min_warmup_trades=80, min_warmup_trades_rare=60, min_warmup_months=18,
            recalc_freq="daily", top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
            min_t_stat_dyn=2.6, min_synergy_t=1.6, shrink_tau=20.0, max_delta=md,
            orig_score_col="v20_score", max_corr_orig=0.70, top_base_k=20, max_dyn_keep=25,
        )
        _, s_grd = m1.sim_standalone("20cm", sc_grd, sc_grd["wf_delta_score"].to_numpy(float), high_cb_mode="v51_exact", cm20_thr=82.0)
        t3[f"std_d{md}_Mech_Guarded"] = (s_grd[s_grd["buy_date"] >= (meta_grd["wf_actual_start"] or "2023-01-03")].reset_index(drop=True), "20cm", False)

        sc_dyn, meta_dyn = w2f.run_expanding_interaction_loop(
            m20_h, mech_cols=ix_cols, base_cols=base_cols20, mode="delta_patch", wf_start_date="2023-01-03",
            min_warmup_trades=80, min_warmup_trades_rare=60, min_warmup_months=18,
            recalc_freq="daily", top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
            min_t_stat_dyn=2.6, min_synergy_t=1.6, shrink_tau=20.0, max_delta=md,
            orig_score_col="v20_score", max_corr_orig=0.70, top_base_k=20, max_dyn_keep=25,
        )
        _, s_dyn = m1.sim_standalone("20cm", sc_dyn, sc_dyn["wf_delta_score"].to_numpy(float), high_cb_mode="v51_exact", cm20_thr=82.0)
        t3[f"std_d{md}_Mech_Plus_Dyn20x19"] = (s_dyn[s_dyn["buy_date"] >= (meta_dyn["wf_actual_start"] or "2023-01-03")].reset_index(drop=True), "20cm", False)
    raw_tracks["20cm_Mech130"] = t3
    print(f"  [Track 3 Mech130] {len(t3)} variants | d15_Nat n={len(t3['std_d15_Mech_Native'][0])} | RSS={rss_mb()} MB")
    del m20, m20_h
    gc.collect()

    # =========================================================================
    # TRACK 4 & 5: W2A2 (3to4 MineSplit + Pry DropRed)
    # =========================================================================
    import _w2a2_common as cm2
    import run_w2a2_modules_1_to_4 as r2_14

    pm34, _ = cm2.load_master_pool_with_exec("3to4")
    fg34 = cm2.get_feature_groups(pm34, "3to4")
    t4 = {}
    _, b34_slot = cm2.sim_strategy_custom("3to4", pm34, "orig_score", cm2.ORIG_THRESHOLDS["3to4"], wf_only=False)
    t4["3to4_Baseline_030"] = (b34_slot[b34_slot["buy_date"] >= "2023-01-03"].reset_index(drop=True), "3to4", False)
    _, m4_det = r2_14.run_module4_minefield_dragon(
        "3to4", pm34, fg34["all_with_native"], v20_ctx,
        blacklist_qs=(10, 15, 20, 25), use_declustered=False, wf_start_date="2023-01-03",
    )
    out34 = m4_det["scored_df"]
    for q in (10, 15, 20, 25):
        safe_df = out34.copy()
        is_black = safe_df["wf_mine_score"] >= safe_df[f"wf_mine_thr_{q}"]
        safe_df["can_buy_hygiene"] = safe_df["can_buy_hygiene"] & (~is_black.fillna(False))
        _, s1 = cm2.sim_strategy_custom("3to4", safe_df, "orig_score", cm2.ORIG_THRESHOLDS["3to4"], wf_only=True)
        t4[f"M4_MineBL{q}_OrigScore"] = (s1, "3to4", False)
        for d_thr in ("top30", "top20", "top10", 65, 70):
            t_arg = f"wf_drag_{d_thr}" if isinstance(d_thr, str) else float(d_thr)
            t_lbl = d_thr if isinstance(d_thr, str) else f"abs{d_thr}"
            _, s2 = cm2.sim_strategy_custom("3to4", safe_df, "wf_dragon_score", t_arg, wf_only=True)
            t4[f"M4_MineBL{q}_Dragon_{t_lbl}"] = (s2, "3to4", False)
    raw_tracks["3to4_MineSplit"] = t4
    print(f"  [Track 4 3to4_MineSplit] {len(t4)} variants | BL15 n={len(t4['M4_MineBL15_OrigScore'][0])} | RSS={rss_mb()} MB")

    pmp, _ = cm2.load_master_pool_with_exec("pry")
    fgp = cm2.get_feature_groups(pmp, "pry")
    t5 = {}
    _, bp_slot = cm2.sim_strategy_custom("pry", pmp, "orig_score", cm2.ORIG_THRESHOLDS["pry"], wf_only=False)
    t5["pry_Baseline_030"] = (bp_slot[bp_slot["buy_date"] >= "2023-01-03"].reset_index(drop=True), "pry", False)
    for t_cut, tag in ((0.0, "t0"), (-0.5, "tm05")):
        pr_df, _ = r2_14.run_causal_neg_prune_atoms("pry", pmp, fgp["native_af"], t_cut=t_cut, wf_start_date="2023-01-03")
        _, s_pr = cm2.sim_strategy_custom("pry", pr_df, "wf_pruned_score", cm2.ORIG_THRESHOLDS["pry"], wf_only=True)
        t5[f"M1_WF_DropNeg_{tag}"] = (s_pr, "pry", False)
    for afc in fgp["native_af"]:
        pm_l = pmp.copy(); pm_l["sc_loo"] = pm_l["orig_score"] - pm_l[afc].fillna(0.0)
        _, s_l = cm2.sim_strategy_custom("pry", pm_l, "sc_loo", cm2.ORIG_THRESHOLDS["pry"], wf_only=False)
        t5[f"M1_LOO_Drop_{afc}"] = (s_l[s_l["buy_date"] >= "2023-01-03"].reset_index(drop=True), "pry", False)
        if afc == "spry_af_lock50":
            _, s_l2 = cm2.sim_strategy_custom("pry", pm_l, "sc_loo", 155.0, wf_only=False)
            t5["M1_LOO_Drop_spry_af_lock50_thr155"] = (s_l2[s_l2["buy_date"] >= "2023-01-03"].reset_index(drop=True), "pry", False)
    for use_dec, prefix in [(True, "Dec"), (False, "Naive")]:
        for md in (10, 15, 25):
            _, _, s_mb, _ = r2_14.run_mode_b_custom("pry", pmp, fgp["all_with_native"], v20_ctx, max_delta=md, max_corr_orig=0.70, use_declustered=use_dec)
            t5[f"M3_{prefix}_ModeB_d{md}"] = (s_mb, "pry", False)
    raw_tracks["pry_DropRed"] = t5
    print(f"  [Track 5 pry_DropRed] {len(t5)} variants | RSS={rss_mb()} MB")
    del pm34, pmp, m4_det, out34
    gc.collect()

    # =========================================================================
    # TRACK 10: W2B1 (20cm 10-19.8% Surge Top Daily Specs)
    # =========================================================================
    import w2b1_core_lib as b1lib
    df_b1 = pd.read_parquet(f"{W2B1_DIR}/w2b1_cand_pool_pit.parquet")
    core_fcols = [c for c in b1lib.CORE_96_FEATURES if c in df_b1.columns]
    t10 = {}
    b1_specs = [
        ("ModeM", "P0_Full", "E1_all", "X2_T2_Close", "t1t2_7pct", core_fcols),
        ("ModeM", "P1_Strong", "E4_deep", "X3_20cm_4Branch", "t1t2_7pct", core_fcols),
        ("ModeA", "P1_Strong", "E3_weak", "X3_20cm_4Branch", "none", core_fcols),
    ]
    for mode_lbl, pn, en, ex, mine_m, fcols_u in b1_specs:
        sub_b1 = b1lib.slice_pool_entry_exit(df_b1, pn, en, ex)
        if mine_m != "none":
            mined_df, _ = b1lib.run_causal_mine_removal(
                sub_b1, fcols_u, mine_mode=mine_m, recalc_freq="daily",
                mine_start_date="2021-09-01", min_warmup_trades=80, min_warmup_months=6,
                top_k_mine=10, blacklist_pct=20.0,
            )
            work_df = mined_df[mined_df["is_safe_causal"]].copy().reset_index(drop=True)
        else:
            work_df = sub_b1.copy()
        df_h1 = wfm.prepare_hygiene_and_net_ret(work_df, fee_rt=0.0)
        for tk in (8, 12, 15):
            sc_1, _ = wfc.run_expanding_scorecard_loop(
                df_h1, feature_cols=fcols_u, mode="scorecard_0_100",
                wf_start_date="2023-01-03", min_warmup_trades=80,
                min_warmup_trades_rare=45 if mine_m != "none" else 50,
                min_warmup_months=18, recalc_freq="daily", top_k=tk, min_k=5,
                max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
            )
            for th in ("all_cands", "top20", "top10", "top5", 75, 80, 85):
                tname = str(th) if not isinstance(th, int) else f"abs_{th}"
                targ = None if th == "all_cands" else (f"wf_thr_{th}" if isinstance(th, str) else float(th))
                _, s_b1 = wfm.select_single_slot_trades(sc_1, score_col="wf_score", threshold=targ, wf_only=True)
                vkey = f"{mode_lbl}__{pn}__{en}__{ex}__{mine_m}__k{tk}::{tname}"
                t10[vkey] = (s_b1, None, True)
    raw_tracks["20cm_Surge10_19_W2B1"] = t10
    del df_b1
    gc.collect()
    print(f"  [Track 10 W2B1] {len(t10)} variants | RSS={rss_mb()} MB")

    # Now preload ONLY bars needed by executed trades across all raw_tracks!
    all_sdfs = [tup[0] for tmap in raw_tracks.values() for tup in tmap.values()]
    mtm = CompactNumpyMTM(cal_dts, end_cutoff="2026-11-16")
    mtm.preload_needed_pairs(all_sdfs)
    print(f"  CompactNumpyMTM preloaded {len(mtm.bar_lu)} trade-day bars | RSS={rss_mb()} MB")

    tracks = {}
    for tname, tmap in raw_tracks.items():
        out_m = {}
        for vname, (sdf, st_ovr, op_ovr) in tmap.items():
            dre, diff = mtm.build_daily_ret(sdf, strat_override=st_ovr, buy_at_open_override=op_ovr)
            drg, _ = wfm.build_daily_mtm_returns(sdf, cal_dts, mtm_col=None)
            # Keep slim slot_df columns to minimize pickle footprint
            keep_cols = [c for c in ["buy_date", "exit_date", "code", "name", "strategy", "net_ret", "buy_hhmm", "exit_hhmm", "wf_score", "v20_score"] if c in sdf.columns]
            out_m[vname] = {"slot_df": sdf[keep_cols].copy(), "dr_exact": dre, "dr_geom": drg, "diff": diff}
        tracks[tname] = out_m

    out_pkl = f"{OUT_DIR}/_cache_tracks_partA.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump(tracks, f)
    print(f"[Part2A DONE in {time.time()-t0:.1f}s] Saved -> {out_pkl} | Peak RSS={rss_mb()} MB")


if __name__ == "__main__":
    main()
