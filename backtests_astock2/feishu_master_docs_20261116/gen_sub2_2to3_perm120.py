# -*- coding: utf-8 -*-
"""子文档2：20261117 二进三暗牌弱转强重构与五策略120种顺位全排列实证"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub2_2to3_perm120_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "结论：二进三暗牌弱转强重构与五策略 120 种顺位全排列优选非常有用。",
            background_color=3,
        ),
        make_text_run(
            "二进三 V2.0 五年单仓升至 144.21 倍。新五顺位百万封顶 183.31 倍居第 1。",
            background_color=3,
        ),
        make_text_run("二进三 V2.0 胜率升至 52.13%。盈亏比 4.01，回撤压至 28.68%。"),
        make_text_run("其 150 次试验缩水夏普概率 DSR 达 95.76%，正式通过防过拟合红线。"),
        make_text_run("满 96 分高严档五年 35 笔回撤 15.87%。2026 年胜率达 83.33%。"),
        make_text_run("120 排列定顺位为：三进四 > 高标首阴。后接超跌撬板 > 二进三 > 一进二。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("二进三 18 项正交因子重构逻辑", bold=True, underline=True),
        make_text_run("，彻底删去旧波段误伤项并补入跨板位真约束："),
    ]
    blocks.append(make_para_block(p2_head))

    o1 = [
        make_text_run("底层锁死 09 点 25 分低开至微高开暗牌赔率错配。", bold=True),
        make_text_run("竞价严卡跌 6.5% 至涨 2.5%，二板与买日均非一字且概念少于 15 家。", background_color=3),
        make_text_run("删掉旧版一波脆弱与二波回流，细分锁仓满 50% 配 15% 至 65% 换手加分。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("吸收一进二 5 项跨板位因子并设 96 分顶部重点提醒。", bold=True),
        make_text_run("跨界硬科技与 15 日新词破冰各加 4 分。退潮脉冲等三项各扣 6 至 8 分。", background_color=3),
        make_text_run("底分 60 分共 18 项因子，标准 90 分买。满 96 分顶部单独重点提醒。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("卖点双修：取消未封割地板，新增高开超 9.2% 止盈。", bold=True),
        make_text_run("未封死三板取消低开 0.5% 竞价割肉，统一拿至次日收盘清仓。", background_color=3),
        make_text_run("封死三板次日高开超 9.2% 非一字于竞价止盈，避开均亏 5.66% 的接盘坑。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3_head = [
        make_text_run("09 点 26 分唯一挂单零空耗与 120 种顺位全排列机理", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    b1 = [
        make_text_run("真实实盘在 09 点 26 分仅挂唯一 1 笔单，若未触发绝不当日补买次选。"),
        make_text_run("五顺位合体下所有 09 点 26 分条件单均正常分布成交，挂单零空耗浪费。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("三进四与高标首阴盈亏结构远胜低位首板，稳坐前两顺位。"),
        make_text_run("二进三虽强于一进二但在 2025 年抱团年跑输基准 13.25 个百分点。"),
        make_text_run("故超跌撬板坐第 3，二进三坐第 4，常驻粮仓一进二坐第 5 兜底。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("互学前基线跑 120 种排列已由该顺位以百万封顶 154.31 倍夺第 1。"),
        make_text_run("三策略互学升级合体后，同顺位五年 227 笔胜率 64.32%，盈亏比 3.17。"),
        make_text_run("百万封顶跃升至 183.31 倍，回撤 34.02%。千万起单利达 21.16 倍。"),
    ]
    blocks.append(make_bullet_block(b3))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：五策略 120 种顺位全排列前五名与原顺位对比表（09:26唯一挂单）"
    t1_rows = [
        [[("排名与顺位排列", {"bold": True})], [("五年笔数与胜率", {"bold": True})], [("单仓与百万封顶", {"bold": True})], [("近三年与回撤", {"bold": True})]],
        [[("V19.0 升级定版冠军", {"bold": True})], [("227笔 / 64.32%", {"bold": True})], [("1139万x / 183.31x", {"bold": True})], [("38803x / 34.02%", {"bold": True})]],
        [[("排列1：34>高>撬>23>12", {"bold": True})], [("231笔 / 61.04%", {"bold": True})], [("111.77万x / 154.31x", {"bold": True})], [("17088x / 30.01%", {"bold": True})]],
        [[("排列2：34>高>23>撬>12", {})], [("231笔 / 61.04%", {})], [("111.77万x / 154.31x", {})], [("17088x / 30.01%", {})]],
        [[("排列3：34>撬>高>23>12", {})], [("231笔 / 61.04%", {})], [("111.77万x / 154.31x", {})], [("17088x / 30.01%", {})]],
        [[("排列4：34>撬>23>高>12", {})], [("231笔 / 61.04%", {})], [("105.28万x / 153.68x", {})], [("17319x / 30.01%", {})]],
        [[("排列5：34>23>高>撬>12", {})], [("231笔 / 61.04%", {})], [("105.28万x / 153.68x", {})], [("17319x / 30.01%", {})]],
        [[("旧五顺位(23放末位)", {})], [("231笔 / 62.34%", {})], [("98.25万x / 152.40x", {})], [("23放最后少赚1.91倍封顶", {})]],
        [[("原四策略基线(无23)", {})], [("186笔 / 68.28%", {})], [("6.61万x / 118.61x", {})], [("回撤 26.26%，少45笔机会", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：二进三 V1.0 升级 V2.0 前后及 96 分高严档对比表"
    t2_rows = [
        [[("版本与档位", {"bold": True})], [("五年笔数与胜率", {"bold": True})], [("单仓 / 千万封顶 / 回撤", {"bold": True})], [("统计检验与近期表现", {"bold": True})]],
        [[("前版 V1.0 (90分)", {})], [("77笔 / 48.05%", {})], [("20.32x / 4.99x / 36.72%", {})], [("t=2.53 / DSR 40.08% 未过线", {})]],
        [[("定版 V2.0 (90分)", {"bold": True})], [("94笔 / 52.13%", {"bold": True})], [("144.21x / 7.14x / 28.68%", {"bold": True})], [("t=3.83 / DSR 95.76% 过线", {"bold": True})]],
        [[("定版 V2.0 (96分)", {"bold": True})], [("35笔 / 54.29%", {"bold": True})], [("17.43x / 4.64x / 15.87%", {"bold": True})], [("2026年 6笔胜率 83.33%", {"bold": True})]],
        [[("2025年短板核实", {})], [("8笔 / 25.00%", {})], [("当年赚 4.41%", {})], [("跑输沪深300达 13.25 个点", {})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261117 二进三暗牌弱转强重构与五策略120种顺位全排列实证",
        "parent_node_token": "WrlywVBEOicuVfk15yEcsmfenUg",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
