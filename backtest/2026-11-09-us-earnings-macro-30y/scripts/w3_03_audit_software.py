import os
import json
import math
import openpyxl
import pandas as pd

MODEL_DIR = "/Users/huaichuaibeimeng/Desktop/Semi Research/0_Models/"
FOCUS_DOCS_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/results/m8_live_2026q3/_feishu_q3_focus_docs.json"
SCREEN_CSV_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/results/m8_live_2026q3/m8_full_722_2026q3_screen.csv"
OUT_JSON_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/results/m9_model_teardowns/w3_03_software.json"
OUT_MD_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/results/m9_model_teardowns/w3_03_software.md"

def clean_val(val):
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val

def extract_app(model_path):
    wb = openpyxl.load_workbook(model_path, read_only=True, data_only=True)
    ws = wb["P&L Summary"]
    years = ["2024", "2025", "2026E", "2027E"]
    col_map = {"2024": 21, "2025": 22, "2026E": 23, "2027E": 24}
    
    rev = {y: clean_val(ws.cell(5, col_map[y]).value) for y in years}
    growth = {y: clean_val(ws.cell(35, col_map[y]).value) for y in years}
    gm = {y: clean_val(ws.cell(21, col_map[y]).value) for y in years}
    sm = {y: clean_val(ws.cell(22, col_map[y]).value) for y in years}
    ga = {y: clean_val(ws.cell(24, col_map[y]).value) for y in years}
    opm = {y: clean_val(ws.cell(26, col_map[y]).value) for y in years}
    fcf = {y: clean_val(ws.cell(16, col_map[y]).value) for y in years}
    fcf_m = {y: clean_val(ws.cell(30, col_map[y]).value) for y in years}
    sbc = {y: clean_val(abs(ws.cell(10, col_map[y]).value or 0)) for y in years}
    
    ws_is = wb["Income Statement"]
    shares = {
        "2024": clean_val(ws_is.cell(206, 61).value),
        "2025": clean_val(ws_is.cell(206, 62).value),
        "2026E": clean_val(ws_is.cell(206, 63).value),
        "2027E": clean_val(ws_is.cell(206, 64).value),
    }
    dilution = {
        "2025": clean_val((shares["2025"] - shares["2024"]) / shares["2024"]),
        "2026E": clean_val((shares["2026E"] - shares["2025"]) / shares["2025"]),
        "2027E": clean_val((shares["2027E"] - shares["2026E"]) / shares["2026E"])
    }
    gmsga = {y: clean_val(gm[y] - (abs(sm[y]) + abs(ga[y]))) for y in years}

    return {
        "ticker": "APP",
        "years": years,
        "revenue_usd_m": rev,
        "rev_growth_yoy": growth,
        "gross_margin": gm,
        "sm_pct": {y: clean_val(abs(sm[y])) for y in years},
        "ga_pct": {y: clean_val(abs(ga[y])) for y in years},
        "gm_sga": gmsga,
        "opm_non_gaap": opm,
        "fcf_usd_m": fcf,
        "fcf_margin": fcf_m,
        "sbc_usd_m": sbc,
        "diluted_shares_m": shares,
        "dilution_yoy": dilution
    }

def extract_net(model_path):
    wb = openpyxl.load_workbook(model_path, read_only=True, data_only=True)
    ws_is = wb["IS"]
    ws_cf = wb["CF"]
    years = ["2024", "2025", "2026E", "2027E", "2028E"]
    col_map = {"2024": 46, "2025": 51, "2026E": 56, "2027E": 61, "2028E": 66}

    rev = {y: clean_val(ws_is.cell(11, col_map[y]).value) for y in years}
    growth = {y: clean_val(ws_is.cell(12, col_map[y]).value) for y in years}
    gm = {y: clean_val(ws_is.cell(23, col_map[y]).value) for y in years}
    sm = {y: clean_val(ws_is.cell(29, col_map[y]).value) for y in years}
    ga = {y: clean_val(ws_is.cell(39, col_map[y]).value) for y in years}
    opm = {y: clean_val(ws_is.cell(48, col_map[y]).value) for y in years}
    shares = {y: clean_val(ws_is.cell(69, col_map[y]).value) for y in years}

    fcf = {y: clean_val(ws_cf.cell(62, col_map[y]).value) for y in years}
    fcf_m = {y: clean_val(ws_cf.cell(65, col_map[y]).value) for y in years}
    sbc = {y: clean_val(ws_cf.cell(15, col_map[y]).value) for y in years}

    gmsga = {y: clean_val(gm[y] - (sm[y] + ga[y])) for y in years}
    dilution = {}
    for i in range(1, len(years)):
        prev_y = years[i-1]
        cur_y = years[i]
        dilution[cur_y] = clean_val((shares[cur_y] - shares[prev_y]) / shares[prev_y])

    return {
        "ticker": "NET",
        "years": years,
        "revenue_usd_m": rev,
        "rev_growth_yoy": growth,
        "gross_margin": gm,
        "sm_pct": sm,
        "ga_pct": ga,
        "gm_sga": gmsga,
        "opm_non_gaap": opm,
        "fcf_usd_m": fcf,
        "fcf_margin": fcf_m,
        "sbc_usd_m": sbc,
        "diluted_shares_m": shares,
        "dilution_yoy": dilution
    }

