#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
expC_part2_duality_and_interlock.py
全量实证：
1. 因子对偶律验证：在 Day 3 (1进2卖 vs 2进3买, N=7738) 与 Day 4 (2进3卖 vs 3进4买, N=2161) 上，
   严格计算同一因子的「前手立刻卖出超额收益 Delta_Sell = R_sell_now - R_hold_on」与「后手买入接力净收益 R_buy_relay」，
   验证何时严格反号（前手卖点正向指标 == 后手买点反向指标），何时因开盘跳空方向分裂。
2. 双向买卖点互锁改造实测（IS 2021-2023 -> OOS 2024-2026）：
   - 改造α：二进三 V1.0 封死三板进入 Day 4 时，若触发「三进四拒接盘信号」(如 Day4 开盘<3% / score_v34低 / 10:30破VWAP) 提前卖出 vs 原版死扛至午后/收盘；
   - 改造β：三进四 V3.4 在 Day 4 买入时，利用 cand_3to4_5m_bars 检验剔除「前手10:00/10:30破VWAP或盘中冲高回落出逃时刻」；
   - 改造γ：二进三 V1.0 在 Day 3 买入时，检验剔除「一进二 Day 3 必卖信号」(队友核按钮<-1.5%、一日游席位、深绿核按钮<-4%等) 与盘中 5m 站稳均线买点。
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio")
OUT_DIR = ROOT / "backtests_astock/factor_mutual_learning_and_ablation_20261117"
FEE = 0.002

c23 = pd.read_parquet(ROOT / "backtests_astock/clean_2to3_v10_20261117/data_pit/clean_2to3_5y.parquet")
fa = pd.read_parquet(ROOT / "backtests_astock/clean_2to3_v10_20261117/data_pit/factors_a.parquet")
fb = pd.read_parquet(ROOT / "backtests_astock/clean_2to3_v10_20261117/data_pit/factors_b.parquet")
fc = pd.read_parquet(ROOT / "backtests_astock/clean_2to3_v10_20261117/data_pit/factors_c.parquet")
c34 = pd.read_parquet(ROOT / "backtests_astock2/data_5y/cand_3to4_enriched54.parquet")
b34_5m = pd.read_parquet(ROOT / "backtests_astock2/data_5y/cand_3to4_5m_bars.parquet")
l_12 = pd.read_csv(ROOT / "backtests_astock/clean_rebacktest_20261116/partB_1to2/ledger_base_1to2_v18.csv")
l_23 = pd.read_csv(ROOT / "backtests_astock/clean_2to3_v10_20261117/ledger_base_2to3_v10_std90.csv")
l_34 = pd.read_csv(ROOT / "backtests_astock/clean_rebacktest_20261116/partA_high_3to4/ledger_base_3to4_v34.csv")

assert len(c23) > 10000 and len(c34) > 2500 and c23["open_pct"].abs().median() < 0.20

# Merge 2to3 universe (true 2-board non-yizi buyable on Day 3, 2021-11-15..2026-11-16)
m23 = c23.merge(fa[["code", "buy_date", "b01_hhi_low_q25", "b10_top1_share_ge30", "a22_elo_ice_lt95"]], on=["code", "buy_date"], how="left")
m23 = m23.merge(fb[["code", "buy_date", "xq_cnt_tot", "ir_cnt_20d"]], on=["code", "buy_date"], how="left")
m23 = m23.merge(fc[["code", "buy_date", "d2_seal_amt_ratio", "d2_low_pct", "lock_top10", "d2_real_turn", "peers_open_avg_2b", "is_pure_outsider"]], on=["code", "buy_date"], how="left")
u23 = m23[(m23["buy_date"] >= "2021-11-15") & (~m23["prev_is_yizi"]) & (m23["buyable_open"])].copy()
u23["is_oos"] = u23["buy_date"] >= "2024-01-01"

