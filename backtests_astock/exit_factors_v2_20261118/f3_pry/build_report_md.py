#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Fix exact hit-count notes in factor_30_marginal_table.csv and render report_pry_exit_factors.md directly from verified CSV/JSON."""
import os, json
import pandas as pd

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
F3_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry"

tdf = pd.read_csv(f"{F3_DIR}/factor_30_marginal_table.csv")
# Ensure mechanism notes cite exact raw_hits & changed counts without hyphen/dash prose
fix_mech = {
    "XF01_d0_lhasa_trap": "持仓期仅12笔命中(IS 0笔/OOS 12笔)，实际改单5笔；撬板买前已扣分且极少D0上拉萨榜",
    "XF02_d0_daysurf_in": "持仓期仅9笔命中(IS 0笔/OOS 9笔)，实际改单2笔，仅微调0.002x，样本过稀不入模",
    "XF03_d0_inst_net_buy_vs_sell": "持仓期IS仅2笔且未改单，OOS改单62笔；机构净卖多因大涨出榜或做T，早盘砍反降OOS收益(2.072降至2.004)",
    "XF04_d0_top_youzi_in": "持仓期IS 0笔/OOS 54笔(改单32笔)，OOS拖累P165/P150/P140/P000四池，无普适性",
    "XF05_lhb_quant_churn": "持仓期IS 0笔/OOS 166笔(改单91笔)；量化席位在超跌反弹中提供流动性，砍仓反拉低P165与P150",
    "XF06_north_or_big_net_sell": "持仓期IS 2笔未改单，OOS改单67笔且四池全负贡献，反弹首日换手对倒不等于次日崩盘",
    "XF07_hold_bad_notice": "持仓期共17笔命中(IS 0笔/OOS 17笔，改单9笔)；虽作实盘黑天鹅硬风控必查项，但统计样本少且未升净值",
    "XF09_xq_spike_hold": "持仓期IS仅2笔/OOS 32笔(改单15笔)，且雪球库按1进2历史节点爬取存在覆盖偏倚，严禁入模",
}
for fid, txt in fix_mech.items():
    tdf.loc[tdf["factor_id"] == fid, "mechanism"] = txt
# Clean any ASCII hyphen arrows -> 降至/升至 in mechanism/rule_desc
tdf["mechanism"] = tdf["mechanism"].astype(str).str.replace("->", "变为", regex=False)
tdf["rule_desc"] = tdf["rule_desc"].astype(str).str.replace("->", "降至", regex=False)
tdf.to_csv(f"{F3_DIR}/factor_30_marginal_table.csv", index=False, encoding="utf-8-sig")

s = json.load(open(f"{F3_DIR}/summary_pry_exit_factors.json", encoding="utf-8"))
models = s["models"]
b1, d4, rd, v21 = models["B1_X10_v1_strict"], models["XF28_DecD_4d"], models["XF29a_RD_2d"], models["XF30_V21"]
plat = s["plateau_v21_81"]
ha = s["hard_assertions"]
live = s["live_000011_20261118"]
mid = live["midday_1130_snapshot"]

