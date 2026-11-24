# -*- coding: utf-8 -*-
"""20cm 首板深水错杀反抽 V1.1 飞书主文档生成器（精确节点名 20cm）"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_20cm_v11_blocks():
    blocks = []

    p1 = [
        make_text_run("20cm V1.1 定版，V20.0 第六大实盘策略，仅取 S 档满 82 分。"),
        make_text_run("S 档入第二梯队末位，于 09:25 竞价直买，压制全部盘中条件单。"),
        make_text_run("A 档 76 至 81 分仅在早报观察提示情绪，绝对不占单仓名额。"),
        make_text_run(
            "适用期：主板接力分化或情绪温和修复期最稳，人眼两分钟可独立手算。",
            background_color=3,
        ),
        make_text_run(
            "红线禁区：昨日全市场非 ST 20cm 涨停满 16 家，全天无条件空仓熔断。",
            bold=True,
            text_color=1,
        ),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("全套基于 2021 年至 2026 年数据，含 37 只退市股因果纳入。"),
        make_text_run(
            "S82 六年 199 笔胜率 57.79%。盈亏比 2.01，单仓净值 468.29 倍。",
            background_color=3,
        ),
        make_text_run("按日等权 1729.70 倍。去前五留存 104.06 倍，回撤稳守 26.70%。"),
        make_text_run("Calmar（卡尔玛）6.91，2026 年 32 笔 2.60 倍。OOS（样本外）73 笔 3.94 倍。"),
        make_text_run("A 档 76 分全池参考 349.78 倍。OOS（样本外）13.10 倍，仅作观察。"),
        make_text_run("DSR 0.9988，4F 可交易 Alpha +120.22%。与一进二低相关 0.015。"),
        make_text_run("10% 成交额守卫容量 1797 万。单边保本成本 166.7 bps，缓冲 +0.30%。"),
        make_text_run(
            "永久禁做普涨轨道融合、20cm 连跌停撬板、20cm 打板与盘中追突破。",
            bold=True,
            text_color=1,
        ),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("买入规则：6 道硬门与 9 项整数打分（底分 70，满 82 入仓）", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run(
            "创业板或科创板上市满 10 日，昨收满 2 元、昨非一字首板且额满 1 亿。",
            background_color=3,
        ),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("：今早 09:25 非一字。开盘需落入 -10.0% 至 -3.0% 深水区间。"),
        make_text_run("PIT（点时点）公告非 ST、近 90 日零毒丸公告、近 10 日零监管函。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run(
            "正向加分含甜区、流值、异动、记忆、机构与外溢。最高合计加 30 分。",
            background_color=3,
        ),
        make_text_run("低开在 -7.0% 至 -3.0% 加 4 分。扣锁仓真实流值不超 20 亿加 4 分。"),
        make_text_run("距三日 30% 异动余量满 10% 加 4 分。近 60 日两次 20cm 涨停加 5 分。"),
        make_text_run("昨机构净买大于 0 加 5 分。昨主板涨停超 70 加 7 分或超 55 加 4 分。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run(
            "反向扣分四项：核按钮 -10，假一致封单 -5，同场一字虹吸 -5，周一 -8。",
            background_color=3,
        ),
        make_text_run("低开低于 -8.0% 重扣 10 分，首板封成比满 10% 却低开扣 5 分。"),
        make_text_run("今早 09:25 全场出现 20cm 一字涨停扣 5 分，买入日逢周一扣 8 分。"),
        make_text_run("09:25 满 82 分仅买唯一头名，挂今开乘 1.015 限价单直接成交。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p4_head = [
        make_text_run("卖出规则：四分支动态卖树与风控开关（统一含 +0.30% 缓冲）", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("分支一首日涨停：", bold=True),
        make_text_run("次日起续骑连板，直至首个非涨停日 15:00 收盘清仓。", background_color=3),
        make_text_run("若遇 20cm 跌停无法成交，顺延至首个可卖日收盘卖出。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("分支二首日强真阳（收较开满 +6% 且位振幅 65% 上）。", bold=True),
        make_text_run("第 2 天挂 +12% 止盈。未触且无风控延至第 3 天收盘清。", background_color=3),
        make_text_run("第 2 天涨停同样转连板至破板卖出，不再设死时间止损。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("分支三温和震荡。", bold=True),
        make_text_run("第 2 天挂 1.5 倍低开止盈，限定 +6% 至 +15%。", background_color=3),
        make_text_run("未触止盈则第 2 天 15:00 收盘平仓，零盘中恐慌止损。"),
    ]
    blocks.append(make_bullet_block(b3))

    b4 = [
        make_text_run("分支四深阴或跌停（收较开低于 -5% 或跌停）。", bold=True),
        make_text_run("严禁第 2 天 09:25 割肉，必须持至第 2 天收盘卖出。", background_color=3),
        make_text_run("首日机构卖超 2000 万，或 20cm 跌停满 3 家或主板跌停满 20 家。"),
        make_text_run("触发风控后次日止盈上限压紧至 +7.0%，同时关闭分支二第 3 天延持。"),
    ]
    blocks.append(make_bullet_block(b4))

    p5 = [
        make_text_run("关于"),
        make_text_run("20cm 失效红线与实盘缺口", bold=True, text_color=1),
        make_text_run("。2023 年 8 月 23 日后，本地缺失 20cm 五分钟 K 线。"),
        make_text_run(
            "全期连亏 9 笔黄灯、10 笔红灯（五年口径 8 黄 9 红），立即减半或停机。",
            background_color=3,
        ),
        make_text_run("近 20 笔胜率低于 25.0% 停机。均赚低于 -2.65% 或累积和达 124.7% 停。"),
    ]
    blocks.append(make_para_block(p5))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：20cm V1.1 9 项纯整数零漂移打分卡（底分 70）"
    t1_rows = [
        [[("因子方向", {"bold": True})], [("条件名称", {"bold": True})], [("分值", {"bold": True})], [("判定与物理逻辑", {"bold": True})]],
        [[("开盘甜区", {})], [("低开 -7.0% 至 -3.0%", {})], [("+4 分", {})], [("温和错杀区，<-8.0% 扣10分", {})]],
        [[("自由流值", {})], [("扣十大锁仓不超 20 亿", {})], [("+4 分", {})], [("小自由流通筹码反抽弹性强", {})]],
        [[("异动余量", {})], [("距 3 日 30% 余量满 10%", {})], [("+4 分", {})], [("防买在严重异动触发边缘", {})]],
        [[("股性记忆", {})], [("近 60 日 20cm 涨停满 2 次", {})], [("+5 分", {})], [("含当日首板，活跃基因验证", {})]],
        [[("假一致罚", {})], [("首板封成比满 10% 却低开", {})], [("-5 分", {})], [("强一致变深水低开属资金诱多", {})]],
        [[("机构背书", {})], [("首板龙虎榜机构净买入>0", {})], [("+5 分", {})], [("主流机构买盘支撑次日承接", {})]],
        [[("主板外溢", {})], [("昨 10cm 涨停超 70 / 55 家", {})], [("+7 / +4 分", {})], [("主板赚钱效应外溢 20cm", {})]],
        [[("虹吸与周一", {})], [("今 20cm 有一字 / 逢周一", {})], [("-5 / -8 分", {})], [("一字抢筹抽血与周一惯性抛压", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：20cm V1.1 S82 逐年战绩表（含 37 只退市股）"
    t2_rows = [
        [[("年份维度", {"bold": True})], [("笔数与胜率", {"bold": True})], [("S82 单仓收益", {"bold": True})], [("沪深300与说明", {"bold": True})]],
        [[("2021年", {})], [("46笔 / 54.35%", {})], [("+256.84%", {})], [("沪深300 -5.20%", {})]],
        [[("2022年", {})], [("33笔 / 75.76%", {})], [("+511.82%", {})], [("沪深300 -21.63%", {})]],
        [[("2023年", {})], [("30笔 / 56.67%", {})], [("+131.82%", {})], [("沪深300 -11.38%", {})]],
        [[("2024年", {})], [("29笔 / 55.17%", {})], [("+153.68%", {})], [("沪深300 +14.68%", {})]],
        [[("2025年", {})], [("29笔 / 48.28%", {})], [("+40.14%", {})], [("沪深300 +17.66%", {})]],
        [[("2026年", {})], [("32笔 / 56.25%", {})], [("+160.27%", {})], [("沪深300 -14.51%", {})]],
        [[("六年全周期 S82", {"bold": True})], [("199笔 / 57.79%", {"bold": True})], [("468.29 倍", {"bold": True})], [("六年逐年全正，回撤26.70%", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：20cm S 档 vs A 档与四分支卖树执行表"
    t3_rows = [
        [[("对比与分支", {"bold": True})], [("触发条件", {"bold": True})], [("净值或卖法规则", {"bold": True})], [("风控收紧切换", {"bold": True})]],
        [[("S 档 >= 82 (实盘)", {"bold": True})], [("09:25 直买二梯队", {"bold": True})], [("199笔468.3x / 5年169.2x", {"bold": True})], [("合体贡献 87 笔 21.79x", {"bold": True})]],
        [[("A 档 76 至 81", {})], [("仅观察不上实盘", {})], [("全池285笔349.8x / OOS13.1x", {})], [("仅作早盘情绪辅助指示", {})]],
        [[("卖树 1：D1 涨停", {})], [("买入当日封死 20% 涨停", {})], [("续骑至首个非涨停日收盘", {})], [("跌停顺延至首个可卖日", {})]],
        [[("卖树 2：强真阳", {})], [("收幅>=+6%且位振幅65%上", {})], [("次日挂+12%限价至第3天", {})], [("风控开关压至+7%零延持", {})]],
        [[("卖树 3：温和震荡", {})], [("介于强阳与深阴之间", {})], [("次日挂1.5倍低开止盈6至15%", {})], [("未触收盘平仓，风控限7%", {})]],
        [[("卖树 4：深阴跌停", {})], [("收幅低于-5%或跌停", {})], [("禁早盘割肉，拿至次日收盘", {})], [("遇跌停顺延次可卖日收盘", {})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：20cm V1.1 S82 机构检验与 CUSUM 红线表"
    t4_rows = [
        [[("检验项目", {"bold": True})], [("实测数据结果", {"bold": True})], [("黄灯警告阈值", {"bold": True})], [("红灯停机阈值", {"bold": True})]],
        [[("Alpha 与 DSR", {})], [("5F +96.9% / DSR 0.9988", {})], [("全期连亏 9 笔", {})], [("全期连亏 10 笔 (5年9笔)", {})]],
        [[("容量与相关性", {})], [("1797万 / 相关性 0.015", {})], [("近20笔胜率 < 30.0%", {})], [("近20笔胜率 < 25.0%", {})]],
        [[("保本成本与截断", {})], [("166.7 bps / 截断 diff 0", {})], [("近20笔均赚 < -1.94%", {})], [("近20笔均赚 < -2.65%", {})]],
        [[("WRC 与累积和", {})], [("p 值 0.0 / 峰值 51.1%", {})], [("人工减半排查退化", {})], [("S_t 达到 124.7% 停仓", {})]],
    ]
    tables.append((t4_title, t4_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/chart_20cm_v11_v20.png"

    return {
        "title": "20cm",
        "doc_id": None,
        "node_token": None,
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