# On Day 3:
# Pre-holder (1to2 holder entering Day 3 with 2nd-board close = 1.0):
# If sells immediately at Day 3 09:25 open: value = 1 + open_pct
# If holds through Day 3 (and if unsealed exits D3 close / D4 open, or if sealed_3b rides to f30 exit):
# Notice ret_opn_f30 is net return of buying at D3 open (1 + open_pct) and exiting per clean f30 rule!
# Therefore terminal exit price relative to D2 close = (1 + open_pct) * (1 + ret_opn_f30) / (1 - FEE)!
u23["hold_val_rel_d2c"] = (1.0 + u23["open_pct"]) * (1.0 + u23["ret_opn_f30"]) / (1.0 - FEE)
u23["sell0925_val_rel_d2c"] = 1.0 + u23["open_pct"]
# Pre-holder Delta_Sell (positive = selling immediately at D3 09:25 BEATS holding on!)
u23["delta_1to2_sell_pct"] = (u23["sell0925_val_rel_d2c"] / u23["hold_val_rel_d2c"] - 1.0) * 100.0
# Relayer (2to3 buyer at D3 09:25) net return:
u23["relay_2to3_buy_pct"] = u23["ret_opn_f30"] * 100.0

print("=== A. HANDOFF NODE 1 (DAY 3: 1进2卖点正向Delta vs 2进3买点净收益, N=%d) ===" % len(u23))
conds_d3 = [
    ("D3高开 +2.5%~+9.2% (兑现区)", (u23["open_pct"] > 0.025) & (u23["open_pct"] <= 0.092)),
    ("D3极高开 >+5.0%", u23["open_pct"] > 0.050),
    ("雪球热帖 >=4帖", u23["xq_cnt_tot"].fillna(0) >= 4),
    ("D2缩量死锁(封成比>=25%)", u23["d2_seal_amt_ratio"].fillna(0) >= 0.25),
    ("板块涨停>=15家过热", u23["plate_sz"] >= 15),
    ("近20日有机构调研", u23["ir_cnt_20d"].fillna(0) >= 1),
    ("昨全场涨停>=95家高潮", u23["mkt_zt_prev"] >= 95),
    ("同题材队友竞价<-1.5%核按钮", u23["peers_open_avg_2b"].fillna(0) < -0.015),
    ("[反例:2进3甜区] 绿微红开+雪球0帖+弱封", (u23["open_pct"].between(-0.065, 0.025)) & (u23["xq_cnt_tot"].fillna(0) == 0) & (u23["d2_seal_amt_ratio"].fillna(0.1) < 0.05)),
]
duality_d3 = []
for name, mask in conds_d3:
    s_is = u23[mask & (~u23["is_oos"])]
    s_oos = u23[mask & u23["is_oos"]]
    s_all = u23[mask]
    row = {
        "factor": name, "n": int(len(s_all)),
        "sell_gain_is": round(float(s_is["delta_1to2_sell_pct"].mean()), 2) if len(s_is) else None,
        "sell_gain_oos": round(float(s_oos["delta_1to2_sell_pct"].mean()), 2) if len(s_oos) else None,
        "buy_ret_is": round(float(s_is["relay_2to3_buy_pct"].mean()), 2) if len(s_is) else None,
        "buy_ret_oos": round(float(s_oos["relay_2to3_buy_pct"].mean()), 2) if len(s_oos) else None,
        "buy_wr_all": round(float((s_all["relay_2to3_buy_pct"] > 0).mean() * 100), 1) if len(s_all) else None,
    }
    duality_d3.append(row)
    print(f"  {name:34s} | n={row['n']:4d} | 1进2立卖超额(IS/OOS): {row['sell_gain_is']:+6.2f}%/{row['sell_gain_oos']:+6.2f}% | 2进3买入收益(IS/OOS): {row['buy_ret_is']:+6.2f}%/{row['buy_ret_oos']:+6.2f}% (WR {row['buy_wr_all']}%)")

# --- NODE 2: Day 4 (2进3卖点 vs 3进4买点) ---
print("\n=== B. HANDOFF NODE 2 (DAY 4: 2进3卖点正向Delta vs 3进4买点净收益) ===")
print("c34 cols check:", [c for c in c34.columns if "ret" in c or "pct" in c or "zt" in c or "score" in c])
print("b34_5m cols:", b34_5m.shape, list(b34_5m.columns)[:15])
EOF
