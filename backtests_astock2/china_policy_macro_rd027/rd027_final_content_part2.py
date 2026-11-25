"""Part 2 of RD027 final report content: Critic 2, Critic 3, Critic 4, Live & Buwen Playbook."""


def build_part2_blocks(d: dict) -> list[dict]:
    c, t1, t2, lb = d["c"], d["t1"], d["t2"], d["lb"]
    c2e = c["critic2_extreme_and_pit"]["extreme_leverage_test"]
    c2p = c["critic2_extreme_and_pit"]["pit_alignment_audit"]
    c2l = c["critic2_extreme_and_pit"]["strict_1_full_month_lag_recompute"]
    c3l = {x["case"]: x for x in c["critic3_tool2_and_tool3"]["tool2_leave_one_sector_out"]}
    c3t3 = {x["contract"]: x for x in c["critic3_tool2_and_tool3"]["tool3_2024_2026_v1_vs_v2"]}
    c4 = c["critic4_us_vs_china_paradigm"]
    us, cn = c4["us_pick_verified_facts"], c4["china_rd027_verified_facts"]
    ans = c4["buwen_ultimate_answer"]

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
        st = "PASS" if x["status"] == "PASS" else ("有条件" if "COND" in x["status"] else "FAIL淘汰")
        ext_rows.append([
            name_map[(x["factor"], x["target"])],
            f"{x['t_full']:+.2f}",
            f"{x['t_drop_2015']:+.2f}",
            f"{x['t_drop_all3_extreme']:+.2f}",
            st,
        ])

    t2o, t23 = t2["backtest_windows"]["OOS_2021_2026"], t2["backtest_windows"]["OOS_3Y_2024_2026"]
    t3_names = {
        "Track1_Y_30d": "轨1(30日落地)", "Track1_Y_60d": "轨1(60日落地)",
        "Track1_Y_90d": "轨1(90日落地)", "Track2B_V3ge60_20td": "轨2B(国家队V3)",
        "Track4A_Politburo_Econ43": "轨4A(政治局经济)", "Track4B_PostConf_30d": "轨4B(会后30日)",
    }
    t3_rows = []
    for k, label in t3_names.items():
        r = c3t3[k]
        auc_s = f"{r['v2_auc']:.3f}" if r["v2_auc"] is not None else "样本单类空值"
        t3_rows.append([label, f"{r['n_24_26']}", f"{r['v1_bss']:+.4f}", f"{r['v2_bss']:+.4f}", f"{r['delta_oos_bss'] if 'delta_oos_bss' in r else r['delta_bss']:+.4f}", auc_s])

    pm_labels = {
        "PM-01": "创业板做市细则落地",
        "PM-02": "量化或减持优化细则",
        "PM-03": "12月政治局提股市",
        "PM-04": "经工后30日配套落地",
        "PM-05": "20日内逆周期稳市",
        "PM-06": "20日内国家队V3破60",
        "PM-07": "10日内监控或停牌",
        "PM-08": "经工定调升级产业簇",
    }
    pm_rows = [
        [x["contract_id"].replace("-", ""), pm_labels.get(x["contract_id"], x["question"][:16]), f"{x['v1_prob_pct']}%", f"{x['model_prob_pct']}%", f"{x['track_oos_bss']:+.3f}"]
        for x in lb["live_contracts"]
    ]

    b = [
        {"t": "h2", "text": "五、红队审讯二：反单点极值与 PIT（点时点）滞后复核"},
        {"t": "mark_p", "text": "14对核心因子里12对经受住三段极值全剔考验，原排头兵跌停占比剔除2015年即塌陷淘汰。"},
        {"t": "p", "text": "Wave 2A周表139列水池指标均在月末后10个自然日以上生效，泄露为0，严格滞后1整月后6对核心水池因子t值仍全部大于3.31。"},
        {"t": "p", "text": f"反面隐患在于工具1与工具3日频表月初1至9日共{c2p['tool1_and_tool3_wp_early_month_days_1_to_9_count']}行用了上月水池早熟数值，上线前必须锁死10日后生效。"},
        {"t": "table", "headers": ["核心因子(目标)", "全样本t", "剔2015t", "三段全剔t", "红队判定"], "rows": ext_rows},
        {"t": "h2", "text": "六、红队审讯三：行业红绿灯与概率预测现代验证"},
        {"t": "p", "text": f"工具2绿灯250日策略在2021至2026赢沪深300达+{t2o['Rule1_GreenSub250d_300FB']['excess_ann_vs_csi300_pp']}pp，剔除任一行业仍保留+3.38至+6.87pp正超额。"},
        {"t": "p", "text": f"但近3年绿灯250日输基准{t23['Rule1_GreenSub250d_300FB']['excess_ann_vs_csi300_pp']}pp，一旦去掉半导体更跌至{c3l['DROP_SEMI_HARDTECH']['oos3y_green250_ex300_pp']}pp，唯独120日红灯排雷跨期稳赢+{c3l['BASELINE_ALL14']['oos3y_exclred120_exew_pp']}pp。"},
        {"t": "table", "headers": ["行业留一情形", "21至26绿灯超300", "21至26排红超EW", "24至26绿灯超300", "24至26排红超EW"], "rows": [
            ["基准全14行业", f"+{c3l['BASELINE_ALL14']['oos_green250_ex300_pp']}pp", f"+{c3l['BASELINE_ALL14']['oos_exclred120_exew_pp']}pp", f"{c3l['BASELINE_ALL14']['oos3y_green250_ex300_pp']}pp", f"+{c3l['BASELINE_ALL14']['oos3y_exclred120_exew_pp']}pp"],
            ["剔除半导体硬科技", f"+{c3l['DROP_SEMI_HARDTECH']['oos_green250_ex300_pp']}pp", f"+{c3l['DROP_SEMI_HARDTECH']['oos_exclred120_exew_pp']}pp", f"{c3l['DROP_SEMI_HARDTECH']['oos3y_green250_ex300_pp']}pp", f"+{c3l['DROP_SEMI_HARDTECH']['oos3y_exclred120_exew_pp']}pp"],
            ["剔除TMT人工智能", f"+{c3l['DROP_TMT_AI_MEDIA']['oos_green250_ex300_pp']}pp", f"+{c3l['DROP_TMT_AI_MEDIA']['oos_exclred120_exew_pp']}pp", f"{c3l['DROP_TMT_AI_MEDIA']['oos3y_green250_ex300_pp']}pp", f"+{c3l['DROP_TMT_AI_MEDIA']['oos3y_exclred120_exew_pp']}pp"],
            ["剔除新能源", f"+{c3l['DROP_NEW_ENERGY']['oos_green250_ex300_pp']}pp", f"+{c3l['DROP_NEW_ENERGY']['oos_exclred120_exew_pp']}pp", f"+{c3l['DROP_NEW_ENERGY']['oos3y_green250_ex300_pp']}pp", f"+{c3l['DROP_NEW_ENERGY']['oos3y_exclred120_exew_pp']}pp"],
            ["剔除教培互联网", f"+{c3l['DROP_EDU_INTERNET']['oos_green250_ex300_pp']}pp", f"+{c3l['DROP_EDU_INTERNET']['oos_exclred120_exew_pp']}pp", f"{c3l['DROP_EDU_INTERNET']['oos3y_green250_ex300_pp']}pp", f"+{c3l['DROP_EDU_INTERNET']['oos3y_exclred120_exew_pp']}pp"],
            ["剔除地产链", f"+{c3l['DROP_REAL_ESTATE']['oos_green250_ex300_pp']}pp", f"+{c3l['DROP_REAL_ESTATE']['oos_exclred120_exew_pp']}pp", f"{c3l['DROP_REAL_ESTATE']['oos3y_green250_ex300_pp']}pp", f"+{c3l['DROP_REAL_ESTATE']['oos3y_exclred120_exew_pp']}pp"],
        ]},
        {"t": "p", "text": "工具3概率预测V2升级的6条轨在2024至2026全部赢过V1，轨2B因2026年Brier达0.2781仍须严密观察。"},
        {"t": "table", "headers": ["V2升级轨", "24至26样本", "V1 BSS", "V2 BSS", "净提升", "24至26 AUC"], "rows": t3_rows},
        {"t": "h3", "text": "2026.11.25实时八大合约盘口概率"},
        {"t": "p", "text": "实时盘口用各轨样本外胜出版本出价，其中PM01至PM04及PM06用V2，其余沿用V1。"},
        {"t": "table", "headers": ["合约", "实时跟踪问题", "V1概率", "V2概率", "轨OOS（样本外）BSS"], "rows": pm_rows},
        {"t": "h2", "text": "七、红队审讯四：中美宏观对比与实操终极答案"},
        {"t": "p", "text": f"美方55年{us['factors_tested']}个因子在SPX 12M幸存1.38%，且混合择时Sharpe 0.70主要靠纯1/vol（无信号即0.65）。"},
        {"t": "p", "text": "两国教训完全同源：政策与估值都不是高频择时印钞机，只能定赔率，控回撤与避雷区。"},
        {"t": "table", "headers": ["对比维度", "美方55年实证(2531因子)", "中方22年实证(1099因子)"], "rows": [
            ["权益正收益幸存率", "SPX 12M为1.38% 60M为1.86%", "沪深300 60d为2.91% 250d为1.36%"],
            ["最易预测目标", "CPI 24M达16.79% 利率7.63%", "60日回撤5.82%与红利创2.73%"],
            ["主导有效周期", "3至5年估值需10年才见效", "60至250日(3至12个月)最强"],
            ["ablation（消融）痛点", "混合择时Sharpe 0.70输给1/vol理念", "水位Sharpe 0.46低于纯1/vol的0.55"],
            ["核心机制差别", "利率通胀估值与美元流动性", "四门物理底水池供需与红绿灯"],
        ]},
        {"t": "h3", "text": "中国政策到底怎么用：三条实操规则与三条弃用伪做法"},
        {"t": "mark_p", "text": ans["core_insight"].replace("-", "减").replace("(", "（").replace(")", "）")},
        {"t": "ul", "items": [
            "实操一：先验四道物理门过3门再定大底，单凭喊话与常规会议一律当噪声。",
            "实操二：用12M分红，IPO家数，净减持与PPI/美水池定3至12个月赔率，底层配纯1/vol做仓位护栏。",
            "实操三：借轨1与轨4B盯落地进度，对部委红灯行业（120日均跑输4.06%）做硬排除。",
            "弃用一：听单一发言或静态政治局定调做20日短线追涨。",
            "弃用二：把M1减M2剪刀差或全市场跌停占比当万能信号（跌停剔2015即失效）。",
            "弃用三：拿政策水位打分做高换手全自动择时机器（869.6%换手样本外反输）。",
        ]},
        {"t": "h3", "text": "当前2026.11.24至25实时读数（仅供赔率参考）"},
        {"t": "p", "text": f"沪深300报{t1['current_2026_11_24_pit_completed_month']['raw_diagnostics']['csi300_close']}，60日回撤{lb['market_snapshot_wave1'].get('bench_dd_60d_pct', -14.39)}%，200日均线上方{t1['current_2026_11_24_pit_completed_month']['raw_diagnostics']['pct_above_ma200_pct']}%，ERP为{t1['current_2026_11_24_pit_completed_month']['raw_diagnostics']['erp_csi300_pct']}%，V3峰值{t1['current_2026_11_24_pit_completed_month']['raw_diagnostics']['v3_max_10d']}。"},
        {"t": "p", "text": f"结构仅微盘壳股({len(t2['live_2026_11_25_traffic_lights']['active_red_excluded_codes_120td'])}个赛道)因从严打击造假处于120日红灯排除期，其余{len(t2['live_2026_11_25_traffic_lights']['active_green_sector_codes_250td'])}大行业均带250日绿灯标签。"},
    ]
    return b
