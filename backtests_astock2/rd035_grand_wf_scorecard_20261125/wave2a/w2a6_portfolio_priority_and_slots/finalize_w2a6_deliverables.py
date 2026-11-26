#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Merge Part 1 & Part 2 outputs into the three required deliverables:
  - w2a6_audit.json
  - w2a6_scheme_compare.csv
  - w2a6_nearmiss_pool_audit.json (already created by Part 2, verified here)
"""
import json
import os
import sys
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
p1_json_path = f"{THIS_DIR}/_part1_results.json"
p1_csv_path = f"{THIS_DIR}/w2a6_part1_compare.csv"
p2_json_path = f"{THIS_DIR}/w2a6_nearmiss_pool_audit.json"

assert os.path.exists(p1_json_path), "Missing _part1_results.json"
assert os.path.exists(p1_csv_path), "Missing w2a6_part1_compare.csv"
assert os.path.exists(p2_json_path), "Missing w2a6_nearmiss_pool_audit.json"

with open(p1_json_path, encoding="utf-8") as f:
    p1 = json.load(f)
with open(p2_json_path, encoding="utf-8") as f:
    p2 = json.load(f)

df1 = pd.read_csv(p1_csv_path)
m4_rows = p2.get("part4b_nearmiss_pool_wf_audit", {}).get("csv_rows_m4", [])
df4 = pd.DataFrame(m4_rows) if m4_rows else pd.DataFrame()
df_all = pd.concat([df1, df4], ignore_index=True) if not df4.empty else df1

out_csv = f"{THIS_DIR}/w2a6_scheme_compare.csv"
df_all.to_csv(out_csv, index=False, encoding="utf-8-sig")

# Build unified w2a6_audit.json containing Modules 1, 2, 3, 4 (summary + ref), 5 + truncation checks
audit = {
    "generated_at": p2.get("generated_at", p1.get("generated_at")),
    "d12_yfinance_imported": False,
    "runtime_stats": {
        "part1_elapsed_sec": p1.get("elapsed_sec"),
        "part1_peak_rss_mb": p1.get("peak_rss_mb"),
        "part2_elapsed_sec": p2.get("elapsed_sec"),
        "part2_peak_rss_mb": p2.get("peak_rss_mb"),
    },
    "baseline_parity": p1["baseline_parity"],
    "truncation_20241231_proofs": {
        "module1_dynamic_priority": p1["module1_priority"]["truncation_20241231_M1_DYN"],
        "module2_dynamic_vol_amp": p1["module2_slots"]["truncation_20241231_M2_VolAmp"],
        "module4_nearmiss_wf_scorecard": p2["part4b_nearmiss_pool_wf_audit"]["truncation_20241231_proof"],
    },
    "module1_priority": p1["module1_priority"],
    "module2_slots": p1["module2_slots"],
    "module3_resonance": p1["module3_resonance"],
    "module4_rank2_and_nearmiss_summary": {
        "part4a_rank1_skips_and_rank2": p2["part4a_rank1_skips_and_rank2"],
        "part4b_raw_nearmiss_breakdown": p2["part4b_nearmiss_pool_wf_audit"]["raw_nearmiss_breakdown"],
        "part4b_wf_scorecard_summaries": {
            k: v["summary_table"]
            for k, v in p2["part4b_nearmiss_pool_wf_audit"]["wf_scorecard_nearmiss"].items()
        },
        "full_nearmiss_audit_file": p2_json_path,
    },
    "module5_reflexivity": p1["module5_reflexivity"],
    "deliverables": {
        "w2a6_audit_json": f"{THIS_DIR}/w2a6_audit.json",
        "w2a6_scheme_compare_csv": out_csv,
        "w2a6_nearmiss_pool_audit_json": p2_json_path,
    },
}

out_audit = f"{THIS_DIR}/w2a6_audit.json"
raw_txt = json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False)
assert "cap10m" not in raw_txt.lower() and "cap1000w" not in raw_txt.lower()
with open(out_audit, "w", encoding="utf-8") as f:
    f.write(raw_txt)

print(f"[FINALIZE DONE] rows_in_csv={len(df_all)} | w2a6_audit.json ({os.path.getsize(out_audit)/1024:.1f} KB)")
print("Trunc proofs:", json.dumps(audit["truncation_20241231_proofs"], ensure_ascii=False))
