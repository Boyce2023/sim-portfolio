#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD016 Module 2: 5Y ZT LHB Positive/Negative Leaderboards, Combo Effects & PIT Bayesian Shrinkage Score."""

import json
import os
import re
import time
from collections import defaultdict, deque

import numpy as np
import pandas as pd

SANDBOX = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd016_famous_youzi_seats_20261117"
THS_PQ = f"{SANDBOX}/ths_pit_youzi_5y.parquet"
LHB_PQ = f"{SANDBOX}/clean_lhb_5y.parquet"
ZT_PQ = f"{SANDBOX}/zt_market_5y.parquet"

# Canonical seat groups by OPERATEDEPT_CODE (incorporating Guotai-Haitong renames & migrations)
SEAT_GROUPS = {
    "[组]陈小群(金马+黄河)": {"10657404", "10030463"},
    "[组]六一中路/交易猿(福州六一+二纬)": {"10318896", "10147201"},
    "[组]呼家楼/广渠门/北京总部": {"10045035", "10526806", "10361413"},
    "[组]消闲派(宜昌珍珠+沿江)": {"10026729"},
    "[组]毛老板(东亚苏州)": {"10000526027"},
    "[组]北京知春路(国泰)": {"10025390"},
    "[组]余哥(宁波和源路)": {"10000147202"},
    "[组]作手新一(南京太平南)": {"10025054"},
    "[组]章盟主核心席位": {"10046704", "10023415", "10000526029", "10102873"},
    "[组]方新侠(朱雀+兴业陕西)": {"10453418", "10024604"},
    "[组]上塘路(财通上塘)": {"10063083"},
    "[组]宁波桑田路": {"10456710"},
    "[组]小鳄鱼(长江上海+南京大钟亭)": {"10025461", "10026273"},
    "[组]炒股养家(宛平+茅台+红宝石)": {"10028416", "10048399", "10143273"},
    "[组]开源西安西大街": {"10046745"},
    "[组]开源西安太华路": {"10477800"},
    "[组]量化打板(华鑫上海分)": {"10274545"},
    "[组]量化基金(中金上海+华泰总部)": {"10088113", "10028451"},
    "[组]外资(沪深股通)": {"10434470", "10634757"},
    "[组]瑞银上海花园石桥": {"10110478"},
    "[组]高盛上海世纪大道": {"10000399618"},
    "[组]摩根大通上海银城中路": {"10000100571"},
    "[组]国信浙江互联网": {"10000213448"},
    "[组]拉萨东财散户团": set(),  # populated dynamically
    "[组]西藏昌都+山南东财": {"10342919", "10281327"},
}

TOP_PATRON_GROUPS = {
    "陈小群", "六一中路", "章盟主", "作手新一", "方新侠", "宁波桑田路",
    "小鳄鱼", "炒股养家", "毛老板", "余哥", "北京中关村", "赵老哥", "欢乐海岸",
}


def eval_metrics(df_sub: pd.DataFrame, bench: dict | None = None) -> dict:
    n = len(df_sub)
    if n == 0:
        return {"N": 0}
    op = float(df_sub["d1_open_pct"].mean() * 100.0)
    cl = float(df_sub["d1_close_pct"].mean() * 100.0)
    pb = float(df_sub["d1_intra_pullback"].mean() * 100.0)
    zt_r = float(df_sub["d1_is_zt"].mean() * 100.0)
    nk_r = float(df_sub["d1_nuke"].mean() * 100.0)
    b = df_sub[df_sub["d1_buyable"] & df_sub["d1_t2_tradable_net"].notna()]
    nb = len(b)
    t2 = float(b["d1_t2_tradable_net"].mean() * 100.0) if nb > 0 else np.nan
    wr = float((b["d1_t2_tradable_net"] > 0).mean() * 100.0) if nb > 0 else np.nan
    out = {
        "N": int(n),
        "d1_open_pct": round(op, 2),
        "d1_close_pct": round(cl, 2),
        "d1_pullback_pct": round(pb, 2),
        "d1_zt_rate_pct": round(zt_r, 2),
        "d1_nuke_rate_pct": round(nk_r, 2),
        "tradable_N": int(nb),
        "t2_net_pct": round(t2, 2) if not np.isnan(t2) else None,
        "t2_win_rate_pct": round(wr, 2) if not np.isnan(wr) else None,
    }
    if bench is not None and bench.get("N", 0) > 0:
        out["ex_d1_close_pp"] = round(cl - bench["d1_close_pct"], 2)
        out["ex_t2_net_pp"] = round(t2 - bench["t2_net_pct"], 2) if (not np.isnan(t2) and bench.get("t2_net_pct") is not None) else None
    return out


