#!/opt/homebrew/bin/python3
"""封板窗口采集 — 每轮记录今日B候选与涨停价的距离, 落 data/b_seal_window.jsonl。
⛔2026-09-10建, 起因: Buwen 问"B为什么还零成交"。回测假设涨停必成交, 实盘我90秒轮询一次,
   今日中粮09:31封板09:36炸板只有5分钟窗口。要判断"轮询频率是否抓不住封板", 必须先有窗口时长数据。
用法: 无参数, 由 b_exec_loop.sh 每轮调用。非交易时段自动退出。"""
import json,os,datetime,urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
now=datetime.datetime.now(); hm=now.strftime('%H%M')
if not (('0930'<=hm<='1130') or ('1300'<=hm<='1500')): raise SystemExit(0)
p=f"{ROOT}/data/b_watch_{now.strftime('%Y%m%d')}.json"
if not os.path.exists(p): raise SystemExit(0)
cands=json.load(open(p)).get('候选',[])
if not cands: raise SystemExit(0)
q=','.join(('sh' if c['code'][0]=='6' else 'sz')+c['code'] for c in cands)
try:
    raw=urllib.request.urlopen(urllib.request.Request('https://qt.gtimg.cn/q='+q,headers={'User-Agent':'Mozilla/5.0'}),timeout=8).read().decode('gbk','ignore')
except Exception as e:
    # ⛔2026-09-14: 原写法失败静默exit 0, 当天早盘有1377条而11:30后零条且无任何报错可查。
    #   失败必须留痕, 否则"没数据"和"采集挂了"分不开(故障不得降级成合法正常值)。
    with open('/tmp/b_seal_window_err.log','a') as fh:
        fh.write(f"{datetime.datetime.now():%F %T} 行情取数失败 {type(e).__name__}: {e}\n")
    raise SystemExit(2)
rows=[]
for line in raw.strip().split(';'):
    f=line.split('~')
    if len(f)<45 or not f[3]: continue
    code=f[2]; px=float(f[3]); prev=float(f[4])
    lim=round(prev*(1.2 if code[:2] in ('30','68') else 1.1),2)
    rows.append({'t':now.strftime('%H:%M:%S'),'code':code,'name':f[1],'px':px,'lim':lim,
                 'sealed':abs(px-lim)<0.005,'gap_pct':round((px/lim-1)*100,2),
                 'turn':float(f[38]) if f[38] else None,'amount':float(f[37] or 0)*1e4})
if rows:
    with open(f'{ROOT}/data/b_seal_window.jsonl','a') as fh:
        for r in rows: fh.write(json.dumps(r,ensure_ascii=False)+'\n')