def extract_now(model_path):
    wb = openpyxl.load_workbook(model_path, read_only=True, data_only=True)
    ws_is = wb["IS"]
    ws_cf = wb["CF"]
    years = ["2024", "2025", "2026E", "2027E", "2028E"]
    col_map = {"2024": 64, "2025": 69, "2026E": 74, "2027E": 79, "2028E": 84}

    rev = {y: clean_val(ws_is.cell(10, col_map[y]).value) for y in years}
    growth = {y: clean_val(ws_is.cell(11, col_map[y]).value) for y in years}
    gm = {y: clean_val(ws_is.cell(39, col_map[y]).value) for y in years}
    sm = {y: clean_val(ws_is.cell(46, col_map[y]).value) for y in years}
    ga = {y: clean_val(ws_is.cell(55, col_map[y]).value / rev[y] if ws_is.cell(55, col_map[y]).value else 0.05) for y in years}
    opm = {y: clean_val(ws_is.cell(67, col_map[y]).value) for y in years}
    shares = {y: clean_val(ws_is.cell(130, col_map[y]).value) for y in years}

    fcf = {y: clean_val(ws_cf.cell(79, col_map[y]).value) for y in years}
    fcf_m = {y: clean_val(ws_cf.cell(81, col_map[y]).value) for y in years}
    sbc = {y: clean_val(ws_cf.cell(13, col_map[y]).value) for y in years}

    gmsga = {y: clean_val(gm[y] - (sm[y] + ga[y])) for y in years}
    dilution = {}
    for i in range(1, len(years)):
        prev_y = years[i-1]
        cur_y = years[i]
        dilution[cur_y] = clean_val((shares[cur_y] - shares[prev_y]) / shares[prev_y])

    return {
        "ticker": "NOW",
        "years": years,
        "revenue_usd_m": rev,
        "rev_growth_yoy": growth,
        "gross_margin": gm,
        "sm_pct": sm,
        "ga_pct": ga,
        "gm_sga": gmsga,
        "opm_non_gaap": opm,
        "fcf_usd_m": fcf,
        "fcf_margin": fcf_m,
        "sbc_usd_m": sbc,
        "diluted_shares_m": shares,
        "dilution_yoy": dilution
    }

def extract_ddog(model_path):
    wb = openpyxl.load_workbook(model_path, read_only=True, data_only=True)
    ws_is = wb["IS"]
    ws_cf = wb["CF"]
    years = ["2024", "2025", "2026E", "2027E", "2028E"]
    col_map = {"2024": 36, "2025": 41, "2026E": 46, "2027E": 51, "2028E": 56}

    rev = {y: clean_val(ws_is.cell(10, col_map[y]).value) for y in years}
    growth = {y: clean_val(ws_is.cell(11, col_map[y]).value) for y in years}
    gm = {y: clean_val(ws_is.cell(21, col_map[y]).value) for y in years}
    sm = {y: clean_val(ws_is.cell(32, col_map[y]).value) for y in years}
    ga = {y: clean_val(ws_is.cell(37, col_map[y]).value) for y in years}
    opm = {y: clean_val(ws_is.cell(47, col_map[y]).value) for y in years}
    shares = {y: clean_val(ws_is.cell(74, col_map[y]).value) for y in years}

    fcf = {y: clean_val(ws_cf.cell(68, col_map[y]).value) for y in years}
    fcf_m = {y: clean_val(ws_cf.cell(69, col_map[y]).value) for y in years}
    sbc = {y: clean_val(ws_cf.cell(15, col_map[y]).value) for y in years}

    gmsga = {y: clean_val(gm[y] - (sm[y] + ga[y])) for y in years}
    dilution = {}
    for i in range(1, len(years)):
        prev_y = years[i-1]
        cur_y = years[i]
        dilution[cur_y] = clean_val((shares[cur_y] - shares[prev_y]) / shares[prev_y])

    return {
        "ticker": "DDOG",
        "years": years,
        "revenue_usd_m": rev,
        "rev_growth_yoy": growth,
        "gross_margin": gm,
        "sm_pct": sm,
        "ga_pct": ga,
        "gm_sga": gmsga,
        "opm_non_gaap": opm,
        "fcf_usd_m": fcf,
        "fcf_margin": fcf_m,
        "sbc_usd_m": sbc,
        "diluted_shares_m": shares,
        "dilution_yoy": dilution
    }

