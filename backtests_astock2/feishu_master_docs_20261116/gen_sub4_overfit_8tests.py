# -*- coding: utf-8 -*-
"""子文档4：20261116 全策略八项防过拟合联合大体检报告"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub4_overfit_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "结论：八项防过拟合体检对去伪存真极有用，筛出四大主战真策略并揪出两项伪策略。",
            background_color=3,
        ),
        make_text_run(
            "四大主策略 DSR 全超 95.7% 过关。旧 26Q4 凑分与五板卡异动未过检淘汰。",
            background_color=3,
        ),
        make_text_run("高标、三进四、一进二与二进三齐过线。四者 DSR 全部跨过 95% 红线。"),
        make_text_run("旧版 26Q4 微观凑分出现 PBO 飙升警报，随后已被滚动夏普框架彻底替换。"),
        make_text_run("五板卡异动全五年大亏且显著性为负，超跌撬板仅 16 笔只保留作窄门辅助。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("八项防过拟合体检核心发现", bold=True, underline=True),
        make_text_run("，检验覆盖显著性、防挑拣、防孤岛与地狱滑点："),
    ]
    blocks.append(make_para_block(p2_head))

    o1 = [
        make_text_run("主战合体与单策略均非抛硬币，统计显著性极硬。", bold=True),
        make_text_run("四大主战单仓合体 181 笔 t 值达 5.37。150 次试验 DSR 达 99.98%。", background_color=3),
        make_text_run("5000 次猴子盲抓检验 p 值为 0.0002。过拟合概率 PBO 仅 4.29%。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("11 月 17 日互学升级把最后一块黄灯短板拉成全绿。", bold=True),
        make_text_run("三进四升至 V4.0 后统计过线。DSR 从 91.35% 跃至 98.18%。", background_color=3),
        make_text_run("二进三升至 V2.0 后彻底转正。DSR 从 40.08% 飙至 95.76%，t 值 3.83。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("三大隐患与伪策略被体检精准揪出并及时淘汰。", bold=True),
        make_text_run("五板卡异动 t 值为负 1.04，地狱压测千万封顶倒亏 97.96% 彻底作废。", background_color=3),
        make_text_run("超跌撬板仅 16 笔、猴子 p 值 0.1674。严限仅作第 3 顺位窄门补位。"),
        make_text_run("旧 26Q4 高标 PBO 飙至 41.43%。旧合体 PBO 达 32.86%，已于 16 日废除。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3 = [
        make_text_run("防伪纪律底线：未来升版必先过这八项体检。"),
        make_text_run("DSR 不达 95% 或 PBO 逼近 50% 禁止投产。", background_color=3),
        make_text_run("三策略全部经过砍去前三极值与两倍滑点加砍头部赢家的地狱压力测试，依然稳健大赚。"),
    ]
    blocks.append(make_para_block(p3))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：11月16日全盘 11 项策略八项防过拟合体检总表"
    t1_rows = [
        [[("策略名称", {"bold": True})], [("笔数 / 显著性 t", {"bold": True})], [("DSR150 / PBO", {"bold": True})], [("地狱压测与最终裁决", {"bold": True})]],
        [[("三大主策略合体", {"bold": True})], [("181笔 / 5.37", {"bold": True})], [("99.98% / 4.29%", {"bold": True})], [("地狱赚939.9% / 全绿", {"bold": True})]],
        [[("加撬板四合一", {"bold": True})], [("186笔 / 5.50", {"bold": True})], [("99.99% / 4.29%", {"bold": True})], [("地狱赚985.5% / 全绿", {"bold": True})]],
        [[("高标首阴 V5.1", {"bold": True})], [("42笔 / 5.30", {"bold": True})], [("98.93% / 0.00%", {"bold": True})], [("地狱赚237.4% / 全绿", {"bold": True})]],
        [[("一进二 V18 原版", {"bold": True})], [("96笔 / 4.07", {"bold": True})], [("99.45% / 2.86%", {"bold": True})], [("地狱赚519.3% / 全绿", {"bold": True})]],
        [[("三进四 V3.4 原版", {})], [("88笔 / 3.56", {})], [("91.35% / 0.00%", {})], [("轻黄灯，次日升级V4.0", {})]],
        [[("旧26Q4合体与高标", {})], [("206与40笔", {})], [("PBO 32.9%与41.4%", {})], [("局部过拟合，已淘汰", {})]],
        [[("旧26Q4三进四与一进二", {})], [("97与113笔", {})], [("DSR 83.1%与95.3%", {})], [("三进四未过线，已淘汰", {})]],
        [[("辅助超跌撬板 V1.0", {})], [("16笔 / 1.45", {})], [("17.42% / 21.43%", {})], [("猴子p=0.167，窄门辅助", {})]],
        [[("辅助五板卡异动", {})], [("72笔 / 负1.04", {})], [("0.01% / 11.43%", {})], [("地狱亏98.0% / 永久作废", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：11月17日互学升级后三策略最新八项指标对照表"
    t2_rows = [
        [[("现行定版策略", {"bold": True})], [("笔数 / 显著性 t", {"bold": True})], [("DSR150 / PBO", {"bold": True})], [("去极值与地狱压测", {"bold": True})]],
        [[("三进四 V4.0", {"bold": True})], [("95笔 / 4.09", {"bold": True})], [("98.18% / 0.00%至3.57%", {"bold": True})], [("地狱单仓留存 297.45 倍", {"bold": True})]],
        [[("一进二 V19", {"bold": True})], [("97笔 / 4.08", {"bold": True})], [("99.45% / 6.75%", {"bold": True})], [("地狱单仓留存 80.01 倍", {"bold": True})]],
        [[("二进三 V2.0(90)", {"bold": True})], [("94笔 / 3.83", {"bold": True})], [("95.76% / 5.56%至7.14%", {"bold": True})], [("地狱单仓留存 38.05 倍", {"bold": True})]],
        [[("二进三 V2.0(96)", {})], [("35笔 / 2.62", {})], [("样本仅35笔作顶醒", {})], [("2026年 6笔胜率 83.33%", {})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261116 全策略八项防过拟合联合大体检报告",
        "parent_node_token": "Jxarwc3wliQZCakXO1xccPmrnCc",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
