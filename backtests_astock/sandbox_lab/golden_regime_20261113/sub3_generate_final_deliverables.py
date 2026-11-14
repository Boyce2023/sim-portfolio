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
common_cols = ['buy_date', 'exit_date', 'code', 'name', 'net_ret', 'exit_at_open', 'source']
yin_std = df_yin[common_cols].copy()

# 2. 加载 5年原始五板卡异动
tdf = pd.read_pickle(f"{OUT_DIR}/sub3_raw_simulated_trades_5y.pkl")

# 3. 黄金期最优五板卡异动
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
b5_std = df_5b[common_cols].copy()

def run_single_slot(df_pool, prio_rule="yin_first"):
    pool = df_pool.copy()
    if prio_rule == "yin_first":
        pool['prio'] = np.where(pool['source'] == 'Yin_V5.1', 2, 1)
    else:
        pool['prio'] = np.where(pool['source'] == 'Golden_5Board', 2, 1)
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
    return pd.DataFrame(taken)

def calc_d15(df_sub):
    periods = [
        ("五年全期 (2022-2026)", "2022-01-04", "2026-11-12"),
        ("样本内 IS (2022-2023)", "2022-01-04", "2023-12-29"),
        ("近三年 OOS (2024-2026)", "2024-01-02", "2026-11-12"),
        ("去26下半年四年半 (2022-2026.06)", "2022-01-04", "2026-06-30"),
        ("2026年7-11月专项", "2026-07-01", "2026-11-12"),
    ]
    res = {}
    for p_name, s_d, e_d in periods:
        sub = df_sub[(df_sub['buy_date'] >= s_d) & (df_sub['buy_date'] <= e_d)] if not df_sub.empty else pd.DataFrame()
        n = len(sub)
        csi_r = (CSI_MAP[e_d] / CSI_MAP[s_d] - 1.0) * 100.0 if (s_d in CSI_MAP and e_d in CSI_MAP) else 0.0
        if n == 0:
            res[p_name] = {'trades': 0, 'wr': 0.0, 'plr': 0.0, 'nav': 1.0, 'eq_nav': 1.0, 'mdd': 0.0, 'csi_ret': round(csi_r, 2), 'excess': round(-csi_r, 2)}
            continue
        rets = sub['net_ret'].values
        nav = float(np.prod(1.0 + rets))
        cur, pk, mdd = 1.0, 1.0, 0.0
        for x in rets:
            cur *= (1.0 + x); pk = max(pk, cur); mdd = max(mdd, (pk - cur)/pk)
        wr = float(np.mean(rets > 0) * 100.0)
        pos, neg = rets[rets > 0], np.abs(rets[rets <= 0])
        plr = float(np.mean(pos) / np.mean(neg)) if (len(pos) > 0 and len(neg) > 0) else 99.0
        eq_rets = sub.groupby('buy_date')['net_ret'].mean().values
        eq_nav = float(np.prod(1.0 + eq_rets))
        excess = (nav - 1.0) * 100.0 - csi_r
        res[p_name] = {
            'trades': n,
            'wr': round(wr, 1),
            'plr': round(plr, 2),
            'nav': round(nav, 3),
            'eq_nav': round(eq_nav, 3),
            'mdd': round(mdd * 100.0, 1),
            'csi_ret': round(csi_r, 2),
            'excess': round(excess, 1)
        }
    return res

# 运行 5 套核心配置
# 1. 裸五板卡异动
raw_single = run_single_slot(tdf[['buy_date', 'exit_date', 'code', 'name', 'net_ret', 'exit_at_open']].assign(source='raw'))
d15_raw = calc_d15(raw_single)

# 2. 纯首阴 V5.1
d15_yin = calc_d15(yin_std)

# 3. 纯前视镜黄金期五板卡异动
single_5b = run_single_slot(b5_std)
d15_5b = calc_d15(single_5b)

# 4. 双引擎合一 (首阴优先)
combined_pool = pd.concat([yin_std, b5_std], ignore_index=True)
syn_yin_first = run_single_slot(combined_pool, "yin_first")
d15_syn_yin = calc_d15(syn_yin_first)

# 5. 双引擎合一 (五板优先)
syn_5b_first = run_single_slot(combined_pool, "5b_first")
d15_syn_5b = calc_d15(syn_5b_first)

# 保存 JSON 总结
final_summary = {
    "裸五板卡异动基准 (常年裸奔)": d15_raw,
    "纯高标首阴 V5.1 基准 (42笔)": d15_yin,
    "纯前视镜黄金期五板卡异动 (51笔)": d15_5b,
    "黄金期双引擎合一_首阴优先 (90笔)": d15_syn_yin,
    "黄金期双引擎合一_五板优先 (89笔)": d15_syn_5b,
}

with open(f"{OUT_DIR}/sub3_5board_golden_summary.json", "w", encoding="utf-8") as f:
    json.dump(final_summary, f, ensure_ascii=False, indent=2)

print("Saved sub3_5board_golden_summary.json successfully.")
