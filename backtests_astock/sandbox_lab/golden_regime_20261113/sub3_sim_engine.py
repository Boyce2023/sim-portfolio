import os, sys, pickle, time, json
import numpy as np
import pandas as pd

SANDBOX = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab"
OUT_DIR = f"{SANDBOX}/golden_regime_20261113"
FEE_RATE = 0.0020

# 加载 Part1 Cache
print("[Load Cache] Loading part1_cache.pkl...")
t0 = time.time()
with open(f"{SANDBOX}/high_dragon_scorecard_20261113/part1_cache.pkl", "rb") as f:
    (all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(f)
print(f"[Load Cache] Loaded in {time.time()-t0:.2f}s.")

df_all = pd.read_parquet(f"{SANDBOX}/grand_factor_matrix_20261112/cand_high_dragon.parquet")
print(f"[Load Cands] Total high_dragon candidates: {len(df_all):,}")

def get_yidong_price_limit(bars, curr_p, imap, dev_headroom_discount=0.07):
    """
    计算在 curr_p 日，股票价格达到 10日累计偏离 (100% - discount) 或 30日累计偏离 (200% - discount) 的门槛价
    """
    cd = bars['dts'][curr_p]
    ir = imap.get(cd)
    if not ir:
        return 99999.0
    
    bp = 99999.0
    # 10日偏离线
    for k in range(1, min(11, curr_p + 1)):
        p = curr_p - k
        bi = imap.get(bars['dts'][p])
        bc = bars['close'][p]
        if bi and bc > 0:
            idx_chg = ir / bi - 1.0
            p_line = bc * (1.0 + (1.0 - dev_headroom_discount) + idx_chg)
            if p_line < bp:
                bp = p_line

    # 30日偏离线
    for k in range(1, min(31, curr_p + 1)):
        p = curr_p - k
        bi = imap.get(bars['dts'][p])
        bc = bars['close'][p]
        if bi and bc > 0:
            idx_chg = ir / bi - 1.0
            p_line = bc * (1.0 + (2.0 - dev_headroom_discount) + idx_chg)
            if p_line < bp:
                bp = p_line

    return bp

def simulate_card_yidong_trade(c6, buy_date, bars, imap, buy_price_type="open", dev_headroom_discount=0.07, max_hold_days=5):
    """
    模拟单笔高标接力「卡异动」交易:
    - 买入: 在 buy_date 开盘买入 (需非一字涨停开盘)
    - T+1 锁仓，从 T+1 起:
      * 每日检查该日涨停价是否超过卡异动红线 (get_yidong_price_limit)
      * 若开盘价 >= 门槛价: 竞价直接止盈卖出 (exit_at_open=True)
      * 若盘中最高价 >= 门槛价: 盘中在门槛价止盈卖出 (exit_at_open=False)
      * 若未触碰门槛价:
        - 若封死涨停: 继续锁仓持有
        - 若未封涨停 (断板): 收盘卖出 (遇跌停则顺延至开板日卖出)
    """
    if buy_date not in bars['p']:
        return None
    pos = bars['p'][buy_date]
    n = len(bars['dts'])
    
    b_open = float(bars['open'][pos])
    zt_px = float(bars['zt_px'][pos])
    pre_c = float(bars['pre_c'][pos])
    
    # 必须可买 (非一字涨停且开盘价有效)
    if b_open <= 0 or b_open >= zt_px - 0.01:
        return None
        
    buy_px = b_open
    
    exit_p = None
    exit_px = None
    exit_at_open = False
    
    # T+1 起逐日跟踪
    for step in range(1, max_hold_days + 1):
        p = pos + step
        if p >= n:
            p = n - 1
            exit_p = p
            exit_px = float(bars['close'][p])
            exit_at_open = False
            break
            
        plimit = get_yidong_price_limit(bars, p, imap, dev_headroom_discount)
        cur_open = float(bars['open'][p])
        cur_high = float(bars['high'][p])
        cur_close = float(bars['close'][p])
        
        # 1. 开盘即触及或越过卡异动线
        if cur_open >= plimit:
            exit_p = p
            exit_px = cur_open
            exit_at_open = True
            break
            
        # 2. 盘中触及卡异动线
        if cur_high >= plimit:
            exit_p = p
            exit_px = plimit
            exit_at_open = False
            break
            
        # 3. 未触碰异动线，检查是否封涨停
        if not bars['is_zt'][p]:
            # 断板: 收盘卖出。若一字跌停则顺延至开板日
            while p < n - 1 and bars['is_yizi_dt'][p]:
                p += 1
            exit_p = p
            exit_px = float(bars['close'][p])
            exit_at_open = False
            break
        else:
            # 封涨停，继续持有到下一日
            continue
            
    if exit_p is None:
        p = min(pos + max_hold_days, n - 1)
        exit_p = p
        exit_px = float(bars['close'][p])
        exit_at_open = False
        
    adj_buy = buy_px * bars['adjf'][pos]
    adj_exit = exit_px * bars['adjf'][exit_p]
    net_ret = (adj_exit / adj_buy) * (1.0 - FEE_RATE) - 1.0
    
    return {
        'buy_date': buy_date,
        'exit_date': bars['dts'][exit_p],
        'code': c6,
        'buy_px': buy_px,
        'exit_px': exit_px,
        'net_ret': float(net_ret),
        'hold_bars': exit_p - pos,
        'exit_at_open': exit_at_open
    }

print("Sim engine ready.")
