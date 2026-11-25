#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 2: Engineer 48 Strictly PIT Factors for every extracted 30d-200% near-miss event.
All pre-close D30 features strictly use data <= D30 14:55 (KPL <= D29 for strict pre-close,
plus D30 intraday-known theme resonance; LHB <= D29 for D30 close, plus D30 LHB tagged D31-only).
"""

import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from step1_extract_events_and_returns import (
    A_DAILY,
    A_DELISTED,
    CNINFO_DB,
    KPL_JSONL,
    OUT_DIR,
    SIM,
    build_pit_st_history,
    is_pit_st,
    load_indices,
)

LHB_BUY = SIM / "backtest/2026-10-20-lhasa/lhb_buy.parquet"
LHB_SELL = SIM / "backtest/2026-10-20-lhasa/lhb_sell.parquet"
YOUZI_ATLAS = SIM / "backtests_astock2/rd016_famous_youzi_seats_20261117/youzi_seat_atlas_5y.json"
TOP10_CACHE = SIM / "backtests_astock/sandbox_lab/pit_top10_freeholders_cache.json"
REG_TOX_PQ = SIM / "data/pit_reg_tox_notices_5y_complete.parquet"

NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股",
}


def load_lhb_clean():
    t0 = time.time()
    cols = ["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_CODE", "OPERATEDEPT_NAME", "BUY", "SELL", "NET", "EXPLANATION", "TRADE_ID"]
    lb = pd.read_parquet(LHB_BUY, columns=cols)
    ls = pd.read_parquet(LHB_SELL, columns=cols)
    lb["side"] = "B"
    ls["side"] = "S"
    raw = pd.concat([lb, ls], ignore_index=True)
    raw["date"] = raw["TRADE_DATE"].astype(str).str[:10]
    raw["c6"] = raw["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    raw["is_three"] = raw["EXPLANATION"].astype(str).str.contains("三个交易日|3个交易日").astype(int)
    raw["dept_code"] = raw["OPERATEDEPT_CODE"].astype(str)
    raw["dept_name"] = raw["OPERATEDEPT_NAME"].astype(str)

    canon_tid = raw.groupby(["date", "c6", "is_three"], as_index=False)["TRADE_ID"].min()
    raw = raw.merge(canon_tid, on=["date", "c6", "is_three", "TRADE_ID"], how="inner")
    non_org = raw[raw["dept_code"] != "0"].drop_duplicates(["date", "c6", "is_three", "dept_code"])
    org = raw[raw["dept_code"] == "0"].drop_duplicates(["date", "c6", "is_three", "side", "BUY", "SELL"])
    clean = pd.concat([non_org, org], ignore_index=True)

    # Identify seat classes
    with open(YOUZI_ATLAS, encoding="utf-8") as f:
        atlas = json.load(f)
    famous_depts = set()
    for k, v in atlas.get("famous_seat_migration_2021_2026", {}).items():
        if any(x in k for x in ["拉萨", "山南", "外资", "高盛", "摩根", "瑞银", "中金", "华鑫", "国信浙江"]):
            continue
        famous_depts.update(str(dc) for dc in v.get("by_dept_code", {}).keys())

    clean["is_inst"] = clean["dept_name"].str.contains("机构专用", na=False)
    clean["is_lasa"] = clean["dept_name"].str.contains("拉萨|山南|昌都", na=False)
    clean["is_famous_yz"] = clean["dept_code"].isin(famous_depts)

    # Aggregate per (c6, date) (prefer 1-day rows if present, else 3-day rows to avoid double-counting)
    agg = []
    for (c6, dt), grp in clean.groupby(["c6", "date"]):
        if (grp["is_three"] == 0).any():
            g = grp[grp["is_three"] == 0]
        else:
            g = grp
        tot_b = float(g["BUY"].fillna(0).sum())
        tot_s = float(g["SELL"].fillna(0).sum())
        tot_bs = tot_b + tot_s
        inst_net = float(g.loc[g["is_inst"], "NET"].fillna(0).sum()) / 1e4  # 万元
        inst_buy = float(g.loc[g["is_inst"], "BUY"].fillna(0).sum()) / 1e4
        lasa_bs = float((g.loc[g["is_lasa"], "BUY"].fillna(0) + g.loc[g["is_lasa"], "SELL"].fillna(0)).sum())
        lasa_net = float(g.loc[g["is_lasa"], "NET"].fillna(0).sum()) / 1e4
        yz_net = float(g.loc[g["is_famous_yz"], "NET"].fillna(0).sum()) / 1e4
        yz_buy = float(g.loc[g["is_famous_yz"], "BUY"].fillna(0).sum()) / 1e4
        agg.append({
            "c6": c6, "date": dt,
            "inst_net": inst_net, "inst_buy": inst_buy,
            "lasa_bs": lasa_bs, "tot_bs": tot_bs, "lasa_net": lasa_net,
            "yz_net": yz_net, "yz_buy": yz_buy,
        })
    lhb_day = pd.DataFrame(agg)
    lhb_map = defaultdict(dict)
    for r in lhb_day.itertuples(index=False):
        lhb_map[r.c6][r.date] = r
    print(f"[LHB] Aggregated {len(lhb_day)} stock-days in {time.time()-t0:.1f}s")
    return lhb_map


def load_kpl_pit():
    """Load KPL plates daily mapping: (date -> plate -> set of c6), (c6, date -> list of real plates)."""
    t0 = time.time()
    plate_day_stocks = defaultdict(lambda: defaultdict(set))
    stock_day_plates = defaultdict(lambda: defaultdict(list))
    kpl_dates = []
    with open(KPL_JSONL, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            obj = json.loads(ln)
            dt = obj.get("date", "")
            if dt < "2020-09-01" or dt > "2026-11-24":
                continue
            kpl_dates.append(dt)
            for pl in obj.get("plates", []):
                pname = str(pl.get("plate", "")).strip()
                if not pname or pname in NON_THEME:
                    continue
                for st in pl.get("stocks", []):
                    if isinstance(st, dict):
                        c6 = str(st.get("code", ""))[:6].zfill(6)
                    elif isinstance(st, list) and len(st) >= 1:
                        c6 = str(st[0])[:6].zfill(6)
                    else:
                        continue
                    plate_day_stocks[dt][pname].add(c6)
                    stock_day_plates[c6][dt].append(pname)
    kpl_dates = sorted(set(kpl_dates))
    print(f"[KPL] Loaded {len(kpl_dates)} days in {time.time()-t0:.1f}s")
    return plate_day_stocks, stock_day_plates, kpl_dates


def load_reg_notices(target_codes: set, all_mkt_dts: list):
    """Load CNINFO regulatory / abnormal fluctuation / suspension notices strictly PIT by pub_datetime_cst."""
    import bisect
    t0 = time.time()
    conn = sqlite3.connect(f"file:{CNINFO_DB}?mode=ro", uri=True)
    placeholders = ",".join("?" for _ in target_codes)
    q = f"""
    SELECT sec_code, pub_datetime_cst, trade_date_avail, title
    FROM notices
    WHERE sec_code IN ({placeholders})
      AND (title LIKE '%问询函%' OR title LIKE '%关注函%' OR title LIKE '%监管函%'
           OR title LIKE '%警示函%' OR title LIKE '%立案%' OR title LIKE '%稽查%'
           OR title LIKE '%异常波动%' OR title LIKE '%停牌核查%' OR title LIKE '%风险提示%')
    """
    reg_map = defaultdict(list)
    inq_pat = re.compile(r"(问询函|关注函|监管函|警示函|立案|稽查)")
    abn_pat = re.compile(r"(异常波动|停牌核查|严重异常波动|交易风险提示)")
    for c6, pub_dt, avail_dt, title in conn.execute(q, list(target_codes)):
        c6 = str(c6)[:6].zfill(6)
        t = str(title or "")
        p_date = str(pub_dt)[:10]
        p_time = str(pub_dt)[11:19] if len(str(pub_dt)) >= 19 else "23:59:59"
        eff_dt = p_date if p_time <= "14:50:00" else str(avail_dt)
        is_inq = bool(inq_pat.search(t)) and ("回复" not in t)
        is_abn = bool(abn_pat.search(t))
        if is_inq or is_abn:
            reg_map[c6].append((eff_dt, is_inq, is_abn))
    conn.close()

    # Merge pit_reg_tox_notices_5y_complete.parquet strictly PIT (if time=='00:00:00' or >14:50, push to next market day)
    reg_pq = pd.read_parquet(REG_TOX_PQ)
    reg_pq["c6"] = reg_pq["sec_code"].astype(str).str[:6].str.zfill(6)
    reg_pq = reg_pq[reg_pq["c6"].isin(target_codes)]
    for r in reg_pq.itertuples(index=False):
        p_dt = str(r.pub_datetime_cst)
        p_d = p_dt[:10]
        p_t = p_dt[11:19] if len(p_dt) >= 19 else "23:59:59"
        if p_t != "00:00:00" and p_t <= "14:50:00":
            eff_dt = p_d
        else:
            idx_n = bisect.bisect_right(all_mkt_dts, p_d)
            eff_dt = all_mkt_dts[idx_n] if idx_n < len(all_mkt_dts) else "2099-12-31"
        reg_map[r.c6].append((eff_dt, True, False))

    print(f"[Notices] Loaded reg/abn events for {len(reg_map)} codes in {time.time()-t0:.1f}s")
    return reg_map


def main():
    t_start = time.time()
    eh = pd.read_parquet(OUT_DIR / "events_hold_base.parquet")
    target_codes = set(eh["c6"].unique())

    # 1. Build full daily market matrix (to get zt/dt counts, total amount, streaks, stock OHLCV history)
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp("2020-09-01")
    d1 = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    d2 = ds.dataset(A_DELISTED, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    df = pd.concat([d1, d2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].astype(str).str.endswith((".SH", ".SZ")) & df["c6"].str.startswith(("00", "60", "300", "301", "688", "689"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    g = df.groupby("c6")
    df["pre_adj"] = g["adj_close"].shift(1)
    df["pct"] = df["adj_close"] / df["pre_adj"] - 1.0
    is_20_s = df["c6"].str.startswith(("300", "301", "688", "689"))
    lim_thr_s = np.where(is_20_s, 0.194, 0.094)
    lim_ex_s = np.where(is_20_s, 0.20, 0.10)
    pre_raw = g["close"].shift(1)
    zt_px_s = np.floor(pre_raw * (1.0 + lim_ex_s) * 100.0 + 0.5) / 100.0
    dt_px_s = np.floor(pre_raw * (1.0 - lim_ex_s) * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["pct"] >= lim_thr_s) & (df["close"] >= zt_px_s - 0.015) & (df["pre_adj"] > 0)
    df["is_dt"] = (df["pct"] <= -lim_thr_s) & (df["close"] <= dt_px_s + 0.015) & (df["pre_adj"] > 0)
    df["touch_zt"] = ((df["high"] >= zt_px_s - 0.015) | ((df["high"] / pre_raw - 1.0) >= lim_thr_s)) & (df["pre_adj"] > 0)

    s_zt = df["is_zt"].astype(int)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != g["is_zt"].shift().fillna(False)).cumsum()]).cumsum() * s_zt
    df["ret20"] = df["adj_close"] / g["adj_close"].shift(20) - 1.0

    # Market-wide daily stats
    all_mkt_dts = sorted(df["dt_str"].unique())
    mkt_pos = {d: i for i, d in enumerate(all_mkt_dts)}
    dg = df.groupby("dt_str")
    mkt_stats = pd.DataFrame({
        "mkt_zt_cnt": dg["is_zt"].sum(),
        "mkt_dt_cnt": dg["is_dt"].sum(),
        "mkt_amt_tril": dg["amount"].sum() / 1e12,
        "mkt_max_streak": dg["streak"].max(),
    }).reindex(all_mkt_dts).fillna(0).to_dict("index")

    # Quick lookup for (c6, dt) -> (streak, pct) and ret20 for theme assists & leader check
    zt_lookup = {}
    zt_rows = df[df["is_zt"]][["c6", "dt_str", "streak", "pct"]]
    for r in zt_rows.itertuples(index=False):
        zt_lookup[(r.c6, r.dt_str)] = (int(r.streak), float(r.pct))

    plate_day_stocks, stock_day_plates, kpl_dts = load_kpl_pit()
    kpl_codes = set(stock_day_plates.keys()) | target_codes
    ret20_lookup = {}
    r20_sub = df[df["c6"].isin(kpl_codes) & df["ret20"].notna()][["c6", "dt_str", "ret20"]]
    for r in r20_sub.itertuples(index=False):
        ret20_lookup[(r.c6, r.dt_str)] = float(r.ret20)

    # Sub-dataframe ONLY for target_codes for detailed OHLCV features
    sub_df = df[df["c6"].isin(target_codes)].copy()
    stock_panels = {c6: grp.reset_index(drop=True) for c6, grp in sub_df.groupby("c6", sort=False)}
    del df, sub_df, r20_sub

    # HS300 returns
    idx_map = load_indices()
    hs_s = idx_map["sh000300"].reindex(pd.to_datetime(all_mkt_dts)).ffill()
    hs_vals = hs_s.values
    hs_ret5 = {d: float((hs_vals[i] / hs_vals[i - 5] - 1.0) * 100.0) if i >= 5 else np.nan for i, d in enumerate(all_mkt_dts)}
    hs_ret20 = {d: float((hs_vals[i] / hs_vals[i - 20] - 1.0) * 100.0) if i >= 20 else np.nan for i, d in enumerate(all_mkt_dts)}

    lhb_map = load_lhb_clean()
    reg_map = load_reg_notices(target_codes, all_mkt_dts)
    with open(TOP10_CACHE, encoding="utf-8") as f:
        top10_cache = json.load(f)

    # Pre-index top10 by c6 -> sorted list of (notice_date, total_free_ratio)
    top10_series = {}
    for c6 in target_codes:
        rows = top10_cache.get(c6)
        if not rows:
            continue
        by_notice = defaultdict(float)
        for item in rows:
            nd = str(item.get("NOTICE_DATE", ""))[:10]
            if nd:
                by_notice[nd] += float(item.get("FREE_HOLDNUM_RATIO", 0) or 0)
        if by_notice:
            top10_series[c6] = sorted(by_notice.items())

    # Compute 48 PIT factors for each event row
    feat_rows = []
    for r in eh.itertuples(index=False):
        c6 = r.c6
        sp = stock_panels[c6]
        i = int(r.d30_idx)
        t0 = int(r.t0_idx)
        d30_dt = r.d30_date
        d30_mpos = mkt_pos[d30_dt]
        d29_dt = all_mkt_dts[d30_mpos - 1] if d30_mpos >= 1 else d30_dt

        # 1. Price/Volume Control Features (strictly <= D30)
        adj_c = sp["adj_close"].values
        adj_o = sp["open"].values * (adj_c / sp["close"].values)
        adj_hi = sp["high"].values * (adj_c / sp["close"].values)
        adj_lo = sp["low"].values * (adj_c / sp["close"].values)
        pre_adj = sp["pre_adj"].values
        pct = sp["pct"].values * 100.0
        vol = sp["volume"].values
        amt = sp["amount"].values
        turn = sp["turn"].values * 100.0  # %
        is_zt_a = sp["is_zt"].values
        touch_zt_a = sp["touch_zt"].values
        streak_a = sp["streak"].values
        dts_a = sp["dt_str"].values

        d30_is_yang = bool(adj_c[i] > adj_o[i])
        d30_is_fake_yin = bool((adj_c[i] < adj_o[i]) and (pct[i] > 0))
        d30_is_true_yin = bool((adj_c[i] < adj_o[i]) and (pct[i] < 0))
        d30_upper_shadow = float((adj_hi[i] - max(adj_o[i], adj_c[i])) / pre_adj[i] * 100.0) if pre_adj[i] > 0 else 0.0
        d30_lower_shadow = float((min(adj_o[i], adj_c[i]) - adj_lo[i]) / pre_adj[i] * 100.0) if pre_adj[i] > 0 else 0.0

        amp5_avg = float(np.mean((adj_hi[i - 4:i + 1] - adj_lo[i - 4:i + 1]) / pre_adj[i - 4:i + 1] * 100.0))
        box5_range = float((np.max(adj_c[i - 4:i + 1]) / np.min(adj_c[i - 4:i + 1]) - 1.0) * 100.0)
        vol5 = float(np.mean(vol[i - 4:i + 1]))
        vol20 = float(np.mean(vol[i - 19:i + 1]))
        vol_pre5 = float(np.mean(vol[i - 5:i]))
        vol_shrink_5_20 = vol5 / vol20 if vol20 > 0 else np.nan
        vol_d30_to_5 = float(vol[i] / vol_pre5) if vol_pre5 > 0 else np.nan
        d30_turn_pct = float(turn[i]) if not np.isnan(turn[i]) else np.nan
        turn5_avg_pct = float(np.nanmean(turn[i - 4:i + 1]))

        ma5 = float(np.mean(adj_c[i - 4:i + 1]))
        ma10 = float(np.mean(adj_c[i - 9:i + 1]))
        above_ma5 = bool(adj_c[i] >= ma5)
        above_ma10 = bool(adj_c[i] >= ma10)
        dist_ma5_pct = float((adj_c[i] / ma5 - 1.0) * 100.0)
        dist_ma10_pct = float((adj_c[i] / ma10 - 1.0) * 100.0)

        max_streak_30d = int(np.max(streak_a[t0 + 1:i + 1]))
        zt_days_30d = int(np.sum(is_zt_a[t0 + 1:i + 1]))
        zt_idxs = np.where(is_zt_a[t0 + 1:i + 1])[0]
        days_since_last_zt = int((i - (t0 + 1 + zt_idxs[-1]))) if len(zt_idxs) > 0 else 99
        d30_touch_zt_unsealed = bool(touch_zt_a[i] and (not r.d30_close_zt))
        d30_ret_5d = float((adj_c[i] / adj_c[i - 5] - 1.0) * 100.0)
        had_susp_30d = int((mkt_pos[d30_dt] - mkt_pos[str(dts_a[t0])]) > 30)

        # Cap, Price, Amount
        raw_c_30 = float(sp["close"].iloc[i])
        osh = float(sp["oshare"].iloc[i])
        mcap_yi = float(raw_c_30 * osh / 1e8) if osh > 0 else np.nan
        d30_amount_yi = float(amt[i] / 1e8)
        amount5_avg_yi = float(np.mean(amt[i - 4:i + 1]) / 1e8)

        # 2. KPL Theme & Echelon (strictly <= D29 vs D30 resonance)
        # Market dates window for D29, 3d(D27..D29), 5d(D25..D29), 10d(D20..D29), 30d(t0+1..D29)
        w1_d29 = {all_mkt_dts[k] for k in range(max(0, d30_mpos - 1), d30_mpos)}
        w3_d29 = {all_mkt_dts[k] for k in range(max(0, d30_mpos - 3), d30_mpos)}
        w5_d29 = {all_mkt_dts[k] for k in range(max(0, d30_mpos - 5), d30_mpos)}
        w10_d29 = {all_mkt_dts[k] for k in range(max(0, d30_mpos - 10), d30_mpos)}
        w30_d29 = {all_mkt_dts[k] for k in range(max(0, mkt_pos[str(dts_a[t0])] + 1), d30_mpos)}
        w_pre5_d29 = {all_mkt_dts[k] for k in range(max(0, d30_mpos - 8), max(0, d30_mpos - 3))}

        c_plates = stock_day_plates.get(c6, {})
        kpl_in_1d_d29 = any(dt in w1_d29 for dt in c_plates)
        kpl_in_3d_d29 = any(dt in w3_d29 for dt in c_plates)
        kpl_in_5d_d29 = any(dt in w5_d29 for dt in c_plates)
        kpl_in_10d_d29 = any(dt in w10_d29 for dt in c_plates)
        kpl_days_30d_d29 = sum(1 for dt in c_plates if dt in w30_d29)
        kpl_in_30d_d29 = kpl_days_30d_d29 > 0

        # Identify stock's theme(s) from [t0-20 .. D29]
        theme_freq = Counter()
        w_theme_search = {all_mkt_dts[k] for k in range(max(0, mkt_pos[str(dts_a[t0])] - 20), d30_mpos)}
        for dt, plist in c_plates.items():
            if dt in w_theme_search:
                for pn in plist:
                    theme_freq[pn] += 1
        has_real_theme_d29 = len(theme_freq) > 0
        matched_themes = set(theme_freq.keys())
        primary_theme = theme_freq.most_common(1)[0][0] if theme_freq else ""

        theme_zt_d29 = 0
        theme_zt_5d_d29 = 0
        theme_trend_up_d29 = False
        theme_low_assist_d29 = False
        is_theme_leader_d29 = False
        theme_zt_d30_live = 0
        theme_low_assist_d30 = False

        if matched_themes:
            theme_zt_d29 = max((len(plate_day_stocks[d29_dt].get(th, set())) for th in matched_themes), default=0)
            # 5d cumulative on primary theme (or max across matched themes)
            theme_zt_5d_d29 = max(
                sum(len(plate_day_stocks[dt].get(th, set())) for dt in w5_d29)
                for th in matched_themes
            )
            r3 = max(sum(len(plate_day_stocks[dt].get(th, set())) for dt in w3_d29) / 3.0 for th in matched_themes)
            p5 = max(sum(len(plate_day_stocks[dt].get(th, set())) for dt in w_pre5_d29) / 5.0 for th in matched_themes)
            theme_trend_up_d29 = bool(r3 > p5 and r3 >= 1.0)

            # Low-tier assist (1st/2nd board) on D29 in matched themes
            peers_d29 = set()
            for th in matched_themes:
                peers_d29.update(plate_day_stocks[d29_dt].get(th, set()))
            peers_d29.discard(c6)
            for pc in peers_d29:
                info = zt_lookup.get((pc, d29_dt))
                if info and info[0] in (1, 2):
                    theme_low_assist_d29 = True
                    break

            # Is this stock the highest 20d return leader on D29 among peers appearing in primary_theme over [t0..D29]?
            peers_wave = set()
            for dt in w30_d29:
                peers_wave.update(plate_day_stocks[dt].get(primary_theme, set()))
            if len(peers_wave) <= 1:
                is_theme_leader_d29 = True
            else:
                my_r20 = ret20_lookup.get((c6, d29_dt), 0.0)
                higher_peer = False
                for pc in peers_wave:
                    if pc == c6:
                        continue
                    if ret20_lookup.get((pc, d29_dt), -9.0) > my_r20:
                        higher_peer = True
                        break
                is_theme_leader_d29 = not higher_peer

            # D30 live theme resonance: peers known in matched_themes during [D15..D29] hitting ZT on D30!
            w15_d29 = {all_mkt_dts[k] for k in range(max(0, d30_mpos - 15), d30_mpos)}
            known_peers = set()
            for dt in w15_d29:
                for th in matched_themes:
                    known_peers.update(plate_day_stocks[dt].get(th, set()))
            known_peers.discard(c6)
            for pc in known_peers:
                info = zt_lookup.get((pc, d30_dt))
                if info is not None:
                    theme_zt_d30_live += 1
                    if info[0] in (1, 2):
                        theme_low_assist_d30 = True

        # Also D30 KPL (strictly for D31 open / post-close check)
        kpl_d30_themes = stock_day_plates.get(c6, {}).get(d30_dt, [])
        kpl_in_d30 = len(kpl_d30_themes) > 0
        kpl_theme_zt_d30 = max((len(plate_day_stocks[d30_dt].get(th, set())) for th in (set(kpl_d30_themes) | matched_themes)), default=0)

        # 3. Top-10 freeholder lockup (NOTICE_DATE <= D29)
        top10_free_lock_pct = np.nan
        if c6 in top10_series:
            valid_t10 = [val for nd, val in top10_series[c6] if nd <= d29_dt]
            if valid_t10:
                top10_free_lock_pct = float(valid_t10[-1])

        # 4. Regulatory / Abnormal notices (eff_dt <= D30)
        d10_lo = all_mkt_dts[max(0, d30_mpos - 10)]
        t0_dt = r.t0_date
        reg_inquiry_10d = 0
        reg_inquiry_30d = 0
        reg_abn_cnt_30d = 0
        for eff_dt, is_inq, is_abn in reg_map.get(c6, []):
            if eff_dt <= d30_dt:
                if is_inq and eff_dt >= d10_lo:
                    reg_inquiry_10d = 1
                if is_inq and eff_dt >= t0_dt:
                    reg_inquiry_30d = 1
                if is_abn and eff_dt >= t0_dt:
                    reg_abn_cnt_30d += 1

        # 5. LHB strictly <= D29 (5d window [D25..D29]) + D30 (D31-only)
        s_lhb = lhb_map.get(c6, {})
        lhb_cnt_5d_d29 = 0
        inst_net_5d = 0.0
        inst_buy_5d = 0.0
        lasa_bs_5d = 0.0
        tot_bs_5d = 0.0
        yz_net_5d = 0.0
        for dt in w5_d29:
            rec_l = s_lhb.get(dt)
            if rec_l is not None:
                lhb_cnt_5d_d29 += 1
                inst_net_5d += rec_l.inst_net
                inst_buy_5d += rec_l.inst_buy
                lasa_bs_5d += rec_l.lasa_bs
                tot_bs_5d += rec_l.tot_bs
                yz_net_5d += rec_l.yz_net
        lhb_lasa_ratio_5d_d29 = float(lasa_bs_5d / tot_bs_5d) if tot_bs_5d > 0 else np.nan

        rec_l30 = s_lhb.get(d30_dt)
        lhb_on_d30 = int(rec_l30 is not None)
        lhb_d30_inst_net = float(rec_l30.inst_net) if rec_l30 is not None else np.nan
        lhb_d30_lasa_ratio = float(rec_l30.lasa_bs / rec_l30.tot_bs) if (rec_l30 is not None and rec_l30.tot_bs > 0) else np.nan

        # 6. Market Environment (D29 & D30)
        ms30 = mkt_stats[d30_dt]
        ms29 = mkt_stats[d29_dt]

        feat_rows.append({
            "d30_is_yang": d30_is_yang,
            "d30_is_fake_yin": d30_is_fake_yin,
            "d30_is_true_yin": d30_is_true_yin,
            "d30_upper_shadow": round(d30_upper_shadow, 2),
            "d30_lower_shadow": round(d30_lower_shadow, 2),
            "amp5_avg": round(amp5_avg, 2),
            "box5_range": round(box5_range, 2),
            "vol_shrink_5_20": round(vol_shrink_5_20, 3) if pd.notna(vol_shrink_5_20) else np.nan,
            "vol_d30_to_5": round(vol_d30_to_5, 3) if pd.notna(vol_d30_to_5) else np.nan,
            "d30_turn_pct": round(d30_turn_pct, 2) if pd.notna(d30_turn_pct) else np.nan,
            "turn5_avg_pct": round(turn5_avg_pct, 2) if pd.notna(turn5_avg_pct) else np.nan,
            "above_ma5": above_ma5,
            "above_ma10": above_ma10,
            "dist_ma5_pct": round(dist_ma5_pct, 2),
            "dist_ma10_pct": round(dist_ma10_pct, 2),
            "max_streak_30d": max_streak_30d,
            "zt_days_30d": zt_days_30d,
            "days_since_last_zt": days_since_last_zt,
            "d30_touch_zt_unsealed": d30_touch_zt_unsealed,
            "d30_ret_5d": round(d30_ret_5d, 2),
            "had_susp_30d": had_susp_30d,
            "mcap_yi": round(mcap_yi, 2) if pd.notna(mcap_yi) else np.nan,
            "d30_close_raw": round(raw_c_30, 2),
            "d30_amount_yi": round(d30_amount_yi, 2),
            "amount5_avg_yi": round(amount5_avg_yi, 2),
            "kpl_in_1d_d29": kpl_in_1d_d29,
            "kpl_in_3d_d29": kpl_in_3d_d29,
            "kpl_in_5d_d29": kpl_in_5d_d29,
            "kpl_in_10d_d29": kpl_in_10d_d29,
            "kpl_in_30d_d29": kpl_in_30d_d29,
            "kpl_days_30d_d29": kpl_days_30d_d29,
            "has_real_theme_d29": has_real_theme_d29,
            "primary_theme": primary_theme,
            "theme_zt_d29": theme_zt_d29,
            "theme_zt_5d_d29": theme_zt_5d_d29,
            "theme_trend_up_d29": theme_trend_up_d29,
            "theme_low_assist_d29": theme_low_assist_d29,
            "is_theme_leader_d29": is_theme_leader_d29,
            "theme_zt_d30_live": theme_zt_d30_live,
            "theme_low_assist_d30": theme_low_assist_d30,
            "kpl_in_d30": kpl_in_d30,
            "kpl_theme_zt_d30": kpl_theme_zt_d30,
            "top10_free_lock_pct": round(top10_free_lock_pct, 2) if pd.notna(top10_free_lock_pct) else np.nan,
            "reg_inquiry_10d": reg_inquiry_10d,
            "reg_inquiry_30d": reg_inquiry_30d,
            "reg_abn_cnt_30d": reg_abn_cnt_30d,
            "lhb_cnt_5d_d29": lhb_cnt_5d_d29,
            "lhb_inst_net_5d_d29": round(inst_net_5d, 1),
            "lhb_inst_buy_5d_d29": round(inst_buy_5d, 1),
            "lhb_lasa_ratio_5d_d29": round(lhb_lasa_ratio_5d_d29, 3) if pd.notna(lhb_lasa_ratio_5d_d29) else np.nan,
            "lhb_famous_yz_net_5d_d29": round(yz_net_5d, 1),
            "lhb_on_d30": lhb_on_d30,
            "lhb_d30_inst_net": round(lhb_d30_inst_net, 1) if pd.notna(lhb_d30_inst_net) else np.nan,
            "lhb_d30_lasa_ratio": round(lhb_d30_lasa_ratio, 3) if pd.notna(lhb_d30_lasa_ratio) else np.nan,
            "mkt_zt_cnt_d30": int(ms30["mkt_zt_cnt"]),
            "mkt_dt_cnt_d30": int(ms30["mkt_dt_cnt"]),
            "mkt_amt_tril_d30": round(float(ms30["mkt_amt_tril"]), 3),
            "mkt_max_streak_d30": int(ms30["mkt_max_streak"]),
            "mkt_zt_cnt_d29": int(ms29["mkt_zt_cnt"]),
            "mkt_dt_cnt_d29": int(ms29["mkt_dt_cnt"]),
            "mkt_amt_tril_d29": round(float(ms29["mkt_amt_tril"]), 3),
            "hs300_ret5_d30": round(hs_ret5[d30_dt], 2) if pd.notna(hs_ret5[d30_dt]) else np.nan,
            "hs300_ret20_d30": round(hs_ret20[d30_dt], 2) if pd.notna(hs_ret20[d30_dt]) else np.nan,
            "d30_weekday": pd.Timestamp(d30_dt).weekday(),
        })

    feat_df = pd.DataFrame(feat_rows)
    full_df = pd.concat([eh.reset_index(drop=True), feat_df], axis=1)
    full_df.to_parquet(OUT_DIR / "events_hold_48factors.parquet", index=False)
    print(f"[Factors] Saved events_hold_48factors.parquet shape={full_df.shape} in {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
