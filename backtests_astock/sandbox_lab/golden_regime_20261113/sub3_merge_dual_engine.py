import os, sys, pickle, json
import numpy as np
import pandas as pd

SANDBOX = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab"
OUT_DIR = f"{SANDBOX}/golden_regime_20261113"

with open(f"{SANDBOX}/high_dragon_scorecard_20261113/part1_cache.pkl", "rb") as f:
    (all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(f)

# 1. 加载首阴 V5.1 ledger
df_yin = pd.read_csv(f"{SANDBOX}/high_dragon_scorecard_20261113/v5_morn_42_ledger.csv")
df_yin['source'] = 'Yin_V5.1'
df_yin['exit_at_open'] = df_yin['eo']
df_yin['code'] = df_yin['code'].astype(str).str.zfill(6)

# 2. 提取最优黄金期五板卡异动信号
tdf = pd.read_pickle(f"{OUT_DIR}/sub3_raw_simulated_trades_5y.pkl")
base_mask = (
    (tdf['mkt_max_board_prev'] >= 7) &
    (tdf['prev_break_dt_rate_10d'] <= 0.30) &
    (tdf['open_pct'] >= 0.0) &
    (tdf['open_pct'] <= 0.055) &
    (tdf['headroom'] >= 14.0)
)
df_5b = tdf[base_mask].copy()
df_5b['source'] = 'Golden_5Board'
df_5b['code'] = df_5b['code'].astype(str).str.zfill(6)

print(f"Loaded Yin V5.1: {len(df_yin)} trades.")
print(f"Loaded Golden 5-Board: {len(df_5b)} trades.")

# 统一字段
common_cols = ['buy_date', 'exit_date', 'code', 'name', 'net_ret', 'exit_at_open', 'source']
yin_std = df_yin[common_cols].copy()
b5_std = df_5b[common_cols].copy()

def run_single_slot(df_pool, priority_rule="yin_first"):
    """
    单仓轮动合成回测:
    priority_rule:
      - 'yin_first': 同日首阴优先
      - '5b_first': 同日五板优先
    """
    # 排序权重
    pool = df_pool.copy()
    if priority_rule == "yin_first":
        pool['prio'] = np.where(pool['source'] == 'Yin_V5.1', 2, 1)
    else:
        pool['prio'] = np.where(pool['source'] == 'Golden_5Board', 2, 1)
        
    pool = pool.sort_values(['buy_date', 'prio'], ascending=[True, False]).reset_index(drop=True)
    
    taken = []
    fd = ""
    peo = False
    
    for r in pool.itertuples():
        can_buy = False
        if fd == "":
            can_buy = True
        elif r.buy_date > fd:
            can_buy = True
        elif r.buy_date == fd and peo and r.exit_at_open:
            can_buy = True
            
        if can_buy:
            taken.append(r)
            fd = r.exit_date
            peo = r.exit_at_open
            
    res_df = pd.DataFrame(taken)
    return res_df

def calc_all_periods(df_trades):
    periods = [
        ("full_5y", "2022-01-04", "2026-11-12"),
        ("is_22_23", "2022-01-04", "2023-12-29"),
        ("oos_24_26", "2024-01-02", "2026-11-12"),
        ("ex26h2_4.5y", "2022-01-04", "2026-06-30"),
        ("jul26_special", "2026-07-01", "2026-11-12"),
    ]
    
    res = {}
    for p_name, s_dt, e_dt in periods:
        sub = df_trades[(df_trades['buy_date'] >= s_dt) & (df_trades['buy_date'] <= e_dt)] if not df_trades.empty else pd.DataFrame()
        n = len(sub)
        csi_r = (CSI_MAP[e_dt] / CSI_MAP[s_dt] - 1.0) * 100.0 if (s_dt in CSI_MAP and e_dt in CSI_MAP) else 0.0
        if n == 0:
            res[p_name] = {'trades': 0, 'wr': 0.0, 'plr': 0.0, 'nav': 1.0, 'mdd': 0.0, 'eq_nav': 1.0, 'csi': csi_r, 'excess': -csi_r}
            continue
            
        rets = sub['net_ret'].values
        nav = float(np.prod(1.0 + rets))
        cur, pk, mdd = 1.0, 1.0, 0.0
        for x in rets:
            cur *= (1.0 + x)
            pk = max(pk, cur)
            mdd = max(mdd, (pk - cur) / pk)
        wr = float(np.mean(rets > 0) * 100.0)
        pos = rets[rets > 0]
        neg = np.abs(rets[rets <= 0])
        plr = float(np.mean(pos) / np.mean(neg)) if (len(pos) > 0 and len(neg) > 0) else 99.0
        
        # 日等权
        eq_rets = sub.groupby('buy_date')['net_ret'].mean().values
        eq_nav = float(np.prod(1.0 + eq_rets))
        excess = (nav - 1.0) * 100.0 - csi_r
        
        # 统计子策略笔数
        n_yin = int((sub['source'] == 'Yin_V5.1').sum())
        n_5b = int((sub['source'] == 'Golden_5Board').sum())
        
        res[p_name] = {
            'trades': n,
            'n_yin': n_yin,
            'n_5b': n_5b,
            'wr': round(wr, 1),
            'plr': round(plr, 2),
            'nav': round(nav, 3),
            'mdd': round(mdd * 100.0, 1),
            'eq_nav': round(eq_nav, 3),
            'csi': round(csi_r, 1),
            'excess': round(excess, 1)
        }
    return res

print("Testing 3 configurations:")
# Config 1: 纯首阴 V5.1
m1 = calc_all_periods(yin_std)
print("\n[Config 1: 纯首阴 V5.1 基准 (42笔)]")
for p, s in m1.items():
    print(f"  {p:15s}: N={s['trades']:2d}, WR={s['wr']:4.1f}%, NAV={s['nav']:6.3f}x, MDD={s['mdd']:4.1f}%, EQ={s['eq_nav']:6.3f}x, ExCSI={s['excess']:+6.1f}%")

# Config 2: 纯前视镜黄金期五板卡异动
m2 = calc_all_periods(b5_std)
print("\n[Config 2: 纯前视镜黄金期五板卡异动 (51笔)]")
for p, s in m2.items():
    print(f"  {p:15s}: N={s['trades']:2d}, WR={s['wr']:4.1f}%, NAV={s['nav']:6.3f}x, MDD={s['mdd']:4.1f}%, EQ={s['eq_nav']:6.3f}x, ExCSI={s['excess']:+6.1f}%")

# Config 3A: 双引擎合一 (首阴优先)
combined_pool = pd.concat([yin_std, b5_std], ignore_index=True)
syn_a = run_single_slot(combined_pool, "yin_first")
m3a = calc_all_periods(syn_a)
print("\n[Config 3A: 双引擎合一 (首阴优先)]")
for p, s in m3a.items():
    print(f"  {p:15s}: N={s['trades']:2d} (Yin={s['n_yin']}, 5B={s['n_5b']}), WR={s['wr']:4.1f}%, NAV={s['nav']:6.3f}x, MDD={s['mdd']:4.1f}%, EQ={s['eq_nav']:6.3f}x, ExCSI={s['excess']:+6.1f}%")

# Config 3B: 双引擎合一 (五板优先)
syn_b = run_single_slot(combined_pool, "5b_first")
m3b = calc_all_periods(syn_b)
print("\n[Config 3B: 双引擎合一 (五板优先)]")
for p, s in m3b.items():
    print(f"  {p:15s}: N={s['trades']:2d} (Yin={s['n_yin']}, 5B={s['n_5b']}), WR={s['wr']:4.1f}%, NAV={s['nav']:6.3f}x, MDD={s['mdd']:4.1f}%, EQ={s['eq_nav']:6.3f}x, ExCSI={s['excess']:+6.1f}%")

# 保存 ledger
syn_a.to_csv(f"{OUT_DIR}/sub3_dual_engine_yin_first_ledger.csv", index=False)
syn_b.to_csv(f"{OUT_DIR}/sub3_dual_engine_5b_first_ledger.csv", index=False)
print("Saved ledgers successfully.")
