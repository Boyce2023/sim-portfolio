# -*- coding: utf-8 -*-
"""子文档10：20261123 V19.1全量红队物理真账校准报告"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub10_redteam_v191_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "结论：V19.1 全量红队物理真账校准非常有用，清除了不可成交与除权错算隐患。",
            background_color=3,
        ),
        make_text_run(
            "五大单策略与合体 228 笔全部通过零跌停强卖、零除权差与零误套异动校验。",
            background_color=3,
        ),
        make_text_run("三进四 V4.1 顺延 12 笔跌停。单仓 616.18 倍，封顶 63.87 倍。"),
        make_text_run("高标 V5.1 回归 42 笔真口径并修 11 处偏差，单仓升至 14.75 倍。"),
        make_text_run("二进三 V2.1 清理错挂版本并修 2 笔除权，95 笔升至 404.71 倍。"),
        make_text_run("一进二修 2 笔后 332.72 倍。撬板 16 笔零违规维持 2.44 倍。"),
        make_text_run("合体校准后 228 笔，封顶 187.47 倍。2026 年封顶 21.10 倍。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("全部真账对齐原始日线与 5 分钟线复核，同期沪深300 五年为 -18.49%。"),
        make_text_run("近三年沪深300 为 +10.33%。2026 年至 11 月中旬为 -14.04%。"),
        make_text_run("全量账本零当日买卖、零仓位重叠、零一字涨停买与零一字跌停卖。"),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("五大策略与合体物理校准明细", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run("三进四 V4.1：顺延 12 笔收盘封死跌停至可卖日开盘。", bold=True),
        make_text_run("其中漳州发展、鼎信通讯与中毅达遇次日一字跌停再顺延 1 天。", background_color=3),
        make_text_run("入选 95 笔集合零变化，千红制药放量未封死不作顺延。"),
        make_text_run("102 分 S 档顺延 2 笔后 31 笔为 15.95 倍。胜率 61.29%，盈亏比 3.50。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("高标首阴 V5.1：回归真规则 42 笔序列并修复 11 处偏差。", bold=True),
        make_text_run("修正 10 笔买入日未封涨停却误套 93% 异动止盈单的程序错误。", background_color=3),
        make_text_run("并将蓝焰控股收盘跌停顺延至次日开盘卖出（-7.86%），不设连亏熔断。"),
        make_text_run("五年单仓与等权均为 14.75 倍，胜率 71.43%，近三年 8.78 倍。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("二进三 V2.1：归位现役真版并修正 2 笔跨除权日错算。", bold=True),
        make_text_run("将错挂在目录中的已证伪版本移入历史归档，以 95 笔真版归位。", background_color=3),
        make_text_run("名臣健康除权实为涨停晋级并于次日收盘卖出，真实收益 +12.41%。"),
        make_text_run("北方股份补足复权因子后真实收益 -4.40%，单仓跃升至 404.71 倍。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    o4 = [
        make_text_run("一进二 V19 与超跌撬板 V2.1：微调 2 笔并确认撬板零违规。", bold=True),
        make_text_run("神剑股份收盘跌停顺延次日开盘为 +59.10%，宏川智慧修除权为 -9.81%。", background_color=3),
        make_text_run("一进二 97 笔单仓 332.72 倍。撬板 16 笔零违规维持 2.44 倍。"),
    ]
    blocks.append(make_ordered_block(o4, seq="auto"))

    o5 = [
        make_text_run("五策略合体 V19.1：按 1 至 5 顺位重建 228 笔真账。", bold=True),
        make_text_run("漳州发展顺延阻塞和顺石油（-4.62%），释放槽位接入山东玻纤（+28.99%）。", background_color=3),
        make_text_run("笔数 229 降至 228 笔。封顶 187.47 倍，千万单利 21.52 倍。"),
    ]
    blocks.append(make_ordered_block(o5, seq="auto"))

    p4_head = [
        make_text_run("生产代码一致性红队预警与修复清单", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("五策略整数打分卡与核心门槛均与研发真源及总纲 100% 一致。"),
        make_text_run("26Q4 专供状态文件已更新为 5 策略洁净参数并补齐撬板条目。", background_color=3),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("实盘生产链查出 5 项高危待修问题：26Q4 程序漏接撬板与日报改顺位。"),
        make_text_run("同花顺开板空值错写为 0 误杀三板，部分模块缺行情日期校验且未硬拦单仓。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("另同步证伪暴跌妖股次日弱转强假说：171 组仅 2.3% 三期全正，禁上实盘。"),
    ]
    blocks.append(make_bullet_block(b3))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：V19.1 校准前后全五年核心指标对比表"
    t1_rows = [
        [[("策略版本", {"bold": True})], [("校准前(笔/胜/盈亏/单仓)", {"bold": True})], [("校准后(笔/胜/盈亏/单仓)", {"bold": True})], [("封顶 / 回撤 / 超额", {"bold": True})]],
        [[("三进四 V4.1", {"bold": True})], [("95 / 68.4% / 2.19 / 2319x", {})], [("95 / 65.3% / 1.95 / 616.18x", {"bold": True})], [("63.87x / 37.00% / +61537点", {"bold": True})]],
        [[("高标首阴 V5.1", {"bold": True})], [("42 / 71.4% / 3.18 / 13.41x", {})], [("42 / 71.4% / 2.83 / 14.75x", {"bold": True})], [("14.13x / 15.94% / +1393点", {"bold": True})]],
        [[("超跌撬板 V2.1", {})], [("16 / 87.5% / 0.75 / 2.44x", {})], [("16 / 87.5% / 0.75 / 2.44x", {})], [("2.44x / 19.15% / +162点", {})]],
        [[("二进三 V2.1", {"bold": True})], [("95 / 52.6% / 4.37 / 313.87x", {})], [("95 / 53.7% / 4.57 / 404.71x", {"bold": True})], [("54.06x / 28.68% / +40389点", {"bold": True})]],
        [[("一进二 V19", {})], [("97 / 68.0% / 2.87 / 338.37x", {})], [("97 / 68.0% / 2.88 / 332.72x", {})], [("54.17x / 15.97% / +33190点", {})]],
        [[("五策略合体", {"bold": True})], [("229 / 65.1% / 3.19 / 3068万x", {})], [("228 / 64.9% / 2.90 / 1440万x", {"bold": True})], [("187.47x / 40.12% / 单利21.5x", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：洁净真账近三年、2026 年与滑点去极值压测表"
    t2_rows = [
        [[("策略名称", {"bold": True})], [("近三年(笔/胜率/净值)", {"bold": True})], [("2026年(笔/胜率/净值)", {"bold": True})], [("去前5 / +80bps 压测", {"bold": True})]],
        [[("三进四 V4.1", {})], [("58 / 70.69% / 200.23x", {})], [("18 / 66.67% / 3.74x", {})], [("36.81x / 289.04x", {})]],
        [[("高标首阴 V5.1", {})], [("26 / 76.92% / 8.78x", {})], [("14 / 71.43% / 2.92x", {})], [("5.84x / 10.55x", {})]],
        [[("超跌撬板 V2.1", {})], [("8 / 87.50% / 1.49x", {})], [("2 / 100.0% / 1.09x", {})], [("1.16x / 2.15x", {})]],
        [[("二进三 V2.1", {})], [("52 / 48.08% / 15.23x", {})], [("14 / 64.29% / 4.64x", {})], [("44.01x / 189.84x", {})]],
        [[("一进二 V19", {})], [("51 / 68.63% / 62.37x", {})], [("21 / 80.95% / 3.15x", {})], [("24.58x / 153.60x", {})]],
        [[("五策略合体", {"bold": True})], [("127 / 64.57% / 30969x", {"bold": True})], [("43 / 67.44% / 27.29x", {"bold": True})], [("39.3万x / 234.1万x", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：红队零违规断言与 26Q4 贝叶斯最新参数表"
    t3_rows = [
        [[("洁净账本与顺位", {"bold": True})], [("违规数(8项断言)", {"bold": True})], [("训练期标准差", {"bold": True})], [("最新融合夏普底分", {"bold": True})]],
        [[("三进四 V4.1 (95笔)", {})], [("全部 0 违规", {})], [("7.26", {})], [("0.5828 (近10笔 0.8146)", {})]],
        [[("高标首阴 V5.1 (42笔)", {})], [("全部 0 违规", {})], [("14.23", {})], [("0.8723 (近10笔 1.0633)", {})]],
        [[("超跌撬板 V2.1 (16笔)", {})], [("全部 0 违规", {})], [("15.41", {})], [("0.5073 (近10笔 0.4049)", {})]],
        [[("二进三 V2.1 (95笔)", {})], [("全部 0 违规", {})], [("4.51", {})], [("0.4321 (近10笔 0.4806)", {})]],
        [[("一进二 V19 (97笔)", {})], [("全部 0 违规", {})], [("25.88", {})], [("0.6046 (近10笔 0.8070)", {})]],
        [[("合体 V19.1 (228笔)", {"bold": True})], [("全部 0 违规", {"bold": True})], [("HLZ t = 6.62", {"bold": True})], [("DSR = 1.0000", {"bold": True})]],
    ]
    tables.append((t3_title, t3_rows))

    return {
        "title": "20261123 V19.1全量红队物理真账校准报告",
        "parent_node_token": "Jxarwc3wliQZCakXO1xccPmrnCc",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }
