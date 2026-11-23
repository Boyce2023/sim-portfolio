# -*- coding: utf-8 -*-
"""超跌橡皮筋撬板 V2.1 飞书主文档生成器（V19.1 第 3 顺位红队校准核验定版）"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_pry_v21_blocks():
    blocks = []

    p1 = [
        make_text_run("超跌撬板 V2.1 为唯一实盘辅助小策略，位居全局第 3 顺位。"),
        make_text_run("排在三进四与高标首阴之后，压在二进三与一进二之前。"),
        make_text_run("买点与十项打分不变，废除旧版连挂四天死限价单。"),
        make_text_run("改为四步动态阶梯卖法，每日只在 09:25 与 14:55 看盘两次。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("在连跌止血回暖与见底初阳执行满 165 分。", background_color=3),
        make_text_run("全量红队核验原账零违规，16 笔胜率 87.50%（14 胜 2 负）。", background_color=3),
        make_text_run("五年单仓净值 2.44 倍，盈亏比 0.75，均持仓 2.06 天。", background_color=3),
        make_text_run("最大回撤降至 19.15%，跑赢沪深300（-18.49%）达 162.49 点。"),
        make_text_run("95% 置信胜率下界 63.98%，高于盈亏平衡线 57.15%。"),
        make_text_run("25 触发日等权胜率 88.00%，净值 3.81 倍。顺延头名 5.07 倍。"),
        make_text_run("去前三牛股留存 1.46 倍，额外 +80 bps 压测留存 2.15 倍。"),
        make_text_run("近三年样本外 8 笔单仓胜率 87.50%，净值 1.49 倍（+49.01%）。"),
        make_text_run("2026 年 2 笔胜率 100.0%，收益 +9.45%，最大回撤 0.00%。"),
        make_text_run("150 分扩充池 30 笔单仓升至 2.02 倍，81 宫格全胜原版。"),
        make_text_run("绝不可在近 20 日有过涨停或 20 厘米做，左侧撬板永久禁做。", bold=True, text_color=1),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("买入规则：触跌停撬开次日竞价弱转强买入", bold=True, underline=True),
        make_text_run("，十项打分不变："),
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
        make_text_run("今日非一字且开在 0.00% 至 +5.00% 之间。"),
        make_text_run("十大股东锁仓满 50% 加 10 分，真实流值不超 25 亿加 15 分。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("底分 100 分，十项打分满 165 分扣扳机触发，S 档 175 分。", background_color=3),
        make_text_run("低 10 日线超 15% 加 20 分。连阴 4 天与低 20 日线超 22% 各加 15 分。"),
        make_text_run("竞价涨停满 12 家加 15 分。昨真阳、放量与机构净买各加 10 分。"),
        make_text_run("昨日拉萨买额占比超 25.0% 重扣 20 分。09:26 挂今开乘 1.015 买。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p4_head = [
        make_text_run("卖出规则：V2.1 四步动态阶梯卖法（放飞涨停、去弱留强）", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("第一步全局冰点逃命："),
        make_text_run("每日 09:25 竞价涨停少于 5 家，无条件开盘清仓。", background_color=3),
        make_text_run("买入日收盘回封跌停同样次日 09:25 竞价斩仓，一字跌停顺延。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("第二步买入次日放飞与去弱："),
        make_text_run("第 2 天盘前不挂低位止盈单。封涨停转连板至断板清仓。", background_color=3),
        make_text_run("未涨停且无强阳豁免时，14:55 若较前收低于 -1.5% 立即清仓。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("第三步强阳与止血加成："),
        make_text_run("买日收光头强真阳（收盘高于开盘且位居振幅 70% 上）。", background_color=3),
        make_text_run("满足光头强真阳则豁免次日尾盘弱斩，且止盈目标加 +3.0%。"),
        make_text_run("前一日全场跌停少于 10 家止盈目标再加 +3.0%，总上限封顶 +18.0%。"),
    ]
    blocks.append(make_bullet_block(b3))

    b4 = [
        make_text_run("第四步阶梯止盈："),
        make_text_run("第 3 天挂动态止盈单，取前 10 日跌幅绝对值 0.45 倍。", background_color=3),
        make_text_run("第 3 天基准限 +6.0% 至 +16.0% 加成。第 4 天基准降至 +5.0%。"),
        make_text_run("第 5 天基准降至 +2.0% 并叠加加成，14:55 收盘未成交无条件清仓。"),
    ]
    blocks.append(make_bullet_block(b4))

    p5 = [
        make_text_run("延伸证伪：淘汰次日低开 -2.0% 早盘斩与 20 厘米左侧撬板。"),
        make_text_run("超跌反弹股早盘常急杀洗盘再回弹，09:25 砍低开易割在情绪最低点。"),
        make_text_run("20 厘米撬板胜率仅 22.2%，跌停当日左侧撬板闷杀率超 60% 永久禁用。"),
    ]
    blocks.append(make_para_block(p5))

    p6 = [
        make_text_run("关于"),
        make_text_run("策略的失效问题", bold=True, text_color=1),
        make_text_run("，关注"),
        make_text_run("关注信号稀缺期波动（25至26年仅3笔）与回封跌停。", background_color=3),
        make_text_run("前 5 笔占对数收益 83.17%，故严限第 3 顺位作窄门补位。"),
        make_text_run("若连续出现 2 笔回封跌停，立即暂停运行并交研究席复核。"),
    ]
    blocks.append(make_para_block(p6))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：超跌撬板 V2.1 逐年战绩表（165分标准档 16 笔单仓）"
    t1_rows = [
        [[("统计周期", {"bold": True})], [("笔数与胜率", {"bold": True})], [("单仓净值收益", {"bold": True})], [("相对沪深300超额", {"bold": True})]],
        [[("2022年", {})], [("6笔 / 100.0%", {})], [("+62.65%", {})], [("超额 84.28 点（沪深300 -21.63%）", {})]],
        [[("2023年", {})], [("2笔 / 50.0%", {})], [("+0.68%", {})], [("超额 12.06 点（沪深300 -11.38%）", {})]],
        [[("2024年", {})], [("5笔 / 80.0%", {})], [("+17.57%", {})], [("超额 2.89 点（沪深300 +14.68%）", {})]],
        [[("2025年", {})], [("1笔 / 100.0%", {})], [("+15.79%", {})], [("跑输 1.87 点（沪深300 +17.66%）", {})]],
        [[("2026年", {})], [("2笔 / 100.0%", {})], [("+9.45%", {})], [("超额 23.49 点（沪深300 -14.04%）", {})]],
        [[("五年独立单仓", {"bold": True})], [("16笔 / 87.50%", {"bold": True})], [("2.44 倍 (+144.0%)", {"bold": True})], [("回撤19.15% / 超额162.49点", {"bold": True})]],
        [[("25触发日按日等权", {"bold": True})], [("25日 / 88.00%", {"bold": True})], [("3.81 倍 (+281.1%)", {"bold": True})], [("25日顺延头名 5.07x", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：超跌撬板 V1.0 旧版 vs V2.1 定版多窗口对照表"
    t2_rows = [
        [[("对比维度与档位", {"bold": True})], [("旧版 V1.0 (4天死单)", {"bold": True})], [("定版 V2.1 (四步动态)", {"bold": True})], [("核心改善与机制", {"bold": True})]],
        [[("165分 全五年单仓", {"bold": True})], [("1.94x / 75.0% / 回撤21.42%", {})], [("2.44x / 87.5% / 回撤19.15%", {"bold": True})], [("净值升0.50倍，回撤降2.27点", {"bold": True})]],
        [[("165分 近三年 / 2026年", {})], [("近三年 1.26x", {})], [("近三年 1.49x / 2026年 1.09x", {})], [("近三年超额 38.68 点，零违规", {})]],
        [[("165分 25日按日等权", {})], [("3.33x / 胜率76.0%", {})], [("3.81x / 胜率88.0%", {})], [("全市场等权稳健放大", {})]],
        [[("150分 30笔扩充单仓", {})], [("1.26x (样本外0.83x)", {})], [("2.02x (样本外1.22x)", {})], [("补齐30笔统计效力不靠小样本", {})]],
        [[("红队压力与置信检验", {})], [("盈亏比 0.75 / 下界63.98%", {})], [("+80bps 留存 2.15 倍", {})], [("去前三 1.46x / 均持仓2.06天", {})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：V2.1 四步动态阶梯卖法逐日执行表"
    t3_rows = [
        [[("持仓交易日", {"bold": True})], [("09:25 竞价检查", {"bold": True})], [("盘中限价单公式", {"bold": True})], [("14:55 尾盘兜底", {"bold": True})]],
        [[("买入当日", {})], [("09:26 挂今开乘1.015买", {})], [("封涨停转连板至断板", {})], [("回封跌停则次日开盘斩", {})]],
        [[("持仓第 2 天", {"bold": True})], [("全场竞价涨停<5家清仓", {})], [("不挂低位单放飞涨停板", {"bold": True})], [("非光头强阳且低于-1.5%清", {})]],
        [[("持仓第 3 天", {})], [("全场竞价涨停<5家清仓", {})], [("基准+6%至+16%+双3%加成", {})], [("未涨停且低于-1.5%清仓", {})]],
        [[("持仓第 4 天", {})], [("全场竞价涨停<5家清仓", {})], [("基准降至+5.0%+双3%加成", {})], [("未涨停且低于-1.5%清仓", {})]],
        [[("持仓第 5 天", {})], [("全场竞价涨停<5家清仓", {})], [("基准降至+2.0%+双3%加成", {})], [("14:55 收盘无条件清仓", {"bold": True})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：第一层硬门槛与第二层十项打分卡速查表"
    t4_rows = [
        [[("层级与序号", {"bold": True})], [("条件明细", {"bold": True})], [("标准或分值", {"bold": True})], [("物理约束说明", {"bold": True})]],
        [[("硬门槛 1 至 2", {})], [("10cm主板昨收满2元且触跌停撬开", {})], [("强制否决澄清与毒丸", {})], [("确认承接同时排除退市仙股", {})]],
        [[("硬门槛 3 至 4", {})], [("近20日0板且回撤超20%，开0%至+5%", {})], [("弱转强红开区间", {})], [("剔除高位飞刀并确认主动买力", {})]],
        [[("打分 1 至 5", {})], [("低10线15% / 连阴4天 / 低20线22%等", {})], [("加 20 / 15 / 15 / 15 分", {})], [("超跌乖离深配小盘与情绪回暖", {})]],
        [[("打分 6 至 10", {})], [("昨真阳 / 放量 / 锁仓 / 机构 / 拉萨", {})], [("各加10分 / 拉萨超25%扣20", {})], [("底分100满165触发，S档175", {})]],
    ]
    tables.append((t4_title, t4_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/chart_pry_v21.png"

    return {
        "title": "撬板",
        "doc_id": "WuXLdc9EMoDhaVxyobrcaNNnnwb",
        "node_token": "OZWdwif0ui7DpWksrwGc3lNRnIh",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
