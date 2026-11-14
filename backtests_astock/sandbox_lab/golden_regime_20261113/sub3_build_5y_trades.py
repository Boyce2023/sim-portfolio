import os, sys, pickle, time, json
import numpy as np
import pandas as pd

SANDBOX = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab"
OUT_DIR = f"{SANDBOX}/golden_regime_20261113"
sys.path.insert(0, OUT_DIR)

from sub3_sim_engine import (
    all_dts, dt_to_idx, code_bars, df_all, CSI_MAP, SH_MAP, SZ_MAP,
    simulate_card_yidong_trade, FEE_RATE
)
from sub3_diag_2026_yidong import calc_yidong_headroom

print("Calculating full 5-year trade simulation on 4-to-5 and 5-to-6...")
t0 = time.time()

# 提取五年全量 4进5 (prev_streak == 4) 和 5进6 (prev_streak == 5) 可买候选
pool = df_all[(df_all['prev_streak'].isin([4, 5])) & (df_all['buyable_open'] == True)].copy()
print(f"Total buyable candidates across 5 years: {len(pool):,}")

trades = []
for r in pool.itertuples():
    c6 = str(r.code).zfill(6)
    bars = code_bars.get(c6)
    if not bars: continue
    imap = SH_MAP if c6.startswith('6') else SZ_MAP
    headroom, touch10, touch30, plimit = calc_yidong_headroom(c6, r.buy_date, bars, imap)
    res = simulate_card_yidong_trade(c6, r.buy_date, bars, imap, dev_headroom_discount=0.07)
    if res:
        res['name'] = r.name
        res['prev_streak'] = r.prev_streak
        res['open_pct'] = r.open_pct
        res['headroom'] = headroom
        res['touch10'] = touch10
        res['touch30'] = touch30
        res['mkt_max_board_prev'] = getattr(r, 'mkt_max_board_prev', 0)
        res['prev_break_dt_rate_10d'] = getattr(r, 'prev_break_dt_rate_10d', 0)
        res['prev_3b_dt_cnt'] = getattr(r, 'prev_3b_dt_cnt', 0)
        res['prev_3to4_nuke_rate_20d'] = getattr(r, 'prev_3to4_nuke_rate_20d', 0)
        res['mkt_zt_prev'] = getattr(r, 'mkt_zt_prev', 0)
        res['mkt_dt_prev'] = getattr(r, 'mkt_dt_prev', 0)
        res['lock_top10'] = getattr(r, 'lock_top10', 0)
        res['s_prior'] = getattr(r, 's_prior', 0)
        res['true_buy_rk'] = getattr(r, 'true_buy_rk', 99)
        res['mkt_open_rk'] = getattr(r, 'mkt_open_rk', 99)
        trades.append(res)

tdf = pd.DataFrame(trades)
print(f"Generated {len(tdf):,} simulated trades in {time.time()-t0:.2f}s.")
tdf.to_pickle(f"{OUT_DIR}/sub3_raw_simulated_trades_5y.pkl")
print("Saved to sub3_raw_simulated_trades_5y.pkl")
