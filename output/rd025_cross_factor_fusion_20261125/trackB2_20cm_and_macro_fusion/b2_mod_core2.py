#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Track B2 Core 2: V20.0 6-Strategy Portfolio Macro/Market Switch Audit (Mode A, Mode B Causal Pool6, Mode C 0.5x)."""
import sys
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
sys.path.insert(0, f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority")
sys.path.insert(0, f"{SIM}/output/six_strategies_v20_upgrade_20261124/partD_final_jianyan")
import tier_priority_engine as tpe
import partD2_mod_base as dbase
from b2_mod_eval import WINDOWS_V20, bh_fdr, cscv_pbo_matrix, eval_all_windows, paired_daily_pval


def build_macro_switches(df_m: pd.DataFrame) -> list[tuple[str, str, str, np.ndarray, str]]:
    """Returns (sw_id, group, scope ['ALL'|'HIGH_ONLY'], skip_mask_bool, desc) where True = block/risk-off."""
    hi_strats = df_m["strategy"].isin(["3to4", "high", "2to3"]).to_numpy()
    sw = [
        ("SW_NT_fake_supp", "国家队V3", "ALL", (df_m["fake_supp_d1"].fillna(0) == 1).to_numpy(), "假护盘抽血日空仓"),
        ("SW_NT_rd019_trap", "国家队V3", "ALL", (df_m["rd019_trap_d1"].fillna(0) == 1).to_numpy(), "RD019期现双爆量陷阱空仓"),
        ("SW_NT_redemp_press", "国家队V3", "ALL", (df_m["redemp_press_d1"].fillna(0) == 1).to_numpy(), "国家队/机构赎回压力空仓"),
        ("SW_NT_wflow_le_m80", "国家队V3", "ALL", (df_m["etf22_wflow_yi_d1"].fillna(0) <= -80.0).to_numpy(), "单日纯净净赎回<=-80亿空仓"),
        ("SW_NT_taper_stop", "国家队V3", "ALL", (df_m["nt_tapering_stop_d1"].fillna(0) == 1).to_numpy(), "国家队连续放量转流出空仓"),
        ("SW_NT_high_overheat", "国家队V3", "ALL", (df_m["high_overheat_d1"].fillna(0) == 1).to_numpy(), "MA20上+20日>=5%高位过热空仓"),
        ("SW_NT_score_lt30", "国家队V3", "ALL", (df_m["score_eod_d1"].fillna(20) < 30).to_numpy(), "国家队V3得分<30空仓"),
        ("SW_NT_score_ge40_only", "国家队V3", "ALL", ~(df_m["score_eod_d1"].fillna(20) >= 40).to_numpy(), "仅国家队V3>=40脉冲救市做"),
        ("SW_NT_t1_skew", "国家队V3", "ALL", (df_m["t1_t2_sync_d1"].fillna(0) == -1).to_numpy(), "一队偏心抽血小盘日空仓"),
        ("SW_POL_net10_lt0", "证监会22核", "ALL", (df_m["pol_22_net_10d"].fillna(0) < 0).to_numpy(), "近10日证监会22核净逆风空仓"),
        ("SW_POL_neg20_ge2", "证监会22核", "ALL", (df_m["pol_22_neg_20d"].fillna(0) >= 2).to_numpy(), "近20日负面核心政策>=2空仓"),
        ("SW_POL_exch_surv5", "证监会22核", "ALL", (df_m["pol_exch_surv_5d"].fillna(0) >= 1).to_numpy(), "交易所重点监控/核查5日内空仓"),
        ("SW_US_ixic_dn15", "美股隔夜", "ALL", (df_m["us_ixic_ret"].fillna(0) <= -0.015).to_numpy(), "隔夜纳指<=-1.5%空仓"),
        ("SW_US_ixic_dn20", "美股隔夜", "ALL", (df_m["us_ixic_ret"].fillna(0) <= -0.020).to_numpy(), "隔夜纳指<=-2.0%空仓"),
        ("SW_US_vix_ge25", "美股隔夜", "ALL", (df_m["us_vix_level"].fillna(20) >= 25.0).to_numpy(), "隔夜VIX>=25恐慌区空仓"),
        ("SW_US_ixic15_low20", "美股隔夜", "ALL", ((df_m["us_ixic_ret"].fillna(0) <= -0.015) & (df_m["mkt20_0925_gap"].fillna(0) <= -0.005)).to_numpy(), "隔夜纳指<=-1.5%叠低开空仓"),
        ("SW_RD012_shrink_bank", "RD012防御", "ALL", (df_m["rd012_shrink_bank_fake_d1"].fillna(0) == 1).to_numpy(), "缩量银行假护盘空仓"),
        ("SW_RD012_panic_crash", "RD012防御", "ALL", (df_m["rd012_panic_crash_d1"].fillna(0) == 1).to_numpy(), "放量暴跌日(量>=20均&300<=-2%)空仓"),
        ("SW_RD012_tech_retr", "RD012防御", "ALL", (df_m["rd012_tech_retreat_d1"].fillna(0) == 1).to_numpy(), "科技大退潮日(<=-2%)空仓"),
        ("SW_RD013_brk_lt040", "RD013断板反包", "ALL", (df_m["brk_r10_d1"].fillna(0.05) < 0.040).to_numpy(), "断板反包率<4.0%冰冷区空仓"),
        ("SW_RD013_brk_lt035", "RD013断板反包", "ALL", (df_m["brk_r10_d1"].fillna(0.05) < 0.035).to_numpy(), "断板反包率<3.5%极冷区空仓"),
        ("SW_RD013_reb4_lt20", "RD013断板反包", "ALL", (df_m["reb4_10d_d1"].fillna(0.3) < 0.20).to_numpy(), "4板+高标反抽率<20%空仓"),
        ("SW_GAP_defA_all", "连板断层", "ALL", (df_m["gap_void_defA_d1"].fillna(0) == 1).to_numpy(), "连板断层定义A全组合空仓"),
        ("SW_GAP_defA_high_only", "连板断层", "HIGH_ONLY", ((df_m["gap_void_defA_d1"].fillna(0) == 1) & hi_strats).to_numpy(), "连板断层A禁高位接力(保一进二/撬板/20cm)"),
        ("SW_GAP_defB_all", "连板断层", "ALL", (df_m["gap_ice_defB_d1"].fillna(0) == 1).to_numpy(), "连板断层定义B冰点全组合空仓"),
        ("SW_GAP_defB_high_only", "连板断层", "HIGH_ONLY", ((df_m["gap_ice_defB_d1"].fillna(0) == 1) & hi_strats).to_numpy(), "连板断层B禁高位接力"),
        ("SW_GAP_old_drag_high", "连板断层", "HIGH_ONLY", ((df_m["old_dragon_brk_1_2d_d1"].fillna(0) == 1) & hi_strats).to_numpy(), "老妖断板1-2天禁高位接力"),
        ("SW_ICE_dt_ge20", "全市场跌停", "ALL", (df_m["mkt_all_nonst_dt_d1"].fillna(0) >= 20).to_numpy(), "全市场跌停>=20家空仓"),
        ("SW_ICE_dt_ge35", "全市场跌停", "ALL", (df_m["mkt_all_nonst_dt_d1"].fillna(0) >= 35).to_numpy(), "全市场跌停>=35家空仓"),
        ("SW_ICE_dt_ge50", "全市场跌停", "ALL", (df_m["mkt_all_nonst_dt_d1"].fillna(0) >= 50).to_numpy(), "全市场跌停>=50家空仓"),
        ("SW_ICE_0925_zt_lt5", "全市场竞价", "ALL", (df_m["mkt_all_nonst_0925_zt"].fillna(99) < 5).to_numpy(), "09:25全市场竞价涨停<5家熔断"),
        ("SW_ST15_smb_le_m3", "15年风格", "ALL", (df_m["st15_small_minus_big_5d_d1"].fillna(0) <= -0.03).to_numpy(), "近5日小微盘跑输茅指数<=-3%空仓"),
        ("SW_ST15_hs300_lt_ma20", "15年风格", "ALL", (df_m["hs300_close_d1"] < df_m["hs300_ma20_d1"]).fillna(False).to_numpy(), "沪深300处于MA20下方空仓"),
        ("SW_ST15_dd60_le_m8", "15年风格", "ALL", (df_m["hs300_dd60_d1"].fillna(0) <= -0.08).to_numpy(), "沪深300 60日回撤<=-8%空仓"),
    ]
    return sw


def run_core2_v20_suite(mkt_buy_pit: pd.DataFrame, bar_lu: dict, cal_dts_all: list[str], sh300: dict, all_sh_dts: list[str], df20: pd.DataFrame | None = None) -> dict:
    cal_v20 = [d for d in cal_dts_all if "2021-11-16" <= d <= "2026-11-16"]
    dt_idx = {d: i for i, d in enumerate(cal_v20)}

    pool6 = pd.concat([tpe.load_strategy_csv(st, p, "2021-11-16", "2026-11-16") for st, p in dbase.CSV_MAP.items()], ignore_index=True)
    untrig_df = tpe.build_untriggered_baseline_pool(pool6, "2021-11-16", "2026-11-16")
    tr_base, _ = tpe.run_single_slot(pool6, lambda d: d["tier"].map(dbase.S2C_MAP).fillna(999).to_numpy(), untrig_df=untrig_df, timing_mode="s_tier_reserve_only")
    assert len(tr_base) == 278 and abs(float(np.prod(1.0 + tr_base["net_ret"])) - 69134091.1181) < 1.0
    v20_csv = pd.read_csv(f"{SIM}/output/six_strategies_v20_upgrade_20261124/partD_final_jianyan/ledger_combined_6strat_v20_slot1_clean.csv")
    assert len(v20_csv) == 278 and float(np.max(np.abs(tr_base["net_ret"].to_numpy() - v20_csv["net_ret"].to_numpy()))) < 1e-12

    dr_base, mtm_err = tpe.build_daily_mtm_series(tr_base, cal_v20, dt_idx, bar_lu)
    w_base = eval_all_windows(tr_base, tr_base, dr_base, cal_v20, dt_idx, sh300, all_sh_dts, WINDOWS_V20)

    tr_m = pd.concat([tr_base.reset_index(drop=True), mkt_buy_pit.reindex(tr_base["buy_date"]).reset_index(drop=True)], axis=1)
    p6_m = pd.concat([pool6.reset_index(drop=True), mkt_buy_pit.reindex(pool6["buy_date"]).reset_index(drop=True)], axis=1)
    ut_m = pd.concat([untrig_df.reset_index(drop=True), mkt_buy_pit.reindex(untrig_df["buy_date"]).reset_index(drop=True)], axis=1)

    sw_tr = build_macro_switches(tr_m)
    sw_p6 = build_macro_switches(p6_m)
    sw_ut = build_macro_switches(ut_m)

    res_A, res_B, res_C = [], [], []
    dr_mat_A, dr_mat_B, p_A, p_B = [dr_base], [dr_base], [], []
    for i, (sid, grp, scope, skip_tr, desc) in enumerate(sw_tr):
        # Mode A: Static Filter on 278
        sub_A = tr_base[~skip_tr].copy()
        mod_A = int(skip_tr.sum())
        dr_A, _ = tpe.build_daily_mtm_series(sub_A, cal_v20, dt_idx, bar_lu)
        w_A = eval_all_windows(sub_A, sub_A, dr_A, cal_v20, dt_idx, sh300, all_sh_dts, WINDOWS_V20)
        pvA = paired_daily_pval(dr_A, dr_base)
        dr_mat_A.append(dr_A); p_A.append(pvA)
        res_A.append({
            "switch_id": sid, "group": grp, "scope": scope, "desc": desc, "mod_n": mod_A, "p_daily": round(pvA, 5),
            "d_IS_sharpe": round(w_A["IS"]["daily_sharpe"] - w_base["IS"]["daily_sharpe"], 3),
            "d_OOS_BLIND_sharpe": round(w_A["OOS_BLIND"]["daily_sharpe"] - w_base["OOS_BLIND"]["daily_sharpe"], 3),
            "d_Y26_sharpe": round(w_A["Y26"]["daily_sharpe"] - w_base["Y26"]["daily_sharpe"], 3),
            "d_IS_mdd": round(w_A["IS"]["daily_mdd_pct"] - w_base["IS"]["daily_mdd_pct"], 2),
            "d_OOS_BLIND_mdd": round(w_A["OOS_BLIND"]["daily_mdd_pct"] - w_base["OOS_BLIND"]["daily_mdd_pct"], 2),
            "d_Y26_mdd": round(w_A["Y26"]["daily_mdd_pct"] - w_base["Y26"]["daily_mdd_pct"], 2),
            "windows": w_A,
        })

        # Mode B: Causal re-rotation on pool6 + untrig
        skip_p6, skip_ut = sw_p6[i][3], sw_ut[i][3]
        sub_p6 = pool6[~skip_p6].copy()
        sub_ut = untrig_df[~skip_ut].copy()
        tr_B, _ = tpe.run_single_slot(sub_p6, lambda d: d["tier"].map(dbase.S2C_MAP).fillna(999).to_numpy(), untrig_df=sub_ut, timing_mode="s_tier_reserve_only")
        dr_B, _ = tpe.build_daily_mtm_series(tr_B, cal_v20, dt_idx, bar_lu)
        w_B = eval_all_windows(tr_B, tr_B, dr_B, cal_v20, dt_idx, sh300, all_sh_dts, WINDOWS_V20)
        pvB = paired_daily_pval(dr_B, dr_base)
        base_k = set(zip(tr_base["buy_date"], tr_base["code"], tr_base["strategy"]))
        cur_k = set(zip(tr_B["buy_date"], tr_B["code"], tr_B["strategy"])) if not tr_B.empty else set()
        mod_B = len(base_k ^ cur_k)
        dr_mat_B.append(dr_B); p_B.append(pvB)
        res_B.append({
            "switch_id": sid, "group": grp, "scope": scope, "desc": desc, "mod_n": int(mod_B), "p_daily": round(pvB, 5),
            "d_IS_sharpe": round(w_B["IS"]["daily_sharpe"] - w_base["IS"]["daily_sharpe"], 3),
            "d_OOS_BLIND_sharpe": round(w_B["OOS_BLIND"]["daily_sharpe"] - w_base["OOS_BLIND"]["daily_sharpe"], 3),
            "d_Y26_sharpe": round(w_B["Y26"]["daily_sharpe"] - w_base["Y26"]["daily_sharpe"], 3),
            "d_IS_mdd": round(w_B["IS"]["daily_mdd_pct"] - w_base["IS"]["daily_mdd_pct"], 2),
            "d_OOS_BLIND_mdd": round(w_B["OOS_BLIND"]["daily_mdd_pct"] - w_base["OOS_BLIND"]["daily_mdd_pct"], 2),
            "d_Y26_mdd": round(w_B["Y26"]["daily_mdd_pct"] - w_base["Y26"]["daily_mdd_pct"], 2),
            "windows": w_B,
        })

        # Mode C: 0.5x Sizing on triggered days (exact 0.5 cash + 0.5 stock MTM without exit/entry day collision bug)
        w_vec = np.where(skip_tr, 0.5, 1.0)
        tr_C = tr_base.copy()
        tr_C["net_ret"] = tr_C["net_ret"] * w_vec
        day_mult_C = np.ones(len(cal_v20), dtype=float)
        for r, w_i in zip(tr_base.itertuples(index=False), w_vec):
            bi, ei = dt_idx.get(r.buy_date), dt_idx.get(r.exit_date)
            if bi is None: continue
            bb = bar_lu.get((r.code, r.buy_date))
            b_adj = float(r.buy_price_val) if (r.is_adj_px and pd.notna(r.buy_price_val)) else ((float(r.buy_price_val) * bb[4]) if (pd.notna(r.buy_price_val) and bb) else (bb[1] * bb[4] if bb else 1.0))
            if b_adj <= 0: b_adj = 1.0
            prev_E, last_c = 1.0, b_adj
            end_l = ei if (ei is not None and ei > bi) else len(cal_v20)
            for t in range(bi, end_l):
                bt = bar_lu.get((r.code, cal_v20[t]))
                cur_c = (bt[1] * bt[4]) if (bt and bt[1] * bt[4] > 0) else last_c
                cur_E = (1.0 - w_i) + w_i * (cur_c / b_adj)
                day_mult_C[t] *= (cur_E / prev_E)
                prev_E, last_c = cur_E, cur_c
            if ei is not None and ei > bi:
                day_mult_C[ei] *= ((1.0 + w_i * float(r.net_ret)) / prev_E)
        dr_C = day_mult_C - 1.0
        w_C = eval_all_windows(tr_C, tr_C, dr_C, cal_v20, dt_idx, sh300, all_sh_dts, WINDOWS_V20)
        res_C.append({"switch_id": sid, "mod_n": mod_A, "d_IS_sharpe": round(w_C["IS"]["daily_sharpe"] - w_base["IS"]["daily_sharpe"], 3),
                      "d_OOS_BLIND_sharpe": round(w_C["OOS_BLIND"]["daily_sharpe"] - w_base["OOS_BLIND"]["daily_sharpe"], 3),
                      "d_OOS_RT_sharpe": round(w_C["OOS_RT"]["daily_sharpe"] - w_base["OOS_RT"]["daily_sharpe"], 3),
                      "d_Y26_sharpe": round(w_C["Y26"]["daily_sharpe"] - w_base["Y26"]["daily_sharpe"], 3),
                      "d_IS_mdd": round(w_C["IS"]["daily_mdd_pct"] - w_base["IS"]["daily_mdd_pct"], 2),
                      "d_OOS_BLIND_mdd": round(w_C["OOS_BLIND"]["daily_mdd_pct"] - w_base["OOS_BLIND"]["daily_mdd_pct"], 2),
                      "d_Y26_mdd": round(w_C["Y26"]["daily_mdd_pct"] - w_base["Y26"]["daily_mdd_pct"], 2),
                      "FULL_nav": w_C["FULL"]["nav"], "FULL_sharpe": w_C["FULL"]["daily_sharpe"], "FULL_mdd": w_C["FULL"]["daily_mdd_pct"],
                      "Y26_nav": w_C["Y26"]["nav"], "Y26_mdd": w_C["Y26"]["daily_mdd_pct"]})

    qA, qB = bh_fdr(p_A), bh_fdr(p_B)
    for res_l, ql in [(res_A, qA), (res_B, qB)]:
        for i, r in enumerate(res_l):
            r["q_bh"] = ql[i]
            w = r["windows"]
            imp_is = (r["d_IS_sharpe"] > 0) or (w["IS"]["nav"] > w_base["IS"]["nav"])
            imp_oob = (r["d_OOS_BLIND_sharpe"] > 0) or (w["OOS_BLIND"]["nav"] > w_base["OOS_BLIND"]["nav"])
            y26_ok = (w["Y26"]["mean_pct"] >= 0.0) and (r["d_Y26_mdd"] <= 0.5)
            r["pass_is_oos_y26_n"] = bool(imp_is and imp_oob and y26_ok and r["mod_n"] >= 5)
            r["pass_both_sharpe_is_oos"] = bool((r["d_IS_sharpe"] > 0) and (r["d_OOS_BLIND_sharpe"] > 0) and y26_ok and r["mod_n"] >= 5)
            r["pass_both_mdd_is_oos"] = bool((r["d_IS_mdd"] < 0) and (r["d_OOS_BLIND_mdd"] < 0) and (r["d_Y26_mdd"] <= 0.5) and (w["Y26"]["mean_pct"] >= 0) and (r["mod_n"] >= 5))

    bridge = {}
    if df20 is not None:
        is_m20 = df20["buy_date"].to_numpy() <= "2024-06-30"
        q_ice70 = float(np.quantile(df20.loc[is_m20, "st15_ice_5d_d1"].dropna(), 0.70))
        q_bt30 = float(np.quantile(df20.loc[is_m20, "rd012_bank_minus_tech_d1"].dropna(), 0.30))
        sc_ice = df20["score_base_v11"].to_numpy(float) + np.where(df20["st15_ice_5d_d1"].fillna(0) >= q_ice70, 4.0, 0.0)
        sc_bt = df20["score_base_v11"].to_numpy(float) + np.where(df20["rd012_bank_minus_tech_d1"].fillna(0) <= q_bt30, 4.0, 0.0)
        for b_lbl, sc_map in [
            ("V20_20cm_A76_P6", dict(zip(zip(df20["buy_date"], df20["c6"]), np.maximum(df20["score_base_v11"], 82.0)))),
            ("V20_20cm_M4_ice_add", dict(zip(zip(df20["buy_date"], df20["c6"]), sc_ice))),
            ("V20_20cm_M7_tech_add", dict(zip(zip(df20["buy_date"], df20["c6"]), sc_bt))),
        ]:
            p6_b = pool6.copy()
            m20 = p6_b["strategy"] == "20cm"
            p6_b.loc[m20, "score"] = [sc_map.get((r.buy_date, r.code), r.score) for r in p6_b[m20].itertuples(index=False)]
            p6_b.loc[m20, "tier"] = [tpe.assign_physical_tier("20cm", s) for s in p6_b.loc[m20, "score"]]
            tr_br, _ = tpe.run_single_slot(p6_b, lambda d: d["tier"].map(dbase.S2C_MAP).fillna(999).to_numpy(), untrig_df=untrig_df, timing_mode="s_tier_reserve_only")
            dr_br, _ = tpe.build_daily_mtm_series(tr_br, cal_v20, dt_idx, bar_lu)
            bridge[b_lbl] = {"n": int(len(tr_br)), "windows": eval_all_windows(tr_br, tr_br, dr_br, cal_v20, dt_idx, sh300, all_sh_dts, WINDOWS_V20)}

    return {
        "v20_baseline": {"n_trades": 278, "mtm_err": round(float(mtm_err), 6), "windows": w_base},
        "mode_A_static_278": res_A,
        "mode_B_causal_pool6": res_B,
        "mode_C_half_size_278": res_C,
        "core1_to_v20_bridge": bridge,
        "cscv_pbo_mode_A": cscv_pbo_matrix(np.column_stack(dr_mat_A)),
        "cscv_pbo_mode_B": cscv_pbo_matrix(np.column_stack(dr_mat_B)),
    }
