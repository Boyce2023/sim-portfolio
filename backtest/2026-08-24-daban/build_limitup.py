#!/usr/bin/env python3
"""从日K重构涨停池 — 因 ak.stock_zt_pool_em 只提供最近约1个月历史(实测20260731及更早全空),
2025全年打板回测无法用该接口, 改从原始日K反推涨停(更可靠: 直接由价格算, 不依赖第三方标注)。

涨停判定: 收盘价 == round(前收 * (1+涨跌幅上限), 2)
  上限: 主板60/00 =10%; 创业板30 / 科创板68 =20%; 北交所8/4 =30%; ST(名称含ST) =5%
  ⚠️2026-09-04更正: 上面这句与实现不符——第41行实现用的是 abs(c-lim)<0.005 容差比较, 不是纯 round 相等。
  注释与实现相反会误导后来者(2026-09-04 us session 自查时即被此注释误导, 以为这批数据干净)。
  实测该容差的真实漏板率仅 2.1%-2.5%(见 backtest/2026-09-04-abc-fix/measure_miss_rate.py),
  且逐笔diff显示对A策略的影响主要来自分仓标的数变化而非交易本身(见 trade_diff.py), 故未重跑本文件产出。
"""
import sqlite3, json, sys
from collections import defaultdict

DB = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kline_cache.db'
OUT = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'

def limit_pct(code):
    if code.startswith(('30', '68')): return 0.20
    if code.startswith(('8', '4', '92')): return 0.30
    return 0.10

def main(start='2025-01-01', end='2025-12-31'):
    con = sqlite3.connect(DB)
    rows = con.execute(
        "select code,date,open,high,low,close,volume from daily_kline "
        "where date>=? and date<=? order by code,date", (start, end)).fetchall()
    print(f'读入 {len(rows)} 行, 区间 {start}~{end}', file=sys.stderr)

    bycode = defaultdict(list)
    for r in rows: bycode[r[0]].append(r)

    limitups = []          # 涨停记录
    daily_all = defaultdict(dict)   # date -> code -> bar (供后续算收益)
    for code, bars in bycode.items():
        lp = limit_pct(code)
        for i, b in enumerate(bars):
            _, d, o, h, l, c, v = b
            daily_all[d][code] = {'o': o, 'h': h, 'l': l, 'c': c, 'v': v}
            if i == 0: continue
            prev_c = bars[i-1][5]
            if prev_c <= 0: continue
            lim = round(prev_c * (1 + lp), 2)
            if abs(c - lim) < 0.005:      # 收盘=涨停价
                # 特征
                is_yiziban = abs(o - lim) < 0.005 and abs(l - lim) < 0.005   # 一字板
                touched_only = abs(h - lim) < 0.005 and abs(c - lim) >= 0.005
                # 连板数: 往前数连续涨停天数
                streak = 1
                j = i - 1
                while j > 0:
                    pc2 = bars[j-1][5]
                    if pc2 <= 0: break
                    lim2 = round(pc2 * (1 + lp), 2)
                    if abs(bars[j][5] - lim2) < 0.005: streak += 1; j -= 1
                    else: break
                # 前期涨幅(20日)
                k = max(0, i - 20)
                gain20 = (c / bars[k][5] - 1) * 100 if bars[k][5] > 0 else None
                limitups.append({
                    'code': code, 'date': d, 'close': c, 'limit_price': lim,
                    'board_pct': lp, 'streak': streak, 'yiziban': is_yiziban,
                    'open_gap': (o / prev_c - 1) * 100,
                    'volume': v, 'gain20_before': gain20,
                })
    print(f'重构出涨停记录 {len(limitups)} 条', file=sys.stderr)
    json.dump(limitups, open(f'{OUT}/limitups_2025.json', 'w'))
    # daily_all 太大, 存sqlite索引表供收益计算
    json.dump({d: len(v) for d, v in sorted(daily_all.items())},
              open(f'{OUT}/daily_coverage.json', 'w'))
    bydate = defaultdict(int)
    for r in limitups: bydate[r['date']] += 1
    print('涨停家数样例(前10个交易日):', file=sys.stderr)
    for d in sorted(bydate)[:10]: print(f'  {d}: {bydate[d]}', file=sys.stderr)
    print(f'\n覆盖交易日 {len(bydate)} 天, 日均涨停 {len(limitups)/max(len(bydate),1):.1f} 只', file=sys.stderr)

if __name__ == '__main__':
    main(*(sys.argv[1:] or []))
