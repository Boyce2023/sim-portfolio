#!/usr/bin/env python3
"""
机械异动层 · tree_anomaly_scan.py · 2026-08-07
────────────────────────────────────────────────────────────────────────────
新架构第2层。第1层(产品树映射, data/product_tree_map.json)回答"谁在链上",
本层回答"今天谁在动"。两层交叉 = 今日候选池。

核心原则: 脚本负责筛选(机械无偏), agent负责判断(基本面)。
本脚本不做任何"该不该买"的判断,只产出客观读数+按分排序。买卖判断归 organism_decision.py。

数据源(⛔硬约束,不得使用其他源):
  ① astock_data_layer.get_full_market / get_batch_prices  — 今日实时快照(价/涨跌%/换手率/量,手为单位)
  ② 腾讯 qt.gtimg.cn                                        — astock_data_layer内部已含此兜底
  ③ 新浪 money.finance.sina.com.cn CN_MarketData.getKLineData — 历史日K(不含未收盘的"今日")
  ⛔ 禁用 ak.*_em (东财akshare接口, 2026-08-07实测push2his限流) / 禁用 yfinance / 禁用 baostock(kline_cache.py)

单位换算(2026-08-07实测确认,勿改):
  新浪K线成交量字段单位=股。astock_data_layer(EM口径)成交量字段单位=手(f5)。1手=100股。
  本脚本内部统一为"手": 新浪读数 volume_shares / 100 → 手。

"今日"这根K线的构造:
  新浪历史K线在盘中不含当日(实测: 2026-08-07 10:09盘中查询,最后一根仍是08-06)。
  所以"今日"用 astock_data_layer 实时快照拼一根: {今开/今高/今低/现价/累计成交量(手)}。
  若新浪返回的最后一根日期已等于今天(盘后已收), 则不重复拼接, 直接用新浪的收盘K线。

异动强度综合分(全部客观量,公式如下,范围约[-100,100]):
  score = 40*A + 25*B + 15*C + 10*D + 10*E
    A = clip(今日涨跌% / 10, -1, 1)                          今日涨跌幅度,±10%封顶
    B = sign(今日涨跌%) * clip((量比5 - 1) / 2, -1, 1)        5日量比确认(放量同向加分/缩量同向减分)
    C = sign(今日涨跌%) * clip((量比60 - 1) / 2, -1, 1)       60日量比确认(60日基准抗恐慌污染,权重次于5日)
    D = +1 突破前25日高 / -1 破前10日低(不含今) / 0 其他        结构位置信号
    E = +1 超跌反转(距60日高<-25%且近3日转正) / 0 其他          反转结构信号
  正=偏多异动, 负=偏空异动, 绝对值=强度。sign(0)=0(平盘不放大量比项)。

用法:
  python3 tree_anomaly_scan.py                              # 用默认产品树映射, 无则退化全市场扫描
  python3 tree_anomaly_scan.py --map /path/to/map.json       # 指定映射文件(测试/自定义用)
  python3 tree_anomaly_scan.py --tree "半导体设备国产化" --top 20
  python3 tree_anomaly_scan.py --json > /tmp/anomaly.json
  python3 tree_anomaly_scan.py --limit 30                    # 退化全市场模式下限制扫描数量(性能/测试)

产品树映射JSON兼容格式(自动识别):
  {"树名": ["600519", "000858", ...]}                        最简形式
  {"树名": [{"ticker":"600519","name":"贵州茅台","node":"..."}]}  带元数据
  [{"ticker":"600519","tree":"树名","name":"...","node":"..."}]  扁平列表形式
  {"trees": {...}}                                            带外层包装
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ⛔代理软件(Clash/Surge类)会劫持eastmoney/新浪的DNS→ProxyError。绕开走直连。
# astock_data_layer import时也会设一次, 这里显式再设一次(防止import顺序变化时漏设)。
os.environ.setdefault('NO_PROXY', '*')
os.environ.setdefault('no_proxy', '*')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import astock_data_layer as adl  # noqa: E402  (import即安装yfinance拦截器)

TZ_BJ = adl.TZ_BEIJING

TREE_MAP_PATH_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'product_tree_map.json'
)

SINA_KLINE_URL = (
    'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
    'CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen={n}'
)
SINA_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
    'Referer': 'https://finance.sina.com.cn',
}

BREAKOUT_N = 25   # 突破/距高窗口
PREVLOW_N = 10    # 破前低窗口
MA_SHORT = 20
MA_LONG = 60
CUMWIN = (3, 5, 10, 20, 60)   # 累计涨跌窗口(3日仅用于超跌反转判定, 其余按spec要求输出)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §1 产品树映射加载(第1层产出的消费方)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _norm_name(x):
    """名称比对归一化(2026-08-07加): 行情源会返回带空格("五 粮 液")、除权前缀("XD上汽集")、
    全角字母("京东方Ａ")的名字, 这些是显示噪音不是真事件。归一化后剩下的不匹配才值得看——
    实测24条警告里只有6条是真的(全是变ST: 迪瑞/香雪/明德/天际/荃银/闻泰)。
    噪音淹没真信号 = 警告机制失效, 所以必须归一化。"""
    t = str(x or "").replace(" ", "").replace("\u3000", "")
    for pre in ("XD", "DR", "XR"):
        if t.startswith(pre):
            t = t[len(pre):]
    return (t.replace("Ａ", "A").replace("Ｂ", "B")
             .replace("（", "(").replace("）", ")"))

def _norm_member(m, default_tree: str | None) -> dict | None:
    if isinstance(m, str):
        return {'ticker': m, 'tree': default_tree, 'name': None, 'node': None}
    if isinstance(m, dict):
        t = m.get('ticker') or m.get('code') or m.get('symbol')
        if not t:
            return None
        return {
            'ticker': str(t),
            'tree': m.get('tree') or m.get('tree_name') or default_tree,
            'name': m.get('name'),
            'node': m.get('node') or m.get('role'),
        }
    return None


def load_tree_map(path: str) -> list[dict] | None:
    """读产品树映射JSON。文件不存在返回None(调用方据此退化为全市场扫描)。
    兼容: {树名:[ticker,...]} / {树名:[{ticker,name,...}]} / [{ticker,tree,...}] / {'trees':{...}}"""
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    if isinstance(raw, dict) and 'trees' in raw and isinstance(raw['trees'], (dict, list)):
        raw = raw['trees']

    entries: list[dict | None] = []
    if isinstance(raw, dict):
        for tree_name, members in raw.items():
            if not isinstance(members, list):
                continue
            entries.extend(_norm_member(m, tree_name) for m in members)
    elif isinstance(raw, list):
        entries.extend(_norm_member(m, None) for m in raw)
    else:
        return []

    out: list[dict] = []
    seen: set[tuple[str, str | None]] = set()
    for e in entries:
        if e is None:
            continue
        code = adl.bare_code(str(e['ticker']))
        if not (code.isdigit() and len(code) == 6):
            continue  # ticker格式不合法(非6位数字), 静默跳过而非编造
        key = (code, e.get('tree'))
        if key in seen:
            continue
        seen.add(key)
        e['ticker'] = code
        out.append(e)
    return out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §2 数据拉取: ①今日实时快照(astock_data_layer) ③历史日K(新浪)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def batch_realtime(codes: list[str], chunk: int = 180) -> dict[str, dict]:
    """分块批量拉实时快照(EM ulist URL过长会被拒, 大池必须分块)。"""
    snaps: dict[str, dict] = {}
    for i in range(0, len(codes), chunk):
        part = codes[i:i + chunk]
        try:
            snaps.update(adl.get_batch_prices(part))
        except Exception as e:
            print(f'[warn] 实时快照批次{i // chunk}失败: {e}', file=sys.stderr)
        if i + chunk < len(codes):
            time.sleep(0.3)
    return snaps


def _sina_prefix(code: str) -> str:
    if code.startswith('6'):
        return 'sh'
    if code[:2] in ('92', '87', '83') or code[:1] in ('4', '8'):
        return 'bj'
    return 'sz'


def fetch_kline_sina(code: str, n: int = 90, timeout: int = 10, retries: int = 1) -> list[dict]:
    """拉N个交易日日K(新浪, 不含盘中未收盘的今日)。返回按日期升序[{d,o,h,l,c,v(手)}]。失败返回[]。"""
    prefix = _sina_prefix(code)
    url = SINA_KLINE_URL.format(prefix=prefix, code=code, n=n)
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=SINA_HEADERS)
            raw = urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', errors='ignore')
            m = re.search(r'\[.*\]', raw, re.DOTALL)
            if not m:
                if attempt < retries:
                    time.sleep(0.4)
                    continue
                return []
            rows = json.loads(m.group(0))
            bars = []
            for r in rows:
                try:
                    bars.append({
                        'd': str(r['day'])[:10],
                        'o': float(r['open']), 'h': float(r['high']),
                        'l': float(r['low']), 'c': float(r['close']),
                        'v': float(r['volume']) / 100.0,   # 新浪=股 → /100换算为手, 与EM口径对齐
                    })
                except (KeyError, TypeError, ValueError):
                    continue
            bars.sort(key=lambda x: x['d'])
            return bars
        except Exception:
            if attempt < retries:
                time.sleep(0.4)
                continue
            return []
    return []


def today_bar_from_snapshot(snap: dict, today_str: str) -> dict | None:
    """把实时快照拼成"今天"这根K线(手为单位, 与新浪换算后一致)。快照无价格返回None。"""
    price = snap.get('price')
    if price is None:
        return None
    return {
        'd': today_str,
        'o': snap.get('open') if snap.get('open') is not None else price,
        'h': snap.get('high') if snap.get('high') is not None else price,
        'l': snap.get('low') if snap.get('low') is not None else price,
        'c': price,
        'v': snap.get('volume') if snap.get('volume') is not None else 0.0,
    }


def combine_bars(hist: list[dict], snap: dict | None, today_str: str) -> tuple[list[dict], str]:
    """拼接历史K线+今日快照。新浪最后一根若已是今天(盘后已收)则不重复拼接。"""
    if hist and hist[-1]['d'] == today_str:
        return hist, 'kline含今日收盘(盘后数据)'
    tb = today_bar_from_snapshot(snap, today_str) if snap else None
    if tb is None:
        return hist, '实时快照缺失,今日读数用kline最后一根(可能非当日)'
    return hist + [tb], '今日=实时快照拼接(盘中数据,非最终收盘)'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §3 客观读数计算(全部机械, 无判断)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def compute_signals(bars: list[dict], snap: dict | None) -> dict:
    n = len(bars)
    out: dict = {'bars_n': n}
    if n < 2:
        out['_insufficient'] = True
        return out

    cur = bars[-1]['c']
    prev = bars[-2]['c']

    # 今日涨跌%: 优先用实时快照(更权威, 尤其盘中); 无快照时退化为K线收盘比
    if snap and snap.get('change_pct') is not None:
        chg_pct = snap['change_pct']
    else:
        chg_pct = round((cur / prev - 1) * 100, 2) if prev else None
    out['今日涨跌%'] = chg_pct

    out['换手率%'] = (snap or {}).get('turnover_rate')

    # 量比(5日基准) = 今日成交量(手) / 前5个交易日均量(不含今)
    v5 = [b['v'] for b in bars[-6:-1] if b.get('v')]
    out['量比5'] = round(bars[-1]['v'] / (sum(v5) / len(v5)), 2) if v5 and bars[-1].get('v') else None

    # 量比(60日基准), 要求至少40根有效数据避免样本太薄
    v60 = [b['v'] for b in bars[-61:-1] if b.get('v')]
    out['量比60'] = round(bars[-1]['v'] / (sum(v60) / len(v60)), 2) if len(v60) >= 40 and bars[-1].get('v') else None

    # 距25日高%(含今)
    out['距25日高%'] = round((cur / max(b['h'] for b in bars[-BREAKOUT_N:]) - 1) * 100, 1) if n >= BREAKOUT_N else None

    # 突破: 收盘>前25日高(不含今)
    if n >= BREAKOUT_N + 1:
        hi25_excl = max(b['h'] for b in bars[-BREAKOUT_N - 1:-1])
        out['突破前25日高'] = cur > hi25_excl
    else:
        out['突破前25日高'] = None

    # 距20日低%(含今)
    out['距20日低%'] = round((cur / min(b['l'] for b in bars[-MA_SHORT:]) - 1) * 100, 1) if n >= MA_SHORT else None

    # 破前10日低(不含今) — 辅助读数, 供综合分D分量对称使用
    if n >= PREVLOW_N + 1:
        lo10_excl = min(b['l'] for b in bars[-PREVLOW_N - 1:-1])
        out['破前10日低'] = cur < lo10_excl
    else:
        out['破前10日低'] = None

    # 是否站上20/60日线(MA含今日自身)
    out['站上20日线'] = (cur >= sum(b['c'] for b in bars[-MA_SHORT:]) / MA_SHORT) if n >= MA_SHORT else None
    out['站上60日线'] = (cur >= sum(b['c'] for b in bars[-MA_LONG:]) / MA_LONG) if n >= MA_LONG else None

    # 连续站上5日线天数(从最新往回数, 遇到跌破即停)
    days = 0
    if n >= 5:
        for i in range(n - 1, 3, -1):
            m5 = sum(b['c'] for b in bars[i - 4:i + 1]) / 5
            if bars[i]['c'] >= m5:
                days += 1
            else:
                break
    out['连续站上5日线天数'] = days

    # 近10日是否有一字板(高=低, 容差0.1%防浮点噪音)
    out['近10日一字板'] = any(b['h'] <= b['l'] * 1.001 for b in bars[-10:]) if n >= 10 else None

    # 近N日累计涨跌%(N=3用于超跌反转判定, 3/5/10/20/60均输出供审计)
    for N in CUMWIN:
        key = f'近{N}日累计%'
        if n >= N + 1 and bars[-(N + 1)]['c']:
            out[key] = round((cur / bars[-(N + 1)]['c'] - 1) * 100, 1)
        else:
            out[key] = None

    # 超跌反转: 距60日高(含今)<-25% 且 近3日转正
    if n >= MA_LONG:
        dist60 = round((cur / max(b['h'] for b in bars[-MA_LONG:]) - 1) * 100, 1)
        out['距60日高%'] = dist60
        near3 = out.get('近3日累计%')
        out['超跌反转'] = bool(dist60 < -25 and near3 is not None and near3 > 0)
    else:
        out['距60日高%'] = None
        out['超跌反转'] = None

    out['异动强度'] = _score(out)
    return out


def _score(sig: dict) -> float | None:
    """异动强度综合分, 公式见模块docstring。全部输入为本函数以上已算出的客观量, 无额外主观项。"""
    chg = sig.get('今日涨跌%')
    if chg is None:
        return None
    sign = 1.0 if chg > 0 else (-1.0 if chg < 0 else 0.0)

    A = _clip(chg / 10.0, -1, 1)

    vr5 = sig.get('量比5')
    B = sign * _clip((vr5 - 1) / 2.0, -1, 1) if vr5 is not None else 0.0

    vr60 = sig.get('量比60')
    C = sign * _clip((vr60 - 1) / 2.0, -1, 1) if vr60 is not None else 0.0

    if sig.get('突破前25日高'):
        D = 1.0
    elif sig.get('破前10日低'):
        D = -1.0
    else:
        D = 0.0

    E = 1.0 if sig.get('超跌反转') else 0.0

    score = 40 * A + 25 * B + 15 * C + 10 * D + 10 * E
    return round(_clip(score, -100, 100), 2)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §4 池构建 + ticker验证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_pool(map_path: str, limit: int | None) -> tuple[list[dict], dict[str, dict], bool]:
    """返回(entries, snaps, degraded)。degraded=True表示映射文件不存在, 已退化为全市场扫描。"""
    entries = load_tree_map(map_path)
    if entries is None:
        print(f'⚠️ 产品树映射文件不存在: {map_path}', file=sys.stderr)
        print('   退化为全市场扫描(全部A股, 不含产业树归属), 仅供机械异动读数用', file=sys.stderr)
        stocks = adl.get_full_market()
        entries = [{'ticker': s['code'], 'tree': None, 'name': s.get('name'), 'node': None}
                   for s in stocks if s.get('code')]
        snaps = {s['code']: s for s in stocks if s.get('code')}
        degraded = True
    else:
        if limit:
            entries = entries[:limit]
        codes = sorted({e['ticker'] for e in entries})
        snaps = batch_realtime(codes)
        degraded = False
    if limit and degraded:
        entries = entries[:limit]
        snaps = {c: s for c, s in snaps.items() if c in {e['ticker'] for e in entries}}
    return entries, snaps, degraded


def validate_entry(e: dict, snap: dict | None) -> tuple[bool, str | None]:
    """验证ticker确实存在(有实时价格)且映射文件里的name(若有)与行情名称一致。
    返回(是否有效, 问题描述或None)。⛔无价格=不存在/停牌/代码有误, 直接判无效, 绝不编造。"""
    if not snap or snap.get('price') is None:
        return False, '行情接口查无此代码或无价格(可能停牌/退市/北交所未覆盖/代码有误)'
    live_name = snap.get('name')
    map_name = e.get('name')
    _m, _l = _norm_name(map_name), _norm_name(live_name)
    # 行情名限4字, XD/DR除权前缀会挤掉尾字("XD上汽集"←"上汽集团"), 故去前缀后允许前缀匹配;
    # 映射名常带括号说明("中稀有色(原广晟有色,2025-12-31更名)"), 取括号前主体比对
    _m = _m.split('(')[0]
    if _m and _l and _m != _l and not (_m.startswith(_l) or _l.startswith(_m)):
        # ⭐ST变更单独标出来——这是真事件不是名称噪音, 应从建仓池排除
        st = '⚠️已变ST/退市风险! ' if any(k in str(live_name) for k in ('ST', 'PT', '退')) \
             and not any(k in str(map_name) for k in ('ST', 'PT', '退')) else ''
        map_name, live_name = _m, _l
        return True, f'{st}名称不匹配: 映射文件="{map_name}" vs 行情="{live_name}"(按行情名继续, 请检查映射文件)'
    return True, None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §5 主扫描流程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def scan(entries: list[dict], snaps: dict[str, dict], kline_days: int = 90,
         workers: int = 10, kline_timeout: int = 10) -> tuple[list[dict], list[dict]]:
    today_str = datetime.now(TZ_BJ).strftime('%Y-%m-%d')
    codes = sorted({e['ticker'] for e in entries})

    kline_map: dict[str, list[dict]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_kline_sina, c, kline_days, kline_timeout): c for c in codes}
        for fut in as_completed(futs):
            code = futs[fut]
            try:
                kline_map[code] = fut.result()
            except Exception:
                kline_map[code] = []
            done += 1
            if done % 200 == 0:
                print(f'  ...K线拉取 {done}/{len(codes)}', file=sys.stderr, flush=True)

    results: list[dict] = []
    invalid: list[dict] = []

    for e in entries:
        code = e['ticker']
        snap = snaps.get(code)
        ok, msg = validate_entry(e, snap)
        if not ok:
            invalid.append({'ticker': code, 'tree': e.get('tree'), 'reason': msg})
            continue

        hist = kline_map.get(code, [])
        if not hist:
            invalid.append({'ticker': code, 'tree': e.get('tree'),
                             'reason': 'K线获取失败(新浪接口无返回, 可能停牌/次新股/接口超时)'})
            continue

        bars, note = combine_bars(hist, snap, today_str)
        sig = compute_signals(bars, snap)
        if sig.get('_insufficient'):
            invalid.append({'ticker': code, 'tree': e.get('tree'),
                             'reason': f'K线数据不足({sig["bars_n"]}根,少于2根无法计算)'})
            continue

        row = {
            'ticker': code,
            'name': (snap or {}).get('name') or e.get('name'),
            'tree': e.get('tree'),
            'node': e.get('node'),
            **sig,
            'data_note': note,
        }
        if msg:
            row['flag'] = msg
        results.append(row)

    results.sort(key=lambda r: (r.get('异动强度') is None, -(r.get('异动强度') or 0)))
    return results, invalid


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §6 输出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _fmt(v) -> str:
    if v is None:
        return 'N/A'
    if isinstance(v, bool):
        return 'Y' if v else 'N'
    if isinstance(v, float):
        return f'{v:.2f}'
    return str(v)


def _boolmark(v) -> str:
    if v is None:
        return '-'
    return 'Y' if v else 'N'


def print_table(results: list[dict], invalid: list[dict], top: int, degraded: bool,
                 pool_size: int, elapsed: float) -> None:
    print('=' * 108)
    print(f'机械异动扫描 | {datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M")} | '
          f'池={pool_size} 有效={len(results)} 无效={len(invalid)} 耗时={elapsed:.1f}s')
    if degraded:
        print('⚠️ 退化模式: 映射文件缺失, 本次为全市场扫描, 结果无产业树归属')
    print('=' * 108)
    print(f'{"标的":<10}{"代码":<8}{"树":<16}{"涨跌%":>7}{"量比5":>7}{"量比60":>7}{"换手%":>7}'
          f'{"距25高%":>8}{"距20低%":>8}{"20线":>5}{"60线":>5}{"5线天":>5}{"突破":>5}{"超跌反转":>7}{"分":>8}')
    for r in results[:top]:
        print(
            f'{(r["name"] or "?")[:9]:<10}{r["ticker"]:<8}{(r.get("tree") or "-")[:15]:<16}'
            f'{_fmt(r.get("今日涨跌%")):>7}{_fmt(r.get("量比5")):>7}{_fmt(r.get("量比60")):>7}'
            f'{_fmt(r.get("换手率%")):>7}{_fmt(r.get("距25日高%")):>8}{_fmt(r.get("距20日低%")):>8}'
            f'{_boolmark(r.get("站上20日线")):>5}{_boolmark(r.get("站上60日线")):>5}'
            f'{r.get("连续站上5日线天数", 0):>5}{_boolmark(r.get("突破前25日高")):>5}'
            f'{_boolmark(r.get("超跌反转")):>7}{_fmt(r.get("异动强度")):>8}'
        )

    if invalid:
        print(f'\n--- 验证失败/数据不足({len(invalid)}只, 已排除排序) ---')
        for v in invalid[:30]:
            print(f'  {v["ticker"]:<8}{(v.get("tree") or "-")[:14]:<15}{v["reason"]}')
        if len(invalid) > 30:
            print(f'  ...还有{len(invalid) - 30}只未列出')

    flagged = [r for r in results if r.get('flag')]
    if flagged:
        print(f'\n--- 映射文件名称不匹配警告({len(flagged)}只, 仍纳入结果按行情名处理) ---')
        for r in flagged:
            print(f'  {r["ticker"]}: {r["flag"]}')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §7 CLI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main() -> None:
    ap = argparse.ArgumentParser(
        description='机械异动层: 产品树×今日异动扫描(纯客观读数, 不做买卖判断, 见模块docstring公式)')
    ap.add_argument('--map', default=TREE_MAP_PATH_DEFAULT, help='产品树映射JSON路径(默认data/product_tree_map.json)')
    ap.add_argument('--top', type=int, default=30, help='显示异动强度前N(默认30, 不影响--json的完整输出)')
    ap.add_argument('--tree', default=None, help='只看某棵产品树(按映射文件里的树名精确匹配)')
    ap.add_argument('--json', action='store_true', help='输出JSON(全部结果+无效清单, 不受--top限制)')
    ap.add_argument('--limit', type=int, default=None, help='限制处理的ticker总数(测试/性能用)')
    ap.add_argument('--workers', type=int, default=10, help='K线并发线程数(默认10)')
    ap.add_argument('--kline-days', type=int, default=90, help='拉取历史交易日数(默认90, 需≥61覆盖60日窗口)')
    args = ap.parse_args()

    entries, snaps, degraded = build_pool(args.map, args.limit)

    if args.tree:
        if degraded:
            print(f'⚠️ 退化模式下无产业树归属, --tree "{args.tree}" 过滤将返回空, 请先补齐映射文件', file=sys.stderr)
        entries = [e for e in entries if e.get('tree') == args.tree]
        if not entries:
            print(f'[warn] 树名 "{args.tree}" 未匹配到任何ticker, 可用树名见映射文件的key', file=sys.stderr)

    if not entries:
        print('无可扫描标的, 退出', file=sys.stderr)
        sys.exit(1)

    t0 = time.time()
    results, invalid = scan(entries, snaps, kline_days=args.kline_days,
                             workers=args.workers, kline_timeout=10)
    elapsed = time.time() - t0

    if args.json:
        print(json.dumps({
            'meta': {
                'scanned_at': datetime.now(TZ_BJ).isoformat(),
                'map_path': args.map,
                'pool_size': len(entries),
                'valid': len(results),
                'invalid': len(invalid),
                'degraded_full_market': degraded,
                'elapsed_sec': round(elapsed, 1),
            },
            'results': results,
            'invalid': invalid,
        }, ensure_ascii=False, indent=2))
        return

    print_table(results, invalid, args.top, degraded, len(entries), elapsed)


if __name__ == '__main__':
    main()
