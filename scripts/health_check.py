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
    return age < 12, f"更新于{age:.1f}小时前"

def c_tg():
    f = os.path.expanduser("~/.claude/session-remote/tg-reply.sh")
    return os.path.exists(f) and os.access(f, os.X_OK), "存在且可执行" if os.path.exists(f) else "缺失"

def c_git_remote():
    r = subprocess.run(["git","ls-remote","origin","HEAD"], cwd=R,
                       capture_output=True, text=True, timeout=30)
    return r.returncode == 0, "远端可达" if r.returncode==0 else r.stderr[:60]

def c_git_backlog():
    r = subprocess.run(["git","rev-list","--count","origin/main..HEAD"], cwd=R,
                       capture_output=True, text=True, timeout=10)
    n = int(r.stdout.strip() or 0)
    return n < 10, f"未push commit {n}个" + ("" if n<10 else " ⛔积压")

print("═══ health_check (外部源探活) ═══")
check("yfinance", c_yf)
check("腾讯行情", c_tencent)
check("news_pulse", c_pulse)
check("telegram", c_tg)
check("git远端", c_git_remote)
check("git积压", c_git_backlog)
if fails:
    print(f"⛔ {len(fails)}项失败: {', '.join(fails)}")
    sys.exit(1)
print("✓ 全部通过")
