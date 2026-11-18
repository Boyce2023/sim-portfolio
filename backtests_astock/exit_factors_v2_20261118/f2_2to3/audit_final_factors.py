#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Final synthesis & Q8 Gate-2 audit for 二进三 V2.0 (`s_2to3`) 30 cross-strategy holding exit factors:
- Evaluates IS-locked XF30_composite_exit_scorecard once on blind OOS (2024-2026)
- Exports complete 30-factor table (factor_30_marginal_table.csv)
- Runs D15 6-window comparison, 8 overfitting tests, 5-strategy synergy, and trade-level diff audit
- Runs physical truncation >= 2025-01-01 from all raw sources, asserting max_abs_diff == 0.0
- Exports summary_2to3_exit_factors.json strictly inside f2_2to3/.
"""

import os
import sys
import json
import time
import pickle
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
S2_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s2_2to3_exit"
OUT_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f2_2to3"
CLEAN_16_DIR = f"{SIM}/backtests_astock/clean_rebacktest_20261116"

CACHE_FULL = f"{OUT_DIR}/_cache_holding_factors_full.pkl"
CACHE_TRUNC = f"{OUT_DIR}/_cache_holding_factors_trunc2024.pkl"
SCAN_RAW = f"{OUT_DIR}/_scan_29factors_raw.pkl"
CACHE_2TO3_IN = f"{S2_DIR}/_cache_2to3_pit_20261116.pkl"

sys.path.insert(0, UPG_DIR)
import upgrade_2to3_pit as u23
sys.path.insert(0, S2_DIR)
import exit_engine as base_ee
import verify_final_and_audit as vfa
sys.path.insert(0, OUT_DIR)
import exit_factor_engine as efe
import build_holding_factors as bhf


# Locked strictly on IS (2021-2023) BEFORE looking at OOS:
def xf30_u_risk_pts(m: dict, df: dict) -> tuple[int, list[str]]:
    pts = 0
    reasons = []
    if df.get("lh_cnt", 0) >= 3:
        pts += 2; reasons.append("拉萨>=3家(+2)")
    if df.get("inst_net_sell", False):
        pts += 2; reasons.append("机构净卖(+2)")
    if df.get("daysurf_buy", False):
        pts += 2; reasons.append("一日游买入(+2)")
    if df.get("clarify_or_tox", False) or df.get("sreg_hold", False) or df.get("ex_reg5_cnt", 0) >= 2:
        pts += 2; reasons.append("监管/澄清/毒丸(+2)")
    if m.get("d3_tombstone", False):
        pts += 1; reasons.append("D3墓碑上影阴(+1)")
    if df.get("sd_mates_cnt", 0) >= 1 and df.get("sd_mates_open_avg", 0.0) < -0.015:
        pts += 1; reasons.append("队友竞价<-1.5%(+1)")
    if df.get("mkt_fb_open_avg", 0.0) < 0.0:
        pts += 1; reasons.append("首板均开<0%(+1)")
    if df.get("has_higher_mate", False):
        pts += 1; reasons.append("同板块高板压制(+1)")
    if df.get("hd_reb_r10", 0.30) < 0.15:
        pts += 1; reasons.append("高标10日反包<15%(+1)")
    return pts, reasons


def xf30_z_risk_pts(m: dict, df: dict) -> tuple[int, list[str]]:
    pts = 0
    reasons = []
    if df.get("lh_cnt", 0) >= 3:
        pts += 2; reasons.append("拉萨>=3家(+2)")
    if df.get("inst_net_sell", False):
        pts += 2; reasons.append("机构净卖(+2)")
    if df.get("clarify_or_tox", False) or df.get("sreg_hold", False) or df.get("ex_reg5_cnt", 0) >= 2:
        pts += 2; reasons.append("监管/澄清/毒丸(+2)")
    if df.get("has_higher_mate", False):
        pts += 1; reasons.append("同板块高板压制(+1)")
    if df.get("hd_reb_r10", 0.30) < 0.15:
        pts += 1; reasons.append("高标10日反包<15%(+1)")
    if df.get("csi_1d_prev", 0.0) <= -0.020 or df.get("csi_5d_prev", 0.0) <= -0.025:
        pts += 1; reasons.append("沪深300急杀(+1)")
    if df.get("mkt_zt_prev", 50) >= 100 or df.get("mkt_seal_prev", 0.5) >= 0.80:
        pts += 1; reasons.append("全场涨停高潮(+1)")
    return pts, reasons


def xf30_unsealed_policy(r, m, df):
    pts, _ = xf30_u_risk_pts(m, df)
    if pts >= 4:
        return "sell_0925"
    if pts >= 2:
        return "vwap_1030"
    return "hold_eod"


def xf30_zt_policy(r, m, df, bd, st):
    pts, _ = xf30_z_risk_pts(m, df)
    if pts >= 2:
        return {"triggered": True, "vwap_1030": True, "allow_imm": False}
    return {}


def main():
    t0 = time.time()
    pkg = pickle.load(open(CACHE_FULL, "rb"))
    raw_scan = pickle.load(open(SCAN_RAW, "rb"))
    orig_2to3 = pickle.load(open(CACHE_2TO3_IN, "rb"))

    sub84 = pkg["sub84"].copy()
    sf = pkg["sig_factors"]
    plook, stk_hist = pkg["plook"], pkg["stk_hist"]
    b5m1, b5m2 = pkg["b5m1"], pkg["b5m2"]
    all_dts, dt_idx = pkg["all_dts"], pkg["dt_idx"]
    idx_sh, idx_sz, sh300 = pkg["idx_sh"], pkg["idx_sz"], pkg["sh300"]
    csi_canon = pkg["csi_canon"]

    # Also keep full gated_all (>=84 is inside gated_all) & comp_v2 for 8-test audit on >=90 and >=96
    gated_all = orig_2to3["gated_all"].copy()
    comp_v2_all = orig_2to3["comp_v2"]
    mask_84 = (gated_all["score_v2"] >= 84).to_numpy()
    df_all = orig_2to3["df_all"]
    t_days = sorted([dt for dt in sh300.keys() if u23.CANON_5Y_START <= dt <= u23.DATA_AS_OF_EXPECTED])

    # Run 6 configurations across Track 1 & Track 2 on sub84
    configs = [
        ("base_t1", b5m1, 0.050, None, None),
        ("opt_t1", b5m1, 0.065, None, None),
        ("xf30_t1", b5m1, 0.065, xf30_unsealed_policy, xf30_zt_policy),
        ("base_t2", b5m2, 0.050, None, None),
        ("opt_t2", b5m2, 0.065, None, None),
        ("xf30_t2", b5m2, 0.065, xf30_unsealed_policy, xf30_zt_policy),
    ]

    for tag, bmap, cdrop, upol, zpol in configs:
        rx, edx, ehx, st_d = efe.sim_exit_policy(
            sub84, sf, plook, stk_hist, bmap, all_dts, dt_idx, idx_sh, idx_sz,
            base_c_drop=cdrop, unsealed_policy=upol, zt_day_policy=zpol, strict_assert=True,
        )
        sub84[f"ret_{tag}"] = rx
        sub84[f"ed_{tag}"] = edx
        sub84[f"eh_{tag}"] = ehx

    # Also verify XF30 on top of Base_V20 (+5.0%) for reference
    rx_b20_xf30, ed_b20_xf30, eh_b20_xf30, _ = efe.sim_exit_policy(
        sub84, sf, plook, stk_hist, b5m2, all_dts, dt_idx, idx_sh, idx_sz,
        base_c_drop=0.050, unsealed_policy=xf30_unsealed_policy, zt_day_policy=xf30_zt_policy, strict_assert=True,
    )
    ev_b20_xf30 = efe.eval_pools(sub84, rx_b20_xf30, ed_b20_xf30, eh_b20_xf30, csi_canon, pools=(84, 86, 90, 96))

    # Build XF30 row for the 30-factor summary table
    ev_xf30 = efe.eval_pools(sub84, sub84["ret_xf30_t2"].tolist(), sub84["ed_xf30_t2"].tolist(), sub84["eh_xf30_t2"].tolist(), csi_canon, pools=(84, 86, 90, 96))
    r_base_arr = sub84["ret_opt_t2"].to_numpy()
    r_xf30_arr = sub84["ret_xf30_t2"].to_numpy()
    mask_is = (sub84["buy_date"] <= "2023-12-31").to_numpy()
    mask_oos = (sub84["buy_date"] >= "2024-01-01").to_numpy()
    mask_90 = (sub84["score_v2"] >= 90).to_numpy()
    chg_xf30 = (np.abs(r_xf30_arr - r_base_arr) > 1e-6) | (sub84["ed_xf30_t2"] != sub84["ed_opt_t2"]) | (sub84["eh_xf30_t2"] != sub84["eh_opt_t2"])

    r90 = ev_xf30["th_90"]
    r96 = ev_xf30["th_96"]
    r84 = ev_xf30["th_84"]
    b90 = raw_scan["res_base"]["th_90"]
    b84 = raw_scan["res_base"]["th_84"]

    xf30_is_ok = (
        r90["IS_21_23"]["nav"] > b90["IS_21_23"]["nav"] * 1.005
        and r90["IS_early"]["nav"] >= b90["IS_early"]["nav"] * 0.995
        and r90["IS_late"]["nav"] >= b90["IS_late"]["nav"] * 0.995
        and r84["IS_21_23"]["nav"] >= b84["IS_21_23"]["nav"] * 0.99
    )
    xf30_oos_ok = (
        r90["OOS_24_26"]["nav"] >= b90["OOS_24_26"]["nav"] * 0.995
        and r90["OOS_24_26"]["max_dd_pct"] <= b90["OOS_24_26"]["max_dd_pct"] + 0.5
    )
    xf30_verdict = "有效_通过IS+OOS" if (xf30_is_ok and xf30_oos_ok) else ("证伪_IS通过但OOS退化" if xf30_is_ok else "证伪_IS未过")

    xf30_row = {
        "factor_id": "XF30",
        "factor_name": "XF30_composite_exit_scorecard",
        "category": "6_盘口微观形态",
        "path": "双路径合成卡",
        "best_is_rule": "U>=4->0925_U>=2->1030vw + Z>=2->1030vw_noimm + C+6.5%",
        "trig_chg_90_IS": int((chg_xf30 & mask_is & mask_90).sum()),
        "trig_chg_90_OOS": int((chg_xf30 & mask_oos & mask_90).sum()),
        "trig_chg_84_IS": int((chg_xf30 & mask_is).sum()),
        "trig_chg_84_OOS": int((chg_xf30 & mask_oos).sum()),
        "imp_vs_hurt_IS90": f"{int((chg_xf30 & mask_is & mask_90 & (r_xf30_arr > r_base_arr)).sum())}/{int((chg_xf30 & mask_is & mask_90 & (r_xf30_arr < r_base_arr)).sum())}",
        "imp_vs_hurt_OOS90": f"{int((chg_xf30 & mask_oos & mask_90 & (r_xf30_arr > r_base_arr)).sum())}/{int((chg_xf30 & mask_oos & mask_90 & (r_xf30_arr < r_base_arr)).sum())}",
        "IS90_trades": r90["IS_21_23"]["trades"],
        "IS90_WR_pct": r90["IS_21_23"]["win_rate_pct"],
        "IS90_PLR": r90["IS_21_23"]["plr"],
        "IS90_NAV": r90["IS_21_23"]["nav"],
        "IS90_EQ_NAV": r90["IS_21_23"]["eq_nav"],
        "IS90_MDD_pct": r90["IS_21_23"]["max_dd_pct"],
        "IS90_early_NAV": r90["IS_early"]["nav"],
        "IS90_late_NAV": r90["IS_late"]["nav"],
        "OOS90_trades": r90["OOS_24_26"]["trades"],
        "OOS90_WR_pct": r90["OOS_24_26"]["win_rate_pct"],
        "OOS90_PLR": r90["OOS_24_26"]["plr"],
        "OOS90_NAV": r90["OOS_24_26"]["nav"],
        "OOS90_EQ_NAV": r90["OOS_24_26"]["eq_nav"],
        "OOS90_MDD_pct": r90["OOS_24_26"]["max_dd_pct"],
        "5Y90_NAV": r90["5Y_211116"]["nav"],
        "5Y90_EQ_NAV": r90["5Y_211116"]["eq_nav"],
        "5Y90_MDD_pct": r90["5Y_211116"]["max_dd_pct"],
        "96S_IS_NAV": r96["IS_21_23"]["nav"],
        "96S_OOS_NAV": r96["OOS_24_26"]["nav"],
        "96S_5Y_NAV": r96["5Y_211116"]["nav"],
        "96S_5Y_MDD": r96["5Y_211116"]["max_dd_pct"],
        "84Exp_IS_NAV": r84["IS_21_23"]["nav"],
        "84Exp_IS_MDD": r84["IS_21_23"]["max_dd_pct"],
        "84Exp_OOS_NAV": r84["OOS_24_26"]["nav"],
        "84Exp_OOS_MDD": r84["OOS_24_26"]["max_dd_pct"],
        "is_pass": xf30_is_ok,
        "verdict": xf30_verdict,
    }

    factor_30_rows = raw_scan["factor_rows"] + [xf30_row]
    df_30 = pd.DataFrame(factor_30_rows)
    df_30.to_csv(f"{OUT_DIR}/factor_30_marginal_table.csv", index=False, encoding="utf-8-sig")

    # Print XF30 Blind OOS & 5Y results immediately
    print("\n=== XF30_composite_exit_scorecard BLIND OOS & 5Y AUDIT ===")
    for tag_lbl, key_tag in [
        ("Opt_V21_T2 (Anchor +6.5%)", "opt_t2"),
        ("XF30_V22_T2 (Scorecard)", "xf30_t2"),
        ("Base_V20_T2 (+5.0%)", "base_t2"),
        ("Opt_V21_T1 (Canon +6.5%)", "opt_t1"),
        ("XF30_V22_T1 (Canon SC)", "xf30_t1"),
    ]:
        ev_k = efe.eval_pools(sub84, sub84[f"ret_{key_tag}"].tolist(), sub84[f"ed_{key_tag}"].tolist(), sub84[f"eh_{key_tag}"].tolist(), csi_canon, pools=(84, 86, 90, 96))
        for p in (90, 96, 84):
            tp = ev_k[f"th_{p}"]
            wi, wo, w5 = tp["IS_21_23"], tp["OOS_24_26"], tp["5Y_211116"]
            print(f"  {tag_lbl:26s} th_{p} | IS={wi['trades']:3d}b {wi['win_rate_pct']:5.1f}% {wi['nav']:6.2f}x MDD={wi['max_dd_pct']:4.1f}% | OOS={wo['trades']:3d}b {wo['win_rate_pct']:5.1f}% {wo['nav']:6.2f}x MDD={wo['max_dd_pct']:4.1f}% | 5Y={w5['nav']:6.2f}x EQ={w5['eq_nav']:6.2f}x MDD={w5['max_dd_pct']:4.1f}%")

    # Full D15 Windows, Hard Invariants, 8-Test Audit on Std90 & Strict96 (plus Exp84 D15)
    mask_5y = (sub84["buy_date"] >= u23.CANON_5Y_START).to_numpy()
    sub84_5y = sub84[mask_5y].copy().reset_index(drop=True)
    comp_v2_5y = comp_v2_all[mask_84][mask_5y]
    base_5y = df_all[df_all["buy_date"] >= u23.CANON_5Y_START].copy()

    d15_cmp, audit_cmp, invariants, ledgers = {}, {}, {}, {}
    for tag in ["base_t1", "opt_t1", "xf30_t1", "base_t2", "opt_t2", "xf30_t2"]:
        rc, ec, hc = f"ret_{tag}", f"ed_{tag}", f"eh_{tag}"
        for tier, th in [("std90", 90), ("strict96", 96), ("exp84", 84)]:
            kname = f"{tag}_{tier}"
            l_full = base_ee.sim_single_slot(sub84[sub84["score_v2"] >= th], "score_v2", rc, ec, hc)
            l_5y = base_ee.sim_single_slot(sub84_5y[sub84_5y["score_v2"] >= th], "score_v2", rc, ec, hc)
            ledgers[kname] = (l_full, l_5y)
            invariants[kname] = vfa.check_hard_invariants(l_5y, plook, all_dts)
            d15_cmp[kname] = vfa.eval_d15_windows(sub84, sub84_5y, l_full, l_5y, "score_v2", th, rc, ec, hc, csi_canon)
            if tier in ("std90", "strict96"):
                audit_cmp[kname] = u23.run_8tests_audit(
                    l_5y, sub84_5y, comp_v2_5y, base_5y, sh300, t_days, "score_v2", th, rc, ec, hc,
                    60, u23.FACTOR_NAMES_V2, run_lofo=False
                )

    for tag in ["xf30_t1", "xf30_t2"]:
        for tier in ["std90", "strict96"]:
            ledgers[f"{tag}_{tier}"][1].to_csv(f"{OUT_DIR}/ledger_{tag}_{tier}.csv", index=False, encoding="utf-8-sig")

    # 5-Strategy Synergy
    port_syn = {
        "track1": {
            "Opt_V21": vfa.eval_portfolio_synergy_custom(sub84_5y, csi_canon, "ret_opt_t1", "ed_opt_t1", "eh_opt_t1", "2to3_Opt_T1"),
            "XF30_V22": vfa.eval_portfolio_synergy_custom(sub84_5y, csi_canon, "ret_xf30_t1", "ed_xf30_t1", "eh_xf30_t1", "2to3_XF30_T1"),
        },
        "track2": {
            "Opt_V21": vfa.eval_portfolio_synergy_custom(sub84_5y, csi_canon, "ret_opt_t2", "ed_opt_t2", "eh_opt_t2", "2to3_Opt_T2"),
            "XF30_V22": vfa.eval_portfolio_synergy_custom(sub84_5y, csi_canon, "ret_xf30_t2", "ed_xf30_t2", "eh_xf30_t2", "2to3_XF30_T2"),
        },
    }

    # Trade-level diffs vs Opt_V21
    def _collect_diffs(tag_a, tag_b):
        diffs = []
        sub90_r = sub84[sub84["score_v2"] >= 90].copy().reset_index(drop=True)
        for r in sub90_r.itertuples(index=False):
            ra, rb = float(getattr(r, f"ret_{tag_a}")), float(getattr(r, f"ret_{tag_b}"))
            eda, edb = str(getattr(r, f"ed_{tag_a}")), str(getattr(r, f"ed_{tag_b}"))
            eha, ehb = int(getattr(r, f"eh_{tag_a}")), int(getattr(r, f"eh_{tag_b}"))
            if abs(rb - ra) > 1e-6 or edb != eda or ehb != eha:
                c6 = str(r.code).zfill(6)
                bd = str(r.buy_date)
                d4 = all_dts[dt_idx[bd] + 1]
                sf_e = sf.get((c6, bd), {"meta": {}, "days": {}})
                df4 = sf_e["days"].get(d4, {})
                u_pts, u_rs = xf30_u_risk_pts(sf_e["meta"], df4)
                z_pts, z_rs = xf30_z_risk_pts(sf_e["meta"], df4)
                # Also collect any Z triggers on holding days
                z_all = []
                for dk_i in range(dt_idx[bd] + 1, min(dt_idx.get(edb, dt_idx[bd] + 1) + 2, len(all_dts))):
                    dk_s = all_dts[dk_i]
                    zp_i, zr_i = xf30_z_risk_pts(sf_e["meta"], sf_e["days"].get(dk_s, {}))
                    if zp_i >= 2:
                        z_all.append(f"{dk_s}({zp_i}分:{'+'.join(zr_i)})")
                diffs.append({
                    "buy_date": bd, "code": c6, "name": str(r.name), "score": int(r.score_v2),
                    "sealed_3b": bool(r.sealed_3b),
                    "anchor_exit": f"{eda} {eha}", "anchor_ret_pct": round(ra * 100, 2),
                    "xf30_exit": f"{edb} {ehb}", "xf30_ret_pct": round(rb * 100, 2),
                    "diff_pp": round((rb - ra) * 100, 2),
                    "trigger_detail": f"U={u_pts}分({'+'.join(u_rs)})" if not r.sealed_3b else f"Z={';'.join(z_all) or str(z_pts)+'分'}",
                })
        return diffs

    diffs_t1 = _collect_diffs("opt_t1", "xf30_t1")
    diffs_t2 = _collect_diffs("opt_t2", "xf30_t2")

    # Physical truncation >= 2025-01-01 zero-lookahead check from raw data!
    print("\nRunning physical truncation >= 2025-01-01 from raw sources...")
    pkg_tr = bhf.build_cache(cutoff_date="2024-12-31", out_name="_cache_holding_factors_trunc2024.pkl")
    sub84_tr = pkg_tr["sub84"].copy()
    trunc_check = {}
    for btag, bmap_tr, full_key_prefix in [
        ("track1_canon5m", pkg_tr["b5m1"], "xf30_t1"),
        ("track2_full5m", pkg_tr["b5m2"], "xf30_t2"),
    ]:
        r_tr, ed_tr, eh_tr, _ = efe.sim_exit_policy(
            sub84_tr, pkg_tr["sig_factors"], pkg_tr["plook"], pkg_tr["stk_hist"], bmap_tr,
            pkg_tr["all_dts"], pkg_tr["dt_idx"], pkg_tr["idx_sh"], pkg_tr["idx_sz"],
            base_c_drop=0.065, unsealed_policy=xf30_unsealed_policy, zt_day_policy=xf30_zt_policy, strict_assert=True,
        )
        sub84_tr["r_tr"] = r_tr; sub84_tr["ed_tr"] = ed_tr; sub84_tr["eh_tr"] = eh_tr
        trunc_check[btag] = {}
        for tier, th in [("std90", 90), ("strict96", 96), ("exp84", 84)]:
            f24 = ledgers[f"{full_key_prefix}_{tier}"][0]
            f24 = f24[f24["exit_date"] <= "2024-12-31"].reset_index(drop=True)
            t_led = base_ee.sim_single_slot(sub84_tr[sub84_tr["score_v2"] >= th], "score_v2", "r_tr", "ed_tr", "eh_tr")
            t24 = t_led[t_led["exit_date"] <= "2024-12-31"].reset_index(drop=True)
            assert len(f24) == len(t24), f"Trunc len mismatch {btag} {tier}: {len(f24)} vs {len(t24)}"
            assert (f24["buy_date"] == t24["buy_date"]).all() and (f24["exit_date"] == t24["exit_date"]).all()
            assert (f24["code"] == t24["code"]).all()
            diff_sc = float(np.max(np.abs(f24["score"].to_numpy() - t24["score"].to_numpy())))
            diff_ret = float(np.max(np.abs(f24["net_ret"].to_numpy() - t24["net_ret"].to_numpy())))
            assert diff_sc == 0.0 and diff_ret == 0.0, f"Trunc diff != 0: {diff_ret}"
            trunc_check[btag][tier] = {"trades_2021_2024": int(len(t24)), "max_abs_diff_score": diff_sc, "max_abs_diff_ret": diff_ret}
    print("[PASS TRUNCATION 0.0]", trunc_check)

    # Export JSON
    summary = u23.sanitize_json({
        "meta": {
            "strategy": "二进三 V2.0 跨策略持仓动态卖点因子全量挖掘 (s_2to3)",
            "data_as_of_date": "2026-11-16",
            "canon_5y_window": "2021-11-16 ~ 2026-11-16",
            "is_window": "2021-01-04 ~ 2023-12-31",
            "oos_window": "2024-01-01 ~ 2026-11-16",
            "anchor_baseline": "Opt_V21 (Stage C 13:45 摸+8.5% 回落破+6.5%)",
            "xf30_scorecard_spec": {
                "path1_unsealed_3b_weights": {
                    "lh_cnt>=3": 2, "inst_net_sell": 2, "daysurf_buy": 2, "clarify_tox_sreg_exreg2": 2,
                    "d3_tombstone": 1, "sd_mates_open<-1.5%": 1, "mkt_fb_open<0%": 1, "has_higher_mate": 1, "hd_reb_r10<15%": 1
                },
                "path1_action": "pts>=4 -> D4 09:25 cut; pts in [2,3] -> D4 10:30 VWAP; pts<=1 -> D4 15:00 hold",
                "path2_zt_chain_weights": {
                    "lh_cnt>=3": 2, "inst_net_sell": 2, "clarify_tox_sreg_exreg2": 2,
                    "has_higher_mate": 1, "hd_reb_r10<15%": 1, "csi_drop_2%/5d_2.5%": 1, "mkt_zt>=100_or_seal>=80%": 1
                },
                "path2_action": "pts>=2 -> 10:30 VWAP + revoke immunity (preserving 13:45 +6.5% lock)",
            },
            "xf30_on_base_v20_plus5_eval": ev_b20_xf30,
            "elapsed_sec": round(time.time() - t0, 2),
        },
        "factor_30_marginal_summary": factor_30_rows,
        "all_single_factor_variants": raw_scan["all_variants_dump"],
        "hard_invariants_and_truncation": {
            "invariants_5y": invariants,
            "truncation_cutoff_2024_12_31_zero_lookahead": trunc_check,
        },
        "d15_windows_comparison": d15_cmp,
        "overfitting_8_tests_comparison": audit_cmp,
        "portfolio_synergy_5th_priority": port_syn,
        "trade_diffs_vs_opt_v21_track1": diffs_t1,
        "trade_diffs_vs_opt_v21_track2": diffs_t2,
    })

    out_json = f"{OUT_DIR}/summary_2to3_exit_factors.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n=== FINAL D15 + 8-TEST SUMMARY ({out_json}) ===")
    for k in ["base_t1_std90", "opt_t1_std90", "xf30_t1_std90",
              "base_t2_std90", "opt_t2_std90", "xf30_t2_std90",
              "opt_t1_strict96", "xf30_t1_strict96", "opt_t2_strict96", "xf30_t2_strict96"]:
        w5 = d15_cmp[k]["全五年_20211116起"]
        wi = d15_cmp[k]["IS_21_23"]
        wo = d15_cmp[k]["OOS_24_26"]
        w3 = d15_cmp[k]["近三年_20231116起"]
        w26 = d15_cmp[k]["2026全年"]
        a1 = audit_cmp[k]["test1_hlz_dsr"]
        a4 = audit_cmp[k]["test4_cscv_pbo"]
        print(f"  {k:17s} | IS:{wi['single_n']:2d}b/{wi['win_rate_pct']:4.1f}%/{wi['single_nav']:6.2f}x/MDD={wi['max_dd_pct']:4.1f}% | "
              f"OOS:{wo['single_n']:2d}b/{wo['win_rate_pct']:4.1f}%/{wo['single_nav']:5.2f}x/MDD={wo['max_dd_pct']:4.1f}% | "
              f"5Y:{w5['single_nav']:6.2f}x EQ:{w5['eq_nav']:6.2f}x T3:{w5['trim3_nav']:5.2f}x MDD:{w5['max_dd_pct']:4.1f}% | "
              f"3Y:{w3['single_nav']:5.2f}x 26:{w26['single_nav']:4.2f}x | t={a1['hlz_t_trade']} DSR150={a1['dsr_trade_prob']['M150']} PBO10={a4['quantile_S10']['pbo_pct']}%")
    print(f"Track 2 diffs vs Opt_V21: {len(diffs_t2)} trades | Track 1 diffs: {len(diffs_t1)} trades")


if __name__ == "__main__":
    main()
