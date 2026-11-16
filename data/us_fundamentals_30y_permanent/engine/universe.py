import os
import json
import glob
import pandas as pd

SHARDS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/shards"
XBRL_MASTER_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/data/xbrl_master_pit_2009_2026.parquet"

def get_pre2009_universe():
    """
    Returns sorted list of dicts: [{'ticker': str, 'cik': int, 'name': str}]
    Combines 851 CIKs from pre2009_shard_0..3.json plus pre-2009 tickers from xbrl_master.
    """
    all_items = []
    for s_path in sorted(glob.glob(os.path.join(SHARDS_DIR, "pre2009_shard_*.json"))):
        with open(s_path, "r", encoding="utf-8") as f:
            all_items.extend(json.load(f))

    by_ticker = {x['ticker'].upper().strip(): {'ticker': x['ticker'].upper().strip(), 'cik': int(x['cik']), 'name': x.get('name', '')} for x in all_items}

    # Add extra tickers from xbrl_master filed <= 2011-12-31 with pre-2009 history
    if os.path.exists(XBRL_MASTER_PATH):
        df_xbrl = pd.read_parquet(XBRL_MASTER_PATH)
        earliest_filed = df_xbrl.groupby('ticker')['filed'].min()
        early_tickers = earliest_filed[earliest_filed <= '2011-12-31'].index
        for t in early_tickers:
            t_clean = t.upper().strip()
            if t_clean not in by_ticker:
                sub_df = df_xbrl[df_xbrl['ticker'] == t].iloc[0]
                by_ticker[t_clean] = {
                    'ticker': t_clean,
                    'cik': int(sub_df['cik']),
                    'name': str(sub_df.get('name', ''))
                }

    sorted_universe = sorted(by_ticker.values(), key=lambda x: x['ticker'])
    return sorted_universe

if __name__ == "__main__":
    uni = get_pre2009_universe()
    print(f"Loaded {len(uni)} unique companies. Sample: {uni[:5]}")
