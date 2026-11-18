# -*- coding: utf-8 -*-
"""高标首阴真阳反包 V5.1 飞书主文档生成器（V19.1 跨策略版本号与正负号同步版）"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_high_v51_v191_blocks():
    blocks = []

    p1 = [
        make_text_run("高标首阴真阳反包 V5.1 定版，全局第 2 顺位核心主战策略。"),
        make_text_run("全盘仅次于三进四 V4.1，2026 年 7 月起新周期持续有效。"),
        make_text_run("全盘顺位：三进四 > 高标首阴 > 超跌撬板 > 二进三 > 一进二。"),
        make_text_run("对应版本为 V4.1、V5.1、V2.1、V2.1 与 V19。"),
        make_text_run("每天只在 09 点 25 分、11 点 30 分与 14 点 55 分看盘三次。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("这是高标接力的一种，"),
        make_text_run("在窄幅横盘震荡期尤其急跌见底后横盘做，次选急跌期。", background_color=3),
        make_text_run("平时执行底分 60 分满 88 分标准，S 档满 96 分胜率 73.5%。"),
        make_text_run("五年全周期 42 笔胜率 73.8%，盈亏比 3.01，单仓 16.39 倍。"),
        make_text_run("五年回撤 15.9%。纯五分钟精算 42 笔胜率 71.43%，净值 13.41 倍。"),
        make_text_run("显著性 t 值 5.30，缩水夏普概率 98.93%。过拟合概率 PBO 为 0.0%。"),
        make_text_run("近三年 25 笔胜率 76.0%，净值 8.50 倍。剔除前五牛股留存 6.49 倍。"),
        make_text_run("相对沪深300取得 1556.8 个百分点超额。2022 至 2024 年熊市达 2.51 倍。"),
        make_text_run("绝不可以在指数单边阴跌期间做，20 厘米彻底失效绝对禁做。", bold=True, text_color=1),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("买入规则：高标首阴次日低吸承接", bold=True, underline=True),
        make_text_run("，交易守则如下："),
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
        make_text_run("底分 60 分，综合打分满 88 分扣扳机触发。", background_color=3),
        make_text_run("近 10 日反包满 20% 加 12 分否则扣 8 分。涨停少于 70 家加 10 分。"),
        make_text_run("连板期换手满 4 个加 5 分，首阴绿开与买日绿开各加 8 分。"),
        make_text_run("平红开 0.0% 至 +2.5% 加 6 分。满 88 分后按开盘位置挂单。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3_trade = [
        make_text_run("09 点 26 分手操：平红开 0.0% 至 +4.5% 直买。挂今开乘 1.015 限价单。"),
        make_text_run("绿开 -6.5% 至 0.0% 挂今开乘 1.015 条件单。11 点 30 分未成自动撤单。"),
        make_text_run("同日多只标的仅取总分最高者唯一 1 只，严禁分仓。"),
    ]
    blocks.append(make_para_block(p3_trade))

    p4_head = [
        make_text_run("卖出规则：双异动 93% 缓冲预埋与断板清仓", bold=True, underline=True),
        make_text_run("，绝不为新信号提前腾仓："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("买入日封板则次日起执行止盈。"),
        make_text_run("按 10 日与 30 日异动较紧值 93% 预埋止盈。", background_color=3),
        make_text_run("开盘越线在 09 点 25 分竞价止盈，盘中触线自动落袋。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("连板途中"),
        make_text_run("首次真阳断板免死 1 天（限 1 次）", background_color=3),
        make_text_run("，多留一天博反包板。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("其余假阴真阴断板或次日不板，在 14 点 55 分清仓卖出。"),
        make_text_run("买入日未封收真阳且次日低于 -3.5%，09 点 25 分竞价先走。", background_color=3),
    ]
    blocks.append(make_bullet_block(b3))

    p5 = [
        make_text_run("延伸证伪：20 厘米高标、六连板及超级高标均已验证失效。"),
        make_text_run("20 厘米彻底不能做，六连板收益被大幅压缩，超级高标多阴跌腰斩。"),
    ]
    blocks.append(make_para_block(p5))

    p6 = [
        make_text_run("关于"),
        make_text_run("策略的失效问题", bold=True, text_color=1),
        make_text_run("，重点监控"),
        make_text_run("高标断板日拉萨席位与断板跌停率。", background_color=3),
        make_text_run("首阴现 3 至 4 家拉萨、或最后一板现 2 家起拉萨即极危险信号。"),
        make_text_run("断板股跌停率从黄金期 23% 升至寒冬期 43% 时，立即停手空仓。"),
    ]
    blocks.append(make_para_block(p6))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：纯五分钟无前视精算逐年与全周期对比表"
    t1_rows = [
        [[("统计周期", {"bold": True})], [("笔数与胜率", {"bold": True})], [("五分钟单仓收益", {"bold": True})], [("基准与说明", {"bold": True})]],
        [[("2022年", {})], [("11笔 / 63.6%", {})], [("+47.8%", {})], [("沪深300 -19.44%，超额67.26点", {})]],
        [[("2023年", {})], [("6笔 / 66.7%", {})], [("+16.4%", {})], [("逐年全部稳健正收益", {})]],
        [[("2024年", {})], [("2笔 / 100.0%", {})], [("+30.0%", {})], [("低频率严选精准出手", {})]],
        [[("2025年", {})], [("9笔 / 77.8%", {})], [("+105.3%", {})], [("大年翻倍抓核心高标", {})]],
        [[("2026年", {})], [("14笔 / 71.4%", {})], [("+192.0%", {})], [("2026年大盘下逆势近3倍", {})]],
        [[("五年精算(无熔断)", {"bold": True})], [("42笔 / 71.43%", {"bold": True})], [("13.41 倍 (回撤17.8%)", {"bold": True})], [("含两连亏熔断基准为16.39倍", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：高标 V5.1 多窗口、去极值与漏斗筛选表"
    t2_rows = [
        [[("测试维度", {"bold": True})], [("样本与胜率", {"bold": True})], [("净值表现", {"bold": True})], [("回撤与统计核验", {"bold": True})]],
        [[("日频含熔断全五年", {"bold": True})], [("42笔 / 73.8%", {"bold": True})], [("16.39 倍 (盈亏比3.01)", {"bold": True})], [("回撤 15.9%，净超额1556.8点", {"bold": True})]],
        [[("近三年窗口", {})], [("25笔 / 76.0%", {})], [("8.50 倍", {})], [("回撤仅 12.5%", {})]],
        [[("剔除前五牛股去极值", {})], [("37笔 / 70.3%", {})], [("6.49 倍", {})], [("非少数极值驱动", {})]],
        [[("八项体检（5m口径）", {})], [("HLZ t = 5.30", {})], [("DSR 98.93% / PBO 0%", {})], [("地狱压测千万封顶 +237.4%", {})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：第一层硬门槛说明表"
    t3_rows = [
        [[("门槛项", {"bold": True})], [("监控维度", {"bold": True})], [("核心硬指标", {"bold": True})], [("否决物理机制", {"bold": True})]],
        [[("硬门槛 1", {})], [("身位与高度", {})], [("唯一绝对最高板满 4 板", {})], [("排除次高位跟风炮灰", {})]],
        [[("硬门槛 2", {})], [("首阴 K 线", {})], [("首断收真阳且换手不超 35%", {})], [("收盘大于开盘确认承接", {})]],
        [[("硬门槛 3", {})], [("公告排雷", {})], [("零澄清零营收，无监管毒丸", {})], [("近10日监管近90日毒丸否决", {})]],
        [[("硬门槛 4", {})], [("竞价区间", {})], [("-6.5% 至 +4.5%", {})], [("排除恐慌核按钮与高开透支", {})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：第二层 22 项打分卡核心明细表"
    t4_rows = [
        [[("模块分类", {"bold": True})], [("打分细项", {"bold": True})], [("分值增减", {"bold": True})], [("评分物理约束", {"bold": True})]],
        [[("生态大局", {})], [("10日反包满20% / 涨停少70", {})], [("加 12 分 / 加 10 分", {})], [("情绪集中且反包环境友好", {})]],
        [[("生态大局", {})], [("沪深300稳 / 热度低于135", {})], [("加 8 分 / 加 6 分", {})], [("避开系统破位与过热板块", {})]],
        [[("盘口结构", {})], [("换手板4个 / 紧密度35 / 绿承", {})], [("加 5 / 6 / 8 分", {})], [("换手龙生命力强且洗盘充分", {})]],
        [[("股价流值", {})], [("不超20元加5 / 锁仓流值达标", {})], [("加 5 至 6 分", {})], [("超35元扣10分，双不达标扣6", {})]],
        [[("老妖记忆", {})], [("1年内5板 / 老熟 / 格局锁仓", {})], [("加 6 / 3 / 5 分", {})], [("硬蹭新概念扣5，一日游扣6", {})]],
        [[("龙虎席位", {})], [("首阴0拉萨加6 / 量化参与加4", {})], [("2拉萨扣10，买超20%扣10", {})], [("净买过大扣5，机构出现扣6", {})]],
        [[("买日竞价", {})], [("绿开 -6.5% 至 0% / 平红开", {})], [("加 8 分 / 加 6 分", {})], [("绿开挂条件单，平红直买", {})]],
    ]
    tables.append((t4_title, t4_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/feishu_high_v51_20261114/feishu_high_v51_chart1.png"

    return {
        "title": "高标",
        "doc_id": "RrybdVJmQoxfrExuYOacxn8Nn1f",
        "node_token": "KGZww0jBYifjsFk1V8JcOuPrnpe",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
