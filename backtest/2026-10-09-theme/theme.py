#!/opt/homebrew/bin/python3.13
"""概念题材口径的'连续两天强势'规则化与前推回测。
数据: 同花顺涨停池逐日涨停原因(当日标注, 无成分股后补的前视), 2025-09-24 到 2026-10-09。
题材: 涨停原因按'+'拆词, 同义词并组, 剔除国资/业绩/回购等非题材词。
信号(T日收盘可得): 题材 T-1 与 T 两天涨停只数都排全市场前 K, 每天至少 M 只, 且 T 日该题材有 2 板及以上。
结局(只看T之后): 未来 5/10 个交易日累计涨停只数是否全市场第一(主线)或前二。"""
import json,glob,re,collections,sys
import pandas as pd, numpy as np
SYN={
 '固态电池':['固态电池','锂电池','锂电','钠离子电池','钠电池','六氟磷酸锂','电解液','动力电池','负极材料','正极材料','隔膜','铝塑膜','锂电池材料','电池','磷酸铁锂','硅碳负极','复合集流体','电池回收'],
 '农业':['种业','转基因','粮食','农业','生猪养殖','猪肉','农药','化肥','种植业','大豆','玉米','乡村振兴','农产品','粮食安全','生物育种','鸡肉','养殖','饲料','水产','种子','农机','土地流转','农业种植','杂交水稻','钾肥','磷肥'],
 '医药':['创新药','中药','医药','CXO','仿制药','原料药','生物医药','医疗器械','疫苗','流感','减肥药','医药商业','生物制品','化学制药','抗癌','ADC','GLP-1','多肽','合成生物','细胞治疗','基因治疗','医疗','医疗服务','CRO','血液制品','抗生素','创新药出海','BD授权'],
 'AI制药':['AI医疗','AI制药','AI药物研发','AI医药','AI+医疗','AI诊断','医疗AI','AI药物发现'],
}
TOK2={t:k for k,v in SYN.items() for t in v}
GEN=re.compile('国资|央企|国企|报|预增|扭亏|增长|回购|控制权|定增|股权|摘帽|复牌|次新|减亏|亏损|外销|产能|重组|并购|收购|转让|激励|业绩|涨价|订单|中标|合同|子公司|新股|出海|大客户|海外|高送转|ST|举牌|实控人|分红|借壳|资产注入|上市|增持|减持|签约|投资|合作|扩产|降本|提价|利润|营收|主业|龙头|第一|全球|国内|市占率')
def themes(reason):
    out=set()
    for t in (reason or '').split('+'):
        t=t.strip()
        if not t: continue
        if t in TOK2: out.add(TOK2[t]); continue
        if 'AI' in t and ('医' in t or '药' in t): out.add('AI制药'); continue
        if re.search('钙钛矿|光伏|HJT|TOPCon|BC电池|太阳能',t): out.add('光伏'); continue
        if re.search('电池|锂|钠离子|电解液|负极|正极|隔膜|铝塑膜|集流体',t): out.add('固态电池'); continue
        if re.search('种业|育种|制种|种子|粮|玉米|大豆|水稻|小麦|转基因|农业|农产品|化肥|钾肥|磷肥|农药|生猪|猪肉|养殖|饲料|水产|棉花|种植',t): out.add('农业'); continue
        if re.search('药|医|生物|疫苗|CXO|CRO|CDMO|ADC|抗体|细胞|基因治疗|诊断|器械|血液',t): out.add('医药'); continue
        if GEN.search(t): continue
        out.add(t)
    return out
rows=[]
for f in sorted(glob.glob('ths/*.json')):
    d=f.split('/')[-1][:8]
    for r in json.load(open(f)):
        hd=r.get('high_days_value') or 1
        try: hd=int(hd)>>16  # 高16位=板数, 低16位=天数(如 131075 = 3天2板)
        except: hd=1
        for th in themes(r.get('reason_type')):
            rows.append((pd.Timestamp(d),th,r['code'],hd))
T=pd.DataFrame(rows,columns=['date','theme','code','lb'])
days=np.sort(T.date.unique())
cnt=T.groupby(['date','theme']).code.nunique().unstack(fill_value=0).reindex(days,fill_value=0)
lb2=T[T.lb>=2].groupby(['date','theme']).code.nunique().unstack(fill_value=0).reindex(index=days,columns=cnt.columns,fill_value=0)
rk=cnt.rank(axis=1,ascending=False,method='min')
cnt.to_parquet('theme_cnt.parquet'); T.to_parquet('theme_rows.parquet')
def run(K=3,M=5,fresh=True):
    out=[]
    for i in range(6,len(days)):
        t,t1=days[i],days[i-1]
        ok=(rk.loc[t]<=K)&(rk.loc[t1]<=K)&(cnt.loc[t]>=M)&(cnt.loc[t1]>=M)&(lb2.loc[t]>=1)
        if fresh: ok&=~((rk.iloc[i-6:i-1]<=K)&(cnt.iloc[i-6:i-1]>=M)).any()
        for th in ok[ok].index:
            r={'date':t,'theme':th,'c_t1':int(cnt.loc[t1,th]),'c_t':int(cnt.loc[t,th]),'lb2':int(lb2.loc[t,th])}
            for h in (5,10):
                if i+h<len(days):
                    s=cnt.iloc[i+1:i+h+1].sum(); r[f'rank{h}']=int(s.rank(ascending=False,method='min')[th]); r[f'zt{h}']=int(s[th])
                    r[f'top3days{h}']=int((rk.iloc[i+1:i+h+1][th]<=3).sum())
            out.append(r)
    return pd.DataFrame(out)
if __name__=='__main__':
    for K,M,fr in [(3,5,True),(2,5,True),(3,5,False),(3,4,True),(5,5,True)]:
        S=run(K,M,fr); S.to_parquet(f'sig_K{K}_M{M}_{"fresh" if fr else "all"}.parquet')
        v=S.dropna(subset=['rank10'])
        print(f'K={K} M={M} {"新题材" if fr else "不限"}: 信号{len(S)} 有10日窗口{len(v)} | 10日第一 {(v.rank10==1).mean()*100:.0f}% 前二 {(v.rank10<=2).mean()*100:.0f}% 前三 {(v.rank10<=3).mean()*100:.0f}% | 5日第一 {(S.rank5==1).mean()*100:.0f}% | 后10日仍居前三天数均值 {v.top3days10.mean():.1f}')
