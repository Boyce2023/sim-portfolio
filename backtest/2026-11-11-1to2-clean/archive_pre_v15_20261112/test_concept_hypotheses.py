#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_concept_hypotheses.py
Ablation test for:
1. is_new_concept_for_stock
2. is_pioneer_of_brand_new_concept
Strictly PIT, evaluating 2021-2026 full sample on:
- 2B seal rate
- D3 premium rate (d3_open_ret)
- 3+ streak rate (streak >= 3)
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
from collections import defaultdict

DATA_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
sys.path.insert(0, DATA_DIR)
from clean_wf_1to2_v4_3_master import load_kpl_and_notices, load_price_data

def run_ablation():
    t0 = time.time()
    stock_to_plate_info, kpl_daily_plates, plate_daily_counts, neg_notices, pos_notices = load_kpl_and_notices()
    df = load_price_data()
    
    # Identify limit ups and streaks
    all_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_dates)}
    
    # Pre-parse KPL history by date to determine:
    # 1. When did a concept first appear in market?
    # 2. When did a stock first get labeled with a concept?
    
    concept_first_seen = {} # concept -> first date_str
    stock_concept_history = defaultdict(set) # (code6, concept) -> set of date_str
    
    # Read KPL chronologically
    with open('/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            d_str = entry['date']
            plates = entry.get('plates', [])
            for p_obj in plates:
                p_name = p_obj.get('plate', '')
                if p_name and p_name != "其他":
                    if p_name not in concept_first_seen:
                        concept_first_seen[p_name] = d_str
                stks = p_obj.get('stocks', [])
                for s in stks:
                    code6 = str(s[0])[:6].zfill(6)
                    subp = s[2] if len(s) > 2 else ""
                    if p_name and p_name != "其他":
                        stock_concept_history[(code6, p_name)].add(d_str)
                    if subp and subp != "其他":
                        if subp not in concept_first_seen:
                            concept_first_seen[subp] = d_str
                        stock_concept_history[(code6, subp)].add(d_str)

    print(f"Parsed {len(concept_first_seen)} unique concepts.")
    
    # Filter turnover first boards
    fb_all = df[df['is_turnover_fb']].copy()
    fb_all = fb_all[fb_all['d2_date_str'].notna()].copy()
    fb_all = fb_all[(fb_all['d2_date_str'] >= "2021-01-04") & (fb_all['d2_date_str'] <= "2026-11-10")].copy()
    
    # Attach plate info
    plates_list = []
    subplates_list = []
    for row in fb_all[['date_str', 'code6']].itertuples(index=False):
        info = stock_to_plate_info.get((row.date_str, row.code6))
        if info:
            plates_list.append(info['plate'])
            subplates_list.append(info.get('subplate', ''))
        else:
            plates_list.append("其他")
            subplates_list.append("")
    fb_all['plate'] = plates_list
    fb_all['subplate'] = subplates_list
    
    # Add streak forward check: does this trade reach 3+ limit ups?
    # streak on D2 is 2 if d2_is_zt. If D2 is zt, what happens on D3?
    # We can check streak on D3 from df
    code_date_streak = df.set_index(['code6', 'date_str'])['streak'].to_dict()
    
    # Check D3 streak
    d3_date_arr = df.groupby('code6')['date_str'].shift(-2)
    df['d3_date_str'] = d3_date_arr
    code_d3_date = df.set_index(['code6', 'date_str'])['d3_date_str'].to_dict()
    
    d3_streaks = []
    reach_3b = []
    for row in fb_all[['code6', 'd2_date_str', 'd2_is_zt']].itertuples(index=False):
        c6 = row.code6
        d2 = row.d2_date_str
        d2_zt = row.d2_is_zt
        if not d2_zt:
            reach_3b.append(0)
            d3_streaks.append(0)
        else:
            d3_d = code_d3_date.get((c6, d2))
            s3 = code_date_streak.get((c6, d3_d), 0) if d3_d else 0
            d3_streaks.append(s3)
            reach_3b.append(1 if s3 >= 3 else 0)
    fb_all['reach_3b'] = reach_3b
    
    # Calculate hypothesis indicators
    is_new_concept_stock_list = []
    is_pioneer_concept_list = []
    
    for row in fb_all[['date_str', 'code6', 'plate', 'subplate']].itertuples(index=False):
        d1 = row.date_str
        d1_idx = date_to_idx.get(d1, 0)
        c6 = row.code6
        p = row.plate
        subp = row.subplate
        
        # Indicator 1: is_new_concept_for_stock
        # In past 250 trading days prior to D1 (or history prior to D1), did stock ever appear with p or subp?
        prior_dates_p = [d for d in stock_concept_history.get((c6, p), set()) if d < d1]
        # check if any in past 250 trading days:
        past_250_dates = set(all_dates[max(0, d1_idx - 250):d1_idx])
        appeared_in_250 = any(d in past_250_dates for d in prior_dates_p)
        
        if p != "其他" and not appeared_in_250:
            is_new_for_stock = 1
        else:
            is_new_for_stock = 0
        is_new_concept_stock_list.append(is_new_for_stock)
        
        # Indicator 2: is_pioneer_of_brand_new_concept
        # Concept never appeared in market in past 120 trading days prior to D1
        # Check concept_first_seen or past 120 days
        past_120_dates = set(all_dates[max(0, d1_idx - 120):d1_idx])
        # Did p appear in past 120 days?
        first_d = concept_first_seen.get(p)
        if p != "其他" and first_d == d1:
            is_pioneer = 1
        else:
            is_pioneer = 0
        is_pioneer_concept_list.append(is_pioneer)
        
    fb_all['is_new_concept_for_stock'] = is_new_concept_stock_list
    fb_all['is_pioneer_of_brand_new_concept'] = is_pioneer_concept_list
    
    # Let's filter to tradable domain / candidates to see stats
    # Filter 1: All turnover FB with plate != "其他" and d2_open valid
    fb_valid = fb_all[(fb_all['plate'] != "其他") & (fb_all['d2_open'].notna())].copy()
    
    print("\n" + "="*80)
    print("HYPOTHESIS ABLATION ANALYSIS (2021-2026 Full Sample, N =", len(fb_valid), ")")
    print("="*80)
    
    groups = {
        "All Valid First Boards": fb_valid,
        "is_new_concept_for_stock == 1": fb_valid[fb_valid['is_new_concept_for_stock'] == 1],
        "is_new_concept_for_stock == 0 (Old Concept)": fb_valid[fb_valid['is_new_concept_for_stock'] == 0],
        "is_pioneer_of_brand_new_concept == 1": fb_valid[fb_valid['is_pioneer_of_brand_new_concept'] == 1],
        "is_pioneer_of_brand_new_concept == 0": fb_valid[fb_valid['is_pioneer_of_brand_new_concept'] == 0],
        "BOTH is_new_concept == 1 & is_pioneer == 1": fb_valid[(fb_valid['is_new_concept_for_stock'] == 1) & (fb_valid['is_pioneer_of_brand_new_concept'] == 1)],
    }
    
    results = {}
    for name, grp in groups.items():
        n = len(grp)
        if n == 0:
            continue
        rate_2b = grp['d2_is_zt'].mean()
        avg_d3_open_ret = grp['d3_open_ret'].mean()
        win_d3_rate = (grp['d3_open_ret'] > 0).mean()
        rate_3b = grp['reach_3b'].mean() # 3+ limit ups
        
        results[name] = {
            'N': int(n),
            'pct_of_total': round(n / len(fb_valid) * 100, 2),
            'rate_2b': round(float(rate_2b) * 100, 2),
            'avg_d3_open_ret': round(float(avg_d3_open_ret) * 100, 2),
            'win_d3_rate': round(float(win_d3_rate) * 100, 2),
            'rate_3b': round(float(rate_3b) * 100, 2),
        }
        print(f"{name:45s} | N: {n:5d} ({n/len(fb_valid)*100:5.1f}%) | 2B Rate: {rate_2b*100:5.2f}% | D3 Ret: {avg_d3_open_ret*100:+5.2f}% | D3 Win%: {win_d3_rate*100:5.2f}% | 3B+ Rate: {rate_3b*100:5.2f}%")
        
    # Also check within domain candidates (0.015 <= d2_o_pct <= 0.075, plate_d2_cnt >= 2)
    domain_mask = (
        (fb_valid['d2_o_pct'] >= 0.015) & 
        (fb_valid['d2_o_pct'] <= 0.075) & 
        (fb_valid['plate_d2_cnt'] >= 2 if 'plate_d2_cnt' in fb_valid.columns else True)
    )
    fb_domain = fb_valid[domain_mask].copy()
    print("\n" + "="*80)
    print("WITHIN TRADING DOMAIN (0.015 <= d2_o_pct <= 0.075, N =", len(fb_domain), ")")
    print("="*80)
    domain_groups = {
        "Domain: All": fb_domain,
        "Domain: is_new_concept_for_stock == 1": fb_domain[fb_domain['is_new_concept_for_stock'] == 1],
        "Domain: is_new_concept_for_stock == 0": fb_domain[fb_domain['is_new_concept_for_stock'] == 0],
        "Domain: is_pioneer == 1": fb_domain[fb_domain['is_pioneer_of_brand_new_concept'] == 1],
        "Domain: is_pioneer == 0": fb_domain[fb_domain['is_pioneer_of_brand_new_concept'] == 0],
    }
    for name, grp in domain_groups.items():
        n = len(grp)
        if n == 0:
            continue
        rate_2b = grp['d2_is_zt'].mean()
        avg_d3_open_ret = grp['d3_open_ret'].mean()
        rate_3b = grp['reach_3b'].mean()
        print(f"{name:45s} | N: {n:5d} | 2B Rate: {rate_2b*100:5.2f}% | D3 Ret: {avg_d3_open_ret*100:+5.2f}% | 3B+ Rate: {rate_3b*100:5.2f}%")

    with open(os.path.join(DATA_DIR, "hypothesis_ablation_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    run_ablation()
