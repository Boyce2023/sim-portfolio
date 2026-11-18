# -*- coding: utf-8 -*-
"""子文档9：20261118 超跌撬板V2.1四步动态阶梯卖法回测"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub9_pry_exits_v21_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "结论：V2.1 四步动态阶梯卖法非常有用，16 笔胜率跃升至 87.50%。",
            background_color=3,
        ),
        make_text_run(
            "五年单仓由 1.94 倍升至 2.44 倍。回撤由 21.42% 降至 19.15%。",
            background_color=3,
        ),
        make_text_run("平均持仓由 2.81 天缩至 2.06 天。25 日等权升至 3.81 倍。"),
        make_text_run("样本外（近三年）8 笔单仓由 1.26 倍升至 1.49 倍，胜率 87.50%。"),
        make_text_run("150 分扩充池 30 笔单仓升至 2.02 倍。44 日等权升至 3.10 倍。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("30 项候选因子均在 165、150、140 与全基础四池样本内检验。"),
        make_text_run("仅入选四池样本内全胜且样本外同步跑赢的三大核心动态卖点机制。"),
        make_text_run("物理截断至 2025 年前复验全部 693 笔历史信号，偏差严格为 0.0。"),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("核心物理机制：修正死限价单与三大真因子注入", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run("废除连挂四天死限价单，次日不设盖子放飞涨停板。", bold=True),
        make_text_run("旧版从买入次日起即挂固定限价单，刚走强的涨停板常在封板前夜被提前卖飞。", background_color=3),
        make_text_run("第 2 天盘前不挂低位单，封板转连板，未板尾盘低于 -1.5% 清。"),
        make_text_run("如禾盛新材受益转连板接力，单笔收益由旧版 +16.75% 提升至 +24.66%。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("09:25 全场竞价涨停少于 5 家无条件开盘逃命最有用。", bold=True),
        make_text_run("样本内四池全胜，捕捉二次流动性真空熄火（如 2024 年 2 月仅 3 家）。", background_color=3),
        make_text_run("相比之下，昨日跌停满 30 家或首板负溢价砍仓均属滞后恐慌，专洗反弹底部大亏。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("光头强真阳与昨日跌停少于 10 家止血双双加宽止盈空间。", bold=True),
        make_text_run("买日高开阳线且收盘居振幅 70% 上，免尾盘弱斩且止盈加 +3.0%。", background_color=3),
        make_text_run("昨日全场跌停少于 10 家代表市场止血。目标再加 +3.0%，上限 +18.0%。"),
        make_text_run("第 3 天挂 10 日跌幅 0.45 倍止盈。第 4 天 +5.0%，第 5 天 +2.0%。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p4_head = [
        make_text_run("被证伪的伪因子与低开早盘斩对照", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("淘汰次日低于 -2.0% 于 09:25 立斩。尾盘 14:55 低于 -1.5% 更稳。"),
        make_text_run("超跌股早盘常急杀再回弹，09:25 斩低开在四池均跑输，基础池降至 1.36 倍。", background_color=3),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("淘汰一进二涨停紧封裁判、MA5 均线压制及股吧与交易所监管砍仓。"),
        make_text_run("超跌底部首板本就分歧放量换手大，硬套连板紧封门限会将 25 笔底部涨停提前洗出。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("81 宫格双向 20% 扰动中 100.0% 击败 V1.0。77.8% 胜过纯阶梯版。"),
        make_text_run("五顺位合体中，撬板 V2.1 助近三年回撤由 32.12% 降至 29.54%。", background_color=3),
    ]
    blocks.append(make_bullet_block(b3))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：超跌撬板 30 项持仓动态因子四池检验汇总表"
    t1_rows = [
        [[("因子与分组", {"bold": True})], [("规则口径", {"bold": True})], [("165分单仓 / 4池表现", {"bold": True})], [("最终裁决", {"bold": True})]],
        [[("V2.1 终极合成", {"bold": True})], [("涨停<5逃+强阳免斩加3%+止血加3%", {"bold": True})], [("2.44x(87.5%) / 内4/4全胜", {"bold": True})], [("正式定版上线", {"bold": True})]],
        [[("竞价涨停少于5家", {})], [("盘前全场竞价涨停<5家开盘走", {})], [("2.40x / 样本内4池全赢", {})], [("入选(最强救命闸)", {})]],
        [[("买入日收光头强真阳", {})], [("收盘居振幅70%上免弱斩加3%", {})], [("2.36x / 样本内4池全赢", {})], [("入选(强买盘延续)", {})]],
        [[("昨日全场跌停少于10家", {})], [("市场止血后止盈目标再加+3%", {})], [("2.40x / 样本内4池全赢", {})], [("入选(止血拓空间)", {})]],
        [[("次日低开低于-2.0%早斩", {})], [("同台对比14:55低于-1.5%走", {})], [("基础池1.57x跌至1.36x", {})], [("证伪淘汰(割地板)", {})]],
        [[("监管/股吧/MA5/紧封等", {})], [("共24项滞后恐慌与错位规则", {})], [("165分单仓跌至1.62至2.23x", {})], [("全部证伪淘汰", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：超跌撬板 V1.0 vs V2.0 阶梯版 vs V2.1 定版全对照表"
    t2_rows = [
        [[("评估维度", {"bold": True})], [("旧版 V1.0 (死限价)", {"bold": True})], [("上轮 V2.0 (纯阶梯)", {"bold": True})], [("定版 V2.1 (三大因子)", {"bold": True})]],
        [[("165分 全五年单仓", {"bold": True})], [("1.94x / 胜率75.0%", {})], [("2.30x / 胜率81.2%", {})], [("2.44x / 胜率87.50%", {"bold": True})]],
        [[("165分 回撤 / 均持仓", {})], [("21.42% / 2.81天", {})], [("19.15% / 2.19天", {})], [("19.15% / 2.06天", {"bold": True})]],
        [[("165分 样本内 / 外", {})], [("1.54x / 1.26x", {})], [("1.57x / 1.47x", {})], [("1.64x / 1.49x", {"bold": True})]],
        [[("165分 25日等权", {})], [("3.33x (76.0%)", {})], [("3.29x (84.0%)", {})], [("3.81x (88.0%)", {"bold": True})]],
        [[("150分 30笔达标单仓", {})], [("1.26x (样本外0.83x)", {})], [("1.57x (样本外1.01x)", {})], [("2.02x (样本外1.22x)", {"bold": True})]],
        [[("去前三极值 / 3倍滑点", {})], [("1.31x / 不及V2.1", {})], [("1.42x / 1.98x", {})], [("1.46x / 2.23x", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261118 超跌撬板V2.1四步动态阶梯卖法回测",
        "parent_node_token": "OZWdwif0ui7DpWksrwGc3lNRnIh",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
