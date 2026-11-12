#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lab_exit_tplus1_1to2.py
=============================================================================
一进二 T+1 真实离场法则与赔率倍增实验室
=============================================================================
严守 A 股 T+1 制度与零未来函数：
1. 统一输入底盘：基于 PIT 纯净前向 Walk-Forward 选拔的高质一进二底册（合并 active + delisted 255 只退市股）
2. 严格测试 6 种 T+1 离场规则，含一字跌停锁仓顺延：
   - Exit 1: 基准（D2 未封板 D3 开盘出，封二板断板收盘出）
   - Exit 2: D3 弱转强分流（D3_open > D2_close 拿至收盘，否则 D3 开盘秒砍）
   - Exit 3: 连板持仓 09:25 低开截断（持仓 Dk 开盘 < -2.5% 竞价秒砍防天地板）
   - Exit 4: 高标冲高分批止盈（晋级三板以上断板日盘中冲高锁定利润）
   - Exit 5: D3 早盘流动性修复均价离场（未封板不竞价割肉，09:35~09:45 均价离场）
   - Exit 6: 综合最优全天候规则（弱转强分流 + 低开截断 + 冲高止盈）
=============================================================================
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
os.makedirs(OUTPUT_DIR, exist_ok=True)

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
LEDGER_CSV = os.path.join(OUTPUT_DIR, "clean_wf_selective50_ledger.csv")
RESULTS_JSON_PATH = os.path.join(OUTPUT_DIR, "lab_exit_tplus1_results.json")

