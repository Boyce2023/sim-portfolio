# -*- coding: utf-8 -*-
"""高标首阴真阳反包 V5.1 飞书主文档生成器（V20.0 机构检验与 CUSUM 红线同步版）"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_high_v51_v20_blocks():
    blocks = []

    p1 = [
        make_text_run("高标首阴真阳反包 V5.1 定版，V20.0 核心龙空衔接主战策略。"),
        make_text_run("满 96 分 S 档排第一梯队第 2 位，仅次于三进四 S 档强占位。"),
        make_text_run("标准 88 分平红开进第二梯队直买，绿开条件单进第三梯队。"),
        make_text_run("每天只在 09 点 25 分、11 点 30 分与 14 点 55 分看盘三次。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run(
            "窄幅横盘或急跌见底期最稳，基本可凭 22 项整数人眼直接算清。",
            background_color=3,
        ),
        make_text_run("五年纯五分钟 42 笔胜率 71.43%。盈亏比 2.83，单仓与等权均 14.75 倍。"),
        make_text_run("去前五留存 5.84 倍，最大回撤 15.94%，Calmar（卡尔玛）4.51。"),
        make_text_run("22 至 24 熊市 19 笔 2.26 倍。近三年 8.78 倍，2026 年 14 笔 2.92 倍。"),
        make_text_run("4F 可交易 Alpha +80.19%（t 4.06）。HLZ t 值 5.40，DSR 0.9909。"),
        make_text_run("过拟合概率 PBO 为 0.0%。容量 7568 万，保本成本 319.7 bps。"),
        make_text_run("实盘警醒：延迟 5 分钟追入曾错失 3 笔强板。净值由 14.75 倍降至 3.23 倍。"),
        make_text_run("绝不在指数单边阴跌期间强做，20 厘米高标彻底失效绝对禁做。", bold=True, text_color=1),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("买入规则：唯一绝对高标首阴次日低吸承接", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run("前日唯一绝对最高板满 4 连板，昨日首断收真阳且换手不超 35%。", background_color=3),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("：09 点 25 分前必查澄清公告，零营收或无关即一票否决。"),
        make_text_run("否决近 10 日监管函、近 90 日毒丸、监管满 2 封与首阴拉萨满 3 家。"),
        make_text_run("次日竞价高于 +4.5% 或低于 -6.5% 一律否决不买。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("股价不超 20 元加 5 分，超 35 元扣 10 分，锁仓或流值达标加 6 分。", background_color=3),
        make_text_run("最高板日格局游资买且首阴锁仓加 5 分，一日游买入扣 6 分。"),
        make_text_run("首阴零拉萨加 6 分，满 2 家扣 10 分，买额满 20% 再扣 10 分。"),
        make_text_run("龙虎榜出现机构扣 6 分，量化参与且拉萨不超 1 家加 4 分。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("底分 60 分满 88 分触发，S 档 96 分，绿开与平红各加 8 与 6 分。", background_color=3),
        make_text_run("近 10 日反包满 20% 加 12 分否则扣 8 分。涨停少于 70 家加 10 分。"),
        make_text_run("平红开 0.0% 至 +4.5% 直买。绿开挂今开乘 1.015 至 11:30 撤。"),
        make_text_run("同日多只仅取最高分 1 只，绝不在 11:30 后追单。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p4_head = [
        make_text_run("卖出规则：双异动 93% 缓冲预埋与断板清仓", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("买入日封板或途中连板后才执行止盈。"),
        make_text_run("按 10 日与 30 日异动较紧值 93% 预埋止盈。", background_color=3),
        make_text_run("未封板当日严禁误套 93% 异动单，开盘越线在 09:25 竞价止盈。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("连板途中"),
        make_text_run("首次真阳断板免死 1 天（限 1 次）", background_color=3),
        make_text_run("。其余断板或未封次日不板，于 14 点 55 分清仓。"),
        make_text_run("收盘封死跌停顺延至可卖日 09:25 出，未封低开低于 -3.5% 先走。"),
    ]
    blocks.append(make_bullet_block(b2))

    p5 = [
        make_text_run("关于"),
        make_text_run("V5.1 失效与 CUSUM 红线", bold=True, text_color=1),
        make_text_run("。首阴现 3 家拉萨或断板跌停率升至 43%，立即停手空仓。"),
        make_text_run("连亏 5 笔黄灯、6 笔红灯。近 15 笔胜率低于 46.7% 减半，40% 停。", background_color=3),
        make_text_run("近 15 笔均赚低于 +2.30% 黄灯。低于 +1.17% 或累积和达 49.9% 停机。"),
    ]
    blocks.append(make_para_block(p5))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：高标首阴 V5.1 纯五分钟真账逐年与全周期对比表"
    t1_rows = [
        [[("统计周期", {"bold": True})], [("笔数与胜率", {"bold": True})], [("单仓净收益", {"bold": True})], [("基准与说明", {"bold": True})]],
        [[("2022年", {})], [("11笔 / 63.64%", {})], [("+45.47%", {})], [("沪深300 -21.63%，超额67.1点", {})]],
        [[("2023年", {})], [("6笔 / 66.67%", {})], [("+19.25%", {})], [("超额30.6点（基准 -11.38%）", {})]],
        [[("2024年", {})], [("2笔 / 100.0%", {})], [("+30.01%", {})], [("超额15.3点（基准 +14.68%）", {})]],
        [[("2025年", {})], [("9笔 / 77.78%", {})], [("+124.06%", {})], [("超额106.4点，稳定翻倍", {})]],
        [[("2026年", {})], [("14笔 / 71.43%", {})], [("+191.88%", {})], [("超额205.9点，回撤仅2.06%", {})]],
        [[("五年全周期", {"bold": True})], [("42笔 / 71.43%", {"bold": True})], [("14.75 倍 (等权同值)", {"bold": True})], [("去前五5.84x / 回撤15.94%", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：第一层硬门槛与第二层 22 项打分核心明细表"
    t2_rows = [
        [[("模块分类", {"bold": True})], [("细项条款", {"bold": True})], [("分值或条件", {"bold": True})], [("物理约束", {"bold": True})]],
        [[("硬门槛 1至2", {})], [("唯一绝对高标>=4板且首阴真阳", {})], [("换手<=35%且零澄清毒丸", {})], [("确认承接并避开退市与次高", {})]],
        [[("硬门槛 3至4", {})], [("监管<2封、拉萨<3家、开-6.5至4.5%", {})], [("任一超限一票否决", {})], [("排除核按钮高开与散户接盘", {})]],
        [[("生态与盘口", {})], [("10日反包20% / 涨停<70 / 热度<135", {})], [("加 12 / 10 / 6 分", {})], [("换手4板加5、首阴绿加8", {})]],
        [[("老妖与席位", {})], [("1年5板加6 / 首阴0拉萨加6", {})], [("2拉萨扣10、一日游扣6", {})], [("买日绿加8、平红加6", {})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：V5.1 机构级双套件检验与 CUSUM 红线表"
    t3_rows = [
        [[("检验项目", {"bold": True})], [("实测数据", {"bold": True})], [("黄灯警戒线", {"bold": True})], [("红灯停机线", {"bold": True})]],
        [[("Alpha 与 DSR", {})], [("4F +80.2% / DSR 0.9909", {})], [("连亏满 5 笔", {})], [("连亏满 6 笔 (峰值2)", {})]],
        [[("容量与保本成本", {})], [("7568万 / 319.7 bps", {})], [("近15笔均赚 < +2.30%", {})], [("近15笔均赚 < +1.17%", {})]],
        [[("+5m 延迟与交叉", {})], [("3笔漏买 / 五折全正", {})], [("近15笔胜率 < 46.7%", {})], [("近15笔胜率 < 40.0%", {})]],
        [[("WRC 与累积和", {})], [("p 0.0002 / 峰值25.8%", {})], [("人工减半排查退化", {})], [("累积和 S_t >= 49.9%", {})]],
    ]
    tables.append((t3_title, t3_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/chart_high_v51_v20.png"

    return {
        "title": "高标",
        "doc_id": "RrybdVJmQoxfrExuYOacxn8Nn1f",
        "node_token": "KGZww0jBYifjsFk1V8JcOuPrnpe",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
