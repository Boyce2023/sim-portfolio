#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Study #27 (Lab H): 100% PIT Real Free-Float & 09:35/09:40 Plunge Human-Switch 5Y Backtest."""
import os, sys, json, time, sqlite3
import numpy as np
import pandas as pd

LAB_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab"
sys.path.append(LAB_DIR)
from v16_parameterized_engine import load_engine_data_cache, evaluate_parameterized_v16, create_parameterized_trade_engine, V16_DEFAULT_KNOBS
from lab_e2_gates_and_trial_v1 import build_pit_sensors_and_theme_matrix, evaluate_ablation_experiment

RAW_HOLDERS = f"{LAB_DIR}/pit_top10_freeholders_cache.json"
SUM_HOLDERS = f"{LAB_DIR}/pit_top10_summary.json"
SUPP_5M = f"{LAB_DIR}/lab_h_switch_5m_cache.json"
OUT_JSON = f"{LAB_DIR}/lab_h_results.json"
TAPE_DB = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/zt_micro_tape_5y_pit.db"
DB_5M_OLD = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/data_5y/firstboard_5m_5y_pit.db"

def load_holders_idx():
    if os.path.exists(SUM_HOLDERS):
        return json.load(open(SUM_HOLDERS, "r", encoding="utf-8"))
    raw = json.load(open(RAW_HOLDERS, "r", encoding="utf-8"))
    idx = {}
    for c, items in raw.items():
        by_ed = {}
        for it in items or []:
            nd, ed, rt = (it.get("NOTICE_DATE") or "")[:10], (it.get("END_DATE") or "")[:10], float(it.get("FREE_HOLDNUM_RATIO") or 0)
            if nd and ed:
                rec = by_ed.setdefault(ed, [nd, 0.0, 0.0])
                rec[0] = min(rec[0], nd); rec[1] += rt
                if rt >= 5.0: rec[2] += rt
        if by_ed:
            idx[c] = sorted([[v[0], ed, round(min(95.0, v[1]), 2), round(min(95.0, v[2]), 2)] for ed, v in by_ed.items()])
    json.dump(idx, open(SUM_HOLDERS, "w", encoding="utf-8"))
    return idx

def pit_lock(idx, c6, dt):
    valid = [r for r in idx.get(c6, []) if r[0] < dt]
    if not valid: return None, 38.0, 25.0
    b = max(valid, key=lambda x: x[1])
    return b[1], b[2], b[3]

def calc_st(tl):
    if not tl: return {"n": 0, "wr": 0.0, "po": 0.0, "mean": 0.0, "nav": 1.0, "mdd": 0.0}
    arr = np.array([t["net_ret"] for t in tl], dtype=float)
    w, l = arr[arr > 0], arr[arr <= 0]
    po = float(w.mean() / abs(l.mean())) if len(w) > 0 and len(l) > 0 and l.mean() < 0 else 99.0
    nav, pk, mdd = 1.0, 1.0, 0.0
    for r in arr:
        nav *= (1 + r); pk = max(pk, nav); mdd = max(mdd, (pk - nav) / pk)
    return {"n": len(arr), "wr": round(float((arr > 0).mean() * 100), 1), "po": round(po, 2), "mean": round(float(arr.mean() * 100), 2), "nav": round(nav, 2), "mdd": round(mdd * 100, 1)}

def ensure_5m_for_switch(bars_5m, need_pairs):
    supp = json.load(open(SUPP_5M, "r")) if os.path.exists(SUPP_5M) else {}
    todo = [(c, d) for c, d in need_pairs if (c, d) not in bars_5m and f"{c}_{d}" not in supp]
    if todo:
        conn = sqlite3.connect(DB_5M_OLD)
        rem = []
        for c, d in todo:
            if d <= "2023-08-23":
                rows = conn.execute("SELECT substr(bar_time,9,4), open, high, low, close, volume, amount FROM firstboard_5m_kline WHERE trade_date=? AND substr(sec_code,4,6)=? ORDER BY bar_time", (d, c)).fetchall()
                if rows: supp[f"{c}_{d}"] = [[int(x[0]), x[1], x[2], x[3], x[4], x[5], x[6]] for x in rows]; continue
            rem.append((c, d))
        conn.close()
        json.dump(supp, open(SUPP_5M, "w"))
    for k, rows in supp.items():
        c, d = k.split("_")
        if (c, d) not in bars_5m:
            bars_5m[(c, d)] = np.array(rows, dtype=float)