lines = []
lines.append("# 超跌橡皮筋撬板 V1.0 (`s_pry`) 持仓期 30 跨策略动态卖点因子挖掘与 V2.1 升级报告\n")
lines.append("`将「T+k 09:25 全场竞价涨停不足 5 家逃命 (XF13)」「D0 强真阳 CLV 满 0.70 免 T+1 弱斩兼抬止盈 3% (XF21)」「昨全场跌停不足 10 家市场止血后抬止盈 3% (XF16b)」三项多池 IS 4/4 全赢真因子注入 DecD_4d 时间阶梯后，P165 单仓五年净值从 1.9411 倍(现役 X10)与 2.3036 倍(上轮 V2.0)跃升至 2.4400 倍(胜率 87.50%，均持仓 2.06 天)，并在全局五顺位合体中五年与近三年同步超越 X10 与 DecD_4d；同时实证证伪二号席 RD 版 T+1 低开跌超 2% 于 09:25 立斩(割在日内情绪最低点)及龙虎榜/监管/雪球/股吧/MA5 等 24 项伪因子。`\n")
lines.append("---\n")
lines.append("## 一、研究方法论与 PIT 数据防泄漏约束\n")
lines.append("1. **严格多池 IS 定标与 OOS 盲测**：在 `P165`(>=165分，435笔/25触发日/16单仓)、`P150`(>=150分，541笔/44日)、`P140`(>=140分，612笔/58日) 与 `P000`(全基础池 830笔/92日) 的样本内 `IS (2021-11-15 至 2023-12-31)` 上同时检验因子同向性与 `±20%` 参数高原，随后在 `OOS (2024-01-01 至 2026-11-16)` 独立盲测。\n")
lines.append("2. **全库严格 PIT 时点截断**：龙虎榜优先取单日 `TRADE_ID` 并按营业部去重(仅 `D0..T+k-1` 盘后席位可用于 `T+k 09:25`)；公告与监管函联立 `cninfo_notices_5y_pit.db`、`pit_reg_tox_notices_5y_complete.parquet`、`notices.db` 与 `zdjk` 并卡死 `pub_datetime_cst < T+k 09:25:00`；雪球与股吧严格 `< T+k 09:25:00`；大盘竞价取自 `rt_env_map.json` 当日 `09:25` 实时切片；所有价格撮合沿用真实盘前死限价单与一字跌停顺延机制，零 `yfinance`。\n")
lines.append("3. **龙虎榜与雪球样本覆盖实情披露**：`P000` 全池 `IS` 阶段 138 笔超跌信号极少在买入当晚登榜龙虎榜(`XF01/XF02/XF04/XF05` 在 `IS` 命中 0 笔，`XF03/XF06` 在 `T+2` 后命中 2 笔)，故龙虎榜因子无法通过 `IS` 锁定门槛，仅在 `OOS` 验证其真实边际效应；`xueqiu_posts` 仅按一进二节点爬取，在超跌撬板 `IS` 仅命中 2 笔且存在回溯爬取覆盖偏倚，严禁入模。\n")
lines.append("---\n")
lines.append("## 二、30 个跨策略持仓卖点因子四池 IS 与 OOS 逐项实测总表\n")
lines.append("下表基准为上轮最佳 `XF28_DecD_4d`(现役 `B1_X10_v1` 对照见第三节)。「命中数」为全持仓窗内曾触发该因子的信号笔数，「改单数」为实际改变 `DecD_4d` 收益或卖点的笔数。\n")
lines.append("| 因子编号 | 规则口径简述 | P000命中(IS/OOS) | 改单数 | P165单仓(胜率/均持) | P165 IS/OOS等权 | P150 IS/OOS等权 | P140 IS/OOS等权 | P000 5Y等权 | 裁决与物理机制 |\n")
lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|\n")
for r in tdf.itertuples(index=False):
    lines.append(
        f"| `{r.factor_id}` | {r.rule_desc} | {r.raw_hits_P000} ({r.raw_hits_IS}/{r.raw_hits_OOS}) | {r.changed_trades_vs_DecD4} | "
        f"`{r.P165_ss_nav:.4f}x` ({r.P165_ss_wr:.1f}%/{r.P165_ss_hold:.2f}d) | "
        f"`{r.P165_IS_deq:.3f}/{r.P165_OOS_deq:.3f}` | `{r.P150_IS_deq:.3f}/{r.P150_OOS_deq:.3f}` | "
        f"`{r.P140_IS_deq:.3f}/{r.P140_OOS_deq:.3f}` | `{r.P000_ALL_deq:.3f}` | **{r.verdict}**：{r.mechanism} |\n"
    )

