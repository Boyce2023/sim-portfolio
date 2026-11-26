#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Module 1B: Forensic Anatomy of 20cm V1.1 S82 2026H2 Win-Rate Cooling (~43.8%) vs A76 & 5Y."""
import sys
import numpy as np
import pandas as pd
from scipy import stats

assert "yfinance" not in sys.modules, "D12 violation!"
from rd032_common import calc_slot_summary, perm_diff_mean, sf


def analyze_20cm_h2_drawdown(df20: pd.DataFrame, win: dict, sh300: dict, dts: list, prev_td: dict, rng: np.random.Generator) -> dict:
    h_start = win["h_start"]
    w1y_start = win["w1y_start"]
    as_of = win["as_of"]

    # 1. Period slices across S82 slot1, S82 pass, A76 slot1, A76 pass, A(76-81) obs, and full pool
    slices = {}
    for cohort_name, mask_c in [
        ("S82_slot1", df20["is_standalone_slot1"].astype(bool)),
        ("S82_pass", df20["is_pass_official"].astype(bool)),
        ("A76_slot1", df20["is_standalone_a76"].astype(bool)),
        ("A76_pass", df20["score"] >= 76.0),
        ("A76_81_obs", df20["score"].between(76.0, 81.99)),
        ("All_Cand", pd.Series(True, index=df20.index)),
    ]:
        sub_c = df20[mask_c]
        periods = [
            ("5Y", pd.Series(True, index=sub_c.index)),
            ("Pre_1Y", sub_c["buy_date"] < w1y_start),
            ("1Y", sub_c["buy_date"] >= w1y_start),
            ("2026H1", sub_c["buy_date"].between("2026-01-01", "2026-06-30")),
            ("H2_Recent", sub_c["buy_date"] >= h_start),
        ]
        slices[cohort_name] = {}
        for pnm, pm in periods:
            ss = sub_c[pm]
            m = calc_slot_summary(ss, sh300, dts, prev_td)
            if len(ss) > 0:
                m["risk_hit_pct"] = sf(ss["risk_hit"].mean() * 100.0, 1)
                m["mkt10_dt_mean"] = sf(ss["f1_mkt10_dt_cnt"].mean(), 1)
                m["mkt10_zt_mean"] = sf(ss["mkt10_zt_cnt"].mean(), 1)
                m["mkt20_zt_mean"] = sf(ss["mkt20_zt_cnt"].mean(), 1)
                m["open_pct_mean"] = sf(ss["open_pct"].mean() * 100.0, 2)
                m["f06_hit_pct"] = sf((ss["F06_inst_net_pos"] > 0).mean() * 100.0, 1)
                m["f07_hit_pct"] = sf((ss["F07_mkt10_zt_gt55"] > 0).mean() * 100.0, 1)
                m["b2_strong_pct"] = sf((ss["d1_branch"] == "B2_D1_StrongYang").mean() * 100.0, 1)
                m["b4_deepyin_pct"] = sf((ss["d1_branch"] == "B4_D1_DeepYin").mean() * 100.0, 1)
            slices[cohort_name][pnm] = m

    # 2. Factor-by-factor check across Full Pool (N=809), A76 Pass, and S82 Pass in 5Y / 1Y / H2
    fac_list = [
        ("F01_open_gap", +1, "低开甜区[-7%,-3%](+4)/核按钮(-10)"),
        ("F02_rfm_le20", +1, "真实自由流值<=20亿(+4)"),
        ("F03_dist3d30_ge10", +1, "3日30%异动余量>=10%(+4)"),
        ("F04_zt60d_ge2", +1, "近60日涨停>=2次(+5)"),
        ("F05_seal_ratio_ge10_pen", -1, "封成比>=10%诱多(-5)"),
        ("F06_inst_net_pos", +1, "T0机构专用净买>0(+5)"),
        ("F07_mkt10_zt_gt55", +1, "T0全市场10cm涨停>55(+4/+7)"),
        ("F08_yizi20_siphon_pen", -1, "买日20cm一字虹吸(-5)"),
        ("F09_monday_pen", -1, "买入日周一(-8)"),
    ]
    fac_anatomy = []
    for fc, exp_s, desc in fac_list:
        row_d = {"factor": fc, "exp_sign": exp_s, "desc": desc}
        for pool_nm, df_p in [("All_Cand", df20), ("A76_pass", df20[df20["score"] >= 76.0])]:
            for pnm, pm in [("5Y", pd.Series(True, index=df_p.index)), ("1Y", df_p["buy_date"] >= w1y_start), ("H2", df_p["buy_date"] >= h_start)]:
                sub = df_p[pm]
                v = sub[fc].to_numpy(float)
                m_h = (v > 0) if exp_s > 0 else (v < 0)
                if m_h.sum() == 0:
                    m_h = v != 0
                res = perm_diff_mean(sub.loc[m_h, "net_ret"].to_numpy(float), sub.loc[~m_h, "net_ret"].to_numpy(float), rng, n_perm=1000)
                if res["mean_diff_pp"] is not None:
                    res["oriented_mean_edge_pp"] = sf(res["mean_diff_pp"] * exp_s, 2)
                    res["oriented_wr_edge_pp"] = sf(res["wr_diff_pp"] * exp_s, 2)
                row_d[f"{pool_nm}_{pnm}"] = res
        fac_anatomy.append(row_d)

    # 3. Exit branch & exit reason breakdown for S82_slot1 in Pre-H2 vs 2026H1 vs H2
    s82 = df20[df20["is_standalone_slot1"]].copy()
    branch_cmp = {}
    for pnm, pm in [("5Y", pd.Series(True, index=s82.index)), ("2026H1", s82["buy_date"].between("2026-01-01", "2026-06-30")), ("H2", s82["buy_date"] >= h_start)]:
        sub = s82[pm]
        b_dict = {}
        for br, g in sub.groupby("d1_branch"):
            b_dict[str(br)] = {
                "n": int(len(g)), "share_pct": sf(len(g) / max(len(sub), 1) * 100.0, 1),
                "wr_pct": sf((g["net_ret"] > 0).mean() * 100.0, 1),
                "mean_ret_pct": sf(g["net_ret"].mean() * 100.0, 2),
            }
        branch_cmp[pnm] = b_dict

    # 4. Monte Carlo & Binomial test for S82_slot1 H2 drawdown vs Pre-H2 baseline
    s82_pre = s82[s82["buy_date"] < h_start]
    s82_h2 = s82[s82["buy_date"] >= h_start].sort_values("buy_date")
    n_h2 = int(len(s82_h2))
    k_win = int((s82_h2["net_ret"] > 0).sum())
    mean_h2 = float(s82_h2["net_ret"].mean()) if n_h2 > 0 else 0.0
    p_pre = float((s82_pre["net_ret"] > 0).mean()) if len(s82_pre) > 0 else 0.58
    binom_p = float(stats.binom.cdf(k_win, n_h2, p_pre)) if n_h2 > 0 else 1.0
    r_pre = s82_pre["net_ret"].to_numpy(float)
    if n_h2 > 0 and len(r_pre) >= 10:
        draws = rng.choice(r_pre, size=(20000, n_h2), replace=True)
        mc_p_wr = float(((draws > 0).mean(axis=1) <= (k_win / n_h2) + 1e-9).mean())
        mc_p_mean = float((draws.mean(axis=1) <= mean_h2 + 1e-9).mean())
    else:
        mc_p_wr, mc_p_mean = 1.0, 1.0

    # 5. Cold-market F06 dependence inside H2 S82
    cold_f06 = s82_h2[(s82_h2["F07_mkt10_zt_gt55"] == 0) & (s82_h2["F06_inst_net_pos"] > 0)]
    h2_trades = [
        {
            "buy_date": r.buy_date, "code": r.code, "name": r.name, "score": float(r.score),
            "open_pct": sf(float(r.open_pct) * 100.0, 2), "d1_branch": str(r.d1_branch),
            "exit_reason": str(r.exit_reason), "net_ret_pct": sf(float(r.net_ret) * 100.0, 2),
            "risk_hit": int(r.risk_hit), "mkt10_dt": int(r.f1_mkt10_dt_cnt) if pd.notna(r.f1_mkt10_dt_cnt) else 0,
            "mkt10_zt": int(r.mkt10_zt_cnt) if pd.notna(r.mkt10_zt_cnt) else 0,
            "f06_inst": int(r.F06_inst_net_pos > 0), "f07_mkt10": int(r.F07_mkt10_zt_gt55 > 0),
        }
        for r in s82_h2.itertuples(index=False)
    ]

    verdict = "NORMAL_VOLATILITY_AND_REGIME_SQUEEZE_WITH_F06_CAUTION" if (binom_p > 0.05 and mean_h2 > 0) else "FACTOR_DEGRADATION_WARNING"
    return {
        "as_of": as_of,
        "h2_window": f"{h_start}~{as_of}",
        "verdict": verdict,
        "cohort_periods": slices,
        "factor_anatomy_9f": fac_anatomy,
        "d1_branch_comparison": branch_cmp,
        "statistical_noise_test": {
            "pre_h2_n": int(len(s82_pre)), "pre_h2_wr_pct": sf(p_pre * 100.0, 2),
            "h2_n": n_h2, "h2_wins": k_win, "h2_wr_pct": sf(k_win / max(n_h2, 1) * 100.0, 2),
            "h2_mean_ret_pct": sf(mean_h2 * 100.0, 2),
            "binom_p_wr_le": sf(binom_p, 4), "mc20k_p_wr_le": sf(mc_p_wr, 4), "mc20k_p_mean_le": sf(mc_p_mean, 4),
        },
        "s82_h2_cold_f06_subset": {
            "n": int(len(cold_f06)),
            "wr_pct": sf((cold_f06["net_ret"] > 0).mean() * 100.0, 1) if len(cold_f06) else None,
            "mean_ret_pct": sf(cold_f06["net_ret"].mean() * 100.0, 2) if len(cold_f06) else None,
        },
        "s82_h2_trades": h2_trades,
    }
