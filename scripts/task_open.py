#!/opt/homebrew/bin/python3
"""列出本域真正未结的任务 — ⛔2026-09-08建, 起因是我自己的临时统计逻辑制造了假的未结项。
病因: 早期行没有 id 只有中文 theme, 后期行 id 与 theme 都有但值不同,
      我用 {id或theme: row} 归并 → 同一个任务在两个key下各存一份, 旧行以中文theme活着显示未结。
      我差点为了让数字归零去写第三次补丁, 而任务其实早就关了。
判据: **有 id 的以 id 归并; 无 id 的才用 theme。** 归并后取 updated_at 最新的一条为最终态。
"""
import json,os,sys
P=os.path.expanduser('~/.claude/nexus/tasks/astock.jsonl')
OPEN={'planned','in_progress','受阻','完成待验','doing','todo','needs_buwen'}
def load():
    rows=[json.loads(l) for l in open(P) if l.strip()]
    byid, bytheme = {}, {}
    for r in rows:
        k=r.get('id')
        ts=r.get('updated_at') or r.get('ts') or ''
        if k:
            if k not in byid or ts >= (byid[k].get('updated_at') or byid[k].get('ts') or ''):
                byid[k]=r
        else:
            t=r.get('theme')
            if t and (t not in bytheme or ts >= (bytheme[t].get('updated_at') or bytheme[t].get('ts') or '')):
                bytheme[t]=r
    # 无id的theme若已被某个有id的行"认领"(该行theme相同), 视为同一任务
    claimed={r.get('theme') for r in byid.values() if r.get('theme')}
    merged=list(byid.values())+[r for t,r in bytheme.items() if t not in claimed]
    return merged
if __name__=='__main__':
    m=load()
    op=[r for r in m if r.get('status') in OPEN]
    print(f"astock 未结任务: {len(op)} 条 (总任务 {len(m)})")
    for r in sorted(op,key=lambda x:(x.get('updated_at') or x.get('ts') or '')):
        print(f"  [{r.get('status'):<8}] {r.get('id') or r.get('theme')}  更新{(r.get('updated_at') or r.get('ts') or '?')[:16]}")
        print(f"       {(r.get('theme') or '')[:40]}: {(r.get('detail') or '')[:110]}")
