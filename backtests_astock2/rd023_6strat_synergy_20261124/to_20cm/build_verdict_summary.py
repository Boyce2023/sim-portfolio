#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Compile master RD023 verdict summary CSV (Module 1 + PM tests + Module 2 duality) without cap10m."""
import os
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd023_6strat_synergy_20261124/to_20cm"
df1 = pd.read_csv(f"{OUT_DIR}/module1_40plus_experiments.csv")

verdicts = []
for r in df1.itertuples(index=False):
    eid = r.exp_id
    if eid == "T4_R_sen20_lt40":
        vd = "唯一候补外挂(OOS+2.61x/Y26+0.56x/EW+118x/PBO降,但IS微降-1.54x,不强升V1.2,保留V1.1为主线)"
    elif eid == "PM_F02_pct_le40":
        vd = "证伪淘汰(EW翻倍至678.35x/MDD降至31.68%,但PBO从1.43%/20%飙至30%/45.7%且S82 OOS跌至2.89x)"
    elif eid in ("PM_F02_pct_le30", "PM_F02_pct_le50", "PM_F02_drop_only"):
        vd = "证伪淘汰(或推高PBO或损及IS/OOS/S82,不替代F02静态<=20亿)"
    elif eid in ("T3_high_dual_dev93_b1", "T2_2to3_1345_guard_b1_12", "T2_2to3_d2_hiopen_tp12_b1"):
        vd = "证伪淘汰(极小样本仅改2~3笔且dev93首例系买前已触发异动,缺乏统计显著性与5m验证)"
    elif eid in ("T3_high_lock45_or_rfm45", "T3_high_lock45_alone"):
        vd = "证伪淘汰(覆盖率从17.5%漂移至58.1%,2026边际转负-0.84%,EW净值暴跌69.9x~134.9x)"
    elif eid == "T5_bias20_oversold_plus":
        vd = "证伪淘汰(2025年0%覆盖,EW净值跌38.4x,PBO跳升)"
    elif eid in ("T4_R_reg_new", "T4_R_elo135", "T3_high_true_yang_life", "T2_2to3_d2_hiopen_tp15_b1"):
        vd = "零改动冗余(被V1.1既有规则或骨架门控覆盖,触发改变0笔)"
    else:
        vd = "证伪淘汰(IS或OOS/2026恶化或大幅推高回撤/降低净值)"
    verdicts.append({
        "exp_id": eid, "source": r.source, "desc": r.desc,
        "IS_nav": r.IS_nav, "d_IS": r.d_IS, "OOS_nav": r.OOS_nav, "d_OOS": r.d_OOS,
        "Y26_nav": r.Y26_nav, "d_Y26": r.d_Y26, "FULL_nav": r.FULL_nav, "EW_nav": r.EW_nav,
        "MDD_pct": r.MDD_pct, "N_1s": r.N_1s, "WR_pct": r.WR_pct, "verdict": vd,
    })

pd.DataFrame(verdicts).to_csv(f"{OUT_DIR}/rd023_falsified_and_accepted_verdicts.csv", index=False, encoding="utf-8-sig")
print("Saved rd023_falsified_and_accepted_verdicts.csv:", len(verdicts), "rows")
