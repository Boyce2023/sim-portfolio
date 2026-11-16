# -*- coding: utf-8 -*-
"""二进三全量因子证伪淘汰主文档生成器"""
from build_master_docs import make_text_run, make_para_block, make_ordered_block, make_bullet_block, make_blank_line, validate_runs, validate_table

def build_2to3_blocks():
    doc_name = "二进三"
    blocks = []

    # 第 1 段：精炼定位与证伪结论
    p1 = [make_text_run("小策略证伪淘汰备查文档，二进三全量因子证伪淘汰定版。2026年11月14日经773切片全市场实测，二进三被系统性证伪淘汰，实盘永久空置不做，仅留底备查。")]
    validate_runs(p1, doc_name)
    blocks.append(make_para_block(p1))

    # 第 2 段：测试战绩与禁做红线
    p2 = [
        make_text_run("这是中位过渡接力的一种，"),
        make_text_run("历史测试过常规与严格各档门槛，最优108分档五年仅69笔交易", background_color=3),
        make_text_run("。交易胜率封顶47.8%（连五成都不到），真实盈亏比仅1.45，最大回撤43.3%，剔除前三妖股后净值仅0.90倍（本金直接缩水亏10%），塞入纯单仓抢占三进四与高标槽位令去极值净值暴跌56%。"),
        make_text_run("实盘严禁开仓交易二进三标的", bold=True, text_color=1),
        make_text_run("，中位尴尬身位极易受上下两头双向挤压，属于典型的炮灰身位。")
    ]
    validate_runs(p2, doc_name)
    blocks.append(make_para_block(p2))

    # 第 3 段：理论买点推演与证伪守则
    p3_head = [
        make_text_run("理论在二连板次日（Day3）买入推演", bold=True, underline=True),
        make_text_run("，证伪守则：")
    ]
    validate_runs(p3_head, doc_name)
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run("二板大换手次日弱转强测试：92笔交易胜率仅44.6%，断板跌停率高达36.8%", background_color=3),
        make_text_run("，"),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("，换手分歧消耗过多多头资金，次日缺乏接力资金封板，容易遭遇日内瀑布杀。")
    ]
    validate_runs(o1, doc_name)
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("二板缩量一字次日接力测试：84笔交易胜率崩塌至28.6%，日内炸板率超42%", background_color=3),
        make_text_run("，缩量加速透支跟风买力，筹码断层极易引发高开低走大阴线核按钮。")
    ]
    validate_runs(o2, doc_name)
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("同题材有三板及以上龙头顶一字压制：胜率仅33.3%，断板跌停率48.9%", background_color=3),
        make_text_run("，身位劣势导致资金全被龙头吸走，跟风票沦为纯粹买单炮灰。")
    ]
    validate_runs(o3, doc_name)
    blocks.append(make_ordered_block(o3, seq="auto"))

    # 避坑提示段
    p3_trade = [make_text_run("实操避坑提示：由于全量切片实证二进三无法跑赢基准，且会严重拖累纯单仓整体净值，每日早盘09点25分系统自动屏蔽二进三一切候选标的，不挂任何买单，坚决不参与二进三接力。")]
    validate_runs(p3_trade, doc_name)
    blocks.append(make_para_block(p3_trade))

    # 第 4 段：卖出推演
    p4_head = [
        make_text_run("卖出推演：断板大面特征与处置模拟", bold=True, underline=True),
        make_text_run("，买谁按谁的规则卖，中途出现其他策略信号绝不提前腾仓")
    ]
    validate_runs(p4_head, doc_name)
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("二进三买入日若未封板："),
        make_text_run("次日低开闷杀概率超55%，必须在次日09点25分竞价止损", background_color=3),
        make_text_run("。")
    ]
    validate_runs(b1, doc_name)
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("二进三即便成功封板，"),
        make_text_run("三进四次日面临全市场最严苛考验，断板日跌停计提率超35%", background_color=3),
        make_text_run("。")
    ]
    validate_runs(b2, doc_name)
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("模拟卖出规则："),
        make_text_run("未封板次日09点25分必须斩仓，断板日一律14点55分出清", background_color=3),
        make_text_run("。")
    ]
    validate_runs(b3, doc_name)
    blocks.append(make_bullet_block(b3))

    # 第 5 段：延伸证伪
    p5 = [make_text_run("策略的延伸，是尝试用题材共振或缩量一字二进三解题，回测证实缩量二板次日接力胜率崩至28.6%，日内炸板率超42%，无论如何调参均无法改变中位炮灰本质。")]
    validate_runs(p5, doc_name)
    blocks.append(make_para_block(p5))

    # 第 6 段：失效问题
    p6 = [
        make_text_run("关于"),
        make_text_run("策略的失效问题", bold=True, text_color=1),
        make_text_run("，核心关注点是"),
        make_text_run("二板到三板的尴尬身位与盈亏比不对称", background_color=3),
        make_text_run("。上面有四板高标吸血，下面有一进二海量筹码分流，二进三既无低位赔率又无高位辨识度，因此决定永久淘汰该策略。")
    ]
    validate_runs(p6, doc_name)
    blocks.append(make_para_block(p6))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格
    tables = []

    t1_title = "附录：二进三全量因子证伪淘汰核心数据表"
    t1_rows = [
        [[("策略版本", {"bold": True})], [("测试样本", {"bold": True})], [("交易胜率", {"bold": True})], [("盈亏比", {"bold": True})], [("累计净值与回撤", {"bold": True})]],
        [[("二进三常规全样本", {})], [("285笔", {})], [("35.8%", {})], [("1.05", {})], [("0.22倍（回撤58.2%）", {})]],
        [[("二进三90分标准档", {})], [("142笔", {})], [("42.3%", {})], [("1.25", {})], [("0.65倍（回撤48.5%）", {})]],
        [[("二进三108分最优档", {})], [("69笔", {})], [("47.8%", {})], [("1.45", {})], [("0.90倍（回撤43.3%）", {})]],
        [[("纯单仓引入二进三", {})], [("215笔", {})], [("61.2%", {})], [("1.85", {})], [("40120倍（回撤38.5%）", {})]],
        [[("纯单仓剔除二进三", {"bold": True})], [("187笔", {"bold": True})], [("67.91%", {"bold": True})], [("2.65", {"bold": True})], [("136325倍（回撤29.22%）", {"bold": True})]]
    ]
    validate_table(t1_rows, doc_name)
    tables.append((t1_title, t1_rows))

    t2_title = "附录：二进三身位尴尬度对比表"
    t2_rows = [
        [[("身位对比维度", {"bold": True})], [("一进二主战", {"bold": True})], [("二进三淘汰", {"bold": True})], [("三进四主战", {"bold": True})], [("高标主战", {"bold": True})]],
        [[("全市场容量", {})], [("容量最大粮仓", {})], [("中位夹缝尴尬", {})], [("主线梯队龙头", {})], [("唯一最高标", {})]],
        [[("全周期胜率", {})], [("68.4%", {})], [("47.8%（不及格）", {})], [("64.8%", {})], [("73.8%", {})]],
        [[("真实盈亏比", {})], [("2.89", {})], [("1.45（极差）", {})], [("2.23", {})], [("3.01", {})]],
        [[("去极值净值", {})], [("35.41倍", {})], [("0.90倍（亏损）", {})], [("33.05倍", {})], [("6.49倍", {})]],
        [[("实盘处置裁决", {})], [("第5顺位常驻", {})], [("永久废止不买", {})], [("第2顺位主战", {})], [("第1顺位主战", {})]]
    ]
    validate_table(t2_rows, doc_name)
    tables.append((t2_title, t2_rows))

    t3_title = "附录：分步证伪与切片检验表"
    t3_rows = [
        [[("检验切片", {"bold": True})], [("样本量", {"bold": True})], [("胜率上限", {"bold": True})], [("断板跌停率", {"bold": True})], [("证伪裁决", {"bold": True})]],
        [[("二板缩量一字次日接力", {})], [("84笔", {})], [("28.6%", {})], [("42.5%", {})], [("缩量加速必死淘汰", {})]],
        [[("二板大换手次日弱转强", {})], [("92笔", {})], [("44.6%", {})], [("36.8%", {})], [("换手分歧消耗过大", {})]],
        [[("同题材三板顶一字压制", {})], [("45笔", {})], [("33.3%", {})], [("48.9%", {})], [("身位落后跟风炮灰", {})]],
        [[("最优108分高严档", {})], [("69笔", {})], [("47.8%", {})], [("34.8%", {})], [("胜率封顶不过半淘汰", {})]]
    ]
    validate_table(t3_rows, doc_name)
    tables.append((t3_title, t3_rows))

    return {
        "title": "二进三",
        "doc_id": "Y2Acd0VpNoZopYxvsotcTwCrnqe",
        "node_token": "WrlywVBEOicuVfk15yEcsmfenUg",
        "blocks": blocks,
        "img_path": None,
        "tables": tables
    }

if __name__ == "__main__":
    d = build_2to3_blocks()
    print("二进三证伪主文档校验成功，正文块数:", len(d["blocks"]), "表格数:", len(d["tables"]))
