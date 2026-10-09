"""从 composite.json(当日 rebuild_mech+combine 产物)生成判断层刷新的批次输入。

⛔为什么需要: judge_batches.json 是 08-27 手工拼的, judge-refresh-inline.js 又把它连同日期 09-04 写死,
  每周五照跑等于让 agent 拿一个月前的价格与行情打分(10-09 发现)。现在每次刷新前先跑本脚本。
用法: python3 build_judge_batches.py YYYY-MM-DD M/D   → 写 judge_batches.json(旧版备份) 并打印 args 文件路径
"""
import json, os, sys, shutil, datetime

D = os.path.dirname(os.path.abspath(__file__))
today, last_close = sys.argv[1], sys.argv[2]

rows = json.load(open(os.path.join(D, 'composite.json')))
rows.sort(key=lambda r: (not r.get('held'), r['t']))   # 持仓排前


def f(v, nd=2, pct=False):
    if v is None:
        return '缺'
    return (f"{v:+.1f}%" if pct else f"{v:.{nd}f}")


def block(r):
    mc = r.get('mc')
    s = (f"{r['t']} ({r.get('name') or r['t']})\n"
         f"  行业={r.get('industry') or '缺'} | 市值={f(mc/1e9 if mc else None, 1)}B\n"
         f"  价格={f(r.get('px'))} | YTD={f(r.get('ytd'), pct=True)} | 距3月高={f(r.get('dh3'), pct=True)} | 距52周高={f(r.get('dh52'), pct=True)}\n"
         f"  TTM_EPS={f(r.get('ttm_eps'))} 前瞻EPS={f(r.get('fwd_eps'))} 前瞻PE={f(r.get('fwd_pe'))} | 实测经营现金流/净利={f(r.get('fcf_conv'))}")
    if r.get('held'):
        s += f"\n  ⭐当前持仓 权重{f(r.get('weight'), 1)}%"
    return s


batches = []
for i in range(0, len(rows), 5):
    grp = rows[i:i + 5]
    batches.append({'idx': i // 5 + 1, 'tickers': [r['t'] for r in grp],
                    'block': '\n\n'.join(block(r) for r in grp)})

out = os.path.join(D, 'judge_batches.json')
if os.path.exists(out):
    shutil.copy(out, out + f".bak-{datetime.date.today():%Y%m%d}")
json.dump(batches, open(out, 'w'), ensure_ascii=False, indent=1)
args_path = os.path.join(D, 'judge_args.json')
json.dump({'batches': batches, 'today': today, 'last_close': last_close}, open(args_path, 'w'), ensure_ascii=False)
print(f"{len(rows)} 只 → {len(batches)} 批, today={today} last_close={last_close} → {args_path}")
