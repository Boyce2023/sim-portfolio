#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""60-Factor Metadata Dictionary (9 Families / 11 Seat-2 Modules) + HLZ / DSR / JSON helpers."""
import math
import numpy as np
import scipy.stats as stats

FACTOR_META = {
    # Family 1: National Team V3.0 (11 factors)
    "f01_nt_v3_eod_d1": ("F1_NT_V3", "国家队V3.0", "d-1盘后", "国家队V3.0盘后确认分(0-100)"),
    "f02_nt_v3_live_d1": ("F1_NT_V3", "国家队V3.0", "d-1盘中", "国家队V3.0盘中即时分(0-100)"),
    "f03_nt_etf_spike_d1": ("F1_NT_V3", "国家队V3.0", "d-1收盘", "10核心/22宽基ETF成交额放量倍数"),
    "f04_nt_fake_support_d1": ("F1_NT_V3", "国家队V3.0+假护盘", "d-1收盘", "缩量拉四大行石油抽血中证1000"),
    "f05_nt_rd019_trap_d1": ("F1_NT_V3", "国家队V3.0", "d-1收盘", "非交割日期现双爆量陷阱(ETF>=1.8x&IF0>=1.5x)"),
    "f06_nt_t1_skew_d1": ("F1_NT_V3", "国家队V3.0", "d-1盘后", "一队净申购减二队净申购(亿元)"),
    "f07_nt_t2_res_d1": ("F1_NT_V3", "国家队V3.0", "d-1盘后", "二队(500/1000/创业/科创)ETF净申购(亿元)"),
    "f08_nt_f152_sync_d1": ("F1_NT_V3", "国家队V3.0", "d-1盘后", "F152一二队共振(一队>=50亿且二队>=25亿)"),
    "f09_nt_fund8_dump_d1": ("F1_NT_V3", "国家队V3.0", "d-1收盘", "公募8大重仓放量砸盘家数"),
    "f10_nt_wflow5d_d1": ("F1_NT_V3", "国家队V3.0", "d-1盘后", "近5日国家队加权宽基净申购(亿元)"),
    "f11_nt_if0_basis_d1": ("F1_NT_V3", "国家队V3.0", "d-1收盘", "IF0沪深300股指期货基差率(%)"),
    # Family 2: CSRC Policy 22 Core (5 factors)
    "f12_pol_rescue_20d": ("F2_CSRC_Policy22", "证监会政策22核", "td<=d", "近20日救市/限融券/不干预正常交易信号计数"),
    "f13_pol_tech_ma_20d": ("F2_CSRC_Policy22", "证监会政策22核", "td<=d", "近20日低拥挤窗口科技/并购政策加分事件"),
    "f14_pol_headwind_10d": ("F2_CSRC_Policy22", "证监会政策22核", "td<=d", "近10日严监管/退市/交易所监控/非股市会议逆风"),
    "f15_pol_div_large_20d": ("F2_CSRC_Policy22", "证监会政策22核", "td<=d", "近20日分红回购+严打炒小政策共振事件"),
    "f16_pol_net_score_20d": ("F2_CSRC_Policy22", "证监会政策22核", "td<=d", "近20日政策净得分(顺风-逆风)"),
    # Family 3: US Nasdaq Overnight (4 factors)
    "f17_us_ixic_ret1d": ("F3_US_Overnight", "美股纳指大跌传导", "美股<d", "隔夜纳指IXIC日涨跌幅"),
    "f18_us_ixic_drop15": ("F3_US_Overnight", "美股纳指大跌传导", "美股<d", "隔夜纳指大跌<=-1.5%开关"),
    "f19_us_ixic_ret5d": ("F3_US_Overnight", "美股纳指大跌传导", "美股<d", "隔夜纳指近5日累计涨跌幅"),
    "f20_us_vix_chg1d": ("F3_US_Overnight", "美股纳指大跌传导", "美股<d", "隔夜VIX恐慌指数单日变动"),
    # Family 4: Market Defensive / Fake Support / Panic (5 factors)
    "f21_mkt_shrink_bank_fake_d1": ("F4_Defensive", "缩量假护盘与恐慌出清", "d-1收盘", "全市场缩量+银行涨+沪深300跌假护盘"),
    "f22_mkt_panic_wash_d1": ("F4_Defensive", "缩量假护盘与恐慌出清", "d-1收盘", "放量恐慌出清(沪深300<=-1.5%或非ST跌停>=25)"),
    "f23_mkt_csi300_ret_d1": ("F4_Defensive", "缩量假护盘与恐慌出清", "d-1收盘", "前日沪深300涨跌幅"),
    "f24_mkt_tech_retreat_d1": ("F4_Defensive", "缩量假护盘与恐慌出清", "d-1收盘", "前日TMT科技板块(C39/I65/I63)均涨幅"),
    "f25_mkt_amt_ratio20_d1": ("F4_Defensive", "缩量假护盘与恐慌出清", "d-1收盘", "前日全A成交额/20日均额比"),
    # Family 5: 15Y Style & Stock Reversal (4 factors)
    "f26_style_small_vs_big_20d": ("F5_15Y_Style_Rev", "15年风格与反转", "d-1收盘", "近20日小市值(含退市)减大蓝筹风格差"),
    "f27_style_rev_vs_mom_20d": ("F5_15Y_Style_Rev", "15年风格与反转", "d-1收盘", "近20日超跌反转减动量追强风格差"),
    "f28_stk_ret20_d1": ("F5_15Y_Style_Rev", "15年风格与反转", "d-1收盘", "个股前20日累计涨幅(10cm横截面反转)"),
    "f29_stk_ret5_d1": ("F5_15Y_Style_Rev", "15年风格与反转", "d-1收盘", "个股前5日累计涨幅"),
    # Family 6: RD011 Grand 120 Cross-Year Core (11 factors)
    "f30_rd11_hr10d": ("F6_RD011_120Core", "跨年大票120因子核", "d开盘", "10日+100%监管异动剩余安全空间"),
    "f31_rd11_hr30d": ("F6_RD011_120Core", "跨年大票120因子核", "d开盘", "30日+200%监管异动剩余安全空间"),
    "f32_rd11_tight_hr": ("F6_RD011_120Core", "跨年大票120因子核", "d开盘", "min(10日异动空间,30日异动空间)"),
    "f33_rd11_dev10_slope3": ("F6_RD011_120Core", "跨年大票120因子核", "d-1收盘", "3日异动偏离度斜率(赶顶加速度)"),
    "f34_rd11_ma20_dist": ("F6_RD011_120Core", "跨年大票120因子核", "d-1收盘", "个股收盘距MA20乖离率"),
    "f35_rd11_ir_cnt30d": ("F6_RD011_120Core", "跨年大票120因子核", "d 09:25前", "近30天互动易机构/投资者问答条数"),
    "f36_rd11_soe_flag": ("F6_RD011_120Core", "跨年大票120因子核", "静态名称", "央国企/地方国资/高校背景标识"),
    "f37_rd11_contract45d": ("F6_RD011_120Core", "跨年大票120因子核", "d 09:25前", "近45天中标/重大合同订单公告"),
    "f38_rd11_earn_pos90d": ("F6_RD011_120Core", "跨年大票120因子核", "d 09:25前", "近90天业绩预增/略增/扭亏公告"),
    "f39_rd11_reg_letter15d": ("F6_RD011_120Core", "跨年大票120因子核", "d 09:25前", "近15天监管函/关注函/重点监控公告"),
    "f40_rd11_mid100yi_theme": ("F6_RD011_120Core", "跨年大票120因子核", "d-1收盘", "前日题材内存在>=100亿活跃中军共振"),
    # Family 7: Rebound Heat Lock (4 factors)
    "f41_reb_brk_r10_d1": ("F7_Rebound_Lock", "断板反包热区锁", "d-1已结算", "全市场近10日断板次日反包涨停成功率"),
    "f42_reb_4p_10d_d1": ("F7_Rebound_Lock", "断板反包热区锁", "d-1已结算", "4板+断板近10日次日红盘率"),
    "f43_reb_mkt_max_board_d1": ("F7_Rebound_Lock", "断板反包热区锁", "d-1收盘", "前日全市场10cm最高连板高度"),
    "f44_reb_is_rebound_stk": ("F7_Rebound_Lock", "断板反包热区锁", "d-1收盘", "个股本身前日刚完成断板反包涨停"),
    # Family 8: LHB Bayes & Lhasa 3-State (5 factors)
    "f45_lhb_bayes_t2_d1": ("F8_LHB_Bayes_Lhasa", "游资250日贝叶斯与拉萨", "d-1龙虎榜", "前日买方席位250日滚动贝叶斯超额分"),
    "f46_lhb_lhasa_state_d1": ("F8_LHB_Bayes_Lhasa", "游资250日贝叶斯与拉萨", "d-1龙虎榜", "拉萨三态(净卖+1/无榜0/净买-1)"),
    "f47_lhb_lhasa_net_buy_d1": ("F8_LHB_Bayes_Lhasa", "游资250日贝叶斯与拉萨", "d-1龙虎榜", "前日非三日榜拉萨净买入"),
    "f48_lhb_lhasa_net_sell_d1": ("F8_LHB_Bayes_Lhasa", "游资250日贝叶斯与拉萨", "d-1龙虎榜", "前日非三日榜拉萨净卖出"),
    "f49_lhb_org_net_yi_d1": ("F8_LHB_Bayes_Lhasa", "游资250日贝叶斯与拉萨", "d-1龙虎榜", "前日非三日榜机构席位净买额(亿元)"),
    # Family 9: Ladder Gap, 20cm Suppression & Mcap Structure (11 factors)
    "f50_lad_gap_A_d1": ("F9_Ladder_20cm_Mcap", "连板断层真空日", "d-1收盘", "连板断层TypeA(4-6板全0且1+2板>=30)"),
    "f51_lad_gap_B_d1": ("F9_Ladder_20cm_Mcap", "连板断层真空日", "d-1收盘", "连板断层TypeB(前日最高板<=2)"),
    "f52_lad_3p_cnt_d1": ("F9_Ladder_20cm_Mcap", "连板断层真空日", "d-1收盘", "前日全市场3板及以上家数"),
    "f53_lad_s1_promo_d1": ("F9_Ladder_20cm_Mcap", "连板断层真空日", "d-1已结算", "前日已结算首板晋级二板率"),
    "f54_c20_fb20_cln_cnt": ("F9_Ladder_20cm_Mcap", "20cm跨板抑制", "d-1收盘", "前日20cm干净首板家数(1to2 V20已用-25)"),
    "f55_c20_a76_flag": ("F9_Ladder_20cm_Mcap", "20cm跨板抑制", "d 09:25", "20cm V11 A>=76分强势分流日"),
    "f56_c20_mkt20_zt_d1": ("F9_Ladder_20cm_Mcap", "20cm跨板抑制", "d-1收盘", "前日20cm非ST涨停总数"),
    "f57_c20_mkt20_dt_d1": ("F9_Ladder_20cm_Mcap", "20cm跨板抑制", "d-1收盘", "前日20cm非ST跌停总数"),
    "f58_mcap_yi_d1": ("F9_Ladder_20cm_Mcap", "首板大市值vs高标小市值", "d-1收盘", "前日总市值(亿元)"),
    "f59_mcap_log_d1": ("F9_Ladder_20cm_Mcap", "首板大市值vs高标小市值", "d-1收盘", "前日log(1+总市值亿元)"),
    "f60_free_mcap_yi_d1": ("F9_Ladder_20cm_Mcap", "首板大市值vs高标小市值", "d-1收盘", "前日PIT剔除十大流通冻结后自由市值(亿元)"),
}