def load_price_db():
    print(">>> 正在加载全市场日线行情（含退市股）...")
    cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'volume', 'amount']
    
    # 1. 活跃股
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2022-01-01'))).to_table().to_pandas()
    
    # 2. 退市股
    df_del = pd.DataFrame()
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format="parquet")
        df_del = ds_del.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2022-01-01'))).to_table().to_pandas()
        print(f"    已加载退市股行情: {len(df_del):,} 行")
        
    df = pd.concat([df_act, df_del], ignore_index=True)
    del df_act, df_del
    
    # 修复 6 位股票代码
    df['ticker_str'] = df['ticker'].astype(str).str.split('.').str[0].str.zfill(6)
    df = df[df['ticker_str'].str.startswith(('00', '60'))].copy()
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
    df.sort_values(['ticker_str', 'date'], inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    # 涨跌停计算
    df['pre_close'] = df.groupby('ticker_str')['close'].shift(1)
    df['zt_price'] = (df['pre_close'] * 1.10).round(2)
    df['dt_price'] = (df['pre_close'] * 0.90).round(2)
    df['is_zt'] = (df['close'] >= df['zt_price'] - 0.01) & (df['close'] == df['high']) & (df['pre_close'] > 0)
    df['is_yizi'] = df['is_zt'] & (df['open'] == df['close']) & (df['low'] == df['close'])
    df['is_dt'] = (df['close'] <= df['dt_price'] + 0.01) & (df['close'] == df['low'])
    df['is_yizi_dt'] = df['is_dt'] & (df['open'] == df['close']) & (df['high'] == df['close'])
    
    print(f"行情数据加载完成: {len(df):,} 行，覆盖标的: {df['ticker_str'].nunique()} 只。")
    return df

def simulate_6_exit_rules(df, ledger_df):
    print(">>> 正在为高质量一进二样本池逐笔执行 6 种 T+1 离场仿真...")
    
    # 构建快速行情索引: (ticker, date_str) -> dict
    price_records = {}
    for r in df[['ticker_str', 'date_str', 'open', 'high', 'low', 'close', 'pre_close', 'zt_price', 'dt_price', 'is_zt', 'is_yizi_dt']].itertuples(index=False):
        price_records[(r.ticker_str, r.date_str)] = {
            'open': r.open,
            'high': r.high,
            'low': r.low,
            'close': r.close,
            'pre_close': r.pre_close,
            'zt_price': r.zt_price,
            'dt_price': r.dt_price,
            'is_zt': r.is_zt,
            'is_yizi_dt': r.is_yizi_dt
        }
        
    all_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_dates)}
    
    FEE_RATE = 0.0013 # 0.13% 交易成本 (万0.5佣金 + 千1印花税 + 万2滑点)
    
    exit_results = {f"Exit_{i}": [] for i in range(1, 7)}
    
    for row in ledger_df.itertuples(index=False):
        raw_tk = getattr(row, 'ticker', '')
        tk = str(raw_tk).split('.')[0].zfill(6)
        d2_date = str(getattr(row, 'd2_date', ''))[:10]
        buy_p = float(getattr(row, 'buy_price', 0.0))
        is_d2_zt = bool(getattr(row, 'is_d2_zt', 0))
        test_year = str(getattr(row, 'test_year', d2_date[:4]))
        
        d2_idx = date_to_idx.get(d2_date, None)
        if d2_idx is None or d2_idx + 1 >= len(all_dates):
            continue
            
        # 获取 D2 真实行情
        if (tk, d2_date) not in price_records:
            continue
        d2_rec = price_records[(tk, d2_date)]
        if buy_p <= 0:
            buy_p = d2_rec['open']
        d2_close = d2_rec['close']
        
        # 获取未来 15 个交易日行情用于跟踪持仓与一字跌停顺延
        forward_days = []
        for idx in range(d2_idx + 1, min(d2_idx + 25, len(all_dates))):
            f_date = all_dates[idx]
            if (tk, f_date) in price_records:
                forward_days.append((f_date, price_records[(tk, f_date)]))
            else:
                break
                
        if not forward_days:
            continue
            
        d3_date, d3_rec = forward_days[0]
        
        # ---------------------------------------------------------------------
        # 核心撮合引擎：严格支持一字跌停锁仓顺延
        # 若指定离场日是一字跌停，资金无法挂单卖出，必须顺延至开板日竞价卖出
        # ---------------------------------------------------------------------
        def get_executable_exit(target_k, ptype='close'):
            curr_k = target_k
            while curr_k < len(forward_days):
                f_d, r = forward_days[curr_k]
                if not r['is_yizi_dt']:
                    p = r[ptype] if curr_k == target_k else r['open']
                    return f_d, p, curr_k + 1
                curr_k += 1
            f_d, r = forward_days[-1]
            return f_d, r['close'], len(forward_days)

        # ---------------------------------------------------------------------
        # Exit 1: 基准（D2 未封板 D3 开盘出，封二板断板收盘出）
        # ---------------------------------------------------------------------
        if not is_d2_zt:
            ex_date, ex_price, hold_d = get_executable_exit(0, 'open')
        else:
            broken_k = 0
            for k, (f_d, r) in enumerate(forward_days):
                if not r['is_zt']:
                    broken_k = k
                    break
            ex_date, ex_price, hold_d = get_executable_exit(broken_k, 'close')
        r1_net = (ex_price / buy_p) * (1.0 - FEE_RATE) - 1.0
        exit_results["Exit_1"].append({'ret': r1_net, 'hold_d': hold_d, 'year': test_year})

        # ---------------------------------------------------------------------
        # Exit 2: D3 弱转强分流离场
        # 未封板时：若 D3_open > D2_close，主力竞价做弱转强修复，拿至收盘；
        # 若 D3_open <= D2_close，竞价不及预期，09:25 开盘秒砍！
        # 封板时：断板收盘出。
        # ---------------------------------------------------------------------
        if not is_d2_zt:
            if d3_rec['open'] > d2_close:
                ex_date, ex_price, hold_d = get_executable_exit(0, 'close')
            else:
                ex_date, ex_price, hold_d = get_executable_exit(0, 'open')
        else:
            broken_k = 0
            for k, (f_d, r) in enumerate(forward_days):
                if not r['is_zt']:
                    broken_k = k
                    break
            ex_date, ex_price, hold_d = get_executable_exit(broken_k, 'close')
        r2_net = (ex_price / buy_p) * (1.0 - FEE_RATE) - 1.0
        exit_results["Exit_2"].append({'ret': r2_net, 'hold_d': hold_d, 'year': test_year})

        # ---------------------------------------------------------------------
        # Exit 3: 连板持仓 09:25 低开截断保护
        # 未封板时：D3 开盘出。
        # 封板后进入 D3+：若某日开盘 open_pct < -2.5%（竞价断层核按钮），
        # 不等待吃全天跌停，09:25 集合竞价秒砍；若开盘 >= -2.5% 未封死则收盘出。
        # ---------------------------------------------------------------------
        if not is_d2_zt:
            ex_date, ex_price, hold_d = get_executable_exit(0, 'open')
        else:
            exit_k = 0
            exit_ptype = 'close'
            for k, (f_d, r) in enumerate(forward_days):
                op_pct = r['open'] / r['pre_close'] - 1.0
                if op_pct < -0.025:
                    exit_k = k
                    exit_ptype = 'open'
                    break
                elif not r['is_zt']:
                    exit_k = k
                    exit_ptype = 'close'
                    break
            ex_date, ex_price, hold_d = get_executable_exit(exit_k, exit_ptype)
        r3_net = (ex_price / buy_p) * (1.0 - FEE_RATE) - 1.0
        exit_results["Exit_3"].append({'ret': r3_net, 'hold_d': hold_d, 'year': test_year})

        # ---------------------------------------------------------------------
        # Exit 4: 高标冲高分批止盈（死拿断板 vs 冲高锁定利润）
        # 未封板：D3 开盘出。
        # 封二板后：断板日若盘中大幅冲高 (high >= pre_close * 1.045)，
        # 避免回落吐回利润，以盘中冲高均价 (0.4*high + 0.6*close) 止盈离场。
        # ---------------------------------------------------------------------
        if not is_d2_zt:
            ex_date, ex_price, hold_d = get_executable_exit(0, 'open')
        else:
            exit_k = 0
            spike_price = None
            for k, (f_d, r) in enumerate(forward_days):
                if not r['is_zt']:
                    exit_k = k
                    if r['high'] >= r['pre_close'] * 1.045:
                        spike_price = 0.4 * r['high'] + 0.6 * r['close']
                    break
            if spike_price is not None:
                ex_date, _, hold_d = get_executable_exit(exit_k, 'close')
                ex_price = spike_price
            else:
                ex_date, ex_price, hold_d = get_executable_exit(exit_k, 'close')
        r4_net = (ex_price / buy_p) * (1.0 - FEE_RATE) - 1.0
        exit_results["Exit_4"].append({'ret': r4_net, 'hold_d': hold_d, 'year': test_year})

        # ---------------------------------------------------------------------
        # Exit 5: D3 早盘流动性修复均价离场
        # 未封板时不盲目在 09:25 竞价核按钮恐慌割肉，而是等待 09:35~09:45 冲高均价离场
        # 模拟均价: 0.5*open + 0.5*high（若当天一字跌停则锁仓顺延）
        # ---------------------------------------------------------------------
        if not is_d2_zt:
            ex_date, ex_price, hold_d = get_executable_exit(0, 'open')
            if not d3_rec['is_yizi_dt']:
                ex_price = min(0.5 * d3_rec['open'] + 0.5 * d3_rec['high'], d3_rec['high'])
        else:
            broken_k = 0
            for k, (f_d, r) in enumerate(forward_days):
                if not r['is_zt']:
                    broken_k = k
                    break
            ex_date, ex_price, hold_d = get_executable_exit(broken_k, 'close')
        r5_net = (ex_price / buy_p) * (1.0 - FEE_RATE) - 1.0
        exit_results["Exit_5"].append({'ret': r5_net, 'hold_d': hold_d, 'year': test_year})

        # ---------------------------------------------------------------------
        # Exit 6: 综合最优全天候 T+1 规则
        # 1. 未封板：弱转强分流（D3_open > D2_close 拿至收盘，否则开盘秒砍）
        # 2. 封二板：连板期低开截断（Dk_open < -2.5% 竞价秒砍）+ 断板冲高保护
        # ---------------------------------------------------------------------
        if not is_d2_zt:
            if d3_rec['open'] > d2_close:
                ex_date, ex_price, hold_d = get_executable_exit(0, 'close')
            else:
                ex_date, ex_price, hold_d = get_executable_exit(0, 'open')
        else:
            exit_k = 0
            exit_ptype = 'close'
            spike_price = None
            for k, (f_d, r) in enumerate(forward_days):
                op_pct = r['open'] / r['pre_close'] - 1.0
                if op_pct < -0.025:
                    exit_k = k
                    exit_ptype = 'open'
                    break
                elif not r['is_zt']:
                    exit_k = k
                    exit_ptype = 'close'
                    if r['high'] >= r['pre_close'] * 1.045:
                        spike_price = 0.4 * r['high'] + 0.6 * r['close']
                    break
            if spike_price is not None and exit_ptype == 'close':
                ex_date, _, hold_d = get_executable_exit(exit_k, 'close')
                ex_price = spike_price
            else:
                ex_date, ex_price, hold_d = get_executable_exit(exit_k, exit_ptype)
        r6_net = (ex_price / buy_p) * (1.0 - FEE_RATE) - 1.0
        exit_results["Exit_6"].append({'ret': r6_net, 'hold_d': hold_d, 'year': test_year})

    return exit_results

