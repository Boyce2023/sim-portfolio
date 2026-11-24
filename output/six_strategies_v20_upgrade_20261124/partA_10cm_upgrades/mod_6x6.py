#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""6x6 (30 ordered pairs x 2 lags) full interaction matrix scanner."""
import numpy as np, pandas as pd, scipy.stats as stats
from mod_common import SIM

STRATS = ["3to4_V41", "high_V51", "pry_V21", "2to3_V21", "1to2_V19", "20cm_V11_A76"]

def _eval_view(src_dts: dict, df_t: pd.DataFrame, prev_td: dict, view: str, src: str, tgt: str, lag: str) -> dict:
    fn = (lambda d: d in src_dts[src]) if lag == "same_day" else (lambda d: prev_td.get(d, "") in src_dts[src])
    bdt = df_t["buy_date"].astype(str)
    hit = bdt.map(fn).to_numpy()
    r = df_t["net_ret"].to_numpy(dtype=float)
    is_m = (bdt <= "2024-08-31").to_numpy()
    oo_m = (bdt >= "2024-09-01").to_numpy()
    m26 = (bdt >= "2026-01-01").to_numpy()

    def _blk(mask_w):
        hw, nw = hit & mask_w, (~hit) & mask_w
        nh, nn = int(hw.sum()), int(nw.sum())
        if nh < 1 or nn < 1:
            return {"hits": nh, "non_hits": nn, "wr_hit_pct": None, "wr_non_pct": None, "wr_diff_pp": None,
                    "mean_hit_pct": None, "mean_non_pct": None, "mean_diff_pp": None, "t": None, "p": None}
        rh, rn = r[hw], r[nw]
        wrh, wrn = float((rh > 0).mean() * 100.0), float((rn > 0).mean() * 100.0)
        mh, mn = float(rh.mean() * 100.0), float(rn.mean() * 100.0)
        if nh >= 2 and nn >= 2 and (rh.std(ddof=1) > 1e-12 or rn.std(ddof=1) > 1e-12):
            tv, pv = stats.ttest_ind(rh, rn, equal_var=False)
            tv, pv = round(float(tv), 3), round(float(pv), 4)
        else:
            tv, pv = None, None
        return {"hits": nh, "non_hits": nn, "wr_hit_pct": round(wrh, 2), "wr_non_pct": round(wrn, 2),
                "wr_diff_pp": round(wrh - wrn, 2), "mean_hit_pct": round(mh, 2), "mean_non_pct": round(mn, 2),
                "mean_diff_pp": round(mh - mn, 2), "t": tv, "p": pv}

    return {
        "view": view, "source": src, "target": tgt, "lag": lag,
        "FULL": _blk(np.ones(len(r), dtype=bool)),
        "IS": _blk(is_m), "OOS": _blk(oo_m), "2026": _blk(m26),
    }

def run_6x6_matrix(pass_1to2_df: pd.DataFrame, prev_td: dict) -> dict:
    pc = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
    s20_all = pd.read_csv(f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack/final_v11_all_scored_signals.csv", dtype={"c6": str})
    s20_all["buy_date"] = s20_all["buy_date"].astype(str)
    l20 = pd.read_csv(f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack/final_v11_ledger.csv", dtype={"c6": str})
    l20["buy_date"] = l20["buy_date"].astype(str)

    p34 = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high/pool_3to4_full_clean.csv", dtype={"code": str})
    phd = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high/pool_high_full_clean.csv", dtype={"code": str})
    ppr = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry/pool_pry_full_clean.csv", dtype={"code": str})
    p23 = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry/pool_2to3_full_clean.csv", dtype={"code": str})

    ledgers = {
        "3to4_V41": pd.read_csv(f"{pc}/ledger_3to4_v41_clean.csv", dtype={"code": str}),
        "high_V51": pd.read_csv(f"{pc}/ledger_high_v51_clean.csv", dtype={"code": str}),
        "pry_V21": pd.read_csv(f"{pc}/ledger_pry_v21_ss165_clean.csv", dtype={"code": str}),
        "2to3_V21": pd.read_csv(f"{pc}/ledger_2to3_v21_opt_std90_clean.csv", dtype={"code": str}),
        "1to2_V19": pd.read_csv(f"{pc}/ledger_1to2_v19_clean.csv", dtype={"code": str}),
        "20cm_V11_A76": l20,
    }
    pass_pools = {
        "3to4_V41": p34[p34["base_score"] >= 90].copy(),
        "high_V51": phd[phd["base_score"] >= 88].copy(),
        "pry_V21": ppr[ppr["base_score"] >= 165].copy(),
        "2to3_V21": p23[p23["base_score"] >= 90].copy(),
        "1to2_V19": pass_1to2_df.copy(),
        "20cm_V11_A76": s20_all[s20_all["score"] >= 76].copy(),
    }
    raw_0925_dts = {k: set(v["buy_date"].astype(str)) for k, v in pass_pools.items()}
    ledger_dts = {k: set(v["buy_date"].astype(str)) for k, v in ledgers.items()}

    cells_raw_to_1s, cells_raw_to_pool, cells_ldg_to_1s = [], [], []
    for src in STRATS:
        for tgt in STRATS:
            if src == tgt: continue
            for lag in ("same_day", "prev_day"):
                cells_raw_to_1s.append(_eval_view(raw_0925_dts, ledgers[tgt], prev_td, "RAW_0925->LEDGER_1S", src, tgt, lag))
                cells_raw_to_pool.append(_eval_view(raw_0925_dts, pass_pools[tgt], prev_td, "RAW_0925->POOL_PASS", src, tgt, lag))
                cells_ldg_to_1s.append(_eval_view(ledger_dts, ledgers[tgt], prev_td, "LEDGER->LEDGER_1S", src, tgt, lag))

    def _dual_screen(cells):
        out = []
        for c in cells:
            dm_is, dm_oo = c["IS"]["mean_diff_pp"], c["OOS"]["mean_diff_pp"]
            p_full, nh = c["FULL"]["p"], c["FULL"]["hits"]
            if nh >= 8 and dm_is is not None and dm_oo is not None and (dm_is * dm_oo > 0) and p_full is not None and p_full <= 0.20:
                c2 = dict(c)
                if c["source"] == "20cm_V11_A76" and c["target"] == "1to2_V19" and c["lag"] == "same_day":
                    c2["verdict"] = "ADMITTED_GOLDEN_10CM"
                elif c["target"] == "20cm_V11_A76":
                    c2["verdict"] = "OUT_OF_SCOPE_20CM_NOTE"
                else:
                    c2["verdict"] = "CANDIDATE_FOR_FULL_POOL_REOPT_TEST"
                out.append(c2)
        return out

    return {
        "total_ordered_pairs": 30,
        "total_lag_tests_per_view": 60,
        "raw_signal_day_counts": {k: len(v) for k, v in raw_0925_dts.items()},
        "cells_raw_to_ledger1s": cells_raw_to_1s,
        "cells_raw_to_pool_pass": cells_raw_to_pool,
        "cells_ledger_to_ledger1s": cells_ldg_to_1s,
        "dual_period_screen_raw_to_1s": _dual_screen(cells_raw_to_1s),
        "dual_period_screen_raw_to_pool": _dual_screen(cells_raw_to_pool),
    }
