#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
trackA_100_factors.py
100 orthogonal, strictly-PIT exit/risk-control factors derived from Super-Oversold Pry (超跌撬板 V2.1)
across 7 families: A(16) + B(16) + C(16) + D(14) + E(14) + F(12) + G(12) = 100 factors.
"""

def _exempt_soft(extra_imm=False, extend_20=False, tp_boost=0.0):
    act = {
        "exempt_1030": True,
        "exempt_d5": True,
        "exempt_weak": True,
        "relax_1345_delta": 0.020,
        "exempt_20cm_risk": True,
    }
    if extra_imm:
        act["extra_imm"] = True
    if extend_20:
        act["extend_20cm_d3"] = True
    if tp_boost > 0:
        act["tp_boost_20cm"] = tp_boost
    return act


def _tight_1345(thr=0.070, peak=0.085, strip_imm=True, strip_20_d3=True):
    return {
        "tight_1345_thr": thr,
        "tight_1345_peak": peak,
        "strip_imm": strip_imm,
        "strip_20cm_d3": strip_20_d3,
    }


def build_100_factors() -> list[dict]:
    F = []

    def add(fid, fam, name_cn, desc, decision_time, action_type, pit_note, fn):
        F.append({
            "id": fid, "family": fam, "name_cn": name_cn, "desc": desc,
            "decision_time": decision_time, "action_type": action_type,
            "pit_note": pit_note, "fn": fn,
        })

    # ================= A族 (16个): 全市场跌停与流动性冰点熔断 =================
    add("A01", "A", "昨跌停>=15_0925清", "昨非ST主板跌停>=15家，次日非一字09:25清", "09:25", "cut_0925", "k-1收盘全场跌停数",
        lambda sk, tr, st: {"cut_0925": True} if st.get("prev_mkt_dt_10", 0) >= 15 else {})
    add("A02", "A", "昨跌停>=25_0925清", "昨非ST主板跌停>=25家，次日非一字09:25清", "09:25", "cut_0925", "k-1收盘全场跌停数",
        lambda sk, tr, st: {"cut_0925": True} if st.get("prev_mkt_dt_10", 0) >= 25 else {})
    add("A03", "A", "昨跌停>=40_0925清", "昨非ST主板跌停>=40家，次日非一字09:25清", "09:25", "cut_0925", "k-1收盘全场跌停数",
        lambda sk, tr, st: {"cut_0925": True} if st.get("prev_mkt_dt_10", 0) >= 40 else {})
    add("A04", "A", "昨跌停>=60_0925清", "昨非ST主板跌停>=60家，次日非一字09:25清", "09:25", "cut_0925", "k-1收盘全场跌停数",
        lambda sk, tr, st: {"cut_0925": True} if st.get("prev_mkt_dt_10", 0) >= 60 else {})
    add("A05", "A", "昨跌停>=25_尾盘弱斩去免死", "昨跌停>=25家，14:55跌破-1.5%清且剥夺免死", "14:55", "tighten_eod", "k-1收盘全场跌停数",
        lambda sk, tr, st: {"eod_1455_weak_thr": -0.015, "strip_imm": True, "strip_20cm_d3": True} if st.get("prev_mkt_dt_10", 0) >= 25 else {})
    add("A06", "A", "昨跌停>=25_收紧护利", "昨跌停>=25家，盘中13:45护利上收2%/20cm限价封顶7%", "13:45", "tighten_1345", "k-1收盘全场跌停数",
        lambda sk, tr, st: {"tight_1345_thr": 0.070, "tight_20cm_tp_cap": 0.07, "strip_20cm_d3": True} if st.get("prev_mkt_dt_10", 0) >= 25 else {})
    add("A07", "A", "跌停较5日均激增>=2x_0925清", "昨跌停>=5日均2倍且>=15家，09:25非一字清", "09:25", "cut_0925", "k-1跌停与k-6..k-2均值",
        lambda sk, tr, st: {"cut_0925": True} if (st.get("prev_mkt_dt_10", 0) >= 15 and st.get("prev_mkt_dt_10", 0) >= 2.0 * max(1.0, st.get("prev_mkt_dt_ma5", 5.0))) else {})
    add("A08", "A", "跌停较5日均激增>=3x_0925清", "昨跌停>=5日均3倍且>=15家，09:25非一字清", "09:25", "cut_0925", "k-1跌停与k-6..k-2均值",
        lambda sk, tr, st: {"cut_0925": True} if (st.get("prev_mkt_dt_10", 0) >= 15 and st.get("prev_mkt_dt_10", 0) >= 3.0 * max(1.0, st.get("prev_mkt_dt_ma5", 5.0))) else {})
    add("A09", "A", "跌停激增>=2x_1030+尾盘清", "昨跌停>=5日均2倍且>=15家，10:30破均线或14:55弱斩", "10:30/14:55", "tighten_intraday", "k-1跌停与k-6..k-2均值",
        lambda sk, tr, st: {"vwap_1030": True, "eod_1455_weak_thr": -0.015, "strip_imm": True} if (st.get("prev_mkt_dt_10", 0) >= 15 and st.get("prev_mkt_dt_10", 0) >= 2.0 * max(1.0, st.get("prev_mkt_dt_ma5", 5.0))) else {})
    add("A10", "A", "0925竞价涨停<5_0925熔断", "今09:25全场竞价涨停<5家(撬板XF13原版)，非一字清", "09:25", "cut_0925", "k日09:25全场开盘涨停家数",
        lambda sk, tr, st: {"cut_0925": True} if st.get("mkt_0925_zt", 10) < 5 else {})
    add("A11", "A", "0925竞价涨停<8_0925熔断", "今09:25全场竞价涨停<8家，非一字09:25清", "09:25", "cut_0925", "k日09:25全场开盘涨停家数",
        lambda sk, tr, st: {"cut_0925": True} if st.get("mkt_0925_zt", 10) < 8 else {})
    add("A12", "A", "0925竞价涨停<10_0925熔断", "今09:25全场竞价涨停<10家，非一字09:25清", "09:25", "cut_0925", "k日09:25全场开盘涨停家数",
        lambda sk, tr, st: {"cut_0925": True} if st.get("mkt_0925_zt", 10) < 10 else {})
    add("A13", "A", "0925竞价涨停<15_取消免死留仓", "今09:25竞价涨停<15家，取消断板免死/D5保留/20cm延D3", "09:25/15:00", "strip_exempt", "k日09:25全场开盘涨停家数",
        lambda sk, tr, st: {"strip_imm": True, "strip_d5_keep": True, "strip_20cm_d3": True} if st.get("mkt_0925_zt", 20) < 15 else {})
    add("A14", "A", "0925竞价涨停<10_1030破均线走", "今09:25竞价涨停<10家且10:30未板破均线走", "10:30", "vwap_1030", "k日09:25全场开盘涨停家数+10:30 5m",
        lambda sk, tr, st: {"vwap_1030": True, "strip_imm": True} if st.get("mkt_0925_zt", 10) < 10 else {})
    add("A15", "A", "昨跌停<5_极暖放飞", "昨全场跌停<5家无恐慌，放宽护利2%+豁免1030/D5+20cm延D3", "09:25..15:00", "exempt_fly", "k-1收盘全场跌停数",
        lambda sk, tr, st: _exempt_soft(extra_imm=True, extend_20=True, tp_boost=0.03) if st.get("prev_mkt_dt_all", 10) < 5 else {})
    add("A16", "A", "昨跌停<10_撬板暖日加成放飞", "昨全场跌停<10家(撬板加3%原版)，放宽护利2%+豁免1030+20cm+3%", "09:25..15:00", "exempt_fly", "k-1收盘全场跌停数",
        lambda sk, tr, st: _exempt_soft(extra_imm=False, extend_20=False, tp_boost=0.03) if st.get("prev_mkt_dt_all", 10) < 10 else {})

    # ================= B族 (16个): 个股超跌/超买乖离橡皮筋 =================
    add("B01", "B", "昨bias5>20%_1030破均走", "前收bias5>+20%，10:30未板破分时均线走", "10:30", "vwap_1030", "k-1前复权收盘与MA5",
        lambda sk, tr, st: {"vwap_1030": True} if st.get("prev_bias5", 0.0) > 0.20 else {})
    add("B02", "B", "昨bias5>25%_1345锁+去免死", "前收bias5>+25%，13:45护利收紧+7%且剥夺免死", "13:45", "tighten_1345", "k-1前复权收盘与MA5",
        lambda sk, tr, st: _tight_1345(0.070, 0.085) if st.get("prev_bias5", 0.0) > 0.25 else {})
    add("B03", "B", "昨bias5>30%_低开<3%早盘斩", "前收bias5>+30%且今开<+3%，09:25清", "09:25", "cut_0925", "k-1 bias5 + k日09:25开盘",
        lambda sk, tr, st: {"cut_0925": True} if (st.get("prev_bias5", 0.0) > 0.30 and st.get("o_pct", 0.0) < 0.03) else {})
    add("B04", "B", "昨bias10>30%_1030破均+去免死", "前收bias10>+30%，10:30破均线走且取消免死", "10:30", "vwap_1030", "k-1前复权收盘与MA10",
        lambda sk, tr, st: {"vwap_1030": True, "strip_imm": True} if st.get("prev_bias10", 0.0) > 0.30 else {})
    add("B05", "B", "昨bias10>40%_1345冲7破5锁利", "前收bias10>+40%，13:45冲+7%破+5%即锁利且去免死", "13:45", "tighten_1345", "k-1前复权收盘与MA10",
        lambda sk, tr, st: _tight_1345(0.050, 0.070) if st.get("prev_bias10", 0.0) > 0.40 else {})
    add("B06", "B", "昨bias10>50%_0925止盈清", "前收bias10>+50%，次日非一字09:25止盈", "09:25", "cut_0925", "k-1前复权收盘与MA10",
        lambda sk, tr, st: {"cut_0925": True} if st.get("prev_bias10", 0.0) > 0.50 else {})
    add("B07", "B", "昨bias20>40%_1030破均+去免死", "前收bias20>+40%，10:30破均线走且取消免死", "10:30", "vwap_1030", "k-1前复权收盘与MA20",
        lambda sk, tr, st: {"vwap_1030": True, "strip_imm": True} if st.get("prev_bias20", 0.0) > 0.40 else {})
    add("B08", "B", "昨bias20>55%_紧护利+尾盘弱斩", "前收bias20>+55%，13:45收紧+6.5%+尾盘跌1%清", "13:45/14:55", "tighten_all", "k-1前复权收盘与MA20",
        lambda sk, tr, st: {"tight_1345_thr": 0.065, "eod_1455_weak_thr": -0.010, "strip_imm": True, "strip_20cm_d3": True} if st.get("prev_bias20", 0.0) > 0.55 else {})
    add("B09", "B", "昨bias20>70%_0925止盈清", "前收bias20>+70%，次日非一字09:25止盈", "09:25", "cut_0925", "k-1前复权收盘与MA20",
        lambda sk, tr, st: {"cut_0925": True} if st.get("prev_bias20", 0.0) > 0.70 else {})
    add("B10", "B", "昨bias20<10%_低位豁免放飞", "前收bias20<+10%仍在低位，豁免洗盘并放宽护利+20cm延D3", "09:25..15:00", "exempt_fly", "k-1前复权收盘与MA20",
        lambda sk, tr, st: _exempt_soft(extra_imm=False, extend_20=True) if st.get("prev_bias20", 1.0) < 0.10 else {})
    add("B11", "B", "昨bias20<15%_低位放飞+真阳免死", "前收bias20<+15%，豁免1030并赋予1次阳线免死", "10:30/15:00", "exempt_fly", "k-1前复权收盘与MA20",
        lambda sk, tr, st: _exempt_soft(extra_imm=True, extend_20=False) if st.get("prev_bias20", 1.0) < 0.15 else {})
    add("B12", "B", "昨pos60<0.5_底部半区豁免放飞", "前收位于近60日下半区(pos60<0.5)，豁免1030+20cm延D3", "10:30/15:00", "exempt_fly", "k-1相对60日高低位",
        lambda sk, tr, st: _exempt_soft(extra_imm=False, extend_20=True) if st.get("prev_pos60", 1.0) < 0.50 else {})
    add("B13", "B", "前10日涨>40%_动态限价止盈", "前10日涨幅>40%，挂clip(0.35*ret10,6%,12%)相对成本止盈", "09:25..15:00", "tp_limit", "k-1前10日复权涨幅",
        lambda sk, tr, st: {"tp_rel_buy": float(min(0.12, max(0.06, 0.35 * st.get("prev_ret10", 0.0))))} if st.get("prev_ret10", 0.0) > 0.40 else {})
    add("B14", "B", "前10日涨>60%_限价+8%止盈", "前10日涨幅>60%，盘前挂+8%限价止盈(rel昨收)且去免死", "09:25..15:00", "tp_limit", "k-1前10日复权涨幅",
        lambda sk, tr, st: {"tp_rel_prev": 0.08, "strip_imm": True} if st.get("prev_ret10", 0.0) > 0.60 else {})
    add("B15", "B", "前10日涨>80%_开<5%早盘清", "前10日涨幅>80%且今开<+5%，09:25落袋", "09:25", "cut_0925", "k-1 ret10 + k日09:25开盘",
        lambda sk, tr, st: {"cut_0925": True} if (st.get("prev_ret10", 0.0) > 0.80 and st.get("o_pct", 0.0) < 0.05) else {})
    add("B16", "B", "昨dd20<=0.80_纯超跌深水放飞", "前收仍距20日高回撤>=20%，深水超跌豁免早斩并放飞", "09:25..15:00", "exempt_fly", "k-1相对20日高点回撤",
        lambda sk, tr, st: _exempt_soft(extra_imm=True, extend_20=True) if st.get("prev_dd20", 1.0) <= 0.80 else {})

    # ================= C族 (16个): 撬板强阳/阴线形态与K线质量 =================
    add("C01", "C", "买日CLV>=0.70强真阳_T1豁免", "买入日C>O且CLV>=0.70(撬板原版)，T+1豁免弱斩/1030/20cm延D3", "T+1", "exempt_fly", "买日收盘K线(仅T+1用)",
        lambda sk, tr, st: _exempt_soft(extend_20=True) if (st.get("off") == 1 and st.get("buy_c_gt_o") and st.get("buy_clv", 0.0) >= 0.70) else {})
    add("C02", "C", "买日CLV>=0.80强真阳_T1豁免", "买入日C>O且CLV>=0.80，T+1豁免洗盘并放宽护利2%", "T+1", "exempt_fly", "买日收盘K线(仅T+1用)",
        lambda sk, tr, st: _exempt_soft(extra_imm=True, extend_20=True) if (st.get("off") == 1 and st.get("buy_c_gt_o") and st.get("buy_clv", 0.0) >= 0.80) else {})
    add("C03", "C", "买日CLV>=0.90光头_T1T2豁免", "买入日C>O且CLV>=0.90极强光头，T+1~T+2豁免洗盘", "T+1..T+2", "exempt_fly", "买日收盘K线",
        lambda sk, tr, st: _exempt_soft(extra_imm=True, extend_20=True) if (st.get("off", 9) <= 2 and st.get("buy_c_gt_o") and st.get("buy_clv", 0.0) >= 0.90) else {})
    add("C04", "C", "昨日CLV>=0.75强真阳_今日豁免", "昨日C>O且CLV>=0.75，今日豁免1030/D5与弱斩", "09:25..15:00", "exempt_fly", "k-1收盘K线",
        lambda sk, tr, st: _exempt_soft(extend_20=True) if (st.get("prev_c_gt_o") and st.get("prev_clv", 0.0) >= 0.75) else {})
    add("C05", "C", "买日上影>=0.45_T1开<2%斩", "买日非板且上影占比>=0.45，T+1开<+2%果断09:25止损", "09:25", "cut_0925", "买日收盘K线+T+1开盘",
        lambda sk, tr, st: {"cut_0925": True} if (st.get("off") == 1 and (not st.get("buy_zt")) and st.get("buy_upper_shad", 0.0) >= 0.45 and st.get("o_pct", 0.0) < 0.02) else {})
    add("C06", "C", "买日上影>=0.60避雷针_T1斩", "买日非板且上影>=0.60避雷针，T+1非一字直接09:25止损", "09:25", "cut_0925", "买日收盘K线",
        lambda sk, tr, st: {"cut_0925": True} if (st.get("off") == 1 and (not st.get("buy_zt")) and st.get("buy_upper_shad", 0.0) >= 0.60) else {})
    add("C07", "C", "昨日上影>=0.45_今开<1%斩", "昨日非板且上影>=0.45，今开<+1%立即09:25止损", "09:25", "cut_0925", "k-1收盘K线+k日09:25开盘",
        lambda sk, tr, st: {"cut_0925": True} if ((not st.get("prev_zt")) and st.get("prev_upper_shad", 0.0) >= 0.45 and st.get("o_pct", 0.0) < 0.01) else {})
    add("C08", "C", "昨日上影>=0.60避雷针_0925斩", "昨日非板且上影>=0.60避雷针，今日非一字直接09:25清", "09:25", "cut_0925", "k-1收盘K线",
        lambda sk, tr, st: {"cut_0925": True} if ((not st.get("prev_zt")) and st.get("prev_upper_shad", 0.0) >= 0.60) else {})
    add("C09", "C", "买日收阴_T1开<1%斩", "买日非板且实体收阴(C<O)，T+1开<+1%直接09:25清", "09:25", "cut_0925", "买日收盘K线+T+1开盘",
        lambda sk, tr, st: {"cut_0925": True} if (st.get("off") == 1 and (not st.get("buy_zt")) and (not st.get("buy_c_gt_o")) and st.get("o_pct", 0.0) < 0.01) else {})
    add("C10", "C", "昨日收阴_今开<2%斩", "昨日非板且实体收阴(C<O)，今开<+2%直接09:25清", "09:25", "cut_0925", "k-1收盘K线+k日开盘",
        lambda sk, tr, st: {"cut_0925": True} if ((not st.get("prev_zt")) and (not st.get("prev_c_gt_o")) and st.get("o_pct", 0.0) < 0.02) else {})
    add("C11", "C", "昨日长阴光脚CLV<=0.30_0925斩", "昨日收阴且CLV<=0.30丑陋光脚阴，今日非一字09:25止损", "09:25", "cut_0925", "k-1收盘K线",
        lambda sk, tr, st: {"cut_0925": True} if ((not st.get("prev_zt")) and (not st.get("prev_c_gt_o")) and st.get("prev_clv", 1.0) <= 0.30) else {})
    add("C12", "C", "买日深水-5%拉起强阳_T1豁免", "买日曾跌<=-5%且收真阳CLV>=0.60强承接，T+1豁免洗盘", "T+1", "exempt_fly", "买日日内最低与收盘K线",
        lambda sk, tr, st: _exempt_soft(extra_imm=True, extend_20=True) if (st.get("off") == 1 and st.get("buy_low_pct", 0.0) <= -0.05 and st.get("buy_c_gt_o") and st.get("buy_clv", 0.0) >= 0.60) else {})
    add("C13", "C", "昨日深水撬起收真阳_今日豁免", "昨日曾触跌停或跌<=-5%且收真阳，今日豁免1030/弱斩", "09:25..15:00", "exempt_fly", "k-1最低与收盘K线",
        lambda sk, tr, st: _exempt_soft(extend_20=True) if (st.get("prev_dip5_or_dt") and st.get("prev_c_gt_o")) else {})
    add("C14", "C", "连阳>=3天_1030破均+去免死", "截至昨日已连阳>=3天疲劳，今日10:30破均线走且去免死", "10:30", "vwap_1030", "k-1连阳计数",
        lambda sk, tr, st: {"vwap_1030": True, "strip_imm": True} if st.get("prev_yang_streak", 0) >= 3 else {})
    add("C15", "C", "连阳>=4天_紧护利+尾盘弱斩", "截至昨日已连阳>=4天，13:45收紧+7%且14:55跌1%清", "13:45/14:55", "tighten_all", "k-1连阳计数",
        lambda sk, tr, st: {"tight_1345_thr": 0.070, "eod_1455_weak_thr": -0.010, "strip_imm": True, "strip_20cm_d3": True} if st.get("prev_yang_streak", 0) >= 4 else {})
    add("C16", "C", "连阳>=5天_0925止盈清", "截至昨日连阳>=5天极端疲劳，今日非一字09:25止盈", "09:25", "cut_0925", "k-1连阳计数",
        lambda sk, tr, st: {"cut_0925": True} if st.get("prev_yang_streak", 0) >= 5 else {})

    # ================= D族 (14个): 放量爆量与锁仓自由流通盘换手 =================
    add("D01", "D", "昨放量>=2.5x_1345锁+去免死", "昨额>=前5日均2.5倍，13:45收紧+7%且取消免死", "13:45", "tighten_1345", "k-1成交额/前5日均额",
        lambda sk, tr, st: _tight_1345(0.070, 0.085) if st.get("prev_vr", 1.0) >= 2.5 else {})
    add("D02", "D", "昨放量>=3.5x_1030破均+去免死", "昨额>=前5日均3.5倍分歧爆量，10:30破均走且去免死", "10:30", "vwap_1030", "k-1成交额/前5日均额",
        lambda sk, tr, st: {"vwap_1030": True, "strip_imm": True, "strip_20cm_d3": True} if st.get("prev_vr", 1.0) >= 3.5 else {})
    add("D03", "D", "昨放量>=5.0x_开<2%早盘清", "昨额>=前5日均5倍天量且今开<+2%，09:25果断清", "09:25", "cut_0925", "k-1量比+k日09:25开盘",
        lambda sk, tr, st: {"cut_0925": True} if (st.get("prev_vr", 1.0) >= 5.0 and st.get("o_pct", 0.0) < 0.02) else {})
    add("D04", "D", "昨放量>=5.0x_0925直接清", "昨额>=前5日均5倍天量透支，次日非一字直接09:25清", "09:25", "cut_0925", "k-1成交额/前5日均额",
        lambda sk, tr, st: {"cut_0925": True} if st.get("prev_vr", 1.0) >= 5.0 else {})
    add("D05", "D", "昨缩量<=0.7x_锁筹豁免放飞", "昨量比<=0.7x良性锁筹，豁免1030/D5洗盘+真阳免死", "09:25..15:00", "exempt_fly", "k-1成交额/前5日均额",
        lambda sk, tr, st: _exempt_soft(extra_imm=True, extend_20=True) if st.get("prev_vr", 1.0) <= 0.70 else {})
    add("D06", "D", "昨缩量<=0.9x_轻度锁筹豁免", "昨量比<=0.9x，豁免1030破均线洗盘与D5轻斩", "09:25..15:00", "exempt_fly", "k-1成交额/前5日均额",
        lambda sk, tr, st: _exempt_soft(extra_imm=False, extend_20=False) if st.get("prev_vr", 1.0) <= 0.90 else {})
    add("D07", "D", "真实流值<=15亿_超小盘放飞", "扣前十大锁仓后真实流值<=15亿，放宽护利+20cm延D3", "09:25..15:00", "exempt_fly", "PIT前十大锁仓+k-1市值",
        lambda sk, tr, st: _exempt_soft(extra_imm=True, extend_20=True) if st.get("prev_real_fmcap", 99.0) <= 15.0 else {})
    add("D08", "D", "真实流值<=25亿_小盘豁免", "真实自由流通市值<=25亿(撬板原版门槛)，豁免1030洗盘", "09:25..15:00", "exempt_fly", "PIT前十大锁仓+k-1市值",
        lambda sk, tr, st: _exempt_soft(extra_imm=False, extend_20=True) if st.get("prev_real_fmcap", 99.0) <= 25.0 else {})
    add("D09", "D", "真实流值>=60亿_大盘严锁利", "真实自由流通市值>=60亿笨重，1030破均+1345收紧+7%", "10:30/13:45", "tighten_all", "PIT前十大锁仓+k-1市值",
        lambda sk, tr, st: {"vwap_1030": True, "tight_1345_thr": 0.070, "strip_20cm_d3": True} if st.get("prev_real_fmcap", 0.0) >= 60.0 else {})
    add("D10", "D", "锁仓率>=50%_高锁筹豁免", "PIT前十大锁仓率>=50%(撬板原版)，豁免1030/D5洗盘", "09:25..15:00", "exempt_fly", "PIT前十大公告日<=k-1",
        lambda sk, tr, st: _exempt_soft(extra_imm=False, extend_20=True) if st.get("lock10", 0.0) >= 50.0 else {})
    add("D11", "D", "锁仓率<35%_散盘严管", "PIT前十大锁仓率<35%筹码分散，1030破均且取消免死", "10:30/15:00", "tighten_1030", "PIT前十大公告日<=k-1",
        lambda sk, tr, st: {"vwap_1030": True, "strip_imm": True} if st.get("lock10", 50.0) < 35.0 else {})
    add("D12", "D", "昨真实自由换手>=35%_尾盘严斩", "昨自由换手>=35%筹码透支，14:55跌1%清且去免死", "14:55", "tighten_eod", "k-1换手/(1-lock10)",
        lambda sk, tr, st: {"eod_1455_weak_thr": -0.010, "strip_imm": True, "strip_20cm_d3": True} if st.get("prev_real_turn", 0.0) >= 0.35 else {})
    add("D13", "D", "昨真实自由换手>=50%_1030破均走", "昨自由换手>=50%极端博弈，10:30破均走且取消免死", "10:30", "vwap_1030", "k-1换手/(1-lock10)",
        lambda sk, tr, st: {"vwap_1030": True, "strip_imm": True, "strip_20cm_d3": True} if st.get("prev_real_turn", 0.0) >= 0.50 else {})
    add("D14", "D", "昨真实自由换手>=70%_0925清", "昨自由换手>=70%彻底透支，次日非一字直接09:25清", "09:25", "cut_0925", "k-1换手/(1-lock10)",
        lambda sk, tr, st: {"cut_0925": True} if st.get("prev_real_turn", 0.0) >= 0.70 else {})

    # ================= E族 (14个): 撬板阶梯时间衰减与T+1 14:55弱斩移植 =================
    add("E01", "E", "T1_1455跌超1.0%弱斩", "持仓T+1日14:55较昨收跌超-1.0%(非板)清仓", "14:55", "eod_weak", "T+1 14:55 bar",
        lambda sk, tr, st: {"eod_1455_weak_thr": -0.010} if st.get("off") == 1 else {})
    add("E02", "E", "T1_1455跌超1.5%弱斩(撬板原版)", "持仓T+1日14:55较昨收跌超-1.5%(非板)清仓", "14:55", "eod_weak", "T+1 14:55 bar",
        lambda sk, tr, st: {"eod_1455_weak_thr": -0.015} if st.get("off") == 1 else {})
    add("E03", "E", "T1_1455跌超2.5%弱斩", "持仓T+1日14:55较昨收跌超-2.5%(非板)清仓", "14:55", "eod_weak", "T+1 14:55 bar",
        lambda sk, tr, st: {"eod_1455_weak_thr": -0.025} if st.get("off") == 1 else {})
    add("E04", "E", "T1_1455跌超4.0%弱斩", "持仓T+1日14:55较昨收跌超-4.0%(非板)清仓", "14:55", "eod_weak", "T+1 14:55 bar",
        lambda sk, tr, st: {"eod_1455_weak_thr": -0.040} if st.get("off") == 1 else {})
    add("E05", "E", "全持仓期1455跌超1.5%弱斩", "所有持仓日14:55较昨收跌超-1.5%(非板)一律清仓", "14:55", "eod_weak", "各持仓日14:55 bar",
        lambda sk, tr, st: {"eod_1455_weak_thr": -0.015})
    add("E06", "E", "盘前固定+6%限价止盈", "持仓日挂相对买价+6%盘前限价止盈(先于连板锁利)", "09:25..15:00", "tp_limit", "买价*(1+6%)",
        lambda sk, tr, st: {"tp_rel_buy": 0.06})
    add("E07", "E", "盘前固定+8%限价止盈", "持仓日挂相对买价+8%盘前限价止盈", "09:25..15:00", "tp_limit", "买价*(1+8%)",
        lambda sk, tr, st: {"tp_rel_buy": 0.08})
    add("E08", "E", "盘前固定+10%限价止盈", "持仓日挂相对买价+10%盘前限价止盈", "09:25..15:00", "tp_limit", "买价*(1+10%)",
        lambda sk, tr, st: {"tp_rel_buy": 0.10})
    add("E09", "E", "T2起挂+12%限价止盈", "T+1放飞，T+2起挂相对买价+12%限价止盈", "09:25..15:00", "tp_limit", "T+2起买价*(1+12%)",
        lambda sk, tr, st: {"tp_rel_buy": 0.12} if st.get("off", 0) >= 2 else {})
    add("E10", "E", "T2起挂+15%限价止盈", "T+1放飞，T+2起挂相对买价+15%限价止盈", "09:25..15:00", "tp_limit", "T+2起买价*(1+15%)",
        lambda sk, tr, st: {"tp_rel_buy": 0.15} if st.get("off", 0) >= 2 else {})
    add("E11", "E", "T2起撬板动态限价止盈", "T+2起挂clip(0.45*|ret10|,6%,16%)相对买价动态止盈", "09:25..15:00", "tp_limit", "买日前10日振幅",
        lambda sk, tr, st: {"tp_rel_buy": float(min(0.16, max(0.06, 0.45 * abs(st.get("prev_ret10", 0.10)))))} if st.get("off", 0) >= 2 else {})
    add("E12", "E", "撬板T2+5%/T3+2%/T4必清阶梯", "T+2挂+5%、T+3挂+2%限价止盈且T+4非板必清", "09:25..15:00", "time_decay", "持仓天数off",
        lambda sk, tr, st: ({"tp_rel_buy": 0.05} if st.get("off") == 2 else ({"tp_rel_buy": 0.02} if st.get("off") == 3 else ({"force_eod_off": 4} if st.get("off", 0) >= 4 else {}))))
    add("E13", "E", "T3非涨停强制清仓时间止损", "持仓达T+3及以后未封涨停于15:00强制清仓", "15:00", "time_stop", "持仓天数off>=3",
        lambda sk, tr, st: {"force_eod_off": 3} if st.get("off", 0) >= 3 else {})
    add("E14", "E", "T2非涨停强制清仓时间止损", "持仓达T+2及以后未封涨停即清仓(剥夺连板断板免死)", "15:00", "time_stop", "持仓天数off>=2",
        lambda sk, tr, st: {"force_eod_off": 2, "strip_imm": True} if st.get("off", 0) >= 2 else {})

    # ================= F族 (12个): 龙虎榜机构净买与拉萨散户接盘 =================
    add("F01", "F", "拉萨买额>15%_高开止盈否则1030走", "前收已知龙虎榜拉萨买额>15%，今开>=2% 0925清否则1030破均走", "09:25/10:30", "lhb_lhasa", "<=k-1晚龙虎榜",
        lambda sk, tr, st: ({"cut_0925": True} if st.get("o_pct", 0.0) >= 0.02 else {"vwap_1030": True}) if st.get("lhb_lh_ratio", 0.0) > 0.15 else {})
    add("F02", "F", "拉萨买额>25%_1030破均+去免死", "已知龙虎榜拉萨买额>25%(撬板-20原版)，1030破均走且去免死", "10:30", "lhb_lhasa", "<=k-1晚龙虎榜",
        lambda sk, tr, st: {"vwap_1030": True, "strip_imm": True, "strip_20cm_d3": True} if st.get("lhb_lh_ratio", 0.0) > 0.25 else {})
    add("F03", "F", "拉萨买额>35%_0925直接清", "已知龙虎榜拉萨买额>35%散户接盘，非一字直接09:25清", "09:25", "cut_0925", "<=k-1晚龙虎榜",
        lambda sk, tr, st: {"cut_0925": True} if st.get("lhb_lh_ratio", 0.0) > 0.35 else {})
    add("F04", "F", "拉萨买额>25%_0925直接清", "已知龙虎榜拉萨买额>25%，非一字直接09:25清仓", "09:25", "cut_0925", "<=k-1晚龙虎榜",
        lambda sk, tr, st: {"cut_0925": True} if st.get("lhb_lh_ratio", 0.0) > 0.25 else {})
    add("F05", "F", "机构净买>0_豁免洗盘放飞", "已知龙虎榜机构净买>0(撬板+10原版)，豁免1030洗盘+20cm延D3", "09:25..15:00", "exempt_fly", "<=k-1晚龙虎榜",
        lambda sk, tr, st: _exempt_soft(extra_imm=False, extend_20=True) if st.get("lhb_inst_net", 0.0) > 0.0 else {})
    add("F06", "F", "机构净买>2000万_强背书放飞", "已知龙虎榜机构净买>2000万，豁免1030+赋1次真阳免死+延D3", "09:25..15:00", "exempt_fly", "<=k-1晚龙虎榜",
        lambda sk, tr, st: _exempt_soft(extra_imm=True, extend_20=True) if st.get("lhb_inst_net", 0.0) > 2e7 else {})
    add("F07", "F", "机构净卖>2000万_1345锁+1030走", "已知龙虎榜机构净卖>2000万，1345收紧+7%且1030破均走", "10:30/13:45", "tighten_inst", "<=k-1晚龙虎榜",
        lambda sk, tr, st: {"vwap_1030": True, "tight_1345_thr": 0.070, "strip_imm": True, "strip_20cm_d3": True} if st.get("lhb_inst_net", 0.0) < -2e7 else {})
    add("F08", "F", "机构净卖>5000万_0925直接清", "已知龙虎榜机构净卖>5000万，非一字09:25直接清仓", "09:25", "cut_0925", "<=k-1晚龙虎榜",
        lambda sk, tr, st: {"cut_0925": True} if st.get("lhb_inst_net", 0.0) < -5e7 else {})
    add("F09", "F", "机构净卖>2000万_开<2%早盘清", "已知龙虎榜机构净卖>2000万且今开<+2%，09:25清", "09:25", "cut_0925", "<=k-1晚龙虎榜+k日开盘",
        lambda sk, tr, st: {"cut_0925": True} if (st.get("lhb_inst_net", 0.0) < -2e7 and st.get("o_pct", 0.0) < 0.02) else {})
    add("F10", "F", "龙虎榜前5席净卖出_1030破均走", "已知龙虎榜前5席总买<总卖(净流出)，1030破均且去免死", "10:30", "lhb_net_neg", "<=k-1晚龙虎榜",
        lambda sk, tr, st: {"vwap_1030": True, "strip_imm": True} if (st.get("has_lhb") and st.get("lhb_tot_net", 0.0) < 0.0) else {})
    add("F11", "F", "龙虎榜净流出_开<1%0925清", "已知龙虎榜总净买为负且今开<+1%，09:25清仓", "09:25", "cut_0925", "<=k-1晚龙虎榜+k日开盘",
        lambda sk, tr, st: {"cut_0925": True} if (st.get("has_lhb") and st.get("lhb_tot_net", 0.0) < 0.0 and st.get("o_pct", 0.0) < 0.01) else {})
    add("F12", "F", "龙虎榜拉萨>=2家_紧护利+弱斩", "已知龙虎榜出现>=2家拉萨席位，1345收紧+7%+1455跌1.5%清", "13:45/14:55", "lhb_lhasa", "<=k-1晚龙虎榜",
        lambda sk, tr, st: {"tight_1345_thr": 0.070, "eod_1455_weak_thr": -0.015, "strip_imm": True} if st.get("lhb_lh_cnt", 0) >= 2 else {})

    # ================= G族 (12个): 5分钟盘中橡皮筋冲高回落与指数联动 =================
    add("G01", "G", "早盘冲5%回落破2%锁利", "09:35~10:30曾摸>=+5%回落破+2%即卖出(5m)", "09:35..10:30", "g_intraday", "5m实时bar至10:30",
        lambda sk, tr, st: {"g_peak_drop": (0.050, 0.020)})
    add("G02", "G", "早盘冲7%回落破4%锁利", "09:35~10:30曾摸>=+7%回落破+4%即卖出(5m)", "09:35..10:30", "g_intraday", "5m实时bar至10:30",
        lambda sk, tr, st: {"g_peak_drop": (0.070, 0.040)})
    add("G03", "G", "早盘冲8.5%回落破5%锁利", "09:35~10:30曾摸>=+8.5%回落破+5%即卖出(5m)", "09:35..10:30", "g_intraday", "5m实时bar至10:30",
        lambda sk, tr, st: {"g_peak_drop": (0.085, 0.050)})
    add("G04", "G", "早盘冲8.5%回落破6%锁利", "09:35~10:30曾摸>=+8.5%回落破+6%即卖出(5m)", "09:35..10:30", "g_intraday", "5m实时bar至10:30",
        lambda sk, tr, st: {"g_peak_drop": (0.085, 0.060)})
    add("G05", "G", "早盘急杀破-3%即刻止损", "09:35~10:30跌破昨收-3%立刻止损(5m)", "09:35..10:30", "g_panic_sl", "5m实时bar至10:30",
        lambda sk, tr, st: {"g_panic_sl": -0.030})
    add("G06", "G", "早盘急杀破-5%即刻止损", "09:35~10:30跌破昨收-5%立刻止损(5m)", "09:35..10:30", "g_panic_sl", "5m实时bar至10:30",
        lambda sk, tr, st: {"g_panic_sl": -0.050})
    add("G07", "G", "早盘急杀破-7%即刻止损", "09:35~10:30跌破昨收-7%立刻止损(5m)", "09:35..10:30", "g_panic_sl", "5m实时bar至10:30",
        lambda sk, tr, st: {"g_panic_sl": -0.070})
    add("G08", "G", "早盘深水-4%反包站回1030均线留仓", "早盘曾跌<=-4%但10:30站回VWAP，豁免1030弱斩留仓(5m)", "10:30", "g_bounce_exempt", "5m实时bar至10:30",
        lambda sk, tr, st: {"g_bounce_exempt": True})
    add("G09", "G", "沪深300昨跌<=-1.5%_收紧防守", "昨沪深300跌<=-1.5%，1030破均+1345收紧+7%+去免死", "10:30/13:45", "idx_tight", "k-1沪深300日涨幅",
        lambda sk, tr, st: {"vwap_1030": True, "tight_1345_thr": 0.070, "strip_imm": True, "strip_20cm_d3": True} if st.get("prev_csi_ret", 0.0) <= -0.015 else {})
    add("G10", "G", "沪深300昨暴跌<=-2.5%_0925避险清", "昨沪深300跌<=-2.5%，次日非一字09:25直接清", "09:25", "cut_0925", "k-1沪深300日涨幅",
        lambda sk, tr, st: {"cut_0925": True} if st.get("prev_csi_ret", 0.0) <= -0.025 else {})
    add("G11", "G", "深综指昨跌<=-2.0%_弱开0925/尾盘斩", "昨深证综指(中小微代表)跌<=-2.0%，弱开0925清+尾盘弱斩", "09:25/14:55", "idx_tight", "k-1 sz399107日涨幅",
        lambda sk, tr, st: ({"cut_0925": True} if st.get("o_pct", 0.0) < 0.01 else {"eod_1455_weak_thr": -0.015, "strip_imm": True}) if st.get("prev_sz_ret", 0.0) <= -0.020 else {})
    add("G12", "G", "沪深300昨大涨>=+2.0%_顺风放飞", "昨沪深300大涨>=+2.0%顺风，豁免1030/放宽护利/20cm延D3", "09:25..15:00", "exempt_fly", "k-1沪深300日涨幅",
        lambda sk, tr, st: _exempt_soft(extra_imm=False, extend_20=True) if st.get("prev_csi_ret", 0.0) >= 0.020 else {})

    assert len(F) == 100, f"Expected 100 factors, got {len(F)}"
    assert len({x["id"] for x in F}) == 100, "Duplicate factor IDs"
    return F