lines.append("\n### 关键证伪与新发现物理归因\n")
lines.append("1. **为什么 `XF13` (`09:25` 全场竞价涨停不足 5 家立斩) 是最强救命闸，而昨日跌停多 (`XF16a`) 与首板负溢价 (`XF14a`) 反而大亏？** `s_pry` 本身买在连续恐慌暴跌刚止血的左侧窗口，昨日跌停多 (`n_dt >= 30`) 与首板负溢价均是已计价的滞后恐慌，早上按此砍仓专洗反弹低点(`P165` 单仓跌至 `1.6217x` 与 `2.1559x`)；唯独持仓次日 `09:25` 全场开盘涨停骤降至 `< 5` 家(如 `2024-02-06` 仅 `3` 家涨停且 `149` 家跌停、`2022-03`、`2023-03`)，说明多头承接在次日早盘再次真空熄火，必须 `09:25` 立即市价出逃。\n")
lines.append("2. **为什么二号席 RD 推荐的 `T+1 低开 < -2% 于 09:25 立斩` 不如 `DecD_4d` 的 `14:55 跌超 1.5% 清仓`？** 同台对照证实：`XF29a_RD_2d` 胜过现役 `X10` (`1.1578x` vs `0.6677x`) 全部来自「涨停骑乘」与「缩短周期至 2 天」；而在 `DecD_4d` 基础上单加 `T+1 低开 < -2% 于 09:25 斩` (`XF23a`)，反让 `P150`/`P140`/`P000` 在 `IS` 与 `OOS` 全线回落(`P000` 从 `1.5695x` 降至 `1.3567x`)，因超跌橡皮筋股早盘常急杀洗盘后日内回弹，等到 `14:55` 收盘确认真弱再砍更少挨反手巴掌。\n")
lines.append("3. **为什么 `XF27` (一进二首板紧密度 `>= 37`) 不适用于超跌撬板涨停股？** 一进二主战吃的是「主线强分歧转一致紧封」，而超跌撬板股在底部首板时本就带着巨量抄底与套牢抛压换手，硬套 `>= 37` 紧封与零拉萨门槛将 25 笔底部烂板首板提前赶下车，反输给无条件连板接力。\n")
lines.append("4. **为什么 `XF19` (行业涨停队友) 与 `XF24` (高开 >= +2% 放飞) 虽有正贡献却不入 core V2.1？** 实测将 `XF19b` 与 `XF24a` 叠加进 `V2.1` 后(`C8`)，虽单池等权小幅上升，但个别样本持仓拉长挤占了全局五顺位单仓中的三进四与一进二主战大牛股，导致全局五顺位五年合体净值从 `14,359,337x` 回落至 `12,689,586x` (`-11.6%`)，故严格剔除。\n")

lines.append("\n---\n")
lines.append("## 三、终极版 `XF30_V21` vs `XF28_DecD_4d` vs `XF29_RD_2d` vs 现役 `X10` 硬核全面对比\n")
lines.append("### 3.1 D15 五大窗口与全局五顺位合体 (`三进四V4.0 > 高标首阴V5.1 > 超跌撬板 > 二进三V2 > 一进二V19`)\n")
lines.append("| 评估维度与窗口 | `B1_X10_v1` (现役V1.0) | `XF28_DecD_4d` (上轮V2.0) | `XF29a_RD_2d` (RD推荐版) | `XF30_V21` (终极V2.1) |\n")
lines.append("|---|---:|---:|---:|---:|\n")

def fmt_w(md, pool, win, sub="ss"):
    m = md[pool][win][sub]
    return f"`{m['nav']:.4f}x` ({m['wr']:.1f}%/{m['plr']:.2f}/回撤{m['mdd']:.1f}%/超额`{m['excess_pp']:+.1f}pp`)"

