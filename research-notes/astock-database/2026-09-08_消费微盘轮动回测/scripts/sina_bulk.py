"""新浪源(ak.stock_zh_a_daily qfq) 单线程拉790只10年 → sqlite; 逐日 outstanding_share/turnover"""
import warnings,sqlite3,json,time; warnings.filterwarnings('ignore')
import akshare as ak
DB='/tmp/dhbr/hist10y_sina.db'
c=sqlite3.connect(DB)
c.execute("""create table if not exists k(code text,date text,open real,high real,low real,close real,
             volume real,amount real,oshare real,turn real,primary key(code,date))""")
c.execute("create table if not exists done(code text primary key,n int,first text,last text)"); c.commit()
codes=json.load(open('/tmp/dhbr/consumer_codes_bs.json'))
have={r[0] for r in c.execute("select code from done")}
todo=[x for x in codes if x not in have]; print(f"待拉 {len(todo)} / 已有 {len(have)}",flush=True)
t0=time.time(); empty=[]
for i,bs in enumerate(todo,1):
    sym=bs.replace('.','')   # sh.600305 -> sh600305
    rows=[]
    for att in range(3):
        try:
            df=ak.stock_zh_a_daily(symbol=sym,start_date='20160101',end_date='20260908',adjust='qfq')
            rows=[(bs,str(r['date'])[:10],float(r['open']),float(r['high']),float(r['low']),float(r['close']),
                   float(r['volume']),float(r['amount']),float(r['outstanding_share']),float(r['turnover'])) for _,r in df.iterrows()]
            break
        except Exception as e:
            time.sleep(1.5*(att+1))
    if rows: c.executemany("insert or replace into k values(?,?,?,?,?,?,?,?,?,?)",rows)
    else: empty.append(bs)
    ds=sorted({r[1] for r in rows})
    c.execute("insert or replace into done values(?,?,?,?)",(bs,len(rows),ds[0] if ds else '',ds[-1] if ds else '')); c.commit()
    if i%50==0 or i==len(todo):
        el=time.time()-t0; print(f"  {i}/{len(todo)} {el/60:.1f}min eta{(len(todo)-i)/i*el/60:.1f}min 空返{len(empty)}",flush=True)
    time.sleep(0.2)
n,nc,mn,mx=c.execute("select count(*),count(distinct code),min(date),max(date) from k").fetchone()
z=c.execute("select count(*) from done where n=0").fetchone()[0]
print(f"完成: {n:,}行 {nc}只 {mn}~{mx} | 空返{z}",flush=True)
if empty: print("空返:",empty[:20],flush=True)
