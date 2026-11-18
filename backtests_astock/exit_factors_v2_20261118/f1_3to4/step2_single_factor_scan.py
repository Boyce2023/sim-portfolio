#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step2_single_factor_scan.py
1. 0.0 误差核验基准引擎 (95笔 1799.9931x & 31笔 16.7204x)
2. 为全部核心池交易预计算 XF01~XF29 逐日持仓 PIT 因子状态
3. 对 XF01~XF29 全部 29 项因子 × 4 种卖点动作做系统扫描：
   - 严格先在 IS (2021-11-15 ~ 2023-12-31) 看数据（兼顾 90分44笔、78分+84笔大样本及 IS22/IS23 早晚同向）
   - 同步记录全盲 OOS (2024-01-01 ~ 2026-11-16) 真实表现用于 100% 透明披露与证伪检验
"""

import os
import sys
import time
import pickle
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_factors_v2_20261118/f1_3to4"
UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, OUT_DIR)

import exit_factor_engine as efe


def verify_baseline(cache: dict, states: dict) -> dict:
    b90 = efe.evaluate_rule(cache, states, None, "BASE_V40_90", 90.0)
    b102 = efe.evaluate_rule(cache, states, None, "BASE_V40_102", 102.0)
    b78 = efe.evaluate_rule(cache, states, None, "BASE_V40_78", 78.0)

    ref90 = pd.read_csv(f"{UPG_DIR}/ledger_upg_3to4_std.csv", dtype={"code": str})
    ref102 = pd.read_csv(f"{UPG_DIR}/ledger_upg_3to4_strict.csv", dtype={"code": str})
    for lbl, cur, ref in [("std90", b90["slot_df"], ref90), ("strict102", b102["slot_df"], ref102)]:
        cur_r = cur.reset_index(drop=True)
        assert len(cur_r) == len(ref), f"{lbl} len mismatch: {len(cur_r)} vs {len(ref)}"
        assert (cur_r["code"] == ref["code"].str.zfill(6)).all()
        assert (cur_r["buy_date"] == ref["buy_date"]).all()
        assert (cur_r["exit_date"] == ref["exit_date"]).all()
        assert np.max(np.abs(cur_r["net_ret"].round(6) - ref["net_ret"])) == 0.0

    print(f"[BASELINE 0.0 DIFF VERIFIED]")
    print(f"  90分 : IS_1S={b90['IS']['nav_1s']}x (EQ={b90['IS']['eq_nav']}x) | OOS_1S={b90['OOS']['nav_1s']}x (EQ={b90['OOS']['eq_nav']}x) | 5Y_1S={b90['ALL_5Y']['nav_1s']}x")
    print(f"  78分+: IS_1S={b78['IS']['nav_1s']}x (EQ={b78['IS']['eq_nav']}x, N={b78['IS']['raw_n']}) | OOS_1S={b78['OOS']['nav_1s']}x (EQ={b78['OOS']['eq_nav']}x, N={b78['OOS']['raw_n']})")
    print(f"  102S : IS_1S={b102['IS']['nav_1s']}x | OOS_1S={b102['OOS']['nav_1s']}x | 5Y_1S={b102['ALL_5Y']['nav_1s']}x")
    return {"90": b90, "78": b78, "102": b102}


def build_factor_specs() -> list:
    """定义全部 XF01~XF29 因子及待测阈值/方向（含危险因子与保护因子）"""
    # (xf_id, var_id, group, name, polarity, fn_trigger(st, ctx))
    # polarity: "danger" (命中触发卖/收紧/剥夺免死) or "safe" (命中保护/豁免/仅安全时免死)
    specs = [
        # Group 1: LHB (t-1)
        ("XF01_lhasa_surge", "xf01_2", "G1_LHB", "t-1拉萨>=2家或买占比>=20%", "danger", lambda st, ctx: bool(st.get("xf01_2"))),
        ("XF01_lhasa_surge", "xf01_3", "G1_LHB", "t-1拉萨>=3家或买占比>=25%", "danger", lambda st, ctx: bool(st.get("xf01_3"))),
        ("XF02_daysurf_in", "xf02", "G1_LHB", "t-1一日游游资买入", "danger", lambda st, ctx: bool(st.get("xf02"))),
        ("XF03_inst_dump", "xf03_net", "G1_LHB", "t-1机构专用净卖出", "danger", lambda st, ctx: bool(st.get("xf03_net"))),
        ("XF03_inst_dump", "xf03_20m", "G1_LHB", "t-1机构卖出>2000万", "danger", lambda st, ctx: bool(st.get("xf03_20m"))),
        ("XF04_top_yz_exit", "xf04_exit", "G1_LHB", "此前顶级游资t-1净卖出清仓", "danger", lambda st, ctx: bool(st.get("xf04_exit"))),
        ("XF04_top_yz_exit", "xf04_lock", "G1_LHB", "此前顶级游资锁仓护航(保护)", "safe", lambda st, ctx: bool(st.get("xf04_lock"))),
        ("XF05_net_buy_overheat", "xf05_12", "G1_LHB", "t-1龙虎榜净买/成交额>12%", "danger", lambda st, ctx: bool(st.get("xf05_12"))),
        ("XF05_net_buy_overheat", "xf05_15", "G1_LHB", "t-1龙虎榜净买/成交额>15%", "danger", lambda st, ctx: bool(st.get("xf05_15"))),
        ("XF06_quant_churn", "xf06", "G1_LHB", "t-1量化双边做T且拉萨跟风", "danger", lambda st, ctx: bool(st.get("xf06"))),

        # Group 2: Notices & Reg (< t 09:25)
        ("XF07_stock_reg_hit", "xf07_new", "G2_RegNotice", "持仓期新增个股监管/重点监控", "danger", lambda st, ctx: bool(st.get("xf07_new"))),
        ("XF07_stock_reg_hit", "xf07_10d", "G2_RegNotice", "近10日含持仓新增个股监管", "danger", lambda st, ctx: bool(st.get("xf07_10d"))),
        ("XF08_clarify_or_tox", "xf08", "G2_RegNotice", "持仓期澄清/严重异动风险提示/减持", "danger", lambda st, ctx: bool(st.get("xf08"))),
        ("XF08_clarify_or_tox", "xf08_strict", "G2_RegNotice", "持仓期澄清或股东减持/立案", "danger", lambda st, ctx: bool(st.get("xf08_strict"))),
        ("XF09_ex_reg5_tight", "xf09_2", "G2_RegNotice", "交易所近5日监管函>=2封(V5.1标准)", "danger", lambda st, ctx: bool(st.get("xf09_2"))),
        ("XF09_ex_reg5_tight", "xf09_3", "G2_RegNotice", "交易所近5日监管函>=3封(V5.1标准)", "danger", lambda st, ctx: bool(st.get("xf09_3"))),
        ("XF09_ex_reg5_tight", "xf09_full2", "G2_RegNotice", "交易所近5日监管函>=2封(全量补全)", "danger", lambda st, ctx: bool(st.get("xf09_full2"))),
        ("XF09_ex_reg5_tight", "xf09_full3", "G2_RegNotice", "交易所近5日监管函>=3封(全量补全)", "danger", lambda st, ctx: bool(st.get("xf09_full3"))),
        ("XF10_abn_notice_cnt", "xf10_2", "G2_RegNotice", "近10日异常波动公告>=2次", "danger", lambda st, ctx: bool(st.get("xf10_2"))),
        ("XF10_abn_notice_cnt", "xf10_3", "G2_RegNotice", "近10日异常波动公告>=3次", "danger", lambda st, ctx: bool(st.get("xf10_3"))),
        ("XF11_ir_pit", "xf11_new", "G2_RegNotice", "持仓期机构调研突发(危险检验)", "danger", lambda st, ctx: bool(st.get("xf11_new"))),
        ("XF11_ir_pit", "xf11_7d_safe", "G2_RegNotice", "近7日有机构调研(保护检验)", "safe", lambda st, ctx: bool(st.get("xf11_7d"))),

        # Group 3: Community (< t 09:25)
        ("XF12_xq_explode", "xf12_4", "G3_Community", "持仓24h雪球暴增>=4帖", "danger", lambda st, ctx: bool(st.get("xf12_4"))),
        ("XF12_xq_explode", "xf12_8", "G3_Community", "持仓24h雪球暴增>=8帖", "danger", lambda st, ctx: bool(st.get("xf12_8"))),
        ("XF12_xq_explode", "xf12_15", "G3_Community", "持仓24h雪球暴增>=15帖", "danger", lambda st, ctx: bool(st.get("xf12_15"))),
        ("XF12_xq_explode", "xf12_cum8", "G3_Community", "D1起雪球累计>=8帖", "danger", lambda st, ctx: bool(st.get("xf12_cum8"))),
        ("XF13_guba_surge", "xf13_3x", "G3_Community", "t-1股吧发帖>=买前3日均3x", "danger", lambda st, ctx: bool(st.get("xf13_3x"))),
        ("XF13_guba_surge", "xf13_5x", "G3_Community", "t-1股吧发帖>=买前3日均5x", "danger", lambda st, ctx: bool(st.get("xf13_5x"))),
        ("XF14_xq_still_quiet", "xf14_24h", "G3_Community", "持仓24h雪球仍<4帖(暗牌延续)", "safe", lambda st, ctx: bool(st.get("xf14_24h"))),
        ("XF14_xq_still_quiet", "xf14_cum", "G3_Community", "D1起雪球累计仍<4帖(强暗牌)", "safe", lambda st, ctx: bool(st.get("xf14_cum"))),

        # Group 4: 09:25 Sector & Market Auction + Ecology
        ("XF15_mates_nuke_0925", "xf15_15", "G4_AuctionMacro", "09:25同板块队友均开<-1.5%或跌停", "danger", lambda st, ctx: bool(st.get("xf15_15"))),
        ("XF15_mates_nuke_0925", "xf15_25", "G4_AuctionMacro", "09:25同板块队友均开<-2.5%或跌停", "danger", lambda st, ctx: bool(st.get("xf15_25"))),
        ("XF16_lone_wolf_0925", "xf16", "G4_AuctionMacro", "09:25同板块无一字且无>=3%助攻小弟", "danger", lambda st, ctx: bool(st.get("xf16"))),
        ("XF17_mkt_fb_open_neg", "xf17_zt", "G4_AuctionMacro", "09:25全场昨涨停今开均值<0%", "danger", lambda st, ctx: bool(st.get("xf17_zt"))),
        ("XF17_mkt_fb_open_neg", "xf17_fb", "G4_AuctionMacro", "09:25全场昨首板今开均值<0%", "danger", lambda st, ctx: bool(st.get("xf17_fb"))),
        ("XF18_mkt_climax_100", "xf18_95", "G4_AuctionMacro", "t-1非ST涨停>=95或封板率>=80%", "danger", lambda st, ctx: bool(st.get("xf18_95"))),
        ("XF18_mkt_climax_100", "xf18_100", "G4_AuctionMacro", "t-1非ST涨停>=100或封板率>=80%", "danger", lambda st, ctx: bool(st.get("xf18_100"))),
        ("XF19_promo_freeze", "xf19_12", "G4_AuctionMacro", "近5日1进2晋级率<13%冰点", "danger", lambda st, ctx: bool(st.get("xf19_12"))),
        ("XF19_promo_freeze", "xf19_2p", "G4_AuctionMacro", "近5日2+板晋级率<25%冰点", "danger", lambda st, ctx: bool(st.get("xf19_2p"))),
        ("XF20_dragon_usurped", "xf20_plt", "G4_AuctionMacro", "t-1同板块出现更高板位新龙头卡位", "danger", lambda st, ctx: bool(st.get("xf20_plt"))),
        ("XF20_dragon_usurped", "xf20_mkt", "G4_AuctionMacro", "t-1全场存在更高板位新龙头", "danger", lambda st, ctx: bool(st.get("xf20_mkt"))),
        ("XF21_elo_overheat", "xf21_135", "G4_AuctionMacro", "主概念动态Elo>=135过热", "danger", lambda st, ctx: bool(st.get("xf21_135"))),
        ("XF21_elo_overheat", "xf21_145", "G4_AuctionMacro", "主概念动态Elo>=145极度过热", "danger", lambda st, ctx: bool(st.get("xf21_145"))),
        ("XF22_csi300_slump", "xf22", "G4_AuctionMacro", "沪深300昨跌>=2%或5日跌>=2.5%", "danger", lambda st, ctx: bool(st.get("xf22"))),

        # Group 5: Break-Board Rebound Ecology & Micro-Tape
        ("XF23_rebound_rate10", "xf23_dt_cold", "G5_BreakTape", "近10日高标断板跌停率<20%(高标冷区)", "danger", lambda st, ctx: bool(st.get("xf23_dt_cold"))),
        ("XF23_rebound_rate10", "xf23_reb15", "G5_BreakTape", "近10日高标断板次日反包率<15%", "danger", lambda st, ctx: bool(st.get("xf23_reb15"))),
        ("XF23_rebound_rate10", "xf23_reb20", "G5_BreakTape", "近10日高标断板次日反包率<20%", "danger", lambda st, ctx: bool(st.get("xf23_reb20"))),
        ("XF24_high_dragon_score_judge", "xf24_lt78", "G5_BreakTape", "断板日高标V5.1打分<78或否决", "danger", lambda st, ctx: bool(st.get("xf24_veto")) or int(st.get("xf24_sc", 0)) < 78),
        ("XF24_high_dragon_score_judge", "xf24_lt84", "G5_BreakTape", "断板日高标V5.1打分<84或否决", "danger", lambda st, ctx: bool(st.get("xf24_veto")) or int(st.get("xf24_sc", 0)) < 84),
        ("XF24_high_dragon_score_judge", "xf24_lt88", "G5_BreakTape", "断板日高标V5.1打分<88或否决", "danger", lambda st, ctx: bool(st.get("xf24_veto")) or int(st.get("xf24_sc", 0)) < 88),
        ("XF25_late_rotten_seal", "xf25_1400", "G5_BreakTape", "t-1尾盘>=14:00封板或炸板>=3次", "danger", lambda st, ctx: bool(st.get("xf25_1400"))),
        ("XF25_late_rotten_seal", "xf25_1430", "G5_BreakTape", "t-1尾盘>=14:30封板或炸板>=3次", "danger", lambda st, ctx: bool(st.get("xf25_1430"))),
        ("XF26_tiny_seal_ratio", "xf26_10", "G5_BreakTape", "t-1涨停封成比<1.0%纸糊封单", "danger", lambda st, ctx: bool(st.get("xf26_10"))),
        ("XF26_tiny_seal_ratio", "xf26_05", "G5_BreakTape", "t-1涨停封成比<0.5%极弱封单", "danger", lambda st, ctx: bool(st.get("xf26_05"))),
        ("XF27_death_turnover", "xf27_32", "G5_BreakTape", "t-1换手>32%或真换手>65%", "danger", lambda st, ctx: bool(st.get("xf27_32"))),
        ("XF27_death_turnover", "xf27_35", "G5_BreakTape", "t-1换手>35%或真换手>65%", "danger", lambda st, ctx: bool(st.get("xf27_35"))),
        ("XF27_death_turnover", "xf27_k35", "G5_BreakTape", "断板当日换手>35%或真换手>65%", "danger", lambda st, ctx: bool(st.get("xf27_k35"))),
        ("XF28_vol_blowoff", "xf28_35", "G5_BreakTape", "t-1成交额>3.5x 5日均量爆量", "danger", lambda st, ctx: bool(st.get("xf28_35"))),
        ("XF28_vol_blowoff", "xf28_40", "G5_BreakTape", "t-1成交额>4.0x 5日均量爆量", "danger", lambda st, ctx: bool(st.get("xf28_40"))),
        ("XF29_upper_wick_grave", "xf29_grave", "G5_BreakTape", "断板日长上影墓碑线", "danger", lambda st, ctx: bool(st.get("xf29_grave"))),
        ("XF29_upper_wick_grave", "xf29_leg", "G5_BreakTape", "断板日探底大长腿>=5%(保护)", "safe", lambda st, ctx: bool(st.get("xf29_leg"))),
    ]
    return specs


def make_action_rule(polarity: str, trig_fn, action_id: str):
    if polarity == "danger":
        if action_id == "A1_all_0925":
            return lambda st, ctx: {"cut_0925": trig_fn(st, ctx)}
        if action_id == "A1_hold_0925":
            return lambda st, ctx: {"cut_0925": (not ctx["is_d4_unsealed"]) and trig_fn(st, ctx)}
        if action_id == "A1_after_imm_0925":
            return lambda st, ctx: {"cut_0925": ctx["just_used_imm"] and trig_fn(st, ctx)}
        if action_id == "A1_d5_strip":
            return lambda st, ctx: {"d5_strip": ctx["is_d4_unsealed"] and trig_fn(st, ctx)}
        if action_id == "A2_1030vwap":
            return lambda st, ctx: {"tight_1030vwap": trig_fn(st, ctx)}
        if action_id == "A2_1345_d70":
            return lambda st, ctx: {"tight_1345_thr": 0.070 if trig_fn(st, ctx) else 0.050}
        if action_id == "A2_1345_d60":
            return lambda st, ctx: {"tight_1345_thr": 0.060 if trig_fn(st, ctx) else 0.050}
        if action_id == "A2_1430rush":
            return lambda st, ctx: {"tight_1430rush": trig_fn(st, ctx)}
        if action_id == "A3_dev93_5b":
            return lambda st, ctx: {"cond_dev_ratio": 0.93 if (ctx["boards"] >= 5 and trig_fn(st, ctx)) else None}
        if action_id == "A3_dev96_5b":
            return lambda st, ctx: {"cond_dev_ratio": 0.96 if (ctx["boards"] >= 5 and trig_fn(st, ctx)) else None}
        if action_id == "A3_dev93_all":
            return lambda st, ctx: {"cond_dev_ratio": 0.93 if trig_fn(st, ctx) else None}
        if action_id == "A4_strip_imm":
            return lambda st, ctx: {"strip_imm": trig_fn(st, ctx)}
    else:  # safe
        if action_id == "A1_d5_exempt":
            return lambda st, ctx: {"d5_exempt": ctx["is_d4_unsealed"] and trig_fn(st, ctx)}
        if action_id == "A4_require_safe":
            # 仅在真阳线且安全因子满足时才给免死；否则剥夺免死
            return lambda st, ctx: {"strip_imm": not trig_fn(st, ctx)}
        if action_id == "A4_grant_any_yang":
            # 更宽容：只要安全因子命中，即使平盘/微跌真阳也可免死 (在非跌停日测试)
            return lambda st, ctx: {"d5_exempt": False}  # handled specifically if needed
    raise ValueError(f"Unknown action {polarity}/{action_id}")


def main():
    t0 = time.time()
    with open(f"{OUT_DIR}/pit_exit_cache_full.pkl", "rb") as f:
        cache = pickle.load(f)

    print("[Step2] Precomputing holding-day factor states for all buyable core trades (351 trades)...")
    states = precompute_trade_day_states_fast(cache) if False else efe.precompute_trade_day_states(cache, min_score=0.0)
    print(f"[Step2] States built for {len(states)} trades in {time.time()-t0:.1f}s")

    base = verify_baseline(cache, states)

    # 先快速统计每个因子的持仓期触发次数（IS 90分 & IS 78分+ & OOS 90分），零遗漏披露覆盖度
    specs = build_factor_specs()
    b90_raw = base["90"]["raw_df"].set_index("idx")
    b78_raw = base["78"]["raw_df"].set_index("idx")
    b102_raw = base["102"]["raw_df"].set_index("idx")

    # 确定各动作列表
    DANGER_ACTIONS = [
        "A1_all_0925", "A1_hold_0925", "A1_after_imm_0925", "A1_d5_strip",
        "A2_1030vwap", "A2_1345_d70", "A2_1345_d60", "A2_1430rush",
        "A3_dev93_5b", "A3_dev96_5b", "A3_dev93_all",
        "A4_strip_imm",
    ]
    SAFE_ACTIONS = ["A1_d5_exempt", "A4_require_safe"]

    rows = []
    # 只为 XF24_lt78 / lt84 / lt88 测 A4_strip_imm（因为 XF24 定义在断板日）与 A1_after_imm（不过断板当日就走无需次日）
    # 对于 XF29_grave / xf29_leg 与 xf27_k35 也属于断板日 14:55 因子，仅限 A4 动作以严守不偷看当日收盘的铁律！
    CLOSE_DAY_ONLY_VARS = {"xf24_lt78", "xf24_lt84", "xf24_lt88", "xf27_k35", "xf29_grave", "xf29_leg"}

    for xf_id, var_id, grp, desc, pol, fn in specs:
        if var_id in CLOSE_DAY_ONLY_VARS:
            act_list = ["A4_strip_imm"] if pol == "danger" else ["A4_require_safe"]
        else:
            act_list = DANGER_ACTIONS if pol == "danger" else SAFE_ACTIONS

        for act_id in act_list:
            rule = make_action_rule(pol, fn, act_id)
            r90 = efe.evaluate_rule(cache, states, rule, f"{var_id}__{act_id}", 90.0)
            r78 = efe.evaluate_rule(cache, states, rule, f"{var_id}__{act_id}", 78.0)
            r102 = efe.evaluate_rule(cache, states, rule, f"{var_id}__{act_id}", 102.0)

            # 计算实际改动交易笔数（IS & OOS in 90分 & 78分+）
            cur90 = r90["raw_df"].set_index("idx")
            chg90 = (cur90["net_ret"] - b90_raw["net_ret"]).abs() > 1e-6
            is_chg90 = int(chg90[cur90["buy_date"] <= "2023-12-31"].sum())
            oos_chg90 = int(chg90[cur90["buy_date"] >= "2024-01-01"].sum())
            is_win90 = int(((cur90["net_ret"] - b90_raw["net_ret"]) > 1e-6)[cur90["buy_date"] <= "2023-12-31"].sum())
            oos_win90 = int(((cur90["net_ret"] - b90_raw["net_ret"]) > 1e-6)[cur90["buy_date"] >= "2024-01-01"].sum())

            cur78 = r78["raw_df"].set_index("idx")
            chg78 = (cur78["net_ret"] - b78_raw["net_ret"]).abs() > 1e-6
            is_chg78 = int(chg78[cur78["buy_date"] <= "2023-12-31"].sum())
            oos_chg78 = int(chg78[cur78["buy_date"] >= "2024-01-01"].sum())
            is_win78 = int(((cur78["net_ret"] - b78_raw["net_ret"]) > 1e-6)[cur78["buy_date"] <= "2023-12-31"].sum())
            oos_win78 = int(((cur78["net_ret"] - b78_raw["net_ret"]) > 1e-6)[cur78["buy_date"] >= "2024-01-01"].sum())

            is_d1s_90 = round(r90["IS"]["nav_1s"] - base["90"]["IS"]["nav_1s"], 4)
            is_deq_90 = round(r90["IS"]["eq_nav"] - base["90"]["IS"]["eq_nav"], 4)
            is22_d1s_90 = round(r90["IS_22"]["nav_1s"] - base["90"]["IS_22"]["nav_1s"], 4)
            is23_d1s_90 = round(r90["IS_23"]["nav_1s"] - base["90"]["IS_23"]["nav_1s"], 4)
            is22_deq_90 = round(r90["IS_22"]["eq_nav"] - base["90"]["IS_22"]["eq_nav"], 4)
            is23_deq_90 = round(r90["IS_23"]["eq_nav"] - base["90"]["IS_23"]["eq_nav"], 4)

            is_d1s_78 = round(r78["IS"]["nav_1s"] - base["78"]["IS"]["nav_1s"], 4)
            is_deq_78 = round(r78["IS"]["eq_nav"] - base["78"]["IS"]["eq_nav"], 4)
            is22_deq_78 = round(r78["IS_22"]["eq_nav"] - base["78"]["IS_22"]["eq_nav"], 4)
            is23_deq_78 = round(r78["IS_23"]["eq_nav"] - base["78"]["IS_23"]["eq_nav"], 4)

            oos_d1s_90 = round(r90["OOS"]["nav_1s"] - base["90"]["OOS"]["nav_1s"], 4)
            oos_deq_90 = round(r90["OOS"]["eq_nav"] - base["90"]["OOS"]["eq_nav"], 4)
            oos_deq_78 = round(r78["OOS"]["eq_nav"] - base["78"]["OOS"]["eq_nav"], 4)
            oos_d1s_78 = round(r78["OOS"]["nav_1s"] - base["78"]["OOS"]["nav_1s"], 4)
            is_d1s_102 = round(r102["IS"]["nav_1s"] - base["102"]["IS"]["nav_1s"], 4)
            oos_d1s_102 = round(r102["OOS"]["nav_1s"] - base["102"]["OOS"]["nav_1s"], 4)

            rows.append({
                "xf_id": xf_id, "var_id": var_id, "group": grp, "desc": desc, "polarity": pol, "action": act_id,
                "is_chg90": is_chg90, "is_win90": is_win90, "oos_chg90": oos_chg90, "oos_win90": oos_win90,
                "is_chg78": is_chg78, "is_win78": is_win78, "oos_chg78": oos_chg78, "oos_win78": oos_win78,
                "is_wr90": r90["IS"]["wr_1s"], "is_dwr90": round(r90["IS"]["wr_1s"] - base["90"]["IS"]["wr_1s"], 2),
                "is_dmean90": round(r90["IS"]["raw_mean"] - base["90"]["IS"]["raw_mean"], 2),
                "is_1s_90": r90["IS"]["nav_1s"], "is_d1s_90": is_d1s_90,
                "is_eq_90": r90["IS"]["eq_nav"], "is_deq_90": is_deq_90,
                "is22_d1s_90": is22_d1s_90, "is23_d1s_90": is23_d1s_90,
                "is22_deq_90": is22_deq_90, "is23_deq_90": is23_deq_90,
                "is_eq_78": r78["IS"]["eq_nav"], "is_deq_78": is_deq_78,
                "is_1s_78": r78["IS"]["nav_1s"], "is_d1s_78": is_d1s_78,
                "is22_deq_78": is22_deq_78, "is23_deq_78": is23_deq_78,
                "is_1s_102": r102["IS"]["nav_1s"], "is_d1s_102": is_d1s_102,
                # OOS 记录 (严格只用于盲测验证与总表披露)
                "oos_wr90": r90["OOS"]["wr_1s"], "oos_dwr90": round(r90["OOS"]["wr_1s"] - base["90"]["OOS"]["wr_1s"], 2),
                "oos_dmean90": round(r90["OOS"]["raw_mean"] - base["90"]["OOS"]["raw_mean"], 2),
                "oos_1s_90": r90["OOS"]["nav_1s"], "oos_d1s_90": oos_d1s_90,
                "oos_eq_90": r90["OOS"]["eq_nav"], "oos_deq_90": oos_deq_90,
                "oos_eq_78": r78["OOS"]["eq_nav"], "oos_deq_78": oos_deq_78,
                "oos_1s_78": r78["OOS"]["nav_1s"], "oos_d1s_78": oos_d1s_78,
                "oos_1s_102": r102["OOS"]["nav_1s"], "oos_d1s_102": oos_d1s_102,
                "5y_1s_90": r90["ALL_5Y"]["nav_1s"], "5y_eq_90": r90["ALL_5Y"]["eq_nav"], "5y_1s_102": r102["ALL_5Y"]["nav_1s"],
            })

    df_all = pd.DataFrame(rows)
    df_all.to_csv(f"{OUT_DIR}/all_factor_actions_scan.csv", index=False, encoding="utf-8-sig")

    # 严格只看 IS 排序挑出通过 IS 初步筛选的规则（同时看 IS_deq_90, IS_d1s_90, IS_deq_78, IS22/IS23 同向）
    df_all["is_both_sub_90"] = (df_all["is22_deq_90"] >= -1e-6) & (df_all["is23_deq_90"] >= -1e-6) & (df_all["is_deq_90"] > 0.01)
    df_all["is_both_sub_78"] = (df_all["is22_deq_78"] >= -1e-6) & (df_all["is23_deq_78"] >= -1e-6) & (df_all["is_deq_78"] > 0.01)

    print(f"\n[SCAN DONE] Evaluated {len(df_all)} (factor_variant x action) combinations in {time.time()-t0:.1f}s")
    print("\n=== TOP 25 BY IS_EQ_90 + IS_EQ_78 (IS-ONLY VIEW) ===")
    cols_show = ["var_id", "action", "is_chg90", "is_win90", "is_d1s_90", "is_deq_90", "is22_deq_90", "is23_deq_90", "is_chg78", "is_deq_78", "is_d1s_78", "is_both_sub_90", "is_both_sub_78"]
    top_is = df_all[df_all["is_chg90"] >= 1].sort_values(["is_deq_90", "is_deq_78", "is_d1s_90"], ascending=False)
    print(top_is[cols_show].head(25).to_string(index=False))

    print("\n=== TOP 20 WHERE IS_BOTH_SUB_90 OR IS_BOTH_SUB_78 == True (IS-ONLY VIEW) ===")
    sub_pass = df_all[(df_all["is_both_sub_90"] | df_all["is_both_sub_78"]) & (df_all["is_chg78"] >= 2)].sort_values(["is_deq_90", "is_deq_78"], ascending=False)
    print(sub_pass[cols_show].head(20).to_string(index=False))

    # 每个 XF01~XF29 因子按 IS 最优动作汇总一行（只看 IS 选择代表动作，再如实打印其 OOS）
    best_per_xf = []
    for xf_id, grp_df in df_all.groupby("xf_id", sort=True):
        # 优先选 is_chg90 >= 1 且 (is_deq_90 + is_deq_78) 最高者；若无触发则选第一行
        active = grp_df[grp_df["is_chg90"] + grp_df["is_chg78"] > 0]
        if active.empty:
            pick = grp_df.iloc[0]
        else:
            pick = active.assign(_rank=active["is_deq_90"] * 2.0 + active["is_deq_78"] + active["is_d1s_90"]).sort_values("_rank", ascending=False).iloc[0]
        best_per_xf.append(pick)
    df_29 = pd.DataFrame(best_per_xf)
    df_29.to_csv(f"{OUT_DIR}/factor_29_is_best_preview.csv", index=False, encoding="utf-8-sig")
    print("\n=== ALL 29 FACTORS BEST-ON-IS SUMMARY ===")
    cols29 = ["xf_id", "var_id", "action", "is_chg90", "is_win90", "is_d1s_90", "is_deq_90", "is_deq_78", "oos_chg90", "oos_win90", "oos_d1s_90", "oos_deq_90", "oos_deq_78", "oos_d1s_102"]
    print(df_29[cols29].to_string(index=False))


if __name__ == "__main__":
    main()
