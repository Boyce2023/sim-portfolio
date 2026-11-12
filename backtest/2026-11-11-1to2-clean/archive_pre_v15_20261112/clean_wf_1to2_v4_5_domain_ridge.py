#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v4_5_domain_ridge.py
--------------------------------------------------------------------------------
1to2 V4.5 Domain-Trained Ridge Engine & Production Optimizer
1. 样本域严格对齐（Domain Convergence）：
   - 彻底修复 V4.4 在全市场（包含 -10% 到 +9.8% 所有首板及「其他」独苗股）上训练导致的
     开盘斜率失真（无脑偏好 +7.3% 挤压 +3.5%）。
   - 将 Ridge 训练样本域（Domain）严格收敛到真实候选域：
     is_domain = (fb['plate'] != '其他') & (fb['plate_d2_cnt'] >= 2) &
                 (fb['d2_o_pct'] >= 0.015) & (fb['d2_o_pct'] <= 0.075) &
                 (fb['theme_d2_peer_open_mean'] >= -0.01)
2. 引入两个纯事前微观结构特征：
   - theme_focus_2_6: ((plate_d2_cnt >= 2) & (plate_d2_cnt <= 6)).astype(float)
     （聚焦型板块梯队，区分 2~6 只精锐板块与 >7 只大锅饭分散行情）
   - turn_sweet: ((turn_pct >= 3.0) & (turn_pct <= 16.0)).astype(float) - (turn_pct > 22.0).astype(float)
     （首板换手率舒适区，奖励 3%~16% 充分换手，惩罚 >22% 死亡换手烂板）
3. 保持 V4.4 全部零未来函数 T+1 撮合与风控逻辑：
   - 跨题材多板块真龙头架构（Multi-Sector Leader Architecture）
   - 日内高开瀑布防御机制（TouchProtect）
   - 严格 expanding walk-forward（2022 至 2026，train < Y）
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
import warnings
warnings.filterwarnings('ignore')

CSI300_ANNUAL_RETURNS = {
    2022: -0.2163,
    2023: -0.1138,
    2024: +0.1468,
    2025: -0.0350,
    2026: +0.0120
}

DATA_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
RESULTS_JSON = os.path.join(DATA_DIR, "clean_wf_1to2_v4_5_domain_ridge_results.json")
TRADES_CSV = os.path.join(DATA_DIR, "clean_wf_1to2_v4_5_domain_ridge_ledger.csv")
COMPARISON_JSON = os.path.join(DATA_DIR, "clean_wf_1to2_v4_4_vs_v4_5_comparison.json")

sys.path.insert(0, DATA_DIR)
from clean_wf_1to2_v4_3_master import load_kpl_and_notices, load_price_data, build_feature_matrix_v4_3, simulate_portfolio_slots