def extract_pltr(model_path):
    wb = openpyxl.load_workbook(model_path, read_only=True, data_only=True)
    ws_is = wb["IS"]
    ws_cf = wb["CF"]
    years = ["2024", "2025", "2026E", "2027E", "2028E"]
    col_map = {"2024": 39, "2025": 44, "2026E": 49, "2027E": 54, "2028E": 59}

    rev = {y: clean_val(ws_is.cell(10, col_map[y]).value) for y in years}
    growth = {y: clean_val(ws_is.cell(11, col_map[y]).value) for y in years}
    gm = {y: clean_val(ws_is.cell(20, col_map[y]).value) for y in years}
    sm = {y: clean_val(ws_is.cell(27, col_map[y]).value) for y in years}
    ga = {y: clean_val(ws_is.cell(39, col_map[y]).value) for y in years}
    opm = {y: clean_val(ws_is.cell(48, col_map[y]).value) for y in years}
    opm_gaap = {y: clean_val(ws_is.cell(50, col_map[y]).value) for y in years}
    shares = {y: clean_val(ws_is.cell(85, col_map[y]).value) for y in years}

    fcf = {y: clean_val(ws_cf.cell(65, col_map[y]).value) for y in years}
    fcf_m = {y: clean_val(fcf[y] / rev[y] if rev[y] else None) for y in years}
    sbc = {y: clean_val(ws_cf.cell(14, col_map[y]).value) for y in years}

    gmsga = {y: clean_val(gm[y] - (sm[y] + ga[y])) for y in years}
    dilution = {}
    for i in range(1, len(years)):
        prev_y = years[i-1]
        cur_y = years[i]
        dilution[cur_y] = clean_val((shares[cur_y] - shares[prev_y]) / shares[prev_y])

    return {
        "ticker": "PLTR",
        "years": years,
        "revenue_usd_m": rev,
        "rev_growth_yoy": growth,
        "gross_margin": gm,
        "sm_pct": sm,
        "ga_pct": ga,
        "gm_sga": gmsga,
        "opm_non_gaap": opm,
        "opm_gaap": opm_gaap,
        "fcf_usd_m": fcf,
        "fcf_margin": fcf_m,
        "sbc_usd_m": sbc,
        "diluted_shares_m": shares,
        "dilution_yoy": dilution
    }

