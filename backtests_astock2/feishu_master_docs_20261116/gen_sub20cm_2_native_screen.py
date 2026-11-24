# -*- coding: utf-8 -*-
"""20cm子文档2：20261124 20cm七大原生策略海选与首板深水错杀胜出实证"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub20cm_2_native_screen_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "直接结论：20cm 七大原生策略中六套全没用，唯首板深水错杀胜出且极有用。",
            background_color=3,
        ),
        make_text_run("本海选对创业板科创板七大结构在严格单仓口径下进行盲测。"),
        make_text_run("包含二板接力、断板真阳、炸板低开、机构突破、调研及急跌。"),
        make_text_run("样本内与 OOS（样本外）双双跑出十倍的只有首板深水低开。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("一、七大 20cm 原生策略海选排名与淘汰原因", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p2_head))

    o1 = [
        make_text_run("第一名胜出者：首板次日深水低开错杀结构。", bold=True),
        make_text_run(
            "零打分硬骨架下，354 笔全期 20.22 倍，OOS（样本外）9.33 倍。",
            background_color=3,
        ),
        make_text_run("样本内 208 笔 2.17 倍，2026 年 56 笔仍跑出 2.48 倍收益。"),
        make_text_run("在首板套利与恐慌抛压交接的错杀点，赔率与胜率天然共振。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("淘汰组一：二板接力、机构突破与急跌全线亏钱。", bold=True),
        make_text_run(
            "20cm 二板接力全期仅 0.99 倍，OOS（样本外）0.80 倍。",
            background_color=3,
        ),
        make_text_run("2026 年接力仅 0.98 倍，因涨跌幅极宽极易遭获利盘核砸。"),
        make_text_run("机构突破三日轨净值剩 0.12 倍，急跌放量反抽剩 0.32 倍。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("淘汰组二：断板真阳、炸板低开与调研弹性不足。", bold=True),
        make_text_run(
            "断板真阳绿开虽全期 2.48 倍，但样本内 0.91 倍且回撤 67.56%。",
            background_color=3,
        ),
        make_text_run("首板弱炸仅 1.74 倍，调研突破 26 年仅剩 0.72 倍。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3_head = [
        make_text_run("二、候补结构二次深挖对照与终极收敛", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    b1 = [
        make_text_run("加装过滤硬骨架后，深水结构收益放大十倍以上。", bold=True),
        make_text_run(
            "补全PIT（点时点）排雷与1亿额门，261笔升至341.14倍。",
            background_color=3,
        ),
        make_text_run("同期OOS（样本外）10.62倍，26年2.48倍，盈亏比1.75。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("同口径下断板真阳与炸板精筛仍无法翻身。", bold=True),
        make_text_run(
            "精筛断板真阳316笔仅7.05倍，回撤69.1%，样外0.86倍。",
            background_color=3,
        ),
        make_text_run("精筛弱炸160笔仅1.95倍，OOS（样本外）0.82倍出局。"),
    ]
    blocks.append(make_bullet_block(b2))

    p4 = [
        make_text_run("海选结论："),
        make_text_run("20cm 市场禁做接力突破与反包，唯一金矿是首板深水错杀。", background_color=3),
        make_text_run("该原型原生即穿越牛熊，成为后续打分建模的唯一底座。"),
    ]
    blocks.append(make_para_block(p4))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：20cm 七大原生原型策略海选实证全表（单仓复利）"
    t1_rows = [
        [[("原型名称", {"bold": True})], [("全期笔数 / 胜率", {"bold": True})], [("全期 / 样本内", {"bold": True})], [("OOS（样本外）/ 2026年", {"bold": True})]],
        [[("1号 首板深水低开", {"bold": True})], [("354笔 / 50.85%", {"bold": True})], [("20.22x / 2.17x", {"bold": True})], [("9.33x / 2.48x", {"bold": True})]],
        [[("2号 低位分歧二板接力", {})], [("31笔 / 51.61%", {})], [("0.99x / 1.24x", {})], [("0.80x / 0.98x", {})]],
        [[("3号 首板真阳绿开", {})], [("440笔 / 48.64%", {})], [("2.48x / 0.91x", {})], [("2.73x / 1.87x", {})]],
        [[("4号 首板弱炸次日低开", {})], [("151笔 / 48.34%", {})], [("1.74x / 1.51x", {})], [("1.15x / 1.29x", {})]],
        [[("5号 机构突破放量三日", {})], [("334笔 / 44.61%", {})], [("0.12x / 0.14x", {})], [("0.84x / 1.18x", {})]],
        [[("6号 机构调研突破五日", {})], [("159笔 / 47.17%", {})], [("2.30x / 1.51x", {})], [("1.52x / 0.72x", {})]],
        [[("7号 急跌真阳三日反抽", {})], [("216笔 / 41.67%", {})], [("0.32x / 0.61x", {})], [("0.49x / 0.46x", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：三组精筛候补结构深度淘汰对比表"
    t2_rows = [
        [[("精筛方案", {"bold": True})], [("全期笔数与回撤", {"bold": True})], [("全期单仓", {"bold": True})], [("OOS（样本外）/ 2026年", {"bold": True})]],
        [[("深水硬门加涨停续骑", {"bold": True})], [("261笔 / 回撤45.8%", {"bold": True})], [("341.14 倍", {"bold": True})], [("10.62x / 2.48x", {"bold": True})]],
        [[("深水硬门加纯T2收盘", {})], [("261笔 / 回撤47.4%", {})], [("224.91 倍", {})], [("10.67x / 2.74x", {})]],
        [[("断板真阳精筛对照组", {})], [("316笔 / 回撤69.1%", {})], [("7.05 倍", {})], [("0.86x / 1.32x (淘汰)", {})]],
        [[("炸板回落精筛对照组", {})], [("160笔 / 回撤49.4%", {})], [("1.95 倍", {})], [("0.82x / 0.69x (淘汰)", {})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261124 20cm七大原生策略海选与首板深水错杀胜出实证",
        "parent_node_token": "Bm0AwmIg5if5vekhQmacamjdnIc",
        "doc_id": None,
        "node_token": None,
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
