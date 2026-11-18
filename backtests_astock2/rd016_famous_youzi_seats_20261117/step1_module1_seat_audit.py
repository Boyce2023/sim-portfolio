#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD016 Module 1: 5Y PIT Youzi Seat Atlas, Purity, Migration & Action-State Audit."""

import json
import os
import re
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
SANDBOX = f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117"
A_DAILY = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
LHB_BUY = f"{SIM}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
LHB_SELL = f"{SIM}/backtest/2026-10-20-lhasa/lhb_sell.parquet"
THS_PQ = f"{SANDBOX}/ths_pit_youzi_5y.parquet"

FEE_30BPS = 0.0030


def build_market_zt_panel() -> pd.DataFrame:
    """Load active + delisted A-shares (00/30/60/68) and compute ZT, streak, T+1 & T+2 tradable metrics."""
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn", "oshare"]
    flt = (ds.field("date") >= pd.Timestamp("2020-11-01")) & (ds.field("date") <= pd.Timestamp("2026-11-17"))
    d1 = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    d2 = ds.dataset(A_DELISTED, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    df = pd.concat([d1, d2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].astype(str).str.endswith((".SH", ".SZ")) & df["c6"].str.startswith(("00", "30", "60", "68"))].copy()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "date"], inplace=True)
    df.drop_duplicates(["c6", "date"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    g = df.groupby("c6", sort=False)
    df["adjf"] = np.where(df["close"] > 0, df["adj_close"] / df["close"], 1.0)
    df["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["o_pct"] = df["open"] / df["pre_c"] - 1.0

    is_20 = df["c6"].str.startswith(("30", "68"))
    lim_mult = np.where(is_20, 1.20, 1.10)
    dt_mult = np.where(is_20, 0.80, 0.90)
    df["zt_px"] = np.floor(df["pre_c"] * lim_mult * 100.0 + 0.5) / 100.0
    df["dt_px"] = np.floor(df["pre_c"] * dt_mult * 100.0 + 0.5) / 100.0
    df["is_zt"] = np.where(
        is_20,
        (df["close"] >= df["zt_px"] - 0.011) & (df["pct"] >= 0.195),
        (df["close"] >= df["zt_px"] - 0.011) & (df["pct"] >= 0.095),
    ) & (df["pre_c"] > 0)
    df["is_dt"] = np.where(
        is_20,
        (df["close"] <= df["dt_px"] + 0.011) & (df["pct"] <= -0.195),
        (df["close"] <= df["dt_px"] + 0.011) & (df["pct"] <= -0.095),
    ) & (df["pre_c"] > 0)
    df["is_yizi_zt"] = df["is_zt"] & (df["open"] >= df["zt_px"] - 0.011) & (df["low"] >= df["zt_px"] - 0.011)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_px"] + 0.011) & (df["high"] <= df["dt_px"] + 0.011)
    df["is_20cm"] = is_20

    s_zt = df["is_zt"].astype(int)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != g["is_zt"].shift().fillna(False)).cumsum()]).cumsum() * s_zt

    # Next-day T+1 metrics
    df["d1_date"] = g["date"].shift(-1)
    df["d1_open_pct"] = g["o_pct"].shift(-1)
    df["d1_close_pct"] = g["pct"].shift(-1)
    df["d1_intra_pullback"] = df["d1_close_pct"] - df["d1_open_pct"]
    df["d1_is_zt"] = g["is_zt"].shift(-1)
    df["d1_is_yizi_zt"] = g["is_yizi_zt"].shift(-1)
    df["d1_is_yizi_dt"] = g["is_yizi_dt"].shift(-1)
    df["d1_nuke"] = (df["d1_close_pct"] <= -0.05).astype(float)
    df["d1_open"] = g["open"].shift(-1)
    df["d1_zt_px"] = g["zt_px"].shift(-1)
    df["d1_adjf"] = g["adjf"].shift(-1)
    df["d1_buyable"] = (
        df["d1_open"].notna()
        & (df["d1_open"] < df["d1_zt_px"] - 0.011)
        & (~df["d1_is_yizi_dt"].fillna(False))
    )

    # Compute T+1 open buy -> T+2 close (delay if T+2 yizi_dt or close limit-down)
    c6_arr = df["c6"].to_numpy()
    open_arr = df["open"].to_numpy()
    close_arr = df["close"].to_numpy()
    adjf_arr = df["adjf"].to_numpy()
    is_dt_arr = df["is_dt"].to_numpy()
    is_yz_dt_arr = df["is_yizi_dt"].to_numpy()
    buyable_arr = df["d1_buyable"].to_numpy()
    is_zt_arr = df["is_zt"].to_numpy()
    date_arr = df["date"].to_numpy()

    n = len(df)
    t2_net = np.full(n, np.nan, dtype=float)
    # Build c6 bounds
    starts = np.flatnonzero(np.r_[True, c6_arr[1:] != c6_arr[:-1]])
    ends = np.r_[starts[1:], n]
    for st_i, en_i in zip(starts, ends):
        for i in range(st_i, en_i - 2):
            if date_arr[i] < "2021-01-04":
                continue
            if not buyable_arr[i]:
                continue
            b_px = open_arr[i + 1] * adjf_arr[i + 1]
            if not (b_px > 0):
                continue
            k = i + 2
            while k < en_i - 1 and is_yz_dt_arr[k]:
                k += 1
            if is_yz_dt_arr[k]:
                # If still yizi_dt on last available bar, use its close (delisted/end)
                s_px = close_arr[k] * adjf_arr[k]
            elif is_dt_arr[k] and k < en_i - 1:
                # Close locked at limit-down, exit next non-yizi_dt open or close
                k2 = k + 1
                while k2 < en_i - 1 and is_yz_dt_arr[k2]:
                    k2 += 1
                s_px = open_arr[k2] * adjf_arr[k2] if not is_yz_dt_arr[k2] else close_arr[k2] * adjf_arr[k2]
            else:
                s_px = close_arr[k] * adjf_arr[k]
            t2_net[i] = (s_px / b_px) * (1.0 - FEE_30BPS) - 1.0

    df["d1_t2_tradable_net"] = t2_net
    sub = df[df["date"] >= "2021-01-04"].copy()
    print(f"[MarketPanel] Built {len(sub)} daily rows in {time.time()-t0:.1f}s")
    return sub


