#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD039-B Front 3B: 超跌撬板 V2.1 T+1 Left-Tail Physical Autopsy & Delayed Confirmation Audit
  - 100% Baseline Parity Check (16 trades 2.4400x @ 20bps, WF 10 trades 1.4852x / Sharpe 0.732 / PLR 0.75)
  - 5m Coverage Audit across ALL local 5m databases/parquets (exact counts, ZERO fabricated 5m!)
  - Full pool (759 rows / 435 passing across 25 dates) loss autopsy & D0-reseal-DT T+1 lockup physics
  - Tests: (1) Daily-OHLC optimistic upper-bound delayed confirmation (+0.5%..+3.0%),
           (2) Pre-09:25 / 09:25 crash & cold day skip filters (mkt_0925_zt_cnt, L1_dt_cnt_t1, open_pct),
           (3) P165 (16/10) vs P150 (30) vs 435-pool daily-EW, plus CSCV PBO & IS(21-24)->OOS(25-26).
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import pickle
import sqlite3
import sys
import time
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _f23_common as cm


def audit_5m_coverage_pry(m_pry: pd.DataFrame, led_16: pd.DataFrame) -> dict:
    """Verify exact local 5m bar coverage on pry 759 pool, 435 passing, and 16 ledger trades."""
    s_union = set()
    for p in (
        f"{cm.SIM}/data/all_strategies_5m_complete_pit.parquet",
        f"{cm.SIM}/data/cand_5m_bars_v15_complete.parquet",
        f"{cm.SIM}/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet",
        f"{cm.SLIP_P2}/_patch_5m_bars.parquet",
    ):
        if os.path.exists(p):
            d = pd.read_parquet(p, columns=["c6", "date"])
            s_union.update(zip(d["c6"].astype(str).str.zfill(6), d["date"].astype(str).str[:10]))

    p2_path = f"{cm.SIM}/backtests_astock2/_archive/20261116/old_phase1_phase2_supersede/p4_pry_board/p2_5m_bars_cache.pkl"
    if os.path.exists(p2_path):
        with open(p2_path, "rb") as f:
            for k in pickle.load(f).keys():
                s_union.add((str(k[0]).zfill(6), str(k[1])[:10]))

    fb_db = f"{cm.SIM}/backtests_astock2/data_5y/firstboard_5m_5y_pit.db"
    if os.path.exists(fb_db):
        con = sqlite3.connect(f"file:{fb_db}?mode=ro", uri=True)
        for r in con.execute("SELECT DISTINCT sec_code, trade_date FROM firstboard_5m_kline"):
            s_union.add((str(r[0])[:6].zfill(6), str(r[1])[:10]))
        con.close()

    mp = m_pry[m_pry["orig_pass"] == 1]
    wf16 = led_16[led_16["buy_date"] >= cm.WF_START]
    return {
        "union_5m_pairs": len(s_union),
        "pool_759_buy_date_5m": int(sum((r.c6, r.bd) in s_union for r in m_pry.itertuples())),
        "pool_759_buy_date_cov_pct": round(sum((r.c6, r.bd) in s_union for r in m_pry.itertuples()) / len(m_pry) * 100.0, 2),
        "pass_435_buy_date_5m": int(sum((r.c6, r.bd) in s_union for r in mp.itertuples())),
        "pass_435_buy_date_cov_pct": round(sum((r.c6, r.bd) in s_union for r in mp.itertuples()) / len(mp) * 100.0, 2),
        "ledger_16_buy_date_5m": int(sum((r.code, r.buy_date) in s_union for r in led_16.itertuples())),
        "ledger_16_exit_date_5m": int(sum((r.code, r.exit_date) in s_union for r in led_16.itertuples())),
        "ledger_wf10_buy_date_5m": int(sum((r.code, r.buy_date) in s_union for r in wf16.itertuples())),
    }


def sim_pry_slot(df_cand: pd.DataFrame) -> pd.DataFrame:
    """Exact single-slot simulation for pry (priority: orig_score desc, bias10 asc, code asc)."""
    if df_cand.empty:
        return df_cand
    srt = df_cand.sort_values(["buy_date", "orig_score", "bias10", "code"], ascending=[True, False, True, True], kind="mergesort")
    taken = []
    fdt = ""
    for r in srt.itertuples(index=False):
        if (not fdt) or (r.buy_date > fdt):
            taken.append(r._asdict())
            fdt = str(r.exit_date)
    return pd.DataFrame(taken)


