#!/usr/bin/env python3
"""
tree_coverage_backtest.py · 2026-08-14 · 重建任务B2历史回溯验证
────────────────────────────────────────────────────────────────────────────
验证对象: tree_anomaly_scan.py新增的覆盖率修复三件套(per_tree_top/compute_tree_stats/
diffusion_watch)相对旧版"纯全局Top N"能不能捕获 2026-07-24~08-13 区间内那15只
"Top30机会里全区间从未被扫到"的票。

方法: 对映射内851只ticker各拉一份~1年日K(新浪, 复用tree_anomaly_scan.fetch_kline_sina),
对窗口内每个真实交易日D, 把每只票的K线截断到"d<=D"重算compute_signals(等价于"如果
D那天收盘后跑一次scan()会看到什么"), 分别用旧方法(全局Top40)和新方法(每链Top5 ∪
滞涨扩散候选)看谁先捕获这15只目标票, 在哪天捕获、捕获时这只票已经涨了多少(捕获早晚
决定这个信号有没有操作价值)。

⛔数据源: 与tree_anomaly_scan.py一致, 仅新浪日K(不含未收盘当日, 回溯不需要)。
⛔不引入新数据源, 直接import并复用tree_anomaly_scan的函数, 逻辑与生产版本100%一致。

用法:
  export NO_PROXY='*'
  python3 tree_coverage_backtest.py                    # 默认回溯2026-07-24~2026-08-13
  python3 tree_coverage_backtest.py --start 2026-07-24 --end 2026-08-13
  python3 tree_coverage_backtest.py --json > /tmp/backtest.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault('NO_PROXY', '*')
os.environ.setdefault('no_proxy', '*')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tree_anomaly_scan as tas  # noqa: E402

# 15只已实证"07-24~08-13全区间从未被扫到"的票(任务B2背景给定, 全部在映射范围内)
TARGETS = {
    '301080': ('百普赛斯', '+68.9%'),
    '301230': ('泓博医药', '+58.1%'),
    '688596': ('正帆科技', '+48.5%'),
    '688222': ('成都先导', '+44.3%'),
    '603011': ('合锻智能', '+39.5%'),
    '300620': ('光库科技', '+36.6%'),
    '300244': ('迪安诊断', '+35.1%'),
    '301333': ('诺思格', '+33.4%'),
    '002149': ('西部材料', '+33.3%'),
    '000048': ('京基智农', '+32.2%'),
    '300740': ('水羊股份', '+32.2%'),
    '002896': ('中大力德', '+31.5%'),
    '603456': ('九洲药业', '+30.6%'),
    '688202': ('美迪西', '+30.2%'),
    '300401': ('花园生物', '+30.2%'),
}

OLD_TOP_N = 40   # 对齐prompts/astock_scan_sop.md Step2实际使用的命令 `--top 40`
NEW_PER_TREE_N = 5
NEW_HOT_SCORE_MIN = 20.0


def fetch_all_klines(codes: list[str], n: int = 260, workers: int = 15) -> dict[str, list[dict]]:
    kmap: dict[str, list[dict]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(tas.fetch_kline_sina, c, n, 10, 1): c for c in codes}
        for fut in as_completed(futs):
            code = futs[fut]
            try:
                kmap[code] = fut.result()
            except Exception:
                kmap[code] = []
            done += 1
            if done % 200 == 0:
                print(f'  ...K线拉取 {done}/{len(codes)}', file=sys.stderr, flush=True)
    return kmap


def trading_days_in_window(kmap: dict[str, list[dict]], start: str, end: str,
                            min_coverage: int = 400) -> list[str]:
    """从实际K线数据里反推窗口内真实交易日(而非硬编码日历), 只保留被>=min_coverage只
    股票同时报出的日期(排除个别停牌/退市/次新股污染日期集合)。"""
    cnt: Counter[str] = Counter()
    for bars in kmap.values():
        for b in bars:
            if start <= b['d'] <= end:
                cnt[b['d']] += 1
    days = sorted(d for d, c in cnt.items() if c >= min_coverage)
    return days


def sort_key(r: dict):
    return (r.get('异动强度') is None, -(r.get('异动强度') or 0))


def build_results_asof(entries: list[dict], kmap: dict[str, list[dict]], day: str) -> list[dict]:
    """等价于scan()在day收盘后跑一次的产出, 但用snap=None(回溯没有实时快照,
    今日涨跌%退化为K线收盘比, 与compute_signals()文档注明的退化路径一致)。"""
    out: list[dict] = []
    for e in entries:
        code = e['ticker']
        bars = kmap.get(code) or []
        bars_trunc = [b for b in bars if b['d'] <= day]
        if len(bars_trunc) < 2:
            continue
        sig = tas.compute_signals(bars_trunc, snap=None)
        if sig.get('_insufficient'):
            continue
        out.append({'ticker': code, 'name': e.get('name'), 'tree': e.get('tree'),
                     'node': e.get('node'), **sig})
    out.sort(key=sort_key)
    return out


def run_backtest(start: str, end: str, kline_n: int = 260) -> dict:
    entries = tas.load_tree_map(tas.TREE_MAP_PATH_DEFAULT)
    if entries is None:
        print('产品树映射文件不存在, 无法回溯', file=sys.stderr)
        sys.exit(1)
    codes = sorted({e['ticker'] for e in entries})
    print(f'映射: {len(entries)}条entries / {len(codes)}只unique ticker', file=sys.stderr)

    t0 = time.time()
    kmap = fetch_all_klines(codes, n=kline_n)
    print(f'K线拉取完成, 耗时{time.time() - t0:.1f}s, 成功{sum(1 for v in kmap.values() if v)}/{len(codes)}',
          file=sys.stderr)

    days = trading_days_in_window(kmap, start, end)
    print(f'窗口内识别到{len(days)}个真实交易日: {days}', file=sys.stderr)
    if not days:
        print('窗口内无可用交易日, 检查K线数据/日期范围', file=sys.stderr)
        sys.exit(1)

    # baseline价(窗口开始前最后一根收盘, 用于计算"捕获时已经涨了多少")
    baseline_day = None
    for bars in kmap.values():
        for b in bars:
            if b['d'] < start:
                if baseline_day is None or b['d'] > baseline_day:
                    baseline_day = b['d']
    baseline_price: dict[str, float | None] = {}
    for code, bars in kmap.items():
        p = None
        for b in bars:
            if b['d'] <= (baseline_day or start):
                p = b['c']
        baseline_price[code] = p

    capture_old: dict[str, dict] = {}   # code -> {'day':..., 'move_at_capture_pct':...}
    capture_new: dict[str, dict] = {}
    capture_new_via: dict[str, str] = {}  # 'per_tree_top' / 'diffusion_watch' / 'both'
    daily_log: list[dict] = []

    for day in days:
        results_d = build_results_asof(entries, kmap, day)
        if not results_d:
            continue

        old_top = results_d[:OLD_TOP_N]
        old_tickers = {r['ticker'] for r in old_top}

        tstats_d = tas.compute_tree_stats(results_d)
        ptop_d = tas.per_tree_top(results_d, NEW_PER_TREE_N)
        ptop_tickers = {r['ticker'] for rows in ptop_d.values() for r in rows}
        dwatch_d = tas.diffusion_watch(results_d, tstats_d, hot_score_min=NEW_HOT_SCORE_MIN)
        dwatch_tickers = {r['ticker'] for r in dwatch_d}
        new_tickers = ptop_tickers | dwatch_tickers

        daily_log.append({
            'day': day, 'old_top_n': len(old_tickers),
            'new_per_tree_n': len(ptop_tickers), 'new_diffusion_n': len(dwatch_tickers),
            'new_union_n': len(new_tickers),
        })

        for code in TARGETS:
            if code not in {e['ticker'] for e in entries}:
                continue
            price_now = baseline_price.get(code)
            bars_code = kmap.get(code) or []
            close_today = next((b['c'] for b in reversed(bars_code) if b['d'] <= day), None)
            move_pct = (round((close_today / price_now - 1) * 100, 1)
                        if price_now and close_today else None)

            if code in old_tickers and code not in capture_old:
                capture_old[code] = {'day': day, 'move_at_capture_pct': move_pct}
            if code in new_tickers and code not in capture_new:
                capture_new[code] = {'day': day, 'move_at_capture_pct': move_pct}
                via = []
                if code in ptop_tickers:
                    via.append('per_tree_top')
                if code in dwatch_tickers:
                    via.append('diffusion_watch')
                capture_new_via[code] = '+'.join(via)

    # 窗口末尾实际累计涨幅(脚本自算, 供与任务背景给定的%对照; baseline定义可能与
    # 背景数字的口径不完全一致, 此处明确标注为"脚本口径", 不覆盖背景给定的事实数字)
    final_move: dict[str, float | None] = {}
    for code in TARGETS:
        price0 = baseline_price.get(code)
        bars_code = kmap.get(code) or []
        close_end = next((b['c'] for b in reversed(bars_code) if b['d'] <= end), None)
        final_move[code] = (round((close_end / price0 - 1) * 100, 1)
                             if price0 and close_end else None)

    return {
        'window': {'start': start, 'end': end, 'baseline_day': baseline_day,
                   'trading_days': days},
        'daily_log': daily_log,
        'capture_old': capture_old,
        'capture_new': capture_new,
        'capture_new_via': capture_new_via,
        'final_move_script_calc': final_move,
    }


def print_report(res: dict) -> None:
    targets = TARGETS
    old_hit = res['capture_old']
    new_hit = res['capture_new']
    n = len(targets)

    print('=' * 100)
    print(f'历史回溯 {res["window"]["start"]} ~ {res["window"]["end"]} '
          f'(baseline={res["window"]["baseline_day"]}, {len(res["window"]["trading_days"])}个交易日)')
    print('=' * 100)
    print(f'\n旧方法(全局Top{OLD_TOP_N})捕获: {len(old_hit)}/{n} = {len(old_hit) / n * 100:.1f}%')
    print(f'新方法(每链Top{NEW_PER_TREE_N} ∪ 滞涨扩散候选)捕获: {len(new_hit)}/{n} = {len(new_hit) / n * 100:.1f}%')

    print(f'\n{"标的":<10}{"代码":<8}{"背景给定涨幅":<12}{"脚本口径涨幅":<12}'
          f'{"旧法捕获日":<12}{"旧法捕获时已涨%":<16}{"新法捕获日":<12}{"新法捕获时已涨%":<16}{"新法途径"}')
    for code, (name, given_pct) in targets.items():
        fin = res['final_move_script_calc'].get(code)
        o = old_hit.get(code)
        w = new_hit.get(code)
        via = res['capture_new_via'].get(code, '-')
        print(f'{name:<10}{code:<8}{given_pct:<12}{tas._fmt(fin):<12}'
              f'{(o["day"] if o else "未捕获"):<12}{tas._fmt(o["move_at_capture_pct"] if o else None):<16}'
              f'{(w["day"] if w else "未捕获"):<12}{tas._fmt(w["move_at_capture_pct"] if w else None):<16}{via}')

    print('\n每日候选池规模(旧法固定40 vs 新法每链Top5∪滞涨候选):')
    print(f'{"交易日":<12}{"旧法(全局Top40)":<18}{"新法-每链Top":<14}{"新法-滞涨候选":<14}{"新法-并集":<10}')
    for d in res['daily_log']:
        print(f'{d["day"]:<12}{d["old_top_n"]:<18}{d["new_per_tree_n"]:<14}{d["new_diffusion_n"]:<14}{d["new_union_n"]:<10}')


def main() -> None:
    ap = argparse.ArgumentParser(description='tree_anomaly_scan覆盖率修复历史回溯验证(任务B2)')
    ap.add_argument('--start', default='2026-07-24')
    ap.add_argument('--end', default='2026-08-13')
    ap.add_argument('--kline-days', type=int, default=260)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    res = run_backtest(args.start, args.end, kline_n=args.kline_days)

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
    print_report(res)


if __name__ == '__main__':
    main()
