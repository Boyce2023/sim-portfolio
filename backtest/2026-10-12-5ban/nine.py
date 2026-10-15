#!/opt/homebrew/bin/python3.13
"""7月以来每只五板股: 首板到五板(5天)+五板后4天, 共9天的换手与涨跌; 再看三板、四板换手高低与五板后表现的关系.
五板后表现口径: ①次日开盘买(开盘一字买不到)T+2收盘卖 ②次日是否晋级六板 ③五板收盘到T+4收盘."""
import pandas as pd,numpy as np
from common import panel
P=panel('2026-05-01')
T=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','turn'],filters=[('date','>=',pd.Timestamp('2026-05-01'))])
P=P.merge(T,on=['date','ticker'],how='left').sort_values(['code','date']).reset_index(drop=True)
g=P.groupby('code')
P['chg']=P.close*P.adjf/P.prevc/P.adjf-1   # prevc 已换算到当日口径
P['chg']=P.close/P.prevc-1
for k in range(-4,5):
    if k==0: continue
    P[f'turn{k}']=g.turn.shift(-k); P[f'chg{k}']=g.chg.shift(-k)
E=P[(P.streak==5)&(P.date>='2026-07-01')&(P.nth>=5)].copy()
E['六板']=E.zt1==1 if 'zt1' in E else np.nan
E['六板']=g.zt.shift(-1).reindex(E.index)
E['yizi1']=(E.open1>=E.zt_px1-0.011)&(E.low1>=E.zt_px1-0.011)
buy=E.open1*E.adjf1
E['开买T+2收']=np.where(E.yizi1|E.open1.isna(),np.nan,E.close2*E.adjf2/buy-1)
E['五板收到T+4收']=E.close4*E.adjf4/(E.close*E.adjf)-1
cols={}
for i,k in enumerate([-4,-3,-2,-1,0,1,2,3,4]):
    lab=['首板','二板','三板','四板','五板','T+1','T+2','T+3','T+4'][i]
    cols[lab+'换手%']=(E[f'turn{k}'] if k!=0 else E.turn)*100
    cols[lab+'涨跌%']=(E[f'chg{k}'] if k!=0 else E.chg)*100
out=pd.DataFrame({'五板日':E.date.dt.strftime('%Y-%m-%d'),'代码':E.code,'名称':''},index=E.index)
import json,glob
names={}
for f in glob.glob('../2026-10-09-theme/ths/2026*.json'):
    for r in json.load(open(f)): names[r['code']]=r['name']
out['名称']=out.代码.map(names)
for c,v in cols.items(): out[c]=v.round(2)
out['次日一字买不到']=E.yizi1.map({True:'是',False:''})
out['次日晋级六板']=E['六板'].map({True:'是',False:'否'})
out['次日开盘买T+2收盘卖%']=(E['开买T+2收']*100).round(2)
out['五板收盘到T+4收盘%']=(E['五板收到T+4收']*100).round(2)
out=out.sort_values('五板日').reset_index(drop=True)
out.to_pickle('nine.pkl')
print('五板事件',len(out),'区间',out.五板日.min(),out.五板日.max())
# 分析: 三板/四板换手高低
def summ(m,lab):
    s=out[m]; v=s['次日开盘买T+2收盘卖%'].dropna()
    return f"{lab}: 事件{len(s)} 六板晋级{(s.次日晋级六板=='是').mean()*100:.0f}% | 可买{len(v)}笔 胜率{(v>0).mean()*100:.0f}% 均{v.mean():+.1f}% 中位{v.median():+.1f}% | 五板到T+4均{s['五板收盘到T+4收盘%'].mean():+.1f}%"
for b in ['三板','四板']:
    med=out[b+'换手%'].median(); print(f'\n{b}换手中位数 {med:.1f}%')
    print(summ(out[b+'换手%']>med,f'  {b}换手高于中位'))
    print(summ(out[b+'换手%']<=med,f'  {b}换手低于中位'))
    for th in (10,20):
        print(summ(out[b+'换手%']>th,f'  {b}换手>{th}%')); print(summ(out[b+'换手%']<=th,f'  {b}换手<={th}%'))
m=(out['三板换手%']>out['三板换手%'].median())|(out['四板换手%']>out['四板换手%'].median())
print(); print(summ(m,'三板或四板任一高换手')); print(summ(~m,'三板四板都低换手'))
print(summ(out['五板换手%']>out['五板换手%'].median(),'五板当日换手高于中位')); print(summ(out['五板换手%']<=out['五板换手%'].median(),'五板当日换手低于中位'))
