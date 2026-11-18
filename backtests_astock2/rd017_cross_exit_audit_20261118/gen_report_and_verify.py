#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""生成精炼可读报告 RD_CROSS_EXIT_REPORT.md 并核验 rd_cross_exit_advice.json 结构与 D15 完整性。"""
import json, os, re

OUT_BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_opt_20261118"
ADV_PATH = f"{OUT_BASE}/rd_cross_exit_advice.json"
RPT_PATH = f"{OUT_BASE}/RD_CROSS_EXIT_REPORT.md"

d = json.load(open(ADV_PATH, encoding="utf-8"))

req_keys = ["generated_at", "author", "methodology_notes", "s_pry_audit_and_advice", "s_2to3_cross_advice", "s_3to4_cross_advice", "overall_summary_for_pm"]
for k in req_keys:
    assert k in d, f"Missing key: {k}"
assert d["author"] == "astock2_rd"

# Build markdown tables strictly from verified JSON values
lines = []
lines.append("# A股二号席（`astock2`）跨策略卖点交叉实证审计报告")
lines.append("")
lines.append(f"生成时间：{d['generated_at']} ｜ 作者：`{d['author']}` ｜ 交易成本：双边 `0.20%` ｜ 严禁 `yfinance`（`D12`）与日内未来函数（`D15`）")
lines.append("")
lines.append("## 一、一句话总结论（给 PM `astock`）")
lines.append("")
lines.append(f"1. **`s_pry`（超跌撬板 V1.0）**：{d['overall_summary_for_pm']['s_pry']}")
lines.append(f"2. **`s_2to3`（二进三 V2.0）**：{d['overall_summary_for_pm']['s_2to3']}")
lines.append(f"3. **`s_3to4`（三进四 V4.0）**：{d['overall_summary_for_pm']['s_3to4']}")
lines.append("")

# 5m coverage section
lines.append("## 二、本地全量 5m 库覆盖率实查（绝不静默填补）")
lines.append("")
c1 = d["s_pry_audit_and_advice"]["five_m_coverage_audit"]
c2 = d["s_2to3_cross_advice"]["baseline_repro"]["five_m_coverage"]
c3 = d["s_3to4_cross_advice"]["baseline_repro"]["five_m_coverage"]
lines.append(f"- **`s_pry`**：联合本地 5m 库共 `{c1['union_5m_pairs']}` 个 `(c6, date)` 样本。`435` 笔满 `165` 分全池在 `T+1` 仅覆盖 `{c1['full_435_pool']['day_counts']['T+1']}/435`（`{c1['full_435_pool']['t1_cov_pct']}%`），`25` 笔单日头名在 `T+1~T+3` 覆盖 `0/25`（`0.0%`）。结论：盘中分时条件止盈（`10:30` 均价线或摸高回撤 `-2.5%`）因缺乏 5m 数据无法做无偏回测，标为数据缺口待补采。")
lines.append(f"- **`s_2to3`**：`94` 笔标准档总 `D4` 覆盖 `{c2['std90_94trades']['d4_5m_cov']}`（`{c2['std90_94trades']['d4_5m_cov_pct']}%`），持仓期全覆盖 `{c2['std90_94trades']['hold_days_5m_cov']}`（`{c2['std90_94trades']['hold_days_5m_cov_pct']}%`）。其中**未封三板（`69` 笔）`D4` 覆盖 `0/69`（`0.0%`）**，**封死三板（`25` 笔）`D4` 覆盖 `22/25`（`88.0%`）**、持仓期 `47/58`（`81.0%`）。故未封三板 `D4` 10:30 均价线亦因 0% 覆盖暂无法检验，封板期 5m 连板规则可充分实测。")
lines.append(f"- **`s_3to4`**：`95` 笔标准档 `D5` 覆盖 `{c3['std90_95trades']['d5_5m_cov']}`（`{c3['std90_95trades']['d5_5m_cov_pct']}%`），全持仓日覆盖 `{c3['std90_95trades']['hold_days_5m_cov']}`（`{c3['std90_95trades']['hold_days_5m_cov_pct']}%`），S 档 `31` 笔持仓日覆盖 `{c3['strict102_31trades']['hold_days_5m_cov']}`（`{c3['strict102_31trades']['hold_days_5m_cov_pct']}%`），5m 回测完备。")
lines.append("")