def main():
    cache = load_engine_data_cache()
    evaluate_parameterized_v16(cache=cache)
    sensors_map, dom_no_dragon, melee_days = build_pit_sensors_and_theme_matrix(cache)
    hist_fb, p_lookup, bars_5m = cache["hist_fb"], cache["price_lookup"], cache["bars_5m_map"]
    idx_h = load_holders_idx()

    # Compute exact PIT real free float on hist_fb
    rf10_arr = np.array([mc * (1.0 - pit_lock(idx_h, c, d)[1] / 100.0) for c, d, mc in zip(hist_fb["c6"], hist_fb["d2_dt"], hist_fb["mcap"])])
    orig_mcap = hist_fb["mcap"].copy()

    # 1. Test V17 (exact live V17: 96 trades, 66.7% WR, 249.04x, exit_1430_rush=True) with statutory mcap vs real_free_mcap
    v17_kw = dict(cache=cache, sensors_map=sensors_map, dom_no_dragon=dom_no_dragon, melee_days=melee_days, allow_l1b=True, sq_min=-999.0, exit_1430_rush=True, rule_alpha=True, rule_beta=True, rule_gamma=True)
    res_p1 = {}
    print("=== PART 1: V17 线上主策略(96笔 249.04x) 真实自由流通盘替换对账 ===")
    for tag, use_rf, gcap in [("V17基准_同板一字卡法定90亿", False, None), ("V17_同板一字改卡真流通90亿", True, None), ("V17_全域硬卡真流通<=60亿", True, 60.0), ("V17_全域硬卡真流通<=45亿", True, 45.0)]:
        hist_fb["mcap"] = rf10_arr if use_rf else orig_mcap
        if gcap is not None:
            hist_fb["is_buyable_open_bak"] = hist_fb["is_buyable_open"].copy()
            hist_fb["is_buyable_open"] = hist_fb["is_buyable_open"] & (rf10_arr <= gcap)
        r = evaluate_ablation_experiment(tag, tag, **v17_kw)
        if gcap is not None:
            hist_fb["is_buyable_open"] = hist_fb["is_buyable_open_bak"]
        tl = r["trades_list"]
        s_ex25 = calc_st([t for t in tl if not t["buy_date"].startswith("2025")])
        s_3y = calc_st([t for t in tl if t["buy_date"] >= "2024-01-01"])
        s_jul = calc_st([t for t in tl if t["buy_date"] >= "2026-07-01"])
        res_p1[tag] = {"5y": calc_st(tl), "daily_eq": r["daily_eq"], "ex25": s_ex25, "3y": s_3y, "jul": s_jul, "trades": tl}
        print(f"  {tag:<26s}: 5Y {r['trades']:3d}笔 WR={r['wr']:4.1f}% PO={r['payoff']:4.2f} 单仓={r['nav_1s']:6.2f}x 等权={r['daily_eq']:5.2f}x MDD={r['mdd_1s']:4.1f}% | 去25:{s_ex25['n']}笔/{s_ex25['wr']}%/{s_ex25['nav']}x | 3Y:{s_3y['n']}笔/{s_3y['wr']}% | 7月+:{s_jul['n']}笔/{s_jul['wr']}%")
    hist_fb["mcap"] = orig_mcap
    b_set = {(t["buy_date"], t["c6"]) for t in res_p1["V17基准_同板一字卡法定90亿"]["trades"]}
    rf_trades = [t for t in res_p1["V17_同板一字改卡真流通90亿"]["trades"] if (t["buy_date"], t["c6"]) not in b_set]
    print("  V17改卡真流通90亿新增成交明细:", [(t["buy_date"], t["c6"], t["name"], t["net_ret"]) for t in rf_trades])

    # 2. Part 2: Backfill missing 5m bars ONLY on untriggered/09:35-09:40 dip days (~35 days -> ~90 pairs, 3s!)
    qual_df = hist_fb[(hist_fb["_sv_eval"] >= 304.8) & (hist_fb["d2_dt"] >= "2022-01-01") & (hist_fb["d2_dt"] <= "2026-11-10")].sort_values(["d2_dt", "_sv_eval"], ascending=[True, False])
    by_day_all = {d: g for d, g in hist_fb[(hist_fb["d2_dt"] >= "2022-01-01") & (hist_fb["d2_dt"] <= "2026-11-10")].groupby("d2_dt")}
    need_r0 = [(grp.iloc[0]["c6"], d2) for d2, grp in qual_df.groupby("d2_dt") if (grp.iloc[0]["c6"], d2) not in bars_5m]
    if need_r0: ensure_5m_for_switch(bars_5m, need_r0)
    need_5m = set()
    for d2, grp in qual_df.groupby("d2_dt"):
        r0 = grp.iloc[0]; c6 = r0["c6"]; b0 = p_lookup.get((c6, d2))
        if not b0: continue
        o0, h0, _, _, zt0, _, _, _ = b0
        trig0 = min(zt0, max(round(o0 * 1.012, 2), round(float(r0["close"]) * 1.065, 2)))
        a0 = bars_5m.get((c6, d2))
        is_dip = (h0 < trig0) or (a0 is not None and len(a0) >= 2 and (float(a0[0, 4]) / o0 - 1.0 <= -0.012 or float(a0[1, 4]) / o0 - 1.0 <= -0.015))
        if not is_dip: continue
        ddf = by_day_all[d2]
        ot = ddf[(ddf["c6"] != c6) & ddf["d2_o_pct"].between(0.005, 0.092)]
        for cc6 in set(ot[ot["plate"] == r0["plate"]]["c6"]).union(set(ot.sort_values("score_wk", ascending=False).head(6)["c6"])):
            need_5m.add((cc6, d2))
    print(f"  Supplementing 5m bars for {len(need_5m)} backup candidate pairs...")
    ensure_5m_for_switch(bars_5m, need_5m)

    conn = sqlite3.connect(TAPE_DB)
    tdf = pd.read_sql_query("SELECT substr(sec_code,1,6) as c6, trade_date, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape", conn); conn.close()
    tape_map = {(r.c6, r.trade_date if "-" in str(r.trade_date) else f"{r.trade_date[:4]}-{r.trade_date[4:6]}-{r.trade_date[6:8]}"): (str(r.first_seal_time or ""), float(r.seal_amount or 0)) for r in tdf.itertuples()}
    eng = create_parameterized_trade_engine(p_lookup, cache["all_dts"], cache["dt_to_idx"], bars_5m, V16_DEFAULT_KNOBS)

    def sim_px(rd, px):
        rc = dict(rd); rc["gap_days"] = 3; rc["score_active"] = 999.0; rc["buy_open_lead"] = 0.05
        res = eng(rc)
        if not res: return None
        res["buy_price"] = round(float(px), 2); res["net_ret"] = round((res["exit_price"] / res["buy_price"]) * 0.998 - 1.0, 4)
        return res

    print("\n=== PART 2: 100%真实5分钟K线 榜一09:35/09:40未触发且跳水切换回测 (2022-2026) ===")
    res_p2 = {}
    for mname, pool, nb, drop_thr, req_trig, hold_mult, min_sc, max_rf in [
        ("S1_盲切全场第2分_0935现价直买", "mkt", 1, -0.015, False, 0.0, 0.0, 9999.0),
        ("S2_盲切同题材老二_0935现价直买", "theme", 1, -0.015, False, 0.0, 0.0, 9999.0),
        ("S3_同题材老二+0935站稳开盘价+挂点火买", "theme", 1, -0.015, True, 0.998, 0.0, 9999.0),
        ("S4_同题材老二+0935红盘拉升>=1%+真流通<=35亿+点火", "theme", 1, -0.015, True, 1.010, 0.0, 35.0),
        ("S5_同题材老二+补27分>=275+站稳开盘+点火", "theme", 1, -0.015, True, 0.998, 275.0, 9999.0),
        ("S6_全场备选score>=275+0935拉升>=1%+点火", "mkt", 1, -0.015, True, 1.010, 275.0, 9999.0),
        ("S7_0940观察窗_同题材老二+站稳开盘+点火", "theme", 2, -0.020, True, 1.000, 0.0, 9999.0),
        ("S8_0940观察窗_同题材老二+站稳+真流通<=30亿+点火", "theme", 2, -0.020, True, 1.000, 0.0, 30.0),
    ]:
        sw_tl = []
        scut = "09:35:00" if nb == 1 else "09:40:00"
        for d2, grp in qual_df.groupby("d2_dt"):
            r0 = grp.iloc[0].to_dict(); c6 = r0["c6"]; b0 = p_lookup.get((c6, d2))
            if not b0: continue
            o0, _, _, _, zt0, _, _, _ = b0
            if ((r0.get("gap_days", 1) >= 3) and (r0.get("score_active", 0) >= 310.0) and (r0.get("buy_open_lead", 0) >= 0.025)) or o0 >= zt0 - 0.005: continue
            trig0 = min(zt0, max(round(o0 * 1.012, 2), round(float(r0["close"]) * 1.065, 2)))
            a0 = bars_5m.get((c6, d2))
            if a0 is None or len(a0) < nb or float(a0[:nb, 2].max()) >= trig0 or (float(a0[nb-1, 4]) / o0 - 1.0) > drop_thr: continue
            ot = by_day_all[d2]
            ot = ot[(ot["c6"] != c6) & ot["d2_o_pct"].between(0.010, 0.088)]
            cands = ot[ot["plate"] == r0["plate"]].sort_values("score_active", ascending=False) if pool == "theme" else ot.sort_values("score_active", ascending=False).head(6)
            ebon = 27.0 if pool == "theme" else 0.0
            for _, cr in cands.iterrows():
                cd = cr.to_dict(); cc6 = cd["c6"]; bb = p_lookup.get((cc6, d2))
                if not bb or bb[0] >= bb[4] - 0.005: continue
                ob, hb, _, _, ztb, _, iztb, _ = bb
                tp = tape_map.get((cc6, d2))
                if iztb and tp and tp[0] and tp[0] <= scut: continue
                ab = bars_5m.get((cc6, d2))
                if ab is None or len(ab) < nb or float(ab[:nb, 2].max()) >= ztb - 0.005: continue
                cbt = float(ab[nb-1, 4])
                if hold_mult > 0 and cbt < ob * hold_mult: continue
                if float(cd.get("score_active", 0)) + ebon < min_sc: continue
                rfv = float(cd["mcap"]) * (1.0 - pit_lock(idx_h, cc6, d2)[1] / 100.0)
                if rfv > max_rf: continue
                trigb = min(ztb, max(round(ob * 1.012, 2), round(float(cd["close"]) * 1.065, 2)))
                post_h = float(ab[nb:, 2].max()) if len(ab) > nb else hb
                if req_trig:
                    if trigb >= ztb - 0.005 or post_h < trigb: continue
                    bpx = max(round(cbt, 2), trigb) if cbt >= trigb else trigb
                else:
                    bpx = round(cbt, 2)
                sim = sim_px(cd, bpx)
                if sim:
                    sim["plate"] = cd["plate"]; sim["rf10"] = round(rfv, 1); sim["replaced"] = r0["name"]
                    sw_tl.append(sim); break
        s5, sex, s3, sj = calc_st(sw_tl), calc_st([t for t in sw_tl if not t["buy_date"].startswith("2025")]), calc_st([t for t in sw_tl if t["buy_date"] >= "2024-01-01"]), calc_st([t for t in sw_tl if t["buy_date"] >= "2026-07-01"])
        res_p2[mname] = {"5y": s5, "ex25": sex, "3y": s3, "jul": sj, "sample": [(t["buy_date"], t["replaced"]+"->"+t["name"], t["net_ret"]) for t in sw_tl]}
        print(f"  {mname:<48s}: 5Y {s5['n']:2d}笔 WR={s5['wr']:4.1f}% PO={s5['po']:4.2f} 均={s5['mean']:+5.2f}% 净值={s5['nav']:5.2f}x MDD={s5['mdd']:4.1f}% | 去25:{sex['n']}笔/WR={sex['wr']}%/均{sex['mean']:+.2f}% | 3Y:{s3['n']}笔/{s3['wr']}% | 7月+:{sj['n']}笔/{sj['wr']}%")
        if 0 < len(sw_tl) <= 15:
            print("    明细:", [(t["buy_date"], t["replaced"]+"->"+t["name"], f"{t['net_ret']*100:+.1f}%") for t in sw_tl])

    json.dump({"part1_v17_freefloat": {k: {kk: vv for kk, vv in v.items() if kk != "trades"} for k, v in res_p1.items()}, "part2_switch": res_p2}, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
