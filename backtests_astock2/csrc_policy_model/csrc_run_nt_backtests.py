#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Evaluate F145-F156 (Pure National Team 21-ETF Entry, Exit & Tier Structure) with D15 anti-fraud:
- Zero-lookahead entry at first tradable open after observation/disclosure
- Single-slot non-overlapping rotation & IS (2012-2023.10) vs OOS (2023.10-2026.11) vs 1Y
- CSI1000/Micro30 vs CSI300 style spread + Short-term limit-up/down & v18/v51 ecology overlay
"""
import json, os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from csrc_factors_part3_nt import get_nt_factor_specs
from csrc_nt_eval_lib import build_cum_levels, forward_ret, stats_arr, single_slot_stats, eval_target_series

BASE = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
BT_DIR = os.path.join(BASE, "backtest")
NT_DIR = os.path.join(BASE, "national_team")


def align_events(ev_df: pd.DataFrame, p: pd.DataFrame) -> pd.DataFrame:
    dates = p["date"].tolist()
    d2i = {d: i for i, d in enumerate(dates)}
    rows = []
    for _, r in ev_df.iterrows():
        dt, slot = r["event_date"], str(r["slot"]).upper()
        if dt in d2i:
            i = d2i[dt]
            t_en = i if slot == "BMO" else i + 1
            t_pr = i - 1 if slot in ("BMO", "INTRADAY") else i
        else:
            later = [k for k, d in enumerate(dates) if d > dt]
            t_en = later[0] if later else -1
            t_pr = (t_en - 1) if t_en > 0 else -1
        if t_en < 0 or t_en >= len(p) or t_pr < 0:
            continue
        pr = p.iloc[t_pr]
        en = p.iloc[t_en]
        nt_5d = float(pr.get("etf_nt_weighted_flow_5d_yi", 0.0) or 0.0)
        d_rec = dict(r)
        d_rec.update({
            "t_entry_idx": t_en,
            "tradable_date": dates[t_en],
            "prior_dd_60d": float(pr.get("bench_dd_60d", np.nan)),
            "prior_nt_5d_yi": nt_5d,
            "entry_gap_bench": float(en.get("bench_gap_ret", np.nan)),
        })
        rows.append(d_rec)
    return pd.DataFrame(rows)


def run_all():
    panel_raw = pd.read_parquet(os.path.join(BT_DIR, "daily_market_panel.parquet"))
    p = build_cum_levels(panel_raw)
    ev_raw = pd.read_parquet(os.path.join(NT_DIR, "nt_official_events.parquet"))
    ev = align_events(ev_raw, p)

    # Unconditional baselines (2012-2026 ETF era for panel factors, 2008-2026 for events)
    p12 = p[p["date"] >= "2012-01-05"].copy()
    uncond_bench = {h: float(np.nanmean([forward_ret(p, i, "bench", h) for i in p12.index if i + h < len(p)])) for h in [1, 5, 20, 60]}
    base_zt = float(p12["zt_cnt"].mean())
    base_dt = float(p12["dt_cnt"].mean())
    base_hr = float(p12["high_relay_oc_ret"].mean()) if "high_relay_oc_ret" in p12 else np.nan
    base_brk = float(p12["broken_rate"].mean()) if "broken_rate" in p12 else np.nan
    base_v18 = float(p12["v18_1to2_ret"].mean()) if "v18_1to2_ret" in p12 else np.nan
    base_v51 = float(p12["v51_high_dip_ret"].mean()) if "v51_high_dip_ret" in p12 else np.nan

    specs = get_nt_factor_specs()
    rows_out = []
    for sp in specs:
        target, h_main, exp_dir = sp["target"], sp["horizon"], sp["exp_dir"]
        if sp["src_type"] == "panel":
            m = sp["mask_fn"](p)
            obs_idx = p.index[m].to_numpy()
            en_idx = np.array([i + 1 for i in obs_idx if i + 1 < len(p)], dtype=int)
            en_dates = p.loc[en_idx, "date"].tolist()
            gaps = p.loc[en_idx, "bench_gap_ret"].to_numpy(dtype=float)
        else:
            sub_e = ev[sp["mask_fn"](ev)].copy()
            idx_col = "t_confirm_idx" if sp.get("use_confirm_entry") else "t_entry_idx"
            sub_e = sub_e[sub_e[idx_col] >= 0].sort_values(idx_col).drop_duplicates(idx_col)
            en_idx = sub_e[idx_col].to_numpy(dtype=int)
            en_dates = p.loc[en_idx, "date"].tolist()
            gaps = p.loc[en_idx, "bench_gap_ret"].to_numpy(dtype=float)

        rec = {
            "factor_id": sp["id"], "family": sp["family"], "factor_name": sp["name"],
            "target_asset": target, "primary_horizon_days": h_main, "expected_dir": exp_dir,
            "n_events_dedup": len(en_idx),
            "avg_entry_gap_pct": float(np.nanmean(gaps) * 100) if len(gaps) else np.nan,
        }
        # Multi-horizon target returns + benchmark excess + style spreads
        for h in [1, 5, 20, 60]:
            arr_t = eval_target_series(p, en_idx, target, h, uncond_bench)
            st = stats_arr(arr_t, exp_dir)
            rec[f"ret_{h}d_pct"] = st["mean"] * 100 if pd.notna(st["mean"]) else np.nan
            rec[f"win_{h}d_pct"] = st["win_rate"] * 100 if pd.notna(st["win_rate"]) else np.nan
            arr_b = eval_target_series(p, en_idx, "bench", h, uncond_bench)
            rec[f"bench_{h}d_pct"] = float(np.nanmean(arr_b) * 100) if len(arr_b) else np.nan
            rec[f"excess_{h}d_pct"] = (float(np.nanmean(arr_b)) - uncond_bench[h]) * 100 if (target == "bench" and len(arr_b)) else rec[f"ret_{h}d_pct"]
            sp_1000 = eval_target_series(p, en_idx, "csi1000_vs_csi300", h, uncond_bench)
            sp_mic = eval_target_series(p, en_idx, "micro30_vs_csi300", h, uncond_bench)
            rec[f"sp1000_{h}d_pct"] = float(np.nanmean(sp_1000) * 100) if np.isfinite(sp_1000).any() else np.nan
            rec[f"spmicro_{h}d_pct"] = float(np.nanmean(sp_mic) * 100) if np.isfinite(sp_mic).any() else np.nan

        # Primary horizon full + slot + IS/OOS/1Y
        arr_m = eval_target_series(p, en_idx, target, h_main, uncond_bench)
        st_m = stats_arr(arr_m, exp_dir)
        sl_m = single_slot_stats(en_idx, arr_m, h_main, exp_dir)
        d_ser = pd.Series(en_dates)
        st_is = stats_arr(arr_m[(d_ser < "2023-10-11").to_numpy()], exp_dir)
        st_oos = stats_arr(arr_m[(d_ser >= "2023-10-11").to_numpy()], exp_dir)
        st_1y = stats_arr(arr_m[(d_ser >= "2025-11-18").to_numpy()], exp_dir)

        # Short-term ecology over [entry .. entry+4]
        zt5 = [p["zt_cnt"].iloc[i:min(len(p), i + 5)].mean() for i in en_idx] if len(en_idx) else []
        dt5 = [p["dt_cnt"].iloc[i:min(len(p), i + 5)].mean() for i in en_idx] if len(en_idx) else []
        hr5 = [p["high_relay_oc_ret"].iloc[i:min(len(p), i + 5)].mean() for i in en_idx] if ("high_relay_oc_ret" in p.columns and len(en_idx)) else []
        brk5 = [p["broken_rate"].iloc[i:min(len(p), i + 5)].mean() for i in en_idx] if ("broken_rate" in p.columns and len(en_idx)) else []
        v18_5 = [p["v18_1to2_ret"].iloc[i:min(len(p), i + 5)].mean() for i in en_idx] if ("v18_1to2_ret" in p.columns and len(en_idx)) else []
        v51_5 = [p["v51_high_dip_ret"].iloc[i:min(len(p), i + 5)].mean() for i in en_idx] if ("v51_high_dip_ret" in p.columns and len(en_idx)) else []

        rec.update({
            "main_n": st_m["n"], "main_mean_pct": st_m["mean"] * 100 if pd.notna(st_m["mean"]) else np.nan,
            "main_median_pct": st_m["median"] * 100 if pd.notna(st_m["median"]) else np.nan,
            "main_win_pct": st_m["win_rate"] * 100 if pd.notna(st_m["win_rate"]) else np.nan,
            "main_payoff": st_m["payoff"], "main_t_stat": st_m["t_stat"], "main_p_val": st_m["p_val"],
            "slot_n": sl_m["n"], "slot_mean_pct": sl_m["mean"] * 100 if pd.notna(sl_m["mean"]) else np.nan,
            "slot_win_pct": sl_m["win_rate"] * 100 if pd.notna(sl_m["win_rate"]) else np.nan,
            "slot_compound_pct": sl_m["compound_ret"] * 100 if pd.notna(sl_m["compound_ret"]) else np.nan,
            "is_n": st_is["n"], "is_mean_pct": st_is["mean"] * 100 if pd.notna(st_is["mean"]) else np.nan,
            "oos_n": st_oos["n"], "oos_mean_pct": st_oos["mean"] * 100 if pd.notna(st_oos["mean"]) else np.nan,
            "oos_win_pct": st_oos["win_rate"] * 100 if pd.notna(st_oos["win_rate"]) else np.nan,
            "p1y_n": st_1y["n"], "p1y_mean_pct": st_1y["mean"] * 100 if pd.notna(st_1y["mean"]) else np.nan,
            "p1y_win_pct": st_1y["win_rate"] * 100 if pd.notna(st_1y["win_rate"]) else np.nan,
            "fwd5_zt_cnt": float(np.nanmean(zt5)) if zt5 else np.nan,
            "fwd5_dt_cnt": float(np.nanmean(dt5)) if dt5 else np.nan,
            "fwd5_high_relay_pct": float(np.nanmean(hr5) * 100) if hr5 else np.nan,
            "fwd5_broken_pct": float(np.nanmean(brk5) * 100) if brk5 else np.nan,
            "fwd5_v18_pct": float(np.nanmean(v18_5) * 100) if v18_5 else np.nan,
            "fwd5_v51_pct": float(np.nanmean(v51_5) * 100) if v51_5 else np.nan,
        })
        # Objective verdict
        dr = (rec["main_mean_pct"] or 0.0) * exp_dir
        wr = rec["main_win_pct"] or 0.0
        n_ev = st_m["n"]
        if (n_ev >= 6 and dr >= 1.2 and wr >= 55.0) or (n_ev >= 4 and dr >= 2.5 and wr >= 65.0):
            rec["verdict"] = "有效核心因子"
        elif n_ev >= 5 and dr >= 0.4 and wr >= 52.0:
            rec["verdict"] = "条件或弱有效因子"
        else:
            rec["verdict"] = "已证伪无效或陷阱"
        rows_out.append(rec)

    res_df = pd.DataFrame(rows_out)
    res_df.to_csv(os.path.join(NT_DIR, "nt_12_pure_ledger.csv"), index=False, encoding="utf-8-sig")

    # Merge seamlessly into factors_156_full_ledger.csv
    f144 = pd.read_csv(os.path.join(BT_DIR, "factors_144_full_ledger.csv"))
    f156 = pd.concat([f144, res_df.reindex(columns=f144.columns)], ignore_index=True)
    f156.to_csv(os.path.join(BT_DIR, "factors_156_full_ledger.csv"), index=False, encoding="utf-8-sig")

    # Save baseline benchmarks
    meta = {
        "uncond_bench_pct": {str(k): round(v * 100, 3) for k, v in uncond_bench.items()},
        "ecology_baseline": {
            "zt_cnt": round(base_zt, 1), "dt_cnt": round(base_dt, 1),
            "high_relay_pct": round(base_hr * 100, 3) if pd.notna(base_hr) else None,
            "broken_pct": round(base_brk * 100, 1) if pd.notna(base_brk) else None,
        },
    }
    json.dump(meta, open(os.path.join(NT_DIR, "nt_baselines.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(res_df[["factor_id", "main_n", "main_mean_pct", "main_win_pct", "slot_mean_pct", "excess_20d_pct", "oos_mean_pct", "sp1000_5d_pct", "sp1000_20d_pct", "verdict"]].round(2).to_string(index=False))


if __name__ == "__main__":
    run_all()
