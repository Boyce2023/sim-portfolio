#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 1b: Strictly leak-free audit of S1_hit_zt, S2 (10cm tide -> 20cm arb), S3, S4, S5, S6 variants."""
import bisect, json, pickle, time
from collections import defaultdict
import numpy as np
import pandas as pd
from backtest_utils import calc_d15_suite, simulate_fixed_hold
from layer_events_pit import BASE, NON_THEME

OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def build_strict_prev_kpl(plate_stats: dict) -> tuple[dict, dict]:
    """Build strictly < dt (T-1) theme membership for T0_close, and <= dt for T1_open."""
    hist = defaultdict(list)
    with open(f"{BASE}/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            obj = json.loads(ln)
            dt = obj.get("date", "")
            if dt < "2020-11-01" or dt > "2026-11-23":
                continue
            for pl in obj.get("plates", []):
                pn = str(pl.get("plate", ""))
                if pn in NON_THEME:
                    continue
                for s in pl.get("stocks", []):
                    c6 = str(s[0]).strip()[:6].zfill(6)
                    if c6.startswith(("30", "688", "689")):
                        hist[c6].append((dt, pn))
    hist_dts = {c6: [x[0] for x in v] for c6, v in hist.items()}
    return hist, hist_dts


def run_case(cases: list, proto: str, name: str, sub: pd.DataFrame, entry: str, hold: int, sh300: dict, ew20: dict, exit_rule: str = "fixed"):
    if sub.empty:
        cases.append({"proto": proto, "variant": name, "entry": entry, "hold": hold, "IS_1sN": 0})
        print(f"[{proto}] {name:42s} | EMPTY")
        return
    tr = simulate_fixed_hold(sub, entry, hold, fee=0.0030, exit_rule=exit_rule, score_col="score")
    m = calc_d15_suite(tr, sh300, ew20)
    row = {"proto": proto, "variant": name, "entry": entry, "hold": hold, "exit_rule": exit_rule}
    for w in ("FULL", "IS", "OOS", "2026"):
        mw = m[w]
        for k in ("raw_n", "n_1s", "wr_1s", "po_1s", "nav_1s", "mdd_1s", "nav_3s", "ew_nav", "ex5_1s", "fee50_1s", "ex_hs300_1s", "ex_ew20_1s"):
            row[f"{w}_{k}"] = mw.get(k, 0)
    cases.append(row)
    print(f"[{proto}] {name:42s} | IS: N={row['IS_n_1s']:3d} WR={row['IS_wr_1s']:5.1f}% 1s={row['IS_nav_1s']:6.2f}x ew={row['IS_ew_nav']:5.2f}x | "
          f"OOS: N={row['OOS_n_1s']:3d} WR={row['OOS_wr_1s']:5.1f}% 1s={row['OOS_nav_1s']:6.2f}x ew={row['OOS_ew_nav']:5.2f}x | 26: {row['2026_nav_1s']:5.2f}x")


def main():
    t0 = time.time()
    df = pd.read_parquet(f"{OUT_DIR}/cache_20cm_panel.parquet")
    aux = pickle.load(open(f"{OUT_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, ew20, plate_stats = aux["sh300"], aux["ew20_daily"], aux["plate_stats"]
    hist, hist_dts = build_strict_prev_kpl(plate_stats)

    # Strictly < dt KPL 30d peer theme stats (no T0 post-close leak!)
    n = len(df)
    prev_p10zt = np.zeros(n, dtype=np.int16)
    prev_p10yz = np.zeros(n, dtype=np.int16)
    c6_a, dt_a = df["c6"].values, df["dt"].values
    from datetime import datetime, timedelta
    cal30 = {}
    for i in range(n):
        c6, dt = c6_a[i], dt_a[i]
        hd = hist_dts.get(c6)
        if not hd:
            continue
        d30 = cal30.get(dt)
        if d30 is None:
            d30 = (datetime.strptime(dt, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
            cal30[dt] = d30
        lo = bisect.bisect_left(hd, d30)
        hi = bisect.bisect_left(hd, dt)  # strictly < dt!
        if hi > lo:
            pns = {hist[c6][j][1] for j in range(lo, hi)}
            m10, my10 = 0, 0
            for pn in pns:
                ps = plate_stats.get((dt, pn))
                if ps:
                    if ps[1] > m10: m10 = ps[1]
                    if ps[2] > my10: my10 = ps[2]
            prev_p10zt[i], prev_p10yz[i] = m10, my10
    df["prev_p10zt"] = prev_p10zt
    df["prev_p10yz"] = prev_p10yz

    base = df[df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0)].copy()
    cases = []

    # 1. Leak-free S1_hit_zt (NO T0 kpl_10zt!)
    s1_hit = base[base["is_touch_zt"] & (base["prev_streak"] == 0) & (~base["is_yizi_zt"])].copy()
    s1_hit["score"] = -s1_hit["prev_pos20"].fillna(0.5) * 100.0 + s1_hit["prev_p10zt"] * 2.0
    run_case(cases, "S1_LEAKFREE", "S1_打板含炸板分母_无泄露_持T1", s1_hit, "T0_hit_zt", 1, sh300, ew20)
    run_case(cases, "S1_LEAKFREE", "S1_打板含炸板分母_无泄露_持T2", s1_hit, "T0_hit_zt", 2, sh300, ew20)
    run_case(cases, "S1_LEAKFREE", "S1_打板低位pos20<0.4_持T1", s1_hit[s1_hit["prev_pos20"] <= 0.40], "T0_hit_zt", 1, sh300, ew20)

    # 2. Leak-free S2: 10cm tide -> 20cm arb (T0_close using prev_p10zt, T1_open using kpl_hist_10zt_max)
    s2_t0_4 = base[(base["prev_p10zt"] >= 4) & (~base["is_zt"]) & (base["ret"].between(0.05, 0.15)) & (base["tox_t0_90d"] == 0)].copy()
    s2_t0_4["score"] = s2_t0_4["prev_p10zt"] * 5.0 + s2_t0_4["ret"] * 50.0
    run_case(cases, "S2", "S2_T0尾_10cm>=4_20cm大阳5~15_T1", s2_t0_4, "T0_close", 1, sh300, ew20)
    run_case(cases, "S2", "S2_T0尾_10cm>=4_20cm大阳5~15_T2", s2_t0_4, "T0_close", 2, sh300, ew20)
    run_case(cases, "S2", "S2_T0尾_10cm>=6_20cm大阳5~15_T2", s2_t0_4[s2_t0_4["prev_p10zt"] >= 6], "T0_close", 2, sh300, ew20)
    s2_t0_yz = base[(base["prev_p10yz"] >= 2) & (~base["is_zt"]) & (base["ret"].between(0.03, 0.15)) & (base["tox_t0_90d"] == 0)].copy()
    s2_t0_yz["score"] = s2_t0_yz["prev_p10yz"] * 10.0 - s2_t0_yz["pos20"] * 20.0
    run_case(cases, "S2", "S2_T0尾_10cm一字>=2_20cm套利_T2", s2_t0_yz, "T0_close", 2, sh300, ew20)

    # S2 T1_open (strictly PIT at T+1 09:25!)
    s2_t1_pm = base[(base["kpl_hist_10yz_max"] >= 2) & (base["ret"].between(0.03, 0.205)) & (base["pos20"] <= 0.50) & (base["f1_o_pct"].between(-0.04, 0.05)) & (base["tox_90d"] == 0)].copy()
    s2_t1_pm["score"] = s2_t1_pm["kpl_hist_10yz_max"] * 10.0 - s2_t1_pm["pos20"] * 20.0
    run_case(cases, "S2", "S2_T1开_10cm一字>=2_低位20cm分歧_T2", s2_t1_pm, "T1_open", 2, sh300, ew20)
    run_case(cases, "S2", "S2_T1开_10cm一字>=2_低位20cm分歧_T3", s2_t1_pm, "T1_open", 3, sh300, ew20)

    s2_t1_4 = base[(base["kpl_hist_10zt_max"] >= 6) & (base["ret"].between(0.03, 0.15)) & (base["pos20"] <= 0.50) & (base["f1_o_pct"].between(-0.05, 0.02)) & (base["tox_90d"] == 0)].copy()
    s2_t1_4["score"] = s2_t1_4["kpl_hist_10zt_max"] * 5.0 - s2_t1_4["pos20"] * 20.0
    run_case(cases, "S2", "S2_T1开_10cm>=6_低位20cm绿平开_T2", s2_t1_4, "T1_open", 2, sh300, ew20)

    # 3. Deeper check on S3 (First-board true-yang broken board) & S1<-4% & S4<-3% & S5 low-open & S6 earn/IR
    s1_deep = base[base["is_zt"] & (base["streak"] == 1) & (~base["is_yizi_zt"]) & (base["f1_o_pct"] < -0.04) & (base["tox_90d"] == 0)].copy()
    s1_deep["score"] = -s1_deep["f1_o_pct"] * 100.0
    run_case(cases, "S1_DEEP", "S1_首板低开<-4%_按低开排序_T2", s1_deep, "T1_open", 2, sh300, ew20)
    run_case(cases, "S1_DEEP", "S1_首板低开<-4%_持有T3", s1_deep, "T1_open", 3, sh300, ew20)

    s3_1b = base[(base["prev_streak"] == 1) & (~base["is_zt"]) & (base["is_true_yang"]) & (base["tox_90d"] == 0)].copy()
    s3_1b["score"] = -s3_1b["f1_o_pct"] * 50.0 + (s3_1b["pos20"] <= 0.5).astype(int) * 10.0
    run_case(cases, "S3", "S3_首板真阳_深低开<-4%_T2", s3_1b[s3_1b["f1_o_pct"] < -0.04], "T1_open", 2, sh300, ew20)
    run_case(cases, "S3", "S3_首板真阳_绿开-6~0%_低位pos<=0.5_T2", s3_1b[s3_1b["f1_o_pct"].between(-0.06, 0.0) & (s3_1b["prev_pos20"] <= 0.50)], "T1_open", 2, sh300, ew20)
    run_case(cases, "S3", "S3_首板真阳_绿平-4~+3%_暗牌XQ<4_T2", s3_1b[s3_1b["f1_o_pct"].between(-0.04, 0.03) & (s3_1b["xq_t1_pre"] < 4)], "T1_open", 2, sh300, ew20)

    # S5 low-open check (is S5 still dead if not chasing high open?)
    s5_lo = base[(base["lhb_inst_net"] >= 3000) & (base["lhb_lh_cnt"] == 0) & (base["tox_90d"] == 0) & (base["f1_o_pct"].between(-0.05, 0.02))].copy()
    s5_lo["score"] = s5_lo["lhb_inst_net"] / 1000.0
    run_case(cases, "S5", "S5_机构>=3kw_零拉萨_绿平开-5~+2%_T3", s5_lo, "T1_open", 3, sh300, ew20)
    run_case(cases, "S5", "S5_机构>=3kw_零拉萨_绿平开-5~+2%_T5", s5_lo, "T1_open", 5, sh300, ew20)

    # S6 clean check (earn & IR only, which have full 6y coverage)
    s6_e = base[(base["cat_earn_3d"] == 1) & (base["tox_90d"] == 0) & (base["vol_ratio5"] >= 1.5) & (base["bias20"] > 0)].copy()
    s6_e["score"] = s6_e["vol_ratio5"]
    run_case(cases, "S6", "S6_业绩预增扭亏+放量站MA20_T2", s6_e, "T1_open", 2, sh300, ew20)
    run_case(cases, "S6", "S6_业绩预增扭亏+放量站MA20_T3", s6_e, "T1_open", 3, sh300, ew20)

    pd.DataFrame(cases).to_csv(f"{OUT_DIR}/part2_step1b_audit.csv", index=False)
    print(f"[DONE] Step 1b in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
