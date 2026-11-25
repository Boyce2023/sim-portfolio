#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 4: Strict Red-Team Verification of Top 20cm & 10cm Candidates
(including separate IS & OOS Trim-Top-3, Yearly Breakdown, Sensitivity, and Exact Report Tables).
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

P = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/abn_30d200_day30_31_factors_20261125")
sys.path.insert(0, str(P))

from step1_extract_events_and_returns import load_indices
from step3_analyze_and_redteam import define_binary_factors, eval_portfolio_metrics, hs300_period_ret


def full_redteam_row(name, sub, ent_col, r30, r50, ex_col, hs_s, open_exit=False):
    m_all = eval_portfolio_metrics(sub, r30, ent_col, ex_col, hs_s, "2021-01-04", "2026-11-24", open_exit=open_exit)
    m_is = eval_portfolio_metrics(sub[sub[ent_col] <= "2023-12-31"], r30, ent_col, ex_col, hs_s, "2021-01-04", "2023-12-29", open_exit=open_exit)
    m_oos = eval_portfolio_metrics(sub[sub[ent_col] >= "2024-01-01"], r30, ent_col, ex_col, hs_s, "2024-01-02", "2026-11-24", open_exit=open_exit)
    m_26 = eval_portfolio_metrics(sub[sub[ent_col] >= "2026-01-01"], r30, ent_col, ex_col, hs_s, "2026-01-05", "2026-11-24", open_exit=open_exit)
    m_50 = eval_portfolio_metrics(sub, r50, ent_col, ex_col, hs_s, "2021-01-04", "2026-11-24", open_exit=open_exit)
    m_oos_50 = eval_portfolio_metrics(sub[sub[ent_col] >= "2024-01-01"], r50, ent_col, ex_col, hs_s, "2024-01-02", "2026-11-24", open_exit=open_exit)

    g1 = (m_is.get("n", 0) >= 5 and m_oos.get("n", 0) >= 8 and m_26.get("n", 0) >= 2
          and m_is.get("mean", -99) > 0 and m_oos.get("mean", -99) > 0 and m_26.get("mean", -99) > 0
          and m_is.get("slot_cum", -99) > 0 and m_oos.get("slot_cum", -99) > 0 and m_26.get("slot_cum", -99) > 0)
    g2 = (m_all.get("slot_excess", -999) > 0 and m_all.get("ew_excess", -999) > 0
          and m_oos.get("slot_excess", -999) > 0 and m_oos.get("ew_excess", -999) > 0)
    g3_all = (m_all.get("trim3_mean", -99) > 0 and m_all.get("slot_trim3_cum", -99) > 0)
    g3_sep = (m_is.get("trim3_mean", -99) > 0 and m_oos.get("trim3_mean", -99) > 0 and m_oos.get("slot_trim3_cum", -99) > 0)
    g4 = (m_50.get("mean", -99) > 0 and m_50.get("slot_cum", -99) > 0 and m_oos_50.get("slot_cum", -99) > 0)

    yr_col = "d30_yr" if ent_col == "d30_date" else "d31_yr"
    yr_stats = {}
    for yr, g in sub.groupby(yr_col):
        v = g[r30].dropna()
        if len(v):
            yr_stats[int(yr)] = f"n={len(v)},wr={(v>0).mean()*100:.0f}%,m={v.mean()*100:+.1f}%"

    return {
        "strategy": name,
        "n_all": m_all.get("n", 0), "n_IS": m_is.get("n", 0), "n_OOS": m_oos.get("n", 0), "n_2026": m_26.get("n", 0),
        "wr_all": m_all.get("wr"), "po_all": m_all.get("po"),
        "mean_all": m_all.get("mean"), "slot_all": m_all.get("slot_cum"), "slot_exc_all": m_all.get("slot_excess"),
        "ew_all": m_all.get("ew_cum"), "ew_exc_all": m_all.get("ew_excess"),
        "mean_IS": m_is.get("mean"), "slot_IS": m_is.get("slot_cum"), "trim3_IS": m_is.get("trim3_mean"),
        "mean_OOS": m_oos.get("mean"), "slot_OOS": m_oos.get("slot_cum"), "slot_exc_OOS": m_oos.get("slot_excess"),
        "ew_OOS": m_oos.get("ew_cum"), "trim3_OOS": m_oos.get("trim3_mean"), "slot_trim3_OOS": m_oos.get("slot_trim3_cum"),
        "mean_2026": m_26.get("mean"), "slot_2026": m_26.get("slot_cum"),
        "trim3_all": m_all.get("trim3_mean"), "slot_trim3_all": m_all.get("slot_trim3_cum"),
        "slip50_slot_all": m_50.get("slot_cum"), "slip50_slot_OOS": m_oos_50.get("slot_cum"),
        "G1_3per": g1, "G2_hs300": g2, "G3_trim3_all": g3_all, "G3_trim3_IS_OOS_sep": g3_sep, "G4_slip50": g4,
        "PASS_STRICT": bool(g1 and g2 and g3_sep and g4),
        "yearly": yr_stats,
    }


