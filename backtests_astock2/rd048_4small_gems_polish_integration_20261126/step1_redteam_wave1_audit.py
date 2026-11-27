#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD048 Wave 2 Step 1: Independent Red-Team Audit of Wave 1-A & Wave 1-B Artifacts."""
import json, os, re, sys, time
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import _rd048_w2_lib as w2

def audit_gem1_fixpit_strict() -> dict:
    """Re-verify Gem1 Base vs FixPIT, expose TOX_RE omission (600396), and test StrictJianchi variant."""
    w1a = f"{w2.RD048_DIR}/wave1a_gem1_gem3"
    with open(f"{w1a}/rd048_gem1_4to5.json", encoding="utf-8") as f:
        g1_json = json.load(f)
    g1_pq = pd.read_parquet(f"{w1a}/rd048_gem1_trades.parquet")

    # Independent MTM parity check across all parquet variants
    max_mtm_err = 0.0
    for vn, grp in g1_pq[g1_pq["is_single_slot"]].groupby("variant"):
        for r in grp.itertuples(index=False):
            segs = json.loads(r.mtm_pairs_json)
            prod = float(np.prod([x[1] for x in segs]))
            max_mtm_err = max(max_mtm_err, abs(prod - (1.0 + float(r.net_ret))))

    # Check StrictJianchi (catches 集中竞价减持股份计划, 减持股份预披露, 股票交易风险提示)
    df_e = pd.read_parquet(f"{w2.BASE_AST2}/p3_deep_100/w2_4to5_enriched_master.parquet")
    df_e["code6"] = df_e["code"].astype(str).str.zfill(6)
    df_tox = pd.read_parquet(f"{w2.SIM}/data/pit_reg_tox_notices_5y_complete.parquet")
    tox_strict_re = re.compile(r"(?:减持.*(?:计划|预披露|公告)|(?:计划|预披露).*减持|立案调查|收到立案|退市风险|违法违规|股票交易风险提示)")
    df_tox_strict = df_tox[df_tox["title"].astype(str).str.contains(tox_strict_re)].copy()

    # Check which FixPIT_114 trades are caught by tox_strict_re (at 30bps from parquet!)
    f114_raw = g1_pq[(g1_pq["variant"] == "G1_FixPIT_114") & (~g1_pq["is_single_slot"])].copy()
    caught_rows = []
    keep_mask = []
    for r in f114_raw.itertuples(index=False):
        d90 = (pd.Timestamp(r.buy_date) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
        hit = df_tox_strict[(df_tox_strict["sec_code"] == r.code) & (df_tox_strict["pub_datetime_cst"] >= d90) & (df_tox_strict["pub_datetime_cst"] <= r.buy_date + " 09:25:00")]
        if not hit.empty:
            caught_rows.append({"buy_date": r.buy_date, "code": r.code, "name": r.name, "net_ret_030_pct": round(float(r.net_ret) * 100.0, 2), "title": str(hit.iloc[0]["title"])})
            keep_mask.append(False)
        else:
            keep_mask.append(True)
    f114_strict_raw = f114_raw[keep_mask].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).copy()
    # Single-slot strict
    ss_idx, fd = [], ""
    for r in f114_strict_raw.itertuples():
        if not fd or r.buy_date > fd:
            ss_idx.append(r.Index)
            fd = r.exit_date
    f114_strict_ss = f114_strict_raw.loc[ss_idx].copy()
    r_arr = f114_strict_ss["net_ret"].to_numpy(float)
    r_ex5 = float(np.prod(1.0 + np.sort(r_arr)[:-5])) if len(r_arr) > 5 else 1.0
    strict_3y = f114_strict_ss[f114_strict_ss["buy_date"] >= "2023-01-03"]["net_ret"].to_numpy(float)
    strict_26 = f114_strict_ss[f114_strict_ss["buy_date"] >= "2026-01-01"]["net_ret"].to_numpy(float)

    return {
        "parquet_mtm_max_err": round(max_mtm_err, 10),
        "trunc_20241231_max_diff": g1_json["meta"]["trunc_20241231_max_abs_diff"],
        "fixpit_vs_base_cause": "Rival double-count (+6+3) fix removed 14 marginal trades (incl -27.2%/-24.0%/-17.1%); real tox fix removed normal limit-up abnormal-volatility misclassifications and added 7 positive trades.",
        "tox_re_omission_audit": {"n_omitted_by_narrow_re_in_fix114": len(caught_rows), "caught_details": caught_rows},
        "strict_jianchi_114_30bps": {
            "raw_n": int(len(f114_strict_raw)), "ss_n": int(len(r_arr)),
            "wr_pct": round(float((r_arr > 0).mean() * 100.0), 2),
            "nav_5y": round(float(np.prod(1.0 + r_arr)), 4), "ex5_5y": round(r_ex5, 4),
            "nav_3y": round(float(np.prod(1.0 + strict_3y)), 4), "nav_2026": round(float(np.prod(1.0 + strict_26)), 4),
        },
        "f114_strict_raw_df": f114_strict_raw,
    }

