#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD021 Auto-Publish -> Feishu Wiki (Claude/Argon 因子挖掘、回测)."""
import json, os, sys, time, fcntl, argparse

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/commodities_leadlag_10y_20261123"
FS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
sys.path.insert(0, FS_DIR)
import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from build_master_docs import make_text_run as TR, make_para_block as P, make_bullet_block as B, make_ordered_block as O, make_blank_line as BL

PARENT_NODE = "Jxarwc3wliQZCakXO1xccPmrnCc"
TITLE = "20261123 六大商品股期联动提前性与左右侧策略十年实证回测"

def row(vals, bold=False):
    st = {"bold": True} if bold else {}
    return [[(str(v), st)] for v in vals]

def build_payload():
    blocks = [
        P([
            TR("结论：股票并非普遍领先商品，六大商品呈两极分化。", background_color=3),
            TR("生猪与碳酸锂股真领先商品，左侧布局完胜右侧追涨。", background_color=3),
            TR("金铜油煤全部 0 天同步共振，不存在股先商品数月神话。", background_color=3),
            TR("回测覆盖 2016.01 至 2026.11 共 2643 个交易日。"),
            TR("全量严守次日开盘成交与双边 0.30% 真实交易成本。"),
        ]),
        P([TR("一、第一性原理拆解：为何仅生猪与碳酸锂领先", bold=True)]),
        B([
            TR("股期是否提前，只取决于产能出清是否存在刚性时滞。", background_color=3),
            TR("生猪从能繁母猪到出栏需 10 至 14 月，股市提前博弈去化。"),
            TR("碳酸锂云母矿与澳矿停产有出清周期，股市提前交易成本底。"),
            TR("金铜油煤全球高频定价，期现与股票同一天同步消化宏观信息。", background_color=3),
            TR("美股同行 NEM、FCX、XOM 同样 0 天同步，排除市场差异。"),
        ]),
        P([TR("二、六大品种领先滞后与左右侧策略实证裁决", bold=True)]),
        O([
            TR("生猪：股票大幅领先现货 +136 天，右侧追猪价必被套。", bold=True),
            TR("十年现货轨大顶中位领先 +37 天，牧原领先 +45 天。", background_color=3),
            TR("纯左侧低谷买股 A2 十年年化 +14.03%，TEI 达 63.7。", background_color=3),
            TR("跑赢沪深300 年化 +13.49%，跑赢买入持有 +2.86%。"),
            TR("右侧等猪价走强追股 B 十年年化 -0.70%，近五年 -6.96%。"),
        ], seq="1"),
        O([
            TR("碳酸锂：股票领先 LC0 达 +37 天，严禁盲接飞刀。", bold=True),
            TR("广期所 LC0 实盘 3.3 年，大底中位股票领先 +32 天。", background_color=3),
            TR("赣锋领先 +51 天，天齐 +36 天，美股 ALB 领先 +20 天。"),
            TR("左侧低谷加股票站上 60 日线 A 年化 +19.03%，TEI 69.3。", background_color=3),
            TR("同期纯盲抄底 A2 年化 -6.48%，买入持有 -10.21%。"),
            TR("说明 2016 至 2023 无公开日频现货，不编造前置历史。"),
        ], seq="auto"),
        O([
            TR("铜：股期 0 天同步，外盘深调加股票转强赔率最高。", bold=True),
            TR("沪铜与外盘铜 60 日相关峰均在 0 天，紫金相关度 0.58。"),
            TR("外盘 HG 驱动左侧 A 仅用 17.7% 仓位年化 +12.95%。", background_color=3),
            TR("最大回撤压至 -21.7%，盈亏比 10.1，TEI 达 67.7。", background_color=3),
            TR("近三年左侧 A 年化 +33.83%，完胜右侧 B 的 -0.45%。"),
        ], seq="auto"),
        O([
            TR("石油：股期 0 天同步，右侧追油价极易吃脉冲耳光。", bold=True),
            TR("布油右侧 B 十年年化 -2.54%，国内 SC0 右侧 B 为 -1.76%。", background_color=3),
            TR("国内 SC0 左侧 A 八年年化 +10.78%，回撤压至 -29.5%。", background_color=3),
            TR("相比买入持有 +10.84% 与 -46.0% 回撤，少扛三分之一回撤。"),
        ], seq="auto"),
        O([
            TR("黄金：股期 0 天同步且十年长牛，左侧抄底严重踏空。", bold=True),
            TR("黄金等权与沪金相关度 0.72，大底大顶误差在 3 天内。"),
            TR("长牛导致左侧 A 十年仓位仅 2.2%，年化 -1.56%。"),
            TR("沪金右侧 B 年化 +9.06%，山东黄金右侧 +8.31% 赢持有。", background_color=3),
            TR("长期主线直接持有黄金等权十年年化 +12.58%，TEI 59.5。"),
        ], seq="auto"),
        O([
            TR("煤炭：双焦 0 天同步，右侧追焦煤完胜左侧抄底。", bold=True),
            TR("双焦左侧 A 十年年化 -6.64%，山西焦煤与潞安均负收益。", background_color=3),
            TR("右侧等焦煤走强 B 十年年化 +10.45%，TEI 达 61.6。", background_color=3),
            TR("近五年煤炭右侧 B 年化 +10.30%，TEI 升至 67.8。"),
            TR("中国神华自带红利长牛，买入持有十年年化 +20.29%，TEI 70.0。", background_color=3),
        ], seq="auto"),
        P([TR("三、实战口诀与口径防伪边界", bold=True)]),
        B([
            TR("产能长周期品种看左侧：生猪低谷拿稳，碳酸锂等转强买。", background_color=3),
            TR("宽幅震荡品种反追高：铜与油等商品深调且股转强再出手。", background_color=3),
            TR("强趋势长牛品种顺大势：黄金与煤炭只做右侧趋势或拿龙头。", background_color=3),
            TR("十年沪深300 基准年化 +0.53%，最大回撤 -45.60%。"),
            TR("WTI 原油 2020.04.20 负油价与盐湖 2021 复牌已隔离。"),
        ]),
        BL(), BL(), BL(),
    ]
    t1 = [
        row(["品种与窗口", "60日相关峰(r)", "大底/大顶领先", "美股对照峰"], bold=True),
        row(["生猪(10Y现货)", "+136d (+0.41)", "-49d / +37d", "国内独立周期"]),
        row(["碳酸锂(3.3Y LC0)", "+37d (+0.69)", "+32d / +2d", "ALB +20d (+0.85)"]),
        row(["铜(10Y CU0/HG)", "0d (+0.51)", "-16d / -27d", "FCX 0d (+0.70)"]),
        row(["石油(SC0/BZ)", "0d (+0.55)", "+2d / +7d", "XOM 0d (+0.65)"]),
        row(["黄金(10Y AU0)", "0d (+0.72)", "+3d / +0.5d", "NEM 0d (+0.72)"]),
        row(["煤炭(10Y JM0)", "0d (+0.61)", "0d / -6d", "纽卡月频 +1月"]),
    ]
    t2 = [
        row(["品种(同窗对齐)", "左侧A/A2年化", "右侧B年化/MDD", "持有C / 最佳TEI"], bold=True),
        row(["生猪(10Y现货)", "+3.6% / +14.0%", "-0.7% / -55.6%", "+11.2% / A2(63.7)"]),
        row(["碳酸锂(LC0)", "+19.0% / -6.5%", "+1.7% / -29.9%", "-10.2% / A(69.3)"]),
        row(["铜(10Y HG)", "+13.0% / +8.7%", "+8.3% / -51.0%", "+17.4% / A(67.7)"]),
        row(["石油(8Y SC0)", "+10.8% / +7.5%", "-1.8% / -38.9%", "+10.8% / A(61.5)"]),
        row(["石油(10Y BZ)", "+2.6% / +3.6%", "-2.5% / -52.6%", "+7.3% / A2(57.9)"]),
        row(["黄金(10Y AU0)", "-1.6% / -0.6%", "+9.1% / -61.3%", "+12.6% / C(59.5)"]),
        row(["煤炭(10Y JM0)", "-6.6% / +5.8%", "+10.5% / -32.6%", "+14.4% / 神华(70.0)"]),
    ]
    t3 = [
        row(["品种与最佳策略", "全窗年化/超300", "近5年年化/TEI", "近3年年化/TEI"], bold=True),
        row(["生猪 A2纯左侧", "+14.0% / +13.5%", "+4.0% / 55.8", "+10.6% / 50.9"]),
        row(["碳酸锂 A左+强", "+19.0% / +18.0%", "上市满3.3年", "+19.0% / 69.3"]),
        row(["铜 HG 策略A左+强", "+13.0% / +12.4%", "+21.7% / 76.6", "+33.8% / 78.0"]),
        row(["煤炭 JM0 策略B右侧", "+10.5% / +9.9%", "+10.3% / 67.8", "+4.3% / 50.9"]),
        row(["中国神华 持有C", "+20.3% / +19.8%", "+30.4% / 77.4", "+26.3% / 69.3"]),
        row(["黄金 AU0 策略B右侧", "+9.1% / +8.5%", "+1.4% / 54.8", "+12.9% / 57.1"]),
    ]
    return {
        "title": TITLE, "parent_node_token": PARENT_NODE, "blocks": blocks,
        "img_path": f"{OUT_DIR}/chart1_leadlag_6commodities.png",
        "img_path2": f"{OUT_DIR}/chart2_strategy_ab_vs_bh.png",
        "tables": [
            ("附录表一：六大商品股期领先滞后与拐点实证总表", t1),
            ("附录表二：严格 PIT 左右侧择时与买入持有收益对比表（扣双边 0.30% 费）", t2),
            ("附录表三：核心胜出策略十年、近五年与近三年稳定性核验表", t3),
        ],
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    d = build_payload()
    longs = s9.audit_doc_strict_v191(d, require_img=True)
    if longs:
        for x in longs: print("LONG:", x)
        raise ValueError("存在超40字长句或违规")
    print("[PASS] Local audit_doc_strict_v191 passed with 0 errors!")
    if args.dry_run: return
    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        doc_id, node_tok = s9.find_or_create_child_node(PARENT_NODE, TITLE)
        if doc_id in s6.PROTECTED_DOCS: raise RuntimeError(f"Protected: {doc_id}")
        done, fail = s6.write_document_payload(doc_id, d["blocks"], d["tables"], d["img_path"])
        if fail > 0: raise RuntimeError(f"Write failed: {fail}")
        # Insert Chart 2 + 3 trailing blank lines cleanly
        s6.insert_image_block(doc_id, d["img_path2"])
        s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
               {"children": [BL(), BL(), BL()], "index": -1}, "POST")
        time.sleep(1.5)
        v = s9.verify_document_v191(doc_id, TITLE, expected_tables_count=len(d["tables"]), has_img=True)
        url = f"https://my.feishu.cn/wiki/{node_tok}"
        mf = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        mf.setdefault("nodes", {})["commodities_leadlag_10y"] = {
            "title": TITLE, "node_token": node_tok, "obj_token": doc_id,
            "parent_node_token": PARENT_NODE, "wiki_url": url,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        json.dump(mf, open(s6.MANIFEST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"[SUCCESS] URL={url} | blocks={v['blocks_count']} | tables={v['tables_count']} | images={v['images_count']}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN); lock_fd.close()

if __name__ == "__main__":
    main()
