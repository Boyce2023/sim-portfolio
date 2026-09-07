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
def _prev_trading_day():
    """上一个交易日(粗口径: 跳过周末)。节假日会误报, 但误报远好过静默用陈数据。"""
    d=datetime.date.today()-datetime.timedelta(days=1)
    while d.weekday()>=5: d-=datetime.timedelta(days=1)
    return d.strftime('%Y%m%d')

def yesterday_pool():
    """⛔2026-09-07修: 原实现取"文件名<今天的最后一个", 昨日池没生成时会静默拿
    前天/上周/上个月的池子当"昨日板", 不报错不提示日期——二进三候选基于过期数据。
    与交易所前缀写错时腾讯静默返回过期bar是同一族坑。
    判据(main提炼): 好锚点是"错了会自己露馅"的。这里的唯一正确答案=上一交易日。"""
    files=sorted(f for f in os.listdir(f'{ROOT}/data/zt_pool') if f.endswith('.json'))
    today=datetime.date.today().strftime('%Y%m%d'); prev=[f for f in files if f[:8]<today]
    exp=_prev_trading_day()
    if not prev:
        fs(f"[B⛔数据] zt_pool 一个历史文件都没有, 昨日板池为空。二进三候选本日不可用。"); return {}
    fn=prev[-1]; got=fn[:8]
    if got!=exp:
        fs(f"[B⛔数据] 昨日涨停池陈旧: 期望{exp}, 实际最新只有{got}。"
           f"⛔已拒绝使用(避免拿过期池当昨日板), 二进三候选本日不可用。请先补跑涨停池采集。")
        return {}
    return {str(r['代码']):r['名称'] for r in json.load(open(f'{ROOT}/data/zt_pool/{fn}'))}
def refresh_pool():
    pool=dict(yesterday_pool())
    try:
        for x in get_full_market():
            c=str(x.get('code') or '')[-6:]; cp=x.get('change_pct') or 0
            if cp>=5 and (x.get('market_cap') or 0)>=10 and (x.get('turnover_rate') or 99)<=12 and not str(x.get('name','')).startswith(('ST','*ST')) and not c.startswith(('4','8','9')):
                pool[c]=x.get('name')
    except Exception as e: print('full_market fail',e)
    return pool
def shortlist():
    """封单四道门短名单(gates>=3), 由每日收盘版调仓写到 data/b_watch_YYYYMMDD.json
    ⛔2026-09-07修: 原实现三种情况都返回{}, 播报统一显示"(无)"——
      ①文件不存在(上游收盘版没跑) ②文件在但候选为空(今天真没有) ③解析失败(格式坏了)
    ①③是故障, ②是事实, 输出却一样, 我会把故障当成"今天没票"。返回(dict, 状态)分开。"""
    p=f'{ROOT}/data/b_watch_{datetime.datetime.now():%Y%m%d}.json'
    if not os.path.exists(p):
        return {}, f"⛔短名单文件未生成({os.path.basename(p)}), 上游收盘版调仓可能没跑——这不等于今天没候选"
    try:
        cand=json.load(open(p)).get('候选',[])
    except Exception as e:
        return {}, f"⛔短名单文件解析失败({type(e).__name__}), 格式可能坏了——这不等于今天没候选"
    if not cand: return {}, "今日四门短名单为空(文件正常, 确实没有过门的票)"
    return {str(c['code']):f"{c['name']}({c['lb']}板{c['gates']}/4)" for c in cand}, None
SHORT,SHORT_ERR=shortlist()
alerted={}; sealed={}
pool=refresh_pool(); last_refresh=time.time(); print(f"{datetime.datetime.now():%H:%M} 候选池{len(pool)}只")
_y=yesterday_pool()
_sl=" / ".join(SHORT.values()) if SHORT else (SHORT_ERR or "(无)")
_yy="/".join(list(_y.values())[:20])
fs(f"[B盘前候选] {datetime.datetime.now():%H:%M} 池{len(pool)}只(昨日板{len(_y)}+今强势{len(pool)-len(_y)}). ⭐四门短名单: {_sl} ‖ 昨日板二进三: {_yy} — 临板(10cm≥8.5%/20cm≥17%)即报,请提前排板")
while datetime.datetime.now().strftime('%H%M')<'1500':
    if time.time()-last_refresh>600: pool=refresh_pool(); last_refresh=time.time()
    codes=list(pool)
    for i in range(0,len(codes),50):
        q=get_batch_prices(codes[i:i+50])
        for c,d in q.items():
            cp=d.get('change_pct') or 0; lim=19.9 if c.startswith(('30','68')) else 9.9
            thr=17.0 if lim>10 else 8.5
            if cp>=lim-0.05 and c not in sealed:
                sealed[c]=cp; fs(f"[B已封]{chr(11088) if c in SHORT else chr(32)} {pool.get(c,'')}({c}) {cp:+.2f}% 现{d.get('price')} 换手{d.get('turnover_rate')}% {datetime.datetime.now():%H:%M}")
            elif thr<=cp<lim-0.05 and c not in alerted:
                alerted[c]=cp; fs(f"[B临板⚡]{chr(11088) if c in SHORT else chr(32)} {pool.get(c,'')}({c}) {cp:+.2f}% 距板{lim-cp:.1f}pp 现{d.get('price')} 换手{d.get('turnover_rate')}% 市值{d.get('market_cap')}亿 {datetime.datetime.now():%H:%M} ← 现在排板")
    time.sleep(45)
print('15:00 收工', '临板',len(alerted),'已封',len(sealed))
