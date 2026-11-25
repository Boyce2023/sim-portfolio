#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Track B2 Core 1 Part A: >=60 Strictly PIT Atomic Factors Scan (Spearman IC, BH-FDR, V1.1 Collinearity)."""
import sys
import numpy as np
import pandas as pd
from scipy import stats

assert "yfinance" not in sys.modules, "D12 violation"
from b2_mod_eval import bh_fdr

# (fid, module, desc, col, exp_dir_hint)
ATOMIC_LIST = [
    # M1: US Overnight Transmission (6)
    ("M01_us_ixic_ret", "M1_美股隔夜", "隔夜纳指涨跌幅", "us_ixic_ret", 1),
    ("M01_us_gspc_ret", "M1_美股隔夜", "隔夜标普500涨跌幅", "us_gspc_ret", 1),
    ("M01_us_vix_ret", "M1_美股隔夜", "隔夜VIX恐慌变化", "us_vix_ret", -1),
    ("M01_us_vix_level", "M1_美股隔夜", "隔夜VIX绝对水平", "us_vix_level", -1),
    ("M01_us_ixic_dn15", "M1_美股隔夜", "隔夜纳指大跌<=-1.5%", "us_ixic_drop15_flag", 1),
    ("M01_us_ixic_panic_open", "M1_美股隔夜", "隔夜纳指<=-1.5%叠早盘深低开<=-5%", "us_ixic_drop15_panic_open", 1),
    ("M01_us_ixic10_panic_open", "M1_美股隔夜", "隔夜纳指<=-1.0%叠早盘深低开<=-5%", "us_ixic_drop10_panic_open", 1),
    ("M01_us_ixic_mkt20_gap", "M1_美股隔夜", "隔夜纳指<=-1.5%叠20cm板块低开<=-0.5%", "us_ixic_drop15_mkt_lowopen", 1),
    # M2: National Team V3.0 (10)
    ("M02_nt_score_eod_d1", "M2_国家队V3", "买前国家队V3.0盘后总分", "score_eod_d1", 1),
    ("M02_nt_score_live_d1", "M2_国家队V3", "买前国家队V3.0盘中分", "score_live_d1", 1),
    ("M02_nt_core10_spk_d1", "M2_国家队V3", "买前核心10宽基ETF量比", "core10_amt_spike_d1", 1),
    ("M02_nt_wflow_yi_d1", "M2_国家队V3", "买前国家队纯净单日净申购(亿)", "etf22_wflow_yi_d1", 1),
    ("M02_nt_wflow_5d_d1", "M2_国家队V3", "买前国家队近5日净申购(亿)", "etf22_wflow_5d_d1", 1),
    ("M02_nt_hw16_cnt_d1", "M2_国家队V3", "买前16权重放量同步家数", "hw16_sync_cnt_d1", 1),
    ("M02_nt_if0_basis_d1", "M2_国家队V3", "买前IF0期指贴水/升水(%)", "if0_basis_pct_d1", -1),
    ("M02_nt_fake_supp_d1", "M2_国家队V3", "买前假护盘抽血(银行石油抽血小盘)", "fake_supp_d1", -1),
    ("M02_nt_rd019_trap_d1", "M2_国家队V3", "买前RD019期现双爆量恐慌陷阱", "rd019_trap_d1", -1),
    ("M02_nt_redemp_press_d1", "M2_国家队V3", "买前国家队/机构赎回对冲压力", "redemp_press_d1", -1),
    ("M02_nt_t1_t2_sync_d1", "M2_国家队V3", "买前一二队共振(+1)vs一队偏心(-1)", "t1_t2_sync_d1", 1),
    # M3: CSRC Policy 22 Core (5)
    ("M03_pol_22_net_10d", "M3_证监会22核", "近10日证监会22核净得分", "pol_22_net_10d", 1),
    ("M03_pol_22_pos_20d", "M3_证监会22核", "近20日正面核心政策数", "pol_22_pos_20d", 1),
    ("M03_pol_22_neg_20d", "M3_证监会22核", "近20日负面核心政策数(F009/47/58)", "pol_22_neg_20d", -1),
    ("M03_pol_tech_ma_10d", "M3_证监会22核", "近10日硬科技/并购政策数", "pol_tech_ma_10d", 1),
    ("M03_pol_exch_surv_5d", "M3_证监会22核", "近5日交易所监管点名/停牌核查", "pol_exch_surv_5d", -1),
    # M4: 15Y Style / Tech / Macro (7)
    ("M04_st15_smallcap_5d", "M4_15年风格", "近5日小市值轮动策略收益", "st15_smallcap_5d_d1", 1),
    ("M04_st15_lowvol_5d", "M4_15年风格", "近5日茅指数大蓝筹低波收益", "st15_lowvol_5d_d1", -1),
    ("M04_st15_small_vs_big", "M4_15年风格", "近5日小盘相对大盘超额差", "st15_small_minus_big_5d_d1", 1),
    ("M04_st15_oversold_5d", "M4_15年风格", "近5日超跌反转策略收益", "st15_oversold_5d_d1", 1),
    ("M04_st15_ice_5d", "M4_15年风格", "近5日游资周期冰点策略收益", "st15_ice_5d_d1", 1),
    ("M04_tech15_rsi_5d", "M4_15年风格", "近5日RSI逆势策略收益", "tech15_rsi_5d_d1", 1),
    ("M04_macro15_erp_20d", "M4_15年风格", "近20日股债ERP三档择时收益", "macro15_erp_20d_d1", 1),
    # M5: Youzi 250d Bayes & Lhasa Buy/Sell 3-State (6)
    ("M05_yz_bayes_c", "M5_游资贝叶斯", "T0席位250日贝叶斯次日收盘Alpha", "yz_bayes_c", 1),
    ("M05_yz_bayes_t2", "M5_游资贝叶斯", "T0席位250日贝叶斯T+2 Alpha", "yz_bayes_t2", 1),
    ("M05_lhb_sell_lasa_net", "M5_游资贝叶斯", "T0卖榜纯拉萨净卖出额(万元)", "lhb_sell_lasa_net_sell", -1),
    ("M05_lhb_sell_lasa_sh", "M5_游资贝叶斯", "T0卖榜拉萨占卖额比例", "lhb_sell_lasa_share", -1),
    ("M05_lhb_buy_lasa_sh", "M5_游资贝叶斯", "T0买榜拉萨占买额比例", "lhb_buy_lasa_share", -1),
    ("M05_lhb_famous_yz_net", "M5_游资贝叶斯", "T0活跃知名游资净买入(万元)", "lhb_famous_yz_net", 1),
    ("M05_lhb_surf_flag", "M5_游资贝叶斯", "T0纯一日游席位(上塘/绿景等)出现", "lhb_surf_flag", -1),
    # M6: Cross-Year V4 / 30d200 Abnormality / CNINFO IR & Notices (6)
    ("M06_abn_tight_headroom", "M6_异动与公告", "10日100%/30日200%最紧异动余量", "abn_tight_headroom", 1),
    ("M06_abn_dist_10d100", "M6_异动与公告", "距10日100%异动余量", "dist_10d100", 1),
    ("M06_abn_dist_30d200", "M6_异动与公告", "距30日200%异动余量", "dist_30d200", 1),
    ("M06_cninfo_ir_30d", "M6_异动与公告", "买前30天互动易/调研次数(PIT)", "cninfo_ir_30d", 1),
    ("M06_cninfo_pos_45d", "M6_异动与公告", "买前45天预增/中标/回购正面公告数", "cninfo_pos_45d", 1),
    ("M06_cninfo_reg_neg_30d", "M6_异动与公告", "买前30天问询/减持/亏损负面公告数", "cninfo_reg_neg_30d", -1),
    # M7: RD012 Defensive Switch (4)
    ("M07_rd012_shrink_bank", "M7_RD012防御", "买前缩量银行假护盘(量<20均&银行涨)", "rd012_shrink_bank_fake_d1", -1),
    ("M07_rd012_panic_crash", "M7_RD012防御", "买前放量暴跌日(量>=20均&300<=-2%)", "rd012_panic_crash_d1", -1),
    ("M07_rd012_tech_retreat", "M7_RD012防御", "买前科技板块大退潮日(<=-2%)", "rd012_tech_retreat_d1", -1),
    ("M07_rd012_bank_m_tech", "M7_RD012防御", "买前银行减科技涨幅差(翘翘板)", "rd012_bank_minus_tech_d1", -1),
    # M8: RD013 Broken-Board Rebound (2)
    ("M08_rd013_brk_r10", "M8_断板反包", "买前10日全市场断板次日反包涨停率", "brk_r10_d1", 1),
    ("M08_rd013_reb4_10d", "M8_断板反包", "买前10日4板+高标断板次日反抽红率", "reb4_10d_d1", 1),
    # M9: Streak Gap 连板断层 (4)
    ("M09_gap_max_streak10", "M9_连板断层", "买前10cm最高连板高度", "max_streak_10cm_d1", 1),
    ("M09_gap_void_defA", "M9_连板断层", "连板断层定义A(4至6板真空&1+2>=30)", "gap_void_defA_d1", -1),
    ("M09_gap_ice_defB", "M9_连板断层", "连板断层定义B(最高<=2板&3+板=0)", "gap_ice_defB_d1", 1),
    ("M09_gap_old_dragon_brk", "M9_连板断层", "近2日存在4板+老龙断板退潮", "old_dragon_brk_1_2d_d1", -1),
    # M10: Theme Co-occurrence / Cap Paradox / Seal Micro (5)
    ("M10_kpl_10_20_zt", "M10_题材微观", "T0同题材10cm+20cm涨停共振数", "kpl_10_20_zt", 1),
    ("M10_zt_mins", "M10_题材微观", "T0首次封板耗时(分钟)", "zt_mins", -1),
    ("M10_zt_obc", "M10_题材微观", "T0封板开板次数(烂板度)", "zt_obc", -1),
    ("M10_rfm_pct_all20", "M10_题材微观", "T0真实流值在当日20cm分位", "rfm_pct_all20", -1),
    ("M10_seal_to_rfm", "M10_题材微观", "T0封单额占真实自由流值比", "micro_seal_to_rfm", 1),
    # M11: Commodities + Oversold Pry Entry DNA (9)
    ("M11_comm_gc_ret", "M11_商品与撬板", "隔夜COMEX黄金涨跌幅", "comm_gc_ret", -1),
    ("M11_comm_cl_ret", "M11_商品与撬板", "隔夜WTI原油涨跌幅", "comm_cl_ret", 1),
    ("M11_mkt_dt_cnt_d1", "M11_商品与撬板", "买前全市场非ST跌停家数", "mkt_all_nonst_dt_d1", -1),
    ("M11_mkt_dt_spike20_d1", "M11_商品与撬板", "买前跌停数相对20日均倍数", "mkt_dt_spike20_d1", -1),
    ("M11_mkt_0925_zt", "M11_商品与撬板", "买日09:25全市场非ST竞价涨停数", "mkt_all_nonst_0925_zt", 1),
    ("M11_pry_prev_bias20", "M11_商品与撬板", "首板前20日均线乖离率(超跌)", "prev_bias20", -1),
    ("M11_pry_prev_pos60", "M11_商品与撬板", "首板前60日区间价格位置", "prev_pos60", -1),
    ("M11_pry_down_streak", "M11_商品与撬板", "首板前连续收跌天数(超跌连阴)", "pry_down_streak_pre", 1),
    ("M11_pry_vol_ratio5", "M11_商品与撬板", "T0首板相对5日均量倍数", "vol_ratio5", 1),
    ("M11_pry_dt_cnt_10d", "M11_商品与撬板", "T0前10日个股自身跌停次数", "dt_cnt_10d", 1),
    ("M11_pry_lock_top10", "M11_商品与撬板", "十大股东/自由流通锁仓比例(%)", "lock_top10", 1),
]


