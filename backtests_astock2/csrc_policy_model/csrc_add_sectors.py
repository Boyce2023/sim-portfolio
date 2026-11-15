#!/usr/bin/env python3
"""Add CSI/SZSE sector indices (Semis, AI/TMT, Defense, Pharma, SOE, Real Estate) via Tencent API."""
import os
import pandas as pd
import akshare as ak

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/backtest"
panel_path = os.path.join(OUT_DIR, "daily_market_panel.parquet")
panel = pd.read_parquet(panel_path)

SECTOR_INDICES = {
    "sh000933": "pharma",        # 中证医药 (2009-2026)
    "sz399974": "soe_reform",    # 国企改革/央企代表
    "sh000926": "central_soe",   # 央企100 (2009-2026)
    "sz399967": "defense",       # 中证军工 (2014-2026)
    "sz399971": "media_ai",      # 中证传媒/AI应用
    "sh000993": "tmt_info",      # 全指信息/TMT硬科技 (2011-2026)
    "sh000989": "cons_opt",      # 全指可选消费 (2011-2026)
    "sz399393": "real_estate",   # 国证地产
    "sh512480": "semi_etf",      # 半导体ETF (2019-2026)
}

added = 0
for sym, pref in SECTOR_INDICES.items():
    try:
        df = ak.stock_zh_index_daily_tx(symbol=sym)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.sort_values("date").drop_duplicates("date")
        df = df[df["date"] >= "2000-01-01"].copy()
        df[f"{pref}_open"] = df["open"].astype(float)
        df[f"{pref}_close"] = df["close"].astype(float)
        df[f"{pref}_prev_close"] = df[f"{pref}_close"].shift(1)
        df[f"{pref}_cc_ret"] = df[f"{pref}_close"] / df[f"{pref}_prev_close"] - 1.0
        df[f"{pref}_gap_ret"] = df[f"{pref}_open"] / df[f"{pref}_prev_close"] - 1.0
        df[f"{pref}_oc_ret"] = df[f"{pref}_close"] / df[f"{pref}_open"] - 1.0
        keep = ["date", f"{pref}_open", f"{pref}_close", f"{pref}_cc_ret", f"{pref}_gap_ret", f"{pref}_oc_ret"]
        panel = panel.merge(df[keep], on="date", how="left")
        added += 1
        print(f"Added {sym} ({pref}): {len(df)} rows [{df['date'].min()} -> {df['date'].max()}]")
    except Exception as e:
        print(f"Skip {sym}: {e}")

# Also merge sub2_daily_regime (ex_cnt5 = rolling 5d exchange surveillance count, brk_nuke, etc.)
reg_p = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113/sub2_daily_regime.parquet"
if os.path.exists(reg_p):
    reg = pd.read_parquet(reg_p)
    reg["date"] = reg["date"].astype(str).str[:10]
    reg_cols = ["date", "ex_cnt5", "brk_nuke", "brk_avg_pct", "n_b4p"]
    reg_cols = [c for c in reg_cols if c in reg.columns]
    panel = panel.merge(reg[reg_cols].drop_duplicates("date"), on="date", how="left")
    print(f"Merged sub2_daily_regime: {reg_cols}")

panel.to_parquet(panel_path, index=False)
print(f"DONE: Updated panel has {len(panel)} rows, {len(panel.columns)} columns (added {added} sector series)")
