#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Module 4 (RD026): publish_feishu_policy_polymarket.py
Generate plain-Chinese, V19.1-compliant HTML report from verified RD026 JSONs
and publish into Feishu Wiki under 《政策》 (YSDKwKuQciRq0ekDVw9c5LnRnDe).

D12 compliant (Tencent akshare + local DB only). Pure policy probability metrics.
Enforces V19.1 hard rules:
  - Zero banned clichés in body (矩阵/铁证/铁律/零未来函数/引擎 etc.)
  - Zero non-negative hyphens '-' anywhere in visible text (only genuine negative numbers allowed)
  - Zero em-dashes (—/——), zero exclamation marks, zero bold markdown '**'
  - Every table cell <= 40 characters
  - >= 6 blocks before the first table
  - Explicit empty paragraph block before every table
  - Total visible text >= 800 characters
"""
import fcntl
import json
import os
import re
import time
from bs4 import BeautifulSoup, Comment, Doctype, NavigableString

exec(open("/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())

BASE = "https://open.feishu.cn"
SPACE_ID = "7700231295393107208"
POLICY_PARENT_NODE = "YSDKwKuQciRq0ekDVw9c5LnRnDe"
ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = os.path.join(ROOT, "output/csrc_policy_100factors_20261114")
POLY_DIR = os.path.join(OUT_DIR, "policy_polymarket_v1")
AUDIT_JSON = os.path.join(POLY_DIR, "polymarket_4track_backtest_audit.json")
BOARD_JSON = os.path.join(POLY_DIR, "live_polymarket_board_20261125.json")
INGEST_JSON = os.path.join(POLY_DIR, "ingest_v2_audit.json")
HTML_OUT = os.path.join(POLY_DIR, "policy_polymarket_v1_report.html")
MANIFEST_PATH = os.path.join(OUT_DIR, "feishu_csrc_wiki_manifest.json")
LOCK_PATH = "/tmp/.feishu_csrc_144_pub.lock"

DOC_KEY = "csrc_polymarket_v1"
DOC_TITLE = "20261125 中国政策概率预测引擎V1与Polymarket实时盘口实证"

BANNED = [
    "星辰大海", "皇冠明珠", "飞轮", "底座", "赋能", "闭环", "引擎", "跃迁", "重塑", "颠覆",
    "范式", "生态", "矩阵", "全景", "硬核", "标尺", "试金石", "胜负手", "王牌",
    "钩子", "年金", "天花板", "破局", "抓手", "撬动", "罕见", "极其", "绝不", "完美",
    "铁证", "铁律", "暗礁", "命门", "底牌", "法典", "死限", "拆穿", "十战十胜", "干干净净",
    "圣经", "贵族", "宪法", "绞肉机", "法医", "零未来函数"
]


def fmt_dt(s: str) -> str:
    p = str(s).strip()[:10].split("-")
    return f"{p[0]}.{p[1]}.{p[2]}" if len(p) == 3 else str(s)


def fmt_bss(v) -> str:
    if v is None:
        return "无"
    v = float(v)
    return f"{v:+.4f}"


def fmt_auc(v) -> str:
    if v is None:
        return "无"
    return f"{float(v):.3f}"


def clean_text_strict(txt: str) -> str:
    rep = {
        "矩阵": "对照表", "铁证": "实证", "铁律": "硬规律", "零未来函数": "严格事前",
        "引擎": "模型", "赋能": "助力", "生态": "环境", "闭环": "完整链条",
        "范式": "模式", "罕见": "少见", "极其": "十分", "绝不": "不会",
        "完美": "理想", "全景": "全貌", "硬核": "扎实", "标尺": "参照",
        "胜负手": "关键点", "抓手": "着力点", "撬动": "带动", "重塑": "改变",
    }
    for k, v in rep.items():
        txt = txt.replace(k, v)
    txt = txt.replace("——", "，").replace("—", "，").replace("–", "至").replace("->", "至").replace("→", "至")
    txt = txt.replace("！", "。").replace("!", "。").replace("**", "")
    # Replace date strings YYYY-MM-DD with YYYY.MM.DD
    txt = re.sub(r"(\d{4})-(\d{2})-(\d{2})", r"\1.\2.\3", txt)
    # Replace PM-01..PM-08 with PM01..PM08 so no non-negative hyphen exists
    txt = re.sub(r"PM-(\d{2})", r"PM\1", txt)
    # Replace numeric ranges like 2021-2026 or 15-20 with '至' while preserving negative numbers like -0.0061 or -14.4%
    txt = re.sub(r"(\d)-(\d)", r"\1至\2", txt)
    # Replace remaining non-negative hyphens (not preceded by space/start/comma before digit)
    txt = re.sub(r"(?<=[A-Za-z\u4e00-\u9fff])-(?=[A-Za-z\u4e00-\u9fff0-9])", "", txt)
    txt = re.sub(r"(?<!\S)-(?!\d)", " ", txt)
    return txt


def assert_cell_len(rows: list, max_len: int = 40):
    for r in rows:
        for cell in r:
            plain = re.sub(r"<[^>]+>", "", str(cell)).strip()
            if len(plain) > max_len:
                raise RuntimeError(f"Table cell exceeds {max_len} chars ({len(plain)}): {plain}")


def build_html() -> str:
    audit = json.load(open(AUDIT_JSON, "r", encoding="utf-8"))
    board = json.load(open(BOARD_JSON, "r", encoding="utf-8"))
    ingest = json.load(open(INGEST_JSON, "r", encoding="utf-8"))

    snap = board["market_snapshot"]
    t1 = audit["track1"]
    t2 = audit["track2"]
    t3 = audit["track3"]
    t4 = audit["track4"]

    # Collect 4-track calibration table rows (strictly <= 40 chars per cell)
    track_rows = [
        ["预测轨道与合约", "OOS（样本外）N", "实际频/IS基准", "BS模型/BS基准", "OOS BSS", "AUC", "ECE误差", "诚实定性"],
    ]
    row_specs = [
        ("轨1: 吹风30天落地", t1["contracts"]["Y_30d"]["oos_2021_2026"], t1["contracts"]["Y_30d"]["verdict"]),
        ("轨1: 吹风60天落地", t1["contracts"]["Y_60d"]["oos_2021_2026"], t1["contracts"]["Y_60d"]["verdict"]),
        ("轨1: 吹风90天落地", t1["contracts"]["Y_90d"]["oos_2021_2026"], t1["contracts"]["Y_90d"]["verdict"]),
        ("轨2A: 20日硬稳市", t2["contracts"]["2A_hard_rescue_20td"]["oos_2021_2026"], t2["contracts"]["2A_hard_rescue_20td"]["verdict"]),
        ("轨2B: 20日V3>=60", t2["contracts"]["2B_v3_ge60_20td"]["oos_2023_2026"], t2["contracts"]["2B_v3_ge60_20td"]["verdict"]),
        ("轨3A: 10日特停(全)", t3["contracts"]["3A_exchange_surveillance_10td"]["oos_2021_2026"], t3["contracts"]["3A_exchange_surveillance_10td"]["verdict"]),
        ("轨3A: 停牌核查高频", t3["contracts"]["3A_notices_dense_10td"]["oos_2026"], t3["contracts"]["3A_notices_dense_10td"]["verdict"]),
        ("轨3B: 20日严监管", t3["contracts"]["3B_csrc_crackdown_20td"]["oos_2021_2026"], t3["contracts"]["3B_csrc_crackdown_20td"]["verdict"]),
        ("轨4A: 政治局(全70)", t4["contracts"]["4A_politburo_all70"]["oos_2021_2026"], t4["contracts"]["4A_politburo_all70"]["verdict"]),
        ("轨4A: 经济局贝叶斯", t4["contracts"]["4A_politburo_econ43"]["oos_seq_bayes_2021_2026"], t4["contracts"]["4A_politburo_econ43"]["verdict"]),
        ("轨4B: 会后30天落地", t4["contracts"]["4B_conf_followup_30d"]["oos_2021_2025"], t4["contracts"]["4B_conf_followup_30d"]["verdict"]),
    ]
    for label, o, verd in row_specs:
        track_rows.append([
            label,
            f"{o['n']}({o['pos_n']}正)",
            f"{o['actual_rate_pct']:.1f}%/{o['base_pred_pct']:.1f}%",
            f"{o['brier_model']:.3f}/{o['brier_base']:.3f}",
            f"<strong>{fmt_bss(o['bss'])}</strong>",
            fmt_auc(o["roc_auc"]),
            f"{o['ece_pct']:.1f}%",
            verd,
        ])
    assert_cell_len(track_rows)

    # Track 1 KM table
    stage_cn = {
        "IMMINENT_RULE": "即将推出",
        "DRAFT_CONSULT": "征求意见",
        "RESEARCH_EVALUATE": "深入研究",
        "ROUTINE_SLOGAN": "常规口号",
    }
    km_rows = [["措辞阶段", "样本N(落地)", "P25天", "中位P50天", "P75天", "30天转化", "60天转化", "90天转化"]]
    for stg in ["IMMINENT_RULE", "DRAFT_CONSULT", "RESEARCH_EVALUATE", "ROUTINE_SLOGAN"]:
        km = t1["km_by_action_verb_stage"][stg]
        km_rows.append([
            stage_cn[stg],
            f"{km['n']}({km['n_events']})",
            f"{km['p25_days']}天" if km["p25_days"] else "未达",
            f"<strong>{km['p50_days']}天</strong>" if km["p50_days"] else "未达",
            f"{km['p75_days']}天" if km["p75_days"] else "未达",
            f"{km['km_30d_pct']:.1f}%",
            f"{km['km_60d_pct']:.1f}%",
            f"{km['km_90d_pct']:.1f}%",
        ])
    assert_cell_len(km_rows)

    # Track 1 90d calibration bins table
    cal_rows = [["轨1 90天分箱区间", "样本N", "落地数", "预测均概率", "实际落地率", "偏差百分点"]]
    for b in t1["contracts"]["Y_90d"]["oos_2021_2026"]["calibration_bins"]:
        cal_rows.append([
            clean_text_strict(b["bin_range"]),
            str(b["n"]),
            str(b["pos_n"]),
            f"{b['mean_pred_pct']:.1f}%",
            f"{b['actual_freq_pct']:.1f}%",
            f"{b['gap_pp']:+.1f}pp",
        ])
    assert_cell_len(cal_rows)

    # Sequential Bayes Politburo recent 6 rows
    bayes_rows = [["会议日期", "会议月份", "会前60日回撤", "事前预测概率", "实际是否提及", "单次Brier"]]
    for br in t4["sequential_bayesian_update_table"][-6:]:
        dd_s = f"{br['prior_dd_60d_pct']:.1f}%" if br["prior_dd_60d_pct"] is not None else "无"
        bayes_rows.append([
            fmt_dt(br["event_date"]),
            f"{br['month']}月",
            dd_s,
            f"{br['pit_prior_prob_pct']:.1f}%",
            "提及(F008)" if br["actual_f008"] == 1 else "未提(F009)",
            f"{br['brier_contrib']:.4f}",
        ])
    assert_cell_len(bayes_rows)

    # Historical Replay table
    rep_rows = [["回放日期", "历史关键节点", "IS模型概率", "扩展PIT概率", "实际结果"]]
    short_landmarks = {
        "2023-07-24": "7月政治局首提活跃资本市场",
        "2024-02-02": "2月初微盘踩踏与汇金增持前夜",
        "2024-09-20": "9.24国新办组合拳前周五收市",
        "2024-11-01": "9.24后题材高点(5日均170板)",
        "2025-04-03": "4月关税冲击前最后交易日",
        "2026-11-06": "国常会研究稳市(16天后三连发)",
    }
    short_outcomes = {
        "2023-07-24": "命中：F008=1且30天内落地组合拳",
        "2024-02-02": "命中：2.6汇金扩增持且2.7换帅",
        "2024-09-20": "命中：4天后央行推5000亿SFISF",
        "2024-11-01": "命中：7天后浩欧博停牌核查",
        "2025-04-03": "外生冲击：4.7汇金盘中出手",
        "2026-11-06": "提前兑现：V3冲82分且11.22三连发",
    }
    for rp in board["historical_replays"]:
        dt_k = rp["replay_date"]
        rep_rows.append([
            fmt_dt(dt_k),
            short_landmarks.get(dt_k, rp["landmark"][:30]),
            f"{rp['is_model_prob_pct']:.1f}%",
            f"<strong>{rp['expanding_pit_prob_pct']:.1f}%</strong>",
            short_outcomes.get(dt_k, rp["actual_outcome"][:30]),
        ])
    assert_cell_len(rep_rows)

    # Live 8 contracts table
    short_q = {
        "PM-01": "深交所正式发布创业板做市细则",
        "PM-02": "证监会出台量化或减持优化细则",
        "PM-03": "12月政治局通稿提及资本市场",
        "PM-04": "经济工作会议后30天落地硬政策",
        "PM-05": "20交易日内再出央行部委硬稳市",
        "PM-06": "20交易日内国家队V3再触60分",
        "PM-07": "10交易日内交易所重点监控/特停",
        "PM-08": "经济工作会议升级且年内发文件簇",
    }
    short_drv = {
        "PM-01": "11.22征求意见+回撤14.6%+中位64天",
        "PM-02": "11.14吴清研究讲话+90天转61.5%",
        "PM-03": "连续7次全提+12月折价+跌14.4%",
        "PM-04": "4B强校准+积极表态后62.5%落地",
        "PM-05": "回撤14.4%承压+11.22刚落冷却期",
        "PM-06": "24至26高精度+5日净买1300亿托底",
        "PM-07": "宏观低技能，改用notices+5日63板",
        "PM-08": "24至25连两年19至20天内落地",
    }
    live_rows = [["编号", "轨道", "预测事件(截至到期日)", "到期日", "模型概率", "90%置信区间", "IS基准", "OOS BSS", "定性", "核心依据"]]
    for c in board["live_contracts"]:
        cid = c["contract_id"]
        live_rows.append([
            clean_text_strict(cid),
            clean_text_strict(c["track"]),
            short_q[cid],
            fmt_dt(c["deadline"]),
            f"<strong>{c['model_prob_pct']:.1f}%</strong>",
            f"{c['ci_90_pct'][0]:.1f}%至{c['ci_90_pct'][1]:.1f}%",
            f"{c['base_rate_pct']:.1f}%",
            fmt_bss(c["track_oos_bss"]),
            c["model_verdict"],
            short_drv[cid],
        ])
    assert_cell_len(live_rows)

    def mk_table(rows):
        trs = []
        for idx_r, r in enumerate(rows):
            tag = "th" if idx_r == 0 else "td"
            tds = "".join(f"<{tag}>{clean_text_strict(x)}</{tag}>" for x in r)
            trs.append(f"<tr>{tds}</tr>")
        return "<table>" + "".join(trs) + "</table>"

    h = ["<html><body>"]
    # >= 6 blocks before the first table (h1, mark-p, h2, p, ul(4 li) -> 9 blocks!)
    h.append("<h1>中国政策概率预测系统V1与Polymarket实时盘口实证（2026年11月25日）</h1>")
    h.append(
        "<p><mark>总结论：先预测下一项政策是否落地，比直接用发言猜大盘指数更可靠。"
        "26年663条事件严格样本外实证表明：『吹风至真落地（Track 1）』与『重磅会议后30天配套落地（Track 4B）』具备强校准能力，"
        "OOS（样本外）Brier Skill Score 分别达 +0.2660 与 +0.2046（AUC均在0.80左右）。"
        "『国家队V3护盘（Track 2B）』在2024至2026样本外稳定有效（BSS +0.1088）。"
        "同时必须诚实指出：『交易所重点监控点名（Track 3A宏观版）』OOS（样本外）BSS 为 -0.0061，未跑赢基准概率，主因特停由个股偏离度触发而非全市场涨停家数。</mark></p>"
    )
    h.append("<h2>一、设计原则与语料升级（截至2026年11月25日）</h2>")
    h.append(
        f"<p>本次升级将历史政策库由657条增补至<strong>{ingest['events_total']}条</strong>，日频市场面板延展至<strong>{fmt_dt(snap['as_of_market_date'])}</strong>（共{ingest['panel_rows']}个交易日）。"
        "全流程坚守三项纪律，保证每个历史节点均在严格PIT（点时点）口径下完成训练与打分。</p>"
    )
    h.append("<ul>")
    h.append("<li><strong>剔除同日泄露</strong>：Track 1 仅保留非当日硬规则的363条先行信号，修正2024.06.19与2026.07.03两笔同日标签，严格要求后续政策滞后至少1个自然日。</li>")
    h.append("<li><strong>非重叠周频决策</strong>：Track 2 与 Track 3 统一采用每周五收盘切点，前向观察窗口严格落在交易日次日至第10或第20日，杜绝日频重叠虚增样本。</li>")
    h.append("<li><strong>诚实基准对照</strong>：所有OOS（样本外）一律对标IS（样本内）基准气候概率，跑输基准即如实标为低技能，不在样本外凑参数。</li>")
    h.append("</ul>")

    h.append("<h2>二、四轨26年严格OOS（样本外）Brier Score校准总表</h2>")
    h.append(
        "<p>下表汇总四个预测轨道在2021至2026年OOS（样本外）的真实校准表现。"
        "Brier Score 越低越准，BSS大于0代表击败IS（样本内）基准概率，ECE代表各概率分箱与实际落地率的平均偏差。</p>"
    )
    h.append(mk_table(track_rows))

    h.append("<h3>Track 1 政策措辞动词转化规律与90天分箱校准</h3>")
    h.append(
        "<p>使用 Kaplan Meier 生存曲线处理末尾右删失样本后，政策措辞与落地速度呈现稳定单调阶梯。"
        "一旦官方从常规口号推进到深入研究或征求意见，60天内落地率由20.1%跃升至50.0%至53.2%。</p>"
    )
    h.append(mk_table(km_rows))
    h.append("<p>下表检验 Track 1 90天模型在2021至2026年OOS（样本外）五个分箱内的预测概率与实际落地频率。</p>")
    h.append(mk_table(cal_rows))

    h.append("<h3>Track 2、Track 3 与 Track 4 有效性与失效原因拆解</h3>")
    h.append("<ul>")
    h.append(
        "<li><strong>Track 2A（央行与部委硬稳市，BSS +0.0382）</strong>：模型在2021至2026年排序有效（AUC 0.599），"
        "但IS（样本内）基准仅28.7%，2024至2026年高频托底使实际发生率跳升至72.4%，产生系统性偏低校准漂移（ECE 22.8%）。</li>"
    )
    h.append(
        "<li><strong>Track 2B（国家队V3触及60分，BSS +0.0604）</strong>：2023至2026年整体校准误差仅6.6%，"
        "在2024至2026年宽基ETF主导阶段OOS（样本外）BSS进一步升至 +0.1088（AUC 0.774）。</li>"
    )
    h.append(
        "<li><strong>Track 3（短线狂热与监管降温，3A宏观 BSS -0.0061）</strong>：宏观全市场版本未跑赢基准，因为2015至2020年语料稀疏且交易所停牌核查由单只连板股偏离度决定；"
        "改用 notices.db 2025至2026年全量停牌核查公告子轨后，OOS（样本外）BSS转正至 +0.0330。Track 3B因2015年后20日内发生广义严监管常态率高达81.8%，边际增益仅 +0.0029。</li>"
    )
    h.append(
        "<li><strong>Track 4（重磅会议前瞻，4A序贯 +0.0550，4B +0.2046）</strong>：全部70条样本受早期非经济月史料收录偏倚影响（BSS -0.2068）；"
        "聚焦4月、7月、12月常规经济政治局会议后，指数衰减序贯贝叶斯追踪到2024.04以来连续7次会议100%提及资本市场的体制切换（BSS +0.0550）。会后通稿定调对30天配套硬政策具备强预测力（BSS +0.2046，AUC 0.798）。</li>"
    )
    h.append("</ul>")
    h.append("<p>下表展示 Track 4A 经济政治局会议最近6次在严格事前口径下的序贯贝叶斯概率更新过程。</p>")
    h.append(mk_table(bayes_rows))

    h.append("<h2>三、六大历史关键节点严格事前零回放验证</h2>")
    h.append(
        "<p>为检验模型在实战转折点的真实表现，我们在每个历史关键节点严格截断训练数据（仅使用该日之前已结算样本），"
        "特别回放2026.11.06国常会能否提前发出预警信号。</p>"
    )
    h.append(mk_table(rep_rows))
    h.append(
        "<p><mark>重点回放解读（2026.11.06 国常会至 2026.11.22 三连发）："
        "11月6日国常会公报使用研究类措辞，Track 1 仅给出30天落地率26.1%（IS基准版13.9%）、60天43.5%、90天52.2%；"
        "但同期沪深300已回撤14.5%且成交额跌至年内9%分位，Track 2A 扩展模型同步亮出64.3%的20交易日硬稳市高概率。"
        "随后11月19日至20日国家队V3评分冲至63与82分，16天后11月22日证监会统筹下调融资保证金至80%、降费27.6亿元及创业板做市征求意见三连发落地，兑现双轨交叉预警。</mark></p>"
    )

    h.append("<h2>四、截至2026年11月25日 Polymarket 实时8张概率盘口账本</h2>")
    h.append(
        f"<p>截至{fmt_dt(snap['as_of_market_date'])}收盘，沪深300报{snap['csi300_close']:.2f}点（60日回撤{snap['bench_dd_60d_pct']:.2f}%），"
        f"全A成交{snap['total_amount_yi']:.1f}亿元（年内{snap['amount_pct_250d_pct']:.1f}%分位），国家队V3盘后回落至{snap['v3_score_eod']}分（近5日纯净净申购+{snap['etf22_wflow_5d_yi']:.1f}亿元）。"
        "下表为实时生成的8张在途可复核合约，后续新政落地将由入库脚本自动结算评分。</p>"
    )
    h.append(mk_table(live_rows))

    h.append("<h3>关键盘口翻转条件提示</h3>")
    h.append("<ul>")
    h.append("<li><strong>PM03与PM04（12月政治局与经济工作会议）</strong>：当前模型给出78.7%提及资本市场（F008），但仍有21.3%的F009落空风险。若会前两周指数大涨收复4200点，会议篇幅转向内需消费的概率将显著上升。</li>")
    h.append("<li><strong>PM05与PM06（未来20交易日硬工具与国家队）</strong>：11月22日两融与降费落地使政策进入短期观察窗口，但沪深300仍在20日均线下方且回撤14.4%，一旦再度放量下探3954点低点，国家队二队共振脉冲重回60分以上的概率将迅速越过70%。</li>")
    h.append("<li><strong>PM07（10交易日交易所特停）</strong>：由于11月23日涨停骤增至152家且11月25日北纬科技已触发严重异常波动公告，高频停牌核查子轨给出34.6%，但该轨受单股连板高度主导，仅作辅助温度计使用。</li>")
    h.append("</ul></body></html>")

    raw_html = "\n".join(h)
    # Clean and run programmatic verification
    soup = BeautifulSoup(raw_html, "html.parser")
    for elem in soup.find_all(string=True):
        if isinstance(elem, (Doctype, Comment)):
            elem.extract()
            continue
        if elem.parent and elem.parent.name in ("style", "script"):
            continue
        txt = clean_text_strict(str(elem))
        elem.replace_with(NavigableString(txt))
    clean = str(soup)
    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(clean)

    # Verification gate: check visible text (excluding h1 title for "引擎" since user explicitly requested it in title)
    body_soup = BeautifulSoup(clean, "html.parser")
    h1 = body_soup.find("h1")
    body_text_no_h1 = body_soup.get_text() if not h1 else body_soup.get_text().replace(h1.get_text(), "", 1)
    vis_all = body_soup.get_text()

    bad_hyphens = re.findall(r".{0,6}(?:-(?!\d)|—|–|！|!|→|\*\*).{0,6}", vis_all)
    if bad_hyphens:
        raise RuntimeError(f"Bad punctuation found: {bad_hyphens[:5]}")
    hits = [w for w in BANNED if w in body_text_no_h1]
    if hits:
        raise RuntimeError(f"Banned word found in body: {hits}")
    if len(vis_all) < 800:
        raise RuntimeError(f"Visible char count too short: {len(vis_all)}")
    print(f"[HTML Check OK] visible_chars={len(vis_all)} -> {HTML_OUT}")
    return HTML_OUT


def load_manifest():
    return json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))


def save_manifest(m):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def ensure_node(key: str, title: str, parent_node_token: str) -> dict:
    m = load_manifest()
    if key in m["nodes"] and m["nodes"][key].get("obj_token"):
        info = m["nodes"][key]
        if info.get("title") != title:
            api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{info['node_token']}/update_title", {"title": title}, "POST")
            info["title"] = title
            save_manifest(m)
        return info
    payload = {"obj_type": "docx", "node_type": "origin", "title": title, "parent_node_token": parent_node_token}
    r = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes", payload, "POST")
    if r.get("code") != 0:
        raise RuntimeError(f"Failed creating node {key}: {r}")
    nd = r["data"]["node"]
    info = {
        "key": key, "title": title, "node_token": nd["node_token"], "obj_token": nd["obj_token"],
        "parent_node_token": parent_node_token, "url": f"https://my.feishu.cn/wiki/{nd['node_token']}"
    }
    m["nodes"][key] = info
    save_manifest(m)
    return info


def clear_doc_all(doc_id: str):
    for _ in range(40):
        r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500", method="GET")
        if r.get("code") != 0:
            break
        n = len(r["data"].get("items") or [])
        if n == 0:
            return True
        api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children/batch_delete", {"start_index": 0, "end_index": min(n, 150)}, "DELETE")
        time.sleep(0.25)
    return False


def publish_to_feishu(html_path: str):
    info = ensure_node(DOC_KEY, DOC_TITLE, POLICY_PARENT_NODE)
    doc_id = info["obj_token"]
    lock_fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        clear_doc_all(doc_id)
        parsed = split_big_tables(sanitize_callouts(parse2(html_path)))

        # V19.1 structural checks & blank paragraph before every table
        first_tbl_idx = next((idx for idx, it in enumerate(parsed) if it.get("t") == "table"), len(parsed))
        assert first_tbl_idx >= 6, f"Only {first_tbl_idx} blocks before first table (<6)"

        items = []
        for idx, it in enumerate(parsed):
            if it.get("t") == "table":
                items.append({"t": "empty_p"})
            items.append(it)

        # Check human prose gate (html2feishu.py)
        bad_hits = check_human_prose(items)
        if bad_hits:
            raise RuntimeError(f"Human prose gate hit: {bad_hits[:5]}")

        buf, done, fail = [], 0, 0

        def flush():
            nonlocal buf, done, fail
            for i in range(0, len(buf), 40):
                ch = buf[i:i + 40]
                r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": ch, "index": -1}, "POST")
                if r.get("code") == 0:
                    done += len(ch)
                else:
                    for b in ch:
                        r2 = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": [b], "index": -1}, "POST")
                        if r2.get("code") == 0:
                            done += 1
                        else:
                            fail += 1
                time.sleep(0.25)
            buf = []

        for it in items:
            if it.get("t") in ("table", "callout"):
                flush()
                d = Desc()
                root = d.add(it)
                rt = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant", {"children_id": [root], "descendants": d.d})
                if rt.get("code") == 0:
                    done += 1
                else:
                    fail += 1
                time.sleep(0.35)
            else:
                b = simple(it)
                if b:
                    buf.append(b)
        flush()

        rb = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET").get("data", {}).get("content", "")
        print(f"[FEISHU OK] title={DOC_TITLE}")
        print(f"[FEISHU URL] {info['url']}")
        print(f"[FEISHU VERIFY] blocks_before_first_table={first_tbl_idx} done_blocks={done} fail={fail} readback_chars={len(rb)}")
        if fail > 0 or len(rb) < 800:
            raise RuntimeError(f"Publish verify failed: fail={fail}, readback={len(rb)}")

        m = load_manifest()
        m["nodes"][DOC_KEY].update({"done_blocks": done, "readback_chars": len(rb), "blocks_before_first_table": first_tbl_idx})
        save_manifest(m)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    p_html = build_html()
    publish_to_feishu(p_html)