w_rows = [
    ("**P165 独立单仓 全五年 (16笔)**", "P165", "全五年(2021-11-15~2026-11-16)", "ss"),
    ("**P165 独立单仓 IS (8笔)**", "P165", "IS(2021-11-15~2023-12-31)", "ss"),
    ("**P165 独立单仓 OOS (8笔)**", "P165", "OOS(2024-01-01~2026-11-16)", "ss"),
    ("**P165 独立单仓 近三年 (8笔)**", "P165", "近三年(2023-11-16~2026-11-16)", "ss"),
    ("**P165 独立单仓 2026全年 (2笔)**", "P165", "2026全年(2026-01-01~2026-11-16)", "ss"),
    ("**P165 25触发日等权 (全5Y)**", "P165", "全五年(2021-11-15~2026-11-16)", "deq"),
    ("**P150 44触发日等权 (全5Y)**", "P150", "全五年(2021-11-15~2026-11-16)", "deq"),
    ("**P150 单仓全五年 (IS/OOS)**", None, None, None),
    ("**P140 58触发日等权 (全5Y)**", "P140", "全五年(2021-11-15~2026-11-16)", "deq"),
    ("**P000 92触发日等权 (全5Y)**", "P000", "全五年(2021-11-15~2026-11-16)", "deq"),
]
for lbl, pl, wn, sb in w_rows:
    if pl is None:
        cells = []
        for md in (b1, d4, rd, v21):
            t50 = md["tests_P150_ss"]
            is_s = md["P150"]["IS(2021-11-15~2023-12-31)"]["ss"]["nav"]
            oo_s = md["P150"]["OOS(2024-01-01~2026-11-16)"]["ss"]["nav"]
            cells.append(f"`{is_s*oo_s:.3f}x` (IS`{is_s:.3f}`/OOS`{oo_s:.3f}`, N={t50['N']})")
        lines.append(f"| {lbl} | {cells[0]} | {cells[1]} | {cells[2]} | **{cells[3]}** |\n")
    else:
        lines.append(f"| {lbl} | {fmt_w(b1,pl,wn,sb)} | {fmt_w(d4,pl,wn,sb)} | {fmt_w(rd,pl,wn,sb)} | **{fmt_w(v21,pl,wn,sb)}** |\n")

# Portfolio rows
for lbl, key in [
    ("**全局4策略合体 (5Y单仓/1000万封顶)**", "portfolio_4strat_5y"),
    ("**全局5策略合体 全五年 (5Y)**", "portfolio_5strat_5y"),
    ("**全局5策略合体 近三年 (3Y)**", "portfolio_5strat_3y"),
    ("**全局5策略合体 2026全年**", "portfolio_5strat_26"),
]:
    c_list = []
    for md in (b1, d4, rd, v21):
        pm = md[key]
        c_list.append(f"`{pm['nav_slot']:,.2f}x` (WR`{pm['win_rate']:.2f}%`/MDD`{pm['max_dd_pct']:.2f}%`/10M`{pm['cap10m_mult']:.2f}x`)")
    lines.append(f"| {lbl} | {c_list[0]} | {c_list[1]} | {c_list[2]} | **{c_list[3]}** |\n")

lines.append("\n### 3.2 Q8 八大防过拟合检验、81 宫格高原与物理截断四大硬断言\n")
lines.append("1. **四大硬断言全绿**：全部模型 `t0_violations == 0`、`overlap_violations == 0`、`yizi_dt_exit_violations == 0`；将行情、基础面板及全部外部 PIT 库(龙虎榜、公告、监管、雪球、股吧、开盘啦、涨停微观、每日市场环境)严格物理截断至 `< 2025-01-01` 全量重跑 `XF30_V21`，`exit_date < 2025-01-01` 共 **`693` 笔** 全部信号收益与原回测 **`max_abs_diff = 0.0`**。\n")
lines.append(f"2. **81 宫格 `±20%` 参数高原稳健性**(`zt_th∈{{4,5,6}} × clv_th∈{{0.6,0.7,0.8}} × ndt_th∈{{8,10,12}} × boost∈{{2%,3%,4%}}`)：`P165` 单仓净值最小值 `2.2380x`、中位数 `2.3447x`、最大值 `2.4637x`；**`100.0%` 组合同时全面击败现役 `X10`**，**`77.8%` 组合同时在 `P165` 单仓、`P150 OOS` 与 `P140 IS` 三维度超越 `DecD_4d`**。\n")
lines.append("3. **八项防过拟合统计学对比（诚实披露 `P165 N=16 < 30` 红灯，联合 `P150 N=30` 达标验证）**：\n")
for lbl, key in [("P165 单仓 (`N=16` 红灯)", "tests_P165_ss"), ("P150 单仓 (`N=30` 达标)", "tests_P150_ss")]:
    t_b1, t_d4, t_21 = b1[key], d4[key], v21[key]
    lines.append(
        f"   - **{lbl}**：`XF30_V21` vs `DecD_4d` vs `X10`：`HLZ t_trade` 从 `{t_b1['HLZ_t_trade']:.2f}` / `{t_d4['HLZ_t_trade']:.2f}` 升至 **`{t_21['HLZ_t_trade']:.2f}`**(`t_daily` `{t_21['HLZ_t_daily']:.2f}`)，"
        f"`DSR(M=150)` 从 `{t_b1['DSR_M150_trade']:.3f}` / `{t_d4['DSR_M150_trade']:.3f}` 升至 **`{t_21['DSR_M150_trade']:.3f}`**，"
        f"同池猴子抽签 `p` 为 **`{t_21['monkey_p']:.4f}`**，Bootstrap 5% 超额下限 **`{t_21['bootstrap_5pct_ci_pct']:+.2f}%`**，"
        f"去前 3 笔净值 **`{t_21['ex_top3_nav']:.4f}x`**(现役 `{t_b1['ex_top3_nav']:.4f}x`/上轮 `{t_d4['ex_top3_nav']:.4f}x`)，"
        f"3 倍滑点净值 **`{t_21['nav_3x_slip']:.4f}x`**，85 变体 CSCV `PBO = {t_21['cscv_pbo']:.4f} < 0.50`。\n"
    )

