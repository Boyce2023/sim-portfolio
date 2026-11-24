# -*- coding: utf-8 -*-
"""20cm子文档6：20261124 20cm七大机构支柱检验与10cm交叉信号全证伪"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub20cm_6_pillars_10cm_veto_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "直接结论：20cm过七大机构检验有用，拿10cm与冷区补丁改它全没用。",
            background_color=3,
        ),
        make_text_run("本文沉淀 20cm 独立于主板五策略的七项机构级深检全部实证。"),
        make_text_run("同时记录 10 套 10cm 盘前信号与二十日红盘补丁的证伪全过程。"),
        make_text_run("所有检验基于 1426 个交易日并严格执行无前视偏差对齐。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("一、20cm 单独通过七大机构检验全实录（聚焦 S82）", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p2_head))

    o1 = [
        make_text_run("支柱一与二：真实超额、首板配对与容量延迟实测。", bold=True),
        make_text_run(
            "S82 5F O2C年化Alpha +96.92%，4F可交易+120.22%。",
            background_color=3,
        ),
        make_text_run("配对同日同档20cm首板对照，S82单笔多赚+1.91%，p 0.042。"),
        make_text_run("10% 成交额守卫容量 1797 万，冲击半 CAGR 容量为 1500 万。"),
        make_text_run("需诚实标明 2023 年 8 月后缺 5 分钟线，已覆 59 笔延迟无踏空。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("支柱三与四：极端韧性、万次抽样与高保本安全垫。", bold=True),
        make_text_run(
            "1 万次区块自助抽样亏损概率 0.0%，5% 最坏情景仍高达 51.31 倍。",
            background_color=3,
        ),
        make_text_run("22年封控6笔全胜赚+80.9%，退潮30笔赚+29.98%。"),
        make_text_run("单边几何保本成本166.7bps，11.1倍安全垫，池子IC 0.239。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("支柱五至七：五折交叉、大盘暴跌逆势与 CUSUM 红线。", bold=True),
        make_text_run(
            "S82与10cm相关仅0.015，沪深300最差日逆势赚+0.62%。",
            background_color=3,
        ),
        make_text_run("五折清洗交叉五折全正，均值夏普 2.18 高于全样本，游程随机。"),
        make_text_run("半凯利上限 203%，五年红黄线连亏 8 黄 9 红、累积和 124.7% 停机。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3_head = [
        make_text_run("二、十项 10cm 交叉信号与二十日冷区补丁证伪实录", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    b1 = [
        make_text_run("全部十套 10cm 09:25 交叉信号双向增减分全部淘汰。", bold=True),
        make_text_run(
            "把主板五策略盘前信号喂给 20cm，十套里面没有一套通过双期检验。",
            background_color=3,
        ),
        make_text_run("部分信号在样本内看似有效，一到 OOS（样本外）立刻翻负倒扣。"),
        make_text_run("只有 20cm 低开反向压制一进二成立，反向输入全部属于伪相关。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("近 20 日 20cm 红盘低于 40% 收紧补丁正式淘汰。", bold=True),
        make_text_run(
            "该补丁虽让 A76 的 OOS（样本外）提至 15.71 倍，但样本内倒退。",
            background_color=3,
        ),
        make_text_run("样本内由26.71倍降至25.16倍，局部PBO由1.43%翻倍。"),
        make_text_run("坚决锁死原版 V1.1 卖树，拒绝一切后验微调补丁进入实盘代码。"),
    ]
    blocks.append(make_bullet_block(b2))

    p4 = [
        make_text_run("最终结论："),
        make_text_run("20cm 是与主板几乎零相关、暴跌日也能赚钱的正交第六极。", background_color=3),
        make_text_run("保持 V1.1 纯净独立运行，严禁被 10cm 信号与二十日冷区补丁污染。"),
    ]
    blocks.append(make_para_block(p4))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：20cm V1.1 S82 七大机构检验明细表"
    t1_rows = [
        [[("机构检验支柱", {"bold": True})], [("核心测试项目", {"bold": True})], [("S82 实测值", {"bold": True})], [("结论与安全边际", {"bold": True})]],
        [[("支柱一 Alpha", {})], [("5F O2C / 4F可交易", {})], [("+96.9%(t4.4) / +120.2%", {})], [("匹配首板对照多赚 +1.91%", {})]],
        [[("支柱二 容量延迟", {})], [("10%十分位 / 半CAGR", {})], [("1797万 / 1500万", {})], [("23年8月后缺5分线覆59笔", {})]],
        [[("支柱三 极端韧性", {})], [("1万次抽样 / 退潮30笔", {})], [("亏损0% / 退潮+29.98%", {})], [("5%分位下界仍有 51.31 倍", {})]],
        [[("支柱四 成本特性", {})], [("单边保本 / 池子 IC", {})], [("166.7 bps / IC 0.239", {})], [("成本安全垫达 11.1 倍", {})]],
        [[("支柱五 统计独立", {})], [("BCa 95%置信 / 游程p", {})], [("[+2.29%,+5.09%] / p0.99", {})], [("半凯利 203%，WRC p=0", {})]],
        [[("支柱六 五折复权", {})], [("五折交叉 / 250万行核", {})], [("5全正(夏普2.18) / 0差", {})], [("最差折 1.34 倍，0前视", {})]],
        [[("支柱七 正交暴跌", {"bold": True})], [("5策略相关 / 最差一成日", {"bold": True})], [("均值0.015 / 逆势+0.62%", {"bold": True})], [("全期9黄10红 / 5年8黄9红", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：10cm 交叉信号与二十日红盘补丁证伪对比表"
    t2_rows = [
        [[("测试改造方案", {"bold": True})], [("样本内变化", {"bold": True})], [("OOS（样本外）变化", {"bold": True})], [("淘汰原因与裁决", {"bold": True})]],
        [[("三进四09:25信号喂20cm", {})], [("13笔净差 -0.99点", {})], [("19笔 -1.08点 / 26年-4.2", {})], [("p=0.55不显著，淘汰", {})]],
        [[("高标与二进三信号喂20cm", {})], [("样本内假正 +1.79点", {})], [("样本外反转 -2.94点", {})], [("样本内外正负号反转，淘汰", {})]],
        [[("撬板与全五汇信号喂20cm", {})], [("样本内假正 +3.65点", {})], [("样本外反转 -1.33点", {})], [("10套 0 双期同向，淘汰", {})]],
        [[("20日红盘<40%收紧补丁", {})], [("26.71x 降为 25.16x", {})], [("13.10x 升为 15.71x", {})], [("局部PBO翻倍恶化，淘汰", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261124 20cm七大机构支柱检验与10cm交叉信号全证伪",
        "parent_node_token": "Bm0AwmIg5if5vekhQmacamjdnIc",
        "doc_id": None,
        "node_token": None,
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
