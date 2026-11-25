#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Auto-publish 20261125 30d-200% abnormality Day30/31 48-factor & exit red-team falsification to Feishu 证伪回测与避坑墓碑."""
import fcntl, os, sys, time

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR_DIR)
import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from build_master_docs import make_text_run as R, make_para_block as P, make_bullet_block as B, make_blank_line as BL
from small_backtests_payloads_20261124 import build_hub_doc

I_NODE = "QiDewdTkJiquokkbbo6cWr3Fn6f"
I_DOC = "ZTaudjSqtoaj71xTPSLciMcdnLb"


def _c(txt, bold=False):
    return [(txt, {"bold": True} if bold else {})]


def main():
    doc = {
        "title": "20261125 卡30天200%异动第30与31天买点、48因子打分与卖点优化六年证伪",
        "blocks": [
            P([R("结论：卡住30天200%异动后在第30天尾买或第31天盲买全线大亏，48项因子打分与7套卖点优化共418组仍0过红队六关。", background_color=3),
               R("民间流传的出笼二波神话主要是双买点均封死一字买不到的幸存者偏差，实盘严禁以此立项。")]),
            P([R("一、盲买全线大亏：第30天尾盘提前埋伏反而更惨", bold=True)]),
            B([R("第31天盲买拿越久亏越惨：主板真控盘73笔持5天均亏 -4.51%、持10天均亏 -6.77%，五年单仓亏 -71.3% 至 -84.9%。")]),
            B([R("第30天尾盘提前买遭遇严重逆向选择：主板真控盘105笔中58%尾盘封死涨停买不到，能买的44笔隔夜胜率仅 15.9%、均亏 -2.45%。")]),
            B([R("第31天高开就是明牌出货坑：真控盘第31天高开36笔持10天胜率骤降至 25.0% 均亏 -11.58%，持20天胜率仅 13.9% 均亏 -16.86%。")]),
            P([R("二、48项严格时点因子精选与7套动态卖点优化红队终裁", bold=True)]),
            B([R("题材梯队与控盘因子全线样本外失效：开盘啦题材池样本内 +5.52% 至样本外翻负 -5.50%，同题材助攻样本外 -1.86%，2026年更跌至 -5.08%。")]),
            B([R("主板10cm宽池靠回调低开打分加次日+12%限价快跑曾在2021至2025连赢5年（单仓 +899.2%），但2026年11笔破功转亏 -17.8%，且缩回真控盘样本仅7笔碎裂。")]),
            B([R("双创20cm与全市场合池全卡死在红队关：20cm分期去前3极值全负（样本内 -14.2%、样本外 -17.2%），合池2024大亏 -21.2% 且多重检验未过关。")]),
            B([R("幸存者根因：双成药业、天普股份、大千生态、高新发展全系D30封板叠D31一字锁死买不到，可买池频踩雷科防务(-32.5%)与浙江建投停牌核查。")]),
            BL(), BL(), BL(),
        ],
        "tables": [
            ("表一：第30天尾盘买 vs 第31天开盘买及打分卖点优化终局对照（扣30bps滑点与跌停顺延）", [
                [_c("测试方案", True), _c("可买笔数", True), _c("胜率 / 单仓累计", True), _c("样本外与2026红队裁定", True)],
                [_c("主板真控盘 D30尾买持5天"), _c("44 笔"), _c("隔夜15.9% / -80.0%"), _c("58%买不到，逆向选择大亏")],
                [_c("主板真控盘 D31开买持5天"), _c("73 笔"), _c("43.1% / -84.9%"), _c("2026年均亏 -5.52%，彻底证伪")],
                [_c("主板真控盘 D31高开持10天"), _c("36 笔"), _c("25.0% / 均-11.58%"), _c("明牌一致高开必被出货")],
                [_c("主板宽池>=80 + D32挂+12%"), _c("54 笔"), _c("72.1% / +899.2%"), _c("2026破功 -17.8%，真控盘碎裂")],
                [_c("双创20cm>=76 + 固定D35"), _c("78 笔"), _c("57.4% / +576.0%"), _c("分期去前3极值全负，DSR仅0.24")],
                [_c("合池>=80 + 3日递减止盈"), _c("130 笔"), _c("68.0% / +683.2%"), _c("2024亏-21.2%，真控盘OOS负")],
            ]),
        ],
        "img_path": None,
    }

    invalid_rows = [
        ("卡30天200%异动第30与31天证伪", "6年48因子", "D30尾买隔夜胜16%，418组0过红队六关", "作老仓兑现窗，禁接盘二波"),
        ("四进五 V2.0 (下放淘汰)", "五年全量", "去前三大妖股独立净值仅 0.89x", "依赖少数极值，移出实盘"),
        ("大跌切银行与退潮切消费证伪", "五年全量", "退潮切白酒胜36.8%，生猪22.7%亏-2.04%", "严禁科技退潮买消费避险"),
        ("十年暴涨暴跌反抽证伪", "10年/5年", "9套急跌抄底与反抽规则全灭，亏至-93%以上", "永久禁做A杀反抽"),
        ("行业明牌大高潮追买证伪", "8年661次", "大高潮买中军日内亏-0.64%，领涨亏-1.51%", "纯A独立高潮高开禁追"),
        ("热门题材200亿大中军证伪", "5年28740组", "三轨全证伪，热门题材买200亿大中军亏钱", "禁追热门题材大中军"),
        ("大池子妖股暴跌反核证伪", "5年171组", "仅2.3%三期全正，去前5亏-35.08%", "永久禁做大池子反核"),
        ("雪球短线大V三年胜率证伪", "122位大V", "粉丝数与赚钱倒挂，超8成扣费亏钱", "严禁盲跟雪球高频复盘号"),
        ("连板晋级率与冰点抄底证伪", "5年1211日", "高晋级率不超19天，追高抄冰点双亏", "禁用晋级率盲抄冰点"),
        ("庄股事前可预测性证伪", "421只庄股", "横盘缩量找庄股样本外全灭，与随机无异", "永久放弃事前猜庄股"),
        ("电竞夺冠事件追涨证伪", "2022至2026", "电竞夺冠无产业增量，次日追涨必亏", "纯情绪事件禁追高"),
    ]
    hub_i = build_hub_doc("证伪回测与避坑墓碑", "结论：本目录收录6大主力策略之外全部已证伪小策略与全市场亏钱陷阱，用于永久避坑防复燃。", invalid_rows)

    s9.audit_doc_strict_v191(doc, require_img=False)
    s9.audit_doc_strict_v191(hub_i, require_img=False)

    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        did, ntk = s9.find_or_create_child_node(I_NODE, doc["title"])
        done, fail = s6.write_document_payload(did, doc["blocks"], doc["tables"], None)
        if fail > 0:
            raise RuntimeError(f"Write fail={fail}")
        time.sleep(0.8)
        s9.verify_document_v191(did, doc["title"], expected_tables_count=1, has_img=False)
        print(f"PUBLISHED_INVALID [{ntk}] https://my.feishu.cn/wiki/{ntk}")

        done2, fail2 = s6.write_document_payload(I_DOC, hub_i["blocks"], hub_i["tables"], None)
        if fail2 > 0:
            raise RuntimeError(f"Hub write fail={fail2}")
        time.sleep(0.8)
        s9.verify_document_v191(I_DOC, "证伪回测与避坑墓碑", expected_tables_count=1, has_img=False)
        print("UPDATED_INVALID_HUB 11 items verified PASS!")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
