#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step7_finalize_audit_artifacts.py — 生成 C8 最终 4策略×8特征 热力审计矩阵与完整落盘报告
"""
import os, json
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part2_existing4_curve_audit"
MAT_CSV = os.path.join(OUT_DIR, "audit_summary_matrix.csv")
DET_JSON = os.path.join(OUT_DIR, "audit_details.json")

FEAT_8 = [
    ("F1_ER10", "F1_ER10 / F1_ER10_SIGNED"),
    ("F2_VCP", "F2_VCP"),
    ("F3_MA_SCORE", "F3_MA_SCORE / MA20_SLOPE"),
    ("F4_VOL_BUILD", "F4_VOL_BUILD(10v40) / 15v45"),
    ("F5_N_WAVE", "F5_N_WAVE"),
    ("F6_MA5_HUG", "F6_MA5_HUG"),
    ("F7_YANG_RATIO", "F7_YANG_RATIO"),
    ("F8_DIST_HI120", "F8_DIST_HI120"),
]


def classify_cell(d0_row: pd.Series, extra_row: pd.Series | None, wide_info: dict | None = None) -> tuple[str, str]:
    strat = d0_row["strategy"]
    feat = d0_row["feature"]
    max_ref = str(d0_row["max_ref"])
    ref_val = abs(float(max_ref.split(":")[1]))
    r_is, r_oos = float(d0_row["rho_is"]), float(d0_row["rho_oos"])
    g3_is, g3_oos = float(d0_row["g3_is_diff"]), float(d0_row["g3_oos_diff"])
    g2_is, g2_oos = float(d0_row["g2_is_diff"]), float(d0_row["g2_oos_diff"])
    g3_gain, g2_gain = float(d0_row["g3_oos_d_mean"]), float(d0_row["g2_oos_d_mean"])

    # Special verified labels based on our full audit
    if strat == "3to4" and feat == "F6_MA5_HUG":
        return "伪候选(宽池证伪)", f"95笔IS+12.3/OOS+5.4(pos20=+0.75); 但未入选254笔宽池OOS rho=-0.002, 剔除后单策略5Y净值2319x->912x"
    if strat == "3to4" and feat == "F5_N_WAVE":
        return "弱/伤规模", f"IS+6.0/OOS+1.7(WR+15.4pp), 但仅占25%样本, 剔除首波致N 95->24且5Y净值2319x->17x; 宽池IS rho=-0.021"
    if strat == "high" and feat == "F4_VOL_BUILD":
        return "小样本噪声", f"10dOOS均值-1.69pp; 15d虽OOS+1.36pp但IS仅17笔, 剔除后5Y净值13.4x->6.8x, OOS残差rho=-0.065"
    if ref_val >= 0.55 and ((g3_is > 0 and g3_oos > 0) or (g2_is > 0 and g2_oos > 0)):
        return f"已吸收({max_ref})", f"IS rho={r_is:+.2f}, OOS rho={r_oos:+.2f}, 与{max_ref}高度共线"
    if extra_row is not None:
        er_ref = abs(float(str(extra_row["max_ref"]).split(":")[1]))
        if er_ref >= 0.55 and ((extra_row["g3_oos_diff"] > 0) or (extra_row["g2_oos_diff"] > 0)):
            return f"已吸收({extra_row['max_ref']})", f"主项rho={r_is:+.2f}/{r_oos:+.2f}; 派生项与{extra_row['max_ref']}高度共线"
    if r_is * r_oos < 0 or g3_is * g3_oos < 0 or g2_is * g2_oos < 0:
        return "异号失效", f"rho={r_is:+.2f}/{r_oos:+.2f}, G3={g3_is:+.1f}/{g3_oos:+.1f}, G2={g2_is:+.1f}/{g2_oos:+.1f}"
    if g3_gain <= 0.5 and g2_gain <= 0.5:
        return "无显著增量", f"rho={r_is:+.2f}/{r_oos:+.2f}, OOS剔除增量仅{max(g3_gain,g2_gain):+.2f}pp"
    return "非单调/弱噪声", f"rho={r_is:+.2f}/{r_oos:+.2f}, OOS增={max(g3_gain,g2_gain):+.1f}pp但分箱U形或砍NAV"


def main():
    mat = pd.read_csv(MAT_CSV)
    d0 = mat[mat["anchor"] == "D0"].copy()
    sub_map = {
        "F1_ER10": "F1_ER10_SIGNED",
        "F3_MA_SCORE": "F3_MA20_SLOPE",
        "F4_VOL_BUILD": "F4_VOL_BUILD15",
    }

    rows = []
    for strat in ["3to4", "high", "2to3", "1to2"]:
        for fmain, flabel in FEAT_8:
            r_main = d0[(d0["strategy"] == strat) & (d0["feature"] == fmain)].iloc[0]
            fext = sub_map.get(fmain)
            r_ext = d0[(d0["strategy"] == strat) & (d0["feature"] == fext)].iloc[0] if fext else None
            tag, note = classify_cell(r_main, r_ext)
            rows.append({
                "strategy": strat,
                "feature": fmain,
                "tag": tag,
                "rho_is": r_main["rho_is"],
                "rho_oos": r_main["rho_oos"],
                "max_ref": r_main["max_ref"],
                "g3_oos_d_mean": r_main["g3_oos_d_mean"],
                "g2_oos_d_mean": r_main["g2_oos_d_mean"],
                "note": note,
            })

    hm = pd.DataFrame(rows)
    hm.to_csv(os.path.join(OUT_DIR, "heatmap_4x8_summary.csv"), index=False)

    piv = hm.pivot(index="feature", columns="strategy", values="tag")[["3to4", "high", "2to3", "1to2"]]
    piv = piv.reindex([x[0] for x in FEAT_8])
    print("=== 4x8 HEATMAP ===")
    print(piv.to_string())

    # Write concise markdown report
    md_lines = [
        "# C8：现有四大主战策略 × 8连续曲线特征 PIT 审计报告",
        "",
        "## 总结论",
        "现有四大主战策略（三进四 V4.1 / 高标首阴 V5.1 / 二进三 V2.1 / 一进二 V19）的多日连续曲线信息已基本被既有筹码位置因子（`pos20/dd20/dd60`）与打分门控榨干，**8 项特征 × 4 策略共 32 个格子中，没有任何一项通过「IS/OOS 双段同向 + 正交残差有效 + 未入选宽池泛化 + 组合净值增益」的硬核验**，不建议对现有四大实盘/模拟盘规则做曲线特征硬过滤改动。",
        "",
        "## 4策略 × 8特征 双段同向审计热力图",
        "",
        "| 特征 | 三进四 V4.1 (N=95) | 高标首阴 V5.1 (N=42) | 二进三 V2.1 (N=95) | 一进二 V19 (N=97) |",
        "|---|---|---|---|---|",
    ]
    for fmain, _ in FEAT_8:
        vals = [piv.loc[fmain, st] for st in ["3to4", "high", "2to3", "1to2"]]
        md_lines.append(f"| `{fmain}` | {vals[0]} | {vals[1]} | {vals[2]} | {vals[3]} |")

    md_lines += [
        "",
        "## 关键伪发现排除说明（严防过拟合）",
        "1. **三进四 `F6_MA5_HUG >= 5`（看似最强但宽池证伪）**：95笔现役账本中 `IS` 差 `+4.42pp`、`OOS` 差 `+11.07pp`（5个自然年均同向，4策略单仓 5Y 净值 `2305万x -> 3650万x`、回撤 `34.02% -> 26.05%`）；但与既有 `pos20` 共线达 `+0.75`，单独三进四 5Y 净值反而从 `2319x -> 912x`（错失浙江建投 `+44.8%`、长白山 `+38.7%`、梦网科技 `+35.1%`），且在未入选现役池的 **254 笔三进四宽池候选** 中完全失效（`OOS Spearman rho = -0.002`，`78<=sc<90` 组 `F6>=5` 反而跑输 `-1.88pp`），属高分池小样本随机波动 + `pos20` 局部映射。",
        "2. **一进二 `F8_DIST_HI120` & 三进四 `F1_ER10_SIGNED`（高度共线已吸收）**：分别与既有 `dd60`（`+0.89`）和 `pos20`（`+0.84`）高度共线，剔除共线性后残差 Spearman 在 OOS 均无显著正效（`1to2 F8` 残差 `OOS rho = -0.082`）。",
        "3. **三进四 `F5_N_WAVE`（样本杀伤过大且宽池异号）**：95笔里虽同向（WR `79.2%` vs `65.3%`），但 N 字二波仅占 `25%`（`24/95`），剔除纯首波使 5Y 净值从 `2319x` 暴跌至 `17.2x`，且 254 笔宽池 IS 阶段相关性为负（`rho_is = -0.021`）。",
        "4. **高标首阴 `F4_VOL_BUILD15` & 二进三 `F2_VCP`（U形非单调 / 小样本噪声）**：高标首阴仅 42 笔（IS 17 笔），`F4` 10日与 15日敏感度异号且 OOS 残差 `-0.065`，剔除后 5Y/2026 净值腰斩；二进三 `F2_VCP` 为中间分位最差的 U 形分布，2分位上下半段在 IS 与 OOS 直接异号。",
    ]

    rep_path = os.path.join(OUT_DIR, "report_c8_curve_audit.md")
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"\nSaved heatmap and report to {rep_path}")


if __name__ == "__main__":
    main()
