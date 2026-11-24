# -*- coding: utf-8 -*-
"""20cm子文档5：20261124 20cm与五套10cm双席盲测交叉审计与协同评估"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub20cm_5_dual_seat_synergy_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "结论：S82补空档与一进二优化极有用，A76占单仓全没用。",
            background_color=3,
        ),
        make_text_run("本文汇总双席盲测、单仓顺位排队、61项交互与留一贡献实证。"),
        make_text_run("全套基于 2021 至 2026 五年统一单仓口径，零一字买点与零零日交易。"),
        make_text_run("所有结论均经样本内与 OOS（样本外）双向复核，严禁主观加戏。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("一、双席空档填补、因果顺位排序与 A76 降级依据", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p2_head))

    o1 = [
        make_text_run("零抢占空档先过门：专门吃掉主板空仓真空期。", bold=True),
        make_text_run(
            "原基线228笔1440万倍，加S82空档49笔升至9704万倍。",
            background_color=3,
        ),
        make_text_run("原先228笔主板交易一笔未少，新49笔胜率63.3%、均+4.34%。"),
        make_text_run("单看这 49 笔空档期交易本身独立复利即赚 6.74 倍，证实错峰互补。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("因果轮动排队：严禁压制二进三，S82 只守第二梯队。", bold=True),
        make_text_run(
            "强行把20cm放二进三前，全期崩至1554万倍且样外腰斩。",
            background_color=3,
        ),
        make_text_run("S82 放第六顺位得 4414 万倍，OOS（样本外）5883 倍最稳健。"),
        make_text_run("仅保留三进四与高标 S 档占位，其他 09:25 确定单优先成交。"),
        make_text_run("精排终版278笔6913万倍，OOS（样本外）5648倍，夏普4.74。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("降级 A76 仅作观察：不许低胜率单抢占真金单仓。", bold=True),
        make_text_run(
            "纳入A76占单仓后，五套精排净值由4619万倍滑落至2655万倍。",
            background_color=3,
        ),
        make_text_run("同时组合胜率由65.11%降至62.74%，夏普由4.74跌回4.45。"),
        make_text_run("因此 76 至 81 分只入早报情绪观测，绝不占用实盘单仓宝贵名额。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3_head = [
        make_text_run("二、61 项交互淘汰与一进二 V20.0 唯一真协同", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    b1 = [
        make_text_run("61 项相互喂信号海选，淘汰率超过九成五。", bold=True),
        make_text_run(
            "46项因样本内外或回撤恶化淘汰，14项属冗余、噪音或PBO飙高。",
            background_color=3,
        ),
        make_text_run("市值分位替静态20亿虽好看，却让局部PBO从1.4%飙至30%。"),
        make_text_run("二十日红盘外挂虽提 OOS（样本外），却伤样本内并让 PBO 翻倍。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("唯一验真协同：20cm 低开情绪压制一进二 V20.0。", bold=True),
        make_text_run(
            "20cm低开满2家扣一进二25分，5年单仓由332.7倍升至474.4倍。",
            background_color=3,
        ),
        make_text_run("一进二OOS（样本外）胜率升至76.19%，回撤从12.4%降至8.34%。"),
        make_text_run("V20.0六策略留一抽查，踢20cm后净值由6913万倍跌回1322万倍。"),
    ]
    blocks.append(make_bullet_block(b2))

    p4 = [
        make_text_run("协同终裁："),
        make_text_run("S82贡献5.23倍净值与+21.9点Calmar（卡尔玛）。", background_color=3),
        make_text_run("S82排第二梯队末位并保护一进二V20.0，构筑最高效六极组合。"),
    ]
    blocks.append(make_para_block(p4))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：20cm 与五套 10cm 因果顺位及终版协同实测表"
    t1_rows = [
        [[("组合顺位方案", {"bold": True})], [("笔数与胜率", {"bold": True})], [("全期 / OOS（样本外）", {"bold": True})], [("2026年与裁决", {"bold": True})]],
        [[("V19.1 五策略基线", {})], [("228笔 / 64.91%", {})], [("1440万x / 样外3239x", {})], [("27.29x (未纳20cm)", {})]],
        [[("S82 纯第六顺位(因果)", {})], [("285笔 / 63.51%", {})], [("4414万x / 样外5883x", {})], [("31.91x (S82占82笔)", {})]],
        [[("S82 压一进二第五顺位", {})], [("285笔 / 63.86%", {})], [("5538万x / 样外4753x", {})], [("28.61x (S82占92笔)", {})]],
        [[("错置二进三之前(淘汰)", {})], [("322笔 / 62.73%", {})], [("1554万x / 样外1649x", {})], [("严重抢占二进三，淘汰", {})]],
        [[("强纳 A76 占单仓(淘汰)", {})], [("314笔 / 62.74%", {})], [("2655万x / 样外4186x", {})], [("夏普降至4.45，淘汰", {})]],
        [[("V20.0 终版 S档保留优先", {"bold": True})], [("278笔 / 65.11%", {"bold": True})], [("6913万x / 样外5648x", {"bold": True})], [("夏普4.74 / 贡献5.23x", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：61 项交互海选分类与一进二 V20.0 唯一升级对照表"
    t2_rows = [
        [[("海选实验归类", {"bold": True})], [("实验数量", {"bold": True})], [("关键指标变化", {"bold": True})], [("最终裁决", {"bold": True})]],
        [[("直接证伪淘汰组", {})], [("46 项", {})], [("样本外或回撤明显变差", {})], [("全部物理切除禁入", {})]],
        [[("冗余/小样本/漂移组", {})], [("14 项", {})], [("0改动或PBO飙至45.7%", {})], [("淘汰，拒绝市值分位", {})]],
        [[("20日红盘外挂候补", {})], [("1 项", {})], [("样本内降且局部PBO翻倍", {})], [("不强升，锁死V1.1", {})]],
        [[("一进二低开扣25分", {"bold": True})], [("唯一采纳", {"bold": True})], [("332.7x升474.4x/回撤8.3%", {"bold": True})], [("写入一进二V20.0实盘", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261124 20cm与五套10cm双席盲测交叉审计与协同评估",
        "parent_node_token": "Bm0AwmIg5if5vekhQmacamjdnIc",
        "doc_id": None,
        "node_token": None,
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
