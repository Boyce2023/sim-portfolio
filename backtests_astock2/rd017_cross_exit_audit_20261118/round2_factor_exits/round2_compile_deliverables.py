#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
round2_compile_deliverables.py — 汇总第二轮全量 IS/OOS 实证 JSON 并生成 PM 报告
"""
import os, json
from datetime import datetime

ROOT = "/Users/huaichuaibeimeng/claude-projects"
RD2_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd017_cross_exit_audit_20261118/round2_factor_exits"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/exit_factors_v2_20261118"


def load_j(fn):
    with open(f"{RD2_DIR}/{fn}", "r", encoding="utf-8") as f:
        return json.load(f)


def fmt_uni_status(a, b):
    if a["n_trig"] == 0 and b["n_trig"] == 0:
        return "零触发"
    if b["delta_bps"] > 0:
        return "IS宽池偏正(需OOS检验)"
    if a["delta_bps"] > 0 and b["delta_bps"] <= 0:
        return "仅小样本偏正/宽池负效"
    return "IS负效/淘汰"


def norm_pry_entry(e):
    return {
        "name": e["name"],
        "pool_435_and_16_1s": e.get("pool_435_and_16_1s") or e.get("pool_435_strict"),
        "pool_830_broad": e["pool_830_broad"],
    }


def main():
    t1 = load_j("round2_task1_2to3.json")
    t2 = load_j("round2_task2_3to4.json")
    t3 = load_j("round2_task3_pry.json")
    rf = load_j("round2_refine.json")

    t1_comp = t1["is_oos_full_comparison"] + [e for e in rf["s_2to3_refine"]["comp"] if e["name"] != "r1_no_imm"]
    t2_comp = t2["is_oos_full_comparison"] + rf["s_3to4_refine"]["comp"]
    t3_comp = [norm_pry_entry(e) for e in (t3["is_oos_full_comparison"] + rf["s_pry_refine"]["comp"])]

    t1_uni = dict(t1["univariate_is_tests"])
    t1_uni["broken_board_immunity_is"] = rf["s_2to3_refine"]["uni_imm"]
    t2_uni = {
        "k_0925_open_cut_hold_days_is": t2["univariate_is_tests"],
        "cond_dev96_and_imm_trade_level_is": rf["s_3to4_refine"]["uni_is_dev_imm"],
    }
    t3_uni = {
        "round2_core_factors_is": t3["univariate_is_tests"],
        "refined_liquid_factors_is": rf["s_pry_refine"]["uni"],
    }

    audit = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "seat": "astock2",
            "cutoff_date": "2026-11-16",
            "fee_roundtrip": 0.0020,
            "pit_guarantee": "strict point-in-time: <= k-1 post-close LHB, < k 09:25 notices & xueqiu, exact k 09:25 open cross-section; 0 future leak; 0 yfinance; SQLite mode=ro",
            "windows": {
                "full_5y": "2021-11-16 ~ 2026-11-16",
                "is_2to3": "2021-01-04 ~ 2023-12-31 (and 2021-11-16 ~ 2023-12-31 canon)",
                "is_3to4_pry": "2022-01-04 ~ 2023-12-31",
                "oos_24_26": "2024-01-01 ~ 2026-11-16",
                "y25_26_reg": "2025-01-01 ~ 2026-11-16",
                "y2026_1y": "2026-01-01 ~ 2026-11-16",
            },
        },
        "s_2to3_factor_exit": {
            "univariate_is_tests": t1_uni,
            "composite_scorecard_rules": [
                {
                    "id": "r1_no_imm",
                    "description": "取消1次破板真阳免死, 不叠加D4 09:25对手盘一刀切或10:30收紧",
                    "is_validation_status": "PASS (IS std90: N=7, +24.85% -> +28.29%, +344bps, 5/7 improved; ISf 27.88x -> 31.74x)",
                    "oos_validation_status": "PASS (OOS 12.34x -> 15.50x; S96 17.43x -> 20.41x)",
                },
                {
                    "id": "r2_cond_v51_imm",
                    "description": "用高标V5.1 6因子给14:55真阳免死加条件豁免",
                    "is_validation_status": "WEAKER (+117bps vs +344bps, ISf 27.52x < 31.74x)",
                    "oos_validation_status": "REJECTED (OOS 13.90x < 15.50x; EQ 107.82x < 138.64x)",
                },
                {
                    "id": "d4_open_cuts_and_3to4_referee",
                    "description": "D4 09:25三进四不达标/游资/拉萨/监管/队友核按钮一刀切与10:30收紧",
                    "is_validation_status": "REJECTED (IS std90 -442bps ~ -3315bps; wide75 -101bps ~ -1130bps; d3_to>31虽IS偏正+107bps但OOS失效15.50x->13.31x)",
                    "oos_validation_status": "REJECTED (5Y 1S drops from 203.38x to 78.58x~201.24x)",
                },
            ],
            "is_oos_full_comparison": t1_comp,
            "verdict": "NEGATIVE_ON_D4_COUNTERPARTY_CUT_KEEP_R1_NO_IMM",
            "recommended_dynamic_exit": "r1_no_imm (维持全取消1次破板真阳免死; 零新增参数, 禁止在D4 09:25用三进四打分卡/龙虎榜/公告硬砍三板封死仓位)",
        },
        "s_3to4_factor_exit": {
            "univariate_is_tests": t2_uni,
            "composite_scorecard_rules": [
                {
                    "id": "r2_cond_dev96_risk2",
                    "description": "持仓动态整数风控分>=2时当日盘前挂96%双严重异动缓冲限价单: s_reg/tox(+2) + ex_reg5>=2(+1) + lhasa_any(+1) + surf_yz(+1) + top_yz_dump(+1) + xq_ov>=4(+1), >=2分触发",
                    "is_validation_status": "PASS_WIDE_IS (wide75 N=5, +23.93% -> +24.73%, +79bps, 3/5 improved; std90 IS 4.25x vs base 4.75x)",
                    "oos_validation_status": "STRONG_ON_S90_1S (5Y 2230.51x vs 1799.99x, OOS 524.35x vs 379.08x, T5 178.59x vs 105.82x; EQ 4331.89x vs 4458.94x; S102 10.19x vs 16.72x)",
                },
                {
                    "id": "r2_cond_dev96_k6_reglhxq",
                    "description": "仅在k_rel>=2(6板及以上)且累计监管/拉萨或当日雪球>=8/一日游时挂96%双严重异动缓冲限价单",
                    "is_validation_status": "PASS_WIDE_IS (wide75 N=7, +24.35% -> +26.71%, +236bps, 5/7 improved; std90 IS 4.26x)",
                    "oos_validation_status": "STRONG_T5_PROTECTION (5Y 1918.53x, OOS 450.79x, T5 209.72x vs 105.82x; S102 9.04x vs 16.72x)",
                },
                {
                    "id": "r2_cond_dev96_reglhxq_non102_posthoc_hypothesis",
                    "description": "分档假说: strict102(>=102分)不封顶保留合富中国/艾艾精工, 90~101分挂条件96%双严重异动单",
                    "is_validation_status": "IS_DIP (IS 3.75x < 4.75x)",
                    "oos_validation_status": "POST_HOC_OOS_OBSERVATION_ONLY (OOS 949.50x, EQ 7963.64x, S102 16.72x; 事后归因于OOS仅2只S102妖股, 严禁当作已锁IS规则)",
                },
                {
                    "id": "always_imm_and_0925_hard_cuts",
                    "description": "09:25硬砍规则与取消/收紧14:55真阳免死",
                    "is_validation_status": "09:25_CUT_REJECTED (IS std90 -92bps ~ -1185bps; peers_nuke EQ drops 4458.94x -> 4169.90x)",
                    "oos_validation_status": "IMM_CUT_REJECTED (取消或V5.1收紧免死使OOS从379.08x暴跌至277.30x, 误杀合富中国-75.16%)",
                },
            ],
            "is_oos_full_comparison": t2_comp,
            "verdict": "CONDITIONAL_DEV96_RISK2_OR_K6_FOR_STD90_TAIL_ROBUSTNESS_NO_CAP_ON_S102",
            "recommended_dynamic_exit": "保留1次真阳免死且禁止09:25硬砍; S102严格档维持原V4.0不设96%上限(16.72x); S90标准档若优先追求极值剥离稳健性(T5翻倍至178~210x), 推荐用r2_cond_dev96_risk2或r2_cond_dev96_k6_reglhxq(全信号EQ微让渡约3%, 换取单仓5Y 2230.51x与T5 178.59x~209.72x)",
        },
        "s_pry_factor_exit": {
            "univariate_is_tests": t3_uni,
            "composite_scorecard_rules": [
                {
                    "id": "r1_h3_t1m2_imm1",
                    "description": "Round 1 基准: T+1<-2%止损 + 涨停接力(含1次真阳免死) + 非涨停T+3",
                    "is_validation_status": "BASELINE (435 1S IS=1.547x, EQ435=4.116x, 830 EQ=1.046x)",
                    "oos_validation_status": "BASELINE (435 1S 5Y=2.222x, OOS=1.436x, 26=1.099x)",
                },
                {
                    "id": "r2_h3_divcut_only",
                    "description": "仅当昨日1B今开>=0%且本股T+1低开<-1.5%时于09:25走(弱分歧加严)",
                    "is_validation_status": "FAIL_BROAD_IS (830 IS n=11, -262bps)",
                    "oos_validation_status": "MIXED (EQ435 4.116x->4.355x, 830_EQ 1.046x->1.349x; 但435_1S 2.222x->2.088x, Top1 5.228x->4.115x)",
                },
                {
                    "id": "r2_h3_zt_referees_and_dt15",
                    "description": "一进二V19接力裁判/跌停>=15冰点砍仓/T0龙虎榜加仓延期",
                    "is_validation_status": "REJECTED (dt15 830 IS -774bps; zt_all -306bps; zt_weak_noimm 830 IS -426bps; 夜间公告与极端冰点IS样本为0)",
                    "oos_validation_status": "REJECTED (cut_1to2_weak使435_1S跌至1.848x; dt15跌至1.693x)",
                },
            ],
            "is_oos_full_comparison": t3_comp,
            "verdict": "NEGATIVE_KEEP_ROUND1_STATIC_PLUS_ZT_RELAY",
            "recommended_dynamic_exit": "维持r1_h3_t1m2_imm1(或偏胜率h=2 imm=0: 2.291x/WR=81.2%); 严禁对超跌撬板加情绪冰点跌停砍仓或用一进二标准在次日09:25砍反弹首板",
        },
        "overall_summary_for_pm": {
            "core_conclusion": "动态持仓因子在三策略呈现清晰分化: 仅s_3to4(std90)的条件96%双严重异动限价单(risk2/k6)在宽池IS正效且OOS把T5稳健净值翻倍(105.82x->178.59x~209.72x); s_2to3所有D4 09:25对手盘一刀切均负贡献(-250~-3315bps), 应坚持r1_no_imm; s_pry所有盘后/09:25动态砍仓与一进二裁判均不增厚435单仓主线, 应维持Round 1机制。",
            "anti_overfit_audit": "所有规则先经IS单因子边际bps+胜率筛选, 明确标注wide75统计功效池与S102分档事后假说边界, 零IS负效规则硬推OOS。",
        },
    }

    with open(f"{OUT_DIR}/rd_factor_exit_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    def pick(lst, names):
        mp = {x["name"]: x for x in lst}
        return [mp[n] for n in names if n in mp]

    md = []
    md.append("# A股二号席 (`astock2`) 第二轮持仓动态因子与跨板位裁判实证报告")
    md.append("")
    md.append("**总结论：跨板位动态因子只有一条线通过「IS 单因子正向 + OOS 真实增厚」硬检验，其余多数 09:25 硬砍反噬收益。** ① `s_2to3` 彻底否定在 `D4 09:25` 用 `3to4` 打分卡、龙虎榜、公告或队友核按钮硬砍三板封死仓（IS `std90` 均亏 `442bps` 至 `3315bps`），唯一有效升级仍是 Round 1 的「全取消 1 次破板真阳免死（`r1_no_imm`）」；② `s_3to4` 在 `S90` 必须保留真阳免死且禁止 `09:25` 硬砍，而**条件触发 96% 双严重异动限价单（`r2_cond_dev96_risk2` 或 `r2_cond_dev96_k6_reglhxq`）** 在 `wide75` IS 为正（`+79bps` / `+236bps`），OOS 单仓 `5Y` 升至 `2230.51x` / `1918.53x`（基线 `1799.99x`）且 `T5` 几乎翻倍（`178.59x` / `209.72x` vs `105.82x`），但 `strict102` 必须不设 96% 上限以保住高分超级龙头（`16.72x` vs `9.04x~10.19x`）；③ `s_pry` 所有夜间公告、情绪冰点跌停砍仓与 `1to2` 反弹首板裁判均不增厚 `435` 单仓，应维持 Round 1 的 `T+1<-2% + 涨停接力 + 非涨停 T+3/T+2`。")
    md.append("")
    md.append("## 一、口径与 PIT 防伪说明")
    md.append("1. 数据截断至 `2026-11-16`，双边交易成本千二（`0.20%`），所有 SQLite 只读连接且零 `yfinance` 调用。")
    md.append("2. 持仓第 `k` 日 `09:25` 决策只读取 `<= k-1` 日盘后龙虎榜（含机构与游资席位明细）、`< k 09:25:00` 监管/毒性/异动公告与雪球帖数、以及 `k 09:25` 当下同题材队友与市场开盘截面。")
    md.append("3. 关键统计发现：`xueqiu_guba_5y_pit.db` 在 2022 至 2023 年全市场仅约 `7.5k~8.4k` 条/年，而 2025 至 2026 年升至 `2.65万~6.12万` 条/年；`s_pry`（435 严池）5 年全期 T+0 龙虎榜坏席位仅 5 笔、持仓期监管公告仅 2 笔、极端冰点（`09:25` 涨停<5 且昨首板均开<-1%）0 笔。为避免样本稀疏幻觉，所有单因子检验均同步在宽池（`2to3/3to4` `score>=75`，`pry` `830` 宽池）验证统计功效。")
    md.append("")

    md.append("## 二、任务一：`s_2to3`（二进三 V2.0）IS/OOS 实证结果")
    md.append("### 1. IS 单因子检验（2021 至 2023，D4 09:25 提前砍仓 vs `r1_no_imm` 持有）")
    md.append("| 分组 | 因子 | std90 N | std90 边际 (`base->cut`) | wide75 N | wide75 边际 (`base->cut`) | 判定 |")
    md.append("|---|---|---|---|---|---|---|")
    for grp, lst in [("sealed_3B", t1["univariate_is_tests"]["sealed_3b_d4_open_cut"]), ("unsealed_3B", t1["univariate_is_tests"]["unsealed_3b_d4_open_cut"])]:
        for x in lst:
            a, b = x["is_std90"], x["is_wide75"]
            md.append(f"| {grp} | `{x['factor']}` | {a['n_trig']} | {a['base_mean_pct']:+.2f}%->{a['alt_mean_pct']:+.2f}% ({a['delta_bps']:+.0f}bps) | {b['n_trig']} | {b['base_mean_pct']:+.2f}%->{b['alt_mean_pct']:+.2f}% ({b['delta_bps']:+.0f}bps) | {fmt_uni_status(a, b)} |")
    for k, v in rf["s_2to3_refine"]["uni_imm"].items():
        md.append(f"| broken_board | `{k}` | {v['n_trig']} | {v['base_mean_pct']:+.2f}%->{v['alt_mean_pct']:+.2f}% ({v['delta_bps']:+.0f}bps, +{v.get('improved_trades',0)}/-{v.get('hurt_trades',0)}) | 同左 | 同左 | {'通过' if 'cancel_imm_std90' in k else '较弱'} |")
    md.append("")
    md.append("核心物理机制：三板封死股即便在 `D4 09:25` 不符合三进四买点（`f_3to4_sc_lt85`），早盘仍自带冲高溢价；直接按 `09:25` 竞价卖出会主动放弃原有 `13:45 破5%` 护利机制的日内高点，导致 IS 平均少赚 `946bps`（wide75 少赚 `257bps`）。甚至仅把 `D4` 收紧到 `10:30 < VWAP`（`r2_noimm_d4tighten_3to4_lt85`），5 年单仓仍从 `203.38x` 降至 `182.81x`。`D3` 高换手 `>31%` 虽在 IS 偏正，但在盲测 OOS 从 `15.50x` 跌至 `13.31x`。")
    md.append("")
    md.append("### 2. `s_2to3` IS 与盲测 OOS 双轨全指标对比（`std90` 与 `strict96`）")
    md.append("| 方案 | 5Y单仓 (WR/PLR/T3/MDD/Ex) | IS_full单仓 | OOS单仓 (Ex) | 2026单仓 | 5Y日等权 | S96 5Y/OOS |")
    md.append("|---|---|---|---|---|---|---|")
    for e in pick(t1_comp, ["baseline_v20", "r1_no_imm", "r2_cond_v51_imm", "r2_noimm_d4cut_3to4_lt85", "r2_noimm_d4cut_reg_or_lhasa", "r2_noimm_d4cut_to_gt31", "r2_noimm_d4tighten_3to4_lt85", "r2_noimm_unsealed_toxic2"]):
        s90, s96 = e["std90"], e["strict96"]
        f5, isf, oo, y26 = s90["full_5y"]["single_slot"], s90["is_21_23_full"]["single_slot"], s90["oos_24_26"]["single_slot"], s90["y2026_1y"]["single_slot"]
        eq5 = s90["full_5y"]["daily_eq"]
        md.append(f"| `{e['name']}` | {f5['nav']:.2f}x ({f5['wr_pct']:.1f}%/{f5['plr']:.2f}/{f5['trim3_nav']:.2f}x/{f5['mdd_pct']:.1f}%/{f5['excess_pp']:+.1f}pp) | {isf['nav']:.2f}x | {oo['nav']:.2f}x ({oo['excess_pp']:+.1f}pp) | {y26['nav']:.2f}x | {eq5['nav']:.2f}x | {s96['full_5y']['single_slot']['nav']:.2f}x / {s96['oos_24_26']['single_slot']['nav']:.2f}x |")
    md.append("")

    md.append("## 三、任务二：`s_3to4`（三进四 V4.0）IS/OOS 实证结果")
    md.append("### 1. IS 单因子检验（2022 至 2023：区分 `09:25` 硬砍 vs 条件 96% 双严重异动挂单）")
    md.append("1. **`09:25` 直接硬砍全线负效**：在 IS `std90`（`61` 个涨停持仓观察日）上，拉萨>=3（`-775bps`）、一日游（`-301bps`）、顶级游资砸盘（`-1185bps`）、个股/交易所监管（`-130bps` 至 `-947bps`）与队友核按钮（`-250bps`）均值全部为负；`r2_cut_peers_nuke` 虽在 OOS 单仓偶得 `409.34x`，但 IS 跌至 `4.45x` 且全信号等权 `EQ` 从 `4458.94x` 跌至 `4169.90x`，属单仓槽位轮动噪音。")
    md.append("2. **`14:55` 真阳免死不可取消**：IS 上虽偶见 `+493bps`（2 笔），但在 OOS 直接将 `603122 合富中国` 从 `+148.46%` 砍半至 `+73.29%`，令 OOS 单仓从 `379.08x` 暴跌至 `277.30x`。")
    md.append("3. **条件 96% 双严重异动限价单（`cond_dev96`）在宽池 IS 呈稳定正效**：")
    md.append("")
    md.append("| 条件 `dev96` / `imm` 变体 | IS std90 N | IS std90 边际 (+/-/bps) | IS wide75 N | IS wide75 边际 (+/-/bps) | IS判定 |")
    md.append("|---|---|---|---|---|---|")
    for k, v in rf["s_3to4_refine"]["uni_is_dev_imm"].items():
        a, b = v["is_std90"], v["is_wide75"]
        md.append(f"| `{k}` | {a['n_trig']} | {a['base_mean_pct']:+.2f}%->{a['alt_mean_pct']:+.2f}% (+{a.get('improved_trades',0)}/-{a.get('hurt_trades',0)}, {a['delta_bps']:+.0f}bps) | {b['n_trig']} | {b['base_mean_pct']:+.2f}%->{b['alt_mean_pct']:+.2f}% (+{b.get('improved_trades',0)}/-{b.get('hurt_trades',0)}, {b['delta_bps']:+.0f}bps) | {'宽池正效' if b['delta_bps']>0 else '淘汰'} |")
    md.append("")
    md.append("### 2. `s_3to4` IS 与盲测 OOS 双轨全指标对比（含 2025 至 2026 严监管期与 S102）")
    md.append("| 方案 | 5Y单仓 (WR/PLR/MDD/T5) | IS单仓 | OOS单仓 (Ex) | 25~26单仓 | 2026单仓 | 5Y日等权 | S102 5Y/OOS |")
    md.append("|---|---|---|---|---|---|---|---|")
    for e in pick(t2_comp, ["baseline_v40", "r1_always_dev96_5b", "r2_cond_dev96_risk2", "r2_cond_dev96_k6_reglhxq", "r2_cond_dev96_reg_lhasa_xq", "r2_cond_dev96_reg_only", "r2_cond_dev96_reglhxq_non102", "r2_cut_peers_nuke", "r2_no_imm"]):
        s90, s102 = e["std90"], e["strict102"]
        f5, is_, oo, y25, y26 = s90["full_5y"]["single_slot"], s90["is_22_23"]["single_slot"], s90["oos_24_26"]["single_slot"], s90["y25_26_reg"]["single_slot"], s90["y2026_1y"]["single_slot"]
        eq5 = s90["full_5y"]["daily_eq"]
        md.append(f"| `{e['name']}` | {f5['nav']:.2f}x ({f5['wr_pct']:.1f}%/{f5['plr']:.2f}/{f5['mdd_pct']:.1f}%/T5={f5['trim5_nav']:.2f}x) | {is_['nav']:.2f}x | {oo['nav']:.2f}x ({oo['excess_pp']:+.1f}pp) | {y25['nav']:.2f}x | {y26['nav']:.2f}x | {eq5['nav']:.2f}x | {s102['full_5y']['single_slot']['nav']:.2f}x / {s102['oos_24_26']['single_slot']['nav']:.2f}x |")
    md.append("")
    md.append("诚实风控权衡：在 `std90` OOS 共 19 笔触及 `cond_dev96_reglhxq` 的交易里，多达 `14` 笔显著改善（如杭齿前进 `+22.78%`、园林股份 `+17.88%`、梦网科技 `+14.97%`、山东墨龙 `+12.98%`、漳州发展 `+10.35%`、中毅达 `+10.25%`），唯一大幅回吐来自 `S102` 超级龙头 `合富中国`（`108` 分，`+148.46%->+36.13%`）与 `艾艾精工`（`103` 分，`+123.55%->+89.95%`）。因此：`strict102` 必须不加 96% 上限；`std90` 若以 **去前 5 极值稳健复合净值（`T5`）** 与 **2025 至 2026 严监管期防护** 为先，IS 锁定的整数风控分 `r2_cond_dev96_risk2`（`5Y=2230.51x, OOS=524.35x, T5=178.59x, EQ=4331.89x`）与 `r2_cond_dev96_k6_reglhxq`（`T5=209.72x`）均全面优于 Round 1 无差别挂单 `r1_always_dev96_5b`（`EQ 3736.44x, S102 6.53x`）。至于 `r2_cond_dev96_reglhxq_non102`（`S90 3555.92x`）严正标为「OOS 事后归因假说」，不得当作 IS 锁定结果直接上线。")
    md.append("")

    md.append("## 四、任务三：`s_pry`（超跌撬板 V1.0）IS/OOS 实证结果")
    md.append("### 1. IS 单因子检验（`435` 严池 15 笔与 `830` 宽池 138 笔）")
    md.append("| 因子 | 435 IS (N/边际bps) | 830 IS (N/边际bps) | 结论 |")
    md.append("|---|---|---|---|")
    for x in t3["univariate_is_tests"]:
        a, b = x["is_435_pool"], x["is_830_pool"]
        md.append(f"| `{x['factor']}` | n={a['n_trig']} ({a['delta_bps']:+.0f}bps) | n={b['n_trig']} ({b['delta_bps']:+.0f}bps) | {fmt_uni_status(a, b)} |")
    for x in rf["s_pry_refine"]["uni"]:
        a, b = x["is_435"], x["is_830"]
        md.append(f"| `{x['factor']}` | n={a['n_trig']} ({a['delta_bps']:+.0f}bps) | n={b['n_trig']} ({b['delta_bps']:+.0f}bps) | {fmt_uni_status(a, b)} |")
    md.append("")
    md.append("### 2. `s_pry` IS 与盲测 OOS 双轨全指标对比")
    md.append("| 方案 | 435单仓 5Y (WR/PLR/MDD/Ex) | 435单仓 IS / OOS / 2026 | 435全信号EQ | Top1 EQ | 830宽池EQ (IS/OOS) |")
    md.append("|---|---|---|---|---|---|")
    for e in pick(t3_comp, ["r1_h3_t1m2_imm1", "r1_h2_t1m2_imm0", "r2_h3_divcut_only", "r2_h3_zt_weak1to2_noimm", "r2_h3_zt_cut_1to2_weak", "r2_h3_dt15_cut", "r2_h3_night_notice_cut"]):
        p4, p8 = e["pool_435_and_16_1s"], e["pool_830_broad"]
        f5, is_, oo, y26 = p4["full_5y"]["single_slot"], p4["is_22_23"]["single_slot"], p4["oos_24_26"]["single_slot"], p4["y2026_1y"]["single_slot"]
        eq4, t1_ = p4["full_5y"]["daily_eq_all"], p4["full_5y"]["daily_top1_eq"]
        md.append(f"| `{e['name']}` | {f5['nav']:.3f}x ({f5['wr_pct']:.1f}%/{f5['plr']:.2f}/{f5['mdd_pct']:.1f}%/{f5['excess_pp']:+.1f}pp) | {is_['nav']:.3f}x / {oo['nav']:.3f}x / {y26['nav']:.3f}x | {eq4['nav']:.3f}x | {t1_['nav']:.3f}x | {p8['full_5y']['daily_eq_all']['nav']:.3f}x ({p8['is_22_23']['daily_eq_all']['nav']:.2f}/{p8['oos_24_26']['daily_eq_all']['nav']:.2f}) |")
    md.append("")
    md.append("核心结论：`s_pry` 买的是极度超跌后的恐慌反抽，在 `09:25` 跌停家数>=15 时砍仓等同于砍在地板上（`830 IS -774bps`），用 `1to2` 严格框架次日早上砍掉反弹涨停股同样损失二板溢价（`830 IS -306bps`）。维持 Round 1 的静态时间窗口 + 涨停接力（`r1_h3_t1m2_imm1` 或 `r1_h2_t1m2_imm0`）即是最优解。")

    with open(f"{OUT_DIR}/RD_FACTOR_EXIT_REPORT.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    print("Compiled deliverables cleanly!")
    print("JSON size:", os.path.getsize(f"{OUT_DIR}/rd_factor_exit_audit.json"))
    print("MD size:", os.path.getsize(f"{OUT_DIR}/RD_FACTOR_EXIT_REPORT.md"))


if __name__ == "__main__":
    main()
