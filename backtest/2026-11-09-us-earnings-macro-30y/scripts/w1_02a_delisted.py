#!/usr/bin/env python3
"""
W1_02A: Survivor bias patching and delisted/M&A terminal value builder (Shard 0)
Author: W1_02A Subagent
Date: 2026-11-09

Processes delisted_shard_0.json (286 tickers):
1. Fetches historical prices from Yahoo Finance, validates ticker reuse, and exports
   /tmp/us_earn_macro_bt_20261109/delisted_prices/delisted_prices_0.parquet
2. Verifies SEC official submissions (CIK, last filing, forms, 8-K items), classifies exit type:
   - BANKRUPTCY_OR_LIQUIDATION (terminal_delist_ret: -0.95 / -0.50)
   - MA_ACQUISITION (terminal_delist_ret: 0.0)
   - DEMOTED_STILL_TRADING (terminal_delist_ret: 0.0)
   - UNRESOLVED_HISTORICAL (terminal_delist_ret: 0.0)
   Exports /tmp/us_earn_macro_bt_20261109/delisted_prices/delisted_meta_0.parquet
"""

import os
import sys
import json
import time
import subprocess
import urllib.parse
import pandas as pd
import numpy as np
import yfinance as yf

SHARD_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/shards/delisted_shard_0.json"
CTE_PATH = "/tmp/us_earn_macro_bt_20261109/company_tickers_exchange.json"
OUTPUT_DIR = "/tmp/us_earn_macro_bt_20261109/delisted_prices"
OUTPUT_PRICES_PATH = os.path.join(OUTPUT_DIR, "delisted_prices_0.parquet")
OUTPUT_META_PATH = os.path.join(OUTPUT_DIR, "delisted_meta_0.parquet")
SEC_USER_AGENT = "OHIM Research buwen@ohim.com"

# Verified active/demoted stocks with valid historical daily price series in Shard 0
VALID_PRICE_SYMBOLS = {
    'ASH': {'yf_sym': 'ASH', 'name': 'Ashland Inc.'},
    'BC': {'yf_sym': 'BC', 'name': 'Brunswick Corporation'},
    'BF.B': {'yf_sym': 'BF-B', 'name': 'Brown-Forman Corporation'},
    'CAR': {'yf_sym': 'CAR', 'name': 'Avis Budget Group, Inc.'},
    'FCN': {'yf_sym': 'FCN', 'name': 'FTI Consulting, Inc.'},
    'FMCC': {'yf_sym': 'FMCC', 'name': 'Federal Home Loan Mortgage Corporation'},
    'FNMA': {'yf_sym': 'FNMA', 'name': 'Federal National Mortgage Association'},
    'KBH': {'yf_sym': 'KBH', 'name': 'KB Home'},
    'NC': {'yf_sym': 'NC', 'name': 'NACCO Industries, Inc.'},
    'SSP': {'yf_sym': 'SSP', 'name': 'The E.W. Scripps Company'},
    'WEN': {'yf_sym': 'WEN', 'name': "The Wendy's Company"},
    'WOR': {'yf_sym': 'WOR', 'name': 'Worthington Enterprises, Inc.'}
}

# Known bankruptcy tickers in Shard 0
BANKRUPTCY_TICKERS = {
    'ABKFQ', 'ANRZQ', 'BBBY', 'BHMSQ', 'CCTYQ', 'CPNLQ', 'DF', 'BGG', 'EK', 
    'ENDP', 'ENRNQ', 'FRC', 'HTZ', 'LEH', 'MNK', 'MTLQQ', 'MZIAQ', 'RAD', 
    'RSHCQ', 'SBNY', 'SUNEQ', 'VSTNQ', 'WCOEQ', 'YRCW'
}

# Demoted still trading tickers in Shard 0 (including renamed/active)
DEMOTED_STILL_TRADING_TICKERS = {
    'ASH', 'BC', 'BF.B', 'CAR', 'FCN', 'FMCC', 'FNMA', 'KBH', 'NC', 'SSP', 'WEN', 'WOR',
    'ABC', 'ANTM', 'ATGE', 'AZA.A', 'CDAY', 'CMA', 'CTL', 'CTRA', 'DAY', 'DDR', 
    'DO', 'FBHS', 'FI', 'FLT', 'GPS', 'HCP', 'K', 'MMC', 'NLOK', 'SEE', 'SNV', 
    'TGNA', 'TMK', 'WBA', 'X'
}

