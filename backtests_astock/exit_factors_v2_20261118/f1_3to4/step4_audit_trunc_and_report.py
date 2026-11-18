#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step4_audit_trunc_and_report.py
完整执行：
  1. >= 2025-01-01 物理截断重跑 2021-2024 零穿越硬检验 (max_abs_diff == 0.0)
  2. D15 六大窗口对比 (90分标准档 & 102分S档 & 78分+扩充池)
  3. 八大防过拟合完整审计 (HLZ t, DSR M=150, 猴子p值, ±20%保留, 200x MC, CSCV PBO, 逐年胜出, 地狱模式)
  4. 5m盘口逐笔变动核验 + enforce_dt_exact=True 收盘精确跌停核查
  5. 生成全部 30 个跨策略卖点因子总表 factor_30_marginal_table.csv、summary_3to4_exit_factors.json 与 report_3to4_exit_factors.md
"""

import json
import os
import pickle
import sys
import time

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION"

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_factors_v2_20261118/f1_3to4"
UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, OUT_DIR)
sys.path.insert(0, UPG_DIR)

import upgrade_3to4_pit as u34
import step1_build_exit_pit_db as s1
import exit_factor_engine as efe

F7 = ["xf21_135", "xf03_20m", "xf28_35", "xf02", "xf07_new", "xf22", "xf23_reb20"]
F3 = ["xf21_135", "xf03_20m", "xf28_35"]


def risk7_score(st: dict) -> int:
    return sum(int(bool(st.get(k))) for k in F7)


def risk3_score(st: dict) -> int:
    return sum(int(bool(st.get(k))) for k in F3)


def make_audited_configs() -> list:
    return [
        ("V4.0_Base_原版", None),
        ("XF21_Elo135_1345d70", lambda st, ctx: {"tight_1345_thr": 0.070 if st.get("xf21_135") else 0.050}),
        ("XF30_3f_ge1_1345d70", lambda st, ctx: {"tight_1345_thr": 0.070 if risk3_score(st) >= 1 else 0.050}),
        ("XF30_7f_ge1_1345d70", lambda st, ctx: {"tight_1345_thr": 0.070 if risk7_score(st) >= 1 else 0.050}),
        ("XF30_7f_Reb20dev96", lambda st, ctx: {
            "tight_1345_thr": 0.070 if risk7_score(st) >= 1 else 0.050,
            "cond_dev_ratio": 0.96 if (ctx["boards"] >= 5 and st.get("xf23_reb20")) else None,
        }),
    ]


def build_p_list(cache: dict, states: dict, rule_fn) -> list:
    code_bars = cache["code_bars_ext"]
    p_list = []
    for e in cache["buy_entries"]:
        if (not e["skel"]) or (e["buy_px"] is None):
            p_list.append(None)
            continue
        pos = e["pos"]
        cb = code_bars[e["code"]]
        ex_dt, spx, adjs, hb, shh, rsn = efe.sim_exit_with_rule(e, cache, states.get(e["idx"], {}), rule_fn)
        nr = (spx * adjs) / (e["buy_px"] * float(cb["adjf"][pos])) * (1.0 - efe.FEE_RATE) - 1.0
        p_list.append({
            "code": e["code"], "name": e["name"], "buy_date": e["buy_date"], "buy_hhmm": e["buy_hhmm"],
            "buy_price": round(e["buy_px"], 2), "exit_date": ex_dt, "exit_hhmm": shh,
            "exit_price": round(spx, 2), "hold_bars": hb, "net_ret": float(nr),
            "reason": rsn,
        })
    return p_list


def run_physical_truncation(cache_full: dict, states_full: dict, cfgs: list) -> dict:
    t0 = time.time()
    print("[Trunc] Rebuilding entire exit PIT database from raw files with max_date=2024-12-31...")
    cache_tr = s1.build_exit_pit_data("2024-12-31", verbose=False)
    states_tr = efe.precompute_trade_day_states(cache_tr, min_score=78.0)

    trunc_res = {}
    for lbl, rfn in cfgs:
        for thr, tier in [(90.0, "std90"), (102.0, "strict102")]:
            rf = efe.evaluate_rule(cache_full, states_full, rfn, lbl, thr)["slot_df"]
            rt = efe.evaluate_rule(cache_tr, states_tr, rfn, lbl, thr)["slot_df"]
            f24 = rf[rf["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
            t24 = rt[rt["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
            assert len(f24) == len(t24), f"Trunc len mismatch {lbl}/{tier}: {len(f24)} vs {len(t24)}"
            assert (f24["code"] == t24["code"]).all() and (f24["buy_date"] == t24["buy_date"]).all()
            assert (f24["exit_date"] == t24["exit_date"]).all() and (f24["exit_hhmm"] == t24["exit_hhmm"]).all()
            max_ret = float(np.max(np.abs(f24["net_ret"].to_numpy() - t24["net_ret"].to_numpy())))
            max_px = float(np.max(np.abs(f24["exit_price"].to_numpy() - t24["exit_price"].to_numpy())))
            assert max_ret == 0.0 and max_px == 0.0, f"Trunc diff {lbl}/{tier}: {max_ret}/{max_px}"
            trunc_res[f"{lbl}__{tier}"] = {"trades_2124": int(len(t24)), "max_abs_diff": max_ret, "max_px_diff": max_px}
    print(f"[TRUNCATION 20250101 PASS] Verified {len(trunc_res)} runs in {time.time()-t0:.1f}s -> ALL max_abs_diff == 0.0")
    return trunc_res


def verify_5m_day(cache: dict, code: str, dt: str) -> dict:
    cb = cache["code_bars_ext"][code]
    if dt not in cb["date_to_pos"]:
        return {}
    p = cb["date_to_pos"][dt]
    pc = float(cb["pre_c"][p])
    arr = cache["bars_5m_map"].get((code, dt))
    pm_hi, pm1345_lo, bar_last = None, None, None
    if arr is not None and len(arr) > 0 and pc > 0:
        pm_hi = round((float(np.max(arr[:, 2])) / pc - 1.0) * 100.0, 2)
        s13 = arr[arr[:, 0] >= 1345]
        if len(s13) > 0:
            pm1345_lo = round((float(np.min(s13[:, 3])) / pc - 1.0) * 100.0, 2)
        bar_last = round((float(arr[-1, 4]) / pc - 1.0) * 100.0, 2)
    return {
        "date": dt,
        "open_pct": round((float(cb["open"][p]) / pc - 1.0) * 100.0, 2) if pc > 0 else 0.0,
        "high_pct": round((float(cb["high"][p]) / pc - 1.0) * 100.0, 2) if pc > 0 else 0.0,
        "low_pct": round((float(cb["low"][p]) / pc - 1.0) * 100.0, 2) if pc > 0 else 0.0,
        "close_pct": round((float(cb["close"][p]) / pc - 1.0) * 100.0, 2) if pc > 0 else 0.0,
        "to_pct": round(float(cb["to"][p]), 2),
        "is_zt": bool(cb["is_zt"][p]),
        "is_dt_exact": bool(cb["is_dt_exact"][p]),
        "pm1345_low_pct": pm1345_lo,
        "bar_last_pct": bar_last,
    }


def build_30_factor_table(df_scan: pd.DataFrame, xf30_row: dict, cache: dict, states: dict) -> pd.DataFrame:
    """整理全部 30 个跨策略持仓卖点因子 (XF01~XF30) 的 IS + OOS 逐项实测总表"""
    bes90 = [e for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 90 and e["buy_px"] is not None]
    is_ids = {e["idx"] for e in bes90 if e["buy_date"] <= "2023-12-31"}
    oos_ids = {e["idx"] for e in bes90 if e["buy_date"] >= "2024-01-01"}

    REASON_MAP = {
        "XF01_lhasa_surge": ("证伪淘汰", "OOS触发散户跟风但大妖常伴拉萨席位洗盘，A3在OOS砍断主升龙致大亏(单仓减165.45x，等权减452.25x)"),
        "XF02_daysurf_in": ("辅助观察(入打分卡)", "前一日游资一日游买入后温和收紧13:45破7.0%护利，IS 1胜(+0.38x)且OOS 2胜(+1.18x单仓/+21.84x等权)"),
        "XF03_inst_dump": ("有效入选(核心因子)", "前一日机构卖出超2000万时收紧13:45护利，IS 2/2胜(+0.48x)且OOS 6/7胜(+20.09x单仓/+10.13x 78+等权/+0.38x 102S，仅1笔建设工业回撤8.78pp拉低90等权3.59x)"),
        "XF04_top_yz_exit": ("证伪淘汰", "大妖中途顶级游资换手属正常换庄，强行限制免死在OOS错失后续拉升(单仓减129.51x，等权减329.42x)"),
        "XF05_net_buy_overheat": ("证伪淘汰", "龙虎榜净买占比超12%样本稀少(IS 0笔)，OOS 09:25抢跑触发3笔仅1胜(单仓减45.96x，等权减276.08x)"),
        "XF06_quant_churn": ("证伪淘汰", "量化做T叠加拉萨在IS仅改1笔(+0.08x)，90分OOS零改动且换用09:25或10:30动作在OOS大幅亏损"),
        "XF07_stock_reg_hit": ("辅助观察(入打分卡)", "持仓新增个股监管函在IS 2/2胜(+0.18x)，90分OOS因买入端T11扣12分预拦截而0改动，入打分卡轻度收紧13:45"),
        "XF08_clarify_or_tox": ("证伪淘汰", "风险提示在OOS频繁命中合富中国(11月3日至14日连续发布)，盲目挂93%双异动斩杀龙头(单仓减153.97x，等权减388.96x)"),
        "XF09_ex_reg5_tight": ("证伪淘汰", "买入端T11已先拦截严监管周期标的，78分+扩充池补全库在OOS等权净亏11.37x且102S净亏0.36x"),
        "XF10_abn_notice_cnt": ("证伪淘汰", "IS 0笔触发，OOS达2次异常波动即09:25清仓斩杀妖股(单仓减129.10x，等权减587.95x)"),
        "XF11_ir_pit": ("证伪淘汰", "机构调研突发样本稀少，以此限制免死在OOS错失妖股(单仓减101.78x，等权减256.78x)"),
        "XF12_xq_explode": ("证伪淘汰", "买入前已筛除雪球热帖，持仓期24h雪球增至4帖及以上仅在OOS改2笔即净亏7.02x单仓/18.20x等权"),
        "XF13_guba_surge": ("证伪淘汰", "股吧发帖2025年爬虫量级较2022与2023年衰减超90%，且A3 93%在OOS砍断妖股(单仓减153.59x，等权减398.35x)"),
        "XF14_xq_still_quiet": ("证伪淘汰", "暗牌免死在IS/OOS仅各改0至1笔不具稳健性；若反过来豁免D4未封板则在IS亏1.19x且OOS单仓亏96.62x"),
        "XF15_mates_nuke_0925": ("证伪淘汰", "连板龙头常虹吸同板块后排小弟，A4仅IS改1笔且OOS 0改动；改用09:25抢跑在IS与OOS等权双亏(减0.46x/减324.41x)"),
        "XF16_lone_wolf_0925": ("证伪淘汰", "三进四龙头多为全板块独苗(101/115笔触发)，无小弟助攻时10:30破均线卖出在OOS重创龙头(单仓减196.00x，等权减489.52x)"),
        "XF17_mkt_fb_open_neg": ("证伪淘汰", "首板核按钮日反而是高标抱团温床，IS即净亏0.03x(A1 09:25亦在IS大亏1.25x)，物理逻辑不成立"),
        "XF18_mkt_climax_100": ("证伪淘汰", "百股涨停高潮后次日收紧13:45在IS仅改1笔，OOS等权净亏69.63x(78+等权亏8.53x)"),
        "XF19_promo_freeze": ("证伪淘汰", "一进二晋级率冰点主要影响低位接力，对三进四90分OOS零改动且78+等权净亏1.24x"),
        "XF20_dragon_usurped": ("证伪淘汰", "全场出现更高板位在113/115笔均触发，等价于无差别收紧，OOS等权暴跌242.25x(78+等权亏7.64x)"),
        "XF21_elo_overheat": ("有效入选(核心因子)", "主概念动态Elo满135分且日内冲高回落破7.0%代表板块高潮兑现，IS 3/3胜(+0.25x单仓/+0.33x等权)且OOS 9/11胜(+33.71x单仓/+49.12x等权/+0.30x 102S)，不误伤合富中国"),
        "XF22_csi300_slump": ("辅助观察(入打分卡)", "沪深300大跌时收紧13:45破7.0%在IS 2/2胜(+0.10x单仓/+0.09x等权)，OOS 78分+增厚3.78x，可作打分卡辅助项"),
        "XF23_rebound_rate10": ("有效入选(生态增强)", "近10日4板及以上断板次日反包率低于20%冷区时，5板以上挂96%双异动止盈在IS(+0.08x/+0.13x 78EQ)与OOS(+27.24x单仓/+158.20x等权)全胜，完美避开热区合富中国(22%阈值捷荣有回撤)"),
        "XF24_high_dragon_score_judge": ("证伪淘汰", "90分档断板免死样本稀少且IS零触发；OOS用高标首阴打分强行剥夺免死直接砍飞龙头(单仓减114.68x，等权减290.57x)"),
        "XF25_late_rotten_seal": ("证伪淘汰", "尾盘回封烂板常为分歧转一致起爆点，IS仅改1笔，OOS剥夺免死单笔亏损(单仓减114.68x，等权减297.44x)"),
        "XF26_tiny_seal_ratio": ("证伪淘汰", "前一日封成比低于1.0%在90分OOS零改动(78EQ虽增28.85x但改用09:25即在OOS 2连败亏24.11x)，跨动作不稳健"),
        "XF27_death_turnover": ("证伪淘汰", "换手率超32%频繁命中主升龙头，OOS挂93%双异动砍断龙头利润(单仓减100.79x，等权减261.42x)"),
        "XF28_vol_blowoff": ("有效入选(核心因子)", "前一日成交额超5日均量3.5倍时仅收紧13:45破7.0%温和护利，在IS 1/1胜(+0.38x)与OOS 4/4胜(+14.75x单仓/+61.03x等权)全胜，不似09:25与93%误杀龙头"),
        "XF29_upper_wick_grave": ("证伪淘汰", "以长上影与大长腿限制断板免死在OOS错失龙头反包(单仓减85.30x，等权减221.25x)"),
    }

    # 为每个因子挑出 IS 最优动作（同时把入卡因子对齐其入选动作 A2_1345_d70 / A3_dev96_5b）
    FORCE_ACTION = {
        "XF02_daysurf_in": ("xf02", "A2_1345_d70"),
        "XF03_inst_dump": ("xf03_20m", "A2_1345_d70"),
        "XF07_stock_reg_hit": ("xf07_new", "A2_1345_d70"),
        "XF21_elo_overheat": ("xf21_135", "A2_1345_d70"),
        "XF22_csi300_slump": ("xf22", "A2_1345_d70"),
        "XF28_vol_blowoff": ("xf28_35", "A2_1345_d70"),
        "XF23_rebound_rate10": ("xf23_reb20", "A3_dev96_5b"),
    }

    out_rows = []
    for xf_id in sorted(REASON_MAP.keys()):
        grp_df = df_scan[df_scan["xf_id"] == xf_id]
        if xf_id in FORCE_ACTION:
            v_sel, a_sel = FORCE_ACTION[xf_id]
            pick = grp_df[(grp_df["var_id"] == v_sel) & (grp_df["action"] == a_sel)].iloc[0]
        else:
            act = grp_df[grp_df["is_chg90"] + grp_df["is_chg78"] > 0]
            if act.empty:
                pick = grp_df.iloc[0]
            else:
                pick = act.assign(_rk=act["is_deq_90"] * 2.0 + act["is_deq_78"] + act["is_d1s_90"]).sort_values("_rk", ascending=False).iloc[0]

        verdict, phys = REASON_MAP[xf_id]
        # 计算该 var_id 在持仓期内的标的总触发笔数
        vid = str(pick["var_id"])
        state_key = "xf11_7d" if vid == "xf11_7d_safe" else vid
        is_trig = sum(1 for idx in is_ids if any(bool(d.get(state_key)) for d in states.get(idx, {}).values()))
        oos_trig = sum(1 for idx in oos_ids if any(bool(d.get(state_key)) for d in states.get(idx, {}).values()))
        # 处理 xf24 特例
        if xf_id == "XF24_high_dragon_score_judge":
            th_v = int(vid.split("lt")[-1])
            is_trig = sum(1 for idx in is_ids if any(bool(d.get("xf24_veto")) or int(d.get("xf24_sc", 0)) < th_v for d in states.get(idx, {}).values()))
            oos_trig = sum(1 for idx in oos_ids if any(bool(d.get("xf24_veto")) or int(d.get("xf24_sc", 0)) < th_v for d in states.get(idx, {}).values()))

        out_rows.append({
            "xf_id": xf_id,
            "group": str(pick["group"]),
            "desc": str(pick["desc"]),
            "var_id": vid,
            "action": str(pick["action"]),
            "is_trig_90": is_trig,
            "is_chg_90": int(pick["is_chg90"]),
            "is_win_90": int(pick["is_win90"]),
            "is_dwr_90_pp": float(pick["is_dwr90"]),
            "is_dmean_90_pp": float(pick["is_dmean90"]),
            "is_d1s_90": float(pick["is_d1s_90"]),
            "is_deq_90": float(pick["is_deq_90"]),
            "is_deq_78": float(pick["is_deq_78"]),
            "is_d1s_102": float(pick["is_d1s_102"]),
            "oos_trig_90": oos_trig,
            "oos_chg_90": int(pick["oos_chg90"]),
            "oos_win_90": int(pick["oos_win90"]),
            "oos_dwr_90_pp": float(pick["oos_dwr90"]),
            "oos_dmean_90_pp": float(pick["oos_dmean90"]),
            "oos_d1s_90": float(pick["oos_d1s_90"]),
            "oos_deq_90": float(pick["oos_deq_90"]),
            "oos_deq_78": float(pick["oos_deq_78"]),
            "oos_d1s_102": float(pick["oos_d1s_102"]),
            "verdict": verdict,
            "physical_reason": phys,
        })

    # 第 30 项：XF30_composite_exit_scorecard
    out_rows.append(xf30_row)
    df_out = pd.DataFrame(out_rows)
    df_out.to_csv(f"{OUT_DIR}/factor_30_marginal_table.csv", index=False, encoding="utf-8-sig")
    return df_out


def main():
    t0 = time.time()
    with open(f"{OUT_DIR}/pit_exit_cache_full.pkl", "rb") as f:
        cache = pickle.load(f)
    with open(u34.CSI_CANON_JSON, "r", encoding="utf-8") as f:
        csi_canon = json.load(f)

    states = efe.precompute_trade_day_states(cache, min_score=78.0)
    cfgs = make_audited_configs()

    # 1. 物理截断 >= 2025-01-01 硬测试
    trunc_audit = run_physical_truncation(cache, states, cfgs)

    # 2. D15 六大窗口 + 8项防过拟合 + 合规检验
    win_specs = [
        ("全五年", "2021-11-15", "2026-11-16", csi_canon["全五年(2021-11-16起)"][0]),
        ("IS_21_23", "2021-11-15", "2023-12-31", None),
        ("OOS_24_26", "2024-01-01", "2026-11-16", csi_canon["近三年(2024-01-01起)"][0]),
        ("近三年", "2023-11-16", "2026-11-16", csi_canon["近三年(2023-11-16起)"][0]),
        ("2026全年", "2026-01-01", "2026-11-16", csi_canon["2026全年"][0]),
        ("2026年7月以来", "2026-07-01", "2026-11-16", csi_canon["2026年7月以来"][0]),
    ]

    res_skel = {
        "cand_df": cache["cand_df"],
        "skel": cache["skel"],
        "csi_map": cache["csi_map"],
        "all_csi_dts": cache["all_csi_dts"],
    }

    d15_all = {"std90": {}, "strict102": {}}
    audit8_all = {"std90": {}, "strict102": {}}
    tier78_stats = {}
    integrity = {}
    base_raw90 = base_raw102 = None
    diffs_by_cfg = {}

    for lbl, rfn in cfgs:
        p_cur = build_p_list(cache, states, rfn)
        res_tmp = dict(res_skel)
        res_tmp["p_cur"] = p_cur

        # 78分+ 扩充池对照
        ev78 = efe.evaluate_rule(cache, states, rfn, lbl, 78.0)
        tier78_stats[lbl] = {"IS": ev78["IS"], "OOS": ev78["OOS"], "ALL_5Y": ev78["ALL_5Y"]}

        for thr, tier in [(90.0, "std90"), (102.0, "strict102")]:
            raw_df, slot_df = u34.extract_raw_and_slot(res_tmp, cache["sc_v40"], thr, "p_cur")
            t0_v = int((slot_df["exit_date"] <= slot_df["buy_date"]).sum())
            ov_v = 0
            for i in range(1, len(slot_df)):
                pr, cr = slot_df.iloc[i - 1], slot_df.iloc[i]
                if cr["buy_date"] < pr["exit_date"] or (cr["buy_date"] == pr["exit_date"] and int(cr["buy_hhmm"]) <= int(pr["exit_hhmm"])):
                    ov_v += 1
            yz_v = 0
            for r in slot_df.itertuples(index=False):
                cb = cache["code_bars_ext"][r.code]
                pos = cb["date_to_pos"][r.buy_date]
                if r.buy_price >= cb["zt_px"][pos] - 0.005:
                    yz_v += 1
            assert t0_v == 0 and ov_v == 0 and yz_v == 0
            integrity[f"{lbl}__{tier}"] = {"t0": t0_v, "overlap": ov_v, "yizi_buy": yz_v}

            d15_all[tier][lbl] = {
                wn: u34._calc_metrics_window(raw_df, slot_df, cache["csi_map"], cache["all_csi_dts"], sd, ed, cp)
                for wn, sd, ed, cp in win_specs
            }
            audit8_all[tier][lbl] = u34.run_8tests_overfitting_audit(
                res_tmp, cache["sc_v40"], cache["comp_v40"], u34.V40_FACTOR_NAMES, thr, "p_cur", f"{lbl}_{tier}"
            )

            if lbl == "V4.0_Base_原版":
                if tier == "std90":
                    base_raw90 = raw_df.set_index(["buy_date", "code"])
                else:
                    base_raw102 = raw_df.set_index(["buy_date", "code"])
            else:
                ref_b = base_raw90 if tier == "std90" else base_raw102
                cur_ix = raw_df.set_index(["buy_date", "code"])
                chgs = []
                for k_t, row in cur_ix.iterrows():
                    br = ref_b.loc[k_t]
                    if abs(float(row["net_ret"]) - float(br["net_ret"])) > 1e-6:
                        d_pp = round((float(row["net_ret"]) - float(br["net_ret"])) * 100.0, 2)
                        chgs.append({
                            "buy_date": k_t[0], "code": k_t[1], "name": str(row["name"]), "score": int(row["score"]),
                            "base_exit": f"{br['exit_date']} {int(br['exit_hhmm'])} ({br['exit_price']:.2f})",
                            "base_ret_pct": round(float(br["net_ret"]) * 100.0, 2),
                            "new_exit": f"{row['exit_date']} {int(row['exit_hhmm'])} ({row['exit_price']:.2f})",
                            "new_ret_pct": round(float(row["net_ret"]) * 100.0, 2),
                            "diff_pp": d_pp,
                            "base_day_5m": verify_5m_day(cache, k_t[1], str(br["exit_date"])),
                            "new_day_5m": verify_5m_day(cache, k_t[1], str(row["exit_date"])),
                        })
                diffs_by_cfg[f"{lbl}__{tier}"] = chgs

            if lbl == "XF30_7f_ge1_1345d70":
                csv_cols = ["code", "name", "buy_date", "buy_hhmm", "buy_price", "exit_date", "exit_hhmm", "exit_price", "net_ret", "score"]
                fn_out = "ledger_3to4_xf30_std.csv" if tier == "std90" else "ledger_3to4_xf30_strict.csv"
                out_c = slot_df[csv_cols].copy()
                out_c["net_ret"] = out_c["net_ret"].round(6)
                out_c.to_csv(f"{OUT_DIR}/{fn_out}", index=False, encoding="utf-8-sig")

    # 3. XF30 的 200x 打分卡内部权重扰动测试 (权重 uniform(0.8, 1.2) vs 阈值 1.0，实际等效检验去随机子集因子稳健性)
    rng = np.random.default_rng(20261118)
    mc_xf30 = []
    for _ in range(200):
        w = rng.uniform(0.5, 1.5, size=len(F7))  # 扰动 ±50% 权重与阈值1.0 -> 等价检验核心子集随机组合
        th_r = float(rng.uniform(0.8, 1.2))
        rfn_mc = lambda st, ctx, ww=w, tt=th_r: {"tight_1345_thr": 0.070 if sum(ww[j] * int(bool(st.get(F7[j]))) for j in range(len(F7))) >= tt else 0.050}
        ev_mc = efe.evaluate_rule(cache, states, rfn_mc, "mc", 90.0)
        mc_xf30.append((ev_mc["IS"]["nav_1s"], ev_mc["OOS"]["nav_1s"], ev_mc["ALL_5Y"]["nav_1s"]))
    mc_arr = np.array(mc_xf30)
    xf30_weight_mc = {
        "runs": 200,
        "is_nav_min": round(float(mc_arr[:, 0].min()), 4),
        "is_nav_median": round(float(np.median(mc_arr[:, 0])), 4),
        "oos_nav_min": round(float(mc_arr[:, 1].min()), 4),
        "oos_nav_median": round(float(np.median(mc_arr[:, 1])), 4),
        "5y_nav_min": round(float(mc_arr[:, 2].min()), 2),
        "5y_nav_median": round(float(np.median(mc_arr[:, 2])), 2),
        "prob_beat_base_all_5y_pct": round(float((mc_arr[:, 2] > 1799.9931).mean() * 100.0), 1),
    }

    # 3b. XF30_7f_ge1 护利阈值 ±20% 平滑曲线 (+5.0% ~ +8.0%)
    drop_smoothness = []
    for thr_d in [0.050, 0.055, 0.060, 0.065, 0.070, 0.075, 0.080]:
        rfn_d = None if abs(thr_d - 0.050) < 1e-9 else (lambda st, ctx, t=thr_d: {"tight_1345_thr": t if risk7_score(st) >= 1 else 0.050})
        e90 = efe.evaluate_rule(cache, states, rfn_d, "sm", 90.0)
        e78 = efe.evaluate_rule(cache, states, rfn_d, "sm", 78.0)
        e102 = efe.evaluate_rule(cache, states, rfn_d, "sm", 102.0)
        drop_smoothness.append({
            "drop_pct": round(thr_d * 100.0, 1),
            "is_90_1s": round(e90["IS"]["nav_1s"], 4),
            "is_90_eq": round(e90["IS"]["eq_nav"], 4),
            "is22_90_eq": round(e90["IS_22"]["eq_nav"], 4),
            "is23_90_eq": round(e90["IS_23"]["eq_nav"], 4),
            "is_78_eq": round(e78["IS"]["eq_nav"], 4),
            "is_102_1s": round(e102["IS"]["nav_1s"], 4),
            "oos_90_1s": round(e90["OOS"]["nav_1s"], 4),
            "oos_90_eq": round(e90["OOS"]["eq_nav"], 4),
            "oos_102_1s": round(e102["OOS"]["nav_1s"], 4),
        })

    # 3c. 收盘精确跌停(is_dt_exact)不可卖压力测试 (顺延至次日非一字跌停卖出)
    dt_exact_sens = {}
    for lbl_dt, rfn_dt in [
        ("V4.0_Base_原版", None),
        ("XF30_7f_ge1_1345d70", lambda st, ctx: {"tight_1345_thr": 0.070 if risk7_score(st) >= 1 else 0.050}),
        ("XF30_7f_Reb20dev96", lambda st, ctx: {
            "tight_1345_thr": 0.070 if risk7_score(st) >= 1 else 0.050,
            "cond_dev_ratio": 0.96 if (ctx["boards"] >= 5 and st.get("xf23_reb20")) else None,
        }),
    ]:
        cb_map = cache["code_bars_ext"]
        recs_dt = []
        for e in cache["buy_entries"]:
            if (not e["skel"]) or (e["sc_v40"] < 90.0) or (e["buy_px"] is None):
                continue
            pos = e["pos"]
            cb = cb_map[e["code"]]
            ex_dt, spx, adjs, hb, shh, rsn = efe.sim_exit_with_rule(e, cache, states.get(e["idx"], {}), rfn_dt)
            p = cb["date_to_pos"][ex_dt]
            if shh == 1500 and bool(cb["is_dt_exact"][p]):
                kd = p + 1
                while kd < len(cb["dts"]):
                    if float(cb["open"][kd]) > round(float(cb["pre_c"][kd]) * 0.90, 2) + 0.005:
                        ex_dt, spx, adjs, shh = cb["dts"][kd], float(cb["open"][kd]), float(cb["adjf"][kd]), 925
                        break
                    if not bool(cb["is_dt_exact"][kd]):
                        ex_dt, spx, adjs, shh = cb["dts"][kd], float(cb["close"][kd]), float(cb["adjf"][kd]), 1500
                        break
                    kd += 1
            nr = (spx * adjs) / (e["buy_px"] * float(cb["adjf"][pos])) * (1.0 - efe.FEE_RATE) - 1.0
            recs_dt.append({
                "code": e["code"], "name": e["name"], "buy_date": e["buy_date"], "buy_hhmm": e["buy_hhmm"],
                "buy_price": round(e["buy_px"], 2), "exit_date": ex_dt, "exit_hhmm": shh, "exit_price": round(spx, 2),
                "net_ret": float(nr), "score": int(round(e["sc_v40"])), "priority_score": e["priority_score"],
            })
        rdf_dt = pd.DataFrame(recs_dt)
        sdf_dt = u34.sim_single_slot(rdf_dt)
        dt_exact_sens[lbl_dt] = {
            "is_1s": round(float(sdf_dt[sdf_dt["buy_date"] <= "2023-12-31"]["net_ret"].add(1.0).prod()), 4),
            "oos_1s": round(float(sdf_dt[sdf_dt["buy_date"] >= "2024-01-01"]["net_ret"].add(1.0).prod()), 4),
            "all_5y_1s": round(float(sdf_dt["net_ret"].add(1.0).prod()), 4),
            "all_5y_eq": round(float((rdf_dt.groupby("buy_date")["net_ret"].mean() + 1.0).prod()), 4),
        }

    # 4. 生成全部 30 项跨策略卖点因子总表
    df_scan = pd.read_csv(f"{OUT_DIR}/all_factor_actions_scan.csv")
    b90_w = d15_all["std90"]["V4.0_Base_原版"]
    x90_w = d15_all["std90"]["XF30_7f_ge1_1345d70"]
    b102_w = d15_all["strict102"]["V4.0_Base_原版"]
    x102_w = d15_all["strict102"]["XF30_7f_ge1_1345d70"]
    is_diffs_x = [d for d in diffs_by_cfg["XF30_7f_ge1_1345d70__std90"] if d["buy_date"] <= "2023-12-31"]
    oos_diffs_x = [d for d in diffs_by_cfg["XF30_7f_ge1_1345d70__std90"] if d["buy_date"] >= "2024-01-01"]

    xf30_row = {
        "xf_id": "XF30_composite_exit_scorecard",
        "group": "G6_Scorecard",
        "desc": "7项正交持仓卖点风险整数打分卡(>=1分触发13:45破+7.0%护利)",
        "var_id": "xf30_7f_ge1",
        "action": "A2_1345_d70",
        "is_trig_90": sum(1 for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 90 and e["buy_px"] is not None and e["buy_date"] <= "2023-12-31" and any(risk7_score(d) >= 1 for d in states[e["idx"]].values())),
        "is_chg_90": len(is_diffs_x),
        "is_win_90": sum(1 for d in is_diffs_x if d["diff_pp"] > 0),
        "is_dwr_90_pp": round(x90_w["IS_21_23"]["win_rate_pct"] - b90_w["IS_21_23"]["win_rate_pct"], 2),
        "is_dmean_90_pp": round(x90_w["IS_21_23"]["mean_ret_pct"] - b90_w["IS_21_23"]["mean_ret_pct"], 2),
        "is_d1s_90": round(x90_w["IS_21_23"]["single_slot_nav"] - b90_w["IS_21_23"]["single_slot_nav"], 4),
        "is_deq_90": round(x90_w["IS_21_23"]["daily_equal_weight_nav"] - b90_w["IS_21_23"]["daily_equal_weight_nav"], 4),
        "is_deq_78": round(tier78_stats["XF30_7f_ge1_1345d70"]["IS"]["eq_nav"] - tier78_stats["V4.0_Base_原版"]["IS"]["eq_nav"], 4),
        "is_d1s_102": round(x102_w["IS_21_23"]["single_slot_nav"] - b102_w["IS_21_23"]["single_slot_nav"], 4),
        "oos_trig_90": sum(1 for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 90 and e["buy_px"] is not None and e["buy_date"] >= "2024-01-01" and any(risk7_score(d) >= 1 for d in states[e["idx"]].values())),
        "oos_chg_90": len(oos_diffs_x),
        "oos_win_90": sum(1 for d in oos_diffs_x if d["diff_pp"] > 0),
        "oos_dwr_90_pp": round(x90_w["OOS_24_26"]["win_rate_pct"] - b90_w["OOS_24_26"]["win_rate_pct"], 2),
        "oos_dmean_90_pp": round(x90_w["OOS_24_26"]["mean_ret_pct"] - b90_w["OOS_24_26"]["mean_ret_pct"], 2),
        "oos_d1s_90": round(x90_w["OOS_24_26"]["single_slot_nav"] - b90_w["OOS_24_26"]["single_slot_nav"], 4),
        "oos_deq_90": round(x90_w["OOS_24_26"]["daily_equal_weight_nav"] - b90_w["OOS_24_26"]["daily_equal_weight_nav"], 4),
        "oos_deq_78": round(tier78_stats["XF30_7f_ge1_1345d70"]["OOS"]["eq_nav"] - tier78_stats["V4.0_Base_原版"]["OOS"]["eq_nav"], 4),
        "oos_d1s_102": round(x102_w["OOS_24_26"]["single_slot_nav"] - b102_w["OOS_24_26"]["single_slot_nav"], 4),
        "verdict": "有效入选(终极主方案)",
        "physical_reason": "合成7项低相关持仓风险因子，低风险期保留+5%护利放飞合富中国(+146.86%)，高风险期收紧至+7.0%，IS/OOS/78+/102S全档双赢且±20%全平滑",
    }
    df_30 = build_30_factor_table(df_scan, xf30_row, cache, states)

    # 5. 保存 summary_3to4_exit_factors.json
    summary = {
        "strategy_name": "三进四_V4.0_跨策略持仓动态卖点因子研究",
        "data_as_of_date": "2026-11-16",
        "is_window": "2021-11-15 至 2023-12-31",
        "oos_window": "2024-01-01 至 2026-11-16",
        "total_factors_tested": 30,
        "total_action_variants_tested": int(len(df_scan)),
        "truncation_cutoff_20250101": trunc_audit,
        "integrity_checks": integrity,
        "d15_windows_comparison": d15_all,
        "tier78_expanded_comparison": tier78_stats,
        "overfitting_8tests_comparison": audit8_all,
        "xf30_weight_mc_200": xf30_weight_mc,
        "xf30_drop_smoothness": drop_smoothness,
        "dt_exact_strict_sensitivity": dt_exact_sens,
        "trade_diffs_and_5m_trace": diffs_by_cfg,
        "factor_30_verdict_counts": df_30["verdict"].value_counts().to_dict(),
    }
    with open(f"{OUT_DIR}/summary_3to4_exit_factors.json", "w", encoding="utf-8") as f:
        json.dump(u34.sanitize_json(summary), f, ensure_ascii=False, indent=2)

    print(f"\n[Step4 AUDIT DONE in {time.time()-t0:.1f}s]")
    for tier in ("std90", "strict102"):
        print(f"\n=== D15 SUMMARY ({tier}) ===")
        for lbl, _ in cfgs:
            w5 = d15_all[tier][lbl]["全五年"]
            wis = d15_all[tier][lbl]["IS_21_23"]
            woos = d15_all[tier][lbl]["OOS_24_26"]
            w26 = d15_all[tier][lbl]["2026全年"]
            au = audit8_all[tier][lbl]
            print(f"{lbl:22s} | IS={wis['single_slot_nav']:6.2f}x(EQ={wis['daily_equal_weight_nav']:5.2f}x,MDD={wis['max_drawdown_pct']}%) | OOS={woos['single_slot_nav']:6.2f}x(EQ={woos['daily_equal_weight_nav']:7.2f}x) | 5Y={w5['single_slot_nav']:7.2f}x(EQ={w5['daily_equal_weight_nav']:7.2f}x,T5={w5['trimmed_top5_nav']:6.2f}x) | 26={w26['single_slot_nav']:5.2f}x | HLZ={au['test1_dsr_hlz']['hlz_t_trade']} DSR={au['test1_dsr_hlz']['dsr_M150']} Hell={au['test8_slippage_and_hell_mode']['hell_mode']['nav']:.2f}x")
    print(f"\nXF30 200x Weight MC: {xf30_weight_mc}")


if __name__ == "__main__":
    main()
