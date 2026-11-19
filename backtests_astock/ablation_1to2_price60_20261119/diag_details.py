#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import sys, numpy as np, pandas as pd
ABL_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/ablation_1to2_price60_20261119"
UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, ABL_DIR)
sys.path.insert(0, UPG_DIR)
import upgrade_1to2_pit as u
from pit_signal_base import build_base_ctx_pit, apply_variant_v19

base_ctx = build_base_ctx_pit(u.DATA_END_DT)
c_b = apply_variant_v19(base_ctx, 60.0, 0.0)
c_n = apply_variant_v19(base_ctx, None, 0.0)
hb, hn = c_b["hist_fb"], c_n["hist_fb"]
mb = c_b["mask_v19"] & (hb["d2_dt"] >= u.CANON_5Y_START) & (hb["d2_dt"] <= u.DATA_END_DT)
mn = c_n["mask_v19"] & (hn["d2_dt"] >= u.CANON_5Y_START) & (hn["d2_dt"] <= u.DATA_END_DT)

kb = set(zip(hb.loc[mb, "d2_dt"], hb.loc[mb, "c6"]))
kn = set(zip(hn.loc[mn, "d2_dt"], hn.loc[mn, "c6"]))
print("=== 1. NoCap 导致原本 <=60 的掉出 pass 池的标的 ===")
for dt, c6 in sorted(kb - kn):
    rb = hb[(hb["d2_dt"] == dt) & (hb["c6"] == c6)].iloc[0]
    rn = hn[(hn["d2_dt"] == dt) & (hn["c6"] == c6)].iloc[0]
    print(
        f"  {dt} {c6} {rb['name']} | Base: sc={rb['score_active']:.1f} tbrk={rb['true_buy_rk']} mkt_rk={rb['buyable_mkt_open_rk']} "
        f"| NoCap: sc={rn['score_active']:.1f} tbrk={rn['true_buy_rk']} mkt_rk={rn['buyable_mkt_open_rk']}"
    )
    day_gt60 = hn[(hn["d2_dt"] == dt) & (hn["close"] > 60.0) & (hn["gate_no_price"])]
    for _, x in day_gt60.iterrows():
        print(
            f"    同日gt60干扰源: {x['c6']} {x['name']} close={x['close']:.2f} plate={x['plate']} "
            f"o_pct={x['d2_o_pct']*100:+.2f}% sc={x['score_active']:.1f} tbrk={x['true_buy_rk']} mkt_rk={x['buyable_mkt_open_rk']}"
        )

print("\n=== 2. 4笔 NoCap 新增 gt60 成交的精确 5m 时序 ===")
u.FEE_RATE = 0.0030
sim = u.make_trade_sim(c_n, use_m1_d3_exempt=True)
for dt, c6 in [("2022-12-12", "002932"), ("2026-01-26", "003041"), ("2026-06-26", "603459"), ("2026-06-30", "003043")]:
    row = hn[(hn["d2_dt"] == dt) & (hn["c6"] == c6)].iloc[0].to_dict()
    tr = sim(row)
    has_d2_5m = (c6, dt) in c_n["bars_5m_map"]
    has_d3_5m = (c6, tr["exit_date"]) in c_n["bars_5m_map"]
    print(f"  {dt} {c6} {tr['name']}: buy={tr['buy_price']}@{tr['buy_hhmm']} exit={tr['exit_price']}@{tr['exit_date']} {tr['exit_hhmm']} tag={tr['tag']} ret={tr['net_ret']:+.4f} (5m_d2={has_d2_5m}, 5m_d3={has_d3_5m})")

print("\n=== 3. 全市场底池(无V19规则，仅 gate_no_price & 可买不核冻) 按股价分档统计 ===")
sub = hn[(hn["d2_dt"] >= u.CANON_5Y_START) & (hn["d2_dt"] <= u.DATA_END_DT) & hn["is_buyable_open"] & (~hn["nuclear_halt"]) & (~hn["promo_freeze"])].copy()
sub["oc"] = sub["d2_close"] / sub["d2_open"] - 1.0
for lbl, cond in [
    ("5Y close<=60", sub["close"] <= 60),
    ("5Y 60<close<=80", (sub["close"] > 60) & (sub["close"] <= 80)),
    ("5Y 80<close<=100", (sub["close"] > 80) & (sub["close"] <= 100)),
    ("5Y close>100", sub["close"] > 100),
    ("5Y close>60 ALL", sub["close"] > 60),
    ("25-26 close<=60", (sub["close"] <= 60) & (sub["d2_dt"] >= "2025-01-01")),
    ("25-26 close>60 ALL", (sub["close"] > 60) & (sub["d2_dt"] >= "2025-01-01")),
]:
    g = sub[cond]
    print(f"  {lbl:<20}: n={len(g):>5}, 2b_rate={g['d2_is_zt'].mean()*100:5.2f}%, o_pct={g['d2_o_pct'].mean()*100:+5.2f}%, oc_ret={g['oc'].mean()*100:+5.2f}%, touch_zt={(g['d2_high']>=g['d2_zt_p']-0.01).mean()*100:5.2f}%")

big_gt60 = hn[(hn["d2_dt"] >= "2025-01-01") & (hn["d2_dt"] <= u.DATA_END_DT) & (hn["close"] > 60) & (hn["mcap"] > 220) & (hn["d2_open"] > 0) & (~hn["d2_is_yizi"])].copy()
big_gt60["oc"] = big_gt60["d2_close"] / big_gt60["d2_open"] - 1.0
print(f"  {'25-26 mcap>220&c>60':<20}: n={len(big_gt60):>5}, 2b_rate={big_gt60['d2_is_zt'].mean()*100:5.2f}%, o_pct={big_gt60['d2_o_pct'].mean()*100:+5.2f}%, oc_ret={big_gt60['oc'].mean()*100:+5.2f}%")
