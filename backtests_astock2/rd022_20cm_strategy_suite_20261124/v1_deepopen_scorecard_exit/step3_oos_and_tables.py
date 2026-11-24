#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 3: Locked V1.0 Scorecard & 4-Branch Dynamic Exit Tree — Full Blind OOS & Table Export.
Outputs:
  - scorecard_v1.csv
  - ablation_v1.csv
  - score_buckets_v1.csv
  - exit_opt_v1.csv
  - all_scored_signals_v1.csv
  - ledger_v1_A.csv (1-slot A-tier >= 78)
  - ledger_v1_S.csv (1-slot S-tier >= 88)
"""
import json, pickle, sys, time
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True

PART2_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
sys.path.insert(0, OUT_DIR)
sys.path.insert(0, PART2_DIR)

from backtest_utils import calc_d15_suite, _sim_k_slots, bench_return, ew20_bench_return
from step2_is_exit_tree_opt import compute_scorecard_v1, sim_exit_tree, make_36_configs

FINAL_EXIT_CFG = {
    "zt_imm": True,
    "b2_body": 0.06,
    "b2_clv": 0.65,
    "b2_mode": "d3_hold",
    "b2_tp": 0.12,
    "b3_tp_mode": "adaptive",
    "b3_adapt_k": 1.5,
    "b4_body": -0.05,
    "b4_mode": "d2_close",
    "risk_mode": "inst_dt",
}

FACTOR_META = [
    ("F01_lock_top10_ge40", "D1_筹码流通", "前十大自由流通锁仓 >= 40%", "+6", "大股东/锁仓高则次日深开抛压小"),
    ("F02_rfmcap_tier", "D1_筹码流通", "真实自由流值 <= 20亿 (+4) / > 40亿 (-4)", "+4 / -4", "真实流通盘小弹性足，超40亿反抽受阻"),
    ("F03_open_gap_zone", "D2_量价微观", "T+1开盘甜区[-6.5%,-3.0%](+5) / 核按钮<-8.0%(-12)", "+5 / -12", "温和深水错杀反抽强，跌破-8%多为真崩盘"),
    ("F04_bias20_le12", "D2_量价微观", "20日均线乖离 bias20 <= 12%", "+8", "低位刚起爆安全性高，防高位接盘"),
    ("F05_dist3d30_ge10", "D2_量价微观", "距3日30%严重异动余量 >= 10%", "+4", "反抽空间充裕不卡监管异动红线"),
    ("F06_zt60d_ge2", "D2_量价微观", "近60日涨停次数 >= 2 (含当日)", "+5", "具活跃股性记忆，游资识别度高"),
    ("F07_zt_early_le945_pen", "D2_量价微观", "T0封板时间 <= 09:45 却次日深低开", "-5", "早盘秒板次日却低开属该强不强诱多陷阱"),
    ("F08_seal_ratio_ge10_pen", "D2_量价微观", "T0封单金额/成交额 >= 10% 却次日深低开", "-6", "大封单假一致次日却低开说明隔夜资金撤退"),
    ("F09_inst_net_pos", "D3_资金席位", "T0龙虎榜机构专用净买入 > 0", "+7", "机构真金白银背书，次日错杀有承接"),
    ("F10_quant_noinst_pen", "D3_资金席位", "T0量化席位买且无机构净买", "-6", "纯量化铺单次日竞价无底线砸盘出货"),
    ("F11_surf_yz_pen", "D3_资金席位", "T0一日游席位(且拉萨非净买)介入", "-5", "超短一日游席位次日早盘无脑兑现"),
    ("F12_mkt10_zt_gt70", "D4_题材情绪", "T0全市场10cm涨停家数 > 70", "+8", "主板高风险偏好资金外溢至错杀20cm首板"),
    ("F13_kpl_overheat_pen", "D4_题材情绪", "开盘啦主概念Elo >= 112 或同题材20cm涨停 >= 3", "-6", "题材过热拥挤后次日深低开属掉队后排"),
    ("F14_peers20_nuke_pen", "D4_题材情绪", "T+1 09:25 昨日20cm首板同伴开盘均值 < -1.5%", "-8", "同批20cm首板集体核按钮属系统性冰点"),
    ("F15_yizi20_siphon_pen", "D4_题材情绪", "T+1 09:25 全场出现 >= 1只20cm一字涨停", "-5", "20cm出现一字新龙虹吸流动性"),
    ("F16_xq_pre_ge1_pen", "D5_社区公告", "T0~T+1 09:00前雪球新增讨论 >= 1帖", "-12", "暗牌破坏散户提前一致预期导致低开砸盘"),
    ("F17_earn_pos_sellnews_pen", "D5_社区公告", "近3日(<09:00)发布业绩预增/扭亏/快报公告", "-10", "利好兑现叠加首板次日低开典型见光死"),
    ("F18_monday_pen", "D6_日历效应", "T+1买入日为周一", "-10", "周末消息消化后周一深开情绪承压胜率骤降"),
]


def calc_cap10m_nav(rets: np.ndarray, init_w: float = 100.0, cap_w: float = 1000.0) -> float:
    cap = init_w
    for r in rets:
        cap += min(cap, cap_w) * float(r)
    return round(cap / init_w, 3)


def eval_full_suite(tr: pd.DataFrame, sh300: dict, ew20: dict) -> dict:
    m = calc_d15_suite(tr, sh300, ew20)
    # Attach 10M cap nav for FULL/IS/OOS/2026
    for wname, sdt, edt in [("FULL", "2021-01-04", "2026-11-23"), ("IS", "2021-01-04", "2024-08-31"), ("OOS", "2024-09-01", "2026-11-23"), ("2026", "2026-01-01", "2026-11-23")]:
        sub = tr[(tr["buy_date"] >= sdt) & (tr["buy_date"] <= edt)] if not tr.empty else pd.DataFrame()
        t1, _, _ = _sim_k_slots(sub, 1)
        r1 = t1["net_ret_eval"].to_numpy(dtype=float) if not t1.empty else np.array([], dtype=float)
        m[wname]["cap10m_1s"] = calc_cap10m_nav(r1) if len(r1) else 1.0
        m[wname]["mean_1s"] = round(float(r1.mean() * 100.0), 2) if len(r1) else 0.0
    return m


def main():
    t0 = time.time()
    df = pd.read_parquet(f"{OUT_DIR}/p1_clean_candidates.parquet")
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, ew20 = aux["sh300"], aux["ew20_daily"]

    # Apply locked hard skeleton
    skel_mask = df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)
    pool = df[skel_mask].copy().reset_index(drop=True)
    sc, fm = compute_scorecard_v1(pool)
    pool["score"] = sc.values

    # Run Final Exit Tree on ALL skeleton candidates (so all_scored_signals_v1.csv has full outcomes!)
    tr_all = sim_exit_tree(pool, FINAL_EXIT_CFG).drop(columns=["score"])
    # Merge score & factor details onto tr_all (1-to-1 by sig_date + c6)
    pool_meta = pool[["dt", "c6", "score", "f1_body", "f1_clv", "f1_zt", "f1_is_dt"]].rename(columns={"dt": "sig_date"})
    all_sig = tr_all.merge(pool_meta, on=["sig_date", "c6"], how="left")
    pool_fm = pd.concat([pool[["dt", "c6"]].rename(columns={"dt": "sig_date"}), fm], axis=1)
    all_sig = all_sig.merge(pool_fm, on=["sig_date", "c6"], how="left")

    # Attach D1 branch label
    def _branch(r):
        if r.f1_zt:
            return "B1_D1_ZT"
        if r.f1_body <= -0.05 or r.f1_is_dt:
            return "B4_D1_DeepYin"
        if r.f1_body >= 0.06 and r.f1_clv >= 0.65:
            return "B2_D1_StrongYang"
        return "B3_D1_Mild"
    all_sig["d1_branch"] = [_branch(r) for r in all_sig.itertuples(index=False)]
    all_sig.to_csv(f"{OUT_DIR}/all_scored_signals_v1.csv", index=False, encoding="utf-8-sig")

    # Export A-tier (>=78) & S-tier (>=88) 1-slot executed ledgers (plus raw metrics)
    tr_A_raw = all_sig[all_sig["score"] >= 78.0].copy()
    tr_S_raw = all_sig[all_sig["score"] >= 88.0].copy()
    slot_A, _, _ = _sim_k_slots(tr_A_raw, 1)
    slot_S, _, _ = _sim_k_slots(tr_S_raw, 1)
    slot_A["buy_hhmm"] = 925
    slot_A["exit_hhmm"] = np.where(slot_A["exit_reason"].str.contains("open|gap|tp"), 1030, 1500)
    slot_S["buy_hhmm"] = 925
    slot_S["exit_hhmm"] = np.where(slot_S["exit_reason"].str.contains("open|gap|tp"), 1030, 1500)
    slot_A.to_csv(f"{OUT_DIR}/ledger_v1_A.csv", index=False, encoding="utf-8-sig")
    slot_S.to_csv(f"{OUT_DIR}/ledger_v1_S.csv", index=False, encoding="utf-8-sig")

    # 1. Export scorecard_v1.csv (IS & OOS standalone hit stats)
    sc_rows = []
    for fid, dim, desc, w_str, phys in FACTOR_META:
        hit_m = fm[fid].to_numpy() != 0
        sub_is = all_sig[(all_sig["buy_date"] <= "2024-08-31")]
        sub_oos = all_sig[(all_sig["buy_date"] >= "2024-09-01")]
        # Align fm mask with all_sig (note len(all_sig) == len(pool) check!)
        m_is = (all_sig["buy_date"] <= "2024-08-31").to_numpy() & (all_sig[fid].to_numpy() != 0)
        m_oos = (all_sig["buy_date"] >= "2024-09-01").to_numpy() & (all_sig[fid].to_numpy() != 0)
        r_is = all_sig.loc[m_is, "net_ret"].to_numpy()
        r_oos = all_sig.loc[m_oos, "net_ret"].to_numpy()
        b_is = sub_is["net_ret"].mean() * 100.0
        b_oos = sub_oos["net_ret"].mean() * 100.0
        sc_rows.append({
            "factor_id": fid, "dimension": dim, "definition": desc, "weight": w_str, "physics": phys,
            "IS_hits": int(len(r_is)), "IS_WR": round(float((r_is > 0).mean() * 100), 2) if len(r_is) else 0.0,
            "IS_mean_pct": round(float(r_is.mean() * 100), 2) if len(r_is) else 0.0,
            "IS_delta_pct": round(float(r_is.mean() * 100 - b_is), 2) if len(r_is) else 0.0,
            "OOS_hits": int(len(r_oos)), "OOS_WR": round(float((r_oos > 0).mean() * 100), 2) if len(r_oos) else 0.0,
            "OOS_mean_pct": round(float(r_oos.mean() * 100), 2) if len(r_oos) else 0.0,
            "OOS_delta_pct": round(float(r_oos.mean() * 100 - b_oos), 2) if len(r_oos) else 0.0,
        })
    pd.DataFrame(sc_rows).to_csv(f"{OUT_DIR}/scorecard_v1.csv", index=False, encoding="utf-8-sig")

    # 2. Export ablation_v1.csv (LOO at A >= 78 across IS & OOS & FULL using Final Exit Tree AND Pure T2)
    base_A_m = eval_full_suite(tr_A_raw, sh300, ew20)
    abl_rows = []
    for fid, dim, desc, w_str, _ in FACTOR_META:
        sc_drop = all_sig["score"] - all_sig[fid]
        tr_d = all_sig[sc_drop >= 78.0]
        m_d = eval_full_suite(tr_d, sh300, ew20)
        abl_rows.append({
            "factor_id": fid, "dimension": dim, "weight": w_str,
            "IS_base_1s": base_A_m["IS"]["nav_1s"], "IS_drop_1s": m_d["IS"]["nav_1s"],
            "IS_keep_d1s": round(base_A_m["IS"]["nav_1s"] - m_d["IS"]["nav_1s"], 3),
            "IS_keep_dEW": round(base_A_m["IS"]["ew_nav"] - m_d["IS"]["ew_nav"], 3),
            "IS_keep_dWR": round(base_A_m["IS"]["wr_1s"] - m_d["IS"]["wr_1s"], 2),
            "OOS_base_1s": base_A_m["OOS"]["nav_1s"], "OOS_drop_1s": m_d["OOS"]["nav_1s"],
            "OOS_keep_d1s": round(base_A_m["OOS"]["nav_1s"] - m_d["OOS"]["nav_1s"], 3),
            "OOS_keep_dEW": round(base_A_m["OOS"]["ew_nav"] - m_d["OOS"]["ew_nav"], 3),
            "OOS_keep_dWR": round(base_A_m["OOS"]["wr_1s"] - m_d["OOS"]["wr_1s"], 2),
            "FULL_base_1s": base_A_m["FULL"]["nav_1s"], "FULL_drop_1s": m_d["FULL"]["nav_1s"],
            "FULL_keep_d1s": round(base_A_m["FULL"]["nav_1s"] - m_d["FULL"]["nav_1s"], 3),
        })
    pd.DataFrame(abl_rows).to_csv(f"{OUT_DIR}/ablation_v1.csv", index=False, encoding="utf-8-sig")

    # 3. Export score_buckets_v1.csv (6 buckets aligned to A=78 & S=88 across IS & OOS & FULL)
    buckets = [("<65", -999, 64.9), ("65~71", 65, 71.9), ("72~77", 72, 77.9), ("78~82", 78, 82.9), ("83~87", 83, 87.9), (">=88 (S)", 88, 999)]
    b_rows = []
    for bl, lo, hi in buckets:
        sub_b = all_sig[all_sig["score"].between(lo, hi)]
        mb = eval_full_suite(sub_b, sh300, ew20)
        for wn in ("IS", "OOS", "FULL"):
            mw = mb[wn]
            b_rows.append({
                "bucket": bl, "window": wn, "raw_n": mw.get("raw_n", 0), "n_1s": mw.get("n_1s", 0),
                "wr_1s": mw.get("wr_1s", 0.0), "mean_1s": mw.get("mean_1s", 0.0), "po_1s": mw.get("po_1s", 0.0),
                "nav_1s": mw.get("nav_1s", 1.0), "ew_nav": mw.get("ew_nav", 1.0), "mdd_1s": mw.get("mdd_1s", 0.0),
            })
    pd.DataFrame(b_rows).to_csv(f"{OUT_DIR}/score_buckets_v1.csv", index=False, encoding="utf-8-sig")

    # 4. Export exit_opt_v1.csv (ALL 38 variants + V1_Final_Tree across IS, OOS, 2026, FULL on A-tier >= 78)
    cfgs = make_36_configs() + [("39_V1_FINAL_TREE", FINAL_EXIT_CFG)]
    pool_A = pool[pool["score"] >= 78.0].copy()
    ex_rows = []
    print("\n=== [BLIND OOS CHECK] TOP EXIT VARIANTS ON A-TIER (>=78) ===")
    for nm, cfg in cfgs:
        tr_e = sim_exit_tree(pool_A, cfg)
        me = eval_full_suite(tr_e, sh300, ew20)
        ex_rows.append({
            "variant": nm,
            "IS_1sN": me["IS"]["n_1s"], "IS_WR": me["IS"]["wr_1s"], "IS_PO": me["IS"]["po_1s"],
            "IS_1s": me["IS"]["nav_1s"], "IS_EW": me["IS"]["ew_nav"], "IS_MDD": me["IS"]["mdd_1s"],
            "OOS_1sN": me["OOS"]["n_1s"], "OOS_WR": me["OOS"]["wr_1s"], "OOS_PO": me["OOS"]["po_1s"],
            "OOS_1s": me["OOS"]["nav_1s"], "OOS_EW": me["OOS"]["ew_nav"], "OOS_MDD": me["OOS"]["mdd_1s"],
            "Y26_1s": me["2026"]["nav_1s"], "Y26_EW": me["2026"]["ew_nav"],
            "FULL_1s": me["FULL"]["nav_1s"], "FULL_EW": me["FULL"]["ew_nav"], "FULL_3s": me["FULL"]["nav_3s"],
            "FULL_cap10m": me["FULL"]["cap10m_1s"], "FULL_ex5": me["FULL"]["ex5_1s"], "FULL_fee50": me["FULL"]["fee50_1s"],
            "col_sl_cnt": int(tr_e["exit_reason"].str.contains("collision_sl").sum()),
        })
        if nm in ("01_Pure_T2_Close", "08_B3_TP08", "09_B3_TP10", "12_B3_AdaptTP_1.5x", "15_B3_TP10_SL07", "19_B2_D3Hold_TP12", "23_B4_OpenCut_All", "26_B4_KeepD2Close", "35_TreeA_TP10_RiskInstDT", "37_TreeC_Adapt_Hi08_RiskInst", "39_V1_FINAL_TREE"):
            print(f"  {nm:30s} | IS: 1s={me['IS']['nav_1s']:6.2f}x EW={me['IS']['ew_nav']:6.2f}x WR={me['IS']['wr_1s']:5.1f}% | "
                  f"OOS: 1s={me['OOS']['nav_1s']:5.2f}x EW={me['OOS']['ew_nav']:5.2f}x WR={me['OOS']['wr_1s']:5.1f}% MDD={me['OOS']['mdd_1s']:4.1f}% | 26: 1s={me['2026']['nav_1s']:4.2f}x | FULL: 1s={me['FULL']['nav_1s']:6.2f}x cap10m={me['FULL']['cap10m_1s']:5.2f}x")
    pd.DataFrame(ex_rows).to_csv(f"{OUT_DIR}/exit_opt_v1.csv", index=False, encoding="utf-8-sig")

    # Print Buckets (IS & OOS) and Branch breakdown + A-tier vs S-tier vs Pure_T2
    print("\n=== [SCORE BUCKETS: IS vs BLIND OOS] ===")
    print(pd.DataFrame(b_rows)[pd.DataFrame(b_rows)["window"].isin(["IS", "OOS"])].to_string(index=False))

    print("\n=== [A-TIER >=78 & S-TIER >=88 FULL SUMMARY] ===")
    for lbl, tr_x in [("A_tier_FinalTree(>=78)", tr_A_raw), ("S_tier_FinalTree(>=88)", tr_S_raw), ("A_tier_PureT2(>=78)", sim_exit_tree(pool_A, {"b3_tp_mode": "none"}))]:
        mx = eval_full_suite(tr_x, sh300, ew20)
        print(f"\n  [{lbl}]")
        for wn in ("FULL", "IS", "OOS", "2026"):
            mw = mx[wn]
            print(f"    {wn:4s} | raw={mw['raw_n']:3d} 1sN={mw['n_1s']:3d} WR={mw['wr_1s']:5.1f}% PO={mw['po_1s']:4.2f} mn={mw['mean_1s']:+5.2f}% "
                  f"1s={mw['nav_1s']:7.2f}x cap10m={mw['cap10m_1s']:6.2f}x 3s={mw['nav_3s']:6.2f}x EW={mw['ew_nav']:7.2f}x MDD={mw['mdd_1s']:5.1f}% "
                  f"ex5={mw['ex5_1s']:6.2f}x f50={mw['fee50_1s']:6.2f}x exHS={mw['ex_hs300_1s']:+8.1f}pp exEW20={mw['ex_ew20_1s']:+8.1f}pp")

    print("\n=== [D1 BRANCH BREAKDOWN ON A-TIER >=78] ===")
    for br, grp in tr_A_raw.assign(d1_branch=all_sig.loc[all_sig["score"] >= 78.0, "d1_branch"]).groupby("d1_branch"):
        for wn, sdt, edt in [("IS", "2021-01-04", "2024-08-31"), ("OOS", "2024-09-01", "2026-11-23")]:
            g2 = grp[(grp["buy_date"] >= sdt) & (grp["buy_date"] <= edt)]
            if g2.empty: continue
            r = g2["net_ret"].to_numpy()
            print(f"  {br:16s} {wn:3s}: N={len(r):3d} WR={(r>0).mean()*100:5.1f}% mean={r.mean()*100:+5.2f}% reasons={g2['exit_reason'].value_counts().to_dict()}")

    print(f"\n[DONE] Step 3 in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
