"""9-10月游资选股学习分析脚本(复跑说明)
数据源: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/limitups_full2025.json
  (由baostock preclose字段重构涨停,详见同目录rebuild_full.py)
名称映射: raw/code_name_from_lhb.pkl (从raw/lhb_detail_em_FULL_2025.csv提取,覆盖86.8%)
复跑: python3 scripts/mainline_analysis_sep_oct.py
"""
import json, pickle, statistics
from collections import defaultdict

LU_PATH = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/limitups_full2025.json'
NAME_MAP_PATH = 'raw/code_name_from_lhb.pkl'

def load():
    lus = json.load(open(LU_PATH))
    name_map = pickle.load(open(NAME_MAP_PATH, 'rb'))
    sept_oct = [r for r in lus if '2025-09-01' <= r['date'] <= '2025-10-31']
    return sept_oct, name_map

if __name__ == '__main__':
    sept_oct, name_map = load()
    bydate = defaultdict(list)
    for r in sept_oct: bydate[r['date']].append(r)
    print(f"样本量 n={len(sept_oct)}, 交易日数={len(bydate)}")
    top_days = sorted(bydate.items(), key=lambda x: -len(x[1]))[:8]
    for d, recs in sorted(top_days):
        print(d, len(recs))
