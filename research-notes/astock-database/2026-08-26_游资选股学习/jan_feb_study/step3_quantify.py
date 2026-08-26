#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step3: 量化游资选股特征
- 流通市值分布 (amount/turn*100)
- 首板 vs 连板(>=2) 占比
- 换手率分布
- 前期20日涨幅 (涨停日收盘 vs 20个交易日前收盘)
"""
import sqlite3, json, statistics

DB = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/univ2025.db"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26_游资选股学习/jan_feb_study"

with open(f"{OUT_DIR}/zt_records_janfeb2025.json", encoding="utf-8") as f:
    zt = json.load(f)

print(f"total zt instances: {len(zt)}")

# 1. float market cap distribution (using amount/turn*100)
fmc = []
for z in zt:
    if z['turn'] and z['turn'] > 0:
        fmc.append(z['amount'] / (z['turn']/100) / 1e8)  # 亿元
fmc.sort()
def pct(lst, p):
    idx = int(len(lst)*p)
    idx = min(idx, len(lst)-1)
    return lst[idx]
print(f"\n=== 流通市值(亿元) n={len(fmc)} ===")
print(f"  min={fmc[0]:.1f} p10={pct(fmc,0.10):.1f} p25={pct(fmc,0.25):.1f} median={pct(fmc,0.5):.1f} p75={pct(fmc,0.75):.1f} p90={pct(fmc,0.90):.1f} max={fmc[-1]:.1f}")
print(f"  mean={statistics.mean(fmc):.1f}")
under_50 = sum(1 for x in fmc if x < 50)
under_100 = sum(1 for x in fmc if x < 100)
over_300 = sum(1 for x in fmc if x > 300)
print(f"  <50亿: {under_50} ({under_50/len(fmc)*100:.1f}%)  <100亿: {under_100} ({under_100/len(fmc)*100:.1f}%)  >300亿: {over_300} ({over_300/len(fmc)*100:.1f}%)")

# 2. board_streak distribution (首板 vs 连板)
board1 = sum(1 for z in zt if z['board_streak']==1)
board2 = sum(1 for z in zt if z['board_streak']==2)
board3plus = sum(1 for z in zt if z['board_streak']>=3)
print(f"\n=== 板数分布 n={len(zt)} ===")
print(f"  首板(1): {board1} ({board1/len(zt)*100:.1f}%)")
print(f"  2板: {board2} ({board2/len(zt)*100:.1f}%)")
print(f"  >=3板: {board3plus} ({board3plus/len(zt)*100:.1f}%)")

# 3. turnover rate distribution (only for first-board instances, to avoid double count bias)
turns_1st = [z['turn'] for z in zt if z['board_streak']==1 and z['turn'] is not None]
turns_1st.sort()
print(f"\n=== 首板换手率(%) n={len(turns_1st)} ===")
print(f"  median={pct(turns_1st,0.5):.1f} p25={pct(turns_1st,0.25):.1f} p75={pct(turns_1st,0.75):.1f}")
low_turn = sum(1 for x in turns_1st if x < 3)
high_turn = sum(1 for x in turns_1st if x > 15)
print(f"  <3%(缩量'地天板'型): {low_turn} ({low_turn/len(turns_1st)*100:.1f}%)   >15%(放量抢筹型): {high_turn} ({high_turn/len(turns_1st)*100:.1f}%)")

# 4. ST proportion
st_count = sum(1 for z in zt if z['isST'])
print(f"\n=== ST股占比 ===")
print(f"  ST涨停instances: {st_count} / {len(zt)} = {st_count/len(zt)*100:.1f}%")

# 5. prior 20-trading-day gain, for first-board instances only (sample codes)
conn = sqlite3.connect(DB)
cur = conn.cursor()

def get_prior_20d_gain(code, date):
    cur.execute("SELECT date, close FROM k WHERE code=? AND date<=? ORDER BY date DESC LIMIT 25", (code, date))
    rows = cur.fetchall()
    if len(rows) < 21:
        return None
    # rows[0] = date itself (close on zt day), rows[20] = 20 trading days before
    zt_close = rows[0][1]
    prior_close = rows[20][1]
    if prior_close is None or prior_close <= 0:
        return None
    return (zt_close - prior_close) / prior_close * 100

import random
random.seed(42)
sample = random.sample([z for z in zt if z['board_streak']==1], min(300, len([z for z in zt if z['board_streak']==1])))
gains = []
for z in sample:
    g = get_prior_20d_gain(z['code'], z['date'])
    if g is not None:
        gains.append(g)
gains.sort()
print(f"\n=== 首板股 涨停日相对20个交易日前收盘的涨幅(%) n={len(gains)} (随机抽样{len(sample)}首板中可计算的) ===")
print(f"  median={pct(gains,0.5):.1f} p25={pct(gains,0.25):.1f} p75={pct(gains,0.75):.1f} mean={statistics.mean(gains):.1f}")
already_up = sum(1 for g in gains if g > 20)
flat_or_down = sum(1 for g in gains if g <= 5)
print(f"  涨停前20日已涨>20%(趋势中启动): {already_up} ({already_up/len(gains)*100:.1f}%)")
print(f"  涨停前20日<=5%(横盘/无趋势中启动,含首次爆发): {flat_or_down} ({flat_or_down/len(gains)*100:.1f}%)")

results = {
    "n_zt_total": len(zt),
    "float_mktcap_yi": {"min": fmc[0], "p10": pct(fmc,0.1), "p25": pct(fmc,0.25), "median": pct(fmc,0.5), "p75": pct(fmc,0.75), "p90": pct(fmc,0.9), "max": fmc[-1], "pct_under_50yi": under_50/len(fmc)*100, "pct_under_100yi": under_100/len(fmc)*100, "pct_over_300yi": over_300/len(fmc)*100},
    "board_streak_dist": {"board1_pct": board1/len(zt)*100, "board2_pct": board2/len(zt)*100, "board3plus_pct": board3plus/len(zt)*100, "n": len(zt)},
    "first_board_turnover_pct": {"median": pct(turns_1st,0.5), "p25": pct(turns_1st,0.25), "p75": pct(turns_1st,0.75), "pct_low_lt3": low_turn/len(turns_1st)*100, "pct_high_gt15": high_turn/len(turns_1st)*100, "n": len(turns_1st)},
    "st_pct_of_zt": st_count/len(zt)*100,
    "prior_20d_gain_pct_sample": {"n": len(gains), "median": pct(gains,0.5), "p25": pct(gains,0.25), "p75": pct(gains,0.75), "mean": statistics.mean(gains), "pct_already_up_gt20": already_up/len(gains)*100, "pct_flat_lte5": flat_or_down/len(gains)*100},
}
with open(f"{OUT_DIR}/quant_summary.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\nsaved to quant_summary.json")
