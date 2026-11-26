#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Module 1: Active Scorecard Factor Degradation Audit across all 6 V20.0 strategies."""
import sys
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation!"
from rd032_common import STRAT_CN, STRAT_HEALTH_CFG, STRATS, calc_slot_summary, perm_diff_mean, sf

# (factor_id, col, expected_sign: +1 means factor increases score/win, -1 means penalty/reduces score, human_label, weight_desc)
FACTOR_SPECS = {
    "1to2": [
        ("1T_01_rk1", "atom_rk_theme_1", +1, "第一主线题材", "+28"),
        ("1T_02_psz4", "atom_p_sz_ge4", +1, "题材涨停家数满4家", "+18"),
        ("1T_03_gran", "atom_is_gran", +1, "先锋新词或细分聚类", "+15"),
        ("1T_04_selo_hot", "atom_s_elo_hot", +1, "细分题材热度满105", "+10"),
        ("1T_05_selo_cold", "atom_s_elo_cold", -1, "细分题材热度低迷", "-10"),
        ("1T_06_wk", "atom_wk_mask", +1, "周一或节后首日", "+10"),
        ("1T_07_cat", "atom_hard_cat", +1, "硬催化或并购重组", "+18"),
        ("1T_08_dd20", "atom_dd20_deep", +1, "启动前20日深跌", "+32~+42"),
        ("1T_09_brk60", "atom_clean_brk60", +1, "60日平台首突", "+24"),
        ("1T_10_tbrk1", "atom_true_buy_rk1", +1, "板块可买竞价头名", "+35"),
        ("1T_11_mktop3", "atom_mkt_open_top3", +1, "全场可买高开前三", "+20"),
        ("1T_12_opsweet", "atom_open_sweet", +1, "高开4%至8.2%甜区", "+20"),
        ("1T_13_flock1", "atom_front_lock1", +1, "前排锁筹1只配一字", "+8"),
        ("1T_14_crowd", "atom_front_lock_crowd", -1, "前排锁筹拥挤", "-15~-22"),
        ("1T_15_tight1", "atom_tight_open1", +1, "早盘开板1次紧封", "+5"),
        ("1T_16_ir", "atom_has_ir", +1, "近8天机构调研", "+5"),
        ("1T_17_outsider", "atom_pure_outsider", -1, "外行硬蹭科技概念", "-20"),
        ("1T_18_cap90", "atom_cap_yizi_gt90", -1, "伴生一字超90亿大票", "-25"),
        ("1T_19_climax", "atom_climax_95", -1, "前日涨停满95家过热", "-10~-15"),
        ("1T_20_seal80", "atom_seal_80", -1, "前日封板率满80%", "-10"),
        ("1T_21_fb20v20", "atom_v20_fb20_pen", -1, "20cm首板深水跨板抑制", "-25"),
    ],
    "2to3": [
        ("2T_01_hhi_lo", "af_00", +1, "题材分散轮动/独大拥挤", "+6/-10"),
        ("2T_02_promo_lo", "af_01", +1, "昨晋级率低迷分歧", "+8/+5"),
        ("2T_03_maxb3", "af_02", +1, "前日最高板不超3板", "+6"),
        ("2T_04_midwarm", "af_03", +1, "板块温热/过热拥挤", "+5/-10"),
        ("2T_05_elo_ice", "af_04", +1, "板块极寒破冰", "+8"),
        ("2T_06_3b_press", "af_05", -1, "同板块已有3板压制", "-8"),
        ("2T_07_xq_hot", "af_06", -1, "雪球讨论度高", "-10/-18"),
        ("2T_08_ir20", "af_07", -1, "近20日机构调研", "-10"),
        ("2T_09_deepwash", "af_08", +1, "二板盘中深水洗盘", "+6"),
        ("2T_10_weakseal", "af_09", +1, "二板弱封/秒板死锁", "+6/-8/-16"),
        ("2T_11_pos20", "af_10", +1, "启动前20日箱体低位", "+6"),
        ("2T_12_lockturn", "af_11", +1, "高锁仓配黄金换手", "+8/+5/-8"),
        ("2T_13_green", "af_12", +1, "买入日竞价绿开承接", "+5"),
        ("2T_14_u1_tech", "af_13", +1, "传统行业跨界硬科技", "+4"),
        ("2T_15_u2_new", "af_14", +1, "细分概念15日新词", "+4"),
        ("2T_16_u3_pulse", "af_15", -1, "退潮一日游脉冲", "-8"),
        ("2T_17_u4_late", "af_16", -1, "二板14点半后偷袭封板", "-6"),
        ("2T_18_u5_yizi", "af_17", -1, "首板一字透支", "-6"),
    ],
    "3to4": [
        ("3T_01_px20", "af_00", +1, "三板收盘不超20元", "+8"),
        ("3T_02_maxb4", "af_01", +1, "前日最高板不超4板", "+8"),
        ("3T_03_zt_warm", "af_02", +1, "前日涨停35至85家温热", "+5"),
        ("3T_04_fb_peers", "af_03", +1, "同题材首板高开无一字", "+4"),
        ("3T_05_zero_lh", "af_04", +1, "三板零拉萨席位", "+4"),
        ("3T_06_elo115", "af_05", +1, "动态题材热度满115", "+3"),
        ("3T_07_3b_dt0", "af_06", +1, "前日三板零跌停", "+3"),
        ("3T_08_to_band", "af_07", +1, "三板换手9.5至28%", "+3"),
        ("3T_09_seal_am", "af_08", +1, "三板早盘换手封板", "+3"),
        ("3T_10_ex_reg", "af_09", -1, "交易所监管期", "-12"),
        ("3T_11_surf_yz", "af_10", -1, "一日游席位买入", "-12"),
        ("3T_12_not_top1", "af_11", -1, "非三板竞价头名", "-12"),
        ("3T_13_peer_dn", "af_12", -1, "同题材队友低开偏弱", "-10"),
        ("3T_14_lk_fm_bad", "af_13", -1, "低锁仓且小自由流通", "-10"),
        ("3T_15_to_oob", "af_14", -1, "三板换手越界", "-10"),
        ("3T_16_csi_dn", "af_15", -1, "沪深300大盘急跌", "-8"),
        ("3T_17_fb_yizi", "af_16", -1, "同题材首板顶一字", "-7"),
        ("3T_18_lh3", "af_17", -1, "拉萨席位满3家", "-5"),
        ("3T_19_3b_dt2", "af_18", -1, "前日三板跌停满2家", "-4"),
        ("3T_20_jan_may", "af_19", -1, "1月或5月退潮窗", "-4"),
        ("3T_21_pos20", "af_20", +1, "启动前20日箱体低位", "+5"),
        ("3T_22_xq4", "af_21", -1, "雪球盘前讨论满4帖", "-15"),
    ],
    "high": [
        ("HB_01_brk_r10", "af_brk_r10", +1, "近10日高标反包率满20%", "+12/-8"),
        ("HB_02_n_zt", "af_n_zt_low", +1, "涨停少于70家/超95家", "+10/-10"),
        ("HB_03_csi5", "af_csi5", +1, "沪深300近5日稳健", "+8/-10"),
        ("HB_04_d1_op", "af_d1_op_neg", +1, "首阴当日绿开承接", "+8"),
        ("HB_05_op2_neg", "af_op2_neg", +1, "买日绿开/平红开", "+8/+6"),
        ("HB_06_tight", "af_d0_tight", +1, "最高板零炸板紧封", "+6"),
        ("HB_07_pelo", "af_pelo_cool", +1, "题材不过热非独大", "+6"),
        ("HB_08_lh0", "af_lh1_zero", +1, "首阴零拉萨席位", "+6/-10"),
        ("HB_09_inst", "af_inst_pen", -1, "龙虎榜机构出现", "-6"),
        ("HB_10_px20", "af_px_le20", +1, "低价不超20元", "+5/-10"),
        ("HB_11_turnb4", "af_turn_b4", +1, "连板换手板满4个", "+5/-5"),
        ("HB_12_dip6", "af_d1_dip6", +1, "首阴探底大长腿", "+5"),
        ("HB_13_lk_fm", "af_lock_fmcap", +1, "高锁仓或大自由流值", "+6/-6"),
        ("HB_14_quant", "af_qu_in", +1, "量化参与配低拉萨", "+4"),
        ("HB_15_kpl5", "af_kpl_ge5", +1, "近1至3年曾出5连板", "+6/+3"),
        ("HB_16_old_th", "af_old_stk_th", +1, "老妖做熟概念/蹭新概念", "+3/-5"),
        ("HB_17_d0_lock", "af_d0_top_lock", +1, "高板日格局游资锁仓", "+5"),
        ("HB_18_lh_hvy", "af_d1_lh_hvy", -1, "首阴拉萨占比过重", "-10"),
        ("HB_19_net_pos", "af_d1_net_pos", -1, "首阴龙虎榜净买过大", "-5"),
        ("HB_20_surf", "af_d0_surf", -1, "高板日一日游买入", "-6"),
        ("HB_21_early", "af_d0_early", -1, "高板日09:35前秒封", "-5"),
        ("HB_22_tech", "af_tech_pen", -1, "高位硬科技标签", "-4"),
    ],
    "pry": [
        ("PR_01_bias10", "af_bias10", +1, "低于10日均线超15%", "+20"),
        ("PR_02_down4", "af_down4", +1, "连续收阴满4天", "+15"),
        ("PR_03_ma20", "af_ma20_22", +1, "低于20日均线超22%", "+15"),
        ("PR_04_fmcap", "af_fmcap25", +1, "真实自由流值不超25亿", "+15"),
        ("PR_05_mkt_zt", "af_mkt_zt12", +1, "早盘竞价涨停满12家", "+15"),
        ("PR_06_yang", "af_is_yang", +1, "昨日撬板收真阳", "+10"),
        ("PR_07_vr15", "af_vr15", +1, "昨日成交量超5日均量1.5倍", "+10"),
        ("PR_08_lock50", "af_lock50", +1, "前十大股东锁仓满50%", "+10"),
        ("PR_09_inst", "af_inst_b", +1, "昨日龙虎榜机构买入", "+10"),
        ("PR_10_lhasa", "af_lhasa_25", -1, "昨日拉萨买额超25%", "-20"),
    ],
    "20cm": [
        ("C20_01_gap", "F01_open_gap", +1, "低开-7%至-3%甜区", "+4/-10"),
        ("C20_02_rfm20", "F02_rfm_le20", +1, "真实自由流值不超20亿", "+4"),
        ("C20_03_dist", "F03_dist3d30_ge10", +1, "距3日30%异动余量满10%", "+4"),
        ("C20_04_zt60", "F04_zt60d_ge2", +1, "近60日20cm涨停满2次", "+5"),
        ("C20_05_seal", "F05_seal_ratio_ge10_pen", -1, "首板大封单次日低开诱多", "-5"),
        ("C20_06_inst", "F06_inst_net_pos", +1, "首板龙虎榜机构净买入", "+5"),
        ("C20_07_mkt10", "F07_mkt10_zt_gt55", +1, "前日全市场10cm涨停超55家", "+7/+4"),
        ("C20_08_yizi20", "F08_yizi20_siphon_pen", -1, "买日早盘20cm一字虹吸", "-5"),
        ("C20_09_mon", "F09_monday_pen", -1, "买入日为周一", "-8"),
    ],
}


