#!/opt/homebrew/bin/python3
"""全市场收盘快照 — 策略一"剔除前一日下跌"过滤的前置基建。

⛔为什么需要: 实盘拆解实证"剔除前一日下跌"是最大单一杠杆(8-9月T+5加权 +2.49→+3.06%;
   4-5月T+3止损7% +1.57→+4.31% 胜率71%), 而实时接口只给当日 prev_close,
   判不了"前一日相对再前一日"的涨跌。必须每日收盘后落一份全市场快照。
⛔口径: 必须在 15:00 收盘后运行。盘中运行会把盘中价当收盘价存, 下游无法分辨。
   故本脚本自带时段断言, 盘中运行直接非零退出, 不写文件(不给"看起来正常"的坏数据)。
"""
import sys, os, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import astock_data_layer as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'market_snapshots')

def main():
    force = '--force' in sys.argv
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        print('⛔非交易日, 跳过'); return 0
    hm = now.hour * 100 + now.minute
    if hm < 1500 and not force:
        print(f'⛔当前 {now:%H:%M} 未收盘(需≥15:00)。盘中快照会把盘中价当收盘价, '
              f'下游"前一日涨跌"判据将基于错误数据。拒绝写入。')
        return 2                      # ⛔不是echo警告后照写, 是真的退出
    rows = A.get_full_market()
    snap = {x['code']: {'name': x['name'], 'close': x['price'], 'chg': x['change_pct'],
                        'turnover': x.get('turnover'), 'turnover_rate': x.get('turnover_rate'),
                        'mc': x.get('market_cap'), 'pe': x.get('pe')}
            for x in rows if x.get('price')}
    if len(snap) < 4000:              # ⛔覆盖率断言: 正常5000+, 骤降说明取数残缺
        print(f'⛔只取到 {len(snap)} 只(正常5000+), 疑似取数残缺, 拒绝写入'); return 3
    d = now.strftime('%Y%m%d')
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, f'{d}.json')
    json.dump({'date': now.strftime('%Y-%m-%d'), 'captured_at': now.isoformat(timespec='seconds'),
               'is_close': hm >= 1500, 'n': len(snap), 'data': snap},
              open(p, 'w'), ensure_ascii=False)
    back = json.load(open(p))         # ⛔写完读回验证
    assert back['n'] == len(snap), '写入校验失败'
    print(f'✅ {p}  {len(snap)} 只  is_close={back["is_close"]}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