def _sp(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 12 or np.std(x[m]) < 1e-12 or np.std(y[m]) < 1e-12:
        return 0.0, 1.0, int(m.sum())
    r, p = stats.spearmanr(x[m], y[m])
    return (0.0 if np.isnan(r) else float(r)), (1.0 if np.isnan(p) else float(p)), int(m.sum())


def run_atomic_ic_scan(df20: pd.DataFrame, v11_fcols: list[str]) -> list[dict]:
    y = df20["net_ret"].to_numpy(float)
    bdt = df20["buy_date"].to_numpy()
    m_is = bdt <= "2024-06-30"
    m_oob = bdt >= "2024-07-04"
    m_oort = bdt >= "2024-09-01"
    m_y26 = bdt >= "2026-01-01"
    v11_mat = np.column_stack([df20[f"V11_{c}"].to_numpy(float) for c in v11_fcols])

    rows, p_full, p_oob = [], [], []
    for fid, mod, desc, col, hint in ATOMIC_LIST:
        x = pd.to_numeric(df20[col], errors="coerce").to_numpy(float)
        ic_f, pf, n_f = _sp(x, y)
        ic_is, pis, _ = _sp(x[m_is], y[m_is])
        ic_oob, poob, _ = _sp(x[m_oob], y[m_oob])
        ic_oort, poort, _ = _sp(x[m_oort], y[m_oort])
        ic_y26, py26, _ = _sp(x[m_y26], y[m_y26])
        max_corr, corr_nm = 0.0, ""
        for j, fc in enumerate(v11_fcols):
            cr, _, _ = _sp(x, v11_mat[:, j])
            if abs(cr) > max_corr:
                max_corr, corr_nm = abs(cr), fc
        p_full.append(pf); p_oob.append(poob)
        rows.append({
            "fid": fid, "module": mod, "desc": desc, "col": col, "hint_dir": hint, "n_valid": n_f,
            "ic_full": round(ic_f, 4), "p_full": round(pf, 5),
            "ic_is": round(ic_is, 4), "ic_oos_blind": round(ic_oob, 4), "p_oos_blind": round(poob, 5),
            "ic_oos_rt": round(ic_oort, 4), "ic_y26": round(ic_y26, 4),
            "same_sign_is_oos": bool(ic_is * ic_oob > 0 and abs(ic_is) >= 0.03 and abs(ic_oob) >= 0.03),
            "max_corr_v11": round(max_corr, 4), "max_corr_v11_factor": corr_nm,
        })
    qf = bh_fdr(p_full)
    qo = bh_fdr(p_oob)
    for i, r in enumerate(rows):
        r["q_full_bh"] = qf[i]
        r["q_oos_blind_bh"] = qo[i]
    return rows
