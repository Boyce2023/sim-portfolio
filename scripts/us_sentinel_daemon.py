#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实物资产哨兵 daemon (2026-09-02): 脱离session, launchd KeepAlive 常驻。
原因: session内Monitor随重启死, 8/31~9/2 死了3次, 9/1扳机B触发6小时无人发现。
输出: 状态变化 → us inbox(session监听消费) + 飞书(Buwen可见); 心跳 → .sentinel_heartbeat(health_check反查)
"""
import json, os, time, subprocess, datetime, warnings
warnings.filterwarnings('ignore')
R=os.path.expanduser('~/claude-projects/sim-portfolio')
INBOX=os.path.expanduser('~/.claude/session-inbox/us.jsonl')
FS=os.path.expanduser('~/.claude/session-remote/fs-reply.sh')
HB=f'{R}/.sentinel_heartbeat'
STATE=f'{R}/.sentinel_daemon_state.json'
NEED=['DX-Y.NYB','GDX','GC=F','^TNX','NEM','RGLD']

def ny_now():
    import zoneinfo
    return datetime.datetime.now(zoneinfo.ZoneInfo('America/New_York'))

def market_open(t):
    return t.weekday()<5 and (9,30)<=(t.hour,t.minute)<=(16,15)

def emit(msg, level='info'):
    rec=dict(ts=datetime.datetime.now().isoformat(timespec='seconds'),from_='us-sentinel-daemon',kind='alert',level=level,text=msg)
    rec['from']=rec.pop('from_')
    with open(INBOX,'a') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
    if level in ('warn','crit'):
        # ⛔2026-09-08: 原实现 Popen+双DEVNULL+start_new_session = 发射后不管。
        # 飞书挂了/token过期/脚本报错, 哨兵一律不知道——而这是它唯一的对外告警出口。
        # 判据(interview提, 全组采纳): 我为了解决A问题(不阻塞主循环)引入的措施,
        # 是否顺手关掉了B问题(告警是否真送达)的感知通道? 这里答案是"是"。
        # 改法: 不改回阻塞, 改成短超时+捕获结果; 失败写本地失败日志, inbox那条本来就已经写了(双通道)。
        try:
            r = subprocess.run(['bash', FS, f'[美股哨兵] {msg}'],
                               capture_output=True, text=True, timeout=20)
            if r.returncode != 0:
                _log_alert_failure(f"fs-reply退出码{r.returncode}: {(r.stderr or r.stdout)[:160]}", msg)
        except subprocess.TimeoutExpired:
            _log_alert_failure("fs-reply超时20秒未返回", msg)
        except Exception as e:
            _log_alert_failure(f"fs-reply调用异常 {type(e).__name__}: {str(e)[:120]}", msg)


def _log_alert_failure(why, original_msg):
    """飞书没送达时留痕。inbox 那条已经写了, 这里记的是"送达失败"本身。"""
    try:
        with open(f'{R}/.sentinel_alert_failures.log', 'a') as f:
            f.write(json.dumps({
                'ts': datetime.datetime.now().isoformat(timespec='seconds'),
                'why': why, 'undelivered_alert': original_msg[:300],
            }, ensure_ascii=False) + '\n')
    except Exception:
        pass          # 连留痕都失败就只能放弃, 但inbox那条仍在


# ── 扳机A计数器 (2026-09-07 重写) ─────────────────────────────────────
# 事故: 原实现 `try: cnt=json.load(...)["count"] except: pass`, cnt 默认 0。
# 故障注入实测: 文件在 / 文件丢失 / 文件损坏, 三种输出完全一样都是"计数0天",
# 而"计数0天"语义上等同于"美元从未连续站上99.60"(最安全最正常的样子)。
# 后果: 文件一旦丢或坏, 扳机A(管金对簇17%)永远不触发而哨兵一直报正常。
# 另: 全代码库无任何程序写它, 一直靠手工维护, 09-04 起就没更新。
# 现在: 1) 哨兵自己维护 2) 三态区分(可用/缺失/损坏) 3) 新鲜度断言
DXY_FILE = R + '/.dxy_count.json'
DXY_LINE = 99.60

def read_dxy_count():
    """返回 (count, note)。count 为 None 表示不可信, 调用方必须报 STALE。"""
    try:
        with open(DXY_FILE) as f:
            j = json.load(f)
    except FileNotFoundError:
        return None, '计数文件不存在'
    except Exception as e:
        return None, '计数文件损坏无法解析(' + type(e).__name__ + ')'
    if not isinstance(j.get('count'), int):
        return None, '计数文件缺少合法 count 字段'
    days = j.get('days') or []
    if not days:
        return None, '计数文件无 days 明细, 无法判断新鲜度'
    last_date = days[-1].get('date')
    try:
        ld = datetime.date.fromisoformat(last_date)
    except Exception:
        return None, '计数文件日期不可解析: ' + str(last_date)
    gap = (ny_now().date() - ld).days
    if gap > 4:
        return None, '计数已 ' + str(gap) + ' 天未更新(最后 ' + last_date + '), 可能无人维护'
    return j['count'], '最后更新 ' + last_date


def update_dxy_count(close_px, close_date):
    """收盘后按规则推进计数。只在收盘价上判定(feedback_trigger_close_only)。"""
    try:
        with open(DXY_FILE) as f:
            j = json.load(f)
    except Exception:
        j = {'rule': '扳机A: 连续3个交易日收盘站上99.60 且 5/10/30日窗口同向 → 金对20.5%降至12%',
             'count': 0, 'days': []}
    days = j.setdefault('days', [])
    if days and days[-1].get('date') == close_date:
        return j['count']
    above = close_px >= DXY_LINE
    j['count'] = (j.get('count', 0) + 1) if above else 0
    days.append({'date': close_date, 'close': round(close_px, 3), 'above': above})
    j['days'] = days[-10:]
    j['auto_maintained_since'] = '2026-09-07'
    tmp = DXY_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(j, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DXY_FILE)
    return j['count']


def check():
    import yfinance as yf
    d={}; wins={}; h3={}; dates={}
    for t in NEED:
        try:
            h=yf.Ticker(t).history(period='3mo')['Close'].dropna()
            if len(h)>=4:
                dates[t]=h.index[-1].date()
                d[t]=(float(h.iloc[-1]),(float(h.iloc[-1])/float(h.iloc[-2])-1)*100)
                h3[t]=(float(h.iloc[-1])/float(h.iloc[-4])-1)*100
                if t=='DX-Y.NYB' and len(h)>=31:
                    wins={k:(float(h.iloc[-1])/float(h.iloc[-1-k])-1)*100 for k in (5,10,30)}
        except Exception: pass
    miss=[t for t in NEED if t not in d]
    if miss: return 'STALE', f"哨兵取不到数: {','.join(miss)} — 此刻它是瞎的"
    # ⛔2026-09-07 事故: 劳动节休市日哨兵仍每15分钟按周五收盘价报警(10Y 4.784)。
    # market_open() 只判周一至周五+时段, 不认节假日 → "休市无数据"与"交易日数据没变"输出一样。
    # 修法不硬编日历(会过期), 改为断言数据日期==美东今日; 同时覆盖节假日/数据源滞后/停摆三种。
    stale_dates = {k: v for k, v in dates.items() if v != ny_now().date()}
    if stale_dates:
        shown = ', '.join(f"{k}@{v}" for k, v in list(stale_dates.items())[:3])
        return 'HOLIDAY', (f"数据日期不是今天({shown}) — 休市或数据源滞后, "
                           f"本轮读数全部是上一交易日的, 不构成任何扳机判定")
    dxy,dxc=d['DX-Y.NYB']; gx,gxc=d['GDX']; au,auc=d['GC=F']; tn,_=d['^TNX']
    cnt, cnt_note = read_dxy_count()
    if cnt is None:
        return 'STALE', ('扳机A计数器不可用: ' + cnt_note +
               ' — 此刻扳机A是瞎的。不要把"计数0天"读成"美元没站上过"')
    m=[]; lvl='info'
    if dxy>=99.60:
        agree=bool(wins) and all(v>0 for v in wins.values())
        w=" ".join(f"{k}日{v:+.2f}%" for k,v in wins.items())
        m.append(f"美元{dxy:.2f}在线上|计数{cnt}天|{w}→{'同向' if agree else '不同向'}|⛔非指令:需收盘+连续3日+多窗口同向"); lvl='warn'
    elif dxy>=99.40: m.append(f"美元{dxy:.2f}逼近99.60|计数{cnt}天")
    elif cnt>0: m.append(f"⚠️美元{dxy:.2f}跌回线下→若收盘确认计数({cnt}天)归零"); lvl='warn'
    c1=(d['NEM'][1]+d['RGLD'][1])/2; c3=(h3['NEM']+h3['RGLD'])/2
    if c1<=-3 or c3<=-6: m.append(f"⚠️⚠️金对簇 单日{c1:+.2f}%/三日{c3:+.2f}% 越门槛→盘中读数,收盘确认后按预案B"); lvl='crit'
    if gxc<=-4: m.append(f"GDX单日{gxc:+.2f}%"); lvl=max(lvl,'warn',key=['info','warn','crit'].index)
    if auc<=-2: m.append(f"黄金单日{auc:+.2f}%")
    if tn>=4.75: m.append(f"10Y{tn:.3f}%上破4.75")
    if not m: return 'OK', f"美元{dxy:.2f}({dxc:+.2f}%) 计数{cnt}天 金对1日{c1:+.2f}%/3日{c3:+.2f}% GDX{gxc:+.2f}% 金{auc:+.2f}% 10Y{tn:.2f}"
    return lvl.upper(), " | ".join(m)


def post_close_maintain(t):
    """收盘后把当日美元收盘价推进计数器。⛔幂等: 同一天只写一次。
    2026-09-07 加: 此前全代码库无任何程序写 .dxy_count.json, 靠手工维护, 09-04起漏更。"""
    if t.weekday() >= 5 or (t.hour, t.minute) < (16, 20):
        return                                  # 只在交易日收盘后
    try:
        import yfinance as yf
        h = yf.Ticker('DX-Y.NYB').history(period='5d')['Close'].dropna()
        if h.empty:
            return
        d = h.index[-1].date()
        if d.weekday() >= 5 or d != t.date():
            return                              # 数据日不是今天, 说明收盘价还没落盘, 下轮再试
        cnt = update_dxy_count(float(h.iloc[-1]), d.isoformat())
        if cnt >= 3:
            emit(f"⛔扳机A条件①达成: 美元连续{cnt}个收盘站上{DXY_LINE} "
                 f"(今日收{float(h.iloc[-1]):.3f}) — 需再核5/10/30日窗口是否同向", 'crit')
    except Exception as e:
        emit(f"扳机A计数器维护失败: {type(e).__name__} — 计数可能停更, 别当'未触发'", 'warn')


def main():
    prev=''; fails=0
    while True:
        open(HB,'w').write(str(int(time.time())))
        t=ny_now()
        if not market_open(t):
            post_close_maintain(t)   # 收盘后维护扳机A计数器
            time.sleep(900); continue
        try: status,msg=check()
        except Exception as e: status,msg='STALE',f"哨兵异常: {str(e)[:80]}"
        if status=='HOLIDAY':
            fails=0
            if msg!=prev: prev=msg          # 休市: 只记state, 不发inbox不发飞书
        elif status=='STALE':
            fails+=1
            if fails>=2: emit(f"{msg} (连续{fails}次)",'warn'); fails=0
        else:
            fails=0
            if msg!=prev:
                emit(msg, {'OK':'info','WARN':'warn','CRIT':'crit'}.get(status,'info')); prev=msg
        json.dump(dict(last=datetime.datetime.now().isoformat(timespec='seconds'),status=status,msg=msg),open(STATE,'w'),ensure_ascii=False)
        time.sleep(900)

if __name__=='__main__':
    main()
