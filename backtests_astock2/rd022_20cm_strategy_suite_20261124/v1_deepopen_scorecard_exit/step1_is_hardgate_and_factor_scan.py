#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 1 (IS-ONLY <= 2024-08-31):
1. Audit 133 rescued ST false positives.
2. Compare hard gate boundaries (open gap windows & mkt20_zt_cnt hard vs soft) on IS.
3. Comprehensive 6-dimension factor bucket & inflection point scan on IS.
"""
import os, pickle, sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True

PART2_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"


def sim_t2_strict(df: pd.DataFrame, fee: float = 0.0030) -> pd.DataFrame:
    """Pure T+2 close baseline with strict sealed-20cm-DT (f{k}_sellable_strict) deferral."""
    rows = []
    for idx, r in enumerate(df.itertuples(index=False)):
        b_px = float(r.f1_ao)
        if np.isnan(b_px) or b_px <= 0:
            continue
        k = 2
        while k < 11 and not getattr(r, f"f{k}_sellable_strict", False):
            k += 1
        while k >= 2 and np.isnan(getattr(r, f"f{k}_ac", np.nan)):
            k -= 1
        if k < 2:
            continue
        s_px = float(getattr(r, f"f{k}_ac"))
        s_dt = getattr(r, f"f{k}_dt")
        if not s_dt or np.isnan(s_px) or s_px <= 0:
            continue
        gross = s_px / b_px - 1.0
        net = (1.0 + gross) * (1.0 - fee) - 1.0
        rows.append({
            "idx": idx, "sig_date": r.dt, "buy_date": r.f1_dt, "exit_date": s_dt,
            "c6": r.c6, "score": float(getattr(r, "score", 0.0)), "net_ret": net, "hold_k": k
        })
    return pd.DataFrame(rows)


def one_slot_stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"raw_n": 0, "n1": 0, "wr": 0.0, "mean": 0.0, "po": 0.0, "nav1": 1.0, "ew": 1.0, "mdd": 0.0}
    srt = tr.sort_values(["buy_date", "score", "c6"], ascending=[True, False, True])
    free_dt = ""
    taken = []
    for r in srt.itertuples(index=False):
        if free_dt == "" or r.buy_date > free_dt:
            taken.append(r.net_ret)
            free_dt = r.exit_date
    r1 = np.array(taken, dtype=float)
    w, l = r1[r1 > 0], r1[r1 <= 0]
    po = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else 99.0
    cum = np.cumprod(1.0 + r1)
    pk = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
    mdd = float(np.max((pk - cum) / pk) * 100.0)
    ew = float(np.prod(1.0 + tr.groupby("buy_date")["net_ret"].mean().to_numpy()))
    return {
        "raw_n": int(len(tr)), "n1": int(len(r1)),
        "wr": round(float((r1 > 0).mean() * 100.0), 2),
        "mean": round(float(tr["net_ret"].mean() * 100.0), 2),
        "po": round(po, 2),
        "nav1": round(float(cum[-1]), 3),
        "ew": round(ew, 3),
        "mdd": round(mdd, 2),
    }


def main():
    df = pd.read_parquet(f"{OUT_DIR}/p1_clean_candidates.parquet")

    # 1. Spot check rescued ST rows
    rescued = df[df["is_st_pit"] == 1]
    print(f"[AUDIT] Rescued old-ST false positives in clean pool: {len(rescued)} rows, sample names:")
    print(rescued[["dt", "c6", "name", "dl", "f1_o_pct"]].head(15).to_string(index=False))

    # 2. IS ONLY slice
    df_is = df[df["f1_dt"] <= "2024-08-31"].copy().reset_index(drop=True)
    df_is["score"] = -df_is["f1_o_pct"] * 100.0  # neutral open tie-break for skeleton scan

    print("\n=== [IS ONLY] HARD GATE BOUNDARY COMPARISON (Pure T+2 Strict Close) ===")
    gates = [
        ("open[-12%,-2%] all_mkt", df_is["f1_o_pct"].between(-0.12, -0.02)),
        ("open[-12%,-2%] mkt20<16", df_is["f1_o_pct"].between(-0.12, -0.02) & (df_is["mkt20_zt_cnt"] < 16)),
        ("open[-12%,-2%] mkt20<15", df_is["f1_o_pct"].between(-0.12, -0.02) & (df_is["mkt20_zt_cnt"] < 15)),
        ("open[-10%,-3.5%] all_mkt", df_is["f1_o_pct"].between(-0.10, -0.035)),
        ("open[-10%,-3.5%] mkt20<16", df_is["f1_o_pct"].between(-0.10, -0.035) & (df_is["mkt20_zt_cnt"] < 16)),
        ("open[-10%,-3.5%] mkt20<15", df_is["f1_o_pct"].between(-0.10, -0.035) & (df_is["mkt20_zt_cnt"] < 15)),
        ("open[-10%,-3.0%] all_mkt", df_is["f1_o_pct"].between(-0.10, -0.030)),
        ("open[-10%,-3.0%] mkt20<16", df_is["f1_o_pct"].between(-0.10, -0.030) & (df_is["mkt20_zt_cnt"] < 16)),
        ("open[-10%,-3.0%] mkt20<15", df_is["f1_o_pct"].between(-0.10, -0.030) & (df_is["mkt20_zt_cnt"] < 15)),
        ("open[-10%,-2.5%] mkt20<16", df_is["f1_o_pct"].between(-0.10, -0.025) & (df_is["mkt20_zt_cnt"] < 16)),
        ("open[-9%,-3.5%] mkt20<16", df_is["f1_o_pct"].between(-0.09, -0.035) & (df_is["mkt20_zt_cnt"] < 16)),
        ("open[-9%,-3.0%] mkt20<16", df_is["f1_o_pct"].between(-0.09, -0.030) & (df_is["mkt20_zt_cnt"] < 16)),
        ("open[-12%,-3.0%] mkt20<16", df_is["f1_o_pct"].between(-0.12, -0.030) & (df_is["mkt20_zt_cnt"] < 16)),
    ]
    for lbl, m in gates:
        tr = sim_t2_strict(df_is[m])
        st = one_slot_stats(tr)
        print(f"  {lbl:28s} | N={st['raw_n']:3d}/{st['n1']:3d} WR={st['wr']:5.2f}% mn={st['mean']:+5.2f}% PO={st['po']:4.2f} 1s={st['nav1']:6.3f}x EW={st['ew']:6.3f}x MDD={st['mdd']:5.1f}%")

    # 3. Exhaustive 6-Dim Factor Scan on IS wide base ([-12%, -2%]) and core base ([-10%, -3.0%])
    for b_lbl, mask_b in [
        ("WIDE[-12,-2]", df_is["f1_o_pct"].between(-0.12, -0.02)),
        ("CORE[-10,-3]", df_is["f1_o_pct"].between(-0.10, -0.030)),
    ]:
        sub = df_is[mask_b].copy().reset_index(drop=True)
        tr = sim_t2_strict(sub)
        sub_valid = sub.iloc[tr["idx"].values].copy().reset_index(drop=True)
        sub_valid["net2"] = tr["net_ret"].values
        sub_valid["buy_date"] = tr["buy_date"].values
        base_mn = sub_valid["net2"].mean() * 100.0
        base_wr = (sub_valid["net2"] > 0).mean() * 100.0
        print(f"\n=== [IS FACTOR SCAN on {b_lbl}] N={len(sub_valid)}, WR={base_wr:.2f}%, mean={base_mn:+.2f}% ===")

        def chk(grp, nm, cond):
            m = np.asarray(cond(sub_valid), dtype=bool)
            s = sub_valid[m]
            if len(s) < 5:
                return
            r = s["net2"].to_numpy()
            wr = (r > 0).mean() * 100.0
            mn = r.mean() * 100.0
            t = mn / (r.std(ddof=1) * 100.0 / np.sqrt(len(r))) if (len(r) > 1 and r.std(ddof=1) > 0) else 0.0
            ew = np.prod(1.0 + s.groupby("buy_date")["net2"].mean().to_numpy())
            mn_not = sub_valid[~m]["net2"].mean() * 100.0 if (~m).sum() else 0.0
            print(f"  [{grp:6s}] {nm:30s} | N={len(s):4d} WR={wr:5.1f}% mn={mn:+6.2f}% (d={mn-base_mn:+5.2f},not={mn_not:+5.2f}) t={t:+5.2f} ew={ew:6.2f}x")

        # Dim 1: Chips & Free Float
        chk("D1_chp", "lock_top10 >= 40%", lambda d: d["lock_top10"].fillna(0) >= 40)
        chk("D1_chp", "lock_top10 >= 45%", lambda d: d["lock_top10"].fillna(0) >= 45)
        chk("D1_chp", "lock_top10 >= 50%", lambda d: d["lock_top10"].fillna(0) >= 50)
        chk("D1_chp", "lock_top10 < 35%", lambda d: d["lock_top10"].fillna(40) < 35)
        chk("D1_chp", "real_free_mcap <= 25", lambda d: d["real_free_mcap"] <= 25)
        chk("D1_chp", "real_free_mcap <= 30", lambda d: d["real_free_mcap"] <= 30)
        chk("D1_chp", "real_free_mcap > 60", lambda d: d["real_free_mcap"] > 60)
        chk("D1_chp", "mcap <= 45", lambda d: d["mcap"] <= 45)
        chk("D1_chp", "mcap > 100", lambda d: d["mcap"] > 100)
        chk("D1_chp", "real_to < 20%", lambda d: d["real_to"] < 20)
        chk("D1_chp", "real_to [20%,45%)", lambda d: d["real_to"].between(20, 44.999))
        chk("D1_chp", "real_to >= 45%", lambda d: d["real_to"] >= 45)
        chk("D1_chp", "to < 10%", lambda d: d["to"] < 10)
        chk("D1_chp", "to [10%,25%)", lambda d: d["to"].between(10, 24.999))
        chk("D1_chp", "to >= 25%", lambda d: d["to"] >= 25)
        chk("D1_chp", "vol_ratio5 < 1.8", lambda d: d["vol_ratio5"] < 1.8)
        chk("D1_chp", "vol_ratio5 >= 4.5", lambda d: d["vol_ratio5"] >= 4.5)

        # Dim 2: Price, Position, Abn space, ZT Tape
        chk("D2_pos", "open [-12,-10)", lambda d: d["f1_o_pct"].between(-0.12, -0.10001))
        chk("D2_pos", "open [-10,-8)", lambda d: d["f1_o_pct"].between(-0.10, -0.08001))
        chk("D2_pos", "open [-8,-5.5)", lambda d: d["f1_o_pct"].between(-0.08, -0.05501))
        chk("D2_pos", "open [-5.5,-3.5)", lambda d: d["f1_o_pct"].between(-0.055, -0.03501))
        chk("D2_pos", "open [-3.5,-2.0]", lambda d: d["f1_o_pct"].between(-0.035, -0.02))
        chk("D2_pos", "bias20 <= 0.05", lambda d: d["bias20"] <= 0.05)
        chk("D2_pos", "bias20 <= 0.12", lambda d: d["bias20"] <= 0.12)
        chk("D2_pos", "bias20 > 0.25", lambda d: d["bias20"] > 0.25)
        chk("D2_pos", "box20_prev <= 0.35", lambda d: d["box20_prev"] <= 0.35)
        chk("D2_pos", "box20_prev > 0.55", lambda d: d["box20_prev"] > 0.55)
        chk("D2_pos", "prev_pos20 <= 0.40", lambda d: d["prev_pos20"] <= 0.40)
        chk("D2_pos", "prev_pos20 (0.40,0.75]", lambda d: (d["prev_pos20"] > 0.40) & (d["prev_pos20"] <= 0.75))
        chk("D2_pos", "prev_pos20 > 0.75", lambda d: d["prev_pos20"] > 0.75)
        chk("D2_pos", "pos60 <= 0.50", lambda d: d["pos60"] <= 0.50)
        chk("D2_pos", "dist_3d30 >= 0.10", lambda d: d["dist_3d30"] >= 0.10)
        chk("D2_pos", "dist_3d30 < 0.05", lambda d: d["dist_3d30"] < 0.05)
        chk("D2_pos", "zt_cnt_60d >= 2", lambda d: d["zt_cnt_60d"] >= 2)
        chk("D2_pos", "zt_cnt_60d >= 3", lambda d: d["zt_cnt_60d"] >= 3)
        chk("D2_pos", "zt_cnt_20d >= 2", lambda d: d["zt_cnt_20d"] >= 2)
        chk("D2_pos", "close <= 15", lambda d: d["close"] <= 15)
        chk("D2_pos", "close (15,35]", lambda d: (d["close"] > 15) & (d["close"] <= 35))
        chk("D2_pos", "close > 35", lambda d: d["close"] > 35)
        chk("D2_pos", "zt_hhmm <= 1000", lambda d: d["zt_hhmm"] <= 1000)
        chk("D2_pos", "zt_hhmm (1000,1330]", lambda d: (d["zt_hhmm"] > 1000) & (d["zt_hhmm"] <= 1330))
        chk("D2_pos", "zt_hhmm >= 1400", lambda d: (d["zt_hhmm"] >= 1400) & (d["zt_hhmm"] < 9999))
        chk("D2_pos", "zt_hhmm >= 1430", lambda d: (d["zt_hhmm"] >= 1430) & (d["zt_hhmm"] < 9999))
        chk("D2_pos", "zt_obc == 0", lambda d: d["zt_obc"] == 0)
        chk("D2_pos", "zt_obc >= 2", lambda d: d["zt_obc"] >= 2)
        chk("D2_pos", "zt_seal_ratio >= 0.10", lambda d: d["zt_seal_ratio"] >= 0.10)
        chk("D2_pos", "zt_seal_ratio < 0.03", lambda d: (d["zt_seal_ratio"] > 0) & (d["zt_seal_ratio"] < 0.03))
        chk("D2_pos", "prev_ret5 <= 0", lambda d: d["prev_ret5"] <= 0)
        chk("D2_pos", "amp >= 0.18", lambda d: d["amp"] >= 0.18)

        # Dim 3: LHB Seats
        chk("D3_lhb", "lhb_has == 1", lambda d: d["lhb_has"] == 1)
        chk("D3_lhb", "lhb_inst_net > 0", lambda d: d["lhb_inst_net"] > 0)
        chk("D3_lhb", "lhb_inst_net >= 1500", lambda d: d["lhb_inst_net"] >= 1500)
        chk("D3_lhb", "lhb_inst_net < -1000", lambda d: d["lhb_inst_net"] < -1000)
        chk("D3_lhb", "lhb_lh_net_pos == 1", lambda d: d["lhb_lh_net_pos"] == 1)
        chk("D3_lhb", "lhb_lh_share >= 0.15", lambda d: d["lhb_lh_share"] >= 0.15)
        chk("D3_lhb", "lhb_lh_cnt >= 2", lambda d: d["lhb_lh_cnt"] >= 2)
        chk("D3_lhb", "lhb_lh_cnt == 0 & has", lambda d: (d["lhb_has"] == 1) & (d["lhb_lh_cnt"] == 0))
        chk("D3_lhb", "lhb_surf == 1", lambda d: d["lhb_surf"] == 1)
        chk("D3_lhb", "lhb_quant >= 1", lambda d: d["lhb_quant"] >= 1)
        chk("D3_lhb", "lhb_quant>=1 & inst<=0", lambda d: (d["lhb_quant"] >= 1) & (d["lhb_inst_net"] <= 0))
        chk("D3_lhb", "lhb_north > 0", lambda d: d["lhb_north"] > 0)

        # Dim 4: Theme & Sentiment & Board
        chk("D4_thm", "mkt20_zt <= 5", lambda d: d["mkt20_zt_cnt"] <= 5)
        chk("D4_thm", "mkt20_zt [6,15]", lambda d: d["mkt20_zt_cnt"].between(6, 15))
        chk("D4_thm", "mkt20_zt >= 16", lambda d: d["mkt20_zt_cnt"] >= 16)
        chk("D4_thm", "mkt20_zt >= 12", lambda d: d["mkt20_zt_cnt"] >= 12)
        chk("D4_thm", "mkt10_zt > 70", lambda d: d["mkt10_zt_cnt"] > 70)
        chk("D4_thm", "mkt10_dt >= 15", lambda d: d["mkt10_dt_cnt"] >= 15)
        chk("D4_thm", "mkt20_dt >= 3", lambda d: d["mkt20_dt_cnt"] >= 3)
        chk("D4_thm", "csi_5d <= -0.02", lambda d: d["csi_5d"] <= -0.02)
        chk("D4_thm", "csi_5d >= 0.02", lambda d: d["csi_5d"] >= 0.02)
        chk("D4_thm", "kpl_in == 1", lambda d: d["kpl_in"] == 1)
        chk("D4_thm", "kpl_elo >= 115", lambda d: d["kpl_elo"] >= 115)
        chk("D4_thm", "kpl_elo >= 125", lambda d: d["kpl_elo"] >= 125)
        chk("D4_thm", "kpl_10zt >= 3", lambda d: d["kpl_10zt"] >= 3)
        chk("D4_thm", "kpl_20zt >= 2", lambda d: d["kpl_20zt"] >= 2)
        chk("D4_thm", "kpl_10_20_zt >= 5", lambda d: d["kpl_10_20_zt"] >= 5)
        chk("D4_thm", "kpl_peers_f1o_ex >= 0", lambda d: d["kpl_peers_f1o_ex"] >= 0.0)
        chk("D4_thm", "kpl_peers_f1o_ex < -0.015", lambda d: d["kpl_peers_f1o_ex"] < -0.015)
        chk("D4_thm", "f1_mkt20_prev1b_open >= 0", lambda d: d["f1_mkt20_prev1b_open"] >= 0.0)
        chk("D4_thm", "f1_mkt20_prev1b_open < -0.02", lambda d: d["f1_mkt20_prev1b_open"] < -0.02)
        chk("D4_thm", "f1_mkt10_0925_zt < 10", lambda d: d["f1_mkt10_0925_zt"] < 10)
        chk("D4_thm", "is_chinext == 1 (30x)", lambda d: d["is_chinext"] == 1)
        chk("D4_thm", "is_chinext == 0 (688/689)", lambda d: d["is_chinext"] == 0)
        chk("D4_thm", "is_tech == 1", lambda d: d["is_tech"] == 1)

        # Dim 5: Community & Notices (<09:00)
        chk("D5_inf", "xq_t1_0900 == 0", lambda d: d["xq_t1_0900"] == 0)
        chk("D5_inf", "xq_t1_0900 >= 1", lambda d: d["xq_t1_0900"] >= 1)
        chk("D5_inf", "xq_t1_0900 >= 2", lambda d: d["xq_t1_0900"] >= 2)
        chk("D5_inf", "xq_3d_0900 >= 4", lambda d: d["xq_3d_0900"] >= 4)
        chk("D5_inf", "gb_t1_0900 <= 20", lambda d: d["gb_t1_0900"] <= 20)
        chk("D5_inf", "gb_surge >= 3.5", lambda d: d["gb_surge"] >= 3.5)
        chk("D5_inf", "cat_earn_pos_3d == 1", lambda d: d["cat_earn_pos_3d"] == 1)
        chk("D5_inf", "cat_earn_neg_3d == 1", lambda d: d["cat_earn_neg_3d"] == 1)
        chk("D5_inf", "cat_earn_any_3d == 1", lambda d: d["cat_earn_any_3d"] == 1)
        chk("D5_inf", "cat_clarify_3d == 1", lambda d: d["cat_clarify_3d"] == 1)
        chk("D5_inf", "cat_any == 1", lambda d: d["cat_any"] == 1)
        chk("D5_inf", "ir_10d_0900 >= 1", lambda d: d["ir_10d_0900"] >= 1)
        chk("D5_inf", "ir_30d_0900 >= 1", lambda d: d["ir_30d_0900"] >= 1)

        # Dim 6: Calendar
        chk("D6_cal", "f1_weekday == 0 (Mon)", lambda d: d["f1_weekday"] == 0)
        chk("D6_cal", "f1_weekday == 4 (Fri)", lambda d: d["f1_weekday"] == 4)
        chk("D6_cal", "f1_month in (01,04)", lambda d: d["f1_month"].isin(["01", "04"]))
        chk("D6_cal", "f1_month == 05", lambda d: d["f1_month"] == "05")


if __name__ == "__main__":
    main()
