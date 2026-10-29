#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股价格数据缺口守卫 (2026-09-01 建, 2026-10-29 拆分为持仓个股硬阻断与宏观期货软提示)

背景与分层设计:
1. 2026-09-01 事故: 数据源偶发漏掉单日收盘价时, 直接取最后两根非空日线会把跨两日涨跌误算成单日涨跌。
2. 2026-10-26~28 教训: 美元指数(DX-Y.NYB)与黄金期货(GC=F)交易结算日历与美股(SPY)不同,
   旧版把期货与13只持仓个股混在同一退出码1里, 导致期货日历差异常年误报退出码1, 反而掩盖了
   个股目标交易日收盘价是否真正完备的硬校验。
3. 现行分层语义(CLI 退出码):
   - 退出码 0: 全部美股持仓个股在窗口内无交易日缺口, 且已包含最近一个应落盘美股交易日收盘价
               (宏观期货若有日历差异仅打印 [软提示], 不阻断持仓复核)。
   - 退出码 1: [硬阻断] 任一美股持仓个股存在交易日缺口, 或基准/持仓尚未落盘最近美股交易日收盘价。
   - 退出码 2: 守卫自身无法完成检查(持仓文件读取失败或基准 SPY 整列缺失)。
"""
import argparse
import datetime
import json
import os
import sys
import warnings

import pandas as pd

warnings.filterwarnings('ignore')

BENCH = 'SPY'
MACRO_AUX_TICKERS = ('DX-Y.NYB', 'GC=F', 'GDX', '^TNX')
REPO_ROOT = os.path.expanduser('~/claude-projects/sim-portfolio')


def _load_us_holidays() -> set[str]:
    """从 market_calendar.json 读取美股休市日列表, 失败时回退内置2026休市表。"""
    fallback = {
        '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25',
        '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
    }
    cal_path = os.path.join(REPO_ROOT, 'market_calendar.json')
    try:
        with open(cal_path, encoding='utf-8') as f:
            mc = json.load(f)
        items = mc.get('holidays_2026', {}).get('us', [])
        dates = {str(x.get('date')).strip() for x in items if x.get('date')}
        return dates or fallback
    except Exception:
        return fallback


def expected_latest_us_close_date(now_et: datetime.datetime | None = None) -> str:
    """计算当前时刻美股最近一个应已收盘落盘的交易日(美东 16:35 后算当日, 否则回退上一交易日)。"""
    import zoneinfo
    if now_et is None:
        now_et = datetime.datetime.now(zoneinfo.ZoneInfo('America/New_York'))
    holidays = _load_us_holidays()
    d = now_et.date()
    if (now_et.hour, now_et.minute) < (16, 35):
        d -= datetime.timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in holidays:
        d -= datetime.timedelta(days=1)
    return d.isoformat()


def fetch_aligned(tickers, days=10, bench=BENCH):
    """按基准日历对齐取价, 返回 (df, report)。保留原签名兼容所有库调用方。"""
    import yfinance as yf
    tk = list(dict.fromkeys(list(tickers) + [bench]))
    raw = yf.download(tk, period=f'{days}d', progress=False, auto_adjust=True, threads=True)
    if raw is None or raw.empty or 'Close' not in raw:
        return pd.DataFrame(), {'ok': False, 'reason': '行情下载返回空表', 'gap_tickers': {}}
    df = raw['Close']
    if isinstance(df, pd.Series):
        df = df.to_frame(name=tk[0])
    if bench not in df.columns or df[bench].dropna().empty:
        return df, {'ok': False, 'reason': f'基准 {bench} 取不到收盘序列, 无法定义美股交易日', 'gap_tickers': {}}

    cal = set(df[bench].dropna().index)
    cal_days = sorted(str(d.date()) for d in cal)
    gaps = {}
    for t in tickers:
        if t not in df.columns or df[t].dropna().empty:
            gaps[t] = ['<整列缺失>']
            continue
        miss = sorted(cal - set(df[t].dropna().index))
        if miss:
            gaps[t] = [str(d.date()) for d in miss]
    return df, {
        'ok': not gaps,
        'cal_days': cal_days,
        'latest_cal_day': cal_days[-1] if cal_days else None,
        'gap_tickers': gaps,
    }


def day_change(df, ticker, report, bench=BENCH):
    """返回 (单日涨跌%, 是否可信)。前一交易日缺失则标不可信。"""
    cal = sorted(set(df[bench].dropna().index))
    if len(cal) < 2:
        return None, False
    last, prev = cal[-1], cal[-2]
    ser = df[ticker]
    cur = ser.get(last)
    pv = ser.get(prev)
    if pd.isna(cur):
        return None, False
    if pd.isna(pv):
        s = ser.dropna()
        s = s[s.index < last]
        if s.empty:
            return None, False
        return (float(cur) / float(s.iloc[-1]) - 1) * 100, False
    return (float(cur) / float(pv) - 1) * 100, True


def assert_trigger_safe(report, needed):
    """判定前调用: 所需标的有缺口即抛错中止, 严禁静默算跨日涨跌。"""
    bad = {t: v for t, v in report.get('gap_tickers', {}).items() if t in needed}
    if bad:
        raise SystemExit(
            "⛔ 中止判定: 相关标的价格存在交易日缺口, 算出的单日涨跌实为跨多日。\n"
            f"   缺口明细: {bad}\n"
            "   处理: 核实该日真实收盘或等待数据源补齐, 严禁带缺口出结论。"
        )


def main():
    ap = argparse.ArgumentParser(description='美股价格缺口守卫(持仓个股硬阻断 + 宏观期货软提示)')
    ap.add_argument('--tickers', help='逗号分隔自定义标的(传入时全部按硬阻断校验)')
    ap.add_argument('--days', type=int, default=10, help='回看日历窗口天数(默认10)')
    ap.add_argument('--equities-only', action='store_true', help='仅检查美股持仓个股, 跳过宏观期货软提示')
    a = ap.parse_args()

    if a.tickers:
        equity_tickers = [x.strip() for x in a.tickers.split(',') if x.strip()]
        macro_tickers = []
    else:
        pf = os.path.join(REPO_ROOT, 'portfolio_state.json')
        try:
            with open(pf, encoding='utf-8') as f:
                st = json.load(f)
            equity_tickers = [p['ticker'] for p in st['accounts']['us']['positions']]
        except Exception as e:
            print(f"⛔ 无法读取美股持仓({type(e).__name__}), 守卫异常退出")
            return 2
        if not equity_tickers:
            print("⛔ 美股持仓列表为空, 守卫异常退出")
            return 2
        macro_tickers = [] if a.equities_only else [t for t in MACRO_AUX_TICKERS if t not in equity_tickers]

    all_tickers = list(dict.fromkeys(equity_tickers + macro_tickers))
    df, rep = fetch_aligned(all_tickers, days=a.days)
    if not rep.get('ok', True) and not rep.get('gap_tickers'):
        print(f"⛔ 守卫取数失败: {rep.get('reason', '未知原因')}")
        return 2

    expected_close = expected_latest_us_close_date()
    latest_cal = rep.get('latest_cal_day')
    gaps = rep.get('gap_tickers', {})

    equity_set = set(equity_tickers)
    equity_gaps = {t: d for t, d in gaps.items() if t in equity_set}
    macro_gaps = {t: d for t, d in gaps.items() if t not in equity_set}

    bench_lagging = bool(latest_cal and latest_cal < expected_close)
    # 额外逐只核对目标交易日收盘价是否非空
    missing_target_close = []
    if latest_cal:
        for t in equity_tickers:
            if t not in df.columns:
                missing_target_close.append(t)
                continue
            s = df[t].dropna()
            last_t = str(s.index[-1].date()) if not s.empty else None
            if last_t != latest_cal:
                missing_target_close.append(f"{t}(停在{last_t})")

    print(
        f"检查持仓个股 {len(equity_tickers)} 只 + 宏观观察 {len(macro_tickers)} 项 "
        f"| 窗口 {a.days} 天 | 基准 {BENCH} 最新日 {latest_cal} (应到 {expected_close})"
    )

    if bench_lagging or equity_gaps or missing_target_close:
        print("⛔ [硬阻断] 美股持仓个股收盘价不完备, 禁止生成正式调仓裁决:")
        if bench_lagging:
            print(f"   基准滞后: {BENCH} 最新日线停在 {latest_cal}, 尚未落盘目标交易日 {expected_close}")
        for t, d in equity_gaps.items():
            print(f"   持仓缺口: {t} 缺失交易日 {d}")
        if missing_target_close and not equity_gaps:
            print(f"   目标日缺失: {missing_target_close}")
        if macro_gaps:
            print(f"   (附宏观期货日历差异: {macro_gaps})")
        return 1

    if macro_gaps:
        print("⚠️ [软提示] 宏观或期货结算日历差异(不阻断美股持仓复核):")
        for t, d in macro_gaps.items():
            print(f"   {t}: 相对 {BENCH} 日历缺 {d}")

    print(f"✅ {len(equity_tickers)}/{len(equity_tickers)} 只美股持仓目标交易日({latest_cal})收盘价完备, 放行复核")
    return 0


if __name__ == '__main__':
    sys.exit(main())
