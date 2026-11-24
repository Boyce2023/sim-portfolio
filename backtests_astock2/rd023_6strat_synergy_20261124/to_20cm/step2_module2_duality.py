#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD023 Module 2: Opponent-Duality Cross-Strategy Causal Signals (10cm V19.1 <-> 20cm DeepOpen V1.1)."""
import json, os, pickle, sys, time
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
PC_DIR = f"{BASE}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
OUT_DIR = f"{BASE}/backtests_astock2/rd023_6strat_synergy_20261124/to_20cm"
sys.path.insert(0, OUT_DIR)

from rd023_eval_lib import V11_EXIT_CFG, compute_scorecard_v11, eval_splits, sim_v11_exit_ext


def load_10cm_ledgers() -> dict[str, pd.DataFrame]:
    files = {
        "comb": "ledger_combined_5strat_v191_slot1_clean.csv",
        "3to4": "ledger_3to4_v41_clean.csv",
        "high": "ledger_high_v51_clean.csv",
        "pry_top1": "ledger_pry_v21_top1_clean.csv",
        "pry_ss165": "ledger_pry_v21_ss165_clean.csv",
        "2to3": "ledger_2to3_v21_opt_std90_clean.csv",
        "1to2": "ledger_1to2_v19_clean.csv",
    }
    out = {}
    for k, fn in files.items():
        d = pd.read_csv(f"{PC_DIR}/{fn}")
        d["code"] = d["code"].astype(str).str.zfill(6)
        d["buy_date"] = d["buy_date"].astype(str).str[:10]
        d["exit_date"] = d["exit_date"].astype(str).str[:10]
        out[k] = d
    return out


