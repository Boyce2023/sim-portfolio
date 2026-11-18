#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Upgrade 00_main_csrc_report.html cleanly to 156 factors (144 speech + 12 pure NT 21-ETF factors, zero Not Sell)."""
import json, os, re
import pandas as pd

BASE = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
OLD_00 = os.path.join(BASE, "_archive/20261116_shards_and_logs/feishu_html/00_main_csrc_report.html")
NT_DIR = os.path.join(BASE, "national_team")
CH_DIR = os.path.join(BASE, "charts")
OUT_00 = os.path.join(BASE, "feishu_html/00_main_csrc_report.html")


def upgrade_main():
    raw = open(OLD_00, "r", encoding="utf-8").read()
    raw = re.sub(r"涨(\d+(?:\.\d+)?%)", r"+\1", raw)
    raw = re.sub(r"跌(\d+(?:\.\d+)?%)", r"-\1", raw)
    raw = raw.replace("沪深300-", "沪深300为-").replace("。；", "；")
    raw = raw.replace("144因子", "156因子").replace("144个颗粒度因子", "156个颗粒度因子")
    raw = raw.replace(
        "在全部144个细拆因子中，通过跨周期与单仓轮动检验的<strong>有效核心因子共22个</strong>，<strong>条件或弱有效因子共19个</strong>，<strong>低频高胜率事件共0个</strong>，同时诚实证伪了<strong>无效或诱多陷阱因子103个</strong>",
        "在原有144个发言因子叠加新增12个国家队宽基ETF进退场因子共156个细拆因子中，通过跨周期与单仓轮动检验的<strong>有效核心因子共29个</strong>，<strong>条件或弱有效因子共21个</strong>，同时诚实证伪了<strong>无效或诱多陷阱因子106个</strong>"
    )

    nt = pd.read_csv(os.path.join(NT_DIR, "nt_12_pure_ledger.csv")).set_index("factor_id")
    snap = json.load(open(os.path.join(NT_DIR, "latest_monitor_snapshot.json"), encoding="utf-8"))
    dt_s = snap["run_at"][:10].replace("-", ".")
    st_s = snap["last_settled_date"].replace("-", ".")
    r300 = [x for x in snap["per_etf"] if x["code"] == "510300"][0]

    nt_add = (
        f"新增21只国家队重仓宽基ETF进退场监测模块实证证明：按2025年报持仓纯度加权后，单日净赎回超80亿元退场预警十分灵敏（20日{nt.loc['F154','main_mean_pct']:+.2f}%，下跌胜率{nt.loc['F154','main_win_pct']:.1f}%，单仓轮动{nt.loc['F154','slot_mean_pct']:+.2f}%）；"
        f"进场须看爆量2.2倍加长下影（20日{nt.loc['F149','main_mean_pct']:+.2f}%，单仓{nt.loc['F149','slot_mean_pct']:+.2f}%）或深跌8%加权扫货（OOS近3年{nt.loc['F148','oos_mean_pct']:+.2f}%），"
        f"且一队大盘与二队中小创共振买入时20日内中证1000跑赢沪深300达{nt.loc['F152','sp1000_20d_pct']:+.2f}%（胜率{nt.loc['F152','main_win_pct']:.1f}%）。"
    )
    raw = raw.replace("</mark></p>", nt_add + "</mark></p>", 1)

    sec5 = [
        "<h2>五、国家队21只重仓宽基ETF（华泰柏瑞300等）进退场实证及实时看板</h2>",
        f"<p><mark>核心结论：21只年报穿透核实的国家队重仓ETF按持仓占比加权后，退场预警与一二队风格切换均达到核心有效标准。截至{dt_s}实时雷达显示：{snap['regime']}（昨日{st_s}全池净申购{snap['last_day_flow_yi']:+.1f}亿元，其中纯净加权{snap['last_day_wflow_yi']:+.1f}亿元，头号标杆华泰柏瑞510300净申购{r300['last_flow_yi']:+.1f}亿元）。</mark></p>",
        f"<img src=\"{CH_DIR}/chart5_national_team_etf_flows_and_2024_pivot.png\"/>",
        f"<img src=\"{CH_DIR}/chart6_national_team_pure_backtest.png\"/>",
        "<ul>",
        f"<li><strong>2025年报穿透锁定21只真仓池并剔除19只伪标的</strong>：华泰柏瑞300（510300，国家队纯度82.96%）、易方达300（85.49%）、华夏300（89.14%）、嘉实300（87.66%）、华夏上证50（86.05%）与华安上证180（91.93%）领衔一队，广发1000（91.86%）、南方1000（86.43%）、华夏1000（86.15%）、富国1000（85.74%）、南方500（75.91%）、易方达创业板（54.03%）及易方达科创50（41.95%）构成二队，南方央企科技引领（66.30%）为三队国新代表；原华夏科创50（588000）等前十无国家队席位已剔除。</li>",
        f"<li><strong>纯度加权退场预警显著优于单盯510300与盲追进场</strong>：按持仓纯度加权单日净赎回达80亿以上（F154，样本{int(nt.loc['F154','main_n'])}次），次日起20日沪深300平均<strong>{nt.loc['F154','main_mean_pct']:+.2f}%</strong>（单仓<strong>{nt.loc['F154','slot_mean_pct']:+.2f}%</strong>，60日{nt.loc['F154','ret_60d_pct']:+.2f}%），如2026年1月15日至29日连续十一日纯净加权净赎回7620.6亿元即精准对应高位降温。单盯510300进场（F147单仓{nt.loc['F147','slot_mean_pct']:+.2f}%）易吃飞刀，进场须盯全池爆量2.2倍配长下影（F149，20日{nt.loc['F149','main_mean_pct']:+.2f}%，OOS达{nt.loc['F149','oos_mean_pct']:+.2f}%）或深跌8%加权扫货（F148，OOS达{nt.loc['F148','oos_mean_pct']:+.2f}%）。</li>",
        f"<li><strong>一队抽血小盘 vs 一二队共振反转</strong>：国家队只买一队蓝筹超75亿但二队低于15亿时（F151），5日内中证1000跑输沪深300达<strong>{nt.loc['F151','sp1000_5d_pct']:+.2f}%</strong>；一旦二队中小创同步净申购超25亿形成共振（F152），20日内中证1000反超沪深300达<strong>{nt.loc['F152','sp1000_20d_pct']:+.2f}%</strong>（胜率{nt.loc['F152','main_win_pct']:.1f}%），微盘30%更跑赢<strong>{nt.loc['F152','spmicro_20d_pct']:+.2f}%</strong>。</li>",
        "</ul>",
        "<p>完整21只ETF持仓穿透明细表、12个国家队因子账本及今日逐只ETF实时资金流明细请参阅下方子文档04。</p>",
    ]
    raw = raw.replace("</body></html>", "\n".join(sec5) + "\n</body></html>")
    open(OUT_00, "w", encoding="utf-8").write(raw)
    print("Upgraded", OUT_00)


if __name__ == "__main__":
    upgrade_main()