def _eval_factor_slice(sub: pd.DataFrame, col: str, exp_sign: int, rng: np.random.Generator) -> dict:
    v = sub[col].to_numpy(float)
    r = sub["net_ret"].to_numpy(float)
    ok = np.isfinite(v) & np.isfinite(r)
    v, r = v[ok], r[ok]
    m_hit = (v > 0) if exp_sign > 0 else (v < 0)
    m_non = ~m_hit
    if m_hit.sum() == 0 or m_non.sum() == 0:
        m_hit = v != 0
        m_non = v == 0
    res = perm_diff_mean(r[m_hit], r[m_non], rng, n_perm=1000)
    if res["mean_diff_pp"] is not None:
        res["oriented_mean_edge_pp"] = sf(res["mean_diff_pp"] * exp_sign, 2)
        res["oriented_wr_edge_pp"] = sf(res["wr_diff_pp"] * exp_sign, 2)
    else:
        res["oriented_mean_edge_pp"] = None
        res["oriented_wr_edge_pp"] = None
    return res


def _classify_factor_light(s5: dict, s1: dict, sh2: dict) -> str:
    e5, e1, eh2 = s5.get("oriented_mean_edge_pp"), s1.get("oriented_mean_edge_pp"), sh2.get("oriented_mean_edge_pp")
    w5, w1, wh2 = s5.get("oriented_wr_edge_pp"), s1.get("oriented_wr_edge_pp"), sh2.get("oriented_wr_edge_pp")
    n1_ok = (s1.get("n1", 0) >= 8 and s1.get("n0", 0) >= 8)
    if e1 is None or (s1.get("n1", 0) < 3 or s1.get("n0", 0) < 3):
        return "YELLOW_SMALL_N"
    if n1_ok and (e1 < -1.5) and (w1 is not None and w1 < -3.0) and (eh2 is None or eh2 < 0.0):
        return "RED"
    if (e1 < 0.0) or (w1 is not None and w1 < -5.0) or (eh2 is not None and eh2 < -1.5 and (wh2 is not None and wh2 < -5.0)):
        return "YELLOW"
    if e5 is not None and e5 > 0 and e1 >= 0.5 * e5:
        return "GREEN"
    return "GREEN" if (e1 >= 0 and (w1 is None or w1 >= 0)) else "YELLOW"