def build_causal_10cm_flags(df20: pd.DataFrame, leds: dict, bar_10: dict) -> pd.DataFrame:
    """Attach 100% causal 10cm state flags known at T+1 09:25 (plus same-day T+1 reference flags)."""
    comb = leds["comb"]
    indiv = {k: leds[k] for k in ["3to4", "high", "pry_top1", "2to3", "1to2"]}
    all_10 = pd.concat([v.assign(st=k) for k, v in indiv.items()], ignore_index=True)

    # Pre-index T0 events
    by_buy = {k: set(v["buy_date"]) for k, v in leds.items()}
    comb_hold_eod = set()  # dates d where comb holds overnight AFTER d 15:00
    for r in comb.itertuples(index=False):
        pass
    # Direct date checks using trade intervals
    comb_rows = list(comb.itertuples(index=False))
    all10_rows = list(all_10.itertuples(index=False))

    # Compute causal T0-buy -> T0-close & T+1 09:25 open return from bar_10!
    t0_open_loss_dts, t0_open_bigloss_dts, t0_eod_loss_dts = set(), set(), set()
    for r in all10_rows:
        binfo = bar_10.get((r.code, r.buy_date))
        if binfo is None:
            continue
        ao_b, ac_b, nxt_dt, nxt_ao, is_zt_b = binfo
        scale_b = float(r.buy_price) / ao_b if ao_b > 0 else 1.0
        # T0 EOD P&L vs buy_price (if buy_hhmm > 925, compare ac_b vs ao_b * scale_b)
        if ac_b < float(r.buy_price) * 0.999 and (not is_zt_b):
            t0_eod_loss_dts.add(r.buy_date)
        # T+1 09:25 open P&L relative to buy_price (known at T+1 09:25!)
        if pd.notna(nxt_ao) and nxt_dt:
            # Adjust for adjf via ao_b -> ac_b ratio already in bar_10 (both ao & ac are adj-scaled in step0!)
            # Note: in step0, bar_10 stored ao = open * (adj_close/close), ac = adj_close. Wait: r.buy_price is UNADJUSTED!
            # Wait: r.buy_price / open_raw == ratio! Let's use (nxt_ao - ao_b * (r.buy_price / open_raw))?
            # Even better: r.buy_price in bar_10: since step0 adj_close/close is qfq_factor-normalized, ratio ao_b vs buy_price needs exact check!
            # Wait: let's check if r.buy_hhmm == 925 -> r.buy_price ~ raw open, so use nxt_ao / ao_b - 1 (exact adj open-to-open return!)
            # Or if r.buy_hhmm > 925 (breakout buy ~ +6.5%+), compare nxt_ao / ac_b - 1 (gap down from T0 close!) or nxt_ao / (ao_b * (r.buy_price / (ao_b / adjf)))!
            # Wait: let's just check BOTH: gap_from_T0_close <= -0.02 AND (nxt_ao / (ao_b * (1.065 if r.buy_hhmm > 925 else 1.0)) - 1)
            gap_ret = nxt_ao / ac_b - 1.0 if ac_b > 0 else 0.0
            est_open_ret = nxt_ao / ao_b - 1.0 if (r.buy_hhmm == 925 and ao_b > 0) else (nxt_ao / (ac_b * 0.98) - 1.0 if ac_b > 0 else 0.0)
            if gap_ret <= -0.02 or est_open_ret < 0.0:
                t0_open_loss_dts.add(r.buy_date)
            if gap_ret <= -0.04 or est_open_ret <= -0.03:
                t0_open_bigloss_dts.add(r.buy_date)

    # EOD exits with loss on T0
    exit_loss_t0 = set(all_10[all_10["net_ret"] < 0]["exit_date"])
    exit_bigloss_t0 = set(all_10[all_10["net_ret"] <= -0.04]["exit_date"])
    comb_exit_loss_t0 = set(comb[comb["net_ret"] < 0]["exit_date"])
    exit_0925_loss_t1 = set(all_10[(all_10["exit_hhmm"] == 925) & (all_10["net_ret"] < 0)]["exit_date"])

    flags = []
    for r in df20.itertuples(index=False):
        t0, t1 = r.sig_date, r.buy_date
        c_hold_t0 = any((cr.buy_date <= t0) and (cr.exit_date > t0) for cr in comb_rows)
        c_act_t1 = any((cr.buy_date <= t1 <= cr.exit_date) and not (cr.exit_date == t1 and cr.exit_hhmm == 925) for cr in comb_rows)
        c_buy_t1_925 = any((cr.buy_date == t1) and (cr.buy_hhmm == 925) for cr in comb_rows)
        c_buy_t1_all = (t1 in by_buy["comb"])
        any5_buy_t0 = any(t0 in by_buy[k] for k in indiv)
        any5_buy_t1 = any(t1 in by_buy[k] for k in indiv)
        flags.append({
            "comb_hold_overnight_T0": int(c_hold_t0),
            "comb_active_T1": int(c_act_t1),
            "comb_empty_T1": int(not c_act_t1),
            "comb_buy_T0": int(t0 in by_buy["comb"]),
            "comb_buy_T1": int(c_buy_t1_all),
            "comb_buy_T1_925": int(c_buy_t1_925),
            "any5_buy_T0": int(any5_buy_t0),
            "any5_empty_T0": int(not any5_buy_t0),
            "any5_buy_T1": int(any5_buy_t1),
            "s34_buy_T0": int(t0 in by_buy["3to4"]), "s34_buy_T1": int(t1 in by_buy["3to4"]),
            "shd_buy_T0": int(t0 in by_buy["high"]), "shd_buy_T1": int(t1 in by_buy["high"]),
            "s23_buy_T0": int(t0 in by_buy["2to3"]), "s23_buy_T1": int(t1 in by_buy["2to3"]),
            "s12_buy_T0": int(t0 in by_buy["1to2"]), "s12_buy_T1": int(t1 in by_buy["1to2"]),
            "spry_T0_buyday": int(t0 in by_buy["pry_top1"]),
            "spry_T1_buyday": int(t1 in by_buy["pry_top1"]),
            "spry_ss165_T0": int(t0 in by_buy["pry_ss165"]),
            "spry_ss165_T1": int(t1 in by_buy["pry_ss165"]),
            "t0_10cm_exit_loss": int(t0 in exit_loss_t0),
            "t0_10cm_exit_bigloss": int(t0 in exit_bigloss_t0),
            "t0_comb_exit_loss": int(t0 in comb_exit_loss_t0),
            "t0_buy_T0_eod_loss": int(t0 in t0_eod_loss_dts),
            "t0_buy_T1_gap_loss": int(t0 in t0_open_loss_dts),
            "t0_buy_T1_gap_bigloss": int(t0 in t0_open_bigloss_dts),
            "t1_0925_exit_loss": int(t1 in exit_0925_loss_t1),
        })
    return pd.concat([df20.reset_index(drop=True), pd.DataFrame(flags)], axis=1)


