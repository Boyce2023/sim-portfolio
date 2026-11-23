# -*- coding: utf-8 -*-
"""26Q4专供 V2.1（接入全部 5 策略 V19.1 物理真账最新滚动夏普参数）飞书主文档生成器"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_26q4_v21_blocks():
    blocks = []

    p1 = [
        make_text_run("11月16日八项防过拟合体检证伪了旧版微观凑分参数，现行当季专供已升级。"),
        make_text_run(
            "现行机制锁死五年基础分门槛。用近 10 笔 50/50 贝叶斯夏普择优。",
            background_color=3,
        ),
        make_text_run(
            "常态严守五顺位，仅低顺位把握度领先高顺位满 1.50 以上才越级挂唯一 1 笔单。",
            background_color=3,
        ),
        make_text_run("全盘顺位：三进四 > 高标首阴 > 超跌撬板 > 二进三 > 一进二。"),
        make_text_run("五顺位对应版本锁死为 V4.1、V5.1、V2.1、V2.1 与 V19。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("为什么要废除旧版微观凑分版。"),
        make_text_run("旧版看近端 1 至 7 笔样本凑参数，导致严重样本外过拟合。"),
        make_text_run("高标旧专供过拟合概率 PBO 飙升至 41.43%，且 2023 年转为亏损。"),
        make_text_run("三进四旧专供缩水夏普概率 DSR 降至 83.08%，未过 95% 显著红线。"),
        make_text_run("旧合体 PBO 从 4.29% 飙至 32.86%。2022 至 2025 年收益退化。"),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("现行当季专供核心运行规则", bold=True, underline=True),
        make_text_run("，严格恪守底层不变、上层择优两步法："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run("底层门槛与卖点 100% 锁死 V19.1 基础版一字不改。", bold=True),
        make_text_run("高标满 88 分，三进四 V4.1 满 90 分，撬板 V2.1 满 165 分。", background_color=3),
        make_text_run("二进三 V2.1 满 90 分。一进二维持 304.8、329.8 与 295.0 分。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("上层计算当季滚动把握度。", bold=True),
        make_text_run("把握度等于超门槛标准分加上当季 50/50 贝叶斯滚动夏普。", background_color=3),
        make_text_run("超门槛标准分按 2021 至 2025 年洁净真账标准差严格标准化。"),
        make_text_run("夏普底分由五年先验夏普与近 10 笔纸面触发均值五五收缩得出。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("09 点 26 分唯一挂单越级规则。", bold=True),
        make_text_run("常态严守五策略死顺位，只取最高顺位头名挂唯一 1 笔单。", background_color=3),
        make_text_run("仅当低顺位把握度领先最高顺位满 1.50 以上时，才破格越级挂单。"),
        make_text_run("未触发条件单当日直接空仓，买谁按谁的 V19.1 卖点规则执行。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p4_head = [
        make_text_run("实证边界与红队校准状态同步", bold=True, underline=True),
        make_text_run("，确保全部 5 策略真账同口径接入："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("科学分层机制近三年封顶 86.81 倍，2026 年单仓达 16.51 倍。"),
        make_text_run("其 150 次试验 DSR 达 99.99%，过拟合概率 PBO 仅 5.71%。", background_color=3),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("2026 年 11 月 23 日全量物理真账校准已同步更新 5 策略状态文件。"),
        make_text_run("超跌撬板 V2.1 已补齐接入参数。标准差 15.41，底分 0.5073。", background_color=3),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("现行训练期基准标准差与当前贝叶斯底分固化如下，只随新结平交易滚动。"),
        make_text_run("严禁按盘中个案主观调高或调低门槛，确保零后视污染。", background_color=3),
    ]
    blocks.append(make_bullet_block(b3))

    p5 = [
        make_text_run("关于"),
        make_text_run("当季专供的失效监控", bold=True, text_color=1),
        make_text_run("，核心盯着"),
        make_text_run("越级频次、滚动夏普回落速度与撬板顺位接线完整性", background_color=3),
        make_text_run("。若某一主策略连续 2 笔亏损，其贝叶斯滚动夏普会自动下沉让位。"),
        make_text_run("一切调仓仍在纯单仓互斥框架下运行，买谁按谁的规则卖。"),
    ]
    blocks.append(make_para_block(p5))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：旧版微观凑分专供 vs 现行科学版防过拟合对比表"
    t1_rows = [
        [[("方案名称", {"bold": True})], [("五年笔数与胜率", {"bold": True})], [("过拟合概率 PBO", {"bold": True})], [("样本外与近期结论", {"bold": True})]],
        [[("静态五年基础版", {})], [("181笔 / 66.85%", {})], [("4.29% (极稳)", {})], [("DSR 99.98%，稳健底座", {})]],
        [[("旧版26Q4合体", {})], [("206笔 / 64.08%", {})], [("32.86% (黄灯)", {})], [("2022至2025年收益退化", {})]],
        [[("旧版高标与三进四", {})], [("40笔 / 97笔", {})], [("高标 41.43% 逼红线", {})], [("三进四 DSR 83.08% 淘汰", {})]],
        [[("科学分层最优版", {"bold": True})], [("181笔 / 66.85%", {"bold": True})], [("5.71% (稳健通过)", {"bold": True})], [("2026年16.51倍，DSR 99.99%", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：现行全5策略50/50贝叶斯滚动夏普参数表（2026.11.20洁净版）"
    t2_rows = [
        [[("基石策略(顺位)", {"bold": True})], [("锁死五年门槛", {"bold": True})], [("训练期标准差", {"bold": True})], [("先验 / 近10 / 融合底分", {"bold": True})]],
        [[("三进四 V4.1 (1)", {"bold": True})], [("90 分 (底78)", {})], [("7.26", {})], [("0.3511 / 0.8146 / 0.5828", {"bold": True})]],
        [[("高标首阴 V5.1 (2)", {"bold": True})], [("88 分 (底60)", {})], [("14.23", {})], [("0.6813 / 1.0633 / 0.8723", {"bold": True})]],
        [[("超跌撬板 V2.1 (3)", {"bold": True})], [("165 分 (底100)", {})], [("15.41", {})], [("0.6096 / 0.4049 / 0.5073", {"bold": True})]],
        [[("二进三 V2.1 (4)", {"bold": True})], [("90 分 (底60)", {})], [("4.51", {})], [("0.3836 / 0.4806 / 0.4321", {"bold": True})]],
        [[("一进二 V19 (5)", {"bold": True})], [("304.8 / 329.8 分", {})], [("25.88", {})], [("0.4023 / 0.8070 / 0.6046", {"bold": True})]],
        [[("越级触发硬条件", {"bold": True})], [("低顺位领先满 1.50", {"bold": True})], [("09:26 唯一挂单", {"bold": True})], [("不足 1.50 严守五顺位", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "26Q4专供",
        "doc_id": "WGtbd6n5Po4llQxEKoVceMsWndb",
        "node_token": "NUz8wegleiU66Kk0gVQcUigfnVf",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