def compute_dsr_and_hlz(dr: np.ndarray, m_trials: int = 300) -> dict:
    """Daily Deflated Sharpe Ratio (Bailey-Lopez de Prado) & HLZ t-stat."""
    r = np.asarray(dr, dtype=float)
    r = r[np.isfinite(r)]
    t_len = len(r)
    if t_len < 30 or np.std(r, ddof=1) < 1e-12:
        return {"sr_daily": 0.0, "hlz_t": 0.0, "dsr_m300": 0.0, "skew": 0.0, "kurt": 3.0}
    mu = float(np.mean(r))
    sd = float(np.std(r, ddof=1))
    sr = mu / sd
    hlz_t = mu / (sd / math.sqrt(t_len))
    sk = float(stats.skew(r))
    ku = float(stats.kurtosis(r, fisher=False))
    euler_g = 0.5772156649
    # Expected max SR under null across M independent-equivalent trials (~N/3)
    m_eff = max(10.0, float(m_trials))
    sr0 = math.sqrt(1.0 / t_len) * (
        (1.0 - euler_g) * stats.norm.ppf(1.0 - 1.0 / m_eff)
        + euler_g * stats.norm.ppf(1.0 - 1.0 / (m_eff * math.e))
    )
    denom_sq = max(1e-8, 1.0 - sk * sr + ((ku - 1.0) / 4.0) * (sr ** 2))
    z_dsr = (sr - sr0) * math.sqrt(t_len - 1.0) / math.sqrt(denom_sq)
    return {
        "sr_daily": round(sr, 4),
        "hlz_t": round(hlz_t, 3),
        "dsr_m300": round(float(stats.norm.cdf(z_dsr)), 4),
        "skew": round(sk, 3),
        "kurt": round(ku, 3),
    }


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if (np.isnan(obj) or np.isinf(obj)) else float(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj
