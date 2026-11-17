import json
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd011_v4_100factors_20261116"
GRAND_PARQUET = f"{OUT_DIR}/grand_cross_year_120factors.parquet"

df = pd.read_parquet(GRAND_PARQUET)

# Factor Scorecard V4.0 Formula
# Base score 0
score = np.zeros(len(df))

# 1. Double abnormal movement headroom (IC = +0.25)
score += np.clip(df['tight_headroom'] * 50.0, 0.0, 25.0)
score += np.where(df['is_detour_10d'] == 1, 15.0, 0.0)
score += np.clip(df['days_since_last_ord_abn'] * 1.5, 0.0, 15.0)
score -= np.where(df['tight_headroom'] < 0.05, 35.0, 0.0) # barrier death trap
score -= np.where(df['dev_10d'] > 0.70, 20.0, 0.0)
score -= np.where(df['dev_30d'] > 1.85, 25.0, 0.0)

# 2. Policy & Geopolitics burst (IC = +0.08)
score += np.clip(df['pol_ministry_burst_15d'] * 4.0, 0.0, 15.0)
score += np.clip(df['pol_geopolitics_burst_15d'] * 3.5, 0.0, 12.0)
score += np.where(df['pol_macro_central_meeting'] == 1, 5.0, 0.0)

# 3. Theme status & Midfielder (IC = +0.07)
score += np.where(df['theme_is_top1_10d'] == 1, 15.0, np.where(df['theme_is_top2_10d'] == 1, 8.0, 0.0))
score += np.where(df['theme_has_100yi_midfielder'] == 1, 12.0, 0.0)
score += np.where(df['theme_is_fresh_q4_new'] == 1, 8.0, 0.0)
score -= np.where((df['theme_is_top1_10d'] == 0) & (df['theme_is_top2_10d'] == 0), 20.0, 0.0)

# 4. Non-M&A fundamental & business catalyst (IC = +0.07)
score += np.where(df['has_major_contract_45d'] == 1, 10.0, 0.0)
score += np.where(df['has_strategic_coop_45d'] == 1, 8.0, 0.0)
score += np.where(df['has_new_sub_or_cap_60d'] == 1, 8.0, 0.0)
score += np.where(df['q3_pre_profit_up'] == 1, 10.0, 0.0)
score += np.where(df['q3_turnaround'] == 1, 12.0, 0.0)
score += np.where(df['is_soe_flagship'] == 1, 10.0, 0.0)
score -= np.where(df['q3_severe_loss'] == 1, 15.0, 0.0)
score -= np.where(df['has_reg_letter_15d'] == 1, 25.0, 0.0)
score -= np.where(df['has_shareholder_reduce_60d'] == 1, 20.0, 0.0)

# 5. Stealth & microstructure
score += np.where(df['comm_is_stealth_start'] == 1, 10.0, 0.0)
score += np.where(df['is_ir_unpopular_90d'] == 1, 6.0, 0.0)
score += np.where(df['close_px'] <= 15.0, 6.0, 0.0)
score += np.where(df['name_matches_theme_or_map'] == 1, 6.0, 0.0)
score -= np.where(df['comm_guba_frenzy_3d'] >= 20, 15.0, 0.0)
score -= np.where(df['is_csrc_outsider'] == 1, 15.0, 0.0)
score -= np.where(df['zt_streak'] >= 4, 15.0, 0.0)

df['v4_score'] = np.round(score, 1)

