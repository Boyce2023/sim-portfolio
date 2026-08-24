#!/usr/bin/env python3
"""N-cap (持仓数上限) 回测复核 v2 — 2026-08-24
延续 sim-portfolio/scripts/ncap_verify.py 的方法论, 三处扩展:
  ① 窗口延伸: END从2026-08-13推到2026-08-24, 交易笔数192->220 (含08-14~08-24新增28笔)
  ② 新增两种淘汰规则对照: worst_gain(淘汰浮盈最低者) / worst_fund(淘汰基本面增速最低者)
  ③ 独立做一次"增速 vs 窗口收益"横截面相关性检验, 直接回答因果问题而不只看N-cap replay

⛔数据源: A股不用yfinance(D12铁律)。价格=本地kline_cache.db(baostock源,05-18~08-21已缓存,
08-24当日价用trade_log里的成交价兜底)。基本面增速=akshare stock_yjbb_em(东财业绩报表,
H1 2026为主/Q1 2026对40只未披露中报的票做fallback, 已在fundamentals_*.csv落盘)。

结论只对2026-06-24~08-24这一段单一regime负责, 外推需谨慎(见脚本末尾disclaimer)。
"""
import json, sqlite3, random, statistics, csv
from collections import OrderedDict, defaultdict

BASE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio'
ST = json.load(open(f'{BASE}/portfolio_state.json'))
TL = [t for t in ST['trade_log'] if t.get('account') == 'a_share']
TL.sort(key=lambda t: (t['timestamp'], t['id']))
INIT = 10_000_000
END = '2026-08-24'          # 延伸后的窗口终点(市场当日未收盘,px()会自动回退到08-21最后收盘价)
WIN_START = '2026-06-24'    # 报告约定的2个月窗口起点(N-cap replay仍吃全部220笔以保持持仓延续性)

con = sqlite3.connect(f'{BASE}/data/kline_cache.db')
def px(code, date):
    r = con.execute("select close from daily_kline where code=? and date<=? order by date desc limit 1",
                    (code, date)).fetchone()
    return r[0] if r else None

# ---------- 基本面增速表: H1 2026为主, Q1 2026 fallback (40只中报未披露的票) ----------
fund_map = {}   # code -> {'np_g':净利润同比增长%, 'rev_g':营收同比增长%, 'period':'H1'/'Q1'}
def load_fund_csv(path, period):
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            code = row['股票代码'].zfill(6)
            if code in fund_map:
                continue  # H1优先, 已有则不覆盖
            try:
                np_g = float(row['净利润-同比增长'])
                rev_g = float(row['营业总收入-同比增长'])
            except (ValueError, KeyError):
                continue
            fund_map[code] = {'np_g': np_g, 'rev_g': rev_g, 'period': period, 'name': row['股票简称']}

load_fund_csv(f'{BASE}/backtest/2026-08-24/fundamentals_h1_2026.csv', 'H1')
load_fund_csv(f'{BASE}/backtest/2026-08-24/fundamentals_q1_2026.csv', 'Q1')

tickers_all = sorted(set(t['ticker'] for t in TL))
missing_fund = [tk for tk in tickers_all if tk not in fund_map]
_h1n = sum(1 for tk in tickers_all if tk in fund_map and fund_map[tk]['period'] == 'H1')
_q1n = sum(1 for tk in tickers_all if tk in fund_map and fund_map[tk]['period'] == 'Q1')
print(f"基本面覆盖(仅统计76只交易过的票, 下方H1/Q1计数不含fundamentals_q1_2026.csv里未交易过的全市场票): "
      f"{len(tickers_all)-len(missing_fund)}/{len(tickers_all)} 只 "
      f"(H1 2026中报={_h1n}, Q1 2026一季报fallback={_q1n}, 缺失={missing_fund})")

# ---------- N-cap replay核心 ----------
def run(N, policy, seed=0):
    rnd = random.Random(seed)
    cash = INIT
    pos = OrderedDict()   # ticker -> {'sh':shares,'entry':date,'last':price,'cost':avg_cost_per_share}
    rejects = swaps = 0
    for t in TL:
        tk, d, p, sh = t['ticker'], t['date'], t['price'], t['shares']
        if t['action'] == 'buy':
            if tk in pos:
                old = pos[tk]
                new_sh = old['sh'] + sh
                old['cost'] = (old['cost'] * old['sh'] + p * sh) / new_sh
                old['sh'] = new_sh
                old['last'] = p
                cash -= p * sh
                continue
            if len(pos) < N:
                cash -= p * sh
                pos[tk] = {'sh': sh, 'entry': d, 'last': p, 'cost': p}
                continue
            # 已满员, 按policy选淘汰对象
            if policy == 'fcfs':
                rejects += 1
                continue
            if policy == 'lifo':
                victim = max(pos, key=lambda k: pos[k]['entry'])
            elif policy == 'fifo':
                victim = min(pos, key=lambda k: pos[k]['entry'])
            elif policy == 'worst_gain':
                def gain(k):
                    cp = px(k, d) or pos[k]['last']
                    return cp / pos[k]['cost'] - 1
                victim = min(pos, key=gain)
            elif policy == 'worst_fund':
                # 缺基本面数据的票视为增速=-999(优先淘汰), 已知76只全覆盖不会触发
                victim = min(pos, key=lambda k: fund_map.get(k, {}).get('np_g', -999))
            else:  # random
                victim = rnd.choice(list(pos))
            vp = px(victim, d) or pos[victim]['last']
            cash += vp * pos[victim]['sh']
            del pos[victim]
            swaps += 1
            cash -= p * sh
            pos[tk] = {'sh': sh, 'entry': d, 'last': p, 'cost': p}
        else:  # sell
            if tk not in pos:
                continue
            s = min(pos[tk]['sh'], sh)
            cash += p * s
            pos[tk]['sh'] -= s
            pos[tk]['last'] = p
            if pos[tk]['sh'] <= 0:
                del pos[tk]
    mv = sum((px(k, END) or v['last']) * v['sh'] for k, v in pos.items())
    return (cash + mv) / INIT - 1, rejects, swaps, len(pos)


