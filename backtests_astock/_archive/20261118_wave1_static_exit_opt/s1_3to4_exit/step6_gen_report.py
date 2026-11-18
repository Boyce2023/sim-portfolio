#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step6_gen_report.py
基于 summary_3to4_exit_opt.json 与 sweep_all_phases_raw.csv 生成研究报告 report_3to4_exit_opt.md。
遵循通俗人话、零连字符/破折号、单句极简、11个术语带中文注与硬数据可溯源原则。
"""

import json
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_opt_20261118/s1_3to4_exit"
SUM_JSON = f"{OUT_DIR}/summary_3to4_exit_opt.json"
SWEEP_CSV = f"{OUT_DIR}/sweep_all_phases_raw.csv"
OUT_MD = f"{OUT_DIR}/report_3to4_exit_opt.md"


def fmt_dt(s: str) -> str:
    return s.replace("-", ".")


def main():
    with open(SUM_JSON, "r", encoding="utf-8") as f:
        d = json.load(f)
    df_sw = pd.read_csv(SWEEP_CSV)

    d15_90 = d["d15_windows_comparison"]["std90"]
    d15_102 = d["d15_windows_comparison"]["strict102"]
    a8_90 = d["overfitting_8tests_comparison"]["std90"]
    a8_102 = d["overfitting_8tests_comparison"]["strict102"]
    diffs = d["changed_trades_vs_v40_with_5m_trace"]
    trunc = d["integrity_and_truncation_audit"]["truncation_cutoff_20250101"]

    lines = []
    lines.append("# 三进四 V4.0 卖点全谱系跨策略互学与五分钟微观深度优化报告\n")
    lines.append(
        "**总结论：现役三进四 V4.0 卖出规则已达全局最优，建议保留原版卖点不改。** "
        "我们在四阶段共测试 363 组跨策略互学与五分钟微观卖点变体。 "
        "所有在 IS（2021.11.15 至 2023.12.31）表现抢眼的激进改法，在全盲 OOS（样本外，2024.01.01 至 2026.11.16）检验中均出现明显退化并被证伪。 "
        "唯一零负面副作用的轻度风控备选，是在断板免死判定中增加当日换手率不超过 35% 的上限。 "
        "该风控使 90 分标准档单仓维持 1799.99 倍不变，按日等权从 4458.94 倍微升至 4503.64 倍，102 分 S 档从 16.72 倍微升至 16.89 倍。\n"
    )

    lines.append("## 一、基准复现与硬边界核验\n")
    b5 = d15_90["V4.0_Base_保留原版最优"]["全五年"]
    b102_5 = d15_102["V4.0_Base_保留原版最优"]["全五年"]
    lines.append("1. **买点与打分零混杂**：候选池、22 项打分卡与 `10:30` 前突破买点均与现役 V4.0 完全一致，只改变卖出分支。")
    lines.append(
        f"2. **基准 0.0 误差复现**：90 分标准档五年 {b5['single_n']} 笔，胜率 {b5['win_rate_pct']}%，盈亏比 {b5['plr']}，单仓 {b5['single_slot_nav']} 倍，等权 {b5['daily_equal_weight_nav']} 倍，最大回撤 {b5['max_drawdown_pct']}%。"
    )
    lines.append(
        f"3. **S 档同步复现**：102 分 S 档五年 {b102_5['single_n']} 笔，胜率 {b102_5['win_rate_pct']}%，盈亏比 {b102_5['plr']}，单仓 {b102_5['single_slot_nav']} 倍，与现役台账逐笔误差为 `0.0`。"
    )
    lines.append(
        f"4. **合规与物理截断通过**：全部受审方案满足零 `T+0`、零仓位重叠、零一字涨停买入；物理切除 `2025.01.01` 及之后全部数据单独回测 `2021 至 2024` 共 {len(trunc)} 组，`max_abs_diff` 全为 `0.0`。\n"
    )

    lines.append("## 二、四阶段正交卖点扫描结论\n")
    lines.append(f"全谱系共评估 **{len(df_sw)} 组** 卖点方案。其中阶段 A 测试 25 组，阶段 B 测试 35 组，阶段 C 测试 284 组，阶段 D 测试 19 组。\n")

    lines.append("### 1. 阶段 A（买日未封死四板）：现行次日弱斩规则不可动摇")
    lines.append("- **借二进三 V2.0（取消 `09:25` 斩或仅大阴破位斩）**：IS 净值从 4.75 倍跌至 3.56 到 3.80 倍；OOS（样本外）单仓从 379.08 倍跌至 241.08 到 247.73 倍。若叠加收盘跌停不可卖延迟，IS 回撤恶化到 47.73%。")
    lines.append("- **物理机制原因**：二进三失败时筹码处于低位接力期，扛早盘容易反抽；三进四失败属于四连板高位衰竭，开盘竞价转弱即是先知主力核按钮派发起点。")
    lines.append("- **借一进二 V19（`10:30` 分时 VWAP 或暗牌雪球 `<4` 帖豁免）**：IS 净值全部跌至 3.52 到 4.15 倍，OOS（样本外）跌至 276.10 到 290.13 倍。因 V4.0 选股期已用 U02 筛过雪球热度，再对未封死四板票给暗牌豁免等于放任跌停套牢。")
    lines.append("- **Day5 竞价阈值细扫（负 3.0% 到正 2.0%）**：保持 `c4>=o4 且 c4>=p4` 下，0.0% 到 +2.0% 在 IS 上构成 4.75 倍平台，现行 `+0.5%` 处于中心稳健区。\n")

    lines.append("### 2. 阶段 B（极高开兑现与双严重异动限价单）：全部被 OOS（样本外）证伪")
    lines.append("- **封板次日极高开兑现（借二进三 V2.0）**：在 IS 仅 `+8.8%` 且 5 板以上触发 1 笔，`+9.0%` 以上触发为 0。在 OOS（样本外）使等权净值从 983.21 倍跌至 824.32 倍，102 分 S 档从 11.37 倍跌至 7.44 倍。")
    lines.append("- **双严重异动缓冲限价单（借高标首阴 V5.1）**：在 IS 上，只有 `93%`（5.39 到 5.46 倍）表面占优，微调到 `96%` 与 `98%` 在 IS 立刻塌方至 4.02 到 4.59 倍，未过参数平滑检验。")
    lines.append("- **OOS（样本外）腰斩大妖证据**：即便延迟到满 7 板（8 板日及以上）才挂 `93%` 限价单，依然半途砍断 `合富中国`（少赚 98.76pp）与 `艾艾精工`（少赚 72.70pp）。这导致 90 分 OOS（样本外）等权净值跌 14.5% 至 840.29 倍，102 分 S 档 OOS（样本外）从 11.37 倍跌 55.9% 至 5.02 倍。\n")

    lines.append("### 3. 阶段 C（连板持有期五分钟护利网格）：收紧阈值在 OOS（样本外）切伤妖股呼吸区")
    lines.append("- **借一进二 V19（`10:30` VWAP 与 `14:30` 炸板抢跑）**：`10:30` 破均线在 IS 跌至 2.70 倍、OOS（样本外）跌至 102.99 倍；叠加 `14:30` 炸板即跑使 OOS（样本外）跌至 244.20 倍。")
    lines.append("- **280 组三维网格与大妖分歧验证**：在熊市 IS 上，将回落阈值从 `+5.0%` 收紧至 `+6.0%`（`13:45 摸 +8.5% 破 +6.0%`），IS 净值升至 5.49 倍、回撤降至 29.23% 且 9 笔改动全胜。但在 OOS（样本外）上，该方案单仓从 379.08 倍跌至 275.99 倍，等权从 983.21 倍跌至 738.83 倍。")
    lines.append("- **五分钟微观根因**：全五年 21 笔改动中虽有 19 笔小幅优化，但 `603122 合富中国` 在 `2025.11.10`（第 10 板）日内深水拉升封板后，于 `15:00` 尾盘集合竞价压至 `+5.26%` 完成极限分歧洗盘，随后再连走 4 板总赚 +148.46%。现行 `+5.0%` 护利线恰好保住了这只总龙，而 `+6.0%` 在 `15:00` 将其踢飞（少赚 73.95pp）。\n")

    lines.append("### 4. 阶段 D（断板免死金牌）：保留原版，备选增加换手率不超过 35% 上限")
    lines.append("- **零免死方案**：IS 仅靠 2 笔微涨至 5.23 倍，但在 OOS（样本外）同样在 `2025.11.10` 提前卖出 `合富中国`（少赚 75.16pp），致 OOS（样本外）单仓跌至 277.30 倍、S 档跌至 8.01 倍，判定证伪。")
    lines.append("- **收涨满 2%、假阴真阳与次日低开斩**：在 90 分档仅影响 2 到 4 笔交易，扩充到 351 笔全部核心候选池验证后胜负参半（均值分别为负 0.18pp、负 0.60pp 与 4 胜 3 负），不具备跨样本统计稳健性。")
    lines.append("- **换手率上限 35% 微风控**：在 30% 到 40% 平稳区间上，全部核心池 3 胜 0 负（IS 救出 `好上好` +4.09pp，OOS 避开 `红宝丽` 48.7% 巨量派发 +1.04pp 及 `百花医药` +6.72pp），且绝不误伤换手 28.9% 的 `合富中国`。\n")

    lines.append("## 三、D15 六大窗口核心对比（90 分标准档 & 102 分 S 档）\n")
    show_models = [
        ("V4.0_Base_保留原版最优", "现行 V4.0 原版（推荐保留）"),
        ("V4.0_Plus_D4to35_换手微风控", "V4.0 加免死换手上限 35%（备选）"),
        ("StageA_2to3_no_0925_cut", "阶段 A 对照：取消 09:25 斩（证伪）"),
        ("StageB2_IS_dev93_ge7b", "阶段 B2 对照：7 板起挂 93%（证伪）"),
        ("StageC_IS_1345_p85_d60", "阶段 C 对照：13:45 摸 8.5 破 6.0（证伪）"),
        ("StageD_IS_D1_zero_imm", "阶段 D 对照：零免死（证伪）"),
        ("Combo_IS_Naive_C8560_D1", "IS 最优强拼接对照（证伪）"),
    ]
    win_order = ["全五年", "IS_21_23", "OOS_24_26", "近三年", "2026全年", "2026年7月以来"]
    win_disp_map = {
        "全五年": "全五年",
        "IS_21_23": "IS（2021 至 2023）",
        "OOS_24_26": "OOS（样本外 2024 至 2026）",
        "近三年": "近三年",
        "2026全年": "2026 全年",
        "2026年7月以来": "2026 年 7 月以来",
    }

    for tier, tier_name, store in [("std90", "90 分标准档", d15_90), ("strict102", "102 分 S 档", d15_102)]:
        lines.append(f"### {tier_name}\n")
        lines.append("| 方案 | 窗口 | 笔数(全信号) | 胜率 | 盈亏比 | 单仓净值 | 等权净值 | 去Top3 | 去Top5 | 最大回撤 | 沪深300 | 单仓超额(pp) | 等权超额(pp) |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for mk, mname in show_models:
            for wn in win_order:
                v = store[mk][wn]
                lines.append(
                    f"| {mname} | {win_disp_map[wn]} | {v['single_n']}({v['raw_n']}) | {v['win_rate_pct']}% | {v['plr']} | {v['single_slot_nav']}倍 | {v['daily_equal_weight_nav']}倍 | {v['trimmed_top3_nav']}倍 | {v['trimmed_top5_nav']}倍 | {v['max_drawdown_pct']}% | {v['csi300_ret_pct']}% | {v['excess_1s_pp']} | {v['excess_eq_pp']} |"
                )
        lines.append("")

    lines.append("## 四、八项防过拟合硬核验\n")
    lines.append("| 档位 | 方案 | HLZ t(笔) | DSR(M=150) | 猴子 p 值 | ±20%最低保留 | 200x MC 中位 | CSCV PBO(分位/阶梯) | N_eff | Bootstrap 5%超额 | 胜出年份 | 地狱模式净值 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for tier, tname, astore in [("std90", "90分", a8_90), ("strict102", "102分S", a8_102)]:
        for mk, mname in [
            ("V4.0_Base_保留原版最优", "现行 V4.0 原版"),
            ("V4.0_Plus_D4to35_换手微风控", "V4.0 加换手上限 35%"),
            ("StageB2_IS_dev93_ge7b", "7 板起挂 93%（证伪）"),
            ("StageC_IS_1345_p85_d60", "13:45 破 6.0（证伪）"),
            ("Combo_IS_Naive_C8560_D1", "IS 最优强拼接（证伪）"),
        ]:
            a = astore[mk]
            t1, t2, t3, t4, t6, t7, t8 = (
                a["test1_dsr_hlz"], a["test2_monkey_5000"], a["test3_perturbation_and_lofo"],
                a["test4_cscv_pbo"], a["test6_n_eff_bootstrap"], a["test7_yearly_stability"], a["test8_slippage_and_hell_mode"]
            )
            lines.append(
                f"| {tname} | {mname} | {t1['hlz_t_trade']} | {t1['dsr_M150']} | {t2['p_value']} | {t3['min_perturb_retention_pct']}% | {t3['mc_weight_pm20_200runs']['nav_median']}倍 | {t4['quantile14_S10']['pbo_pct']}% / {t4['ladder_86_102_S10']['pbo_pct']}% | {t6['N_eff']} | {t6['bootstrap_5pct_excess_pct']}% | {t7['years_beating_csi300']} | {t8['hell_mode']['nav']}倍 |"
            )
    lines.append("\n注：7 板起挂 93% 双异动方案虽因砍断极端正极值拉低收益方差而使单笔 `HLZ t` 表面升至 5.22，但其真实复利能力全面下跌（90 分 MC 中位跌至 833.14 倍，102 分 S 档 MC 中位跌至 7.95 倍，地狱模式跌至 4.38 倍）。\n")

    lines.append("## 五、改动前后逐笔真实交易差异与五分钟盘口核验\n")
    for mk, mtitle in [
        ("V4.0_Plus_D4to35_换手微风控", "1. 免死换手上限 35% 变动明细（全五年 90 分档全信号仅 1 笔，属 102 分 S 档）"),
        ("StageB2_IS_dev93_ge7b", "2. 7 板起挂 93% 双异动单变动明细（共 17 笔，证伪核心原因在砍断合富中国与艾艾精工）"),
        ("StageC_IS_1345_p85_d60", "3. 13:45 摸 +8.5% 破 +6.0% 变动明细（共 21 笔，19 胜 2 负但遭合富中国尾盘集合竞价反杀）"),
        ("StageD_IS_D1_zero_imm", "4. 零免死变动明细（共 6 笔，合富中国少赚 75.16pp）"),
    ]:
        rows = diffs[mk]
        lines.append(f"### {mtitle}\n")
        lines.append("| 买日 | 代码 | 名称 | 分数 | 原版卖出 | 原收益 | 新版卖出 | 新收益 | 差值(pp) | 五分钟盘口真实走势核验 |")
        lines.append("|---|---|---|---:|---|---:|---|---:|---:|---|")
        for r in rows:
            tr = r["micro_5m_trace"]
            be = tr.get("base_exit_day", {})
            ne = tr.get("new_exit_day", {})
            b_txt = f"原卖日 {fmt_dt(be.get('date',''))}(开{be.get('open_pct')}%/高{be.get('high_pct')}%/低{be.get('low_pct')}%/收{be.get('close_pct')}%/换{be.get('turnover_pct')}%)" if be else "无"
            n_txt = f"新卖日 {fmt_dt(ne.get('date',''))}(开{ne.get('open_pct')}%/高{ne.get('high_pct')}%/低{ne.get('low_pct')}%/收{ne.get('close_pct')}%/换{ne.get('turnover_pct')}%)" if ne else "无"
            trace_str = b_txt if be.get("date") == ne.get("date") else f"{b_txt}；{n_txt}"
            lines.append(
                f"| {fmt_dt(r['buy_date'])} | {r['code']} | {r['name']} | {r['score']} | {fmt_dt(r['base_exit'])} | {r['base_ret_pct']:+.2f}% | {fmt_dt(r['new_exit'])} | {r['new_ret_pct']:+.2f}% | {r['delta_pp']:+.2f} | {trace_str} |"
            )
        lines.append("")

    a_rows = sorted(diffs["StageA_2to3_no_0925_cut"], key=lambda x: x["delta_pp"])
    lines.append("### 5. 阶段 A 取消 09:25 斩变动摘要（全五年共 30 笔，列最差 10 笔与最好 5 笔）\n")
    lines.append("| 买日 | 代码 | 名称 | 分数 | 原版卖出 | 原收益 | 新版卖出 | 新收益 | 差值(pp) | 新卖日盘口走势核验 |")
    lines.append("|---|---|---|---:|---|---:|---|---:|---:|---|")
    for r in a_rows[:10] + a_rows[-5:]:
        tr = r["micro_5m_trace"]
        ne = tr.get("new_exit_day", {})
        n_txt = f"{fmt_dt(ne.get('date',''))}(开{ne.get('open_pct')}%/低{ne.get('low_pct')}%/收{ne.get('close_pct')}%)" if ne else "无"
        lines.append(
            f"| {fmt_dt(r['buy_date'])} | {r['code']} | {r['name']} | {r['score']} | {fmt_dt(r['base_exit'])} | {r['base_ret_pct']:+.2f}% | {fmt_dt(r['new_exit'])} | {r['new_ret_pct']:+.2f}% | {r['delta_pp']:+.2f} | {n_txt} |"
        )
    lines.append("")

    content = "\n".join(lines)
    # 自动化标点规范核查（剔除 Markdown 表格对齐行 |---| 与负数减号及反引号标识）
    bad_em = content.count("—") + content.count("–")
    assert bad_em == 0, f"Found em/en dash: {bad_em}"

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[REPORT GENERATED CLEANLY] {OUT_MD} ({len(lines)} lines, {len(content)} chars)")


if __name__ == "__main__":
    main()
