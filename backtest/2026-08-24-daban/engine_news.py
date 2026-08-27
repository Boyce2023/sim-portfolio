#!/usr/bin/env python3
"""阶段2: A策略 ± 消息过滤器 对比回测

⛔与engine.py共用完全相同的入场/出场/费用逻辑,唯一差别是 signals() 后加一层消息过滤,
   这样两组的差异只能来自消息因子本身,不来自任何其他改动。
⛔PIT: A策略在涨停次日(T+1)开盘买入 → 公告窗口取[T-1,T](T=涨停日),
   T日盘后发布的公告在T+1开盘前已公开,可用;T+1的公告不可用。
⛔行业聚集度同样PIT安全: 同日同行业涨停家数在T日收盘即已知。
"""
import sqlite3, sys, json, collections
sys.path.insert(0, '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
from strategy_v2 import PARAMS as P
from engine import lim_pct, load, signals, run

BASE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'


def load_notice_index():
    con = sqlite3.connect(f'{BASE}/notices.db')
    d = collections.defaultdict(set)
    for code, ntype, ndate in con.execute("select code,ntype,ndate from notice"):
        d[(code, ndate)].add(ntype)
    con.close()
    return d


def prev_trading_day(by, code, date):
    bars = by[code]
    prev = None
    for b in bars:
        if b[1] >= date: break
        prev = b[1]
    return prev


def enrich(by, sig, NT, ind):
    """给每个signal挂上消息特征。signal的date是买入日(T+1),涨停日是它的前一交易日。

    ⛔2026-08-27修: zt_today/ind_zt原来从signal自己数(=A策略信号数,每天个位数),
      不是全市场涨停家数——"当日涨停>80"档永远空转。改用阶段1全量涨停表(15925条)。"""
    # ⛔2026-08-27再修: 原来读news_recs_univ2025.json——跑2026样本外时会拿2025的涨停数。
    #   改为从当前by(本次回测的K数据)现算全市场涨停家数,与信号检测同一套判定。
    zt_by_day = collections.Counter()
    ind_by_day = collections.Counter()
    for code, bars in by.items():
        l0 = lim_pct(code)
        for b in bars:
            _, d0, o, h, l, c, pc, turn, st = b
            if pc <= 0 or c < 2.0: continue
            L = 0.05 if st else l0
            if abs(c - round(pc * (1 + L), 2)) >= 0.005: continue
            if abs(o - round(pc * (1 + L), 2)) < 0.005 and abs(l - round(pc * (1 + L), 2)) < 0.005: continue
            zt_by_day[d0] += 1
            sec = ind.get(code.split('.')[1])
            if sec: ind_by_day[(d0, sec)] += 1
    for d, lst in sig.items():
        for s in lst:
            bars = by[s['code']]
            zt = None
            for i, b in enumerate(bars):
                if b[1] == d and i > 0: zt = bars[i - 1][1]; break
            s['zt_date'] = zt
            s['ind'] = ind.get(s['code'].split('.')[1])
    for d, lst in sig.items():
        for s in lst:
            zt = s.get('zt_date')
            if not zt: s['ntypes'] = set(); s['zt_today'] = 0; s['ind_zt'] = 0; continue
            bare = s['code'].split('.')[1]
            pd_ = prev_trading_day(by, s['code'], zt) or zt
            s['ntypes'] = NT.get((bare, zt), set()) | NT.get((bare, pd_), set())
            s['zt_today'] = zt_by_day.get(zt, 0)
            s['ind_zt'] = ind_by_day.get((zt, s.get('ind')), 0)
    return sig


def apply_filter(sig, fn):
    out = collections.defaultdict(list)
    for d, lst in sig.items():
        keep = [s for s in lst if fn(s)]
        if keep: out[d] = keep
    return out


def main():
    db = sys.argv[1]; m0 = sys.argv[2]; m1 = sys.argv[3]
    by = load(db)
    TD = sorted({b[1] for bars in by.values() for b in bars if m0 <= b[1] <= m1})
    sig = signals(by, m0, m1)
    NT = load_notice_index()
    ind = json.load(open(f'{BASE}/ind_map.json'))
    sig = enrich(by, sig, NT, ind)
    last_buy = TD[-1]

    NEG = {'股东/实际控制人股份减持', '股份质押、冻结', '股票交易异常波动',
           '终止上市风险提示', '回复问询函公告', '风险提示'}

    variants = [
        ('A原版(无消息过滤)', lambda s: True),
        ('剔除有利空公告', lambda s: not (s['ntypes'] & NEG)),
        ('剔除异动公告', lambda s: '股票交易异常波动' not in s['ntypes']),
        ('只要有公告', lambda s: len(s['ntypes']) > 0),
        ('只要无公告', lambda s: len(s['ntypes']) == 0),
        ('同行业涨停≥3', lambda s: s.get('ind_zt', 0) >= 3),
        ('同行业涨停=1孤立', lambda s: s.get('ind_zt', 0) == 1),
        ('当日涨停≤80', lambda s: s.get('zt_today', 0) <= 80),
        ('当日涨停>80', lambda s: s.get('zt_today', 0) > 80),
        # 组合: 5-7月试跑中三个各自为正的条件叠加(⛔定稿前视为候选,须全年+样本外都过才算)
        ('组合:无公告+孤立+非过热', lambda s: len(s['ntypes']) == 0 and s.get('ind_zt', 0) <= 2 and s.get('zt_today', 0) <= 80),
        ('组合:仅剔利空+非过热', lambda s: not (s['ntypes'] & NEG) and s.get('zt_today', 0) <= 80),
    ]
    print('=' * 84)
    print('阶段2  A策略 ± 消息过滤器   区间 %s ~ %s' % (m0, m1))
    print('=' * 84)
    print('%-22s %10s %7s %8s %9s %9s' % ('变体', 'NAV', '笔数', '胜率%', '均值%', '最大单笔'))
    print('-' * 84)
    base_nav = None
    for name, fn in variants:
        s2 = apply_filter(sig, fn)
        nav, tr, log = run(by, s2, TD, last_buy)
        if not tr:
            print('%-22s %10s %7d' % (name, '无交易', 0)); continue
        nets = [t['net'] for t in tr]
        w = sum(1 for x in nets if x > 0) / len(nets) * 100
        if base_nav is None: base_nav = nav
        print('%-22s %10.4f %7d %8.1f %+9.2f %+9.2f' % (
            name, nav, len(tr), w, sum(nets) / len(nets), max(nets)))
    print('-' * 84)
    print('注: NAV起点1.0。含中金财富实际费率(印花0.05%%卖单边/过户0.001%%双边/佣金0.03%%双边最低5元)+滑点0.3%%单边')


main()