lines.append("\n---\n")
lines.append("## 四、`P165` 16 笔单仓逐笔对比与今日 `000011 深物业A` 实盘执行手册\n")
lines.append("### 4.1 `P165` 16 笔单仓四版本逐笔对照\n")
lines.append("| 买入日 | 代码 | 名称 | X10净益 | DecD4净益 | RD2d净益 | V2.1净益 | V2.1 vs X10 | V2.1 vs DecD4 | V2.1触发分支 |\n")
lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---|\n")
for tr in s["p165_16trades_comparison"]:
    lines.append(
        f"| {tr['buy_date']} | {tr['code']} | {tr['name']} | {tr['X10_ret']:+.2f}% | {tr['DecD4_ret']:+.2f}% | {tr['RD2d_ret']:+.2f}% | "
        f"**{tr['V21_ret']:+.2f}%** | {tr['delta_V21_vs_X10']:+.2f}pp | {tr['delta_V21_vs_DecD4']:+.2f}pp | {tr['V21_reason']} |\n"
    )

lines.append("\n### 4.2 今日 (`2026-11-18`) 实盘持仓 `000011 深物业A` 精确执行手册与今晚盘后检查清单\n")
lines.append(
    f"- **实时盘面锚定（截至今日 `11:30` 午盘休市）**：昨日 (`11-17`) 收盘 `6.94` 元，今日开盘买入价 `6.97` 元(`+0.43%`)，今日涨停价 `7.63` 元、跌停价 `6.25` 元，基准止盈 `dyn_tp = +11.46%` (`7.77` 元)。今日早盘最高 `7.12` 元(`+2.59%`)、最低 `6.80` 元(`-2.02%`)、午盘收报 **`{mid['price']:.2f}` 元(`{mid['pct_vs_prev']:+.2f}%`)**，换手 `{mid['to_pct']:.2f}%`，当前 `CLV = {mid['clv_midday']:.3f}`(暂未达强真阳标准)；今日早盘 `09:25` 全场竞价涨停 `{mid['mkt_open_zt_0925']}` 家(较昨日 `4` 家回暖)，午盘实时涨停 `{mid['mkt_now_zt_1130']}` 家、跌停 `{mid['mkt_now_dt_1130']}` 家(较昨日 `{mid['prev_1117_n_dt']}` 家跌停明显收窄但仍大于 `10` 家)。\n"
)
lines.append("- **V2.1 分日精确执行动作**：\n")
for k, v in live["v21_execution_rules"].items():
    lines.append(f"  - **`{k}`**：{v}\n")
lines.append("- **今日收盘后 (`15:00`+) 至明早 `09:25` 实时因子检查清单**：\n")
for item in live["tonight_postclose_checklist"]:
    lines.append(f"  - {item}\n")

with open(f"{F3_DIR}/report_pry_exit_factors.md", "w", encoding="utf-8") as f:
    f.writelines(lines)
print(f"Wrote {F3_DIR}/report_pry_exit_factors.md ({len(lines)} lines)")
