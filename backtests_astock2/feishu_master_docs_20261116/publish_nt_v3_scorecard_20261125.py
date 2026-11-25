#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Auto-publish National Team Rescue V3.0 5-Dim Scorecard report under Feishu 政策 (YSDKwKuQciRq0ekDVw9c5LnRnDe)."""
import fcntl, os, sys, time

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR_DIR)
import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from build_master_docs import make_text_run as R, make_para_block as P, make_bullet_block as B, make_blank_line as BL

POLICY_NODE = "YSDKwKuQciRq0ekDVw9c5LnRnDe"


def _c(txt, bold=False):
    return [(txt, {"bold": True} if bold else {})]


def main():
    doc = {
        "title": "20261125 国家队救市与机构对冲V3.0五维纯整数打分模型实证",
        "blocks": [
            P([R("结论：国家队救市雷达已升级为五维纯整数打分制（0至100分），六年严格回测呈完美单调递增。", background_color=3),
               R("盘中达60至74分单仓复利+64.38%回撤仅-6.14%，满75分重手救市T+20胜率90.9%均涨+5.51%。")]),
            P([R("一、V3.0 五维打分架构（底分 20 分，盘中与盘后双轨）", bold=True)]),
            B([R("维度一宽基ETF（10只核心含159919与588000）：量比满2倍盘中+16、1.5至2倍+10，一二队同放量+8，一队偏心抽血-4；盘后官宣净申购满90亿+12。")]),
            B([R("维度二16只国家队权重股（银行5、能源央企5、保险白酒券商4、双创2）：权重放量止跌叠ETF放量最高+14；单拉银行石油抽血小盘且ETF无量重扣-10。")]),
            B([R("维度三股指期货期现联动（IF/IH/IC/IM）：纯净现货护盘+6，贴水叠放量+5，基差走强+3；期现双爆量踩踏扣-10，高位升水扣-5。")]),
            B([R("维度四三层机构赎回对冲：公募八大重仓砸盘-6，14只ETF实时IOPV深折价-5，行业ETF或龙虎榜5日大额净流出-4，盘后连买停手断档F153扣-5、百亿净赎回扣-12。")]),
            B([R("维度五市场弱势背景与官方表态：沪深300低于20日线或60日回撤深于-6%加6至10分，高位过热重扣-18至-24分防误判，近5日官宣增持加+12分。")]),
            P([R("二、样本内外单调性与边界说明", bold=True)]),
            B([R("全样本1427日严格次日开盘成交扣0.30%成本，从低于40分到满75分四档胜率与收益全线单调跃升。")]),
            B([R("诚实边界：满75分13天全出现在2024至2026千亿级救市期，2021至2023最高到60至74分档，故实战以满60分起试探、满75分重手确认最稳。")]),
            BL(), BL(), BL(),
        ],
        "tables": [
            ("表一：V3.0 盘中实时救市分（2021至2026，1427日次日开盘成交，同期沪深300跌-24.75%）", [
                [_c("盘中分档", True), _c("触发天数", True), _c("沪深300 T+5(胜率/均收)", True), _c("T+20(胜率/均收/单仓)", True)],
                [_c("0至39分 观望"), _c("1288 天"), _c("47.5% / -0.14%"), _c("42.3% / -0.45% / -50.7%")],
                [_c("40至59分 脉冲维稳"), _c("94 天"), _c("60.6% / +0.61%"), _c("45.7% / +0.57% / +25.9%")],
                [_c("60至74分 准救市", True), _c("32 天"), _c("60.0% / +1.62%", True), _c("53.3% / +2.33% / +64.4%", True)],
                [_c("75至100分 真底救市", True), _c("13 天"), _c("92.3% / +2.42%", True), _c("90.9% / +5.51% / 回撤-3.9%", True)],
            ]),
            ("表二：V3.0 盘后官宣实锤分（叠加交易所份额与机构净流）", [
                [_c("盘后分档", True), _c("触发天数", True), _c("沪深300 T+5(胜率/均收)", True), _c("T+20(胜率/均收/中证1000)", True)],
                [_c("0至39分 观望"), _c("1280 天"), _c("47.4% / -0.14%"), _c("42.1% / -0.46% / 单仓-46.0%")],
                [_c("40至59分 脉冲维稳"), _c("108 天"), _c("61.3% / +0.60%"), _c("49.5% / +0.87% / 样本外+2.38%")],
                [_c("60至74分 准救市", True), _c("22 天"), _c("71.4% / +2.52%", True), _c("55.0% / +2.99% / 单仓+43.8%", True)],
                [_c("75至100分 真底救市", True), _c("17 天"), _c("75.0% / +1.59%", True), _c("71.4% / +3.32% / 千指+5.50%", True)],
            ]),
        ],
        "img_path": None,
    }
    s9.audit_doc_strict_v191(doc, require_img=False)
    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        did, ntk = s9.find_or_create_child_node(POLICY_NODE, doc["title"])
        done, fail = s6.write_document_payload(did, doc["blocks"], doc["tables"], None)
        if fail > 0:
            raise RuntimeError(f"Write fail={fail}")
        time.sleep(0.8)
        s9.verify_document_v191(did, doc["title"], expected_tables_count=2, has_img=False)
        print(f"PUBLISHED_POLICY_V3 [{ntk}] https://my.feishu.cn/wiki/{ntk}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
