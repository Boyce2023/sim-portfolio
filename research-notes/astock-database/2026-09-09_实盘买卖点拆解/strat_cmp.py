# -*- coding: utf-8 -*-
import json,sqlite3,itertools,numpy as np,pandas as pd,importlib.util,io,sys
spec=importlib.util.spec_from_file_location("eo","/tmp/dhbr/exit_opt.py"); old=sys.stdout; sys.stdout=io.StringIO(); eo=importlib.util.module_from_spec(spec); spec.loader.exec_module(eo); sys.stdout=old
# 用最新日线库(含到09-08)
con=sqlite3.connect('/tmp/dhbr/exit_bars.db'); K=pd.read_sql("select code,date,open,high,low,close from k",con); K['date']=pd.to_datetime(K['date']); K=K.sort_values(['code','date'])
eo.bars={c:g.reset_index(drop=True) for c,g in K.groupby('code')}
T=json.load(open('/tmp/dhbr/buwen_trades_all.json'))
B_all=[(pd.Timestamp(f"{t['date'][:4]}-{t['date'][4:6]}-{t['date'][6:]}"),t['code'],t['name'],t['qty'],t['price'],t['time']) for t in T if t['side']=='buy']
S_all=[(pd.Timestamp(f"{t['date'][:4]}-{t['date'][4:6]}-{t['date'][6:]}"),t['code'],t['name'],t['qty'],t['price']) for t in T if t['side']=='sell']
B2,S2=eo.load_aprmay(); B2=[(d,c,n,q,p,'') for d,c,n,q,p in B2]
def prev_ret(c,d):
    g=eo.bars.get(c); 
    if g is None: return np.nan
    i=g.index[g.date==d]
    if len(i)==0 or i[0]==0: return np.nan
    return (g.close.iloc[i[0]]/g.close.iloc[i[0]-1]-1)*100
def run(lots,SL,TP,N,TS,mode='close'):
    out=[]
    for d,c,n,q,p,tm in lots:
        r=eo.sim(c,d,p,SL,TP,N,TS,mode)
        if r: out.append((r[0],q*p,r[4]))
    r=np.array([o[0] for o in out]); cap=np.array([o[1] for o in out]); w=cap/cap.sum()
    return dict(mean=r.mean(),wmean=(r*w).sum(),yuan=(r/100*cap).sum(),win=(r>0).mean()*100,n=len(r),worst=r.min(),open=np.mean([o[2] for o in out])*100)
filters={'全部买点':lambda l:l,'只做前一日涨>5%':lambda l:[x for x in l if prev_ret(x[1],x[0])>5],'剔除前一日下跌的':lambda l:[x for x in l if not (prev_ret(x[1],x[0])<0)],'剔除10点档买入':lambda l:[x for x in l if not str(x[5]).startswith('10')]}
rules=[('你实际(基准)',None),('T+6 止损8%',(0.08,None,6,None)),('T+5 无止损',(None,None,5,None)),('T+5 止损5%',(0.05,None,5,None)),('T+5 止损7%',(0.07,None,5,None)),('T+3 无止损',(None,None,3,None)),('T+3 止损7%',(0.07,None,3,None)),('T+10 止损7%',(0.07,None,10,None)),('止损5% 不设止盈 不限时',(0.05,None,None,None)),('止损5% 止盈30%',(0.05,0.30,None,None)),('T+5 止损7% 移动8%',(0.07,None,5,0.08)),('T+5 止盈5%',(None,0.05,5,None))]
for pname,B,S in [('8月到9月(139买点)',B_all,S_all),('4到5月(58买点)',B2,[(d,c,n,q,p) for d,c,n,q,p in S2])]:
    print(f"\n════════ {pname} ════════")
    # 基准
    rt,openl=eo.fifo([(d,c,n,q,p) for d,c,n,q,p,_ in B],S)
    base=[((r['sp']/r['bp']-1)*100-0.123,r['q']*r['bp']) for r in rt]
    for o in openl:
        g=eo.bars.get(o['code']); 
        if g is not None: base.append(((g.close.iloc[-1]/o['bp']-1)*100-0.123,o['q']*o['bp']))
    ba=np.array(base); print(f"  基准(你的实际): 等权{ba[:,0].mean():+.2f}% 金额加权{(ba[:,0]*ba[:,1]/ba[:,1].sum()).sum():+.2f}% 合计{(ba[:,0]/100*ba[:,1]).sum():+,.0f}元 胜率{(ba[:,0]>0).mean()*100:.0f}%")
    for fname,fn in filters.items():
        lots=fn(B)
        print(f"\n  ── 入场过滤: {fname} ({len(lots)}笔) ──")
        print(f"  {'规则':<22}{'等权%':>8}{'加权%':>8}{'合计元':>10}{'胜率':>6}{'最差%':>7}{'未平%':>5}")
        for rn,rl in rules[1:]:
            x=run(lots,*rl); print(f"  {rn:<22}{x['mean']:>+8.2f}{x['wmean']:>+8.2f}{x['yuan']:>+10,.0f}{x['win']:>5.0f}%{x['worst']:>+7.1f}{x['open']:>5.0f}")
