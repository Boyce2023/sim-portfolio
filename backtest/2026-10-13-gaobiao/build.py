#!/opt/homebrew/bin/python3.13
"""7月以来高标(当日>=5连板)次日表现 vs 当日可得特征: 流通市值、当日炸板次数、同题材当日涨停数、概念数、近5个交易日是否有'风险提示'公告(公司主动提示, 区别于规则性的'异常波动'公告)"""
import json,glob,time,requests,pandas as pd,numpy as np,sys
sys.path.insert(0,'../2026-10-09-theme'); from theme import themes
rows=[]
for f in sorted(glob.glob('../2026-10-09-theme/ths/2026*.json')):
    d=f.split('/')[-1][:8]
    if d<'20260701': continue
    for r in json.load(open(f)):
        lb=int(r.get('high_days_value') or 65537)>>16
        days=int(r.get('high_days_value') or 65537)&0xFFFF
        rows.append(dict(date=pd.Timestamp(d),code=r['code'],name=r['name'],lb=lb,days=days,open_num=r.get('open_num') or 0,
                         cap=(r.get('currency_value') or 0)/1e8,reason=r.get('reason_type') or '',ths=list(themes(r.get('reason_type')))))
Z=pd.DataFrame(rows)
# 同题材当日涨停数(取该股各题材中最大的)
tc=Z.explode('ths').groupby(['date','ths']).code.nunique()
Z['题材同伴']=[max([tc.get((d,t),0) for t in ts] or [0])-1 for d,ts in zip(Z.date,Z.ths)]
Z['概念数']=Z.reason.str.count(r'\+')+1
H=Z[(Z.lb>=5)&(Z.lb==Z.days)].copy()   # 连续 N 天 N 板
print('高标样本',len(H),H.date.min().date(),H.date.max().date())
# 风险提示公告
Hd={'User-Agent':'Mozilla/5.0','Referer':'http://www.cninfo.com.cn/'}
cache={}
def anns(code,name):
    if code in cache: return cache[code]
    out=[]
    for col in ('sse','szse'):
        try:
            r=requests.post('http://www.cninfo.com.cn/new/hisAnnouncement/query',headers=Hd,timeout=20,data={'pageNum':1,'pageSize':30,'column':col,'tabName':'fulltext','searchkey':name.replace(' ',''),'seDate':'2026-06-20~2026-10-13','isHLtitle':'true'}).json()
            for a in r.get('announcements') or []:
                if a['secCode']==code: out.append((time.strftime('%Y-%m-%d',time.localtime(a['announcementTime']/1000)),a['announcementTitle'].replace('<em>','').replace('</em>','')))
        except Exception: pass
        time.sleep(0.3)
    cache[code]=out; return out
cal=sorted(Z.date.unique())
def prev5(d):
    i=cal.index(d); return cal[max(0,i-5)]
H['风险提示']=[any(('风险提示' in t or '澄清' in t) and prev5(d).strftime('%Y-%m-%d')<=dt<=d.strftime('%Y-%m-%d') for dt,t in anns(c,n)) for d,c,n in zip(H.date,H.code,H.name)]
# 次日收益
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','close','adj_close'],filters=[('date','>=',pd.Timestamp('2026-06-25'))])
A['code']=A.ticker.str[:6]; A['f']=A.adj_close/A.close; A=A.sort_values(['code','date']); g=A.groupby('code')
for k in (1,2): A[f'c{k}']=g.adj_close.shift(-k); A[f'o{k}']=g.open.shift(-k)*g.f.shift(-k)
A=A.set_index(['date','code'])
def get(d,c,col):
    try: return A.loc[(d,c),col]
    except KeyError: return np.nan
H['次日涨跌']=[get(d,c,'c1')/get(d,c,'adj_close')-1 for d,c in zip(H.date,H.code)]
H['次日开盘买_再下日收盘']=[get(d,c,'c2')/get(d,c,'o1')-1 for d,c in zip(H.date,H.code)]
H.to_csv('gaobiao.csv',index=False,encoding='utf-8-sig')
print(H[['date','name','lb','cap','open_num','题材同伴','概念数','风险提示','次日涨跌','次日开盘买_再下日收盘']].round(3).to_string(index=False))
