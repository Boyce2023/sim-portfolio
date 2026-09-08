#!/opt/homebrew/bin/python3
"""集合竞价段自建采集器 — 腾讯免费源, 每日 09:14:50 起自动跑
⛔为什么不用 iFinD snap_shot (2026-09-07 定):
   snap_shot 走独立高频额度桶, 全市场当日一次采集(250765条)就打满整月额度。
   即"每日采集攒一个月"在 iFinD 上物理不可行——一天用光一个月。
   免费源无额度限制, 且实测腾讯 800只/请求 仅 0.09 秒, 全市场5200只≈7请求<1秒,
   所以 3 秒粒度做得到, 不必牺牲关键时刻的分辨率。

采样节奏(Buwen要的形态核心是 09:24:57→09:25:00 那三秒, 均匀15秒会正好跨过去):
   09:15:00-09:24:00  每 30 秒   看"一直挂低位阴量"的前半段
   09:24:24-09:25:06  每 3 秒    抓最后一刻的突变(冲天阳量)
   每只每天约 19+15=34 条

存储: data/auction/auction.db 表 snapf (与 iFinD 的 snap 表分开, 不混源)
用法: auction_collect.py run       今日采集(到点自动等待)
      auction_collect.py test      立刻打一轮验通道(盘中可跑)
      auction_collect.py verify    ⭐锚点校验: 09:25快照价 是否==当日开盘价(已知答案, 通道错了藏不住)
      auction_collect.py stat      看库存
"""
import urllib.request,sqlite3,time,sys,os,glob,datetime
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB=f'{BASE}/data/auction/auction.db'
BATCH=800          # 实测800只/请求 0.09秒
SEG1=(('09:15:12','09:24:00'),30)
SEG2=(('09:24:24','09:25:06'),3)

def mkt(c):
    """⛔交易所前缀: 6/5=沪 4/8=北 其余(0/3)=深。3xxxxx是创业板属深不属沪——
    写错时腾讯不报错, kline会静默返回过期bar(2026-09-03 污染过三处产出)"""
    return 'sh' if c[0] in '56' else ('bj' if c[0] in '48' else 'sz')

def codes_all():
    errs=[]
    for f in reversed(sorted(glob.glob(f'{BASE}/backtest/2026-08-24-daban/univ*.db'))):
        try:
            c=[x[0] for x in sqlite3.connect(f'file:{f}?mode=ro',uri=True).execute("select distinct code from k")]
            if len(c)>3000:
                return sorted({(x.split('.')[1] if '.' in x else x)[-6:] for x in c})
            errs.append(f'{os.path.basename(f)}: 只有{len(c)}只<3000, 跳过')
        except Exception as e:
            errs.append(f'{os.path.basename(f)}: {type(e).__name__} {str(e)[:60]}')   # ⛔原为 pass, 失败原因全丢
    raise SystemExit('⛔拿不到全市场代码。各库失败原因:\n  '+'\n  '.join(errs or ['(没找到任何univ*.db)']))

def db():
    os.makedirs(os.path.dirname(DB),exist_ok=True)
    con=sqlite3.connect(DB)
    con.execute('''create table if not exists snapf(code text,date text,ts text,price real,
        prevclose real,vol real,amount real,bid1 real,bidsz1 real,ask1 real,asksz1 real,
        primary key(code,date,ts))''')
    con.execute('create index if not exists ixf_cd on snapf(code,date)')
    con.commit(); return con

def poll(codes):
    """打一轮全市场。返回 [(code,price,prevclose,vol,amount,bid1,bidsz1,ask1,asksz1)]"""
    out=[]
    for i in range(0,len(codes),BATCH):
        q=','.join(mkt(c)+c for c in codes[i:i+BATCH])
        try:
            raw=urllib.request.urlopen(f'http://qt.gtimg.cn/q={q}',timeout=8).read().decode('gbk','ignore')
        except Exception as e:
            print(f'    批{i//BATCH} ERR {type(e).__name__}',flush=True); continue
        for line in raw.split('\n'):
            p=line.split('~')
            if len(p)<46 or 'none_match' in line: continue
            try:
                out.append((p[2],float(p[3] or 0),float(p[4] or 0),float(p[6] or 0),
                            float(p[37] or 0),float(p[9] or 0),float(p[10] or 0),
                            float(p[19] or 0),float(p[20] or 0)))
            except ValueError: continue
    return out

def save(con,day,ts,rows):
    con.executemany("insert or replace into snapf values(?,?,?,?,?,?,?,?,?,?,?)",
        [(r[0],day,ts,r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8]) for r in rows])
    con.commit()

def validate(rows,day):
    """⛔锚点验通道(main建议2): 铺全市场前先确认竞价段返回的是真竞价数据, 不是昨收或停滞值。
    通道坏掉的失败形态是静默的——返回结构完整但全是昨收, 看不出错。"""
    n=len(rows)
    moved=sum(1 for r in rows if r[2] and abs(r[1]/r[2]-1)>0.001)   # 价格偏离昨收
    # ⛔2026-09-08实测修正: 竞价段(09:15-09:25) 腾讯 volume 字段[6] **恒为0**,
    #   累计匹配量在 bid1量/ask1量 上(且竞价撮合时 bid1价==ask1价==参考价)。
    #   原代码拿 volume>0 当"有量"判据 → 竞价段必然0% → validate必然失败 → 整轮中止。
    #   这是把"我以为的字段"当成了"实际的字段", 昨天只验了盘中(volume正常)没验竞价段。
    hasvol=sum(1 for r in rows if r[6]>0 or r[8]>0)                  # 买一量或卖一量
    hasbid=sum(1 for r in rows if r[5]>0)
    print(f'  验通道: {n}只 | 价≠昨收 {moved}只({moved/max(n,1)*100:.0f}%) | '
          f'有量 {hasvol}只({hasvol/max(n,1)*100:.0f}%) | 有买一 {hasbid}只({hasbid/max(n,1)*100:.0f}%)')
    if moved/max(n,1)<0.05:
        print('  ⛔价格几乎全等于昨收 → 通道可能没返回竞价数据, 停下人工确认'); return False
    if hasvol/max(n,1)<0.05:
        print('  ⛔几乎全无委托量(买一/卖一量都为0) → 竞价数据没拿到, 停下人工确认'); return False
    return True