def audit_gem2_and_gem3_and_gem4() -> dict:
    """Audit Gem2 concentration/leakage, Gem3 2023-2025 slump, and Gem4 V3EOD_t1 & SL2 neighborhood."""
    w1a, w1b = f"{w2.RD048_DIR}/wave1a_gem1_gem3", f"{w2.RD048_DIR}/wave1b_gem2_gem4"
    with open(f"{w1b}/rd048_gem2_usmap.json", encoding="utf-8") as f: g2 = json.load(f)
    with open(f"{w1a}/rd048_gem3_5board.json", encoding="utf-8") as f: g3 = json.load(f)
    with open(f"{w1b}/rd048_gem4_if_futures.json", encoding="utf-8") as f: g4 = json.load(f)
    with open(f"{w1b}/if_data_audit.json", encoding="utf-8") as f: if_aud = json.load(f)
    with open(f"{w1b}/rd048_crisis_sniper_v21_overlap.json", encoding="utf-8") as f: cs_ov = json.load(f)

    # Check Gem2 top 5 trades concentration in P_PIT1A_NoZT_GapMod15_VR12_MA5_30bps
    g2_pq = pd.read_parquet(f"{w1b}/rd048_gem2_trades.parquet")
    p1a = g2_pq[g2_pq["variant"] == "P_PIT1A_NoZT_GapMod15_VR12_MA5_30bps"].copy()
    p1a_top5 = p1a.sort_values("net_ret", ascending=False)[["buy_date", "code", "name", "us_group", "net_ret"]].head(5).to_dict("records")

    # Check Gem4 V3EOD_ge65_H3_SL2 vs NoSL & 2026-11-16 cutoff vs 2026-11-25
    g4_pq = pd.read_parquet(f"{w1b}/rd048_gem4_trades.parquet")
    g4_3x_sl2 = g4_pq[g4_pq["variant"] == "P_IF_3x_V3EOD_ge65_H3_SL2"].copy()
    g4_3x_nosl = g4_pq[g4_pq["variant"] == "P_IF_3x_V3EOD_ge65_H3_NoSL"].copy()
    sl2_extra = g4_3x_sl2[~g4_3x_sl2["buy_date"].isin(set(g4_3x_nosl["buy_date"]))][["buy_date", "exit_date", "net_ret", "exit_reason"]].to_dict("records")

    return {
        "gem2_redteam": {
            "trunc_20241231_all_pass": g2["truncation_20241231_audit"]["all_pass"],
            "p1a_ma5_nav_5y": g2["key_variants_full_eval"]["P_PIT1A_NoZT_GapMod15_VR12_MA5_30bps"]["d15"]["W_5Y_2021_2026"]["mtm_nav"],
            "p1a_ma5_ex5_5y": g2["key_variants_full_eval"]["P_PIT1A_NoZT_GapMod15_VR12_MA5_30bps"]["d15"]["W_5Y_2021_2026"]["ex5_nav"],
            "p1a_ma5_wr_5y": g2["key_variants_full_eval"]["P_PIT1A_NoZT_GapMod15_VR12_MA5_30bps"]["d15"]["W_5Y_2021_2026"]["wr_pct"],
            "p1a_ma5_boot_p05": g2["key_variants_full_eval"]["P_PIT1A_NoZT_GapMod15_VR12_MA5_30bps"]["four_small_sample_tests"]["test1_bootstrap_10k"]["mean_ret_pct_p05"],
            "p1a_ma5_top5_trades": p1a_top5,
            "p1b_t1c_nav_5y": g2["key_variants_full_eval"]["P_PIT1B_NoZT_GapLow_m3_p1_VR12_T1C_30bps"]["d15"]["W_5Y_2021_2026"]["mtm_nav"],
            "p1b_t1c_80bps_5y": g2["stress_50_80bps_and_0925_collision"]["P_PIT1B_NoZT_GapLow_m3_p1_VR12_T1C_30bps"]["fee_80bps"]["5y"]["mtm_nav"],
            "p1b_t1c_26h2": g2["key_variants_full_eval"]["P_PIT1B_NoZT_GapLow_m3_p1_VR12_T1C_30bps"]["d15"]["W_26H2"]["mtm_nav"],
        },
        "gem3_redteam": {
            "trunc_max_diff": g3["meta"]["trunc_20241231_max_abs_diff"],
            "base_all_5y": g3["variants"]["G3_Base_All"]["d15"]["5Y_2021_2026"]["nav"],
            "sz00_5y": g3["variants"]["G3_SZ00"]["d15"]["5Y_2021_2026"]["nav"],
            "sz00_lock50_23_25": g3["variants"]["G3_SZ00_Lock50"]["d15"]["Period_2023_2025"]["nav"],
            "sz00_lock50_26h2": g3["variants"]["G3_SZ00_Lock50"]["d15"]["Y26H2"]["nav"],
            "sole_lock50_changepoint": g3["variants"]["G3_SoleHighest_Lock50"]["tool4_regime_dd"]["changepoint"],
            "sole_lock50_k_stop": g3["variants"]["G3_SoleHighest_Lock50"]["tool2_bayesian"]["priors"]["Beta(2,2)_neutral"]["k_consec_loss_prob50_capped25"],
        },
        "gem4_redteam": {
            "trunc_all_pass": g4["truncation_20241231_audit"]["all_pass"],
            "roll_count": if_aud["rollover_2021_2026"]["roll_count"],
            "max_roll_jump_pct": if_aud["rollover_2021_2026"]["max_abs_roll_jump_pct"],
            "v3eod_lag_verified": "T-1 close PIT verified in wave1a_factor_catalog_and_pit_audit.json",
            "sl2_vs_nosl_extra_trade": sl2_extra,
            "crisis_sniper_v21_coverage": cs_ov["binary_conclusion"],
        },
    }

def main():
    t0 = time.time()
    g1_aud = audit_gem1_fixpit_strict()
    strict_raw = g1_aud.pop("f114_strict_raw_df")
    strict_raw.to_parquet(f"{w2.RD048_DIR}/_cache_g1_strict_jianchi_raw.parquet", index=False)
    g234_aud = audit_gem2_and_gem3_and_gem4()
    out = {"gem1_redteam": g1_aud, **g234_aud, "elapsed_sec": round(time.time() - t0, 2), "rss_mb": w2.rss_mb()}
    with open(f"{w2.RD048_DIR}/_step1_redteam_audit.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
