#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Gate 3 (Zero-lookahead / timestamp / timezone PIT) and Gate 5 (Diff-trade causality) audits."""
import json, sqlite3, sys
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1 = f"{RD035}/wave1_base"

PATCHED_TREES_AUG26 = (
    "PCB本体", "成熟制程涨价", "晶圆代工", "光纤光缆", "MLCC/被动元件",
)


def _nav(s: pd.Series | np.ndarray) -> float:
    a = np.asarray(s, dtype=float)
    return float(np.prod(1.0 + a)) if len(a) else 1.0


def _ex5(s: pd.Series | np.ndarray) -> float:
    a = np.sort(np.asarray(s, dtype=float))
    return float(np.prod(1.0 + a[:-5])) if len(a) > 5 else 1.0


def audit_mode_e3_pit(df_e3: pd.DataFrame, ref_names: dict) -> dict:
    with open(f"{SIM}/data/product_tree_map.json", encoding="utf-8") as f:
        ptm = json.load(f)
    code_tree = {}
    patched_codes = set()
    for row in ptm["trees"]:
        c6 = str(row["code"]).zfill(6)
        tr = str(row.get("tree", ""))
        nd = str(row.get("node", ""))
        code_tree.setdefault(c6, []).append(f"{tr}::{nd}")
        if any(k in tr or k in nd for k in PATCHED_TREES_AUG26):
            patched_codes.add(c6)

    us = pd.read_parquet(f"{SIM}/data/us_price_db/all_daily.parquet", columns=["date", "ticker", "close", "adj_close"])
    us["dt"] = pd.to_datetime(us["date"]).dt.strftime("%Y-%m-%d")
    us = us[us["dt"] >= "2022-12-01"].sort_values(["ticker", "dt"]).reset_index(drop=True)
    us["ret_c"] = us.groupby("ticker", sort=False)["close"].pct_change() * 100.0
    us["ret_ac"] = us.groupby("ticker", sort=False)["adj_close"].pct_change() * 100.0
    us = us.dropna(subset=["ret_c"]).copy()

    matched_rows = []
    n_strict_t_lt_buy = 0
    n_same_or_future_only = 0
    n_unmatched = 0
    gap_days_list = []

    for r in df_e3.itertuples(index=False):
        bd = str(r.buy_date)[:10]
        c6 = str(r.code).zfill(6)
        ur = float(r.us_ret1d)
        cand = us[(np.abs(us["ret_c"] - ur) < 1e-4) | (np.abs(us["ret_ac"] - ur) < 1e-4)]
        prior = cand[(cand["dt"] < bd)]
        if not prior.empty:
            prior = prior.sort_values("dt", ascending=False)
            best = prior.iloc[0]
            gdays = (pd.Timestamp(bd) - pd.Timestamp(best["dt"])).days
            is_valid_gap = gdays <= 6
            if is_valid_gap:
                n_strict_t_lt_buy += 1
            else:
                n_unmatched += 1
            gap_days_list.append(int(gdays))
            matched_rows.append({
                "buy_date": bd, "code": c6, "name": ref_names.get(c6, ""),
                "us_ticker": str(best["ticker"]), "us_date": str(best["dt"]),
                "cal_gap_days": int(gdays), "us_ret1d": round(ur, 3),
                "prev_streak": int(r.prev_streak), "net_ret_pct": round(float(r.net_ret) * 100.0, 2),
                "in_aug26_patched_tree": c6 in patched_codes,
            })
        else:
            same_or_fut = cand[cand["dt"] >= bd]
            if not same_or_fut.empty:
                n_same_or_future_only += 1
            else:
                n_unmatched += 1
            matched_rows.append({
                "buy_date": bd, "code": c6, "name": ref_names.get(c6, ""),
                "us_ticker": "UNMATCHED", "us_date": "",
                "cal_gap_days": -1, "us_ret1d": round(ur, 3),
                "prev_streak": int(r.prev_streak), "net_ret_pct": round(float(r.net_ret) * 100.0, 2),
                "in_aug26_patched_tree": c6 in patched_codes,
            })

    mdf = pd.DataFrame(matched_rows)
    rng = np.random.default_rng(42)
    sample_idx = sorted(rng.choice(len(mdf), size=min(10, len(mdf)), replace=False).tolist())
    sample_10 = mdf.iloc[sample_idx].to_dict("records")

    # Decompose prev_streak==0 vs >=1, and patched_tree vs non_patched_tree
    m_nozt = df_e3["prev_streak"].to_numpy() == 0
    m_patch = mdf["in_aug26_patched_tree"].to_numpy()
    m_pre_aug = df_e3["buy_date"].to_numpy() < "2026-08-14"
    r_all = df_e3["net_ret"].to_numpy(float)

    return {
        "n_trades": int(len(df_e3)),
        "us_cn_tz_alignment": {
            "strict_us_date_lt_cn_buy_date_within_6d": int(n_strict_t_lt_buy),
            "same_day_or_future_only_leaks": int(n_same_or_future_only),
            "unmatched_or_gt6d": int(n_unmatched),
            "gap_days_min_max": [int(min(gap_days_list)), int(max(gap_days_list))] if gap_days_list else None,
            "verdict_tz": "CAUSAL_US_T1_TO_CN_T_0925" if n_same_or_future_only == 0 and n_strict_t_lt_buy == len(df_e3) else "CHECK_GAPS",
        },
        "random_10_samples": sample_10,
        "hindsight_and_zt_confounding": {
            "product_tree_built_at": ptm.get("built_at"),
            "patch_dates": [p.get("date") for p in ptm.get("patch_log", [])],
            "non_zt_prev_streak_0": {"n": int(m_nozt.sum()), "nav": round(_nav(r_all[m_nozt]), 4), "ex5": round(_ex5(r_all[m_nozt]), 4)},
            "zt_relay_prev_streak_ge1": {"n": int((~m_nozt).sum()), "nav": round(_nav(r_all[~m_nozt]), 4), "ex5": round(_ex5(r_all[~m_nozt]), 4)},
            "aug26_patched_tree_stocks": {"n": int(m_patch.sum()), "nav": round(_nav(r_all[m_patch]), 4)},
            "non_patched_tree_stocks": {"n": int((~m_patch).sum()), "nav": round(_nav(r_all[~m_patch]), 4), "ex5": round(_ex5(r_all[~m_patch]), 4)},
            "pre_2026_08_14": {"n": int(m_pre_aug.sum()), "nav": round(_nav(r_all[m_pre_aug]), 4)},
            "post_2026_08_14_pure_oos_vs_tree": {"n": int((~m_pre_aug).sum()), "nav": round(_nav(r_all[~m_pre_aug]), 4)},
        },
    }


