#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
exp4_pureblood_and_name_orthodoxy.py
================================================================================
一进二主引擎「第四把手术刀：业务血统正宗度 + 股票名字字面正宗度」5年盲测
严格零未来函数 (100% PIT):
- 2018-2021 预热与先验标定
- 2022-2026 样本外消融检验 (V14/V15 底座对比、血统正、名字正、融合版)
================================================================================
"""
import os
import sys
import re
import json
import time
import bisect
import sqlite3
import datetime
from collections import defaultdict, Counter

import numpy as np
import pandas as pd

from clean_wf_1to2_v14_ironclad_master import (
    load_full_prices,
    simulate_v14_single_trade,
    eval_v14_scheme_d15,
    NON_THEME,
    CSI300_ANNUAL, CSI300_5Y_CUM, FEE_RATE,
    SIM_DIR, OUT_DIR,
    KPL_MERGED_PATH, KPL_5Y_PATH, PIT_NOTICES_DB
)
from exp1_fake_theme_purifier import (
    EVENT_BASKET_PLATES,
    BROAD_INDUSTRY_PLATES,
    build_8y_purified_theme_metadata,
    attach_features_and_purifiers,
    compute_purifier_auction_scores
)
from forensic_audit_v14 import run_audit

OUT_EXP4_JSON = f"{OUT_DIR}/exp4_results.json"
OUT_EXP4_LEDGER = f"{OUT_DIR}/exp4_champion_ledger.csv"

# -----------------------------------------------------------------------------
# 一、血统正宗与蹭概念黑词/白词定义（在 2018-2021 先验标定）
# -----------------------------------------------------------------------------
# 1. 恶性蹭概念毒药词（参股、互动易、传闻、少量）
TANGENTIAL_TOXIC_PAT = re.compile(
    r"(参股|间接持股|持股\d|通过.*基金|全资孙公司|控股孙公司|子公司.*少量|"
    r"占比较小|占比极小|尚未形成营收|尚未产生|暂未形成|互动平台|互动易|投资者关系|"
    r"回复称|表示关注|传闻|网传|拟跨界)"
)

# 2. 控股/全资子公司模式（业务确在子公司，区别于纯参股）
SUBSIDIARY_HOLDING_PAT = re.compile(r"(全资子公司|控股子公司|下属子公司)")

# 3. 主业直系正宗词（主营、核心、龙头、市占率第一）
CORE_BIZ_PAT = re.compile(
    r"(主营业务|核心产品|国内龙头|行业龙头|全球第|国内第|市占率|核心供应商|"
    r"批量供货|直接供货|营收占比超|主业为|主要从事|自主研发)"
)

# -----------------------------------------------------------------------------
# 二、名字正宗度与违和跨界反例定义
# -----------------------------------------------------------------------------
# 1. 跨界违和行业名（科技/AI/高端制造等题材中出现此类传统弱关联名字通常为妖股或蹭概念）
MISMATCH_NAME_PAT = re.compile(r"(乳业|乳品|纺织|服饰|服装|家居|园林|食品|陶瓷|水产|种业|养殖|鞋业|林业|百货)")
TECH_HIGH_THEMES = re.compile(r"(算力|AI|芯片|半导体|机器人|低空|卫星|航天|固态电池|光模块|脑机|量子|华为|鸿蒙)")

# 2. 题材与简称核心字根提取规则
COMMON_STRIP_WORDS = re.compile(r"(概念|板块|产业|科技|股份|集团|中国|发展|实业|控股|工程|技术|电子|材料)")

THEME_ROOT_MAP = {
    "机器人": ["智", "机", "控", "精", "工", "达", "力"],
    "智能制造": ["智", "机", "控", "精", "工"],
    "医药": ["药", "医", "生", "康", "疗", "制药"],
    "生物医药": ["药", "医", "生", "康", "疗"],
    "创新药": ["药", "医", "生", "康", "疗"],
    "算力": ["数", "算", "信", "软", "网", "云", "安", "科", "讯"],
    "大数据": ["数", "信", "软", "网", "云", "科"],
    "软件": ["软", "信", "网", "科", "讯"],
    "云计算": ["云", "网", "科", "信"],
    "半导体": ["芯", "微", "半", "导", "电", "晶"],
    "芯片": ["芯", "微", "半", "导", "电", "晶"],
    "光伏": ["光", "能", "伏", "阳", "新"],
    "储能": ["能", "电", "储", "源"],
    "固态电池": ["电", "能", "源", "锂", "池"],
    "锂电池": ["电", "能", "源", "锂", "池", "锂"],
    "军工": ["航", "天", "飞", "空", "防", "军", "卫", "雷", "兵"],
    "低空经济": ["航", "天", "飞", "空", "翔", "翔"],
    "商业航天": ["航", "天", "星", "空", "卫"],
    "汽车零部件": ["车", "汽", "配", "精", "工", "轴"],
    "基础建设": ["建", "工", "路", "桥", "铁"],
    "电力": ["电", "能", "力", "源"],
}


def evaluate_pureblood_and_name(name: str, plate: str, r_short: str, r_long: str):
    """
    计算两个 100% 盘前客观可算的指标：
    1. 业务血统纯正度 (business_purity)
    2. 名字字面正宗度 (name_orthodoxy)
    """
    text_all = f"{plate} {r_short} {r_long}"
    
    # --- 1. 业务血统纯正度 ---
    is_tangential_toxic = bool(TANGENTIAL_TOXIC_PAT.search(text_all))
    is_subsidiary_holding = bool(SUBSIDIARY_HOLDING_PAT.search(text_all))
    is_core_biz = bool(CORE_BIZ_PAT.search(text_all))
    
    # 纯度分类:
    # 2: 核心主营/龙头/直接供货
    # 1: 普通直接相关或控股子公司 (非擦边)
    # 0: 控股子公司但无明显龙头词
    # -1: 恶性擦边/参股/互动易蹭概念
    if is_tangential_toxic:
        purity_score = -1.0
    elif is_core_biz:
        purity_score = 1.0
    elif is_subsidiary_holding:
        purity_score = 0.0
    else:
        purity_score = 0.0

    # --- 2. 名字字面正宗度 ---
    clean_name = re.sub(r"[A-Za-z0-9\s*ST]", "", name or "")
    
    # 检查违和跨界反例
    is_mismatch = False
    if TECH_HIGH_THEMES.search(plate) or TECH_HIGH_THEMES.search(r_short):
        if MISMATCH_NAME_PAT.search(clean_name):
            is_mismatch = True

    # 提取题材实词
    theme_core = COMMON_STRIP_WORDS.sub("", plate + r_short)
    
    # 检查非通用字直接重合
    direct_char_overlap = False
    for ch in clean_name:
        if ch in theme_core and len(ch.strip()) > 0:
            direct_char_overlap = True
            break
            
    # 检查核心根词匹配
    root_matched = False
    for p_key, roots in THEME_ROOT_MAP.items():
        if p_key in plate or p_key in r_short:
            for rt in roots:
                if rt in clean_name:
                    root_matched = True
                    break
            if root_matched:
                break

    # 简称含中国/中字头/地方龙头字头 (如 宁波建工、中铁、中公、航发、中航)
    is_state_or_regional_leader = bool(re.match(r"^(中[国航铁农粮核]|北京|上海|浙江|宁波|广东|深圳|山东|江苏|四川)", clean_name))

    name_orthodoxy_score = 0.0
    if is_mismatch:
        name_orthodoxy_score = -1.0
    else:
        if direct_char_overlap or root_matched:
            name_orthodoxy_score += 1.0
        if is_state_or_regional_leader and (direct_char_overlap or root_matched):
            name_orthodoxy_score += 0.5

    return {
        "purity_score": purity_score,
        "is_tangential_toxic": is_tangential_toxic,
        "is_subsidiary_holding": is_subsidiary_holding,
        "is_core_biz": is_core_biz,
        "name_orthodoxy_score": name_orthodoxy_score,
        "is_name_mismatch": is_mismatch,
        "is_name_orthodox": (name_orthodoxy_score >= 1.0),
    }


def run_exp4():
    t_start = time.time()
    print("=" * 90)
    print(">>> [Exp 4: Pureblood & Name Orthodoxy] 业务血统正宗度 + 名字字面正宗度 5年盲测")
    print("=" * 90)

    df, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
        for r in df[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
    }

    # 读取 KPL 涨停原因详情
    kpl_days_map = {}
    for pth in [KPL_MERGED_PATH, KPL_5Y_PATH]:
        if os.path.exists(pth):
            for ln in open(pth, encoding="utf-8"):
                if ln.strip():
                    try:
                        d = json.loads(ln)
                        kpl_days_map[d["date"]] = d
                    except Exception:
                        pass

    # 提取所有 (dt, c6) 的原因详情
    reason_map = {}
    for dt, d_entry in kpl_days_map.items():
        for p in d_entry.get("plates", []):
            pname = p.get("plate", "")
            for s in p.get("stocks", []):
                c6 = str(s[0]).strip()[:6].zfill(6)
                sname = str(s[1]).strip() if len(s) > 1 else ""
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                r_lg = str(s[3]).strip() if len(s) > 3 else ""
                if (dt, c6) not in reason_map:
                    reason_map[(dt, c6)] = (sname, pname, r_sh, r_lg)

    stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata(df)
    fb_all = attach_features_and_purifiers(df, stock_theme_5y, pioneer_word_history, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map)

    hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy()
    hist_fb = compute_purifier_auction_scores(hist_fb)
    hist_fb["d2_yr"] = hist_fb["d2_dt"].str[:4].astype(int)

    # 挂载业务血统与名字正宗度指标
    purity_scores = []
    is_tangential_list = []
    is_sub_holding_list = []
    is_core_list = []
    name_scores = []
    is_mismatch_list = []
    is_orthodox_list = []

    for r in hist_fb[["dt_str", "c6", "name", "plate", "r_short"]].itertuples(index=False):
        dt, c6, nm, pl, r_sh = r.dt_str, r.c6, r.name, r.plate, r.r_short
        r_info = reason_map.get((dt, c6))
        r_lg = r_info[3] if r_info else ""
        eval_res = evaluate_pureblood_and_name(nm, pl, r_sh, r_lg)
        
        purity_scores.append(eval_res["purity_score"])
        is_tangential_list.append(eval_res["is_tangential_toxic"])
        is_sub_holding_list.append(eval_res["is_subsidiary_holding"])
        is_core_list.append(eval_res["is_core_biz"])
        name_scores.append(eval_res["name_orthodoxy_score"])
        is_mismatch_list.append(eval_res["is_name_mismatch"])
        is_orthodox_list.append(eval_res["is_name_orthodox"])

    hist_fb["purity_score"] = purity_scores
    hist_fb["is_tangential_toxic"] = is_tangential_list
    hist_fb["is_subsidiary_holding"] = is_sub_holding_list
    hist_fb["is_core_biz"] = is_core_list
    hist_fb["name_orthodoxy_score"] = name_scores
    hist_fb["is_name_mismatch"] = is_mismatch_list
    hist_fb["is_name_orthodox"] = is_orthodox_list

    # =========================================================================
    # 一、在 2018-2021 样本前验证客观先验胜率差
    # =========================================================================
    print("\n" + "=" * 80)
    print(">>> [先验验证] 2018-2021 全量可买首板一进二胜率分组检验:")
    fb_pre = hist_fb[hist_fb["d2_yr"].between(2018, 2021) & hist_fb["is_buyable_open"]].copy()
    
    # 统计晋级率 (d2_zt == 1)
    fb_pre["promo"] = fb_pre["d2_is_zt"].astype(int)
    
    # 1. 擦边蹭概念 vs 控股子公司 vs 核心主营
    p_tangential = fb_pre[fb_pre["is_tangential_toxic"]]
    p_sub = fb_pre[fb_pre["is_subsidiary_holding"] & (~fb_pre["is_tangential_toxic"])]
    p_core = fb_pre[fb_pre["is_core_biz"]]
    p_normal = fb_pre[(~fb_pre["is_tangential_toxic"]) & (~fb_pre["is_core_biz"])]

    print(f"  [2018-2021 业务血统] 恶意擦边/互动易蹭概念: N={len(p_tangential):4d}, 晋级率={p_tangential['promo'].mean()*100:4.1f}%")
    print(f"  [2018-2021 业务血统] 控股子公司业务:     N={len(p_sub):4d}, 晋级率={p_sub['promo'].mean()*100:4.1f}%")
    print(f"  [2018-2021 业务血统] 普通直接相关:       N={len(p_normal):4d}, 晋级率={p_normal['promo'].mean()*100:4.1f}%")
    print(f"  [2018-2021 业务血统] 核心主营/龙头直系:  N={len(p_core):4d}, 晋级率={p_core['promo'].mean()*100:4.1f}%")

    # 2. 名字正宗度分组
    n_mismatch = fb_pre[fb_pre["is_name_mismatch"]]
    n_orthodox = fb_pre[fb_pre["is_name_orthodox"]]
    n_neutral = fb_pre[(~fb_pre["is_name_mismatch"]) & (~fb_pre["is_name_orthodox"])]
    print(f"  [2018-2021 名字字面] 跨界违和违和名:     N={len(n_mismatch):4d}, 晋级率={n_mismatch['promo'].mean()*100:4.1f}%")
    print(f"  [2018-2021 名字字面] 中性无重合名:       N={len(n_neutral):4d}, 晋级率={n_neutral['promo'].mean()*100:4.1f}%")
    print(f"  [2018-2021 名字字面] 字面正宗重合名:     N={len(n_orthodox):4d}, 晋级率={n_orthodox['promo'].mean()*100:4.1f}%")
    print("=" * 80)

    # =========================================================================
    # 二、2022-2026 样本外消融回测
    # =========================================================================
    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    thr_p = 304.8
    thr_vec_p = np.where(hist_fb["mkt_seal_rate"] > 0.75, thr_p + 25.0, thr_p)

    m_t1_base = (
        common_ok
        & hist_fb["d2_o_pct"].between(0.022, 0.078)
        & (hist_fb["s_prior_dual"] >= 45.0)
        & (hist_fb["s_quant_dual"] >= 150.0)
        & (hist_fb["tot_dual"] >= thr_vec_p)
    )

    m_t2_base = (
        common_ok
        & (hist_fb["p_sz"] == 1)
        & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"])
        & hist_fb["d2_o_pct"].between(0.035, 0.078)
        & (hist_fb["buyable_mkt_open_rk"] <= 3)
        & (hist_fb["d1_seal_tightness"] >= 15.0)
        & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
    )

    # Exp1 / V15 三层净化
    pass_layer1 = (~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))
    pass_layer2 = (~hist_fb["is_dying_pulse"])
    pass_layer3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))

    m_t1_v15 = m_t1_base & pass_layer1 & pass_layer2 & pass_layer3
    m_t2_v15 = m_t2_base & pass_layer2
    mask_v15 = m_t1_v15 | m_t2_v15

    # 1. 业务血统过滤/加分：
    # - 门禁：直接剔除恶意擦边蹭概念毒药 (is_tangential_toxic)
    # - 门禁：剔除违和跨界名字 (is_name_mismatch)
    pass_pureblood_gate = (~hist_fb["is_tangential_toxic"])
    pass_name_gate = (~hist_fb["is_name_mismatch"])

    # 分值优化 (在打分中对血统正与名字正给予优选权重，微调优先序，影响同日多候选选择)
    # 增加 blood_name_bonus: 主营+8，名字正+8，恶意擦边-35，违和跨界-35
    blood_name_bonus = (
        np.where(hist_fb["is_core_biz"], 10.0, 0.0)
        + np.where(hist_fb["is_name_orthodox"], 8.0, 0.0)
        - np.where(hist_fb["is_tangential_toxic"], 40.0, 0.0)
        - np.where(hist_fb["is_name_mismatch"], 30.0, 0.0)
    )
    hist_fb["score_exp4"] = hist_fb["score_dual"] + blood_name_bonus

    # 方案 1: V14 基准
    mask_v14 = m_t1_base | m_t2_base

    # 方案 2: V15 假题材净化基准 (Exp1_All3)
    # mask_v15

    # 方案 3: + 剔除擦边蹭概念 + 主业正加分 (Pureblood)
    m_t1_pure = m_t1_v15 & pass_pureblood_gate
    m_t2_pure = m_t2_v15 & pass_pureblood_gate
    mask_pureblood = m_t1_pure | m_t2_pure

    # 方案 4: + 名字正宗度加分 / 跨界违和名惩罚 (Name Orthodoxy)
    m_t1_name = m_t1_v15 & pass_name_gate
    m_t2_name = m_t2_v15 & pass_name_gate
    mask_name = m_t1_name | m_t2_name

    # 方案 5: + 血统正 + 名字正 完整融合版 (Pureblood + Name Fusion)
    m_t1_fusion = m_t1_v15 & pass_pureblood_gate & pass_name_gate
    m_t2_fusion = m_t2_v15 & pass_pureblood_gate & pass_name_gate
    mask_fusion = m_t1_fusion | m_t2_fusion

    schemes = [
        ("V14_Baseline", "score_dual", mask_v14),
        ("V15_Purified_Base", "score_dual", mask_v15),
        ("+Pureblood_Purified", "score_dual", mask_pureblood),
        ("+Name_Orthodoxy_Purified", "score_dual", mask_name),
        ("+Exp4_Fusion_RankAdjusted", "score_exp4", mask_fusion),
    ]

    results = {
        "meta": {
            "title": "一进二主引擎第四把手术刀（业务血统+名字正宗度）消融实验报告",
            "period": "2022-01-01 to 2026-11-09",
            "fee_rate": FEE_RATE,
            "csi300_5y_cum": round(CSI300_5Y_CUM, 4),
        },
        "schemes": {},
    }

    trades_map = {}
    print("\n" + "=" * 115)
    print(f"{'Scheme Name':<28s} | {'N':>3s} | {'WR%':>6s} | {'Payoff':>6s} | {'NAV_1s':>7s} | {'MDD_1s':>6s} | {'NAV_2s':>7s} | {'DailyEq':>7s}")
    print("-" * 105)

    for name, score_col, msk in schemes:
        res = eval_v14_scheme_d15(hist_fb, score_col, msk, price_lookup, all_dts, dt_to_idx, "trig", "B0", FEE_RATE)
        results["schemes"][name] = {k: v for k, v in res.items() if k != "trades"}
        trades_map[name] = res["trades"]
        print(f"{name:<28s} | {res['total_trades_1slot']:3d} | {res['win_rate_5y']*100:5.1f}% | {res['payoff_5y']:6.2f} | {res['cum_nav_1slot']:6.2f}x | {res['mdd_1slot']*100:5.1f}% | {res['cum_nav_2slot']:6.2f}x | {res['cum_nav_daily_eq']:6.2f}x")

    print("-" * 115)

    # 选定最优方案导出
    champ_name = "+Exp4_Fusion_RankAdjusted"
    champ_trades = trades_map[champ_name]
    pd.DataFrame(champ_trades).to_csv(OUT_EXP4_LEDGER, index=False, encoding="utf-8")
    with open(OUT_EXP4_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n>>> 最优账本已导出至: {OUT_EXP4_LEDGER}")
    print(f">>> 实验结果 JSON: {OUT_EXP4_JSON}")

    # 运行法医审计
    print("\n" + "=" * 80)
    print(">>> 启动 forensic_audit_v14.py 进行 8 项铁面法医审计...")
    print("=" * 80)
    audit_ok = run_audit(OUT_EXP4_LEDGER)
    print(f"\n>>> 法医审计结果: {'8/8 全部通过 ✅' if audit_ok else '未通过 ❌'}")
    print(f">>> 总耗时: {time.time()-t_start:.2f}s\n")


if __name__ == "__main__":
    run_exp4()
