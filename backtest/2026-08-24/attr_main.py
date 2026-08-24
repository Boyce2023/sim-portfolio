import json, csv
from collections import defaultdict, deque

WINDOW_START = "2026-06-24"
WINDOW_END = "2026-08-24"

# ---------- Load index series ----------
def load_index(sym):
    with open(f"attr_index_{sym}.json") as f:
        rows = json.load(f)
    d = {}
    for r in rows:
        date, o, c, h, l, v = r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])
        d[date] = c
    return d

csi300 = load_index("sh000300")
csi1000 = load_index("sh000852")

def idx_close(d, date, name):
    if date in d:
        return d[date]
    # fallback: nearest earlier date present
    dates_sorted = sorted(d.keys())
    prior = [x for x in dates_sorted if x <= date]
    if prior:
        return d[prior[-1]]
    raise KeyError(f"{name} no data for {date}")

print("CSI300 T0(06-24)=", idx_close(csi300, WINDOW_START, "csi300"), "T1(08-24)=", idx_close(csi300, WINDOW_END, "csi300"))
print("CSI1000 T0(06-24)=", idx_close(csi1000, WINDOW_START, "csi1000"), "T1(08-24)=", idx_close(csi1000, WINDOW_END, "csi1000"))

# ---------- Load portfolio_state ----------
with open("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json") as f:
    PS = json.load(f)

snaps = {s['date']: s for s in PS['performance']['daily_snapshots']}
nav_t0 = snaps[WINDOW_START]['a_share_nav']
nav_t1 = snaps[WINDOW_END]['a_share_nav']
print("NAV_T0(06-24)=", nav_t0, "NAV_T1(08-24)=", nav_t1)
print("R_total =", nav_t1/nav_t0 - 1)

tl_all = [t for t in PS['trade_log'] if t['account']=='a_share']
tl_before = [t for t in tl_all if t['date'] < WINDOW_START]
tl_window = [t for t in tl_all if WINDOW_START <= t['date'] <= WINDOW_END]
tl_window_sorted = sorted(tl_window, key=lambda x: (x['date'], x['id']))

# ---------- reconstruct legacy open positions at T0 ----------
pos_net = defaultdict(int)
name_map = {}
for t in sorted(tl_before, key=lambda x: x['date']):
    name_map[t['ticker']] = t.get('name')
    if t['action']=='buy':
        pos_net[t['ticker']] += t['shares']
    elif t['action']=='sell':
        pos_net[t['ticker']] -= t['shares']
legacy_open = {k:v for k,v in pos_net.items() if v != 0}
print("\nLegacy positions open at T0:", legacy_open)

# T0 mark prices for legacy positions (manually sourced from tencent kline, qfq/raw as noted)
T0_MARK_PRICE = {
    '688072': 820.0,     # 拓荆科技, raw close (kline_cache)
    '600309': 74.700,    # 万华化学, qfq close (attr_fetch)
    '002049': 83.334,    # 紫光国微, qfq close
    '300308': 1312.180,  # 中际旭创, qfq close
    '601899': 26.91,     # 紫金矿业, raw close (kline_cache)
    '300476': 343.430,   # 胜宏科技, qfq close
    '600150': 34.985,    # 中国船舶, qfq close
}
for tk in legacy_open:
    if tk not in T0_MARK_PRICE:
        raise SystemExit(f"MISSING T0 mark price for legacy ticker {tk}")

# ---------- FIFO lot engine ----------
# lots[ticker] = deque of {entry_date, shares, entry_price, entry_csi300, entry_csi1000}
lots = defaultdict(deque)

for tk, shares in legacy_open.items():
    lots[tk].append({
        'entry_date': WINDOW_START,
        'shares': shares,
        'entry_price': T0_MARK_PRICE[tk],
        'entry_csi300': idx_close(csi300, WINDOW_START, 'csi300'),
        'entry_csi1000': idx_close(csi1000, WINDOW_START, 'csi1000'),
        'origin': 'legacy_T0_mark',
    })

matched_records = []  # closed lots (sold within window)
current_positions_check = defaultdict(int)

