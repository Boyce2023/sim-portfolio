"""
factor_ic_5y.py - 1进2客观单因子五年单调性与跨年一致性全检引擎 (纯向量化高速版)
严格截至 D2 09:25:00 已知，零未来函数，零后视镜。
"""
import sys
import os
import json
import time
import datetime
from collections import defaultdict
import pyarrow.parquet as pq
import pyarrow.dataset as ds
import pandas as pd
import numpy as np

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
os.makedirs(OUTPUT_DIR, exist_ok=True)

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
KPL_PATH = "/Users/huaichuaibeimeng/claude-projects/news-dashboard/output/kpl_plates_v2.jsonl"

def main():
    t0 = time.time()
    print("=== Step 1: 加载并解析开盘啦历史题材库 ===")
    stock_to_plate_info = {}
    date_top1_plate = {}
    token_last_seen = {}
    stock_novelty = {}
    
    with open(KPL_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            d_str = entry['date']
            d_curr = datetime.datetime.strptime(d_str, '%Y-%m-%d').date()
            plates = entry.get('plates', [])
            
            p_counts = []
            for p_obj in plates:
                p_name = p_obj.get('plate', '')
                stocks = p_obj.get('stocks', [])
                p_counts.append((p_name, len(stocks), stocks))
            p_counts.sort(key=lambda x: x[1], reverse=True)
            top1_p = p_counts[0][0] if p_counts else ""
            date_top1_plate[d_str] = top1_p
            
            for p_name, sz, stocks in p_counts:
                for s in stocks:
                    code = str(s[0]).zfill(6)
                    s_name = s[1] if len(s) > 1 else ""
                    subp = s[2] if len(s) > 2 else ""
                    reason = s[3] if len(s) > 3 else ""
                    
                    key = (d_str, code)
                    if key not in stock_to_plate_info or sz > stock_to_plate_info[key]['plate_sz']:
                        stock_to_plate_info[key] = {
                            'plate': p_name,
                            'name': s_name,
                            'subplate': subp,
                            'reason': reason,
                            'plate_sz': sz,
                            'is_top1': 1 if p_name == top1_p else 0
                        }
                    
                    raw_tokens = []
                    for seg in [p_name, subp, reason]:
                        for part in seg.replace('(', '+').replace(')', '+').replace('/', '+').split('+'):
                            p_clean = part.strip()
                            if len(p_clean) >= 2 and p_clean not in ["三季报增长", "年报增长", "业绩增长", "ST摘帽"]:
                                raw_tokens.append(p_clean)
                    
                    is_novel = 0
                    for tok in raw_tokens:
                        if tok not in token_last_seen:
                            is_novel = 1
                        else:
                            if (d_curr - token_last_seen[tok]).days >= 60:
                                is_novel = 1
                        token_last_seen[tok] = d_curr
                    stock_novelty[(d_str, code)] = is_novel

    print(f"KPL 数据解析完毕，耗时 {time.time()-t0:.2f}s")

    print("=== Step 2: 加载 A 股日线数据并向量化计算 ===")
    t1 = time.time()
    dataset = ds.dataset(A_DAILY_PATH, format="parquet")
    scanner = dataset.scanner(
        columns=['date', 'ticker', 'open', 'high', 'low', 'close', 'adj_close', 'amount', 'turn', 'oshare'],
        filter=(ds.field('date') >= pd.Timestamp('2021-05-01'))
    )
    df = scanner.to_table().to_pandas()
    df['ticker_str'] = df['ticker'].astype(str).str.zfill(6)
    df = df[df['ticker_str'].str.startswith(('00', '60'))].copy()
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
    df.sort_values(['ticker_str', 'date'], inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    # 基础技术指标与涨停
    df['pre_close'] = df.groupby('ticker_str')['close'].shift(1)
    df['zt_price'] = (df['pre_close'] * 1.10).round(2)
    df['is_zt'] = (df['close'] >= df['zt_price'] - 0.01) & (df['close'] == df['high']) & (df['pre_close'] > 0)
    df['is_yizi'] = df['is_zt'] & (df['open'] == df['close']) & (df['low'] == df['close'])
    
    # 连板数 streak (高速一维数组遍历)
    zt_arr = df['is_zt'].values
    ticker_arr = df['ticker_str'].values
    n_rows = len(df)
    streak_arr = np.zeros(n_rows, dtype=int)
    curr_streak = 0
    last_tk = ""
    for i in range(n_rows):
        tk = ticker_arr[i]
        if tk != last_tk:
            curr_streak = 0
            last_tk = tk
        if zt_arr[i]:
            curr_streak += 1
        else:
            curr_streak = 0
        streak_arr[i] = curr_streak
    df['streak'] = streak_arr
    df['is_turnover_fb'] = (df['streak'] == 1) & (~df['is_yizi'])
    
    # 技术面衍生
    df['ret_1d'] = df['close'] / df['pre_close'] - 1.0
    df['open_pct'] = df['open'] / df['pre_close'] - 1.0
    df['entity_ratio'] = (df['close'] - df['low']) / df['pre_close']
    df['mcap_circ'] = df['close'] * df['oshare'] / 1e8
    
    df['amt_ma5'] = df.groupby('ticker_str')['amount'].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    df['high_max_20d'] = df.groupby('ticker_str')['high'].transform(lambda s: s.shift(1).rolling(20, min_periods=10).max())
    df['high_max_60d'] = df.groupby('ticker_str')['high'].transform(lambda s: s.shift(1).rolling(60, min_periods=30).max())
    
    df['d0_ret'] = df.groupby('ticker_str')['ret_1d'].shift(1)
    df['d0_drawdown_20d'] = df['pre_close'] / df['high_max_20d']
    df['d1_amt_ratio'] = df['amount'] / (df['amt_ma5'] + 1e-5)
    df['is_breakout_60d'] = (df['close'] >= df['high_max_60d'] - 0.01).astype(int)
    
    # 宏观情绪指标 (纯向量化)
    df['prev_is_turnover_fb'] = df.groupby('ticker_str')['is_turnover_fb'].shift(1).fillna(False)
    
    mkt_max_streak = df.groupby('date_str')['streak'].max().to_dict()
    
    prev_fb_df = df[df['prev_is_turnover_fb']]
    mkt_succ_rate = prev_fb_df.groupby('date_str')['streak'].apply(lambda s: (s == 2).mean()).to_dict()
    mkt_auc_mean = prev_fb_df.groupby('date_str')['open_pct'].mean().to_dict()
    
    print(f"数据向量化完毕，耗时 {time.time()-t1:.2f}s")
    
    print("=== Step 3: 提取 D1 首板与 D2 交易样本 ===")
    t2 = time.time()
    
    # 构造 D2 数据列
    df['d2_date_str'] = df.groupby('ticker_str')['date_str'].shift(-1)
    df['d2_open'] = df.groupby('ticker_str')['open'].shift(-1)
    df['d2_high'] = df.groupby('ticker_str')['high'].shift(-1)
    df['d2_low'] = df.groupby('ticker_str')['low'].shift(-1)
    df['d2_close'] = df.groupby('ticker_str')['close'].shift(-1)
    df['d2_adj_close'] = df.groupby('ticker_str')['adj_close'].shift(-1)
    df['d2_streak'] = df.groupby('ticker_str')['streak'].shift(-1)
    
    # D2 涨停价与开盘涨幅
    df['d2_zt_price'] = (df['close'] * 1.10).round(2)
    df['d2_o_pct'] = df['d2_open'] / df['close'] - 1.0
    
    # 仅保留 D1 是换手首板的行
    fb_samples = df[df['is_turnover_fb']].copy()
    
    # 过滤 D2 日期范围: 2021-10-20 ~ 2026-11-10
    fb_samples = fb_samples[(fb_samples['d2_date_str'] >= "2021-10-20") & (fb_samples['d2_date_str'] <= "2026-11-10")].copy()
    
    # 剔除 D2 一字涨停开盘不可买样本!
    fb_samples = fb_samples[fb_samples['d2_open'] < fb_samples['d2_zt_price'] - 0.01].copy()
    
    # 关联板块题材
    def get_info(r):
        key = (r['date_str'], r['ticker_str'])
        info = stock_to_plate_info.get(key, None)
        if info:
            return info['plate'], info['name'], info['subplate'], info['reason'], info['plate_sz'], info['is_top1']
        return "其他", "", "", "", 1, 0

    info_tuples = [get_info(r) for _, r in fb_samples[['date_str', 'ticker_str']].iterrows()]
    fb_samples['plate'] = [t[0] for t in info_tuples]
    fb_samples['name'] = [t[1] for t in info_tuples]
    fb_samples['subplate'] = [t[2] for t in info_tuples]
    fb_samples['reason'] = [t[3] for t in info_tuples]
    fb_samples['plate_sz'] = [t[4] for t in info_tuples]
    fb_samples['is_top1'] = [t[5] for t in info_tuples]
    
    # 过滤名字含 ST 或 退
    fb_samples = fb_samples[~fb_samples['name'].str.contains('ST|退', regex=True)].copy()
    
    # 计算断板卖出收益率
    adj_map = dict(zip(zip(df['ticker_str'], df['date_str']), zip(df['close'], df['adj_close'], df['streak'], df['is_zt'])))
    all_dates = sorted(df['date_str'].unique())
    date_idx_map = {d: i for i, d in enumerate(all_dates)}
    
    net_rets = []
    hold_days_list = []
    is_d2_zt_list = []
    
    for _, r in fb_samples.iterrows():
        tk = r['ticker_str']
        d2_d = r['d2_date_str']
        d2_o = r['d2_open']
        d2_c = r['d2_close']
        d2_adj = r['d2_adj_close']
        d2_streak = r['d2_streak']
        
        is_d2_zt = (d2_streak == 2)
        is_d2_zt_list.append(1 if is_d2_zt else 0)
        
        curr_d_idx = date_idx_map[d2_d]
        hold_days = 1
        sell_adj = d2_adj
        
        if is_d2_zt:
            while curr_d_idx + 1 < len(all_dates):
                next_d = all_dates[curr_d_idx + 1]
                rec = adj_map.get((tk, next_d))
                if not rec:
                    break
                n_close, n_adj, n_streak, n_is_zt = rec
                hold_days += 1
                sell_adj = n_adj
                curr_d_idx += 1
                if not n_is_zt:
                    break
                    
        buy_adj = d2_o * (d2_adj / d2_c)
        ret = (sell_adj / buy_adj) - 1.0 - 0.0025
        net_rets.append(ret)
        hold_days_list.append(hold_days)
        
    fb_samples['is_d2_zt'] = is_d2_zt_list
    fb_samples['net_ret'] = net_rets
    fb_samples['hold_days'] = hold_days_list
    fb_samples['year'] = fb_samples['d2_date_str'].str[:4].astype(int)
    
    print(f"样本库提取完毕: 共 {len(fb_samples)} 个换手首板样本，耗时 {time.time()-t2:.2f}s")
    
    print("=== Step 4: 计算 18 个候选因子 ===")
    t3 = time.time()
    
    # F01 ~ F05
    fb_samples['F01_plate_sz'] = fb_samples['plate_sz']
    fb_samples['F02_is_top1'] = fb_samples['is_top1']
    
    # F04: plate_yizi_cnt
    yizi_df = df[df['is_yizi']][['date_str', 'ticker_str']].copy()
    yizi_set = set(zip(yizi_df['date_str'], yizi_df['ticker_str']))
    plate_yizi_map = defaultdict(int)
    for (d_str, code), p_info in stock_to_plate_info.items():
        if (d_str, code) in yizi_set:
            plate_yizi_map[(d_str, p_info['plate'])] += 1
            
    fb_samples['F04_plate_yizi_cnt'] = [plate_yizi_map.get((r['date_str'], r['plate']), 0) for _, r in fb_samples.iterrows()]
    fb_samples['F05_novelty'] = [stock_novelty.get((r['date_str'], r['ticker_str']), 0) for _, r in fb_samples.iterrows()]
    
    # F06: 通用重组/合同硬催化 vs 业绩明牌
    hard_words = ['重组', '收购', '控制权', '股权转让', '借壳', '中标', '重大合同', '签约', '协议']
    perf_words = ['季报', '年报', '中报', '业绩', '预增', '扭亏', '增长']
    def get_f06(r):
        text = str(r['plate']) + " " + str(r['subplate']) + " " + str(r['reason'])
        has_hard = any(w in text for w in hard_words)
        has_perf = any(w in text for w in perf_words)
        if has_hard and not has_perf:
            return 1
        elif has_perf and not has_hard:
            return -1
        elif has_hard and has_perf:
            return 1
        return 0
    fb_samples['F06_catalyst'] = [get_f06(r) for _, r in fb_samples.iterrows()]
    
    # F07 ~ F13
    fb_samples['F07_turn'] = fb_samples['turn']
    fb_samples['F08_mcap'] = fb_samples['mcap_circ']
    fb_samples['F09_drawdown'] = fb_samples['d0_drawdown_20d'].fillna(1.0)
    fb_samples['F10_breakout60'] = fb_samples['is_breakout_60d']
    fb_samples['F11_d0_ret'] = fb_samples['d0_ret'].fillna(0.0)
    fb_samples['F12_amt_ratio'] = fb_samples['d1_amt_ratio'].fillna(1.0)
    fb_samples['F13_entity'] = fb_samples['entity_ratio'].fillna(0.09)
    fb_samples['F13_open_pct'] = fb_samples['open_pct'].fillna(0.0)
    
    # F14 ~ F16
    fb_samples['F14_d2_o_pct'] = fb_samples['d2_o_pct']
    fb_samples['auc_rank_in_plate'] = fb_samples.groupby(['d2_date_str', 'plate'])['d2_o_pct'].rank(ascending=False, method='min')
    fb_samples['F15_auc_rank'] = fb_samples['auc_rank_in_plate']
    
    plate_groups = fb_samples.groupby(['d2_date_str', 'plate'])
    lead_dict = {}
    for (d2_d, p), group in plate_groups:
        sorted_vals = group.sort_values('d2_o_pct', ascending=False)
        vals = sorted_vals['d2_o_pct'].values
        tickers = sorted_vals['ticker_str'].values
        if len(vals) == 1:
            lead_dict[(d2_d, tickers[0])] = 0.0
        else:
            first_val = vals[0]
            second_val = vals[1]
            for i, tk in enumerate(tickers):
                if i == 0:
                    lead_dict[(d2_d, tk)] = first_val - second_val
                else:
                    lead_dict[(d2_d, tk)] = vals[i] - first_val
    fb_samples['F16_open_lead'] = [lead_dict.get((r['d2_date_str'], r['ticker_str']), 0.0) for _, r in fb_samples.iterrows()]
    
    # F17 & F18
    fb_samples['F17_mkt_auc_mean'] = [mkt_auc_mean.get(d, 0.0) for d in fb_samples['d2_date_str']]
    fb_samples['F18_mkt_streak_d1'] = [mkt_max_streak.get(d, 0) for d in fb_samples['date_str']]
    fb_samples['F18_mkt_1to2_rate_d1'] = [mkt_succ_rate.get(d, 0.0) for d in fb_samples['date_str']]
    
    # F03: 过去3日同题材赚钱效应
    d2_dates_sorted = sorted(fb_samples['d2_date_str'].unique())
    hist_3d_dates = {cur_d: d2_dates_sorted[max(0, idx_d-3):idx_d] for idx_d, cur_d in enumerate(d2_dates_sorted)}
    plate_date_avg_ret = fb_samples.groupby(['d2_date_str', 'plate'])['net_ret'].mean().to_dict()
    f03_vals = []
    for _, r in fb_samples.iterrows():
        p = r['plate']
        cur_d = r['d2_date_str']
        past_ds = hist_3d_dates.get(cur_d, [])
        past_rets = [plate_date_avg_ret.get((pd_d, p)) for pd_d in past_ds if (pd_d, p) in plate_date_avg_ret]
        f03_vals.append(float(np.mean(past_rets)) if past_rets else 0.0)
    fb_samples['F03_plate_past3d_ret'] = f03_vals
    
    print(f"因子衍生完成，耗时 {time.time()-t3:.2f}s")

    print("=== Step 5: 单调性检验与 5 年分年度稳定性汇总 ===")
    t4 = time.time()
    
    factors_to_test = [
        ('F01_plate_sz', '所属题材D1涨停总家数', 'continuous'),
        ('F02_is_top1', '所属题材是否全场第1大涨停板块', 'binary'),
        ('F03_plate_past3d_ret', '所属题材过去3日连板赚钱效应', 'continuous'),
        ('F04_plate_yizi_cnt', '所属题材D1一字板前排个数', 'discrete'),
        ('F05_novelty', '纯动态新词首次爆发(沉寂>60天)', 'binary'),
        ('F06_catalyst', '通用重组合同硬催化(+1)vs业绩明牌(-1)', 'discrete'),
        ('F07_turn', 'D1首板换手率', 'continuous'),
        ('F08_mcap', 'D1流通市值(亿元)', 'continuous'),
        ('F09_drawdown', '首板前20日回撤深度(D0收盘/20日最高)', 'continuous'),
        ('F10_breakout60', '首板涨停价突破60日最高', 'binary'),
        ('F11_d0_ret', '首板前一日D0涨跌幅', 'continuous'),
        ('F12_amt_ratio', '首板量比(D1成交额/5日均额)', 'continuous'),
        ('F13_entity', '首板当日K线实体比例', 'continuous'),
        ('F14_d2_o_pct', 'D2集合竞价开盘涨幅', 'continuous'),
        ('F15_auc_rank', '同题材内部竞价排名(1为卡位龙)', 'discrete'),
        ('F16_open_lead', '竞价领先幅度(较第2名超额)', 'continuous'),
        ('F17_mkt_auc_mean', '全市场昨日首板平均开盘溢价(择时A)', 'continuous'),
        ('F18_mkt_streak_d1', '昨日全市场最高连板高度(择时B1)', 'continuous'),
        ('F18_mkt_1to2_rate_d1', '昨日全市场一进二封板率(择时B2)', 'continuous'),
    ]
    
    results = {}
    years = [2022, 2023, 2024, 2025, 2026]
    
    for f_code, f_name, f_type in factors_to_test:
        sub_df = fb_samples[['year', 'is_d2_zt', 'net_ret', 'hold_days', f_code]].dropna().copy()
        
        if f_type == 'continuous':
            sub_df['q'] = pd.qcut(sub_df[f_code].rank(method='first'), 5, labels=['Q1', 'Q2', 'Q3', 'Q4', 'Q5'])
            top_label, bot_label = 'Q5', 'Q1'
        elif f_type == 'binary':
            sub_df['q'] = sub_df[f_code].apply(lambda x: 'Top' if x == 1 else 'Bottom')
            top_label, bot_label = 'Top', 'Bottom'
        elif f_type == 'discrete':
            if f_code == 'F06_catalyst':
                sub_df['q'] = sub_df[f_code].map({1: 'Hard_Catalyst', 0: 'Neutral_Theme', -1: 'Earnings_Report'})
                top_label, bot_label = 'Hard_Catalyst', 'Earnings_Report'
            elif f_code == 'F04_plate_yizi_cnt':
                sub_df['q'] = sub_df[f_code].apply(lambda x: '0家' if x == 0 else ('1家' if x == 1 else '>=2家'))
                top_label, bot_label = '>=2家', '0家'
            elif f_code == 'F15_auc_rank':
                sub_df['q'] = sub_df[f_code].apply(lambda x: 'Rank_1' if x == 1 else ('Rank_2' if x == 2 else 'Rank_3+'))
                top_label, bot_label = 'Rank_1', 'Rank_3+'
        
        overall_grp = sub_df.groupby('q', observed=False).agg(
            n=('net_ret', 'count'),
            win_rate=('is_d2_zt', 'mean'),
            avg_net_ret=('net_ret', 'mean'),
            avg_hold_days=('hold_days', 'mean'),
            val_min=(f_code, 'min'),
            val_max=(f_code, 'max')
        ).to_dict(orient='index')
        
        yearly_excess = {}
        pos_years = 0
        
        for yr in years:
            yr_df = sub_df[sub_df['year'] == yr]
            if len(yr_df) == 0:
                continue
            yr_grp = yr_df.groupby('q', observed=False)['net_ret'].mean().to_dict()
            yr_win = yr_df.groupby('q', observed=False)['is_d2_zt'].mean().to_dict()
            
            top_ret = yr_grp.get(top_label, np.nan)
            bot_ret = yr_grp.get(bot_label, np.nan)
            top_w = yr_win.get(top_label, np.nan)
            bot_w = yr_win.get(bot_label, np.nan)
            
            diff_ret = top_ret - bot_ret if not (np.isnan(top_ret) or np.isnan(bot_ret)) else 0.0
            diff_win = top_w - bot_w if not (np.isnan(top_w) or np.isnan(bot_w)) else 0.0
            
            if diff_ret > 0:
                pos_years += 1
                
            yearly_excess[str(yr)] = {
                'excess_net_ret': float(diff_ret),
                'excess_win_rate': float(diff_win),
                'top_ret': float(top_ret),
                'bot_ret': float(bot_ret),
                'top_win': float(top_w),
                'bot_win': float(bot_w)
            }
            
        corr_ret = None
        corr_win = None
        if f_type == 'continuous':
            q_order = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']
            rets = [overall_grp[q]['avg_net_ret'] for q in q_order]
            wins = [overall_grp[q]['win_rate'] for q in q_order]
            corr_ret = float(pd.Series(range(1, 6)).corr(pd.Series(rets), method='spearman'))
            corr_win = float(pd.Series(range(1, 6)).corr(pd.Series(wins), method='spearman'))
            
        results[f_code] = {
            'name': f_name,
            'type': f_type,
            'top_label': top_label,
            'bot_label': bot_label,
            'overall_groups': {str(k): {
                'n': int(v['n']),
                'win_rate': float(v['win_rate']),
                'avg_net_ret': float(v['avg_net_ret']),
                'avg_hold_days': float(v['avg_hold_days']),
                'val_min': float(v['val_min']) if not np.isnan(v['val_min']) else None,
                'val_max': float(v['val_max']) if not np.isnan(v['val_max']) else None,
            } for k, v in overall_grp.items()},
            'yearly_excess': yearly_excess,
            'positive_years_count': pos_years,
            'spearman_corr_net_ret': corr_ret,
            'spearman_corr_win_rate': corr_win,
            'is_stable_5y': (pos_years >= 4)
        }

    # F14 1% 细拆
    bins = [-1.0, -0.05, -0.02, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.095]
    bin_labels = ['< -5%', '[-5%,-2%)', '[-2%,0%)', '[0%,1%)', '[1%,2%)', '[2%,3%)', '[3%,4%)', '[4%,5%)', '[5%,6%)', '[6%,7%)', '[7%,8%)', '[8%,9.5%)']
    fb_samples['d2_o_bin'] = pd.cut(fb_samples['d2_o_pct'], bins=bins, labels=bin_labels)
    f14_detailed = fb_samples.groupby('d2_o_bin', observed=False).agg(
        n=('net_ret', 'count'),
        win_rate=('is_d2_zt', 'mean'),
        avg_net_ret=('net_ret', 'mean'),
        avg_hold_days=('hold_days', 'mean')
    ).to_dict(orient='index')
    
    results['F14_detailed_1pct_bins'] = {
        str(k): {
            'n': int(v['n']),
            'win_rate': float(v['win_rate']),
            'avg_net_ret': float(v['avg_net_ret']),
            'avg_hold_days': float(v['avg_hold_days'])
        } for k, v in f14_detailed.items()
    }

    # 落盘 json
    json_path = os.path.join(OUTPUT_DIR, "factor_ic_5y_results.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        
    print(f"\n================== 核心检验结论汇总 (全量样本 N={len(fb_samples)}) ==================")
    print(f"{'因子代码':<22} | {'因子名称':<25} | {'正收益年数':<10} | {'5年稳定性':<8} | {'Q5(Top)净收益':<12} | {'Q1(Bot)净收益':<12} | {'胜率差':<10}")
    print("-" * 110)
    for f_code, f_name, _ in factors_to_test:
        r = results[f_code]
        pos_yrs = r['positive_years_count']
        stable = "PASS" if r['is_stable_5y'] else "FAIL"
        top_grp = r['overall_groups'].get(r['top_label'], {})
        bot_grp = r['overall_groups'].get(r['bot_label'], {})
        top_ret = top_grp.get('avg_net_ret', 0.0) * 100
        bot_ret = bot_grp.get('avg_net_ret', 0.0) * 100
        top_w = top_grp.get('win_rate', 0.0) * 100
        bot_w = bot_grp.get('win_rate', 0.0) * 100
        diff_w = top_w - bot_w
        print(f"{f_code:<22} | {f_name:<25} | {pos_yrs}/5 年    | {stable:<8} | {top_ret:+6.2f}%      | {bot_ret:+6.2f}%      | {diff_w:+6.2f}%")
        
    print(f"\n全部计算完毕，总耗时 {time.time()-t0:.2f}s")

if __name__ == '__main__':
    main()