def main():
    t0 = time.time()
    m_pry = pd.read_parquet(f"{cm.WAVE1}/pool_pry_master_pit.parquet")
    m_pry["c6"] = m_pry["code"].astype(str).str.zfill(6)
    m_pry["code"] = m_pry["c6"]
    m_pry["bd"] = m_pry["buy_date"].astype(str).str[:10]
    m_pry["buy_date"] = m_pry["bd"]
    m_pry["exit_date"] = m_pry["exit_date"].astype(str).str[:10]
    m_pry["net_ret_020"] = m_pry["net_ret"].astype(float)

    led_16 = pd.read_csv(f"{cm.SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_pry_v21_ss165_clean.csv", dtype={"code": str})
    led_16["code"] = led_16["code"].str.zfill(6)

    # Load daily truth ONLY for pry codes (skip loading full 5m since pry has 0.46% 5m coverage!)
    # Load calendars & pry daily bars via _f23_common
    ctx = cm.load_filtered_5m_and_dmap(set(m_pry["code"].unique()))
    cov = audit_5m_coverage_pry(m_pry, led_16)
    print(f"[Front3B Pry] 5m coverage audit: {cov} | RSS={cm.rss_mb()} MB")

    # Attach bias10 if missing
    p_clean = pd.read_csv(f"{cm.SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry/pool_pry_full_clean.csv", dtype={"code": str})
    p_clean["code"] = p_clean["code"].str.zfill(6)
    p_clean["buy_date"] = p_clean["buy_date"].astype(str).str[:10]
    b10_map = dict(zip(zip(p_clean["buy_date"], p_clean["code"]), p_clean["bias10"]))
    m_pry["bias10"] = [b10_map.get((r.buy_date, r.code), 0.0) for r in m_pry.itertuples(index=False)]

    # Daily OHLC ratios
    m_pry["d0_hi_o"] = m_pry["bar_b0_high"] / m_pry["bar_b0_open"] - 1.0
    m_pry["d0_lo_o"] = m_pry["bar_b0_low"] / m_pry["bar_b0_open"] - 1.0
    m_pry["d0_c_o"] = m_pry["bar_b0_close"] / m_pry["bar_b0_open"] - 1.0
    m_pry["is_d0_dt"] = m_pry["exit_reason"].astype(str).str.contains("D0回封跌停")

    # 1. Exact Baseline Parity Check on P165 (orig_score >= 165)
    p165 = m_pry[m_pry["orig_score"] >= 165.0].copy()
    sl_base = sim_pry_slot(p165)
    assert len(sl_base) == 16 and list(zip(sl_base["buy_date"], sl_base["code"])) == list(zip(led_16["buy_date"], led_16["code"]))
    ret_diff = float(np.max(np.abs(sl_base["net_ret_020"].to_numpy() - led_16["net_ret"].to_numpy())))
    assert ret_diff < 1e-6, f"Pry parity diff={ret_diff}"
    res_base = cm.evaluate_full_suite(ctx, "pry", "V21_Baseline_P165", sl_base, 0.0)
    base_dr_wf = res_base["dr_wf_030"]
    base_dr_5y = res_base["dr_5y_030"]
    res_base = cm.evaluate_full_suite(ctx, "pry", "V21_Baseline_P165", sl_base, 0.0, base_dr_wf, base_dr_5y)
    wb = res_base["windows_030"]["WF_2326"]
    print(f"  [Parity PASS] diff={ret_diff:.2e} | 5Y_020={np.prod(1+sl_base['net_ret_020']):.4f}x | WF_030 n={wb['n']} nav={wb['nav']}x sh={wb['sharpe']} plr={wb['plr']} mloss={wb['mean_loss_pct']}%")

    # 2. Left-Tail Autopsy on P165 (435 rows) & Full Pool (759 rows)
    autopsy = {}
    for lbl, sub in [("P165_pass435", p165), ("P150_pass541", m_pry[m_pry["orig_score"] >= 150.0]), ("All_759", m_pry)]:
        losses = sub[sub["net_ret_020"] <= 0]
        d0_dt = sub[sub["is_d0_dt"]]
        wins = sub[sub["net_ret_020"] > 0]
        autopsy[lbl] = {
            "n_total": int(len(sub)),
            "n_days": int(sub["buy_date"].nunique()),
            "n_losses": int(len(losses)),
            "n_le_m7pct": int((sub["net_ret_020"] <= -0.07).sum()),
            "mean_loss_pct": round(float(losses["net_ret_020"].mean() * 100.0), 2) if len(losses) else 0.0,
            "n_d0_reseal_dt": int(len(d0_dt)),
            "d0_reseal_dt_share_of_losses_pct": round(len(d0_dt) / max(1, len(losses)) * 100.0, 2),
            "d0_reseal_dt_dates": sorted(d0_dt["buy_date"].unique().tolist()),
            "d0_reseal_dt_mean_ret_pct": round(float(d0_dt["net_ret_020"].mean() * 100.0), 2) if len(d0_dt) else 0.0,
            "d0_reseal_dt_d0_hi_o_quantiles_pct": [round(float(x) * 100.0, 2) for x in np.quantile(d0_dt["d0_hi_o"], [0, 0.25, 0.5, 0.75, 0.9, 1.0])] if len(d0_dt) else [],
            "wins_d0_hi_o_lt_150bps_pct": round(float((wins["d0_hi_o"] < 0.015).mean() * 100.0), 2) if len(wins) else 0.0,
            "wins_d0_hi_o_zero_pct": round(float((wins["d0_hi_o"] <= 0.0001).mean() * 100.0), 2) if len(wins) else 0.0,
        }

    # 3. Test Cures (A: Daily-OHLC Optimistic Delayed Confirmation Upper Bound; B: 09:25 Market/Open Gate; C: P150 Comparison)
    results = [res_base]
    slot_map = {"V21_Baseline_P165": sl_base}

    # A. Optimistic Upper-Bound Delayed Confirmation: assume buying at open * (1 + d) if d0_hi_o >= d & open*(1+d) < zt_px,
    #    and recompute net_ret scaled by (open / (open*(1+d)))! NOTE: this is an OPTIMISTIC UPPER BOUND (ignores 5m reverse order & vel slip!).
    for d_pct in [0.005, 0.010, 0.015, 0.020, 0.030]:
        sub = p165[p165["d0_hi_o"] >= d_pct].copy()
        # Keep capped below zt_px (~+10%): new buy_px = min(zt_px, open*(1+d_pct))
        zt_est = np.floor(sub["bar_b0_open"] / (1.0 + sub["open_pct"]) * 1.10 * 100.0 + 0.5) / 100.0
        new_bp = np.minimum(zt_est, sub["bar_b0_open"] * (1.0 + d_pct))
        ok_px = new_bp < zt_est - 0.005
        sub = sub[ok_px].copy()
        new_bp = new_bp[ok_px]
        sub["net_ret_020"] = (1.0 + sub["net_ret_020"]) * (sub["buy_price"] / new_bp) - 1.0
        sub["buy_price"] = np.round(new_bp, 2)
        sl = sim_pry_slot(sub)
        miss_r = (len(p165) - len(sub)) / len(p165) * 100.0
        vid = f"UB_DelayConf_open_p{int(round(d_pct*1000)):03d}"
        r = cm.evaluate_full_suite(ctx, "pry", vid, sl, miss_r, base_dr_wf, base_dr_5y)
        results.append(r)
        slot_map[vid] = sl

    # B. Strictly Causal Pre-09:25 / 09:25 Market & Open Filters (100% exact without 5m assumptions!)
    gate_specs = [
        ("Skip_zt0925_lt3", lambda d: d["mkt_0925_zt_cnt"] >= 3),
        ("Skip_zt0925_lt5", lambda d: d["mkt_0925_zt_cnt"] >= 5),
        ("Skip_zt0925_lt8", lambda d: d["mkt_0925_zt_cnt"] >= 8),
        ("Skip_zt0925_lt10", lambda d: d["mkt_0925_zt_cnt"] >= 10),
        ("Skip_dtT1_gt150", lambda d: d["L1_dt_cnt_t1"] <= 150),
        ("Skip_dtT1_gt100", lambda d: d["L1_dt_cnt_t1"] <= 100),
        ("Open_ge_050bps", lambda d: d["open_pct"] >= 0.005),
        ("Open_ge_100bps", lambda d: d["open_pct"] >= 0.010),
        ("Open_050_to_350bps", lambda d: d["open_pct"].between(0.005, 0.035)),
        ("Combo_zt5_open050", lambda d: (d["mkt_0925_zt_cnt"] >= 5) & (d["open_pct"] >= 0.005)),
        ("P150_Expanded", None),
        ("P150_zt0925_ge5", lambda d: d["mkt_0925_zt_cnt"] >= 5),
    ]
    for vid, fn in gate_specs:
        pool_use = m_pry[m_pry["orig_score"] >= 150.0].copy() if vid.startswith("P150_") else p165.copy()
        sub = pool_use[fn(pool_use)].copy() if fn is not None else pool_use
        sl = sim_pry_slot(sub)
        miss_r = (len(pool_use) - len(sub)) / len(pool_use) * 100.0
        r = cm.evaluate_full_suite(ctx, "pry", vid, sl, miss_r, base_dr_wf, base_dr_5y)
        results.append(r)
        slot_map[vid] = sl

    # Also compute daily equal-weight 25-day (P165) & 44-day (P150) under delayed conf vs baseline
    ew_diag = {}
    for lbl, sub_p in [("P165_Base", p165), ("P165_UB_Delay15", p165[p165["d0_hi_o"] >= 0.015]), ("P165_zt5", p165[p165["mkt_0925_zt_cnt"] >= 5])]:
        g_d = sub_p.groupby("buy_date")["net_ret_020"].mean()
        g_wf = g_d[g_d.index >= cm.WF_START]
        ew_diag[lbl] = {
            "n_days_5y": int(len(g_d)), "ew_nav_5y": round(float(np.prod(1.0 + g_d)), 4),
            "n_days_wf": int(len(g_wf)), "ew_nav_wf": round(float(np.prod(1.0 + g_wf)), 4),
            "ew_wr_wf_pct": round(float((g_wf > 0).mean() * 100.0), 2) if len(g_wf) else 0.0,
        }

    mat_wf = {r["variant_id"]: r["dr_wf_030"] for r in results if r.get("dr_wf_030") is not None}
    mat_5y = {r["variant_id"]: r["dr_5y_030"] for r in results if r.get("dr_5y_030") is not None}
    pbo_wf_16 = cm.cscv_pbo(mat_wf, S=16)
    pbo_5y_16 = cm.cscv_pbo(mat_5y, S=16)

    rows_print = []
    for r in results:
        if "windows_030" not in r:
            continue
        wf = r["windows_030"]["WF_2326"]
        f5 = r["windows_030"]["FULL_5Y"]
        oos = r["windows_030"]["OOS_2526"]
        y26 = r["windows_030"]["Y2026"]
        rows_print.append({
            "variant_id": r["variant_id"],
            "n_5y": f5["n"], "n_wf": wf["n"], "miss": r["miss_rate_pct"],
            "wr_wf": wf["wr_pct"], "plr_wf": wf["plr"], "mloss_wf": wf["mean_loss_pct"], "le7_wf": wf["big_loss_rate_pct"],
            "nav_wf": wf["nav"], "mdd_wf": wf["mdd_pct"], "sh_wf": wf["sharpe"],
            "nav_5y": f5["nav"], "sh_5y": f5["sharpe"], "nav_2526": oos["nav"], "nav_26": y26["nav"],
            "pp_wf": r["paired_p_wf_030"],
        })
    df_sum = pd.DataFrame(rows_print).sort_values("sh_wf", ascending=False)
    print("\n=== PRY V2.1 AUTOPSY & CURE TESTS ===")
    print(df_sum.to_string(index=False))
    print("Autopsy P165:", json.dumps(autopsy["P165_pass435"], ensure_ascii=False))
    print("EW diag:", json.dumps(ew_diag, ensure_ascii=False))
    print(f"CSCV PBO (S=16): WF={pbo_wf_16['pbo']} | 5Y={pbo_5y_16['pbo']}")

    out_cache = {
        "coverage_5m": cov,
        "autopsy": autopsy,
        "ew_diag": ew_diag,
        "results": [{k: v for k, v in r.items() if not k.startswith("dr_")} for r in results],
        "drs_wf": mat_wf,
        "drs_5y": mat_5y,
        "pbo_wf_16": pbo_wf_16,
        "pbo_5y_16": pbo_5y_16,
        "summary_df": df_sum,
        "top_slots": slot_map,
    }
    with open(f"{cm.CACHE_DIR}/front3b_pry.pkl", "wb") as f:
        pickle.dump(out_cache, f)
    print(f"[Front3B DONE in {time.time()-t0:.1f}s] RSS={cm.rss_mb()} MB")


if __name__ == "__main__":
    main()
