"""⛔检验: B核心规则里的'量比<1.5'是事后变量吗? 换成买入前可知的口径后edge还在吗?

背景(2026-09-04实盘发现): 09-03定的B核心过滤是"前1日涨>3% 且 当日量比<1.5",
四期胜率84/80/80/79%。但"当日量比"=当日全天成交量/前5日均量——**收盘才知道**,
而B在盘中触板瞬间(如09:32)买入,那时拿不到全天量。这是lookahead bias。

本脚本对同一批1001笔样本,把过滤条件里的 vr 换成三种买入前可知的口径,看胜率是否幸存:
  A. vr_prev  = 前1日成交量 / 前2-6日均量        (完全前视无关)
  B. vr_open  = 当日开盘半小时估计 —— 日线数据做不到,标记为不可测
  C. 无量比    = 只用"前1日涨>3%"                 (对照)
"""
import json,sqlite3,collections,statistics as st,sys
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
from engine_b2 import build
from strategy_b2 import PARAMS_B2 as P
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
def fee(a,sell): return max(a*P['comm'],P['comm_min'])+a*P['transfer']+(a*P['stamp'] if sell else 0)
def rows_for(db,m0,m1,tag):
    by,sig,mood=build(db,m0,m1)
    con=sqlite3.connect(db); k=collections.defaultdict(list)
    for r in con.execute("select code,date,open,high,low,close,preclose,volume,amount,turn from k order by code,date"): k[r[0]].append(r)
    out=[]
    for d,lst in sig.items():
        for t in sorted(lst,key=lambda x:x['rank'])[:P['max_positions']]:
            bars=k.get(t['code']); 
            if not bars: continue
            idx=[i for i,b in enumerate(bars) if b[1]==d]
            if not idx or idx[0]<21: continue
            i=idx[0]; b=bars[i]
            cap=1e6/3; sh=int(cap/t['buy']/100)*100
            if sh<=0: continue
            ba=sh*t['buy']; sa=sh*t['sell']*(1-P['slip_sell']); net=(sa-ba-fee(ba,False)-fee(sa,True))/cap*100
            v5=st.mean([x[7] for x in bars[i-5:i]])          # 前5日均量(买入前可知)
            v5p=st.mean([x[7] for x in bars[i-6:i-1]])       # 前2-6日均量
            out.append(dict(tag=tag,d=d,code=t['code'],net=net,
                pre1=(bars[i-1][5]/bars[i-1][6]-1)*100,
                vr_today=b[7]/v5 if v5 else 0,               # ⚠️事后变量(原规则用的)
                vr_prev=bars[i-1][7]/v5p if v5p else 0))     # ✅买入前可知
    return out
R=[]
R+=rows_for(B+'univ2025.db','2025-01-01','2025-06-30','25H1')
R+=rows_for(B+'univ2025.db','2025-07-01','2025-12-31','25H2')
for m in ['01','02','03']: R+=rows_for(B+f'univ2026{m}.db',f'2026-{m}-01',f'2026-{m}-31','26Q1')
for m in ['04','05','06']: R+=rows_for(B+f'univ2026{m}.db',f'2026-{m}-01',f'2026-{m}-31','26Q2')
json.dump(R,open('/tmp/vr_rows.json','w'))
tags=['25H1','25H2','26Q1','26Q2']
def rep(name,f):
    print(f"\n{name}")
    print(f"  {'期':<6}{'笔数':>5}{'胜率':>7}{'均收益':>8}")
    worst=1
    for t in tags:
        s=[r for r in R if r['tag']==t and f(r)]
        if len(s)<10: print(f"  {t:<6}{len(s):>5}   样本不足"); worst=0; continue
        w=sum(1 for r in s if r['net']>0)/len(s); m=st.mean(r['net'] for r in s)
        worst=min(worst,w)
        print(f"  {t:<6}{len(s):>5}{w:>6.0%}{m:>+8.2f}%")
    print(f"  最差期胜率 {worst:.0%}")
print(f"样本 {len(R)} 笔"); 
rep("基线(全部)",lambda r: True)
rep("原规则: 前1日涨>3% 且 当日量比<1.5  ⚠️含事后变量",lambda r: r['pre1']>3 and r['vr_today']<1.5)
rep("替代A: 前1日涨>3% 且 前1日量比<1.5  ✅买入前可知",lambda r: r['pre1']>3 and r['vr_prev']<1.5)
rep("对照C: 只用 前1日涨>3%",lambda r: r['pre1']>3)