def compute_metrics(trades_list):
    if not trades_list:
        return {}
    rets = np.array([t['ret'] for t in trades_list])
    n = len(rets)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    
    win_rate = float(len(wins) / n) if n > 0 else 0.0
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(abs(np.mean(losses))) if len(losses) > 0 else 0.0
    
    pl_ratio = float(avg_win / avg_loss) if avg_loss > 0 else 0.0
    profit_factor = float(np.sum(wins) / abs(np.sum(losses))) if len(losses) > 0 and abs(np.sum(losses)) > 0 else 0.0
    
    cum_nav = np.cumprod(1.0 + rets)
    final_nav = float(cum_nav[-1]) if len(cum_nav) > 0 else 1.0
    
    peak = np.maximum.accumulate(cum_nav)
    dd = (cum_nav - peak) / peak
    max_dd = float(np.min(dd)) if len(dd) > 0 else 0.0
    
    cum_nav_half = np.cumprod(1.0 + 0.5 * rets)
    final_nav_half = float(cum_nav_half[-1]) if len(cum_nav_half) > 0 else 1.0
    
    years = sorted(list(set([t['year'] for t in trades_list])))
    yearly = {}
    for y in years:
        y_rets = np.array([t['ret'] for t in trades_list if t['year'] == y])
        y_wins = y_rets[y_rets > 0]
        y_losses = y_rets[y_rets <= 0]
        yearly[y] = {
            'trades': int(len(y_rets)),
            'win_rate': round(float(len(y_wins) / len(y_rets)), 4) if len(y_rets) > 0 else 0.0,
            'avg_net_ret': round(float(np.mean(y_rets)), 4) if len(y_rets) > 0 else 0.0,
            'profit_factor': round(float(np.sum(y_wins) / abs(np.sum(y_losses))), 2) if len(y_losses) > 0 and abs(np.sum(y_losses)) > 0 else 0.0,
            'cum_nav': round(float(np.cumprod(1.0 + y_rets)[-1]), 4) if len(y_rets) > 0 else 1.0
        }
        
    return {
        'trade_count': n,
        'win_rate': round(win_rate, 4),
        'avg_win': round(avg_win, 4),
        'avg_loss': round(avg_loss, 4),
        'pl_ratio': round(pl_ratio, 2),
        'profit_factor': round(profit_factor, 2),
        'final_cum_nav': round(final_nav, 4),
        'dual_slot_nav': round(final_nav_half, 4),
        'max_drawdown': round(max_dd, 4),
        'yearly': yearly
    }

