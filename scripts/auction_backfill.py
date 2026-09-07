#!/opt/homebrew/bin/python3
"""⛔集合竞价段(09:15-09:25)数据回补与每日采集 — iFinD snap_shot, 3秒粒度

起因(2026-09-07 Buwen): 他观察到一个形态——竞价段9:24之前一直是低位阴量,
9:25那一刻突然翻红并爆出大于前面所有的巨量, 只在最后一秒完成。想知道次日胜率。
实例: 万向德农600371 今日 09:16-09:24挂13.70待撮合67万股 → 09:24:57跳到184.8万
→ 09:25:00达210.7万@14.23 → 撮合成交。三秒内涌入140万股把价格从-3.7%拉到+0.2%。

⛔数据约束(main实测): iFinD snap_shot 只有**约30天滚动窗口**, 08-06之前返回0条。
每天都在滑走, 所以要尽早回补。免费源全部不含竞价段(腾讯从09:30/新浪从09:31起)。

用法:
  auction_backfill.py backfill [天数]   回补最近N个交易日(默认30)
  auction_backfill.py daily             采集当日(供每日cron)
  auction_backfill.py stat              看已存数据统计
存储: data/auction/auction.db  表 snap(code,date,ts,latest,volume,bid1,ask1,bidsz,asksz)
"""
import sys,os,time,sqlite3,datetime,json
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import ifind_data_layer as I
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB=f'{BASE}/data/auction/auction.db'
IND="tradeTime,latest,volume,bid1,ask1,bidSize1,askSize1"
BATCH=30          # 每批股票数(main实测3只1.7秒, 30只约需数秒)
SLEEP=0.15

def db():
    con=sqlite3.connect(DB)
    con.execute('''create table if not exists snap(code text,date text,ts text,latest real,
      volume real,bid1 real,ask1 real,bidsz real,asksz real,primary key(code,date,ts))''')
    con.execute('create index if not exists ix_cd on snap(code,date)')
    con.execute('''create table if not exists done(code text,date text,n integer,primary key(code,date))''')
    con.commit(); return con

def codes_all():
    """全市场代码, 用本地日线库最新一期的成分"""
    import glob
    dbs=sorted(glob.glob(f'{BASE}/backtest/2026-08-24-daban/univ*.db'))
    for f in reversed(dbs):
        try:
            c=[x[0] for x in sqlite3.connect(f'file:{f}?mode=ro',uri=True).execute("select distinct code from k")]
            if len(c)>3000:
                # baostock格式 sh.600371 → iFinD格式 600371.SH
                out=[]
                for x in c:
                    if '.' in x:
                        mk,num=x.split('.')
                        out.append(f"{num}.{mk.upper()}")
                return sorted(set(out))
        except Exception: continue
    return []

class QuotaExhausted(Exception):
    """iFinD 高频快照接口本月额度用尽(errorcode=-4318)。
    ⛔2026-09-07: 原代码把这个错误当成普通批次失败continue掉, 最后整天0条,
    再被外层误判成"滑出30天窗口"并stop——额度问题被当成数据边界问题, 是静默误诊。
    同族坑: 交易所前缀写错时腾讯不报错只给过期bar。错误必须当场炸, 不许降级成空值。"""