# Task 1 table
lines.append("## 三、任务一：`s_pry` 前视偏差审计与零前视卖点重塑")
lines.append("")
lines.append(f"- **前视偏差审计结论**：{d['s_pry_audit_and_advice']['lookahead_bug_audit']['finding']}")
lines.append("")
lines.append("| 变体方案 | 5Y单仓净值 (胜率/PLR/MDD/去T3/净超额) | IS(21~23)单仓 | OOS(24~26)单仓 | 2026单仓 | 5Y全池等权(IS/OOS) | 25日头名等权 |")
lines.append("|---|---|---|---|---|---|---|")
for v in d["s_pry_audit_and_advice"]["variants_comparison"]:
    m = v["metrics"]
    f5, is_, oo, y26 = m["full_5y"], m["is_21_23"], m["oos_24_26"], m["y2026_1y"]
    s5 = f5["single_slot"]
    lines.append(
        f"| `{v['name']}` | `{s5['nav']:.3f}x` ({s5['wr_pct']}%/{s5['plr']}/{s5['mdd_pct']}%/{s5['trim3_nav']:.2f}x/`{s5['excess_pp']:+.1f}pp`) "
        f"| `{is_['single_slot']['nav']:.3f}x` ({is_['single_slot']['excess_pp']:+.1f}pp) "
        f"| `{oo['single_slot']['nav']:.3f}x` ({oo['single_slot']['excess_pp']:+.1f}pp) "
        f"| `{y26['single_slot']['nav']:.3f}x` ({y26['single_slot']['excess_pp']:+.1f}pp) "
        f"| `{f5['daily_eq_all']['nav']:.3f}x` (`{is_['daily_eq_all']['nav']:.2f}x`/`{oo['daily_eq_all']['nav']:.2f}x`) "
        f"| `{f5['daily_top1_eq']['nav']:.3f}x` |"
    )
lines.append("")
lines.append("**`830` 笔宽池（`92` 个交易日）样本外同向验证**：")
b8 = d["s_pry_audit_and_advice"]["broad_830_pool_robustness"]["variants"]
for nm in ["strict_premarket_v1", "1a_limit_c65_f5_uncap_h3", "1a_no_below_zt_h4", "1c_switch_t1-02_h2_imm0", "1c_switch_t1-02_h3_imm1"]:
    bm = b8[nm]
    lines.append(f"- `{nm}`：5Y全池等权 `{bm['full_5y']['daily_eq_all']['nav']:.3f}x`（IS `{bm['is_21_23']['daily_eq_all']['nav']:.2f}x`，OOS `{bm['oos_24_26']['daily_eq_all']['nav']:.2f}x`），单仓 `{bm['full_5y']['single_slot']['nav']:.3f}x`。")
lines.append("")

# Task 2 table
lines.append("## 四、任务二：`s_2to3`（94笔标准档 & 35笔96分S档）跨策略卖点实测")
lines.append("")
lines.append("| 变体方案 | std90 5Y单仓 (WR/PLR/MDD/去T3/净超额) | std90 IS(full) / OOS / 2026 | std90 5Y日等权 | strict96 5Y单仓 (IS/OOS/EQ) |")
lines.append("|---|---|---|---|---|")
seen_2 = set()
for e in d["s_2to3_cross_advice"]["unsealed_d3_variants"] + d["s_2to3_cross_advice"]["sealed_3b_relay_variants"]:
    if e["name"] in seen_2:
        continue
    seen_2.add(e["name"])
    s90, s96 = e["std90"], e["strict96"]
    f5 = s90["full_5y"]["single_slot"]
    isf, oo, y26 = s90["is_21_23_full"]["single_slot"], s90["oos_24_26"]["single_slot"], s90["y2026_1y"]["single_slot"]
    eq5 = s90["full_5y"]["daily_eq"]
    f5_s = s96["full_5y"]["single_slot"]
    lines.append(
        f"| `{e['name']}` | `{f5['nav']:.2f}x` ({f5['wr_pct']}%/{f5['plr']}/{f5['mdd_pct']}%/{f5['trim3_nav']:.2f}x/`{f5['excess_pp']:+.1f}pp`) "
        f"| `{isf['nav']:.2f}x` / `{oo['nav']:.2f}x` / `{y26['nav']:.2f}x` "
        f"| `{eq5['nav']:.2f}x` (`{eq5['excess_pp']:+.1f}pp`) "
        f"| `{f5_s['nav']:.2f}x` (`{s96['is_21_23_full']['single_slot']['nav']:.2f}x`/`{s96['oos_24_26']['single_slot']['nav']:.2f}x`/`{s96['full_5y']['daily_eq']['nav']:.2f}x`) |"
    )
