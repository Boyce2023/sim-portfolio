#!/opt/homebrew/bin/python3
"""B策略概率打分 — 2026-09-10 Buwen令"以后所有的规则都是按概率给, 做每一条规则的概率分布"。

⛔取代原来的二元门(过/不过), 改为: 每条规则贡献一个相对基线的期望超额(pp), 相加得总分, 总分定仓位档。
训练: 2025 H1 涨停样本(非一字, n=8086), 口径 = 次日开盘价 ÷ 当日涨停价 - 1(B策略真实买卖点)。
样本外验证: 2025 H2(n=8104) 按分数五等分, 均值 1.19→2.62%, 胜率 59.3→74.7%, 亏超3%概率 13.8→2.9%, 三条线全单调。
底稿: backtest/2026-08-24-daban/backtest_raw.json; 验证脚本见 memory feedback 记录。
"""
BASE = 1.68  # H1 基线均值(%)

# 每维: (分档边界, 各档超额pp)。边界左闭右开。
TABLE = {
    'turn':   ([0, 3, 5, 8, 10, 13, 17, 25, 9e9],
               [+0.61, +0.62, +0.27, -0.06, +0.15, -0.04, -0.68, -1.65]),
    'amount': ([0, 2e8, 5e8, 10e8, 20e8, 9e18],
               [+0.64, +0.15, -0.41, -0.75, -1.00]),
    'streak': ([1, 2, 3, 4, 5, 99],
               [-0.08, +0.32, +0.53, +0.33, -0.14]),
    'gain20': ([-999, 0, 10, 30, 50, 9e9],
               [-0.38, +0.06, +0.15, +0.20, -0.41]),
    'board':  ([0, 0.15, 9],
               [-0.04, +0.34]),
    'isST':   ([0, 1, 2],
               [+0.02, -0.14]),
    # ⛔2026-09-10 新增: 流通市值(亿元)。此前一直说"回测样本无市值字段无法验证",
    #   实为可算 —— cn_hk_price_db 的 oshare × close 即当时流通市值, 13945 条匹配率 100%。
    #   验证结论: 各档超额全部落在 ±0.22pp 内(几乎为零), 而原硬门(首板≥100亿/2板以上≥50亿)
    #   挡掉 68% 样本只换来均值 +1.84%→+1.89%。故降级为打分一维, 不再一票否决。
    'fmv':    ([0, 20, 50, 100, 200, 500, 9e9],
               [+0.07, +0.12, -0.22, +0.01, +0.04, -0.05]),
}

# 分数 → 仓位档(占 B 池比例)。切点取自 H2 五等分的实际分界。
LADDER = [(2.50, 1/3, '满档'), (1.94, 2/9, '三分之二档'), (1.36, 1/9, '三分之一档')]
FLOOR = 1.36  # 低于此分不买(H2 最低两档: 均值仅+1.19%/+1.69%, 亏超3%概率 13.8%/6.0%)


def _bin(v, edges):
    for i in range(len(edges) - 1):
        if edges[i] <= v < edges[i + 1]:
            return i
    return len(edges) - 2


def score(turn=None, amount=None, streak=1, gain20=0.0, board=0.1, is_st=0, fmv=None, strict=True):
    """返回 (总分, 各维贡献dict)。

    ⛔strict=True(默认, 实盘用): 任何一维缺失 → 总分返回 None = 不买。
      理由(2026-09-10): 缺失按 0 贡献处理时, 拿不到数据的票会按基线记分反而进档,
      等于把"数据故障"降级成"合法正常值"。实盘七维全部可得(qt 给 turn/amount/流通市值f44,
      b_watch 给 streak, K线算 gain20, 代码前缀定 board, 名称定 isST), 拿不到就该弃权。
    strict=False: 研究/回填用, 缺失记 0。"""
    detail = {}
    total = BASE
    vals = {'turn': turn, 'amount': amount, 'streak': streak,
            'gain20': gain20, 'board': board, 'isST': 1 if is_st else 0, 'fmv': fmv}
    missing = [d for d, v in vals.items() if v is None]
    for dim, (edges, deltas) in TABLE.items():
        v = vals.get(dim)
        if v is None:
            detail[dim] = None
            continue
        d = deltas[_bin(v, edges)]
        detail[dim] = d
        total += d
    if strict and missing:
        return None, detail
    return round(total, 2), detail


def sizing(s):
    """分数 → (占池比例, 档位名)。低于 FLOOR 或分数为 None(数据缺失) 返回 (0, '不买')。"""
    if s is None:
        return 0.0, '不买(数据缺失)'
    for cut, frac, name in LADDER:
        if s >= cut:
            return frac, name
    return 0.0, '不买'


def explain(turn=None, amount=None, streak=1, gain20=0.0, board=0.1, is_st=0, fmv=None, strict=True):
    s, d = score(turn, amount, streak, gain20, board, is_st, fmv, strict)
    frac, name = sizing(s)
    parts = ' '.join(f"{k}{v:+.2f}" for k, v in d.items() if v is not None)
    miss = [k for k, v in d.items() if v is None]
    head = f"分{s:+.2f}" if s is not None else "分—"
    return (f"{head}(基线{BASE:+.2f} {parts}"
            + (f" ⛔缺{','.join(miss)}" if miss else "") + f") → {name}")
