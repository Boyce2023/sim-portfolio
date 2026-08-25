#!/usr/bin/env python3
"""baostock拉2025全A股日K → sqlite。
⛔2026-08-25重写: 前一版在某只票上无限阻塞,CPU 99%空转89分钟,DB停在201只不动,
   而进程还活着(ps看得到)——这是"后台任务必须验活"最典型的形态: 活着≠在工作。
   根因: baostock的query_history_k_data_plus没有超时机制,网络半开时会永久挂起。
   修法: ①每个请求用SIGALRM硬超时20秒 ②心跳文件每只票都写(不是每200只) ③断点续传
"""
import baostock as bs, sqlite3, sys, time, signal, os
BASE='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'
DB=f'{BASE}/univ2025.db'; HB=f'{BASE}/.heartbeat'

class TO(Exception): pass
def _alarm(sig,frm): raise TO()
signal.signal(signal.SIGALRM,_alarm)

lg=bs.login()
if lg.error_code!='0': print('登录失败',lg.error_msg,flush=True); sys.exit(1)

con=sqlite3.connect(DB)
con.execute('''create table if not exists k(
  code text,date text,open real,high real,low real,close real,preclose real,
  volume real,amount real,turn real,isST integer, primary key(code,date))''')
con.commit()

signal.alarm(60)
rs=bs.query_all_stock(day='2025-12-31'); signal.alarm(0)
codes=[]
while rs.next():
    c=rs.get_row_data()[0]
    if c.startswith(('sh.60','sh.68','sz.00','sz.30','bj.')): codes.append(c)
done=set(x[0] for x in con.execute('select distinct code from k'))
todo=[c for c in codes if c not in done]
print(f'全A {len(codes)}只 | 已有{len(done)} | 待拉{len(todo)}',flush=True)

t0=time.time(); ok=fail=to=0
for i,c in enumerate(todo):
    try:
        signal.alarm(20)                     # ⛔硬超时,治死循环
        rs=bs.query_history_k_data_plus(c,
            "date,code,open,high,low,close,preclose,volume,amount,turn,isST",
            start_date='2025-01-01',end_date='2025-12-31',frequency='d',adjustflag='3')
        rows=[]
        while rs.next():
            d=rs.get_row_data()
            try: rows.append((d[1],d[0],float(d[2]or 0),float(d[3]or 0),float(d[4]or 0),
                              float(d[5]or 0),float(d[6]or 0),float(d[7]or 0),
                              float(d[8]or 0),float(d[9]or 0),int(d[10]or 0)))
            except: pass
        signal.alarm(0)
        if rows: con.executemany('insert or replace into k values(?,?,?,?,?,?,?,?,?,?,?)',rows); ok+=1
        else: fail+=1
    except TO:
        signal.alarm(0); to+=1
        try: bs.logout(); bs.login()          # 超时后重建连接
        except: pass
    except Exception:
        signal.alarm(0); fail+=1
    # 心跳: 每只票都写,让外部能验活(不是每200只)
    open(HB,'w').write(f'{time.time()}|{i+1}/{len(todo)}|ok={ok} fail={fail} timeout={to}')
    if (i+1)%100==0:
        con.commit(); el=time.time()-t0
        print(f'  {i+1}/{len(todo)} ok={ok} fail={fail} to={to} '
              f'{el/60:.1f}分 剩~{el/(i+1)*(len(todo)-i-1)/60:.0f}分',flush=True)
con.commit()
n=con.execute('select count(*) from k').fetchone()[0]
d=con.execute('select count(distinct code) from k').fetchone()[0]
print(f'完成: {d}只 {n}行 | ok={ok} fail={fail} timeout={to} | {(time.time()-t0)/60:.1f}分',flush=True)
bs.logout()
