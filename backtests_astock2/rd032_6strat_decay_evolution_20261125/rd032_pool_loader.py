#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Load all 6 V20.0 pools <= as_of, reconstruct exact active atomic factors (max_diff=0), and attach 40 evo features."""
import os
import pickle
import sys
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation!"
from rd032_common import OUT_DIR, RD028_DIR, SIM
from rd032_pool_loader_evo import attach_40_evo_features


def _load_1to2_atomic(p12: pd.DataFrame, as_of: str, rebuild_1to2: bool) -> pd.DataFrame:
    cache_p = f"{OUT_DIR}/cache_1to2_atomic_703.parquet"
    if (not rebuild_1to2) and as_of <= "2026-11-25" and os.path.exists(cache_p):
        c12 = pd.read_parquet(cache_p)
    else:
        sys.path.insert(0, f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117")
        import upgrade_1to2_pit as u12
        hf = u12.build_signals_and_data_pit(as_of)["hist_fb"].copy()
        hf["code"] = hf["c6"].astype(str).str.zfill(6)
        hf["buy_date"] = hf["d2_dt"].astype(str).str[:10]
        csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hf["csrc_ind"]]
        ht = hf["plate"].astype(str).str.contains(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)", regex=True).values
        hm = (hf["notice_hard"] | hf["is_ma"]).values
        hf["atom_pure_outsider"] = [a and (cs in u12.CSRC_PURE_OUTSIDER) and (not b) for a, cs, b in zip(ht, csrc_sec, hm)]
        hf["atom_is_gran"] = (hf["is_pioneer_word"] | hf["has_new_term"] | hf["own_new_term"] | (hf["sub_cluster_cnt"] >= 2)).astype(int)
        hf["atom_s_elo_hot"] = (hf["s_elo"] >= 105.0).astype(int)
        hf["atom_s_elo_cold"] = (hf["s_elo"] <= 95.0).astype(int)
        hf["atom_wk_mask"] = (hf["gap_days"] >= 3).astype(int)
        hf["atom_rk_theme_1"] = (hf["rk_theme"] == 1).astype(int)
        hf["atom_p_sz_ge4"] = (hf["p_sz"] >= 4).astype(int)
        hf["atom_hard_cat"] = (hf["notice_hard"] | hf["is_ma"]).astype(int)
        hf["atom_dd20_deep"] = (hf["f_dd20_d0"].fillna(0.9) <= 0.86).astype(int)
        hf["atom_clean_brk60"] = (hf["clean_brk60"] == 1).astype(int)
        hf["atom_true_buy_rk1"] = (hf["true_buy_rk"] == 1).astype(int)
        hf["atom_mkt_open_top3"] = (hf["buyable_mkt_open_rk"] <= 3).astype(int)
        hf["atom_open_sweet"] = hf["d2_o_pct"].between(0.040, 0.082).astype(int)
        hf["atom_front_lock1"] = ((hf["front_lock_cnt"] == 1) & (hf["true_buy_rk"] == 1) & hf["mkt_yizi_cnt"].isin([1, 2])).astype(int)
        hf["atom_front_lock_crowd"] = (hf["front_lock_cnt"] >= 2).astype(int)
        st_col = hf["first_seal_time"].fillna("99:99:99")
        oc_col = hf["open_board_count"].fillna(0)
        hf["atom_tight_open1"] = ((oc_col == 1) & (st_col <= "10:30:00") & (hf["d1_seal_tightness"] >= 38.0)).astype(int)
        hf["atom_has_ir"] = hf["has_ir_pit"].astype(int)
        hf["atom_cap_yizi_gt90"] = ((hf["plate_d2_yizi_cnt"] >= 1) & (hf["mcap"] > 90.0)).astype(int)
        hf["atom_climax_95"] = (hf["mkt_zt_cnt"] >= 95).astype(int)
        hf["atom_seal_80"] = (hf["mkt_seal_rate"] >= 0.80).astype(int)
        c12 = hf[[c for c in hf.columns if c in ("buy_date", "code", "score_active", "s_prior_wk", "s_quant_dual", "xq_pre_d2") or c.startswith("atom_")]]
    m = p12.merge(c12.drop_duplicates(["buy_date", "code"]), on=["buy_date", "code"], how="left")
    assert (m["base_score"] - m["score_active"]).abs().max() < 1e-6, "1to2 parity error!"
    m["atom_v20_fb20_pen"] = (m["v20_pen"] < 0).astype(int)
    m["atom_xq_cold"] = (m["xq_pre_d2"].fillna(0) < 4).astype(int)
    return m


