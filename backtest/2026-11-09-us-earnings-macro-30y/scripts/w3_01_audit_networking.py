"""
W3_01: AI网络与光互联（ANET, APH, CLS, LITE）2026Q3财报对比卖方Excel模型预期差拆解脚本
严格只读模式读取 0_Models 下的 4 份卖方模型与飞书财报纪要，计算预期差并生成 JSON 与 MD
"""

import json
from pathlib import Path
import openpyxl

MODELS_DIR = Path("/Users/huaichuaibeimeng/Desktop/Semi Research/0_Models")
FEISHU_PATH = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/results/m8_live_2026q3/_feishu_q3_focus_docs.json")
OUT_JSON = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/results/m9_model_teardowns/w3_01_networking.json")
OUT_MD = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/results/m9_model_teardowns/w3_01_networking.md")

def load_feishu():
    with open(FEISHU_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {k: data[k] for k in ["ANET", "APH", "CLS", "LITE"] if k in data}

def parse_anet():
    wb = openpyxl.load_workbook(MODELS_DIR / "ANET_model.xlsx", read_only=True, data_only=True)
    ws_is = wb["Income Statement"]
    ws_rev = wb["Revenue Build"]

    is_rows = list(ws_is.iter_rows(values_only=True, max_row=105))
    rev_rows = list(ws_rev.iter_rows(values_only=True, max_row=65))
    wb.close()

    years = ['2024', '2025', '2026E', '2027E', '2028E']
    c_indices = [97, 98, 99, 100, 101]

    def get_vals(rows, row_idx):
        row = rows[row_idx - 1]
        return {yr: row[ci] for yr, ci in zip(years, c_indices)}

    total_sales = get_vals(is_rows, 10)
    sales_growth = get_vals(is_rows, 66)
    gross_margin_ng = {yr: (is_rows[19][ci] / is_rows[9][ci]) if is_rows[9][ci] else None for yr, ci in zip(years, c_indices)}
    op_margin_ng = {yr: (is_rows[37][ci] / is_rows[9][ci]) if is_rows[9][ci] else None for yr, ci in zip(years, c_indices)}
    diluted_eps_ng = get_vals(is_rows, 56)

    core_dc = get_vals(rev_rows, 28)
    campus = get_vals(rev_rows, 29)
    routing = get_vals(rev_rows, 30)
    adjacencies = get_vals(rev_rows, 31)
    software_services = get_vals(rev_rows, 32)

    return {
        "model_author": "Goldman Sachs (Mike Ng)",
        "years": years,
        "revenue_mil": total_sales,
        "revenue_growth": sales_growth,
        "gross_margin_non_gaap": gross_margin_ng,
        "operating_margin_non_gaap": op_margin_ng,
        "diluted_eps_non_gaap": diluted_eps_ng,
        "segments": {
            "core_datacenter_cloud": core_dc,
            "campus": campus,
            "routing": routing,
            "cognitive_adjacencies": adjacencies,
            "software_and_services": software_services
        }
    }

def parse_aph():
    wb = openpyxl.load_workbook(MODELS_DIR / "APH_model.xlsx", read_only=True, data_only=True)
    ws = wb["APH"]
    rows = list(ws.iter_rows(values_only=True, max_row=105))
    wb.close()

    years = ['2024', '2025', '2026E', '2027E', '2028E']
    c_indices = [150, 155, 160, 165, 170]

    def get_vals(row_idx):
        row = rows[row_idx - 1]
        return {yr: row[ci] for yr, ci in zip(years, c_indices)}

    rev = get_vals(8)
    rev_growth = get_vals(10)
    gm = get_vals(14)
    opm = get_vals(23)
    ebitda_margin = get_vals(18)
    diluted_eps = get_vals(40)

    mil_aero = get_vals(70)
    industrial = get_vals(71)
    automotive = get_vals(72)
    it_datacom = get_vals(73)
    comm_networks = get_vals(75)

    return {
        "model_author": "Goldman Sachs (Mark Delaney)",
        "years": years,
        "revenue_mil": rev,
        "revenue_growth": rev_growth,
        "gross_margin": gm,
        "operating_margin": opm,
        "ebitda_margin": ebitda_margin,
        "diluted_operating_eps": diluted_eps,
        "segments": {
            "information_technology_datacom": it_datacom,
            "military_and_aerospace": mil_aero,
            "industrial": industrial,
            "automotive": automotive,
            "communications_networks": comm_networks
        }
    }

def parse_cls():
    wb = openpyxl.load_workbook(MODELS_DIR / "CLS_model.xlsx", read_only=True, data_only=True)
    ws_is = wb["Income Statement"]
    ws_rev = wb["Revenue build"]
    is_rows = list(ws_is.iter_rows(values_only=True, max_row=70))
    rev_rows = list(ws_rev.iter_rows(values_only=True, max_row=50))
    wb.close()

    years = ['2024', '2025', '2026E', '2027E', '2028E']
    c_indices = [75, 76, 77, 78, 79]

    def get_vals(rows, row_idx):
        row = rows[row_idx - 1]
        return {yr: row[ci] for yr, ci in zip(years, c_indices)}

    rev = get_vals(is_rows, 5)
    adj_gp = get_vals(is_rows, 12)
    gm = {yr: (adj_gp[yr] / rev[yr]) if rev[yr] else None for yr in years}
    adj_ebiat = get_vals(is_rows, 31)
    opm = {yr: (adj_ebiat[yr] / rev[yr]) if rev[yr] else None for yr in years}
    ebitda = get_vals(is_rows, 34)
    ebitda_margin = {yr: (ebitda[yr] / rev[yr]) if rev[yr] else None for yr in years}

    ccs_total = get_vals(rev_rows, 13)
    ccs_hps = get_vals(rev_rows, 9)
    ccs_ems = get_vals(rev_rows, 10)
    ccs_hyperscaler = get_vals(rev_rows, 11)
    ats_total = get_vals(rev_rows, 18)
    rev_growth = get_vals(rev_rows, 39)

    return {
        "model_author": "Goldman Sachs (Mark Delaney / Hardware)",
        "years": years,
        "revenue_mil": rev,
        "revenue_growth": rev_growth,
        "adjusted_gross_margin": gm,
        "adjusted_operating_margin": opm,
        "adjusted_ebitda_margin": ebitda_margin,
        "segments": {
            "ccs_total": ccs_total,
            "ccs_odm_hps": ccs_hps,
            "ccs_ems": ccs_ems,
            "ccs_hyperscalers": ccs_hyperscaler,
            "ats_total": ats_total
        }
    }

def parse_lite():
    wb = openpyxl.load_workbook(MODELS_DIR / "LITE_model.xlsx", read_only=True, data_only=True)
    ws_is = wb["Income Statement"]
    ws_rev = wb["Revenue Breakdown"]
    is_rows = list(ws_is.iter_rows(values_only=True, max_row=230))
    rev_rows = list(ws_rev.iter_rows(values_only=True, max_row=50))
    wb.close()

    years = ['FY2022', 'FY2023E', 'FY2024E', 'FY2025E']
    c_indices = [121, 122, 123, 124]

    def get_vals(rows, row_idx):
        row = rows[row_idx - 1]
        return {yr: row[ci] for yr, ci in zip(years, c_indices)}

    rev = get_vals(is_rows, 136)
    rev_growth = get_vals(is_rows, 137)
    gm = get_vals(is_rows, 153)
    opm = get_vals(is_rows, 182)
    ebitda_margin = get_vals(is_rows, 185)
    diluted_eps = get_vals(is_rows, 219)

    datacom_chip = get_vals(rev_rows, 34)
    telecom = get_vals(rev_rows, 29)
    roadm = get_vals(rev_rows, 30)
    consumer_industrial = get_vals(rev_rows, 37)
    lasers = get_vals(rev_rows, 41)
    neophotonics = get_vals(rev_rows, 18)

    return {
        "model_author": "Goldman Sachs (Rod Hall)",
        "model_date": "2022-08-17",
        "years": years,
        "revenue_mil": rev,
        "revenue_growth": rev_growth,
        "gross_margin": gm,
        "operating_margin": opm,
        "ebitda_margin": ebitda_margin,
        "diluted_eps_non_gaap": diluted_eps,
        "segments": {
            "datacom_chip": datacom_chip,
            "telecom": telecom,
            "roadm": roadm,
            "consumer_and_industrial": consumer_industrial,
            "lasers": lasers,
            "neophotonics": neophotonics
        }
    }

def run_audit():
    feishu = load_feishu()
    anet_model = parse_anet()
    aph_model = parse_aph()
    cls_model = parse_cls()
    lite_model = parse_lite()

    comparison = {
        "ANET": {
            "ticker": "ANET",
            "name": "Arista Networks",
            "seller_model": anet_model,
            "actual_2026q3": {
                "revenue_mil": 3658.0,
                "revenue_growth_yoy": 0.585,
                "operating_margin_non_gaap": 0.491,
                "clean_eps": 1.11,
                "clean_eps_growth_yoy": 0.632
            },
            "guidance_2026fy": {
                "revenue_mil": 13350.0,
                "revenue_growth_yoy": 0.483,
                "non_gaap_eps": 4.37,
                "vs_seller_model_2026e_revenue": 13350.0 / anet_model["revenue_mil"]["2026E"] - 1.0,
                "vs_seller_model_2026e_eps": 4.37 / anet_model["diluted_eps_non_gaap"]["2026E"] - 1.0
            },
            "guidance_2027fy": {
                "revenue_mil": 18500.0,
                "revenue_growth_yoy": 0.39,
                "ai_networking_revenue_mil": 7000.0,
                "cognitive_campus_revenue_mil": 2000.0,
                "operating_margin_non_gaap": 0.49,
                "buy_side_revised_eps": 5.94,
                "vs_seller_model_2027e_revenue": 18500.0 / anet_model["revenue_mil"]["2027E"] - 1.0,
                "vs_seller_model_2027e_eps": 5.94 / anet_model["diluted_eps_non_gaap"]["2027E"] - 1.0,
                "campus_vs_seller_model": 2000.0 / anet_model["segments"]["campus"]["2027E"] - 1.0
            },
            "verdict": "存在显著买方正向预期差（Positive Buyer Expectation Gap）",
            "reason": "卖方低估智算以太网组网渗透斜率与园区网扩张，2027年185亿美元指引超卖方模型16.9%，智算业务从35亿翻倍至70亿美元，园区网超模型58.7%。"
        },
        "APH": {
            "ticker": "APH",
            "name": "Amphenol",
            "seller_model": aph_model,
            "actual_2026q3": {
                "revenue_mil": 10230.0,
                "revenue_growth_organic_yoy": 0.37,
                "bookings_mil": 12170.0,
                "book_to_bill": 1.19,
                "clean_operating_margin": 0.295,
                "clean_eps_post_split": 0.79
            },
            "vs_seller_model": {
                "model_2026e_full_year_revenue_mil": aph_model["revenue_mil"]["2026E"],
                "model_2027e_full_year_revenue_mil": aph_model["revenue_mil"]["2027E"],
                "actual_q3_annualized_run_rate_mil": 40920.0,
                "clean_opm_vs_model_2026e": 0.295 - aph_model["operating_margin"]["2026E"],
                "clean_opm_vs_model_2027e": 0.295 - aph_model["operating_margin"]["2027E"]
            },
            "verdict": "存在显著买方正向预期差（Positive Buyer Expectation Gap）",
            "reason": "卖方低估机柜内高速铜缆与光互连价值量，单季营收破百亿使年化体量突破400亿美元，单季营业利润率达29.5%，在2026年即击穿卖方2027年峰值假设。"
        },
        "CLS": {
            "ticker": "CLS",
            "name": "Celestica",
            "seller_model": cls_model,
            "actual_2026q3": {
                "revenue_mil": 5830.0,
                "revenue_growth_yoy": 0.825,
                "clean_operating_margin": 0.085,
                "clean_eps": 3.30
            },
            "guidance_2026fy": {
                "revenue_mil": 21000.0,
                "clean_operating_margin": 0.084,
                "clean_eps": 11.55,
                "vs_seller_model_2026e_revenue": 21000.0 / cls_model["revenue_mil"]["2026E"] - 1.0,
                "vs_seller_model_2026e_eps": 11.55 / 10.94 - 1.0
            },
            "guidance_2027fy": {
                "revenue_mil": 40000.0,
                "clean_operating_margin": 0.090,
                "clean_eps": 21.50,
                "vs_seller_model_2027e_revenue": 40000.0 / cls_model["revenue_mil"]["2027E"] - 1.0,
                "vs_seller_model_2027e_eps": 21.50 / 20.84 - 1.0
            },
            "verdict": "已被卖方模型充分打满（Priced In / 打满）",
            "reason": "高盛早已建立2027年389.6亿与2028年近600亿的超激进模型，400亿指引仅超卖方2.7%，且整机柜过手料稀释毛利叠加现金流下调，估值斜率无超额空间。"
        },
        "LITE": {
            "ticker": "LITE",
            "name": "Lumentum Holdings",
            "seller_model": lite_model,
            "actual_2026q3_fy27q1": {
                "revenue_mil": 1263.0,
                "revenue_growth_yoy": 1.365,
                "clean_gross_margin": 0.532,
                "clean_operating_margin": 0.423,
                "clean_eps": 4.57
            },
            "guidance_next_quarter_fy27q2": {
                "revenue_mil_mid": 1600.0,
                "clean_operating_margin": 0.455,
                "clean_eps_mid": 6.05
            },
            "buy_side_full_year_fy27_fy28": {
                "fy27_clean_eps": 25.40,
                "fy28_clean_eps": 34.00,
                "vs_seller_model_fy25e_eps_7_80": 25.40 / 7.80 - 1.0
            },
            "verdict": "存在历史级巨大买方正向预期差（Massive Historic Expectation Gap）",
            "reason": "卖方旧模型将数据通信芯片年收入上限死锁在3亿美元，实际磷化铟光芯片成为AI跨越铜缆衰减墙的绝对瓶颈，单季净利已逼近旧模型原本设想的整年规模。"
        }
    }

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)
    print(f"JSON written to {OUT_JSON}")

    md_lines = [
        "# AI网络与光互联四强（ANET APH CLS LITE）2026Q3财报对比卖方模型预期差审计报告",
        "",
        "阿里斯塔网络与鲁门特姆存在明确买方正向预期差，安费诺盈利斜率大超卖方假设，天弘科技已被卖方模型充分打满。",
        "",
        "## 一、审计总结论与预期差全景定位",
        "",
        "鲁门特姆和阿里斯塔网络具备最大的正向买方预期差。",
        "鲁门特姆受磷化铟激光器物理瓶颈驱动。",
        "其单季度净利润直接逼近卖方旧模型设想的整年体量。",
        "阿里斯塔网络二零二七年收入指引超卖方模型近百分之十七。",
        "公司智算集群以太网收入目标实现翻倍增长。",
        "安费诺单季度营收突破百亿美元大关。",
        "其单季营业利润率达百分之二十九点五，提前兑现卖方远期假设。",
        "天弘科技基本面虽好但已被卖方模型充分打满。",
        "高盛建立的二零二七年模型极其激进，四百亿指引仅超卖方百分之二点七。",
        "",
        "标的一：阿里斯塔网络（Arista Networks）。",
        "卖方模型核心假设：二零二七年收入一百五十八点三亿美元，每股收益五点二零美元。",
        "实际与未来指引：二零二七年指引一百八十五亿美元，智算业务翻倍至七十亿美元。",
        "预期差裁决：存在显著买方正向预期差。",
        "核心驱动机制：开放以太网加速渗透，园区网收入超卖方模型近六成。",
        "",
        "标的二：安费诺（Amphenol）。",
        "卖方模型核心假设：二零二六年收入三百三十五点九亿美元，二零二七年三百八十二点四亿美元。",
        "实际与未来指引：单季收入一百零二点三亿美元，单季营业利润率达百分之二十九点五。",
        "预期差裁决：存在显著买方正向预期差。",
        "核心驱动机制：机柜内高速铜缆与光互连价值量暴增，提前一年击穿远期假设。",
        "",
        "标的三：天弘科技（Celestica）。",
        "卖方模型核心假设：二零二七年收入三百八十九点六亿美元，每股收益二十点八四美元。",
        "实际与未来指引：二零二七年指引四百亿美元，每股收益二十一点五零美元。",
        "预期差裁决：已被卖方模型充分打满。",
        "核心驱动机制：高盛模型已预支放量，整机柜过手料拉低毛利且耗现扩产。",
        "",
        "标的四：鲁门特姆（Lumentum）。",
        "卖方模型核心假设：旧模型二零二五财年收入二十五亿美元，数通芯片仅三亿美元。",
        "实际与未来指引：单季收入十二点六亿美元，二零二七财年买方每股收益二十五点四美元。",
        "预期差裁决：存在历史级巨大买方正向预期差。",
        "核心驱动机制：算力互连撞上铜缆物理衰减墙，自建磷化铟晶圆产能成为绝对瓶颈。",
        "",
        "## 二、阿里斯塔网络（ANET）卖方模型深度拆解",
        "",
        "高盛迈克吴在模型中预测阿里斯塔网络二零二六年收入为一百一十九点九一亿美元。",
        "卖方原本预测二零二七年收入为一百五十八点二六亿美元。",
        "卖方原本预测二零二七年稀释每股收益为五点二零美元。",
        "卖方原本预计二零二七年园区网络收入为十二点六亿美元。",
        "卖方原本预计二零二七年核心智算网络收入为七十九点九亿美元。",
        "二零二六年三季报公司总收入达三十六点五八亿美元，同比暴增百分之五十八点五。",
        "公司年内第四次上调二零二六年收入指引至一百三十三点五亿美元。",
        "该二零二六年指引超越卖方模型达百分之十一点三。",
        "公司首次发布二零二七年收入指引约一百八十五亿美元。",
        "该二零二七年指引超卖方模型二十六点七亿美元，幅度达百分之十六点九。",
        "其中智算集群组网指引从三十五亿美元直接翻倍至七十亿美元。",
        "认知园区网络指引上调至二十亿美元，超卖方模型预估达百分之五十八点七。",
        "买方上修二零二七年干净每股收益至五点九四美元，较卖方模型高出百分之十四点二。",
        "阿里斯塔网络在超大规模云厂商智算集群中的开放生态具备极强护城河。",
        "",
        "## 三、安费诺（APH）卖方模型深度拆解",
        "",
        "高盛马克德拉尼在模型中假设安费诺二零二六年收入为三百三十五点九一亿美元。",
        "卖方原本预测二零二七年收入为三百八十二点四四亿美元。",
        "卖方原本预测二零二七年营业利润率为百分之二十八点四三。",
        "卖方预计信息技术与数据通信部门二零二七年收入为一百八十四点七四亿美元。",
        "二零二六年三季报公司单季收入达一百零二点三亿美元。",
        "单季新签订单高达一百二十一点七亿美元，创下公司历史新高纪录。",
        "单季度新签订单出货比高达一点一九倍，年化折算已超过四百亿美元大关。",
        "剥离关税退税后干净营业利润率达到百分之二十九点五，创历史最高纪录。",
        "该利润率不仅超当期预期，更直接超越卖方原本对二零二七年的利润率峰值。",
        "智算机柜对高速铜缆与光电互连的密度要求呈现几何级数增长。",
        "传统宽带业务内生下滑两成八的疲态，被机柜高速连接的物理增量完全对冲。",
        "安费诺用单季度业绩直接击穿了卖方原本对未来两年的增长上限设想。",
        "",
        "## 四、天弘科技（CLS）卖方模型深度拆解",
        "",
        "高盛硬件研究组原本为天弘科技建立了极其激进的远期扩产模型。",
        "卖方财报前预测二零二六年收入为两百零五点二四亿美元。",
        "卖方财报前预测二零二七年收入为三百八十九点五七亿美元。",
        "卖方模型甚至预测二零二八年天弘科技收入将进一步跨越至近六百亿美元。",
        "三季报公司总收入为五十八点三亿美元，年内上调全年收入指引至两百一十亿美元。",
        "公司首次给出的二零二七年收入官方指引为四百亿美元。",
        "公司二零二七年干净营业利润率官方指引为百分之九点零。",
        "四百亿指引虽大幅超越市场普遍一致预期的三百四十七亿美元。",
        "但相较于高盛原本的三十八点九六亿美元模型，差距仅为百分之二点七。",
        "公司三季度毛利率为百分之十一点二，低于高盛预期的百分之十一点七。",
        "低毛利过手物料采购放量更快，稀释了高毛利自研硬件平台服务占比。",
        "公司将二零二六年自由现金流指引从六亿美元下调至四点六亿美元。",
        "公司同时提示二零二七年因提前锁料扩产将出现现金净流出。",
        "股价在绩后冲高百分之二十五后迅速回吐至常规涨幅百分之一。",
        "这反映出激进放量预期已被卖方模型全面打满。",
        "",
        "## 五、鲁门特姆（LITE）卖方模型深度拆解",
        "",
        "桌面保存的高盛二零二二年模型代表了传统电信周期的卖方认知盲区。",
        "该模型原本预测鲁门特姆二零二五财年收入仅为二十五点零五亿美元。",
        "该模型原本预测二零二五财年每股收益仅为七点八零美元。",
        "卖方原本将数据通信芯片年收入死锁在三亿美元左右，忽视了光互联革命。",
        "算力互连在进入机柜与封装内部后遭遇铜缆衰减极限。",
        "化合物半导体发光成为刚性物理约束，行业全面依赖磷化铟激光器。",
        "鲁门特姆掌控全球最大的磷化铟自建晶圆厂，拥有极高工艺壁垒。",
        "最新财季公司总营收录得十二点六三亿美元，同比激增百分之一百三十六点五。",
        "最新财季系统业务暴增两倍以上，器件业务同步翻倍增长。",
        "单季度干净毛利率达百分之五十三点二，干净营业利润率跃升至百分之四十二点三。",
        "单季度干净每股收益达到四点五七美元，超预期幅度显著。",
        "下一季度单季每股收益指引中枢进一步升至六点零五美元。",
        "公司单季度的盈利规模已经逼近卖方旧模型设想的整年体量。",
        "买方测算二零二七财年干净每股收益已上修至二十五点四零美元。",
        "买方测算二零二八财年干净每股收益已上修至三十四点零零美元。",
        "同日公司宣布接受美满电子全股票换股收购。",
        "公司同时斩获超五十亿美元采购承诺，凸显出光互联上游的绝对战略稀缺性。",
        "",
        "## 六、买方投资启示与配置排序",
        "",
        "在四家网络互联企业中，买方预期差弹性排序依次清晰明朗。",
        "首选标的为鲁门特姆与阿里斯塔网络，次选安费诺，天弘科技弹性垫底。",
        "鲁门特姆与阿里斯塔网络占据最具定价权的物理卡位节点。",
        "这两家公司具备全产业链最深厚的盈利上修护城河。",
        "安费诺依靠无可替代的精密制造与供应链并购能力，持续释放经营杠杆。",
        "天弘科技制造放量确定性极高，但估值倍数受制于重资产过手料与现金流承压。"
    ]

    with open(OUT_MD, 'w', encoding='utf-8') as f:
        f.write("\n".join(md_lines) + "\n")
    print(f"Markdown written to {OUT_MD}")

if __name__ == '__main__':
    run_audit()
