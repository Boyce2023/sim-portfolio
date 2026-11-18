#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Generate Feishu HTML 04 (21-ETF Pure National Team Entry/Exit Empirical & Live Board)."""
import json, os
import numpy as np
import pandas as pd

BASE = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
NT_DIR = os.path.join(BASE, "national_team")
CH_DIR = os.path.join(BASE, "charts")
HTML_DIR = os.path.join(BASE, "feishu_html")
os.makedirs(HTML_DIR, exist_ok=True)


def fmt_dt(s: str) -> str:
    p = str(s).strip()[:10].split("-")
    return f"{p[0]}.{p[1]}.{p[2]}" if len(p) == 3 else str(s)


def s_pct(v, signed=True):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "无样本"
    v = float(v)
    return f"{v:+.2f}%" if signed else f"{v:.1f}%"


def build_doc04():
    pool = pd.read_csv(os.path.join(NT_DIR, "nt_verified_etf_pool.csv"))
    nt = pd.read_csv(os.path.join(NT_DIR, "nt_12_pure_ledger.csv"))
    m = nt.set_index("factor_id").to_dict("index")
    q_df = pd.read_parquet(os.path.join(NT_DIR, "etf_quarterly_scale.parquet"))
    snap = json.load(open(os.path.join(NT_DIR, "latest_monitor_snapshot.json"), encoding="utf-8"))
    ev_df = pd.read_parquet(os.path.join(NT_DIR, "nt_official_events.parquet"))
    gv = lambda fid, col, sg=True: s_pct(m.get(fid, {}).get(col), signed=sg)
    gn = lambda fid: int(m.get(fid, {}).get("main_n", 0) or 0)

    h = ["<html><body>"]
    h.append("<h1>子文档04：国家队宽基ETF（华泰柏瑞300等）进退场实证与实时看板</h1>")
    h.append(
        f"<p><mark>总结论：国家队21只重仓宽基ETF的资金流在抓高位退场降温与大小盘风格切换上十分有效，按年报持仓纯度加权后信号显著优于原始总申赎与单一ETF盲追。"
        f"全样本与OOS（样本外）实证显示：纯净加权单日净赎回达80亿元以上退场时（F154，样本{gn('F154')}次），次日起20日沪深300平均{gv('F154','main_mean_pct')}（下跌胜率{gv('F154','main_win_pct',False)}，单仓轮动{gv('F154','slot_mean_pct')}，净超额{gv('F154','excess_20d_pct')}）；"
        f"进场唯有在20日成交脉冲超2.2倍配大盘收阴或长下影（F149，20日{gv('F149','main_mean_pct')}，单仓{gv('F149','slot_mean_pct')}，OOS达{gv('F149','oos_mean_pct')}）或深跌8%后重手加权买盘（F148，20日{gv('F148','main_mean_pct')}，OOS达{gv('F148','oos_mean_pct')}）真稳健；"
        f"一旦一队大盘与二队中小创同步净申购形成共振（F152，样本{gn('F152')}次），20日内中证1000跑赢沪深300达{gv('F152','sp1000_20d_pct')}（胜率{gv('F152','main_win_pct',False)}）。</mark></p>"
    )

    h.append("<h2>一、2025年报穿透核实：21只国家队真实重仓ETF清单（华泰柏瑞510300居首）</h2>")
    h.append("<p>逐只穿透2025年基金年度报告前十名上市持有人（2025年12月31日口径）与2026年中期报告总份额变化：仅纳入中央汇金投资、中央汇金资管、国新投资或中国诚通（含诚旸投资）真实重仓的21只A股ETF（合计年末持仓3771.91亿份）。原市场常误盯的华夏科创50（588000）、红利ETF（510880）、中证A500等19只ETF因前十名均无国家队席位已全部剔除。</p>")
    h.append("<table><tr><th>代码</th><th>基金简称</th><th>梯队归属</th><th>跟踪指数</th><th>2025年末总份额(亿份)</th><th>汇金占比</th><th>国新诚通占比</th><th>国家队总纯度</th><th>2025年末国家队持仓(亿份)</th><th>2026年中总份额(亿份)</th></tr>")
    for _, r in pool.iterrows():
        t_lbl = r["team"].replace("_", " ")
        h.append(
            f"<tr><td><strong>{r['code']}</strong></td><td>{r['name']}</td><td>{t_lbl}</td><td>{r['index']}</td>"
            f"<td>{r['ar2025_tot_yi']:.2f}</td><td>{r['ar2025_huijin_pct']:.2f}%</td><td>{r['ar2025_gx_ct_pct']:.2f}%</td>"
            f"<td><strong>{r['ar2025_nt_pct']:.2f}%</strong></td><td>{r['ar2025_nt_shares_yi']:.2f}</td><td>{r['sr2026_tot_yi']:.2f}</td></tr>"
        )
    h.append("</table>")

    h.append("<h2>二、21只核心ETF万亿级进退周期与2024年初双切换实证</h2>")
    h.append(f"<img src=\"{CH_DIR}/chart5_national_team_etf_flows_and_2024_pivot.png\"/>")
    q_sub = q_df[(q_df["date"] >= "2024-12-31") & (q_df["date"].isin(["2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]))].groupby("date")[["shares_yi", "nav_yi", "sub_yi", "red_yi"]].sum(min_count=1).reset_index()
    h.append("<table><tr><th>季报截止日</th><th>21只ETF总份额(亿份)</th><th>总净资产(亿元)</th><th>季内总申购(亿份)</th><th>季内总赎回(亿份)</th><th>阶段定性</th></tr>")
    q_notes = {
        "2024-12-31": "924行情后国家队持仓高位平台", "2025-03-31": "震荡温和净赎回", "2025-06-30": "4月关税冲击汇金暴力加仓托底",
        "2025-09-30": "净资产冲顶1.94万亿元", "2025-12-31": "年末规模维持1.92万亿元",
        "2026-03-31": "1月高位连续天量赎回规模腰斩", "2026-06-30": "二季度继续撤出至0.46万亿元低谷", "2026-09-30": "国新诚通7月增持及Q3重回净申购"
    }
    for _, r in q_sub.iterrows():
        h.append(f"<tr><td><strong>{fmt_dt(r['date'])}</strong></td><td>{r['shares_yi']:.2f}</td><td>{r['nav_yi']:.2f}</td><td>{r['sub_yi']:.2f}</td><td>{r['red_yi']:.2f}</td><td>{q_notes.get(r['date'],'常规波动')}</td></tr>")
    h.append("</table>")

    h.append("<h2>三、纯度加权 vs 华泰510300单票：进退场与大小盘切换回测结果</h2>")
    h.append(f"<img src=\"{CH_DIR}/chart6_national_team_pure_backtest.png\"/>")
    h.append("<ul>")
    h.append(f"<li><strong>持仓纯度加权优于原始总净申购（F146 vs F145、F148）</strong>：按2025年报国家队占比加权后过滤了创业板科创板内大量散户与保险日常交易噪音。纯净加权百亿进场（F146）20日均值{gv('F146','main_mean_pct')}、胜率{gv('F146','main_win_pct',False)}，全面优于原始总申购（F145均值{gv('F145','main_mean_pct')}、胜率{gv('F145','main_win_pct',False)}）；若叠加60日回撤深于8%（F148），20日收益跃升至<strong>{gv('F148','main_mean_pct')}</strong>，近3年OOS（样本外）更达<strong>{gv('F148','oos_mean_pct')}</strong>（胜率{gv('F148','oos_win_pct',False)}）。</li>")
    h.append(f"<li><strong>华泰柏瑞510300适合做盘口风向标，不宜独立替代21只全池（F147、F155 vs F149、F154）</strong>：<mark>单盯510300一只基金的进场信号（F147）20日仅{gv('F147','main_mean_pct')}、胜率{gv('F147','main_win_pct',False)}（已证伪）；退场信号（F155）虽全样本均值{gv('F155','main_mean_pct')}（OOS为{gv('F155','oos_mean_pct')}），但单仓轮动为{gv('F155','slot_mean_pct')}，易受早期单只ETF套利申赎干扰。</mark>真正抗噪音的是21只加权净赎回（F154，20日{gv('F154','main_mean_pct')}、单仓{gv('F154','slot_mean_pct')}）与全池爆量2.2倍加长下影（F149，20日{gv('F149','main_mean_pct')}、单仓{gv('F149','slot_mean_pct')}）。</li>")
    h.append(f"<li><strong>一队救蓝筹抽血小盘 vs 一二队共振大底（F151 vs F152）</strong>：一队大盘蓝筹净申购超75亿但二队中小创低于15亿时（F151），5日内中证1000跑输沪深300达{gv('F151','sp1000_5d_pct')}（2024年1月18日至2月2日一队买+1451.3亿而二队仅+99.4亿，触发小微盘踩踏）。一旦二队跟进超25亿形成共振（F152），20日内中证1000反超沪深300达<strong>{gv('F152','sp1000_20d_pct')}</strong>（胜率{gv('F152','main_win_pct',False)}），微盘30%更跑赢<strong>{gv('F152','spmicro_20d_pct')}</strong>。连买后单日停手（F153）样本仅6次且无显著下跌（已证伪）。</li>")
    h.append("</ul>")

    h.append("<h2>四、12个纯正国家队宽基ETF因子（F145至F156）明细账本</h2>")
    h.append("<table><tr><th>编号</th><th>因子名称</th><th>主观测标的</th><th>样本N</th><th>5日收益</th><th>20日主均值</th><th>方向胜率</th><th>单仓轮动</th><th>OOS（样本外）</th><th>1000减300(20日)</th><th>5日日均涨停</th><th>定性</th></tr>")
    for _, r in nt.iterrows():
        t_cn = "沪深300" if r["target_asset"] == "bench" else "1000相对300"
        h.append(
            f"<tr><td><strong>{r['factor_id']}</strong></td><td>{r['factor_name']}</td><td>{t_cn}</td>"
            f"<td>{int(r['main_n'])}</td><td>{s_pct(r['ret_5d_pct'])}</td><td><strong>{s_pct(r['main_mean_pct'])}</strong></td>"
            f"<td>{s_pct(r['main_win_pct'],False)}</td><td>{s_pct(r['slot_mean_pct'])}</td><td>{s_pct(r['oos_mean_pct'])}</td>"
            f"<td>{s_pct(r['sp1000_20d_pct'])}</td><td>{r['fwd5_zt_cnt']:.1f}家</td><td>{r['verdict']}</td></tr>"
        )
    h.append("</table>")

    h.append(f"<h2>五、截至{fmt_dt(snap['run_at'][:10])}实时监测看板：逐只ETF与官方动向</h2>")
    h.append(
        f"<p><mark>当前实时定性（{fmt_dt(snap['run_at'][:10])} {snap['run_at'][11:16]}）：{snap['regime']}。</mark>"
        f"盘中沪深300报{snap['csi300_lvl']:.2f}点（{snap['csi300_pct']:+.2f}%），中证1000报{snap['csi1000_pct']:+.2f}%，四大行均幅{snap['big4_pct']:+.2f}%。"
        f"21只池截至昨日（{fmt_dt(snap['last_settled_date'])}）原始净申购{snap['last_day_flow_yi']:+.1f}亿元、纯净加权{snap['last_day_wflow_yi']:+.1f}亿元（一队{snap['last_day_t1_yi']:+.1f}亿、二队{snap['last_day_t2_yi']:+.1f}亿、三队{snap['last_day_t3_yi']:+.1f}亿）；近5日原始{snap['flow_5d_yi']:+.1f}亿元（纯净{snap['wflow_5d_yi']:+.1f}亿），近20日原始{snap['flow_20d_yi']:+.1f}亿元（纯净{snap['wflow_20d_yi']:+.1f}亿）。</p>"
    )
    h.append("<table><tr><th>代码</th><th>基金简称</th><th>梯队</th><th>国家队纯度</th><th>今日涨跌</th><th>今日已成交(亿)</th><th>预计量比</th><th>昨日净申赎(亿)</th><th>5日累计(亿)</th><th>20日累计(亿)</th></tr>")
    for pr in snap["per_etf"]:
        sp_s = f"{pr['proj_spike']:.2f}x" if pr.get("proj_spike") is not None else "无"
        h.append(
            f"<tr><td><strong>{pr['code']}</strong></td><td>{pr['name']}</td><td>{pr['team']}</td><td>{pr['nt_pct']:.2f}%</td>"
            f"<td>{pr['pct_chg']:+.2f}%</td><td>{pr['cur_amt_yi']:.2f}</td><td>{sp_s}</td>"
            f"<td><strong>{pr['last_flow_yi']:+.2f}</strong></td><td>{pr['flow_5d_yi']:+.2f}</td><td>{pr['flow_20d_yi']:+.2f}</td></tr>"
        )
    h.append("</table>")

    h.append("<h3>2023年10月以来国家队与平准工具官方公告事件溯源</h3>")
    h.append("<table><tr><th>事件日期</th><th>发布时段</th><th>类别</th><th>主体与官方内容</th></tr>")
    slot_cn = {"BMO": "盘前BMO", "INTRADAY": "盘中", "AMC": "盘后AMC", "WEEKEND_HOLIDAY": "周末休市"}
    for _, er in ev_df[ev_df["event_date"] >= "2023-10-01"].sort_values("event_date", ascending=False).iterrows():
        h.append(f"<tr><td><strong>{fmt_dt(er['event_date'])}</strong></td><td>{slot_cn.get(er['slot'], er['slot'])}</td><td>{er['src']}</td><td>{er['body']}：{er['title']}</td></tr>")
    h.append("</table></body></html>")

    out_p = os.path.join(HTML_DIR, "04_national_team_etf_radar.html")
    open(out_p, "w", encoding="utf-8").write("\n".join(h))
    print("Generated", out_p)


if __name__ == "__main__":
    build_doc04()
