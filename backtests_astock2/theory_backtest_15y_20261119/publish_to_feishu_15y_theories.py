#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Auto-Publish: 20261119 A股15年知名投资理论实证大回测与TEI动态有效度指数 -> 飞书知识库
Parent Node: Jxarwc3wliQZCakXO1xccPmrnCc (Claude/Argon 因子挖掘、回测)
Strict Compliance: audit_doc_strict_v191 + verify_document_v191 (黄底高亮、零违规标点、单句<=40字、双图+四表)
"""
import os, sys, json, time, fcntl

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/theory_backtest_15y_20261119"
FS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
sys.path.insert(0, FS_DIR)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from build_master_docs import (
    make_text_run, make_para_block, make_bullet_block, make_blank_line
)

PARENT_NODE = "Jxarwc3wliQZCakXO1xccPmrnCc"
TITLE = "20261119 A股15年知名投资理论实证大回测与TEI有效度指数"


def fmt_pct(x):
    if x is None:
        return "无"
    return f"+{x:.2f}%" if x >= 0 else f"{x:.2f}%"


def fmt_num(x):
    if x is None:
        return "无"
    return f"+{x:.1f}" if x > 0 else f"{x:.1f}"


def build_payload():
    m = json.load(open(f"{OUT_DIR}/master_15y_theory_audit.json", encoding="utf-8"))
    lb = m["leaderboard"]

    blocks = []
    # Paragraph 1: First-sentence yellow-highlighted master conclusion (strict <= 40 chars per sentence)
    blocks.append(make_para_block([
        make_text_run("结论：A股15年真正有效的是本土风格而非宏观周期与玄学指标。", background_color=3),
        make_text_run("小市值与大盘低波双雄领先，涛动周期论与动量追强为反向指标。", background_color=3),
        make_text_run("检验覆盖 2011.01 至 2026.11 共 3855 个交易日。"),
        make_text_run("全量严守时点发布滞后、次日成交、剔一字不可买与实盘换手扣费。"),
        make_text_run("同期沪深300买入持有年化 +1.53%，最大回撤 -46.70%。"),
    ]))

    # Section 1: TEI Indicator Definition
    blocks.append(make_para_block([
        make_text_run("一、理论动态有效度指数（TEI）设计口径", bold=True),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("TEI 满分 100 分，50 分代表与抛硬币或随机持有基准无异。"),
        make_text_run("满 65 分为真有效强超额，55 至 65 分为吃环境饭的条件有效。"),
        make_text_run("45 至 55 分为故事好听但无超额的噪音，低于 45 分为反向失效指标。"),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("四项正交权重：信息比率占 35%，经统计缩水的净超额占 25%。"),
        make_text_run("最大回撤保护改善占 20%，季度样本外胜率一致性占 20%。"),
        make_text_run("按滚动 2 年窗口算时间衰减斜率，并拆分 10 大行业与 6 类环境。"),
    ]))

    # Section 2: What Works vs What Fails
    blocks.append(make_para_block([
        make_text_run("二、三大阵营实证裁决：谁真有用、谁在坑人", bold=True),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("本土风格：小市值 15 年 TEI 64.3 夺冠，净超额 +13.11%。", background_color=3),
        make_text_run("纳入 255 只历史退市股后年化仅降 0.69 点，并非幸存者幻觉。"),
        make_text_run("大蓝筹低波 15 年 TEI 62.3，近 3 年飙至 67.3 领跑全场。", background_color=3),
        make_text_run("20 日超跌反转 TEI 59.2，远胜 60 日动量追强（34.2）。"),
        make_text_run("动量追强年化净超额 -8.41%，A 股本质是反转市但反转正衰减。"),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("宏观周期：周金涛涛动周期论两套实测双双沦为反向指标。", background_color=3),
        make_text_run("库存象限 41.0（-3.06%），40月律 39.7（-3.13%）。"),
        make_text_run("根因在于 A 股永远在主动去库最悲观时抢跑，等确认已走完。"),
        make_text_run("美林轮动 15 年 54.0 但衰减 -11.9 分，2016 后彻底失灵。"),
        make_text_run("宏观派唯一走强的是 M1 与 M2 剪刀差，近 3 年升至 57.2。"),
        make_text_run("股债 ERP 没暴利（+0.31%），但能把最大回撤砍至 -36.25%。"),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("技术玄学：因果波浪拿下 54.9 分，靠牛市拿住和降撤胜出。"),
        make_text_run("大 C 浪 10% 级急跌中，沪深300 有 70% 先走 C4 假反抽再破底。"),
        make_text_run("缠论 15 年仅 48.3，但近 3 年震荡市跳升至 61.3（+17.0）。"),
        make_text_run("经典均线（48.7）与传统 RSI（48.4）长期扣费后跑输基准。"),
        make_text_run("日历魔咒斜率 -8.8 分，五穷六绝变六涨，仅 2 月小盘仍灵。"),
    ]))

    # Section 3: Time, Industry & Regime Drivers
    blocks.append(make_para_block([
        make_text_run("三、随时间、行业与市场环境的切换规律", bold=True),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("三时代切换：11 至 15 散户期是小盘（72.0）与超跌（75.3）天堂。"),
        make_text_run("16 至 20 外资抱团期，小盘（36.7）与反转（32.3）惨遭屠杀。"),
        make_text_run("21 至 26 量化期，大盘低波（76.0）与小盘（70.1）哑铃双强。", background_color=3),
        make_text_run("震荡降波让缠论（68.5）与 RSI（66.2）翻红，宏观日历全面退潮。"),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("行业分化规律：小市值与反转最吃散户密集的传媒（72.5）与科技（67.6）。"),
        make_text_run("大蓝筹低波恰恰相反，只在金融地产（59.3）与公用基建（56.4）最有效。"),
        make_text_run("趋势波浪与均线最吃高弹性大波段的电力新能源（波浪 TEI 达 61.8）。"),
        make_text_run("金融地产是几乎所有技术派与宏观择时的坟墓（波浪 42.6，缠论 32.9）。"),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("环境敏感度：通胀方向决定宏观理论生死，再通胀期 M1M2 升至 61.2。"),
        make_text_run("通缩下行期所有宏观与周期理论集体雪崩，40 月周期律跌至 22.5 分。"),
        make_text_run("单边牛市最容易让择时理论踏空，库存象限牛市 TEI 仅 24.8 分。"),
    ]))

    # Section 4: Validity Duration & Shelf Life
    blocks.append(make_para_block([
        make_text_run("四、理论有效期与半衰期：顺风管多久、死一次套多久", bold=True),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("没有永动机：A 股最强策略单次顺风也仅管 10 至 14 个月。", background_color=3),
        make_text_run("大盘低波最长连赢 48 个月（21.08 至 25.07），也曾连死 30 个月。"),
        make_text_run("小市值有效月占比 66.1% 排第一，单次均管 10.8 月，最长连死 20 月。"),
        make_text_run("波浪与 M1M2 属中波段工具，单次均管 8.2 月，逆风均套 2 年。"),
        make_text_run("日历与情绪择时近 8 年有效时长腰斩，分别曾连续失效 31 与 37 月。"),
        make_text_run("股债ERP仅 24.4% 月份跑赢，最长沉寂 50 月，属极端熊底警报。"),
    ]))

    # Mandatory 3 consecutive blank lines before appendices
    blocks.extend([make_blank_line(), make_blank_line(), make_blank_line()])

    # Tables (strictly <= 5 columns each for clean mobile & desktop Feishu readability)
    tables = []

    # Table 1: Master 16-Theory TEI Leaderboard (strictly 4 columns)
    t1_rows = [[
        [("投资理论与阵营", {"bold": True})],
        [("15Y / 10Y / 3Y TEI", {"bold": True})],
        [("15Y净超额 / 回撤 / 衰减", {"bold": True})],
        [("实证定性", {"bold": True})],
    ]]
    for r in lb:
        tei15 = r["tei_15y"]
        if tei15 >= 60:
            tag = "长期有效"
        elif tei15 >= 54:
            tag = "条件有效"
        elif tei15 >= 46:
            tag = "噪音或看环境"
        else:
            tag = "反向失效"
        if r["display_name"] == "核心资产大盘低波":
            tag = "当下最强主线"
        elif r["display_name"] == "缠论(分型笔背驰)":
            tag = "近3年震荡翻红"
        elif r["display_name"] == "美林时钟(行业轮动)":
            tag = "早期强近年失效"
        t1_rows.append([
            [(f"{r['display_name']}（{r['camp'][:2]}）", {"bold": tei15 >= 60})],
            [(f"{r['tei_15y']:.1f} / {r['tei_10y']:.1f} / {r['tei_3y']:.1f}", {"bold": tei15 >= 60})],
            [(f"{fmt_pct(r['excess_15y'])} / {r['mdd_15y']:.1f}% / {fmt_num(r['decay_decade'])}", {"bold": abs(r["excess_15y"]) >= 5})],
            [(tag, {})],
        ])
    tables.append(("附录表一：A股 15 年 16 套主流投资理论 TEI 综合总榜（基准沪深300）", t1_rows))

    # Table 2: Three-Era Evolution & Regime Sensitivity (strictly 4 columns)
    t2_rows = [[
        [("代表理论", {"bold": True})],
        [("11至15 / 16至20 / 21至26 TEI", {"bold": True})],
        [("最吃环境", {"bold": True})],
        [("最惨环境", {"bold": True})],
    ]]
    for r in lb[:12] + [x for x in lb[12:] if "涛动" in x["display_name"] or "动量" in x["display_name"]]:
        e1 = f"{r['era_11_15']:.1f}" if r["era_11_15"] is not None else "无"
        e2 = f"{r['era_16_20']:.1f}" if r["era_16_20"] is not None else "无"
        e3 = f"{r['era_21_26']:.1f}" if r["era_21_26"] is not None else "无"
        br = r["best_regime"].replace("2011至2015", "11至15").replace("2016至2020", "16至20").replace("2021至2026", "21至26")
        wr = r["worst_regime"].replace("2011至2015", "11至15").replace("2016至2020", "16至20").replace("2021至2026", "21至26")
        t2_rows.append([
            [(r["display_name"], {})],
            [(f"{e1} / {e2} / {e3}", {"bold": (r["era_21_26"] or 0) >= 65})],
            [(br, {})],
            [(wr, {})],
        ])
    tables.append(("附录表二：三大市场时代 TEI 迁移与环境敏感度归因表", t2_rows))

    # Table 3: Industry Applicability Matrix (strictly 4 columns)
    t3_rows = [[
        [("代表理论", {"bold": True})],
        [("科技 / 电新 / 金融 TEI", {"bold": True})],
        [("最佳适用行业", {"bold": True})],
        [("最差失效行业", {"bold": True})],
    ]]
    for r in lb:
        sc = r["industry_scores"]
        t3_rows.append([
            [(r["display_name"], {})],
            [(f"{sc.get('科技电子软件', 50):.1f} / {sc.get('电力新能源', 50):.1f} / {sc.get('金融地产', 50):.1f}", {})],
            [(r["best_ind"], {"bold": True})],
            [(r["worst_ind"], {})],
        ])
    tables.append(("附录表三：10 大行业适用度 TEI 分化对照表", t3_rows))

    # Table 4: C-Wave 4 & Calendar Effect Key Empirical Facts
    t4_rows = [
        [[("专项检验命题", {"bold": True})], [("实证标的与口径", {"bold": True})], [("核心统计结果", {"bold": True})], [("实战含义", {"bold": True})]],
        [[("C浪4假反抽概率(大级别)", {"bold": True})], [("沪深300 10%级大C浪(10次)", {})], [("70.0%先反抽再破底，30%直见底", {"bold": True})], [("大跌首抽忌轻言见大底", {})]],
        [[("C浪4假反抽概率(小级别)", {})], [("沪深300 6%级C浪(24次)", {})], [("37.5%属假反抽(均再下探 -10.02%)", {})], [("小级别止跌胜率高于大级别", {})]],
        [[("春季躁动 2 月效应", {"bold": True})], [("中证500 2019至2026年 2月", {})], [("胜率 100%，月均收益 +6.17%", {"bold": True})], [("唯一未被消灭的强日历规律", {})]],
        [[("五穷六绝七翻身魔咒", {})], [("沪深300 2019至2026年 5至7月", {})], [("6月转正、7月转负，斜率 -8.8 分", {})], [("老日历口诀已失效勿机械套用", {})]],
    ]
    tables.append(("附录表四：波浪 C浪4 与日历魔咒专项实证拆解表", t4_rows))

    # Table 5: Validity Duration & Spell Lengths (strictly 4 columns)
    vd_p = f"{OUT_DIR}/validity_duration_15y.json"
    if os.path.exists(vd_p):
        vd = json.load(open(vd_p, encoding="utf-8"))
        t5_rows = [[
            [("投资理论", {"bold": True})],
            [("有效月占比(前半/后半)", {"bold": True})],
            [("单次均长 / 最长顺风", {"bold": True})],
            [("最长连死期(月)", {"bold": True})],
        ]]
        for vr in vd:
            t5_rows.append([
                [(vr["name"], {"bold": vr["eff_pct"] >= 60})],
                [(f"{vr['eff_pct']:.1f}% ({vr['eff_h1']:.0f}% / {vr['eff_h2']:.0f}%)", {})],
                [(f"{vr['avg_on_m']:.1f}月 / {vr['max_on_m']}月", {"bold": vr["max_on_m"] >= 24})],
                [(f"{vr['max_off_m']}月 ({vr['max_off_span'].replace('-', '.').replace('~', '至')})", {})],
            ])
        tables.append(("附录表五：16 套投资理论真实有效期、单次顺风时长与最长失效期", t5_rows))

    return {
        "title": TITLE,
        "parent_node_token": PARENT_NODE,
        "blocks": blocks,
        "img_path": f"{OUT_DIR}/tei_master_dashboard.png",
        "img_path_2": f"{OUT_DIR}/tei_industry_regime_heatmap.png",
        "tables": tables,
    }


def main():
    d = build_payload()
    # Strict local pre-publish audit (exact v19.1 rules)
    longs = s9.audit_doc_strict_v191(d, require_img=True)
    if longs:
        for item in longs:
            print("LONG SENTENCE:", item)
        raise ValueError("存在超40字长句，拦截发布")
    print("[PASS] Local audit_doc_strict_v191 passed with 0 errors!")

    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        doc_id, node_tok = s9.find_or_create_child_node(PARENT_NODE, TITLE)
        print(f"[*] Target Feishu Wiki Node: node_token={node_tok}, doc_id={doc_id}")
        if doc_id in s6.PROTECTED_DOCS:
            raise RuntimeError(f"Protected doc blocked: {doc_id}")

        done, fail = s6.write_document_payload(doc_id, d["blocks"], d["tables"], d["img_path"])
        if fail > 0:
            raise RuntimeError(f"Write failed for {fail} blocks")
        # Also embed the 2nd chart (10 Industries x 6 Regimes TEI Heatmap) at the bottom
        if os.path.exists(d["img_path_2"]):
            if not s6.insert_image_block(doc_id, d["img_path_2"]):
                raise RuntimeError("Failed to insert 2nd heatmap image")
            done += 1
        time.sleep(1.5)
        v = s9.verify_document_v191(doc_id, TITLE, expected_tables_count=len(d["tables"]), has_img=True)
        wiki_url = f"https://my.feishu.cn/wiki/{node_tok}"

        # Register into feishu_master_manifest.json
        mf = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        mf.setdefault("nodes", {})["theory_backtest_15y"] = {
            "title": TITLE,
            "node_token": node_tok,
            "obj_token": doc_id,
            "parent_node_token": PARENT_NODE,
            "wiki_url": wiki_url,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        json.dump(mf, open(s6.MANIFEST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"[SUCCESS] Published & verified! URL={wiki_url} | blocks={v['blocks_count']} | tables={v['tables_count']} | images={v['images_count']}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