for t in tl_window_sorted:
    tk = t['ticker']
    name_map[tk] = t.get('name', name_map.get(tk))
    if t['action'] == 'buy':
        lots[tk].append({
            'entry_date': t['date'],
            'shares': t['shares'],
            'entry_price': t['price'],
            'entry_csi300': idx_close(csi300, t['date'], 'csi300'),
            'entry_csi1000': idx_close(csi1000, t['date'], 'csi1000'),
            'origin': 'window_buy',
            'trade_id': t['id'],
        })
    elif t['action'] == 'sell':
        remaining_to_sell = t['shares']
        exit_price = t['price']
        exit_date = t['date']
        exit_csi300 = idx_close(csi300, exit_date, 'csi300')
        exit_csi1000 = idx_close(csi1000, exit_date, 'csi1000')
        while remaining_to_sell > 0:
            if not lots[tk]:
                raise SystemExit(f"FIFO underflow: {tk} sell more than held, trade {t['id']}")
            lot = lots[tk][0]
            chunk = min(lot['shares'], remaining_to_sell)
            entry_value = chunk * lot['entry_price']
            actual_pnl = chunk * (exit_price - lot['entry_price'])
            cf300_pnl = entry_value * (exit_csi300/lot['entry_csi300'] - 1)
            cf1000_pnl = entry_value * (exit_csi1000/lot['entry_csi1000'] - 1)
            matched_records.append({
                'ticker': tk, 'name': name_map.get(tk),
                'entry_date': lot['entry_date'], 'exit_date': exit_date,
                'shares': chunk, 'entry_price': lot['entry_price'], 'exit_price': exit_price,
                'entry_value': entry_value,
                'actual_pnl': actual_pnl, 'cf_csi300_pnl': cf300_pnl, 'cf_csi1000_pnl': cf1000_pnl,
                'origin': lot['origin'], 'status': 'closed',
            })
            lot['shares'] -= chunk
            remaining_to_sell -= chunk
            if lot['shares'] == 0:
                lots[tk].popleft()
    else:
        raise SystemExit(f"unexpected action {t['action']}")

# ---------- remaining open lots at T1 (still held 08-24) ----------
# get T1 mark price from current a_share positions (current_price) as ground truth
cur_positions = {p['ticker']: p for p in PS['accounts']['a_share']['positions']}
open_records = []
for tk, dq in lots.items():
    for lot in dq:
        if lot['shares'] == 0:
            continue
        if tk not in cur_positions:
            raise SystemExit(f"ticker {tk} has open lot but not in current positions - mismatch")
        exit_price = cur_positions[tk]['current_price']
        exit_csi300 = idx_close(csi300, WINDOW_END, 'csi300')
        exit_csi1000 = idx_close(csi1000, WINDOW_END, 'csi1000')
        entry_value = lot['shares'] * lot['entry_price']
        actual_pnl = lot['shares'] * (exit_price - lot['entry_price'])
        cf300_pnl = entry_value * (exit_csi300/lot['entry_csi300'] - 1)
        cf1000_pnl = entry_value * (exit_csi1000/lot['entry_csi1000'] - 1)
        open_records.append({
            'ticker': tk, 'name': name_map.get(tk),
            'entry_date': lot['entry_date'], 'exit_date': WINDOW_END,
            'shares': lot['shares'], 'entry_price': lot['entry_price'], 'exit_price': exit_price,
            'entry_value': entry_value,
            'actual_pnl': actual_pnl, 'cf_csi300_pnl': cf300_pnl, 'cf_csi1000_pnl': cf1000_pnl,
            'origin': lot['origin'], 'status': 'open_at_T1',
        })

all_records = matched_records + open_records

# ---------- reconciliation & aggregation ----------
total_actual_pnl = sum(r['actual_pnl'] for r in all_records)
total_cf300_pnl = sum(r['cf_csi300_pnl'] for r in all_records)
total_cf1000_pnl = sum(r['cf_csi1000_pnl'] for r in all_records)
total_entry_value = sum(r['entry_value'] for r in all_records)

print("\n--- Reconciliation ---")
print("Sum actual $PnL from lots:", round(total_actual_pnl,2))
print("NAV_T1 - NAV_T0 (SSOT):", round(nav_t1-nav_t0,2))
print("Diff (unexplained, fees/rounding/other):", round((nav_t1-nav_t0) - total_actual_pnl, 2))
print("Total entry_value (capital base, dollar-time weighted):", round(total_entry_value,2))
print("n_records:", len(all_records), "n_closed:", len(matched_records), "n_open_T1:", len(open_records))

results = {
    'nav_t0': nav_t0, 'nav_t1': nav_t1, 'r_total': nav_t1/nav_t0-1,
    'csi300_t0': idx_close(csi300, WINDOW_START,'x'), 'csi300_t1': idx_close(csi300, WINDOW_END,'x'),
    'csi1000_t0': idx_close(csi1000, WINDOW_START,'x'), 'csi1000_t1': idx_close(csi1000, WINDOW_END,'x'),
    'total_actual_pnl': total_actual_pnl,
    'total_cf300_pnl': total_cf300_pnl,
    'total_cf1000_pnl': total_cf1000_pnl,
    'total_entry_value': total_entry_value,
    'reconciliation_gap': (nav_t1-nav_t0) - total_actual_pnl,
    'n_records': len(all_records), 'n_closed': len(matched_records), 'n_open_T1': len(open_records),
}
with open('attr_results.json','w') as f:
    json.dump({'summary': results, 'records': all_records}, f, ensure_ascii=False, indent=2)
print("\nSaved attr_results.json")
