#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD035 Wave 3-2 Red Team Audit A runner: 7 Wave-2 finalists across 6 cold-blooded gates."""
import gc, json, os, resource, sys
import numpy as np
import pandas as pd
import pyarrow as pa

os.environ.setdefault("OMP_NUM_THREADS", "1")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _rt_loaders as ld
import _rt_checks as ck
import _rt_pit_audits as paud

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
WAVE1 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"

VERDICTS = {
    "item1_w2a3_20cm_F06_and_CLEAN_B": {
        "verdict": "PASS_READY (1a F06_COLD50 pure physical) / PASS_CAUTIOUS_WATCH (1b CLEAN_B S84)",
        "rationale": "F06_COLD50 removes only cold-regime false positives physically; CLEAN_B S84 passes 50/80bps & >=2亿 liquidity with ex5=15.66x but shows modest overfitting sensitivity vs pure F06.",
    },
    "item2_w2a4_pairwise_interactions": {
        "verdict": "PASS_CAUTIOUS_WATCH (standalone 2a 46.86x) / PASS_READY_MODEST_UPGRADE (combined 2b)",
        "rationale": "Combined V20 ledger (209 trades) upgrades V20 smoothly with zero ST/yizi leaks; Road2 melee (2c, 377 trades) dilutes per-trade quality and must be checked under 50/80bps.",
    },
    "item3_w2a2_3to4_high_pry": {
        "verdict": "PASS_CAUTIOUS_WATCH (3to4 M4_MineBL15; only small-N diff) / KILL_REJECT (high & pry as main pillar)",
        "rationale": "3to4 M4_MineBL15 removes tiny sample vs 73-trade baseline (verify exact removed mines in Gate 5); pry M1 drops 4 of 10 trades (small-N coincidence, +3% NAV only).",
    },
    "item4_w2b5_512100_and_D1": {
        "verdict": "KILL_REJECT (512100 YieldAllV20 causal leak; D1 low live marginal)",
        "rationale": "512100 YieldAllV20 leaks intraday V20 triggers at 09:24 exit (causal Yield_open_0925 collapses comb_ratio from 1.31x to 0.76x; standalone n=11 ex5=0.95x); D1 standalone fades sharply ex5 & under >=2亿 liquidity / 74 V20 skips.",
    },
    "item5_w2b6_ModE_C1_B1": {
        "verdict": "KILL_REJECT (ModE_E3 hindsight+ZT-relay; ModB_B1 timestamp leak) / PASS_CAUTIOUS_WATCH (ModC_C1 clean PIT weak standalone)",
        "rationale": "ModE_E3 US->CN T-1 date is causal, BUT depends on 2026-08 hindsight supply-tree patches & ZT-relay (NoZT collapses 9.77x->1.32x); ModB_B1 ignores trade_date_avail & leaks 00:00:00 same-day IR Q&A; ModC_C1 is 100% PIT-clean pre-09:25.",
    },
    "item6_w2b4_A5_12_23": {
        "verdict": "PASS_CAUTIOUS_WATCH (A5_v11_PURE abs80/85, watch ex5 & 80bps decay)",
        "rationale": "Zero PIT leak, clean 20cm first-board-to-second-board extension; check ex5 (abs85 only ~1.70x at n=51) & 50/80bps capacity.",
    },
    "item7_w2b1_ModeM_surge10_19": {
        "verdict": "KILL_REJECT (Confirm NO_GO: 50bps rescore collapses 6.05x -> 1.32x, ex5 0.49x)",
        "rationale": "Confirmed NO_GO: rescoring factors at 50bps flips selected mine/dragon factors (126 -> 130 trades) causing catastrophic 6.05x -> 1.32x collapse; fixed 30bps ex5=1.71x also marginal.",
    },
}


