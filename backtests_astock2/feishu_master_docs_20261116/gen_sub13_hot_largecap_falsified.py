# -*- coding: utf-8 -*-
"""专题子文档13（证伪墓碑目录）：20261124 热门题材买200亿大中军五年三轨28740组全证伪"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub13_hot_largecap_falsified_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "直接结论：空仓日买热门题材 200 亿大中军完全没用，五年三轨全盘证伪。",
            background_color=3,
        ),
        make_text_run("本回测横扫 28740 组切片与 56 个 PIT（点时点）因子。叠加 17 组实盘对照。"),
        make_text_run("200 亿以上全部切片中，高达 97.3% 在五年内录得负收益。"),
        make_text_run("越是全市场排名第一的热门主线，追高大中军亏得越惨重。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("三大轨道证伪实证（五年等权、因子打分与空仓补位）", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p2_head))

    b1 = [
        make_text_run("第一轨：越热门越亏，5 日等权跑输沪深300 高达 68 个点。", bold=True),
        make_text_run(
            "200 亿以上大票持有 5 日，全热点等权收益为 -64.63%。",
            background_color=3,
        ),
        make_text_run("缩圈至排名前二热榜主线恶化至 -75.62%，排名第一主线惨亏 -87.59%。"),
        make_text_run("同期沪深300 指数仅回报 -18.93%。可见越热门的大中军接盘越凶险。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("第二轨：科技高潮拥挤必踩踏，换四种卖法全部失效。", bold=True),
        make_text_run(
            "在涨停超 35 家的科技高潮日追入大中军，713 笔胜率仅 31.0%。",
            background_color=3,
        ),
        make_text_run("这 713 笔笔均收益为 -4.54%。换做次日开盘、收盘、+3% 与 +5% 止盈全负。"),
        make_text_run("56 个基本面估值因子全部无法救活。OOS（样本外）PBO 高达 0.60 至 0.74。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("第三轨：空仓日拿去填仓会把主策略净值毁掉八成五以上。", bold=True),
        make_text_run(
            "将主策略空仓期强行填补热门大票，单仓终值从 1440 万倍缩水超 85%。",
            background_color=3,
        ),
        make_text_run("原本用来躲避主线退潮的现金仓位，反而变成满仓硬扛大票补跌的绞肉坑。"),
    ]
    blocks.append(make_bullet_block(b3))

    p3 = [
        make_text_run("最终墓碑裁决："),
        make_text_run("永久禁止用热门题材大中军填补空仓，大票与高流动反核均已彻底出局。", background_color=3),
        make_text_run("高流动性大妖反核 171 组仅 2.3% 全正。该证伪已另案归档，绝不上实盘。"),
    ]
    blocks.append(make_para_block(p3))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：200亿以上热门大中军五年三轨证伪核心数据表"
    t1_rows = [
        [[("切片与分组条件", {"bold": True})], [("样本规模", {"bold": True})], [("五年等权或胜率", {"bold": True})], [("相对沪深300与结论", {"bold": True})]],
        [[("全热点大票 5 日等权", {})], [("129302 次信号", {})], [("-64.63% / 胜率44.4%", {})], [("跑输基准 -18.93% 达 45.7点", {})]],
        [[("热榜前 2 主线 5 日等权", {})], [("46969 次信号", {})], [("-75.62% / 胜率42.8%", {})], [("越挤进核心越亏", {})]],
        [[("热榜第 1 主线 5 日等权", {"bold": True})], [("25388 次信号", {"bold": True})], [("-87.59% / 胜率41.2%", {"bold": True})], [("跑输基准 68.7 个百分点", {"bold": True})]],
        [[("科技涨停>35家高潮日", {"bold": True})], [("713 笔实测", {"bold": True})], [("胜率31.0% / 均赚-4.54%", {"bold": True})], [("高潮后中军大面积派发", {"bold": True})]],
        [[("200亿+ 全量 28740 网格", {})], [("4种卖法×56因子", {})], [("97.3% 切片五年全负", {})], [("过拟合 PBO 0.60 至 0.74", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：空仓期填补大票与已入库避坑对比表"
    t2_rows = [
        [[("空仓处理方式", {"bold": True})], [("主策略净值影响", {"bold": True})], [("核心原因", {"bold": True})], [("实盘纪律", {"bold": True})]],
        [[("严格现金空仓防守", {"bold": True})], [("保留 100% 主升复利", {"bold": True})], [("现金是退潮期最强盾牌", {})], [("无合格信号坚决空仓", {"bold": True})]],
        [[("填补热门 200 亿+ 大中军", {})], [("单仓净值打掉超 85%", {})], [("高潮退潮大票共振补跌", {})], [("永久证伪严禁填仓", {})]],
        [[("高流动性大妖反核(已归档)", {})], [("26年单仓 -25.27%", {})], [("171组仅2.3%全正滑点归零", {})], [("已另立墓碑绝不复买", {})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261124 热门题材买200亿大中军五年三轨28740组全证伪",
        "parent_node_token": "QiDewdTkJiquokkbbo6cWr3Fn6f",
        "doc_id": None,
        "node_token": None,
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