def load_clean_lhb():
    """Load and deduplicate lhb_buy and lhb_sell by taking 1 canonical TRADE_ID per (date, code, is_three)."""
    t0 = time.time()
    cols = ["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_CODE", "OPERATEDEPT_NAME", "BUY", "SELL", "NET", "EXPLANATION", "TRADE_ID"]
    lb = pd.read_parquet(LHB_BUY, columns=cols)
    ls = pd.read_parquet(LHB_SELL, columns=cols)
    lb["side"] = "B"
    ls["side"] = "S"
    raw = pd.concat([lb, ls], ignore_index=True)
    raw["date"] = raw["TRADE_DATE"].astype(str).str[:10]
    raw["stock_code"] = raw["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    raw["is_three"] = raw["EXPLANATION"].astype(str).str.contains("三个交易日|3个交易日").astype(int)
    raw["dept_code"] = raw["OPERATEDEPT_CODE"].astype(str)
    raw["dept_name"] = raw["OPERATEDEPT_NAME"].astype(str)

    # Pick deterministic canonical TRADE_ID per (date, stock_code, is_three) to remove multi-reason duplicates
    canon_tid = raw.groupby(["date", "stock_code", "is_three"], as_index=False)["TRADE_ID"].min()
    raw = raw.merge(canon_tid, on=["date", "stock_code", "is_three", "TRADE_ID"], how="inner")

    # An institute/dept appearing in both buy-5 and sell-5 within same TRADE_ID: deduplicate non-'0' dept_code
    non_org = raw[raw["dept_code"] != "0"].drop_duplicates(["date", "stock_code", "is_three", "dept_code", "BUY", "SELL"])
    # For same dept appearing in both B and S with same BUY/SELL (rare), keep once
    non_org = non_org.drop_duplicates(["date", "stock_code", "is_three", "dept_code"])
    org = raw[raw["dept_code"] == "0"].drop_duplicates(["date", "stock_code", "is_three", "side", "BUY", "SELL"])
    clean = pd.concat([non_org, org], ignore_index=True)
    print(f"[LHB] Clean rows={len(clean)} (B={int((clean['side']=='B').sum())}, S={int((clean['side']=='S').sum())}) in {time.time()-t0:.1f}s")
    return clean


def main():
    t0 = time.time()
    mkt = build_market_zt_panel()
    lhb = load_clean_lhb()
    lhb.to_parquet(f"{SANDBOX}/clean_lhb_5y.parquet", index=False)
    ths = pd.read_parquet(THS_PQ)

    # Attach stock_name PIT from ths to zt panel and save zt_market_5y.parquet for Step 2 & 3
    name_pit = ths[["date", "stock_code", "stock_name"]].drop_duplicates(["date", "stock_code"]).rename(columns={"stock_code": "c6"})
    mkt_lhb_dates = mkt.merge(name_pit, on=["date", "c6"], how="left")
    mkt_lhb_dates["is_st_pit"] = mkt_lhb_dates["stock_name"].fillna("").str.contains("ST|退", case=False)
    zt_only = mkt_lhb_dates[mkt_lhb_dates["is_zt"] | mkt_lhb_dates["stock_name"].notna()].copy()
    zt_only.to_parquet(f"{SANDBOX}/zt_market_5y.parquet", index=False)
    print(f"Saved zt_market_5y.parquet: {len(zt_only)} rows")

    # 1. Exact matching between single-icon 10jqka events and non-org lhb dept rows
    lhb_non_org = lhb[lhb["dept_code"] != "0"].drop_duplicates(["date", "stock_code", "is_three", "dept_code"]).copy()
    s1 = ths[(ths["n_capital_icons"] == 1) & (ths["cap_count"] == 1) & ths["cap_inflow"].notna()].copy()
    s1["icon"] = s1["capital_icons_str"]
    m1 = s1.merge(lhb_non_org[["date", "stock_code", "is_three", "dept_code", "dept_name", "BUY", "SELL", "NET"]],
                  on=["date", "stock_code", "is_three"], how="inner")
    m1["abs_diff"] = (m1["NET"] - m1["cap_inflow"]).abs()
    exact = m1[m1["abs_diff"] <= 5.0].copy()

    # For each dept_code, also check all appearances in ths (even multi-icon) to audit purity
    lhb_ths = lhb_non_org.merge(ths[["date", "stock_code", "is_three", "capital_icons_str", "n_capital_icons"]],
                                on=["date", "stock_code", "is_three"], how="left")

    # Build dept_code canonical summary
    dept_stats = {}
    exact_by_dept = defaultdict(Counter)
    for r in exact.itertuples(index=False):
        exact_by_dept[r.dept_code][r.icon] += 1

    # Also track all co-occurrences on THS-labelled events for each dept_code
    co_by_dept = defaultdict(Counter)
    total_ths_matched = Counter()
    for r in lhb_ths.itertuples(index=False):
        total_ths_matched[r.dept_code] += 1
        ics = str(r.capital_icons_str or "")
        if ics:
            for ic in ics.split("|"):
                co_by_dept[r.dept_code][ic] += 1
        else:
            co_by_dept[r.dept_code]["(无标签)"] += 1

    dept_meta = lhb_non_org.groupby("dept_code").agg(
        total_appearances=("date", "size"),
        latest_name=("dept_name", lambda s: s.iloc[-1]),
        all_names=("dept_name", lambda s: list(s.value_counts().index[:5])),
        yr_counts=("date", lambda s: s.str[:4].value_counts().sort_index().to_dict()),
    )

    purity_audit = []
    for dcode, row in dept_meta.iterrows():
        n_tot = int(row["total_appearances"])
        ex_cnts = exact_by_dept.get(dcode, Counter())
        n_ex = sum(ex_cnts.values())
        co_cnts = co_by_dept.get(dcode, Counter())
        if n_ex >= 5 or n_tot >= 150:
            top1_ic, top1_n = ex_cnts.most_common(1)[0] if n_ex > 0 else ("(无官方单标)", 0)
            top2_ic, top2_n = ex_cnts.most_common(2)[1] if len(ex_cnts) >= 2 else ("", 0)
            purity_exact = round(top1_n / n_ex * 100.0, 1) if n_ex > 0 else 0.0
            # Co-occurrence rate of top1_ic when this dept appears (across all THS events)
            co_top1_rate = round(co_cnts.get(top1_ic, 0) / max(1, total_ths_matched[dcode]) * 100.0, 1) if top1_ic != "(无官方单标)" else 0.0
            grade = "高纯独享(>=90%)" if purity_exact >= 90.0 else ("中度混用(60~90%)" if purity_exact >= 60.0 else ("严重混用(<60%)" if n_ex > 0 else "官方未单标/混合通道"))
            purity_audit.append({
                "dept_code": dcode,
                "latest_name": row["latest_name"],
                "aliases": row["all_names"],
                "total_lhb_rows": n_tot,
                "exact_single_icon_matches": n_ex,
                "top1_icon": top1_ic,
                "top1_exact_n": top1_n,
                "top2_icon": top2_ic,
                "top2_exact_n": top2_n,
                "purity_exact_pct": purity_exact,
                "co_occur_top1_pct": co_top1_rate,
                "purity_grade": grade,
                "yr_counts": {str(k): int(v) for k, v in row["yr_counts"].items()},
                "top_co_icons": co_cnts.most_common(4),
            })
    purity_audit.sort(key=lambda x: (-x["total_lhb_rows"]))

    # 2. Build 67 THS icons + Named Unlabeled Famous Seats Atlas
    icon_atlas = {}
    for ic, g in exact.groupby("icon"):
        if not ic:
            continue
        dc_vc = g["dept_code"].value_counts()
        depts_info = []
        for dc, cnt in dc_vc.items():
            meta = dept_meta.loc[dc]
            depts_info.append({
                "dept_code": dc,
                "latest_name": meta["latest_name"],
                "aliases": meta["all_names"],
                "exact_matches": int(cnt),
                "total_dept_rows": int(meta["total_appearances"]),
                "yr_counts": {str(k): int(v) for k, v in meta["yr_counts"].items()},
            })
        icon_atlas[ic] = {
            "source": "10jqka_pit_exact",
            "total_ths_events": int(ths["capital_icons_str"].str.contains(re.escape(ic), na=False).sum()),
            "exact_matched_events": int(len(g)),
            "depts": depts_info[:10],
        }

    # Supplementary renowned seat groups (checking both coded & unlabelled)
    special_seats = {
        "陈小群_席位群(金马路+黄河路)": ["10657404", "10030463"],
        "六一中路/交易猿(福州六一+华泰二纬路)": ["10318896", "10147201"],
        "呼家楼/广渠门/中信北京总部": ["10045035", "10526806", "10361413"],
        "消闲派(国泰宜昌珍珠路->沿江大道)": ["10026729"],
        "毛老板_东亚苏州留园路": ["10000526027"],
        "国泰知春路(北京知春路)": ["10025390"],
        "余哥_宁波和源路": ["10000147202"],
        "作手新一_南京太平南路": ["10025054"],
        "章盟主_主席位群(延安+广福+海阳+建国)": ["10046704", "10023415", "10000526029", "10102873"],
        "上塘路(财通上塘路)": ["10063083"],
        "宁波桑田路(国盛桑田路)": ["10456710"],
        "方新侠(中信朱雀+兴业陕西)": ["10453418", "10024604"],
        "开源西安西大街": ["10046745"],
        "开源西安太华路": ["10477800"],
        "兴业厦门湖里大道": ["10119151"],
        "华鑫上海分公司(量化打板)": ["10274545"],
        "中金上海分公司(量化基金)": ["10088113"],
        "高盛上海世纪大道": ["10000399618"],
        "摩根大通上海银城中路": ["10000100571"],
        "瑞银上海花园石桥路": ["10110478"],
        "国信浙江互联网(25-26暴增)": ["10000213448"],
        "外资_沪股通+深股通": ["10434470", "10634757"],
        "拉萨东财散户团(东环+团结+金融城等)": [
            d for d in dept_meta.index if any("拉萨" in nm for nm in dept_meta.loc[d, "all_names"]) and "东亚" not in dept_meta.loc[d, "latest_name"]
        ],
        "西藏昌都+山南东财散户": ["10342919", "10281327"],
    }
    # Add 兴业陕西分公司 code dynamically if different
    sx_codes = [d for d, r in dept_meta.iterrows() if any("兴业证券股份有限公司陕西分公司" in nm for nm in r["all_names"])]
    if sx_codes:
        special_seats["方新侠(中信朱雀+兴业陕西)"] = sorted(set(["10453418"] + sx_codes))

    migration_table = {}
    for label, codes in special_seats.items():
        sub = lhb_non_org[lhb_non_org["dept_code"].isin(codes)]
        yr_dist = sub["date"].str[:4].value_counts().sort_index().to_dict()
        by_code = {}
        for c in codes:
            sc = sub[sub["dept_code"] == c]
            if not sc.empty:
                by_code[c] = {
                    "latest_name": dept_meta.loc[c, "latest_name"],
                    "aliases": dept_meta.loc[c, "all_names"],
                    "yr_counts": {str(k): int(v) for k, v in sc["date"].str[:4].value_counts().sort_index().to_dict().items()},
                }
        migration_table[label] = {
            "total": int(len(sub)),
            "yr_counts": {str(k): int(v) for k, v in yr_dist.items()},
            "by_dept_code": by_code,
        }

    # 3. Static Dictionary Lookahead & Decay Experiment
    # Exp A: Using static old regex (from existing V19/V40 scripts: 国泰君安.*宜昌, 财通.*上塘, etc.) on 2025-2026
    sub_2526 = lhb_non_org[lhb_non_org["date"] >= "2025-01-01"]
    old_xxp_hit = int(sub_2526["dept_name"].str.contains(r"国泰君安.*宜昌", regex=True).sum())
    true_xxp_total = int((sub_2526["dept_code"] == "10026729").sum())
    old_xy_hit = int(sub_2526["dept_name"].str.contains(r"国泰君安.*太平南路", regex=True).sum())
    true_xy_total = int((sub_2526["dept_code"] == "10025054").sum())
    old_zmz_hy = int(sub_2526["dept_name"].str.contains(r"国泰君安.*海阳西路", regex=True).sum())
    true_zmz_hy = int((sub_2526["dept_code"] == "10000526029").sum())

    # Exp B: Using 2025-2026 active new seat names/codes to back-detect 2021-2023
    sub_2123 = lhb_non_org[lhb_non_org["date"] <= "2023-12-31"]
    # 陈小群: 2025-2026 almost 100% 大连黄河路 (10030463), 0% 金马路 (10657404)
    cxq_2123_tot = int(sub_2123["dept_code"].isin(["10657404", "10030463"]).sum())
    cxq_2123_hh_only = int((sub_2123["dept_code"] == "10030463").sum())
    # Top 2026 seats (2026 top 10 active non-Lhasa/org depts) back-coverage in 2021-2023
    top15_2026 = sub_2526[sub_2526["date"] >= "2026-01-01"]["dept_code"].value_counts().head(15).index.tolist()
    top15_2123 = sub_2123["dept_code"].value_counts().head(15).index.tolist()
    overlap_top15 = len(set(top15_2026) & set(top15_2123))

    # Static name-regex miss rate due to 国泰海通 renaming + relocation
    static_bias_exp = {
        "old_regex_on_2526_xiaoxianpai_miss_pct": round((1.0 - old_xxp_hit / max(1, true_xxp_total)) * 100.0, 1),
        "old_regex_on_2526_xiaoxianpai_hits": f"{old_xxp_hit}/{true_xxp_total}",
        "old_regex_on_2526_zuoshouxinyi_miss_pct": round((1.0 - old_xy_hit / max(1, true_xy_total)) * 100.0, 1),
        "old_regex_on_2526_zuoshouxinyi_hits": f"{old_xy_hit}/{true_xy_total}",
        "old_regex_on_2526_zhangmengzhu_haiyang_miss_pct": round((1.0 - old_zmz_hy / max(1, true_zmz_hy)) * 100.0, 1),
        "old_regex_on_2526_zhangmengzhu_haiyang_hits": f"{old_zmz_hy}/{true_zmz_hy}",
        "new_2026_cxq_huanghe_only_on_2123_miss_pct": round((1.0 - cxq_2123_hh_only / max(1, cxq_2123_tot)) * 100.0, 1),
        "new_2026_cxq_huanghe_only_hits": f"{cxq_2123_hh_only}/{cxq_2123_tot}",
        "top15_depts_2021_23_vs_2026_overlap": f"{overlap_top15}/15",
        "shangtanglu_2123_vs_2026_count": f"{int((sub_2123['dept_code']=='10063083').sum())} -> {int((sub_2526[sub_2526['date']>='2026-01-01']['dept_code']=='10063083').sum())}",
    }

    # 4. Single-day vs 3-day AND Action-State (True Net Buy vs Two-Way DayTrade T vs Net Sell Dump)
    # Focus on Mainboard 10cm non-ST limit-up stocks
    zt10 = mkt_lhb_dates[(~mkt_lhb_dates["is_20cm"]) & (~mkt_lhb_dates["is_st_pit"]) & mkt_lhb_dates["is_zt"]].copy()
    zt10 = zt10[["date", "c6", "streak", "d1_open_pct", "d1_close_pct", "d1_intra_pullback",
                 "d1_is_zt", "d1_is_yizi_zt", "d1_nuke", "d1_buyable", "d1_t2_tradable_net"]].rename(columns={"c6": "stock_code"})

    lhb_zt = lhb_non_org.merge(zt10, on=["date", "stock_code"], how="inner")
    # Classify action state
    ratio_sb = lhb_zt["SELL"] / np.maximum(lhb_zt["BUY"], 1.0)
    lhb_zt["action_state"] = np.select(
        [
            (lhb_zt["NET"] >= 1e7) & (ratio_sb < 0.25),
            (lhb_zt["BUY"] >= 1e7) & (lhb_zt["SELL"] >= 1e7) & (ratio_sb >= 0.25) & (ratio_sb <= 2.5),
            (lhb_zt["NET"] <= -1e7),
        ],
        ["真净买(>=1000万且卖/买<25%)", "双向做T(买卖均>=1000万)", "净卖出砸盘(<=-1000万)"],
        default="小额或混合"
    )

    def summarize_perf(df_sub: pd.DataFrame) -> dict:
        n = len(df_sub)
        if n == 0:
            return {"N": 0}
        b_sub = df_sub[df_sub["d1_buyable"] == True]
        return {
            "N": int(n),
            "d1_open_pct_mean": round(float(df_sub["d1_open_pct"].mean() * 100.0), 2),
            "d1_close_pct_mean": round(float(df_sub["d1_close_pct"].mean() * 100.0), 2),
            "d1_pullback_pct": round(float(df_sub["d1_intra_pullback"].mean() * 100.0), 2),
            "d1_zt_rate_pct": round(float(df_sub["d1_is_zt"].mean() * 100.0), 2),
            "d1_nuke_rate_pct": round(float(df_sub["d1_nuke"].mean() * 100.0), 2),
            "tradable_N": int(b_sub["d1_t2_tradable_net"].notna().sum()),
            "tradable_t2_net_pct": round(float(b_sub["d1_t2_tradable_net"].mean() * 100.0), 2) if b_sub["d1_t2_tradable_net"].notna().any() else None,
        }

    # Global 1-day vs 3-day x action_state across top active youzi dept codes
    key_youzi_codes = {
        "陈小群(金马+黄河)": ["10657404", "10030463"],
        "章盟主(延安+海阳+建国+广福)": ["10046704", "10000526029", "10102873", "10023415"],
        "作手新一(太平南)": ["10025054"],
        "方新侠(朱雀+陕西)": ["10453418"] + sx_codes,
        "宁波桑田路": ["10456710"],
        "上塘路": ["10063083"],
        "消闲派(宜昌珍珠+沿江)": ["10026729"],
        "六一中路/交易猿": ["10318896", "10147201"],
        "量化打板(华鑫上海分)": ["10274545"],
        "量化基金(中金上海分)": ["10088113"],
        "拉萨东财散户": [d for d in dept_meta.index if any("拉萨" in nm for nm in dept_meta.loc[d, "all_names"]) and "东亚" not in dept_meta.loc[d, "latest_name"]],
        "外资(沪深股通)": ["10434470", "10634757"],
    }

    day1_vs_day3_and_actions = {"overall_by_type_action": {}, "by_famous_youzi": {}}
    # All non-Lhasa seats overall
    non_lhasa_mask = ~lhb_zt["dept_code"].isin(key_youzi_codes["拉萨东财散户"])
    for is3_val, lbl3 in [(0, "单日榜"), (1, "三日榜")]:
        for act in ["真净买(>=1000万且卖/买<25%)", "双向做T(买卖均>=1000万)", "净卖出砸盘(<=-1000万)"]:
            sub = lhb_zt[non_lhasa_mask & (lhb_zt["is_three"] == is3_val) & (lhb_zt["action_state"] == act)]
            day1_vs_day3_and_actions["overall_by_type_action"][f"{lbl3}|{act}"] = summarize_perf(sub)

    for yname, ycodes in key_youzi_codes.items():
        sub_y = lhb_zt[lhb_zt["dept_code"].isin(ycodes)]
        res_y = {}
        for is3_val, lbl3 in [(0, "单日榜"), (1, "三日榜")]:
            for act in ["真净买(>=1000万且卖/买<25%)", "双向做T(买卖均>=1000万)", "净卖出砸盘(<=-1000万)"]:
                s = sub_y[(sub_y["is_three"] == is3_val) & (sub_y["action_state"] == act)]
                if len(s) >= 15:
                    res_y[f"{lbl3}|{act}"] = summarize_perf(s)
        day1_vs_day3_and_actions["by_famous_youzi"][yname] = res_y

    atlas_out = {
        "meta": {
            "period": "2021-01-04 ~ 2026-11-17",
            "total_ths_events": int(len(ths)),
            "single_icon_exact_matches": int(len(exact)),
            "unique_ths_icons": len(icon_atlas),
            "fee_assumption": "30 bps roundtrip",
        },
        "purity_audit_top60_and_matched": purity_audit[:120],
        "ths_icon_atlas": icon_atlas,
        "famous_seat_migration_2021_2026": migration_table,
        "static_dict_lookahead_and_decay": static_bias_exp,
        "day1_vs_day3_and_action_states": day1_vs_day3_and_actions,
    }
    with open(f"{SANDBOX}/youzi_seat_atlas_5y.json", "w", encoding="utf-8") as f:
        json.dump(atlas_out, f, ensure_ascii=False, indent=2)
    print(f"Saved {SANDBOX}/youzi_seat_atlas_5y.json in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
