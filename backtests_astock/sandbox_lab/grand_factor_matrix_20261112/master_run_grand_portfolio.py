#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Master Synthesis & Multi-Strategy Combined Account Runner (Zero-Lookahead PIT, D15 4-Pillar)."""
import os, sys, json, pickle, sqlite3, datetime
from collections import defaultdict
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

import re
from d15_eval_helper import evaluate_d15_full, csi300_ret, _sim_single_slot
from grand_portfolio_combiner import load_v17_df, combine_and_evaluate, eval_4bucket_equal_split
from agent2_3to4_sweep import precompute_trade_engines

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
REAL_MINE_PAT = re.compile(r"(?:减持|立案|问询函|警示函|预亏|退市|涉嫌违法|违规|冻结|留置|调查)")


def build_true_bad_flag(df: pd.DataFrame) -> np.ndarray:
    codes = set(df["code"].astype(str).str.zfill(6).unique())
    by_c6 = defaultdict(list)
    conn = sqlite3.connect(f"file:{BASE}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc, pub_dt, title in conn.execute(
        "SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst >= '2021-12-20'"
    ):
        c6 = str(sc)[:6].zfill(6)
        if c6 in codes and pub_dt and REAL_MINE_PAT.search(str(title or "")):
            by_c6[c6].append(str(pub_dt))
    conn.close()
    out = np.zeros(len(df), dtype=bool)
    for i, (c6, bd) in enumerate(zip(df["code"].astype(str).str.zfill(6), df["buy_date"].astype(str))):
        arr = by_c6.get(c6)
        if not arr:
            continue
        hi_cut = f"{bd} 09:25:00"
        lo_cut = (datetime.date.fromisoformat(bd) - datetime.timedelta(days=8)).isoformat()
        out[i] = any(lo_cut <= x < hi_cut for x in arr)
    return out


