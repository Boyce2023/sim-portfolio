#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Organize Feishu `Claude/Argon 因子挖掘、回测` (Jxarwc3wliQZCakXO1xccPmrnCc) into 2 clean subdirectories:
1. 有效回测与可用规律
2. 证伪回测与避坑墓碑
"""
import fcntl, os, sys, time, requests

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR_DIR)
import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from small_backtests_payloads_20261124 import build_new_valid_docs, build_new_invalid_docs, build_hub_doc

PARENT_ROOT = "Jxarwc3wliQZCakXO1xccPmrnCc"
TITLE_VALID = "有效回测与可用规律"
TITLE_INVALID = "证伪回测与避坑墓碑"

EXISTING_VALID = [
    ("Oq9wwF3tFiR6KukhacBcr5tynUc", "美股对A股传导回归实证", "5年/1年/4月", "创业板近四月20日R方48.5%弹性+1.30", "波段盯纳指，科创做低开"),
    ("GC92wJFluiowqDkSELIcNMu8n0c", "六大商品股期联动十年回测", "2016至2026", "猪锂股真领先左侧胜，金铜油煤0d同步", "猪锂做左侧，煤金跟趋势"),
    ("SFVdwWKUAiY52Gk6PD8cYPp7nNg", "大哥护盘五句口诀十年实证", "2017至2026", "宽基爆量>=2x叠净申购T+20胜率83.9%", "脉冲吃瓜，真爆量方抄底"),
    ("VhmFwi67miB7DwkJS9ycCK2anQb", "A股15年16套投资理论TEI", "2011至2026", "小市值(64.3)与大盘低波(62.3)双强", "信本土风格，弃周期玄学"),
    ("Q6lSwxMwuiPXVIkCLPncfPyDnRg", "V19.1全量红队物理真账校准", "五年228笔", "清除跌停强卖与除权错算，真账归正", "生产策略唯一账本基准"),
    ("QlJuwfCZVitkhMkPB1ecJ815n1g", "三大连板跨板位互学升级", "五年全量", "机制移植大增净值，三策略DSR全过95%", "已实盘落地V19至V20"),
    ("RVB6wqwAFirgflkK8b3cAwFmn7g", "全策略八项防过拟合体检", "五年全量", "四大主战策略全过95.7%，淘汰两伪策略", "防过拟合统一准入门槛"),
    ("NpkMwJZrki7zzykJxEqceDDxn6c", "跨年妖十五年深度回测", "2011至2026", "近十年每年100%出跨年妖，年末抱团", "年末右侧截获高辨识龙头"),
    ("CpbZw55C3i9AVlkoiEFckNKunLf", "3进4扫板与反包17因子全集", "2021至2026", "17条无前视偏差正期望因子全期稳赚", "已吸收进三进四主策略"),
    ("O2DMwooeRiNLFuk90QCcPUJ8nAf", "五板高标锁仓与挂价回测", "2021至2026", "锁仓超50%叠换手15%至70%胜率91.7%", "已吸收进高标首阴V5.1"),
    ("H5Yywz4JGi2323kBiL5cGREqnj0", "同高度PK与拉萨席位实证", "7.2万笔", "同高度PK挑封单大换手低，4拉萨必跌", "盘前唯一头名筛选硬规则"),
    ("SlAWw0vqki7w0lk7a0AcKxYvn2g", "新概念词启动率与共现池", "698新词", "独苗92.6%一日游，满3板共现首板26.3%", "防独苗陷阱，只做梯队共现"),
    ("Vo8KwR8mIiexcvktPKqcTngTn6J", "题材连两天强势分流选股", "五年全量", "连两天前3满5板，未封挑小市值正超额", "挑低位小市值，禁追高涨幅"),
    ("PFTOw4x2OiOg2skpb65cSHgXnwb", "首板与高标市值悖论实证", "2.2万笔", "首板超100亿次日胜率71%，高标买小", "首板买大不买小，高标买小"),
    ("AzC2wKAdKi3GJMkODbtce9dkngd", "连板断层真空日回测", "5年1211日", "断层日一进二胜率跳升，缩量三进四大面", "断层做低位切，避缩量高切"),
    ("Efc9wkxZOiyfwSkf6WmcZFehnXb", "超级高标与绕异动二波", "2015至2026", "10日滚动剔除控异动二波与100%见顶律", "高标持仓盯紧双异动红线"),
]

EXISTING_INVALID = [
    ("AEvTwHSVQiBGfQkoNKGcJUlonWc", "知名游资红黑榜外挂证伪", "五年9.6万条", "四大策略外挂游资榜全线大跌，溢价透支", "维持粗席位规则，禁加细榜"),
    ("Pdhcwd8aviC157kjvV2cLEQvnkf", "雪球短线大V三年胜率证伪", "122位大V", "粉丝数与赚钱倒挂，超8成扣费亏钱", "严禁盲跟雪球高频复盘号"),
    ("XPYpw1nsti6AQBkFcpScv2EOnrb", "连板晋级率与冰点抄底证伪", "5年1211日", "高晋级率不超19天，追高抄冰点双亏", "禁用晋级率盲抄冰点"),
    ("PvifwBqxCiQFuGkBf89cFax0nAd", "庄股事前可预测性证伪", "421只庄股", "横盘缩量找庄股样本外全灭，与随机无异", "永久放弃事前猜庄股"),
    ("RRznw0BPoiimX2kVDCfcN9mBnne", "电竞夺冠事件追涨证伪", "2022至2026", "电竞夺冠无产业增量，次日追涨必亏", "纯情绪事件禁追高"),
    ("J3dmwefcoiGZEVkxXoEcN20kny4", "绕异动二波跟风模仿证伪", "2015至2026", "跟风模仿横盘控异动真突破暴跌成大面", "禁买跟风模仿控异动票"),
    ("SXkvwr58dirOG9kpKa2chdY6nlb", "绕异动模仿回测空壳重复页", "历史残留", "重名空壳残留页，移入归档防误删", "查阅请看上篇完整版"),
]


def ls_kids(pt: str):
    hdr = {"Authorization": f"Bearer {s6.tok()}"}
    items, page_tok = [], None
    while True:
        p = {"parent_node_token": pt, "page_size": 50}
        if page_tok:
            p["page_token"] = page_tok
        d = requests.get(f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes", params=p, headers=hdr, timeout=10).json().get("data", {})
        items.extend(d.get("items", []))
        if not d.get("has_more"):
            break
        page_tok = d.get("page_token")
    return items


def move_wiki_node(node_token: str, target_parent_token: str):
    hdr = {"Authorization": f"Bearer {s6.tok()}", "Content-Type": "application/json"}
    url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes/{node_token}/move"
    r = requests.post(url, headers=hdr, json={"target_parent_token": target_parent_token, "target_space_id": s6.SPACE_ID}, timeout=15).json()
    if r.get("code") != 0:
        raise RuntimeError(f"Move {node_token} -> {target_parent_token} failed: {r}")


def publish_one(parent_tok: str, payload: dict, skip_titles: set):
    s9.audit_doc_strict_v191(payload, require_img=False)
    if payload["title"] in skip_titles:
        print(f"SKIP_ALREADY_VERIFIED {payload['title']}")
        return
    doc_id, node_tok = s9.find_or_create_child_node(parent_tok, payload["title"])
    done, fail = s6.write_document_payload(doc_id, payload["blocks"], payload["tables"], None)
    if fail > 0:
        raise RuntimeError(f"Write fail={fail} on {payload['title']}")
    time.sleep(0.8)
    s9.verify_document_v191(doc_id, payload["title"], expected_tables_count=len(payload["tables"]), has_img=False)
    print(f"PUBLISHED [{node_tok}] {payload['title']} -> https://my.feishu.cn/wiki/{node_tok}")


def main():
    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        v_doc, v_node = s9.find_or_create_child_node(PARENT_ROOT, TITLE_VALID)
        i_doc, i_node = s9.find_or_create_child_node(PARENT_ROOT, TITLE_INVALID)

        existing_v_titles = {k["title"] for k in ls_kids(v_node)}
        existing_i_titles = {k["title"] for k in ls_kids(i_node)}
        for p in build_new_valid_docs():
            publish_one(v_node, p, existing_v_titles)
        for p in build_new_invalid_docs():
            publish_one(i_node, p, existing_i_titles)

        # Move only nodes still sitting under PARENT_ROOT
        root_tokens = {k["node_token"] for k in ls_kids(PARENT_ROOT)}
        moved_v = moved_i = 0
        for nt, *_ in EXISTING_VALID:
            if nt in root_tokens:
                move_wiki_node(nt, v_node)
                moved_v += 1
                time.sleep(0.2)
        for nt, *_ in EXISTING_INVALID:
            if nt in root_tokens:
                move_wiki_node(nt, i_node)
                moved_i += 1
                time.sleep(0.2)
        print(f"MOVED_NOW valid={moved_v}, invalid={moved_i}")

        valid_rows = [
            ("美股大跌A股低开高走实证", "5年/1年", "纳指跌超-1.5%叠科创低开，次日卖胜73%赔1.52", "首选科创50深低开接反抽"),
        ] + [(nm, per, concl, use) for _, nm, per, concl, use in EXISTING_VALID]
        invalid_rows = [
            ("十年暴涨暴跌反抽证伪", "10年/5年", "9套急跌抄底与反抽规则全灭，亏至-93%以上", "永久禁做A杀反抽"),
            ("四板断板二波规则证伪", "5年时点", "有梯队断板收跌165笔胜21.8%，2026亏-48.4%", "禁按11月幸存者盲买"),
            ("行业明牌大高潮追买证伪", "8年661次", "大高潮买中军日内亏-0.64%，领涨亏-1.51%", "纯A独立高潮高开禁追"),
            ("大池子妖股暴跌反核证伪", "5年171组", "仅2.3%三期全正，去前5亏-35.08%", "永久禁做大池子反核"),
            ("关联：大跌切银行与消费证伪", "挂小策略下", "退潮切白酒生猪胜率仅22.7%至36.8%", "切忌退潮买消费避险"),
        ] + [(nm, per, concl, use) for _, nm, per, concl, use in EXISTING_INVALID if "空壳" not in nm]

        hub_v = build_hub_doc(TITLE_VALID, "结论：本目录收录全部经历史实证检验、具备真实正超额或实战约束力的有效回测。", valid_rows)
        hub_i = build_hub_doc(TITLE_INVALID, "结论：本目录收录全部被严格时点回测证伪的假说与亏钱陷阱，用于永久避坑防复燃。", invalid_rows)
        s9.audit_doc_strict_v191(hub_v, require_img=False)
        s9.audit_doc_strict_v191(hub_i, require_img=False)
        s6.write_document_payload(v_doc, hub_v["blocks"], hub_v["tables"], None)
        s6.write_document_payload(i_doc, hub_i["blocks"], hub_i["tables"], None)
        time.sleep(1.0)
        s9.verify_document_v191(v_doc, TITLE_VALID, expected_tables_count=1, has_img=False)
        s9.verify_document_v191(i_doc, TITLE_INVALID, expected_tables_count=1, has_img=False)

        root_kids, v_kids, i_kids = ls_kids(PARENT_ROOT), ls_kids(v_node), ls_kids(i_node)
        print(f"\nFINAL AUDIT: root_children={len(root_kids)} | valid_children={len(v_kids)} | invalid_children={len(i_kids)}")
        for k in root_kids:
            print(f"  ROOT -> [{k['node_token']}] {k['title']} (https://my.feishu.cn/wiki/{k['node_token']})")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
