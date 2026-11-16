# -*- coding: utf-8 -*-
"""退潮切消费与大跌切银行防御小策略飞书主文档生成器"""
from build_master_docs import make_text_run, make_para_block, make_ordered_block, make_bullet_block, make_blank_line, validate_runs, validate_table

def build_defensive_switch_blocks(doc_id, node_token):
    doc_name = "大跌切银行与退潮切消费证伪"
    blocks = []

    # 第 1 段：精炼定位
    p1 = [make_text_run("小策略防御与避坑备查文档，退潮切消费与大跌切银行量化定版。2021年1月至2026年11月连续近六年全样本实测，全面证伪科技退潮日买消费的盘中视觉陷阱，量化确立放量恐慌暴跌日买入绩优城商行持有三至五天的防御顺位。")]
    validate_runs(p1, doc_name)
    blocks.append(make_para_block(p1))

    # 第 2 段：市场阶段与门槛切换 + 战绩 + 禁做红线
    p2 = [
        make_text_run("这是大盘系统性风险期防御切换的一种，"),
        make_text_run("在科技大退潮日全面禁止切换买白酒与生猪，在2024年至2026年红利时代且大盘单日放量恐慌暴跌满2.0%时尾盘买入绩优城商行", background_color=3),
        make_text_run("。近六年全样本实证显示，科技大跌买白酒与生猪各持有周期绝对胜率仅在31.6%至45.7%，单笔收益全线亏损，大幅跑输沪深300指数；而在2024年至2026年红利托底时代，放量恐慌暴跌尾盘买入高ROE绩优城商行持有3至5天，绝对胜率达到67.4%，单笔均利赚0.97%，最大回撤仅6.1%，相对沪深300录得稳定正超额。"),
        make_text_run("绝不可以在科技退潮日接盘消费股或在缩量阴跌假护盘日买银行", bold=True, text_color=1),
        make_text_run("，极易遭遇流动性虹吸迟到补跌与护盘撤单闷杀。")
    ]
    validate_runs(p2, doc_name)
    blocks.append(make_para_block(p2))

    # 第 3 段：买点总起
    p3_head = [
        make_text_run("在放量恐慌大跌日（Day1）尾盘买入银行", bold=True, underline=True),
        make_text_run("，交易守则：")
    ]
    validate_runs(p3_head, doc_name)
    blocks.append(make_para_block(p3_head))

    # 有序列表 3 条
    o1 = [
        make_text_run("坚决执行分支A禁买令：科技大跌日盘中白酒与生猪逆势拉升一律视为一日游诱多陷阱，禁止任何买入", background_color=3),
        make_text_run("，"),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("，次日科技一旦超跌反弹，全场投机资金瞬间从防御板块抽血回流科技，逆势飘红的消费股沦为第一提款机，遭遇惨烈迟到补跌。")
    ]
    validate_runs(o1, doc_name)
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("分支B时代与盘面硬门槛：必须处于红利低利率周期，且沪深300单日暴跌满1.5%至2.0%全场放量恐慌", background_color=3),
        make_text_run("，坚决避开缩量阴跌假护盘模式（胜率仅36.1%单笔均亏），唯有全场割肉盘涌出时国家队进场抄底方有大弹性。")
    ]
    validate_runs(o2, doc_name)
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("标的池绝对锁定高ROE绩优城商行等权组合（江苏银行、成都银行、杭州银行、宁波银行、招商银行），禁止买冷门杂毛银行", background_color=3),
        make_text_run("，绩优城商行基本面扎实且兼具红利属性与游资合力弹性。")
    ]
    validate_runs(o3, doc_name)
    blocks.append(make_ordered_block(o3, seq="auto"))

    # 挂单手操段
    p3_trade = [make_text_run("最新14点55分同花顺手操挂单口径：放量恐慌大跌日尾盘14点55分挂同花顺《普通限价单》，委托价填现价乘1.005买入高ROE绩优城商行等权组合，不在盘中盲目猜底，不推迟到次日追高。")]
    validate_runs(p3_trade, doc_name)
    blocks.append(make_para_block(p3_trade))

    # 第 4 段：卖点总起
    p4_head = [
        make_text_run("卖出点：严守持有三至五个交易日尾盘清仓", bold=True, underline=True),
        make_text_run("，买谁按谁的规则卖，中途出现其他策略信号绝不提前腾仓")
    ]
    validate_runs(p4_head, doc_name)
    blocks.append(make_para_block(p4_head))

    # 无序列表 3 条
    b1 = [
        make_text_run("持有周期："),
        make_text_run("必须拿足3至5个交易日（胜率达67.4%）", background_color=3),
        make_text_run("，持有1天胜率仅44.2%，次日早盘受隔夜恐慌惯性打压急于卖出必被洗出。")
    ]
    validate_runs(b1, doc_name)
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("出场执行："),
        make_text_run("持有满5个交易日于尾盘14点55分全部平仓离场", background_color=3),
        make_text_run("，持有满10天胜率略降回撤放大，不及5天高效。")
    ]
    validate_runs(b2, doc_name)
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("止损红线："),
        make_text_run("持有期间若遭遇宏观债务黑天鹅且单票亏损达4.5%无条件收盘止损", background_color=3),
        make_text_run("，严控防御仓位回撤。")
    ]
    validate_runs(b3, doc_name)
    blocks.append(make_bullet_block(b3))

    # 第 5 段：延伸证伪
    p5 = [make_text_run("策略的延伸，是尝试在科技大跌日等白酒或生猪逆势翻红（跷跷板资金确认）后再追入。回测证实等跷跷板确认买入亏损幅度从负0.09%扩大至负0.62%至负2.04%，胜率跌破32%，比盲买还要惨烈得多；因为日内逆势翻红纯属先手资金避险拉升，尾盘追入纯属为先手资金抬轿接盘，次日流动性虹吸必然导致踩踏。")]
    validate_runs(p5, doc_name)
    blocks.append(make_para_block(p5))

    # 第 6 段：失效问题
    p6 = [
        make_text_run("关于"),
        make_text_run("策略的失效问题", bold=True, text_color=1),
        make_text_run("，核心关注点是"),
        make_text_run("宏观利率环境与地产债务坏账预期", background_color=3),
        make_text_run("。在2021年至2023年外资流出与地产违约主跌浪期，大跌买银行胜率不足40%；唯有在国家队托底且资产荒红利牛周期方能稳定生效；一旦宏观环境重回债务信用紧缩，防御策略立即失效，必须切换为全仓现金空仓防守。")
    ]
    validate_runs(p6, doc_name)
    blocks.append(make_para_block(p6))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格
    tables = []

    # 附录 1：科技大退潮买消费实证对比
    t1_title = "附录：科技大退潮买消费全周期实证对比表"
    t1_rows = [
        [[("目标标的池", {"bold": True})], [("入场条件与时点", {"bold": True})], [("持有天数", {"bold": True})], [("交易胜率", {"bold": True})], [("扣费单笔均利", {"bold": True})]],
        [[("白酒核心资产", {})], [("盲买 / 当日尾盘", {})], [("持有1天", {})], [("38.2%", {})], [("亏0.38%", {})]],
        [[("白酒核心资产", {})], [("盲买 / 当日尾盘", {})], [("持有3天", {})], [("45.7%", {})], [("赚0.02%", {})]],
        [[("白酒核心资产", {})], [("跷跷板确认 / 当日尾盘", {})], [("持有3天", {})], [("36.8%", {})], [("亏0.62%", {})]],
        [[("生猪核心资产", {})], [("盲买 / 当日尾盘", {})], [("持有3天", {})], [("43.3%", {})], [("赚0.11%", {})]],
        [[("生猪核心资产", {})], [("跷跷板确认 / 当日尾盘", {})], [("持有3天", {})], [("31.8%", {})], [("亏1.25%", {})]],
        [[("生猪核心资产", {})], [("跷跷板确认 / 当日尾盘", {})], [("持有5天", {})], [("22.7%", {})], [("亏2.04%", {})]]
    ]
    validate_table(t1_rows, doc_name)
    tables.append((t1_title, t1_rows))

    # 附录 2：大跌买银行时代与模式对比
    t2_title = "附录：大盘下跌买银行不同时代与模式对比表"
    t2_rows = [
        [[("银行资产组合", {"bold": True})], [("时代周期与盘面模式", {"bold": True})], [("交易笔数", {"bold": True})], [("绝对胜率", {"bold": True})], [("扣费单笔均利", {"bold": True})]],
        [[("国有四大行", {})], [("2021年至2023年熊市", {})], [("58笔", {})], [("39.7%", {})], [("亏0.35%", {})]],
        [[("国有四大行", {})], [("2024年至2026年红利牛", {})], [("43笔", {})], [("60.5%", {})], [("赚0.36%", {})]],
        [[("高ROE城商行", {})], [("2021年至2023年熊市", {})], [("58笔", {})], [("39.7%", {})], [("亏0.34%", {})]],
        [[("高ROE城商行", {"bold": True})], [("2024年至2026年红利牛", {"bold": True})], [("43笔", {"bold": True})], [("58.1%", {"bold": True})], [("赚0.76%", {"bold": True})]],
        [[("高ROE城商行", {})], [("模式一：缩量阴跌假护盘", {})], [("36笔", {})], [("36.1%", {})], [("亏0.44%", {})]],
        [[("高ROE城商行", {"bold": True})], [("模式二：放量恐慌暴跌", {"bold": True})], [("28笔", {"bold": True})], [("57.1%（近三年66.7%）", {"bold": True})], [("赚0.58%（近三年赚1.22%）", {"bold": True})]]
    ]
    validate_table(t2_rows, doc_name)
    tables.append((t2_title, t2_rows))

    # 附录 3：持仓天数敏感度
    t3_title = "附录：银行资产持仓天数敏感度检验表"
    t3_rows = [
        [[("持仓天数", {"bold": True})], [("交易笔数", {"bold": True})], [("绝对胜率", {"bold": True})], [("扣费单笔均利", {"bold": True})], [("最大回撤", {"bold": True})]],
        [[("持有1天", {})], [("43笔", {})], [("44.2%", {})], [("亏0.06%", {})], [("10.5%", {})]],
        [[("持有3天", {})], [("43笔", {})], [("58.1%", {})], [("赚0.76%", {})], [("5.8%", {})]],
        [[("持有5天", {"bold": True})], [("43笔", {"bold": True})], [("67.4%", {"bold": True})], [("赚0.97%", {"bold": True})], [("6.1%", {"bold": True})]],
        [[("持有10天", {})], [("43笔", {})], [("62.8%", {})], [("赚0.93%", {})], [("11.7%", {})]]
    ]
    validate_table(t3_rows, doc_name)
    tables.append((t3_title, t3_rows))

    # 附录 4：实战执行判定清单
    t4_title = "附录：防御策略实战执行判定清单表"
    t4_rows = [
        [[("检验维度", {"bold": True})], [("实操判定标准", {"bold": True})], [("执行决策", {"bold": True})], [("核心物理逻辑", {"bold": True})]],
        [[("科技大跌切消费", {})], [("盘中白酒生猪逆势拉升", {})], [("绝对禁止买入", {})], [("日内避险资金次日抽血补跌", {})]],
        [[("大盘下跌切银行", {})], [("缩量阴跌微幅护盘", {})], [("绝对禁止买入", {})], [("虚假护盘指数掩护出货", {})]],
        [[("大盘暴跌切银行", {})], [("放量恐慌暴跌满2.0%", {})], [("尾盘买入城商行", {})], [("割肉盘涌出国家队真金白银", {})]],
        [[("持仓周期要求", {})], [("买入后严守3至5天", {})], [("满5天尾盘平仓", {})], [("避开次日早盘惯性恐慌洗盘", {})]]
    ]
    validate_table(t4_rows, doc_name)
    tables.append((t4_title, t4_rows))

    return {
        "title": "大跌切银行与退潮切消费证伪",
        "doc_id": doc_id,
        "node_token": node_token,
        "blocks": blocks,
        "img_path": None,
        "tables": tables
    }

if __name__ == "__main__":
    d = build_defensive_switch_blocks("test_id", "test_tok")
    print("大跌切银行与退潮切消费证伪校验成功，正文块数:", len(d["blocks"]), "表格数:", len(d["tables"]))
