# -*- coding: utf-8 -*-
"""超跌橡皮筋撬板 V2.1 飞书主文档生成器（V20.0 机构检验与 CUSUM 红线同步版）"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_pry_v21_v20_blocks():
    blocks = []

    p1 = [
        make_text_run("超跌撬板 V2.1 为唯一辅助小策略，位居 V20.0 第二梯队第 5 顺位。"),
        make_text_run("09:25 竞价直买，压在二进三、一进二周一与 20cm S82 之前。"),
        make_text_run("买点与十项整数不变，人眼两分钟可独立手算，不依赖复杂程序。"),
        make_text_run("采用四步动态阶梯卖法，每日只在 09:25 与 14:55 看盘两次。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("在连跌止血回暖与见底初阳执行满 165 分，S 档 175 分。", background_color=3),
        make_text_run("五年 16 笔胜率 87.50%。单仓 2.44 倍，均持仓 2.06 天。"),
        make_text_run("25 触发日等权胜率 88.00%。净值 3.81 倍，去前三 1.46 倍，回撤 19.15%。"),
        make_text_run("近三年 8 笔胜率 87.50% 得 1.49 倍。2026 年 2 笔全胜得 1.09 倍。"),
        make_text_run("4F Alpha +14.11%，PSR 0.997。WRC p 值 0.038，五折交叉全正。"),
        make_text_run("10% 成交额守卫容量 326 万，单边保本成本 280.6 bps。"),
        make_text_run("实盘须知：年均约 3 笔属极窄门补位，25 年至今仅触发 3 笔。"),
        make_text_run("绝不可在近 20 日有过涨停或 20 厘米做，左侧撬板永久禁做。", bold=True, text_color=1),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("买入规则：触跌停撬开次日竞价弱转强买入", bold=True, underline=True),
        make_text_run("："),
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
        make_text_run("今日非一字且开在 0.00% 至 +5.00%，十大锁仓满 50% 加 10 分。"),
        make_text_run("真实流值不超 25 亿加 15 分，底分 100 分，满 165 分扣扳机触发。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("低 10 日线超 15% 加 20 分。连阴 4 天与低 20 日线超 22% 各加 15 分。", background_color=3),
        make_text_run("竞价涨停满 12 家加 15 分，昨真阳、放量与机构净买各加 10 分。"),
        make_text_run("昨日拉萨买额占比超 25.0% 重扣 20 分。09:26 挂今开乘 1.015 买。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p4_head = [
        make_text_run("卖出规则：V2.1 四步动态阶梯卖法（放飞涨停、去弱留强）", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("第一步冰点逃命：每日 09:25 竞价涨停少于 5 家无条件开盘清仓。", background_color=3),
        make_text_run("买入日收盘回封跌停同样次日 09:25 竞价斩仓，一字跌停顺延。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("第二步次日放飞：第 2 天盘前不挂低位单，封涨停转连板至断板清。", background_color=3),
        make_text_run("未涨停且无光头强阳豁免时，14:55 较前收低于 -1.5% 立即清仓。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("第三步双加成与阶梯止盈：光头强阳或昨跌停少 10 家各加 +3.0% 止盈。", background_color=3),
        make_text_run("第 3 天取前 10 日跌幅绝对值 0.45 倍止盈，上限封顶 +18.0%。"),
        make_text_run("第 4 天基准降至 +5.0%，第 5 天降至 +2.0%。14:55 未成交清仓。"),
    ]
    blocks.append(make_bullet_block(b3))

    p5 = [
        make_text_run("关于"),
        make_text_run("V2.1 失效与 CUSUM 红线", bold=True, text_color=1),
        make_text_run("。禁用 20 厘米撬板与左侧当日抄跌停。"),
        make_text_run("连亏 2 笔黄灯、3 笔红灯。近 10 笔胜率低于 70% 减半，60% 停。", background_color=3),
        make_text_run("近 10 笔均赚低于 +1.32% 黄灯。低于 -0.72% 或累积和达 54.6% 停机。"),
    ]
    blocks.append(make_para_block(p5))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：超跌撬板 V2.1 逐年战绩表（165分标准档 16 笔单仓）"
    t1_rows = [
        [[("统计周期", {"bold": True})], [("笔数与胜率", {"bold": True})], [("单仓净值收益", {"bold": True})], [("相对沪深300超额", {"bold": True})]],
        [[("2022年", {})], [("6笔 / 100.0%", {})], [("+62.65%", {})], [("超额 84.28 点", {})]],
        [[("2023年", {})], [("2笔 / 50.0%", {})], [("+0.68%", {})], [("超额 12.06 点", {})]],
        [[("2024年", {})], [("5笔 / 80.0%", {})], [("+17.57%", {})], [("超额 2.89 点", {})]],
        [[("2025年", {})], [("1笔 / 100.0%", {})], [("+15.79%", {})], [("小幅跑输 1.87 点", {})]],
        [[("2026年", {})], [("2笔 / 100.0%", {})], [("+9.45%", {})], [("超额 23.49 点", {})]],
        [[("五年独立单仓", {"bold": True})], [("16笔 / 87.50%", {"bold": True})], [("2.44 倍 (等权 3.81x)", {"bold": True})], [("回撤19.15% / 超额162.5点", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：V2.1 四步动态阶梯卖法逐日执行表"
    t2_rows = [
        [[("持仓交易日", {"bold": True})], [("09:25 竞价检查", {"bold": True})], [("盘中限价单公式", {"bold": True})], [("14:55 尾盘兜底", {"bold": True})]],
        [[("买入当日", {})], [("09:26 挂今开乘1.015买", {})], [("封涨停转连板至断板", {})], [("回封跌停则次日开盘斩", {})]],
        [[("持仓第 2 天", {"bold": True})], [("全场竞价涨停<5家清仓", {})], [("不挂低位单放飞涨停板", {"bold": True})], [("非光头强阳且低于-1.5%清", {})]],
        [[("持仓第 3 天", {})], [("全场竞价涨停<5家清仓", {})], [("基准+6%至+16%+双3%加成", {})], [("未涨停且低于-1.5%清仓", {})]],
        [[("持仓第 4 天", {})], [("全场竞价涨停<5家清仓", {})], [("基准降至+5.0%+双3%加成", {})], [("未涨停且低于-1.5%清仓", {})]],
        [[("持仓第 5 天", {})], [("全场竞价涨停<5家清仓", {})], [("基准降至+2.0%+双3%加成", {})], [("14:55 收盘无条件清仓", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：V2.1 机构级双套件检验与 CUSUM 红线表"
    t3_rows = [
        [[("检验项目", {"bold": True})], [("实测数据", {"bold": True})], [("黄灯警戒线", {"bold": True})], [("红灯停机线", {"bold": True})]],
        [[("Alpha 与统计", {})], [("4F +14.1% / PSR 0.997", {})], [("连亏满 2 笔", {})], [("连亏满 3 笔 (峰值1)", {})]],
        [[("容量与保本成本", {})], [("326万 / 280.6 bps", {})], [("近10笔均赚 < +1.32%", {})], [("近10笔均赚 < -0.72%", {})]],
        [[("WRC 与五折验证", {})], [("p 0.038 / 5折全正", {})], [("近10笔胜率 < 70.0%", {})], [("近10笔胜率 < 60.0%", {})]],
        [[("稀缺风险与累积和", {})], [("25年起3笔 / 峰值27.6%", {})], [("仅作窄门高胜率补位", {})], [("累积和 S_t >= 54.6%", {})]],
    ]
    tables.append((t3_title, t3_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/chart_pry_v21.png"

    return {
        "title": "撬板",
        "doc_id": "WuXLdc9EMoDhaVxyobrcaNNnnwb",
        "node_token": "OZWdwif0ui7DpWksrwGc3lNRnIh",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
