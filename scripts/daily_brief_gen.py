#!/usr/bin/env python3
"""A股晨报block生成器 (2026-08-27 main晨报工程派单)
产出: output/astock_daily_brief.json — main每日7:30晨报直读
机械字段自动生成;"要点"字段保留session手写内容(当日已写则不覆盖)。
"""
import json, os, sys, datetime, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'output', 'astock_daily_brief.json')
today = datetime.date.today().isoformat()

# 1) 持仓概览+异动(读SSOT)
st = json.load(open(os.path.join(BASE, 'portfolio_state.json')))
a = st['accounts']['a_share']
nav = a.get('total_assets', 0)
pos_moves = []
for p in a['positions']:
    chg = p.get('change_pct', 0) or 0
    pl = (p['shares'] * p.get('current_price', 0) - p.get('cost_basis', 0)) / p.get('cost_basis', 1) * 100
    if abs(chg) >= 3 or abs(pl) >= 10:
        pos_moves.append(f"{p.get('name')}({p['ticker']}) 日{chg:+.1f}% 浮盈{pl:+.1f}%")

# 2) 今日催化剂(中报判决日历: watchlist的next_catalyst_date==今日/明日)
cats = []
try:
    wl = json.load(open(os.path.join(BASE, 'watchlist_config.json')))
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    for it in wl.get('cn_watchlist', []):
        d = it.get('next_catalyst_date', '')
        if d in (today, tomorrow):
            ev = it.get('next_catalyst', {})
            ev = ev.get('event', '') if isinstance(ev, dict) else str(ev)
            tag = '今日' if d == today else '明日'
            cats.append(f"[{tag}] {it.get('name')}({it.get('ticker')}): {ev[:50]}")
except Exception as e:
    cats.append(f"(催化剂读取失败: {e})")

# 3) pending信号
sigs = []
for f in sorted(glob.glob(os.path.expanduser('~/.claude/nexus/signals/pending/sig-*.json'))):
    try:
        d = json.load(open(f))
        sigs.append(f"[{d.get('priority')}] {str(d.get('title'))[:60]}")
    except Exception:
        pass

# 4) 要点: 保留当日session手写
notes = []
if os.path.exists(OUT):
    try:
        old = json.load(open(OUT))
        if old.get('date') == today:
            notes = old.get('要点', [])
    except Exception:
        pass

out = {
    'date': today,
    'generated_at': datetime.datetime.now().isoformat(timespec='seconds'),
    'NAV': round(nav), '现金pct': round(a.get('cash', 0) / nav * 100, 1) if nav else None,
    '持仓数': len(a['positions']),
    '今日催化剂': cats, '持仓异动': pos_moves, '信号': sigs, '要点': notes,
}
json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
print(f"✓ {OUT} 已更新 催化剂{len(cats)} 异动{len(pos_moves)} 信号{len(sigs)} 要点{len(notes)}")
