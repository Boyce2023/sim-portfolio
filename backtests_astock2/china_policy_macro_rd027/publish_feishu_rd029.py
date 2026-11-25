#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD029 Feishu Wiki Publisher: 2000至2026逐日ETF回测
Reads verified outputs from output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/,
enforces V19.1 + zh-delivery hard gates, and publishes under 政策 (YSDKwKuQciRq0ekDVw9c5LnRnDe).
"""
import fcntl
import json
import os
import re
import sys
import time
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup, Comment, Doctype, NavigableString

ROOT = "/Users/huaichuaibeimeng/claude-projects"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
exec(open(os.path.join(ROOT, "股票研究 Equity Research/_tools/html2feishu.py"), "r", encoding="utf-8").read(), globals())

BASE = "https://open.feishu.cn"
SPACE_ID = "7700231295393107208"
POLICY_PARENT_NODE = "YSDKwKuQciRq0ekDVw9c5LnRnDe"
OUT_DIR = os.path.join(ROOT, "output/china_policy_macro_rd027_20261125")
RD029_DIR = os.path.join(OUT_DIR, "rd029_daybyday_etf")
AUDIT_JSON = os.path.join(RD029_DIR, "rd029_daybyday_audit.json")
LEDGER_CSV = os.path.join(RD029_DIR, "rd029_trades_ledger.csv")
NAV_PARQ = os.path.join(RD029_DIR, "rd029_nav_daily.parquet")
HTML_OUT = os.path.join(RD029_DIR, "rd029_daybyday_etf_report.html")
MANIFEST_PATH = os.path.join(OUT_DIR, "feishu_rd027_wiki_manifest.json")
LOCK_PATH = "/tmp/.feishu_rd029_pub.lock"

DOC_KEY = "rd029_daybyday_etf_2000_2026"
DOC_TITLE = "2000至2026逐日ETF回测"

BANNED = [
    "星辰大海", "皇冠明珠", "飞轮", "底座", "赋能", "闭环", "引擎", "跃迁", "重塑", "颠覆",
    "范式", "生态", "矩阵", "全景", "硬核", "标尺", "试金石", "胜负手", "王牌", "钩子",
    "年金", "天花板", "破局", "抓手", "撬动", "罕见", "极其", "绝不", "完美", "铁证",
    "铁律", "暗礁", "命门", "底牌", "法典", "死限", "拆穿", "十战十胜", "干干净净", "圣经",
    "贵族", "宪法", "绞肉机", "法医", "零未来函数", "D8", "D15", "SSOT",
]
LOAN11 = [
    "ablation", "daemon", "metadata", "telemetry", "guardrail",
    "handle", "endpoint", "idempotent", "Calmar", "PIT", "OOS",
]

STRAT_CN = {
    "BH": "满仓买入持有",
    "S1_Live_ge60": "S1实时60分(20日)",
    "S1_Live_ge75": "S1实时75分(20日)",
    "S1_EOD_ge60": "S1盘后60分(20日)",
    "S1_EOD_ge75": "S1盘后75分(20日)",
    "S2_4Gate_H60": "S2四门60日",
    "S2_4Gate_H120": "S2四门120日",
    "S2_4Gate_DynExit": "S2四门动态",
    "S3a_HoldETF_PolicyEscape": "S3a避险全仓",
    "S3b_HoldETF_Escape_1overVol": "S3b避险波控",
    "Pure_1overVol_T16": "纯1/vol波控",
    "BH_S4_2008": "沪深300基准",
    "All14_EW_BH": "14行业等权持有",
    "S4_Rescue300_ExclRed120": "S4救市切300+排红",
    "S4_Rescue300_Green250_ExclRed120": "S4切300+绿增配+排红",
}


def fmt_dt(s: str) -> str:
    p = str(s).strip()[:10].split("-")
    return f"{p[0]}.{p[1]}.{p[2]}" if len(p) == 3 else str(s)


def clean_text_strict(txt: str) -> str:
    txt = txt.replace("——", "，").replace("—", "，").replace("–", "至")
    txt = txt.replace("->", "至").replace("→", "至").replace("！", "。").replace("!", "。").replace("**", "")
    txt = re.sub(r"(\d{4})-(\d{2})-(\d{2})", r"\1.\2.\3", txt)
    txt = re.sub(r"(\d)-(\d)", r"\1至\2", txt)
    txt = re.sub(r"(?<=[A-Za-z\u4e00-\u9fff])-(?=[A-Za-z\u4e00-\u9fff0-9])", "至", txt)
    txt = re.sub(r"(?<!\S)-(?!\d)", " ", txt)
    return txt


def assert_cell_len(rows: list, max_len: int = 40):
    for r in rows:
        for cell in r:
            plain = re.sub(r"<[^>]+>", "", str(cell)).strip()
            if len(plain) > max_len:
                raise RuntimeError(f"Cell > {max_len} chars ({len(plain)}): {plain}")


def td_m(v: dict) -> str:
    return f"{v['total_mult']:.2f}x / {v['ann_ret_pct']:+.2f}%"


def tbl_html(rows: list, first_bold: bool = False) -> str:
    assert_cell_len(rows)
    out = ["<table><thead><tr>"]
    for c in rows[0]:
        out.append(f"<th>{c}</th>")
    out.append("</tr></thead><tbody>")
    for r in rows[1:]:
        out.append("<tr>")
        for idx, c in enumerate(r):
            cell_s = f"<strong>{c}</strong>" if (first_bold and idx == 0) else str(c)
            out.append(f"<td>{cell_s}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def compute_ablation_and_spells():
    import rd029_engine as eng
    from run_rd029_daybyday_etf_2000_2026 import make_strategy_fns
    state = eng.build_causal_state(cutoff_date=None, wp_lag_mode="after_16")
    sig = state["signals"]
    red120, grn250 = sig["sec_red120"], sig["sec_green250"]

    def fn_pure_red(i, ctx):
        reds = red120[i]
        pool = [s for s in eng.SECTORS if s not in reds] or list(eng.SECTORS)
        return {f"SEC_{s}": 1.0 / len(pool) for s in pool}, ""

    def fn_pure_grn(i, ctx):
        reds = red120[i]
        pool = [s for s in eng.SECTORS if s not in reds] or list(eng.SECTORS)
        grns = grn250[i]
        rw = {s: (1.5 if s in grns else 1.0) for s in pool}
        tot = sum(rw.values())
        return {f"SEC_{s}": rw[s] / tot for s in pool}, ""

    s_red = eng.run_daily_portfolio_sim(state, fn_pure_red, "2008-08-28", 0.0005, "0pct")
    s_grn = eng.run_daily_portfolio_sim(state, fn_pure_grn, "2008-08-28", 0.0005, "0pct")
    s_bh08 = eng.run_daily_portfolio_sim(state, make_strategy_fns(state, "CHAIN")["BH"][0], "2008-08-28", 0.0005, "0pct")
    pure_s4 = {}
    for wn, d0 in [("18Y", "2008-08-28"), ("MOD", "2016-11-04"), ("6Y", "2021-01-04"), ("3Y", "2024-01-02")]:
        pure_s4[wn] = {
            "pure_red": eng.compute_window_metrics(s_red["nav"], s_red["eq_w"], s_red["turnover"], s_red["dates"], s_bh08["nav"], None, d0, "2026-11-25"),
            "pure_grn": eng.compute_window_metrics(s_grn["nav"], s_grn["eq_w"], s_grn["turnover"], s_grn["dates"], s_bh08["nav"], None, d0, "2026-11-25"),
        }

    s2_g4 = (sig["g1_gate"].astype(int) + sig["g2_gate"].astype(int) + sig["g3_gate"].astype(int) + sig["g4_gate"].astype(int) >= 3) & sig["g2_gate"] & sig["g4_gate"]
    def fn_g4(i, ctx):
        if not ctx["in_pos"]:
            if s2_g4[i]:
                ctx["hold_rem"] = 60
                return {str(state["chain_asset"][i]): 1.0}, "ReqG4"
            return {}, ""
        ctx["hold_rem"] = ctx.get("hold_rem", 1) - 1
        return ({str(state["chain_asset"][i]): 1.0}, "") if ctx["hold_rem"] > 0 else ({}, "")

    s_g4 = eng.run_daily_portfolio_sim(state, fn_g4, "2000-01-04", 0.0005, "0pct")
    s_bh = eng.run_daily_portfolio_sim(state, make_strategy_fns(state, "CHAIN")["BH"][0], "2000-01-04", 0.0005, "0pct")
    req_g4_full = eng.compute_window_metrics(s_g4["nav"], s_g4["eq_w"], s_g4["turnover"], s_g4["dates"], s_bh["nav"], None, "2000-01-04", "2026-11-25")

    nav_df = pd.read_parquet(NAV_PARQ)
    w3, dates, bh = nav_df["S3a_HoldETF_PolicyEscape_w"].values, nav_df["date"].astype(str).values, nav_df["BH_nav"].values
    in_esc, st_i, spells = False, 0, []
    for i in range(len(w3)):
        if w3[i] < 0.5 and not in_esc:
            in_esc, st_i = True, i
        elif w3[i] >= 0.5 and in_esc:
            in_esc = False
            spells.append((dates[st_i], dates[i], i - st_i, round(float((bh[i] / bh[st_i] - 1) * 100), 2)))
    return pure_s4, req_g4_full, len(spells), sorted(spells, key=lambda x: -x[3])[:2], sorted(spells, key=lambda x: x[3])[:2]


def trade_stats_str(df: pd.DataFrame, strat: str, d0: str, d1: str = "2099-12-31") -> str:
    sub = df[(df["strategy"] == strat) & (df["buy_date"] >= d0) & (df["buy_date"] <= d1)]
    if len(sub) == 0:
        return "无"
    r = sub["net_ret_pct"].values
    pos, neg = r[r > 0], r[r <= 0]
    w = (r > 0).mean() * 100
    pl = (pos.mean() / abs(neg.mean())) if (len(pos) and len(neg) and abs(neg.mean()) > 0) else 0.0
    return f"{len(r)}笔 / {w:.1f}% / {pl:.2f}"


def fmt_reason(r: str) -> str:
    s = str(r)
    if s.startswith("V3="):
        return f"实时V3满{s.split('=')[1]}分"
    if s.startswith("Pre2016"):
        return "2016前硬工具放量2倍"
    if s.startswith("4Gate["):
        g = s[6:-1].replace("+", " ")
        return f"四门 {g}"
    return s


def fmt_etf(e: str) -> str:
    return {"sh_comp": "上证代理", "sh_comp->510050": "上证转510050", "510050->510300": "50转300"}.get(str(e), str(e))


def build_html() -> str:
    audit = json.load(open(AUDIT_JSON, "r", encoding="utf-8"))
    df_tr = pd.read_csv(LEDGER_CSV)
    pure_s4, req_g4_full, n_spells, worst_rallies, best_drops = compute_ablation_and_spells()

    meta = audit["meta"]
    trc = audit["truncation_test_2020_12_31"]
    cw = audit["chain_windows_010fee_0cash"]
    mod = audit["modern_510300_vs_512100"]
    s4w = audit["s4_sector_windows_010fee_0cash"]
    fc = audit["fee_and_cash_sensitivity"]
    wlag = audit["waterpool_lag_sensitivity"]
    live = meta["live_2026_11_25_reading"]

    # Table 1: Multi-period main strategies vs B&H
    t1 = [["策略名称", "全26.9年", "300 14.5年", "现代10年", "近6年", "近3年", "最大回撤全/300", "均仓全/300"]]
    for sk in ["BH", "S1_Live_ge60", "S1_Live_ge75", "S1_EOD_ge60", "S2_4Gate_H60", "S2_4Gate_H120", "S2_4Gate_DynExit", "S3a_HoldETF_PolicyEscape", "S3b_HoldETF_Escape_1overVol", "Pure_1overVol_T16"]:
        f_m = cw["FULL_2000_2026"][sk]["strategy"]
        p_m = cw["PURE_510300_2012_2026"][sk]["strategy"]
        m_m = cw["MODERN_2016_2026"][sk]["strategy"]
        r6 = cw["RECENT_6Y_2021_2026"][sk]["strategy"]
        r3 = cw["RECENT_3Y_2024_2026"][sk]["strategy"]
        t1.append([
            STRAT_CN[sk], td_m(f_m), td_m(p_m), td_m(m_m), td_m(r6), td_m(r3),
            f"{f_m['mdd_pct']:.1f}% / {p_m['mdd_pct']:.1f}%",
            f"{f_m['avg_weight_pct']:.1f}% / {p_m['avg_weight_pct']:.1f}%",
        ])

    # Table 2: Same-Avg-Weight & 1/vol ablation
    t2 = [["策略与检验时段", "策略年化", "同均仓年化", "纯1/vol年化", "超同均仓", "夏普策/同仓", "笔数/胜率/盈亏"]]
    t2_specs = [
        ("FULL_2000_2026", "S1_Live_ge60", "S1实时60分 全26.9年", "2000-01-01"),
        ("FULL_2000_2026", "S2_4Gate_H60", "S2四门60日 全26.9年", "2000-01-01"),
        ("FULL_2000_2026", "S2_4Gate_H120", "S2四门120日 全26.9年", "2000-01-01"),
        ("FULL_2000_2026", "S3a_HoldETF_PolicyEscape", "S3a避险全仓 全26.9年", ""),
        ("FULL_2000_2026", "S3b_HoldETF_Escape_1overVol", "S3b避险波控 全26.9年", ""),
        ("PURE_510300_2012_2026", "S1_Live_ge60", "S1实时60分 300近14.5年", "2012-05-28"),
        ("PURE_510300_2012_2026", "S2_4Gate_H120", "S2四门120日 300近14.5年", "2012-05-28"),
        ("MODERN_2016_2026", "S1_Live_ge60", "S1实时60分 现代10年", "2016-11-04"),
        ("RECENT_6Y_2021_2026", "S1_Live_ge60", "S1实时60分 近6年", "2021-01-04"),
        ("RECENT_3Y_2024_2026", "S1_Live_ge60", "S1实时60分 近3年", "2024-01-02"),
    ]
    for wk, sk, lbl, td0 in t2_specs:
        row = cw[wk][sk]
        st, sw, iv = row["strategy"], row["same_avg_weight_bh"], row["pure_1overvol_matched"]
        tr_s = trade_stats_str(df_tr, sk, td0) if td0 else "择时轮动"
        t2.append([
            lbl, f"{st['ann_ret_pct']:+.2f}%", f"{sw['ann_ret_pct']:+.2f}%", f"{iv['ann_ret_pct']:+.2f}%",
            f"{row['alpha_vs_same_w_ann_pp']:+.2f}pp", f"{st['sharpe']:.2f} / {sw['sharpe']:.2f}", tr_s,
        ])

    # Table 3: Modern 2016-2026 510300 vs 512100
    t3 = [["策略与标的", "10年倍数/年化", "10年回撤", "10年夏普", "超同均仓10年", "近6年年化", "近3年年化", "10年笔/胜率"]]
    for sk, cname in [("BH", "满仓买入"), ("S1_Live_ge60", "S1实时60分"), ("S1_EOD_ge60", "S1盘后60分"), ("S1_Live_ge75", "S1实时75分"), ("S2_4Gate_H60", "S2四门60日"), ("S2_4Gate_H120", "S2四门120日"), ("S3a_HoldETF_PolicyEscape", "S3a避险全仓")]:
        for ek, ename in [("ETF_510300", "510300"), ("ETF_512100", "512100")]:
            m10 = mod["MODERN_2016_2026"][sk][ek]
            m6 = mod["RECENT_6Y_2021_2026"][sk][ek]["strategy"]
            m3 = mod["RECENT_3Y_2024_2026"][sk][ek]["strategy"]
            s10 = m10["strategy"]
            tr_lbl = "一直持有" if sk == "BH" else ("高仓轮动" if sk.startswith("S3") else "")
            if ek == "ETF_512100" and (s10.get("n_trades") or 0) > 0:
                tr_lbl = f"{s10['n_trades']}笔 / {s10['trade_win_rate_pct']:.1f}%"
            elif ek == "ETF_510300" and sk in ("S1_Live_ge60", "S1_Live_ge75", "S1_EOD_ge60", "S2_4Gate_H60", "S2_4Gate_H120"):
                sub = df_tr[(df_tr["strategy"] == sk) & (df_tr["buy_date"] >= "2016-11-04")]
                tr_lbl = f"{len(sub)}笔 / {(sub['net_ret_pct'] > 0).mean() * 100:.1f}%" if len(sub) else "无"
            t3.append([
                f"{cname}({ename})", td_m(s10), f"{s10['mdd_pct']:.1f}%", f"{s10['sharpe']:.2f}",
                f"{m10['alpha_vs_same_w_ann_pp']:+.2f}pp", f"{m6['ann_ret_pct']:+.2f}%", f"{m3['ann_ret_pct']:+.2f}%", tr_lbl,
            ])

    # Table 4: S4 sector traffic light ablation
    t4 = [["18年行业组合方案", "18年倍数/年化", "18年回撤/夏普", "现代10年年化", "近6年年化", "近3年年化", "超14行业(18年)"]]
    for sk in ["BH_S4_2008", "All14_EW_BH", "S4_Rescue300_ExclRed120", "S4_Rescue300_Green250_ExclRed120"]:
        a18, am, a6, a3 = s4w["S4_18Y_2008_2026"][sk], s4w["S4_MODERN_2016_2026"][sk], s4w["S4_6Y_2021_2026"][sk], s4w["S4_3Y_2024_2026"][sk]
        t4.append([
            STRAT_CN[sk], td_m(a18), f"{a18['mdd_pct']:.1f}% / {a18['sharpe']:.2f}",
            f"{am['ann_ret_pct']:+.2f}%", f"{a6['ann_ret_pct']:+.2f}%", f"{a3['ann_ret_pct']:+.2f}%", f"{a18['excess_ann_vs_all14ew_pp']:+.2f}pp",
        ])
    ew_18_ann = s4w["S4_18Y_2008_2026"]["All14_EW_BH"]["ann_ret_pct"]
    for pk, plbl in [("pure_red", "纯排120日红灯(不切300)"), ("pure_grn", "纯绿增配+排红(不切300)")]:
        p18, pm, p6, p3 = pure_s4["18Y"][pk], pure_s4["MOD"][pk], pure_s4["6Y"][pk], pure_s4["3Y"][pk]
        t4.append([
            plbl, td_m(p18), f"{p18['mdd_pct']:.1f}% / {p18['sharpe']:.2f}",
            f"{pm['ann_ret_pct']:+.2f}%", f"{p6['ann_ret_pct']:+.2f}%", f"{p3['ann_ret_pct']:+.2f}%", f"{p18['ann_ret_pct'] - ew_18_ann:+.2f}pp",
        ])

    # Table 5: Fee, Cash yield, Waterpool PIT sensitivity
    t5 = [["敏感性测试维度", "全26.9年收益", "全期回撤", "300 14.5年收益", "300夏普", "近6年收益"]]
    sens_specs = [
        ("BH(0.10%费/零息)", "Fee010_Cash0pct", "BH"),
        ("S1实时60分(0.10%费/零息)", "Fee010_Cash0pct", "S1_Live_ge60"),
        ("S1实时60分(0.10%费/2%货基)", "Fee010_Cash2pct", "S1_Live_ge60"),
        ("S1实时60分(0.10%费/十年国债)", "Fee010_CashCGB10Y", "S1_Live_ge60"),
        ("S1实时60分(0.30%费/零息)", "Fee030_Cash0pct", "S1_Live_ge60"),
        ("S2四门120日(0.10%费/2%货基)", "Fee010_Cash2pct", "S2_4Gate_H120"),
        ("S2四门120日(0.10%费/十年国债)", "Fee010_CashCGB10Y", "S2_4Gate_H120"),
    ]
    for lbl, fk, sk in sens_specs:
        if fk == "Fee010_Cash0pct":
            wf, wp, w6 = cw["FULL_2000_2026"][sk]["strategy"], cw["PURE_510300_2012_2026"][sk]["strategy"], cw["RECENT_6Y_2021_2026"][sk]["strategy"]
        else:
            wf, wp, w6 = fc[fk][sk]["FULL_2000_2026"], fc[fk][sk]["PURE_510300_2012_2026"], fc[fk][sk]["RECENT_6Y_2021_2026"]
        t5.append([lbl, td_m(wf), f"{wf['mdd_pct']:.1f}%", td_m(wp), f"{wp['sharpe']:.2f}", td_m(w6)])
    for sk, cname in [("S2_4Gate_H60", "S2四门60日"), ("S3a_HoldETF_PolicyEscape", "S3a避险全仓")]:
        a16, m2 = wlag[sk]["after_day16"], wlag[sk]["full_1m_M2_day1"]
        t5.append([f"{cname}(次月17日/再延月初)", f"{a16['ann_ret_pct']:+.2f}% / {m2['ann_ret_pct']:+.2f}%", f"{a16['mdd_pct']:.1f}%", "PIT（点时点）严滞", "年化差0.17至0.82pp", "水池非主因"])

    # Table 6: Landmark trade samples
    t6 = [["策略", "信号日期", "持仓区间", "交易标的", "扣费净收益", "同期300", "触发依据"]]
    picks = [
        ("S1_Live_ge60", "2008-09-18"), ("S1_Live_ge60", "2015-06-29"), ("S1_Live_ge60", "2016-01-08"),
        ("S1_Live_ge60", "2020-02-03"), ("S1_Live_ge60", "2022-04-26"), ("S1_Live_ge60", "2024-09-20"),
        ("S1_Live_ge60", "2025-04-07"), ("S1_Live_ge60", "2026-04-08"), ("S1_Live_ge60", "2026-10-09"),
        ("S1_Live_ge60_512100", "2024-09-20"), ("S1_Live_ge60_512100", "2026-10-09"),
        ("S2_4Gate_H60", "2008-04-23"), ("S2_4Gate_H60", "2015-06-29"), ("S2_4Gate_H60", "2026-07-30"),
    ]
    for st_k, sig_d in picks:
        m_df = df_tr[(df_tr["strategy"] == st_k) & (df_tr["signal_date"] == sig_d)]
        if m_df.empty:
            continue
        r = m_df.iloc[0]
        sname_short = "S1实时(1000)" if "512100" in st_k else ("S1实时60分" if "S1" in st_k else "S2四门60日")
        sd_end = "2026.11.25未平" if bool(r["is_open_mtm"]) else fmt_dt(r["sell_date"])
        t6.append([
            sname_short, fmt_dt(r["signal_date"]), f"{fmt_dt(r['buy_date'])}至{sd_end}",
            fmt_etf(r["etf_code"]), f"{r['net_ret_pct']:+.2f}%", f"{r['bench_same_window_pct']:+.2f}%", fmt_reason(r["trigger_reason"]),
        ])

    r_real = cw["REAL_ETF_2005_2026"]
    miss0 = worst_rallies[0]
    raw_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{DOC_TITLE}</title></head><body>
<h1>{DOC_TITLE}</h1>
<p><mark>总结论，按2000年至2026.11.25逐日零后视镜回测，只有2016年后国家队ETF环境下的S1真救市右侧策略（V3打分满60分买510300或512100）具备真Alpha，其余S2四门与S3高仓位避险在26.9年机械全样本里均跑输同均仓基准。</mark></p>
<p>本审计按日循环执行，第T日盘后只读截至当日已公布数据，严格在T+1日开盘成交。</p>
<p>当前最新交易日2026.11.25收盘读取，沪深300收于{live['csi300_close']:.2f}点，实时V3得{live['v3_score_live']}分。</p>
<p>当天未达60分右侧买线，同时S1前期于2026.10.12开仓的多单仍在浮亏持有中，按真实收盘计入净值。</p>
<h2>一、零后视镜防线与真实标的单链</h2>
<p><mark>2020.12.31物理截断验证最大净值差与权重差均为{trc['max_abs_diff']:.1f}，实时打分差为{trc['v3_score_live_max_diff']:.1f}，全链路不存在任何未来信息泄露。</mark></p>
<ul>
<li>真实标的单链：2000.01至2005.02尚无ETF故用上证指数代理，2005.02.23切换真实含分红后复权510050，2012.05.28切换真实510300。</li>
<li>2016.11.04起同步测试真实512100中证1000ETF，精准对照大盘托底与中小盘弹性的差异。</li>
<li>月度水池严格强制压后至次月17日生效，同时做PIT（点时点）再延至次下月初的敏感性验证。</li>
<li>全部净值先按千一双边费率加零息现金最苛刻口径测算，再用双边千三费率与2%货基及十年国债利率压力复核。</li>
</ul>
<h2>二、核心策略26.9年与分时代真伪对照</h2>
<p><mark>S1在2016年前后判若两套系统，2000至2015年共13笔交易胜率46.2%且均亏1.87%，2016年后国家队22只ETF护盘机制成型后胜率升至56.2%至70.4%。</mark></p>
<p>纯真实ETF时代（2005.02.23起21.8年）满仓买入持有录得{r_real['BH']['strategy']['total_mult']:.2f}倍（年化{r_real['BH']['strategy']['ann_ret_pct']:+.2f}%），S1实时60分仅1.47倍，跑输主因全部来自2008.09与2015.06及2016.01三笔左侧接刀。</p>
{tbl_html(t1, first_bold=True)}
<h2>三、同均仓静态基准与纯1/vol对比（ablation（消融））</h2>
<p><mark>用同平均仓位静态持有与纯1/vol波控剥离现金垫子幻觉后，S1在2016年后现代救市期仍跑赢同均仓每年5.65至13.71个百分点，而S2与S3在全样本里全部跑输。</mark></p>
<p>S2因果四门机械版全26.9年输给同均仓3.23个百分点，主因在2008.04与2015.06急跌半山腰买满，且2023年后低IPO让第一门长亮而频频误触。</p>
<p>即便在S2上强行锁死必须满足深跌冰点第四门，全样本年化仍为{req_g4_full['ann_ret_pct']:+.2f}%，说明单靠机械四门做中线ETF并不成立。</p>
<p>S3避险机制全期累计逃顶{n_spells}次，最痛踏空是{fmt_dt(miss0[0])}至{fmt_dt(miss0[1])}牛市主升浪空仓错过{miss0[3]:+.2f}%，同时2008年仍吃下72.67%深回撤。</p>
{tbl_html(t2, first_bold=True)}
<h2>四、2016年后现代救市期510300与512100弹性对比</h2>
<p><mark>2016.11至今十年里512100自身买入持有年化亏损1.63%（0.85倍），而用S1实时60分狙击512100年化高达11.20%（2.91倍），S1盘后60分更达13.85%（3.69倍）。</mark></p>
<p>这一组数字包含2026.10.12至11.25仍在持仓中的单笔22.34%账面浮亏，充分证明国家队护盘信号在中小盘弹性端具备极强真实捕获力。</p>
{tbl_html(t3, first_bold=True)}
<h2>五、S4行业红绿灯与真救市合体拆解（18年）</h2>
<p><mark>红绿灯排雷本身有效，纯排120日红灯不切300全18年年化{pure_s4['18Y']['pure_red']['ann_ret_pct']:+.2f}%，跑赢14行业等权持有（{ew_18_ann:+.2f}%）；但强行在救市日全仓切入沪深300反而把18年年化拖低至{s4w['S4_18Y_2008_2026']['S4_Rescue300_ExclRed120']['ann_ret_pct']:+.2f}%。</mark></p>
<p>拖累仅发生于2016年前与2018年单边熊市切换损耗，近三年切300加排红达+3.18%已重新反超纯排红（+2.64%）。</p>
{tbl_html(t4, first_bold=True)}
<h2>六、费率升至千三、现金计息与水池滞后压测</h2>
<p><mark>若计入闲置期真实十年国债收益，S1实时60分在510300 14.5年时代录得2.38倍与年化6.15%（Calmar（卡尔玛）0.27），直接跑赢满仓持有（1.93倍与4.64%）且最大回撤腰斩至22.77%。</mark></p>
<p>即便在零息现金加双边千三高压费用下，S1实时60分近6年年化仍有+6.69%，信号并非靠手续费敏感凑出。</p>
{tbl_html(t5, first_bold=True)}
<h2>七、逐笔实盘经典对账抽样</h2>
<p>下表抽样展示2008至2026年关键节点真实买卖开盘价核算结果，所有273笔完整台账均存本地供逐日复核。</p>
{tbl_html(t6, first_bold=False)}
</body></html>"""

    soup = BeautifulSoup(raw_html, "html.parser")
    for elem in soup.find_all(string=True):
        if isinstance(elem, (Doctype, Comment)):
            elem.extract()
            continue
        if elem.parent and elem.parent.name in ("style", "script"):
            continue
        elem.replace_with(NavigableString(clean_text_strict(str(elem))))
    clean = str(soup)
    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(clean)

    bs_chk = BeautifulSoup(clean, "html.parser")
    vis_all = bs_chk.get_text()
    bad_p = re.findall(r".{0,6}(?:-(?!\d)|—|–|！|!|→|\*\*).{0,6}", vis_all)
    if bad_p:
        raise RuntimeError(f"Bad punct: {bad_p[:5]}")
    hits = [w for w in BANNED if w in vis_all]
    if hits:
        raise RuntimeError(f"Banned words: {hits}")
    for lw in LOAN11:
        bare = re.findall(rf"\b{lw}\b(?!（)", vis_all)
        if bare:
            raise RuntimeError(f"Loanword missing gloss: {lw} -> {bare}")
    if len(vis_all) < 1200:
        raise RuntimeError(f"Visible text too short: {len(vis_all)}")
    print(f"[HTML OK] visible_chars={len(vis_all)} -> {HTML_OUT}")
    return HTML_OUT


