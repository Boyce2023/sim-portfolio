#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股宏观与实物资产哨兵 daemon (2026-09-02 建, 2026-10-29 慢账纯化与 Antigravity 原生唤醒版)

职责:
1. launchd KeepAlive 常驻监控美元指数(DX-Y.NYB)、黄金期货(GC=F)、金矿(GDX/RGLD/NEM对照)与10Y美债(^TNX)。
2. 2026-10-29 慢账对齐: 全面清除旧版自动减仓与机械止损文案(如预案B/自动砍仓至12%),
   所有阈值越界均定义为「触发 RGLD/FCX 基本面慢账复核提示, 非自动减仓指令」。
3. 唤醒收口至 Antigravity 原生链路: 需唤醒 us 会话时直读 ~/.claude/session-registry/us.json
   调用 agy agentapi send-message 投递并记入 _consumed/us.jsonl; 仅当原生投递失败时回退写入
   us.jsonl 交由 inbox-watchdog 重试兜底。
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import warnings

warnings.filterwarnings('ignore')

R = os.path.expanduser('~/claude-projects/sim-portfolio')
INBOX = os.path.expanduser('~/.claude/session-inbox/us.jsonl')
CONSUMED = os.path.expanduser('~/.claude/session-inbox/_consumed/us.jsonl')
DIGEST = os.path.expanduser('~/.claude/session-inbox/_digest/us.jsonl')
REG_US = os.path.expanduser('~/.claude/session-registry/us.json')
AGY_BIN = '/Users/huaichuaibeimeng/.gemini/bin/agy'
FS = os.path.expanduser('~/.claude/session-remote/fs-reply.sh')
HB = f'{R}/.sentinel_heartbeat'
STATE = f'{R}/.sentinel_daemon_state.json'
# 注: RGLD 为当前美股慢账持仓, NEM 保留作上游金矿对照基准以观测权益金模式相对矿山股的抗跌性
NEED = ['DX-Y.NYB', 'GDX', 'GC=F', '^TNX', 'NEM', 'RGLD']

DXY_FILE = R + '/.dxy_count.json'
DXY_LINE = 99.60
DXY_RULE_DESC = '美元哨兵(慢账复核): 连续3个交易日收盘站上99.60 且 5/10/30日窗口同向 → 触发RGLD/FCX慢账基本面复核(非自动减仓)'


def ny_now():
    import zoneinfo
    return datetime.datetime.now(zoneinfo.ZoneInfo('America/New_York'))


def market_open(t):
    return t.weekday() < 5 and (9, 30) <= (t.hour, t.minute) <= (16, 15)


def _wake_us_antigravity(rec: dict) -> bool:
    """优先走 Antigravity 原生 send-message 唤醒 us 会话, 成功返回 True。"""
    if not (os.path.exists(REG_US) and os.path.exists(AGY_BIN)):
        return False
    try:
        with open(REG_US, encoding='utf-8') as f:
            conv_id = json.load(f).get('conversation_id')
        if not conv_id:
            return False
        wake_text = f"【美股哨兵慢账复核提示 · {rec['ts']}】\n{rec['text']}"
        res = subprocess.run(
            [AGY_BIN, 'agentapi', 'send-message', conv_id, wake_text],
            capture_output=True,
            text=True,
            timeout=25,
        )
        return res.returncode == 0
    except Exception:
        return False


