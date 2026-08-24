#!/usr/bin/env python3
"""
T18 五道门审判: 门①(破前10日低) + 门③(round-trip峰值+15%吐回成本) 实证价值检验
数据源: portfolio_state.json trade_log (a_share) + akshare kline (ak CLI, 不复权, 与成本口径一致)
窗口: 2026-06-24 ~ 2026-08-24
落盘: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/t18_gate13_backtest.py
"""
import json, subprocess, sys, statistics as st

AK = "/Users/huaichuaibeimeng/.claude/skills/akshare-china/scripts/ak"
STATE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json"
WINDOW_START = "2026-06-24"
TODAY = "2026-08-24"
EXIT_N = 10
RT_PEAK = 0.15
RT_GIVE = 0.0

def load_trades():
    d = json.load(open(STATE))
    return [t for t in d['trade_log'] if t.get('account') == 'a_share']

def build_periods(trades):
    trades = sorted(trades, key=lambda t: (t['date'], t['id']))
    pos = {}
    open_period = {}
    periods = []
    for t in trades:
        tk = t['ticker']; act = t['action']; date = t['date']
        shares = t['shares']; price = t['price']
        if tk not in pos:
            pos[tk] = {'shares': 0, 'cost_total': 0.0}
        p = pos[tk]
        if act == 'buy':
            if p['shares'] == 0:
                op = {'ticker': tk, 'name': t.get('name', tk), 'entry_date': date,
                      'exit_date': None, 'exit_price': None, 'buys': [], 'sells': []}
                open_period[tk] = op
                periods.append(op)
            p['cost_total'] += shares * price
            p['shares'] += shares
            if tk in open_period:
                open_period[tk]['buys'].append((date, shares, price))
        elif act == 'sell':
            if tk in open_period:
                open_period[tk]['sells'].append((date, shares, price))
            p['shares'] -= shares
            if p['shares'] <= 0:
                p['shares'] = 0
                p['cost_total'] = 0.0
                if tk in open_period:
                    op = open_period[tk]
                    op['exit_date'] = date
                    # weighted sell price of the sells that closed it (last day's sells)
                    last_day_sells = [s for s in op['sells'] if s[0] == date]
                    tot_sh = sum(s[1] for s in last_day_sells)
                    op['exit_price'] = (sum(s[1]*s[2] for s in last_day_sells)/tot_sh) if tot_sh else None
                    del open_period[tk]
    return periods

def relevant(periods):
    out = []
    for p in periods:
        if p['exit_date'] is not None and p['exit_date'] < WINDOW_START:
            continue
        out.append(p)
    return out

def fetch_kline(ticker, n=160):
    try:
        r = subprocess.run([AK, "kline", ticker, str(n), "--json"],
                            capture_output=True, text=True, timeout=30)
        d = json.loads(r.stdout)
        rows = d if isinstance(d, list) else (d.get('data') or d.get('kline') or [])
        bars = []
        for row in rows:
            try:
                bars.append({
                    'd': str(row.get('day') or row.get('date') or row.get('日期'))[:10],
                    'o': float(row.get('open') or row.get('开盘')),
                    'h': float(row.get('high') or row.get('最高')),
                    'l': float(row.get('low') or row.get('最低')),
                    'c': float(row.get('close') or row.get('收盘')),
                })
            except Exception:
                continue
        bars.sort(key=lambda x: x['d'])
        return bars
    except Exception as e:
        print(f"  !! kline fetch fail {ticker}: {e}", file=sys.stderr)
        return []

def cost_asof(period, date):
    """weighted avg cost using buys with date <= given date"""
    buys = [b for b in period['buys'] if b[0] <= date]
    if not buys:
        buys = period['buys'][:1]
    tot_sh = sum(b[1] for b in buys)
    tot_cost = sum(b[1]*b[2] for b in buys)
    return tot_cost / tot_sh if tot_sh else None

def simulate(period, bars):
    """returns dict of per-door trigger info + retrace-variant triggers"""
    dates = [b['d'] for b in bars]
    idx = {d: i for i, d in enumerate(dates)}
    entry_date = period['entry_date']
    exit_date = period['exit_date']
    test_start = max(entry_date, WINDOW_START)
    test_end = exit_date if exit_date else TODAY
    test_end = min(test_end, TODAY)

    result = {
        'gate1_trigger': None,   # (date, close, low10)
        'gate3_trigger': None,   # (date, close, cost, peak_pct)
        'gate1_days_tested': 0,
        'gate3_days_tested': 0,
        'retrace': {10: None, 15: None, 20: None},  # pure peak-retrace, cost-independent
    }
    if entry_date not in idx and entry_date < dates[0] if dates else True:
        pass  # entry may be before our fetched window; fine, we just need enough trailing data

    running_peak_high = None  # for retrace variant, tracks max high since entry_date (cost independent)
    peak_armed = {10: False, 15: False, 20: False}  # arm only after price has moved up at all (peak>entry close) - keep simple: track peak from entry regardless

    for d in dates:
        if d < entry_date:
            continue
        if d > test_end:
            break
        i = idx[d]
        # need at least EXIT_N prior bars for low10
        if i - EXIT_N < 0:
            prior_avail = i
        cur_close = bars[i]['c']
        cur_high = bars[i]['h']

        # running peak high since entry (for retrace variant, cost independent)
        if running_peak_high is None:
            running_peak_high = cur_high
        else:
            running_peak_high = max(running_peak_high, cur_high)

        if d < test_start:
            continue  # don't record triggers before window start, but keep peak accumulating

        # --- gate 1: break prior EXIT_N-day low (using trailing bars, close < min(low) of prior N bars excl today) ---
        if i >= EXIT_N:
            low10 = min(bars[j]['l'] for j in range(i-EXIT_N, i))
            result['gate1_days_tested'] += 1
            if result['gate1_trigger'] is None and cur_close < low10:
                result['gate1_trigger'] = (d, cur_close, low10)

        # --- gate 3: round-trip from cost ---
        cps = cost_asof(period, d)
        if cps:
            hold_bars_idx = [j for j in range(len(bars)) if entry_date <= bars[j]['d'] <= d]
            if hold_bars_idx:
                peak_pct = max(bars[j]['h'] for j in hold_bars_idx) / cps - 1
                g = cur_close / cps - 1
                result['gate3_days_tested'] += 1
                if result['gate3_trigger'] is None and peak_pct >= RT_PEAK and g <= RT_GIVE:
                    result['gate3_trigger'] = (d, cur_close, cps, peak_pct)

        # --- retrace variant (cost independent): trigger when close <= running_peak_high*(1-X%) ---
        for X in (10, 15, 20):
            if result['retrace'][X] is None:
                retr = (running_peak_high - cur_close) / running_peak_high
                if retr >= X/100.0:
                    result['retrace'][X] = (d, cur_close, running_peak_high, retr)

    return result

