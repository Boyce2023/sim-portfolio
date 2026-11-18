# -*- coding: utf-8 -*-
"""二进三 V2.0 飞书主文档生成器"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_2to3_v20_blocks():
    blocks = []

    # 第 1 段：定位与顺位
    p1 = [
        make_text_run("二进三 V2.0 定版，正式列为全局第 4 顺位投产策略。"),
        make_text_run("排在三进四、高标首阴与超跌撬板之后，压在一进二之前。"),
        make_text_run("标准档门槛 90 分，"),
        make_text_run("满 96 分高胜率档在早盘报告顶部无条件单独重点提醒。", background_color=3),
        make_text_run("每日只在 09:25、13:45 与 15:00 看盘三次。"),
    ]
    blocks.append(make_para_block(p1))

    # 第 2 段：底层机制 + 真实战绩 + 组合协同 + 禁做红线
    p2 = [
        make_text_run("核心赚钱机制是捕捉"),
        make_text_run(
            "暗牌零吹票、非死锁二板次日低开至微高开的赔率错配。",
            background_color=3,
        ),
        make_text_run("买入竞价区间严格卡在跌 6.5% 至涨 2.5%。"),
        make_text_run("标准 90 分档全五年 94 笔胜率 52.13%，盈亏比 4.01。"),
        make_text_run("单仓复利 144.21 倍，百万封顶 41.65 倍，回撤 28.68%。"),
        make_text_run("全五年跑赢跌 18.49% 的沪深300，封顶超额 4083.32 百分点。"),
        make_text_run("近三年 51 笔胜率 47.06%，盈亏比 3.96，单仓 9.83 倍。"),
        make_text_run("2026 年 14 笔胜率 64.29%，盈亏比 8.29，单仓 4.33 倍。"),
        make_text_run(
            "96 分档 35 笔赚 17.43 倍，回撤 15.87%。",
            background_color=3,
        ),
        make_text_run("2026 年 96 分档 6 笔胜率 83.33%，单仓 2.67 倍。"),
        make_text_run("2025 年 8 笔仅赚 4.41%，跑输沪深300达 13.25 个百分点。"),
        make_text_run("120 种全排列实证锁死二进三为第 4 顺位，压在一进二之前。"),
        make_text_run("V19.0 合体五年 227 笔胜率 64.32%。百万封顶达 183.31 倍。"),
        make_text_run(
            "禁买高开超 2.5% 或低开破跌 6.5% 标的，主概念涨停满 15 家禁做。",
            bold=True,
            text_color=1,
        ),
    ]
    blocks.append(make_para_block(p2))

    # 第 3 段：买点总起
    p3_head = [
        make_text_run("买入规则：主板二连板次日 09:25 竞价低吸承接", bold=True, underline=True),
        make_text_run("。"),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run(
            "10cm 主板非 ST 真二连板，二板与三板开盘均非一字。",
            background_color=3,
        ),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("：三板竞价必须在跌 6.5% 至涨 2.5% 之间。"),
        make_text_run("近 90 日零立案退市减持毒丸，近 10 日零监管函，概念少于 15 家。"),
        make_text_run("二板封成比满 25% 扣 16 分，秒板扣 8 分，深水洗盘加 6 分。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run(
            "底分 60 分共 18 项正交因子，删旧波段项并细分锁仓换手。",
            background_color=3,
        ),
        make_text_run("十大股东锁仓满 50% 时，换手 25% 至 65% 加 8 分。"),
        make_text_run("换手 15% 至 25% 增补加 5 分，换手低于 15% 扣 8 分。"),
        make_text_run("雪球零帖不扣分，1 至 3 帖扣 10 分，满 4 帖扣 18 分。"),
        make_text_run("近 20 日有机构调研，直接扣 10 分。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run(
            "吸收一进二 5 项：跨界硬科技与 15 日细分新词破冰各加 4 分。",
            background_color=3,
        ),
        make_text_run("首板退潮脉冲扣 8 分，二板 14:30 后烂板偷袭扣 6 分。"),
        make_text_run("首板缩量一字透支扣 6 分，避免前手压缩接力空间。"),
        make_text_run("传统行业切入硬科技未爆炒时，在二进三阶段有增量弹性。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3_trade = [
        make_text_run("09:26 手操口径："),
        make_text_run(
            "空仓且前 3 顺位无触发时，按总分降序取唯一最高分买入。",
            background_color=3,
        ),
        make_text_run("09:26 直接挂今开乘 1.015 保护限价单于开盘成交。"),
        make_text_run("同分优先低开更深且概念规模更小者。"),
        make_text_run("达 96 分高严档标的，无论前 3 顺位是否开仓均置顶提醒。"),
    ]
    blocks.append(make_para_block(p3_trade))

    # 第 4 段：卖点总起
    p4_head = [
        make_text_run("卖出规则：未封死持至次日收盘，封死增加高开止盈", bold=True, underline=True),
        make_text_run("。"),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("未封三板："),
        make_text_run(
            "取消次日低开割肉，统一拿至次日 15:00 收盘清仓。",
            background_color=3,
        ),
        make_text_run("此前低于涨 0.5% 竞价斩仓废止，反包涨停续骑，跌停顺延。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("买入日封死三板："),
        make_text_run(
            "次日高开超涨 9.2% 且非一字板，09:25 竞价直接止盈。",
            background_color=3,
        ),
        make_text_run("透支高开极易遭兑现砸盘，早盘竞价落袋可锁定陡峭浮盈。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("连板："),
        make_text_run(
            "13:45 后摸涨 8.5% 破涨 5.0% 护利，保留 1 次真阳免死。",
            background_color=3,
        ),
        make_text_run("其余断板日一律 15:00 收盘清仓，跌停顺延至开板日卖出。"),
    ]
    blocks.append(make_bullet_block(b3))

    # 第 5 段：延伸证伪
    p5 = [
        make_text_run("延伸边界：严禁套用高开追涨思维买涨超 2.5% 的二板。"),
        make_text_run("高开加速或死锁秒板炸板闷杀极重，盈亏比结构完全倒挂。"),
        make_text_run("旧版「一波脆弱与二波回流」拖累波段，V2.0 已彻底删除。"),
    ]
    blocks.append(make_para_block(p5))

    # 第 6 段：失效问题
    p6 = [
        make_text_run("关于"),
        make_text_run("策略的失效问题", bold=True, text_color=1),
        make_text_run("，重点看"),
        make_text_run(
            "抱团大年跑输风险（如 2025 年）与盘前雪球喧嚣度。",
            background_color=3,
        ),
        make_text_run("当市场全面抱团一进二与高标时，冷门二进三机会大幅萎缩。"),
        make_text_run("必须死守第 4 顺位定位，绝不抢占前三顺位主力仓位。"),
    ]
    blocks.append(make_para_block(p6))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格（严格 <= 4 列）
    tables = []

    t1_title = "附录：V2.0 净值曲线与逐年真实战绩（含 2025 年跑输实录）"
    t1_rows = [
        [[("年份维度", {"bold": True})], [("标准90分笔数与胜率", {"bold": True})], [("标准90分单仓收益", {"bold": True})], [("相对沪深300净超额", {"bold": True})]],
        [[("2021年底", {})], [("7笔 / 57.14%", {})], [("赚 94.82%", {})], [("起步阶段完整入表", {})]],
        [[("2022年", {})], [("22笔 / 68.18%", {})], [("赚 309.93%", {})], [("超额 331.56 百分点", {})]],
        [[("2023年", {})], [("17笔 / 35.29%", {})], [("赚 46.34%", {})], [("超额 57.72 百分点", {})]],
        [[("2024年", {})], [("26笔 / 50.00%", {})], [("赚 173.10%", {})], [("超额 158.41 百分点", {})]],
        [[("2025年", {})], [("8笔 / 25.00%", {})], [("赚 4.41%", {})], [("跑输 13.25 百分点", {})]],
        [[("2026年", {})], [("14笔 / 64.29%", {})], [("赚 332.76%", {})], [("超额 346.80 百分点", {})]],
        [[("五年全周期", {"bold": True})], [("94笔 / 52.13%", {"bold": True})], [("复利 144.21 倍", {"bold": True})], [("封顶超额 4083.32 百分点", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：V2.0 标准90分与高严96分多窗口对照表"
    t2_rows = [
        [[("档位与窗口", {"bold": True})], [("笔数 / 胜率 / 盈亏比", {"bold": True})], [("单仓 / 千万封顶 / 等权", {"bold": True})], [("最大回撤 / 单仓超额", {"bold": True})]],
        [[("V1.0 90分五年", {})], [("77笔 / 48.05% / 3.40", {})], [("20.32x / 千万起4.99x / 21.63x", {})], [("36.72% / 1950.49 百分点", {})]],
        [[("V2.0 90分五年", {"bold": True})], [("94笔 / 52.13% / 4.01", {"bold": True})], [("144.21x / 41.65x / 134.03x", {"bold": True})], [("28.68% / 14339.49 百分点", {})]],
        [[("V2.0 90分近三年", {})], [("51笔 / 47.06% / 3.96", {})], [("9.83x / 9.83x / 12.49x", {})], [("24.58% / 872.67 百分点", {})]],
        [[("V2.0 90分2026", {})], [("14笔 / 64.29% / 8.29", {})], [("4.33x / 4.33x / 5.73x", {})], [("7.12% / 347.04 百分点", {})]],
        [[("V2.0 96分五年", {"bold": True})], [("35笔 / 54.29% / 6.10", {"bold": True})], [("17.43x / 16.98x / 14.97x", {"bold": True})], [("15.87% / 1661.49 百分点", {})]],
        [[("V2.0 96分近三年", {})], [("21笔 / 52.38% / 4.27", {})], [("3.76x / 3.76x / 3.98x", {})], [("15.87% / 265.67 百分点", {})]],
        [[("V2.0 96分2026", {})], [("6笔 / 83.33% / 4.86", {})], [("2.67x / 2.67x / 2.71x", {})], [("5.04% / 181.04 百分点", {})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：V2.0 互学升级与 18 项打分卡核心表"
    t3_rows = [
        [[("变更类型", {"bold": True})], [("因子条款", {"bold": True})], [("分值调整", {"bold": True})], [("逻辑与物理机制", {"bold": True})]],
        [[("删旧与改段", {})], [("删一波脆弱与二波回流", {})], [("彻底删除", {})], [("消除波段反转误伤龙头", {})]],
        [[("删旧与改段", {})], [("锁仓满50%配真实换手", {})], [("15%至25%加5分", {})], [("25%至65%加8分，低15%扣8分", {})]],
        [[("一进二互学", {"bold": True})], [("传统跨界硬科技暗牌", {"bold": True})], [("加 4 分", {"bold": True})], [("跨界增量带来接力弹性", {})]],
        [[("一进二互学", {"bold": True})], [("自身细分15日新词破冰", {"bold": True})], [("加 4 分", {"bold": True})], [("新词萌芽期获先发溢价", {})]],
        [[("一进二互学", {"bold": True})], [("首板退潮一日游脉冲", {"bold": True})], [("扣 8 分", {"bold": True})], [("退潮脉冲无老大哥护航", {})]],
        [[("一进二互学", {"bold": True})], [("二板14:30尾盘烂板偷袭", {"bold": True})], [("扣 6 分", {"bold": True})], [("尾盘偷袭板次日承接极弱", {})]],
        [[("一进二互学", {"bold": True})], [("首板缩量一字透支", {"bold": True})], [("扣 6 分", {"bold": True})], [("首板顶死压缩二进三空间", {})]],
        [[("核心底盘", {})], [("离散低、双低迷、冷清、低位", {})], [("各加 5 至 8 分", {})], [("雪球满4帖扣18分，死锁扣16分", {})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：第 4 顺位全组合协同与过拟合检验表"
    t4_rows = [
        [[("组合或检验项", {"bold": True})], [("交易笔数与胜率", {"bold": True})], [("盈亏比与回撤", {"bold": True})], [("净值表现与结论", {"bold": True})]],
        [[("前4顺位基线组合", {})], [("186笔 / 68.28%", {})], [("2.09 / 26.26%", {})], [("单仓 6.61万倍，封顶 14.58倍", {})]],
        [[("加二进三90分第5顺位", {"bold": True})], [("232笔 / 65.09%", {"bold": True})], [("2.86 / 26.05%", {"bold": True})], [("单仓 313.09万倍，封顶 19.25倍", {})]],
        [[("加二进三96分第5顺位", {})], [("202笔 / 65.84%", {"bold": True})], [("2.67 / 26.05%", {"bold": True})], [("单仓 56.17万倍，2026年 17.82倍", {})]],
        [[("显著性（HLZ）与缩水夏普（DSR）", {})], [("94笔独立检验", {})], [("t值 3.83 / 日频 3.49", {})], [("DSR 95.76% 过 95% 硬线", {})]],
        [[("过拟合（PBO）与地狱压测", {})], [("阶梯 PBO 5.56%至7.14%", {})], [("去前三 30.81 倍", {})], [("地狱压测单仓仍达 38.05 倍", {})]],
    ]
    tables.append((t4_title, t4_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/chart_2to3_v20.png"

    return {
        "title": "二进三",
        "doc_id": "Y2Acd0VpNoZopYxvsotcTwCrnqe",
        "node_token": "WrlywVBEOicuVfk15yEcsmfenUg",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