def fetch_day(codes,day,con):
    """拉一天的竞价段。返回(成功股数,快照条数)。额度耗尽直接抛QuotaExhausted"""
    cur=con.cursor()
    done=set(x[0] for x in cur.execute("select code from done where date=?",(day,)))
    todo=[c for c in codes if c not in done]
    if not todo: return 0,0
    nok=nrow=0
    for i in range(0,len(todo),BATCH):
        chunk=todo[i:i+BATCH]
        try:
            r=I._post("snap_shot",{"codes":",".join(chunk),"indicators":IND,
                "starttime":f"{day} 09:15:00","endtime":f"{day} 09:26:00"})
        except Exception as e:
            print(f"    批{i//BATCH} ERR {repr(e)[:70]}"); time.sleep(2); continue
        ec=r.get("errorcode")
        if str(ec)=='-4318':
            raise QuotaExhausted(f"{day} 批{i//BATCH}: {str(r.get('errmsg'))[:80]}")
        if ec not in (0,None,'0'):
            print(f"    ⛔errorcode={ec} {str(r.get('errmsg'))[:60]}"); time.sleep(3); continue
        for t in (r.get("tables") or []):
            code=t.get("thscode"); tm=t.get("time") or []; tb=t.get("table") or {}
            if not tm: cur.execute("insert or replace into done values(?,?,0)",(code,day)); continue
            rec=[]
            for k,ts in enumerate(tm):
                g=lambda f: (tb.get(f) or [None]*len(tm))[k]
                rec.append((code,day,ts,g('latest'),g('volume'),g('bid1'),g('ask1'),g('bidSize1'),g('askSize1')))
            cur.executemany("insert or replace into snap values(?,?,?,?,?,?,?,?,?)",rec)
            cur.execute("insert or replace into done values(?,?,?)",(code,day,len(rec)))
            nok+=1; nrow+=len(rec)
        con.commit(); time.sleep(SLEEP)
    return nok,nrow

def trading_days(n):
    """从本地日线库取最近n个交易日; 不足则用日历近似"""
    import glob
    ds=set()
    for f in sorted(glob.glob(f'{BASE}/backtest/2026-08-24-daban/univ*.db')):
        try:
            for (d,) in sqlite3.connect(f'file:{f}?mode=ro',uri=True).execute("select distinct date from k"): ds.add(d)
        except Exception: pass
    today=datetime.date.today()
    # 补上库里没有的近期交易日(周一到周五)
    d=today
    extra=[]
    while len(extra)<45:
        if d.weekday()<5: extra.append(d.isoformat())
        d-=datetime.timedelta(days=1)
    allд=sorted(set(list(ds)+extra))
    return [x for x in allд if x<=today.isoformat()][-n:]

def main():
    a=sys.argv[1:] or ['stat']
    con=db()
    if a[0]=='stat':
        for d,n,c in con.execute("select date,count(*),count(distinct code) from snap group by date order by date"):
            print(f"  {d}: {n}条快照 {c}只股票")
        tot=con.execute("select count(*) from snap").fetchone()[0]
        print(f"合计 {tot} 条")
    elif a[0]=='daily':
        day=datetime.date.today().isoformat()
        codes=codes_all(); print(f"当日采集 {day}, 全市场{len(codes)}只")
        t0=time.time(); nok,nrow=fetch_day(codes,day,con)
        print(f"完成: {nok}只 {nrow}条 用时{(time.time()-t0)/60:.1f}分")
    elif a[0]=='backfill':
        n=int(a[1]) if len(a)>1 else 30
        codes=codes_all(); days=trading_days(n)
        print(f"回补最近{len(days)}个交易日 × {len(codes)}只  {days[0]}~{days[-1]}")
        for day in reversed(days):     # 从最近的往回拉, 越早的越可能已滑出窗口
            t0=time.time()
            try:
                nok,nrow=fetch_day(codes,day,con)
            except QuotaExhausted as e:
                print(f"\n⛔⛔ iFinD高频快照本月额度用尽, 回补中止(不是窗口滑走): {e}")
                print(f"   已入库天数见 stat。额度按自然月重置, 下月1日后重跑本命令续补。")
                print(f"   ⚠️常规接口(realtime/history/basic)不受影响, 只有snap_shot走高频额度。")
                return
            print(f"  {day}: {nok}只 {nrow}条 {(time.time()-t0)/60:.1f}分",flush=True)
            if nok==0 and nrow==0:
                # 空≠滑出窗口: 先确认这天是不是交易日, 再判边界
                print(f"  ⛔{day}返回0条。若为交易日则可能已滑出30天窗口, 停止往前")
                break
if __name__=='__main__': main()