def audit_modc_c1_pit(df_c1: pd.DataFrame) -> dict:
    codes = sorted(df_c1["code"].astype(str).str.zfill(6).unique().tolist())
    con = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    ph = ",".join("?" for _ in codes)
    nt = pd.read_sql_query(
        f"SELECT sec_code, ann_type, pub_datetime_cst, trade_date_avail, title FROM notices "
        f"WHERE ann_type LIKE '业绩预告%' AND sec_code IN ({ph})",
        con, params=codes,
    )
    con.close()
    nt["c6"] = nt["sec_code"].astype(str).str.zfill(6)
    nt["pub_d"] = nt["pub_datetime_cst"].astype(str).str[:10]
    nt["pub_h"] = nt["pub_datetime_cst"].astype(str).str[11:19]
    nt["tda"] = nt["trade_date_avail"].astype(str).str[:10]
    by_code = {k: g for k, g in nt.groupby("c6")}

    n_avail_ok, n_pub_lt_buy, n_pub_eq_buy_pre0925, n_leak, n_missing = 0, 0, 0, 0, 0
    zero_hms_cnt = 0
    samples = []
    for i, r in enumerate(df_c1.itertuples(index=False)):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)[:10]
        g = by_code.get(c6)
        if g is None:
            n_missing += 1; continue
        # Match notice whose trade_date_avail is on or shortly before buy_date (C1 triggers on avail_dt or +1/+2d if open_pct ok? Let's check exact!)
        sub = g[g["tda"] <= bd].sort_values("tda", ascending=False)
        if sub.empty:
            fut = g[g["tda"] > bd]
            if not fut.empty:
                n_leak += 1
            else:
                n_missing += 1
            continue
        rec = sub.iloc[0]
        n_avail_ok += 1
        if rec["pub_h"] == "00:00:00":
            zero_hms_cnt += 1
        if rec["pub_d"] < bd:
            n_pub_lt_buy += 1
        elif rec["pub_d"] == bd and rec["pub_h"] < "09:25:00" and rec["pub_h"] != "00:00:00":
            n_pub_eq_buy_pre0925 += 1
        else:
            n_leak += 1
        if i < 5:
            samples.append({
                "code": c6, "buy_date": bd, "pub_datetime_cst": str(rec["pub_datetime_cst"]),
                "trade_date_avail": str(rec["tda"]), "ann_type": str(rec["ann_type"]),
            })
    return {
        "n_trades": int(len(df_c1)),
        "n_trade_date_avail_le_buy": int(n_avail_ok),
        "n_pub_date_strictly_lt_buy_date": int(n_pub_lt_buy),
        "n_pub_same_day_pre0925_verified": int(n_pub_eq_buy_pre0925),
        "n_zero_hms_000000_but_tda_lt_or_eq_buy": int(zero_hms_cnt),
        "n_leaks": int(n_leak),
        "n_missing": int(n_missing),
        "samples": samples,
    }


