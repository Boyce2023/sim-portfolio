#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate Feishu HTML 02 (6 Left-Right Perturbation Grids & 7 Chairmen) & HTML 03 (Wu Qing Latest Decode) + Markdown."""
import json, os
import numpy as np
import pandas as pd

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
BT_DIR = os.path.join(BASE_DIR, "backtest")
AUDIT_DIR = os.path.join(BASE_DIR, "audit")
HTML_DIR = os.path.join(BASE_DIR, "feishu_html")
os.makedirs(HTML_DIR, exist_ok=True)


def fp(v, signed=True):
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


def build_doc02_and_doc03():
    grids = json.load(open(os.path.join(BT_DIR, "perturbation_grids.json"), encoding="utf-8"))
    ev_df = pd.read_parquet(os.path.join(BT_DIR, "master_events_pit.parquet"))
    f_df = pd.read_csv(os.path.join(BT_DIR, "factors_144_full_ledger.csv"))
    a24 = json.load(open(os.path.join(BASE_DIR, "shards", "A24.json"), encoding="utf-8"))
    audits = load_audits()

    # Doc 02: 6 Perturbation Grids + 7 Chairmen + Historical Milestone Events
    h2 = ["<html><body>"]
    h2.append("<h1>子文档02：六维左右参数打磨试错表与历任七位证监会主席横向成绩单</h1>")
    h2.append("<p><mark>每一个阈值都不是拍脑袋定的，而是把先验回撤、隔夜高开、成交分位、措辞动词、七任主席任期与交易所监控家数逐档左右平移试错，找出的真实盈利边界与追高死穴。</mark></p>")

    h2.append("<h2>打磨表一：先验60日市场回撤深度 × 持有窗口（1日至120日开盘买入收益）</h2>")
    h2.append("<table><tr><th>先验60日回撤分档</th><th>样本数</th><th>持有1日</th><th>持有5日</th><th>持有20日</th><th>20日胜率</th><th>持有60日</th><th>持有120日</th></tr>")
    for r in grids.get("grid1_drawdown_x_horizon", []):
        h2.append(f"<tr><td><strong>{r['bucket']}</strong></td><td>{r['n']}</td><td>{fp(r['ret_1d_pct'])}</td><td>{fp(r['ret_5d_pct'])}</td><td><strong>{fp(r['ret_20d_pct'])}</strong></td><td>{fp(r['win_20d_pct'],False)}</td><td>{fp(r['ret_60d_pct'])}</td><td>{fp(r['ret_120d_pct'])}</td></tr>")
    h2.append("</table>")

    h2.append("<h2>打磨表二：利好发布首日隔夜高开幅度 × 开盘追入后真实收益（识破高开诱多陷阱）</h2>")
    h2.append("<table><tr><th>首日开盘跳空分档</th><th>样本数</th><th>平均高开幅度</th><th>当日开盘至收盘</th><th>开盘买持有5日</th><th>开盘买持有20日</th><th>20日胜率</th><th>开盘买持有60日</th></tr>")
    for r in grids.get("grid2_gap_vs_post_open", []):
        h2.append(f"<tr><td><strong>{r['gap_bucket']}</strong></td><td>{r['n']}</td><td>{fp(r['avg_gap_pct'])}</td><td>{fp(r['post_open_1d_pct'])}</td><td>{fp(r['post_open_5d_pct'])}</td><td><strong>{fp(r['post_open_20d_pct'])}</strong></td><td>{fp(r['win_20d_pct'],False)}</td><td>{fp(r['post_open_60d_pct'])}</td></tr>")
    h2.append("</table>")

    h2.append("<h2>打磨表三：官方发言行动动词梯度 × 后续实质监管政策落地时间分布</h2>")
    h2.append("<table><tr><th>官方措辞动词阶段</th><th>事件数</th><th>15天内出细则率</th><th>30天内出细则率</th><th>60天内出细则率</th><th>90天内出细则率</th><th>中位提前天数</th></tr>")
    for r in grids.get("grid3_verb_to_policy_lead", []):
        med = f"{r['median_lead_days']}天" if r.get("median_lead_days") is not None else "无"
        h2.append(f"<tr><td><strong>{r['stage_cn']}</strong></td><td>{r['n_events']}</td><td>{fp(r['hit_15d_pct'],False)}</td><td>{fp(r['hit_30d_pct'],False)}</td><td>{fp(r['hit_60d_pct'],False)}</td><td>{fp(r['hit_90d_pct'],False)}</td><td>{med}</td></tr>")
    h2.append("</table>")

    h2.append("<h2>打磨表四：2000至2026年历任七位证监会主席施政兑现率与市场反应横向对比</h2>")
    h2.append("<table><tr><th>历任主席</th><th>收录样本总数</th><th>发言后30日政策兑现率</th><th>维稳发声样本</th><th>维稳后20日平均表现</th><th>维稳后20日胜率</th><th>严监管期大盘赢微盘20日超额</th></tr>")
    for r in grids.get("grid4_seven_chairmen_scorecard", []):
        h2.append(f"<tr><td><strong>{r['chairman']}</strong></td><td>{r['total_events']}</td><td>{fp(r['policy_30d_conversion_pct'],False)}</td><td>{r['rescue_n']}</td><td><strong>{fp(r['rescue_20d_ret_pct'])}</strong></td><td>{fp(r['rescue_20d_win_pct'],False)}</td><td>{fp(r['crackdown_large_vs_micro_20d_pct'])}</td></tr>")
    h2.append("</table>")

    h2.append("<h2>打磨表五：先验一年成交额分位 × 硬工具协同与纯口头喊话二维交叉表</h2>")
    h2.append("<table><tr><th>先验250日成交额分位</th><th>总样本</th><th>总样本20日表现</th><th>硬工具或多部委样本</th><th>硬工具20日表现</th><th>硬工具胜率</th><th>单兵口头样本</th><th>单兵口头20日表现</th></tr>")
    for r in grids.get("grid6_turnover_x_hard_vs_soft", []):
        h2.append(f"<tr><td><strong>{r['turnover_bucket']}</strong></td><td>{r['n_all']}</td><td>{fp(r['all_20d_pct'])}</td><td>{r['n_hard']}</td><td><strong>{fp(r['hard_20d_pct'])}</strong></td><td>{fp(r['hard_win_pct'],False)}</td><td>{r['n_soft']}</td><td>{fp(r['soft_20d_pct'])}</td></tr>")
    h2.append("</table>")

    h2.append("<h2>打磨表六：近5日交易所重点监控公告密度对超短线策略（一进二与高标首阴）的压制阈值</h2>")
    h2.append("<table><tr><th>近5日重点监控热度分档</th><th>交易日数</th><th>高标连板接力日均收益</th><th>一进二策略日均收益</th><th>高标首阴策略日均收益</th><th>全市场平均炸板率</th></tr>")
    for r in grids.get("grid5_exchange_surveillance_sweep", []):
        h2.append(f"<tr><td><strong>{r['ex_cnt5_bucket']}</strong></td><td>{r['n_days']}</td><td>{fp(r['high_relay_oc_pct'])}</td><td>{fp(r['v18_1to2_ret_pct'])}</td><td>{fp(r['v51_dip_ret_pct'])}</td><td>{fp(r['broken_board_rate_pct'],False)}</td></tr>")
    h2.append("</table></body></html>")
    open(os.path.join(HTML_DIR, "02_perturbation_grids_and_chairmen.html"), "w", encoding="utf-8").write("\n".join(h2))

    # Doc 03: Wu Qing Latest Speeches Line-by-Line Decode & 60-Day Policy Forecast
    h3 = ["<html><body>"]
    h3.append("<h1>子文档03：吴清2026年10月至11月最新公开发言逐句密码拆解与未来60天政策推演</h1>")
    h3.append("<p><mark>核心定性：吴清在2026年10月19日金融街论坛与11月14日（今日）首届中国资本市场学术年会上的两篇讲话，构成了『十五五』开局阶段的完整监管蓝图。10月19日主打当场发枪（批复18只主动ETF上限360亿加当晚落地违规减持量罚细则）；11月14日主打制度吹风与交易降温（研究大型科技与新消费上市适配、防范AI算法黑箱、减少羊群效应短期化交易、评估优化量化与减持规则）。</mark></p>")
    h3.append("<h2>一、2026年10月中旬至11月14日证监会与金融高层12大核心动作逐条台账</h2>")
    h3.append("<table><tr><th>日期与发布时段</th><th>发言主体与场合</th><th>核心原话摘录</th><th>动作阶段</th><th>受益与承压方向</th></tr>")
    STG_CN = {
        "ROUTINE_SLOGAN": "常规原则表态", "RESEARCH_EVALUATE": "深入研究与评估",
        "DRAFT_CONSULT": "公开征求意见", "IMMINENT_RULE": "近期即将出台", "HARD_ACTION_NOW": "当日直接落地硬工具"
    }
    for ev in a24.get("events", []):
        qt = " ".join(ev.get("verbatim_quotes", []))[:180]
        secs = "、".join(ev.get("named_sectors", []))
        p_dt = ev["event_date"].split("-")
        dt_cn = f"{p_dt[0]}年{int(p_dt[1])}月{int(p_dt[2])}日" if len(p_dt) == 3 else ev["event_date"]
        st_cn = STG_CN.get(ev.get("action_verb_stage", ""), ev.get("action_verb_stage", ""))
        h3.append(f"<tr><td><strong>{dt_cn}</strong>（{ev['exact_time_cst']}）</td><td>{ev['speaker_or_body']}：{ev['title_or_occasion']}</td><td>{qt}</td><td>{st_cn}</td><td>{secs}</td></tr>")
    h3.append("</table>")

    h3.append("<h2>二、深度审计组对吴清两篇讲话与跨年主基调的逐项推演</h2><ul>")
    for ob in a24.get("key_observations", []):
        h3.append(f"<li>{ob}</li>")
    for tid in ["W3_09", "W3_10", "W3_12"]:
        if tid in audits:
            ad = audits[tid]
            h3.append(f"<li><strong>{tid} 专项结论</strong>：{ad.get('core_conclusion','')} " + "；".join(ad.get("key_findings", [])) + "</li>")
    h3.append("</ul>")

    h3.append("<h2>三、未来15至60天（2026年11月下旬至2027年1月）可验证政策日历与交易纪律</h2>")
    h3.append("<table><tr><th>时间窗口</th><th>高概率落地事项（基于动词提前天数模型推演）</th><th>预期市场影响与应对纪律</th></tr>")
    h3.append("<tr><td><strong>11月下旬（15天内）</strong></td><td>《证券市场先行赔付指导意见》征求意见结束（11月18日截止）后择机定稿；首批18只主动ETF完成募集陆续上市建仓</td><td>退市追责与先行赔付刚性化压制财务存疑ST及壳资源；主动ETF建仓利好科创龙头与现金流白马</td></tr>")
    h3.append("<tr><td><strong>12月1日起</strong></td><td>《违规转让证券案件行政处罚实施规则》正式施行；新修订《上市公司证券发行注册管理办法》择机发布</td><td>绕道减持与马甲代持被精准量罚封堵；优质科技与制造龙头再融资并购审批提速</td></tr>")
    h3.append("<tr><td><strong>12月中旬（政治局与中央经济工作会议）</strong></td><td>年度最高规格经济定调，重点观察通稿中资本市场排序及是否再提稳住楼市股市或扩大内需新消费</td><td>若会前已抢跑大涨超5%（F056），切忌次日高开追涨；若会前缩量回调且出现强提振词（F010、F123），则是跨年春季躁动最佳买点</td></tr>")
    h3.append("<tr><td><strong>2026年底至2027年一季度（30至90天）</strong></td><td>量化交易与股份减持规则运行评估后的优化补丁出台；大型硬科技企业上市承接机制与新消费企业IPO审核指引落地</td><td>AI黑箱高频共振策略受限；微盘纯题材连板继续受两所重点监控压制；真硬科技（AI、具身智能、商业航天）与新消费龙头迎制度红利</td></tr>")
    h3.append("</table></body></html>")
    open(os.path.join(HTML_DIR, "03_wuqing_latest_decode.html"), "w", encoding="utf-8").write("\n".join(h3))
    print("Generated 02_perturbation_grids_and_chairmen.html and 03_wuqing_latest_decode.html")


if __name__ == "__main__":
    build_doc02_and_doc03()
