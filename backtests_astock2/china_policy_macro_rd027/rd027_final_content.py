"""Part 1 of RD027 final report content: Title, Exec Verdict, Pillars, Wave 2A, Critic 1."""


def build_part1_blocks(d: dict) -> list[dict]:
    p1, p2, p3, p5 = d["p1"], d["p2"], d["p3"], d["p5"]
    w2, t1, c = d["w2"], d["t1"], d["c"]
    gs = w2["global_summary"]
    pt = w2["per_target_summary"]
    ch = w2["ch1_to_ch8_hypotheses"]
    c1w = c["critic1_tool1_ablation"]["windows"]
    lag = c["critic1_tool1_ablation"]["waterpool_pit_lag_sensitivity"]
    tb = p5["watershed_summary"]["TRUE_POLICY_BOTTOM"]
    ft = p5["watershed_summary"]["FALSE_BOTTOM_TRAP"]
    tp = p5["watershed_summary"]["POLICY_VALUATION_TOP"]
    fg = p5["four_gates_classifier_on_bottom_attempts"]

    b = [
        {"t": "h1", "text": "20261125 中国宏观政策水池全景与千因子系统性实证（RD027终版）"},
        {"t": "mark_p", "text": "中国政策只管真底四门，水池赔率与行业排雷，单靠水位打分择时其实跑输无信号纯风控。"},
        {"t": "p", "text": f"本终版汇总2005.01至2026.11共22年实证，经独立红队四路无情审计后输出最终定论。"},
        {"t": "p", "text": f"全样本{w2['n_factors']}个因子对照{w2['n_targets']}大目标共{w2['total_tests']}次检验，S级仅{gs['unique_factors_S_only']}个，S与A合计{gs['unique_factors_SA_hlz']}个占{gs['unique_factors_SA_pct']}%。"},
        {"t": "p", "text": f"红队ablation（消融）揭露工具1全样本Sharpe仅{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_CSI300']['sharpe']}，低于静态等均仓{c1w['FULL_2005_2026']['strategies']['Static_AvgW_CSI300']['sharpe']}及纯1/vol的{c1w['FULL_2005_2026']['strategies']['Pure_1overVol_MatchedW_CSI300']['sharpe']}。"},
        {"t": "p", "text": f"2026.11.24严格PIT（点时点）水位{t1['current_2026_11_24_pit_completed_month']['total_score']}分，11.25当月累计升至{t1['current_2026_11_25_with_nov_mtd']['total_score']}分，但微盘壳股仍在120日红灯期。"},
        {"t": "h2", "text": "一、红队总览与核心模块定性"},
        {"t": "p", "text": "经过等均仓消融，单点极值剔除与行业留一测试，五大研究模块仅部分通过实战准入。"},
        {
            "t": "table",
            "headers": ["模块", "表面结果", "红队暴露真相", "最终定性"],
            "rows": [
                ["25大拐点四门", f"{fg['true_positives']}+{fg['true_negatives']}全对100%", "真底与假底物理分野清晰", "PASS（可用）"],
                ["千因子双样本", f"S与A级{gs['unique_factors_SA_hlz']}个", "跌停占比系2015单次脉冲", "12过1条件1淘汰"],
                ["工具1水位择时", f"OOS（样本外）+2.99pp", "靠现金垫子且滞后1月归零", "CONDITIONAL"],
                ["工具2绿灯250日", "2021至2026赢5.45pp", "近3年依赖半导体输1.11pp", "OOS过近3年降级"],
                ["工具2红灯120日", "2021至2026赢1.20pp", "近3年仍赢1.26pp跨期最稳", "PASS（核心盾牌）"],
                ["工具3概率V2", "6条轨全样本赢V1", "24至26全胜唯轨2B微弱", "PASS（V2主力）"],
            ],
        },
        {"t": "h2", "text": "二、五大实证数据底数与真底四道物理门"},
        {"t": "p", "text": f"A股价格严格用本土全行情接口，剔除北向2024.08.16停更与社融2026.04断更。"},
        {"t": "p", "text": f"顶层会议{p2['n_meetings']}场中一阶超预期60日均值+{p2['diff_vs_static_comparison']['diff_ge1_60d_mean_pct'] if 'diff_ge1_60d_mean_pct' in p2['diff_vs_static_comparison'] else ch['CH4_顶层会议diff与F009']['event_p2_diff_ge1_mean_60d_pct']}%，高于静态高姿态+{ch['CH4_顶层会议diff与F009']['event_p2_static_ge4_mean_60d_pct']}%。"},
        {"t": "p", "text": "历史25个大拐点证明：只看口号与估值必然踩坑，真底必须跨过至少3道物理门。"},
        {"t": "ul", "items": [
            "门一止血阀：IPO发行或产业净减持实质收紧。",
            "门二真扩表：国家队真金白银买入或强降息降准。",
            "门三破格定调：顶层会议突破常规提法并直指市场。",
            "门四深度出清：200日均线上方个股低于20%或ERP极高。",
        ]},
        {
            "t": "table",
            "headers": ["拐点类型", "样本数", "T+20均值", "T+60均值", "T+120均值", "T+250均值"],
            "rows": [
                ["真政策底", f"{tb['n_cases']}次", f"+{tb['T+20_bench_mean_pct']}%", f"+{tb['T+60_bench_mean_pct']}%", f"+{tb['T+120_bench_mean_pct']}%", f"+{tb['T+250_bench_mean_pct']}%"],
                ["假底陷阱", f"{ft['n_cases']}次", f"{ft['T+20_bench_mean_pct']}%", f"{ft['T+60_bench_mean_pct']}%", f"{ft['T+120_bench_mean_pct']}%", f"{ft['T+250_bench_mean_pct']}%"],
                ["政策估值顶", f"{tp['n_cases']}次", f"{tp['T+20_bench_mean_pct']}%", f"{tp['T+60_bench_mean_pct']}%", f"{tp['T+120_bench_mean_pct']}%", f"{tp['T+250_bench_mean_pct']}%"],
                ["2024.09真底", "过3门", "+15.31%", "+17.04%", "+15.53%", "+35.64%"],
                ["2025.04真底", "过3门", "+7.08%", "+10.68%", "+26.46%", "+31.43%"],
                ["2023.07假底", "仅2门", "-3.55%", "-9.81%", "-16.49%", "-12.47%"],
            ],
        },
        {"t": "h2", "text": "三、千因子系统性检验与经典假设裁决"},
        {"t": "p", "text": "把1,099个因子按周频对齐未来8类目标，绝大多数短线指标都在样本外淘汰。"},
        {"t": "p", "text": "预测60日最大回撤最容易过关，科技相对沪深300的宏观因子仅幸存1个。"},
        {
            "t": "table",
            "headers": ["预测目标", "S级数量", "S与A合计", "幸存率", "代表有效方向"],
            "rows": [
                ["沪深300的60日回撤", f"{pt['tgt_csi300_fwd_60d_mdd']['S_tier_3era_hlz']}", f"{pt['tgt_csi300_fwd_60d_mdd']['robust_SA_total']}", f"{pt['tgt_csi300_fwd_60d_mdd']['robust_SA_pct']}%", "ERP与宏观痛阈"],
                ["沪深300的60日收益", f"{pt['tgt_csi300_fwd_60d']['S_tier_3era_hlz']}", f"{pt['tgt_csi300_fwd_60d']['robust_SA_total']}", f"{pt['tgt_csi300_fwd_60d']['robust_SA_pct']}%", "PPI变化与全A估值"],
                ["红利减创业板120日", f"{pt['tgt_div_minus_chinext_120d']['S_tier_3era_hlz']}", f"{pt['tgt_div_minus_chinext_120d']['robust_SA_total']}", f"{pt['tgt_div_minus_chinext_120d']['robust_SA_pct']}%", "美息与国内痛阈"],
                ["沪深300的250日收益", f"{pt['tgt_csi300_fwd_250d']['S_tier_3era_hlz']}", f"{pt['tgt_csi300_fwd_250d']['robust_SA_total']}", f"{pt['tgt_csi300_fwd_250d']['robust_SA_pct']}%", "产业减持与分红"],
                ["沪深300的120日收益", f"{pt['tgt_csi300_fwd_120d']['S_tier_3era_hlz']}", f"{pt['tgt_csi300_fwd_120d']['robust_SA_total']}", f"{pt['tgt_csi300_fwd_120d']['robust_SA_pct']}%", "美联储扩表与分红"],
                ["全A等权120日收益", f"{pt['tgt_ew_all_fwd_120d']['S_tier_3era_hlz']}", f"{pt['tgt_ew_all_fwd_120d']['robust_SA_total']}", f"{pt['tgt_ew_all_fwd_120d']['robust_SA_pct']}%", "分红与3M IPO家数"],
                ["微盘减300的120日", f"{pt['tgt_micro30_minus_300_120d']['S_tier_3era_hlz']}", f"{pt['tgt_micro30_minus_300_120d']['robust_SA_total']}", f"{pt['tgt_micro30_minus_300_120d']['robust_SA_pct']}%", "深跌乘两融变化"],
                ["科技减300的120日", f"{pt['tgt_tech_minus_300_120d']['S_tier_3era_hlz']}", f"{pt['tgt_tech_minus_300_120d']['robust_SA_total']}", f"{pt['tgt_tech_minus_300_120d']['robust_SA_pct']}%", "极缺宏观直接驱动"],
            ],
        },
        {"t": "h3", "text": "八大经典市场假设过堂裁决"},
        {"t": "p", "text": "逐项检验市场常见宏观与政策口诀后，只有三项全面成立，其余必须附带前置条件。"},
        {
            "t": "table",
            "headers": ["经典假设", "核心实证数字", "红队客观裁决"],
            "rows": [
                ["CH1口号无水阀", "47周均值-7.15%对比翻牌+7.17%", "没止血阀的喊话不要碰"],
                ["CH2 M1减M2", f"300全样本t={ch['CH2_M1M2与信贷脉冲2021断裂']['m1_m2_vs_csi300_120d']['t_hac']}不显著", "真正有效是社融脉冲t=+2.94"],
                ["CH3汇率破7压微盘", f"120日跑输300达{ch['CH3_中美利差与汇率非对称压制']['grp_usdcny_ge7_vs_micro_minus_300_120d']['diff_on_minus_off_pct']}pp", "破7重创微盘唯大盘偏韧性"],
                ["CH4会议一阶变化", "事件60日+5.56%胜静态+4.02%", "事件窗口有效但周频噪音大"],
                ["CH5 ERP短弱长强", "20日t=0.27升至250日3.68", "估值只做中长周期赔率参考"],
                ["CH6红灯深于绿灯", "红灯120日-4.06%绿灯250日+7.54%", "行政打压立竿见影持续久"],
                ["CH7抽血阀约束", f"12M抽血250日OOS（样本外）t={ch['CH7_抽血阀占市值比供给约束']['drain_equity_12m_vs_csi300_250d']['OOS']['t_hac']}", "仅2021后显著早年曾吸金同涨"],
                ["CH8国家队护盘", "120日+3.07%仅胜出+1.01pp", "更像下行防波堤而非暴涨催化"],
            ],
        },
        {"t": "h2", "text": "四、红队审讯一：水池择时还是现金垫子幻觉"},
        {"t": "mark_p", "text": "工具1全样本Sharpe为0.46，低于静态等均仓0.47，更跑输纯1/vol无信号基线0.55。"},
        {"t": "p", "text": f"工具1全样本平均股票仓位仅{c1w['FULL_2005_2026']['w_bar_pct']}%，其余{round(100-c1w['FULL_2005_2026']['w_bar_pct'],1)}%常年拿现金和国债。"},
        {"t": "p", "text": f"把同样{c1w['FULL_2005_2026']['w_bar_pct']}%仓位静态不动，年化就有{c1w['FULL_2005_2026']['strategies']['Static_AvgW_CSI300']['ann_ret_pct']}%，Sharpe还略高0.01，全自动加减仓基本没赢。"},
        {
            "t": "table",
            "headers": ["策略与基线", "全样本年化", "全样本Sharpe", "全样本MDD", "OOS（样本外）年化", "年换手率"],
            "rows": [
                ["沪深300基准持有", f"{c1w['FULL_2005_2026']['strategies']['CSI300_BH']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['CSI300_BH']['sharpe']}", f"{c1w['FULL_2005_2026']['strategies']['CSI300_BH']['mdd_pct']}%", f"{c1w['OOS_2021_2026']['strategies']['CSI300_BH']['ann_ret_pct']}%", "0.0%"],
                ["工具1动态300", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_CSI300']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_CSI300']['sharpe']}", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_CSI300']['mdd_pct']}%", f"{c1w['OOS_2021_2026']['strategies']['Waterpool_Dyn_CSI300']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_CSI300']['annual_turnover_pct']}%"],
                ["静态等均仓300", f"{c1w['FULL_2005_2026']['strategies']['Static_AvgW_CSI300']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Static_AvgW_CSI300']['sharpe']}", f"{c1w['FULL_2005_2026']['strategies']['Static_AvgW_CSI300']['mdd_pct']}%", f"{c1w['OOS_2021_2026']['strategies']['Static_AvgW_CSI300']['ann_ret_pct']}%", "0.0%"],
                ["纯1/vol同均仓", f"{c1w['FULL_2005_2026']['strategies']['Pure_1overVol_MatchedW_CSI300']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Pure_1overVol_MatchedW_CSI300']['sharpe']}", f"{c1w['FULL_2005_2026']['strategies']['Pure_1overVol_MatchedW_CSI300']['mdd_pct']}%", f"{c1w['OOS_2021_2026']['strategies']['Pure_1overVol_MatchedW_CSI300']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Pure_1overVol_MatchedW_CSI300']['annual_turnover_pct']}%"],
                ["动态水池风格版", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_Style']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_Style']['sharpe']}", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_Style']['mdd_pct']}%", f"{c1w['OOS_2021_2026']['strategies']['Waterpool_Dyn_Style']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Waterpool_Dyn_Style']['annual_turnover_pct']}%"],
                ["静态同均仓风格版", f"{c1w['FULL_2005_2026']['strategies']['Static_AvgW_StyleMix']['ann_ret_pct']}%", f"{c1w['FULL_2005_2026']['strategies']['Static_AvgW_StyleMix']['sharpe']}", f"{c1w['FULL_2005_2026']['strategies']['Static_AvgW_StyleMix']['mdd_pct']}%", f"{c1w['OOS_2021_2026']['strategies']['Static_AvgW_StyleMix']['ann_ret_pct']}%", "0.0%"],
            ],
        },
        {"t": "p", "text": f"2021至2026单边下跌期工具1靠高分赢1.62pp，可近3年又跑输同均仓1/vol达1.20pp，风格版更以869.6%换手跑输静态0.25pp。"},
        {"t": "p", "text": f"更痛的是分数漂移与滞后敏感：70分以上占比从IS（样本内）11.9%飙到近3年81.1%，严格滞后1整月后OOS（样本外）超额从+{lag['orig_td1']['OOS_Dyn300']['excess_ann_vs_csi300_pp']}pp跌到+{lag['full_1m']['OOS_Dyn300']['excess_ann_vs_csi300_pp']}pp。"},
    ]
    return b
