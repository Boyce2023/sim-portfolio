#!/usr/bin/env python3
"""独立复核: 持仓数上限(N-cap)回测的因果归因
问题: 重建10报告N=4收益+8.25% vs N=16实际-2.73%, 但脚本已丢失无法复现。
怀疑: N-cap下"先到先得"(先建仓的留下)等价于"偏好持有更久的票",
      而本组合5月建仓cohort回报+4.3%、7-8月为负 → 可能是持有期偏差而非集中度效应。
测法: 同一N下换四种淘汰规则 + 随机淘汰的分布, 看N=4的优势是否稳健。
"""
import json, sqlite3, random, statistics
from collections import OrderedDict

ST = json.load(open('/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json'))
TL = [t for t in ST['trade_log'] if t.get('account') == 'a_share']
TL.sort(key=lambda t: (t['timestamp'], t['id']))
INIT = 10_000_000
END = '2026-08-13'

con = sqlite3.connect('/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kline_cache.db')
def px(code, date):
    r = con.execute("select close from daily_kline where code=? and date<=? order by date desc limit 1",
                    (code, date)).fetchone()
    return r[0] if r else None

def run(N, policy, seed=0):
    rnd = random.Random(seed)
    cash = INIT
    pos = OrderedDict()          # ticker -> {'sh':shares,'entry':date,'last':price}
    rejects = swaps = 0
    for t in TL:
        tk, d, p, sh = t['ticker'], t['date'], t['price'], t['shares']
        if t['action'] == 'buy':
            if tk in pos:                      # 加仓: 已在池内, 不占新名额
                cash -= p * sh; pos[tk]['sh'] += sh; pos[tk]['last'] = p
                continue
            if len(pos) < N:
                cash -= p * sh; pos[tk] = {'sh': sh, 'entry': d, 'last': p}
                continue
            # 已满员
            if policy == 'fcfs':               # 先到先得: 拒绝新票(重建10的实际效果)
                rejects += 1; continue
            if policy == 'lifo':   victim = max(pos, key=lambda k: pos[k]['entry'])
            elif policy == 'fifo': victim = min(pos, key=lambda k: pos[k]['entry'])
            else:                  victim = rnd.choice(list(pos))     # random
            vp = px(victim, d) or pos[victim]['last']
            cash += vp * pos[victim]['sh']; del pos[victim]; swaps += 1
            cash -= p * sh; pos[tk] = {'sh': sh, 'entry': d, 'last': p}
        else:                                   # sell
            if tk not in pos: continue
            s = min(pos[tk]['sh'], sh)
            cash += p * s; pos[tk]['sh'] -= s; pos[tk]['last'] = p
            if pos[tk]['sh'] <= 0: del pos[tk]
    mv = sum((px(k, END) or v['last']) * v['sh'] for k, v in pos.items())
    return (cash + mv) / INIT - 1, rejects, swaps, len(pos)

print("=" * 78)
print("复核1: 同一N下, 换淘汰规则 → 结论是否稳健")
print("=" * 78)
print(f"{'N':>3} | {'先到先得(重建10)':>16} | {'淘汰最新(≈先到)':>16} | {'淘汰最早(留新)':>15} | {'随机200次均值':>14}")
print("-" * 78)
rows = {}
for N in (4, 6, 8, 10, 12, 16):
    a = run(N, 'fcfs')[0]
    b = run(N, 'lifo')[0]
    c = run(N, 'fifo')[0]
    rs = [run(N, 'random', s)[0] for s in range(200)]
    rows[N] = (a, b, c, rs)
    print(f"{N:>3} | {a:>15.2%} | {b:>15.2%} | {c:>14.2%} | "
          f"{statistics.mean(rs):>13.2%}")

print()
print("=" * 78)
print("复核2: N=4的+8%在随机淘汰分布中的位置(判决artifact的关键)")
print("=" * 78)
for N in (4, 6, 8):
    a, _, _, rs = rows[N]
    rs_s = sorted(rs)
    pct = sum(1 for x in rs_s if x < a) / len(rs_s)
    print(f"N={N}: 先到先得={a:.2%} | 随机分布 p5={rs_s[9]:.2%} 中位={statistics.median(rs_s):.2%} "
          f"p95={rs_s[189]:.2%} | 先到先得处于第{pct:.0%}分位")

print()
print("=" * 78)
print("复核3: 建仓月cohort回报(检验'先到先得=偏好早期票'是否等于偏好赢家)")
print("=" * 78)
from collections import defaultdict
coh = defaultdict(list)
buys = defaultdict(list)
for t in TL:
    if t['action'] == 'buy': buys[t['ticker']].append(t)
for tk, bs in buys.items():
    first = min(bs, key=lambda x: x['date'])
    cost = sum(b['price'] * b['shares'] for b in bs); tot = sum(b['shares'] for b in bs)
    sells = [t for t in TL if t['ticker'] == tk and t['action'] == 'sell']
    proceeds = sum(s['price'] * s['shares'] for s in sells); sold = sum(s['shares'] for s in sells)
    rem = tot - sold
    endp = px(tk, END) or first['price']
    ret = (proceeds + rem * endp) / cost - 1 if cost else 0
    coh[first['date'][:7]].append((tk, first['name'], ret))
for m in sorted(coh):
    v = [r for _, _, r in coh[m]]
    print(f"{m}: {len(v):>2}只  均回报 {statistics.mean(v):>+7.2%}  中位 {statistics.median(v):>+7.2%}")
