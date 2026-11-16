#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import json, bisect
from collections import Counter, defaultdict
import numpy as np
import pandas as pd
from v3_lib import (
    OUT_DIR, SEASONS, MA_PAT, BAD_KPL,
    load_hs300_10y, load_meta, load_seasonal_prices
)

FEE = 0.0020

def has_dt(sorted_dts, lo_dt, hi_dt):
    if not sorted_dts: return False
    i = bisect.bisect_left(sorted_dts, lo_dt)
    return i < len(sorted_dts) and sorted_dts[i] <= hi_dt

def calc_d15(sub, rcol, ecol, excol):
    if sub.empty:
        return {"eq_n": 0, "slot_n": 0}
    d_ret = sub.groupby("buy_dt")[rcol].mean()
    d_ex = sub.groupby("buy_dt")[excol].mean()
    eq_nav = float((1 + d_ret).prod())
    eq_dd = abs(float(((1 + d_ret).cumprod() / (1 + d_ret).cumprod().cummax() - 1).min()))
    srt = sub.sort_values(["buy_dt", "p10_cnt", "amt_yi"], ascending=[True, False, False])
    sel, busy = [], "1990-01-01"
    for _, r in srt.iterrows():
        if r["buy_dt"] > busy:
            sel.append(r)
            busy = str(r[ecol])
    sdf = pd.DataFrame(sel)
    wr = float((sdf[rcol] > 0).mean())
    w = float(sdf[sdf[rcol] > 0][rcol].mean()) if (sdf[rcol] > 0).any() else 0.0
    l = abs(float(sdf[sdf[rcol] <= 0][rcol].mean())) if (sdf[sdf[rcol] <= 0].any() if False else (sdf[rcol] <= 0).any()) else 1e-6
    s_nav = float((1 + sdf[rcol]).prod())
    s_dd = abs(float(((1 + sdf[rcol]).cumprod() / (1 + sdf[rcol]).cumprod().cummax() - 1).min()))
    s_ex = float((1 + sdf[excol]).prod() - 1.0)
    return {
        "eq_n": int(len(sub)), "eq_nav": round(eq_nav, 2), "eq_dd": round(eq_dd * 100, 1),
        "slot_n": int(len(sdf)), "wr": round(wr * 100, 1), "pf": round(w / l, 2),
        "avg_ret": round(float(sdf[rcol].mean()) * 100, 2), "slot_nav": round(s_nav, 2),
        "slot_dd": round(s_dd * 100, 1), "ex_hs300_pct": round(s_ex * 100, 1)
    }