def main():
    df = pd.read_parquet(P / "events_hold_48factors.parquet")
    hs_s = load_indices()["sh000300"]
    f_dict = {code: cond for code, _, cond in define_binary_factors(df)}

    # Test ALL top contenders across 10cm & 20cm with strict separate IS/OOS trim-top-3!
    sc_20cm = (
        f_dict["A13_is_theme_leader_d29"].astype(int)
        + f_dict["C01_mcap_lt50"].astype(int)
        + f_dict["C09_lhb_inst_net_pos_d29"].astype(int)
        + f_dict["A04_kpl_in_10d_d29"].astype(int)
    )

    tests = [
        # 20cm winners from Step 3
        ("20cm_peak_D31o_D32c_mcap_lt50",
         df[df["is_20"] & df["in_peak_pool"] & df["d31_buyable"] & f_dict["C01_mcap_lt50"]],
         "d31_date", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
        ("20cm_peak_D31o_D32c_IS_Score_ge2(A13+C01+C09+A04)",
         df[df["is_20"] & df["in_peak_pool"] & df["d31_buyable"] & (sc_20cm >= 2)],
         "d31_date", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
        ("20cm_peak_D31o_D32c_IS_Score_ge3(A13+C01+C09+A04)",
         df[df["is_20"] & df["in_peak_pool"] & df["d31_buyable"] & (sc_20cm >= 3)],
         "d31_date", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
        ("20cm_end165_D31o_D32c_IS_Score_ge2",
         df[df["is_20"] & df["in_end_pool"] & df["d31_buyable"] & (sc_20cm >= 2)],
         "d31_date", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
        ("20cm_peak_D31o_D32c_mcap_lt50_AND_Leader",
         df[df["is_20"] & df["in_peak_pool"] & df["d31_buyable"] & f_dict["C01_mcap_lt50"] & f_dict["A13_is_theme_leader_d29"]],
         "d31_date", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),

        # 10cm strongest contenders from Step 3
        ("10cm_peak_D30c_D32c_hs300_5d_pos",
         df[(~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"] & f_dict["C17_hs300_5d_pos"]],
         "d30_date", "r30c_d32c_f30", "r30c_d32c_f50", "exdt_30c_d32c", False),
        ("10cm_peak_D30c_D35c_hs300_5d_pos",
         df[(~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"] & f_dict["C17_hs300_5d_pos"]],
         "d30_date", "r30c_d35c_f30", "r30c_d35c_f50", "exdt_30c_d35c", False),
        ("10cm_peak_D30c_D32c_hs300_5d_AND_dt_le10",
         df[(~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"] & f_dict["C17_hs300_5d_pos"] & f_dict["C14_mkt_dt_le10_d30"]],
         "d30_date", "r30c_d32c_f30", "r30c_d32c_f50", "exdt_30c_d32c", False),
        ("10cm_peak_D30c_D35c_hs300_5d_AND_dt_le10",
         df[(~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"] & f_dict["C17_hs300_5d_pos"] & f_dict["C14_mkt_dt_le10_d30"]],
         "d30_date", "r30c_d35c_f30", "r30c_d35c_f50", "exdt_30c_d35c", False),
        ("10cm_end165_D30c_D35c_hs300_5d_pos",
         df[(~df["is_20"]) & df["in_end_pool"] & df["d30_buyable"] & f_dict["C17_hs300_5d_pos"]],
         "d30_date", "r30c_d35c_f30", "r30c_d35c_f50", "exdt_30c_d35c", False),
        ("10cm_end165_D31o_D32c_d30_small_pos",
         df[(~df["is_20"]) & df["in_end_pool"] & df["d31_buyable"] & f_dict["B11_d30_small_pos"]],
         "d31_date", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
        ("10cm_end165_D31o_D32c_small_pos_OR_hs300_20d",
         df[(~df["is_20"]) & df["in_end_pool"] & df["d31_buyable"] & f_dict["B11_d30_small_pos"] & f_dict["C18_hs300_20d_pos"]],
         "d31_date", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
        ("10cm_peak_D31o_D32c_no_reg_inq_AND_fri",
         df[(~df["is_20"]) & df["in_peak_pool"] & df["d31_buyable"] & f_dict["C05_no_reg_inq_30d"] & f_dict["C19_d30_fri"]],
         "d31_date", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
        ("10cm_peak_D31o_D32c_no_reg_inq_AND_neg_washout",
         df[(~df["is_20"]) & df["in_peak_pool"] & df["d31_buyable"] & f_dict["C05_no_reg_inq_30d"] & f_dict["B10_d30_neg_washout"]],
         "d31_date", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
    ]

    rows = [full_redteam_row(nm, sub, ent, r30, r50, exc, hs_s, op) for nm, sub, ent, r30, r50, exc, op in tests]
    res = pd.DataFrame(rows)
    res.to_csv(P / "part4_strict_redteam_final.csv", index=False)

    print("=== STRICT RED-TEAM FINAL VERIFICATION (Including Separate IS/OOS Trim-Top-3) ===")
    cols_show = ["strategy", "n_all", "n_IS", "n_OOS", "n_2026", "mean_all", "slot_all", "ew_all",
                 "mean_IS", "trim3_IS", "mean_OOS", "slot_OOS", "trim3_OOS", "slot_trim3_OOS",
                 "mean_2026", "slip50_slot_OOS", "G1_3per", "G2_hs300", "G3_trim3_all", "G3_trim3_IS_OOS_sep", "G4_slip50", "PASS_STRICT"]
    print(res[cols_show].to_string(index=False))

    print("\n=== YEARLY DETAILS OF TOP 4 CANDIDATES ===")
    for rr in rows[:7]:
        print(rr["strategy"], "->", rr["yearly"])


if __name__ == "__main__":
    main()
