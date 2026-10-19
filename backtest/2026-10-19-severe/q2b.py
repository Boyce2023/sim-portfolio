"""Q2 严格版: 收盘时10日窗口偏离落在 90% 到 100% 之间(贴着异动线但没破), 每段行情取第一次; 此前10日内已破线的不算"""
import pandas as pd, numpy as np, json, glob
A=pd.read_pickle('/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad/devpanel.pkl')
names={}
for f in glob.glob('../2026-10-09-theme/ths/*.json'):
    for x in json.load(open(f)): names[x['code']]=x['name']
ev=[]
for c,d in A.groupby('code'):
    d=d.reset_index(drop=True); last=-99
    hit=(d.m10>=0.9)&(d.m10<1.0)&(d.date>='2025-10-20')
    for i in np.where(hit)[0]:
        if i-last<10 or (d.m10.iloc[max(0,i-10):i]>=1.0).any(): continue
        last=i; base=d.adj_close[i]; fut=d.iloc[i+1:i+31]
        if len(fut)<20: continue
        up,prev=0,base
        for x in fut.adj_close.values:
            if x>prev*1.0000001: up+=1; prev=x
            else: break
        pk=int(fut.adj_close.values.argmax())
        trig=fut.m10.ge(1.0).values
        ev.append({'code':c,'name':names.get(c,c),'date':d.date[i],'当天涨幅':d.adj_close[i]/d.adj_close[i-1]-1,'偏离':d.m10[i],
                   '连涨':up,'高点天':pk+1,'高点收益':fut.adj_close.values[pk]/base-1,'破线':bool(trig.any()),'破线天':int(np.argmax(trig))+1 if trig.any() else None,
                   **{f'r{h}':d.adj_close[i+h]/base-1 for h in (1,3,5,10,20)},'n_open':d.open[i+1]*(d.adj_close[i+1]/d.close[i+1])/base-1})
Q=pd.DataFrame(ev); Q.to_pickle('q2b.pkl')
def s(x,lab):
    m=lambda c: x[c].median()*100
    print(f"{lab} n={len(x)} | 次日开盘中位{m('n_open'):+.1f}% | 之后连涨天数 均{x.连涨.mean():.1f} 0天{(x.连涨==0).mean()*100:.0f}% 1天{(x.连涨==1).mean()*100:.0f}% 2天以上{(x.连涨>=2).mean()*100:.0f}% | 30日内高点 第{x.高点天.median():.0f}天(中位) 涨{m('高点收益'):+.1f}%(中位) | 之后破线{x.破线.mean()*100:.0f}% | 中位 1日{m('r1'):+.1f}% 3日{m('r3'):+.1f}% 5日{m('r5'):+.1f}% 10日{m('r10'):+.1f}% 20日{m('r20'):+.1f}% | 20日收涨{(x.r20>0).mean()*100:.0f}%")
s(Q,'近一年'); s(Q[Q.date>='2026-07-01'],'7月以来'); s(Q[Q.破线],'之后破线的'); s(Q[~Q.破线],'之后没破线的')
s(Q[Q.当天涨幅>=0.05],'卡线当天涨5%以上'); s(Q[Q.当天涨幅<0.05],'卡线当天涨不到5%')
print('高点天数分布',pd.cut(Q.高点天,[0,1,2,3,5,10,20,30]).value_counts().sort_index().to_dict())
