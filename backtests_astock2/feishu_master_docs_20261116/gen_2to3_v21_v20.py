# -*- coding: utf-8 -*-
"""二进三 V2.1 飞书主文档生成器（V20.0 机构检验与 CUSUM 红线同步版）"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_2to3_v21_v20_blocks():
    blocks = []

    p1 = [
        make_text_run("二进三 V2.1 定版，稳居 V20.0 第二梯队第 6 顺位主力战法。"),
        make_text_run("09:25 竞价直买，压在一进二周一与 20cm S82 之前。"),
        make_text_run("买点与 18 项打分不变，满 96 分高盈亏比档顶部单独重点提醒。", background_color=3),
        make_text_run("每日只在 09:25、13:45 与 15:00 看盘三次。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("封三板连板后，13:45 摸 +8.5% 护利由 +5.0% 升至 +6.5%。", background_color=3),
        make_text_run("修正两笔除权后，完备五分钟库五年 95 笔胜率 53.68%，盈亏比 4.57。"),
        make_text_run("单仓净值 404.71 倍，等权 319.29 倍。去前三 84.05 倍，去前五 44.01 倍。"),
        make_text_run("最大回撤 28.68%，Calmar（卡尔玛）8.10。近三年 52 笔 15.23 倍。"),
        make_text_run("2026 年 14 笔胜率 64.29% 得 4.64 倍。96 分档 35 笔盈亏比 6.62。"),
        make_text_run("4F 可交易 Alpha +319.23%（t 4.79）。HLZ t 值 4.39，DSR 0.9930。"),
        make_text_run("10% 成交额守卫容量 2417 万。保本成本 315.6 bps，五折交叉全正。"),
        make_text_run("实盘缺口：二进三高开买点无直接 5 分钟验证，仅依赖 09:25 竞价成交。"),
        make_text_run("禁买高开超 +2.5% 或低开低于 -6.5% 标的，主概念涨停满 15 家禁做。", bold=True, text_color=1),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("买入规则：主板二连板次日 09:25 竞价低吸承接", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run("10cm 主板非 ST 真二连板，二板与三板开盘均非一字。", background_color=3),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("：三板竞价必须在 -6.5% 至 +2.5% 之间，概念涨停少于 15 家。"),
        make_text_run("近 90 日零立案退市减持毒丸，近 10 日零监管函。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("底分 60 分共 18 项。锁仓满 50% 配换手 25% 至 65% 加 8 分。", background_color=3),
        make_text_run("二板封成比满 25% 扣 16 分，秒板扣 8 分，深水洗盘加 6 分。"),
        make_text_run("雪球零帖不扣分，1 至 3 帖扣 10 分。满 4 帖扣 18 分，调研扣 10 分。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("跨界硬科技与 15 日细分新词破冰各加 4 分，退潮偷袭与一字透支扣分。", background_color=3),
        make_text_run("因依赖八年滚动热度与五分封成比，盘前必须由本地程序算分出单。"),
        make_text_run("09:26 挂今开乘 1.015 限价单按最高分直买，同分优先低开与小概念。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p4_head = [
        make_text_run("卖出规则：未封死拿至收盘，连板 13:45 破 +6.5% 锁利", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("未封三板：取消次日早盘竞价割肉，统一拿至次日 15:00 收盘清仓。", background_color=3),
        make_text_run("跌停则顺延至可卖日收盘，避免在早盘情绪最低点割飞反包板。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("买入日封死三板：次日高开超 +9.2% 且非一字板，09:25 竞价止盈。", background_color=3),
        make_text_run("连板期间 13:45 曾摸 +8.5% 回落破 +6.5% 且未封死即锁利卖出。"),
        make_text_run("保留首次真阳断板免死 1 次，禁挂双异动单，其余断板 15:00 清仓。"),
    ]
    blocks.append(make_bullet_block(b2))

    p5 = [
        make_text_run("关于"),
        make_text_run("V2.1 失效与 CUSUM 红线", bold=True, text_color=1),
        make_text_run("。全市场抱团趋势年（如 2025 年 8 笔 -2.09%）极易跑输。"),
        make_text_run("连亏 9 笔黄灯、10 笔红灯。近 20 笔胜率低于 30% 减半，25% 停。", background_color=3),
        make_text_run("近 20 笔均赚低于 +0.06% 黄灯。低于 -0.91% 或累积和达 121.2% 停机。"),
    ]
    blocks.append(make_para_block(p5))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：二进三 V2.1 完备五分钟真账逐年战绩表"
    t1_rows = [
        [[("年份维度", {"bold": True})], [("笔数与胜率", {"bold": True})], [("单仓净收益", {"bold": True})], [("相对沪深300超额", {"bold": True})]],
        [[("2021年底", {})], [("7笔 / 57.14%", {})], [("+103.03%", {})], [("超额 101.97 点", {})]],
        [[("2022年", {})], [("22笔 / 68.18%", {})], [("+404.54%", {})], [("超额 426.17 点", {})]],
        [[("2023年", {})], [("17笔 / 41.18%", {})], [("+106.68%", {})], [("超额 118.06 点", {})]],
        [[("2024年", {})], [("27笔 / 51.85%", {})], [("+320.44%", {})], [("超额 305.75 点", {})]],
        [[("2025年", {})], [("8笔 / 25.00%", {})], [("-2.09%", {})], [("大票抱团年跑输19.8点", {})]],
        [[("2026年", {})], [("14笔 / 64.29%", {})], [("+364.35%", {})], [("超额 378.39 点", {})]],
        [[("五年全周期", {"bold": True})], [("95笔 / 53.68%", {"bold": True})], [("404.71 倍 (等权 319x)", {"bold": True})], [("回撤 28.68% / 盈亏比 4.57", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：V2.1 18 项打分与 96 分高盈亏比档对照表"
    t2_rows = [
        [[("分类与档位", {"bold": True})], [("核心规则条款", {"bold": True})], [("分值或指标", {"bold": True})], [("说明与备注", {"bold": True})]],
        [[("硬门与筹码", {})], [("真二板均非一字、概念<15家", {})], [("竞价 -6.5% 至 +2.5%", {})], [("锁仓50%配换手25至65%加8", {})]],
        [[("情绪排雷", {})], [("雪球1至3帖/4帖、调研、封成", {})], [("扣 10 / 18 / 10 / 16 分", {})], [("退潮偷袭与一字透支各扣", {})]],
        [[("标准 90 分档", {})], [("近三年 52 笔 / 2026年 14 笔", {})], [("近3年15.23x / 26年4.64x", {})], [("官库94笔157.85x作为下限", {})]],
        [[("96 分提醒档", {"bold": True})], [("五年 35 笔胜率 54.29%", {"bold": True})], [("23.36x / 盈亏比 6.62", {"bold": True})], [("回撤仅15.87%，26年胜83%", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：V2.1 机构级双套件检验与 CUSUM 红线表"
    t3_rows = [
        [[("检验项目", {"bold": True})], [("实测数据", {"bold": True})], [("黄灯警戒线", {"bold": True})], [("红灯停机线", {"bold": True})]],
        [[("Alpha 与 DSR", {})], [("4F +319.2% / DSR 0.993", {})], [("连亏满 9 笔", {})], [("连亏满 10 笔 (峰值6)", {})]],
        [[("容量与保本成本", {})], [("2417万 / 315.6 bps", {})], [("近20笔均赚 < +0.06%", {})], [("近20笔均赚 < -0.91%", {})]],
        [[("WRC 与五折验证", {})], [("p 0.0044 / 5折全正", {})], [("近20笔胜率 < 30.0%", {})], [("近20笔胜率 < 25.0%", {})]],
        [[("官库差异与累积和", {})], [("去前五44.0x / 峰值76.7%", {})], [("仅依靠09:25竞价买", {})], [("累积和 S_t >= 121.2%", {})]],
    ]
    tables.append((t3_title, t3_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/chart_2to3_v21_v20.png"

    return {
        "title": "二进三",
        "doc_id": "Y2Acd0VpNoZopYxvsotcTwCrnqe",
        "node_token": "WrlywVBEOicuVfk15yEcsmfenUg",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
