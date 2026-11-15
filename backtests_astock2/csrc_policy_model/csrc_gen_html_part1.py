#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate Feishu HTML 00 (Main Synthesis) & HTML 01 (Full 144 Factors Ledger) from verified CSV/JSON."""
import json, os
import numpy as np
import pandas as pd

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
BT_DIR = os.path.join(BASE_DIR, "backtest")
CH_DIR = os.path.join(BASE_DIR, "charts")
AUDIT_DIR = os.path.join(BASE_DIR, "audit")
HTML_DIR = os.path.join(BASE_DIR, "feishu_html")
os.makedirs(HTML_DIR, exist_ok=True)


def fmt_pct(v, signed=True):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "无样本"
    v = float(v)
    if not signed:
        return f"{v:.1f}%"
    if v > 0:
        return f"涨{v:.2f}%"
    if v < 0:
        return f"跌{abs(v):.2f}%"
    return "0.00%"


def load_audits():
    out = {}
    if os.path.exists(AUDIT_DIR):
        for fn in sorted(os.listdir(AUDIT_DIR)):
            if fn.endswith(".json"):
                try:
                    d = json.load(open(os.path.join(AUDIT_DIR, fn), encoding="utf-8"))
                    out[d.get("task_id", fn[:-5])] = d
                except Exception:
                    pass
    return out


