# -*- coding: utf-8 -*-
"""A股短线五策略体系总纲（V19.1 定版）飞书主文档生成器"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_master_charter_v191_blocks():
    blocks = []

    # 第 1 段：总纲定位与唯一顺位
    p1 = [
        make_text_run("本总纲为 A 股机械账 V19.1 定版，统管实盘与模拟盘短线。"),
        make_text_run("全盘仅留五套主战策略，按单一满仓顺位互斥出击。"),
        make_text_run(
            "全盘顺位：三进四 > 高标首阴 > 超跌撬板 > 二进三 > 一进二。",
            background_color=3,
        ),
        make_text_run("对应版本为 V4.1、V5.1、V2.1、V2.1 与 V19。"),
        make_text_run("顺位就是最高权限，同日有高顺位信号时低顺位让路。"),
        make_text_run("四进五 V2.0 下放研发池保留参照，不再参与实盘排单。"),
        make_text_run("盘中追涨、当日左侧撬板与七项旧线已永久作废。"),
    ]
    blocks.append(make_para_block(p1))

    # 第 2 段：V19.1 三大卖点升级 + 全周期组合收益概览
    p2 = [
        make_text_run(
            "沪深300 五年为 -18.49%，近三年为 +10.33%。",
            background_color=3,
        ),
        make_text_run("2026 年以来沪深300 为 -14.04%。"),
        make_text_run("V19.1 买点不变，仅对三进四、撬板与二进三升级卖点。"),
        make_text_run(
            "全五年五顺位合体 232 笔，胜率 65.09%，盈亏比 3.13。",
            background_color=3,
        ),
        make_text_run(
            "完备库百万封顶 191.26 倍（官库 187.73 倍），回撤 34.02%。",
            background_color=3,
        ),
        make_text_run("千万单利达 21.90 倍（官库 21.58 倍），近三年封顶 114.18 倍。"),
        make_text_run("2026 年合体 43 笔胜率 67.44%，百万封顶 21.09 倍。"),
        make_text_run("2026 年回撤稳守 12.30%，严禁因新信号提前腾仓卖旧仓。"),
    ]
    blocks.append(make_para_block(p2))

    # 第 3 段：五大策略分工总起
    p3_head = [
        make_text_run("五大实盘策略顺位与 V19.1 卖点升级拆解", bold=True, underline=True),
        make_text_run("，各守不同情绪周期与生态位："),
    ]
    blocks.append(make_para_block(p3_head))

    # 有序列表 5 条（严格对齐第1至第5顺位）
    o1 = [
        make_text_run("第 1 顺位三进四 V4.1：主板三连板换手分歧转强。", bold=True),
        make_text_run("底分 78 分共 22 项，标准 90 分，S 档 102 分。", background_color=3),
        make_text_run("新增七项持仓风险开关，命中满 1 项时 13:45 护利收紧至 +7.0%。"),
        make_text_run("0 命中低风险日维持 +5.0% 放飞总龙头，95 笔胜率 68.42%。"),
        make_text_run("五年单仓由 1800.0 倍升至 2319.09 倍，回撤降至 29.23%。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("第 2 顺位高标首阴 V5.1：4板以上连板龙首阴低吸。", bold=True),
        make_text_run("标准分 88 分，S 档 96 分，全五年共 42 笔。", background_color=3),
        make_text_run("全仓胜率 73.8%，盈亏比 3.01，单仓 16.39 倍，回撤 15.9%。"),
        make_text_run("纯五分钟精算 42 笔胜率 71.43%，净值 13.41 倍，t 值 5.30。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("第 3 顺位超跌撬板 V2.1：急跌后早盘温和开盘撬板。", bold=True),
        make_text_run("底分 100 分共 10 项，标准 165 分，S 档 175 分。", background_color=3),
        make_text_run("废除连挂四天死限价单，改用四步动态阶梯卖法并设涨停<5家逃命。"),
        make_text_run("五年 16 笔胜率由 75.0% 跃至 87.5%。单仓由 1.94 倍升至 2.44 倍。"),
        make_text_run("最大回撤由 21.42% 降至 19.15%，帮五合体近三年降低回撤。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    o4 = [
        make_text_run("第 4 顺位二进三 V2.1：二连板次日换手低吸接力。", bold=True),
        make_text_run("底分 60 分共 18 项，标准 90 分，96 分高严档顶部重点提醒。", background_color=3),
        make_text_run("封死三板后 13:45 护利由 +5.0% 升至 +6.5%。变动 17 笔全胜。"),
        make_text_run("完备库单仓由 261.1 倍升至 313.87 倍。官库升至 157.85 倍。"),
        make_text_run("96 分高严档完备库由 20.84 倍升至 23.36 倍，回撤仅 15.87%。"),
    ]
    blocks.append(make_ordered_block(o4, seq="auto"))

    o5 = [
        make_text_run("第 5 顺位一进二 V19：主板换手首板分歧转一致。", bold=True),
        make_text_run("平时 304.8 分，过热升 329.8 分，候补 295.0 分。", background_color=3),
        make_text_run("吸纳低位暗牌弱斩豁免后，五年 97 笔胜率 68.04%，单仓 338.37 倍。"),
        make_text_run("百万封顶 54.57 倍，按日等权 65.74 倍，回撤稳守 15.97%。"),
    ]
    blocks.append(make_ordered_block(o5, seq="auto"))

    # 第 4 段：交易纪律与日常操作死规矩
    p4_head = [
        make_text_run("实盘操作与风控死规矩", bold=True, underline=True),
        make_text_run("，每日按固定四步节奏机械执行："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("早盘 09 点 25 分与 26 分统一扫盘出单。"),
        make_text_run("严格按五策略顺位只买唯一头号标的，零盘中换股。", background_color=3),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("板位只认连续自然涨停："),
        make_text_run("几进几必须严格对应连续天板数，中间断板反包一律踢出", background_color=3),
        make_text_run("。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("持仓出场严格锁定买入策略：买谁按谁的 V19.1 规则卖。"),
        make_text_run("中途绝不因新信号提前腾仓，避免两边挨打。", background_color=3),
    ]
    blocks.append(make_bullet_block(b3))

    b4 = [
        make_text_run("五大熔断开关直接管住手。"),
        make_text_run("昨日首板均开为绿或晋级率低于 13% 停一进二，四板全灭停三进四。", background_color=3),
        make_text_run("撬板持仓期早盘 09:25 全场竞价涨停少于 5 家立即无条件开盘清仓。"),
    ]
    blocks.append(make_bullet_block(b4))

    # 第 5 段：双席位边界与准入红线
    p5 = [
        make_text_run("交易席与研究席严格分离："),
        make_text_run("交易席只负责每日盘前扫盘、实盘跟单与风控复盘，不擅改参数。"),
        make_text_run("研究席负责因子挖掘、物理截断与八项过拟合检验，不干涉每日下单。"),
        make_text_run(
            "任何新版本必须同时通过样本内外、物理截断与多窗口考验才准投产。",
            background_color=3,
        ),
    ]
    blocks.append(make_para_block(p5))

    # 第 6 段：关于失效与退化监控
    p6 = [
        make_text_run("关于"),
        make_text_run("总纲体系的失效防线", bold=True, text_color=1),
        make_text_run("，核心盯着"),
        make_text_run("连板生态晋级率与各策略近 20 笔真实回撤", background_color=3),
        make_text_run("。"),
        make_text_run("五策略全部经过五年日频、五分钟线与 2025 年初物理截断核验。"),
        make_text_run("一旦单策略实盘回撤逼近历史极值，立即半仓观察并交研究席复核。"),
    ]
    blocks.append(make_para_block(p6))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格（严格 <= 4 列，细胞 <= 32 字）
    tables = []

    t1_title = "附录：V19.1 五大实盘策略顺位、门槛与卖点升级表"
    t1_rows = [
        [[("全局顺位", {"bold": True})], [("策略与定版", {"bold": True})], [("触发门槛", {"bold": True})], [("核心生态位与卖点升级", {"bold": True})]],
        [[("第 1 顺位", {"bold": True})], [("三进四 V4.1", {"bold": True})], [("90 分 / S 102 分", {})], [("7项风险开关收紧13:45至+7.0%", {})]],
        [[("第 2 顺位", {"bold": True})], [("高标首阴 V5.1", {})], [("88 分 / S 96 分", {})], [("4板以上首阴低吸，规则保持稳定", {})]],
        [[("第 3 顺位", {"bold": True})], [("超跌撬板 V2.1", {"bold": True})], [("165 分 / S 175 分", {})], [("四步动态阶梯卖+涨停<5逃命", {})]],
        [[("第 4 顺位", {"bold": True})], [("二进三 V2.1", {"bold": True})], [("90 分 / 顶醒 96 分", {})], [("13:45护利线升至+6.5%(17胜0负)", {})]],
        [[("第 5 顺位", {"bold": True})], [("一进二 V19", {})], [("304.8 / 329.8 / 295", {})], [("换手首板粮仓，规则保持稳定", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：V19.1 五大策略五年全周期与近期实证表现表"
    t2_rows = [
        [[("策略版本", {"bold": True})], [("五年笔数与胜率", {"bold": True})], [("单仓 / 百万封顶 / 回撤", {"bold": True})], [("近三年与 2026 年表现", {"bold": True})]],
        [[("三进四 V4.1", {"bold": True})], [("95笔 / 68.42%", {"bold": True})], [("2319.09x / 79.02x / 29.23%", {"bold": True})], [("近3年581.22x / 2026年3.74x", {"bold": True})]],
        [[("高标首阴 V5.1", {})], [("42笔 / 73.8%", {})], [("16.39x / 纯5m 13.41x / 15.9%", {})], [("近3年76.92% / 2026年71.43%", {})]],
        [[("超跌撬板 V2.1", {"bold": True})], [("16笔 / 87.50%", {"bold": True})], [("2.44x / 等权3.81x / 19.15%", {"bold": True})], [("近3年1.49x / 2026年100%", {"bold": True})]],
        [[("二进三 V2.1(官库)", {"bold": True})], [("94笔 / 52.13%", {"bold": True})], [("157.85x / 42.75x / 28.68%", {"bold": True})], [("近3年10.17x / 2026年4.35x", {"bold": True})]],
        [[("二进三 V2.1(完备)", {"bold": True})], [("95笔 / 52.63%", {"bold": True})], [("313.87x / 51.31x / 28.68%", {"bold": True})], [("96分23.36x / 2026年83.33%", {"bold": True})]],
        [[("一进二 V19", {})], [("97笔 / 68.04%", {})], [("338.37x / 54.57x / 15.97%", {})], [("近3年68.63% / 2026年80.95%", {})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：每日四时段操作与熔断开关速查表"
    t3_rows = [
        [[("看盘时刻", {"bold": True})], [("核心核对对象", {"bold": True})], [("执行动作", {"bold": True})], [("红线熔断", {"bold": True})]],
        [[("09:25 竞价", {})], [("五策略排序与涨停家数", {})], [("选唯一头号，撬板<5家逃命", {})], [("晋级率低于13%停一进二", {})]],
        [[("09:26 挂单", {})], [("三进四、撬板、低位接力", {})], [("按规则挂限价或条件单", {})], [("96分二进三顶部单独提醒", {})]],
        [[("10:30 与 10:40", {})], [("三进四未成与一进二弱势", {})], [("10:30三进四撤单+10:40复盘", {})], [("4板高标全灭停次日三进四", {})]],
        [[("13:45 与 14:55", {})], [("摸+8.5%护利与尾盘清仓", {})], [("34破+7/5%，23破+6.5%，撬-1.5%", {})], [("绝不为新信号提前卖旧仓", {})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：V19.0 原版 vs V19.1 升级版五顺位合体对比表"
    t4_rows = [
        [[("组合版本与口径", {"bold": True})], [("五年笔数与胜率", {"bold": True})], [("百万封顶与千万单利", {"bold": True})], [("近三年与 2026 年封顶", {"bold": True})]],
        [[("V19.0 原版(官库)", {})], [("231笔 / 64.94%", {})], [("181.74x / 单利21.00x", {})], [("近3年109.76x / 2026年20.79x", {})]],
        [[("V19.1 升级(官库)", {"bold": True})], [("232笔 / 65.09%", {"bold": True})], [("187.73x / 单利21.58x", {"bold": True})], [("近3年112.77x / 2026年21.12x", {})]],
        [[("V19.1 升级(完备5m)", {"bold": True})], [("232笔 / 65.09%", {"bold": True})], [("191.26x / 单利21.90x", {"bold": True})], [("近3年114.18x / 2026年21.09x", {})]],
        [[("四进五 V2.0", {})], [("下放研发池", {})], [("不入实盘排单队列", {})], [("仅作空间突破研究参照", {})]],
    ]
    tables.append((t4_title, t4_rows))

    return {
        "title": "A股短线五策略体系总纲（V19.1 定版）",
        "doc_id": "MNYxdBGBxomQ8gxtz5tcYibBn6d",
        "node_token": "M0GEwOfn2ievUZkfvXHc97fJnOh",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
