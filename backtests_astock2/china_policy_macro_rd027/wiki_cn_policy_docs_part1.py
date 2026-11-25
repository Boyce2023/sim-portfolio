"""Builders for China Macro & Policy Feishu Wiki sub-docs 1 to 3 (Wave 3 Critic verified)."""


def build_doc1_waterpool(d: dict) -> list[dict]:
    """Doc 1: 水池与千因子."""
    w2, t1, c = d["w2"], d["t1"], d["c"]
    gs, pt = w2["global_summary"], w2["per_target_summary"]
    c1w = c["critic1_tool1_ablation"]["windows"]
    lag = c["critic1_tool1_ablation"]["waterpool_pit_lag_sensitivity"]
    c2e = c["critic2_extreme_and_pit"]["extreme_leverage_test"]
    c2p = c["critic2_extreme_and_pit"]["pit_alignment_audit"]
    name_map = {
        ("wp_cash_dividend_mcap_12m", "tgt_ew_all_fwd_120d"): "12M分红占市值比(全A)",
        ("wp_cash_dividend_mcap_12m", "tgt_csi300_fwd_120d"): "12M分红占市值比(300)",
        ("wp_ipo_count_3m", "tgt_ew_all_fwd_120d"): "3M IPO家数(全A)",
        ("wp_insider_net_reduce_mcap_6m", "tgt_csi300_fwd_250d"): "6M产业净减持(300)",
        ("wp_inject_total_incl_div_mcap_12m", "tgt_ew_all_fwd_120d"): "12M含分红总输血",
        ("f2_erp_csi300_pct", "tgt_csi300_fwd_60d_mdd"): "沪深300 ERP(60日MDD)",
        ("f2_dt_ratio", "tgt_csi300_fwd_60d_mdd"): "两市跌停占比(60日MDD)",
        ("f3_cn_ppi_yoy_chg13w", "tgt_csi300_fwd_60d"): "PPI同比13周变化",
        ("f3_cn_macro_pain_composite", "tgt_div_minus_chinext_120d"): "中国宏观痛阈(红利创)",
        ("f4_us_fed_assets_yoy_chg13w", "tgt_csi300_fwd_120d"): "美联储扩表13周",
        ("f4_us_dff_chg26w", "tgt_div_minus_chinext_120d"): "联邦基金利率26周变化",
        ("f7_g1_deep_freeze__x__wp_net_waterpool_incl_div_mcap_3m", "tgt_csi300_fwd_250d"): "深跌乘净水池3M",
        ("f7_g1_deep_freeze__x__f2_erp_all_a_median_pct", "tgt_csi300_fwd_60d"): "深跌乘全A中位ERP",
        ("f7_g1_deep_freeze__x__d_margin_chg_20d_mcap", "tgt_micro30_minus_300_120d"): "深跌乘两融去杠杆",
    }
    ext_rows = []
    for x in c2e:
        st = "通过" if x["status"] == "PASS" else ("有条件" if "COND" in x["status"] else "淘汰")
        ext_rows.append([name_map[(x["factor"], x["target"])], f"{x['t_full']:+.2f}", f"{x['t_drop_2015']:+.2f}", f"{x['t_drop_all3_extreme']:+.2f}", st])

    cur24 = t1["current_2026_11_24_pit_completed_month"]
    cur25 = t1["current_2026_11_25_with_nov_mtd"]
    return [
        {"t": "h1", "text": "水池与千因子"},
        {"t": "mark_p", "text": "中国水池与宏观因子只管中长周期赔率与回撤风控，单靠水位打分做自动择时其实跑输无信号纯风控。"},
        {"t": "p", "text": f"本篇汇总 2005.01 至 2026.11 共 263 个月与 5,316 个交易日实证，全部行情取自本土全市场数据库。"},
        {"t": "p", "text": f"数据严格剔除 2024.08.16 停更的北向日频资金及 2026.04 断更的社融存量，避免断更假信号。"},
        {"t": "p", "text": f"全样本 {w2['n_factors']} 个因子对照 {w2['n_targets']} 大目标共做 {w2['total_tests']} 次周频检验，S 级仅 {gs['unique_factors_S_only']} 个。"},
        {"t": "p", "text": f"S 与 A 级真因子合计 {gs['unique_factors_SA_hlz']} 个，总幸存率 {gs['unique_factors_SA_pct']}%。"},
        {"t": "h2", "text": "一、二十二年抽血与输血总账本"},
        {"t": "p", "text": "拆清资金流向后可见，A 股交易端长期净失血，全靠现金分红把总账本拉回净流入。"},
        {"t": "ul", "items": [
            "累计抽血 232,050.5 亿元：IPO 募资 50,244.9 亿，再融资 120,727.4 亿，产业净减持 29,298.0 亿，印花税 27,356.6 亿。",
            "交易端累计输血 50,130.2 亿元：回购 9,464.5 亿，国家队 ETF 净流入 1,628.7 亿，北向停更前 17,615.2 亿，两融余额 21,421.8 亿。",
            "纯交易端二十二年净失血 181,920.3 亿元，叠加上市公司现金分红 226,723.6 亿元后，含分红全口径净流入 +44,803.4 亿元。",
        ]},
        {"t": "table", "headers": ["历史节点", "交易净流(亿)", "含分红净流(亿)", "200日线上占比", "沪深300 ERP"], "rows": [
            ["2008.11 四万亿底", "-42.5", "+217.7", "1.6%", "4.73%"],
            ["2018.10 政策联合底", "-620.7", "-525.1", "4.8%", "5.93%"],
            ["2024.09 924大底", "+1,657.6", "+3,320.3", "78.0%", "5.75%"],
            ["2026.11 最新月度", "+671.0", "+956.5", "8.65%", "6.30%"],
        ]},
        {"t": "h2", "text": "二、千因子四重筛选与八大假设裁决"},
        {"t": "p", "text": f"8,792 次因子目标检验中有 {gs['pair_tier_counts']['过拟合淘汰']} 对在样本外淘汰，短线噪音占比极高。"},
        {"t": "p", "text": "预测 60 日最大回撤最容易过关，科技相对沪深 300 几乎找不到稳健的宏观直接驱动。"},
        {"t": "table", "headers": ["预测目标", "S级数量", "S与A合计", "幸存率", "代表有效方向"], "rows": [
            ["沪深300的60日回撤", f"{pt['tgt_csi300_fwd_60d_mdd']['S_tier_3era_hlz']}", f"{pt['tgt_csi300_fwd_60d_mdd']['robust_SA_total']}", f"{pt['tgt_csi300_fwd_60d_mdd']['robust_SA_pct']}%", "ERP与宏观痛阈"],
            ["沪深300的60日收益", f"{pt['tgt_csi300_fwd_60d']['S_tier_3era_hlz']}", f"{pt['tgt_csi300_fwd_60d']['robust_SA_total']}", f"{pt['tgt_csi300_fwd_60d']['robust_SA_pct']}%", "PPI变化与全A估值"],
            ["红利减创业板120日", f"{pt['tgt_div_minus_chinext_120d']['S_tier_3era_hlz']}", f"{pt['tgt_div_minus_chinext_120d']['robust_SA_total']}", f"{pt['tgt_div_minus_chinext_120d']['robust_SA_pct']}%", "美息与国内痛阈"],
            ["沪深300的250日收益", f"{pt['tgt_csi300_fwd_250d']['S_tier_3era_hlz']}", f"{pt['tgt_csi300_fwd_250d']['robust_SA_total']}", f"{pt['tgt_csi300_fwd_250d']['robust_SA_pct']}%", "产业减持与分红"],
            ["沪深300的120日收益", f"{pt['tgt_csi300_fwd_120d']['S_tier_3era_hlz']}", f"{pt['tgt_csi300_fwd_120d']['robust_SA_total']}", f"{pt['tgt_csi300_fwd_120d']['robust_SA_pct']}%", "美联储扩表与分红"],
            ["全A等权120日收益", f"{pt['tgt_ew_all_fwd_120d']['S_tier_3era_hlz']}", f"{pt['tgt_ew_all_fwd_120d']['robust_SA_total']}", f"{pt['tgt_ew_all_fwd_120d']['robust_SA_pct']}%", "分红与3M IPO家数"],
            ["微盘减300的120日", f"{pt['tgt_micro30_minus_300_120d']['S_tier_3era_hlz']}", f"{pt['tgt_micro30_minus_300_120d']['robust_SA_total']}", f"{pt['tgt_micro30_minus_300_120d']['robust_SA_pct']}%", "深跌乘两融变化"],
            ["科技减300的120日", f"{pt['tgt_tech_minus_300_120d']['S_tier_3era_hlz']}", f"{pt['tgt_tech_minus_300_120d']['robust_SA_total']}", f"{pt['tgt_tech_minus_300_120d']['robust_SA_pct']}%", "极缺宏观直接驱动"],
        ]},
        {"t": "ul", "items": [
            "M1 减 M2 剪刀差在沪深 300 全样本 120 日 t 值仅 -1.05 不显著，真正有效的是社融脉冲 t = +2.94。",
            "人民币汇率破 7 显著压制小微盘，120 日微盘相对沪深 300 跑输达 -10.87pp。",
            "沪深 300 ERP 呈现短弱长强，20 日 t 值仅 0.27，拉长到 250 日升至 3.68。",
            "12M 抽血占市值比仅在 2021 年后发挥硬约束（250 日 OOS（样本外）t = -10.43），早年曾现吸金同涨。",
        ]},
        {"t": "h2", "text": "三、反单点极值审计与跌停因子淘汰教训"},
        {"t": "mark_p", "text": "14 对核心因子里 12 对扛过三段极值全剔考验，原排头兵两市跌停占比剔除 2015 年即塌陷淘汰。"},
        {"t": "p", "text": "红队同步剔除 2008 金融危机、2015 股灾与 2024 年 924 三段极端行情，防止单次历史脉冲制造虚假高分。"},
        {"t": "p", "text": f"PIT（点时点）检查显示，周表 139 列水池指标均在月末后 10 个自然日以上生效，泄露数为 0。"},
        {"t": "p", "text": f"但工具 1 与工具 3 日频表月初 1 至 9 日曾有 {c2p['tool1_and_tool3_wp_early_month_days_1_to_9_count']} 行提前用了上月数值，上线前已锁死 10 日后生效。"},
        {"t": "table", "headers": ["核心因子(目标)", "全样本t", "剔2015t", "三段全剔t", "红队裁决"], "rows": ext_rows},
        {"t": "h2", "text": "四、水位自动择时为何跑输纯波动率基线"},
        {"t": "mark_p", "text": f"工具 1 全样本 Sharpe 仅 {c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_CSI300']['sharpe']}，低于静态等均仓 {c1w['FULL_2005_2026']['strategies']['Static_AvgW_CSI300']['sharpe']}，更跑输纯 1/vol 基线 {c1w['FULL_2005_2026']['strategies']['Pure_1overVol_MatchedW_CSI300']['sharpe']}。"},
        {"t": "p", "text": f"工具 1 全样本平均股票仓位仅 {c1w['FULL_2005_2026']['w_bar_pct']}%，表面回撤更小主要是常年拿近四成现金垫子。"},
        {"t": "p", "text": f"更致命的是分数漂移：70 分以上占比从样本内 11.9% 飙到近 3 年 81.1%，严格滞后 1 整月后 OOS（样本外）超额从 +{lag['orig_td1']['OOS_Dyn300']['excess_ann_vs_csi300_pp']}pp 跌至 +{lag['full_1m']['OOS_Dyn300']['excess_ann_vs_csi300_pp']}pp。"},
        {"t": "p", "text": f"截至 2026.11.24 严格 PIT（点时点）水位 {cur24['total_score']} 分（11.25 当月累计升至 {cur25['total_score']} 分），只作 3 至 12 个月赔率参考。"},
        {"t": "table", "headers": ["策略与基线", "全样本年化", "全样本Sharpe", "全样本MDD", "OOS（样本外）年化", "年换手率"], "rows": [
            ["沪深300基准持有", f"{c1w['FULL_2005_2026']['strategies']['CSI300_BH']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['CSI300_BH']['sharpe']}", f"{c1w['FULL_2005_2026']['strategies']['CSI300_BH']['mdd_pct']}%", f"{c1w['OOS_2021_2026']['strategies']['CSI300_BH']['ann_ret_pct']}%", "0.0%"],
            ["工具1动态300", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_CSI300']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_CSI300']['sharpe']}", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_CSI300']['mdd_pct']}%", f"{c1w['OOS_2021_2026']['strategies']['Waterpool_Dyn_CSI300']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_CSI300']['annual_turnover_pct']}%"],
            ["静态等均仓300", f"{c1w['FULL_2005_2026']['strategies']['Static_AvgW_CSI300']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Static_AvgW_CSI300']['sharpe']}", f"{c1w['FULL_2005_2026']['strategies']['Static_AvgW_CSI300']['mdd_pct']}%", f"{c1w['OOS_2021_2026']['strategies']['Static_AvgW_CSI300']['ann_ret_pct']}%", "0.0%"],
            ["纯1/vol同均仓", f"{c1w['FULL_2005_2026']['strategies']['Pure_1overVol_MatchedW_CSI300']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Pure_1overVol_MatchedW_CSI300']['sharpe']}", f"{c1w['FULL_2005_2026']['strategies']['Pure_1overVol_MatchedW_CSI300']['mdd_pct']}%", f"{c1w['OOS_2021_2026']['strategies']['Pure_1overVol_MatchedW_CSI300']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Pure_1overVol_MatchedW_CSI300']['annual_turnover_pct']}%"],
            ["动态水池风格版", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_Style']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_Style']['sharpe']}", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_Style']['mdd_pct']}%", f"{c1w['OOS_2021_2026']['strategies']['Waterpool_Dyn_Style']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_Style']['annual_turnover_pct']}%"],
            ["静态同均仓风格版", f"{c1w['FULL_2005_2026']['strategies']['Static_AvgW_StyleMix']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Static_AvgW_StyleMix']['sharpe']}", f"{c1w['FULL_2005_2026']['strategies']['Static_AvgW_StyleMix']['mdd_pct']}%", f"{c1w['OOS_2021_2026']['strategies']['Static_AvgW_StyleMix']['ann_ret_pct']}%", "0.0%"],
        ]},
    ]