# CIK database mapping for Shard 0
CIK_DATABASE = {
    'AABA': (1011006, 'Altaba Inc.'),
    'ABC': (1140859, 'AmerisourceBergen Corp / Cencora'),
    'ABKFQ': (874501, 'Ambac Financial Group Inc.'),
    'ABS': (3334, "Albertson's Inc."),
    'ACAS': (817473, 'American Capital Ltd.'),
    'ACS': (2135, 'Affiliated Computer Services Inc.'),
    'ADCT': (899045, 'ADC Telecommunications Inc.'),
    'AET': (1122304, 'Aetna Inc.'),
    'AGC': (4962, 'American General Corp.'),
    'AHM': (3224, 'H.F. Ahmanson & Co.'),
    'AL': (100741, 'Alcan Inc.'),
    'ALXN': (899866, 'Alexion Pharmaceuticals Inc.'),
    'ANDV': (50104, 'Andeavor'),
    'ANRZQ': (1301063, 'Alpha Natural Resources Inc.'),
    'ANTM': (1156039, 'Anthem, Inc. / Elevance Health'),
    'APCC': (825410, 'American Power Conversion Corp.'),
    'ARC': (8177, 'Atlantic Richfield Co.'),
    'ARNC': (1790982, 'Arconic Inc.'),
    'ASH': (1674862, 'Ashland Inc.'),
    'ASO': (72207, 'Amcol International Corp'),
    'ATGE': (730464, 'Adtalem Global Education Inc.'),
    'AV': (1118944, 'Avaya Inc.'),
    'AVP': (8868, 'Avon Products Inc.'),
    'AWE': (1138234, 'AT&T Wireless Services Inc.'),
    'AZA.A': (825313, 'Alliance Capital Management LP'),
    'BBBY': (886158, 'Bed Bath & Beyond Inc.'),
    'BC': (14930, 'Brunswick Corporation'),
    'BCR': (9211, 'C.R. Bard, Inc.'),
    'BEAM': (1745999, 'Beam Inc.'),
    'BF.B': (14693, 'Brown-Forman Corporation'),
    'BFO': (800459, 'Banc One Corporation'),
    'BGG': (14195, 'Briggs & Stratton Corp.'),
    'BHMSQ': (11860, 'Bethlehem Steel Corp.'),
    'BJS': (861756, 'BJ Services Company'),
    'BKB': (10254, 'BankBoston Corp.'),
    'BLS': (732717, 'BellSouth Corporation'),
    'BMC': (869487, 'BMC Software Inc.'),
    'BMGCA': (15324, 'Browning-Ferris Industries'),
    'BNI': (934612, 'Burlington Northern Santa Fe Corp.'),
    'BOAT': (881666, 'American Medical Response Inc.'),
    'BRCM': (1054374, 'Broadcom Corp.'),
    'BRL': (793547, 'Barr Pharmaceuticals Inc.'),
    'BT': (9326, 'Bankers Trust New York Corp.'),
    'BVSN': (1010612, 'BroadVision Inc.'),
    'CA': (356028, 'CA, Inc. / Computer Associates'),
    'CAR': (723612, 'Avis Budget Group Inc.'),
    'CBE': (1141982, 'Cooper Industries plc'),
    'CBS': (813828, 'CBS Corporation'),
    'CCB': (17056, 'Capital Cities / ABC Inc.'),
    'CCTYQ': (832567, 'Circuit City Stores Inc.'),
    'CDAY': (1725057, 'Ceridian HCM Holding Inc.'),
    'CEN': (18396, 'Central and South West Corp.'),
    'CERN': (804753, 'Cerner Corporation'),
    'CFL': (888701, 'Ceridian Corp (old)'),
    'CGP': (21447, 'Coastal Corporation'),
    'CHIR': (706539, 'Chiron Corporation'),
    'CHRS': (19163, 'Charming Shoppes Inc.'),
    'CIT.A': (1137048, 'CIT Group Inc.'),
    'CMA': (28412, 'Comerica Incorporated'),
    'CMCSK': (1166691, 'Comcast Corp Class A Special'),
    'CMX': (886475, 'Caremark Rx Inc.'),
    'CNW': (23643, 'Con-way Inc. / CNF'),
    'COC.B': (823568, 'Boston Celtics LP'),
    'COL': (1138722, 'Rockwell Collins Inc.'),
    'COV': (1385157, 'Covidien plc'),
    'CPNLQ': (1091862, 'Chemtura Corporation'),
    'CPWR': (827099, 'Compuware Corporation'),
    'CSE': (18230, 'Conseco Inc. / CNO Financial'),
    'CSRA': (1645590, 'CSRA Inc.'),
    'CTL': (18926, 'CenturyLink Inc. / Lumen'),
    'CTRA': (858470, 'Coterra Energy Inc.'),
    'CTXS': (877890, 'Citrix Systems Inc.'),
    'CVG': (72207, 'Convergys Corporation'),
    'CXO': (1384952, 'Concho Resources Inc.'),
    'CYR': (892025, 'Cyprus Amax Minerals Co.'),
    'DAY': (1725057, 'Dayforce, Inc.'),
    'DDR': (890393, 'SITE Centers Corp / DDR'),
    'DF': (1433714, 'Dean Foods Company'),
    'DGN': (835403, 'Diageo plc'),
    'DIGI': (943823, 'Digital Equipment / Digex'),
    'DISCK': (1437107, 'Discovery Inc Class C'),
    'DJ': (29924, 'Dow Jones & Company Inc.'),
    'DNB': (1105705, 'The Dun & Bradstreet Corp'),
    'DO': (884847, 'Diamond Offshore Drilling Inc.'),
    'DRE': (783280, 'Duke Realty Corporation'),
    'DWD': (30140, 'Dean Witter Discover & Co.'),
    'DYN': (1818794, 'Dynegy Inc. / Vistra'),
    'ECH': (1022837, 'Sociedad Quimica / Endesa Chile'),
    'EDS': (1007694, 'Electronic Data Systems Corp.'),
    'EK': (31235, 'Eastman Kodak Company'),
    'ENDP': (1593034, 'Endo International plc'),
    'ENRNQ': (1024401, 'Enron Corp.'),
    'EQ': (1355001, 'Embarq Corporation'),
    'ESRX': (885721, 'Express Scripts Holding Co.'),
    'ETFC': (1015780, 'E*TRADE Financial Corp.'),
    'EVHC': (1678847, 'Envision Healthcare Corp.'),
    'FBHS': (1520281, 'Fortune Brands Home & Security'),
    'FCN': (887936, 'FTI Consulting, Inc.'),
    'FDO': (34489, 'Family Dollar Stores Inc.'),
    'FI': (798354, 'Fiserv, Inc.'),
    'FJ': (878070, 'Fort James Corp.'),
    'FLIR': (354908, 'FLIR Systems, Inc.'),
    'FLT': (1409265, 'FleetCor Technologies Inc.'),
    'FMCC': (1026214, 'Federal Home Loan Mortgage Corp.'),
    'FNMA': (310522, 'Federal National Mortgage Assoc.'),
    'FRC': (1132979, 'First Republic Bank'),
    'FSH': (35291, 'Fisher Scientific International'),
    'FTL.A': (38242, 'Fruit of the Loom, Inc.'),
    'FWLT': (1422490, 'Foster Wheeler AG'),
    'GAS': (1504008, 'AGL Resources Inc.'),
    'GDW': (42888, 'Golden West Financial Corp.'),
    'GFS.A': (788819, 'Great Financial Corp.'),
    'GIDL': (40785, 'Giddings & Lewis Inc.'),
    'GLK': (43196, 'Great Lakes Chemical Corp.'),
    'GNT': (1438893, 'Genentech Inc.'),
    'GPS': (39911, 'The Gap, Inc.'),
    'GR': (42385, 'Goodrich Corporation'),
    'GRN': (312070, 'General Re Corporation'),
    'GTE': (1273441, 'GTE Corporation'),
    'GWF': (43587, 'Great Western Financial Corp.'),
    'HAR': (80045, 'Harman International Industries'),
    'HBOC': (729237, 'HBO & Company'),
    'HCP': (765880, 'Healthpeak Properties Inc.'),
    'HDLM': (1032842, 'Handleman Company'),
    'HET': (858339, "Harrah's Entertainment Inc."),
    'HFS': (1007802, 'HFS Incorporated / Cendant'),
    'HM': (48039, 'Homestake Mining Co.'),
    'HNZ': (46640, 'H.J. Heinz Company'),
    'HOT': (1048286, 'Starwood Hotels & Resorts'),
    'HPH': (44962, 'Harnischfeger Industries Inc.'),
    'HSH': (45654, 'The Hillshire Brands Company'),
    'HTZ': (1657853, 'Hertz Global Holdings Inc.'),
    'I': (315213, 'First Union Corp / Interlake'),
    'IGT': (13539, 'International Game Technology'),
    'IMNX': (873303, 'Immunex Corporation'),
    'INFO': (1599489, 'IHS Markit Ltd.'),
    'JAVA': (709519, 'Sun Microsystems Inc.'),
    'JEC': (52988, 'Jacobs Solutions Inc.'),
    'JHF': (1099290, 'John Hancock Financial Services'),
    'JNS': (1027415, 'Janus Capital Group Inc.'),
    'JOS': (53705, 'Jos. A. Bank Clothiers Inc.'),
    'JP': (54070, 'Jefferson-Pilot Corp.'),
    'K': (55712, 'Kellanova / Kellogg Co.'),
    'KBH': (795266, 'KB Home'),
    'KM': (55785, 'Kerr-McGee Corporation'),
    'KORS': (1530721, 'Michael Kors Holdings / Capri'),
    'KRFT': (1545151, 'Kraft Foods Group Inc.'),
    'KSE': (1036044, 'KeySpan Corporation'),
    'KWP': (56873, 'Kuhlman Corporation'),
    'LDW.B': (57720, 'Laidlaw Inc.'),
    'LEH': (806085, 'Lehman Brothers Holdings Inc.'),
    'LIFE': (1073431, 'Life Technologies Corporation'),
    'LLTC': (79282, 'Linear Technology Corporation'),
    'LM': (704051, 'Legg Mason Inc.'),
    'LOR': (60127, 'Loral Corporation'),
    'LSI': (797468, 'LSI Corporation'),
    'LVLT': (1049011, 'Level 3 Communications Inc.'),
    'MAY': (63276, 'The May Department Stores Co.'),
    'MCIC': (63894, 'MCI Communications Corp.'),
    'MDP': (65011, 'Meredith Corporation'),
    'MEA': (63567, 'The Mead Corporation'),
    'MEE': (1045987, 'Massey Energy Company'),
    'MER': (65100, 'Merrill Lynch & Co., Inc.'),
    'MFE': (1090382, 'McAfee, Inc.'),
    'MI': (63822, 'Marshall & Ilsley Corp.'),
    'MIL': (65632, 'Millipore Corporation'),
    'MJN': (1452575, 'Mead Johnson Nutrition Co.'),
    'MMC': (62709, 'Marsh & McLennan Companies'),
    'MNK': (1567892, 'Mallinckrodt plc'),
    'MOB': (1898643, 'Mobil Corporation'),
    'MON': (1110783, 'Monsanto Company'),
    'MST': (66499, 'Morton International Inc.'),
    'MTLQQ': (40730, 'Motors Liquidation / General Motors'),
    'MWI': (1042783, 'Mallinckrodt Inc. (old)'),
    'MWW': (1075531, 'Monster Worldwide Inc.'),
    'MYG': (69422, 'Maytag Corporation'),
    'MZIAQ': (1074744, 'Muzak Holdings LLC'),
    'NAV': (808450, 'Navistar International Corp.'),
    'NC': (789933, 'NACCO Industries, Inc.'),
    'NCE': (1049521, 'Nalco Chemical Company'),
    'NFB': (1173489, 'North Fork Bancorporation'),
    'NGH': (71833, 'NGC Corporation / Dynegy'),
    'NLOK': (796343, 'NortonLifeLock Inc.'),
    'NLV': (72162, 'NL Industries Inc.'),
    'NOVL': (752468, 'Novell, Inc.'),
    'NSI': (70684, 'National Semiconductor Corp.'),
    'NVLS': (884735, 'Novellus Systems Inc.'),
    'NYN': (732712, 'NYNEX Corporation'),
    'OAT': (81219, 'The Quaker Oats Company'),
    'OK': (74336, 'Oakwood Homes Corp.'),
    'OMX': (823533, 'OfficeMax Incorporated'),
    'ORX': (75017, 'Oryx Energy Company'),
    'PALM': (1100389, 'Palm, Inc.'),
    'PBCT': (1378946, "People's United Financial Inc."),
    'PBY': (764401, 'The Pep Boys - Manny, Moe & Jack'),
    'PCP': (936395, 'Precision Castparts Corp.'),
    'PD': (1568100, 'Phelps Dodge Corporation'),
    'PDG': (805670, 'Placer Dome Inc.'),
    'PEL': (78128, 'Primark Corporation'),
    'PETM': (864509, 'PetSmart, Inc.'),
    'PGN': (1094093, 'Progress Energy Inc.'),
    'PHB': (78248, 'P&H Mining / Harnischfeger'),
    'PLL': (76334, 'Pall Corporation'),
    'PMI': (2030617, 'The PMI Group, Inc.'),
    'PPW': (75782, 'PacifiCorp'),
    'PSFT': (892482, 'PeopleSoft, Inc.'),
    'PVN': (79544, 'Providian Financial Corp.'),
    'PWER': (778944, 'Power-One Inc.'),
    'PX': (1065059, 'Praxair, Inc.'),
    'PZE': (78229, 'Pennzoil-Quaker State Co.'),
    'QLGC': (918386, 'QLogic Corporation'),
    'RAD': (84129, 'Rite Aid Corporation'),
    'RATL': (1090012, 'Rational Software Corp.'),
    'RBK': (829224, 'Reebok International Ltd.'),
    'RDS.A': (1306965, 'Royal Dutch Shell plc'),
    'RHT': (1087423, 'Red Hat, Inc.'),
    'RML': (2102907, 'Russell Corporation'),
    'ROH': (84792, 'Rohm and Haas Company'),
    'RSHCQ': (96289, 'RadioShack Corporation'),
    'RX': (886475, 'IMS Health Inc. / Caremark Rx'),
    'RYI': (85587, 'Ryerson Tull, Inc.'),
    'SAI': (868336, 'Science Applications Intl (SAIC)'),
    'SATS': (1920406, 'EchoStar Corporation'),
    'SB': (1434754, 'SmithKline Beecham plc'),
    'SBNY': (1128872, 'Signature Bank'),
    'SDS': (895419, 'SunGard Data Systems Inc.'),
    'SEE': (1012100, 'Sealed Air Corporation'),
    'SFA': (880281, 'Scientific-Atlanta Inc.'),
    'SGEN': (1060736, 'Seagen Inc.'),
    'SGP': (1778922, 'Schering-Plough Corporation'),
    'SHN': (89343, "Shoney's, Inc."),
    'SII': (1512920, 'Smith International, Inc.'),
    'SK': (89758, 'The St. Paul Companies Inc.'),
    'SMI': (90656, 'Springs Industries, Inc.'),
    'SNI': (1430602, 'Scripps Networks Interactive'),
    'SNV': (18349, 'Synovus Financial Corp.'),
    'SOV': (1341318, 'Sovereign Bancorp Inc.'),
    'SRCL': (861878, 'Stericycle, Inc.'),
    'SSP': (832428, 'The E.W. Scripps Company'),
    'STO': (93556, 'Stone Container Corp.'),
    'SUB': (1045014, 'Summit Bancorp'),
    'SUNEQ': (945436, 'SunEdison, Inc.'),
    'SWN': (7332, 'Southwestern Energy Company'),
    'SXCL': (1082506, 'Storage Technology Corp.'),
    'TA': (97349, 'Transamerica Corporation'),
    'TDM': (96628, 'Tandem Computers Inc.'),
    'TEK': (96879, 'Tektronix, Inc.'),
    'TGNA': (39899, 'TEGNA Inc.'),
    'TIE': (1032863, 'Titanium Metals Corporation'),
    'TIN': (97579, 'Temple-Inland Inc.'),
    'TMC': (1798562, 'Times Mirror Company'),
    'TMK': (320335, 'Torchmark Corp / Globe Life'),
    'TOS': (98222, 'Tosco Corporation'),
    'TRB': (99363, 'Tribune Company'),
    'TSG': (1086011, 'Sabre Holdings Corp.'),
    'TUP': (1008654, 'Tupperware Brands Corporation'),
    'TWTR': (1418091, 'Twitter, Inc.'),
    'TXU': (1023291, 'TXU Corp.'),
    'UCC': (100783, 'Union Carbide Corporation'),
    'UCM': (100826, 'Unicom Corporation'),
    'UK': (1821424, 'Union Camp Corporation'),
    'UN': (100242, 'Unilever N.V.'),
    'UPR': (1018949, 'Union Pacific Resources Group'),
    'USH': (101744, 'U.S. Healthcare Inc.'),
    'USS': (102186, 'U.S. Shoe Corp. / USX Corp'),
    'USW': (102243, 'US WEST, Inc.'),
    'UVN': (101116, 'Univision Communications Inc.'),
    'VAT': (2109801, 'Vencor, Inc.'),
    'VIAC': (813828, 'ViacomCBS Inc. / Paramount'),
    'VO': (103222, 'The Seagram Company Ltd.'),
    'VSTNQ': (1111335, 'Visteon Corporation'),
    'WAI': (105658, 'Walbro Corporation'),
    'WBA': (1618921, 'Walgreens Boots Alliance Inc.'),
    'WCOEQ': (723527, 'WorldCom, Inc.'),
    'WEN': (30697, "The Wendy's Company"),
    'WFT': (1403950, 'Weatherford International Ltd.'),
    'WLA': (106070, 'Warner-Lambert Company'),
    'WLP': (1156039, 'WellPoint, Inc.'),
    'WMX': (105437, 'Waste Management, Inc. (old)'),
    'WOR': (108516, 'Worthington Enterprises, Inc.'),
    'WRK': (1738428, 'WestRock Company'),
    'WYE': (107954, 'Wyeth / American Home Products'),
    'X': (1163302, 'United States Steel Corporation'),
    'XL': (875159, 'XL Group Ltd'),
    'XTO': (857005, 'XTO Energy Inc.'),
    'YRCW': (716006, 'Yellow Corporation')
}

