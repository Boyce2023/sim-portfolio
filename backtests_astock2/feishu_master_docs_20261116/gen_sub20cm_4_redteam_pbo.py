# -*- coding: utf-8 -*-
"""20cm子文档4：20261124 20cm V1.1独立红队攻防与过拟合压力测试"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub20cm_4_redteam_pbo_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "独立红队测试结论：V1.1 瘦身彻底消除过拟合尖峰，全压测通过极有用。",
            background_color=3,
        ),
        make_text_run("本文聚焦 V1.0 病灶排查、18 缩 9 因子纯化与四种架构盲测。"),
        make_text_run("全程带 +0.30% 穿价缓冲与千三滑点，并含 45 只退市 20cm 股。"),
        make_text_run("所有盲测 OOS（样本外）数字严格按实测报告，绝无任何虚报。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("一、诊断 V1.0 过拟合尖峰与 V1.1 瘦身降噪过程", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p2_head))

    o1 = [
        make_text_run("揪出 V1.0 过拟合概率高达七成的四大漂移病灶。", bold=True),
        make_text_run(
            "雪球盘前发帖命中率从 21 年 3.1% 漂至 26 年 14.7%，股吧失灵。",
            background_color=3,
        ),
        make_text_run("开盘啦动态热度漂移致 26 年命中 70.5%，切除后样本外飙升。"),
        make_text_run("静态超 40 亿扣分错杀大票，致 V1.0 S 档 2025 年仅剩 2 笔。"),
        make_text_run("另外 6 项小样本噪音在留一检验中倒扣样本外，一律物理切除。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("V1.1 瘦身为 9 项物理正交因子，过拟合骤降至安全区。", bold=True),
        make_text_run(
            "A 档局部 PBO 由 70% 降至 1.43%，S 档恢复至 199 笔。",
            background_color=3,
        ),
        make_text_run("四种架构盲测对决下，纯深水单轨在样本外与去 924 后全胜其余版。"),
        make_text_run("插入普涨交易平均每笔亏 -1.28% 至 -1.49%，奠定纯单轨架构。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    p3_head = [
        make_text_run("二、极端抗压指标与真实 OOS（样本外）逐年实证", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    b1 = [
        make_text_run("极值、牛市、滑点与流动性四大压力测试全通过。", bold=True),
        make_text_run(
            "S82 六年 468.29 倍，去前五 104.06 倍，去前十 36.63 倍。",
            background_color=3,
        ),
        make_text_run("OOS（样本外）S82仅3.94倍，A76 107笔13.10倍。"),
        make_text_run("A76 即使剔除 924 大牛市，样本外仍一分不少维持 13.10 倍。"),
        make_text_run("千五千八滑点A76仍197.4x与83.5x，卡三亿49.27x。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("统计硬度与 2025 截断复现全部零瑕疵。", bold=True),
        make_text_run(
            "S82的HLZ t值5.41且DSR 0.9988，随机权99%超2倍。",
            background_color=3,
        ),
        make_text_run("2025 年初截断重放 S82 与 A76 全部零偏差，138 笔完全复现。"),
        make_text_run("21 至 26 年 S82 连续六年收正，最弱 2025 年仍赚 +40.14%。"),
    ]
    blocks.append(make_bullet_block(b2))

    p4 = [
        make_text_run("红队终裁："),
        make_text_run("V1.1 彻底治好过拟合尖峰，经得起极值熊市与滑点摩擦毒打。", background_color=3),
        make_text_run("实盘坚定只做纯单轨深水反抽，S 档 82 分上车，A 档仅作观察。"),
    ]
    blocks.append(make_para_block(p4))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：四种架构盲测对决表（含 +0.30% 穿价缓冲）"
    t1_rows = [
        [[("架构方案", {"bold": True})], [("全期单仓", {"bold": True})], [("去924 OOS（样本外）", {"bold": True})], [("融合表现与裁决", {"bold": True})]],
        [[("架构1 纯深水 A76", {"bold": True})], [("349.78 倍", {"bold": True})], [("13.10 倍 (26年3.90x)", {"bold": True})], [("无毒污染，全期胜出", {"bold": True})]],
        [[("架构2 全量融合 T5", {})], [("406.81 倍", {})], [("8.60 倍 (26年3.81x)", {})], [("所加普涨股均亏 -1.49%", {})]],
        [[("架构3a 快进普涨版", {})], [("658.22 倍", {})], [("10.70 倍 (26年3.61x)", {})], [("所加普涨股均亏 -1.28%", {})]],
        [[("纯深水 S82 实盘版", {"bold": True})], [("468.29 倍", {"bold": True})], [("3.94 倍 (26年2.60x)", {"bold": True})], [("六年全正，夏普大增", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：V1.1 过拟合诊断、极值压测与逐年拆解全表"
    t2_rows = [
        [[("红队压测与年份", {"bold": True})], [("S82 实测结果", {"bold": True})], [("A76 参照结果", {"bold": True})], [("关键校验结论", {"bold": True})]],
        [[("HLZ t / DSR 200次", {})], [("5.41 / 0.9988", {})], [("4.58 / 0.9771", {})], [("猴子抽签 p 值万分之二", {})]],
        [[("PBO 对比 V1.0", {})], [("阈值高原 323至877x", {})], [("局部 PBO 降至 1.43%", {})], [("由 V1.0 的 70% 大幅降噪", {})]],
        [[("去前5 / 去前10极值", {})], [("104.06x / 36.63x", {})], [("74.86x / 24.85x", {})], [("高分散复利不靠单票", {})]],
        [[("2025截断 / 45只退市", {})], [("误差0.0 / 2626全覆盖", {})], [("误差0.0 / 0违规", {})], [("因果纳入零幸存者偏差", {})]],
        [[("2021至2023逐年 S82", {})], [("+257% / +512% / +132%", {})], [("+133% / +174% / +30%", {})], [("熊市三年全部大赚", {})]],
        [[("2024至2026逐年 S82", {})], [("+154% / +40% / +160%", {})], [("+388% / +121% / +291%", {})], [("S 档 2025 恢复至 29 笔", {})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261124 20cm V1.1独立红队攻防与过拟合压力测试",
        "parent_node_token": "Bm0AwmIg5if5vekhQmacamjdnIc",
        "doc_id": None,
        "node_token": None,
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