def audit_modb_b1_pit(df_b1: pd.DataFrame, cal_dates: list[str]) -> dict:
    codes = sorted(df_b1["code"].astype(str).str.zfill(6).unique().tolist())
    con = sqlite3.connect(f"file:{SIM}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    ph = ",".join("?" for _ in codes)
    qa = pd.read_sql_query(
        f"SELECT sec_code, pub_datetime_cst, trade_date_avail FROM ir_qa "
        f"WHERE fetch_status='DONE' AND sec_code IN ({ph})",
        con, params=codes,
    )
    con.close()
    qa["c6"] = qa["sec_code"].astype(str).str.zfill(6)
    qa["pub_d"] = qa["pub_datetime_cst"].astype(str).str[:10]
    qa["pub_h"] = qa["pub_datetime_cst"].astype(str).str[11:19]
    qa["tda"] = qa["trade_date_avail"].astype(str).str[:10]

    # Replicate run_w2b6_modB_ir_qa mapping: pub_h >= "09:25:00" -> next trade day, else >= pub_d
    cal_arr = np.array(sorted(cal_dates))
    idx_eq = np.searchsorted(cal_arr, qa["pub_d"].to_numpy(), side="left")
    idx_gt = np.searchsorted(cal_arr, qa["pub_d"].to_numpy(), side="right")
    is_ge925 = qa["pub_h"].to_numpy() >= "09:25:00"
    eff_idx = np.where(is_ge925, idx_gt, idx_eq)
    eff_dt = np.where(eff_idx < len(cal_arr), cal_arr[np.minimum(eff_idx, len(cal_arr) - 1)], "9999-99-99")
    qa["eff_dt_script"] = eff_dt
    by_key = qa.groupby(["c6", "eff_dt_script"])

    statuses, leak_rows = [], []
    for r in df_b1.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)[:10]
        if (c6, bd) not in by_key.groups:
            statuses.append("UNMATCHED"); continue
        sub = by_key.get_group((c6, bd))
        if (sub["tda"] > bd).any() and (sub["tda"] <= bd).sum() == 0:
            st = "DEFINITE_LEAK_TDA_GT_BUY"
            leak_rows.append({"code": c6, "buy_date": bd, "pub": str(sub["pub_datetime_cst"].iloc[0]), "tda": str(sub["tda"].iloc[0]), "net_ret_pct": round(float(r.net_ret) * 100.0, 2), "status": st})
        elif (sub["pub_d"] == bd).any() and (sub["pub_h"] == "00:00:00").any() and not ((sub["pub_d"] < bd) | ((sub["pub_h"] > "00:00:00") & (sub["pub_h"] < "09:25:00"))).any():
            st = "UNVERIFIED_000000_SAME_DAY"
            leak_rows.append({"code": c6, "buy_date": bd, "pub": str(sub["pub_datetime_cst"].iloc[0]), "tda": str(sub["tda"].iloc[0]), "net_ret_pct": round(float(r.net_ret) * 100.0, 2), "status": st})
        else:
            st = "CLEAN_VERIFIED"
        statuses.append(st)

    st_s = pd.Series(statuses)
    nr = df_b1["net_ret"].to_numpy(float)
    m_clean = (st_s == "CLEAN_VERIFIED").to_numpy()
    m_def_leak = (st_s == "DEFINITE_LEAK_TDA_GT_BUY").to_numpy()
    m_unv = (st_s == "UNVERIFIED_000000_SAME_DAY").to_numpy()
    return {
        "n_trades": int(len(df_b1)),
        "counts": st_s.value_counts().to_dict(),
        "clean_only": {"n": int(m_clean.sum()), "nav": round(_nav(nr[m_clean]), 4), "ex5": round(_ex5(nr[m_clean]), 4)},
        "definite_leak_tda_gt_buy": {"n": int(m_def_leak.sum()), "nav": round(_nav(nr[m_def_leak]), 4)},
        "unverified_000000_same_day": {"n": int(m_unv.sum()), "nav": round(_nav(nr[m_unv]), 4)},
        "sample_leaks": leak_rows[:8],
    }