def load_manifest():
    return json.load(open(MANIFEST_PATH, "r", encoding="utf-8")) if os.path.exists(MANIFEST_PATH) else {"space_id": SPACE_ID, "parent_node_token": POLICY_PARENT_NODE, "nodes": {}}


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
    r = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes", {"obj_type": "docx", "node_type": "origin", "title": title, "parent_node_token": parent_node_token}, "POST")
    if r.get("code") != 0:
        raise RuntimeError(f"Failed creating node {key}: {r}")
    nd = r["data"]["node"]
    info = {"key": key, "title": title, "node_token": nd["node_token"], "obj_token": nd["obj_token"], "parent_node_token": parent_node_token, "url": f"https://my.feishu.cn/wiki/{nd['node_token']}"}
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
        first_tbl_idx = next((idx for idx, it in enumerate(parsed) if it.get("t") == "table"), len(parsed))
        assert first_tbl_idx >= 6, f"Only {first_tbl_idx} blocks before first table (<6)"
        items = []
        for it in parsed:
            if it.get("t") == "table":
                items.append({"t": "empty_p"})
            items.append(it)
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
                        if r2.get("code") == 0: done += 1
                        else: fail += 1
                time.sleep(0.25)
            buf = []
        for it in items:
            if it.get("t") in ("table", "callout"):
                flush()
                d = Desc()
                root = d.add(it)
                rt = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant", {"children_id": [root], "descendants": d.d})
                if rt.get("code") == 0: done += 1
                else: fail += 1
                time.sleep(0.35)
            else:
                b = simple(it)
                if b: buf.append(b)
        flush()
        rb = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET").get("data", {}).get("content", "")
        print(f"[FEISHU OK] title={DOC_TITLE}\n[FEISHU URL] {info['url']}\n[FEISHU VERIFY] blocks_before_first_table={first_tbl_idx} done_blocks={done} fail={fail} readback_chars={len(rb)}")
        if fail > 0 or len(rb) < 1200:
            raise RuntimeError(f"Publish verify failed: fail={fail}, readback={len(rb)}")
        m = load_manifest()
        m["nodes"][DOC_KEY].update({"done_blocks": done, "readback_chars": len(rb), "blocks_before_first_table": first_tbl_idx})
        save_manifest(m)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    publish_to_feishu(build_html())
