#!/opt/homebrew/bin/python3.13
"""首板那天的封板速度 与 后续2到4板时晋级的关系. 首板日 = 当前日往前推(N-1)个交易日; 封板时间取同花顺涨停池 first_limit_up_time"""
import json,glob,pandas as pd,numpy as np
H=pd.read_pickle('H.pkl')
ft={}
for f in sorted(glob.glob('../2026-10-09-theme/ths/2026*.json')):
    d=pd.Timestamp(f.split('/')[-1][:8])
    for r in json.load(open(f)):
        t=pd.Timestamp(int(r.get('first_limit_up_time') or 0),unit='s',tz='UTC').tz_convert('Asia/Shanghai')
        ft[(d,r['code'])]=(t.hour*60+t.minute, r.get('limit_up_type'))
cal=sorted({k[0] for k in ft})
def first_day(d,lb):
    i=cal.index(d)-(lb-1); return cal[i] if i>=0 else None
H['首板日']=[first_day(d,lb) for d,lb in zip(H.date,H.lb)]
H['首板封板分钟']=[ft.get((fd,c),(np.nan,None))[0] for fd,c in zip(H.首板日,H.code)]
H['首板一字']=[ft.get((fd,c),(np.nan,''))[1]=='一字板' for fd,c in zip(H.首板日,H.code)]
H=H[H.首板封板分钟.notna()]
def bucket(m,yz):
    if yz: return '1 首板一字'
    if m<=9*60+45: return '2 09:45前'
    if m<=10*60+30: return '3 09:45到10:30'
    if m<=13*60: return '4 10:30到午盘'
    return '5 下午'
H['首板速度']=[bucket(m,y) for m,y in zip(H.首板封板分钟,H.首板一字)]
print('样本',len(H))
for lb in ('全部',2,3,4):
    h=H if lb=='全部' else H[H.lb==lb]
    T=h.groupby(['首板速度']).agg(样本=('晋级','size'),晋级率=('晋级','mean'))
    T2=h.groupby(['首板速度','段']).晋级.mean().unstack()
    print(f'\n== {lb}板 =='); print(pd.concat([T,T2],axis=1).assign(晋级率=lambda x:(x.晋级率*100).round(0),**{'7-8月':lambda x:(x['7-8月']*100).round(0),'9-10月':lambda x:(x['9-10月']*100).round(0)}).to_string())
# 组内: 首板封得最早的那只
print('\n== 同高度组内, 首板那天封板最早的那只 ==')
for seg in ('全部','7-8月','9-10月'):
    sel=[];base=[];w=n=0
    for _,g in H.groupby(['date','lb']):
        if len(g)<2 or (seg!='全部' and g.段.iloc[0]!=seg): continue
        v=g.首板封板分钟
        if (v==v.min()).sum()>1: continue
        s=g[v==v.min()].iloc[0]; o=g[v!=v.min()]
        sel.append(s.晋级); base.append(g.晋级.mean())
        if s.晋级!=o.晋级.mean(): n+=1; w+=s.晋级>o.晋级.mean()
    print(f'{seg}: 组 {len(sel)}, 首板最早那只晋级 {np.mean(sel):.0%}, 组均 {np.mean(base):.0%}, 分化占优 {w}/{n}')
# 控制封单与换手后还有没有增量
import statsmodels.api as sm
A=pd.read_pickle('A.pkl')[['date','code','lb','r_seal','r_turn','段','晋级']].merge(H[['date','code','首板封板分钟']],on=['date','code'])
A['r_speed']=A.groupby(['date','lb']).首板封板分钟.rank(pct=True,ascending=False)
for seg in ('7-8月','9-10月'):
    a=A[A.段==seg].dropna(); m=sm.Logit(a.晋级,sm.add_constant(a[['r_seal','r_turn','r_speed']])).fit(disp=0)
    print(seg,'样本',len(a),{k:(round(m.params[k],2),round(m.pvalues[k],3)) for k in ['r_seal','r_turn','r_speed']})
