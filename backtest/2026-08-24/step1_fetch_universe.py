#!/usr/bin/env python3
"""Step 1 (isolated process -- importing astock_data_layer here and doing heavy
threaded akshare fetches in a SECOND separate process avoids a native mini_racer
crash observed when both happen in the same Python process, see run log)."""
import sys, json
OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts")
import astock_data_layer as dl

full = dl.get_full_market(max_pages=60)
codes = [{"code": x["code"], "name": x["name"]} for x in full]
json.dump(codes, open(f"{OUTDIR}/universe_codes.json", "w"), ensure_ascii=False, indent=0)
sh_sz = [c["code"] for c in codes if c["code"][0] in ("6", "0", "3")]
bj_excluded = [c["code"] for c in codes if c["code"][0] in ("4", "8", "9")]
print(f"[universe] total={len(codes)} SH/SZ(usable)={len(sh_sz)} BJ_excluded(no sina coverage)={len(bj_excluded)}",
      file=sys.stderr)
