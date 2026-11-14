#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""高标 V5.1 大盘环境微调实测：复用 sub2_03 的 5 分钟撮合与单仓轮动引擎，只改沪深300近5日加减分"""
import numpy as np, pandas as pd
SRC = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113/sub2_03_golden_relaxation_backtest.py"
lines = open(SRC, encoding="utf-8").read().split("\n")
exec("\n".join(lines[:192]), globals())

base_no_csi = dfr.apply(lambda r: score_v5_1(r) - (8 if r["csi5"] >= -0.005 else (-10 if r["csi5"] < -0.025 else 0)) if score_v5_1(r) > -900 else -999, axis=1)

def csi_pts(c5, up=8, flat=8, mild=0, crash=-10, big=0.025):
    if c5 < -0.025: return crash
    if c5 < -0.005: return mild
    if c5 > big: return up
    return flat

def run(tag, fn, th=88):
    dfr["sc5_1"] = [b if b < -900 else b + fn(c) for b, c in zip(base_no_csi, dfr["csi5"])]
    led = run_simulation(th, th, "morn_cond", "S_hold_d3", False, True, g_map={})
    if led.empty: print(tag, "empty"); return
    r = led["net_ret"].values
    nav = float(np.prod(1 + r)); pk = cur = 1.0; mdd = 0.0
    for x in r: cur *= 1 + x; pk = max(pk, cur); mdd = max(mdd, 1 - cur / pk)
    pos, neg = r[r > 0], -r[r <= 0]
    po = pos.mean() / neg.mean() if len(neg) else 99
    yrs = [round(float(np.prod(1 + led[led.buy_date.str.startswith(y)].net_ret)), 2) for y in ["2022", "2023", "2024", "2025", "2026"]]
    r3 = float(np.prod(1 + led[led.buy_date >= "2024-01-01"].net_ret))
    j7 = led[led.buy_date >= "2026-07-01"]
    print(f"{tag:44s} | n={len(r):2d} WR={np.mean(r>0)*100:4.1f}% PO={po:4.2f} NAV={nav:6.2f}x MDD={mdd*100:4.1f}% | 近三年={r3:5.2f}x | 7月起={len(j7)}笔 {float(np.prod(1+j7.net_ret)):4.2f}x | Yrs={yrs}")

run("0. 现役V5.1 (平稳或涨+8, 跌超2.5%扣10)", lambda c: csi_pts(c))
run("1. 大涨超2.5%再多加4 (+12)", lambda c: csi_pts(c, up=12))
run("2. 大涨超2.5%再多加8 (+16)", lambda c: csi_pts(c, up=16))
run("3. 微跌0.5至2.5%由0改加4", lambda c: csi_pts(c, mild=4))
run("4. 微跌改加4 + 大涨+12", lambda c: csi_pts(c, mild=4, up=12))
run("5. 急跌超2.5%由扣10改一票否决", lambda c: csi_pts(c, crash=-99))
run("6. 急跌扣15", lambda c: csi_pts(c, crash=-15))
run("7. 急跌扣6 (放松)", lambda c: csi_pts(c, crash=-6))
run("8. 大涨+12 + 急跌否决", lambda c: csi_pts(c, up=12, crash=-99))
