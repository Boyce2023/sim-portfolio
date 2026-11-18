# -*- coding: utf-8 -*-
"""子文档1：20261117 五年知名游资席位真伪、红黑榜与四大策略沙盒回测"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub1_youzi_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "结论：给四大现行策略新增知名游资名单加减分没用，强加后一进二与二进三净值大跌。",
            background_color=3,
        ),
        make_text_run(
            "但三进四既有席位排雷极有用，贡献超 7 倍净值，滚动营业部口碑也能砍掉近四成大面。",
            background_color=3,
        ),
        make_text_run("新增红黑榜后，一进二五年单仓从 307.01 倍掉至 188.31 倍。"),
        make_text_run("二进三强套游资榜，五年单仓从 131.24 倍腰斩至 40.01 倍。"),
        make_text_run("三进四剥离既有席位规则后，五年净值从 1636.48 倍跌至 235.30 倍。"),
        make_text_run("高标首阴剥离原有 7 项席位规则后，五年净值从 9.98 倍降至 9.24 倍。"),
        make_text_run("全市场 250 日滚动贝叶斯口碑有用。样本外大面率从 21.02% 压至 13.34%。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("全市场五年涨停上榜样本平均次日高开 1.65%，但接力并不赚钱。"),
        make_text_run("剔除一字板买入持有两天扣 30 基点摩擦后，全样本平均倒亏 1.17%。"),
        make_text_run("同花顺与开盘啦双源核对重合率超 99.9%，确保底层龙虎榜零偏差。"),
        make_text_run("滚动贝叶斯得分经过 2024 年底物理截断检验，最大偏差为 0.0。"),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("席位真伪三大发现", bold=True, underline=True),
        make_text_run("，解释了为什么静态名字字典必定大面积失效："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run("顶级游资频繁换马甲迁移，静态历史倒推严重遗漏。", bold=True),
        make_text_run("陈小群从大连金马路切至大连黄河路，若只搜黄河路会漏掉 53.6% 早期上榜。", background_color=3),
        make_text_run("方新侠从兴业陕西分迁至中信西安朱雀大街，上塘路则在 2026 年几乎隐退。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("国泰海通合并更名引发正则大面积失灵，漏判 60% 至 88%。", bold=True),
        make_text_run("2025 年合并后营业部批量改名国泰海通，旧国泰君安正则大面积漏判。", background_color=3),
        make_text_run("作手新一漏判 87.6%，章盟主海阳西路漏判 68.4%，消闲派漏判 60.3%。"),
        make_text_run("今后一切席位库必须绑定底层唯一营业部编码，绝不能只匹配文字简称。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("单日榜与三日榜、真净买与做T砸盘三态差异极大。", bold=True),
        make_text_run("只看人名不看方向极危险，顶级游资转为做T或净卖后大面率直接翻倍。", background_color=3),
        make_text_run("陈小群真净买大面率 21.09%，净卖砸盘时大面率飙至 44.12%。"),
        make_text_run("拉萨真净买大面率 38.11%。反过来拉萨净卖出归主力则减半至 17.60%。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p4_head = [
        make_text_run("四大策略独立沙盒盲测最终裁决", bold=True, underline=True),
        make_text_run("，全部保持现行生产参数不动："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("一进二 V19 首板龙虎榜覆盖率仅 18.18%，强制删拉萨反而误杀牛股。"),
        make_text_run("保持零新增，日内排序微调在近三年对收益几乎零作用。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("二进三 V2.0 专吃低开分歧错配，知名正榜反而推高开盘破坏买点。"),
        make_text_run("贝叶斯口碑压低回撤至 18.64%。但样本外从 11.76 倍降至 10.38 倍。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("三进四 V4.0 现有三项龙虎榜条款是绝对核心，剥离即崩盘。"),
        make_text_run("额外叠加游资榜或贝叶斯分均未跑赢原规则，维持现行 V4.0。"),
    ]
    blocks.append(make_bullet_block(b3))

    b4 = [
        make_text_run("高标首阴 V5.1 既有 7 项席位规则已有效提纯并压低回撤。"),
        make_text_run("外挂精选游资净值反跌至 9.17 倍，外挂贝叶斯与原版完全重叠，维持不变。"),
    ]
    blocks.append(make_bullet_block(b4))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：67 官方游资标签红榜贵人与黑榜毒药对比表（样本数不少于 30）"
    t1_rows = [
        [[("阵营与标签", {"bold": True})], [("上榜数与竞价", {"bold": True})], [("两天净收益与超额", {"bold": True})], [("跨周期属性", {"bold": True})]],
        [[("红榜：涪陵广场路", {})], [("53笔 / 高开1.37%", {})], [("赚 2.05% / 超 3.22点", {})], [("跨周期真稳健贵人", {})]],
        [[("红榜：北京帮", {})], [("131笔 / 高开2.45%", {})], [("赚 1.02% / 超 2.19点", {})], [("大面率仅9.92%，稳健", {})]],
        [[("红榜：徐留胜", {})], [("196笔 / 高开1.32%", {})], [("赚 0.36% / 超 1.53点", {})], [("低吸套利跨周期有效", {})]],
        [[("红榜：上海超短", {})], [("612笔 / 高开1.69%", {})], [("微亏0.01% / 超1.16点", {})], [("大面率10.46%极抗跌", {})]],
        [[("黑榜：N周二与申港广东", {})], [("119笔与67笔", {})], [("亏3.17% / 亏3.16%", {})], [("重度毒药，超额垫底", {})]],
        [[("黑榜：上塘路", {})], [("516笔 / 高开0.87%", {})], [("亏 2.35% / 落1.18点", {})], [("大面率 27.13% 真毒药", {})]],
        [[("黑榜：赵老哥与养家", {})], [("748笔与939笔", {})], [("亏2.07% / 亏2.02%", {})], [("高开透支接力大概率亏损", {})]],
        [[("贝叶斯口碑五分位", {"bold": True})], [("Q5最优 vs Q1最差", {"bold": True})], [("样本外差加 1.09 点", {"bold": True})], [("大面率 21.02% 降至 13.34%", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：四大策略沙盒盲测对比表（30 基点双边摩擦）"
    t2_rows = [
        [[("策略与测试方案", {"bold": True})], [("五年单仓与千万封顶", {"bold": True})], [("胜率与最大回撤", {"bold": True})], [("样本外单仓与裁决", {"bold": True})]],
        [[("一进二：原基准 V19", {"bold": True})], [("307.01x / 53.06x", {"bold": True})], [("67.01% / 16.23%", {"bold": True})], [("60.27x / 维持原版", {"bold": True})]],
        [[("一进二：剔拉萨或毒药", {})], [("188.31x / 46.43x", {})], [("64.21% / 16.30%", {})], [("误杀牛股净值大跌，淘汰", {})]],
        [[("二进三：原基准 V2.0", {"bold": True})], [("131.24x / 40.62x", {"bold": True})], [("50.00% / 29.11%", {"bold": True})], [("11.76x / 保持零席位", {"bold": True})]],
        [[("二进三：套游资红黑榜", {})], [("40.01x / 26.02x", {})], [("44.33% / 54.65%", {})], [("8.89x / 净值腰斩淘汰", {})]],
        [[("二进三：加贝叶斯口碑", {})], [("151.72x / 42.28x", {})], [("48.91% / 18.64%", {})], [("10.38x / 样本外跑输不用", {})]],
        [[("三进四：原基准 V4.0", {"bold": True})], [("1636.48x / 74.30x", {"bold": True})], [("68.42% / 31.52%", {"bold": True})], [("359.10x / 维持原版", {"bold": True})]],
        [[("三进四：剥离全部席位", {})], [("235.30x / 50.72x", {})], [("62.79% / 52.26%", {})], [("147.37x / 暴跌证实有用", {})]],
        [[("高标：基准 vs 剥离", {})], [("9.98x vs 9.24x", {})], [("回撤 38.3% vs 40.0%", {})], [("含熔断11.64x，维持原版", {})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261117 五年知名游资席位真伪、红黑榜与四大策略沙盒回测",
        "parent_node_token": "Jxarwc3wliQZCakXO1xccPmrnCc",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
