# -*- coding: utf-8 -*-
"""子文档5：20261116 当季滚动夏普与多方案样本外择优实证"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub5_seasonal_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "结论：按季度重凑微观因子没用，样本外大幅退化，锁死五年基础分加滚动夏普择优有用。",
            background_color=3,
        ),
        make_text_run(
            "HBCP 五年单仓 50655 倍超静态 43635 倍。2026 年 16.51 倍且回撤 15.36%。",
            background_color=3,
        ),
        make_text_run("旧版微观凑分在 2022 至 2025 年退化。样本外从 3848.36 倍掉至 2372.53 倍。"),
        make_text_run("同时旧版回撤从 26.26% 恶化至 32.33%。过拟合概率 PBO 飙升至 32.86%。"),
        make_text_run("严格 09 点 26 分唯一挂单走步实测下。滚动机制 2026 年 7 月起跑赢基础版。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("两阶段严格对照实验设计", bold=True, underline=True),
        make_text_run("，彻底杜绝用 2026 年答案偷看参数："),
    ]
    blocks.append(make_para_block(p2_head))

    o1 = [
        make_text_run("所有标准化均值、标准差与层级先验仅在 2021 至 2025 年率定。", bold=True),
        make_text_run("2026 年全年尤其 7 月与 10 月以来的两万亿行情作为纯粹盲测窗口。", background_color=3),
        make_text_run("实验统一采用双边千分之二手续费，T加0违规与单仓重叠严格为零。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("第一实验：固定池机制对比（HBCP 显著胜出）。", bold=True),
        make_text_run("纯去偏置的标准化择优会损失大局层级，五年单仓小降至 43106.54 倍。", background_color=3),
        make_text_run("分层先验 HBCP 近三年封顶升至 86.81 倍。2026 年单仓达 16.51 倍。"),
        make_text_run("HBCP 机制 DSR 达 99.99%，5 年赢基准。过拟合概率 PBO 仅 5.71%。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("第二实验：严格 09 点 26 分唯一挂单全池走步盲测。", bold=True),
        make_text_run("模拟盘前 09:26 挂唯一 1 笔单、未成交当日不补买次选的严苛约束。", background_color=3),
        make_text_run("静态基础版五年 187 笔 39647.03 倍。千万封顶 116.98 倍，PBO 8.57%。"),
        make_text_run("M1 与 M3 在 2026 年 7 月后达 3.22 倍。显著高于同期基础版的 3.01 倍。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3 = [
        make_text_run("实盘综合落地：底座锁死五年基础版一字不改。"),
        make_text_run("上层用近 10 笔 50/50 贝叶斯夏普算把握度。", background_color=3),
        make_text_run("常态严守五顺位，仅当低顺位把握度领先满 1.50 时才破格越级挂唯一 1 笔单。"),
    ]
    blocks.append(make_para_block(p3))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：固定主池四方案样本外与全周期效果对比表"
    t1_rows = [
        [[("机制方案", {"bold": True})], [("五年单仓与回撤", {"bold": True})], [("2026全年与样本外", {"bold": True})], [("DSR 与 PBO 体检", {"bold": True})]],
        [[("静态五年基础版", {})], [("43635.18x / 26.26%", {})], [("2026 12.30x / 样外 3848x", {})], [("99.98% / PBO 4.29%", {})]],
        [[("旧版 26Q4 专供", {})], [("29483.12x / 32.33%", {})], [("2026 13.48x / 样外 2372x", {})], [("PBO 32.86% 退化淘汰", {})]],
        [[("C1 纯标准化顺位", {})], [("43106.54x / 29.98%", {})], [("2026 13.89x / 样外 3366x", {})], [("99.98% / PBO 15.71%", {})]],
        [[("HBCP 科学最优版", {"bold": True})], [("50655.46x / 29.98%", {"bold": True})], [("2026 16.51x / 7月 3.63x", {"bold": True})], [("99.99% / PBO 5.71%", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：严格 09 点 26 分唯一挂单全池走步盲测对比表"
    t2_rows = [
        [[("走步方案", {"bold": True})], [("全五年笔数与净值", {"bold": True})], [("2026年7月与10月", {"bold": True})], [("PBO 与稳定性评估", {"bold": True})]],
        [[("静态基础(0926严格)", {"bold": True})], [("187笔 / 39647.03x", {"bold": True})], [("7月3.01x / 10月1.14x", {"bold": True})], [("PBO 8.57% / 百万116.98x", {"bold": True})]],
        [[("M1 滚动纸面动量", {})], [("184笔 / 26011.16x", {})], [("7月3.22x / 10月1.25x", {})], [("PBO 12.86% / 近期短窗占优", {})]],
        [[("M2 D1宏观温度计", {})], [("182笔 / 22112.37x", {})], [("7月3.22x / 10月1.25x", {})], [("PBO 18.57% / 全年 11.23x", {})]],
        [[("M3 综合贝叶斯收缩", {})], [("181笔 / 20636.35x", {})], [("7月3.22x / 10月1.25x", {})], [("PBO 17.14% / DSR 99.92%", {})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261116 当季滚动夏普与多方案样本外择优实证",
        "parent_node_token": "NUz8wegleiU66Kk0gVQcUigfnVf",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
