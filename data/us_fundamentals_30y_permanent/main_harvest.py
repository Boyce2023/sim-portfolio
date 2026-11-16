import os
import sys
import time
import pandas as pd
from datetime import datetime

# Add permanent data dir to path
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent")

from engine.universe import get_pre2009_universe
from engine.step_a_submissions import run_step_a
from engine.step_b_xbrl import run_step_b
from engine.step_c_item6 import run_step_c
from engine.merger_and_audit import merge_and_audit

CHECKPOINTS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent/pre2009/checkpoints"
os.makedirs(CHECKPOINTS_DIR, exist_ok=True)

def main():
    start_time = time.time()
    print("=" * 70)
    print("=== STARTING PRE-2009 SEC (1996–2008) PERMANENT HARVESTER ===")
    print("=" * 70)

    # 1. Load universe
    universe = get_pre2009_universe()
    total_companies = len(universe)
    print(f"Total Target Universe: {total_companies} companies.")

    # 2. Step A: Filings Submissions (1995-2009)
    df_filings, filings_index = run_step_a(universe)

    # 3. Step B: Early Comparative XBRL (2005-2008)
    df_xbrl = run_step_b(universe, filings_index)

    # 4. Step C: Historical 10-K Item 6 (1996-2006) with Checkpoints every 100 companies
    print(f"\n=== [Step C & Checkpoints] Processing {total_companies} Companies with 100-Company Checkpoints ===")
    all_item6_frames = []
    chunk_size = 100
    total_chunks = (total_companies + chunk_size - 1) // chunk_size

    for chunk_idx in range(total_chunks):
        start_idx = chunk_idx * chunk_size
        end_idx = min(start_idx + chunk_size, total_companies)
        chunk = universe[start_idx:end_idx]
        chunk_file = os.path.join(CHECKPOINTS_DIR, f"item6_chunk_{chunk_idx:02d}_{start_idx}_{end_idx}.parquet")

        print(f"\n>>> Running Chunk {chunk_idx + 1} / {total_chunks} (Companies {start_idx + 1} to {end_idx}) <<<")

        if os.path.exists(chunk_file) and os.path.getsize(chunk_file) > 1000:
            df_chunk_item6 = pd.read_parquet(chunk_file)
            print(f"Loaded Chunk {chunk_idx + 1} from checkpoint: {len(df_chunk_item6)} rows.")
        else:
            df_chunk_item6 = run_step_c(chunk, filings_index, df_xbrl)
            if df_chunk_item6 is not None and not df_chunk_item6.empty:
                df_chunk_item6.to_parquet(chunk_file, index=False)
                print(f"Saved Chunk {chunk_idx + 1} to {chunk_file} ({len(df_chunk_item6)} rows).")

        if df_chunk_item6 is not None and not df_chunk_item6.empty:
            all_item6_frames.append(df_chunk_item6)

        # Merge and checkpoint after every chunk
        current_item6_df = pd.concat(all_item6_frames, ignore_index=True) if all_item6_frames else pd.DataFrame()
        merge_and_audit(df_xbrl, current_item6_df, end_idx, total_companies)

    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print(f"=== HARVEST COMPLETED SUCCESSFULLY IN {elapsed:.1f}s ({elapsed/60:.1f}m) ===")
    print("=" * 70)

if __name__ == "__main__":
    main()
