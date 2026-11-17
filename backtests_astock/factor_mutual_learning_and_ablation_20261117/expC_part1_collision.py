#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
expC_handoff_exit_entry_duality.py
实证检验：
1. 一进二卖点 <-> 二进三买点 (Day 3) 与 二进三/一进二卖点 <-> 三进四买点 (Day 4) 的历史真实撞单与盘口时刻互斥；
2. 同一因子在交接节点上「前手卖点正向指标(越早卖越少亏/多赚) == 后手买点反向指标(买进去必亏)」的对偶定律；
3. 买卖点双向互锁改造 (IS 2021-2023 -> OOS 2024-2026) 实测净值与回撤对比。
严守 D12 (零 yfinance) 与 PIT 只读约束。
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio")
OUT_DIR = ROOT / "backtests_astock/factor_mutual_learning_and_ablation_20261117"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 1. Load canonical ledgers & PIT candidate tables
l_12 = pd.read_csv(ROOT / "backtests_astock/clean_rebacktest_20261116/partB_1to2/ledger_base_1to2_v18.csv")
l_23 = pd.read_csv(ROOT / "backtests_astock/clean_2to3_v10_20261117/ledger_base_2to3_v10_std90.csv")
c_23_raw90 = pd.read_csv(ROOT / "backtests_astock/clean_2to3_v10_20261117/candidates_2to3_v10_all_raw90.csv")
l_34 = pd.read_csv(ROOT / "backtests_astock/clean_rebacktest_20261116/partA_high_3to4/ledger_base_3to4_v34.csv")

c23 = pd.read_parquet(ROOT / "backtests_astock/clean_2to3_v10_20261117/data_pit/clean_2to3_5y.parquet")
fa = pd.read_parquet(ROOT / "backtests_astock/clean_2to3_v10_20261117/data_pit/factors_a.parquet")
fb = pd.read_parquet(ROOT / "backtests_astock/clean_2to3_v10_20261117/data_pit/factors_b.parquet")
fc = pd.read_parquet(ROOT / "backtests_astock/clean_2to3_v10_20261117/data_pit/factors_c.parquet")
c34 = pd.read_parquet(ROOT / "backtests_astock2/data_5y/cand_3to4_enriched54.parquet")

for df in (l_12, l_23, c_23_raw90, l_34, c23, fa, fb, fc, c34):
    if "code" in df.columns:
        df["c6"] = df["code"].astype(int).astype(str).str.zfill(6)

# 三行硬校验: 单位除数 + 时间锚点 + 行列断言
assert c23["open_pct"].abs().median() < 0.20, "c23 open_pct unit must be decimal"
assert c34["open_pct"].abs().median() < 20.0, "c34 open_pct check"
assert len(c23) > 10000 and len(c34) > 2500 and c23["buy_date"].max() >= "2026-11-01"

# Load 5m bars needed for Day3 (2to3) & Day4 (3to4) 10:30 VWAP check
p5m = pd.read_parquet(
    ROOT / "data/all_strategies_5m_complete_pit.parquet",
    columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"]
)
# Compute 10:30 close, 10:30 cum VWAP, 10:35 open, 15:00 close, first time hitting 10% ZT or trigger
p5m_am = p5m[p5m["hhmm_int"] <= 1030]
g_1030 = p5m_am.groupby(["c6", "date"], sort=False).agg(
    vol_1030=("volume", "sum"),
    amt_1030=("amount", "sum"),
    px_1030=("close", "last"),
    hi_1030=("high", "max"),
).reset_index()
g_1030["vwap_1030"] = np.where(g_1030["vol_1030"] > 0, g_1030["amt_1030"] / g_1030["vol_1030"], g_1030["px_1030"])

p5m_1035 = p5m[p5m["hhmm_int"] == 1035][["c6", "date", "open", "close"]].rename(
    columns={"open": "px_1035_open", "close": "px_1035_close"}
)
p5m_eod = p5m.groupby(["c6", "date"], sort=False).agg(
    px_1500=("close", "last"),
    px_0935=("open", "first"),
    hi_all=("high", "max"),
).reset_index()

