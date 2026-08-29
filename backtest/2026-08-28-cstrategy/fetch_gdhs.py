#!/usr/bin/env python3
"""拉C策略信号池股票的股东户数历史(含公告日期,PIT对齐用)。
⛔fail必须计数+覆盖率断言(08-27教训)"""
import akshare as ak,warnings,json,time,signal,sys
warnings.filterwarnings('ignore')
class TO(Exception):pass
signal.signal(signal.SIGALRM,lambda s,f:(_ for _ in ()).throw(TO()))
pool=json.load(open('/tmp/c_sig_stocks.json'))
codes=sorted(pool,key=lambda k:-pool[k])[:400]  # 信号次数前400只(覆盖绝大多数潜在买入)
out={};ok=fail=0
for i,c in enumerate(codes):
    bare=c.split('.')[-1]
    for a in range(2):
        try:
            signal.alarm(20)
            df=ak.stock_zh_a_gdhs_detail_em(symbol=bare)
            signal.alarm(0)
            if df is None or len(df)==0: raise ValueError('empty')
            rec=[{'end':str(r['股东户数统计截止日'])[:10],'ann':str(r['股东户数公告日期'])[:10],
                  'n':int(r['股东户数-本次']),'chg':float(r['股东户数-增减比例']) if r['股东户数-增减比例']==r['股东户数-增减比例'] else None}
                 for _,r in df.iterrows() if str(r['股东户数统计截止日'])[:4] in ('2024','2025','2026')]
            out[bare]=rec; ok+=1; break
        except Exception as e:
            signal.alarm(0)
            if a==1: fail+=1
            time.sleep(1)
    if (i+1)%50==0:
        print(f'{i+1}/{len(codes)} ok={ok} fail={fail}',flush=True)
        open('.hb_gdhs','w').write(f'{i+1}/{len(codes)} ok={ok} fail={fail}\n')
json.dump(out,open('gdhs_pit.json','w'))
cov=ok/len(codes)
print(f'DONE ok={ok} fail={fail} 覆盖率{cov:.0%}',flush=True)
if cov<0.7: sys.exit(1)  # 覆盖率断言