NS = (4, 6, 8, 10, 12, 16)
RANDOM_DRAWS = 200

print("=" * 100)
print(f"部分1: 延伸窗口后(220笔交易, END={END}) N-cap replay, 5种淘汰规则")
print("=" * 100)
print(f"{'N':>3} | {'fcfs拒绝新票':>11} | {'lifo淘汰新仓':>11} | {'fifo淘汰老仓':>11} | "
      f"{'随机200次均值':>12} | {'浮盈最低淘汰':>11} | {'增速最低淘汰':>11}")
print("-" * 100)
rows = {}
for N in NS:
    a = run(N, 'fcfs')[0]
    b = run(N, 'lifo')[0]
    c = run(N, 'fifo')[0]
    rs = [run(N, 'random', s)[0] for s in range(RANDOM_DRAWS)]
    g = run(N, 'worst_gain')[0]
    f = run(N, 'worst_fund')[0]
    rows[N] = dict(fcfs=a, lifo=b, fifo=c, random=rs, worst_gain=g, worst_fund=f)
    print(f"{N:>3} | {a:>10.2%} | {b:>10.2%} | {c:>10.2%} | "
          f"{statistics.mean(rs):>11.2%} | {g:>10.2%} | {f:>10.2%}")

print()
print("=" * 100)
print("部分2: worst_gain / worst_fund 两个确定性策略, 在同N随机200次分布中的分位 + 完整分布统计")
print("=" * 100)
print(f"{'N':>3} | {'随机n':>5} | {'随机均值':>8} | {'随机中位':>8} | {'随机p5':>8} | {'随机p95':>8} | "
      f"{'浮盈淘汰':>8} | {'浮盈分位':>8} | {'增速淘汰':>8} | {'增速分位':>8}")
print("-" * 100)
summary_rows = []
for N in NS:
    r = rows[N]
    rs_s = sorted(r['random'])
    n = len(rs_s)
    mean_ = statistics.mean(rs_s)
    med_ = statistics.median(rs_s)
    p5 = rs_s[int(n * 0.05)]
    p95 = rs_s[min(n - 1, int(n * 0.95))]
    pct_gain = sum(1 for x in rs_s if x < r['worst_gain']) / n
    pct_fund = sum(1 for x in rs_s if x < r['worst_fund']) / n
    print(f"{N:>3} | {n:>5} | {mean_:>7.2%} | {med_:>7.2%} | {p5:>7.2%} | {p95:>7.2%} | "
          f"{r['worst_gain']:>7.2%} | 第{pct_gain:>4.0%}位 | {r['worst_fund']:>7.2%} | 第{pct_fund:>4.0%}位")
    summary_rows.append(dict(N=N, random_mean=mean_, random_median=med_, random_p5=p5, random_p95=p95,
                              worst_gain=r['worst_gain'], worst_gain_pct=pct_gain,
                              worst_fund=r['worst_fund'], worst_fund_pct=pct_fund,
                              fcfs=r['fcfs'], lifo=r['lifo'], fifo=r['fifo']))

# 部分2b: 增速策略 vs 浮盈策略 直接对比 (哪个更常win, 跨N汇总)
wf_wins = sum(1 for r in summary_rows if r['worst_fund'] > r['worst_gain'])
diffs = [r['worst_fund'] - r['worst_gain'] for r in summary_rows]
print()
print(f"[跨{len(NS)}个N值] 增速淘汰 vs 浮盈淘汰: 增速赢{wf_wins}/{len(NS)}次 | "
      f"差值均值={statistics.mean(diffs):+.2%} | 中位={statistics.median(diffs):+.2%} | "
      f"最大差={max(diffs):+.2%} | 最小差={min(diffs):+.2%}")
print("⚠️样本量提示: 上表'增速赢N次'的N只有6个(N=4,6,8,10,12,16), 属方向性提示不构成统计显著结论。")