def audit_w2b5_track_c_pit(df_yield_all: pd.DataFrame, df_yield_open: pd.DataFrame) -> dict:
    v20 = pd.read_parquet(f"{WAVE1}/v20_baseline_ledger_278.parquet")
    v20_wf = v20[v20["buy_date"] >= "2023-01-03"].copy()
    mkt = pd.read_parquet(f"{WAVE1}/market_daily_all_new_factors_pit.parquet", columns=["trade_date", "nt_v3_score_live_t1", "nt_v3_score_eod_t1", "nt_etf22_wflow_yi_t1"])
    mkt["trade_date"] = mkt["trade_date"].astype(str).str[:10]
    m_lu = mkt.set_index("trade_date").to_dict("index")

    # Find ETF trades overlapping V20 intraday triggers (>0925)
    v20_intraday = v20_wf[v20_wf["buy_hhmm"] > 925][["buy_date", "exit_date", "code", "name", "buy_hhmm", "net_ret"]]
    all_rows = df_yield_all.merge(mkt, left_on="buy_date", right_on="trade_date", how="left")
    collisions = []
    for r in df_yield_all.itertuples(index=False):
        hit = v20_wf[(v20_wf["buy_date"] >= r.buy_date) & (v20_wf["buy_date"] <= r.exit_date)]
        intra = hit[hit["buy_hhmm"] > 925]
        op = hit[hit["buy_hhmm"] <= 925]
        collisions.append({
            "etf_buy": r.buy_date, "etf_exit_allv20": r.exit_date,
            "etf_net_ret_pct": round(float(r.net_ret) * 100.0, 2),
            "nt_v3_eod_t1": round(float(m_lu.get(r.buy_date, {}).get("nt_v3_score_eod_t1", np.nan)), 2),
            "nt_v3_live_t1": round(float(m_lu.get(r.buy_date, {}).get("nt_v3_score_live_t1", np.nan)), 2),
            "v20_open_hits": op[["buy_date", "code", "buy_hhmm"]].to_dict("records"),
            "v20_intraday_hits": intra[["buy_date", "code", "buy_hhmm", "net_ret"]].to_dict("records"),
        })
    return {
        "v20_wf_n": int(len(v20_wf)),
        "v20_wf_buy_hhmm_counts": v20_wf["buy_hhmm"].value_counts().to_dict(),
        "yield_all_v20_n": int(len(df_yield_all)),
        "yield_all_v20_nav": round(_nav(df_yield_all["net_ret"]), 4),
        "yield_open_0925_n": int(len(df_yield_open)),
        "yield_open_0925_nav": round(_nav(df_yield_open["net_ret"]), 4),
        "etf_trades_v3_and_v20_collisions": collisions,
        "note": "Yield_all_v20 exits ETF at 09:24 open using intraday V20 signal (>09:25); causal Yield_open_0925_only crashes comb_delta_nav_ratio from 1.3096 to 0.7628 in w2b5_track_c.json",
    }


