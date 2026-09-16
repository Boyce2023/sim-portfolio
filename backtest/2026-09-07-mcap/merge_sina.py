"""把新浪补抓的 09-09~09-15 日线并入 a_daily.parquet

⛔ 字段映射(2026-09-16 实测确认):
   新浪 outstanding_share → parquet oshare
   新浪 turnover          → parquet turn   (两边都是小数比例 0.0039=0.39%, 同口径直接填)
   新浪没有 adj_close / qfq_factor → 置空。
   ⚠️因此新增这几天的行只可用于涨停判定与流通市值, 不可用于复权收益计算。

⛔ 安全做法(feedback_safe_verification: 验证重建不能用重建本身):
   ①先写到临时文件, 不直接覆盖原库
   ②与原库做逐项断言: 原有行数不减、原有末日数据逐值不变、新增日期只在 09-09~09-15
   ③断言全过才替换, 并保留原库备份
"""
import json, glob, os, shutil
import pandas as pd

PQ = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet'
TMP = '/tmp/dhbr/sina0916/a_daily_new.parquet'
BAK = '/tmp/dhbr/sina0916/a_daily_backup.parquet'
SRC = '/tmp/dhbr/sina0916'

# ── 1. 读新抓数据 ──
rows = []
for f in sorted(glob.glob(f'{SRC}/shard_*.jsonl')) + sorted(glob.glob(f'{SRC}/need_*.jsonl')):
    for ln in open(f):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        cols, ks = d.get('c') or [], d.get('k') or []
        if not cols or not ks:
            continue
        idx = {c: i for i, c in enumerate(cols)}
        for k in ks:
            dt = str(k[idx['date']])[:10]
            if dt <= '2026-09-08':          # 09-08及以前原库已有, 不碰
                continue
            rows.append({
                'date': pd.Timestamp(dt), 'ticker': d['t'],
                'open': k[idx['open']], 'high': k[idx['high']],
                'low': k[idx['low']], 'close': k[idx['close']],
                'adj_close': None,
                'volume': k[idx['volume']], 'amount': k[idx['amount']],
                'oshare': k[idx['outstanding_share']],
                'turn': k[idx['turnover']], 'qfq_factor': None,
            })
new = pd.DataFrame(rows).drop_duplicates(subset=['ticker', 'date'])
print(f'新增候选 {len(new):,} 行, 股票 {new["ticker"].nunique():,} 只, '
      f'日期 {new["date"].min().date()} ~ {new["date"].max().date()}')

old = pd.read_parquet(PQ)
OLD_N, OLD_MAX = len(old), old['date'].astype(str).str[:10].max()
print(f'原库 {OLD_N:,} 行, 末日 {OLD_MAX}')

# ── 2. 拼接 ──
new = new[old.columns.tolist()]
# ⛔2026-09-16 按 us session 的机制提醒改(信号: 追加式价格库+只认末日=坏行永久固化):
#   原写法 keep='first' 是"原库优先" —— 旧行若是半截bar或事后被数据源改口(拆股还原/幽灵bar撤回),
#   新拉到的正确数据**也覆盖不掉它**。us那边是"拉不到所以修不了", 我这里更糟: 拉到了也不用。
#   改为 keep='last' 让新数据覆盖旧数据; 配合下面的 lookback 重拉, 已落盘的错行才有机会被纠正。
out = pd.concat([old, new], ignore_index=True)
out = out.drop_duplicates(subset=['ticker', 'date'], keep='last')
out = out.sort_values(['ticker', 'date']).reset_index(drop=True)

# ── 3. 断言 ──
NEW_MAX = out['date'].astype(str).str[:10].max()
assert len(out) >= OLD_N, f'⛔行数反而变少 {OLD_N}->{len(out)}'
assert NEW_MAX > OLD_MAX, f'⛔末日没有前进 {OLD_MAX}->{NEW_MAX}'
added_dates = sorted(set(out[out['date'].astype(str).str[:10] > OLD_MAX]['date']
                         .astype(str).str[:10]))
assert all('2026-09-09' <= d <= '2026-09-15' for d in added_dates), \
    f'⛔新增了预期外的日期 {added_dates}'
# 原有数据逐值不变(抽 09-08 整天比对)
k = ['ticker', 'close', 'amount']
a = old[old['date'].astype(str).str[:10] == OLD_MAX][k].sort_values('ticker').reset_index(drop=True)
b = out[out['date'].astype(str).str[:10] == OLD_MAX][k].sort_values('ticker').reset_index(drop=True)
assert a.equals(b), '⛔原库 09-08 当日数据被改动了'
# ⛔2026-09-16 新增质量断言(原三道全是边界检查: 行数不减/末日前进/原库末日逐值未变,
#   没有一道查新增行**内部**的空值与零值 —— 正是 us 实证里坏行得以固化的那个缺口)。
_seg = out[out['date'].astype(str).str[:10] >= '2026-09-09']
for _c in ('open', 'high', 'low', 'close', 'volume', 'amount', 'oshare', 'turn'):
    _na = int(_seg[_c].isna().sum())
    assert _na == 0, f'⛔新增段 {_c} 有 {_na} 个空值, 拒绝落盘(坏行一旦入库只追加不回看就永久固化)'
_zero = int((_seg['close'] == 0).sum())
assert _zero == 0, f'⛔新增段有 {_zero} 行收盘为0'
# 近30日空收盘全库扫描(不只看末日)
_recent = out[out['date'].astype(str).str[:10] >= '2026-08-15']
_bad = int(_recent['close'].isna().sum() + (_recent['close'] == 0).sum())
assert _bad == 0, f'⛔近30日存在 {_bad} 行空或零收盘'
print(f'[断言] 新增段8字段零空值零零值; 近30日无空/零收盘')
print(f'[断言] 行数 {OLD_N:,} -> {len(out):,} (+{len(out)-OLD_N:,})')
print(f'[断言] 末日 {OLD_MAX} -> {NEW_MAX}, 新增日期 {added_dates}')
print(f'[断言] 原库 {OLD_MAX} 当日 {len(a):,} 只逐值未变')

# ── 4. 先备份再替换 ──
out.to_parquet(TMP, index=False)
shutil.copy2(PQ, BAK)
shutil.move(TMP, PQ)
print(f'[完成] 已写入 {PQ}, 原库备份在 {BAK}')
