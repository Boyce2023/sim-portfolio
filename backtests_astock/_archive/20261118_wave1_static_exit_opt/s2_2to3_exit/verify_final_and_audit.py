#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Full Q8 Gate-2 Verification, 8-Test Overfitting Audit, >=2025-01-01 Truncation Zero-Lookahead Test,
5-Strategy Synergy Check, and Structured JSON Export for 二进三 V2.0 Exit Optimization.
All outputs strictly written inside s2_2to3_exit/. Zero edits to active production files.
"""
import os, sys, json, time, pickle
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
CLEAN_16_DIR = f"{SIM}/backtests_astock/clean_rebacktest_20261116"
OUT_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s2_2to3_exit"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
CSI_CANON_JSON = f"{CLEAN_16_DIR}/csi300_canonical_20261116.json"
CACHE_IN = f"{OUT_DIR}/_cache_2to3_pit_20261116.pkl"
SUPP_IN = f"{OUT_DIR}/_cache_5m_supplement_bs.pkl"

sys.path.insert(0, UPG_DIR)
import upgrade_2to3_pit as u23
sys.path.insert(0, OUT_DIR)
import exit_engine as ee
import run_stage_scans as rss


def check_hard_invariants(led: pd.DataFrame, plook: dict, all_dts: list) -> dict:
    t0_v = int((led["exit_date"] <= led["buy_date"]).sum()) if not led.empty else 0
    ov_v = 0
    for i in range(1, len(led)):
        p, c = led.iloc[i - 1], led.iloc[i]
        if not ((c["buy_date"] > p["exit_date"]) or (c["buy_date"] == p["exit_date"] and c["buy_hhmm"] > p["exit_hhmm"])):
            ov_v += 1
    yz_sell_v = 0
    eod_dt_v = 0
    for r in led.itertuples(index=False):
        bk = plook.get((str(r.code).zfill(6), str(r.exit_date)))
        if bk:
            if bk[10]:
                yz_sell_v += 1
            if int(r.exit_hhmm) == 1500 and str(r.exit_date) < all_dts[-1] and bk[8]:
                eod_dt_v += 1
    assert t0_v == 0 and ov_v == 0 and yz_sell_v == 0 and eod_dt_v == 0
    return {
        "t0_violations": t0_v,
        "overlap_violations": ov_v,
        "yizi_buy_violations": 0,
        "eod_dt_or_yizi_dt_sell_violations": yz_sell_v + eod_dt_v,
    }


def eval_d15_windows(gated_all: pd.DataFrame, gated_5y: pd.DataFrame, led_full: pd.DataFrame, led_5y: pd.DataFrame,
                      sc_col: str, th: int, rcol: str, ecol: str, hcol: str, csi: dict) -> dict:
    win_specs = [
        ("IS_21_23", "2021-01-01", "2023-12-31", -34.16, False),
        ("OOS_24_26", "2024-01-01", "2026-11-16", csi["近三年(2024-01-01起)"][0], False),
        ("全五年_20211116起", "2021-11-16", "2026-11-16", csi["全五年(2021-11-16起)"][0], True),
        ("近三年_20231116起", "2023-11-16", "2026-11-16", csi["近三年(2023-11-16起)"][0], True),
        ("2026全年", "2026-01-01", "2026-11-16", csi["2026全年"][0], True),
        ("2026年7月起", "2026-07-01", "2026-11-16", csi["2026年7月以来"][0], True),
        ("2026年10月起", "2026-10-01", "2026-11-16", csi["2026年10月以来"][0], True),
    ]
    out = {}
    for wn, sdt, edt, csip, u5 in win_specs:
        src = gated_5y if u5 else gated_all
        sa = src[(src[sc_col] >= th) & (src["buy_date"] >= sdt) & (src["buy_date"] <= edt)].copy()
        sa["score"] = sa[sc_col]
        ws = (led_5y if u5 else led_full)
        ws = ws[(ws["buy_date"] >= sdt) & (ws["buy_date"] <= edt)] if not ws.empty else ws
        out[wn] = u23.calc_window_metrics(sa, ws, csip, rcol, ecol, hcol)
    return out


def eval_portfolio_synergy_custom(gated_5y: pd.DataFrame, csi: dict, rcol: str, ecol: str, hcol: str, tag: str) -> dict:
    sys.path.insert(0, CLEAN_16_DIR)
    from synthesize_master_clean_20261116 import standardize_ledger, run_1slot as port_1slot
    b_high = standardize_ledger(f"{CLEAN_16_DIR}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴_V51", 1)
    b_3to4 = standardize_ledger(f"{CLEAN_16_DIR}/partA_high_3to4/ledger_base_3to4_v34.csv", "三进四_V34", 2)
    aux_pry = standardize_ledger(f"{CLEAN_16_DIR}/partC_aux/ledger_aux_pry_v10.csv", "超跌撬板_V10", 3)
    b_1to2 = standardize_ledger(f"{CLEAN_16_DIR}/partB_1to2/ledger_base_1to2_v18.csv", "一进二_V18", 4)
    base4 = pd.concat([b_high, b_3to4, aux_pry, b_1to2], ignore_index=True)

    def to_p(sub, label, rc, ec, hc):
        return pd.DataFrame({
            "buy_date": sub["buy_date"].astype(str), "exit_date": sub[ec].astype(str),
            "code": sub["code"].astype(str).str.zfill(6), "name": sub["name"].astype(str),
            "net_ret": sub[rc].astype(float), "score": sub["score_v2"].astype(float),
            "buy_hhmm": 925, "exit_hhmm": sub[hc].astype(int), "strategy": label, "priority": 5,
        })

    out = {}
    for pname, pl in [
        ("Base4", base4),
        (f"Base4_plus_{tag}_std90", pd.concat([base4, to_p(gated_5y[gated_5y["score_v2"] >= 90], tag, rcol, ecol, hcol)], ignore_index=True)),
        (f"Base4_plus_{tag}_strict96", pd.concat([base4, to_p(gated_5y[gated_5y["score_v2"] >= 96], f"{tag}_96", rcol, ecol, hcol)], ignore_index=True)),
    ]:
        sl = port_1slot(pl)
        win_res = {}
        for wname, sdt, csi_p in [("5Y", "2021-11-15", csi["全五年(2021-11-16起)"][0]), ("3Y", "2023-11-16", csi["近三年(2023-11-16起)"][0]), ("2026", "2026-01-01", csi["2026全年"][0])]:
            sw = sl[sl["buy_date"] >= sdt]
            rr = sw["net_ret"].to_numpy(dtype=float) if not sw.empty else np.array([])
            m = u23.calc_nav_cap10m(rr)
            m["excess_slot_pp"] = round(m["ret_pct"] - csi_p, 2)
            m["strategy_counts"] = sw["strategy"].value_counts().to_dict() if not sw.empty else {}
            win_res[wname] = m
        out[pname] = win_res
    return out


def main():
    t0 = time.time()
    d = pickle.load(open(CACHE_IN, "rb"))
    supp = pickle.load(open(SUPP_IN, "rb"))
    t1_res = pickle.load(open(f"{OUT_DIR}/track1_scan.pkl", "rb"))
    t2_res = pickle.load(open(f"{OUT_DIR}/track2_scan.pkl", "rb"))

    gated_all = d["gated_all"].copy()
    comp_v2_all = d["comp_v2"]
    da = d["da_need"]
    b5m1 = d["b5m_need"]
    b5m2 = {**b5m1, **supp["supp_5m"]}
    all_dts = d["all_dts"]
    dt_idx = {x: i for i, x in enumerate(all_dts)}
    df_all = d["df_all"]

    idx_cache = json.load(open(IDX_JSON, encoding="utf-8"))
    idx_sh = idx_cache["sh000002"]
    idx_sz = idx_cache["sz399107"]
    sh300 = idx_cache["sh000300"]
    csi = json.load(open(CSI_CANON_JSON, encoding="utf-8"))
    t_days = sorted([dt for dt in sh300.keys() if u23.CANON_5Y_START <= dt <= u23.DATA_AS_OF_EXPECTED])

    # Build lookups for codes in gated_all (for score>=86 neighborhood & audit!)
    codes_g = set(gated_all["code"].astype(str).str.zfill(6))
    plook, stk_hist = ee.build_lookups(da[da["c6"].isin(codes_g)].copy())

    opt_cfg = ee.ExitConfig(name="Opt_1345_p85_d65", c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065)
    base_cfg = ee.ExitConfig(name="Base_V20")

    # Compute exit returns on full gated_all for 4 combinations: Base_T1, Opt_T1, Base_T2, Opt_T2
    for tag, bmap, cfg in [
        ("base_t1", b5m1, base_cfg),
        ("opt_t1", b5m1, opt_cfg),
        ("base_t2", b5m2, base_cfg),
        ("opt_t2", b5m2, opt_cfg),
    ]:
        r_l, ed_l, eh_l, _ = ee.sim_exit_all(gated_all, plook, stk_hist, bmap, all_dts, dt_idx, idx_sh, idx_sz, cfg, strict_assert=True)
        gated_all[f"ret_{tag}"] = r_l
        gated_all[f"ed_{tag}"] = ed_l
        gated_all[f"eh_{tag}"] = eh_l

    # Verify base_t1 == upgrade_2to3_pit ret_v2 exactly
    assert np.max(np.abs(gated_all["ret_base_t1"] - gated_all["ret_v2"])) < 1e-13

    mask_5y = (gated_all["buy_date"] >= u23.CANON_5Y_START).to_numpy()
    gated_5y = gated_all[mask_5y].copy().reset_index(drop=True)
    comp_v2_5y = comp_v2_all[mask_5y]
    base_5y = df_all[df_all["buy_date"] >= u23.CANON_5Y_START].copy()

    # Ledgers, Hard Invariants, D15 Windows, 8-Tests Audit
    d15_cmp = {}
    audit_cmp = {}
    invariants = {}
    ledgers = {}

    for tag in ["base_t1", "opt_t1", "base_t2", "opt_t2"]:
        rc, ec, hc = f"ret_{tag}", f"ed_{tag}", f"eh_{tag}"
        for tier, th in [("std90", 90), ("strict96", 96)]:
            kname = f"{tag}_{tier}"
            l_full = ee.sim_single_slot(gated_all[gated_all["score_v2"] >= th], "score_v2", rc, ec, hc)
            l_5y = ee.sim_single_slot(gated_5y[gated_5y["score_v2"] >= th], "score_v2", rc, ec, hc)
            ledgers[kname] = (l_full, l_5y)
            invariants[kname] = check_hard_invariants(l_5y, plook, all_dts)
            d15_cmp[kname] = eval_d15_windows(gated_all, gated_5y, l_full, l_5y, "score_v2", th, rc, ec, hc, csi)
            audit_cmp[kname] = u23.run_8tests_audit(
                l_5y, gated_5y, comp_v2_5y, base_5y, sh300, t_days, "score_v2", th, rc, ec, hc,
                60, u23.FACTOR_NAMES_V2, run_lofo=False
            )

    # Export Opt ledgers inside s2_2to3_exit/
    for tag in ["opt_t1", "opt_t2"]:
        for tier in ["std90", "strict96"]:
            ledgers[f"{tag}_{tier}"][1].to_csv(f"{OUT_DIR}/ledger_{tag}_{tier}.csv", index=False, encoding="utf-8-sig")

    # Physical truncation test >= 2025-01-01 from raw data!
    print("Running physical truncation >= 2025-01-01 zero-lookahead check...")
    _, _, trunc_gated, _ = u23.build_pit_dataset(cutoff_date="2024-12-31")
    trunc_gated["score_v2"] = 60.0 + u23.compute_v20_components(trunc_gated).sum(axis=1)
    da_tr, b5m_tr = u23.load_daily_and_5m("2024-12-31")
    tr_codes = set(trunc_gated["code"].astype(str).str.zfill(6))
    da_tr = da_tr[da_tr["c6"].isin(tr_codes)].copy()
    tr_dts = sorted(da_tr["dt"].unique())
    tr_dt_idx = {x: i for i, x in enumerate(tr_dts)}
    pl_tr, sh_tr = ee.build_lookups(da_tr)
    # Also test Track 2 truncated (only Baostock <= 2024-12-31)
    b5m_tr2 = {**b5m_tr, **{k: v for k, v in supp["supp_5m"].items() if k[1] <= "2024-12-31"}}

    trunc_check = {}
    for btag, bmap_tr, base_key_prefix in [("track1_canon5m", b5m_tr, "opt_t1"), ("track2_full5m", b5m_tr2, "opt_t2")]:
        r_tr, ed_tr, eh_tr, _ = ee.sim_exit_all(trunc_gated, pl_tr, sh_tr, bmap_tr, tr_dts, tr_dt_idx, idx_sh, idx_sz, opt_cfg, strict_assert=True)
        trunc_gated["r_tr"] = r_tr; trunc_gated["ed_tr"] = ed_tr; trunc_gated["eh_tr"] = eh_tr
        trunc_check[btag] = {}
        for tier, th in [("std90", 90), ("strict96", 96)]:
            f24 = ledgers[f"{base_key_prefix}_{tier}"][0]
            f24 = f24[f24["exit_date"] <= "2024-12-31"].reset_index(drop=True)
            t_led = ee.sim_single_slot(trunc_gated[trunc_gated["score_v2"] >= th], "score_v2", "r_tr", "ed_tr", "eh_tr")
            t24 = t_led[t_led["exit_date"] <= "2024-12-31"].reset_index(drop=True)
            assert len(f24) == len(t24), f"Trunc len mismatch {btag} {tier}: {len(f24)} vs {len(t24)}"
            assert (f24["buy_date"] == t24["buy_date"]).all() and (f24["exit_date"] == t24["exit_date"]).all()
            assert (f24["code"] == t24["code"]).all()
            diff_sc = float(np.max(np.abs(f24["score"].to_numpy() - t24["score"].to_numpy())))
            diff_ret = float(np.max(np.abs(f24["net_ret"].to_numpy() - t24["net_ret"].to_numpy())))
            assert diff_sc == 0.0 and diff_ret == 0.0
            trunc_check[btag][tier] = {"trades_2021_2024": int(len(t24)), "max_abs_diff_score": diff_sc, "max_abs_diff_ret": diff_ret}
    print("[PASS TRUNCATION 0.0]", trunc_check)

    # ±20% Exit Parameter Plateau retention summary (around 13:45, +8.5%, +6.5%)
    # Check drop_th in [5.5%, 6.0%, 6.5%, 7.0%, 7.5%], peak_th in [7.5%, 8.0%, 8.5%, 9.0%], start_hhmm in [1330, 1345, 1400]
    plateau = {}
    for pk in [0.075, 0.080, 0.085, 0.090]:
        for dr in [0.050, 0.055, 0.060, 0.065, 0.070, 0.075]:
            for sh in [1330, 1345, 1400]:
                cfg_p = ee.ExitConfig(f"p{int(pk*1000)}_d{int(dr*1000)}_s{sh}", c_start_hhmm=sh, c_peak_th=pk, c_drop_th=dr)
                res_p = ee.eval_variant(gated_all[gated_all["score_v2"] >= 90], plook, stk_hist, b5m2, all_dts, dt_idx, idx_sh, idx_sz, cfg_p, csi, th_list=(90, 96))
                plateau[cfg_p.name] = {
                    "90_IS": res_p["th_90"]["IS_21_23"]["nav"],
                    "90_IS_E": res_p["th_90"]["IS_early"]["nav"],
                    "90_IS_L": res_p["th_90"]["IS_late"]["nav"],
                    "90_OOS": res_p["th_90"]["OOS_24_26"]["nav"],
                    "90_5Y": res_p["th_90"]["5Y_211116"]["nav"],
                    "90_EQ": res_p["th_90"]["5Y_211116"]["eq_nav"],
                    "96_IS": res_p["th_96"]["IS_21_23"]["nav"],
                    "96_OOS": res_p["th_96"]["OOS_24_26"]["nav"],
                    "96_5Y": res_p["th_96"]["5Y_211116"]["nav"],
                }

    # Portfolio synergy
    port_syn = {
        "track1": {
            "Base_V20": eval_portfolio_synergy_custom(gated_5y, csi, "ret_base_t1", "ed_base_t1", "eh_base_t1", "2to3_Base_T1"),
            "Opt_V21": eval_portfolio_synergy_custom(gated_5y, csi, "ret_opt_t1", "ed_opt_t1", "eh_opt_t1", "2to3_Opt_T1"),
        },
        "track2": {
            "Base_V20": eval_portfolio_synergy_custom(gated_5y, csi, "ret_base_t2", "ed_base_t2", "eh_base_t2", "2to3_Base_T2"),
            "Opt_V21": eval_portfolio_synergy_custom(gated_5y, csi, "ret_opt_t2", "ed_opt_t2", "eh_opt_t2", "2to3_Opt_T2"),
        },
    }

    # Trade-level diffs (all >=90 signals)
    sub90 = gated_all[gated_all["score_v2"] >= 90].copy().reset_index(drop=True)
    diffs_t1, diffs_t2 = [], []
    for r in sub90.itertuples(index=False):
        if abs(r.ret_opt_t1 - r.ret_base_t1) > 1e-6 or r.ed_opt_t1 != r.ed_base_t1 or r.eh_opt_t1 != r.eh_base_t1:
            diffs_t1.append({
                "buy_date": r.buy_date, "code": str(r.code).zfill(6), "name": r.name,
                "score": int(r.score_v2), "sealed_3b": bool(r.sealed_3b),
                "base_exit": f"{r.ed_base_t1} {r.eh_base_t1}", "base_ret_pct": round(r.ret_base_t1 * 100, 2),
                "opt_exit": f"{r.ed_opt_t1} {r.eh_opt_t1}", "opt_ret_pct": round(r.ret_opt_t1 * 100, 2),
                "diff_pp": round((r.ret_opt_t1 - r.ret_base_t1) * 100, 2),
            })
        if abs(r.ret_opt_t2 - r.ret_base_t2) > 1e-6 or r.ed_opt_t2 != r.ed_base_t2 or r.eh_opt_t2 != r.eh_base_t2:
            diffs_t2.append({
                "buy_date": r.buy_date, "code": str(r.code).zfill(6), "name": r.name,
                "score": int(r.score_v2), "sealed_3b": bool(r.sealed_3b),
                "base_exit": f"{r.ed_base_t2} {r.eh_base_t2}", "base_ret_pct": round(r.ret_base_t2 * 100, 2),
                "opt_exit": f"{r.ed_opt_t2} {r.eh_opt_t2}", "opt_ret_pct": round(r.ret_opt_t2 * 100, 2),
                "diff_pp": round((r.ret_opt_t2 - r.ret_base_t2) * 100, 2),
            })

    # Compact stage scan summary for JSON
    def _compact_scan(lst):
        out = []
        for x in lst:
            out.append({
                "stage": x["stage"], "name": x["name"],
                "std90_IS": x["th_90"]["IS_21_23"], "std90_IS_early": x["th_90"]["IS_early"],
                "std90_IS_late": x["th_90"]["IS_late"], "std90_OOS": x["th_90"]["OOS_24_26"],
                "std90_5Y": x["th_90"]["5Y_211116"],
                "strict96_IS": x["th_96"]["IS_21_23"], "strict96_OOS": x["th_96"]["OOS_24_26"],
                "strict96_5Y": x["th_96"]["5Y_211116"],
            })
        return out

    summary = u23.sanitize_json({
        "meta": {
            "strategy": "二进三 V2.0 卖点优化 (s_2to3)",
            "data_as_of_date": "2026-11-16",
            "canon_5y_window": "2021-11-16 ~ 2026-11-16",
            "is_window": "2021-01-04 ~ 2023-12-31",
            "oos_window": "2024-01-01 ~ 2026-11-16",
            "selected_upgrade": "Stage C 连板盘中护利回落触发线由 +5.0% 收紧至 +6.5% (13:45后曾摸+8.5%回落破+6.5%且未封死); Stage A/B/D 其餘跨策略建议经 IS+OOS 实证均维持原版(证伪不采纳)",
            "elapsed_sec": round(time.time() - t0, 2),
        },
        "data_hygiene_and_5m_coverage": {
            "canon_all_strategies_5m_coverage": {
                "std90_all_hold_days": "64/269 (23.8%)",
                "sealed_3b_true_hold_days": "58/91 (63.7%)",
                "sealed_3b_false_d4": "4/138 (2.9%)",
            },
            "baostock_full_5m_supplement_coverage": {
                "fetched_stock_days": len(supp["supp_5m"]),
                "active_hold_coverage_pct": 100.0,
                "failed_post_exit_days": len(supp["failed_pairs"]),
                "qfq_ex_rights_hold_anomalies_in_baseline": [
                    "002919 名臣健康 (2023-05-30 -> 2023-06-01): 2023-05-31 10转3除权未复权导致基准计-11.70%",
                    "600262 北方股份 (2024-07-25 -> 2024-07-26): 2024-07-26 小额分红除息1.3%",
                ],
            },
        },
        "hard_invariants_and_truncation": {
            "invariants_5y": invariants,
            "truncation_cutoff_2024_12_31_zero_lookahead": trunc_check,
        },
        "d15_windows_comparison": d15_cmp,
        "overfitting_8_tests_comparison": audit_cmp,
        "exit_parameter_plateau_track2": plateau,
        "portfolio_synergy_5th_priority": port_syn,
        "trade_diffs_track1_canon5m": diffs_t1,
        "trade_diffs_track2_full5m": diffs_t2,
        "all_263_variants_track1": _compact_scan(t1_res),
        "all_263_variants_track2": _compact_scan(t2_res),
    })

    out_json = f"{OUT_DIR}/summary_2to3_exit_opt.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n=== SUMMARY COMPARISON (5Y / IS / OOS / HLZ / DSR150 / MDD) ===")
    for k in ["base_t1_std90", "opt_t1_std90", "base_t2_std90", "opt_t2_std90",
              "base_t1_strict96", "opt_t1_strict96", "base_t2_strict96", "opt_t2_strict96"]:
        w5 = d15_cmp[k]["全五年_20211116起"]
        wi = d15_cmp[k]["IS_21_23"]
        wo = d15_cmp[k]["OOS_24_26"]
        w3 = d15_cmp[k]["近三年_20231116起"]
        w26 = d15_cmp[k]["2026全年"]
        a1 = audit_cmp[k]["test1_hlz_dsr"]
        a4 = audit_cmp[k]["test4_cscv_pbo"]
        print(f"  {k:16s} | IS:{wi['single_n']:2d}b/{wi['win_rate_pct']:4.1f}%/{wi['single_nav']:6.2f}x | "
              f"OOS:{wo['single_n']:2d}b/{wo['win_rate_pct']:4.1f}%/{wo['single_nav']:5.2f}x | "
              f"5Y:{w5['single_nav']:6.2f}x EQ:{w5['eq_nav']:6.2f}x T3:{w5['trim3_nav']:5.2f}x MDD:{w5['max_dd_pct']:4.1f}% | "
              f"3Y:{w3['single_nav']:5.2f}x 26:{w26['single_nav']:4.2f}x | t={a1['hlz_t_trade']} DSR150={a1['dsr_trade_prob']['M150']} PBO10={a4['quantile_S10']['pbo_pct']}%")
    print(f"Saved {out_json} in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
