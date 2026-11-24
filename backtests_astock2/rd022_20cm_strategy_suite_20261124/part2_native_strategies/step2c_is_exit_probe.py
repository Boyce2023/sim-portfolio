#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2c: IS-only (<= 2024-08-31) Exit Tree Optimization across P1, P2, P3 (zero OOS peeking!)."""
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def sim_dynamic_exit(pool: pd.DataFrame, rule: str, fee: float = 0.0030) -> pd.DataFrame:
    """
    100% path-consistent daily dynamic exit rules after buying at T+1 open (f1_ao):
      - 'T2_close': fixed sell at T+2 close
      - 'T3_close': fixed sell at T+3 close
      - 'T2_ty_imm': ride f1_zt; on T+2 if weak close on f1 (f1_ac < f1_ao) & f2_o_pct < 0 -> cut at f2_ao;
                     if f2 is true_yang & f2_ac > f1_ac -> immunity to T+3 close; else T+2 close.
      - 'T2_tp10_weakcut': ride f1_zt; if f1_ac < f1_ao and f2_o_pct < -0.01 -> cut at f2_ao;
                           on T+2 pre-market limit TP at f1_ac*1.10 (fill at max(f2_ao, lim) if f2_ah >= lim);
                           else if f2_ty and f2_ac > f1_ac -> hold to T+3 close (with +10% TP); else T+2 close.
      - 'T2_tp08_ty': ride f1_zt; on T+2 pre-market limit TP at f1_ac*1.08; if not filled and f2_ty and f2_ac > f1_ac -> T+3 close (TP +8%); else T+2 close.
      - 'T2_gap_cut_only': ride f1_zt; if f1 closed < f1_ao*0.98 and f2_o_pct < 0 -> cut at f2_ao; if f2_o_pct >= 0.06 -> sell f2_ao; else T+2 close.
      - 'T3_ma5_tp12': ride f1_zt; T+2..T+5 pre-market limit TP at prev_ac*1.12, cut if close < ma5 (from T+2) or max T+5.
    All sells defer if sealed 20cm limit-down at sell_k!
    """
    rows = []
    for r in pool.itertuples(index=False):
        if not r.f1_buyable or not r.f1_dt or np.isnan(r.f1_ao) or r.f1_ao <= 0:
            continue
        b_px = float(r.f1_ao)
        b_dt = r.f1_dt
        sell_k, s_px = 2, np.nan

        if rule == "T2_close":
            sell_k = 2
        elif rule == "T3_close":
            sell_k = 3
        elif rule == "T2_zt_ride":
            k = 2
            while k < 10 and getattr(r, f"f{k}_zt", False):
                k += 1
            sell_k = k
        elif rule in ("T2_ty_imm", "T2_tp10_weakcut", "T2_tp08_ty", "T2_gap_cut_only"):
            k = 2
            # If f1 sealed ZT, ride ZT streak first
            if r.f1_zt:
                while k < 10 and getattr(r, f"f{k}_zt", False):
                    k += 1
                sell_k = k
            else:
                f1_ac, f1_ao = float(r.f1_ac), float(r.f1_ao)
                f2_ao, f2_ah, f2_ac = float(r.f2_ao), float(r.f2_ah), float(r.f2_ac)
                f2_op = float(r.f2_o_pct) if not np.isnan(r.f2_o_pct) else 0.0
                if rule == "T2_gap_cut_only":
                    if (f1_ac < f1_ao * 0.98 and f2_op < 0.0) or (f2_op >= 0.06):
                        s_px, sell_k = f2_ao, 2
                    else:
                        sell_k = 2
                elif rule == "T2_ty_imm":
                    if f1_ac < f1_ao and f2_op < 0.0:
                        s_px, sell_k = f2_ao, 2
                    elif r.f2_ty and f2_ac > f1_ac and not np.isnan(r.f3_ac):
                        sell_k = 3
                    else:
                        sell_k = 2
                elif rule in ("T2_tp10_weakcut", "T2_tp08_ty"):
                    tp = 1.10 if rule == "T2_tp10_weakcut" else 1.08
                    if rule == "T2_tp10_weakcut" and f1_ac < f1_ao and f2_op < -0.01:
                        s_px, sell_k = f2_ao, 2
                    else:
                        lim2 = f1_ac * tp
                        if not np.isnan(f2_ah) and f2_ah >= lim2 and r.f2_sellable:
                            s_px, sell_k = max(f2_ao, lim2), 2
                        elif r.f2_ty and f2_ac > f1_ac and not np.isnan(r.f3_ac):
                            lim3 = f2_ac * tp
                            if not np.isnan(r.f3_ah) and r.f3_ah >= lim3 and r.f3_sellable:
                                s_px, sell_k = max(float(r.f3_ao), lim3), 3
                            else:
                                sell_k = 3
                        else:
                            sell_k = 2
        elif rule == "T3_ma5_tp12":
            sell_k = 5
            for k in range(2, 6):
                ac_p = float(getattr(r, f"f{k-1}_ac", np.nan))
                ah_k = float(getattr(r, f"f{k}_ah", np.nan))
                ao_k = float(getattr(r, f"f{k}_ao", np.nan))
                ac_k = float(getattr(r, f"f{k}_ac", np.nan))
                ma5_k = float(getattr(r, f"f{k}_ma5", np.nan))
                if np.isnan(ac_k):
                    sell_k = max(2, k - 1)
                    break
                lim = ac_p * 1.12
                if ah_k >= lim and getattr(r, f"f{k}_sellable", False):
                    s_px, sell_k = max(ao_k, lim), k
                    break
                if k >= 2 and ac_k < ma5_k and not getattr(r, f"f{k}_zt", False) and getattr(r, f"f{k}_sellable", False):
                    sell_k = k
                    break

        # Enforce limit-down sell deferral when exiting at close (or if s_px is nan)
        if np.isnan(s_px):
            while sell_k < 11 and not getattr(r, f"f{sell_k}_sellable", False):
                sell_k += 1
            while sell_k >= 2 and np.isnan(getattr(r, f"f{sell_k}_ac", np.nan)):
                sell_k -= 1
            if sell_k < 2:
                continue
            s_px = float(getattr(r, f"f{sell_k}_ac"))
        s_dt = getattr(r, f"f{sell_k}_dt")
        if not s_dt or np.isnan(s_px) or s_px <= 0:
            continue
        gross = s_px / b_px - 1.0
        net = (1.0 + gross) * (1.0 - fee) - 1.0
        rows.append({"sig_date": r.dt, "buy_date": b_dt, "exit_date": s_dt, "c6": r.c6, "gross_ret": gross, "net_ret": net, "score": getattr(r, "score", 0.0)})
    return pd.DataFrame(rows)


