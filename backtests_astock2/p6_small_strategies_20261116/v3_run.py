#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import json, bisect
from collections import Counter
import numpy as np
import pandas as pd
from v3_lib import (
    OUT_DIR, SEASONS, MA_PAT, BAD_KPL,
    load_hs300_10y, load_meta, load_seasonal_prices
)

FEE = 0.0020  # 双边合计千二摩擦

def has_date_in_range(sorted_dts, lo_dt, hi_dt):
    if not sorted_dts:
        return False
    i = bisect.bisect_left(sorted_dts, lo_dt)
    return i < len(sorted_dts) and sorted_dts[i] <= hi_dt

def main():
    hs300 = load_hs300_10y()
    name_map, date_plate, stock_season_tags, tape_dict, ma_dates, poison_dates = load_meta()
    df = load_seasonal_prices()

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
    df["ma5"] = g["close"].transform(lambda s: s.rolling(5, min_periods=5).mean())
    df["ma10"] = g["close"].transform(lambda s: s.rolling(10, min_periods=10).mean())
    df["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=15).mean())
    df["zt_5d"] = g["is_zt"].transform(lambda s: s.rolling(5, min_periods=3).sum())
    df["yizi_5d"] = g["is_yizi"].transform(lambda s: s.rolling(5, min_periods=1).sum())
    df["st_20d"] = g["is_st_like"].transform(lambda s: s.rolling(20, min_periods=1).sum())
    df["past15_zt"] = g["is_zt"].transform(lambda s: s.shift(1).rolling(15, min_periods=5).sum())
    df["past15_max_strk"] = g["zt_streak"].transform(lambda s: s.shift(1).rolling(15, min_periods=5).max())
    df["past15_max_amt"] = g["amt_yi"].transform(lambda s: s.shift(1).rolling(15, min_periods=5).max())
    df["low_vs_ma20"] = df["low"] / df["ma20"] - 1.0
    df["past10_min_ma20"] = g["low_vs_ma20"].transform(lambda s: s.shift(1).rolling(10, min_periods=3).min())

    fwd_cols = {}
    for k in range(1, 35):
        fwd_cols[f"fc_{k}"] = g["close"].shift(-k)
        fwd_cols[f"fo_{k}"] = g["open"].shift(-k)
        fwd_cols[f"fl_{k}"] = g["low"].shift(-k)
        fwd_cols[f"fdt_{k}"] = g["dt_str"].shift(-k)
        fwd_cols[f"fzt_{k}"] = g["is_zt"].shift(-k).fillna(False)
        fwd_cols[f"fyz_{k}"] = g["is_yizi"].shift(-k).fillna(False)
        fwd_cols[f"fma10_{k}"] = g["ma10"].shift(-k)
        fwd_cols[f"fma20_{k}"] = g["ma20"].shift(-k)
    df = pd.concat([df, pd.DataFrame(fwd_cols, index=df.index)], axis=1)

    # Part 1: Real Market Non-M&A Cross-Year Leaders (10-15 ~ 01-31)
    real_top5_all, real_top5_big = {}, {}
    for s_name, s_beg, s_end, _, _ in SEASONS:
        yr = int(s_beg[:4])
        w = df[(df["season_yr"] == yr) & (df["dt_str"] >= s_beg) & (df["dt_str"] <= s_end)]
        hs_cnt = w.groupby("c6")["is_hs_zt"].sum()
        cands = hs_cnt[hs_cnt >= 6].index.tolist()
        rows_all, rows_big = [], []
        for c6 in cands:
            gw = w[w["c6"] == c6]
            if len(gw) < 15 or gw["st_20d"].max() > 0:
                continue
            zts = gw[gw["is_zt"]]
            if zts.empty or zts.iloc[:4]["is_yizi"].sum() >= 3:
                continue
            first_dt = zts["dt_str"].iloc[0]
            lo_chk = (pd.Timestamp(first_dt) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
            if has_date_in_range(ma_dates.get(c6, []), lo_chk, s_end):
                continue
            tags = stock_season_tags.get((yr, c6), Counter()).most_common(3)
            top_tag = tags[0][0] if tags else ""
            if any(b in top_tag for b in BAD_KPL):
                continue
            p0 = float(zts["pre_c"].iloc[0])
            mv0 = float(zts["mcap"].iloc[0]) / (1.0 + float(zts["pct"].iloc[0]))
            g_after = gw[gw["dt_str"] >= first_dt]
            p_max = float(g_after["high"].max())
            mv_max = float(g_after["mcap"].max())
            gain = p_max / p0 - 1.0
            if gain < 1.10 or mv0 < 15.0:
                continue
            item = {
                "c6": c6, "name": name_map.get(c6, c6), "first_zt": first_dt,
                "p_start": round(p0, 2), "mv_start": round(mv0, 1), "mv_peak": round(mv_max, 1),
                "gain_pct": round(gain * 100, 1), "hs_zts": int(hs_cnt[c6]),
                "theme": top_tag or (tape_dict.get(first_dt, {}).get(c6, ("", ""))[0])
            }
            rows_all.append(item)
            if mv0 >= 50.0:
                rows_big.append(item)
        rows_all.sort(key=lambda x: x["gain_pct"], reverse=True)
        rows_big.sort(key=lambda x: x["gain_pct"], reverse=True)
        real_top5_all[s_name] = rows_all[:5]
        real_top5_big[s_name] = rows_big[:5]

    # Part 2: Point-in-Time Mechanical Backtest (10-15 ~ 01-15 entry)
    def plate_info(dt, c6):
        pdic = date_plate.get(dt, {})
        ranked = sorted([(p, len(stks)) for p, stks in pdic.items() if p not in ("其他", "公告", "ST板块")], key=lambda x: x[1], reverse=True)
        top2 = {p for p, _ in ranked[:2]}
        top3 = {p for p, _ in ranked[:3]}
        best_p, best_cnt, in2, in3 = "", 0, False, False
        for p, stks in pdic.items():
            if p not in ("其他", "公告", "ST板块") and c6 in stks:
                if len(stks) > best_cnt:
                    best_p, best_cnt = p, len(stks)
                if p in top2: in2 = True
                if p in top3: in3 = True
        if not best_p and dt in tape_dict and c6 in tape_dict[dt]:
            tp = tape_dict[dt][c6][0]
            if tp and tp not in ("其他", "公告", "无"):
                best_p, best_cnt = tp, 2
        return best_p, best_cnt, in2, in3

    trades = []
    w_bt = df[(df["bar_idx"] >= 25) & (df["is_zt"]) & (~df["is_yizi"]) & (df["yizi_5d"] <= 1) & (df["st_20d"] == 0)].copy()
    for _, r in w_bt.iterrows():
        yr = int(r["season_yr"])
        dt = r["dt_str"]
        if not (f"{yr}-10-15" <= dt <= f"{yr+1}-01-15"):
            continue
        c6 = r["c6"]
        d1_dt, d1_o, d1_l = r["fdt_1"], r["fo_1"], r["fl_1"]
        if pd.isna(d1_dt) or pd.isna(d1_o) or d1_o <= 0 or bool(r["fyz_1"]):
            continue
        lo_ma = (pd.Timestamp(dt) - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
        lo_ps = (pd.Timestamp(dt) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
        if has_date_in_range(ma_dates.get(c6, []), lo_ma, dt) or has_date_in_range(poison_dates.get(c6, []), lo_ps, dt):
            continue
        tp_n, tp_r = tape_dict.get(dt, {}).get(c6, ("", ""))
        if MA_PAT.search(f"{tp_n} {tp_r}") or any(b in tp_n for b in BAD_KPL):
            continue
        bp, pcnt, in2, in3 = plate_info(dt, c6)
        if any(b in bp for b in BAD_KPL):
            continue
        ogap = d1_o / r["close"] - 1.0
        if ogap < -0.035 or ogap > 0.068:
            continue
        is_m1 = (r["zt_streak"] in (3, 4) or (r["zt_streak"] == 2 and r["zt_5d"] >= 3)) and (in2 or pcnt >= 4)
        is_m2 = (r["zt_streak"] == 1) and (r["past15_zt"] >= 2) and (r["past10_min_ma20"] >= -0.03) and (in3 or pcnt >= 3)
        if not (is_m1 or is_m2):
            continue

        def sim_exit(mode):
            for k in range(1, 31):
                ck, ok1, dtk1 = r[f"fc_{k}"], r[f"fo_{k+1}"], r[f"fdt_{k+1}"]
                if pd.isna(ck) or pd.isna(ok1) or ok1 <= 0:
                    return r[f"fdt_{k}"], ck, k
                if mode == "break" and not bool(r[f"fzt_{k}"]):
                    return dtk1, ok1, k
                if mode == "ma10" and not pd.isna(r[f"fma10_{k}"]) and ck < r[f"fma10_{k}"]:
                    return dtk1, ok1, k
                if mode == "ma10_buf2":
                    m10, m20 = r[f"fma10_{k}"], r[f"fma20_{k}"]
                    if (not pd.isna(m10) and ck < m10 * 0.98) or (not pd.isna(m20) and ck < m20):
                        return dtk1, ok1, k
            return r["fdt_30"], r["fc_30"], 30

        ea_dt, ea_px, ha = sim_exit("break")
        eb_dt, eb_px, hb = sim_exit("ma10")
        ec_dt, ec_px, hc = sim_exit("ma10_buf2")
        if pd.isna(eb_px) or eb_px <= 0:
            continue
        ra = (ea_px / d1_o - 1.0) - FEE
        rb = (eb_px / d1_o - 1.0) - FEE
        rc = (ec_px / d1_o - 1.0) - FEE
        hs_sub = hs300[(hs300.index >= pd.Timestamp(d1_dt)) & (hs300.index <= pd.Timestamp(eb_dt))]
        hs_b = (hs_sub.iloc[-1] / hs_sub.iloc[0] - 1.0) if len(hs_sub) >= 2 else 0.0
        hs_subc = hs300[(hs300.index >= pd.Timestamp(d1_dt)) & (hs300.index <= pd.Timestamp(ec_dt))]
        hs_c = (hs_subc.iloc[-1] / hs_subc.iloc[0] - 1.0) if len(hs_subc) >= 2 else 0.0
        trades.append({
            "season": f"{yr}/{str(yr+1)[2:]}", "sig_dt": dt, "buy_dt": d1_dt, "c6": c6,
            "name": name_map.get(c6, c6), "theme": bp, "pcnt": pcnt, "in2": in2,
            "is_m1": bool(is_m1), "is_m2": bool(is_m2), "streak": int(r["zt_streak"]),
            "close_t0": round(float(r["close"]), 2), "mcap": round(float(r["mcap"]), 1),
            "amt_yi": round(float(r["amt_yi"]), 2), "past15_amt": round(float(r["past15_max_amt"] or 0), 2),
            "buy_px": round(float(d1_o), 2),
            "ea_dt": ea_dt, "ra": ra, "ha": ha,
            "eb_dt": eb_dt, "rb": rb, "hb": hb, "hs_b": hs_b, "ex_b": rb - hs_b,
            "ec_dt": ec_dt, "rc": rc, "hc": hc, "hs_c": hs_c, "ex_c": rc - hs_c,
        })

    tdf = pd.DataFrame(trades)
    tdf.to_csv(f"{OUT_DIR}/v3_ledger_cross_year_big.csv", index=False, encoding="utf-8-sig")
    with open(f"{OUT_DIR}/v3_real_top5.json", "w", encoding="utf-8") as f:
        json.dump({"all_cap": real_top5_all, "big_cap_50": real_top5_big}, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(tdf)} raw candidate trades. 2025/26 AllCap Top5:")
    for x in real_top5_all["2025/26"]:
        print(" ", x)
    print("2025/26 BigCap(>=50亿) Top5:")
    for x in real_top5_big["2025/26"]:
        print(" ", x)

if __name__ == "__main__":
    main()