m5 = g_1030.merge(p5m_1035, on=["c6", "date"], how="left").merge(p5m_eod, on=["c6", "date"], how="left")
m5_map = m5.set_index(["c6", "date"])

# --- PART 1: Direct Ledger Handoff Collisions ---
# 1A: 1to2 sealed_2b entering Day 3 vs 2to3 buying on Day 3
l12_2b = l_12[l_12["sealed_2b"] == 1].copy()
# Find next trading day after 1to2 buy_date using c23 (code, d2_actual_date or sig_date == l12 buy_date)
d2_to_d3 = c23[["c6", "sig_date", "buy_date", "open_pct", "close_pct", "sealed_3b"]].rename(
    columns={"sig_date": "d2_date", "buy_date": "d3_date"}
)
l12_d3 = l12_2b.merge(d2_to_d3, left_on=["c6", "buy_date"], right_on=["c6", "d2_date"], how="left")
l12_d3["sold_on_d3"] = l12_d3["exit_date"] == l12_d3["d3_date"]
l12_d3["in_23_raw90"] = l12_d3.set_index(["c6", "d3_date"]).index.isin(c_23_raw90.set_index(["c6", "buy_date"]).index)
l12_d3["in_23_ledger"] = l12_d3.set_index(["c6", "d3_date"]).index.isin(l_23.set_index(["c6", "buy_date"]).index)

# 1B: 1to2 or 2to3 holding 3-board entering Day 4 vs 3to4 buying on Day 4
d3_to_d4 = c34[["c6", "sig_date", "buy_date", "open_pct", "pct", "is_zt_today", "score_v34"]].rename(
    columns={"sig_date": "d3_date", "buy_date": "d4_date", "open_pct": "d4_open_pct", "pct": "d4_close_pct"}
)
l23_3b = l_23[l_23["sealed_3b"] == True].merge(d3_to_d4, left_on=["c6", "buy_date"], right_on=["c6", "d3_date"], how="left")
l23_3b["sold_on_d4"] = l23_3b["exit_date"] == l23_3b["d4_date"]
l23_3b["in_34_ledger"] = l23_3b.set_index(["c6", "d4_date"]).index.isin(l_34.set_index(["c6", "buy_date"]).index)

l12_3b = l12_d3[l12_d3["exit_date"] > l12_d3["d3_date"]].merge(d3_to_d4, on=["c6", "d3_date"], how="left")
l12_3b["sold_on_d4"] = l12_3b["exit_date"] == l12_3b["d4_date"]
l12_3b["in_34_ledger"] = l12_3b.set_index(["c6", "d4_date"]).index.isin(l_34.set_index(["c6", "buy_date"]).index)

# Check 3to4 ledger (88 trades): how many bought AFTER 10:30, and how many were below VWAP at 10:30 (i.e. 1to2's exact 10:30 sell trigger!)
l34_m = l_34.merge(m5, left_on=["c6", "buy_date"], right_on=["c6", "date"], how="left")
l34_m["below_vwap_1030"] = l34_m["px_1030"] < l34_m["vwap_1030"] - 1e-6
l34_m["bought_after_1030"] = l34_m["buy_hhmm"] > 1030
l34_m["knife_catch_1030"] = l34_m["bought_after_1030"] & l34_m["below_vwap_1030"]

# Check 2to3 ledger (77 trades): at Day 3 10:30, if 1to2's rule says SELL (unsealed & px_1030 < vwap_1030) vs HOLD
l23_m = l_23.merge(m5, left_on=["c6", "buy_date"], right_on=["c6", "date"], how="left")
l23_m = l23_m.merge(c23[["c6", "buy_date", "prev_close", "close_pct"]], on=["c6", "buy_date"], how="left")
l23_m["zt_px_d3"] = (l23_m["prev_close"] * 1.10 + 1e-6).round(2)
l23_m["sealed_at_1030"] = l23_m["px_1030"] >= l23_m["zt_px_d3"] - 0.005
l23_m["trig_1to2_sell_1030"] = (~l23_m["sealed_at_1030"]) & (l23_m["px_1030"] < l23_m["vwap_1030"] - 1e-6)

