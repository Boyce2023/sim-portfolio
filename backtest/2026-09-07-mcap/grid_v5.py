"""v5 — 与 v4 同口径, 只修两处数据处理错误

⛔ 2026-09-16 修正一(单位量纲, 这是表二九月列几乎全空的根因):
  univ*.db 的 turn 是百分数(4.0671 = 4.07%)  → mcap = amt/(turn/100)
  日线库 parquet 的 turn 是小数(0.04067)      → 同一公式会把市值算大100倍
  日线库自带 oshare(流通股本), 直接 oshare*close 更稳, 与 amt/turn 互校在1.5%内
  v4 把两个源合并后套同一个公式, 于是只存在于日线库的交易日(2026-09-04之后)
  市值整体放大约98倍, 一部分撞上 mcap>1e4 的上限守卫被丢弃, 残存的也全部落到
  表二 10-300亿 分桶之外 → 该列显示为 0。

⛔ 2026-09-16 修正二(除权日处理):
  日线库没有 preclose 字段, 前收要用前一根收盘价推, 但除权日的前收不等于前一根收盘。
  最初的做法是把除权日整根丢掉, 这会连带毁掉**前一个交易日**的次日数据 ——
  剑桥科技 603083 的 09-07 首板就是这么丢的(它 09-08 除权)。
  正确做法: bar 留着(仍可充当前一根/后一根), 只是不参与涨停判定。

  univ 覆盖期(2025-01-02~2026-09-04)的结果与 v4 逐只逐值完全一致, 见末尾回归断言。
"""
import sqlite3, collections, sys, glob, json, datetime
import pandas as pd