def main():
    hs300 = load_hs300_10y()
    name_map, date_plate, stock_season_tags, tape_dict, ma_dates, poison_dates = load_meta()
    df = load_seasonal_prices()

    # Build 10-day rolling KPL plate cumulative ZT counts
    all_kpl_dts = sorted(date_plate.keys())
    plate_10d_rank = {}
    for idx, dt in enumerate(all_kpl_dts):
        win = all_kpl_dts[max(0, idx - 9): idx + 1]
        cnt = Counter()
        for wdt in win:
            for p, stks in date_plate.get(wdt, {}).items():
                if p not in ("其他", "公告", "ST板块") and not any(b in p for b in BAD_KPL):
                    cnt[p] += len(stks)
        ranked = cnt.most_common(5)
        plate_10d_rank[dt] = ({p: c for p, c in cnt.items()}, [p for p, _ in ranked[:2]], [p for p, _ in ranked[:3]])

    g = df.groupby(["season_yr", "c6"], sort=False)
    df["bar_idx"] = g.cumcount()
    df["pre_c"] = g["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["mcap"] = df["close"] * df["oshare"] / 1e8
    df["amt_yi"] = df["amount"] / 1e8
    df["zt_px"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_px"] - 0.01) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
    df["is_st_like"] = (df["pct"] >= 0.047) & (df["pct"] <= 0.054) & (df["close"] == df["high"])
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_px"] - 0.01) & (df["low"] >= df["zt_px"] - 0.01)
    df["is_hs_zt"] = df["is_zt"] & (~df["is_yizi"])
    s_zt = df["is_zt"].astype(int)
    df["zt_streak"] = s_zt.groupby((~df["is_zt"]).cumsum()).cumsum()
    df["ma10"] = g["close"].transform(lambda s: s.rolling(10, min_periods=10).mean())
    df["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=15).mean())
    df["yizi_5d"] = g["is_yizi"].transform(lambda s: s.rolling(5, min_periods=1).sum())
    df["st_20d"] = g["is_st_like"].transform(lambda s: s.rolling(20, min_periods=1).sum())
    df["past15_zt"] = g["is_zt"].transform(lambda s: s.shift(1).rolling(15, min_periods=5).sum())
    df["past15_amt"] = g["amt_yi"].transform(lambda s: s.shift(1).rolling(15, min_periods=5).max())
    df["low_ma20"] = g["low"].transform(lambda s: s) / df["ma20"] - 1.0
    df["p10_min_ma20"] = df.groupby(["season_yr", "c6"], sort=False)["low_ma20"].transform(lambda s: s.shift(1).rolling(10, min_periods=3).min())

    fwd = {}
    for k in range(1, 33):
        fwd[f"fc_{k}"] = g["close"].shift(-k)
        fwd[f"fo_{k}"] = g["open"].shift(-k)
        fwd[f"fh_{k}"] = g["high"].shift(-k)
        fwd[f"fdt_{k}"] = g["dt_str"].shift(-k)
        fwd[f"fzt_{k}"] = g["is_zt"].shift(-k).fillna(False).infer_objects(copy=False)
        fwd[f"fyz_{k}"] = g["is_yizi"].shift(-k).fillna(False).infer_objects(copy=False)
        fwd[f"fma10_{k}"] = g["ma10"].shift(-k)
    df = pd.concat([df, pd.DataFrame(fwd, index=df.index)], axis=1)

    # Part 1: Verify exact Top 5 per season
    top5_all, top5_big = {}, {}
    for s_name, s_beg, s_end, _, _ in SEASONS:
        yr = int(s_beg[:4])
        w = df[(df["season_yr"] == yr) & (df["dt_str"] >= s_beg) & (df["dt_str"] <= s_end)]
        hs_cnt = w.groupby("c6")["is_hs_zt"].sum()
        ra, rb = [], []
        for c6 in hs_cnt[hs_cnt >= 6].index:
            gw = w[w["c6"] == c6]
            if len(gw) < 15 or gw["st_20d"].max() > 0: continue
            zts = gw[gw["is_zt"]]
            if zts.empty or zts.iloc[:4]["is_yizi"].sum() >= 3: continue
            fdt = zts["dt_str"].iloc[0]
            if has_dt(ma_dates.get(c6, []), (pd.Timestamp(fdt) - pd.Timedelta(days=90)).strftime("%Y-%m-%d"), s_end): continue
            tags = stock_season_tags.get((yr, c6), Counter()).most_common(3)
            ttag = tags[0][0] if tags else ""
            if any(b in ttag for b in BAD_KPL): continue
            p0 = float(zts["pre_c"].iloc[0])
            mv0 = float(zts["mcap"].iloc[0]) / (1.0 + float(zts["pct"].iloc[0]))
            ga = gw[gw["dt_str"] >= fdt]
            gain = float(ga["high"].max()) / p0 - 1.0
            if gain < 1.10 or mv0 < 15.0: continue
            it = {"c6": c6, "name": name_map.get(c6, c6), "first_zt": fdt, "p0": round(p0, 2),
                  "mv0": round(mv0, 1), "mv_max": round(float(ga["mcap"].max()), 1), "gain_pct": round(gain * 100, 1),
                  "hs_zts": int(hs_cnt[c6]), "theme": ttag}
            ra.append(it)
            if mv0 >= 50.0: rb.append(it)
        ra.sort(key=lambda x: x["gain_pct"], reverse=True)
        rb.sort(key=lambda x: x["gain_pct"], reverse=True)
        top5_all[s_name], top5_big[s_name] = ra[:5], rb[:5]

    print("=== 2025/26 All Non-M&A Top5 ===")
    for x in top5_all["2025/26"]: print(" ", x)
    print("=== 2025/26 BigCap(>=50亿) Non-M&A Top5 ===")
    for x in top5_big["2025/26"]: print(" ", x)

    # Part 2: Two-Stage Exit (Tight Initial Stop -> Profit Cushion -> MA10 Wave Lock) + Top1-in-MegaTheme
    # Pre-rank daily candidates within each KPL plate by amt_yi and zt_streak
    w_cand = df[(df["bar_idx"] >= 25) & (df["is_zt"]) & (~df["is_yizi"]) & (df["yizi_5d"] <= 1) & (df["st_20d"] == 0)].copy()
    day_plate_max_amt = defaultdict(float)
    day_plate_max_strk = defaultdict(int)
    for _, r in w_cand.iterrows():
        dt, c6 = r["dt_str"], r["c6"]
        for p, stks in date_plate.get(dt, {}).items():
            if c6 in stks:
                day_plate_max_amt[(dt, p)] = max(day_plate_max_amt[(dt, p)], float(r["amt_yi"]))
                day_plate_max_strk[(dt, p)] = max(day_plate_max_strk[(dt, p)], int(r["zt_streak"]))

    rows = []
    for _, r in w_cand.iterrows():
        yr, dt, c6 = int(r["season_yr"]), r["dt_str"], r["c6"]
        if not (f"{yr}-10-15" <= dt <= f"{yr+1}-01-15"): continue
        d1_dt, d1_o = r["fdt_1"], r["fo_1"]
        if pd.isna(d1_dt) or pd.isna(d1_o) or d1_o <= 0 or bool(r["fyz_1"]): continue
        if has_dt(ma_dates.get(c6, []), (pd.Timestamp(dt) - pd.Timedelta(days=120)).strftime("%Y-%m-%d"), dt): continue
        if has_dt(poison_dates.get(c6, []), (pd.Timestamp(dt) - pd.Timedelta(days=90)).strftime("%Y-%m-%d"), dt): continue
        tp_n, tp_r = tape_dict.get(dt, {}).get(c6, ("", ""))
        if MA_PAT.search(f"{tp_n} {tp_r}") or any(b in tp_n for b in BAD_KPL): continue

        cnt10_map, top2_10d, top3_10d = plate_10d_rank.get(dt, ({}, [], []))
        best_p, p10_c, is_top2_10d, is_leader = "", 0, False, False
        for p, stks in date_plate.get(dt, {}).items():
            if p not in ("其他", "公告", "ST板块") and not any(b in p for b in BAD_KPL) and c6 in stks:
                c10 = cnt10_map.get(p, len(stks))
                if c10 > p10_c:
                    best_p, p10_c = p, c10
                if p in top2_10d: is_top2_10d = True
                if float(r["amt_yi"]) >= day_plate_max_amt[(dt, p)] * 0.75 or int(r["zt_streak"]) >= day_plate_max_strk[(dt, p)]:
                    is_leader = True
        if not best_p or p10_c < 10: continue
        ogap = d1_o / r["close"] - 1.0
        if not (0.005 <= ogap <= 0.068): continue

        is_m1 = (r["zt_streak"] in (3, 4)) and is_top2_10d and is_leader
        is_m2 = (r["zt_streak"] == 1) and (r["past15_zt"] >= 3) and (r["p10_min_ma20"] >= -0.02) and is_top2_10d and is_leader
        if not (is_m1 or is_m2): continue

        # Two-stage exit:
        # Day 1 (buy day): if NOT ZT and close < buy_px * 1.01, exit Day 2 open!
        # Once ZT on Day 1 or peak close >= buy_px * 1.10 -> wave_mode = True: hold until close < max(MA10*0.985, buy_px*1.01)
        ex_dt, ex_px, h_days = r["fdt_2"], r["fo_2"], 1
        wave_on = False
        for k in range(1, 31):
            ck, ok1, dtk1 = r[f"fc_{k}"], r[f"fo_{k+1}"], r[f"fdt_{k+1}"]
            if pd.isna(ck) or pd.isna(ok1) or ok1 <= 0:
                ex_dt, ex_px, h_days = r[f"fdt_{k}"], ck, k
                break
            if bool(r[f"fzt_{k}"]) or ck >= d1_o * 1.09:
                wave_on = True
            if not wave_on:
                # Tight verification on k=1..2
                if k == 1 and ck < d1_o * 1.01:
                    ex_dt, ex_px, h_days = dtk1, ok1, k
                    break
                if k >= 2 and not bool(r[f"fzt_{k}"]):
                    ex_dt, ex_px, h_days = dtk1, ok1, k
                    break
            else:
                m10 = r[f"fma10_{k}"]
                stop_lvl = max((m10 * 0.985) if not pd.isna(m10) else 0.0, d1_o * 1.005)
                if ck < stop_lvl:
                    ex_dt, ex_px, h_days = dtk1, ok1, k
                    break
        else:
            ex_dt, ex_px, h_days = r["fdt_30"], r["fc_30"], 30

        # Pure break exit for comparison
        ebrk_dt, ebrk_px = r["fdt_2"], r["fo_2"]
        for k in range(1, 31):
            if pd.isna(r[f"fo_{k+1}"]) or r[f"fo_{k+1}"] <= 0:
                ebrk_dt, ebrk_px = r[f"fdt_{k}"], r[f"fc_{k}"]; break
            if not bool(r[f"fzt_{k}"]):
                ebrk_dt, ebrk_px = r[f"fdt_{k+1}"], r[f"fo_{k+1}"]; break

        if pd.isna(ex_px) or ex_px <= 0 or pd.isna(ebrk_px) or ebrk_px <= 0: continue
        ret_2s = (ex_px / d1_o - 1.0) - FEE
        ret_brk = (ebrk_px / d1_o - 1.0) - FEE
        hs_s = hs300[(hs300.index >= pd.Timestamp(d1_dt)) & (hs300.index <= pd.Timestamp(ex_dt))]
        hs_r = (hs_s.iloc[-1] / hs_s.iloc[0] - 1.0) if len(hs_s) >= 2 else 0.0
        rows.append({
            "season": f"{yr}/{str(yr+1)[2:]}", "sig_dt": dt, "buy_dt": d1_dt, "exit_dt": ex_dt, "ebrk_dt": ebrk_dt,
            "c6": c6, "name": name_map.get(c6, c6), "theme": best_p, "p10_cnt": p10_c,
            "is_m1": bool(is_m1), "is_m2": bool(is_m2), "mcap": round(float(r["mcap"]), 1),
            "close_t0": round(float(r["close"]), 2), "amt_yi": round(float(r["amt_yi"]), 2),
            "buy_px": round(float(d1_o), 2), "exit_px": round(float(ex_px), 2), "hold": h_days,
            "ret_2s": ret_2s, "ex_2s": ret_2s - hs_r, "ret_brk": ret_brk, "ex_brk": ret_brk - hs_r
        })

    rdf = pd.DataFrame(rows)
    rdf.to_csv(f"{OUT_DIR}/v3_1_ledger_cross_year_big.csv", index=False, encoding="utf-8-sig")
    out_json = {"top5_all_non_ma": top5_all, "top5_big50_non_ma": top5_big, "strategies": {}}
    configs = {
        "All25_350_TwoStage": (rdf[rdf["mcap"].between(25, 350)], "ret_2s", "exit_dt", "ex_2s"),
        "Big45_300_Low22_TwoStage": (rdf[rdf["mcap"].between(45, 300) & (rdf["close_t0"] <= 22)], "ret_2s", "exit_dt", "ex_2s"),
        "Big45_300_Low22_BreakOnly": (rdf[rdf["mcap"].between(45, 300) & (rdf["close_t0"] <= 22)], "ret_brk", "ebrk_dt", "ex_brk"),
        "Big45_300_Low22_M2Wave_TwoStage": (rdf[rdf["is_m2"] & rdf["mcap"].between(45, 300) & (rdf["close_t0"] <= 22)], "ret_2s", "exit_dt", "ex_2s"),
        "Big45_300_Low22_M1Brk_TwoStage": (rdf[rdf["is_m1"] & rdf["mcap"].between(45, 300) & (rdf["close_t0"] <= 22)], "ret_2s", "exit_dt", "ex_2s"),
    }
    for k, (s, rc, ec, exc) in configs.items():
        out_json["strategies"][k] = {
            lbl: calc_d15(s[s["buy_dt"] >= d0], rc, ec, exc)
            for lbl, d0 in [("10Y", "2016-10-01"), ("5Y", "2021-10-01"), ("3Y", "2023-10-01"), ("Rec", "2025-10-01")]
        }
        print(f"\n[{k}]")
        for lbl, m in out_json["strategies"][k].items():
            print(f"  {lbl:3s}: {m}")

    print("\n=== 2025/26 Trades in Big45_300_Low22_TwoStage ===")
    s25 = rdf[(rdf["buy_dt"] >= "2025-10-01") & rdf["mcap"].between(45, 300) & (rdf["close_t0"] <= 22)]
    if not s25.empty:
        print(s25[["buy_dt", "exit_dt", "c6", "name", "theme", "is_m1", "is_m2", "mcap", "buy_px", "exit_px", "ret_2s", "ret_brk"]].to_string(index=False))
    with open(f"{OUT_DIR}/v3_1_summary_cross_year_big.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
