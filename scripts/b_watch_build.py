#!/opt/homebrew/bin/python3
"""B策略次日候选短名单生成器 — 收盘调仓第④步产出, 供次日 09:27 的 b_board_alert 读取
⛔2026-09-07建: 此前 b_watch_YYYYMMDD.json 全靠手动生成(09-04是当天09:12手搓,
   09-05是前一晚21:35手搓), 没有任何脚本或定时负责 → 某天没人手搓, 盘中短名单就是空的,
   而旧版 shortlist() 对"文件没生成"和"今天真没候选"返回同一个值, 我看不出区别。
   本脚本把它变成收盘流程的固定产出。

四道门(全部来自当日涨停池, 无前视):
  ①首封 < 10:00   ②炸板次数 = 0   ③封板资金÷成交额 ≥ 3%   ④同行业当日涨停 ≥ 2只
市值门(三次修正定版): 首板需流通市值≥100亿; 2板及以上需≥50亿
排除: 一字板(开盘价即涨停价, 买不进) / ST / 北交所
用法: b_watch_build.py [YYYYMMDD涨停池日期]   默认今天, 产出次一日的候选文件
"""
import json,os,sys,datetime,urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def mkt(c): return 'sh' if c[0] in '56' else ('bj' if c[0] in '48' else 'sz')

def opens(codes):
    """取当日开盘价, 用于准确排一字板(只看封板时间会把'竞价快速封板'误判成一字)"""
    out={}
    for i in range(0,len(codes),400):
        q=','.join(mkt(c)+c for c in codes[i:i+400])
        try: raw=urllib.request.urlopen(f'http://qt.gtimg.cn/q={q}',timeout=8).read().decode('gbk','ignore')
        except Exception as e: print('  取开盘价失败',type(e).__name__); continue
        for line in raw.split('\n'):
            p=line.split('~')
            if len(p)>6 and 'none_match' not in line:
                try: out[p[2]]={'open':float(p[5] or 0),'close':float(p[3] or 0),'prev':float(p[4] or 0)}
                except ValueError: pass
    return out

def main():
    day=sys.argv[1] if len(sys.argv)>1 else datetime.date.today().strftime('%Y%m%d')
    src=f'{ROOT}/data/zt_pool/{day}.json'
    if not os.path.exists(src): print(f'⛔涨停池 {day} 不存在: {src}'); sys.exit(1)
    zt=json.load(open(src))
    print(f'涨停池 {day}: {len(zt)} 只')
    ind_cnt={}
    for r in zt: ind_cnt[r.get('所属行业')]=ind_cnt.get(r.get('所属行业'),0)+1
    px=opens([str(r['代码']) for r in zt])
    print(f'开盘价取到 {len(px)} 只')
    cands=[]; stat={'一字':0,'市值':0,'门<3':0,'ST/北交':0}
    for r in zt:
        c=str(r['代码']); nm=str(r.get('名称') or '')
        if nm.startswith(('ST','*ST')) or c[0] in '489': stat['ST/北交']+=1; continue
        o=px.get(c,{})
        if o.get('open') and o.get('close') and abs(o['open']-o['close'])<0.005:
            stat['一字']+=1; continue                      # 开盘即收盘且是涨停 = 一字板, 买不进
        lb=int(r.get('连板数') or 1); mc=(r.get('流通市值') or 0)/1e8
        need=100 if lb<=1 else 50
        if mc<need: stat['市值']+=1; continue
        amt=r.get('成交额') or 0; seal=r.get('封板资金') or 0
        ratio=seal/amt if amt else 0
        t1=str(r.get('首次封板时间') or '999999')
        ind=r.get('所属行业'); cc=ind_cnt.get(ind,0)
        g=sum([t1<'100000', (r.get('炸板次数') or 0)==0, ratio>=0.03, cc>=2])
        if g<3: stat['门<3']+=1; continue
        cands.append({'code':c,'name':nm,'lb':lb,'ind':ind,'gates':g,
                      'ratio':round(ratio,3),'t1':t1,'turn':round(r.get('换手率') or 0,1),
                      'cc':cc,'mcap':round(mc,1)})
    cands.sort(key=lambda x:(-x['gates'],-x['lb'],-x['ratio']))
    nxt=datetime.datetime.strptime(day,'%Y%m%d').date()+datetime.timedelta(days=1)
    while nxt.weekday()>=5: nxt+=datetime.timedelta(days=1)
    out={'date':nxt.isoformat(),'source':f'zt_pool/{day}.json ({len(zt)}只涨停)',
         'chains':sorted({c['ind'] for c in cands}),
         '⛔硬门槛':'首板流通市值≥100亿 / 2板及以上≥50亿; 四门过≥3; 排除一字板与ST与北交所',
         '生成时间':datetime.datetime.now().isoformat(timespec='seconds'),
         '过滤统计':stat,'候选':cands}
    p=f'{ROOT}/data/b_watch_{nxt.strftime("%Y%m%d")}.json'
    json.dump(out,open(p,'w'),ensure_ascii=False,indent=1)
    print(f'过滤: 一字{stat["一字"]} 市值不足{stat["市值"]} 四门<3的{stat["门<3"]} ST/北交{stat["ST/北交"]}')
    print(f'→ {len(cands)} 只候选写入 {os.path.basename(p)} (供 {nxt} 盘前使用)')
    for c in cands: print(f'   {c["code"]} {c["name"]:<8}{c["lb"]}板 {c["gates"]}/4门 封{c["ratio"]*100:.1f}% 首封{c["t1"]} 市值{c["mcap"]}亿 {c["ind"]}({c["cc"]}只)')
if __name__=='__main__': main()
