# -*- coding: utf-8 -*-
"""一进二 V19 飞书主文档生成器（V19.1 跨策略版本号与正负号同步版）"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_1to2_v191_blocks():
    blocks = []

    # 第 1 段：定位与顺位
    p1 = [
        make_text_run("一进二 V19 定版，全局第 5 顺位常驻容量粮仓。"),
        make_text_run("全盘顺位：三进四 > 高标首阴 > 超跌撬板 > 二进三 > 一进二。"),
        make_text_run("对应版本为 V4.1、V5.1、V2.1、V2.1 与 V19。"),
        make_text_run("专做主板换手首板分歧转一致，自 2021 年底持续有效。"),
        make_text_run("每日只在 09:25、10:30、11:30 与 14:55 看盘四次。"),
    ]
    blocks.append(make_para_block(p1))

    # 第 2 段：门槛切换 + 真实战绩 + 禁做红线
    p2 = [
        make_text_run("平时采用标准 304.8 分门槛。"),
        make_text_run(
            "昨日一进二封板率超 75% 次日，门槛升至 329.8 分。",
            background_color=3,
        ),
        make_text_run("全五年 97 笔胜率 68.04%，盈亏比 2.87，单仓 338.37 倍。"),
        make_text_run("百万起千万封顶 54.57 倍，按日等权 65.74 倍。"),
        make_text_run("剔除前三牛股留存 57.09 倍。"),
        make_text_run(
            "回撤由 21.98% 降至 15.97%，远胜同期沪深300的 -18.49%。",
            background_color=3,
        ),
        make_text_run("全五年单仓超额 33755.34 百分点，封顶超额 5375.02 百分点。"),
        make_text_run("近三年 51 笔胜率 68.63%，盈亏比 3.69，单仓 63.43 倍。"),
        make_text_run("近三年跑赢同期沪深300（+10.33%）达 6232.60 个百分点。"),
        make_text_run("2026 年 21 笔胜率 80.95%，盈亏比 3.02，单仓 3.15 倍。"),
        make_text_run("2026 年回撤仅 4.03%，跑赢基准 228.84 个百分点。"),
        make_text_run(
            "昨日首板竞价均值为绿，或近 5 日自然晋级率低于 13.0% 全天空仓。",
            bold=True,
            text_color=1,
        ),
    ]
    blocks.append(make_para_block(p2))

    # 第 3 段：买点总起
    p3_head = [
        make_text_run("买入规则：主板首板次日上午点火，11:30 撤单", bold=True, underline=True),
        make_text_run("。"),
    ]
    blocks.append(make_para_block(p3_head))

    # 有序列表 3 条
    o1 = [
        make_text_run(
            "题材过三层净化，先验分满 45 分（周一空仓放宽至 38 分）。",
            background_color=3,
        ),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("：09:25 前查澄清公告，称零营收或无关即否决。"),
        make_text_run("硬科技主线若属纯传统外行且无重组，直接扣 20 分。"),
        make_text_run("第一主线领先满 20 分却无过线股时，禁退选第三题材。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run(
            "10cm 主板非 ST 首板非一字，流值 18 亿至 220 亿。",
            background_color=3,
        ),
        make_text_run("首板换手不超 20%，股价不超 60 元，封单紧密度满 37 分。"),
        make_text_run("排除高位老庄反抽，10:30 前开板 1 次与调研各加 5 分。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run(
            "主通道高开 +2.2% 至 +7.8%。周一放宽至 +2.0% 至 +8.8%。",
            background_color=3,
        ),
        make_text_run("周二至周五低于 +3.1% 扣 15 分，低晋级期低于 +3.5% 扣 25 分。"),
        make_text_run("同题材可买第 1 名加 35 分，第 2 名加 8 分，第 3 名扣 25 分。"),
        make_text_run("伴生一字且流值超 90 亿扣 25 分，锁筹 2 只起扣 15 至 22 分。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    # 主线空仓候补轨 + 挂单手操
    p3_trade = [
        make_text_run("V19 候补轨："),
        make_text_run(
            "主轨与周一轨空仓时，第 2 或第 3 主线头名作低优先候补。",
            background_color=3,
        ),
        make_text_run("候补须雪球少于 4 帖，启动前 20 日箱体不超 40%。"),
        make_text_run("同时须有硬催化或新词、零拉萨及一日游，去压制满 295.0 分。"),
        make_text_run("手操口径：09:26 挂云条件单，11:30 未触发撤单。"),
        make_text_run("触发价填 max(昨收乘1.065, 今开乘1.012)。"),
        make_text_run("周一满 310 分且领先第 2 名超 +2.5%，挂今开乘 1.015 限价单。"),
        make_text_run("同日多只严格按主轨、候补、周一顺位，仅取最高分 1 只。"),
    ]
    blocks.append(make_para_block(p3_trade))

    # 第 4 段：卖点总起
    p4_head = [
        make_text_run("卖出规则：次日弱开清仓、10:30 弱斩与暗牌低开豁免", bold=True, underline=True),
        make_text_run("。"),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("未封二板若收阴跌或次日高开不足 +0.5%，"),
        make_text_run("次日 09:25 竞价全仓卖出。", background_color=3),
        make_text_run("收红且次日高开满 +0.5% 留至 15:00 卖，反包涨停续骑。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("封死二板后，次日起 10:30 未封板且破均价线卖出。"),
        make_text_run(
            "二板次日开于 -6.5% 至 +2.5%、雪球少 4 帖且封成低 25%，免弱斩。",
            background_color=3,
        ),
        make_text_run("筹码未过热派发，留至 15:00 未封板再清仓，封三板则续骑。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("14:30 后尾盘炸板立即卖出。"),
        make_text_run("三连板及以上真阳断板且收幅满 +2.0%，免死 1 天博反包。", background_color=3),
        make_text_run("其余断板一律 15:00 收盘出清，最长持有至第 12 个交易日。"),
    ]
    blocks.append(make_bullet_block(b3))

    # 第 5 段：延伸证伪
    p5 = [
        make_text_run("延伸边界：禁买 40 亿以下微盘、一字炸板回封与好名字虚加分。"),
        make_text_run("实测 40 亿以下微盘胜率崩至 15.4%，一字炸板回封近一年净亏。"),
        make_text_run("断层主线无龙时强放第 3 题材因缺完整分时线，本版予以剥离。"),
    ]
    blocks.append(make_para_block(p5))

    # 第 6 段：失效问题
    p6 = [
        make_text_run("关于"),
        make_text_run("策略的失效问题", bold=True, text_color=1),
        make_text_run("，重点监控"),
        make_text_run(
            "近 5 日晋级率、昨日封板率与首板竞价均值。",
            background_color=3,
        ),
        make_text_run("自然晋级率低于 13.0% 或昨日首板平均竞价为绿立即空仓。"),
        make_text_run("实盘连亏 5 笔或触及 15.97% 回撤线，立即减半仓位复盘。"),
    ]
    blocks.append(make_para_block(p6))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格（严格 <= 4 列）
    tables = []

    t1_title = "附录：V19 净值曲线与逐年真实战绩（五年全胜基准）"
    t1_rows = [
        [[("年份维度", {"bold": True})], [("笔数与胜率", {"bold": True})], [("单仓净收益", {"bold": True})], [("相对沪深300超额", {"bold": True})]],
        [[("2021年底", {})], [("2笔 / 50.00%", {})], [("-7.83%", {})], [("起步阶段极小样本", {})]],
        [[("2022年", {})], [("32笔 / 62.50%", {})], [("+261.79%", {})], [("超额 283.43 百分点", {})]],
        [[("2023年", {})], [("12笔 / 83.33%", {})], [("+59.97%", {})], [("超额 71.35 百分点", {})]],
        [[("2024年", {})], [("8笔 / 62.50%", {})], [("+96.16%", {})], [("超额 81.47 百分点", {})]],
        [[("2025年", {})], [("22笔 / 59.09%", {})], [("+927.19%", {})], [("超额 909.53 百分点", {})]],
        [[("2026年", {})], [("21笔 / 80.95%", {})], [("+214.80%", {})], [("超额 228.84 百分点", {})]],
        [[("五年全周期", {"bold": True})], [("97笔 / 68.04%", {"bold": True})], [("复利 338.37 倍", {"bold": True})], [("超额 33755.34 百分点", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：前版 V18 与定版 V19 多窗口对照表"
    t2_rows = [
        [[("版本与窗口", {"bold": True})], [("笔数 / 胜率 / 盈亏比", {"bold": True})], [("单仓 / 千万封顶 / 等权", {"bold": True})], [("最大回撤 / 封顶超额", {"bold": True})]],
        [[("V18 全五年", {})], [("96笔 / 68.75% / 2.79", {})], [("328.91x / 54.14x / 57.09x", {})], [("21.98% / 5332.04 百分点", {})]],
        [[("V19 全五年", {"bold": True})], [("97笔 / 68.04% / 2.87", {"bold": True})], [("338.37x / 54.57x / 65.74x", {"bold": True})], [("15.97% / 5375.02 百分点", {})]],
        [[("V19 近三年", {})], [("51笔 / 68.63% / 3.69", {})], [("63.43x / 31.13x / 22.29x", {})], [("13.83% / 3002.91 百分点", {})]],
        [[("V19 2026年", {})], [("21笔 / 80.95% / 3.02", {})], [("3.15x / 3.15x / 2.50x", {})], [("4.03% / 228.84 百分点", {})]],
        [[("V19 去前三极值", {})], [("94笔留存样本", {})], [("单仓 57.09 倍", {})], [("地狱压测单仓 80.01 倍", {})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：V19 两项跨策略互学升级效果表"
    t3_rows = [
        [[("升级模块", {"bold": True})], [("触发条件", {"bold": True})], [("核心动作", {"bold": True})], [("实证效果", {"bold": True})]],
        [[("卖点弱斩豁免", {})], [("二板开于-6.5%至+2.5%", {})], [("雪球少于4帖且封成低25%", {})], [("免10:30斩仓，回撤降至15.97%", {})]],
        [[("空仓候补轨", {})], [("主轨与周一轨均空仓", {})], [("第2或第3主线头名低位暗牌", {})], [("去压制满295分，等权升至65.74倍", {})]],
        [[("典型受益案例", {})], [("千金药业与新金路", {})], [("豁免10:30弱斩拿至收盘", {})], [("千金转+2.01%，新金路+9.40%", {})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：V19 过拟合八项检验与风控核验表"
    t4_rows = [
        [[("检验项目", {"bold": True})], [("前版 V18", {"bold": True})], [("定版 V19", {"bold": True})], [("判定结论", {"bold": True})]],
        [[("显著性检验（HLZ t值）", {})], [("4.07", {})], [("4.08", {})], [("远超 3.0 强显著", {})]],
        [[("缩水夏普概率（DSR）", {})], [("99.45%", {})], [("99.45%", {})], [("150次试验过 95% 线", {})]],
        [[("过拟合概率（CSCV PBO）", {})], [("9.13%", {})], [("6.75%", {})], [("过拟合风险进一步下降", {})]],
        [[("双向20%参数扰动", {})], [("最低留存 69.38%", {})], [("最低留存 68.79%", {})], [("非局部孤岛参数", {})]],
        [[("截断与5分钟覆盖", {})], [("251天 100% 覆盖", {})], [("255天 100% 覆盖", {})], [("2024年底截断检验零偏差", {})]],
    ]
    tables.append((t4_title, t4_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/chart_1to2_v19.png"

    return {
        "title": "一进二",
        "doc_id": "OeJed4uL5oQ2nRxeOXIc4HronDe",
        "node_token": "TRE2wRsLbimSFhkl7sPc9XZHnBj",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
