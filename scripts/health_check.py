#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部数据源日探活 (2026-08-27 us域维护建, Buwen批准)

⛔缘起: nitter死了几天靠用户发现; git push静默失败积压28个commit; 哨兵取数失败还打OK。
脆弱外部源必须主动探活, 坏了当天知道, 不能等用户发现。
六项: yfinance / 腾讯行情 / news pulse新鲜度 / telegram脚本 / git远端可达 / git积压数。
任一FAIL → exit非零(daily_run的run_step会标红✗); 全过 → exit 0。只告警不修。
"""
import os, subprocess, sys, time

R = os.path.expanduser("~/claude-projects/sim-portfolio")
fails = []

def check(name, fn):
    try:
        ok, msg = fn()
    except Exception as e:
        ok, msg = False, str(e)[:80]
    print(f"  [{'✓' if ok else '✗'}] {name}: {msg}")
    if not ok:
        fails.append(f"{name}({msg[:40]})")

def c_yf():
    import warnings; warnings.filterwarnings('ignore')
    import yfinance as yf
    h = yf.Ticker('SPY').history(period='2d')['Close']
    if len(h) == 0: return False, "空数据"
    age_d = (time.time()/86400) - h.index[-1].timestamp()/86400
    return age_d < 5, f"SPY {float(h.iloc[-1]):.2f} bar龄{age_d:.1f}天"

def c_tencent():
    r = subprocess.run(["curl","-s","--max-time","8","https://qt.gtimg.cn/q=sh000300"],
                       capture_output=True)  # 腾讯返回GBK, 不能按utf-8解text
    out = r.stdout.decode('utf-8', errors='ignore')
    return ("v_sh000300" in out), f"返回{len(r.stdout)}字节"

def c_pulse():
    f = os.path.expanduser("~/claude-projects/news-dashboard/output/twitter_feed.json")
    if not os.path.exists(f): return False, "文件不存在"
    age = (time.time()-os.path.getmtime(f))/3600
    return age < 24, f"更新于{age:.1f}小时前(阈值24h,适配周末/假日,2026-09-02改)"

def c_tg():
    # 2026-08-27: tg退役→fs-reply(astock已sed路径); fs-reply无执行位但走`bash 脚本`调用,
    #   查X_OK会假失败(本函数刚因此误报), 改查存在+可读。
    f = os.path.expanduser("~/.claude/session-remote/fs-reply.sh")
    ok = os.path.exists(f) and os.access(f, os.R_OK)
    return ok, "fs-reply在且可读" if ok else "fs-reply缺失(通报链断)"

def c_git_remote():
    r = subprocess.run(["git","ls-remote","origin","HEAD"], cwd=R,
                       capture_output=True, text=True, timeout=30)
    return r.returncode == 0, "远端可达" if r.returncode==0 else r.stderr[:60]


def c_proxy_path():
    """区分'代理挂'与'源挂': 走代理打境外站 vs 绕代理直连境内站 (2026-09-02加, 早间08:00间歇失败归因用)"""
    import subprocess
    def curl(args):
        try:
            r=subprocess.run(['curl','-s','-o','/dev/null','-w','%{http_code}','--max-time','8']+args,capture_output=True,text=True,timeout=12); return r.stdout.strip()
        except Exception as e: return 'ERR'
    via=curl(['-x','http://127.0.0.1:1082','https://www.google.com/generate_204'])
    direct=curl(['--noproxy','*','https://qt.gtimg.cn/q=sh000001'])
    ok=(via in ('204','200')) and (direct=='200')
    return ok, f"代理路径(1082→google)={via} 直连路径(qt.gtimg)={direct}"

def c_git_backlog():
    r = subprocess.run(["git","rev-list","--count","origin/main..HEAD"], cwd=R,
                       capture_output=True, text=True, timeout=10)
    n = int(r.stdout.strip() or 0)
    return n < 10, f"未push commit {n}个" + ("" if n<10 else " ⛔积压")


def c_sentinel():
    """反查监控器的层(2026-08-27圆桌从interview学到): 哨兵Monitor死了是静默的,
    此项检查心跳文件mtime——哨兵每轮(15分钟)写一次, 超过45分钟没写=哨兵死了。"""
    f = os.path.join(R, ".sentinel_heartbeat")
    if not os.path.exists(f): return False, "心跳文件不存在(哨兵从未启动或被清)"
    age = (time.time() - os.path.getmtime(f)) / 60
    return age < 45, f"哨兵心跳{age:.0f}分钟前"

print("═══ health_check (外部源探活) ═══")
check("yfinance", c_yf)
check("腾讯行情", c_tencent)
check("news_pulse", c_pulse)
check("通报链fs", c_tg)
check("git远端", c_git_remote)
check("git积压", c_git_backlog)
check("代理/直连双路径", c_proxy_path)
check("哨兵心跳", c_sentinel)
if fails:
    print(f"⛔ {len(fails)}项失败: {', '.join(fails)}")
    try:
        subprocess.run(["bash", os.path.expanduser("~/.claude/session-remote/fs-reply.sh"),
                        f"[美股] health_check {len(fails)}项失败: {', '.join(fails)[:150]}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, timeout=30)
    except Exception:
        pass
    sys.exit(1)
print("✓ 全部通过")
# 周一平安报(2026-08-27圆桌从interview学到: 让沉默变成信号——每周一即使无事也报一声,
# Buwen的眼睛是不回归的最后一层, 从此"连续静默"本身成为异常信号)
import datetime
if datetime.date.today().weekday() == 0:
    try:
        subprocess.run(["bash", os.path.expanduser("~/.claude/session-remote/fs-reply.sh"),
                        "[美股] 周一平安报: health_check七项全过(yfinance/腾讯/pulse/通报链/git远端/git积压/哨兵心跳)。若未来某周一没收到这条=检查链本身死了。"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, timeout=30)
    except Exception:
        pass
