#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_v34_baseline_trades.py
检视 V3.4 原版在 2026 年（尤其是 7 月后和 10 月后）的具体交易台账与指标
"""
import os, sys, pickle, json
import numpy as np, pandas as pd

CACHE_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/special_26q4/3to4_26q4/cache_d_and_p.pkl"
BTEST2_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2"
sys.path.insert(0, BTEST2_DIR)
from core_3to4_5m_engine import _slice_metrics_chrono, _sim_single_slot_chrono, csi300_ret

with open(CACHE_PATH, "rb") as f:
    pkg = pickle.load(f)

d = pkg["df"].copy()
p = pkg["p_v32"]
sc_v34 = pkg["sc_v34"]

for th in [90, 98]:
    idx = np.where(sc_v34 >= th)[0]
    recs = [dict(p[i], score=int(sc_v34[i]), priority_score=float(sc_v34[i])*10.0 + float(d["prio_3to4"].iloc[i])*0.1,
                 px_d3=float(d["px_d3"].iloc[i]), open_pct=float(d["open_pct"].iloc[i]), prev_to=float(d["prev_to"].iloc[i]))
            for i in idx if p[i] is not None]
    tdf = pd.DataFrame(recs)
    taken, nav, mdd, _ = _sim_single_slot_chrono(tdf)
    print(f"\n==================== V3.4 原版 门槛 >={th} ====================")
    print(f"总触发笔数: {len(tdf)}, 单仓轮动实际买入笔数: {len(taken)}")
    
    # 2026 trades
    taken_df = pd.DataFrame([x._asdict() for x in taken])
    t26 = taken_df[taken_df["buy_date"] >= "2026-01-01"].sort_values("buy_date")
    print(f"2026年实际买入 {len(t26)} 笔:")
    for _, r in t26.iterrows():
        print(f"  [{r['buy_date']}] {str(r['code']).zfill(6)} {r['name']:6s} 买:{r['buy_price']:6.2f}({r['buy_hhmm']:04d}) 卖:{r['exit_price']:6.2f} 持:{r['hold_bars']}d 净益:{r['net_ret']*100:+6.2f}% 分:{r['priority_score']/10:.0f}")

    # Slice metrics across windows:
    # 1. 2026-10-01 ~ 2026-11-13
    # 2. 2026-07-01 ~ 2026-11-13
    # 3. 2026-01-01 ~ 2026-11-13
    # 4. 2023-11-01 ~ 2026-11-13
    # 5. 2021-11-01 ~ 2026-11-13
    windows = [
        ("2026-10后", "2026-10-01", "2026-11-13"),
        ("2026-07后", "2026-07-01", "2026-11-13"),
        ("2026全年", "2026-01-01", "2026-11-13"),
        ("近三年", "2023-11-01", "2026-11-13"),
        ("全五年", "2021-11-01", "2026-11-13"),
    ]
    for wname, sdt, edt in windows:
        sub_t = tdf[(tdf["buy_date"] >= sdt) & (tdf["buy_date"] <= edt)]
        m = _slice_metrics_chrono(sub_t, sdt, edt)
        csi = csi300_ret(sdt, edt)
        single_ret = m["single_nav"] - 1.0
        eq_ret = m["eq_nav"] - 1.0
        print(f"  [{wname:8s}] 单仓: {m['single_n']:2d}笔 胜率={m['wr']:4.1f}% 盈亏比={m['payoff']:4.2f} NAV={m['single_nav']:6.2f}x(益{single_ret*100:+6.1f}%) MDD={m['single_mdd_pct']:4.1f}% | 沪深300={csi*100:+5.1f}% 单仓净超额={(single_ret - csi)*100:+6.1f}% | 等权NAV={m['eq_nav']:6.2f}x(益{eq_ret*100:+6.1f}%) 等权净超额={(eq_ret - csi)*100:+6.1f}%")