def _trade_diff(df_new: pd.DataFrame, df_base: pd.DataFrame, ref_names: dict) -> dict:
    kn = {(str(r.buy_date)[:10], str(r.code).zfill(6)): (float(r.net_ret), str(r.exit_date)[:10]) for r in df_new.itertuples(index=False)}
    kb = {(str(r.buy_date)[:10], str(r.code).zfill(6)): (float(r.net_ret), str(r.exit_date)[:10]) for r in df_base.itertuples(index=False)}
    rem_keys = sorted(set(kb) - set(kn))
    add_keys = sorted(set(kn) - set(kb))
    com_keys = sorted(set(kn) & set(kb))
    return {
        "n_new": int(len(df_new)), "n_base": int(len(df_base)),
        "n_common": int(len(com_keys)), "n_removed": int(len(rem_keys)), "n_added": int(len(add_keys)),
        "removed_nav_impact": round(float(np.prod([1.0 + kb[k][0] for k in rem_keys])), 4) if rem_keys else 1.0,
        "added_nav_impact": round(float(np.prod([1.0 + kn[k][0] for k in add_keys])), 4) if add_keys else 1.0,
        "removed_trades": [{"buy_date": k[0], "code": k[1], "name": ref_names.get(k[1], ""), "exit_date": kb[k][1], "net_ret_pct": round(kb[k][0] * 100.0, 2)} for k in rem_keys],
        "added_trades": [{"buy_date": k[0], "code": k[1], "name": ref_names.get(k[1], ""), "exit_date": kn[k][1], "net_ret_pct": round(kn[k][0] * 100.0, 2)} for k in add_keys],
    }


def audit_gate5_all_diffs(ledgers: dict[str, pd.DataFrame], ref_names: dict) -> dict:
    pairs = [
        ("3to4_M4_MineBL15_vs_baseline", "3a_w2a2_3to4_M4_MineBL15_Orig", "3r_w2a2_3to4_baseline_wf"),
        ("pry_M1_DropNeg_vs_baseline", "3b_w2a2_pry_M1_WF_DropNeg_tm05", "3r_w2a2_pry_baseline_wf"),
        ("3to4_M2_XTR_ModeB_vs_baseline", "3c_w2a2_3to4_M2_XTR_ModeB_d10", "3r_w2a2_3to4_baseline_wf"),
        ("w2a3_F06_COLD50_vs_BASE_S80", "1a_w2a3_F06_COLD50_thr80", "1r_w2a3_BASE_V11_S80"),
        ("w2a3_CLEAN_B_S84_vs_BASE_S82", "1b_w2a3_CLEAN_B_cold50_d15_S84", "1r_w2a3_BASE_V11_S82"),
        ("w2a3_CLEAN_B_S80_vs_BASE_S80", "1c_w2a3_CLEAN_B_cold50_d15_S80", "1r_w2a3_BASE_V11_S80"),
        ("w2a4_20cm_MechNative_d15_vs_BASE_S80", "2a_w2a4_20cm_MechNative_d15", "1r_w2a3_BASE_V11_S80"),
        ("w2a4_V20Comb_vs_V20_Baseline", "2b_w2a4_V20Comb_MechNative_d10", "2r_V20_Baseline_WF"),
        ("w2b1_ModeM_50bps_rescore_vs_30bps", "7b_w2b1_ModeM_P0_E1_X2_k15_50bps_rescore", "7a_w2b1_ModeM_P0_E1_X2_k15_30bps"),
    ]
    out = {}
    for label, nk, bk in pairs:
        if nk in ledgers and bk in ledgers:
            d = _trade_diff(ledgers[nk], ledgers[bk], ref_names)
            # Keep full lists for small diffs (<=30), summarize counts + top impact for large diffs
            if len(d["removed_trades"]) > 25:
                d["removed_trades_top5_worst_and_best"] = sorted(d["removed_trades"], key=lambda x: x["net_ret_pct"])[:5] + sorted(d["removed_trades"], key=lambda x: x["net_ret_pct"], reverse=True)[:5]
                del d["removed_trades"]
            if len(d["added_trades"]) > 25:
                d["added_trades_top5_worst_and_best"] = sorted(d["added_trades"], key=lambda x: x["net_ret_pct"])[:5] + sorted(d["added_trades"], key=lambda x: x["net_ret_pct"], reverse=True)[:5]
                del d["added_trades"]
            out[label] = d
    return out
