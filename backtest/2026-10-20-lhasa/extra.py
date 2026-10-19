"""补充切片: 断板子集的可比性与显著性, 买拉萨卖游资的出货形态, 近3月逐只名单(带名字)"""
import pandas as pd, numpy as np, os, requests, glob
from scipy import stats
os.chdir(os.path.dirname(os.path.abspath(__file__)))
df = pd.read_pickle('events.pkl').reset_index()
df['ln_g'] = df.ln.clip(upper=4).map({0: '0', 1: '1', 2: '2', 3: '3', 4: '4到5'})


def names(codes):
    out = {}
    s = requests.Session(); s.trust_env = False
    codes = list(codes)
    for i in range(0, len(codes), 60):
        q = ','.join(('sh' if c[0] == '6' else 'sz') + c for c in codes[i:i + 60])
        r = s.get('https://qt.gtimg.cn/q=' + q, timeout=15); r.encoding = 'gbk'
        for line in r.text.split(';'):
            if '~' in line:
                f = line.split('~'); out[f[2]] = f[1]
    return out


hi = df[df.boards_prev >= 5]; brk = hi[~hi.zt_T]
print('=== 断板子集(前一日连板≥5, T日未涨停) 各组可比性 ===')
print(brk.groupby('ln_g').agg(n=('code', 'size'), T日涨幅均=('ret_T', 'mean'), T日换手均=('turn_T', 'mean'), 前20日涨幅均=('prior20', 'mean'),
                              前一日连板均=('boards_prev', 'mean'), 卖方拉萨席位均=('s_ln', 'mean'), 拉萨买入份额均=('share', 'mean')).round(3).to_string())
a, b = brk[brk.ln == 0], brk[brk.ln >= 4]
for col in ['c1', 'c5', 'mdd5', 'c10']:
    x, y = a[col].dropna(), b[col].dropna()
    t = stats.ttest_ind(x, y, equal_var=False); u = stats.mannwhitneyu(x, y)
    print(f'{col}: 拉萨0 均{x.mean()*100:.1f}% (n={len(x)}) vs 拉萨4到5 均{y.mean()*100:.1f}% (n={len(y)})  Welch t={t.statistic:.2f} p={t.pvalue:.4f}  MannWhitney p={u.pvalue:.4f}')
print('\n=== 断板子集里 买方拉萨≥4 再按卖方是谁拆: 卖方拉萨≤1(游资或机构在卖给散户) vs 卖方也是拉萨≥3 ===')
b2 = brk[brk.ln >= 4].copy(); b2['卖方'] = np.where(b2.s_ln <= 1, '卖方非拉萨', np.where(b2.s_ln >= 3, '卖方也拉萨', '中间'))
print(b2.groupby('卖方').agg(n=('code', 'size'), 次日收盘=('c1', 'mean'), 五日中位=('c5', 'median'), 五日均=('c5', 'mean'),
                            五日回撤超15=('mdd5', lambda s: (s <= -0.15).mean()), 十日均=('c10', 'mean')).round(3).to_string())
print('\n=== 全样本 断板子集 按拉萨买入份额分档(份额=拉萨买入额/买五合计) ===')
brk2 = brk.copy(); brk2['份额档'] = pd.cut(brk2.share, [-0.01, 0.0001, 0.3, 0.6, 0.8, 1.01], labels=['0', '0到30%', '30到60%', '60到80%', '80%以上'])
print(brk2.groupby('份额档', observed=True).agg(n=('code', 'size'), 次日收盘=('c1', 'mean'), 五日中位=('c5', 'median'), 五日回撤超15=('mdd5', lambda s: (s <= -0.15).mean()),
                                              十日回撤超20=('mdd10', lambda s: (s <= -0.20).mean())).round(3).to_string())

rec = df[(df.date >= '2026-07-20') & (df.ln >= 3) & (df.boards_prev >= 3)].sort_values('date')
nm = names(set(rec.code) | {'600825'})
rec['name'] = rec.code.map(nm)
cols = ['date', 'code', 'name', 'boards_prev', 'zt_T', 'ret_T', 'turn_T', 'ln', 'share', 's_ln', 'gap1', 'c1', 'c5', 'mdd5', 'c10']
r = rec[cols].copy()
for c in ['ret_T', 'turn_T', 'share', 'gap1', 'c1', 'c5', 'mdd5', 'c10']:
    r[c] = (r[c] * 100).round(1)
r['date'] = r.date.dt.strftime('%m-%d')
print('\n=== 近3月 前一日连板≥3 且买方拉萨≥3 逐只(% 单位; c5/c10 为 T 后第5/10日收盘相对 T 收盘; mdd5 为 5 日内最低价) ===')
print(r.to_string(index=False))
x = df[(df.code == '600825')].sort_values('date')
print('\n=== 新华传媒 600825 本轮上榜记录 ===')
print(x[['date', 'boards_prev', 'zt_T', 'ret_T', 'turn_T', 'ln', 'share', 's_ln', 'c1', 'c5']].to_string(index=False))
raw = pd.concat([pd.read_parquet(f) for f in glob.glob('raw/buy_2026-09.parquet') + glob.glob('raw/buy_2026-10.parquet')])
print('raw 里 600825 上榜日:', sorted(raw[raw.SECURITY_CODE.astype(str) == '600825'].TRADE_DATE.str[:10].unique()))
