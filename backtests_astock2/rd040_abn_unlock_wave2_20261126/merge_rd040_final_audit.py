#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Merge Step 3 E1a anatomy, open-bound plateau, WF extra & V20 patch into final rd040_audit.json & CSV."""
import json
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd040_abn_unlock_wave2_20261126"

def main():
    audit = json.load(open(f"{OUT_DIR}/rd040_audit.json", encoding="utf-8"))
    step1 = json.load(open(f"{OUT_DIR}/_step1_audit.json", encoding="utf-8"))
    forensics = json.load(open(f"{OUT_DIR}/rd040_e1a_forensics.json", encoding="utf-8"))
    pl_df = pd.read_csv(f"{OUT_DIR}/rd040_e1a_plateau.csv")
    wf_ex = pd.read_csv(f"{OUT_DIR}/rd040_e1a_wf_extra.csv")
    wf_base = pd.read_csv(f"{OUT_DIR}/rd040_wf_scorecard_grid.csv")
    bm = pd.read_csv(f"{OUT_DIR}/rd040_blind_matrix.csv")

    audit["step1_summary"] = step1
    audit["e1a_redteam_forensics"] = forensics
    audit["e1a_plateau_summary"] = {
        "n_grid_points": int(len(pl_df)),
        "s7_nav_5y_range": [float(pl_df[pl_df["exit"] == "S7_lianban"]["nav_5y_30"].min()), float(pl_df[pl_df["exit"] == "S7_lianban"]["nav_5y_30"].max())],
        "s7_ex5_wf_range": [float(pl_df[pl_df["exit"] == "S7_lianban"]["ex5_wf"].min()), float(pl_df[pl_df["exit"] == "S7_lianban"]["ex5_wf"].max())],
    }

    wf_all = pd.concat([wf_base, wf_ex], ignore_index=True)
    wf_all.to_csv(f"{OUT_DIR}/rd040_wf_scorecard_grid.csv", index=False, encoding="utf-8-sig")
    comb = pd.concat([bm.assign(section="BLIND"), wf_all.assign(section="WF_SCORECARD"), pl_df.assign(section="E1A_PLATEAU")], ignore_index=True, sort=False)
    comb.to_csv(f"{OUT_DIR}/rd040_events_and_grid.csv", index=False, encoding="utf-8-sig")

    audit["final_verdict"] = {
        "status": "FALSIFIED",
        "reason": "1) E1a/E1b/E2/E3/E_ALL_Cleared blind pools all lose money over 5Y (0.0004x~0.28x); 2) 20 WF 0..100 scorecards yield 0 passing thresholds; 3) Only positive blind pocket E1a_NoHit100_LowOpen (12.60x 5Y) drops to 0.99x ex-top5 in 2023-2026 WF, loses -37.4% in 2023, degrades under WF scoring (0.57x), and crashes V20 combined NAV by -34.2% to -62.4% under empty-slot patching.",
    }
    with open(f"{OUT_DIR}/rd040_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"Merged final audit: blind={len(bm)}, wf_all={len(wf_all)}, plateau={len(pl_df)}, total_grid_rows={len(comb)}")

if __name__ == "__main__":
    main()