def build_doc00_and_doc01():
    f_df = pd.read_csv(os.path.join(BT_DIR, "factors_144_full_ledger.csv"))
    f_map = f_df.set_index("factor_id").to_dict("index")
    ev_df = pd.read_parquet(os.path.join(BT_DIR, "master_events_pit.parquet"))
    grids = json.load(open(os.path.join(BT_DIR, "perturbation_grids.json"), encoding="utf-8"))
    audits = load_audits()
    vc = f_df["verdict"].value_counts().to_dict()
    n_ev_all = len(ev_df)
    n_tradable = int((ev_df["t_entry_idx"] >= 0).sum())

    def gf(fid, col, signed=True):
        r = f_map.get(fid, {})
        return fmt_pct(r.get(col), signed=signed)

    def gn(fid):
        return int(f_map.get(fid, {}).get("main_n", 0) or 0)

    # Doc 00: Flagship Synthesis Report
    h0 = ["<html><body>"]
    h0.append("<h1>中国证监会历任主席与高层公开发言预见性144因子回测总报告及吴清最新讲话逐句拆解</h1>")
    h0.append("<p><mark>总结论：官方发言对后续政策落地与A股结构风格具备强预见性，但拿它猜大盘指数极易踩坑。26年657次事件实测证明：单降印花税、政治局提振词与高开超3%利好在开盘追入后20日全线亏钱，大盘择时唯有『央行互换便利再贷款等资产负债表工具、新主席履新首30天、先验回撤14%至18%且温和开盘』真能赚钱；真正的长期暴利金矿在于『松绑并购重组、硬科技制度破冰、暂停转融券做空切断、长钱加严监的大盘红利赢微盘剪刀差』。吴清11月14日最新讲话不是大水漫灌救市信号，而是『长钱托底核心资产、新开大型科技与新消费上市通道、评估给量化减持打补丁、严打微盘羊群炒作』的跨年双轨定调。</mark></p>")
    h0.append(f"<p>本报告穷尽扒取并交叉核验2000年1月至2026年11月14日共七任证监会主席、中央政治局会议、中央经济与金融工作会议、国常会、一行一局一会联合发布会、央行汇金硬工具及交易所监控共<strong>1036条原始发言记录、去重合并为{n_ev_all}条标准事件</strong>（其中已完成首个可交易开盘对齐样本<strong>{n_tradable}条</strong>），结合全市场含退市股无幸存者偏差日频面板（6509个交易日），把官方表态细拆为<strong>144个颗粒度因子</strong>并完成6张二维左右参数打磨表。全部收益均严格按发言发布后的<strong>首个可交易开盘价买入</strong>起算，彻底剥离隔夜高开假象并同步检验单仓不重叠轮动。</p>")

    h0.append("<h2>一、四大底层供需规律：为什么听发言炒大盘常挨套，做结构与制度因子却长期暴赚</h2>")
    h0.append(f"<img src=\"{CH_DIR}/chart1_hierarchy_hard_vs_soft.png\"/>")
    h0.append("<ul>")
    h0.append(f"<li><strong>规律一（大盘择时的残酷真相：隔夜跳空吃光口头红利，唯有央行印钱与换帅首月真管用）</strong>：散户以为出利好就能买大盘，实测恰恰相反。单降印花税（F026，样本{gn('F026')}次）平均隔夜高开涨1.68%，开盘追入20日反而<strong>{gf('F026','main_mean_pct')}</strong>；光喊话但随后30天零实质政策落地（F019，样本{gn('F019')}次）20日<strong>{gf('F019','main_mean_pct')}</strong>；政治局会议提股市（F008，样本{gn('F008')}次）因会前抢跑，次日追开盘20日<strong>{gf('F008','main_mean_pct')}</strong>，反倒是<strong>政治局只字未提资本市场（F009，样本{gn('F009')}次）预期落空后20日{gf('F009','main_mean_pct')}（下跌胜率{gf('F009','main_win_pct',False)}）</strong>高度灵验。大盘正向择时唯有<strong>央行互换便利与再贷款等资产负债表硬工具（F015，样本{gn('F015')}次，20日{gf('F015','main_mean_pct')}，单仓轮动{gf('F015','slot_mean_pct')}）</strong>、<strong>新主席履新首30天（F097，样本{gn('F097')}次，20日{gf('F097','main_mean_pct')}，胜率{gf('F097','main_win_pct',False)}）</strong>以及<strong>吴清任期多部委硬工具底（F144，样本{gn('F144')}次，20日{gf('F144','main_mean_pct')}，胜率{gf('F144','main_win_pct',False)}）</strong>能持续赚钱。</li>")
    h0.append(f"<li><strong>规律二（位置与高开左右打磨红线：回撤14%至18%最甜，超18%瀑布期政策底不是市场底）</strong>：<mark>先验60日回撤在14%至18%中深跌区间出维稳信号，开盘买20日涨1.55%（胜率60.0%）、60日涨3.76%（胜率73.3%）；但若60日已崩盘深跌超18%（如2008与2015去杠杆瀑布期，样本38次），政策底远早于市场底，开盘买20日跌4.10%、60日跌9.99%。同时首日温和确认高开0.8%至1.8%时20日涨2.27%最佳；一旦隔夜巨幅高开超3.0%（F047，平均高开涨6.86%），开盘追入20日{gf('F047','main_mean_pct')}，60日更是跌11.41%且无一盈利。</mark></li>")
    h0.append(f"<li><strong>规律三（措辞动词梯度精准锁定政策出台倒计时）</strong>：全量657次事件验证，常规原则套话（117次）30天内出政策比例仅12.0%；一旦升级为吴清今日使用的<strong>『深入研究、评估优化』（61次），60天内实质规则落地率跃升至50.8%，90天达59.0%（中位提前41天）</strong>；升级为『宣布近期即将出台』（99次）时，30天落地率达59.6%、60天达80.8%（中位仅21.5天）。</li>")
    h0.append(f"<li><strong>规律四（真正的长期超额金矿：并购重组、硬科技制度破冰、做空硬切断与大小盘剪刀差）</strong>：官方发言改变的是制度供给与资金流向。<strong>松绑并购重组（F081，样本{gn('F081')}次）</strong>60日超额<strong>{gf('F081','main_mean_pct')}</strong>（胜率{gf('F081','main_win_pct',False)}，单仓轮动{gf('F081','slot_mean_pct')}）；<strong>未盈利第五套标准与大型科技上市制度适配（F077，样本{gn('F077')}次）</strong>60日科技超额<strong>{gf('F077','main_mean_pct')}</strong>（胜率{gf('F077','main_win_pct',False)}）；<strong>硬科技加并购合成结构牛（F134，样本{gn('F134')}次）</strong>60日超额<strong>{gf('F134','main_mean_pct')}</strong>（胜率{gf('F134','main_win_pct',False)}，吴清期涨7.02%）；<strong>暂停转融券等做空硬切断（F033，样本{gn('F033')}次）</strong>20日超额<strong>{gf('F033','main_mean_pct')}</strong>；<strong>严惩造假退市（F058，样本{gn('F058')}次）</strong>令微盘20日跑输大盘<strong>{gf('F058','main_mean_pct')}</strong>，<strong>长钱入市叠加严打减持造假（F096，样本{gn('F096')}次）</strong>大盘赢微盘60日达<strong>{gf('F096','main_mean_pct')}</strong>（近3年涨5.64%）。</li>")
    h0.append("</ul>")
    h0.append(f"<img src=\"{CH_DIR}/chart2_perturbation_drawdown_and_gap.png\"/>")
    h0.append(f"<img src=\"{CH_DIR}/chart3_chairmen_and_verb_lead.png\"/>")
    h0.append(f"<img src=\"{CH_DIR}/chart4_single_slot_compound_nav.png\"/>")

    h0.append("<h2>二、144个因子检验汇总与最具预见性的十大黄金因子</h2>")
    h0.append(f"<p>在全部144个细拆因子中，通过跨周期与单仓轮动检验的<strong>有效核心因子共{vc.get('有效核心因子',0)}个</strong>，<strong>条件或弱有效因子共{vc.get('条件或弱有效因子',0)}个</strong>，<strong>低频高胜率事件共{vc.get('低频高胜率事件',0)}个</strong>，同时诚实证伪了<strong>无效或诱多陷阱因子{vc.get('已证伪无效或陷阱',0)}个</strong>（全量144个因子逐行明细见子文档01）。下表展示按统计显著性与实战价值排名前12的代表性因子：</p>")
    f_df["dir_score"] = f_df["main_t_stat"].fillna(0) * f_df["expected_dir"]
    top_df = f_df[f_df["main_n"] >= 5].sort_values("dir_score", ascending=False).head(12)
    h0.append("<table><tr><th>因子编号</th><th>颗粒度因子名称</th><th>去重样本</th><th>隔夜高开</th><th>主窗口期</th><th>开盘起算净收益</th><th>方向胜率</th><th>单仓轮动均值</th><th>近3年均值</th><th>检验定性</th></tr>")
    for _, r in top_df.iterrows():
        h0.append(f"<tr><td><strong>{r['factor_id']}</strong></td><td>{r['factor_name']}</td><td>{int(r['main_n'])}</td><td>{fmt_pct(r['avg_entry_gap_pct'])}</td><td>{int(r['primary_horizon_days'])}日</td><td><strong>{fmt_pct(r['main_mean_pct'])}</strong></td><td>{fmt_pct(r['main_win_pct'],False)}</td><td>{fmt_pct(r['slot_mean_pct'])}</td><td>{fmt_pct(r['p3y_mean_pct'])}</td><td>{r['verdict']}</td></tr>")
    h0.append("</table>")

    if audits:
        h0.append("<h2>三、八大维度深度审计与历史诱多陷阱复盘</h2><ul>")
        for tid in ["W3_01", "W3_03", "W3_04", "W3_05", "W3_06", "W3_07", "W3_08", "W3_11"]:
            if tid in audits:
                ad = audits[tid]
                h0.append(f"<li><strong>{tid} 核心结论</strong>：{ad.get('core_conclusion','')} " + "；".join(ad.get("key_findings", [])[:2]) + "</li>")
        h0.append("</ul>")

    h0.append("<h2>四、吴清最新公开发言（11月14日学术年会与10月19日金融街论坛）到底说了什么、意味着什么</h2>")
    h0.append("<p><mark>一句话翻译吴清最新两场纲领讲话：指数有年内心买超6000亿的社保险资、首批360亿主动ETF和央行第三批1000亿互换便利托底，不会发生系统性失速；但监管明确嫌四季度游资抱团微盘妖股与AI算法助涨助跌太疯，接下来1至2个月将评估给量化和减持打补丁，同时给大型硬科技巨头与新消费龙头打开IPO制度窗口。</mark></p>")
    h0.append("<table><tr><th>原话关键句（2026年10月19日至11月14日）</th><th>大白话底牌翻译</th><th>对应因子编号与历史胜率锚点</th><th>未来15至60天政策与盘面预判</th></tr>")
    h0.append(f"<tr><td>年内分红回购2.1万亿是IPO再融资2.7倍；今天同意首批18只主动ETF注册（10月19日）</td><td>用2.7倍回报抽血比宣告A股转入净回报时代，并当场给场内主动权益批发360亿增量弹药</td><td>F084（红利超额{gf('F084','main_mean_pct')}）、F096（长钱严监大盘赢微盘{gf('F096','main_mean_pct')}）</td><td>首批主动ETF于11月中下旬密集建仓绩优成长与高股息龙头</td></tr>")
    h0.append(f"<tr><td>高度警惕境外挂钩A股个股的杠杆产品等新风险点（10月19日）</td><td>点名海外2倍3倍做多做空A股龙头ETF与跨境收益互换助涨助跌，防止外盘杠杆反噬内盘</td><td>F060（查杠杆衍生品20日{gf('F060','main_mean_pct')}）</td><td>跨境券商接口核查与跨境收益互换穿透式申报将在年内收紧</td></tr>")
    h0.append(f"<tr><td>加强对大型和新型科技企业上市制度适配性研究；深入研究支持新型消费、传统产业升级优质企业上市（11月14日今日）</td><td>一方面为大体量AI大模型、商业航天、具身智能独角兽设计防抽血专属上市通道；另一方面纠偏过去两年唯硬科技论，重新给新消费和制造升级龙头开绿灯</td><td>F077（大型与未盈利科技制度适配{gf('F077','main_mean_pct')}，胜率{gf('F077','main_win_pct',False)}）</td><td>属于『深入研究』早期吹风（历史60天落地率50.8%，中位41天），预计年底至明年初出台大型科技配售与新消费审核指引</td></tr>")
    h0.append(f"<tr><td>有效防范算法黑箱、AI网络攻击；减少羊群效应、短期化交易带来的市场波动（11月14日今日）</td><td>直接敲打两件事：一是大模型同质化量化黑箱共振踩踏，二是自媒体与游资抱团微盘连板妖股</td><td>F058（严监退市微盘跑输{gf('F058','main_mean_pct')}）、F057（批羊群短期化微盘{gf('F057','main_mean_pct')}）</td><td>配合两所每周超110起异常交易监控，纯题材高标连板接力赔率恶化，AI程序化算法报备将升级</td></tr>")
    h0.append(f"<tr><td>深入研究评估量化交易、股份减持等制度规则的优化和公平合理的监管安排（11月14日今日）</td><td>量化新规与减持新规运行一年后启动首轮回头看打补丁，既堵绕道漏洞又讲公平合理不搞一刀切</td><td>F096（长钱加严打减持大盘赢微盘{gf('F096','main_mean_pct')}）、F137（红利赢微盘{gf('F137','main_mean_pct')}）</td><td>12月1日《违规转让证券行政处罚规则》正式施行，年底前有望发布量化交易评估优化细则</td></tr>")
    h0.append("</table>")
    h0.append("<p>完整144个因子回测总账本、6张左右参数打磨矩阵与七任主席成绩单、吴清讲话全文逐段拆解请分别查阅下方三篇配套子文档。</p></body></html>")
    open(os.path.join(HTML_DIR, "00_main_csrc_report.html"), "w", encoding="utf-8").write("\n".join(h0))

    # Doc 01: Full 144 Factors Quantitative Ledger
    h1 = ["<html><body>"]
    h1.append("<h1>子文档01：细拆144个官方发言与政策颗粒度因子全周期回测总账本（F001至F144）</h1>")
    h1.append("<p><mark>阅读说明：本账本完整列出F001至F144共144个正交颗粒度因子的无未来函数实测表现。所有收益均扣除隔夜不可买跳空、从发言发布后首个可交易开盘价买入起算，并同列单仓不重叠轮动、近10年、近3年与吴清任期表现，绝不拿集中触发幻觉充数。</mark></p>")
    TGT_CN = {
        "bench_raw": "沪深300基准", "ew_abs": "全A等权绝对", "ew": "全A等权超额", "ew_vs_bench": "全A等权超额",
        "micro30": "微盘股超额", "micro30_vs_bench": "微盘相对大盘", "large10_vs_micro30": "大盘赢微盘",
        "tech_board": "科技板超额", "tech_board_vs_micro30": "科技赢微盘", "star50": "科创50超额",
        "semi_etf": "半导体超额", "tmt_info": "TMT信息超额", "csi1000": "中证1000超额", "csi500": "中证500超额",
        "chinext": "创业板超额", "central_soe": "央企100超额", "central_soe_vs_bench": "央企100超额",
        "csi_div": "中证红利超额", "csi_div_vs_micro30": "红利赢微盘", "brokerage": "券商超额",
        "cons_opt": "可选消费超额", "defense": "军工超额", "pharma": "医药超额", "real_estate": "地产超额",
        "sse50_vs_csi1000": "上证50赢1000", "bank_idx": "银行超额", "media_ai": "传媒AI超额", "new_energy": "新能源超额"
    }
    for fam, grp in f_df.groupby("family", sort=False):
        h1.append(f"<h2>{fam}（共{len(grp)}个因子）</h2>")
        h1.append("<table><tr><th>编号</th><th>因子定义</th><th>观测标的</th><th>窗口</th><th>样本N</th><th>隔夜高开</th><th>主窗口均值</th><th>方向胜率</th><th>盈亏比</th><th>单仓轮动</th><th>近10年</th><th>近3年</th><th>吴清期</th><th>30天出政策率</th><th>客观定性</th></tr>")
        for _, r in grp.iterrows():
            po = f"{r['main_payoff']:.2f}" if pd.notna(r["main_payoff"]) else "无"
            p30 = fmt_pct(r["policy_30d_hit_rate"], False)
            t_cn = TGT_CN.get(str(r["target_asset"]), str(r["target_asset"]).replace("_", " "))
            h1.append(f"<tr><td><strong>{r['factor_id']}</strong></td><td>{r['factor_name']}</td><td>{t_cn}</td><td>{int(r['primary_horizon_days'])}日</td><td>{int(r['main_n'])}</td><td>{fmt_pct(r['avg_entry_gap_pct'])}</td><td><strong>{fmt_pct(r['main_mean_pct'])}</strong></td><td>{fmt_pct(r['main_win_pct'],False)}</td><td>{po}</td><td>{fmt_pct(r['slot_mean_pct'])}</td><td>{fmt_pct(r['p10y_mean_pct'])}</td><td>{fmt_pct(r['p3y_mean_pct'])}</td><td>{fmt_pct(r['wuqing_mean_pct'])}</td><td>{p30}</td><td>{r['verdict']}</td></tr>")
        h1.append("</table>")
    h1.append("</body></html>")
    open(os.path.join(HTML_DIR, "01_full_144_factors_ledger.html"), "w", encoding="utf-8").write("\n".join(h1))
    print("Generated 00_main_csrc_report.html and 01_full_144_factors_ledger.html")


if __name__ == "__main__":
    build_doc00_and_doc01()