# Check simulation
def run_d15_eval(sub_pool, min_score, tier_label):
    print(f"\n==================== {tier_label} (V4 Score >= {min_score}) ====================")
    qualified = sub_pool[sub_pool['v4_score'] >= min_score].copy()
    qualified.sort_values(['sig_dt', 'v4_score'], ascending=[True, False], inplace=True)
    
    results = {}
    periods = [
        ('全5年（2021~2026）', ['2021/22', '2022/23', '2023/24', '2024/25', '2025/26']),
        ('近3年（2023~2026）', ['2023/24', '2024/25', '2025/26']),
        ('去年季（2025/26）', ['2025/26']),
        ('前3季样本内（2021~2024）', ['2021/22', '2022/23', '2023/24']),
        ('后2季样本外（2024~2026）', ['2024/25', '2025/26']),
    ]
    
    for p_label, s_list in periods:
        p_df = qualified[qualified['season'].isin(s_list)].copy()
        n_trades = len(p_df)
        if n_trades == 0:
            results[p_label] = {'trades': 0}
            continue
            
        daily_ret = p_df.groupby('buy_dt')['ret_smart_dev30_ma10'].mean()
        daily_hs = p_df.groupby('buy_dt')['hs300_ret_smart'].mean()
        eq_win_rate = float((daily_ret > 0).mean())
        eq_mean_ret = float(daily_ret.mean())
        eq_cum_ret = float(np.prod(1.0 + daily_ret) - 1.0)
        eq_cum_hs = float(np.prod(1.0 + daily_hs) - 1.0)
        eq_excess = eq_cum_ret - eq_cum_hs
        
        nv = np.cumprod(1.0 + daily_ret.values)
        peak = np.maximum.accumulate(nv)
        dd = (peak - nv) / peak
        eq_max_dd = float(dd.max()) if len(dd) > 0 else 0.0
        
        # Single slot rotation
        slot_trades = []
        free_date = '1990-01-01'
        for dt, grp in p_df.groupby('sig_dt'):
            buy_dt = grp['buy_dt'].iloc[0]
            if buy_dt >= free_date:
                best_pick = grp.iloc[0]
                hold_d = 14 if best_pick['ret_smart_dev30_ma10'] > 0 else 5
                exit_dt = (pd.to_datetime(buy_dt) + pd.Timedelta(days=hold_d * 1.4)).strftime('%Y-%m-%d')
                free_date = exit_dt
                slot_trades.append(best_pick)
                
        df_slot = pd.DataFrame(slot_trades) if slot_trades else pd.DataFrame()
        if len(df_slot) > 0:
            s_trades = len(df_slot)
            s_win_rate = float((df_slot['ret_smart_dev30_ma10'] > 0).mean())
            pos_t = df_slot['ret_smart_dev30_ma10'][df_slot['ret_smart_dev30_ma10'] > 0]
            neg_t = df_slot['ret_smart_dev30_ma10'][df_slot['ret_smart_dev30_ma10'] < 0]
            s_plr = float(abs(pos_t.mean() / neg_t.mean())) if len(pos_t)>0 and len(neg_t)>0 and neg_t.mean()!=0 else 1.0
            s_avg_ret = float(df_slot['ret_smart_dev30_ma10'].mean())
            s_cum_ret = float(np.prod(1.0 + df_slot['ret_smart_dev30_ma10']) - 1.0)
            s_cum_hs = float(np.prod(1.0 + df_slot['hs300_ret_smart']) - 1.0)
            s_excess = s_cum_ret - s_cum_hs
            
            nv_s = np.cumprod(1.0 + df_slot['ret_smart_dev30_ma10'].values)
            peak_s = np.maximum.accumulate(nv_s)
            dd_s = (peak_s - nv_s) / peak_s
            s_max_dd = float(dd_s.max()) if len(dd_s) > 0 else 0.0
        else:
            s_trades, s_win_rate, s_plr, s_avg_ret = 0, 0.0, 1.0, 0.0
            s_cum_ret, s_cum_hs, s_excess, s_max_dd = 0.0, 0.0, 0.0, 0.0

        results[p_label] = {
            'equal_weight': {
                'trades': n_trades,
                'win_rate': round(eq_win_rate * 100, 1),
                'mean_return_pct': round(eq_mean_ret * 100, 2),
                'cum_net_value': round(eq_cum_ret + 1.0, 2),
                'cum_return_pct': round(eq_cum_ret * 100, 1),
                'hs300_return_pct': round(eq_cum_hs * 100, 1),
                'net_excess_pct': round(eq_excess * 100, 1),
                'max_drawdown_pct': round(eq_max_dd * 100, 1),
            },
            'single_slot': {
                'trades': s_trades,
                'win_rate': round(s_win_rate * 100, 1),
                'plr': round(s_plr, 2),
                'mean_return_pct': round(s_avg_ret * 100, 2),
                'cum_net_value': round(s_cum_ret + 1.0, 2),
                'cum_return_pct': round(s_cum_ret * 100, 1),
                'hs300_return_pct': round(s_cum_hs * 100, 1),
                'net_excess_pct': round(s_excess * 100, 1),
                'max_drawdown_pct': round(s_max_dd * 100, 1),
            }
        }
        print(f"{p_label:20s} | 等权: {n_trades:4d}笔 胜率{eq_win_rate*100:4.1f}% 净值{eq_cum_ret+1:5.2f}倍 相对沪深300超额{eq_excess*100:+6.1f}% (回撤{eq_max_dd*100:4.1f}%) | 单仓: {s_trades:2d}笔 胜率{s_win_rate*100:4.1f}% 盈亏比{s_plr:4.2f} 净值{s_cum_ret+1:5.2f}倍 相对沪深300超额{s_excess*100:+6.1f}% (回撤{s_max_dd*100:4.1f}%)")
    return results

# Test Big Cap Tier (45亿~350亿)
tier_big = df[(df['mcap'] >= 45.0) & (df['mcap'] <= 350.0)]
res_big = run_d15_eval(tier_big, min_score=60.0, tier_label="容量大票档 (45亿~350亿)")

# Test All Cap Tier (20亿~350亿)
tier_all = df[(df['mcap'] >= 20.0) & (df['mcap'] <= 350.0)]
res_all = run_d15_eval(tier_all, min_score=60.0, tier_label="全容量档 (20亿~350亿)")

# Save final summary
final_summary = {
    'scorecard_name': 'RD011-V4.0 跨年大票120因子提纯打分卡',
    'score_threshold': 60.0,
    'big_cap_tier_45_350': res_big,
    'all_cap_tier_20_350': res_all,
}
with open(f"{OUT_DIR}/v4_scorecard_summary.json", "w") as f:
    json.dump(final_summary, f, indent=2, ensure_ascii=False)
print(f"\nSaved final scorecard summary to {OUT_DIR}/v4_scorecard_summary.json")

# Save qualified ledger
sub_ledger = df[df['v4_score'] >= 60.0].copy()
ledger_cols = [
    'season', 'sig_dt', 'buy_dt', 'c6', 'name', 'cand_type', 'mcap', 'close_px', 'v4_score',
    'tight_headroom', 'is_detour_10d', 'pol_ministry_burst_15d', 'pol_geopolitics_burst_15d',
    'theme_is_top1_10d', 'theme_has_100yi_midfielder', 'has_major_contract_45d', 'q3_pre_profit_up',
    'is_soe_flagship', 'ret_smart_dev30_ma10', 'excess_smart_dev30'
]
sub_ledger_out = sub_ledger[ledger_cols].sort_values(['sig_dt', 'v4_score'], ascending=[True, False])
sub_ledger_out.to_csv(f"{OUT_DIR}/v4_scorecard_ledger.csv", index=False)
print(f"Saved qualified trade ledger to {OUT_DIR}/v4_scorecard_ledger.csv ({len(sub_ledger_out):,} rows)")
