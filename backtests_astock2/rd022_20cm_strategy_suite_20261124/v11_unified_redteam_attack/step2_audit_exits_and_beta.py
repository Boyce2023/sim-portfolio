#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Attack 2 & 3a: Execution buffer (+0.30% TP penetration), slippage/liquidity stress, and Beta V1.0 factor/year audit."""
import os, pickle, sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
B1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_beta_scorecard_exit"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
sys.path.insert(0, V1_DIR)
sys.path.insert(0, PART2_DIR)
from backtest_utils import _sim_k_slots
from step2_is_exit_tree_opt import defer_to_sellable_close
from step3_oos_and_tables import FINAL_EXIT_CFG


def sim_deepopen_strict_exec(df: pd.DataFrame, cfg: dict, fee: float = 0.0030, tp_buf: float = 0.0030) -> pd.DataFrame:
    """Strict physical execution: intraday TP requires ah >= tp_px * (1 + tp_buf) to fill at tp_px!"""
    rows = []
    for r in df.itertuples(index=False):
        b_px = float(r.f1_ao)
        if np.isnan(b_px) or b_px <= 0:
            continue
        rm = cfg.get("risk_mode", "none")
        risk_hit = ((r.f1_lhb_inst_net < -2000.0) or (r.f1_mkt20_dt_cnt >= 3) or (r.f1_mkt10_dt_cnt >= 20)) if rm == "inst_dt" else False
        sell_k, s_px, reason = 2, np.nan, "d2_close"

        def try_tp_sl_buf(k, tp_r, sl_r, ref_px):
            ao = float(getattr(r, f"f{k}_ao", np.nan))
            ah = float(getattr(r, f"f{k}_ah", np.nan))
            al = float(getattr(r, f"f{k}_al", np.nan))
            if np.isnan(ao) or np.isnan(ah) or np.isnan(al) or (not getattr(r, f"f{k}_sellable", False)):
                return False, np.nan, ""
            open_dt = bool(getattr(r, f"f{k}_open_is_dt", False))
            tp_px = ref_px * (1.0 + tp_r) if tp_r is not None else 1e18
            sl_px = ref_px * (1.0 + sl_r) if sl_r is not None else -1e18
            if sl_r is not None and ao <= sl_px and not open_dt:
                return True, ao, "gap_sl"
            if tp_r is not None and ao >= tp_px and not open_dt:
                return True, ao, "gap_tp"
            hit_sl = (sl_r is not None) and (al <= sl_px)
            # CRITICAL: Require ah >= tp_px * (1 + tp_buf) OR tp_px at ZT!
            zt_px_k = float(getattr(r, f"f{k}_zt_px_adj", 1e18) or 1e18)
            need_ah = min(tp_px * (1.0 + tp_buf), zt_px_k - 1e-4) if tp_r is not None else 1e18
            hit_tp = (tp_r is not None) and (ah >= need_ah)
            if hit_sl:
                dt_px = float(getattr(r, f"f{k}_dt_px_adj", 0.0) or 0.0)
                if sl_px <= dt_px and bool(getattr(r, f"f{k}_is_dt", False)):
                    return False, np.nan, ""
                return True, max(sl_px, al), "collision_sl" if hit_tp else "intraday_sl"
            if hit_tp:
                return True, tp_px, "intraday_tp"
            return False, np.nan, ""

        if r.f1_zt:
            k, imm = 2, False
            while k < 10:
                ac_k, ac_p = float(getattr(r, f"f{k}_ac", np.nan)), float(getattr(r, f"f{k-1}_ac", np.nan))
                if np.isnan(ac_k):
                    k = max(2, k - 1); break
                if getattr(r, f"f{k}_zt", False):
                    k += 1; continue
                if cfg.get("zt_imm", False) and not imm and getattr(r, f"f{k}_ty", False) and ac_k > ac_p:
                    imm = True; k += 1; continue
                sell_k, reason = k, "B1_zt_break"; break
            else:
                sell_k, reason = 10, "B1_zt_max10"
        else:
            f1_ac, f1_body, f1_clv = float(r.f1_ac), float(r.f1_body or 0.0), float(r.f1_clv or 0.5)
            is_b4 = (f1_body <= cfg.get("b4_body", -0.05) or r.f1_is_dt)
            is_b2 = (not is_b4) and (f1_body >= cfg.get("b2_body", 0.06)) and (f1_clv >= cfg.get("b2_clv", 0.65))
            if is_b4:
                sell_k, reason = 2, "B4_d2_close"
            elif is_b2:
                tp2 = min(cfg.get("b2_tp", 0.12), 0.07) if (risk_hit and cfg.get("b2_tp")) else cfg.get("b2_tp", None)
                if cfg.get("b2_mode") in ("d2_tp", "d3_hold") and tp2 is not None:
                    hit, px_h, r_h = try_tp_sl_buf(2, tp2, None, f1_ac)
                    if hit: s_px, sell_k, reason = px_h, 2, f"B2_{r_h}"
                if np.isnan(s_px):
                    if cfg.get("b2_mode") == "d3_hold" and (not risk_hit) and not np.isnan(r.f3_ac):
                        if r.f2_zt:
                            k = 3
                            while k < 10 and getattr(r, f"f{k}_zt", False): k += 1
                            sell_k, reason = k, "B2_d2zt_ride"
                        else:
                            if tp2 is not None:
                                hit3, px3, r3 = try_tp_sl_buf(3, tp2, None, float(r.f2_ac))
                                if hit3: s_px, sell_k, reason = px3, 3, f"B2_d3_{r3}"
                            if np.isnan(s_px): sell_k, reason = 3, "B2_d3_close"
                    else:
                        sell_k, reason = 2, "B2_d2_close"
            else:
                tp3 = max(0.06, min(0.15, abs(float(r.f1_o_pct)) * cfg.get("b3_adapt_k", 1.5))) if cfg.get("b3_tp_mode") == "adaptive" else cfg.get("b3_tp", None)
                if risk_hit and tp3 is not None: tp3 = min(tp3, 0.07)
                if tp3 is not None:
                    hit, px_h, r_h = try_tp_sl_buf(2, tp3, None, f1_ac)
                    if hit: s_px, sell_k, reason = px_h, 2, f"B3_{r_h}"
                if np.isnan(s_px): sell_k, reason = 2, "B3_d2_close"

        if np.isnan(s_px):
            sell_k, s_px = defer_to_sellable_close(r, sell_k)
            if sell_k < 2: continue
        s_dt = getattr(r, f"f{sell_k}_dt")
        if not s_dt or np.isnan(s_px) or s_px <= 0: continue
        gross = s_px / b_px - 1.0
        net = (1.0 + gross) * (1.0 - fee) - 1.0
        rows.append({"sig_date": r.dt, "buy_date": r.f1_dt, "exit_date": s_dt, "c6": r.c6, "score": float(getattr(r, "score", 0.0)), "amount": float(r.amount), "gross_ret": gross, "net_ret": net, "exit_reason": reason})
    return pd.DataFrame(rows)


