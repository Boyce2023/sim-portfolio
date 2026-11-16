# -*- coding: utf-8 -*-
"""小策略顶层汇总导览页生成器"""
from build_master_docs import make_text_run, make_para_block, make_bullet_block, make_blank_line, validate_runs, validate_table

def build_small_hub_blocks():
    doc_name = "小策略"
    blocks = []

    # 第 1 段：定位说明
    p1 = [make_text_run("小策略归口导览库，作为三大主策略（高标首阴、三进四、一进二）的精细化补充与证伪淘汰档案。主要容纳特定极端市场阶段下的高胜率辅助顺位策略、已证伪淘汰备查策略、以及正在归档整理中的专题策略。每天由二号席统一维护，严守与纯单仓主战顺位的物理隔离。")]
    validate_runs(p1, doc_name)
    blocks.append(make_para_block(p1))

    # 第 2 段：分类管理逻辑与纯单仓纪律
    p2 = [
        make_text_run("这是小策略分类管理的总纲，"),
        make_text_run("小策略分为三类管理：第一类是已纳入实盘纯单仓辅助顺位的策略；第二类是全周期实测后证伪淘汰的策略；第三类是正在归档研究的专项策略", background_color=3),
        make_text_run("。日常实盘永远只做纯单仓轮动，旧仓未平绝不开新仓，空仓日09点25分严格按全局顺位机械执行。"),
        make_text_run("绝不可以在未达高严门槛或非空仓日主观随意加仓小策略", bold=True, text_color=1),
        make_text_run("，避免破坏整体回撤控制。")
    ]
    validate_runs(p2, doc_name)
    blocks.append(make_para_block(p2))

    # 第 3 段：纯单仓辅助顺位策略
    p3_head = [
        make_text_run("第一类：已纳入纯单仓辅助顺位的实做小策略", bold=True, underline=True),
        make_text_run("，准入规则：")
    ]
    validate_runs(p3_head, doc_name)
    blocks.append(make_para_block(p3_head))

    b1 = [
        make_text_run("四进五 V2.0 满120分（纯单仓第3顺位）："),
        make_text_run("吃空间破局独苗冲五进七八板", background_color=3),
        make_text_run("，09点25分竞价开在涨2.0%至涨7.5%直接挂保护限价单买入，未封板满足高标首阴原地移交，封死五板严禁挂93%异动单。")
    ]
    validate_runs(b1, doc_name)
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("超跌橡皮筋撬板 V1.0 满165分（纯单仓第4顺位）："),
        make_text_run("吃连续暴跌止血回暖日弱转强快肉", background_color=3),
        make_text_run("，压在容易炸板的一进二前面，盘前预埋动态限价单自动成交止盈，到期第4日清仓。")
    ]
    validate_runs(b2, doc_name)
    blocks.append(make_bullet_block(b2))

    # 第 4 段：已证伪淘汰策略
    p4_head = [
        make_text_run("第二类：全周期实证淘汰与封存策略", bold=True, underline=True),
        make_text_run("，警示纪律：")
    ]
    validate_runs(p4_head, doc_name)
    blocks.append(make_para_block(p4_head))

    b3 = [
        make_text_run("二进三策略（已证伪淘汰永久废止）："),
        make_text_run("五年最优108分档胜率仅47.8%，剔除前三妖股后净值0.90倍亏损", background_color=3),
        make_text_run("，塞入纯单仓抢占三进四与高标槽位使去极值净值暴跌56%，实盘永久空置不做，下设子文档仅留底备查。")
    ]
    validate_runs(b3, doc_name)
    blocks.append(make_bullet_block(b3))

    b4 = [
        make_text_run("当日左侧撬板与20cm撬板："),
        make_text_run("当日买入次日低开闷杀率超60%，20cm胜率仅22.2%", background_color=3),
        make_text_run("，全谱系永久砍掉，实盘绝不涉足。")
    ]
    validate_runs(b4, doc_name)
    blocks.append(make_bullet_block(b4))

    # 第 5 段：正在归档中的专项策略
    p5_head = [
        make_text_run("第三类：正在归档整理中的专题策略", bold=True, underline=True),
        make_text_run("，研究进展：")
    ]
    validate_runs(p5_head, doc_name)
    blocks.append(make_para_block(p5_head))

    b5 = [
        make_text_run("跨年妖策略：专项回测年尾特定时间窗口的大妖股成因与连板路径，目前处于历史数据整理阶段。")
    ]
    validate_runs(b5, doc_name)
    blocks.append(make_bullet_block(b5))

    b6 = [
        make_text_run("退潮与大跌防御切换策略：专项量化退潮期空仓与半仓自检纪律，防范极端踩踏。")
    ]
    validate_runs(b6, doc_name)
    blocks.append(make_bullet_block(b6))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格
    tables = []

    t1_title = "附录：小策略状态与纯单仓顺位总览表"
    t1_rows = [
        [[("子策略名称", {"bold": True})], [("当前定版", {"bold": True})], [("纯单仓顺位", {"bold": True})], [("核心定位", {"bold": True})], [("实盘状态", {"bold": True})]],
        [[("四进五", {})], [("V2.0高严档", {})], [("第3顺位", {})], [("空间破局独苗", {})], [("实做（满120分直买）", {})]],
        [[("超跌橡皮筋撬板", {})], [("V1.0高严档", {})], [("第4顺位", {})], [("暴跌止血弱转强", {})], [("实做（满165分直买）", {})]],
        [[("二进三", {})], [("证伪淘汰版", {})], [("无顺位", {})], [("中位尴尬炮灰", {})], [("永久废止仅备查", {})]],
        [[("跨年妖", {})], [("专题归档中", {})], [("待定", {})], [("年底特定窗口", {})], [("归档整理中", {})]],
        [[("退潮与大跌防御", {})], [("专题归档中", {})], [("待定", {})], [("极端冰点防御", {})], [("归档整理中", {})]]
    ]
    validate_table(t1_rows, doc_name)
    tables.append((t1_title, t1_rows))

    t2_title = "附录：各策略全周期回测指标对比表"
    t2_rows = [
        [[("策略名称", {"bold": True})], [("测试样本", {"bold": True})], [("交易胜率", {"bold": True})], [("真实盈亏比", {"bold": True})], [("实盘裁决", {"bold": True})]],
        [[("高标首阴V5.1", {})], [("42笔", {})], [("73.8%", {})], [("3.01", {})], [("三大主战第1顺位", {})]],
        [[("三进四V3.4", {})], [("88笔", {})], [("64.8%", {})], [("2.23", {})], [("三大主战第2顺位", {})]],
        [[("四进五V2.0", {})], [("19笔", {})], [("68.4%", {})], [("2.45", {})], [("小策略辅助第3顺位", {})]],
        [[("超跌撬板V1.0", {})], [("16笔", {})], [("75.0%", {})], [("2.15", {})], [("小策略辅助第4顺位", {})]],
        [[("一进二V18", {})], [("95笔", {})], [("68.4%", {})], [("2.89", {})], [("三大主战第5顺位", {})]],
        [[("二进三淘汰版", {})], [("69笔", {})], [("47.8%", {})], [("1.45", {})], [("系统性证伪永久废止", {})]]
    ]
    validate_table(t2_rows, doc_name)
    tables.append((t2_title, t2_rows))

    return {
        "title": "小策略",
        "doc_id": "UVEWdG2ZqoJqXqxdbJNcNZM1nme",
        "node_token": "MNp3wiZMWihVBDkZrnRcAFJanOg",
        "blocks": blocks,
        "img_path": None,
        "tables": tables
    }

if __name__ == "__main__":
    d = build_small_hub_blocks()
    print("小策略导览页校验成功，正文块数:", len(d["blocks"]), "表格数:", len(d["tables"]))
