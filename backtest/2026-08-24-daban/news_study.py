#!/usr/bin/env python3
"""B策略消息回测 · 阶段1: 公告类型 × 打板前瞻收益

⛔PIT纪律(与铁律1的盘前/盘后问题同源):
  A策略在涨停次日(T+1)开盘买入 → T+1开盘前已公开的信息都可用。
  日期为T的公告(T日盘后发布)在T+1开盘前公开 ✓ 可用。
  日期为T+1的公告 ✗ 不可用(可能盘中/盘后才发)。
  故窗口取 [T-1, T],T=涨停日。

⛔不预设"哪类公告是利好": 直接按公告类型分桶算前瞻收益,让数据说话。
  预先分类=把我的先验当成结论,正是B2那次栽跟头的形状。
"""
import sqlite3, json, sys, collections, statistics

BASE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'

def lim_pct(c):
    b = c.split('.')[1]
    if b.startswith(('30', '68')): return 0.20
    if b.startswith(('8', '4', '92')): return 0.30
    return 0.10

def load_k(db):
    con = sqlite3.connect(db)
    rows = con.execute("select code,date,open,high,low,close,preclose,turn,isST from k where preclose>0 order by code,date").fetchall()
    con.close()
    by = collections.defaultdict(list)
    for r in rows: by[r[0]].append(r)
    return by

def load_notices():
    con = sqlite3.connect(f'{BASE}/notices.db')
    d = collections.defaultdict(list)
    for code, ntype, ndate in con.execute("select code,ntype,ndate from notice"):
        d[(code, ndate)].append(ntype)
    con.close()
    return d

def main():
    db = sys.argv[1] if len(sys.argv) > 1 else f'{BASE}/univ2025.db'
    by = load_k(db)
    NT = load_notices()
    print(f'[加载] K线{len(by)}只  公告(code,date)组合{len(NT)}个', flush=True)

    recs = []
    for code, bars in by.items():
        l0 = lim_pct(code)
        bare = code.split('.')[1]
        for i, b in enumerate(bars):
            _, d, o, h, l, c, pc, turn, st = b
            if c < 2.0 or not turn or turn <= 0.3: continue
            L = 0.05 if st else l0
            lim = round(pc * (1 + L), 2)
            if abs(c - lim) >= 0.005: continue          # 非涨停收盘
            if abs(o - lim) < 0.005 and abs(l - lim) < 0.005: continue   # 一字板剔除
            if i + 1 >= len(bars): continue
            nb = bars[i + 1]
            if not nb[7] or nb[7] <= 0.3 or nb[2] <= 0: continue
            gap = (nb[2] / c - 1) * 100
            # 连板数
            s = 1; j = i - 1
            while j >= 0:
                pb = bars[j]; Lj = 0.05 if pb[8] else l0
                if pb[6] > 0 and abs(pb[5] - round(pb[6] * (1 + Lj), 2)) < 0.005: s += 1; j -= 1
                else: break
            k = max(0, i - 20)
            g20 = (c / bars[k][5] - 1) * 100 if bars[k][5] > 0 else None
            if g20 is None: continue
            # 前瞻收益: T+1开盘买入 → T+1/T+2/T+3/T+5 收盘(毛,不含费,阶段1只看信号强弱)
            buy = nb[2]
            fwd = {}
            for n in (1, 2, 3, 5):
                if i + n < len(bars): fwd[f'r{n}'] = (bars[i + n][5] / buy - 1) * 100
                else: fwd[f'r{n}'] = None
            # 公告窗口 [T-1, T]
            pd_ = bars[i - 1][1] if i >= 1 else d
            types = set(NT.get((bare, d), [])) | set(NT.get((bare, pd_), []))
            recs.append({'code': code, 'date': d, 'gap': gap, 'streak': s, 'g20': g20,
                         'turn': turn, 'types': sorted(types), 'n_notice': len(types), **fwd})
    print(f'[样本] 涨停(非一字)且次日可交易 {len(recs)} 条', flush=True)
    json.dump(recs, open(f'{BASE}/news_recs_{db.split("/")[-1].replace(".db","")}.json', 'w'), ensure_ascii=False)

    def agg(rows, key):
        v = [r[key] for r in rows if r.get(key) is not None]
        if not v: return None
        w = sum(1 for x in v if x > 0) / len(v) * 100
        return (len(v), statistics.mean(v), statistics.median(v), w)

    print('\n' + '=' * 92)
    print('【基准】全部涨停样本  T+1开盘买入后的毛收益')
    print('=' * 92)
    print('%-8s %7s %9s %9s %8s' % ('窗口', 'n', '均值%', '中位%', '胜率%'))
    for n in (1, 2, 3, 5):
        a = agg(recs, f'r{n}')
        if a: print('%-8s %7d %+9.2f %+9.2f %8.1f' % (f'T+{n}', *a))

    has = [r for r in recs if r['n_notice'] > 0]
    non = [r for r in recs if r['n_notice'] == 0]
    print('\n' + '=' * 92)
    print('【有无公告】窗口[T-1,T]')
    print('=' * 92)
    print('%-14s %7s %9s %9s %8s' % ('组', 'n', 'T+1均值%', 'T+3均值%', 'T+3胜率%'))
    for nm, g in (('有公告', has), ('无公告', non)):
        a1, a3 = agg(g, 'r1'), agg(g, 'r3')
        if a1 and a3: print('%-14s %7d %+9.2f %+9.2f %8.1f' % (nm, a1[0], a1[1], a3[1], a3[3]))

    cnt = collections.Counter()
    for r in recs:
        for t in r['types']: cnt[t] += 1
    print('\n' + '=' * 92)
    print('【按公告类型】样本≥40的类型,按T+3均值排序   基准T+3均值=%.2f%%' % agg(recs, 'r3')[1])
    print('=' * 92)
    print('%-26s %6s %9s %9s %8s %9s' % ('公告类型', 'n', 'T+1均值%', 'T+3均值%', 'T+3胜率%', 'vs基准pp'))
    base3 = agg(recs, 'r3')[1]
    out = []
    for t, n in cnt.items():
        if n < 40: continue
        g = [r for r in recs if t in r['types']]
        a1, a3 = agg(g, 'r1'), agg(g, 'r3')
        if a1 and a3: out.append((t, a3[0], a1[1], a3[1], a3[3], a3[1] - base3))
    for row in sorted(out, key=lambda x: -x[3]):
        print('%-26s %6d %+9.2f %+9.2f %8.1f %+9.2f' % row)

