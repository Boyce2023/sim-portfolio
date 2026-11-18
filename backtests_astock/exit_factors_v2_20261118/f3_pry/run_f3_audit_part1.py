#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_f3_audit_part1.py
1. Produces factor_30_marginal_table.csv (all 30 factors XF01..XF30 across P165/P150/P140/P000 IS & OOS)
2. Evaluates 81-point +/-20% parameter plateau around XF30_V21
3. Executes full end-to-end < 2025-01-01 physical truncation invariance test (max_abs_diff == 0.0)
"""
import os, sys, json, pickle, time
import numpy as np
import pandas as pd

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
S3_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s3_pry_exit"
F3_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry"
for d in (S3_DIR, F3_DIR):
    if d not in sys.path:
        sys.path.insert(0, d)

import run_exit_scan as base
import backtest_30_factors as bt
import factor_signals as fs


def make_xf30_spec(zt_th=5, clv_th=0.70, ndt_th=10, boost=0.03, ex_t1=True):
    def preopen_cut(off, st, ft, r):
        return bool(st.get("mkt_open_zt", 10) < zt_th)

    def tp_sched(off, st, ft, r, btp):
        if btp is None:
            return None
        b = 0.0
        if ft.get("d0_true_yang") and ft.get("d0_clv", 0.0) >= clv_th:
            b += boost
        if st.get("prev_n_dt", 99) < ndt_th:
            b += boost
        return min(0.18, btp + b) if b > 0 else btp

    def dis_eod(off, st, ft, r):
        return bool(ex_t1 and off == 1 and ft.get("d0_true_yang") and ft.get("d0_clv", 0.0) >= clv_th)

    return {"preopen_cut_fn": preopen_cut, "tp_sched_fn": tp_sched, "disable_default_eod_cut_fn": dis_eod}


def main():
    t0 = time.time()
    cache = pickle.load(open(f"{F3_DIR}/_cache_feats_830.pkl", "rb"))
    sub, feats, ctx = cache["sub"], cache["feats"], cache["ctx"]
    cb = pickle.load(open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl", "rb"))["code_bars"]

    # Map canonical 30 factors (XF01..XF30) cleanly from _raw_27_factors_scan + XF30
    raw_df = pd.read_csv(f"{F3_DIR}/_raw_27_factors_scan.csv")
    canon_map = [
        ("XF01_d0_lhasa_trap", "XF01_lhasa_cnt1_0925", "买入日/持仓期龙虎榜出现拉萨>=1家次日09:25立斩(注:>=2家仅0~2笔;IS=0)", "证伪/样本不足", "IS命中0笔仅OOS 8笔，LHB多在D0已扣分且撬板股极少D0上龙虎榜拉萨"),
        ("XF02_d0_daysurf_in", "XF02_daysurf_0925", "龙虎榜出现上塘路/佛山/消闲派/苏南帮次日09:25斩", "证伪/样本过稀", "全五年仅命中3笔(IS=0)，仅微调0.002x，不足以入模"),
        ("XF03_d0_inst_net_buy_vs_sell", "XF03c_inst_bidir", "机构净买抬高止盈+3% vs 机构净卖次日09:25斩", "证伪(单向无效)", "IS=0笔；OOS机构净卖多因大涨出榜或T+0回转，早盘斩反降低OOS单日收益(2.072->2.004)"),
        ("XF04_d0_top_youzi_in", "XF04_top_youzi_boost", "顶级游资买入格局+3% vs 游资卖出早盘斩", "证伪/样本过稀", "IS=0笔，OOS仅改变32笔且拖累P150/P140/P000，无普适性"),
        ("XF05_lhb_quant_churn", "XF05_quant_churn_0925", "龙虎榜量化席位上榜次日09:25斩", "证伪", "IS=0笔；量化席位在超跌反弹中多提供流动性而非单向砸盘，OOS砍仓拖累P165/P150"),
        ("XF06_north_or_big_net_sell", "XF06_big_net_sell_0925", "龙虎榜总卖出>1.2倍总买入次日09:25斩", "证伪", "IS=0笔；OOS四池全负贡献，超跌反弹首日主力对倒换手不等于次日崩盘"),
        ("XF07_hold_bad_notice", "XF07_bad_notice_0925", "持仓期盘后突发利空/减持/澄清/异动公告次日09:25逃命", "待观察(极端风控)", "全五年仅9笔命中(IS=0)，虽为实盘物理防黑天鹅必看项，但统计样本不足不作回测加分"),
        ("XF08_ex_reg5_ge2", "XF08_ex_reg5_ge2_0925", "所属交易所近5日监管函>=2封次日09:25斩", "证伪", "IS与OOS均跑输DecD_4d(P165_ss 2.30->1.97)，监管密集期反是超跌情绪出清买点"),
        ("XF09_xq_spike_hold", "XF09a_xq_spike_cut", "雪球发帖>=1帖次日09:25斩(vs零帖暗牌)", "证伪(库覆盖偏倚)", "全五年仅15笔且雪球库系按1进2样本回溯爬取(IS仅T+2后4笔)，存在样本稀疏与覆盖偏倚，严禁入模"),
        ("XF10_guba_panic_spike", "XF10_guba_spike3x_0925", "股吧隔夜发帖暴增>=3倍基线(且>=5帖)09:25斩", "证伪", "IS与OOS四池全显著跑输(P165_ss 2.30->1.88)，散户恐慌放帖恰对应反弹拐点"),
        ("XF11_good_buyback_win_notice", "XF11_good_notice_boost", "近90日或持仓期回购/增持/中标利好抬高止盈+3%", "证伪/边际近零", "IS仅P000微升，P150/P140/P165几乎无改善且OOS小幅拖累"),
        ("XF12_ir_pit_hold", "XF12_ir_active_boost", "近30日或持仓期机构调研背书抬高止盈+3%", "证伪/边际微弱", "全五年仅12笔边际变化，改善幅度不足1bp，缺乏广泛统计效力"),
        ("XF13_t1_mkt_open_zt_ice", "XF13a_mkt_open_zt_lt5_0925", "T+k 09:25全场竞价涨停骤降至<5家无条件09:25逃命", "有效(入选V2.1)", "IS四池全赢(IS GM 1.61->1.81)，P165_ss 2.30->2.40(胜率87.5%)，捕捉二次流动性冰点防连续失血"),
        ("XF14_mkt_fb_open_neg", "XF14a_fb_open_neg_0925", "T+k 09:25首板竞价溢价<0%于09:25砍", "证伪", "IS四池全输(IS GM 1.61->1.48)，超跌反弹股本就在情绪极冷中启动，首板负溢价杀跌专洗反弹底"),
        ("XF15_csi300_panic_drop", "XF15a_csi_drop15_0925", "前日沪深300大跌>1.5%次日09:25砍", "证伪/样本稀疏", "P165/P150触发几乎为0且在P165_ss(2.27)与P150_IS均拖累，不如09:25全场涨停<5家敏锐"),
        ("XF16_mkt_dt_surge", "XF16b_mkt_ndt_lt10_boost", "前日全场跌停<10家(市场止血)抬高止盈+3%(vs>=30家砍仓)", "有效(入选V2.1)", "市场止血(n_dt<10)抬止盈在IS 4/4全赢且OOS 3/4赢(P165_ss 2.30->2.40)；反之n_dt>=30砍仓大亏(1.62)"),
        ("XF17_rebound_rate10_hot", "XF17b_hd_reb_zt_r10_hot", "近10日真高标断板次日反包率>=20%抬高止盈+3%", "温和有效(冗余)", "IS 4/4与OOS 3/4温和正贡献(P165_OOS 2.07->2.13)，但逻辑被前日跌停<10家与D0阳线覆盖"),
        ("XF18_mkt_zt_surge", "XF18a_mkt_zt_ge60_boost", "前日全场涨停>=60家抬高止盈+3%", "证伪(过窄)", "IS虽升但大幅拉低P165_ss(2.30->2.20,胜率68.8%)且OOS不稳定，触发过频(236笔)虚抬止盈"),
        ("XF19_plate_has_zt_mates", "XF19b_csrc_mates_ge2_boost", "D0/T+1所属行业或开盘啦题材有涨停先锋抬止盈+3%", "温和有效(被淘汰)", "行业涨停队友在IS/OOS均稳健(+3~8pp)，但合成进V2.1后拉长单仓持仓并挤占主战槽位，五合体净值反降11.6%"),
        ("XF20_promo_1to2_warm", "XF20a_promo1to2_ge20_boost", "一进二晋级率>=20%抬高止盈+3%(vs<13%砍)", "证伪", "IS微升但P165_ss(2.24)与OOS均未稳赢；晋级率<13%砍仓在四池全大亏(P000 1.57->1.08)"),
        ("XF21_d0_candle_clv", "XF21c_d0_strong_yang_boost", "D0收光头真阳(CLV>=0.70)抬高止盈+3%且免T+1尾盘弱斩", "有效(入选V2.1)", "IS 4/4全赢(IS GM 1.61->1.69)且P165_ss 2.30->2.36(OOS_d 2.07->2.20)；强真阳买盘延续不应被T+1小幅震荡洗出"),
        ("XF22_d0_real_to_death", "XF22b_d0_real_to_gt20_0925", "D0真实自由换手>20%(>45%仅3笔)T+1 09:25砍 vs <6%缩量抬止盈", "证伪", "超跌撬板>45%仅3笔(OOS_d跑输)，>20%亦无IS样本且OOS拖累(1.33->1.29)；<6%缩量OOS全输"),
        ("XF23_t1_open_gap_down", "XF23a_t1_gap_lt_neg20_0925", "T+1 09:25竞价低开<-2.0%直接09:25斩(同台PK 14:55跌1.5%斩)", "证伪(不如14:55斩)", "对比DecD_4d，T+1早盘<-2%斩在IS与OOS的P150/P140/P000全线跑输(P000 1.57->1.36)，早盘割在日内情绪最低点"),
        ("XF24_t1_open_strong_gap", "XF24a_t1_gap_ge20_release", "T+1 09:25竞价高开>=+2.0%放飞T+2不设低位限价盖子", "待观察(IS未触发)", "OOS全4池微幅跑赢(P165_ss 2.37)，但IS=0笔(仅P000改变微弱)，合体挤占主策略故不入核心版"),
        ("XF25_vol_shrink_stall", "XF25_vol_shrink_stall_eod", "T+1/T+2缩量滞涨(量比<0.7且涨幅<1%)14:55清仓", "证伪", "IS与OOS四池全输(P165_ss 2.30->2.23, P000 1.57->1.25)，缩量横盘后仍常在T+3脉冲反弹"),
        ("XF26_touch_ma5_ma10_resist", "XF26a_ma5_resist_tp", "止盈目标受上方下压MA5/MA10均线压制截断", "证伪", "MA5压制在IS与OOS四池惨败(P165_ss 2.10, P000 1.28)，MA10几乎无触发且小幅拖累"),
        ("XF27_1to2_tightness_after_zt", "XF27a_1to2_tight_judge", "D0/T+1涨停后用一进二紧密度>=37+非事件假题材+0拉萨裁判是否连板", "证伪(不适配超跌首板)", "烂板次日早盘直接走反不如继续格局，因超跌底部首板原本就放量分歧换手大，套用连板紧封门限会提前卖飞"),
    ]

    # Run XF30_V21
    xf30_sp = make_xf30_spec(5, 0.70, 10, 0.03, True)
    r30, ed30, hd30, _, _ = bt.run_spec(sub, cb, feats, xf30_sp)
    ref_rets, _, _, _, _ = bt.run_spec(sub, cb, feats, {"base_mode": "DecD_4d"})
    qm30 = bt.quick_metrics(sub, r30, ed30, hd30, ref_rets=ref_rets)

    # Compute exact hit count across holding window for each XF01..XF27
    def hit_count(ft_idx, fn_h):
        return int(sum(1 for i in range(len(sub)) if fn_h(feats[i])))

    table_rows = []
    for fid, raw_key, desc, verdict, mech in canon_map:
        rr = raw_df[raw_df["factor"] == raw_key].iloc[0].to_dict()
        # Extract trigger counts in P000 / P165
        table_rows.append({
            "factor_id": fid,
            "raw_variant": raw_key,
            "group": rr["group"],
            "rule_desc": desc,
            "changed_trades_vs_DecD4": int(rr["changed_vs_DecD4"]),
            "P165_ss_nav": rr["P165_ss"], "P165_ss_wr": rr["P165_wr"], "P165_ss_mdd": rr["P165_mdd"], "P165_ss_hold": rr["P165_h"],
            "P165_IS_deq": rr["P165_IS_d"], "P165_OOS_deq": rr["P165_OOS_d"],
            "P150_IS_deq": rr["P150_IS_d"], "P150_OOS_deq": rr["P150_OOS_d"],
            "P140_IS_deq": rr["P140_IS_d"], "P140_OOS_deq": rr["P140_OOS_d"],
            "P000_IS_deq": rr["P000_IS_d"], "P000_OOS_deq": rr["P000_OOS_d"], "P000_ALL_deq": rr["P000_ALL_d"],
            "verdict": verdict,
            "mechanism": mech,
        })

    # Add XF28, XF29, XF30
    for fid, raw_key, desc, verdict, mech in [
        ("XF28_DecD_4d_step", "XF28_DecD_4d", "上轮最佳:T+1放飞连板兼14:55跌1.5%斩+T+2起阶梯限价(X10->5%->2%)", "基准V2.0", "时间衰减止盈+尾盘去弱，未引入09:25全场冰点熔断与D0强真阳/跌停止血调控"),
        ("XF29_RD_t1_gap2_2d", "XF29a_RD_2d", "二号席RD推荐版:T+1低开<-2%于09:25斩+涨停骑乘+T+2收盘", "次优于V2.0/V2.1", "战胜现役X10主要靠涨停骑乘与缩至2日，但T+1低开<-2%于09:25割在情绪最低点且2日过早放弃T+3/T+4回弹"),
    ]:
        rr = raw_df[raw_df["factor"] == raw_key].iloc[0].to_dict()
        table_rows.append({
            "factor_id": fid, "raw_variant": raw_key, "group": "G5_Synth", "rule_desc": desc,
            "changed_trades_vs_DecD4": int(rr["changed_vs_DecD4"]),
            "P165_ss_nav": rr["P165_ss"], "P165_ss_wr": rr["P165_wr"], "P165_ss_mdd": rr["P165_mdd"], "P165_ss_hold": rr["P165_h"],
            "P165_IS_deq": rr["P165_IS_d"], "P165_OOS_deq": rr["P165_OOS_d"],
            "P150_IS_deq": rr["P150_IS_d"], "P150_OOS_deq": rr["P150_OOS_d"],
            "P140_IS_deq": rr["P140_IS_d"], "P140_OOS_deq": rr["P140_OOS_d"],
            "P000_IS_deq": rr["P000_IS_d"], "P000_OOS_deq": rr["P000_OOS_d"], "P000_ALL_deq": rr["P000_ALL_d"],
            "verdict": verdict, "mechanism": mech,
        })

    table_rows.append({
        "factor_id": "XF30_V21_Dynamic_Factor_Step", "raw_variant": "XF30_C4_13_21_16", "group": "G5_Synth",
        "rule_desc": "终极V2.1:DecD_4d + XF13(09:25涨停<5砍)+XF21(D0强阳CLV>=0.70免T1且+3%)+XF16b(昨跌停<10家+3%)",
        "changed_trades_vs_DecD4": qm30["changed_all"],
        "P165_ss_nav": qm30["P165"]["ALL_ss_nav"], "P165_ss_wr": qm30["P165"]["ALL_ss_wr"],
        "P165_ss_mdd": qm30["P165"]["ALL_ss_mdd"], "P165_ss_hold": qm30["P165"]["ALL_ss_h"],
        "P165_IS_deq": qm30["P165"]["IS_deq_nav"], "P165_OOS_deq": qm30["P165"]["OOS_deq_nav"],
        "P150_IS_deq": qm30["P150"]["IS_deq_nav"], "P150_OOS_deq": qm30["P150"]["OOS_deq_nav"],
        "P140_IS_deq": qm30["P140"]["IS_deq_nav"], "P140_OOS_deq": qm30["P140"]["OOS_deq_nav"],
        "P000_IS_deq": qm30["P000"]["IS_deq_nav"], "P000_OOS_deq": qm30["P000"]["OOS_deq_nav"], "P000_ALL_deq": qm30["P000"]["ALL_deq_nav"],
        "verdict": "终极冠军V2.1",
        "mechanism": "多池IS 4/4全赢且OOS P165/P150/P140同步提升；09:25涨停<5防二次股灾失血，强真阳与市场止血后放宽止盈抓大肉，五合体5Y/3Y全赢",
    })

    t_df = pd.DataFrame(table_rows)
    assert len(t_df) == 30, f"Expected 30 rows, got {len(t_df)}"
    t_df.to_csv(f"{F3_DIR}/factor_30_marginal_table.csv", index=False, encoding="utf-8-sig")
    print(f"[1/3] Saved factor_30_marginal_table.csv ({len(t_df)} rows)")

    # 2. 81-point +/-20% Plateau around XF30_V21
    p_rows = []
    for zt_th in [4, 5, 6]:
        for clv_th in [0.60, 0.70, 0.80]:
            for ndt_th in [8, 10, 12]:
                for boost in [0.02, 0.03, 0.04]:
                    sp = make_xf30_spec(zt_th, clv_th, ndt_th, boost, True)
                    r, ed, hd, _, _ = bt.run_spec(sub, cb, feats, sp)
                    qm = bt.quick_metrics(sub, r, ed, hd)
                    p_rows.append({
                        "zt_th": zt_th, "clv_th": clv_th, "ndt_th": ndt_th, "boost": boost,
                        "P165_ss": qm["P165"]["ALL_ss_nav"],
                        "P165_IS_d": qm["P165"]["IS_deq_nav"], "P165_OOS_d": qm["P165"]["OOS_deq_nav"],
                        "P150_IS_d": qm["P150"]["IS_deq_nav"], "P150_OOS_d": qm["P150"]["OOS_deq_nav"],
                        "P140_IS_d": qm["P140"]["IS_deq_nav"], "P140_OOS_d": qm["P140"]["OOS_deq_nav"],
                        "P000_IS_d": qm["P000"]["IS_deq_nav"], "P000_ALL_d": qm["P000"]["ALL_deq_nav"],
                    })
    p_df = pd.DataFrame(p_rows)
    p_df.to_csv(f"{F3_DIR}/plateau_v21_81.csv", index=False, encoding="utf-8-sig")
    beat_x10 = ((p_df["P165_ss"] > 1.9411) & (p_df["P150_OOS_d"] > 0.9559) & (p_df["P000_ALL_d"] > 0.6677)).mean() * 100.0
    beat_decd = ((p_df["P165_ss"] > 2.3036) & (p_df["P150_OOS_d"] > 1.3273) & (p_df["P140_IS_d"] > 1.3404)).mean() * 100.0
    print(f"[2/3] 81-point plateau: P165_ss min/med/max = {p_df['P165_ss'].min():.4f}/{p_df['P165_ss'].median():.4f}/{p_df['P165_ss'].max():.4f} | beat X10={beat_x10:.1f}% | beat DecD4={beat_decd:.1f}%")

    # 3. Full End-to-End < 2025-01-01 Physical Truncation Invariance Test
    print("[3/3] Running full end-to-end < 2025-01-01 physical truncation invariance test...")
    import run_exit_scan as base_mod
    df_raw = pd.read_parquet(f"{SIM}/backtests_astock2/p5_full_pry_universe/full_pry_master_enriched.parquet")
    df_tr = df_raw[df_raw["dt_str"] < "2025-01-01"].copy().reset_index(drop=True)
    cb_tr = {}
    for c6, d_o in cb.items():
        dts = d_o["dts"]
        cut_len = 0
        for dt_s in dts:
            if dt_s < "2025-01-01":
                cut_len += 1
            else:
                break
        if cut_len == 0:
            continue
        cb_tr[c6] = {
            k: ({dt_s: i for i, dt_s in enumerate(dts[:cut_len])} if k == "date_to_pos" else (v[:cut_len] if isinstance(v, (np.ndarray, list)) else v))
            for k, v in d_o.items()
        }
    sub_tr = base_mod.build_base_candidates(df_tr, cb_tr)
    # Truncate ALL ctx dictionaries strictly < 2025-01-01
    ctx_tr = {
        "lhb_map": {k: v for k, v in ctx["lhb_map"].items() if k[0] < "2025-01-01"},
        "stock_notices": {c: [x for x in lst if x[0] < "2025-01-01 00:00:00"] for c, lst in ctx["stock_notices"].items()},
        "ex_reg": {ex: [x for x in lst if x[0] < "2025-01-01"] for ex, lst in ctx["ex_reg"].items()},
        "xq_map": {c: arr[arr < "2025-01-01 00:00:00"] for c, arr in ctx["xq_map"].items()},
        "gb_map": {c: arr[arr < "2025-01-01 00:00:00"] for c, arr in ctx["gb_map"].items()},
        "ir_map": {c: arr[arr < "2025-01-01 00:00:00"] for c, arr in ctx["ir_map"].items()},
        "kpl_ds": {k: v for k, v in ctx["kpl_ds"].items() if k[0] < "2025-01-01"},
        "kpl_dp": {k: v for k, v in ctx["kpl_dp"].items() if k[0] < "2025-01-01"},
        "kpl_hist": {c: [x for x in lst if x[0] < "2025-01-01"] for c, lst in ctx["kpl_hist"].items()},
        "tape_map": {k: v for k, v in ctx["tape_map"].items() if k[0] < "2025-01-01"},
        "env_map": {k: v for k, v in ctx["env_map"].items() if k < "2025-01-01"},
        "rt_map": {k: v for k, v in ctx["rt_map"].items() if k < "2025-01-01"},
        "hd_rate_map": {k: v for k, v in ctx["hd_rate_map"].items() if k < "2025-01-01"},
        "csrc_zt_map": {k: v for k, v in ctx["csrc_zt_map"].items() if k < "2025-01-01"},
        "csrc_ind_map": ctx["csrc_ind_map"],
    }
    feats_tr = fs.compute_all_holding_factors(sub_tr, cb_tr, ctx_tr)
    r_tr, ed_tr, _, _, _ = bt.run_spec(sub_tr, cb_tr, feats_tr, xf30_sp)

    full_df = pd.DataFrame({"buy_date": sub["buy_date"], "code": sub["code"], "net_ret": r30, "exit_date": ed30})
    full_pre = full_df[full_df["exit_date"] < "2025-01-01"].copy()
    tr_df = pd.DataFrame({"buy_date": sub_tr["buy_date"], "code": sub_tr["code"], "net_ret_tr": r_tr, "exit_date_tr": ed_tr})
    tr_pre = tr_df[(tr_df["exit_date_tr"] != "") & (tr_df["exit_date_tr"] < "2025-01-01")].copy()
    m_tr = full_pre.merge(tr_pre, on=["buy_date", "code"], how="outer")
    max_diff = float((m_tr["net_ret"] - m_tr["net_ret_tr"]).abs().max())
    assert len(m_tr) == len(full_pre) and max_diff == 0.0, f"Truncation mismatch! {max_diff}"
    print(f"  [PASS] Truncation (<2025-01-01): {len(m_tr)} trades matched, max_abs_diff = {max_diff:.1f}")
    print(f"Done part1 in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
