#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD027 Wave 2A: Build weekly PIT master panel (~1,050+ factors across 7 orthogonal families)
and forward T+1 open -> T+h close targets (zero yfinance, zero lookahead).
Outputs:
  - output/china_policy_macro_rd027_20261125/wave2_factors/master_weekly_1000factors_pit.parquet
  - output/china_policy_macro_rd027_20261125/wave2_factors/factor_catalog.json
"""
import json
import os
import sys
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import rd027_common as cm
from factor_builders_f1_f4 import (
    build_f1_waterpool,
    build_f2_breadth_valuation,
    build_f3_cn_macro,
    build_f4_us_china_constraints,
)
from factor_builders_f5_f7 import (
    build_f5_meetings_events,
    build_f6_traffic_lights,
    build_f7_regime_interactions,
)

OUT_DIR = os.path.join(cm.ROOT, "output/china_policy_macro_rd027_20261125/wave2_factors")
os.makedirs(OUT_DIR, exist_ok=True)
OUT_PQ = os.path.join(OUT_DIR, "master_weekly_1000factors_pit.parquet")
OUT_CAT = os.path.join(OUT_DIR, "factor_catalog.json")


def build_forward_targets(panel: pd.DataFrame, wk_df: pd.DataFrame) -> pd.DataFrame:
    """Compute strictly T+1 open -> T+h close forward returns & drawdowns."""
    tgt = pd.DataFrame(index=wk_df.index)
    t_entries = wk_df["t_entry_idx"].to_numpy(dtype=int)

    def _ret(asset: str, h: int) -> np.ndarray:
        return np.array([cm.calc_fwd_return(panel, int(te), h, asset) for te in t_entries], dtype=float)

    def _mdd(asset: str, h: int) -> np.ndarray:
        return np.array([cm.calc_fwd_max_drawdown(panel, int(te), h, asset) for te in t_entries], dtype=float)

    # 8 Primary Targets (5 market/risk + 3 style spreads)
    tgt["tgt_csi300_fwd_60d"] = _ret("csi300", 60)
    tgt["tgt_csi300_fwd_120d"] = _ret("csi300", 120)
    tgt["tgt_csi300_fwd_250d"] = _ret("csi300", 250)
    tgt["tgt_ew_all_fwd_120d"] = _ret("ew", 120)
    tgt["tgt_csi300_fwd_60d_mdd"] = _mdd("csi300", 60)
    tgt["tgt_micro30_minus_300_120d"] = _ret("micro30", 120) - _ret("csi300", 120)
    tgt["tgt_div_minus_chinext_120d"] = _ret("csi_div", 120) - _ret("chinext", 120)
    tgt["tgt_tech_minus_300_120d"] = _ret("tech_board", 120) - _ret("csi300", 120)

    # Auxiliary horizons for CH5 & Jorda Local Projections (20d/60d/120d/250d)
    tgt["tgt_csi300_fwd_20d"] = _ret("csi300", 20)
    tgt["tgt_ew_all_fwd_20d"] = _ret("ew", 20)
    tgt["tgt_ew_all_fwd_60d"] = _ret("ew", 60)
    tgt["tgt_ew_all_fwd_250d"] = _ret("ew", 250)
    tgt["tgt_csi300_fwd_20d_mdd"] = _mdd("csi300", 20)
    tgt["tgt_csi300_fwd_120d_mdd"] = _mdd("csi300", 120)
    tgt["tgt_csi300_fwd_250d_mdd"] = _mdd("csi300", 250)
    tgt["tgt_micro30_minus_300_20d"] = _ret("micro30", 20) - _ret("csi300", 20)
    tgt["tgt_micro30_minus_300_60d"] = _ret("micro30", 60) - _ret("csi300", 60)
    tgt["tgt_micro30_minus_300_250d"] = _ret("micro30", 250) - _ret("csi300", 250)
    tgt["tgt_div_minus_chinext_20d"] = _ret("csi_div", 20) - _ret("chinext", 20)
    tgt["tgt_div_minus_chinext_60d"] = _ret("csi_div", 60) - _ret("chinext", 60)
    tgt["tgt_div_minus_chinext_250d"] = _ret("csi_div", 250) - _ret("chinext", 250)
    tgt["tgt_tech_minus_300_20d"] = _ret("tech_board", 20) - _ret("csi300", 20)
    tgt["tgt_tech_minus_300_60d"] = _ret("tech_board", 60) - _ret("csi300", 60)
    tgt["tgt_tech_minus_300_250d"] = _ret("tech_board", 250) - _ret("csi300", 250)
    return tgt


def main():
    print("[Wave2A-Build] Loading 5 data pillars & market panel...")
    panel_full, dates_full, date_to_idx_full = cm.load_market_panel()
    panel_full["date_ts"] = pd.to_datetime(panel_full["date"])

    wp_raw = pd.read_parquet(os.path.join(cm.OUT_PILLAR_DIR, "pillar1_waterpool_monthly.parquet"))
    bd_daily = pd.read_parquet(os.path.join(cm.OUT_PILLAR_DIR, "pillar1_market_breadth_daily.parquet"))
    mp_daily = pd.read_parquet(os.path.join(cm.OUT_PILLAR_DIR, "pillar4_macro_pain_daily_pit.parquet"))
    p2_raw = pd.read_parquet(os.path.join(cm.OUT_PILLAR_DIR, "pillar2_top_meetings_diff.parquet"))
    p3_raw = pd.read_parquet(os.path.join(cm.OUT_PILLAR_DIR, "pillar3_sector_traffic_lights.parquet"))
    me_raw = pd.read_parquet(cm.MASTER_PQ)

    # Weekly grid: last trading day of each W-FRI week in [2005-01-01, 2026-11-24]
    cal_05 = panel_full[(panel_full["date_ts"] >= "2005-01-01") & (panel_full["date_ts"] <= "2026-11-24")][["date_ts", "date"]].copy()
    cal_05["yw"] = cal_05["date_ts"].dt.to_period("W-FRI")
    wk_df = cal_05.groupby("yw", sort=True, as_index=False).agg(date=("date_ts", "max"), date_str=("date", "max"))
    wk_df["t_idx"] = wk_df["date_str"].map(date_to_idx_full).astype(int)
    wk_df["t_entry_idx"] = np.where(wk_df["t_idx"] + 1 < len(dates_full), wk_df["t_idx"] + 1, -1)
    wk_df["entry_date"] = np.where(wk_df["t_entry_idx"] >= 0, [dates_full[i] if i >= 0 else None for i in wk_df["t_entry_idx"]], None)
    wk_df = wk_df.drop(columns=["yw"]).reset_index(drop=True)
    print(f"[Wave2A-Build] Weekly grid: {len(wk_df)} weeks ({wk_df['date_str'].iloc[0]} ~ {wk_df['date_str'].iloc[-1]})")

    tgt_df = build_forward_targets(panel_full, wk_df)

    print("[Wave2A-Build] Building F1..F6 orthogonal factor families...")
    f1_df, m1 = build_f1_waterpool(wk_df, wp_raw, bd_daily, cal_05["date_ts"])
    f2_df, m2 = build_f2_breadth_valuation(wk_df, bd_daily, panel_full)
    f3_df, m3 = build_f3_cn_macro(wk_df, mp_daily)
    f4_df, m4 = build_f4_us_china_constraints(wk_df, mp_daily)
    f5_df, m5 = build_f5_meetings_events(wk_df, p2_raw, me_raw, panel_full)
    f6_df, m6 = build_f6_traffic_lights(wk_df, p3_raw)

    df_f1_f6 = pd.concat([f1_df, f2_df, f3_df, f4_df, f5_df, f6_df], axis=1)
    f7_df, gate_df, m7 = build_f7_regime_interactions(df_f1_f6)

    all_meta = m1 + m2 + m3 + m4 + m5 + m6 + m7
    all_factors_df = pd.concat([df_f1_f6, f7_df], axis=1)

    # Filter out degenerate / constant / near-empty factors
    keep_names = []
    dropped = []
    catalog = {}
    dates_s = wk_df["date_str"]
    n_tot = len(wk_df)

    for info in all_meta:
        fn = info["factor"]
        s = all_factors_df[fn].replace([np.inf, -np.inf], np.nan)
        all_factors_df[fn] = s
        fv = s.first_valid_index()
        if fv is None:
            dropped.append((fn, "all_nan"))
            continue
        valid_cnt = int(s.notna().sum())
        sub = s.loc[fv:]
        if valid_cnt < 40 or float(sub.std(ddof=1)) < 1e-12 or int(sub.nunique(dropna=True)) < 2:
            dropped.append((fn, f"degenerate(valid={valid_cnt},std={sub.std()})"))
            continue
        eff_start = str(dates_s.loc[fv])
        miss_after = round(float(sub.isna().mean() * 100.0), 3)
        lv = s.iloc[-1]
        keep_names.append(fn)
        catalog[fn] = {
            "family": info["family"],
            "formula": info["formula"],
            "source": info["source"],
            "effective_start_date": eff_start,
            "valid_count": valid_cnt,
            "total_weeks": n_tot,
            "missing_rate_after_start_pct": miss_after,
            "latest_date": str(dates_s.iloc[-1]),
            "latest_value_20261124": None if pd.isna(lv) else round(float(lv), 6),
        }

    master_out = pd.concat([wk_df, tgt_df, gate_df, all_factors_df[keep_names]], axis=1)
    master_out.to_parquet(OUT_PQ, index=False)

    fam_counts = pd.Series([catalog[k]["family"] for k in keep_names]).value_counts().sort_index().to_dict()
    gate_rates = {c: round(float(gate_df[c].mean() * 100.0), 2) for c in gate_df.columns}

    cat_payload = {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "n_weeks": n_tot,
        "date_range": [str(dates_s.iloc[0]), str(dates_s.iloc[-1])],
        "n_factors_total": len(keep_names),
        "n_dropped": len(dropped),
        "dropped_samples": dropped[:20],
        "family_counts": fam_counts,
        "gate_hit_rates_pct": gate_rates,
        "primary_targets": [
            "tgt_csi300_fwd_60d", "tgt_csi300_fwd_120d", "tgt_csi300_fwd_250d",
            "tgt_ew_all_fwd_120d", "tgt_csi300_fwd_60d_mdd",
            "tgt_micro30_minus_300_120d", "tgt_div_minus_chinext_120d", "tgt_tech_minus_300_120d",
        ],
        "factors": catalog,
    }
    with open(OUT_CAT, "w", encoding="utf-8") as f:
        json.dump(cat_payload, f, ensure_ascii=False, indent=2)

    print(f"[Wave2A-Build] Saved {OUT_PQ}: shape={master_out.shape}")
    print(f"[Wave2A-Build] Valid factors: {len(keep_names)}, Dropped: {len(dropped)}")
    print(f"[Wave2A-Build] Family breakdown: {fam_counts}")
    print(f"[Wave2A-Build] Gate hit rates (%): {gate_rates}")


if __name__ == "__main__":
    main()
