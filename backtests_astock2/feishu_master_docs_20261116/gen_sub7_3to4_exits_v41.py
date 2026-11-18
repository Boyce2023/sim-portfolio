# -*- coding: utf-8 -*-
"""子文档7：20261118 三进四V4.1七项持仓风险因子护利回测"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub7_3to4_exits_v41_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "结论：七项持仓风险开关护利非常有用，五年单仓升至 2319.09 倍。",
            background_color=3,
        ),
        make_text_run(
            "原版五年单仓 1799.99 倍，回撤从 31.25% 降至 29.23%。",
            background_color=3,
        ),
        make_text_run("102 分极严档由 16.72 倍升至 17.73 倍。"),
        make_text_run("按日等权从 4458.94 倍升至 5644.80 倍。去前五牛股升至 134.19 倍。"),
        make_text_run("样本内 41 笔由 4.75 倍升至 5.62 倍。样本外由 379.08 倍升至 412.79 倍。"),
        make_text_run("78 分扩充池 227 笔升至 112.11 倍。原版仅 74.13 倍，零样本外分化。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("30 项候选因子与 626 组动作均先在样本内定标。随后一次性盲测样本外。"),
        make_text_run("全周期严格隔离时点信息：盘前仅用前晚龙虎榜、开盘前公告与当日竞价数据。"),
        make_text_run("物理切除 2025 年及之后数据复验 56 笔历史交易，偏差严格为 0.0。"),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("核心物理机制：风险门控护利与淘汰 22 项负效规则", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run("淘汰 09:25 直接抢跑与强行剥夺免死，样本外大亏上百倍。", bold=True),
        make_text_run("三进四主升总龙天生伴随高频风险提示、高换手与游资接力，过激抢跑专斩龙头。", background_color=3),
        make_text_run("22 项被淘汰规则中，09:25 抢跑与 93% 异动单在样本外大亏上百倍。"),
        make_text_run("强行剥夺首次真阳断板免死会使总龙头合富中国收益腰斩，样本外大跌逾百倍。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("淘汰无差别收紧 +7.0% 护利，避免洗盘日误杀总龙头。", bold=True),
        make_text_run("无差别把 13:45 护利收紧至 +7.0%，样本内虽升但样本外腰斩。", background_color=3),
        make_text_run("合富中国十连板洗盘日尾盘压至 +5.26%。无差别收紧少收 73.95 点。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("七项正交持仓风险开关实现低风险放飞、高风险锁利。", bold=True),
        make_text_run("七项因子两两相关极低，仅在 59.5% 持仓日激活 +7.0% 护利。", background_color=3),
        make_text_run("核心三项：概念热度满 135 分、机构卖超 2000 万、爆量超 3.5 倍。"),
        make_text_run("辅助四项：一日游买入、新监管函、沪深300 急跌、断板反包低于 20.0%。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p4_head = [
        make_text_run("稳健性检验、改动明细与备选方案边界", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("90 分标准档共改变 18 笔交易，16 胜 2 负。样本内 7 胜 0 负。"),
        make_text_run("合富中国洗盘日风险分为 0 放飞，直至过热断板才兑现 +146.86%。", background_color=3),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("护利阈值在 +5.5% 至 +8.0% 区间全单调胜过原版，无参数孤岛问题。"),
        make_text_run("200 次随机权重与双向 20% 扰动中，胜过 V4.0 概率达 100.0%。", background_color=3),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("冷区反包 96% 备选虽可达 2960.91 倍，但 22% 阈值曾误砍捷荣技术。"),
        make_text_run("因此 V4.1 严选零缺陷的纯七项风险开关收紧 +7.0% 作为唯一上线定版。"),
    ]
    blocks.append(make_bullet_block(b3))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：三进四 30 项持仓动态卖点因子分类检验汇总表"
    t1_rows = [
        [[("因子分组与数量", {"bold": True})], [("代表动作与规则", {"bold": True})], [("样本内 / 样本外效果", {"bold": True})], [("最终裁决", {"bold": True})]],
        [[("七项正交风险合成(1)", {"bold": True})], [("满1项13:45破+7.0%护利", {"bold": True})], [("内 5.62x / 外 412.79x", {"bold": True})], [("入选V4.1定版", {"bold": True})]],
        [[("核心三项单因子(3)", {})], [("热度135 / 机构卖2千万 / 爆量3.5x", {})], [("三项样本内外双双正增益", {})], [("入选核心开关", {})]],
        [[("辅助四项单因子(4)", {})], [("一日游 / 新监管 / 300急跌 / 冷反包", {})], [("样本内全胜且扩充池全升", {})], [("入选辅助开关", {})]],
        [[("冷区96%双异动(1)", {})], [("断板反包低于20%且5板挂96%", {})], [("五年2960.91x，22%有回撤", {})], [("列为高风险备选", {})]],
        [[("早盘抢跑与剥夺免死(22)", {})], [("拉萨/游资/换手/监管09:25斩或93%", {})], [("样本外砍飞总龙大亏数百倍", {})], [("全部证伪淘汰", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：三进四 V4.0 原版 vs V4.1 定版全窗口与八项体检对比表"
    t2_rows = [
        [[("评估维度与窗口", {"bold": True})], [("原版 V4.0 (+5.0%)", {"bold": True})], [("定版 V4.1 (七项开关)", {"bold": True})], [("净提升幅度", {"bold": True})]],
        [[("90分 全五年单仓", {"bold": True})], [("1799.99x (回撤31.25%)", {})], [("2319.09x (回撤29.23%)", {"bold": True})], [("升519.1x / 回撤降2.02点", {"bold": True})]],
        [[("90分 百万封顶 / 等权", {})], [("75.49x / 4458.94x", {})], [("79.02x / 5644.80x", {})], [("封顶超额7820.51百分点", {})]],
        [[("90分 样本内 / 样本外", {})], [("4.75x / 379.08x", {})], [("5.62x / 412.79x", {})], [("样本内外同步跑赢原版", {})]],
        [[("90分 近三年 / 2026年", {})], [("533.76x / 3.64x", {})], [("581.22x / 3.74x", {})], [("去前五由105.82x升134.19x", {})]],
        [[("102分极严 / 78分扩充池", {})], [("16.72x / 74.13x", {})], [("17.73x / 112.11x", {})], [("高低档位大样本全面验证", {})]],
        [[("HLZ t / DSR / 地狱压测", {})], [("4.09 / 0.9818 / 297.45x", {})], [("4.20 / 0.9869 / 383.49x", {})], [("200次随机扰动100%胜出", {})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261118 三进四V4.1七项持仓风险因子护利回测",
        "parent_node_token": "NkWqwz0gcicZh0kTxeWciaXmnyg",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