def build_doc2_meetings_bottoms(d: dict) -> list[dict]:
    """Doc 2: 顶层会议与真假底."""
    p2, p5 = d["p2"], d["p5"]
    sigs = {x["signal"]: x for x in p2["diff_vs_static_comparison"]}
    pb_slice = {x["signal"]: x for x in p2["politburo_2013_2026_slice"]}
    tb = p5["watershed_summary"]["TRUE_POLICY_BOTTOM"]
    ft = p5["watershed_summary"]["FALSE_BOTTOM_TRAP"]
    tp = p5["watershed_summary"]["POLICY_VALUATION_TOP"]
    fg = p5["four_gates_classifier_on_bottom_attempts"]

    return [
        {"t": "h1", "text": "顶层会议与真假底"},
        {"t": "mark_p", "text": "顶层会议只看一阶措辞升级才有效，史诗级真假底则必须跨过四道物理门里的至少三门。"},
        {"t": "p", "text": f"本篇拆解 2005.03 至 2026.07 共 {p2['n_meetings']} 场顶层会议通稿，并复盘 1999 至 2026 年 25 次大拐点。"},
        {"t": "p", "text": "110 场会议覆盖政府工作报告 22 场、7 月政治局 22 场、12 月政治局 21 场与中央经济工作会议 21 场。"},
        {"t": "p", "text": "市场常犯的错，是把静态高频词当利好，或者见最高层喊话就闭眼当政策底。"},
        {"t": "p", "text": "二十五年实证给出硬答案：真底不仅要嘴上转弯，更要止血阀与真扩表同时落地。"},
        {"t": "h2", "text": "一、110 场顶层会议一阶措辞升级胜过静态姿态"},
        {"t": "p", "text": "会议文本对比证明，相比上一场会议的一阶边际升级，远比静态高姿态更有定价弹性。"},
        {"t": "ul", "items": [
            f"超预期转向信号（16 次）会后 60 日基准均值 +{sigs['DIFF_surprise_pos_shift']['bench_60d_mean_pct']}%，胜率 {sigs['DIFF_surprise_pos_shift']['bench_60d_win_pct']}%，全 A 等权超额 +{sigs['DIFF_surprise_pos_shift']['ex_ew_60d_mean_pct']}pp。",
            f"宏观基调升级一档以上（44 次）60 日基准均值 +{sigs['DIFF_macro_stance_up_ge1']['bench_60d_mean_pct']}%，胜率 {sigs['DIFF_macro_stance_up_ge1']['bench_60d_win_pct']}%。",
            f"地产定调边际升级（16 次）会后 5 日胜率高达 {sigs['DIFF_property_upgrade_ge1']['bench_5d_win_pct']}%，120 日基准均值 +{sigs['DIFF_property_upgrade_ge1']['bench_120d_mean_pct']}%。",
            f"静态高姿态（40 次）60 日均值仅 +{sigs['STATIC_macro_stance_ge4']['bench_60d_mean_pct']}%，静态最高级提股市（7 次）20 日均值仅 +{sigs['STATIC_tone_equity_eq3']['bench_20d_mean_pct']}%。",
            f"2013 至 2026 政治局单切片显示，近十年基调升级后 20 日与 60 日均值收敛至 +{pb_slice['PB13_26_DIFF_macro_stance_up_ge1']['bench_20d_mean_pct']}% 与 +{pb_slice['PB13_26_DIFF_macro_stance_up_ge1']['bench_60d_mean_pct']}%。",
        ]},
        {"t": "table", "headers": ["会议信号类型", "样本数", "T+5均值(胜率)", "T+20均值", "T+60均值", "T+120均值"], "rows": [
            ["一阶_超预期正转向", f"{sigs['DIFF_surprise_pos_shift']['n']}", f"+{sigs['DIFF_surprise_pos_shift']['bench_5d_mean_pct']}% ({sigs['DIFF_surprise_pos_shift']['bench_5d_win_pct']}%)", f"+{sigs['DIFF_surprise_pos_shift']['bench_20d_mean_pct']}%", f"+{sigs['DIFF_surprise_pos_shift']['bench_60d_mean_pct']}%", f"+{sigs['DIFF_surprise_pos_shift']['bench_120d_mean_pct']}%"],
            ["一阶_宏观基调升级", f"{sigs['DIFF_macro_stance_up_ge1']['n']}", f"+{sigs['DIFF_macro_stance_up_ge1']['bench_5d_mean_pct']}% ({sigs['DIFF_macro_stance_up_ge1']['bench_5d_win_pct']}%)", f"+{sigs['DIFF_macro_stance_up_ge1']['bench_20d_mean_pct']}%", f"+{sigs['DIFF_macro_stance_up_ge1']['bench_60d_mean_pct']}%", f"+{sigs['DIFF_macro_stance_up_ge1']['bench_120d_mean_pct']}%"],
            ["一阶_股市表述升级", f"{sigs['DIFF_equity_upgrade_ge1']['n']}", f"+{sigs['DIFF_equity_upgrade_ge1']['bench_5d_mean_pct']}% ({sigs['DIFF_equity_upgrade_ge1']['bench_5d_win_pct']}%)", f"+{sigs['DIFF_equity_upgrade_ge1']['bench_20d_mean_pct']}%", f"+{sigs['DIFF_equity_upgrade_ge1']['bench_60d_mean_pct']}%", f"+{sigs['DIFF_equity_upgrade_ge1']['bench_120d_mean_pct']}%"],
            ["一阶_地产表述升级", f"{sigs['DIFF_property_upgrade_ge1']['n']}", f"+{sigs['DIFF_property_upgrade_ge1']['bench_5d_mean_pct']}% ({sigs['DIFF_property_upgrade_ge1']['bench_5d_win_pct']}%)", f"+{sigs['DIFF_property_upgrade_ge1']['bench_20d_mean_pct']}%", f"+{sigs['DIFF_property_upgrade_ge1']['bench_60d_mean_pct']}%", f"+{sigs['DIFF_property_upgrade_ge1']['bench_120d_mean_pct']}%"],
            ["静态_宏观高姿态", f"{sigs['STATIC_macro_stance_ge4']['n']}", f"+{sigs['STATIC_macro_stance_ge4']['bench_5d_mean_pct']}% ({sigs['STATIC_macro_stance_ge4']['bench_5d_win_pct']}%)", f"+{sigs['STATIC_macro_stance_ge4']['bench_20d_mean_pct']}%", f"+{sigs['STATIC_macro_stance_ge4']['bench_60d_mean_pct']}%", f"+{sigs['STATIC_macro_stance_ge4']['bench_120d_mean_pct']}%"],
            ["静态_最高级提股市", f"{sigs['STATIC_tone_equity_eq3']['n']}", f"+{sigs['STATIC_tone_equity_eq3']['bench_5d_mean_pct']}% ({sigs['STATIC_tone_equity_eq3']['bench_5d_win_pct']}%)", f"+{sigs['STATIC_tone_equity_eq3']['bench_20d_mean_pct']}%", f"+{sigs['STATIC_tone_equity_eq3']['bench_60d_mean_pct']}%", f"+{sigs['STATIC_tone_equity_eq3']['bench_120d_mean_pct']}%"],
        ]},
        {"t": "h2", "text": "二、四道物理门 100% 劈开十真底与七假底"},
        {"t": "mark_p", "text": f"以通过 3 门为界，四道物理门在 {fg['true_positives']} 次真底与 {fg['true_negatives']} 次假底上实现零误判的 {fg['accuracy_pct']}% 精准切分。"},
        {"t": "ul", "items": [
            "门一止血阀：IPO 发行、再融资或产业净减持出现实质性收紧，堵住市场净抽血缺口。",
            "门二真扩表：央行强力降息降准、创设直通股市流动性工具，或汇金类平准基金真金白银净买入。",
            "门三破格定调：最高层会议或权威联合发声突破常规词库，直接把稳股市与扭转预期摆上台面。",
            "门四深度出清：成交分位低于 25%，或 60 日回撤满 15%，或 250 日回撤满 25%，完成筹码出清。",
        ]},
        {"t": "p", "text": f"10 次真底平均过 {tb['avg_four_gates_score']} 门，前三大门触发率全为 100%；7 次假底无一超过 2 门。"},
        {"t": "p", "text": f"真底后一年均值 +{tb['T+250_bench_mean_pct']}%；假底 T+120 与 T+250 均值跌至 {ft['T+120_bench_mean_pct']}% 与 {ft['T+250_bench_mean_pct']}%，胜率全是 0%。"},
        {"t": "table", "headers": ["拐点类别", "样本与均门数", "T+20均值", "T+60均值", "T+120均值", "T+250均值(胜率)"], "rows": [
            ["真政策底", f"{tb['n_cases']}次 ({tb['avg_four_gates_score']}门)", f"+{tb['T+20_bench_mean_pct']}%", f"+{tb['T+60_bench_mean_pct']}%", f"+{tb['T+120_bench_mean_pct']}%", f"+{tb['T+250_bench_mean_pct']}% ({tb['T+250_bench_win_pct']}%)"],
            ["假底陷阱", f"{ft['n_cases']}次 ({ft['avg_four_gates_score']}门)", f"{ft['T+20_bench_mean_pct']}%", f"{ft['T+60_bench_mean_pct']}%", f"{ft['T+120_bench_mean_pct']}%", f"{ft['T+250_bench_mean_pct']}% ({ft['T+250_bench_win_pct']}%)"],
            ["政策估值顶", f"{tp['n_cases']}次 ({tp['avg_four_gates_score']}门)", f"{tp['T+20_bench_mean_pct']}%", f"{tp['T+60_bench_mean_pct']}%", f"{tp['T+120_bench_mean_pct']}%", f"{tp['T+250_bench_mean_pct']}% ({tp['T+250_bench_win_pct']}%)"],
        ]},
        {"t": "table", "headers": ["经典拐点案例", "类别与门数", "物理缺口或触发核心", "T+60收益", "T+250收益"], "rows": [
            ["2008.11 四万亿", "真底 (4门)", "停IPO加4万亿扩表", "+35.74%", "+111.67%"],
            ["2018.10 副总理发声", "真底 (4门)", "纾困质押加政治局定调", "+1.66%", "+29.57%"],
            ["2024.09 924大招", "真底 (3门)", "限减持加SFISF加926", "+17.04%", "+35.64%"],
            ["2025.04 关税抗击", "真底 (3门)", "汇金平准加央行再贷款", "+10.68%", "+31.43%"],
            ["2008.04 降印花税", "假底 (1门)", "只降摩擦税未停IPO", "-22.15%", "-27.41%"],
            ["2015.07 救市一浪", "假底 (2门)", "配资强平链未清零", "-24.64%", "-22.40%"],
            ["2023.07 724会议", "假底 (2门)", "高层首提但缺止血扩表", "-9.81%", "-12.47%"],
            ["2023.08 四箭齐发", "假底 (2门)", "降税限IPO但无央行接盘", "-10.22%", "-16.71%"],
        ]},
        {"t": "h2", "text": "三、解构李大霄视角边界与情绪极值定位"},
        {"t": "p", "text": "市场常拿李大霄早年的「钻石底」或「婴儿底」作反指调侃，本质是混淆了估值口号与物理条件。"},
        {"t": "ul", "items": [
            "2012.07 沪指 2132 点「钻石底」期间只见温和降准与估值低位，IPO 照发且无地产信用扩表，0 门状态下随后跌破 2000 点。",
            "他后来总结的四大风向标（上市公司买卖股票、估值、汇金、社保），已分别对应本体系的门一、门四与门二。",
            "实操边界很清晰：名嘴喊话只作散户情绪极值彩蛋观察，任何时候都必须回到四道物理门逐门打勾验证。",
        ]},
    ]


