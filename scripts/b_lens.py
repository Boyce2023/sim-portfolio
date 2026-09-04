#!/opt/homebrew/bin/python3
"""B策略透镜: 对任意股票列表算B核心规则特征(前1日涨幅/量比/前20日涨幅/连板)。
用法: b_lens.py pool            -> 跑当日涨停池
      b_lens.py 600111,603259  -> 跑指定标的
数据源腾讯不复权日K(短窗口口径,除权日需注意)。"""
import sys,os,json,time,requests
for k in ('HTTPS_PROXY','HTTP_PROXY','https_proxy','http_proxy','ALL_PROXY'): os.environ.pop(k,None)
def mkt(code):
    """⛔代码→交易所前缀。6/5=沪(含ETF), 0/3=深(3xxxxx是创业板属深, 曾误判为沪), 4/8=北交所。
    误判后果: 腾讯qt返回v_pv_none_match, kline静默返回过期bar(不报错)——2026-09-03实证。"""
    c=code[0]
    return 'sh' if c in '65' else ('bj' if c in '48' else 'sz')

BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def rt(code):
    """腾讯实时快照, 返回(日期,收盘,成交量手)"""
    mk=mkt(code)
    r=requests.get(f'https://qt.gtimg.cn/q={mk}{code}',timeout=10); r.encoding='gbk'
    fl=r.text.split('~')
    if len(fl)<40: return None
    return (fl[30][:8], float(fl[3]), float(fl[6]))   # 日期时间/现价/成交量(手)

def kline(code,start='2026-07-01',end=None):
    mk=mkt(code)
    u=f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={mk}{code},day,{start},{end or '2026-12-31'},60"
    for _ in range(3):
        try:
            j=requests.get(u,timeout=12).json()['data'][mk+code]
            k=j.get('day') or j.get('qfqday')
            if k: return k
        except Exception: time.sleep(0.4)
    return None
def feat(code,name=''):
    k=kline(code)
    if not k or len(k)<23: return None
    c=[float(x[2]) for x in k]; v=[float(x[5]) for x in k]
    # 腾讯日K在收盘后并非全部即时更新: 若最后一根不是今天, 用实时快照补今日bar
    q=rt(code)
    if q and k[-1][0].replace('-','')!=q[0]:
        c.append(q[1]); v.append(q[2]); k.append([q[0],'','','',''])
    today_chg=(c[-1]/c[-2]-1)*100
    prev=(c[-2]/c[-3]-1)*100
    v20=sum(v[-21:-1])/20
    vr=v[-1]/v20 if v20 else 99
    r20=(c[-2]/c[-22]-1)*100
    return dict(code=code,name=name,today=today_chg,prev=prev,vr=vr,r20=r20,close=c[-1])
def core(f): return f['prev']>3 and f['vr']<1.5
if __name__=='__main__':
    arg=sys.argv[1]
    if arg=='pool':
        pool=json.load(open(f"{BASE}/data/zt_pool/{sys.argv[2] if len(sys.argv)>2 else '20260903'}.json"))
        items=[(p['代码'],p['名称'],p) for p in pool]
    else:
        items=[(c,'',None) for c in arg.split(',')]
    out=[]
    for c,n,p in items:
        f=feat(c,n)
        if not f: print('SKIP',c,n); continue
        if p: f.update(lb=p['连板数'],turn=p['换手率'],mcap=p['流通市值']/1e8,seal=p['封板资金']/1e8,t1=p['首次封板时间'],boom=p['炸板次数'],ind=p['所属行业'])
        f['B核心']=core(f); out.append(f)
        time.sleep(0.05)
    json.dump(out,open('/tmp/b_lens_out.json','w'),ensure_ascii=False)
    print(json.dumps({'n':len(out),'hit':sum(1 for f in out if f['B核心'])},ensure_ascii=False))
