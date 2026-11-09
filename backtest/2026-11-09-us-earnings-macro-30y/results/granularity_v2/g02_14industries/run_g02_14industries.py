#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
G02: 14 Buy-Side Sub-Industries x Strategy Fit, Valuation Hard Ceilings & False-Inflection/SBC Trap Rates
30-Year US Stock Selection Joint Backtest (Strictly Zero-Lookahead PIT XBRL 2009-2026 + Delisted Terminal Recovery)

Guarantees:
1. Strict D+1 Close Entry (entry_date) after SEC 10-Q/10-K filing reaction completes (zero lookahead).
2. Full Delisted Stock Recovery (mergers at actual deal premium, bankruptcies at -95% terminal residual; zero survivorship drop).
3. Zero-Lookahead 1,000x / 1,000,000x XBRL Share-Unit Bloat Calibration (prevents fake multi-trillion mcap & fake 10,000x PE/PS).
4. D15-Compliant Calendar-Quarter Equal-Weight Net Excess Return vs SPY Total Return + 250d Per-Ticker Cooldown Deduplication.
5. Evaluates across both mcap_2026_equiv_b >= 10B and >= 25B, and across Full (2009-2026), Last 10Y (2016-2026), and High-Rate (2022-2026).
"""

import os
import re
import sys
import json
import time
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy import stats

PROJ_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
DATA_PATH = os.path.join(PROJ_DIR, "data/xbrl_master_pit_2009_2026.parquet")
MACRO_PATH = os.path.join(PROJ_DIR, "data/macro_pit_daily_1990_2026.parquet")
OUT_DIR = os.path.join(PROJ_DIR, "results/granularity_v2/g02_14industries")
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, os.path.join(PROJ_DIR, "scripts"))
from backtest_stats_lib import deduplicate_cooldown
from w2_01_trajectory_anatomy import build_uniform_pit_trajectories
from w2_07_30y_and_survivorship import build_augmented_price_engine, attach_events_fast


# ==============================================================================
# 1. 14 BUY-SIDE BUSINESS MODEL TRACKS TAXONOMY (100% COVERAGE OF CLEAN UNIVERSE)
# ==============================================================================
TRACK_META = {
    1: ("G02_T01", "01_半导体设备与晶圆代工"),
    2: ("G02_T02", "02_AI算力芯片与光通信硬件互连"),
    3: ("G02_T03", "03_存储芯片与强周期科技硬件"),
    4: ("G02_T04", "04_企业级软件与网络安全SaaS"),
    5: ("G02_T05", "05_互联网平台电商与数字广告"),
    6: ("G02_T06", "06_医疗器械生命科学与诊断耗材"),
    7: ("G02_T07", "07_创新药与商业化生物科技"),
    8: ("G02_T08", "08_金融交易所支付网络与评级数据"),
    9: ("G02_T09", "09_传统商业银行资管与保险"),
    10: ("G02_T10", "10_连锁零售餐饮与专营分销食人族"),
    11: ("G02_T11", "11_高端工业制造工程与国防航空"),
    12: ("G02_T12", "12_消费品牌与必需消费"),
    13: ("G02_T13", "13_电力公用事业核电与基础设施"),
    14: ("G02_T14", "14_大宗矿产油气炼化化工航运与地产REITs"),
}

EXACT_TRACK_MAP = {
    # 01. 半导体设备、特种材料、晶圆代工封测与EDA/IP
    **{t: 1 for t in [
        "KLAC", "LRCX", "AMAT", "ASML", "TSM", "SNPS", "CDNS",
        "TER", "ENTG", "ONTO", "MKSI", "ACMR", "AEIS", "FORM", "AMKR",
        "Q", "OLED", "RMBS", "IPGP", "IDCC"
    ]},
    # 02. AI算力芯片、高端模拟信号链与光通信互连液冷供电EMS
    **{t: 2 for t in [
        "NVDA", "AVGO", "ANET", "APH", "LITE", "CIEN", "VRT", "CLS",
        "AMD", "MRVL", "MPWR", "QCOM", "XLNX", "ALAB", "CRDO", "MTSI", "SMTC", "CBRS", "LSCC",
        "TXN", "ADI", "NXPI", "MXIM", "SLAB", "SITM",
        "COHR", "FN", "AAOI", "GLW", "TEL", "CSCO", "FFIV", "UI", "MSI", "VIAV",
        "JBL", "FLEX", "SANM", "PLXS", "TTMI", "VICR", "APLD", "CRWV"
    ]},
    # 03. 存储芯片与强周期科技硬件 (DRAM/NAND/HDD/PC/Server/IDM/RF-Power/Solar/IT-Dist)
    **{t: 3 for t in [
        "MU", "WDC", "SNDK", "STX", "HPQ", "DELL",
        "EMC", "NTAP", "P", "HPE", "SMCI", "INTC", "MBLY",
        "ON", "MCHP", "SWKS", "QRVO", "CRUS", "ALGM", "MXL", "PI",
        "LOGI", "XRX", "PBI", "EK",
        "ENPH", "SEDG", "FSLR", "NXT", "TE",
        "ARW", "AVT", "SNX", "INGM", "IONQ", "RGTI", "QBTS", "QNT"
    ]},
    # 04. 企业级软件、云底座与网络安全 SaaS (+ IT咨询服务)
    **{t: 4 for t in [
        "MSFT", "NOW", "CRM", "PANW", "FTNT", "CRWD", "DDOG", "NET", "ADBE", "INTU",
        "ORCL", "PLTR", "SNOW", "MDB", "ZS", "OKTA", "WDAY", "ADSK", "ANSS", "AZPN",
        "PTC", "BSY", "ROP", "TYL", "GWRE", "MANH", "HUBS", "TEAM", "ZM", "DOCU",
        "TWLO", "SPLK", "VMW", "RHT", "WORK", "PLAN", "COUP", "SMAR", "AVLR",
        "PCTY", "PAYC", "ADP", "PAYX", "BILL", "VEEV", "IOT", "RBRK", "NTSK", "TTAN",
        "FIG", "GTLB", "ESTC", "DT", "S", "QLYS", "VRNS", "SAIL", "CVLT", "NTNX",
        "OTEX", "GEN", "GDDY", "AKAM", "VRSN", "FIVN", "RNG", "PEGA", "APPF", "PCOR",
        "PATH", "DBX", "FROG", "DOCN", "ZETA", "YOU", "MSTR", "NAVN", "OCTV", "GTM",
        "KVYO", "U",
        "ACN", "IBM", "CTSH", "EPAM", "DXC", "IT", "EXLS", "G", "TDC", "AGYS", "NIQ",
        "ATHN", "DOCS", "PHR", "CERT", "SDGR", "TEM", "HNGE", "LVGO", "ACCD", "PGNY", "TDOC"
    ]},
    # 05. 互联网平台、电商、数字广告与数字娱乐
    **{t: 5 for t in [
        "META", "GOOGL", "GOOG", "AMZN", "NFLX", "APP", "BKNG", "UBER", "DUOL",
        "MELI", "DASH", "ABNB", "SHOP", "SPOT", "TTD", "RDDT", "PINS", "SNAP", "TWTR", "LNKD",
        "EBAY", "ETSY", "CPNG", "W", "CHWY", "EXPE", "TRIP", "LYFT", "CART", "MTCH",
        "RBLX", "EA", "TTWO", "ATVI", "FLUT", "DKNG", "RSI", "ROKU",
        "DIS", "LYV", "TKO", "WMG", "SIRI", "NYT", "NWS", "OMC", "FOX", "FWONA",
        "LLYVA", "SPHR", "VSNT", "NXST", "AMC", "CHGG", "Z", "GDRX", "HIMS", "GHC",
        "LAUR", "XMTR", "MBGL", "MSGS"
    ]},
    # 06. 医疗器械、生命科学工具与诊断耗材 (严格不含重资产医院与药房医保)
    **{t: 6 for t in [
        "ISRG", "SYK", "TMO", "DHR", "IDXX", "DXCM", "NTRA", "GH", "EW",
        "ABT", "BSX", "MDT", "BDX", "ZBH", "BAX", "GEHC", "SOLV", "MMED",
        "ALGN", "PODD", "RMD", "STE", "WST", "HOLX", "TFX", "COO", "BLCO",
        "PEN", "INSP", "ABMD", "SWAV", "AXNX", "NARI", "ATRC", "AXGN", "GKOS", "GMED",
        "MASI", "MMSI", "IRTC", "TNDM", "NVRO", "STAA", "PRCT", "TMDX", "NVCR", "XRAY", "HSIC", "MDLN",
        "A", "WAT", "MTD", "BRKR", "RVTY", "BIO", "AVTR", "RGEN", "TECH", "CRL", "IQV", "MEDP",
        "ILMN", "EXAS", "LH", "DGX", "CPHD", "GRAL", "CAI", "VCYT", "CDNA", "PACB", "TXG",
        "NVTA", "ADPT", "NEO", "NEOG", "HSKA", "OPK", "SHC", "RDNT"
    ]},
    # 07. 创新药与商业化生物科技
    **{t: 7 for t in [
        "LLY", "VRTX", "REGN", "ABBV", "AMGN", "GILD", "HALO", "ALNY",
        "MRK", "JNJ", "PFE", "BMY", "ZTS", "BIIB", "MRNA", "INCY", "NBIX", "BMRN",
        "UTHR", "EXEL", "JAZZ", "ROIV", "RPRX", "IONS", "SRPT", "ALKS", "ARWR", "AXSM",
        "BBIO", "INSM", "MDGL", "CYTK", "RVMD", "SMMT", "CORT", "KRYS",
        "PCYC", "CELG", "ALXN", "AGN", "SHPG", "HZNP", "SGEN", "GWPH", "ICPT", "GBT",
        "FOLD", "TSRO", "XLRN", "BPMC", "BLUE", "JUNO", "BIVV", "SLXP", "ARNA", "VVUS",
        "ENDP", "BHC", "TEVA", "VTRS", "OGN", "PRGO", "AMRX", "SUPN", "PCRX", "IRWD",
        "ITCI", "RARE", "BCRX", "PTCT", "LGND", "NKTR", "NVAX", "VIR", "BEAM", "CRSP",
        "DNLI", "RCUS", "XNCR", "IOVA", "ACLX", "SWTX", "RVNC", "ADMA", "CBPO", "APLS",
        "KNSA", "MIRM", "PTGX", "RYTM", "TGTX", "TVTX", "XENE", "CGON", "COGT", "DNTH",
        "ELAN", "ERAS", "IBRX", "IMCR", "IMVT", "KYMR", "KYNB", "LNTH", "LQDA", "ORKA",
        "PGEN", "PRAX", "SRRK", "SYRE", "DFTX", "AMRN", "ACAD", "AGIO", "VCEL"
    ]},
    # 08. 金融交易所、支付网络与评级数据
    **{t: 8 for t in [
        "V", "MA", "ICE", "CME", "CBOE", "SPGI", "MCO", "MSCI", "FICO",
        "NDAQ", "TW", "MKTX", "VIRT", "BGC", "COIN", "SNEX",
        "EFX", "TRU", "FDS", "MORN", "VRSK",
        "PYPL", "XYZ", "FIS", "FISV", "GPN", "JKHY", "CPAY", "WEX", "TOST",
        "BR", "WU", "RELY", "ACIW", "BKI", "SSNC", "CRCL", "HQY"
    ]},
    # 09. 传统商业银行、资管与保险 (含医保Managed Care)
    **{t: 9 for t in [
        "JPM", "BAC", "SCHW", "BLK", "PGR", "CB", "AXP",
        "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "BNY", "STT", "NTRS",
        "COF", "DFS", "SYF", "ALLY", "SIVB", "BBT", "FLG", "CBC",
        "IBKR", "HOOD", "RJF", "LPLA", "SF", "JEF", "PIPR", "EVR", "HLI", "PJT", "FRHC", "GLXY",
        "BX", "KKR", "APO", "ARES", "BAM", "OWL", "TPG", "CG", "TROW", "BEN", "IVZ",
        "AMP", "AMG", "SEIC", "HLNE", "STEP", "VCTR", "WT", "MAIN", "ARCC", "OBDC", "OTF", "PS", "HASI",
        "BRK-A", "TRV", "ALL", "AIG", "HIG", "ACGL", "WRB", "CINF", "MKL", "RNR", "RLI", "KNSL",
        "ORI", "AFG", "CNA", "EG", "AXS", "WTM", "L", "MRSH", "AON", "AJG", "WTW", "BRO", "RYAN",
        "ERIE", "MET", "PRU", "AFL", "PFG", "UNM", "EQH", "VOYA", "LNC", "GL", "BHF", "GNW",
        "RGA", "CRBG", "JXN", "FNF", "FAF", "ACT", "ESNT", "MTG", "AIZ", "CNO", "PRI", "SIGI", "THG", "MCY",
        "AFRM", "SOFI", "RKT", "SLM", "OMF", "CACC", "NAVI", "ENVA", "CHYM", "FIGR", "ANDG",
        "UNH", "ELV", "CI", "HUM", "CNC", "MOH", "AET", "CVS", "OSCR"
    ]},
    # 10. 连锁零售、餐饮与专营分销食人族
    **{t: 10 for t in [
        "COST", "ORLY", "AZO", "HD", "TJX", "CMG", "CPRT", "CTAS", "GWW", "URI",
        "WMT", "BJ", "PSMT", "KR", "ACI", "SFM", "CASY", "MUSA",
        "AAP", "GPC", "LKQ", "KMX", "AN", "LAD", "PAG", "CVNA", "RUSHA",
        "LOW", "FND", "TSCO", "FAST", "FERG", "WCC", "AIT", "MSM", "CNM", "POOL", "WSO", "BLDR", "QXO",
        "SUNB", "ROL", "ARMK", "SYY", "USFD", "PFGC", "MCK", "COR", "CAH", "CDW", "RBA",
        "ROST", "BURL", "FIVE", "DG", "DLTR", "TGT", "ULTA", "DKS", "WSM", "BBY", "SIG", "BBWI",
        "GAP", "ANF", "URBN", "VSXY", "M", "KSS", "DDS", "JCP", "SHLD", "BBBY", "SPLS", "RAD", "GME",
        "FCFS", "HRB", "SCI", "FTDR", "ADT",
        "MCD", "SBUX", "YUM", "QSR", "DRI", "DPZ", "TXRH", "WING", "CAVA", "BROS", "EAT", "CAKE", "JMKE",
        "MAR", "HLT", "H", "WH"
    ]},
    # 11. 高端工业制造、工程与国防航空
    **{t: 11 for t in [
        "GE", "GEV", "ETN", "PH", "TT", "EME", "PWR", "RTX", "LMT", "TDG", "HEI", "BWXT",
        "CARR", "LII", "AAON", "JCI", "OTIS", "FIX", "MTZ", "DY", "IESC", "MWH", "STRL",
        "ACM", "FLR", "GVA", "J", "TTEK", "ROAD", "AGX", "LGN",
        "NOC", "GD", "LHX", "BA", "HWM", "AXON", "CW", "HII", "TXT", "DRS", "SARO", "LOAR",
        "KRMN", "KTOS", "AVAV", "RKLB", "SPCX", "PL", "LDOS", "BAH", "CACI", "SAIC", "PSN", "AMTM", "VSEC",
        "MRCY", "ESE", "ARXS", "AIR", "BETA", "JOBY", "HONA",
        "HON", "CAT", "DE", "PCAR", "CMI", "ITW", "EMR", "ROK", "AME", "DOV", "IR",
        "XYL", "IEX", "NDSN", "GGG", "FLS", "ITT", "PNR", "WTS", "ZWS", "FTV", "RAL", "VNT",
        "TDY", "KEYS", "GRMN", "TRMB", "CGNX", "ZBRA", "SYM", "NOVT", "HUBB", "NVT", "POWL",
        "LFUS", "ENS", "BE", "GNRC", "INIO", "LECO", "SNA", "SWK", "TTC", "SSD", "AYI",
        "AGCO", "CNH", "OSK", "TEX", "FSS", "GTES", "JBTM", "MIDD", "NPO", "RBC", "RRX", "SPXC", "ST", "TKR", "VMI", "CR", "ACA", "MTRN",
        "WAB", "UNP", "CSX", "NSC", "ODFL", "SAIA", "JBHT", "KNX", "LSTR", "SNDR", "XPO", "GXO",
        "CHRW", "EXPD", "UPS", "FDX", "FDXF", "FTAI", "GATX",
        "ALLE", "APG", "DCI", "MAIR", "CSW", "MMM", "ULS", "RHI", "MSA", "AUR"
    ]},
    # 12. 消费品牌与必需消费
    **{t: 12 for t in [
        "AAPL", "NKE", "PG", "KO", "PEP", "MNST", "PM",
        "DECK", "CROX", "LULU", "TPR", "RL", "PVH", "VFC", "CPRI", "UA", "LEVI", "FOSL",
        "CELH", "KDP", "COKE", "PRMB", "STZ", "BF-B", "TAP", "MO",
        "CL", "CHD", "CLX", "KMB", "KVUE", "EL", "ELF", "COTY", "OLPX", "NWL",
        "WHR", "SN", "AOS", "SGI", "MHK",
        "MDLZ", "HSY", "KHC", "GIS", "CPB", "CAG", "SJM", "MKC", "HRL", "TSN", "PPC", "SFD",
        "LW", "DAR", "INGR", "ADM", "BG", "BYND",
        "HAS", "MAT", "GOLF", "PTON", "HOG", "DLB"
    ]},
    # 13. 电力公用事业、核电与能源环保基础设施
    **{t: 13 for t in [
        "CEG", "VST", "TLN", "NEE", "LNG", "WM", "RSG",
        "NRG", "OKLO", "XE", "FRVO", "ORA", "CWEN", "AES", "PLUG",
        "SO", "DUK", "D", "AEP", "SRE", "EXC", "PEG", "XEL", "ED", "PCG", "EIX", "ETR",
        "PPL", "FE", "ES", "DTE", "WEC", "AEE", "CMS", "CNP", "NI", "EVRG", "PNW", "LNT",
        "OGE", "IDA", "POR", "BKH", "TXNM", "AWK", "WTRG",
        "ATO", "NJR", "OGS", "NFG", "UGI", "SWX",
        "VG", "KMI", "WMB", "OKE", "EPD", "TRGP", "DTM", "AM", "KNTK", "AROC", "KGS", "MMP", "HESM",
        "WCN", "CWST", "CLH", "VLTO"
    ]},
    # 14. 大宗矿产、油气、炼化、化工、航运与地产REITs (强周期与重资产对照池)
    **{t: 14 for t in [
        "XOM", "CVX", "COP", "EOG", "SLB", "HAL", "BKR", "MPC", "PSX", "VLO", "DINO", "PBF",
        "OXY", "DVN", "FANG", "EQT", "CTRA", "PXD", "APA", "OVV", "MUR", "AR", "RRC", "CNX",
        "CHRD", "PR", "MGY", "MTDR", "SM", "VNOM", "TPL", "CHK", "GPOR", "EP", "LB",
        "NOV", "FTI", "WFRD", "WHD", "HP", "NBR", "RIG", "VAL", "NE", "OII", "CAM", "FPS", "WWD",
        "FCX", "SCCO", "NEM", "RGLD", "AA", "NUE", "STLD", "CLF", "CMC", "RS", "ATI", "CRS", "MLI",
        "MP", "USAR", "UEC", "CDE", "HL", "SSRM", "HCC",
        "VMC", "MLM", "CRH", "AMRZ", "EXP", "JHX", "OC", "TREX", "AWI", "MAS", "FBIN",
        "LIN", "APD", "SHW", "PPG", "ECL", "AXTA", "RPM", "DD", "DOW", "LYB", "CE", "EMN", "WLK",
        "ALB", "CF", "MOS", "CTVA", "FMC", "MON", "SOLS", "IFF", "ESI", "HXL", "NEU", "BCPC", "SXT", "CSL", "PRM",
        "IP", "PKG", "SW", "BALL", "CCK", "OI", "AVY", "AMCR", "ATR", "SON", "WMS",
        "DAL", "UAL", "LUV", "AAL", "ALK", "SAVE", "RJET", "CCL", "RCL", "NCLH", "MATX", "KEX", "INSW",
        "DHI", "LEN", "NVR", "PHM", "TOL", "IBP", "ECG",
        "TSLA", "GM", "F", "RIVN", "LCID", "APTV", "BWA", "ALV", "LEA", "ALSN", "MOD", "GTX", "GT",
        "HTZ", "UHAL", "R", "LVS", "WYNN", "MGM", "CZR", "BYD", "PENN", "CHDN", "RRR", "LTH",
        "T", "VZ", "TMUS", "CMCSA", "CHTR", "LUMN", "CABO", "LBRDA", "ASTS", "IRDM", "VSAT", "GSAT", "ECHO", "DPC",
        "HCA", "UHS", "THC", "DVA", "EHC", "ENSG", "PACS", "CHE", "BTSG", "ONEM",
        "CBRE", "JLL", "CSGP", "COMP", "INVH", "MRP", "TRNO", "AIV", "FCPT", "SLG",
        "BMNR", "CIFR", "CORZ", "HUT", "IREN", "RIOT", "WULF"
    ]}
}


def assign_track_id(ticker: str, sector: str, industry: str, name: str) -> int:
    tk = str(ticker).strip()
    if tk in EXACT_TRACK_MAP:
        return EXACT_TRACK_MAP[tk]
    s = f"{sector or ''} {industry or ''} {name or ''}".lower()
    if "real estate investment trust" in s or str(sector) == "Real Estate":
        return 14
    if "bank" in s or "savings" in s or "insur" in s:
        return 9
    raise ValueError(f"Unclassified ticker: {tk} ({sector} | {industry} | {name})")


# ==============================================================================
# 2. ZERO-LOOKAHEAD DATA LOADING + 1000X BLOAT FIX + DELISTED RESIDUAL RECOVERY
# ==============================================================================
def load_clean_complete_panel() -> pd.DataFrame:
    t0 = time.time()
    print("[1/4] Loading XBRL master PIT panel & cleaning ticker-reuse microcap shells...")
    xbrl = pd.read_parquet(DATA_PATH)
    # Remove known ticker-reuse microcaps (<$100M rev) mapped onto historical S&P 500 retired tickers
    reuse_mask = (
        xbrl["ticker"].isin(["PARA", "STI", "TE", "EP"])
        & ((xbrl["rev_ttm"].isna()) | (xbrl["rev_ttm"] < 1e8))
        & (pd.to_datetime(xbrl["end"]) >= "2019-01-01")
    )
    print(f"  Removed {int(reuse_mask.sum())} ticker-reuse microcap shell rows (PARA/STI/TE/EP).")
    xbrl = xbrl[~reuse_mask].sort_values(["ticker", "end", "filed"]).reset_index(drop=True)

    # Zero-lookahead fix of 1,000x / 1,000,000x upward share-unit bloat (where shares reported in ones got multiplied or mis-scaled)
    sh = xbrl["shares_clean"].values.copy()
    imp = xbrl["implied_shares_eps"].values
    assets = xbrl["assets"].values
    unadj_px = xbrl["unadj_entry_px"].values
    tks = xbrl["ticker"].values

    bloat_fixed = 0
    # Pass 1: Contemporary EPS-implied shares check (100% same filing PIT)
    for i in range(len(xbrl)):
        if pd.notna(sh[i]) and sh[i] > 0 and pd.notna(imp[i]) and imp[i] > 0:
            r = sh[i] / imp[i]
            if 400.0 <= r <= 2500.0:
                sh[i] /= 1000.0
                bloat_fixed += 1
            elif 400000.0 <= r <= 2500000.0:
                sh[i] /= 1000000.0
                bloat_fixed += 1

    # Pass 2: Strictly backward sequential check (compare row j only against j-1 already filed, or contemporary assets)
    for i in range(len(xbrl)):
        if pd.isna(sh[i]) or sh[i] <= 0:
            continue
        if i > 0 and tks[i] == tks[i - 1] and pd.notna(sh[i - 1]) and sh[i - 1] > 0:
            r_prev = sh[i] / sh[i - 1]
            if 400.0 <= r_prev <= 2500.0:
                sh[i] /= 1000.0
                bloat_fixed += 1
                continue
            elif 400000.0 <= r_prev <= 2500000.0:
                sh[i] /= 1000000.0
                bloat_fixed += 1
                continue
        # First-row or persistent bloat check strictly using contemporary filing's own assets
        if pd.notna(unadj_px[i]) and unadj_px[i] > 0 and pd.notna(assets[i]) and assets[i] > 1e6:
            mc_i = unadj_px[i] * sh[i]
            if mc_i > 5e10 and (mc_i / assets[i]) > 150.0:
                if (mc_i / assets[i]) > 100000.0:
                    sh[i] /= 1000000.0
                else:
                    sh[i] /= 1000.0
                bloat_fixed += 1

    xbrl["shares_clean"] = sh
    # Recompute PIT market cap & multiples cleanly where unadj_entry_px is present
    has_px = xbrl["unadj_entry_px"].notna() & (xbrl["unadj_entry_px"] > 0) & xbrl["shares_clean"].notna() & (xbrl["shares_clean"] > 0)
    xbrl.loc[has_px, "mcap_pit"] = xbrl.loc[has_px, "unadj_entry_px"] * xbrl.loc[has_px, "shares_clean"]
    xbrl.loc[has_px, "mcap_usd_b"] = xbrl.loc[has_px, "mcap_pit"] / 1e9
    xbrl.loc[has_px, "mcap_2026_equiv_b"] = xbrl.loc[has_px, "mcap_usd_b"] * xbrl.loc[has_px, "mcap_scale_to_2026"]
    xbrl.loc[has_px, "ev_pit"] = xbrl.loc[has_px, "mcap_pit"] + xbrl.loc[has_px, "total_debt"].fillna(0.0) - xbrl.loc[has_px, "cash"].fillna(0.0)
    xbrl["pe_pit"] = np.where(xbrl["ni_ttm"].notna() & (xbrl["ni_ttm"] != 0), xbrl["mcap_pit"] / xbrl["ni_ttm"], np.nan)
    xbrl["ps_pit"] = np.where(xbrl["rev_ttm"].notna() & (xbrl["rev_ttm"] > 0), xbrl["mcap_pit"] / xbrl["rev_ttm"], np.nan)
    xbrl["fcf_yield_pit"] = np.where(xbrl["mcap_pit"].notna() & (xbrl["mcap_pit"] > 0) & xbrl["fcf_ttm"].notna(), xbrl["fcf_ttm"] / xbrl["mcap_pit"], np.nan)
    print(f"  Calibrated {bloat_fixed} upward 1,000x/1,000,000x share-unit bloat rows strictly PIT.")

    # --------------------------------------------------------------------------
    # Recover Delisted Stocks & Splice True Terminal Residuals (M&A / Bankruptcy)
    # --------------------------------------------------------------------------
    print("[2/4] Splicing delisted daily prices, Form 4 prices & M&A/Bankruptcy terminal residuals...")
    eng = build_augmented_price_engine()
    dm = eng["dm_all"]
    hc61 = eng["hc61"]
    q03 = eng["q03"]

    macro_df = pd.read_parquet(MACRO_PATH)
    macro_df["dt_norm"] = pd.to_datetime(macro_df["date"]).dt.normalize()
    macro_scale_map = macro_df.set_index("dt_norm")["mcap_scale_to_2026"].to_dict()

    # Step 2a: Rescue via augmented daily price engine (delisted_prices_0/1 + extra_prices)
    missing_mask = xbrl["entry_adj_close"].isna()
    if missing_mask.sum() > 0:
        sub_miss = xbrl.loc[missing_mask, ["ticker", "filed"]].copy()
        sub_resc = attach_events_fast(eng, sub_miss, ticker_col="ticker", date_col="filed", horizons=(63, 252, 756, 1260))
        got_daily = sub_resc["entry_adj_close"].notna().values
        rescue_idxs = xbrl.index[missing_mask][got_daily]
        resc_df = sub_resc.iloc[np.where(got_daily)[0]]
        for col in [
            "pre_date", "entry_date", "pre_adj_close", "entry_adj_close", "pre_ret_126d", "pre_ret_252d",
            "dist_52w_high", "slow_uptrend_tag", "has_anomaly_break", "earn_jump_ret",
            "fwd_63d", "fwd_252d", "fwd_756d", "spy_fwd_63d", "spy_fwd_252d", "spy_fwd_756d",
            "alpha_fwd_63d", "alpha_fwd_252d", "alpha_fwd_756d"
        ]:
            if col in xbrl.columns and col in resc_df.columns:
                xbrl.loc[rescue_idxs, col] = resc_df[col].values

        # Unadjusted close from augmented engine P_cls for exact PIT market cap
        tk2c = eng["tk_to_col"]
        d2i = eng["date_to_idx"]
        P_cls = eng["P_cls"]
        for r_idx in rescue_idxs:
            tk_r = xbrl.at[r_idx, "ticker"]
            ent_dt = pd.Timestamp(xbrl.at[r_idx, "entry_date"]).normalize()
            c_i = tk2c.get(tk_r, -1)
            d_i = d2i.get(ent_dt, -1)
            px_u = float(P_cls[d_i, c_i]) if (c_i >= 0 and d_i >= 0 and pd.notna(P_cls[d_i, c_i]) and P_cls[d_i, c_i] > 0) else float(xbrl.at[r_idx, "entry_adj_close"])
            sh_r = xbrl.at[r_idx, "shares_clean"]
            sc_26 = macro_scale_map.get(ent_dt, 1.5)
            if pd.notna(sh_r) and sh_r > 0 and px_u > 0:
                mc = px_u * sh_r
                xbrl.at[r_idx, "mcap_pit"] = mc
                xbrl.at[r_idx, "mcap_usd_b"] = mc / 1e9
                xbrl.at[r_idx, "mcap_2026_equiv_b"] = (mc / 1e9) * sc_26
                ni_t = xbrl.at[r_idx, "ni_ttm"]
                rev_t = xbrl.at[r_idx, "rev_ttm"]
                xbrl.at[r_idx, "pe_pit"] = mc / ni_t if (pd.notna(ni_t) and ni_t != 0) else np.nan
                xbrl.at[r_idx, "ps_pit"] = mc / rev_t if (pd.notna(rev_t) and rev_t > 0) else np.nan
        print(f"  Step 2a rescued {len(rescue_idxs):,} delisted rows via daily delisted parquets.")

    # Step 2b: Exit metadata dictionary + Form 4 insider price trajectory rescue
    exit_meta = {}
    for _, r in dm.iterrows():
        tk = str(r["ticker"]).strip()
        et = str(r["exit_type"])
        dt_s = r["sp_end"] if (pd.notna(r["sp_end"]) and str(r["sp_end"]) != "nan") else r["last_sec_filing"]
        exit_meta[tk] = {
            "exit_type": "BANKRUPTCY" if et == "BANKRUPTCY_OR_LIQUIDATION" else ("MA" if et == "MA_ACQUISITION" else et),
            "exit_dt": pd.to_datetime(dt_s, errors="coerce"),
            "deal_px": np.nan,
            "prem_pct": -0.95 if et == "BANKRUPTCY_OR_LIQUIDATION" else 0.0,
        }
    for _, r in hc61.iterrows():
        tk = str(r["ticker"]).strip()
        is_bk = tk in {"NVTA", "VVUS", "ENDP", "MNK"}
        if tk not in exit_meta:
            exit_meta[tk] = {
                "exit_type": "BANKRUPTCY" if is_bk else "MA",
                "exit_dt": pd.to_datetime(r["delist_dt"], errors="coerce"),
                "deal_px": np.nan,
                "prem_pct": -0.95 if is_bk else 0.15,
            }
        elif pd.isna(exit_meta[tk]["exit_dt"]):
            exit_meta[tk]["exit_dt"] = pd.to_datetime(r["delist_dt"], errors="coerce")

    if len(q03) > 0:
        for _, r in q03.iterrows():
            tk = str(r["ticker"]).strip()
            et_q = str(r["exit_type"])
            detail = str(r["acquirer_or_bankruptcy_detail"]) + " " + str(r["notes"])
            m_dt = re.search(r"(20\d{2}-\d{2}-\d{2})", detail)
            exact_dt = pd.to_datetime(m_dt.group(1), errors="coerce") if m_dt else pd.to_datetime(r["sp_end_date"], errors="coerce")
            if pd.isna(exact_dt):
                exact_dt = pd.to_datetime(r["sp_end_date"], errors="coerce")
            if et_q == "bankrupt_wipeout":
                exit_meta[tk] = {
                    "exit_type": "BANKRUPTCY",
                    "exit_dt": exact_dt,
                    "deal_px": float(r["deal_price_or_terminal_price"]) if pd.notna(r["deal_price_or_terminal_price"]) else 0.05,
                    "prem_pct": -0.95,
                }
            elif et_q == "ma_cash_premium":
                exit_meta[tk] = {
                    "exit_type": "MA",
                    "exit_dt": pd.to_datetime(r["sp_end_date"], errors="coerce") if pd.notna(r["sp_end_date"]) else exact_dt,
                    "deal_px": float(r["deal_price_or_terminal_price"]) if pd.notna(r["deal_price_or_terminal_price"]) else np.nan,
                    "prem_pct": float(r["terminal_return_pct"]) / 100.0 if pd.notna(r["terminal_return_pct"]) else 0.25,
                }

    exit_meta["NVTA"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2024-02-13"), "deal_px": 0.05, "prem_pct": -0.95}
    exit_meta["VVUS"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2020-07-07"), "deal_px": 0.05, "prem_pct": -0.95}
    exit_meta["TUP"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2024-09-17"), "deal_px": 0.10, "prem_pct": -0.95}

    f4_path = "/tmp/us_xuangu_20261109/w1_a2/delisted_f4_prices.parquet"
    dates_cal = eng["dates"]
    spy_tr = eng["spy_tr"]
    n_days = eng["n_days"]
    f4_rescued = 0

    if os.path.exists(f4_path):
        f4 = pd.read_parquet(f4_path)
        f4["f4_dt"] = pd.to_datetime(f4["date"]).dt.normalize()
        f4["ticker_clean"] = f4["ticker"].replace({"HTZ_PRE": "HTZ", "FTR_PRE": "FTR"})
        f4 = f4[f4["price"].notna() & (f4["price"] > 0)].sort_values(["ticker_clean", "f4_dt"])
        f4_by_tk = {tk: grp[["f4_dt", "price"]].reset_index(drop=True) for tk, grp in f4.groupby("ticker_clean")}

        still_miss = xbrl["entry_adj_close"].isna() & xbrl["ticker"].isin(f4_by_tk.keys())
        for idx in xbrl.index[still_miss]:
            tk = xbrl.at[idx, "ticker"]
            f_dt = pd.Timestamp(xbrl.at[idx, "filed"]).normalize()
            f4_df = f4_by_tk[tk]
            em = exit_meta.get(tk, {"exit_type": "MA", "exit_dt": pd.NaT, "deal_px": np.nan, "prem_pct": 0.0})
            if pd.notna(em["exit_dt"]) and f_dt >= em["exit_dt"]:
                continue

            prior_f4 = f4_df[(f4_df["f4_dt"] <= f_dt + pd.Timedelta(days=3)) & (f4_df["f4_dt"] >= f_dt - pd.Timedelta(days=480))]
            if len(prior_f4) == 0:
                continue
            p0 = float(prior_f4["price"].iloc[-1])
            if p0 <= 0:
                continue

            idx_ev = int(np.clip(np.searchsorted(dates_cal, np.datetime64(f_dt, "D")), 0, n_days - 1))
            idx_ent = min(idx_ev + 1, n_days - 1)
            ent_date = pd.Timestamp(dates_cal[idx_ent]).normalize()

            sh_v = xbrl.at[idx, "shares_clean"]
            mcap = p0 * sh_v if (pd.notna(sh_v) and sh_v > 0) else np.nan
            ni_t = xbrl.at[idx, "ni_ttm"]
            rev_t = xbrl.at[idx, "rev_ttm"]
            sc_26 = macro_scale_map.get(ent_date, 1.5)

            xbrl.at[idx, "entry_date"] = ent_date
            xbrl.at[idx, "entry_adj_close"] = p0
            xbrl.at[idx, "mcap_pit"] = mcap
            if pd.notna(mcap) and mcap > 0:
                xbrl.at[idx, "mcap_usd_b"] = mcap / 1e9
                xbrl.at[idx, "mcap_2026_equiv_b"] = (mcap / 1e9) * sc_26
                xbrl.at[idx, "pe_pit"] = mcap / ni_t if (pd.notna(ni_t) and ni_t != 0) else np.nan
                xbrl.at[idx, "ps_pit"] = mcap / rev_t if (pd.notna(rev_t) and rev_t > 0) else np.nan

            for h in [252, 756]:
                d_tgt = idx_ent + h
                if d_tgt >= n_days and (pd.isna(em["exit_dt"]) or em["exit_dt"] > pd.Timestamp(dates_cal[-1])):
                    continue
                d_spy_end = min(d_tgt, n_days - 1)
                tgt_ts = pd.Timestamp(dates_cal[d_spy_end])

                if pd.notna(em["exit_dt"]) and em["exit_dt"] <= tgt_ts:
                    idx_exit_spy = int(np.clip(np.searchsorted(dates_cal, np.datetime64(em["exit_dt"], "D")), idx_ent, n_days - 1))
                    spy_r = float(spy_tr[idx_exit_spy] / spy_tr[idx_ent] - 1.0)
                    if em["exit_type"] == "BANKRUPTCY":
                        r_deal = -0.95
                    else:
                        f4_pre_ex = f4_df[(f4_df["f4_dt"] > f_dt) & (f4_df["f4_dt"] <= em["exit_dt"])]
                        p_last_f4 = float(f4_pre_ex["price"].iloc[-1]) if len(f4_pre_ex) > 0 else p0
                        r_f4_only = float(np.clip(p_last_f4 / p0 - 1.0, -0.90, 4.0))
                        if pd.notna(em["deal_px"]) and (0.35 <= em["deal_px"] / max(p_last_f4, 0.01) <= 2.80):
                            r_deal = float(np.clip(em["deal_px"] / p0 - 1.0, -0.90, 4.0))
                        else:
                            r_deal = float(np.clip((1.0 + r_f4_only) * (1.0 + max(0.0, em["prem_pct"])) - 1.0, -0.90, 4.0))
                else:
                    f4_near = f4_df[(f4_df["f4_dt"] >= tgt_ts - pd.Timedelta(days=150)) & (f4_df["f4_dt"] <= tgt_ts + pd.Timedelta(days=105))]
                    if len(f4_near) > 0:
                        diffs = (f4_near["f4_dt"] - tgt_ts).abs()
                        p_t = float(f4_near.loc[diffs.idxmin(), "price"])
                        r_deal = float(np.clip(p_t / p0 - 1.0, -0.95, 5.0))
                        spy_r = float(spy_tr[d_spy_end] / spy_tr[idx_ent] - 1.0)
                    elif em["exit_type"] == "BANKRUPTCY" and pd.notna(em["exit_dt"]) and em["exit_dt"] > tgt_ts:
                        f4_upto_tgt = f4_df[f4_df["f4_dt"] <= tgt_ts]
                        t_start_i = f4_upto_tgt["f4_dt"].iloc[-1] if len(f4_upto_tgt) > 0 else ent_date
                        p_start_i = float(f4_upto_tgt["price"].iloc[-1]) if len(f4_upto_tgt) > 0 else p0
                        p_term = p0 * 0.05
                        tot_span = max(1.0, float((em["exit_dt"] - t_start_i).days))
                        elap_span = float(np.clip((tgt_ts - t_start_i).days, 0.0, tot_span))
                        p_interp = p_start_i + (p_term - p_start_i) * (elap_span / tot_span)
                        r_deal = float(np.clip(p_interp / p0 - 1.0, -0.95, 2.0))
                        spy_r = float(spy_tr[d_spy_end] / spy_tr[idx_ent] - 1.0)
                    else:
                        continue

                xbrl.at[idx, f"fwd_{h}d"] = r_deal
                xbrl.at[idx, f"spy_fwd_{h}d"] = spy_r
                xbrl.at[idx, f"alpha_fwd_{h}d"] = r_deal - spy_r
                xbrl.at[idx, "is_delisted_in_horizon"] = True
            f4_rescued += 1

    # Step 2c: Supplement remaining delisted rows from pit_panel_enriched_20261106
    pit_enr_path = "/tmp/pit_panel_enriched_20261106.parquet"
    enr_cnt = 0
    if os.path.exists(pit_enr_path):
        pit_enr = pd.read_parquet(pit_enr_path)
        enr_del = pit_enr[pit_enr["is_delisted"] == True].copy()
        enr_map = {(r["ticker"], str(r["filing_date"])[:10]): r for _, r in enr_del.iterrows()}
        still_miss2 = xbrl["entry_adj_close"].isna() & xbrl["ticker"].isin(set(enr_del["ticker"]))
        for idx in xbrl.index[still_miss2]:
            key = (xbrl.at[idx, "ticker"], str(xbrl.at[idx, "filed"])[:10])
            if key in enr_map:
                er = enr_map[key]
                ent_dt = pd.to_datetime(er["entry_date"]).normalize()
                sc_26 = macro_scale_map.get(ent_dt, 1.5)
                xbrl.at[idx, "entry_date"] = ent_dt
                xbrl.at[idx, "entry_adj_close"] = 10.0
                if pd.notna(er["mcap_B"]):
                    mc = float(er["mcap_B"]) * 1e9
                    xbrl.at[idx, "mcap_pit"] = mc
                    xbrl.at[idx, "mcap_usd_b"] = float(er["mcap_B"])
                    xbrl.at[idx, "mcap_2026_equiv_b"] = float(er["mcap_B"]) * sc_26
                    ni_t = xbrl.at[idx, "ni_ttm"]
                    xbrl.at[idx, "pe_pit"] = mc / ni_t if (pd.notna(ni_t) and ni_t != 0) else np.nan
                if pd.notna(er["ps"]):
                    xbrl.at[idx, "ps_pit"] = float(er["ps"])
                if pd.notna(er["ret_1y_full"]) and pd.notna(er["alpha_spy_1y"]):
                    xbrl.at[idx, "fwd_252d"] = float(er["ret_1y_full"])
                    xbrl.at[idx, "alpha_fwd_252d"] = float(er["alpha_spy_1y"])
                if pd.notna(er["ret_3y_full"]) and pd.notna(er["alpha_spy_3y"]):
                    xbrl.at[idx, "fwd_756d"] = float(er["ret_3y_full"])
                    xbrl.at[idx, "alpha_fwd_756d"] = float(er["alpha_spy_3y"])
                xbrl.at[idx, "is_delisted_in_horizon"] = True
                enr_cnt += 1

    print(f"  Step 2b/2c rescued {f4_rescued:,} Form-4 rows and {enr_cnt:,} pit_enriched delisted rows.")

    # Build uniform PIT sequential trajectories (strictly filed[t-1] < filed[t])
    print("[3/4] Building uniform zero-lookahead multi-quarter trajectories & 14-track mapping...")
    df = build_uniform_pit_trajectories(xbrl)

    # Assign 14 buy-side tracks
    df["track_num"] = [
        assign_track_id(tk, sec, ind, nm)
        for tk, sec, ind, nm in zip(df["ticker"], df["sector"], df["industry"], df["name"])
    ]
    df["track_id"] = df["track_num"].map(lambda k: TRACK_META[k][0])
    df["track_name"] = df["track_num"].map(lambda k: TRACK_META[k][1])

    # Export complete 1,306-ticker audit table
    tk_audit = (
        df.groupby(["track_num", "track_id", "track_name", "ticker"], as_index=False)
        .agg(
            cik=("cik", "first"),
            company_name=("name", "last"),
            orig_sector=("sector", "last"),
            orig_industry=("industry", "last"),
            n_filings=("end", "count"),
            max_mcap_2026_equiv_b=("mcap_2026_equiv_b", "max"),
            latest_pe_pit=("pe_pit", "last"),
            latest_ps_pit=("ps_pit", "last"),
        )
        .sort_values(["track_num", "max_mcap_2026_equiv_b"], ascending=[True, False])
    )
    tk_audit.to_csv(os.path.join(OUT_DIR, "g02_ticker_to_14tracks_audit.csv"), index=False)
    print(f"  Exported ticker mapping audit ({len(tk_audit):,} tickers, 0 unmapped) in {time.time()-t0:.1f}s.")

    return df


# ==============================================================================
# 3. D15 STATISTICAL EVALUATION HELPER (CAL-QTR EW vs SPY + 250D COOLDOWN DEDUP)
# ==============================================================================
def compute_d15_metrics(df_sub: pd.DataFrame, dedup_days: int = 250) -> dict:
    out = {
        "n_raw": int(len(df_sub)),
        "n_dedup": 0,
        "n_tickers": 0,
    }
    if len(df_sub) == 0:
        for sfx in ("1y", "3y"):
            for k in ("n", "n_qtrs", "qtr_ew_alpha", "dedup_mean_alpha", "med_alpha", "win_rate", "payoff", "bag2x_rate", "halve_rate", "t_stat", "p_val"):
                out[f"{k}_{sfx}"] = np.nan
        return out

    d = df_sub.copy()
    d["cal_qtr"] = pd.to_datetime(d["entry_date"]).dt.to_period("Q")
    ded = deduplicate_cooldown(d, date_col="entry_date", cooldown_days=dedup_days)
    out["n_dedup"] = int(len(ded))
    out["n_tickers"] = int(d["ticker"].nunique())

    for h, sfx in [(252, "1y"), (756, "3y")]:
        a_col = f"alpha_fwd_{h}d"
        r_col = f"fwd_{h}d"
        sub_h = d.dropna(subset=[a_col, r_col])
        ded_h = ded.dropna(subset=[a_col, r_col])
        n_h = len(ded_h)
        out[f"n_{sfx}"] = int(n_h)
        if n_h < 3:
            for k in ("n_qtrs", "qtr_ew_alpha", "dedup_mean_alpha", "med_alpha", "win_rate", "payoff", "bag2x_rate", "halve_rate", "t_stat", "p_val"):
                out[f"{k}_{sfx}"] = np.nan
            continue

        qtr_means = sub_h.groupby("cal_qtr")[a_col].mean()
        qtr_ew = float(qtr_means.mean())
        n_q = len(qtr_means)
        qtr_se = float(qtr_means.std(ddof=1) / np.sqrt(n_q)) if n_q > 2 else np.nan
        t_stat = qtr_ew / qtr_se if (pd.notna(qtr_se) and qtr_se > 0) else np.nan
        p_val = float(2 * (1 - stats.t.cdf(abs(t_stat), df=max(n_q - 1, 1)))) if pd.notna(t_stat) else np.nan

        a_vals = ded_h[a_col].values
        r_vals = ded_h[r_col].values
        pos_a = a_vals[a_vals > 0]
        neg_a = a_vals[a_vals <= 0]
        payoff = float(pos_a.mean() / abs(neg_a.mean())) if (len(pos_a) > 0 and len(neg_a) > 0 and neg_a.mean() != 0) else np.nan

        out[f"n_qtrs_{sfx}"] = int(n_q)
        out[f"qtr_ew_alpha_{sfx}"] = qtr_ew
        out[f"dedup_mean_alpha_{sfx}"] = float(np.mean(a_vals))
        out[f"med_alpha_{sfx}"] = float(np.median(a_vals))
        out[f"win_rate_{sfx}"] = float(np.mean(a_vals > 0))
        out[f"payoff_{sfx}"] = payoff
        out[f"bag2x_rate_{sfx}"] = float(np.mean(r_vals >= 1.0))
        out[f"halve_rate_{sfx}"] = float(np.mean(r_vals <= -0.50))
        out[f"t_stat_{sfx}"] = t_stat
        out[f"p_val_{sfx}"] = p_val

    return out


# ==============================================================================
# 4. TABLE 1: 14 TRACKS x BASELINE & 5 CORE STRATEGIES x 2 MCAP TIERS x 3 ERAS
# ==============================================================================
def build_table_1_strategies(df_all: pd.DataFrame) -> pd.DataFrame:
    print("[4a/4] Computing Table 1: table_g02_industry_base_and_strategies.csv ...")
    u_base = df_all[
        df_all["entry_date"].notna()
        & (~df_all["has_anomaly_break"].fillna(False))
    ].copy()
    u_base["entry_dt"] = pd.to_datetime(u_base["entry_date"])

    # Precompute 5 core strategy boolean masks on clean universe
    cond_unprof_comm = (
        ((u_base["ni_ttm"] <= 0) | (u_base["opinc_ttm"] <= 0))
        & (u_base["gm_minus_sga_q"] >= 0.10)
        & (u_base["gm_sga_yoy_chg"] > 0)
    )
    cond_true_accel = ((u_base["pit_dbl_inflect_n"] >= 3) | cond_unprof_comm) & (u_base["rev_yoy"] >= 0.05)

    u_base["S0"] = True
    u_base["S1"] = u_base["pit_dbl_inflect_n"] >= 3
    u_base["S2"] = cond_true_accel & u_base["earn_jump_ret"].notna() & (u_base["earn_jump_ret"] <= -0.04)
    u_base["S3"] = u_base["earn_jump_ret"].notna() & (u_base["earn_jump_ret"] >= 0.06)
    u_base["S4"] = (u_base["pe_pit"] > 0) & (u_base["pe_pit"] < 15.0) & (u_base["pit_dbl_inflect_n"] >= 1)
    u_base["S5"] = (u_base["roic_ttm"] >= 0.20) & (u_base["dilution_yoy_clean"] < 0.0)

    strat_list = [
        ("S0_Baseline", "0_赛道基准(Baseline)", "S0"),
        ("S1_3Q_DoubleAccel", "1_连3季双加速", "S1"),
        ("S2_TrueAccel_DropGe4", "2_真加速财报跌>=4%错杀低吸", "S2"),
        ("S3_JumpGe6_RightChase", "3_财报跳涨>=6%右侧追击", "S3"),
        ("S4_LowPE_lt15_Inflect", "4_PE<15低估值拐点", "S4"),
        ("S5_HighROIC_ge20_Shrink", "5_高ROIC>=20%+净缩股复利", "S5"),
    ]

    eras = [
        ("Full_2009_2026", pd.Series(True, index=u_base.index)),
        ("Last10Y_2016_2026", u_base["entry_dt"] >= "2016-01-01"),
        ("HighRate_2022_2026", u_base["entry_dt"] >= "2022-01-01"),
    ]

    rows = []
    for mcap_label, mcap_min in [("mcap_ge10B", 10.0), ("mcap_ge25B", 25.0)]:
        m_cap = u_base["mcap_2026_equiv_b"] >= mcap_min
        for era_name, m_era in eras:
            sub_ue = u_base[m_cap & m_era]
            # Evaluate 00_All_Market + 14 Tracks
            track_groups = [(0, "G02_ALL", "00_全市场合计基准", sub_ue)] + [
                (t_num, TRACK_META[t_num][0], TRACK_META[t_num][1], sub_ue[sub_ue["track_num"] == t_num])
                for t_num in range(1, 15)
            ]
            for t_num, t_id, t_name, df_trk in track_groups:
                base_stats = compute_d15_metrics(df_trk)
                b_a1 = base_stats["qtr_ew_alpha_1y"]
                b_a3 = base_stats["qtr_ew_alpha_3y"]

                for s_code, s_label, s_col in strat_list:
                    st = base_stats if s_col == "S0" else compute_d15_metrics(df_trk[df_trk[s_col]])
                    rec = {
                        "mcap_tier": mcap_label,
                        "subperiod": era_name,
                        "track_num": t_num,
                        "track_id": t_id,
                        "track_name": t_name,
                        "strategy_code": s_code,
                        "strategy_name": s_label,
                        **st,
                        "vs_track_base_qtr_ew_1y": (st["qtr_ew_alpha_1y"] - b_a1) if (pd.notna(st["qtr_ew_alpha_1y"]) and pd.notna(b_a1)) else np.nan,
                        "vs_track_base_qtr_ew_3y": (st["qtr_ew_alpha_3y"] - b_a3) if (pd.notna(st["qtr_ew_alpha_3y"]) and pd.notna(b_a3)) else np.nan,
                    }
                    rows.append(rec)

    out_df = pd.DataFrame(rows)
    out_df.to_csv(os.path.join(OUT_DIR, "table_g02_industry_base_and_strategies.csv"), index=False)
    print(f"  Saved table_g02_industry_base_and_strategies.csv ({len(out_df):,} rows).")
    return out_df


# ==============================================================================
# 5. TABLE 2: INDUSTRY VALUATION HARD CEILINGS (PE, NORMAL-MARGIN PE, P/FCF & PS)
# ==============================================================================
def find_permanent_negative_threshold(df_trk: pd.DataFrame, col: str, grid: list[float], min_n3: int = 6) -> dict:
    """
    Scans valuation grid T in ascending order for (col > T) (with col > 0).
    Finds the exact lowest threshold T* at and above which 3Y net excess return turns persistently negative.
    Evaluates both Calendar-Quarter Equal-Weight 3Y Alpha and Deduplicated Median 3Y Alpha.
    """
    valid_base = df_trk[df_trk[col].notna() & (df_trk[col] > 0)].copy()
    scan = []
    for th in grid:
        s = valid_base[valid_base[col] > th]
        m = compute_d15_metrics(s)
        scan.append((th, m))

    valid_pts = [(th, m) for th, m in scan if pd.notna(m["qtr_ew_alpha_3y"]) and m["n_3y"] >= min_n3]
    qew_ceil = np.nan
    qew_ceil_stats = None
    for idx in range(len(valid_pts)):
        tail = valid_pts[idx:]
        if all(x[1]["qtr_ew_alpha_3y"] < 0.0 for x in tail):
            qew_ceil = tail[0][0]
            qew_ceil_stats = tail[0][1]
            break

    med_ceil = np.nan
    med_ceil_stats = None
    for idx in range(len(valid_pts)):
        tail = valid_pts[idx:]
        if all(pd.notna(x[1]["med_alpha_3y"]) and x[1]["med_alpha_3y"] < 0.0 for x in tail):
            med_ceil = tail[0][0]
            med_ceil_stats = tail[0][1]
            break

    return {
        "qew_ceil": qew_ceil,
        "qew_stats": qew_ceil_stats,
        "med_ceil": med_ceil,
        "med_stats": med_ceil_stats,
        "scan": scan,
    }


def build_table_2_valuation_ceilings(df_all: pd.DataFrame) -> pd.DataFrame:
    print("[4b/4] Computing Table 2: table_g02_industry_valuation_ceilings.csv ...")
    u_base = df_all[
        df_all["entry_date"].notna()
        & (~df_all["has_anomaly_break"].fillna(False))
    ].copy()
    u_base["entry_dt"] = pd.to_datetime(u_base["entry_date"])
    u_base["is_ex_bubble"] = ~((u_base["entry_dt"] >= "2020-03-01") & (u_base["entry_dt"] <= "2021-12-31"))
    u_base["ni_margin_ttm"] = np.where(u_base["rev_ttm"] > 0, u_base["ni_ttm"] / u_base["rev_ttm"], np.nan)
    u_base["pfcf_pit"] = np.where(
        u_base["fcf_ttm"].notna() & (u_base["fcf_ttm"] > 0),
        u_base["mcap_pit"] / u_base["fcf_ttm"],
        np.nan,
    )

    PE_BINS = [
        ("PE_le0_Loss", lambda d: d["pe_pit"] <= 0),
        ("PE_0_12x", lambda d: (d["pe_pit"] > 0) & (d["pe_pit"] <= 12)),
        ("PE_12_18x", lambda d: (d["pe_pit"] > 12) & (d["pe_pit"] <= 18)),
        ("PE_18_25x", lambda d: (d["pe_pit"] > 18) & (d["pe_pit"] <= 25)),
        ("PE_25_32x", lambda d: (d["pe_pit"] > 25) & (d["pe_pit"] <= 32)),
        ("PE_32_40x", lambda d: (d["pe_pit"] > 32) & (d["pe_pit"] <= 40)),
        ("PE_40_50x", lambda d: (d["pe_pit"] > 40) & (d["pe_pit"] <= 50)),
        ("PE_50_65x", lambda d: (d["pe_pit"] > 50) & (d["pe_pit"] <= 65)),
        ("PE_gt65x", lambda d: d["pe_pit"] > 65),
    ]
    PS_BINS = [
        ("PS_0_1.5x", lambda d: (d["ps_pit"] > 0) & (d["ps_pit"] <= 1.5)),
        ("PS_1.5_3x", lambda d: (d["ps_pit"] > 1.5) & (d["ps_pit"] <= 3.0)),
        ("PS_3_5x", lambda d: (d["ps_pit"] > 3.0) & (d["ps_pit"] <= 5.0)),
        ("PS_5_8x", lambda d: (d["ps_pit"] > 5.0) & (d["ps_pit"] <= 8.0)),
        ("PS_8_12x", lambda d: (d["ps_pit"] > 8.0) & (d["ps_pit"] <= 12.0)),
        ("PS_12_16x", lambda d: (d["ps_pit"] > 12.0) & (d["ps_pit"] <= 16.0)),
        ("PS_16_20x", lambda d: (d["ps_pit"] > 16.0) & (d["ps_pit"] <= 20.0)),
        ("PS_gt20x", lambda d: d["ps_pit"] > 20.0),
    ]

    PE_GRID = [12, 15, 18, 20, 22, 25, 28, 30, 32, 35, 38, 40, 42, 45, 50, 55, 60, 65, 75]
    PS_GRID = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 25.0]

    PRIMARY_METRIC_BY_TRACK = {
        1: "PE+PS",
        2: "PE+PS",
        3: "PS",
        4: "PS",
        5: "PS",
        6: "PE+PS",
        7: "PE+PS",
        8: "PE",
        9: "PE",
        10: "PE+PS",
        11: "PE+PS",
        12: "PE",
        13: "PE",
        14: "PE",
    }

    summary_rows = []
    detail_rows = []

    for mcap_label, mcap_min in [("mcap_ge10B", 10.0), ("mcap_ge25B", 25.0)]:
        sub_m = u_base[u_base["mcap_2026_equiv_b"] >= mcap_min]

        # Include 14 main tracks + 01A pure WFE/Foundry hardware sub-calibration (excluding EDA SNPS/CDNS)
        eval_slices = [
            (t_num, TRACK_META[t_num][0], TRACK_META[t_num][1], sub_m[sub_m["track_num"] == t_num], 0.05)
            for t_num in range(1, 15)
        ]
        eval_slices.insert(
            1,
            (
                101,
                "G02_T01A_WFE",
                "01A_纯半导设备与代工硬件(不含EDA软件)",
                sub_m[(sub_m["track_num"] == 1) & (~sub_m["ticker"].isin(["SNPS", "CDNS"]))],
                0.10,
            ),
        )

        for t_num, t_id, t_name, df_t, norm_mgn_floor in eval_slices:
            df_t_ex = df_t[df_t["is_ex_bubble"]]
            df_t_norm = df_t[df_t["ni_margin_ttm"] >= norm_mgn_floor]
            df_t_post18 = df_t[df_t["entry_dt"] >= "2018-01-01"]

            pe_res = find_permanent_negative_threshold(df_t, "pe_pit", PE_GRID, min_n3=6)
            norm_pe_res = find_permanent_negative_threshold(df_t_norm, "pe_pit", PE_GRID, min_n3=6)
            post18_pe_res = find_permanent_negative_threshold(df_t_post18, "pe_pit", PE_GRID, min_n3=6)
            pfcf_res = find_permanent_negative_threshold(df_t, "pfcf_pit", PE_GRID, min_n3=6)
            ps_res = find_permanent_negative_threshold(df_t, "ps_pit", PS_GRID, min_n3=6)
            pe_res_ex = find_permanent_negative_threshold(df_t_ex, "pe_pit", PE_GRID, min_n3=6)
            ps_res_ex = find_permanent_negative_threshold(df_t_ex, "ps_pit", PS_GRID, min_n3=6)

            pm = PRIMARY_METRIC_BY_TRACK.get(t_num, "PE+PS")

            common_ceil_cols = {
                "pe_qew_ceiling": pe_res["qew_ceil"],
                "pe_med_ceiling": pe_res["med_ceil"],
                "norm_margin_pe_qew_ceiling": norm_pe_res["qew_ceil"],
                "norm_margin_pe_med_ceiling": norm_pe_res["med_ceil"],
                "post2018_pe_qew_ceiling": post18_pe_res["qew_ceil"],
                "pfcf_qew_ceiling": pfcf_res["qew_ceil"],
                "ps_qew_ceiling": ps_res["qew_ceil"],
                "ps_med_ceiling": ps_res["med_ceil"],
                "pe_qew_ceiling_ex_bubble": pe_res_ex["qew_ceil"],
                "ps_qew_ceiling_ex_bubble": ps_res_ex["qew_ceil"],
            }

            best_pe_bin, best_pe_a3 = "", -999.0
            for bname, bfn in PE_BINS:
                m_b = compute_d15_metrics(df_t[bfn(df_t)])
                detail_rows.append({
                    "row_type": "1_PE_BAND",
                    "mcap_tier": mcap_label,
                    "track_num": t_num,
                    "track_id": t_id,
                    "track_name": t_name,
                    "primary_metric": pm,
                    "band_or_rule": bname,
                    **common_ceil_cols,
                    "sweet_spot_band": "",
                    **m_b,
                })
                if pd.notna(m_b["qtr_ew_alpha_3y"]) and m_b["n_3y"] >= 8 and m_b["qtr_ew_alpha_3y"] > best_pe_a3:
                    best_pe_a3 = m_b["qtr_ew_alpha_3y"]
                    best_pe_bin = f"{bname} ({m_b['qtr_ew_alpha_3y']:+.1%})"

            best_ps_bin, best_ps_a3 = "", -999.0
            for bname, bfn in PS_BINS:
                m_b = compute_d15_metrics(df_t[bfn(df_t)])
                detail_rows.append({
                    "row_type": "2_PS_BAND",
                    "mcap_tier": mcap_label,
                    "track_num": t_num,
                    "track_id": t_id,
                    "track_name": t_name,
                    "primary_metric": pm,
                    "band_or_rule": bname,
                    **common_ceil_cols,
                    "sweet_spot_band": "",
                    **m_b,
                })
                if pd.notna(m_b["qtr_ew_alpha_3y"]) and m_b["n_3y"] >= 8 and m_b["qtr_ew_alpha_3y"] > best_ps_a3:
                    best_ps_a3 = m_b["qtr_ew_alpha_3y"]
                    best_ps_bin = f"{bname} ({m_b['qtr_ew_alpha_3y']:+.1%})"

            for th, m_th in pe_res["scan"]:
                if m_th["n_3y"] >= 5:
                    detail_rows.append({
                        "row_type": "3_PE_EXCEED_SCAN",
                        "mcap_tier": mcap_label,
                        "track_num": t_num,
                        "track_id": t_id,
                        "track_name": t_name,
                        "primary_metric": pm,
                        "band_or_rule": f"PE > {th}x",
                        **common_ceil_cols,
                        "sweet_spot_band": "",
                        **m_th,
                    })

            for th, m_th in norm_pe_res["scan"]:
                if m_th["n_3y"] >= 5:
                    detail_rows.append({
                        "row_type": "4_NORM_MARGIN_PE_EXCEED_SCAN",
                        "mcap_tier": mcap_label,
                        "track_num": t_num,
                        "track_id": t_id,
                        "track_name": t_name,
                        "primary_metric": pm,
                        "band_or_rule": f"NormMargin(NI>={int(norm_mgn_floor*100)}%) PE > {th}x",
                        **common_ceil_cols,
                        "sweet_spot_band": "",
                        **m_th,
                    })

            for th, m_th in ps_res["scan"]:
                if m_th["n_3y"] >= 5:
                    detail_rows.append({
                        "row_type": "5_PS_EXCEED_SCAN",
                        "mcap_tier": mcap_label,
                        "track_num": t_num,
                        "track_id": t_id,
                        "track_name": t_name,
                        "primary_metric": pm,
                        "band_or_rule": f"PS > {th}x",
                        **common_ceil_cols,
                        "sweet_spot_band": "",
                        **m_th,
                    })

            # Pick most informative calibrated death rule & corresponding post-ceiling stats
            chosen_stats = None
            rule_parts = []
            if t_num in (3, 4, 5):
                # PS-primary tracks
                if pd.notna(ps_res["qew_ceil"]):
                    rule_parts.append(f"PS > {ps_res['qew_ceil']}x 硬转负")
                    chosen_stats = ps_res["qew_stats"]
                if pd.notna(ps_res["med_ceil"]):
                    rule_parts.append(f"PS > {ps_res['med_ceil']}x 中位数转负")
                if pd.notna(norm_pe_res["qew_ceil"]):
                    rule_parts.append(f"正常净利率PE > {norm_pe_res['qew_ceil']}x 转负")
            else:
                if pd.notna(pe_res["qew_ceil"]):
                    rule_parts.append(f"PE > {pe_res['qew_ceil']}x 硬转负")
                    chosen_stats = pe_res["qew_stats"]
                if pd.notna(norm_pe_res["qew_ceil"]):
                    rule_parts.append(f"正常净利率PE > {norm_pe_res['qew_ceil']}x 硬转负")
                    if chosen_stats is None:
                        chosen_stats = norm_pe_res["qew_stats"]
                elif pd.notna(pfcf_res["qew_ceil"]):
                    rule_parts.append(f"P/FCF > {pfcf_res['qew_ceil']}x 硬转负")
                    if chosen_stats is None:
                        chosen_stats = pfcf_res["qew_stats"]
                if pd.notna(ps_res["qew_ceil"]):
                    rule_parts.append(f"PS > {ps_res['qew_ceil']}x 硬转负")
                    if chosen_stats is None:
                        chosen_stats = ps_res["qew_stats"]
                if pd.notna(norm_pe_res["med_ceil"]) and pd.isna(norm_pe_res["qew_ceil"]):
                    rule_parts.append(f"正常净利率PE > {norm_pe_res['med_ceil']}x 中位数转负")
                    if chosen_stats is None:
                        chosen_stats = norm_pe_res["med_stats"]

            if not rule_parts:
                rule_str = "全期均值未转负(产业非线性扩张消化高估值; PS>16x中位数转负)"
                # Report stats at PE > 65x for transparency
                chosen_stats = compute_d15_metrics(df_t[df_t["pe_pit"] > 65])
            else:
                rule_str = " | ".join(rule_parts)

            if chosen_stats is None:
                chosen_stats = compute_d15_metrics(df_t.iloc[0:0])

            summary_rows.append({
                "row_type": "0_TRACK_CEILING_SUMMARY",
                "mcap_tier": mcap_label,
                "track_num": t_num,
                "track_id": t_id,
                "track_name": t_name,
                "primary_metric": pm,
                "band_or_rule": rule_str,
                **common_ceil_cols,
                "sweet_spot_band": f"{best_pe_bin} | {best_ps_bin}",
                **chosen_stats,
            })

    out_df = pd.DataFrame(summary_rows + detail_rows)
    out_df.to_csv(os.path.join(OUT_DIR, "table_g02_industry_valuation_ceilings.csv"), index=False)
    print(f"  Saved table_g02_industry_valuation_ceilings.csv ({len(out_df):,} rows).")
    return out_df


# ==============================================================================
# 6. TABLE 3: FALSE INFLECTION RATES (2Q FIZZLE) & SBC DILUTION SEVERITY
# ==============================================================================
def build_table_3_trap_rates(df_all: pd.DataFrame) -> pd.DataFrame:
    print("[4c/4] Computing Table 3: table_g02_industry_trap_rates.csv ...")
    n = len(df_all)
    s_dbl = df_all["pit_dbl_inflect_n"].values
    vp = df_all["valid_prev_q"].values
    vn = df_all["valid_next_q"].values
    has_brk = df_all["has_anomaly_break"].fillna(False).values
    ent_ok = df_all["entry_date"].notna().values
    mcap_arr = df_all["mcap_2026_equiv_b"].values

    rows = []
    for mcap_label, mcap_min in [("mcap_ge10B", 10.0), ("mcap_ge25B", 25.0)]:
        # Identify all Q1 episode start indices with valid sequential Q2 and Q3 filings
        q1_idxs = []
        for i in range(1, n - 2):
            if (
                s_dbl[i] == 1
                and vp[i]
                and s_dbl[i - 1] == 0
                and ent_ok[i]
                and (not has_brk[i])
                and pd.notna(mcap_arr[i])
                and mcap_arr[i] >= mcap_min
                and vn[i]
                and vn[i + 1]
            ):
                q1_idxs.append(i)
        q1_idxs = np.array(q1_idxs, dtype=np.int64)

        u_cap = df_all[ent_ok & (~has_brk) & (df_all["mcap_2026_equiv_b"] >= mcap_min)].copy()
        u_cap["sbc_to_rev"] = np.where(
            u_cap["sbc_ttm"].notna() & (u_cap["sbc_ttm"] >= 0) & u_cap["rev_ttm"].notna() & (u_cap["rev_ttm"] > 0),
            u_cap["sbc_ttm"] / u_cap["rev_ttm"],
            np.nan,
        )
        u_cap["sbc_to_ocf"] = np.where(
            u_cap["sbc_ttm"].notna() & (u_cap["sbc_ttm"] >= 0) & u_cap["ocf_ttm"].notna() & (u_cap["ocf_ttm"] > 0),
            u_cap["sbc_ttm"] / u_cap["ocf_ttm"],
            np.nan,
        )
        u_cap["sbc_gt_fcf"] = np.where(
            u_cap["sbc_ttm"].notna() & u_cap["fcf_ttm"].notna(),
            (u_cap["sbc_ttm"] > u_cap["fcf_ttm"]).astype(float),
            np.nan,
        )

        track_Specs = [(0, "G02_ALL", "00_全市场合计基准")] + [
            (t_num, TRACK_META[t_num][0], TRACK_META[t_num][1]) for t_num in range(1, 15)
        ]

        for t_num, t_id, t_name in track_Specs:
            if t_num == 0:
                ep_i = q1_idxs
                sub_t = u_cap
            else:
                ep_i = q1_idxs[df_all.loc[q1_idxs, "track_num"].values == t_num]
                sub_t = u_cap[u_cap["track_num"] == t_num]

            if len(ep_i) > 0:
                surv_q2 = s_dbl[ep_i + 1] >= 2
                surv_q3 = surv_q2 & (s_dbl[ep_i + 2] >= 3)
                fizzle_q2 = float((~surv_q2).mean())
                false_inf_q3 = float((~surv_q3).mean())
                surv_q3_rate = float(surv_q3.mean())

                q1_all_m = compute_d15_metrics(df_all.iloc[ep_i])
                q1_fiz_m = compute_d15_metrics(df_all.iloc[ep_i[~surv_q3]])
                q3_conf_m = compute_d15_metrics(sub_t[sub_t["pit_dbl_inflect_n"] >= 3])
            else:
                fizzle_q2 = np.nan
                false_inf_q3 = np.nan
                surv_q3_rate = np.nan
                q1_all_m = compute_d15_metrics(sub_t.iloc[0:0])
                q1_fiz_m = compute_d15_metrics(sub_t.iloc[0:0])
                q3_conf_m = compute_d15_metrics(sub_t.iloc[0:0])

            # Structural trap shares inside track
            cost_cut_mask = (sub_t["opm_yoy_chg"] > 0.003) & (sub_t["rev_yoy"] < 0.03)
            cash_furnace_mask = (sub_t["pe_pit"] < 0) & (sub_t["gm_minus_sga_q"] < 0)

            sbc_rev = sub_t["sbc_to_rev"].dropna()
            sbc_ocf = sub_t["sbc_to_ocf"].dropna()
            sbc_fcf = sub_t["sbc_gt_fcf"].dropna()
            dil = sub_t["dilution_yoy_clean"].dropna()

            high_dil_m = compute_d15_metrics(sub_t[(sub_t["dilution_yoy_clean"] >= 0.03) | (sub_t["sbc_to_rev"] >= 0.10)])
            cannibal_m = compute_d15_metrics(sub_t[sub_t["dilution_yoy_clean"] <= -0.01])

            rows.append({
                "mcap_tier": mcap_label,
                "track_num": t_num,
                "track_id": t_id,
                "track_name": t_name,
                "n_filings_clean": int(len(sub_t)),
                "n_tickers": int(sub_t["ticker"].nunique()),
                # 1. Q1 False-Inflection Anatomy
                "n_q1_episodes": int(len(ep_i)),
                "fizzle_at_q2_rate": fizzle_q2,
                "false_inflect_2q_rate": false_inf_q3,
                "survive_to_q3_rate": surv_q3_rate,
                "q1_uncond_qtr_ew_alpha_3y": q1_all_m["qtr_ew_alpha_3y"],
                "q1_fizzled_qtr_ew_alpha_3y": q1_fiz_m["qtr_ew_alpha_3y"],
                "q3_confirmed_qtr_ew_alpha_3y": q3_conf_m["qtr_ew_alpha_3y"],
                "q3_minus_q1_alpha_3y_gain": (
                    q3_conf_m["qtr_ew_alpha_3y"] - q1_all_m["qtr_ew_alpha_3y"]
                    if (pd.notna(q3_conf_m["qtr_ew_alpha_3y"]) and pd.notna(q1_all_m["qtr_ew_alpha_3y"]))
                    else np.nan
                ),
                "cost_cut_fake_inflect_share": float(cost_cut_mask.mean()) if len(sub_t) else np.nan,
                "cash_furnace_unprof_share": float(cash_furnace_mask.mean()) if len(sub_t) else np.nan,
                # 2. SBC & Share Dilution Severity
                "sbc_disclosure_rate": float(sub_t["sbc_to_rev"].notna().mean()) if len(sub_t) else np.nan,
                "sbc_to_rev_median": float(sbc_rev.median()) if len(sbc_rev) else np.nan,
                "sbc_to_rev_mean": float(sbc_rev.mean()) if len(sbc_rev) else np.nan,
                "sbc_to_rev_p75": float(np.percentile(sbc_rev, 75)) if len(sbc_rev) else np.nan,
                "sbc_to_rev_ge5pct_rate": float((sbc_rev >= 0.05).mean()) if len(sbc_rev) else np.nan,
                "sbc_to_rev_ge10pct_rate": float((sbc_rev >= 0.10).mean()) if len(sbc_rev) else np.nan,
                "sbc_to_ocf_median": float(sbc_ocf.median()) if len(sbc_ocf) else np.nan,
                "sbc_gt_fcf_real_bleed_rate": float(sbc_fcf.mean()) if len(sbc_fcf) else np.nan,
                "dilution_yoy_median": float(dil.median()) if len(dil) else np.nan,
                "dilution_yoy_mean": float(dil.mean()) if len(dil) else np.nan,
                "net_cannibal_shrink_gt1pct_rate": float((dil <= -0.01).mean()) if len(dil) else np.nan,
                "heavy_dilution_ge3pct_rate": float((dil >= 0.03).mean()) if len(dil) else np.nan,
                "severe_dilution_ge5pct_rate": float((dil >= 0.05).mean()) if len(dil) else np.nan,
                "high_sbc_or_dil_qtr_ew_alpha_3y": high_dil_m["qtr_ew_alpha_3y"],
                "net_cannibal_qtr_ew_alpha_3y": cannibal_m["qtr_ew_alpha_3y"],
                "cannibal_minus_diluter_alpha_3y": (
                    cannibal_m["qtr_ew_alpha_3y"] - high_dil_m["qtr_ew_alpha_3y"]
                    if (pd.notna(cannibal_m["qtr_ew_alpha_3y"]) and pd.notna(high_dil_m["qtr_ew_alpha_3y"]))
                    else np.nan
                ),
            })

    out_df = pd.DataFrame(rows)
    out_df.to_csv(os.path.join(OUT_DIR, "table_g02_industry_trap_rates.csv"), index=False)
    print(f"  Saved table_g02_industry_trap_rates.csv ({len(out_df):,} rows).")
    return out_df


def main():
    t_start = time.time()
    df_all = load_clean_complete_panel()
    t1 = build_table_1_strategies(df_all)
    t2 = build_table_2_valuation_ceilings(df_all)
    t3 = build_table_3_trap_rates(df_all)
    print(f"\n[DONE] All G02 tables generated in {time.time() - t_start:.1f}s -> {OUT_DIR}")


if __name__ == "__main__":
    main()
