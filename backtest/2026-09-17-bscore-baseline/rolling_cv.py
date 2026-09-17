#!/usr/bin/env python3
"""#48 合规路径②: 滚动交叉验证 — 每折的收缩系数只由该折之前的数据决定
⛔为什么不选路径①(先验系数0.5): 那个0.5仍然是我拍的。滚动的系数由时间顺序决定, 无人为设定。
⛔amount与fmv共线, 必须一起定 -> 三种配置并排评估, 不分两次改。
"""
import json, statistics, sys
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts')
import b_score as B

rows = sorted(json.load(open('raw_with_fmv.json')), key=lambda r: r['date'])
days = sorted({r['date'] for r in rows})
print(f"样本 {len(rows):,} 条 / {len(days)} 个交易日 {days[0]} ~ {days[-1]}\n")

def score(r, scale, seven):
    kw = dict(turn=r['turn'], amount=r['amount'], streak=r['streak'], gain20=r['gain20'],
              board=r['board'], is_st=r['isST'], fmv=r.get('fmv') if seven else None)
    s, det = B.score(strict=False, **kw)
    if s is None: return None
    d = det.get('amount')
    return s - d + d*scale if d is not None else s

def top_mean(data, scale, seven):
    sr = sorted([(score(r,scale,seven), r) for r in data], key=lambda x: x[0])
    q = len(sr)//5
    return statistics.mean(r['gap1'] for _, r in sr[4*q:])

def fit_scale(train, seven):
    """只用训练段搜最优 scale —— 该折之后的数据不参与"""
    best, bs = None, -9e9
    for s10 in range(0, 13):
        m = top_mean(train, s10/10, seven)
        if m > bs: bs, best = m, s10/10
    return best

# 5 折前向滚动: 训练段 = 该折之前全部, 测试段 = 当折
K = 5
fold = len(days)//K
print(f"{'折':>3}{'训练期':>26}{'测试期':>26}{'七维scale':>10}{'七维现状':>10}{'七维收缩':>10}{'六维收缩':>10}")
res = {'seven_now': [], 'seven_shrink': [], 'six_shrink': []}
for k in range(1, K):
    tr_days = days[:fold*k]; te_days = days[fold*k: fold*(k+1) if k < K-1 else len(days)]
    tr = [r for r in rows if r['date'] in set(tr_days)]
    te = [r for r in rows if r['date'] in set(te_days)]
    s7 = fit_scale(tr, True); s6 = fit_scale(tr, False)
    now  = top_mean(te, 1.0, True)
    shr7 = top_mean(te, s7, True)
    shr6 = top_mean(te, s6, False)
    res['seven_now'].append(now); res['seven_shrink'].append(shr7); res['six_shrink'].append(shr6)
    print(f"{k:>3}{tr_days[0][5:]+'~'+tr_days[-1][5:]:>26}{te_days[0][5:]+'~'+te_days[-1][5:]:>26}"
          f"{s7:>10.1f}{now:>10.3f}{shr7:>10.3f}{shr6:>10.3f}")

print(f"\n{'配置':<28}{'各折均值':>10}{'对现状增量':>12}{'折中获胜次数':>14}")
base = statistics.mean(res['seven_now'])
for k, lab in (('seven_now','七维 维持现状(scale=1.0)'),
               ('seven_shrink','七维 + amount滚动收缩'),
               ('six_shrink','六维(删fmv) + amount滚动收缩')):
    m = statistics.mean(res[k])
    wins = sum(1 for i in range(len(res[k])) if res[k][i] >= max(res['seven_now'][i], res['seven_shrink'][i], res['six_shrink'][i]) - 1e-9)
    print(f"{lab:<28}{m:>10.3f}{m-base:>+12.3f}{wins:>10}/{len(res[k])}")

print("\n⛔判读: 增量为正且多数折获胜 -> 该配置可上线; 折间摇摆 -> 说明系数不稳, 维持现状")
print("⛔本结果的每折系数只由该折之前的数据决定, 无未来信息泄漏; 可作为上线依据。")
