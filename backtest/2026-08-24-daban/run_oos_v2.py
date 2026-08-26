#!/usr/bin/env python3
"""2026年1月样本外 v2 — 真实资金曲线
规则(用户2026-08-25定):
  ①每天最多选3只(按信号强度排序),选了就等权打满仓; 无信号则空仓
  ②持仓期间不换股; 出场后当日收盘才可再选新的(A股T+1,当日买入次日才能卖)
  ③两套出场: A=第一个非涨停日收盘出 / B=第一个下跌日收盘出
成本: 印花税0.05%(卖出单边) + 佣金万三(双边) + 滑点0.3%(单边,打板股竞价冲击大)
策略参数在2025样本内锁死,不调参
"""
import sqlite3,json,statistics
from collections import defaultdict
BASE='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'
con=sqlite3.connect(f'{BASE}/univ202601.db')
STAMP=0.0005; COMM=0.0003; SLIP=0.003
def lim_pct(c):
    b=c.split('.')[1]
    if b.startswith(('30','68')): return 0.20
    if b.startswith(('8','4','92')): return 0.30
    return 0.10

rows=con.execute("select code,date,open,high,low,close,preclose,turn,isST from k where preclose>0 order by code,date").fetchall()
bycode=defaultdict(list); alldates=set()
for r in rows: bycode[r[0]].append(r); alldates.add(r[1])
idx={c:{b[1]:i for i,b in enumerate(bars)} for c,bars in bycode.items()}
TD=sorted(d for d in alldates if '2026-01-01'<=d<='2026-02-10')

# 生成信号(策略参数锁死)
sigs=defaultdict(list)
for code,bars in bycode.items():
    lp0=lim_pct(code)
    for i,b in enumerate(bars):
        _,d,o,h,l,c,pc,turn,st=b
        if not ('2026-01-01'<=d<='2026-01-31'): continue
        lp=0.05 if st else lp0
        lim=round(pc*(1+lp),2)
        if abs(c-lim)>=0.005: continue
        if abs(o-lim)<0.005 and abs(l-lim)<0.005: continue   # 一字剔除
        # ⛔2026-08-25 数据清洗: baostock在部分票上有复权因子异常/退市停牌脏数据。
        # 实例 sz.300344 价格序列 0.67→0.80→0.96→1.15(单日+19.4%/+20.0%/+19.8%),
        #      sz.300391 0.44→0.53→0.64→0.77 后连续7日完全不动(0.92)。
        # 主板/创业板股票不可能是0.44-0.67元, 这类小数价上 close==round(preclose*1.2,2)
        # 会大量误判成涨停, 把脏数据喂进信号池——未清洗前跑出+91%/+107%的假收益。
        if c < 2.0: continue                    # 剔除异常低价(A股面值退市线1元,正常票极少<2元)
        if turn is not None and turn <= 0: continue   # 剔除零换手(停牌/无成交)
        streak=1; j=i-1
        while j>=0:
            pb=bars[j]; lpj=0.05 if pb[8] else lp0
            if pb[6]>0 and abs(pb[5]-round(pb[6]*(1+lpj),2))<0.005: streak+=1; j-=1
            else: break
        k=max(0,i-20); g20=(c/bars[k][5]-1)*100 if bars[k][5]>0 else None
        if i+1>=len(bars): continue
        buy=bars[i+1][2]
        if buy<=0: continue
        gap1=(buy/c-1)*100
        if gap1<=0 and streak<=3 and g20 is not None and g20>=50:
            # 信号强度: gap越低(越不高开)越优先, 其次20日涨幅越大越优先
            sigs[bars[i+1][1]].append({'code':code,'sig_date':d,'buy':buy,'gap1':gap1,
                                       'g20':g20,'streak':streak,'rank':(gap1,-g20)})

def run(exit_mode,maxn=3):
    nav=1.0; cash=True; hold=[]; log=[]; trades=[]
    for di,d in enumerate(TD):
        if hold:
            # 检查出场
            out=[]
            for h in hold:
                bars=bycode[h['code']]; i=idx[h['code']].get(d)
                if i is None: continue
                b=bars[i]; lp=0.05 if b[8] else lim_pct(h['code'])
                is_lim=abs(b[5]-round(b[6]*(1+lp),2))<0.005
                is_up=b[5]>b[6]
                held_days=(d>h['buy_date'])
                if not held_days: continue          # T+1不能卖
                sell = (not is_lim) if exit_mode=='A' else (not is_up)
                if sell: out.append((h,b[5]))
            # ⛔2026-08-25修bug: 原为 len(out)==len(hold) 才结算,导致3只里只有1-2只触发出场时
            # 全部继续持有——规则A"第一个非涨停日出"被架空,出现01-22买入持有到01-30净+43%的
            # 不可能结果(6个交易日全涨停)。正确做法: 逐只独立出场,按仓位权重结算。
            if out:
                w=1.0/len(hold)                       # 等权,每只占仓位1/N
                for h,px in out:
                    g=px/h['buy']-1
                    net=(1+g)*(1-SLIP-COMM)*(1-SLIP-COMM-STAMP)-1
                    nav*=(1+net*w)                    # 只有该只对应的仓位份额参与结算
                    trades.append({'code':h['code'],'buy_date':h['buy_date'],'sell_date':d,
                        'gross':g*100,'net':net*100,'days':TD.index(d)-TD.index(h['buy_date'])})
                outset={id(h) for h,_ in out}
                log.append((d,'SELL',len(out),statistics.mean([t['net'] for t in trades[-len(out):]]),nav))
                hold=[h for h in hold if id(h) not in outset]
        if not hold and d in sigs and d<='2026-01-30':
            cand=sorted(sigs[d],key=lambda x:x['rank'])[:maxn]
            if cand:
                for c in cand: c['buy_date']=d
                hold=cand
                log.append((d,'BUY',len(cand),0,nav))
    # 月末强制平仓
    if hold:
        d=TD[-1]; out=[]
        for h in hold:
            i=idx[h['code']].get(d)
            if i is not None: out.append((h,bycode[h['code']][i][5]))
        if out:
            r=statistics.mean([(px/h['buy']-1) for h,px in out])
            net=(1+r)*(1-SLIP-COMM)*(1-SLIP-COMM-STAMP)-1; nav*=(1+net)
            log.append((d,'SELL(月末)',len(out),net*100,nav))
    return nav,log,trades

for mode,name in [('A','第一个非涨停日出'),('B','第一个下跌日出')]:
    nav,log,tr=run(mode)
    print('='*78); print(f'出场规则{mode}: {name}'); print('='*78)
    for d,act,n,net,v in log:
        print(f'  {d} {act:<10} {n}只  {"" if act=="BUY" else f"净{net:+6.2f}%"}  NAV {v:.4f}')
    days=[t['days'] for t in tr]
    wins=[t for t in tr if t['gross']>0]
    print(f'\n  最终NAV {nav:.4f}  → 月收益 {(nav-1)*100:+.2f}%')
    print(f'  完成交易 {len(tr)}笔 | 胜率{len(wins)/max(len(tr),1)*100:.1f}% | 平均持有{statistics.mean(days) if days else 0:.1f}天')
    print()
# 基准
b0=con.execute("select close from k where code='sh.000001' and date<=? order by date desc limit 1",('2026-01-05',)).fetchone()
print('说明: 成本=印花税0.05%(卖出)+佣金万三(双边)+滑点0.3%(单边)')
