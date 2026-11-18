# -*- coding: utf-8 -*-
"""超跌橡皮筋撬板 V1.0 飞书主文档生成器（V19.0 第 3 顺位修订版）"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_pry_v10_blocks():
    blocks = []

    p1 = [
        make_text_run("超跌橡皮筋撬板次日弱转强 V1.0 定版，全局第 3 顺位。"),
        make_text_run("排在三进四与高标首阴之后，压在二进三与一进二之前。"),
        make_text_run("核心卡连续暴跌刚止血回暖日，吃超跌撬板弱转强快肉。"),
        make_text_run("每天只在 09 点 25 分与 14 点 55 分看盘两次即可。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("这是超跌反弹弱转强的一种。"),
        make_text_run("在连跌止血回暖与见底初阳执行满 165 分。", background_color=3),
        make_text_run("S 档满 175 分胜率达 82.4%。A 档 165 至 174 分胜率 50.0%。"),
        make_text_run("五年 25 个触发日等权胜率 76.0%。独立单仓 16 笔胜率 75.00%。"),
        make_text_run("近三年胜率 75.0%，2026 年胜率 100.0%。单仓 1.94 倍，回撤 12.8%。"),
        make_text_run("因独立样本仅 16 笔、统计检验 t 值为 1.45 偏弱，仅作窄门辅助。"),
        make_text_run("接入前四策略空仓日实做 11 笔 9 胜 2 负，胜率 81.82%。"),
        make_text_run("V19.0 五顺位中占 10 笔，有效填补退潮空窗期。"),
        make_text_run("绝不可以在近 20 日有过涨停或 20 厘米做，左侧撬板永久禁做。", bold=True, text_color=1),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("买入规则：触跌停撬开次日（Day2）竞价弱转强买入", bold=True, underline=True),
        make_text_run("，守则如下："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run("10 厘米主板非 ST 且昨收满 2 元，昨日触跌停且收盘撬开。", background_color=3),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("：09 点 25 分前查澄清公告，零营收或无关即一票否决。"),
        make_text_run("近 90 日零立案退市违规毒丸，昨日之前近 20 日涨停次数等于 0。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("昨收低于 20 日均线超 15%，较 20 日高点回撤超 20%。", background_color=3),
        make_text_run("今日非一字且开在 0.00% 至涨 5.00% 之间。"),
        make_text_run("十大股东锁仓满 50% 加 10 分，真实流值不超 25 亿加 15 分。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("底分 100 分，十项打分满 165 分扣扳机触发。", background_color=3),
        make_text_run("低 10 日线超 15% 加 20 分。连阴 4 天与低 20 日线超 22% 各加 15 分。"),
        make_text_run("竞价涨停满 12 家加 15 分。昨真阳、放量与机构净买各加 10 分。"),
        make_text_run("昨日拉萨买额占比超 25.0% 直接重扣 20 分。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3_trade = [
        make_text_run("09 点 26 分手操：排在三进四与高标首阴之后，压在二进三与一进二前。"),
        make_text_run("满 165 分挂今开乘 1.015 普通限价单，确保按开盘价成交。"),
        make_text_run("同日多票取总分最高唯一标的，并列取偏离 10 日均线最深者。"),
    ]
    blocks.append(make_para_block(p3_trade))

    p4_head = [
        make_text_run("卖出规则：盘前动态止盈树与第 4 日收盘清仓", bold=True, underline=True),
        make_text_run("，绝不为新信号提前腾仓："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("买入日收盘回封跌停则止损。"),
        make_text_run("次日 09 点 25 分竞价止损。", background_color=3),
        make_text_run("遇一字跌停则顺延至撬开首日。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("买入日封死涨停："),
        make_text_run("转连板持有至断板日收盘清仓", background_color=3),
        make_text_run("。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("常态止盈设盘前限价单。"),
        make_text_run("按前 10 日跌幅 0.45 倍止盈，保底 6% 封顶 16%。", background_color=3),
        make_text_run("自次日起盘前预埋限价卖单，摸线自动落袋，盘中禁撤单。"),
    ]
    blocks.append(make_bullet_block(b3))

    b4 = [
        make_text_run("满 4 个交易日未触线："),
        make_text_run("在第 4 日 14 点 55 分无条件清仓", background_color=3),
        make_text_run("。"),
    ]
    blocks.append(make_bullet_block(b4))

    p5 = [
        make_text_run("延伸证伪：跌停当日盘中或尾盘左侧撬板与 20 厘米撬板永久淘汰。"),
        make_text_run("当日买入次日低开闷杀率超 60% 且五年大亏，20 厘米胜率仅 22.2%。"),
    ]
    blocks.append(make_para_block(p5))

    p6 = [
        make_text_run("关于"),
        make_text_run("策略的失效问题", bold=True, text_color=1),
        make_text_run("，关注"),
        make_text_run("超跌反弹封板率与全市场竞价涨停家数。", background_color=3),
        make_text_run("09 点 25 分全市场竞价涨停不足 12 家或单边踩踏期，严守空仓。"),
        make_text_run("若连续出现 2 笔回封跌停计提则暂停运行。"),
    ]
    blocks.append(make_para_block(p6))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：超跌撬板 V1.0 逐年与多窗口战绩表"
    t1_rows = [
        [[("统计周期", {"bold": True})], [("笔数与胜率", {"bold": True})], [("单仓净值收益", {"bold": True})], [("基准与组合意义", {"bold": True})]],
        [[("2022年", {})], [("5笔 / 80.0%", {})], [("赚 25.0%", {})], [("沪深300跌 21.6%", {})]],
        [[("2023年", {})], [("4笔 / 75.0%", {})], [("赚 18.5%", {})], [("沪深300跌 11.4%", {})]],
        [[("2024年", {})], [("3笔 / 66.7%", {})], [("赚 15.0%", {})], [("沪深300涨 14.8%", {})]],
        [[("2025年", {})], [("2笔 / 50.0%", {})], [("赚 8.0%", {})], [("沪深300涨 17.6%", {})]],
        [[("2026年", {})], [("2笔 / 100.0%", {})], [("赚 22.0%", {})], [("沪深300跌 13.8%", {})]],
        [[("五年独立单仓", {"bold": True})], [("16笔 / 75.00%", {"bold": True})], [("1.94倍 / 回撤12.8%", {"bold": True})], [("按日等权25日胜率76.0%", {"bold": True})]],
        [[("V19.0 第3顺位", {"bold": True})], [("占 10 笔实做", {"bold": True})], [("补位退潮空仓期", {"bold": True})], [("独立t=1.45，仅作窄门辅助", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：超跌撬板漏斗筛选逐层提纯表"
    t2_rows = [
        [[("筛选层级", {"bold": True})], [("触发笔数与胜率", {"bold": True})], [("单笔均值", {"bold": True})], [("累计净值", {"bold": True})]],
        [[("跌停撬开全样本", {})], [("1250笔 / 31.5%", {})], [("亏 2.10%", {})], [("0.18 倍", {})]],
        [[("近20日零涨停纯超跌", {})], [("380笔 / 48.5%", {})], [("赚 0.80%", {})], [("1.15 倍", {})]],
        [[("今日竞价开在0%至5%", {})], [("95笔 / 63.2%", {})], [("赚 4.20%", {})], [("1.45 倍", {})]],
        [[("V1.0 满165分过线", {"bold": True})], [("16笔 / 75.0%", {"bold": True})], [("赚 8.65%", {"bold": True})], [("1.94 倍", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：第一层四道硬门槛说明表"
    t3_rows = [
        [[("门槛项", {"bold": True})], [("监控维度", {"bold": True})], [("具体指标", {"bold": True})], [("否决物理机制", {"bold": True})]],
        [[("硬门槛 1", {})], [("板块与价格", {})], [("10cm主板非ST，昨收满2元", {})], [("排除面值退市仙股", {})]],
        [[("硬门槛 2", {})], [("跌停撬开事实", {})], [("昨日盘中触跌停且收盘撬开", {})], [("确认盘中大资金承接撬板", {})]],
        [[("硬门槛 3", {})], [("纯超跌零涨停", {})], [("近20日0涨停且回撤超20%", {})], [("剔除高位妖股退潮飞刀", {})]],
        [[("硬门槛 4", {})], [("竞价与公告", {})], [("零澄清毒丸，竞价0%至5%", {})], [("弱转强红开确认主动买力", {})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：第二层十项打分卡明细表（底分100分，满165分触发）"
    t4_rows = [
        [[("序号", {"bold": True})], [("打分条件", {"bold": True})], [("分值变化", {"bold": True})], [("物理约束说明", {"bold": True})]],
        [[("1 至 3", {})], [("低10日线15% / 连阴4天 / 低20线22%", {})], [("加 20 / 15 / 15 分", {})], [("超跌乖离越大回弹动能越足", {})]],
        [[("4 至 5", {})], [("真实流值不超25亿 / 竞价板满12家", {})], [("各加 15 分", {})], [("小盘易拉升且大盘情绪回暖", {})]],
        [[("6 至 8", {})], [("昨收真阳 / 放量1.5倍 / 锁仓满50%", {})], [("各加 10 分", {})], [("底部放量换手且浮点筹码轻", {})]],
        [[("9 至 10", {})], [("机构净买加10 / 拉萨买超25%", {})], [("加 10 分 / 扣 20 分", {})], [("机构抄底加分，散户扎堆重罚", {})]],
    ]
    tables.append((t4_title, t4_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/_archive/20261116/old_feishu_drafts/feishu_pry_v10_20261115/feishu_pry_v10_chart1.png"

    return {
        "title": "撬板",
        "doc_id": "WuXLdc9EMoDhaVxyobrcaNNnnwb",
        "node_token": "OZWdwif0ui7DpWksrwGc3lNRnIh",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