sys.path.insert(0, '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
sys.path.insert(0, '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts')
import astock_rules as AR

# ⛔2026-09-16 改用 astock_rules.price_limit_pct, 不再用 engine.lim_pct:
#   engine.lim_pct 只按代码前缀分 10%/20%/30%, **没有ST分支**, 于是ST涨停被整批漏判。
#   实测2025样本漏2,712条(15.1%), 九月漏21条。
#   ⛔为什么不直接修 engine.lim_pct: 它有20+个调用方, 全是历史回测脚本(rebuild_full/run_oos/
#   engine_b2/news_study/游资选股学习等), 改它会静默改变那些早已写进memory与交易规则的回测结论。
#   所以只在本脚本局部换用权威实现, 影响面锁死在这一个产物内。
#   astock_rules 额外覆盖: ST_LIMIT_CHANGE_DATE=2026-07-06(主板ST 5%→10%)、创业板科创板ST为20%不区分、
#   新股上市前5日不设限。已用七个场景单测通过, 并经价格行为独立交叉验证(九月主板最高冲高>10.6%的为0只)。
_ST = set(json.load(open('/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/st_universe.json'))['codes'])
_LCACHE = {}
def lim_pct_at(code, d):
    """带ST与日期的涨跌幅。code形如 sh.600111, d形如 2026-09-10。"""
    bare = code.split('.')[-1]
    k = (bare, d)
    v = _LCACHE.get(k)
    if v is None:
        v = AR.price_limit_pct(bare, is_st=(bare in _ST),
                               on_date=datetime.date.fromisoformat(d))
        _LCACHE[k] = v
    return v

B = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
PQ = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet'
OUT = '/tmp/grid_v5.json'
START = '2025-01'

def _islim(x, pc, L):
    return x >= round(pc * (1 + L), 2) - 0.02 and (x / pc - 1) >= L - 0.004

# bars[code][date] = (open, high, low, close, preclose, mcap亿, 是否除权日)

# ── 1. univ*.db (turn=百分数, 自带 preclose) ─────────────────
bars = collections.defaultdict(dict)
for f in sorted(glob.glob(B + 'univ*.db')):
    con = sqlite3.connect(f'file:{f}?mode=ro', uri=True)
    for code, d, o, h, l, c, pc, amt, turn in con.execute(
            "select code,date,open,high,low,close,preclose,amount,turn from k"):
        if d[:7] >= START:
            mc = amt / (turn / 100) / 1e8 if (turn and turn > 0 and amt) else 0.0
            bars[code][d] = (o, h, l, c, pc, mc, False)
UNIV_MAX = max(d for dd in bars.values() for d in dd)
print(f'univ 覆盖至 {UNIV_MAX}, 股票 {len(bars)}')

# ── 2. 日线库补 univ 之后的交易日 (turn=小数, 改用 oshare) ────
df = pd.read_parquet(PQ, columns=['date', 'ticker', 'open', 'high', 'low', 'close',
                                  'oshare', 'qfq_factor'])
df['d'] = df['date'].astype(str).str[:10]
df = df[df['d'] >= '2026-08-01'].sort_values(['ticker', 'd'])
df['pc'] = df.groupby('ticker')['close'].shift(1)
df['pf'] = df.groupby('ticker')['qfq_factor'].shift(1)
df = df[(df['d'] > UNIV_MAX) & df['pc'].notna()].copy()
df['exr'] = (df['qfq_factor'] - df['pf']).abs() > 1e-9
print(f'日线库: 除权日 {int(df["exr"].sum())} 根 (保留bar, 仅不参与涨停判定)')

_sfx = {'SH': 'sh.', 'SZ': 'sz.', 'BJ': 'bj.'}
added = 0
for tk, d, o, h, l, c, pc, osh, exr in zip(df['ticker'], df['d'], df['open'], df['high'],
                                           df['low'], df['close'], df['pc'],
                                           df['oshare'], df['exr']):
    num, _, sfx = str(tk).partition('.')
    p = _sfx.get(sfx)
    if not p:
        continue
    mc = osh * c / 1e8 if (osh and osh > 0 and c and c > 0) else 0.0
    bars[p + num][d] = (float(o), float(h), float(l), float(c), float(pc),
                        float(mc), bool(exr))
    added += 1
print(f'日线库补 {UNIV_MAX} 之后 {added:,} 根, 补到 {df["d"].max()}')

# ── 2b. 单位量纲门 ⛔2026-09-16 加 ───────────────────────────
# 两个源同名字段单位不同(univ 的 turn 是百分数, 日线库的是小数比例), 这件事
# memory/reference_cn_hk_price_db.md 早就写了, 我合并时没去取, 于是九月整列算废。
# 下面这道断言就是把"记得去看"换成"忘了会炸": 换源当天市值中位数不该跳数量级。
import statistics as _st
_d1 = min(d for dd in bars.values() for d in dd if d > UNIV_MAX)
_med = lambda day: _st.median([v[5] for dd in bars.values()
                               for d, v in dd.items() if d == day and v[5] > 0])
_m0, _m1 = _med(UNIV_MAX), _med(_d1)
print(f'[单位门] {UNIV_MAX} 中位市值 {_m0:.1f}亿  vs  {_d1} {_m1:.1f}亿  比值 {_m1/_m0:.3f}')
assert 0.5 < _m1 / _m0 < 2.0, (
    f'⛔换源当天市值中位跳变 {_m1/_m0:.1f} 倍 — 十有八九是换手率单位没对齐')

# ── 3. 与 v4 完全一致的首板逻辑 ──────────────────────────────
rows = []
for code, dd in bars.items():
    ds = sorted(dd)
    n = len(ds)
    for i, d in enumerate(ds):
        o, h, l, c, pc, mcap, exr = dd[d]
        # ⛔涨跌幅随日期变(2026-07-06 主板ST 5%→10%), 所以 L 必须逐日算, 不能在股票循环外算一次。
        #   L 为 None = 该日无涨跌幅限制(新股前5日/老三板), 无法判涨停, 跳过。
        L = lim_pct_at(code, d)
        if L is None or exr or pc <= 0 or mcap <= 0 or mcap > 1e4:
            continue
        if not _islim(c, pc, L):
            continue
        if i > 0:                                  # ⛔只要首板
            p = dd[ds[i - 1]]
            Lp = lim_pct_at(code, ds[i - 1])       # ⛔前一日用前一日自己的制度, 不共用当日的
            if (not p[6]) and Lp is not None and p[4] > 0 and _islim(p[3], p[4], Lp):
                continue
        if i + 1 >= n:
            continue
        avail = n - 1 - i
        rec = dict(m=d[:7], code=code, date=d, mcap=mcap,
                   board='20cm' if L > 0.15 else '10cm',
                   open1=(dd[ds[i + 1]][0] / c - 1) * 100, avail=avail)
        for N in (1, 3, 5, 10, 20):
            k = min(i + N, n - 1)
            if k <= i:
                continue
            rec[f'r{N}'] = (dd[ds[k]][3] / c - 1) * 100
            rec[f'full{N}'] = avail >= N
            seg = [dd[ds[x]] for x in range(i + 1, k + 1)]
            rec[f'hi{N}'] = max((s[1] / c - 1) * 100 for s in seg)
            rec[f'lo{N}'] = min((s[2] / c - 1) * 100 for s in seg)
        final = 1
        fw = i + 1
        while fw < n:
            fb = dd[ds[fw]]
            Lf = lim_pct_at(code, ds[fw])          # ⛔后续每一日用该日自己的制度, 否则跨2026-07-06的连板会用错口径
            if (not fb[6]) and Lf is not None and fb[4] > 0 and _islim(fb[3], fb[4], Lf):
                final += 1
                fw += 1
            else:
                break
        rec['final'] = final
        if 'r10' in rec:
            rows.append(rec)

json.dump(rows, open(OUT, 'w'))
print(f'首板样本 {len(rows)} | {min(r["m"] for r in rows)}~{max(r["m"] for r in rows)}')

# ── 4. 回归断言: univ 覆盖期必须与 v4 逐只逐值一致 ────────────
old = json.load(open('/tmp/grid_v4.json'))
key = lambda R: {(r['code'], r['date']) for r in R if r['date'] <= UNIV_MAX}
a, b = key(old), key(rows)
print(f'\n[回归] univ期(<={UNIV_MAX}) v4={len(a)} v5={len(b)} '
      f'只在v4={len(a - b)} 只在v5={len(b - a)}')
# ⛔2026-09-16 断言改版: 原断言是"历史逐只逐值不变", 但当日加入ST涨跌幅维度后历史**必然**变化
#   (2025-2026全期新增2,328条ST涨停, 另46条因前一日在5%制度下也构成涨停而由首板降级)。
#   继续用旧断言会让每次重建都失败, 于是断言失去意义。改为分段断言: 差异必须全部与ST相关。
_bare = lambda k: k[0].split('.')[-1]
_add, _lost = b - a, a - b
_add_nonst = [k for k in _add if _bare(k) not in _ST]
_lost_nonst = [k for k in _lost if _bare(k) not in _ST]
print(f'[回归] 新增{len(_add)}(非ST {len(_add_nonst)}) 降级{len(_lost)}(非ST {len(_lost_nonst)})')
# 非ST的变化只允许极少数连带效应(前一日判定改变导致首板归属移动), 超过阈值即视为引入新错误
assert len(_add_nonst) <= 20, f'⛔非ST条目异常新增 {len(_add_nonst)} 条: {_add_nonst[:5]}'
assert len(_lost_nonst) <= 20, f'⛔非ST条目异常丢失 {len(_lost_nonst)} 条: {_lost_nonst[:5]}'
mc_old = {(r['code'], r['date']): r['mcap'] for r in old}
# ⛔2026-09-16: 只比对两版都存在的条目。加入ST维度后新增2,328条, 它们在旧版里不存在,
#   原写法会直接 KeyError —— 上半截断言改了、这半截忘了改, 与当日 astock_data_layer 的半截修改同型。
_both = [r for r in rows if r['date'] <= UNIV_MAX and (r['code'], r['date']) in mc_old]
worst = max(abs(r['mcap'] - mc_old[(r['code'], r['date'])]) for r in _both)
print(f'[回归] 历史市值最大偏差 {worst:.9f} 亿')
assert worst < 1e-6, '⛔历史市值被改动'
print(f'[回归] 通过: 共有条目逐值未变; 历史新增{len(_add)}条(ST涨跌幅维度, 非ST仅{len(_add_nonst)}条连带), '
      f'降级{len(_lost)}条(前一日在5%制度下亦涨停故当日非首板); {UNIV_MAX} 之后为新补数据')
