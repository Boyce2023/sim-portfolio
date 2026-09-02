"""B可成交基准率(2026-08样本): 涨停池炸板次数/首次封板时间 → 可成交概率按换手分桶; 套到4-6月B交易估算期望NAV"""
import json,akshare as ak,pandas as pd,time,sys
days=[d.strftime('%Y%m%d') for d in pd.bdate_range('2026-08-03','2026-09-01')]
recs=[]
for D in days:
    for a in range(3):
        try:
            df=ak.stock_zt_pool_em(date=D)
            if df is not None and len(df):
                for _,r in df.iterrows():
                    recs.append(dict(date=D,code=str(r['代码']),name=r['名称'],turn=float(r.get('换手率',0) or 0),zb=int(r.get('炸板次数',0) or 0),fbt=str(r.get('首次封板时间','')),lbt=str(r.get('最后封板时间','')),lb=int(r.get('连板数',0) or 0),amt=float(r.get('成交额',0) or 0),fund=float(r.get('封板资金',0) or 0)))
            break
        except Exception as e: time.sleep(2)
print('8月样本板数',len(recs),'天数',len({r['date'] for r in recs}))
if not recs: print('B_BASE_FAIL'); sys.exit(0)
import collections
def bucket(t): return '<3%' if t<3 else '3-8%' if t<8 else '8-15%' if t<15 else '>=15%'
agg=collections.defaultdict(lambda:[0,0,0])
for r in recs:
    b=bucket(r['turn']); agg[b][0]+=1
    if r['zb']>=1 or (r['fbt'] and r['fbt']>='130000'): agg[b][1]+=1
    if r['zb']>=1: agg[b][2]+=1
prob={b:dict(n=v[0],loose=v[1]/v[0],strict=v[2]/v[0]) for b,v in agg.items()}
for b,v in sorted(prob.items()): print(f"换手{b}: n={v['n']} 可成交(宽)={v['loose']*100:.0f}% (严)={v['strict']*100:.0f}%")
tot=len(recs); print(f"总体: 宽{sum(1 for r in recs if r['zb']>=1 or (r['fbt'] and r['fbt']>='130000'))/tot*100:.0f}% 严{sum(1 for r in recs if r['zb']>=1)/tot*100:.0f}%")
res={}
for m in ['04','05','06']:
    B=json.load(open(f'/tmp/abc_4-6/ab_2026-{m}.json'))['B']
    byd=collections.defaultdict(list)
    for t in B:
        p=prob.get(bucket(t['turn']),dict(loose=0,strict=0))
        byd[t['date']].append((t['net'],p['loose'],p['strict']))
    nav=[1.0,1.0,1.0]
    for d in sorted(byd):
        L=byd[d]; n=len(L)
        nav[0]*=1+sum(x[0] for x in L)/n/100
        nav[1]*=1+sum(x[0]*x[1] for x in L)/n/100
        nav[2]*=1+sum(x[0]*x[2] for x in L)/n/100
    res[m]=dict(all=nav[0],exp_loose=nav[1],exp_strict=nav[2])
    print(f"B 2026-{m}: 全成交NAV {nav[0]:.3f} | 期望(宽){nav[1]:.3f} | 期望(严){nav[2]:.3f}")
json.dump(dict(prob=prob,res=res,n=tot),open('/tmp/b_fill/baserate.json','w'),ensure_ascii=False)
print('B_BASE_DONE')
