# -*- coding: utf-8 -*-
"""A股短线五策略体系总纲（V19.1 定版）飞书主文档生成器（红队物理真账校准同步版）"""
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
        make_text_run("全盘为四大核心主策略加唯一实盘辅助小策略，按单仓顺位互斥。"),
        make_text_run(
            "全盘顺位：三进四 > 高标首阴 > 超跌撬板 > 二进三 > 一进二。",
            background_color=3,
        ),
        make_text_run("四大主策略为三进四、高标、二进三与一进二，辅策为超跌撬板。"),
        make_text_run("顺位就是最高权限，同日有高顺位信号时低顺位让路。"),
        make_text_run("四进五 V2.0 下放研发池保留参照，不再参与实盘排单。"),
        make_text_run("盘中追涨、当日左侧撬板与七项旧线已永久作废。"),
    ]
    blocks.append(make_para_block(p1))

    # 第 2 段：红队物理真账校准 + 全周期组合收益概览
    p2 = [
        make_text_run(
            "沪深300 五年为 -18.49%，近三年为 +10.33%。",
            background_color=3,
        ),
        make_text_run("2026 年以来沪深300 为 -14.04%，下半年为 -20.08%。"),
        make_text_run("五大真账通过零跌停强卖、零除权错算与零误套异动校验。"),
        make_text_run(
            "全五年五顺位合体 228 笔，胜率 64.91%，盈亏比 2.90。",
            background_color=3,
        ),
        make_text_run(
            "百万起千万封顶 187.47 倍，回撤 40.12%，复利 14403077 倍。",
            background_color=3,
        ),
        make_text_run("千万单利达 21.52 倍，近三年 127 笔封顶 109.89 倍。"),
        make_text_run("2026 年合体 43 笔胜率 67.44%，单仓 27.29 倍。"),
        make_text_run("2026 年百万封顶 21.10 倍，回撤稳守 12.30%。"),
    ]
    blocks.append(make_para_block(p2))

    # 第 3 段：五大策略分工总起
    p3_head = [
        make_text_run("五大实盘策略顺位与物理真账校准基准", bold=True, underline=True),
        make_text_run("，各守不同情绪周期与生态位："),
    ]
    blocks.append(make_para_block(p3_head))

    # 有序列表 5 条（严格对齐第1至第5顺位）
    o1 = [
        make_text_run("第 1 顺位三进四 V4.1：主板三连板换手分歧转强。", bold=True),
        make_text_run("底分 78 分共 22 项，标准 90 分，S 档 102 分。", background_color=3),
        make_text_run("命中七项持仓风险开关时，13:45 护利收紧至 +7.0%。"),
        make_text_run("12 笔收盘封死跌停顺延开盘后，95 笔胜率 65.26%。"),
        make_text_run("五年单仓 616.18 倍，百万封顶 63.87 倍，回撤 37.00%。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("第 2 顺位高标首阴 V5.1：4板以上连板龙首阴低吸。", bold=True),
        make_text_run("标准分 88 分，S 档 96 分，全五年共 42 笔。", background_color=3),
        make_text_run("修正 10 笔误套异动与 1 笔跌停顺延，胜率 71.43%。"),
        make_text_run("五年单仓与等权均 14.75 倍，盈亏比 2.83，回撤 15.94%。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("第 3 顺位超跌撬板 V2.1：急跌后早盘温和开盘撬板。", bold=True),
        make_text_run("底分 100 分共 10 项，标准 165 分，S 档 175 分。", background_color=3),
        make_text_run("采用四步动态阶梯卖法并设竞价涨停少于 5 家逃命。"),
        make_text_run("原账零违规，16 笔胜率 87.50%，单仓 2.44 倍。"),
        make_text_run("最大回撤 19.15%，近三年 8 笔 1.49 倍，2026 年 1.09 倍。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    o4 = [
        make_text_run("第 4 顺位二进三 V2.1：二连板次日换手低吸接力。", bold=True),
        make_text_run("底分 60 分共 18 项，标准 90 分，96 分高严档顶部重点提醒。", background_color=3),
        make_text_run("清理错挂版本并修复 2 笔除权后，95 笔胜率 53.68%。"),
        make_text_run("完备库五年单仓升至 404.71 倍，盈亏比 4.57，回撤 28.68%。"),
        make_text_run("百万封顶 54.06 倍，近三年 15.23 倍，2026 年 4.64 倍。"),
    ]
    blocks.append(make_ordered_block(o4, seq="auto"))

    o5 = [
        make_text_run("第 5 顺位一进二 V19：主板换手首板分歧转一致。", bold=True),
        make_text_run("平时 304.8 分，过热升 329.8 分，候补 295.0 分。", background_color=3),
        make_text_run("修复 1 笔跌停顺延与 1 笔除权后，97 笔胜率 68.04%。"),
        make_text_run("五年单仓 332.72 倍，百万封顶 54.17 倍，回撤 15.97%。"),
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
        make_text_run("五策略全部经过五年日频、五分钟线与红队物理真账核验。"),
        make_text_run("一旦单策略实盘回撤逼近历史极值，立即半仓观察并交研究席复核。"),
    ]
    blocks.append(make_para_block(p6))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格（严格 <= 4 列，细胞 <= 32 字）
    tables = []

    t1_title = "附录：V19.1 五大实盘策略顺位、门槛与核心规则表"
    t1_rows = [
        [[("全局顺位", {"bold": True})], [("策略与定版", {"bold": True})], [("触发门槛", {"bold": True})], [("核心生态位与卖出机制", {"bold": True})]],
        [[("第 1 顺位", {"bold": True})], [("三进四 V4.1", {"bold": True})], [("90 分 / S 102 分", {})], [("7项风险开关收紧13:45至+7.0%", {})]],
        [[("第 2 顺位", {"bold": True})], [("高标首阴 V5.1", {})], [("88 分 / S 96 分", {})], [("封板套93%异动，未封次日不板走", {})]],
        [[("第 3 顺位", {"bold": True})], [("超跌撬板 V2.1", {"bold": True})], [("165 分 / S 175 分", {})], [("四步动态阶梯卖+涨停<5逃命", {})]],
        [[("第 4 顺位", {"bold": True})], [("二进三 V2.1", {"bold": True})], [("90 分 / 顶醒 96 分", {})], [("13:45护利+6.5%，高开>9.2%止盈", {})]],
        [[("第 5 顺位", {"bold": True})], [("一进二 V19", {})], [("304.8 / 329.8 / 295", {})], [("换手首板粮仓，含暗牌免弱斩", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：V19.1 物理校准后五大策略实证表现表"
    t2_rows = [
        [[("策略版本", {"bold": True})], [("五年笔数与胜率", {"bold": True})], [("单仓 / 百万封顶 / 回撤", {"bold": True})], [("近三年与 2026 年表现", {"bold": True})]],
        [[("三进四 V4.1", {"bold": True})], [("95笔 / 65.26%", {"bold": True})], [("616.18x / 63.87x / 37.00%", {"bold": True})], [("近3年200.23x / 2026年3.74x", {"bold": True})]],
        [[("高标首阴 V5.1", {})], [("42笔 / 71.43%", {})], [("14.75x / 14.13x / 15.94%", {})], [("近3年8.78x / 2026年2.92x", {})]],
        [[("超跌撬板 V2.1", {"bold": True})], [("16笔 / 87.50%", {"bold": True})], [("2.44x / 2.44x / 19.15%", {"bold": True})], [("近3年1.49x / 2026年1.09x", {"bold": True})]],
        [[("二进三 V2.1(完备)", {"bold": True})], [("95笔 / 53.68%", {"bold": True})], [("404.71x / 54.06x / 28.68%", {"bold": True})], [("近3年15.23x / 2026年4.64x", {"bold": True})]],
        [[("二进三 V2.1(官库)", {})], [("94笔 / 52.13%", {})], [("157.85x / 42.75x / 28.68%", {})], [("96分35笔23.36x / 回撤15.87%", {})]],
        [[("一进二 V19", {})], [("97笔 / 68.04%", {})], [("332.72x / 54.17x / 15.97%", {})], [("近3年62.37x / 2026年3.15x", {})]],
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

    t4_title = "附录：红队校准前后五顺位合体单仓对比表"
    t4_rows = [
        [[("组合版本与口径", {"bold": True})], [("五年笔数与胜率", {"bold": True})], [("单仓 / 百万封顶 / 单利", {"bold": True})], [("近三年与 2026 年封顶", {"bold": True})]],
        [[("V19.1 校准前(合体)", {})], [("229笔 / 65.07%", {})], [("3068万x / 195.27x / 22.30x", {})], [("近3年118.19x / 2026年21.09x", {})]],
        [[("V19.1 校准后(真账)", {"bold": True})], [("228笔 / 64.91%", {"bold": True})], [("1440万x / 187.47x / 21.52x", {"bold": True})], [("近3年109.89x / 2026年21.10x", {"bold": True})]],
        [[("合体回撤与盈亏比", {})], [("盈亏比 2.90", {})], [("五年及近三年回撤 40.12%", {})], [("2026年回撤 12.30% (27.29x)", {})]],
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
