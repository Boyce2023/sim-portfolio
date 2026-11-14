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

def run_portfolio_simulation(candidates_df, dev_headroom_discount=0.07, open_filter="red_auc", pick_rule="highest_open"):
    """
    运行单仓轮动与日等权回测:
    open_filter:
      - 'red_auc': 0.0 <= open_pct <= 0.055
      - 'any_buyable': open_pct <= 0.095
      - 'positive_open': open_pct > 0.0
    pick_rule:
      - 'highest_open': 当日多只取竞价涨幅最高者
      - 'lowest_open': 取涨幅最低者
      - 'all': 所有候选都参与 (用于算日等权)
    """
    # 筛选候选
    cands = candidates_df[candidates_df['buyable_open'] == True].copy()
    if open_filter == "red_auc":
        cands = cands[(cands['open_pct'] >= 0.0) & (cands['open_pct'] <= 0.055)]
    elif open_filter == "positive_open":
        cands = cands[(cands['open_pct'] > 0.0) & (cands['open_pct'] <= 0.095)]
    elif open_filter == "any_buyable":
        cands = cands[cands['open_pct'] <= 0.095]
        
    trades = []
    for r in cands.itertuples():
        c6 = str(r.code).zfill(6)
        bars = code_bars.get(c6)
        if not bars: continue
        imap = SH_MAP if c6.startswith('6') else SZ_MAP
        res = simulate_card_yidong_trade(c6, r.buy_date, bars, imap, dev_headroom_discount=dev_headroom_discount)
        if res:
            res['name'] = r.name
            res['prev_streak'] = r.prev_streak
            res['open_pct'] = r.open_pct
            res['priority'] = r.open_pct
            trades.append(res)
            
    if not trades:
        return pd.DataFrame(), pd.DataFrame()
        
    tdf = pd.DataFrame(trades).sort_values(['buy_date', 'priority'], ascending=[True, False])
    
    # 单仓轮动模拟: 同一时间最多持仓 1 只，持仓未退出前跳过新信号
    single_trades = []
    free_date = ""
    prev_exit_at_open = False
    
    for r in tdf.itertuples(index=False):
        # 允许同一天买入的条件: 上笔在今日开盘已卖出 (exit_at_open=True 且 exit_date == buy_date)，或者 buy_date > free_date
        can_buy = False
        if free_date == "":
            can_buy = True
        elif r.buy_date > free_date:
            can_buy = True
        elif r.buy_date == free_date and prev_exit_at_open:
            can_buy = True
            
        if can_buy:
            single_trades.append(r)
            free_date = r.exit_date
            prev_exit_at_open = r.exit_at_open
            
    df_single = pd.DataFrame(single_trades)
    return tdf, df_single

def calc_d15_metrics(df_trades, start_dt, end_dt):
    sub = df_trades[(df_trades['buy_date'] >= start_dt) & (df_trades['buy_date'] <= end_dt)]
    n = len(sub)
    csi_ret = (CSI_MAP[end_dt] / CSI_MAP[start_dt] - 1.0) * 100.0 if (end_dt in CSI_MAP and start_dt in CSI_MAP) else 0.0
    
    if n == 0:
        return {
            'trades': 0, 'win_rate': 0.0, 'plr': 0.0, 'nav': 1.0, 'mdd': 0.0,
            'eq_nav': 1.0, 'csi_ret': csi_ret, 'excess': -csi_ret
        }
        
    rets = sub['net_ret'].values
    nav = float(np.prod(1.0 + rets))
    
    # MDD
    cur, pk, mdd = 1.0, 1.0, 0.0
    for r in rets:
        cur *= (1.0 + r)
        pk = max(pk, cur)
        mdd = max(mdd, (pk - cur) / pk)
        
    wr = float(np.mean(rets > 0) * 100.0)
    pos = rets[rets > 0]
    neg = np.abs(rets[rets <= 0])
    plr = float(np.mean(pos) / np.mean(neg)) if (len(pos) > 0 and len(neg) > 0) else 99.0
    
    # 日等权
    eq_rets = sub.groupby('buy_date')['net_ret'].mean().values
    eq_nav = float(np.prod(1.0 + eq_rets))
    
    excess = (nav - 1.0) * 100.0 - csi_ret
    return {
        'trades': n,
        'win_rate': round(wr, 2),
        'plr': round(plr, 2),
        'nav': round(nav, 3),
        'mdd': round(mdd * 100.0, 2),
        'eq_nav': round(eq_nav, 3),
        'csi_ret': round(csi_ret, 2),
        'excess': round(excess, 2)
    }

print("Running test across different candidate pools and periods...")

# 测试 1: 2026-07-01 至 2026-11-12 期间表现
cands_5b = df_all[df_all['prev_streak'] == 5]
cands_4to5 = df_all[df_all['prev_streak'] == 4]
cands_both = df_all[df_all['prev_streak'].isin([4, 5])]

for name, pool in [("五板接力 (5进6)", cands_5b), ("四进五 (买第5板)", cands_4to5), ("高标四进五+五板合集", cands_both)]:
    print(f"\n==================== {name} ====================")
    for flt in ["red_auc", "positive_open", "any_buyable"]:
        all_tdf, single_tdf = run_portfolio_simulation(pool, dev_headroom_discount=0.07, open_filter=flt)
        m_2026 = calc_d15_metrics(single_tdf, "2026-07-01", "2026-11-12")
        m_5y = calc_d15_metrics(single_tdf, "2022-01-04", "2026-11-12")
        m_ex26 = calc_d15_metrics(single_tdf, "2022-01-04", "2026-06-30")
        print(f"Filter [{flt:13s}]:")
        print(f"  2026.07-11: Trades={m_2026['trades']:2d}, WR={m_2026['win_rate']:5.1f}%, NAV={m_2026['nav']:6.3f}x, MDD={m_2026['mdd']:5.1f}%, ExCSI={m_2026['excess']:+6.1f}%")
        print(f"  5-Year 全量: Trades={m_5y['trades']:2d}, WR={m_5y['win_rate']:5.1f}%, NAV={m_5y['nav']:6.3f}x, MDD={m_5y['mdd']:5.1f}%, ExCSI={m_5y['excess']:+6.1f}%")
        print(f"  前四年半(去26下半年): Trades={m_ex26['trades']:2d}, WR={m_ex26['win_rate']:5.1f}%, NAV={m_ex26['nav']:6.3f}x, MDD={m_ex26['mdd']:5.1f}%, ExCSI={m_ex26['excess']:+6.1f}%")