def emit(msg, level='info'):
    rec = {
        'ts': datetime.datetime.now().isoformat(timespec='seconds'),
        'from': 'us-sentinel-daemon',
        'kind': 'alert',
        'level': level,
        'text': msg,
    }
    actionable = level == 'crit' and '美元哨兵条件①' not in msg
    if actionable:
        if _wake_us_antigravity(rec):
            rec['delivered_via'] = 'agy_agentapi'
            os.makedirs(os.path.dirname(CONSUMED), exist_ok=True)
            with open(CONSUMED, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        else:
            os.makedirs(os.path.dirname(INBOX), exist_ok=True)
            with open(INBOX, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    else:
        os.makedirs(os.path.dirname(DIGEST), exist_ok=True)
        with open(DIGEST, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    if level in ('warn', 'crit'):
        try:
            r = subprocess.run(
                ['bash', FS, f'[美股哨兵] {msg}'],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if r.returncode != 0:
                _log_alert_failure(f"fs-reply退出码{r.returncode}: {(r.stderr or r.stdout)[:160]}", msg)
        except subprocess.TimeoutExpired:
            _log_alert_failure("fs-reply超时20秒未返回", msg)
        except Exception as e:
            _log_alert_failure(f"fs-reply调用异常 {type(e).__name__}: {str(e)[:120]}", msg)


def _log_alert_failure(why, original_msg):
    """飞书未送达时写本地失败日志。"""
    try:
        with open(f'{R}/.sentinel_alert_failures.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': datetime.datetime.now().isoformat(timespec='seconds'),
                'why': why,
                'undelivered_alert': original_msg[:300],
            }, ensure_ascii=False) + '\n')
    except Exception:
        pass


def read_dxy_count():
    """返回 (count, note)。count 为 None 表示不可信, 调用方必须报 STALE。"""
    try:
        with open(DXY_FILE, encoding='utf-8') as f:
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
        return None, f'计数已 {gap} 天未更新(最后 {last_date}), 可能无人维护'
    return j['count'], '最后更新 ' + last_date


def reconcile_dxy_days(hist):
    """用数据源当前真实日线对账最近10天记录, 剔除结算后消失的幽灵bar。"""
    return {d.date().isoformat(): round(float(v), 3) for d, v in hist.items()}


def update_dxy_count(close_px, close_date, hist=None):
    """收盘后推进美元站上 99.60 连续交易日计数(幂等)。"""
    try:
        with open(DXY_FILE, encoding='utf-8') as f:
            j = json.load(f)
    except Exception:
        j = {'rule': DXY_RULE_DESC, 'count': 0, 'days': []}
    j['rule'] = DXY_RULE_DESC
    days = j.setdefault('days', [])

    if hist is not None and len(hist):
        truth = reconcile_dxy_days(hist)
        oldest = min(truth)
        ghosts = [d for d in days if d.get('date') >= oldest and d.get('date') not in truth]
        if ghosts:
            j.setdefault('reconciled', []).append({
                'at': datetime.datetime.now().isoformat(timespec='seconds'),
                'removed': [{'date': g['date'], 'close': g.get('close')} for g in ghosts],
                'why': '数据源当前日线不含该日, 判为收盘后被结算掉的幽灵bar',
            })
            days = [d for d in days if d not in ghosts]

    if days and days[-1].get('date') == close_date:
        j['days'] = days[-10:]
        _write_dxy(j)
        return j['count']
    above = close_px >= DXY_LINE
    j['count'] = (j.get('count', 0) + 1) if above else 0
    days.append({'date': close_date, 'close': round(close_px, 3), 'above': above})
    j['days'] = days[-10:]
    _write_dxy(j)
    return j['count']


def _write_dxy(j):
    j['auto_maintained_since'] = '2026-09-07'
    tmp = DXY_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(j, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DXY_FILE)


def check():
    import yfinance as yf
    d = {}
    wins = {}
    h3 = {}
    dates = {}
    for t in NEED:
        try:
            h = yf.Ticker(t).history(period='3mo')['Close'].dropna()
            if len(h) >= 4:
                dates[t] = h.index[-1].date()
                d[t] = (float(h.iloc[-1]), (float(h.iloc[-1]) / float(h.iloc[-2]) - 1) * 100)
                h3[t] = (float(h.iloc[-1]) / float(h.iloc[-4]) - 1) * 100
                if t == 'DX-Y.NYB' and len(h) >= 31:
                    wins = {k: (float(h.iloc[-1]) / float(h.iloc[-1 - k]) - 1) * 100 for k in (5, 10, 30)}
        except Exception:
            pass
    miss = [t for t in NEED if t not in d]
    if miss:
        return 'STALE', f"哨兵取不到数: {','.join(miss)}, 当前读数不可用"

    stale_dates = {k: v for k, v in dates.items() if v != ny_now().date()}
    if stale_dates:
        shown = ', '.join(f"{k}@{v}" for k, v in list(stale_dates.items())[:3])
        return 'HOLIDAY', f"数据日期非美东今日({shown}), 属休市或日线未落盘, 不触发复核告警"

    dxy, dxc = d['DX-Y.NYB']
    gx, gxc = d['GDX']
    au, auc = d['GC=F']
    tn, _ = d['^TNX']
    cnt, cnt_note = read_dxy_count()
    if cnt is None:
        return 'STALE', f'美元计数器不可用({cnt_note}), 请核查 .dxy_count.json'

    m = []
    lvl = 'info'
    if dxy >= 99.60:
        agree = bool(wins) and all(v > 0 for v in wins.values())
        w = " ".join(f"{k}日{v:+.2f}%" for k, v in wins.items())
        m.append(
            f"美元{dxy:.2f}在线上|计数{cnt}天|{w}→{'同向' if agree else '不同向'}"
            "|慢账观察:需收盘确认且仅触发基本面复核,非自动减仓"
        )
        lvl = 'warn'
    elif dxy >= 99.40:
        m.append(f"美元{dxy:.2f}逼近99.60|计数{cnt}天")
    elif cnt > 0:
        m.append(f"美元{dxy:.2f}跌回线下→若收盘确认计数({cnt}天)归零")
        lvl = 'warn'

    c1 = (d['NEM'][1] + d['RGLD'][1]) / 2
    c3 = (h3['NEM'] + h3['RGLD']) / 2
    if c1 <= -3 or c3 <= -6:
        m.append(
            f"金矿对照簇(RGLD/NEM) 单日{c1:+.2f}%/三日{c3:+.2f}% 越波动观察线"
            "→收盘后复核RGLD权益金基本面与相对GDX抗跌性(慢账不自动减仓)"
        )
        lvl = 'crit'
    if gxc <= -4:
        m.append(f"GDX单日{gxc:+.2f}%")
        lvl = max(lvl, 'warn', key=['info', 'warn', 'crit'].index)
    if auc <= -2:
        m.append(f"黄金单日{auc:+.2f}%")
    if tn >= 4.75:
        m.append(f"10Y美债{tn:.3f}%上破4.75%")

    if not m:
        return (
            'OK',
            f"美元{dxy:.2f}({dxc:+.2f}%) 计数{cnt}天 金矿簇1日{c1:+.2f}%/3日{c3:+.2f}% "
            f"GDX{gxc:+.2f}% 金{auc:+.2f}% 10Y{tn:.2f}%",
        )
    return lvl.upper(), " | ".join(m)


def post_close_maintain(t):
    """收盘后幂等更新美元收盘计数。"""
    if t.weekday() >= 5 or (t.hour, t.minute) < (16, 20):
        return
    try:
        import yfinance as yf
        h = yf.Ticker('DX-Y.NYB').history(period='5d')['Close'].dropna()
        if h.empty:
            return
        d = h.index[-1].date()
        if d.weekday() >= 5 or d != t.date():
            return
        cnt = update_dxy_count(float(h.iloc[-1]), d.isoformat(), hist=h)
        _af = R + '/.dxy_alerted.json'
        try:
            with open(_af, encoding='utf-8') as f:
                _last = json.load(f).get('cnt')
        except Exception:
            _last = None
        if cnt >= 3 and cnt != _last:
            with open(_af, 'w', encoding='utf-8') as f:
                json.dump({'cnt': cnt, 'date': d.isoformat()}, f)
            emit(
                f"⛔美元哨兵条件①达成: 美元连续{cnt}个收盘站上{DXY_LINE} "
                f"(今日收{float(h.iloc[-1]):.3f}), 请核对5/10/30日窗口并复核RGLD/FCX基本面(慢账不自动卖)",
                'crit',
            )
    except Exception as e:
        emit(f"美元计数器维护失败: {type(e).__name__}, 计数可能停更", 'warn')


def _sig(msg):
    """状态去重签名: 剥离实时数字, 仅在定性状态切换时触发通知。"""
    return re.sub(r'[-+]?\d+(\.\d+)?', '#', msg)


def main():
    ap = argparse.ArgumentParser(description='美股宏观与实物资产哨兵 daemon')
    ap.add_argument('--check-once', action='store_true', help='仅跑一次只读 check() 打印状态, 不写文件不发告警')
    args = ap.parse_args()
    if args.check_once:
        st, msg = check()
        print(f"[{st}] {msg}")
        return 0

    prev = ''
    fails = 0
    while True:
        with open(HB, 'w', encoding='utf-8') as f:
            f.write(str(int(time.time())))
        t = ny_now()
        if not market_open(t):
            post_close_maintain(t)
            time.sleep(900)
            continue
        try:
            status, msg = check()
        except Exception as e:
            status, msg = 'STALE', f"哨兵异常: {str(e)[:80]}"
        if status == 'HOLIDAY':
            fails = 0
            if msg != prev:
                prev = msg
        elif status == 'STALE':
            fails += 1
            if fails >= 2:
                emit(f"{msg} (连续{fails}次)", 'warn')
                fails = 0
        else:
            fails = 0
            if _sig(msg) != _sig(prev):
                emit(msg, {'OK': 'info', 'WARN': 'warn', 'CRIT': 'crit'}.get(status, 'info'))
                prev = msg
        with open(STATE, 'w', encoding='utf-8') as f:
            json.dump(
                {'last': datetime.datetime.now().isoformat(timespec='seconds'), 'status': status, 'msg': msg},
                f,
                ensure_ascii=False,
            )
        time.sleep(900)


if __name__ == '__main__':
    sys.exit(main())