print()
print("=" * 100)
print("部分3(独立检验, 反例专用): 基本面增速 vs 窗口收益(06-24~08-24) 横截面相关性")
print("样本=76只交易过的股票各自的区间收益率, 与其净利润/营收同比增速的相关系数")
print("=" * 100)

def window_return(code):
    p0 = px(code, WIN_START)
    p1 = px(code, END)
    if p0 is None or p1 is None or p0 == 0:
        return None
    return p1 / p0 - 1

xy_np, xy_rev = [], []
missing_ret = []
for tk in tickers_all:
    ret = window_return(tk)
    if ret is None:
        missing_ret.append(tk)
        continue
    fd = fund_map.get(tk)
    if fd is None:
        continue
    xy_np.append((fd['np_g'], ret, tk, fd.get('name', ''), fd['period']))
    xy_rev.append((fd['rev_g'], ret, tk, fd.get('name', ''), fd['period']))

def pearson(pairs):
    xs = [a for a, b, *_ in pairs]
    ys = [b for a, b, *_ in pairs]
    n = len(xs)
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys)) ** 0.5
    return cov / (sx * sy) if sx > 0 and sy > 0 else float('nan')

def spearman(pairs):
    xs = [a for a, b, *_ in pairs]
    ys = [b for a, b, *_ in pairs]
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0] * len(v)
        for rank_i, idx in enumerate(order):
            r[idx] = rank_i
        return r
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1 - 6 * d2 / (n * (n ** 2 - 1)) if n > 1 else float('nan')

r_np_pearson = pearson(xy_np)
r_np_spearman = spearman(xy_np)
r_rev_pearson = pearson(xy_rev)
r_rev_spearman = spearman(xy_rev)

def t_and_p(r, n):
    import math
    t = r * math.sqrt(n - 2) / math.sqrt(1 - r ** 2)
    try:
        from scipy import stats
        p = 2 * (1 - stats.t.cdf(abs(t), df=n - 2))
    except ImportError:
        p = None
    return t, p

n_np = len(xy_np)
t_np, p_np = t_and_p(r_np_pearson, n_np)
t_rev, p_rev = t_and_p(r_rev_pearson, len(xy_rev))

print(f"样本量 n={len(xy_np)} (缺价格数据被剔除: {missing_ret}, 缺基本面数据: {[tk for tk in tickers_all if tk not in fund_map]})")
print(f"净利润同比增速 vs 区间收益率: Pearson r={r_np_pearson:+.3f} | Spearman rho={r_np_spearman:+.3f} | "
      f"t={t_np:+.3f}(df={n_np-2}) | p={p_np:.3f}" + ("  ← 不显著,与0无法区分" if p_np is not None and p_np > 0.05 else ""))
print(f"营收同比增速   vs 区间收益率: Pearson r={r_rev_pearson:+.3f} | Spearman rho={r_rev_spearman:+.3f} | "
      f"t={t_rev:+.3f}(df={len(xy_rev)-2}) | p={p_rev:.3f}" + ("  ← 不显著,与0无法区分" if p_rev is not None and p_rev > 0.05 else ""))

# winsorize净利润增速(掐掉<p5/>p95的极端值)重算一次, 检验是否是被爆炸值(2917%/-917%)带偏
vals = sorted(a for a, *_ in xy_np)
n = len(vals)
lo, hi = vals[int(n * 0.05)], vals[int(n * 0.95)]
xy_np_wins = [(min(max(a, lo), hi), b, c, d, e) for a, b, c, d, e in xy_np]
r_np_wins_pearson = pearson(xy_np_wins)
print(f"净利润增速winsorize(p5={lo:.1f}%,p95={hi:.1f}%)后: Pearson r={r_np_wins_pearson:+.3f} "
      f"(对照未winsorize={r_np_pearson:+.3f}, 检验是否被极端值带偏)")

print()
top10 = sorted(xy_np, key=lambda x: -x[0])[:10]
bot10 = sorted(xy_np, key=lambda x: x[0])[:10]
print("增速最高10只(净利润同比) — 代码/名称/period/增速/区间收益:")
for a, b, tk, name, per in top10:
    print(f"  {tk} {name:6s} [{per}] 增速{a:>+9.1f}%  区间收益{b:>+7.2%}")
print("增速最低10只(净利润同比) — 代码/名称/period/增速/区间收益:")
for a, b, tk, name, per in bot10:
    print(f"  {tk} {name:6s} [{per}] 增速{a:>+9.1f}%  区间收益{b:>+7.2%}")
mean_top10 = statistics.mean(b for a, b, *_ in top10)
mean_bot10 = statistics.mean(b for a, b, *_ in bot10)
print(f"\n增速最高10只 平均区间收益={mean_top10:+.2%} | 增速最低10只 平均区间收益={mean_bot10:+.2%} | "
      f"差={mean_top10-mean_bot10:+.2%}")

print()
print("=" * 100)
print("最终结论(见返回文本首行), 数据表见上; 脚本+CSV已落盘 backtest/2026-08-24/")
print("=" * 100)
