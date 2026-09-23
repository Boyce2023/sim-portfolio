#!/opt/homebrew/bin/python3.13
"""锚点校验: 我从日线库机械判定的连板数, 与东财涨停池官方"连板数"字段是否一致。
判定: 当日收盘 >= round(前收 * (1+涨跌幅上限), 2) 视为涨停(容差0.011元)。
上限: 创业300/301 与 科创688/689 = 20%; 北交所 4xx/8xx = 30%; 主板 = 10%; 主板ST = 5%。
连板数 = 从当日往前连续涨停的天数。
⛔ 这是为了把回测窗口从14天扩到60天而做的校验, 不通过就不回溯。
"""
import json, glob
import pandas as pd, numpy as np

px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
                     columns=['date','ticker','close'],
                     filters=[('date','>=',pd.Timestamp('2026-05-01'))]).sort_values(['ticker','date'])
px['prev_close'] = px.groupby('ticker')['close'].shift(1)

def lim(t):
    c = t[:6]
    if c[:3] in ('300','301','688','689'): return .20
    if c[0] in ('4','8'): return .30
    return .10

px['lim'] = px['ticker'].map(lim)
px['zt'] = px['close'] >= (px['prev_close']*(1+px['lim'])).round(2) - 0.011
# 连板数: 分组内连续True计数
g = px.groupby('ticker')['zt']
px['blk'] = (~px['zt']).groupby(px['ticker']).cumsum()
px['nb_calc'] = px.groupby(['ticker','blk']).cumcount()
# 块内第一行是那个非涨停日(计0); 若该票在窗口内一开头就涨停(blk==0)则无前置非涨停日, 需补1
px.loc[(px['blk'] == 0) & px['zt'], 'nb_calc'] = px.loc[(px['blk'] == 0) & px['zt'], 'nb_calc'] + 1
px.loc[~px['zt'], 'nb_calc'] = 0

rows = []
for f in sorted(glob.glob('/tmp/ztpool/*.json')):
    try: data = json.load(open(f))
    except Exception: continue
    d = f.split('/')[-1][:8]
    for r in data:
        c = str(r['代码']).zfill(6)
        rows.append({'date': pd.Timestamp(d), 'ticker': c+('.SH' if c[0] in '69' else ('.BJ' if c[0] in '48' else '.SZ')),
                     'name': r['名称'], 'nb_off': r['连板数']})
O = pd.DataFrame(rows)
print(f"官方涨停池 {len(O)} 条, {O['date'].nunique()} 天 {O['date'].min().date()} 到 {O['date'].max().date()}")

M = O.merge(px[['date','ticker','nb_calc','zt','close','prev_close','lim']], on=['date','ticker'], how='left')
miss = M['nb_calc'].isna().sum()
M2 = M.dropna(subset=['nb_calc'])
same = (M2['nb_calc'] == M2['nb_off']).sum()
print(f"可比 {len(M2)} 条: 一致 {same} ({same/len(M2)*100:.2f}%) | 不符 {len(M2)-same} | 库中无此票 {miss}")
bad = M2[M2['nb_calc'] != M2['nb_off']]
if len(bad):
    print("\n不符样例(前20):")
    print(bad[['date','ticker','name','nb_off','nb_calc','close','prev_close','lim']].head(20).to_string(index=False))
    print("\n不符按板块:")
    bad2 = bad.copy(); bad2['bk'] = bad2['lim'].map({.1:'10cm',.2:'20cm',.3:'30cm'})
    print(bad2.groupby(['bk','nb_off']).size().to_string())