def build_all_strategy_ledgers():
    with open(f"{CUR_DIR}/code_bars_5y.pkl", "rb") as f:
        code_bars = pickle.load(f)["code_bars"]

    # 1. Live 1-to-2 (96 trades, 249.04x)
    s_1to2 = load_v17_df()

    # 2. High-Dragon 1A (5-Board Feishu Base vs Zero-Lookahead Rolling 4-Trade Regime Upgrade)
    c1a = pd.read_parquet(f"{CUR_DIR}/verified_1a_5ban_cands.parquet").copy()
    c1a["code"] = c1a["code"].astype(str).str.zfill(6)
    c1a["true_bad"] = build_true_bad_flag(c1a)
    c1a["buy_at_open"] = True
    c1a["priority_score"] = c1a["lock_top10"].fillna(0.0) + c1a["s_prior"].fillna(0.0) * 0.1
    f1a_base = c1a[(c1a["open_pct"] <= 0.055) & (c1a["lock_top10"] >= 50.0)].copy()
    f1a_base["exit_date"] = f1a_base["ed_d4_93"]
    f1a_base["net_ret"] = f1a_base["ret_d4_93"]
    f1a_base["hold_bars"] = f1a_base["hb_d4_93"]
    f1a_base["exit_at_open"] = f1a_base["eo_d4_93"]

    # Strict PIT Rolling 4-Trade Regime on 1A (only look at already-exited trades with exit_date < buy_date)
    all_5b = f1a_base.sort_values(["buy_date", "priority_score"], ascending=[True, False]).reset_index(drop=True)
    closed_pool = []
    keep_rows = []
    for r in all_5b.itertuples(index=False):
        past = [x for x in closed_pool if x[0] < r.buy_date]
        closed_pool.append((r.exit_date, float(r.net_ret)))
        if len(past) < 4:
            continue
        last4 = [x[1] for x in past[-4:]]
        if (sum(v > 0 for v in last4) / 4.0 >= 0.60) and (np.mean(last4) >= 0.04):
            if (r.prev_break_dt_rate_10d <= 0.30) and (not (-0.035 <= r.open_pct <= 0.010)) and (r.lhasa_seats_prev <= 1) and (not r.true_bad):
                keep_rows.append(r._asdict())
    s_1a_regime = pd.DataFrame(keep_rows)

    # 3. High-Dragon 1C (Market Top Dragon 4+ Break-Board True-Yang Rebound)
    c1c = pd.read_parquet(f"{CUR_DIR}/verified_1c_rebound_cands.parquet").copy()
    c1c["code"] = c1c["code"].astype(str).str.zfill(6)
    c1c["true_bad"] = build_true_bad_flag(c1c)
    c1c["buy_at_open"] = True
    c1c["priority_score"] = c1c["prev_streak"].fillna(4) * 10.0 - c1c["d1_to"].fillna(20.0) * 0.1
    m1c_base = (c1c["prev_streak"] >= 4) & (c1c["d1_to"] < 35.0) & (c1c["d2_gap"] <= 0.05)
    s_1c_bal = c1c[m1c_base & (~c1c["true_bad"]) & (~c1c["is_pure_outsider"])].copy()
    s_1c_tight25 = s_1c_bal[s_1c_bal["seal_tightness"] >= 25.0].copy()
    s_1c_lowmdd = s_1c_bal[(s_1c_bal["lhasa_seats_prev"] <= 2) & (s_1c_bal["d1_lhasa"] <= 2)].copy()

    # 4. 3-to-4 (Feishu Base vs Elite Touch7 vs Dual-Track HiCap Touch7)
    c34 = pd.read_parquet(f"{CUR_DIR}/cand_3to4.parquet")
    eng34 = precompute_trade_engines(c34, code_bars)
    m34_b = (~c34["prev_is_yizi"]) & c34["buyable_open"]
    m34_feishu = m34_b & (c34["csrc_zt_cnt"] >= 2) & c34["prev_to"].between(11.0, 25.0) & c34["open_pct"].between(0.04, 0.085)
    m34_hicap = (
        m34_b & c34["prev_to"].between(9.0, 26.0) & c34["open_pct"].between(0.03, 0.085)
        & (~c34["is_event_basket"]) & (~c34["is_dying_pulse"]) & (~c34["is_pure_outsider"]) & (~c34["notice_bad"])
        & (c34["plate_peers_open_avg"] >= -0.005) & (c34["mkt_promo_1to2_5d"] >= 0.13)
        & ((c34["csrc_zt_cnt"] >= 2) | ((c34["csrc_zt_cnt"] == 1) & (c34["s_prior"] >= 65.0) & (c34["rk_theme"] <= 2)))
    )
    s_34_feishu = pd.DataFrame([t for i in np.where(m34_feishu.values)[0] for t in [eng34[("open", "feishu")][i]] if t is not None])
    s_34_feishu["buy_at_open"] = True
    s_34_elite = pd.read_csv(f"{CUR_DIR}/agent2_3to4_best_ledger.csv")
    s_34_elite["code"] = s_34_elite["code"].astype(str).str.zfill(6)
    s_34_elite["buy_at_open"] = False
    s_34_hicap = pd.DataFrame([t for i in np.where(m34_hicap.values)[0] for t in [eng34[("touch7", "feishu")][i]] if t is not None])
    s_34_hicap["buy_at_open"] = False

    # 5. 2-to-3 & Limit-Down Pry
    s_23 = pd.read_csv(f"{CUR_DIR}/agent3_2to3_best_ledger.csv")
    s_23["code"] = s_23["code"].astype(str).str.zfill(6)
    s_pry_elite = pd.read_csv(f"{CUR_DIR}/agent5_pry_best_ledger.csv")
    s_pry_elite["code"] = s_pry_elite["code"].astype(str).str.zfill(6)

    s_34_half = s_34_elite.copy()
    s_34_half["net_ret"] = s_34_half["net_ret"] * 0.5

    return {
        "1to2_V17": s_1to2, "1A_feishu_base": f1a_base, "1A_regime": s_1a_regime,
        "1C_bal63": s_1c_bal, "1C_tight51": s_1c_tight25, "1C_lowmdd48": s_1c_lowmdd,
        "3to4_feishu_base": s_34_feishu, "3to4_elite57": s_34_elite, "3to4_elite_half": s_34_half, "3to4_hicap92": s_34_hicap,
        "2to3_champ": s_23, "pry_elite21": s_pry_elite,
    }


