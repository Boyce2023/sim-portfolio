# -*- coding: utf-8 -*-
import csv,json,sqlite3,time,warnings,numpy as np,pandas as pd; warnings.filterwarnings('ignore')
from collections import defaultdict,deque
# ── 1 合并
R2=[]
for fn,side in [('buys','buy'),('sells','sell')]:
    for r in csv.DictReader(open(f'/Users/huaichuaibeimeng/claude-projects/trading-journal/data/{fn}_202608.csv',encoding='utf-8-sig')):
        R2.append(dict(date=r['date'],time='',code=r['code'],name=r['name'],side=side,price=float(r['price']),qty=int(float(r['qty'])),amount=float(r['price'])*int(float(r['qty']))))
S=json.load(open('/tmp/dhbr/shots_trades.json'))
for r in S:
    if r['name']=='红利ETF易方达': r['code']='515180'
allt={}
for r in R2+S:
    k=(r['date'],r['code'],r['side'],r['qty'],round(r['price'],3))
    if k in allt:
        if r['time'] and not allt[k]['time']: allt[k]['time']=r['time']
        continue
    allt[k]=r
T=sorted(allt.values(),key=lambda r:(r['date'],r['time'] or '00:00:00'))
print(f"合并后 {len(T)} 笔 ({min(r['date'] for r in T)}~{max(r['date'] for r in T)}); 买{sum(1 for r in T if r['side']=='buy')} 卖{sum(1 for r in T if r['side']=='sell')} 标的{len({r['code'] for r in T})}")
json.dump(T,open('/tmp/dhbr/buwen_trades_all.json','w'),ensure_ascii=False,indent=0)
# ── 2 日线补齐
import akshare as ak
con=sqlite3.connect('/tmp/dhbr/exit_bars.db')
have={r[0] for r in con.execute("select code from (select code,min(date) mn from k group by code) where mn<='2026-07-02'")}
codes=sorted({r['code'] for r in T}); need=[c for c in codes if c not in have]; bad=[]
for c in need:
    if c[0] in '15': 
        try:
            df=ak.fund_etf_hist_sina(symbol=('sh' if c[0]=='5' else 'sz')+c); df=df[(df['date'].astype(str)>='2026-07-01')]
            con.executemany("insert or replace into k values(?,?,?,?,?,?,?)",[(c,str(r['date'])[:10],float(r['open']),float(r['high']),float(r['low']),float(r['close']),float(r['volume'])) for _,r in df.iterrows()]); con.commit(); continue
        except Exception as e: bad.append((c,str(e)[:40])); continue
    sym=('sh' if c[0]=='6' else 'sz')+c
    for att in range(3):
        try:
            df=ak.stock_zh_a_daily(symbol=sym,start_date='20260701',end_date='20260908',adjust='qfq')
            con.executemany("insert or replace into k values(?,?,?,?,?,?,?)",[(c,str(r['date'])[:10],float(r['open']),float(r['high']),float(r['low']),float(r['close']),float(r['volume'])) for _,r in df.iterrows()]); con.commit(); break
        except Exception as e:
            if att==2: bad.append((c,str(e)[:40]))
            time.sleep(1)
    time.sleep(0.15)
print("补拉",len(need),"只; 失败",bad)
K=pd.read_sql("select code,date,open,high,low,close from k",con); K['date']=pd.to_datetime(K['date']); K=K.sort_values(['code','date'])
bars={c:g.reset_index(drop=True) for c,g in K.groupby('code')}
missing=[c for c in codes if c not in bars]; print("仍缺日线:",missing)
# ── 3 FIFO
FEE_B,FEE_S=0.00036,0.00086
lots=defaultdict(deque); rt=[]
for r in T:
    d=pd.Timestamp(f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:]}")
    if r['side']=='buy': lots[r['code']].append([d,r['price'],r['qty'],r['name'],r['time']])
    else:
        rem=r['qty']
        while rem>0 and lots[r['code']]:
            l=lots[r['code']][0]; take=min(rem,l[2])
            rt.append(dict(code=r['code'],name=r['name'],bd=l[0],bp=l[1],bt=l[4],sd=d,sp=r['price'],st=r['time'],q=take)); l[2]-=take; rem-=take
            if l[2]==0: lots[r['code']].popleft()
        if rem>0: rt.append(dict(code=r['code'],name=r['name'],bd=None,bp=None,bt='',sd=d,sp=r['price'],st=r['time'],q=rem))
openl=[dict(code=c,name=l[3],bd=l[0],bp=l[1],q=l[2]) for c,dq in lots.items() for l in dq]
def bar(c,d):
    g=bars.get(c); 
    if g is None: return None
    x=g[g.date==d]; return x.iloc[0] if len(x) else None
def close_after(c,d,n):
    g=bars.get(c); 
    if g is None: return None
    x=g[g.date>d].head(n)
    return x.close.iloc[-1] if len(x)>=n else None
