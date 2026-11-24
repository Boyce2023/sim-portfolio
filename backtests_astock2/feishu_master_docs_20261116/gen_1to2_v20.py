# -*- coding: utf-8 -*-
"""一进二 V20 跨板防抽血定版 飞书主文档生成器"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_1to2_v20_blocks():
    blocks = []

    p1 = [
        make_text_run("一进二 V20 定版，专做主板换手首板次日分歧转一致。"),
        make_text_run("在 V20.0 三梯队中，周一 09:25 断层直买排在第二梯队。"),
        make_text_run("周二至周五盘中条件单居第三梯队，让位一切 09:25 确定买点。"),
        make_text_run("每日仅在 09:25、10:30、11:30 与 14:55 看盘四次。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run(
            "V20 核心新增：20cm 清洁首板低开压制时全池总分统一扣 25 分。",
            background_color=3,
        ),
        make_text_run("V20 五年 92 笔胜率 71.74%。盈亏比 3.21，单笔均赚 +8.01%。"),
        make_text_run("纯单仓净值升至 474.35 倍。去前三 80.03 倍，去前五 35.04 倍。"),
        make_text_run("按日等权 114 日净值 98.89 倍。最大回撤由 15.97% 降至 13.31%。"),
        make_text_run("同期沪深300 回报 -18.49%，单仓超额达 47353.60 个百分点。"),
        make_text_run("OOS（样本外）42 笔胜率 76.19%。盈亏比 4.27，净值 63.80 倍，回撤 8.34%。"),
        make_text_run("2026 年以来 20 笔胜率 85.00%。净值 3.22 倍，回撤稳守 4.03%。"),
        make_text_run("HLZ t 值 4.43，DSR 0.9995。过拟合概率 PBO 仅 1.43%。"),
        make_text_run("10% 成交额守卫容量 3228 万，5 分钟买点覆盖率达 100.0%。"),
        make_text_run(
            "昨日首板均开为绿，或近 5 日自然晋级率低于 13.0% 全天空仓。",
            bold=True,
            text_color=1,
        ),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("买入规则：跨板防抽血校验与 11:30 突破点火", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run(
            "V20 跨板抑制：昨日 20cm 非 ST 涨停不足 16 家时检查首板池。",
            background_color=3,
        ),
        make_text_run("清洁池需上市满 10 日、非一字首板、收满 2 元、额满 1 亿、无公告雷。"),
        make_text_run("今早 09:25 池内开盘低于 -3.0% 达 2 家及以上，说明跨板接力退潮。"),
        make_text_run("触发后一进二全池候选总分扣 25 分，若昨 20cm 满 16 家则不扣分。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run(
            "题材过三层净化满 45 分（周一 38 分），09:25 必排澄清公告雷。",
            background_color=3,
        ),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("：10cm 主板非 ST 首板非一字。流值 18 至 220 亿，换手不超 20%。"),
        make_text_run("封单紧密度卡 37 分与主线涨停上限 35 家，单双项放开均已验证拖累。"),
        make_text_run("ablation（消融）验证：放开 35 家跌至 274.9 倍。删 37 分多 5 笔均亏 -1.67%。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run(
            "周二至五高开 +2.2% 至 +7.8% 排换手名次。周一放宽至 +2.0% 至 +8.8%。",
            background_color=3,
        ),
        make_text_run("平时过线 304.8 分。昨封板超 75% 升至 329.8 分，候补 295.0 分。"),
        make_text_run("第 1 名加 35 分（独立分支 24 分）。第 2 名加 8 分，第 3 名起扣 25 分。"),
        make_text_run("伴生一字且流值超 90 亿扣 25 分。锁筹 2 只起扣 15 至 22 分。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3_trade = [
        make_text_run("下单与 11:30 撤单实证。"),
        make_text_run(
            "09:26 挂 max(昨收乘1.065, 今开乘1.012) 单。11:30 未触即撤。",
            background_color=3,
        ),
        make_text_run("周一满 310 分且断层超 +2.5% 于 09:25 直买，其余只买唯一头名。"),
        make_text_run("五年 5 分钟线验证：改全直买。净值由 332.7 倍腰斩至 132.4 倍。"),
        make_text_run("真强二板 89% 在 09:45 前触发。87 笔封板 70.1%，均赚 +6.66%。"),
        make_text_run("13:00 至 15:00 触发的 5 笔胜率 0% 均亏 -5.28%。延至 15:00 白丢 53 倍。"),
    ]
    blocks.append(make_para_block(p3_trade))

    p4_head = [
        make_text_run("卖出规则：次日弱开斩、10:30 均线与暗牌免弱斩", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("未封二板若收阴或次日高开不足 +0.5%，"),
        make_text_run("次日 09:25 竞价全仓清仓。", background_color=3),
        make_text_run("收红且高开满 +0.5% 留至 15:00 卖，反包涨停则续骑连板。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("封死二板次日起 10:30 未封且破均价线卖出，但满足豁免条件除外。"),
        make_text_run(
            "开在 -6.5% 至 +2.5%、雪球少 4 帖且封成低 25%。满足即免弱斩。",
            background_color=3,
        ),
        make_text_run("筹码未透支时留至 15:00 未封再清，14:30 后尾盘炸板即刻卖出。"),
        make_text_run("满 3 板后首次真阳断板且收幅满 +2.0% 免死 1 天，限用 1 次。"),
    ]
    blocks.append(make_bullet_block(b2))

    p5 = [
        make_text_run("关于"),
        make_text_run("V20 失效红线与容量边界", bold=True, text_color=1),
        make_text_run("。禁买 40 亿以下微盘（胜率 15.4%）与一字炸板回封。"),
        make_text_run(
            "连亏 5 笔黄灯、6 笔红灯。近 20 笔胜率低于 45% 减半，40% 停。",
            background_color=3,
        ),
        make_text_run("近 20 笔均赚低于 +1.12% 黄灯。低于 +0.26% 或累积和达 91.7% 停机。"),
    ]
    blocks.append(make_para_block(p5))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：一进二 V20 跨板防抽血升级前后对比表"
    t1_rows = [
        [[("对比维度", {"bold": True})], [("V19 旧版", {"bold": True})], [("V20 跨板定版", {"bold": True})], [("改进核心逻辑", {"bold": True})]],
        [[("五年笔数与胜率", {})], [("97笔 / 68.04%", {})], [("92笔 / 71.74%", {"bold": True})], [("挡掉5笔20cm抽血负样本", {})]],
        [[("单仓净值 / 盈亏比", {})], [("332.72x / 2.88", {})], [("474.35x / 3.21", {"bold": True})], [("单仓提升 +42.6%", {})]],
        [[("去前三 / 去前五", {})], [("56.13x / 24.58x", {})], [("80.03x / 35.04x", {"bold": True})], [("去极值留存全线上涨", {})]],
        [[("最大回撤 / 按日等权", {})], [("15.97% / 64.64x", {})], [("13.31% / 98.89x", {"bold": True})], [("回撤降 2.66 点，等权大增", {})]],
        [[("OOS（样本外）与26年", {})], [("45笔39.3x / 21笔3.15x", {})], [("42笔63.80x / 20笔3.22x", {"bold": True})], [("2026年胜率冲上 85.0%", {})]],
        [[("PBO / 10%容量", {})], [("6.75% / 3166万", {})], [("1.43% / 3228万", {"bold": True})], [("过拟合概率大幅下降", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：一进二 V20 逐年真实战绩表（100% 5分钟覆盖）"
    t2_rows = [
        [[("年份维度", {"bold": True})], [("笔数与胜率", {"bold": True})], [("单仓净收益", {"bold": True})], [("同期沪深300与说明", {"bold": True})]],
        [[("2021年底", {})], [("1笔 / 100.0%", {})], [("+0.09%", {})], [("V20 拦下首年1笔亏单", {})]],
        [[("2022年", {})], [("32笔 / 62.50%", {})], [("+261.79%", {})], [("沪深300 -21.63%", {})]],
        [[("2023年", {})], [("12笔 / 83.33%", {})], [("+59.97%", {})], [("沪深300 -11.38%", {})]],
        [[("2024年", {})], [("8笔 / 62.50%", {})], [("+96.16%", {})], [("沪深300 +14.68%", {})]],
        [[("2025年", {})], [("19笔 / 68.42%", {})], [("+1198.38%", {})], [("挡掉3笔负单暴增收益", {})]],
        [[("2026年", {})], [("20笔 / 85.00%", {})], [("+221.52%", {})], [("沪深300 -14.04%，回撤4.03%", {})]],
        [[("五年全周期", {"bold": True})], [("92笔 / 71.74%", {"bold": True})], [("474.35 倍", {"bold": True})], [("超额 +47353.6 个百分点", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：11:30 撤单与 35 家过热门禁五年消融实证表"
    t3_rows = [
        [[("对照变体", {"bold": True})], [("五年单仓净值", {"bold": True})], [("胜率与回撤", {"bold": True})], [("实证结论", {"bold": True})]],
        [[("标准 V19（11:30撤单）", {"bold": True})], [("332.72 倍", {"bold": True})], [("68.04% / 15.97%", {"bold": True})], [("真二板89%在09:45前触发", {})]],
        [[("改 09:25 全直买", {})], [("132.38 倍", {})], [("50.0% / 30.8%", {})], [("未触50笔直买胜率仅2.0%", {})]],
        [[("放开挂全天至 15:00", {})], [("279.7 倍", {})], [("尾盘5笔 0% 胜率", {})], [("13点后均亏 -5.28% 丢53x", {})]],
        [[("放开单题材涨停>35家", {})], [("274.90 倍", {})], [("新增4笔胜率 0%", {})], [("新增笔均 -5.25%，门禁必留", {})]],
        [[("取消紧密度满 37 分", {})], [("新增5笔亏", {})], [("胜率40%，盈亏比 0.39", {})], [("笔均 -1.67%，门禁必留", {})]],
    ]
    tables.append((t3_title, t3_rows))

    t4_title = "附录：一进二 V20 机构检验与 CUSUM 红线速查表"
    t4_rows = [
        [[("检验维度", {"bold": True})], [("实测指标值", {"bold": True})], [("警告阈值（黄灯）", {"bold": True})], [("停机阈值（红灯）", {"bold": True})]],
        [[("HLZ t 值 / DSR", {})], [("t 4.43 / DSR 0.9995", {})], [("连续亏损 5 笔", {})], [("连续亏损 6 笔", {})]],
        [[("4F Alpha / 保本成本", {})], [("+141.4% / 333.3 bps", {})], [("近20笔均赚 < +1.12%", {})], [("近20笔均赚 < +0.26%", {})]],
        [[("延迟 +5 分钟压测", {})], [("35 笔买不到涨停", {})], [("近20笔胜率 < 45.0%", {})], [("近20笔胜率 < 40.0%", {})]],
        [[("CUSUM 累积和", {})], [("五年历史峰值 40.6%", {})], [("人工减半仓位排查", {})], [("S_t 达到 91.7% 停机", {})]],
    ]
    tables.append((t4_title, t4_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/chart_1to2_v20.png"

    return {
        "title": "一进二",
        "doc_id": "OeJed4uL5oQ2nRxeOXIc4HronDe",
        "node_token": "TRE2wRsLbimSFhkl7sPc9XZHnBj",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }
