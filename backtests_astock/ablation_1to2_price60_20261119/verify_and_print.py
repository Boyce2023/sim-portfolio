#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import json, sys, numpy as np, pandas as pd
ABL_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/ablation_1to2_price60_20261119"
UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, ABL_DIR)
sys.path.insert(0, UPG_DIR)
import upgrade_1to2_pit as u
from pit_signal_base import build_base_ctx_pit, apply_variant_v19

with open(f"{ABL_DIR}/ablation_summary.json", encoding="utf-8") as f:
    summ = json.load(f)

for fee_k in ["fee_30bps", "fee_20bps"]:
    print(f"\n=== {fee_k} D15 完整指标 ===")
    for wk in ["全五年", "近三年", "2026全年", "IS_21_23", "OOS_24_26", "2025_2026"]:
        print(f"  -- {wk} --")
        for vn in ["Base_le60", "NoCap", "Cap_80", "Cap_100", "Soft_m10", "Soft_m20"]:
            w = summ[fee_k][vn]["d15"][wk]
            tr, wr, plr = w["trades"], w["win_rate_pct"], w["plr"]
            n1, eq, t3 = w["nav_1s"], w["eq_nav"], w["trim3_nav"]
            mdd, csi, ex1, exeq = w["mdd_pct"], w["csi300_pct"], w["excess_1s_pp"], w["excess_eq_pp"]
            print(f"    {vn:<9}: {tr:>2}b WR={wr:>5.2f}% PLR={plr:>4.2f} 1S={n1:>6.2f}x EQ={eq:>5.2f}x Trim3={t3:>5.2f}x MDD={mdd:>5.2f}% CSI={csi:>+6.2f}% Ex1S={ex1:>+8.1f}pp ExEQ={exeq:>+7.1f}pp")

print("\n=== 检查 2026-08-28 宏昌电子 & 4 笔 gt60 成交 5m 核验 ===")
base_ctx = build_base_ctx_pit(u.DATA_END_DT)
c_b = apply_variant_v19(base_ctx, 60.0, 0.0)
c_n = apply_variant_v19(base_ctx, None, 0.0)
hb, hn = c_b["hist_fb"], c_n["hist_fb"]
rb = hb[(hb["d2_dt"] == "2026-08-28") & (hb["c6"] == "603002")].iloc[0]
rn = hn[(hn["d2_dt"] == "2026-08-28") & (hn["c6"] == "603002")].iloc[0]
print("603002 宏昌电子 Base vs NoCap:")
for col in ["score_active", "tot_thr", "true_buy_rk", "front_lock_cnt", "mkt_yizi_cnt", "buy_open_lead", "rk_theme"]:
    print(f"  {col}: Base={rb[col]} vs NoCap={rn[col]}")
print("  NoCap 2026-08-28 top candidates by _sv_v19:")
day828 = hn[(hn["d2_dt"] == "2026-08-28") & (hn["score_active"] >= 260)].sort_values("score_active", ascending=False)
for _, x in day828.iterrows():
    print(f"    {x['c6']} {x['name']} c={x['close']:.2f} plate={x['plate']} rk_t={x['rk_theme']} sc={x['score_active']:.1f} thr={x['tot_thr']} pass={bool(c_n['mask_v19'][x.name])}")

bars = c_n["bars_5m_map"]
for c6, nm, d2, d3, trig in [
    ("002932", "明德生物", "2022-12-12", "2022-12-13", 71.07),
    ("003043", "华亚智能", "2026-06-30", "2026-07-01", 96.23),
]:
    a2 = bars[(c6, d2)]
    hits = [(int(r[0]), float(r[2])) for r in a2 if r[2] >= trig - 1e-4]
    a3 = bars[(c6, d3)]
    idx30 = [i for i, r in enumerate(a3) if int(r[0]) == 1030][0]
    vwap = a3[: idx30 + 1, 6].sum() / a3[: idx30 + 1, 5].sum()
    c1030 = float(a3[idx30, 4])
    zt3 = c_n["price_lookup"][(c6, d3)][4]
    print(f"  5m核验 {c6} {nm}: d2首次>=trig({trig}) bar={hits[0] if hits else None}; d3 10:30 close={c1030:.2f} vs vwap={vwap:.2f} (zt3={zt3:.2f})")
