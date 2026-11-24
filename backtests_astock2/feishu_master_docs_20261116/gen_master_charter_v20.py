# -*- coding: utf-8 -*-
"""A股短线六策略体系总纲（V20.0 定版）飞书主文档生成器"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def make_shell_code_block(cmd_text: str):
    return {
        "block_type": 14,
        "code": {
            "elements": [{"text_run": {"content": cmd_text, "text_element_style": {}}}],
            "style": {"language": 60, "wrap": True},
        },
    }


def build_master_charter_v20_blocks():
    blocks = []

    p1 = [
        make_text_run("本总纲为 A 股机械账 V20.0 定版，统管六大实盘纯单仓策略。"),
        make_text_run("永远只做纯单仓，旧仓平仓后按三梯队买点时序分配唯一槽位。"),
        make_text_run(
            "冠军规则：第一梯队S档强占位优先，第二梯队 09:25 直买压制第三梯队。",
            background_color=3,
        ),
        make_text_run("第一梯队只有三进四满 102 分与高标首阴满 96 分可盘中强占位。"),
        make_text_run("第二梯队 09:25 确定直买六席，第三梯队盘中条件单让位第二梯队。"),
        make_text_run("20cm A 档 76 至 81 分仅做观察，四进五下放研发不上实盘。"),
        make_text_run("六策略百分百独立评分与独立出场，严禁跨策略混卖或中途抢槽。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("全盘统一报纯单仓复利与按日等权口径，永久剔除一切人为截断。"),
        make_text_run(
            "V20.0 合体五年 278 笔胜率 65.11%。盈亏比 2.70，单仓 6913.41 万倍。",
            background_color=3,
        ),
        make_text_run("剔除前五大牛股留存 188.73 万倍。交易回撤 41.21%，日回撤 47.27%。"),
        make_text_run("年化 Sharpe 4.75，Calmar（卡尔玛）75.65。同期沪深300 回报 -18.49%。"),
        make_text_run("OOS（样本外）120 笔净值 5648.47 倍。胜率 64.17%，Sharpe 5.10。"),
        make_text_run("2026 年以来合体 53 笔胜率 66.04%。净值 27.78 倍，回撤 17.59%。"),
        make_text_run("10% 成交额守卫容量 2532 万。HLZ t 值 7.10，DSR 满分 1.00。"),
        make_text_run("6 策略日收益平均相关性仅 0.0247，五折清洗交叉验证五折全正。"),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("六大实盘策略生态位与 V20.0 最新定版基准", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run("三进四 V4.1：主板三连板分歧转强龙头战法。", bold=True),
        make_text_run("满 102 分入第一梯队强占位，满 90 分入二或三梯队。", background_color=3),
        make_text_run("95 笔胜率 65.26%，单仓 616.18 倍。去前五 36.81 倍，容量 3076 万。"),
        make_text_run("实盘死穴：延后 5 分钟追单将失去 20 笔封板机会，净值暴跌至 2.26 倍。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("高标首阴 V5.1：唯一绝对最高板首阴真阳低吸。", bold=True),
        make_text_run("满 96 分入第一梯队，88 分平红开二梯队，绿开三梯队。", background_color=3),
        make_text_run("42 笔胜率 71.43%，单仓与等权均 14.75 倍。回撤 15.94%，容量 7568 万。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("超跌撬板 V2.1：20 日深度急跌触跌停撬开弱转强。", bold=True),
        make_text_run("满 165 分于 09:25 直买，压在二进三与一进二之前。", background_color=3),
        make_text_run("16 笔胜率 87.50%，单仓 2.44 倍。均持仓 2.06 天，回撤 19.15%。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    o4 = [
        make_text_run("二进三 V2.1：主板二连板次日 09:25 换手低吸承接。", bold=True),
        make_text_run("底分 60 分共 18 项，标准 90 分直买，96 分高盈亏比重点提醒。", background_color=3),
        make_text_run("95 笔胜率 53.68%，盈亏比 4.57。单仓 404.71 倍，去前五 44.01 倍。"),
    ]
    blocks.append(make_ordered_block(o4, seq="auto"))

    o5 = [
        make_text_run("一进二 V20：新增 20cm 清洁首板低开防抽血扣 25 分。", bold=True),
        make_text_run("周一 09:25 断层进二梯队，日常 11:30 撤单条件单排三梯队。", background_color=3),
        make_text_run("92 笔胜率 71.74%，单仓 474.35 倍。回撤 13.31%，OOS（样本外）63.80 倍。"),
    ]
    blocks.append(make_ordered_block(o5, seq="auto"))

    o6 = [
        make_text_run("20cm V1.1：创业板科创板首板次日深水错杀低吸。", bold=True),
        make_text_run("S 档满 82 分直买入二梯队末位。A 档 76 至 81 分仅在早报观察。", background_color=3),
        make_text_run("S82 六年 199 笔胜率 57.79%，单仓 468.29 倍。与一进二相关仅 0.015。"),
    ]
    blocks.append(make_ordered_block(o6, seq="auto"))

    p4_head = [
        make_text_run("脱离 AI 独立运行与人眼手算复现指南", bold=True, underline=True),
        make_text_run("：即便离线，仍可完整算清六大策略："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("纯人眼可直接手算（3 套）：", bold=True),
        make_text_run("20cm、撬板与高标均用整数与盘口打分。人眼三分钟可算完。", background_color=3),
        make_text_run("高标仅有板块热度一项可用开盘啦热榜前排替代估算。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("半人眼半本地（0.5 套）：", bold=True),
        make_text_run("三进四共 29 项打分与风控。其中 27 项可用眼睛直接核对。", background_color=3),
        make_text_run("唯一依赖程序的是主概念八年动态热度是否达到 115 分或 135 分。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("全靠本地程序（2 套）：", bold=True),
        make_text_run("二进三与一进二依赖八年动态概念库、五分封成比与历史分位。", background_color=3),
        make_text_run("每日开盘 09:25 至 09:26 运行下方早盘命令行，自动排出唯一买单。"),
    ]
    blocks.append(make_bullet_block(b3))

    p_cmd1 = [make_text_run("早盘 09:25 一键扫盘出单命令（脱离 AI 直接运行）：", bold=True)]
    blocks.append(make_para_block(p_cmd1))
    blocks.append(make_shell_code_block("cd ~/claude-projects && /opt/homebrew/bin/python3.13 sim-portfolio/scripts/daily_3strategies_score_report.py"))

    p_cmd2 = [make_text_run("盘后 15:30 全链路行情与 PIT（点时点）公告同步命令：", bold=True)]
    blocks.append(make_para_block(p_cmd2))
    blocks.append(make_shell_code_block("cd ~/claude-projects && /opt/homebrew/bin/python3.13 sim-portfolio/scripts/rd_master_trading_data_sync.py"))

    p5 = [
        make_text_run("在线衰减监控红线："),
        make_text_run("六策略均标定五千次抽样红线。触黄灯减半仓，触红灯停仓。", background_color=3),
        make_text_run("合体近 20 笔连亏 7 笔或胜率低于 35% 亮黄灯。连亏 8 笔或低于 30% 停机。"),
    ]
    blocks.append(make_para_block(p5))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：V20.0 六策略三梯队买点时序精细化顺位表"
    t1_rows = [
        [[("梯队与顺位", {"bold": True})], [("策略与门槛", {"bold": True})], [("买点时序与撤单", {"bold": True})], [("核心卖法与熔断", {"bold": True})]],
        [[("一梯队 1", {"bold": True})], [("三进四 S>=102", {"bold": True})], [("10:30 突破抢占位", {})], [("7项风控收紧+7.0%", {})]],
        [[("一梯队 2", {"bold": True})], [("高标首阴 S>=96", {})], [("平红直买 / 绿开 11:30", {})], [("封板双异动93%缓冲", {})]],
        [[("二梯队 3至4", {})], [("三进四>=6.5% / 高标红开", {})], [("09:25 竞价确定直买", {})], [("不等待盘中不确定性", {})]],
        [[("二梯队 5至6", {})], [("撬板>=165 / 二进三>=90", {})], [("09:25 竞价直买", {})], [("涨停<5逃命 / 护+6.5%", {})]],
        [[("二梯队 7至8", {})], [("一进二周一 / 20cm S>=82", {})], [("09:25 竞价直买", {})], [("昨20cm板满16家熔断", {})]],
        [[("三梯队 9至11", {})], [("三四A / 高标绿 / 一二V20", {})], [("盘中突破条件单", {})], [("让位一切二梯队直买", {})]],
        [[("仅观察不上仓", {})], [("20cm A 档 76 至 81 分", {})], [("只在早报提示情绪", {})], [("四进五下放研发池", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：六策略与合体 V20.0 净值、OOS（样本外）与容量总表"
    t2_rows = [
        [[("策略版本", {"bold": True})], [("笔数 / 胜率 / 盈亏比", {"bold": True})], [("全期单仓 / 去前五", {"bold": True})], [("OOS（样本外）/ 10%容量", {"bold": True})]],
        [[("三进四 V4.1", {})], [("95笔 / 65.26% / 1.95", {})], [("616.18x / 36.81x", {})], [("近3年200.23x / 3076万", {})]],
        [[("高标首阴 V5.1", {})], [("42笔 / 71.43% / 2.83", {})], [("14.75x / 5.84x", {})], [("近3年8.78x / 7568万", {})]],
        [[("超跌撬板 V2.1", {})], [("16笔 / 87.50% / 0.75", {})], [("2.44x / 去三1.46x", {})], [("近3年1.49x / 326万", {})]],
        [[("二进三 V2.1", {})], [("95笔 / 53.68% / 4.57", {})], [("404.71x / 44.01x", {})], [("近3年15.23x / 2417万", {})]],
        [[("一进二 V20", {"bold": True})], [("92笔 / 71.74% / 3.21", {"bold": True})], [("474.35x / 35.04x", {"bold": True})], [("63.80x / 3228万", {"bold": True})]],
        [[("20cm V1.1 S82", {"bold": True})], [("199笔 / 57.79% / 2.01", {"bold": True})], [("468.29x / 104.06x", {"bold": True})], [("3.94x(A档13.1x)/1797万", {"bold": True})]],
        [[("合体 V20.0", {"bold": True})], [("278笔 / 65.11% / 2.70", {"bold": True})], [("6913万x / 188.7万x", {"bold": True})], [("5648.5x / 2532万", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：六策略与合体回撤、Alpha 与统计显著性检验总表"
    t3_rows = [
        [[("策略版本", {"bold": True})], [("最大回撤 / Calmar（卡尔玛）", {"bold": True})], [("4F可交易Alpha (t值)", {"bold": True})], [("DSR / 5折交叉 / 保本成本", {"bold": True})]],
        [[("三进四 V4.1", {})], [("37.00% / 7.05", {})], [("+337.1% (4.17)", {})], [("0.905 / 5全正 / 336bps", {})]],
        [[("高标首阴 V5.1", {})], [("15.94% / 4.51", {})], [("+80.2% (4.06)", {})], [("0.991 / 5全正 / 320bps", {})]],
        [[("超跌撬板 V2.1", {})], [("19.15% / 1.02", {})], [("+14.1% (1.60)", {})], [("PSR 0.997 / 5全正 / 281", {})]],
        [[("二进三 V2.1", {})], [("28.68% / 8.10", {})], [("+319.2% (4.79)", {})], [("0.993 / 5全正 / 316bps", {})]],
        [[("一进二 V20", {})], [("13.31% / 18.23", {})], [("+141.4% (5.37)", {})], [("0.9995 / PBO 1.4% / 333", {})]],
        [[("20cm V1.1 S82", {})], [("26.70% / 6.91", {})], [("+120.2% (5.16)", {})], [("0.9988 / WRC 0 / 167", {})]],
        [[("合体 V20.0", {"bold": True})], [("47.27% / 75.65", {"bold": True})], [("+419.6% (9.03)", {"bold": True})], [("1.00 / 5全正 / 325bps", {"bold": True})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：六策略与合体 CUSUM 在线衰减报警红线表"
    t4_rows = [
        [[("策略(窗口N)", {"bold": True})], [("连亏黄 / 红灯", {"bold": True})], [("近N笔均收益黄/红", {"bold": True})], [("胜率红 / 累积和红线(峰值)", {"bold": True})]],
        [[("三进四 (20)", {})], [("6 笔 / 7 笔", {})], [("<-1.32% / <-2.86%", {})], [("<35.0% / 192.9% (67.2%)", {})]],
        [[("高标 (15)", {})], [("5 笔 / 6 笔", {})], [("<+2.30% / <+1.17%", {})], [("<40.0% / 49.9% (25.8%)", {})]],
        [[("撬板 (10)", {})], [("2 笔 / 3 笔", {})], [("<+1.32% / <-0.72%", {})], [("<60.0% / 54.6% (27.6%)", {})]],
        [[("二进三 (20)", {})], [("9 笔 / 10 笔", {})], [("<+0.06% / <-0.91%", {})], [("<25.0% / 121.2% (76.7%)", {})]],
        [[("一进二 V20 (20)", {"bold": True})], [("5 笔 / 6 笔", {"bold": True})], [("<+1.12% / <+0.26%", {"bold": True})], [("<40.0% / 91.7% (40.6%)", {"bold": True})]],
        [[("20cm S82 (20)", {"bold": True})], [("9/10(5Y 8/9)", {"bold": True})], [("<-1.94% / <-2.65%", {"bold": True})], [("<25.0% / 124.7% (51.1%)", {"bold": True})]],
        [[("合体 V20.0 (20)", {"bold": True})], [("7 笔 / 8 笔", {"bold": True})], [("<-1.14% / <-2.15%", {"bold": True})], [("<30.0% / 162.5% (73.4%)", {"bold": True})]],
    ]
    tables.append((t4_title, t4_rows))

    t5_title = "附录：脱离 AI 人眼手算与本地程序分工速查表"
    t5_rows = [
        [[("策略名称", {"bold": True})], [("脱离 AI 可算性", {"bold": True})], [("人眼难算核心项", {"bold": True})], [("实盘每日看盘点", {"bold": True})]],
        [[("20cm V1.1", {})], [("纯人眼 2 分钟算清", {})], [("无难算项，9项整数", {})], [("09:25 直买 / 盘前限价单", {})]],
        [[("超跌撬板 V2.1", {})], [("纯人眼 2 分钟算清", {})], [("无难算项，10项整数", {})], [("09:25 逃命与买 / 14:55", {})]],
        [[("高标首阴 V5.1", {})], [("基本纯人眼可手算", {})], [("板块热度看热榜估算", {})], [("09:25 / 11:30 / 14:55", {})]],
        [[("三进四 V4.1", {})], [("半人眼半本地计算", {})], [("主概念 115 / 135 热度", {})], [("10:30 撤单 / 13:45 护利", {})]],
        [[("二进三 V2.1", {})], [("必须跑本地扫盘程序", {})], [("滚动热度与5分封成比", {})], [("09:25 直买 / 13:45 护利", {})]],
        [[("一进二 V20", {})], [("必须跑本地扫盘程序", {})], [("分位数与跨板低开池", {})], [("11:30 撤单 / 10:30 均线", {})]],
    ]
    tables.append((t5_title, t5_rows))

    return {
        "title": "A股短线六策略体系总纲（V20.0 定版）",
        "doc_id": "MNYxdBGBxomQ8gxtz5tcYibBn6d",
        "node_token": "M0GEwOfn2ievUZkfvXHc97fJnOh",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