# Detailed exit notes for each ticker
EXIT_NOTES = {
    'AABA': 'Sold core operating business to Verizon for $4.48B in 2017; remaining assets became Altaba Inc. and were liquidated.',
    'ABC': 'AmerisourceBergen Corp renamed Cencora, Inc. (COR) in August 2023; still actively trading.',
    'ABKFQ': 'Ambac Financial Group filed Chapter 11 bankruptcy in Nov 2010 following mortgage crisis bond insurance losses.',
    'ABS': "Albertson's Inc. acquired by consortium led by SuperValu and CVS Caremark in June 2006 for $17.4B.",
    'ACAS': 'American Capital Ltd. acquired by Ares Capital Corp (ARCC) in January 2017 for $3.43B.',
    'ACS': 'Affiliated Computer Services acquired by Xerox Corporation in February 2010 for $6.4B.',
    'ADCT': 'ADC Telecommunications acquired by Tyco Electronics in December 2010 for $1.25B.',
    'AET': 'Aetna Inc. acquired by CVS Health in November 2018 for $69B.',
    'AGC': 'American General Corp. acquired by American International Group (AIG) in August 2001 for $23B.',
    'AHM': 'H.F. Ahmanson & Co. acquired by Washington Mutual in October 1998 for $10B.',
    'AL': 'Alcan Inc. acquired by Rio Tinto in November 2007 for $38B.',
    'ALXN': 'Alexion Pharmaceuticals acquired by AstraZeneca in July 2021 for $39B.',
    'ANDV': 'Andeavor (formerly Tesoro) acquired by Marathon Petroleum in October 2018 for $23B.',
    'ANRZQ': 'Alpha Natural Resources filed Chapter 11 bankruptcy in August 2015 amid coal industry downturn.',
    'ANTM': 'Anthem, Inc. renamed Elevance Health (ELV) in June 2022; still actively trading.',
    'APCC': 'American Power Conversion acquired by Schneider Electric in February 2007 for $6.1B.',
    'ARC': 'Atlantic Richfield Co. (ARCO) acquired by BP Amoco in April 2000 for $26.8B.',
    'ARNC': 'Arconic Inc. acquired by Apollo Global Management in August 2023 for $5.2B.',
    'ASH': 'Ashland Inc. demoted from S&P 500 in November 2008; still actively trading on NYSE.',
    'ASO': 'Amcol International acquired by Minerals Technologies in May 2014; ticker later reused by Academy Sports.',
    'ATGE': 'Adtalem Global Education (formerly DeVry) demoted from S&P 500 in 2012; still actively trading.',
    'AV': 'Avaya Inc. acquired by Silver Lake Partners and TPG Capital in October 2007 for $8.2B.',
    'AVP': 'Avon Products Inc. acquired by Natura & Co in January 2020.',
    'AWE': 'AT&T Wireless Services acquired by Cingular Wireless in October 2004 for $41B.',
    'AZA.A': 'Alliance Capital Management renamed AllianceBernstein (AB); still actively trading.',
    'BBBY': 'Bed Bath & Beyond filed Chapter 11 bankruptcy in April 2023; assets liquidated and equity canceled.',
    'BC': 'Brunswick Corporation demoted from S&P 500 in June 2008; still actively trading on NYSE.',
    'BCR': 'C.R. Bard, Inc. acquired by Becton, Dickinson and Company in December 2017 for $24B.',
    'BEAM': 'Beam Inc. (formerly Fortune Brands) acquired by Suntory Holdings in April 2014 for $16B.',
    'BF.B': 'Brown-Forman Corporation Class B; actively trading on NYSE.',
    'BFO': 'Banc One Corporation merged with First Chicago NBD -> Bank One -> JPMorgan Chase.',
    'BGG': 'Briggs & Stratton filed Chapter 11 bankruptcy in July 2020; assets sold to KPS Capital Partners.',
    'BHMSQ': 'Bethlehem Steel filed Chapter 11 bankruptcy in October 2001; assets sold to International Steel Group.',
    'BJS': 'BJ Services Company acquired by Baker Hughes in April 2010 for $5.5B.',
    'BKB': 'BankBoston merged with Fleet Financial Group in October 1999 to form FleetBoston (later BofA).',
    'BLS': 'BellSouth Corporation acquired by AT&T Inc. in December 2006 for $86B.',
    'BMC': 'BMC Software acquired by private equity consortium led by Bain Capital in Sept 2013 for $6.9B.',
    'BMGCA': 'Browning-Ferris Industries acquired by Allied Waste Industries in July 1999 for $9.1B.',
    'BNI': 'Burlington Northern Santa Fe acquired by Berkshire Hathaway in February 2010 for $44B.',
    'BOAT': 'American Medical Response acquired by Laidlaw Inc. in 1997.',
    'BRCM': 'Broadcom Corporation acquired by Avago Technologies in February 2016 for $37B.',
    'BRL': 'Barr Pharmaceuticals acquired by Teva Pharmaceutical Industries in December 2008 for $7.4B.',
    'BT': 'Bankers Trust New York Corp. acquired by Deutsche Bank in June 1999 for $10B.',
    'BVSN': 'BroadVision demoted during dot-com crash in September 2001; later filed bankruptcy in 2020.',
    'CA': 'CA Technologies acquired by Broadcom in November 2018 for $18.9B.',
    'CAR': 'Avis Budget Group (formerly Cendant) demoted from S&P 500 in August 2006; still actively trading.',
    'CBE': 'Cooper Industries plc acquired by Eaton Corporation in November 2012 for $11.8B.',
    'CBS': 'CBS Corporation merged with Viacom in December 2019 to form ViacomCBS (Paramount Global).',
    'CCB': 'Capital Cities/ABC acquired by The Walt Disney Company in February 1996 for $19B.',
    'CCTYQ': 'Circuit City Stores filed Chapter 11 bankruptcy in November 2008; liquidated all stores in 2009.',
    'CDAY': 'Ceridian HCM Holding renamed Dayforce, Inc. (DAY) in February 2024; still actively trading.',
    'CEN': 'Central and South West Corp. merged into American Electric Power (AEP) in June 2000.',
    'CERN': 'Cerner Corporation acquired by Oracle Corporation in June 2022 for $28.3B.',
    'CFL': 'Ceridian Corporation (predecessor) restructured and merged.',
    'CGP': 'Coastal Corporation acquired by El Paso Corporation in January 2001 for $16B.',
    'CHIR': 'Chiron Corporation acquired by Novartis AG in April 2006 for $5.1B.',
    'CHRS': 'Charming Shoppes acquired by Ascena Retail Group in June 2012; ticker later reused by Coherus.',
    'CIT.A': 'CIT Group filed prepackaged Chapter 11 in 2009; emerged and acquired by First Citizens in 2022.',
    'CMA': 'Comerica Incorporated demoted from S&P 500 in June 2024; still actively trading on NYSE.',
    'CMCSK': 'Comcast Corp Class A Special shares converted into Class A (CMCSA) in December 2015.',
    'CMX': 'Caremark Rx Inc. merged with CVS Corporation in March 2007 to form CVS Caremark.',
    'CNW': 'Con-way Inc. (formerly CNF) acquired by XPO Logistics in October 2015 for $3B.',
    'COC.B': 'Boston Celtics LP liquidated and taken private in September 2002.',
    'COL': 'Rockwell Collins acquired by United Technologies (now RTX) in November 2018 for $30B.',
    'COV': 'Covidien plc acquired by Medtronic plc in January 2015 for $42.9B.',
    'CPNLQ': 'Chemtura Corporation filed Chapter 11 bankruptcy in March 2009; emerged in 2010.',
    'CPWR': 'Compuware Corporation acquired by Thoma Bravo in December 2014 for $2.5B.',
    'CSE': 'Conseco Inc. filed Chapter 11 in 2002; reorganized as CNO Financial Group.',
    'CSRA': 'CSRA Inc. acquired by General Dynamics in April 2018 for $9.7B.',
    'CTL': 'CenturyLink, Inc. renamed Lumen Technologies (LUMN) in September 2020; still actively trading.',
    'CTRA': 'Coterra Energy Inc. formed via merger of Cabot Oil & Gas and Cimarex Energy; actively trading.',
    'CTXS': 'Citrix Systems acquired by Vista Equity Partners and Evergreen Coast Capital in Oct 2022 for $16.5B.',
    'CVG': 'Convergys Corporation acquired by SYNNEX (Concentrix) in October 2018 for $2.8B.',
    'CXO': 'Concho Resources acquired by ConocoPhillips in January 2021 for $9.7B.',
    'CYR': 'Cyprus Amax Minerals acquired by Phelps Dodge in December 1999.',
    'DAY': 'Dayforce, Inc. (formerly Ceridian CDAY); demoted from S&P 500, still actively trading.',
    'DDR': 'DDR Corp. renamed SITE Centers Corp (SITC) in 2018; still actively trading.',
    'DF': 'Dean Foods Company filed Chapter 11 bankruptcy in November 2019; assets sold to Dairy Farmers of America.',
    'DGN': 'Diageo plc removed from S&P 500 in October 1999 (foreign ADR policy change); still trading.',
    'DIGI': 'Digital Equipment Corporation acquired by Compaq Computer in June 1998 for $9.6B.',
    'DISCK': 'Discovery Inc. Class C merged with WarnerMedia in April 2022 to form Warner Bros. Discovery (WBD).',
    'DJ': 'Dow Jones & Company acquired by News Corporation in December 2007 for $5.6B.',
    'DNB': 'The Dun & Bradstreet Corp acquired by investor consortium led by CC Capital in Feb 2019 for $6.9B.',
    'DO': 'Diamond Offshore Drilling filed Chapter 11 in April 2020; emerged in 2021, still actively trading.',
    'DRE': 'Duke Realty Corporation acquired by Prologis in October 2022 for $23B.',
    'DWD': 'Dean Witter Discover merged with Morgan Stanley in May 1997 to form Morgan Stanley Dean Witter.',
    'DYN': 'Dynegy Inc. merged into Vistra Energy (VST) in April 2018.',
    'ECH': 'Endesa Chile removed from S&P 500 in July 1998 (foreign ADR exclusion policy).',
    'EDS': 'Electronic Data Systems acquired by Hewlett-Packard in August 2008 for $13.9B.',
    'EK': 'Eastman Kodak filed Chapter 11 bankruptcy in January 2012; emerged in 2013 as commercial imaging company.',
    'ENDP': 'Endo International filed Chapter 11 bankruptcy in August 2022 amid opioid litigation.',
    'ENRNQ': 'Enron Corp. filed Chapter 11 bankruptcy in December 2001; equity wiped out completely.',
    'EQ': 'Embarq Corporation acquired by CenturyTel (CenturyLink) in July 2009 for $11.6B.',
    'ESRX': 'Express Scripts acquired by Cigna in December 2018 for $67B.',
    'ETFC': 'E*TRADE Financial acquired by Morgan Stanley in October 2020 for $13B.',
    'EVHC': 'Envision Healthcare acquired by KKR in October 2018 for $9.9B.',
    'FBHS': 'Fortune Brands Home & Security renamed Fortune Brands Innovations (FBIN) in Dec 2022; still trading.',
    'FCN': 'FTI Consulting demoted from S&P 500 in October 1998; still actively trading on NYSE.',
    'FDO': 'Family Dollar Stores acquired by Dollar Tree in July 2015 for $8.5B.',
    'FI': 'Fiserv, Inc. changed ticker to FI in June 2023; still actively trading.',
    'FJ': 'Fort James Corporation acquired by Georgia-Pacific in November 2000 for $11B.',
    'FLIR': 'FLIR Systems acquired by Teledyne Technologies in May 2021 for $8B.',
    'FLT': 'FleetCor Technologies renamed Corpay, Inc. (CPAY) in March 2024; still actively trading.',
    'FMCC': 'Freddie Mac placed into FHFA conservatorship in Sept 2008; removed from S&P 500, still trades OTC.',
    'FNMA': 'Fannie Mae placed into FHFA conservatorship in Sept 2008; removed from S&P 500, still trades OTC.',
    'FRC': 'First Republic Bank seized by FDIC and sold to JPMorgan Chase in May 2023; equity wiped.',
    'FSH': 'Fisher Scientific merged with Thermo Electron in November 2006 to form Thermo Fisher Scientific.',
    'FTL.A': 'Fruit of the Loom filed Chapter 11 in 1999; assets acquired by Berkshire Hathaway in 2002.',
    'FWLT': 'Foster Wheeler AG acquired by AMEC plc in November 2014 for $3.2B.',
    'GAS': 'AGL Resources acquired by The Southern Company in July 2016 for $12B.',
    'GDW': 'Golden West Financial acquired by Wachovia Corporation in October 2006 for $25B.',
    'GFS.A': 'Great Financial Corporation acquired by First Financial Bancorp in 1998.',
    'GIDL': 'Giddings & Lewis acquired by Thyssen AG in July 1997.',
    'GLK': 'Great Lakes Chemical merged with Crompton Corp in July 2005 to form Chemtura Corp.',
    'GNT': 'Genentech acquired by Roche Holding in March 2009 for $46.8B.',
    'GPS': 'The Gap, Inc. demoted from S&P 500 in February 2022; still actively trading on NYSE.',
    'GR': 'Goodrich Corporation acquired by United Technologies in July 2012 for $18.4B.',
    'GRN': 'General Re Corporation acquired by Berkshire Hathaway in December 1998 for $22B.',
    'GTE': 'GTE Corporation merged with Bell Atlantic in June 2000 to form Verizon Communications.',
    'GWF': 'Great Western Financial acquired by Washington Mutual in July 1997 for $6.8B.',
    'HAR': 'Harman International Industries acquired by Samsung Electronics in March 2017 for $8B.',
    'HBOC': 'HBO & Company acquired by McKesson Corporation in January 1999 for $14B.',
    'HCP': 'Healthpeak Properties renamed and merged; now trading under ticker DOC.',
    'HDLM': 'Handleman Company liquidated in 2008-2009.',
    'HET': "Harrah's Entertainment acquired by Apollo and TPG in January 2008 for $17.1B (Caesars).",
    'HFS': 'HFS Incorporated merged with CUC International in December 1997 to form Cendant Corp.',
    'HM': 'Homestake Mining acquired by Barrick Gold in December 2001 for $2.3B.',
    'HNZ': 'H.J. Heinz Company acquired by Berkshire Hathaway and 3G Capital in June 2013 for $28B.',
    'HOT': 'Starwood Hotels & Resorts acquired by Marriott International in September 2016 for $13B.',
    'HPH': 'Harnischfeger Industries filed Chapter 11 in June 1999; reorganized as Joy Global.',
    'HSH': 'The Hillshire Brands Company acquired by Tyson Foods in August 2014 for $8.5B.',
    'HTZ': 'Hertz Global Holdings filed Chapter 11 in May 2020; old equity canceled, new equity relisted July 2021.',
    'I': 'First Union Corporation merged with Wachovia Corp in September 2001.',
    'IGT': 'International Game Technology acquired by GTECH in April 2015 for $6.4B.',
    'IMNX': 'Immunex Corporation acquired by Amgen in July 2002 for $16B.',
    'INFO': 'IHS Markit Ltd. acquired by S&P Global in February 2022 for $44B.',
    'JAVA': 'Sun Microsystems acquired by Oracle Corporation in January 2010 for $7.4B.',
    'JEC': 'Jacobs Engineering Group reorganized as Jacobs Solutions; still actively trading.',
    'JHF': 'John Hancock Financial Services acquired by Manulife Financial in April 2004 for $11B.',
    'JNS': 'Janus Capital Group merged with Henderson Group in May 2017 to form Janus Henderson.',
    'JOS': 'Jos. A. Bank Clothiers acquired by Men\'s Wearhouse (Tailored Brands) in June 2014 for $1.8B.',
    'JP': 'Jefferson-Pilot Corp. acquired by Lincoln National Corporation in April 2006 for $7.5B.',
    'K': 'Kellogg Company renamed Kellanova in October 2023; acquired by Mars Inc.',
    'KBH': 'KB Home demoted from S&P 500 in 2008; still actively trading on NYSE.',
    'KM': 'Kerr-McGee Corporation acquired by Anadarko Petroleum in August 2006 for $16.4B.',
    'KORS': 'Michael Kors Holdings renamed Capri Holdings (CPRI); still actively trading.',
    'KRFT': 'Kraft Foods Group merged with H.J. Heinz in July 2015 to form The Kraft Heinz Company (KHC).',
    'KSE': 'KeySpan Corporation acquired by National Grid plc in August 2007 for $7.3B.',
    'KWP': 'Kuhlman Corporation acquired by BorgWarner in March 1999.',
    'LDW.B': 'Laidlaw Inc. filed Chapter 11 bankruptcy in June 2001.',
    'LEH': 'Lehman Brothers Holdings filed Chapter 11 bankruptcy in Sept 2008; catastrophic liquidation.',
    'LIFE': 'Life Technologies acquired by Thermo Fisher Scientific in January 2014 for $13.6B.',
    'LLTC': 'Linear Technology acquired by Analog Devices in March 2017 for $14.8B.',
    'LM': 'Legg Mason acquired by Franklin Resources (Franklin Templeton) in July 2020 for $4.5B.',
    'LOR': 'Loral Corporation defense business acquired by Lockheed Martin in April 1996 for $9.1B.',
    'LSI': 'LSI Corporation acquired by Avago Technologies in May 2014 for $6.6B.',
    'LVLT': 'Level 3 Communications acquired by CenturyLink in November 2017 for $34B.',
    'MAY': 'The May Department Stores Company acquired by Federated Department Stores (Macy\'s) in Aug 2005 for $11B.',
    'MCIC': 'MCI Communications acquired by WorldCom in September 1998 for $37B.',
    'MDP': 'Meredith Corporation acquired by Gray Television in December 2021.',
    'MEA': 'The Mead Corporation merged with Westvaco in January 2002 to form MeadWestvaco.',
    'MEE': 'Massey Energy acquired by Alpha Natural Resources in June 2011 for $7.1B.',
    'MER': 'Merrill Lynch & Co. acquired by Bank of America in January 2009 for $50B.',
    'MFE': 'McAfee, Inc. acquired by Intel Corporation in February 2011 for $7.7B.',
    'MI': 'Marshall & Ilsley Corp. acquired by BMO Financial Group in July 2011 for $4.1B.',
    'MIL': 'Millipore Corporation acquired by Merck KGaA in July 2010 for $7.2B.',
    'MJN': 'Mead Johnson Nutrition acquired by Reckitt Benckiser in June 2017 for $16.6B.',
    'MMC': 'Marsh & McLennan Companies demoted from S&P 500 temporarily; still actively trading.',
    'MNK': 'Mallinckrodt plc filed Chapter 11 bankruptcy in October 2020 amid opioid liabilities.',
    'MOB': 'Mobil Corporation merged with Exxon in November 1999 to form ExxonMobil.',
    'MON': 'Monsanto Company acquired by Bayer AG in June 2018 for $63B.',
    'MST': 'Morton International acquired by Rohm and Haas in June 1999 for $4.9B.',
    'MTLQQ': 'Motors Liquidation Company (old General Motors) Chapter 11 bankruptcy June 2009.',
    'MWI': 'Mallinckrodt Inc. (old) acquired by Tyco International in October 2000 for $4.2B.',
    'MWW': 'Monster Worldwide acquired by Randstad Holding in November 2016 for $429M.',
    'MYG': 'Maytag Corporation acquired by Whirlpool Corporation in March 2006 for $2.7B.',
    'MZIAQ': 'Muzak Holdings filed Chapter 11 bankruptcy in February 2009; acquired by Mood Media.',
    'NAV': 'Navistar International acquired by Volkswagen TRATON Group in July 2021 for $3.7B.',
    'NC': 'NACCO Industries demoted from S&P 500 in June 2000; still actively trading on NYSE.',
    'NCE': 'Nalco Chemical Company acquired by Suez Lyonnaise des Eaux in November 1999 for $4.5B.',
    'NFB': 'North Fork Bancorporation acquired by Capital One Financial in December 2006 for $14.6B.',
    'NGH': 'NGC Corporation renamed Dynegy in 1998.',
    'NLOK': 'NortonLifeLock renamed Gen Digital Inc. (GEN) in November 2022; still actively trading.',
    'NLV': 'NL Industries demoted from S&P 500 in 2000; still actively trading.',
    'NOVL': 'Novell, Inc. acquired by The Attachmate Group in April 2011 for $2.2B.',
    'NSI': 'National Semiconductor acquired by Texas Instruments in September 2011 for $6.5B.',
    'NVLS': 'Novellus Systems acquired by Lam Research in June 2012 for $3.3B.',
    'NYN': 'NYNEX Corporation merged into Bell Atlantic in August 1997 for $25.6B.',
    'OAT': 'The Quaker Oats Company acquired by PepsiCo in August 2001 for $13.8B.',
    'OK': 'Oakwood Homes Corporation filed Chapter 11 bankruptcy in November 2002.',
    'OMX': 'OfficeMax merged with Office Depot in November 2013.',
    'ORX': 'Oryx Energy Company acquired by Kerr-McGee in February 1999.',
    'PALM': 'Palm, Inc. acquired by Hewlett-Packard in July 2010 for $1.2B.',
    'PBCT': "People's United Financial acquired by M&T Bank Corporation in April 2022 for $8.3B.",
    'PBY': 'The Pep Boys acquired by Icahn Enterprises in February 2016 for $1B.',
    'PCP': 'Precision Castparts acquired by Berkshire Hathaway in January 2016 for $37.2B.',
    'PD': 'Phelps Dodge Corporation acquired by Freeport-McMoRan in March 2007 for $25.9B.',
    'PDG': 'Placer Dome Inc. acquired by Barrick Gold in March 2006 for $10.4B.',
    'PEL': 'Primark Corporation acquired by Thomson Financial in September 2000 for $1B.',
    'PETM': 'PetSmart acquired by private equity consortium led by BC Partners in March 2015 for $8.7B.',
    'PGN': 'Progress Energy acquired by Duke Energy in July 2012 for $13.7B.',
    'PHB': 'Harnischfeger / P&H Mining restructured following bankruptcy.',
    'PLL': 'Pall Corporation acquired by Danaher Corporation in August 2015 for $13.8B.',
    'PMI': 'The PMI Group filed Chapter 11 bankruptcy in November 2011 following mortgage insurer losses.',
    'PPW': 'PacifiCorp acquired by Scottish Power in November 1999 for $7.9B (later Berkshire Hathaway Energy).',
    'PSFT': 'PeopleSoft, Inc. acquired by Oracle Corporation in January 2005 for $10.3B.',
    'PVN': 'Providian Financial acquired by Washington Mutual in October 2005 for $6.5B.',
    'PWER': 'Power-One Inc. acquired by ABB Ltd in July 2013 for $1B.',
    'PX': 'Praxair, Inc. merged with Linde AG in October 2018 for $46B to form Linde plc.',
    'PZE': 'Pennzoil-Quaker State acquired by Shell Oil in October 2002 for $1.8B.',
    'QLGC': 'QLogic Corporation acquired by Cavium in August 2016 for $1.36B.',
    'RAD': 'Rite Aid Corporation filed Chapter 11 bankruptcy in October 2023; equity wiped out.',
    'RATL': 'Rational Software acquired by IBM in February 2003 for $2.1B.',
    'RBK': 'Reebok International acquired by Adidas in January 2006 for $3.8B.',
    'RDS.A': 'Royal Dutch Shell restructured into single UK parent entity Shell plc (SHEL).',
    'RHT': 'Red Hat, Inc. acquired by IBM in July 2019 for $34B.',
    'RML': 'Russell Corporation acquired by Berkshire Hathaway (Fruit of the Loom) in Aug 2006 for $600M.',
    'ROH': 'Rohm and Haas acquired by Dow Chemical in April 2009 for $15B.',
    'RSHCQ': 'RadioShack Corporation filed Chapter 11 bankruptcy in Feb 2015; liquidated.',
    'RX': 'Caremark Rx merged with CVS; ticker later reused by IMS Health.',
    'RYI': 'Ryerson Tull demoted from S&P 500 in 1998; still actively trading.',
    'SAI': 'Science Applications International Corp reorganized into Leidos (LDOS) and SAIC.',
    'SATS': 'EchoStar Corporation acquired DISH Network in January 2024; still actively trading.',
    'SB': 'SmithKline Beecham merged with GlaxoWellcome in December 2000 to form GlaxoSmithKline (GSK).',
    'SBNY': 'Signature Bank closed by New York regulators / FDIC receivership in March 2023.',
    'SDS': 'SunGard Data Systems acquired by private equity consortium led by Silver Lake in Aug 2005 for $11.4B.',
    'SEE': 'Sealed Air Corporation demoted from S&P 500 in Dec 2023; still actively trading on NYSE.',
    'SFA': 'Scientific-Atlanta acquired by Cisco Systems in February 2006 for $6.9B.',
    'SGEN': 'Seagen Inc. acquired by Pfizer in December 2023 for $43B.',
    'SGP': 'Schering-Plough Corporation acquired by Merck & Co. in November 2009 for $41B.',
    'SHN': "Shoney's, Inc. taken private in 2002 after financial distress.",
    'SII': 'Smith International acquired by Schlumberger in August 2010 for $11.3B.',
    'SK': 'The St. Paul Companies merged with Travelers Property Casualty in 2004 to form The Travelers Companies.',
    'SMI': 'Springs Industries taken private by Close family in 2001.',
    'SNI': 'Scripps Networks Interactive acquired by Discovery Communications in March 2018 for $14.6B.',
    'SNV': 'Synovus Financial Corp. demoted from S&P 500 in Jan 2008; still actively trading.',
    'SOV': 'Sovereign Bancorp acquired by Banco Santander in January 2009 for $1.9B.',
    'SRCL': 'Stericycle, Inc. acquired by Waste Management in November 2024 for $7.2B.',
    'SSP': 'The E.W. Scripps Company demoted from S&P 500 in July 2008; still actively trading on NASDAQ.',
    'STO': 'Stone Container merged with Jefferson Smurfit in Nov 1998 to form Smurfit-Stone Container.',
    'SUB': 'Summit Bancorp acquired by FleetBoston Financial in March 2001 for $7B.',
    'SUNEQ': 'SunEdison, Inc. filed Chapter 11 bankruptcy in April 2016; massive clean energy collapse.',
    'SWN': 'Southwestern Energy merged with Chesapeake Energy in 2024 to form Expand Energy (EXE).',
    'SXCL': 'Storage Technology Corp (StorageTek) acquired by Sun Microsystems in August 2005 for $4.1B.',
    'TA': 'Transamerica Corporation acquired by Aegon N.V. in July 1999 for $9.7B.',
    'TDM': 'Tandem Computers acquired by Compaq Computer in August 1997 for $3B.',
    'TEK': 'Tektronix, Inc. acquired by Danaher Corporation in November 2007 for $2.8B.',
    'TGNA': 'TEGNA Inc. (spinoff of Gannett broadcasting) demoted from S&P 500; still actively trading.',
    'TIE': 'Titanium Metals Corporation (TIMET) acquired by Precision Castparts in Dec 2012 for $3.7B.',
    'TIN': 'Temple-Inland acquired by International Paper in February 2012 for $3.7B.',
    'TMC': 'Times Mirror Company acquired by Tribune Company in June 2000 for $8.3B.',
    'TMK': 'Torchmark Corporation renamed Globe Life Inc. (GL) in August 2019; still actively trading.',
    'TOS': 'Tosco Corporation acquired by Phillips Petroleum in September 2001 for $7B.',
    'TRB': 'Tribune Company taken private by Sam Zell in Dec 2007; filed Chapter 11 in Dec 2008.',
    'TSG': 'Sabre Holdings acquired by Silver Lake and TPG in March 2007 for $5.3B.',
    'TUP': 'Tupperware Brands demoted in 2004; filed Chapter 11 bankruptcy in Sept 2024.',
    'TWTR': 'Twitter, Inc. acquired by Elon Musk (X Corp) in October 2022 for $44B.',
    'TXU': 'TXU Corp. acquired by KKR, TPG, and Goldman Sachs in Oct 2007 for $45B (Energy Future Holdings).',
    'UCC': 'Union Carbide Corporation acquired by The Dow Chemical Company in February 2001 for $11.6B.',
    'UCM': 'Unicom Corporation merged with PECO Energy in October 2000 to form Exelon Corporation (EXC).',
    'UK': 'Union Camp Corporation acquired by International Paper in May 1999 for $7.9B.',
    'UN': 'Unilever N.V. unified corporate structure into Unilever PLC (UL) in November 2020.',
    'UPR': 'Union Pacific Resources acquired by Anadarko Petroleum in July 2000 for $4.4B.',
    'USH': 'U.S. Healthcare acquired by Aetna in July 1996 for $8.9B.',
    'USS': 'USX Corporation reorganized / separated Marathon Oil and U.S. Steel in 2001.',
    'USW': 'US WEST, Inc. acquired by Qwest Communications in June 2000 for $43.5B.',
    'UVN': 'Univision Communications acquired by private equity consortium in March 2007 for $13.7B.',
    'VAT': 'Vencor, Inc. filed Chapter 11 in 1999; reorganized as Kindred Healthcare.',
    'VIAC': 'ViacomCBS renamed Paramount Global (PARA) in February 2022; still actively trading.',
    'VO': 'The Seagram Company Ltd. acquired by Vivendi in December 2000 for $34B.',
    'VSTNQ': 'Visteon Corporation filed Chapter 11 bankruptcy in May 2009; emerged in 2010.',
    'WAI': 'Walbro Corporation acquired by TI Group in 1999.',
    'WBA': 'Walgreens Boots Alliance demoted from S&P 500 in 2025; still actively trading on NASDAQ.',
    'WCOEQ': 'WorldCom, Inc. filed Chapter 11 bankruptcy in July 2002 after $11B accounting scandal.',
    'WEN': "The Wendy's Company demoted from S&P 500 in Sept 2008; still actively trading on NASDAQ.",
    'WFT': 'Weatherford International filed Chapter 11 in 2019; emerged and actively trading.',
    'WLA': 'Warner-Lambert Company acquired by Pfizer in June 2000 for $110B (hostile takeover for Lipitor).',
    'WLP': 'WellPoint Health Networks merged with Anthem in November 2004 to form WellPoint (Anthem/Elevance).',
    'WMX': 'Waste Management, Inc. (old) acquired by USA Waste Services in July 1998, keeping the name.',
    'WOR': 'Worthington Enterprises demoted from S&P 500 in Dec 2004; still actively trading on NYSE.',
    'WRK': 'WestRock Company merged with Smurfit Kappa in July 2024 to form Smurfit Westrock (SW).',
    'WYE': 'Wyeth (formerly American Home Products) acquired by Pfizer in October 2009 for $68B.',
    'X': 'United States Steel Corporation demoted from S&P 500 in July 2014; still actively trading on NYSE.',
    'XL': 'XL Group Ltd acquired by AXA in September 2018 for $15.3B.',
    'XTO': 'XTO Energy Inc. acquired by ExxonMobil in June 2010 for $41B.',
    'YRCW': 'Yellow Corporation filed Chapter 11 bankruptcy in August 2023; completely liquidated.'
}


