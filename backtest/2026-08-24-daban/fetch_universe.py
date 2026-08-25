#!/usr/bin/env python3
"""用baostock拉2025全年全A股日K → 本地sqlite。
⛔为什么不用本地kline_cache.db: 它只有2371只(全市场约5400只),且这2371只是我过去研究/扫描过的票,
不是随机样本——用它跑打板回测会被我自己的选股偏好污染(日均涨停只有19.7只 vs 真实50-150只)。
⛔为什么不用 ak.stock_zt_pool_em: 实测该接口只提供最近约1个月(20260731及更早全空)。
"""
import baostock as bs, sqlite3, sys, time
DB='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/univ2025.db'
lg=bs.login()
if lg.error_code!='0': print('登录失败',lg.error_msg); sys.exit(1)

con=sqlite3.connect(DB)
con.execute('''create table if not exists k(
  code text,date text,open real,high real,low real,close real,preclose real,
  volume real,amount real,turn real,isST integer, primary key(code,date))''')
con.commit()

# 全A股列表(用某个交易日的全部证券)
rs=bs.query_all_stock(day='2025-12-31')
codes=[]
while rs.next():
    r=rs.get_row_data()
    c=r[0]
    if c.startswith(('sh.60','sh.68','sz.00','sz.30','bj.')): codes.append(c)
print(f'全A股票 {len(codes)} 只',file=sys.stderr)

done=set(x[0] for x in con.execute('select distinct code from k'))
todo=[c for c in codes if c not in done]
print(f'待拉 {len(todo)} 只(已有{len(done)})',file=sys.stderr)

t0=time.time(); ok=0; fail=0
for i,c in enumerate(todo):
    try:
        rs=bs.query_history_k_data_plus(c,
            "date,code,open,high,low,close,preclose,volume,amount,turn,isST",
            start_date='2025-01-01',end_date='2025-12-31',frequency='d',adjustflag='3')
        rows=[]
        while rs.next():
            d=rs.get_row_data()
            try: rows.append((d[1],d[0],float(d[2]or 0),float(d[3]or 0),float(d[4]or 0),
                              float(d[5]or 0),float(d[6]or 0),float(d[7]or 0),float(d[8]or 0),
                              float(d[9]or 0),int(d[10]or 0)))
            except: pass
        if rows:
            con.executemany('insert or replace into k values(?,?,?,?,?,?,?,?,?,?,?)',rows); ok+=1
        else: fail+=1
        if i%200==0:
            con.commit()
            el=time.time()-t0
            print(f'  {i}/{len(todo)} ok={ok} fail={fail} 用时{el/60:.1f}分 预计还需{el/max(i,1)*(len(todo)-i)/60:.0f}分',file=sys.stderr,flush=True)
    except Exception as e:
        fail+=1
con.commit()
n=con.execute('select count(*) from k').fetchone()[0]
d=con.execute('select count(distinct code) from k').fetchone()[0]
print(f'\n完成: {d}只股票 {n}行, 成功{ok} 失败{fail}, 总用时{(time.time()-t0)/60:.1f}分',file=sys.stderr)
bs.logout()
