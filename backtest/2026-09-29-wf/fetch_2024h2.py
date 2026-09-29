#!/usr/bin/env python3
"""补 2024-06-20..2024-12-31 全A(含后来退市的) 日线+isST, baostock 单进程(并行login会被拉黑)"""
import baostock as bs,sqlite3,time,signal
DB='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-09-29-wf/univ2024h2.db'
class TO(Exception):pass
signal.signal(signal.SIGALRM,lambda s,f:(_ for _ in ()).throw(TO()))
bs.login()
con=sqlite3.connect(DB)
con.execute('create table if not exists k(code text,date text,open real,high real,low real,close real,preclose real,volume real,amount real,turn real,isST integer,primary key(code,date))')
codes=set()
for day in ['2024-07-01','2024-09-30','2024-12-31']:
    signal.alarm(60)
    try:
        rs=bs.query_all_stock(day=day)
        while rs.next():
            c=rs.get_row_data()[0]
            if c[:5] in('sh.60','sz.00','sz.30','sh.68'): codes.add(c)
    except TO: print('query_all_stock 超时',day,flush=True)
    signal.alarm(0)
print('当期股票池',len(codes),flush=True)
if len(codes)<4000:
    import sqlite3 as q
    codes|=set(x[0] for x in q.connect('/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/univ2025.db').execute('select distinct code from k'))
    print('⛔股票池不足, 用2025库清单补, 现',len(codes),flush=True)
done=set(x[0] for x in con.execute('select distinct code from k'))
import pandas as pd
have=set(pd.read_parquet('/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet',columns=['ticker']).ticker.str[:6].unique())
pri=sorted(c for c in codes-done if c[3:] not in have)       # 主库没有的(后来退市) 优先
rest=sorted(c for c in codes-done if c[3:] in have)
todo=pri+rest
print('优先(主库缺失/退市)',len(pri),' 其余(只为ST标记)',len(rest),flush=True); t0=time.time(); ok=to=0
for i,c in enumerate(todo):
    try:
        signal.alarm(20)
        rs=bs.query_history_k_data_plus(c,"date,code,open,high,low,close,preclose,volume,amount,turn,isST",start_date="2024-06-20",end_date="2024-12-31",frequency='d',adjustflag='3')
        rows=[]
        while rs.next():
            d=rs.get_row_data()
            try: rows.append((d[1],d[0],*[float(x or 0) for x in d[2:10]],int(d[10] or 0)))
            except: pass
        signal.alarm(0)
        if rows: con.executemany('insert or replace into k values(?,?,?,?,?,?,?,?,?,?,?)',rows); ok+=1
    except TO:
        signal.alarm(0); to+=1
        try: bs.logout(); bs.login()
        except: pass
    except Exception: signal.alarm(0)
    if i+1==len(pri):
        con.commit(); open('PRIORITY_DONE','w').write(str(len(pri))); print('== 优先批完成',len(pri),flush=True)
    if (i+1)%250==0:
        con.commit(); el=time.time()-t0
        print(f'{i+1}/{len(todo)} ok={ok} to={to} {el/60:.1f}分 剩~{el/(i+1)*(len(todo)-i-1)/60:.0f}分',flush=True)
con.commit(); bs.logout()
print('完成',con.execute('select count(distinct code),count(*) from k').fetchone(),flush=True)
