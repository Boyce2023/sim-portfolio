#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
audit_5strategies_priority_winrate.py
全候选池无遮蔽同日撞车配对胜率对比 + 5! (120种) 与 6! (720种，拆分二进三>=96与90~95) 顺位全排列真实回测审计
严格遵循 Buwen 准则：顺位完全靠真实回测对比胜率与净值回撤决定，严禁拍脑袋直接排序。
"""
import os, sys, json, pickle, itertools
import numpy as np
import pandas as pd
from pathlib import Path

SIM = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio")
OUT23 = SIM / "backtests_astock/clean_2to3_v10_20261117"
CLEAN16 = SIM / "backtests_astock/clean_rebacktest_20261116"
sys.path.insert(0, str(OUT23))
import bt_2to3_v10_clean_master as m23

def load_unmasked_daily_top1():
    # 1. 2to3 V1.0 all raw >=90 signals (unmasked before 1-slot)
    _, df_merged, _ = m23.load_all_clean_data()
    df_gated = m23.apply_hard_gates(df_merged)
    df_gated["score"] = m23.score_dataframe(df_gated)
    df23 = df_gated[df_gated["score"] >= 90].copy()
    df23["code"] = df23["code"].astype(str).str.zfill(6)
    df23["net_ret"] = df23["ret_opn_cc"].astype(float)
    df23["exit_date"] = df23["exit_dt_cc"].astype(str)
    df23["exit_hhmm"] = df23["exit_hh_cc"].astype(int)
    df23["buy_hhmm"] = 925
    df23["triggered"] = True
    df23["is_base_passed"] = True
    df23["strategy"] = "二进三_V10"
    keep = ["strategy", "code", "name", "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "net_ret", "score", "triggered", "is_base_passed"]
    df23 = df23.sort_values(["buy_date", "score", "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True])[keep].reset_index(drop=True)
    df23.to_csv(OUT23 / "candidates_2to3_v10_all_raw90.csv", index=False)

    # Same-day top1 for 2to3 >=90, >=96, and 90~95
    d23_all_top1 = df23.groupby("buy_date", as_index=False).first()
    d23_96_top1 = df23[df23["score"] >= 96].groupby("buy_date", as_index=False).first()
    d23_90_95_top1 = df23[(df23["score"] >= 90) & (df23["score"] < 96)].groupby("buy_date", as_index=False).first()

    # 2. Load unmasked candidates from full_candidates_3main_5y.pkl + ledger_aux_pry_v10.csv
    with open(CLEAN16 / "scientific_seasonal_lab/full_candidates_3main_5y.pkl", "rb") as f:
        fc = pickle.load(f)

    def prep_fc(lst, strat_name):
        d = pd.DataFrame(lst)
        d = d[d["is_base_passed"] == True].copy()
        if d["net_ret"].abs().median() > 0.8:
            d["net_ret"] = d["net_ret"] / 100.0
        d["strategy"] = strat_name
        d["buy_hhmm"] = pd.to_numeric(d["buy_hhmm"], errors="coerce").fillna(935).astype(int)
        d["exit_hhmm"] = pd.to_numeric(d["exit_hhmm"], errors="coerce").fillna(1455).astype(int)
        return d.sort_values(["buy_date", "score", "buy_hhmm"], ascending=[True, False, True]).reset_index(drop=True)

    d_hd = prep_fc(fc["high_dragon"], "高标首阴_V51")
    d_34 = prep_fc(fc["3to4"], "三进四_V34")
    d_12 = prep_fc(fc["1to2"], "一进二_V18")

    # Also check clean_rebacktest_20261116 standalone ledgers (to see if any dates differ from full_candidates_3main_5y.pkl)
    d_pry = pd.read_csv(CLEAN16 / "partC_aux/ledger_aux_pry_v10.csv")
    if d_pry["net_ret"].abs().median() > 0.8:
        d_pry["net_ret"] = d_pry["net_ret"] / 100.0
    d_pry["strategy"] = "超跌撬板_V10"
    d_pry["triggered"] = True
    d_pry["is_base_passed"] = True
    d_pry["buy_hhmm"] = 925
    d_pry["exit_hhmm"] = pd.to_numeric(d_pry["exit_hhmm"], errors="coerce").fillna(1455).astype(int)
    d_pry = d_pry[keep].sort_values(["buy_date", "score"], ascending=[True, False]).reset_index(drop=True)

    return {
        "高标首阴": d_hd,
        "三进四": d_34,
        "超跌撬板": d_pry,
        "一进二": d_12,
        "二进三90": df23,
        "二进三96": df23[df23["score"] >= 96].copy().assign(strategy="二进三_96"),
        "二进三90_95": df23[(df23["score"] >= 90) & (df23["score"] < 96)].copy().assign(strategy="二进三_90_95"),
    }

def pairwise_collision_audit(pools: dict, triggered_only: bool = True, start_dt: str = "2021-11-16"):
    """计算两两策略在同日同时出信号时的真实胜率、均益、中位数对比（无单仓遮蔽）"""
    top1_by_strat = {}
    for k, df in pools.items():
        sub = df[df["buy_date"] >= start_dt].copy()
        if triggered_only:
            sub = sub[sub["triggered"] == True]
        top1_by_strat[k] = sub.sort_values(["buy_date", "score", "buy_hhmm"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()

    results = {}
    targets = ["二进三90", "二进三96", "二进三90_95"]
    others = ["高标首阴", "三进四", "超跌撬板", "一进二"]
    for t in targets:
        results[t] = {}
        dt_t = top1_by_strat[t].set_index("buy_date")
        for o in others:
            dt_o = top1_by_strat[o].set_index("buy_date")
            common = sorted(set(dt_t.index) & set(dt_o.index))
            if not common:
                results[t][o] = {"n_days": 0}
                continue
            rt = dt_t.loc[common, "net_ret"].to_numpy()
            ro = dt_o.loc[common, "net_ret"].to_numpy()
            details = []
            for d in common:
                details.append({
                    "date": d,
                    "t_code": dt_t.loc[d, "code"], "t_name": dt_t.loc[d, "name"], "t_score": float(dt_t.loc[d, "score"]),
                    "t_ret_pct": round(float(dt_t.loc[d, "net_ret"]) * 100, 2),
                    "o_code": dt_o.loc[d, "code"], "o_name": dt_o.loc[d, "name"], "o_score": float(dt_o.loc[d, "score"]),
                    "o_ret_pct": round(float(dt_o.loc[d, "net_ret"]) * 100, 2),
                })
            results[t][o] = {
                "n_days": len(common),
                "t_wr_pct": round(float((rt > 0).mean() * 100), 2),
                "o_wr_pct": round(float((ro > 0).mean() * 100), 2),
                "t_avg_pct": round(float(rt.mean() * 100), 2),
                "o_avg_pct": round(float(ro.mean() * 100), 2),
                "head_to_head_o_beats_t_pct": round(float((ro > rt).mean() * 100), 2),
                "details": details,
            }
    return results

def sim_permutation(pools: dict, order: list[str], mode: str = "triggered", start_dt: str = "2021-11-16"):
    """
    mode='triggered': 同日已触发候选按顺位挑第1只可买（匹配 synthesize_master_clean_20261116.py 口径）
    mode='single_order_0926': 盘前 09:26 严格只能挂唯一 1 笔单；若排前面的条件单当天未触发（triggered=False），当天空仓不递补！
    """
    frames = []
    for prio, name in enumerate(order, 1):
        sub = pools[name][pools[name]["buy_date"] >= start_dt].copy()
        if mode == "triggered":
            sub = sub[sub["triggered"] == True].copy()
        # Each strategy picks its own daily Top1 at 09:25 first
        sub = sub.sort_values(["buy_date", "score", "buy_hhmm"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
        sub["prio"] = prio
        sub["strat_key"] = name
        frames.append(sub)
    all_df = pd.concat(frames, ignore_index=True).sort_values(["buy_date", "prio", "score"], ascending=[True, True, False]).reset_index(drop=True)

    picked = []
    cur_exit_dt = ""
    cur_exit_hhmm = 0
    for row in all_df.itertuples(index=False):
        # Check if account is free at 09:26 (or after 09:25 morning exit)
        can_enter = (not cur_exit_dt) or (row.buy_date > cur_exit_dt) or (row.buy_date == cur_exit_dt and row.buy_hhmm > cur_exit_hhmm)
        if not can_enter:
            continue
        if mode == "single_order_0926":
            if not row.triggered:
                # Placed single conditional order at 09:26, failed to trigger by 11:30 -> day wasted (cash), cannot buy lower-priority 09:25 stock retroactively!
                cur_exit_dt = row.buy_date
                cur_exit_hhmm = 1130
                continue
        picked.append(row._asdict())
        cur_exit_dt = row.exit_date
        cur_exit_hhmm = row.exit_hhmm

    df_p = pd.DataFrame(picked)
    def stats_win(d, sdt):
        s = d[d["buy_date"] >= sdt]
        if s.empty:
            return {"n": 0, "wr": 0.0, "plr": 0.0, "nav": 1.0, "mdd": 0.0, "cap10m": 1.0, "ex3_nav": 1.0}
        r = s["net_ret"].to_numpy()
        w, l = r[r > 0], r[r <= 0]
        wr = float(len(w) / len(r) * 100.0)
        plr = float(w.mean() / abs(l.mean())) if (len(w) > 0 and len(l) > 0 and l.mean() < 0) else 99.9
        nav_c = np.cumprod(1.0 + r)
        pk = np.maximum.accumulate(np.insert(nav_c, 0, 1.0))[1:]
        mdd = float(np.max((pk - nav_c) / pk) * 100.0)
        cap = 100.0
        for x in r:
            cap += min(cap, 1000.0) * float(x)
        r_ex3 = np.sort(r)[:-3] if len(r) > 3 else r
        return {
            "n": int(len(r)),
            "wr": round(wr, 2),
            "plr": round(plr, 2),
            "nav": round(float(nav_c[-1]), 2),
            "mdd": round(mdd, 2),
            "cap10m": round(cap / 100.0, 2),
            "ex3_nav": round(float(np.prod(1.0 + r_ex3)), 2),
        }

    by_strat_cnt = df_p["strat_key"].value_counts().to_dict() if not df_p.empty else {}
    by_strat_wr = {k: round(float((g["net_ret"] > 0).mean() * 100), 2) for k, g in df_p.groupby("strat_key")} if not df_p.empty else {}
    return {
        "order": " > ".join(order),
        "5y": stats_win(df_p, "2021-11-16"),
        "3y": stats_win(df_p, "2023-11-16"),
        "2026": stats_win(df_p, "2026-01-01"),
        "by_strat_cnt": by_strat_cnt,
        "by_strat_wr": by_strat_wr,
    }

def main():
    pools = load_unmasked_daily_top1()
    pw_trig = pairwise_collision_audit(pools, triggered_only=True)
    pw_0925 = pairwise_collision_audit(pools, triggered_only=False)

    # Baseline 4-strategy (without 2to3)
    base4_trig = sim_permutation(pools, ["高标首阴", "三进四", "超跌撬板", "一进二"], mode="triggered")
    base4_0926 = sim_permutation(pools, ["高标首阴", "三进四", "超跌撬板", "一进二"], mode="single_order_0926")

    # 1. All 5! = 120 permutations of [高标首阴, 三进四, 超跌撬板, 一进二, 二进三90]
    s5 = ["高标首阴", "三进四", "超跌撬板", "一进二", "二进三90"]
    perms5_trig = [sim_permutation(pools, list(p), mode="triggered") for p in itertools.permutations(s5)]
    perms5_0926 = [sim_permutation(pools, list(p), mode="single_order_0926") for p in itertools.permutations(s5)]

    # 2. Inserting 二进三90 at each of the 5 slots while keeping [高标首阴 > 三进四 > 超跌撬板 > 一进二] fixed
    fixed4 = ["高标首阴", "三进四", "超跌撬板", "一进二"]
    slot5_trig = []
    slot5_0926 = []
    for idx in range(5):
        ord_i = fixed4[:idx] + ["二进三90"] + fixed4[idx:]
        slot5_trig.append(sim_permutation(pools, ord_i, mode="triggered"))
        slot5_0926.append(sim_permutation(pools, ord_i, mode="single_order_0926"))

    # 3. Splitting 二进三96 (high-conviction alert) vs 二进三90_95 across slots relative to fixed4
    slot6_trig = []
    slot6_0926 = []
    for i96 in range(5):
        for i90 in range(i96, 5):
            temp = list(fixed4)
            temp.insert(i90, "二进三90_95")
            temp.insert(i96, "二进三96")
            slot6_trig.append(sim_permutation(pools, temp, mode="triggered"))
            slot6_0926.append(sim_permutation(pools, temp, mode="single_order_0926"))

    out = {
        "pairwise_triggered": pw_trig,
        "pairwise_0925_all_passed": pw_0925,
        "base4_triggered": base4_trig,
        "base4_single_order_0926": base4_0926,
        "slot5_triggered": slot5_trig,
        "slot5_single_order_0926": slot5_0926,
        "top5_perms120_by_5y_wr_triggered": sorted(perms5_trig, key=lambda x: (-x["5y"]["wr"], -x["5y"]["cap10m"]))[:8],
        "top5_perms120_by_5y_wr_0926": sorted(perms5_0926, key=lambda x: (-x["5y"]["wr"], -x["5y"]["cap10m"]))[:8],
        "top5_perms120_by_cap10m_triggered": sorted(perms5_trig, key=lambda x: (-x["5y"]["cap10m"], -x["5y"]["wr"]))[:8],
        "slot6_split96_triggered": sorted(slot6_trig, key=lambda x: (-x["5y"]["wr"], -x["5y"]["cap10m"])),
        "slot6_split96_0926": sorted(slot6_0926, key=lambda x: (-x["5y"]["wr"], -x["5y"]["cap10m"])),
    }
    (OUT23 / "audit_5strategies_priority_permutations_20261117.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print("=== [1] 无遮蔽同日撞车配对胜率对比 (Triggered) ===")
    for t in ["二进三90", "二进三96"]:
        print(f"\n--- {t} vs 四大既有策略 ---")
        for o, v in pw_trig[t].items():
            if v["n_days"] == 0:
                print(f"  vs {o}: 0天撞车 (100%正交)")
            else:
                print(f"  vs {o}: 撞车{v['n_days']}天 | {t}胜率={v['t_wr_pct']}% (均{v['t_avg_pct']:+.2f}%) vs {o}胜率={v['o_wr_pct']}% (均{v['o_avg_pct']:+.2f}%) | {o}单日跑赢率={v['head_to_head_o_beats_t_pct']}%")

    print("\n=== [2] 无遮蔽同日撞车配对胜率对比 (09:25 All Passed 含盘中未触发) ===")
    for t in ["二进三90", "二进三96"]:
        print(f"\n--- {t} vs 四大既有策略 (09:25口径) ---")
        for o, v in pw_0925[t].items():
            if v["n_days"] == 0:
                print(f"  vs {o}: 0天撞车")
            else:
                print(f"  vs {o}: 撞车{v['n_days']}天 | {t}胜率={v['t_wr_pct']}% (均{v['t_avg_pct']:+.2f}%) vs {o}胜率={v['o_wr_pct']}% (均{v['o_avg_pct']:+.2f}%)")

    print("\n=== [3] 原四策略基准 vs 二进三90 插入 5 个顺位全对比 (Triggered口径) ===")
    b = base4_trig["5y"]
    print(f"  [基准4策略] {base4_trig['order']} -> 5Y {b['n']}笔 | 胜率={b['wr']}% | PLR={b['plr']} | 1000万单利={b['cap10m']}x | 单仓复利={b['nav']}x (去前3={b['ex3_nav']}x) | 回撤={b['mdd']}% | 3Y胜率={base4_trig['3y']['wr']}% | 2026胜率={base4_trig['2026']['wr']}%")
    for idx, r in enumerate(slot5_trig, 1):
        m = r["5y"]
        print(f"  [插第{idx}顺位] {r['order']} -> 5Y {m['n']}笔(二进三实做{r['by_strat_cnt'].get('二进三90',0)}笔,胜率{r['by_strat_wr'].get('二进三90',0)}%) | 总胜率={m['wr']}% | PLR={m['plr']} | 1000万单利={m['cap10m']}x | 单仓={m['nav']}x | 回撤={m['mdd']}% | 3Y胜率={r['3y']['wr']}% | 2026胜率={r['2026']['wr']}%")

    print("\n=== [4] 09:26 盘前唯一1笔挂单物理约束口径 (含未触发条件单占坑) ===")
    b2 = base4_0926["5y"]
    print(f"  [基准4策略_0926单笔] {base4_0926['order']} -> 5Y {b2['n']}笔 | 胜率={b2['wr']}% | 1000万单利={b2['cap10m']}x | 单仓={b2['nav']}x | 回撤={b2['mdd']}% | 3Y胜率={base4_0926['3y']['wr']}% | 2026胜率={base4_0926['2026']['wr']}%")
    for idx, r in enumerate(slot5_0926, 1):
        m = r["5y"]
        print(f"  [插第{idx}顺位_0926单笔] {r['order']} -> 5Y {m['n']}笔(二进三实做{r['by_strat_cnt'].get('二进三90',0)}笔,胜率{r['by_strat_wr'].get('二进三90',0)}%) | 总胜率={m['wr']}% | 1000万单利={m['cap10m']}x | 单仓={m['nav']}x | 回撤={m['mdd']}% | 3Y胜率={r['3y']['wr']}% | 2026胜率={r['2026']['wr']}%")

    print("\n=== [5] 拆分 二进三>=96 (单独提醒档) 与 二进三90~95 跨顺位 Top 6 (按5Y胜率排序, 0926单笔口径) ===")
    for r in out["slot6_split96_0926"][:6]:
        m = r["5y"]
        print(f"  {r['order']} -> 5Y {m['n']}笔(96档{r['by_strat_cnt'].get('二进三96',0)}笔WR={r['by_strat_wr'].get('二进三96',0)}%, 90_95档{r['by_strat_cnt'].get('二进三90_95',0)}笔WR={r['by_strat_wr'].get('二进三90_95',0)}%) | 总胜率={m['wr']}% | 1000万单利={m['cap10m']}x | 单仓={m['nav']}x | 回撤={m['mdd']}% | 2026胜率={r['2026']['wr']}%")

    print("\n=== [6] 120种全排列 Top 5 (按总胜率排序, Triggered vs 0926单笔) ===")
    for r in out["top5_perms120_by_5y_wr_triggered"][:5]:
        m = r["5y"]
        print(f"  [Trig] {r['order']} -> 胜率={m['wr']}% | 1000万={m['cap10m']}x | 单仓={m['nav']}x | 回撤={m['mdd']}%")
    for r in out["top5_perms120_by_5y_wr_0926"][:5]:
        m = r["5y"]
        print(f"  [0926] {r['order']} -> 胜率={m['wr']}% | 1000万={m['cap10m']}x | 单仓={m['nav']}x | 回撤={m['mdd']}%")

    # Also compute exact canonical ledger baseline (186 trades, 68.28% WR from synthesize_master_clean_20261116.py)
    sys.path.insert(0, str(CLEAN16))
    import synthesize_master_clean_20261116 as syn
    d_hd = syn.standardize_ledger(str(CLEAN16 / "partA_high_3to4/ledger_base_high_v51.csv"), "高标首阴", 1)
    d_34 = syn.standardize_ledger(str(CLEAN16 / "partA_high_3to4/ledger_base_3to4_v34.csv"), "三进四", 2)
    d_pry = syn.standardize_ledger(str(CLEAN16 / "partC_aux/ledger_aux_pry_v10.csv"), "超跌撬板", 3)
    d_12 = syn.standardize_ledger(str(CLEAN16 / "partB_1to2/ledger_base_1to2_v18.csv"), "一进二", 4)
    d_23 = syn.standardize_ledger(str(OUT23 / "candidates_2to3_v10_all_raw90.csv"), "二进三90", 5)
    fixed4_c = [("高标首阴", d_hd), ("三进四", d_34), ("超跌撬板", d_pry), ("一进二", d_12)]
    base_pool = pd.concat([x[1].assign(priority=i+1) for i, x in enumerate(fixed4_c)], ignore_index=True)
    base_slot = syn.run_1slot(base_pool)
    bm5 = syn.calc_metrics(base_pool, base_slot, "2021-11-16", -18.49)
    print(f"\n=== [7] 对齐 11-16 权威单仓总账口径 (基准4策略 186笔 WR={bm5['win_rate']}% cap10m={bm5['cap10m_mult']}x MDD={bm5['max_dd_pct']}%) ===")
    canon_slots = []
    for idx in range(5):
        seq = fixed4_c[:idx] + [("二进三90", d_23)] + fixed4_c[idx:]
        pool = pd.concat([x[1].assign(priority=i+1) for i, x in enumerate(seq)], ignore_index=True)
        slot = syn.run_1slot(pool)
        m5 = syn.calc_metrics(pool, slot, "2021-11-16", -18.49)
        m3 = syn.calc_metrics(pool, slot, "2023-11-16", 10.33)
        m26 = syn.calc_metrics(pool, slot, "2026-01-01", -14.04)
        m26_7 = syn.calc_metrics(pool, slot, "2026-07-01", -20.08)
        m26_10 = syn.calc_metrics(pool, slot, "2026-10-01", -8.67)
        s23 = slot[(slot["strategy"] == "二进三90") & (slot["buy_date"] >= "2021-11-16")]
        s96 = s23[s23["score"] >= 96]
        nm = " > ".join(x[0] for x in seq)
        wr23 = round(float((s23["net_ret"] > 0).mean() * 100), 2) if len(s23) else 0.0
        wr96 = round(float((s96["net_ret"] > 0).mean() * 100), 2) if len(s96) else 0.0
        canon_slots.append({"slot": idx+1, "order": nm, "5y": m5, "3y": m3, "2026": m26, "2026_7": m26_7, "2026_10": m26_10,
                            "n_2to3": int(len(s23)), "wr_2to3": wr23, "n_96": int(len(s96)), "wr_96": wr96})
        if idx == 4:
            slot.to_csv(OUT23 / "ledger_combined_5strat_slot5_canonical.csv", index=False)
        print(f"  [顺位#{idx+1}] {nm} -> 5Y {m5['n_slot']}笔 总WR={m5['win_rate']}% PLR={m5['wl_ratio']} cap10m={m5['cap10m_mult']}x 单仓={m5['nav_slot']}x MDD={m5['max_dd_pct']}% | 3Y WR={m3['win_rate']}% | 2026 WR={m26['win_rate']}% | 2to3实做={len(s23)}笔(WR={wr23}%, >=96实做{len(s96)}笔WR={wr96}%)")
    out["canonical_186_baseline"] = bm5
    out["canonical_5slots"] = canon_slots
    (OUT23 / "audit_5strategies_priority_permutations_20261117.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
