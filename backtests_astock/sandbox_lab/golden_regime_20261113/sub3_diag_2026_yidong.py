import os, sys, pickle, pandas as pd, numpy as np

SANDBOX = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab"
OUT_DIR = f"{SANDBOX}/golden_regime_20261113"

with open(f"{SANDBOX}/high_dragon_scorecard_20261113/part1_cache.pkl", "rb") as f:
    (all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(f)

df_all = pd.read_parquet(f"{SANDBOX}/grand_factor_matrix_20261112/cand_high_dragon.parquet")

def calc_yidong_headroom(code, dt, bars, imap):
    """
    计算在 dt 这一天，股票收盘若涨停，距离 10日累计偏离100% 和 30日累计偏离200% 的剩余空间
    返回: (min_headroom_pct, is_touch_10d, is_touch_30d, p_limit)
    """
    pos = bars['p'].get(dt)
    if pos is None or pos < 1:
        return 999.0, False, False, 9999.0
    
    cd = bars['dts'][pos]
    ir = imap.get(cd)
    if not ir:
        return 999.0, False, False, 9999.0
        
    zt_px = bars['zt_px'][pos]
    p_limit_10 = 99999.0
    p_limit_30 = 99999.0
    
    # 10日偏离线 (累计达 100%)
    for k in range(1, min(11, pos + 1)):
        p = pos - k
        bi = imap.get(bars['dts'][p])
        bc = bars['close'][p]
        if bi and bc > 0:
            idx_chg = ir / bi - 1.0
            # 股票累计涨幅 - 指数累计涨幅 = 1.00  => P / bc - 1.0 - idx_chg = 1.00 => P = bc * (2.0 + idx_chg)
            target_p = bc * (2.0 + idx_chg)
            if target_p < p_limit_10:
                p_limit_10 = target_p

    # 30日偏离线 (累计达 200%)
    for k in range(1, min(31, pos + 1)):
        p = pos - k
        bi = imap.get(bars['dts'][p])
        bc = bars['close'][p]
        if bi and bc > 0:
            idx_chg = ir / bi - 1.0
            # 股票累计涨幅 - 指数累计涨幅 = 2.00  => P = bc * (3.0 + idx_chg)
            target_p = bc * (3.0 + idx_chg)
            if target_p < p_limit_30:
                p_limit_30 = target_p

    p_limit = min(p_limit_10, p_limit_30)
    # 距离涨停价的余量 (若涨停价已超 target_p，则余量为负)
    headroom = (p_limit / zt_px - 1.0) * 100.0
    return headroom, (zt_px >= p_limit_10), (zt_px >= p_limit_30), p_limit

print("Diagnostic script ready.")