rows=[]
for r in rt:
    if r['bd'] is None: continue
    b=bar(r['code'],r['bd']); s=bar(r['code'],r['sd']); g=bars.get(r['code'])
    if b is None or s is None: continue
    pnl=(r['sp']*(1-FEE_S)-r['bp']*(1+FEE_B))*r['q']
    hold=int(((g.date>r['bd'])&(g.date<=r['sd'])).sum())
    c5=close_after(r['code'],r['bd'],5); last=g.close.iloc[-1]
    rows.append(dict(**{k:r[k] for k in ('code','name','bd','bp','bt','sd','sp','st','q')},cap=r['bp']*r['q'],pnl=pnl,ret=(r['sp']/r['bp']-1)*100-0.123,hold=hold,
        entry_vs_close=(b.close/r['bp']-1)*100, entry_vs_open=(b.open/r['bp']-1)*100, entry_pos=((r['bp']-b.low)/(b.high-b.low)*100 if b.high>b.low else 50),
        exit_vs_close=(r['sp']/s.close-1)*100, exit_pos=((r['sp']-s.low)/(s.high-s.low)*100 if s.high>s.low else 50),
        stock_c2c=(s.close/b.close-1)*100, hold5=((c5/r['bp']-1)*100-0.123) if c5 else None, to_now=(last/r['bp']-1)*100-0.123,
        auction_sell=(r['st']=='09:25:00'), same_or_next_day=(hold<=1)))
D=pd.DataFrame(rows)
# 未卖lot按09-08收盘
op=[]
for o in openl:
    g=bars.get(o['code']); 
    if g is None: continue
    op.append(dict(code=o['code'],name=o['name'],bd=o['bd'],bp=o['bp'],q=o['q'],cap=o['bp']*o['q'],mkt=g.close.iloc[-1],pnl=(g.close.iloc[-1]-o['bp']*(1+FEE_B))*o['q'],ret=(g.close.iloc[-1]/o['bp']-1)*100))
O=pd.DataFrame(op)
D.to_pickle('/tmp/dhbr/diag_rt.pkl'); O.to_pickle('/tmp/dhbr/diag_open.pkl')
print(f"\n配对round-trip {len(D)}笔, 未平仓lot {len(O)}个")
print(f"已实现: 合计 {D.pnl.sum():+,.0f}元 | 等权{D.ret.mean():+.2f}% 中位{D.ret.median():+.2f}% 胜率{(D.ret>0).mean()*100:.0f}% | 均持{D.hold.mean():.1f}个交易日")
print(f"未平仓浮动: {O.pnl.sum():+,.0f}元 ({len(O)}个lot, 成本{O.cap.sum():,.0f})")
print(f"总计(已实现+浮动): {D.pnl.sum()+O.pnl.sum():+,.0f}元")
print("\n【A 选股本身】同一持有窗口内股票收盘到收盘: 等权",f"{D.stock_c2c.mean():+.2f}%","| 若买入后持5日:",f"{D.hold5.dropna().mean():+.2f}%","| 拿到09-08:",f"{D.to_now.mean():+.2f}% (胜率{(D.to_now>0).mean()*100:.0f}%)")
print("【B 入场时点】买价相对当日收盘:",f"{D.entry_vs_close.mean():+.2f}%","(负=买在当日收盘之上); 买价在当日振幅中的位置(0=最低 100=最高):",f"{D.entry_pos.mean():.0f}")
print("【C 出场时点】卖价相对当日收盘:",f"{D.exit_vs_close.mean():+.2f}%","(负=卖在当日收盘之下); 卖价在当日振幅位置:",f"{D.exit_pos.mean():.0f}")
a=D[D.auction_sell]; print(f"   其中 09:25集合竞价卖出 {len(a)}笔: 卖价vs当日收盘 {a.exit_vs_close.mean():+.2f}%, 合计盈亏 {a.pnl.sum():+,.0f}元, 若改当日收盘卖 {((a.sp/(1+a.exit_vs_close/100))*(1-FEE_S)*a.q - a.bp*(1+FEE_B)*a.q).sum():+,.0f}元")
print(f"【D 持有期】≤1个交易日就卖的 {int(D.same_or_next_day.sum())}笔: 盈亏{D[D.same_or_next_day].pnl.sum():+,.0f}元, 等权{D[D.same_or_next_day].ret.mean():+.2f}%; 持有>1日的{int((~D.same_or_next_day).sum())}笔: {D[~D.same_or_next_day].pnl.sum():+,.0f}元, {D[~D.same_or_next_day].ret.mean():+.2f}%")
# 反复进出: 同一票多轮
per=D.groupby('name').agg(n=('pnl','size'),pnl=('pnl','sum'),cap=('cap','sum'),ret=('ret','mean')).sort_values('pnl')
print("\n【E 分票盈亏(已实现)】亏最多前8:"); print(per.head(8).round(0).to_string())
print("赚最多前5:"); print(per.tail(5).round(0).to_string())
fees=(D.cap*FEE_B+D.sp*D.q*FEE_S).sum(); print(f"\n手续费+印花税合计 {fees:,.0f}元 (占已实现亏损的{fees/abs(D.pnl.sum())*100:.0f}%)" if D.pnl.sum()<0 else f"\n费用 {fees:,.0f}元")
