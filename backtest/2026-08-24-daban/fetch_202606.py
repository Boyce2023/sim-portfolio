#!/usr/bin/env python3
"""样本外验证: 2026年1月逐日选股
⛔策略参数在2025样本内已锁死(strategy_search.py),本脚本不做任何调参
   gap1<=0 (次日不高开) & streak<=3 & gain20>=50
⛔数据独立拉取,与2025库分开
"""
import baostock as bs,sqlite3,sys,time,signal,json,statistics
from collections import defaultdict
BASE='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'
DB=f'{BASE}/univ202606.db'
class TO(Exception):pass
signal.signal(signal.SIGALRM,lambda s,f:(_ for _ in ()).throw(TO()))
lg=bs.login()
con=sqlite3.connect(DB)
con.execute('''create table if not exists k(code text,date text,open real,high real,low real,
 close real,preclose real,volume real,amount real,turn real,isST integer,primary key(code,date))''')
con.commit()
import sqlite3 as _sq
codes=[x[0] for x in _sq.connect(f'{BASE}/univ202605.db').execute("select distinct code from k")]
# ⛔2026-08-28换路: query_all_stock晚间返回空/挂起(零数据不设防第3次咬人),改用5月库清单(成分差异仅个位数)
done=set(x[0] for x in con.execute('select distinct code from k'))
todo=[c for c in codes if c not in done]
print(f'全A {len(codes)} 待拉 {len(todo)}',flush=True)
t0=time.time(); ok=to=0
for i,c in enumerate(todo):
    try:
        signal.alarm(20)
        # 多取前后: 前30日算gain20, 后10日算T+1/2/5
        rs=bs.query_history_k_data_plus(c,"date,code,open,high,low,close,preclose,volume,amount,turn,isST",
            start_date="2026-05-01",end_date="2026-07-05",frequency='d',adjustflag='3')
        rows=[]
        while rs.next():
            d=rs.get_row_data()
            try: rows.append((d[1],d[0],float(d[2]or 0),float(d[3]or 0),float(d[4]or 0),float(d[5]or 0),
                              float(d[6]or 0),float(d[7]or 0),float(d[8]or 0),float(d[9]or 0),int(d[10]or 0)))
            except: pass
        signal.alarm(0)
        if rows: con.executemany('insert or replace into k values(?,?,?,?,?,?,?,?,?,?,?)',rows); ok+=1
    except TO:
        signal.alarm(0); to+=1
        try: bs.logout(); bs.login()
        except: pass
    except Exception: signal.alarm(0)
    open(f'{BASE}/.hb_oos3','w').write(f'{time.time()}|{i+1}/{len(todo)}|ok={ok} to={to}')
    if (i+1)%500==0:
        con.commit(); el=time.time()-t0
        print(f'  {i+1}/{len(todo)} ok={ok} to={to} {el/60:.1f}分 剩~{el/(i+1)*(len(todo)-i-1)/60:.0f}分',flush=True)
con.commit(); bs.logout()
print(f'拉取完成 {con.execute("select count(distinct code) from k").fetchone()[0]}只',flush=True)
