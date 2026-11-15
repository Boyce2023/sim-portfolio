#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
w2_2to3_v20_scorecard.py — 《二进三 V2.0：一进二主线空间真龙 + 黄金坑分歧换手》纯整数打分卡
核心架构：
  1. 硬前提门 (09:25 PIT 否决项)：
     - 10cm 主板非 ST、竞价可买 (buyable_open)
     - 剔除二板一字缩量板 (放行首板一字二板爆量换手 10~25% 回封换血龙 F02)
     - 剔除 90 日毒雷与 10 日监管函
     - 剔除微盘庄股与流动性枯竭股 (mcap >= 35亿, prev_amt >= 1.8亿, cum_real_to_2d >= 22%)
     - 龙头身位铁律：同题材二板竞价第 1 名或唯一二板活口，前方一字二板 <= 1 只，剔除小微盘扎堆跟风 F05
     - 竞价窗口：-1.5% <= open_pct < 7.0%，二板首封时间在 09:33~14:15，二板股价 <= 28 元，10日断板跌停率 <= 30%
  2. 四大核心正负打分支柱 (100 分起评)：
     - 支柱 A：一进二题材龙头与身位纯度 (空间龙、开盘啦第一主线、新词催化、炒冷饭扣分)
     - 支柱 B：黄金坑与 N 型龙回头筹码结构 (20日箱体低位、深回撤洗盘、十大股东锁仓、真实换手)
     - 支柱 C：二板分歧换血与左端漏网真龙 (放量换手、早盘硬回封、开板换血、0拉萨席位、排雷)
     - 支柱 D：冰点均值回归周期与高潮熔断 (一进二熔断冰点、20日封板率冰点、破局窗口、大高潮退潮排雷)