if __name__ == "__main__":
    dfs = build_all_strategy_ledgers()
    r22 = csi300_ret("2022-01-04", "2022-12-31")
    r23 = csi300_ret("2023-01-01", "2023-12-31")
    r24 = csi300_ret("2024-01-01", "2024-12-31")
    r26 = csi300_ret("2026-01-01", "2026-11-10")
    ex25_bench = float((1 + r22) * (1 + r23) * (1 + r24) * (1 + r26) - 1.0)

    indiv = {k: evaluate_d15_full(v) for k, v in dfs.items() if k != "3to4_elite_half"}
    combos = {
        "C0_LowMDD_Steady": combine_and_evaluate(dfs, ["1to2_V17", "1C_tight51", "1A_regime", "pry_elite21"]),
        "C1_Balanced_Half3to4": combine_and_evaluate(dfs, ["1to2_V17", "1C_tight51", "3to4_elite_half", "1A_regime", "pry_elite21"]),
        "C2_Full_Elite_Rotation": combine_and_evaluate(dfs, ["1to2_V17", "1C_tight51", "3to4_elite57", "1A_regime", "pry_elite21"]),
        "C3_HiCap_Expanded": combine_and_evaluate(dfs, ["1to2_V17", "1C_bal63", "3to4_hicap92", "1A_regime", "pry_elite21"]),
        "C4_HighDragon_DualLeg": combine_and_evaluate(dfs, ["1C_tight51", "1A_regime"]),
    }
    b4_new = eval_4bucket_equal_split([dfs["1to2_V17"], dfs["3to4_elite57"], pd.concat([dfs["1C_tight51"], dfs["1A_regime"]], ignore_index=True), dfs["pry_elite21"]])
    b4_old = eval_4bucket_equal_split([dfs["1to2_V17"], dfs["3to4_feishu_base"], dfs["1A_feishu_base"], dfs["pry_elite21"]])
    out = {"ex2025_csi300_compounded_pct": round(ex25_bench * 100, 2), "individual": indiv, "combined_rotations": combos, "bucket4_upgraded": b4_new}
    with open(f"{CUR_DIR}/grand_portfolio_synthesis_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    for cname, order in [("C0_LowMDD_Steady", ["1to2_V17", "1C_tight51", "1A_regime", "pry_elite21"]),
                         ("C1_Balanced_Half3to4", ["1to2_V17", "1C_tight51", "3to4_elite_half", "1A_regime", "pry_elite21"]),
                         ("C2_Full_Elite_Rotation", ["1to2_V17", "1C_tight51", "3to4_elite57", "1A_regime", "pry_elite21"])]:
        parts = []
        for rk, sn in enumerate(order):
            t = dfs[sn][["code", "name", "buy_date", "exit_date", "net_ret", "buy_at_open", "exit_at_open", "hold_bars", "priority_score"]].copy()
            t["strategy"] = sn
            t["priority_score"] = (len(order) - rk) * 10000.0 + np.clip(t["priority_score"].fillna(0.0), -999, 999)
            parts.append(t)
        m = pd.concat(parts, ignore_index=True).sort_values(["buy_date", "priority_score"], ascending=[True, False]).drop_duplicates(["buy_date", "code"])
        taken, _, _, _ = _sim_single_slot(m)
        pd.DataFrame([x._asdict() for x in taken]).to_csv(f"{CUR_DIR}/grand_combined_{cname}_ledger.csv", index=False, encoding="utf-8-sig")
    print("DONE! Ex-2025 CSI300 compounded:", round(ex25_bench * 100, 2), "%")
    for k, m in list(indiv.items()) + list(combos.items()):
        f5, ex, r3, j6 = m["full_5y"], m["ex2025_4y"], m["recent_3y"], m["since_jul2026"]
        h2 = m["half2_5y"]
        print(f"{k:24s} | 5Y N={f5['single_n']:3d} Hold={f5['hold_days']:3d}d WR={f5['wr']:5.1f}% PO={f5['payoff']:4.2f} S_NAV={f5['single_nav']:8.2f}x Eq={f5['eq_nav']:7.2f}x Trim5={f5['trimmed5_nav']:6.2f}x MDD={f5['single_mdd_pct']:5.1f}% | Ex25={ex['single_nav']:6.2f}x | 3Y={r3['single_nav']:6.2f}x({r3['wr']:4.1f}%) | Jul26 N={j6['single_n']:2d} WR={j6['wr']:5.1f}% NAV={j6['single_nav']:5.2f}x(MDD={j6['single_mdd_pct']:4.1f}%)")
    print("4-Bucket Upgraded:", b4_new)
