#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
w2_4to5_v20_scorecard.py — 《四进五 V2.0》纯整数打分卡锻造、执行矩阵正面对决与 5 折盲测大考
遵守 D12（零 yfinance）、D15（单仓+按日等权+三期+沪深300净超额+去Top3）、SQLite mode=ro。
"""
import os
import sys
import json
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
AST2_DIR = f"{ROOT}/sim-portfolio/backtests_astock2"
P3_DIR = f"{AST2_DIR}/p3_deep_100"
if P3_DIR not in sys.path:
    sys.path.insert(0, P3_DIR)

from common_eval_harness import eval_factor_slice, CSI_BENCH

ENRICHED_MASTER_PATH = f"{P3_DIR}/w2_4to5_enriched_master.parquet"
OUT_LEDGER_PATH = f"{P3_DIR}/w2_4to5_v20_ledger.csv"
OUT_AUDIT_PATH = f"{P3_DIR}/w2_4to5_v20_audit.json"

RET_COL = "ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"
EX_COL = "exdt_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"


def score_single_4to5_row(r: dict) -> dict:
    """
    《四进五 V2.0》纯整数打分卡（100 分起评，结构透明可解释）
    严格 09:25 PIT，前置硬门直接否决 (-999)；正负分严格对应物理第一性原理与双期同向边际收益。
    """
    # 1. 硬前提门（09:25 PIT）
    if not (r.get("buyable_open") == True):
        return {"score": -999, "gate_status": "fail_not_buyable", "breakdown": {}}
    if r.get("f_tox_90d", False) or (r.get("has_tox_notice", 0) > 0):
        return {"score": -999, "gate_status": "fail_tox_notice", "breakdown": {}}
    if r.get("f_s_reg_10d", False) or (r.get("has_stock_reg", 0) > 0):
        return {"score": -999, "gate_status": "fail_stock_reg", "breakdown": {}}
    if float(r.get("tighter_headroom_pit", 0.0)) < 0.12:
        return {"score": -999, "gate_status": "fail_headroom_lt12", "breakdown": {}}
    if r.get("d4_blown_pm_5m", False) or r.get("d4_blown_pm_proxy", False):
        return {"score": -999, "gate_status": "fail_d4_blown_pm", "breakdown": {}}
    op_pct = float(r.get("open_pct", 0.0))
    if op_pct < -0.010 or op_pct > 0.085:
        return {"score": -999, "gate_status": "fail_open_out_of_bounds", "breakdown": {}}

    score = 100
    bd = {}

    # 2. 筹码轻盈锁仓王牌 F49
    lock_top10 = float(r.get("lock_top10", 0.0))
    real_mcap = float(r.get("real_free_mcap", 0.0))
    f49_score = 0
    if (lock_top10 >= 50.0) and (12.0 <= real_mcap <= 35.0):
        f49_score = 8
    elif (lock_top10 >= 45.0) or (real_mcap >= 45.0):
        f49_score = 3
    elif (lock_top10 < 45.0) and (real_mcap < 45.0):
        f49_score = -8
    score += f49_score
    bd["f49_chip"] = f49_score

    # 3. 双严重异动两板安全垫 F58
    hr_pit = float(r.get("tighter_headroom_pit", 0.0))
    f58_score = 0
    if hr_pit >= 0.25:
        f58_score = 6
    elif hr_pit >= 0.22:
        f58_score = 4
    score += f58_score
    bd["f58_headroom"] = f58_score

    # 4. 身位周期与卡位
    max_b = int(r.get("mkt_max_board_prev", 0))
    status_score = 0
    if max_b == 4:
        status_score = 5
    elif max_b == 5:
        status_score = 2
    elif max_b >= 6:
        status_score = -5
    score += status_score
    bd["status_lead"] = status_score

    # 5. 四板竞争格局
    rival_score = 0
    if int(r.get("is_sole_4b", 0)) == 1:
        rival_score += 6
    if int(r.get("is_top1_4b_open", 0)) == 1:
        rival_score += 3
    if (int(r.get("b4_rival_cnt", 0)) >= 2) or (int(r.get("is_top1_4b_open", 0)) == 0):
        rival_score -= 5
    score += rival_score
    bd["rival_open"] = rival_score

    # 6. 左端基因
    left_score = 0
    d4_s34 = float(r.get("d4_v34_score", -999))
    if (82.0 <= d4_s34 <= 89.0) and (int(r.get("is_sole_4b", 0)) == 1):
        left_score += 5
    if bool(r.get("is_held_3to4", False)):
        left_score += 4
    d4_op = float(r.get("d4_open_pct", 0.0))
    d4_buyable = bool(r.get("d4_buyable_open", True))
    d3_yizi = bool(r.get("d3_prev_is_yizi", False))
    if ((d4_op > 0.092) or (not d4_buyable) or d3_yizi) and (0.020 <= op_pct <= 0.060):
        left_score += 3
    obc = int(r.get("open_board_count", 0))
    d3_obc = int(r.get("d3_open_board_count", 0))
    to_r = float(r.get("to_ratio_d4_d3", 1.0))
    if (obc >= 1) and (d3_obc >= 1) and (0.70 <= to_r <= 1.35):
        left_score += 3
    score += left_score
    bd["left_gene"] = left_score

    # 7. 席位博弈
    lhb_score = 0
    if int(r.get("f_d4_quant_sell", 0)) >= 1:
        lhb_score -= 5
    if int(r.get("f52_d4_inst_sell", 0)) >= 1:
        lhb_score -= 3
    if bool(r.get("f50_d4_top_yz_new_buy", False)):
        lhb_score -= 3
    if int(r.get("f51_d4_lh_cnt", 0)) >= 3:
        lhb_score -= 6
    score += lhb_score
    bd["lhb_seat"] = lhb_score

    # 8. 题材与日历节律
    env_score = 0
    if int(r.get("plate_3b_cnt", 0)) >= 1:
        env_score -= 6
    if float(r.get("px_d4", 0.0)) > 20.0:
        env_score -= 6
    if int(r.get("d4_mkt_nuke_cnt", 0)) >= 1:
        env_score -= 3
    if float(r.get("f47_reb_zt_r10", 0.0)) >= 0.20:
        env_score += 6
    dow = int(r.get("dow", 0))
    is_post_mon = bool(r.get("is_post_holiday_or_mon_pit", False))
    if (dow == 1) or is_post_mon:
        env_score += 6
    month = int(r.get("buy_month", 0))
    if month in (1, 5):
        env_score -= 6
    if dow in (4, 5):
        env_score -= 3
    score += env_score
    bd["theme_calendar"] = env_score

    return {"score": score, "gate_status": "pass", "breakdown": bd}


def run_full_pipeline():
    print("[1/5] 加载全特征宽表...")
    df = pd.read_parquet(ENRICHED_MASTER_PATH)
    print(f"数据行数: {len(df)}, 列数: {len(df.columns)}")

    print("[2/5] 批量打分...")
    scores, statuses, bds = [], [], []
    for r in df.to_dict("records"):
        res = score_single_4to5_row(r)
        scores.append(res["score"])
        statuses.append(res["gate_status"])
        bds.append(res["breakdown"])
    df["v20_score"] = scores
    df["gate_status"] = statuses

    # 拆分打分子项进宽表
    keys = ["f49_chip", "f58_headroom", "status_lead", "rival_open", "left_gene", "lhb_seat", "theme_calendar"]
    for k in keys:
        df[f"score_{k}"] = [b.get(k, 0) for b in bds]

    print("[3/5] 买卖执行矩阵横向对比 (M1 - M4)...")
    matrix_comp = {}
    modes = [
        ("M1_B3_E4", "ret_B3_pm_f59_1030_E4_F61_high_dragon_handoff", "exdt_B3_pm_f59_1030_E4_F61_high_dragon_handoff"),
        ("M2_B5_E4", "ret_B5_3to4_touch65_1130_E4_F61_high_dragon_handoff", "exdt_B5_3to4_touch65_1130_E4_F61_high_dragon_handoff"),
        ("M3_B6_E4", "ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff", "exdt_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"),
        ("M4_B6_E1", "ret_B6_auc_sweet_2_7_E1_3to4_std", "exdt_B6_auc_sweet_2_7_E1_3to4_std"),
    ]
    for m_name, rc, ec in modes:
        sub = df[(df["v20_score"] >= 114) & df[rc].notna()].copy()
        res = eval_factor_slice(sub, ret_col=rc, exit_col=ec, rank_col="v20_score")
        matrix_comp[m_name] = res

    print("[4/5] 导出主推阈值 (Thr 114) 逐笔真实交易台账...")
    sub_114 = df[(df["v20_score"] >= 114) & df[RET_COL].notna()].sort_values(["buy_date", "v20_score"], ascending=[True, False]).copy()
    free_dt = ""
    ledger_rows = []
    for r in sub_114.itertuples():
        bd = str(r.buy_date)[:10]
        if free_dt == "" or bd > free_dt:
            rt = float(getattr(r, RET_COL))
            ed = str(getattr(r, EX_COL))[:10] if pd.notna(getattr(r, EX_COL)) else bd
            c6 = str(r.code).zfill(6)
            bpx = float(getattr(r, "B6_auc_sweet_2_7_px")) if hasattr(r, "B6_auc_sweet_2_7_px") and pd.notna(getattr(r, "B6_auc_sweet_2_7_px")) else float(getattr(r, "open_pct", 0.0))
            ledger_rows.append({
                "buy_date": bd,
                "code": c6,
                "name": str(r.name),
                "buy_mode": "B6_auc_sweet_2_7",
                "buy_px": round(bpx, 2),
                "exit_date": ed,
                "net_ret": round(rt * 100, 2),
                "v20_score": int(r.v20_score),
                "score_f49_chip": int(r.score_f49_chip),
                "score_f58_headroom": int(r.score_f58_headroom),
                "score_status_lead": int(r.score_status_lead),
                "score_rival_open": int(r.score_rival_open),
                "score_left_gene": int(r.score_left_gene),
                "score_lhb_seat": int(r.score_lhb_seat),
                "score_theme_calendar": int(r.score_theme_calendar),
                "is_held_3to4": bool(r.is_held_3to4),
                "f68_main3_empty_slot": bool(r.f68_main3_empty_slot),
            })
            free_dt = max(bd, ed)
    df_ledger = pd.DataFrame(ledger_rows)
    df_ledger.to_csv(OUT_LEDGER_PATH, index=False, encoding="utf-8-sig")
    print(f"已保存台账至: {OUT_LEDGER_PATH}, 笔数: {len(df_ledger)}")

    print("[5/5] 执行铁血防过拟合检验与三大口径全景审计...")
    audit = {
        "execution_matrix_comparison": matrix_comp,
        "three_scopes": {},
        "yearly_breakdown_thr114": {},
        "loyo_5fold_oos": {},
        "plateau_test": {},
        "weight_perturbation_300": {},
        "d15_benchmarks": {
            "5y": -17.84,
            "3y": 12.35,
            "rec": -18.48
        }
    }

    # 三大口径 D15 细化统计
    periods = [
        ("5y_full", "2022-01-01", "2026-11-14", -0.1784),
        ("3y_recent", "2023-11-15", "2026-11-14", 0.1235),
        ("rec_recent", "2026-07-01", "2026-11-14", -0.1848),
    ]
    scope_defs = [
        ("scope1_independent", lambda d: d["v20_score"] >= 114),
        ("scope2_pure_incremental", lambda d: (d["v20_score"] >= 114) & (d["is_held_3to4"] == False)),
        ("scope3_empty_slot", lambda d: (d["v20_score"] >= 114) & (d["f68_main3_empty_slot"] == True)),
    ]

    for s_id, s_fn in scope_defs:
        audit["three_scopes"][s_id] = {}
        sub_s = df[s_fn(df) & df[RET_COL].notna()].sort_values(["buy_date", "v20_score"], ascending=[True, False]).copy()
        free_s = ""
        s_trades = []
        for r in sub_s.itertuples():
            bd = str(r.buy_date)[:10]
            if free_s == "" or bd > free_s:
                rt = float(getattr(r, RET_COL))
                ed = str(getattr(r, EX_COL))[:10] if pd.notna(getattr(r, EX_COL)) else bd
                s_trades.append({"buy_date": bd, "ret": rt})
                free_s = max(bd, ed)
        st_df = pd.DataFrame(s_trades)

        for p_name, d_st, d_ed, b_ret in periods:
            sub_p = st_df[(st_df["buy_date"] >= d_st) & (st_df["buy_date"] <= d_ed)]
            n = len(sub_p)
            rets = sub_p["ret"].values if n > 0 else np.array([])
            wins = rets[rets > 0]
            losses = rets[rets <= 0]
            wr = round(float(len(wins) / n * 100), 1) if n > 0 else 0.0
            po = round(float(wins.mean() / abs(losses.mean())), 2) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (9.99 if len(wins) > 0 else 0.0)
            nav = round(float(np.prod(1.0 + rets)), 3) if n > 0 else 1.0
            cum = np.cumprod(1.0 + rets) if n > 0 else np.array([1.0])
            pk = np.maximum.accumulate(cum)
            mdd = round(float(np.max((pk - cum) / pk) * 100), 1) if len(cum) else 0.0
            ex3 = round(float(np.prod(1.0 + np.sort(rets)[:-3])), 3) if len(rets) > 3 else 1.0
            excess = round(float((nav - 1.0 - b_ret) * 100), 2)

            # 等权
            sub_raw = sub_s[(sub_s["buy_date"] >= d_st) & (sub_s["buy_date"] <= d_ed)]
            eq_d = sub_raw.groupby("buy_date")[RET_COL].mean().sort_index()
            eq_nav = round(float(np.prod(1.0 + eq_d.values)), 3) if len(eq_d) else 1.0
            eq_cum = np.cumprod(1.0 + eq_d.values) if len(eq_d) else np.array([1.0])
            eq_pk = np.maximum.accumulate(eq_cum)
            eq_mdd = round(float(np.max((eq_pk - eq_cum) / eq_pk) * 100), 1) if len(eq_cum) else 0.0
            eq_excess = round(float((eq_nav - 1.0 - b_ret) * 100), 2)

            audit["three_scopes"][s_id][p_name] = {
                "ss_n": n, "ss_wr": wr, "ss_payoff": po, "ss_nav": nav, "ss_mdd": mdd,
                "ss_ex_top3_nav": ex3, "ss_net_excess": excess,
                "eq_n": len(sub_raw), "eq_nav": eq_nav, "eq_mdd": eq_mdd, "eq_net_excess": eq_excess
            }

    # 检验 1: 逐年明细
    for yr in ["2022", "2023", "2024", "2025", "2026"]:
        yr_sub = df_ledger[df_ledger["buy_date"].str.startswith(yr)]
        n = len(yr_sub)
        r_arr = (yr_sub["net_ret"] / 100.0).values
        w = r_arr[r_arr > 0]
        l = r_arr[r_arr <= 0]
        wr = round(float(len(w) / n * 100), 1) if n > 0 else 0.0
        po = round(float(w.mean() / abs(l.mean())), 2) if (len(w) > 0 and len(l) > 0 and l.mean() < 0) else (9.99 if len(w) > 0 else 0.0)
        nav = round(float(np.prod(1.0 + r_arr)), 3) if n > 0 else 1.0
        raw_yr = sub_114[sub_114["buy_date"].str.startswith(yr)]
        eq_d = raw_yr.groupby("buy_date")[RET_COL].mean()
        eq_nav = round(float(np.prod(1.0 + eq_d.values)), 3) if len(eq_d) else 1.0
        audit["yearly_breakdown_thr114"][yr] = {
            "ss_n": n, "raw_n": len(raw_yr), "ss_wr": wr, "ss_payoff": po, "ss_nav": nav, "eq_nav": eq_nav
        }

    # 检验 2: 5-Fold LOYO
    gate_mask = (
        (df["buyable_open"] == True) &
        (df["f_tox_90d"] == False) & (df["has_tox_notice"] == 0) &
        (df["f_s_reg_10d"] == False) & (df["has_stock_reg"] == 0) &
        (df["tighter_headroom_pit"] >= 0.12) &
        (df["d4_blown_pm_5m"] == False) & (df["d4_blown_pm_proxy"] == False) &
        (df["open_pct"] >= -0.010) & (df["open_pct"] <= 0.085) &
        (df[RET_COL].notna())
    )
    df_valid = df[gate_mask].copy().reset_index(drop=True)
    df_valid["year"] = df_valid["buy_date"].str[:4]

    feat_dict = {
        "F49_sweet": lambda d: (d["lock_top10"] >= 50.0) & (d["real_free_mcap"].between(12.0, 35.0)),
        "F49_ok": lambda d: (d["lock_top10"] >= 45.0) | (d["real_free_mcap"] >= 45.0),
        "F49_fail": lambda d: (d["lock_top10"] < 45.0) & (d["real_free_mcap"] < 45.0),
        "F58_hr22": lambda d: d["tighter_headroom_pit"] >= 0.22,
        "F58_hr25": lambda d: d["tighter_headroom_pit"] >= 0.25,
        "mkt_max4": lambda d: d["mkt_max_board_prev"] == 4,
        "mkt_max5": lambda d: d["mkt_max_board_prev"] == 5,
        "mkt_max6": lambda d: d["mkt_max_board_prev"] >= 6,
        "is_sole": lambda d: d["is_sole_4b"] == 1,
        "top1_open": lambda d: d["is_top1_4b_open"] == 1,
        "crowded_not_top1": lambda d: (d["b4_rival_cnt"] >= 2) | (d["is_top1_4b_open"] == 0),
        "f40_sole": lambda d: (d["d4_v34_score"].between(82, 89)) & (d["is_sole_4b"] == 1),
        "f35_held": lambda d: d["is_held_3to4"] == True,
        "f37_rush": lambda d: ((d["d4_open_pct"] > 0.092) | (d["d4_buyable_open"] == False) | (d["d3_prev_is_yizi"] == True)) & (d["open_pct"].between(0.020, 0.060)),
        "f64_conv": lambda d: (d["open_board_count"] >= 1) & (d["d3_open_board_count"] >= 1) & (d["to_ratio_d4_d3"].between(0.70, 1.35)),
        "quant_sell": lambda d: d["f_d4_quant_sell"] >= 1,
        "inst_sell": lambda d: d["f52_d4_inst_sell"] >= 1,
        "top_yz_buy": lambda d: d["f50_d4_top_yz_new_buy"] == True,
        "lhasa_ge3": lambda d: d["f51_d4_lh_cnt"] >= 3,
        "plate_3b": lambda d: d["plate_3b_cnt"] >= 1,
        "px_gt20": lambda d: d["px_d4"] > 20.0,
        "mkt_nuke": lambda d: d["d4_mkt_nuke_cnt"] >= 1,
        "reb_zt20": lambda d: d["f47_reb_zt_r10"] >= 0.20,
        "mon_post_hol": lambda d: (d["dow"] == 1) | (d["is_post_holiday_or_mon_pit"] == True),
        "month_1_5": lambda d: d["buy_month"].isin([1, 5]),
        "thu_fri": lambda d: d["dow"].isin([4, 5]),
    }
    for k, fn in feat_dict.items():
        df_valid[k] = fn(df_valid)

    loyo_folds = []
    all_test_rets = []
    for yr in ["2022", "2023", "2024", "2025", "2026"]:
        tr_sub = df_valid[df_valid["year"] != yr].copy()
        te_sub = df_valid[df_valid["year"] == yr].copy()
        b_r = tr_sub[RET_COL].mean()
        w_map = {}
        for k in feat_dict:
            s_k = tr_sub[tr_sub[k]]
            w_map[k] = int(np.clip(round((s_k[RET_COL].mean() - b_r) * 100), -8, 8)) if len(s_k) >= 4 else 0

        def s_fn(d):
            s = np.zeros(len(d), dtype=int) + 100
            for k, w in w_map.items():
                if w != 0:
                    s += d[k].values.astype(int) * w
            return s

        tr_s = s_fn(tr_sub)
        te_s = s_fn(te_sub)
        thr_tr = float(np.percentile(tr_s, 75))
        te_sub["score"] = te_s
        te_sel = te_sub[te_sub["score"] >= thr_tr].sort_values(["buy_date", "score"], ascending=[True, False]).copy()

        fr = ""
        tr_list = []
        for r in te_sel.itertuples():
            bd = str(r.buy_date)[:10]
            if fr == "" or bd > fr:
                rt = float(getattr(r, RET_COL))
                ed = str(getattr(r, EX_COL))[:10] if pd.notna(getattr(r, EX_COL)) else bd
                tr_list.append(rt)
                all_test_rets.append(rt)
                fr = max(bd, ed)
        n_t = len(tr_list)
        t_arr = np.array(tr_list) if n_t else np.array([])
        nav_t = round(float(np.prod(1.0 + t_arr)), 3) if n_t else 1.0
        wr_t = round(float((t_arr > 0).sum() / n_t * 100), 1) if n_t else 0.0
        loyo_folds.append({
            "test_year": yr, "train_thr": thr_tr, "ss_n": n_t, "ss_wr": wr_t, "ss_nav": nav_t, "pos_return": bool(nav_t > 1.0)
        })

    all_t_arr = np.array(all_test_rets)
    audit["loyo_5fold_oos"] = {
        "folds": loyo_folds,
        "combined_ss_n": len(all_t_arr),
        "combined_ss_wr": round(float((all_t_arr > 0).sum() / len(all_t_arr) * 100), 1),
        "combined_ss_nav": round(float(np.prod(1.0 + all_t_arr)), 3),
        "pos_folds_count": sum(1 for f in loyo_folds if f["pos_return"]),
    }

    # 检验 3: 三阈值高原 (110, 114, 118)
    for t_val in [110, 112, 114, 116, 118]:
        s_pl = df[(df["v20_score"] >= t_val) & df[RET_COL].notna()].copy()
        res_pl = eval_factor_slice(s_pl, ret_col=RET_COL, exit_col=EX_COL, rank_col="v20_score")
        audit["plateau_test"][str(t_val)] = res_pl

    # 检验 4: 300 次扰动
    np.random.seed(42)
    items = [
        ("f49_sweet", 8, (df_valid["lock_top10"] >= 50.0) & (df_valid["real_free_mcap"].between(12.0, 35.0))),
        ("f49_ok", 3, ((df_valid["lock_top10"] >= 45.0) | (df_valid["real_free_mcap"] >= 45.0)) & ~((df_valid["lock_top10"] >= 50.0) & (df_valid["real_free_mcap"].between(12.0, 35.0)))),
        ("f49_fail", -8, (df_valid["lock_top10"] < 45.0) & (df_valid["real_free_mcap"] < 45.0)),
        ("f58_hr25", 6, df_valid["tighter_headroom_pit"] >= 0.25),
        ("f58_hr22", 4, (df_valid["tighter_headroom_pit"] >= 0.22) & (df_valid["tighter_headroom_pit"] < 0.25)),
        ("mkt_max4", 5, df_valid["mkt_max_board_prev"] == 4),
        ("mkt_max5", 2, df_valid["mkt_max_board_prev"] == 5),
        ("mkt_max6", -5, df_valid["mkt_max_board_prev"] >= 6),
        ("is_sole", 6, df_valid["is_sole_4b"] == 1),
        ("top1_open", 3, df_valid["is_top1_4b_open"] == 1),
        ("crowded", -5, (df_valid["b4_rival_cnt"] >= 2) | (df_valid["is_top1_4b_open"] == 0)),
        ("f40_sole", 5, (df_valid["d4_v34_score"].between(82, 89)) & (df_valid["is_sole_4b"] == 1)),
        ("f35_held", 4, df_valid["is_held_3to4"] == True),
        ("f37_rush", 3, ((df_valid["d4_open_pct"] > 0.092) | (~df_valid["d4_buyable_open"]) | df_valid["d3_prev_is_yizi"]) & (df_valid["open_pct"].between(0.020, 0.060))),
        ("f64_conv", 3, (df_valid["open_board_count"] >= 1) & (df_valid["d3_open_board_count"] >= 1) & (df_valid["to_ratio_d4_d3"].between(0.70, 1.35))),
        ("quant_sell", -5, df_valid["f_d4_quant_sell"] >= 1),
        ("inst_sell", -3, df_valid["f52_d4_inst_sell"] >= 1),
        ("top_yz_buy", -3, df_valid["f50_d4_top_yz_new_buy"] == True),
        ("lhasa_ge3", -6, df_valid["f51_d4_lh_cnt"] >= 3),
        ("plate_3b", -6, df_valid["plate_3b_cnt"] >= 1),
        ("px_gt20", -6, df_valid["px_d4"] > 20.0),
        ("mkt_nuke", -3, df_valid["d4_mkt_nuke_cnt"] >= 1),
        ("reb_zt20", 6, df_valid["f47_reb_zt_r10"] >= 0.20),
        ("mon_post_hol", 6, (df_valid["dow"] == 1) | (df_valid["is_post_holiday_or_mon_pit"] == True)),
        ("month_1_5", -6, df_valid["buy_month"].isin([1, 5])),
        ("thu_fri", -3, df_valid["dow"].isin([4, 5])),
    ]
    f_mat = np.column_stack([item[2].values.astype(float) for item in items])
    b_w = np.array([item[1] for item in items], dtype=float)
    b_dates = df_valid["buy_date"].values
    e_dates = df_valid[EX_COL].values
    r_vals = df_valid[RET_COL].values

    p_navs, p_ex3s = [], []
    for _ in range(300):
        noise = np.random.uniform(-0.20, 0.20, size=len(b_w))
        pw = b_w * (1.0 + noise)
        p_scores = 100.0 + f_mat @ pw
        idx_s = np.where(p_scores >= 114.0)[0]
        if len(idx_s) == 0:
            p_navs.append(1.0)
            p_ex3s.append(1.0)
            continue
        ord_idx = idx_s[np.lexsort((-p_scores[idx_s], b_dates[idx_s]))]
        f_dt = ""
        tr_rets = []
        for i in ord_idx:
            bd = str(b_dates[i])[:10]
            if f_dt == "" or bd > f_dt:
                rt = r_vals[i]
                ed = str(e_dates[i])[:10] if pd.notna(e_dates[i]) else bd
                tr_rets.append(rt)
                f_dt = max(bd, ed)
        if len(tr_rets) == 0:
            p_navs.append(1.0)
            p_ex3s.append(1.0)
            continue
        tr_a = np.array(tr_rets)
        nv = float(np.prod(1.0 + tr_a))
        ex_v = float(np.prod(1.0 + np.sort(tr_a)[:-3])) if len(tr_a) > 3 else 1.0
        p_navs.append(nv)
        p_ex3s.append(ex_v)

    audit["weight_perturbation_300"] = {
        "trials": 300,
        "nav_median": round(float(np.median(p_navs)), 3),
        "nav_p25": round(float(np.percentile(p_navs, 25)), 3),
        "nav_p75": round(float(np.percentile(p_navs, 75)), 3),
        "ex_top3_median": round(float(np.median(p_ex3s)), 3),
        "ex_top3_p25": round(float(np.percentile(p_ex3s, 25)), 3),
        "ex_top3_p75": round(float(np.percentile(p_ex3s, 75)), 3),
        "pos_excess_count": int(sum(1 for v in p_navs if (v - 1.0) > -0.1784)),
        "pos_excess_ratio": round(float(sum(1 for v in p_navs if (v - 1.0) > -0.1784) / 300 * 100), 1),
        "ex_top3_gt1_count": int((np.array(p_ex3s) > 1.0).sum()),
        "ex_top3_gt1_ratio": round(float((np.array(p_ex3s) > 1.0).sum() / 300 * 100), 1),
    }

    with open(OUT_AUDIT_PATH, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"已保存全景审计文件至: {OUT_AUDIT_PATH}")
    print("[Done] 全部产出落盘完毕！")


if __name__ == "__main__":
    run_full_pipeline()