def split_windows(df_sub: pd.DataFrame, bench_map: dict | None = None) -> dict:
    specs = [
        ("全样本21_26", "2021-01-04", "2026-11-17"),
        ("全五年", "2021-11-16", "2026-11-17"),
        ("IS_21_23", "2021-01-04", "2023-12-31"),
        ("OOS_24_26", "2024-01-01", "2026-11-17"),
        ("2026年内", "2026-01-01", "2026-11-17"),
    ]
    res = {}
    for wname, s, e in specs:
        w = df_sub[(df_sub["date"] >= s) & (df_sub["date"] <= e)]
        bm = bench_map[wname] if bench_map else None
        res[wname] = eval_metrics(w, bm)
    return res


def main():
    t0 = time.time()
    ths = pd.read_parquet(THS_PQ)
    lhb = pd.read_parquet(LHB_PQ)
    zt_all = pd.read_parquet(ZT_PQ)

    # Dynamic lookup for Lhasa, Fangxinxia, Xiaoyu, Yangjia codes
    dept_names = lhb[lhb["dept_code"] != "0"][["dept_code", "dept_name"]].drop_duplicates()
    lhasa_codes = set(dept_names[dept_names["dept_name"].str.contains("拉萨", na=False) & (~dept_names["dept_name"].str.contains("东亚", na=False))]["dept_code"])
    SEAT_GROUPS["[组]拉萨东财散户团"] = lhasa_codes

    # Add extra code mappings dynamically by exact name match
    extra_map = {
        "[组]方新侠(朱雀+兴业陕西)": "兴业证券股份有限公司陕西分公司|中信证券股份有限公司西安朱雀",
        "[组]小鳄鱼(长江上海+南京大钟亭)": "长江证券股份有限公司上海分公司|南京证券股份有限公司南京大钟亭",
        "[组]炒股养家(宛平+茅台+红宝石)": "华鑫证券有限责任公司上海宛平南路|华鑫证券有限责任公司上海茅台路|华鑫证券有限责任公司上海红宝石路",
    }
    for gname, pat in extra_map.items():
        SEAT_GROUPS[gname] |= set(dept_names[dept_names["dept_name"].str.contains(pat, regex=True, na=False)]["dept_code"])

    # Prepare Mainboard 10cm non-ST limit-up stocks with Single-Day LHB (is_three == 0)
    zt10 = zt_all[(~zt_all["is_20cm"]) & (~zt_all["is_st_pit"]) & zt_all["is_zt"]].copy()
    zt10 = zt10.rename(columns={"c6": "stock_code"})
    zt10["board_tier"] = np.select(
        [zt10["streak"] == 1, zt10["streak"] == 2, zt10["streak"] == 3, zt10["streak"] >= 4],
        ["1_首板", "2_二板", "3_三板", "4_四板+"],
        default="1_首板",
    )

    ths_d1 = ths[ths["is_three"] == 0].drop_duplicates(["date", "stock_code"]).copy()
    lhb_d1 = lhb[lhb["is_three"] == 0].copy()

    # Keep only ZT10 stocks that actually appeared on Single-Day LHB
    d1_lhb_keys = lhb_d1[["date", "stock_code"]].drop_duplicates()
    base = zt10.merge(d1_lhb_keys, on=["date", "stock_code"], how="inner")
    base = base.merge(
        ths_d1[["date", "stock_code", "capital_icons_str", "n_capital_icons", "cap_inflow", "org_inflow", "all_inflow"]],
        on=["date", "stock_code"], how="left",
    )
    print(f"[Base ZT10 Single-Day LHB] N={len(base)} (by tier: {base['board_tier'].value_counts().to_dict()})")

    # Compute baseline window benchmarks
    bench_map = split_windows(base, None)
    print("[Benchmarks 全样本21_26]:", bench_map["全样本21_26"])
    print("[Benchmarks IS vs OOS]: IS=", bench_map["IS_21_23"], "OOS=", bench_map["OOS_24_26"])

    # Tier breakdown benchmark
    tier_bench = {t: eval_metrics(g, bench_map["全样本21_26"]) for t, g in base.groupby("board_tier")}

    # =========================================================================
    # Part 1A: 10jqka PIT Youzi Icon Leaderboard (Single-day LHB ZT10)
    # =========================================================================
    icon_rows = []
    # Restrict to events where capital_icons_str has icon (also test cap_inflow > 0)
    icon_events = defaultdict(list)
    icon_pos_events = defaultdict(list)
    for idx_i, r in enumerate(base.itertuples(index=False)):
        ics = str(r.capital_icons_str or "")
        if not ics or ics == "nan":
            continue
        for ic in set(ics.split("|")):
            if ic:
                icon_events[ic].append(idx_i)
                if pd.notna(r.cap_inflow) and r.cap_inflow > 0:
                    icon_pos_events[ic].append(idx_i)

    def make_lb_record(kind: str, entity: str, dept_code: str, df_sub: pd.DataFrame, pos_inflow_t2=None) -> dict:
        w = split_windows(df_sub, bench_map)
        n_is, n_oos = w["IS_21_23"]["N"], w["OOS_24_26"]["N"]
        is_ex, oos_ex = w["IS_21_23"].get("ex_t2_net_pp"), w["OOS_24_26"].get("ex_t2_net_pp")
        is_c, oos_c = w["IS_21_23"].get("ex_d1_close_pp"), w["OOS_24_26"].get("ex_d1_close_pp")
        if n_is >= 15 and n_oos >= 15 and is_ex is not None and oos_ex is not None:
            if is_ex >= 0.3 and oos_ex >= 0.3:
                regime = "跨周期真稳健贵人"
            elif is_ex <= -0.3 and oos_ex <= -0.3:
                regime = "跨周期真毒药"
            elif is_ex >= 0.5 and oos_ex <= -0.3:
                regime = "24-26已被反收割失效"
            elif is_ex <= -0.3 and oos_ex >= 0.3:
                regime = "24-26新崛起反转"
            else:
                regime = "中性/波动"
        else:
            regime = "单期样本不足"
        return {
            "kind": kind,
            "entity": entity,
            "dept_code": dept_code,
            "regime_tag": regime,
            "N_all": w["全样本21_26"]["N"],
            "N_5y": w["全五年"]["N"],
            "d1_open_all": w["全样本21_26"]["d1_open_pct"],
            "d1_close_all": w["全样本21_26"]["d1_close_pct"],
            "d1_pullback_all": w["全样本21_26"]["d1_pullback_pct"],
            "d1_zt_all": w["全样本21_26"]["d1_zt_rate_pct"],
            "d1_nuke_all": w["全样本21_26"]["d1_nuke_rate_pct"],
            "t2_net_all": w["全样本21_26"]["t2_net_pct"],
            "ex_t2_all": w["全样本21_26"].get("ex_t2_net_pp"),
            "N_IS": n_is,
            "d1_close_IS": w["IS_21_23"].get("d1_close_pct"),
            "ex_close_IS": is_c,
            "t2_net_IS": w["IS_21_23"].get("t2_net_pct"),
            "ex_t2_IS": is_ex,
            "nuke_IS": w["IS_21_23"].get("d1_nuke_rate_pct"),
            "N_OOS": n_oos,
            "d1_close_OOS": w["OOS_24_26"].get("d1_close_pct"),
            "ex_close_OOS": oos_c,
            "t2_net_OOS": w["OOS_24_26"].get("t2_net_pct"),
            "ex_t2_OOS": oos_ex,
            "nuke_OOS": w["OOS_24_26"].get("d1_nuke_rate_pct"),
            "N_2026": w["2026年内"]["N"],
            "d1_close_2026": w["2026年内"].get("d1_close_pct"),
            "t2_net_2026": w["2026年内"].get("t2_net_pct"),
            "nuke_2026": w["2026年内"].get("d1_nuke_rate_pct"),
            "pos_inflow_t2_all": pos_inflow_t2,
        }

    lb_records = []
    for ic, idxs in icon_events.items():
        if len(idxs) < 30:
            continue
        w_pos = split_windows(base.iloc[icon_pos_events[ic]], bench_map) if len(icon_pos_events[ic]) >= 30 else None
        pos_t2 = w_pos["全样本21_26"]["t2_net_pct"] if w_pos else None
        lb_records.append(make_lb_record("THS_PIT_ICON", ic, "", base.iloc[idxs], pos_t2))

    # Part 1B: Dept-Code & Seat Group Net-Buy Entry Leaderboard (NET > 0)
    lhb_zt_buy = lhb_d1[(lhb_d1["NET"] > 0)].merge(
        base[["date", "stock_code", "streak", "board_tier", "d1_open_pct", "d1_close_pct",
              "d1_intra_pullback", "d1_is_zt", "d1_nuke", "d1_buyable", "d1_t2_tradable_net"]],
        on=["date", "stock_code"], how="inner",
    )
    dept_events = lhb_zt_buy.drop_duplicates(["date", "stock_code", "dept_code"]).copy()
    latest_dname = dept_names.drop_duplicates("dept_code", keep="last").set_index("dept_code")["dept_name"].to_dict()

    for dcode, grp in dept_events.groupby("dept_code"):
        if len(grp) < 40 and dcode not in {c for s in SEAT_GROUPS.values() for c in s}:
            continue
        if len(grp) < 30:
            continue
        dname = "机构专用(买方出现)" if dcode == "0" else latest_dname.get(dcode, dcode)
        lb_records.append(make_lb_record("DEPT_NET_BUY", dname, dcode, grp))

    for gname, gcodes in SEAT_GROUPS.items():
        grp = dept_events[dept_events["dept_code"].isin(gcodes)].drop_duplicates(["date", "stock_code"])
        if len(grp) < 30:
            continue
        lb_records.append(make_lb_record("SEAT_GROUP_NET_BUY", gname, ",".join(sorted(gcodes))[:60], grp))

    df_lb = pd.DataFrame(lb_records)
    df_lb.to_csv(f"{SANDBOX}/youzi_leaderboard_5y.csv", index=False, encoding="utf-8-sig")
    print(f"Saved youzi_leaderboard_5y.csv: {len(df_lb)} entities")

    # =========================================================================
    # Part 2: Seat Combo & Counterparty Effects
    # =========================================================================
    # Build per-(date, stock_code) seat composition features on single-day LHB
    surf_codes = set(SEAT_GROUPS["[组]上塘路(财通上塘)"]) | set(SEAT_GROUPS["[组]消闲派(宜昌珍珠+沿江)"]) | set(SEAT_GROUPS["[组]开源西安西大街"]) | {
        d for d, nm in latest_dname.items() if any(k in nm for k in ("佛山绿景路", "成都北一环", "东莞证券股份有限公司四川"))
    }
    quant_codes = {"10274545", "10088113", "10028451", "10456831", "10000399618", "10000100571", "10110478", "10135341", "10477800"}
    famous_good_codes = (
        SEAT_GROUPS["[组]陈小群(金马+黄河)"]
        | SEAT_GROUPS["[组]六一中路/交易猿(福州六一+二纬)"]
        | SEAT_GROUPS["[组]章盟主核心席位"]
        | SEAT_GROUPS["[组]作手新一(南京太平南)"]
        | SEAT_GROUPS["[组]方新侠(朱雀+兴业陕西)"]
        | SEAT_GROUPS["[组]毛老板(东亚苏州)"]
        | SEAT_GROUPS["[组]余哥(宁波和源路)"]
        | SEAT_GROUPS["[组]小鳄鱼(长江上海+南京大钟亭)"]
        | SEAT_GROUPS["[组]炒股养家(宛平+茅台+红宝石)"]
        | SEAT_GROUPS["[组]呼家楼/广渠门/北京总部"]
    )
    all_famous_codes = famous_good_codes | surf_codes | SEAT_GROUPS["[组]宁波桑田路"]

    # Map each (date, stock_code) in single-day LHB
    d1_by_evt_b = defaultdict(list)
    d1_by_evt_s = defaultdict(list)
    for r in lhb_d1.itertuples(index=False):
        k = (r.date, r.stock_code)
        if r.side == "B":
            d1_by_evt_b[k].append((r.dept_code, float(r.BUY), float(r.SELL), float(r.NET)))
        if r.side == "S":
            d1_by_evt_s[k].append((r.dept_code, float(r.BUY), float(r.SELL), float(r.NET)))

    combo_feats = []
    for r in base.itertuples(index=False):
        k = (r.date, r.stock_code)
        blist = d1_by_evt_b.get(k, [])
        slist = d1_by_evt_s.get(k, [])
        tot_b = sum(x[1] for x in blist)
        top1_b = max((x[1] for x in blist), default=0.0)
        top1_code = max(blist, key=lambda x: x[1])[0] if blist else ""
        top1_share = (top1_b / tot_b) if tot_b > 0 else 0.0

        b_codes = {x[0] for x in blist if x[3] > 0}
        b_all_codes = {x[0] for x in blist}
        s_codes = {x[0] for x in slist if x[3] < 0}

        n_lhasa_b = sum(1 for x in blist if x[0] in lhasa_codes)
        lh_buy_amt = sum(x[1] for x in blist if x[0] in lhasa_codes)
        lh_share = (lh_buy_amt / tot_b) if tot_b > 0 else 0.0

        n_quant_b = sum(1 for c in b_codes if c in quant_codes)
        has_famous_b = len(b_codes & famous_good_codes) > 0
        has_surf_b = len(b_codes & surf_codes) > 0
        surf_top1_solo = (top1_code in surf_codes) and (top1_share > 0.30)

        n_org_b = sum(1 for x in blist if x[0] == "0")
        n_org_s = sum(1 for x in slist if x[0] == "0")
        org_net = sum(x[3] for x in blist if x[0] == "0") + sum(x[3] for x in slist if x[0] == "0")
        # careful if org appears in both, THS org_inflow is cleaner!
        ths_org_net = float(r.org_inflow) if pd.notna(r.org_inflow) else org_net

        famous_dump_amt = sum(-x[3] for x in slist if x[0] in all_famous_codes and x[3] < 0)
        org_dump = ths_org_net <= -1e7

        combo_feats.append({
            "top1_share": top1_share,
            "surf_top1_solo": surf_top1_solo,
            "n_lhasa_b": n_lhasa_b,
            "lh_share": lh_share,
            "n_quant_b": n_quant_b,
            "has_famous_b": has_famous_b,
            "has_surf_b": has_surf_b,
            "n_org_b": n_org_b,
            "ths_org_net": ths_org_net,
            "famous_or_org_dump_to_lhasa": (n_lhasa_b >= 2) and ((famous_dump_amt >= 1e7) or org_dump),
            "b_famous_codes": b_codes & famous_good_codes,
            "s_famous_codes": s_codes & famous_good_codes,
        })

    cf_df = pd.DataFrame(combo_feats)
    base_c = pd.concat([base.reset_index(drop=True), cf_df], axis=1)

    combo_results = {}
    combo_masks = {
        "1_一日游买一独食(>30%)": base_c["surf_top1_solo"],
        "2_非独食且有买方合力(top1<=30%)": base_c["top1_share"] <= 0.30,
        "3_知名游资+量化同榜共振": base_c["has_famous_b"] & (base_c["n_quant_b"] >= 1) & (base_c["n_lhasa_b"] == 0),
        "4_纯量化扎堆(>=2量化且无知名游资)": (base_c["n_quant_b"] >= 2) & (~base_c["has_famous_b"]),
        "5_纯机构真净买(>=2买方机构且净买>0且0拉萨)": (base_c["n_org_b"] >= 2) & (base_c["ths_org_net"] > 1e7) & (base_c["n_lhasa_b"] == 0) & (~base_c["has_surf_b"]),
        "6_假机构一日游(1家机构且净买<=0或伴随拉萨一日游)": (base_c["n_org_b"] == 1) & ((base_c["ths_org_net"] <= 0) | (base_c["n_lhasa_b"] >= 1) | base_c["has_surf_b"]),
        "7_买方零拉萨": base_c["n_lhasa_b"] == 0,
        "8_买方拉萨占比0~20%": (base_c["lh_share"] > 0) & (base_c["lh_share"] < 0.20),
        "9_买方拉萨占比>=20%": base_c["lh_share"] >= 0.20,
        "10_卖方游资或机构千万级出货给>=2家拉萨": base_c["famous_or_org_dump_to_lhasa"],
    }
    for label, msk in combo_masks.items():
        combo_results[label] = split_windows(base_c[msk], bench_map)

    # Lock vs Dump test on consecutive days (yesterday net-buy famous patron vs today same stock on LHB)
    # Index all single-day LHB famous patron buys and sells by (date, stock_code)
    patron_buy_by_key = {(r.date, r.stock_code): r.b_famous_codes for r in base_c.itertuples(index=False)}
    # Also build from lhb_d1 for stocks that were on LHB yesterday even if not zt10
    all_d1_b_famous = defaultdict(set)
    all_d1_s_famous = defaultdict(set)
    for r in lhb_d1[lhb_d1["dept_code"].isin(famous_good_codes)].itertuples(index=False):
        if r.NET > 0:
            all_d1_b_famous[(r.date, r.stock_code)].add(r.dept_code)
        elif r.NET < -2e6:
            all_d1_s_famous[(r.date, r.stock_code)].add(r.dept_code)

    # Get ordered trading dates from ths/lhb
    all_tdts = sorted(zt_all["date"].unique().tolist())
    prev_dt_map = {all_tdts[i]: all_tdts[i - 1] for i in range(1, len(all_tdts))}

    lock_flags = []
    for r in base_c.itertuples(index=False):
        pd1 = prev_dt_map.get(r.date)
        if not pd1:
            lock_flags.append("无")
            continue
        yb = all_d1_b_famous.get((pd1, r.stock_code), set())
        if not yb:
            lock_flags.append("无前日著名买方")
            continue
        today_s = set()
        for dc, _, _, nt in d1_by_evt_s.get((r.date, r.stock_code), []):
            if nt < -1e6:
                today_s.add(dc)
        dumped = yb & today_s
        if dumped:
            lock_flags.append("次日著名游资砸盘出货")
        else:
            # Either bought more or locked (absent from top-5 sell)
            lock_flags.append("次日著名游资锁仓或加仓")

    base_c["lock_state"] = lock_flags
    combo_results["11_连续上榜_前日著名游资今日锁仓或加仓"] = split_windows(base_c[base_c["lock_state"] == "次日著名游资锁仓或加仓"], bench_map)
    combo_results["12_连续上榜_前日著名游资今日上卖榜砸盘"] = split_windows(base_c[base_c["lock_state"] == "次日著名游资砸盘出货"], bench_map)

    # =========================================================================
    # Part 3: Pure Data-Driven Rolling 250-Day Bayesian Shrinkage Seat Score
    # =========================================================================
    # Strict zero-lookahead: at date T (post-close), only use events from [T-250, T-2]
    # Because T-1 event's T+2 return happens on T+1! So <= T-2 guarantees T+1 and T+2 settled by T!
    # For T+1 close excess, T-1 is settled at T close, so [T-250, T-1] is usable for d1_close_pct!
    # Let's maintain rolling 250d queues cleanly for BOTH d1_close_ex and t2_net_ex using [T-250, T-2] so zero lookahead even for T+2!
    t_b0 = time.time()
    all_dates_sorted = all_tdts
    date_to_idx = {d: i for i, d in enumerate(all_dates_sorted)}

    # Gather per-date, per-stock net buyers (non-org or all dept_code) and realized outcomes
    evt_outcomes = {}
    for r in base_c.itertuples(index=False):
        evt_outcomes[(r.date, r.stock_code)] = (
            float(r.d1_close_pct) if pd.notna(r.d1_close_pct) else np.nan,
            float(r.d1_t2_tradable_net) if pd.notna(r.d1_t2_tradable_net) else np.nan,
        )

    # Build day-level records of (dept_code, d1_close, t2_net) for net-buyers
    day_dept_obs = defaultdict(list)
    for r in dept_events.itertuples(index=False):
        if r.dept_code == "0":
            continue
        day_dept_obs[r.date].append((
            r.dept_code,
            float(r.d1_close_pct) if pd.notna(r.d1_close_pct) else np.nan,
            float(r.d1_t2_tradable_net) if pd.notna(r.d1_t2_tradable_net) else np.nan,
        ))

    day_base_obs = defaultdict(list)
    for r in base_c.itertuples(index=False):
        day_base_obs[r.date].append((
            float(r.d1_close_pct) if pd.notna(r.d1_close_pct) else np.nan,
            float(r.d1_t2_tradable_net) if pd.notna(r.d1_t2_tradable_net) else np.nan,
        ))

    # Rolling sums over 250 trading days ending at idx - 2
    dept_c_sum = defaultdict(float)
    dept_c_cnt = defaultdict(int)
    dept_t2_sum = defaultdict(float)
    dept_t2_cnt = defaultdict(int)
    base_c_sum, base_c_cnt = 0.0, 0
    base_t2_sum, base_t2_cnt = 0.0, 0

    m_shrink = 15.0
    min_n = 15
    # Map (date, dept_code) -> (bayes_d1c, bayes_t2, n_obs) for saving and scoring
    bayes_seat_rows = []
    daily_score_lookup = {}  # (date, dept_code) -> (b_c, b_t2)

    q_add_idx = 0
    q_rem_idx = 0

    for cur_idx, cur_dt in enumerate(all_dates_sorted):
        # Settle events up to cur_idx - 2
        target_end = cur_idx - 2
        while q_add_idx <= target_end:
            d_add = all_dates_sorted[q_add_idx]
            for dc, c_v, t2_v in day_dept_obs.get(d_add, []):
                if not np.isnan(c_v):
                    dept_c_sum[dc] += c_v
                    dept_c_cnt[dc] += 1
                if not np.isnan(t2_v):
                    dept_t2_sum[dc] += t2_v
                    dept_t2_cnt[dc] += 1
            for c_v, t2_v in day_base_obs.get(d_add, []):
                if not np.isnan(c_v):
                    base_c_sum += c_v
                    base_c_cnt += 1
                if not np.isnan(t2_v):
                    base_t2_sum += t2_v
                    base_t2_cnt += 1
            q_add_idx += 1

        # Remove events older than 250 trading days before cur_idx
        target_start = max(0, cur_idx - 252)
        while q_rem_idx < target_start:
            d_rem = all_dates_sorted[q_rem_idx]
            for dc, c_v, t2_v in day_dept_obs.get(d_rem, []):
                if not np.isnan(c_v):
                    dept_c_sum[dc] -= c_v
                    dept_c_cnt[dc] -= 1
                if not np.isnan(t2_v):
                    dept_t2_sum[dc] -= t2_v
                    dept_t2_cnt[dc] -= 1
            for c_v, t2_v in day_base_obs.get(d_rem, []):
                if not np.isnan(c_v):
                    base_c_sum -= c_v
                    base_c_cnt -= 1
                if not np.isnan(t2_v):
                    base_t2_sum -= t2_v
                    base_t2_cnt -= 1
            q_rem_idx += 1

        mu0_c = (base_c_sum / base_c_cnt) if base_c_cnt > 0 else 0.0
        mu0_t2 = (base_t2_sum / base_t2_cnt) if base_t2_cnt > 0 else 0.0

        for dc, cnt_t2 in dept_t2_cnt.items():
            if cnt_t2 >= min_n:
                cnt_c = dept_c_cnt[dc]
                b_c = (cnt_c / (cnt_c + m_shrink)) * ((dept_c_sum[dc] / cnt_c) - mu0_c) if cnt_c >= min_n else 0.0
                b_t2 = (cnt_t2 / (cnt_t2 + m_shrink)) * ((dept_t2_sum[dc] / cnt_t2) - mu0_t2)
                daily_score_lookup[(cur_dt, dc)] = (b_c, b_t2)

    lhb_b_pos = lhb_d1[(lhb_d1["NET"] > 0) & (lhb_d1["dept_code"] != "0")][["date", "stock_code", "dept_code", "NET"]].copy()
    lhb_b_pos["b_c"] = [daily_score_lookup.get((d, c), (0.0, 0.0))[0] for d, c in zip(lhb_b_pos["date"], lhb_b_pos["dept_code"])]
    lhb_b_pos["b_t2"] = [daily_score_lookup.get((d, c), (0.0, 0.0))[1] for d, c in zip(lhb_b_pos["date"], lhb_b_pos["dept_code"])]
    lhb_b_pos.to_parquet(f"{SANDBOX}/bayes_seat_scores_d1_5y.parquet", index=False)

    # Aggregate stock-level Bayesian score on base_c (net-buy weighted average)
    stk_bayes_c = {}
    stk_bayes_t2 = {}
    for (dt, sc), g in lhb_b_pos.groupby(["date", "stock_code"], sort=False):
        w = np.maximum(g["NET"].to_numpy(dtype=float), 1.0)
        stk_bayes_c[(dt, sc)] = float(np.sum(w * g["b_c"].to_numpy()) / np.sum(w))
        stk_bayes_t2[(dt, sc)] = float(np.sum(w * g["b_t2"].to_numpy()) / np.sum(w))

    base_c["bayes_d1c"] = [stk_bayes_c.get((d, sc), 0.0) for d, sc in zip(base_c["date"], base_c["stock_code"])]
    base_c["bayes_t2"] = [stk_bayes_t2.get((d, sc), 0.0) for d, sc in zip(base_c["date"], base_c["stock_code"])]

    # Quintile evaluation starting 2022-01-04 (after 1-year burn-in)
    bayes_eval = {}
    for p_name, s_dt, e_dt in [("全周期22_26", "2022-01-04", "2026-11-17"), ("IS_22_23", "2022-01-04", "2023-12-31"), ("OOS_24_26", "2024-01-01", "2026-11-17"), ("2026年内", "2026-01-01", "2026-11-17")]:
        sub_p = base_c[(base_c["date"] >= s_dt) & (base_c["date"] <= e_dt) & (base_c["bayes_t2"] != 0.0)].copy()
        if len(sub_p) >= 50:
            sub_p["q_t2"] = pd.qcut(sub_p["bayes_t2"], 5, labels=["Q1_最差席位", "Q2", "Q3", "Q4", "Q5_最优席位"], duplicates="drop")
            q_res = {str(ql): eval_metrics(qg, bench_map["全样本21_26"]) for ql, qg in sub_p.groupby("q_t2", observed=True)}
            bayes_eval[p_name] = q_res
    print(f"[Bayesian Rolling 250d] Computed in {time.time()-t_b0:.1f}s")

    out_m2 = {
        "benchmarks": bench_map,
        "board_tier_benchmarks": tier_bench,
        "combo_and_counterparty_effects": combo_results,
        "bayesian_rolling_250d_quintiles": bayes_eval,
    }
    with open(f"{SANDBOX}/module2_combo_and_bayes.json", "w", encoding="utf-8") as f:
        json.dump(out_m2, f, ensure_ascii=False, indent=2)
    print(f"Saved module2_combo_and_bayes.json in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