def run_decay_audit(pools: dict, win: dict, sh300: dict, dts: list, prev_td: dict, rng: np.random.Generator) -> dict:
    strat_summary = {}
    factor_rows = []
    for st in STRATS:
        df = pools[st]
        slot = df[df["is_standalone_slot1"]].sort_values(["buy_date", "code"])
        cfg = STRAT_HEALTH_CFG[st]
        tail_n = slot.tail(cfg["n_win"])
        t_wr = float((tail_n["net_ret"] > 0).mean() * 100.0) if len(tail_n) else 0.0
        t_mn = float(tail_n["net_ret"].mean() * 100.0) if len(tail_n) else 0.0
        cur_cl = 0
        for r_v in slot["net_ret"].to_numpy(float)[::-1]:
            if r_v <= 0:
                cur_cl += 1
            else:
                break
        st_light = "RED" if (t_wr < cfg["wr_r"] or t_mn < cfg["mean_r"] or cur_cl >= cfg["cl_r"]) else (
            "YELLOW" if (t_wr < cfg["wr_y"] or t_mn < cfg["mean_y"] or cur_cl >= cfg["cl_y"]) else "GREEN"
        )
        m5 = slot
        m1 = slot[slot["buy_date"] >= win["w1y_start"]]
        mh = slot[slot["buy_date"] >= win["h_start"]]
        strat_summary[st] = {
            "name_cn": STRAT_CN[st],
            "health_light": st_light,
            "trailing_n": int(len(tail_n)),
            "trailing_wr_pct": sf(t_wr, 2),
            "trailing_mean_pct": sf(t_mn, 2),
            "curr_loss_streak": int(cur_cl),
            "slot_5y": calc_slot_summary(m5, sh300, dts, prev_td),
            "slot_1y": calc_slot_summary(m1, sh300, dts, prev_td),
            "slot_h2": calc_slot_summary(mh, sh300, dts, prev_td),
            "cand_n": {"5Y": int(len(df)), "1Y": int((df["buy_date"] >= win["w1y_start"]).sum()), "H2": int((df["buy_date"] >= win["h_start"]).sum())},
        }

        df_1y = df[df["buy_date"] >= win["w1y_start"]]
        df_h2 = df[df["buy_date"] >= win["h_start"]]
        df_pass = df[df["is_pass_official"]]
        df_pass_1y = df_pass[df_pass["buy_date"] >= win["w1y_start"]]
        for fid, col, exp_s, desc, w_str in FACTOR_SPECS[st]:
            s5 = _eval_factor_slice(df, col, exp_s, rng)
            s1 = _eval_factor_slice(df_1y, col, exp_s, rng)
            sh2 = _eval_factor_slice(df_h2, col, exp_s, rng)
            sp5 = _eval_factor_slice(df_pass, col, exp_s, rng)
            sp1 = _eval_factor_slice(df_pass_1y, col, exp_s, rng)
            light = _classify_factor_light(s5, s1, sh2)
            factor_rows.append({
                "strategy": st, "name_cn": STRAT_CN[st], "factor_id": fid, "label": desc, "weight": w_str,
                "exp_sign": exp_s, "light": light,
                "cand_5y": s5, "cand_1y": s1, "cand_h2": sh2,
                "pass_5y": sp5, "pass_1y": sp1,
            })

    return {"strategy_health": strat_summary, "factor_audit": factor_rows}
