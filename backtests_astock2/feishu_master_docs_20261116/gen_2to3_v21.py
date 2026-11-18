# -*- coding: utf-8 -*-
"""二进三 V2.1 飞书主文档生成器（V19.1 第 4 顺位定版）"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_2to3_v21_blocks():
    blocks = []

    # 第 1 段：定位与顺位
    p1 = [
        make_text_run("二进三 V2.1 定版，正式列为全局第 4 顺位投产策略。"),
        make_text_run("排在三进四、高标首阴与超跌撬板之后，压在一进二之前。"),
        make_text_run("买点与 18 项打分不变，满 96 分高胜率档顶部单独重点提醒。", background_color=3),
        make_text_run("每日只在 09:25、13:45 与 15:00 看盘三次。"),
    ]
    blocks.append(make_para_block(p1))

    # 第 2 段：升级机制 + 双轨战绩 + 组合协同 + 禁做红线
    p2 = [
        make_text_run(
            "封三板连板后，13:45 摸 +8.5% 护利由 +5.0% 升至 +6.5%。",
            background_color=3,
        ),
        make_text_run("完备 5 分钟库下，受影响的 17 笔交易录得 17 胜 0 负。"),
        make_text_run(
            "完备库 90 分五年 95 笔单仓升至 313.87 倍。原版为 261.05 倍。",
            background_color=3,
        ),
        make_text_run("完备库盈亏比 4.37，百万封顶 51.31 倍，按日等权 247.62 倍。"),
        make_text_run("官库口径 94 笔单仓由 144.21 倍升至 157.85 倍。封顶 42.75 倍。"),
        make_text_run("全五年最大回撤稳守 28.68%，完备近三年单仓达 15.04 倍。"),
        make_text_run("2026 年完备库 14 笔单仓达 4.64 倍（+364.35%）。"),
        make_text_run(
            "96 分高严档完备库由 20.84 倍升至 23.36 倍。官库升至 18.54 倍。",
            background_color=3,
        ),
        make_text_run("96 分档回撤仅 15.87%。2026 年 6 笔胜率 83.33%（2.78 倍）。"),
        make_text_run("2025 年 8 笔官库仅 +4.41%。完备库 -2.09%，明显跑输沪深300。"),
        make_text_run(
            "禁买高开超 +2.5% 或低开低于 -6.5% 标的，主概念涨停满 15 家禁做。",
            bold=True,
            text_color=1,
        ),
    ]
    blocks.append(make_para_block(p2))

    # 第 3 段：买点总起
    p3_head = [
        make_text_run("买入规则：主板二连板次日 09:25 竞价低吸承接", bold=True, underline=True),
        make_text_run("，18 项打分不变："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run(
            "10cm 主板非 ST 真二连板，二板与三板开盘均非一字。",
            background_color=3,
        ),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("：三板竞价必须在 -6.5% 至 +2.5% 之间。"),
        make_text_run("近 90 日零立案退市减持毒丸，近 10 日零监管函，概念少于 15 家。"),
        make_text_run("二板封成比满 25% 扣 16 分，秒板扣 8 分，深水洗盘加 6 分。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run(
            "底分 60 分共 18 项正交因子，锁仓满 50% 搭配换手区间分级加分。",
            background_color=3,
        ),
        make_text_run("换手 25% 至 65% 加 8 分。15% 至 25% 加 5 分，低于 15% 扣 8 分。"),
        make_text_run("雪球零帖不扣分，1 至 3 帖扣 10 分。满 4 帖扣 18 分，调研扣 10 分。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run(
            "跨界硬科技与 15 日细分新词破冰各加 4 分，退潮偷袭与一字透支扣分。",
            background_color=3,
        ),
        make_text_run("空仓且前 3 顺位无触发时，09:26 挂今开乘 1.015 限价单按最高分直买。"),
        make_text_run("同分优先低开更深且概念规模更小者，96 分档无条件顶部单独重点提醒。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    # 第 4 段：卖点总起
    p4_head = [
        make_text_run("卖出规则：未封死拿至收盘，连板 13:45 破 +6.5% 锁利", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("未封三板："),
        make_text_run(
            "取消次日早盘竞价割肉，统一拿至次日 15:00 收盘清仓。",
            background_color=3,
        ),
        make_text_run("未封三板早盘常放恐慌盘，硬砍会误杀午后反包大妖，跌停顺延。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("买入日封死三板："),
        make_text_run(
            "次日高开超 +9.2% 且非一字板，09:25 竞价直接止盈。",
            background_color=3,
        ),
        make_text_run("极高开接盘极易遭兑现砸盘，早盘竞价落袋锁定陡峭浮盈。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("封死三板或连板："),
        make_text_run(
            "13:45 摸 +8.5% 破 +6.5% 且未封死即锁利卖出。",
            background_color=3,
        ),
        make_text_run("保留 1 次真阳断板免死，禁挂双异动缓冲单，其余断板 15:00 清仓。"),
    ]
    blocks.append(make_bullet_block(b3))

    # 第 5 段：延伸证伪
    p5 = [
        make_text_run("延伸边界：实证淘汰 09:25 地板砍仓、双异动单与分时均线早走。"),
        make_text_run("连板期 13:45 护利至 +7.5% 会踩悬崖。定版 +6.5% 居中高原最稳。"),
        make_text_run("未封三板强行早盘砍仓在样本外连卖在低位地板，因此彻底否决。"),
    ]
    blocks.append(make_para_block(p5))

    # 第 6 段：失效问题
    p6 = [
        make_text_run("关于"),
        make_text_run("策略的失效问题", bold=True, text_color=1),
        make_text_run("。重点看"),
        make_text_run(
            "抱团趋势年跑输风险（如 2025 年）与盘前雪球喧嚣度。",
            background_color=3,
        ),
        make_text_run("当市场全面抱团核心资产或极高标时，冷门二进三胜率易回落。"),
        make_text_run("必须死守第 4 顺位定位，绝不抢占前三顺位主力仓位。"),
    ]
    blocks.append(make_para_block(p6))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格（严格 <= 4 列，细胞 <= 32 字）
    tables = []

    t1_title = "附录：二进三 V2.1 逐年战绩表（完备5分钟与官库双轨对照）"
    t1_rows = [
        [[("年份维度", {"bold": True})], [("笔数与胜率", {"bold": True})], [("官库 / 完备单仓收益", {"bold": True})], [("相对沪深300超额(完备)", {"bold": True})]],
        [[("2021年底", {})], [("7笔 / 57.14%", {})], [("+94.82% / +103.03%", {})], [("起步阶段完整入表", {})]],
        [[("2022年", {})], [("22笔 / 68.18%", {})], [("+327.75% / +404.54%", {})], [("超额 424.05 点（基准-19.51%）", {})]],
        [[("2023年", {})], [("17笔 / 35.29%", {})], [("+48.43% / +62.36%", {})], [("超额 59.65 点（基准+2.71%）", {})]],
        [[("2024年", {})], [("26或27笔 / 50%+", {})], [("+180.95% / +315.09%", {})], [("超额 300.41 点（基准+14.68%）", {})]],
        [[("2025年", {})], [("8笔 / 25.00%", {})], [("+4.41% / -2.09%", {})], [("跑输 19.75 点（基准+17.66%）", {})]],
        [[("2026年", {})], [("14笔 / 64.29%", {})], [("+335.03% / +364.35%", {})], [("超额 378.39 点（基准-14.04%）", {})]],
        [[("五年全周期", {"bold": True})], [("94或95笔 / 52%+", {"bold": True})], [("157.85x / 313.87x", {"bold": True})], [("回撤 28.68% / 盈亏比 4.37", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：二进三 V2.0 原版 vs V2.1 升级版多窗口对照表"
    t2_rows = [
        [[("口径与档位", {"bold": True})], [("笔数 / 胜率 / 盈亏比", {"bold": True})], [("单仓 / 百万封顶 / 等权", {"bold": True})], [("最大回撤 / 单仓超额", {"bold": True})]],
        [[("V2.0 官库90分五年", {})], [("94笔 / 52.13% / 4.01", {})], [("144.21x / 41.65x / 134.03x", {})], [("28.68% / 14339.5 百分点", {})]],
        [[("V2.1 官库90分五年", {"bold": True})], [("94笔 / 52.13% / 4.07", {"bold": True})], [("157.85x / 42.75x / 147.59x", {"bold": True})], [("28.68% / 15703.5 百分点", {})]],
        [[("V2.0 完备90分五年", {})], [("95笔 / 52.63% / 4.25", {})], [("261.05x / 49.40x / 205.94x", {})], [("28.68% / 26023.5 百分点", {})]],
        [[("V2.1 完备90分五年", {"bold": True})], [("95笔 / 52.63% / 4.37", {"bold": True})], [("313.87x / 51.31x / 247.62x", {"bold": True})], [("28.68% / 31305.5 百分点", {})]],
        [[("V2.1 完备近三年 / 26年", {})], [("52笔15.04x / 14笔4.64x", {})], [("2026年等权 6.15x", {})], [("近3年超额1393.7点 / 26年378点", {})]],
        [[("V2.1 96分五年(双轨)", {"bold": True})], [("35笔 / 54.29% / 6.62", {"bold": True})], [("官18.54x / 完备23.36x", {"bold": True})], [("回撤 15.87% / 26年胜率83.3%", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：V2.1 18 项买入打分卡与卖点四步触发对照表"
    t3_rows = [
        [[("模块分类", {"bold": True})], [("规则或因子条款", {"bold": True})], [("分值或参数", {"bold": True})], [("物理机制说明", {"bold": True})]],
        [[("硬门槛", {})], [("真二板均非一字且概念<15家", {})], [("竞价 -6.5% 至 +2.5%", {})], [("卡住深水承接赔率错配区间", {})]],
        [[("锁仓与换手", {})], [("锁仓满50%搭配真实换手", {})], [("25至65%加8 / 15至25%加5", {})], [("换手低于15%扣8分，防死锁", {})]],
        [[("暗牌与互学", {})], [("跨界科技与15日新词破冰", {})], [("各加4 / 雪球满4帖扣18", {})], [("散户吹票重罚，调研扣10分", {})]],
        [[("退潮排雷", {})], [("首板退潮与尾盘烂板一字", {})], [("分别扣 8 / 6 / 6 分", {})], [("排除前手透支与尾盘偷袭板", {})]],
        [[("V2.1 护利线", {"bold": True})], [("13:45后曾摸+8.5%回落线", {"bold": True})], [("由 +5.0% 升至 +6.5%", {"bold": True})], [("完备库17笔改动17胜0负", {"bold": True})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：V2.1 八项防过拟合检验与地狱压测总表"
    t4_rows = [
        [[("检验项目", {"bold": True})], [("官库 5 分钟口径", {"bold": True})], [("完备 5 分钟口径", {"bold": True})], [("稳健性结论", {"bold": True})]],
        [[("显著性（HLZ t值）", {})], [("3.83 (日频 3.49)", {})], [("4.22 (日频 3.81)", {})], [("双轨远超 3.0 强显著红线", {})]],
        [[("缩水夏普（DSR150）", {})], [("0.9583", {})], [("0.9868", {})], [("150次试验稳过 0.95 门槛", {})]],
        [[("过拟合概率（阶梯PBO）", {})], [("5.56% 至 5.71%", {})], [("1.98% 至 4.29%", {})], [("低风险区间且非孤立参数", {})]],
        [[("双向20% 200次扰动", {})], [("中位 54.23 倍", {})], [("中位 94.82 倍", {})], [("100% 盈利，+6.5%居中高原", {})]],
        [[("地狱压测与物理截断", {})], [("留存 40.86 倍", {})], [("留存 58.61 倍", {})], [("2025年初截断零偏差", {})]],
    ]
    tables.append((t4_title, t4_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/chart_2to3_v21.png"

    return {
        "title": "二进三",
        "doc_id": "Y2Acd0VpNoZopYxvsotcTwCrnqe",
        "node_token": "WrlywVBEOicuVfk15yEcsmfenUg",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