def simulate_trade_v4_5(candidate_row, price_lookup, all_trade_dates, date_to_idx, exit_mode="P2", regime_mode="AllWeather", use_touch_order=True):
    code = candidate_row['code6']
    d2_str = candidate_row['d2_date_str']
    idx_d2 = date_to_idx.get(d2_str)
    if idx_d2 is None:
        return None
        
    d2_info = price_lookup.get((code, d2_str))
    if not d2_info:
        return None
    d2_open, d2_high, d2_low, d2_close, d2_adj, d2_zt, d2_dt, d2_is_zt, d2_is_yizi_dt = d2_info
    
    d2_o_pct = candidate_row['d2_o_pct']
    if not (0.015 <= d2_o_pct <= 0.075):
        return None
    if candidate_row['plate'] == "其他" or candidate_row['plate_d2_cnt'] < 2 or candidate_row['theme_d2_peer_open_mean'] < -0.01:
        return None
        
    # Regime Filter
    if regime_mode == "GoldenRegime":
        if candidate_row['plate_past5d_2b_premium'] <= -0.005 or candidate_row['theme_d2_peer_open_mean'] < 0.005:
            return None
    elif regime_mode == "RegimeSafe":
        if candidate_row['plate_past5d_2b_premium'] < -0.02 or candidate_row['mkt_d2_fb_open_mean'] < -0.015:
            return None
            
    # Entry Execution
    if not use_touch_order or d2_o_pct <= 0.050 or candidate_row['theme_d2_peer_open_mean'] >= 0.020:
        buy_price = d2_open
    else:
        if d2_high >= d2_zt - 0.01:
            buy_price = d2_zt
        else:
            return None # Avoided waterfall drop
            
    sealed_2b = 1 if d2_is_zt else 0
    exit_price = None
    exit_date = None
    exit_at_open = True
    
    curr_idx = idx_d2 + 1
    prev_close = d2_close
    
    if not d2_is_zt:
        # D2 failed to seal: exit at D3 09:25 open
        while curr_idx < len(all_trade_dates):
            d_curr = all_trade_dates[curr_idx]
            info = price_lookup.get((code, d_curr))
            if not info:
                exit_price = d2_close
                exit_date = d_curr
                exit_at_open = False
                break
            o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
            if is_yizi_dt:
                curr_idx += 1
                prev_close = c
                continue
            else:
                exit_price = o
                exit_date = d_curr
                exit_at_open = True
                break
    else:
        # D2 sealed limit-up!
        while curr_idx < len(all_trade_dates):
            d_curr = all_trade_dates[curr_idx]
            info = price_lookup.get((code, d_curr))
            if not info:
                exit_price = prev_close
                exit_date = d_curr
                exit_at_open = False
                break
            o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
            
            if exit_mode == "P1":
                if is_yizi_dt:
                    curr_idx += 1
                    prev_close = c
                    continue
                else:
                    exit_price = o
                    exit_date = d_curr
                    exit_at_open = True
                    break
            else:
                # P2: Limit-up open -> 2% stop-loss order
                if o < zt - 0.01:
                    if is_yizi_dt:
                        curr_idx += 1
                        prev_close = c
                        continue
                    else:
                        exit_price = o
                        exit_date = d_curr
                        exit_at_open = True
                        break
                else:
                    stop_px = round(zt * 0.98, 2)
                    if l <= stop_px:
                        exit_price = stop_px
                        exit_date = d_curr
                        exit_at_open = False
                        break
                    else:
                        prev_close = c
                        curr_idx += 1
                        continue
                        
    if exit_price is None:
        exit_price = prev_close
        exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
        exit_at_open = False
        
    holding_days = max(1, curr_idx - idx_d2)
    gross_ret = exit_price / buy_price - 1.0
    net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0
    
    return {
        'code': code,
        'name': candidate_row['stock_name'],
        'buy_date': d2_str,
        'buy_price': round(float(buy_price), 2),
        'exit_date': exit_date,
        'exit_price': round(float(exit_price), 2),
        'exit_at_open': exit_at_open,
        'holding_days': holding_days,
        'sealed_2b': sealed_2b,
        'gross_ret': round(float(gross_ret), 4),
        'net_ret': round(float(net_ret), 4),
        'plate': candidate_row['plate'],
        'plate_d2_cnt': int(candidate_row['plate_d2_cnt']),
        'theme_d2_peer_open_mean': round(float(candidate_row['theme_d2_peer_open_mean']), 4),
        'has_pos_notice': int(candidate_row['has_pos_notice']),
        'd2_o_pct': round(float(candidate_row['d2_o_pct']), 4),
        'score': round(float(candidate_row.get('model_score', 0.0)), 4),
    }