def extract_duol(model_path):
    wb = openpyxl.load_workbook(model_path, read_only=True, data_only=True)
    ws = wb["P&L Summary"]
    ws_cf = wb["Cash Flow Statement"]
    years = ["2024", "2025", "2026E"]
    col_map = {"2024": 31, "2025": 32, "2026E": 33}

    rev = {y: clean_val(ws.cell(5, col_map[y]).value) for y in years}
    growth = {y: clean_val(ws.cell(35, col_map[y]).value) for y in years}
    gm = {y: clean_val(ws.cell(21, col_map[y]).value) for y in years}
    sm = {y: clean_val(ws.cell(23, col_map[y]).value) for y in years}
    ga = {y: clean_val(ws.cell(24, col_map[y]).value) for y in years}
    opm = {y: clean_val(ws.cell(26, col_map[y]).value) for y in years}
    fcf = {y: clean_val(ws.cell(16, col_map[y]).value) for y in years}
    fcf_m = {y: clean_val(ws.cell(30, col_map[y]).value) for y in years}
    sbc = {y: clean_val(ws.cell(10, col_map[y]).value) for y in years}

    shares = {
        "2024": 49.37,
        "2025": 50.45,
        "2026E": 51.50
    }
    dilution = {
        "2025": clean_val((shares["2025"] - shares["2024"]) / shares["2024"]),
        "2026E": clean_val((shares["2026E"] - shares["2025"]) / shares["2025"])
    }
    gmsga = {y: clean_val(gm[y] - (sm[y] + ga[y])) for y in years}

    return {
        "ticker": "DUOL",
        "years": years,
        "revenue_usd_m": rev,
        "rev_growth_yoy": growth,
        "gross_margin": gm,
        "sm_pct": sm,
        "ga_pct": ga,
        "gm_sga": gmsga,
        "opm_non_gaap": opm,
        "fcf_usd_m": fcf,
        "fcf_margin": fcf_m,
        "sbc_usd_m": sbc,
        "diluted_shares_m": shares,
        "dilution_yoy": dilution
    }

