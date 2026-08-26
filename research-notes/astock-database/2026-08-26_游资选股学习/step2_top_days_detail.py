import json
import pandas as pd

BASE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'
OUT = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26_游资选股学习/raw'

d = json.load(open(f'{BASE}/limitups_full2025.json'))
df = pd.DataFrame(d)
sub = df[(df['date'] >= '2025-03-01') & (df['date'] <= '2025-04-30')].copy()

# code->name map
name_map = pd.read_csv(f'{OUT}/code_name_map.csv', dtype=str)
name_map['code'] = name_map['code'].str.zfill(6)
name_map_dict = dict(zip(name_map['code'], name_map['name']))

def bare(code):
    return code.split('.')[-1]

sub['bare_code'] = sub['code'].apply(bare)
sub['name'] = sub['bare_code'].map(name_map_dict)
sub.to_csv(f'{OUT}/mar_apr_2025_zhangting_full.csv', index=False, encoding='utf-8-sig')
print('total rows saved:', len(sub), 'names matched:', sub['name'].notna().sum(), '/', len(sub))

TOP_DAYS = ['2025-04-08', '2025-04-09', '2025-04-10', '2025-04-14',
            '2025-04-21', '2025-03-06', '2025-03-14', '2025-03-26']

for dt in TOP_DAYS:
    day = sub[sub['date'] == dt].sort_values('streak', ascending=False)
    print(f"\n===== {dt}  (n={len(day)}) =====")
    print(f"streak dist: {day['streak'].value_counts().sort_index(ascending=False).to_dict()}")
    print(f"yizi(一字板) count: {day['yizi'].sum()}")
    names = day[['name', 'streak', 'yizi', 'turn', 'gain20', 'isST']].to_dict('records')
    for r in names:
        nm = str(r['name']) if pd.notna(r['name']) else '(NA)'
        print(f"  {nm:>8s}  streak={r['streak']}  yizi={r['yizi']}  turn={r['turn']:.1f}%  gain20={r['gain20']}  ST={r['isST']}")
