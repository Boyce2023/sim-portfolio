# -*- coding: utf-8 -*-
"""20cm子文档3：20261124 20cm首板深水错杀因子打分与次日四分支卖法消融"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub20cm_3_scorecard_exits_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "直接结论：因子打分分档极有用，而次日盘中止损全没用且大幅毁掉收益。",
            background_color=3,
        ),
        make_text_run("本文详细拆解干净首板池构建、各分档阶梯回报与四分支卖法演变。"),
        make_text_run("干净底座从 3114 条初筛候选净化为 2626 条无污染样本。"),
        make_text_run("其中成功纠偏 133 笔老规则误标错杀，因果保留 21 笔退市股记录。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("一、干净首板池构建、分档单调性与因子 ablation（消融）", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p2_head))

    o1 = [
        make_text_run("五道清洗硬门筑底，拒绝任何前视偏差。", bold=True),
        make_text_run(
            "PIT（点时点）公告在 09:00 截断非 ST，并剔除毒丸与监管股。",
            background_color=3,
        ),
        make_text_run("上市满十日且昨收满两元，昨非一字首板且成交满一亿元。"),
        make_text_run("昨 20cm 涨停少于 16 家，样本内与 OOS（样本外）均分 1313 条。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("得分分层极其陡峭，低分段亏钱高分段暴赚。", bold=True),
        make_text_run(
            "65 分以下 158 笔胜率仅 31.65%，净值缩至 0.01 倍近乎归零。",
            background_color=3,
        ),
        make_text_run("65至71分130笔仅0.25倍，72至77分仅1.20倍。"),
        make_text_run("跨过 78 分立刻转盈，V1 版 88 分上胜率 68% 赚 70.61 倍。"),
        make_text_run("V1.1 精简至 9 因子后，分界锁定在 A 档 76 与 S 档 82 分。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    p3_head = [
        make_text_run("二、次日四分支卖法树与 39 组卖点消融实证", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    b1 = [
        make_text_run("铁定零盘中止损：加止损单是 20cm 深水最大自杀动作。", bold=True),
        make_text_run(
            "震荡股若设盘中 -5% 止损，全期净值由 461 倍降至 80.24 倍。",
            background_color=3,
        ),
        make_text_run("改用 -7% 止损同样降至 215.07 倍，-9% 止损降至 372.55 倍。"),
        make_text_run("早盘深水筹码经常先急杀再反抽，固定止损必砍在地板。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("深阴跌停禁早盘斩，且禁拖延至第三天盲目扛单。", bold=True),
        make_text_run(
            "若放开拿至第三天收盘，全期净值由 276.04 倍降至 49.82 倍。",
            background_color=3,
        ),
        make_text_run("分支四深阴若次日 09:25 砍仓，净值由 461 倍降至 305.16 倍。"),
        make_text_run("涨停续骑、强阳锁利延三天、震荡 1.5 倍止盈、深阴拿到收盘。"),
    ]
    blocks.append(make_bullet_block(b2))

    p4 = [
        make_text_run("卖法总结论："),
        make_text_run("自适应止盈配强真阳延持，在全期与样本外碾压止损与纯收盘。", background_color=3),
        make_text_run("叠加穿价 +0.30% 缓冲与尾盘风控收紧，造就零漏洞四分支卖树。"),
    ]
    blocks.append(make_para_block(p4))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：打分分档单调性检验（V1 底座各分段实证）"
    t1_rows = [
        [[("得分区间", {"bold": True})], [("单仓笔数 / 胜率", {"bold": True})], [("盈亏比 / 均收益", {"bold": True})], [("净值 / 回撤", {"bold": True})]],
        [[("65 分以下", {})], [("158笔 / 31.65%", {})], [("0.88 / -2.55%", {})], [("0.01x / 回撤99.0%", {})]],
        [[("65 至 71 分", {})], [("130笔 / 44.62%", {})], [("1.00 / -0.72%", {})], [("0.25x / 回撤78.2%", {})]],
        [[("72 至 77 分", {})], [("115笔 / 45.22%", {})], [("1.42 / +0.47%", {})], [("1.20x / 回撤53.4%", {})]],
        [[("78 至 82 分", {"bold": True})], [("100笔 / 63.00%", {"bold": True})], [("1.61 / +3.78%", {"bold": True})], [("24.32x / 回撤24.5%", {"bold": True})]],
        [[("83 至 87 分", {})], [("61笔 / 54.10%", {})], [("2.32 / +3.78%", {})], [("6.89x / 回撤42.8%", {})]],
        [[("88 分及以上(S档)", {"bold": True})], [("75笔 / 68.00%", {"bold": True})], [("2.89 / +6.25%", {"bold": True})], [("70.61x / 回撤11.0%", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：次日四分支卖法树 39 组核心消融对照表"
    t2_rows = [
        [[("卖法消融变体", {"bold": True})], [("全期单仓", {"bold": True})], [("OOS（样本外）/ 26年", {"bold": True})], [("淘汰或保留结论", {"bold": True})]],
        [[("基准：纯T2收盘卖出", {})], [("276.04 倍", {})], [("5.39x / 3.36x", {})], [("未吃日内脉冲错杀溢价", {})]],
        [[("错误：纯T3收盘才卖", {})], [("49.82 倍", {})], [("2.34x / 2.44x", {})], [("死扛震荡少赚226倍", {})]],
        [[("错误：加盘中-5%/-7%止损", {})], [("80.2x / 215.1x", {})], [("5.16x / 5.80x", {})], [("止损砍在洗盘地板，淘汰", {})]],
        [[("错误：深阴D2 09:25硬割", {})], [("305.16 倍", {})], [("4.02x / 2.98x", {})], [("恐慌盘砸开反抽损失大", {})]],
        [[("最优：1.5倍自适应止盈", {"bold": True})], [("517.92 倍", {"bold": True})], [("5.88x / 3.30x", {"bold": True})], [("大幅击败固定目标，入选", {"bold": True})]],
        [[("终版四分支加风控开关", {"bold": True})], [("843.59 倍", {"bold": True})], [("7.17x / 3.89x", {"bold": True})], [("V1.1降噪带缓冲定版底座", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261124 20cm首板深水错杀因子打分与次日四分支卖法消融",
        "parent_node_token": "Bm0AwmIg5if5vekhQmacamjdnIc",
        "doc_id": None,
        "node_token": None,
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
