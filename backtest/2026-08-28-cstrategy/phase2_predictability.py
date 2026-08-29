#!/usr/bin/env python3
"""Phase2: 可预测性——庄股拉升起点T0之前,和普通股可区分吗?
方法: 421只庄股T0前20日特征 vs 每只配3个对照(同市值段/同期/未拉升),比较分布+可分性"""
import sys,json,random
sys.path.insert(0,'.')
from engine_c import load,lim_pct
random.seed(42)
by=load('univ2025.db')
zh=json.load(open('zhuang_2025.json'))
idx={c:{b[1]:i for i,b in enumerate(bars)} for c,bars in by.items()}
allcodes=list(by.keys())

def feats(code,d):
    """T0前20日特征(不含T0当日)"""
    i=idx.get(code,{}).get(d)
    if i is None or i<25: return None
    win=by[code][i-20:i]
    closes=[x[5] for x in win];turns=[x[9] or 0 for x in win];vols=[x[7] for x in win]
    if not closes or closes[0]<=0: return None
    ret20=(closes[-1]/closes[0]-1)*100
    peak=closes[0];mdd=0
    for c in closes: peak=max(peak,c);mdd=min(mdd,(c/peak-1)*100)
    upv=[];dnv=[]
    for j in range(1,len(win)):
        chg=win[j][5]/win[j-1][5]-1
        if chg>0.005: upv.append(vols[j])
        elif chg<-0.005: dnv.append(vols[j])
    ud=(sum(upv)/len(upv))/(sum(dnv)/len(dnv)) if upv and dnv else 1.0
    # 量能斜率: 后10日均量/前10日均量
    vslope=(sum(vols[10:])/10)/(sum(vols[:10])/10) if sum(vols[:10])>0 else 1
    # 价格位置: 现价/120日低
    j0=max(0,i-120)
    lo120=min(x[5] for x in by[code][j0:i])
    pos=closes[-1]/lo120 if lo120>0 else 1
    amt=win[-1][8]; turn=turns[-1]
    mc=(amt/(turn/100))/1e8 if turn>0 else None
    return {'ret20':ret20,'mdd':mdd,'turn_avg':sum(turns)/len(turns),'ud':ud,'vslope':vslope,'pos120':pos,'mc':mc}

Z=[];C=[]
for z in zh:
    f=feats(z['code'],z['start'])
    if not f or f['mc'] is None: continue
    Z.append(f)
    # 配3个对照: 同日有数据的随机股(市值0.5-2倍)
    got=0;tries=0
    while got<3 and tries<60:
        tries+=1
        cc=random.choice(allcodes)
        if cc==z['code']: continue
        fc=feats(cc,z['start'])
        if fc and fc['mc'] and f['mc']*0.5<=fc['mc']<=f['mc']*2:
            C.append(fc);got+=1
print(f'庄股样本{len(Z)} 对照样本{len(C)}')
import statistics as st
print('%-10s %10s %10s %8s'%('特征','庄股中位','对照中位','分离度*'))
for k in ['ret20','mdd','turn_avg','ud','vslope','pos120']:
    zv=[x[k] for x in Z];cv=[x[k] for x in C]
    zm=st.median(zv);cm=st.median(cv)
    # 分离度: 庄股中位数在对照分布中的分位
    pct=sum(1 for v in cv if v<zm)/len(cv)*100
    print('%-10s %10.2f %10.2f %7.0f%%'%(k,zm,cm,pct))
print('\n*分离度=庄股中位数落在对照分布的第几分位(50%=完全不可分,>75%或<25%=有区分度)')
json.dump({'z':Z,'c':C},open('phase2_feats.json','w'))
