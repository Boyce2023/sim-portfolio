"""把判断层工作流结果(journal.jsonl)写进 agent_scores.json, 带量程校验。

⛔为什么需要(2026-10-09): agent 在"经营现金流/净利"失真(净利近零或为负)时把原始比值当分数填进
  cash_conversion(NRG=52, ALB=31.35, APD=-10), combine 照单全收, NRG 综合分 167.5 冲到第一。
  四维必须在 0 到 10, 越界的维度退回上一版分数并留痕; 越界超过 10% 视为整轮不可用, 不替换。
用法: python3 ingest_judge.py <journal.jsonl> YYYYMMDD
"""
import json, os, sys, shutil

D = os.path.dirname(os.path.abspath(__file__))
journal, tag = sys.argv[1], sys.argv[2]
DIMS = ['supply_constraint', 'cash_conversion', 'catalyst', 'bear_severity']

new = {}
for line in open(journal):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get('type') != 'result':
        continue
    v = d.get('result') or d.get('value') or d.get('output')
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            continue
    if isinstance(v, dict) and isinstance(v.get('scores'), list):
        for s in v['scores']:
            if s.get('ticker'):
                new[s['ticker']] = s

path = os.path.join(D, 'agent_scores.json')
old = json.load(open(path))
universe = [r['t'] for r in json.load(open(os.path.join(D, 'composite.json')))]

bad = []
for t, s in new.items():
    for k in DIMS:
        x = s.get(k)
        if not (isinstance(x, (int, float)) and 0 <= x <= 10):
            prev = (old.get(t) or {}).get(k)
            s.setdefault('fixes', []).append(f"{k}={x} 越界(0到10), 退回上一版 {prev}")
            s[k] = prev
            s['confidence'] = 'low'
            bad.append((t, k, x))

miss = [t for t in universe if t not in new]
print(f"新分 {len(new)} | 缺 {len(miss)} {miss[:10]} | 越界 {len(bad)}")
for b in bad:
    print("  越界:", b)
if len(new) < 0.9 * len(universe) or len(bad) > 0.1 * len(universe):
    sys.exit("⛔ 缺失或越界超过 10%, 整轮不替换")

shutil.copy(path, os.path.join(D, f'agent_scores_{tag}.json.bak'))
for t in miss:
    if t in old:
        new[t] = old[t]
json.dump(new, open(path, 'w'), ensure_ascii=False, indent=1)
print(f"写入 {len(new)} 只 → agent_scores.json (旧版备份 agent_scores_{tag}.json.bak)")
