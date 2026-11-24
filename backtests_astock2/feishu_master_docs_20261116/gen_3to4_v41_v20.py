# -*- coding: utf-8 -*-
"""三进四 V4.1 飞书主文档生成器（V20.0 机构检验与 CUSUM 红线同步版）"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_3to4_v41_v20_blocks():
    blocks = []

    p1 = [
        make_text_run("三进四 V4.1 定版，V20.0 全盘头号核心主战策略。"),
        make_text_run("满 102 分 S 档排第一梯队首位，盘中可强占位压制 09:25 直买。"),
        make_text_run("标准 90 分且开盘满 +6.5% 排第二梯队首位，其余盘中单居第三梯队。"),
        make_text_run("每日仅在 09:25、10:30、13:45 与 14:55 看盘四次。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run(
            "命中七项风险满 1 项时，13:45 摸 +8.5% 护利收紧至 +7.0%。",
            background_color=3,
        ),
        make_text_run("顺延 12 笔收盘封死跌停后，五年 95 笔胜率 65.26%，盈亏比 1.95。"),
        make_text_run("纯单仓净值 616.18 倍。按日等权 1167.33 倍，去前五 36.81 倍。"),
        make_text_run("最大回撤 37.00%，Calmar（卡尔玛）7.05。同期沪深300 为 -18.49%。"),
        make_text_run("近三年 58 笔胜率 70.69% 得 200.23 倍。2026 年 18 笔 3.74 倍。"),
        make_text_run("102 分 S 档 31 笔胜率 61.29%。盈亏比 3.50，单仓 15.95 倍。"),
        make_text_run("4F 可交易 Alpha +337.1%（t 4.17）。HLZ t 值 3.56，DSR 0.9052。"),
        make_text_run("10% 成交额守卫容量 3076 万。保本成本 336.3 bps，五折交叉全正。"),
        make_text_run("最大实盘死穴：延后 5 分钟追单将丢掉 20 笔封板，净值跌至 2.26 倍。"),
        make_text_run(
            "高标不足 5 板或前日三板跌停满 2 家防守，禁在冰点闷杀期强做。",
            bold=True,
            text_color=1,
        ),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("买入规则：10cm 主板三连板次日点火，10:30 未触撤单", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run(
            "三板非一字且盘中至少开板 1 次，次日高开 +3.0% 至 +9.2%。",
            background_color=3,
        ),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("：09:25 前排查公告，澄清无关或立案减持监管一票否决。"),
        make_text_run("排除缩量一字加速板，非同日可买三板竞价头名扣 12 分。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run(
            "底分 78 分共 22 项，满 90 分触发。收不超 20 元与前高不超 4 板各加 8。",
            background_color=3,
        ),
        make_text_run("前涨停 35 至 85 家加 5 分。启动前 20 日箱体不超 40% 加 5 分。"),
        make_text_run("买前雪球两日发帖满 4 条重扣 15 分，重点监控与一日游各扣 12 分。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run(
            "09:26 挂 max(昨收乘1.065, 今开) 条件单。10:30 未触发即撤。",
            background_color=3,
        ),
        make_text_run("开盘若已达 +6.5% 直接入第二梯队直买，不留给低顺位抢槽。"),
        make_text_run("同日多只仅取最高分 1 只，必须零延迟扫入以躲避 5 分钟塌方。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p4_head = [
        make_text_run("卖出规则：七项风险开关护利、弱开斩仓与真阳免死", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("未封四板若收阴或次日高开不足 +0.5%，"),
        make_text_run("次日 09:25 竞价立斩清仓。", background_color=3),
        make_text_run("若买入日收红真阳且次日高开满 +0.5%，留至 15:00 未封板再清。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("连板期 13:45 后曾摸 +8.5%，按七项风险开关决定护利线。"),
        make_text_run(
            "命中满 1 项回落破 +7.0% 卖出，0 命中低风险日保持 +5.0% 放飞。",
            background_color=3,
        ),
        make_text_run("核心三项：概念热度满 135 分、机构卖超 2000 万、爆量超 3.5 倍。"),
        make_text_run("辅助四项：一日游买入、新增监管函、大盘急跌、断板反包低于 20%。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("早盘禁看 10:30 均线与 93% 异动单，保留首次真阳免死 1 天限 1 次。"),
        make_text_run("其余断板一律 14:55 收盘清仓，收盘封死跌停顺延至可卖日 09:25 出。"),
    ]
    blocks.append(make_bullet_block(b3))

    p5 = [
        make_text_run("关于"),
        make_text_run("V4.1 在线衰减报警红线", bold=True, text_color=1),
        make_text_run("。前日三板跌停满 2 家或连现 2 次闷杀，必须空仓避险。"),
        make_text_run(
            "连亏 6 笔黄灯、7 笔停机。近 20 笔胜率低于 40% 减半，35% 停。",
            background_color=3,
        ),
        make_text_run("近 20 笔均赚低于 -1.32% 黄灯。低于 -2.86% 或累积和达 192.9% 停机。"),
    ]
    blocks.append(make_para_block(p5))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：三进四 V4.1 逐年真实战绩（五年每年跑赢基准）"
    t1_rows = [
        [[("年份维度", {"bold": True})], [("笔数与胜率", {"bold": True})], [("单仓净收益", {"bold": True})], [("相对沪深300超额", {"bold": True})]],
        [[("2022年", {})], [("22笔 / 63.64%", {})], [("+139.44%", {})], [("超额 161.07 百分点", {})]],
        [[("2023年", {})], [("19笔 / 57.89%", {})], [("+80.96%", {})], [("超额 92.34 百分点", {})]],
        [[("2024年", {})], [("15笔 / 66.67%", {})], [("+343.84%", {})], [("超额 329.16 百分点", {})]],
        [[("2025年", {})], [("21笔 / 71.43%", {})], [("+756.63%", {})], [("超额 738.97 百分点", {})]],
        [[("2026年", {})], [("18笔 / 66.67%", {})], [("+274.02%", {})], [("超额 288.06 百分点", {})]],
        [[("五年全周期", {"bold": True})], [("95笔 / 65.26%", {"bold": True})], [("复利 616.18 倍", {"bold": True})], [("去前五 36.81x / 等权 1167x", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：三进四 V4.1 七项正交持仓风险开关明细表（满1项破+7.0%走）"
    t2_rows = [
        [[("层级分类", {"bold": True})], [("风险因子条款", {"bold": True})], [("判定窗口与口径", {"bold": True})], [("物理逻辑", {"bold": True})]],
        [[("核心 1", {"bold": True})], [("主概念动态热度分满135", {"bold": True})], [("盘前读昨日概念热度", {"bold": True})], [("板块高潮过热后防冲高回落", {})]],
        [[("核心 2", {"bold": True})], [("前日机构席位卖超2000万", {"bold": True})], [("盘前读昨日龙虎榜", {"bold": True})], [("机构大额兑现抛压警惕分歧", {})]],
        [[("核心 3", {"bold": True})], [("前日成交额超5日均量3.5倍", {"bold": True})], [("盘前读昨日量比", {"bold": True})], [("巨量爆表筹码松动锁住浮盈", {})]],
        [[("辅助 4", {})], [("前日一日游砸盘席位买入", {})], [("盘前读昨日龙虎榜", {"bold": True})], [("短线快枪手介入次日易砸盘", {})]],
        [[("辅助 5", {})], [("持仓期间新增个股监管函", {})], [("09:25前公告截断", {})], [("监管压制连板高度防核按钮", {})]],
        [[("辅助 6", {})], [("沪深300昨低于-2%或5日-2.5%", {})], [("盘前指数风控", {})], [("大盘系统性杀跌护利避险", {})]],
        [[("辅助 7", {})], [("近10日高标断板反包低于20%", {})], [("昨日市场生态统计", {})], [("断板接力冷区防炸板深套", {})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：V4.1 22项买入打分卡核心表（底分78分，90分触发）"
    t3_rows = [
        [[("方向", {"bold": True})], [("打分条款", {"bold": True})], [("分值", {"bold": True})], [("核验要点", {"bold": True})]],
        [[("加分", {})], [("三板收不超20元、前高不超4板", {})], [("各加 8 分", {})], [("低价偏好与空间破局核心", {})]],
        [[("加分", {})], [("前涨停35至85家、箱体低位", {})], [("各加 5 分", {})], [("情绪温热且底部无套牢盘", {})]],
        [[("加分", {})], [("首板高开满2家、三板0拉萨", {})], [("各加 4 分", {})], [("梯队支撑与筹码纯净度", {})]],
        [[("加分", {})], [("热度115、0跌停、换手、早封", {})], [("各加 3 分", {})], [("换手9.5%至28%，10:30前封", {})]],
        [[("扣分", {})], [("买前雪球两日发帖满4条", {})], [("扣 15 分", {})], [("盘前散户狂热一致重罚", {})]],
        [[("扣分", {})], [("重点监控、一日游、非头名", {})], [("各扣 12 分", {})], [("监管压制与次位跟风排雷", {})]],
        [[("扣分", {})], [("队友低开、弱锁小流值、换手越界", {})], [("各扣 10 分", {})], [("换手须在8.5%至31%之间", {})]],
        [[("扣分", {})], [("大盘急杀、首板一字、拉萨多", {})], [("扣 8、7、5 分", {})], [("三板跌停与1月5月各扣4分", {})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：V4.1 机构级双套件检验与 CUSUM 红线表"
    t4_rows = [
        [[("检验项目", {"bold": True})], [("实测数据", {"bold": True})], [("黄灯警戒线", {"bold": True})], [("红灯停机线", {"bold": True})]],
        [[("Alpha 与 DSR", {})], [("4F +337.1% / DSR 0.905", {})], [("连亏满 6 笔", {})], [("连亏满 7 笔 (峰值2)", {})]],
        [[("容量与保本成本", {})], [("3076万 / 336.3 bps", {})], [("近20笔均赚 < -1.32%", {})], [("近20笔均赚 < -2.86%", {})]],
        [[("+5m 延迟实盘风险", {})], [("20笔漏买跌至 2.26x", {})], [("近20笔胜率 < 40.0%", {})], [("近20笔胜率 < 35.0%", {})]],
        [[("WRC / 五折 / CUSUM", {})], [("p 0.0006 / 5全正", {})], [("历史峰值 67.2%", {})], [("累积和 S_t >= 192.9%", {})]],
    ]
    tables.append((t4_title, t4_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/chart_3to4_v41_v20.png"

    return {
        "title": "三进四",
        "doc_id": "SFPVd9gSgoN33SxMsUHc4xJNnVf",
        "node_token": "NkWqwz0gcicZh0kTxeWciaXmnyg",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
