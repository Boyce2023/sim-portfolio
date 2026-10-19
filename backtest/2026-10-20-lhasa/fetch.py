"""龙虎榜买卖前五席位明细(东财数据中心), 2021-01 起逐月拉, 每月一个文件 raw/{buy|sell}_YYYY-MM.parquet(可续拉), 4 线程"""
import os, time, requests, pandas as pd
from concurrent.futures import ThreadPoolExecutor
os.environ['NO_PROXY'] = '*'
COLS = 'TRADE_DATE,SECURITY_CODE,OPERATEDEPT_CODE,OPERATEDEPT_NAME,BUY,SELL,NET,EXPLANATION,CHANGE_TYPE,CHANGE_RATE,CLOSE_PRICE,TRADE_ID'
def page(s, rep, f, n):
    for k in range(6):
        try:
            r = s.get('https://datacenter-web.eastmoney.com/api/data/v1/get', params=dict(reportName=rep, columns=COLS, filter=f,
                      pageNumber=n, pageSize=500, sortColumns='TRADE_DATE,SECURITY_CODE,TRADE_ID', sortTypes='1,1,1', source='WEB', client='WEB'), timeout=30)
            d = r.json()
            if d.get('result') is None:
                return 0, []
            return d['result']['pages'], d['result']['data']
        except Exception as e:
            print('  retry', rep[-4:], f[14:24], n, type(e).__name__, flush=True); time.sleep(2 + 3 * k)
    raise RuntimeError(f'{rep} {f} p{n} 6 次失败')
def job(arg):
    side, m = arg
    out = f'raw/{side}_{m}.parquet'
    if os.path.exists(out):
        return
    rep = 'RPT_BILLBOARD_DAILYDETAILS' + side.upper()
    s = requests.Session(); s.trust_env = False
    f = f"(TRADE_DATE>='{m.start_time:%Y-%m-%d}')(TRADE_DATE<='{m.end_time:%Y-%m-%d}')"
    pages, data = page(s, rep, f, 1); got = list(data)
    for n in range(2, (pages or 1) + 1):
        got += page(s, rep, f, n)[1]
    pd.DataFrame(got).to_parquet(out)
    print(side, m, len(got), flush=True)
months = pd.period_range('2021-01', '2026-10', freq='M')
with ThreadPoolExecutor(4) as ex:
    list(ex.map(job, [(sd, m) for m in months[::-1] for sd in ('buy', 'sell')]))
print('done', flush=True)
