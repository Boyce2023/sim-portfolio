import pandas as pd, numpy as np
e=pd.read_pickle('/tmp/e_data.pkl'); w=pd.read_pickle('/tmp/w2_types.pkl')
e['date']=pd.to_datetime(e['date'])
def z(a,na,b,nb):
    if na==0 or nb==0: return np.nan
    p=(a*na+b*nb)/(na+nb); s=(p*(1-p)*(1/na+1/nb))**.5
    return (a-b)/s if s>0 else np.nan
print("原版（用全期2024-2025分型，含未来信息）")
f=e[e['类型']=='财报型']
A=f[~f.buy]; B=f[f.buy]
a,b=(A.d252>0).mean(),(B.d252>0).mean()
print("  财报型 不买 %d个 %.0f%% | 会买 %d个 %.0f%% | 差 %.1fpp | z=%.2f"%(len(A),a*100,len(B),b*100,(b-a)*100,z(b,len(B),a,len(A))))

print()
print("=== 前视审计：改用'事件发生当时可知'的分型 ===")
print("做法：每个事件只用它发生日之前的跳涨历史来定型，未来的跳涨不算")
# 需要原始跳涨全表；用e_data里的财报日跳涨 + w2的总次数无法回溯。改用可得的近似：
# 用同一只股票在该事件之前已发生的【财报日跳涨次数】占比做PIT分型代理
e=e.sort_values('date')
rows=[]
for i,r in e.iterrows():
    prior=e[(e.t==r.t)&(e.date<r.date)]
    rows.append(len(prior))
e['prior_er_jumps']=rows
print()
print("样本内每只股票的财报日跳涨事件数分布：")
print(e.groupby('t').size().value_counts().sort_index().to_string())
print()
print("关键问题：分型判据是'财报日占比≥40%'，分母是【全期所有跳涨】(含非财报跳涨898次)")
print("而事件发生当天，后面的跳涨还没发生 → 分型使用了未来信息")
print()
# 用事件发生时点之前是否已有足够历史，做一个粗糙的PIT可行性检查
first_half=e[e.date<'2025-01-01']; second=e[e.date>='2025-01-01']
for lab,sub in [('2024年事件',first_half),('2025年事件',second)]:
    f2=sub[sub['类型']=='财报型']
    A2=f2[~f2.buy]; B2=f2[f2.buy]
    if len(A2)>0 and len(B2)>0:
        print("%s: 财报型不买 %d个 %.0f%% | 会买 %d个 %.0f%% | z=%.2f"%(lab,len(A2),(A2.d252>0).mean()*100,len(B2),(B2.d252>0).mean()*100,z((B2.d252>0).mean(),len(B2),(A2.d252>0).mean(),len(A2))))
print()
print("=== 不分型，全样本（完全无前视）===")
A3=e[~e.buy]; B3=e[e.buy]
print("  不买 %d个 %.0f%% | 会买 %d个 %.0f%% | 差 %.1fpp | z=%.2f"%(len(A3),(A3.d252>0).mean()*100,len(B3),(B3.d252>0).mean()*100,((B3.d252>0).mean()-(A3.d252>0).mean())*100,z((B3.d252>0).mean(),len(B3),(A3.d252>0).mean(),len(A3))))