def ticks():
    """生成今天的采样时刻表"""
    d=datetime.date.today().isoformat(); out=[]
    for (a,b),step in (SEG1,SEG2):
        t=datetime.datetime.fromisoformat(f'{d} {a}'); end=datetime.datetime.fromisoformat(f'{d} {b}')
        while t<=end: out.append(t); t+=datetime.timedelta(seconds=step)
    return sorted(set(out))

def main():
    a=sys.argv[1:] or ['run']
    if a[0]=='test':
        codes=codes_all(); print(f'验通道: 全市场{len(codes)}只')
        t0=time.time(); rows=poll(codes)
        print(f'  一轮用时 {time.time()-t0:.2f}秒, 拿到 {len(rows)} 只')
        validate(rows,datetime.date.today().isoformat()); return
    if a[0]=='verify':
        # ⛔已知答案锚点: 集合竞价撮合结果 = 当日开盘价。
        # 09:25 后那一笔快照的price 必须 == 当日open, 不等就是通道拿错了东西。
        # 这条比"看着像竞价数据"强得多——它有唯一正确答案, 静默错误藏不住。
        day=a[1] if len(a)>1 else datetime.date.today().isoformat()
        con=db()
        snap={c:p for c,p in con.execute(
            "select code,price from snapf where date=? and ts=(select max(ts) from snapf where date=?)",(day,day))}
        if not snap: print(f'⛔{day} 无采集数据'); return
        codes=sorted(snap); opens={}
        for i in range(0,len(codes),BATCH):
            q=','.join(mkt(c)+c for c in codes[i:i+BATCH])
            try: raw=urllib.request.urlopen(f'http://qt.gtimg.cn/q={q}',timeout=8).read().decode('gbk','ignore')
            except Exception: continue
            for line in raw.split('\n'):
                p=line.split('~')
                if len(p)>6 and 'none_match' not in line:
                    try: opens[p[2]]=float(p[5] or 0)
                    except ValueError: pass
        ok=bad=skip=0; egs=[]
        for c,pr in snap.items():
            o=opens.get(c,0)
            if not o or not pr: skip+=1; continue
            if abs(pr-o)<=max(0.011,o*0.0011): ok+=1
            else:
                bad+=1
                if len(egs)<8: egs.append(f'{c} 快照{pr:.2f} vs 开盘{o:.2f}')
        n=ok+bad
        print(f'锚点校验 {day}: 对上 {ok}/{n} ({ok/max(n,1)*100:.1f}%) | 不符 {bad} | 无数据跳过 {skip}')
        for e in egs: print('   ⛔',e)
        print('  ✅通道可信' if ok/max(n,1)>=0.97 else '  ⛔对不上比例过高, 通道有问题, 别用这批数据')
        return
    if a[0]=='stat':
        con=db()
        for d,n,k in con.execute("select date,count(*),count(distinct code) from snapf group by date order by date"):
            print(f'  {d}  {n:>8}条  {k:>5}只')
        print('总计',con.execute("select count(*) from snapf").fetchone()[0],'条 (自建源snapf表)')
        return
    # run
    day=datetime.date.today().isoformat()
    codes=codes_all(); con=db(); T=ticks()
    got=0; ticks_ok=0
    print(f'竞价采集 {day} | 全市场{len(codes)}只 | {len(T)}个时刻 {T[0].strftime("%H:%M:%S")}~{T[-1].strftime("%H:%M:%S")}',flush=True)
    checked=False
    for k,t in enumerate(T):
        w=(t-datetime.datetime.now()).total_seconds()
        if w>0: time.sleep(w)
        elif w<-5: continue                      # 已错过的时刻跳过, 不补打
        t0=time.time(); rows=poll(codes)
        if not checked and rows:
            if not validate(rows,day): print('⛔通道验证未过, 中止采集'); return
            checked=True
        save(con,day,t.strftime('%H:%M:%S'),rows)
        got+=len(rows); ticks_ok+= 1 if rows else 0
        print(f'  {t.strftime("%H:%M:%S")} {len(rows):>5}只 {time.time()-t0:.2f}s',flush=True)
    # ⛔2026-09-08修: 原为无条件 print('完成') —— 全部轮次失败也打"完成"。
    # main提炼的判据: 看成功日志不要问"数字对不对", 问"这个✅是算出来的还是硬写在字符串里的"。
    # 硬写的✅等于没有。同族: feishu_wiki全批失败打"✅写0块"。
    n_db=con.execute("select count(*) from snapf where date=?",(day,)).fetchone()[0]
    if ticks_ok==0 or n_db==0:
        print(f'⛔采集失败: {len(T)}个时刻全部无数据, 库内当日{n_db}条。不是"完成"。',flush=True)
        con.close(); sys.exit(1)
    if ticks_ok < len(T)*0.8:
        print(f'⚠️采集不完整: {len(T)}个时刻仅{ticks_ok}个拿到数据, 库内{n_db}条',flush=True)
    else:
        print(f'采集完成: {ticks_ok}/{len(T)}个时刻, 累计{got}条, 库内当日{n_db}条',flush=True)
    con.close()

if __name__=='__main__': main()
