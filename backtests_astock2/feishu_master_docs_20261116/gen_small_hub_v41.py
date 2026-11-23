# -*- coding: utf-8 -*-
"""小策略总入口 V4.1（对齐 V19.1 红队物理真账校准版）飞书主文档生成器"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_small_hub_v41_blocks():
    blocks = []

    # 第 1 段：总定位与最新顺位更新
    p1 = [
        make_text_run("本页为小策略总入口，超跌撬板为唯一实盘辅助小策略。"),
        make_text_run(
            "全盘顺位：三进四 > 高标首阴 > 超跌撬板 > 二进三 > 一进二。",
            background_color=3,
        ),
        make_text_run("对应版本为 V4.1、V5.1、V2.1、V2.1 与 V19。"),
        make_text_run("二进三 V2.1 已升格核心主策略，原全局第 4 顺位保持不变。"),
        make_text_run("原四进五 V2.0 下放研究席保留参照，已移出实盘与模拟盘队列。"),
        make_text_run("其余基本面短线、左侧撬板与七项旧线全部永久废止，严禁复燃。"),
    ]
    blocks.append(make_para_block(p1))

    # 第 2 段：各小策略去留与定位总述
    p2_head = [
        make_text_run("小策略板块现行分级结论", bold=True, underline=True),
        make_text_run("，分为实盘补位、研发观察与永久作废三类："),
    ]
    blocks.append(make_para_block(p2_head))

    # 有序列表 3 条
    o1 = [
        make_text_run("实盘第 3 顺位：超跌撬板 V2.1（原账零违规确认）。", bold=True),
        make_text_run("专做连续急跌后温和开盘反弹，满 165 分出手，S 档 175 分。", background_color=3),
        make_text_run("废除连挂四天死限价单，增 09:25 全场涨停少于 5 家逃命开关。"),
        make_text_run("红队核验原账零违规，16 笔胜率 87.50%，单仓 2.44 倍。"),
        make_text_run("回撤 19.15%，近三年 8 笔 1.49 倍。2026 年 2 笔 1.09 倍。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("升格主策略第 4 顺位：二进三 V2.1（归位真版并修除权）。", bold=True),
        make_text_run("底分 60 分共 18 项正交因子，标准 90 分，96 分高严档顶部重点提醒。", background_color=3),
        make_text_run("封死三板后 13:45 摸 +8.5% 护利线由 +5.0% 升至 +6.5%。"),
        make_text_run("已清理错挂淘汰版本并修复 2 笔除权，95 笔胜率升至 53.68%。"),
        make_text_run("完备库单仓由 313.87 倍升至 404.71 倍。盈亏比 4.57，回撤 28.68%。"),
        make_text_run("百万封顶升至 54.06 倍，近三年 15.23 倍，2026 年 4.64 倍。"),
        make_text_run("满 96 分档 35 笔 23.36 倍。回撤 15.87%，26 年胜率 83.33%。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("下放研发与永久作废区（零实盘排单）。", bold=True),
        make_text_run("四进五 V2.0 移出实盘排单队列，转入研究席继续追踪空间破局样本。"),
        make_text_run("旧版 42 因子二进三、错挂淘汰版本、基本面短线与左侧撬板永久淘汰。"),
        make_text_run("旧四分仓自动买与多套冗余旧门槛均已随总纲彻底下线。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    # 第 3 段：V19.1 组合协同核心数据
    p3 = [
        make_text_run(
            "V19.1 物理真账五顺位合体 228 笔，胜率 64.91%，盈亏比 2.90。",
            background_color=3,
        ),
        make_text_run("百万起千万封顶 187.47 倍，千万单利 21.52 倍，回撤 40.12%。"),
        make_text_run("近三年 127 笔封顶 109.89 倍。2026 年 43 笔封顶 21.10 倍。"),
        make_text_run("注意 2025 年二进三 8 笔胜率 25.00%。官库 +4.41%，完备 -2.09%。"),
        make_text_run("当年跑输沪深300（+17.66%），故在强趋势抱团年由前顺位优先接管仓位。"),
    ]
    blocks.append(make_para_block(p3))

    # 第 4 段：子文档分工与跳转说明
    p4_head = [
        make_text_run("小策略子文档与实盘分工规矩", bold=True, underline=True),
        make_text_run("，查阅与执行口径如下："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("超跌撬板详见独立子节点《撬板》，已同步 V2.1 四步动态卖法与零违规核验。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("二进三详见子节点《二进三》，V2.1 真版规则与除权校准数字已同步更新。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("四进五节点降为研发档案只读参照，每日盘前不再生成实盘下单指令。"),
    ]
    blocks.append(make_bullet_block(b3))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格（严格 <= 4 列，细胞 <= 32 字）
    tables = []

    t1_title = "附录：小策略当前状态与实盘顺位总表（V19.1）"
    t1_rows = [
        [[("策略名称", {"bold": True})], [("当前定位", {"bold": True})], [("触发门槛", {"bold": True})], [("核心变化与结论", {"bold": True})]],
        [[("超跌撬板 V2.1", {"bold": True})], [("唯一辅策(第3顺位)", {"bold": True})], [("165 分 / S 175 分", {})], [("四步卖法+原账零违规2.44x", {"bold": True})]],
        [[("二进三 V2.1", {"bold": True})], [("核心主策(第4顺位)", {"bold": True})], [("90 分 / 顶醒 96 分", {})], [("修2笔除权升至404.71x", {"bold": True})]],
        [[("四进五 V2.0", {})], [("下放研发池", {})], [("仅研发观察", {})], [("移出实盘队列，保留研究参照", {})]],
        [[("旧42因子与错挂版", {})], [("永久淘汰", {})], [("已废止", {})], [("由 18 因子 V2.1 真版接替", {})]],
        [[("基本面与左侧撬", {})], [("永久淘汰", {})], [("已废止", {})], [("实证亏损且违背顺位纪律", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：撬板与二进三 V2.1 物理校准前后实证对比表"
    t2_rows = [
        [[("策略与版本", {"bold": True})], [("五年笔数与胜率", {"bold": True})], [("单仓 / 百万封顶 / 回撤", {"bold": True})], [("核心改善结论", {"bold": True})]],
        [[("超跌撬板 V1.0", {})], [("16笔 / 75.00%", {})], [("1.94x / 等权3.33x / 21.42%", {})], [("旧版死限价单常卖飞涨停尾", {})]],
        [[("超跌撬板 V2.1", {"bold": True})], [("16笔 / 87.50%", {"bold": True})], [("2.44x / 等权3.81x / 19.15%", {"bold": True})], [("零违规，近3年1.49x，26年1.09x", {"bold": True})]],
        [[("二进三 V2.1(校准前)", {})], [("95笔 / 52.63%", {})], [("313.87x / 51.31x / 28.68%", {})], [("名臣与北方除权未复权错算", {})]],
        [[("二进三 V2.1(物理真账)", {"bold": True})], [("95笔 / 53.68%", {"bold": True})], [("404.71x / 54.06x / 28.68%", {"bold": True})], [("盈亏比4.57，96分23.36x", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "小策略",
        "doc_id": "UVEWdG2ZqoJqXqxdbJNcNZM1nme",
        "node_token": "MNp3wiZMWihVBDkZrnRcAFJanOg",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