main()

# ══════════════════════════════════════════════════════════════════════
# 阶段1b: 题材聚集度 —— 用户真正的假设"游资靠消息",公告只是消息的一种,
#   更主要的是板块/题材新闻。板块新闻在数据上的指纹 = 同日同题材多只涨停。
#   ⛔这是PIT安全的: 同日涨停家数在T日收盘即已知,而我T+1开盘才买。
# ══════════════════════════════════════════════════════════════════════
def phase1b(db):
    import sqlite3, json, collections, statistics
    BASE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'
    tag = db.split("/")[-1].replace(".db", "")
    recs = json.load(open(f'{BASE}/news_recs_{tag}.json'))
    # 行业映射(⛔用当前申万分类回溯2025,属轻度lookahead: 个股行业归属变动极少,已标注)
    try:
        ind = json.load(open(f'{BASE}/ind_map.json'))
    except Exception:
        print('\n[阶段1b] 缺 ind_map.json,跳过行业聚集度'); ind = {}
    perday = collections.Counter(r['date'] for r in recs)
    perday_ind = collections.Counter()
    for r in recs:
        s = ind.get(r['code'].split('.')[1])
        if s: perday_ind[(r['date'], s)] += 1
    for r in recs:
        r['zt_today'] = perday[r['date']]
        s = ind.get(r['code'].split('.')[1])
        r['ind'] = s
        r['ind_zt'] = perday_ind.get((r['date'], s), 0) if s else None

    def agg(rows, key='r3'):
        v = [x[key] for x in rows if x.get(key) is not None]
        if not v: return None
        return (len(v), statistics.mean(v), statistics.median(v),
                sum(1 for x in v if x > 0) / len(v) * 100)

    base = agg(recs)
    print('\n' + '=' * 92)
    print('【市场情绪】当日涨停总家数分档  基准T+3均值=%.2f%%' % base[1])
    print('=' * 92)
    print('%-18s %7s %9s %9s %8s %9s' % ('当日涨停家数', 'n', 'T+1均值%', 'T+3均值%', 'T+3胜率%', 'vs基准pp'))
    for lo, hi, nm in ((0, 30, '≤30 冰点'), (30, 50, '30-50 偏冷'), (50, 80, '50-80 中性'),
                       (80, 120, '80-120 偏热'), (120, 10000, '>120 过热')):
        g = [r for r in recs if lo <= r['zt_today'] < hi]
        a1, a3 = agg(g, 'r1'), agg(g, 'r3')
        if a1 and a3 and a3[0] >= 40:
            print('%-18s %7d %+9.2f %+9.2f %8.1f %+9.2f' % (nm, a3[0], a1[1], a3[1], a3[3], a3[1] - base[1]))

    if ind:
        print('\n' + '=' * 92)
        print('【题材聚集度】当日同行业涨停家数(=板块新闻的价格指纹)')
        print('=' * 92)
        print('%-18s %7s %9s %9s %8s %9s' % ('同行业涨停', 'n', 'T+1均值%', 'T+3均值%', 'T+3胜率%', 'vs基准pp'))
        for lo, hi, nm in ((1, 2, '1只 孤立'), (2, 3, '2只'), (3, 5, '3-4只'),
                           (5, 8, '5-7只'), (8, 1000, '≥8只 链级共振')):
            g = [r for r in recs if r['ind_zt'] and lo <= r['ind_zt'] < hi]
            a1, a3 = agg(g, 'r1'), agg(g, 'r3')
            if a1 and a3 and a3[0] >= 40:
                print('%-18s %7d %+9.2f %+9.2f %8.1f %+9.2f' % (nm, a3[0], a1[1], a3[1], a3[3], a3[1] - base[1]))
    json.dump(recs, open(f'{BASE}/news_recs_{tag}.json', 'w'), ensure_ascii=False)

import sys as _s
phase1b(_s.argv[1] if len(_s.argv) > 1 else f'{BASE}/univ2025.db')