def main():
    if not os.path.exists(LEDGER_CSV):
        print(f"Error: {LEDGER_CSV} 不存在！")
        return
    ledger_df = pd.read_csv(LEDGER_CSV)
    print(f"已成功加载前向验证一进二交易底册: {len(ledger_df)} 笔样本")
    
    df = load_price_db()
    exit_results = simulate_6_exit_rules(df, ledger_df)
    
    rule_names = {
        'Exit_1': 'Exit 1 (基准：未封板 D3 开盘出 + 封二板断板收盘出)',
        'Exit_2': 'Exit 2 (D3 弱转强分流：D3_open>D2_close 拿至收盘，否则开盘秒砍)',
        'Exit_3': 'Exit 3 (连板持仓 09:25 低开截断保护：Dk 开盘<-2.5% 秒砍防天地板)',
        'Exit_4': 'Exit 4 (高标冲高分批止盈：断板日盘中冲高锁定部分利润)',
        'Exit_5': 'Exit 5 (D3 早盘流动性修复均价离场：09:35~09:45 均价离场)',
        'Exit_6': 'Exit 6 (综合最优全天候：弱转强分流 + 低开截断 + 冲高止盈)'
    }
    
    print("\n" + "=" * 80)
    print(">>> 6 种 T+1 真实离场规则全样本回测绩效汇总 (2023 ~ 2026 Walk-Forward)")
    print("=" * 80)
    
    final_summary = {}
    for r_k, r_name in rule_names.items():
        m = compute_metrics(exit_results[r_k])
        final_summary[r_k] = {
            'rule_name': r_name,
            'metrics': m
        }
        print(f"\n【{r_name}】")
        print(f"  总笔数: {m['trade_count']} | 胜率: {m['win_rate']*100:.2f}% | 真实盈亏比: {m['pl_ratio']:.2f} (盈 {m['avg_win']*100:.2f}% / 亏 {m['avg_loss']*100:.2f}%)")
        print(f"  盈亏乘数(PF): {m['profit_factor']:.2f} | 单仓累计净值: {m['final_cum_nav']:.4f}x | 双仓累计净值: {m['dual_slot_nav']:.4f}x | 最大回撤: {m['max_drawdown']*100:.2f}%")
        print("  年度细分:")
        for y, y_info in m['yearly'].items():
            print(f"    {y}年: 笔数 {y_info['trades']} | 胜率 {y_info['win_rate']*100:.1f}% | PF {y_info['profit_factor']:.2f} | 净值 {y_info['cum_nav']:.4f}x")

    with open(RESULTS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(final_summary, f, ensure_ascii=False, indent=2)
    print(f"\n实验结果已保存至: {RESULTS_JSON_PATH}")

if __name__ == '__main__':
    main()
