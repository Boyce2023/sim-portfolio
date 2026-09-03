#!/usr/bin/env python3
"""B策略临板报警 (2026-09-03, Buwen: "买得进去得提前告诉我")
候选池 = 昨日涨停池(二进三候选) ∪ 全市场今日涨≥5%且市值≥10亿换手≤12%的股(每10分钟刷新)
报警: 10cm股涨幅≥8.5% / 20cm股≥17% → 飞书"临板"; 到板→"已封"; 每股每日各报一次。
用法: python3 scripts/b_board_alert.py  (前台循环到15:00; launchd 09:27起)"""
import sys,json,time,datetime,os,subprocess
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts')
from astock_data_layer import get_batch_prices,get_full_market
ROOT='/Users/huaichuaibeimeng/claude-projects/sim-portfolio'
def fs(msg): subprocess.run(['bash',os.path.expanduser('~/.claude/session-remote/fs-reply.sh'),msg],capture_output=True)
def yesterday_pool():
    files=sorted(f for f in os.listdir(f'{ROOT}/data/zt_pool') if f.endswith('.json'))
    today=datetime.date.today().strftime('%Y%m%d'); prev=[f for f in files if f[:8]<today]
    if not prev: return {}
    return {str(r['代码']):r['名称'] for r in json.load(open(f'{ROOT}/data/zt_pool/{prev[-1]}'))}
def refresh_pool():
    pool=dict(yesterday_pool())
    try:
        for x in get_full_market():
            c=str(x.get('code') or '')[-6:]; cp=x.get('change_pct') or 0
            if cp>=5 and (x.get('market_cap') or 0)>=10 and (x.get('turnover_rate') or 99)<=12 and not str(x.get('name','')).startswith(('ST','*ST')) and not c.startswith(('4','8','9')):
                pool[c]=x.get('name')
    except Exception as e: print('full_market fail',e)
    return pool
alerted={}; sealed={}
pool=refresh_pool(); last_refresh=time.time(); print(f"{datetime.datetime.now():%H:%M} 候选池{len(pool)}只")
_y=yesterday_pool(); fs(f"[B盘前候选] {datetime.datetime.now():%H:%M} 池{len(pool)}只(昨日板{len(_y)}+今强势{len(pool)-len(_y)}). 昨日板二进三候选: "+"/".join(list(_y.values())[:25])+" — 临板(10cm≥8.5%/20cm≥17%)即报,请提前排板")
while datetime.datetime.now().strftime('%H%M')<'1500':
    if time.time()-last_refresh>600: pool=refresh_pool(); last_refresh=time.time()
    codes=list(pool)
    for i in range(0,len(codes),50):
        q=get_batch_prices(codes[i:i+50])
        for c,d in q.items():
            cp=d.get('change_pct') or 0; lim=19.9 if c.startswith(('30','68')) else 9.9
            thr=17.0 if lim>10 else 8.5
            if cp>=lim-0.05 and c not in sealed:
                sealed[c]=cp; fs(f"[B已封] {pool.get(c,'')}({c}) {cp:+.2f}% 现{d.get('price')} 换手{d.get('turnover_rate')}% {datetime.datetime.now():%H:%M}")
            elif thr<=cp<lim-0.05 and c not in alerted:
                alerted[c]=cp; fs(f"[B临板⚡] {pool.get(c,'')}({c}) {cp:+.2f}% 距板{lim-cp:.1f}pp 现{d.get('price')} 换手{d.get('turnover_rate')}% 市值{d.get('market_cap')}亿 {datetime.datetime.now():%H:%M} ← 现在排板")
    time.sleep(45)
print('15:00 收工', '临板',len(alerted),'已封',len(sealed))
