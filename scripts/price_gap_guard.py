# -*- coding: utf-8 -*-
"""价格数据缺口守卫 (2026-09-01)

起因: yfinance 在 09-01 对 16 只持仓中的 15 只缺失 08-28 收盘。
若直接用 dropna().iloc[-2] 当"前一日", 算出的是**两日涨跌**却被当成单日,
金对簇因此显示 -3.75%(越过-3%门槛) 而真实单日仅约 -0.8% —— **差一点触发一次假减仓**。

用法:
    from price_gap_guard import fetch_aligned
    df, report = fetch_aligned(tickers, days=10)
    if report['gap_tickers']: ...  # 有缺口时禁止用于扳机判定
"""
import warnings, pandas as pd
warnings.filterwarnings('ignore')

BENCH = 'SPY'   # 用SPY定义"哪些天是交易日"

def fetch_aligned(tickers, days=10, bench=BENCH):
    """按基准日历对齐取价, 返回(df, report)。report标明每只缺了哪些交易日。"""
    import yfinance as yf
    tk = list(dict.fromkeys(list(tickers) + [bench]))
    df = yf.download(tk, period=f'{days}d', progress=False, auto_adjust=True, threads=True)['Close']
    if bench not in df.columns or df[bench].dropna().empty:
        return df, {'ok': False, 'reason': f'基准{bench}取不到, 无法定义交易日', 'gap_tickers': {}}
    cal = set(df[bench].dropna().index)
    gaps = {}
    for t in tickers:
        if t not in df.columns:
            gaps[t] = ['<整列缺失>']; continue
        miss = sorted(cal - set(df[t].dropna().index))
        if miss: gaps[t] = [str(d.date()) for d in miss]
    return df, {'ok': not gaps, 'cal_days': sorted(str(d.date()) for d in cal), 'gap_tickers': gaps}

def day_change(df, ticker, report, bench=BENCH):
    """返回(涨跌%, 是否可信)。前一交易日缺失 → 不可信, 调用方禁止拿去判扳机。"""
    cal = sorted(set(df[bench].dropna().index))
    if len(cal) < 2: return None, False
    last, prev = cal[-1], cal[-2]
    ser = df[ticker]
    cur = ser.get(last)
    pv = ser.get(prev)
    if pd.isna(cur): return None, False
    if pd.isna(pv):
        s = ser.dropna(); s = s[s.index < last]
        if s.empty: return None, False
        return (float(cur)/float(s.iloc[-1])-1)*100, False    # ⚠️跨多日, 不可信
    return (float(cur)/float(pv)-1)*100, True

def assert_trigger_safe(report, needed):
    """扳机判定前调用: 相关标的有缺口就抛错, 不许静默出信号。"""
    bad = {t: v for t, v in report['gap_tickers'].items() if t in needed}
    if bad:
        raise SystemExit(
            "⛔ 中止扳机判定: 相关标的价格有交易日缺口, 算出的'单日涨跌'实为跨多日, 会造成假信号。\n"
            f"   缺口: {bad}\n"
            "   处理: 换数据源核实该日收盘, 或等数据源补齐; ⛔不得用带缺口的读数减仓。")
