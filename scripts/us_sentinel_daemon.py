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
        subprocess.Popen(['bash',FS,f'[美股哨兵] {msg}'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)

def check():
    import yfinance as yf
    d={}; wins={}; h3={}
    for t in NEED:
        try:
            h=yf.Ticker(t).history(period='3mo')['Close'].dropna()
            if len(h)>=4:
                d[t]=(float(h.iloc[-1]),(float(h.iloc[-1])/float(h.iloc[-2])-1)*100)
                h3[t]=(float(h.iloc[-1])/float(h.iloc[-4])-1)*100
                if t=='DX-Y.NYB' and len(h)>=31:
                    wins={k:(float(h.iloc[-1])/float(h.iloc[-1-k])-1)*100 for k in (5,10,30)}
        except Exception: pass
    miss=[t for t in NEED if t not in d]
    if miss: return 'STALE', f"哨兵取不到数: {','.join(miss)} — 此刻它是瞎的"
    dxy,dxc=d['DX-Y.NYB']; gx,gxc=d['GDX']; au,auc=d['GC=F']; tn,_=d['^TNX']
    cnt=0
    try: cnt=json.load(open(f'{R}/.dxy_count.json'))['count']
    except Exception: pass
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

def main():
    prev=''; fails=0
    while True:
        open(HB,'w').write(str(int(time.time())))
        t=ny_now()
        if not market_open(t):
            time.sleep(900); continue
        try: status,msg=check()
        except Exception as e: status,msg='STALE',f"哨兵异常: {str(e)[:80]}"
        if status=='STALE':
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
