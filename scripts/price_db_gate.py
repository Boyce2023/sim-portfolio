#!/usr/bin/env python3
"""日线库口径门 — 读库之前先过, 拦"数全在但口径是错的"

⛔ 为什么需要这个门(2026-09-17, 六 session 夜间对账时三个域独立撞到同一个病):
   形状类断言(行数不减/末根日期新/无空值/覆盖率)对口径错误天生免疫。
   实证: 本库 2026-09-15 当日 1,792 只、零空值、末日最新, 四道形状断言全绿,
   而 09-08 当日是 5,207 只 —— 有 3,415 只股票整整一周没有数据,
   任何读近一周做回测或筛股的动作都在用三分之一的市场, 且收不到任何警告。

三道门, 每道都是"口径"不是"形状":
  G1 覆盖连续性 —— 相邻交易日的股票数不得骤降; 只看"有没有数据"看不出来
  G2 复权因子新鲜度 —— 因子最新日必须跟得上价格最新日; 落后就意味着
     这期间除权的股票, 它此前全部历史行的复权价都是旧的(增量只写新行, 够不着历史)
  G3 锚点不变量 —— 钉死一个老日期, 存 close/adj_close 比值; 比值该变没变=历史没被重写,
     不该变却变了=数据源改了口径。⛔只断言"变没变", 不断言"变多少"
     (拆股让比值变整数倍、分红变千分之几, 差三个数量级, 断言幅度必然误报)

⛔ 用法是"读库前调用", 不是"每天跑一次报平安":
     from price_db_gate import assert_usable
     assert_usable(max_date='2026-09-15', need_adj=True)   # 要用复权价就传 True
"""
import json
import os
import sys

import pandas as pd

DB = os.path.expanduser('~/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet')
ANCHOR_FILE = os.path.expanduser('~/claude-projects/sim-portfolio/data/cn_hk_price_db/anchor_ratios.json')
ANCHOR_DATE = '2024-01-02'      # 钉死不动; 换日期等于把基线洗掉, 下次比对必然全绿
COVERAGE_DROP_MAX = 0.20        # 相邻交易日覆盖跌幅上限


def _load(path=DB):
    df = pd.read_parquet(path, columns=['date', 'ticker', 'close', 'adj_close', 'qfq_factor'])
    df['d'] = df['date'].astype(str).str[:10]
    return df


def check_coverage(df, tail=10):
    """G1: 覆盖连续性。返回 (ok, 明细)"""
    days = sorted(df['d'].unique())[-tail:]
    cnt = df[df['d'].isin(days)].groupby('d')['ticker'].nunique().to_dict()
    bad = []
    for a, b in zip(days, days[1:]):
        na, nb = cnt[a], cnt[b]
        if na and (na - nb) / na > COVERAGE_DROP_MAX:
            bad.append(f'{a}({na:,}只) -> {b}({nb:,}只) 覆盖骤降 {(na-nb)/na*100:.1f}%')
    return (not bad), {'每日覆盖': cnt, '骤降': bad}


def check_factor_fresh(df):
    """G2: 复权因子新鲜度。因子最新日落后价格最新日 = 这期间除权的股票历史复权价全过期"""
    price_max = df['d'].max()
    f = df[df['qfq_factor'].notna()]
    factor_max = f['d'].max() if len(f) else None
    lag_rows = int((df['d'] > (factor_max or '')).sum())
    ok = (factor_max == price_max)
    return ok, {'价格最新日': price_max, '因子最新日': factor_max,
                '无因子的行数': lag_rows}


def check_anchor(df, write=False):
    """G3: 锚点不变量。首次跑写基线, 之后每次比对。⛔只断言变没变, 不断言变多少"""
    a = df[df['d'] == ANCHOR_DATE]
    a = a[a['close'].notna() & a['adj_close'].notna() & (a['adj_close'] != 0)]
    cur = {t: round(float(c / ac), 6) for t, c, ac
           in zip(a['ticker'], a['close'], a['adj_close'])}
    if not os.path.exists(ANCHOR_FILE):
        if write:
            json.dump({'anchor_date': ANCHOR_DATE, 'ratios': cur},
                      open(ANCHOR_FILE, 'w'))
            return True, {'首次建立基线': len(cur)}
        return True, {'⚠️尚无基线': '跑一次 --write-anchor 建立, 在此之前 G3 不具判别力'}
    base = json.load(open(ANCHOR_FILE))['ratios']
    changed = [t for t in cur if t in base and cur[t] != base[t]]
    # ⛔新股在锚点日无数据 -> 比值缺失, 按"本期无基线"处理, 绝不能当成"没变"
    no_base = [t for t in cur if t not in base]
    return True, {'比值变化的股票数': len(changed), '变化样例': changed[:8],
                  '锚点日无基线(新股等)': len(no_base)}


def assert_usable(max_date=None, need_adj=False, path=DB, verbose=True):
    """⛔读库前调用。need_adj=True 时 G2 从告警升为硬拦(要用复权价就必须因子是新的)"""
    df = _load(path)
    fails, warns = [], []

    ok1, d1 = check_coverage(df)
    if not ok1:
        fails.append('G1 覆盖连续性: ' + '; '.join(d1['骤降']))

    ok2, d2 = check_factor_fresh(df)
    if not ok2:
        msg = (f"G2 复权因子只到 {d2['因子最新日']}, 而价格到 {d2['价格最新日']}, "
               f"{d2['无因子的行数']:,} 行无因子 —— 这期间除权的股票, 其**全部历史行**的"
               f"复权价都是旧的(增量只写新行, 物理上够不着历史, 只能全量重建)")
        (fails if need_adj else warns).append(msg)

    _, d3 = check_anchor(df)

    if max_date and df['d'].max() != max_date:
        fails.append(f"终点不符: 要求 {max_date}, 库里最新 {df['d'].max()} —— "
                     f"⛔不许静默回退到最近可用日, 那会让区间收益静默错几个百分点")

    if verbose:
        print(f'[库] {len(df):,} 行, {df["ticker"].nunique():,} 只, 最新 {df["d"].max()}')
        print(f'[G1] 近10日覆盖: ' + ', '.join(f'{k[5:]}={v:,}' for k, v in d1['每日覆盖'].items()))
        print(f'[G2] {d2}')
        print(f'[G3] {d3}')
        for w in warns:
            print(f'⚠️  {w}')
    if fails:
        raise AssertionError('⛔日线库口径门未通过:\n  - ' + '\n  - '.join(fails))
    if verbose:
        print('[门] 通过')
    return True


if __name__ == '__main__':
    if '--write-anchor' in sys.argv:
        df = _load()
        print(check_anchor(df, write=True))
        sys.exit(0)
    try:
        assert_usable(need_adj='--need-adj' in sys.argv)
    except AssertionError as e:
        print(e)
        sys.exit(1)