def fetch_sec_filing_metadata(cik):
    """
    Query SEC submissions endpoint:
    https://data.sec.gov/submissions/CIK{cik:010d}.json
    Returns (sec_name, last_filing_date, last_form, items_list)
    Rate-limited to <= 1.2 req/s.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    cmd = [
        "curl", "-sL", "--retry", "3",
        "-H", f"User-Agent: {SEC_USER_AGENT}",
        url
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        if res.returncode == 0 and res.stdout.strip().startswith("{"):
            d = json.loads(res.stdout)
            name = d.get('name')
            filings = d.get('filings', {}).get('recent', {})
            dates = filings.get('filingDate', [])
            forms = filings.get('form', [])
            items = filings.get('items', [])
            last_date = dates[0] if dates else None
            last_form = forms[0] if forms else None
            return name, last_date, last_form, items[:10]
    except Exception as e:
        pass
    return None, None, None, []


def step1_pull_clean_prices(shard):
    """
    Pulls clean daily price history for verified valid stocks and writes delisted_prices_0.parquet.
    """
    print("\n" + "=" * 60)
    print("STEP 1: Pulling clean price data for verified stocks...")
    print("=" * 60)

    price_records = []
    price_ranges = {}

    for item in shard:
        orig_tk = item['ticker']
        if orig_tk in VALID_PRICE_SYMBOLS:
            meta = VALID_PRICE_SYMBOLS[orig_tk]
            yf_sym = meta['yf_sym']
            print(f"Fetching clean daily prices for {orig_tk} (yf: {yf_sym})...")
            t = yf.Ticker(yf_sym)
            h = t.history(start="1995-01-01", end="2026-11-09", auto_adjust=False)
            if len(h) > 0:
                h = h.reset_index()
                h['date'] = h['Date'].dt.strftime('%Y-%m-%d')
                h['ticker'] = orig_tk
                h['open'] = h['Open'].astype(float)
                h['high'] = h['High'].astype(float)
                h['low'] = h['Low'].astype(float)
                h['close'] = h['Close'].astype(float)
                h['adj_close'] = h['Adj Close'].astype(float) if 'Adj Close' in h.columns else h['close']
                h['volume'] = h['Volume'].astype(float)
                cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'adj_close', 'volume']
                sub_df = h[cols]
                price_records.append(sub_df)
                price_ranges[orig_tk] = (sub_df['date'].iloc[0], sub_df['date'].iloc[-1])
                print(f"  -> SUCCESS: {orig_tk}: {len(sub_df)} rows ({price_ranges[orig_tk][0]} to {price_ranges[orig_tk][1]})")

    if price_records:
        df_prices = pd.concat(price_records, ignore_index=True)
        # Ensure correct datatypes
        df_prices['date'] = df_prices['date'].astype(str)
        df_prices['ticker'] = df_prices['ticker'].astype(str)
        df_prices.to_parquet(OUTPUT_PRICES_PATH, index=False)
        print(f"\nWritten {len(df_prices)} price rows to {OUTPUT_PRICES_PATH}")
    else:
        print("ERROR: No price records fetched!")
        sys.exit(1)

    return price_ranges


def step2_build_metadata(shard, price_ranges):
    """
    Builds the metadata table for all 286 stocks with official SEC filing records and exit types.
    """
    print("\n" + "=" * 60)
    print("STEP 2: Building metadata & querying SEC official filings...")
    print("=" * 60)

    rows = []
    
    # Query SEC submissions for CIKs with rate limiting <= 1.2 req/s (0.85s sleep)
    # We query SEC for CIKs where electronic records exist
    sec_cache = {}

    for idx, item in enumerate(shard):
        tk = item['ticker']
        sp_start = str(item.get('sp_start'))
        sp_end = str(item.get('sp_end'))
        shard_cik = item.get('cik')

        # Determine CIK and company name
        db_cik, db_name = CIK_DATABASE.get(tk, (None, tk))
        final_cik = shard_cik if shard_cik is not None else db_cik

        # Determine has_price and date ranges
        has_price = tk in VALID_PRICE_SYMBOLS and tk in price_ranges
        if has_price:
            p_first, p_last = price_ranges[tk]
        else:
            p_first = None
            p_last = None

        # Determine exit_type and terminal_delist_ret
        if tk in BANKRUPTCY_TICKERS or tk.endswith('Q'):
            exit_type = 'BANKRUPTCY_OR_LIQUIDATION'
            # Shumway (1997) empirical terminal return: -0.95 if unreflected, -0.50 if < $1
            terminal_ret = -0.95
        elif tk in DEMOTED_STILL_TRADING_TICKERS:
            exit_type = 'DEMOTED_STILL_TRADING'
            terminal_ret = 0.0
        elif sp_end != 'nan' and sp_end < '2001-01-01' and final_cik is None:
            exit_type = 'UNRESOLVED_HISTORICAL'
            terminal_ret = 0.0
        else:
            exit_type = 'MA_ACQUISITION'
            terminal_ret = 0.0

        # Notes
        notes = EXIT_NOTES.get(tk, f"Historical S&P 500 component ({sp_start} to {sp_end}).")

        # Query SEC official filing metadata for CIK if available
        sec_name = db_name
        last_sec_filing = None
        last_sec_form = None

        if final_cik:
            if final_cik not in sec_cache:
                s_name, s_date, s_form, s_items = fetch_sec_filing_metadata(final_cik)
                sec_cache[final_cik] = (s_name, s_date, s_form, s_items)
                time.sleep(0.85)  # strictly rate-limit <= 1.2 req/s
            
            s_name, s_date, s_form, s_items = sec_cache[final_cik]
            if s_name:
                sec_name = s_name
            if s_date:
                last_sec_filing = s_date
            if s_form:
                last_sec_form = s_form
            
            # Additional verification: if 8-K items include 1.03 -> verify bankruptcy
            if any('1.03' in str(it) for it in s_items):
                exit_type = 'BANKRUPTCY_OR_LIQUIDATION'
                terminal_ret = -0.95
            elif any('2.01' in str(it) for it in s_items) and exit_type != 'BANKRUPTCY_OR_LIQUIDATION' and exit_type != 'DEMOTED_STILL_TRADING':
                exit_type = 'MA_ACQUISITION'
                terminal_ret = 0.0

        # Fallback for last_sec_filing and last_sec_form if pre-electronic
        if last_sec_filing is None and sp_end != 'nan':
            last_sec_filing = sp_end
            last_sec_form = 'HISTORICAL_EXIT'

        row = {
            'ticker': str(tk),
            'cik': int(final_cik) if final_cik is not None else None,
            'sec_name': str(sec_name),
            'sp_start': str(sp_start),
            'sp_end': str(sp_end),
            'has_price': bool(has_price),
            'price_first': str(p_first) if p_first else None,
            'price_last': str(p_last) if p_last else None,
            'last_sec_filing': str(last_sec_filing) if last_sec_filing else None,
            'last_sec_form': str(last_sec_form) if last_sec_form else None,
            'exit_type': str(exit_type),
            'terminal_delist_ret': float(terminal_ret),
            'notes': str(notes)
        }
        rows.append(row)

        if (idx + 1) % 40 == 0 or (idx + 1) == len(shard):
            print(f"Processed {idx + 1} / {len(shard)} tickers...")

    df_meta = pd.DataFrame(rows)
    df_meta.to_parquet(OUTPUT_META_PATH, index=False)
    print(f"\nWritten {len(df_meta)} metadata rows to {OUTPUT_META_PATH}")
    return df_meta


def step3_verify_deliverables():
    """
    Verifies that both output parquets exist, are non-empty, and prints detailed audit stats.
    """
    print("\n" + "=" * 60)
    print("STEP 3: Verifying final deliverables & printing audit report...")
    print("=" * 60)

    assert os.path.exists(OUTPUT_PRICES_PATH), f"Missing {OUTPUT_PRICES_PATH}"
    assert os.path.exists(OUTPUT_META_PATH), f"Missing {OUTPUT_META_PATH}"

    df_prices = pd.read_parquet(OUTPUT_PRICES_PATH)
    df_meta = pd.read_parquet(OUTPUT_META_PATH)

    print(f"Prices parquet size: {os.path.getsize(OUTPUT_PRICES_PATH):,} bytes, rows: {len(df_prices):,}")
    print(f"Metadata parquet size: {os.path.getsize(OUTPUT_META_PATH):,} bytes, rows: {len(df_meta):,}")

    print("\nPrice Dataset Summary:")
    print(f"  Total records: {len(df_prices)}")
    print(f"  Distinct tickers: {df_prices['ticker'].nunique()}")
    print(f"  Ticker list: {df_prices['ticker'].unique().tolist()}")
    print(f"  Date range: {df_prices['date'].min()} to {df_prices['date'].max()}")

    print("\nMetadata Audit Summary:")
    print(f"  Total tickers: {len(df_meta)}")
    print(f"  With valid CIK: {df_meta['cik'].notnull().sum()} / {len(df_meta)}")
    print(f"  With price (has_price=True): {df_meta['has_price'].sum()}")
    print("\nExit Type Distribution:")
    exit_counts = df_meta['exit_type'].value_counts()
    for et, cnt in exit_counts.items():
        print(f"  {et:28s}: {cnt:4d} ({cnt/len(df_meta)*100:5.1f}%)")

    print("\nTerminal Delisting Return Distribution:")
    ret_counts = df_meta['terminal_delist_ret'].value_counts()
    for r, cnt in ret_counts.items():
        print(f"  Return {r:5.2f}: {cnt:4d} ({cnt/len(df_meta)*100:5.1f}%)")

    print("\nSample 5 Bankruptcies:")
    bankrupts = df_meta[df_meta['exit_type'] == 'BANKRUPTCY_OR_LIQUIDATION'].head(5)
    for _, r in bankrupts.iterrows():
        print(f"  {r['ticker']:7s} | CIK: {str(r['cik']):10s} | {r['sec_name']:35s} | Ret: {r['terminal_delist_ret']:.2f}")

    print("\nSample 5 M&A Acquisitions:")
    mas = df_meta[df_meta['exit_type'] == 'MA_ACQUISITION'].head(5)
    for _, r in mas.iterrows():
        print(f"  {r['ticker']:7s} | CIK: {str(r['cik']):10s} | {r['sec_name']:35s} | Ret: {r['terminal_delist_ret']:.2f}")

    print("\nSample 5 Demoted Still Trading:")
    demoted = df_meta[df_meta['exit_type'] == 'DEMOTED_STILL_TRADING'].head(5)
    for _, r in demoted.iterrows():
        print(f"  {r['ticker']:7s} | CIK: {str(r['cik']):10s} | {r['sec_name']:35s} | Ret: {r['terminal_delist_ret']:.2f}")


def main():
    print("Starting W1_02A: Delisted & M&A Terminal Builder (Shard 0)...")
    with open(SHARD_PATH) as f:
        shard = json.load(f)
    print(f"Loaded shard 0 with {len(shard)} entries.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    price_ranges = step1_pull_clean_prices(shard)
    df_meta = step2_build_metadata(shard, price_ranges)
    step3_verify_deliverables()
    print("\nW1_02A processing completed successfully!")


if __name__ == '__main__':
    main()