def main():
    df = pd.read_parquet(f"{OUT_DIR}/cache_20cm_panel.parquet")
    base = df[df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0) & (df["tox_90d"] == 0) & (df["f1_dt"] <= "2024-08-31")].copy()
    base["score"] = 0.0
    pools = {
        "P1_S1": base[base["is_zt"] & (base["streak"] == 1) & (~base["is_yizi_zt"]) & (base["f1_o_pct"].between(-0.10, -0.035))],
        "P2_S3": base[(base["prev_streak"] >= 1) & (~base["is_zt"]) & (base["is_true_yang"]) & (base["to"] <= 35.0) & (base["f1_o_pct"].between(-0.07, 0.02))],
        "P3_S4": base[base["is_touch_zt"] & (~base["is_zt"]) & (base["ret"] < 0.12) & (base["to"] <= 30.0) & (base["f1_o_pct"].between(-0.10, -0.025))],
    }
    rules = ["T2_close", "T3_close", "T2_zt_ride", "T2_gap_cut_only", "T2_ty_imm", "T2_tp10_weakcut", "T2_tp08_ty", "T3_ma5_tp12"]
    for pname, pl in pools.items():
        print(f"\n=== IS EXIT OPTIMIZATION: {pname} (pool={len(pl)}) ===")
        for rl in rules:
            tr = sim_dynamic_exit(pl, rl)
            r = tr["net_ret"].to_numpy()
            w, l = r[r > 0], r[r <= 0]
            po = w.mean() / abs(l.mean()) if len(w) and len(l) else 0
            ew = np.prod(1.0 + tr.groupby("buy_date")["net_ret"].mean().to_numpy())
            print(f"  {rl:18s} | N={len(r):4d} WR={len(w)/len(r)*100:5.1f}% PO={po:4.2f} mean={r.mean()*100:+5.2f}% ew={ew:6.2f}x")


if __name__ == "__main__":
    main()
