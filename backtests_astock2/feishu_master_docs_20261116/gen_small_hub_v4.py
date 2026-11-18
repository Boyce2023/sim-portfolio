# -*- coding: utf-8 -*-
"""小策略总入口 V4.0（对齐 V19.0 全局五顺位与二进三 V2.0 转正）飞书主文档生成器"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_small_hub_v4_blocks():
    blocks = []

    # 第 1 段：总定位与最新顺位更新
    p1 = [
        make_text_run("本页为小策略与辅线总入口，已对齐 V19.0 全局五顺位体系。"),
        make_text_run(
            "全盘顺位：三进四 > 高标首阴 > 超跌撬板 > 二进三 > 一进二。",
            background_color=3,
        ),
        make_text_run("对应版本为 V4.0、V5.1、V1.0、V2.0 与 V19。"),
        make_text_run("核心升级是二进三 V2.0 正式转正，位列实盘第 4 顺位。"),
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
        make_text_run("实盘第 3 顺位：超跌撬板 V1.0（保留在产）。", bold=True),
        make_text_run("专做连续急跌后早盘温和开盘反弹，底分 100 分。", background_color=3),
        make_text_run("门槛满 165 分出手，S 档 175 分，承担强风控窄门补位。"),
        make_text_run("独立五年 16 笔胜率 75.00%，单仓仅 1.94 倍。"),
        make_text_run("排在三进四与高标首阴之后，仅在生态退潮空仓日补位。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("实盘第 4 顺位：二进三 V2.0（跨板位互学转正入列）。", bold=True),
        make_text_run("经跨板位互学重修后，底分 60 分共 18 项正交整数因子。", background_color=3),
        make_text_run("标准 90 分档五年 94 笔胜率 52.13%，盈亏比 4.01。"),
        make_text_run("单仓升至 144.21 倍，百万起千万封顶 41.65 倍。"),
        make_text_run("回撤压降至 28.68%，通过全套防过拟合考验。"),
        make_text_run("满 96 分高严档五年 35 笔回撤仅 15.87%。"),
        make_text_run("该高严档 2026 年 6 笔胜率达 83.33%。"),
        make_text_run("早盘报告顶部对满 96 分信号无条件单独重点提醒，供实盘优先决策。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("下放研发与永久作废区（零实盘排单）。", bold=True),
        make_text_run("四进五 V2.0 移出实盘排单队列，转入研究席继续追踪空间破局样本。"),
        make_text_run("旧版 42 因子二进三、基本面短线、20 厘米撬板与当日左侧撬板永久淘汰。"),
        make_text_run("旧四分仓自动买与多套冗余旧门槛均已随 V19.0 总纲彻底下线。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    # 第 3 段：二进三 V2.0 转正实证与组合协同核心数据
    p3 = [
        make_text_run(
            "120种全排列实证将二进三列第 4 顺位，五策略合计 227 笔。",
            background_color=3,
        ),
        make_text_run("五策略总胜率 64.32%，盈亏比升至 3.17，09:26零挂单空耗。"),
        make_text_run("百万起千万封顶达 183.31 倍，千万起单利升至 21.16 倍。"),
        make_text_run("样本内与样本外双段领跑，显著提升资金周转与高赔率弹性。"),
        make_text_run("注意 2025 年二进三仅 8 笔胜率 25.00%，当年小赚 4.41%。"),
        make_text_run("当年跑输涨 17.66% 的沪深300 达 13.25 个百分点。"),
        make_text_run("因此在强趋势抱团年份，由排前面的三进四与高标首阴优先接管仓位。"),
    ]
    blocks.append(make_para_block(p3))

    # 第 4 段：子文档分工与跳转说明
    p4_head = [
        make_text_run("小策略子文档与实盘分工规矩", bold=True, underline=True),
        make_text_run("，查阅与执行口径如下："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("超跌撬板详见独立子节点《超跌撬板》，严格限 10 厘米主板非一字早盘执行。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("二进三详见子节点《二进三》，V2.0 全套规则与互学参数已同步升版。"),
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

    t1_title = "附录：小策略当前状态与实盘顺位总表"
    t1_rows = [
        [[("策略名称", {"bold": True})], [("当前定位", {"bold": True})], [("触发门槛", {"bold": True})], [("核心变化与结论", {"bold": True})]],
        [[("超跌撬板 V1.0", {})], [("实盘第 3 顺位", {})], [("165 分 / S 175 分", {})], [("二进三与一进二前窄门补位", {})]],
        [[("二进三 V2.0", {"bold": True})], [("实盘第 4 顺位", {"bold": True})], [("90 分 / 顶醒 96 分", {"bold": True})], [("互学升级达标，正式转正入列", {"bold": True})]],
        [[("四进五 V2.0", {})], [("下放研发池", {})], [("仅研发观察", {})], [("移出实盘队列，保留研究参照", {})]],
        [[("旧42因子二进三", {})], [("永久淘汰", {})], [("已废止", {})], [("由 18 因子 V2.0 全面接替", {})]],
        [[("基本面与左侧撬", {})], [("永久淘汰", {})], [("已废止", {})], [("实证亏损且违背顺位纪律", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：二进三升级前后与跨期实证对比表"
    t2_rows = [
        [[("版本与档位", {"bold": True})], [("五年笔数与胜率", {"bold": True})], [("单仓 / 千万起封顶 / 回撤", {"bold": True})], [("统计检验与近期表现", {"bold": True})]],
        [[("前版 V1.0(90)", {})], [("77笔 / 48.05%", {})], [("20.32x / 4.99x / 36.72%", {})], [("t=2.53 / DSR 40.08% 未达标", {})]],
        [[("定版 V2.0(90)", {"bold": True})], [("94笔 / 52.13%", {"bold": True})], [("144.21x / 7.14x / 28.68%", {"bold": True})], [("t=3.83 / DSR 95.76% 全过关", {"bold": True})]],
        [[("定版 V2.0(96)", {"bold": True})], [("35笔 / 54.29%", {"bold": True})], [("17.43x / 4.64x / 15.87%", {"bold": True})], [("2026年 6笔胜率 83.33%", {"bold": True})]],
        [[("超跌撬板 V1.0", {})], [("16笔 / 75.00%", {})], [("1.94x / 辅位补仓 / 21.42%", {})], [("近3年 8笔胜率 75.00%", {})]],
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
