#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Update Feishu doc Oq9wwF3tFiR6KukhacBcr5tynUc with complete Daily + Gap + Weekly + 20D regressions across 5 A-share indices."""
import os, sys, json, time, fcntl
OUT = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/us_to_ashare_reg_20261123"
FS = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
sys.path.insert(0, FS)
import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from build_master_docs import make_text_run, make_para_block, make_bullet_block, make_blank_line

PARENT = "Jxarwc3wliQZCakXO1xccPmrnCc"
TITLE = "20261123 美股对A股五年一年四个月传导回归实证"


def main():
    d = json.load(open(f"{OUT}/us_to_ashare_full_horizons.json", encoding="utf-8"))
    blocks = [
        make_para_block([
            make_text_run("结论：单日看美股解释度低，但按周度与20日波段看，美股对A股影响极高。", background_color=3),
            make_text_run("五大指数全在近一年大幅转向高度联动，但近四月出现明显分化。", background_color=3),
            make_text_run("A股白天实时交易美股期货，导致单日错位回归把一半共振切碎。"),
        ]),
        make_para_block([make_text_run("一、五大A股指数逐一拆解结论", bold=True)]),
        make_bullet_block([
            make_text_run("创业板指：全市场跟纳指绑得最死，且越走越紧。", background_color=3),
            make_text_run("纳指20日解释度由 12.5% 飙至近一年 42.6%、近四月 48.5%。"),
            make_text_run("近四月波段弹性达 +1.30，等于纳指动 1 点、创业板放大动 1.3 点。"),
        ]),
        make_bullet_block([
            make_text_run("中证500：开盘最怕美股，近四月跳空解释度飙至全场最高 42.4%。", background_color=3),
            make_text_run("周度解释度由五年 5.1% 升至近四月 30.4%，20日波段达 31.2%。"),
            make_text_run("中证500 盘中几乎不反拉（盘中弹性仅 -0.06），跟外盘最老实。"),
        ]),
        make_bullet_block([
            make_text_run("上证指数：近四月周度联动意外飙至全场第一（44.9%）。", background_color=3),
            make_text_run("但上证弹性极小（周度弹性仅 +0.29），只跟方向、波动被权重压缩。"),
        ]),
        make_bullet_block([
            make_text_run("沪深300：近一年波段解释度高达 42.9%，近四月被国家队硬托脱敏。", background_color=3),
            make_text_run("近四月纳指波段解释度回落至 18.9%，标普波段解释度更降至 9.4%。"),
        ]),
        make_bullet_block([
            make_text_run("科创50：开盘吓得最狠，但盘中反拉也最凶，近四月走出国产替代独立线。", background_color=3),
            make_text_run("近四月纳指开盘弹性高达 +0.73，但盘中反向拉回 -0.24 吐回三分之一。"),
            make_text_run("近四月纳指波段解释度从 32.4% 降至 16.5%，标普更降至 2.3%。"),
        ]),
        make_para_block([make_text_run("二、套利实盘核验与边界（含588080真实ETF折价）", bold=True)]),
        make_bullet_block([
            make_text_run("科创50美股大跌接低开次日开盘卖，5年47笔指数均 +1.31%。", background_color=3),
            make_text_run("改用实盘 588080 ETF 重核，竞价折价 0.32 点至 +0.99%。", background_color=3),
            make_text_run("剔除前 2 大极值指数均值仍达 +1.05%，5年最大回撤仅 -4.45%。"),
        ]),
        make_blank_line(), make_blank_line(), make_blank_line(),
    ]

    def make_tbl(us_nm):
        rows = [[
            [("A股指数与窗口", {"bold": True})],
            [("单日收盘 / 跳空R方", {"bold": True})],
            [("周度R方 / 弹性", {"bold": True})],
            [("20日波段R方 / 弹性", {"bold": True})],
        ]]
        for a_nm in ("创业板指", "中证500", "上证指数", "沪深300", "科创50"):
            for w in ("5年", "1年", "4个月"):
                x = d[a_nm][us_nm][w]
                rows.append([
                    [(f"{a_nm} ({w})", {"bold": w == "4个月"})],
                    [(f"{x['cc']['r2']:.1f}% / {x['gap']['r2']:.1f}%", {})],
                    [(f"{x['wk']['r2']:.1f}% / {x['wk']['beta']:+.2f}", {"bold": x['wk']['r2'] >= 30})],
                    [(f"{x['d20']['r2']:.1f}% / {x['d20']['beta']:+.2f}", {"bold": x['d20']['r2'] >= 30})],
                ])
        return rows

    arb = json.load(open(f"{OUT}/us_to_ashare_arb_test.json", encoding="utf-8"))
    arb_rows = [[
        [("标的与条件(5年 / 近1年)", {"bold": True})],
        [("触发次数", {"bold": True})],
        [("T+0今开至今收(胜率)", {"bold": True})],
        [("T+1次日开盘卖(胜率)", {"bold": True})],
    ]]
    for nm in ("科创50", "中证500", "创业板指", "沪深300"):
        for w in ("5年", "1年"):
            s1 = arb[nm][w]["buy_dip_15"]
            arb_rows.append([
                [(f"{nm} 美<=-1.5%低开 ({w})", {"bold": nm == "科创50"})],
                [(f"{s1['n']} 次", {})],
                [(f"{s1['t0_mean']:+.2f}% ({s1['t0_win']:.1f}%)", {"bold": nm == "科创50"})],
                [(f"{s1['t1o_mean']:+.2f}% ({s1['t1o_win']:.1f}%)", {"bold": s1['t1o_mean'] >= 1.0})],
            ])
        s2 = arb[nm]["5年"]["buy_dip_20"]
        arb_rows.append([
            [(f"{nm} 严档<=-2%深低开(5年)", {"bold": nm == "科创50"})],
            [(f"{s2['n']} 次", {})],
            [(f"{s2['t0_mean']:+.2f}% ({s2['t0_win']:.1f}%)", {})],
            [(f"{s2['t1o_mean']:+.2f}% ({s2['t1o_win']:.1f}%)", {"bold": s2['t1o_mean'] >= 1.2})],
        ])

    arb_rows.append([
        [("实盘ETF 588080核验(5年)", {"bold": True})],
        [("47 次", {"bold": True})],
        [("+0.71% (折价0.12点)", {"bold": True})],
        [("+0.99% (胜63.8%/回撤 -4.45%)", {"bold": True})],
    ])
    tables = [
        ("附录表一：纳指对五大A股指数全周期传导汇总表（单日 / 跳空 / 周度 / 20日波段）", make_tbl("纳指")),
        ("附录表二：标普500对五大A股指数全周期传导汇总表（单日 / 跳空 / 周度 / 20日波段）", make_tbl("标普500")),
        ("附录表三：美股大跌加A股低开套利实测表（T+0 vs 真实ETF T+1）", arb_rows),
    ]
    payload = {"title": TITLE, "parent_node_token": PARENT, "blocks": blocks, "img_path": None, "tables": tables}
    longs = s9.audit_doc_strict_v191(payload, require_img=False)
    if longs:
        raise ValueError(f"Long sentences: {longs}")

    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        doc_id, node_tok = s9.find_or_create_child_node(PARENT, TITLE)
        done, fail = s6.write_document_payload(doc_id, payload["blocks"], payload["tables"], None)
        if fail > 0:
            raise RuntimeError(f"Write fail={fail}")
        time.sleep(1.2)
        s9.verify_document_v191(doc_id, TITLE, expected_tables_count=3, has_img=False)
        print(f"FEISHU_UPDATED https://my.feishu.cn/wiki/{node_tok}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
