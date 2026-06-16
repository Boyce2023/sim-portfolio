# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.31"]
# ///
"""
A股数据底层 — 唯一合法的A股行情数据入口

所有A股脚本、所有ad-hoc分析、所有agent扫描，获取A股数据必须经过这里。
yfinance已淘汰，本模块在import时自动安装拦截器。

数据源层级:
  1. push2delay.eastmoney.com HTTPS (主源, 5,861只, 59页30秒)
  2. akshare stock_zh_a_spot_em() (备源, 5,500+只, 3秒)
  3. baostock (验证源, 5,494只无北交所, 逐只查询)
  4. 腾讯 qt.gtimg.cn (批量收盘价, ~4,800只)

禁止:
  - yfinance获取A股行情 (慢+无北交所+社区2025年9月宣判死亡)
  - 网易财经API (全域502已死)
  - tushare免费tier (额度不够)
  - 北交所官方API (全线停用)

v1.0 | 2026-06-09 | 根因: Claude反复用yfinance做A股扫描，数据漏一半
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any

TZ_BEIJING = timezone(timedelta(hours=8))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §0 A股Ticker识别
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_CN_SUFFIXES = ('.SS', '.SZ', '.BJ', '.SH')
_CN_PREFIXES = ('60', '00', '30', '68', '8', '4', '9')


def is_cn_ticker(ticker: str) -> bool:
    """判断一个ticker是否为A股。支持 600519 / 600519.SS / 600519.SH 等格式。"""
    t = ticker.strip().upper()
    for sfx in _CN_SUFFIXES:
        if t.endswith(sfx):
            return True
    bare = t.split('.')[0]
    if bare.isdigit() and len(bare) == 6:
        return any(bare.startswith(p) for p in _CN_PREFIXES)
    return False


def bare_code(ticker: str) -> str:
    """提取6位纯数字代码: '600519.SS' → '600519', '600519' → '600519'"""
    return ticker.strip().split('.')[0]


def to_secid(ticker: str) -> str:
    """转Eastmoney secid: 6开头→1.6xxxxx(沪), 其他→0.xxxxxx(深/北)"""
    code = bare_code(ticker)
    if code.startswith('6'):
        return f'1.{code}'
    return f'0.{code}'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §1 Eastmoney push2delay — 主源
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_EM_BASE = 'https://push2delay.eastmoney.com/api/qt'
_EM_FIELDS_LIST = 'f2,f3,f4,f5,f6,f7,f8,f9,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f62'
_EM_UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}


def _em_request(url: str, timeout: int = 15) -> dict:
    """发送Eastmoney API请求，返回JSON。"""
    req = urllib.request.Request(url, headers=_EM_UA)
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def get_full_market(sort_by: str = 'f3', descending: bool = True,
                    max_pages: int = 60, page_size: int = 100) -> list[dict]:
    """
    全量A股行情扫描 — push2delay.eastmoney.com

    返回 list[dict], 每个dict包含:
      code, name, price, change_pct, change_amt, volume(手), turnover(亿),
      turnover_rate(%), pe, high, low, open, prev_close, market_cap(亿),
      circulating_cap(亿), amplitude(%), market(0=深/1=沪)

    默认按涨幅降序。覆盖5,861只(含北交所)。
    """
    all_items: list[dict] = []
    po = 0 if descending else 1

    for page in range(1, max_pages + 1):
        url = (
            f'{_EM_BASE}/clist/get?pn={page}&pz={page_size}&po={po}&np=1'
            f'&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2'
            f'&fid={sort_by}&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048'
            f'&fields={_EM_FIELDS_LIST}'
        )
        try:
            data = _em_request(url)
            diff = data.get('data')
            if diff is None:
                break
            items = diff.get('diff', [])
            if not items:
                break
            all_items.extend(items)
        except Exception as e:
            print(f'[astock_data_layer] page {page} failed: {e}', file=sys.stderr)
            break
        if page % 20 == 0:
            time.sleep(0.5)

    return [_parse_em_item(item) for item in all_items]


def get_batch_prices(tickers: list[str]) -> dict[str, dict]:
    """
    批量获取指定A股价格 — push2delay.eastmoney.com ulist接口

    输入: ['600519', '002371', '688072'] 或 ['600519.SS', ...]
    返回: {code: {price, prev_close, change_pct, name, source, ...}}
    """
    if not tickers:
        return {}

    codes = [bare_code(t) for t in tickers]
    secids = ','.join(to_secid(c) for c in codes)

    url = (
        f'{_EM_BASE}/ulist.np/get'
        f'?ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2'
        f'&fields=f2,f3,f4,f5,f6,f7,f8,f9,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23'
        f'&secids={secids}'
    )
    now_ts = datetime.now(TZ_BEIJING).isoformat()
    results: dict[str, dict] = {}

    try:
        data = _em_request(url)
        items = data.get('data', {}).get('diff', [])
        for item in items:
            code = str(item.get('f12', ''))
            parsed = _parse_em_item(item)
            parsed['source'] = 'eastmoney'
            parsed['timestamp'] = now_ts
            results[code] = parsed
    except Exception as e:
        for c in codes:
            results[c] = {'price': None, 'error': str(e), 'source': 'eastmoney', 'timestamp': now_ts}

    missing = [c for c in codes if c not in results or results[c].get('price') is None]
    if missing:
        for c in missing:
            results[c] = _fallback_single(c)

    return results


def get_single_price(ticker: str) -> dict:
    """获取单只A股价格。"""
    result = get_batch_prices([ticker])
    code = bare_code(ticker)
    return result.get(code, {'price': None, 'error': 'not found'})


def get_market_stats(stocks: list[dict] | None = None) -> dict:
    """
    市场统计 — 从全量数据计算。
    如果传入stocks则直接计算，否则自动调get_full_market()。

    返回: {total, up, down, flat, limit_up_10, limit_up_20, limit_down, turnover_trillion, ...}
    """
    if stocks is None:
        stocks = get_full_market()

    up = sum(1 for s in stocks if s.get('change_pct') is not None and s['change_pct'] > 0)
    down = sum(1 for s in stocks if s.get('change_pct') is not None and s['change_pct'] < 0)
    flat = len(stocks) - up - down

    limit_up_20 = sum(1 for s in stocks if s.get('change_pct') is not None and s['change_pct'] >= 19.9)
    limit_up_10 = sum(1 for s in stocks if s.get('change_pct') is not None and 9.9 <= s['change_pct'] < 19.9)
    limit_down = sum(1 for s in stocks if s.get('change_pct') is not None and s['change_pct'] <= -9.9)

    total_turnover = sum(s.get('turnover', 0) for s in stocks)

    return {
        'total': len(stocks),
        'up': up,
        'down': down,
        'flat': flat,
        'limit_up_10': limit_up_10,
        'limit_up_20': limit_up_20,
        'limit_up_total': limit_up_10 + limit_up_20,
        'limit_down': limit_down,
        'turnover_billion': round(total_turnover, 1),
        'turnover_trillion': round(total_turnover / 10000, 2),
    }


def get_top_movers(n: int = 50, min_turnover: float = 0, min_market_cap: float = 0,
                   stocks: list[dict] | None = None) -> list[dict]:
    """
    涨幅TOP N (排除新股首日>100%)
    min_turnover: 最低成交额(亿)
    min_market_cap: 最低市值(亿)
    """
    if stocks is None:
        stocks = get_full_market()

    filtered = [
        s for s in stocks
        if s.get('change_pct') is not None
        and s['change_pct'] < 100
        and s.get('turnover', 0) >= min_turnover
        and s.get('market_cap', 0) >= min_market_cap
    ]
    filtered.sort(key=lambda x: -(x.get('change_pct') or 0))
    return filtered[:n]


def get_limit_up_stocks(stocks: list[dict] | None = None) -> dict[str, list[dict]]:
    """
    涨停股分类: {'20cm': [...], '10cm': [...]}
    """
    if stocks is None:
        stocks = get_full_market()

    result: dict[str, list[dict]] = {'20cm': [], '10cm': []}
    for s in stocks:
        pct = s.get('change_pct')
        if pct is None or pct >= 100:  # 排除新股首日
            continue
        if 19.9 <= pct < 100:
            result['20cm'].append(s)
        elif 9.9 <= pct < 19.9:
            result['10cm'].append(s)

    for k in result:
        result[k].sort(key=lambda x: -(x.get('turnover') or 0))
    return result


def get_strong_movers(threshold: float = 5.0, min_turnover: float = 5.0,
                      min_market_cap: float = 100.0,
                      stocks: list[dict] | None = None) -> list[dict]:
    """
    强势股(涨幅≥threshold%, 不含涨停, 成交额≥min亿, 市值≥min亿)
    """
    if stocks is None:
        stocks = get_full_market()

    filtered = [
        s for s in stocks
        if s.get('change_pct') is not None
        and threshold <= s['change_pct'] < 9.9
        and s.get('turnover', 0) >= min_turnover
        and s.get('market_cap', 0) >= min_market_cap
    ]
    filtered.sort(key=lambda x: -(x.get('change_pct') or 0))
    return filtered


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §2 内部解析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _safe_float(val: Any) -> float | None:
    try:
        v = float(val)
        return v if v == v else None  # NaN check
    except (TypeError, ValueError):
        return None


def _parse_em_item(item: dict) -> dict:
    """解析Eastmoney API返回的单条记录。"""
    code = str(item.get('f12', ''))
    market = item.get('f13', 0)  # 0=深, 1=沪

    return {
        'code': code,
        'name': str(item.get('f14', '')),
        'price': _safe_float(item.get('f2')),
        'change_pct': _safe_float(item.get('f3')),
        'change_amt': _safe_float(item.get('f4')),
        'volume': _safe_float(item.get('f5')),       # 手
        'turnover': round((_safe_float(item.get('f6')) or 0) / 1e8, 2),  # 亿
        'turnover_rate': _safe_float(item.get('f8')),  # %
        'pe': _safe_float(item.get('f9')),
        'high': _safe_float(item.get('f15')),
        'low': _safe_float(item.get('f16')),
        'open': _safe_float(item.get('f17')),
        'prev_close': _safe_float(item.get('f18')),
        'market_cap': round((_safe_float(item.get('f20')) or 0) / 1e8, 1),  # 亿
        'circulating_cap': round((_safe_float(item.get('f21')) or 0) / 1e8, 1),  # 亿
        'amplitude': _safe_float(item.get('f7')),      # %
        'market': market,
        'suffix': '.SS' if market == 1 else '.SZ' if code.startswith(('0', '3')) else '.BJ',
    }


def _fallback_single(code: str) -> dict:
    """单只股票备源: ①push2delay stock/get ②腾讯qt.gtimg(代理挡EM时兜底,带市值)。"""
    secid = to_secid(code)
    url = f'{_EM_BASE}/stock/get?secid={secid}&fields=f43,f44,f45,f46,f170,f171,f58'
    now_ts = datetime.now(TZ_BEIJING).isoformat()
    try:
        data = _em_request(url)
        d = data.get('data') or {}
        raw_price = d.get('f43')
        if raw_price and raw_price > 0:
            price = round(raw_price / 100, 4)
            return {
                'price': price,
                'source': 'eastmoney_single',
                'timestamp': now_ts,
            }
    except Exception:
        pass
    # ②腾讯兜底 (2026-06-16: EM被代理挡时仍能拿价+市值,禁yfinance)
    try:
        return _fallback_tencent(code, now_ts)
    except Exception:
        pass
    return {'price': None, 'error': 'all sources failed', 'timestamp': now_ts}


def _fallback_tencent(code: str, now_ts: str) -> dict:
    """腾讯qt.gtimg备源: f[3]=现价 f[39]=流通市值(亿) f[45]=总市值(亿)。内部一致(流通<总),代理不挡。"""
    pre = 'sh' if str(code)[0] == '6' else ('bj' if str(code).startswith(('4', '8')) else 'sz')
    raw = urllib.request.urlopen(f'http://qt.gtimg.cn/q={pre}{code}', timeout=8).read().decode('gbk')
    f = raw.split('~')
    if len(f) < 46 or not f[3]:
        raise ValueError('tencent empty')
    prev = _safe_float(f[4])
    price = _safe_float(f[3])
    chg = round((price / prev - 1) * 100, 2) if prev else None
    return {
        'code': str(code), 'name': f[1], 'price': price, 'prev_close': prev,
        'change_pct': chg,
        'pe': _safe_float(f[52]) if len(f) > 52 and f[52] else None,
        'market_cap': _safe_float(f[45]),          # 总市值(亿)
        'circulating_cap': _safe_float(f[39]),      # 流通市值(亿)
        'source': 'tencent', 'timestamp': now_ts,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §3 yfinance拦截器
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class YFinanceCNBlocker:
    """
    yfinance拦截器: 检测到A股ticker自动报错并引导用这个模块。
    安装后yfinance.Ticker('600519.SS')会抛异常。
    yfinance.Ticker('AAPL')不受影响。
    """

    @staticmethod
    def install():
        """安装拦截器。在astock_data_layer被import时自动执行。"""
        try:
            import yfinance as yf
        except ImportError:
            return

        _original_ticker_init = yf.Ticker.__init__

        def _patched_init(self, ticker, *args, **kwargs):
            if is_cn_ticker(str(ticker)):
                raise RuntimeError(
                    f"\n{'='*60}\n"
                    f"⛔ A股数据禁止使用yfinance! ticker='{ticker}'\n"
                    f"\n"
                    f"正确用法:\n"
                    f"  from astock_data_layer import get_batch_prices, get_full_market\n"
                    f"  prices = get_batch_prices(['{bare_code(str(ticker))}'])\n"
                    f"\n"
                    f"数据源: push2delay.eastmoney.com (5,861只/30秒)\n"
                    f"yfinance已淘汰: 慢+无北交所+数据漏一半\n"
                    f"{'='*60}"
                )
            return _original_ticker_init(self, ticker, *args, **kwargs)

        yf.Ticker.__init__ = _patched_init

        _original_download = yf.download

        def _patched_download(tickers=None, *args, **kwargs):
            if tickers:
                ticker_list = tickers if isinstance(tickers, list) else [tickers]
                cn_found = [t for t in ticker_list if is_cn_ticker(str(t))]
                if cn_found:
                    raise RuntimeError(
                        f"\n{'='*60}\n"
                        f"⛔ A股数据禁止使用yfinance.download! 检测到A股ticker: {cn_found}\n"
                        f"\n"
                        f"正确用法:\n"
                        f"  from astock_data_layer import get_batch_prices\n"
                        f"  prices = get_batch_prices({[bare_code(str(t)) for t in cn_found]})\n"
                        f"{'='*60}"
                    )
            return _original_download(tickers, *args, **kwargs)

        yf.download = _patched_download
        print('[astock_data_layer] yfinance A股拦截器已安装', file=sys.stderr)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §4 自动安装 — import时生效
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

YFinanceCNBlocker.install()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §5 CLI — 直接运行时做市场扫描
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='A股数据底层 — Eastmoney数据源')
    parser.add_argument('--scan', action='store_true', help='全量市场扫描')
    parser.add_argument('--top', type=int, default=30, help='显示涨幅TOP N')
    parser.add_argument('--tickers', nargs='+', help='查询指定股票: --tickers 600519 002371')
    parser.add_argument('--stats', action='store_true', help='只显示市场统计')
    parser.add_argument('--limit-up', action='store_true', help='涨停板列表')
    parser.add_argument('--strong', action='store_true', help='强势股(+5%~+9.9%)')
    parser.add_argument('--min-turnover', type=float, default=0, help='最低成交额(亿)')
    parser.add_argument('--min-cap', type=float, default=0, help='最低市值(亿)')
    parser.add_argument('--test-blocker', action='store_true', help='测试yfinance拦截器')
    args = parser.parse_args()

    if args.test_blocker:
        print('测试yfinance拦截器...')
        try:
            import yfinance as yf
            yf.Ticker('600519.SS')
            print('❌ 拦截失败!')
        except RuntimeError as e:
            print(f'✅ 拦截成功:\n{e}')
        try:
            import yfinance as yf
            yf.Ticker('AAPL')
            print('✅ 美股不受影响')
        except RuntimeError:
            print('❌ 美股被误拦!')
        sys.exit(0)

    if args.tickers:
        print(f'查询 {len(args.tickers)} 只...')
        results = get_batch_prices(args.tickers)
        for code, data in results.items():
            if data.get('price'):
                print(f"  {data.get('name','?'):8s} {code} | ¥{data['price']:.2f} | "
                      f"{data.get('change_pct',0):+.2f}%")
            else:
                print(f"  {code}: {data.get('error', 'no data')}")
        sys.exit(0)

    print('正在获取全量A股数据 (push2delay.eastmoney.com)...')
    t0 = time.time()
    stocks = get_full_market()
    elapsed = time.time() - t0
    print(f'获取完成: {len(stocks)} 只, 耗时 {elapsed:.1f}秒\n')

    stats = get_market_stats(stocks)
    print(f"{'='*60}")
    print(f"  A股全量统计 | {datetime.now(TZ_BEIJING).strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    print(f"  总数: {stats['total']} | 涨: {stats['up']} | 跌: {stats['down']} | 平: {stats['flat']}")
    print(f"  涨停: {stats['limit_up_total']} (20cm: {stats['limit_up_20']} + 10cm: {stats['limit_up_10']}) | 跌停: {stats['limit_down']}")
    print(f"  成交额: {stats['turnover_trillion']}万亿")
    print()

    if args.stats:
        sys.exit(0)

    if args.limit_up:
        limits = get_limit_up_stocks(stocks)
        print(f"=== 20cm涨停 ({len(limits['20cm'])}只) ===")
        for i, s in enumerate(limits['20cm'][:30]):
            print(f"  {i+1:2d}. {s['name']:10s} {s['code']:6s} | ¥{s['price'] or 0:>8.2f} | "
                  f"{s.get('change_pct',0):>+7.2f}% | 成交{s['turnover']:>6.1f}亿 | 市值{s['market_cap']:>7.0f}亿")
        print(f"\n=== 10cm涨停 ({len(limits['10cm'])}只, TOP30) ===")
        for i, s in enumerate(limits['10cm'][:30]):
            print(f"  {i+1:2d}. {s['name']:10s} {s['code']:6s} | ¥{s['price'] or 0:>8.2f} | "
                  f"{s.get('change_pct',0):>+7.2f}% | 成交{s['turnover']:>6.1f}亿 | 市值{s['market_cap']:>7.0f}亿")
        sys.exit(0)

    if args.strong:
        strong = get_strong_movers(
            min_turnover=args.min_turnover or 5.0,
            min_market_cap=args.min_cap or 100.0,
            stocks=stocks,
        )
        print(f"=== 强势股 +5%~+9.9% ({len(strong)}只, 成交>={args.min_turnover or 5}亿, 市值>={args.min_cap or 100}亿) ===")
        for i, s in enumerate(strong[:40]):
            print(f"  {i+1:2d}. {s['name']:10s} {s['code']:6s} | ¥{s['price'] or 0:>8.2f} | "
                  f"{s.get('change_pct',0):>+7.2f}% | 成交{s['turnover']:>6.1f}亿 | 市值{s['market_cap']:>7.0f}亿")
        sys.exit(0)

    # Default: top movers
    top = get_top_movers(
        n=args.top,
        min_turnover=args.min_turnover,
        min_market_cap=args.min_cap,
        stocks=stocks,
    )
    print(f"=== 涨幅TOP{args.top} ===")
    for i, s in enumerate(top):
        print(f"  {i+1:2d}. {s['name']:10s} {s['code']:6s} | ¥{s['price'] or 0:>8.2f} | "
              f"{s.get('change_pct',0):>+7.2f}% | 成交{s['turnover']:>6.1f}亿 | 市值{s['market_cap']:>7.0f}亿")