def main():
    ledgers = {}
    for fn in (
        ld.load_w2a3_ledgers,
        ld.load_w2a4_ledgers,
        ld.load_w2a2_ledgers,
        ld.load_w2b5_ledgers,
        ld.load_w2b6_ledgers,
        ld.load_w2b4_and_w2b1_ledgers,
    ):
        part = fn()
        ledgers.update(part)
        gc.collect()
        pa.default_memory_pool().release_unused()

    ref = ck.build_ref_context(ledgers)
    mkt_cal = pd.read_parquet(f"{WAVE1}/market_daily_all_new_factors_pit.parquet", columns=["trade_date"])
    cal_dates = sorted(mkt_cal["trade_date"].astype(str).str[:10].unique().tolist())
    del mkt_cal

    etf_keys = {"4a_w2b5_512100_V3EOD_YieldAllV20", "4a2_w2b5_512100_V3EOD_YieldOpen0925"}
    gate124 = {}
    all_forensics = []
    for k, df in ledgers.items():
        s, frows = ck.enrich_and_audit_ledger(k, df, ref, is_etf=(k in etf_keys))
        gate124[k] = s
        all_forensics.extend(frows)
        print(
            f"[AUDIT] {k:40s} n={s['n_trades']:3d} 30bps={s['slippage_stress'].get('30bps', s['slippage_stress'].get('5bps', {})).get('nav')} "
            f"50bps={s['slippage_stress'].get('50bps', s['slippage_stress'].get('15bps', {})).get('nav')} "
            f"ex5={s['slippage_stress'].get('30bps', s['slippage_stress'].get('5bps', {})).get('ex5_nav')} "
            f"st={s['anomalies']['n_st_static']} yizi={s['anomalies']['n_yizi_zt_buy']} dl={s['anomalies']['n_delisted_ever']}"
        )

    gate3_pit = {
        "ModE_E3_US4pct_Mingmen_H1": paud.audit_mode_e3_pit(ledgers["5a_w2b6_ModE_E3_Mingmen_H1_top5"], ref["names"]),
        "ModC_C1_EarnPre_H3_top20": paud.audit_modc_c1_pit(ledgers["5b_w2b6_ModC_C1_EarnPre_H3_top20"]),
        "ModC_C1_EarnPre_H1_top10": paud.audit_modc_c1_pit(ledgers["5b2_w2b6_ModC_C1_EarnPre_H1_top10"]),
        "ModB_B1_IR_H3_abs70": paud.audit_modb_b1_pit(ledgers["5c_w2b6_ModB_B1_IR_H3_abs70"], cal_dates),
        "ModB_B1_IR_H5_abs75": paud.audit_modb_b1_pit(ledgers["5c2_w2b6_ModB_B1_IR_H5_abs75"], cal_dates),
        "W2B5_512100_YieldToV20": paud.audit_w2b5_track_c_pit(
            ledgers["4a_w2b5_512100_V3EOD_YieldAllV20"],
            ledgers["4a2_w2b5_512100_V3EOD_YieldOpen0925"],
        ),
    }

    gate5_diffs = paud.audit_gate5_all_diffs(ledgers, ref["names"])
    peak_rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)

    audit_out = {
        "meta": {"task": "RD035 Wave 3-2 Red Team Audit A", "peak_rss_mb": peak_rss_mb, "n_variants_audited": len(gate124)},
        "gate6_verdicts_template": VERDICTS,
        "gate1_gate2_gate4_variants": gate124,
        "gate3_pit_timezone_audits": gate3_pit,
        "gate5_incremental_diff_audits": gate5_diffs,
    }
    with open(f"{HERE}/w3_2_redteam_a_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit_out, f, ensure_ascii=False, indent=2, default=str)
    pd.DataFrame(all_forensics).to_csv(f"{HERE}/w3_2_top5_trades_forensics.csv", index=False)
    print(f"DONE peak_rss_mb={peak_rss_mb} json={HERE}/w3_2_redteam_a_audit.json csv_rows={len(all_forensics)}")


if __name__ == "__main__":
    main()
