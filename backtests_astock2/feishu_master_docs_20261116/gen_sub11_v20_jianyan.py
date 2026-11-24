# -*- coding: utf-8 -*-
"""专题子文档11（有效回测目录）：20261124 V20.0六策略双套件检验与精细分档排序报告"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub11_v20_jianyan_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "本检验直接回答六大策略并表及跨板防抽血究竟有没有用：极有用。",
            background_color=3,
        ),
        make_text_run("合体 278 笔单仓净值冲上 6913.41 万倍。OOS（样本外）飙至 5648.47 倍。"),
        make_text_run("日级年化 Sharpe 达 4.75，Calmar（卡尔玛）75.65。远胜原五策略 1645 万倍。"),
        make_text_run("同期沪深300 回报 -18.49%。合体在 1212 个交易日内做到全期稳健超额。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run(
            "结论一：按买点时序分三梯队，合体比盲目混排多赚 2294 万倍。",
            background_color=3,
        ),
        make_text_run("只有三进四满 102 分与高标满 96 分两路盘中 S 档单允许强抢槽位。"),
        make_text_run("其余盘中 A 档突破单必须无条件让位给 09:25 确定直买，避免两头踩空。"),
        make_text_run("20cm A 档 76 至 81 分仅做观察，否则合体夏普会被拉低至 4.44。"),
    ]
    blocks.append(make_para_block(p2))

    p3 = [
        make_text_run(
            "结论二：60 次跨板交互横扫淘汰 58 项噪音，只留 20cm 低开压一进二。",
            background_color=3,
        ),
        make_text_run("当昨 20cm 涨停少于 16 家且清洁首板次日低开低于 -3.0% 达 2 家。"),
        make_text_run("一进二 V20 总分统一扣 25 分。五年胜率升至 71.74%，回撤压至 13.31%。"),
        make_text_run("其 OOS（样本外）由 39.3 倍升至 63.80 倍。PBO 压低到 1.43%。"),
    ]
    blocks.append(make_para_block(p3))

    p4_head = [
        make_text_run("实盘五大死穴与本地数据缺口清点", bold=True, underline=True),
        make_text_run("（不藏瑕、逐项标明边界）："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("缺口一，1 分钟 K 线本地零覆盖。", bold=True),
        make_text_run("缺口二，20cm 五分钟线 2023 年 8 月后全缺。实际仅覆盖 59 笔。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("缺口三，二进三高开买点无直接 5 分钟验证，仅依赖 09:25 竞价确定成交。", bold=True),
        make_text_run("缺口四，公告库约 6% 仅存日期，且前十大锁仓表存 6 条 1900 年哨兵行。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("缺口五，时间敏感度极端陡峭。", bold=True),
        make_text_run("延迟 5 分钟合体有 58 笔买不到涨停。子样本由 10.9 万倍跌至 180 倍。", background_color=3),
        make_text_run("三进四延迟 5 分钟失去 20 笔封板。单策略净值由 616 倍坍缩至 2.26 倍。"),
    ]
    blocks.append(make_bullet_block(b3))

    p5 = [
        make_text_run(
            "结论三：六条策略在合体中的留一乘数全部大于 1.20 倍，无一拖油瓶。",
            background_color=3,
        ),
        make_text_run("二进三贡献 51.58 倍，一进二 28.30 倍。三进四 5.64 倍，20cm 5.23 倍。"),
        make_text_run("一万次区块自助抽样亏损概率为 0.0%，单边保本交易成本 325.2 bps。"),
        make_text_run("6 策略日均等权组合达到 137.30 倍。最大回撤 10.80%，夏普高达 5.29。"),
    ]
    blocks.append(make_para_block(p5))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：V20.0 六策略三梯队顺位多方案排序实证对比表"
    t1_rows = [
        [[("方案名称", {"bold": True})], [("五年笔数与胜率", {"bold": True})], [("单仓净值 / 去前五", {"bold": True})], [("OOS（样本外）/ 2026年", {"bold": True})]],
        [[("原五策略基线(无20cm)", {})], [("226笔 / 65.49%", {})], [("1645万x / 44.9万x", {})], [("3699.8x / 27.87x", {})]],
        [[("粗糙并表未分梯队", {})], [("278笔 / 64.39%", {})], [("4619万x / 126.1万x", {})], [("5488.9x / 34.03x", {})]],
        [[("09:25 确定全压盘中", {})], [("278笔 / 65.11%", {})], [("6091万x / 166.3万x", {})], [("5028.4x / 24.73x", {})]],
        [[("V20.0 S档强占位终版", {"bold": True})], [("278笔 / 65.11%", {"bold": True})], [("6913万x / 188.7万x", {"bold": True})], [("5648.5x / 27.78x", {"bold": True})]],
        [[("接入 20cm A 档拖累版", {})], [("314笔 / 62.74%", {})], [("2655万x / 95.9万x", {})], [("4185.8x / 37.12x", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：6×6 跨板交互横扫淘汰清单与唯一入选规则"
    t2_rows = [
        [[("信号来源至目标策略", {"bold": True})], [("时滞维度", {"bold": True})], [("样本内 / OOS（样本外）", {"bold": True})], [("裁决结果与理由", {"bold": True})]],
        [[("20cm清洁低开压一进二", {"bold": True})], [("同日 09:25", {"bold": True})], [("-7.01 / -15.08 点", {"bold": True})], [("唯一双周期显著，升级扣25", {"bold": True})]],
        [[("20cm低开滞后压一进二", {})], [("前日滞后", {})], [("-3.67 / -7.16 点", {})], [("同步扣分不重复叠加", {})]],
        [[("三进四信号压 20cm A76", {})], [("同日信号", {})], [("-3.53 / -4.62 点", {})], [("p 值未达标，淘汰剔除", {})]],
        [[("高标首阴压二进三或20cm", {})], [("前日滞后", {})], [("-5.67 / -3.18 点", {})], [("样本外失去显著性，淘汰", {})]],
        [[("10cm 09:25 信号反压20cm", {})], [("多策略联合", {})], [("双周期全负拖累", {})], [("全军淘汰，维持20cm独立", {})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：合体 V20.0 机构七支柱检验与留一贡献全表"
    t3_rows = [
        [[("机构检验支柱", {"bold": True})], [("关键指标名称", {"bold": True})], [("合体 V20.0 实测值", {"bold": True})], [("安全边际判断", {"bold": True})]],
        [[("支柱一 Alpha", {})], [("4F可交易 / 5F O2C", {})], [("+419.6%(t9.0) / +450.4%", {})], [("剥离风格因子显著超额", {})]],
        [[("支柱二 容量与冲击", {})], [("10%十分位 / 半CAGR", {})], [("2532万 / 3065万(Y0.5)", {})], [("两千五百万以内几乎零冲击", {})]],
        [[("支柱三 四季全天候", {})], [("1万次自助 / 25至26退潮", {})], [("亏损0% / 退潮+6336%", {})], [("大盘走熊仍独立大涨", {})]],
        [[("支柱四与五 摩擦统计", {})], [("单边保本 / WRC / 凯利", {})], [("325bps / p=0 / 半凯利194%", {})], [("成本安全垫达 28 倍", {})]],
        [[("支柱六与七 纯净留一", {})], [("五折交叉 / 6x6相关", {})], [("5全正(均值4.79) / 0.0247", {})], [("各策略留一贡献全大于1.2x", {})]],
    ]
    tables.append((t3_title, t3_rows))

    return {
        "title": "20261124 V20.0六策略双套件检验与精细分档排序报告",
        "parent_node_token": "OPKUwAqCDibLfRkRE87cd2aCnVc",
        "doc_id": None,
        "node_token": None,
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
