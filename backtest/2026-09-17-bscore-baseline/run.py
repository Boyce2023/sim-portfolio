#!/usr/bin/env python3
"""b_score 体检: 它有没有跑赢"最笨的单变量排序"

⛔ 缘起(main 2026-09-17 判据, 由 #17 龙头识别被样本外否掉催生):
   「任何打分系统上线前必须先跑一个最笨的单变量排序当基线, 跑不赢就不该存在」。
   b_score 做过样本外验证(H1训练/H2测试, 五等分均值1.19->2.62%, 三条线单调),
   **但从未跑过最笨基线对照**。单调性只证明打分内部有序, 不证明它比不用打分更好。

⛔ 口径声明(必须随结论一起给, 否则是拿一个口径评判另一个口径):
   · 样本: backtest_raw.json 的 H2(2025-07-01起), 排除一字板(yizi=True) —— 与 b_score 训练时的排除条件一致
   · 收益: gap1 = 次日开盘价 / 当日涨停价 - 1, 这是 B 策略真实买卖点
   · **六维口径**: 底稿无 fmv(流通市值)字段, 故用 strict=False 跑六维; 实盘是七维。
     两者不可直接比较, 本报告只回答"六维打分 vs 六维里的单变量"这一个问题。
   · 分档边界: 三方共用 b_score 从 H1 拟合的同一套 TABLE 边界, 条件公平。
"""
import json, os, sys, random, statistics
sys.path.insert(0, '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts')
import b_score as B

RAW = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/backtest_raw.json'
random.seed(42)

rows = [r for r in json.load(open(RAW))
        if r.get('date', '') >= '2025-07-01' and not r.get('yizi')]
print(f"样本(H2非一字) n={len(rows):,}  {min(r['date'] for r in rows)} ~ {max(r['date'] for r in rows)}")
base_mean = statistics.mean(r['gap1'] for r in rows)
print(f"无条件基线: 均值 {base_mean:+.2f}%  胜率 {sum(1 for r in rows if r['gap1']>0)/len(rows)*100:.1f}%\n")


def stats(sub):
    if not sub:
        return None
    g = [r['gap1'] for r in sub]
    return (statistics.mean(g), sum(1 for x in g if x > 0) / len(g) * 100,
            sum(1 for x in g if x < -3) / len(g) * 100, len(g))


def quintile_report(name, keyfn, reverse=False):
    """按 keyfn 排序后五等分, 报各档。keyfn 返回 None 的样本剔除并计数。"""
    scored = [(keyfn(r), r) for r in rows]
    dropped = sum(1 for k, _ in scored if k is None)
    scored = [(k, r) for k, r in scored if k is not None]
    scored.sort(key=lambda x: x[0], reverse=reverse)
    n = len(scored)
    q = n // 5
    print(f"--- {name} (可用 {n:,}, 剔除缺失 {dropped}) ---")
    tops = []
    for i in range(5):
        seg = [r for _, r in scored[i * q:(i + 1) * q if i < 4 else n]]
        m, w, l3, cnt = stats(seg)
        tops.append(m)
        print(f"   Q{i+1} n={cnt:<5} 均值{m:+.2f}%  胜率{w:4.1f}%  亏超3%{l3:4.1f}%")
    mono = all(tops[i] <= tops[i+1] for i in range(4))
    print(f"   单调递增: {'是' if mono else '否'}   最高档-最低档 = {tops[-1]-tops[0]:+.2f}pp\n")
    return tops


def six_dim(r):
    s, _ = B.score(turn=r['turn'], amount=r['amount'], streak=r['streak'],
                   gain20=r['gain20'], board=r['board'], is_st=r['isST'],
                   fmv=None, strict=False)
    return s


def one_dim(dim):
    """只用一维的分档超额当分数 —— 最笨的单变量排序"""
    edges, deltas = B.TABLE[dim]
    def f(r):
        v = {'turn': r['turn'], 'amount': r['amount'], 'streak': r['streak'],
             'gain20': r['gain20'], 'board': r['board'], 'isST': r['isST']}[dim]
        return deltas[B._bin(v, edges)] if v is not None else None
    return f


print("=" * 64)
print("一、主角 vs 最笨基线")
print("=" * 64)
main_tops = quintile_report("六维总分 b_score", six_dim)
singles = {}
for d in ('turn', 'amount', 'streak', 'gain20'):
    singles[d] = quintile_report(f"最笨基线: 只按 {d} 单排", one_dim(d))
quintile_report("对照: 随机", lambda r: random.random())

print("=" * 64)
print("二、留一法: 去掉每一维, 看最高档均值怎么变")
print("=" * 64)
full_top = main_tops[-1]
print(f"   完整六维 最高档均值 = {full_top:+.2f}%\n")
for drop in ('turn', 'amount', 'streak', 'gain20', 'board', 'isST'):
    def f(r, _d=drop):
        kw = dict(turn=r['turn'], amount=r['amount'], streak=r['streak'],
                  gain20=r['gain20'], board=r['board'], is_st=r['isST'])
        key = {'isST': 'is_st'}.get(_d, _d)
        kw[key] = None
        s, _ = B.score(fmv=None, strict=False, **kw)
        return s
    scored = sorted([(f(r), r) for r in rows], key=lambda x: x[0])
    n = len(scored); q = n // 5
    top = statistics.mean(r['gap1'] for _, r in scored[4 * q:])
    delta = top - full_top
    flag = '⛔负贡献' if delta > 0.05 else ('  正贡献' if delta < -0.05 else '  近似无影响')
    print(f"   去掉 {drop:<7} 最高档均值 {top:+.2f}%  delta {delta:+.3f}pp  {flag}")

print("\n" + "=" * 64)
print("⛔判读口径: delta 为正 = 去掉这一维反而更好 = 该维在样本外是负贡献")
print("⛔本报告是六维口径(无fmv), 不能直接用于评判实盘的七维打分")
print("=" * 64)
