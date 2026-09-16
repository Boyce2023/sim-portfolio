#!/usr/bin/env python3
"""5连板实验(2026-09-15 Buwen: "五连板的规则, 你可以试试看, 说不定有效")。

规则(来自 /tmp/dhbr/lbN 两个月回测里唯一无前视的口径"封住次开买一周", n19 均+8.0% 中+10.1% 胜68%):
  信号: 第5板收盘封住(当日涨停池 连板数==5, 非ST)
  买入: 次一交易日开盘价; 若开盘即在涨停价(一字)则不买(回测同样剔除)
  卖出: 第5个交易日收盘价(T+5), 无止损(与回测一致, 不中途加规则)
  账本: B策略专户(--book b), 与基本面盘物理隔离; 单笔固定金额, 小仓试验
⛔样本只有两个月19笔且分化极大(+36%到-29%), 这是验证实验不是已证实策略。
用法:
  python3 scripts/lb5_experiment.py buy <代码> <名称> <信号日YYYYMMDD> [金额]
  python3 scripts/lb5_experiment.py sell <代码> <名称>
"""
import json, subprocess, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AMOUNT = 300000


def quote(code):
    pre = 'sh' if code[0] in '69' else 'sz'
    raw = urllib.request.urlopen(urllib.request.Request(
        f'https://qt.gtimg.cn/q={pre}{code}', headers={'User-Agent': 'Mozilla/5.0'}), timeout=10).read().decode('gbk', 'ignore')
    f = raw.split('~')
    return dict(name=f[1], price=float(f[3]), prev=float(f[4]), open=float(f[5]), ts=f[30])


def limit_price(code, prev):
    lim = 0.2 if code[:2] in ('30', '68') else 0.1
    return round(prev * (1 + lim) + 1e-9, 2)


def run(args):
    cmd = ['python3', str(ROOT / 'scripts' / 'execute_trade.py')] + args
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    print(r.stdout[-3000:], r.stderr[-2000:])
    if r.returncode != 0:
        sys.exit(f'⛔ execute_trade 退出码 {r.returncode}, 未成交')


def main():
    act, code, name = sys.argv[1], sys.argv[2], sys.argv[3]
    q = quote(code)
    if act == 'buy':
        sig = sys.argv[4]
        amt = float(sys.argv[5]) if len(sys.argv) > 5 else AMOUNT
        lp = limit_price(code, q['prev'])
        print(f"{code} {q['name']} 开{q['open']} 现{q['price']} 昨收{q['prev']} 涨停价{lp} @{q['ts']}")
        if q['open'] <= 0:
            sys.exit('⛔ 未取到开盘价(可能停牌或未开盘), 不买')
        if q['open'] >= lp - 0.005:
            sys.exit('开盘即涨停(一字), 按回测口径不买')
        shares = int(amt / q['price'] / 100) * 100
        if shares < 100:
            sys.exit('⛔ 股数不足100')
        reason = (f"B策略专户·5连板实验: {name}{code} {sig}第5板收盘封住, 次日开盘买, 持有到第5个交易日收盘卖, 无止损。"
                  f"依据两个月回测'封住次开买一周' n19 均+8.0% 中+10.1% 胜68%, 分化+36%到-29%, 属验证实验。Buwen 09-15令试行")
        run(['buy', '--account', 'cn', '--ticker', code, '--shares', str(shares), '--book', 'b', '--reason', reason])
    elif act == 'sell':
        reason = f"B策略专户·5连板实验: {name}{code} 持有满5个交易日, 按实验规则收盘卖出, 与盈亏无关"
        run(['sell', '--account', 'cn', '--ticker', code, '--all', '--reason', reason])
    else:
        sys.exit('用法: buy|sell')


if __name__ == '__main__':
    main()