def main():
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    all_sig = pd.read_csv(f"{V1_DIR}/all_scored_signals_v1.csv")
    all_sig["c6"] = all_sig["c6"].astype(str).str.zfill(6)
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    pool = pool.merge(all_sig[["sig_date", "c6", "score"]], left_on=["dt", "c6"], right_on=["sig_date", "c6"], how="inner")
    pool_A = pool[pool["score"] >= 78.0].copy()

    print("=== ATTACK 2A: DeepOpen V1.0 A(>=78) EXIT TREE & EXECUTION FRICTION ===")
    cfgs = [
        ("V1_Tree_buf0.00_fee0.30", FINAL_EXIT_CFG, 0.0030, 0.0000, 1e8),
        ("V1_Tree_buf0.30_fee0.30", FINAL_EXIT_CFG, 0.0030, 0.0030, 1e8),
        ("V1_Tree_buf0.50_fee0.30", FINAL_EXIT_CFG, 0.0030, 0.0050, 1e8),
        ("V1_Tree_buf0.30_fee0.50", FINAL_EXIT_CFG, 0.0050, 0.0030, 1e8),
        ("V1_Tree_buf0.30_fee0.80", FINAL_EXIT_CFG, 0.0080, 0.0030, 1e8),
        ("V1_Tree_buf0.30_amt2e8", FINAL_EXIT_CFG, 0.0030, 0.0030, 2e8),
        ("V1_Tree_buf0.30_amt3e8", FINAL_EXIT_CFG, 0.0030, 0.0030, 3e8),
        ("NoB2D3_buf0.30_fee0.30", {**FINAL_EXIT_CFG, "b2_mode": "d2_tp"}, 0.0030, 0.0030, 1e8),
        ("PureT2_Close_fee0.30", {"b3_tp_mode": "none", "b2_mode": "d2_close", "zt_imm": False, "risk_mode": "none"}, 0.0030, 0.0030, 1e8),
        ("ZT_Ride_Only_fee0.30", {"b3_tp_mode": "none", "b2_mode": "d2_close", "zt_imm": True, "risk_mode": "none"}, 0.0030, 0.0030, 1e8),
    ]
    for nm, cfg, fee, buf, amt_min in cfgs:
        sub = pool_A[pool_A["amount"] >= amt_min]
        tr = sim_deepopen_strict_exec(sub, cfg, fee=fee, tp_buf=buf)
        t_full, nv_f, mdd_f = _sim_k_slots(tr, 1)
        t_is, nv_is, _ = _sim_k_slots(tr[tr["buy_date"] <= "2024-08-31"], 1)
        t_oos, nv_oos, _ = _sim_k_slots(tr[tr["buy_date"] >= "2024-09-01"], 1)
        t_26, nv_26, _ = _sim_k_slots(tr[tr["buy_date"] >= "2026-01-01"], 1)
        tp_cnt = int(tr["exit_reason"].str.contains("_tp").sum())
        print(f"  {nm:26s} | N={len(t_full):3d} TP={tp_cnt:2d} | FULL={nv_f:6.2f}x MDD={mdd_f*100:4.1f}% | IS={nv_is:6.2f}x | OOS={nv_oos:5.2f}x | 2026={nv_26:4.2f}x")

    print("\n=== ATTACK 3A: Beta V1.0 FACTOR HIT COVERAGE & IS/OOS/25-26 IC ===")
    b_df = pd.read_csv(f"{B1_DIR}/all_scored_signals_beta_v1.csv")
    b_df["yr"] = b_df["dt"].str[:4]
    b_is = b_df["dt"] <= "2024-08-31"
    b_ox = (b_df["dt"] >= "2024-09-01") & (~b_df["dt"].between("2024-09-24", "2024-10-08"))
    pt_cols = [c for c in b_df.columns if c.startswith("pt_")]
    for c in pt_cols:
        nz_is = b_df.loc[b_is & (b_df[c] != 0), "ret_dyn_yang_tp15_pct"]
        nz_ox = b_df.loc[b_ox & (b_df[c] != 0), "ret_dyn_yang_tp15_pct"]
        pos_is = b_df.loc[b_is & (b_df[c] > 0), "ret_dyn_yang_tp15_pct"]
        neg_is = b_df.loc[b_is & (b_df[c] < 0), "ret_dyn_yang_tp15_pct"]
        pos_ox = b_df.loc[b_ox & (b_df[c] > 0), "ret_dyn_yang_tp15_pct"]
        neg_ox = b_df.loc[b_ox & (b_df[c] < 0), "ret_dyn_yang_tp15_pct"]
        print(f"  {c:20s} | +IS(n={len(pos_is):4d},mn={pos_is.mean():+5.2f}%) -IS(n={len(neg_is):4d},mn={neg_is.mean():+5.2f}%) | "
              f"+OOSx(n={len(pos_ox):4d},mn={pos_ox.mean():+5.2f}%) -OOSx(n={len(neg_ox):4d},mn={neg_ox.mean():+5.2f}%)")

    # Check exact date overlap between DeepOpen A(>=78) and Beta A(>=85)
    b_led = pd.read_csv(f"{B1_DIR}/ledger_beta_v1_A.csv")
    d_led = pd.read_csv(f"{V1_DIR}/ledger_v1_A.csv")
    d_dates = set(d_led["buy_date"])
    b_dates = set(b_led["buy_dt"])
    print(f"\n=== DATE OVERLAP: DeepOpen A buy_days={len(d_dates)} | Beta A buy_days={len(b_dates)} | Same-day overlap={len(d_dates & b_dates)} ===")
    # Check interval overlap (if Beta holds T+2..T+5, how many DeepOpen 1s trades overlap with Beta holding window!)
    b_ints = [(r.buy_dt, r.sell_dt) for r in b_led.itertuples(index=False)]
    coll = sum(1 for r in d_led.itertuples(index=False) if any(not (r.exit_date < bs or r.buy_date > be) for bs, be in b_ints))
    print(f"  DeepOpen 1s trades colliding with Beta A holding intervals: {coll} / {len(d_led)}")


if __name__ == "__main__":
    main()
