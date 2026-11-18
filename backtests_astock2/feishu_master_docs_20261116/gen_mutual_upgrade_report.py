# -*- coding: utf-8 -*-
"""三大连板策略跨板位互学升级五年实证报告飞书主文档生成器"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_mutual_upgrade_report_blocks():
    blocks = []

    # 第 1 段：核心总结论（首句说有用没用与量化效果并标黄）
    p1 = [
        make_text_run(
            "结论：跨板位物理机制互学升级非常有用，三策略净值与稳健度全面大涨。",
            background_color=3,
        ),
        make_text_run(
            "三进四升至 1799.99 倍，一进二回撤 15.97%。二进三升至 144.21 倍转正。",
            background_color=3,
        ),
        make_text_run("三进四 V4.0 百万封顶从 61.62 倍升至 75.49 倍。"),
        make_text_run("一进二 V19 单仓升至 338.37 倍，百万封顶 54.57 倍。"),
        make_text_run("二进三 V2.0 回撤从 36.72% 降至 28.68%，入列第 4 顺位。"),
        make_text_run(
            "三策略 150 次试验缩水夏普概率 DSR 全过 95% 红线，无过拟合虚胖。",
            background_color=3,
        ),
    ]
    blocks.append(make_para_block(p1))

    # 第 2 段：为什么可以跨板位互学（第一性原理物理机制）
    p2 = [
        make_text_run("为什么不同连板可以互相学习？"),
        make_text_run("因它们同属主板连板接力生态。"),
        make_text_run("底层决定盈亏的筹码锁仓、资金性质与散户拥挤度规律完全相通。"),
        make_text_run(
            "互学只迁移经过对手盘检验的物理约束，绝不跨板位硬搬绝对分数。",
            background_color=3,
        ),
        make_text_run("过去各自独立迭代留下了盲区，拉通互看后补齐了短板并砍掉冗余。"),
    ]
    blocks.append(make_para_block(p2))

    # 第 3 段：六大跨板位物理机制与对手盘验证总起
    p3_head = [
        make_text_run("六项互学升级机制与对手盘实证", bold=True, underline=True),
        make_text_run("，每一项改法都同时查验了买方与卖方双向收益："),
    ]
    blocks.append(make_para_block(p3_head))

    # 有序列表 6 条
    o1 = [
        make_text_run("低位起跳加分：启动前 20 日箱体低位不超 40% 加 5 分。", bold=True),
        make_text_run("三进四吸收一进二该因子，优先抓无套牢盘阻挡的新龙。", background_color=3),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("盘前雪球拥挤排雷：买日 09 点 25 分前满 4 帖扣 15 分。", bold=True),
        make_text_run("二板次日热议满 4 帖时，接盘买家胜率跌至 25.8%。", background_color=3),
        make_text_run("这类高热度二板买家样本外均亏 3.76%，而卖方均赚 4.31%。"),
        make_text_run("三板次日热议满 4 帖触发接盘买家胜率仅 12.5%，均亏 4.03%。"),
        make_text_run("早盘散户热烈讨论的高位板本质就是先手资金派发接盘坟场。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("跨界硬科技暗牌与 15 日新词破冰：二进三吸收各加 4 分。", bold=True),
        make_text_run("专门捕捉市场认知未满、估值弹性大的首波加速牛股。", background_color=3),
        make_text_run("同时对冲退潮一日游、尾盘 14 点半偷袭与首板一字透支各扣 6 至 8 分。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    o4 = [
        make_text_run("一进二暗牌低开弱斩豁免：针对封死二板次日温和开盘区。", bold=True),
        make_text_run("开在跌 6.5% 至涨 2.5% 且雪球少于 4 帖、封成比低 25%。", background_color=3),
        make_text_run("说明筹码尚未过热派发，豁免 10 点 30 分破均价线弱斩。"),
        make_text_run("改拿至收盘未板再清仓，回撤直接从 21.98% 降至 15.97%。"),
    ]
    blocks.append(make_ordered_block(o4, seq="auto"))

    o5 = [
        make_text_run("三进四 10 点半撤单收紧：突破单由 11 点半提至 10 点半。", bold=True),
        make_text_run("直接踢走十点半后主力弱转强失败的诱多偷袭。", background_color=3),
        make_text_run("既留住放量干脆上板的强龙，又避免午盘前炸板吃面。"),
    ]
    blocks.append(make_ordered_block(o5, seq="auto"))

    o6 = [
        make_text_run("二进三出场精修：未封死三板取消低开 0.5% 竞价乱割。", bold=True),
        make_text_run("统一拿至次日收盘清仓，避免卖在早盘恐慌地板。"),
        make_text_run("封死三板次日若高开超 9.2% 且非一字，09 点 25 分止盈。"),
        make_text_run("样本外高开超 9.2% 接力买家胜率仅 30.3%。"),
        make_text_run("这类极高开接盘触发后平均亏损达 5.66%，止盈落袋最稳。"),
    ]
    blocks.append(make_ordered_block(o6, seq="auto"))

    # 第 4 段：因子剪枝与克制边界
    p4_head = [
        make_text_run("瘦身剪枝与严防过拟合纪律", bold=True, underline=True),
        make_text_run("，该砍就砍、绝不为了凑漂亮数字强改："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("三进四剔除周几、全市场涨停家数与 32 元股价 3 项冗余。"),
        make_text_run("叠加新增 2 项互学项后收口为 22 项正交整数因子。", background_color=3),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("二进三删去旧波段项，补入锁仓真换手与暗牌 5 项。"),
        make_text_run("最终收口为 18 项正交整数因子，同步设 96 分顶部提醒。", background_color=3),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("高标首阴与超跌撬板实测剪枝会伤害样本外收益。"),
        make_text_run("严格保持原结构零强行改动，绝不为了凑数瞎改参数。", background_color=3),
    ]
    blocks.append(make_bullet_block(b3))

    # 第 5 段：物理截断与八项防过拟合扎实验证
    p5 = [
        make_text_run(
            "2025 年 1 月 1 日起执行物理数据截断检验，阻断一切前视信息。",
            background_color=3,
        ),
        make_text_run("三策略自截断日以来的最大收益偏差全部严格为 0.0。"),
        make_text_run("其中三进四 56 笔、一进二 54 笔、二进三 98 笔均完全一致。"),
        make_text_run("三策略正负 20% 参数扰动与 200 次蒙特卡洛抽样 100% 盈利。"),
        make_text_run("一进二 255 天五分钟线覆盖率 100%。"),
        make_text_run("三进四买日五分钟线覆盖率同样达 100%。"),
    ]
    blocks.append(make_para_block(p5))

    # 第 6 段：缺点坦白与风险边界
    p6 = [
        make_text_run("关于"),
        make_text_run("升级后仍须盯紧的短板", bold=True, text_color=1),
        make_text_run("，主要是"),
        make_text_run("二进三在机构抱团趋势年份的周期适应性局限", background_color=3),
        make_text_run("。"),
        make_text_run("2025 年二进三 90 分档仅 8 笔胜率 25.00%，小赚 4.41%。"),
        make_text_run("当年跑输涨 17.66% 的沪深300 达 13.25 个百分点。"),
        make_text_run("因此二进三经 120 排列实证列第 4 顺位，压在一进二之前。"),
    ]
    blocks.append(make_para_block(p6))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格（严格 <= 4 列，细胞 <= 32 字）
    tables = []

    t1_title = "附录：互学升级前后五年全周期净值与回撤对比表"
    t1_rows = [
        [[("策略版本对照", {"bold": True})], [("五年笔数与胜率", {"bold": True})], [("单仓 / 百万封顶 / 盈亏比", {"bold": True})], [("回撤与单仓超额基准", {"bold": True})]],
        [[("三进四 V3.4", {})], [("89笔 / 64.04%", {})], [("537.53x / 61.62x / 2.27", {})], [("31.25% / 超额53671.63点", {})]],
        [[("三进四 V4.0", {"bold": True})], [("95笔 / 68.42%", {"bold": True})], [("1799.99x / 75.49x / 2.14", {"bold": True})], [("31.25% / 超额179917.80点", {"bold": True})]],
        [[("一进二 V18", {})], [("96笔 / 68.75%", {})], [("328.91x / 54.14x / 2.79", {})], [("21.98% / 超额32809.49点", {})]],
        [[("一进二 V19", {"bold": True})], [("97笔 / 68.04%", {"bold": True})], [("338.37x / 54.57x / 2.87", {"bold": True})], [("15.97% / 超额33755.34点", {"bold": True})]],
        [[("二进三 V1.0(90)", {})], [("77笔 / 48.05%", {})], [("20.32x / 千万4.99x / 3.40", {})], [("36.72% / 超额1950.49点", {})]],
        [[("二进三 V2.0(90)", {"bold": True})], [("94笔 / 52.13%", {"bold": True})], [("144.21x / 41.65x / 4.01", {"bold": True})], [("28.68% / 超额14339.49点", {"bold": True})]],
        [[("二进三 V2.0(96)", {"bold": True})], [("35笔 / 54.29%", {"bold": True})], [("17.43x / 16.98x / 6.10", {"bold": True})], [("15.87% / 超额1661.49点", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：近三年与 2026 年样本外真实净超额对比表"
    t2_rows = [
        [[("策略版本与窗口", {"bold": True})], [("笔数与胜率", {"bold": True})], [("单仓净倍数与回撤", {"bold": True})], [("相对沪深300净超额", {"bold": True})]],
        [[("三进四 V4.0 近3年", {"bold": True})], [("58笔 / 72.41%", {"bold": True})], [("533.76x / 回撤23.82%", {"bold": True})], [("跑赢 53265.45 百分点", {"bold": True})]],
        [[("三进四 V4.0 2026年", {})], [("18笔 / 66.67%", {})], [("3.64x / 回撤17.28%", {})], [("跑赢 278.13 百分点", {})]],
        [[("一进二 V19 近3年", {"bold": True})], [("51笔 / 68.63%", {"bold": True})], [("63.43x / 回撤13.83%", {"bold": True})], [("跑赢 6232.60 百分点", {"bold": True})]],
        [[("一进二 V19 2026年", {})], [("21笔 / 80.95%", {})], [("3.15x / 回撤4.03%", {})], [("跑赢 228.84 百分点", {})]],
        [[("二进三90 近3年", {})], [("51笔 / 47.06%", {})], [("9.83x / 回撤24.58%", {})], [("跑赢 872.67 百分点", {})]],
        [[("二进三90 2026年", {})], [("14笔 / 64.29%", {})], [("4.33x / 回撤7.12%", {})], [("跑赢 347.04 百分点", {})]],
        [[("二进三96 2026年", {"bold": True})], [("6笔 / 83.33%", {"bold": True})], [("2.67x / 回撤5.04%", {"bold": True})], [("跑赢 181.04 百分点", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：跨板位互学核心机制与对手盘实证统计表"
    t3_rows = [
        [[("验证机制", {"bold": True})], [("适用对象与触发", {"bold": True})], [("对手盘买家实证", {"bold": True})], [("对应策略动作", {"bold": True})]],
        [[("买前雪球热帖排雷", {})], [("二板与三板买前满4帖", {})], [("二板25.8% / 三板12.5%", {})], [("三进四扣15分 / 免死剔除", {})]],
        [[("极高开接盘过热", {})], [("三板次日非一字高开超9.2%", {})], [("样本外胜率30.3%均亏5.66%", {})], [("二进三9.2%以上竞价止盈", {})]],
        [[("二板温和开盘不斩", {})], [("二板开跌6.5%至涨2.5%暗牌", {})], [("低热度低封成仍具承接", {})], [("一进二回撤降6.01百分点", {})]],
        [[("三进四早盘防偷袭", {})], [("突破条件单撤单时点", {})], [("十点半后突破质量骤降", {})], [("撤单由11:30提前至10:30", {})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：八项防过拟合检验与 2025 年物理截断总表"
    t4_rows = [
        [[("检验指标", {"bold": True})], [("三进四 V4.0", {"bold": True})], [("一进二 V19", {"bold": True})], [("二进三 V2.0(90)", {"bold": True})]],
        [[("显著性 HLZ t值", {})], [("4.09 (原3.54)", {})], [("4.08 (原4.07)", {})], [("3.83 (原2.53)", {})]],
        [[("缩水夏普 DSR", {})], [("98.18% 过线", {})], [("99.45% 稳过", {})], [("95.76% 过线", {})]],
        [[("过拟合概率 PBO", {})], [("阶梯 0.0% / 3.57%", {})], [("6.75% (原9.13%)", {})], [("阶梯 5.56%", {})]],
        [[("地狱压测单仓", {})], [("留存 297.45 倍", {})], [("留存 80.01 倍", {})], [("留存 38.05 倍", {})]],
        [[("2025年起物理截断", {})], [("56笔偏差 0.0", {})], [("54笔偏差 0.0", {})], [("98笔偏差 0.0", {})]],
    ]
    tables.append((t4_title, t4_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/chart_mutual_upgrade_3strategies.png"

    return {
        "title": "三大连板策略跨板位互学升级五年实证报告",
        "doc_id": "ErCzdovDLoPGA3xYOqWc7oUmnvc",
        "node_token": "QlJuwfCZVitkhMkPB1ecJ815n1g",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