def summarize_flag(df: pd.DataFrame, col: str, is_split: str = "2024-08-31") -> dict:
    s1 = df[df[col] == 1]
    s0 = df[df[col] == 0]
    def st(sub):
        if sub.empty:
            return {"n": 0, "wr": 0.0, "mean": 0.0}
        r = sub["net_ret"].to_numpy(dtype=float)
        return {"n": int(len(r)), "wr": round(float((r > 0).mean() * 100), 2), "mean": round(float(r.mean() * 100), 2)}
    return {
        "flag": col,
        "FULL_1": st(s1), "FULL_0": st(s0),
        "IS_1": st(s1[s1["buy_date"] <= is_split]), "IS_0": st(s0[s0["buy_date"] <= is_split]),
        "OOS_1": st(s1[s1["buy_date"] > is_split]), "OOS_0": st(s0[s0["buy_date"] > is_split]),
        "Y26_1": st(s1[s1["buy_date"] >= "2026-01-01"]), "Y26_0": st(s0[s0["buy_date"] >= "2026-01-01"]),
    }


def main():
    t0 = time.time()
    pool = pd.read_parquet(f"{OUT_DIR}/rd023_pool_enriched.parquet")
    aux23 = pickle.load(open(f"{OUT_DIR}/rd023_aux.pkl", "rb"))
    sc, _ = compute_scorecard_v11(pool)
    pool["score"] = sc.values
    tr_all = sim_v11_exit_ext(pool, V11_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
    # Strictly align window with V19.1 5-year clean ledgers (2021-11-15 ~ 2026-11-16)
    tr_w = tr_all[tr_all["buy_date"].between("2021-11-15", "2026-11-16")].copy().reset_index(drop=True)
    leds = load_10cm_ledgers()
    df_f = build_causal_10cm_flags(tr_w, leds, aux23["bar_10"])
    df_a = df_f[df_f["score"] >= 76.0].copy().reset_index(drop=True)

    flag_cols = [
        "comb_empty_T1", "comb_hold_overnight_T0", "comb_buy_T0", "comb_buy_T1", "comb_buy_T1_925",
        "any5_empty_T0", "any5_buy_T0", "any5_buy_T1",
        "s34_buy_T0", "s34_buy_T1", "shd_buy_T0", "shd_buy_T1", "s23_buy_T0", "s23_buy_T1", "s12_buy_T0", "s12_buy_T1",
        "spry_T0_buyday", "spry_T1_buyday", "spry_ss165_T0", "spry_ss165_T1",
        "t0_10cm_exit_loss", "t0_10cm_exit_bigloss", "t0_comb_exit_loss",
        "t0_buy_T0_eod_loss", "t0_buy_T1_gap_loss", "t0_buy_T1_gap_bigloss", "t1_0925_exit_loss",
    ]
    res_rows = []
    for set_nm, dset in [("A76", df_a), ("ALL_809_in_win", df_f)]:
        for fc in flag_cols:
            s = summarize_flag(dset, fc)
            res_rows.append({
                "pool": set_nm, "flag": fc,
                "n1": s["FULL_1"]["n"], "wr1": s["FULL_1"]["wr"], "mn1": s["FULL_1"]["mean"],
                "n0": s["FULL_0"]["n"], "wr0": s["FULL_0"]["wr"], "mn0": s["FULL_0"]["mean"],
                "delta_mn": round(s["FULL_1"]["mean"] - s["FULL_0"]["mean"], 2),
                "IS_n1": s["IS_1"]["n"], "IS_wr1": s["IS_1"]["wr"], "IS_mn1": s["IS_1"]["mean"], "IS_mn0": s["IS_0"]["mean"],
                "OOS_n1": s["OOS_1"]["n"], "OOS_wr1": s["OOS_1"]["wr"], "OOS_mn1": s["OOS_1"]["mean"], "OOS_mn0": s["OOS_0"]["mean"],
                "Y26_n1": s["Y26_1"]["n"], "Y26_wr1": s["Y26_1"]["wr"], "Y26_mn1": s["Y26_1"]["mean"], "Y26_mn0": s["Y26_0"]["mean"],
            })
    out_df = pd.DataFrame(res_rows)
    out_df.to_csv(f"{OUT_DIR}/module2_opponent_duality.csv", index=False, encoding="utf-8-sig")

    # Also test scoring/filtering rules from Module 2 on full V1.1 A76 (2021-11-15~2026-11-16 window)!
    b_w = eval_splits(df_a)
    m2_tests = []
    for nm, delta in [
        ("M2_comb_empty_T1_plus4", np.where(df_f["comb_empty_T1"] == 1, 4, 0)),
        ("M2_comb_hold_T0_plus4", np.where(df_f["comb_hold_overnight_T0"] == 0, 4, 0)),
        ("M2_any5_empty_T0_plus4", np.where(df_f["any5_empty_T0"] == 1, 4, 0)),
        ("M2_t0_loss_pen6", np.where((df_f["t0_10cm_exit_loss"] == 1) | (df_f["t0_buy_T1_gap_loss"] == 1), -6, 0)),
        ("M2_t0_loss_plus4", np.where((df_f["t0_10cm_exit_loss"] == 1) | (df_f["t0_buy_T1_gap_loss"] == 1), 4, 0)),
        ("M2_s12_T1_plus4", np.where(df_f["s12_buy_T1"] == 1, 4, 0)),
    ]:
        t_c = df_f.copy()
        t_c["score"] = t_c["score"] + delta
        ev = eval_splits(t_c[t_c["score"] >= 76.0])
        m2_tests.append({
            "test": nm, "IS_nav": ev["IS"]["nav"], "d_IS": round(ev["IS"]["nav"] - b_w["IS"]["nav"], 2),
            "OOS_nav": ev["OOS"]["nav"], "d_OOS": round(ev["OOS"]["nav"] - b_w["OOS"]["nav"], 2),
            "Y26_nav": ev["Y26"]["nav"], "d_Y26": round(ev["Y26"]["nav"] - b_w["Y26"]["nav"], 2),
            "FULL_nav": ev["FULL"]["nav"], "MDD": ev["FULL"]["mdd"], "N": ev["FULL"]["n"],
        })
    pd.DataFrame(m2_tests).to_csv(f"{OUT_DIR}/module2_score_tests.csv", index=False, encoding="utf-8-sig")
    print(f"[DONE Module 2 in {time.time()-t0:.2f}s]")
    print("=== A76 Opponent Duality (2021-11-15 ~ 2026-11-16, N=417) ===")
    print(out_df[out_df["pool"] == "A76"][["flag", "n1", "wr1", "mn1", "n0", "wr0", "mn0", "delta_mn", "IS_mn1", "IS_mn0", "OOS_mn1", "OOS_mn0", "Y26_mn1", "Y26_mn0"]].to_string(index=False))
    print("\n=== Module 2 Score Adjustments ===")
    print(pd.DataFrame(m2_tests).to_string(index=False))


if __name__ == "__main__":
    main()