def price_after(bars, from_date, to_date):
    """simulate holding from from_date's close forward to to_date; return the close on to_date if available else last available <= to_date"""
    cands = [b for b in bars if from_date <= b['d'] <= to_date]
    if not cands:
        return None
    return cands[-1]['c']

def main():
    trades = load_trades()
    periods = relevant(build_periods(trades))
    tickers = sorted(set(p['ticker'] for p in periods))
    print(f"# relevant holding periods: {len(periods)}  distinct tickers: {len(tickers)}", file=sys.stderr)

    kdata = {}
    for tk in tickers:
        bars = fetch_kline(tk, 160)
        kdata[tk] = bars
        print(f"  fetched {tk}: {len(bars)} bars ({bars[0]['d'] if bars else '?'} ~ {bars[-1]['d'] if bars else '?'})", file=sys.stderr)

    rows = []
    for p in periods:
        bars = kdata.get(p['ticker'], [])
        if len(bars) < EXIT_N + 5:
            print(f"  skip {p['ticker']} {p['entry_date']}: insufficient kline ({len(bars)})", file=sys.stderr)
            continue
        sim = simulate(p, bars)

        actual_end_date = p['exit_date'] if p['exit_date'] else TODAY
        actual_end_price = p['exit_price'] if p['exit_price'] else None
        if actual_end_price is None:
            # still open -> use last available close <= TODAY
            avail = [b for b in bars if b['d'] <= TODAY]
            actual_end_price = avail[-1]['c'] if avail else None

        row = {
            'ticker': p['ticker'], 'name': p['name'], 'entry_date': p['entry_date'],
            'exit_date': p['exit_date'], 'exit_price': p['exit_price'],
            'still_open': p['exit_date'] is None,
            'entry_cost0': p['buys'][0][2] if p['buys'] else None,
        }

        for gate_key, trig_key in (('gate1', 'gate1_trigger'), ('gate3', 'gate3_trigger')):
            trig = sim[trig_key]
            if trig is None:
                row[f'{gate_key}_triggered'] = False
                continue
            tdate, tclose = trig[0], trig[1]
            row[f'{gate_key}_triggered'] = True
            row[f'{gate_key}_trigger_date'] = tdate
            row[f'{gate_key}_trigger_close'] = tclose
            if gate_key == 'gate1':
                row['gate1_low10'] = trig[2]
            else:
                row['gate3_cost_at_trigger'] = trig[2]
                row['gate3_peak_pct_at_trigger'] = trig[3]
            # actual continuation price after trigger date through actual_end_date
            cont_price = price_after(bars, tdate, actual_end_date)
            if cont_price is None:
                cont_price = actual_end_price
            row[f'{gate_key}_actual_cont_price'] = cont_price
            # pct diff: (actual_cont - trigger_close)/trigger_close; negative = gate saved you that pct, positive = gate cost you that pct
            row[f'{gate_key}_pct_diff_vs_trigger'] = (cont_price / tclose - 1) if tclose else None

        for X in (10, 15, 20):
            trig = sim['retrace'][X]
            if trig is None:
                row[f'retrace{X}_triggered'] = False
                continue
            tdate, tclose, peakhigh, retr = trig
            row[f'retrace{X}_triggered'] = True
            row[f'retrace{X}_trigger_date'] = tdate
            row[f'retrace{X}_trigger_close'] = tclose
            cont_price = price_after(bars, tdate, actual_end_date)
            if cont_price is None:
                cont_price = actual_end_price
            row[f'retrace{X}_actual_cont_price'] = cont_price
            row[f'retrace{X}_pct_diff_vs_trigger'] = (cont_price / tclose - 1) if tclose else None

        row['actual_end_date'] = actual_end_date
        row['actual_end_price'] = actual_end_price
        rows.append(row)

    out_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/t18_gate13_result.json"
    json.dump(rows, open(out_path, 'w'), ensure_ascii=False, indent=2)
    print(f"\n# wrote {len(rows)} rows to {out_path}", file=sys.stderr)

if __name__ == '__main__':
    main()
