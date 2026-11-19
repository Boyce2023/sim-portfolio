#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_ablation_price60.py
一进二 V19 硬门槛 close <= 60.0 五年严格 PIT 消融回测与明细审计。
"""

import json
import os
import sys
import time

import numpy as np
import pandas as pd

ABL_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/ablation_1to2_price60_20261119"
UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
if ABL_DIR not in sys.path:
    sys.path.insert(0, ABL_DIR)
if UPG_DIR not in sys.path:
    sys.path.insert(0, UPG_DIR)

import upgrade_1to2_pit as u
from pit_signal_base import build_base_ctx_pit, apply_variant_v19

VARIANTS = [
    ("Base_le60", 60.0, 0.0),
    ("NoCap", None, 0.0),
    ("Cap_80", 80.0, 0.0),
    ("Cap_100", 100.0, 0.0),
    ("Soft_m10", None, -10.0),
    ("Soft_m20", None, -20.0),
]


def inspect_forensics_nonfatal(trades_list, ctx):
    pl = ctx["price_lookup"]
    bars = ctx["bars_5m_map"]
    all_dts = ctx["all_dts"]
    dt_to_idx = ctx["dt_to_idx"]
    t0_viol = sum(1 for t in trades_list if t["exit_date"] <= t["buy_date"])
    overlap_viol = 0
    for i in range(len(trades_list) - 1):
        c_t, n_t = trades_list[i], trades_list[i + 1]
        if n_t["buy_date"] < c_t["exit_date"] or (n_t["buy_date"] == c_t["exit_date"] and not c_t["exit_at_open"]):
            overlap_viol += 1
    yizi_viol = 0
    tot_days, cov_days, miss_days = 0, 0, []
    for t in trades_list:
        c6 = str(t["code"]).zfill(6)
        b_bar = pl.get((c6, t["buy_date"]))
        if b_bar and b_bar[0] >= b_bar[4] - 0.005:
            yizi_viol += 1
        bi, ei = dt_to_idx[t["buy_date"]], dt_to_idx[t["exit_date"]]
        for idx in range(bi, ei + 1):
            dt = all_dts[idx]
            tot_days += 1
            if (c6, dt) in bars:
                cov_days += 1
            else:
                miss_days.append(f"{dt}:{c6}:{t['name']}")
    cov_pct = round(cov_days / tot_days * 100.0, 2) if tot_days > 0 else 100.0
    return {
        "t0_violations": t0_viol,
        "overlap_violations": overlap_viol,
        "yizi_buy_violations": yizi_viol,
        "five_min_coverage_pct": cov_pct,
        "five_min_checked_days": tot_days,
        "five_min_missing_days": miss_days,
    }


def enrich_trades(trades_list, ctx, in_1s_keys=None):
    hist = ctx["hist_fb"]
    meta_map = {
        (r.d2_dt, str(r.c6).zfill(6)): (float(r.close), float(r.mcap), str(r.plate), str(r.name), float(r.score_active))
        for r in hist[["d2_dt", "c6", "close", "mcap", "plate", "name", "score_active"]].itertuples(index=False)
    }
    out = []
    for t in trades_list:
        c6 = str(t["code"]).zfill(6)
        bd = t["buy_date"]
        c_d1, mcap, plate, nm, sc = meta_map.get((bd, c6), (np.nan, np.nan, "", t.get("name", ""), t.get("score", np.nan)))
        rec = dict(t)
        rec["code"] = c6
        rec["name"] = nm or t.get("name", "")
        rec["close_d1"] = round(c_d1, 2)
        rec["mcap"] = round(mcap, 2)
        rec["plate"] = plate
        rec["score_active"] = round(sc, 1)
        if in_1s_keys is not None:
            rec["in_1s_slot"] = (bd, c6) in in_1s_keys
        out.append(rec)
    return out


def calc_sub_stats(rets):
    n = len(rets)
    if n == 0:
        return {"n": 0, "win_rate_pct": 0.0, "mean_ret_pct": 0.0, "med_ret_pct": 0.0, "plr": 0.0}
    arr = np.array(rets, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0) else (99.9 if len(wins) > 0 else 0.0)
    return {
        "n": int(n),
        "win_rate_pct": round(float((arr > 0).mean() * 100.0), 2),
        "mean_ret_pct": round(float(arr.mean() * 100.0), 2),
        "med_ret_pct": round(float(np.median(arr) * 100.0), 2),
        "plr": round(plr, 2),
    }


def evaluate_one_variant(base_ctx, name, price_cap, soft_pen, fee_rate, sh300_full, windows):
    u.FEE_RATE = float(fee_rate)
    ctx = apply_variant_v19(base_ctx, price_cap=price_cap, soft_pen_gt60=soft_pen)
    sim_fn = u.make_trade_sim(ctx, use_m1_d3_exempt=True)
    tr_1s, eq_rets, eq_sigs = u.run_slot_and_eq(
        ctx, ctx["mask_v19"], "_sv_v19", sim_fn, u.CANON_5Y_START, u.DATA_END_DT
    )
    forensics_1s = inspect_forensics_nonfatal(tr_1s, ctx)
    forensics_eq = inspect_forensics_nonfatal(eq_sigs, ctx)

    d15 = {}
    for wname, sd, ed, b_ov in windows:
        d15[wname] = u.calc_window_metrics(tr_1s, eq_rets, sd, ed, sh300_full, b_ov)

    in_1s_keys = {(t["buy_date"], str(t["code"]).zfill(6)) for t in tr_1s}
    tr_1s_e = enrich_trades(tr_1s, ctx, in_1s_keys)
    eq_sigs_e = enrich_trades(eq_sigs, ctx, in_1s_keys)

    # 统计全部通过 mask_v19 的 close > 60 候选（含未触发 11:30 买点的）
    hist = ctx["hist_fb"]
    pass_df = hist[ctx["mask_v19"] & (hist["d2_dt"] >= u.CANON_5Y_START) & (hist["d2_dt"] <= u.DATA_END_DT)].copy()
    eq_map = {(t["buy_date"], t["code"]): t for t in eq_sigs_e}
    gt60_cands = []
    for r in pass_df[pass_df["close"] > 60.0].sort_values(["d2_dt", "_sv_v19"], ascending=[True, False]).itertuples(index=False):
        c6 = str(r.c6).zfill(6)
        tr = eq_map.get((r.d2_dt, c6))
        gt60_cands.append({
            "buy_date": r.d2_dt, "code": c6, "name": r.name,
            "close_d1": round(float(r.close), 2), "mcap": round(float(r.mcap), 2),
            "plate": r.plate, "d2_o_pct": round(float(r.d2_o_pct) * 100.0, 2),
            "score": round(float(r.score_active), 1),
            "triggered_buy": tr is not None,
            "in_1s_slot": (r.d2_dt, c6) in in_1s_keys,
            "buy_price": tr["buy_price"] if tr else np.nan,
            "exit_date": tr["exit_date"] if tr else "",
            "exit_price": tr["exit_price"] if tr else np.nan,
            "net_ret": tr["net_ret"] if tr else np.nan,
            "tag": tr["tag"] if tr else "no_trig_before_1130_or_yizi",
        })

    return {
        "name": name, "price_cap": price_cap, "soft_pen": soft_pen, "fee_rate": fee_rate,
        "ctx": ctx, "d15": d15, "forensics_1s": forensics_1s, "forensics_eq": forensics_eq,
        "tr_1s": tr_1s_e, "eq_sigs": eq_sigs_e, "gt60_cands": gt60_cands,
        "passed_total_rows": int(len(pass_df)),
        "passed_gt60_rows": int((pass_df["close"] > 60.0).sum()),
    }


def main():
    t0 = time.time()
    with open(u.IDX_JSON_PATH, encoding="utf-8") as f:
        sh300_full = json.load(f)["sh000300"]
    with open(u.CSI300_BENCH_FILE, encoding="utf-8") as f:
        csi_canon = json.load(f)

    windows = [
        ("全五年", u.CANON_5Y_START, u.DATA_END_DT, csi_canon.get("全五年(2021-11-16起)", [-18.49])[0]),
        ("IS_21_23", "2021-11-15", "2023-12-31", None),
        ("OOS_24_26", "2024-01-01", u.DATA_END_DT, csi_canon.get("近三年(2024-01-01起)", [15.99])[0]),
        ("近三年", "2023-11-16", u.DATA_END_DT, csi_canon.get("近三年(2023-11-16起)", [10.33])[0]),
        ("2025_2026", "2025-01-01", u.DATA_END_DT, None),
        ("2026全年", "2026-01-01", u.DATA_END_DT, csi_canon.get("2026全年", [-14.04])[0]),
    ]

    base_ctx = build_base_ctx_pit(u.DATA_END_DT)

    # 1. 基线复现校验 (FEE=0.0020 对齐 upgrade_1to2_pit.py 原版结果)
    base_002 = evaluate_one_variant(base_ctx, "Base_le60", 60.0, 0.0, 0.0020, sh300_full, windows)
    ref_df = pd.read_csv(f"{UPG_DIR}/ledger_upg_1to2.csv", dtype={"code": str})
    assert len(base_002["tr_1s"]) == len(ref_df), f"Count mismatch: {len(base_002['tr_1s'])} vs {len(ref_df)}"
    max_diff = max(
        abs(float(a["net_ret"]) - float(b.net_ret))
        for a, b in zip(base_002["tr_1s"], ref_df.itertuples(index=False))
    )
    assert max_diff == 0.0, f"Base_le60 vs V19 ref diff={max_diff}"
    print(f"[Baseline Check PASSED] FEE=0.0020 Base_le60 matches V19 ref ({len(ref_df)} trades, max_diff={max_diff})")

    # 2. 分别跑千三 (0.0030) 主表与千二 (0.0020) 对照表
    all_summaries = {}
    for fee_label, fee_val in [("fee_30bps", 0.0030), ("fee_20bps", 0.0020)]:
        res_map = {}
        print(f"\n=== 消融测试 ({fee_label}: FEE_RATE={fee_val:.4f}) ===")
        for vname, pcap, spen in VARIANTS:
            r = evaluate_one_variant(base_ctx, vname, pcap, spen, fee_val, sh300_full, windows)
            res_map[vname] = r
            w5 = r["d15"]["全五年"]
            w3 = r["d15"]["近三年"]
            w26 = r["d15"]["2026全年"]
            f1 = r["forensics_1s"]
            fe = r["forensics_eq"]
            print(
                f"  {vname:<10} | pass={r['passed_total_rows']}(>60:{r['passed_gt60_rows']}) | "
                f"5Y:{w5['trades']}b WR={w5['win_rate_pct']}% PLR={w5['plr']} 1S={w5['nav_1s']}x EQ={w5['eq_nav']}x "
                f"Trim3={w5['trim3_nav']}x MDD={w5['mdd_pct']}% Ex1S={w5['excess_1s_pp']:+.1f}pp | "
                f"3Y:{w3['trades']}b WR={w3['win_rate_pct']}% 1S={w3['nav_1s']}x EQ={w3['eq_nav']}x | "
                f"26:{w26['trades']}b WR={w26['win_rate_pct']}% 1S={w26['nav_1s']}x | "
                f"5m_1S={f1['five_min_coverage_pct']}%(miss={len(f1['five_min_missing_days'])}) "
                f"5m_EQ={fe['five_min_coverage_pct']}%(miss={len(fe['five_min_missing_days'])})"
            )

        # 保存 NoCap 等详细明细与 summary
        all_summaries[fee_label] = {
            vn: {
                "passed_total_rows": r["passed_total_rows"],
                "passed_gt60_rows": r["passed_gt60_rows"],
                "d15": r["d15"],
                "forensics_1s": r["forensics_1s"],
                "forensics_eq": r["forensics_eq"],
            }
            for vn, r in res_map.items()
        }

        if fee_label == "fee_30bps":
            # 输出 NoCap 下所有 close > 60 候选与成交明细 CSV
            nocap = res_map["NoCap"]
            pd.DataFrame(nocap["gt60_cands"]).to_csv(f"{ABL_DIR}/nocap_gt60_candidates_30bps.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame(nocap["tr_1s"]).to_csv(f"{ABL_DIR}/nocap_1s_trades_30bps.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame(nocap["eq_sigs"]).to_csv(f"{ABL_DIR}/nocap_eq_trades_30bps.csv", index=False, encoding="utf-8-sig")
            for vn, r in res_map.items():
                pd.DataFrame(r["tr_1s"]).to_csv(f"{ABL_DIR}/{vn}_1s_30bps.csv", index=False, encoding="utf-8-sig")

            # 分时期统计 close > 60 成交表现 + 全量打印候补与成交清单
            gt60_eq = [t for t in nocap["eq_sigs"] if t["close_d1"] > 60.0]
            gt60_1s = [t for t in nocap["tr_1s"] if t["close_d1"] > 60.0]
            print("\n--- NoCap 新增 close > 60 全量候选与成交明细 (30bps) ---")
            print(f"  passed_cands(>60)={len(nocap['gt60_cands'])}, eq_filled(>60)={len(gt60_eq)}, 1s_filled(>60)={len(gt60_1s)}")
            for c in nocap["gt60_cands"]:
                print("   ", c)
            for grp_name, tlist in [("EQ全部触发成交(>60)", gt60_eq), ("1S单仓实际选中(>60)", gt60_1s)]:
                is_r = [t["net_ret"] for t in tlist if "2021-01-01" <= t["buy_date"] <= "2023-12-31"]
                oos_r = [t["net_ret"] for t in tlist if t["buy_date"] >= "2024-01-01"]
                y2526_r = [t["net_ret"] for t in tlist if t["buy_date"] >= "2025-01-01"]
                all_r = [t["net_ret"] for t in tlist]
                print(f"  [{grp_name}]")
                print("    ALL      :", calc_sub_stats(all_r))
                print("    IS 21-23 :", calc_sub_stats(is_r))
                print("    OOS 24-26:", calc_sub_stats(oos_r))
                print("    2025-2026:", calc_sub_stats(y2526_r))

            # 对比 Base_le60 vs NoCap / Soft_m10 单仓逐笔差异（含被挤占的原有交易！）
            b_map = {(t["buy_date"], t["code"]): t for t in res_map["Base_le60"]["tr_1s"]}
            for vn in ["NoCap", "Cap_80", "Cap_100", "Soft_m10", "Soft_m20"]:
                v_map = {(t["buy_date"], t["code"]): t for t in res_map[vn]["tr_1s"]}
                added = [v_map[k] for k in sorted(set(v_map) - set(b_map))]
                dropped = [b_map[k] for k in sorted(set(b_map) - set(v_map))]
                print(f"  [1S Diff Base_le60 -> {vn}] +{len(added)} / -{len(dropped)}")
                for t in added:
                    print(f"    + {t['buy_date']} {t['code']} {t['name']} c_d1={t['close_d1']} sc={t['score']} buy={t['buy_price']} exit={t['exit_price']} ret={t['net_ret']:+.4f} {t['tag']}")
                for t in dropped:
                    print(f"    - {t['buy_date']} {t['code']} {t['name']} c_d1={t['close_d1']} sc={t['score']} buy={t['buy_price']} exit={t['exit_price']} ret={t['net_ret']:+.4f} {t['tag']}")

            # 全市场 close > 60 首板漏斗拆解（为什么 2025-2026 很少过线）
            h_nc = nocap["ctx"]["hist_fb"]
            h5y = h_nc[(h_nc["d2_dt"] >= u.CANON_5Y_START) & (h_nc["d2_dt"] <= u.DATA_END_DT)]
            gt60_all = h5y[h5y["close"] > 60.0]
            gt60_2526 = gt60_all[gt60_all["d2_dt"] >= "2025-01-01"]
            print("\n--- 全市场主板非一字首板 close > 60 漏斗拆解 ---")
            for lbl, sub in [("全5年(2021-11~2026-11)", gt60_all), ("2025-2026", gt60_2526)]:
                m_ok = sub["mcap"].between(18.0, 220.0)
                g_ok = sub["gate_no_price"]
                bo_ok = sub["is_buyable_open"] & (~sub["nuclear_halt"]) & (~sub["promo_freeze"])
                v19_ok = nocap["ctx"]["mask_v19"][sub.index]
                print(
                    f"  {lbl}: 主板首板>60元={len(sub)} | mcap<=220={int(m_ok.sum())} (被mcap>220拦:{int((sub['mcap']>220).sum())}) | "
                    f"过其他gate={int(g_ok.sum())} | 次日可买不核冻={int(bo_ok.sum())} | 过V19全套={int(v19_ok.sum())}"
                )

            if nocap["forensics_1s"]["five_min_missing_days"]:
                print("  [5m Missing Days in NoCap 1S]:", nocap["forensics_1s"]["five_min_missing_days"])

    with open(f"{ABL_DIR}/ablation_summary.json", "w", encoding="utf-8") as f:
        json.dump(all_summaries, f, ensure_ascii=False, indent=2)
    print(f"\n[Done] elapsed={time.time()-t0:.1f}s, saved to {ABL_DIR}")


if __name__ == "__main__":
    main()
