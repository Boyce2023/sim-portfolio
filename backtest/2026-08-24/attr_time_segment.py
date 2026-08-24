import json
with open('/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json') as f:
    PS = json.load(f)
snaps = [s for s in PS['performance']['daily_snapshots'] if '2026-06-24' <= s['date'] <= '2026-08-24']
snaps.sort(key=lambda x: x['date'])

print(f"{'date':12s} {'nav':>13s} {'dNAV':>12s} {'dNAV%':>7s} {'sse_ret%':>9s}")
prev = None
month_pnl = {}
for s in snaps:
    nav = s['a_share_nav']
    d = nav - prev if prev is not None else 0
    dpct = d/prev*100 if prev else 0
    mo = s['date'][:7]
    month_pnl[mo] = month_pnl.get(mo,0) + d
    print(f"{s['date']:12s} {nav:13,.0f} {d:12,.0f} {dpct:6.2f}% {s.get('sse_today_pct','' ) if s.get('sse_today_pct') is not None else '':>9}")
    prev = nav

print("\n--- 月度NAV变化(A股book) ---")
for mo, v in sorted(month_pnl.items()):
    print(mo, f"¥{v:,.0f}")

# find worst single-day / worst 5-day rolling window
daily = []
prev=None
for s in snaps:
    nav=s['a_share_nav']
    if prev is not None:
        daily.append((s['date'], nav-prev))
    prev=nav

daily_sorted = sorted(daily, key=lambda x: x[1])
print("\n--- 最差5个交易日(单日NAV变化) ---")
for d,v in daily_sorted[:5]:
    print(d, f"¥{v:,.0f}")

# rolling 5-day sum
print("\n--- 最差滚动5日窗口 ---")
best_window=None
for i in range(len(daily)-4):
    window = daily[i:i+5]
    s = sum(v for _,v in window)
    if best_window is None or s < best_window[0]:
        best_window = (s, window[0][0], window[-1][0])
print(f"{best_window[1]} ~ {best_window[2]}: ¥{best_window[0]:,.0f}")
