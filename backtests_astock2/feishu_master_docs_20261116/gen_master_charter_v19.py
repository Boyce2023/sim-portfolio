# -*- coding: utf-8 -*-
"""A股短线五策略体系总纲（V19.0 定版）飞书主文档生成器"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_master_charter_v19_blocks():
    blocks = []

    # 第 1 段：总纲定位与唯一顺位
    p1 = [
        make_text_run("本总纲为 A 股机械账 V19.0 定版，统管实盘与模拟盘短线。"),
        make_text_run("全盘仅留五套主战策略，按单一满仓顺位互斥出击。"),
        make_text_run(
            "全盘顺位：三进四 > 高标首阴 > 超跌撬板 > 二进三 > 一进二。",
            background_color=3,
        ),
        make_text_run("对应版本为 V4.0、V5.1、V1.0、V2.0 与 V19。"),
        make_text_run("顺位就是最高权限，同日有高顺位信号时低顺位让路。"),
        make_text_run("四进五 V2.0 下放研发池保留参照，不再参与实盘排单。"),
        make_text_run("盘中追涨、当日左侧撬板与七项旧线已永久作废。"),
    ]
    blocks.append(make_para_block(p1))

    # 第 2 段：五策略核心门槛与全周期收益概览
    p2 = [
        make_text_run(
            "五年沪深300跌 18.49%，近三年涨 10.33%。",
            background_color=3,
        ),
        make_text_run(
            "2026 年以来沪深300跌 14.04%。",
            background_color=3,
        ),
        make_text_run("前四套组合五年单仓 66123.71 倍，回撤 26.26%。"),
        make_text_run("前四套千万起封顶五年 14.58 倍。"),
        make_text_run(
            "经120种全排列实证锁死最优五顺位，五年共 227 笔。",
            background_color=3,
        ),
        make_text_run(
            "五策略总胜率 64.32%，盈亏比升至 3.17。",
            background_color=3,
        ),
        make_text_run("百万起千万封顶达 183.31 倍，千万单利达 21.16 倍。"),
        make_text_run("实盘每笔严格单仓滚动，不因新信号提前卖旧仓。"),
    ]
    blocks.append(make_para_block(p2))

    # 第 3 段：五大策略分工总起
    p3_head = [
        make_text_run("五大实盘策略顺位拆解", bold=True, underline=True),
        make_text_run("，各守不同情绪周期与板位生态位："),
    ]
    blocks.append(make_para_block(p3_head))

    # 有序列表 5 条（严格对齐第1至第5顺位）
    o1 = [
        make_text_run("第 1 顺位三进四 V4.0：主板三连板换手分歧转强。", bold=True),
        make_text_run("底分 78 分共 22 项，标准 90 分，S 档 102 分。", background_color=3),
        make_text_run("09 点 26 分突破挂单，10 点 30 分未成自动撤单。"),
        make_text_run("五年 95 笔胜率 68.42%，单仓 1799.99 倍。"),
        make_text_run("百万封顶 75.49 倍，回撤稳守 31.25%。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("第 2 顺位高标首阴 V5.1：4板以上连板龙首阴低吸。", bold=True),
        make_text_run("标准分 88 分，S 档 96 分，全五年共 42 笔。", background_color=3),
        make_text_run("全仓胜率 73.8%，盈亏比 3.01，单仓 16.39 倍。"),
        make_text_run("回撤控制 15.9%，跑赢基准 1556.8 个百分点。"),
        make_text_run("纯五分钟精算 42 笔胜率 71.43%，13.41 倍。"),
        make_text_run("显著性统计检验 t 值达 5.30，单笔统计最稳。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("第 3 顺位超跌撬板 V1.0：急跌后早盘温和开盘撬板。", bold=True),
        make_text_run("底分 100 分共 10 项，标准 165 分，S 档 175 分。", background_color=3),
        make_text_run("独立五年 16 笔胜率 75.00%，单仓仅 1.94 倍。"),
        make_text_run("仅在三进四与高标空仓日作窄门辅助补位。"),
        make_text_run("独立统计检验 t 为 1.45 偏弱，仅作辅助通道。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    o4 = [
        make_text_run("第 4 顺位二进三 V2.0：二连板次日换手接力补强。", bold=True),
        make_text_run("底分 60 分共 18 项，标准 90 分，高严 96 分。", background_color=3),
        make_text_run("满 96 分信号在早盘报告顶部无条件单独重点提醒。"),
        make_text_run("90 分档五年 94 笔胜率 52.13%，盈亏比 4.01。"),
        make_text_run("单仓 144.21 倍，百万封顶 41.65 倍，回撤 28.68%。"),
        make_text_run("96 分档五年 35 笔回撤仅 15.87%，2026 年胜率 83.33%。"),
    ]
    blocks.append(make_ordered_block(o4, seq="auto"))

    o5 = [
        make_text_run("第 5 顺位一进二 V19：主板换手首板分歧转一致。", bold=True),
        make_text_run("平时 304.8 分，过热升 329.8 分，候补 295.0 分。", background_color=3),
        make_text_run("吸纳低位暗牌弱斩豁免后，五年 97 笔胜率 68.04%。"),
        make_text_run("单仓 338.37 倍，百万封顶 54.57 倍。"),
        make_text_run("按日等权 65.74 倍，回撤降至 15.97%。"),
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
        make_text_run("持仓出场严格锁定买入策略：买谁按谁的规则卖。"),
        make_text_run("中途绝不因新信号提前腾仓，避免两边挨打。", background_color=3),
    ]
    blocks.append(make_bullet_block(b3))

    b4 = [
        make_text_run("四大熔断开关直接管住手。"),
        make_text_run("昨日首板竞价均值为绿，或近 5 日晋级率低于 13.0% 停一进二。", background_color=3),
        make_text_run("昨日四板及高标全灭、封板不足 3 家停做三进四。"),
    ]
    blocks.append(make_bullet_block(b4))

    # 第 5 段：双席位边界与准入红线
    p5 = [
        make_text_run("交易席与研究席严格分离："),
        make_text_run("交易席只负责每日盘前扫盘、实盘跟单与风控复盘，不擅改参数。"),
        make_text_run("研究席负责因子挖掘、物理截断与八项过拟合检验，不干涉每日下单。"),
        make_text_run(
            "任何新版本必须同时通过近三年与 2026 年稳健考验，才准写入本总纲投产。",
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

    t1_title = "附录：五大实盘策略顺位、门槛与定位对照表"
    t1_rows = [
        [[("全局顺位", {"bold": True})], [("策略与定版", {"bold": True})], [("触发门槛", {"bold": True})], [("核心生态位", {"bold": True})]],
        [[("第 1 顺位", {"bold": True})], [("三进四 V4.0", {})], [("90 分 / S 102 分", {})], [("3连板突破转强，10:30撤单", {})]],
        [[("第 2 顺位", {"bold": True})], [("高标首阴 V5.1", {})], [("88 分 / S 96 分", {})], [("4板以上连板龙首阴低吸", {})]],
        [[("第 3 顺位", {"bold": True})], [("超跌撬板 V1.0", {})], [("165 分 / S 175 分", {})], [("连跌急杀后温和开盘补位", {})]],
        [[("第 4 顺位", {"bold": True})], [("二进三 V2.0", {})], [("90 分 / 顶醒 96 分", {})], [("二连板09:25直买高赔率接力", {})]],
        [[("第 5 顺位", {"bold": True})], [("一进二 V19", {})], [("304.8 / 329.8 / 295", {})], [("换手首板分歧转一致粮仓", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：五大策略五年全周期与近期实证表现表"
    t2_rows = [
        [[("策略版本", {"bold": True})], [("五年笔数与胜率", {"bold": True})], [("单仓 / 百万封顶 / 回撤", {"bold": True})], [("近三年与 2026 年表现", {"bold": True})]],
        [[("高标首阴 V5.1", {})], [("42笔 / 73.8%", {})], [("16.39x / 纯5m 13.41x / 15.9%", {})], [("近3年76.92% / 2026年71.43%", {})]],
        [[("三进四 V4.0", {})], [("95笔 / 68.42%", {})], [("1799.99x / 75.49x / 31.25%", {})], [("近3年72.41% / 2026年66.67%", {})]],
        [[("超跌撬板 V1.0", {})], [("16笔 / 75.00%", {})], [("1.94x / 仅作辅助 / 21.42%", {})], [("近3年75.00% / 2026年100%", {})]],
        [[("一进二 V19", {})], [("97笔 / 68.04%", {})], [("338.37x / 54.57x / 15.97%", {})], [("近3年68.63% / 2026年80.95%", {})]],
        [[("二进三 V2.0(90)", {})], [("94笔 / 52.13%", {})], [("144.21x / 41.65x / 28.68%", {})], [("近3年47.06% / 2026年64.29%", {})]],
        [[("二进三 V2.0(96)", {})], [("35笔 / 54.29%", {})], [("17.43x / 16.98x / 15.87%", {})], [("近3年52.38% / 2026年83.33%", {})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：每日四时段操作与熔断开关速查表"
    t3_rows = [
        [[("看盘时刻", {"bold": True})], [("核心核对对象", {"bold": True})], [("执行动作", {"bold": True})], [("红线熔断", {"bold": True})]],
        [[("09:25 竞价", {})], [("五策略打分与顺位排序", {})], [("锁定唯一最高顺位候选", {})], [("晋级率低于13%停一进二", {})]],
        [[("09:26 挂单", {})], [("三进四、撬板、低位接力", {})], [("按规则挂限价或条件单", {})], [("96分二进三顶部单独提醒", {})]],
        [[("10:30 与 10:40", {})], [("三进四未成与一进二弱势", {})], [("10:30三进四撤单+10:40复盘", {})], [("4板高标全灭停次日三进四", {})]],
        [[("13:45 与 14:55", {})], [("高标异动缓冲与尾盘清仓", {})], [("触缓冲止盈，不板尾盘走", {})], [("绝不为新信号提前卖旧仓", {})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：五策略组合协同与封顶实战对比表"
    t4_rows = [
        [[("组合阶段", {"bold": True})], [("交易笔数与胜率", {"bold": True})], [("单仓与千万起封顶", {"bold": True})], [("最大回撤与结论", {"bold": True})]],
        [[("原四策略底座", {})], [("前四顺位满仓轮动", {})], [("单仓66123.71x / 千万14.58x", {})], [("回撤 26.26%，存在空仓闲置", {})]],
        [[("120排列冠军顺位", {"bold": True})], [("227笔 / 64.32%", {"bold": True})], [("封顶183.31x / 单利21.16x", {"bold": True})], [("盈亏比3.17，09:26零空耗", {})]],
        [[("四进五 V2.0", {})], [("下放研发池", {})], [("不入实盘排单队列", {})], [("仅作空间突破研究参照", {})]],
    ]
    tables.append((t4_title, t4_rows))

    return {
        "title": "A股短线五策略体系总纲（V19.0 定版）",
        "doc_id": "MNYxdBGBxomQ8gxtz5tcYibBn6d",
        "node_token": "M0GEwOfn2ievUZkfvXHc97fJnOh",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
