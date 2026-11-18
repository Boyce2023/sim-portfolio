# -*- coding: utf-8 -*-
"""子文档3：20261116 断板反包与多日多板全谱系回测"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub3_rd013_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "结论：断板潜伏（16.1%）与反包次日接力（断板率 79.2%）完全没用。",
            background_color=3,
        ),
        make_text_run(
            "断板次日真阳弱转强叠反包热区满 15% 有用。胜率升至 60.9%，单笔均赚 5.75%。",
            background_color=3,
        ),
        make_text_run("五年全市场回测证实，断板反包不可作为独立一类主力策略单挂。"),
        make_text_run("仅可作为高标首阴 V5.1 的下沉扩充补丁，在反包热区填补退潮空窗。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("三大买点窗口与物理规律解剖", bold=True, underline=True),
        make_text_run("，解释了为什么绝大多数反包接力都亏钱："),
    ]
    blocks.append(make_para_block(p2_head))

    o1 = [
        make_text_run("断板日尾盘潜伏全市场胜率仅 16.1%，单仓净值归零。", bold=True),
        make_text_run("全池 48197 笔均值亏 1.29%，三板与高标首阴尾盘买均亏超 3.2%。", background_color=3),
        make_text_run("隔夜低开下杀概率极高，盲目左侧潜伏等于直接接飞刀。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("反包板是主升能量终点，次日接力 75% 至 79% 直接断板。", bold=True),
        make_text_run("传统三连板次日断板率 52.25%，而四天三板反包次日断板率飙至 79.19%。", background_color=3),
        make_text_run("五天四板反包次日断板率也达 75.43%，竞价与突破追高均告亏损。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("唯一正期望切入点在断板次日早盘平红开抓真阳反包板。", bold=True),
        make_text_run("核心约束为前序三连板以上、收真阳、换手不超 32%、主线梯队与热区。", background_color=3),
        make_text_run("叠加近 10 日反包热区满 15% 时有效。胜率由 34.95% 跃至 60.9%，单仓 1.48 倍。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3_head = [
        make_text_run("卖出规则对决与高标下沉补丁定级", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    b1 = [
        make_text_run("10 厘米超短反包存在剧烈时间折价，严禁按 5 日均线死扛趋势。"),
        make_text_run("方案 A 连板卖法单仓 0.457 倍。改用 5 日均线卖法则崩塌至 0.083 倍。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("2024 至 2026 年监管趋严后主力故意断板绕异动，近三年明显回暖。"),
        make_text_run("主线换手龙近三年 235 笔单仓 1.575 倍。2026 年胜率 49.6%，净值 1.251 倍。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("与既有主力策略日历碰撞率仅 23.0%，高达 77.0% 发生在主力空仓日。"),
        make_text_run("实盘定级：不单独成军，仅纳入高标首阴前序三板以上反包热区备选补丁。"),
    ]
    blocks.append(make_bullet_block(b3))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：断板反包三大买点窗口五年实证对比表（扣 20 基点摩擦）"
    t1_rows = [
        [[("买点定义", {"bold": True})], [("样本与胜率", {"bold": True})], [("单笔均值与盈亏比", {"bold": True})], [("单仓净值与评价", {"bold": True})]],
        [[("买点甲：断板尾盘潜伏", {})], [("48197笔 / 16.1%", {})], [("亏1.29% / 1.45", {})], [("净值 0.000 / 绝对深坑", {})]],
        [[("买点甲：3板与高标首阴", {})], [("1309与1009笔", {})], [("胜率13.0%与18.9%", {})], [("均亏超3.2%，零买入空间", {})]],
        [[("买点乙：断板次日早盘弱转", {})], [("16471笔 / 38.6%", {})], [("微亏0.31% / 1.36", {})], [("唯一值得单因子提纯窗口", {})]],
        [[("买点丙：4天3板反包接力", {})], [("141笔 / 35.5%", {})], [("亏0.87% / 断板79.2%", {})], [("净值 0.185 / 散户接盘坑", {})]],
        [[("买点丙：5天4板反包接力", {})], [("46笔 / 28.3%", {})], [("亏3.88% / 断板75.4%", {})], [("净值 0.207 / 严重亏钱", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：核心迁移单因子增益与卖出机制对决表"
    t2_rows = [
        [[("测试因子或方案", {"bold": True})], [("样本与胜率", {"bold": True})], [("单笔均值", {"bold": True})], [("单仓净值与核心裁决", {"bold": True})]],
        [[("基线池：2板起早盘弱转强", {})], [("2246笔 / 34.95%", {})], [("亏 0.65%", {})], [("净值 0.001 / 待提纯基准", {})]],
        [[("单因子：断板收真阳线", {"bold": True})], [("600笔 / 42.8%", {"bold": True})], [("赚 0.01%", {"bold": True})], [("胜率增 7.9%，第一过滤条件", {"bold": True})]],
        [[("单因子：反包热区满15%", {"bold": True})], [("23笔 / 60.9%", {"bold": True})], [("赚 5.75%", {"bold": True})], [("净值 1.480 / 最强环境锁", {"bold": True})]],
        [[("单因子：破局期最高5板内", {})], [("1102笔 / 37.8%", {})], [("亏 0.54%", {})], [("胜率增 2.9%，老龙退潮防假", {})]],
        [[("方案A：连板卖 vs 5日线", {})], [("342笔 / 43.6% vs 31.6%", {})], [("亏0.17% vs 亏1.01%", {})], [("0.457倍 vs 0.083倍，禁均线扛", {})]],
        [[("方案A：近三年与2026年", {})], [("235笔与115笔", {})], [("胜率43.8%与49.6%", {})], [("单仓 1.575 倍与 1.251 倍", {})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261116 断板反包与多日多板全谱系回测",
        "parent_node_token": "KGZww0jBYifjsFk1V8JcOuPrnpe",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