"""
import os, sys, json, argparse
import numpy as np, pandas as pd

P3_DIR = os.path.dirname(os.path.abspath(__file__))
AST2_DIR = os.path.dirname(P3_DIR)
for p in (AST2_DIR, P3_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

def score_single_2to3_row(r: dict) -> dict:
    """对单只二进三候选股计算 V2.0 打分卡得分及打分明细。"""
    veto = []
    c6 = str(r.get('code', '')).zfill(6)
    name = str(r.get('name', ''))
    if not (c6.startswith(('00', '60')) and 'ST' not in name.upper()):
        veto.append('非主板10cm或ST')
    if not bool(r.get('buyable_open', True)):
        veto.append('竞价一字不可买')
    is_f02 = bool(r.get('F02_yizi1b_heavyto2b', False))
    if bool(r.get('prev_is_yizi', False)) and not is_f02:
        veto.append('二板一字缩量无换血')
    if float(r.get('to_ratio_d2_d1', 1.0)) < 0.55:
        veto.append('二板换手严重萎缩(<0.55)')
    op = float(r.get('open_pct', 0.0))
    if not (-0.015 <= op < 0.070):
        veto.append(f'竞价开盘越界({op*100:.1f}%)')
    if bool(r.get('has_tox_notice', False)) or bool(r.get('has_stock_reg', False)) or bool(r.get('has_ex_reg', False)):
        veto.append('真立案/监管函/毒雷')
    fs = str(r.get('first_seal_time', ''))[:5]
    if fs <= '09:33' or fs >= '14:15':
        veto.append(f'二板首封时间越界({fs})')
    if float(r.get('px_d2', 10.0)) >= 28.0:
        veto.append('二板收盘价超28元高价')
    if float(r.get('prev_break_dt_rate_10d', 0.0)) > 0.30:
        veto.append('近10日断板跌停率超30%')
    
    # 龙头身位与流动性
    if float(r.get('mcap', 50.0)) < 35.0:
        veto.append('总市值低于35亿微盘')
    if float(r.get('prev_amt', 3e8)) < 1.8e8:
        veto.append('二板成交额低于1.8亿缺乏流动性')
    if float(r.get('cum_real_to_2d', 30.0)) < 22.0:
        veto.append('两日累计真实自由换手低于22%')
    rk2 = int(r.get('2b_plate_buy_rk', 1))
    pcnt = int(r.get('plate_2b_cnt', 1))
    if not (rk2 == 1 or pcnt == 1):
        veto.append(f'非同题材可买二板头名(排名{rk2})')
    if int(r.get('plate_2b_yizi_cnt', 0)) >= 2:
        veto.append('同题材>=2只二板顶一字通道堵死')
    if bool(r.get('F05_micro_cluster', False)):
        veto.append('小微盘扎堆跟风排雷')
    if str(r.get('plate', '')) == '其他' and int(r.get('d2_rk_c', 99)) > 10:
        veto.append('无板块孤立独苗强上三板')
    if bool(r.get('d2_spark_bonus', 0) > 0):
        veto.append('老题材二次点火炒冷饭')
    if bool(r.get('has_ir_8d', False)):
        veto.append('近8日机构调研出货盘')
        
    if veto:
        return {'passed_veto': False, 'score': -999, 'veto_reasons': veto, 'breakdown': '未过硬前提门：' + '、'.join(veto)}
        
    sc = 100
    items = ['底分100']
    
    # 支柱 A: 题材真龙与身位纯度
    if bool(r.get('is_sole_plate_space_dragon', False)):
        sc += 12; items.append('同题材唯一无压制空间龙+12')
    elif bool(r.get('is_plate_space_dragon', False)):
        sc += 6; items.append('板块最高连板空间龙+6')
    if bool(r.get('has_plate_4b_plus_bro', False)):
        sc -= 12; items.append('头顶4板+大哥压制-12')
    elif bool(r.get('has_plate_3b_plus_bro', False)):
        sc -= 6; items.append('头顶3板大哥压制-6')
        
    d2_rk = int(r.get('d2_rk_c', 99))
    if d2_rk == 1:
        sc += 8; items.append('Day2开盘啦第一主线+8')
        if float(r.get('d2_gap_c', 0.0)) >= 20.0:
            sc += 6; items.append('断层第一主线+6')
    elif d2_rk == 2:
        sc += 4; items.append('Day2开盘啦第二主线+4')
    elif d2_rk >= 4 or bool(r.get('Rule_alpha_blocked', False)) or bool(r.get('V18_Rule_3_penalized', False)):
        sc -= 8; items.append('杂毛退选题材-8')
        
    if int(r.get('d2_p_sz', 1)) > 15:
        sc -= 8; items.append('板块涨停超15家过热拥挤-8')
    if bool(r.get('notice_ma', False)):
        sc += 10; items.append('并购重组硬核催化+10')
    if bool(r.get('d2_has_new_term', False)) or bool(r.get('d2_is_pioneer_word', False)):
        sc += 6; items.append('先锋新词催化+6')
        
    # 支柱 B: 黄金坑与筹码结构
    pos20 = float(r.get('pos20', 0.5))
    dd20 = float(r.get('dd20', 0.9))
    dd60 = float(r.get('dd60', 0.9))
    if pos20 <= 0.45:
        sc += 12; items.append('20日低位黄金坑+12')
    elif pos20 > 0.85:
        sc -= 8; items.append('20日高位透支-8')
    if dd20 <= 0.85:
        sc += 10; items.append('20日回撤超15%洗盘+10')
    if dd60 <= 0.80:
        sc += 18; items.append('60日深坑超跌超20%+18')
    elif dd60 <= 0.88:
        sc += 10; items.append('60日中度洗盘+10')
    zt20 = int(r.get('zt_cnt_pre20', 0))
    if 1 <= zt20 <= 2 and dd20 <= 0.88:
        sc += 10; items.append('经典N型龙回头基因+10')
        
    lock = float(r.get('lock_top10', 0.0))
    if lock >= 55.0:
        sc += 18; items.append('十大股东锁仓超55%+18')
    elif lock >= 48.0:
        sc += 10; items.append('十大股东锁仓超48%+10')
    elif lock < 32.0:
        sc -= 10; items.append('十大股东锁仓过低-10')
    if float(r.get('real_free_mcap', 0.0)) >= 45.0:
        sc += 8; items.append('真实自由流通市值超45亿+8')
    pto = float(r.get('prev_real_to', 30.0))
    if 15.0 <= pto <= 48.0:
        sc += 12; items.append('真实自由流通换手黄金区(15~48%)+12')
    elif pto > 58.0:
        sc -= 8; items.append('真实自由流通换手过高筹码涣散-8')
        
    # 支柱 C: 二板分歧换手与盘口微观
    tor = float(r.get('to_ratio_d2_d1', 1.0))
    if tor > 2.0:
        sc += 12; items.append('二板爆量换手超2倍充分换血+12')
    elif 0.80 <= tor <= 1.65:
        sc += 10; items.append('二板换手温和放量+10')
    if bool(r.get('is_hard_open_1030', False)):
        sc += 8; items.append('早盘换手硬开板回封+8')
    if int(r.get('open_board_count', 0)) >= 1:
        sc += 14; items.append('二板有开板分歧换手+14')
    else:
        sc -= 8; items.append('二板未开板缺乏分歧-8')
    if float(r.get('seal_amt_ratio', 0.0)) < 0.08:
        sc += 6; items.append('二板封单非死顶+6')
    if 936 <= int(str(r.get('first_seal_time', '')).replace(':', '')[:4] if str(r.get('first_seal_time', '')).replace(':', '')[:4].isdigit() else 0) <= 1030:
        sc += 10; items.append('二板09:36至10:30早盘黄金首封+10')
    if 0.025 <= op <= 0.062:
        sc += 14; items.append('竞价2.5%至6.2%舒适抢筹+14')
    elif 0.005 <= op < 0.025:
        sc += 6; items.append('竞价微幅高开+6')
    if bool(r.get('is_top1_2b_open', False)):
        sc += 14; items.append('全场可买二板竞价第1名+14')
    if bool(r.get('is_plate_top1_2b', False)):
        sc += 8; items.append('同题材二板竞价第1名+8')
    else:
        sc -= 8; items.append('同题材二板后排-8')
    if int(r.get('plate_fresh01_hi_cnt', 0)) >= 1:
        sc += 12; items.append('同题材首板次日高开助攻+12')
    if is_f02:
        sc += 10; items.append('首板一字二板换手10-25%回封龙+10')
    if bool(r.get('F03A_turnover_rush', False)):
        sc += 8; items.append('二板超抢换手Day3分歧+8')
    if bool(r.get('F12_fail_zt_nuke', False)):
        sc -= 12; items.append('同题材昨日冲板失败股今早核按钮-12')
    lh = int(r.get('lhasa_seats_prev', 0))
    if lh == 0:
        sc += 6; items.append('零拉萨散户席位+6')
    else:
        sc -= 6; items.append('拉萨散户席位上榜-6')
    if int(r.get('surf_yz_buy', 0)) >= 1:
        sc -= 14; items.append('一日游砸盘席位买入-14')
    if int(r.get('top_yz_buy', 0)) >= 1:
        sc -= 10; items.append('知名游资大买席位-10')
        
    # 支柱 D: 周期冰点与情绪熔断
    if float(r.get('mkt_promo_1to2_5d', 0.2)) < 0.14:
        sc += 10; items.append('一进二熔断冰点期逆势活口+10')
    if bool(r.get('F18_sensor_cold', False)):
        sc += 10; items.append('滚动20日二进三封板率冰点均值回归+10')
    if int(r.get('mkt_max_board_prev', 5)) in (3, 4):
        sc += 8; items.append('全场最高板3至4板破局窗+8')
    if float(r.get('s_elo', 100.0)) >= 100.0:
        sc += 8; items.append('题材Elo热度达标+8')
    else:
        sc -= 8; items.append('题材Elo过低-8')
    if float(r.get('csi300_ret20', 0.0)) >= -0.02:
        sc += 10; items.append('大盘20日无系统性风险+10')
    else:
        sc -= 6; items.append('大盘20日深跌-6')
    if float(r.get('mkt_seal_rate_prev', 0.6)) >= 0.65:
        sc += 8; items.append('昨日封板率达标+8')
    if int(r.get('prev_3b_dt_cnt', 0)) == 0:
        sc += 8; items.append('前日三板零跌停安全+8')
    else:
        sc -= 6; items.append('前日三板有跌停-6')
    if bool(r.get('F13_climax_carnival', False)):
        sc -= 12; items.append('昨日大高潮退潮排雷-12')
    if bool(r.get('F18_sensor_hot', False)):
        sc -= 10; items.append('滚动20日封板率过热排雷-10')
        
    return {'passed_veto': True, 'score': sc, 'veto_reasons': [], 'breakdown': ' + '.join(items)}

def calc_batch_scores(df: pd.DataFrame) -> pd.DataFrame:
    res = [score_single_2to3_row(r) for r in df.to_dict('records')]
    df = df.copy()
    df['v20_passed'] = [x['passed_veto'] for x in res]
    df['v20_score'] = [x['score'] for x in res]
    df['v20_breakdown'] = [x['breakdown'] for x in res]
    return df

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='《二进三 V2.0》纯整数打分卡')
    parser.add_argument('--date', type=str, help='指定日期 YYYY-MM-DD 打分')
    parser.add_argument('--recent', type=int, default=5, help='最近 N 个交易日')
    args = parser.parse_args()
    
    pq_path = os.path.join(P3_DIR, 'w2_2to3_enriched_master.parquet')
    if not os.path.exists(pq_path):
        print(f'Error: {pq_path} not found!')
        sys.exit(1)
        
    df_raw = pd.read_parquet(pq_path)
    if args.date:
        sub = df_raw[df_raw['buy_date'].astype(str).str[:10] == args.date]
    else:
        all_dts = sorted(df_raw['buy_date'].astype(str).str[:10].unique())
        sub = df_raw[df_raw['buy_date'].astype(str).str[:10].isin(all_dts[-args.recent:])]
        
    res_df = calc_batch_scores(sub)
    passed = res_df[res_df['v20_passed']].sort_values(['buy_date', 'v20_score'], ascending=[True, False])
    print(f'=== 二进三 V2.0 打分卡输出 (样本数: {len(sub)}, 过硬门数: {len(passed)}) ===')
    for r in passed.itertuples(index=False):
        print(f'{r.buy_date} {r.code} {r.name:6s} | 总分={r.v20_score:3d} | plate={r.plate} rk={r.d2_rk_c} open={r.open_pct*100:+.1f}% | {r.v20_breakdown[:80]}...')