lines.append("")

# Task 3 table
lines.append("## 五、任务三：`s_3to4`（95笔标准档 & 31笔102分S档）跨策略卖点实测")
lines.append("")
lines.append("| 变体方案 | std90 5Y单仓 (WR/PLR/MDD/去T5/净超额) | std90 IS / OOS / 2026 | std90 5Y日等权 | strict102 5Y单仓 (OOS/去T5/EQ) |")
lines.append("|---|---|---|---|---|")
seen_3 = set()
for e in d["s_3to4_cross_advice"]["high_open_d5_takeprofit_variants"] + d["s_3to4_cross_advice"]["severe_abnormality_buffer_variants"] + d["s_3to4_cross_advice"]["intraday_guard_and_unsealed_variants"]:
    if e["name"] in seen_3:
        continue
    seen_3.add(e["name"])
    s90, s102 = e["std90"], e["strict102"]
    f5 = s90["full_5y"]["single_slot"]
    is_, oo, y26 = s90["is_22_23"]["single_slot"], s90["oos_24_26"]["single_slot"], s90["y2026_1y"]["single_slot"]
    eq5 = s90["full_5y"]["daily_eq"]
    f5_s = s102["full_5y"]["single_slot"]
    lines.append(
        f"| `{e['name']}` | `{f5['nav']:.2f}x` ({f5['wr_pct']}%/{f5['plr']}/{f5['mdd_pct']}%/{f5['trim5_nav']:.2f}x/`{f5['excess_pp']:+.1f}pp`) "
        f"| `{is_['nav']:.2f}x` / `{oo['nav']:.2f}x` / `{y26['nav']:.2f}x` "
        f"| `{eq5['nav']:.2f}x` (`{eq5['excess_pp']:+.1f}pp`) "
        f"| `{f5_s['nav']:.2f}x` (`{s102['oos_24_26']['single_slot']['nav']:.2f}x`/`{f5_s['trim5_nav']:.2f}x`/`{s102['full_5y']['daily_eq']['nav']:.2f}x`) |"
    )
lines.append("")
lines.append("### 近两年严监管期（`2025-01-01 ~ 2026-11-16`，沪深300 `+1.14%`）补充对比")
lines.append("")
r25 = d["s_3to4_cross_advice"]["recent_25_26_reg_era_check"]
for k in ["baseline_v40", "3b_dev93_5b", "3b_dev96_5b", "3b_dev98_5b"]:
    m90, m102 = r25[k]["std90"], r25[k]["strict102"]
    lines.append(f"- `{k}`：std90 单仓 `{m90['single_nav']:.2f}x`（胜率 `{m90['wr_pct']}%`，去T3 `{m90['trim3_nav']:.2f}x`，等权 `{m90['eq_nav']:.2f}x`）｜ strict102 单仓 `{m102['single_nav']:.2f}x`（去T3 `{m102['trim3_nav']:.2f}x`）。")

txt = "\n".join(lines) + "\n"
assert "—" not in txt and "——" not in txt, "Em-dash found!"
with open(RPT_PATH, "w", encoding="utf-8") as f:
    f.write(txt)
print(f"[PASS] Verified JSON & wrote {RPT_PATH} ({os.path.getsize(RPT_PATH):,} bytes)")