print("=== 1. DIRECT LEDGER COLLISIONS ===")
print(f"1to2 sealed_2b count={len(l12_d3)}, sold_on_d3={l12_d3['sold_on_d3'].sum()}, overlap_23_raw90={l12_d3['in_23_raw90'].sum()}, overlap_23_ledger={l12_d3['in_23_ledger'].sum()}")
if l12_d3["in_23_raw90"].any():
    print(l12_d3[l12_d3["in_23_raw90"]][["c6", "name", "d3_date", "exit_date", "exit_hhmm", "net_ret", "sold_on_d3", "in_23_ledger"]])
print(f"2to3 sealed_3b count={len(l23_3b)}, sold_on_d4={l23_3b['sold_on_d4'].sum()}, overlap_34_ledger={l23_3b['in_34_ledger'].sum()}")
print(f"1to2 rode_to_d4 count={len(l12_3b)}, sold_on_d4={l12_3b['sold_on_d4'].sum()}, overlap_34_ledger={l12_3b['in_34_ledger'].sum()}")
if l12_3b["in_34_ledger"].any():
    print("1to2 D4 vs 3to4 ledger:", l12_3b[l12_3b["in_34_ledger"]][["c6", "name", "d4_date", "exit_date", "exit_hhmm", "tag", "sold_on_d4"]])

print("\n=== 2. 3TO4 BUYING AT/AFTER 10:30 VS 1TO2 10:30 SELL SIGNAL ===")
for label, sub in [
    ("3to4 ALL (88)", l34_m),
    ("3to4 buy <= 10:30", l34_m[~l34_m["bought_after_1030"]]),
    ("3to4 buy > 10:30 (all)", l34_m[l34_m["bought_after_1030"]]),
    ("3to4 buy > 10:30 & 10:30<VWAP (1to2刚卖三进四接盘!)", l34_m[l34_m["knife_catch_1030"]]),
    ("3to4 buy <= 10:00", l34_m[l34_m["buy_hhmm"] <= 1000]),
]:
    wr = (sub["net_ret"] > 0).mean() * 100 if len(sub) else 0
    mn = sub["net_ret"].mean() * 100 if len(sub) else 0
    nav = float(np.prod(1.0 + sub["net_ret"].values)) if len(sub) else 1.0
    print(f"  {label:46s}: n={len(sub):2d} WR={wr:5.1f}% mean={mn:+6.2f}% prod_nav={nav:7.2f}x")
if l34_m["bought_after_1030"].any():
    print("  3to4 bought_after_1030 detail:\n", l34_m[l34_m["bought_after_1030"]][["c6", "name", "buy_date", "buy_hhmm", "below_vwap_1030", "net_ret"]].to_string(index=False))

print("\n=== 3. 2TO3 (77 TRADES) SPLIT BY 1TO2'S 10:30 SELL SIGNAL ON DAY 3 ===")
l23_5m_ok = l23_m[l23_m["px_1030"].notna()].copy()
for label, sub in [
    ("2to3 w/ 5m all", l23_5m_ok),
    ("Day3 10:30 一进二锁仓不卖 (封板或>=VWAP)", l23_5m_ok[~l23_5m_ok["trig_1to2_sell_1030"]]),
    ("Day3 10:30 触发一进二破均线必卖 (<VWAP)", l23_5m_ok[l23_5m_ok["trig_1to2_sell_1030"]]),
]:
    wr = (sub["net_ret"] > 0).mean() * 100 if len(sub) else 0
    mn = sub["net_ret"].mean() * 100 if len(sub) else 0
    print(f"  {label:46s}: n={len(sub):2d} WR={wr:5.1f}% mean={mn:+6.2f}%")