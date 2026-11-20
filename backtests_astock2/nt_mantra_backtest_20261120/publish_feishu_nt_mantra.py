#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Auto-Publish: 20261120 大哥护盘五句口诀十年实证回测 -> 飞书知识库
Parent Node: Jxarwc3wliQZCakXO1xccPmrnCc (Claude/Argon 因子挖掘、回测)
Strict Compliance: audit_doc_strict_v191 + verify_document_v191
"""
import os
import sys
import json
import time
import fcntl
import argparse

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/nt_mantra_backtest_20261120"
FS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
sys.path.insert(0, FS_DIR)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_bullet_block,
    make_ordered_block,
    make_blank_line,
)

PARENT_NODE = "Jxarwc3wliQZCakXO1xccPmrnCc"
TITLE = "20261120 大哥护盘五句口诀十年实证回测"


def build_payload():
    blocks = []

    # Paragraph 1: Master conclusion first + yellow highlights (every sentence <= 40 chars)
    blocks.append(make_para_block([
        make_text_run("结论：五句口诀全套照搬没用，十年年化仅 -0.38% 跑输基准。", background_color=3),
        make_text_run("唯有吃瓜避坑与宽基爆量真有用，其余三句均须改写。", background_color=3),
        make_text_run("剔除毒药二和五后，纯爆量单仓十年 +89.4%，TEI 达 62.1。", background_color=3),
        make_text_run("主回测覆盖 2017.01 至 2026.11 共 2388 日。"),
        make_text_run("另设 2011.01 至 2026.11 共 3856 日纯 ETF 对照。"),
        make_text_run("全量严守无未来量比、开盘尾盘双口径与双边 0.30% 成本。"),
    ]))

    # Section 1: Data & Anti-Leakage Spec
    blocks.append(make_para_block([
        make_text_run("一、实证口径、语境划分与混杂变量排查", bold=True),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("量比基准全部采用前移一日的过去 20 日中位数，杜绝当日泄漏。"),
        make_text_run("弱势期定义为沪深300低于 20 日均线或 20 日回撤满 3.0%。"),
        make_text_run("所有信号同步核查盘后净申购金额，防止只换手不真买。"),
        make_text_run("组合同时对照满仓沪深300与等仓位基准，剔除低仓假象。"),
    ]))

    # Section 2: Sentence-by-sentence Verdict
    blocks.append(make_para_block([
        make_text_run("二、五句口诀逐句实证裁决：两真三伪", bold=True),
    ]))
    blocks.append(make_ordered_block([
        make_text_run("一句「大哥脉冲我吃瓜」真有效：无量拉升是大哥没买。", bold=True),
        make_text_run("弱势脉冲但宽基量比低于 1.2 倍共 231 次，净申购均值 -1.8亿。", background_color=3),
        make_text_run("沪深300后续 5 日均值 -0.04%，20 日均值 -0.47%。"),
        make_text_run("20 日胜率仅 46.1%。十五年 420 次同样 20 日 -0.57%。"),
    ], seq="1"))
    blocks.append(make_ordered_block([
        make_text_run("二句「大哥放量我底仓」伪信号：温和托盘最易挨套。", bold=True),
        make_text_run("脉冲且放量 1.2 至 2.0 倍共 110 次，净申购均 +44.6亿。", background_color=3),
        make_text_run("虽然证实大哥真买，但次日与 5 日均值仅 -0.25% 与 -0.20%。"),
        make_text_run("20 日胜率低至 39.6%，净申购超 10亿组胜率仅 35.7%。", background_color=3),
        make_text_run("十五年 185 次均值仅 +0.02%，温和买盘顶不住抛压。"),
    ], seq="auto"))
    blocks.append(make_ordered_block([
        make_text_run("三句「大哥爆量我三成」全场唯一真有效信号。", bold=True),
        make_text_run("弱势期宽基爆量达 2.0 倍共 44 次，当日均现 -1.00% 急杀出清。", background_color=3),
        make_text_run("尾盘买入 5 日均值 +1.13%。20 日均值 +3.45%，胜率 78.0%。", background_color=3),
        make_text_run("叠日内脉冲双信号 23 次，20 日均值飙至 +4.97%，胜率 90.0%。"),
        make_text_run("同期买中证500弹性更大，20 日达 +5.26%，双信号达 +7.34%。"),
        make_text_run("多只宽基合力显著强于单拉 510300，后者 20 日仅 +1.60%。"),
        make_text_run("2026年1月曾现单日 -1455亿赎回爆量，正净申购过滤可完美避开。", background_color=3),
    ], seq="auto"))
    blocks.append(make_ordered_block([
        make_text_run("四句「期现联动我半仓」属加仓陷阱，并非加强信号。", bold=True),
        make_text_run("宽基 1.8 倍且期货 1.5 倍共 17 次，剔除三周五交割日剩 15 次。"),
        make_text_run("剔交割后 20 日均值由 +1.56% 升至 +1.86%，仅 8 波独立样本。"),
        make_text_run("次日开盘追入 5 日跌回 -0.48%，期货爆量多为恐慌对冲踩踏。", background_color=3),
        make_text_run("对比单宽基开盘 5 日 +0.96%，加期货半仓反增组合最大回撤。"),
    ], seq="auto"))
    blocks.append(make_ordered_block([
        make_text_run("五句「远古巨阳我减仓」一刀清错杀大底，须看资金续买。", bold=True),
        make_text_run("护盘后大阳共 31 次，剔除 924 三连阳后 5 日均值 -0.90%。"),
        make_text_run("2018 熊市反抽大阳后 5 日均值 -2.37%，弱势反抽确该止盈。"),
        make_text_run("但一刀清在 2024.09.24 卖飞 +17.09%。24.02.06 卖飞 +7.87%。", background_color=3),
        make_text_run("盘后净申购鉴别：仍买超 50亿组 5 日 +4.36%，未续买组 -1.15%。", background_color=3),
    ], seq="auto"))

    # Section 3: Portfolio Simulation & Ablation
    blocks.append(make_para_block([
        make_text_run("三、十年与十五年合体仓位仿真及消融对照", bold=True),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("原教旨五句合体十年 -3.7%，年化 -0.38%，回撤 -11.73%。", background_color=3),
        make_text_run("跑输 8.4% 等仓基准 -0.66%。信息比率 -0.25，TEI 仅 43.4。"),
        make_text_run("十五年纯 ETF 原教旨同样负超额，年化 -0.45%，TEI 仅 43.6。"),
        make_text_run("改良巨阳减半留底版仍被二句假底仓拖累，十年年化仅 -0.04%。"),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("去二去五后，纯爆量 30% 仓持 20 日十年 +22.2%，回撤 -3.36%。", background_color=3),
        make_text_run("跑赢同仓位基准 +1.86%，信息比率 +0.76，TEI 跃升至 60.8。", background_color=3),
        make_text_run("100% 单仓尾盘版十年 +89.4%。年化 +6.69%，回撤 -10.99%。", background_color=3),
        make_text_run("次日开盘加正净申购版 +86.3%。TEI 60.4，近三年超额 +13.66%。"),
        make_text_run("剔除 924 或去前五极值日，纯爆量版仍保持 +3.47% 以上超额。"),
        make_text_run("十五年正申购开盘年化 +1.13%。等仓超额 +0.98%，TEI 55.6。"),
    ]))

    # Section 4: Latest Status & Actionable Rule
    blocks.append(make_para_block([
        make_text_run("四、2026年11月19日最新状态与实战改版口诀", bold=True),
    ]))
    blocks.append(make_bullet_block([
        make_text_run("11月19日沪深300拉 +1.18%。宽基量比 1.77 倍，净申购 +520.4亿。"),
        make_text_run("按老口诀算二句底仓，但实证表明未满 2.0 倍前不应盲目重仓抄底。"),
        make_text_run("实战新准则：脉冲无量吃瓜，温和放量忍住，宽基 2.0 倍配正申购才重手。", background_color=3),
        make_text_run("大阳次日看净申购定去留：大哥停买再减仓，仍在扫货死拿跟随趋势。"),
    ]))

    # Mandatory 3 consecutive blank lines before appendices
    blocks.extend([make_blank_line(), make_blank_line(), make_blank_line()])

    # Tables (strictly <= 4 columns, every cell <= 32 chars, no banned chars)
    tables = []

    # Table 1: Five Mantras Event Study Summary (10Y)
    t1_rows = [
        [
            [("口诀与条件(样本数)", {"bold": True})],
            [("净申购 / 当日均涨", {"bold": True})],
            [("300尾盘 T+5 / T+20", {"bold": True})],
            [("开盘T+20 / 实证裁决", {"bold": True})],
        ],
        [
            [("①脉冲吃瓜 (<1.2x, 231)", {"bold": True})],
            [("-1.8亿 / +0.63%", {})],
            [("-0.04% / -0.47%(46%胜)", {})],
            [("-0.42% / 吃瓜避坑真对", {"bold": True})],
        ],
        [
            [("②放量底仓 (1.2至2x, 110)", {})],
            [("+44.6亿 / +0.84%", {})],
            [("-0.20% / +0.19%(40%胜)", {})],
            [("+0.36% / 伪信号极易套", {})],
        ],
        [
            [("②底仓真买 (>10亿, 73)", {})],
            [("+73.5亿 / +0.86%", {})],
            [("+0.06% / +0.22%(36%胜)", {})],
            [("+0.32% / 托而不举仍跌", {})],
        ],
        [
            [("③弱势爆量 (>=2.0x, 44)", {"bold": True})],
            [("+50.3亿 / -1.00%", {})],
            [("+1.13% / +3.45%(78%胜)", {"bold": True})],
            [("+3.29% / 全场真有效核", {"bold": True})],
        ],
        [
            [("③弱势脉冲+爆量 (23)", {"bold": True})],
            [("+172.4亿 / +0.33%", {})],
            [("+1.52% / +4.97%(90%胜)", {"bold": True})],
            [("+4.80% / 500可达+7.34%", {"bold": True})],
        ],
        [
            [("③爆量+正净申购 (34)", {})],
            [("+189.0亿 / -0.89%", {})],
            [("+0.98% / +3.99%(84%胜)", {"bold": True})],
            [("+3.90% / 滤掉26年赎回", {})],
        ],
        [
            [("③510300单爆 (>=2.5x, 34)", {})],
            [("+26.6亿 / -0.98%", {})],
            [("+0.21% / +1.60%(63%胜)", {})],
            [("+1.76% / 弱于宽基合力", {})],
        ],
    ]
    tables.append(("附录表一：大哥护盘五句口诀十年事件研究实证表（2017.01至2026.11）", t1_rows))

    # Table 2: Confounder Audit (Delivery Day, High Pos, M4 PK, M5 Split)
    t2_rows = [
        [
            [("专项排查与对照分组", {"bold": True})],
            [("样本数(独立波次)", {"bold": True})],
            [("尾盘 T+5 / T+20", {"bold": True})],
            [("次日开盘 T+5 / 核心结论", {"bold": True})],
        ],
        [
            [("④期现双爆 含交割(>=1.8x)", {})],
            [("17 次 (9 波)", {})],
            [("+0.06% / +1.56%(63%胜)", {})],
            [("-0.41% / 含交割噪音", {})],
        ],
        [
            [("④期现双爆 剔三周五交割", {"bold": True})],
            [("15 次 (8 波)", {})],
            [("+0.07% / +1.86%(64%胜)", {})],
            [("-0.48% / 开盘追买吃回踩", {"bold": True})],
        ],
        [
            [("PK: 单宽基爆量 (>=2.0x)", {"bold": True})],
            [("29 次 (21 波)", {})],
            [("+0.92% / +2.81%(70%胜)", {"bold": True})],
            [("+0.96% / 稳胜期现双爆", {"bold": True})],
        ],
        [
            [("③高位连涨爆量 (反面对照)", {})],
            [("21 次 (10 波)", {})],
            [("+1.34% / +1.96%(81%胜)", {})],
            [("+0.48% / 26年赎回成陷阱", {})],
        ],
        [
            [("⑤巨阳 剔924三连阳 (>=2.5%)", {})],
            [("28 次 (22 波)", {})],
            [("-0.90% / -0.23%(50%胜)", {})],
            [("-1.30% / 普通反抽确遇阻", {})],
        ],
        [
            [("⑤巨阳 净申购>=50亿 (真反转)", {"bold": True})],
            [("10 次 (7 波)", {})],
            [("+4.36% / +4.32%(70%胜)", {"bold": True})],
            [("+2.66% / 一刀清卖飞主升", {"bold": True})],
        ],
        [
            [("⑤巨阳 净申购<50亿 (假反抽)", {})],
            [("21 次 (18 波)", {})],
            [("-1.15% / -0.85%(48%胜)", {})],
            [("-1.25% / 无续买真该止盈", {"bold": True})],
        ],
    ]
    tables.append(("附录表二：期现交割日剔除、单宽基对照与巨阳分化排查表", t2_rows))

    # Table 3: Portfolio Simulation D15 + TEI Comparison
    t3_rows = [
        [
            [("组合版本与执行口径", {"bold": True})],
            [("均仓 / 年化 / 回撤", {"bold": True})],
            [("等仓超额 / IR / TEI", {"bold": True})],
            [("近3年超额 / 去924超额", {"bold": True})],
        ],
        [
            [("S1 原教旨五句一刀清(尾盘)", {"bold": True})],
            [("8.4% / -0.38% / -11.7%", {})],
            [("-0.66% / -0.25 / 43.4", {"bold": True})],
            [("-1.30% / -0.54% (失效)", {})],
        ],
        [
            [("S1b 原教旨五句(次日开盘)", {})],
            [("8.4% / -0.33% / -10.5%", {})],
            [("-0.61% / -0.23 / 43.7", {})],
            [("-1.22% / -0.54% (失效)", {})],
        ],
        [
            [("S2 改良巨阳减半留底(尾盘)", {})],
            [("8.8% / -0.04% / -9.5%", {})],
            [("-0.34% / -0.13 / 45.7", {})],
            [("-0.59% / -0.37% (拖累)", {})],
        ],
        [
            [("S5 纯③爆量 30%仓(尾盘)", {"bold": True})],
            [("5.6% / +2.05% / -3.4%", {"bold": True})],
            [("+1.86% / +0.76 / 60.8", {"bold": True})],
            [("+3.64% / +1.14% (真有效)", {"bold": True})],
        ],
        [
            [("S6 纯③+正申购 30%(开盘)", {})],
            [("4.7% / +2.00% / -3.8%", {})],
            [("+1.84% / +0.77 / 60.1", {"bold": True})],
            [("+4.03% / +1.09% (实盘稳)", {})],
        ],
        [
            [("S7 纯③爆量 100%单仓(尾盘)", {"bold": True})],
            [("18.7% / +6.69% / -11.0%", {"bold": True})],
            [("+6.09% / +0.76 / 62.1", {"bold": True})],
            [("+12.33% / +3.64% (跑赢满仓)", {"bold": True})],
        ],
        [
            [("S7b 纯③+正申购 100%(开盘)", {"bold": True})],
            [("15.8% / +6.51% / -12.3%", {"bold": True})],
            [("+5.99% / +0.76 / 60.4", {"bold": True})],
            [("+13.66% / +3.47% (可复现)", {"bold": True})],
        ],
        [
            [("S8 纯③ 30%买中证500(尾盘)", {})],
            [("5.6% / +2.87% / -5.4%", {})],
            [("+2.68% / +0.84 / 61.8", {"bold": True})],
            [("+3.55% / +1.84% (弹性强)", {})],
        ],
        [
            [("15Y 原教旨五句纯ETF(11至26)", {})],
            [("6.9% / -0.45% / -9.9%", {})],
            [("-0.69% / -0.31 / 43.6", {})],
            [("-1.19% / -0.65% (长窗失效)", {})],
        ],
        [
            [("15Y 纯③+正申购 30%(开盘)", {"bold": True})],
            [("4.1% / +1.13% / -8.6%", {})],
            [("+0.98% / +0.38 / 55.6", {"bold": True})],
            [("+4.03% / +0.51% (15年有效)", {"bold": True})],
        ],
    ]
    tables.append(("附录表三：合体仿真与消融实验全指标对比表（扣双边 0.30% 成本）", t3_rows))

    return {
        "title": TITLE,
        "parent_node_token": PARENT_NODE,
        "blocks": blocks,
        "img_path": f"{OUT_DIR}/chart_nt_mantra_audit.png",
        "tables": tables,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    d = build_payload()
    longs = s9.audit_doc_strict_v191(d, require_img=True)
    if longs:
        for item in longs:
            print("LONG SENTENCE:", item)
        raise ValueError("存在超 40 字长句，拒绝发布！")
    print("[PASS] Local audit_doc_strict_v191 passed with 0 errors!")

    if args.dry_run:
        print("[Dry-Run PASS] 本地校验零违规。")
        return

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
        time.sleep(1.5)
        v = s9.verify_document_v191(doc_id, TITLE, expected_tables_count=len(d["tables"]), has_img=True)
        wiki_url = f"https://my.feishu.cn/wiki/{node_tok}"

        mf = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        mf.setdefault("nodes", {})["nt_mantra_10y"] = {
            "title": TITLE,
            "node_token": node_tok,
            "obj_token": doc_id,
            "parent_node_token": PARENT_NODE,
            "wiki_url": wiki_url,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(s6.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(mf, f, ensure_ascii=False, indent=2)
        print(f"[SUCCESS] Published & verified! URL={wiki_url} | blocks={v['blocks_count']} | tables={v['tables_count']} | images={v['images_count']}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