def build_doc3_traffic_lights(d: dict) -> list[dict]:
    """Doc 3: 产业红绿灯."""
    p3, t2, c = d["p3"], d["t2"], d["c"]
    sigs = {
        (x["signal_type"], x["split"]): x
        for x in p3["summary_by_signal"]["spliced_panel"]
        if x["split"] in ("FULL", "OOS_2021_2026")
    }
    w_full = t2["backtest_windows"]["FULL_2008_2026"]
    w_oos = t2["backtest_windows"]["OOS_2021_2026"]
    w_3y = t2["backtest_windows"]["OOS_3Y_2024_2026"]
    c3l = {x["case"]: x for x in c["critic3_tool2_and_tool3"]["tool2_leave_one_sector_out"]}
    live = t2["live_2026_11_25_traffic_lights"]

    return [
        {"t": "h1", "text": "产业红绿灯"},
        {"t": "mark_p", "text": "部委 120 日红灯死刑排雷跨期最稳，250 日绿灯补贴池近三年高度依赖半导体须防过剩。"},
        {"t": "p", "text": f"本篇整理 2008.08 至 2026.11 共 {p3['n_events']} 条部委产业文件，映射 14 个核心 A 股行业板块。"},
        {"t": "p", "text": "事件分成三类绿灯（补贴规划 62 条、松绑并购 62 条、供给收缩 10 条）与两类红灯（严打叫停 36 条、限价加税 9 条）。"},
        {"t": "p", "text": "所有组合统一按 T+1 开盘调仓并扣除双边 0.30% 交易成本，对照全 14 行业等权与沪深 300 基准。"},
        {"t": "p", "text": "红队审计证明，政策最大的结构性价值不在追逐热闹补贴，而在避开被行政打击的行业雷区。"},
        {"t": "h2", "text": "一、179 条部委文件五类信号超额分化"},
        {"t": "p", "text": "行政红灯打压见效极快且持续一整年，而供给收缩文件常发生于需求下滑后，长周期反而跑输。"},
        {"t": "table", "headers": ["信号类别", "全样本条数", "120日全样本超额", "250日全样本超额", "250日OOS（样本外）超额"], "rows": [
            ["绿灯_补贴规划", f"{sigs[('GREEN_SUBSIDY_PLAN', 'FULL')]['n_events']}", f"+{sigs[('GREEN_SUBSIDY_PLAN', 'FULL')]['ex_mean_120d_pct']}%", f"+{sigs[('GREEN_SUBSIDY_PLAN', 'FULL')]['ex_mean_250d_pct']}%", f"+{sigs[('GREEN_SUBSIDY_PLAN', 'OOS_2021_2026')]['ex_mean_250d_pct']}%"],
            ["绿灯_松绑并购", f"{sigs[('GREEN_DEREG_MA', 'FULL')]['n_events']}", f"{sigs[('GREEN_DEREG_MA', 'FULL')]['ex_mean_120d_pct']}%", f"+{sigs[('GREEN_DEREG_MA', 'FULL')]['ex_mean_250d_pct']}%", f"{sigs[('GREEN_DEREG_MA', 'OOS_2021_2026')]['ex_mean_250d_pct']}%"],
            ["绿灯_供给收缩", f"{sigs[('GREEN_SUPPLY_CUT', 'FULL')]['n_events']}", f"{sigs[('GREEN_SUPPLY_CUT', 'FULL')]['ex_mean_120d_pct']}%", f"{sigs[('GREEN_SUPPLY_CUT', 'FULL')]['ex_mean_250d_pct']}%", f"+{sigs[('GREEN_SUPPLY_CUT', 'OOS_2021_2026')]['ex_mean_250d_pct']}%"],
            ["红灯_严打叫停", f"{sigs[('RED_CRACKDOWN_BAN', 'FULL')]['n_events']}", f"{sigs[('RED_CRACKDOWN_BAN', 'FULL')]['ex_mean_120d_pct']}%", f"{sigs[('RED_CRACKDOWN_BAN', 'FULL')]['ex_mean_250d_pct']}%", f"{sigs[('RED_CRACKDOWN_BAN', 'OOS_2021_2026')]['ex_mean_250d_pct']}%"],
            ["红灯_限价加税", f"{sigs[('RED_PRICE_CAP_TAX', 'FULL')]['n_events']}", f"{sigs[('RED_PRICE_CAP_TAX', 'FULL')]['ex_mean_120d_pct']}%", f"{sigs[('RED_PRICE_CAP_TAX', 'FULL')]['ex_mean_250d_pct']}%", f"{sigs[('RED_PRICE_CAP_TAX', 'OOS_2021_2026')]['ex_mean_250d_pct']}%"],
        ]},
        {"t": "h2", "text": "二、120 日红灯排雷稳赢 vs 250 日绿灯过剩陷阱"},
        {"t": "mark_p", "text": "120 日红灯排雷全样本年化 6.35% 跑赢 14 行业等权，近三年仍稳赢 +1.26pp，剔除任一行业全部正超额。"},
        {"t": "p", "text": f"被 120 日红灯踢出的篮子全样本年化仅 {w_full['Rule2_Red120d_ExcludedBasket']['ann_ret_pct']}%，年均跑输 14 行业等权 {w_full['Rule2_Red120d_ExcludedBasket']['excess_ann_vs_all14ew_pp']}pp。"},
        {"t": "p", "text": f"250 日绿灯补贴池在 2021 至 2026 年虽赢沪深 300 达 +{w_oos['Rule1_GreenSub250d_300FB']['excess_ann_vs_csi300_pp']}pp，但近三年反输 {w_3y['Rule1_GreenSub250d_300FB']['excess_ann_vs_csi300_pp']}pp。"},
        {"t": "p", "text": f"留一敏感性测试揭露，近三年若剔除半导体硬科技，绿灯超额立刻塌陷到 {c3l['DROP_SEMI_HARDTECH']['oos3y_green250_ex300_pp']}pp；若剔除新能源则升到 +{c3l['DROP_NEW_ENERGY']['oos3y_green250_ex300_pp']}pp。"},
        {"t": "p", "text": "结论很清楚：120 日红灯排雷无条件必用，250 日绿灯补贴必须主动过滤产能过剩行业。"},
        {"t": "table", "headers": ["策略组合", "全样本年化", "21至26年化", "21至26超300", "24至26超EW", "年换手率"], "rows": [
            ["沪深300基准", f"{w_full['CSI300_BH']['ann_ret_pct']}%", f"{w_oos['CSI300_BH']['ann_ret_pct']}%", "0.00pp", "+3.31pp", "5.5%"],
            ["14行业等权基准", f"{w_full['All_14_Sectors_EW']['ann_ret_pct']}%", f"{w_oos['All_14_Sectors_EW']['ann_ret_pct']}%", "+1.14pp", "0.00pp", "5.5%"],
            ["绿灯250日(300替补)", f"{w_full['Rule1_GreenSub250d_300FB']['ann_ret_pct']}%", f"{w_oos['Rule1_GreenSub250d_300FB']['ann_ret_pct']}%", f"+{w_oos['Rule1_GreenSub250d_300FB']['excess_ann_vs_csi300_pp']}pp", f"+{w_3y['Rule1_GreenSub250d_300FB']['excess_ann_vs_all14ew_pp']}pp", f"{w_full['Rule1_GreenSub250d_300FB']['annual_turnover_pct']}%"],
            ["绿灯250日(现金替补)", f"{w_full['Rule1_GreenSub250d_CashFB']['ann_ret_pct']}%", f"{w_oos['Rule1_GreenSub250d_CashFB']['ann_ret_pct']}%", f"+{w_oos['Rule1_GreenSub250d_CashFB']['excess_ann_vs_csi300_pp']}pp", f"+{w_3y['Rule1_GreenSub250d_CashFB']['excess_ann_vs_all14ew_pp']}pp", f"{w_full['Rule1_GreenSub250d_CashFB']['annual_turnover_pct']}%"],
            ["120日排红等权(核心)", f"{w_full['Rule2_AllSectors_ExclRed120d']['ann_ret_pct']}%", f"{w_oos['Rule2_AllSectors_ExclRed120d']['ann_ret_pct']}%", f"+{w_oos['Rule2_AllSectors_ExclRed120d']['excess_ann_vs_csi300_pp']}pp", f"+{w_3y['Rule2_AllSectors_ExclRed120d']['excess_ann_vs_all14ew_pp']}pp", f"{w_full['Rule2_AllSectors_ExclRed120d']['annual_turnover_pct']}%"],
            ["被排除红灯篮子", f"{w_full['Rule2_Red120d_ExcludedBasket']['ann_ret_pct']}%", f"{w_oos['Rule2_Red120d_ExcludedBasket']['ann_ret_pct']}%", f"{w_oos['Rule2_Red120d_ExcludedBasket']['excess_ann_vs_csi300_pp']}pp", f"+{w_3y['Rule2_Red120d_ExcludedBasket']['excess_ann_vs_all14ew_pp']}pp", f"{w_full['Rule2_Red120d_ExcludedBasket']['annual_turnover_pct']}%"],
        ]},
        {"t": "table", "headers": ["行业留一敏感性测试", "21至26绿灯超300", "21至26排红超EW", "24至26绿灯超300", "24至26排红超EW"], "rows": [
            ["基准全14行业", f"+{c3l['BASELINE_ALL14']['oos_green250_ex300_pp']}pp", f"+{c3l['BASELINE_ALL14']['oos_exclred120_exew_pp']}pp", f"{c3l['BASELINE_ALL14']['oos3y_green250_ex300_pp']}pp", f"+{c3l['BASELINE_ALL14']['oos3y_exclred120_exew_pp']}pp"],
            ["剔除半导体硬科技", f"+{c3l['DROP_SEMI_HARDTECH']['oos_green250_ex300_pp']}pp", f"+{c3l['DROP_SEMI_HARDTECH']['oos_exclred120_exew_pp']}pp", f"{c3l['DROP_SEMI_HARDTECH']['oos3y_green250_ex300_pp']}pp", f"+{c3l['DROP_SEMI_HARDTECH']['oos3y_exclred120_exew_pp']}pp"],
            ["剔除TMT人工智能", f"+{c3l['DROP_TMT_AI_MEDIA']['oos_green250_ex300_pp']}pp", f"+{c3l['DROP_TMT_AI_MEDIA']['oos_exclred120_exew_pp']}pp", f"{c3l['DROP_TMT_AI_MEDIA']['oos3y_green250_ex300_pp']}pp", f"+{c3l['DROP_TMT_AI_MEDIA']['oos3y_exclred120_exew_pp']}pp"],
            ["剔除新能源", f"+{c3l['DROP_NEW_ENERGY']['oos_green250_ex300_pp']}pp", f"+{c3l['DROP_NEW_ENERGY']['oos_exclred120_exew_pp']}pp", f"+{c3l['DROP_NEW_ENERGY']['oos3y_green250_ex300_pp']}pp", f"+{c3l['DROP_NEW_ENERGY']['oos3y_exclred120_exew_pp']}pp"],
            ["剔除教培互联网", f"+{c3l['DROP_EDU_INTERNET']['oos_green250_ex300_pp']}pp", f"+{c3l['DROP_EDU_INTERNET']['oos_exclred120_exew_pp']}pp", f"{c3l['DROP_EDU_INTERNET']['oos3y_green250_ex300_pp']}pp", f"+{c3l['DROP_EDU_INTERNET']['oos3y_exclred120_exew_pp']}pp"],
            ["剔除地产链", f"+{c3l['DROP_REAL_ESTATE']['oos_green250_ex300_pp']}pp", f"+{c3l['DROP_REAL_ESTATE']['oos_exclred120_exew_pp']}pp", f"{c3l['DROP_REAL_ESTATE']['oos3y_green250_ex300_pp']}pp", f"+{c3l['DROP_REAL_ESTATE']['oos3y_exclred120_exew_pp']}pp"],
        ]},
        {"t": "h2", "text": "三、截至 2026.11.25 活跃红绿灯行业清单"},
        {"t": "p", "text": f"当下全市场仅剩 {len(live['active_red_excluded_codes_120td'])} 个赛道处在 120 日红灯排雷期，其余 {len(live['active_green_sector_codes_250td'])} 大行业均带 250 日绿灯。"},
        {"t": "ul", "items": [
            "唯一 120 日红灯封锁赛道：微盘壳股，2026.11.11 证监会推进先赔征求意见并严打造假股，仍余 111 个交易日。",
            "120 日内新亮绿灯行业：券商（保证金降至 80%）、银行（1,500 亿注资特别国债）、半导体硬科技（增值税加计抵减）、TMT（具身智能专项）。",
            "250 日内延续绿灯行业：军工航天（商业航天司与低空保险）、可选消费（2026 以旧换新）、医药、新能源与央企红利。",
        ]},
        {"t": "table", "headers": ["日期", "灯色与赛道", "发文部委", "核心政策摘要", "剩余有效天数"], "rows": [
            ["2026.11.11", "红灯_微盘壳股", "中国证监会", "推进先赔意见从严打击造假股", "111交易日"],
            ["2026.11.22", "绿灯_券商", "证监会/交易所", "融资保证金100%降至80%且降费", "248交易日"],
            ["2026.11.18", "绿灯_银行", "财政部", "1500亿中央金融机构注资落地", "246交易日"],
            ["2026.09.29", "绿灯_半导体", "工信部等4部门", "2026集成电路增值税抵减清单", "215交易日"],
            ["2026.06.11", "绿灯_AI具身", "工信部/国资委", "人形机器人与具身智能实训专项", "139交易日"],
            ["2026.03.01", "绿灯_军工低空", "发改委/民航局", "联合发布推动低空保险实施意见", "69交易日"],
            ["2026.01.06", "绿灯_可选消费", "商务部等7部门", "2026年消费品以旧换新通知", "37交易日"],
        ]},
    ]
