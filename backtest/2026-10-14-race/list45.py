import pandas as pd,numpy as np,runpy,io,contextlib
with contextlib.redirect_stdout(io.StringIO()): ns=runpy.run_path('race3.py')
H=ns['H']
P=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','close','adj_close'],filters=[('date','>=',pd.Timestamp('2026-06-25'))])
P['code']=P.ticker.str[:6]; P=P.sort_values(['code','date']); P['c1']=P.groupby('code').adj_close.shift(-1); P=P.set_index(['date','code'])
def r1(d,c):
    try: x=P.loc[(d,c)]; return x.c1/x.adj_close-1
    except KeyError: return np.nan
H['次日涨跌']=[r1(d,c) for d,c in zip(H.date,H.code)]
PATCH={('2026-10-12','002242'):0.0619,('2026-10-12','600241'):-0.0062}
H['次日涨跌']=[PATCH.get((d.strftime('%Y-%m-%d'),c),v) for d,c,v in zip(H.date,H.code,H.次日涨跌)]
for band in ('4板','5板以上'):
    print(f'\n######## {band} ########')
    for (d,lb),x in H[H.档==band].groupby(['date','lb']):
        if len(x)<2: continue
        print(f'{d.date()} {lb}板')
        for _,r in x.sort_values('封单占流通',ascending=False).iterrows():
            print(f"   {r['name']:<6} 流通{r.cap:>5.0f}亿 换手{r.turn:>5.1f}% 封单/流通{r.封单占流通*100:>5.1f}% | 次日{'涨停' if r.晋级 else '未涨停'} {r.次日涨跌*100:+5.1f}% 开买后日收{('买不到' if pd.isna(r.开买后日收) else f'{r.开买后日收*100:+.1f}%')}")
