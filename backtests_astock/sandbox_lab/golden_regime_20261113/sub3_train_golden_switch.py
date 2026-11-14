import os, sys, pickle, json
import numpy as np
import pandas as pd

SANDBOX = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab"
OUT_DIR = f"{SANDBOX}/golden_regime_20261113"

with open(f"{SANDBOX}/high_dragon_scorecard_20261113/part1_cache.pkl", "rb") as f:
    (all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(f)

tdf = pd.read_pickle(f"{OUT_DIR}/sub3_raw_simulated_trades_5y.pkl")
print(f"Loaded {len(tdf)} raw simulated trades.")

def eval_sub_portfolio(df, name="Strategy"):
    """
    计算单仓轮动在不同周期的 D15 指标:
    - 5年全期 (2022-01-04 至 2026-11-12)
    - 样本内 (2022-01-04 至 2023-12-29)
    - 样本外近三年 (2024-01-02 至 2026-11-12)
    - 去26年下半年四年半 (2022-01-04 至 2026-06-30)
    - 2026年7-11月专项区间 (2026-07-01 至 2026-11-12)
    """
    if df.empty:
        return {}
        
    df_sorted = df.sort_values(['buy_date', 'open_pct'], ascending=[True, False]).copy()
    
    # 单仓轮动
    taken = []
    fd = ""
    peo = False
    for r in df_sorted.itertuples():
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and r.exit_at_open):
            taken.append(r)
            fd = r.exit_date
            peo = r.exit_at_open
            
    res_df = pd.DataFrame(taken)
    
    periods = [
        ("full_5y", "2022-01-04", "2026-11-12"),
        ("is_22_23", "2022-01-04", "2023-12-29"),
        ("oos_24_26", "2024-01-02", "2026-11-12"),
        ("ex26h2_4.5y", "2022-01-04", "2026-06-30"),
        ("jul26_special", "2026-07-01", "2026-11-12"),
    ]
    
    out = {}
    for p_name, s_dt, e_dt in periods:
        sub = res_df[(res_df['buy_date'] >= s_dt) & (res_df['buy_date'] <= e_dt)] if not res_df.empty else pd.DataFrame()
        n = len(sub)
        csi_r = (CSI_MAP[e_dt] / CSI_MAP[s_dt] - 1.0) * 100.0 if (s_dt in CSI_MAP and e_dt in CSI_MAP) else 0.0
        if n == 0:
            out[p_name] = {'trades': 0, 'wr': 0.0, 'plr': 0.0, 'nav': 1.0, 'mdd': 0.0, 'eq_nav': 1.0, 'csi': csi_r, 'excess': -csi_r}
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
        
        out[p_name] = {
            'trades': n,
            'wr': round(wr, 1),
            'plr': round(plr, 2),
            'nav': round(nav, 3),
            'mdd': round(mdd * 100.0, 1),
            'eq_nav': round(eq_nav, 3),
            'csi': round(csi_r, 1),
            'excess': round(excess, 1)
        }
    return out, res_df

print("Script template ready.")

# 1. 基准无过滤 (裸五板卡异动)
stats_base, _ = eval_sub_portfolio(tdf, "Raw Baseline")

print("\n=== [1] 基准: 裸五板卡异动 (未加任何前视镜开关) ===")
for p, s in stats_base.items():
    print(f"  {p:15s}: N={s['trades']:3d}, WR={s['wr']:4.1f}%, NAV={s['nav']:6.3f}x, MDD={s['mdd']:4.1f}%, EQ={s['eq_nav']:6.3f}x, ExCSI={s['excess']:+6.1f}%")

# 2. 单因子测试
conds = {
    "C1_空间破局 (前日最高板>=6)": tdf['mkt_max_board_prev'] >= 6,
    "C1b_空间破局强 (前日最高板>=7)": tdf['mkt_max_board_prev'] >= 7,
    "C2_断板容错高 (10日断板跌停率<=30%)": tdf['prev_break_dt_rate_10d'] <= 0.30,
    "C2b_零高位跌停 (前日>=3板跌停数==0)": tdf['prev_3b_dt_cnt'] == 0,
    "C3_安全余量足 (买入时余量>=15%)": tdf['headroom'] >= 15.0,
    "C3b_安全余量极宽 (买入时余量>=20%)": tdf['headroom'] >= 20.0,
    "C4_竞价红开平稳 (0.0<=open<=5.5%)": (tdf['open_pct'] >= 0.0) & (tdf['open_pct'] <= 0.055),
    "C4b_筹码锁仓好 (前十股东>=45%)": tdf['lock_top10'] >= 45.0,
    "C5_急刹阀 (市场跌停<=5且前日3板跌停==0)": (tdf['mkt_dt_prev'] <= 5) & (tdf['prev_3b_dt_cnt'] == 0),
}

print("\n=== [2] 单因子前视镜开关消融测试 ===")
print(f"{'因子名称':35s} | {'22-23 IS NAV':12s} | {'24-26 OOS NAV':13s} | {'5年全量 NAV':12s} | {'去26下半年':11s} | {'26年7-11月':11s}")
print("-" * 105)

single_results = {}
for c_name, mask in conds.items():
    sub_df = tdf[mask].copy()
    st, _ = eval_sub_portfolio(sub_df, c_name)
    single_results[c_name] = st
    is_nav = st['is_22_23']['nav']
    oos_nav = st['oos_24_26']['nav']
    full_nav = st['full_5y']['nav']
    ex26_nav = st['ex26h2_4.5y']['nav']
    jul26_nav = st['jul26_special']['nav']
    print(f"{c_name:35s} | {is_nav:10.3f}x  | {oos_nav:11.3f}x  | {full_nav:10.3f}x  | {ex26_nav:9.3f}x | {jul26_nav:9.3f}x")

