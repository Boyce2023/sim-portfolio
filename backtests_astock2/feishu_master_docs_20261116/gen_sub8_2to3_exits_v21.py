# -*- coding: utf-8 -*-
"""子文档8：20261118 二进三V2.1分时护利与动态卖点回测"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub8_2to3_exits_v21_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "结论：13:45 护利升至 +6.5% 非常有用，改动 17 笔全胜零负。",
            background_color=3,
        ),
        make_text_run(
            "完备 5 分钟单仓升至 313.87 倍，官库升至 157.85 倍。",
            background_color=3,
        ),
        make_text_run("但第 4 日早盘硬砍未封三板没用，样本外多割在地板。", background_color=3),
        make_text_run("完备库 90 分单仓原版 261.05 倍，百万封顶升至 51.31 倍。"),
        make_text_run("官库口径 90 分单仓原版 144.21 倍，百万封顶升至 42.75 倍。"),
        make_text_run("96 分高严档完备库由 20.84 倍升至 23.36 倍。官库升至 18.54 倍。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("研究同步构建官库 5 分钟与补全缺失持有日的完备 5 分钟双轨，消除数据盲区。"),
        make_text_run("官库对未封三板次日覆盖率仅 2.9%，补齐至 100% 后才可真实检验早盘均线。"),
        make_text_run("全部参数先在 2021 至 2023 年样本内定标。再经样本外盲测检验。"),
        make_text_run("2025 年初物理截断复验 99 笔历史交易，得分与收益率偏差严格为 0.0。"),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("有用升级与没用淘汰的三项物理机理", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run("连板 13:45 护利从 +5.0% 升至 +6.5% 是核心真增益。", bold=True),
        make_text_run("完备库改动 17 笔均多收（12 内 5 外），平均每笔多 +1.76 点。", background_color=3),
        make_text_run("核心邻域 12 组参数中 11 组四象限全赢，回落至 +7.5% 起触发震仓悬崖。"),
        make_text_run("定版 +6.5% 居中稳守高原，既规避下午流动性衰减又绝不误杀洗盘龙头。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("第 4 日 09:25 硬砍未封三板没用，专割在早盘恐慌地板。", bold=True),
        make_text_run("未封三板占 73% 信号，样本外 09:25 斩仓的 4 笔有 3 笔割在地板。", background_color=3),
        make_text_run("骏亚科技早盘 -4.61% 砍出而尾盘 +3.79%。四笔合计少收 11.77 点。"),
        make_text_run("且 2023 年底六连亏源于微盘冬眠期系统波动，硬砍反而误杀午后反包大妖。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("30 项持仓风险打分卡因盲测分化与公告噪音暂不上线。", bold=True),
        make_text_run("2025 年起常规异常波动公告暴增 4 倍，误杀长城军工单笔少收 34.97 点。", background_color=3),
        make_text_run("合成卡虽推升官库与 96 分档，但完备库 90 分与 84 分样本外均回落。"),
        make_text_run("按样本外严格纪律判定不上线，仅留剥离公告噪音后的连板预警作前瞻跟踪。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p4_head = [
        make_text_run("跨策略移植淘汰项与龙虎榜合规细节", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("已彻底否定在二进三连板期挂双异动缓冲单与取消首次真阳断板免死。"),
        make_text_run("挂 93% 或 96% 缓冲单会在高板抢跑赣能股份等总龙，拉低样本内净值。", background_color=3),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("同步淘汰次日高开止盈扩至连板日、10:30 均线替代护利与早盘低开砍。"),
        make_text_run("实证兼容国泰君安与国泰海通合并后的营业部代码，避免 2025 年起漏掉龙虎榜席位。"),
    ]
    blocks.append(make_bullet_block(b2))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：二进三两轮 260+ 变体与 30 项持仓因子检验汇总表"
    t1_rows = [
        [[("测试方案与阶段", {"bold": True})], [("完备 90分 样本内/外", {"bold": True})], [("完备库五年 / 96分", {"bold": True})], [("裁决结论", {"bold": True})]],
        [[("原版 V2.0 (+5.0%护利)", {})], [("40.30x / 17.32x", {})], [("261.05x / 20.84x", {})], [("上轮基线", {})]],
        [[("定版 V2.1 (+6.5%护利)", {"bold": True})], [("45.72x / 18.87x", {"bold": True})], [("313.87x / 23.36x", {"bold": True})], [("唯一全过线，正式上线", {"bold": True})]],
        [[("官库口径 V2.1 (+6.5%)", {})], [("29.50x / 12.76x", {})], [("157.85x / 18.54x", {})], [("官库与完备库双双提升", {})]],
        [[("早盘09:25硬砍未封(合成卡)", {})], [("59.68x / 16.65x", {})], [("347.96x / 84分外 9.45x", {})], [("样本外分化且误杀，淘汰", {})]],
        [[("双异动93%单 / 零免死", {})], [("37.61x / 16.71x", {})], [("231.64x / 样本外 16.35x", {})], [("砍飞总龙头，淘汰", {})]],
        [[("纯连板风险预警(消融)", {})], [("54.10x / 19.80x", {})], [("377.64x / 25.57x", {})], [("待剥离公告噪音后前瞻跟踪", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：二进三 V2.1 护利阈值参数高原与八项检验表"
    t2_rows = [
        [[("回落线或指标", {"bold": True})], [("完备样本内 90 / 96", {"bold": True})], [("完备库样本外 90分", {"bold": True})], [("官库对照与定论", {"bold": True})]],
        [[("+5.0% (V2.0 原版)", {})], [("40.30x / 11.84x", {})], [("17.32x", {})], [("官库五年 144.21 倍", {})]],
        [[("+6.0% (邻域低档)", {})], [("44.04x / 12.30x", {})], [("18.43x", {})], [("温和正增益区间", {})]],
        [[("+6.5% (V2.1 定版)", {"bold": True})], [("45.72x / 12.54x", {"bold": True})], [("18.87x", {"bold": True})], [("官库157.85x，17笔17胜0负", {"bold": True})]],
        [[("+7.5% (悬崖边界)", {})], [("41.02x / 11.15x", {})], [("19.64x", {})], [("96分样本内跌破原版，弃用", {})]],
        [[("HLZ t / DSR150 / PBO", {})], [("4.22 / 0.9868 / 1.98%", {})], [("地狱压测 58.61 倍", {})], [("官库 t=3.83 / DSR 0.9583", {})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261118 二进三V2.1分时护利与动态卖点回测",
        "parent_node_token": "WrlywVBEOicuVfk15yEcsmfenUg",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
