#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Granular Factors F145 - F156: Family 9 (Pure National Team 21-ETF Entry, Exit & Tier Structure).
All signals strictly PIT-aligned to first tradable open AFTER observation/disclosure!
Zero Not-Sell / window-guidance items.
"""


def get_nt_factor_specs():
    F9 = "九、国家队宽基ETF进退场监测"
    return [
        {"id": "F145", "family": F9, "src_type": "panel",
         "name": "全池原始百亿净申购进场日（21只国家队重仓ETF合计净申购>=100亿元）",
         "target": "bench", "horizon": 20, "exp_dir": 1,
         "mask_fn": lambda p: (p["etf_data_avail"] == 1) & (p["etf_net_flow_yi"] >= 100.0)},

        {"id": "F146", "family": F9, "src_type": "panel",
         "name": "国家队持仓纯度加权百亿进场日（按2025年报汇金国新占比加权>=90亿元）",
         "target": "bench", "horizon": 20, "exp_dir": 1,
         "mask_fn": lambda p: (p["etf_data_avail"] == 1) & (p["etf_nt_weighted_flow_yi"] >= 90.0)},

        {"id": "F147", "family": F9, "src_type": "panel",
         "name": "头号标杆510300华泰柏瑞300ETF单票重手进场（单日净申购>=35亿或放量2.3倍护盘）",
         "target": "bench", "horizon": 20, "exp_dir": 1,
         "mask_fn": lambda p: (p["etf_data_avail"] == 1) & ((p["etf510300_net_flow_yi"] >= 35.0) | ((p["etf510300_amt_spike"] >= 2.3) & ((p["csi300_cc_ret"] <= -0.005) | (p["csi300_lower_shadow"] >= 0.008))))},

        {"id": "F148", "family": F9, "src_type": "panel",
         "name": "国家队深跌黄金托底档（纯净加权净申购>=80亿元且沪深300近60日回撤深于8%）",
         "target": "bench", "horizon": 20, "exp_dir": 1,
         "mask_fn": lambda p: (p["etf_data_avail"] == 1) & (p["etf_nt_weighted_flow_yi"] >= 80.0) & (p["bench_dd_60d"] <= -0.08)},

        {"id": "F149", "family": F9, "src_type": "panel",
         "name": "国家队盘中爆量下影线信号（21只ETF成交额>=20日中位2.2倍配沪深300收阴或下影>=1%）",
         "target": "bench", "horizon": 20, "exp_dir": 1,
         "mask_fn": lambda p: (p["etf_amt_spike_20d"] >= 2.2) & ((p["csi300_cc_ret"] <= -0.005) | (p["csi300_lower_shadow"] >= 0.010))},

        {"id": "F150", "family": F9, "src_type": "event",
         "name": "国家队官方明牌公告进场（汇金/国新/诚通/央行互换便利官宣增持或招标）",
         "target": "bench", "horizon": 20, "exp_dir": 1,
         "mask_fn": lambda e: e["cat"] == "NT_OFFICIAL_ENTRY"},

        {"id": "F151", "family": F9, "src_type": "panel",
         "name": "一队偏心只救大盘蓝筹抽血小盘（一队300/50净申购>=75亿但二队中小创<15亿）",
         "target": "csi1000_vs_csi300", "horizon": 5, "exp_dir": -1,
         "mask_fn": lambda p: (p["etf_data_avail"] == 1) & (p["etf_t1_flow_yi"] >= 75.0) & (p["etf_t2_flow_yi"] < 15.0)},

        {"id": "F152", "family": F9, "src_type": "panel",
         "name": "一队叠加二队全面共振扩散底（一队蓝筹>=50亿且二队500/1000/双创>=25亿）",
         "target": "csi1000_vs_csi300", "horizon": 20, "exp_dir": 1,
         "mask_fn": lambda p: (p["etf_data_avail"] == 1) & (p["etf_t1_flow_yi"] >= 50.0) & (p["etf_t2_flow_yi"] >= 25.0)},

        {"id": "F153", "family": F9, "src_type": "panel",
         "name": "国家队护盘停手断档日（纯净加权连买>=3日且5日累计>=220亿后转净流出）",
         "target": "bench", "horizon": 5, "exp_dir": -1,
         "mask_fn": lambda p: (p["etf_data_avail"] == 1) & (p["nt_tapering_stop"] == 1)},

        {"id": "F154", "family": F9, "src_type": "panel",
         "name": "国家队纯度加权百亿净赎回退场日（按持仓占比加权单日净赎回<=-80亿元）",
         "target": "bench", "horizon": 20, "exp_dir": -1,
         "mask_fn": lambda p: (p["etf_data_avail"] == 1) & (p["etf_nt_weighted_flow_yi"] <= -80.0)},

        {"id": "F155", "family": F9, "src_type": "panel",
         "name": "头号标杆510300华泰柏瑞300ETF单票大额退场日（单日净赎回<=-30亿元）",
         "target": "bench", "horizon": 20, "exp_dir": -1,
         "mask_fn": lambda p: (p["etf_data_avail"] == 1) & (p["etf510300_net_flow_yi"] <= -30.0)},

        {"id": "F156", "family": F9, "src_type": "panel",
         "name": "国家队高位过热5日连续重手撤离波段（纯净5日净赎回<=-250亿且20日涨幅>=5%或成交高位）",
         "target": "bench", "horizon": 20, "exp_dir": -1,
         "mask_fn": lambda p: (p["etf_data_avail"] == 1) & (p["etf_nt_weighted_flow_5d_yi"] <= -250.0) & ((p["bench_ret_20d"] >= 0.05) | (p["amount_pct_250d"] >= 0.70))},
    ]
