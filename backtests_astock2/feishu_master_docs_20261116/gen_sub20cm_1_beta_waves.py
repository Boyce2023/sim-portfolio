# -*- coding: utf-8 -*-
"""20cm子文档1：20261124 20cm主升浪与Beta周期波段全谱系及淘汰证伪"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub20cm_1_beta_waves_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "直接结论：20cm 主升浪顺周期波段追高轨道全盘没用，已永久淘汰。",
            background_color=3,
        ),
        make_text_run("本研究拆解 2021 至 2026 年共 26 个客观大波段与 10 轮周期。"),
        make_text_run("高潮主升段虽短时暴利，但极度依赖牛市日且样本外剧烈缩水。"),
        make_text_run("实盘接入反而拉垮深水主线收益，因此彻底放弃上线。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("一、六年 20cm 周期波段结构与大盘背离规律", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p2_head))

    o1 = [
        make_text_run("周期波段高度集中于成交破万亿且首二板放量期。", bold=True),
        make_text_run(
            "全市场探测 26 个正向波段，典型如锂电、超跌反弹与 924 牛市。",
            background_color=3,
        ),
        make_text_run("锂电周期 83 天等权赚 +24.34%，同期沪深300 为 -6.20%。"),
        make_text_run("924 周期等权回报 +48.46%，25 年机器人波段跑赢 12.51 点。"),
        make_text_run("但 26 年暑期波段等权为 -15.07%，11 月再报 -6.30%。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("筹码生态迁移：机构买盘萎缩与市值中枢上移。", bold=True),
        make_text_run(
            "21 至 22 年机构龙虎榜净买强力主导，此后散户拉萨占比上升。",
            background_color=3,
        ),
        make_text_run("波段爆发极度挑水位，全 A 高红盘与成交万亿仅 65 个交易日。"),
        make_text_run("全六年仅 33 个黄金高水位日适合主升突击，空窗期极长。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    p3_head = [
        make_text_run("二、两条波段通道与打分卖法实测及淘汰依据", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    b1 = [
        make_text_run("两条原生通道收益单薄且回撤集中。", bold=True),
        make_text_run(
            "宽松通道单仓六年 44 笔仅 2.73 倍，硬门槛通道约 3.4 倍。",
            background_color=3,
        ),
        make_text_run("宽松通道 OOS（样本外）18 笔仅 1.57 倍，26 年仅 1.02 倍。"),
        make_text_run("一旦剔除前 5 大牛股，全期单仓留存降至 1.58 倍与 0.97 倍。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("V1 打分版脱离 924 牛市后原形毕露。", bold=True),
        make_text_run(
            "94分S档有7.59倍，去924后OOS（样本外）仅1.30倍。",
            background_color=3,
        ),
        make_text_run("85 分 A 档去 924 后仅 1.25 倍，26 年五笔 0.91 倍。"),
        make_text_run("更致命的是插入深水主轨时，实盘在样本外平均每笔亏 -1.49%。"),
    ]
    blocks.append(make_bullet_block(b2))

    p4 = [
        make_text_run("淘汰终裁："),
        make_text_run("20cm 顺周期波段只是牛市贝塔脉冲，样本外全面跑输。", background_color=3),
        make_text_run("严格物理淘汰，绝不让顺周期波段信号污染深水实盘池。"),
    ]
    blocks.append(make_para_block(p4))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：六年 20cm 代表周期波段客观统计表"
    t1_rows = [
        [[("波段名称与时段", {"bold": True})], [("板块等权", {"bold": True})], [("沪深300", {"bold": True})], [("结构特征与日均涨停", {"bold": True})]],
        [[("21年锂电半导体(83天)", {})], [("+24.34%", {})], [("-6.20%", {})], [("日均1.1万亿 / 7.8家涨停", {})]],
        [[("22年5至6月光伏汽车", {})], [("+28.78%", {})], [("+18.64%", {})], [("超额+10.14点，熊市反弹", {})]],
        [[("23年人工智能光模块", {})], [("+6.84%", {})], [("-9.16%", {})], [("超额+16.0点，分支轮动", {})]],
        [[("24年2月超跌与924牛", {})], [("+37% / +48%", {})], [("+12% / +24%", {})], [("强脉冲但持续性极短", {})]],
        [[("25年机器人与科技波", {})], [("+17.5% / +20.0%", {})], [("+5.0% / +17.9%", {})], [("超额大幅收窄至2.14点", {})]],
        [[("26年暑期与11月波段", {"bold": True})], [("-15.07% / -6.30%", {"bold": True})], [("-7.86% / -0.69%", {"bold": True})], [("20cm 顺周期波段明显走弱", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：顺周期波段原生线 vs V1 打分版全周期对比表"
    t2_rows = [
        [[("测试方案与档位", {"bold": True})], [("笔数与胜率", {"bold": True})], [("全期 / 去924样本外", {"bold": True})], [("2026年与淘汰理由", {"bold": True})]],
        [[("宽松波段通道", {})], [("44笔 / 64.9%", {})], [("2.73x / 样外1.57x", {})], [("26年1.02x，去前5仅1.58x", {})]],
        [[("V1 85分 A 档波段", {})], [("45笔 / 68.9%", {})], [("5.83x / 去924 1.25x", {})], [("26年0.91x，靠924撑面", {})]],
        [[("V1 94分 S 档波段", {"bold": True})], [("39笔 / 76.9%", {"bold": True})], [("7.59x / 去924 1.30x", {"bold": True})], [("26年0.98x，拖垮深水主线", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261124 20cm主升浪与Beta周期波段全谱系及淘汰证伪",
        "parent_node_token": "Bm0AwmIg5if5vekhQmacamjdnIc",
        "doc_id": None,
        "node_token": None,
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
