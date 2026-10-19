"""龙虎榜买方前五里拉萨席位扎堆后的走势(2026-10-20 Buwen 问: 拉萨相关特别多, 历史上会暴跌吗, 近3个月呢, 类似今天的新华传媒)
数据: raw/{buy,sell}_YYYY-MM.parquet(东财龙虎榜席位明细, 2021-01 起), 日线库 a_daily(不复权原价)。
事件 = (股票, 上榜日 T)。特征全部在 T 收盘后可得(龙虎榜当晚公布), 买卖按 T+1 起算, 无前视。
拉萨席位 = 营业部名含"拉萨"或"山南"(都是东方财富证券西藏营业部, 散户通道)。
"""
import pandas as pd, numpy as np, glob, os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
DB = '../../data/cn_hk_price_db/a_daily.parquet'
RECENT = '2026-07-20'


def load_side(side):
    df = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f'raw/{side}_*.parquet'))], ignore_index=True)
    df['date'] = pd.to_datetime(df.TRADE_DATE.str[:10])
    df['code'] = df.SECURITY_CODE.astype(str).str.zfill(6)
    df = df[df.code.str[0].isin(list('036'))]            # 只要沪深 A 股, 不要北交所
    amt = 'BUY' if side == 'buy' else 'SELL'
    # 同一股同一天可能因两条上榜理由各报一次前五, 席位按营业部去重取最大金额, 再取前五
    g = df.groupby(['code', 'date', 'OPERATEDEPT_CODE'], as_index=False).agg(amt=(amt, 'max'), name=('OPERATEDEPT_NAME', 'first'),
                                                                               chg=('CHANGE_RATE', 'first'))
    g = g.sort_values('amt', ascending=False).groupby(['code', 'date']).head(5)
    g['ls'] = g.name.str.contains('拉萨|山南', na=False)
    g['lamt'] = g.amt.where(g.ls, 0.0)
    ev = g.groupby(['code', 'date']).agg(n=('ls', 'size'), ln=('ls', 'sum'), amt=('amt', 'sum'), lamt=('lamt', 'sum'), chg=('chg', 'first'))
    ev['share'] = ev.lamt / ev.amt
    return ev


def forward(ev):
    """给每个事件接上 T 前后走势。P 用不复权价; 事件股当期没有除权(连板中极少), 偏差可忽略。"""
    codes = set(ev.index.get_level_values(0))
    P = pd.read_parquet(DB, columns=['date', 'ticker', 'open', 'high', 'low', 'close', 'turn'],
                        filters=[('date', '>=', pd.Timestamp('2020-11-01'))])
    P['code'] = P.ticker.str[:6]
    P = P[P.code.isin(codes)].sort_values(['code', 'date'])
    out = []
    for code, g in P.groupby('code'):
        g = g.reset_index(drop=True)
        c, o, h, l = g.close.values, g.open.values, g.high.values, g.low.values
        lim = 0.195 if code[:2] in ('30', '68') else 0.095
        pct = c[1:] / c[:-1] - 1
        zt = np.r_[False, (pct >= lim) & (c[1:] >= h[1:] - 1e-9)]
        dt = np.r_[False, (pct <= -lim) & (c[1:] <= l[1:] + 1e-9)]
        boards = np.zeros(len(c), int)
        for i in range(1, len(c)):
            boards[i] = boards[i - 1] + 1 if zt[i] else 0
        idx = {d: i for i, d in enumerate(g.date)}
        for d in ev.loc[code].index:
            i = idx.get(d)
            if i is None or i < 20:
                continue
            r = dict(code=code, date=d, ret_T=c[i] / c[i - 1] - 1, zt_T=zt[i], boards_T=boards[i], boards_prev=boards[i - 1],
                     prior10=c[i] / c[i - 10] - 1, prior20=c[i] / c[i - 20] - 1, turn_T=g.turn.values[i])
            for k in (1, 2, 3, 4, 5, 10):
                r[f'c{k}'] = c[i + k] / c[i] - 1 if i + k < len(c) else np.nan
            r['gap1'] = o[i + 1] / c[i] - 1 if i + 1 < len(c) else np.nan
            r['dt1'] = dt[i + 1] if i + 1 < len(c) else np.nan
            r['buy1_c5'] = c[i + 5] / o[i + 1] - 1 if i + 5 < len(c) else np.nan       # 次日开盘买, 第5日收盘卖
            for k in (5, 10):
                r[f'mdd{k}'] = l[i + 1:i + 1 + k].min() / c[i] - 1 if i + k < len(c) else np.nan
                r[f'mup{k}'] = h[i + 1:i + 1 + k].max() / c[i] - 1 if i + k < len(c) else np.nan
            out.append(r)
    F = pd.DataFrame(out).set_index(['code', 'date'])
    return ev.join(F, how='inner')


def table(df, by, label):
    rows = []
    for k, g in df.groupby(by):
        rows.append({label: k, 'n': len(g),
                     '次日开盘%': g.gap1.mean() * 100, '次日收盘%': g.c1.mean() * 100, '次日跌停%': g.dt1.mean() * 100,
                     '次日收≤-7%': (g.c1 <= -0.07).mean() * 100,
                     '5日收盘中位%': g.c5.median() * 100, '5日均%': g.c5.mean() * 100, '5日为负%': (g.c5 < 0).mean() * 100,
                     '5日最深回撤均%': g.mdd5.mean() * 100, '5日内≤-15%': (g.mdd5 <= -0.15).mean() * 100,
                     '10日收盘均%': g.c10.mean() * 100, '10日内≤-20%': (g.mdd10 <= -0.20).mean() * 100,
                     '次日开买5日卖均%': g.buy1_c5.mean() * 100})
    return pd.DataFrame(rows).round(1)


if __name__ == '__main__':
    buy = load_side('buy'); sell = load_side('sell').rename(columns=lambda c: 's_' + c)
    ev = buy.join(sell, how='left')
    ev['s_ln'] = ev.s_ln.fillna(0).astype(int)
    df = forward(ev)
    df['ln_g'] = df.ln.clip(upper=4).map({0: '0', 1: '1', 2: '2', 3: '3', 4: '4到5'})
    df['period'] = np.where(df.index.get_level_values(1) >= RECENT, '近3月', '2021起')
    df.to_pickle('events.pkl')
    print('事件数', len(df), '日期', df.index.get_level_values(1).min().date(), '到', df.index.get_level_values(1).max().date())
    print('\n=== 全样本 2021-01 到今, 按买方前五里拉萨席位数 ===')
    print(table(df, 'ln_g', '拉萨席位').to_string(index=False))
    print('\n=== 近3个月(', RECENT, '起) ===')
    print(table(df[df.period == '近3月'], 'ln_g', '拉萨席位').to_string(index=False))
    hi = df[(df.boards_prev >= 5)]
    print('\n=== 前一日已连板≥5 的高标(新华传媒同类), 全样本 ===')
    print(table(hi, 'ln_g', '拉萨席位').to_string(index=False))
    brk = hi[~hi.zt_T]
    print('\n=== 其中 T 日断板(新华传媒 10-19 形态), 全样本 ===')
    print(table(brk, 'ln_g', '拉萨席位').to_string(index=False))
    cont = hi[hi.zt_T]
    print('\n=== 其中 T 日继续涨停, 全样本 ===')
    print(table(cont, 'ln_g', '拉萨席位').to_string(index=False))
    print('\n=== 近3月 高标(连板≥5) 按拉萨席位 ===')
    print(table(hi[hi.period == '近3月'], 'ln_g', '拉萨席位').to_string(index=False))
