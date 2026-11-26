#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD033 Master Runner: 20cm Strong-Mainline-Theme Surge (10%~19.8%, Non-ZT) 5-Year Backtest (2021-01-04 ~ 2026-11-25).
Modules:
  1. Full Spectrum Contrast: No-theme vs Warm(3-4) vs Strong-Mainline(Top3 & 5-9) vs Super-Climax(>=10),
     plus Top1/2/3, >=5/>=8/>=12, 10cm Yizi/Early leader, Type A (光头强趋势) vs Type B (冲板炸板烂大阳),
     lateral benchmarks (20cm ZT1 & 10cm ZT1 on the SAME strong themes), and 180d/365d/all-prior KPL sensitivity.
  2. Full 5 Entries (E1..E5) x 6 Exits (H1a/H1b/H2/H3/H4/H5/H6) Blind Matrix on Strong-Mainline 20cm Surge (All/A/B).
  3. IS-Only (2021-01-04~2024-06-30) Structural Factor Scan + BH-FDR + IS-Locked Top Archetypes ->
     Blind OOS (2024-07-01~2026-11-25) & 2026 Audit + Ex-Top3/Top5 + Static/1-over-Vol Ablations +
     V20.0 Empty-Slot Patch Test + Comparison vs Active S82 + 2024-06-30 Physical Truncation Proof.