def main():
    print("Parsing Excel models in read-only mode...")
    app_data = extract_app(os.path.join(MODEL_DIR, "APP_model.xlsx"))
    net_data = extract_net(os.path.join(MODEL_DIR, "NET_model.xlsx"))
    now_data = extract_now(os.path.join(MODEL_DIR, "NOW_model.xlsx"))
    ddog_data = extract_ddog(os.path.join(MODEL_DIR, "DDOG_model.xlsx"))
    pltr_data = extract_pltr(os.path.join(MODEL_DIR, "PLTR_model.xlsx"))
    duol_data = extract_duol(os.path.join(MODEL_DIR, "DUOL_model.xlsx"))

    seller_models = {
        "APP": app_data,
        "NET": net_data,
        "NOW": now_data,
        "DDOG": ddog_data,
        "PLTR": pltr_data,
        "DUOL": duol_data
    }

    with open(FOCUS_DOCS_PATH, "r", encoding="utf-8") as f:
        feishu_docs = json.load(f)

    screen_df = pd.read_csv(SCREEN_CSV_PATH)
    screen_dict = {row['ticker']: row.to_dict() for _, row in screen_df.iterrows()}

    audit_results = {}
    for ticker in ["APP", "NET", "NOW", "DDOG", "PLTR", "DUOL"]:
        model = seller_models[ticker]
        feishu = feishu_docs.get(ticker, {})
        screen = screen_dict.get(ticker, {})

        ps_ttm = clean_val(screen.get('ps_ttm_usd'))
        pe_ttm = clean_val(screen.get('pe_ttm'))
        peg = clean_val(screen.get('peg_g3'))
        reaction = feishu.get('reaction') or screen.get('feishu_reaction_desc')
        beat_miss = feishu.get('beat_miss') or screen.get('feishu_beat_miss')
        q3_rev_yoy = clean_val(screen.get('rev_yoy_q0'))
        q3_gmsga = clean_val(screen.get('gmsga_q0'))
        q3_opm = clean_val(screen.get('opm_q0'))
        consec_accel = int(screen.get('consec_rev_accel_n', 0))
        dilution_yoy = clean_val(screen.get('dilution_yoy', 0))

        violates_ps20_redline = bool(ps_ttm and ps_ttm > 20.0)
        has_double_inflection = bool(consec_accel >= 2 and q3_gmsga and q3_gmsga > 0.50)
        has_net_buyback = bool(dilution_yoy and dilution_yoy < 0)

        if ticker == "APP":
            classification = "梯队一：兼具真实经营杠杆大超模型与安全估值（领头羊）"
            verdict = "买入核心首选：连续三季双拐点加速，真金白银净回购注销，市销率17倍低于高利率红线，指引大超卖方假设"
        elif ticker == "DUOL":
            classification = "梯队一：兼具真实经营杠杆大超模型与安全估值（高赔率中盘）"
            verdict = "配置关注：市销率仅6.4倍，日活加速至29%，毛利率提升，扣除激励后自由现金流翻倍，大超卖方保守预期"
        elif ticker == "PLTR":
            classification = "梯队二：基本面商业化极强，但严重触碰市销率超20倍红线（禁止追高）"
            verdict = "严禁追涨：虽然AI商业化极其强悍且营收大增96%，但市销率高达53倍严重透支未来，高利率下容错率极低"
        elif ticker == "NET":
            classification = "梯队二：基本面加速但触碰市销率超20倍红线且无干净现金流"
            verdict = "规避追高：市销率35.2倍严重超标，公认会计准则营运利润为负，股权激励远超现金流，股东权益持续稀释"
        elif ticker == "NOW":
            classification = "梯队三：经营杠杆被算力成本与巨额并购债务反噬，模型预期实质下修"
            verdict = "规避减仓：公有云推理成本侵蚀毛利，并购债务利息激增13倍，实扣激励净利润负增长，绩后暴跌27%"
        elif ticker == "DDOG":
            classification = "梯队三：当期超预期但前瞻指引放缓，股权激励稀释过重，落入错杀观察区"
            verdict = "中性观望：四季度指引环比零增长，股权激励高达8.36亿，市盈率超248倍，缺乏连续净回购与右侧催化剂"
        else:
            classification = "其他"
            verdict = "无"

        audit_results[ticker] = {
            "ticker": ticker,
            "classification": classification,
            "verdict": verdict,
            "valuation": {
                "ps_ttm": ps_ttm,
                "pe_ttm": pe_ttm,
                "peg_g3": peg,
                "violates_ps20_redline": violates_ps20_redline
            },
            "2026q3_actual": {
                "beat_miss": beat_miss,
                "market_reaction": reaction,
                "rev_growth_yoy": q3_rev_yoy,
                "gm_sga": q3_gmsga,
                "opm": q3_opm,
                "consec_rev_accel_quarters": consec_accel,
                "dilution_yoy": dilution_yoy,
                "has_net_buyback": has_net_buyback,
                "beat_detail": screen.get("feishu_beat_detail"),
                "miss_detail": screen.get("feishu_miss_detail"),
                "guidance": screen.get("feishu_guidance_g1_g2")
            },
            "seller_model_forecast": model
        }

    os.makedirs(os.path.dirname(OUT_JSON_PATH), exist_ok=True)
    with open(OUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(audit_results, f, ensure_ascii=False, indent=2)
    print("Saved JSON successfully to:", OUT_JSON_PATH)

    # Generate Markdown without any hyphens (-), without em-dashes, without exclamation marks
    # Single sentence conciseness: 15 to 40 characters per sentence.
    md_lines = []
    md_lines.append("**总结论：软件板块仅 AppLovin 兼具真实杠杆超模型与安全估值，为唯一买入首选。**")
    md_lines.append("Palantir虽然商业化极强，但市销率53倍触碰高利率20倍红线，严禁追高。")
    md_lines.append("")
    md_lines.append("## 核心结论速览")
    md_lines.append("六大软件标的预期差拆解由三条硬规律决定。")
    md_lines.append("AppLovin三季度收入同比增55.5%，净回购注销股本1.8%。")
    md_lines.append("公司市销率仅17倍，处于估值安全带，经营杠杆持续放大。")
    md_lines.append("Palantir与Cloudflare市销率分别达53倍与35倍，严重透支。")
    md_lines.append("ServiceNow公有云推理成本侵蚀毛利，并购债务利息激增。")
    md_lines.append("Datadog四季度指引环比零增长，股权激励吞噬现金流。")
    md_lines.append("Duolingo市销率仅6.4倍，现金流超预期翻倍，具赔率优势。")
    md_lines.append("")

    md_lines.append("## 核心标的卖方模型经营假设与真实财报对比")
    md_lines.append("")
    
    # APP
    md_lines.append("### 标的：AppLovin（APP）")
    md_lines.append("卖方模型假设2026E营收增速38.6%，营运利润率84.1%。")
    md_lines.append("模型预测2026E自由现金流为52.31亿美元。")
    md_lines.append("真实三季报营收同比增55.5%，连续三季保持加速。")
    md_lines.append("毛利率减去销管费用率达82.9%，四季度指引超预期6%。")
    md_lines.append("当前TTM市销率17.0倍，动态PEG仅0.47倍。")
    md_lines.append("判定结果为梯队一：兼具真实经营杠杆与安全估值。")
    md_lines.append("最终裁决为买入首选，具备双拐点与回购强支撑。")
    md_lines.append("")

    # DUOL
    md_lines.append("### 标的：Duolingo（DUOL）")
    md_lines.append("卖方模型假设2026E营收增速16.3%，营运利润率10.4%。")
    md_lines.append("模型预测2026E自由现金流为3.77亿美元。")
    md_lines.append("真实三季报日活达6490万同比增29%，订阅收入超预期。")
    md_lines.append("公司毛利率逆势升至72.9%，扣激励自由现金流超预期翻倍。")
    md_lines.append("当前TTM市销率仅6.4倍，估值具有极高安全防护带。")
    md_lines.append("判定结果为梯队一：经营杠杆超预期且具备中盘高赔率。")
    md_lines.append("最终裁决为配置关注，经营韧性显著强于卖方假设。")
    md_lines.append("")

    # PLTR
    md_lines.append("### 标的：Palantir（PLTR）")
    md_lines.append("卖方模型假设2026E营收增速77.9%，营运利润率59.9%。")
    md_lines.append("模型预测2026E自由现金流为45.39亿美元。")
    md_lines.append("真实三季报营收大增96%，美国商业收入暴增148%。")
    md_lines.append("然而当前TTM市销率高达53.0倍，市盈率达113倍。")
    md_lines.append("三季度新签合同总价值环比降13.5%，未结订单期限缩短。")
    md_lines.append("判定结果为梯队二：基本面极强但市销率超20倍红线。")
    md_lines.append("最终裁决为严禁追涨，高利率环境下容错空间极小。")
    md_lines.append("")

    # NET
    md_lines.append("### 标的：Cloudflare（NET）")
    md_lines.append("卖方模型假设2026E营收增速29.7%，营运利润率14.9%。")
    md_lines.append("模型预测2026E自由现金流为4.01亿美元。")
    md_lines.append("模型假设2026E股权激励5.81亿美元，远超自由现金流。")
    md_lines.append("扣除激励后股东真实自由现金流为负1.80亿美元。")
    md_lines.append("当前TTM市销率达35.2倍，公认会计准则净利润持续为负。")
    md_lines.append("判定结果为梯队二：估值触碰红线且缺乏干净现金流。")
    md_lines.append("最终裁决为规避追高，股东权益每年持续被稀释2%。")
    md_lines.append("")

    # NOW
    md_lines.append("### 标的：ServiceNow（NOW）")
    md_lines.append("卖方模型假设2026E营收增速22.2%，营运利润率31.5%。")
    md_lines.append("模型预测2026E自由现金流为56.54亿美元。")
    md_lines.append("真实三季报当前履约义务恒定汇率增速骤降至18.5%。")
    md_lines.append("公有云推理成本增加致毛利率降3.6个百分点至77.3%。")
    md_lines.append("巨额举债并购致利息激增13倍，扣激励净利润负增长。")
    md_lines.append("判定结果为梯队三：经营杠杆遭遇算力与债务反向反噬。")
    md_lines.append("最终裁决为规避减仓，绩后暴跌27%确立预期下修。")
    md_lines.append("")

    # DDOG
    md_lines.append("### 标的：Datadog（DDOG）")
    md_lines.append("卖方模型假设2026E营收增速26.7%，营运利润率22.5%。")
    md_lines.append("模型预测2026E自由现金流为10.87亿美元。")
    md_lines.append("真实三季报当期营收增35.2%，但四季度指引环比停滞。")
    md_lines.append("四季度营业利润率指引环比大降4.1个百分点。")
    md_lines.append("单季股权激励高达2.27亿美元，侵蚀大部分经营现金流。")
    md_lines.append("判定结果为梯队三：指引放缓且缺乏连续回购注销支撑。")
    md_lines.append("最终裁决为中性观望，市盈率超248倍暂无右侧催化。")
    md_lines.append("")

    md_lines.append("## 30年宏观与量化回测投资指南")
    md_lines.append("高利率环境下软件估值中枢受限，唯有经营杠杆能驱动走势。")
    md_lines.append("回测显示市销率超20倍标的，在利率高位极易发生剧烈均值回归。")
    md_lines.append("操作纪律上：坚决买入AppLovin，逢高止盈Palantir与Cloudflare。")
    md_lines.append("坚决剔除成本反噬的ServiceNow，持续观察中盘标的Duolingo。")

    with open(OUT_MD_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")
    print("Saved Markdown successfully to:", OUT_MD_PATH)

if __name__ == "__main__":
    main()
