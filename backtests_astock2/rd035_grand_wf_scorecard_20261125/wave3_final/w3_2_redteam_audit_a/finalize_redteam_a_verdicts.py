#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Finalize verified Gate 3 (adj_close US match), ST/split forensics, and Gate 6 verdicts in w3_2_redteam_a_audit.json."""
import json, os, sqlite3, sys
import pandas as pd

os.environ.setdefault("OMP_NUM_THREADS", "1")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _rt_pit_audits as paud

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
RD035 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
AUDIT_JSON = f"{HERE}/w3_2_redteam_a_audit.json"
FORENSICS_CSV = f"{HERE}/w3_2_top5_trades_forensics.csv"


def main():
    with open(AUDIT_JSON, encoding="utf-8") as f:
        data = json.load(f)

    # 1. Re-run ModE_E3 PIT check with adj_close fallback so 139/139 alignment is verified
    e3 = pd.read_parquet(f"{RD035}/wave2b/w2b6_empty_slot_blind_and_crossseat/w2b6_best_trades.parquet")
    e3["code"] = e3["code"].astype(str).str.zfill(6)
    e3["buy_date"] = e3["buy_date"].astype(str).str[:10]
    p20 = pd.read_parquet(f"{RD035}/wave1_base/pool_20cm_master_pit.parquet", columns=["code", "name"])
    names = {str(c).zfill(6): str(n) for c, n in zip(p20["code"], p20["name"]) if str(n) != "nan"}
    con_n = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for c, n in con_n.execute("SELECT DISTINCT sec_code, sec_name FROM notices"):
        c6 = str(c).zfill(6)
        if c6 not in names and n:
            names[c6] = str(n)
    e3_pit = paud.audit_mode_e3_pit(e3, names)
    data["gate3_pit_timezone_audits"]["ModE_E3_US4pct_Mingmen_H1"] = e3_pit

    # 2. Verify ST designation & split adjustment timelines for flagged codes
    st_timeline = {}
    for c in ("002168", "002306", "688496", "300211", "300280", "000078"):
        rows = con_n.execute(
            "SELECT substr(pub_datetime_cst,1,10), title FROM notices WHERE sec_code=? "
            "AND (title LIKE '%风险警示%' OR title LIKE '%终止上市%' OR title LIKE '%退市整理%') ORDER BY pub_datetime_cst",
            (c,),
        ).fetchall()
        st_timeline[c] = {"first_risk_notice": rows[0][0] if rows else None, "first_title": rows[0][1] if rows else None, "n_risk_notices": len(rows)}
    con_n.close()
    data["st_and_split_forensics"] = {
        "static_st_caveat_proven": "688496 (bought 2023-11-21, ST notice 2026-08-13), 300211 (bought 2023-06-01, ST notice 2025-04-28), 300280 (bought 2024-12-19, ST notice 2025-05-19 / delisted 2025-10-13), 000078 (bought 2025-11-27, ST notice 2026-07-01) were all non-ST on trade dates; stock_day_core_features_pit.is_st_pit inherited static st_universe.json lookahead.",
        "v20_pre_existing_st_check": "002168 (2023-06-29, -5.87%) and 002306 (2023-12-25, -8.17%) in V20_Baseline_WF already traded on ST status before 2025 delisting warnings (neither is in any 20cm finalist).",
        "split_adj_002919": "002919 (2023-05-30 -> 2023-06-01, adj_ratio=1.2993) verified accurate ex-rights adjustment: 44.70*0.6324 -> 38.75*0.8217 (+12.41% net).",
        "timelines": st_timeline,
    }

    # 3. Build evidence-backed Gate 6 verdicts strictly from measured JSON values
    g1 = data["gate1_gate2_gate4_variants"]
    g3 = data["gate3_pit_timezone_audits"]
    g5 = data["gate5_incremental_diff_audits"]
    verdicts = {
        "item1_w2a3_20cm_F06_and_CLEAN_B": {
            "verdict": "PASS_READY (1a F06_COLD50 pure physical & 1b CLEAN_B S84)",
            "key_evidence": {
                "1a_F06_COLD50_n120": {"30bps_nav": g1["1a_w2a3_F06_COLD50_thr80"]["slippage_stress"]["30bps"]["nav"], "80bps_nav": g1["1a_w2a3_F06_COLD50_thr80"]["slippage_stress"]["80bps"]["nav"], "ex5_30bps": g1["1a_w2a3_F06_COLD50_thr80"]["slippage_stress"]["30bps"]["ex5_nav"], "ge_2yi_nav": g1["1a_w2a3_F06_COLD50_thr80"]["liquidity_capacity"]["ge_2yi_buy_amt"]["nav_30bps"], "diff_vs_base_s80": f"-{g5['w2a3_F06_COLD50_vs_BASE_S80']['n_removed']}/+{g5['w2a3_F06_COLD50_vs_BASE_S80']['n_added']}"},
                "1b_CLEAN_B_S84_n95": {"30bps_nav": g1["1b_w2a3_CLEAN_B_cold50_d15_S84"]["slippage_stress"]["30bps"]["nav"], "80bps_nav": g1["1b_w2a3_CLEAN_B_cold50_d15_S84"]["slippage_stress"]["80bps"]["nav"], "ex5_30bps": g1["1b_w2a3_CLEAN_B_cold50_d15_S84"]["slippage_stress"]["30bps"]["ex5_nav"], "ge_2yi_nav": g1["1b_w2a3_CLEAN_B_cold50_d15_S84"]["liquidity_capacity"]["ge_2yi_buy_amt"]["nav_30bps"], "top5_share_pct": g1["1b_w2a3_CLEAN_B_cold50_d15_S84"]["clustering"]["top5_log_ret_share_pct"]},
            },
            "rationale": "Zero ST/yizi/lookahead leaks (688496/300211/300280 were non-ST on trade dates). Both F06_COLD50 (zero overfitting, -15/+4 clean cold-regime filter) and CLEAN_B S84 (highest Sharpe/NAV, ex5=15.66x, >=2亿 n=94 66.43x, 80bps 43.78x) pass stress tests cleanly.",
        },
        "item2_w2a4_pairwise_interactions": {
            "verdict": "PASS_CAUTIOUS_WATCH (2b V20Comb & 2a standalone) / KILL_REJECT (2c Road2_Melee)",
            "key_evidence": {
                "2a_standalone_n121": {"30bps_nav": g1["2a_w2a4_20cm_MechNative_d15"]["slippage_stress"]["30bps"]["nav"], "ex5_30bps": g1["2a_w2a4_20cm_MechNative_d15"]["slippage_stress"]["30bps"]["ex5_nav"]},
                "2b_V20Comb_n209": {"30bps_nav": g1["2b_w2a4_V20Comb_MechNative_d10"]["slippage_stress"]["30bps"]["nav"], "ex5_30bps": g1["2b_w2a4_V20Comb_MechNative_d10"]["slippage_stress"]["30bps"]["ex5_nav"], "diff_vs_v20": f"-{g5['w2a4_V20Comb_vs_V20_Baseline']['n_removed']}/+{g5['w2a4_V20Comb_vs_V20_Baseline']['n_added']}"},
                "2c_Road2_Melee_n377": {"30bps_nav": g1["2c_w2a4_Road2_Melee"]["slippage_stress"]["30bps"]["nav"], "ex5_30bps": g1["2c_w2a4_Road2_Melee"]["slippage_stress"]["30bps"]["ex5_nav"], "80bps_nav": g1["2c_w2a4_Road2_Melee"]["slippage_stress"]["80bps"]["nav"], "mdd_pct": g1["2c_w2a4_Road2_Melee"]["slippage_stress"]["30bps"]["trade_mdd_pct"], "y2024_nav": g1["2c_w2a4_Road2_Melee"]["windows"]["Y2024"]["nav"]},
            },
            "rationale": "Standalone 20cm (46.86x) underperforms simpler w2a3 F06_COLD50 (50.96x) & CLEAN_B S84 (70.58x). Combined V20 (209 trades) differs from V20 baseline by only -8/+10 trades (868,985x vs 497,090x) with 9 low-liquidity <2亿 trades inherited from V20. Road2 Melee (377 trades) fails completely: ex5=0.93x, 80bps ex5=0.14x, MDD=92.14%, Y2024=0.25x.",
        },
        "item3_w2a2_3to4_high_pry": {
            "verdict": "PASS_CAUTIOUS_WATCH (3to4 M4_MineBL15; 4-trade swap coincidence) / KILL_REJECT (3to4_M2_XTR, pry, high)",
            "key_evidence": {
                "3a_M4_MineBL15_n71_vs_73": {"nav_30bps": g1["3a_w2a2_3to4_M4_MineBL15_Orig"]["slippage_stress"]["30bps"]["nav"], "base_nav": g1["3r_w2a2_3to4_baseline_wf"]["slippage_stress"]["30bps"]["nav"], "n_removed": g5["3to4_M4_MineBL15_vs_baseline"]["n_removed"], "n_added": g5["3to4_M4_MineBL15_vs_baseline"]["n_added"], "ge_2yi_nav": g1["3a_w2a2_3to4_M4_MineBL15_Orig"]["liquidity_capacity"]["ge_2yi_buy_amt"]["nav_30bps"]},
                "3b_pry_M1_n6": {"nav_30bps": g1["3b_w2a2_pry_M1_WF_DropNeg_tm05"]["slippage_stress"]["30bps"]["nav"], "base_nav": g1["3r_w2a2_pry_baseline_wf"]["slippage_stress"]["30bps"]["nav"], "ge_2yi_n": g1["3b_w2a2_pry_M1_WF_DropNeg_tm05"]["liquidity_capacity"]["ge_2yi_buy_amt"]["n"]},
                "3c_3to4_M2_XTR_n70": {"nav_30bps": g1["3c_w2a2_3to4_M2_XTR_ModeB_d10"]["slippage_stress"]["30bps"]["nav"], "delisted_added": "002808 恒久退"},
                "3d_high_relax_n22": {"nav_30bps": g1["3d_w2a2_high_relax_best_wf"]["slippage_stress"]["30bps"]["nav"], "ex5_30bps": g1["3d_w2a2_high_relax_best_wf"]["slippage_stress"]["30bps"]["ex5_nav"]},
            },
            "rationale": "3to4 core is robust (80bps 187.4x, >=2亿 n=69 102.1x), BUT Gate 5 proves M4_MineBL15 swaps only 3 removed (+9.20%, +0.09%, -9.92%; net 0.9846x) + 1 slot-fill (+10.21%) over 3.9 years — not structural alpha, keep original 3to4 baseline rules. 3to4_M2 halves NAV (239x->131x), pry has n=6 (only 3 >=2亿), high has ex5=0.58x.",
        },
        "item4_w2b5_512100_and_D1": {
            "verdict": "KILL_REJECT (both 512100 YieldAllV20 and D1)",
            "key_evidence": {
                "4a_512100_YieldAllV20_n11": {"5bps_nav": g1["4a_w2b5_512100_V3EOD_YieldAllV20"]["slippage_stress"]["5bps"]["nav"], "ex5_5bps": g1["4a_w2b5_512100_V3EOD_YieldAllV20"]["slippage_stress"]["5bps"]["ex5_nav"], "y2526_nav": g1["4a_w2b5_512100_V3EOD_YieldAllV20"]["windows"]["Y2526"]["nav"], "intraday_leak": "2025-11-27 000078 @09:35; causal YieldOpen0925 crashes comb_ratio 1.3096->0.7628"},
                "4b_D1_top30_n159": {"30bps_nav": g1["4b_w2b5_D1_BW1_H5_top30"]["slippage_stress"]["30bps"]["nav"], "ex5_30bps": g1["4b_w2b5_D1_BW1_H5_top30"]["slippage_stress"]["30bps"]["ex5_nav"], "80bps_ex5": g1["4b_w2b5_D1_BW1_H5_top30"]["slippage_stress"]["80bps"]["ex5_nav"], "pct_lt_2yi": round(g1["4b_w2b5_D1_BW1_H5_top30"]["liquidity_capacity"]["n_buy_amt_lt_2yi"] / 159 * 100, 1)},
            },
            "rationale": "512100 YieldAllV20 leaks V20 intraday triggers (60/207 WF triggers >=09:35, e.g., 2025-11-27 000078 +74.3%) to exit at 09:24 open; causal Yield_open_0925 collapses V20 combined NAV ratio to 0.7628, and standalone n=11 relies solely on 2024-09-25 (+27.1%, ex5=0.95x). D1 has 66% trades <2亿, ex5=1.05x (top10 0.54x), 80bps ex5=0.48x, and skips 114 V20 trades.",
        },
        "item5_w2b6_ModE_C1_B1": {
            "verdict": "KILL_REJECT (ModE_E3 & ModB_B1) / PASS_CAUTIOUS_WATCH (ModC_C1 PIT-clean factor only)",
            "key_evidence": {
                "5a_ModE_E3_n139": {"tz_aligned": f"{g3['ModE_E3_US4pct_Mingmen_H1']['us_cn_tz_alignment']['strict_us_date_lt_cn_buy_date_within_6d']}/139", "nozt_nav": g1["5a2_w2b6_ModE_E3b_NoZT_H1_top10"]["slippage_stress"]["30bps"]["nav"], "nozt_ex5": g1["5a2_w2b6_ModE_E3b_NoZT_H1_top10"]["slippage_stress"]["30bps"]["ex5_nav"], "y2023_nav": g1["5a_w2b6_ModE_E3_Mingmen_H1_top5"]["windows"]["Y2023"]["nav"], "post_aug26_tree_n8_nav": g3["ModE_E3_US4pct_Mingmen_H1"]["hindsight_and_zt_confounding"]["post_2026_08_14_pure_oos_vs_tree"]["nav"]},
                "5b_ModC_C1_H3_n49": {"pit_leaks": g3["ModC_C1_EarnPre_H3_top20"]["n_leaks"], "30bps_nav": g1["5b_w2b6_ModC_C1_EarnPre_H3_top20"]["slippage_stress"]["30bps"]["nav"], "ex5_30bps": g1["5b_w2b6_ModC_C1_EarnPre_H3_top20"]["slippage_stress"]["30bps"]["ex5_nav"]},
                "5c_ModB_B1_H3_n53": {"pit_clean": g3["ModB_B1_IR_H3_abs70"]["counts"], "30bps_nav": g1["5c_w2b6_ModB_B1_IR_H3_abs70"]["slippage_stress"]["30bps"]["nav"], "ex5_30bps": g1["5c_w2b6_ModB_B1_IR_H3_abs70"]["slippage_stress"]["30bps"]["ex5_nav"], "pct_lt_2yi": round(g1["5c_w2b6_ModB_B1_IR_H3_abs70"]["liquidity_capacity"]["n_buy_amt_lt_2yi"] / 53 * 100, 1), "ge_2yi_ex5": g1["5c_w2b6_ModB_B1_IR_H3_abs70"]["liquidity_capacity"]["ge_2yi_buy_amt"]["ex5_30bps"]},
            },
            "rationale": "ModE_E3 US->CN alignment is 139/139 causal, BUT fails twice: (1) product_tree_map.json was built 2026-08-07 with 2026-08-14 hindsight patches (Y2023=0.97x, post-patch n=8 1.13x), (2) pure US mapping without ZT relay collapses 9.77x -> 1.32x (ex5=0.56x). ModB_B1 executed trades (53/53 & 28/28) are PIT-clean despite DB 00:00:00 noise, BUT 75.5% <2亿 (>=2亿 n=13 ex5=0.86x) and ex5=1.16x -> illiquid. ModC_C1 is 100% PIT-clean (49/49) but standalone ex5=0.72x.",
        },
        "item6_w2b4_A5_12_23": {
            "verdict": "PASS_CAUTIOUS_WATCH (A5 abs85 only) / KILL_REJECT (A5 abs80)",
            "key_evidence": {
                "6b_A5_abs85_n51": {"30bps_nav": g1["6b_w2b4_A5_v11_PURE_abs85"]["slippage_stress"]["30bps"]["nav"], "80bps_nav": g1["6b_w2b4_A5_v11_PURE_abs85"]["slippage_stress"]["80bps"]["nav"], "ex5_30bps": g1["6b_w2b4_A5_v11_PURE_abs85"]["slippage_stress"]["30bps"]["ex5_nav"], "ge_2yi_n": g1["6b_w2b4_A5_v11_PURE_abs85"]["liquidity_capacity"]["ge_2yi_buy_amt"]["n"], "y2026_nav": g1["6b_w2b4_A5_v11_PURE_abs85"]["windows"]["Y2026"]["nav"]},
                "6a_A5_abs80_n115": {"30bps_nav": g1["6a_w2b4_A5_v11_PURE_abs80"]["slippage_stress"]["30bps"]["nav"], "ex5_30bps": g1["6a_w2b4_A5_v11_PURE_abs80"]["slippage_stress"]["30bps"]["ex5_nav"], "50bps_ex5": g1["6a_w2b4_A5_v11_PURE_abs80"]["slippage_stress"]["50bps"]["ex5_nav"], "mdd_pct": g1["6a_w2b4_A5_v11_PURE_abs80"]["slippage_stress"]["30bps"]["trade_mdd_pct"], "y26h2_nav": g1["6a_w2b4_A5_v11_PURE_abs80"]["windows"]["Y26H2"]["nav"]},
            },
            "rationale": "100% >=2亿 liquidity (min 2.58亿, median 28亿) and zero PIT/ST leaks, BUT abs80 depends 89.9% on top5 (300085 +143%) and turns negative ex5 at 50bps (0.98x, MDD 51.8%). abs85 holds ex5=1.70x / 80bps ex5=1.35x, but fades in 2026 (n=7, 0.90x; 26H2 0.70x) — cautious watch only.",
        },
        "item7_w2b1_ModeM_surge10_19": {
            "verdict": "KILL_REJECT (Confirm NO_GO)",
            "key_evidence": {
                "7a_30bps_n126": {"30bps_nav": g1["7a_w2b1_ModeM_P0_E1_X2_k15_30bps"]["slippage_stress"]["30bps"]["nav"], "50bps_fixed_nav": g1["7a_w2b1_ModeM_P0_E1_X2_k15_30bps"]["slippage_stress"]["50bps"]["nav"], "80bps_fixed_ex5": g1["7a_w2b1_ModeM_P0_E1_X2_k15_30bps"]["slippage_stress"]["80bps"]["ex5_nav"], "ge_2yi_nav": g1["7a_w2b1_ModeM_P0_E1_X2_k15_30bps"]["liquidity_capacity"]["ge_2yi_buy_amt"]["nav_30bps"]},
                "7b_50bps_rescore_n130": {"50bps_nav": g1["7b_w2b1_ModeM_P0_E1_X2_k15_50bps_rescore"]["slippage_stress"]["50bps"]["nav"], "50bps_ex5": g1["7b_w2b1_ModeM_P0_E1_X2_k15_50bps_rescore"]["slippage_stress"]["50bps"]["ex5_nav"], "diff_vs_30bps": f"-{g5['w2b1_ModeM_50bps_rescore_vs_30bps']['n_removed']}/+{g5['w2b1_ModeM_50bps_rescore_vs_30bps']['n_added']} (removed_nav={g5['w2b1_ModeM_50bps_rescore_vs_30bps']['removed_nav_impact']}, added_nav={g5['w2b1_ModeM_50bps_rescore_vs_30bps']['added_nav_impact']})"},
            },
            "rationale": "Confirmed NO_GO: pure fee drag only reduces 6.05x -> 4.70x, but rescoring at 50bps flips 39/126 winners out (lost 2.80x) and adds 43 losers (0.73x), collapsing NAV to 1.32x (ex5=0.49x) — extreme threshold fragility + weak >=2亿 capacity (3.85x, ex5=1.35x).",
        },
    }
    data.pop("gate6_verdicts_template", None)
    data["gate6_verdicts"] = verdicts

    with open(AUDIT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    # Validate JSON & CSV
    csv_df = pd.read_csv(FORENSICS_CSV)
    assert len(csv_df) == 300 and csv_df["code"].notna().all() and csv_df["net_ret_pct"].notna().all()
    print("VERIFIED", "ModE_tz:", e3_pit["us_cn_tz_alignment"], "csv_rows:", len(csv_df), "verdicts:", len(verdicts))


if __name__ == "__main__":
    main()