ZERO yfinance (D12). ZERO cap10m. SQLite mode=ro only. Read-only on production files.
"""
import json
import math
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd033_20cm_theme_surge10_19_20261125"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import rd033_data_and_kpl as dk
import rd033_sim_and_metrics as sm

SIM = dk.SIM
V20_LEDGER = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partD_final_jianyan/ledger_combined_6strat_v20_slot1_clean.csv"
S82_LEDGER = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack/final_v11_ledger_S82.csv"

WINDOWS = [
    ("FULL", "2021-01-04", "2026-11-25"),
    ("IS", "2021-01-04", "2024-06-30"),
    ("OOS", "2024-07-01", "2026-11-25"),
    ("Y3", "2024-01-01", "2026-11-25"),
    ("Y2026", "2026-01-01", "2026-11-25"),
]


def sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def flatten_row(cat: str, name: str, entry: str, exit_r: str, res: dict) -> dict:
    row = {"category": cat, "slice_name": name, "entry": entry, "exit_rule": exit_r}
    for wlbl, _, _ in WINDOWS:
        m = res.get(wlbl, {})
        for k in ("raw_n", "raw_wr_pct", "raw_mean_pct", "ew_nav", "n_1s", "wr_pct", "plr",
                  "mean_pct", "nav_1s", "ex3_nav", "ex5_nav", "mdd_daily_pct", "sharpe", "hlz_t",
                  "ex_hs300_pp", "ex_cyb_pp", "ex_kc50_pp", "ex_ew_hs300_pp"):
            row[f"{wlbl}_{k}"] = m.get(k)
    row["fee50_full_nav_1s"] = res.get("fee50_full_nav_1s")
    row["fee50_oos_nav_1s"] = res.get("fee50_oos_nav_1s")
    return row


def classify_subtype(df_s: pd.DataFrame) -> pd.Series:
    cond_b = df_s["touch_zt"] & (~df_s["is_zt"])
    cond_a = (~df_s["touch_zt"]) & (df_s["upper_shad"] <= 0.03) & (df_s["close"] > df_s["open"]) & (df_s["body_ratio_hl"] >= 0.55)
    return np.where(cond_b, "B_冲板炸板烂大阳", np.where(cond_a, "A_光头强趋势大阳", "C_冲高回落上影阳"))


def main():
    t_start = time.time()
    print("[1/5] Loading 5-year PIT data warehouse (2021-01-04 ~ 2026-11-25)...")
    wh = dk.load_rd033_warehouse("2026-11-25")
    d20 = wh["d20"]
    d10_zt = wh["d10_zt"]
    bar_ac_lu = wh["bar_ac_lu"]

    # Base 20cm 10%..19.8% non-ZT universe (amount >= 1e8, non-ST, list_age > 20, close >= 2)
    surge = d20[d20["in_surge"] & (d20["dt"] <= "2026-11-24")].copy().reset_index(drop=True)
    surge["subtype"] = classify_subtype(surge)
    surge["score"] = surge["kpl_zt_cnt"] * 100.0 + surge["ret"] * 100.0

    # Also build 20cm ZT1 non-yizi & 10cm ZT1 non-yizi pools for lateral comparisons
    zt20_1b = d20[d20["in_zt20_1b"] & (d20["dt"] <= "2026-11-24")].copy().reset_index(drop=True)
    zt20_1b["score"] = zt20_1b["kpl_zt_cnt"] * 100.0 + zt20_1b["ret"] * 100.0

    zt10_1b = d10_zt[d10_zt["dt"] <= "2026-11-24"].copy().reset_index(drop=True)
    zt10_1b["score"] = zt10_1b["kpl_zt_cnt"] * 100.0 + zt10_1b["ret"] * 100.0

    # Also include 20cm surge without 1e8 floor as sanity check
    surge_all_amt = d20[d20["in_surge_all_amt"] & (d20["dt"] <= "2026-11-24")].copy().reset_index(drop=True)

    print(f"  Pool counts: surge(>=1e8)={len(surge):,} [A={int((surge['subtype']=='A_光头强趋势大阳').sum()):,}, "
          f"B={int((surge['subtype']=='B_冲板炸板烂大阳').sum()):,}, C={int((surge['subtype']=='C_冲高回落上影阳').sum()):,}], "
          f"surge_all_amt={len(surge_all_amt):,}, zt20_1b={len(zt20_1b):,}, zt10_1b={len(zt10_1b):,}")

    slice_rows = []

    def _run_eval(cat: str, name: str, df_sub: pd.DataFrame, entry: str, exit_r: str, sc_col: str | None = None):
        tr = sm.simulate_trades(df_sub, entry, exit_r, fee=sm.FEE_RT, score_col=sc_col)
        res, slot_df = sm.eval_full_suite(tr, bar_ac_lu, wh, WINDOWS)
        slice_rows.append(flatten_row(cat, name, entry, exit_r, res))
        return res, tr, slot_df

    # =========================================================================
    # MODULE 1: Full Spectrum Contrast (Theme Layers x Subtypes x Benchmarks)
    # =========================================================================
    print("\n[2/5] Module 1: Theme Strength 4-Layer Contrast + Subtype A/B + 10cm/20cm ZT1 Benchmarks...")
    theme_layers = [
        ("M1_全池基准", "20cm_10~19.8%_全池(不限题材)", surge),
        ("M1_全池无额限", "20cm_10~19.8%_含微额(<1亿)", surge_all_amt),
        ("M1_题材4层", "T0_无主线_未入今日KPL(含无历史)", surge[surge["kpl_zt_cnt"] == 0]),
        ("M1_题材4层", "T0_无主线含边缘(<3涨停)", surge[surge["kpl_zt_cnt"] < 3]),
        ("M1_题材4层", "T0_边缘弱题材(1~2涨停)", surge[surge["kpl_zt_cnt"].between(1, 2)]),
        ("M1_题材4层", "T1_温热题材(3~4涨停)", surge[surge["kpl_zt_cnt"].between(3, 4)]),
        ("M1_题材4层", "T2_强主线(前3且5~9涨停)", surge[(surge["kpl_rk"] <= 3) & surge["kpl_zt_cnt"].between(5, 9)]),
        ("M1_题材4层", "T3_超级高潮主线(前3且>=10涨停)", surge[(surge["kpl_rk"] <= 3) & (surge["kpl_zt_cnt"] >= 10)]),
        # Prompt's specific mainline strength thresholds
        ("M1_主线分层", "强主线_前1大主线(rk==1且>=5)", surge[(surge["kpl_rk"] == 1) & (surge["kpl_zt_cnt"] >= 5)]),
        ("M1_主线分层", "强主线_前2主线(rk<=2且>=5)", surge[(surge["kpl_rk"] <= 2) & (surge["kpl_zt_cnt"] >= 5)]),
        ("M1_主线分层", "强主线_前3主线(rk<=3且>=5)", surge[(surge["kpl_rk"] <= 3) & (surge["kpl_zt_cnt"] >= 5)]),
        ("M1_主线分层", "涨停家数>=8", surge[surge["kpl_zt_cnt"] >= 8]),
        ("M1_主线分层", "涨停家数>=12", surge[surge["kpl_zt_cnt"] >= 12]),
        ("M1_主线分层", "强主线+10cm龙头一字带动", surge[(surge["kpl_rk"] <= 3) & (surge["kpl_zt_cnt"] >= 5) & (surge["kpl_10yz"] == 1)]),
        ("M1_主线分层", "强主线+10cm早板(<=10:30)带动", surge[(surge["kpl_rk"] <= 3) & (surge["kpl_zt_cnt"] >= 5) & (surge["kpl_10e1030"] == 1)]),
        # KPL lookback window sensitivity (180d & 365d recent memory)
        ("M1_近期题材敏感", "近365日归属_强主线(前3且>=5)", surge[(surge["kpl_rk_365"] <= 3) & (surge["kpl_zt_365"] >= 5)]),
        ("M1_近期题材敏感", "近180日归属_强主线(前3且>=5)", surge[(surge["kpl_rk_180"] <= 3) & (surge["kpl_zt_180"] >= 5)]),
        # Subtypes A vs B (Overall & under Strong Mainline)
        ("M1_K线亚型", "A型_光头强趋势大阳_全池", surge[surge["subtype"] == "A_光头强趋势大阳"]),
        ("M1_K线亚型", "B型_冲板炸板烂大阳_全池", surge[surge["subtype"] == "B_冲板炸板烂大阳"]),
        ("M1_K线亚型", "C型_冲高回落上影_全池", surge[surge["subtype"] == "C_冲高回落上影阳"]),
        ("M1_K线亚型", "A型_光头强趋势_强主线(前3&>=5)", surge[(surge["subtype"] == "A_光头强趋势大阳") & (surge["kpl_rk"] <= 3) & (surge["kpl_zt_cnt"] >= 5)]),
        ("M1_K线亚型", "B型_冲板炸板烂阳_强主线(前3&>=5)", surge[(surge["subtype"] == "B_冲板炸板烂大阳") & (surge["kpl_rk"] <= 3) & (surge["kpl_zt_cnt"] >= 5)]),
        ("M1_K线亚型", "A型_光头强趋势_无主线(<3)", surge[(surge["subtype"] == "A_光头强趋势大阳") & (surge["kpl_zt_cnt"] < 3)]),
        ("M1_K线亚型", "B型_冲板炸板烂阳_无主线(<3)", surge[(surge["subtype"] == "B_冲板炸板烂大阳") & (surge["kpl_zt_cnt"] < 3)]),
        # Lateral Benchmarks: 20cm ZT1 & 10cm ZT1 on same theme definitions!
        ("M1_横向对照", "20cm封死首板_无主线(<3)", zt20_1b[zt20_1b["kpl_zt_cnt"] < 3]),
        ("M1_横向对照", "20cm封死首板_强主线(前3&>=5)", zt20_1b[(zt20_1b["kpl_rk"] <= 3) & (zt20_1b["kpl_zt_cnt"] >= 5)]),
        ("M1_横向对照", "20cm封死首板_超级高潮(>=10)", zt20_1b[(zt20_1b["kpl_rk"] <= 3) & (zt20_1b["kpl_zt_cnt"] >= 10)]),
        ("M1_横向对照", "10cm封死首板_无主线(<3)", zt10_1b[zt10_1b["kpl_zt_cnt"] < 3]),
        ("M1_横向对照", "10cm封死首板_强主线(前3&>=5)", zt10_1b[(zt10_1b["kpl_rk"] <= 3) & (zt10_1b["kpl_zt_cnt"] >= 5)]),
        ("M1_横向对照", "10cm封死首板_超级高潮(>=10)", zt10_1b[(zt10_1b["kpl_rk"] <= 3) & (zt10_1b["kpl_zt_cnt"] >= 10)]),
    ]
    m1_results = {}
    for cat, lbl, df_s in theme_layers:
        r_t2, _, _ = _run_eval(cat, lbl, df_s, "E1_all", "H1b_T2_close")
        r_t3, _, _ = _run_eval(cat + "_T3", lbl, df_s, "E1_all", "H2_T3_close")
        m1_results[lbl] = {"T2_close": r_t2, "T3_close": r_t3}
        f_m = r_t2["FULL"]
        is_m = r_t2["IS"]
        oos_m = r_t2["OOS"]
        print(f"  {lbl:34s} | FULL N={f_m['raw_n']:5d} 1s={f_m['n_1s']:3d} WR={f_m['wr_pct']:5.1f}% mean={f_m['mean_pct']:+5.2f}% "
              f"1sNAV={f_m['nav_1s']:6.3f}x EW={f_m['ew_nav']:6.3f}x | IS={is_m['nav_1s']:5.2f}x OOS={oos_m['nav_1s']:5.2f}x 26={r_t2['Y2026']['nav_1s']:5.2f}x")

    # =========================================================================
    # MODULE 2: 5 Entries x 7 Exits Full Blind Matrix on Strong Mainline (All, A, B)
    # =========================================================================
    print("\n[3/5] Module 2: Entry (E1..E5) x Exit (H1a/H1b/H2..H6) Full Matrix...")
    strong_pool = surge[(surge["kpl_rk"] <= 3) & (surge["kpl_zt_cnt"] >= 5)].copy().reset_index(drop=True)
    strong_A = strong_pool[strong_pool["subtype"] == "A_光头强趋势大阳"].copy().reset_index(drop=True)
    strong_B = strong_pool[strong_pool["subtype"] == "B_冲板炸板烂大阳"].copy().reset_index(drop=True)

    entries = ["E1_all", "E2_gapup", "E3_mild", "E4_deep", "E5a_pullback", "E5b_breakhigh"]
    exits = ["H1a_T2_open", "H1b_T2_close", "H2_T3_close", "H3_T4_close", "H4_T6_close", "H5_ma5_break", "H6_tpsl_10_6"]

    m2_matrix = {}
    for pool_lbl, df_p in [("StrongMainline_All", strong_pool), ("StrongMainline_TypeA", strong_A), ("StrongMainline_TypeB", strong_B), ("FullPool_All", surge)]:
        m2_matrix[pool_lbl] = {}
        # Run full grid on StrongMainline_All, and core exits on TypeA/TypeB/FullPool
        use_exits = exits if pool_lbl == "StrongMainline_All" else ["H1a_T2_open", "H1b_T2_close", "H2_T3_close", "H4_T6_close", "H5_ma5_break", "H6_tpsl_10_6"]
        for e in entries:
            for x in use_exits:
                res, _, _ = _run_eval(f"M2_{pool_lbl}", f"{pool_lbl}_{e}_{x}", df_p, e, x)
                m2_matrix[pool_lbl][f"{e}__{x}"] = res
                if pool_lbl == "StrongMainline_All":
                    fm, im, om = res["FULL"], res["IS"], res["OOS"]
                    print(f"  [Strong] {e:13s} x {x:13s} | N={fm['raw_n']:4d}(1s={fm['n_1s']:3d}) WR={fm['wr_pct']:5.1f}% PLR={fm['plr']:4.2f} "
                          f"mean={fm['mean_pct']:+5.2f}% | FULL={fm['nav_1s']:5.2f}x(ex5={fm['ex5_nav']:5.2f}x) IS={im['nav_1s']:5.2f}x OOS={om['nav_1s']:5.2f}x 26={res['Y2026']['nav_1s']:5.2f}x")

    # =========================================================================
    # MODULE 3: IS-Only Structural Factor Scan + BH-FDR + Locked OOS & V20 Patch
    # =========================================================================
    print("\n[4/5] Module 3: IS-Only Factor Scan (BH-FDR) -> Blind OOS & V20 Empty-Slot Audit...")
    factor_defs = [
        ("F_强主线(前3&>=5)", lambda d: (d["kpl_rk"] <= 3) & (d["kpl_zt_cnt"] >= 5)),
        ("F_超级高潮(>=10)", lambda d: (d["kpl_rk"] <= 3) & (d["kpl_zt_cnt"] >= 10)),
        ("F_无主线(<3)", lambda d: d["kpl_zt_cnt"] < 3),
        ("F_A型光头强阳", lambda d: d["subtype"] == "A_光头强趋势大阳"),
        ("F_B型冲板炸板", lambda d: d["subtype"] == "B_冲板炸板烂大阳"),
        ("F_实体涨幅>=12%", lambda d: d["body_pct"] >= 0.12),
        ("F_容量中军额>=5亿", lambda d: d["amount"] >= 5e8),
        ("F_容量大中军>=10亿", lambda d: d["amount"] >= 10e8),
        ("F_小自由流值<=25亿", lambda d: d["real_free_mcap"] <= 25.0),
        ("F_大自由流值>60亿", lambda d: d["real_free_mcap"] > 60.0),
        ("F_60日新高突破区(>=0.85)", lambda d: d["pos60_t0"] >= 0.85),
        ("F_60日突破当日创高", lambda d: d["break60_t0"] == 1),
        ("F_60日低位超跌(<=0.45)", lambda d: d["pos60_t0"] <= 0.45),
        ("F_真首日启动(5日<=5%&20日无大阳)", lambda d: (d["prev_ret5"] <= 0.05) & (d["big10_20d_pre"] == 0)),
        ("F_连续加速(前5日>12%)", lambda d: d["prev_ret5"] > 0.12),
        ("F_主线20cm涨幅第1名", lambda d: d["rk20_ret_in_theme"] == 1),
        ("F_主线20cm成交第1名", lambda d: d["rk20_amt_in_theme"] == 1),
        ("F_主线20cm跟风(排名>=2)", lambda d: (d["rk20_ret_in_theme"] >= 2) & (d["rk20_ret_in_theme"] < 99)),
        ("F_20cm冰点期(<=5家)", lambda d: d["mkt20_zt_cnt"] <= 5),
        ("F_20cm温热期(6~15家)", lambda d: d["mkt20_zt_cnt"].between(6, 15)),
        ("F_20cm过热期(>=16家)", lambda d: d["mkt20_zt_cnt"] >= 16),
        ("F_10cm强情绪(>60家)", lambda d: d["mkt10_zt_cnt"] > 60),
        ("F_龙虎榜机构净买>0", lambda d: d["lhb_inst_net"] > 0),
        ("F_无拉萨且无毒丸监管", lambda d: (d["lhb_lh_cnt"] == 0) & (d["tox_90d"] == 0) & (d["reg_10d"] == 0)),
        ("F_3日30%异动余量>=10%", lambda d: d["dist_3d30"] >= 0.10),
        ("F_10cm同题材一字龙头", lambda d: d["kpl_10yz"] == 1),
        ("F_10cm同题材早板带动", lambda d: d["kpl_10e1030"] == 1),
    ]

    scan_configs = [
        ("StrongMainline", strong_pool, "E1_all", "H1b_T2_close"),
        ("StrongMainline", strong_pool, "E4_deep", "H1b_T2_close"),
        ("StrongMainline", strong_pool, "E2_gapup", "H1b_T2_close"),
        ("StrongMainline", strong_pool, "E3_mild", "H1b_T2_close"),
        ("StrongMainline", strong_pool, "E1_all", "H2_T3_close"),
        ("StrongMainline", strong_pool, "E1_all", "H5_ma5_break"),
    ]

    scan_rows = []
    p_vals_is = []
    for base_lbl, df_b, e_r, x_r in scan_configs:
        for fname, fn in factor_defs:
            m_mask = np.asarray(fn(df_b), dtype=bool)
            sub_f = df_b[m_mask].copy().reset_index(drop=True)
            if len(sub_f) < 30:
                continue
            tr_f = sm.simulate_trades(sub_f, e_r, x_r, fee=sm.FEE_RT)
            if tr_f.empty:
                continue
            tr_is = tr_f[tr_f["buy_date"] <= "2024-06-30"]
            tr_oos = tr_f[tr_f["buy_date"] >= "2024-07-01"]
            tr_26 = tr_f[tr_f["buy_date"] >= "2026-01-01"]
            if len(tr_is) < 30:
                continue
            r_is = tr_is["net_ret"].to_numpy(float)
            _, p_raw = stats.ttest_1samp(r_is, 0.0, alternative="greater") if np.std(r_is, ddof=1) > 1e-12 else (0.0, 1.0)
            p_vals_is.append(float(p_raw))
            s1_is = sm.sim_1_slot(tr_is)
            s1_oos = sm.sim_1_slot(tr_oos)
            s1_26 = sm.sim_1_slot(tr_26)
            ew_is = float(np.prod(1.0 + tr_is.groupby("buy_date")["net_ret"].mean().to_numpy(float)))
            ew_oos = float(np.prod(1.0 + tr_oos.groupby("buy_date")["net_ret"].mean().to_numpy(float))) if not tr_oos.empty else 1.0
            scan_rows.append({
                "base": base_lbl, "entry": e_r, "exit": x_r, "factor": fname,
                "is_raw_n": int(len(tr_is)), "is_1s_n": int(len(s1_is)),
                "is_raw_wr": round(float((r_is > 0).mean() * 100), 2),
                "is_raw_mean": round(float(r_is.mean() * 100), 2),
                "is_ew_nav": round(ew_is, 4),
                "is_1s_nav": round(float(np.prod(1.0 + s1_is["net_ret"].to_numpy(float))), 4) if not s1_is.empty else 1.0,
                "p_is_raw": round(float(p_raw), 6),
                "oos_raw_n": int(len(tr_oos)),
                "oos_raw_mean": round(float(tr_oos["net_ret"].mean() * 100), 2) if not tr_oos.empty else 0.0,
                "oos_ew_nav": round(ew_oos, 4),
                "oos_1s_nav": round(float(np.prod(1.0 + s1_oos["net_ret"].to_numpy(float))), 4) if not s1_oos.empty else 1.0,
                "y26_raw_n": int(len(tr_26)),
                "y26_1s_nav": round(float(np.prod(1.0 + s1_26["net_ret"].to_numpy(float))), 4) if not s1_26.empty else 1.0,
            })
    q_is = sm.bh_fdr(p_vals_is)
    for idx_s, sr_row in enumerate(scan_rows):
        sr_row["is_bh_fdr_q"] = q_is[idx_s]
    scan_df = pd.DataFrame(scan_rows).sort_values(["is_bh_fdr_q", "is_raw_mean"], ascending=[True, False]).reset_index(drop=True)
    n_fdr_05 = int((scan_df["is_bh_fdr_q"] <= 0.05).sum()) if not scan_df.empty else 0
    n_fdr_10 = int((scan_df["is_bh_fdr_q"] <= 0.10).sum()) if not scan_df.empty else 0
    print(f"  IS Scan tested {len(scan_df)} factor x entry x exit cells (min_group_n >= 30): "
          f"BH-FDR q<=0.05: {n_fdr_05}, q<=0.10: {n_fdr_10}")
    for r in scan_df.head(12).itertuples(index=False):
        print(f"    {r.entry:8s} {r.exit:12s} | {r.factor:22s} | IS N={r.is_raw_n:4d} mean={r.is_raw_mean:+5.2f}% q={r.is_bh_fdr_q:.4f} 1s={r.is_1s_nav:5.2f}x | "
              f"OOS N={r.oos_raw_n:4d} mean={r.oos_raw_mean:+5.2f}% 1s={r.oos_1s_nav:5.2f}x 26={r.y26_1s_nav:5.2f}x")

    # Stage 3B: Define structural candidate archetypes (tested IS -> OOS + V20 empty slots!)
    archetypes = [
        ("C0_强主线基准_E1全买T2收", strong_pool, "E1_all", "H1b_T2_close"),
        ("C1_强主线_E4深水低吸T2收", strong_pool[strong_pool["tox_90d"] == 0], "E4_deep", "H1b_T2_close"),
        ("C2_强主线_E4深水+非过热T2收", strong_pool[(strong_pool["tox_90d"] == 0) & (strong_pool["reg_10d"] == 0) & (strong_pool["mkt20_zt_cnt"] < 16)], "E4_deep", "H1b_T2_close"),
        ("C3_强主线_E2高开顺势T2收", strong_pool[strong_pool["tox_90d"] == 0], "E2_gapup", "H1b_T2_close"),
        ("C4_强主线_A型光头+突破60高_E1_T3", strong_A[(strong_A["pos60_t0"] >= 0.80) & (strong_A["tox_90d"] == 0)], "E1_all", "H2_T3_close"),
        ("C5_强主线_A型光头+首日启动_E2_MA5", strong_A[(strong_A["prev_ret5"] <= 0.05) & (strong_A["big10_20d_pre"] == 0) & (strong_A["tox_90d"] == 0)], "E2_gapup", "H5_ma5_break"),
        ("C6_强主线_B型炸板+深水低吸T2收", strong_B[(strong_B["tox_90d"] == 0) & (strong_B["reg_10d"] == 0) & (strong_B["mkt20_zt_cnt"] < 16)], "E4_deep", "H1b_T2_close"),
        ("C7_强主线_容量中军>=5亿_E4低吸T2", strong_pool[(strong_pool["amount"] >= 5e8) & (strong_pool["tox_90d"] == 0)], "E4_deep", "H1b_T2_close"),
        ("C8_强主线_60日低位<=0.45_E4低吸T2", strong_pool[(strong_pool["pos60_t0"] <= 0.45) & (strong_pool["tox_90d"] == 0) & (strong_pool["reg_10d"] == 0)], "E4_deep", "H1b_T2_close"),
        ("C9_强主线_龙头第1+无过热_E4低吸T2", strong_pool[(strong_pool["rk20_ret_in_theme"] == 1) & (strong_pool["mkt20_zt_cnt"] < 16) & (strong_pool["tox_90d"] == 0)], "E4_deep", "H1b_T2_close"),
        ("C10_全池对照(不限题材)_E4深水T2", surge[(surge["tox_90d"] == 0) & (surge["reg_10d"] == 0) & (surge["mkt20_zt_cnt"] < 16)], "E4_deep", "H1b_T2_close"),
    ]

    # Dynamically lock top IS archetype with IS n_1s >= 30 (strictly before looking at OOS!)
    arch_results = {}
    v20_patch_results = {}
    cand_trades_map = {}
    is_best_key, is_best_score = None, -1e9
    for aname, df_a, e_r, x_r in archetypes:
        res, tr_a, slot_a = _run_eval("M3_候选原型", aname, df_a, e_r, x_r)
        v20_res = sm.v20_empty_slot_test(tr_a, V20_LEDGER, S82_LEDGER)
        arch_results[aname] = res
        v20_patch_results[aname] = v20_res
        cand_trades_map[aname] = slot_a
        im, om, ym = res["IS"], res["OOS"], res["Y2026"]
        vp = v20_res["added_patch_solo"]
        print(f"  {aname:30s} | IS: N={im['n_1s']:3d} WR={im['wr_pct']:5.1f}% 1s={im['nav_1s']:5.2f}x ex5={im['ex5_nav']:5.2f}x | "
              f"OOS: N={om['n_1s']:3d} WR={om['wr_pct']:5.1f}% 1s={om['nav_1s']:5.2f}x ex5={om['ex5_nav']:5.2f}x | "
              f"26={ym['nav_1s']:5.2f}x | V20空位补丁:+{vp['n']:2d}笔 胜{vp['wr_pct']:5.1f}% 均{vp['mean_pct']:+5.2f}% OOS={vp['oos_nav']:5.2f}x")
        if im["n_1s"] >= 30 and aname != "C10_全池对照(不限题材)_E4深水T2":
            sc_is = im["sharpe"] + math.log(max(0.01, im["ex5_nav"]))
            if sc_is > is_best_score:
                is_best_score = sc_is
                is_best_key = aname

    # =========================================================================
    # Physical Truncation Proof at 2024-06-30 (Zero Future Leakage Verification)
    # =========================================================================
    print("\n[5/5] Running 2024-06-30 physical truncation proof & saving outputs...")
    wh_tr = dk.load_rd033_warehouse("2024-06-30")
    d20_tr = wh_tr["d20"]
    surge_tr = d20_tr[d20_tr["in_surge"] & (d20_tr["dt"] <= "2024-06-30")].copy().reset_index(drop=True)
    surge_tr["subtype"] = classify_subtype(surge_tr)
    surge_tr["score"] = surge_tr["kpl_zt_cnt"] * 100.0 + surge_tr["ret"] * 100.0
    strong_tr = surge_tr[(surge_tr["kpl_rk"] <= 3) & (surge_tr["kpl_zt_cnt"] >= 5)].copy().reset_index(drop=True)
    tr_trunc_raw = sm.simulate_trades(strong_tr, "E1_all", "H1b_T2_close", fee=sm.FEE_RT)
    slot_trunc = sm.sim_1_slot(tr_trunc_raw)
    slot_trunc = slot_trunc[slot_trunc["exit_date"] <= "2024-06-30"].reset_index(drop=True)

    tr_full_c0 = sm.simulate_trades(strong_pool, "E1_all", "H1b_T2_close", fee=sm.FEE_RT)
    slot_full_c0 = sm.sim_1_slot(tr_full_c0)
    slot_full_le = slot_full_c0[slot_full_c0["exit_date"] <= "2024-06-30"].reset_index(drop=True)

    assert len(slot_trunc) == len(slot_full_le), f"Trunc len mismatch: {len(slot_trunc)} vs {len(slot_full_le)}"
    assert (slot_trunc["buy_date"] == slot_full_le["buy_date"]).all() and (slot_trunc["c6"] == slot_full_le["c6"]).all()
    max_trunc_diff = float(np.max(np.abs(slot_trunc["net_ret"].to_numpy(float) - slot_full_le["net_ret"].to_numpy(float))))
    assert max_trunc_diff == 0.0, f"Trunc max_diff != 0: {max_trunc_diff}"
    print(f"  [TRUNC PROOF PASS] 2024-06-30 cutoff: trades={len(slot_trunc)}, max_abs_diff={max_trunc_diff}")

    # Active S82 Benchmark summary on EXACT same windows
    s82 = pd.read_csv(S82_LEDGER)
    s82["c6"] = s82["c6"].astype(str).str.zfill(6)
    s82_summary = {}
    for wlbl, sdt, edt in WINDOWS:
        sub_s = s82[(s82["buy_date"] >= sdt) & (s82["buy_date"] <= edt)]
        rt = sub_s["net_ret"].to_numpy(float)
        w, l = rt[rt > 0], rt[rt <= 0]
        plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else 0.0
        cum = np.cumprod(1.0 + rt) if len(rt) else np.array([1.0])
        pk = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
        mdd = float(np.max((pk - cum) / pk) * 100.0) if len(rt) else 0.0
        ex5 = float(np.prod(1.0 + np.sort(rt)[:-5])) if len(rt) > 5 else 1.0
        s82_summary[wlbl] = {
            "n_1s": int(len(rt)), "wr_pct": round(float((rt > 0).mean() * 100), 2) if len(rt) else 0.0,
            "plr": round(plr, 2), "mean_pct": round(float(rt.mean() * 100), 2) if len(rt) else 0.0,
            "nav_1s": round(float(cum[-1]), 4), "ex5_nav": round(ex5, 4), "mdd_trade_pct": round(mdd, 2),
        }

    # Save CSVs and JSON
    pd.DataFrame(slice_rows).to_csv(f"{OUT_DIR}/rd033_slice_matrix.csv", index=False)

    # Save top candidates sample (Strong mainline E1 + E4 + IS-locked best + A/B samples)
    samp_parts = []
    for lbl_s in ["C0_强主线基准_E1全买T2收", "C1_强主线_E4深水低吸T2收", "C2_强主线_E4深水+非过热T2收", "C4_强主线_A型光头+突破60高_E1_T3"]:
        df_cand = cand_trades_map.get(lbl_s, pd.DataFrame()).copy()
        if not df_cand.empty:
            df_cand["archetype"] = lbl_s
            samp_parts.append(df_cand)
    samp_df = pd.concat(samp_parts, ignore_index=True) if samp_parts else pd.DataFrame()
    samp_df.to_csv(f"{OUT_DIR}/rd033_top_candidates_sample.csv", index=False)

    # Compute overall Go/No-Go verdict
    best_arch = arch_results.get(is_best_key, {}) if is_best_key else {}
    best_oos_nav = best_arch.get("OOS", {}).get("nav_1s", 1.0)
    best_oos_ex5 = best_arch.get("OOS", {}).get("ex5_nav", 1.0)
    best_y26_nav = best_arch.get("Y2026", {}).get("nav_1s", 1.0)
    best_v20_patch = v20_patch_results.get(is_best_key, {}).get("added_patch_solo", {}) if is_best_key else {}
    verdict = "GO_VALID_STRATEGY" if (best_oos_nav >= 1.50 and best_oos_ex5 >= 1.15 and best_y26_nav >= 1.10 and best_v20_patch.get("oos_nav", 1.0) > 1.05) else "NO_GO_FALSIFIED"

    audit = {
        "meta": {
            "rd_id": "RD033",
            "title": "20cm强主线题材大涨10%至19.9%未涨停5年专项实证",
            "window": "2021-01-04 ~ 2026-11-25",
            "is_window": "2021-01-04 ~ 2024-06-30",
            "oos_window": "2024-07-01 ~ 2026-11-25",
            "fee_rt": sm.FEE_RT,
            "pen_buf": sm.PEN_BUF,
            "pool_counts": {
                "surge_ge1e8": int(len(surge)),
                "subtype_A": int((surge["subtype"] == "A_光头强趋势大阳").sum()),
                "subtype_B": int((surge["subtype"] == "B_冲板炸板烂大阳").sum()),
                "subtype_C": int((surge["subtype"] == "C_冲高回落上影阳").sum()),
                "zt20_1b": int(len(zt20_1b)),
                "zt10_1b": int(len(zt10_1b)),
            },
            "truncation_proof_20240630": {
                "trades_le_cutoff": int(len(slot_trunc)),
                "max_abs_diff": max_trunc_diff,
                "pass": True,
            },
            "elapsed_sec": round(time.time() - t_start, 2),
        },
        "module1_spectrum_and_crossboard": m1_results,
        "module2_entry_exit_matrix": m2_matrix,
        "module3_is_fdr_scan_summary": {
            "total_tested": int(len(scan_df)),
            "fdr_q_le_005": n_fdr_05,
            "fdr_q_le_010": n_fdr_10,
            "top20_is_sorted": scan_df.head(20).to_dict("records"),
            "all_scan_rows": scan_df.to_dict("records"),
        },
        "module3_archetypes": arch_results,
        "module3_v20_empty_slot_tests": v20_patch_results,
        "is_locked_best_key": is_best_key,
        "s82_benchmark": s82_summary,
        "verdict": verdict,
    }
    json_path = f"{OUT_DIR}/rd033_20cm_theme_surge_audit.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(sanitize(audit), f, ensure_ascii=False, indent=2)

    print(f"\n[DONE RD033] Verdict={verdict} | IS-Locked Best={is_best_key} | S82 FULL={s82_summary['FULL']['nav_1s']}x (OOS={s82_summary['OOS']['nav_1s']}x, 26={s82_summary['Y2026']['nav_1s']}x)")
    print(f"  Saved: {json_path} in {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