def _load_2to3_atomic(p23: pd.DataFrame) -> pd.DataFrame:
    c23 = pickle.load(open(f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_2to3_pit_20261116.pkl", "rb"))
    ga = c23["gated_all"].copy()
    ga["code"] = ga["code"].astype(str).str.zfill(6)
    sys.path.insert(0, f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117")
    import upgrade_2to3_pit as u23
    comp = u23.compute_v20_components(ga)
    assert np.max(np.abs((60.0 + comp.sum(axis=1)) - ga["score_v2"].to_numpy())) < 1e-6, "2to3 parity error!"
    fcols = [f"af_{i:02d}" for i in range(18)]
    for i, fc in enumerate(fcols):
        ga[fc] = comp[:, i]
    return p23.merge(ga[["buy_date", "code"] + fcols].drop_duplicates(["buy_date", "code"]), on=["buy_date", "code"], how="left")


def _load_3to4_atomic(p34: pd.DataFrame) -> pd.DataFrame:
    c34 = pickle.load(open(f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4/pit_exit_cache_full.pkl", "rb"))
    cd = c34["cand_df"].copy()
    cd["code"] = cd["code"].astype(str).str.zfill(6)
    fs = pd.to_numeric(cd["first_seal_time"].astype(str).str.replace(":", "").str[:4], errors="coerce").fillna(9999).astype(int)
    lb = (cd["lock_top10"] < 45.0) & (cd["real_free_mcap"] < 45.0)
    cols_v4 = [
        np.where(cd["px_d3"] <= 20.0, 8.0, 0.0),
        np.where(cd["mkt_max_board_prev"] <= 4, 8.0, 0.0),
        np.where(cd["mkt_zt_prev"].between(35, 85), 5.0, 0.0),
        np.where((cd["plate_fb_ho_cnt"] >= 2) & (cd["plate_fb_yz_cnt"] == 0), 4.0, 0.0),
        np.where(cd["lhb_lh_cnt"] == 0, 4.0, 0.0),
        np.where(cd["p_elo"] >= 115.0, 3.0, 0.0),
        np.where(cd["prev_3b_dt_cnt"] == 0, 3.0, 0.0),
        np.where(cd["prev_to"].between(9.5, 28.0), 3.0, 0.0),
        np.where(fs.between(936, 1030), 3.0, 0.0),
        np.where(cd["has_ex_reg"], -12.0, 0.0),
        np.where(cd["surf_yz_buy"], -12.0, 0.0),
        np.where(~cd["is_top1_3b_open"], -12.0, 0.0),
        np.where(cd["plate_peers_open_avg"] < -0.015, -10.0, 0.0),
        np.where(lb, -10.0, 0.0),
        np.where(~cd["prev_to"].between(8.5, 31.0), -10.0, 0.0),
        np.where((cd["csi_1d_prev"] <= -0.020) | (cd["csi_5d_prev"] <= -0.030), -8.0, 0.0),
        np.where(cd["plate_fb_yz_cnt"] >= 1, -7.0, 0.0),
        np.where(cd["lhb_lh_cnt"] >= 3, -5.0, 0.0),
        np.where(cd["prev_3b_dt_cnt"] >= 2, -4.0, 0.0),
        np.where(cd["buy_month"].isin([1, 5]), -4.0, 0.0),
        np.where(cd["pos20_d0"] <= 0.40, 5.0, 0.0),
        np.where(cd["xq_cnt_2d"] >= 4, -15.0, 0.0),
    ]
    fcols = [f"af_{i:02d}" for i in range(22)]
    for fc, arr in zip(fcols, cols_v4):
        cd[fc] = arr
    m = p34.merge(cd[["buy_date", "code"] + fcols].drop_duplicates(["buy_date", "code"]), on=["buy_date", "code"], how="left")
    assert (78.0 + m[fcols].sum(axis=1) - m["base_score"]).abs().max() < 1e-6, "3to4 parity error!"
    return m


def _load_high_atomic(ph: pd.DataFrame) -> pd.DataFrame:
    v5 = pd.read_pickle(f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/v5_enriched_119.pkl")
    v5["code"] = v5["code"].astype(str).str.zfill(6)
    v5["af_brk_r10"] = np.where(v5["brk_r10"] >= 0.20, 12.0, -8.0)
    v5["af_n_zt_low"] = np.where(v5["n_zt"] < 70, 10.0, np.where(v5["n_zt"] >= 95, -10.0, 0.0))
    v5["af_csi5"] = np.where(v5["csi5"] >= -0.005, 8.0, np.where(v5["csi5"] < -0.025, -10.0, 0.0))
    v5["af_d1_op_neg"] = np.where(v5["d1_op"] < 0.0, 8.0, 0.0)
    v5["af_op2_neg"] = np.where(v5["op2"] < 0.0, 8.0, np.where(v5["op2"].between(0.0, 0.025), 6.0, 0.0))
    v5["af_d0_tight"] = np.where((v5["obc"] == 0) & (v5["d0_tight"] >= 35.0), 6.0, 0.0)
    v5["af_pelo_cool"] = np.where((v5["pelo"] < 135.0) & (~v5["dom"]), 6.0, 0.0)
    v5["af_lh1_zero"] = np.where(v5["lh1"] == 0, 6.0, np.where(v5["lh1"] == 2, -10.0, 0.0))
    v5["af_inst_pen"] = np.where(v5["in1"] >= 1, -6.0, 0.0)
    v5["af_px_le20"] = np.where(v5["low_price_le20"], 5.0, np.where(v5["high_price_gt35"], -10.0, 0.0))
    v5["af_turn_b4"] = np.where(v5["turn_boards_ge4"], 5.0, np.where(v5["turn_boards_cnt"] <= 2, -5.0, 0.0))
    v5["af_d1_dip6"] = np.where(v5["d1_deep_dip_le6"], 5.0, 0.0)
    v5["af_lock_fmcap"] = np.where((v5["lock"] >= 45.0) | (v5["fmcap"] >= 45.0), 6.0, -6.0)
    v5["af_qu_in"] = np.where((v5["qu1"] >= 1) & (v5["lh1"] <= 1), 4.0, 0.0)
    v5["af_kpl_ge5"] = np.where(v5["kpl_hist_1y_has_ge5"], 6.0, np.where(v5["kpl_hist_3y_has_ge5"], 3.0, 0.0))
    v5["af_old_stk_th"] = np.where(v5["kpl_old_stock_old_theme"], 3.0, np.where(v5["kpl_old_stock_new_theme"], -5.0, 0.0))
    v5["af_d0_top_lock"] = np.where(v5["lhb_d0_top_locked"], 5.0, 0.0)
    v5["af_d1_lh_hvy"] = np.where(v5["lhb_d1_lhasa_heavy"], -10.0, 0.0)
    v5["af_d1_net_pos"] = np.where(v5["lhb_d1_net_positive"], -5.0, 0.0)
    v5["af_d0_surf"] = np.where(v5["lhb_d0_day_surf_buy"], -6.0, 0.0)
    v5["af_d0_early"] = np.where(v5["kpl_d0_seal_early_0935"], -5.0, 0.0)
    v5["af_tech_pen"] = np.where(v5["kpl_reason_tech"], -4.0, 0.0)
    af_cols = [c for c in v5.columns if c.startswith("af_")]
    m = ph.merge(v5[["buy_date", "code"] + af_cols].drop_duplicates(["buy_date", "code"]), on=["buy_date", "code"], how="left")
    assert (60.0 + m[af_cols].sum(axis=1) - m["base_score"]).abs().max() < 1e-6, "high parity error!"
    return m


def _load_pry_atomic(ppr: pd.DataFrame) -> pd.DataFrame:
    fp = pickle.load(open(f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry/_cache_feats_830.pkl", "rb"))
    sub = fp["sub"].copy()
    sub["code"] = sub["code"].astype(str).str.zfill(6)
    sub["af_bias10"] = np.where(sub["bias10"] <= -0.15, 20.0, 0.0)
    sub["af_down4"] = np.where(sub["down_streak"] >= 4, 15.0, 0.0)
    sub["af_ma20_22"] = np.where(sub["prev_c_ma20"] <= -0.22, 15.0, 0.0)
    sub["af_fmcap25"] = np.where(sub["real_free_mcap"] <= 25.0, 15.0, 0.0)
    sub["af_mkt_zt12"] = np.where(sub["mkt_open_zt_0925"] >= 12, 15.0, 0.0)
    sub["af_is_yang"] = np.where(sub["is_yang"], 10.0, 0.0)
    sub["af_vr15"] = np.where(sub["prev_vr"] >= 1.5, 10.0, 0.0)
    sub["af_lock50"] = np.where(sub["lock_top10"] >= 50.0, 10.0, 0.0)
    sub["af_inst_b"] = np.where(sub["inst_buy_prev"] > 0, 10.0, 0.0)
    sub["af_lhasa_25"] = np.where(sub["lhasa_sh_prev"] > 0.25, -20.0, 0.0)
    af_cols = [c for c in sub.columns if c.startswith("af_")]
    m = ppr.merge(sub[["buy_date", "code"] + af_cols].drop_duplicates(["buy_date", "code"]), on=["buy_date", "code"], how="left")
    assert (100.0 + m[af_cols].sum(axis=1) - m["base_score"]).abs().max() < 1e-6, "pry parity error!"
    return m


def load_all_6_pools(as_of: str, prev_td: dict, sh_idx: dict, sz_idx: dict, rebuild_1to2: bool = False) -> dict[str, pd.DataFrame]:
    raw = {}
    for st in ("1to2", "2to3", "3to4", "high", "pry", "20cm"):
        df = pd.read_parquet(f"{RD028_DIR}/pool_{st}_oldhot.parquet")
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["buy_date"] = df["buy_date"].astype(str).str[:10]
        df["exit_date"] = df["exit_date"].astype(str).str[:10]
        df = df[(df["buy_date"] <= as_of) & (df["exit_date"] <= as_of) & df["net_ret"].notna()].copy()
        if st == "1to2":
            df = df[df["sim_ok"].astype(bool)].copy()
        raw[st] = df.reset_index(drop=True)

    raw["1to2"] = _load_1to2_atomic(raw["1to2"], as_of, rebuild_1to2)
    raw["2to3"] = _load_2to3_atomic(raw["2to3"])
    raw["3to4"] = _load_3to4_atomic(raw["3to4"])
    raw["high"] = _load_high_atomic(raw["high"])
    raw["pry"] = _load_pry_atomic(raw["pry"])

    p23_20 = pd.read_parquet(f"{SIM}/backtests_astock2/rd023_6strat_synergy_20261124/to_20cm/rd023_pool_enriched.parquet")
    p23_20["buy_date"] = p23_20["f1_dt"].astype(str)
    p23_20["code"] = p23_20["c6"].astype(str).str.zfill(6)
    ex_cols = [c for c in p23_20.columns if c not in raw["20cm"].columns]
    raw["20cm"] = raw["20cm"].merge(p23_20[["buy_date", "code"] + ex_cols].drop_duplicates(["buy_date", "code"]), on=["buy_date", "code"], how="left")

    return attach_40_evo_features(raw, as_of, prev_td, sh_idx, sz_idx)
