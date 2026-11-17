#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
audit_intra_strategy_tiers_5y.py
实证检验 Buwen 核心洞察：「每个策略内部超高分机会可能超出其他策略普通过线票的胜率，必须做策略内部分档回测与撞车对比」
严格遵守：
  1. 分档切点先用 2021-2023 样本内分位数与既有定版档位（如三进四102极严档、二进三96高严档）锚定，严核 2024-2026 样本外是否成立；
  2. 同时检验「无遮蔽 09:26 盘前唯一1笔挂单全候选池（含盘中未触发占坑）」与「11-16 权威单仓台账池」双口径；
  3. 逐对输出「低顺位策略超高分档 vs 高顺位策略普通过线档」的真实同日撞车胜率与单仓净值、1000万封顶净值、最大回撤对比。
"""
import os, sys, json, pickle, itertools
import numpy as np
import pandas as pd
from pathlib import Path

SIM = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio")
CLEAN16 = SIM / "backtests_astock/clean_rebacktest_20261116"
OUT23 = SIM / "backtests_astock/clean_2to3_v10_20261117"
sys.path.insert(0, str(CLEAN16))
import synthesize_master_clean_20261116 as syn

def load_pools():
    with open(CLEAN16 / "scientific_seasonal_lab/full_candidates_3main_5y.pkl", "rb") as f:
        fc = pickle.load(f)

    def prep_unmasked(lst, strat_name):
        d = pd.DataFrame(lst)
        d = d[d["is_base_passed"] == True].copy()
        if d["net_ret"].abs().median() > 0.8:
            d["net_ret"] = d["net_ret"] / 100.0
        d["strategy"] = strat_name
        d["buy_hhmm"] = pd.to_numeric(d["buy_hhmm"], errors="coerce").fillna(935).astype(int)
        d["exit_hhmm"] = pd.to_numeric(d["exit_hhmm"], errors="coerce").fillna(1455).astype(int)
        return d.sort_values(["buy_date", "score", "buy_hhmm"], ascending=[True, False, True]).reset_index(drop=True)

    c_hd = syn.standardize_ledger(str(CLEAN16 / "partA_high_3to4/ledger_base_high_v51.csv"), "高标首阴", 1).assign(triggered=True)
    c_34 = syn.standardize_ledger(str(CLEAN16 / "partA_high_3to4/ledger_base_3to4_v34.csv"), "三进四", 2).assign(triggered=True)
    c_pry = syn.standardize_ledger(str(CLEAN16 / "partC_aux/ledger_aux_pry_v10.csv"), "超跌撬板", 3).assign(triggered=True)
    c_12 = syn.standardize_ledger(str(CLEAN16 / "partB_1to2/ledger_base_1to2_v18.csv"), "一进二", 4).assign(triggered=True)
    c_23 = syn.standardize_ledger(str(OUT23 / "candidates_2to3_v10_all_raw90.csv"), "二进三", 5).assign(triggered=True)

    u_hd = prep_unmasked(fc["high_dragon"], "高标首阴")
    u_34 = prep_unmasked(fc["3to4"], "三进四")
    u_pry = c_pry.copy()
    u_12 = prep_unmasked(fc["1to2"], "一进二")
    u_23 = c_23.copy()

    return {
        "canon": {"高标首阴": c_hd, "三进四": c_34, "超跌撬板": c_pry, "一进二": c_12, "二进三": c_23},
        "unmasked_trig": {k: v[v["triggered"] == True].copy() for k, v in [("高标首阴", u_hd), ("三进四", u_34), ("超跌撬板", u_pry), ("一进二", u_12), ("二进三", u_23)]},
        "unmasked_0926": {"高标首阴": u_hd, "三进四": u_34, "超跌撬板": u_pry, "一进二": u_12, "二进三": u_23},
    }

def stats_slice(df: pd.DataFrame):
    if df.empty:
        return {"n": 0, "wr": 0.0, "avg": 0.0, "plr": 0.0}
    d = df.sort_values(["buy_date", "score"], ascending=[True, False]).groupby("buy_date", as_index=False).first()
    r = d["net_ret"].to_numpy()
    w, l = r[r > 0], r[r <= 0]
    plr = float(w.mean() / abs(l.mean())) if (len(w) > 0 and len(l) > 0 and l.mean() < 0) else (99.9 if len(w) > 0 else 0.0)
    return {"n": int(len(r)), "wr": round(float((r > 0).mean() * 100), 2), "avg": round(float(r.mean() * 100), 2), "plr": round(plr, 2)}

def sim_bucket_order(buckets: list[tuple[str, pd.DataFrame]], single_order_0926: bool = False):
    frames = []
    for prio, (bname, bdf) in enumerate(buckets, 1):
        if bdf.empty:
            continue
        sub = bdf[bdf["buy_date"] >= "2021-11-16"].copy()
        if not single_order_0926:
            sub = sub[sub["triggered"] == True].copy()
        if sub.empty:
            continue
        sub = sub.sort_values(["buy_date", "score", "buy_hhmm"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
        sub["prio"] = prio
        sub["bucket"] = bname
        frames.append(sub)
    all_df = pd.concat(frames, ignore_index=True).sort_values(["buy_date", "prio", "score"], ascending=[True, True, False]).reset_index(drop=True)

    picked = []
    cur_exit_dt = ""
    cur_exit_hhmm = 0
    for row in all_df.itertuples(index=False):
        can_enter = (not cur_exit_dt) or (row.buy_date > cur_exit_dt) or (row.buy_date == cur_exit_dt and row.buy_hhmm > cur_exit_hhmm)
        if not can_enter:
            continue
        if single_order_0926 and (not row.triggered):
            cur_exit_dt = row.buy_date
            cur_exit_hhmm = 1130
            continue
        picked.append(row._asdict())
        cur_exit_dt = row.exit_date
        cur_exit_hhmm = row.exit_hhmm

    dp = pd.DataFrame(picked)
    def win_m(sdt):
        s = dp[dp["buy_date"] >= sdt]
        if s.empty: return {"n": 0, "wr": 0.0, "plr": 0.0, "cap10m": 1.0, "nav": 1.0, "mdd": 0.0}
        r = s["net_ret"].to_numpy()
        w, l = r[r > 0], r[r <= 0]
        plr = float(w.mean() / abs(l.mean())) if (len(w) > 0 and len(l) > 0 and l.mean() < 0) else 99.9
        nav_c = np.cumprod(1.0 + r)
        pk = np.maximum.accumulate(np.insert(nav_c, 0, 1.0))[1:]
        mdd = float(np.max((pk - nav_c) / pk) * 100.0)
        cap = 100.0
        for x in r:
            cap += min(cap, 1000.0) * float(x)
        return {"n": int(len(r)), "wr": round(float((r > 0).mean() * 100), 2), "plr": round(plr, 2),
                "cap10m": round(cap / 100.0, 2), "nav": round(float(nav_c[-1]), 2), "mdd": round(mdd, 2)}

    s_is = dp[dp["buy_date"] < "2024-01-01"]
    wr_is = round(float((s_is["net_ret"] > 0).mean() * 100), 2) if len(s_is) else 0.0
    s_oos = dp[dp["buy_date"] >= "2024-01-01"]
    wr_oos = round(float((s_oos["net_ret"] > 0).mean() * 100), 2) if len(s_oos) else 0.0
    return {
        "5y": win_m("2021-11-16"),
        "is_wr": wr_is, "is_n": int(len(s_is)),
        "oos_wr": wr_oos, "oos_n": int(len(s_oos)),
        "3y": win_m("2023-11-16"),
        "2026": win_m("2026-01-01"),
        "bucket_cnt": dp["bucket"].value_counts().to_dict() if not dp.empty else {},
        "bucket_wr": {k: round(float((g["net_ret"] > 0).mean() * 100), 2) for k, g in dp.groupby("bucket")} if not dp.empty else {},
    }

def main():
    pools = load_pools()
    print("=== [1] 五大策略精细分档扫描 (含一进二 340/355/370 上尾检验) ===")
    scan_defs = {
        "高标首阴": [(88, 96, "普通88_95"), (96, 106, "高分96_105"), (106, 999, "超高>=106"), (96, 999, "高严>=96"), (100, 999, "超高>=100")],
        "三进四": [(90, 98, "普通90_97"), (98, 102, "中严98_101"), (102, 999, "极严>=102"), (90, 102, "常规90_101"), (104, 999, "超高>=104")],
        "超跌撬板": [(165, 175, "普通165_174"), (175, 999, "高严>=175"), (180, 999, "超高>=180"), (185, 999, "王牌>=185")],
        "一进二": [(304.8, 335, "普通304.8_334"), (335, 355, "高分335_354"), (355, 999, "超高>=355"), (340, 999, "高严>=340"), (365, 999, "王牌>=365")],
        "二进三": [(90, 96, "普通90_95"), (96, 999, "高严>=96"), (96, 100, "高严96_99"), (100, 999, "满百>=100")],
    }
    for s, bands in scan_defs.items():
        print(f"\n--- {s} ---")
        for lo, hi, lb in bands:
            dc = pools["canon"][s]
            du = pools["unmasked_trig"][s]
            c5 = stats_slice(dc[(dc["buy_date"] >= "2021-11-16") & (dc["score"] >= lo) & (dc["score"] < hi)])
            cis = stats_slice(dc[(dc["buy_date"] >= "2021-11-16") & (dc["buy_date"] < "2024-01-01") & (dc["score"] >= lo) & (dc["score"] < hi)])
            coos = stats_slice(dc[(dc["buy_date"] >= "2024-01-01") & (dc["score"] >= lo) & (dc["score"] < hi)])
            u5 = stats_slice(du[(du["buy_date"] >= "2021-11-16") & (du["score"] >= lo) & (du["score"] < hi)])
            u_oos = stats_slice(du[(du["buy_date"] >= "2024-01-01") & (du["score"] >= lo) & (du["score"] < hi)])
            print(f"  {lb:16s} | 权威5Y: {c5['n']:2d}笔 WR={c5['wr']:6.2f}% avg={c5['avg']:+6.2f}% PLR={c5['plr']:4.2f} (IS={cis['wr']:5.1f}%[{cis['n']}]/OOS={coos['wr']:5.1f}%[{coos['n']}]) | 无遮蔽5Y: {u5['n']:3d}天 WR={u5['wr']:6.2f}% avg={u5['avg']:+6.2f}% (OOS={u_oos['wr']:5.1f}%[{u_oos['n']}])")

    # === [2] 核心实证：构建「策略内部分两档（S级超高分王牌档 vs A级普通过线档）」10个子桶，按真实胜率排顺位 vs 不分档整策略死顺位 ===
    # 注意看各策略 S级切点（全部用既有定版整数门槛或训练集中位数，零新造怪异小数）：
    #   高标首阴: S级 >=96 (73.7% WR) vs A级 88~95 (60.0% WR)  [或 >=100 vs 88~99]
    #   超跌撬板: S级 >=175 (82.4% WR, IS 100% / OOS 70%) vs A级 165~174 (50.0% WR, +1.14% avg!)
    #   三进四  : S级 >=102 (既有极严档, 69.0% WR, +13.04% avg, PLR 3.15) vs A级 90~101 (62.7% WR, +7.81% avg)
    #   一进二  : S级 >=355 (或 >=340) vs A级 304.8~354
    #   二进三  : S级 >=96 (既有高严档, 62.1% raw / 75.0% slot WR, +10.66% avg) vs A级 90~95 (43.6% raw WR, +2.22% avg)

    def make_10buckets(pdict, hd_cut=96, t34_cut=102, pry_cut=175, t12_cut=355, t23_cut=96):
        return {
            "撬板_S": pdict["超跌撬板"][pdict["超跌撬板"]["score"] >= pry_cut],
            "撬板_A": pdict["超跌撬板"][pdict["超跌撬板"]["score"] < pry_cut],
            "高标_S": pdict["高标首阴"][pdict["高标首阴"]["score"] >= hd_cut],
            "高标_A": pdict["高标首阴"][pdict["高标首阴"]["score"] < hd_cut],
            "三进四_S": pdict["三进四"][pdict["三进四"]["score"] >= t34_cut],
            "三进四_A": pdict["三进四"][pdict["三进四"]["score"] < t34_cut],
            "一进二_S": pdict["一进二"][pdict["一进二"]["score"] >= t12_cut],
            "一进二_A": pdict["一进二"][pdict["一进二"]["score"] < t12_cut],
            "二进三_S": pdict["二进三"][pdict["二进三"]["score"] >= t23_cut],
            "二进三_A": pdict["二进三"][pdict["二进三"]["score"] < t23_cut],
        }

    # Pairwise cross-collision check between lower-strategy S-tier vs higher-strategy A-tier on unmasked_trig!
    b_unm = make_10buckets(pools["unmasked_trig"], hd_cut=96, t34_cut=102, pry_cut=175, t12_cut=355, t23_cut=96)
    print("\n=== [2] 跨策略「下位超高分 S档 vs 上位普通过线 A档」无遮蔽同日撞车对决 ===")
    cross_pairs = [
        ("撬板_S", "高标_A"), ("撬板_S", "三进四_A"),
        ("三进四_S", "高标_A"),
        ("一进二_S", "高标_A"), ("一进二_S", "三进四_A"), ("一进二_S", "撬板_A"),
        ("二进三_S", "高标_A"), ("二进三_S", "三进四_A"), ("二进三_S", "撬板_A"), ("二进三_S", "一进二_A"),
        ("一进二_A", "撬板_A"), ("二进三_A", "撬板_A"),
    ]
    for s_lo, a_hi in cross_pairs:
        d1 = b_unm[s_lo][b_unm[s_lo]["buy_date"] >= "2021-11-16"].groupby("buy_date").first()
        d2 = b_unm[a_hi][b_unm[a_hi]["buy_date"] >= "2021-11-16"].groupby("buy_date").first()
        cm = sorted(set(d1.index) & set(d2.index))
        if not cm:
            print(f"  {s_lo:8s} vs {a_hi:8s}: 0天同日撞车")
        else:
            r1, r2 = d1.loc[cm, "net_ret"].to_numpy(), d2.loc[cm, "net_ret"].to_numpy()
            print(f"  {s_lo:8s} vs {a_hi:8s}: 撞车{len(cm)}天 | {s_lo} WR={(r1>0).mean()*100:5.1f}% (均{r1.mean()*100:+6.2f}%) vs {a_hi} WR={(r2>0).mean()*100:5.1f}% (均{r2.mean()*100:+6.2f}%)")

    # Compare candidate tiered priority schemes on BOTH Unmasked_0926, Unmasked_Trig, and Canonical!
    schemes = [
        ("基准_不分档整策略五顺位", ["高标_S", "高标_A", "三进四_S", "三进四_A", "撬板_S", "撬板_A", "一进二_S", "一进二_A", "二进三_S", "二进三_A"]),
        ("方案1_全S王牌优先于全A普通", ["撬板_S", "高标_S", "三进四_S", "一进二_S", "二进三_S", "高标_A", "三进四_A", "一进二_A", "撬板_A", "二进三_A"]),
        ("方案2_S档梯队压低胜率普通档", ["高标_S", "撬板_S", "三进四_S", "高标_A", "一进二_S", "三进四_A", "二进三_S", "一进二_A", "撬板_A", "二进三_A"]),
        ("方案3_精准降级撬板普通与二进三普通", ["高标_S", "撬板_S", "高标_A", "三进四_S", "三进四_A", "一进二_S", "一进二_A", "二进三_S", "撬板_A", "二进三_A"]),
        ("方案4_一进二S与二进三S越级压普通档", ["高标_S", "撬板_S", "三进四_S", "一进二_S", "高标_A", "三进四_A", "二进三_S", "一进二_A", "撬板_A", "二进三_A"]),
        ("方案5_砍除低胜率撬板普通档(仅留>=175)", ["高标_S", "撬板_S", "高标_A", "三进四_S", "三进四_A", "一进二_S", "一进二_A", "二进三_S", "二进三_A"]),
    ]

    for mode_label, pkey, is_0926 in [
        ("无遮蔽_0926盘前唯一1笔挂单口径", "unmasked_0926", True),
        ("权威11_16单仓台账口径", "canon", False),
    ]:
        print(f"\n=== [3] 分档顺位方案真实回测对比 ({mode_label}) ===")
        bk = make_10buckets(pools[pkey], hd_cut=96, t34_cut=102, pry_cut=175, t12_cut=355, t23_cut=96)
        for sname, ord_keys in schemes:
            res = sim_bucket_order([(k, bk[k]) for k in ord_keys], single_order_0926=is_0926)
            m5, m3, m26 = res["5y"], res["3y"], res["2026"]
            print(f"  {sname:32s} | 5Y {m5['n']:3d}笔 WR={m5['wr']:6.2f}% (IS={res['is_wr']:5.1f}%/OOS={res['oos_wr']:5.1f}%/26={m26['wr']:5.1f}%) PLR={m5['plr']:4.2f} cap10m={m5['cap10m']:6.2f}x 单仓={m5['nav']:10.2f}x MDD={m5['mdd']:5.2f}%")

    # === [4] 精细检验：全部同日跨策略高分越级碰撞样本逐笔穿透 + 12子桶精准越级方案 ===
    print("\n=== [4] 12子桶（S+王牌 / S高严 / A普通）越级方案与逐笔碰撞解剖 ===")
    for mode_lb, pk, is0926 in [("无遮蔽_0926唯一1笔", "unmasked_0926", True), ("权威11_16单仓台账", "canon", False)]:
        p = pools[pk]
        b = {
            "HD_S": p["高标首阴"][p["高标首阴"]["score"] >= 96],
            "HD_A": p["高标首阴"][p["高标首阴"]["score"] < 96],
            "T34_SS": p["三进四"][p["三进四"]["score"] >= 108],
            "T34_S": p["三进四"][(p["三进四"]["score"] >= 102) & (p["三进四"]["score"] < 108)],
            "T34_A": p["三进四"][p["三进四"]["score"] < 102],
            "PRY_S": p["超跌撬板"][p["超跌撬板"]["score"] >= 175],
            "PRY_A": p["超跌撬板"][p["超跌撬板"]["score"] < 175],
            "T12_SS": p["一进二"][p["一进二"]["score"] >= 370],
            "T12_S": p["一进二"][(p["一进二"]["score"] >= 355) & (p["一进二"]["score"] < 370)],
            "T12_A": p["一进二"][p["一进二"]["score"] < 355],
            "T23_S": p["二进三"][p["二进三"]["score"] >= 96],
            "T23_A": p["二进三"][p["二进三"]["score"] < 96],
        }
        tests = [
            ("0_整策略五顺位基准", ["HD_S","HD_A","T34_SS","T34_S","T34_A","PRY_S","PRY_A","T12_SS","T12_S","T12_A","T23_S","T23_A"]),
            ("1_三进四108越级压高标普通", ["HD_S","T34_SS","HD_A","T34_S","T34_A","PRY_S","PRY_A","T12_SS","T12_S","T12_A","T23_S","T23_A"]),
            ("2_撬板175保留第3_撬板普通降第5", ["HD_S","HD_A","T34_SS","T34_S","T34_A","PRY_S","T12_SS","T12_S","T12_A","PRY_A","T23_S","T23_A"]),
            ("3_一进二355越级压撬板普通", ["HD_S","HD_A","T34_SS","T34_S","T34_A","PRY_S","T12_SS","T12_S","PRY_A","T12_A","T23_S","T23_A"]),
            ("4_一进二370越级压三进四普通", ["HD_S","HD_A","T34_SS","T34_S","PRY_S","T12_SS","T34_A","T12_S","T12_A","PRY_A","T23_S","T23_A"]),
            ("5_综合越级(T34_108+T12_355压撬板A)", ["HD_S","T34_SS","HD_A","T34_S","T34_A","PRY_S","T12_SS","T12_S","PRY_A","T12_A","T23_S","T23_A"]),
        ]
        print(f"--- {mode_lb} ---")
        for nm, seq in tests:
            r = sim_bucket_order([(k, b[k]) for k in seq], single_order_0926=is0926)
            m = r["5y"]
            print(f"  {nm:32s}: 5Y {m['n']:3d}笔 WR={m['wr']:6.2f}% (IS={r['is_wr']:5.1f}%/OOS={r['oos_wr']:5.1f}%/26={r['2026']['wr']:5.1f}%) PLR={m['plr']:4.2f} cap10m={m['cap10m']:6.2f}x 单仓={m['nav']:10.2f}x MDD={m['mdd']:5.2f}%")

    # Also print EVERY single day where two different strategies both passed on unmasked_trig so we see the exact scores & returns!
    ut = pools["unmasked_trig"]
    top_day = {k: v[v["buy_date"] >= "2021-11-16"].groupby("buy_date").first() for k, v in ut.items()}
    all_dates = sorted(set().union(*[set(d.index) for d in top_day.values()]))
    multi_days = [dt for dt in all_dates if sum(1 for d in top_day.values() if dt in d.index) >= 2]
    print(f"\n=== [5] 全五年多策略同日触发全明细 (共 {len(multi_days)} 个交易日) ===")
    for dt in multi_days:
        items = []
        for s in ["高标首阴", "三进四", "超跌撬板", "一进二", "二进三"]:
            if dt in top_day[s].index:
                row = top_day[s].loc[dt]
                items.append(f"{s}({row['name']} {row['score']:.1f}分 -> {row['net_ret']*100:+.2f}%)")
        print(f"  {dt}: " + "  VS  ".join(items))

if __name__ == "__main__":
    main()
