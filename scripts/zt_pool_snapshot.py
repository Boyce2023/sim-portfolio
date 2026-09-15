#!/usr/bin/env python3
"""每交易日15:30留存东财涨停池快照(含首次封板时间/炸板次数/封板资金/换手), 供B策略逐笔验成交(东财仅保留约1个月历史)。
输出: data/zt_pool/YYYYMMDD.json  (2026-09-02建)"""
import json,sys,datetime,os,time
import akshare as ak
D=sys.argv[1] if len(sys.argv)>1 else datetime.date.today().strftime('%Y%m%d')
if datetime.datetime.strptime(D,'%Y%m%d').weekday()>4: print('weekend skip'); sys.exit(0)
out=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'data','zt_pool',f'{D}.json')
# ⛔2026-09-15: 原来3次重试各隔5秒, 09-14 东财连续'连接被重置'三次即FAIL退出且不通知任何人,
#   连锁导致 b_watch_build 缺存档失败、09-15 B策略无候选名单。改为退避重试约12分钟 + 最终失败必告警。
WAITS=(5,30,60,120,240,300)
err=None
for a,w in enumerate((0,)+WAITS):
    if w: time.sleep(w)
    try:
        df=ak.stock_zt_pool_em(date=D)
        if df is None or not len(df): raise RuntimeError('empty')
        json.dump(df.to_dict('records'),open(out,'w'),ensure_ascii=False,default=str)
        print(f'zt_pool {D}: {len(df)}板 → {out} (第{a+1}次成功)'); sys.exit(0)
    except Exception as e:
        err=e; print(f'zt_pool {D} 第{a+1}次失败: {type(e).__name__}: {e}',flush=True)
print(f'zt_pool {D} FAIL: {err}')
inbox=os.environ.get('ZT_ALERT_INBOX',os.path.expanduser('~/.claude/session-inbox/astock.jsonl'))
with open(inbox,'a',encoding='utf-8') as fh:
    fh.write(json.dumps({"ts":datetime.datetime.now().isoformat(timespec='seconds'),"from":"zt-pool-snapshot","kind":"task",
        "instruction":f"⛔涨停池存档{D}失败({type(err).__name__}: {err})。后果: 15:40 b_watch_build 将因缺存档失败, 次日B策略无候选名单。手动补: python3 scripts/zt_pool_snapshot.py {D} 后再跑 scripts/b_watch_build.py {D}"},ensure_ascii=False)+'\n')
sys.exit(1)
