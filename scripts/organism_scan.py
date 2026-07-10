#!/usr/bin/env python3
"""
有机体扫描 · 收盘建仓计划 · 2026-07-10
非持仓候选 → 收盘择时信号(timing_signals) × 选股conviction × decide_buy → 建仓计划
regime=缩圈(今日半导体总攻+breadth负) → sizing×0.5
⚠️首过滤: conviction来自30板块选股agent(非逐只深研),edge_real默认True/peg默认薄——建仓计划是"时机对+基本面初筛过关"的候选,top标的实际建仓前仍需逐只深研
"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timing_signals import _kline, trend_signals
from organism_decision import decide_buy, CONV_CAP, REGIME_MULT

HOLDINGS={'688072','002049','000049','603505','603662','605020','600160','002025'}
REGIME='缩圈'   # 今日: 半导体总攻+全A跌多于涨=缩圈
uni=json.load(open('/tmp/universe.json'))

buy=[]; watch=[]; ok=fail=0
for u in uni:
    t=str(u.get('ticker',''))[:6]
    if t in HOLDINGS or not t.isdigit(): continue
    conv=u.get('conviction','B+')
    if conv not in ('A+','A','A-'): continue   # 建仓门槛A-以上
    try:
        bars=_kline(t,40); tr=trend_signals(bars)
        if not tr: fail+=1; continue
        sv={'fundamental':{'sabct':conv,'edge_real':True,'peg_margin':'薄','tree_node':u.get('sector','')},
            'trend':tr,'hold_nature':'趋势追高仓','regime':{'water_level':REGIME}}
        d=decide_buy(sv)
        rec={'t':t,'name':u.get('name'),'conv':conv,'sector':u.get('sector','')[:14],
             'chg':tr.get('今日涨跌%'),'vp':tr.get('量价结构'),'dist_bk':tr.get('距前高突破%'),
             'is_bk':tr.get('是否突破前高'),'limit_up':(tr.get('今日涨跌%') or 0)>=9.8,'d':d}
        if d['action']=='probe/买': buy.append(rec)
        elif d['action']=='watch': watch.append(rec)
        ok+=1
    except Exception: fail+=1
    if (ok+fail)%40==0: print(f"  ...{ok+fail}", flush=True)

CO={'A+':0,'A':1,'A-':2}
buy.sort(key=lambda r:(CO.get(r['conv'],9), -(r['dist_bk'] or -99)))
print(f"\n载入ok={ok} fail={fail} | 可建仓candidate={len(buy)} watch={len(watch)}")
print(f"\n{'='*96}\n建仓计划(缩圈regime·sizing×0.5) · 收盘 · 非持仓 · conviction×择时×decide_buy\n{'='*96}")
print(f"{'标的':<10}{'信心':<4}{'今涨%':>7}{'量价':<8}{'距突破%':>8}{'仓位':>6}{'止损':<8}{'板块':<14}{'涨停?':<5}")
for r in buy[:30]:
    size=r['d'].get('size_pct',0)
    print(f"{r['name'][:8]:<9}{r['conv']:<4}{r['chg']:>6}%{r['vp']:<8}{r['dist_bk']:>7}%{size*100:>5.0f}%{'技术':<8}{r['sector']:<14}{'涨停' if r['limit_up'] else '':<5}")
print(f"\n--- WATCH(基本面过但时机未到/末段,等回踩,{len(watch)}只TOP10) ---")
for r in watch[:10]:
    print(f"  {r['name'][:8]:<9}{r['conv']:<4}{r['chg']:>6}% {r['vp']:<8} {r['d']['reason'][:40]}")
json.dump({'buy':buy,'watch':watch,'regime':REGIME}, open('/tmp/build_plan.json','w'), ensure_ascii=False)
print("\n已存 /tmp/build_plan.json")
