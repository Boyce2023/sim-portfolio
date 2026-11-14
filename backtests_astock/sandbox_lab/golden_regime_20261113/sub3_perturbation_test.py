import os, sys, pickle, json
import numpy as np
import pandas as pd

SANDBOX = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab"
OUT_DIR = f"{SANDBOX}/golden_regime_20261113"

with open(f"{SANDBOX}/high_dragon_scorecard_20261113/part1_cache.pkl", "rb") as f:
    (all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(f)

# 加载首阴 V5.1
df_yin = pd.read_csv(f"{SANDBOX}/high_dragon_scorecard_20261113/v5_morn_42_ledger.csv")
df_yin['source'] = 'Yin_V5.1'
df_yin['exit_at_open'] = df_yin['eo']
df_yin['code'] = df_yin['code'].astype(str).str.zfill(6)
common_cols = ['buy_date', 'exit_date', 'code', 'name', 'net_ret', 'exit_at_open', 'source']
yin_std = df_yin[common_cols].copy()

tdf = pd.read_pickle(f"{OUT_DIR}/sub3_raw_simulated_trades_5y.pkl")

def eval_perturbed_dual(max_b=7, dt_rate=0.30, hr=14.0, op_hi=0.055):
    mask = (
        (tdf['mkt_max_board_prev'] >= max_b) &
        (tdf['prev_break_dt_rate_10d'] <= dt_rate) &
        (tdf['open_pct'] >= 0.0) &
        (tdf['open_pct'] <= op_hi) &
        (tdf['headroom'] >= hr)
    )
    b5 = tdf[mask].copy()
    b5['source'] = 'Golden_5Board'
    b5['code'] = b5['code'].astype(str).str.zfill(6)
    b5_std = b5[common_cols].copy()
    
    # 合成单仓 (首阴优先)
    pool = pd.concat([yin_std, b5_std], ignore_index=True)
    pool['prio'] = np.where(pool['source'] == 'Yin_V5.1', 2, 1)
    pool = pool.sort_values(['buy_date', 'prio'], ascending=[True, False]).reset_index(drop=True)
    
    taken, fd, peo = [], "", False
    for r in pool.itertuples():
        can_buy = False
        if fd == "": can_buy = True
        elif r.buy_date > fd: can_buy = True
        elif r.buy_date == fd and peo and r.exit_at_open: can_buy = True
        if can_buy:
            taken.append(r)
            fd = r.exit_date
            peo = r.exit_at_open
    td = pd.DataFrame(taken)
    if td.empty: return 0, 0, 1.0, 0, 1.0, 1.0
    
    # 计算全期、样本外、去26H2净值
    def get_nav(s_d, e_d):
        sub = td[(td['buy_date'] >= s_d) & (td['buy_date'] <= e_d)]
        if sub.empty: return 0, 0.0, 1.0, 0.0
        rets = sub['net_ret'].values
        nav = float(np.prod(1.0 + rets))
        cur, pk, mdd = 1.0, 1.0, 0.0
        for x in rets:
            cur *= (1.0 + x); pk = max(pk, cur); mdd = max(mdd, (pk - cur)/pk)
        return len(sub), float(np.mean(rets > 0)*100), nav, mdd*100
        
    n_5y, wr_5y, nav_5y, mdd_5y = get_nav("2022-01-04", "2026-11-12")
    _, _, nav_oos, _ = get_nav("2024-01-02", "2026-11-12")
    _, _, nav_ex26, _ = get_nav("2022-01-04", "2026-06-30")
    _, _, nav_jul26, _ = get_nav("2026-07-01", "2026-11-12")
    
    return {
        'trades': n_5y, 'wr': round(wr_5y, 1), 'nav_5y': round(nav_5y, 2),
        'mdd_5y': round(mdd_5y, 1), 'nav_oos': round(nav_oos, 2),
        'nav_ex26': round(nav_ex26, 2), 'nav_jul26': round(nav_jul26, 2)
    }

print("Running parameter perturbation table (±10% / ±15%)...")
grid = []

# 基准参数
base = eval_perturbed_dual(max_b=7, dt_rate=0.30, hr=14.0, op_hi=0.055)
grid.append({'param': '基准参数 (MaxBoard>=7, DTRate<=0.30, HR>=14%, Open<=5.5%)', **base})

# 扰动 1: Headroom (余量) ±15% (12.0%, 14.0%, 16.0%)
grid.append({'param': 'Headroom -15% (12.0%)', **eval_perturbed_dual(max_b=7, dt_rate=0.30, hr=12.0, op_hi=0.055)})
grid.append({'param': 'Headroom +15% (16.0%)', **eval_perturbed_dual(max_b=7, dt_rate=0.30, hr=16.0, op_hi=0.055)})

# 扰动 2: DTRate (断板跌停率) ±10% (0.27, 0.30, 0.33)
grid.append({'param': 'DTRate -10% (0.27)', **eval_perturbed_dual(max_b=7, dt_rate=0.27, hr=14.0, op_hi=0.055)})
grid.append({'param': 'DTRate +10% (0.33)', **eval_perturbed_dual(max_b=7, dt_rate=0.33, hr=14.0, op_hi=0.055)})

# 扰动 3: Open_Hi (开盘涨幅上限) ±15% (0.047, 0.055, 0.063)
grid.append({'param': 'Open_Hi -15% (4.7%)', **eval_perturbed_dual(max_b=7, dt_rate=0.30, hr=14.0, op_hi=0.047)})
grid.append({'param': 'Open_Hi +15% (6.3%)', **eval_perturbed_dual(max_b=7, dt_rate=0.30, hr=14.0, op_hi=0.063)})

# 扰动 4: MaxBoard (最高板破局) 6板 vs 7板 vs 8板
grid.append({'param': 'MaxBoard 放宽至 >=6板', **eval_perturbed_dual(max_b=6, dt_rate=0.30, hr=14.0, op_hi=0.055)})
grid.append({'param': 'MaxBoard 收紧至 >=8板', **eval_perturbed_dual(max_b=8, dt_rate=0.30, hr=14.0, op_hi=0.055)})

df_grid = pd.DataFrame(grid)
print(df_grid.to_string())
df_grid.to_csv(f"{OUT_DIR}/sub3_perturbation_summary.csv", index=False)