def run_v4_5_domain_ridge():
    print("=" * 80)
    print(">>> [Phase 1] Loading Clean Data & Building V4.5 Domain-Aligned Feature Matrix...")
    print("=" * 80)
    
    stock_to_plate_info, kpl_daily_plates, plate_daily_counts, neg_notices, pos_notices = load_kpl_and_notices()
    df = load_price_data()
    fb, df = build_feature_matrix_v4_3(df, stock_to_plate_info, kpl_daily_plates, plate_daily_counts, neg_notices, pos_notices)
    
    price_lookup = {}
    for r in df[['code6', 'date_str', 'open', 'high', 'low', 'close', 'adj_close', 'zt_price', 'dt_price', 'is_zt', 'is_yizi_dt']].itertuples(index=False):
        price_lookup[(r.code6, r.date_str)] = (
            r.open, r.high, r.low, r.close, r.adj_close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt
        )
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    
    fb['year'] = pd.to_datetime(fb['d2_date_str']).dt.year
    years = [2022, 2023, 2024, 2025, 2026]
    
    # New V4.5 Features
    fb['theme_focus_2_6'] = ((fb['plate_d2_cnt'] >= 2) & (fb['plate_d2_cnt'] <= 6)).astype(float)
    turn_pct = fb['turn'] * 100.0 if fb['turn'].median() < 1.0 else fb['turn']
    fb['turn_sweet'] = ((turn_pct >= 3.0) & (turn_pct <= 16.0)).astype(float) - (turn_pct > 22.0).astype(float)
    
    features = [
        'theme_zt_cnt_d1', 'theme_burst_ratio', 'theme_is_fresh',
        'theme_d2_peer_open_mean', 'theme_d2_zt_open_cnt', 'plate_past5d_2b_premium',
        'in_theme_open_rank', 'is_true_sector_leader', 'has_pos_notice', 'd1_seal_quality',
        'd2_o_pct', 'd2_o_pct_sq',
        'entity_ratio', 'amplitude', 'vol_ratio', 'turn', 'dd20', 'ret5d', 'mcap_circ',
        'theme_focus_2_6', 'turn_sweet'
    ]
    for col in features:
        fb[col] = fb[col].fillna(0.0)
        
    fb['model_score'] = 0.0
    
    # Domain definition
    is_domain = (
        (fb['plate'] != '其他') & 
        (fb['plate_d2_cnt'] >= 2) & 
        (fb['d2_o_pct'] >= 0.015) & 
        (fb['d2_o_pct'] <= 0.075) & 
        (fb['theme_d2_peer_open_mean'] >= -0.01)
    )
    
    print(f"Total candidates: {len(fb):,}, Domain candidates: {is_domain.sum():,}")
    
    # Train Domain Ridge for each expanding year
    # Test both alpha=10.0 and alpha=20.0
    models_dict = {}
    for alpha_val in [10.0, 20.0]:
        models_dict[alpha_val] = {}
        for test_yr in years:
            train_df = fb[(fb['year'] < test_yr) & is_domain]
            X_train = train_df[features].values
            y_train = train_df['target_win'].values
            
            x_mean = np.mean(X_train, axis=0)
            x_std = np.std(X_train, axis=0) + 1e-6
            X_train_norm = (X_train - x_mean) / x_std
            
            model = Ridge(alpha=alpha_val)
            model.fit(X_train_norm, y_train)
            
            models_dict[alpha_val][test_yr] = (model, x_mean, x_std)
            
    # Combos definition for V4.5
    combos = [
        # (label, name, target_rate, max_daily_sectors, use_touch, exit_mode, regime, alpha)
        ("Combo 1", "V4_5_Core_P2_PureOpen", 45, 1, False, "P2", "AllWeather", 10.0),
        ("Combo 2", "V4_5_Core_P2_TouchProtect", 45, 1, True, "P2", "AllWeather", 10.0),
        ("Combo 3", "V4_5_Core_P2_TouchProtect_A20", 45, 1, True, "P2", "AllWeather", 20.0),
        ("Combo 4", "V4_5_Selected50_P2_MultiSector", 65, 2, False, "P2", "AllWeather", 10.0),
        ("Combo 5", "V4_5_Selected50_P2_TouchProtect", 65, 2, True, "P2", "AllWeather", 10.0),
        ("Combo 6", "V4_5_GoldenRegime_Core_P2", 55, 1, False, "P2", "GoldenRegime", 10.0),
        ("Combo 7", "V4_5_GoldenRegime_Core_TouchProtect", 55, 1, True, "P2", "GoldenRegime", 10.0),
        ("Combo 8", "V4_5_GoldenRegime_Selected50_TouchProtect", 65, 2, True, "P2", "GoldenRegime", 10.0),
    ]
    
    all_results = {}
    all_trades_ledger = []
    
    for combo_label, combo_name, target_rate, max_sectors, use_touch, exit_mode, regime_mode, alpha_val in combos:
        print(f"\n" + "-" * 75)
        print(f"--- Running {combo_label}: {combo_name} (Target: {target_rate}/yr, MaxSectors: {max_sectors}, Touch: {use_touch}, Regime: {regime_mode}, Alpha: {alpha_val}) ---")
        print("-" * 75)
        
        combo_trades = []
        combo_yearly = {}
        
        for test_yr in years:
            model, x_mean, x_std = models_dict[alpha_val][test_yr]
            train_pool = fb[(fb['year'] < test_yr) & is_domain].copy()
            test_pool = fb[fb['year'] == test_yr].copy()
            
            # Compute test pool scores
            X_test = test_pool[features].values
            X_test_norm = (X_test - x_mean) / x_std
            test_pool['model_score'] = model.predict(X_test_norm)
            
            # Compute train cutoff
            X_tr = train_pool[features].values
            X_tr_norm = (X_tr - x_mean) / x_std
            train_scores = model.predict(X_tr_norm)
            
            train_span = max(1.0, (pd.to_datetime(train_pool['d2_date_str'].max()) - pd.to_datetime(train_pool['d2_date_str'].min())).days / 365.25)
            target_train_count = int(target_rate * train_span)
            
            if len(train_scores) > target_train_count:
                cutoff = float(np.percentile(train_scores, 100.0 * (1.0 - target_train_count / len(train_scores))))
            else:
                cutoff = float(np.percentile(train_scores, 80.0))
                
            test_cands = test_pool[test_pool['model_score'] >= cutoff].sort_values(['d2_date_str', 'model_score'], ascending=[True, False])
            
            yr_trades = []
            for d_str, day_group in test_cands.groupby('d2_date_str'):
                seen_plates = set()
                picks_count = 0
                for _, r in day_group.iterrows():
                    p = r['plate']
                    if p in seen_plates:
                        continue
                    seen_plates.add(p)
                    picks_count += 1
                    
                    tr = simulate_trade_v4_5(r, price_lookup, all_trade_dates, date_to_idx, exit_mode=exit_mode, regime_mode=regime_mode, use_touch_order=use_touch)
                    if tr:
                        tr['combo'] = combo_name
                        tr['test_year'] = test_yr
                        yr_trades.append(tr)
                        combo_trades.append(tr)
                        all_trades_ledger.append(tr)
                        
                    if picks_count >= max_sectors:
                        break
                        
            if yr_trades:
                df_yr = pd.DataFrame(yr_trades)
                yr_n = len(df_yr)
                yr_wr = (df_yr['net_ret'] > 0).mean()
                wins = df_yr[df_yr['net_ret'] > 0]['net_ret']
                losses = df_yr[df_yr['net_ret'] <= 0]['net_ret']
                avg_win = wins.mean() if len(wins) > 0 else 0.0
                avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.01
                pnl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
                yr_2b_rate = df_yr['sealed_2b'].mean()
                
                nav_1s, _, _ = simulate_portfolio_slots(yr_trades, num_slots=1)
                nav_2s, _, _ = simulate_portfolio_slots(yr_trades, num_slots=2)
                yr_bench = CSI300_ANNUAL_RETURNS.get(test_yr, 0.0)
                yr_excess = (nav_1s - 1.0) - yr_bench
                
                combo_yearly[test_yr] = {
                    'trades_count': yr_n,
                    'win_rate': round(float(yr_wr), 4),
                    'pnl_ratio': round(float(pnl_ratio), 2),
                    'sealed_2b_rate': round(float(yr_2b_rate), 4),
                    'nav_1slot': round(float(nav_1s), 4),
                    'nav_2slot': round(float(nav_2s), 4),
                    'benchmark_csi300': yr_bench,
                    'excess_1slot': round(float(yr_excess), 4),
                }
                print(f"  {test_yr}: {yr_n:2d} trades | WinRate: {yr_wr*100:4.1f}% | 2B: {yr_2b_rate*100:4.1f}% | PnL: {pnl_ratio:4.2f} | 1-Slot: {nav_1s:6.4f}x (Excess: {yr_excess*100:+6.2f}%) | 2-Slot: {nav_2s:6.4f}x")
            else:
                combo_yearly[test_yr] = {'trades_count': 0}
                print(f"  {test_yr}:  0 trades")
                
        df_combo = pd.DataFrame(combo_trades)
        total_n = len(df_combo)
        if total_n > 0:
            tot_wr = (df_combo['net_ret'] > 0).mean()
            wins = df_combo[df_combo['net_ret'] > 0]['net_ret']
            losses = df_combo[df_combo['net_ret'] <= 0]['net_ret']
            tot_pnl = (wins.mean() / abs(losses.mean())) if len(losses) > 0 and abs(losses.mean()) > 0 else 0.0
            tot_2b = df_combo['sealed_2b'].mean()
            tot_nav_1s, _, _ = simulate_portfolio_slots(combo_trades, num_slots=1)
            tot_nav_2s, _, _ = simulate_portfolio_slots(combo_trades, num_slots=2)
            
            all_results[combo_name] = {
                'total_trades': total_n,
                'annual_trades_avg': round(total_n / 5.0, 1),
                'win_rate': round(float(tot_wr), 4),
                'pnl_ratio': round(float(tot_pnl), 2),
                'sealed_2b_rate': round(float(tot_2b), 4),
                'cum_nav_1slot': round(float(tot_nav_1s), 4),
                'cum_nav_2slot': round(float(tot_nav_2s), 4),
                'yearly': combo_yearly
            }
            print(f"  => 5-Year Total: {total_n} trades ({total_n/5.0:.1f}/yr) | WinRate: {tot_wr*100:4.1f}% | 2B: {tot_2b*100:4.1f}% | PnL: {tot_pnl:4.2f} | 1-Slot NAV: {tot_nav_1s:6.4f}x | 2-Slot NAV: {tot_nav_2s:6.4f}x")

    with open(RESULTS_JSON, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    pd.DataFrame(all_trades_ledger).to_csv(TRADES_CSV, index=False, encoding='utf-8-sig')
    print(f"\nAll V4.5 results saved to: {RESULTS_JSON}")
    print(f"All V4.5 trades ledger saved to: {TRADES_CSV}")
    
    # Load V4.4 results for side-by-side comparison
    v4_4_json_path = os.path.join(DATA_DIR, "clean_wf_1to2_v4_4_ultimate_results.json")
    if os.path.exists(v4_4_json_path):
        with open(v4_4_json_path, 'r', encoding='utf-8') as f:
            v4_4_results = json.load(f)
            
        comparison = {}
        for key in ["Core_P2_PureOpen", "Core_P2_TouchProtect", "Selected50_P2_TouchProtect", "GoldenRegime_Core_TouchProtect"]:
            k4 = f"V4_4_{key}"
            k5 = f"V4_5_{key}"
            if k4 in v4_4_results and k5 in all_results:
                comparison[key] = {
                    'V4.4': v4_4_results[k4],
                    'V4.5': all_results[k5]
                }
        with open(COMPARISON_JSON, 'w', encoding='utf-8') as f:
            json.dump(comparison, f, ensure_ascii=False, indent=2)
        print(f"Comparison saved to: {COMPARISON_JSON}")

if __name__ == '__main__':
    run_v4_5_domain_ridge()
